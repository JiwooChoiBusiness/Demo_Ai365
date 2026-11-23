# -*- coding: utf-8 -*-
"""위젯 데이터 파이프라인(2026-11-16, app/widget_data.py — 위젯 에이전트 전용, 계약 = docs/widget-agent.md 11절): 의도 판단 정리 · 낱말 규칙,
자료에서 뽑기(자료 본문에 없는 숫자 · 자료에 없는 주소는 버린다), 이름으로 짝짓기, 갈래 실행(의도 판단이 웹을 고르면 바로 웹, 여럿이면 동시에,
기한 하나 · 계획 순서가 정해지면 기다리지 않음, DB 에 없으면 웹), 사내 데이터 · 문서의 권한, 실시간 출처, 부분별 새로 가져오기(카드는 이름 키로,
권한이 없어지면 내용을 뺀다). LLM · 검색 · DB 는 모두 가짜다.

The widget data pipeline (2026-11-16; for the widget agent only): plan cleanup and the keyword rule, extraction (numbers not in the
material's body and addresses not in the material are dropped), name matching, running branches (the web at once when picked,
concurrently, one deadline, no waiting once plan order decides, the web when the company data has nothing), permissions, live
sources, and per-part refreshing (cards by their name key; a part whose permission is gone loses its content). The LLM, search and
DB are all fakes."""
import datetime as dt
import decimal
import json
import threading
import time
import unittest
from unittest.mock import patch

from app import catalog, kst, report_agent as ra, widget_data as wd


def at(*args):
    return patch.object(kst, "_clock", return_value=dt.datetime(*args, tzinfo=dt.timezone.utc))


class PlanTests(unittest.TestCase):
    def test_the_keyword_rule_picks_sources_views_and_a_clean_title(self):
        self.assertEqual(wd.rule_plan("오늘 원달러 환율")["sources"], ["web"])
        self.assertEqual(wd.rule_plan("연차 규정 요약")["sources"], ["docs"])
        self.assertEqual(wd.rule_plan("경쟁사 뉴스와 휴가 규정")["sources"], ["web", "docs"])
        self.assertEqual(wd.rule_plan("이번 달 매출")["sources"], ["data"])
        self.assertEqual([wd.rule_plan(t)["view"] for t in ("업계 뉴스", "휴가 규정 요약", "지점별 매출 추이", "이번 달 매출")],
                         ["list", "text", "chart", "kpi"])
        # 끝의 '위젯을 만들어줘' 같은 말은 제목에서 뺀다(3단계 검토) / trailing ask phrases leave the title (phase-3 review)
        self.assertEqual([wd.rule_plan(t)["title"] for t in ("오늘 원달러 환율 위젯을 만들어줘", "지점별 매출 차트를 보여줘", "환율")],
                         ["오늘 원달러 환율", "지점별 매출", "환율"])

    def test_the_intent_answer_is_cleaned_and_falls_back_to_the_rule(self):
        p = wd.clean_plan({"sources": ["web", "mail", "web", "docs"], "view": "kpi", "title": "가" * 30, "query": " 환율 ",
                           "labels": ["원달러", "", "엔화", "원달러", 7, "유로", "위안", "파운드"]}, "오늘 환율")
        self.assertEqual(p, {"sources": ["web", "docs"], "view": "kpi", "title": "가" * 20, "query": "환율",
                             "labels": ["원달러", "엔화", "유로", "위안"]})
        self.assertEqual(wd.clean_plan("garbage", "오늘 환율"), wd.rule_plan("오늘 환율"))
        self.assertEqual(wd.clean_plan({"sources": [], "view": "map", "labels": ["x"]}, "이번 달 매출")["sources"], ["data"])
        self.assertEqual(wd.clean_plan({"view": "list", "labels": ["x"]}, "뉴스")["labels"], [])   # 카드 이름은 kpi 일 때만 / labels for kpi only
        # 글자가 아닌 출처(목록 속 목록)는 버리고 낱말 규칙으로 — 예전에는 TypeError 로 도구가 실패했다(3단계 검토)
        # non-text sources are dropped and the keyword rule applies; this used to raise TypeError (phase-3 review)
        self.assertEqual(wd.clean_plan({"sources": [["web"], {"a": 1}]}, "오늘 원달러 환율")["sources"], ["web"])
        with patch.object(wd.llm, "generate", return_value={"sources": [["web"]], "view": "kpi"}):
            self.assertEqual(wd.plan_request("오늘 원달러 환율")["sources"], ["web"])
        with patch.object(wd.llm, "generate", side_effect=RuntimeError("down")):
            self.assertEqual(wd.plan_request("오늘 원달러 환율"), wd.rule_plan("오늘 원달러 환율"))


MATERIAL = "원달러 환율은 1,350.50원이고 엔화는 100엔당 905원이다. 기사: https://news.example/fx 2026-11-16 기준."


