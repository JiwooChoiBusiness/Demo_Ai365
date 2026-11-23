"""선택한 업무 하위 범위와 질문 카드 재개 계약. 격리 DB, 실제 모델·네트워크 사용 없음."""
import asyncio
import copy
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from db_fixture import isolate_db
from app import capability_catalog, conversation_execution, db, execution_store, pipeline


def decision(worker="email", clarify=None):
    return {"version": 3, "query": "고객 자료 조회", "steps": [
        {"id": "read", "agent": "work", "worker": worker, "task": "고객 자료 조회", "depends_on": [], "inputs": {}}],
        "send_query": "", "clarify": clarify, "document": None, "use_previous": False, "web": False}


def question():
    return {"question": "어느 기간을 조회할까요?", "options": ["이번 달"],
            "slots": [{"key": "period", "target": "task", "task_id": "read"}]}


async def collect(stream):
    return [event async for event in stream]


class WorkerScopeTests(unittest.TestCase):
    def ids(self, scope=None, eff=None):
        return {row["id"] for row in capability_catalog.build(
            allowed_agents=["work", "groupware"], scope_files=scope, eff=eff)}

    def test_explicit_email_scope_keeps_groupware_and_excludes_education(self):
        selected = self.ids({"workers": ["email"]})
        self.assertIn("agent:work:email", selected)
        self.assertNotIn("agent:work:edu", selected)
        self.assertIn("agent:groupware", selected)
        self.assertIn("delivery:groupware", selected)

    def test_absent_scope_preserves_both_existing_workers(self):
        self.assertTrue({"agent:work:email", "agent:work:edu"} <= self.ids())
        self.assertNotIn("workers", pipeline._clean_scope_files({"work": True}))

    def test_normalization_deduplicates_without_widening_invalid_input(self):
        self.assertEqual(pipeline._clean_scope_files({"workers": ["email", "email", "edu", {}, "unknown"]})["workers"],
                         ["email", "edu"])
        for values in ([], ["unknown", {}], "email", None, True):
            with self.subTest(values=values):
                scope = pipeline._clean_scope_files({"workers": values})
                self.assertEqual(scope["workers"], [])
                self.assertFalse(any(key.startswith("agent:work:") for key in self.ids(scope)))
                self.assertFalse(any(key.startswith("agent:work:") for key in self.ids({"workers": values})))

    def test_selection_does_not_grant_worker_permission(self):
        granted = {"nodes": {"agent_email": 0, "agent_edu": 1}}
        selected = self.ids({"workers": ["email"]}, granted)
        self.assertFalse(any(key.startswith("agent:work:") for key in selected))
        self.assertIn("agent:groupware", selected)


class ResumeSelectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        self.chat = db.create_chat("선택 및 재개", "사내")
        self.stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")))
        self.stack.enter_context(patch("app.llm.stream", side_effect=AssertionError("unexpected LLM stream")))
        self.stack.enter_context(patch("app.llm.generate_calls", side_effect=AssertionError("unexpected tool model")))
        self.stack.enter_context(patch("app.flow_api_call.call", side_effect=AssertionError("unexpected HTTP")))
        self.current_eff = self.stack.enter_context(patch.object(pipeline, "_resolve_eff", return_value=None))
        self.stack.enter_context(patch.object(pipeline, "_await_send_state", return_value=None))
        self.judge = self.stack.enter_context(patch.object(pipeline, "_judge_intent", return_value=decision("edu")))
        self.driven = []

        async def drive(run, chat, connectors, eff):
            self.driven.append(copy.deepcopy(run))
            execution_store.save(run, "completed")
            yield {"type": "done", "message_id": "test"}

        self.stack.enter_context(patch.object(conversation_execution, "drive", drive))

    def pending(self, *, actor="", eff=None, lane="chat", state="needs_input"):
        d = decision(clarify=question())
        run = conversation_execution.create(self.chat, d, "고객 자료 조회", [{"role": "user", "content": "고객 자료 조회"}],
            "사내", eff, pipeline._clean_scope_files({"work": True, "workers": ["email"]}), actor, "")
        run["snapshot"].update(allowed_agents=["work", "groupware"], lane=lane)
        execution_store.save(run, state)
        return run

    def run_count(self):
        conn = db._conn()
        try:
            return conn.execute("SELECT COUNT(*) FROM execution_runs").fetchone()[0]
        finally:
            conn.close()

    async def test_explicit_card_uses_snapshot_after_composer_scope_reset(self):
        saved = self.pending()
        events = await collect(pipeline.run_pipeline(self.chat, "이번 달", "외부", agents=[], scope_files={}, resume_id=saved["id"]))
        self.assertEqual(events[-1]["type"], "done")
        self.judge.assert_not_called()
        self.assertEqual(self.run_count(), 1)
        snap = self.driven[0]["snapshot"]
        self.assertEqual(snap["allowed_agents"], ["work", "groupware"])
        self.assertEqual(snap["scope"], "사내")
        self.assertEqual(snap["scope_files"]["workers"], ["email"])
        self.assertIn("이번 달", snap["decision"]["steps"][0]["task"])

    async def test_unrelated_implicit_request_uses_current_selection(self):
        saved = self.pending()
        # 모델은 기존 질문의 답이 아닌 새 요청으로 분류한다. 실제 LLM 호출은 없다.
        with patch("app.llm.generate", return_value={"resume": False}):
            events = await collect(pipeline.run_pipeline(self.chat, "교육 이수율 알려줘", "자동", agents=["work"],
                scope_files={"workers": ["edu"]}))
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(execution_store.get(saved["id"])["state"], "cancelled")
        self.assertEqual(self.judge.call_args.args[2], ["work"])
        self.assertEqual(self.judge.call_args.kwargs["scope_files"]["workers"], ["edu"])
        self.assertEqual(self.driven[0]["snapshot"]["scope"], "자동")
        self.assertEqual(self.driven[0]["snapshot"]["scope_files"]["workers"], ["edu"])
        self.assertEqual(self.run_count(), 2)

    async def test_implicit_reply_can_resume_snapshot_when_selection_changed(self):
        saved = self.pending()
        with patch("app.llm.generate", return_value={"resume": True, "values": {"period": "이번 달"}}):
            events = await collect(pipeline.run_pipeline(self.chat, "이번 달", "사내", agents=["groupware"],
                scope_files={"workers": []}))
        self.assertEqual(events[-1]["type"], "done")
        self.judge.assert_not_called()
        self.assertEqual(self.driven[0]["id"], saved["id"])
        self.assertEqual(self.driven[0]["snapshot"]["scope_files"]["workers"], ["email"])

    async def test_unknown_card_never_becomes_new_or_scheduled_execution(self):
        with patch.object(pipeline.schedules_nl, "parse", side_effect=AssertionError("unexpected schedule")), \
                self.assertLogs("ai365.pipeline", level="ERROR"):
            events = await collect(pipeline.run_pipeline(self.chat, "매주 월요일", "사내", resume_id="run_missing",
                allow_schedule=True, force_schedule=True))
        self.assertEqual(events[-1]["type"], "error")
        self.judge.assert_not_called()
        self.assertEqual(self.driven, [])
        self.assertEqual(self.run_count(), 0)

    async def test_terminal_cards_never_become_new_execution(self):
        for state in ("completed", "cancelled", "failed", "needs_confirmation"):
            with self.subTest(state=state):
                saved = self.pending(state=state)
                before = self.run_count()
                with self.assertLogs("ai365.pipeline", level="ERROR"):
                    events = await collect(pipeline.run_pipeline(self.chat, "이번 달", "사내", resume_id=saved["id"]))
                self.assertEqual(events[-1]["type"], "error")
                self.assertEqual(self.run_count(), before)
                self.assertEqual(execution_store.get(saved["id"])["state"], state)
        self.judge.assert_not_called()
        self.assertEqual(self.driven, [])

    async def test_identity_permissions_chat_and_lane_still_block_resume(self):
        for mismatch in ("actor", "permissions", "chat", "lane"):
            with self.subTest(mismatch=mismatch):
                saved = self.pending(actor="7" if mismatch == "actor" else "",
                    eff={"nodes": {"agent_email": 1}} if mismatch == "permissions" else None,
                    lane="explore" if mismatch == "lane" else "chat")
                chat = db.create_chat("다른 채팅", "사내") if mismatch == "chat" else self.chat
                before = self.run_count()
                with self.assertLogs("ai365.pipeline", level="ERROR"):
                    events = await collect(pipeline.run_pipeline(chat, "이번 달", "사내", resume_id=saved["id"]))
                self.assertEqual(events[-1]["type"], "error")
                self.assertEqual(self.run_count(), before)
                self.assertEqual(execution_store.get(saved["id"])["state"], "needs_input")
        self.judge.assert_not_called()
        self.assertEqual(self.driven, [])

    async def test_legacy_plan_cannot_escape_explicit_worker_selection(self):
        self.judge.return_value = decision("edu")
        with self.assertLogs("ai365.pipeline", level="ERROR"):
            events = await collect(pipeline.run_pipeline(self.chat, "고객 메일", "사내", agents=["work"],
                scope_files={"workers": ["email"]}))
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(self.driven, [])
        self.assertEqual(self.run_count(), 0)

    async def test_legacy_web_fallback_uses_only_selected_worker(self):
        self.judge.return_value = {**decision(), "steps": [], "web": True}
        events = await collect(pipeline.run_pipeline(self.chat, "교육 관련 자료", "사내", agents=["work"],
            scope_files={"workers": ["edu"]}))
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(self.driven[0]["snapshot"]["decision"]["steps"][0]["worker"], "edu")


if __name__ == "__main__":
    unittest.main()
