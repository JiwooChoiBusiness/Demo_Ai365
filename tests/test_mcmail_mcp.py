# -*- coding: utf-8 -*-
"""M코스메틱 이메일 에이전트 MCP 서버(/mock/mcosmetic/mcp, 2026-09-29) — JSON-RPC 처리·인증, 도구 25종(조회 10 · 실행 15)이 같은
스토어를 바꾸는지, 업무 현황 조회(get_work_status, 2026-09-30 채팅 주 조회)와 도구 오류의 구조화 정보(상태 404 · 409 · 422),
업무 자동화 탭의 기본 제공 연결 설정, 우리 MCP 클라이언트와 채팅 연결(app/mcmail_link.py)로 끝까지 통과, HTTP 경로.
격리 DB(tests/db_fixture) + 오늘 날짜 고정, 실제 LLM 없음.

M Cosmetic Email Agent MCP server (/mock/mcosmetic/mcp, 2026-09-29): JSON-RPC handling and auth, the 25 tools (10 reads,
15 actions) changing the same store, the work-status read (get_work_status, the chat's main read since 2026-09-30) and the
structured tool-error info (status 404, 409, 422), the automation tab's built-in connection, end-to-end passes through our
MCP client and the chat link (app/mcmail_link.py), and the HTTP route. Isolated DB (tests/db_fixture) with a pinned
today; no real LLM."""
import json
import os
import unittest
from contextlib import ExitStack
from datetime import date
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from db_fixture import isolate_db
from app import (builtin_agents, connectors, mcmail, mcmail_link, mcp_client, mcp_servers, mock_mcosmetic, mock_mcosmetic_mcp as mcp,
                 work_agents_api)

AUTH = f"Bearer {mock_mcosmetic.DEMO_KEY}"
TODAY = date(2026, 10, 5)


def rpc(method, params=None, mid=1):
    msg = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def call(name, args=None):
    status, body = mcp.handle(rpc("tools/call", {"name": name, "arguments": args or {}}), AUTH)
    assert status == 200, (status, body)
    return body["result"] if "result" in body else body


class McpBase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        self.stack.enter_context(patch.object(mcmail, "_server_today", return_value=TODAY))
        self.stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")))
        mcmail.init_mcmail()