class ExtractTests(unittest.TestCase):
    def ask(self, out, view="kpi", labels=(), material=MATERIAL, facts=None):
        with patch.object(wd.llm, "generate", return_value=out):
            return wd.extract("환율", view, list(labels), material, facts)

    def test_numbers_are_kept_only_when_the_material_states_them(self):
        got = self.ask({"numbers": [{"label": "원달러", "value": "1350.5", "unit": "원", "note": "11/16"},
                                    {"label": "", "value": "905"},                             # 이름 없음 → 같은 자리 [카드 이름] / no name → the label at that position
                                    {"label": "유로", "value": "1480", "unit": "원"},          # 자료에 없다 / not in the material
                                    {"label": "", "value": "1350.5"},                          # 그 자리에 카드 이름이 없다 / no label at that position
                                    {"label": "원달러", "value": "905"}]}, labels=["달러", "엔화"])   # 같은 이름은 한 번 / a name once
        self.assertEqual(got, {"kind": "numbers", "numbers": [{"label": "원달러", "value": 1350.5, "unit": "원", "note": "11/16"},
                                                              {"label": "엔화", "value": 905.0, "unit": "", "note": ""}]})

    def test_dates_are_not_signed_numbers_and_markers_are_not_facts(self):
        # 3단계 검토: '2026-11-16' 을 2026 · -11 · -16 으로 읽어 "11월 16일" 요약을 버렸고, 표식([3] · p.3)의 숫자를 사실로 셌다
        # phase-3 review: '2026-11-16' read as 2026, -11 and -16 dropped a "11월 16일" summary, and marker numbers counted as facts
        self.assertEqual(wd._NUM.findall("2026-11-16 기준 -3.5% A-1"), ["2026", "11", "16", "-3.5", "1"])
        self.assertEqual(self.ask({"text": "11월 16일 기준 원달러는 1,350.50원입니다."}, view="text")["text"], "11월 16일 기준 원달러는 1,350.50원입니다.")
        material = "[3] (근태_규정.pdf, p.7)\n연차는 15일이다."
        got = self.ask({"numbers": [{"label": "연차", "value": "15", "unit": "일"}, {"label": "쪽", "value": "7"}, {"label": "번호", "value": "3"}]},
                       material=material, facts="연차는 15일이다.")
        self.assertEqual(got["numbers"], [{"label": "연차", "value": 15.0, "unit": "일", "note": ""}])

    def test_tables_items_and_text_are_checked_against_the_material(self):
        table = self.ask({"table": {"columns": ["통화", "원"], "rows": [["달러", "1,350.50"], ["유로", 1480], ["엔화", 905], ["", 1]]}}, view="chart")
        self.assertEqual(table, {"kind": "table", "table": {"columns": ["통화", "원"], "rows": [["달러", 1350.5], ["엔화", 905.0]]}})
        items = self.ask({"items": [{"title": "환율 기사", "sub": "11/16", "url": "https://news.example/fx"},
                                    {"title": "가짜", "url": "https://evil.example"}, {"title": " "}]}, view="list")
        self.assertEqual(items["items"], [{"title": "환율 기사", "sub": "11/16", "url": "https://news.example/fx"},
                                          {"title": "가짜", "sub": "", "url": ""}])
        self.assertEqual(self.ask({"text": "원달러는 1,350.50원입니다."}, view="text"), {"kind": "text", "text": "원달러는 1,350.50원입니다."})
        self.assertIsNone(self.ask({"text": "원달러는 1,400원입니다."}, view="text"))   # 자료에 없는 숫자가 든 요약 / an unstated number
        self.assertIsNone(self.ask({}, view="kpi"))
        self.assertEqual(self.ask({"text": "환율 정리"}, view="list")["kind"], "text")   # 모양의 내용이 비면 다른 내용으로 / another kind when empty
        with patch.object(wd.llm, "generate", side_effect=RuntimeError("down")):
            self.assertIsNone(wd.extract("환율", "kpi", [], MATERIAL))


USD = {"label": "1달러", "value": 1350.5, "aliases": ["USD", "미국 달러", "달러", "달러화"]}
JPY = {"label": "100엔", "value": 905.1, "aliases": ["JPY", "일본 엔", "엔", "엔화"]}


class MatchTests(unittest.TestCase):
    def test_names_pair_by_name_containment_then_alias_and_never_by_position(self):
        self.assertEqual(wd.match_numbers(["엔화", "원달러", "유가"], [USD, JPY]), {0: 1, 1: 0})   # 유가는 짝이 없다 / no match for 유가
        self.assertEqual(wd.match_numbers(["1달러", "달러"], [USD]), {0: 0})                      # 같은 이름이 먼저, 숫자는 한 번 / exact first, once
        self.assertEqual(wd.match_numbers(["매출 합계"], [{"label": "매출"}]), {0: 0})
        self.assertEqual(wd.match_numbers(["이익"], [{"label": "매출"}]), {})

    def test_number_columns_skip_periods_and_ids_and_columns_pair_by_name(self):
        types = {"연도": "number", "월": "number", "지점": "text", "매출": "number", "이익": "number", "고객_id": "number"}
        self.assertEqual(wd.number_columns(list(types), types), ["매출", "이익"])
        self.assertEqual(wd.number_columns(["연도"], {"연도": "number"}), ["연도"])   # 그것뿐이면 그대로 / kept when it is all there is
        self.assertEqual(wd.match_columns(["이익", "매출"], ["매출", "이익"]), {0: "이익", 1: "매출"})


