# -*- coding: utf-8 -*-
"""리포트 에이전트 대시보드(2026-09-18) — 상태 정규화·집계·옛 모양 변환·세션 저장·도구 루프·API. 실제 LLM·real DB 없음(격리 DB + 패치).

Report-agent dashboards (2026-09-18) — state normalization, aggregation, legacy conversion, the session store, the tool
loop and the API. No real LLM or real DB (isolated DB + patches)."""
import json
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from db_fixture import isolate_db
from app import access, boards, boards_api, db, report_agent, report_dash as rd, reports, reports_api

COLS = ["제품", "연도", "불량률", "검사수"]
ROWS = [["FG-CREAM-01", 2025, 0.52, 100], ["FG-CREAM-01", 2026, 0.0, 140],
        ["FG-MASK-03", 2025, 0.23, 80], ["FG-MASK-03", 2026, 0.26, 90],
        ["BULK-TONER-01", 2025, 0.0, 60], ["BULK-TONER-01", 2026, 0.0, 70]]
SQL = "SELECT * FROM (SELECT item, yr, rate, n FROM quality) AS _q LIMIT 200"


def state_with(charts=None, filters=None):
    return rd.normalize_state({"title": "품질", "sources": [{"columns": COLS, "rows": ROWS, "sql": SQL}],
                               "charts": charts or [], "filters": filters or []})


class NormalizeTests(unittest.TestCase):
    def test_source_gets_name_types_and_caps(self):
        s = state_with()["sources"][0]
        self.assertEqual((s["id"], s["name"]), ("s1", "Source 1"))
        self.assertEqual(s["types"], {"제품": "text", "연도": "number", "불량률": "number", "검사수": "number"})
        self.assertEqual(s["origin"]["kind"], "chat")
        big = rd.normalize_state({"sources": [{"columns": ["a"], "rows": [[i] for i in range(rd.MAX_SOURCE_ROWS + 50)]}]})
        self.assertEqual(len(big["sources"][0]["rows"]), rd.MAX_SOURCE_ROWS)

    def test_chart_resolves_columns_loosely_and_names_what_is_missing(self):
        st = state_with([{"source": "s1", "type": "bar", "x": " 제품 ", "y": [{"column": "불량률", "agg": "avg"}]}])
        c = st["charts"][0]
        self.assertEqual((c["id"], c["x"], c["y"][0]["col"], c["y"][0]["agg"], c["size"]), ("c1", "제품", "불량률", "avg", "half"))
        with self.assertRaises(ValueError) as cm:
            rd.norm_chart({"source": "s1", "x": "없는컬럼"}, {s["id"]: s for s in st["sources"]}, set())
        self.assertIn("쓸 수 있는 컬럼", str(cm.exception))
        with self.assertRaises(ValueError):
            rd.norm_chart({"source": "s9"}, {s["id"]: s for s in st["sources"]}, set())

    def test_text_value_column_can_only_be_counted_and_invalid_pieces_are_dropped(self):
        st = state_with([{"source": "s1", "x": "연도", "y": [{"column": "제품", "agg": "sum"}],
                          "filters": [{"col": "없음"}, {"col": " 연도 ", "selected": [2026, 2026]}, {"col": "연도"}]},
                         {"source": "s1", "x": "없음"}])
        self.assertEqual(st["charts"][0]["y"][0]["agg"], "count")
        self.assertEqual(len(st["charts"]), 1)              # 깨진 차트는 버린다 / the broken chart is dropped
        # 필터는 차트의 것 — 없는 컬럼·같은 컬럼 중복은 버린다 / filters belong to the chart; unknown and duplicate columns are dropped
        self.assertEqual(st["charts"][0]["filters"], [{"id": "f1", "col": "연도", "label": "연도", "selected": ["2026"]}])
        self.assertNotIn("filters", st)

    def test_the_short_lived_dashboard_level_filters_move_into_the_charts_of_their_sources(self):
        st = rd.normalize_state({"sources": [{"columns": COLS, "rows": ROWS}, {"columns": ["연도", "매출"], "rows": [[2026, 1]]}],
                                 "charts": [{"source": "s1", "x": "제품"}, {"source": "s2", "x": "연도"}, {"source": "s1", "x": "연도"}],
                                 "filters": [{"col": "연도", "sources": ["s1"], "selected": ["2026"]}, {"col": "제품", "label": "품목"}]})
        self.assertEqual([[(f["col"], f["label"], f["selected"]) for f in c["filters"]] for c in st["charts"]],
                         [[("연도", "연도", ["2026"]), ("제품", "품목", [])], [], [("연도", "연도", ["2026"]), ("제품", "품목", [])]])
        # 같은 Source 를 같이 쓰던 셋째 차트는 복제된 Source 3 으로 나뉜다(리포트 하나 = Source 하나) — 필터는 데이터 계보로 따라간다
        # The third chart shared s1, so it moves to the cloned Source 3 (one report = one source); filters follow the data lineage
        self.assertEqual([(c["id"], c["source"]) for c in st["charts"]], [("c1", "s1"), ("c2", "s2"), ("c3", "s3")])
        self.assertEqual((st["sources"][2]["name"], st["sources"][2]["origin"]["clone_of"], st["sources"][2]["rows"] == st["sources"][0]["rows"]),
                         ("Source 3", "s1", True))

    def test_a_new_report_takes_a_free_source_of_the_same_data_before_cloning_and_shares_at_the_cap(self):
        st = state_with([{"source": "s1", "x": "제품"}])
        sid_, made = rd.source_for_new_chart(st, "s1")
        self.assertEqual((sid_, made, st["sources"][1]["origin"]["clone_of"]), ("s2", True, "s1"))
        self.assertEqual(rd.source_for_new_chart(st, "s1"), ("s2", False))      # 빈 복제본을 다시 쓴다 / the chartless clone is reused
        self.assertEqual(rd.source_for_new_chart(st, "s2"), ("s2", False))
        st["charts"].append(rd.norm_chart({"source": "s2", "x": "연도"}, {s["id"]: s for s in st["sources"]}, {"c1"}))
        self.assertEqual(rd.source_for_new_chart(st, "s2")[0], "s3")            # 복제본에서 또 만들어도 뿌리는 s1 / clones of clones keep the root
        self.assertEqual(st["sources"][2]["origin"]["clone_of"], "s1")
        with patch.object(rd, "MAX_SOURCES", 3):
            st["charts"].append(rd.norm_chart({"source": "s3", "x": "제품"}, {s["id"]: s for s in st["sources"]}, {"c1", "c2"}))
            self.assertEqual(rd.source_for_new_chart(st, "s1"), ("s1", False))  # 상한이면 같이 쓴다 / shared at the cap

    def test_pie_and_kpi_take_one_value_and_no_reference_lines(self):
        st = state_with([{"source": "s1", "type": "donut", "x": "제품", "y": ["불량률", "검사수"], "ref_lines": [{"value": 1}]},
                         {"source": "s1", "type": "kpi", "y": [{"column": "검사수", "agg": "sum"}]}])
        self.assertEqual([len(c["y"]) for c in st["charts"]], [1, 1])
        self.assertEqual(st["charts"][0]["ref_lines"], [])
        self.assertIsNone(st["charts"][1]["x"])


