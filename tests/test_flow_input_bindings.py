# -*- coding: utf-8 -*-
"""API 작업 입력값 바인딩(2026-09-14) — 값 출처 우선순위(검수 답변 > 값 지정 > 자동 추출 > 기본값 > 질문)와 팝업·질문 카드 표기.
실제 LLM·HTTP 호출은 없다(전부 패치).

API-task input bindings (2026-09-14) — value-source precedence (review answer > fixed value > AI extraction > default >
question) plus the popup / question-card wording. No real LLM or HTTP calls (everything is patched)."""
import unittest
from unittest.mock import AsyncMock, patch

from app import flows

CONN = {"id": "cn_e", "kind": "read", "name": "EMS 사용량", "enabled": True, "description": "사업장 전력 사용량",
        "api": {"url": "https://x/usage?site={{input.site}}&period={{input.period}}",
                "input_docs": [{"name": "site", "description": "사업장 코드", "example": "HQ"},
                               {"name": "period", "description": "조회 월", "example": "2026-08"}]}}
CONN_DEFAULT = {**CONN, "api": {**CONN["api"], "input_docs": [
    {"name": "site", "description": "사업장 코드", "example": "HQ"},
    {"name": "period", "description": "조회 월", "example": "2026-08", "default": "2026-09"}]}}
PRIOR = [{"label": "1단계 조회", "agent": "api", "stage": 1, "text": "본사 결과",
          "data": {"site": "HQ", "meta": {"code": "B1"}}, "outputs": {"site_code": "HQ2"}}]


def api_node(binds=None, **over) -> dict:
    n = {"agent": "api", "resources": ["cn_e"], "instruction": "", "prompt": "사용량 조회"}
    if binds:
        n["input_bindings"] = binds
    n.update(over)
    return n


class InputBindingRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def run_node(self, node, llm_out=None, conn=CONN, prior=None, message="사용량 알려줘"):
        """_run_api_node 를 스텁과 함께 실행 — (결과, call_connector 목, LLM 프롬프트 목록) / run with stubs"""
        prompts: list[str] = []

        def fake_generate(prompt, **kwargs):
            prompts.append(prompt)
            if isinstance(llm_out, BaseException):
                raise llm_out
            return llm_out if llm_out is not None else {"inputs": {}}

        call = AsyncMock(return_value={"ok": True, "status": 200, "result_text": "ok", "outputs": {}})
        with patch.object(flows, "_api_candidates", return_value=([conn], None)), \
             patch.object(flows.llm, "generate", side_effect=fake_generate), \
             patch.object(flows, "call_connector", call):
            result = await flows._run_api_node(node, message, prior or [], "7")
        return result, call, prompts

    async def test_value_binding_substitutes_prior_stage_output_and_narrows_the_llm(self):
        node = api_node({"site": {"mode": "value", "value": "{{step1.result.site}}"}})
        result, call, prompts = await self.run_node(node, {"inputs": {"period": "2026-08", "site": "IGNORED"}}, prior=PRIOR)
        self.assertEqual(result["status"], "done")
        self.assertEqual(call.await_args.args[3], {"site": "HQ", "period": "2026-08"})   # 값 지정이 LLM 을 이긴다 / fixed beats the LLM
        self.assertEqual(len(prompts), 1)
        self.assertIn("- period: 조회 월", prompts[0])
        self.assertNotIn("- site: 사업장 코드", prompts[0])          # 자동 추출 대상만 설명에 / only auto inputs are described
        self.assertIn("[이미 정해진 값", prompts[0])
        self.assertIn("site: HQ", prompts[0])

    async def test_value_binding_that_resolves_empty_asks_instead_of_calling(self):
        node = api_node({"site": {"mode": "value", "value": "{{step1.result.nope}}"},
                         "period": {"mode": "value", "value": "2026-08"}})
        result, call, prompts = await self.run_node(node, AssertionError("불필요한 LLM 호출"), prior=PRIOR)
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["extras"]["missing_inputs"], ["site"])
        self.assertEqual(result["extras"]["asked"], [])
        self.assertEqual(prompts, [])
        call.assert_not_awaited()

    async def test_ask_binding_is_never_extracted_even_when_the_llm_guesses_it(self):
        node = api_node({"site": {"mode": "ask"}})
        result, call, prompts = await self.run_node(node, {"inputs": {"site": "HQ", "period": "2026-08"}})
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["extras"]["missing_inputs"], ["site"])
        self.assertEqual(result["extras"]["asked"], ["site"])
        self.assertEqual(result["extras"]["inputs"].get("period"), "2026-08")   # 자동 추출분은 유지 / the auto value is kept
        self.assertNotIn("- site:", prompts[0])
        call.assert_not_awaited()

    async def test_all_inputs_bound_skips_the_llm_entirely(self):
        node = api_node({"site": {"mode": "value", "value": "HQ"}, "period": {"mode": "value", "value": "{{input.month}}"}})
        result, call, prompts = await self.run_node(node, AssertionError("불필요한 LLM 호출"))
        self.assertEqual(result["status"], "done")
        self.assertEqual(prompts, [])
        args = call.await_args.args[3]
        self.assertEqual(args["site"], "HQ")
        self.assertRegex(args["period"], r"^\d{4}-\d{2}$")   # {{input.month}} 치환 / substituted

    async def test_default_fills_an_unextracted_input_and_the_task_runs(self):
        result, call, _ = await self.run_node(api_node(), {"inputs": {"site": "HQ"}}, conn=CONN_DEFAULT)
        self.assertEqual(result["status"], "done")
        self.assertEqual(call.await_args.args[3], {"site": "HQ", "period": "2026-09"})

    async def test_ask_binding_beats_a_default(self):
        node = api_node({"period": {"mode": "ask"}, "site": {"mode": "value", "value": "HQ"}})
        result, call, _ = await self.run_node(node, AssertionError("불필요한 LLM 호출"), conn=CONN_DEFAULT)
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual((result["extras"]["missing_inputs"], result["extras"]["asked"]), (["period"], ["period"]))
        call.assert_not_awaited()

    async def test_provided_inputs_override_bindings_without_re_resolving(self):
        node = api_node({"site": {"mode": "value", "value": "HQ"}}, _resolved_connector="cn_e",
                        _provided_inputs={"site": "BUSAN", "period": "2026-07"})
        result, call, prompts = await self.run_node(node, AssertionError("불필요한 LLM 호출"))
        self.assertEqual(result["status"], "done")
        self.assertEqual(call.await_args.args[3], {"site": "BUSAN", "period": "2026-07"})
        self.assertEqual(prompts, [])

    async def test_binding_for_an_unknown_input_name_is_ignored(self):
        node = api_node({"foo": {"mode": "value", "value": "1"}})
        result, call, prompts = await self.run_node(node, {"inputs": {"site": "HQ", "period": "2026-08"}})
        self.assertEqual(result["status"], "done")
        self.assertEqual(call.await_args.args[3], {"site": "HQ", "period": "2026-08"})
        self.assertEqual(len(prompts), 1)

    async def test_blank_llm_value_never_blocks_the_default(self):
        # 2026-09-14 점검: 모델이 스키마의 키를 빈 값(""·공백·null)으로 채워 와도 기본값이 이긴다 / a blank LLM value never beats the default
        for blank in ("", "  ", None):
            with self.subTest(blank=repr(blank)):
                result, call, _ = await self.run_node(api_node(), {"inputs": {"site": "HQ", "period": blank}}, conn=CONN_DEFAULT)
                self.assertEqual(result["status"], "done")
                self.assertEqual(call.await_args.args[3], {"site": "HQ", "period": "2026-09"})

    async def test_blank_llm_value_without_a_default_still_asks(self):
        result, call, _ = await self.run_node(api_node(), {"inputs": {"site": "", "period": "2026-08"}})
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["extras"]["missing_inputs"], ["site"])
        self.assertNotIn("site", result["extras"]["inputs"])   # 빈 값은 카드에 실리지 않는다 / a blank never rides along
        call.assert_not_awaited()