class BranchTests(unittest.TestCase):
    def test_company_data_uses_the_report_agents_text2sql_and_cleans_db_values(self):
        rows = [[dt.date(2026, 1, 1), decimal.Decimal("12.50"), True, None, float("nan")]]
        with patch.object(ra, "query", return_value=(["월", "매출", "완료", "비고", "비고"], rows, "SELECT 1 FROM sales_branch_monthly")) as q, \
                patch.object(ra, "tables_in", return_value=["sales_branch_monthly"]):
            got = wd.run_data("월별 매출", None)
        q.assert_called_once_with("월별 매출" + wd.KO_ALIAS, None)   # 열 이름은 한국어 별칭으로 / Korean column aliases
        self.assertEqual(got["table"], {"tool": "inline", "columns": ["월", "매출", "완료", "비고", "비고_2"], "rows": [["2026-01-01", 12.5, "True", None, None]]})
        self.assertEqual((got["ok"], got["kind"], got["sql"], got["tables"], got["refs"], "note" in got),
                         (True, "table", "SELECT 1 FROM sales_branch_monthly", ["sales_branch_monthly"],
                          [{"kind": "data", "label": "지점별_월매출", "url": "", "page": None}], False))
        with patch.object(ra, "query", side_effect=ra.AgentError("데이터를 조회할 수 있는 테이블 권한이 없습니다")):
            self.assertEqual(wd.run_data("x", {"no": 7}), {"ok": False, "why": "데이터를 조회할 수 있는 테이블 권한이 없습니다"})
        with patch.object(ra, "query", return_value=(["a"], [], "SELECT")) as q:
            self.assertEqual(wd.run_data("x", None)["why"], "사내 데이터에서 찾지 못했습니다")
        self.assertEqual(q.call_count, 2)   # 빈 결과면 한 번만 더 / one more try on an empty result
        # 빈 결과 → 데이터에 있는 최근 기간으로 다시 묻고, 그랬다고 알린다 / asked again with the latest period, and the note says so
        answers = iter([(["지점", "매출"], [], "SELECT … WHERE month = '2026-11'"), (["지점", "매출"], [["서울", 5]], "SELECT … MAX(month)")])
        with patch.object(ra, "query", side_effect=lambda q, e: next(answers)) as q, patch.object(ra, "tables_in", return_value=[]):
            got = wd.run_data("이번 달 지점별 매출", None)
        self.assertEqual((got["sql"], got["table"]["rows"], got["note"]), ("SELECT … MAX(month)", [["서울", 5]], wd.RETRY_NOTE))
        self.assertEqual(q.call_args_list[1].args[0], "이번 달 지점별 매출" + wd.KO_ALIAS + wd.RETRY_EMPTY)

    def test_reference_names_only_come_from_workspaces_the_identity_can_read(self):
        # 3단계 검토: 근거 이름이 권한 없는 워크스페이스의 데이터 이름을 보였다 / references showed a dataset name from an unreadable workspace
        node = catalog.data_locate(table="sales_branch_monthly")["node"]
        self.assertEqual(wd._table_label("sales_branch_monthly", None), "지점별_월매출")
        self.assertEqual(wd._table_label("sales_branch_monthly", {"nodes": {node: 1}}), "지점별_월매출")
        self.assertEqual(wd._table_label("sales_branch_monthly", {"nodes": {}}), "sales_branch_monthly")
        self.assertEqual(wd._table_label("made_up", None), "made_up")

    def test_company_documents_respect_permissions_and_check_numbers_in_bodies_only(self):
        hits = [{"doc": "근태_취업규칙.pdf", "page": 3, "text": "연차는 15일이다.", "similarity": 0.8},
                {"doc": "임원규정.pdf", "page": 1, "text": "임원 연차는 25일이다.", "similarity": 0.9},
                {"doc": "근태_취업규칙.pdf", "page": 4, "text": "약한 근거", "similarity": 0.01}]
        with patch.object(wd.catalog, "domain_readable", return_value=False):
            self.assertEqual(wd.run_docs("연차", {"no": 7}, "text", []), {"ok": False, "why": "사내 문서를 볼 권한이 없습니다", "denied": True})
        seen = {}

        def fake_extract(query, view, labels, material, facts=None):
            seen.update(material=material, facts=facts)
            return {"kind": "text", "text": "연차는 15일이다."}
        with patch.object(wd.catalog, "domain_readable", return_value=True), \
                patch.object(wd.catalog, "allowed_knowledge_files", return_value={"근태_취업규칙.pdf"}), \
                patch.object(wd.kb, "search", return_value=hits), patch.object(wd, "extract", side_effect=fake_extract):
            got = wd.run_docs("연차", {"no": 7}, "text", [])
        self.assertNotIn("임원", seen["material"])          # 허용되지 않은 문서는 자료에도 없다 / an unallowed file never reaches the material
        self.assertNotIn("약한 근거", seen["material"])
        self.assertIn("(근태_취업규칙.pdf, p.3)", seen["material"])
        self.assertEqual(seen["facts"], "연차는 15일이다.")   # 숫자는 본문에서만 / numbers from the bodies only
        self.assertEqual(got, {"ok": True, "kind": "text", "text": "연차는 15일이다.",
                               "refs": [{"kind": "doc", "label": "근태_취업규칙.pdf", "url": "", "page": 3}]})

    def test_the_web_branch_uses_grounded_search_and_never_model_knowledge(self):
        meta = {"text": MATERIAL, "sources": [{"title": "news.example", "url": "https://news.example/fx"}, {"title": "x", "url": "ftp://x"}]}
        seen = {}

        def fake_extract(query, view, labels, material, facts=None):
            seen.update(facts=facts)
            return {"kind": "items", "items": [{"title": "업계 소식", "sub": "", "url": ""}]}
        with patch.object(wd.llm, "generate_grounded_meta", return_value=meta), patch.object(wd, "extract", side_effect=fake_extract):
            got = wd.run_web("반도체 업계 뉴스", "list", [])
        self.assertEqual(seen["facts"], MATERIAL)   # 출처 목록의 숫자는 사실이 아니다 / numbers in the source list are not facts
        self.assertEqual(got["refs"], [{"kind": "web", "label": "news.example", "url": "https://news.example/fx", "page": None},
                                       {"kind": "web", "label": "x", "url": "", "page": None}])
        with patch.object(wd.llm, "generate_grounded_meta", side_effect=wd.llm.GroundingUnavailableError("off")), patch.object(wd.llm, "generate") as plain:
            self.assertEqual(wd.run_web("반도체 업계 뉴스", "list", []), {"ok": False, "why": "웹 검색을 쓸 수 없습니다"})
        plain.assert_not_called()

    def test_rates_and_weather_come_from_the_live_sources_first(self):
        from app import live_fx, live_weather

        def quote(base, quote_ccy="KRW", amount=None):
            if base == "EUR":
                raise live_fx.FxError("no quote")
            unit = live_fx.CURRENCIES[base][4]
            return {"base": {"code": base, "amount": float(unit)}, "quote": {"code": "KRW", "amount": {"USD": 1350.456, "JPY": 905.1}[base]},
                    "as_of": "2026-11-16T14:05:00+09:00"}
        with patch.object(live_fx, "quote", side_effect=quote), patch.object(live_fx, "text", side_effect=lambda c: f"{c['base']['code']} 문장\n기준"), \
                patch.object(wd.llm, "generate_grounded_meta") as grounded:
            nums = wd.run_web("오늘 원달러 · 엔화 · 유로 환율", "kpi", ["매매기준율", "전일대비"])
            chart = wd.run_web("원달러 엔화 환율 비교", "chart", [])
            text = wd.run_web("원달러 환율", "text", [])
            lst = wd.run_web("엔화 환율", "list", [])
            one = wd.run_web("환율 위젯", "kpi", [])
        grounded.assert_not_called()   # 실시간 출처가 있으면 검색하지 않는다 / no search when a live source answers
        yahoo = [{"kind": "web", "label": "Yahoo Finance", "url": live_fx.SOURCE["url"], "page": None}]
        self.assertEqual(nums, {"ok": True, "kind": "numbers", "refs": yahoo, "numbers": [   # 받지 못한 유로는 빠진다 / the failed EUR is skipped
            {"label": "1달러", "value": 1350.46, "unit": "원", "note": "11/16 14:05 기준", "aliases": ["USD", "미국 달러", "달러", "달러화"]},
            {"label": "100엔", "value": 905.1, "unit": "원", "note": "11/16 14:05 기준", "aliases": ["JPY", "일본 엔", "엔", "엔화"]}],
            "live": True})   # 실시간 출처 표시(2026-11-19 진행 줄) / marked live (the 2026-11-19 progress lines)
        self.assertEqual(chart["table"], {"tool": "inline", "columns": ["통화", "원"], "rows": [["1달러", 1350.46], ["100엔", 905.1]]})
        self.assertEqual((text["kind"], text["text"]), ("text", "USD 문장 기준"))
        self.assertEqual(lst["items"], [{"title": "100엔 = 905.10원", "sub": "11/16 14:05 기준 · Yahoo Finance", "url": live_fx.SOURCE["url"]}])
        self.assertEqual(one["numbers"][0]["label"], "1달러")   # 통화를 말하지 않으면 달러 / USD when no currency is named
        facts = {"location": "부산", "now": {"temp": 13, "sky": "맑음"},
                 "days": [{"day": "일", "date": "2026-11-16", "sky": "맑음", "max": 17, "min": 9, "rain_chance": 10},
                          {"day": "월", "date": "2026-11-17", "sky": "비", "max": 15, "min": 8, "rain_chance": None}]}
        with patch.object(live_weather, "get", return_value=({}, True)) as get, patch.object(live_weather, "facts", return_value=facts), \
                patch.object(live_weather, "template", return_value="부산은 맑습니다."):
            wx = wd.run_web("부산 날씨", "kpi", [])
            week = wd.run_web("부산 이번 주 날씨", "list", [])
            temps = wd.run_web("부산 주간 기온 추이", "chart", [])
            said = wd.run_web("부산 날씨 요약", "text", [])
        self.assertEqual(get.call_args_list[0].args, ("부산", 0))
        self.assertEqual([(n["label"], n["value"], n["unit"]) for n in wx["numbers"]],
                         [("지금 기온", 13, "°C"), ("최고", 17, "°C"), ("최저", 9, "°C"), ("강수 확률", 10, "%")])
        self.assertEqual((wx["numbers"][0]["note"], wx["numbers"][0]["aliases"]), ("부산 · 맑음", ["지금", "현재", "기온", "온도"]))
        self.assertEqual(week["items"][1], {"title": "11-17(월) 비", "sub": "최고 15° · 최저 8°", "url": ""})
        self.assertEqual(temps["table"]["rows"], [["11-16(일)", 17, 9], ["11-17(월)", 15, 8]])
        self.assertEqual((said["text"], said["refs"][0]["label"]), ("부산은 맑습니다.", "Open-Meteo"))
        # 실시간 출처가 실패하면 그라운딩으로, 그것도 못 쓰면 실시간 출처의 까닭 / a failed live source falls to grounding, then reports its reason
        with patch.object(live_fx, "quote", side_effect=live_fx.FxError("down")), \
                patch.object(wd.llm, "generate_grounded_meta", side_effect=wd.llm.GroundingUnavailableError("off")):
            self.assertEqual(wd.run_web("원달러 환율", "kpi", []), {"ok": False, "why": "환율 시세를 받지 못했습니다"})
        with patch.object(live_weather, "get", side_effect=RuntimeError("down")), \
                patch.object(wd.llm, "generate_grounded_meta", return_value={"text": "서울 12도", "sources": []}), \
                patch.object(wd, "extract", return_value={"kind": "text", "text": "서울 12도"}):
            self.assertEqual(wd.run_web("서울 날씨", "text", [])["text"], "서울 12도")

    def test_document_like_requests_never_take_live_values(self):
        # 3단계 검토: "출장비 정산 시 적용 환율 규정 요약" 이 오늘 달러 환율 글이 됐다 / a rate-policy request became today's USD rate
        from app import live_fx
        self.assertIsNone(wd.run_live("해외 출장비 정산 시 적용 환율 규정 요약", "text"))
        with patch.object(live_fx, "quote") as quote, patch.object(wd.llm, "generate_grounded_meta", side_effect=wd.llm.GroundingUnavailableError("off")):
            self.assertEqual(wd.run_web("해외 출장비 정산 시 적용 환율 규정 요약", "text", []), {"ok": False, "why": "웹 검색을 쓸 수 없습니다"})
        quote.assert_not_called()

    def test_fetched_tables_stay_under_the_definition_cap(self):
        # 3단계 검토: 200줄 × 290자 두 칸이 정의 상한(10만 자)을 넘겨 턴을 잃었다 → 표를 6만 자 안으로 / tables are kept under 60k characters
        t = wd.table_source(["이름", "메모", "설명"], [[f"항목{i}", "가" * 290, "나" * 290] for i in range(200)])
        self.assertLessEqual(len(json.dumps({"columns": t["columns"], "rows": t["rows"]}, ensure_ascii=False)), wd.MAX_TABLE_CHARS)
        self.assertGreater(len(t["rows"]), 50)
        self.assertEqual(t["rows"][0][0], "항목0")   # 앞쪽 줄을 남긴다 / the leading rows stay


