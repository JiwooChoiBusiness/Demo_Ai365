"""API registration and workflow regressions. No live HTTP, LLM, or application DB writes."""
import asyncio
import base64
import json
import socket
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import FastAPI

from app import connectors, connectors_api, flow_api_call as api, flows, tool_contracts


def connector(**api_fields):
    return {"id": "cn_test", "name": "Test API", "description": "Test", "category": "other",
            "kind": "read", "enabled": True,
            "api": api.normalize({"url": "https://example.invalid/endpoint", **api_fields})}


class RequestTests(unittest.TestCase):
    def call(self, cfg, values=None, response=None):
        client = MagicMock()
        client.__enter__.return_value = client
        client.request.return_value = response or httpx.Response(200, json={"data": {"id": "A"}})
        with patch.object(api, "check_url"), patch.object(api.httpx, "Client", return_value=client):
            out = api.call(api.normalize(cfg), api.build_ctx(vars=values or {}))
        return out, client.request

    def test_json_strings_escape_quotes_newlines_and_backslashes(self):
        value = 'ACME "Line A"\nC:\\parts'
        result, call = self.call({"url": "https://example.invalid", "method": "POST",
                                 "body": {"content_type": "application/json", "payload": '{"name":"{{input.name}}"}'}},
                                {"input.name": value})
        self.assertTrue(result["ok"])
        self.assertEqual(call.call_args.kwargs["json"], {"name": value})

    def test_unquoted_json_variables_keep_types(self):
        result = api.json_payload('{"qty":{{input.qty}},"rows":{{input.rows}},"ok":{{input.ok}}}',
                                  api.build_ctx(vars={"input.qty": 10, "input.rows": [{"id": "A"}], "input.ok": False}))
        self.assertEqual(result, {"qty": 10, "rows": [{"id": "A"}], "ok": False})

    def test_invalid_json_never_calls_http(self):
        result, call = self.call({"url": "https://example.invalid", "method": "POST",
                                 "body": {"content_type": "application/json", "payload": '{"a": }'}})
        self.assertFalse(result["ok"])
        call.assert_not_called()

    def test_missing_extraction_or_output_is_failure(self):
        for resp in ({"path": "data.missing"}, {"outputs": [{"name": "id", "path": "data.missing"}]}):
            out, _ = self.call({"url": "https://example.invalid", "response": resp})
            self.assertFalse(out["ok"])
            self.assertTrue(out["error"])

    def test_text_response_with_json_output_is_failure(self):
        out, _ = self.call({"url": "https://example.invalid", "response": {"format": "text", "path": "data.id"}},
                           response=httpx.Response(200, text="hello"))
        self.assertFalse(out["ok"])

    def test_basic_and_body_secrets_are_not_in_request_diagnostics(self):
        secret = "audituser:auditpass"
        out, _ = self.call({"url": "https://example.invalid", "method": "POST", "auth": {"type": "basic", "key": secret},
                            "body": {"content_type": "application/json", "payload": '{"token":"{{api_key}}"}'}})
        rendered = json.dumps(out["request"])
        self.assertNotIn(secret, rendered)
        self.assertNotIn(base64.b64encode(secret.encode()).decode(), rendered)

    def test_mock_private_exception_is_bound_to_configured_origin(self):
        with patch.dict("os.environ", {"FLOW_API_ALLOW_PRIVATE": "0", "AI365_BASE_URL": "http://localhost:8000"}), \
             patch.object(api.socket, "getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 8000))]):
            api.check_url("http://localhost:8000/mock/erp/v1/inventory")
            for url in ("http://10.1.2.3:8000/mock/admin", "http://localhost:9000/mock/admin", "http://localhost:8000/admin"):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    api.check_url(url)

    def test_array_paths_and_task_qualified_outputs(self):
        ctx = api.build_ctx(prior=[{"stage": 1, "node": 1, "data": {"items": [{"id": "A"}]}, "outputs": {"id": "A"}},
                                   {"stage": 1, "node": 2, "data": {"items": [{"id": "B"}]}, "outputs": {"id": "B"}}])
        self.assertEqual(api.resolve("step1.task2.result.items[0].id", ctx), "B")
        self.assertEqual(api.resolve("step1.task1.id", ctx), "A")
        for ambiguous in ("step1.id", "step1.result.items[0].id"):
            with self.assertRaises(ValueError):
                api.resolve(ambiguous, ctx)
        single = api.build_ctx(prior=[{"stage": 1, "data": {"items": [{"id": "A"}]}}])
        self.assertEqual(api.resolve("step1.result.items[0].id", single), "A")

    def test_duplicate_output_names_are_rejected(self):
        with self.assertRaises(ValueError):
            api.normalize({"response": {"outputs": [{"name": "id", "path": "a"}, {"name": "id", "path": "b"}]}})

    def test_typed_default_is_validated_before_save(self):
        for value in ("abc", "true", '"10"'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                api.normalize({"url": "https://example.invalid/{{input.qty}}",
                               "input_docs": [{"name": "qty", "type": "integer", "default": value}]})
        api.normalize({"url": "https://example.invalid/{{input.qty}}",
                       "input_docs": [{"name": "qty", "type": "integer", "default": "10"}]})

    def test_masked_header_rows_keep_credentials_when_reordered(self):
        c = connector(headers=[{"name": "Authorization", "value": "Bearer audit-token"},
                               {"name": "Accept", "value": "application/json"}])
        shown = connectors.editor_record(c)
        self.assertNotIn("audit-token", json.dumps(shown))
        shown["api"]["headers"].reverse()
        restored = connectors.restore_credentials(shown, c)
        self.assertEqual(restored["api"]["headers"][1]["value"], "Bearer audit-token")
        shown["api"]["headers"][1]["name"] = "X-Different"
        with self.assertRaises(ValueError):
            connectors.restore_credentials(shown, c)

    def test_embedded_and_encoded_secrets_round_trip_without_corruption(self):
        secret = 'audit:user"pass'
        encoded = base64.b64encode(secret.encode()).decode()
        c = connector(auth={"type": "basic", "key": secret},
                      body={"content_type": "text/plain", "payload": "Basic " + encoded})
        shown = connectors.editor_record(c)
        self.assertNotIn(encoded, json.dumps(shown))
        self.assertEqual(connectors.restore_credentials(shown, c)["api"], c["api"])


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = FastAPI()
        app.include_router(connectors_api.router)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_member_cannot_read_modify_or_test_admin_api(self):
        calls = [("GET", "/api/connectors?acting_user_id=7", None),
                 ("GET", "/api/connectors/cn_test?acting_user_id=7", None),
                 ("DELETE", "/api/connectors/cn_test?acting_user_id=7", None),
                 ("POST", "/api/connectors", {"acting_user_id": "7"}),
                 ("PUT", "/api/connectors/cn_test", {"acting_user_id": "7"}),
                 ("POST", "/api/connectors/test", {"acting_user_id": "7", "api": {}})]
        for method, url, body in calls:
            r = await self.client.request(method, url, json=body)
            self.assertEqual(r.status_code, 403, (method, url, r.text))

    async def test_list_masks_key_and_update_restores_it(self):
        c = connector(auth={"type": "bearer", "key": "audit-secret"})
        with patch.object(connectors, "list_connectors", return_value=[c]):
            r = await self.client.get("/api/connectors")
        self.assertNotIn("audit-secret", r.text)
        shown = r.json()["connectors"][0]
        restored = connectors.restore_credentials(shown, c)
        self.assertEqual(restored["api"]["auth"]["key"], "audit-secret")
        shown["api"]["auth"]["key"] = ""
        self.assertEqual(connectors.restore_credentials(shown, c)["api"]["auth"]["key"], "")

    async def test_test_and_workflow_both_disable_action_retries(self):
        c = connector(method="POST", response={"on_error": "retry", "retries": 3})
        c["kind"] = "action"
        seen = []
        def call(cfg, ctx, **kwargs):
            seen.append(cfg["response"]["retries"])
            return {"ok": True}
        with patch.object(api, "call", side_effect=call), patch.object(flows, "_api_candidates", return_value=([c], None)):
            r = await self.client.post("/api/connectors/test", json={"kind": "action", "api": c["api"]})
            result = await flows._run_api_node({"agent": "api", "resources": [c["id"]]}, "", [])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(result["status"], "done")
        self.assertEqual(seen, [0, 0])

    async def test_test_rejects_missing_required_input_before_http(self):
        c = connector(url="https://example.invalid/{{input.sku}}")
        with patch.object(api, "call") as call:
            r = await self.client.post("/api/connectors/test", json={"kind": "read", "api": c["api"]})
        self.assertEqual(r.status_code, 422)
        call.assert_not_called()

    async def test_admin_test_restores_stored_key_and_converts_integer_input(self):
        c = connector(url="https://example.invalid/{{input.qty}}", auth={"type": "bearer", "key": "audit-secret"},
                      input_docs=[{"name": "qty", "type": "integer"}])
        shown = connectors.editor_record(c)
        with patch.object(connectors, "get_connector", return_value=c), patch.object(api, "call", return_value={"ok": True}) as call:
            r = await self.client.post("/api/connectors/test", json={"connector_id": c["id"], "api": shown["api"], "vars": {"input.qty": "10"}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(call.call_args.args[0]["auth"]["key"], "audit-secret")
        self.assertEqual(call.call_args.args[1]["vars"]["input.qty"], 10)

    async def test_usage_lists_stage_and_task_for_each_reference(self):
        saved = [{"id": "f1", "name": "재고 확인", "stages": [{"nodes": [
            {"agent": "api", "resources": ["cn_test"]}, {"agent": "data", "resources": []}]},
            {"nodes": [{"agent": "api", "resources": ["cn_test"]}]}]}]
        with patch.object(flows, "get_flows", return_value=saved):
            r = await self.client.get("/api/connectors/cn_test/usage")
        self.assertEqual([(w["stage"], w["task"]) for w in r.json()["workflows"]], [(1, 1), (2, 1)])

    async def test_integer_fixed_binding_and_optional_input_work(self):
        c = connector(url="https://example.invalid/{{input.qty}}?filter={{input.filter}}",
                      input_docs=[{"name": "qty", "type": "integer", "required": True},
                                  {"name": "filter", "type": "string", "required": False}])
        node = {"agent": "api", "resources": [c["id"]], "input_bindings": {"qty": {"mode": "value", "value": "10"}}}
        call = AsyncMock(return_value={"ok": True})
        with patch.object(flows, "_api_candidates", return_value=([c], None)), patch.object(flows.llm, "generate", return_value={"inputs": {}}), \
             patch.object(flows, "call_connector", call):
            result = await flows._run_api_node(node, "", [])
        self.assertEqual(result["status"], "done")
        self.assertEqual(call.call_args.args[3], {"qty": 10})

    async def test_explicit_contract_fixed_integer_and_validation_failure(self):
        c = connector(url="https://example.invalid/{{input.qty}}", response={"on_error": "stop"})
        c["api"]["tool_contract"] = {"version": 1, "input_schema": {"type": "object", "properties": {"qty": {"type": "integer"}}, "required": ["qty"]}}
        with patch.object(flows, "_api_candidates", return_value=([c], None)), patch.object(flows, "call_connector", AsyncMock(return_value={"ok": True})):
            for value, status in (("10", "done"), ("abc", "failed")):
                node = {"agent": "api", "resources": [c["id"]], "input_bindings": {"qty": {"mode": "value", "value": value}}}
                result = await flows._run_api_node(node, "", [])
                self.assertEqual(result["status"], status)
                if status == "failed":
                    self.assertEqual(result["extras"]["api"]["on_error"], "stop")


if __name__ == "__main__":
    unittest.main()
