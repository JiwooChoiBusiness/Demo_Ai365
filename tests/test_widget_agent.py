# -*- coding: utf-8 -*-
"""위젯 에이전트(2026-11-16, 계약 = docs/widget-agent.md 8절): 붙은 도구(리포트 에이전트의 차트 · KPI 도구 + 위젯 도구)와 그 선언,
한 턴의 흐름(LLM 은 가짜 — 정해 둔 도구 호출을 돌려준다): KPI 카드를 만들면 "어떤 데이터를 연결할까요?"로 되묻기, 숫자를 말하면
고정 숫자 카드, 위젯 제목 변경, 차트 도구, 붙지 않은 도구 거절, 데이터 질문, 데이터가 바뀌면 같이 바뀌는 인사이트, /api/home/agent.
임시 DB 도 쓰지 않는다(작업본은 화면이 들고 있다). LLM · 네트워크는 없다.

The widget agent (2026-11-16; contract = docs/widget-agent.md section 8): its tools (the report agent's chart and KPI tools
plus its own) and their declarations, and one turn with a fake LLM that returns scripted tool calls: making a KPI card
asks "which data shall I connect?", a stated number makes a fixed-number card, renaming, chart tools, refusing tools that
are not attached, the data question, insights that follow the data, and /api/home/agent. No DB (the screen holds the
draft), no LLM, no network."""
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from app import home_widgets as hw, home_widgets_api, report_agent as ra, widget_agent as wa

MONTHLY = {"tool": "inline", "columns": ["월", "매출", "지점"],
           "rows": [["2026-01", 120, "서울"], ["2026-02", 150, "부산"], ["2026-03", 90, "서울"], ["2026-04", 180, "울산"]]}
CHART = {"v": 2, "title": "월별 매출", "source": MONTHLY, "chart": {"type": "bar", "x": "월", "y": [{"col": "매출"}]}}
PENDING = {"id": "k1", "source": "", "col": "", "agg": "", "label": "KPI 1", "unit": "", "link": "", "delta": "", "value": None,
           "note": "", "pending": True}


def said(*calls, text=""):
    """가짜 LLM 의 한 라운드 답 / one round of the fake LLM"""
    return {"calls": [{"name": n, "args": a} for n, a in calls], "text": text}


def llm(*rounds):
    return patch.object(wa.llm, "generate_calls", side_effect=list(rounds))


class ToolTests(unittest.TestCase):
    """붙은 도구 / the attached tools"""

    def test_only_the_chart_kpi_and_widget_tools_are_attached(self):
        names = [s["name"] for s in wa.TOOL_SPECS]
        self.assertEqual(names, ["update_chart", "set_style", "set_theme", "add_reference_line", "remove_reference_line", "add_calculation",
                                 "add_highlight", "remove_highlight", "set_trend", "add_filter", "remove_filter",
                                 "add_kpi", "remove_kpi", "arrange_kpis", "fetch_data", "rename_widget", "set_insight", "ask_data"])
        for gone in ("query_data", "create_chart", "remove_chart", "arrange", "rename_dashboard", "set_drill"):
            self.assertNotIn(gone, names)
        by = {s["name"]: s for s in wa.TOOL_SPECS}
        # 차트는 하나뿐: chart_id 는 필수가 아니고, 제목 · 크기 · 데이터 바꾸기는 없다 / one chart: no required chart_id, no title, size or data change
        for name in wa.CHART_TOOLS:
            self.assertNotIn("chart_id", by[name]["parameters"].get("required") or [], name)
        props = by["update_chart"]["parameters"]["properties"]
        for gone in ("title", "subtitle", "size", "source_id"):
            self.assertNotIn(gone, props)
        self.assertIn("type", props)
        self.assertNotIn("source_id", by["add_kpi"]["parameters"]["properties"])
        # 리포트 에이전트의 선언은 그대로다(복사해서 고쳤다) / the report agent's declarations are untouched (copied, then fitted)
        report = {s["name"]: s for s in ra.TOOL_SPECS}
        self.assertIn("title", report["update_chart"]["parameters"]["properties"])
        self.assertIn("chart_id", report["update_chart"]["parameters"]["required"])

    def test_tool_tree_groups_by_agent(self):
        tree = wa.tool_tree()
        self.assertEqual([a["agent"] for a in tree], ["Visualize Agent", "Data Agent"])
        groups = {g["group"]: [t["name"] for t in g["tools"]] for g in tree[0]["groups"]}
        self.assertEqual(groups["KPI 카드"], ["add_kpi", "remove_kpi", "arrange_kpis"])
        self.assertEqual(groups["정리"], ["rename_widget", "set_insight"])
        self.assertEqual(groups["리포트"], ["update_chart"])
        self.assertEqual([(t["name"], t["label"]) for t in tree[1]["groups"][0]["tools"]], [("fetch_data", "데이터 가져오기"), ("ask_data", "데이터 질문")])
        self.assertEqual(tree[1]["groups"][0]["group"], "데이터")