def plan_of(*sources, view="kpi"):
    return {"sources": list(sources), "view": view, "title": "제목", "query": "질의", "labels": []}


class FetchTests(unittest.TestCase):
    def run_fetch(self, plan, results, **kw):
        calls, events = [], []

        def branch(src, p, eff):
            calls.append(src)
            r = results[src]
            if isinstance(r, Exception):
                raise r
            return r
        with patch.object(wd, "plan_request", return_value=plan), patch.object(wd, "_branch", side_effect=branch), \
                patch.object(wd, "run_web", side_effect=lambda *a: results["web"]):
            out = wd.fetch("요청", {"no": 7}, emit=lambda k, d: events.append((k, d)), **kw)
        return out, calls, events

    def test_the_plan_order_decides_and_the_plan_is_announced_first(self):
        found = {"ok": True, "kind": "text", "text": "x", "refs": []}
        out, calls, events = self.run_fetch(plan_of("web", "data"), {"web": found, "data": {"ok": True, "kind": "table"}})
        self.assertEqual(out["origin"], "web")   # 웹을 고르면 바로 웹(사내를 기다리지 않는다) / the web runs at once
        self.assertEqual([k for k, _ in events][:3], ["plan", "stage", "stage"])
        out, _, _ = self.run_fetch(plan_of("data", "web"), {"web": found, "data": {"ok": False, "why": "없음"}})
        self.assertEqual((out["origin"], out["tried"]), ("web", {"data": "없음"}))

    def test_nothing_in_the_company_data_means_the_web(self):
        web = {"ok": True, "kind": "numbers", "numbers": [], "refs": []}
        out, calls, events = self.run_fetch(plan_of("data"), {"data": {"ok": False, "why": "사내 데이터에서 찾지 못했습니다"}, "web": web})
        self.assertEqual((out["origin"], calls), ("web", ["data"]))
        self.assertIn(("stage", {"source": "web", "label": "웹 검색", "fallback": True}), events)
        out, _, _ = self.run_fetch(plan_of("docs"), {"docs": {"ok": False, "why": "a"}, "web": {"ok": False, "why": "b"}})
        self.assertEqual((out["origin"], out["result"], out["tried"]), (None, None, {"docs": "a", "web": "b"}))
        out, _, _ = self.run_fetch(plan_of("data"), {"data": RuntimeError("boom"), "web": {"ok": False, "why": "b"}})
        self.assertEqual(out["tried"]["data"], "사내 데이터에서 가져오지 못했습니다")

    def test_several_branches_run_at_the_same_time(self):
        started, gate = [], threading.Event()

        def slow(src, p, eff):
            started.append(src)
            if len(started) == 2:
                gate.set()
            gate.wait(2)   # 다른 갈래가 시작해야 풀린다 — 차례로 돌면 2초를 기다린다 / released only when the other branch starts
            return {"ok": src == "docs", "why": "x", "kind": "text", "text": "t", "refs": []}
        with patch.object(wd, "plan_request", return_value=plan_of("data", "docs")), patch.object(wd, "_branch", side_effect=slow):
            t0 = time.monotonic()
            out = wd.fetch("요청", None)
        self.assertLess(time.monotonic() - t0, 1.5)
        self.assertEqual(out["origin"], "docs")

    def test_one_deadline_and_no_waiting_once_plan_order_decides(self):
        # 3단계 검토: 갈래마다 기다려 0.5초 한도에 3초 갈래가 3초를 잡았고, 웹이 이미 이겼는데도 사내 갈래를 기다렸다
        # phase-3 review: per-branch waits let a 3 s branch hold a 0.5 s limit, and a decided web result still waited for data
        release = threading.Event()
        self.addCleanup(release.set)

        def branch(src, p, eff):
            if src == "web":
                return {"ok": True, "kind": "text", "text": "t", "refs": []}
            release.wait(5)
            return {"ok": True, "kind": "table"}
        with patch.object(wd, "plan_request", return_value=plan_of("web", "data")), patch.object(wd, "_branch", side_effect=branch):
            t0 = time.monotonic()
            out = wd.fetch("요청", None)
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertEqual(out["origin"], "web")
        with patch.object(wd, "BRANCH_TIMEOUT", 0.3), patch.object(wd, "plan_request", return_value=plan_of("data", "docs")), \
                patch.object(wd, "_branch", side_effect=lambda src, p, eff: release.wait(5) and {"ok": False, "why": "늦음"}), \
                patch.object(wd, "run_web", return_value={"ok": False, "why": "웹 없음"}):
            t0 = time.monotonic()
            out = wd.fetch("요청", None)
        self.assertLess(time.monotonic() - t0, 1.5)
        self.assertEqual(out["tried"], {"data": "사내 데이터 응답이 늦어 건너뛰었습니다", "docs": "사내 문서 응답이 늦어 건너뛰었습니다", "web": "웹 없음"})

    def test_a_given_view_overrides_the_plan(self):
        out, _, events = self.run_fetch(plan_of("web", view="kpi") | {"labels": ["원달러"]}, {"web": {"ok": True, "kind": "items", "items": [], "refs": []}}, view="list")
        self.assertEqual((out["plan"]["view"], out["plan"]["labels"]), ("list", []))


