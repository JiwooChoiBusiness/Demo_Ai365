# -*- coding: utf-8 -*-
"""Visualize Agent 확장(2026-09-21) — 기간 컬럼 판정·계산 값·조건부 강조·드릴다운 설정. 실제 LLM·real DB 없음.

Visualize Agent extensions (2026-09-21) — period columns, calculated values, conditional highlights and the drill-down
path. No real LLM or real DB."""
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from db_fixture import isolate_db
from app import boards, report_agent, report_dash as rd, reports_api

COLS = ["지점", "월", "매출", "불량수", "검사수"]
# 일부러 10월을 맨 앞에 둔다 — 글자 순으로는 10월 < 1월 이다 / 10월 comes first on purpose: by code points 10월 < 1월
ROWS = [["강남점", "10월", 150, 3, 100], ["광주점", "10월", 30, 4, 40],
        ["강남점", "1월", 100, 1, 100], ["광주점", "1월", 50, 2, 50],
        ["강남점", "2월", 120, 2, 100], ["광주점", "2월", 40, 1, 50],
        ["강남점", "3월", 90, 0, 100], ["광주점", "3월", 60, 3, 60]]


def state_with(charts=None, cols=COLS, rows=ROWS):
    return rd.normalize_state({"title": "매출", "sources": [{"columns": cols, "rows": rows}], "charts": charts or []})


def comp(st, i=0):
    c = st["charts"][i]
    return rd.compute(c, next(s for s in st["sources"] if s["id"] == c["source"]))


def calls(*items, text=""):
    return {"calls": [{"name": n, "args": a} for n, a in items], "text": text}


class PeriodTests(unittest.TestCase):
    def test_labels_are_read_by_shape_and_bare_digits_only_by_the_column_hint(self):
        p = rd.parse_period
        self.assertEqual([p(v) for v in ("2026-03-15", "2026.3.5 00:00:00", "2026년 3월 15일")],
                         [("date", 2026, 315), ("date", 2026, 305), ("date", 2026, 315)])
        self.assertEqual([p(v) for v in ("2026-03", "2026/3", "2026년 3월", "3월", "12 월")],
                         [("month", 2026, 3), ("month", 2026, 3), ("month", 2026, 3), ("month", 0, 3), ("month", 0, 12)])
        self.assertEqual([p(v) for v in ("2026 Q1", "2026-Q4", "1분기", "2026년 2분기", "3Q")],
                         [("quarter", 2026, 1), ("quarter", 2026, 4), ("quarter", 0, 1), ("quarter", 2026, 2), ("quarter", 0, 3)])
        self.assertEqual([p(v) for v in ("12주차", "W05", "2026-W12", "2026년")],
                         [("week", 0, 12), ("week", 0, 5), ("week", 2026, 12), ("year", 2026, 0)])
        self.assertEqual([p(v) for v in ("13월", "강남점", "", "2026", 2026, "202603", 3)], [None] * 7)   # 숫자뿐이면 이름 없이는 모른다
        self.assertEqual([p(2026.0, "year"), p("202603", "month"), p(3, "month"), p("2", "quarter"), p("20260315", "date")],
                         [("year", 2026, 0), ("month", 2026, 3), ("month", 0, 3), ("quarter", 0, 2), ("date", 2026, 315)])
        self.assertEqual([rd.period_hint(c) for c in ("연도", "기준년월", "분기", "주차", "판매일자", "지점", "year_month")],
                         ["year", "month", "quarter", "week", "date", "", "month"])

    def test_period_columns_are_found_per_source_and_amounts_are_not_periods(self):
        st = rd.normalize_state({"sources": [{"columns": COLS, "rows": ROWS},
                                             {"columns": ["연도", "월매출", "일자"], "rows": [[2025, 1200, "2025-01-31"], [2026, 7, "2026-01-31"]]}]})
        self.assertEqual([s["periods"] for s in st["sources"]], [{"월": "month"}, {"연도": "year", "일자": "date"}])
        self.assertEqual(st["sources"][0]["types"]["월"], "text")            # 종류(types)는 그대로 — 기간은 따로 적는다 / types are untouched

    def test_a_period_axis_sorts_by_period_not_by_code_points(self):
        st = state_with([{"source": "s1", "type": "line", "x": "월", "y": ["매출"], "sort": {"by": "x"}}])
        self.assertEqual(comp(st)["x"], ["1월", "2월", "3월", "10월"])
        st["charts"][0]["sort"] = {"by": "x", "dir": "desc"}
        self.assertEqual(comp(st)["x"], ["10월", "3월", "2월", "1월"])
        self.assertEqual(rd.auto_chart_spec({**st["sources"][0], "columns": ["월", "매출"], "types": {"월": "text", "매출": "number"},
                                             "rows": [["1월", 1]], "periods": {"월": "month"}})["sort"], {"by": "x", "dir": "asc"})


class CalcTests(unittest.TestCase):
    def gangnam(self, y, **over):
        return state_with([{"source": "s1", "type": "line", "x": "월", "y": [y], "filters": [{"col": "지점", "selected": ["강남점"]}], **over}])

    def test_order_dependent_calcs_pin_the_period_order_and_leave_gaps(self):
        st = self.gangnam({"column": "매출", "calc": "pct_prev"})
        c = st["charts"][0]
        self.assertEqual((c["sort"], c["y"][0]["name"], c["y"][0]["unit"]), ({"by": "x", "dir": "asc"}, "매출 증감률", "%"))
        out = comp(st)
        self.assertEqual(out["x"], ["1월", "2월", "3월", "10월"])
        self.assertEqual(out["series"][0]["values"], [None, 20.0, -25.0, 66.666667])
        self.assertEqual((out["series"][0]["unit"], out["series"][0]["calc"]), ("%", "pct_prev"))
        self.assertEqual(comp(self.gangnam({"column": "매출", "calc": "diff_prev"}))["series"][0]["values"], [None, 20.0, -30.0, 60.0])
        self.assertEqual(comp(self.gangnam({"column": "매출", "calc": "cumsum"}))["series"][0]["values"], [100.0, 220.0, 310.0, 460.0])
        self.assertEqual(comp(self.gangnam({"column": "매출", "calc": "moving_avg", "window": 2}))["series"][0]["values"], [None, 110.0, 105.0, 120.0])
        self.assertEqual(st["charts"][0]["y"][0].get("window"), None)
        # 자르기(limit)는 계산 뒤 — 첫 칸도 진짜 앞 달과 비교된 값이다 / the limit cuts after the calc
        self.assertEqual(comp(self.gangnam({"column": "매출", "calc": "cumsum"}, limit=2))["series"][0]["values"], [100.0, 220.0])

    def test_share_rank_and_pair_calcs_run_before_sorting_so_the_chart_can_sort_by_them(self):
        st = state_with([{"source": "s1", "type": "bar", "x": "지점", "sort": {"by": "y"},
                          "y": [{"column": "불량수", "calc": "ratio_pct", "by_column": "검사수"}]}])
        y = st["charts"][0]["y"][0]
        self.assertEqual((y["name"], y["by"], y["unit"]), ("불량수 ÷ 검사수", {"col": "검사수", "agg": "sum"}, "%"))
        out = comp(st)
        self.assertEqual((out["x"], out["series"][0]["values"]), (["광주점", "강남점"], [5.0, 1.5]))   # 불량률이 높은 순 / sorted by the ratio
        share = comp(state_with([{"source": "s1", "x": "지점", "y": [{"column": "매출", "calc": "share"}]}]))
        self.assertEqual(share["series"][0]["values"], [71.875, 28.125])
        rank = comp(state_with([{"source": "s1", "x": "월", "y": [{"column": "매출", "calc": "rank"}], "sort": {"by": "x"}}]))
        self.assertEqual((rank["series"][0]["values"], rank["series"][0]["unit"]), ([3.0, 2.0, 3.0, 1.0], "위"))
        # 파레토: 범주 축에서는 정렬한 순서대로 누적한다(기간 축이면 기간 순으로 고정) / Pareto: on a category axis the running share follows the sort
        pareto = comp(state_with([{"source": "s1", "x": "지점", "sort": {"by": "y"}, "y": ["매출", {"column": "매출", "calc": "cum_share"}]}]))
        self.assertEqual((pareto["x"], pareto["series"][1]["values"]), (["강남점", "광주점"], [71.875, 100.0]))

    def test_year_over_year_pairs_the_same_period_of_the_previous_year(self):
        rows = [["2025-01", 100], ["2025-02", 200], ["2026-01", 150], ["2026-02", 100]]
        st = state_with([{"source": "s1", "type": "line", "x": "월", "y": [{"column": "매출", "calc": "yoy"}]}], ["월", "매출"], rows)
        self.assertEqual(comp(st)["series"][0]["values"], [None, None, 50.0, -50.0])

    def test_tools_are_told_why_a_calc_cannot_apply_while_saved_charts_only_lose_the_calc(self):
        raw = {"source": "s1", "type": "bar", "x": "지점", "y": [{"column": "매출", "calc": "pct_prev"}]}
        st = state_with([raw, {"source": "s1", "type": "donut", "x": "지점", "y": [{"column": "매출", "calc": "share"}]}])
        self.assertEqual([c["y"][0].get("calc") for c in st["charts"]], [None, None])      # 차트는 살리고 계산만 걷어낸다 / the chart survives
        self.assertEqual([c["y"][0].get("unit") for c in st["charts"]], [None, None])
        with self.assertRaises(ValueError) as cm:
            rd.norm_chart(raw, {s["id"]: s for s in st["sources"]}, set(), strict=True)
        self.assertIn("이 Source 의 기간 컬럼: 월", str(cm.exception))
        with self.assertRaises(ValueError):
            rd.norm_chart({"source": "s1", "x": "지점", "y": [{"column": "매출", "calc": "ratio"}]}, {s["id"]: s for s in st["sources"]}, set())

    def test_a_percent_series_beside_amounts_becomes_a_line_on_the_right_axis_unless_told(self):
        st = state_with([{"source": "s1", "type": "bar", "x": "월", "y": ["매출", {"column": "매출", "calc": "pct_prev"}]},
                         {"source": "s1", "type": "bar", "x": "월", "y": ["매출", {"column": "매출", "calc": "pct_prev", "type": "bar", "axis": 0}]}])
        self.assertEqual([[(y["type"], y["axis"]) for y in c["y"]] for c in st["charts"]],
                         [[("bar", 0), ("line", 1)], [("bar", 0), ("bar", 0)]])
        again = rd.normalize_state(st)                                                        # 다시 읽어도 그대로 / stable on reload
        self.assertEqual(again["charts"], st["charts"])
        # 같은 컬럼의 원래 값과 계산 값은 다른 계열이다 / the raw and the calculated series of one column are different series
        self.assertEqual(len(st["charts"][0]["y"]), 2)


