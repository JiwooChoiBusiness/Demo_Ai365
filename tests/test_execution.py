import asyncio
import unittest
from contextlib import aclosing

from app.execution import Task, PlanError, execute, stream_task, validate_tasks
from app.planning import normalize_plan, validate_intent


class PlanningTests(unittest.TestCase):
    def test_legacy_chain_preserves_all_predecessors(self):
        plan = normalize_plan({"steps": [{"agent": a, "task": a} for a in ("knowledge", "data", "knowledge")]})
        self.assertEqual(plan["steps"][2]["depends_on"], ["s1", "s2"])

    def test_groupware_and_connector_are_valid_dependencies(self):
        plan = normalize_plan({"steps": [
            {"id": "person", "agent": "groupware", "task": "사람 조회", "depends_on": []},
            {"id": "erp", "agent": "connector", "connector_id": "cn_1", "task": "ERP 조회",
             "depends_on": ["person"], "inputs": {"name": {"from": "person", "path": ["text"]}}}
        ]}, connector_ids={"cn_1"})
        self.assertEqual(len(plan["steps"]), 2)

    def test_invalid_graphs_are_rejected_before_calls(self):
        graphs = [
            [Task("a", "data", "a"), Task("a", "data", "b")],
            [Task("a", "data", "a", ("missing",))],
            [Task("a", "data", "a", ("a",))],
            [Task("a", "data", "a", ("b",)), Task("b", "data", "b", ("a",))],
            [Task("a", "data", "a", inputs={"x": {"from": "missing"}})],
        ]
        for graph in graphs:
            with self.subTest(graph=graph), self.assertRaises(PlanError):
                validate_tasks(graph)

    def test_rejects_unknown_agent_without_dropping_step(self):
        with self.assertRaises(PlanError):
            normalize_plan({"steps": [{"agent": "unknown", "task": "a"}]})

    def test_rejects_unconnected_connector(self):
        with self.assertRaises(PlanError):
            normalize_plan({"steps": [{"agent": "connector", "task": "a", "connector_id": "cn_other"}]}, connector_ids={"cn_1"})

    def test_selected_agents_are_constraints(self):
        with self.assertRaises(PlanError):
            normalize_plan({"steps": [{"agent": "data", "task": "a"}]}, allowed_agents={"knowledge"})

    def test_invalid_intent_shapes(self):
        cases = [[], {"parallel": "false"}, {"route": "data"}, {"refined_query": []},
                 {"route": ["data"], "clarify": {"question": "?"}},
                 {"connectors": ["not_connected"]}]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(PlanError):
                validate_intent(case, connector_ids=set())

    def test_plan_and_external_routes_cannot_silently_diverge(self):
        with self.assertRaises(PlanError):
            validate_intent({"plan": {"steps": [{"agent": "data", "task": "a"}]},
                             "connectors": ["cn_1"]}, connector_ids={"cn_1"})


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, tasks, run, **kwargs):
        return [e async for e in execute(tasks, run, **kwargs)]

    async def test_parallel_then_join_with_exact_dependencies(self):
        ready = set()
        together = asyncio.Event()
        calls = []
        async def run(task, deps, inputs):
            calls.append(task.id)
            if task.id in ("a", "b"):
                ready.add(task.id)
                if len(ready) == 2:
                    together.set()
                await asyncio.wait_for(together.wait(), 1)
            if task.id == "c":
                self.assertEqual(set(deps), {"a", "b"})
            return {"status": "answer", "text": task.id}
        events = await self.collect([Task("a", "knowledge", "A"), Task("b", "work", "B"),
                                     Task("c", "data", "C", ("a", "b"))], run)
        self.assertEqual(calls, ["a", "b", "c"])
        self.assertEqual(sum(e["type"] == "finished" for e in events), 3)

    async def test_ready_branch_does_not_wait_for_unrelated_slow_task(self):
        release = asyncio.Event()
        async def run(task, deps, inputs):
            if task.id == "slow":
                await asyncio.wait_for(release.wait(), 1)
            if task.id == "child":
                self.assertEqual(set(deps), {"fast"})
                release.set()
            return {"status": "answer", "text": task.id}
        await self.collect([Task("slow", "data", ""), Task("fast", "data", ""),
                            Task("child", "data", "", ("fast",))], run)

    async def test_failed_prerequisite_blocks_only_dependents(self):
        calls = []
        async def run(task, deps, inputs):
            calls.append(task.id)
            return {"status": "not_found" if task.id == "a" else "answer", "text": task.id}
        events = await self.collect([Task("a", "data", ""), Task("b", "data", "", ("a",)),
                                     Task("c", "data", "")], run)
        self.assertEqual(set(calls), {"a", "c"})
        blocked = next(e["result"] for e in events if e["type"] == "finished" and e["task"].id == "b")
        self.assertTrue(blocked["extras"]["blocked"])

    async def test_confirm_is_not_completed_action(self):
        calls = []
        async def run(task, deps, inputs):
            calls.append(task.id)
            return {"status": "answer", "extras": {"action_draft": {"kind": "test"}}}
        await self.collect([Task("a", "work", ""), Task("b", "data", "", ("a",))], run)
        self.assertEqual(calls, ["a"])

    async def test_structured_input_binding_preserves_types(self):
        async def run(task, deps, inputs):
            if task.id == "a":
                return {"status": "answer", "extras": {"rows": [{"quantity": 0}]}}
            self.assertEqual(inputs, {"quantity": 0})
            return {"status": "answer"}
        await self.collect([Task("a", "data", ""), Task("b", "connector", "", ("a",),
                            inputs={"quantity": {"from": "a", "path": ["extras", "rows", 0, "quantity"]}})], run)

    async def test_missing_binding_does_not_call_tool(self):
        calls = []
        async def run(task, deps, inputs):
            calls.append(task.id)
            return {"status": "answer", "extras": {}}
        await self.collect([Task("a", "data", ""), Task("b", "connector", "", ("a",),
                            inputs={"sku": {"from": "a", "path": ["missing"]}})], run)
        self.assertEqual(calls, ["a"])

    async def test_after_only_orders_but_does_not_require_success(self):
        calls = []
        async def run(task, deps, inputs):
            calls.append(task.id)
            self.assertFalse(deps)
            return {"status": "not_found"}
        await self.collect([Task("a", "data", ""), Task("b", "data", "", after=("a",))], run)
        self.assertEqual(calls, ["a", "b"])

    async def test_cancellation_does_not_launch_downstream(self):
        calls, cancelled = [], asyncio.Event()
        async def run(task, deps, inputs):
            calls.append(task.id)
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        async def consume():
            async with aclosing(execute([Task("a", "data", ""), Task("b", "data", "", ("a",))], run)) as stream:
                async for event in stream:
                    pass
        consumer = asyncio.create_task(consume())
        while not calls:
            await asyncio.sleep(0)
        consumer.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await consumer
        self.assertTrue(cancelled.is_set())
        self.assertEqual(calls, ["a"])

    async def test_streaming_node_preserves_event_contract(self):
        expected = [{"type": "doc_meta", "doc_id": "doc_test"}, {"type": "doc_page", "idx": 1}, {"type": "done"}]
        async def produce():
            for e in expected:
                yield e
        self.assertEqual([e async for e in stream_task(Task("doc", "docgen", ""), produce)], expected)

    async def test_streaming_node_failure_is_error_event(self):
        async def produce():
            yield {"type": "doc_meta"}
            raise RuntimeError("simulated failure")
        with self.assertLogs("ai365.execution", level="ERROR"):
            events = [e async for e in stream_task(Task("doc", "docgen", ""), produce)]
        self.assertEqual([e["type"] for e in events], ["doc_meta", "error"])

    async def test_stream_producer_cancellation_terminates_consumer(self):
        async def produce():
            yield {"type": "doc_meta"}
            raise asyncio.CancelledError()
        async def consume():
            return [e async for e in stream_task(Task("doc", "docgen", ""), produce)]
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(consume(), timeout=1)

    async def test_stream_closing_cancels_work(self):
        cancelled = asyncio.Event()
        async def produce():
            try:
                yield {"type": "doc_meta"}
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        stream = stream_task(Task("doc", "docgen", ""), produce)
        await anext(stream)
        await asyncio.wait_for(stream.aclose(), 1)
        self.assertTrue(cancelled.is_set())


if __name__ == "__main__":
    unittest.main()
