import asyncio
import copy
import json
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

from db_fixture import isolate_db
from app import db, execution_store as store, conversation_execution as conversation, artifact_execution, answers, flows, runs
from app.decisions import validate, fill, from_legacy
from app.execution import execute, Task, PlanError
from app.task_results import usable, state
from app.tool_runtime import call_connector, run_connector
from app.tool_contracts import prepare_inputs


def decision(steps=None, **kwargs):
    return {"version": 3, "query": "원래 요청", "steps": steps or [], "send_query": "", "clarify": None,
            "document": None, "use_previous": False, "web": False, **kwargs}


def step(key, agent="data", deps=None, **kwargs):
    return {"id": key, "agent": agent, "task": key, "depends_on": deps or [], "inputs": {}, **kwargs}


async def collect(stream):
    return [e async for e in stream]


async def aggregate(*args, **kwargs):
    yield {"type": "answer_head", "source": "사내"}
    yield {"type": "token", "text": "완성된 보고서"}
    yield {"type": "done"}


class ContractTests(unittest.TestCase):
    def test_new_plan_requires_explicit_dependencies(self):
        with self.assertRaises(PlanError):
            validate(decision([{"id": "a", "agent": "data", "task": "매출", "inputs": {}}]))
        self.assertEqual(from_legacy({"plan": {"steps": [{"agent": "data", "task": "매출"},
                          {"agent": "data", "task": "분석"}]}}, "q")["steps"][1]["depends_on"], ["s1"])

    def test_clarification_preserves_three_tasks_and_only_fills_recipient(self):
        d = decision([step("sales"), step("rights", "work", worker="edu"),
                      step("stock", "connector", connector_id="cn_stock")], send_query="보고서를 메일로 보내줘",
                     clarify={"question": "누구에게?", "options": ["나에게"], "slots": [{"key": "to", "target": "send_query"}]})
        validate(d, connector_ids={"cn_stock"})
        filled = fill(d, {"to": "나에게"})
        self.assertEqual(d["steps"], filled["steps"])
        self.assertIsNotNone(d["clarify"])
        self.assertIsNone(filled["clarify"])
        self.assertIn("나에게", filled["send_query"])

    def test_input_schema_types_required_defaults(self):
        c = {"kind": "read", "api": {"tool_contract": {"version": 1, "retry_safe": True,
             "input_schema": {"type": "object", "properties": {"id": {"type": "integer"},
                "active": {"type": "boolean", "default": False}}, "required": ["id"], "additionalProperties": False}}}}
        self.assertEqual(prepare_inputs(c, {})[1], ["id"])
        self.assertEqual(prepare_inputs(c, {"id": 0})[0], {"id": 0, "active": False})
        for invalid in ({"id": True}, {"id": "3"}, {"id": 2, "extra": "x"}):
            with self.assertRaises(PlanError):
                prepare_inputs(c, invalid)

    def test_failed_and_waiting_are_never_success(self):
        for r in [{"status": "failed"}, {"status": "blocked"}, {"status": "answer", "extras": {"await_recipient": True}}]:
            self.assertFalse(usable(r))
        self.assertEqual(state({"status": "not_found"}), "not_found")


class PersistentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        self.chat = db.create_chat("test", "사내")
        self.stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")))
        self.stack.enter_context(patch("app.llm.stream", side_effect=AssertionError("unexpected LLM stream")))
        self.stack.enter_context(patch("app.flow_api_call.call", side_effect=AssertionError("unexpected external API")))
        self.stack.enter_context(patch.object(answers, "_aggregate_answer", aggregate))

    def make_run(self, d):
        return conversation.create(self.chat, d, "원래 요청", [{"role": "user", "content": "원래 요청"}],
                                   "사내", None, {}, "", "")

    async def test_multiple_confirmations_resume_only_remaining_tasks(self):
        from app.agents import AGENT_REGISTRY
        calls = []
        async def worker(query, *args, **kwargs):
            calls.append(query)
            return {"status": "answer", "extras": {"action_draft": {"kind": "todo.action.create",
                    "payload": {"title": query}, "summary": query}}}
        run = self.make_run(decision([step("first", "groupware"), step("second", "groupware"), step("last", deps=["first", "second"])]))
        with patch.dict(AGENT_REGISTRY["groupware"], {"run": worker}), \
             patch.dict(AGENT_REGISTRY["data"], {"run": AsyncMock(return_value={"status": "answer", "text": "후속 분석"})}):
            events = await collect(conversation.drive(run, self.chat, [], None))
            first = next(e for e in events if e["type"] == "confirm")
            AGENT_REGISTRY["data"]["run"].assert_not_called()
            run = conversation.action_finished(first["action_id"], True, "첫 작업 완료")
            events = await collect(conversation.drive(run, self.chat, [], None))
            second = next(e for e in events if e["type"] == "confirm")
            self.assertNotEqual(first["action_id"], second["action_id"])
            AGENT_REGISTRY["data"]["run"].assert_not_called()
            run = conversation.action_finished(second["action_id"], True, "둘째 작업 완료")
            await collect(conversation.drive(run, self.chat, [], None))
            query = AGENT_REGISTRY["data"]["run"].call_args.args[0]
            self.assertIn("첫 작업 완료", query)
            self.assertIn("둘째 작업 완료", query)
        self.assertEqual(calls, ["first", "second"])
        self.assertEqual(store.get(run["id"])["state"], "completed")

    async def test_clarify_before_any_work_and_resume_retains_query(self):
        from app.agents import AGENT_REGISTRY
        d = decision([step("sales")], clarify={"question": "어느 기간?", "options": [],
                     "slots": [{"key": "period", "target": "task", "task_id": "sales"}]})
        run = self.make_run(d)
        with patch.dict(AGENT_REGISTRY["data"], {"run": AsyncMock(return_value={"status": "answer", "text": "매출"})}):
            events = await collect(conversation.drive(run, self.chat, [], None))
            self.assertEqual(events[-1]["type"], "clarify")
            AGENT_REGISTRY["data"]["run"].assert_not_called()
            run = store.get(run["id"])
            self.assertTrue(conversation.fill_reply(run, "이번 달", explicit=True))
            await collect(conversation.drive(run, self.chat, [], None))
            self.assertIn("이번 달", AGENT_REGISTRY["data"]["run"].call_args.args[0])
        self.assertEqual(run["snapshot"]["message"], "원래 요청")

    async def test_completed_effect_is_reused_and_uncertain_effect_is_not_retried(self):
        c = {"id": "cn", "name": "주문", "kind": "action", "api": {"url": "https://example.invalid",
             "response": {"on_error": "retry", "retries": 3}}}
        result = {"ok": True, "json": {"id": 1}}
        with patch("app.flow_api_call.call", return_value=result) as http:
            self.assertEqual(await call_connector(c, "q", "", {}, effect_key="run:one"), result)
            self.assertEqual(await call_connector(c, "q", "", {}, effect_key="run:one"), result)
            http.assert_called_once()
            self.assertEqual(http.call_args.args[0]["response"]["retries"], 0)
            store.effect_claim("run:uncertain")
            with self.assertRaises(PlanError):
                await call_connector(c, "q", "", {}, effect_key="run:uncertain")
            http.assert_called_once()

    async def test_failure_never_triggers_web_fallback(self):
        with patch.object(answers, "_run_external") as web, patch.object(answers, "_judge_gap") as gap:
            events = await collect(answers._auto_answer(self.chat["id"], "사내", [], "q", {"a": {"agent": "data", "status": "failed"}}))
        web.assert_not_called()
        gap.assert_not_called()
        self.assertEqual(events[-1]["type"], "done")

    async def test_server_document_chain_does_not_depend_on_subscriber(self):
        from app import background_execution
        entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def producer():
            yield {"type": "token", "text": "보고서"}
            entered.set()
            await release.wait()
            yield {"type": "segment_start", "doc": {"format": "pdf"}}
            yield {"type": "done", "artifact": {"id": "doc_test"}}
            finished.set()
        run = background_execution.start(self.chat["id"], producer())
        replay, queue = runs.subscribe(self.chat["id"])
        await entered.wait()
        runs.unsubscribe(self.chat["id"], queue)
        release.set()
        await asyncio.wait_for(finished.wait(), 1)
        await run.task
        self.assertEqual(run.state, "done")
        self.assertEqual(run.events[-1]["artifact"]["id"], "doc_test")
        runs._evict(run)

    async def test_workflow_checkpoint_skips_completed_stage_after_restart(self):
        # 2026-09-11 단계 게이트: 저장된 1단계 결과는 재실행하지 않고, 1단계 보고 뒤 실행 카드에서 멈춘다(needs_input).
        # 실행 카드 응답(run)으로 재개하면 2단계만 실행하고 최종 취합까지 간다.
        # Stage gates (2026-09-11): the saved stage-1 result is not re-run; after the stage-1 report the run stops at the
        # run card (needs_input). Resuming with the run-card reply executes only stage 2 and finishes with the aggregation.
        flow = {"id": "f", "name": "test", "stages": [{"nodes": [{"agent": "data", "instruction": "a", "resources": []}]},
                    {"nodes": [{"agent": "data", "instruction": "b", "resources": []}]}]}
        calls = []
        async def worker(node, *args):
            calls.append(node["instruction"])
            return {"status": "done", "text": node["instruction"], "label": node["instruction"]}
        async def tokens(*a, **k):
            yield "보고서"
        run = store.create(self.chat["id"], {"kind": "workflow", "flow": flow, "message": "q", "actor": "", "eff": None,
             "results": {"stage1_1": {"status": "done", "text": "a", "label": "a"}}})
        with patch.object(flows, "_resolve_eff", return_value=None), patch.object(flows, "_build_context", return_value=[]), \
             patch.object(flows, "_run_step_node", side_effect=worker), patch.object(flows, "_astream", tokens), \
             patch.object(flows, "_flow_sources", return_value=None), \
             patch.object(flows.llm, "generate", side_effect=AssertionError("no review LLM expected here")):
            events = await collect(artifact_execution.workflow_run(flow, self.chat, "q", "", run))
            self.assertEqual(calls, [])
            self.assertEqual([e["type"] for e in events if e["type"] in ("flow_gate", "done")], ["flow_gate", "done"])
            run = store.get(run["id"])
            self.assertEqual(run["state"], "needs_input")
            self.assertEqual(run["snapshot"]["waiting"], {"kind": "gate", "stage": 0})
            self.assertFalse(artifact_execution.resume_workflow(run, {"kind": "flow_gate", "action": "run", "note": ""}))
            await collect(artifact_execution.workflow_run(flow, self.chat, "q", "", store.get(run["id"])))
        self.assertEqual(calls, ["b"])
        self.assertEqual(store.get(run["id"])["state"], "completed")

    async def test_action_claim_prevents_double_execution(self):
        from fastapi import FastAPI
        import httpx
        from app import actions_api
        app = FastAPI()
        app.include_router(actions_api.router)
        action_id = db.create_action(self.chat["id"], "todo.action.create", {"title": "task"}, "task")
        with patch.object(actions_api.groupware_agent, "execute_action", return_value="완료") as action:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                responses = await asyncio.gather(*[client.post(f"/api/actions/{action_id}/confirm", json={}) for _ in range(2)])
        self.assertEqual(sorted(r.status_code for r in responses), [200, 409])
        action.assert_called_once()

    async def test_new_read_schema_missing_input_asks_without_http(self):
        c = {"id": "cn", "name": "조회", "kind": "read", "api": {"tool_contract": {"version": 1,
             "input_schema": {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]}}}}
        result = await run_connector(c, "q", "", {})
        self.assertEqual(state(result), "needs_input")
        self.assertEqual(result["extras"]["missing_inputs"], ["sku"])

    async def test_recovery_marks_running_interrupted_and_retains_results(self):
        run = self.make_run(decision([step("a")]))
        run["snapshot"]["results"] = {"a": {"status": "answer", "text": "저장됨"}}
        store.save(run, "running")
        store.recover()
        restored = store.get(run["id"])
        self.assertEqual(restored["state"], "interrupted")
        self.assertEqual(restored["snapshot"]["results"]["a"]["text"], "저장됨")

    async def test_missing_inputs_and_recipient_are_asked_together_before_effects(self):
        from app.agents import AGENT_REGISTRY
        c = {"id": "cn", "name": "주문 승인", "kind": "action", "api": {"tool_contract": {"version": 1,
             "input_schema": {"type": "object", "properties": {"order_id": {"type": "integer"}}, "required": ["order_id"]}}}}
        run = self.make_run(decision([step("approve", "connector", connector_id="cn"), step("sales")], send_query="메일 보내줘"))
        with patch("app.agents.groupware.run", AsyncMock(return_value={"status": "answer", "text": "누구에게?",
                   "extras": {"await_recipient": True}})), patch.dict(AGENT_REGISTRY["data"], {"run": AsyncMock()}) as registry:
            events = await collect(conversation.drive(run, self.chat, [c], None))
            AGENT_REGISTRY["data"]["run"].assert_not_called()
        self.assertEqual(events[-1]["type"], "clarify")
        saved = store.get(run["id"])
        self.assertEqual({slot["target"] for slot in saved["snapshot"]["decision"]["clarify"]["slots"]}, {"input", "send_query"})
        self.assertEqual(saved["snapshot"]["results"], {})
        self.assertIsNone(store.effect_get(run["id"] + ":approve"))

    async def test_cancelled_action_blocks_dependents_without_replaying(self):
        from app.agents import AGENT_REGISTRY
        run = self.make_run(decision([step("first", "groupware"), step("next", deps=["first"])]))
        draft = {"status": "answer", "extras": {"action_draft": {"kind": "todo.action.create", "payload": {"title": "x"}, "summary": "x"}}}
        with patch.dict(AGENT_REGISTRY["groupware"], {"run": AsyncMock(return_value=draft)}), \
             patch.dict(AGENT_REGISTRY["data"], {"run": AsyncMock()}):
            events = await collect(conversation.drive(run, self.chat, [], None))
            run = conversation.action_finished(next(e["action_id"] for e in events if e["type"] == "confirm"), False, "취소", True)
            await collect(conversation.drive(run, self.chat, [], None))
            AGENT_REGISTRY["data"]["run"].assert_not_called()
            AGENT_REGISTRY["groupware"]["run"].assert_called_once()
        self.assertEqual(state(store.get(run["id"])["snapshot"]["results"]["next"]), "blocked")

    async def test_document_completed_before_delivery_and_artifact_is_attached(self):
        from app.agents import AGENT_REGISTRY
        run = self.make_run(decision([step("sales")], send_query="나에게 메일", document={"format": "pdf", "topic": "매출"}))
        run["snapshot"]["doc_cfg"] = {"format": "pdf", "topic": "매출", "style": "report", "length": 2, "source": "context"}
        order = []
        async def make_doc(*a, **kw):
            order.append("document")
            self.assertFalse(run["snapshot"]["actions"])
            self.assertEqual(run["snapshot"]["report"], "완성된 보고서")
            yield {"type": "doc_meta", "doc_id": "doc_test", "format": "pdf", "filename": "report.pdf"}
            yield {"type": "done"}
        probe = {"status": "answer", "extras": {"action_draft": {"kind": "mail.action.compose", "payload": {"to": "self"}}}}
        final = {"kind": "mail.action.compose", "payload": {"to": "self", "body": "완성된 보고서"}, "summary": "메일"}
        with patch.dict(AGENT_REGISTRY["data"], {"run": AsyncMock(return_value={"status": "answer", "text": "매출"})}), \
             patch("app.agents.groupware.run", AsyncMock(return_value=probe)), \
             patch("app.agents.groupware.build_batch_delivery", return_value=final), \
             patch.object(artifact_execution.docgen, "run_docgen", make_doc):
            events = await collect(conversation.drive(run, self.chat, [], None))
        self.assertEqual(order, ["document"])
        action = db.get_action(next(e["action_id"] for e in events if e["type"] == "confirm"))
        self.assertEqual(action["payload"]["artifacts"][0]["id"], "doc_test")
        self.assertLess(next(i for i,e in enumerate(events) if e["type"] == "doc_meta"), next(i for i,e in enumerate(events) if e["type"] == "confirm"))
        self.assertEqual(store.get(run["id"])["state"], "needs_confirmation")

    async def test_completed_document_recovery_reuses_artifact_without_generation(self):
        run = self.make_run(decision())
        run["snapshot"]["building_artifact"] = {"id": "doc_test", "format": "pdf", "filename": "report.pdf"}
        doc = {"status": "done", "format": "pdf", "filename": "report.pdf", "topic": "매출", "style": "report", "total": 2}
        with patch.object(artifact_execution.docgen, "get_doc", return_value=doc), \
             patch.object(artifact_execution.docgen, "build_file") as build, \
             patch.object(artifact_execution.docgen, "list_pages", return_value=[]), \
             patch.object(artifact_execution.docgen, "run_docgen") as generator:
            events = await collect(artifact_execution.document_events(self.chat, {"source": "context"}, run))
        generator.assert_not_called()
        build.assert_called_once_with("doc_test")
        self.assertEqual(events[-1]["artifact"]["id"], "doc_test")
        self.assertEqual(store.get(run["id"])["snapshot"]["artifact"]["id"], "doc_test")

    async def test_workflow_file_chain_defers_confirmation_and_stops_on_doc_error(self):
        cfg = {"format": "pdf", "topic": "매출", "style": "report", "length": 2, "source": "context"}
        async def flow_events(*a, checkpoint_run, **kw):
            snap = checkpoint_run["snapshot"]
            snap.update({"pending_sends": [{"query": "나에게"}], "answer": {"text": "보고서"}, "context": [], "flow_source": "워크플로우"})
            yield {"type": "done", "docgen": cfg}
        for failed in (False, True):
            run = store.create(self.chat["id"], {"kind": "workflow", "flow": {}, "message": "q", "actor": "", "eff": None, "results": {}})
            async def make_doc(*a, **kw):
                confirm.assert_not_called()
                yield {"type": "doc_meta", "doc_id": "doc_flow", "format": "pdf", "filename": "flow.pdf"}
                yield {"type": "error", "detail": "파일 실패"} if failed else {"type": "done"}
            action_id = db.create_action(self.chat["id"], "mail.action.compose", {"to": "self"}, "메일")
            with patch.object(flows, "run_flow", flow_events), \
                 patch.object(flows, "_flow_send_confirm", AsyncMock(return_value={"type": "confirm", "action_id": action_id})) as confirm, \
                 patch.object(artifact_execution.docgen, "run_docgen", make_doc):
                events = await collect(artifact_execution.workflow_run({}, self.chat, "q", "", run))
            self.assertFalse(any(e.get("docgen") for e in events))
            if failed:
                confirm.assert_not_called()
                self.assertEqual(store.get(run["id"])["state"], "interrupted")
            else:
                confirm.assert_called_once()
                self.assertEqual(db.get_action(action_id)["payload"]["artifacts"][0]["id"], "doc_flow")

    async def test_permission_change_blocks_confirm_and_resume(self):
        from app import actions_api
        from fastapi import HTTPException
        run = self.make_run(decision([step("sales")]))
        event = conversation.confirm_event(run, "sales", {"kind": "todo.action.create", "payload": {"title": "x"}, "summary": "x"})
        changed = {"menus": {}}
        with patch("app.pipeline._resolve_eff", return_value=changed), patch.object(actions_api.groupware_agent, "execute_action") as executor:
            with self.assertRaises(HTTPException) as err:
                await actions_api.confirm_action(event["action_id"])
            self.assertEqual(err.exception.status_code, 403)
            events = await collect(conversation.drive(store.get(run["id"]), self.chat, [], changed))
        executor.assert_not_called()
        self.assertEqual(events[-1]["type"], "error")

    async def test_explore_does_not_consume_main_chat_question(self):
        from app import pipeline
        run = self.make_run(decision([step("sales")], clarify={"question": "기간?", "options": [], "slots": [{"key": "period", "target": "task", "task_id": "sales"}]}))
        conversation.question_event(run)
        with patch.object(pipeline, "_judge_intent", return_value=decision()), patch.object(answers, "_stream_answer", aggregate):
            await collect(pipeline.run_pipeline(self.chat, "탐색 질문", "사내", execution_lane="explore"))
        self.assertEqual(store.pending(self.chat["id"])["id"], run["id"])
        self.assertEqual(store.get(run["id"])["state"], "needs_input")

    async def test_document_settings_api_resumes_original_plan_and_marks_card_answered(self):
        from app import docgen_api, background_execution
        cfg = {"format": "pdf", "topic": "매출", "style": "report", "length": 2, "source": "context"}
        run = self.make_run(decision([step("sales")], document={"format": "pdf", "topic": "매출"}))
        events = await collect(conversation.drive(run, self.chat, [], None))
        self.assertEqual(events[-1]["type"], "docgen")
        captured = []
        async def resumed(saved):
            captured.append(saved)
            yield {"type": "done"}
        with patch.object(conversation, "resume_events", resumed):
            response = await docgen_api.run(docgen_api.RunIn(chat_id=self.chat["id"], message="파일", resume_id=run["id"], **cfg))
            server_run = runs.get(self.chat["id"])
            await server_run.task
            runs._evict(server_run)
        self.assertEqual(captured[0]["snapshot"]["decision"]["steps"][0]["id"], "sales")
        card = next(m for m in db.list_messages(self.chat["id"]) if (m.get("meta") or {}).get("kind") == "docgen_settings")
        self.assertTrue(card["meta"]["answered"])

    async def test_linked_action_api_starts_continuation_with_confirmed_result(self):
        from app import actions_api
        run = self.make_run(decision([step("todo", "groupware"), step("sales", deps=["todo"])]))
        card = conversation.confirm_event(run, "todo", {"kind": "todo.action.create", "payload": {"title": "x"}, "summary": "x"})
        saved = []
        async def resume(r):
            saved.append(r)
            yield {"type": "done"}
        with patch.object(actions_api.groupware_agent, "execute_action", return_value="할 일 생성 완료"), \
             patch.object(conversation, "resume_events", resume):
            response = await actions_api.confirm_action(card["action_id"])
            background = runs.get(self.chat["id"])
            await background.task
            runs._evict(background)
        self.assertEqual(response["resume_chat_id"], self.chat["id"])
        self.assertEqual(saved[0]["snapshot"]["results"]["todo"]["text"], "할 일 생성 완료")
        self.assertEqual(state(saved[0]["snapshot"]["results"]["todo"]), "completed")

    async def test_chat_deletion_removes_only_its_checkpoints_and_effects(self):
        from app import chats_api
        run = self.make_run(decision())
        other_chat = db.create_chat("other", "사내")
        other = store.create(other_chat["id"], {})
        action = db.create_action(self.chat["id"], "todo.action.create", {}, "x")
        store.link_action(action, run["id"], "todo")
        store.effect_claim("action:" + action)
        store.effect_claim(run["id"] + ":connector")
        store.effect_claim(other["id"] + ":connector")
        await chats_api.remove_chat(self.chat["id"])
        self.assertIsNone(store.get(run["id"]))
        self.assertIsNone(store.action_link(action))
        self.assertIsNone(store.effect_get("action:" + action))
        self.assertIsNone(store.effect_get(run["id"] + ":connector"))
        self.assertIsNotNone(store.effect_get(other["id"] + ":connector"))
        self.assertIsNotNone(store.get(other["id"]))

    async def test_background_trace_keeps_workflow_stages_separate_from_document(self):
        from app.background_execution import trace_events
        report = db.add_message(self.chat["id"], "assistant", "보고서")
        document = db.add_message(self.chat["id"], "assistant", "파일", {"kind": "doc"})
        async def producer():
            yield {"type": "task_tree", "tasks": [{"id": "data", "label": "데이터"}], "stages": [{"no": 1, "tasks": ["매출"]}]}
            yield {"type": "stage_status", "stage": 1, "status": "done"}
            yield {"type": "done", "message_id": report}
            yield {"type": "segment_start", "doc": {"format": "pdf"}}
            yield {"type": "done", "message_id": document}
        await collect(trace_events(producer()))
        messages = {m["id"]: m for m in db.list_messages(self.chat["id"])}
        self.assertEqual(messages[report]["meta"]["trace"]["stages"][0]["no"], 1)
        self.assertEqual(messages[report]["meta"]["trace"]["lines"][0]["t"], "stage")
        self.assertNotIn("trace", messages[document]["meta"])