class HighlightTests(unittest.TestCase):
    def chart(self, highlights, refs=None):
        return state_with([{"source": "s1", "type": "bar", "x": "월", "y": ["매출"], "sort": {"by": "x"},
                            "ref_lines": refs or [], "highlights": highlights}])

    def test_threshold_rules_follow_the_reference_line_and_the_first_rule_wins(self):
        st = self.chart([{"kind": "ref", "ref_label": "목표", "op": "lt"}, {"kind": "top", "n": 3}], [{"label": "목표", "value": 160}])
        rules = st["charts"][0]["highlights"]
        self.assertEqual([(h["id"], h["kind"], h["label"], h["color"], h["dim"]) for h in rules],
                         [("h1", "ref", "목표 미달", rd.HL_COLORS["red"], False), ("h2", "top", "상위 3", "", True)])
        marks = comp(st)["marks"]                                                             # 매출: 1월 150, 2월 160, 3월 150, 10월 180
        self.assertEqual([(m["label"], m["hits"]) for m in marks], [("목표 미달", [0, 2]), ("상위 3", [1, 3])])   # 1월은 앞 규칙 차지 / taken by the first rule
        st["charts"][0]["ref_lines"][0]["value"] = 100
        self.assertEqual(comp(st)["marks"][0]["hits"], [])                                    # 기준선이 움직이면 같이 움직인다 / follows the line

    def test_value_stat_bottom_and_items_rules(self):
        st = self.chart([{"kind": "value", "op": "gte", "value": 170, "color": "green", "label": "170 이상"},
                         {"kind": "items", "items": ["1월", "없는달"], "color": "#123456"}, {"kind": "bottom", "n": 2}])
        marks = {m["label"]: (m["hits"], m["color"], m["dim"]) for m in comp(st)["marks"]}
        # 하위 2 = 1월·3월(150)인데 1월은 앞 규칙이 가져갔다 — 색은 앞 규칙이 이긴다 / bottom 2 = 1월 and 3월, but 1월 already belongs to an earlier rule
        self.assertEqual(marks, {"170 이상": ([3], rd.HL_COLORS["green"], False), "1월, 없는달": ([0], "#123456", True),
                                 "하위 2": ([2], rd.HL_COLORS["amber"], True)})
        avg = comp(self.chart([{"kind": "stat", "stat": "avg"}]))["marks"][0]                 # 평균 160 이상 / at or above the average of 160
        self.assertEqual((avg["label"], avg["hits"]), ("평균 이상", [1, 3]))

    def test_rules_without_a_condition_and_rules_on_pies_are_dropped(self):
        st = self.chart([{"kind": "value"}, {"kind": "ref", "ref_label": "없는선"}, {"color": "red"}, {"kind": "top"}] + [{"kind": "top", "n": i} for i in (1, 2, 4)])
        self.assertEqual([h["label"] for h in st["charts"][0]["highlights"]], ["상위 3", "상위 1", "상위 2"])   # 최대 3개 / three at most
        pie = state_with([{"source": "s1", "type": "pie", "x": "월", "y": ["매출"], "highlights": [{"kind": "top", "n": 1}]}])
        self.assertNotIn("highlights", pie["charts"][0])
        self.assertNotIn("marks", comp(pie))


class DrillAndAgentTests(unittest.TestCase):
    def test_the_drill_path_keeps_real_columns_below_x(self):
        st = state_with([{"source": "s1", "x": "지점", "y": ["매출"], "drill": [" 월 ", "지점", "없음", "월", "불량수", "검사수", "매출"]}])
        self.assertEqual(st["charts"][0]["drill"], ["월", "불량수", "검사수"])
        self.assertNotIn("drill", state_with([{"source": "s1", "x": "지점", "y": ["매출"]}])["charts"][0])

    def test_on_a_source_tab_its_one_report_is_this_chart(self):
        st = state_with([{"source": "s1", "x": "지점", "y": ["매출"]}])
        with patch("app.llm.generate_calls", return_value=calls(text="네")) as m:
            report_agent.run_turn(st, [], "이 차트 설명해줘", None, view="s1")
            report_agent.run_turn(st, [], "이 차트 설명해줘", None)
        self.assertIn("[선택된 차트] c1", m.call_args_list[0].args[0])       # Source 탭 = 그 리포트의 화면 / a Source tab is that report's screen
        self.assertNotIn("[선택된 차트]", m.call_args_list[1].args[0])

    def test_add_calculation_places_the_series_and_reports_the_computed_values(self):
        st = state_with([{"source": "s1", "type": "bar", "x": "월", "y": ["매출"]}])
        note, say = report_agent.run_tool(st, "add_calculation", {"chart_id": "c1", "calc": "pct_prev"}, None)
        c = st["charts"][0]
        self.assertEqual([(y["name"], y.get("calc"), y["type"], y["axis"]) for y in c["y"]],
                         [("매출", None, "bar", 0), ("매출 증감률", "pct_prev", "line", 1)])
        self.assertIn("매출 증감률=[None, 6.666667", note)
        self.assertIn("추가했습니다", say)
        report_agent.run_tool(st, "add_calculation", {"chart_id": "c1", "calc": "moving_avg", "window": 2}, None)
        self.assertEqual((st["charts"][0]["y"][2]["axis"], st["charts"][0]["y"][2]["window"]), (0, 2))      # 눈금이 같은 계산은 같은 축 / same scale, same axis
        report_agent.run_tool(st, "add_calculation", {"chart_id": "c1", "calc": "cumsum", "replace": True}, None)
        self.assertEqual([(y.get("calc"), y["type"]) for y in st["charts"][0]["y"]], [("cumsum", "bar"), ("pct_prev", "line"), ("moving_avg", "line")])
        hbar = state_with([{"source": "s1", "type": "hbar", "x": "지점", "y": ["매출"]}])
        report_agent.run_tool(hbar, "add_calculation", {"chart_id": "c1", "calc": "share"}, None)
        self.assertEqual([y.get("calc") for y in hbar["charts"][0]["y"]], ["share"])                         # 가로 막대는 바꾼다 / replaced on hbar
        with self.assertRaises(ValueError):
            report_agent.run_tool(hbar, "add_calculation", {"chart_id": "c1", "calc": "pct_prev"}, None)     # x 가 기간이 아니다 / not a period axis

    def test_one_round_adds_the_line_then_the_highlight_that_follows_it(self):
        st = state_with([{"source": "s1", "type": "bar", "x": "월", "y": ["매출"], "sort": {"by": "x"}}])
        fake = calls(("add_reference_line", {"chart_id": "c1", "label": "목표", "value": 160}),
                     ("add_highlight", {"chart_id": "c1", "kind": "ref", "ref_label": "목표", "op": "lt", "color": "red"}),
                     ("set_drill", {"chart_id": "c1", "columns": ["지점"]}))
        with patch("app.llm.generate_calls", return_value=fake) as m:
            out = report_agent.run_turn(st, [], "목표 160 못 넘은 달은 빨갛게, 누르면 지점별로", None,
                                        drill={"chart": "c1", "path": [{"col": "월", "value": "3월"}], "level": "지점"})
        self.assertEqual(m.call_count, 1)                                                      # 강조·드릴다운은 한 번에 끝난다 / no follow-up round
        c = out["state"]["charts"][0]
        self.assertEqual((c["highlights"][0]["ref"], c["drill"]), (c["ref_lines"][0]["id"], ["지점"]))
        self.assertIn("'목표 미달' 2곳", out["reply"])
        prompt = m.call_args.args[0]
        self.assertIn("월([기간] month 4개: 1월~10월)", prompt)
        self.assertIn("드릴다운 중: 차트 c1 을(를) 월=3월 (으)로 좁혀 지점별로 보고 있다", prompt)
        prompt2 = report_agent.describe_state(out["state"])
        self.assertIn("강조=[목표 미달]", prompt2)
        self.assertIn("드릴다운=[지점]", prompt2)
        report_agent.run_tool(out["state"], "remove_highlight", {"chart_id": "c1"}, None)
        self.assertEqual(out["state"]["charts"][0]["highlights"], [])
        with self.assertRaises(ValueError):
            report_agent.run_tool(out["state"], "set_drill", {"chart_id": "c1", "columns": ["없는컬럼"]}, None)
        with self.assertRaises(ValueError):
            report_agent.run_tool(out["state"], "add_highlight", {"chart_id": "c1", "kind": "ref", "ref_label": "없는선"}, None)


