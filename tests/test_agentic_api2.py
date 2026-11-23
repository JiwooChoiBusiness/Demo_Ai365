# -*- coding: utf-8 -*-
"""Agentic 모드 2차 · 3차 API(2026-10-19): 설정 새 키 검증 · PATCH(connectors · notify · plan/prev_perm) · 메시지 mode 와
슬래시 명령(실행 중 409) · seen · 체크포인트(만들기 · 되돌리기, 저장소 아님 422 · 실행 중 409) · 산출물 목록 · 내려받기(밖 403 ·
없음 404 · 비밀 파일 403) · git 변경 · diff · 커밋 · 제안 · 명령 · 연결 도구 목록 · 서브에이전트 작업 행 · 삭제 때 ref 정리 · 권한.
실제 LLM · 실 DB · 네트워크 없음(임시 DB · 가짜 모델 · 권한 함수 패치, git 은 임시 저장소에서 실제로).

Agentic mode phases 2 and 3, the API (2026-10-19): new setting keys, PATCH (connectors, notify, plan/prev_perm), message
modes and slash commands (409 while running), seen, checkpoints (create and restore; 422 outside a repository, 409 while
running), outputs and downloads (403 outside or for the secrets file, 404 when missing), git changes, diffs, commits and
suggestions, command and connector lists, subagent task rows, ref cleanup on delete and permissions. No real LLM, real
DB or network (temp DB, fake models, patched permission lookup; git runs for real in temporary repositories).

폴더 고르기(2026-10-19): browse(처음 목록 · 하위 폴더 · 밖 403 · 없음 404 · 파일 422 · 숨김 제외 · 슈퍼 drives · 500개 상한) ·
pick-folder(AI365_PICK_FAKE 로 자식을 실제로 돌려 경로 · 취소 · 밖, 동시 2회 409, 띄울 수 없으면 503) · app.agentic_pick 의 JSON 한 줄.
Folder picking (2026-10-19): browse (top list, subfolders, 403 outside, 404 missing, 422 for files, hidden ones left out,
drives for the super admin, the 500 cap), pick-folder (the child really runs with AI365_PICK_FAKE: path, cancel, outside;
409 for a second one; 503 when no window can open) and the one JSON line of app.agentic_pick."""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

import httpx
from fastapi import FastAPI

from db_fixture import isolate_db
from app import agentic_api, agentic_exec, agentic_runner as runner, agentic_store, agentic_tools

GIT = shutil.which("git")


def git(cwd: str, *args: str) -> str:
    r = subprocess.run([GIT, "-c", "user.email=t@t", "-c", "user.name=t", "-c", "core.autocrlf=false", *args], cwd=cwd,
                       capture_output=True, timeout=60)
    if r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} 실패: {r.stderr.decode('utf-8', 'replace')}")
    return r.stdout.decode("utf-8", "replace")


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def eff_of(acting_user_id):
    """권한 함수 대역: '' = 슈퍼(None), 7 = m_agentic 있음, 그 밖 숫자 = 없음 / stand-in for resources_api._eff"""
    aid = (acting_user_id or "").strip()
    if not aid or not aid.isdigit():
        return None
    return {"no": int(aid), "menus": {"m_home": True, "m_agentic": True} if aid == "7" else {"m_home": True},
            "nodes": {}, "mgmt": {}, "read": {}}


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


def fake_module(stack: ExitStack, name: str, **funcs):
    """app.<name> 함수 바꿔 끼우기(진짜 모듈이 없으면 가짜 모듈) / swap functions of app.<name>, faking a missing module"""
    import app
    try:
        mod = __import__(f"app.{name}", fromlist=[name])
    except ImportError:
        mod = types.ModuleType(f"app.{name}")
        stack.enter_context(patch.dict(sys.modules, {f"app.{name}": mod}))
        stack.enter_context(patch.object(app, name, mod, create=True))
    for k, v in funcs.items():
        stack.enter_context(patch.object(mod, k, v, create=True))
    return mod


