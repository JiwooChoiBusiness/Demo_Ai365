# -*- coding: utf-8 -*-
"""Agentic 모드 API(2026-10-19): 세션 CRUD · 소유자 범위(남의 세션 404) · 폴더 검증(422) · 메시지 → 이벤트 · 승인 · 중단 ·
동시 실행 상한(409) · 설정 GET/PUT 검증 · 파일 보기(폴더 밖 403) · background 작업 · 메뉴 권한(403) · SSE 재생과 라이브 · git.
실제 LLM · 실 DB · 네트워크 없음(임시 DB · 가짜 모델 · 권한 함수 패치). SSE 는 ASGI 앱을 직접 불러 짧게 읽고 끊는다.

Agentic mode API (2026-10-19): session CRUD, owner scope (others get 404), folder validation (422), messages to events,
approvals, stop, the concurrency cap (409), settings GET/PUT validation, file viewing (outside is 403), background tasks,
the menu permission (403), SSE replay and live events, git. No real LLM, real DB or network (temp DB, fake model, patched
permission lookup). SSE calls the ASGI app directly, reads briefly and disconnects."""
import asyncio
import json
import os
import shlex
import socket
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from unittest.mock import patch
from urllib.parse import quote

import httpx
from fastapi import FastAPI

from db_fixture import isolate_db
from app import agentic_api, agentic_exec, agentic_runner as runner, agentic_store, agentic_tools

SESSION_KEYS = {"id", "owner", "title", "folder", "extra_folders", "model", "effort", "perm_mode", "status", "context_pct",
                "rules", "steps", "last_seq", "created", "updated",
                # 2차 계약 A 절의 세션 키 / phase-2 contract section A session keys
                "connectors", "notify", "seen_seq", "prev_perm", "hooks_trust", "compact_seq",
                # 내 컴퓨터 폴더 계약 A 절(2026-10-20) / browser-folder contract section A
                "kind"}
LIGHT_KEYS = {"id", "title", "folder", "model", "perm_mode", "status", "updated", "created", "steps",
              "notify", "seen_seq", "last_seq",   # 2차: 사이드바 미확인 점 / phase 2: the sidebar's unseen dot
              "kind"}                             # 내 컴퓨터 폴더(2026-10-20) / browser folders


def py(code: str) -> str:
    """이 파이썬으로 code 를 돌리는 명령 한 줄(code 안에는 작은따옴표만) / a command running code with this Python"""
    if os.name == "nt":
        return f'"{sys.executable}" -c "{code}"'
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def fake_model(*script):
    """호출 순서대로 대본을 돌려주는 가짜 generate_calls(칸 = dict 또는 블록 함수) / a scripted fake generate_calls"""
    steps = list(script)
    lock = threading.Lock()

    def fake(messages, system=None, tools=None, tier="main", models=None):
        with lock:
            step = steps.pop(0) if steps else {"text": "끝났습니다."}
        if callable(step):
            step = step()
        return {"calls": [{"name": n, "args": a} for n, a in step.get("calls", [])], "text": step.get("text", "")}
    return fake


def eff_of(acting_user_id):
    """권한 함수 대역: ''·비숫자 = 슈퍼(None), 7 = m_agentic 있음, 그 밖 숫자 = 없음 / stand-in for resources_api._eff"""
    aid = (acting_user_id or "").strip()
    if not aid or not aid.isdigit():
        return None
    return {"no": int(aid), "menus": {"m_home": True, "m_agentic": True} if aid == "7" else {"m_home": True},
            "nodes": {}, "mgmt": {}, "read": {}}


async def read_sse(app, path: str, want: int = 1, timeout: float = 10.0, headers: list | None = None) -> tuple[int | None, bytes]:
    """ASGI 앱을 직접 불러 SSE 를 읽다가 data 줄이 want 개 오면 연결을 끊는다 / read SSE, disconnect after `want` data lines"""
    url = httpx.URL("http://test" + path)
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1", "method": "GET",
             "scheme": "http", "path": url.path, "raw_path": url.raw_path.split(b"?")[0], "query_string": url.query,
             "root_path": "", "headers": [(b"host", b"test"), (b"accept", b"text/event-stream"), *(headers or [])],
             "client": ("127.0.0.1", 50000), "server": ("test", 80)}
    body = bytearray()
    status: dict = {}
    gone = asyncio.Event()
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await gone.wait()
        return {"type": "http.disconnect"}

    async def send(msg):
        if msg["type"] == "http.response.start":
            status["code"] = msg["status"]
        elif msg["type"] == "http.response.body":
            body.extend(msg.get("body", b""))
            if body.count(b"data:") >= want:
                gone.set()

    await asyncio.wait_for(app(scope, receive, send), timeout)
    return status.get("code"), bytes(body)


class ApiCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        agentic_store.init_agentic()
        self.root = os.path.realpath(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.outside = os.path.realpath(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.proj = os.path.join(self.root, "proj")
        os.makedirs(os.path.join(self.proj, "sub"))
        with open(os.path.join(self.proj, "README.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("# 데모\nhello\n")
        with open(os.path.join(self.proj, "data.bin"), "wb") as f:
            f.write(b"\x00\x01\x02\x03")
        with open(os.path.join(self.outside, "secret.txt"), "w", encoding="utf-8") as f:
            f.write("밖\n")
        agentic_store.put_settings({"allowed_folders": [self.root], "deny_commands": [r"\bdanger_word\b"]})
        self.stack.enter_context(patch("app.resources_api._eff", side_effect=eff_of))
        self.stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")))
        self.stack.enter_context(patch("app.llm.generate_grounded_meta", side_effect=AssertionError("unexpected web")))
        runner.REGISTRY.clear()
        runner.SUBS.clear()
        self.gates: list[threading.Event] = []
        self.app = FastAPI()
        self.app.include_router(agentic_api.router)

    async def asyncTearDown(self):
        for g in self.gates:
            g.set()
        for r in list(runner.REGISTRY.values()):
            if r.alive:
                r.task.cancel()
                await asyncio.wait({r.task}, timeout=5)
        runner.REGISTRY.clear()
        runner.SUBS.clear()

    async def req(self, method, path, json=None):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
            return await client.request(method, path, json=json)

    async def make(self, who: str = "", **extra) -> dict:
        r = await self.req("POST", "/api/agentic/sessions", {"acting_user_id": who, "folder": self.proj, **extra})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["session"]

    async def events(self, sid: str, who: str = "", after: int = 0) -> list[dict]:
        r = await self.req("GET", f"/api/agentic/sessions/{sid}/events?acting_user_id={who}&after={after}&limit=2000")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["events"]

    async def until(self, pred, timeout: float = 15.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if await pred():
                return
            await asyncio.sleep(0.02)
        self.fail("시간 안에 조건이 맞지 않았습니다 / condition not met in time")

    async def idle(self, sid: str) -> list[dict]:
        async def done():
            evs = await self.events(sid)
            return bool(evs) and evs[-1]["kind"] == "status" and evs[-1]["payload"]["state"] in ("idle", "error", "stopped")
        await self.until(done)
        return await self.events(sid)

    async def pending(self, sid: str) -> list[dict]:
        latest: dict[str, dict] = {}
        for e in await self.events(sid):
            if e["kind"] == "approval":
                latest[e["payload"]["approval_id"]] = e["payload"]
        return [p for p in latest.values() if p["decision"] == "pending"]


class SessionApiTests(ApiCase):
    async def test_crud_light_list_owner_scope_and_delete(self):
        s = await self.make()
        self.assertEqual(set(s), SESSION_KEYS)
        self.assertEqual((s["owner"], s["title"], s["folder"], s["model"], s["perm_mode"], s["status"], s["extra_folders"],
                          s["rules"], s["last_seq"]),
                         ("", "proj", os.path.realpath(self.proj), "gemini-3.7-flash", "auto", "idle", [], [], 0))
        self.assertTrue(s["id"].startswith("ag_"))
        named = await self.make(title="리팩터링", model="gemini-3.7-flash", perm_mode="ask")
        self.assertEqual((named["title"], named["model"], named["perm_mode"]), ("리팩터링", "gemini-3.7-flash", "ask"))
        listed = (await self.req("GET", "/api/agentic/sessions?acting_user_id=")).json()["sessions"]
        self.assertEqual({tuple(sorted(x)) for x in listed}, {tuple(sorted(LIGHT_KEYS))})
        self.assertEqual({x["id"] for x in listed}, {s["id"], named["id"]})
        got = (await self.req("GET", f"/api/agentic/sessions/{s['id']}?acting_user_id=")).json()
        self.assertEqual((got["session"]["id"], got["git"]), (s["id"], {"repo": False}))
        # 고치기 / patch
        sub = os.path.join(self.proj, "sub")
        r = await self.req("PATCH", f"/api/agentic/sessions/{s['id']}",
                           {"acting_user_id": "", "title": "새 이름", "model": "gemini-3.5-flash-lite", "perm_mode": "ask",
                            "extra_folders": [sub, sub]})
        self.assertEqual(r.status_code, 200, r.text)
        p = r.json()["session"]
        self.assertEqual((p["title"], p["model"], p["perm_mode"], p["extra_folders"]),
                         ("새 이름", "gemini-3.5-flash-lite", "ask", [os.path.realpath(sub)]))
        for bad in ({"model": "gpt-5"}, {"perm_mode": "yolo"}, {"title": "  "}, {"extra_folders": [self.outside]},
                    {"extra_folders": ["relative/path"]}):
            r = await self.req("PATCH", f"/api/agentic/sessions/{s['id']}", {"acting_user_id": "", **bad})
            self.assertEqual(r.status_code, 422, (bad, r.text))
        # 남의 세션은 404, 목록도 소유자별 / other owners get 404 and lists are per owner
        mine7 = await self.make("7")
        self.assertEqual([x["id"] for x in (await self.req("GET", "/api/agentic/sessions?acting_user_id=7")).json()["sessions"]],
                         [mine7["id"]])
        for method, path, body in (("GET", f"/api/agentic/sessions/{s['id']}?acting_user_id=7", None),
                                   ("PATCH", f"/api/agentic/sessions/{s['id']}", {"acting_user_id": "7", "title": "x"}),
                                   ("GET", f"/api/agentic/sessions/{s['id']}/events?acting_user_id=7", None),
                                   ("POST", f"/api/agentic/sessions/{s['id']}/messages", {"acting_user_id": "7", "text": "hi"}),
                                   ("DELETE", f"/api/agentic/sessions/{s['id']}?acting_user_id=7", None),
                                   ("GET", f"/api/agentic/sessions/{mine7['id']}?acting_user_id=", None)):
            self.assertEqual((await self.req(method, path, body)).status_code, 404, (method, path))
        # 지우기 / delete
        r = await self.req("DELETE", f"/api/agentic/sessions/{s['id']}?acting_user_id=")
        self.assertEqual(r.json(), {"ok": True})
        self.assertEqual((await self.req("GET", f"/api/agentic/sessions/{s['id']}?acting_user_id=")).status_code, 404)
        self.assertEqual(agentic_store.list_events(s["id"]), [])

    async def test_folder_must_exist_be_absolute_and_inside_the_allowed_folders(self):
        for folder in (self.outside, os.path.join(self.root, "nope"), "proj", "", os.path.join(self.proj, "README.md")):
            r = await self.req("POST", "/api/agentic/sessions", {"acting_user_id": "", "folder": folder})
            self.assertEqual(r.status_code, 422, (folder, r.text))
        r = await self.req("POST", "/api/agentic/sessions", {"acting_user_id": "", "folder": self.proj, "model": "gpt-5"})
        self.assertEqual(r.status_code, 422)
        self.assertEqual((await self.req("GET", "/api/agentic/sessions?acting_user_id=")).json()["sessions"], [])

    async def test_menu_permission_and_super_only_settings(self):
        denied = {"detail": "Agentic 모드 권한이 없습니다"}
        r = await self.req("GET", "/api/agentic/sessions?acting_user_id=8")
        self.assertEqual((r.status_code, r.json()), (403, denied))
        r = await self.req("POST", "/api/agentic/sessions", {"acting_user_id": "8", "folder": self.proj})
        self.assertEqual((r.status_code, r.json()), (403, denied))
        self.assertEqual((await self.req("GET", "/api/agentic/settings?acting_user_id=8")).status_code, 403)
        self.assertEqual((await self.req("GET", "/api/agentic/settings?acting_user_id=7")).status_code, 200)
        r = await self.req("PUT", "/api/agentic/settings", {"acting_user_id": "7", "settings": {"default_perm": "ask"}})
        self.assertEqual((r.status_code, r.json()), (403, {"detail": "슈퍼관리자 전용 기능입니다"}))
        models = (await self.req("GET", "/api/agentic/models")).json()["models"]
        self.assertEqual(models, [{"id": "gemini-3.7-flash", "label": "Gemini 3.7 Flash"},
                                  {"id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash"},
                                  {"id": "gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash-Lite"}])

    async def test_remote_requests_keep_to_browser_sessions_and_ids_are_numeric_or_empty(self):
        # 비숫자 신원은 이 라우터에서 403(다른 API 의 '비숫자 = 슈퍼' 관례를 받지 않는다) / non-numeric ids are refused here
        for method, path, body in (("GET", "/api/agentic/sessions?acting_user_id=abc", None),
                                   ("GET", "/api/agentic/models?acting_user_id=admin", None),
                                   ("POST", "/api/agentic/sessions", {"acting_user_id": "x7", "folder": self.proj}),
                                   ("PUT", "/api/agentic/settings", {"acting_user_id": "abc", "settings": {}})):
            r = await self.req(method, path, body)
            self.assertEqual(r.status_code, 403, (method, path, r.text))
        self.assertEqual((await self.req("GET", "/api/agentic/sessions?acting_user_id=")).status_code, 200)

        async def remote(method, path, body=None):
            transport = httpx.ASGITransport(app=self.app, client=("10.1.2.3", 5000))
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, json=body)
        # 원격 클라이언트 정책(2026-10-20): 원격은 내 컴퓨터 폴더 세션만, 서버 폴더 세션은 만들 수도 열 수도 없다(목록에서도 빠진다)
        # The remote-client policy (2026-10-20): remote clients get browser-folder sessions only; server-folder sessions can be
        # neither created nor opened, and the list leaves them out
        local = await self.make()
        r = await remote("GET", "/api/agentic/sessions?acting_user_id=")
        self.assertEqual((r.status_code, r.json()), (200, {"sessions": []}))
        self.assertEqual((await remote("GET", "/api/agentic/models")).status_code, 200)
        r = await remote("POST", "/api/agentic/sessions", {"acting_user_id": "", "folder": self.proj})
        self.assertEqual((r.status_code, r.json()), (403, {"detail": "원격에서는 내 컴퓨터 폴더 세션만 만들 수 있습니다"}))
        r = await remote("GET", f"/api/agentic/sessions/{local['id']}?acting_user_id=")
        self.assertEqual((r.status_code, r.json()), (403, {"detail": "원격에서는 내 컴퓨터 폴더 세션만 쓸 수 있습니다"}))
        with patch("app.settings.AGENTIC_ALLOW_REMOTE", True):                          # AGENTIC_ALLOW_REMOTE=1 / remote allowed
            r = await remote("GET", "/api/agentic/sessions?acting_user_id=")
            self.assertEqual((r.status_code, [s["id"] for s in r.json()["sessions"]]), (200, [local["id"]]))
            self.assertEqual((await remote("GET", f"/api/agentic/sessions/{local['id']}?acting_user_id=")).status_code, 200)
        for host, loop in (("127.0.0.1", True), ("127.8.9.1", True), ("::1", True), ("::ffff:127.0.0.1", True),
                           ("testclient", False), ("localhost", False), ("192.168.0.2", False), ("", False)):
            self.assertEqual(agentic_api._is_loopback(host), loop, host)

    async def test_settings_merge_defaults_and_validate(self):
        got = (await self.req("GET", "/api/agentic/settings?acting_user_id=")).json()
        self.assertEqual(got["host"], socket.gethostname())
        st = got["settings"]
        self.assertEqual(set(st), {"allowed_folders", "default_perm", "default_model", "deny_commands", "budgets",
                                   "notify_default", "commands", "skills", "hooks"})   # 2차 설정 키 / phase-2 setting keys
        self.assertEqual((st["allowed_folders"], st["default_perm"], st["default_model"], st["deny_commands"]),
                         ([self.root], "auto", "gemini-3.7-flash", [r"\bdanger_word\b"]))
        self.assertEqual(st["budgets"], agentic_store.DEFAULT_BUDGETS)
        r = await self.req("PUT", "/api/agentic/settings", {"acting_user_id": "", "settings": {"budgets": {"max_steps": 50},
                                                                                              "default_perm": "ask"}})
        self.assertEqual(r.status_code, 200, r.text)
        st = r.json()["settings"]
        self.assertEqual((st["budgets"]["max_steps"], st["budgets"]["max_minutes"], st["default_perm"]), (50, 120, "ask"))
        for bad in ({"deny_commands": ["("]}, {"allowed_folders": ["relative/path"]},
                    {"allowed_folders": [os.path.join(self.root, "nope")]}, {"budgets": {"max_steps": 0}},
                    {"budgets": {"nope": 1}}, {"budgets": {"max_steps": "many"}}, {"default_model": "gpt-5"},
                    {"default_perm": "yolo"}, {"nope": 1}):
            r = await self.req("PUT", "/api/agentic/settings", {"acting_user_id": "", "settings": bad})
            self.assertEqual(r.status_code, 422, (bad, r.text))
        self.assertEqual(agentic_store.get_settings()["budgets"]["max_steps"], 50)   # 실패한 PUT 은 아무것도 바꾸지 않았다 / failed PUTs changed nothing
        # 기본값: 홈의 Desktop · Documents 중 있는 것만 / defaults: only existing Desktop and Documents under the home folder
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, "Documents"))
            with patch("app.agentic_store.Path.home", return_value=agentic_store.Path(home)):
                self.assertEqual(agentic_store.default_folders(), [os.path.realpath(os.path.join(home, "Documents"))])


class RunApiTests(ApiCase):
    async def test_a_message_runs_a_turn_and_events_page_by_seq(self):
        s = await self.make()
        r = await self.req("POST", f"/api/agentic/sessions/{s['id']}/messages", {"acting_user_id": "", "text": "  "})
        self.assertEqual(r.status_code, 422)
        with patch("app.llm.generate_calls", side_effect=fake_model({"calls": [("read_file", {"path": "README.md"})]},
                                                                    {"text": "README 는 두 줄입니다."})):
            r = await self.req("POST", f"/api/agentic/sessions/{s['id']}/messages", {"acting_user_id": "", "text": "README 봐 줘"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual((r.json()["queued"], r.json()["session"]["status"]), (False, "running"))
            evs = await self.idle(s["id"])
        self.assertEqual([e["kind"] for e in evs], ["user", "status", "tool_call", "tool_result", "assistant", "summary",
                                                    "context", "status"])
        self.assertEqual(set(evs[0]), {"seq", "ts", "kind", "payload"})
        page = (await self.req("GET", f"/api/agentic/sessions/{s['id']}/events?acting_user_id=&after=3&limit=2")).json()
        self.assertEqual(([e["seq"] for e in page["events"]], page["last_seq"]), ([4, 5], 8))
        got = (await self.req("GET", f"/api/agentic/sessions/{s['id']}?acting_user_id=")).json()["session"]
        self.assertEqual((got["status"], got["steps"], got["last_seq"]), ("idle", 1, 8))

    async def test_approval_api_decides_once(self):
        s = await self.make()
        with patch("app.llm.generate_calls", side_effect=fake_model({"calls": [("bash", {"command": py("print('danger_word')")})]},
                                                                    {"text": "실행했습니다."})):
            await self.req("POST", f"/api/agentic/sessions/{s['id']}/messages", {"acting_user_id": "", "text": "돌려 봐"})

            async def has_pending():
                return bool(await self.pending(s["id"]))
            await self.until(has_pending)
            aid = (await self.pending(s["id"]))[0]["approval_id"]
            url = f"/api/agentic/sessions/{s['id']}/approvals/{aid}"
            self.assertEqual((await self.req("POST", url, {"acting_user_id": "", "decision": "maybe"})).status_code, 422)
            self.assertEqual((await self.req("POST", f"/api/agentic/sessions/{s['id']}/approvals/a_nope",
                                             {"acting_user_id": "", "decision": "allow"})).status_code, 409)
            self.assertEqual((await self.req("POST", url, {"acting_user_id": "7", "decision": "allow"})).status_code, 404)
            r = await self.req("POST", url, {"acting_user_id": "", "decision": "allow"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual((await self.req("POST", url, {"acting_user_id": "", "decision": "allow"})).status_code, 409)
            evs = await self.idle(s["id"])
        res = [e["payload"] for e in evs if e["kind"] == "tool_result"][0]
        self.assertEqual((res["ok"], res["exit_code"]), (True, 0))
        self.assertIn("danger_word", res["output"])

    async def test_stop_and_the_concurrency_cap(self):
        agentic_store.put_settings({"budgets": {"max_sessions": 1}})
        a, b = await self.make(), await self.make()
        release, entered = threading.Event(), threading.Event()
        self.gates.append(release)

        def hold():
            entered.set()
            release.wait(10)
            return {"text": "늦은 답"}
        with patch("app.llm.generate_calls", side_effect=fake_model(hold)):
            await self.req("POST", f"/api/agentic/sessions/{a['id']}/messages", {"acting_user_id": "", "text": "A"})

            async def started():
                return entered.is_set()
            await self.until(started)
            # 2차: 기본 mode(auto)는 스티어링이라 대기 큐는 mode=queue / phase 2: the default steers, the queue needs mode=queue
            again = await self.req("POST", f"/api/agentic/sessions/{a['id']}/messages",
                                   {"acting_user_id": "", "text": "A2", "mode": "queue"})
            self.assertEqual(again.json()["queued"], True)
            busy = await self.req("POST", f"/api/agentic/sessions/{b['id']}/messages", {"acting_user_id": "", "text": "B"})
            self.assertEqual(busy.status_code, 409)
            self.assertIn("동시 실행 상한", busy.json()["detail"])
            r = await self.req("POST", f"/api/agentic/sessions/{a['id']}/stop", {"acting_user_id": ""})
            self.assertEqual(r.json()["session"]["status"], "stopped")
            release.set()
        evs = await self.events(a["id"])
        self.assertEqual([e["kind"] for e in evs], ["user", "status", "status"])
        self.assertEqual(evs[-1]["payload"]["state"], "stopped")

    async def test_files_view_dirs_text_binary_and_refuse_outside(self):
        s = await self.make()
        base = f"/api/agentic/sessions/{s['id']}/files?acting_user_id="
        d = (await self.req("GET", base)).json()
        self.assertEqual((d["kind"], d["path"], d["rel"]), ("dir", os.path.realpath(self.proj), "."))
        self.assertEqual([(e["name"], e["type"]) for e in d["entries"]], [("sub", "dir"), ("data.bin", "file"), ("README.md", "file")])
        self.assertEqual(set(d["entries"][1]), {"name", "type", "size", "mtime"})
        f = (await self.req("GET", base + "&path=README.md")).json()
        self.assertEqual((f["kind"], f["rel"], f["content"], f["truncated"], f["binary"]), ("file", "README.md", "# 데모\nhello\n", False, False))
        b = (await self.req("GET", base + "&path=data.bin")).json()
        self.assertEqual((b["kind"], b["binary"], "content" in b, b["size"]), ("file", True, False, 4))
        r = await self.req("GET", base + "&path=" + quote(os.path.join(self.outside, "secret.txt")))
        self.assertEqual(r.status_code, 403)
        self.assertEqual((await self.req("GET", base + "&path=" + quote("../.."))).status_code, 403)
        self.assertEqual((await self.req("GET", base + "&path=nope.txt")).status_code, 404)

    async def test_background_tasks_are_listed_and_read(self):
        s = await self.make()
        session = agentic_store.get_session(s["id"])
        ex = agentic_tools.make_executor(session, agentic_store.get_settings())
        tid = ex.run(py("print('bg-hi')"), background=True)["task_id"]
        self.addCleanup(agentic_exec.kill_session_tasks, s["id"])

        async def finished():
            t = (await self.req("GET", f"/api/agentic/sessions/{s['id']}/tasks/{tid}?acting_user_id=")).json()["task"]
            return t["status"] != "running"
        await self.until(finished, 20)
        t = (await self.req("GET", f"/api/agentic/sessions/{s['id']}/tasks/{tid}?acting_user_id=")).json()["task"]
        self.assertEqual((t["status"], t["exit_code"], t["kind"]), ("done", 0, "bash"))
        self.assertIn("bg-hi", t["output"])
        listed = (await self.req("GET", f"/api/agentic/sessions/{s['id']}/tasks?acting_user_id=")).json()["tasks"]
        self.assertEqual([x["id"] for x in listed], [tid])
        self.assertNotIn("output", listed[0])
        other = await self.make()
        self.assertEqual((await self.req("GET", f"/api/agentic/sessions/{other['id']}/tasks/{tid}?acting_user_id=")).status_code, 404)

    async def test_git_branch_is_shown_when_the_folder_is_a_repo(self):
        os.makedirs(os.path.join(self.proj, ".git"))
        s = await self.make()
        with patch.object(agentic_exec, "_git_branch", return_value="feature-x"):
            got = (await self.req("GET", f"/api/agentic/sessions/{s['id']}?acting_user_id=")).json()
        self.assertEqual(got["git"], {"repo": True, "branch": "feature-x"})


class StreamApiTests(ApiCase):
    async def test_stream_replays_after_a_seq_then_goes_live_and_unsubscribes(self):
        s = await self.make()
        with patch("app.llm.generate_calls", side_effect=fake_model({"text": "안녕하세요."})):
            await self.req("POST", f"/api/agentic/sessions/{s['id']}/messages", {"acting_user_id": "", "text": "안녕"})
            evs = await self.idle(s["id"])
        self.assertEqual(len(evs), 6)
        code, body = await read_sse(self.app, f"/api/agentic/sessions/{s['id']}/stream?acting_user_id=&after=0", want=1)
        self.assertEqual(code, 200)
        text = body.decode("utf-8")
        self.assertIn("id: 1", text)
        first = json.loads(next(ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")))
        self.assertEqual((first["seq"], first["kind"], first["payload"]), (1, "user", {"text": "안녕"}))
        self.assertEqual(runner.subscriber_count(s["id"]), 0)                        # 끊으면 구독 해제 / disconnect unsubscribes
        code, body = await read_sse(self.app, f"/api/agentic/sessions/{s['id']}/stream?acting_user_id=&after=4", want=2)
        self.assertEqual([json.loads(ln[5:])["seq"] for ln in body.decode("utf-8").splitlines() if ln.startswith("data:")], [5, 6])
        # 브라우저가 스스로 다시 붙으면 Last-Event-ID 뒤부터 / a browser's own reconnect resumes after Last-Event-ID
        code, body = await read_sse(self.app, f"/api/agentic/sessions/{s['id']}/stream?acting_user_id=&after=0", want=1,
                                    headers=[(b"last-event-id", b"5")])
        self.assertEqual([json.loads(ln[5:])["seq"] for ln in body.decode("utf-8").splitlines() if ln.startswith("data:")], [6])
        # 라이브: 연결해 둔 채 새 이벤트가 생기면 흘러온다 / live: a new event flows while connected
        reader = asyncio.ensure_future(read_sse(self.app, f"/api/agentic/sessions/{s['id']}/stream?acting_user_id=&after=6", want=1))

        async def subscribed():
            return runner.subscriber_count(s["id"]) == 1
        await self.until(subscribed)
        runner.emit(s["id"], "status", {"state": "idle", "note": "라이브"})
        code, body = await reader
        live = json.loads(next(ln[5:] for ln in body.decode("utf-8").splitlines() if ln.startswith("data:")))
        self.assertEqual((live["seq"], live["payload"]["note"]), (7, "라이브"))
        self.assertEqual(runner.subscriber_count(s["id"]), 0)
        # 권한 · 소유자 / permission and owner
        self.assertEqual((await read_sse(self.app, f"/api/agentic/sessions/{s['id']}/stream?acting_user_id=8"))[0], 403)
        self.assertEqual((await read_sse(self.app, f"/api/agentic/sessions/{s['id']}/stream?acting_user_id=7"))[0], 404)


if __name__ == "__main__":
    unittest.main()