class CloneTests(unittest.TestCase):
    def test_a_clone_points_at_its_roots_rows_and_carries_none_when_stored_or_sent(self):
        st = state_with([{"source": "s1", "x": "지점", "y": ["매출"]}])
        sid_, made = rd.source_for_new_chart(st, "s1")
        root, clone = st["sources"]
        self.assertTrue(made and clone["rows"] is root["rows"] and clone["columns"] is root["columns"])   # 복사하지 않는다 / no copy
        st["charts"].append(rd.norm_chart({"source": sid_, "x": "월", "y": ["매출"]}, {s["id"]: s for s in st["sources"]}, {"c1"}))
        packed = rd.pack_state(st)
        self.assertEqual([len(s["rows"]) for s in packed["sources"]], [len(ROWS), 0])
        self.assertEqual(len(root["rows"]), len(ROWS))                                        # 원본은 그대로 / packing never touches the live state
        again = rd.normalize_state(packed)
        self.assertTrue(again["sources"][1]["rows"] is again["sources"][0]["rows"])
        self.assertEqual((again["sources"][1]["periods"], comp(again, 1)["x"][:2]), ({"월": "month"}, ["10월", "1월"]))
        data = rd.dashboard_data(st)
        self.assertEqual(([len(s["rows"]) for s in data["sources"]], len(data["items"])), ([len(ROWS), 0], 2))
        # 차트 하나만 떼어 낸 리포트는 복제본이어도 데이터를 직접 갖는다 / a lone report carries its own data even from a clone
        alone = rd.report_data(st, "c2")["sources"]
        self.assertEqual([(s["id"], s["origin"]["clone_of"], len(s["rows"])) for s in alone], [("s2", "", len(ROWS))])

    def test_older_saved_states_whose_clones_copied_the_rows_are_linked_on_load(self):
        old = {"sources": [{"id": "s1", "columns": COLS, "rows": ROWS}, {"id": "s2", "columns": COLS, "rows": [list(r) for r in ROWS], "origin": {"clone_of": "s1"}}],
               "charts": [{"source": "s1", "x": "지점"}, {"source": "s2", "x": "월"}]}
        st = rd.normalize_state(old)
        self.assertTrue(st["sources"][1]["rows"] is st["sources"][0]["rows"])