class Api2Case(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        agentic_store.init_agentic()
        self.root = os.path.realpath(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.outside = os.path.realpath(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.proj = os.path.join(self.root, "proj")
        write(os.path.join(self.proj, "README.md"), "# 데모\nhello\n")
        write(os.path.join(self.outside, "secret.txt"), "밖\n")
        agentic_store.put_settings({"allowed_folders": [self.root], "deny_commands": [r"\bdanger_word\b"]})
        self.stack.enter_context(patch("app.resources_api._eff", side_effect=eff_of))
        self.stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")))
        self.stack.enter_context(patch("app.llm.generate_grounded_meta", side_effect=AssertionError("unexpected web")))
        self.stack.enter_context(patch("app.notify.send_mail", side_effect=AssertionError("unexpected mail")))
        runner.REGISTRY.clear()
        runner.SUBS.clear()
        runner._BUSY.clear()
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
        runner._BUSY.clear()

    async def req(self, method, path, json=None):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
            return await client.request(method, path, json=json)

    async def make(self, folder: str | None = None, who: str = "", **extra) -> dict:
        r = await self.req("POST", "/api/agentic/sessions", {"acting_user_id": who, "folder": folder or self.proj, **extra})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["session"]

    async def events(self, sid: str) -> list[dict]:
        r = await self.req("GET", f"/api/agentic/sessions/{sid}/events?acting_user_id=&after=0&limit=2000")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["events"]

    async def post(self, sid: str, text: str, **extra):
        return await self.req("POST", f"/api/agentic/sessions/{sid}/messages", {"acting_user_id": "", "text": text, **extra})

    async def until(self, pred, timeout: float = 20.0):
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

    def hold(self) -> tuple[threading.Event, threading.Event]:
        """모델 호출을 붙잡는 가짜 모델을 건다 → (release, entered) / patch in a model call that waits to be released"""
        release, entered = threading.Event(), threading.Event()
        self.gates.append(release)

        def held():
            entered.set()
            release.wait(10)
            return {"text": "늦은 답"}
        self.stack.enter_context(patch("app.llm.generate_calls", side_effect=fake_model(held)))
        return release, entered

    def repo(self, name: str = "repo") -> str:
        path = os.path.join(self.root, name)
        os.makedirs(path)
        git(path, "init", "-q")
        git(path, "config", "core.autocrlf", "false")
        write(os.path.join(path, "README.md"), "hello teh\n")
        git(path, "add", "-A")
        git(path, "commit", "-q", "-m", "init")
        return path


class SettingsAndPatchTests(Api2Case):
    async def test_settings_have_the_phase2_keys_and_validate_commands_skills_hooks(self):
        st = (await self.req("GET", "/api/agentic/settings?acting_user_id=")).json()["settings"]
        self.assertEqual((st["notify_default"], st["commands"], st["skills"], st["hooks"]), (False, [], [], []))
        self.assertEqual({k: st["budgets"][k] for k in ("compact_pct", "max_subagents", "subagent_max_steps")},
                         {"compact_pct": 80, "max_subagents": 3, "subagent_max_steps": 60})
        good = {"commands": [{"name": "review", "description": "리뷰", "body": "리뷰하라: $ARGUMENTS"}],
                "skills": [{"name": "style", "description": "문체", "body": "존댓말"}],
                "hooks": [{"event": "pre_tool", "matcher": "^bash$", "command": "echo hi", "timeout_sec": 5}],
                "notify_default": True, "default_perm": "plan",
                "budgets": {"compact_pct": 50, "max_subagents": 2, "subagent_max_steps": 10}}
        r = await self.req("PUT", "/api/agentic/settings", {"acting_user_id": "", "settings": good})
        self.assertEqual(r.status_code, 200, r.text)
        st = r.json()["settings"]
        self.assertEqual(([c["name"] for c in st["commands"]], [s["name"] for s in st["skills"]], st["hooks"][0]["matcher"],
                          st["notify_default"], st["default_perm"], st["budgets"]["max_subagents"]),
                         (["review"], ["style"], "^bash$", True, "plan", 2))
        for bad in ({"commands": [{"name": "Bad Name", "body": "x"}]}, {"commands": [{"name": "help", "body": "x"}]},
                    {"skills": "nope"}, {"hooks": [{"event": "nope", "command": "x"}]},
                    {"hooks": [{"event": "pre_tool", "matcher": "(", "command": "x"}]},
                    {"budgets": {"compact_pct": 20}}, {"budgets": {"max_subagents": 9}}, {"budgets": {"subagent_max_steps": 4}},
                    {"notify_default": "yes"}):
            r = await self.req("PUT", "/api/agentic/settings", {"acting_user_id": "", "settings": bad})
            self.assertEqual(r.status_code, 422, (bad, r.text))
        self.assertEqual(agentic_store.get_settings()["budgets"]["compact_pct"], 50)              # 실패한 PUT 은 그대로 / unchanged
        s = await self.make()
        self.assertEqual((s["perm_mode"], s["notify"], s["prev_perm"]), ("plan", True, ""))        # 새 기본값 / new defaults

    async def test_patch_connectors_notify_and_plan_mode(self):
        fake_module(self.stack, "agentic_mcp", get=lambda cid: {"id": cid} if cid.startswith("cn_m") else None)
        s = await self.make()
        url = f"/api/agentic/sessions/{s['id']}"
        r = await self.req("PATCH", url, {"acting_user_id": "", "connectors": ["cn_ma", "cn_ma", " cn_mb "], "notify": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["session"]["connectors"], r.json()["session"]["notify"]), (["cn_ma", "cn_mb"], True))
        for bad in ({"connectors": ["cn_zz"]}, {"connectors": [f"cn_m{i}" for i in range(21)]}, {"perm_mode": "yolo"}):
            r = await self.req("PATCH", url, {"acting_user_id": "", **bad})
            self.assertEqual(r.status_code, 422, (bad, r.text))
        self.assertEqual(agentic_store.get_session(s["id"])["connectors"], ["cn_ma", "cn_mb"])
        r = await self.req("PATCH", url, {"acting_user_id": "", "perm_mode": "plan"})
        self.assertEqual((r.json()["session"]["perm_mode"], r.json()["session"]["prev_perm"]), ("plan", "auto"))
        r = await self.req("PATCH", url, {"acting_user_id": "", "perm_mode": "ask"})
        self.assertEqual((r.json()["session"]["perm_mode"], r.json()["session"]["prev_perm"]), ("ask", ""))
        r = await self.req("PATCH", url, {"acting_user_id": "", "connectors": []})
        self.assertEqual(r.json()["session"]["connectors"], [])
        listed = (await self.req("GET", "/api/agentic/sessions?acting_user_id=")).json()["sessions"][0]
        self.assertEqual((listed["notify"], listed["seen_seq"], listed["last_seq"]), (True, 0, 0))


class MessageApiTests(Api2Case):
    async def test_modes_and_slash_commands(self):
        s = await self.make()
        url = f"/api/agentic/sessions/{s['id']}/messages"
        self.assertEqual((await self.post(s["id"], "hi", mode="nope")).status_code, 422)
        self.stack.enter_context(patch("app.llm.generate_calls", side_effect=AssertionError("no model for builtins")))
        r = await self.post(s["id"], "/help")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["command"], body["queued"], body["steered"], body["session"]["id"]), ("help", False, False, s["id"]))
        evs = await self.events(s["id"])
        self.assertEqual([(e["kind"], e["payload"].get("command")) for e in evs], [("user", "help"), ("assistant", True)])
        r = await self.post(s["id"], "/plan")
        self.assertEqual((r.json()["command"], r.json()["session"]["perm_mode"]), ("plan", "plan"))
        await self.post(s["id"], "/auto")
        # 실행 중: 명령은 409, 보통 글은 스티어링, 명령이 아닌 '/경로' 글도 보통 글 / while running
        release, entered = self.hold()
        r = await self.post(s["id"], "길게 해 줘")
        self.assertEqual((r.json()["queued"], r.json()["steered"], r.json()["session"]["status"]), (False, False, "running"))

        async def started():
            return entered.is_set()
        await self.until(started)
        r = await self.post(s["id"], "/help")
        self.assertEqual((r.status_code, r.json()), (409, {"detail": "실행 중에는 명령을 쓸 수 없습니다"}))
        r = await self.post(s["id"], "README 도 봐", mode="steer")
        self.assertEqual((r.status_code, r.json()["queued"], r.json()["steered"]), (200, False, True))
        r = await self.post(s["id"], "/usr/bin/env 를 읽어")
        self.assertEqual((r.status_code, r.json()["steered"]), (200, True))
        r = await self.post(s["id"], "그다음", mode="queue")
        self.assertEqual((r.json()["queued"], r.json()["steered"]), (True, False))
        r = await self.req("POST", f"/api/agentic/sessions/{s['id']}/stop", {"acting_user_id": ""})
        self.assertEqual(r.json()["session"]["status"], "stopped")
        release.set()
        # /clear = 같은 폴더 · 모델 · 권한의 새 세션 / a new session with the same folder, model and mode
        r = await self.post(s["id"], "/clear")
        new = r.json()["session"]
        self.assertEqual(r.json()["command"], "clear")
        self.assertNotEqual(new["id"], s["id"])
        self.assertEqual((new["folder"], new["model"], new["perm_mode"]), (s["folder"], s["model"], "auto"))
        sessions = {x["id"] for x in (await self.req("GET", "/api/agentic/sessions?acting_user_id=")).json()["sessions"]}
        self.assertEqual(sessions, {s["id"], new["id"]})
        self.assertEqual(url, f"/api/agentic/sessions/{s['id']}/messages")

    async def test_a_folder_command_starts_a_turn_with_the_expanded_prompt(self):
        write(os.path.join(self.proj, ".ai365", "commands", "review.md"), "리뷰하라: $ARGUMENTS\n")
        s = await self.make()
        seen = []

        def model(messages, system=None, tools=None, tier="main", models=None):
            seen.append(messages[-1]["content"])
            return {"calls": [], "text": "리뷰했습니다."}
        with patch("app.llm.generate_calls", side_effect=model):
            r = await self.post(s["id"], "/review app.py")
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual((r.json()["command"], r.json()["queued"]), ("review", False))
            evs = await self.idle(s["id"])
        self.assertEqual(evs[0]["payload"], {"text": "/review app.py", "command": "review", "expanded": "리뷰하라: app.py"})
        self.assertEqual(seen, ["리뷰하라: app.py"])

    async def test_seen_is_capped_and_never_goes_back(self):
        s = await self.make()
        for _ in range(4):
            runner.emit(s["id"], "status", {"state": "idle"})
        url = f"/api/agentic/sessions/{s['id']}/seen"
        r = await self.req("POST", url, {"acting_user_id": "", "seq": 3})
        self.assertEqual(r.json()["session"]["seen_seq"], 3)
        r = await self.req("POST", url, {"acting_user_id": "", "seq": 99})
        self.assertEqual(r.json()["session"]["seen_seq"], 4)
        r = await self.req("POST", url, {"acting_user_id": "", "seq": 1})
        self.assertEqual(r.json()["session"]["seen_seq"], 4)
        self.assertEqual((await self.req("POST", url, {"acting_user_id": "7", "seq": 1})).status_code, 404)


@unittest.skipUnless(GIT, "git 이 필요합니다 / git is required")
class GitApiTests(Api2Case):
    async def test_non_repo_sessions_get_422_or_an_empty_change_list(self):
        s = await self.make()
        base = f"/api/agentic/sessions/{s['id']}"
        r = await self.req("POST", f"{base}/checkpoints", {"acting_user_id": "", "label": "x"})
        self.assertEqual((r.status_code, r.json()), (422, {"detail": "git 저장소가 아닙니다"}))
        self.assertEqual((await self.req("GET", f"{base}/checkpoints?acting_user_id=")).json(), {"checkpoints": []})
        ch = (await self.req("GET", f"{base}/changes?acting_user_id=")).json()
        self.assertEqual((ch["repo"], ch["files"], ch["count"], ch["last_checkpoint"]), (False, [], 0, None))
        self.assertEqual((await self.req("GET", f"{base}/changes/diff?acting_user_id=&path=README.md")).status_code, 422)
        self.assertEqual((await self.req("POST", f"{base}/commit", {"acting_user_id": "", "message": "x"})).status_code, 422)
        self.assertEqual((await self.req("GET", f"{base}/commit/suggest?acting_user_id=")).status_code, 422)

    async def test_checkpoints_restore_changes_diff_suggest_commit_and_ref_cleanup(self):
        path = self.repo()
        s = await self.make(path)
        base = f"/api/agentic/sessions/{s['id']}"
        r = await self.req("POST", f"{base}/checkpoints", {"acting_user_id": "", "label": "처음"})
        self.assertEqual(r.status_code, 200, r.text)
        cp = r.json()["checkpoint"]
        self.assertEqual(set(cp), {"id", "seq", "ref", "commit", "tree", "label", "files", "ts"})
        self.assertEqual((cp["label"], cp["files"]), ("처음", 1))
        evs = await self.events(s["id"])
        self.assertEqual([(e["kind"], e["payload"]["action"], "seq" in e["payload"]) for e in evs], [("checkpoint", "create", False)])
        self.assertEqual([c["id"] for c in (await self.req("GET", f"{base}/checkpoints?acting_user_id=")).json()["checkpoints"]],
                         [cp["id"]])
        write(os.path.join(path, "README.md"), "hello the\nmore\n")
        write(os.path.join(path, "new.txt"), "n1\nn2\n")
        ch = (await self.req("GET", f"{base}/changes?acting_user_id=")).json()
        self.assertTrue(ch["repo"])
        files = {f["path"]: f for f in ch["files"]}
        self.assertEqual((files["README.md"]["status"], files["README.md"]["added"], files["README.md"]["removed"]), ("M", 2, 1))
        self.assertEqual((files["new.txt"]["status"], files["new.txt"]["added"]), ("?", 2))
        self.assertEqual((ch["count"], ch["added"], ch["removed"], ch["last_checkpoint"]["id"]), (2, 4, 1, cp["id"]))
        d = (await self.req("GET", f"{base}/changes/diff?acting_user_id=&path=README.md")).json()
        self.assertEqual((d["path"], d["status"], d["binary"], d["truncated"]), ("README.md", "M", False, False))
        self.assertIn("-hello teh\n+hello the\n", d["unified"])
        self.assertIn("+n1\n", (await self.req("GET", f"{base}/changes/diff?acting_user_id=&path=new.txt")).json()["unified"])
        self.assertEqual((await self.req("GET", f"{base}/changes/diff?acting_user_id=&path=" + quote("../x.txt"))).status_code, 403)
        self.assertEqual((await self.req("GET", f"{base}/changes/diff?acting_user_id=&path=")).status_code, 422)
        same = (await self.req("GET", f"{base}/changes/diff?acting_user_id=&path=nope.txt")).json()
        self.assertEqual((same["status"], same["unified"]), ("", ""))
        with patch("app.llm.generate", return_value="README 고침 / Fix README"):
            sug = (await self.req("GET", f"{base}/commit/suggest?acting_user_id=")).json()
        self.assertEqual(sug, {"message": "README 고침 / Fix README", "files": 2})
        # 되돌리기: 안전 저장 뒤 복원 / restore after a safety save
        r = await self.req("POST", f"{base}/checkpoints/{cp['id']}/restore", {"acting_user_id": ""})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["checkpoint"]["id"], r.json()["session"]["id"]), (cp["id"], s["id"]))
        self.assertEqual(read(os.path.join(path, "README.md")), "hello teh\n")
        self.assertFalse(os.path.exists(os.path.join(path, "new.txt")))
        evs = await self.events(s["id"])
        self.assertEqual([e["payload"]["action"] for e in evs], ["create", "create", "restore"])
        self.assertEqual((await self.req("POST", f"{base}/checkpoints/cp_nope/restore", {"acting_user_id": ""})).status_code, 404)
        # 커밋 / commit
        write(os.path.join(path, "README.md"), "hello the\n")
        self.assertEqual((await self.req("POST", f"{base}/commit", {"acting_user_id": "", "message": "  "})).status_code, 422)
        r = await self.req("POST", f"{base}/commit", {"acting_user_id": "", "message": "오타 / typo"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["ok"], len(r.json()["commit"]), r.json()["files"], r.json()["message"]), (True, 7, 1, "오타 / typo"))
        self.assertEqual(git(path, "log", "-1", "--format=%s").strip(), "오타 / typo")
        r = await self.req("POST", f"{base}/commit", {"acting_user_id": "", "message": "또 / again"})
        self.assertEqual(r.status_code, 422)                                                          # 변경 없음 / nothing to commit
        # 삭제하면 ref 도 지운다 / delete drops the refs
        from app import agentic_git
        self.assertEqual(len(agentic_git.list_refs(path, s["id"])), 2)
        self.assertEqual((await self.req("DELETE", f"{base}?acting_user_id=")).json(), {"ok": True})
        self.assertEqual(agentic_git.list_refs(path, s["id"]), [])

    async def test_restore_failures_report_the_safety_checkpoint_and_a_failed_save_refuses(self):
        from app import agentic_git
        path = self.repo()
        s = await self.make(path)
        base = f"/api/agentic/sessions/{s['id']}"
        cp = (await self.req("POST", f"{base}/checkpoints", {"acting_user_id": "", "label": "처음"})).json()["checkpoint"]
        write(os.path.join(path, "README.md"), "changed\n")
        with patch.object(agentic_git, "restore", side_effect=agentic_git.GitError("read-tree 실패")):
            r = await self.req("POST", f"{base}/checkpoints/{cp['id']}/restore", {"acting_user_id": ""})
        self.assertEqual(r.status_code, 422)
        body = r.json()
        self.assertIn(runner.RESTORE_PARTIAL, body["detail"])
        safety = agentic_store.get_checkpoint(body["safety_checkpoint_id"], s["id"])
        self.assertEqual(safety["label"], runner.CHECKPOINT_SAFETY_LABEL)
        with patch.object(agentic_git, "snapshot", side_effect=agentic_git.GitError("디스크가 가득 찼습니다")), \
                patch.object(agentic_git, "restore", side_effect=AssertionError("must not restore")):
            r = await self.req("POST", f"{base}/checkpoints/{cp['id']}/restore", {"acting_user_id": ""})
        self.assertEqual(r.status_code, 422)
        self.assertIn("되돌리지 않았습니다", r.json()["detail"])
        self.assertEqual(read(os.path.join(path, "README.md")), "changed\n")

    async def test_restore_and_commit_wait_for_background_commands(self):
        path = self.repo()
        s = await self.make(path)
        base = f"/api/agentic/sessions/{s['id']}"
        cp = (await self.req("POST", f"{base}/checkpoints", {"acting_user_id": ""})).json()["checkpoint"]
        ex = agentic_tools.make_executor(agentic_store.get_session(s["id"]), agentic_store.get_settings())
        if os.name == "nt":
            slow = f'"{sys.executable}" -c "import time; time.sleep(30)"'
        else:
            slow = f"'{sys.executable}' -c 'import time; time.sleep(30)'"
        ex.run(slow, background=True)
        self.addCleanup(agentic_exec.kill_session_tasks, s["id"])
        write(os.path.join(path, "README.md"), "changed\n")
        for url, body in ((f"{base}/checkpoints/{cp['id']}/restore", {"acting_user_id": ""}),
                          (f"{base}/commit", {"acting_user_id": "", "message": "x / x"})):
            r = await self.req("POST", url, body)
            self.assertEqual((r.status_code, r.json()["detail"]), (409, runner.BG_BUSY), url)
        agentic_exec.kill_session_tasks(s["id"])

        async def quiet():
            return agentic_exec.live_session_tasks(s["id"]) == 0
        await self.until(quiet)
        r = await self.req("POST", f"{base}/checkpoints/{cp['id']}/restore", {"acting_user_id": ""})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(read(os.path.join(path, "README.md")), "hello teh\n")
        task = agentic_store.list_tasks(s["id"])[0]

        async def closed():   # 감시 스레드가 작업 행을 마감할 때까지 / until the watcher closes the task row
            return (agentic_store.get_task(task["id"]) or {}).get("status") != "running"
        await self.until(closed)

    async def test_git_writes_are_refused_while_running(self):
        path = self.repo()
        s = await self.make(path)
        base = f"/api/agentic/sessions/{s['id']}"
        cp = (await self.req("POST", f"{base}/checkpoints", {"acting_user_id": ""})).json()["checkpoint"]
        self.assertEqual(cp["label"], runner.CHECKPOINT_MANUAL_LABEL)
        release, entered = self.hold()
        await self.post(s["id"], "길게")

        async def started():
            return entered.is_set()
        await self.until(started)
        for method, url, body in (("POST", f"{base}/checkpoints", {"acting_user_id": ""}),
                                  ("POST", f"{base}/checkpoints/{cp['id']}/restore", {"acting_user_id": ""}),
                                  ("POST", f"{base}/commit", {"acting_user_id": "", "message": "x / x"})):
            r = await self.req(method, url, body)
            self.assertEqual(r.status_code, 409, (url, r.text))
        release.set()
        evs = await self.idle(s["id"])
        self.assertEqual([e["kind"] for e in evs][:4], ["checkpoint", "user", "checkpoint", "status"])   # 턴 시작 체크포인트