class ComputeTests(unittest.TestCase):
    def test_group_by_sum_sort_and_limit(self):
        st = state_with([{"source": "s1", "type": "bar", "x": "제품", "y": [{"column": "검사수", "agg": "sum"}],
                          "sort": {"by": "y"}, "limit": 2}])
        c = rd.compute(st["charts"][0], st["sources"][0])
        self.assertEqual(c["x"], ["FG-CREAM-01", "FG-MASK-03"])
        self.assertEqual(c["series"][0]["values"], [240.0, 170.0])

    def test_group_column_splits_series_and_filters_apply(self):
        st = state_with([{"source": "s1", "type": "bar", "x": "제품", "group": "연도", "y": [{"column": "불량률", "agg": "avg"}],
                          "filters": [{"col": "제품", "selected": ["FG-MASK-03", "BULK-TONER-01"]}]},
                         {"source": "s1", "type": "bar", "x": "제품", "y": [{"column": "검사수", "agg": "sum"}]}])
        self.assertEqual(len(rd.compute(st["charts"][1], st["sources"][0])["x"]), 3)   # 옆 차트는 그 필터와 무관하다 / the other chart is unaffected
        c = rd.compute(st["charts"][0], st["sources"][0])
        self.assertEqual(c["x"], ["FG-MASK-03", "BULK-TONER-01"])
        self.assertEqual([(s["name"], s["values"]) for s in c["series"]], [("2025", [0.23, 0.0]), ("2026", [0.26, 0.0])])
        self.assertEqual(c["rows"], 4)

    def test_reference_lines_fixed_and_stat_follow_the_filtered_values(self):
        st = state_with([{"source": "s1", "x": "제품", "y": [{"column": "검사수", "agg": "sum"}],
                          "ref_lines": [{"label": "목표", "value": 200}, {"label": "평균", "stat": "avg"}]}])
        refs = {r["label"]: r["value"] for r in rd.compute(st["charts"][0], st["sources"][0])["refs"]}
        self.assertEqual(refs, {"목표": 200.0, "평균": 180.0})
        st["charts"][0]["filters"] = [rd.norm_filter({"col": "제품", "selected": ["FG-MASK-03"]}, st["sources"][0], set())]
        refs = {r["label"]: r["value"] for r in rd.compute(st["charts"][0], st["sources"][0])["refs"]}
        self.assertEqual(refs["평균"], 170.0)

    def test_pie_folds_the_tail_into_others_and_kpi_is_one_number(self):
        rows = [[f"P{i}", 1, float(20 - i), 1] for i in range(12)]
        st = rd.normalize_state({"sources": [{"columns": COLS, "rows": rows}],
                                 "charts": [{"source": "s1", "type": "pie", "x": "제품", "y": ["불량률"]},
                                            {"source": "s1", "type": "kpi", "y": [{"column": "불량률", "agg": "max"}]}]})
        pie = rd.compute(st["charts"][0], st["sources"][0])
        self.assertEqual(len(pie["x"]), rd.MAX_PIE_SLICES)
        self.assertEqual(pie["x"][-1], rd.OTHERS_LABEL)
        self.assertEqual(pie["series"][0]["values"][-1], float(sum(20 - i for i in range(7, 12))))
        self.assertEqual(rd.compute(st["charts"][1], st["sources"][0])["series"][0]["values"], [20.0])

    def test_keys_match_javascript_string_rules(self):
        self.assertEqual([rd.key(v) for v in (2025.0, 0.5, True, None, "A")], ["2025", "0.5", "true", "", "A"])
        self.assertEqual([rd.num(v) for v in ("1,200", "12.5%", "", "x", True)], [1200.0, 12.5, None, None, None])