class HandleTests(McpBase):
    def test_auth_handshake_and_listing(self):
        status, body = mcp.handle(rpc("tools/list"), "Bearer wrong")
        self.assertEqual((status, body["error"]["code"]), (401, -32001))
        self.assertEqual(mcp.handle(rpc("tools/list"), None)[0], 401)
        status, body = mcp.handle(rpc("initialize", {"protocolVersion": "2025-03-26"}), AUTH)
        self.assertEqual((status, body["result"]["protocolVersion"]), (200, "2025-03-26"))
        self.assertEqual(body["result"]["serverInfo"]["name"], "M코스메틱 이메일 에이전트 MCP 서버")
        self.assertEqual(mcp.handle(rpc("initialize", {"protocolVersion": "1999-01-01"}), AUTH)[1]["result"]["protocolVersion"],
                         mcp.PROTOCOL)   # 모르는 버전 → 우리 버전 / unknown version falls back to ours
        self.assertEqual(mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, AUTH), (202, None))
        tools = mcp.handle(rpc("tools/list"), AUTH)[1]["result"]["tools"]
        names = [t["name"] for t in tools]
        self.assertEqual(len(names), 25)
        self.assertEqual(len(set(names)), 25)
        reads = [t["name"] for t in tools if t["annotations"]["readOnlyHint"]]
        self.assertEqual(reads, ["get_work_status", "get_dashboard", "list_mails", "get_mail", "list_cases", "get_case",
                                 "list_errors", "search", "get_activity_log", "get_notifications"])
        self.assertEqual(names[0], "get_work_status")   # 채팅의 주 조회가 맨 앞 / the chat's main read comes first
        self.assertTrue(next(t for t in tools if t["name"] == "send_reply")["annotations"]["destructiveHint"])
        for t in tools:   # 화면 문구에 em dash 금지 / no em dash in UI text
            self.assertNotIn("—", t["title"] + t["description"], t["name"])
        self.assertEqual(mcp.handle(rpc("resources/list"), AUTH)[1]["error"]["code"], -32601)
        self.assertEqual(mcp.handle("junk", AUTH)[0], 400)
        self.assertEqual(mcp.handle(rpc("tools/call", {"name": "nope"}), AUTH)[1]["error"]["code"], -32602)

    def test_reads_answer_from_the_store(self):
        r = call("get_dashboard")
        self.assertFalse(r["isError"])
        self.assertEqual(r["structuredContent"]["date"], "2026-10-05")
        self.assertIn("수신 19건", r["content"][0]["text"])
        quotes = call("list_mails", {"view": "quote"})["structuredContent"]
        self.assertEqual((quotes["view"], quotes["filter"]), ("quote", "todo"))
        self.assertEqual(quotes["total"], len(quotes["items"]))
        self.assertEqual(call("get_mail", {"email_id": "E-1001"})["structuredContent"]["email"]["emailId"], "E-1001")
        case = call("get_case", {"case_id": "rfq-2026-00123"})["structuredContent"]   # Case 번호는 대문자로 / case ids are upper-cased
        self.assertEqual(case["case"]["caseId"], "RFQ-2026-00123")
        self.assertEqual(call("list_cases", {"filter": "견적"})["structuredContent"]["filter"], "견적")
        self.assertEqual(call("list_errors")["structuredContent"]["counts"]["open"], 2)
        self.assertEqual(call("search", {"q": "누리"})["structuredContent"]["q"], "누리")
        self.assertEqual(len(call("get_activity_log", {"limit": 3})["structuredContent"]["items"]), 3)
        self.assertEqual(len(call("get_activity_log", {"limit": 500})["structuredContent"]["items"]), 8)   # 상한 40, 시드 8건 / capped
        self.assertEqual(call("get_notifications")["structuredContent"]["count"], 8)

    def test_bad_input_and_rule_violations_are_tool_errors(self):
        # 도구 오류는 structuredContent.error 에 상태와 문구를 싣는다(2026-09-30): 인자 오류 422 · 없는 id 404 · 스토어 규칙 422
        # Tool errors carry the status and message in structuredContent.error (2026-09-30): argument errors 422, unknown ids
        # 404, store rules 422
        for name, args, text, status in [
                ("get_mail", {}, "필수 인자 'email_id'", 422),
                ("get_mail", {"email_id": "E-0000"}, "메일을 찾을 수 없습니다", 404),
                ("list_mails", {"view": "inbox", "filter": "err"}, "알 수 없는 필터", 422),
                ("list_mails", {"view": "spam"}, "'view' 값은", 422),
                ("classify_mail", {"email_id": "E-1001", "classification": "zzz"}, "'classification' 값은", 422),
                ("assign_owner", {"kind": "mail", "id": "E-1001", "user": "홍길동"}, "'user' 값은", 422),
                ("get_activity_log", {"limit": "many"}, "limit 는 정수", 422),
                ("hold_mail", {"email_id": "E-1001", "on": "maybe"}, "참/거짓", 422),
                ("retry_error", {"error_id": "ERR-9999"}, "오류를 찾을 수 없습니다", 404),
                ("get_case", {"case_id": "RFQ-2026-99999"}, "Case를 찾을 수 없습니다", 404)]:
            r = call(name, args)
            self.assertTrue(r["isError"], (name, args))
            self.assertIn(text, r["content"][0]["text"], (name, args))
            self.assertEqual(r["structuredContent"], {"error": {"status": status, "message": r["content"][0]["text"]}},
                             (name, args))
        # 스토어의 충돌(409)도 같은 모양 / a store conflict (409) has the same shape
        with patch.object(mcmail, "create_order", side_effect=mcmail.MailConflict("Sales Order SO-1 는 이미 다른 내용으로 등록되어 있습니다.")):
            r = call("create_order", {"email_id": "E-1005"})
        self.assertTrue(r["isError"])
        self.assertEqual(r["structuredContent"]["error"]["status"], 409)
        # 우리 클라이언트 변환도 구조화 오류를 그대로 보존한다 / our client conversion keeps the structured error
        conv = mcp_client.result_to_common(call("get_mail", {"email_id": "E-0000"}))
        self.assertEqual((conv["ok"], conv["json"]["error"]["status"]), (False, 404))

    def test_work_status_read_matches_the_in_process_lookup(self):
        r = call("get_work_status", {"target": "errors"})
        self.assertFalse(r["isError"])
        s = r["structuredContent"]
        self.assertEqual(set(s), {"target", "task", "detail", "answer", "data"})
        data, task, detail = mcmail.lookup("errors")
        self.assertEqual((s["target"], s["task"], s["detail"]), ("errors", task, detail))
        self.assertEqual(s["answer"], mcmail.fallback_answer(data, task))   # 채팅이 받던 표 그대로 / the table the chat used to build
        self.assertIn("미해결 API 오류는 **2건**", s["answer"])
        self.assertEqual(r["content"][0]["text"], f"{task} {detail}")
        self.assertEqual(s["data"]["target"], "errors")
        # 고객사 · Case 인자는 종전 채팅 호출과 같은 모양으로 스토어에 간다 / customer and case args reach the store in the old shape
        with patch.object(mcmail, "lookup", wraps=mcmail.lookup) as spy:
            cust = call("get_work_status", {"target": "customer", "customer": "누리뷰티 02"})["structuredContent"]
            case = call("get_work_status", {"target": "case", "case_id": "rfq-2026-00123"})["structuredContent"]
            call("get_work_status", {"target": "quotes", "customer": "무시"})   # 대상 밖 인자는 넘기지 않는다 / ignored off-target
        self.assertEqual([c.args for c in spy.call_args_list],
                         [("customer", {"customer": "누리뷰티 02"}), ("case", {"case_id": "rfq-2026-00123"}), ("quotes", None)])
        self.assertIn("**누리뷰티 02** (CUST-00002)", cust["answer"])
        self.assertIn("**RFQ-2026-00123**", case["answer"])   # 스토어가 대문자로 / the store upper-cases the id
        for args, text in [({}, "필수 인자 'target'"), ({"target": "nope"}, "'target' 값은"),
                           ({"target": "customer"}, "'customer' 인자가 필요합니다"),
                           ({"target": "case", "case_id": " "}, "'case_id' 인자가 필요합니다")]:
            bad = call("get_work_status", args)
            self.assertTrue(bad["isError"], args)
            self.assertIn(text, bad["content"][0]["text"], args)
            self.assertEqual(bad["structuredContent"]["error"]["status"], 422, args)

    def test_summaries_tolerate_partial_store_payloads(self):
        # 스토어 응답에 건수 키가 없어도 요약 문장이 깨지지 않는다(채팅 플래너 테스트가 목록을 이렇게 바꾼다)
        # Summaries survive store payloads without count keys (a chat planner test patches the list like this)
        with patch.object(mcmail, "list_emails", return_value={"items": [{"emailId": "E-9001"}]}), \
             patch.object(mcmail, "list_cases", return_value={"items": []}), \
             patch.object(mcmail, "list_errors", return_value={"items": []}), \
             patch.object(mcmail, "notifications", return_value={}), \
             patch.object(mcmail, "search", return_value={}):
            self.assertEqual(call("list_mails")["content"][0]["text"], "메일 1건을 찾았습니다.")
            self.assertEqual(call("list_cases")["content"][0]["text"], "업무 Case 0건을 찾았습니다.")
            self.assertEqual(call("list_errors")["content"][0]["text"], "처리오류 0건을 찾았습니다(미해결 0건).")
            self.assertFalse(call("get_notifications")["isError"])
            self.assertFalse(call("search", {"q": "x"})["isError"])

    def test_actions_change_the_same_store_the_email_screen_reads(self):
        before = mcmail.get_email("E-1001")["email"]
        r = call("run_erp", {"email_id": "E-1001"})
        self.assertFalse(r["isError"])
        self.assertIn("단가조회 완료", r["content"][0]["text"])
        after = mcmail.get_email("E-1001")["email"]   # /api/email 이 읽는 같은 스토어 / the store /api/email reads
        self.assertNotEqual(before["flow"].get("erp"), "done")
        self.assertEqual(after["flow"]["erp"], "done")
        self.assertEqual(r["structuredContent"]["email"]["emailId"], "E-1001")
        self.assertTrue(call("hold_mail", {"email_id": "E-1001", "on": True})["structuredContent"]["email"]["hold"])
        self.assertFalse(call("hold_mail", {"email_id": "E-1001", "on": "false"})["structuredContent"]["email"]["hold"])
        call("assign_owner", {"kind": "case", "id": "RFQ-2026-00123", "user": "이수진"})
        self.assertEqual(mcmail.get_case("RFQ-2026-00123")["case"]["assignedUser"], "이수진")
        sent = call("send_reply", {"email_id": "E-1001"})
        self.assertFalse(sent["isError"], sent["content"])
        self.assertTrue(mcmail.get_email("E-1001")["email"]["closed"])
        again = call("send_reply", {"email_id": "E-1001"})   # 완료된 메일은 다시 못 보낸다(스토어 규칙) / the store's rule holds
        self.assertTrue(again["isError"])


