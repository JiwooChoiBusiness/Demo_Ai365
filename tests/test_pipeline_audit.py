import asyncio
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

from db_fixture import isolate_db
from app import (actions_api, answers, artifact_execution, collections_store as coll, db, docgen,
                 execution_store as store, flows, notify, pipeline, runs, schedules)
from app import conversation_execution as conversation
from app.agents import AGENT_REGISTRY, groupware
from app.sql_policy import select_sql
from app.run_context import MESSAGE_LANE


class SQLPolicyTests(unittest.TestCase):
    def test_permitted_cte_join_aggregate_and_window(self):
        sql = '''WITH totals AS (SELECT dept, SUM(budget) AS total FROM dept_budget GROUP BY dept)
                 SELECT dept, total, ROW_NUMBER() OVER (ORDER BY total DESC) FROM totals'''
        self.assertIn("SUM", select_sql(sql, {"dept_budget"}))
        self.assertIn("JOIN", select_sql('SELECT * FROM dept_budget a JOIN dept_budget b ON a.dept=b.dept', {"dept_budget"}))
        self.assertIn("DATE_TRUNC", select_sql("SELECT date_trunc('month', current_date)", set()))

    def test_external_sources_and_unapproved_functions_are_blocked(self):
        for sql in ["SELECT * FROM read_csv_auto('canary.csv')", "SELECT * FROM 'canary.csv'",
                    "SELECT * FROM read_blob('canary.txt')", "SELECT * FROM query('SELECT 1')",
                    "SELECT * FROM information_schema.tables", "SELECT * FROM blocked_table",
                    "SELECT * FROM (SELECT * FROM blocked_table) x", "SELECT getenv('HOME')",
                    "SELECT * FROM duckdb_secrets()", "SELECT 1; SELECT 2", "DELETE FROM allowed_table"]:
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                select_sql(sql, {"allowed_table"})

    def test_semi_and_anti_joins_cannot_reach_blocked_tables_or_files(self):
        # 2026-11-16(위젯 3단계 검토): selected_sources 가 SEMI · ANTI JOIN 의 오른쪽을 빼서, 금지된 테이블과 따옴표 친 파일 경로를
        # ON 조건으로 한 비트씩 읽을 수 있었다 / selected_sources skipped the right side of SEMI / ANTI JOINs, leaking blocked tables
        # and quoted file paths one bit at a time through the ON condition
        for sql in ["SELECT COUNT(*) AS n FROM allowed_table SEMI JOIN blocked_table ON blocked_table.salary > 500",
                    "SELECT COUNT(*) FROM allowed_table ANTI JOIN blocked_table b ON b.x = 1",
                    "SELECT COUNT(*) FROM allowed_table SEMI JOIN \"C:/secret/keys.csv\" AS s ON s.token LIKE 'x%'",
                    "SELECT COUNT(*) FROM allowed_table ANTI JOIN '/etc/passwd.json' s ON TRUE",
                    "SELECT COUNT(*) FROM allowed_table a ASOF JOIN blocked_table s ON a.x >= s.x",
                    "SELECT * FROM allowed_table WHERE EXISTS (SELECT 1 FROM allowed_table SEMI JOIN blocked_table ON TRUE)"]:
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                select_sql(sql, {"allowed_table"})
        # 허용된 테이블끼리의 SEMI JOIN · CTE 는 그대로 된다 / SEMI JOINs between allowed tables and CTEs still work
        self.assertIn("SEMI JOIN", select_sql("SELECT COUNT(*) FROM allowed_table a SEMI JOIN other_table b ON a.x = b.x",
                                              {"allowed_table", "other_table"}))
        self.assertTrue(select_sql("WITH t AS (SELECT x FROM allowed_table) SELECT * FROM t SEMI JOIN allowed_table a ON t.x = a.x",
                                   {"allowed_table"}))

    def test_cte_alias_does_not_hide_a_blocked_source(self):
        with self.assertRaises(ValueError):
            select_sql('WITH blocked_table AS (SELECT * FROM blocked_table) SELECT * FROM blocked_table', {"allowed_table"})

    def test_logical_connectors_and_predicates_are_not_treated_as_functions(self):
        # 2026-09-26: sqlglot 30.18.0 에서 And/Or/Xor(exp.Connector)·Exists 가 Func 도 상속해 "허용되지 않는 SQL 함수: AND" 로
        # 조건이 둘 이상인 질의가 전부 거부되던 결함 — 연산자·술어는 함수 허용 목록 검사 대상이 아니다
        # 2026-09-26: in sqlglot 30.18.0 And/Or/Xor (exp.Connector) and Exists also inherit Func, so every query with two or more
        # conditions was rejected as "unapproved function AND"; operators and predicates are not subject to the function allow list
        tables = {"quality", "sales"}
        for sql in [
            "SELECT plant FROM quality WHERE plant = 'HQ' AND defect_rate_pct > 1",
            "SELECT plant FROM quality WHERE plant = 'HQ' OR plant = 'BUSAN'",
            "SELECT plant FROM quality WHERE (plant = 'HQ' OR plant = 'BUSAN') AND defect_rate_pct > 1",
            "SELECT plant FROM quality WHERE NOT (plant = 'HQ') AND plant IS NOT NULL",
            "SELECT plant FROM quality WHERE defect_rate_pct BETWEEN 1 AND 3 AND plant IN ('HQ', 'BUSAN')",
            "SELECT plant FROM quality WHERE plant LIKE 'H%' OR plant ILIKE 'b%'",
            "SELECT CASE WHEN defect_rate_pct > 1 AND plant = 'HQ' THEN 'high' ELSE 'low' END AS lvl FROM quality",
            "SELECT plant, SUM(defect_rate_pct) FROM quality GROUP BY plant HAVING SUM(defect_rate_pct) > 1 AND COUNT(*) > 2",
            "SELECT COUNT(*) FILTER (WHERE defect_rate_pct > 1 AND plant = 'HQ') FROM quality",
            "SELECT plant FROM quality q WHERE EXISTS (SELECT 1 FROM sales s WHERE s.branch = q.plant AND s.amount > 0)",
        ]:
            with self.subTest(sql=sql):
                self.assertTrue(select_sql(sql, tables))
        self.assertIn(" AND ", select_sql("SELECT plant FROM quality WHERE plant = 'HQ' AND defect_rate_pct > 1", tables))

    def test_connectors_never_open_external_sources_or_unapproved_functions(self):
        # 연산자 노드 자체의 이름 검사만 빠진다 — 피연산자·서브쿼리 안의 함수와 테이블은 그대로 검사된다
        # Only the operator node's own name check is skipped; functions and tables inside operands and subqueries are still checked
        for sql, needle in [
            ("SELECT * FROM read_csv_auto('canary.csv') WHERE 1 = 1 AND 2 = 2", "READ_CSV_AUTO"),
            ("SELECT plant FROM quality WHERE plant = 'HQ' AND getenv('HOME') = 'x'", "GETENV"),
            ("SELECT plant FROM quality WHERE plant = 'A' OR regexp_matches(plant, 'H.*')", "REGEXP"),
            ("SELECT plant FROM quality WHERE EXISTS (SELECT 1 FROM read_csv_auto('x.csv'))", "READ_CSV_AUTO"),
            ("SELECT plant FROM quality WHERE EXISTS (SELECT 1 FROM blocked_table)", "허용된 테이블"),
            ("SELECT plant FROM quality WHERE plant = 'A' OR plant IN (SELECT secret FROM blocked_table)", "허용된 테이블"),
            ("SELECT plant FROM quality WHERE plant = 'A' AND 1 = 1; DELETE FROM quality", "SELECT 단일"),
        ]:
            with self.subTest(sql=sql), self.assertRaises(ValueError) as ctx:
                select_sql(sql, {"quality"})
            self.assertIn(needle, str(ctx.exception))


class AuditTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        coll.init_collections()
        schedules.init_schedules()
        self.stack.enter_context(patch.object(schedules, "_owner_names", return_value={}))
        self.stack.enter_context(patch.object(pipeline, "_resolve_eff", return_value=None))
        self.stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")))
        self.stack.enter_context(patch("app.llm.stream", side_effect=AssertionError("unexpected LLM")))
        self.stack.enter_context(patch("app.flow_api_call.call", side_effect=AssertionError("unexpected external call")))
        self.stack.enter_context(patch.object(notify, "mail_backend", return_value="virtual"))
        self.stack.enter_context(patch.object(notify, "resolve_me", return_value=["test@example.invalid"]))
        self.mail = self.stack.enter_context(patch.object(schedules, "_send_one", AsyncMock(return_value={"ok": True, "backend": "test"})))

    def pending_schedule(self):
        s = schedules.create(None, "", "test", "query", "사내", "daily", "09:00", [], True, True)
        schedules.claim(s["id"], force=True)
        chat = db.create_chat("run", "사내", sched=s["id"])
        schedules._close(s["id"], "needs_input", chat["id"])
        db.set_chat_sched_result(chat["id"], "needs_input")
        return s, chat

    async def test_api_node_without_api_fails_closed_without_calling(self):
        # 2026-09-11: 전역(AI 선택) 폐지 — API 미지정 노드는 후보 풀 없이 실패로 닫히고 LLM·호출 모두 없다
        # 2026-09-11: the global AI pick is retired — an unset node fails closed with no candidate pool, no LLM, no call
        pool = [{"id": "cn_test", "kind": "read", "name": "test", "enabled": True, "api": {}}]
        with patch("app.connectors.list_connectors", return_value=pool), \
             patch("app.access.allowed_connectors", return_value=None), \
             patch.object(flows, "call_connector", AsyncMock()) as call:
            result = await flows._run_api_node({"resources": [], "prompt": "조회"}, "조회", [])
        self.assertEqual(result["status"], "failed")
        self.assertIn("API가 지정되지 않았습니다", result["text"])
        call.assert_not_awaited()

    async def test_missing_inputs_ask_instead_of_calling_regardless_of_kind(self):
        # 2026-09-11: 워크플로우 API 작업은 설정에 쓰인 입력값을 종류와 무관하게 필수로 본다 — 입력값 추출 LLM 이 실패한 조회 API 도
        # 빈 값으로 호출하지 않고 needs_input 으로 묻는다(옛 '빈 필터=전체 조회' 계약은 채팅 커넥터 경로 전용이었다)
        # 2026-09-11: workflow API tasks treat every configured input as required regardless of kind — a read API whose
        # input-extraction LLM failed asks (needs_input) instead of calling with an empty value (the old "empty filter =
        # list all" contract belonged to the retired chat-connector path)
        read = {"id": "cn_r", "kind": "read", "name": "read", "api": {"url": "https://x/{{input.sku}}"}}
        with patch.object(flows, "_api_candidates", return_value=([read], None)), \
             patch.object(flows.llm, "generate", side_effect=RuntimeError("model error")), \
             patch.object(flows, "call_connector", AsyncMock(return_value={"ok": True})) as call:
            result = await flows._run_api_node({"resources": ["cn_r"]}, "조회", [])
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["extras"]["missing_inputs"], ["sku"])
        call.assert_not_awaited()
        # 값이 뽑히면(공백 아님) 조회 API 는 그대로 호출된다 / an extracted non-blank value lets the read API run
        with patch.object(flows, "_api_candidates", return_value=([read], None)), \
             patch.object(flows.llm, "generate", return_value={"inputs": {"sku": "SKU-1001"}}), \
             patch.object(flows, "call_connector", AsyncMock(return_value={"ok": True})) as call:
            result = await flows._run_api_node({"resources": ["cn_r"]}, "SKU-1001 재고", [])
        self.assertEqual(result["status"], "done")
        self.assertEqual(call.await_args.args[3], {"sku": "SKU-1001"})
        act = {"id": "cn_a", "kind": "action", "name": "act", "api": {"url": "https://x/{{input.sku}}",
               "input_docs": [{"name": "sku", "description": "품목 코드", "example": "SKU-1"}]}}
        with patch.object(flows, "_api_candidates", return_value=([act], None)), \
             patch.object(flows.llm, "generate", return_value={"inputs": {}}), \
             patch.object(flows, "call_connector", AsyncMock()) as call:
            result = await flows._run_api_node({"resources": ["cn_a"]}, "주문", [])
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["extras"]["missing_inputs"], ["sku"])
        call.assert_not_awaited()

    async def test_fixed_connector_without_inputs_still_runs(self):
        c = {"id": "cn_test", "kind": "read", "name": "test", "api": {}}
        with patch.object(flows, "_api_candidates", return_value=([c], None)), \
             patch.object(flows, "call_connector", AsyncMock(return_value={"ok": True})) as call:
            result = await flows._run_api_node({"resources": ["cn_test"]}, "조회", [])
        self.assertEqual(result["status"], "done")
        call.assert_awaited_once()

    async def test_main_context_and_file_sources_exclude_exploration(self):
        chat = db.create_chat("test", "사내")
        db.add_message(chat["id"], "assistant", "MAIN_REPORT")
        token = MESSAGE_LANE.set("explore")
        try:
            db.add_message(chat["id"], "assistant", "HIDDEN", {"sources": {"knowledge": {"items": [{"title": "hidden.pdf"}]}}})
        finally:
            MESSAGE_LANE.reset(token)
        db.add_message(chat["id"], "assistant", "OLD_EXPLORE", {"kind": "explore"})
        for build in (pipeline._build_context, flows._build_context):
            context = build(chat["id"], "그대로 메일로 보내줘")
            self.assertEqual(next(m["content"] for m in reversed(context) if m["role"] == "assistant"), "MAIN_REPORT")
        self.assertNotIn("HIDDEN", str(docgen._context_messages(chat["id"], "현재")))

    async def test_deleted_selected_collection_file_does_not_expand_scope(self):
        c = coll.create_collection("test")
        chosen = coll.add_file(c["id"], "chosen.txt", "CHOSEN")
        coll.add_file(c["id"], "other.txt", "UNSELECTED")
        coll.remove_file(c["id"], chosen["id"])
        material = coll.context_for(c["id"], ["chosen.txt"])
        self.assertNotIn("UNSELECTED", material)
        self.assertIn("다시 선택", material)
        self.assertIn("UNSELECTED", coll.context_for(c["id"]))

    async def test_web_success_enables_file_but_worker_failure_does_not(self):
        for status in ("not_found", "failed"):
            chat = db.create_chat("test", "자동")
            d = {"version": 3, "query": "뉴스 PDF", "steps": [{"id": "news", "agent": "knowledge", "task": "뉴스",
                 "depends_on": [], "inputs": {}}], "send_query": "", "clarify": None,
                 "document": {"format": "pdf", "topic": "뉴스"}, "use_previous": False, "web": True}
            run = conversation.create(chat, d, d["query"], [], "자동", None, {}, "", "")
            run["snapshot"]["doc_cfg"] = {"format": "pdf", "topic": "뉴스", "style": "report", "length": 2, "source": "context"}
            made = []
            async def make_doc(*a, **kw):
                made.append(True)
                yield {"type": "doc_meta", "doc_id": "doc_test", "format": "pdf", "filename": "news.pdf"}
                yield {"type": "done"}
            async def aggregate(*a, **kw):
                yield {"type": "token", "text": "실패 안내"}
                yield {"type": "done"}
            with patch.dict(AGENT_REGISTRY["knowledge"], {"run": AsyncMock(return_value={"status": status})}), \
                 patch.object(answers.llm, "generate_grounded_meta", return_value={"text": "웹 뉴스", "sources": [], "supports": []}), \
                 patch.object(answers, "_aggregate_answer", aggregate), patch.object(docgen, "run_docgen", make_doc):
                events = [e async for e in conversation.drive(run, chat, [], None)]
            self.assertEqual(bool(made), status == "not_found")
            self.assertEqual(runs._derive_state(events), "done" if status == "not_found" else "error")

    async def test_failed_workflow_is_error_in_both_chat_and_schedule(self):
        s, _ = self.pending_schedule()
        schedules.update(s["id"], {"flow_id": "flow_test", "flow_query": "실패 처리 검증"})
        schedules.claim(s["id"], force=True)
        async def failed(*a, checkpoint_run=None):
            checkpoint_run["snapshot"]["results"]["first"] = {"status": "failed"}
            yield {"type": "done"}
        with patch.object(flows, "find_flow", return_value={"name": "test"}), patch.object(flows, "run_flow", failed):
            result, _, _ = await schedules._fire_inner(s["id"], {})
        self.assertTrue(result.startswith("error:"))

    async def test_confirmed_delivery_updates_history_and_notifies_once(self):
        s, chat = self.pending_schedule()
        run = store.create(chat["id"], {"actor": "", "eff": None, "artifact": {"id": "doc_test"}})
        aid = db.create_action(chat["id"], "mail.action.compose", {}, "test")
        store.link_action(aid, run["id"], "$delivery")
        store.save(run, "needs_confirmation")
        await schedules._notify_after_run(s["id"], "needs_input", chat["id"], "")
        with patch.object(groupware, "execute_action", return_value="sent"):
            await actions_api.confirm_action(aid)
        await schedules.complete_resumed(chat["id"], "completed", True)
        await schedules._notify_after_run(s["id"], "doc", chat["id"], "")
        self.assertEqual(self.mail.await_count, 2)  # 입력 필요 1회 + 최종 완료 1회
        self.assertEqual(db.get_chat(chat["id"])["sched_result"], "doc")
        self.assertEqual(schedules.get(s["id"])["last_result"], "doc")

    async def test_old_resume_preserves_newest_run_and_next_time(self):
        s, old = self.pending_schedule()
        schedules.claim(s["id"], force=True)
        newest = db.create_chat("new", "사내", sched=s["id"])
        schedules._close(s["id"], "ok", newest["id"])
        before = schedules.get(s["id"])
        await schedules.complete_resumed(old["id"], "failed")
        after = schedules.get(s["id"])
        for field in ("last_result", "last_chat_id", "next_run_at"):
            self.assertEqual(before[field], after[field])
        self.assertTrue(db.get_chat(old["id"])["sched_result"].startswith("error:"))

    async def test_background_resume_finalizes_only_original_schedule_execution(self):
        from app import background_execution
        s, chat = self.pending_schedule()
        original = store.create(chat["id"], {})
        async def completed(run):
            yield {"type": "execution_result", "run_id": run["id"], "state": "completed", "artifact": True}
        job = background_execution.start(chat["id"], completed(original))
        await job.task
        self.assertEqual(schedules.get(s["id"])["last_result"], "doc")
        self.assertEqual(self.mail.await_count, 1)
        followup = store.create(chat["id"], {})
        async def failed_followup():
            yield {"type": "execution_result", "run_id": followup["id"], "state": "failed"}
        job = background_execution.start(chat["id"], failed_followup())
        await job.task
        self.assertEqual(schedules.get(s["id"])["last_result"], "doc")
        self.assertEqual(self.mail.await_count, 1)
        runs.RUNS.pop(chat["id"], None)

    async def test_close_after_execution_start_marks_checkpoint_interrupted(self):
        chat = db.create_chat("test", "사내")
        d = {"version": 3, "query": "test", "steps": [], "send_query": "", "clarify": None,
             "document": None, "use_previous": False, "web": False}
        run = conversation.create(chat, d, "test", [], "사내", None, {}, "", "")
        stream = conversation.drive(run, chat, [], None)
        self.assertEqual((await anext(stream))["state"], "running")
        await stream.aclose()
        self.assertEqual(store.get(run["id"])["state"], "interrupted")

    async def test_delete_and_prune_remove_effects_but_preserve_pending_runs(self):
        s, waiting = self.pending_schedule()
        pending = store.create(waiting["id"], {})
        store.save(pending, "needs_input")
        done = db.create_chat("done", "사내", sched=s["id"])
        finished = store.create(done["id"], {})
        store.save(finished, "completed")
        aid = db.create_action(done["id"], "mail.action.compose", {}, "test")
        store.link_action(aid, finished["id"], "$delivery")
        store.effect_claim("action:" + aid)
        self.assertEqual(schedules._prune_runs(s["id"], keep=0), 1)
        self.assertIsNone(store.get(finished["id"]))
        self.assertIsNone(store.effect_get("action:" + aid))
        self.assertIsNone(db.get_action(aid))
        self.assertIsNotNone(db.get_chat(waiting["id"]))
        self.assertTrue(await schedules.delete_with_runs(s["id"]))
        self.assertIsNone(store.get(pending["id"]))

    async def test_delete_cancels_active_scheduled_execution(self):
        s, chat = self.pending_schedule()
        schedules.claim(s["id"], force=True)
        started, stopped = asyncio.Event(), asyncio.Event()
        async def blocking(sid, state):
            state["chat_id"] = chat["id"]
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        with patch.object(schedules, "_fire_inner", blocking):
            task = asyncio.create_task(schedules.fire(s["id"]))
            await started.wait()
            await schedules.delete_with_runs(s["id"])
        self.assertTrue(stopped.is_set())
        self.assertTrue(task.done())
        self.assertIsNone(schedules.get(s["id"]))
