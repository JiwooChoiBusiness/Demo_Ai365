# -*- coding: utf-8 -*-
"""Agentic 내 컴퓨터 폴더(브라우저) 세션(2026-10-20, docs/agentic-browser-folder-contract.md H Python): 저장소 kind 열 · 이름 검증 ·
API 생성(허용 폴더 검사 없음, 잘못된 kind 422, extra_folders 422) · specs_for 에 bash 없음 · classify 가 outside 를 묻지 않음 ·
가짜 브라우저(러너 구독 큐에서 tool_request 를 받아 메모리 트리로 F3 의 op 를 흉내 내고 agentic_browser.resolve 로 답하는 asyncio
태스크)로 read(줄 자르기 · extracted) · write(diff) · edit(CRLF · 0곳 · 여러 곳 · 문서 거절) · list_dir(정렬 · 상한) · glob(서버
정규식) · grep 전달 · 오류 코드 문구 · 시간 초과(짧게 패치) · 중단이 대기 요청을 취소 · 루프 스레드에서 부르면 RuntimeError · 러너 턴
(규칙 파일 읽기 · bash 거절 · 훅 없음 · 체크포인트 없음 · /clear · /commit 거절) · API tool-results 404/409 · tool-requests · extract
(txt 거절 422 · docx 본문 · 20MB 413) · files 409 · outputs/download 409 · 스트림이 transient 를 event: tool_request 로 보냄.
실제 LLM · 실 DB · 네트워크 없음(임시 DB · 가짜 모델 · 가짜 브라우저).

Agentic browser-folder sessions (2026-10-20, contract section H, Python): the store's kind column and name checks, API
creation (no allowed-folder check, 422 for a bad kind or extra_folders), no bash in specs_for, classify never asking
outside, and through a fake browser (an asyncio task that takes tool_request events from the runner's subscriber queue,
runs F3's ops on an in-memory tree and answers through agentic_browser.resolve): read (slicing, extracted), write (diff),
edit (CRLF, zero and many matches, documents refused), list_dir (sorting, cap), glob (server regex), grep passing,
error-code wording, timeouts (patched short), stop cancelling pending requests, RuntimeError on the loop thread, runner
turns (rules file, bash refused, no hooks, no checkpoints, /clear, /commit refused), the API's tool-results 404/409,
tool-requests, extract (422 for txt, docx text, 413 over 20 MB), files 409, outputs/download 409 and the stream sending
transient events as event: tool_request. No real LLM, real DB or network (temp DB, fake model, fake browser)."""
import asyncio
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import zipfile
from contextlib import ExitStack
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from db_fixture import isolate_db
from app import agentic_api, agentic_browser as ab, agentic_exec, agentic_runner as runner, agentic_store, agentic_tools

NAME = "경동"
DOC_EXTS = ("pdf", "docx", "pptx", "xlsx")


def eff_of(acting_user_id):
    """권한 함수 대역: '' = 슈퍼(None), 7 = m_agentic 있음, 그 밖 숫자 = 없음 / stand-in for resources_api._eff"""
    aid = (acting_user_id or "").strip()
    if not aid or not aid.isdigit():
        return None
    return {"no": int(aid), "menus": {"m_home": True, "m_agentic": True} if aid == "7" else {"m_home": True},
            "nodes": {}, "mgmt": {}, "read": {}}


class _Err(Exception):
    def __init__(self, code: str, msg: str = ""):
        super().__init__(msg or code)
        self.code, self.msg = code, msg


class FakeBrowser:
    """메모리 트리로 F3 의 op 를 흉내 내는 가짜 브라우저. 러너 구독 큐(subscribe)에서 transient tool_request 를 받아 실행하고
    agentic_browser.resolve 로 답한다. hold = 답하지 않는다(시간 초과 · 중단), force = (코드, 문구) 로 실패 답.
    A fake browser running F3's ops on an in-memory tree: it takes transient tool_request events from the runner's
    subscriber queue and answers through agentic_browser.resolve. hold = never answer (timeouts, stops), force = fail
    with (code, message)."""

    def __init__(self, sid: str, name: str = NAME):
        self.sid, self.name = sid, name
        self.files: dict[str, bytes] = {}
        self.dirs: set[str] = set()
        self.mtimes: dict[str, float] = {}   # 밀리초(lastModified) / milliseconds (lastModified)
        self.docs: dict[str, str] = {}       # 문서 → /extract 가 뽑았을 본문 / documents → the text /extract would give
        self.doc_cut: set[str] = set()       # /extract 가 상한에서 자른 문서 / documents /extract cut at its cap
        self.encodings: dict[str, str] = {}  # 브라우저가 알아낸 인코딩 / encodings the browser detected
        self.seen: list[dict] = []
        self.done: list[str] = []
        self.hold = False
        self.force: tuple[str, str] | None = None
        self.q = None
        self.task = None

    def put(self, rel: str, data, mtime_ms: float | None = None) -> None:
        b = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        self.files[rel] = b
        parts = rel.split("/")
        for i in range(1, len(parts)):
            self.dirs.add("/".join(parts[:i]))
        self.mtimes[rel] = time.time() * 1000 if mtime_ms is None else mtime_ms

    def text(self, rel: str) -> bytes:
        return self.files[rel]

    def start(self) -> "FakeBrowser":
        self.q = runner.subscribe(self.sid)
        self.task = asyncio.ensure_future(self._loop())
        return self

    async def close(self) -> None:
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.q is not None:
            runner.unsubscribe(self.sid, self.q)

    def ops(self, op: str) -> list[dict]:
        return [p for p in self.seen if p["op"] == op]

    async def _loop(self) -> None:
        while True:
            ev = await self.q.get()
            if ev is runner.CLOSE:
                return
            if not ev.get("transient"):
                continue
            p = ev["payload"]
            if p.get("done"):
                self.done.append(p["request_id"])
                continue
            self.seen.append(p)
            if self.hold:
                continue
            ok, result, code, error = self.run(p["op"], p.get("args") or {})
            ab.resolve(self.sid, p["request_id"], ok, result, error, code)

    # ── F3 흉내 / imitating F3 ──
    def norm(self, raw) -> str:
        """실제 브라우저처럼 정규화만 하고 폴더 이름 접두는 벗기지 않는다(2026-10-20 결정) / normalize only, like the browser;
        the folder-name prefix is never stripped (decision, 2026-10-20)"""
        s = str(raw if raw is not None else "").replace("\\", "/")
        while s.startswith("./"):
            s = s[2:]
        if s.startswith("/") or re.match(r"^[A-Za-z]:", s):
            raise _Err("outside")
        parts = [p for p in s.split("/") if p not in ("", ".")]
        if ".." in parts:
            raise _Err("outside")
        return "/".join(parts)

    def isdir(self, rel: str) -> bool:
        return rel == "" or rel in self.dirs

    def under(self, rel: str, skip=()) -> list[str]:
        prefix = rel + "/" if rel else ""
        out = []
        for f in sorted(self.files):
            if not f.startswith(prefix):
                continue
            if any(seg in skip for seg in f[len(prefix):].split("/")[:-1]):
                continue
            out.append(f)
        return out

    def run(self, op: str, a: dict):
        if self.force is not None:
            return False, None, self.force[0], self.force[1]
        try:
            rel = self.norm(a.get("path"))
            return True, getattr(self, "op_" + op)(rel, a), "", ""
        except _Err as e:
            return False, None, e.code, e.msg

    def op_list(self, rel, a):
        if rel in self.files:
            raise _Err("notdir")
        if not self.isdir(rel):
            raise _Err("notfound")
        prefix = rel + "/" if rel else ""
        kinds: dict[str, str] = {}
        for f in self.files:
            if f.startswith(prefix):
                rest = f[len(prefix):]
                kinds[rest.split("/")[0]] = "dir" if "/" in rest else "file"
        for d in self.dirs:
            if d.startswith(prefix) and "/" not in d[len(prefix):]:
                kinds[d[len(prefix):]] = "dir"
        names = sorted(kinds, reverse=True)   # 서버가 정렬하는지 보려고 거꾸로 / reversed, so the server must sort
        entries = [{"name": n, "type": kinds[n], "size": len(self.files.get(prefix + n, b"")) if kinds[n] == "file" else 0,
                    "mtime": self.mtimes.get(prefix + n, 0)} for n in names]
        # 실제 브라우저처럼 500개에서 자르고 자르기 전 수(total)를 준다 / like the browser: cut at 500, report the count before
        return {"entries": entries[:500], "truncated": len(entries) > 500, "total": len(entries)}

    def op_read(self, rel, a):
        if self.isdir(rel):
            raise _Err("isdir")
        if rel not in self.files:
            raise _Err("notfound")
        data = self.files[rel]
        if len(data) > int(a.get("max_bytes") or 0):
            raise _Err("toolarge")
        if rel.rsplit(".", 1)[-1].lower() in DOC_EXTS:
            return {"text": self.docs.get(rel, ""), "size": len(data), "binary": False, "extracted": True,
                    "truncated": rel in self.doc_cut}
        if b"\x00" in data[:8192]:
            return {"text": "", "size": len(data), "binary": True, "extracted": False, "truncated": False}
        out = {"text": data.decode("utf-8", errors="replace"), "size": len(data), "binary": False, "extracted": False,
               "truncated": False}
        if rel in self.encodings:
            out["encoding"] = self.encodings[rel]
        return out

    def op_write(self, rel, a):
        if not rel or self.isdir(rel):
            raise _Err("isdir")
        old = None
        existed = rel in self.files
        if existed and b"\x00" not in self.files[rel][:8192]:
            old = self.files[rel].decode("utf-8", errors="replace")
        text = str(a.get("text") or "")
        self.put(rel, text)
        return {"created": not existed, "bytes": len(text.encode("utf-8")), "old_text": old}

    def op_walk(self, rel, a):
        if rel in self.files:
            raise _Err("notdir")
        if not self.isdir(rel):
            raise _Err("notfound")
        prefix = rel + "/" if rel else ""
        out = [{"rel": f[len(prefix):], "size": len(self.files[f]), "mtime": self.mtimes[f]}
               for f in self.under(rel, set(a.get("skip") or []))]
        mx = int(a.get("max") or 50000)
        return {"files": out[:mx], "capped": len(out) > mx}

    def op_grep(self, rel, a):
        try:   # JS RegExp(pattern, flags) 대역 / stand-in for JS RegExp(pattern, flags)
            rx = re.compile(a.get("pattern") or "", re.IGNORECASE if "i" in (a.get("flags") or "") else 0)
        except re.error as e:
            raise _Err("exec", f"정규식 오류: {e}")
        name_rx = re.compile(a["glob_re"], re.IGNORECASE) if a.get("glob_re") else None
        if rel in self.files:
            targets, prefix = [rel], rel.rsplit("/", 1)[0] + "/" if "/" in rel else ""
        elif self.isdir(rel):
            targets, prefix = self.under(rel, set(a.get("skip") or [])), (rel + "/" if rel else "")
        else:
            raise _Err("notfound")
        mx = int(a.get("max_results") or 200)
        matches, files, truncated = [], 0, False
        for f in targets:
            inner = f[len(prefix):]
            if name_rx is not None and not name_rx.match(inner if a.get("by_path") else inner.rsplit("/", 1)[-1]):
                continue
            data = self.files[f]
            if b"\x00" in data[:8192]:
                continue
            hit = False
            for i, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    matches.append(f"{f}:{i}:{line[:300]}")
                    hit = True
                    if len(matches) >= mx:
                        truncated = True
                        break
            files += int(hit)
            if len(matches) >= mx:
                break
        return {"matches": matches, "count": len(matches), "files": files, "truncated": truncated}


