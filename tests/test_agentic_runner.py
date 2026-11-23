# -*- coding: utf-8 -*-
"""Agentic 모드 실행 루프(2026-10-19): 가짜 모델(호출 순서대로 대본을 돌려준다)로 턴 이벤트 순서 · 승인(Auto 의 차단 명령 ·
묻기 모드) · 예산 · 대기 큐 · 중단 · 오류 · 동시 실행 상한 · 기동 정리를 본다. 실제 LLM · 실 DB · 네트워크 없음.

Agentic mode run loop (2026-10-19): with a fake model replaying a script in call order, checks the turn's event order,
approvals (denied commands in Auto, ask mode), budgets, the message queue, stop, errors, the concurrency cap and the boot
cleanup. No real LLM, real DB or network."""
import asyncio
import json
import os
import shlex
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from google.genai import types

from db_fixture import isolate_db
from app import agentic_exec, agentic_runner as runner, agentic_store, agentic_tools, llm

MODELS = ["gemini-3.7-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"]


def py(code: str) -> str:
    """이 파이썬으로 code 를 돌리는 명령 한 줄(code 안에는 작은따옴표만) / a command running code with this Python"""
    if os.name == "nt":
        return f'"{sys.executable}" -c "{code}"'
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


class FakeModel:
    """호출 순서대로 대본을 돌려주는 가짜 llm.generate_calls. 대본 한 칸 = {"calls": [(이름, 인자) 또는 호출 dict], "text": 글} ·
    함수(블록) · 예외. 호출 dict 는 그대로 돌려준다(thought_signature · id 를 실은 실제 응답 흉내).
    A fake llm.generate_calls replaying a script: a step is {"calls": [(name, args) or a call dict], "text": str}, a
    callable or an exception. Call dicts pass through as they are (like real calls carrying thought_signature and id)."""

    def __init__(self, *script):
        self.script = list(script)
        self.seen: list[dict] = []
        self.lock = threading.Lock()

    def __call__(self, messages, system=None, tools=None, tier="main", models=None):
        with self.lock:
            self.seen.append({"messages": [dict(m) for m in messages], "system": system, "tools": tools, "tier": tier,
                              "models": models})
            step = self.script.pop(0) if self.script else {"text": "끝났습니다."}
        if callable(step):
            step = step()
        if isinstance(step, BaseException):
            raise step
        calls = [dict(c) if isinstance(c, dict) else {"name": c[0], "args": c[1]} for c in step.get("calls", [])]
        return {"calls": calls, "text": step.get("text", "")}


def gate(release: threading.Event, entered: threading.Event, then):
    """모델 호출을 release 까지 붙잡는 대본 칸 / a script step that holds the model call until released"""
    def step():
        entered.set()
        release.wait(10)
        return then
    return step


class RunnerCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        agentic_store.init_agentic()
        self.folder = os.path.realpath(self.stack.enter_context(tempfile.TemporaryDirectory()))
        with open(os.path.join(self.folder, "README.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("# 데모\nThis is teh demo.\n")
        with open(os.path.join(self.folder, "AGENTS.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("RULES-MARKER-42: 테스트 규칙\n")
        agentic_store.put_settings({"allowed_folders": [self.folder], "deny_commands": [r"\bdanger_word\b"]})
        self.sid = agentic_store.create_session("", self.folder)["id"]
        runner.REGISTRY.clear()
        runner.SUBS.clear()
        self.gates: list[threading.Event] = []
        self.stack.enter_context(patch("app.llm.generate_grounded_meta", side_effect=AssertionError("unexpected web")))

    async def asyncTearDown(self):
        for g in self.gates:
            g.set()
        for r in list(runner.REGISTRY.values()):
            if r.alive:
                r.task.cancel()
                await asyncio.wait({r.task}, timeout=5)
        runner.REGISTRY.clear()
        runner.SUBS.clear()
        agentic_exec.kill_session_tasks(self.sid)

    def model(self, *script) -> FakeModel:
        fake = FakeModel(*script)
        self.stack.enter_context(patch("app.llm.generate_calls", side_effect=fake))
        return fake

    def events(self, after: int = 0) -> list[dict]:
        return agentic_store.list_events(self.sid, after, 10000)

    def kinds(self, after: int = 0) -> list[str]:
        return [e["kind"] for e in self.events(after)]

    def states(self, after: int = 0) -> list[str]:
        return [e["payload"]["state"] for e in self.events(after) if e["kind"] == "status"]

    def pending(self) -> list[dict]:
        latest: dict[str, dict] = {}
        for e in self.events():
            if e["kind"] == "approval":
                latest[e["payload"]["approval_id"]] = e["payload"]
        return [p for p in latest.values() if p["decision"] == "pending"]

    def last_seq(self) -> int:
        return agentic_store.get_session(self.sid)["last_seq"]

    async def until(self, pred, timeout: float = 15.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if pred():
                return
            await asyncio.sleep(0.02)
        self.fail(f"시간 안에 조건이 맞지 않았습니다 / condition not met in time: {self.kinds()}")

    async def finish(self, timeout: float = 20.0):
        self.assertTrue(await runner.join(self.sid, timeout), "턴이 끝나지 않았습니다 / the turn did not end")


class TurnTests(RunnerCase):
    async def test_read_edit_then_text_writes_the_contract_event_order(self):
        fake = self.model({"calls": [("read_file", {"path": "README.md"})]},
                          {"calls": [("edit_file", {"path": "README.md", "old_string": "teh", "new_string": "the"})]},
                          {"text": "README 의 오타를 고쳤습니다."})
        self.assertEqual(runner.start_turn(self.sid, "README 오타 고쳐줘"), {"queued": False})
        await self.finish()
        evs = self.events()
        self.assertEqual([e["kind"] for e in evs], ["user", "status", "tool_call", "tool_result", "tool_call", "tool_result",
                                                    "assistant", "summary", "context", "status"])
        self.assertEqual([e["seq"] for e in evs], list(range(1, 11)))
        self.assertEqual(self.states(), ["running", "idle"])
        read_call, read_res, edit_call, edit_res = (evs[i]["payload"] for i in (2, 3, 4, 5))
        self.assertEqual((read_call["tool"], read_call["group"], read_call["label"], read_call["args"]),
                         ("read_file", "read", "README.md 읽기", {"path": "README.md"}))
        self.assertEqual((read_res["call_id"], read_res["ok"], read_res["summary"]), (read_call["call_id"], True, "2줄 읽음"))
        self.assertIn("     2\tThis is teh demo.", read_res["detail"])
        self.assertEqual((edit_call["label"], edit_call["group"], edit_res["call_id"], edit_res["ok"], edit_res["summary"]),
                         ("README.md 편집", "write", edit_call["call_id"], True, "1줄 바뀜"))
        self.assertEqual(edit_res["diff"]["path"], "README.md")
        self.assertIn("-This is teh demo.\n+This is the demo.\n", edit_res["diff"]["unified"])
        with open(os.path.join(self.folder, "README.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "# 데모\nThis is the demo.\n")
        self.assertEqual(evs[6]["payload"], {"text": "README 의 오타를 고쳤습니다."})
        summary = evs[7]["payload"]
        self.assertEqual((summary["steps"], summary["text"].startswith("도구 2회")), (2, True))
        self.assertGreater(summary["tokens_est"], 0)
        self.assertIsInstance(evs[8]["payload"]["pct"], int)
        s = agentic_store.get_session(self.sid)
        self.assertEqual((s["status"], s["steps"], s["last_seq"], s["context_pct"]), ("idle", 2, 10, evs[8]["payload"]["pct"]))
        # 모델 호출: 세션 모델부터의 체인 · 규칙 파일 · 글로 되먹인 결과 / model calls: the chain, the rules file, text feedback
        self.assertEqual(len(fake.seen), 3)
        first = fake.seen[0]
        self.assertEqual((first["models"], first["tier"], first["tools"]), (MODELS, "main", agentic_tools.TOOL_SPECS))
        self.assertIn(self.folder, first["system"])
        self.assertIn("RULES-MARKER-42", first["system"])
        self.assertIn("한국어", first["system"])
        self.assertEqual(first["messages"], [{"role": "user", "content": "README 오타 고쳐줘"}])
        # 되먹임은 함수 호출 · 함수 응답 모양(글 흉내 형식 없음) / feedback is function calls and responses, never imitable text
        second = fake.seen[1]["messages"]
        self.assertEqual([m["role"] for m in second], ["user", "assistant", "tool"])
        self.assertEqual((second[1]["content"], second[1]["calls"]), ("", [{"name": "read_file", "args": {"path": "README.md"}}]))
        result = second[2]["results"][0]
        self.assertEqual((result["name"], result["response"]["ok"], result["response"]["summary"]), ("read_file", True, "2줄 읽음"))
        self.assertIn("     2\tThis is teh demo.", result["response"]["detail"])
        self.assertNotIn("[도구", json.dumps(fake.seen[2]["messages"], ensure_ascii=False))
        self.assertIn("반드시 함수 호출", first["system"])
        # 다음 턴은 지난 턴의 요청 · 마지막 답을 기록으로 받는다 / the next turn gets the last request and answer as history
        fake2 = FakeModel({"text": "네, 고쳤습니다."})
        with patch("app.llm.generate_calls", side_effect=fake2):
            runner.start_turn(self.sid, "다 고쳤어?")
            await self.finish()
        self.assertEqual(fake2.seen[0]["messages"], [{"role": "user", "content": "README 오타 고쳐줘"},
                                                     {"role": "assistant", "content": "README 의 오타를 고쳤습니다."},
                                                     {"role": "user", "content": "다 고쳤어?"}])

    async def test_text_that_comes_with_calls_is_an_interim_assistant_event(self):
        self.model({"calls": [("list_dir", {})], "text": "먼저 폴더를 봅니다."}, {"text": "README.md 와 AGENTS.md 가 있습니다."})
        runner.start_turn(self.sid, "뭐가 있어?")
        await self.finish()
        evs = self.events()
        self.assertEqual([e["kind"] for e in evs], ["user", "status", "assistant", "tool_call", "tool_result", "assistant",
                                                    "summary", "context", "status"])
        self.assertEqual(evs[2]["payload"]["text"], "먼저 폴더를 봅니다.")
        self.assertIn("[파일] README.md", evs[4]["payload"]["detail"])

    async def test_a_model_error_ends_the_turn_with_error_events(self):
        self.model(llm.ModelBusyError())
        runner.start_turn(self.sid, "안녕")
        await self.finish()
        self.assertEqual(self.kinds(), ["user", "status", "error", "status"])
        self.assertEqual(self.states(), ["running", "error"])
        self.assertIn("503", self.events()[2]["payload"]["message"])
        self.assertEqual(agentic_store.get_session(self.sid)["status"], "error")

    async def test_an_unknown_tool_fails_without_killing_the_turn(self):
        fake = self.model({"calls": [("delete_everything", {"path": "."})]}, {"text": "그 도구는 없습니다."})
        runner.start_turn(self.sid, "다 지워")
        await self.finish()
        res = [e["payload"] for e in self.events() if e["kind"] == "tool_result"][0]
        self.assertEqual((res["ok"], res["summary"]), (False, "알 수 없는 도구입니다: delete_everything"))
        result = fake.seen[1]["messages"][-1]["results"][0]
        self.assertEqual((result["name"], result["response"]["ok"]), ("delete_everything", False))
        self.assertEqual(self.states()[-1], "idle")

    async def test_call_ids_and_thought_signatures_go_back_with_one_response_per_call(self):
        # Gemini 3 계열은 현재 턴의 함수 호출에 받은 서명이 그대로 있어야 한다. 9번째 호출도 '실행하지 않음' 응답을 받는다
        # Gemini 3 needs the received signatures on this turn's calls; a ninth call still gets a "not run" response
        first = {"name": "read_file", "args": {"path": "README.md"}, "id": "fc-1", "thought_signature": b"sig-1"}
        rest = [{"name": "list_dir", "args": {}} for _ in range(8)]
        fake = self.model({"calls": [first, *rest], "text": "둘러보겠습니다."}, {"text": "다 봤습니다."})
        runner.start_turn(self.sid, "둘러봐")
        await self.finish()
        model_turn, tool_turn = fake.seen[1]["messages"][1:]
        self.assertEqual((model_turn["role"], model_turn["content"], model_turn["calls"][0]), ("assistant", "둘러보겠습니다.", first))
        self.assertEqual(len(model_turn["calls"]), 9)
        self.assertEqual([r["name"] for r in tool_turn["results"]], ["read_file"] + ["list_dir"] * 8)
        self.assertEqual(tool_turn["results"][0]["id"], "fc-1")
        self.assertEqual([r["response"]["ok"] for r in tool_turn["results"]], [True] * 8 + [False])
        self.assertIn("실행하지 않았습니다", tool_turn["results"][8]["response"]["detail"])
        self.assertEqual(len([e for e in self.events() if e["kind"] == "tool_result"]), 8)   # 실행은 8개까지 / at most 8 run

    async def test_a_call_written_as_text_is_asked_once_to_be_a_real_call(self):
        imitation = "[도구 호출]\nedit_file(path=README.md, old_string=teh, new_string=the)\nbash(command=node test.js)"
        fake = self.model({"text": imitation},
                          {"calls": [("edit_file", {"path": "README.md", "old_string": "teh", "new_string": "the"})]},
                          {"text": "고쳤습니다."})
        runner.start_turn(self.sid, "오타 고쳐줘")
        await self.finish()
        self.assertEqual(len(fake.seen), 3)
        nudge = fake.seen[1]["messages"]
        self.assertEqual([m["role"] for m in nudge], ["user", "assistant", "user"])
        self.assertEqual((nudge[1]["content"], nudge[2]["content"]), (imitation, runner.NUDGE))
        evs = self.events()
        self.assertEqual([e["kind"] for e in evs], ["user", "status", "tool_call", "tool_result", "assistant", "summary",
                                                    "context", "status"])   # 흉내 낸 글은 답으로 쓰지 않는다 / the imitation is not shown
        self.assertEqual(evs[4]["payload"]["text"], "고쳤습니다.")
        with open(os.path.join(self.folder, "README.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "# 데모\nThis is the demo.\n")

    async def test_a_second_text_imitation_ends_the_turn_with_that_text(self):
        fake = self.model({"text": "read_file(path=README.md)"}, {"text": "default_api.read_file(path='README.md')"})
        runner.start_turn(self.sid, "읽어 줘")
        await self.finish()
        self.assertEqual(len(fake.seen), 2)                                          # 다시 묻기는 1번만 / only one retry
        self.assertEqual([e["payload"]["text"] for e in self.events() if e["kind"] == "assistant"],
                         ["default_api.read_file(path='README.md')"])
        self.assertEqual(self.states()[-1], "idle")

    async def test_an_ordinary_answer_is_not_mistaken_for_an_imitation(self):
        fake = self.model({"text": "README.md 를 읽고 read_file 도구로 확인했습니다. 고칠 곳은 없습니다."})
        runner.start_turn(self.sid, "확인해 줘")
        await self.finish()
        self.assertEqual(len(fake.seen), 1)


class ApprovalTests(RunnerCase):
    async def test_a_denied_command_waits_and_allow_deny_always_are_each_honoured(self):
        cmd = py("print('danger_word')")
        outcomes = {}
        for decision in ("allow", "deny", "always"):
            fake = FakeModel({"calls": [("bash", {"command": cmd})]}, {"text": f"{decision} 끝"})
            with patch("app.llm.generate_calls", side_effect=fake):
                before = self.last_seq()
                runner.start_turn(self.sid, f"{decision} 해 봐")
                await self.until(lambda: self.pending())
                ap = self.pending()[0]
                self.assertEqual((ap["reason"], ap["tool"], ap["call_id"] != "", ap["decided_at"]), ("deny_cmd", "bash", True, ""))
                self.assertEqual(agentic_store.get_session(self.sid)["status"], "waiting")
                runner.decide(self.sid, ap["approval_id"], decision)
                with self.assertRaises(runner.NotPending):
                    runner.decide(self.sid, ap["approval_id"], "allow")             # 두 번째 결정은 409 감 / a second decision is refused
                await self.finish()
            evs = self.events(before)
            outcomes[decision] = (evs, fake)
            self.assertEqual([e["kind"] for e in evs], ["user", "status", "tool_call", "approval", "status", "approval", "status",
                                                        "tool_result", "assistant", "summary", "context", "status"])
            self.assertEqual([e["payload"]["state"] for e in evs if e["kind"] == "status"], ["running", "waiting", "running", "idle"])
            decided = evs[5]["payload"]
            self.assertEqual((decided["approval_id"], decided["decision"], bool(decided["decided_at"])), (ap["approval_id"], decision, True))
        allow_res = outcomes["allow"][0][7]["payload"]
        self.assertEqual((allow_res["ok"], allow_res["exit_code"]), (True, 0))
        self.assertIn("danger_word", allow_res["output"])
        allowed = outcomes["allow"][1].seen[1]["messages"][-1]["results"][0]
        self.assertEqual((allowed["name"], allowed["response"]["ok"], allowed["response"]["exit_code"]), ("bash", True, 0))
        self.assertIn("danger_word", allowed["response"]["detail"])
        deny_res = outcomes["deny"][0][7]["payload"]
        self.assertEqual((deny_res["ok"], deny_res["summary"], "output" in deny_res), (False, "사용자가 거부했습니다", False))
        self.assertEqual(outcomes["deny"][1].seen[1]["messages"][-1]["results"][0]["response"],
                         {"ok": False, "summary": "사용자가 거부했습니다", "detail": "사용자가 거부했습니다"})
        self.assertTrue(outcomes["always"][0][7]["payload"]["ok"], outcomes["always"][0][7]["payload"])
        # python 규칙은 프로그램만(2026-10-19) / a python rule keeps the program alone (2026-10-19)
        self.assertEqual(agentic_store.get_session(self.sid)["rules"], [{"tool": "bash", "prefix": sys.executable}])
        # 항상 허용 규칙도 차단 명령은 다시 묻는다(규칙은 ask_mode 만 건너뛴다) / rules never skip deny_cmd
        self.model({"calls": [("bash", {"command": cmd})]}, {"text": "끝"})
        runner.start_turn(self.sid, "한 번 더")
        await self.until(lambda: self.pending())
        self.assertEqual(self.pending()[0]["reason"], "deny_cmd")
        runner.decide(self.sid, self.pending()[0]["approval_id"], "deny")
        await self.finish()

    async def test_ask_mode_asks_before_edits_but_reads_run_and_always_remembers_the_tool(self):
        agentic_store.update_session(self.sid, perm_mode="ask")
        self.model({"calls": [("read_file", {"path": "README.md"}),
                              ("edit_file", {"path": "README.md", "old_string": "teh", "new_string": "the"})]},
                   {"text": "고쳤습니다."},
                   {"calls": [("edit_file", {"path": "README.md", "old_string": "demo", "new_string": "sample"})]},
                   {"text": "또 고쳤습니다."})
        runner.start_turn(self.sid, "오타 고쳐줘")
        await self.until(lambda: self.pending())
        ap = self.pending()[0]
        self.assertEqual((ap["reason"], ap["tool"], ap["label"]), ("ask_mode", "edit_file", "README.md 편집"))
        results = [e["payload"] for e in self.events() if e["kind"] == "tool_result"]
        self.assertEqual([r["tool"] for r in results], ["read_file"])                 # 읽기는 묻지 않았다 / the read did not ask
        runner.decide(self.sid, ap["approval_id"], "always")
        await self.finish()
        self.assertEqual(agentic_store.get_session(self.sid)["rules"], [{"tool": "edit_file"}])
        before = self.last_seq()
        runner.start_turn(self.sid, "demo 를 sample 로")
        await self.finish()
        self.assertNotIn("approval", self.kinds(before))                             # 규칙이 ask_mode 를 건너뛴다 / the rule skips ask_mode
        with open(os.path.join(self.folder, "README.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "# 데모\nThis is the sample.\n")

    async def test_a_path_outside_the_allowed_folders_asks_even_in_auto(self):
        with tempfile.TemporaryDirectory() as other:
            secret = os.path.join(other, "secret.txt")
            with open(secret, "w", encoding="utf-8") as f:
                f.write("밖의 파일\n")
            fake = self.model({"calls": [("read_file", {"path": secret})]}, {"text": "읽었습니다."})
            runner.start_turn(self.sid, "밖 파일 읽어")
            await self.until(lambda: self.pending())
            ap = self.pending()[0]
            self.assertEqual((ap["reason"], ap["tool"]), ("outside", "read_file"))
            runner.decide(self.sid, ap["approval_id"], "allow")
            await self.finish()
            res = [e["payload"] for e in self.events() if e["kind"] == "tool_result"][0]
            self.assertTrue(res["ok"])
            self.assertIn("밖의 파일", fake.seen[1]["messages"][-1]["results"][0]["response"]["detail"])

    async def test_auto_mode_asks_for_unsafe_commands_and_always_remembers_the_subcommand(self):
        unsafe = py("print('made')")                                                  # python -c = 안전 목록 밖 / off the safe list
        self.model({"calls": [("bash", {"command": unsafe})]}, {"text": "끝"},
                   {"calls": [("bash", {"command": py("print('again')")})]}, {"text": "끝"})
        runner.start_turn(self.sid, "만들어 봐")
        await self.until(lambda: self.pending())
        ap = self.pending()[0]
        self.assertEqual((ap["reason"], ap["tool"]), ("auto_cmd", "bash"))
        runner.decide(self.sid, ap["approval_id"], "always")
        await self.finish()
        # python 규칙은 프로그램만(2026-10-19) / a python rule keeps the program alone (2026-10-19)
        self.assertEqual(agentic_store.get_session(self.sid)["rules"], [{"tool": "bash", "prefix": sys.executable}])
        before = self.last_seq()
        runner.start_turn(self.sid, "한 번 더")                                       # 같은 프로그램이라 묻지 않는다 / same program: no ask
        await self.finish()
        self.assertNotIn("approval", self.kinds(before))
        self.assertIn("again", [e["payload"] for e in self.events(before) if e["kind"] == "tool_result"][0]["output"])

    async def test_the_time_budget_is_cumulative_over_turns_and_continue_resets_it(self):
        agentic_store.put_settings({"budgets": {"max_minutes": 1}})
        clock = {"t": 1000.0}
        self.stack.enter_context(patch.object(runner, "_clock", lambda: clock["t"]))

        def after(seconds, step):   # 모델이 생각하는 동안 시간이 흐른다 / time passes while the model thinks
            def run_step():
                clock["t"] += seconds
                return step
            return run_step
        self.model(after(40, {"calls": [("read_file", {"path": "README.md"})]}), {"text": "첫 턴 끝"},
                   after(40, {"calls": [("list_dir", {})]}), {"text": "둘째 턴 끝"})
        runner.start_turn(self.sid, "A")
        await self.finish()
        self.assertNotIn("approval", self.kinds())                                    # 40초 < 60초 / under the minute
        self.assertAlmostEqual(runner.REGISTRY[self.sid].spent_sec, 40.0)
        first_runner = runner.REGISTRY[self.sid]
        runner.start_turn(self.sid, "B")                                              # 누적 40 + 이번 40 = 80초 / 40 carried + 40 now
        self.assertIsNot(runner.REGISTRY[self.sid], first_runner)
        await self.until(lambda: self.pending())
        ap = self.pending()[0]
        self.assertEqual((ap["reason"], ap["tool"], ap["args"]["minutes"], ap["args"]["max_minutes"]), ("budget", "continue", 1, 1))
        clock["t"] += 3600                                                            # 승인 대기는 일한 시간이 아니다 / waiting is not work
        runner.decide(self.sid, ap["approval_id"], "allow")
        await self.finish()
        self.assertEqual(self.states()[-1], "idle")
        self.assertAlmostEqual(runner.REGISTRY[self.sid].spent_sec, 0.0)              # [계속]이 0 으로 / continue reset it

    async def test_the_budget_asks_to_continue_and_allow_resets_while_deny_stops(self):
        agentic_store.put_settings({"budgets": {"max_steps": 1}})
        self.model({"calls": [("read_file", {"path": "README.md"})]}, {"calls": [("list_dir", {})]}, {"text": "다 봤습니다."})
        runner.start_turn(self.sid, "둘러봐")
        await self.until(lambda: self.pending())
        ap = self.pending()[0]
        self.assertEqual((ap["reason"], ap["tool"], ap["call_id"], ap["args"]["steps"], ap["args"]["max_steps"]),
                         ("budget", "continue", "", 1, 1))
        self.assertEqual(agentic_store.get_session(self.sid)["status"], "waiting")
        self.assertEqual([e["payload"]["tool"] for e in self.events() if e["kind"] == "tool_result"], ["read_file"])
        runner.decide(self.sid, ap["approval_id"], "allow")
        await self.finish()
        self.assertEqual(self.kinds()[-10:], ["approval", "status", "approval", "status", "tool_call", "tool_result",
                                              "assistant", "summary", "context", "status"])
        self.assertEqual(agentic_store.get_session(self.sid)["steps"], 1)            # 0 으로 돌린 뒤 +1 / reset to 0, then +1
        # 거부하면 그 자리에서 멈춘다 / deny stops right there
        before = self.last_seq()
        self.model({"calls": [("read_file", {"path": "README.md"})]})
        runner.start_turn(self.sid, "또 둘러봐")
        await self.until(lambda: self.pending())
        runner.decide(self.sid, self.pending()[0]["approval_id"], "deny")
        await self.finish()
        self.assertEqual(self.kinds(before), ["user", "status", "approval", "status", "approval", "status"])
        self.assertEqual(self.states(before), ["running", "waiting", "stopped"])
        self.assertEqual(agentic_store.get_session(self.sid)["status"], "stopped")


class QueueStopTests(RunnerCase):
    async def test_a_message_sent_while_running_is_queued_and_starts_the_next_turn(self):
        release, entered = threading.Event(), threading.Event()
        self.gates.append(release)
        fake = self.model(gate(release, entered, {"text": "첫 답"}), {"text": "둘째 답"})
        self.assertEqual(runner.start_turn(self.sid, "A"), {"queued": False})
        await self.until(entered.is_set)
        # 2차: 기본 mode(auto)는 스티어링이라 대기 큐는 mode="queue" 로 연다 / phase 2: the default mode steers, so the queue needs mode="queue"
        self.assertEqual(runner.start_turn(self.sid, "B", mode="queue"), {"queued": True})
        self.assertEqual([e["payload"]["text"] for e in self.events() if e["kind"] == "user"], ["A"])   # 큐의 글은 아직 이벤트가 아니다 / not yet an event
        release.set()
        await self.finish()
        self.assertEqual(self.kinds(), ["user", "status", "assistant", "summary", "context", "status"] * 2)
        self.assertEqual([e["payload"]["text"] for e in self.events() if e["kind"] == "user"], ["A", "B"])
        self.assertEqual(self.states(), ["running", "idle", "running", "idle"])
        self.assertEqual(fake.seen[1]["messages"], [{"role": "user", "content": "A"}, {"role": "assistant", "content": "첫 답"},
                                                    {"role": "user", "content": "B"}])

    async def test_stop_during_a_model_call_ends_as_stopped_and_drops_the_late_answer(self):
        release, entered = threading.Event(), threading.Event()
        self.gates.append(release)
        self.model(gate(release, entered, {"calls": [("read_file", {"path": "README.md"})]}))
        runner.start_turn(self.sid, "읽어 줘")
        await self.until(entered.is_set)
        runner.start_turn(self.sid, "그다음 이것도")                                   # 중단하면 큐도 비운다 / stop clears the queue
        self.assertTrue(await runner.stop(self.sid))
        self.assertFalse(runner.is_running(self.sid))
        self.assertEqual(self.kinds(), ["user", "status", "status"])
        self.assertEqual(self.states(), ["running", "stopped"])
        self.assertEqual(agentic_store.get_session(self.sid)["status"], "stopped")
        release.set()
        await asyncio.sleep(0.3)
        self.assertEqual(self.kinds(), ["user", "status", "status"])                 # 늦게 온 답은 버린다 / the late answer is dropped
        self.assertFalse(await runner.stop(self.sid))

    async def test_stop_during_an_approval_closes_it_and_the_pending_call(self):
        self.model({"calls": [("bash", {"command": py("print('danger_word')")})]})
        runner.start_turn(self.sid, "해 봐")
        await self.until(lambda: self.pending())
        aid = self.pending()[0]["approval_id"]
        self.assertTrue(await runner.stop(self.sid))
        evs = self.events()
        self.assertEqual([e["kind"] for e in evs][-3:], ["approval", "tool_result", "status"])
        self.assertEqual((evs[-3]["payload"]["approval_id"], evs[-3]["payload"]["decision"]), (aid, "deny"))
        self.assertEqual((evs[-2]["payload"]["ok"], evs[-2]["payload"]["summary"]), (False, "중단되었습니다"))
        self.assertEqual(evs[-1]["payload"]["state"], "stopped")
        with self.assertRaises(runner.NotPending):
            runner.decide(self.sid, aid, "allow")

    async def test_stop_kills_a_running_command(self):
        # 상대 경로 스크립트는 안전 명령이라 승인 없이 바로 돈다 / a relative script is a safe command, so it runs at once
        with open(os.path.join(self.folder, "slow.py"), "w", encoding="utf-8") as f:
            f.write("import time\ntime.sleep(30)\n")
        cmd = f'"{sys.executable}" slow.py' if os.name == "nt" else f"{shlex.quote(sys.executable)} slow.py"
        self.assertIsNone(agentic_tools.classify(agentic_store.get_session(self.sid), "bash", {"command": cmd},
                                                 agentic_store.get_settings()))
        self.model({"calls": [("bash", {"command": cmd})]})
        runner.start_turn(self.sid, "오래 걸리는 명령")
        await self.until(lambda: "tool_call" in self.kinds())
        await asyncio.sleep(0.5)
        t0 = time.monotonic()
        self.assertTrue(await runner.stop(self.sid))
        self.assertLess(time.monotonic() - t0, 10)
        res = [e["payload"] for e in self.events() if e["kind"] == "tool_result"]
        self.assertEqual([(r["ok"], r["summary"]) for r in res], [(False, "중단되었습니다")])
        self.assertEqual(self.states()[-1], "stopped")

    async def test_the_concurrency_cap_refuses_a_new_running_session(self):
        agentic_store.put_settings({"budgets": {"max_sessions": 1}})
        other = agentic_store.create_session("", self.folder)["id"]
        release, entered = threading.Event(), threading.Event()
        self.gates.append(release)
        self.model(gate(release, entered, {"text": "끝"}), {"text": "끝"})
        runner.start_turn(self.sid, "A")
        await self.until(entered.is_set)
        with self.assertRaises(runner.TooManySessions):
            runner.start_turn(other, "B")
        self.assertEqual(agentic_store.list_events(other), [])
        release.set()
        await self.finish()
        self.assertEqual(runner.start_turn(other, "B"), {"queued": False})          # 끝나면 다시 된다 / free again afterwards
        self.assertTrue(await runner.join(other, 20))


class ContentsTests(unittest.TestCase):
    """llm._to_contents 의 세 모양 · generate_calls 의 호출 파싱(서명 · id). 네트워크 · 키 없음.
    The three message shapes of llm._to_contents and call parsing in generate_calls (signatures, ids); no network or keys."""

    def test_text_messages_keep_their_old_shape(self):
        self.assertEqual([(c.role, [p.text for p in c.parts]) for c in llm._to_contents("안녕")], [("user", ["안녕"])])
        got = llm._to_contents([{"role": "user", "content": "질문"}, {"role": "assistant", "content": "답"}])
        self.assertEqual([(c.role, c.parts[0].text, len(c.parts)) for c in got], [("user", "질문", 1), ("model", "답", 1)])

    def test_a_model_turn_becomes_text_then_function_call_parts_with_signatures(self):
        first, second = llm._to_contents([
            {"role": "assistant", "content": "먼저 읽겠습니다.",
             "calls": [{"name": "read_file", "args": {"path": "README.md"}, "id": "fc-1", "thought_signature": b"sig-1"},
                       {"name": "list_dir", "args": {}}]},
            {"role": "assistant", "content": "", "calls": [{"name": "glob", "args": {"pattern": "*.md"}}]}])
        self.assertEqual((first.role, first.parts[0].text), ("model", "먼저 읽겠습니다."))
        fc = first.parts[1].function_call
        self.assertEqual((fc.name, fc.args, fc.id, first.parts[1].thought_signature), ("read_file", {"path": "README.md"}, "fc-1", b"sig-1"))
        self.assertEqual((first.parts[2].function_call.name, first.parts[2].function_call.args, first.parts[2].thought_signature),
                         ("list_dir", {}, None))
        self.assertEqual([(p.text, p.function_call.name) for p in second.parts], [(None, "glob")])   # 글이 없으면 글 파트 없음 / no text part

    def test_function_responses_become_one_user_turn_in_call_order(self):
        (turn,) = llm._to_contents([{"role": "tool", "results": [
            {"name": "read_file", "response": {"ok": True, "detail": "본문"}, "id": "fc-1"},
            {"name": "list_dir", "response": {"ok": False, "detail": "없음"}}]}])
        self.assertEqual(turn.role, "user")
        self.assertEqual([(p.function_response.name, p.function_response.response, p.function_response.id, p.text) for p in turn.parts],
                         [("read_file", {"ok": True, "detail": "본문"}, "fc-1", None), ("list_dir", {"ok": False, "detail": "없음"}, None, None)])

    def test_generate_calls_returns_text_and_calls_with_their_signatures_and_ids(self):
        resp = types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=[
            types.Part.from_text(text="먼저 읽겠습니다."),
            types.Part(function_call=types.FunctionCall(name="read_file", args={"path": "README.md"}, id="fc-1"), thought_signature=b"sig-1"),
            types.Part.from_function_call(name="list_dir", args={})]))])
        client = llm.GeminiClient.__new__(llm.GeminiClient)   # 키 없이 만든다 / built without keys
        seen = {}

        def rotate(fn, tier="main", kind="gen", models=None):
            seen.update(tier=tier, models=models)
            return resp
        client._with_rotation = rotate
        out = client.generate_calls([{"role": "user", "content": "읽어"}], system="s", tools=agentic_tools.TOOL_SPECS,
                                    models=["gemini-3.7-flash", "gemini-3.5-flash-lite"])
        self.assertEqual(out, {"calls": [{"name": "read_file", "args": {"path": "README.md"}, "id": "fc-1", "thought_signature": b"sig-1"},
                                         {"name": "list_dir", "args": {}}], "text": "먼저 읽겠습니다."})
        self.assertEqual(seen, {"tier": "main", "models": ["gemini-3.7-flash", "gemini-3.5-flash-lite"]})
        # 받은 호출이 그대로 다음 라운드의 모델 턴이 된다(서명 자리 유지) / the calls round-trip into the next model turn, signatures in place
        (turn,) = llm._to_contents([{"role": "assistant", "content": out["text"], "calls": out["calls"]}])
        self.assertEqual([(p.text is not None, p.thought_signature) for p in turn.parts], [(True, None), (False, b"sig-1"), (False, None)])


class RuleScopeTests(RunnerCase):
    """'이 세션에서 항상 허용' 범위(2026-10-19): python · node 는 프로그램만, git 등은 둘째 낱말까지, 규칙이 건너뛸 수 있는 승인만
    payload.rule 을 싣는다.
    The always-allow scope (2026-10-19): python and node keep the program alone, git and friends keep the subcommand, and only
    approvals a rule can skip carry payload.rule."""

    def test_rule_for_keeps_python_and_node_to_the_program_and_git_npm_pip_to_the_subcommand(self):
        rule = lambda cmd: agentic_tools.rule_for("bash", {"command": cmd})["prefix"]   # noqa: E731
        self.assertEqual([rule(c) for c in ("python --version", 'python -c "print(1)"', "python -m pytest -q", "python3 -m http.server",
                                            "py -3 x.py", "node --test", "node app.js", r"C:\tools\node.exe app.js")],
                         ["python", "python", "python", "python3", "py", "node", "node", r"C:\tools\node.exe"])
        self.assertEqual([rule(c) for c in ("git commit -m x", "npm run build", "npx tsc --noEmit", "pnpm install", "yarn add x", "pip install x",
                                            "pip3 list", "docker compose up", "uv run x.py", "powershell -Command Get-Date", "pwsh -File x.ps1",
                                            "cmd /c dir", "git")],
                         ["git commit", "npm run", "npx tsc", "pnpm install", "yarn add", "pip install", "pip3 list", "docker compose", "uv run",
                          "powershell -Command", "pwsh -File", "cmd /c", "git"])
        python = [agentic_tools.rule_for("bash", {"command": "python --version"})]
        covers = lambda cmd, rules=python: agentic_tools.rule_matches(rules, "bash", {"command": cmd})   # noqa: E731
        self.assertEqual([covers(c) for c in ("python --version", 'python -c "import sys"', "python -m pytest -q", "python x.py")], [True] * 4)
        self.assertEqual([covers(c) for c in ("python3 x.py", "pythonx", "py x.py", "pip install x")], [False] * 4)
        commit = [agentic_tools.rule_for("bash", {"command": "git commit -m first"})]
        self.assertEqual((covers("git commit -am again", commit), covers("git push origin main", commit)), (True, False))

    def test_a_program_rule_never_passes_a_denied_command(self):
        st = agentic_store.get_settings()
        s = {**agentic_store.get_session(self.sid), "rules": [{"tool": "bash", "prefix": sys.executable}]}
        self.assertIsNone(agentic_tools.classify(s, "bash", {"command": py("print(1)")}, st))
        self.assertEqual(agentic_tools.classify(s, "bash", {"command": py("print('danger_word')")}, st), "deny_cmd")

    async def test_an_auto_cmd_approval_carries_the_program_rule_and_always_covers_version_c_and_m(self):
        exe = f'"{sys.executable}"' if os.name == "nt" else shlex.quote(sys.executable)
        self.model({"calls": [("bash", {"command": py("print('first')")})]}, {"text": "끝"},
                   {"calls": [("bash", {"command": f"{exe} --version"}), ("bash", {"command": f"{exe} -m platform"}),
                              ("bash", {"command": py("print('again')")})]}, {"text": "또 끝"})
        runner.start_turn(self.sid, "돌려 봐")
        await self.until(lambda: self.pending())
        ap = self.pending()[0]
        self.assertEqual((ap["reason"], ap["rule"]), ("auto_cmd", {"tool": "bash", "prefix": sys.executable}))
        runner.decide(self.sid, ap["approval_id"], "always")
        await self.finish()
        before = self.last_seq()
        runner.start_turn(self.sid, "세 가지 더")   # --version · -m · -c 모두 한 규칙으로 / one rule covers --version, -m and -c
        await self.finish()
        self.assertNotIn("approval", self.kinds(before))
        res = [e["payload"] for e in self.events(before) if e["kind"] == "tool_result"]
        self.assertEqual([(r["ok"], r["exit_code"]) for r in res], [(True, 0)] * 3)
        self.assertIn("Python", res[0]["output"])
        self.assertIn("again", res[2]["output"])
        self.assertEqual(agentic_store.get_session(self.sid)["rules"], [{"tool": "bash", "prefix": sys.executable}])

    async def test_the_rule_rides_on_ask_mode_approvals_but_not_on_denied_or_outside_ones(self):
        agentic_store.update_session(self.sid, perm_mode="ask")
        self.model({"calls": [("edit_file", {"path": "README.md", "old_string": "teh", "new_string": "the"})]}, {"text": "끝"})
        runner.start_turn(self.sid, "고쳐")
        await self.until(lambda: self.pending())
        ap = self.pending()[0]
        self.assertEqual((ap["reason"], ap["rule"]), ("ask_mode", {"tool": "edit_file"}))
        runner.decide(self.sid, ap["approval_id"], "deny")
        await self.finish()
        agentic_store.update_session(self.sid, perm_mode="auto")
        with tempfile.TemporaryDirectory() as other:
            self.model({"calls": [("bash", {"command": py("print('danger_word')")})]}, {"text": "끝"},
                       {"calls": [("read_file", {"path": os.path.join(other, "x.txt")})]}, {"text": "끝"})
            for text, reason in (("차단 명령", "deny_cmd"), ("밖 파일", "outside")):
                runner.start_turn(self.sid, text)
                await self.until(lambda: self.pending())
                ap = self.pending()[0]
                self.assertEqual((ap["reason"], "rule" in ap), (reason, False))
                runner.decide(self.sid, ap["approval_id"], "deny")
                await self.finish()


class BootCleanupTests(RunnerCase):
    async def test_boot_cleanup_stops_running_and_waiting_sessions_and_closes_pending_approvals(self):
        running = agentic_store.create_session("", self.folder)["id"]
        waiting = agentic_store.create_session("", self.folder)["id"]
        agentic_store.update_session(running, status="running")
        agentic_store.update_session(waiting, status="waiting")
        agentic_store.append_event(waiting, "approval", {"approval_id": "a1", "call_id": "c1", "tool": "bash", "args": {},
                                                         "label": "x 실행", "reason": "deny_cmd", "decision": "pending",
                                                         "decided_at": ""})
        task = agentic_store.create_task(running, "bash", "npm run dev")
        stamp = agentic_store.get_session(running)["updated"]
        agentic_store.init_agentic()
        for sid in (running, waiting):
            s = agentic_store.get_session(sid)
            last = agentic_store.list_events(sid)[-1]
            self.assertEqual((s["status"], last["kind"], last["payload"]), ("stopped", "status",
                             {"state": "stopped", "note": agentic_store.RESTART_NOTE}))
        self.assertEqual(agentic_store.get_session(running)["updated"], stamp)       # 정리는 활동이 아니다 / cleanup is not activity
        approvals = [e["payload"] for e in agentic_store.list_events(waiting) if e["kind"] == "approval"]
        self.assertEqual([(a["approval_id"], a["decision"]) for a in approvals], [("a1", "pending"), ("a1", "deny")])
        self.assertTrue(approvals[-1]["decided_at"])
        row = agentic_store.get_task(task["id"])
        self.assertEqual((row["status"], bool(row["ended"])), ("stopped", True))
        self.assertEqual((agentic_store.get_session(self.sid)["status"], agentic_store.list_events(self.sid)), ("idle", []))


if __name__ == "__main__":
    unittest.main()