class DuplicateNoteKpiTests(unittest.TestCase):
    def test_duplicate_makes_a_new_report_tab_beside_the_original_in_one_compare_group(self):
        st = state_with([{"source": "s1", "type": "bar", "x": "월", "y": ["매출"], "size": "full", "title": "월별 매출",
                          "filters": [{"col": "지점", "selected": ["강남점"]}]}, {"source": "s1", "type": "pie", "x": "지점", "y": ["매출"]}])
        copy = rd.duplicate_chart(st, "c1")
        self.assertEqual([(c["id"], c["source"], c.get("compare"), c["size"]) for c in st["charts"]],
                         [("c1", "s1", "g1", "half"), ("c3", "s3", "g1", "half"), ("c2", "s2", None, "half")])
        self.assertEqual((copy["title"], copy["filters"][0]["selected"], st["sources"][2]["label"], st["sources"][2]["origin"]["clone_of"]),
                         ("월별 매출 (복사)", ["강남점"], "월별 매출 (복사)", "s1"))
        self.assertTrue(st["sources"][2]["rows"] is st["sources"][0]["rows"])
        pie = rd.duplicate_chart(st, "c2")
        self.assertNotIn("compare", pie)                                                      # 원·도넛은 눈금이 없다 / no scale to share
        st["charts"] = [c for c in st["charts"] if c["id"] != "c3"]
        self.assertNotIn("compare", rd.normalize_state(st)["charts"][0])                      # 혼자 남은 묶음은 풀린다 / a group of one dissolves
        with self.assertRaises(ValueError):
            rd.duplicate_chart(st, "c9")

    def test_notes_anchor_to_x_values_and_are_not_for_pies(self):
        st = state_with([{"source": "s1", "x": "월", "y": ["매출"], "notes": [{"x": "3월", "text": " 신제품 출시 "}, {"x": "3월", "text": "중복"},
                                                                             {"x": "1월", "text": ""}, {"x": 2026, "text": "가" * 40}]},
                         {"source": "s1", "type": "donut", "x": "월", "y": ["매출"], "notes": [{"x": "3월", "text": "x"}]}])
        self.assertEqual(st["charts"][0]["notes"], [{"id": "n1", "x": "3월", "text": "신제품 출시"}, {"id": "n2", "x": "2026", "text": "가" * rd.MAX_NOTE_TEXT}])
        self.assertNotIn("notes", st["charts"][1])
        self.assertIn("메모=[3월:신제품 출시", report_agent.describe_state(st))

    def test_summary_numbers_point_at_a_source_follow_the_linked_chart_and_compare_periods(self):
        st = state_with([{"source": "s1", "x": "월", "y": ["매출"], "filters": [{"col": "지점", "selected": ["강남점"]}]}])
        st["kpis"] = [{"source": "s1", "column": "매출", "link": "c1", "delta": "prev"}, {"source": "s1", "col": "지점", "agg": "sum", "link": "c9"},
                      {"source": "s1", "col": "*"}, {"source": "s9", "col": "매출"}, {"source": "s1", "col": "없음"}]
        st = rd.normalize_state(st)
        self.assertEqual([(k["id"], k["col"], k["agg"], k["label"], k["link"], k["delta"]) for k in st["kpis"]],
                         [("k1", "매출", "sum", "매출 합계", "c1", "prev"), ("k2", "지점", "count", "지점 건수", "", ""), ("k3", "*", "count", "건수", "", "")])
        v = rd.kpi_value(st["kpis"][0], st)                                                   # 강남점: 1월 100 … 3월 90, 10월 150
        self.assertEqual((v["value"], v["period"], v["prev_period"], v["delta"]), (460.0, "10월", "3월", 66.666667))
        st["charts"][0]["filters"][0]["selected"] = []
        self.assertEqual(rd.kpi_value(st["kpis"][0], st)["value"], 640.0)                     # 연결한 차트의 필터를 따라간다 / follows the linked chart
        self.assertEqual(rd.kpi_value(st["kpis"][2], st), {"value": 8.0, "rows": 8})
        self.assertEqual(rd.dashboard_data(st)["kpis"], st["kpis"])
        self.assertNotIn("kpis", state_with())
        with self.assertRaises(ValueError) as cm:
            rd.norm_kpi({"source": "s1", "col": "없음"}, {s["id"]: s for s in st["sources"]}, st["charts"], set(), strict=True)
        self.assertIn("쓸 수 있는 컬럼", str(cm.exception))
        # 직접 적은 숫자 카드(2026-10-12): source 없이 value 그대로, 이름은 필수, 설명은 40자 / a typed-number card: no source, the value as is, a name is required, notes are cut at 40
        st["kpis"] = st["kpis"] + [{"label": " 목표 ", "value": "1,200", "unit": "원", "note": "2026년 목표"}, {"value": 5}, {"source": "s1", "col": "매출", "note": "x" * 50}]
        st = rd.normalize_state(st)
        self.assertEqual([(k["id"], k["source"], k.get("value"), k["label"], k["unit"], k["note"]) for k in st["kpis"][3:]],
                         [("k4", "", 1200.0, "목표", "원", "2026년 목표"), ("k5", "s1", None, "매출 합계", "", "x" * rd.MAX_KPI_NOTE)])
        self.assertEqual(rd.kpi_value(st["kpis"][3], st), {"value": 1200.0, "rows": 0, "manual": True})
        with self.assertRaisesRegex(ValueError, "이름"):
            rd.norm_kpi({"value": 5}, {}, [], set(), strict=True)
        with self.assertRaisesRegex(ValueError, "숫자"):
            rd.norm_kpi({"label": "x", "value": "abc"}, {}, [], set(), strict=True)

    def test_suggested_cards_are_rule_based_but_not_placed_first_and_the_agent_adds_edits_and_removes_them(self):
        st = state_with([{"source": "s1", "x": "월", "y": ["매출"]}])
        self.assertEqual(rd.auto_kpis(st), [{"source": "s1", "col": "매출", "link": "c1", "delta": "prev"},
                                            {"source": "s1", "col": "불량수", "link": "c1", "delta": ""}, {"source": "s1", "col": "검사수", "link": "c1", "delta": ""}])
        with patch("app.llm.generate_calls", side_effect=RuntimeError("down")):
            out = report_agent.auto_charts(state_with(), None)
        self.assertNotIn("kpis", out["state"])                                                # 첫 화면에는 카드가 없다(2026-10-12) / no cards on the first screen
        note, say = report_agent.run_tool(st, "add_kpi", {"source_id": "Source 1", "column": "매출", "agg": "avg", "label": "평균 매출", "unit": "원",
                                                         "link_chart_id": "차트 1"}, None)
        self.assertEqual([(k["label"], k["agg"], k["link"]) for k in st["kpis"]], [("평균 매출", "avg", "c1")])
        self.assertIn("'평균 매출'(80원)", say)
        report_agent.run_tool(st, "add_kpi", {"source_id": "s1", "column": "매출", "label": "평균 매출", "note": "전 지점"}, None)   # 같은 이름 = 제자리 수정(적은 항목만) / same label edits in place
        self.assertEqual([(k["id"], k["label"], k["agg"], k["unit"], k["note"]) for k in st["kpis"]], [("k1", "평균 매출", "avg", "원", "전 지점")])
        note, say = report_agent.run_tool(st, "add_kpi", {"kpi_id": "k1", "source_id": "s1", "column": "매출", "label": "총 매출", "agg": "sum"}, None)
        self.assertEqual(([(k["id"], k["label"], k["agg"], k["link"]) for k in st["kpis"]], "고쳤습니다" in say), ([("k1", "총 매출", "sum", "c1")], True))
        desc = report_agent.describe_state(st)
        self.assertIn("KPI 카드(대시보드 맨 위 요약 숫자 줄):", desc)
        self.assertIn('k1 "총 매출" = sum(매출) source=s1 연결 차트=c1 단위=원 설명="전 지점"', desc)
        st["kpis"].append(rd.norm_kpi({"label": "목표", "value": 1000}, {}, [], {"k1"}, strict=True))
        self.assertIn('k2 "목표" = 직접 적은 숫자 1000.0', report_agent.describe_state(st))
        report_agent.run_tool(st, "add_kpi", {"kpi_id": "목표", "label": "목표(수정)", "unit": "원"}, None)   # 이름으로 찾아 적은 항목만 — 숫자는 지킨다 / found by name, given fields only; the number stays
        self.assertEqual((st["kpis"][1]["label"], st["kpis"][1]["value"], st["kpis"][1]["unit"], st["kpis"][1]["source"]), ("목표(수정)", 1000.0, "원", ""))
        report_agent.run_tool(st, "remove_kpi", {"label": "k2"}, None)
        report_agent.run_tool(st, "remove_kpi", {}, None)
        self.assertEqual(st["kpis"], [])
        report_agent.run_tool(st, "add_kpi", {"kpi_id": "k9", "source_id": "s1", "column": "매출"}, None)   # 모르는 id 는 새 카드 / an unknown id adds a card
        self.assertEqual([k["id"] for k in st["kpis"]], ["k1"])
        with self.assertRaises(ValueError):
            report_agent.run_tool(st, "add_kpi", {"source_id": "s1", "column": "없는컬럼"}, None)

    def test_the_agent_creates_and_adjusts_cards_from_the_conversation(self):
        # 2026-10-12 사용자 지시 "KPI 카드는 채팅으로 생성하고 조정" / user decision: KPI cards are created and adjusted from the conversation
        st = state_with([{"source": "s1", "x": "월", "y": ["매출"]}])
        note, say = report_agent.run_tool(st, "add_kpi", {"label": "연간 목표", "value": 1200, "unit": "원", "note": "경영 계획"}, None)   # 사용자가 말한 숫자 / a stated number
        self.assertEqual(([(k["id"], k["label"], k.get("value"), k["source"], k["note"]) for k in st["kpis"]], "'연간 목표'(1,200원)" in say),
                         ([("k1", "연간 목표", 1200.0, "", "경영 계획")], True))
        report_agent.run_tool(st, "add_kpi", {"column": "매출", "agg": "sum", "label": "총 매출", "link_chart_id": "c1"}, None)   # Source 생략 = 첫 Source / no source: the first one
        self.assertEqual((st["kpis"][1]["source"], st["kpis"][1]["col"], st["kpis"][1]["link"]), ("s1", "매출", "c1"))
        report_agent.run_tool(st, "add_kpi", {"kpi_id": "연간 목표", "value": "1,500"}, None)                               # 숫자만 바꾼다 / only the number changes
        self.assertEqual((st["kpis"][0]["label"], st["kpis"][0]["value"], st["kpis"][0]["unit"]), ("연간 목표", 1500.0, "원"))
        report_agent.run_tool(st, "add_kpi", {"kpi_id": "KPI 2", "agg": "avg", "label": "평균 매출"}, None)                   # 느슨한 id / a loose id
        self.assertEqual((st["kpis"][1]["id"], st["kpis"][1]["label"], st["kpis"][1]["agg"], st["kpis"][1]["link"]), ("k2", "평균 매출", "avg", "c1"))
        report_agent.run_tool(st, "add_kpi", {"kpi_id": "k1", "column": "검사수"}, None)                                     # 컬럼을 말하면 데이터 카드로 / a column makes it computed
        self.assertEqual((st["kpis"][0]["source"], st["kpis"][0]["col"], st["kpis"][0].get("value"), st["kpis"][0]["label"]), ("s1", "검사수", None, "연간 목표"))
        report_agent.run_tool(st, "add_kpi", {"kpi_id": "k2", "value": 700}, None)                                           # 숫자를 말하면 고정 숫자 카드로 / a number makes it fixed
        self.assertEqual((st["kpis"][1]["source"], st["kpis"][1]["value"], st["kpis"][1]["label"]), ("", 700.0, "평균 매출"))
        with self.assertRaisesRegex(ValueError, "물어보세요"):                                                               # 숫자도 컬럼도 없으면 지어내지 않는다 / neither a column nor a number
            report_agent.run_tool(st, "add_kpi", {"label": "목표"}, None)
        note, say = report_agent.run_tool(st, "arrange_kpis", {"order": ["평균 매출", "k1"]}, None)
        self.assertEqual(([k["id"] for k in st["kpis"]], "순서" in say), (["k2", "k1"], True))
        with self.assertRaisesRegex(ValueError, "찾지 못했습니다"):
            report_agent.run_tool(st, "arrange_kpis", {"order": ["없는 카드"]}, None)
        report_agent.run_tool(st, "remove_kpi", {"kpi_id": "평균 매출"}, None)
        self.assertEqual([k["id"] for k in st["kpis"]], ["k1"])
        with self.assertRaisesRegex(ValueError, "찾지 못했습니다"):
            report_agent.run_tool(st, "remove_kpi", {"label": "없는 카드"}, None)
        # 대화 한 턴: 도구 두 번 → 카드 두 장 + 도구별 답 문장 / one turn: two tool calls make two cards and the per-tool sentences
        st = state_with([{"source": "s1", "x": "월", "y": ["매출"]}])
        with patch("app.llm.generate_calls", return_value=calls(("add_kpi", {"source_id": "s1", "column": "매출", "label": "총 매출", "delta": "prev"}),
                                                                 ("add_kpi", {"label": "연간 목표", "value": 1500, "unit": "원"}))):
            out = report_agent.run_turn(st, [], "KPI 카드로 총 매출이랑 연간 목표 1500원 넣어줘", None)
        self.assertEqual(([(k["label"], k.get("value")) for k in out["state"]["kpis"]], [t["tool"] for t in out["trace"]]),
                         ([("총 매출", None), ("연간 목표", 1500.0)], ["add_kpi", "add_kpi"]))
        self.assertIn("'총 매출'", out["reply"])
        self.assertIn("KPI 카드(대시보드 맨 위 요약 숫자 줄):", report_agent.describe_state(out["state"]))

    def test_conversation_edits_keep_the_source_turn_fields_off_and_refuse_no_ops_and_duplicate_names(self):
        # 리뷰 반영(2026-10-12): 두 Source(같은 컬럼) — 고치기가 카드를 첫 Source 로 옮기지 않는다 / review fix: an edit never moves a card to the first source
        st = rd.normalize_state({"title": "매출", "sources": [{"columns": COLS, "rows": ROWS}, {"columns": COLS, "rows": [[r[0], r[1], r[2] * 2, r[3], r[4]] for r in ROWS]}],
                                 "charts": [{"source": "s1", "x": "월", "y": ["매출"]}, {"source": "s2", "x": "월", "y": ["매출"]}]})
        report_agent.run_tool(st, "add_kpi", {"source_id": "s2", "column": "매출", "label": "B사 매출", "link_chart_id": "c2", "delta": "prev"}, None)
        report_agent.run_tool(st, "add_kpi", {"kpi_id": "k1", "agg": "avg"}, None)
        k = st["kpis"][0]
        self.assertEqual((k["source"], k["agg"], k["link"], k["delta"], k["label"], rd.kpi_value(k, st)["value"]), ("s2", "avg", "c2", "prev", "B사 매출", 160.0))
        with self.assertRaisesRegex(ValueError, "다른 Source"):                                                   # 다른 데이터의 차트에는 못 붙인다 / no link across sources
            report_agent.run_tool(st, "add_kpi", {"kpi_id": "k1", "link_chart_id": "c1"}, None)
        report_agent.run_tool(st, "add_kpi", {"kpi_id": "k1", "link_chart_id": "none", "delta": "none", "unit": "", "note": ""}, None)   # 끄기 / turning fields off
        self.assertEqual((st["kpis"][0]["link"], st["kpis"][0]["delta"], st["kpis"][0]["unit"], st["kpis"][0]["source"]), ("", "", "", "s2"))
        with self.assertRaisesRegex(ValueError, "바뀐 항목이 없습니다"):
            report_agent.run_tool(st, "add_kpi", {"kpi_id": "k1", "agg": "avg"}, None)
        with self.assertRaisesRegex(ValueError, "함께 줄 수 없습니다"):
            report_agent.run_tool(st, "add_kpi", {"column": "매출", "value": 640, "label": "x"}, None)
        # 자동 이름은 집계 · 컬럼을 따라 다시 붙고, 비율 컬럼으로 바꾸면 집계는 평균으로 / auto names follow the column and aggregation; a rate column re-picks avg
        st = state_with([{"source": "s1", "x": "월", "y": ["매출"]}], cols=COLS + ["달성률"], rows=[r + [80] for r in ROWS])
        report_agent.run_tool(st, "add_kpi", {"column": "매출"}, None)
        report_agent.run_tool(st, "add_kpi", {"kpi_id": "k1", "agg": "avg"}, None)
        self.assertEqual((st["kpis"][0]["label"], st["kpis"][0]["agg"]), ("매출 평균", "avg"))
        report_agent.run_tool(st, "add_kpi", {"kpi_id": "k1", "column": "달성률"}, None)
        self.assertEqual((st["kpis"][0]["label"], st["kpis"][0]["agg"], st["kpis"][0]["col"]), ("달성률 평균", "avg", "달성률"))
        report_agent.run_tool(st, "add_kpi", {"kpi_id": "k1", "label": "달성률"}, None)
        report_agent.run_tool(st, "add_kpi", {"kpi_id": "k1", "agg": "max"}, None)                               # 사용자가 지은 이름은 지킨다 / a user-given name stays
        self.assertEqual((st["kpis"][0]["label"], st["kpis"][0]["agg"]), ("달성률", "max"))
        report_agent.run_tool(st, "add_kpi", {"column": "검사수", "label": "검사"}, None)
        with self.assertRaisesRegex(ValueError, "같은 이름"):
            report_agent.run_tool(st, "add_kpi", {"kpi_id": "k2", "label": "달성률"}, None)
        self.assertEqual(rd.norm_kpi({"source": "s1", "col": "share"}, {s["id"]: s for s in state_with(cols=["지점", "share"], rows=[["a", 0.5]])["sources"]}, [], set())["agg"], "avg")

    def test_put_kpi_adds_edits_in_place_merges_for_tools_and_refuses_rate_sums_and_the_cap(self):
        st = state_with([{"source": "s1", "x": "월", "y": ["매출"]}], cols=COLS + ["달성률"], rows=[r + [80] for r in ROWS])
        k = rd.put_kpi(st, {"label": "총 매출", "source": "s1", "col": "매출", "agg": "sum", "link": "c1", "delta": "prev", "unit": "원"})
        self.assertEqual((k["id"], k["delta"], rd.kpi_value(k, st)["value"]), ("k1", "prev", 640.0))
        with self.assertRaisesRegex(ValueError, "비율"):
            rd.put_kpi(st, {"source": "s1", "col": "달성률", "agg": "sum"})
        rd.put_kpi(st, {"label": "목표", "value": "1,000", "unit": "원"})
        self.assertEqual([(x["id"], x["source"], x.get("value")) for x in st["kpis"]], [("k1", "s1", None), ("k2", "", 1000.0)])
        before = [dict(x) for x in st["kpis"]]                                                 # ops 의 되돌리기 스냅샷처럼 / like the ops undo snapshot
        rd.put_kpi(st, {"label": "평균 매출", "source": "s1", "col": "매출", "agg": "avg"}, "k1")      # 제자리 수정, 전체 설정 / in place, whole spec
        self.assertEqual((st["kpis"][0]["id"], st["kpis"][0]["agg"], st["kpis"][0]["link"], before[0]["agg"]), ("k1", "avg", "", "sum"))
        rd.put_kpi(st, {"label": "평균 매출(강남)", "link": "c1"}, "k1", merge=True)                    # 도구: 적은 항목만 / tools: given fields only
        self.assertEqual((st["kpis"][0]["label"], st["kpis"][0]["agg"], st["kpis"][0]["link"]), ("평균 매출(강남)", "avg", "c1"))
        rd.put_kpi(st, {"label": "목표 2026"}, "k2", merge=True)                                       # 적은 항목만 — 숫자는 지킨다 / given fields only; the number stays
        self.assertEqual((st["kpis"][1]["label"], st["kpis"][1]["value"], st["kpis"][1]["source"]), ("목표 2026", 1000.0, ""))
        rd.put_kpi(st, {"source": "s1", "col": "매출"}, "k2", merge=True)                               # 컬럼을 말하면 데이터 카드로 / naming a column makes it computed
        self.assertEqual((st["kpis"][1]["label"], st["kpis"][1].get("value"), st["kpis"][1]["source"], st["kpis"][1]["col"]), ("목표 2026", None, "s1", "매출"))
        rd.put_kpi(st, {"value": 1000}, "k2", merge=True)                                               # 숫자를 말하면 다시 고정 숫자 카드 / a number makes it fixed again
        self.assertEqual((st["kpis"][1]["value"], st["kpis"][1]["source"]), (1000.0, ""))
        with self.assertRaisesRegex(ValueError, "없습니다"):
            rd.put_kpi(st, {"label": "x", "value": 1}, "k9")
        for i in range(rd.MAX_KPIS - 2):
            rd.put_kpi(st, {"label": f"n{i}", "value": i})
        with self.assertRaisesRegex(ValueError, "개까지"):
            rd.put_kpi(st, {"label": "넘침", "value": 1})
        self.assertEqual(len(rd.normalize_state(st)["kpis"]), rd.MAX_KPIS)


