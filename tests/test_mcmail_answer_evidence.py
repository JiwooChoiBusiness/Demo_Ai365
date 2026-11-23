"""M코스메틱 조회 근거가 최종 취합까지 유지되는지 검사. 네트워크·실제 LLM·DB 쓰기는 없다."""
import asyncio
import copy
import json
import unittest
from unittest.mock import patch

from app import answers


def evidence():
    return {
        "target": "orders", "filters": {"date_from": "2026-09-01", "date_to": "2026-09-30", "filter": "done"},
        "task": "주문등록 메일 24건을 조회했습니다.", "detail": "지정 기간의 완료 메일만 조회했습니다.",
        "data": {
            "target": "orders", "today": "2026-09-30", "counts": {"all": 24, "done": 24, "todo": 0},
            "rows": [{"emailId": f"E-{n}", "body": "원본 메일 본문은 취합에 중복해서 보내지 않음"} for n in range(24)],
            "recentDone": [], "contact": {"email": "not-for-answer@example.invalid"},
        },
    }


class EvidenceTests(unittest.TestCase):
    def test_scope_and_full_counts_survive_without_raw_messages(self):
        ex = {"auto_agent": "email", "auto_evidence": [evidence()], "mcp_tools": ["get_work_status"]}
        before = copy.deepcopy(ex)
        out = answers._slim_extras(ex)
        item = out["auto_evidence"][0]
        self.assertEqual(item["filters"], ex["auto_evidence"][0]["filters"])
        self.assertEqual(item["summary"]["counts"], {"all": 24, "done": 24, "todo": 0})
        self.assertEqual(item["returned_collections"], {"rows": 24, "recentDone": 0})
        self.assertEqual(item["summary"]["today"], "2026-09-30")
        self.assertNotIn("원본 메일 본문", json.dumps(out, ensure_ascii=False))
        self.assertNotIn("not-for-answer", json.dumps(out))
        self.assertNotIn("data", item)
        self.assertNotIn("mcp_tools", out)
        self.assertEqual(ex, before)

    def test_large_metadata_is_bounded_and_omission_is_explicit(self):
        item = evidence()
        item["task"] = "x" * 20000
        item["filters"]["q"] = "y" * 20000
        out = answers._slim_extras({"auto_evidence": [item] * 30})
        self.assertLess(len(json.dumps(out, ensure_ascii=False)), 25000)
        self.assertEqual(out["auto_evidence_total"], 30)
        self.assertEqual(out["auto_evidence_omitted"], 18)

    def test_normalized_scope_and_erp_snapshot_exclusion_survive(self):
        item = evidence()
        item["data"].update({
            "filtered": True,
            "filters": {"customer": "누리뷰티 02", "date_from": "2026-09-01", "date_to": "2026-09-30"},
            "scope": "9월 누리뷰티 02 재고문의 메일",
            "scopeNote": "기간별 재고문의 메일 조회이며 현재 ERP 재고는 포함하지 않았습니다.",
            "snapshotAsOf": "2026-09-30", "todoTotal": 19,
        })
        summary = answers._slim_extras({"auto_evidence": [item]})["auto_evidence"][0]["summary"]
        for key in ("filtered", "filters", "scope", "scopeNote", "snapshotAsOf", "todoTotal"):
            self.assertEqual(summary[key], item["data"][key])

    def test_invalid_evidence_does_not_break_existing_answer(self):
        for value in (None, "invalid", {}, [None, 1, "bad", {"data": []}]):
            with self.subTest(value=value):
                out = answers._slim_extras({"auto_evidence": value, "auto_label": "기존 답변"})
                self.assertEqual(out["auto_label"], "기존 답변")
                self.assertIsInstance(out["auto_evidence"], list)


class AggregateTests(unittest.TestCase):
    def aggregate(self, result):
        captured = []

        async def fake_stream(messages, system=None):
            captured.append({"messages": messages, "system": system})
            yield "검증용 최종 답변"

        async def collect():
            return [ev async for ev in answers._aggregate_answer(
                "chat-test", "사내", [{"role": "user", "content": "9월 완료 주문 메일만 요약해줘"}],
                {"work-1": result}, local_done=True)]

        with patch.object(answers, "_astream", fake_stream), patch.object(answers, "SMOOTH_DELAY", 0), \
                patch.object(answers.db, "add_message", return_value="msg-test") as save, \
                patch.object(answers.llm, "generate", side_effect=AssertionError("실제 LLM 금지")), \
                patch.object(answers.llm, "stream", side_effect=AssertionError("실제 LLM 금지")):
            events = asyncio.run(collect())
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["message_id"], "msg-test")
        self.assertEqual(save.call_args.args[2], "검증용 최종 답변")
        return captured[0]

    def test_final_model_receives_scope_and_counts_but_not_raw_body(self):
        call = self.aggregate({
            "agent": "work", "status": "answer", "text": "완료 주문 메일 24건. 표에는 10건만 표시합니다.",
            "extras": {"auto_agent": "email", "auto_label": "M코스메틱", "auto_evidence": [evidence()]},
        })
        prompt = call["messages"][-1]["content"]
        self.assertIn('"rows": 24', prompt)
        self.assertIn('"all": 24', prompt)
        self.assertIn('"date_from": "2026-09-01"', prompt)
        self.assertNotIn("원본 메일 본문", prompt)
        self.assertIn("전체 건수라는 뜻이 아니다", call["system"])
        self.assertIn("표본·최근 완료 목록만으로", call["system"])
        self.assertIn("ERP의 실제 재고", call["system"])

    def test_pending_action_is_not_described_as_completed_by_the_contract(self):
        call = self.aggregate({
            "agent": "work", "status": "answer", "text": "메일 발송 확인이 필요합니다.",
            "extras": {"auto_agent": "email", "action_draft": {
                "kind": "email.action.send", "summary": "고객 회신 발송", "payload": {"email_id": "E-1001"}}},
        })
        self.assertIn("action_draft는 확인 대기", call["system"])
        self.assertIn("초안 작성은 발송이 아니고 ERP 조회는 주문등록이 아니다", call["system"])
        self.assertIn("기존 데이터의 완료 상태와 이번 요청에서 실행한", call["system"])

    def test_non_mcosmetic_answer_does_not_receive_email_rules(self):
        call = self.aggregate({"agent": "work", "status": "answer", "text": "교육 이수율 80%",
                               "extras": {"auto_agent": "edu"}})
        self.assertNotIn("[M코스메틱 고객 메일 결과의 해석]", call["system"])


if __name__ == "__main__":
    unittest.main()