class TurnTests(unittest.TestCase):
    """한 턴(가짜 LLM) / one turn (fake LLM)"""

    def test_a_kpi_card_without_data_asks_which_data_to_connect(self):
        with llm(said(("add_kpi", {}), text="KPI 카드를 만들었어요. 어떤 데이터를 연결할까요?")) as m:
            out = wa.run_turn(None, [], "KPI 카드 위젯을 만들어줘")
        self.assertEqual(m.call_count, 1)
        prompt, kw = m.call_args.args[0], m.call_args.kwargs
        self.assertEqual((kw["system"], kw["tools"]), (wa.SYSTEM, wa.TOOL_SPECS))
        self.assertIn("제목: 새 위젯", prompt)
        self.assertIn("데이터: 없음", prompt)
        self.assertIn("[요청]\nKPI 카드 위젯을 만들어줘", prompt)
        self.assertEqual(out["widget"]["kpis"], [PENDING])
        self.assertEqual(out["ask"], {"kind": "data", "question": "어떤 데이터를 연결할까요?", "cards": ["KPI 1"], "need": "KPI 카드",
                                      "hint": wa.ASK_HINT_KPI})
        # 질문은 질문 칸이 맡고 답에는 한 일만 / the question lives in its box; the reply holds what was done
        self.assertEqual(out["reply"], "'KPI 1' KPI 카드를 만들었습니다.")
        self.assertEqual([(t["agent"], t["group"], t["tool"], t["label"], t["ok"]) for t in out["trace"]],
                         [("Visualize Agent", "KPI 카드", "add_kpi", "KPI 카드 추가", True)])
        self.assertEqual((out["model"]["kpis"][0]["pending"], out["model"]["needs_data"], out["model"]["empty"]), (True, True, False))

    def test_a_stated_number_turns_the_card_into_a_fixed_number_card(self):
        draft = {"v": 2, "title": "새 위젯", "kpis": [PENDING]}
        history = [{"role": "user", "text": "KPI 카드 위젯을 만들어줘"}, {"role": "agent", "text": "'KPI 1' KPI 카드를 만들었습니다.",
                                                                     "trace": [{"tool": "add_kpi", "ok": True}]}]
        with llm(said(("add_kpi", {"kpi_id": "KPI 1", "value": 1200, "unit": "건"}))) as m:
            out = wa.run_turn(draft, history, "목표 1,200건으로 해줘")
        self.assertIn("사용자: KPI 카드 위젯을 만들어줘\n에이전트: 'KPI 1' KPI 카드를 만들었습니다. (실행한 도구: add_kpi)", m.call_args.args[0])
        self.assertEqual(out["widget"]["kpis"], [{"id": "k1", "source": "", "col": "", "agg": "", "label": "KPI 1", "unit": "건", "link": "",
                                                  "delta": "", "value": 1200.0, "note": ""}])
        self.assertIsNone(out["ask"])
        self.assertEqual(out["model"]["kpis"][0]["text"], "1,200건")
        self.assertEqual(out["reply"], "KPI 카드 'KPI 1'(1,200건)을 고쳤습니다.")

    def test_renaming_a_not_connected_card_does_not_ask_again_and_names_stay_unique(self):
        draft = {"v": 2, "title": "새 위젯", "kpis": [PENDING, {"label": "목표", "value": 10}]}
        with llm(said(("add_kpi", {"kpi_id": "k1", "label": "이번 달 매출"}), text="이름을 바꿨어요. 데이터 연결은 아직 준비 중입니다.")):
            out = wa.run_turn(draft, [], "카드 이름은 이번 달 매출로")
        self.assertEqual((out["widget"]["kpis"][0]["label"], out["widget"]["kpis"][0]["pending"]), ("이번 달 매출", True))
        # 만든 카드가 아니라 이름만 고친 카드는 다시 묻지 않고, 모델의 답이 그대로 간다 / a card only renamed is not asked about again; the model's reply stays
        self.assertEqual((out["ask"], out["reply"]), (None, "이름을 바꿨어요. 데이터 연결은 아직 준비 중입니다."))
        with llm(said(("add_kpi", {"kpi_id": "k1", "label": "목표"})), said()):
            out = wa.run_turn(draft, [], "이름을 목표로")
        self.assertEqual((out["trace"][0]["ok"], out["trace"][0]["detail"]), (False, "같은 이름의 KPI 카드가 이미 있습니다: 목표"))
        self.assertEqual(out["widget"]["kpis"][0]["label"], "KPI 1")

    def test_an_exact_card_name_wins_over_the_report_agents_loose_ids(self):
        # 고정 카드를 먼저 만들고 빈 카드를 더하면 [k1 "목표", k2 "KPI 1"]: 'KPI 1'은 k1 이 아니라 k2 다(2026-11-16 검토 1)
        # a fixed card first and an empty one after gives [k1 "목표", k2 "KPI 1"]: 'KPI 1' is k2, not k1 (review finding 1)
        draft = {"v": 2, "title": "t", "kpis": [{"label": "목표", "value": 1200, "unit": "건"}, {**PENDING, "id": "k2"}]}
        with llm(said(("add_kpi", {"kpi_id": "KPI 1", "value": 500}))):
            out = wa.run_turn(draft, [], "KPI 1 은 500")
        self.assertEqual([(k["label"], k["value"]) for k in out["widget"]["kpis"]], [("목표", 1200.0), ("KPI 1", 500.0)])
        with llm(said(("arrange_kpis", {"order": ["KPI 1"]}))):
            out = wa.run_turn(draft, [], "KPI 1 을 앞으로")
        self.assertEqual([k["label"] for k in out["widget"]["kpis"]], ["KPI 1", "목표"])
        with llm(said(("remove_kpi", {"label": "KPI 1"}))):
            out = wa.run_turn(draft, [], "KPI 1 지워줘")
        self.assertEqual([k["label"] for k in out["widget"]["kpis"]], ["목표"])
        three = {"v": 2, "title": "t", "kpis": [{"label": "목표", "value": 1}, {**PENDING, "id": "k2"}, {**PENDING, "id": "k3", "label": "KPI 2"}]}
        with llm(said(("remove_kpi", {"kpi_id": "KPI 2"}))):
            out = wa.run_turn(three, [], "KPI 2 지워줘")
        self.assertEqual([k["label"] for k in out["widget"]["kpis"]], ["목표", "KPI 1"])

    def test_removing_a_card_removes_the_insight_that_used_it(self):
        draft = {"v": 2, "title": "t", "kpis": [{"label": "목표", "value": 1200, "unit": "건"}, {"label": "비용", "value": 300, "unit": "만원"}],
                 "insight": "올해 {k1}을 달성해야 합니다"}
        with llm(said(("remove_kpi", {"label": "목표"}), ("add_kpi", {"label": "매출", "value": 900, "unit": "만원"}))):
            out = wa.run_turn(draft, [], "목표 카드 지우고 매출 900 카드")
        # 새 카드가 k1 을 다시 받아도 "올해 900만원을 달성해야 합니다"가 되살아나지 않는다 / the reused k1 never revives the sentence with 900
        self.assertEqual([(k["id"], k["label"]) for k in out["widget"]["kpis"]], [("k2", "비용"), ("k1", "매출")])
        self.assertEqual((out["widget"]["insight"], out["model"]["insight"]), ("", ""))
        self.assertEqual(out["trace"][0]["say"], "KPI 카드를 지웠습니다. 이 카드를 쓰던 인사이트도 지웠습니다.")
        with llm(said(("remove_kpi", {"label": "비용"}))):
            kept = wa.run_turn(draft, [], "비용 카드 지워줘")
        self.assertEqual(kept["widget"]["insight"], "올해 {k1}을 달성해야 합니다")   # 쓰지 않던 카드면 그대로 / untouched when the card was not used

    def test_a_number_without_a_name_still_makes_a_card(self):
        with llm(said(("add_kpi", {"value": 1200, "unit": "건"}))):
            out = wa.run_turn(None, [], "1,200건 카드 넣어줘")
        self.assertEqual([(k["label"], k["value"], k["unit"]) for k in out["widget"]["kpis"]], [("KPI 1", 1200.0, "건")])
        self.assertTrue(out["trace"][0]["ok"])

    def test_a_tool_that_breaks_changes_nothing_and_the_turn_goes_on(self):
        # 고정 조건으로 데이터가 비면 리포트 에이전트의 평균 기준선 문장이 None 을 그리다 TypeError 를 낸다(2026-11-16 검토 5)
        # with the data filtered empty the report agent's average-line sentence formats None and raises TypeError (review finding 5)
        empty = {**CHART, "chart": {**CHART["chart"], "filters": [{"col": "지점", "selected": ["대전"]}]}}
        with llm(said(("add_reference_line", {"label": "평균", "stat": "avg"}), ("rename_widget", {"title": "대전 매출"})), said(text="평균선은 넣지 못했어요")):
            out = wa.run_turn(empty, [], "평균선 넣고 제목은 대전 매출")
        self.assertEqual([(t["tool"], t["ok"], t["detail"] if not t["ok"] else "") for t in out["trace"]],
                         [("add_reference_line", False, wa.TOOL_BROKE), ("rename_widget", True, "")])
        self.assertEqual((out["widget"]["chart"]["ref_lines"], out["widget"]["title"]), ([], "대전 매출"))   # 반쯤 바뀐 것은 되돌렸다 / the half-made change was rolled back

    def test_kpi_limits_and_data_cards_without_data(self):
        four = {"v": 2, "title": "t", "kpis": [{"label": n, "value": i} for i, n in enumerate(("매출", "이익", "비용", "고객"))]}
        with llm(said(("add_kpi", {"value": 5, "label": "다섯째"})), said(text="네 개까지예요")):
            out = wa.run_turn(four, [], "하나 더")
        self.assertEqual((out["trace"][0]["ok"], out["trace"][0]["detail"]), (False, "위젯에는 KPI 카드를 4개까지 넣을 수 있습니다"))
        self.assertEqual((len(out["widget"]["kpis"]), out["reply"]), (4, "네 개까지예요"))
        with llm(said(("add_kpi", {"label": "매출 합계", "column": "매출"})), said(text="데이터가 아직 없습니다")):
            out = wa.run_turn(None, [], "매출 합계 카드")
        self.assertEqual((out["trace"][0]["ok"], out["trace"][0]["detail"]), (False, wa.NO_DATA))
        self.assertEqual(out["widget"]["kpis"], [])
        with llm(said(("remove_kpi", {"label": "이익"}), ("arrange_kpis", {"order": ["고객"]}))):
            out = wa.run_turn(four, [], "이익 카드 지우고 고객 카드를 맨 앞으로")
        self.assertEqual([k["label"] for k in out["widget"]["kpis"]], ["고객", "매출", "비용"])

    def test_rename_widget_also_renames_the_chart(self):
        with llm(said(("rename_widget", {"title": "이번 달 실적"}))):
            out = wa.run_turn(CHART, [], "제목을 이번 달 실적으로")
        self.assertEqual((out["widget"]["title"], out["widget"]["chart"]["title"]), ("이번 달 실적", "이번 달 실적"))
        self.assertEqual(out["reply"], "위젯 제목을 '이번 달 실적'(으)로 바꿨습니다.")
        with llm(said(("rename_widget", {"title": "가" * 41})), said()):
            out = wa.run_turn(CHART, [], "아주 긴 제목")
        self.assertEqual(out["trace"][0]["detail"], "위젯 제목은 40자까지 쓸 수 있습니다")

    def test_the_report_agents_chart_tools_change_the_widget_chart(self):
        rounds = [said(("update_chart", {"type": "line", "title": "무시", "size": "half", "chart_id": "c9"})),
                  said(("set_style", {"labels": True}), ("add_reference_line", {"label": "평균", "stat": "avg"}),
                       ("add_highlight", {"kind": "top", "n": 1, "color": "red"}), ("add_filter", {"column": "월", "last_n": 3}),
                       ("set_trend", {"line": True}), ("set_theme", {"brand_color": "#1BA672"}))]
        with llm(*rounds) as m:
            out = wa.run_turn(CHART, [], "선으로 바꾸고 값 라벨 · 평균선 · 최고 강조 · 최근 3개월 · 추세선 · 초록 테마")
        self.assertEqual(m.call_count, 2)   # 차트 수정은 바뀐 값을 보고 한 번 더 / an edited chart gets another round
        self.assertTrue(all(t["ok"] for t in out["trace"]), out["trace"])
        c = out["widget"]["chart"]
        self.assertEqual((c["type"], c["title"], c["size"], c["style"]["labels"], c["style"]["palette"]), ("line", "월별 매출", "full", True, "theme"))
        self.assertEqual([(r["label"], r["stat"]) for r in c["ref_lines"]], [("평균", "avg")])
        self.assertEqual([h["kind"] for h in c["highlights"]], ["top"])
        self.assertEqual([(f["col"], f["range"]) for f in c["filters"]], [("월", {"last": 3})])
        self.assertTrue(c["trend"]["line"])
        self.assertEqual(out["widget"]["theme"]["brand"], "#1BA672")
        data = out["model"]["chart"]["data"]
        self.assertEqual((data["x"], data["refs"][0]["value"]), (["2026-02", "2026-03", "2026-04"], 140.0))
        self.assertEqual(out["model"]["chart"]["filters"], ["월: 최근 3개"])
        with llm(said(("add_calculation", {"calc": "pct_prev"})), said(text="증감률을 더했습니다")):
            out = wa.run_turn(CHART, [], "전월 대비 증감률도")
        self.assertEqual([y.get("calc") for y in out["widget"]["chart"]["y"]], [None, "pct_prev"])
        self.assertEqual(out["reply"], "증감률을 더했습니다")

    def test_tools_that_are_not_attached_are_refused(self):
        refused = ("create_chart", "query_data", "set_drill", "arrange", "rename_dashboard", "remove_chart", "")
        with llm(said(*[(n, {"chart_id": "c1"}) for n in refused]), said(text="그 일은 할 수 없습니다")):
            out = wa.run_turn(CHART, [], "다 해줘")
        self.assertEqual([(t["ok"], t["detail"]) for t in out["trace"]], [(False, f"위젯 에이전트에 없는 도구입니다: {n}") for n in refused])
        self.assertEqual(out["widget"], hw.normalize_spec(CHART, draft=True))
        self.assertEqual(out["reply"], "그 일은 할 수 없습니다")

    def test_chart_tools_need_a_chart(self):
        with llm(said(("update_chart", {"type": "line"}), ("set_theme", {"brand_color": "#123456"})), said()):
            out = wa.run_turn(None, [], "선 차트로")
        self.assertEqual([(t["ok"], t["detail"]) for t in out["trace"]], [(False, wa.NO_CHART), (False, wa.NO_CHART)])
        self.assertEqual(out["reply"], f"요청을 반영하지 못했습니다. {wa.NO_CHART}")

    def test_the_data_question_ends_the_turn(self):
        with llm(said(("ask_data", {"question": "어떤 매출 데이터를 쓸까요?", "need": "월별 매출 차트"}),
                      ("rename_widget", {"title": "실행되면 안 됨"}))) as m:
            out = wa.run_turn(None, [], "월별 매출 차트 위젯을 만들어줘")
        self.assertEqual(m.call_count, 1)
        self.assertEqual([t["tool"] for t in out["trace"]], ["ask_data"])
        self.assertEqual(out["ask"], {"kind": "data", "question": "어떤 매출 데이터를 쓸까요?", "cards": [], "need": "월별 매출 차트", "hint": wa.ASK_HINT_DATA})
        self.assertEqual((out["reply"], out["widget"]["title"]), ("", "새 위젯"))
        with llm(said(("ask_data", {}))):
            self.assertEqual(wa.run_turn(None, [], "차트")["ask"]["question"], "어떤 데이터를 연결할까요?")

    def test_insights_are_templates_that_follow_the_data(self):
        with llm(said(("set_insight", {"text": "{최고}가 {최고값}으로 가장 높습니다."}))) as m:
            out = wa.run_turn(CHART, [], "인사이트 한 줄")
        self.assertIn("{최고값} = 180", m.call_args.args[0])   # 변수의 지금 값이 프롬프트에 있다 / current values are in the prompt
        self.assertEqual((out["widget"]["insight"], out["model"]["insight"]), ("{최고}가 {최고값}으로 가장 높습니다.", "2026-04가 180으로 가장 높습니다."))
        later = {**out["widget"], "source": {**MONTHLY, "rows": [["2026-01", 300, "서울"], ["2026-02", 100, "부산"]]}}
        self.assertEqual(hw.resolve(later, draft=True)["insight"], "2026-01이 300으로 가장 높습니다.")
        with llm(said(("set_insight", {"text": "{최고}가 180으로 가장 높습니다."})), said()):
            bad = wa.run_turn(CHART, [], "인사이트")
        self.assertFalse(bad["trace"][0]["ok"])
        self.assertTrue(bad["trace"][0]["detail"].startswith("숫자는 직접 쓰지 말고 변수로 써 주세요"))
        self.assertEqual(bad["widget"]["insight"], "")
        with llm(said(("set_insight", {"text": ""}))):
            cleared = wa.run_turn(out["widget"], [], "인사이트 지워줘")
        self.assertEqual((cleared["widget"]["insight"], cleared["model"]["insight"]), ("", ""))

    def test_variables_leaked_into_a_reply_take_their_values(self):
        with llm(said(("add_highlight", {"kind": "top", "n": 1}), text="가장 높은 달({최고})을 강조했고 {최고}가 {최고값}입니다. {없는값}")):
            out = wa.run_turn(CHART, [], "가장 높은 달 강조")
        self.assertEqual(out["reply"], "가장 높은 달(2026-04)을 강조했고 2026-04가 180입니다. 없는값")   # 값이 없으면 괄호만 뗀다 / no value: braces dropped
        self.assertEqual(hw.fill_values("{최고}은 {최고값}이", {"최고": "서울"}), "서울은 최고값이")

    def test_a_hidden_insight_is_told_to_the_model(self):
        draft = {**hw.normalize_spec(CHART, draft=True), "chart": {**CHART["chart"], "type": "kpi"}, "insight": "{최고}가 가장 높습니다"}
        with llm(said(text="네")) as m:
            out = wa.run_turn(draft, [], "어때?")
        self.assertIn("(값을 기다리는 중이라 지금은 숨겨져 있다)", m.call_args.args[0])
        self.assertEqual((out["model"]["insight"], out["model"]["insight_wait"], out["reply"]), ("", True, "네"))

    def test_history_is_cleaned(self):
        out = wa._history([{"role": "user", "text": "가" * 500}, {"role": "x", "text": "답", "trace": [{"tool": "add_kpi", "ok": True}, "junk", {"tool": 3}]},
                           {"role": "user", "text": "  "}, "junk", {"text": 5}] + [{"role": "user", "text": f"{i}"} for i in range(12)])
        self.assertEqual(len(out), 10)
        self.assertEqual(out[0], {"role": "user", "text": "2", "trace": []})
        self.assertEqual(wa._history("x"), [])
        first = wa._history([{"role": "user", "text": "가" * 500}, {"role": "x", "text": "답", "trace": [{"tool": "add_kpi", "ok": True}, "junk", {"tool": 3}]}])
        self.assertEqual(first, [{"role": "user", "text": "가" * 400, "trace": []},
                                 {"role": "agent", "text": "답", "trace": [{"tool": "add_kpi", "ok": True}, {"tool": "3", "ok": False}]}])

    def test_a_wrong_draft_is_a_spec_error_and_a_model_failure_propagates(self):
        with self.assertRaises(hw.SpecError):
            wa.run_turn({"v": 1}, [], "안녕")
        with patch.object(wa.llm, "generate_calls", side_effect=RuntimeError("down")):
            with self.assertRaises(RuntimeError):
                wa.run_turn(None, [], "안녕")