class LegacyTests(unittest.TestCase):
    CHART = {"x": ["1월", "2월"], "xLabel": "월", "yLabel": "매출",
             "series": [{"name": "매출", "type": "bar", "values": [1, 2], "yAxis": 0},
                        {"name": "이익률", "type": "line", "values": [10, 20], "yAxis": 1}]}

    def test_legacy_report_becomes_an_equivalent_state_with_the_saved_table_as_a_second_source(self):
        st = rd.state_of({"title": "월별", "chart": self.CHART, "insight": "2월이 높다",
                          "table": {"columns": ["월", "금액"], "rows": [["1월", 5]]}, "source": {"sql": "SELECT 1"}})
        self.assertEqual([s["origin"]["kind"] for s in st["sources"]], ["legacy", "legacy"])
        self.assertEqual(st["sources"][1]["sql"], "SELECT 1")
        again = rd.legacy_chart(st["charts"][0], st["sources"][0])
        self.assertEqual(again["x"], ["1월", "2월"])
        self.assertEqual([(s["name"], s["type"], s["values"], s["yAxis"]) for s in again["series"]],
                         [("매출", "bar", [1.0, 2.0], 0), ("이익률", "line", [10.0, 20.0], 1)])
        self.assertEqual(st["charts"][0]["insight"], "2월이 높다")

    def test_legacy_dashboard_tiles_each_get_a_source(self):
        st = rd.state_of({"type": "dashboard", "title": "묶음", "items": [{"title": "A", "chart": self.CHART},
                                                                         {"title": "B", "chart": self.CHART}]})
        self.assertEqual([c["source"] for c in st["charts"]], ["s1", "s2"])
        data = rd.dashboard_data(st)
        self.assertEqual((data["type"], data["v"], [t["cid"] for t in data["items"]]), ("dashboard", 2, ["c1", "c2"]))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        boards.init_boards()
        rd.init_report_dash()

    def test_nothing_reaches_the_library_until_saved_and_saving_again_updates_the_same_post(self):
        # 2026-09-22 사용자 결정: 자동 저장 대신 [저장] — 작업본은 세션에, 보관함 글은 save_to_library 에서만 / explicit save: the working copy lives in the session
        st = state_with([{"source": "s1", "x": "제품", "y": ["불량률"], "insight": "핵심"}])
        s = rd.create_session("7", st, rd.origin_key("chat1", [SQL]), {"chat_id": "chat1"})
        self.assertEqual((s["saved"], s["dirty"]), (False, False))
        st["title"] = "품질 대시보드"
        s = rd.save_state(s["id"], st, touch=True)
        self.assertEqual((s["saved"], s["dirty"], s["state"]["title"]), (False, True, "품질 대시보드"))   # 작업본만 바뀐다 / only the working copy changes
        self.assertEqual(boards.list_posts("me:7"), [])
        self.assertEqual(rd.find_by_origin("7", rd.origin_key("chat1", [SQL]))["id"], s["id"])
        saved = rd.save_to_library(s["id"])
        posts = boards.list_posts("me:7")
        self.assertEqual([(p["kind"], p["title"], p["summary"]) for p in posts], [("dashboard", "품질 대시보드", "핵심")])
        self.assertEqual((saved["post_id"], saved["saved"], saved["dirty"], bool(saved["saved_at"])), (posts[0]["id"], True, False, True))
        self.assertEqual(posts[0]["data"]["items"][0]["chart"]["x"][:1], ["FG-CREAM-01"])
        # 저장 뒤의 변경은 다시 저장할 때까지 글에 가지 않는다 / later changes stay off the post until the next save
        st["title"] = "바뀐 이름"
        s = rd.save_state(s["id"], st, touch=True)
        self.assertEqual((s["dirty"], boards.get_post(posts[0]["id"])["title"]), (True, "품질 대시보드"))
        again = rd.save_to_library(s["id"])
        self.assertEqual((again["post_id"], again["dirty"], boards.get_post(posts[0]["id"])["title"]), (posts[0]["id"], False, "바뀐 이름"))
        self.assertEqual(len(boards.list_posts("me:7")), 1)                # 같은 글을 갱신한다 / the same post is updated
        # 저장하지 않고 닫기: 글이 있으면 마지막 저장본으로 / discard: back to the last saved copy when a post exists
        st["title"] = "버릴 이름"
        rd.save_state(s["id"], st, touch=True)
        back = rd.discard_changes(s["id"])
        self.assertEqual((back["state"]["title"], back["dirty"], back["can_undo"]), ("바뀐 이름", False, False))
        # 한 번도 저장하지 않은 초안은 세션째 사라진다 / a never-saved draft is gone with its session
        d = rd.create_session("7", state_with())
        self.assertIsNone(rd.discard_changes(d["id"]))
        self.assertIsNone(rd.get_session(d["id"]))
        with self.assertRaises(ValueError):                                # 차트 없음 / no charts
            rd.save_to_library(rd.create_session("7", rd.normalize_state({"sources": []}))["id"])

    def test_messages_never_reach_the_post_and_the_session_dies_with_it(self):
        s = rd.create_session("7", state_with([{"source": "s1", "x": "제품"}]))
        rd.append_messages(s["id"], [{"role": "user", "text": "비밀 대화"}])
        rd.save_state(s["id"], s["state"], touch=True)
        saved = rd.save_to_library(s["id"])
        self.assertNotIn("비밀 대화", str(boards.get_post(saved["post_id"])))
        self.assertEqual(rd.get_session(s["id"])["messages"][0]["text"], "비밀 대화")
        self.assertIsNone(rd.get_session(s["id"], owner="9"))          # 남의 세션은 없다 / not another user's
        self.assertTrue(reports.delete_personal("7", saved["post_id"]))
        self.assertIsNone(rd.get_session(s["id"]))

    def test_old_untouched_drafts_are_purged(self):
        s = rd.create_session("7", state_with())
        self.assertEqual(rd.purge_drafts(hours=-1), 1)
        self.assertIsNone(rd.get_session(s["id"]))

    def test_versions_keep_the_latest_forty_and_numbering_continues(self):
        # 버전(2026-10-13): 상한을 넘으면 오래된 것부터 버리고 번호는 이어 간다, 스냅은 데이터 없이 / past the cap the oldest go, numbering continues, snaps carry no data
        st = state_with([{"source": "s1", "x": "제품", "y": ["불량률"]}])
        s = rd.create_session("7", st)
        self.assertEqual((s["versions"], rd.list_versions(s["id"]), rd.get_version(s["id"], 1)), ([], [], None))
        for i in range(1, rd.MAX_VERSIONS + 3):
            st["title"] = f"제목 {i}"
            self.assertEqual(rd.push_version(s["id"], st, f"변경 {i}"), i)
        vers = rd.list_versions(s["id"])
        self.assertEqual((rd.MAX_VERSIONS, [v["n"] for v in vers]), (40, list(range(3, 43))))   # 오래된 2개가 밀려났다 / the two oldest are gone
        self.assertEqual((set(vers[0]), vers[0]["label"], bool(vers[0]["at"])), ({"n", "label", "at"}, "변경 3", True))   # 가벼운 모양 / light
        self.assertIsNone(rd.get_version(s["id"], 2))
        v3 = rd.get_version(s["id"], 3)
        self.assertEqual((sorted(v3["snap"]), v3["snap"]["title"], v3["snap"]["charts"][0]["x"]),
                         (["charts", "kpis", "theme", "title"], "제목 3", "제품"))   # Source(행 데이터)는 빼고 / no sources
        self.assertEqual(rd.get_session(s["id"])["versions"], vers)
        self.assertEqual(rd.push_version(s["id"], st, "가" * 100), 43)          # 마지막 번호 + 1 / last number + 1
        vers = rd.list_versions(s["id"])
        self.assertEqual((len(vers), vers[0]["n"], vers[-1]["label"]), (40, 4, "가" * rd.MAX_VERSION_LABEL))   # 이름 40자 / label capped at 40
        self.assertEqual((rd.push_version(s["id"], st, "  "), rd.list_versions(s["id"])[-1]["label"]), (44, "변경"))
        self.assertEqual((rd.push_version("rd_none", st, "x"), rd.list_versions("rd_none"), rd.get_version("rd_none", 1)), (0, [], None))

    def test_continuing_from_a_version_takes_the_current_data_and_pushes_undo_only_when_it_changes(self):
        # [이 버전으로 이어가기]: 지금 상태와 같으면 되돌리기에 쌓지 않는다. 그래도 새 버전 · 안내 메시지(ver) · 저장하지 않은 변경
        # Continue from a version: no undo entry when nothing changes, still a new version, a notice (ver) and an unsaved change
        st = state_with([{"source": "s1", "x": "제품", "y": ["불량률"]}])
        s = rd.create_session("7", st)
        self.assertEqual(rd.push_version(s["id"], st, "대시보드 생성"), 1)
        same = rd.restore_version(s["id"], 1)
        self.assertEqual((same["can_undo"], same["dirty"], [(v["n"], v["label"]) for v in same["versions"]]),
                         (False, True, [(1, "대시보드 생성"), (2, "V1에서 이어가기")]))
        self.assertEqual([{k: m[k] for k in ("role", "text", "trace", "ver")} for m in same["messages"]],
                         [{"role": "agent", "text": "V1 시점의 대시보드로 되돌렸습니다. 이어서 요청해 주세요.", "trace": [], "ver": 2}])
        self.assertTrue(same["messages"][0]["ts"])
        # 다르면 지금 상태를 되돌리기에 쌓고, 작업본 = 그 버전의 차트 설정 + 지금 데이터(행 2개로 바뀐 Source)
        # When it differs the current state goes to undo, and the working copy = that version's specs on the current data
        rd.save_state(s["id"], rd.normalize_state({**st, "title": "바뀐 제목", "charts": [{**st["charts"][0], "type": "line"}],
                                                    "sources": [{**st["sources"][0], "rows": ROWS[:2]}]}), touch=False)
        back = rd.restore_version(s["id"], 1)
        self.assertEqual((back["state"]["title"], back["state"]["charts"][0]["type"], len(back["state"]["sources"][0]["rows"])), ("품질", "bar", 2))
        self.assertEqual((back["can_undo"], back["messages"][-1]["ver"], [v["n"] for v in back["versions"]]), (True, 3, [1, 2, 3]))
        self.assertEqual(rd.pop_undo(s["id"])["title"], "바뀐 제목")
        self.assertEqual((rd.restore_version(s["id"], 9), rd.restore_version("rd_none", 1)), (None, None))   # 없는 번호 · 없는 세션 / unknown

    def test_an_old_table_without_the_versions_column_reads_as_no_versions_and_is_migrated(self):
        # 버전 열이 없던 옛 DB: 열 없이도 읽히고(versions = []), init 이 열을 붙이면 버전이 쌓인다
        # An old DB without the versions column reads as no versions, and once init adds the column versions accumulate
        st = state_with([{"source": "s1", "x": "제품", "y": ["불량률"]}])
        with db._conn() as conn:
            conn.execute("DROP TABLE report_dash")
            conn.execute("CREATE TABLE report_dash(id TEXT PRIMARY KEY, owner TEXT NOT NULL, post_id TEXT, origin_key TEXT NOT NULL DEFAULT '',"
                         " origin TEXT NOT NULL DEFAULT '{}', state TEXT NOT NULL DEFAULT '{}', messages TEXT NOT NULL DEFAULT '[]',"
                         " created TEXT NOT NULL, updated TEXT NOT NULL, undo TEXT NOT NULL DEFAULT '[]',"
                         " dirty INTEGER NOT NULL DEFAULT 0, saved_at TEXT NOT NULL DEFAULT '')")
            conn.execute("INSERT INTO report_dash(id, owner, state, created, updated) VALUES(?,?,?,?,?)",
                         ("rd_old", "7", json.dumps(rd.pack_state(st), ensure_ascii=False), rd._now(), rd._now()))
        old = rd.get_session("rd_old")
        self.assertEqual((old["versions"], reports_api._public(old)["session"]["versions"], len(old["state"]["charts"])), ([], [], 1))
        rd.init_report_dash()
        self.assertEqual((rd.list_versions("rd_old"), rd.push_version("rd_old", old["state"], "차트 추가")), ([], 1))
        self.assertEqual([(v["n"], v["label"]) for v in rd.get_session("rd_old")["versions"]], [(1, "차트 추가")])


def calls(*items, text=""):
    return {"calls": [{"name": n, "args": a} for n, a in items], "text": text}