def cards_spec(kpis, cards, **origin):
    """고정 숫자 카드 + 카드 출처 하나 / fixed cards with one cards origin"""
    return {"v": 2, "title": "환율", "source": None, "chart": None, "theme": None, "insight": "", "blocks": [],
            "kpis": [{"id": f"k{i + 1}", "label": label, "value": value, "unit": "원", "note": "", "source": "", "col": "", "agg": "", "link": "", "delta": ""}
                     for i, (label, value) in enumerate(kpis)],
            "origins": [{"part": "cards", "kind": "web", "query": "환율", "view": "kpi", "sql": "", "sig": "", "tables": [], "refs": [],
                         "fetched_at": "2026-11-16T09:00:00", "cards": cards, **origin}]}


class RefreshTests(unittest.TestCase):
    def test_due_times_per_origin(self):
        o = lambda kind, **kw: {"part": "source" if kind == "data" else "text", "kind": kind, "query": "q", "sql": "SELECT 1" if kind == "data" else "",
                                "fetched_at": "2026-11-16T09:00:00", **kw}
        with at(2026, 11, 16, 0, 30):   # = 09:30 KST
            self.assertTrue(wd.stale(o("web")))          # 30분 / 30 minutes
            self.assertFalse(wd.stale(o("docs")))        # 6시간 / 6 hours
            self.assertTrue(wd.stale(o("data")))         # 1분 / 1 minute
            self.assertFalse(wd.stale(o("data", sql="")))   # 서명된 SQL 이 없는 표는 다시 가져오지 않는다 / no signed SQL, no refresh
            self.assertFalse(wd.stale(None))
            self.assertFalse(wd.stale(o("web", query="")))
            self.assertTrue(wd.stale(o("web", fetched_at="?")))
            self.assertTrue(wd.stale(o("web", fetched_at="2026-11-16T09:00:00+09:00")))   # 시간대가 붙은 값도 한 번 다시 / an aware time refreshes once
            self.assertEqual((wd.due({"origins": [o("docs")]}), wd.due({"origins": [o("docs"), o("web")]}), wd.due({})), (False, True, False))
            self.assertIsNone(wd.refresh({"origins": [o("docs")]}, None))

    def test_cards_refresh_by_their_name_never_by_position(self):
        # 3단계 검토: 순서로 짝지어 카드 순서를 바꾸거나 한 통화가 빠지면 엉뚱한 카드에 숫자가 들어갔다
        # phase-3 review: positional pairing put numbers under the wrong cards after a reorder or a missing currency
        spec = cards_spec([("1유로", 1500), ("1달러", 1300), ("100엔", 900)],
                          [{"id": "k1", "key": "1유로"}, {"id": "k2", "key": "1달러"}, {"id": "k3", "key": "100엔"}])
        fresh = {"ok": True, "kind": "numbers", "refs": [{"kind": "web", "label": "Yahoo Finance"}],
                 "numbers": [{**USD, "unit": "원", "note": "11/16 10:00 기준"}, {**JPY, "unit": "원", "note": "11/16 10:00 기준"}]}   # 유로는 받지 못했다 / no EUR
        with at(2026, 11, 16, 1, 0), patch.object(wd, "run_web", return_value=fresh) as web:
            new = wd.refresh(spec, None)
        web.assert_called_once_with("환율", "kpi", ["1유로", "1달러", "100엔"])
        self.assertEqual([(k["label"], k["value"]) for k in new["kpis"]], [("1유로", 1500), ("1달러", 1350.5), ("100엔", 905.1)])
        self.assertEqual((new["origins"][0]["fetched_at"], new["origins"][0]["refs"]), ("2026-11-16T10:00:00", [{"kind": "web", "label": "Yahoo Finance"}]))
        # 데이터 카드로 바뀐 카드 · 없어진 카드는 건드리지 않는다 / a card turned computed or gone is left alone
        turned = {**spec, "kpis": [{**spec["kpis"][0]}, {**spec["kpis"][1], "source": "s1", "col": "매출"}, spec["kpis"][2]]}
        with at(2026, 11, 16, 1, 0), patch.object(wd, "run_web", return_value=fresh):
            new = wd.refresh(turned, None)
        self.assertEqual([k.get("value") for k in new["kpis"]], [1500, 1300, 905.1])
        with at(2026, 11, 16, 1, 0), patch.object(wd, "run_web", return_value={**fresh, "numbers": [{"label": "1파운드", "value": 1, "unit": "", "note": ""}]}):
            self.assertIsNone(wd.refresh(spec, None))   # 맞는 숫자가 하나도 없으면 그대로 / nothing matched, nothing changes

    def test_text_and_list_blocks_follow_new_content(self):
        spec = {"v": 2, "title": "t", "source": None, "chart": None, "kpis": [], "theme": None, "insight": "",
                "blocks": [{"type": "text", "text": "옛 요약"}],
                "origins": [{"part": "text", "kind": "web", "query": "q", "view": "text", "sql": "", "sig": "", "tables": [], "refs": [],
                             "fetched_at": "2026-11-16T09:00:00", "cards": []},
                            {"part": "list", "kind": "web", "query": "뉴스", "view": "list", "sql": "", "sig": "", "tables": [], "refs": [],
                             "fetched_at": "2026-11-16T09:00:00", "cards": []}]}
        def web(query, view, labels):
            return ({"ok": True, "kind": "text", "text": "새 요약", "refs": []} if view == "text"
                    else {"ok": True, "kind": "items", "items": [{"title": "새 소식", "sub": "", "url": ""}], "refs": []})
        with at(2026, 11, 16, 1, 0), patch.object(wd, "run_web", side_effect=web):
            new = wd.refresh(spec, None)
        self.assertEqual(new["blocks"], [{"type": "text", "text": "새 요약"}, {"type": "list", "items": [{"title": "새 소식", "sub": "", "url": ""}]}])
        with at(2026, 11, 16, 1, 0), patch.object(wd, "run_web", side_effect=[RuntimeError("down"), {"ok": True, "kind": "items", "items": [{"title": "a"}], "refs": []}]):
            new = wd.refresh(spec, None)   # 한 부분의 실패가 다른 부분을 막지 않는다 / one failed part never blocks another
        self.assertEqual([b["type"] for b in new["blocks"]], ["text", "list"])
        self.assertEqual([o["fetched_at"] for o in new["origins"]], ["2026-11-16T09:00:00", "2026-11-16T10:00:00"])

    def test_company_data_reruns_the_signed_sql_under_todays_permissions(self):
        from app import analytics
        spec = {"v": 2, "title": "t", "source": {"tool": "inline", "columns": ["월", "매출"], "rows": [["2026-01", 1]]}, "chart": None, "kpis": [],
                "theme": None, "insight": "", "blocks": [],
                "origins": [{"part": "source", "kind": "data", "query": "q", "view": "chart", "sql": "SELECT 월, 매출 FROM sales", "sig": "s",
                             "tables": ["sales"], "refs": [], "fetched_at": "2026-11-16T09:00:00", "cards": []}]}
        with at(2026, 11, 16, 1, 0), patch.object(analytics, "refresh_csv_views"), patch.object(analytics, "guard_sql", side_effect=lambda s, a: s), \
                patch.object(analytics, "run_select", return_value=(["월", "매출"], [["2026-01", 5], ["2026-02", 6]])) as run:
            new = wd.refresh(spec, None)
        run.assert_called_once_with("SELECT 월, 매출 FROM sales", None)
        self.assertEqual(new["source"]["rows"], [["2026-01", 5], ["2026-02", 6]])
        with at(2026, 11, 16, 1, 0), patch.object(analytics, "refresh_csv_views"), patch.object(analytics, "guard_sql", side_effect=lambda s, a: s), \
                patch.object(analytics, "run_select", return_value=(["월", "이익"], [["2026-01", 5]])):
            self.assertIsNone(wd.refresh(spec, None))   # 열이 바뀌면 그대로 / changed columns keep the old table
        # 권한이 없어지면 표의 줄을 뺀다(출처는 남아 권한이 돌아오면 다시 채운다) / without permission the rows go; access back refills them
        with at(2026, 11, 16, 1, 0), patch.object(wd.catalog, "domain_readable", return_value=True), \
                patch.object(wd.ra, "allowed_tables", return_value={"other"}), patch.object(wd.ra, "tables_in", return_value=["sales"]):
            new = wd.refresh(spec, {"no": 7})
        self.assertEqual((new["source"]["columns"], new["source"]["rows"], new["origins"][0]["fetched_at"]), (["월", "매출"], [], "2026-11-16T10:00:00"))

    def test_documents_withheld_when_permission_is_gone_and_back_when_it_returns(self):
        spec = {**cards_spec([("연차", 15)], [{"id": "k1", "key": "연차"}], kind="docs"), "blocks": [{"type": "text", "text": "연차는 15일"}]}
        spec["origins"].append({"part": "text", "kind": "docs", "query": "연차 규정", "view": "text", "sql": "", "sig": "", "tables": [], "refs": [],
                                "fetched_at": "2026-11-16T09:00:00", "cards": []})
        later = dt.datetime(2026, 11, 16, 9, 0) + dt.timedelta(hours=7)
        with patch.object(kst, "_clock", return_value=(later - dt.timedelta(hours=9)).replace(tzinfo=dt.timezone.utc)), \
                patch.object(wd.catalog, "domain_readable", return_value=False):
            gone = wd.refresh(spec, {"no": 7})
        self.assertEqual((gone["kpis"][0].get("pending"), "value" in gone["kpis"][0], gone["blocks"]), (True, False, []))
        back = {"ok": True, "kind": "numbers", "numbers": [{"label": "연차", "value": 15, "unit": "일", "note": ""}], "refs": []}
        text = {"ok": True, "kind": "text", "text": "연차는 15일", "refs": []}
        with patch.object(kst, "_clock", return_value=(later + dt.timedelta(hours=7) - dt.timedelta(hours=9)).replace(tzinfo=dt.timezone.utc)), \
                patch.object(wd, "run_docs", side_effect=lambda q, e, view, labels: back if view == "kpi" else text):
            again = wd.refresh(gone, {"no": 7})
        self.assertEqual((again["kpis"][0]["value"], "pending" in again["kpis"][0], again["blocks"]), (15, False, [{"type": "text", "text": "연차는 15일"}]))