WEB_FX = {"kind": "web", "label": "news.example", "url": "https://news.example/fx", "page": None}
SALES = {"tool": "inline", "columns": ["지점", "매출"], "rows": [["서울", 120], ["부산", 150]]}
USD = {"label": "1달러", "value": 1350.5, "unit": "원", "note": "11/16", "aliases": ["USD", "미국 달러", "달러", "달러화"]}
JPY = {"label": "100엔", "value": 905.1, "unit": "원", "note": "11/16", "aliases": ["JPY", "일본 엔", "엔", "엔화"]}
_SECRET = None


def setUpModule():
    # 서명 키는 실 DB 대신 고정값(이 파일은 임시 DB 도 쓰지 않는다) / a fixed signing key instead of the real DB (no DB in this file)
    global _SECRET
    _SECRET = patch.object(hw, "_secret", return_value=b"k" * 32)
    _SECRET.start()


def tearDownModule():
    _SECRET.stop()


def fetched(origin, result, plan=None, tried=None):
    """가짜 데이터 파이프라인 결과(wd.fetch) / a fake pipeline result"""
    plan = plan or {"sources": [origin or "data"], "view": "kpi", "title": "오늘 환율", "query": "오늘 원달러 환율", "labels": ["원달러"]}
    return {"plan": plan, "origin": origin, "result": result, "tried": tried or {}, "fetched_at": "2026-11-16T10:00:00"}