class AgentTests(unittest.TestCase):
    def test_create_then_insight_round_and_the_prompt_never_sees_chat(self):
        seen = []

        def fake(prompt, system=None, tools=None, tier="main"):
            seen.append(prompt)
            if len(seen) == 1:
                return calls(("create_chart", {"source_id": "s1", "type": "bar", "title": "제품별 불량률", "x": "제품",
                                               "y": [{"column": "불량률", "agg": "avg"}]}))
            return calls(("set_insight", {"chart_id": "c1", "text": "FG-CREAM-01 이 0.26 으로 가장 높다"}), text="차트를 추가했습니다.")

        with patch("app.llm.generate_calls", side_effect=fake):
            out = report_agent.run_turn(state_with(), [{"role": "user", "text": "이전 요청"}], "불량률 차트 만들어줘", None)
        self.assertEqual(len(seen), 2)                                     # 인사이트까지 2라운드, 3번째 호출 없음 / two rounds only
        self.assertIn("[이번 턴 도구 실행 결과]", seen[1])
        self.assertIn("불량률=[0.26", seen[1])                              # 계산된 실제 값이 돌아간다 / real computed values are fed back
        self.assertEqual(out["state"]["charts"][0]["insight"], "FG-CREAM-01 이 0.26 으로 가장 높다")
        self.assertEqual([(t["agent"], t["group"], t["tool"], t["ok"]) for t in out["trace"]],
                         [("Visualize Agent", "리포트", "create_chart", True), ("Visualize Agent", "정리", "set_insight", True)])
        self.assertEqual(out["reply"], "차트를 추가했습니다.")

    def test_style_reference_line_and_filter_finish_in_one_round(self):
        st = state_with([{"source": "s1", "x": "제품", "y": ["불량률"]}])
        fake = calls(("add_reference_line", {"chart_id": "c1", "label": "목표 0.3%", "value": 0.3}),
                     ("set_style", {"chart_id": "all", "palette": "ocean", "labels": True}),
                     ("add_filter", {"chart_id": "c1", "column": "연도", "selected": ["2026"]}))
        with patch("app.llm.generate_calls", return_value=fake) as m:
            out = report_agent.run_turn(st, [], "기준선 넣고 파랗게, 연도 필터도", None, focus="c1")
        self.assertEqual(m.call_count, 1)
        c = out["state"]["charts"][0]
        self.assertEqual((c["ref_lines"][0]["label"], c["ref_lines"][0]["value"], c["style"]["palette"], c["style"]["labels"]),
                         ("목표 0.3%", 0.3, "ocean", True))
        self.assertEqual([(f["col"], f["selected"]) for f in c["filters"]], [("연도", ["2026"])])
        self.assertIn("[선택된 차트] c1", m.call_args.args[0])
        self.assertIn("[현재 화면] 전체 대시보드", m.call_args.args[0])
        self.assertIn("기준선 '목표 0.3%'", out["reply"])                   # LLM 이 말이 없으면 도구별 문장을 잇는다 / per-tool sentences when the LLM is silent

    def test_filters_are_per_chart_all_means_each_chart_and_a_second_call_updates_the_selection(self):
        st = state_with([{"source": "s1", "x": "제품", "y": ["불량률"]}, {"source": "s1", "x": "연도", "y": ["검사수"]}])
        note, say = report_agent.run_tool(st, "add_filter", {"chart_id": "all", "column": "연도"}, None)
        self.assertEqual([[f["col"] for f in c["filters"]] for c in st["charts"]], [["연도"], ["연도"]])
        self.assertIn("차트 2개", say)
        report_agent.run_tool(st, "add_filter", {"chart_id": "c2", "column": "연도", "selected": ["2026"]}, None)
        self.assertEqual([c["filters"][0]["selected"] for c in st["charts"]], [[], ["2026"]])   # 차트마다 따로 / independent per chart
        self.assertEqual(len(st["charts"][1]["filters"]), 1)                                     # 같은 컬럼은 하나 / one filter per column
        # chart_id 를 안 주면 선택된 차트, 그다음 보고 있는 Source 탭의 차트 / blank id: the focused chart, then the tab's charts
        report_agent.run_tool(st, "remove_filter", {"column": "연도"}, None, {"focus": "c1", "view": ""})
        self.assertEqual([len(c["filters"]) for c in st["charts"]], [0, 1])
        with self.assertRaises(ValueError):
            report_agent.run_tool(st, "add_filter", {"chart_id": "c1", "column": "없는컬럼"}, None)

    def test_a_source_tab_scopes_new_charts_style_and_the_prompt(self):
        st = rd.normalize_state({"sources": [{"columns": COLS, "rows": ROWS}, {"columns": ["월", "매출"], "rows": [["1월", 10], ["2월", 30]]}],
                                 "charts": [{"source": "s1", "x": "제품", "y": ["검사수"]}, {"source": "s2", "x": "월", "y": ["매출"]}]})
        fake = calls(("create_chart", {"type": "line", "title": "월별 매출 추이", "x": "월", "y": [{"column": "매출"}]}),
                     ("set_style", {"chart_id": "all", "palette": "forest"}))
        with patch("app.llm.generate_calls", side_effect=[fake, calls(text="추가했습니다.")]) as m:
            out = report_agent.run_turn(st, [], "추이 차트 하나 더, 색은 초록으로", None, view="s2")
        self.assertIn("[현재 화면] Source 2(s2) 탭", m.call_args_list[0].args[0])
        charts = out["state"]["charts"]
        # 새 리포트는 Source 3(같은 데이터의 복제) 탭이 되고, Source 탭의 '모든 차트'는 그 데이터로 만든 리포트들이다
        # The new report becomes Source 3 (a clone of the same data); "every chart" on a Source tab means the reports of that data
        self.assertEqual([(c["id"], c["source"], c["style"]["palette"]) for c in charts],
                         [("c1", "s1", "indigo"), ("c2", "s2", "forest"), ("c3", "s3", "forest")])
        s3 = out["state"]["sources"][2]
        self.assertEqual((s3["name"], s3["label"], s3["origin"]["clone_of"]), ("Source 3", "월별 매출 추이", "s2"))
        self.assertIn("'월별 매출 추이' 리포트를 추가했습니다", out["reply"] + " ".join(t["say"] for t in out["trace"]))   # 탭 문구 폐지(2026-09-22) / no tab wording

    def test_ids_the_model_writes_loosely_still_resolve(self):
        st = state_with([{"source": "s1", "x": "제품", "y": ["불량률"], "title": "제품별 불량률"}])
        report_agent.run_tool(st, "create_chart", {"source_id": "Source 1", "type": "line", "title": "추이", "x": "연도", "y": ["검사수"]}, None)
        self.assertEqual([(c["id"], c["source"]) for c in st["charts"]], [("c1", "s1"), ("c2", "s2")])   # 'Source 1' = s1 → 새 리포트라 s2 로 복제
        report_agent.run_tool(st, "set_insight", {"chart_id": "차트 2", "text": "가"}, None)
        report_agent.run_tool(st, "set_insight", {"chart_id": "'제품별 불량률'", "text": "나"}, None)
        self.assertEqual([c["insight"] for c in st["charts"]], ["나", "가"])
        with self.assertRaises(ValueError):
            report_agent.run_tool(st, "set_insight", {"chart_id": "c9", "text": "다"}, None)

    def test_failed_tool_is_reported_back_and_update_chart_switches_type(self):
        st = state_with([{"source": "s1", "type": "bar", "x": "제품", "y": ["불량률"]}])
        rounds = [calls(("update_chart", {"chart_id": "c1", "add_y": [{"column": "없는값"}]})),
                  calls(("update_chart", {"chart_id": "c1", "type": "line", "add_y": [{"column": "검사수", "axis": 1}]})),
                  calls(text="선 차트로 바꾸고 검사수를 추가했습니다.")]
        with patch("app.llm.generate_calls", side_effect=rounds):
            out = report_agent.run_turn(st, [], "선으로 바꾸고 검사수도", None)
        self.assertEqual([t["ok"] for t in out["trace"]], [False, True])
        c = out["state"]["charts"][0]
        self.assertEqual((c["type"], [(y["col"], y["type"], y["axis"]) for y in c["y"]]),
                         ("line", [("불량률", "line", 0), ("검사수", "line", 1)]))

    def test_query_data_is_gated_and_adds_a_source_with_provenance(self):
        eff = {"nodes": {}, "read": {"p_data": True}}
        with patch.object(report_agent.catalog, "allowed_tables", return_value=set()), \
                patch("app.analytics.refresh_csv_views"):
            with self.assertRaises(report_agent.AgentError):
                report_agent.query("매출", eff)
        with patch("app.analytics.refresh_csv_views"), patch("app.analytics.schema_summary", return_value="t(a)"), \
                patch("app.llm.generate", return_value={"sql": "SELECT a FROM sales"}), \
                patch("app.analytics.guard_sql", return_value="SELECT a FROM sales LIMIT 200"), \
                patch("app.analytics.run_select", return_value=(["월", "매출"], [["1월", 10]])), \
                patch.object(report_agent.catalog, "all_table_names", return_value={"sales", "hr"}):
            st = state_with()
            note, say = report_agent.run_tool(st, "query_data", {"request": "월별 매출", "label": "월 매출"}, None)
        src = st["sources"][1]
        self.assertEqual((src["id"], src["name"], src["label"], src["tables"], src["origin"]["kind"], src["origin"]["note"]),
                         ("s2", "Source 2", "월 매출", ["sales"], "agent", "월별 매출"))
        self.assertIn("s2", note)
        self.assertIn("Source 2", say)

    def test_auto_charts_fall_back_to_rules_when_the_llm_fails(self):
        with patch("app.llm.generate_calls", side_effect=RuntimeError("down")):
            out = report_agent.auto_charts(state_with(), None)
        c = out["state"]["charts"][0]
        self.assertEqual((c["x"], c["y"][0]["col"], c["y"][0]["agg"], c["type"]), ("제품", "불량률", "avg", "bar"))   # 연도는 값이 아니다, 비율은 평균 / a year is not a value; rates average
        self.assertTrue(c["insight"])
        self.assertNotEqual(out["state"]["title"], "새 대시보드")

    def test_a_version_is_named_after_the_tools_that_succeeded(self):
        # 버전 이름(2026-10-13): 성공한 도구 이름을 순서대로 겹치지 않게 2개 + ' 외 N', 없으면 '변경' / two tool labels plus ' 외 N', else '변경'
        def t(name, ok=True):
            return report_agent._trace_entry(name, ok, "")
        label = reports_api._version_label
        self.assertEqual(label([t("create_chart"), t("set_insight")]), "차트 추가 · 인사이트 작성")
        self.assertEqual(label([t("create_chart"), t("add_filter"), t("set_style")]), "차트 추가 · 필터 추가 외 1")
        self.assertEqual(label([t("add_filter", False), t("create_chart"), t("create_chart"), t("add_filter"), t("set_style"), t("set_theme")]),
                         "차트 추가 · 필터 추가 외 2")   # 실패한 도구는 빠지고 같은 이름은 한 번 / failures skipped, repeats once
        self.assertEqual((label([]), label([t("add_filter", False)])), ("변경", "변경"))


class ApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        boards.init_boards()
        rd.init_report_dash()
        self.stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")))
        self.stack.enter_context(patch.object(access, "list_groups", return_value=[]))
        self.stack.enter_context(patch.object(access, "list_members", return_value=[{"no": 7, "name": "강수아"}]))
        self.stack.enter_context(patch("app.resources_api._eff", return_value=None))
        self.app = FastAPI()
        self.app.include_router(reports_api.router)
        self.app.include_router(boards_api.router)

    async def req(self, method, path, json=None):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
            return await client.request(method, path, json=json)

    async def start(self):
        r = await self.req("POST", "/api/reports/dash", {"acting_user_id": "7", "chat_id": "chat1", "chat_title": "품질 질문",
                                                          "sources": [{"columns": COLS, "rows": ROWS, "sql": SQL}]})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["session"]

    async def test_open_auto_turn_explicit_save_and_resume(self):
        # 2026-09-22 사용자 결정: 자동 저장 대신 [저장] — 저장 전에는 보관함에 아무것도 없다 / explicit save: nothing reaches the library before [Save]
        s = await self.start()
        self.assertTrue(s["pending_auto"])
        self.assertEqual(s["state"]["sources"][0]["origin"], {"kind": "chat", "note": "품질 질문", "chat_id": "chat1", "clone_of": ""})
        with patch("app.llm.generate_calls", side_effect=RuntimeError("down")):
            auto = (await self.req("POST", f"/api/reports/dash/{s['id']}/auto", {"acting_user_id": "7"})).json()
        self.assertEqual(len(auto["session"]["state"]["charts"]), 1)
        self.assertEqual((auto["session"]["saved"], auto["session"]["dirty"]), (False, False))   # 첫 차트는 사용자의 변경이 아니다 / the first charts are not the user's change
        self.assertEqual((await self.req("GET", "/api/reports/dash/library?acting_user_id=7")).json()["items"], [])
        fake = calls(("add_reference_line", {"chart_id": "c1", "label": "목표", "value": 2000}), text="기준선을 넣었습니다.")
        with patch("app.llm.generate_calls", return_value=fake):
            turn = (await self.req("POST", f"/api/reports/dash/{s['id']}/turn",
                                   {"acting_user_id": "7", "message": "목표선 넣어줘", "focus": "c1"})).json()
        self.assertEqual((turn["session"]["saved"], turn["session"]["dirty"]), (False, True))   # 저장 안 된 변경 / an unsaved change
        self.assertEqual(turn["trace"][0]["label"], "기준선 추가")
        self.assertEqual((await self.req("GET", "/api/reports/dash/library?acting_user_id=7")).json()["items"], [])
        saved = (await self.req("POST", f"/api/reports/dash/{s['id']}/save", {"acting_user_id": "7"})).json()
        self.assertEqual((saved["created"], saved["session"]["saved"], saved["session"]["dirty"], bool(saved["session"]["saved_at"])), (True, True, False, True))
        lib = (await self.req("GET", "/api/reports/dash/library?acting_user_id=7")).json()["items"]
        self.assertEqual([(i["kind"], i["v2"], i["charts"], i["sources"]) for i in lib], [("dashboard", True, 1, 1)])
        self.assertNotIn("rows", str(lib[0]["thumbs"][0].keys()))
        self.assertEqual(boards.get_post(saved["session"]["post_id"])["data"]["charts"][0]["ref_lines"][0]["label"], "목표")
        again = (await self.req("POST", "/api/reports/dash", {"acting_user_id": "7", "chat_id": "chat1",
                                                              "sources": [{"columns": COLS, "rows": ROWS, "sql": SQL}]})).json()
        self.assertTrue(again["resumed"] and again["session"]["saved"])
        self.assertEqual([m["role"] for m in again["session"]["messages"]], ["agent", "user", "agent"])
        # 남의 세션은 404 / another identity gets 404
        self.assertEqual((await self.req("GET", f"/api/reports/dash/{s['id']}?acting_user_id=9")).status_code, 404)
        # 다시 저장하면 같은 글이 갱신된다 / saving again updates the same post
        with patch("app.llm.generate_calls", return_value=calls(("rename_dashboard", {"title": "새 제목"}), text="바꿨습니다.")):
            turn = (await self.req("POST", f"/api/reports/dash/{s['id']}/turn", {"acting_user_id": "7", "message": "이름 바꿔"})).json()
        self.assertEqual((turn["session"]["dirty"], boards.get_post(saved["session"]["post_id"])["title"]), (True, boards.get_post(saved["session"]["post_id"])["title"]))
        self.assertNotEqual(boards.get_post(saved["session"]["post_id"])["title"], "새 제목")
        again = (await self.req("POST", f"/api/reports/dash/{s['id']}/save", {"acting_user_id": "7"})).json()
        self.assertEqual((again["created"], again["session"]["post_id"]), (False, saved["session"]["post_id"]))
        self.assertEqual([p["title"] for p in boards.list_posts("me:7")], ["새 제목"])

    async def test_discard_reverts_to_the_saved_copy_or_drops_a_never_saved_draft(self):
        s = await self.start()
        with patch("app.llm.generate_calls", side_effect=RuntimeError("down")):
            await self.req("POST", f"/api/reports/dash/{s['id']}/auto", {"acting_user_id": "7"})
        await self.req("POST", f"/api/reports/dash/{s['id']}/save", {"acting_user_id": "7"})
        r = (await self.req("POST", f"/api/reports/dash/{s['id']}/ops",
                            {"acting_user_id": "7", "ops": [{"op": "title", "title": "버릴 이름"}, {"op": "chart_remove", "id": "c1"}]})).json()
        self.assertEqual((r["session"]["dirty"], r["session"]["state"]["charts"], r["session"]["can_undo"]), (True, [], True))
        back = (await self.req("POST", f"/api/reports/dash/{s['id']}/discard", {"acting_user_id": "7"})).json()
        self.assertEqual((back["deleted"], back["session"]["dirty"], back["session"]["can_undo"], len(back["session"]["state"]["charts"])), (False, False, False, 1))
        self.assertNotEqual(back["session"]["state"]["title"], "버릴 이름")   # 마지막 저장본으로 / back to the last saved copy
        # 저장 안 된 변경이 없으면 보관함에서 다시 열 때 글의 최신 내용을 따른다 / a clean session follows the post when reopened
        boards.update_post(back["session"]["post_id"], {"title": "다른 화면에서 바꾼 이름"})
        opened = (await self.req("POST", "/api/reports/dash/open", {"acting_user_id": "7", "post_id": back["session"]["post_id"]})).json()
        self.assertEqual((opened["session"]["id"], opened["session"]["state"]["title"]), (s["id"], "다른 화면에서 바꾼 이름"))
        # 한 번도 저장하지 않은 초안은 세션째 사라진다 / a never-saved draft is dropped with its session
        d = (await self.req("POST", "/api/reports/dash", {"acting_user_id": "7", "chat_id": "chat2",
                                                          "sources": [{"columns": COLS, "rows": ROWS, "sql": SQL}]})).json()["session"]
        gone = (await self.req("POST", f"/api/reports/dash/{d['id']}/discard", {"acting_user_id": "7"})).json()
        self.assertEqual((gone["deleted"], gone["session"]), (True, None))
        self.assertEqual((await self.req("GET", f"/api/reports/dash/{d['id']}?acting_user_id=7")).status_code, 404)
        self.assertEqual((await self.req("POST", f"/api/reports/dash/{d['id']}/save", {"acting_user_id": "7"})).status_code, 404)
        blank = (await self.req("POST", "/api/reports/dash", {"acting_user_id": "7", "blank": True})).json()["session"]
        self.assertEqual((await self.req("POST", f"/api/reports/dash/{blank['id']}/save", {"acting_user_id": "7"})).status_code, 422)   # 차트 없음 / no charts

    async def test_tool_tree_lists_every_attached_tool_under_its_agent_and_group(self):
        r = (await self.req("GET", "/api/reports/dash/tools")).json()
        self.assertEqual(r["root"], "리포트 에이전트")
        self.assertEqual([(a["agent"], [g["group"] for g in a["groups"]]) for a in r["agents"]],
                         [("Data Agent", ["데이터"]),
                          ("Visualize Agent", ["리포트", "기준선", "계산 값", "강조", "드릴다운", "디자인", "필터", "추세·예측", "KPI 카드", "정리"])])
        names = [t["name"] for a in r["agents"] for g in a["groups"] for t in g["tools"]]
        self.assertEqual(sorted(names), sorted(s["name"] for s in report_agent.TOOL_SPECS))   # 빠진 도구가 없다 / none is missing
        self.assertEqual(set(report_agent.TOOL_GROUP), set(report_agent.TOOL_META))

    async def test_ops_change_the_working_copy_and_mark_it_unsaved(self):
        s = await self.start()
        with patch("app.llm.generate_calls", side_effect=RuntimeError("down")):
            await self.req("POST", f"/api/reports/dash/{s['id']}/auto", {"acting_user_id": "7"})
        st = rd.get_session(s["id"])["state"]
        st["charts"][0]["filters"] = [{"col": "연도"}]
        rd.save_state(s["id"], st, touch=False)
        r = (await self.req("POST", f"/api/reports/dash/{s['id']}/ops",
                            {"acting_user_id": "7", "ops": [{"op": "filter_select", "chart": "c1", "id": "f1", "selected": [2026]}]})).json()
        self.assertEqual((r["session"]["state"]["charts"][0]["filters"][0]["selected"], r["session"]["saved"], r["session"]["dirty"]), (["2026"], False, True))
        r = (await self.req("POST", f"/api/reports/dash/{s['id']}/ops",
                            {"acting_user_id": "7", "ops": [{"op": "filter_add", "chart": "c1", "col": "제품"}]})).json()
        self.assertEqual(([f["col"] for f in r["session"]["state"]["charts"][0]["filters"]], r["session"]["saved"]), (["연도", "제품"], False))
        r = (await self.req("POST", f"/api/reports/dash/{s['id']}/ops",
                            {"acting_user_id": "7", "ops": [{"op": "filter_remove", "chart": "c1", "id": "f1"}]})).json()
        self.assertEqual([f["col"] for f in r["session"]["state"]["charts"][0]["filters"]], ["제품"])
        r = (await self.req("POST", f"/api/reports/dash/{s['id']}/ops",
                            {"acting_user_id": "7", "ops": [{"op": "chart_size", "id": "c1", "size": "full"},
                                                            {"op": "title", "title": "품질 현황"}]})).json()
        self.assertEqual((r["session"]["state"]["charts"][0]["size"], r["session"]["state"]["title"], r["session"]["saved"], r["session"]["dirty"]),
                         ("full", "품질 현황", False, True))
        self.assertEqual(boards.list_posts("me:7"), [])                    # 보관함은 [저장] 전까지 비어 있다 / the library stays empty until [Save]
        bad = await self.req("POST", f"/api/reports/dash/{s['id']}/ops", {"acting_user_id": "7", "ops": [{"op": "nope"}]})
        self.assertEqual(bad.status_code, 422)
        saved = (await self.req("POST", f"/api/reports/dash/{s['id']}/save", {"acting_user_id": "7"})).json()["session"]
        post = boards.get_post(saved["post_id"])
        self.assertEqual((post["title"], [f["col"] for f in post["data"]["charts"][0]["filters"]], post["data"]["charts"][0]["size"]),
                         ("품질 현황", ["제품"], "full"))

    async def test_undo_restores_the_charts_before_a_turn_and_before_a_deletion(self):
        s = await self.start()
        with patch("app.llm.generate_calls", side_effect=RuntimeError("down")):
            await self.req("POST", f"/api/reports/dash/{s['id']}/auto", {"acting_user_id": "7"})
        none = await self.req("POST", f"/api/reports/dash/{s['id']}/undo", {"acting_user_id": "7"})
        self.assertEqual(none.status_code, 409)
        fake = calls(("set_style", {"chart_id": "c1", "palette": "sunset"}), ("rename_dashboard", {"title": "새 제목"}))
        with patch("app.llm.generate_calls", return_value=fake):
            turn = (await self.req("POST", f"/api/reports/dash/{s['id']}/turn",
                                   {"acting_user_id": "7", "message": "주황으로", "view": "s1"})).json()
        self.assertEqual((turn["session"]["state"]["charts"][0]["style"]["palette"], turn["session"]["can_undo"]), ("sunset", True))
        await self.req("POST", f"/api/reports/dash/{s['id']}/ops", {"acting_user_id": "7", "ops": [{"op": "chart_remove", "id": "c1"}]})
        back = (await self.req("POST", f"/api/reports/dash/{s['id']}/undo", {"acting_user_id": "7"})).json()
        self.assertEqual([c["style"]["palette"] for c in back["session"]["state"]["charts"]], ["sunset"])   # 삭제를 되돌림 / the deletion is undone
        back = (await self.req("POST", f"/api/reports/dash/{s['id']}/undo", {"acting_user_id": "7"})).json()
        st = back["session"]["state"]
        self.assertEqual((st["charts"][0]["style"]["palette"], st["title"] != "새 제목", back["session"]["can_undo"]), ("indigo", True, False))
        self.assertEqual(len(st["sources"]), 1)                           # 데이터는 그대로 / sources stay

    async def two_versions(self):
        """시작 → 첫 차트(V1) → 상태를 바꾼 턴(V2, 실패한 도구 하나 포함) / start, first charts (V1), one changing turn (V2, one tool fails)"""
        s = await self.start()
        with patch("app.llm.generate_calls", side_effect=RuntimeError("down")):
            auto = (await self.req("POST", f"/api/reports/dash/{s['id']}/auto", {"acting_user_id": "7"})).json()["session"]
        fake = calls(("add_reference_line", {"chart_id": "c1", "label": "목표", "value": 0.3}),
                     ("set_style", {"chart_id": "c1", "palette": "sunset"}), ("set_style", {"chart_id": "c1", "labels": True}),
                     ("add_filter", {"chart_id": "c1", "column": "없는컬럼"}), ("rename_dashboard", {"title": "품질 현황"}))
        with patch("app.llm.generate_calls", side_effect=[fake, calls(text="반영했습니다.")]):
            turn = (await self.req("POST", f"/api/reports/dash/{s['id']}/turn",
                                   {"acting_user_id": "7", "message": "목표선 넣고 주황으로, 이름은 품질 현황"})).json()
        return s, auto, turn

    async def test_versions_follow_the_first_charts_and_changing_turns_and_every_agent_message_carries_the_latest(self):
        # 버전(2026-10-13): 첫 차트 = V1 '대시보드 생성', 상태를 바꾼 턴 = 새 버전(성공한 도구 이름), agent 메시지의 ver = 그 시점의 최신 번호
        # Versions: the first charts are V1, a changing turn adds one named after its tools, agent messages carry the latest number
        s, auto, turn = await self.two_versions()
        self.assertEqual(s["versions"], [])                                       # 시작할 때는 없다 / none at the start
        self.assertEqual([(v["n"], v["label"]) for v in auto["versions"]], [(1, "대시보드 생성")])
        self.assertEqual((set(auto["versions"][0]), bool(auto["versions"][0]["at"])), ({"n", "label", "at"}, True))   # 스냅은 싣지 않는다 / no snaps
        self.assertEqual(auto["messages"][-1]["ver"], 1)
        ses = turn["session"]
        self.assertEqual([t["ok"] for t in turn["trace"]], [True, True, True, False, True])
        self.assertEqual([(v["n"], v["label"]) for v in ses["versions"]], [(1, "대시보드 생성"), (2, "기준선 추가 · 디자인 변경 외 1")])
        self.assertEqual([(m["role"], m.get("ver")) for m in ses["messages"]], [("agent", 1), ("user", None), ("agent", 2)])
        # 바꾸지 않은 턴(답만 · 실패한 도구만)은 버전을 늘리지 않고 최신 번호를 단다 / turns that change nothing add none and carry the latest
        for rounds in ([calls(text="지금은 제품별 불량률 차트 하나입니다.")],
                       [calls(("add_filter", {"chart_id": "c1", "column": "없는컬럼"})), calls(text="그런 컬럼은 없습니다.")]):
            with patch("app.llm.generate_calls", side_effect=rounds):
                same = (await self.req("POST", f"/api/reports/dash/{s['id']}/turn", {"acting_user_id": "7", "message": "어때?"})).json()["session"]
            self.assertEqual(([v["n"] for v in same["versions"]], same["messages"][-1]["ver"], "ver" in same["messages"][-2]), ([1, 2], 2, False))
        # 버전이 하나도 없으면 ver 키가 없다 / no version yet, no ver key
        blank = (await self.req("POST", "/api/reports/dash", {"acting_user_id": "7", "blank": True})).json()["session"]
        with patch("app.llm.generate_calls", return_value=calls(text="어떤 데이터를 볼까요?")):
            b = (await self.req("POST", f"/api/reports/dash/{blank['id']}/turn", {"acting_user_id": "7", "message": "안녕"})).json()["session"]
        self.assertEqual((b["versions"], [m["role"] for m in b["messages"]], "ver" in b["messages"][-1]), ([], ["user", "agent"], False))

    async def test_a_version_previews_on_the_current_data_and_continuing_from_it_is_an_undoable_new_version(self):
        s, auto, _ = await self.two_versions()
        sid, v1, title1 = s["id"], auto["versions"][0], auto["state"]["title"]
        # 새로고침은 버전이 아니다. 미리보기 = 그 시점의 차트 설정을 지금 데이터(새로고침한 행 2개)로, 작업본은 그대로
        # A refresh is no version; a preview draws that moment's specs on the current data (two refreshed rows), the working copy stays
        with patch("app.analytics.refresh_csv_views"), patch("app.analytics.run_select", return_value=(COLS, ROWS[:2])):
            ref = (await self.req("POST", f"/api/reports/dash/{sid}/refresh", {"acting_user_id": "7"})).json()["session"]
        self.assertEqual([v["n"] for v in ref["versions"]], [1, 2])
        r = await self.req("GET", f"/api/reports/dash/{sid}/versions/1?acting_user_id=7")
        self.assertEqual(r.status_code, 200, r.text)
        prev = r.json()
        c = prev["state"]["charts"][0]
        self.assertEqual((prev["version"], prev["state"]["title"], c["ref_lines"], c["style"]["palette"]), (v1, title1, [], "indigo"))
        self.assertEqual([len(x["rows"]) for x in prev["state"]["sources"]], [2])
        v2 = (await self.req("GET", f"/api/reports/dash/{sid}/versions/2?acting_user_id=7")).json()["state"]
        self.assertEqual((v2["title"], v2["charts"][0]["ref_lines"][0]["label"], v2["charts"][0]["style"]["palette"]), ("품질 현황", "목표", "sunset"))
        cur = rd.get_session(sid)["state"]
        self.assertEqual((cur["title"], cur["charts"][0]["style"]["palette"]), ("품질 현황", "sunset"))
        # 없는 번호 · 남의 세션은 404 / an unknown number or another identity gets 404
        self.assertEqual([(await self.req("GET", f"/api/reports/dash/{sid}/versions/{n}?acting_user_id={who}")).status_code
                          for n, who in ((9, "7"), (0, "7"), (1, "9"))], [404, 404, 404])
        self.assertEqual([(await self.req("POST", f"/api/reports/dash/{sid}/versions/{n}/restore", {"acting_user_id": who})).status_code
                          for n, who in ((9, "7"), (1, "9"))], [404, 404])
        # [이 버전으로 이어가기]: 작업본 = V1 의 차트(지금 데이터), 되돌리기 가능, 새 버전 V3, 저장하지 않은 변경(저장해 둔 뒤 확인)
        # Continue from V1: the working copy = V1's charts on the current data, undoable, a new V3, unsaved (checked after a save)
        await self.req("POST", f"/api/reports/dash/{sid}/save", {"acting_user_id": "7"})
        r = await self.req("POST", f"/api/reports/dash/{sid}/versions/1/restore", {"acting_user_id": "7"})
        self.assertEqual(r.status_code, 200, r.text)
        text = "V1 시점의 대시보드로 되돌렸습니다. 이어서 요청해 주세요."
        ses = r.json()["session"]
        st = ses["state"]
        self.assertEqual((r.json()["reply"], st["title"], st["charts"][0]["ref_lines"], st["charts"][0]["style"]["palette"], len(st["sources"][0]["rows"])),
                         (text, title1, [], "indigo", 2))
        self.assertEqual((ses["can_undo"], ses["dirty"], ses["saved"]), (True, True, True))
        self.assertEqual([(v["n"], v["label"]) for v in ses["versions"]],
                         [(1, "대시보드 생성"), (2, "기준선 추가 · 디자인 변경 외 1"), (3, "V1에서 이어가기")])
        last = ses["messages"][-1]
        self.assertEqual({k: last[k] for k in ("role", "text", "trace", "ver")}, {"role": "agent", "text": text, "trace": [], "ver": 3})
        # 되돌리기 = 이어가기 전으로. 되돌리기 · 화면 조작 · 저장 · 저장하지 않고 닫기는 버전을 만들지도 지우지도 않는다
        # Undo goes back to before continuing; undo, UI ops, saving and discarding neither add nor remove versions
        back = (await self.req("POST", f"/api/reports/dash/{sid}/undo", {"acting_user_id": "7"})).json()["session"]
        # 되돌리기 안내에는 버전 칩이 없다(되돌린 상태는 최신 버전과 다르다) / the undo notice carries no version chip (its state differs from the latest version)
        self.assertEqual((back["state"]["title"], back["state"]["charts"][0]["style"]["palette"], "ver" in back["messages"][-1]), ("품질 현황", "sunset", False))
        ops = (await self.req("POST", f"/api/reports/dash/{sid}/ops", {"acting_user_id": "7", "ops": [{"op": "title", "title": "조작한 이름"}]})).json()["session"]
        saved = (await self.req("POST", f"/api/reports/dash/{sid}/save", {"acting_user_id": "7"})).json()["session"]
        await self.req("POST", f"/api/reports/dash/{sid}/ops", {"acting_user_id": "7", "ops": [{"op": "chart_remove", "id": "c1"}]})
        kept = (await self.req("POST", f"/api/reports/dash/{sid}/discard", {"acting_user_id": "7"})).json()["session"]
        self.assertEqual([[v["n"] for v in x["versions"]] for x in (back, ops, saved, kept)], [[1, 2, 3]] * 4)
        self.assertEqual((kept["state"]["title"], len(kept["state"]["charts"]), kept["dirty"]), ("조작한 이름", 1, False))

    async def test_snapshot_shares_to_a_board_recomputed_and_reopens_from_the_library(self):
        s = await self.start()
        with patch("app.llm.generate_calls", side_effect=RuntimeError("down")):
            await self.req("POST", f"/api/reports/dash/{s['id']}/auto", {"acting_user_id": "7"})
        snap = (await self.req("GET", f"/api/reports/dash/{s['id']}/snapshot?acting_user_id=7")).json()
        self.assertEqual((snap["kind"], snap["data"]["v"]), ("dashboard", 2))
        forged = {**snap["data"], "items": [{"title": "위조", "chart": {"x": ["a"], "series": [{"name": "v", "values": [999]}]}}]}
        with patch.object(access, "list_groups", return_value=[{"id": "og9", "name": "팀장"}]):   # 전체 게시판은 읽기 전용(2026-09-22) — 그룹 게시판에 공유 / all-hands is read-only; share to a group board
            shared = await self.req("POST", "/api/boards/g:og9/posts", {"acting_user_id": "7", "post": {
                "kind": "dashboard", "title": snap["title"], "data": forged}})
        self.assertEqual(shared.status_code, 200, shared.text)
        tile = shared.json()["post"]["data"]["items"][0]
        self.assertNotEqual(tile["title"], "위조")                        # 타일은 서버가 다시 계산한다 / tiles are recomputed by the server
        self.assertNotIn("messages", shared.json()["post"]["data"])
        one = (await self.req("POST", f"/api/reports/dash/{s['id']}/charts/c1/save", {"acting_user_id": "7"})).json()
        self.assertEqual(one["report"]["v"], 2)
        opened = (await self.req("POST", "/api/reports/dash/open", {"acting_user_id": "7", "post_id": one["report"]["id"]})).json()
        self.assertEqual((opened["session"]["kind"], len(opened["session"]["state"]["charts"])), ("report", 1))
        miss = await self.req("POST", "/api/reports/dash/open", {"acting_user_id": "9", "post_id": one["report"]["id"]})
        self.assertEqual(miss.status_code, 404)

    async def test_mail_share_records_a_sent_mail_and_returns_an_outlook_compose_link(self):
        # 이메일로 공유(2026-09-22): 가상 메일함 기록 + Outlook 웹 작성 링크, 대화는 싣지 않는다 / mail share: a virtual-mailbox row + an Outlook compose link, never the conversation
        s = await self.start()
        with patch("app.llm.generate_calls", side_effect=RuntimeError("down")):
            await self.req("POST", f"/api/reports/dash/{s['id']}/auto", {"acting_user_id": "7"})
        rd.append_messages(s["id"], [{"role": "user", "text": "비밀 대화"}])
        members = [{"no": 7, "name": "강수아", "dept": "PMO파트", "email": "sua.kang@example.com"},
                   {"no": 8, "name": "박도윤", "dept": "PMO파트", "email": "doyun.park@example.com"},
                   {"no": 9, "name": "퇴직자", "dept": "PMO파트", "email": "gone@example.com", "status": "퇴직"},
                   {"no": 10, "name": "이서윤", "dept": "재무회계파트", "email": "seoyoon.lee@example.com"}]
        with patch.object(access, "list_members", return_value=members), \
                patch("app.smart_seed.mail_send", return_value={"id": "s77"}) as sent:
            r = await self.req("POST", f"/api/reports/dash/{s['id']}/mail",
                               {"acting_user_id": "7", "teams": ["PMO파트"],
                                "people": [{"name": "외부", "email": "demo-8d01dff546@workspace.example"}, {"name": "나쁜", "email": "not-an-email"},
                                           {"name": "중복", "email": "SUA.KANG@example.com"}]})
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()
        self.assertEqual(out["to"], ["demo-8d01dff546@workspace.example", "SUA.KANG@example.com", "doyun.park@example.com"])   # 부서 재직자만, 중복·잘못된 주소 제외 / active department members only; duplicates and bad addresses dropped
        self.assertEqual((out["mail_id"], out["subject"].startswith("[Ai365 리포트] ")), ("s77", True))
        to, subject, text = sent.call_args.args[:3]
        self.assertEqual((to, subject), (out["to"], out["subject"]))
        self.assertIn("[리포트]", text)
        self.assertIn("강수아님이 공유했습니다", text)
        self.assertNotIn("비밀 대화", text)
        self.assertTrue(out["open_urls"][0].startswith("https://outlook.office.com/mail/deeplink/compose?to=ext%40partner.com%2C"))
        self.assertIn("&subject=%5BAi365", out["open_urls"][0])
        # 차트 하나 = 리포트 / 받는 사람 없음 = 422 / 없는 차트 = 404 — 공유는 변경이 아니다
        # one chart = a report / no recipients = 422 / unknown chart = 404 — sharing is not a change
        with patch.object(access, "list_members", return_value=members), patch("app.smart_seed.mail_send", return_value={"id": "s78"}):
            one = await self.req("POST", f"/api/reports/dash/{s['id']}/mail", {"acting_user_id": "7", "chart": "c1", "people": [{"email": "demo-8d01dff546@workspace.example"}]})
            none = await self.req("POST", f"/api/reports/dash/{s['id']}/mail", {"acting_user_id": "7", "teams": ["없는 부서"]})
            miss = await self.req("POST", f"/api/reports/dash/{s['id']}/mail", {"acting_user_id": "7", "chart": "c9", "people": [{"email": "demo-8d01dff546@workspace.example"}]})
        self.assertEqual((one.status_code, none.status_code, miss.status_code), (200, 422, 404))
        self.assertEqual(one.json()["subject"], "[Ai365 리포트] " + rd.get_session(s["id"])["state"]["charts"][0]["title"])
        self.assertFalse(rd.get_session(s["id"])["dirty"])

    async def test_library_post_mail_share_uses_the_post_title_and_is_owner_only(self):
        # 게시판 › 내 보관함 상세의 [공유하기] › 메일로 공유(2026-09-22) / the library detail's [Share] › email
        st = state_with([{"source": "s1", "x": "제품", "y": ["불량률"], "insight": "핵심 인사이트"}])
        saved = reports.add_personal("7", rd.dashboard_data(st))
        boards.update_post(saved["id"], {"title": "보관함 제목", "summary": "보관함 요약"})
        with patch("app.smart_seed.mail_send", return_value={"id": "s79"}) as sent:
            r = await self.req("POST", f"/api/reports/personal/{saved['id']}/mail", {"acting_user_id": "7", "people": [{"email": "demo-8d01dff546@workspace.example"}]})
            other = await self.req("POST", f"/api/reports/personal/{saved['id']}/mail", {"acting_user_id": "9", "people": [{"email": "demo-8d01dff546@workspace.example"}]})
            none = await self.req("POST", f"/api/reports/personal/{saved['id']}/mail", {"acting_user_id": "7", "people": []})
        self.assertEqual((r.status_code, other.status_code, none.status_code), (200, 404, 422), r.text)
        self.assertEqual((r.json()["subject"], r.json()["mail_id"], r.json()["to"]), ("[Ai365 리포트] 보관함 제목", "s79", ["demo-8d01dff546@workspace.example"]))
        text = sent.call_args.args[2]
        self.assertIn("보관함 요약", text)
        self.assertIn("핵심 인사이트", text)
        self.assertTrue(r.json()["open_urls"][0].startswith("https://outlook.office.com/mail/deeplink/compose?to=ext%40partner.com&subject="))

    async def test_legacy_library_screen_can_rename_and_drop_tiles_of_a_v2_dashboard(self):
        st = state_with([{"source": "s1", "x": "제품", "y": ["불량률"]}, {"source": "s1", "x": "연도", "y": ["검사수"]}])
        saved = reports.add_personal("7", rd.dashboard_data(st))
        items = [saved["items"][1]]                                       # 리소스 센터 화면이 보내는 모양(타일 그대로) / what the legacy screen sends
        r = await self.req("PATCH", f"/api/reports/personal/{saved['id']}",
                           {"acting_user_id": "7", "report": {"type": "dashboard", "title": "새 이름", "items": items}})
        self.assertEqual(r.status_code, 200, r.text)
        rep = r.json()["report"]
        self.assertEqual((rep["title"], rep["v"], [(c["id"], c["source"]) for c in rep["charts"]], len(rep["sources"])),
                         ("새 이름", 2, [("c2", "s2")], 2))   # Source 는 지우지 않는다 / sources are never removed

    async def test_refresh_reruns_stored_sql_and_reports_what_it_could_not(self):
        s = await self.start()
        with patch("app.analytics.refresh_csv_views"), \
                patch("app.analytics.run_select", return_value=(COLS, ROWS[:2])) as run:
            r = (await self.req("POST", f"/api/reports/dash/{s['id']}/refresh", {"acting_user_id": "7"})).json()
        self.assertEqual(run.call_args.args, (SQL, None))                 # 슈퍼 = 제한 없음 / super = unrestricted
        self.assertEqual((r["refreshed"], len(r["session"]["state"]["sources"][0]["rows"])), ([{"id": "s1", "ok": True, "rows": 2}], 2))


if __name__ == "__main__":
    unittest.main()
