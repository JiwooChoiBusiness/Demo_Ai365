# -*- coding: utf-8 -*-
"""데모 MCP 서버(/mock/mcp, 2026-09-15) — JSON-RPC 처리·인증·도구 6종 실행, 그리고 우리 MCP 클라이언트로 끝까지 통과.

Demo MCP server (/mock/mcp, 2026-09-15) — JSON-RPC handling, auth, the six tools, and an end-to-end pass through our client."""
import json
import unittest

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import mcp_client, mcp_servers, mock_mcp

AUTH = f"Bearer {mock_mcp.DEMO_MCP_KEY}"


def rpc(method, params=None, mid=1):
    msg = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def call(name, args):
    status, body = mock_mcp.handle(rpc("tools/call", {"name": name, "arguments": args}), AUTH)
    return status, body


class HandleTests(unittest.TestCase):
    def test_auth_handshake_and_listing(self):
        status, body = mock_mcp.handle(rpc("tools/list"), "Bearer wrong")
        self.assertEqual((status, body["error"]["code"]), (401, -32001))
        status, body = mock_mcp.handle(rpc("initialize", {"protocolVersion": "2025-03-26"}), AUTH)
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(body["result"]["serverInfo"]["name"], mock_mcp.SERVER_INFO["name"])
        self.assertEqual(mock_mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, AUTH), (202, None))
        status, body = mock_mcp.handle(rpc("tools/list"), AUTH)
        tools = body["result"]["tools"]
        self.assertEqual(len(tools), 6)
        kinds = {t["name"]: t["annotations"]["readOnlyHint"] for t in tools}
        self.assertTrue(kinds["erp_sales_summary"])
        self.assertFalse(kinds["ems_equipment_control"])
        self.assertEqual(mock_mcp.handle(rpc("nope"), AUTH)[1]["error"]["code"], -32601)
        self.assertEqual(mock_mcp.handle("junk", AUTH)[0], 400)

    def test_tools_run_and_validate(self):
        status, body = call("erp_sales_summary", {"period": "2026-08", "branch": "서울"})
        r = body["result"]
        self.assertFalse(r["isError"])
        self.assertEqual(r["structuredContent"]["branch"], "서울")
        self.assertIn("매출", r["content"][0]["text"])
        self.assertTrue(call("erp_sales_summary", {"branch": "서울"})[1]["result"]["isError"])          # period 필수 / required
        self.assertTrue(call("erp_sales_summary", {"period": "2026-08", "branch": "화성"})[1]["result"]["isError"])   # enum
        inv = call("erp_inventory", {})[1]["result"]
        self.assertGreater(inv["structuredContent"]["item_count"], 0)
        one = call("erp_inventory", {"sku": "SKU-1001"})[1]["result"]["structuredContent"]
        self.assertEqual(one["sku"], "SKU-1001")
        ok = call("erp_order_approve", {"order_id": "O-100231"})[1]["result"]
        self.assertEqual(ok["structuredContent"]["status"], "approved")
        self.assertTrue(call("erp_order_approve", {"order_id": "bad"})[1]["result"]["isError"])
        usage = call("ems_energy_usage", {"period": "2026-08"})[1]["result"]["structuredContent"]
        self.assertEqual(usage["site"], "HQ")
        alarms = call("ems_alarms", {"severity": "critical", "hours": 48})[1]["result"]["structuredContent"]
        self.assertEqual(alarms["window_hours"], 48)
        self.assertTrue(all(a["severity"] == "critical" for a in alarms["alarms"]))
        self.assertTrue(call("ems_alarms", {"hours": "many"})[1]["result"]["isError"])
        ctl = call("ems_equipment_control", {"equipment_id": "EQ-101", "command": "stop"})[1]["result"]
        self.assertEqual(ctl["structuredContent"]["status"], "stopped")
        self.assertTrue(call("ems_equipment_control", {"equipment_id": "EQ-101", "command": "fly"})[1]["result"]["isError"])
        self.assertEqual(call("unknown_tool", {})[1]["error"]["code"], -32602)


class EndToEndTests(unittest.TestCase):
    def transport(self):
        def handle(request: httpx.Request) -> httpx.Response:
            if request.method == "DELETE":
                return httpx.Response(200)
            status, body = mock_mcp.handle(json.loads(request.content), request.headers.get("authorization"))
            if body is None:
                return httpx.Response(status)
            return httpx.Response(status, headers={"content-type": "application/json"}, json=body)
        return httpx.MockTransport(handle)

    def test_client_lists_and_calls_the_demo_server(self):
        with mcp_client.MCPClient("http://localhost:8000/mock/mcp", {"Authorization": AUTH}, transport=self.transport()) as c:
            names = [t["name"] for t in c.list_tools()]
            res = c.call_tool("ems_energy_usage", {"period": "2026-07", "site": "BUSAN"})
        self.assertEqual(len(names), 6)
        conv = mcp_client.result_to_common(res)
        self.assertTrue(conv["ok"])
        self.assertEqual(conv["json"]["site"], "BUSAN")
        self.assertIn("kwh_total", conv["outputs"])
        norm = [mcp_servers.merge_tools([mcp_client.normalize_tool(t) for t in mock_mcp.TOOLS], None)[0]]
        kinds = {t["name"]: t["kind"] for t in norm[0]}
        self.assertEqual(kinds["erp_sales_summary"], "read")
        self.assertEqual(kinds["erp_order_approve"], "action")
        self.assertEqual(kinds["ems_equipment_control"], "action")

    def test_http_route_serves_json_rpc_and_batches(self):
        app = FastAPI()
        app.include_router(mock_mcp.router)
        client = TestClient(app)
        r = client.post("/mock/mcp", json=rpc("ping"), headers={"Authorization": AUTH})
        self.assertEqual((r.status_code, r.json()["result"]), (200, {}))
        self.assertEqual(client.post("/mock/mcp", json=rpc("ping")).status_code, 401)
        self.assertEqual(client.post("/mock/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers={"Authorization": AUTH}).status_code, 202)
        batch = client.post("/mock/mcp", json=[rpc("ping", mid=1), rpc("tools/list", mid=2)], headers={"Authorization": AUTH})
        self.assertEqual([b["id"] for b in batch.json()], [1, 2])
        self.assertEqual(client.get("/mock/mcp").status_code, 405)
        self.assertEqual(client.post("/mock/mcp", content=b"{bad", headers={"Authorization": AUTH}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