def pipeline(out, events=()):
    """wd.fetch 를 가짜로: 알림(plan · stage)을 보낸 뒤 out 을 돌려준다(차례로 여러 개면 목록) / fake wd.fetch: announce, then return out"""
    outs = list(out) if isinstance(out, list) else None

    def fake(request, eff, view=None, emit=None, **kw):
        for kind, data in events:
            if emit is not None:
                emit(kind, data)
        return outs.pop(0) if outs is not None else out
    return patch.object(wa.wd, "fetch", side_effect=fake)


class FetchTurnTests(unittest.TestCase):
    """fetch_data — 위젯 전용 데이터 파이프라인(가짜)의 결과를 위젯에 넣는다 / fetch_data fills the widget from the (fake) pipeline"""

    def test_fetched_numbers_fill_the_not_connected_card_and_record_where_they_came_from(self):
        draft = {"v": 2, "title": "새 위젯", "kpis": [PENDING]}
        res = {"ok": True, "kind": "numbers", "numbers": [USD], "refs": [WEB_FX]}
        with llm(said(("fetch_data", {"request": "오늘 원달러 환율", "view": "kpi"})), said(text="환율을 넣었어요.")) as m, \
                pipeline(fetched("web", res)) as f:
            out = wa.run_turn(draft, [], "오늘 원달러 환율로 채워줘", eff={"no": 7}, owner="7")
        self.assertEqual((f.call_args.args, f.call_args.kwargs["view"]), (("오늘 원달러 환율", {"no": 7}), "kpi"))
        self.assertIn("1. fetch_data → 성공: 웹 검색에서 가져와 KPI 카드(으)로 넣음 — 1달러=1350.5원", m.call_args.args[0])   # 결과를 보고 한 번 더 / another look
        self.assertIn("출처(카드 k1): 웹 검색", m.call_args.args[0])
        w = out["widget"]
        self.assertEqual((w["title"], w["kpis"][0]["id"], w["kpis"][0]["label"], w["kpis"][0]["value"], w["kpis"][0]["unit"], w["kpis"][0]["note"]),
                         ("오늘 환율", "k1", "1달러", 1350.5, "원", "11/16"))   # 'KPI 1' 카드는 가져온 이름을 받는다 / an auto-named card takes the fetched name
        self.assertNotIn("pending", w["kpis"][0])
        self.assertEqual(w["origins"], [{"part": "cards", "kind": "web", "query": "오늘 원달러 환율", "view": "kpi", "sql": "", "sig": "", "tables": [],
                                         "refs": [WEB_FX], "fetched_at": "2026-11-16T10:00:00", "cards": [{"id": "k1", "key": "1달러"}]}])
        self.assertIsNone(out["ask"])
        self.assertEqual((out["model"]["kpis"][0]["text"], out["model"]["origins"], out["model"]["refresh"], out["model"]["refs"]),
                         ("1,350.5원", [{"kind": "web", "label": "웹 검색", "fetched_at": "2026-11-16T10:00:00"}], True, [WEB_FX]))
        self.assertEqual([(t["agent"], t["tool"], t["ok"], t["say"]) for t in out["trace"]],
                         [("Data Agent", "fetch_data", True, "웹 검색에서 가져와 KPI 카드(으)로 넣었습니다.")])
        self.assertEqual(out["reply"], "환율을 넣었어요.")

    def test_numbers_pair_with_cards_by_name_never_by_position(self):
        # 3단계 검토: 순서로 채워 '엔화' 카드에 달러 값이 들어갔다 / phase-3 review: positional filling put the dollar into '엔화'
        draft = {"v": 2, "title": "환율", "kpis": [{**PENDING, "label": "엔화"}, {**PENDING, "id": "k2", "label": "원달러"}, {**PENDING, "id": "k3", "label": "유가"}]}
        res = {"ok": True, "kind": "numbers", "numbers": [USD, JPY], "refs": [WEB_FX]}
        with llm(said(("fetch_data", {"request": "달러 엔화 환율"})), said()), pipeline(fetched("web", res)):
            out = wa.run_turn(draft, [], "환율 연결해줘")
        k = {c["id"]: c for c in out["widget"]["kpis"]}
        self.assertEqual((k["k1"]["label"], k["k1"]["value"], k["k2"]["label"], k["k2"]["value"]), ("엔화", 905.1, "원달러", 1350.5))
        self.assertTrue(k["k3"]["pending"])   # 맞는 숫자가 없는 카드는 그대로 / a card without a match stays
        self.assertEqual(out["widget"]["origins"][0]["cards"], [{"id": "k1", "key": "100엔"}, {"id": "k2", "key": "1달러"}])

    def test_a_fetched_table_becomes_the_chart_or_data_kpi_cards(self):
        res = {"ok": True, "kind": "table", "table": SALES, "sql": "SELECT 지점, 매출 FROM sales_branch_monthly",
               "tables": ["sales_branch_monthly"], "refs": [{"kind": "data", "label": "sales_branch_monthly", "url": "", "page": None}]}
        chart_plan = {"sources": ["data"], "view": "chart", "title": "지점별 매출", "query": "이번 달 지점별 매출", "labels": []}
        with llm(said(("fetch_data", {"request": "지점별 매출"})), said()), pipeline(fetched("data", res, chart_plan)):
            out = wa.run_turn(None, [], "지점별 매출 차트", owner="7")
        w = out["widget"]
        self.assertEqual((w["title"], w["source"], w["chart"]["type"], w["chart"]["x"], [y["col"] for y in w["chart"]["y"]], w["kpis"]),
                         ("지점별 매출", SALES, "bar", "지점", ["매출"], []))
        o = w["origins"][0]
        self.assertEqual((o["part"], o["kind"], o["sql"], o["tables"], o["cards"], o["sig"]),
                         ("source", "data", "SELECT 지점, 매출 FROM sales_branch_monthly", ["sales_branch_monthly"], [],
                          hw.sign_sql("7", "SELECT 지점, 매출 FROM sales_branch_monthly")))   # 서버가 만든 SQL 에만 서명 / the server signs its own SQL
        # 사용자가 고른 차트 종류는 새 데이터에서도 그대로 / the chosen chart type survives new data
        line = {**CHART, "chart": {**CHART["chart"], "type": "line"}}
        with llm(said(("fetch_data", {"request": "지점별 매출"})), said()), pipeline(fetched("data", res, chart_plan)):
            self.assertEqual(wa.run_turn(line, [], "데이터를 지점별 매출로")["widget"]["chart"]["type"], "line")
        # 숫자 모양(kpi)이면 데이터 KPI 카드 — 이름 있는 데이터 연결 전 카드부터 / a kpi view makes data cards, named not-connected cards first
        kpi_plan = {**chart_plan, "view": "kpi", "labels": ["매출 합계"]}
        with llm(said(("fetch_data", {"request": "지점 매출 합계"})), said()), pipeline(fetched("data", res, kpi_plan)):
            out = wa.run_turn({"v": 2, "title": "매출", "kpis": [{**PENDING, "label": "총매출"}]}, [], "총매출 카드에 매출을 연결해줘")
        k = out["widget"]["kpis"][0]
        self.assertEqual((k["id"], k["label"], k["source"], k["col"], out["widget"]["chart"], out["widget"]["title"]),
                         ("k1", "총매출", hw.SOURCE_ID, "매출", None, "매출"))   # 사용자가 지은 제목은 그대로 / a user's title stays
        self.assertEqual(out["model"]["kpis"][0]["text"], "270")

    def test_table_columns_pair_with_cards_by_name_and_skip_periods(self):
        # 3단계 검토: 순서로 붙여 '매출' 카드에 연도(2,026)가 들어가고, [이익, 매출] 이 [매출, 이익] 열과 뒤바뀌었다
        # phase-3 review: positional pairing put the year into '매출' and swapped [이익, 매출] against [매출, 이익]
        table = {"tool": "inline", "columns": ["연도", "매출", "이익"], "rows": [[2026, 120, 30], [2025, 100, 20]]}
        res = {"ok": True, "kind": "table", "table": table, "refs": []}
        plan = {"sources": ["data"], "view": "kpi", "title": "실적", "query": "연도별 매출 이익", "labels": ["이익", "매출"]}
        with llm(said(("fetch_data", {"request": "매출 이익"})), said()), pipeline(fetched("data", res, plan)):
            out = wa.run_turn(None, [], "매출과 이익 카드")
        self.assertEqual([(k["label"], k["col"]) for k in out["widget"]["kpis"]], [("이익", "이익"), ("매출", "매출")])
        with llm(said(("fetch_data", {"request": "매출"})), said()), pipeline(fetched("data", res, {**plan, "labels": ["매출"]})):
            out = wa.run_turn(None, [], "매출 카드")
        self.assertEqual([(k["label"], k["col"]) for k in out["widget"]["kpis"]], [("매출", "매출")])   # 연도가 아니라 매출 / not the year

    def test_lists_and_text_become_blocks_that_replace_their_own_kind(self):
        items = [{"title": "환율 1,350원 돌파", "sub": "11/16 · news.example", "url": "https://news.example/fx"}]
        plan = {"sources": ["web"], "view": "list", "title": "환율 뉴스", "query": "오늘 환율 뉴스", "labels": []}
        with llm(said(("fetch_data", {"request": "환율 뉴스", "view": "list"})), said()), \
                pipeline(fetched("web", {"ok": True, "kind": "items", "items": items, "refs": [WEB_FX]}, plan)):
            out = wa.run_turn(None, [], "환율 뉴스 위젯")
        self.assertEqual((out["widget"]["blocks"], out["model"]["blocks"], out["model"]["empty"], out["widget"]["title"]),
                         ([{"type": "list", "items": items}], [{"type": "list", "items": items}], False, "환율 뉴스"))
        draft = {**out["widget"], "blocks": [{"type": "text", "text": "옛 요약"}, {"type": "list", "items": items}]}
        with llm(said(("fetch_data", {"request": "환율 요약", "view": "text"})), said()), \
                pipeline(fetched("docs", {"ok": True, "kind": "text", "text": "새 요약", "refs": []}, {**plan, "view": "text", "sources": ["docs"]})):
            out = wa.run_turn(draft, [], "요약도 바꿔줘")
        self.assertEqual(out["widget"]["blocks"], [{"type": "list", "items": items}, {"type": "text", "text": "새 요약"}])
        # 목록 출처(웹)는 그대로, 글 출처(문서)가 더해진다 / the list keeps its web origin and the text adds a documents origin
        self.assertEqual([(o["part"], o["kind"]) for o in out["widget"]["origins"]], [("list", "web"), ("text", "docs")])
        self.assertEqual(out["trace"][0]["say"], "사내 문서에서 가져와 글(으)로 넣었습니다.")

    def test_each_part_keeps_its_own_origin(self):
        # 3단계 검토: 사내 데이터 차트에 웹 환율 카드를 더하자 출처가 웹으로 덮여 차트가 다시는 새로 가져와지지 않았다
        # phase-3 review: adding a web rate card to a company-data chart overwrote the origin, so the chart never refreshed again
        res = {"ok": True, "kind": "table", "table": SALES, "sql": "SELECT 지점, 매출 FROM s", "tables": ["s"], "refs": []}
        chart_plan = {"sources": ["data"], "view": "chart", "title": "지점별 매출", "query": "지점별 매출", "labels": []}
        with llm(said(("fetch_data", {"request": "지점별 매출"})), said()), pipeline(fetched("data", res, chart_plan)):
            first = wa.run_turn(None, [], "지점별 매출 차트", owner="7")["widget"]
        with llm(said(("fetch_data", {"request": "원달러 환율", "view": "kpi"})), said()), \
                pipeline(fetched("web", {"ok": True, "kind": "numbers", "numbers": [USD], "refs": [WEB_FX]})):
            out = wa.run_turn(first, [], "환율 카드도 넣어줘", owner="7")
        parts = [(o["part"], o["kind"], o["sql"]) for o in out["widget"]["origins"]]
        self.assertEqual(parts, [("source", "data", "SELECT 지점, 매출 FROM s"), ("cards", "web", "")])
        self.assertEqual([o["kind"] for o in out["model"]["origins"]], ["data", "web"])

    def test_cards_the_user_removes_or_sets_leave_their_origin(self):
        # 3단계 검토: 지운 카드의 id(k1)를 새 고정 카드가 다시 받아, 다시 가져오기가 사용자의 숫자를 덮어썼다
        # phase-3 review: a new fixed card reused the removed card's id (k1), and a refresh overwrote the user's number
        widget = {"v": 2, "title": "환율", "kpis": [{"label": "1달러", "value": 1350, "unit": "원"}, {"label": "100엔", "value": 905, "unit": "원"}],
                  "origins": [{"part": "cards", "kind": "web", "query": "환율", "view": "kpi", "fetched_at": "2026-11-16T10:00:00",
                               "cards": [{"id": "k1", "key": "1달러"}, {"id": "k2", "key": "100엔"}]}]}
        with llm(said(("remove_kpi", {"kpi_id": "1달러"}), ("add_kpi", {"label": "목표", "value": 1000}))):
            out = wa.run_turn(widget, [], "달러 카드는 지우고 목표 1000 카드 넣어줘")
        self.assertEqual([(k["id"], k["label"]) for k in out["widget"]["kpis"]], [("k2", "100엔"), ("k1", "목표")])
        self.assertEqual(out["widget"]["origins"][0]["cards"], [{"id": "k2", "key": "100엔"}])   # 새 k1 은 가져온 카드가 아니다 / the new k1 is not fetched
        with llm(said(("add_kpi", {"kpi_id": "100엔", "value": 900}))):
            out = wa.run_turn(out["widget"], [], "엔화는 900으로 고정해줘")
        self.assertEqual(out["widget"]["origins"], [])   # 사용자가 정한 숫자 / the user's own number

    def test_a_tool_result_that_cannot_be_saved_fails_alone_and_the_turn_goes_on(self):
        # 3단계 검토: 가져오기는 성공했는데 정의 상한(10만 자)에 걸려 턴 전체를 잃었다 — 이제 그 도구만 실패하고 같은 턴의 이름 바꾸기는 남는다
        # phase-3 review: a successful fetch broke the 100k cap and lost the turn; now only that tool fails and the rename stays
        huge = {"tool": "inline", "columns": ["이름", "메모", "설명", "값"], "rows": [[f"항목{i}", "가" * 290, "나" * 290, i] for i in range(200)]}
        res = {"ok": True, "kind": "table", "table": huge, "refs": []}
        plan = {"sources": ["data"], "view": "chart", "title": "큰 표", "query": "큰 표", "labels": []}
        with llm(said(("rename_widget", {"title": "이름만 바꿈"}), ("fetch_data", {"request": "큰 표"})), said()), pipeline(fetched("data", res, plan)):
            out = wa.run_turn(None, [], "이름 바꾸고 큰 표 가져와")
        self.assertEqual([(t["tool"], t["ok"]) for t in out["trace"]], [("rename_widget", True), ("fetch_data", False)])
        self.assertEqual(out["trace"][1]["detail"], "위젯에 넣은 데이터가 너무 큽니다. 줄 수나 글자 수를 줄여 주세요")
        self.assertEqual((out["widget"]["title"], out["widget"]["source"], out["widget"]["origins"]), ("이름만 바꿈", None, []))
        # 표를 지우는 kpi 모양에서도 차트에 묶인 카드는 연결을 푼다 / a kpi view that removes the chart unlinks cards tied to it
        linked = {**CHART, "kpis": [{"label": "합계", "source": "s1", "col": "매출", "agg": "sum", "link": "c1"}]}
        res = {"ok": True, "kind": "table", "table": MONTHLY, "refs": []}
        with llm(said(("fetch_data", {"request": "매출 합계", "view": "kpi"})), said()), \
                pipeline(fetched("data", res, {**plan, "view": "kpi", "labels": []})):
            out = wa.run_turn(linked, [], "매출 합계 카드로")
        self.assertEqual((out["trace"][0]["ok"], out["widget"]["chart"], out["widget"]["kpis"][0]["link"]), (True, None, ""))

    def test_nothing_found_fails_the_tool_and_changes_nothing(self):
        tried = {"data": "사내 데이터에서 찾지 못했습니다", "web": "웹 검색을 쓸 수 없습니다"}
        with llm(said(("fetch_data", {"request": "우리 회사 화성 지사 매출"})), said(text="찾지 못했어요.")) as m, pipeline(fetched(None, None, tried=tried)):
            out = wa.run_turn(None, [], "화성 지사 매출")
        self.assertEqual((out["trace"][0]["ok"], out["trace"][0]["detail"]),
                         (False, "요청한 내용을 찾지 못했습니다(사내 데이터: 사내 데이터에서 찾지 못했습니다, 웹 검색: 웹 검색을 쓸 수 없습니다)"))
        self.assertIn("fetch_data → 실패: 요청한 내용을 찾지 못했습니다", m.call_args.args[0])
        self.assertEqual((out["widget"]["title"], out["widget"]["origins"], out["model"]["empty"], out["reply"]), ("새 위젯", [], True, "찾지 못했어요."))
        with llm(said(("fetch_data", {"request": "  "})), said()), pipeline(fetched("web", None)) as f:
            out = wa.run_turn(None, [], "가져와")
        self.assertEqual((out["trace"][0]["detail"], f.call_count), ("가져올 내용을 한 문장으로 적어 주세요", 0))

    def test_a_retried_period_is_told(self):
        # 3단계 검토: 빈 결과를 최근 기간으로 다시 물었으면 그렇게 했다고 말한다 / a retried period is told in the trace and the reply
        res = {"ok": True, "kind": "table", "table": SALES, "refs": [], "note": wa.wd.RETRY_NOTE}
        with llm(said(("fetch_data", {"request": "이번 달 지점별 매출"})), said()), \
                pipeline(fetched("data", res, {"sources": ["data"], "view": "chart", "title": "t", "query": "q", "labels": []})):
            out = wa.run_turn(None, [], "이번 달 지점별 매출")
        self.assertIn(wa.wd.RETRY_NOTE, out["trace"][0]["say"])
        self.assertIn(wa.wd.RETRY_NOTE, out["reply"])

    def test_progress_is_announced_with_an_early_draft(self):
        plan = {"sources": ["web", "docs"], "view": "kpi", "title": "오늘 환율", "query": "오늘 원달러 환율", "labels": ["원달러", "엔화"]}
        res = {"ok": True, "kind": "numbers", "numbers": [USD], "refs": []}
        events = []
        with llm(said(("fetch_data", {"request": "환율"})), said()), \
                pipeline(fetched("web", res, plan), [("plan", plan), ("stage", {"source": "web", "label": "웹 검색"})]):
            out = wa.run_turn(None, [], "환율 위젯", emit=lambda k, d: events.append((k, d)))
        # 2026-11-19: 라운드(고른 도구) → 미리 그린 위젯 → 찾을 곳 → 갈래 시작 → 도구 결과 / round, early draft, plan, stage, tool result
        self.assertEqual([k for k, _ in events], ["round", "draft", "plan", "stage", "tool"])
        self.assertEqual(events[0][1], {"no": 1, "tools": [{"tool": "fetch_data", "label": "데이터 가져오기"}]})
        self.assertEqual(events[2][1], {"sources": ["web", "docs"], "view": "kpi", "forced": False})
        self.assertEqual((events[4][1]["tool"], events[4][1]["ok"], events[4][1]["round"]), ("fetch_data", True, 1))
        events = events[1:]
        draft = events[0][1]["model"]
        # 데이터가 오기 전에 제목 · 칸 모양을 먼저 / the title and slots before the data
        self.assertEqual((draft["title"], draft["skeleton"], draft["empty"], draft["kpis"]),
                         ("오늘 환율", {"view": "kpi", "labels": ["원달러", "엔화"], "sources": ["웹 검색", "사내 문서"]}, False, []))
        self.assertEqual(events[2][1], {"source": "web", "label": "웹 검색"})
        self.assertNotIn("skeleton", out["model"])
        with llm(said(("fetch_data", {"request": "환율"})), said()), pipeline(fetched("web", res, plan), [("plan", plan)]):
            self.assertEqual(wa.run_turn(None, [], "환율 위젯")["widget"]["kpis"][0]["label"], "1달러")   # 알림 없이도 / without emit


