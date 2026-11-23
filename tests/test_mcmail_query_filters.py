"""Query scope and evidence quality regression tests, isolated store and no LLM/network."""
import copy
import unittest
from contextlib import ExitStack
from datetime import date
from unittest.mock import patch

from db_fixture import isolate_db
from app import mcmail, mock_mcosmetic_mcp as mcp


class QueryFiltersTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        self.stack.enter_context(patch.object(mcmail, "_server_today", return_value=date(2026, 10, 5)))
        self.stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")))
        mcmail.init_mcmail()

    def lookup(self, target, **filters):
        data, task, _ = mcmail.lookup(target, {"filters": filters})
        return data, mcmail.fallback_answer(data, task)

    def test_customer_and_type_are_intersected_before_counting(self):
        data, text = self.lookup("quotes", customer="CUST-00002")
        expected = mcmail.list_emails("quote", "all", q="누리뷰티 02")["items"]
        self.assertGreater(len(expected), 0)
        self.assertEqual({e["emailId"] for e in data["rows"]}, {e["emailId"] for e in expected})
        self.assertEqual(data["counts"]["all"], len(expected))
        self.assertEqual({e["customer"] for e in data["rows"]}, {"누리뷰티 02"})
        self.assertIn("조회 범위: 고객사 누리뷰티 02", text)
        self.assertNotIn("라온코스메틱 11", text)

    def test_received_date_and_done_status_intersect(self):
        completed = mcmail.list_emails("quote", "done")["items"]
        self.assertTrue(completed)
        when = completed[0]["receivedDate"][:10]
        data, text = self.lookup("quotes", date_from=when, date_to=when, status="done")
        expected = [e for e in completed if e["receivedDate"].startswith(when)]
        self.assertEqual({e["emailId"] for e in data["rows"]}, {e["emailId"] for e in expected})
        self.assertEqual(data["counts"], {"all": len(expected), "done": len(expected), "todo": 0, "err": 0})
        self.assertIn("조건에 맞는 견적요청 메일", text)
        self.assertNotIn("### 처리할", text)

    def test_keyword_matches_specific_item_instead_of_all_inventory(self):
        data, text = self.lookup("stock", q="MC-CAL-SR050")
        self.assertEqual([r["itemCode"] for r in data["inventory"]], ["MC-CAL-SR050"])
        self.assertIn("현재 가용 수량", text)
        self.assertIn("과거 시점 재고는 제공하지 않습니다", text)

    def test_past_inventory_is_never_claimed_from_current_snapshot(self):
        data, text = self.lookup("stock", date_from="2026-10-01", date_to="2026-10-01")
        self.assertNotIn("inventory", data)
        self.assertIn("재고문의 메일만 조회", text)
        self.assertIn("과거·고객사별 재고를 뜻하지 않아", text)

    def test_shipment_mail_period_does_not_show_unfiltered_erp_rows(self):
        data, text = self.lookup("shipments", date_from="2000-01-01", date_to="2000-01-02")
        self.assertEqual(data["counts"]["all"], 0)
        self.assertNotIn("shipments", data)
        self.assertIn("수신일·메일 처리상태와 다른 기준", text)

    def test_customer_filters_erp_shipments_when_period_is_not_requested(self):
        data, _ = self.lookup("shipments", customer="CUST-00011")
        self.assertTrue(data["shipments"])
        self.assertEqual({x["customerCode"] for x in data["shipments"]}, {"CUST-00011"})

    def test_ambiguous_and_unknown_customer_never_expand_to_everyone(self):
        for name in ("누리", "없는고객사"):
            with self.subTest(name=name), self.assertRaises(mcmail.MailValidationError):
                self.lookup("quotes", customer=name)

    def test_malformed_unsupported_and_reversed_filters_reject(self):
        cases = [("quotes", {"date_from": "2026-02-30"}), ("quotes", {"date_from": "20261005"}),
                 ("orders", {"date_from": "2026-10-06", "date_to": "2026-10-01"}),
                 ("orders", {"status": "resolved"}), ("cases", {"status": "err"}),
                 ("errors", {"status": "todo"}), ("quotes", {"date_from": 20261005}),
                 ("quotes", {"unknown": "x"}), ("case", {"date_from": "2026-10-01"})]
        for target, filters in cases:
            with self.subTest(target=target, filters=filters), self.assertRaises(mcmail.MailValidationError):
                mcmail.lookup(target, {"case_id": "RFQ-2026-00123", "filters": filters})
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.lookup("quotes", {"filters": []})

    def test_cases_apply_updated_date_and_completion_state(self):
        completed = mcmail.list_cases("done")["items"]
        self.assertTrue(completed)
        when = completed[0]["lastUpdatedDate"][:10]
        data, text = self.lookup("cases", status="done", date_from=when, date_to=when)
        expected = mcmail.list_cases("done", date_from=when, date_to=when)["items"]
        self.assertEqual({c["caseId"] for c in data["rows"]}, {c["caseId"] for c in expected})
        self.assertEqual(data["counts"], {"all": len(expected), "done": len(expected), "open": 0})
        self.assertIn("Case 최종 수정일", text)

    def test_resolved_errors_are_labeled_and_counted_as_resolved(self):
        with mcmail._session(write=True) as st:
            resolved = copy.deepcopy(st.errors[0])
            resolved.update(id="ERR-9000", status="done", time="2026-10-04 11:00")
            st.errors.append(resolved)
        data, text = self.lookup("errors", status="done", date_from="2026-10-04", date_to="2026-10-04")
        self.assertEqual([e["id"] for e in data["rows"]], ["ERR-9000"])
        self.assertEqual(data["filters"]["status"], "resolved")
        self.assertIn("해결된 API 오류는 **1건**", text)
        self.assertIn("ERR-9000", text)
        self.assertIn("오류 발생일", text)

    def test_today_filters_every_kpi_and_type_to_same_received_period(self):
        data, text = self.lookup("today", date_from="2000-01-01", date_to="2000-01-01")
        self.assertEqual(data["kpi"], {"recv": 0, "auto": 0, "review": 0, "erp": 0, "err": 0})
        self.assertTrue(all(t["n"] == 0 for t in data["types"]))
        self.assertEqual(data["todo"], [])
        self.assertIn("지정한 조회 조건", text)
        self.assertNotIn("남은 전체", text)

    def test_today_customer_filter_implicitly_means_today(self):
        data, _ = self.lookup("today", customer="CUST-00002")
        self.assertEqual((data["filters"]["date_from"], data["filters"]["date_to"]), ("2026-10-05", "2026-10-05"))
        self.assertEqual(sum(t["n"] for t in data["types"]), data["kpi"]["recv"])

    def test_period_kpi_includes_unclassified_messages_in_type_totals(self):
        data, _ = self.lookup("today", date_from="2026-10-05", date_to="2026-10-05")
        self.assertEqual(sum(t["n"] for t in data["types"]), data["kpi"]["recv"])
        self.assertGreater(next(t["n"] for t in data["types"] if t["t"] == "unclassified"), 0)

    def test_customer_detail_applies_scope_and_refuses_conflicting_customers(self):
        data, task, _ = mcmail.lookup("customer", {"customer": "CUST-00002", "filters": {"date_from": "2000-01-01", "date_to": "2000-01-02"}})
        self.assertEqual((data["rows"], data["cases"], data["shipments"]), ([], [], []))
        self.assertIn("조건에 맞는 거래 이력이 없습니다", mcmail.fallback_answer(data, task))
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.lookup("customer", {"customer": "CUST-00002", "filters": {"customer": "CUST-00011"}})

    def test_answer_exposes_ids_and_actual_omitted_count(self):
        data, text = self.lookup("quotes", status="all")
        self.assertEqual(data["counts"]["all"], mcmail.list_emails("quote", "all")["total"])   # 이력 포함 / history included
        self.assertIn("메일 ID", text)
        self.assertIn("Case ID", text)
        self.assertIn(f"외 {data['counts']['all'] - 10}건이 더 있습니다", text)   # 표는 10건까지 / the table shows ten rows
        for row in data["rows"][:10]:
            self.assertIn(row["emailId"], text)

    def test_mcp_forwards_filters_and_uses_same_scoped_answer(self):
        filters = {"customer": "CUST-00002", "status": "all"}
        _, result = mcp._run("get_work_status", {"target": "quotes", "filters": filters})
        data, task, _ = mcmail.lookup("quotes", {"filters": filters})
        self.assertEqual(result["data"], data)
        self.assertEqual(result["answer"], mcmail.fallback_answer(data, task))
        self.assertIn("filters", mcp.TOOLS[0]["inputSchema"]["properties"])


if __name__ == "__main__":
    unittest.main()