class OutputApiTests(Api2Case):
    async def test_outputs_list_and_download_with_guards(self):
        s = await self.make()
        with patch("app.llm.generate_calls", side_effect=fake_model({"calls": [("write_file", {"path": "out/report.txt",
                                                                                               "content": "보고서\n"})]},
                                                                    {"text": "썼습니다."})):
            await self.post(s["id"], "보고서 써")
            await self.idle(s["id"])
        base = f"/api/agentic/sessions/{s['id']}"
        outs = (await self.req("GET", f"{base}/outputs?acting_user_id=")).json()["outputs"]
        target = os.path.join(os.path.realpath(self.proj), "out", "report.txt")
        self.assertEqual(len(outs), 1)
        self.assertEqual((outs[0]["path"], outs[0]["rel"], outs[0]["kind"], outs[0]["bytes"], outs[0]["exists"]),
                         (target, "out/report.txt", "created", os.path.getsize(target), True))
        self.assertEqual(set(outs[0]), {"path", "rel", "kind", "bytes", "ts", "exists"})
        r = await self.req("GET", f"{base}/outputs/download?acting_user_id=&path=" + quote(target))
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r.headers["content-disposition"])
        self.assertEqual(r.content.decode("utf-8"), "보고서\n")
        r = await self.req("GET", f"{base}/outputs/download?acting_user_id=&path=" + quote("out/report.txt"))
        self.assertEqual(r.status_code, 200)
        # H2: 이 세션의 산출물 행에 있는 경로만, 그 밖은 허용 폴더 안의 파일이라도 404 / only recorded outputs, else 404
        cases = ((quote(os.path.join(self.outside, "secret.txt")), 404), (quote("../../x.txt"), 404), ("nope.txt", 404),
                 ("README.md", 404), (quote(os.path.join(self.proj, "README.md")), 404), ("", 422))
        for p, code in cases:
            self.assertEqual((await self.req("GET", f"{base}/outputs/download?acting_user_id=&path={p}")).status_code, code, p)
        blob = os.path.join(self.proj, "out", "image.bin")   # 이진이라도 산출물 행이면 된다 / binaries are fine when recorded
        with open(blob, "wb") as f:
            f.write(b"\x89PNG\x00\x01\x02")
        agentic_store.upsert_output(s["id"], os.path.realpath(blob), "created", 7)
        r = await self.req("GET", f"{base}/outputs/download?acting_user_id=&path=" + quote("out/image.bin"))
        self.assertEqual((r.status_code, r.content), (200, b"\x89PNG\x00\x01\x02"))
        other = await self.make()                                                                  # 남의 세션 산출물은 404 / not this session's
        r = await self.req("GET", f"/api/agentic/sessions/{other['id']}/outputs/download?acting_user_id=&path=" + quote(target))
        self.assertEqual(r.status_code, 404)
        fake_env = os.path.join(self.proj, "fake.env")
        write(fake_env, "NOT_A_SECRET=1\n")
        with patch.object(agentic_exec, "PROTECTED_FILES", {os.path.normcase(os.path.realpath(fake_env))}):
            r = await self.req("GET", f"{base}/outputs/download?acting_user_id=&path=fake.env")
        self.assertEqual(r.status_code, 403)
        os.remove(target)
        listed = {o["path"]: o for o in (await self.req("GET", f"{base}/outputs?acting_user_id=")).json()["outputs"]}
        self.assertFalse(listed[target]["exists"])
        self.assertEqual((await self.req("GET", f"{base}/outputs/download?acting_user_id=&path=" + quote(target))).status_code, 404)
        self.assertEqual((await self.req("GET", f"{base}/outputs?acting_user_id=7")).status_code, 404)


