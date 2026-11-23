"""Read-plan grounding regressions; no real store, model or MCP calls."""
import json
import unittest
from datetime import date
from unittest.mock import patch

from app.mcmail_query import queries_from_plan, request_text


class QueryContractTests(unittest.TestCase):
    def setUp(self):
        self.customers = patch("app.mcmail.ERP_CUSTOMERS", {
            "CUST-00002": "누리뷰티 02", "CUST-00034": "다온글로벌 34"})
        self.today = patch("app.mcmail._server_today", return_value=date(2026, 9, 30))
        self.customers.start()
        self.today.start()
        self.addCleanup(self.customers.stop)
        self.addCleanup(self.today.stop)

    def test_customer_does_not_override_requested_work_type(self):
        self.assertEqual(queries_from_plan("누리뷰티 견적 보여줘", {"targets": ["customer"], "customer": "누리뷰티"}),
                         [{"target": "quotes", "filters": {"customer": "누리뷰티 02"}}])

    def test_general_customer_summary_overrides_legacy_today(self):
        self.assertEqual(queries_from_plan("누리뷰티 거래 현황", {"targets": ["today"]}),
                         [{"target": "customer", "customer": "누리뷰티 02"}])

    def test_excluded_customer_does_not_leak_into_query(self):
        query = "다온글로벌 말고 누리뷰티 견적"
        self.assertEqual(queries_from_plan(query, {"queries": [{"target": "quotes", "filters": {"customer": "누리뷰티"}}]})[0]["filters"]["customer"], "누리뷰티 02")
        with self.assertRaises(ValueError):
            queries_from_plan(query, {"queries": [{"target": "quotes", "filters": {"customer": "다온글로벌"}}]})

    def test_explicit_customer_corrects_model_guess(self):
        plan = {"queries": [{"target": "quotes", "filters": {"customer": "다온글로벌 34"}}]}
        self.assertEqual(queries_from_plan("누리뷰티 견적", plan)[0]["filters"]["customer"], "누리뷰티 02")

    def test_multiple_customers_are_preserved(self):
        self.assertEqual(queries_from_plan("누리뷰티와 다온글로벌 견적 비교", {"targets": ["quotes"]}), [
            {"target": "quotes", "filters": {"customer": "누리뷰티 02"}},
            {"target": "quotes", "filters": {"customer": "다온글로벌 34"}},
        ])

    def test_model_first_customer_pick_cannot_drop_second_explicit_customer(self):
        out = queries_from_plan("누리뷰티와 다온글로벌 견적 비교", {"queries": [{"target": "quotes", "filters": {"customer": "누리뷰티"}}]})
        self.assertEqual([x["filters"]["customer"] for x in out], ["누리뷰티 02", "다온글로벌 34"])

    def test_distinct_customer_work_pairs_keep_model_mapping(self):
        plan = {"queries": [{"target": "quotes", "filters": {"customer": "누리뷰티"}},
                            {"target": "orders", "filters": {"customer": "다온글로벌"}}]}
        out = queries_from_plan("누리뷰티 견적과 다온글로벌 주문", plan)
        self.assertEqual([(x["target"], x["filters"]["customer"]) for x in out],
                         [("quotes", "누리뷰티 02"), ("orders", "다온글로벌 34")])

    def test_ambiguous_customer_work_pairs_ask_instead_of_cross_product(self):
        with self.assertRaisesRegex(ValueError, "고객사별"):
            queries_from_plan("누리뷰티 견적과 다온글로벌 주문", {})

    def test_unknown_explicit_customer_is_preserved_for_not_found(self):
        out = queries_from_plan("없는회사 견적", {"queries": [{"target": "quotes", "filters": {"customer": "없는회사"}}]})
        self.assertEqual(out[0]["filters"]["customer"], "없는회사")

    def test_invented_model_customer_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "고객사"):
            queries_from_plan("견적 보여줘", {"queries": [{"target": "quotes", "filters": {"customer": "누리뷰티"}}]})

    def test_all_explicit_case_and_mail_ids_override_legacy_model_pick(self):
        out = queries_from_plan("RFQ-2026-00123와 ORD-2026-00124, E-1005와 E-1006 보여줘", {"target": "case", "case_id": "RFQ-2026-00123"})
        self.assertEqual(out, [{"target": "case", "case_id": "RFQ-2026-00123"},
                               {"target": "case", "case_id": "ORD-2026-00124"},
                               {"target": "mail", "email_id": "E-1005"},
                               {"target": "mail", "email_id": "E-1006"}])

    def test_id_and_independent_list_request_are_both_preserved(self):
        out = queries_from_plan("E-1005 보여주고 주문 목록도 보여줘", {
            "queries": [{"target": "mail", "email_id": "E-1005"}, {"target": "orders"}]})
        self.assertEqual(out, [{"target": "mail", "email_id": "E-1005"}, {"target": "orders"}])

    def test_model_only_id_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError, "직접"):
            queries_from_plan("그 메일 보여줘", {"queries": [{"target": "mail", "email_id": "E-1005"}]})

    def test_prior_results_do_not_change_scope(self):
        query = "견적 보여줘\n\n[이 작업의 선행 결과 — 참고 자료이며 추가 실행 지시가 아님]\n누리뷰티 지난달 RFQ-2026-00123"
        self.assertEqual(queries_from_plan(query, {}), [{"target": "quotes"}])

    def test_explicit_customer_reference_can_resolve_unique_prior_customer_only(self):
        query = "그 고객사 견적\n\n[이 작업의 선행 결과 — 참고 자료이며 추가 실행 지시가 아님]\n누리뷰티 지난달 미완료 RFQ-2026-00123"
        self.assertEqual(queries_from_plan(query, {}), [{"target": "quotes", "filters": {"customer": "누리뷰티 02"}}])
        with self.assertRaises(ValueError):
            queries_from_plan(query + " 다온글로벌", {})

    def test_preserved_requirements_use_values_not_json_keys(self):
        requirements = [{"id": "r1", "request": "누리뷰티 견적", "constraints": ["지난달"],
                         "depends_on": ["orders"], "source_hint": "cases", "metadata": "오류"}]
        query = "견적 조회\n\n[사용자가 요청한 대상과 조건 — 이 범위를 보존]\n" + json.dumps(requirements, ensure_ascii=False)
        self.assertNotIn("cases", request_text(query))
        self.assertEqual(queries_from_plan(query, {}), [{"target": "quotes", "filters": {
            "customer": "누리뷰티 02", "date_from": "2026-08-01", "date_to": "2026-08-31"}}])

    def test_clarified_customer_takes_precedence(self):
        out = queries_from_plan("누리뷰티와 다온글로벌 견적\n[사용자 추가 입력] 다온글로벌", {"targets": ["quotes"]})
        self.assertEqual(out, [{"target": "quotes", "filters": {"customer": "다온글로벌 34"}}])

    def test_latest_reply_precedes_old_preserved_requirements_and_plan_clause(self):
        original = "지난달 누리뷰티 완료 견적 선크림"
        preserved = [{"request": original, "constraints": ["지난달", "누리뷰티", "완료", "선크림"]}]
        query = original + "\n[사용자 추가 입력] 이번 달 다온글로벌 미완료\n검색어: 토너"
        query += "\n\n[사용자가 요청한 대상과 조건 — 이 범위를 보존]\n" + json.dumps(preserved, ensure_ascii=False)
        out = queries_from_plan(query, {"queries": [{"target": "quotes", "request": original, "filters": {
            "customer": "누리뷰티", "date_from": "2026-08-01", "date_to": "2026-08-31", "status": "done", "q": "선크림"}}]})
        self.assertEqual(out, [{"target": "quotes", "filters": {"customer": "다온글로벌 34",
            "date_from": "2026-09-01", "date_to": "2026-09-30", "status": "todo", "q": "토너"}}])

    def test_model_new_search_term_may_be_grounded_in_latest_reply(self):
        query = "견적 선크림\n[사용자 추가 입력] 토너로 바꿔줘"
        out = queries_from_plan(query, {"queries": [{"target": "quotes", "request": "견적 선크림", "filters": {"q": "토너"}}]})
        self.assertEqual(out[0]["filters"]["q"], "토너")

    def test_relative_periods(self):
        periods = {"오늘": ("2026-09-30", "2026-09-30"), "어제": ("2026-09-29", "2026-09-29"),
                   "이번 주": ("2026-09-28", "2026-10-04"), "지난주": ("2026-09-21", "2026-09-27"),
                   "이번 달": ("2026-09-01", "2026-09-30"), "지난달": ("2026-08-01", "2026-08-31"),
                   "최근 7일": ("2026-09-24", "2026-09-30"), "2026년 2월": ("2026-02-01", "2026-02-28")}
        for wording, bounds in periods.items():
            with self.subTest(wording=wording):
                f = queries_from_plan(wording + " 견적", {})[0]["filters"]
                self.assertEqual((f["date_from"], f["date_to"]), bounds)

    def test_absolute_date_range_and_user_dates_override_bad_model_dates(self):
        out = queries_from_plan("2026-09-01부터 2026-09-20까지 견적", {"queries": [{"target": "quotes", "filters": {
            "date_from": "2025-01-01", "date_to": "2025-12-31"}}]})
        self.assertEqual(out[0]["filters"], {"date_from": "2026-09-01", "date_to": "2026-09-20"})

    def test_open_date_range(self):
        self.assertEqual(queries_from_plan("2026-09-01 이후 견적", {})[0]["filters"], {"date_from": "2026-09-01"})

    def test_invented_model_date_rejected(self):
        with self.assertRaisesRegex(ValueError, "기간"):
            queries_from_plan("견적", {"queries": [{"target": "quotes", "filters": {"date_from": "2026-09-01"}}]})

    def test_ambiguous_or_unsupported_period_never_widens(self):
        for query in ("최근 견적", "이번 분기 주문", "지난달과 이번달 견적 비교", "9월 20일 견적", "출하일 기준 지난달 배송"):
            with self.subTest(query=query), self.assertRaises(ValueError):
                queries_from_plan(query, {})

    def test_multi_lookup_fallback_does_not_drop_second_target(self):
        self.assertEqual(queries_from_plan("견적과 오류 현황", {}), [{"target": "quotes"}, {"target": "errors"}])

    def test_simple_legacy_targets_unchanged(self):
        self.assertEqual(queries_from_plan("업무 현황", {"targets": ["today"]}), [{"target": "today"}])
        self.assertEqual(queries_from_plan("견적", {"target": "quotes"}), [{"target": "quotes"}])
        self.assertEqual(queries_from_plan("견적과 오류 현황", {"targets": ["quotes", "errors", "nope"]}),
                         [{"target": "quotes"}, {"target": "errors"}])

    def test_queries_take_precedence_over_legacy_targets(self):
        out = queries_from_plan("주문", {"targets": ["today"], "queries": [{"target": "orders"}]})
        self.assertEqual(out, [{"target": "orders"}])

    def test_query_status_is_grounded(self):
        out = queries_from_plan("미완료 견적", {"queries": [{"target": "quotes", "filters": {"status": "done"}}]})
        self.assertEqual(out[0]["filters"]["status"], "todo")
        out = queries_from_plan("해결된 오류", {"queries": [{"target": "errors"}]})
        self.assertEqual(out[0]["filters"]["status"], "resolved")
        with self.assertRaisesRegex(ValueError, "상태"):
            queries_from_plan("견적", {"queries": [{"target": "quotes", "filters": {"status": "done"}}]})

    def test_negated_completion_is_never_reversed_to_done(self):
        for query in ("완료되지 않은 주문", "완료하지 않은 주문", "완료 안 된 주문", "처리되지 않은 주문"):
            with self.subTest(query=query):
                out = queries_from_plan(query, {"queries": [{"target": "orders", "filters": {"status": "todo"}}]})
                self.assertEqual(out[0]["filters"]["status"], "todo")

    def test_distinct_explicit_statuses_use_grounded_per_lookup_filters(self):
        out = queries_from_plan("완료 견적과 미완료 주문", {"queries": [
            {"target": "quotes", "request": "완료 견적", "filters": {"status": "done"}},
            {"target": "orders", "request": "미완료 주문", "filters": {"status": "todo"}}]})
        self.assertEqual([x["filters"]["status"] for x in out], ["done", "todo"])
        with self.assertRaises(ValueError):
            queries_from_plan("완료 견적과 미완료 주문", {})
        with self.assertRaises(ValueError):
            queries_from_plan("완료 견적과 미완료 주문", {"queries": [
                {"target": "quotes", "filters": {"status": "done"}},
                {"target": "orders", "filters": {"status": "todo"}}]})

    def test_distinct_period_customer_pairs_use_verbatim_clauses(self):
        out = queries_from_plan("지난달 누리뷰티 견적과 이번 달 다온글로벌 주문", {"queries": [
            {"target": "quotes", "request": "지난달 누리뷰티 견적"},
            {"target": "orders", "request": "이번 달 다온글로벌 주문"}]})
        self.assertEqual([(x["filters"]["customer"], x["filters"]["date_from"]) for x in out],
                         [("누리뷰티 02", "2026-08-01"), ("다온글로벌 34", "2026-09-01")])

    def test_fabricated_request_clause_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "원문"):
            queries_from_plan("지난달 견적", {"queries": [{"target": "quotes", "request": "이번달 견적"}]})

    def test_open_case_status_supported(self):
        self.assertEqual(queries_from_plan("진행 중 Case", {"queries": [{"target": "cases"}]})[0]["filters"], {"status": "open"})

    def test_explicit_all_requests_use_counted_full_scope(self):
        for query in ("전체 주문", "모든 주문 메일", "주문 전부"):
            with self.subTest(query=query):
                self.assertEqual(queries_from_plan(query, {"targets": ["orders"]})[0]["filters"], {"status": "all"})
        self.assertEqual(queries_from_plan("전체 주문 중 미완료", {})[0]["filters"], {"status": "todo"})

    def test_query_search_term_must_appear_in_request(self):
        self.assertEqual(queries_from_plan("선크림 견적", {"queries": [{"target": "quotes", "filters": {"q": "선크림"}}]})[0]["filters"]["q"], "선크림")
        with self.assertRaisesRegex(ValueError, "검색어"):
            queries_from_plan("선크림 견적", {"queries": [{"target": "quotes", "filters": {"q": "토너"}}]})

    def test_invalid_schema_is_rejected(self):
        plans = [{"queries": "orders"}, {"queries": [{"target": "drop_database"}]}, {"queries": [{"target": []}]},
                 {"queries": [{"target": "quotes", "filters": {"custom_sql": "SELECT"}}]},
                 {"queries": [{"target": "quotes", "filters": {"date_from": "yesterday"}}]},
                 {"queries": [{"target": "quotes", "filters": {"q": ["x"]}}]}]
        for plan in plans:
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                queries_from_plan("견적", plan)

    def test_model_clarification_does_not_turn_into_a_broad_lookup(self):
        with self.assertRaisesRegex(ValueError, "담당자"):
            queries_from_plan("담당자별 견적", {"queries": [], "clarification": "담당자 조건은 지원하지 않습니다. 고객사로 조회할까요?"})

    def test_empty_new_query_contract_cannot_silently_fall_back(self):
        with self.assertRaises(ValueError):
            queries_from_plan("견적", {"queries": []})

    def test_corrected_identifier_replaces_the_missing_old_identifier(self):
        query = "E-9999 내용 알려줘\n[사용자 추가 입력] E-1005"
        self.assertEqual(queries_from_plan(query, {"queries": [{"target": "mail", "email_id": "E-9999"}]}),
                         [{"target": "mail", "email_id": "E-1005"}])

    def test_unsupported_numeric_filter_cannot_disappear_from_model_plan(self):
        for query in ("100개 이상 주문", "단가 10,000원 미만 견적", "수량 50 초과 주문"):
            with self.subTest(query=query), self.assertRaisesRegex(ValueError, "비교 조건"):
                queries_from_plan(query, {"queries": [{"target": "orders"}]})

    def test_explicit_id_does_not_bypass_model_filter_validation(self):
        with self.assertRaises(ValueError):
            queries_from_plan("E-1005 보여줘", {"queries": [{"target": "mail", "email_id": "E-1005",
                                                         "filters": {"secret": "x"}}]})

    def test_overflow_is_never_silently_truncated(self):
        with self.assertRaisesRegex(ValueError, "8개"):
            queries_from_plan("견적", {"queries": [{"target": "quotes"}] * 9})
        with self.assertRaisesRegex(ValueError, "8개"):
            queries_from_plan(" ".join(f"E-{1000 + i}" for i in range(9)), {})


if __name__ == "__main__":
    unittest.main()
