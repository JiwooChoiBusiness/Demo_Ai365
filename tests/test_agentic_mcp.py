# -*- coding: utf-8 -*-
"""Agentic 모드 연결 도구(2026-10-19, 2차 Connectors): 켜진 MCP 도구만 고르기 · 입력 명세 · 프롬프트 글 · 종류 · 이름 ·
호출(성공 · 구조화 결과 · 긴 결과 · 도구 오류 · 연결 실패 · JSON 오류 · 없는 id · 꺼진 도구). 임시 DB(isolate_db)에 MCP 서버를
등록해 도구 커넥터 행을 만들고, MCP 서버는 httpx.MockTransport 로 흉내 낸다. 실제 LLM · 실 DB · 네트워크 없음.

Agentic mode connected tools (phase-2 Connectors): only enabled MCP tools, input specs, the prompt text, kinds, labels
and calls (success, structured results, long results, tool errors, connection failures, bad JSON, unknown ids, disabled
tools). An MCP server registered in a temp DB (isolate_db) creates the tool connector rows; the server itself is an
httpx.MockTransport. No real LLM, real DB or network."""
import json
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import httpx

from app import agentic_mcp as am, connectors, flow_api_call, mcp_servers
from tests.db_fixture import isolate_db

TOOLS = [
    {"name": "erp_sales_summary", "title": "매출 요약", "description": "지점별 매출을 조회합니다",
     "input_schema": {"type": "object", "properties": {"period": {"type": "string", "description": "조회 월"},
                                                        "branch": {"type": "string", "enum": ["all", "서울"], "default": "all"}},
                      "required": ["period"]},
     "annotations": {"readOnlyHint": True}, "kind": "read", "enabled": True},
    {"name": "ems_equipment_control", "title": "설비 제어", "description": "설비를 가동하거나 멈춥니다",
     "input_schema": {"type": "object", "properties": {"equipment_id": {"type": "string"}, "hours": {"type": "integer"}},
                      "required": ["equipment_id"]},
     "kind": "action", "enabled": True},
    {"name": "erp_retired", "title": "옛 조회", "description": "꺼 둔 도구",
     "input_schema": {"type": "object", "properties": {}}, "kind": "read", "enabled": False},
]


class McpCase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        self.api = connectors.create({"name": "재고 API", "description": "재고 조회", "api": {"url": "https://erp.example.invalid/x"}})
        self.server = mcp_servers.create({"name": "데모 MCP", "description": "가상 ERP", "category": "erp",
                                          "url": "https://mcp.example.invalid/mcp", "auth": {"type": "none"}, "timeout": 10,
                                          "tools": TOOLS})
        self.read_id = mcp_servers.tool_connector_id(self.server["id"], "erp_sales_summary")
        self.action_id = mcp_servers.tool_connector_id(self.server["id"], "ems_equipment_control")
        self.off_id = mcp_servers.tool_connector_id(self.server["id"], "erp_retired")
        # input_docs 가 없는 행 → 입력 명세에서 만든다 / a row without input_docs falls back to the schema
        connectors.upsert_mcp_tool({"id": "cn_mfallback01", "name": "수동 › 검색", "description": "입력 설명이 없는 도구", "kind": "odd",
                                    "enabled": True, "source": "mcp",
                                    "api": {"mcp": {"server_id": self.server["id"], "server_name": "수동", "tool": "search"},
                                            "tool_contract": {"version": 1, "input_schema": {
                                                "type": "object", "properties": {"q": {"type": "string", "description": "검색어"},
                                                                                 "limit": {"type": "integer"}},
                                                "required": ["q"]}}}})
        self.stack.enter_context(patch.object(flow_api_call, "check_url"))   # 가짜 주소 · 사설망 판정 끔 / fake host
        self.calls: list[dict] = []
        self.reply = {"content": [{"type": "text", "text": "서울 지점 매출 12억"}]}

        def handle(request):
            body = json.loads(request.content)
            if body.get("id") is None:
                return httpx.Response(202)
            if body["method"] == "initialize":
                res = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "Fake", "version": "1"}}
            else:
                self.calls.append(body["params"])
                res = self.reply
            return httpx.Response(200, headers={"content-type": "application/json"},
                                  json={"jsonrpc": "2.0", "id": body["id"], "result": res})
        self.stack.enter_context(patch.object(am, "TRANSPORT", httpx.MockTransport(handle)))