class RegistryTests(McpBase):
    def test_builtin_row_carries_the_mcp_connection(self):
        cfg = mcp.registry_config()
        self.assertEqual(cfg["url"], "{{base_url}}/mock/mcosmetic/mcp")
        self.assertEqual(cfg["auth"], {"type": "bearer", "key": connectors.SECRET_MASK, "name": "Authorization"})
        self.assertNotIn(mock_mcosmetic.DEMO_KEY, json.dumps(cfg, ensure_ascii=False))   # 키는 가린다 / the key stays masked
        self.assertEqual(len(cfg["tools"]), 25)
        self.assertEqual(sum(t["kind"] == "read" for t in cfg["tools"]), 10)
        self.assertEqual(cfg["tools"][0]["name"], "get_work_status")
        self.assertTrue(all(t["enabled"] and not t["unsupported"] for t in cfg["tools"]))   # 명세 단순화 없음 / nothing simplified
        # 저장 검증기를 그대로 통과하는 모양 / the same shape the store's validator accepts
        self.assertEqual(len(mcp_servers.normalize_tools(cfg["tools"])), 25)
        listed = work_agents_api.list_all("")
        email, edu = listed["builtin"]
        self.assertEqual((email["id"], email["method"]), ("agent_email", "mcp"))
        self.assertEqual(email["label"], "M코스메틱 이메일 에이전트")
        self.assertEqual(email["config"]["url"], cfg["url"])
        self.assertEqual(email["description"], mcp.DESCRIPTION)
        self.assertFalse(email["edited"])   # 고친 값 없음 = 기본값 그대로(2026-10-06) / no edits = the defaults
        self.assertEqual(edu, {"id": "agent_edu", "label": "교육 에이전트", "description": builtin_agents.EDU_DESCRIPTION,
                               "edited": False, "updated_at": ""})   # 교육은 설명만 / education carries its description only