class InputBindingReviewAndSummaryTests(unittest.TestCase):
    def test_ask_bound_missing_input_gets_the_ask_wording_and_default_hint(self):
        node = api_node({"period": {"mode": "ask"}})
        flow = {"stages": [{"nodes": [node]}]}
        finished = [{"status": "needs_input", "_ni": 0, "_node": node, "label": "EMS 사용량",
                     "extras": {"missing_inputs": ["period", "site"], "asked": ["period"], "connector_id": "cn_e", "inputs": {}}}]
        with patch("app.connectors.get_connector", return_value=CONN_DEFAULT), \
             patch.object(flows, "_review_llm", side_effect=AssertionError("검수 LLM 불필요")):
            questions, rerun = flows._stage_review(flow, 0, finished, "q", [], [])
        asked, plain = questions[0], questions[1]
        self.assertEqual((asked["id"], asked["required"]), ("in_1_period", True))
        self.assertTrue(asked["question"].startswith("EMS 사용량 호출에 쓸 'period' 값을 입력해 주세요."))
        self.assertEqual((asked["hint"], asked["placeholder"]), ("조회 월 · 기본값 2026-09", "2026-08"))
        self.assertTrue(plain["question"].startswith("EMS 사용량 호출에 필요한 'site' 값을 알려주세요."))
        self.assertEqual((plain["hint"], plain["placeholder"]), ("사업장 코드", "HQ"))
        self.assertEqual(rerun, ["stage1_1"])

    def test_flow_summary_reports_how_each_input_is_obtained(self):
        flow = {"id": "fl_t", "name": "테스트", "stages": [
            {"nodes": [api_node({"site": {"mode": "value", "value": "HQ"}})]},
            {"nodes": [api_node({"site": {"mode": "ask"}})]}]}
        with patch("app.connectors.list_connectors", return_value=[CONN_DEFAULT]), \
             patch.object(flows, "_flow_ai_summary", return_value="요약"):
            out = flows.flow_summary(flow)
        rows = [(r["stage"], r["name"], r["source"], r["value"], r["default"]) for r in out["inputs"]]
        # 2단계의 period(auto)는 1단계와 같은 행이라 접힌다 / stage 2's auto period collapses into stage 1's row
        self.assertEqual(rows, [(1, "site", "value", "HQ", ""), (1, "period", "auto", "", "2026-09"),
                                (2, "site", "ask", "", "")])
        self.assertFalse(out["inputs"][0]["has_var"])

    def test_flow_summary_lists_every_stage_file_including_the_last(self):
        # 단계별 파일(2026-09-14) → 2026-09-29 최종 파일(flow.docgen) 폐지: 마지막 단계도 목록에 들어가고 docgen 키는 없다.
        # 옛 flow.docgen 이 있으면 종전처럼 그 파일이 마지막 단계 파일이다(숨어 있던 마지막 단계 값은 쓰이지 않던 값).
        # Per-stage files (2026-09-14) → the final flow.docgen is retired (2026-09-29): the last stage is listed too and there is no
        # docgen key. A legacy flow.docgen stays the last stage's file as before (a hidden last-stage value was never used).
        flow = {"id": "fl_t", "name": "테스트", "stages": [
            {"nodes": [api_node()], "docgen": {"format": "docx", "instruction": "표 중심"}},
            {"nodes": [api_node()], "docgen": None},
            {"nodes": [api_node()], "docgen": {"format": "pdf", "instruction": ""}}],
            "docgen": {"format": "pptx", "instruction": "간결하게"}}
        with patch("app.connectors.list_connectors", return_value=[CONN]), \
             patch.object(flows, "_flow_ai_summary", return_value="요약"):
            out = flows.flow_summary(flow)
        self.assertEqual(out["stage_docgen"], [{"stage": 1, "format": "docx", "label": "Word", "instruction": "표 중심"},
                                               {"stage": 3, "format": "pptx", "label": "PPT", "instruction": "간결하게"}])
        self.assertNotIn("docgen", out)
        del flow["docgen"]   # 새 모양 — 마지막 단계 자기 파일 / the new shape: the last stage's own file
        with patch("app.connectors.list_connectors", return_value=[CONN]), \
             patch.object(flows, "_flow_ai_summary", return_value="요약"):
            out = flows.flow_summary(flow)
        self.assertEqual(out["stage_docgen"][-1], {"stage": 3, "format": "pdf", "label": "PDF", "instruction": ""})


if __name__ == "__main__":
    unittest.main()