class ListApiTests(Api2Case):
    async def test_commands_and_connectors_lists(self):
        write(os.path.join(self.proj, ".ai365", "commands", "review.md"), "---\ndescription: 리뷰\n---\n리뷰하라\n")
        write(os.path.join(self.proj, ".ai365", "skills", "style", "SKILL.md"), "---\ndescription: 문체\n---\n존댓말\n")
        s = await self.make()
        rows = (await self.req("GET", f"/api/agentic/sessions/{s['id']}/commands?acting_user_id=")).json()["commands"]
        builtin = [r["name"] for r in rows if r["source"] == "builtin"]
        self.assertEqual(builtin, sorted(runner.BUILTIN_NAMES))
        self.assertEqual([(r["name"], r["source"]) for r in rows if r["source"] != "builtin"], [("review", "folder"), ("style", "skill")])
        self.assertEqual(set(rows[0]), {"name", "description", "source", "args"})
        listed = [{"id": "cn_m1", "name": "ERP › 조회", "description": "조회", "kind": "read", "server_name": "ERP",
                   "tool": "lookup", "inputs": []}]
        fake_module(self.stack, "agentic_mcp", available=lambda: listed)
        self.assertEqual((await self.req("GET", "/api/agentic/connectors?acting_user_id=")).json(), {"connectors": listed})
        self.assertEqual((await self.req("GET", "/api/agentic/connectors?acting_user_id=8")).status_code, 403)

    async def test_connectors_with_real_rows_list_and_patch(self):
        from app import mcp_servers
        server = mcp_servers.create({"name": "데모 MCP", "description": "가상 ERP", "category": "erp",
                                     "url": "https://mcp.example.invalid/mcp", "auth": {"type": "none"}, "timeout": 10,
                                     "tools": [{"name": "sales", "title": "매출", "description": "매출 조회", "kind": "read",
                                                "enabled": True, "input_schema": {"type": "object", "properties": {}}},
                                               {"name": "old", "title": "옛", "description": "꺼 둔 도구", "kind": "read",
                                                "enabled": False, "input_schema": {"type": "object", "properties": {}}}]})
        on_id = mcp_servers.tool_connector_id(server["id"], "sales")
        off_id = mcp_servers.tool_connector_id(server["id"], "old")
        listed = (await self.req("GET", "/api/agentic/connectors?acting_user_id=")).json()["connectors"]
        self.assertEqual([(c["id"], c["name"], c["kind"], c["server_name"], c["tool"]) for c in listed],
                         [(on_id, "데모 MCP › 매출", "read", "데모 MCP", "sales")])
        s = await self.make()
        url = f"/api/agentic/sessions/{s['id']}"
        r = await self.req("PATCH", url, {"acting_user_id": "", "connectors": [on_id]})
        self.assertEqual((r.status_code, r.json()["session"]["connectors"]), (200, [on_id]))
        r = await self.req("PATCH", url, {"acting_user_id": "", "connectors": [on_id, off_id]})
        self.assertEqual(r.status_code, 422)                                                         # 꺼진 도구 / a disabled tool
        rows = (await self.req("GET", f"{url}/commands?acting_user_id=")).json()["commands"]
        self.assertIn("연결 1개", next(c["description"] for c in rows if c["name"] == "connectors"))

    async def test_connectors_follow_the_owner_permission_axis(self):
        from app import mcp_servers
        server = mcp_servers.create({"name": "데모 MCP", "description": "가상 ERP", "category": "erp",
                                     "url": "https://mcp.example.invalid/mcp", "auth": {"type": "none"}, "timeout": 10,
                                     "tools": [{"name": "sales", "title": "매출", "description": "매출 조회", "kind": "read",
                                                "enabled": True, "input_schema": {"type": "object", "properties": {}}}]})
        on_id = mcp_servers.tool_connector_id(server["id"], "sales")
        grants: dict = {"7": set()}
        self.stack.enter_context(patch("app.access.allowed_connectors", side_effect=lambda o: grants.get(o)))
        self.assertEqual((await self.req("GET", "/api/agentic/connectors?acting_user_id=7")).json(), {"connectors": []})
        self.assertEqual([c["id"] for c in (await self.req("GET", "/api/agentic/connectors?acting_user_id=")).json()["connectors"]],
                         [on_id])                                                                     # 슈퍼는 전부 / super sees all
        s7 = await self.make(who="7")
        url = f"/api/agentic/sessions/{s7['id']}"
        r = await self.req("PATCH", url, {"acting_user_id": "7", "connectors": [on_id]})
        self.assertEqual(r.status_code, 422)
        self.assertIn("권한이 없는 연결 도구", r.json()["detail"])
        grants["7"] = {on_id}
        r = await self.req("PATCH", url, {"acting_user_id": "7", "connectors": [on_id]})
        self.assertEqual((r.status_code, r.json()["session"]["connectors"]), (200, [on_id]))

    async def test_tasks_list_includes_subagent_rows(self):
        s = await self.make()
        prompt = "README 를 읽고 요약하라"

        def model(messages, system=None, tools=None, tier="main", models=None):
            if "[서브에이전트] 프리셋" in (system or ""):
                return {"calls": [], "text": "README 요약: 데모"}
            if any(m.get("role") == "tool" for m in messages):
                return {"calls": [], "text": "끝"}
            return {"calls": [{"name": "task", "args": {"description": "README 요약", "prompt": prompt, "preset": "explorer"}}],
                    "text": ""}
        with patch("app.llm.generate_calls", side_effect=model):
            await self.post(s["id"], "맡겨")
            await self.idle(s["id"])
        tasks = (await self.req("GET", f"/api/agentic/sessions/{s['id']}/tasks?acting_user_id=")).json()["tasks"]
        self.assertEqual([(t["kind"], t["label"], t["status"]) for t in tasks], [("subagent", "README 요약", "done")])
        t = (await self.req("GET", f"/api/agentic/sessions/{s['id']}/tasks/{tasks[0]['id']}?acting_user_id=")).json()["task"]
        self.assertEqual(t["output"], "README 요약: 데모")

    async def test_new_endpoints_need_the_permission_and_the_owner(self):
        s = await self.make()
        base = f"/api/agentic/sessions/{s['id']}"
        for method, path, body in (("GET", f"{base}/commands?acting_user_id=8", None),
                                   ("POST", f"{base}/seen", {"acting_user_id": "8", "seq": 1}),
                                   ("GET", f"{base}/checkpoints?acting_user_id=8", None),
                                   ("GET", f"{base}/outputs?acting_user_id=8", None),
                                   ("GET", f"{base}/changes?acting_user_id=8", None),
                                   ("POST", f"{base}/commit", {"acting_user_id": "8", "message": "x"})):
            self.assertEqual((await self.req(method, path, body)).status_code, 403, path)
        for method, path, body in (("GET", f"{base}/commands?acting_user_id=7", None),
                                   ("GET", f"{base}/checkpoints?acting_user_id=7", None),
                                   ("POST", f"{base}/checkpoints", {"acting_user_id": "7"}),
                                   ("GET", f"{base}/changes/diff?acting_user_id=7&path=README.md", None),
                                   ("GET", f"{base}/commit/suggest?acting_user_id=7", None),
                                   ("GET", f"{base}/outputs/download?acting_user_id=7&path=README.md", None)):
            self.assertEqual((await self.req(method, path, body)).status_code, 404, path)


