# -*- coding: utf-8 -*-
"""MCP 클라이언트(2026-09-15) — Streamable HTTP 핸드셰이크·도구 목록(페이지)·도구 호출(JSON/SSE 응답)·오류, 도구 명세 정규화,
결과 변환. 실제 네트워크 없음(httpx MockTransport).

MCP client (2026-09-15) — Streamable HTTP handshake, paged tool list, tool calls (JSON and SSE responses), errors,
tool-spec normalization and result conversion. No network (httpx MockTransport)."""
import json
import unittest

import httpx

from app import mcp_client


def rpc_server(handlers, *, sse=False, session="sess-1"):
    """메서드별 result 를 돌려주는 가짜 서버 → (transport, 받은 요청 목록) / a fake JSON-RPC server → (transport, seen requests)"""
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            seen.append({"headers": dict(request.headers), "body": None, "method": "DELETE"})
            return httpx.Response(200)
        body = json.loads(request.content.decode("utf-8"))
        seen.append({"headers": dict(request.headers), "body": body, "method": request.method})
        if body.get("id") is None:
            return httpx.Response(202, headers={"mcp-session-id": session})
        h = handlers.get(body["method"])
        if h is None:
            payload = {"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32601, "message": "지원하지 않는 메서드입니다"}}
        else:
            res = h(body.get("params") or {})
            payload = {"jsonrpc": "2.0", "id": body["id"], **({"error": res["error"]} if "error" in res else {"result": res})}
        if sse:
            text = ": keepalive\n\nevent: message\ndata: " + json.dumps({"jsonrpc": "2.0", "method": "notifications/message", "params": {}}) \
                   + "\n\ndata: " + json.dumps(payload) + "\n\n"
            return httpx.Response(200, headers={"content-type": "text/event-stream", "mcp-session-id": session}, content=text.encode())
        return httpx.Response(200, headers={"content-type": "application/json", "mcp-session-id": session}, json=payload)

    return httpx.MockTransport(handle), seen


INIT = lambda p: {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "Fake", "version": "0.1"}}


class ClientTests(unittest.TestCase):
    def test_handshake_headers_session_and_paged_tool_list(self):
        pages = {None: {"tools": [{"name": "a", "inputSchema": {"type": "object", "properties": {}}}], "nextCursor": "p2"},
                 "p2": {"tools": [{"name": "b", "inputSchema": {"type": "object", "properties": {}}}]}}
        transport, seen = rpc_server({"initialize": INIT, "tools/list": lambda p: pages[p.get("cursor")]})
        with mcp_client.MCPClient("https://mcp.example.invalid/mcp", {"Authorization": "Bearer k"}, transport=transport) as c:
            tools = c.list_tools()
            self.assertEqual([t["name"] for t in tools], ["a", "b"])
            self.assertEqual(c.protocol, "2025-03-26")
            self.assertEqual(c.server_info["name"], "Fake")
        methods = [s["body"]["method"] for s in seen if s["method"] == "POST"]
        self.assertEqual(methods, ["initialize", "notifications/initialized", "tools/list", "tools/list"])
        first, later = seen[0]["headers"], seen[2]["headers"]
        self.assertEqual(first["accept"], "application/json, text/event-stream")
        self.assertEqual(first["authorization"], "Bearer k")
        self.assertNotIn("mcp-protocol-version", first)              # initialize 전에는 버전 헤더 없음 / no version header before initialize
        self.assertEqual(later["mcp-protocol-version"], "2025-03-26")  # 협상된 버전 / the negotiated version
        self.assertEqual(later["mcp-session-id"], "sess-1")
        self.assertEqual(seen[-1]["method"], "DELETE")                 # 세션 종료 / session teardown

    def test_sse_response_is_parsed_and_notifications_are_skipped(self):
        transport, _ = rpc_server({"initialize": INIT,
                                   "tools/call": lambda p: {"content": [{"type": "text", "text": "hi " + p["arguments"]["x"]}]}}, sse=True)
        with mcp_client.MCPClient("https://mcp.example.invalid/mcp", transport=transport) as c:
            res = c.call_tool("echo", {"x": "there"})
        self.assertEqual(res["content"][0]["text"], "hi there")

    def test_jsonrpc_error_and_http_error_become_mcp_errors(self):
        transport, _ = rpc_server({"initialize": INIT, "tools/call": lambda p: {"error": {"code": -32602, "message": "잘못된 인자"}}})
        with mcp_client.MCPClient("https://mcp.example.invalid/mcp", transport=transport) as c:
            with self.assertRaises(mcp_client.MCPError) as ctx:
                c.call_tool("x", {})
        self.assertIn("잘못된 인자", str(ctx.exception))
        self.assertEqual(ctx.exception.code, -32602)

        def unauthorized(request):
            return httpx.Response(401, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32001, "message": "no key"}})
        with mcp_client.MCPClient("https://mcp.example.invalid/mcp", transport=httpx.MockTransport(unauthorized)) as c:
            with self.assertRaises(mcp_client.MCPError) as ctx:
                c.list_tools()
        self.assertIn("HTTP 401", str(ctx.exception))
        self.assertIn("no key", str(ctx.exception))

    def test_oversized_response_is_refused(self):
        big = httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "application/json"},
                                                            content=b'{"a":"' + b"x" * (mcp_client.MAX_BODY + 10) + b'"}'))
        with mcp_client.MCPClient("https://mcp.example.invalid/mcp", transport=big) as c:
            with self.assertRaises(mcp_client.MCPError) as ctx:
                c.initialize()
        self.assertIn("너무 큽니다", str(ctx.exception))