class FakeModel:
    """호출 순서대로 대본을 돌려주는 가짜 llm.generate_calls(칸 = {"calls": [(이름, 인자)], "text": 글}) / a scripted fake"""

    def __init__(self, *script):
        self.script = list(script)
        self.seen: list[dict] = []
        self.lock = threading.Lock()

    def __call__(self, messages, system=None, tools=None, tier="main", models=None):
        with self.lock:
            self.seen.append({"messages": [dict(m) for m in messages], "system": system, "tools": tools})
            step = self.script.pop(0) if self.script else {"text": "끝났습니다."}
        if callable(step):
            step = step()
        return {"calls": [{"name": n, "args": a} for n, a in step.get("calls", [])], "text": step.get("text", "")}


async def read_sse(app, path: str, want: int = 1, timeout: float = 10.0,
                   client: tuple = ("127.0.0.1", 50000)) -> tuple[int | None, bytes]:
    """ASGI 앱을 직접 불러 SSE 를 읽다가 data 줄이 want 개 오면 연결을 끊는다 / read SSE, disconnect after `want` data lines"""
    url = httpx.URL("http://test" + path)
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1", "method": "GET",
             "scheme": "http", "path": url.path, "raw_path": url.raw_path.split(b"?")[0], "query_string": url.query,
             "root_path": "", "headers": [(b"host", b"test"), (b"accept", b"text/event-stream")],
             "client": client, "server": ("test", 80)}
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


