# -*- coding: utf-8 -*-
"""MCP 서버 저장소·도구 커넥터 동기화·실행 경로(2026-09-15). 임시 DB, 네트워크·LLM 없음.

MCP server store, tool-connector sync and the runtime path (2026-09-15). Temp DB; no network or LLM."""
import json
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import httpx
from fastapi import HTTPException

from app import connectors, connectors_api, flow_api_call, flows, flows_api, mcp_api, mcp_client, mcp_servers, tool_contracts
from app.tool_runtime import call_connector
from tests.db_fixture import isolate_db

TOOLS = [
    {"name": "erp_sales_summary", "title": "매출 요약", "description": "지점별 매출",
     "input_schema": {"type": "object", "properties": {"period": {"type": "string", "description": "조회 월", "examples": ["2026-08"]},
                                                        "branch": {"type": "string", "enum": ["all", "서울"], "default": "all"}},
                      "required": ["period"]},
     "annotations": {"readOnlyHint": True}, "kind_default": "read", "unsupported": []},
    {"name": "ems_equipment_control", "title": "설비 제어", "description": "설비 가동·정지",
     "input_schema": {"type": "object", "properties": {"equipment_id": {"type": "string"}, "command": {"type": "string", "enum": ["start", "stop"]},
                                                        "hours": {"type": "integer", "default": 24}},
                      "required": ["equipment_id", "command"]},
     "annotations": {"readOnlyHint": False, "destructiveHint": True}, "kind_default": "action", "unsupported": ["x: 타입이 없어 문자열로 처리"]},
]