class NormalizeToolTests(unittest.TestCase):
    def test_schema_simplification_and_kind_default(self):
        raw = {"name": "ems_alarms", "title": "알람 조회", "description": "d",
               "inputSchema": {"type": "object",
                               "properties": {"severity": {"type": "string", "enum": ["all", "critical"], "default": "all"},
                                              "hours": {"type": "integer", "description": "시간", "examples": [24]},
                                              "filters": {"anyOf": [{"type": "string"}, {"type": "object"}]},
                                              "tags": {"type": "array", "items": {"type": "string"}},
                                              "opts": {"type": "object", "properties": {"x": {"type": ["string", "null"]}}, "required": ["x", "ghost"]},
                                              "weird": {"type": "date"}},
                               "required": ["severity", "missing"]},
               "annotations": {"readOnlyHint": True, "destructiveHint": "yes"}}
        t = mcp_client.normalize_tool(raw)
        s = t["input_schema"]
        self.assertEqual(t["kind_default"], "read")
        self.assertEqual(t["annotations"], {"readOnlyHint": True})   # 불리언만 / booleans only
        self.assertEqual(s["required"], ["severity"])               # 없는 속성은 required 에서 제거 / unknown required names dropped
        self.assertEqual(s["properties"]["severity"]["enum"], ["all", "critical"])
        self.assertEqual(s["properties"]["hours"]["examples"], [24])
        self.assertEqual(s["properties"]["filters"]["type"], "string")
        self.assertEqual(s["properties"]["opts"]["required"], ["x"])
        self.assertEqual(s["properties"]["opts"]["properties"]["x"]["type"], "string")
        self.assertEqual(s["properties"]["weird"]["type"], "string")
        self.assertTrue(any(u.startswith("filters:") for u in t["unsupported"]))
        self.assertTrue(any(u.startswith("weird:") for u in t["unsupported"]))
        self.assertEqual(s["properties"]["tags"]["items"], {"type": "string"})

    def test_action_default_when_read_only_hint_missing_and_bad_names_are_skipped(self):
        self.assertEqual(mcp_client.normalize_tool({"name": "do_it", "inputSchema": {}})["kind_default"], "action")
        self.assertEqual(mcp_client.normalize_tool({"name": "do_it", "annotations": {"readOnlyHint": False}})["kind_default"], "action")
        self.assertIsNone(mcp_client.normalize_tool({"name": "bad name!"}))
        self.assertIsNone(mcp_client.normalize_tool({"inputSchema": {}}))
        self.assertIsNone(mcp_client.normalize_tool("nope"))


class ResultTests(unittest.TestCase):
    def test_text_and_structured_content_become_common_result(self):
        r = mcp_client.result_to_common({"content": [{"type": "text", "text": "매출 1,000원"}, {"type": "image", "data": "..."}],
                                         "structuredContent": {"total": 1000, "branch": "서울", "rows": [1, 2], "result": "x", "9bad": 1}})
        self.assertTrue(r["ok"])
        self.assertEqual(r["json"]["total"], 1000)
        self.assertEqual(r["outputs"], {"total": 1000, "branch": "서울"})   # 스칼라만, result·잘못된 이름 제외 / scalars only
        self.assertIn("매출 1,000원", r["result_text"])
        self.assertIn("생략", r["result_text"])
        self.assertEqual(r["skipped_blocks"], 1)

    def test_json_text_without_structured_content_is_parsed_and_errors_are_flagged(self):
        r = mcp_client.result_to_common({"content": [{"type": "text", "text": '{"ok": true, "n": 2}'}]})
        self.assertEqual(r["json"], {"ok": True, "n": 2})
        self.assertEqual(r["outputs"], {"ok": True, "n": 2})
        e = mcp_client.result_to_common({"content": [{"type": "text", "text": "필수 인자 'order_id' 가 없습니다"}], "isError": True})
        self.assertFalse(e["ok"])
        self.assertIn("order_id", e["error"])
        self.assertFalse(mcp_client.result_to_common({"isError": True})["ok"])
        self.assertTrue(mcp_client.result_to_common({})["ok"])


if __name__ == "__main__":
    unittest.main()