def docx_bytes(text: str) -> bytes:
    """본문 한 문단짜리 최소 docx(압축 + word/document.xml) / a minimal one-paragraph docx"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml",
                   '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
                   f'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    return buf.getvalue()


class BrowserCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        agentic_store.init_agentic()
        self.root = os.path.realpath(self.stack.enter_context(tempfile.TemporaryDirectory()))
        agentic_store.put_settings({"allowed_folders": [self.root], "deny_commands": [r"\bdanger_word\b"]})
        self.stack.enter_context(patch("app.resources_api._eff", side_effect=eff_of))
        self.stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")))
        self.stack.enter_context(patch("app.llm.generate_grounded_meta", side_effect=AssertionError("unexpected web")))
        self.stack.enter_context(patch("app.notify.send_mail", side_effect=AssertionError("unexpected mail")))
        self.sid = agentic_store.create_session("", NAME, kind="browser")["id"]
        runner.REGISTRY.clear()
        runner.SUBS.clear()
        runner._BUSY.clear()
        ab.PENDING.clear()
        ab._FINISHED.clear()
        self.browsers: list[FakeBrowser] = []
        self.app = FastAPI()
        self.app.include_router(agentic_api.router)

    async def asyncTearDown(self):
        ab.cancel_all("테스트 끝 / test over")   # 붙잡힌 워커 스레드를 깨운다 / wake held worker threads
        for b in self.browsers:
            await b.close()
        for r in list(runner.REGISTRY.values()):
            if r.alive:
                r.task.cancel()
                await asyncio.wait({r.task}, timeout=5)
        runner.REGISTRY.clear()
        runner.SUBS.clear()
        runner._BUSY.clear()
        runner._BROWSER_RULES.clear()
        runner.LOOP = None
        ab.PENDING.clear()
        ab._FINISHED.clear()

    def browser(self, sid: str | None = None, **files) -> FakeBrowser:
        b = FakeBrowser(sid or self.sid)
        for rel, data in files.items():
            b.put(rel, data)
        self.browsers.append(b.start())
        return b

    def ex(self, sid: str | None = None) -> ab.BrowserExecutor:
        return ab.BrowserExecutor(NAME, session_id=sid or self.sid)

    async def call(self, fn, *args, **kwargs):
        return await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), 15)

    async def until(self, pred, timeout: float = 15.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if pred():
                return
            await asyncio.sleep(0.02)
        self.fail("시간 안에 조건이 맞지 않았습니다 / condition not met in time")

    async def req(self, method, path, json=None):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
            return await client.request(method, path, json=json)

    def events(self, sid: str | None = None) -> list[dict]:
        return agentic_store.list_events(sid or self.sid, 0, 10000)

    def of(self, kind: str, sid: str | None = None) -> list[dict]:
        return [e["payload"] for e in self.events(sid) if e["kind"] == kind]


# ────────────────────────────────────────────────────────
# 저장소 / store
# ────────────────────────────────────────────────────────

class StoreTests(BrowserCase):
    async def test_kind_column_keeps_the_name_and_validates_it(self):
        s = agentic_store.get_session(self.sid)
        self.assertEqual((s["kind"], s["folder"], s["title"], s["extra_folders"]), ("browser", NAME, NAME, []))
        self.assertEqual(agentic_store.light(s)["kind"], "browser")
        local = agentic_store.create_session("", self.root)
        self.assertEqual((local["kind"], agentic_store.light(local)["kind"]), ("local", "local"))
        spaced = agentic_store.create_session("", " 경동 폴더 ", title="제목", kind="browser")
        self.assertEqual((spaced["folder"], spaced["title"]), (" 경동 폴더 ", "제목"))   # realpath 없음 · 그대로 / as given
        self.assertEqual(agentic_store.create_session("", "가" * 200, kind="browser")["folder"], "가" * 200)
        for bad in ("", "   ", "a/b", "a\\b", "C:", "x*", "q?", 'd"q', "a<b", "a>b", "a|b", "tab\tname", ".", "..",
                    "가" * 201, None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                agentic_store.create_session("", bad, kind="browser")
        with self.assertRaises(ValueError):
            agentic_store.create_session("", NAME, kind="cloud")

    async def test_an_old_table_gets_kind_local(self):
        from app import db
        with db._conn() as conn:
            conn.execute("DROP TABLE agentic_sessions")
            conn.execute("CREATE TABLE agentic_sessions(id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL, "
                         "folder TEXT NOT NULL, extra_folders TEXT NOT NULL DEFAULT '[]', model TEXT NOT NULL, "
                         "effort TEXT NOT NULL DEFAULT 'auto', perm_mode TEXT NOT NULL DEFAULT 'auto', "
                         "status TEXT NOT NULL DEFAULT 'idle', context_pct INTEGER NOT NULL DEFAULT 0, "
                         "rules TEXT NOT NULL DEFAULT '[]', steps INTEGER NOT NULL DEFAULT 0, last_seq INTEGER NOT NULL DEFAULT 0, "
                         "created TEXT NOT NULL, updated TEXT NOT NULL, connectors TEXT NOT NULL DEFAULT '[]', "
                         "notify INTEGER NOT NULL DEFAULT 0, seen_seq INTEGER NOT NULL DEFAULT 0, "
                         "prev_perm TEXT NOT NULL DEFAULT '', hooks_trust TEXT NOT NULL DEFAULT '', "
                         "compact_seq INTEGER NOT NULL DEFAULT 0)")
            conn.execute("INSERT INTO agentic_sessions(id, owner, title, folder, model, created, updated) "
                         "VALUES('ag_old', '', 'old', ?, 'gemini-3.8-flash', 'x', 'x')", (self.root,))
        agentic_store.init_agentic()
        self.assertEqual(agentic_store.get_session("ag_old")["kind"], "local")
        agentic_store.init_agentic()   # 두 번째도 문제없다 / idempotent
        self.assertEqual(agentic_store.create_session("", NAME, kind="browser")["kind"], "browser")


# ────────────────────────────────────────────────────────
# 도구 선언 · 권한 판정 / declarations and classification
# ────────────────────────────────────────────────────────

class ToolsTests(BrowserCase):
    def names(self, specs) -> list[str]:
        return [s["name"] for s in specs]

    async def test_specs_leave_out_bash_and_task_output(self):
        s = agentic_store.get_session(self.sid)
        st = agentic_store.get_settings()
        top = self.names(agentic_tools.specs_for(s, st))
        self.assertEqual(top, ["read_file", "list_dir", "glob", "grep", "write_file", "edit_file", "web_search", "fetch_page",
                               "task"])
        self.assertNotIn("bash", self.names(agentic_tools.specs_for(s, st, "reviewer")))
        self.assertNotIn("task_output", self.names(agentic_tools.specs_for(s, st, "worker")))
        self.assertEqual(self.names(agentic_tools.specs_for({**s, "perm_mode": "plan"}, st)),
                         ["read_file", "list_dir", "glob", "grep", "web_search", "fetch_page", "task"])
        self.assertIn("bash", agentic_tools.TOOL_NAMES)                              # 이름 목록은 그대로 / names unchanged
        # 전역 스킬만 센다(폴더 이름을 서버 경로로 보지 않는다) / global skills only
        self.assertFalse(agentic_tools.has_skills(s, st))
        self.assertTrue(agentic_tools.has_skills(s, {**st, "skills": [{"name": "style", "description": "d", "body": "b"}]}))
        self.assertIsInstance(agentic_tools.make_executor(s, st), ab.BrowserExecutor)
        self.assertEqual(agentic_tools.allowed_roots(s, st), [])

    async def test_classify_skips_outside_and_never_asks_for_bash(self):
        s = agentic_store.get_session(self.sid)
        st = agentic_store.get_settings()
        for tool, args in (("read_file", {"path": "../밖.txt"}), ("list_dir", {"path": "C:/Windows"}),
                           ("grep", {"pattern": "x", "path": "/etc"}), ("write_file", {"path": "새.txt", "content": "x"}),
                           ("bash", {"command": "danger_word now"}), ("bash", {"command": "rm -rf x"}),
                           ("task_output", {"task_id": "tk_1"})):
            self.assertIsNone(agentic_tools.classify(s, tool, args, st), tool)
        ask = {**s, "perm_mode": "ask"}
        self.assertEqual(agentic_tools.classify(ask, "write_file", {"path": "a.txt", "content": "x"}, st), "ask_mode")
        self.assertEqual(agentic_tools.classify(ask, "edit_file", {"path": "../a.txt"}, st), "ask_mode")
        self.assertIsNone(agentic_tools.classify(ask, "bash", {"command": "dir"}, st))
        ruled = {**ask, "rules": [agentic_tools.rule_for("write_file", {})]}
        self.assertIsNone(agentic_tools.classify(ruled, "write_file", {"path": "a.txt"}, st))
        plan = {**s, "perm_mode": "plan"}
        self.assertEqual(agentic_tools.classify(plan, "bash", {"command": "dir"}, st), "plan_mode")
        self.assertEqual(agentic_tools.classify(plan, "write_file", {"path": "a.txt"}, st), "plan_mode")
        local = agentic_store.create_session("", self.root)                          # 대조: 서버 폴더 / control: a server folder
        self.assertEqual(agentic_tools.classify(local, "read_file", {"path": "../밖.txt"}, st), "outside")


# ────────────────────────────────────────────────────────
# 요청 레지스트리 / the request registry
# ────────────────────────────────────────────────────────

class RegistryTests(BrowserCase):
    async def test_a_request_on_the_loop_thread_is_refused(self):
        with self.assertRaises(RuntimeError):
            ab.request(self.sid, "list", {"path": ""})
        self.assertEqual(ab.PENDING, {})

    async def test_pending_resolve_once_and_done_notices(self):
        q = runner.subscribe(self.sid)
        job = asyncio.ensure_future(self.call(ab.request, self.sid, "list", {"path": "sub"}))
        await self.until(lambda: len(ab.pending(self.sid)) == 1)
        row = ab.pending(self.sid)[0]
        self.assertEqual(set(row), {"request_id", "op", "args", "ts"})
        self.assertTrue(row["request_id"].startswith("br") and len(row["request_id"]) == 12)
        self.assertEqual((row["op"], row["args"]), ("list", {"path": "sub"}))
        ev = await asyncio.wait_for(q.get(), 5)   # 워커 스레드의 알림이 루프로 넘어왔다 / the worker's notice reached the loop
        self.assertEqual((ev["seq"], ev["transient"], ev["kind"]), (None, True, "tool_request"))
        self.assertEqual(ev["payload"], {"request_id": row["request_id"], "session_id": self.sid, "op": "list",
                                         "args": {"path": "sub"}, "ts": row["ts"]})
        self.assertEqual(ab.resolve("ag_other", row["request_id"], True, {}), "unknown")   # 다른 세션 / another session
        self.assertEqual(ab.resolve(self.sid, "br_nope", True, {}), "unknown")
        self.assertEqual(ab.resolve(self.sid, row["request_id"], True, {"entries": []}), "ok")
        self.assertEqual(await job, {"entries": []})
        self.assertEqual(ab.resolve(self.sid, row["request_id"], True, {}), "done")         # 늦은 답 / a late answer
        done = await asyncio.wait_for(q.get(), 5)
        self.assertEqual(done["payload"], {"request_id": row["request_id"], "done": True})
        self.assertEqual(ab.pending(self.sid), [])
        runner.unsubscribe(self.sid, q)

    async def test_a_timeout_frees_the_request_and_a_late_answer_is_done(self):
        b = self.browser(**{"a.txt": "a\n"})
        b.hold = True
        with patch.object(ab, "BROWSER_TIMEOUT_SEC", 0.3):
            with self.assertRaises(ab.BrowserTimeout) as cm:
                await self.call(self.ex().read, "a.txt")
        self.assertEqual(str(cm.exception), ab.BROWSER_TIMEOUT_MSG)
        self.assertEqual(ab.PENDING, {})
        rid = b.seen[0]["request_id"]
        await self.until(lambda: rid in b.done)                                       # 다른 탭도 안내를 지운다 / tabs clear it
        self.assertEqual(ab.resolve(self.sid, rid, True, {"text": "늦음"}), "done")

    async def test_stop_cancels_pending_requests_and_blocks_new_ones(self):
        b = self.browser(**{"a.txt": "a\n"})
        b.hold = True
        ex = self.ex()
        job = asyncio.ensure_future(self.call(ex.read, "a.txt"))
        await self.until(lambda: len(ab.pending(self.sid)) == 1)
        await asyncio.to_thread(ex.cancel_running)
        with self.assertRaises(agentic_exec.ExecError) as cm:
            await job
        self.assertEqual(str(cm.exception), ab.STOPPED_MSG)
        self.assertEqual(ab.pending(self.sid), [])
        with self.assertRaises(agentic_exec.ExecError):                               # 새 요청을 내지 않는다 / no new request
            await self.call(ex.read, "a.txt")
        self.assertEqual(len(b.seen), 1)
        # 모듈 cancel 은 그 세션만 / the module cancel only touches its session
        other = agentic_store.create_session("", "다른", kind="browser")["id"]
        job2 = asyncio.ensure_future(self.call(ab.request, other, "list", {"path": ""}))
        await self.until(lambda: len(ab.pending(other)) == 1)
        self.assertEqual(ab.cancel(self.sid), 0)
        self.assertEqual(ab.cancel(other, "세션이 삭제되었습니다"), 1)
        with self.assertRaises(agentic_exec.ExecError) as cm:
            await job2
        self.assertEqual(str(cm.exception), "세션이 삭제되었습니다")


# ────────────────────────────────────────────────────────
# 브라우저 실행기 / the browser executor
# ────────────────────────────────────────────────────────

class ExecutorTests(BrowserCase):
    async def test_read_slices_lines_keeps_the_path_and_marks_documents(self):
        b = self.browser(**{"docs/a.txt": "l1\nl2\r\nl3\nl4\nl5\n", "bin.dat": b"\x89PNG\x00\x01", "보고서.docx": b"PK\x03\x04\x00",
                            "빈.pdf": b"%PDF\x00", f"{NAME}/b.txt": "하위 폴더의 b\n", "ko.txt": "한글\n"})
        b.docs["보고서.docx"] = "첫 문단\n둘째 문단"
        ex = self.ex()
        r = await self.call(ex.read, "docs/a.txt", 2, 2)
        self.assertEqual((r["text"], r["lines"], r["start"], r["end"], r["more"], r["truncated"]),
                         ("     2\tl2\n     3\tl3", 5, 2, 3, True, False))
        self.assertEqual((r["path"], r["rel"], r["encoding"], r["extracted"], r["size"]),
                         (f"{NAME}/docs/a.txt", "docs/a.txt", "utf-8", False, 16))
        self.assertEqual(b.ops("read")[-1]["args"], {"path": "docs/a.txt", "max_bytes": agentic_exec.MAX_FILE_BYTES})
        await self.call(ex.read, ".\\docs\\a.txt")
        self.assertEqual(b.ops("read")[-1]["args"]["path"], "docs/a.txt")
        # 폴더 이름 접두는 벗기지 않는다: 같은 이름의 하위 폴더가 있으면 그 파일 / the prefix stays: a same-named subfolder wins
        self.assertEqual(ex.resolve(f"{NAME}/a.txt"), f"{NAME}/a.txt")
        sub = await self.call(ex.read, f"{NAME}/b.txt")
        self.assertEqual((sub["rel"], sub["text"]), (f"{NAME}/b.txt", "     1\t하위 폴더의 b"))
        with self.assertRaises(agentic_exec.ExecError) as cm:                         # 없으면 안내를 붙인다 / a hint when missing
            await self.call(ex.read, f"{NAME}/docs/a.txt")
        self.assertEqual(str(cm.exception), f"파일이 없습니다: {NAME}/docs/a.txt {ex.prefix_hint()}")
        self.assertIn(f"작업 폴더 '{NAME}' 기준 상대 경로입니다. 폴더 이름을 앞에 붙이지 마세요", ex.prefix_hint())
        with self.assertRaises(agentic_exec.ExecError) as cm:
            await self.call(ex.list_dir, f"{NAME}/없는")
        self.assertTrue(str(cm.exception).endswith(ex.prefix_hint()))
        with self.assertRaises(agentic_exec.ExecError) as cm:                         # 접두가 아니면 안내 없음 / no prefix, no hint
            await self.call(ex.read, "없는.txt")
        self.assertEqual(str(cm.exception), "파일이 없습니다: 없는.txt")
        self.assertEqual(ex.rel(f"{NAME}/{NAME}/b.txt"), f"{NAME}/b.txt")          # 산출물 경로의 이름 한 조각만 / one segment only
        with patch.object(agentic_exec, "READ_MAX_CHARS", 20):
            r = await self.call(ex.read, "docs/a.txt")
        self.assertEqual((r["truncated"], r["text"]), (True, "     1\tl1\n     2\tl2"))
        doc = await self.call(ex.read, "보고서.docx")
        self.assertEqual((doc["extracted"], doc["text"], doc["lines"], doc["truncated"]),
                         (True, "     1\t첫 문단\n     2\t둘째 문단", 2, False))
        b.doc_cut.add("보고서.docx")                                                   # 문서 본문 상한에서 잘림 / cut at the cap
        self.assertTrue((await self.call(ex.read, "보고서.docx"))["truncated"])
        # 인코딩은 브라우저가 준 값(아는 값만) / the browser's encoding, known values only
        for given, want in (("cp949", "cp949"), ("utf-8-sig", "utf-8-sig"), ("utf-16", "utf-16"), ("latin-9", "utf-8")):
            b.encodings["ko.txt"] = given
            self.assertEqual((await self.call(ex.read, "ko.txt"))["encoding"], want, given)
        # 글 답에 text 가 없으면(또는 문자열이 아니면) 빈 파일이 아니라 틀린 답 / a text answer without text is malformed
        for bad in ({"size": 3, "binary": False}, {"size": 3, "binary": False, "text": 42}):
            with patch.object(b, "op_read", lambda rel, a, bad=bad: dict(bad)):
                with self.assertRaises(agentic_exec.ExecError) as cm:
                    await self.call(ex.read, "ko.txt")
            self.assertEqual(str(cm.exception), ab.BAD_REPLY_MSG)
        with self.assertRaises(agentic_exec.ExecError) as cm:
            await self.call(ex.read, "bin.dat")
        self.assertEqual(str(cm.exception), "이진 파일은 읽을 수 없습니다")
        with self.assertRaises(agentic_exec.ExecError) as cm:
            await self.call(ex.read, "빈.pdf")
        self.assertEqual(str(cm.exception), ab.NO_TEXT_MSG)
        n = len(b.seen)
        for bad in ("../밖.txt", "/etc/passwd", "C:\\Windows\\win.ini", "docs/../../x"):
            with self.assertRaises(agentic_exec.OutsideError):
                await self.call(ex.read, bad)
        self.assertEqual(len(b.seen), n)                                              # 브라우저에 가지 않았다 / never sent

    async def test_write_creates_overwrites_with_a_diff_and_refuses_git(self):
        b = self.browser()
        ex = self.ex()
        r = await self.call(ex.write, "out/new.md", "hello\n")
        self.assertEqual((r["path"], r["rel"], r["created"], r["bytes"], r["diff"]), (f"{NAME}/out/new.md", "out/new.md", True, 6, None))
        self.assertEqual(b.files["out/new.md"], b"hello\n")
        r = await self.call(ex.write, "out/new.md", "hello\nworld\n")
        self.assertEqual((r["created"], r["added"], r["removed"]), (False, 1, 0))
        self.assertIn("--- a/out/new.md\n+++ b/out/new.md\n", r["diff"])
        self.assertIn("+world\n", r["diff"])
        n = len(b.seen)
        for bad in (".git/config", "sub/.GIT/hooks/pre-commit", ".git. /x"):
            with self.assertRaises(agentic_exec.RefusedError):
                await self.call(ex.write, bad, "x")
        for bad in ("", "  ", "."):
            with self.assertRaises(agentic_exec.ExecError):
                await self.call(ex.write, bad, "x")
        with patch.object(agentic_exec, "MAX_FILE_BYTES", 5):
            with self.assertRaises(agentic_exec.ExecError) as cm:
                await self.call(ex.write, "big.txt", "123456")
        self.assertIn("10MB", str(cm.exception))
        self.assertEqual(len(b.seen), n)
        # 도구 함수(run_tool)는 그대로: 산출물 path 는 '<이름>/<rel>' / run_tool as is, the output path is '<name>/<rel>'
        s = agentic_store.get_session(self.sid)
        ok, summary, detail, extra = await self.call(agentic_tools.run_tool, s, "write_file",
                                                     {"path": "out/new.md", "content": "hello\n"}, ex, agentic_store.get_settings())
        self.assertTrue(ok)
        self.assertEqual(extra["written"], {"path": f"{NAME}/out/new.md", "kind": "modified", "bytes": 6})
        self.assertEqual(extra["diff"]["path"], "out/new.md")

    async def test_edit_follows_crlf_zero_many_rules_and_refuses_documents(self):
        b = self.browser(**{"f.txt": "x = 1\ny = 2\nx = 1\n", "win.txt": b"one\r\ntwo\r\nthree\r\n", "보고서.docx": b"PK\x00",
                            "bin.dat": b"\x00\x01", "ko.txt": "첫 줄\n".encode("cp949")})
        ex = self.ex()
        with self.assertRaises(agentic_exec.ExecError) as cm:
            await self.call(ex.edit, "f.txt", "z = 9", "z = 0")
        self.assertIn("찾지 못했습니다", str(cm.exception))
        with self.assertRaises(agentic_exec.ExecError) as cm:
            await self.call(ex.edit, "f.txt", "x = 1", "x = 3")
        self.assertIn("2곳", str(cm.exception))
        r = await self.call(ex.edit, "f.txt", "y = 2", "y = 20")
        self.assertEqual((r["path"], r["rel"], r["replaced"], r["added"], r["removed"], r["bytes"]),
                         (f"{NAME}/f.txt", "f.txt", 1, 1, 1, 19))
        self.assertIn("-y = 2\n+y = 20\n", r["diff"])
        r = await self.call(ex.edit, "f.txt", "x = 1", "x = 3", True)
        self.assertEqual(r["replaced"], 2)
        self.assertEqual(b.files["f.txt"], b"x = 3\ny = 20\nx = 3\n")
        await self.call(ex.edit, "win.txt", "one\ntwo", "uno\ndos")                   # 모델은 LF 로 준다 / the model sends LF
        self.assertEqual(b.files["win.txt"], b"uno\r\ndos\r\nthree\r\n")
        for path, msg in (("보고서.docx", ab.NO_EDIT_MSG), ("bin.dat", ab.NO_EDIT_MSG), ("ko.txt", ab.LOSSY_MSG)):
            with self.assertRaises(agentic_exec.ExecError) as cm:
                await self.call(ex.edit, path, "a", "b")
            self.assertEqual(str(cm.exception), msg)
        with self.assertRaises(agentic_exec.RefusedError):
            await self.call(ex.edit, ".git/config", "a", "b")
        writes = len(b.ops("write"))
        with self.assertRaises(agentic_exec.ExecError):
            await self.call(ex.edit, "f.txt", "", "b")                                # 빈 old_string / empty old_string
        self.assertEqual(len(b.ops("write")), writes)
        # run_tool 의 산출물 크기는 실행기가 준 bytes / run_tool's output size is the executor's bytes
        s = agentic_store.get_session(self.sid)
        ok, _s, _d, extra = await self.call(agentic_tools.run_tool, s, "edit_file",
                                            {"path": "f.txt", "old_string": "y = 20", "new_string": "y = 2"}, ex,
                                            agentic_store.get_settings())
        self.assertTrue(ok)
        self.assertEqual(extra["written"], {"path": f"{NAME}/f.txt", "kind": "modified", "bytes": 18})

    async def test_list_dir_sorts_on_the_server_and_caps(self):
        b = self.browser(**{"b.txt": "bb", "A.txt": "a", "sub/x.txt": "x", "Zdir/y.txt": "y"})
        b.dirs.add("empty")
        ex = self.ex()
        r = await self.call(ex.list_dir, None)
        self.assertEqual([(e["name"], e["type"]) for e in r["entries"]],
                         [("empty", "dir"), ("sub", "dir"), ("Zdir", "dir"), ("A.txt", "file"), ("b.txt", "file")])
        self.assertEqual((r["path"], r["rel"], r["total"], r["truncated"]), (NAME, ".", 5, False))
        self.assertEqual(r["entries"][4]["size"], 2)
        self.assertRegex(r["entries"][4]["mtime"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")   # ISO 로 바꿨다 / made ISO
        with patch.object(agentic_exec, "MAX_LIST", 2):
            r = await self.call(ex.list_dir, "")
        self.assertEqual((len(r["entries"]), r["total"], r["truncated"]), (2, 5, True))
        r = await self.call(ex.list_dir, "sub")
        self.assertEqual((r["rel"], [e["name"] for e in r["entries"]]), ("sub", ["x.txt"]))
        with self.assertRaises(agentic_exec.ExecError) as cm:
            await self.call(ex.list_dir, "없는")
        self.assertEqual(str(cm.exception), "폴더가 없습니다: 없는")
        with self.assertRaises(agentic_exec.ExecError) as cm:
            await self.call(ex.list_dir, "b.txt")
        self.assertEqual(str(cm.exception), "폴더가 아닙니다: b.txt")
        s = agentic_store.get_session(self.sid)
        ok, summary, detail, _x = await self.call(agentic_tools.run_tool, s, "list_dir", {}, ex, agentic_store.get_settings())
        self.assertTrue(ok)
        self.assertTrue(detail.startswith(". (5개)\n[폴더] empty"), detail)
        for k in range(600):   # 브라우저가 500개에서 자르고 total 로 전체 수를 준다 / the browser cuts at 500 and reports total
            b.put(f"many/f{k:03d}.txt", "x")
        r = await self.call(ex.list_dir, "many")
        self.assertEqual((len(r["entries"]), r["total"], r["truncated"]), (500, 600, True))
        # 가짜는 거꾸로 500개(f599~f100)를 준다 → 서버가 그 500개를 정렬 / the fake sends f599..f100; the server sorts those
        self.assertEqual((r["entries"][0]["name"], r["entries"][-1]["name"]), ("f100.txt", "f599.txt"))

    async def test_glob_matches_on_the_server_by_mtime_and_skips_heavy_folders(self):
        now = time.time() * 1000
        b = FakeBrowser(self.sid)
        for rel, age in (("a.py", 30), ("b.py", 10), ("sub/c.py", 20), ("notes.txt", 40), ("node_modules/pkg/x.py", 5)):
            b.put(rel, "def x():\n", now - age * 1000)
        self.browsers.append(b.start())
        ex = self.ex()
        r = await self.call(ex.glob, "**/*.py")
        self.assertEqual(r["paths"], ["b.py", "sub/c.py", "a.py"])
        self.assertEqual((r["count"], r["truncated"], r["scan_capped"], r["rel_base"], r["base"]), (3, False, False, ".", NAME))
        walk = b.ops("walk")[-1]["args"]
        self.assertEqual((walk["path"], walk["max"]), ("", agentic_exec.SCAN_MAX))
        self.assertIn("node_modules", walk["skip"])
        self.assertEqual(sorted(walk["skip"]), walk["skip"])
        self.assertEqual((await self.call(ex.glob, "*.PY"))["paths"], ["b.py", "a.py"])   # 대소문자 무시 / case-insensitive
        r = await self.call(ex.glob, "*.py", "sub")
        self.assertEqual((r["paths"], r["rel_base"]), (["sub/c.py"], "sub"))          # 세션 폴더 기준 / session-relative
        self.assertEqual((await self.call(ex.glob, "node_modules/**/*.py"))["paths"], ["node_modules/pkg/x.py"])
        self.assertEqual((await self.call(ex.glob, "*.{py,txt}"))["paths"], ["b.py", "a.py", "notes.txt"])
        with patch.object(agentic_exec, "MAX_GLOB", 2):
            r = await self.call(ex.glob, "**/*.py")
        self.assertEqual((r["paths"], r["count"], r["truncated"]), (["b.py", "sub/c.py"], 3, True))
        n = len(b.seen)
        for bad in ("../*.py", "/etc/*", "C:/x/*", ""):
            with self.assertRaises(agentic_exec.ExecError):
                await self.call(ex.glob, bad)
        self.assertEqual(len(b.seen), n)
        with self.assertRaises(agentic_exec.ExecError) as cm:
            await self.call(ex.glob, "*.py", "a.py")
        self.assertEqual(str(cm.exception), "폴더가 아닙니다: a.py")

    async def test_grep_passes_its_arguments_and_translates_inline_flags(self):
        b = self.browser(**{"a.py": "def alpha():\n    return 1\n", "sub/c.py": "DEF gamma():\n", "notes.txt": "def in notes\n"})
        ex = self.ex()
        r = await self.call(ex.grep, "(?i)def", None, "*.py")
        args = b.ops("grep")[-1]["args"]
        self.assertEqual({k: args[k] for k in ("path", "pattern", "flags", "glob", "by_path", "max_results")},
                         {"path": "", "pattern": "def", "flags": "i", "glob": "*.py", "by_path": False,
                          "max_results": agentic_exec.GREP_DEFAULT})
        self.assertEqual(args["glob_re"], agentic_exec.glob_regex("*.py").pattern)
        self.assertIn(".git", args["skip"])
        self.assertEqual(sorted(r["matches"]), ["a.py:1:def alpha():", "sub/c.py:1:DEF gamma():"])
        self.assertEqual((r["count"], r["files"], r["truncated"], r["base"], r["rel_base"]), (2, 2, False, NAME, "."))
        r = await self.call(ex.grep, "def", "sub", "*.py", 5000)
        args = b.ops("grep")[-1]["args"]
        self.assertEqual((args["path"], args["flags"], args["by_path"], args["max_results"]),
                         ("sub", "", False, agentic_exec.GREP_MAX))
        self.assertEqual(r["matches"], [])                                             # 대소문자 구분 / case-sensitive
        r = await self.call(ex.grep, "gamma", None, "sub/*.py")
        self.assertTrue(b.ops("grep")[-1]["args"]["by_path"])                         # '/' 가 든 글롭 = 경로 / a path glob
        self.assertEqual(r["matches"], ["sub/c.py:1:DEF gamma():"])
        r = await self.call(ex.grep, "def", None, None, 1)
        self.assertEqual((r["count"], r["truncated"]), (1, True))
        n = len(b.seen)
        with self.assertRaises(agentic_exec.ExecError) as cm:
            await self.call(ex.grep, "(")
        self.assertTrue(str(cm.exception).startswith("정규식 오류: "))
        with self.assertRaises(agentic_exec.ExecError):
            await self.call(ex.grep, "")
        self.assertEqual(len(b.seen), n)
        # JS 식 이름 있는 그룹도 받는다(파이썬 식으로 바꿔 검사한 뒤 다시 JS 식으로) / JS-style names pass (checked as Python)
        with patch.object(b, "op_grep", lambda rel, a: {"matches": [], "count": 0, "files": 0, "truncated": False}):
            await self.call(ex.grep, "(?<이름>경동)\\k<이름>\\w+")
        self.assertEqual(b.ops("grep")[-1]["args"]["pattern"], f"(?<이름>경동)\\k<이름>[{ab.WORD_SET}]+")
        # 브라우저에서 못 쓰는 구문은 요청 전에 거절 / syntax the browser lacks is refused before any request
        n = len(b.seen)
        for bad, what in (("a++", "++"), ("(?x)a b", "(?x)"), ("(?>ab)", "(?>"), ("[\\W]", "[\\W]"), ("(?#c)a", "(?#")):
            with self.assertRaises(agentic_exec.ExecError) as cm:
                await self.call(ex.grep, bad)
            self.assertEqual(str(cm.exception), ab.UNSUPPORTED_MSG + what, bad)
        self.assertEqual(len(b.seen), n)

    async def test_error_codes_read_as_the_contract_says(self):
        b = self.browser(**{"a.txt": "a\n"})
        ex = self.ex()
        want = {"outside": "폴더 밖 경로는 쓸 수 없습니다: a.txt", "notfound": "파일이 없습니다: a.txt",
                "isdir": "폴더입니다: a.txt", "notdir": "폴더가 아닙니다: a.txt", "binary": "이진 파일은 읽을 수 없습니다",
                "toolarge": "파일이 너무 큽니다(10MB 초과)",
                "denied": "브라우저가 폴더 접근을 거부했습니다. 화면의 [허용] 을 누르세요",
                "exec": "정규식 오류: 짝이 맞지 않음", "": "정규식 오류: 짝이 맞지 않음"}
        for code, msg in want.items():
            b.force = (code, "정규식 오류: 짝이 맞지 않음")
            with self.assertRaises(agentic_exec.ExecError) as cm:
                await self.call(ex.read, "a.txt")
            self.assertEqual(str(cm.exception), msg, code)
        b.force = ("notfound", "")
        with self.assertRaises(agentic_exec.ExecError) as cm:
            await self.call(ex.list_dir, "sub")
        self.assertEqual(str(cm.exception), "폴더가 없습니다: sub")
        b.force = ("exec", "")
        with self.assertRaises(agentic_exec.ExecError) as cm:
            await self.call(ex.read, "a.txt")
        self.assertEqual(str(cm.exception), ab.EXEC_FALLBACK_MSG)
        b.force = None
        # 이상한 답(본문 모양이 틀림) / malformed answers
        with patch.object(b, "op_list", lambda rel, a: {"entries": "아님"}):
            with self.assertRaises(agentic_exec.ExecError) as cm:
                await self.call(ex.list_dir, "")
        self.assertEqual(str(cm.exception), ab.BAD_REPLY_MSG)
        # 명령은 실행기가 거절한다(정책 거절) / commands are refused by the executor (a policy refusal)
        for fn, args in ((ex.run, ("dir",)), (ex.task_output, ("tk_1",))):
            with self.assertRaises(agentic_exec.RefusedError) as cm:
                fn(*args)
            self.assertEqual(str(cm.exception), ab.NO_BASH_MSG)

    async def test_rules_file_falls_back_and_gives_up_on_a_timeout(self):
        b = self.browser(**{"AI365.md": "\ufeff  규칙-AI365  \n"})
        self.assertEqual(await self.call(self.ex().read_rules), ("AI365.md", "규칙-AI365"))
        self.assertEqual([p["args"]["path"] for p in b.ops("read")], ["AGENTS.md", "AI365.md"])
        b.put("AGENTS.md", "가" * (ab.RULES_CHARS + 5))
        name, text = await self.call(self.ex().read_rules)
        self.assertEqual((name, len(text)), ("AGENTS.md", ab.RULES_CHARS + len("\n…(규칙 파일이 길어 잘림)")))
        b.hold = True
        n = len(b.seen)
        with patch.object(ab, "RULES_TIMEOUT_SEC", 0.2):
            t0 = time.monotonic()
            self.assertEqual(await self.call(self.ex().read_rules), ("", ""))
        self.assertLess(time.monotonic() - t0, 5)
        self.assertEqual(len(b.seen), n + 1)                                          # 시간 초과면 바로 그만 / stops at once


# ────────────────────────────────────────────────────────
# grep 정규식 번역 · mtime(순수 함수 + node) / grep regex translation and mtime (pure functions, node)
# ────────────────────────────────────────────────────────

W = ab.WORD_SET
# (파이썬 패턴, JS 패턴, JS 플래그) / (Python pattern, JS pattern, JS flags)
TRANSLATED = [
    (r"(?i)(?s)x", "x", "is"), (r"(?s)(?i)x", "x", "is"), (r"(?im)a", "a", "im"), (r"(?u)a", "a", ""), (r"(?iu)a", "a", "i"),
    (r"\Ahead\Z", "^head$", ""), (r"\\A", r"\\A", ""),
    (r"(?P<n>a)(?P=n)", r"(?<n>a)\k<n>", ""), (r"(?P<이름>가)(?P=이름)", r"(?<이름>가)\k<이름>", ""),
    (r"a{,3}", "a{0,3}", ""), (r"a{,}", "a{0,}", ""), (r"a{2,}", "a{2,}", ""), (r"a{}", "a{}", ""), (r"{x}+", "{x}+", ""),
    (r"a{1, 2}", "a{1, 2}", ""), (r"a+?", "a+?", ""), (r"a{2}?", "a{2}?", ""),
    (r"\w+", f"[{W}]+", ""), (r"\W", f"[^{W}]", ""), (r"[\w-]", f"[{W}-]", ""), (r"[^\w]", f"[^{W}]", ""),
    (r"\\w", r"\\w", ""), (r"경동\w+", f"경동[{W}]+", ""),
    (r"[]a]", r"[\]a]", ""), (r"[^]a]", r"[^\]a]", ""), (r"[(?P<]", r"[(?P<]", ""),
    (r"\bword\b", r"\bword\b", ""), (r"(?i:ab)c", "(?i:ab)c", ""), (r"(?-i:ab)", "(?-i:ab)", ""), (r"(?u:ab)", "(?:ab)", ""),
    (r"(?:ab)", "(?:ab)", ""), (r"(?<=a)b", "(?<=a)b", ""), (r"(?<!a)b", "(?<!a)b", ""), (r"(?=a)", "(?=a)", ""),
    (r"\a", r"\x07", ""), (r"x\(?y", r"x\(?y", ""),
]
# (파이썬 패턴, 거절 문구의 구문) / (Python pattern, the construct named in the refusal)
REFUSED = [
    (r"(?x) a", "(?x)"), (r"(?a)\w", "(?a)"), (r"(?L)a", "(?L)"), (r"(?i)(?x)a", "(?x)"), (r"a++", "++"), (r"a*+", "*+"),
    (r"a?+", "?+"), (r"a{2}+", "{2}+"), (r"a{,2}+", "{,2}+"), (r"(?>ab)", "(?>"), (r"(?#c)a", "(?#"),
    (r"(a)(?(1)b|c)", "(?("), (r"[\W]", r"[\W]"), (r"\U0001F600", r"\U"), (r"\N{HANGUL SYLLABLE GA}", r"\N"),
    (r"(?x:a)", "(?x:"), (r"(?a:a)", "(?a:"),
]
# 파이썬 re 와 JS 가 같은 부분을 찾는지 볼 표본 / samples where Python re and JS must find the same substring
SAMPLES = [
    (r"(?i)ABC", ["xabcx", "ABC", "xyz"]), (r"\Ahead\Z", ["head", "a head", "head\n"]), (r"a{,3}", ["aaaa", "b"]),
    (r"[]a]+", ["x]a]"]), (r"경동\w+", ["경동보고서 2026", "경동_v2", "경동!"]), (r"\W+", ["가나 다"]), (r"[^\w]+", ["가,나"]),
    (r"(?P<n>가)(?P=n)", ["가가나", "가나"]), (r"(?<이름>다)\k<이름>", ["다다"]), (r"\a", ["\x07"]), (r"(?i:ab)c", ["ABc", "ABC"]),
    (r"a+?", ["aaa"]), (r"\w+@\w+", ["메일: 홍길동@회사 끝"]),
]
GLOBS = [("*.py", "a.PY"), ("my-file #1.txt", "my-file #1.txt"), ("src/**/*.{ts,tsx}", "src/a/b.tsx"), ("[!a]*.md", "b.md"),
         ("보고서 ~최종.docx", "보고서 ~최종.docx")]


class PatternTests(unittest.TestCase):
    def test_python_patterns_translate_for_js(self):
        for src, js, flags in TRANSLATED:
            re.compile(src)                                                           # 서버 검사를 지나는 패턴만 / valid Python only
            self.assertEqual(ab.js_pattern(src), (js, flags), src)

    def test_syntax_js_lacks_is_refused(self):
        for src, what in REFUSED:
            with self.assertRaises(agentic_exec.ExecError, msg=src) as cm:
                ab.js_pattern(src)
            self.assertEqual(str(cm.exception), ab.UNSUPPORTED_MSG + what, src)
        self.assertTrue(ab.UNSUPPORTED_MSG.startswith("정규식 오류: 브라우저에서 쓸 수 없는 구문입니다: "))

    def test_js_style_names_become_python_for_the_check(self):
        for src, want in ((r"(?<n>a)\k<n>", r"(?P<n>a)(?P=n)"), (r"(?<이름>가)", r"(?P<이름>가)"), (r"(?<=a)(?<!b)", r"(?<=a)(?<!b)"),
                          (r"[(?<n>)]", r"[(?<n>)]"), (r"\\k<n>", r"\\k<n>"), (r"(?P<n>a)", r"(?P<n>a)")):
            self.assertEqual(ab.py_pattern(src), want, src)
            re.compile(ab.py_pattern(src))

    def test_mtime_reads_naive_iso_as_kst(self):
        from datetime import datetime, timezone
        utc = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc).timestamp()
        for value in ("2026-10-20T09:00:00", "2026-10-20T00:00:00Z", "2026-10-20T09:00:00+09:00", utc * 1000, utc):
            self.assertEqual(ab._mtime_num(value), utc, value)                        # 서버 시간대와 무관 / host zone independent
        self.assertEqual(ab._mtime_iso("2026-10-20T09:00:00"), "2026-10-20T09:00:00")
        self.assertEqual((ab._mtime_num("아님"), ab._mtime_num(None), ab._mtime_num(True)), (0.0, 0.0, 0.0))

    def test_node_compiles_the_translations_and_matches_like_python(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node 가 없습니다 / node is not installed")
        rows = [{"js": js, "flags": flags} for _src, js, flags in TRANSLATED]
        rows += [{"js": agentic_exec.glob_regex(g).pattern, "flags": "i", "sample": s, "want": s} for g, s in GLOBS]
        for src, samples in SAMPLES:
            js, flags = ab.js_pattern(ab.py_pattern(src))
            rx = re.compile(ab.py_pattern(src))
            for s in samples:
                m = rx.search(s)
                rows.append({"js": js, "flags": flags, "sample": s, "want": m.group(0) if m else None, "src": src})
        script = ("const rows = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
                  "const out = rows.map(r => { try { const rx = new RegExp(r.js, r.flags);"
                  " if (!('sample' in r)) return {ok: true};"
                  " const m = r.sample.match(rx); return {ok: true, got: m ? m[0] : null}; }"
                  " catch (e) { return {ok: false, err: String(e.message)}; } });"
                  "process.stdout.write(JSON.stringify(out));")
        r = subprocess.run([node, "-e", script], input=json.dumps(rows, ensure_ascii=False), capture_output=True,
                           text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        for row, got in zip(rows, out):
            self.assertTrue(got["ok"], (row, got))                                    # u 없는 JS 에서 컴파일 / compiles without u
            if "sample" in row:
                self.assertEqual(got.get("got"), row["want"], row)                     # 파이썬과 같은 일치 / same match as Python
        korean = [g for row, g in zip(rows, out) if row.get("src") == r"경동\w+" and row["sample"] == "경동보고서 2026"]
        self.assertEqual(korean[0]["got"], "경동보고서")                                # 번역한 \w 가 한글을 잡는다 / \w catches Korean


# ────────────────────────────────────────────────────────
# 러너 / the runner
# ────────────────────────────────────────────────────────

class RunnerTests(BrowserCase):
    def model(self, *script) -> FakeModel:
        fake = FakeModel(*script)
        self.stack.enter_context(patch("app.llm.generate_calls", side_effect=fake))
        return fake

    def no_server_side(self) -> list:
        """훅 · git 을 막는 대역들(러너는 그 오류를 삼키므로 끝에 불리지 않았는지 따로 본다) / stand-ins that block hooks and
        git; the runner swallows their errors, so the tests also check they were never called"""
        mocks = []
        for target in ("app.agentic_hooks.run_event", "app.agentic_hooks.load_folder_hooks", "app.agentic_hooks.active_hooks",
                       "app.agentic_git.is_repo", "app.agentic_git.snapshot", "app.agentic_git.commit"):
            mocks.append(self.stack.enter_context(patch(target, side_effect=AssertionError(f"unexpected {target}"))))
        return mocks

    def never_called(self, mocks: list) -> None:
        for m in mocks:
            m.assert_not_called()

    async def finish(self, sid: str | None = None):
        self.assertTrue(await runner.join(sid or self.sid, 30), "턴이 끝나지 않았습니다 / the turn did not end")

    async def test_a_turn_reads_rules_through_the_browser_without_bash_hooks_or_checkpoints(self):
        agentic_store.put_settings({"hooks": [{"event": "pre_tool", "matcher": ".*", "command": "echo hi", "timeout_sec": 5},
                                              {"event": "user_prompt", "command": "echo hi"}]})
        blocked = self.no_server_side()
        b = self.browser(**{"AGENTS.md": "RULES-MARKER-77: 브라우저 규칙\n", "README.md": "# 데모\nteh\n"})
        fake = self.model({"calls": [("read_file", {"path": "README.md"}), ("bash", {"command": "dir"})]},
                          {"calls": [("write_file", {"path": "out/new.txt", "content": "hi\n"}),
                                     ("edit_file", {"path": "README.md", "old_string": "teh", "new_string": "the"})]},
                          {"text": "고쳤습니다."})
        self.assertEqual(runner.start_turn(self.sid, "README 고쳐줘"), {"queued": False})
        await self.finish()
        kinds = [e["kind"] for e in self.events()]
        self.assertEqual(kinds, ["user", "status", "tool_call", "tool_result", "tool_call", "tool_result", "tool_call",
                                 "tool_result", "tool_call", "tool_result", "assistant", "summary", "context", "status"])
        results = {p["tool"]: p for p in self.of("tool_result")}
        self.assertTrue(results["read_file"]["ok"])
        self.assertEqual((results["bash"]["ok"], results["bash"]["detail"]), (False, ab.NO_BASH_MSG))
        self.assertTrue(results["write_file"]["ok"] and results["edit_file"]["ok"])
        self.assertEqual(b.files["README.md"], "# 데모\nthe\n".encode("utf-8"))
        self.assertEqual(self.of("status")[-1]["state"], "idle")
        self.assertEqual(b.ops("read")[0]["args"]["path"], "AGENTS.md")                 # 규칙 파일이 먼저 / the rules file first
        system = fake.seen[0]["system"]
        self.assertIn(f"[작업 폴더] 사용자의 컴퓨터에 있는 폴더 '{NAME}'(브라우저로 연결). 경로는 이 폴더 기준 상대 경로만 쓴다. "
                      "명령 실행(bash)은 할 수 없다.", system)
        self.assertIn("RULES-MARKER-77", system)
        self.assertNotIn("[허용 폴더]", system)
        self.assertNotIn("bash 는 빌드", system)
        self.assertNotIn("bash", [t["name"] for t in fake.seen[0]["tools"]])
        # grep 은 JS 정규식이라는 안내 · 명령 실행이 없는 권한 문구 / the JS-regex note and the command-free permission text
        self.assertIn("grep 의 pattern 은 브라우저의 JS 정규식으로 실행된다(한글은 글자 그대로 적고, \\b 는 ASCII 낱말 경계, "
                      "이름 있는 그룹은 (?<이름>))", system)
        self.assertIn(f"[권한 모드] {runner.PERM_TEXT_BROWSER['auto']}", system)
        self.assertNotIn("안전한 명령", system)
        self.assertIn(runner.SUBAGENT_GUIDE_BROWSER, system)
        self.assertNotIn("명령 실행, reviewer", system)
        task = [t for t in fake.seen[0]["tools"] if t["name"] == "task"][0]
        self.assertEqual(task["description"], agentic_tools.TASK_SPEC_BROWSER["description"])
        self.assertNotIn("명령 실행까지", task["description"])
        outs = {o["path"]: o["kind"] for o in agentic_store.list_outputs(self.sid)}
        self.assertEqual(outs, {f"{NAME}/out/new.txt": "created", f"{NAME}/README.md": "modified"})
        self.assertEqual(ab.PENDING, {})
        # 다음 턴도 규칙 파일을 다시 읽는다(압축 판정은 마지막 규칙을 쓴다) / the next turn reads the rules again
        self.model({"text": "또 안녕"})
        runner.start_turn(self.sid, "또")
        await self.finish()
        self.assertEqual([p["args"]["path"] for p in b.ops("read")].count("AGENTS.md"), 2)
        self.assertEqual(runner._BROWSER_RULES[self.sid][0], "AGENTS.md")
        self.never_called(blocked)                                                    # 훅 · git 이 한 번도 돌지 않았다 / never ran
        self.assertNotIn("hook", [e["kind"] for e in self.events()])
        self.assertNotIn("checkpoint", [e["kind"] for e in self.events()])

    async def test_a_subagent_reads_through_the_browser_too(self):
        b = self.browser(**{"AGENTS.md": "규칙\n", "a.txt": "한 줄\n"})
        fake = self.model({"calls": [("task", {"description": "a.txt 조사", "prompt": "a.txt 를 읽고 내용을 알려라",
                                               "preset": "worker"})]},
                          {"calls": [("read_file", {"path": "a.txt"})]},
                          {"text": "자식: a.txt 는 '한 줄'"},
                          {"text": "부모: 끝났습니다"})
        runner.start_turn(self.sid, "a.txt 조사해줘")
        await self.finish()
        child_read = [p for p in self.of("tool_result") if p["tool"] == "read_file"]
        self.assertEqual(len(child_read), 1)
        self.assertTrue(child_read[0]["ok"])
        self.assertTrue(child_read[0]["task_id"].startswith("tk_"))                    # 서브에이전트의 호출 / the subagent's call
        task = [p for p in self.of("tool_result") if p["tool"] == "task"][0]
        self.assertTrue(task["ok"])
        self.assertIn("자식: a.txt 는 '한 줄'", task["detail"])
        self.assertEqual(self.of("assistant")[-1]["text"], "부모: 끝났습니다")
        self.assertIn({"path": "a.txt", "max_bytes": agentic_exec.MAX_FILE_BYTES}, [p["args"] for p in b.ops("read")])
        child_system = fake.seen[1]["system"]
        self.assertIn(f"[서브에이전트] 프리셋 worker: {runner.PRESET_ROLE_BROWSER['worker']}", child_system)
        self.assertNotIn("명령 · 테스트를 돌려", child_system)
        self.assertIn(f"사용자의 컴퓨터에 있는 폴더 '{NAME}'", child_system)
        self.assertIn("[규칙 파일 AGENTS.md]", child_system)                           # 부모가 읽은 규칙을 넘긴다 / the parent's rules
        self.assertNotIn("bash", [t["name"] for t in fake.seen[1]["tools"]])
        self.assertEqual(ab.PENDING, {})

    async def test_stop_cancels_the_waiting_browser_request(self):
        b = self.browser(**{"AGENTS.md": "규칙\n", "a.txt": "a\n"})
        self.model({"calls": [("read_file", {"path": "a.txt"})]}, {"text": "끝"})
        runner.start_turn(self.sid, "읽어줘")
        await self.until(lambda: any(p["op"] == "read" and p["args"]["path"] == "AGENTS.md" for p in b.seen))
        b.hold = True   # 규칙 파일 뒤의 read_file 을 붙잡는다 / hold the read_file after the rules file
        await self.until(lambda: any(p["args"].get("path") == "a.txt" for p in b.seen))
        self.assertEqual(len(ab.pending(self.sid)), 1)
        self.assertTrue(await runner.stop(self.sid))
        self.assertEqual(ab.pending(self.sid), [])
        await self.finish()
        self.assertEqual(self.of("status")[-1]["state"], "stopped")
        stopped = [p for p in self.of("tool_result") if p["tool"] == "read_file"]
        self.assertEqual((stopped[-1]["ok"], stopped[-1]["detail"]), (False, runner.STOPPED))

    async def test_slash_commands_have_no_git_or_hooks_and_clear_keeps_the_browser_folder(self):
        blocked = self.no_server_side()
        agentic_store.update_session(self.sid, perm_mode="ask", connectors=[])
        for text in ("/commit", "/commit 메시지 / message", "/checkpoint 이름", "/undo"):
            name = text.split()[0][1:]
            out = await runner.run_command(self.sid, name, text[len(name) + 2:], text)
            self.assertEqual((out["command"], out["queued"]), (name, False), text)
            last = self.of("assistant")[-1]
            self.assertEqual(last, {"text": f"/{name}: {runner.BROWSER_ONLY_SERVER}.", "command": True}, text)
        self.assertNotIn("status", [e["kind"] for e in self.events()])                # 턴이 열리지 않았다 / no turn opened
        await runner.run_command(self.sid, "hooks", "", "/hooks")
        self.assertEqual(self.of("assistant")[-1]["text"], runner.BROWSER_NO_HOOKS)
        await runner.run_command(self.sid, "help", "", "/help")
        self.assertIn(runner.BROWSER_HELP_NOTE, self.of("assistant")[-1]["text"])
        out = await runner.run_command(self.sid, "clear", "", "/clear")
        new = out["session"]
        self.assertNotEqual(new["id"], self.sid)
        self.assertEqual((new["kind"], new["folder"], new["title"], new["perm_mode"], new["extra_folders"]),
                         ("browser", NAME, NAME, "ask", []))
        # 사용자 명령은 전역만(폴더 인자 None) / user commands are global only
        agentic_store.put_settings({"commands": [{"name": "review", "description": "리뷰", "body": "리뷰하라: $ARGUMENTS"}]})
        s = agentic_store.get_session(self.sid)
        self.assertEqual(runner.match_command(s, "/review 이 파일"), ("review", "이 파일", "command"))
        self.assertIsNone(runner.match_command(s, "/nothing"))
        with self.assertRaises(runner.NotRepo):
            await runner.make_checkpoint(self.sid, "x")
        with self.assertRaises(runner.NotRepo):
            await runner.restore_checkpoint(self.sid)
        self.assertIsNone(await runner.make_checkpoint(self.sid, "x", seq=1, quiet=True))   # 턴 시작 자리 / the turn-start call
        self.never_called(blocked)


# ────────────────────────────────────────────────────────
# API
# ────────────────────────────────────────────────────────

class ApiTests(BrowserCase):
    async def test_create_patch_get_and_settings(self):
        r = await self.req("POST", "/api/agentic/sessions", {"acting_user_id": "", "kind": "browser", "folder": "새 폴더",
                                                              "perm_mode": "ask"})
        self.assertEqual(r.status_code, 200, r.text)
        s = r.json()["session"]
        self.assertEqual((s["kind"], s["folder"], s["title"], s["perm_mode"]), ("browser", "새 폴더", "새 폴더", "ask"))
        r = await self.req("POST", "/api/agentic/sessions", {"acting_user_id": "7", "kind": "browser", "folder": NAME})
        self.assertEqual(r.status_code, 200, r.text)                                  # 메뉴 권한이면 된다 / the menu permission suffices
        for body, detail in (({"kind": "cloud", "folder": NAME}, "kind 는 local 또는 browser"),
                             ({"kind": "browser", "folder": "a/b"}, None), ({"kind": "browser", "folder": ""}, None),
                             ({"kind": "browser", "folder": NAME, "model": "gpt"}, None)):
            r = await self.req("POST", "/api/agentic/sessions", {"acting_user_id": "", **body})
            self.assertEqual(r.status_code, 422, (body, r.text))
            if detail:
                self.assertEqual(r.json()["detail"], detail)
        r = await self.req("POST", "/api/agentic/sessions", {"acting_user_id": "", "folder": self.root})   # kind 없음 = local
        self.assertEqual((r.status_code, r.json()["session"]["kind"]), (200, "local"))
        r = await self.req("PATCH", f"/api/agentic/sessions/{s['id']}", {"acting_user_id": "", "extra_folders": [self.root]})
        self.assertEqual((r.status_code, r.json()["detail"]), (422, "내 컴퓨터 폴더 세션은 추가 폴더를 쓸 수 없습니다"))
        r = await self.req("PATCH", f"/api/agentic/sessions/{s['id']}", {"acting_user_id": "", "extra_folders": [],
                                                                         "title": "바꾼 제목"})
        self.assertEqual((r.status_code, r.json()["session"]["title"], r.json()["session"]["extra_folders"]), (200, "바꾼 제목", []))
        r = await self.req("GET", f"/api/agentic/sessions/{s['id']}?acting_user_id=")
        self.assertEqual(r.json()["git"], {"repo": False, "browser": True})
        listed = (await self.req("GET", "/api/agentic/sessions?acting_user_id=")).json()["sessions"]
        self.assertEqual({x["id"]: x["kind"] for x in listed}[s["id"]], "browser")
        for method, path, body in (("GET", "/api/agentic/settings?acting_user_id=", None),
                                   ("PUT", "/api/agentic/settings", {"acting_user_id": "", "settings": {}})):
            r = await self.req(method, path, body)
            self.assertEqual((r.status_code, r.json()["browser_folders"], r.json()["folder_picker"]), (200, True, True))

    async def test_server_folder_features_answer_409(self):
        agentic_store.upsert_output(self.sid, f"{NAME}/out/a.txt", "created", 3)
        base = f"/api/agentic/sessions/{self.sid}"
        for method, path, body, detail in (
                ("GET", f"{base}/files?acting_user_id=&path=", None, "내 컴퓨터 폴더는 브라우저가 직접 읽습니다"),
                ("GET", f"{base}/outputs/download?acting_user_id=&path=out/a.txt", None, "내 컴퓨터 폴더의 파일은 그 컴퓨터에 있습니다"),
                ("GET", f"{base}/changes?acting_user_id=", None, "내 컴퓨터 폴더 세션에서는 쓸 수 없습니다"),
                ("GET", f"{base}/changes/diff?acting_user_id=&path=a.txt", None, "내 컴퓨터 폴더 세션에서는 쓸 수 없습니다"),
                ("POST", f"{base}/commit", {"acting_user_id": "", "message": "m"}, "내 컴퓨터 폴더 세션에서는 쓸 수 없습니다"),
                ("GET", f"{base}/commit/suggest?acting_user_id=", None, "내 컴퓨터 폴더 세션에서는 쓸 수 없습니다"),
                ("POST", f"{base}/checkpoints", {"acting_user_id": "", "label": "x"}, "내 컴퓨터 폴더 세션에서는 쓸 수 없습니다"),
                ("POST", f"{base}/checkpoints/cp_x/restore", {"acting_user_id": ""}, "내 컴퓨터 폴더 세션에서는 쓸 수 없습니다")):
            r = await self.req(method, path, body)
            self.assertEqual((r.status_code, r.json()["detail"]), (409, detail), path)
        outs = (await self.req("GET", f"{base}/outputs?acting_user_id=")).json()["outputs"]
        self.assertEqual([(o["path"], o["rel"], o["exists"]) for o in outs], [(f"{NAME}/out/a.txt", "out/a.txt", True)])
        agentic_store.put_settings({"commands": [{"name": "review", "description": "리뷰", "body": "리뷰하라"}]})
        rows = (await self.req("GET", f"{base}/commands?acting_user_id=")).json()["commands"]
        self.assertIn(("review", "global"), [(c["name"], c["source"]) for c in rows])

    async def test_tool_results_and_tool_requests(self):
        job = asyncio.ensure_future(self.call(ab.request, self.sid, "read", {"path": "a.txt", "max_bytes": 10}))
        await self.until(lambda: len(ab.pending(self.sid)) == 1)
        r = await self.req("GET", f"/api/agentic/sessions/{self.sid}/tool-requests?acting_user_id=")
        self.assertEqual(r.status_code, 200)
        rows = r.json()["requests"]
        self.assertEqual([(x["op"], x["args"]) for x in rows], [("read", {"path": "a.txt", "max_bytes": 10})])
        rid = rows[0]["request_id"]
        self.assertEqual((await self.req("GET", f"/api/agentic/sessions/{self.sid}/tool-requests?acting_user_id=7")).status_code, 404)
        url = f"/api/agentic/sessions/{self.sid}/tool-results"
        r = await self.req("POST", url, {"acting_user_id": "", "request_id": "br_unknown", "ok": True, "result": {}})
        self.assertEqual(r.status_code, 404)
        r = await self.req("POST", url, {"acting_user_id": "7", "request_id": rid, "ok": True, "result": {}})
        self.assertEqual(r.status_code, 404)                                          # 남의 세션 / not the owner's session
        r = await self.req("POST", url, {"acting_user_id": "", "request_id": rid, "ok": True,
                                         "result": {"text": "본문", "size": 6, "binary": False, "extracted": False}})
        self.assertEqual((r.status_code, r.json()), (200, {"accepted": True}))
        self.assertEqual((await job)["text"], "본문")
        r = await self.req("POST", url, {"acting_user_id": "", "request_id": rid, "ok": True, "result": {}})
        self.assertEqual(r.status_code, 409)                                          # 다른 탭이 먼저 답함 / another tab was first
        # 오류 답 / an error answer
        job = asyncio.ensure_future(self.call(ab.request, self.sid, "list", {"path": "sub"}))
        await self.until(lambda: len(ab.pending(self.sid)) == 1)
        rid = ab.pending(self.sid)[0]["request_id"]
        r = await self.req("POST", url, {"acting_user_id": "", "request_id": rid, "ok": False, "code": "notfound",
                                         "error": "NotFoundError"})
        self.assertEqual(r.status_code, 200)
        with self.assertRaises(agentic_exec.ExecError) as cm:
            await job
        self.assertEqual(str(cm.exception), "폴더가 없습니다: sub")

    async def test_a_late_answer_after_a_timeout_is_409(self):
        with patch.object(ab, "BROWSER_TIMEOUT_SEC", 0.3):
            job = asyncio.ensure_future(self.call(ab.request, self.sid, "list", {"path": ""}))
            await self.until(lambda: len(ab.pending(self.sid)) == 1)
            rid = ab.pending(self.sid)[0]["request_id"]
            with self.assertRaises(ab.BrowserTimeout):
                await job
        r = await self.req("POST", f"/api/agentic/sessions/{self.sid}/tool-results",
                           {"acting_user_id": "", "request_id": rid, "ok": True, "result": {"entries": []}})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "이미 끝난 요청입니다"))
        self.assertEqual((await self.req("GET", f"/api/agentic/sessions/{self.sid}/tool-requests?acting_user_id=")).json(),
                         {"requests": []})

    async def test_extract_reads_documents_only(self):
        self.assertEqual(agentic_api.EXTRACT_MAX_BYTES, 20 * 1024 * 1024)

        async def post(name: str, data: bytes, who: str = ""):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                return await client.post("/api/agentic/extract", data={"acting_user_id": who},
                                         files={"file": (name, data, "application/octet-stream")})
        r = await post("보고서.docx", docx_bytes("경동 보고서 본문"))
        self.assertEqual((r.status_code, r.json()), (200, {"text": "경동 보고서 본문", "chars": 9, "truncated": False}))
        r = await post("메모.txt", "글".encode("utf-8"))
        self.assertEqual((r.status_code, r.json()["detail"]), (422, "지원하지 않는 문서 형식"))
        r = await post("확장자없음", b"x")
        self.assertEqual(r.status_code, 422)
        r = await post("깨진.pdf", b"%PDF-1.4 not really")
        self.assertEqual((r.status_code, r.json()["text"]), (200, ""))                # 깨진 파일 = 빈 글 / a broken file
        with patch.object(agentic_exec, "READ_MAX_CHARS", 2):
            r = await post("긴.docx", docx_bytes("가나다라마바사아자차"))
        self.assertEqual(r.json(), {"text": "가나다라마바사아", "chars": 8, "truncated": True})
        with patch.object(agentic_api, "EXTRACT_MAX_BYTES", 1000):
            r = await post("큰.pdf", b"x" * 1001)
        self.assertEqual(r.status_code, 413)
        self.assertEqual((await post("보고서.docx", docx_bytes("x"), who="8")).status_code, 403)   # 메뉴 권한 없음 / no menu

    async def test_the_stream_sends_transient_events_as_tool_request(self):
        runner.emit(self.sid, "status", {"state": "idle"})
        last = agentic_store.get_session(self.sid)["last_seq"]
        reader = asyncio.ensure_future(read_sse(self.app, f"/api/agentic/sessions/{self.sid}/stream?acting_user_id=&after={last}",
                                                want=1))
        await self.until(lambda: runner.subscriber_count(self.sid) == 1)
        payload = {"request_id": "br0123456789", "session_id": self.sid, "op": "list", "args": {"path": ""}, "ts": "t"}
        await asyncio.to_thread(runner.push_transient, self.sid, payload)            # 워커 스레드에서 / from a worker thread
        code, body = await reader
        text = body.decode("utf-8")
        self.assertEqual(code, 200)
        self.assertIn("event: tool_request", text)
        data = next(ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:"))
        self.assertEqual(json.loads(data), payload)
        self.assertFalse(any(ln.startswith("id:") for ln in text.splitlines()))       # seq 가 없다 / no seq id
        # 재생 구간에는 없다(DB 에 쓰지 않았다) / never replayed (not in the DB)
        self.assertEqual(agentic_store.get_session(self.sid)["last_seq"], last)

    async def test_delete_cancels_a_pending_request(self):
        job = asyncio.ensure_future(self.call(ab.request, self.sid, "list", {"path": ""}))
        await self.until(lambda: len(ab.pending(self.sid)) == 1)
        r = await self.req("DELETE", f"/api/agentic/sessions/{self.sid}?acting_user_id=")
        self.assertEqual(r.status_code, 200)
        with self.assertRaises(agentic_exec.ExecError) as cm:
            await job
        self.assertEqual(str(cm.exception), "세션이 삭제되었습니다")
        self.assertIsNone(agentic_store.get_session(self.sid))


# ────────────────────────────────────────────────────────
# 원격 클라이언트 정책(배포 서버) / the remote-client policy (deployed server)
# ────────────────────────────────────────────────────────

REMOTE_CLIENT = ("203.0.113.5", 5555)   # 문서용 주소(TEST-NET-3) = 루프백 아님 / a documentation address, not loopback


class RemoteTests(BrowserCase):
    async def remote(self, method: str, path: str, json=None, **kw):
        transport = httpx.ASGITransport(app=self.app, client=REMOTE_CLIENT)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, json=json, **kw)

    async def test_remote_clients_create_and_use_browser_sessions_only(self):
        local = agentic_store.create_session("", self.root)
        r = await self.remote("POST", "/api/agentic/sessions", {"acting_user_id": "", "kind": "browser", "folder": "원격 폴더"})
        self.assertEqual((r.status_code, r.json()["session"]["kind"]), (200, "browser"), r.text)
        made = r.json()["session"]["id"]
        for body in ({"acting_user_id": "", "folder": self.root}, {"acting_user_id": "", "kind": "local", "folder": self.root}):
            r = await self.remote("POST", "/api/agentic/sessions", body)
            self.assertEqual((r.status_code, r.json()["detail"]), (403, "원격에서는 내 컴퓨터 폴더 세션만 만들 수 있습니다"))
        listed = (await self.remote("GET", "/api/agentic/sessions?acting_user_id=")).json()["sessions"]
        self.assertEqual({s["id"] for s in listed}, {self.sid, made})                  # 서버 폴더 세션은 빠진다 / local left out
        everything = (await self.req("GET", "/api/agentic/sessions?acting_user_id=")).json()["sessions"]
        self.assertIn(local["id"], {s["id"] for s in everything})                       # 로컬은 종전 그대로 / local as before
        # 서버 폴더 세션의 세션 단위 엔드포인트는 전부 403 / every session endpoint of a local session is 403
        base = f"/api/agentic/sessions/{local['id']}"
        calls = [("GET", f"{base}?acting_user_id=", None), ("PATCH", base, {"acting_user_id": "", "title": "x"}),
                 ("POST", f"{base}/messages", {"acting_user_id": "", "text": "안녕"}),
                 ("POST", f"{base}/stop", {"acting_user_id": ""}),
                 ("POST", f"{base}/approvals/a1", {"acting_user_id": "", "decision": "allow"}),
                 ("GET", f"{base}/events?acting_user_id=", None),
                 ("POST", f"{base}/tool-results", {"acting_user_id": "", "request_id": "br1", "ok": True}),
                 ("GET", f"{base}/tool-requests?acting_user_id=", None), ("POST", f"{base}/seen", {"acting_user_id": "", "seq": 1}),
                 ("GET", f"{base}/outputs?acting_user_id=", None), ("GET", f"{base}/commands?acting_user_id=", None),
                 ("GET", f"{base}/tasks?acting_user_id=", None), ("GET", f"{base}/files?acting_user_id=", None),
                 ("GET", f"{base}/checkpoints?acting_user_id=", None), ("DELETE", f"{base}?acting_user_id=", None)]
        for method, path, body in calls:
            r = await self.remote(method, path, body)
            self.assertEqual((r.status_code, r.json()["detail"]), (403, "원격에서는 내 컴퓨터 폴더 세션만 쓸 수 있습니다"),
                             (method, path))
        code, _body = await read_sse(self.app, f"{base}/stream?acting_user_id=", client=REMOTE_CLIENT)
        self.assertEqual(code, 403)
        self.assertIsNotNone(agentic_store.get_session(local["id"]))                    # 지워지지 않았다 / not deleted
        # 내 컴퓨터 폴더 세션은 원격에서도 된다 / browser sessions work remotely
        ok = f"/api/agentic/sessions/{self.sid}"
        for method, path, body in (("GET", f"{ok}?acting_user_id=", None), ("PATCH", ok, {"acting_user_id": "", "title": "원격"}),
                                   ("GET", f"{ok}/events?acting_user_id=", None), ("GET", f"{ok}/tool-requests?acting_user_id=", None),
                                   ("POST", f"{ok}/seen", {"acting_user_id": "", "seq": 0}), ("GET", f"{ok}/outputs?acting_user_id=", None),
                                   ("GET", f"{ok}/commands?acting_user_id=", None), ("GET", f"{ok}/tasks?acting_user_id=", None)):
            r = await self.remote(method, path, body)
            self.assertEqual(r.status_code, 200, (method, path, r.text))
        # 원격 메시지 → 턴이 브라우저 실행기로 돈다 / a remote message runs a turn on the browser executor
        b = self.browser(**{"a.txt": "원격\n"})
        self.stack.enter_context(patch("app.llm.generate_calls",
                                       side_effect=FakeModel({"calls": [("read_file", {"path": "a.txt"})]}, {"text": "읽었습니다"})))
        r = await self.remote("POST", f"{ok}/messages", {"acting_user_id": "", "text": "a.txt 읽어줘"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(await runner.join(self.sid, 30))
        self.assertEqual(self.of("assistant")[-1]["text"], "읽었습니다")
        self.assertIn("a.txt", [p["args"]["path"] for p in b.ops("read")])
        # 원격에서 브라우저의 답(tool-results) / the browser's answer arriving remotely
        await b.close()
        self.browsers.remove(b)
        job = asyncio.ensure_future(self.call(ab.request, self.sid, "list", {"path": ""}))
        await self.until(lambda: len(ab.pending(self.sid)) == 1)
        rid = ab.pending(self.sid)[0]["request_id"]
        r = await self.remote("POST", f"{ok}/tool-results", {"acting_user_id": "", "request_id": rid, "ok": True,
                                                              "result": {"entries": []}})
        self.assertEqual((r.status_code, r.json()), (200, {"accepted": True}))
        self.assertEqual(await job, {"entries": []})
        r = await self.remote("DELETE", f"/api/agentic/sessions/{made}?acting_user_id=")
        self.assertEqual(r.status_code, 200)

    async def test_remote_clients_cannot_pick_server_folders_or_change_settings(self):
        self.stack.enter_context(patch.object(agentic_api.subprocess, "run", side_effect=AssertionError("no window")))
        for method, path, body, detail in (
                ("POST", "/api/agentic/pick-folder", {"acting_user_id": ""}, "원격에서는 서버 폴더를 고를 수 없습니다"),
                ("GET", "/api/agentic/browse?acting_user_id=", None, "원격에서는 서버 폴더를 고를 수 없습니다"),
                ("GET", f"/api/agentic/browse?acting_user_id=&path={self.root}", None, "원격에서는 서버 폴더를 고를 수 없습니다"),
                ("PUT", "/api/agentic/settings", {"acting_user_id": "", "settings": {}}, "설정은 서버 PC(로컬)에서만 바꿀 수 있습니다")):
            r = await self.remote(method, path, body)
            self.assertEqual((r.status_code, r.json()["detail"]), (403, detail), path)
        got = (await self.remote("GET", "/api/agentic/settings?acting_user_id=")).json()
        self.assertEqual((got["remote"], got["folder_picker"], got["browser_folders"]), (True, False, True))
        here = (await self.req("GET", "/api/agentic/settings?acting_user_id=")).json()
        self.assertEqual((here["remote"], here["folder_picker"], here["browser_folders"]), (False, True, True))
        for path in ("/api/agentic/models?acting_user_id=", "/api/agentic/connectors?acting_user_id="):
            self.assertEqual((await self.remote("GET", path)).status_code, 200, path)
        r = await self.remote("POST", "/api/agentic/extract", data={"acting_user_id": ""},
                              files={"file": ("원격.docx", docx_bytes("원격 본문"), "application/octet-stream")})
        self.assertEqual((r.status_code, r.json()["text"]), (200, "원격 본문"))
        # 신원 · 메뉴 권한 검사는 원격에도 그대로 / the identity and menu checks still apply remotely
        self.assertEqual((await self.remote("GET", "/api/agentic/sessions?acting_user_id=abc")).status_code, 403)
        self.assertEqual((await self.remote("GET", "/api/agentic/sessions?acting_user_id=8")).status_code, 403)

    async def test_allow_remote_keeps_the_old_behavior(self):
        self.stack.enter_context(patch("app.settings.AGENTIC_ALLOW_REMOTE", True))
        got = (await self.remote("GET", "/api/agentic/settings?acting_user_id=")).json()
        self.assertEqual((got["remote"], got["folder_picker"]), (False, True))
        r = await self.remote("POST", "/api/agentic/sessions", {"acting_user_id": "", "folder": self.root})
        self.assertEqual((r.status_code, r.json()["session"]["kind"]), (200, "local"))
        self.assertEqual((await self.remote("GET", f"/api/agentic/sessions/{r.json()['session']['id']}?acting_user_id=")).status_code,
                         200)
        self.assertEqual((await self.remote("GET", "/api/agentic/browse?acting_user_id=")).status_code, 200)


if __name__ == "__main__":
    unittest.main()