# ────────────────────────────────────────────────────────
# 폴더 고르기(2026-10-19): GET /browse · POST /pick-folder · app.agentic_pick
# Folder picking (2026-10-19): GET /browse, POST /pick-folder and app.agentic_pick
# 실제 폴더 선택 창은 띄우지 않는다: 자식 프로세스는 AI365_PICK_FAKE 로만 실제로 돌리고, 그 밖은 subprocess.run 을 바꿔 끼운다.
# No real folder window opens: the child process runs for real only with AI365_PICK_FAKE, otherwise subprocess.run is swapped.
# ────────────────────────────────────────────────────────

def hide(path: str) -> None:
    """숨김 폴더로 만든다(Windows = 숨김 속성) / mark a folder hidden (the hidden attribute on Windows)"""
    import ctypes
    if not ctypes.windll.kernel32.SetFileAttributesW(path, 0x2):
        raise OSError("SetFileAttributesW 실패 / failed")


def done(code: int, out: bytes = b"", err: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=out, stderr=err)


class FolderPickTests(Api2Case):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ))   # 테스트가 바꾼 환경 변수를 되돌린다 / restore env changes
        os.environ.pop("AI365_PICK_FAKE", None)
        os.environ.pop("AI365_PICK_AUTOCLOSE_MS", None)

    async def asyncTearDown(self):
        for g in self.gates:   # 붙잡힌 가짜 창을 먼저 놓는다 / let held fake windows go first
            g.set()
        await self.until(self.unlocked)   # 폴더 선택 창 잠금은 늘 풀려 있어야 한다 / the picker lock must end up free
        await super().asyncTearDown()

    async def unlocked(self):
        return not agentic_api._PICK_LOCK.locked()

    async def browse(self, path: str = "", who: str = ""):
        return await self.req("GET", f"/api/agentic/browse?acting_user_id={who}&path={quote(path)}")

    async def pick(self, who: str = "", **body):
        return await self.req("POST", "/api/agentic/pick-folder", {"acting_user_id": who, **body})

    async def test_settings_advertise_the_folder_picker(self):
        for method, url, body in (("GET", "/api/agentic/settings?acting_user_id=", None),
                                  ("PUT", "/api/agentic/settings", {"acting_user_id": "", "settings": {}})):
            r = await self.req(method, url, body)
            self.assertEqual((r.status_code, r.json()["folder_picker"]), (200, True))

    async def test_browse_top_lists_the_allowed_folders_and_drives_for_the_super_admin_only(self):
        gone = os.path.join(self.root, "gone")
        os.makedirs(gone)
        agentic_store.put_settings({"allowed_folders": [self.root, gone]})
        shutil.rmtree(gone)                                                                      # 사라진 허용 폴더는 뺀다 / a vanished one is left out
        top = (await self.browse()).json()
        self.assertEqual((top["path"], top["parent"], top["roots"], top["entries"], top["truncated"], top["crumbs"]),
                         ("", "", [self.root], [{"name": os.path.basename(self.root), "path": self.root}], False, []))
        self.assertTrue(top["drives"])
        self.assertTrue(all(set(d) == {"name", "path"} and os.path.isabs(d["path"]) for d in top["drives"]))
        if os.name == "nt":
            self.assertTrue(all(re.fullmatch(r"[A-Z]:\\", d["path"]) and d["name"] == d["path"] for d in top["drives"]))
        mine = (await self.browse(who="7")).json()
        self.assertEqual((mine["entries"], "drives" in mine), (top["entries"], False))         # 드라이브는 슈퍼만 / drives for the super only
        self.assertEqual((await self.browse(who="8")).status_code, 403)                          # m_agentic 없음 / no m_agentic

    async def test_browse_lists_subfolders_only_by_name_without_hidden_git_or_node_modules(self):
        for name in ("b_dir", "A_dir", ".git", "node_modules", "숨김", "공유 폴더"):
            os.makedirs(os.path.join(self.proj, name))
        write(os.path.join(self.proj, "file.txt"), "x")
        hidden = os.path.join(self.proj, "숨김")
        if os.name == "nt":
            hide(hidden)
        else:
            os.rename(hidden, os.path.join(self.proj, ".숨김"))
        proj = os.path.realpath(self.proj)
        want = [{"name": n, "path": os.path.join(proj, n)} for n in ("A_dir", "b_dir", "공유 폴더")]
        for who in ("", "7"):
            r = await self.browse(self.proj, who)
            self.assertEqual(r.status_code, 200, r.text)
            d = r.json()
            self.assertEqual((d["path"], d["entries"], d["truncated"], d["allowed"], d["parent"]), (proj, want, False, True, self.root), who)
        crumbs = (await self.browse(self.proj, "7")).json()["crumbs"]                             # 허용 폴더부터 / from the allowed folder
        self.assertEqual(crumbs, [{"name": os.path.basename(self.root), "path": self.root}, {"name": "proj", "path": proj}])
        sup = (await self.browse(self.proj)).json()["crumbs"]                                     # 슈퍼는 드라이브 루트부터 / from the drive root
        anchor = Path(proj).anchor
        self.assertEqual((sup[0]["path"], sup[-1], [c["name"] for c in sup[1:]]),
                         (anchor, {"name": "proj", "path": proj}, list(Path(os.path.relpath(proj, anchor)).parts)))
        # 허용 폴더 맨 위: 슈퍼가 아니면 [위로] = 처음 목록(''), 슈퍼는 상위 폴더 / at an allowed root: '' for others, the parent for the super
        self.assertEqual([(await self.browse(self.root, w)).json()["parent"] for w in ("7", "")], ["", os.path.dirname(self.root)])
        self.assertEqual((await self.browse(anchor)).json()["parent"], "")                       # 드라이브 루트 / a drive root

    async def test_browse_refuses_outside_missing_relative_paths_and_files(self):
        cases = ((self.outside, "7", 403), (os.path.join(self.outside, "nope"), "7", 403),          # 밖이면 있는지 묻지 않고 403 / outside: 403 first
                 (os.path.join(self.root, "nope"), "7", 404), (os.path.join(self.root, "nope"), "", 404),
                 (os.path.join(self.proj, "README.md"), "", 422), (os.path.join(self.proj, "README.md"), "7", 422),
                 ("proj", "", 422), ("../x", "7", 422))
        for path, who, code in cases:
            r = await self.browse(path, who)
            self.assertEqual(r.status_code, code, (path, who, r.text))
        d = (await self.browse(self.outside)).json()                                              # 슈퍼는 어디든 / the super goes anywhere
        self.assertEqual((d["path"], d["allowed"], d["entries"]), (self.outside, False, []))
        link = os.path.join(self.proj, "to_outside")
        try:
            os.symlink(self.outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            link = ""
        if link:   # 링크를 따라 밖으로 나가는 경로도 403 / a link leading outside is 403 too
            self.assertEqual((await self.browse(link, "7")).status_code, 403)

    async def test_browse_caps_the_list_at_500(self):
        many = os.path.join(self.proj, "many")
        for i in range(agentic_api.BROWSE_MAX + 1):
            os.makedirs(os.path.join(many, f"d{i:03d}"))
        d = (await self.browse(many)).json()
        self.assertEqual((len(d["entries"]), d["truncated"], d["entries"][0]["name"], d["entries"][-1]["name"]), (500, True, "d000", "d499"))

    async def test_pick_folder_runs_the_child_and_reports_the_path_a_cancel_or_an_outside_folder(self):
        real_run = subprocess.run
        seen = []

        def spy(cmd, **kw):
            seen.append((list(cmd), kw))
            return real_run(cmd, **kw)
        self.stack.enter_context(patch.object(agentic_api.subprocess, "run", side_effect=spy))
        os.environ["AI365_PICK_FAKE"] = self.proj
        r = await self.pick(start=self.proj, title="  작업 폴더   선택 ")
        self.assertEqual((r.status_code, r.json()), (200, {"path": os.path.realpath(self.proj), "cancelled": False, "allowed": True}))
        cmd, kw = seen[0]
        self.assertEqual((cmd[0], cmd[1:]), (agentic_api._picker_python(), ["-m", "app.agentic_pick", os.path.realpath(self.proj), "작업 폴더 선택"]))
        pyw = os.path.join(str(agentic_api.REPO_ROOT), ".venv", "Scripts", "pythonw.exe")
        self.assertEqual(cmd[0], pyw if os.path.isfile(pyw) else sys.executable)
        self.assertEqual((kw["cwd"], kw["timeout"], kw["creationflags"], kw["capture_output"]),
                         (str(agentic_api.REPO_ROOT), 600, agentic_exec._NO_WINDOW, True))
        self.assertEqual([k for k in kw["env"] if k.startswith("GEMINI_")], [])                  # 비밀 변수 없음 / no secrets
        os.environ["AI365_PICK_FAKE"] = self.outside
        r = await self.pick(start=os.path.join(self.root, "nope"))                                 # 없는 start = 첫 허용 폴더 / missing start = first allowed
        self.assertEqual(r.json(), {"path": self.outside, "cancelled": False, "allowed": False})
        self.assertEqual((seen[1][0][3], seen[1][0][4]), (self.root, "폴더 선택"))               # 기본 제목 / the default title
        os.environ["AI365_PICK_FAKE"] = ""
        self.assertEqual((await self.pick()).json(), {"cancelled": True})
        self.assertEqual(seen[2][0][3], self.root)
        self.assertEqual((await self.pick(who="8")).status_code, 403)
        self.assertEqual(len(seen), 3)

    async def test_pick_folder_is_one_at_a_time(self):
        release, entered = threading.Event(), threading.Event()
        self.gates.append(release)

        def held(cmd, **kw):
            entered.set()
            release.wait(10)
            return done(0, json.dumps({"path": self.proj}).encode())
        self.stack.enter_context(patch.object(agentic_api.subprocess, "run", side_effect=held))
        first = asyncio.ensure_future(self.pick())

        async def opened():
            return entered.is_set()
        await self.until(opened)
        r = await self.pick(who="7")
        self.assertEqual((r.status_code, r.json()), (409, {"detail": "이미 폴더 선택 창이 열려 있습니다"}))
        release.set()
        r = await first
        self.assertEqual((r.status_code, r.json()["path"]), (200, os.path.realpath(self.proj)))
        await self.until(self.unlocked)
        self.assertEqual((await self.pick()).status_code, 200)                                    # 잠금이 풀렸다 / the lock is free again

    async def test_pick_folder_answers_503_when_the_window_cannot_open_and_frees_the_lock(self):
        outcomes = [done(3, b"", "tkinter 를 불러오지 못했습니다".encode()), done(1, b"Traceback"), done(0, b"not json\n"),
                    done(0, b'{"nope": 1}\n'), done(0, b""), subprocess.TimeoutExpired(["x"], 600), OSError("no python")]
        for outcome in outcomes:
            def run(cmd, outcome=outcome, **kw):
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome
            with patch.object(agentic_api.subprocess, "run", side_effect=run):
                r = await self.pick()
            self.assertEqual((r.status_code, r.json()), (503, {"detail": "폴더 선택 창을 띄울 수 없습니다"}), outcome)
            self.assertFalse(agentic_api._PICK_LOCK.locked(), outcome)
        # 원격 요청(AGENTIC_ALLOW_REMOTE)은 창이 서버 화면에 뜨므로 띄우지 않고 503 / remote requests get 503 without a window
        self.stack.enter_context(patch.object(agentic_api.settings, "AGENTIC_ALLOW_REMOTE", True))
        self.stack.enter_context(patch.object(agentic_api.subprocess, "run", side_effect=AssertionError("no window for remote clients")))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, client=("10.1.2.3", 5000)), base_url="http://test") as c:
            r = await c.post("/api/agentic/pick-folder", json={"acting_user_id": ""})
            self.assertEqual((r.status_code, r.json()["detail"]), (503, "폴더 선택 창을 띄울 수 없습니다"))
            self.assertEqual((await c.get("/api/agentic/browse?acting_user_id=")).status_code, 200)   # 탐색기는 된다 / the explorer works

    def test_the_pick_module_prints_one_ascii_json_line(self):
        korean = os.path.join(self.root, "한글 폴더")
        os.makedirs(korean)
        for exe in dict.fromkeys([agentic_api._picker_python(), sys.executable]):
            for fake, want in ((korean, korean), ("", "")):
                env = {**agentic_exec._child_env(), "AI365_PICK_FAKE": fake}
                r = subprocess.run([exe, "-m", "app.agentic_pick", self.root, "제목"], cwd=str(agentic_api.REPO_ROOT),
                                   capture_output=True, timeout=60, env=env, creationflags=agentic_exec._NO_WINDOW)
                self.assertEqual(r.returncode, 0, r.stderr)
                lines = r.stdout.decode("ascii").splitlines()                                     # ASCII 만 / ASCII only
                self.assertEqual((len(lines), json.loads(lines[0])), (1, {"path": want}), exe)
        # tkinter 를 못 부르면 창 없이 종료 코드 3(부모는 503) / without tkinter: exit code 3 and no window (the parent answers 503)
        env = agentic_exec._child_env()
        env.pop("AI365_PICK_FAKE", None)
        code = "import sys; sys.modules['tkinter'] = None; from app import agentic_pick; sys.exit(agentic_pick.main(['', 'x']))"
        r = subprocess.run([sys.executable, "-c", code], cwd=str(agentic_api.REPO_ROOT), capture_output=True, timeout=60, env=env,
                           creationflags=agentic_exec._NO_WINDOW)
        self.assertEqual((r.returncode, r.stdout), (3, b""))
        self.assertIn("tkinter", r.stderr.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
