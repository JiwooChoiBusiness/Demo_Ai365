"""엠코스메틱 질의 → MCP → 격리 저장소 → 답변 근거 통합. 실제 모델/네트워크/메일 발송 없음."""
import unittest
from unittest.mock import patch

from test_mcmail_wiring import WorkEmailBase
from app import capability_catalog, mcmail, mcmail_api, request_planning
from app.agents import work
from app.execution import PlanError


class McMailQualityTests(WorkEmailBase):
    def test_customer_does_not_replace_requested_business_type(self):
        result = self.ask("누리뷰티 견적 현황 알려줘", {"targets": ["quotes"]})
        self.assertEqual(result["status"], "answer")
        evidence = result["extras"]["auto_evidence"]
        self.assertEqual(result["extras"]["auto_lookups"], ["quotes"])
        self.assertEqual(evidence[0]["filters"]["customer"], "누리뷰티 02")
        data = evidence[0]["data"]
        self.assertTrue(data["rows"] or data["recentDone"])
        self.assertTrue(all(row["customer"] == "누리뷰티 02" for row in data["rows"] + data["recentDone"]))
        self.assertEqual(self.tools_called(), ["get_work_status"])

    def test_period_and_status_reach_the_mcp_store_and_count(self):
        result = self.ask("2026-10-01부터 2026-10-05까지 완료된 견적 메일 알려줘", {
            "queries": [{"target": "quotes", "filters": {
                "date_from": "2026-10-01", "date_to": "2026-10-05", "status": "done"}}]})
        self.assertEqual(result["status"], "answer", result)
        evidence = result["extras"]["auto_evidence"][0]
        self.assertEqual(evidence["filters"]["date_from"], "2026-10-01")
        self.assertEqual(evidence["filters"]["status"], "done")
        self.assertIn("2026-10-01", result["text"])
        self.assertEqual(evidence["data"]["counts"]["todo"], 0)
        self.assertNotIn("create_order", self.tools_called())
        self.assertNotIn("send_reply", self.tools_called())

    def test_multiple_mail_ids_are_read_without_running_actions(self):
        result = self.ask("E-1001과 E-1005의 메일 내용과 처리 상태를 각각 알려줘", {"targets": ["today"]})
        self.assertEqual(result["status"], "answer", result)
        self.assertEqual(self.tools_called(), ["get_mail", "get_mail"])
        self.assertIn("E-1001", result["text"])
        self.assertIn("E-1005", result["text"])
        self.assertEqual(self.mail("E-1005")["nextStep"]["k"], "order")

    def test_multiple_cases_do_not_drop_the_second_case(self):
        result = self.ask("RFQ-2026-00123과 RFQ-2026-00131 진행 상황을 각각 알려줘", {"targets": ["today"]})
        self.assertEqual(result["status"], "answer", result)
        self.assertEqual(self.tools_called(), ["get_work_status", "get_work_status"])
        self.assertIn("RFQ-2026-00123", result["text"])
        self.assertIn("RFQ-2026-00131", result["text"])

    def test_invalid_filters_ask_before_broad_unfiltered_lookup(self):
        result = self.ask("견적 현황을 알려줘", {"queries": [{"target": "quotes", "filters": {"quantity_min": 500}}]})
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(self.tools_called(), [])

    def test_agent_page_shares_the_same_customer_and_type_contract(self):
        with patch("app.llm.generate", return_value={"queries": [{"target": "quotes", "filters": {"customer": "누리뷰티 02"}}]}):
            answer, execution = mcmail_api._answer("누리뷰티 견적 현황 알려줘")
        self.assertIn("누리뷰티 02", answer)
        self.assertIn("견적", answer)
        self.assertEqual(execution["agent"], "email")
        self.assertEqual(len(execution["think"]["groups"]), 3)

    def test_permission_is_checked_before_reading_planner_mail_candidates(self):
        with patch.object(work, "_plan", side_effect=AssertionError("must not inspect mail candidates")):
            result = work._run_sync("메일 현황", [], {"nodes": {"agent_email": 0}}, worker="email")
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(self.tools_called(), [])


class McMailSourceTests(unittest.TestCase):
    def test_explicit_system_aliases_cannot_route_to_personal_mail(self):
        catalog = capability_catalog.build()
        for name in ("엠코스메틱", "MCosmetic", "M Cosmetic"):
            spec = {"items": [{"id": "r1", "kind": "retrieve", "source_hint": name}]}
            raw = {"routes": [{"requirement_id": "r1", "candidates": ["agent:groupware", "agent:work:email"]}]}
            self.assertEqual(request_planning._routes(raw, spec, catalog)["r1"]["selected"], "agent:work:email")
            raw["routes"][0]["candidates"] = ["agent:groupware"]
            with self.assertRaises(PlanError):
                request_planning._routes(raw, spec, catalog)


if __name__ == "__main__":
    unittest.main()