class EndToEndTests(McpBase):
    def transport(self, auth: str | None = None, seen: list | None = None):
        """서버를 HTTP 없이 부르는 전송 · auth 를 주면 그 인증 헤더로 바꿔 보낸다(거부 흉내), seen 에 JSON-RPC 메서드를 남긴다.
        A transport calling the server without HTTP; auth replaces the auth header (a rejection), seen records the methods."""
        def handle(request: httpx.Request) -> httpx.Response:
            if request.method == "DELETE":
                return httpx.Response(200)
            msg = json.loads(request.content)
            if seen is not None:
                seen.append((str(request.url), msg.get("method"), (msg.get("params") or {}).get("name")))
            status, body = mcp.handle(msg, auth if auth is not None else request.headers.get("authorization"))
            if body is None:
                return httpx.Response(status)
            return httpx.Response(status, headers={"content-type": "application/json"}, json=body)
        return httpx.MockTransport(handle)

    def test_our_client_lists_and_calls_the_server(self):
        url = "http://localhost:8000/mock/mcosmetic/mcp"
        with mcp_client.MCPClient(url, {"Authorization": AUTH}, transport=self.transport()) as c:
            names = [t["name"] for t in c.list_tools()]
            res = c.call_tool("get_notifications", {})
        self.assertEqual(len(names), 25)
        conv = mcp_client.result_to_common(res)
        self.assertTrue(conv["ok"])
        self.assertEqual(conv["json"]["count"], 8)
        # 업무 자동화 에이전트 실행기와 같은 호출 경로(주소·인증 직접) / the same path the work-agent runner uses
        out = mcp_servers.call_tool_at(url, {"type": "bearer", "key": mock_mcosmetic.DEMO_KEY}, 30, "list_errors", {"status": "all"},
                                       transport=self.transport())
        self.assertTrue(out["ok"], out["error"])
        self.assertEqual(out["json"]["counts"]["all"], len(mcmail._SEED["ERRORS"]))   # 이력의 해결된 오류 포함 / resolved history errors included  # noqa: SLF001

    def test_chat_link_session_one_handshake_and_store_exceptions(self):
        # 채팅 연결(app/mcmail_link.py) — 주소 치환 · 핸드셰이크 1번 · 도구 오류 → 스토어 예외 · 전송 실패 → Unavailable
        # The chat link (app/mcmail_link.py): URL substitution, one handshake, tool errors → store exceptions, failures → Unavailable
        seen: list = []
        self.stack.enter_context(patch.dict(os.environ, {"AI365_BASE_URL": "http://localhost:65529", "FLOW_API_ALLOW_PRIVATE": "0"}))
        self.stack.enter_context(patch.object(mcmail_link, "TRANSPORT", self.transport(seen=seen)))
        self.assertEqual(mcmail_link.server_url(), "http://127.0.0.1:65529/mock/mcosmetic/mcp")   # localhost → 127.0.0.1
        with mcmail_link.Session() as link:
            got = link.call("get_work_status", {"target": "errors", "customer": None})   # None 인자는 뺀다 / None args dropped
            self.assertIn("미해결 API 오류는 **2건**", got["answer"])
            with self.assertRaises(mcmail.MailNotFound) as nf:
                link.call("get_mail", {"email_id": "E-0000"})
            self.assertEqual((str(nf.exception), nf.exception.status), ("메일을 찾을 수 없습니다.", 404))
            with self.assertRaises(mcmail.MailValidationError) as bad:
                link.call("list_mails", {"view": "inbox", "filter": "err"})
            self.assertNotIsInstance(bad.exception, mcmail.MailNotFound)
            self.assertEqual(bad.exception.status, 422)
            with patch.object(mcmail, "create_order", side_effect=mcmail.MailConflict("충돌")):
                with self.assertRaises(mcmail.MailConflict):
                    link.call("create_order", {"email_id": "E-1005"})
            self.assertEqual(link.tools(), ["get_work_status", "get_mail", "list_mails", "create_order"])
        self.assertEqual([m for _u, m, _n in seen], ["initialize", "notifications/initialized", "tools/call", "tools/call",
                                                     "tools/call", "tools/call"])   # 핸드셰이크 1번 / one handshake
        self.assertEqual({u for u, _m, _n in seen}, {"http://127.0.0.1:65529/mock/mcosmetic/mcp"})
        self.assertEqual(seen[2][2], "get_work_status")
        # 인증 거부(401) → Unavailable, 서버 문구가 되풀이한 키는 가린다 / auth rejection → Unavailable with the echoed key masked
        with patch.object(mcmail_link, "TRANSPORT", self.transport(auth="Bearer wrong")):
            with mcmail_link.Session() as link, self.assertRaises(mcmail_link.Unavailable) as ctx:
                link.call("get_dashboard", {})
            self.assertEqual(link.tools(), [])
        self.assertIn("HTTP 401", str(ctx.exception))
        self.assertNotIn(mock_mcosmetic.DEMO_KEY, str(ctx.exception))
        # 연결 실패 · 사설망 가드도 Unavailable / a refused connection and the private-network guard are Unavailable too
        def refuse(request):
            raise httpx.ConnectError("connection refused", request=request)
        with patch.object(mcmail_link, "TRANSPORT", httpx.MockTransport(refuse)):
            with mcmail_link.Session() as link, self.assertRaises(mcmail_link.Unavailable):
                link.call("get_dashboard")
        with patch.dict(os.environ, {"AI365_BASE_URL": "ftp://127.0.0.1"}), \
             patch.object(mcmail_link, "TRANSPORT", httpx.MockTransport(refuse)):
            with mcmail_link.Session() as link, self.assertRaises(mcmail_link.Unavailable) as guard:
                link.call("get_dashboard")
        self.assertIn("주소를 쓸 수 없습니다", str(guard.exception))

    def test_chat_link_follows_the_edited_connection(self):
        # 리소스 관리에서 고친 연결(2026-10-06): 주소 · 타임아웃을 쓰고, 쓰지 않는 도구는 서버로 보내지 않으며, 고친 키는 문구에서 가린다
        # The connection edited in Resource Management (2026-10-06): its URL and timeout are used, a disabled tool never reaches
        # the server, and an edited key is masked in messages
        seen: list = []
        self.stack.enter_context(patch.dict(os.environ, {"AI365_BASE_URL": "http://localhost:65529", "FLOW_API_ALLOW_PRIVATE": "0"}))
        self.stack.enter_context(patch.object(mcmail_link, "TRANSPORT", self.transport(seen=seen)))
        row = next(b for b in work_agents_api.list_all("")["builtin"] if b["id"] == "agent_email")
        tools = [dict(t, enabled=t["name"] != "list_errors") for t in row["config"]["tools"]]
        builtin_agents.save("agent_email", {"description": row["description"],
                                            "config": dict(row["config"], url="http://localhost:65530/mock/mcosmetic/mcp", timeout=45, tools=tools)})
        self.assertEqual(mcmail_link.server_url(), "http://127.0.0.1:65530/mock/mcosmetic/mcp")
        with mcmail_link.Session() as link:
            with self.assertRaises(mcmail.MailValidationError) as off:
                link.call("list_errors", {"status": "all"})
            self.assertEqual(off.exception.status, 403)
            self.assertIn("사용하지 않도록", str(off.exception))
            got = link.call("get_work_status", {"target": "errors"})
            self.assertIn("미해결 API 오류는 **2건**", got["answer"])
            self.assertEqual(link._config()["timeout"], 45)
        self.assertEqual({u for u, _m, _n in seen}, {"http://127.0.0.1:65530/mock/mcosmetic/mcp"})
        self.assertNotIn("list_errors", [n for _u, _m, n in seen])
        # 서버가 거부한 고친 키는 Unavailable 문구에 나오지 않는다 / a refused edited key never shows in the Unavailable text
        builtin_agents.save("agent_email", {"description": row["description"],
                                            "config": dict(row["config"], auth={"type": "bearer", "key": "custom-key-123", "name": "Authorization"})})

        def echo(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="bad token " + request.headers.get("authorization", ""))
        with patch.object(mcmail_link, "TRANSPORT", httpx.MockTransport(echo)):
            with mcmail_link.Session() as link, self.assertRaises(mcmail_link.Unavailable) as ctx:
                link.call("get_dashboard", {})
        self.assertNotIn("custom-key-123", str(ctx.exception))
        builtin_agents.reset("agent_email")
        self.assertEqual(mcmail_link.server_url(), "http://127.0.0.1:65529/mock/mcosmetic/mcp")

    def test_lost_reply_is_unavailable_and_a_write_points_to_the_screen(self):
        # 2026-09-30 리뷰 반영: 응답 본문을 읽다 끊긴 httpx 오류도 Unavailable 이고, 실행 도구였으면 "이미 처리됐을 수 있다"로 안내한다.
        # 401 문구는 키를 되풀이하지 않는다. / 2026-09-30 review: an httpx error while reading the reply body is Unavailable too,
        # and a write tool's lost reply says it may already be done; the 401 text never echoes the key.
        from app.agents import work

        class Broken(httpx.SyncByteStream):
            def __iter__(self):
                raise httpx.ReadTimeout("The read operation timed out")

        def handle(request: httpx.Request) -> httpx.Response:
            msg = json.loads(request.content)
            if msg.get("method") == "tools/call":
                return httpx.Response(200, headers={"content-type": "application/json"}, stream=Broken())
            status, body = mcp.handle(msg, request.headers.get("authorization"))
            return httpx.Response(status) if body is None else httpx.Response(status, headers={"content-type": "application/json"}, json=body)
        self.stack.enter_context(patch.dict(os.environ, {"AI365_BASE_URL": "http://localhost:65529", "FLOW_API_ALLOW_PRIVATE": "0"}))
        self.stack.enter_context(patch.object(mcmail_link, "TRANSPORT", httpx.MockTransport(handle)))
        with mcmail_link.Session() as link, self.assertRaises(mcmail_link.Unavailable) as write:
            link.call("run_erp", {"email_id": "E-1001"})
        self.assertTrue(write.exception.write)
        self.assertEqual(write.exception.user_message, mcmail_link.UNANSWERED)
        with mcmail_link.Session() as link, self.assertRaises(mcmail_link.Unavailable) as read:
            link.call("get_mail", {"email_id": "E-1001"})
        self.assertFalse(read.exception.write)
        self.assertEqual(read.exception.user_message, mcmail_link.UNREACHABLE)
        self.assertEqual(work._unreachable(write.exception)["fail_reason"], mcmail_link.UNANSWERED)
        self.assertTrue(work._unreachable(read.exception)["fail_reason"].startswith(mcmail_link.UNREACHABLE))
        self.assertEqual(mcmail_link.WRITE_TOOLS & {"get_mail", "get_work_status"}, set())
        self.assertIn("send_reply", mcmail_link.WRITE_TOOLS)
        _status, body = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, "Bearer wrong")
        self.assertNotIn(mock_mcosmetic.DEMO_KEY, body["error"]["message"])