class FetchEventsTests(unittest.TestCase):
    """2026-11-19 대화 화면 2차: 갈래마다 branch(끝나는 대로) · 쓴 갈래 picked · 사용자가 고른 곳 · 멈춤 · 지금 새로 가져오기(force)
    chat round 2 (2026-11-19): branch per branch as it ends, picked, the chosen place, stopping, refreshing now (force)"""

    def test_branches_are_announced_as_they_finish_and_the_used_one_is_named(self):
        def branch(src, plan, eff):
            if src == "data":
                return {"ok": False, "why": "사내 데이터에서 찾지 못했습니다"}
            return {"ok": True, "kind": "text", "text": "연차 15일", "refs": [{"kind": "doc", "label": "취업규칙.pdf", "url": "", "page": 5},
                                                                            {"kind": "web", "label": "x", "url": "javascript:alert(1)", "page": True}]}
        events = []
        with patch.object(wd, "_branch", side_effect=branch):
            out = wd.fetch("연차", None, emit=lambda k, d: events.append((k, d)), plan=plan_of("data", "docs", view="text"))
        self.assertEqual(events[0], ("plan", {**plan_of("data", "docs", view="text"), "forced": False}))
        self.assertEqual([k for k, _ in events].count("stage"), 2)
        branches = {d["source"]: d for k, d in events if k == "branch"}
        self.assertEqual(branches["data"], {"source": "data", "label": "사내 데이터", "ok": False, "why": "사내 데이터에서 찾지 못했습니다"})
        # 주소는 http(s) 만, 쪽은 정수만 / http(s) links and integer pages only
        self.assertEqual(branches["docs"], {"source": "docs", "label": "사내 문서", "ok": True, "kind": "text",
                                            "refs": [{"kind": "doc", "label": "취업규칙.pdf", "page": 5, "url": ""},
                                                     {"kind": "web", "label": "x", "page": None, "url": ""}]})
        self.assertEqual(events[-1], ("picked", {"source": "docs"}))
        self.assertEqual(out["origin"], "docs")

    def test_branch_notes_carry_rows_sql_counts_and_live(self):
        table = {"tool": "inline", "columns": ["지점", "매출"], "rows": [["강남", 1], ["광주", 2]]}
        self.assertEqual(wd.branch_note("data", {"ok": True, "kind": "table", "table": table, "sql": " SELECT 1 ", "refs": [], "note": wd.RETRY_NOTE}),
                         {"source": "data", "label": "사내 데이터", "ok": True, "kind": "table", "refs": [], "rows": 2, "columns": ["지점", "매출"],
                          "sql": "SELECT 1", "note": wd.RETRY_NOTE})
        self.assertEqual(wd.branch_note("web", {"ok": True, "kind": "numbers", "numbers": [1, 2], "refs": [], "live": True}),
                         {"source": "web", "label": "웹 검색", "ok": True, "kind": "numbers", "refs": [], "count": 2, "live": True})
        self.assertEqual(wd.branch_note("docs", {"ok": False}), {"source": "docs", "label": "사내 문서", "ok": False, "why": "사내 문서에서 찾지 못했습니다"})
        self.assertNotIn("sql", wd.branch_note("web", {"ok": True, "kind": "text", "text": "a", "sql": "SELECT 1"}))   # SQL 은 사내 데이터만 / data only

    def test_a_chosen_place_is_the_only_place_and_never_falls_back_to_the_web(self):
        calls, events = [], []

        def branch(src, plan, eff):
            calls.append(src)
            return {"ok": False, "why": "사내 데이터에서 찾지 못했습니다"}
        with patch.object(wd, "_branch", side_effect=branch), patch.object(wd, "run_web") as web:
            out = wd.fetch("매출", None, emit=lambda k, d: events.append((k, d)), plan=plan_of("web", "docs"), sources=["data", "zzz", "data"])
        web.assert_not_called()
        self.assertEqual((calls, out["origin"], out["plan"]["sources"]), (["data"], None, ["data"]))
        self.assertEqual(events[0][1]["forced"], True)
        self.assertEqual(events[-1], ("picked", {"source": None}))
        # 사내(사내 데이터 + 사내 문서) = 의도 판단이 고른 곳 중 사내만, 없으면 사내 모두 / internal: the planned internal places, else both
        calls.clear()
        with patch.object(wd, "_branch", side_effect=branch), patch.object(wd, "run_web") as web:
            wd.fetch("규정", None, plan=plan_of("web", "docs"), sources=["data", "docs"])
            wd.fetch("환율", None, plan=plan_of("web"), sources=["docs", "data"])
        web.assert_not_called()
        self.assertEqual((calls[0], sorted(calls[1:])), ("docs", ["data", "docs"]))   # 둘째는 동시에 돈다 / the second runs both at once

    def test_a_branch_left_behind_by_an_earlier_find_says_it_was_not_awaited(self):
        gate = threading.Event()
        self.addCleanup(gate.set)

        def branch(src, plan, eff):
            if src == "web":
                gate.wait(5)
                return {"ok": False, "why": "늦음"}
            return {"ok": True, "kind": "text", "text": "규정", "refs": []}
        events = []
        with patch.object(wd, "_branch", side_effect=branch):
            out = wd.fetch("규정", None, emit=lambda k, d: events.append((k, d)), plan=plan_of("docs", "web", view="text"))
        self.assertEqual(out["origin"], "docs")
        web = [d for k, d in events if k == "branch" and d["source"] == "web"][0]
        self.assertEqual(web, {"source": "web", "label": "웹 검색", "ok": False, "why": "다른 곳에서 찾아 기다리지 않았습니다", "skipped": True})

    def test_a_stop_ends_the_wait_with_cancelled(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        checks = []

        def stop():
            checks.append(1)
            return len(checks) > 2   # 처음 두 번은 아니고 그 뒤로 멈춤 / not at first, then stopped

        def slow(src, plan, eff):
            gate.wait(5)
            return {"ok": False, "why": "x"}
        t0 = time.monotonic()
        with patch.object(wd, "_branch", side_effect=slow), self.assertRaises(wd.Cancelled):
            wd.fetch("x", None, plan=plan_of("data"), cancel=stop)
        self.assertLess(time.monotonic() - t0, 3)
        with self.assertRaises(wd.Cancelled):   # 의도 판단 바로 뒤에서도 / right after the plan too
            wd.fetch("x", None, plan=plan_of("data"), cancel=lambda: True)

    def test_force_refreshes_origins_that_are_not_due_yet(self):
        spec = {"v": 2, "title": "연차", "blocks": [{"type": "text", "text": "15일"}],
                "origins": [{"part": "text", "kind": "docs", "query": "연차", "view": "text", "sql": "", "sig": "", "tables": [], "refs": [],
                             "fetched_at": kst.now_iso(), "cards": []},
                            {"part": "list", "kind": "web", "query": "", "view": "list", "sql": "", "sig": "", "tables": [], "refs": [],
                             "fetched_at": kst.now_iso(), "cards": []}]}
        with patch.object(wd, "_refresh_part", return_value="ok") as part:
            self.assertIsNone(wd.refresh(spec, None))            # 때가 아니면 / not due
            new = wd.refresh(spec, None, force=True)
        self.assertEqual(part.call_count, 1)                     # 질의 없는 출처는 다시 가져올 수 없다 / an origin without a query cannot refresh
        self.assertIsNotNone(new)


if __name__ == "__main__":
    unittest.main()
