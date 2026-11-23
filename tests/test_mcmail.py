# -*- coding: utf-8 -*-
"""M코스메틱 Email Agent 서버 스토어(계획 B1) — 시드·상대 날짜, 상태 기계, 필수값·신뢰도, 트리아지, 가상 ERP, 주문,
초안 KO/EN, 발송, 오류, 시나리오, lookup, API 라운드트립. 격리 DB(tests/db_fixture) + 오늘 날짜 고정, 실제 LLM 없음.

M Cosmetic Email Agent server store (plan B1) — seed and relative dates, the state machine, required values and
confidence, triage, the virtual ERP, orders, KO/EN drafts, sending, errors, the scenario, lookups and the API round
trip. Isolated DB (tests/db_fixture) with a pinned today; no real LLM.
"""
import json
import sqlite3
import threading
import time
import unittest
from contextlib import ExitStack
from datetime import date
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from db_fixture import isolate_db
from app import db, mcmail, mcmail_api, mock_mcosmetic

# 시드 건수(2026-10-13 과거 이력 포함) — 고정 숫자 대신 시드에서 센다 / seed counts (history included since 2026-10-13), read from the seed
N_MAILS = len(mcmail._SEED["EMAILS"])  # noqa: SLF001
N_INBOUND = sum(1 for e in mcmail._SEED["EMAILS"] if e.get("direction") == "in")  # noqa: SLF001
N_CASES = len(mcmail._SEED["CASES"])  # noqa: SLF001
N_CASES_DONE = sum(1 for c in mcmail._SEED["CASES"] if mcmail._case_done(c))  # noqa: SLF001
N_ERRORS = len(mcmail._SEED["ERRORS"])  # noqa: SLF001
_SEED_IN = [e for e in mcmail._SEED["EMAILS"] if e.get("direction") == "in" and e.get("confidence") is not None]  # noqa: SLF001
N_TIERS = [sum(1 for e in _SEED_IN if e["confidence"] >= 95), sum(1 for e in _SEED_IN if 80 <= e["confidence"] < 95),
           sum(1 for e in _SEED_IN if e["confidence"] < 80)]

TODAY = date(2026, 10, 5)   # 기준일 2026-09-20 + 15일 — 월이 바뀌어 날짜 복원이 드러난다 / base + 15 days crosses a month
AUTH = {"Authorization": "Bearer demo-mcosmetic-key-2026"}


class McmailBase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.db_path = isolate_db(self.stack)
        self.today = self.stack.enter_context(patch.object(mcmail, "_server_today", return_value=TODAY))
        self.stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")))
        mcmail.init_mcmail()

    def mail(self, email_id):
        return mcmail.get_email(email_id)["email"]

    def case(self, case_id):
        return mcmail.get_case(case_id)["case"]

    def rows(self, sql):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    def peek(self):
        """저장소 내부 상태 스냅숏(발신함·출하) / store internals snapshot (outbox, shipments)"""
        with mcmail._session() as st:  # noqa: SLF001
            return {"outbox": list(st.outbox), "shipments": dict(st.shipments), "clock": st.clock}


class SeedTests(McmailBase):
    def test_seed_counts_and_relative_dates(self):
        total, inbound = self.rows("SELECT COUNT(*), SUM(direction='in') FROM mc_emails")[0]
        self.assertEqual((total, inbound), (N_MAILS, N_INBOUND))
        self.assertEqual(mcmail.list_cases()["total"], N_CASES)
        self.assertEqual(mcmail.list_errors("all")["counts"], {"open": 2, "done": N_ERRORS - 2, "all": N_ERRORS})   # 이력의 오류는 해결됨 / history errors are resolved
        self.assertEqual(len(mcmail.recent_log()), 8)
        meta = mcmail.meta()
        self.assertEqual((meta["today"], meta["clock"]), ("2026-10-05", "12:02"))
        # 기준일 09-20 → 10-05: ISO·한국어·M/D·SO 번호·파일명·연월 모두 15일 이동 / every date form moves by 15 days
        e1 = self.mail("E-1001")
        self.assertEqual(e1["receivedDate"], "2026-10-05 09:13")
        self.assertIn("10월 30일까지 납품 가능한지", e1["body"])
        c = self.case("RFQ-2026-00123")
        self.assertEqual(c["entity"]["deliveryDate"], "2026-10-30")
        self.assertIn("10/30 납기", c["request"])
        self.assertEqual([x for x in sorted(meta["shipments"]) if x[-5:] >= "00097"], ["SO-20260929-00097", "SO-20260930-00102", "SO-20261001-00109",
                                                                                    "SO-20261004-00118"])   # 이력의 SO(00061~00096)는 앞에 / history SOs come before
        self.assertEqual(self.mail("E-1022")["subject"], "SO-20260930-00102 인보이스 요청")
        self.assertEqual(self.mail("E-1014")["attachments"][0]["name"], "CosmeticWeekly_1005.pdf")
        self.assertEqual(self.mail("E-1011")["pick"]["customerCode"][0]["note"], "최근 거래 2026-10")
        self.assertIn("10월 6일 출하 완료 예정", self.mail("E-1012")["flow"]["draft"])
        self.assertEqual(meta["erpItems"]["MC-CAL-SR050"]["lead"], "2026-10-27")
        self.assertEqual(mcmail.list_errors("all")["items"][0]["time"], "2026-10-05 10:49")

    def test_reanchor_shifts_dates_and_keeps_progress(self):
        mcmail.hold("E-1020", True)
        mcmail.create_order("E-1005")
        self.assertIn("SO-20261005-00126", mcmail.recent_log(1)[0]["text"])
        self.today.return_value = date(2026, 10, 7)
        mcmail.init_mcmail()
        self.assertEqual(mcmail.meta()["today"], "2026-10-07")
        self.assertEqual(self.mail("E-1001")["receivedDate"], "2026-10-07 09:13")
        self.assertEqual(self.mail("E-1020")["status"], "보류")
        self.assertEqual(self.mail("E-1005")["flow"]["orderResult"]["so"], "SO-20261007-00126")
        self.assertIn("SO-20261007-00126", mcmail.meta()["shipments"])
        self.assertIn("SO-20261007-00126", mcmail.recent_log(1)[0]["text"])
        self.assertEqual(self.case("RFQ-2026-00123")["entity"]["deliveryDate"], "2026-11-01")
        self.assertEqual(self.rows("SELECT COUNT(*) FROM mc_emails")[0][0], N_MAILS)

    def test_bad_stored_anchor_does_not_block_init(self):
        conn = sqlite3.connect(self.db_path)
        with conn:
            conn.execute("UPDATE mc_meta SET value='garbage' WHERE key='today'")
        conn.close()
        mcmail.init_mcmail()
        self.assertEqual(mcmail.meta()["today"], "2026-10-05")

    def test_reset_reseeds(self):
        mcmail.run_erp("E-1001")
        mcmail.send("E-1001")
        out = mcmail.reset()
        self.assertEqual(out["toast"]["title"], "데모 데이터를 초기화했습니다")
        self.assertEqual(self.mail("E-1001")["status"], "처리 대기")
        self.assertEqual(self.rows("SELECT COUNT(*) FROM mc_emails")[0][0], N_MAILS)
        self.assertEqual(len(out["errors"]), 2)
        self.assertEqual(self.peek()["clock"], 722)


class StateMachineTests(McmailBase):
    def test_unclassified_to_done(self):
        e = self.mail("E-1016")
        self.assertEqual((e["status"], e["nextStep"]["k"], e["inTriage"]), ("미분류", "class", True))
        out = mcmail.classify("E-1016", "quote")
        self.assertEqual(out["toast"], {"type": "success", "title": "견적요청(으)로 분류했습니다", "msg": "남은 확인 항목 3건"})
        self.assertEqual(out["email"]["status"], "확인 필요")
        self.assertEqual([i.get("field", i["k"]) for i in out["email"]["issues"]], ["itemCode", "quantity", "case"])
        out = mcmail.set_entity("E-1016", "itemCode", "MC-CAL-SR050", triage=True)
        self.assertEqual(out["email"]["entities"]["itemName"], {"value": "카밍 세럼 50g", "conf": 1, "src": "user"})
        self.assertEqual((out["toast"]["title"], out["toast"]["msg"]), ("Item Code 확인", "남은 확인 항목 2건"))
        mcmail.set_entity("E-1016", "quantity", "200", triage=True)
        out = mcmail.new_case("E-1016")
        self.assertEqual(out["email"]["caseId"], "RFQ-2026-00133")
        self.assertEqual(out["toast"]["title"], "확인 완료")
        self.assertTrue(out["toast"]["msg"].startswith("견적요청 메뉴로 이동했습니다."))
        self.assertEqual((out["email"]["status"], out["email"]["workStatus"]), ("처리 대기", "견적작성 필요"))
        self.assertEqual(out["case"]["status"], "신규 접수")
        self.assertEqual(out["log"][1]["text"], "다온뷰티 04 · 신규 Case RFQ-2026-00133 생성")
        out = mcmail.run_erp("E-1016")
        self.assertEqual((out["email"]["status"], out["email"]["nextStep"]["k"]), ("진행 중", "send"))
        self.assertEqual(out["email"]["workSteps"], [["ERP 단가 조회", True], ["AI 답변 작성", True], ["확인 후 발송", False]])
        out = mcmail.send("E-1016")
        self.assertEqual(out["email"]["status"], "완료")
        self.assertEqual(out["case"]["status"], "견적 회신 완료")

    def test_hold_error_complete_archive(self):
        out = mcmail.hold("E-1020", True)
        self.assertEqual((out["email"]["status"], out["email"]["workStatus"], out["email"]["nextStep"]["k"]),
                         ("보류", "보류", "hold"))
        self.assertEqual(out["toast"]["title"], "보류했습니다")
        out = mcmail.hold("E-1020", False)
        self.assertEqual((out["email"]["status"], out["email"]["workStatus"]), ("처리 대기", "재고 조회필요"))
        self.assertEqual(mcmail.hold("E-1020")["email"]["status"], "보류")   # on 생략 = 토글 / omitted on toggles
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.hold("E-1009", True)                                      # 트리아지 중 / still in triage
        self.assertEqual(self.mail("E-1008")["status"], "오류")
        self.assertEqual(self.mail("E-1008")["nextStep"], {"k": "retry", "label": "다시 시도", "title": "ERP로 다시 전송"})
        self.assertEqual(self.mail("E-1012")["nextStep"]["title"], "메일 다시 발송")
        out = mcmail.complete("E-1002")          # 할 일 없음 → '확인 완료', 고객 검토 중 유지 / nothing left
        self.assertEqual((out["toast"]["title"], out["email"]["workStatus"], out["email"]["status"]),
                         ("확인 완료", "고객 검토 중", "완료"))
        out = mcmail.complete("E-1006")          # 남은 작업이 있는 완료처리 / completing with work left
        self.assertEqual((out["toast"]["title"], out["email"]["workStatus"]), ("완료처리했습니다", "처리완료"))
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.complete("E-1006")
        self.assertEqual(mcmail.archive("E-1013")["email"]["workStatus"], "보관")
        out = mcmail.spam("E-1014")
        self.assertEqual((out["email"]["workStatus"], out["toast"]["msg"]), ("스팸 처리", "demo-ffcf0acd28@workspace.example"))
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.archive("E-1001")
        with self.assertRaises(mcmail.MailNotFound):
            mcmail.hold("E-9999", True)

    def test_tone_follows_page_rule_order(self):
        # 화면 tone(): 오류·실패 > 확인 필요·보류 > 조회 > 완료·보관·스팸 > 필요·대기·~중·접수 / the page's rule order
        cases = {"ERP 조회 실패": "err", "품목 확인 필요": "warn", "보류": "warn", "출하 조회 완료": "prog",
                 "견적 회신 완료": "done", "보관": "done", "스팸 처리": "done", "ERP 전송대기": "prog", "고객 검토 중": "prog",
                 "신규 접수": "prog", "출하 준비": "", "": "", None: ""}
        self.assertEqual({k: mcmail.tone(k) for k in cases}, cases)
        self.assertEqual((mcmail.STATUS_TONE["확인 필요"], mcmail.STATUS_TONE["보류"]), ("warn", ""))

    def test_hold_blocks_order_draft_and_send(self):
        mcmail.hold("E-1005", True)
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.create_order("E-1005")
        mcmail.hold("E-1021", False)
        mcmail.run_erp("E-1021")
        mcmail.hold("E-1021", True)
        self.assertEqual(mcmail.run_erp("E-1021")["toast"]["title"], "재고조회 완료")   # 카드의 다시 조회는 허용 / re-query allowed
        for blocked in (lambda: mcmail.draft("E-1021", regen=True), lambda: mcmail.send("E-1021")):
            with self.assertRaises(mcmail.MailValidationError):
                blocked()
        mcmail.hold("E-1021", False)
        self.assertEqual(mcmail.send("E-1021")["email"]["status"], "완료")