class Round2Tests(unittest.TestCase):
    """2026-11-19 대화 화면 2차: 사용자가 고른 곳 · 멈추기 · 라운드 표시 / chat round 2: the chosen place, stopping, rounds"""

    def test_a_chosen_place_reaches_the_pipeline_and_the_prompt(self):
        res = {"ok": True, "kind": "numbers", "numbers": [USD], "refs": []}
        with llm(said(("fetch_data", {"request": "환율"})), said()) as m, pipeline(fetched("docs", res)) as f:
            wa.run_turn(None, [], "환율 위젯", source="docs")
        self.assertEqual(f.call_args.kwargs["sources"], ["docs"])
        self.assertIn("[가져올 곳] 사용자가 '사내 문서'에서만 가져오도록 정했다", m.call_args_list[0].args[0])
        with llm(said(("fetch_data", {"request": "환율"})), said()) as m, pipeline(fetched("web", res)) as f:
            wa.run_turn(None, [], "환율 위젯", source="db")   # 모르는 곳 = 에이전트가 고른다 / an unknown place lets the agent decide
        self.assertIsNone(f.call_args.kwargs["sources"])
        self.assertNotIn("[가져올 곳]", m.call_args_list[0].args[0])
        # 메인 채팅 꼴의 [자동 ▾] 사내 = 사내 데이터 + 사내 문서 / the main-chat [Auto ▾] internal = company data and documents
        with llm(said(("fetch_data", {"request": "규정"})), said()) as m, pipeline(fetched("docs", res)) as f:
            wa.run_turn(None, [], "규정 위젯", source="internal")
        self.assertEqual(f.call_args.kwargs["sources"], ["data", "docs"])
        self.assertIn("[가져올 곳] 사용자가 '사내(사내 데이터 · 사내 문서)'에서만", m.call_args_list[0].args[0])

    def test_trace_entries_know_their_round(self):
        with llm(said(("update_chart", {"type": "line"})), said(("rename_widget", {"title": "매출"})), said()):
            out = wa.run_turn(None, [], "선으로")
        self.assertEqual([(t["tool"], t["ok"], t["round"]) for t in out["trace"]], [("update_chart", False, 1), ("rename_widget", True, 2)])

    def test_a_stop_ends_the_turn_between_rounds_and_tools(self):
        with llm(said(("rename_widget", {"title": "가"}))) as m, self.assertRaises(wa.wd.Cancelled):
            wa.run_turn(None, [], "x", cancel=lambda: True)
        self.assertEqual(m.call_count, 0)   # 멈춘 뒤에는 모델을 부르지 않는다 / no model call once stopped
        flags, events = iter([False, False]), []
        with llm(said(("rename_widget", {"title": "가"}), ("set_insight", {"text": ""}))), self.assertRaises(wa.wd.Cancelled):
            wa.run_turn(None, [], "x", emit=lambda k, d: events.append(k), cancel=lambda: next(flags, True))
        self.assertEqual(events, ["round"])   # 도구를 하나도 실행하지 않았다 / no tool ran
        # 데이터 가져오기 안의 멈춤은 도구 실패가 아니라 턴의 끝 / a stop inside fetching ends the turn, not the tool
        with llm(said(("fetch_data", {"request": "환율"})), said()), patch.object(wa.wd, "fetch", side_effect=wa.wd.Cancelled()), \
                self.assertRaises(wa.wd.Cancelled):
            wa.run_turn(None, [], "환율")