TREND_ROWS = [[f"2025-{m:02d}", v] for m, v in enumerate([755, 779, 802, 826, 858, 887, 920, 966], start=1)]


def trend_state(trend, rows=TREND_ROWS, **over):
    return state_with([{"source": "s1", "type": "line", "x": "월", "y": ["매출"], "trend": trend, **over}], ["월", "매출"], rows)


class TrendTests(unittest.TestCase):
    def test_next_labels_continue_the_shape_of_the_last_label(self):
        nx = rd.next_period_labels
        self.assertEqual(nx(["2025-11", "2025-12"], "month", 2), ["2026-01", "2026-02"])
        self.assertEqual(nx(["2025.9"], "month", 2), ["2025.10", "2025.11"])
        self.assertEqual(nx(["2025년 12월"], "month", 1), ["2026년 1월"])
        self.assertEqual(nx(["11월", "12월"], "month", 2), ["1월", "2월"])
        self.assertEqual(nx(["202511", "202512"], "month", 1), ["202601"])
        self.assertEqual(nx(["2025 Q3", "2025 Q4"], "quarter", 2), ["2026 Q1", "2026 Q2"])
        self.assertEqual(nx(["3분기"], "quarter", 2), ["4분기", "1분기"])
        self.assertEqual(nx(["2025", "2026"], "year", 2), ["2027", "2028"])
        self.assertEqual(nx(["2026년"], "year", 1), ["2027년"])
        self.assertEqual(nx(["W08", "W09"], "week", 2), ["W10", "W11"])
        self.assertEqual(nx(["2026-02-14", "2026-02-21", "2026-02-28"], "date", 2), ["2026-03-07", "2026-03-14"])   # 점 사이 간격(7일)만큼 / by the gap between points
        self.assertEqual(nx(["20261230", "20261231"], "date", 1), ["20270101"])
        self.assertEqual(nx(["강남점"], "month", 2), [])

    def test_the_trend_line_and_forecast_are_computed_from_the_visible_values_only(self):
        st = trend_state({"line": True, "forecast": 3})
        c = st["charts"][0]
        self.assertEqual((c["trend"], c["sort"]), ({"line": True, "forecast": 3, "method": "linear", "series": ""}, {"by": "x", "dir": "asc"}))
        tr = comp(st)["trend"]
        self.assertEqual((tr["slope"], tr["points"], tr["values"][0], tr["values"][-1]), (29.392857, 8, 746.25, 952.0))
        fc = tr["forecast"]                                                                   # 점 8개 → 예측은 2개까지(1/3) / eight points allow two
        self.assertEqual((fc["labels"], fc["values"], fc["method"]), (["2025-09", "2025-10"], [981.392857, 1010.785714], "linear"))
        self.assertAlmostEqual(fc["high"][0] - fc["values"][0], 17.192884, places=4)          # ±2σ
        self.assertGreater(fc["high"][1] - fc["low"][1], fc["high"][0] - fc["low"][0])        # 멀수록 넓어진다 / wider with distance
        short = comp(trend_state({"line": True, "forecast": 3}, TREND_ROWS[:5]))["trend"]
        self.assertNotIn("forecast", short)                                                   # 점이 6개 미만이면 예측하지 않는다 / no forecast below six points
        self.assertNotIn("trend", comp(trend_state({"line": True}, TREND_ROWS[:2])))

    def test_seasonal_forecast_repeats_last_year_times_the_recent_growth(self):
        rows = [[f"{y}-{m:02d}", (100 + m * 10) * (1 if y == 2024 else 1.5)] for y in (2024, 2025) for m in range(1, 13)]
        fc = comp(trend_state({"forecast": 2, "method": "seasonal"}, rows))["trend"]["forecast"]
        self.assertEqual((fc["method"], fc["labels"], fc["values"]), ("seasonal", ["2026-01", "2026-02"], [247.5, 270.0]))   # 2025-01 165 × 1.5
        self.assertEqual(comp(trend_state({"forecast": 2, "method": "seasonal"}))["trend"]["forecast"]["method"], "linear")   # 2년치가 안 되면 직선 / falls back

    def test_trend_needs_a_period_axis_and_a_vertical_chart(self):
        srcs = {s["id"]: s for s in state_with()["sources"]}
        with self.assertRaises(ValueError) as cm:
            rd.norm_chart({"source": "s1", "x": "지점", "y": ["매출"], "trend": {"line": True}}, srcs, set(), strict=True)
        self.assertIn("기간 컬럼: 월", str(cm.exception))
        with self.assertRaises(ValueError):
            rd.norm_chart({"source": "s1", "type": "hbar", "x": "월", "y": ["매출"], "trend": {"forecast": 2}}, srcs, set(), strict=True)
        self.assertNotIn("trend", rd.norm_chart({"source": "s1", "x": "지점", "y": ["매출"], "trend": {"line": True}}, srcs, set()))
        st = state_with([{"source": "s1", "type": "bar", "x": "월", "y": ["매출"]}])
        note, say = report_agent.run_tool(st, "set_trend", {"chart_id": "c1", "line": True, "forecast": 2}, None)
        self.assertIn("예측은 점이 6개 이상일 때만", say)                                     # 4개월치라 선만 / four months: the line only
        self.assertEqual(st["charts"][0]["trend"]["forecast"], 2)
        report_agent.run_tool(st, "set_trend", {"chart_id": "c1", "line": False, "forecast": 0}, None)
        self.assertNotIn("trend", st["charts"][0])


