# -*- coding: utf-8 -*-
"""업무 자동화 에이전트 저장소·권한 축·API(2026-09-22). 임시 DB, 네트워크·LLM 없음.

Work-automation agent store, permission axis and API (2026-09-22). Temp DB; no network or LLM."""
import json
import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import httpx
from fastapi import HTTPException

from app import (access, builtin_agents, catalog, connectors, flow_api_call, mcp_servers, mock_mcosmetic, mock_mcosmetic_mcp, work_agents,
                 work_agents_api)
from tests.db_fixture import isolate_db


def api_body(**over) -> dict:
    d = {"name": "사내 ERP", "description": "매출·재고 조회", "method": "api", "enabled": True,
         "config": {"base_url": "https://erp.example.invalid/api/", "version": "v1", "timeout": 20,
                    "auth": {"type": "bearer", "key": "secret-key-1", "name": "Authorization"},
                    "endpoints": [
                        {"name": "GetSalesSummary", "method": "GET", "path": "/sales/summary", "description": "매출 요약",
                         "params": [{"name": "period", "type": "string", "required": True, "description": "조회 월", "example": "2026-08"},
                                    {"name": "branch", "type": "string", "required": False}]},
                        {"name": "GetInventory", "method": "GET", "path": "/inventory/{sku}", "params": []},
                        {"name": "ApproveOrder", "method": "POST", "path": "/orders/{order_id}/approve",
                         "params": [{"name": "qty", "type": "integer", "required": False}]}]}}
    d.update(over)
    return d