class RequiredAndTriageTests(McmailBase):
    def test_low_confidence_and_missing_values(self):
        e = self.mail("E-1004")
        self.assertEqual(e["issues"], [{"k": "field", "field": "shippingAddress", "low": True}])
        out = mcmail.set_entity("E-1004", "shippingAddress", "인천광역시 서구 신규 물류센터 12", triage=True)
        self.assertEqual(out["toast"]["title"], "확인 완료")
        self.assertEqual(out["email"]["workStatus"], "ERP 전송대기")
        self.assertEqual(out["case"]["status"], "ERP 전송대기")          # '주문정보 확인 필요' → 이동 / moved
        self.assertEqual(out["case"]["entity"]["shippingAddress"], "인천광역시 서구 신규 물류센터 12")
        self.assertEqual(self.mail("E-1009")["issues"], [{"k": "field", "field": "itemCode", "missing": True}])
        out = mcmail.set_entity("E-1009", "itemCode", "MC-GLW-SR050", triage=True)   # 후보 선택 / candidate pick
        self.assertEqual(out["toast"]["title"], "확인 완료")
        self.assertEqual((out["case"]["title"], out["case"]["entity"]["itemCode"]), ("글로우 세럼 견적 건", "MC-GLW-SR050"))
        # 자유 편집: 필수값을 비우면 확인 필요, 되돌리면 처리 대기(작업 상태는 그대로) / free edit
        out = mcmail.set_entity("E-1005", "quantity", "")
        self.assertIsNone(out["toast"])
        self.assertEqual(out["email"]["status"], "확인 필요")
        out = mcmail.set_entity("E-1005", "quantity", "400")
        self.assertEqual((out["email"]["status"], out["email"]["workStatus"]), ("처리 대기", "ERP 전송대기"))
        self.assertTrue(mcmail.set_entity("E-1007", "salesOrder", "SO-X")["email"]["flow"]["erpStale"])
        for bad in (lambda: mcmail.set_entity("E-1009", "itemCode", "  ", triage=True),
                    lambda: mcmail.set_entity("E-1009", "nope", "1"),
                    lambda: mcmail.set_entity("E-1011", "customerCode", "CUST-99999", triage=True),
                    lambda: mcmail.set_entity("E-1015", "quantity", "1")):
            with self.assertRaises(mcmail.MailValidationError):
                bad()

    def test_customer_pick_fills_contact_and_case(self):
        out = mcmail.set_entity("E-1011", "customerCode", "CUST-00002", triage=True)
        e = out["email"]
        self.assertEqual((e["customer"], e["entities"]["customer"]["value"]), ("누리뷰티 02", "누리뷰티 02"))
        self.assertEqual(e["entities"]["shippingAddress"], {"value": "경기도 화성시 동탄산단로 45 누리뷰티 물류센터",
                                                           "conf": .93, "src": "master"})
        self.assertEqual((out["case"]["customer"], out["case"]["customerCode"]), ("누리뷰티 02", "CUST-00002"))
        self.assertEqual(out["toast"]["title"], "확인 완료")

    def test_link_case_builds_delta(self):
        out = mcmail.link_case("E-1010", "RFQ-2026-00131")
        e, c = out["email"], out["case"]
        self.assertEqual(e["delta"]["changed"], [{"field": "quantity", "label": "수량", "prev": "400 EA", "cur": "500 EA", "raw": 500}])
        self.assertEqual((e["threadId"], e["assignee"], e["workStatus"]), ("T-00131", "이수진", "수정견적 필요"))
        self.assertEqual(e["entities"]["deliveryDate"], {"value": "2026-11-14", "conf": .95, "src": "case"})
        self.assertEqual((c["status"], c["request"], c["prev"], c["entity"]["quantity"]),
                         ("수정견적 필요", "500EA 기준 단가 재확인", {"quantity": 400}, 500))
        self.assertEqual(c["changes"][-1]["sourceEmailId"], "E-1010")
        self.assertEqual(out["toast"]["title"], "확인 완료")
        out = mcmail.link_case("E-1001", "RFQ-2026-00118")                 # 모달 경로 / modal path
        self.assertEqual(out["toast"], {"type": "success", "title": "Case 연결 완료", "msg": "RFQ-2026-00118"})
        with self.assertRaises(mcmail.MailNotFound):
            mcmail.link_case("E-1001", "RFQ-0000-00000")
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.link_case("E-1013", "RFQ-2026-00118")

    def test_reclassify_and_new_order_case(self):
        out = mcmail.classify("E-1016", "order", intent="주문전환")
        self.assertEqual(out["toast"]["title"], "분류 변경 완료")
        self.assertEqual((out["email"]["classification"], out["email"]["intent"], out["email"]["needs"]),
                         ("order", "주문전환", ["order"]))
        self.assertEqual(mcmail.new_case("E-1016")["email"]["caseId"], "ORD-2026-00133")
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.new_case("E-1016")
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.classify("E-1016", "nope")
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.classify("E-1016", "quote", intent="모름")


class ErpTests(McmailBase):
    def test_price_tiers_stock_and_errors(self):
        p = lambda q: mcmail.erp_price("CUST-00002", "MC-CAL-SR050", q)  # noqa: E731
        self.assertEqual([(p(q)["rate"], p(q)["price"]) for q in (299, 300, 500, 999, 1000)],
                         [(0, 10000), (.05, 9500), (.08, 9200), (.08, 9200), (.12, 8800)])
        self.assertEqual((p(300)["inStock"], p(300)["lead"]), (True, "2026-10-27"))
        self.assertEqual((p(1300)["inStock"], p(1300)["lead"]), (False, "2026-11-14"))
        self.assertEqual(mcmail.erp_price("CUST-00023", "MC-BAL-CR050", 300)["price"], 11880)   # 반올림 = 화면 / rounding
        self.assertEqual(mcmail.erp_price("CUST-99999", "MC-CAL-SR050", 300), {"error": "Customer Code를 찾을 수 없습니다."})
        self.assertEqual(mcmail.erp_price("CUST-00002", "MC-X", 300), {"error": "Item Code가 ERP에 등록되어 있지 않습니다."})
        for q in (0, 1.5, "abc", None):
            self.assertEqual(p(q), {"error": "수량 값이 올바르지 않습니다."})
        s = mcmail.erp_stock("MC-CIC-SR050", 600)
        self.assertEqual({k: s[k] for k in ("onHand", "allocated", "available", "reqQty", "enough", "inboundDate", "inboundQty",
                                            "warehouse", "asOf")},
                         {"onHand": 400, "allocated": 70, "available": 330, "reqQty": 600, "enough": False,
                          "inboundDate": "2026-10-23", "inboundQty": 1500, "warehouse": "화성 제1물류센터",
                          "asOf": "2026-10-05 12:02"})
        self.assertEqual((mcmail.erp_stock("MC-CAL-SR050")["reqQty"], mcmail.erp_stock("MC-CAL-SR050")["enough"]), (0, True))
        self.assertIn("error", mcmail.erp_stock("MC-X"))

    def test_shipment_match_priorities(self):
        self.assertEqual(mcmail.erp_shipment("SO-20261001-00109")["matchedBy"], 1)
        self.assertEqual(mcmail.erp_shipment("SO-20990101-00001"), {"error": "Sales Order SO-20990101-00001 를 ERP에서 찾을 수 없습니다."})
        r = mcmail.erp_shipment(None, "CUST-00004", "MC-CAL-CR050")
        self.assertEqual((r["matchedBy"], r["so"]), (2, "SO-20260930-00102"))
        r = mcmail.erp_shipment(None, "CUST-00011", "MC-HYD-SR050")
        self.assertEqual((r["matchedBy"], r["so"]), (3, "SO-20260929-00097"))
        r = mcmail.erp_shipment(None, "CUST-00002", "MC-CAL-SR050", "ORD-2026-00112")
        self.assertEqual((r["matchedBy"], r["so"]), (4, "SO-20260930-00102"))
        self.assertEqual(mcmail.erp_shipment(None, "CUST-00002", None, None),
                         {"error": "조건에 해당하는 출하내역을 ERP에서 찾을 수 없습니다."})

    def test_sales_order_lookup(self):
        r = mcmail.erp_sales_order("SO-20260930-00102")
        self.assertEqual({k: r[k] for k in ("invoiceNo", "customer", "price", "qty", "amount", "vat", "total", "orderDate",
                                            "deliveryDate", "state")},
                         {"invoiceNo": "INV-20260930-00102", "customer": "다온뷰티 04", "price": 11040, "qty": 800,
                          "amount": 8832000, "vat": 883200, "total": 9715200, "orderDate": "2026-09-30",
                          "deliveryDate": "2026-10-11", "state": "출하 준비"})
        self.assertEqual(mcmail.erp_sales_order("SO-20260930-00102", "CUST-00002"),
                         {"error": "SO-20260930-00102 는 다른 고객(다온뷰티 04)의 주문입니다. 인보이스를 발송할 수 없습니다."})
        self.assertEqual(mcmail.erp_sales_order(""), {"error": "Sales Order (번호 없음) 를 ERP에서 찾을 수 없습니다."})
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.run_erp("E-1023")                                   # SO 확인 전 / before the SO pick
        mcmail.set_entity("E-1023", "salesOrder", "SO-20261001-00109", triage=True)
        out = mcmail.run_erp("E-1023")
        self.assertEqual(out["email"]["flow"]["erpResult"]["invoiceNo"], "INV-20261001-00109")
        self.assertEqual(out["email"]["flow"]["erpApi"], "GET /api/erp/v1/sales-orders/SO-20261001-00109")
        self.assertTrue(700 <= out["email"]["flow"]["erpMs"] < 1200)