class ListTests(McpCase):
    def test_available_keeps_enabled_mcp_tools_only_with_input_specs(self):
        rows = {r["id"]: r for r in am.available()}
        self.assertEqual(set(rows), {self.read_id, self.action_id, "cn_mfallback01"})   # API · 꺼진 도구 제외 / API and disabled left out
        self.assertEqual(rows[self.read_id], {
            "id": self.read_id, "name": "데모 MCP › 매출 요약", "description": "지점별 매출을 조회합니다", "kind": "read",
            "server_name": "데모 MCP", "tool": "erp_sales_summary",
            "inputs": [{"name": "period", "type": "string", "required": True, "description": "조회 월"},
                       {"name": "branch", "type": "string", "required": False, "description": ""}]})
        self.assertEqual(rows[self.action_id]["kind"], "action")
        self.assertEqual(rows["cn_mfallback01"]["kind"], "action")                     # 모르는 종류 = 실행 / unknown = action
        self.assertEqual(rows["cn_mfallback01"]["inputs"], [{"name": "q", "type": "string", "required": True, "description": "검색어"},
                                                            {"name": "limit", "type": "integer", "required": False, "description": ""}])
        self.assertEqual(am.get(self.read_id), rows[self.read_id])
        for missing in (self.off_id, self.api["id"], "cn_missing", "", None):
            self.assertIsNone(am.get(missing), missing)

    def test_kind_of_and_label(self):
        self.assertEqual((am.kind_of(self.read_id), am.kind_of(self.action_id), am.kind_of(self.off_id), am.kind_of("cn_x")),
                         ("read", "action", "", ""))
        self.assertEqual(am.label(self.action_id), "데모 MCP › 설비 제어")
        self.assertEqual(am.label(self.off_id), "데모 MCP › 옛 조회")                    # 꺼진 도구도 이름 / disabled keeps its name
        self.assertEqual(am.label("cn_missing"), "cn_missing")
        self.assertEqual(am.label(self.api["id"]), self.api["id"])                     # MCP 가 아니면 id / not MCP → the id

    def test_prompt_text_lists_the_connected_tools_with_their_inputs(self):
        text = am.prompt_text([self.read_id, "cn_missing", self.action_id, self.read_id, self.off_id, "cn_mfallback01"])
        self.assertEqual(text, "\n".join([
            "[연결된 도구(mcp_tool)]",
            f"- {self.read_id} · 데모 MCP › 매출 요약 (read): 지점별 매출을 조회합니다",
            "  입력: period(string, 필수) 조회 월, branch(string)",
            f"- {self.action_id} · 데모 MCP › 설비 제어 (action): 설비를 가동하거나 멈춥니다",
            "  입력: equipment_id(string, 필수), hours(integer)",
            "- cn_mfallback01 · 수동 › 검색 (action): 입력 설명이 없는 도구",
            "  입력: q(string, 필수) 검색어, limit(integer)"]))
        self.assertEqual(am.prompt_text([]), "")
        self.assertEqual(am.prompt_text(None), "")
        self.assertEqual(am.prompt_text([self.off_id, "cn_missing"]), "")