class AgentApiTests(unittest.IsolatedAsyncioTestCase):
    """/api/home/agent 라우트 / the /api/home/agent routes"""

    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(home_widgets_api.router)

    async def req(self, method, path, json=None):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
            return await client.request(method, path, json=json)

    async def test_turn_and_tools(self):
        with llm(said(("add_kpi", {"value": 3, "label": "대기 결재", "unit": "건"}))):
            r = await self.req("POST", "/api/home/agent/turn", json={"widget": None, "messages": [], "message": "  대기 결재 3건 카드  "})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(set(body), {"widget", "model", "reply", "trace", "ask"})
        self.assertEqual((body["model"]["kpis"][0]["text"], body["ask"]), ("3건", None))
        r = await self.req("GET", "/api/home/agent/tools")
        self.assertEqual(r.json(), {"tree": wa.tool_tree()})

    async def test_errors(self):
        for body, detail in (({"message": "   "}, "요청 내용을 입력해 주세요"), ({"message": 5}, "요청 내용을 입력해 주세요"),
                             ({"message": "가" * 2001}, "요청은 2000자까지 쓸 수 있습니다"),
                             ({"message": "안녕", "widget": {"v": 1}}, "지원하지 않는 위젯 정의입니다. 위젯 에이전트에서 다시 만들어 주세요"),
                             ({"message": "안녕", "widget": "글자"}, "위젯 정의 형식이 올바르지 않습니다")):
            r = await self.req("POST", "/api/home/agent/turn", json=body)
            self.assertEqual((r.status_code, r.json()["detail"]), (422, detail), body)
        with patch.object(wa.llm, "generate_calls", side_effect=RuntimeError("quota")):
            r = await self.req("POST", "/api/home/agent/turn", json={"message": "안녕"})
        self.assertEqual((r.status_code, r.json()["detail"]), (503, home_widgets_api.AGENT_DOWN))

    async def test_turns_fetch_within_the_identitys_permissions(self):
        res = {"ok": True, "kind": "numbers", "numbers": [{"label": "원달러", "value": 1350.5, "unit": "원", "note": ""}], "refs": []}
        with patch.object(home_widgets_api.access, "resolve_eff", return_value={"no": 7}) as eff, \
                llm(said(("fetch_data", {"request": "환율"})), said()), pipeline(fetched("web", res)) as f:
            r = await self.req("POST", "/api/home/agent/turn", json={"acting_user_id": "7", "message": "환율 위젯"})
        self.assertEqual(r.status_code, 200)
        eff.assert_called_once_with("7")
        self.assertEqual(f.call_args.args[1], {"no": 7})
        self.assertEqual(r.json()["widget"]["kpis"][0]["label"], "원달러")

    async def stream(self, body):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
            r = await client.post("/api/home/agent/turn/stream", json=body)
        events = []
        for chunk in r.text.split("\n\n"):
            lines = dict(line.split(": ", 1) for line in chunk.splitlines() if ": " in line)
            if "event" in lines:
                events.append((lines["event"], __import__("json").loads(lines["data"])))
        return r, events

    async def test_the_stream_sends_stages_an_early_draft_and_the_result(self):
        plan = {"sources": ["web"], "view": "kpi", "title": "오늘 환율", "query": "오늘 원달러 환율", "labels": ["원달러"]}
        res = {"ok": True, "kind": "numbers", "numbers": [{"label": "원달러", "value": 1350.5, "unit": "원", "note": ""}], "refs": [WEB_FX]}
        with patch.object(home_widgets_api.access, "resolve_eff", return_value=None), \
                llm(said(("fetch_data", {"request": "환율"})), said(text="넣었어요.")), \
                pipeline(fetched("web", res, plan), [("plan", plan), ("stage", {"source": "web", "label": "웹 검색"})]):
            r, events = await self.stream({"acting_user_id": "7", "widget": None, "messages": [], "message": "환율 위젯"})
        self.assertEqual((r.status_code, r.headers["content-type"].split(";")[0]), (200, "text/event-stream"))
        self.assertEqual([k for k, _ in events], ["round", "draft", "plan", "stage", "tool", "done"])
        self.assertEqual(events[1][1]["model"]["skeleton"]["sources"], ["웹 검색"])
        done = events[5][1]
        self.assertEqual(set(done), {"widget", "model", "reply", "trace", "ask"})
        self.assertEqual((done["model"]["kpis"][0]["text"], done["reply"]), ("1,350.5원", "넣었어요."))

    async def test_stream_errors(self):
        # 본문이 틀리면 스트림을 열기 전에 422 / a wrong body is a 422 before any stream opens
        for body in ({"message": " "}, {"message": "안녕", "widget": {"v": 1}}):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                r = await client.post("/api/home/agent/turn/stream", json=body)
            self.assertEqual(r.status_code, 422, body)
        with patch.object(wa.llm, "generate_calls", side_effect=RuntimeError("quota")):
            r, events = await self.stream({"message": "안녕"})
        self.assertEqual((r.status_code, events), (200, [("error", {"status": 503, "detail": home_widgets_api.AGENT_DOWN})]))


    async def test_a_wrong_place_is_422_and_auto_is_the_agents_pick(self):
        for path in ("/api/home/agent/turn", "/api/home/agent/turn/stream"):
            r = await self.req("POST", path, json={"message": "안녕", "source": "db"})
            self.assertEqual((r.status_code, r.json()["detail"]), (422, "데이터를 가져올 곳이 올바르지 않습니다"), path)
        with llm(said(("rename_widget", {"title": "가"})), said()) as m:
            r = await self.req("POST", "/api/home/agent/turn", json={"message": "안녕", "source": "auto"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("[가져올 곳]", m.call_args_list[0].args[0])
        with llm(said(("rename_widget", {"title": "가"})), said()) as m:
            r = await self.req("POST", "/api/home/agent/turn", json={"message": "안녕", "source": "internal"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("사내(사내 데이터 · 사내 문서)", m.call_args_list[0].args[0])

if __name__ == "__main__":
    unittest.main()