class OrderTests(McmailBase):
    def test_validate_order_kinds(self):
        def en(cc="CUST-00033", ic="MC-GLW-SR050", q="400", dd="2026-11-06"):
            return {"entities": {"customerCode": {"value": cc}, "itemCode": {"value": ic}, "quantity": {"value": q},
                                 "deliveryDate": {"value": dd}}}
        self.assertEqual(mcmail.validate_order(en()), "")
        self.assertEqual(mcmail.validate_order(en(cc="CUST-1")), "Customer Code를 찾을 수 없습니다.")
        self.assertEqual(mcmail.validate_order(en(ic="MC-X")), "Item Code가 ERP에 등록되어 있지 않습니다.")
        for q in ("0", "1.5", "x"):
            self.assertEqual(mcmail.validate_order(en(q=q)), "수량 값이 올바르지 않습니다.")
        for dd in ("2026-10-04", "10/20", "2026-02-30"):
            self.assertEqual(mcmail.validate_order(en(dd=dd)), "납기일 값이 올바르지 않습니다.")

    def test_order_preview_price(self):
        self.assertEqual(self.mail("E-1005")["orderPrice"], 10450)          # 400EA → 5% 구간 / 5% tier
        self.assertEqual(self.mail("E-1008")["orderPrice"], 7360)
        out = mcmail.set_entity("E-1005", "quantity", "500")                 # 편집 즉시 반영 / follows edits
        self.assertEqual(out["email"]["orderPrice"], 10120)
        out = mcmail.set_entity("E-1005", "itemCode", "MC-X")                # ERP 실패 → Case 제시단가 / case fallback
        self.assertEqual(out["email"]["orderPrice"], 10450)
        self.assertNotIn("orderPrice", self.mail("E-1001"))
        self.assertEqual(mcmail.public(mcmail.get_email("E-1008")["email"])["orderPrice"], 7360)   # 상태 없이 / without a state

    def test_create_order_so_shipment_and_confirmation_mail(self):
        out = mcmail.create_order("E-1005")
        e, c = out["email"], out["case"]
        self.assertEqual(out["toast"], {"type": "success", "title": "주문등록 완료", "msg": "Sales Order SO-20261005-00126"})
        self.assertEqual(e["flow"]["orderResult"], {"so": "SO-20261005-00126", "customer": "온유글로벌 33", "item": "글로우 세럼 50g",
                                                    "qty": 400, "date": "2026-11-06", "price": 10450})
        self.assertEqual((e["status"], e["workStatus"], e["flow"]["orderApi"]), ("완료", "주문등록 완료", "POST /api/erp/v1/sales-orders"))
        self.assertEqual((c["status"], c["salesOrderNumber"], c["caseType"], c["request"]),
                         ("주문등록 완료", "SO-20261005-00126", "주문", "주문등록 완료"))
        sh = self.peek()["shipments"]["SO-20261005-00126"]
        self.assertEqual((sh["shipDate"], sh["state"], sh["orderQty"]), ("2026-11-04", "출하 준비", 400))
        d = mcmail.draft("E-1005")["email"]["flow"]["draft"]                # 주문확인 메일(선택) / optional confirmation
        self.assertIn("Sales Order 번호는 SO-20261005-00126입니다.", d)
        out = mcmail.send("E-1005")
        self.assertEqual(out["case"]["status"], "주문등록 완료")
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.create_order("E-1001")

    def test_order_error_registers_then_retry_resolves(self):
        mcmail.set_entity("E-1005", "deliveryDate", "2026-10-01")
        out = mcmail.create_order("E-1005")
        self.assertEqual(out["toast"], {"type": "error", "title": "ERP 전송 실패",
                                        "msg": "납기일 값이 올바르지 않습니다. 주문은 등록되지 않았습니다."})
        self.assertEqual((out["email"]["status"], out["case"]["status"]), ("오류", "ERP 전송 실패"))
        err = out["errors"][0]
        self.assertEqual((err["id"], err["category"], err["failedAction"], err["tries"]), ("ERR-0009", "ERP 주문등록 실패", "ERP 주문등록", 1))
        self.assertEqual(out["case"]["actions"][-1]["status"], "실패")
        self.assertEqual(mcmail.create_order("E-1005")["errors"][0]["tries"], 2)   # 같은 오류 재시도 / same error again
        mcmail.set_entity("E-1005", "deliveryDate", "2026-11-06")
        out = mcmail.retry("ERR-0009")
        self.assertEqual(out["toast"]["title"], "주문등록 완료")
        x = next(x for x in mcmail.list_errors("all")["items"] if x["id"] == "ERR-0009")
        self.assertEqual(x["status"], "resolved")
        self.assertTrue(x["resolvedAt"].startswith("2026-10-05 "))

    def test_retry_seeded_errors(self):
        out = mcmail.retry("ERR-0008")                    # 주문등록 Timeout / order timeout
        self.assertEqual((out["toast"]["title"], out["email"]["status"]), ("주문등록 완료", "완료"))
        out = mcmail.retry("ERR-0006")                    # Email 발송 실패 / mail failure
        self.assertEqual((out["toast"]["title"], out["case"]["status"]), ("이메일 발송 완료", "출하 안내 완료"))
        self.assertEqual(mcmail.list_errors("open")["items"], [])
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.retry("ERR-0006")
        with self.assertRaises(mcmail.MailNotFound):
            mcmail.retry("ERR-9999")


class DraftTests(McmailBase):
    SIG = "\n\n감사합니다.\nM코스메틱 김영업 드림"

    def test_quote_and_revised_quote_drafts(self):
        out = mcmail.run_erp("E-1001")
        self.assertEqual(out["toast"], {"type": "success", "title": "단가조회 완료", "msg": "답변 초안을 작성했습니다. 확인 후 발송해 주세요."})
        self.assertEqual(out["email"]["flow"]["draft"],
                         "안녕하세요, 누리뷰티 02 박지현 대리님.\n\n문의하신 카밍 세럼 50g 300EA 기준 단가는 9,500원이며,\n"
                         "요청하신 10월 30일까지 납품 가능합니다.\n\n확인 후 주문 진행 여부 회신 부탁드립니다." + self.SIG)
        self.assertEqual(out["email"]["flow"]["erpApi"], "GET /api/erp/v1/prices?customer=CUST-00002&item=MC-CAL-SR050&qty=300")
        v1 = mcmail.draft("E-1001", regen=True)["email"]["flow"]["draft"]
        self.assertIn("견적 회신드립니다.\n\n■ 품목: M코스메틱 카밍 세럼 50g (MC-CAL-SR050)", v1)
        self.assertIn("■ 단가: 9,500원 (기준단가 10,000원)\n■ 납기: 10월 30일 납품 가능", v1)
        en0 = mcmail.draft("E-1001", regen=True, lang="en")["email"]["flow"]["draft"]   # 변형 2 → 짝수 / variant 2 is even
        self.assertEqual(en0, "Dear 박지현 대리,\n\nThe unit price for 카밍 세럼 50g 300EA is KRW 9,500,\n"
                              "and we can deliver by your requested date of October 30.\n\n"
                              "Please review it and let us know whether you would like to proceed with the order."
                              "\n\nBest regards,\n김영업\nM Cosmetic")
        r = mcmail.run_erp("E-1003")["email"]["flow"]["draft"]
        self.assertIn("수량 변경(500 EA → 1000 EA) 요청에 따라 단가를 다시 확인했습니다.\n하이드라 세럼 50g 1,000EA 기준 단가는 9,500원이며,", r)
        en1 = mcmail.draft("E-1003", regen=True, lang="en")["email"]["flow"]["draft"]
        self.assertIn("Please find our revised quote below.", en1)
        self.assertIn("■ Delivery: October 30, deliverable", en1)

    def test_stock_invoice_ship_order_drafts(self):
        short = mcmail.run_erp("E-1021")["email"]["flow"]["draft"]
        self.assertIn("요청하신 600EA 중 270EA가 부족합니다.\n다음 입고는 10월 23일 1,500EA 예정이며", short)
        self.assertIn("■ 공급 가능 여부: 부족, 다음 입고 2026-10-23 (1,500EA)", mcmail.draft("E-1021", regen=True)["email"]["flow"]["draft"])
        self.assertIn("so the requested 100EA can be supplied right away.", mcmail.run_erp("E-1020", lang="en")["email"]["flow"]["draft"])
        inv = mcmail.run_erp("E-1022")
        self.assertEqual(inv["toast"]["msg"], "인보이스를 첨부한 메일 초안을 작성했습니다. 확인 후 발송해 주세요.")
        self.assertIn("요청하신 SO-20260930-00102 건의 인보이스(INV-20260930-00102)를 첨부하여 보내드립니다.\n\n"
                      "카밍 크림 50g 800EA, 합계 9,715,200원 (VAT 포함)입니다.", inv["email"]["flow"]["draft"])
        self.assertIn("■ Total: KRW 9,715,200", mcmail.draft("E-1022", regen=True, lang="en")["email"]["flow"]["draft"])
        ship = mcmail.run_erp("E-1006")["email"]["flow"]
        self.assertEqual((ship["erpResult"]["matchedBy"], ship["erpApi"]), (1, "GET /api/erp/v1/shipments?so=SO-20260930-00102"))
        self.assertIn("현재 출하 준비 중이며 10월 9일 출하 예정입니다.", ship["draft"])
        # 초안이 이미 있으면 regen 없는 draft 는 유지하므로 EN 첫 변형은 make_draft 로 본다
        # an existing draft is kept without regen, so the first EN variant is checked through make_draft
        self.assertIn("It is currently being prepared for shipment and is scheduled to ship on October 9.",
                      mcmail.make_draft(self.mail("E-1006"), 0, "en"))
        self.assertIn("■ Delivery status: Preparing shipment", mcmail.draft("E-1006", regen=True, lang="en")["email"]["flow"]["draft"])
        transit = mcmail.draft("E-1007")["email"]["flow"]["draft"]
        self.assertIn("10월 4일 출하되어 현재 배송 중입니다.\n운송장 번호는 CJ-6120-4458-9921입니다.", transit)
        mcmail.create_order("E-1005")
        order = mcmail.draft("E-1005")["email"]["flow"]["draft"]
        self.assertIn("글로우 세럼 50g 400EA 주문이 정상 접수되었으며, 11월 6일까지 납품 예정입니다.", order)
        self.assertTrue(order.endswith("\n\n감사합니다.\nM코스메틱 박민호 드림"))
        self.assertIn("scheduled for delivery by November 6.", mcmail.make_draft(self.mail("E-1005"), 0, "en"))
        self.assertIn("■ 단가: 10,450원", mcmail.draft("E-1005", regen=True)["email"]["flow"]["draft"])

    def test_greeting_and_signature_fallbacks(self):
        e = mcmail.run_erp("E-1020")["email"]
        e.update({"assignee": "", "senderName": ""})
        ko, en = mcmail.make_draft(e, 0), mcmail.make_draft(e, 0, "en")
        self.assertTrue(ko.startswith("안녕하세요, 온유리테일 23 님.") and ko.endswith("M코스메틱 영업담당 드림"))
        self.assertTrue(en.startswith("Dear 온유리테일 23,") and en.endswith("Best regards,\nSales team\nM Cosmetic"))
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.draft("E-1001")                                      # ERP 조회 전 / before the ERP lookup
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.draft("E-1020", lang="jp")