def with_endpoint(**ep) -> dict:
    body = api_body()
    body["config"]["endpoints"] = [dict(body["config"]["endpoints"][0], **ep)]
    return body


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        isolate_db(self.stack)
        self.addCleanup(self.stack.close)
        self.addCleanup(access.rebuild_universe)

    def test_normalize_rejects_bad_values(self):
        cases = [
            (api_body(name=""), "이름"), (api_body(method="rpc"), "연결 방식"),
            (api_body(config=dict(api_body()["config"], base_url="")), "기본 주소"),
            (api_body(config=dict(api_body()["config"], base_url="ftp://x")), "http"),
            (api_body(config=dict(api_body()["config"], auth={"type": "oauth"})), "인증 방식"),
            (api_body(config=dict(api_body()["config"], auth={"type": "bearer", "key": ""})), "인증 키"),
            (api_body(config=dict(api_body()["config"], timeout=0)), "타임아웃"),
            (with_endpoint(name="bad name"), "엔드포인트 이름"), (with_endpoint(name=""), "이름이 비어"),
            (with_endpoint(path="sales"), "/ 로 시작"), (with_endpoint(method="FETCH"), "메서드"), (with_endpoint(kind="delete"), "종류"),
            (with_endpoint(params=[{"name": "bad-name"}]), "입력값 이름"), (with_endpoint(params=[{"name": "a", "type": "date"}]), "타입"),
            (with_endpoint(params=[{"name": "a"}, {"name": "a"}]), "중복"),
            ({"name": "m", "method": "mcp", "config": {"url": "", "auth": {"type": "none"}}}, "MCP 서버 주소"),
            ({"name": "m", "method": "mcp", "config": {"url": "https://x.invalid/mcp", "tools": "no"}}, "배열"),
        ]
        for body, needle in cases:
            with self.assertRaises(connectors.ConnectorValidationError, msg=needle) as ctx:
                work_agents.normalize(body)
            self.assertIn(needle, str(ctx.exception))
        dup = api_body()
        dup["config"]["endpoints"].append(dict(dup["config"]["endpoints"][0]))
        with self.assertRaises(connectors.ConnectorValidationError) as ctx:
            work_agents.normalize(dup)
        self.assertIn("중복", str(ctx.exception))

    def test_create_adds_permission_leaf_masks_key_and_derives_schema(self):
        a = work_agents.create(api_body())
        self.assertTrue(a["id"].startswith("agent_"))
        self.assertEqual(a["config"]["base_url"], "https://erp.example.invalid/api")   # 끝의 / 정리 / trailing slash trimmed
        self.assertEqual(a["config"]["auth"]["key"], "secret-key-1")
        rec = work_agents.editor_record(a)
        self.assertEqual(rec["config"]["auth"]["key"], connectors.SECRET_MASK)
        eps = {e["name"]: e for e in rec["config"]["endpoints"]}
        self.assertEqual(eps["GetSalesSummary"]["input_schema"],
                         {"type": "object", "properties": {"period": {"type": "string", "description": "조회 월", "examples": ["2026-08"]},
                                                           "branch": {"type": "string"}}, "required": ["period"]})
        # 경로 변수는 표에 없어도 필수 입력값으로 생긴다 / a path variable becomes a required input even when the table omits it
        self.assertEqual([(p["name"], p["required"]) for p in eps["GetInventory"]["params"]], [("sku", True)])
        self.assertEqual(eps["GetInventory"]["locations"], {"sku": "path"})
        self.assertEqual(eps["ApproveOrder"]["locations"], {"qty": "body", "order_id": "path"})
        self.assertEqual((eps["GetSalesSummary"]["kind"], eps["ApproveOrder"]["kind"]), ("read", "action"))
        self.assertEqual(rec["count"], 3)
        access.rebuild_universe()
        leaves = {c["id"]: c["label"] for n in access.PV_TREE for m in n.get("children", []) if m["id"] == "p_auto" for c in m["children"]}
        self.assertEqual(leaves.get(a["id"]), "사내 ERP")
        self.assertIn("agent_email", leaves)
        self.assertTrue(catalog.domain_readable({"nodes": {a["id"]: 1}}, "p_auto"))
        self.assertFalse(catalog.domain_readable({"nodes": {"agent_other": 1}}, "p_auto"))
        with self.assertRaises(connectors.ConnectorValidationError):
            work_agents.create(api_body(name="사내 erp"))   # 이름 중복(대소문자 무시) / duplicate name, case-insensitive

    def test_update_keeps_secret_behind_mask_and_delete_removes_leaf(self):
        a = work_agents.create(api_body())
        masked = work_agents.editor_record(a)
        masked["name"] = "사내 ERP 2"
        masked["config"]["endpoints"][0]["sample"] = '{"ok": true}'
        b = work_agents.update(a["id"], masked)
        self.assertEqual(b["config"]["auth"]["key"], "secret-key-1")
        self.assertEqual(b["config"]["endpoints"][0]["sample"], '{"ok": true}')
        self.assertEqual(b["created_at"], a["created_at"])
        cleared = work_agents.editor_record(b)
        cleared["config"]["auth"] = {"type": "none", "key": ""}
        self.assertEqual(work_agents.update(a["id"], cleared)["config"]["auth"]["type"], "none")
        with self.assertRaises(connectors.ConnectorValidationError):
            work_agents.update(a["id"], dict(work_agents.editor_record(work_agents.get_agent(a["id"])),
                                             config={**work_agents.get_agent(a["id"])["config"], "auth": {"type": "bearer", "key": connectors.SECRET_MASK}}))
        self.assertTrue(work_agents.delete(a["id"]))
        self.assertFalse(work_agents.delete(a["id"]))
        access.rebuild_universe()
        leaves = [c["id"] for n in access.PV_TREE for m in n.get("children", []) if m["id"] == "p_auto" for c in m["children"]]
        self.assertNotIn(a["id"], leaves)

    def test_test_endpoint_fills_path_query_and_json_body(self):
        cfg = work_agents.normalize(api_body())["config"]
        eps = {e["name"]: e for e in cfg["endpoints"]}
        seen = []

        def run(**kw):
            client = MagicMock()
            client.__enter__.return_value = client
            def request(method, url, headers=None, params=None, **rest):
                seen.append({"method": method, "url": url, "headers": headers, "params": params, **rest})
                return httpx.Response(200, headers={"content-type": "application/json"}, json={"data": {"id": "A"}})
            client.request.side_effect = request
            with patch.object(flow_api_call, "check_url"), patch.object(flow_api_call.httpx, "Client", return_value=client):
                return work_agents.test_endpoint(cfg, kw["ep"], kw["values"])

        r = run(ep=eps["GetInventory"], values={"sku": "SKU 10/1"})
        self.assertTrue(r["ok"])
        self.assertEqual(seen[-1]["url"], "https://erp.example.invalid/api/inventory/SKU%2010%2F1")
        self.assertEqual(seen[-1]["headers"]["Authorization"], "Bearer secret-key-1")
        self.assertEqual(r["request"]["headers"]["Authorization"], "••••••")   # 응답에는 비밀이 없다 / no secret in the reply
        self.assertEqual(r["json"], {"data": {"id": "A"}})
        r = run(ep=eps["GetSalesSummary"], values={"period": "2026-08", "branch": ""})
        self.assertEqual(seen[-1]["params"], [("period", "2026-08")])
        r = run(ep=eps["ApproveOrder"], values={"order_id": "O-1", "qty": "3"})
        self.assertEqual(seen[-1]["method"], "POST")
        self.assertEqual(seen[-1]["json"], {"qty": 3})
        self.assertIn("경로 변수", run(ep=eps["GetInventory"], values={})["error"])
        self.assertIn("필수 입력값", run(ep=eps["GetSalesSummary"], values={})["error"])

    def test_mcp_agent_discover_and_store(self):
        def handle(request):
            body = json.loads(request.content)
            if body.get("id") is None:
                return httpx.Response(202)
            if body["method"] == "initialize":
                res = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "Fake", "version": "1"}}
            else:
                self.assertEqual(request.headers["authorization"], "Bearer secret-key-1")
                res = {"tools": [{"name": "erp_sales_summary", "description": "d", "annotations": {"readOnlyHint": True},
                                  "inputSchema": {"type": "object", "properties": {"period": {"type": "string"}}, "required": ["period"]}},
                                 {"name": "ems_control", "inputSchema": {"type": "object", "properties": {}}}, {"name": "bad name"}]}
            return httpx.Response(200, headers={"content-type": "application/json"}, json={"jsonrpc": "2.0", "id": body["id"], "result": res})
        with patch.object(flow_api_call, "check_url"):
            out = work_agents.discover_tools("https://mcp.example.invalid/mcp", {"type": "bearer", "key": "secret-key-1", "name": "Authorization"}, 10,
                                             [{"name": "ems_control", "kind": "read", "enabled": False}], transport=httpx.MockTransport(handle))
        self.assertEqual([t["name"] for t in out["tools"]], ["erp_sales_summary", "ems_control"])
        self.assertEqual((out["tools"][0]["kind"], out["tools"][1]["kind"], out["tools"][1]["enabled"]), ("read", "read", False))   # 관리자 설정 유지 / admin settings kept
        self.assertEqual(out["skipped"], 1)
        a = work_agents.create({"name": "설비 MCP", "method": "mcp",
                                "config": {"url": "https://mcp.example.invalid/mcp", "timeout": 10, "server_info": out["server_info"],
                                           "auth": {"type": "bearer", "key": "secret-key-1"}, "tools": out["tools"], "fetched_at": out["fetched_at"]}})
        rec = work_agents.editor_record(a)
        self.assertEqual(rec["count"], 1)   # 사용 중인 도구만 센다 / enabled tools only
        self.assertEqual(rec["config"]["auth"]["key"], connectors.SECRET_MASK)
        self.assertEqual(rec["config"]["tools"][0]["input_schema"]["required"], ["period"])
        # 커넥터 행·MCP 서버 목록에는 들어가지 않는다(관리 센터와 분리) / never leaks into connector rows or the Admin Center MCP list
        self.assertEqual(connectors.list_connectors(), [])
        self.assertEqual(mcp_servers.list_servers(), [])

    def test_demo_fill_data_is_valid(self):
        demo = work_agents_api._demo()
        api = work_agents.normalize({**demo["api"], "method": "api"})
        self.assertEqual([e["name"] for e in api["config"]["endpoints"]], ["GetSalesSummary", "GetInventory", "ApproveOrder"])
        self.assertEqual(api["config"]["base_url"], "{{base_url}}/mock/erp/v1")
        mcp = work_agents.normalize({**demo["mcp"], "method": "mcp"})
        self.assertEqual(mcp["config"]["url"], "{{base_url}}/mock/mcp")


class ApiGatingTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        isolate_db(self.stack)
        self.addCleanup(self.stack.close)
        self.addCleanup(access.rebuild_universe)

    def _eff(self, nodes: dict) -> dict:
        return {"no": 7, "menus": {}, "nodes": nodes, "mgmt": {"p_auto": any(v >= 2 for v in nodes.values())}, "read": {}}

    def test_super_and_managers(self):
        body = work_agents_api.AgentIn(**api_body())
        rec = work_agents_api.create(body)   # 슈퍼(빈 acting id) / super admin
        self.assertEqual(rec["config"]["auth"]["key"], connectors.SECRET_MASK)
        listed = work_agents_api.list_all("")
        self.assertEqual([a["id"] for a in listed["agents"]], [rec["id"]])
        self.assertEqual([b["id"] for b in listed["builtin"]], ["agent_email", "agent_edu"])
        self.assertIn("demo", listed)
        with patch.object(access, "effective", return_value=self._eff({"agent_email": 1})):
            with self.assertRaises(HTTPException) as ctx:
                work_agents_api.list_all("7")
            self.assertEqual(ctx.exception.status_code, 403)
        # 이메일 에이전트만 관리: 목록은 보이지만 새 등록·남의 에이전트 수정은 403 / manages email only: may list, cannot create or edit others
        with patch.object(access, "effective", return_value=self._eff({"agent_email": 2})):
            self.assertEqual(len(work_agents_api.list_all("7")["agents"]), 1)
            with self.assertRaises(HTTPException) as ctx:
                work_agents_api.create(work_agents_api.AgentIn(**api_body(name="다른 ERP"), acting_user_id="7"))
            self.assertEqual(ctx.exception.status_code, 403)
            with self.assertRaises(HTTPException) as ctx:
                work_agents_api.update(rec["id"], work_agents_api.AgentIn(**api_body(), acting_user_id="7"))
            self.assertEqual(ctx.exception.status_code, 403)
        # p_auto 앵커 관리: 등록·수정·삭제 전부 / manage on the anchor: create, update and delete
        with patch.object(access, "effective", return_value=self._eff({"p_auto": 2, rec["id"]: 2})):
            made = work_agents_api.create(work_agents_api.AgentIn(**api_body(name="다른 ERP"), acting_user_id="7"))
            self.assertEqual(made["name"], "다른 ERP")
            upd = work_agents_api.update(rec["id"], work_agents_api.AgentIn(**work_agents.editor_record(work_agents.get_agent(rec["id"])), acting_user_id="7"))
            self.assertEqual(upd["config"]["auth"]["key"], connectors.SECRET_MASK)
            self.assertEqual(work_agents.get_agent(rec["id"])["config"]["auth"]["key"], "secret-key-1")
            self.assertEqual(work_agents_api.remove(rec["id"], "7"), {"ok": True})
        with self.assertRaises(HTTPException) as ctx:
            work_agents_api.get_one(rec["id"], "")
        self.assertEqual(ctx.exception.status_code, 404)
        with self.assertRaises(HTTPException) as ctx:
            work_agents_api.create(work_agents_api.AgentIn(**with_endpoint(name="bad name")))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_test_route_restores_masked_key(self):
        rec = work_agents_api.create(work_agents_api.AgentIn(**api_body()))
        client = MagicMock()
        client.__enter__.return_value = client
        client.request.return_value = httpx.Response(200, headers={"content-type": "application/json"}, json={"ok": 1})
        with patch.object(flow_api_call, "check_url"), patch.object(flow_api_call.httpx, "Client", return_value=client):
            out = work_agents_api.test(work_agents_api.TestIn(agent_id=rec["id"], config=rec["config"],
                                                              endpoint=rec["config"]["endpoints"][0], values={"period": "2026-08"}))
        self.assertTrue(out["ok"])
        self.assertEqual(client.request.call_args.kwargs["headers"]["Authorization"], "Bearer secret-key-1")
        with self.assertRaises(HTTPException) as ctx:
            work_agents_api.test(work_agents_api.TestIn(agent_id="agent_missing", config=rec["config"], endpoint=rec["config"]["endpoints"][0]))
        self.assertEqual(ctx.exception.status_code, 404)