def server_body(**over) -> dict:
    d = {"name": "데모 MCP", "description": "가상 ERP·EMS", "category": "erp", "url": "https://mcp.example.invalid/mcp",
         "auth": {"type": "bearer", "key": "secret-key-1", "name": "Authorization"}, "timeout": 20, "enabled": True,
         "tools": [dict(t, kind=t["kind_default"], enabled=True) for t in TOOLS]}
    d.update(over)
    return d


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        isolate_db(self.stack)
        self.addCleanup(self.stack.close)

    def test_normalize_rejects_bad_values(self):
        for body, needle in ((server_body(name=""), "이름"), (server_body(url="ftp://x"), "http"), (server_body(url=""), "주소"),
                             (server_body(auth={"type": "oauth"}), "인증 방식"), (server_body(auth={"type": "bearer", "key": ""}), "인증 키"),
                             (server_body(timeout=0), "타임아웃"), (server_body(tools="no"), "배열"),
                             (server_body(tools=[{"name": "bad name", "input_schema": {}}]), "형식"),
                             (server_body(tools=[{"name": "ok", "kind": "delete"}]), "kind"), (server_body(category="crm"), "분류")):
            with self.assertRaises(connectors.ConnectorValidationError, msg=needle) as ctx:
                mcp_servers.normalize(body)
            self.assertIn(needle, str(ctx.exception))

    def test_create_syncs_tool_connectors_with_deterministic_ids(self):
        s = mcp_servers.create(server_body())
        rows = [c for c in connectors.list_connectors() if c["source"] == "mcp"]
        self.assertEqual(len(rows), 2)
        by_tool = {c["api"]["mcp"]["tool"]: c for c in rows}
        sales = by_tool["erp_sales_summary"]
        self.assertEqual(sales["id"], mcp_servers.tool_connector_id(s["id"], "erp_sales_summary"))
        self.assertTrue(sales["id"].startswith("cn_"))
        self.assertEqual(sales["name"], "데모 MCP › 매출 요약")
        self.assertEqual(sales["kind"], "read")
        self.assertEqual(sales["category"], "erp")
        self.assertTrue(sales["enabled"])
        self.assertEqual(sales["api"]["tool_contract"]["input_schema"]["required"], ["period"])
        self.assertTrue(sales["api"]["tool_contract"]["retry_safe"])
        self.assertNotIn("auth", sales["api"])   # 비밀은 서버 레코드에만 / secrets stay on the server record
        control = by_tool["ems_equipment_control"]
        self.assertEqual(control["kind"], "action")
        self.assertFalse(control["api"]["tool_contract"]["retry_safe"])
        # 입력값 명세: 이름·타입·필수·enum·기본값 / input specs from the schema
        specs = {x["name"]: x for x in flow_api_call.input_specs(control["api"])}
        self.assertEqual(flow_api_call.required_inputs(control["api"]), ["equipment_id", "command", "hours"])
        self.assertTrue(specs["equipment_id"]["required"])
        self.assertEqual(specs["command"]["enum"], ["start", "stop"])
        self.assertEqual(specs["hours"]["default"], "24")
        self.assertEqual(specs["hours"]["type"], "integer")
        self.assertFalse(specs["hours"]["required"])
        pub = connectors.public(control)
        self.assertEqual((pub["source"], pub["server_name"], pub["tool"], pub["title"]), ("mcp", "데모 MCP", "ems_equipment_control", "설비 제어"))
        self.assertEqual(pub["unsupported"], ["x: 타입이 없어 문자열로 처리"])
        # 목록 응답은 키를 가린다 / the list payload masks the key
        rec = mcp_servers.editor_record(s)
        self.assertEqual(rec["auth"]["key"], connectors.SECRET_MASK)
        self.assertEqual(rec["tool_count"], 2)
        self.assertEqual(connectors.secret_of(sales), "secret-key-1")
        with self.assertRaises(connectors.ConnectorValidationError):   # 같은 이름 거부(2026-09-16) / duplicate server names are rejected
            mcp_servers.create(server_body())
        mcp_servers.update(s["id"], {**rec, "description": "다시 저장"})   # 자기 이름은 그대로 저장 가능 / re-saving under its own name is fine

    def test_update_removes_gone_tools_disables_with_server_and_keeps_masked_key(self):
        s = mcp_servers.create(server_body())
        sid = s["id"]
        body = mcp_servers.editor_record(s)   # 마스킹된 키 그대로 → 저장 키 유지 / masked key echoed → stored key kept
        body["tools"] = [body["tools"][0]]
        body["enabled"] = False
        body["name"] = "새 이름"
        s2 = mcp_servers.update(sid, body)
        self.assertEqual(s2["auth"]["key"], "secret-key-1")
        rows = [c for c in connectors.list_connectors() if c["source"] == "mcp"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "새 이름 › 매출 요약")
        self.assertFalse(rows[0]["enabled"])   # 서버 비활성 → 도구도 비활성 / disabled server → disabled tools
        bad = {**body, "auth": {"type": "bearer", "key": connectors.SECRET_MASK + "x"}}
        with self.assertRaises(connectors.ConnectorValidationError):
            mcp_servers.update(sid, bad)
        # 도구 사용 해제만으로도 커넥터가 비활성 / a disabled tool alone disables its connector
        body["enabled"] = True
        body["tools"][0]["enabled"] = False
        mcp_servers.update(sid, body)
        self.assertFalse(connectors.get_connector(rows[0]["id"])["enabled"])

    def test_delete_server_removes_tools_and_api_guards(self):
        s = mcp_servers.create(server_body())
        tool_id = mcp_servers.tool_connector_id(s["id"], "erp_sales_summary")
        with self.assertRaises(connectors.ConnectorValidationError):
            connectors.update(tool_id, {"name": "x", "description": "y", "api": {"url": "https://x"}})
        with self.assertRaises(HTTPException) as ctx:
            connectors_api.remove(tool_id, "")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(mcp_servers.delete(s["id"]), 2)
        self.assertEqual([c for c in connectors.list_connectors() if c["source"] == "mcp"], [])
        self.assertEqual(mcp_servers.delete("mcp_missing"), -1)
        self.assertEqual(len(connectors_api.list_all("")["mcp_servers"]), 0)

    def test_merge_tools_keeps_admin_settings_and_reports_removed(self):
        prev = [{"name": "a", "kind": "read", "enabled": False, "description_override": "내 설명"}, {"name": "gone", "kind": "read"}]
        merged, gone = mcp_servers.merge_tools([{"name": "a", "kind_default": "action"}, {"name": "new", "kind_default": "action"}], prev)
        self.assertEqual(gone, ["gone"])
        self.assertEqual((merged[0]["kind"], merged[0]["enabled"], merged[0]["description_override"]), ("read", False, "내 설명"))
        self.assertEqual((merged[1]["kind"], merged[1]["enabled"]), ("action", True))

    def test_discover_and_call_tool_through_transport(self):
        def handle(request):
            body = json.loads(request.content)
            if body.get("id") is None:
                return httpx.Response(202)
            m = body["method"]
            if m == "initialize":
                res = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "Fake", "version": "1"}}
            elif m == "tools/list":
                res = {"tools": [{"name": "erp_sales_summary", "description": "d", "inputSchema": TOOLS[0]["input_schema"],
                                  "annotations": {"readOnlyHint": True}}, {"name": "bad name"}]}
            else:
                self.assertEqual(request.headers["authorization"], "Bearer secret-key-1")
                res = {"content": [{"type": "text", "text": "매출 요약"}], "structuredContent": {"total": 5, "branch": body["params"]["arguments"]["branch"]}}
            return httpx.Response(200, headers={"content-type": "application/json"}, json={"jsonrpc": "2.0", "id": body["id"], "result": res})
        transport = httpx.MockTransport(handle)
        with patch.object(flow_api_call, "check_url"):
            out = mcp_servers.discover("https://mcp.example.invalid/mcp", {"type": "bearer", "key": "secret-key-1"}, 10, transport=transport)
            self.assertEqual(out["server_info"]["name"], "Fake")
            self.assertEqual([t["name"] for t in out["tools"]], ["erp_sales_summary"])
            self.assertEqual(out["skipped"], 1)
            self.assertEqual(out["tools"][0]["kind_default"], "read")
            s = mcp_servers.create(server_body(tools=[dict(out["tools"][0], kind="read", enabled=True)]))
            conn = connectors.get_connector(mcp_servers.tool_connector_id(s["id"], "erp_sales_summary"))
            r = mcp_servers.call_tool(conn, {"period": "2026-08", "branch": "서울", "empty": ""}, transport=transport)
        self.assertTrue(r["ok"])
        self.assertEqual(r["status"], 200)
        self.assertEqual(r["outputs"], {"total": 5, "branch": "서울"})
        self.assertEqual(r["request"]["arguments"], {"period": "2026-08", "branch": "서울"})   # 빈 값은 보내지 않음 / blanks dropped
        self.assertTrue(r["url"].endswith("#erp_sales_summary"))
        self.assertNotIn("secret-key-1", json.dumps(r))
        # 서버 비활성 → 실패 결과 / a disabled server fails the call
        mcp_servers.update(s["id"], {**mcp_servers.editor_record(s), "enabled": False})
        self.assertIn("비활성", mcp_servers.call_tool(connectors.get_connector(conn["id"]), {}, transport=transport)["error"])
        # 서버 삭제 뒤 남은 커넥터 사본 → 안내 / a stale connector copy after the server is gone
        mcp_servers.delete(s["id"])
        self.assertIn("삭제", mcp_servers.call_tool(conn, {}, transport=transport)["error"])


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        isolate_db(self.stack)
        self.addCleanup(self.stack.close)
        self.server = mcp_servers.create(server_body())
        self.control = connectors.get_connector(mcp_servers.tool_connector_id(self.server["id"], "ems_equipment_control"))
        self.sales = connectors.get_connector(mcp_servers.tool_connector_id(self.server["id"], "erp_sales_summary"))

    async def test_call_connector_dispatches_to_mcp_with_coerced_inputs_and_defaults(self):
        seen = {}

        def fake_call(connector, inputs, *, keep_body=8000, transport=None):
            seen["inputs"] = inputs
            return {"ok": True, "status": 200, "elapsed_ms": 3, "url": "u#t", "attempts": 1, "result_text": "ok", "json": {"status": "running"},
                    "result": {"status": "running"}, "outputs": {"status": "running"}, "error": None, "request": {}}
        with patch.object(mcp_servers, "call_tool", side_effect=fake_call), patch.object(flow_api_call, "call", side_effect=AssertionError("HTTP 경로 금지")):
            inputs, missing, _ = tool_contracts.prepare_workflow_inputs(self.control, {"equipment_id": "EQ-1", "command": "start", "hours": "12"})
            self.assertEqual(missing, [])
            r = await call_connector(self.control, "설비 가동", "7", inputs)
        self.assertTrue(r["ok"])
        self.assertEqual(seen["inputs"], {"equipment_id": "EQ-1", "command": "start", "hours": 12})   # 문자열 → 정수, 기본값 유지 / text → int
        with self.assertRaises(Exception):   # enum 위반은 호출 전에 막힌다 / an enum violation never reaches the server
            tool_contracts.prepare_workflow_inputs(self.control, {"equipment_id": "EQ-1", "command": "explode"})
        _, missing, _ = tool_contracts.prepare_workflow_inputs(self.control, {"command": "start"})
        self.assertEqual(missing, ["equipment_id"])

    async def test_run_api_node_with_mcp_tool_reports_source_outputs_and_failures(self):
        node = {"agent": "api", "resources": [self.sales["id"]], "instruction": "", "prompt": "서울 매출",
                "input_bindings": {"period": {"mode": "value", "value": "2026-08"}, "branch": {"mode": "value", "value": "서울"}}}
        results = [{"ok": True, "status": 200, "elapsed_ms": 5, "url": "u#erp_sales_summary", "attempts": 1, "result_text": "매출 요약 문장",
                    "json": {"total": 9, "token": "leak-secret-key-1"}, "result": {"total": 9}, "outputs": {"total": 9}, "error": None, "request": {}},
                   {"ok": False, "status": 200, "elapsed_ms": 5, "url": "u#erp_sales_summary", "attempts": 1, "result_text": "필수 인자가 없습니다",
                    "json": None, "result": None, "outputs": {}, "error": "필수 인자가 없습니다", "request": {}}]
        with patch.object(flows, "_api_candidates", return_value=([self.sales], None)), \
             patch.object(flows.llm, "generate", side_effect=AssertionError("LLM 불필요")), \
             patch.object(mcp_servers, "call_tool", side_effect=results):
            done = await flows._run_api_node(node, "매출 알려줘", [], "7")
            failed = await flows._run_api_node(node, "매출 알려줘", [], "7")
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["label"], "데모 MCP › 매출 요약")
        self.assertEqual(done["outputs"], {"total": 9})
        self.assertEqual(done["extras"]["connector"]["source"], "mcp")
        self.assertEqual(done["extras"]["connector"]["inputs"], {"period": "2026-08", "branch": "서울"})
        self.assertEqual(done["data"]["token"], "••••••")            # 응답 마스킹 / response redaction
        self.assertNotIn("secret-key-1", json.dumps(done, ensure_ascii=False))
        self.assertEqual(failed["status"], "failed")
        self.assertTrue(failed["text"].startswith("MCP 도구 호출 실패"))

    async def test_group_palette_and_flow_summary_carry_mcp_labels(self):
        geff = {"nodes": {self.sales["id"]: 1, self.control["id"]: 1}}
        pal = {c["id"]: c for c in flows_api._group_connectors(geff)}
        self.assertEqual(pal[self.sales["id"]]["source"], "mcp")
        self.assertEqual(pal[self.sales["id"]]["server"], "데모 MCP")
        self.assertEqual(pal[self.sales["id"]]["tool"], "매출 요약")
        self.assertEqual(pal[self.control["id"]]["unsupported"], ["x: 타입이 없어 문자열로 처리"])
        self.assertEqual([x["name"] for x in pal[self.sales["id"]]["inputs"]], ["period", "branch"])
        flow = {"id": "f1", "name": "F", "stages": [{"nodes": [{"agent": "api", "resources": [self.sales["id"]], "instruction": "",
                                                                    "input_bindings": {"branch": {"mode": "ask", "value": ""}}}]}]}
        with patch.object(flows, "_flow_ai_summary", return_value="요약"):
            summary = flows.flow_summary(flow)
        self.assertEqual(summary["flow"][0]["labels"], ["데모 MCP › 매출 요약"])
        srcs = {x["name"]: x["source"] for x in summary["inputs"]}
        self.assertEqual(srcs, {"period": "auto", "branch": "ask"})

    def test_mcp_api_usage_and_discover_validation(self):
        with self.assertRaises(HTTPException) as ctx:
            mcp_api.discover(mcp_api.DiscoverIn(url="ftp://bad", auth={}, timeout=5))
        self.assertEqual(ctx.exception.status_code, 422)
        with self.assertRaises(HTTPException) as ctx:
            mcp_api.get_one("mcp_missing", "")
        self.assertEqual(ctx.exception.status_code, 404)
        with patch.object(flows, "get_flows", return_value=[{"id": "f1", "name": "흐름", "stages": [{"nodes": [{"agent": "api", "resources": [self.sales["id"]]}]}]}]):
            rows = mcp_api.usage(self.server["id"], "")["workflows"]
        self.assertEqual(rows, [{"id": "f1", "name": "흐름", "stage": 1, "task": 1, "tool": "매출 요약"}])
        with self.assertRaises(HTTPException) as ctx:
            mcp_api.list_all("42")   # 슈퍼관리자 전용 / super-admin only
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