class RangeFilterAndThemeTests(unittest.TestCase):
    def test_the_filter_shape_follows_the_column_kind(self):
        st = state_with([{"source": "s1", "x": "지점", "y": ["매출"], "filters": [
            {"col": "월", "last_n": 2}, {"col": "매출", "min": 50, "max": "120"}, {"col": "지점", "last_n": 2, "min": 1, "selected": ["강남점"]}]}])
        f = st["charts"][0]["filters"]
        self.assertEqual([(x["col"], x.get("range"), x["selected"]) for x in f],
                         [("월", {"last": 2}, []), ("매출", {"min": 50.0, "max": 120.0}, []), ("지점", None, ["강남점"])])
        src = st["sources"][0]
        self.assertEqual(sorted({r[1] for r in rd.filtered_rows(src, f[:1])}), ["10월", "3월"])                # 최근 2개 = 3월·10월(데이터 기준) / the last two periods of the data
        self.assertEqual([r[2] for r in rd.filtered_rows(src, f[1:2])], [100, 50, 120, 90, 60])
        self.assertEqual([r[2] for r in rd.filtered_rows(src, f)], [90])                                        # 셋 다: 강남점 · 3월/10월 · 50~120
        rng = rd.norm_filter({"col": "월", "range": {"from": "2월", "to": "없는달"}}, src, set())
        self.assertEqual(rng["range"], {"from": "2월", "to": ""})
        self.assertEqual(sorted({r[1] for r in rd.filtered_rows(src, [rng])}), ["10월", "2월", "3월"])
        self.assertEqual(len(rd.filtered_rows(src, [{"col": "월", "range": {"from": "", "to": ""}, "selected": []}])), len(ROWS))
        self.assertEqual(rd.kpi_value({"source": "s1", "col": "매출", "agg": "sum", "link": "c1", "delta": ""}, st)["value"], 90.0)

    def test_the_agent_sets_ranges_and_is_told_when_a_column_cannot_take_one(self):
        st = state_with([{"source": "s1", "x": "지점", "y": ["매출"]}])
        note, say = report_agent.run_tool(st, "add_filter", {"chart_id": "c1", "column": "월", "last_n": 3}, None)
        self.assertEqual((st["charts"][0]["filters"][0]["range"], "최근 3개만" in say), ({"last": 3}, True))
        report_agent.run_tool(st, "add_filter", {"chart_id": "c1", "column": "월", "selected": ["1월"]}, None)   # 같은 컬럼에 다시: 범위 → 목록
        self.assertEqual((st["charts"][0]["filters"][0].get("range"), st["charts"][0]["filters"][0]["selected"]), (None, ["1월"]))
        with self.assertRaises(ValueError) as cm:
            report_agent.run_tool(st, "add_filter", {"chart_id": "c1", "column": "지점", "last_n": 3}, None)
        self.assertIn("범위를 걸 수 없습니다", str(cm.exception))
        self.assertIn("월=1월", report_agent.describe_state(st))

    def test_a_theme_colours_every_chart_and_the_ones_made_later(self):
        st = state_with([{"source": "s1", "x": "지점", "y": ["매출"], "style": {"palette": "ocean", "labels": True}}])
        with self.assertRaises(ValueError):
            report_agent.run_tool(st, "set_theme", {"brand_color": "청록"}, None)
        report_agent.run_tool(st, "set_theme", {"brand_color": "#0f6e56", "rounded": False}, None)
        self.assertEqual(st["theme"], {"brand": "#0F6E56", "second": "", "rounded": False})
        self.assertEqual((st["charts"][0]["style"]["palette"], st["charts"][0]["style"]["rounded"], st["charts"][0]["style"]["labels"]), ("theme", False, True))
        report_agent.run_tool(st, "create_chart", {"source_id": "s1", "type": "line", "title": "추이", "x": "월", "y": ["매출"]}, None)
        self.assertEqual((st["charts"][1]["style"]["palette"], st["charts"][1]["style"]["rounded"]), ("theme", False))
        self.assertEqual(rd.normalize_state(st)["theme"], st["theme"])
        self.assertEqual(rd.dashboard_data(rd.normalize_state(st))["theme"]["brand"], "#0F6E56")
        self.assertIn("테마: 대표 색 #0F6E56", report_agent.describe_state(st))
        report_agent.run_tool(st, "set_theme", {"clear": True}, None)
        self.assertEqual(("theme" in st, [c["style"]["palette"] for c in st["charts"]]), (False, ["indigo", "indigo"]))
        self.assertIsNone(rd.norm_theme({"brand": "red"}))