class BuiltinAgentTests(unittest.TestCase):
    """기본 제공 에이전트 수정(2026-10-06) — 고친 값 덮어쓰기 · 가린 키 복원 · 도구 종류 고정 · 되돌리기 · 권한.
    Built-in agent edits (2026-10-06): the overlay, masked-key restore, locked tool kinds, reset and permissions."""

    def setUp(self):
        self.stack = ExitStack()
        isolate_db(self.stack)
        self.addCleanup(self.stack.close)
        self.addCleanup(access.rebuild_universe)

    def _eff(self, nodes: dict) -> dict:
        return {"no": 7, "menus": {}, "nodes": nodes, "mgmt": {"p_auto": any(v >= 2 for v in nodes.values())}, "read": {}}

    def _email(self) -> dict:
        return next(b for b in work_agents_api.list_all("")["builtin"] if b["id"] == "agent_email")

    def test_email_edits_overlay_the_defaults_and_reset(self):
        row = self._email()
        self.assertFalse(row["edited"])
        cfg = row["config"]
        self.assertEqual(cfg["auth"]["key"], connectors.SECRET_MASK)
        tools = cfg["tools"]
        first = tools[0]["name"]
        tools[0]["enabled"] = False
        tools[0]["kind"] = "action" if tools[0]["kind"] == "read" else "read"   # 바꿔 보내도 서버 명세로 돌아간다 / reverts to the spec
        out = work_agents_api.update_builtin("agent_email", work_agents_api.BuiltinIn(
            description="사내 메일 처리", config=dict(cfg, url="https://mail-mcp.example.invalid/mcp/", timeout=45, tools=tools)))
        self.assertTrue(out["edited"])
        self.assertEqual((out["label"], out["description"]), ("M코스메틱 이메일 에이전트", "사내 메일 처리"))
        self.assertEqual(out["config"]["url"], "https://mail-mcp.example.invalid/mcp")
        self.assertEqual(out["config"]["auth"]["key"], connectors.SECRET_MASK)
        eff = builtin_agents.effective("agent_email")
        self.assertEqual(eff["config"]["auth"]["key"], mock_mcosmetic.DEMO_KEY)   # 가린 키 = 기존 키 유지 / a masked key keeps the stored one
        t0 = next(t for t in eff["config"]["tools"] if t["name"] == first)
        self.assertFalse(t0["enabled"])
        self.assertEqual(t0["kind"], builtin_agents.locked_kind(t0))
        conn = builtin_agents.email_connection()
        self.assertEqual((conn["url"], conn["timeout"], first in conn["disabled"]), ("https://mail-mcp.example.invalid/mcp", 45, True))
        # 새 키로 바꾸면 그 키를 쓰고 목록에서는 가린다 / a new key is used and stays masked in the list
        work_agents_api.update_builtin("agent_email", work_agents_api.BuiltinIn(
            description="사내 메일 처리", config=dict(out["config"], auth={"type": "header", "key": "new-secret", "name": "X-Mail-Key"})))
        self.assertEqual(builtin_agents.email_connection()["auth"], {"type": "header", "key": "new-secret", "name": "X-Mail-Key"})
        self.assertNotIn("new-secret", json.dumps(work_agents_api.list_all(""), ensure_ascii=False))
        # 기본값으로 되돌리기 / reset to the defaults
        back = work_agents_api.reset_builtin("agent_email", "")
        self.assertFalse(back["edited"])
        self.assertEqual(back["description"], mock_mcosmetic_mcp.DESCRIPTION)
        self.assertEqual(builtin_agents.email_connection()["auth"]["key"], mock_mcosmetic.DEMO_KEY)
        self.assertEqual(builtin_agents.email_connection()["disabled"], frozenset())

    def test_edu_takes_a_description_and_bad_values_are_rejected(self):
        out = work_agents_api.update_builtin("agent_edu", work_agents_api.BuiltinIn(description="교육 자료 관리", config={"url": "https://x.invalid"}))
        self.assertEqual(out, {"id": "agent_edu", "label": "교육 에이전트", "description": "교육 자료 관리", "edited": True,
                               "updated_at": out["updated_at"]})   # 연결 설정은 없다 / no connection settings
        self.assertTrue(out["updated_at"])
        cfg = self._email()["config"]
        for bad, needle in [(dict(cfg, url="ftp://x"), "http"), (dict(cfg, tools=[]), "도구 목록"), (dict(cfg, timeout=0), "타임아웃"),
                            (dict(cfg, auth={"type": "bearer", "key": ""}), "인증 키")]:
            with self.assertRaises(HTTPException) as ctx:
                work_agents_api.update_builtin("agent_email", work_agents_api.BuiltinIn(config=bad))
            self.assertEqual(ctx.exception.status_code, 422, needle)
            self.assertIn(needle, ctx.exception.detail)
        self.assertFalse(self._email()["edited"])   # 실패한 저장은 남지 않는다 / failed saves leave nothing
        with self.assertRaises(HTTPException) as ctx:
            work_agents_api.update_builtin("agent_xyz", work_agents_api.BuiltinIn())
        self.assertEqual(ctx.exception.status_code, 404)

    def test_saving_needs_manage_on_that_agent(self):
        body = work_agents_api.BuiltinIn(description="교육 자료", acting_user_id="7")
        with patch.object(access, "effective", return_value=self._eff({"agent_edu": 1, "agent_email": 2})):
            for fn in (lambda: work_agents_api.update_builtin("agent_edu", body), lambda: work_agents_api.reset_builtin("agent_edu", "7")):
                with self.assertRaises(HTTPException) as ctx:
                    fn()
                self.assertEqual(ctx.exception.status_code, 403)
        with patch.object(access, "effective", return_value=self._eff({"agent_edu": 2})):
            self.assertEqual(work_agents_api.update_builtin("agent_edu", body)["description"], "교육 자료")
            self.assertFalse(work_agents_api.reset_builtin("agent_edu", "7")["edited"])

    def test_discover_restores_the_builtin_key_and_keeps_kinds_on_the_spec(self):
        cfg = self._email()["config"]
        seen = {}

        def fake(url, auth, timeout, previous_tools=None, *, transport=None):
            seen.update(url=url, auth=auth, prev=len(previous_tools or []))
            return {"server_info": {}, "tools": [dict(t, kind="read") for t in cfg["tools"]], "removed": [], "skipped": 0,
                    "fetched_at": "2026-10-06T10:00:00"}
        with patch.object(work_agents, "discover_tools", side_effect=fake):
            out = work_agents_api.discover(work_agents_api.DiscoverIn(url=cfg["url"], auth=cfg["auth"], agent_id="agent_email"))
        self.assertEqual(seen["auth"]["key"], mock_mcosmetic.DEMO_KEY)
        self.assertEqual(seen["prev"], len(cfg["tools"]))
        self.assertEqual([t["kind"] for t in out["tools"]], [builtin_agents.locked_kind(t) for t in out["tools"]])
        self.assertIn("action", [t["kind"] for t in out["tools"]])
        with self.assertRaises(HTTPException) as ctx:
            work_agents_api.discover(work_agents_api.DiscoverIn(url="https://x.invalid/mcp", agent_id="agent_edu"))
        self.assertEqual(ctx.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