class SendTests(McmailBase):
    def test_send_creates_outbound_mail_and_case_status(self):
        mcmail.run_erp("E-1001")
        out = mcmail.send("E-1001")
        e, c = out["email"], out["case"]
        self.assertEqual(out["toast"], {"type": "success", "title": "이메일 발송 완료", "msg": "demo-2164f9e258@workspace.example 에게 발송했습니다."})
        self.assertEqual((e["flow"]["mail"], e["flow"]["messageId"], e["flow"]["mailApi"], e["workStatus"]),
                         ("sent", "MSG-00001", "POST /api/mail/v1/send", "견적 회신 완료"))
        sent = mcmail.get_email("E-3043")["email"]
        self.assertEqual({k: sent[k] for k in ("direction", "caseId", "subject", "recipient", "intent", "summary", "receivedDate")},
                         {"direction": "out", "caseId": "RFQ-2026-00123", "subject": "Re: 카밍 세럼 견적 문의드립니다",
                          "recipient": "demo-2164f9e258@workspace.example", "intent": "견적 회신",
                          "summary": "300EA 기준 9,500원 / 예상 납기 10월 27일", "receivedDate": "2026-10-05 12:05"})
        self.assertEqual(sent["body"], e["flow"]["draft"])
        self.assertEqual((c["status"], c["entity"]["unitPrice"]), ("견적 회신 완료", 9500))
        self.assertEqual([(a["actionType"], a["status"], a["result"]) for a in c["actions"]],
                         [("ERP 단가 조회", "완료", "적용단가 9,500원 / 재고 1,200EA"), ("Email 발송", "완료", "견적 회신 발송")])
        self.assertEqual(out["log"][0]["text"], "누리뷰티 02 · 견적 회신 메일 발송 완료")
        self.assertEqual(self.peek()["outbox"][0]["to"], "demo-2164f9e258@workspace.example")
        tl = mcmail.get_case("RFQ-2026-00123")["timeline"]
        self.assertEqual([x["type"] for x in tl], ["mail", "action", "mail"])
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.send("E-1001")

    def test_draft_save_and_send_with_text(self):
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.send("E-1020")                                        # ERP 조회 전 / before the lookup
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.save_draft("E-1020", "초안 없이 저장")                  # 초안이 있어야 저장 / needs an existing draft
        mcmail.run_erp("E-1020")
        out = mcmail.save_draft("E-1020", "수정한 본문")
        self.assertEqual((out["email"]["flow"]["mail"], out["email"]["workStatus"], out["toast"]["title"]),
                         ("saved", "답변 임시저장", "임시저장 완료"))
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.send("E-1020", "   ")
        out = mcmail.send("E-1020", "최종 본문")
        self.assertEqual(out["email"]["flow"]["draft"], "최종 본문")
        self.assertEqual(out["case"]["status"], "재고 안내 완료")

    def test_closed_mail_keeps_draft_frozen_except_order_confirmation(self):
        # 완료처리한 견적 메일의 남은 초안은 저장·다시 생성·발송 모두 막는다(발송과 같은 완료 규칙)
        # a completed quote mail's leftover draft can no longer be saved, regenerated or sent (same closed rule)
        mcmail.set_entity("E-1011", "customerCode", "CUST-00002", triage=True)
        mcmail.run_erp("E-1011")
        mcmail.complete("E-1011")
        for blocked in (lambda: mcmail.save_draft("E-1011", "완료 뒤 수정"), lambda: mcmail.draft("E-1011", regen=True),
                        lambda: mcmail.send("E-1011")):
            with self.assertRaises(mcmail.MailValidationError):
                blocked()
        # 주문 메일은 등록(완료) 뒤에도 주문확인 메일을 쓰고 저장할 수 있다 / an order mail may still save its confirmation
        mcmail.create_order("E-1005")
        mcmail.draft("E-1005")
        out = mcmail.save_draft("E-1005", "주문확인 본문")
        self.assertEqual((out["email"]["flow"]["draft"], out["email"]["flow"]["mail"]), ("주문확인 본문", "saved"))


class ErrorTests(McmailBase):
    def test_erp_error_register_repeat_and_resolve(self):
        mcmail.set_entity("E-1020", "itemCode", "MC-NOPE")
        out = mcmail.run_erp("E-1020")
        self.assertEqual(out["toast"], {"type": "error", "title": "ERP 조회 실패", "msg": "Item Code가 ERP에 등록되어 있지 않습니다."})
        self.assertEqual((out["email"]["status"], out["email"]["workStatus"]), ("오류", "ERP 조회 실패"))
        err = out["errors"][0]
        self.assertEqual({k: err[k] for k in ("id", "category", "failedAction", "tries", "customer", "caseId", "workType")},
                         {"id": "ERR-0009", "category": "ERP 조회 실패", "failedAction": "ERP 재고 조회", "tries": 1,
                          "customer": "온유리테일 23", "caseId": "INQ-2026-00041", "workType": "stock"})
        self.assertEqual(out["log"][0]["text"], "온유리테일 23 · ERP 재고 조회 실패")
        out = mcmail.run_erp("E-1020")
        self.assertEqual((len(out["errors"]), out["errors"][0]["tries"]), (3, 2))
        mcmail.set_entity("E-1020", "itemCode", "MC-CAL-SR050")
        out = mcmail.run_erp("E-1020")
        self.assertEqual(out["email"]["status"], "진행 중")
        self.assertEqual([x["id"] for x in out["errors"]], ["ERR-0008", "ERR-0006"])


class ScenarioTests(McmailBase):
    def test_sequential_injection_with_auto_complete(self):
        for n, exc in ((1, mcmail.MailValidationError), (3, mcmail.MailValidationError), (7, mcmail.MailNotFound)):
            with self.assertRaises(exc):
                mcmail.inject_scenario(n)
        out = mcmail.inject_scenario(2)
        self.assertEqual(out["toast"], {"type": "info", "title": "새 메일 수신 · AI 분석 완료",
                                        "msg": "견적요청 / 확인 / 보류 · STEP 1까지 남은 작업은 자동 완료했습니다."})
        self.assertEqual((out["email"]["emailId"], out["email"]["status"], out["email"]["nextStep"]["k"]), ("E-2002", "처리 대기", "close"))
        self.assertEqual(self.mail("E-1001")["status"], "완료")                 # 자동 완료 / auto-completed
        self.assertEqual((out["case"]["status"], out["case"]["request"]), ("고객 검토 중", "고객 내부 검토 중"))
        out = mcmail.inject_scenario(3)
        self.assertEqual(self.mail("E-2002")["workStatus"], "고객 검토 중")
        self.assertEqual(out["email"]["delta"]["changed"][0], {"field": "quantity", "label": "수량", "prev": "300 EA", "cur": "500 EA", "raw": 500})
        self.assertEqual((out["case"]["entity"]["quantity"], out["case"]["prev"]["quantity"], out["case"]["status"]),
                         (500, 300, "수정견적 필요"))
        out = mcmail.inject_scenario(4)
        self.assertEqual(out["case"]["entity"]["unitPrice"], 9200)
        self.assertEqual(out["email"]["delta"]["changed"][0],
                         {"field": "deliveryDate", "label": "납기일", "prev": "2026-10-30", "cur": "2026-11-04", "raw": "2026-11-04"})
        self.assertEqual((out["case"]["status"], out["case"]["request"]), ("주문등록 필요", "500EA 주문 확정, 11/4 납기"))
        self.assertEqual(out["email"]["entities"]["deliveryDate"]["value"], "2026-11-04")
        out = mcmail.inject_scenario(5)
        self.assertEqual((out["case"]["salesOrderNumber"], out["case"]["caseType"], out["case"]["status"]),
                         ("SO-20261005-00125", "견적 → 주문", "출하 문의 접수"))
        self.assertEqual(self.peek()["shipments"]["SO-20261005-00125"]["shipDate"], "2026-11-02")
        out = mcmail.inject_scenario(6)
        self.assertEqual(out["case"]["status"], "출하 안내 완료")
        self.assertEqual(out["email"]["entities"]["salesOrder"]["value"], "SO-20261005-00125")
        inv = mcmail.run_erp("E-2006")["email"]["flow"]["erpResult"]
        self.assertEqual((inv["price"], inv["total"]), (9200, 5060000))
        self.assertEqual([s["state"] for s in mcmail.dashboard()["scenario"]], ["done"] * 5 + ["act"])
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.inject_scenario(6)


class QueryTests(McmailBase):
    def test_lists_dashboard_search_notifications(self):
        d = mcmail.dashboard()
        self.assertEqual(d["kpi"], {"recv": 19, "auto": 13, "review": 6, "erp": 2, "err": 2})
        self.assertEqual([t["n"] for t in d["tiers"]], N_TIERS)
        self.assertEqual([x["emailId"] for x in d["todo"]][:3], ["E-1008", "E-1012", "E-1016"])
        self.assertEqual(mcmail.dashboard("2026-10-04")["kpi"]["recv"], 6)   # 전날 수신분(발신 메일 제외) / inbound only
        self.assertEqual(mcmail.dashboard("2099-01-01")["date"], "2026-10-05")
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.dashboard("10/04")
        inbox = mcmail.list_emails("inbox")
        self.assertEqual((inbox["counts"], [x["emailId"] for x in inbox["items"]][:2]), ({"todo": 6, "all": N_INBOUND}, ["E-1016", "E-1011"]))
        q = mcmail.list_emails("quote", "all", date_from="2026-10-05", date_to="2026-10-05")
        self.assertEqual([x["emailId"] for x in q["items"]], ["E-1003", "E-1001", "E-1002"])
        self.assertEqual(mcmail.list_emails("order", "err")["items"][0]["emailId"], "E-1008")
        self.assertEqual([x["emailId"] for x in mcmail.list_emails("quote", "todo", q="하이드라")["items"]], ["E-1003"])
        self.assertEqual(mcmail.list_emails()["total"], 19)   # 수신 32 - 완료 13 / 32 inbound minus 13 closed
        for bad in (lambda: mcmail.list_emails("nope"), lambda: mcmail.list_emails("inbox", "err"),
                    lambda: mcmail.list_cases("nope"), lambda: mcmail.list_errors("nope")):
            with self.assertRaises(mcmail.MailValidationError):
                bad()
        self.assertTrue(all("견적" in c["caseType"] for c in mcmail.list_cases("견적")["items"]))
        self.assertEqual(len(mcmail.list_cases("done")["items"]), N_CASES_DONE)
        s = mcmail.search("누리뷰티")
        self.assertEqual([c["caseId"] for c in s["cases"]], ["RFQ-2026-00123"])
        self.assertIn("E-1001", [m["emailId"] for m in s["mails"]])
        n = mcmail.notifications()
        self.assertEqual((n["count"], len(n["errors"]), len(n["triage"])), (8, 2, 6))
        detail = mcmail.get_email("E-1003")
        self.assertEqual([m["emailId"] for m in detail["thread"]], ["E-3009", "E-3008", "E-3007"])   # 최신순 / newest first
        self.assertEqual(detail["case"]["caseId"], "RFQ-2026-00120")
        self.assertEqual(mcmail.meta()["nav"], {"inbox": 6, "errors": 2, "quote": 3, "order": 2, "ship": 3, "stock": 2,
                                                "invoice": 1, "etc": 2, "notif": 8})

    def test_assign_propagates(self):
        out = mcmail.assign("case", "ORD-2026-00122", "이수진")
        self.assertIsNone(out["email"])
        self.assertEqual(out["case"]["assignedUser"], "이수진")
        self.assertEqual(self.mail("E-1008")["assignee"], "이수진")
        self.assertEqual(next(x for x in out["errors"] if x["id"] == "ERR-0008")["assignee"], "이수진")
        self.assertEqual(out["toast"]["msg"], "이수진 님에게 배정했습니다.")
        self.assertEqual(mcmail.assign("mail", "E-1013", "정하늘")["email"]["assignee"], "정하늘")
        for bad in (lambda: mcmail.assign("x", "E-1013", "정하늘"), lambda: mcmail.assign("mail", "E-1013", "홍길동")):
            with self.assertRaises(mcmail.MailValidationError):
                bad()
        with self.assertRaises(mcmail.MailNotFound):
            mcmail.assign("case", "RFQ-0", "정하늘")


class LookupTests(McmailBase):
    def test_all_targets(self):
        n_q, n_i = mcmail.list_emails("quote", "all")["total"], mcmail.list_emails("invoice", "all")["total"]   # 이력 포함 / history included
        expect = {"inbox": "**6건**", "today": "10월 5일", "quotes": f"견적요청 메일은 전체 **{n_q}건**",
                  "orders": "ERP API Timeout", "shipments": "### ERP 출하내역", "stock": "MC-CIC-SR050",
                  "invoices": f"인보이스 발행요청 메일은 전체 **{n_i}건**", "cases": f"업무 Case는 전체 **{N_CASES}건**",
                  "errors": "미해결 API 오류는 **2건**", "customer": "**누리뷰티 02** (CUST-00002)", "case": "**RFQ-2026-00123**"}
        args = {"customer": {"customer": "누리뷰티"}, "case": {"case_id": "rfq-2026-00123"}}
        self.assertEqual(set(expect), set(mcmail.LOOKUP_TARGETS))
        for target, marker in expect.items():
            data, task, line = mcmail.lookup(target, args.get(target))
            self.assertEqual(data["target"], target)
            self.assertTrue(task and line, target)
            text = mcmail.fallback_answer(data, task)
            self.assertIn(marker, text, target)
            self.assertNotIn("[[", text)
        self.assertEqual(mcmail.lookup("stock")[0]["inventory"][5]["available"], 330)
        self.assertEqual(len(mcmail.lookup("shipments")[0]["shipments"]), len(mcmail._SEED["SHIPMENTS"]))  # noqa: SLF001
        self.assertEqual(mcmail.lookup("cases")[0]["counts"], {"open": N_CASES - N_CASES_DONE, "done": N_CASES_DONE, "all": N_CASES})
        data, task, _ = mcmail.lookup("customer", {"customer": "누리"})
        self.assertEqual(len(data["candidates"]), 4)
        self.assertIn("4곳", mcmail.fallback_answer(data, task))
        data, task, _ = mcmail.lookup("customer", {"customer": "없는회사"})
        self.assertIn("찾지 못했습니다", mcmail.fallback_answer(data, task))
        data, task, _ = mcmail.lookup("case", {"case_id": "RFQ-0000-00000"})
        self.assertTrue(data["missing"])
        with self.assertRaises(mcmail.MailValidationError):
            mcmail.lookup("nope")


