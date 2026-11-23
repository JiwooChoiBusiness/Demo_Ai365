"""실제 LLM·API·사용자 DB 없이 기존 진입점과 SSE 계약을 검증한다."""
import asyncio
import unittest
from db_fixture import isolate_db
from contextlib import ExitStack
from unittest.mock import AsyncMock, Mock, patch

from app import answers, docgen, flows, intent, pipeline
from app.agents import AGENT_REGISTRY
from app.execution import PlanError
from app.planning import normalize_plan
from app.run_context import with_material
from app.task_runner import run_tasks
from app.tool_runtime import call_connector


async def collect(stream):
    return [event async for event in stream]


async def aggregate_stub(*args, **kwargs):
    yield {"type": "answer_head", "source": "사내"}
    yield {"type": "token", "text": "통합 답변"}
    yield {"type": "done", "message_id": "test"}


class RefactorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        # 미지정 경로가 실제 서비스/DB에 도달하면 즉시 실패한다.
        self.stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")))
        self.stack.enter_context(patch("app.llm.stream", side_effect=AssertionError("unexpected stream")))
        self.stack.enter_context(patch("app.flow_api_call.call", side_effect=AssertionError("unexpected HTTP")))
        self.stack.enter_context(patch("app.db.add_message", return_value="message-test"))
        self.stack.enter_context(patch("app.db.list_messages", return_value=[]))
        self.stack.enter_context(patch.object(pipeline, "_resolve_eff", return_value=None))
        self.stack.enter_context(patch.object(pipeline, "_build_context", side_effect=lambda cid, msg, lane="chat": [{"role": "user", "content": msg}]))
        self.stack.enter_context(patch.object(pipeline, "_await_send_state", return_value=None))
        self.stack.enter_context(patch.object(pipeline, "_docgen_match", return_value=None))
        for name in AGENT_REGISTRY:
            self.stack.enter_context(patch.dict(AGENT_REGISTRY[name], {"run": AsyncMock(return_value={"status": "answer", "text": name, "extras": {}})}))

    async def test_legacy_sequential_run_passes_previous_result(self):
        results = {}
        await collect(answers._run_agents(["knowledge", "data"], False, "조회 후 분석", [], results))
        query = AGENT_REGISTRY["data"]["run"].call_args.args[0]
        self.assertIn("knowledge", query)
        self.assertEqual(set(results), {"knowledge", "data"})

    async def test_same_agent_tasks_keep_distinct_results_and_one_ui_card(self):
        steps = normalize_plan({"steps": [
            {"id": "a", "agent": "data", "task": "매출", "depends_on": []},
            {"id": "b", "agent": "data", "task": "비용", "depends_on": []}]})["steps"]
        results = {}
        events = await collect(run_tasks(steps, [], results))
        self.assertEqual(list(results), ["a", "b"])
        self.assertEqual([c["id"] for c in events[0]["tasks"]], ["data"])
        self.assertEqual([e["status"] for e in events if e["type"] == "agent_status"], ["running", "done"])
        self.assertEqual(AGENT_REGISTRY["data"]["run"].call_count, 2)

    async def test_connector_result_can_feed_agent_and_another_connector(self):
        steps = normalize_plan({"steps": [
            {"id": "sku", "agent": "connector", "connector_id": "cn_a", "task": "제품 검색", "depends_on": []},
            {"id": "stock", "agent": "connector", "connector_id": "cn_b", "task": "재고 조회", "depends_on": ["sku"],
             "inputs": {"sku": {"from": "sku", "path": ["extras", "connector", "outputs", "sku"]}}},
            {"id": "analysis", "agent": "data", "task": "재고 분석", "depends_on": ["stock"]}]})["steps"]
        calls = []
        async def connector(c, query, actor, inputs):
            calls.append((c["id"], inputs))
            return {"status": "answer", "text": "재고 35", "extras": {"connector": {"outputs": {"sku": "S-1"}}}}
        with patch("app.task_runner.run_connector", side_effect=connector):
            results = {}
            await collect(run_tasks(steps, [], results, connectors=[{"id": "cn_a"}, {"id": "cn_b"}]))
        self.assertEqual(calls, [("cn_a", {}), ("cn_b", {"sku": "S-1"})])
        self.assertIn("재고 35", AGENT_REGISTRY["data"]["run"].call_args.args[0])

    async def test_missing_connector_input_never_calls_api(self):
        connector = {"kind": "action", "api": {"url": "https://example.invalid/{{input.sku}}"}}
        with self.assertRaises(PlanError):
            await call_connector(connector, "query", "", {})

    async def test_read_connector_keeps_empty_filter_contract(self):
        connector = {"kind": "read", "api": {"url": "https://example.invalid/{{input.sku}}"}}
        with patch("app.flow_api_call.call", return_value={"ok": True}) as call:
            self.assertEqual(await call_connector(connector, "query", "", {}), {"ok": True})
        call.assert_called_once()

    async def test_explicit_agents_still_use_planner(self):
        plan = normalize_plan({"steps": [{"agent": "knowledge", "task": "규정"}, {"agent": "data", "task": "분석"}]})
        with patch.object(pipeline, "_judge_intent", return_value={"plan": plan}) as judge, \
             patch.object(answers, "_aggregate_answer", aggregate_stub):
            await collect(pipeline.run_pipeline({"id": "c"}, "규정으로 분석", "사내", agents=["knowledge", "data"]))
        self.assertEqual(judge.call_args.args[2], ["knowledge", "data"])
        self.assertIn("knowledge", AGENT_REGISTRY["data"]["run"].call_args.args[0])

    async def test_collection_context_reaches_planner_and_agent(self):
        with patch.object(pipeline, "_judge_intent", return_value={"route": ["knowledge"]}) as judge, \
             patch.object(pipeline, "_aggregate_answer", aggregate_stub):
            await collect(pipeline.run_pipeline({"id": "c"}, "질문", "사내", instructions="컬렉션 전용 규정"))
        self.assertIn("컬렉션 전용 규정", str(judge.call_args.args[0]))
        self.assertIn("컬렉션 전용 규정", str(AGENT_REGISTRY["knowledge"]["run"].call_args.args[1]))
        self.assertEqual(judge.call_args.args[0][-1]["content"], "질문")

    async def test_invalid_planner_output_does_not_become_direct_answer(self):
        with patch.object(pipeline, "_judge_intent", side_effect=PlanError("bad plan")):
            with self.assertLogs("ai365.pipeline", level="ERROR"):
                events = await collect(pipeline.run_pipeline({"id": "c"}, "조회", "사내"))
        self.assertEqual(events[-1]["type"], "error")
        AGENT_REGISTRY["knowledge"]["run"].assert_not_called()

    async def test_external_path_still_skips_planner(self):
        with patch.object(pipeline, "_judge_intent") as judge, patch.object(pipeline, "_run_external", aggregate_stub):
            # 위젯 낱말(환율 · 날씨 · 맛집)은 위젯이 먼저 가로채므로 무관한 질문으로 외부 경로를 본다(2026-10-06)
            # Widget words (exchange rate, weather, places) are intercepted first, so an unrelated question exercises the external path
            events = await collect(pipeline.run_pipeline({"id": "c"}, "최신 뉴스", "외부"))
        judge.assert_not_called()
        self.assertEqual(events[-1]["type"], "done")

    async def test_docgen_detection_retains_settings_event(self):
        with patch.object(pipeline, "_judge_intent", return_value={"docgen": {"format": "pptx", "topic": "교육"}}) as judge:
            events = await collect(pipeline.run_pipeline({"id": "c"}, "PPT 만들어줘", "사내"))
        self.assertEqual(events[-1]["type"], "docgen")
        judge.assert_called_once()

    async def test_failed_plan_prevents_send_but_returns_partial_answer(self):
        AGENT_REGISTRY["knowledge"]["run"].return_value = {"status": "not_found", "text": "", "extras": {}}
        plan = normalize_plan({"steps": [{"agent": "knowledge", "task": "규정"}, {"agent": "data", "task": "분석"}], "send_query": "나에게"})
        probe = {"status": "answer", "extras": {"action_draft": {"kind": "mail.action.compose", "payload": {"to": "self"}}}}
        with patch.object(answers, "_deliver_answer") as send, patch.object(answers, "_aggregate_answer", aggregate_stub), \
             patch("app.agents.groupware.run", AsyncMock(return_value=probe)):
            events = await collect(answers._plan_answer("c", "사내", [], plan, "", None, None))
        send.assert_not_called()
        AGENT_REGISTRY["data"]["run"].assert_not_called()
        self.assertTrue(any(e["type"] == "done" for e in events))
        self.assertEqual(events[-1]["state"], "failed")

    async def test_recipient_resume_reuses_completed_connector_results(self):
        result = {"connector:x": {"status": "answer", "text": "already executed", "agent": "connector", "extras": {}}}
        state = {"await_recipient": True, "send_query": "메일 발송", "content_results": result, "content_eff": None}
        seen = []
        async def deliver(*args, **kwargs):
            seen.append(args[3])
            yield {"type": "confirm", "action_id": "test", "summary": "발송"}
        with patch.object(pipeline, "_await_send_state", return_value=state), \
             patch.object(pipeline, "_recipientish", return_value=True), patch.object(pipeline, "_deliver_answer", deliver), \
             patch.object(pipeline, "_judge_intent") as judge:
            await collect(pipeline.run_pipeline({"id": "c"}, "나에게", "사내"))
        judge.assert_not_called()
        self.assertEqual(seen, [result])

    async def test_workflow_parallel_stage_and_serial_stages_keep_events(self):
        flow = {"id": "f", "name": "테스트", "stages": [
            {"nodes": [{"agent": "knowledge", "resources": [], "instruction": "A"},
                       {"agent": "data", "resources": [], "instruction": "B"}]},
            {"nodes": [{"agent": "data", "resources": [], "instruction": "C"}]}]}
        ready, barrier, calls, received = set(), asyncio.Event(), [], []
        async def node(n, msg, ctx, eff, prior, actor):
            name = n["instruction"]
            calls.append(name)
            if name in ("A", "B"):
                ready.add(name)
                if len(ready) == 2:
                    barrier.set()
                await asyncio.wait_for(barrier.wait(), 1)
            else:
                # Capture outside the worker: the executor deliberately catches worker exceptions.
                # Stage reports also appear in prior; only task results have a node number.
                received.extend((p["node"], p["text"]) for p in prior if p.get("node"))
            return {"status": "done", "text": name, "label": name}
        async def tokens(*args, **kwargs):
            yield "결과"
        async def smooth(text):
            yield text
        with patch.object(flows, "_resolve_eff", return_value=None), \
             patch.object(flows, "_build_context", return_value=[{"role": "user", "content": "테스트"}]), \
             patch.object(flows, "_run_step_node", side_effect=node), \
             patch.object(flows, "_flow_sources", return_value=None), patch.object(flows, "_astream", tokens), \
             patch.object(flows, "_smooth", smooth):
            events = await collect(flows.run_flow(flow, {"id": "c"}, "테스트"))
        self.assertEqual(calls, ["A", "B", "C"])
        self.assertEqual(received, [(1, "A"), (2, "B")])
        stages = [(e["stage"], e["status"]) for e in events if e["type"] == "stage_status"]
        self.assertEqual(stages, [(1, "running"), (1, "done"), (2, "running"), (2, "done")])
        self.assertEqual(events[-1]["type"], "done")

    async def test_docgen_research_does_not_expand_selected_scope(self):
        found = await docgen._research_internal("규정", "질문", None, {"knowledge_files": ["selected.pdf"]}, "컬렉션")
        self.assertEqual([r["agent"] for r in found], ["knowledge"])
        AGENT_REGISTRY["data"]["run"].assert_not_called()
        self.assertIn("컬렉션", str(AGENT_REGISTRY["knowledge"]["run"].call_args.args[1]))

    async def test_docgen_wrapper_preserves_frontend_events(self):
        expected = [{"type": "doc_meta", "doc_id": "d"}, {"type": "done", "message_id": "m"}]
        async def gen(*args, **kwargs):
            for event in expected:
                yield event
        with patch.object(docgen, "_generate_document", gen):
            actual = await collect(docgen.run_docgen({"id": "c"}, "q", "pdf", "topic", "formal", 2))
        self.assertEqual(actual, expected)

    async def test_collection_material_is_used_by_file_generator(self):
        async def sheet(state, topic, n, material):
            self.assertIn("컬렉션 원문", material)
            return {"sheet_name": "Sheet", "columns": [], "rows": []}
        async def smooth(text):
            yield text
        with patch.object(docgen, "collection_material", return_value="컬렉션 원문"), \
             patch.object(docgen, "_create_doc", return_value="doc_test"), \
             patch.object(docgen, "_gen_sheet", side_effect=sheet), \
             patch.object(docgen, "_sheet_csv", return_value=""), \
             patch.object(docgen, "_add_page"), patch.object(docgen, "_set_status"), \
             patch.object(docgen, "build_file"), patch.object(docgen, "_smooth", smooth):
            events = await collect(docgen.run_docgen({"id": "c", "coll": "col"}, "표 생성", "xlsx", "topic", "blue", 5))
        self.assertTrue(any(e["type"] == "doc_page" for e in events))
        self.assertEqual(events[-1]["type"], "done")

    async def test_api_contracts_for_workflow_and_document_unchanged(self):
        import httpx
        from fastapi import FastAPI
        from app import docgen_api, flows_api
        app = FastAPI()
        app.include_router(docgen_api.router)
        app.include_router(flows_api.router)
        with patch("app.db.get_chat", return_value={"id": "c"}), \
             patch.object(flows, "find_flow", return_value={"id": "f"}), \
             patch.object(flows, "run_flow", aggregate_stub), patch.object(docgen, "run_docgen", aggregate_stub):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                doc = await client.post("/api/docgen/run", json={"chat_id": "c", "message": "q", "format": "pdf", "topic": "topic", "length": 2})
                flow = await client.post("/api/flows/run", json={"chat_id": "c", "flow_id": "f", "message": "q"})
        for response in (doc, flow):
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/event-stream", response.headers["content-type"])
            self.assertIn('"type": "done"', response.text)

    def test_sources_preserve_multiple_work_and_groupware_tasks(self):
        results = {"a": {"agent": "groupware", "status": "answer", "extras": {"gw": [{"title": "일정"}]}},
                   "b": {"agent": "work", "status": "answer", "extras": {"auto_agent": "email"}},
                   "c": {"agent": "work", "status": "answer", "extras": {"auto_agent": "edu"}}}
        source = answers._build_sources(results)
        self.assertEqual(source["groupware"]["resources"], 1)
        self.assertEqual(source["work"]["agents"], 2)

    def test_intent_repair_once_then_validated(self):
        from app.decisions import from_legacy
        spec = {"version": 1, "query": "규정", "items": [{"id": "r1", "kind": "retrieve", "request": "규정",
                "source_hint": "", "constraints": [], "depends_on": []}]}
        valid = from_legacy({"route": ["knowledge"]}, "규정")
        valid["coverage"] = {"r1": [valid["steps"][0]["id"]]}
        routes = {"routes": [{"requirement_id": "r1", "candidates": ["agent:knowledge"], "reason": "규정 검색"}]}
        with patch("app.llm.generate", side_effect=[spec, routes, {"parallel": "false"}, valid]) as generate:
            result = intent._judge_intent([{"role": "user", "content": "규정"}])
        self.assertEqual(result["steps"][0]["agent"], "knowledge")
        self.assertEqual(generate.call_count, 4)
        self.assertTrue(all(call.kwargs["tier"] == "main" for call in generate.call_args_list))

    def test_intent_repair_is_bounded(self):
        with patch("app.llm.generate", return_value={"parallel": "false"}) as generate, self.assertRaises(PlanError):
            intent._judge_intent([])
        self.assertEqual(generate.call_count, 2)


if __name__ == "__main__":
    unittest.main()