class CallTests(McpCase):
    def test_a_successful_call_returns_the_result_text(self):
        ok, summary, detail, extra = am.call(self.read_id, '{"period": "2026-09", "branch": "서울", "blank": ""}')
        self.assertEqual((ok, summary, detail, extra), (True, "결과 12자", "서울 지점 매출 12억", {}))
        self.assertEqual(self.calls, [{"name": "erp_sales_summary", "arguments": {"period": "2026-09", "branch": "서울"}}])
        self.assertTrue(am.call(self.read_id, "")[0])                                  # 빈 문자열 = {} / empty = {}
        self.assertTrue(am.call(self.read_id, None)[0])
        self.assertTrue(am.call(self.read_id, {"period": "2026-10"})[0])               # 객체도 받는다 / a dict is accepted
        self.assertEqual([c["arguments"] for c in self.calls[1:]], [{}, {}, {"period": "2026-10"}])

    def test_structured_and_long_results(self):
        self.reply = {"content": [], "structuredContent": {"합계": 5, "지점": "서울"}}
        ok, summary, detail, _ = am.call(self.read_id, "{}")
        self.assertTrue(ok)
        self.assertEqual(json.loads(detail), {"합계": 5, "지점": "서울"})
        self.assertIn("서울", detail)                                                  # ensure_ascii=False
        self.reply = {"content": [{"type": "text", "text": "가" * 7000}]}
        ok, summary, detail, _ = am.call(self.read_id, "{}")
        self.assertEqual((ok, summary), (True, "결과 7,000자"))
        self.assertLessEqual(len(detail), am.DETAIL_MAX)
        self.assertTrue(detail.startswith("가" * 5000))
        self.assertIn("앞부분만", detail)
        self.reply = {"content": []}
        self.assertEqual(am.call(self.read_id, "{}")[:3], (True, "결과 0자", "(결과 없음)"))

    def test_tool_errors_and_connection_failures_come_back_as_ok_false(self):
        self.reply = {"content": [{"type": "text", "text": "설비 E-7 은 점검 중입니다"}], "isError": True}
        ok, summary, detail, extra = am.call(self.action_id, '{"equipment_id": "E-7"}')
        self.assertEqual((ok, summary, detail, extra), (False, "설비 E-7 은 점검 중입니다", "설비 E-7 은 점검 중입니다", {}))

        def down(request):
            raise httpx.ConnectError("refused", request=request)
        with patch.object(am, "TRANSPORT", httpx.MockTransport(down)):
            ok, _summary, detail, _ = am.call(self.read_id, "{}")
        self.assertFalse(ok)
        self.assertIn("연결할 수 없습니다", detail)
        with patch.object(mcp_servers, "call_tool", side_effect=RuntimeError("boom")), self.assertLogs("ai365.agentic", "ERROR"):
            ok, summary, detail, _ = am.call(self.read_id, "{}")
        self.assertEqual((ok, summary), (False, "도구 호출 오류"))
        self.assertIn("RuntimeError: boom", detail)

    def test_bad_inputs_unknown_and_disabled_tools_never_reach_the_server(self):
        for raw in ("{bad", '{"a": 1', "nul"):
            ok, summary, detail, _ = am.call(self.read_id, raw)
            self.assertEqual((ok, summary), (False, "입력 JSON 오류"), raw)
            self.assertIn("JSON 으로 읽지 못했습니다", detail)
        for raw in ("[1, 2]", '"text"', "3", 5, ["a"]):
            self.assertEqual(am.call(self.read_id, raw)[:3], (False, "입력 JSON 오류", "inputs_json 은 JSON 객체여야 합니다"), raw)
        self.assertEqual(am.call("cn_missing", "{}")[:3], (False, "없는 도구", "연결된 도구를 찾을 수 없습니다: cn_missing"))
        self.assertEqual(am.call(self.api["id"], "{}")[1], "없는 도구")                 # MCP 가 아닌 API / not an MCP tool
        self.assertEqual(am.call(self.off_id, "{}")[:3], (False, "꺼진 도구", "관리 센터에서 꺼 둔 도구입니다: 데모 MCP › 옛 조회"))
        self.assertEqual(am.call("", "{}")[:2], (False, "connector_id 없음"))
        deep = '{"a": ' + "[" * 3000 + "]" * 3000 + "}"                               # 깊은 JSON = RecursionError (M1)
        ok, summary, detail, _ = am.call(self.read_id, deep)
        self.assertEqual((ok, summary), (False, "입력 JSON 오류"))
        self.assertIn("깊게", detail)
        self.assertEqual(self.calls, [])                                               # 서버에 가지 않았다 / nothing was sent
        # 서버를 끄면 그 도구들도 꺼진다(동기화) / disabling the server disables its tools (sync)
        mcp_servers.update(self.server["id"], {**mcp_servers.editor_record(self.server), "enabled": False})
        self.assertFalse({self.read_id, self.action_id} & {r["id"] for r in am.available()})
        self.assertEqual(am.call(self.read_id, "{}")[:2], (False, "꺼진 도구"))
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