class ReviewFixTests(McmailBase):
    """적대 검증 10건 회귀 / regressions for the 10 adversarial-review findings (2026-09-28)"""

    def client(self):
        app = FastAPI()
        app.include_router(mcmail_api.router)
        app.include_router(mock_mcosmetic.router)
        return TestClient(app)

    def edit_state(self, email_id, fn):
        """저장된 메일을 직접 고친다(옛 데이터·경계 상태 재현용) / edit a stored mail directly (legacy or edge states)"""
        with mcmail._session(write=True) as st:  # noqa: SLF001
            fn(st.mail(email_id), st)

    # 1 — 보류 중 재처리 차단 + 닫는 경로는 보류를 푼다 / retry refuses a held mail; every close path clears the hold
    def test_1_order_retry_respects_hold_and_closing_clears_hold(self):
        mcmail.hold("E-1008", True)
        with self.assertRaisesRegex(mcmail.MailValidationError, "보류 중"):
            mcmail.retry("ERR-0008")
        e = self.mail("E-1008")
        self.assertEqual((e["closed"], e["flow"]["order"]), (False, "error"))
        self.assertEqual(mcmail.list_errors("open")["counts"]["open"], 2)
        mcmail.hold("E-1008", False)
        out = mcmail.retry("ERR-0008")
        self.assertEqual((out["email"]["closed"], out["email"]["hold"], out["toast"]["title"]), (True, False, "주문등록 완료"))
        # 시나리오 자동 완료: 보류한 STEP 3(견적)·STEP 4(주문) 메일도 닫히면서 보류가 풀리고, 주문확인 메일을 쓸 수 있다
        # scenario auto-complete: held STEP 3 (quote) and STEP 4 (order) mails close with the hold cleared
        mcmail.inject_scenario(2)
        mcmail.inject_scenario(3)
        mcmail.hold("E-2003", True)
        mcmail.inject_scenario(4)
        self.assertEqual({k: self.mail("E-2003")[k] for k in ("closed", "hold", "status")},
                         {"closed": True, "hold": False, "status": "완료"})
        mcmail.hold("E-2004", True)
        mcmail.inject_scenario(5)
        e = self.mail("E-2004")
        self.assertEqual((e["closed"], e["hold"], e["flow"]["order"]), (True, False, "done"))
        self.assertIn("SO-20261005-00125", mcmail.draft("E-2004")["email"]["flow"]["draft"])
        self.assertEqual(mcmail.send("E-2004")["email"]["flow"]["mail"], "sent")

    # 2 — draft-save 는 draft 키 필수(send 와 같은 키), entity 는 value 필수 / draft key required; value required
    def test_2_draft_save_requires_the_draft_key_and_entity_requires_value(self):
        c = self.client()
        c.post("/api/email/mails/E-1001/erp")
        before = self.mail("E-1001")["flow"]["draft"]
        for body in ({}, {"text": "옛 키"}, {"draft": None}):
            self.assertEqual(c.post("/api/email/mails/E-1001/draft-save", json=body).status_code, 422, body)
        self.assertEqual(self.mail("E-1001")["flow"]["draft"], before)            # 지워지지 않았다 / not blanked
        r = c.post("/api/email/mails/E-1001/draft-save", json={"draft": "고친 본문"}).json()
        self.assertEqual((r["email"]["flow"]["draft"], r["email"]["flow"]["mail"]), ("고친 본문", "saved"))
        r = c.post("/api/email/mails/E-1001/send", json={"draft": "보낼 본문"}).json()   # 같은 키 / the same key
        self.assertEqual((r["email"]["status"], r["email"]["flow"]["draft"]), ("완료", "보낼 본문"))
        self.assertEqual(c.post("/api/email/mails/E-1005/entity", json={"field": "quantity"}).status_code, 422)
        self.assertEqual(self.mail("E-1005")["entities"]["quantity"]["value"], "400")
        mcmail.run_erp("E-1020")
        text = self.mail("E-1020")["flow"]["draft"]
        out = mcmail.save_draft("E-1020", None)                                    # None = 본문 유지 / keep the body
        self.assertEqual((out["email"]["flow"]["draft"], out["email"]["flow"]["mail"]), (text, "saved"))

    # 3 — 값은 저장 때 trim, 주문은 trim 값 하나로 SO·단가·결과·Case·출하 / trimmed on save; orders use one trimmed set
    def test_3_entity_values_are_trimmed_and_orders_use_the_trimmed_values(self):
        out = mcmail.set_entity("E-1005", "deliveryDate", " 2026-11-06 ")
        self.assertEqual(out["email"]["entities"]["deliveryDate"]["value"], "2026-11-06")

        def pad(e, st):   # 이 수정 전에 저장됐을 법한 공백 섞인 값 / padded values stored before this fix
            e["entities"]["itemCode"]["value"] = "MC-GLW-SR050 "
            e["entities"]["quantity"]["value"] = " 500"
            e["entities"]["deliveryDate"]["value"] = "2026-11-06 "
            e["entities"]["customerCode"]["value"] = " CUST-00033"
        self.edit_state("E-1005", pad)
        self.assertEqual(self.mail("E-1005")["orderPrice"], 10120)                # 500EA 구간(케이스 단가 10,450 아님) / tier price
        out = mcmail.create_order("E-1005")
        r = out["email"]["flow"]["orderResult"]
        self.assertEqual((r["so"], r["date"], r["qty"], r["price"]), ("SO-20261005-00126", "2026-11-06", 500, 10120))
        sh = self.peek()["shipments"]["SO-20261005-00126"]
        self.assertEqual((sh["customerCode"], sh["itemCode"], sh["shipDate"]), ("CUST-00033", "MC-GLW-SR050", "2026-11-04"))
        self.assertEqual((out["case"]["entity"]["deliveryDate"], out["case"]["entity"]["unitPrice"]), ("2026-11-06", 10120))

    # 4 — mock 은 시나리오 고정 번호를 못 가져가고, 다른 내용의 기존 SO 는 409 / no scenario number via mock; 409 on conflict
    def test_4_mock_cannot_take_the_scenario_number_and_conflicts_are_409(self):
        c = self.client()
        url = "/mock/mcosmetic/erp/v1/sales-orders"
        body = {"customerCode": "CUST-00011", "itemCode": "MC-HYD-SR050", "quantity": 1000, "deliveryDate": "2026-11-20"}
        r = c.post(url, json={**body, "caseId": "RFQ-2026-00123"}, headers=AUTH)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (422, "invalid"))
        self.assertNotIn("SO-20261005-00125", self.peek()["shipments"])
        r = c.post(url, json={**body, "caseId": "ORD-2026-00124"}, headers=AUTH)   # 다른 caseId 는 번호에 영향 없음 / no effect
        self.assertEqual((r.status_code, r.json()["so"]), (201, "SO-20261005-00126"))
        with mcmail._session(write=True) as st:  # noqa: SLF001 — 순번이 어긋난 상태 재현 / a desynced sequence
            st.seq["so"] = 125
        r = c.post(url, json={**body, "quantity": 5}, headers=AUTH)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "conflict"))
        self.assertEqual(self.peek()["shipments"]["SO-20261005-00126"]["orderQty"], 1000)   # 섞이지 않았다 / not mixed
        with mcmail._session(write=True) as st:  # noqa: SLF001
            st.seq["so"] = 125
        r = c.post(url, json=body, headers=AUTH)                                    # 같은 내용은 그대로 / same content reuses
        self.assertEqual((r.status_code, r.json()["so"], r.json()["qty"]), (201, "SO-20261005-00126", 1000))
        for n in (2, 3, 4):
            mcmail.inject_scenario(n)
        self.assertEqual(mcmail.create_order("E-2004")["email"]["flow"]["orderResult"]["so"], "SO-20261005-00125")
        mcmail.link_case("E-1005", "RFQ-2026-00123")                                # 같은 Case 의 두 번째 주문 / second order
        self.assertEqual(mcmail.create_order("E-1005")["email"]["flow"]["orderResult"]["so"], "SO-20261005-00127")

    # 5 — 완료된 비주문 메일은 발송·재조회·재처리 불가(완료하면 오류도 닫혀 재처리는 '이미 해결'), 주문 메일은 등록 뒤
    #     주문확인만 / final rule for completed mails (completion also closes their errors, so a retry is 'already resolved')
    def test_5_retry_follows_the_direct_call_guards_on_completed_mails(self):
        mcmail.complete("E-1012")
        with self.assertRaisesRegex(mcmail.MailValidationError, "이미 해결된 오류"):
            mcmail.retry("ERR-0006")
        self.assertEqual(self.peek()["outbox"], [])                                  # 보내지 않았다 / nothing sent
        with self.assertRaisesRegex(mcmail.MailValidationError, "이미 완료된 메일"):
            mcmail.send("E-1012")
        mcmail.set_entity("E-1020", "itemCode", "MC-NOPE")
        err = mcmail.run_erp("E-1020")["errors"][0]["id"]
        mcmail.complete("E-1020")
        with self.assertRaisesRegex(mcmail.MailValidationError, "이미 해결된 오류"):
            mcmail.retry(err)
        with self.assertRaisesRegex(mcmail.MailValidationError, "이미 완료된 메일"):
            mcmail.run_erp("E-1020")
        mcmail.complete("E-1008")
        with self.assertRaisesRegex(mcmail.MailValidationError, "이미 해결된 오류"):
            mcmail.retry("ERR-0008")
        mcmail.create_order("E-1005")                                                # 주문확인 메일은 허용 / confirmation allowed
        mcmail.draft("E-1005")
        self.assertEqual(mcmail.send("E-1005")["email"]["flow"]["mail"], "sent")

    # 6a — triage 는 지금 확인 필요 항목일 때만 / triage only for an open review item
    def test_6a_triage_needs_an_open_item(self):
        before = (self.mail("E-1001")["workStatus"], mcmail.recent_log(1))
        with self.assertRaisesRegex(mcmail.MailValidationError, "확인이 필요한 항목이 아닙니다"):
            mcmail.set_entity("E-1001", "quantity", "500", triage=True)
        self.assertEqual((self.mail("E-1001")["workStatus"], mcmail.recent_log(1)), before)
        self.assertEqual(mcmail.set_entity("E-1009", "itemCode", "MC-GLW-SR050", triage=True)["toast"]["title"], "확인 완료")

    # 6b — ERP 조회 뒤 조회 조건이 바뀌면 두 경로 모두 erpStale / erpStale on both paths after the lookup
    def test_6b_both_edit_paths_flag_a_stale_lookup(self):
        mcmail.run_erp("E-1020")
        self.edit_state("E-1020", lambda e, st: e["entities"].update(itemCode={"value": "MC-CAL-SR050", "conf": .5, "src": "ai"}))
        self.assertFalse(self.mail("E-1020")["flow"]["erpStale"])
        out = mcmail.set_entity("E-1020", "itemCode", "MC-CAL-SR050", triage=True)   # 트리아지 경로 / triage path
        self.assertTrue(out["email"]["flow"]["erpStale"])
        mcmail.run_erp("E-1021")
        self.assertFalse(mcmail.set_entity("E-1021", "itemName", "시카 세럼")["email"]["flow"]["erpStale"])   # 조회 조건 아님 / not a key
        self.assertTrue(mcmail.set_entity("E-1021", "quantity", "700")["email"]["flow"]["erpStale"])         # 자유 편집 / free edit

    # 6c — 보류 중 작업이 바꾼 작업 상태는 해제 때 되돌리지 않는다 / release keeps a status changed during the hold
    def test_6c_release_keeps_a_status_changed_during_the_hold(self):
        mcmail.hold("E-1021", True)
        mcmail.run_erp("E-1021")                                                     # 보류 중 첫 조회 / first lookup while held
        out = mcmail.hold("E-1021", False)
        self.assertEqual((out["email"]["workStatus"], out["email"]["status"]), ("답변 검토 중", "진행 중"))
        mcmail.hold("E-1020", True)
        self.assertEqual(mcmail.hold("E-1020", False)["email"]["workStatus"], "재고 조회필요")   # 그대로면 복원 / restored

    # 6d — regen 이 아니면 고친 초안을 덮어쓰지 않는다 / a non-regen draft keeps the edited text
    def test_6d_non_regen_draft_keeps_the_edited_text(self):
        mcmail.run_erp("E-1020")
        mcmail.save_draft("E-1020", "담당자가 고친 본문")
        out = mcmail.draft("E-1020")
        self.assertEqual((out["email"]["flow"]["draft"], out["email"]["flow"]["mail"], out["toast"]),
                         ("담당자가 고친 본문", "saved", None))
        out = mcmail.draft("E-1020", regen=True)
        self.assertNotEqual(out["email"]["flow"]["draft"], "담당자가 고친 본문")
        self.assertEqual(out["toast"]["title"], "AI 답변 생성 완료")

    # 6e — 기타·미분류 메일은 초안 저장 불가(진행 중으로 바뀌지 않는다) / no draft save on etc or unclassified mails
    def test_6e_etc_and_unclassified_mails_refuse_draft_save(self):
        self.edit_state("E-1013", lambda e, st: e["flow"].update(draft="남은 본문"))
        for eid in ("E-1013", "E-1016"):
            with self.assertRaisesRegex(mcmail.MailValidationError, "답변 메일을 작성할 수 없는 메일"):
                mcmail.save_draft(eid, "본문")
        self.assertEqual((self.mail("E-1016")["status"], self.mail("E-1013")["flow"].get("mail")), ("미분류", None))

    # 7 — '실행은 화면에서' 배너는 명령·요청 어미에만 / the banner only for imperative requests
    def test_7_ask_banner_only_for_imperatives(self):
        c = self.client()
        cases = {"오늘 처리해야 할 메일 알려줘": False, "인보이스 보내달라는 메일 있어?": False, "발송된 메일 알려줘": False,
                 "확인 필요한 메일 답장 보내줘": True, "E-1001 발송해 줘": True, "완료 처리해 주세요": True}
        with patch("app.llm.generate", return_value={"target": "inbox"}):
            for q, banner in cases.items():
                body = c.post("/api/email/ask", json={"question": q}).json()
                self.assertEqual(body["answer"].startswith("> 발송이나 주문등록 같은 **실행**은"), banner, q)
                lines = body["exec"]["think"]["groups"][2]["lines"]
                self.assertEqual(any("화면에서 진행하도록" in x for x in lines), banner, q)

    # 8 — 쓰기 세션은 상태를 읽기 전에 DB 쓰기 잠금 / write sessions take the DB lock before loading
    def test_8_write_session_waits_for_another_process_and_reads_fresh_state(self):
        mcmail.run_erp("E-1001")
        other = sqlite3.connect(self.db_path, timeout=5)   # 같은 DB 를 쓰는 다른 서버 프로세스 / another server process
        self.addCleanup(other.close)
        other.execute("BEGIN IMMEDIATE")
        seq = json.loads(other.execute("SELECT value FROM mc_meta WHERE key='seq'").fetchone()[0])
        data = json.loads(other.execute("SELECT data FROM mc_emails WHERE email_id='E-3009'").fetchone()[0])
        other.execute("INSERT INTO mc_emails(email_id, data, received_at, direction, case_id, classification, closed)"
                      " VALUES ('E-3043', ?, ?, 'out', ?, '', 1)",
                      (json.dumps({**data, "emailId": "E-3043"}, ensure_ascii=False), data["receivedDate"], data["caseId"]))
        other.execute("UPDATE mc_meta SET value=? WHERE key='seq'", (json.dumps({**seq, "mail": 3043}),))
        res = {}

        def work():
            try:
                res["out"] = mcmail.send("E-1001")
            except Exception as exc:  # noqa: BLE001 — 스레드 밖에서 검사 / checked outside the thread
                res["err"] = exc
        t = threading.Thread(target=work)
        t.start()
        time.sleep(0.5)                  # 작업 스레드가 잠금을 기다리는 동안 / while the worker waits on the lock
        other.commit()
        t.join(10)
        self.assertFalse(t.is_alive())
        self.assertNotIn("err", res, res.get("err"))
        ids = [r[0] for r in self.rows("SELECT email_id FROM mc_emails WHERE email_id IN ('E-3043', 'E-3044') ORDER BY email_id")]
        self.assertEqual(ids, ["E-3043", "E-3044"])
        self.assertEqual(mcmail.get_email("E-3044")["email"]["caseId"], "RFQ-2026-00123")

    # 9 — 스키마 없음만 복구, 잠김 등은 그대로 올린다 / only a missing schema is recovered
    def test_9_session_recovers_only_a_missing_schema(self):
        with patch.object(mcmail, "_State", side_effect=sqlite3.OperationalError("database is locked")), \
                patch.object(mcmail, "_init_conn") as init:
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                mcmail.meta()
            init.assert_not_called()
        conn = sqlite3.connect(self.db_path)
        with conn:
            for t in ("mc_emails", "mc_cases", "mc_errors", "mc_log", "mc_meta"):
                conn.execute(f"DROP TABLE {t}")
        conn.close()
        self.assertEqual((mcmail.meta()["today"], self.rows("SELECT COUNT(*) FROM mc_emails")[0][0]), ("2026-10-05", N_MAILS))

    # 10 — 재기준은 사용자 글의 '[[…]]' 를 날짜로 바꾸지 않는다 / re-anchoring leaves user '[[…]]' text alone
    def test_10_reanchor_leaves_user_brackets_alone(self):
        mcmail.run_erp("E-1001")
        mcmail.save_draft("E-1001", "메모 [[D+3]] 와 [[[D+1]]] 그리고 10월 30일 \ue000[끝")
        mcmail.set_entity("E-1005", "shippingAddress", "인천 창고 [[K+1]] 동")
        self.today.return_value = date(2026, 10, 7)
        mcmail.init_mcmail()
        self.assertEqual(self.mail("E-1001")["flow"]["draft"], "메모 [[D+3]] 와 [[[D+1]]] 그리고 11월 1일 \ue000[끝")
        self.assertEqual(self.mail("E-1005")["entities"]["shippingAddress"]["value"], "인천 창고 [[K+1]] 동")
        self.assertEqual(self.mail("E-1001")["receivedDate"], "2026-10-07 09:13")   # 진짜 날짜는 옮긴다 / real dates move
        d0 = date(2026, 10, 5)
        for s in ("[[D+0]]", "[[[C-1]]]", "\ue000(", "\ue000\ue000[", "a[b[[c]]", "SO-20261005-00125 [x]"):
            self.assertEqual(mcmail._shift(s, d0, d0), s)  # noqa: SLF001
        self.assertEqual(mcmail._shift("[2026-10-05] [[Y+0]]", d0, date(2026, 10, 7)), "[2026-10-07] [[Y+0]]")  # noqa: SLF001


