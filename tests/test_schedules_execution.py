"""예약 진입점과 실제 공통 실행기 통합. DB·LLM·파일 생성·외부 호출은 격리한다.
2026-09-11: 예약은 프롬프트만 실행한다(워크플로우 예약·커넥터 폐지 — 사용자 확정). 관련 케이스는 삭제하고 프롬프트 계약만 남긴다.
Schedule entry point + shared runner integration with DB/LLM/docgen/HTTP isolated.
2026-09-11: schedules run prompts only (workflow schedules and connectors retired — user decision)."""
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from db_fixture import isolate_db
from app import collections_store, db, docgen, pipeline, schedules, schedules_api
from fastapi import HTTPException


class ScheduleExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        collections_store.init_collections()
        schedules.init_schedules()
        self.stack.enter_context(patch.object(schedules, "_owner_names", return_value={}))
        self.stack.enter_context(patch.object(pipeline, "_resolve_eff", return_value=None))
        self.stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")))
        self.stack.enter_context(patch("app.llm.stream", side_effect=AssertionError("unexpected LLM")))
        self.stack.enter_context(patch("app.flow_api_call.call", side_effect=AssertionError("unexpected API")))
        self.stack.enter_context(patch.object(docgen, "run_docgen", side_effect=AssertionError("unexpected docgen")))

    async def fire(self, message="query", **kwargs):
        owner = kwargs.pop("owner", "")
        schedule = schedules.create(None, owner, "test", message, "사내", "daily", "09:00", [], True, False, **kwargs)
        self.assertTrue(schedules.claim(schedule["id"], force=True))
        return schedule["id"], await schedules._fire_inner(schedule["id"], {})

    async def test_prompt_schedule_runs_the_pipeline_with_its_prompt(self):
        seen = []

        async def fake_pipeline(chat, message, scope, *args, **kwargs):
            seen.append((message, scope, kwargs.get("connectors")))
            mid = db.add_message(chat["id"], "assistant", "조회 완료")
            yield {"type": "token", "text": "조회 완료"}
            yield {"type": "done", "message_id": mid}
        with patch.object(pipeline, "run_pipeline", fake_pipeline):
            _, (result, chat_id, preview) = await self.fire("창고별 재고를 정리해줘")
        self.assertEqual(result, "ok")
        self.assertEqual(seen, [("창고별 재고를 정리해줘", "사내", None)])
        self.assertEqual(db.list_messages(chat_id)[0]["content"], "창고별 재고를 정리해줘")
        self.assertEqual(preview, "조회 완료")
        chat = db.get_chat(chat_id)
        self.assertNotIn("connectors", chat)
        self.assertEqual(chat["flow_id"], "")

    async def test_empty_prompt_pauses_without_running(self):
        with patch.object(pipeline, "run_pipeline") as execute:
            sid, _ = await self.fire("")
        execute.assert_not_called()
        row = schedules.get(sid)
        self.assertEqual(row["status"], "paused")
        self.assertTrue(row["last_result"].startswith("error:프롬프트"))
        self.assertIsNone(row["last_chat_id"])

    def test_message_is_required_on_create_and_patch(self):
        with self.assertRaises(HTTPException):
            schedules_api.create_global(schedules_api.SchedCreateGlobal(message="", rule="daily", run_at="09:00"))
        created = schedules_api.create_global(schedules_api.SchedCreateGlobal(
            name="프롬프트 예약", message="매출 정리", rule="daily", run_at="09:00", notify_email=False))
        with self.assertRaises(HTTPException):
            schedules_api.patch_global(created["id"], schedules_api.SchedPatch(message=""))
        edited = schedules_api.patch_global(created["id"], schedules_api.SchedPatch(message="재고 정리"))
        self.assertEqual(edited["message"], "재고 정리")
        # 폐지된 필드는 응답에 없다 / retired fields are absent from responses
        for key in ("flow_id", "flow_name", "flow_query", "connectors"):
            self.assertNotIn(key, edited)

    def test_retired_columns_survive_migration(self):
        created = schedules.create(None, "", "구형 예약", "query", "사내", "daily", "09:00", [], True, False)
        with db._conn() as conn:
            conn.execute("ALTER TABLE coll_schedules DROP COLUMN flow_query")
        schedules.init_schedules()
        schedules.init_schedules()
        restored = schedules.get(created["id"])
        self.assertEqual(restored["message"], "query")
        self.assertNotIn("flow_query", restored)