class HttpRouteTests(McpBase):
    def test_route_serves_json_rpc_next_to_the_rest_mock(self):
        app = FastAPI()
        app.include_router(mock_mcosmetic.router)
        app.include_router(mcp.router)
        client = TestClient(app)
        h = {"Authorization": AUTH}
        r = client.post("/mock/mcosmetic/mcp", json=rpc("ping"), headers=h)
        self.assertEqual((r.status_code, r.json()["result"]), (200, {}))
        self.assertEqual(client.post("/mock/mcosmetic/mcp", json=rpc("ping")).status_code, 401)
        self.assertEqual(client.post("/mock/mcosmetic/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=h).status_code, 202)
        batch = client.post("/mock/mcosmetic/mcp", json=[rpc("ping", mid=1), rpc("tools/list", mid=2)], headers=h)
        self.assertEqual([b["id"] for b in batch.json()], [1, 2])
        self.assertEqual(client.get("/mock/mcosmetic/mcp").status_code, 405)
        self.assertEqual(client.post("/mock/mcosmetic/mcp", content=b"{bad", headers=h).status_code, 400)
        called = client.post("/mock/mcosmetic/mcp", json=rpc("tools/call", {"name": "get_mail", "arguments": {"email_id": "E-1001"}}), headers=h)
        self.assertEqual(called.json()["result"]["structuredContent"]["email"]["emailId"], "E-1001")
        # 같은 접두의 가상 ERP REST 는 종전 그대로(인증 · 응답) / the REST mock under the same prefix is unchanged
        self.assertEqual(client.get("/mock/mcosmetic/erp/v1/inventory/on-hand", params={"item": "MC-CAL-SR050"}).status_code, 401)
        self.assertEqual(client.get("/mock/mcosmetic/erp/v1/inventory/on-hand", params={"item": "MC-CAL-SR050"}, headers=h).status_code, 200)


if __name__ == "__main__":
    unittest.main()