class ErrorSettleTests(McmailBase):
    """재처리할 작업이 없는 오류는 닫는다(완료·보관·스팸·분류 변경 등) / errors with nothing left to retry are closed"""

    def open_ids(self):
        return [x["id"] for x in mcmail.list_errors("open")["items"]]

    def add_legacy_error(self, email_id, category="ERP 조회 실패"):
        """이 정책 전에 남았을 법한 막다른 오류를 직접 넣는다 / insert a dead-end error as older data could hold"""
        with mcmail._session(write=True) as st:  # noqa: SLF001
            e = st.mail(email_id)
            st.errors.insert(0, {"id": "ERR-0900", "time": f"{st.today} 09:00", "emailId": email_id, "caseId": e.get("caseId") or "",
                                 "customer": e.get("customer"), "workType": e.get("classification"), "category": category,
                                 "failedAction": "ERP 단가 조회", "message": "옛 오류", "status": "open",
                                 "assignee": e.get("assignee"), "tries": 1})

    def test_complete_closes_the_mails_open_errors_everywhere(self):
        before = (mcmail.dashboard()["kpi"]["err"], mcmail.notifications()["count"], mcmail.meta()["nav"]["errors"])
        self.assertEqual(before, (2, 8, 2))
        out = mcmail.complete("E-1012")
        self.assertEqual([x["id"] for x in out["errors"]], ["ERR-0008"])              # 응답의 미해결 목록 / open list in the reply
        x = next(x for x in mcmail.list_errors("all")["items"] if x["id"] == "ERR-0006")
        self.assertEqual(x["status"], "resolved")
        self.assertTrue(x["resolvedAt"].startswith("2026-10-05 "))
        self.assertEqual((mcmail.dashboard()["kpi"]["err"], mcmail.notifications()["count"], mcmail.meta()["nav"]["errors"]),
                         (1, 7, 1))
        self.assertEqual(self.open_ids(), ["ERR-0008"])

    def test_reclassify_and_scenario_close_errors_with_nothing_to_retry(self):
        # 분류 변경: flow 가 비워져 주문 오류를 다시 부를 수 없다 / reclassify: the flow reset leaves nothing to retry
        out = mcmail.classify("E-1008", "quote", intent="추가질문")
        self.assertNotEqual(out["email"]["status"], "오류")
        self.assertEqual(self.open_ids(), ["ERR-0006"])
        # 시나리오 자동 완료: 조회에 실패한 채 닫힌 이전 단계 메일의 오류도 남지 않는다
        # scenario auto-complete: a previous-step mail closed after a failed lookup keeps no open error
        mcmail.inject_scenario(2)
        mcmail.inject_scenario(3)
        mcmail.set_entity("E-2003", "itemCode", "MC-NOPE")
        err = mcmail.run_erp("E-2003")["errors"][0]["id"]
        self.assertEqual(self.open_ids(), [err, "ERR-0006"])
        mcmail.inject_scenario(4)
        self.assertEqual((self.mail("E-2003")["closed"], self.open_ids()), (True, ["ERR-0006"]))
        x = next(x for x in mcmail.list_errors("all")["items"] if x["id"] == err)
        self.assertEqual((x["status"], x["tries"]), ("resolved", 2))                # 자동 완료가 한 번 더 시도 / one more try

    def test_saving_or_redrafting_a_failed_send_keeps_the_error_until_it_is_sent(self):
        # 임시저장은 발송이 아니다 — 초안만 바뀌고 발송 실패 표시·오류 문구·작업 상태·미해결 오류는 그대로
        # saving is not sending: only the draft changes; the failed-send mark, its message, the work status and the error stay
        before = self.mail("E-1012")
        out = mcmail.save_draft("E-1012", "고친 본문")
        e = out["email"]
        self.assertEqual({k: e["flow"].get(k) for k in ("draft", "mail", "mailError", "draftSaved")},
                         {"draft": "고친 본문", "mail": "error", "mailError": before["flow"]["mailError"], "draftSaved": True})
        self.assertEqual((e["workStatus"], e["status"], e["nextStep"]["k"]), (before["workStatus"], "오류", "retry"))
        self.assertEqual(self.open_ids(), ["ERR-0008", "ERR-0006"])
        # 다시 생성·ERP 재조회로 초안이 바뀌어도 발송 실패는 남는다(임시저장 표시만 지워진다)
        # regenerating or re-querying the ERP replaces the draft but keeps the failed send (only the saved mark goes)
        e = mcmail.draft("E-1012", regen=True)["email"]
        self.assertEqual((e["flow"]["mail"], "draftSaved" in e["flow"], e["status"]), ("error", False, "오류"))
        e = mcmail.run_erp("E-1012")["email"]
        self.assertEqual((e["flow"]["mail"], bool(e["flow"]["draft"]), e["status"]), ("error", True, "오류"))
        self.assertEqual(self.open_ids(), ["ERR-0008", "ERR-0006"])
        # 실제 발송이 성공해야 닫힌다 / only an actual successful send closes it
        out = mcmail.retry("ERR-0006")
        self.assertEqual((out["toast"]["title"], out["email"]["flow"]["mail"], "draftSaved" in out["email"]["flow"]),
                         ("이메일 발송 완료", "sent", False))
        self.assertEqual(self.open_ids(), ["ERR-0008"])
        # 발송 실패가 아닌 메일은 종전대로 mail='saved' + draftSaved / a normal save keeps mail='saved' and adds draftSaved
        mcmail.run_erp("E-1020")
        f = mcmail.save_draft("E-1020", "본문")["email"]["flow"]
        self.assertEqual((f["mail"], f["draftSaved"]), ("saved", True))
        f = mcmail.send("E-1020", "바꾼 본문")["email"]["flow"]
        self.assertEqual((f["mail"], "draftSaved" in f), ("sent", False))

    def test_archive_spam_and_retry_close_leftover_errors(self):
        self.add_legacy_error("E-1013")
        mcmail.spam("E-1013")
        self.assertNotIn("ERR-0900", self.open_ids())
        mcmail.reset()
        self.add_legacy_error("E-1014")
        mcmail.archive("E-1014")
        self.assertNotIn("ERR-0900", self.open_ids())
        mcmail.reset()
        self.add_legacy_error("E-1001")                                             # 조회 오류 상태가 없는 열린 메일 / no ERP error state
        out = mcmail.retry("ERR-0900")
        self.assertEqual((out["toast"]["title"], out["toast"]["msg"]), ("재처리할 작업이 없습니다.", "해결됨"))
        self.assertEqual((self.mail("E-1001")["flow"], self.open_ids()), ({}, ["ERR-0008", "ERR-0006"]))   # 아무것도 부르지 않았다 / nothing ran


