"""메인 채팅의 엠코스메틱 조회 → 취합 → Outlook 확인 카드. 모델·전송만 모의, DB는 격리한다."""
import copy
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from test_mcmail_wiring import WorkEmailBase, mcp_transport
from app import (answers, db, execution_store, mcmail_link, pipeline,
                 request_planning, requirements)
from app.agents import work


class McMailDeliveryTests(WorkEmailBase):
    def setUp(self):
        super().setUp()
        self.chat = db.create_chat("인보이스 메일 전달", "사내")
        self.target = "invoices"
        self.lookup = "고객 인보이스 정보 조회"
        self.send_query = "내 메일로 보내줘"
        self.worker_plan = None
        self.model_calls = []
        self.aggregated = []
        self.stack.enter_context(patch("app.llm.generate", side_effect=self.model))
        self.stack.enter_context(patch("app.llm.generate_calls", return_value={
            "calls": [{"name": "compose_mail", "args": {}}]}))
        self.stack.enter_context(patch("app.smart_actions.get_config", return_value={"mail": {"enabled": True}}))
        self.stack.enter_context(patch.object(work, "_plan_lists", side_effect=AssertionError("read-only plans need no action candidates")))
        self.stack.enter_context(patch.object(answers, "_aggregate_answer", self.aggregate))
        self.email_send = self.stack.enter_context(patch("app.mcmail.send", side_effect=AssertionError("no send")))
        self.mail_send = self.stack.enter_context(patch("app.smart_seed.mail_send", side_effect=AssertionError("no send")))
        self.order = self.stack.enter_context(patch("app.mcmail.create_order", side_effect=AssertionError("no order")))

    def model(self, messages, *, system, **kwargs):
        self.model_calls.append((system, copy.deepcopy(messages)))
        if system == requirements.SYSTEM:
            def item(rid, kind, request, source="", deps=()):
                return {"id": rid, "kind": kind, "request": request, "source_hint": source,
                        "constraints": [], "depends_on": list(deps)}
            return {"version": 1, "query": messages[-1]["content"], "items": [
                item("lookup", "retrieve", self.lookup, "M코스메틱"),
                item("report", "answer", "조회 결과 취합", deps=["lookup"]),
                item("send", "delivery", self.send_query, deps=["report"])]}
        if system == request_planning.ROUTING_SYSTEM:
            catalog = json.loads(messages[-1]["content"])["capabilities"]
            ids = {r["id"] for r in catalog}
            self.assertIn("agent:work:email", ids)
            self.assertIn("agent:groupware", ids)
            self.assertNotIn("agent:work:edu", ids)
            return {"routes": [
                {"requirement_id": "lookup", "candidates": ["agent:work:email"]},
                {"requirement_id": "send", "candidates": ["delivery:groupware"]}]}
        if request_planning.PLAN_RULES in system:
            return {"version": 3, "query": "조회 후 전달", "steps": [
                {"id": "invoice", "agent": "work", "worker": "email", "task": self.lookup,
                 "depends_on": [], "inputs": {}}],
                "send_query": self.send_query, "document": None, "clarify": None,
                "use_previous": False, "web": False,
                "coverage": {"lookup": ["invoice"], "report": ["$answer"], "send": ["$delivery"]}}
        if system.startswith(work.PLAN_SYSTEM):
            self.assertIn("상위 실행 계획이 이 호출을 조회 작업으로 확정", system)
            # The worker receives its own requirement, not the report/delivery instructions.
            self.assertNotIn("Outlook", messages[-1]["content"])
            self.assertNotIn("내 메일로 보내", messages[-1]["content"])
            return copy.deepcopy(self.worker_plan or {
                "agent": "email", "kind": "query", "queries": [{"target": self.target}]})
        raise AssertionError("unexpected model phase")

    async def aggregate(self, chat_id, source, context, results, **kwargs):
        self.aggregated.append(copy.deepcopy(results))
        body = "고객 업무 조회 보고서\n" + "\n".join(
            r.get("text") or r.get("fail_reason", "") for r in results.values())
        yield {"type": "token", "text": body}
        yield {"type": "done"}

    async def ask_pipeline(self, question, **kwargs):
        opts = {"agents": ["work", "groupware"], "scope_files": {"work": True, "workers": ["email"]}}
        opts.update(kwargs)
        return [e async for e in pipeline.run_pipeline(self.chat, question, "사내", **opts)]

    def assert_delivery(self, events):
        self.assertFalse([e for e in events if e["type"] == "error"], events)
        confirms = [e for e in events if e["type"] == "confirm"]
        self.assertEqual(len(confirms), 1, events)
        event = confirms[0]
        action = db.get_action(event["action_id"])
        self.assertEqual(action["kind"], "mail.action.compose")
        self.assertEqual(action["status"], "pending")
        self.assertEqual(action["payload"]["to"], "나")
        self.assertIn(self.aggregated[-1]["invoice"]["text"], action["payload"]["body"])
        self.assertEqual(self.tools_called(), ["get_work_status"])
        self.assertEqual(self.aggregated[-1]["invoice"]["extras"]["auto_lookups"], [self.target])
        url = urlparse(event["open_urls"][0])
        self.assertEqual((url.hostname, url.path), ("outlook.office.com", "/mail/deeplink/compose"))
        self.assertIn("고객 업무 조회 보고서", parse_qs(url.query)["body"][0])
        self.email_send.assert_not_called()
        self.mail_send.assert_not_called()
        self.order.assert_not_called()
        return event

    async def test_invoice_lookup_joins_groupware_confirmation_without_customer_or_date(self):
        events = await self.ask_pipeline("고객 인보이스 정보를 모아서 내 메일로 보내줘")
        event = self.assert_delivery(events)
        run = execution_store.get(event["resume_id"])
        self.assertEqual(run["state"], "needs_confirmation")
        self.assertEqual(run["snapshot"]["scope_files"]["workers"], ["email"])
        self.assertEqual(len(self.model_calls), 4)

    async def test_order_information_is_read_not_order_registration(self):
        self.target, self.lookup = "orders", "고객 주문등록 정보 조회"
        self.worker_plan = {"agent": "email", "kind": "action", "action": "order", "email_id": "E-1005",
                            "targets": ["orders"]}
        events = await self.ask_pipeline("주문 등록 정보를 취합해서 내 메일로 보내줘")
        self.assert_delivery(events)

    async def test_recipient_card_resumes_original_selection_after_composer_reset(self):
        self.send_query = "Outlook으로 보내줘"
        events = await self.ask_pipeline("고객 인보이스 정보를 모아서 Outlook으로 보내줘")
        question = next(e for e in events if e["type"] == "clarify")
        self.assertEqual(self.tools_called(), [])
        self.assertEqual(self.aggregated, [])
        rid = question["card"]["resume_id"]
        # Simulate refresh: the composer has lost all current selection.
        events = await self.ask_pipeline("나에게 보내줘", agents=[], scope_files={}, resume_id=rid)
        confirmation = self.assert_delivery(events)
        self.assertEqual(confirmation["resume_id"], rid)
        run = execution_store.get(rid)
        self.assertEqual(run["snapshot"]["allowed_agents"], ["work", "groupware"])
        self.assertEqual(run["snapshot"]["decision"]["steps"][0]["worker"], "email")
        self.assertEqual(sum(system == requirements.SYSTEM for system, _ in self.model_calls), 1)
        cards = [m for m in db.list_messages(self.chat["id"]) if (m.get("meta") or {}).get("kind") == "clarify"]
        self.assertTrue(cards[0]["meta"]["answered"])

    async def test_failed_mcp_lookup_does_not_offer_delivery(self):
        with patch.object(mcmail_link, "TRANSPORT", mcp_transport(refuse=True)):
            events = await self.ask_pipeline("인보이스 정보를 모아서 내 메일로 보내줘")
        self.assertFalse(any(e["type"] == "confirm" for e in events), events)
        self.assertEqual(self.aggregated[-1]["invoice"]["status"], "failed")
        self.email_send.assert_not_called()
        self.mail_send.assert_not_called()
        with db._conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0], 0)

    async def test_invoice_clarification_resumes_only_that_lookup_then_delivery(self):
        self.worker_plan = {"queries": [], "clarification": "어느 고객사의 인보이스를 조회할까요?"}
        events = await self.ask_pipeline("그 고객의 인보이스 정보를 내 메일로 보내줘")
        card = next(e for e in events if e["type"] == "clarify")["card"]
        self.assertEqual(self.tools_called(), [])
        self.worker_plan = {"agent": "email", "kind": "query", "queries": [
            {"target": "invoices", "filters": {"customer": "누리뷰티 02"}}]}
        events = await self.ask_pipeline("누리뷰티", resume_id=card["resume_id"])
        self.assert_delivery(events)
        self.assertEqual(self.aggregated[-1]["invoice"]["extras"]["auto_evidence"][0]["filters"]["customer"], "누리뷰티 02")

    def test_worker_selection_blocks_before_planning_and_mcp_access(self):
        with patch.object(work, "_plan", side_effect=AssertionError("must not plan")):
            for selection in (["edu"], [], "email", [{"bad": "email"}]):
                with self.subTest(selection=selection):
                    result = work._run_sync("인보이스 조회", [], scope_files={"workers": selection}, worker="email")
                    self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.tools_called(), [])


if __name__ == "__main__":
    unittest.main()