class RateGuardTests(unittest.TestCase):
    """비율을 더하는 설정은 도구 호출에서 막는다(2026-10-01, 받은 드릴다운 코드의 계약 DR03 과 같은 뜻) — 드릴다운 · 필터로 단계마다 다시
    계산하면 비율의 합이 되어 오류 없이 틀린 수가 나온다. 저장분은 그대로 읽는다.
    Tool calls refuse rates that would be added up (2026-10-01, the reviewed drill-down code's DR03); saved dashboards still load."""
    COLS = ["지점", "월", "매출", "목표", "달성률"]
    ROWS = [["강남점", "1월", 100, 120, 83.3], ["광주점", "1월", 50, 40, 125.0], ["강남점", "2월", 120, 100, 120.0]]

    def test_tools_refuse_summed_rates_and_rate_pies_while_saved_charts_still_load(self):
        st = state_with(cols=self.COLS, rows=self.ROWS)
        with self.assertRaises(ValueError) as e:
            report_agent.run_tool(st, "create_chart", {"source_id": "s1", "x": "지점", "y": [{"column": "달성률", "agg": "sum"}]}, None)
        self.assertIn("ratio_pct", str(e.exception))
        with self.assertRaises(ValueError):   # 기본 집계(avg)라도 원·도넛의 조각 크기로는 뜻이 없다 / a rate is no slice size, even averaged
            report_agent.run_tool(st, "create_chart", {"source_id": "s1", "type": "donut", "x": "지점", "y": [{"column": "달성률"}]}, None)
        self.assertEqual((st["charts"], len(st["sources"])), ([], 1))
        report_agent.run_tool(st, "create_chart", {"source_id": "s1", "x": "지점", "y": [{"column": "달성률"}]}, None)
        self.assertEqual(st["charts"][0]["y"][0]["agg"], "avg")
        report_agent.run_tool(st, "add_calculation", {"chart_id": "c1", "calc": "ratio_pct", "column": "매출", "agg": "sum",
                                                      "by_column": "목표", "by_agg": "sum"}, None)   # 분자 합 ÷ 분모 합 / Σ numerator ÷ Σ denominator
        made = comp(st)["series"][-1]
        self.assertEqual(made["values"], [round(220 / 220 * 100, 6), 125.0])   # 강남점 (100+120)/(120+100), 광주점 50/40
        with self.assertRaises(ValueError):
            report_agent.run_tool(st, "add_kpi", {"source_id": "s1", "column": "달성률", "agg": "sum", "label": "달성률 합"}, None)
        report_agent.run_tool(st, "add_kpi", {"source_id": "s1", "column": "달성률", "agg": "avg", "label": "평균 달성률"}, None)
        # 저장분은 도구가 아니라 읽기라 그대로 — 손대지 않은 계열 때문에 제목 수정이 막히지 않고, 원으로 바꿀 때만 다시 본다
        # A saved chart loads as is; a title change is not blocked by the untouched series, only a switch to a pie is checked
        legacy = state_with([{"source": "s1", "x": "지점", "y": [{"col": "달성률", "agg": "sum"}]}], cols=self.COLS, rows=self.ROWS)
        self.assertEqual(legacy["charts"][0]["y"][0]["agg"], "sum")
        report_agent.run_tool(legacy, "update_chart", {"chart_id": "c1", "title": "지점별 달성률"}, None)
        self.assertEqual(legacy["charts"][0]["title"], "지점별 달성률")
        with self.assertRaises(ValueError):
            report_agent.run_tool(legacy, "update_chart", {"chart_id": "c1", "type": "pie"}, None)
        with self.assertRaises(ValueError):   # 새로 붙이는 계열은 본다 / a series added now is checked
            report_agent.run_tool(st, "update_chart", {"chart_id": "c1", "add_y": [{"column": "달성률", "agg": "sum", "name": "합"}]}, None)
        # 이름 중간의 '률'(법률자문비)이나 낱말 속 rate(corporate_sales)는 비율이 아니다 — 합계를 막지 않는다
        # '률' inside a name (legal fees) or 'rate' inside a word (corporate_sales) is no rate: sums stay allowed
        costs = state_with(cols=["지점", "법률자문비", "corporate_sales"], rows=[["강남점", 10, 5], ["광주점", 20, 7]])
        report_agent.run_tool(costs, "create_chart", {"source_id": "s1", "x": "지점", "y": [{"column": "법률자문비", "agg": "sum"},
                                                                                          {"column": "corporate_sales", "agg": "sum"}]}, None)
        self.assertEqual([y["agg"] for y in costs["charts"][0]["y"]], ["sum", "sum"])


class ApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        boards.init_boards()
        rd.init_report_dash()
        app = FastAPI()
        app.include_router(reports_api.router)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.client.aclose)
        self.stack.enter_context(patch.object(reports_api, "_eff", return_value=None))

    async def test_the_chip_removes_a_highlight_and_the_turn_carries_the_drilled_view(self):
        s = (await self.client.post("/api/reports/dash", json={"acting_user_id": "7", "chat_id": "c_x",
                                                                "sources": [{"columns": COLS, "rows": ROWS, "sql": "SELECT 1"}]})).json()["session"]
        first = calls(("create_chart", {"source_id": "s1", "type": "bar", "title": "월별 매출", "x": "월", "y": [{"column": "매출"}]}),
                      ("add_highlight", {"chart_id": "c1", "kind": "top", "n": 1}))
        with patch("app.llm.generate_calls", side_effect=[first, calls(text="만들었습니다.")]) as m:
            r = await self.client.post(f"/api/reports/dash/{s['id']}/turn", json={
                "acting_user_id": "7", "message": "월별 매출", "drill": {"chart": "c9", "path": [{"col": "월", "value": "1월"}]}})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("드릴다운 중", m.call_args_list[0].args[0])                            # 없는 차트의 드릴다운은 무시 / an unknown chart is ignored
        chart = r.json()["session"]["state"]["charts"][0]
        self.assertEqual([h["label"] for h in chart["highlights"]], ["상위 1"])
        r = await self.client.post(f"/api/reports/dash/{s['id']}/ops", json={
            "acting_user_id": "7", "ops": [{"op": "hl_remove", "chart": "c1", "id": chart["highlights"][0]["id"]}]})
        self.assertNotIn("highlights", r.json()["session"]["state"]["charts"][0])
        self.assertEqual(r.json()["session"]["state"]["sources"][0]["periods"], {"월": "month"})


    async def test_range_pick_brand_colour_and_trend_chip_work_without_the_llm(self):
        s = (await self.client.post("/api/reports/dash", json={"acting_user_id": "7", "chat_id": "c_z",
                                                                "sources": [{"columns": COLS, "rows": ROWS, "sql": "SELECT 1"}]})).json()["session"]
        first = calls(("create_chart", {"source_id": "s1", "type": "bar", "title": "월별 매출", "x": "월", "y": [{"column": "매출"}]}),
                      ("add_filter", {"chart_id": "c1", "column": "월"}), ("set_trend", {"chart_id": "c1", "line": True}))
        with patch("app.llm.generate_calls", side_effect=[first, calls(text="만들었습니다.")]):
            st = (await self.client.post(f"/api/reports/dash/{s['id']}/turn", json={"acting_user_id": "7", "message": "월별 매출"})).json()["session"]["state"]
        fid = st["charts"][0]["filters"][0]["id"]

        async def ops(*items):
            return (await self.client.post(f"/api/reports/dash/{s['id']}/ops", json={"acting_user_id": "7", "ops": list(items)})).json()["session"]

        st = (await ops({"op": "filter_select", "chart": "c1", "id": fid, "selected": [], "range": {"last": 2, "min": 5}}))["state"]
        self.assertEqual(st["charts"][0]["filters"][0]["range"], {"last": 2})                  # 컬럼 종류에 맞는 것만 남는다 / only what fits the column kind
        st = (await ops({"op": "filter_select", "chart": "c1", "id": fid, "selected": ["1월"]}))["state"]
        self.assertEqual((st["charts"][0]["filters"][0].get("range"), st["charts"][0]["filters"][0]["selected"]), (None, ["1월"]))
        ses = await ops({"op": "theme_set", "brand": "#1D4ED8"}, {"op": "trend_clear", "id": "c1"})
        self.assertEqual((ses["state"]["theme"]["brand"], ses["state"]["charts"][0]["style"]["palette"], "trend" in ses["state"]["charts"][0], ses["can_undo"]),
                         ("#1D4ED8", "theme", False, True))
        back = (await self.client.post(f"/api/reports/dash/{s['id']}/undo", json={"acting_user_id": "7"})).json()["session"]["state"]
        self.assertEqual(("theme" in back, back["charts"][0]["style"]["palette"]), (False, "indigo"))
        self.assertEqual((await self.client.post(f"/api/reports/dash/{s['id']}/ops", json={"acting_user_id": "7", "ops": [{"op": "theme_set", "brand": "파랑"}]})).status_code, 422)

    async def test_buttons_duplicate_annotate_and_trim_the_summary_row_without_the_llm(self):
        s = (await self.client.post("/api/reports/dash", json={"acting_user_id": "7", "chat_id": "c_y",
                                                                "sources": [{"columns": COLS, "rows": ROWS, "sql": "SELECT 1"}]})).json()["session"]
        with patch("app.llm.generate_calls", side_effect=RuntimeError("down")):
            auto = (await self.client.post(f"/api/reports/dash/{s['id']}/auto", json={"acting_user_id": "7"})).json()["session"]
        self.assertNotIn("kpis", auto["state"])                                               # 첫 화면에는 KPI 카드가 없다(2026-10-12) / no KPI cards at first

        async def ops(*items):
            return await self.client.post(f"/api/reports/dash/{s['id']}/ops", json={"acting_user_id": "7", "ops": list(items)})

        st = (await ops({"op": "kpi_auto"})).json()["session"]                                # [추천 채우기] / [Fill suggestions]
        self.assertEqual(([k["label"] for k in st["state"]["kpis"]], st["can_undo"], st["dirty"]), (["매출 합계", "불량수 합계", "검사수 합계"], True, True))
        self.assertEqual((await ops({"op": "kpi_auto"})).status_code, 422)                    # 같은 컬럼은 다시 추천하지 않는다 / nothing new to suggest
        st = (await ops({"op": "chart_duplicate", "id": "c1"})).json()["session"]
        self.assertEqual([(c["id"], c.get("compare")) for c in st["state"]["charts"]], [("c1", "g1"), ("c2", "g1")])
        self.assertEqual([len(x["rows"]) for x in st["state"]["sources"]], [len(ROWS), 0])     # 복제본의 행은 싣지 않는다 / clone rows are not sent
        self.assertTrue(st["can_undo"] and st["dirty"] and not st["saved"])   # 저장 전 — 작업본만 바뀐다(2026-09-22 명시 저장) / unsaved: only the working copy changed
        st = (await ops({"op": "note_add", "chart": "c1", "x": "강남점", "text": "본점"}, {"op": "note_add", "chart": "c1", "x": "강남점", "text": "본점 이전"},
                        {"op": "kpi_remove", "id": "k2"}, {"op": "compare_clear", "id": "c2"})).json()["session"]["state"]
        self.assertEqual((st["charts"][0]["notes"], [k["id"] for k in st["kpis"]], [c.get("compare") for c in st["charts"]]),
                         ([{"id": "n1", "x": "강남점", "text": "본점 이전"}], ["k1", "k3"], [None, None]))
        self.assertEqual((await ops({"op": "note_add", "chart": "c1", "x": "강남점", "text": "  "})).status_code, 422)
        st = (await ops({"op": "note_remove", "chart": "c1", "id": "n1"})).json()["session"]["state"]
        self.assertNotIn("notes", st["charts"][0])
        # KPI 카드 편집(2026-10-12): 추가 · 제자리 수정(직접 적은 숫자로) · 거절 · 상한 / the KPI card editor: add, edit in place (to a typed number), refusals, the cap
        st = (await ops({"op": "kpi_add", "kpi": {"label": "평균 매출", "source": "s1", "col": "매출", "agg": "avg", "unit": "원", "link": "c1", "delta": "prev", "note": "강남점"}},
                        {"op": "kpi_set", "id": "k1", "kpi": {"label": "목표", "value": "1,200", "unit": "원", "note": ""}})).json()["session"]["state"]
        self.assertEqual([(k["id"], k["label"], k.get("value"), k["agg"], k["link"], k["delta"], k["note"]) for k in st["kpis"]],
                         [("k1", "목표", 1200.0, "", "", "", ""), ("k3", "검사수 합계", None, "sum", "c1", "", ""), ("k2", "평균 매출", None, "avg", "c1", "prev", "강남점")])
        for bad in ({"op": "kpi_set", "id": "k9", "kpi": {"label": "x", "value": 1}}, {"op": "kpi_add", "kpi": {"label": "이름만", "value": "abc"}},
                    {"op": "kpi_add", "kpi": {"value": 3}}, {"op": "kpi_add", "kpi": {"source": "s1", "col": "없음"}},
                    {"op": "kpi_set", "kpi": {"label": "id 없음", "value": 1}}, {"op": "kpi_remove", "id": "k9"},                  # 리뷰 반영 / review fixes
                    {"op": "kpi_add", "kpi": {"label": "목표", "value": 2}}):                                                     # 같은 이름 / a clashing name
            self.assertEqual((await ops(bad)).status_code, 422, bad)
        for i in range(rd.MAX_KPIS - 3):
            self.assertEqual((await ops({"op": "kpi_add", "kpi": {"label": f"c{i}", "value": i}})).status_code, 200)
        self.assertEqual((await ops({"op": "kpi_add", "kpi": {"label": "넘침", "value": 9}})).status_code, 422)
        self.assertEqual(len(rd.get_session(s["id"])["state"]["kpis"]), rd.MAX_KPIS)
        # 다시 조회는 원본만 — 복제본은 따라온다 / refresh re-runs roots only; clones follow
        with patch("app.analytics.refresh_csv_views"), patch("app.analytics.run_select", return_value=(COLS, ROWS[:2])) as run:
            r = (await self.client.post(f"/api/reports/dash/{s['id']}/refresh", json={"acting_user_id": "7"})).json()
        self.assertEqual((run.call_count, [x["id"] for x in r["refreshed"]]), (1, ["s1"]))
        saved = rd.get_session(s["id"])["state"]
        self.assertEqual([len(x["rows"]) for x in saved["sources"]], [2, 2])
        # 되돌리기는 한 단계씩 — 카드 편집도 되돌린다, 끝까지 가면 복제 전 · 카드 없음 / undo is one step at a time, card edits included; all the way back: no duplicate, no cards
        back = (await self.client.post(f"/api/reports/dash/{s['id']}/undo", json={"acting_user_id": "7"})).json()["session"]
        self.assertEqual((len(back["state"]["kpis"]), back["can_undo"]), (rd.MAX_KPIS - 1, True))
        for _ in range(rd.MAX_UNDO):
            back = (await self.client.post(f"/api/reports/dash/{s['id']}/undo", json={"acting_user_id": "7"})).json()["session"]
            if not back["can_undo"]:
                break
        self.assertEqual(([c["id"] for c in back["state"]["charts"]], back["state"].get("kpis") or []), (["c1"], []))

    async def test_fill_suggestions_skip_a_clashing_pick_and_average_rate_like_columns(self):
        # 리뷰 반영(2026-10-12): 'share' 같은 컬럼은 합계 대신 평균, 이름이 겹치는 추천은 건너뛴다 / review fix: 'share' averages, a clashing pick is skipped
        s = (await self.client.post("/api/reports/dash", json={"acting_user_id": "7", "chat_id": "c_s", "sources": [{"columns": ["지점", "월", "share", "매출"],
                                                                "rows": [[r[0], r[1], 0.5, r[2]] for r in ROWS], "sql": "SELECT 1"}]})).json()["session"]
        with patch("app.llm.generate_calls", side_effect=RuntimeError("down")):
            await self.client.post(f"/api/reports/dash/{s['id']}/auto", json={"acting_user_id": "7"})
        r = await self.client.post(f"/api/reports/dash/{s['id']}/ops", json={"acting_user_id": "7", "ops": [{"op": "kpi_add", "kpi": {"label": "매출 합계", "value": 1}}, {"op": "kpi_auto"}]})
        self.assertEqual([(k["label"], k["agg"]) for k in r.json()["session"]["state"]["kpis"]], [("매출 합계", ""), ("share 평균", "avg")])
        self.assertEqual((await self.client.post(f"/api/reports/dash/{s['id']}/ops", json={"acting_user_id": "7", "ops": [{"op": "kpi_auto"}]})).status_code, 422)


if __name__ == "__main__":
    unittest.main()