class ApiTests(McmailBase):
    def setUp(self):
        super().setUp()
        app = FastAPI()
        app.include_router(mcmail_api.router)
        app.include_router(mock_mcosmetic.router)
        self.client = TestClient(app)

    def test_reads_and_errors(self):
        c = self.client
        meta = c.get("/api/email/meta").json()
        self.assertEqual((meta["today"], len(meta["users"]), meta["nav"]["inbox"]), ("2026-10-05", 5, 6))
        self.assertEqual(c.get("/api/email/dashboard").json()["kpi"]["recv"], 19)
        self.assertEqual(c.get("/api/email/dashboard", params={"date": "bad"}).status_code, 422)
        r = c.get("/api/email/mails", params={"view": "quote", "filter": "all", "from": "2026-10-05", "to": "2026-10-05"}).json()
        self.assertEqual([x["emailId"] for x in r["items"]], ["E-1003", "E-1001", "E-1002"])
        self.assertEqual(c.get("/api/email/mails", params={"view": "inbox"}).json()["counts"]["todo"], 6)
        self.assertEqual(c.get("/api/email/mails", params={"view": "nope"}).status_code, 422)
        self.assertEqual(c.get("/api/email/mails/E-1001").json()["email"]["status"], "처리 대기")
        self.assertEqual(c.get("/api/email/mails/E-9999").status_code, 404)
        self.assertTrue(all("견적" in x["caseType"] for x in c.get("/api/email/cases", params={"filter": "견적"}).json()["items"]))
        self.assertEqual(c.get("/api/email/cases/RFQ-2026-00123").json()["timeline"][0]["type"], "mail")
        self.assertEqual(c.get("/api/email/cases/NOPE").status_code, 404)
        self.assertEqual(len(c.get("/api/email/errors", params={"status": "open"}).json()["items"]), 2)
        self.assertEqual(len(c.get("/api/email/log", params={"n": 3}).json()["items"]), 3)
        self.assertEqual(c.get("/api/email/search", params={"q": "누리뷰티"}).json()["cases"][0]["caseId"], "RFQ-2026-00123")
        self.assertEqual(c.get("/api/email/notifications").json()["count"], 8)

    def test_actions_round_trip(self):
        c = self.client
        r = c.post("/api/email/mails/E-1001/erp")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.json()), {"email", "case", "errors", "log", "toast", "nav"})
        self.assertEqual(r.json()["email"]["flow"]["erp"], "done")
        self.assertEqual(c.post("/api/email/mails/E-1001/order").status_code, 422)
        self.assertEqual(c.post("/api/email/mails/E-1001/draft", json={"regen": True, "lang": "en"}).json()["email"]["flow"]["variant"], 1)
        self.assertEqual(c.post("/api/email/mails/E-1001/draft-save", json={"draft": "본문"}).json()["email"]["flow"]["mail"], "saved")
        r = c.post("/api/email/mails/E-1001/send", json={"draft": "보낼 본문"}).json()
        self.assertEqual((r["email"]["status"], r["email"]["flow"]["draft"]), ("완료", "보낼 본문"))
        r = c.post("/api/email/mails/E-1016/classify", json={"classification": "quote"}).json()
        self.assertEqual(r["toast"]["title"], "견적요청(으)로 분류했습니다")
        r = c.post("/api/email/mails/E-1016/entity", json={"field": "itemCode", "value": "MC-CAL-SR050", "triage": True}).json()
        self.assertEqual(r["email"]["entities"]["itemName"]["value"], "카밍 세럼 50g")
        r = c.post("/api/email/mails/E-1016/entity", json={"field": "quantity", "value": 200, "triage": True})
        self.assertEqual((r.status_code, r.json()["email"]["entities"]["quantity"]["value"]), (200, "200"))   # 숫자도 문자열로 / numbers stored as text
        self.assertEqual(c.post("/api/email/mails/E-1010/link-case", json={"caseId": "RFQ-2026-00131"}).json()["case"]["status"], "수정견적 필요")
        self.assertEqual(c.post("/api/email/mails/E-1009/new-case").status_code, 422)          # 이미 Case 있음 / has a case
        self.assertEqual(c.post("/api/email/mails/E-1020/hold", json={"on": True}).json()["email"]["status"], "보류")
        self.assertEqual(c.post("/api/email/mails/E-1002/complete").json()["toast"]["title"], "확인 완료")
        self.assertEqual(c.post("/api/email/mails/E-1013/archive").json()["email"]["workStatus"], "보관")
        self.assertEqual(c.post("/api/email/mails/E-1014/spam").json()["email"]["workStatus"], "스팸 처리")
        r = c.post("/api/email/assign", json={"kind": "case", "id": "RFQ-2026-00123", "user": "이수진"}).json()
        self.assertEqual(r["case"]["assignedUser"], "이수진")
        self.assertEqual(c.post("/api/email/assign", json={"kind": "case", "id": "RFQ-2026-00123", "user": "없음"}).status_code, 422)
        self.assertEqual(c.post("/api/email/mails/E-1005/order").json()["toast"]["title"], "주문등록 완료")
        self.assertEqual(c.post("/api/email/errors/ERR-0006/retry").json()["toast"]["title"], "이메일 발송 완료")
        self.assertEqual(c.post("/api/email/errors/ERR-9999/retry").status_code, 404)
        self.assertEqual(c.post("/api/email/scenario/3").status_code, 422)
        self.assertEqual(c.post("/api/email/scenario/2").json()["email"]["emailId"], "E-2002")
        self.assertEqual(c.post("/api/email/reset").json()["toast"]["title"], "데모 데이터를 초기화했습니다")
        self.assertEqual(c.get("/api/email/mails/E-2002").status_code, 404)

    def test_ask_contract_llm_and_fallback(self):
        c = self.client
        with patch("app.llm.generate", return_value={"target": "errors", "customer": ""}) as gen:
            r = c.post("/api/email/ask", json={"question": "처리 오류 알려줘", "acting_user_id": ""})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(set(body), {"chat_id", "title", "answer", "exec"})
        self.assertEqual(gen.call_args.kwargs["tier"], "lite")
        self.assertTrue(gen.call_args.kwargs["json_mode"])
        self.assertIn("미해결 API 오류는 **2건**", body["answer"])
        ex = body["exec"]
        self.assertEqual((ex["agent"], ex["agent_label"], len(ex["tasks"]), len(ex["think"]["groups"])),
                         ("email", "M코스메틱 이메일 에이전트", 3, 3))
        self.assertIn("AI가 질문을 '처리오류' 조회로 분류했습니다.", ex["think"]["groups"][0]["lines"])
        msgs = db.list_messages(body["chat_id"])
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])
        self.assertEqual((msgs[1]["meta"]["kind"], msgs[1]["meta"]["source"]), ("agent_exec", "M코스메틱 이메일 에이전트"))
        self.assertEqual(body["title"], "처리 오류 알려줘")
        with patch("app.llm.generate", side_effect=RuntimeError("down")):
            r2 = c.post("/api/email/ask", json={"question": "누리뷰티 02 주문 현황", "chat_id": body["chat_id"]}).json()
        self.assertEqual(r2["chat_id"], body["chat_id"])
        self.assertIn("조회 범위: 고객사 누리뷰티 02", r2["answer"])
        self.assertIn("주문등록 메일은 전체", r2["answer"])
        self.assertIn("키워드 규칙으로 '주문등록' 조회를 선택했습니다.", r2["exec"]["think"]["groups"][0]["lines"])
        self.assertEqual(len(db.list_messages(body["chat_id"])), 4)
        with patch("app.llm.generate", return_value={"target": "weather"}):
            r3 = c.post("/api/email/ask", json={"question": "재고 문의 메일 보여줘"}).json()
        self.assertIn("재고문의 메일은 전체", r3["answer"])
        with patch("app.llm.generate", return_value={"target": "inbox"}):
            r4 = c.post("/api/email/ask", json={"question": "확인 필요한 메일 답장 보내줘"}).json()
        self.assertTrue(r4["answer"].startswith("> 발송이나 주문등록 같은 **실행**은"))
        self.assertEqual(c.post("/api/email/ask", json={"question": "x", "chat_id": "nope"}).status_code, 404)
        with patch("app.llm.generate", side_effect=RuntimeError("down")):
            r5 = c.post("/api/email/ask", json={}).json()               # 빈 질문 = 기본 제목 '브리핑해줘' / default title
        self.assertEqual(r5["title"], "브리핑해줘")
        self.assertIn("수신 메일 기준 처리 현황입니다.", r5["answer"])

    def test_gate_by_agent_node(self):
        with patch("app.mcmail_api.access.resolve_eff", return_value={"nodes": {"agent_email": 0}}):
            r = self.client.get("/api/email/meta", params={"acting_user_id": "7"})
            self.assertEqual((r.status_code, r.json()["detail"]), (403, "M코스메틱 이메일 에이전트 접근 권한이 없습니다"))
            self.assertEqual(self.client.post("/api/email/mails/E-1001/erp", json={"acting_user_id": "7"}).status_code, 403)
        with patch("app.mcmail_api.access.resolve_eff", return_value={"nodes": {"agent_email": 1}}):
            self.assertEqual(self.client.get("/api/email/meta", params={"acting_user_id": "7"}).status_code, 200)

    def test_mock_erp_and_mail(self):
        c = self.client
        url = "/mock/mcosmetic/erp/v1/prices"
        params = {"customer": "CUST-00002", "item": "MC-CAL-SR050", "qty": "300"}
        r = c.get(url, params=params)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (401, "unauthorized"))
        self.assertEqual(c.get(url, params=params, headers=AUTH).json()["price"], 9500)
        r = c.get(url, params={**params, "item": "MC-X"}, headers=AUTH)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (404, "not_found"))
        self.assertEqual(c.get(url, params={**params, "qty": "1.5"}, headers=AUTH).status_code, 422)
        self.assertEqual(c.get("/mock/mcosmetic/erp/v1/shipments", params={"so": "SO-20261001-00109"}, headers=AUTH).json()["matchedBy"], 1)
        self.assertEqual(c.get("/mock/mcosmetic/erp/v1/shipments", params={"customer": "CUST-00011"}, headers=AUTH).json()["matchedBy"], 3)
        self.assertEqual(c.get("/mock/mcosmetic/erp/v1/inventory/on-hand", params={"item": "MC-CIC-SR050", "qty": "600"},
                               headers=AUTH).json()["available"], 330)
        self.assertEqual(c.get("/mock/mcosmetic/erp/v1/sales-orders/SO-20260930-00102", headers=AUTH).json()["total"], 9715200)
        self.assertEqual(c.get("/mock/mcosmetic/erp/v1/sales-orders/SO-1", headers=AUTH).status_code, 404)
        order = {"customerCode": "CUST-00002", "itemCode": "MC-CAL-SR050", "quantity": 300, "deliveryDate": "2026-11-01"}
        r = c.post("/mock/mcosmetic/erp/v1/sales-orders", json=order, headers=AUTH)
        self.assertEqual((r.status_code, r.json()["so"], r.json()["price"]), (201, "SO-20261005-00126", 9500))
        self.assertEqual(r.json()["shipment"]["shipDate"], "2026-10-30")
        self.assertIn("SO-20261005-00126", c.get("/api/email/meta").json()["shipments"])
        r = c.post("/mock/mcosmetic/erp/v1/sales-orders", json={**order, "deliveryDate": "2026-10-01"}, headers=AUTH)
        self.assertEqual((r.status_code, r.json()["error"]["message"]), (422, "납기일 값이 올바르지 않습니다."))
        r = c.post("/mock/mcosmetic/mail/v1/send", json={"to": "buyer@example.com", "subject": "안내", "body": "본문"}, headers=AUTH)
        self.assertEqual((r.status_code, r.json()["status"], r.json()["messageId"]), (200, "sent", "MSG-00001"))
        self.assertEqual(self.peek()["outbox"][0]["subject"], "안내")
        self.assertEqual(c.post("/mock/mcosmetic/mail/v1/send", json={"to": "nobody", "subject": "s", "body": "b"},
                                headers=AUTH).status_code, 422)


class DashCleanupTests(McmailBase):
    """em dash 정리(2026-09-29). 새 시드에는 em dash 가 없고, 옛 시드·옛 코드가 남긴 문구는 init 이 한 번만 새 문구로 바꾼다.
    문자열만 바뀌고 상태·날짜·색인 열·행 순서는 그대로이며, 두 번째 init 은 아무것도 바꾸지 않는다.
    Em dash cleanup (2026-09-29). The current seed holds no em dash, and init rewrites the wording left by the old seed and
    old code exactly once. Only strings change (statuses, dates, indexed columns and row order stay) and a second init
    changes nothing."""

    EM = "\u2014"
    SMTP_NEW = "SMTP 451 Temporary failure: 수신 서버 응답 지연"

    def dump(self):
        """mc_* 전체(색인 열 포함)와 메타, JSON 으로 정규화 / every mc_* row with its indexed columns and the meta, as JSON"""
        conn = sqlite3.connect(self.db_path)
        try:
            out = {}
            for t, k in (("mc_emails", "email_id"), ("mc_cases", "case_id"), ("mc_errors", "id")):
                cols = [c[1] for c in conn.execute(f"PRAGMA table_info({t})")]
                out[t] = [dict(zip(cols, r)) for r in conn.execute(f"SELECT * FROM {t} ORDER BY rowid")]
            out["mc_log"] = [list(r) for r in conn.execute("SELECT seq, time, type, text FROM mc_log ORDER BY seq")]
            out["mc_meta"] = dict(conn.execute("SELECT key, value FROM mc_meta").fetchall())
            return json.loads(json.dumps(out, ensure_ascii=False))
        finally:
            conn.close()

    def plant_old_wording(self):
        """옛 시드 JSON·옛 코드가 남겼을 문구로 되돌리고 정리 표시를 지운다. 재고 부족 초안(변형 1)과 그 발송본(발신 메일·
        발신함), 사용자가 적은 붙은 em dash, 옛 시나리오 활동 기록도 넣는다. (옛 문구, 새 문구) 쌍을 돌려준다.
        Put back the wording the old seed JSON and old code left and drop the flag: also a shortage stock draft (variant 1)
        with its sent copies (outbound mail, outbox), a bare em dash typed by a user and an old scenario log line. Returns
        the (old, new) pairs."""
        EM = self.EM
        mcmail.run_erp("E-1021")
        mcmail.draft("E-1021", regen=True)
        mcmail.send("E-1021")
        mcmail.set_entity("E-1005", "shippingAddress", "인천 신규 창고 A-3동")
        pairs = [(f"SMTP 451 Temporary failure {EM} 수신 서버 응답 지연", self.SMTP_NEW),
                 (f"Re: 하이드라 세럼 견적 문의 {EM} 수량 변경", "Re: 하이드라 세럼 견적 문의 · 수량 변경"),
                 (f"부족 {EM} 다음 입고 ", "부족, 다음 입고 "),
                 (f"인천 신규 창고 A{EM}3동", "인천 신규 창고 A-3동")]
        conn = sqlite3.connect(self.db_path)
        with conn:
            for t, k in (("mc_emails", "email_id"), ("mc_cases", "case_id"), ("mc_errors", "id")):
                for rid, data in conn.execute(f"SELECT {k}, data FROM {t}").fetchall():
                    old = data
                    for o, n in pairs:
                        old = old.replace(n, o)
                    if old != data:
                        conn.execute(f"UPDATE {t} SET data=? WHERE {k}=?", (old, rid))
            outbox = conn.execute("SELECT value FROM mc_meta WHERE key='outbox'").fetchone()[0]
            conn.execute("UPDATE mc_meta SET value=? WHERE key='outbox'", (outbox.replace("부족, 다음 입고 ", f"부족 {EM} 다음 입고 "),))
            for seq, text in conn.execute("SELECT seq, text FROM mc_log").fetchall():
                conn.execute("UPDATE mc_log SET text=? WHERE seq=?", (text.replace(" · ", f" {EM} ", 1), seq))
            conn.execute("INSERT INTO mc_log(time, type, text) VALUES ('12:30', 'mail', ?)", (f"누리뷰티 02 메일 수신 {EM} 견적요청 / 확인 / 보류",))
            conn.execute("DELETE FROM mc_meta WHERE key='dash_cleanup_v1'")
        conn.close()
        return pairs

    def test_seed_is_clean_and_flagged(self):
        d = self.dump()
        self.assertEqual(d["mc_meta"]["dash_cleanup_v1"], "1")
        self.assertNotIn(self.EM, json.dumps(d, ensure_ascii=False))
        self.assertEqual(mcmail.recent_log()[-1]["text"], "누리뷰티 02 · 견적요청 분류, 신규 Case RFQ-2026-00123 생성")
        self.assertEqual(self.mail("E-1003")["subject"], "Re: 하이드라 세럼 견적 문의 · 수량 변경")
        self.assertEqual(self.mail("E-1012")["flow"]["mailError"], self.SMTP_NEW)
        mcmail.reset()                                                  # 초기화도 표시를 남긴다 / reset keeps the flag
        self.assertEqual(self.dump()["mc_meta"]["dash_cleanup_v1"], "1")

    def test_undash_mapping(self):
        u, EM = mcmail._undash, self.EM  # noqa: SLF001
        self.assertEqual(u(f"다온뷰티 04 {EM} 업무 유형 판단 불가, 수신메일에서 확인 필요"), "다온뷰티 04 · 업무 유형 판단 불가, 수신메일에서 확인 필요")
        self.assertEqual(u(f"■ 공급 가능 여부: 부족 {EM} 다음 입고 2026-10-23 (1,500EA)"), "■ 공급 가능 여부: 부족, 다음 입고 2026-10-23 (1,500EA)")
        self.assertEqual(u(f"SMTP 451 Temporary failure {EM} 수신 서버 응답 지연"), self.SMTP_NEW)
        self.assertEqual(u(f"A{EM}3동"), "A-3동")
        for s in ("2026-10-05 09:13", "SO-20261005-00125 · [[D+1]]", ""):
            self.assertEqual(u(s), s)

    def test_init_rewrites_old_wording_once_and_keeps_everything_else(self):
        pairs = self.plant_old_wording()
        planted = self.dump()
        self.assertNotIn("dash_cleanup_v1", planted["mc_meta"])
        self.assertIn(self.EM, json.dumps(planted, ensure_ascii=False))
        state = lambda: {e["emailId"]: (e["status"], e["receivedDate"], e.get("workStatus")) for e in mcmail.list_emails(None, "all")["items"]}  # noqa: E731
        before = state()
        mcmail.init_mcmail()
        cleaned = self.dump()
        # 옛 문구만 새 문구로 바뀌고(남은 공백 사이 em dash 는 ' · ') 나머지는 그대로 / only the old wording changed
        want = json.dumps(planted, ensure_ascii=False)
        for o, n in pairs:
            want = want.replace(o, n)
        want = json.loads(want.replace(f" {self.EM} ", " · "))
        want["mc_meta"]["dash_cleanup_v1"] = "1"
        self.assertEqual(cleaned, want)
        self.assertNotIn(self.EM, json.dumps(cleaned, ensure_ascii=False))
        self.assertEqual(state(), before)                                 # 상태·날짜·작업 상태 그대로 / statuses and dates kept
        self.assertEqual(self.mail("E-1003")["subject"], "Re: 하이드라 세럼 견적 문의 · 수량 변경")
        self.assertEqual(next(x for x in mcmail.list_errors("all")["items"] if x["id"] == "ERR-0006")["message"], self.SMTP_NEW)
        self.assertEqual([a["errorMessage"] for a in self.case("ORD-2026-00108")["actions"] if a["errorMessage"]], [self.SMTP_NEW])
        self.assertIn("■ 공급 가능 여부: 부족, 다음 입고 ", self.mail("E-1021")["flow"]["draft"])
        self.assertIn("부족, 다음 입고 ", self.peek()["outbox"][0]["body"])
        self.assertEqual(self.mail("E-1005")["entities"]["shippingAddress"]["value"], "인천 신규 창고 A-3동")
        self.assertEqual(mcmail.recent_log(1)[0]["text"], "누리뷰티 02 메일 수신 · 견적요청 / 확인 / 보류")
        # 두 번째 init 은 아무것도 바꾸지 않는다(표시가 있으면 새로 들어온 em dash 도 그대로 둔다: 한 번만 도는 정리)
        # a second init changes nothing (with the flag set even a newly written em dash stays: a one-time cleanup)
        mcmail.init_mcmail()
        self.assertEqual(self.dump(), cleaned)
        conn = sqlite3.connect(self.db_path)
        with conn:
            conn.execute("INSERT INTO mc_log(time, type, text) VALUES ('12:40', 'ok', ?)", (f"다온뷰티 04 {self.EM} 확인 완료",))
            self.assertEqual(mcmail._dash_cleanup(conn), -1)  # noqa: SLF001
        conn.close()
        self.assertEqual(mcmail.recent_log(1)[0]["text"], f"다온뷰티 04 {self.EM} 확인 완료")

    def test_cleanup_runs_after_a_reanchor_in_the_same_init(self):
        self.plant_old_wording()
        self.today.return_value = date(2026, 10, 7)
        mcmail.init_mcmail()
        e = self.mail("E-1003")
        self.assertEqual((e["receivedDate"], e["subject"]), ("2026-10-07 09:32", "Re: 하이드라 세럼 견적 문의 · 수량 변경"))
        self.assertNotIn(self.EM, json.dumps(self.dump(), ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
