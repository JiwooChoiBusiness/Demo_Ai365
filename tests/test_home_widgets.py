# -*- coding: utf-8 -*-
"""홈 대시보드 배치 · 만든 위젯(2026-11-13 1단계, 2026-11-16 위젯 에이전트, 2026-11-17 4단계 격자 — 계약 = docs/widget-agent.md):
격자 배치 정규화(읽기 · 저장 · 옛 세 열 형식 · 위젯 크기 최소 · 최대 · 겹침 풀기), 위젯 정의 v2(리포트 에이전트 모양: 데이터 · 차트 · KPI 카드 · 테마 · 인사이트 틀) 검사, 표시 모델(리포트 에이전트의 계산),
데이터가 바뀌면 같이 바뀌는 인사이트(변수 · 조사), 저장소(사람별 분리 · 30개 상한 · 지우면 배치에서도 빠짐), /api/home 왕복, main.py
연결(/home 의 스크립트 주입). 임시 DB 만 쓰고 LLM · 네트워크 · 실 DB 는 없다. app.main 은 들여오지 않는다(실 DB 정비).

Home dashboard layout and made widgets (phase 1 on 2026-11-13, the widget agent on 2026-11-16, the phase-4 grid on 2026-11-17;
contract = docs/widget-agent.md): grid layout normalization (read, save, the older column shape, widget size limits, overlap
resolution), definition v2 checks (the report agent's shape: data, chart,
KPI cards, theme, insight template), the display model (the report agent's math), insights that follow the data
(variables and particles), the store (per-owner separation, the 30 cap, deleting strips the layout), the /api/home round
trip and the main.py wiring (the /home script injection). Temp DB only; no LLM, network or real DB, and app.main is never
imported (it repairs the real DB)."""
import ast
import json
import re
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from app import db, home_widgets as hw, home_widgets_api, kst, report_dash as rd, widget_data
from tests.db_fixture import isolate_db

ROOT = Path(__file__).resolve().parent.parent
KNOWN = set(hw.BUILTIN_KEYS)

# 월별 매출(기간 축: 2026-01 ~ 2026-04) / monthly sales on a period axis
MONTHLY = {"tool": "inline", "columns": ["월", "매출", "지점"],
           "rows": [["2026-01", 120, "서울"], ["2026-02", 150, "부산"], ["2026-03", 90, "서울"], ["2026-04", 180, "울산"]]}
CHART_SPEC = {"v": 2, "title": "월별 매출", "source": MONTHLY, "chart": {"type": "bar", "x": "월", "y": [{"col": "매출"}]}}


def kpi_spec(title="목표", value=1200, unit="건"):
    """고정 숫자 KPI 카드 하나짜리 위젯 / a widget with one fixed-number KPI card"""
    return {"v": 2, "title": title, "kpis": [{"label": "연간 목표", "value": value, "unit": unit}]}


def chart_spec(**chart):
    return {"v": 2, "title": "월별 매출", "source": MONTHLY, "chart": {"type": "bar", "x": "월", "y": [{"col": "매출"}], **chart}}


def with_source(**source):
    return {"v": 2, "title": "표", "source": {"tool": "inline", "columns": ["a"], "rows": [], **source}, "kpis": [{"label": "k", "value": 1}]}


SIZES = {k: hw.size_of(k) for k in hw.BUILTIN_KEYS}
# 지금 홈과 같은 기본 배치를 격자 차례(y · x)로 / the default layout in grid order (y, x)
DEFAULT_ROWS = ["wx 0 0 1 1", "ask 1 0 1 1", "org 2 0 1 2", "cal 0 1 1 2", "sc 1 1 1 1", "coll 1 2 1 1", "gwb 2 2 1 2", "tok 0 3 1 1",
                "att 1 3 1 1"]


def cfg(*cols, layout="1:1:1"):
    """옛 세 열 형식(1~3단계 · 옛 브라우저 저장본 옮기기) — 열마다 키 목록 / the older three-column shape, one key list per column"""
    return {"layout_type": layout,
            "columns": [{"column_index": i, "widgets": [{"widget_key": k, "sort_order": n} for n, k in enumerate(keys)]}
                        for i, keys in enumerate(cols)]}


def grid(*rows, layout="1:1:1"):
    """격자 배치 본문 — 항목마다 '키 x y 가로 세로' / a grid layout body, one 'key x y w h' per entry"""
    return {"layout_type": layout,
            "items": [{"widget_key": p[0], "x": int(p[1]), "y": int(p[2]), "w": int(p[3]), "h": int(p[4])} for p in (r.split() for r in rows)]}


def rows_of(config) -> list[str]:
    return [f"{i['widget_key']} {i['x']} {i['y']} {i['w']} {i['h']}" for i in config["items"]]


def keys_of(config) -> list[str]:
    return [i["widget_key"] for i in config["items"]]


def at(hour, minute=0, second=0):
    """KST 시계 고정(UTC 로 넣는다) / pin the KST clock (given in UTC)"""
    return patch.object(kst, "_clock", return_value=datetime(2026, 11, 13, hour, minute, second, tzinfo=timezone.utc))


# 값이 틀린 정의 / wrong definitions
BAD_SPECS = [
    ("not an object", ["title"], "위젯 정의 형식이 올바르지 않습니다"),
    ("old version", {"v": 1, "title": "t", "kpis": [{"label": "k", "value": 1}]}, "지원하지 않는 위젯 정의입니다. 위젯 에이전트에서 다시 만들어 주세요"),
    ("no title", {"v": 2, "kpis": [{"label": "k", "value": 1}]}, "위젯 제목을 입력해 주세요"),
    ("blank title", {"v": 2, "title": "  ", "kpis": [{"label": "k", "value": 1}]}, "위젯 제목을 입력해 주세요"),
    ("title 41", {"v": 2, "title": "가" * 41, "kpis": [{"label": "k", "value": 1}]}, "위젯 제목은 40자까지 쓸 수 있습니다"),
    ("title not text", {"v": 2, "title": 7, "kpis": [{"label": "k", "value": 1}]}, "위젯 제목은 글자여야 합니다"),
    ("nothing to show", {"v": 2, "title": "t"}, "위젯에 보여 줄 내용이 없습니다. 위젯 에이전트로 차트나 KPI 카드를 먼저 만들어 주세요"),
    ("source not object", {**kpi_spec(), "source": "a,b"}, "데이터 형식이 올바르지 않습니다"),
    ("other tool", {**kpi_spec(), "source": {"tool": "weather", "columns": ["a"], "rows": []}}, "지원하지 않는 데이터 출처입니다: weather"),
    ("no tool", {**kpi_spec(), "source": {"columns": ["a"], "rows": []}}, "지원하지 않는 데이터 출처입니다"),
    ("no columns", with_source(columns=[]), "데이터 열은 1~12개여야 합니다"),
    ("13 columns", with_source(columns=[f"c{i}" for i in range(13)]), "데이터 열은 1~12개여야 합니다"),
    ("duplicate columns", with_source(columns=["a", " a"]), "열 이름이 겹칩니다: a"),
    ("blank column", with_source(columns=["a", " "]), "열 이름은 비어 있지 않은 글자여야 합니다"),
    ("column 41", with_source(columns=["가" * 41]), "열 이름은 40자까지 쓸 수 있습니다"),
    ("rows not a list", with_source(rows="a,b"), "데이터 행은 목록이어야 합니다"),
    ("201 rows", with_source(rows=[["x"]] * 201), "데이터는 200줄까지 넣을 수 있습니다"),
    ("row not a list", with_source(rows=[{"a": 1}]), "각 데이터 행은 칸의 목록이어야 합니다"),
    ("bool cell", with_source(rows=[[True]]), "칸에는 글자 · 숫자 · 빈 값만 넣을 수 있습니다"),
    ("list cell", with_source(rows=[[[1]]]), "칸에는 글자 · 숫자 · 빈 값만 넣을 수 있습니다"),
    ("301 cell", with_source(rows=[["가" * 301]]), "칸 하나에는 300자까지 넣을 수 있습니다"),
    ("chart without data", {"v": 2, "title": "t", "chart": {"type": "bar"}}, "차트에는 데이터가 필요합니다"),
    ("chart not object", {"v": 2, "title": "t", "source": MONTHLY, "chart": "bar"}, "차트 설정 형식이 올바르지 않습니다"),
    ("chart unknown x", chart_spec(x="날짜"), "'날짜' 컬럼이 없습니다. 쓸 수 있는 컬럼: 월, 매출, 지점"),
    ("chart unknown y", chart_spec(y=[{"col": "이익"}]), "'이익' 컬럼이 없습니다. 쓸 수 있는 컬럼: 월, 매출, 지점"),
    ("kpis not a list", {"v": 2, "title": "t", "kpis": {"label": "k"}}, "KPI 카드 설정 형식이 올바르지 않습니다"),
    ("5 kpis", {"v": 2, "title": "t", "kpis": [{"label": f"k{i}", "value": i} for i in range(5)]}, "위젯에는 KPI 카드를 4개까지 넣을 수 있습니다"),
    ("kpi not object", {"v": 2, "title": "t", "kpis": ["k"]}, "KPI 카드 설정 형식이 올바르지 않습니다"),
    ("pending no label", {"v": 2, "title": "t", "kpis": [{"pending": True}]}, "KPI 카드 이름을 적어 주세요"),
    ("pending label 41", {"v": 2, "title": "t", "kpis": [{"pending": True, "label": "가" * 41}]}, "KPI 카드 이름은 40자까지 쓸 수 있습니다"),
    ("same kpi names", {"v": 2, "title": "t", "kpis": [{"label": "목표", "value": 1}, {"label": "목표", "pending": True}]}, "같은 이름의 KPI 카드가 있습니다: 목표"),
    ("data kpi without data", {"v": 2, "title": "t", "kpis": [{"label": "합", "col": "매출"}]}, "KPI 카드가 가리키는 Source 가 없습니다. 쓸 수 있는 Source: 없음"),
    ("fixed kpi without name", {"v": 2, "title": "t", "kpis": [{"value": 3}]}, "KPI 카드 이름을 적어 주세요"),
    ("insight not text", {**kpi_spec(), "insight": 5}, "인사이트는 글자여야 합니다"),
    ("insight 301", {**kpi_spec(), "insight": "가" * 301}, "인사이트는 300자까지 쓸 수 있습니다"),
]


class LayoutTests(unittest.TestCase):
    """격자 배치 정규화(문서 4절 · 12절) / grid layout normalization (sections 4 and 12)"""

    def test_builtins_layouts_sizes_and_default_follow_the_contract(self):
        self.assertEqual([w["key"] for w in hw.BUILTIN], ["wx", "cal", "tok", "ask", "sc", "coll", "att", "org", "gwb"])
        self.assertEqual([w["name"] for w in hw.BUILTIN], ["오늘의 날씨", "일정", "토큰 사용량", "AI 질문", "바로가기", "컬렉션",
                                                           "근태관리", "조직도", "그룹웨어 게시판"])
        self.assertEqual([w["key"] for w in hw.BUILTIN if w["locked"]], ["wx"])   # wx 만 잠김 / only wx is locked
        self.assertEqual(hw.LAYOUT_OPTIONS, [{"value": "1:1:1", "ratios": [1, 1, 1]}, {"value": "2:3:3", "ratios": [2, 3, 3]},
                                             {"value": "1:2:1", "ratios": [1, 2, 1]}])
        self.assertEqual((hw.MAX_WIDGETS, hw.MAX_KPIS, hw.SPEC_VERSION, hw.MAX_CELL, hw.GRID_COLS), (30, 4, 2, 300, 3))
        for cls in (hw.SpecError, hw.ConfigError, hw.WidgetError):
            self.assertTrue(issubclass(cls, ValueError))
        # 위젯 크기 = (처음 가로, 처음 세로, 최소 가로, 최대 가로, 최소 세로, 최대 세로) — 사용자 결정 표 / the agreed size table
        self.assertEqual({k: tuple(hw.size_of(k).values()) for k in hw.BUILTIN_KEYS}, {
            "wx": (1, 1, 1, 2, 1, 1), "cal": (1, 2, 1, 2, 2, 3), "tok": (1, 1, 1, 2, 1, 1), "ask": (1, 1, 1, 3, 1, 1), "sc": (1, 1, 1, 3, 1, 2),
            "coll": (1, 1, 1, 2, 1, 3), "att": (1, 1, 1, 2, 1, 1), "org": (1, 2, 1, 3, 2, 3), "gwb": (1, 2, 1, 3, 1, 3)})
        self.assertEqual(list(hw.size_of("wx")), ["w", "h", "min_w", "max_w", "min_h", "max_h"])
        # 만든 위젯: 가로 1~3 · 세로 1~3, 차트가 있으면 1 × 2 로 시작 / made widgets: 1..3 by 1..3, starting 1 × 2 with a chart
        for model, h in (({"chart": {"type": "bar"}}, 2), ({"chart": {"type": "kpi"}}, 1), ({"chart": None}, 1), (None, 1), ("x", 1)):
            self.assertEqual(hw.size_of("cw_00000001", model), {"w": 1, "h": h, "min_w": 1, "max_w": 3, "min_h": 1, "max_h": 3}, model)
        d = hw.default_config()
        self.assertEqual(d["layout_type"], "1:1:1")
        self.assertEqual(rows_of(d), DEFAULT_ROWS)
        for i in d["items"]:   # 처음 배치는 위젯마다 처음 크기 / every default item has its default size
            self.assertEqual((i["w"], i["h"]), (hw.size_of(i["widget_key"])["w"], hw.size_of(i["widget_key"])["h"]))
        self.assertEqual({x: max(i["y"] + i["h"] for i in d["items"] if i["x"] == x) for x in range(3)}, {0: 4, 1: 4, 2: 4})   # 세 열 모두 4칸 / all end at row 4
        self.assertEqual(hw.normalize_config(d, SIZES, strict=True), d)   # 기본 배치는 저장 검사도 통과하고 그대로 / passes the save check unchanged

    def test_lenient_read_fits_sizes_and_spots_drops_unknown_and_repeated_keys_adds_weather_and_settles(self):
        sizes = {**SIZES, "cw_aaaa0001": hw.size_of("cw_aaaa0001", {"chart": {"type": "bar"}})}
        raw = {"layout_type": "9:9:9", "items": [
            {"widget_key": " cal ", "x": 0, "y": 0, "w": 5, "h": 1},              # 가로 → 최대 2, 세로 → 최소 2 / w → max 2, h → min 2
            {"widget_key": "nope", "x": 1, "y": 0, "w": 1, "h": 1},                # 모르는 키 / unknown
            {"widget_key": "org", "x": 9, "y": -3, "w": 1, "h": 9},                # x → 2, y → 0, 세로 → 최대 3 / x → 2, y → 0, h → max 3
            {"widget_key": "cal", "x": 2, "y": 5},                                 # 두 번째 / repeated
            {"widget_key": "cw_aaaa0001", "x": 1.4, "y": "2", "w": True, "h": None},   # 소수는 반올림, 글자 · 참거짓 · 없음은 처음 값 / rounding and fallbacks
            {"widget_key": 3}, "junk",
        ]}
        out = hw.normalize_config(raw, sizes)
        # 날씨(잠금)가 맨 위에 들어가 일정을 밀고, 일정이 만든 위젯을 민다 / weather goes on top and pushes the schedule, which pushes the made widget
        self.assertEqual(out["layout_type"], "1:1:1")
        self.assertEqual(rows_of(out), ["wx 0 0 1 1", "org 2 0 1 3", "cal 0 1 2 2", "cw_aaaa0001 1 3 1 2"])
        self.assertEqual(set(out["items"][0]), {"widget_key", "x", "y", "w", "h"})
        # 저장 검사: 레이아웃만 고치면 통과하고 항목은 같다 / strict: fixing the layout alone passes with the same items
        self.assertEqual(hw.normalize_config({**raw, "layout_type": "2:3:3"}, sizes, strict=True), {**out, "layout_type": "2:3:3"})
        # 소수 0.5 는 올림(화면 Math.round 와 같게 — 4단계 검토) / halves round up, like the screen's Math.round (phase-4 review)
        self.assertEqual(rows_of(hw.normalize_config({"layout_type": "1:1:1", "items": [{"widget_key": "ask", "x": 0.5, "y": 2.5}]}, SIZES)),
                         ["wx 0 0 1 1", "ask 1 0 1 1"])
        # 정리된 배치는 다시 해도 같다 / a normalized layout is stable
        self.assertEqual(hw.normalize_config(out, sizes), out)
        self.assertEqual(hw.settle([dict(i) for i in out["items"]]), out["items"])

    def test_the_older_column_shape_reads_as_a_grid(self):
        # 1~3단계에 저장된 세 열(열 i → x = i, 가로는 최소, 세로는 처음 크기로 쌓는다) / phase 1-3 columns: column i stacks at x = i
        out = hw.normalize_config(cfg(["tok", "wx", "cal"], ["ask", "coll", "sc"], ["gwb", "org"], layout="1:2:1"), SIZES)
        self.assertEqual(out["layout_type"], "1:2:1")
        self.assertEqual(rows_of(out), ["tok 0 0 1 1", "ask 1 0 1 1", "gwb 2 0 1 2", "wx 0 1 1 1", "coll 1 1 1 1", "cal 0 2 1 2", "sc 1 2 1 1",
                                        "org 2 2 1 2"])
        # 열 번호 · 순서 · 모르는 키 · 두 번째 키도 종전처럼 고친다 / indexes, order, unknown and repeated keys are repaired as before
        sizes = {**SIZES, "cw_aaaa0001": hw.size_of("cw_aaaa0001", {"chart": {"type": "bar"}})}
        raw = {"layout_type": "2:3:3", "columns": [
            {"column_index": 1, "widgets": [{"widget_key": "sc", "sort_order": 2}, {"widget_key": "ask", "sort_order": 0},
                                            {"widget_key": "nope", "sort_order": 1}]},
            {"column_index": 0, "widgets": [{"widget_key": "wx"}, {"widget_key": " cal ", "sort_order": 5}, "tok", {"widget_key": 3}]},
            {"column_index": 3, "widgets": [{"widget_key": "org", "sort_order": 0}]},      # 없는 열 / no such column
            {"column_index": True, "widgets": [{"widget_key": "gwb", "sort_order": 0}]},   # bool 은 번호가 아니다 / not an index
            {"column_index": "2", "widgets": [{"widget_key": "gwb", "sort_order": 0}]},    # 글자도 아니다 / nor is text
            {"column_index": 1, "widgets": [{"widget_key": "coll", "sort_order": 0}, {"widget_key": "ask", "sort_order": 1}]},
            {"column_index": 2, "widgets": [{"widget_key": "cw_aaaa0001", "sort_order": 1}, {"widget_key": "wx", "sort_order": 0}]},
            "junk",
        ]}
        self.assertEqual(rows_of(hw.normalize_config(raw, sizes)),
                         ["cal 0 0 1 2", "ask 1 0 1 1", "cw_aaaa0001 2 0 1 2", "sc 1 1 1 1", "wx 0 2 1 1", "coll 1 2 1 1"])
        # sort_order 가 없거나 숫자가 아니면 맨 뒤(원래 순서) / a missing or non-numeric sort_order goes last in the original order
        odd = {"layout_type": "1:2:1", "columns": [{"column_index": 0, "widgets": [
            {"widget_key": "wx", "sort_order": None}, {"widget_key": "cal", "sort_order": "1"},
            {"widget_key": "tok", "sort_order": float("nan")}, {"widget_key": "ask", "sort_order": 1},
            {"widget_key": "sc", "sort_order": 0.5}, {"widget_key": "coll", "sort_order": True}, {"widget_key": "att"}]}]}
        self.assertEqual(rows_of(hw.normalize_config(odd, SIZES)),
                         ["sc 0 0 1 1", "ask 0 1 1 1", "wx 0 2 1 1", "cal 0 3 1 2", "tok 0 5 1 1", "coll 0 6 1 1", "att 0 7 1 1"])

    def test_lenient_read_of_garbage_keeps_only_the_weather(self):
        for raw in (None, "1:1:1", {"layout_type": 3, "columns": "wx"}, {"columns": {"0": ["wx"]}}, {"items": "x"},
                    {"layout_type": "2:3:3", "columns": [{"column_index": 0, "widgets": "wx"}]}, {"items": [1, None, {"widget_key": "nope"}]}):
            self.assertEqual(rows_of(hw.normalize_config(raw, SIZES)), ["wx 0 0 1 1"], raw)
        self.assertEqual(hw.normalize_config(None, SIZES), {"layout_type": "1:1:1", "items": [{"widget_key": "wx", "x": 0, "y": 0, "w": 1, "h": 1}]})
        self.assertEqual(rows_of(hw.normalize_config({"layout_type": "1:1:1", "items": []}, {})), [])   # 날씨를 모르면 넣지 않는다 / no weather when unknown

    def test_strict_save_rejects_unknown_layouts_and_mis_shaped_bodies_but_not_a_sparse_grid(self):
        good = grid("wx 0 0 1 1", "cal 1 0 1 2")
        for layout in ("1:1:2", "", None, 111):
            with self.assertRaises(hw.ConfigError, msg=str(layout)):
                hw.normalize_config({**good, "layout_type": layout}, SIZES, strict=True)
        for body in ({"layout_type": "1:1:1"}, {"layout_type": "1:1:1", "items": "x"}, {"layout_type": "1:1:1", "items": None, "columns": None},
                     {"layout_type": "1:1:1", "columns": "x"}, {"layout_type": "1:1:1", "columns": {"0": ["wx"]}}):
            with self.assertRaisesRegex(hw.ConfigError, "^배치 형식이 올바르지 않습니다$", msg=str(body)):
                hw.normalize_config(body, SIZES, strict=True)
        # 빈 열은 이제 괜찮다(격자): 날씨만 남아도 저장된다 · 모르는 키는 조용히 버린다 / empty columns are fine now; unknown keys drop quietly
        self.assertEqual(rows_of(hw.normalize_config({"layout_type": "1:1:1", "items": []}, SIZES, strict=True)), ["wx 0 0 1 1"])
        self.assertEqual(rows_of(hw.normalize_config(grid("wx 0 0 1 1", "cw_gone0001 1 0 1 1"), SIZES, strict=True)), ["wx 0 0 1 1"])
        self.assertEqual(hw.normalize_config({**good, "layout_type": " 1:2:1 "}, SIZES, strict=True)["layout_type"], "1:2:1")
        # 저장 때도 옛 세 열 형식을 받는다(옛 브라우저 저장본 옮기기) / saves still take the older column shape (moving an old browser layout)
        self.assertEqual(rows_of(hw.normalize_config(cfg(["wx"], ["cal"], []), SIZES, strict=True)), ["wx 0 0 1 1", "cal 1 0 1 2"])


class SpecTests(unittest.TestCase):
    """위젯 정의 v2(문서 6절) / definition v2 (section 6)"""

    def test_a_draft_starts_empty_and_normalizing_is_idempotent(self):
        self.assertEqual(hw.normalize_spec({}, draft=True), {"v": 2, "title": "새 위젯", "source": None, "chart": None, "kpis": [],
                                                              "theme": None, "insight": "", "blocks": [], "origins": []})
        clean = hw.normalize_spec(CHART_SPEC)
        self.assertEqual(hw.normalize_spec(clean), clean)
        self.assertEqual(hw.normalize_spec(clean, draft=True), clean)
        chart = clean["chart"]
        # 차트 = 리포트 에이전트 차트 설정. id · 데이터 · 제목(= 위젯 제목) · 크기는 위젯이 정한다
        # the chart is a report-agent chart spec; the widget fixes its id, data, title (= the widget title) and size
        self.assertEqual((chart["id"], chart["source"], chart["title"], chart["size"], chart["type"], chart["x"]),
                         ("c1", "s1", "월별 매출", "full", "bar", "월"))
        self.assertEqual(chart, rd.norm_chart({**CHART_SPEC["chart"], "id": "c1", "source": "s1", "title": "월별 매출", "size": "full"},
                                              {"s1": hw.to_state(clean)["sources"][0]}, set()))
        self.assertEqual(clean["source"], MONTHLY)

    def test_widget_only_fields_are_dropped_and_the_title_follows_the_widget(self):
        clean = hw.normalize_spec({**CHART_SPEC, "title": " 지점 실적 ", "chart": {
            **CHART_SPEC["chart"], "id": "c9", "source": "s7", "title": "다른 제목", "subtitle": "부제", "size": "half",
            "drill": ["지점"], "notes": [{"x": "2026-01", "text": "메모"}], "compare": "g1", "insight": "옛 문장"}})
        chart = clean["chart"]
        self.assertEqual((clean["title"], chart["id"], chart["source"], chart["title"], chart["subtitle"], chart["size"], chart["insight"]),
                         ("지점 실적", "c1", "s1", "지점 실적", "", "full", ""))
        for gone in ("drill", "notes", "compare"):
            self.assertNotIn(gone, chart)

    def test_kpi_cards_fixed_computed_and_not_connected(self):
        clean = hw.normalize_spec({**CHART_SPEC, "kpis": [
            {"label": "매출 합계", "col": "매출", "source": "s1", "delta": "prev"},
            {"label": "목표", "value": "1,200", "unit": "건"},
            {"label": " 신규 고객 ", "pending": True, "unit": "명", "note": "이번 달", "value": 99, "id": "k7"}]})
        data, fixed, pend = clean["kpis"]
        self.assertEqual((data["id"], data["source"], data["col"], data["agg"], data["delta"]), ("k1", "s1", "매출", "sum", "prev"))
        self.assertEqual((fixed["id"], fixed["value"], fixed["unit"], fixed["source"]), ("k2", 1200.0, "건", ""))
        self.assertEqual(pend, {"id": "k7", "source": "", "col": "", "agg": "", "label": "신규 고객", "unit": "명", "link": "",
                                "delta": "", "value": None, "note": "이번 달", "pending": True})
        # 데이터 연결 전 카드만으로도 저장할 수 있다 / a widget of not-connected cards alone can be saved
        self.assertEqual(hw.normalize_spec({"v": 2, "title": "KPI", "kpis": [{"label": "KPI 1", "pending": True}]})["kpis"][0]["pending"], True)

    def test_theme_and_insight(self):
        clean = hw.normalize_spec({**kpi_spec(), "theme": {"brand_color": "#4450ce", "second": "#zzz"}, "insight": "  {k1}이 목표입니다  "})
        self.assertEqual((clean["theme"], clean["insight"]), ({"brand": "#4450CE", "second": ""}, "{k1}이 목표입니다"))
        self.assertIsNone(hw.normalize_spec({**kpi_spec(), "theme": {"brand": "blue"}})["theme"])   # 대표 색이 아니면 없는 것 / not a brand colour

    def test_wrong_values_raise_korean_spec_errors(self):
        for name, spec, detail in BAD_SPECS:
            with self.subTest(name):
                with self.assertRaises(hw.SpecError) as cm:
                    hw.normalize_spec(spec)
                self.assertEqual(str(cm.exception), detail)
                self.assertNotIn("—", str(cm.exception))
        with self.assertRaisesRegex(hw.SpecError, "^위젯에 넣은 데이터가 너무 큽니다"):
            hw.normalize_spec(with_source(columns=["a", "b", "c", "d"], rows=[["가" * 200] * 4] * 200))

    def test_mis_shaped_chart_fields_are_user_sentences_not_crashes(self):
        # 형식이 틀린 항목은 리포트 에이전트 정규화가 TypeError · OverflowError · 영어 ValueError 를 냈다(2026-11-16 검토 4) / they used to crash
        for name, chart in (("filters number", {"filters": 5}), ("highlights number", {"highlights": 5}), ("ref_lines object", {"ref_lines": {"a": 1}}),
                            ("selected number", {"filters": [{"col": "지점", "selected": 5}]}), ("limit infinity", {"limit": float("inf")}),
                            ("limit nan", {"limit": float("nan")}), ("trend infinity", {"trend": {"line": True, "forecast": float("inf")}})):
            with self.subTest(name):
                with self.assertRaises(hw.SpecError) as cm:
                    hw.normalize_spec(chart_spec(**chart))
                self.assertEqual(str(cm.exception), "차트 설정 형식이 올바르지 않습니다")
        # 리포트 에이전트의 한국어 문장은 그대로 / the report agent's Korean sentences stay as they are
        with self.assertRaisesRegex(hw.SpecError, "^'날짜' 컬럼이 없습니다"):
            hw.normalize_spec(chart_spec(x="날짜"))

    def test_origins_and_blocks_from_the_data_pipeline(self):
        # 3단계: 부분별 출처(origins — 표 · 카드 · 글 · 목록)와 숫자가 아닌 내용(blocks) / phase 3: per-part origins and non-numeric blocks
        refs = ([{"kind": "web", "label": "news.example", "url": "https://news.example/a", "page": 0}, {"kind": "doc", "label": "사내규정.pdf", "page": 3},
                 {"kind": "mail", "label": "x"}, {"kind": "web", "label": " "}] + [{"kind": "web", "label": f"s{i}"} for i in range(8)])
        spec = {"v": 2, "title": "오늘 환율", "kpis": [{"label": "1달러", "value": 1350, "unit": "원"}, {"label": "목표", "value": 1}], "blocks": [
            {"type": "list", "items": [{"title": " 원달러 1,350원 ", "sub": "11월 16일", "url": "https://news.example/a"},
                                       {"title": "엔화", "url": "javascript:alert(1)"}, {"title": " "}, "junk"]},
            {"type": "text", "text": "가" * 700}, {"type": "list", "items": [{"title": "두 번째 목록은 버린다"}]}],
            "origins": [
                {"part": "list", "kind": "web", "query": " 환율 뉴스 ", "view": "list", "sql": "SELECT 1", "sig": "x", "tables": ["x"],
                 "fetched_at": "2026-11-16T10:00:00", "refs": refs},
                {"part": "cards", "kind": "web", "query": "오늘 원달러 환율", "view": "kpi", "fetched_at": "2026-11-16T10:05:00",
                 "cards": [{"id": "k1", "key": "1달러"}, {"id": "k9", "key": "없는 카드"}, "k2", {"id": "bad"}]},
                {"part": "cards", "kind": "web", "query": "다른 요청", "cards": [{"id": "k1", "key": "겹침"}]},   # 카드는 한 출처에만 / one origin per card
                {"part": "list", "kind": "docs", "query": "두 번째 목록 출처는 버린다"}]}
        clean = hw.normalize_spec(spec)
        self.assertEqual(clean["blocks"], [{"type": "list", "items": [{"title": "원달러 1,350원", "sub": "11월 16일", "url": "https://news.example/a"},
                                                                       {"title": "엔화", "sub": "", "url": ""}]},
                                           {"type": "text", "text": "가" * 600}])
        self.assertEqual(len(clean["origins"]), 2)
        o1, o2 = clean["origins"]
        self.assertEqual((o1["part"], o1["kind"], o1["query"], o1["view"], o1["sql"], o1["sig"], o1["tables"], o1["cards"]),
                         ("list", "web", "환율 뉴스", "list", "", "", [], []))   # SQL 은 사내 데이터에만 / SQL belongs to company data only
        self.assertEqual(o1["refs"][:2], [{"kind": "web", "label": "news.example", "url": "https://news.example/a", "page": None},
                                          {"kind": "doc", "label": "사내규정.pdf", "url": "", "page": 3}])
        self.assertEqual(len(o1["refs"]), hw.MAX_REFS)
        # 없는 카드(k9) · 틀린 id 는 빠지고, 이름 없는 옛 꼴('k2')은 키 없이 / missing and bad ids are dropped; the old bare id gets no key
        self.assertEqual(o2["cards"], [{"id": "k1", "key": "1달러"}, {"id": "k2", "key": ""}])
        self.assertEqual(hw.normalize_spec(clean), clean)
        m = hw.resolve(spec)   # 글/목록만으로도 저장할 수 있고, 모델에 출처 종류가 실린다 / blocks alone can be saved; the model carries the kinds
        self.assertEqual((m["empty"], m["origins"], m["refresh"], len(m["refs"])),
                         (False, [{"kind": "web", "label": "웹 검색", "fetched_at": "2026-11-16T10:05:00"}], True, 6))
        # 옛 꼴(origin 하나)도 읽는다 / the older single-origin shape still reads
        legacy = hw.normalize_spec({**kpi_spec(), "origin": {"kind": "docs", "query": "q", "view": "text"}})
        self.assertEqual([(o["part"], o["kind"]) for o in legacy["origins"]], [("text", "docs")])
        # 사내 데이터 = 표. SQL 은 2만 자까지(넘으면 자르지 않고 버린다 — 잘린 SQL 은 조용히 실패했다) / company data is a table; longer SQL is dropped
        data = {**CHART_SPEC, "origins": [{"kind": "data", "query": "월별 매출", "sql": "SELECT 월, 매출 FROM sales", "sig": "s", "tables": ["sales"]}]}
        o = hw.normalize_spec(data)["origins"][0]
        self.assertEqual((o["part"], o["sql"], o["sig"], o["tables"], hw.refreshable(o)), ("source", "SELECT 월, 매출 FROM sales", "s", ["sales"], True))
        long = hw.normalize_spec({**CHART_SPEC, "origins": [{"kind": "data", "query": "q", "sql": "SELECT " + "1," * 12000 + "1"}]})["origins"][0]
        self.assertEqual((long["sql"], hw.refreshable(long)), ("", False))
        for bad, detail in (({"origins": [{"kind": "mail"}]}, "내용의 출처 형식이 올바르지 않습니다"), ({"origins": "web"}, "내용의 출처 형식이 올바르지 않습니다"),
                            ({"origin": {"kind": "mail"}}, "내용의 출처 형식이 올바르지 않습니다"),
                            ({"blocks": "글"}, "위젯 내용 형식이 올바르지 않습니다"), ({"blocks": [{"type": "image"}]}, "위젯 내용 형식이 올바르지 않습니다")):
            with self.assertRaises(hw.SpecError) as cm:
                hw.normalize_spec({**kpi_spec(), **bad})
            self.assertEqual(str(cm.exception), detail)

    def test_limits_are_inclusive(self):
        hw.normalize_spec({"v": 2, "title": "가" * 40, "kpis": [{"label": f"k{i}", "value": i} for i in range(4)], "insight": "가" * 300})
        hw.normalize_spec(with_source(columns=[f"c{i}" for i in range(12)], rows=[["가" * 300] + [1] * 11] * 3))
        hw.normalize_spec(with_source(rows=[["x"]] * 200))


class InsightTests(unittest.TestCase):
    """데이터가 바뀌면 같이 바뀌는 인사이트(문서 7절) / insights that follow the data (section 7)"""

    def test_variables_follow_the_data(self):
        spec = {**CHART_SPEC, "insight": "{최고}가 {최고값}으로 가장 높고, {마지막}에는 직전보다 {직전대비} {증감}했습니다"}
        self.assertEqual(hw.resolve(spec)["insight"], "2026-04가 180으로 가장 높고, 2026-04에는 직전보다 100% 증가했습니다")
        # 데이터가 바뀌면 숫자 · 항목 · 조사 · 증감이 같이 바뀐다 / new data changes the numbers, items, particles and direction
        later = {**spec, "source": {**MONTHLY, "rows": [["2026-01", 200, "서울"], ["2026-02", 100, "부산"]]}}
        self.assertEqual(hw.resolve(later)["insight"], "2026-01이 200으로 가장 높고, 2026-02에는 직전보다 50% 감소했습니다")
        flat = {**spec, "source": {**MONTHLY, "rows": [["2026-01", 100, "서울"], ["2026-02", 100, "부산"]]}}
        self.assertTrue(hw.resolve(flat)["insight"].endswith("직전보다 0% 보합했습니다"))

    def test_insight_values(self):
        state = hw.to_state(hw.normalize_spec({**CHART_SPEC, "kpis": [{"label": "목표", "value": 1200, "unit": "건"}, {"label": "새 카드", "pending": True}]}))
        comp = rd.compute(state["charts"][0], state["sources"][0])
        self.assertEqual(hw.insight_values(state, comp), {
            "최고": "2026-04", "최고값": "180", "최저": "2026-03", "최저값": "90", "평균": "135", "개수": "4", "처음": "2026-01", "처음값": "120",
            "마지막": "2026-04", "마지막값": "180", "합계": "540", "직전대비": "100%", "증감": "증가", "k1": "1,200건"})
        # 기간이 아닌 축에는 직전 대비가 없고, 비율(평균)에는 합계가 없다 / no previous-period change off a period axis, no total for a rate (avg)
        by_branch = hw.to_state(hw.normalize_spec(chart_spec(x="지점", y=[{"col": "매출", "agg": "avg"}])))
        vals = hw.insight_values(by_branch, rd.compute(by_branch["charts"][0], by_branch["sources"][0]))
        self.assertEqual((vals["최고"], vals["최고값"], vals["개수"]), ("울산", "180", "3"))
        for gone in ("합계", "직전대비", "증감"):
            self.assertNotIn(gone, vals)
        kpi_chart = hw.to_state(hw.normalize_spec(chart_spec(type="kpi")))
        self.assertEqual(hw.insight_values(kpi_chart, rd.compute(kpi_chart["charts"][0], kpi_chart["sources"][0])), {"값": "540"})

    def test_particles_follow_the_final_sound(self):
        cases = {"서울": "서울이 서울은 서울을 서울로 서울과", "부산": "부산이 부산은 부산을 부산으로 부산과",
                 "KPI": "KPI가 KPI는 KPI를 KPI로 KPI와", "1,200": "1,200이 1,200은 1,200을 1,200으로 1,200과",
                 "12.5%": "12.5%가 12.5%는 12.5%를 12.5%로 12.5%와", "7": "7이 7은 7을 7로 7과", "1.2억": "1.2억이 1.2억은 1.2억을 1.2억으로 1.2억과"}
        for value, want in cases.items():
            self.assertEqual(hw.render_insight("{a}가 {a}은(는) {a}을 {a}(으)로 {a}와", {"a": value}), (want, False), value)
        # 괄호 꼴도 고치고, 조사가 아닌 글자(가장 · 에서)는 그대로 / bracketed forms are fixed too; non-particles (가장, 에서) stay
        self.assertEqual(hw.render_insight("{a}이(가) 1위, {a}가장 {a}에서", {"a": "부산"}), ("부산이 1위, 부산가장 부산에서", False))
        # 값이 없는 변수가 있으면 문장을 숨긴다 / a variable without a value hides the sentence
        self.assertEqual(hw.render_insight("{a}와 {b}", {"a": "1"}), ("", True))
        self.assertEqual(hw.render_insight("", {}), ("", False))
        model = hw.resolve({**kpi_spec(), "insight": "{k2}가 남았습니다"})
        self.assertEqual((model["insight"], model["insight_wait"]), ("", True))

    def test_tool_checks_refuse_literal_numbers_and_items(self):
        state = hw.to_state(hw.normalize_spec(chart_spec(x="지점")))
        comp = rd.compute(state["charts"][0], state["sources"][0])
        self.assertEqual(hw.check_insight(" {최고}가 가장 높습니다 ", state, comp), "{최고}가 가장 높습니다")
        self.assertEqual(hw.check_insight("  ", state, comp), "")
        for text, start in (("가장 높습니다", "인사이트에는 데이터 값 변수를 하나 이상 넣어 주세요"),
                            ("{최댓값}이 큽니다", "쓸 수 없는 변수입니다: {최댓값}"),
                            ("{최고}가 180으로 가장 높습니다", "숫자는 직접 쓰지 말고 변수로 써 주세요"),
                            ("서울이 {최고값}으로 가장 높습니다", "'서울' 같은 항목 이름은 데이터가 바뀌면 달라집니다"),
                            ("{최고}" + "가" * 300, "인사이트는 300자까지 쓸 수 있습니다")):
            with self.assertRaises(ValueError, msg=text) as cm:
                hw.check_insight(text, state, comp)
            self.assertTrue(str(cm.exception).startswith(start), str(cm.exception))
        empty = hw.to_state(hw.normalize_spec({"v": 2, "title": "t", "kpis": [{"label": "KPI 1", "pending": True}]}))
        with self.assertRaisesRegex(ValueError, "^인사이트에 쓸 값이 없습니다"):
            hw.check_insight("{k1}", empty, None)


class ResolveTests(unittest.TestCase):
    """표시 모델 = 리포트 에이전트의 계산(문서 7절) / the display model = the report agent's math (section 7)"""

    def test_chart_model_hands_the_report_spec_and_its_values(self):
        clean = hw.normalize_spec(CHART_SPEC)
        state = hw.to_state(clean)
        m = hw.resolve(CHART_SPEC)
        self.assertEqual(set(m), {"v", "title", "kpis", "chart", "theme", "insight", "insight_wait", "blocks", "refs", "origins", "refresh",
                                  "needs_data", "empty"})
        self.assertEqual((m["v"], m["title"], m["kpis"], m["theme"], m["insight"], m["blocks"], m["refs"], m["origins"], m["refresh"],
                          m["needs_data"], m["empty"]), (2, "월별 매출", [], None, "", [], [], [], False, False, False))
        self.assertEqual(m["chart"], {"type": "bar", "config": clean["chart"], "data": rd.compute(state["charts"][0], state["sources"][0]),
                                      "empty": False, "filters": []})
        self.assertEqual((m["chart"]["data"]["x"], m["chart"]["data"]["series"][0]["values"]),
                         (["2026-01", "2026-02", "2026-03", "2026-04"], [120.0, 150.0, 90.0, 180.0]))
        self.assertEqual(hw.resolve({}, draft=True)["empty"], True)

    def test_kpi_models_and_the_number_chart(self):
        m = hw.resolve({**CHART_SPEC, "chart": {**CHART_SPEC["chart"], "type": "kpi"}, "kpis": [
            {"label": "매출 합계", "col": "매출", "source": "s1", "delta": "prev"}, {"label": "목표", "value": 1200, "unit": "건"},
            {"label": "새 카드", "pending": True, "note": "곧 연결"}]})
        self.assertEqual((m["chart"]["type"], m["chart"]["text"]), ("kpi", "540"))
        self.assertEqual(m["kpis"], [
            {"id": "k1", "label": "매출 합계", "unit": "", "note": "", "pending": False, "text": "540", "manual": False, "delta": 100.0, "period": "2026-04"},
            {"id": "k2", "label": "목표", "unit": "건", "note": "", "pending": False, "text": "1,200건", "manual": True, "delta": None, "period": ""},
            {"id": "k3", "label": "새 카드", "unit": "", "note": "곧 연결", "pending": True, "text": "", "manual": False, "delta": None, "period": ""}])
        self.assertTrue(m["needs_data"])

    def test_fixed_conditions_show_as_tags(self):
        m = hw.resolve(chart_spec(filters=[{"col": "월", "last": 2}, {"col": "지점", "selected": ["서울", "부산"]}]))
        self.assertEqual(m["chart"]["filters"], ["월: 최근 2개", "지점: 서울, 부산"])
        self.assertEqual((m["chart"]["data"]["x"], m["chart"]["data"]["series"][0]["values"]), (["2026-03"], [90.0]))
        nothing = hw.resolve(chart_spec(filters=[{"col": "지점", "selected": ["대전"]}]))
        self.assertTrue(nothing["chart"]["empty"])


class StoreTests(unittest.TestCase):
    """저장소(임시 DB) / the store (temp DB)"""

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        hw.init_home_widgets()
        hw.init_home_widgets()   # 멱등 / idempotent

    def test_new_owner_gets_the_default_dashboard_and_nine_builtins(self):
        d = hw.get_dashboard("7")
        self.assertEqual(set(d), {"layout_options", "config", "widgets"})
        self.assertEqual(d["config"], {**hw.default_config(), "saved": False})
        self.assertEqual(rows_of(d["config"]), DEFAULT_ROWS)
        self.assertEqual(d["layout_options"], hw.LAYOUT_OPTIONS)
        self.assertEqual(d["widgets"], [{"key": b["key"], "kind": "builtin", "name": b["name"], "locked": b["locked"], "size": hw.size_of(b["key"])}
                                        for b in hw.BUILTIN])
        # 돌려준 값을 고쳐도 상수는 그대로 / mutating the answer leaves the constants alone
        d["layout_options"][0]["ratios"].append(9)
        d["widgets"][0]["name"] = "x"
        self.assertEqual((hw.LAYOUT_OPTIONS[0]["ratios"], hw.BUILTIN[0]["name"]), ([1, 1, 1], "오늘의 날씨"))

    def test_save_then_read_back_per_owner(self):
        body = grid("org 0 0 1 2", "wx 0 2 1 1", "cal 1 0 1 2", "gwb 2 0 1 2", "tok 2 2 1 1", layout="2:3:3")
        saved = hw.save_dashboard(" 7 ", body)   # 신원은 공백을 뺀다 / stripped
        self.assertEqual(saved, {**grid("org 0 0 1 2", "cal 1 0 1 2", "gwb 2 0 1 2", "wx 0 2 1 1", "tok 2 2 1 1", layout="2:3:3"), "saved": True})
        self.assertEqual(hw.get_dashboard("7")["config"], saved)
        with db._conn() as conn:   # 격자 형식으로 저장된다 / stored in the grid shape
            row = conn.execute("SELECT layout_type, columns FROM home_dash_config WHERE owner = '7'").fetchone()
        self.assertEqual((row["layout_type"], json.loads(row["columns"])), ("2:3:3", {"grid": 1, "items": saved["items"]}))
        self.assertFalse(hw.get_dashboard("12")["config"]["saved"])   # 다른 사람은 기본 배치 / others keep the default
        self.assertFalse(hw.get_dashboard("")["config"]["saved"])
        with self.assertRaises(hw.ConfigError):   # 실패한 저장은 아무것도 바꾸지 않는다 / a failed save changes nothing
            hw.save_dashboard("7", {"layout_type": "1:1:1", "items": "x"})
        self.assertEqual(hw.get_dashboard("7")["config"], saved)
        again = hw.save_dashboard("7", grid("wx 0 0 1 1", "cal 1 0 1 2", "tok 2 0 1 1", layout="1:2:1"))   # 덮어쓰기 / overwrite
        self.assertEqual(hw.get_dashboard("7")["config"], again)
        # 1~3단계가 저장한 세 열 줄도 격자로 읽힌다 / a row stored by phases 1-3 (columns) still reads, as a grid
        with db._conn() as conn:
            conn.execute("INSERT INTO home_dash_config(owner, layout_type, columns, updated_at) VALUES('9', '1:2:1', ?, 'x')",
                         (json.dumps(cfg(["wx", "cal"], ["ask"], ["org"])["columns"]),))
        old = hw.get_dashboard("9")["config"]
        self.assertEqual((old["saved"], old["layout_type"], rows_of(old)), (True, "1:2:1", ["wx 0 0 1 1", "ask 1 0 1 1", "org 2 0 1 2", "cal 0 1 1 2"]))

    def test_create_update_delete_cycle(self):
        with at(1):   # 01:00 UTC = 10:00 KST
            w = hw.create_widget("7", CHART_SPEC)
        self.assertRegex(w["key"], r"^cw_[0-9a-f]{8}$")
        self.assertEqual((w["kind"], w["name"], w["created_at"], w["updated_at"]),
                         ("custom", "월별 매출", "2026-11-13T10:00:00", "2026-11-13T10:00:00"))
        self.assertEqual((w["spec"], w["model"]), (hw.normalize_spec(CHART_SPEC), hw.resolve(CHART_SPEC)))
        d = hw.get_dashboard("7")
        # 기본 9개 뒤. 대시보드에는 모델만 싣고 정의(spec, 표 전체)는 싣지 않는다 / after the nine built-ins; the dashboard carries the model, never the spec
        self.assertEqual(d["widgets"][9:], [{**{k: v for k, v in w.items() if k != "spec"}, "size": hw.size_of(w["key"], w["model"])}])
        self.assertEqual(d["widgets"][9]["size"], {"w": 1, "h": 2, "min_w": 1, "max_w": 3, "min_h": 1, "max_h": 3})   # 차트 = 1 × 2 로 시작 / a chart starts 1 × 2
        self.assertEqual(hw.list_widgets("7"), [w])                           # 정의는 목록이 준다 / the list has the definition
        self.assertNotIn(w["key"], keys_of(d["config"]))                      # 서랍(안 쓰는 위젯)에 생긴다 / lands in the drawer
        new = chart_spec(type="donut")
        new["title"] = "월별 매출 비중"
        with at(2):
            u = hw.update_widget("7", w["key"], new)
        self.assertEqual((u["key"], u["name"], u["created_at"], u["updated_at"], u["model"]["chart"]["type"]),
                         (w["key"], "월별 매출 비중", "2026-11-13T10:00:00", "2026-11-13T11:00:00", "donut"))
        with self.assertRaises(hw.SpecError):   # 틀린 정의는 아무것도 바꾸지 않는다 / a wrong definition changes nothing
            hw.update_widget("7", w["key"], {"v": 2, "title": "", "kpis": []})
        with self.assertRaises(hw.SpecError):   # 내용 없는 정의도 저장하지 않는다 / nor one with nothing to show
            hw.update_widget("7", w["key"], {"v": 2, "title": "빈 위젯"})
        self.assertEqual(hw.get_widget("7", w["key"]), u)
        self.assertTrue(hw.delete_widget("7", w["key"]))
        self.assertIsNone(hw.get_widget("7", w["key"]))
        self.assertFalse(hw.delete_widget("7", w["key"]))
        self.assertIsNone(hw.update_widget("7", w["key"], new))
        self.assertEqual(hw.list_widgets("7"), [])

    def test_owners_are_separate(self):
        a = hw.create_widget("7", kpi_spec("A 목표"))
        b = hw.create_widget("12", kpi_spec("B 목표"))
        self.assertEqual([w["key"] for w in hw.list_widgets("7")], [a["key"]])
        self.assertIsNone(hw.get_widget("7", b["key"]))
        self.assertIsNone(hw.update_widget("7", b["key"], kpi_spec("가로채기")))
        self.assertFalse(hw.delete_widget("7", b["key"]))
        self.assertIsNone(hw.widget_data("7", b["key"]))
        self.assertEqual(hw.get_widget("12", b["key"])["name"], "B 목표")   # B 의 위젯은 그대로 / B's widget untouched
        # A 의 배치에 넣은 B 의 키는 버려지고 그 자리는 당겨진다 / B's key in A's layout is dropped and the gap closes
        saved = hw.save_dashboard("7", grid("wx 0 0 1 1", f"{b['key']} 1 0 1 1", "cal 2 0 1 2", f"{a['key']} 1 1 1 1"))
        self.assertEqual(rows_of(saved), ["wx 0 0 1 1", f"{a['key']} 1 0 1 1", "cal 2 0 1 2"])
        self.assertEqual(rows_of(hw.save_dashboard("7", grid(f"{b['key']} 0 0 1 1"))), ["wx 0 0 1 1"])
        self.assertEqual([w["key"] for w in hw.get_dashboard("7")["widgets"] if w["kind"] == "custom"], [a["key"]])
        self.assertEqual(hw.list_widgets(""), [])   # 데모 기본 사용자도 따로 / the demo default user is separate too

    def test_delete_strips_the_saved_layout_and_pulls_the_gap_up(self):
        a = hw.create_widget("7", kpi_spec("A"))
        b = hw.create_widget("7", kpi_spec("B"))
        hw.save_dashboard("7", grid("wx 0 0 1 1", f"{a['key']} 0 1 1 1", "cal 0 2 1 2", "ask 1 0 1 1", f"{b['key']} 2 0 1 1", layout="1:2:1"))
        self.assertTrue(hw.delete_widget("7", a["key"]))
        after = hw.get_dashboard("7")["config"]
        self.assertEqual(rows_of(after), ["wx 0 0 1 1", "ask 1 0 1 1", f"{b['key']} 2 0 1 1", "cal 0 1 1 2"])   # 일정이 위로 / the schedule rises
        with db._conn() as conn:   # 저장본 자체에서도 빠졌다 / gone from the stored row too
            stored = json.loads(conn.execute("SELECT columns FROM home_dash_config WHERE owner = '7'").fetchone()["columns"])
        self.assertNotIn(a["key"], json.dumps(stored))
        self.assertEqual(stored, {"grid": 1, "items": after["items"]})
        # 남은 것이 적어도 읽히고 그대로 다시 저장된다(빈 열 규칙은 없어졌다) / a sparse layout still reads and saves again as is
        self.assertTrue(hw.delete_widget("7", b["key"]))
        after = hw.get_dashboard("7")["config"]
        self.assertEqual((after["saved"], after["layout_type"], rows_of(after)), (True, "1:2:1", ["wx 0 0 1 1", "ask 1 0 1 1", "cal 0 1 1 2"]))
        self.assertEqual(hw.save_dashboard("7", {"layout_type": after["layout_type"], "items": after["items"]}), after)
        # 기본 위젯 키는 저장소에서 지워지지 않는다 / built-in keys never delete from the store
        self.assertFalse(hw.delete_widget("7", "wx"))
        self.assertEqual(rows_of(hw.get_dashboard("7")["config"]), ["wx 0 0 1 1", "ask 1 0 1 1", "cal 0 1 1 2"])

    def test_thirty_widgets_per_owner(self):
        for i in range(hw.MAX_WIDGETS):
            hw.create_widget("7", kpi_spec(f"위젯 {i}"))
        with self.assertRaisesRegex(hw.WidgetError, "^위젯은 한 사람당 30개까지 만들 수 있습니다$"):
            hw.create_widget("7", kpi_spec("하나 더"))
        self.assertEqual(len(hw.list_widgets("7")), 30)
        self.assertEqual(hw.create_widget("12", kpi_spec("다른 사람"))["name"], "다른 사람")   # 사람마다 따로 / per owner
        self.assertTrue(hw.delete_widget("7", hw.list_widgets("7")[0]["key"]))                  # 하나 지우면 다시 / one freed
        self.assertEqual(hw.create_widget("7", kpi_spec("다시"))["name"], "다시")

    def test_widgets_are_listed_by_created_at(self):
        with at(1, 0, 5):
            late = hw.create_widget("7", kpi_spec("늦게"))
        with at(1, 0, 1):
            early = hw.create_widget("7", kpi_spec("일찍"))
        with at(1, 0, 5):
            same = hw.create_widget("7", kpi_spec("같은 초"))   # 같은 초면 만든 순서 / same second: creation order
        order = [early["key"], late["key"], same["key"]]
        self.assertEqual([w["key"] for w in hw.list_widgets("7")], order)
        self.assertEqual([w["key"] for w in hw.get_dashboard("7")["widgets"][9:]], order)

    def test_widget_data_recomputes_and_refreshes_the_stored_model(self):
        w = hw.create_widget("7", CHART_SPEC)
        with db._conn() as conn:
            conn.execute("UPDATE home_widgets SET model = ? WHERE id = ?", (json.dumps({"v": 0}), w["key"]))
        self.assertEqual(hw.get_widget("7", w["key"])["model"], {"v": 0})
        with at(3):
            data = hw.widget_data(" 7", w["key"])
        self.assertEqual(data, {"key": w["key"], "model": hw.resolve(CHART_SPEC), "fetched_at": "2026-11-13T12:00:00"})
        after = hw.get_widget("7", w["key"])
        self.assertEqual(after["model"], data["model"])
        self.assertEqual(after["updated_at"], w["updated_at"])   # 정의는 그대로라 updated_at 도 그대로 / definition unchanged
        self.assertIsNone(hw.widget_data("7", "cw_00000000"))
        self.assertIsNone(hw.widget_data("7", "wx"))

    def test_store_refresh_keeps_updated_at_and_skips_a_definition_edited_meanwhile(self):
        with at(1):
            w = hw.create_widget("7", kpi_spec("환율", 1300, "원"))
        fresh = {**w["spec"], "kpis": [{**w["spec"]["kpis"][0], "value": 1350}]}
        model = hw.store_refresh("7", w["key"], fresh, w)
        self.assertEqual(model["kpis"][0]["text"], "1,350원")
        after = hw.get_widget("7", w["key"])
        self.assertEqual((after["spec"]["kpis"][0]["value"], after["model"], after["updated_at"]), (1350.0, model, w["updated_at"]))
        self.assertIsNone(hw.store_refresh("7", w["key"], fresh, {**after, "updated_at": "2000-01-01T00:00:00"}))   # 그 사이 고쳤다 / edited meanwhile
        self.assertIsNone(hw.store_refresh("12", w["key"], fresh, after))                                            # 남의 위젯 / someone else's
        # 같은 초 안의 수정(3단계 검토): updated_at 은 초 단위라 같아도, 정의 글자가 다르면 쓰지 않는다
        # an edit within the same second (phase-3 review): updated_at has whole seconds, so the definition text is compared too
        with at(1):
            hw.update_widget("7", w["key"], kpi_spec("내가 바꾼 제목", 1300, "원"))
        edited = hw.get_widget("7", w["key"])
        self.assertEqual(edited["updated_at"], after["updated_at"])
        self.assertIsNone(hw.store_refresh("7", w["key"], {**fresh, "kpis": [{**fresh["kpis"][0], "value": 1400}]}, after))
        self.assertEqual((hw.get_widget("7", w["key"])["spec"]["title"], hw.get_widget("7", w["key"])["name"]), ("내가 바꾼 제목", "내가 바꾼 제목"))

    def test_only_server_signed_sql_is_kept_on_save(self):
        # 3단계 검토: 정의는 화면이 들고 다니므로 서명 없는 · 남의 · 바뀐 SQL 은 저장할 때 버린다(그 표는 다시 가져오지 않는다)
        # phase-3 review: the screen carries the definition, so unsigned, foreign or edited SQL is dropped on save (that table never refreshes)
        sql = "SELECT 월, 매출 FROM sales"
        origin = {"kind": "data", "query": "월별 매출", "sql": sql, "fetched_at": "2026-11-13T09:00:00"}
        cases = ((origin, "7", ""), ({**origin, "sig": hw.sign_sql("7", sql)}, "7", sql), ({**origin, "sig": hw.sign_sql("7", sql)}, "12", ""),
                 ({**origin, "sql": sql + " WHERE 1 = 1", "sig": hw.sign_sql("7", sql)}, "7", ""), ({**origin, "sig": "f" * 64}, "7", ""))
        for o, who, kept in cases:
            with self.subTest(who=who, sig=o.get("sig", "")[:8], sql=o["sql"][-12:]):
                w = hw.create_widget(who, {**CHART_SPEC, "origins": [o]})
                got = w["spec"]["origins"][0]
                self.assertEqual((got["sql"], bool(got["sig"]), w["model"]["refresh"]), (kept, bool(kept), bool(kept)))
        w = hw.create_widget("7", {**CHART_SPEC, "origins": [{**origin, "sig": hw.sign_sql("7", sql)}]})
        r = hw.update_widget("7", w["key"], {**CHART_SPEC, "title": "바꿈", "origins": [{**origin, "sql": "SELECT * FROM hr", "sig": w["spec"]["origins"][0]["sig"]}]})
        self.assertEqual(r["spec"]["origins"][0]["sql"], "")   # 고치기도 같다 / updates too

    def test_data_never_overwrites_the_model_of_a_definition_that_changed_meanwhile(self):
        with at(1):
            w = hw.create_widget("7", kpi_spec("처음", 100))
        stale = dict(w)
        with at(2):
            hw.update_widget("7", w["key"], kpi_spec("고친 뒤", 300))
        self.assertNotEqual(hw.get_widget("7", w["key"])["updated_at"], stale["updated_at"])
        # /data 가 옛 정의를 읽은 뒤 그 사이 정의가 바뀐 상황: 옛 정의로 계산한 모델을 쓰지 않는다
        # /data read the old definition and the definition changed meanwhile: the old model is not written
        with patch.object(hw, "get_widget", return_value=stale):
            out = hw.widget_data("7", w["key"])
        self.assertEqual(out["model"]["kpis"][0]["text"], "100건")
        self.assertEqual(hw.get_widget("7", w["key"])["model"]["kpis"][0]["text"], "300건")


class ApiTests(unittest.IsolatedAsyncioTestCase):
    """/api/home 라우터만 올린 작은 앱 / a small app carrying only the /api/home router"""

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        hw.init_home_widgets()
        self.app = FastAPI()
        self.app.include_router(home_widgets_api.router)

    async def req(self, method, path, json=None, params=None):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
            return await client.request(method, path, json=json, params=params)

    async def test_dashboard_round_trip(self):
        r = await self.req("GET", "/api/home/dashboard", params={"acting_user_id": "7"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual((set(body), body["config"]["saved"], len(body["widgets"])),
                         ({"layout_options", "config", "widgets"}, False, 9))
        self.assertEqual(rows_of(body["config"]), DEFAULT_ROWS)
        self.assertEqual(body["widgets"][1]["size"], {"w": 1, "h": 2, "min_w": 1, "max_w": 2, "min_h": 2, "max_h": 3})   # 일정 / the schedule
        layout = grid("wx 0 0 1 1", "gwb 0 1 1 2", "ask 1 0 2 1", "org 2 1 1 2", layout="2:3:3")
        r = await self.req("PUT", "/api/home/dashboard", json={"acting_user_id": "7", **layout})
        want = {**grid("wx 0 0 1 1", "ask 1 0 2 1", "gwb 0 1 1 2", "org 2 1 1 2", layout="2:3:3"), "saved": True}   # 격자 차례로 / in grid order
        self.assertEqual((r.status_code, r.json()), (200, want))
        r = await self.req("GET", "/api/home/dashboard", params={"acting_user_id": "7"})
        self.assertEqual(r.json()["config"], want)
        # 옛 세 열 형식으로 보내도(옛 브라우저 저장본 옮기기) 격자로 저장한다 / the older column shape (moving an old browser layout) is saved as a grid
        r = await self.req("PUT", "/api/home/dashboard", json={"acting_user_id": "7", **cfg(["wx", "gwb"], ["ask", "cal"], ["org"], layout="1:2:1")})
        self.assertEqual((r.status_code, rows_of(r.json())), (200, ["wx 0 0 1 1", "ask 1 0 1 1", "org 2 0 1 2", "gwb 0 1 1 2", "cal 1 1 1 2"]))
        r = await self.req("GET", "/api/home/dashboard")   # 신원 없음 = 데모 기본 사용자, 따로 / no identity: separate default user
        self.assertFalse(r.json()["config"]["saved"])

    async def test_layout_errors_are_422_sentences_and_save_nothing(self):
        r = await self.req("PUT", "/api/home/dashboard", json={"acting_user_id": "7", "layout_type": "1:1:1", "items": "x"})
        self.assertEqual((r.status_code, r.json()["detail"]), (422, "배치 형식이 올바르지 않습니다"))
        r = await self.req("PUT", "/api/home/dashboard", json={"acting_user_id": "7", "layout_type": "1:1:1", "columns": "x"})
        self.assertEqual((r.status_code, r.json()["detail"]), (422, "배치 형식이 올바르지 않습니다"))
        r = await self.req("PUT", "/api/home/dashboard", json={"acting_user_id": "7", **grid("wx 0 0 1 1", layout="3:1:1")})
        self.assertEqual((r.status_code, r.json()["detail"]), (422, "지원하지 않는 레이아웃입니다: 3:1:1"))
        r = await self.req("PUT", "/api/home/dashboard", json={"acting_user_id": "7"})   # 레이아웃 · 열 없음 / nothing given
        self.assertEqual(r.status_code, 422)
        self.assertIsInstance(r.json()["detail"], str)
        r = await self.req("GET", "/api/home/dashboard", params={"acting_user_id": "7"})
        self.assertFalse(r.json()["config"]["saved"])

    async def test_widget_crud_over_http(self):
        r = await self.req("POST", "/api/home/widgets", json={"acting_user_id": "7", "spec": CHART_SPEC})
        self.assertEqual(r.status_code, 200)
        w = r.json()
        self.assertEqual((w["kind"], w["name"], w["spec"], w["model"]), ("custom", "월별 매출", hw.normalize_spec(CHART_SPEC), hw.resolve(CHART_SPEC)))
        r = await self.req("GET", "/api/home/widgets", params={"acting_user_id": "7"})
        self.assertEqual(r.json(), {"widgets": [w]})
        r = await self.req("GET", "/api/home/widgets", params={"acting_user_id": "12"})
        self.assertEqual(r.json(), {"widgets": []})
        r = await self.req("PUT", "/api/home/dashboard", json={"acting_user_id": "7", **grid("wx 0 0 1 1", f"{w['key']} 1 0 1 2", "ask 1 2 1 1", "org 2 0 1 2")})
        self.assertEqual((r.status_code, rows_of(r.json())), (200, ["wx 0 0 1 1", f"{w['key']} 1 0 1 2", "org 2 0 1 2", "ask 1 2 1 1"]))
        r = await self.req("PUT", f"/api/home/widgets/{w['key']}", json={"acting_user_id": "7", "spec": kpi_spec("목표 카드")})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["name"], r.json()["model"]["chart"], r.json()["spec"]["source"]), ("목표 카드", None, None))
        r = await self.req("GET", f"/api/home/widgets/{w['key']}/data", params={"acting_user_id": "7"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.json()), {"key", "model", "fetched_at"})
        self.assertEqual(r.json()["model"], hw.resolve(kpi_spec("목표 카드")))
        r = await self.req("DELETE", f"/api/home/widgets/{w['key']}", params={"acting_user_id": "7"})
        # 지운 위젯의 자리는 당겨진다(AI 질문이 위로) / the deleted widget's gap closes (the AI ask rises)
        self.assertEqual((r.status_code, r.json()), (200, {"ok": True, "config": {**grid("wx 0 0 1 1", "ask 1 0 1 1", "org 2 0 1 2"), "saved": True}}))
        r = await self.req("GET", "/api/home/widgets", params={"acting_user_id": "7"})
        self.assertEqual(r.json(), {"widgets": []})

    async def test_data_fetches_pipeline_content_again_when_due(self):
        spec = {**kpi_spec("환율", 1300, "원"), "origins": [{"part": "cards", "kind": "web", "query": "오늘 원달러 환율", "view": "kpi",
                                                           "cards": [{"id": "k1", "key": "1달러"}], "fetched_at": "2026-11-13T09:00:00", "refs": []}]}
        with at(0):   # = 09:00 KST
            w = hw.create_widget("7", spec)
        fresh = {"ok": True, "kind": "numbers", "numbers": [{"label": "1달러", "value": 1350, "unit": "", "note": "11/13"}],
                 "refs": [{"kind": "web", "label": "news.example", "url": "https://news.example/fx", "page": None}]}
        path, me = f"/api/home/widgets/{w['key']}/data", {"acting_user_id": "7"}
        with patch.object(home_widgets_api.access, "resolve_eff", return_value=None) as eff:
            with at(0, 10), patch.object(widget_data, "run_web", return_value=fresh) as web:   # 10분 = 아직 / ten minutes: not yet
                r = await self.req("GET", path, params=me)
            self.assertEqual((web.call_count, eff.call_count, r.json()["model"]["kpis"][0]["text"]), (0, 0, "1,300원"))
            with at(1), patch.object(widget_data, "run_web", return_value=fresh) as web:   # 1시간 = 다시 / an hour: again
                r = await self.req("GET", path, params=me)
            web.assert_called_once_with("오늘 원달러 환율", "kpi", ["1달러"])
            eff.assert_called_once_with("7")
            m = r.json()["model"]
            self.assertEqual((m["kpis"][0]["text"], m["kpis"][0]["note"], m["origins"][0]["fetched_at"], m["refs"][0]["label"]),
                             ("1,350원", "11/13", "2026-11-13T10:00:00", "news.example"))
            after = hw.get_widget("7", w["key"])
            self.assertEqual((after["spec"]["kpis"][0]["value"], after["model"], after["updated_at"]), (1350.0, m, w["updated_at"]))
            # 같은 위젯을 다른 요청이 가져오는 중이면 다시 가져오지 않는다 / no second refresh while another request has it
            self.assertTrue(home_widgets_api._claim(w["key"]))
            try:
                with at(2), patch.object(widget_data, "run_web", return_value=fresh) as web:
                    r = await self.req("GET", path, params=me)
                self.assertEqual((r.status_code, web.call_count), (200, 0))
            finally:
                home_widgets_api._release(w["key"])
            # 못 가져오거나 오류가 나도 예전 내용으로 200, 그 위젯은 10분 쉰다(홈을 열 때마다 모델을 부르지 않게)
            # failures answer 200 with the old content, and the widget rests ten minutes (no model call per home load)
            with at(3), patch.object(widget_data, "run_web", side_effect=RuntimeError("down")):
                r = await self.req("GET", path, params=me)
            self.assertEqual((r.status_code, r.json()["model"]["kpis"][0]["text"]), (200, "1,350원"))
            with at(3, 5), patch.object(widget_data, "run_web", return_value=fresh) as web:
                r = await self.req("GET", path, params=me)
            self.assertEqual((r.status_code, web.call_count), (200, 0))
            home_widgets_api._rested.pop(w["key"], None)
            # 오래 걸리면 예전 내용으로 먼저 답하고, 일은 뒤에서 마쳐 저장한다 / a slow refresh answers with the old content and stores later
            import threading
            gate = threading.Event()

            def slow(*a):
                gate.wait(5)
                return {**fresh, "numbers": [{**fresh["numbers"][0], "value": 1400}]}
            with at(5), patch.object(widget_data, "REFRESH_WAIT", 0.2), patch.object(widget_data, "run_web", side_effect=slow):
                r = await self.req("GET", path, params=me)
                self.assertEqual(r.json()["model"]["kpis"][0]["text"], "1,350원")
                gate.set()
                for _ in range(50):
                    if hw.get_widget("7", w["key"])["spec"]["kpis"][0]["value"] == 1400:
                        break
                    await __import__("asyncio").sleep(0.05)
            self.assertEqual(hw.get_widget("7", w["key"])["spec"]["kpis"][0]["value"], 1400.0)

    async def test_errors_over_http(self):
        r = await self.req("POST", "/api/home/widgets", json={"acting_user_id": "7", "spec": {"title": "t", "view": {"type": "pie"}}})
        self.assertEqual((r.status_code, r.json()["detail"]), (422, "위젯에 보여 줄 내용이 없습니다. 위젯 에이전트로 차트나 KPI 카드를 먼저 만들어 주세요"))
        # 형식이 틀린 본문도 pydantic 의 영어 목록이 아니라 사용자 문장이다(계약 5절) / a mis-shaped body still answers with a user sentence
        for method, path, body, detail in (
                ("POST", "/api/home/widgets", {"acting_user_id": "7"}, "위젯 정의 형식이 올바르지 않습니다"),
                ("POST", "/api/home/widgets", {"acting_user_id": "7", "spec": None}, "위젯 정의 형식이 올바르지 않습니다"),
                ("POST", "/api/home/widgets", {"acting_user_id": "7", "spec": "글자"}, "위젯 정의 형식이 올바르지 않습니다"),
                ("POST", "/api/home/widgets", {"acting_user_id": "7", "spec": {}}, "위젯 제목을 입력해 주세요"),
                ("PUT", "/api/home/dashboard", {"acting_user_id": "7", "layout_type": 5, "items": []}, "레이아웃을 골라 주세요"),
                ("PUT", "/api/home/dashboard", {"acting_user_id": "7", "layout_type": "1:1:1", "items": {"wx": 1}}, "배치 형식이 올바르지 않습니다"),
                ("PUT", "/api/home/dashboard", {"acting_user_id": {"no": 7}, "layout_type": "1:1:1", "items": []}, "사용자 식별자가 올바르지 않습니다"),
                ("POST", "/api/home/widgets", {"acting_user_id": True, "spec": kpi_spec()}, "사용자 식별자가 올바르지 않습니다"),
                ("POST", "/api/home/widgets", {"acting_user_id": "7" * 65, "spec": kpi_spec()}, "사용자 식별자가 올바르지 않습니다")):
            r = await self.req(method, path, json=body)
            self.assertEqual((r.status_code, r.json()["detail"]), (422, detail), (method, path, body))
        r = await self.req("GET", "/api/home/dashboard", params={"acting_user_id": "7" * 65})
        self.assertEqual((r.status_code, r.json()["detail"]), (422, "사용자 식별자가 올바르지 않습니다"))
        # 신원은 글자나 정수: 숫자 7 과 글자 "7" 은 같은 사람, null 은 기본 사용자 / the identity is text or an integer: 7 and "7" are one person, null is the default user
        made = (await self.req("POST", "/api/home/widgets", json={"acting_user_id": 7, "spec": kpi_spec("숫자 신원")})).json()
        mine = (await self.req("GET", "/api/home/widgets", params={"acting_user_id": "7"})).json()["widgets"]
        self.assertEqual([w["key"] for w in mine], [made["key"]])
        r = await self.req("POST", "/api/home/widgets", json={"acting_user_id": None, "spec": kpi_spec("기본 사용자")})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([w["name"] for w in hw.list_widgets("")], ["기본 사용자"])
        b = (await self.req("POST", "/api/home/widgets", json={"acting_user_id": "12", "spec": kpi_spec("B 목표")})).json()
        for method, path, kw in (
                ("PUT", f"/api/home/widgets/{b['key']}", {"json": {"acting_user_id": "7", "spec": kpi_spec()}}),
                ("PUT", f"/api/home/widgets/{b['key']}", {"json": {"acting_user_id": "7", "spec": {}}}),   # 404 가 먼저 / 404 first
                ("DELETE", f"/api/home/widgets/{b['key']}", {"params": {"acting_user_id": "7"}}),
                ("GET", f"/api/home/widgets/{b['key']}/data", {"params": {"acting_user_id": "7"}}),
                ("PUT", "/api/home/widgets/cw_00000000", {"json": {"acting_user_id": "12", "spec": kpi_spec()}}),
                ("DELETE", "/api/home/widgets/cw_00000000", {"params": {"acting_user_id": "12"}}),
                ("GET", "/api/home/widgets/wx/data", {"params": {"acting_user_id": "12"}})):
            r = await self.req(method, path, **kw)
            self.assertEqual((r.status_code, r.json()["detail"]), (404, "존재하지 않는 위젯입니다"), (method, path))
        for key in ("wx", "gwb"):
            r = await self.req("DELETE", f"/api/home/widgets/{key}", params={"acting_user_id": "7"})
            self.assertEqual((r.status_code, r.json()["detail"]), (400, "기본 위젯은 삭제할 수 없습니다"))
        r = await self.req("GET", "/api/home/widgets", params={"acting_user_id": "12"})
        self.assertEqual([w["name"] for w in r.json()["widgets"]], ["B 목표"])   # B 의 위젯은 그대로 / untouched

    async def test_mis_shaped_chart_is_422_over_http(self):
        bad = chart_spec(filters=5)
        r = await self.req("POST", "/api/home/widgets", json={"acting_user_id": "7", "spec": bad})
        self.assertEqual((r.status_code, r.json()["detail"]), (422, "차트 설정 형식이 올바르지 않습니다"))
        r = await self.req("POST", "/api/home/agent/turn", json={"widget": bad, "message": "안녕"})
        self.assertEqual((r.status_code, r.json()["detail"]), (422, "차트 설정 형식이 올바르지 않습니다"))

    async def test_widget_cap_is_422_over_http(self):
        for i in range(hw.MAX_WIDGETS):
            hw.create_widget("7", kpi_spec(f"위젯 {i}"))
        r = await self.req("POST", "/api/home/widgets", json={"acting_user_id": "7", "spec": kpi_spec("31번째")})
        self.assertEqual((r.status_code, r.json()["detail"]), (422, "위젯은 한 사람당 30개까지 만들 수 있습니다"))


class SizeAndChatTests(unittest.TestCase):
    """2026-11-19: 만든 위젯의 처음 크기(정의 size — 위젯 에이전트의 실제 크기 미리보기) · 위젯 에이전트 대화 저장
    the made widget's first size (the definition's size, from the real-size preview) and the saved conversation"""

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        hw.init_home_widgets()

    def test_a_picked_size_is_fitted_kept_and_used_as_the_first_size(self):
        clean = hw.normalize_spec({**kpi_spec(), "size": {"w": 2.4, "h": 9}})
        self.assertEqual(clean["size"], {"w": 2, "h": 3})
        self.assertNotIn("size", hw.normalize_spec(kpi_spec()))   # 고르지 않았으면 없다 / absent unless picked
        self.assertEqual(hw.normalize_spec(clean), clean)          # 멱등 / idempotent
        for bad in ("2x1", {"w": "2", "h": 1}, {"w": True, "h": 1}, {"w": 1}, {"w": float("nan"), "h": 1}):
            with self.assertRaises(hw.SpecError, msg=bad):
                hw.normalize_spec({**kpi_spec(), "size": bad})
        model = hw.model_of(clean)
        self.assertEqual(model["size"], {"w": 2, "h": 3})
        self.assertNotIn("size", hw.model_of(hw.normalize_spec(kpi_spec())))
        self.assertEqual(hw.size_of("cw_1", model), {"w": 2, "h": 3, "min_w": 1, "max_w": 3, "min_h": 1, "max_h": 3})
        self.assertEqual(hw.size_of("cw_1", hw.model_of(hw.normalize_spec(CHART_SPEC)))["h"], 2)   # 고르지 않은 차트 = 1 × 2 / an unpicked chart
        state = hw.to_state(clean)
        state["title"] = "새 이름"
        self.assertEqual(hw.from_state(state, clean)["size"], {"w": 2, "h": 3})   # 도구는 크기를 바꾸지 않는다 / tools keep the size
        w = hw.create_widget("7", {**kpi_spec(), "size": {"w": 3, "h": 1}})
        mine = [x for x in hw.get_dashboard("7")["widgets"] if x["key"] == w["key"]][0]
        self.assertEqual((mine["size"]["w"], mine["size"]["h"]), (3, 1))

    def test_the_conversation_is_kept_per_widget_and_leaves_with_it(self):
        w = hw.create_widget("7", kpi_spec())
        self.assertEqual(hw.get_chat("7", w["key"]), {"key": w["key"], "chat": None, "updated_at": ""})
        chat = {"msgs": [{"role": "user", "text": "카드"}, {"role": "agent", "text": "넣었어요", "frame": {"cards": {}}}],
                "hist": [{"id": "u1", "label": "새 위젯", "at": "2026-11-19T10:00:00", "widget": {"v": 2, "title": "새 위젯"}},
                         {"id": "u2", "label": "깨진 것", "widget": {"v": 1}}, "글자"],
                "label": "카드 만들기", "at": "2026-11-19T10:01:00", "extra": 1}
        self.assertEqual(set(hw.save_chat("7", w["key"], chat)), {"key", "updated_at"})
        got = hw.get_chat("7", w["key"])["chat"]
        self.assertEqual(got["msgs"], chat["msgs"])
        self.assertEqual([(h["id"], h["label"], h["widget"]["title"]) for h in got["hist"]], [("u1", "새 위젯", "새 위젯")])   # 틀린 기록은 버린다 / broken states dropped
        self.assertEqual((got["v"], got["label"], got["at"], "extra" in got), (1, "카드 만들기", "2026-11-19T10:01:00", False))
        self.assertIsNone(hw.get_chat("8", w["key"]))              # 남의 위젯 / someone else's
        self.assertIsNone(hw.save_chat("8", w["key"], chat))
        self.assertIsNone(hw.save_chat("7", "cw_00000000", chat))  # 없는 위젯 / missing
        for bad in (None, [], {"msgs": "x"}, {"msgs": [1]}, {"msgs": [{"role": "user", "text": "a", "n": float("nan")}]}):
            with self.assertRaises(hw.WidgetError, msg=bad):
                hw.save_chat("7", w["key"], bad)
        with self.assertRaises(hw.WidgetError):
            hw.save_chat("7", w["key"], {"msgs": [{"role": "user", "text": "가" * (hw.MAX_CHAT_CHARS + 1)}]})
        hw.save_chat("7", w["key"], {"msgs": [{"role": "user", "text": str(i)} for i in range(70)]})
        self.assertEqual([m["text"] for m in hw.get_chat("7", w["key"])["chat"]["msgs"]][:2], ["10", "11"])   # 마지막 60줄 / the last 60
        # 역할 · 글 꼴이 틀린 줄은 버린다, 저장 글은 화면과 같은 촘촘한 JSON(크기를 같게 잰다) — 독립 검토
        # entries with a wrong role or text are dropped; the stored text is compact JSON measured like the screen (independent review)
        hw.save_chat("7", w["key"], {"msgs": [{"role": "system", "text": "x"}, {"role": "agent", "text": 3}, {"role": "agent"}, {"role": "user", "text": "남는다"}]})
        self.assertEqual([m.get("text") for m in hw.get_chat("7", w["key"])["chat"]["msgs"]], [None, "남는다"])
        with db._conn() as conn:
            stored = conn.execute("SELECT chat FROM home_widget_chats").fetchone()[0]
        self.assertNotIn('", "', stored)
        self.assertEqual(len(hw._chat_text(hw.normalize_chat({"msgs": [{"role": "user", "text": "가" * 10}]}))),  # noqa: SLF001
                         len(json.dumps({"v": 1, "msgs": [{"role": "user", "text": "가" * 10}], "hist": [], "label": "", "at": ""}, ensure_ascii=False, separators=(",", ":"))))
        self.assertTrue(hw.delete_widget("7", w["key"]))           # 위젯을 지우면 대화도 / deleting the widget removes its conversation
        with db._conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM home_widget_chats").fetchone()[0], 0)


class AgentStoreApiTests(unittest.IsolatedAsyncioTestCase):
    """대화 저장 · 미리보기 모델 · 지금 새로 가져오기 라우트(2026-11-19) / the conversation, preview-model and refresh-now routes"""

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        hw.init_home_widgets()
        self.app = FastAPI()
        self.app.include_router(home_widgets_api.router)

    async def req(self, method, path, json=None, params=None):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
            return await client.request(method, path, json=json, params=params)

    async def test_the_conversation_round_trip(self):
        key = hw.create_widget("7", kpi_spec())["key"]
        r = await self.req("GET", f"/api/home/agent/chat/{key}", params={"acting_user_id": "7"})
        self.assertEqual((r.status_code, r.json()["chat"]), (200, None))
        r = await self.req("PUT", f"/api/home/agent/chat/{key}", json={"acting_user_id": "7", "chat": {"msgs": [{"role": "user", "text": "a"}]}})
        self.assertEqual((r.status_code, set(r.json())), (200, {"key", "updated_at"}))
        r = await self.req("GET", f"/api/home/agent/chat/{key}", params={"acting_user_id": "7"})
        self.assertEqual(r.json()["chat"]["msgs"], [{"role": "user", "text": "a"}])
        r = await self.req("GET", f"/api/home/agent/chat/{key}", params={"acting_user_id": "8"})
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "존재하지 않는 위젯입니다"))
        r = await self.req("PUT", f"/api/home/agent/chat/{key}", json={"acting_user_id": "8", "chat": {"msgs": []}})
        self.assertEqual(r.status_code, 404)
        r = await self.req("PUT", f"/api/home/agent/chat/{key}", json={"acting_user_id": "7", "chat": {"msgs": 3}})
        self.assertEqual((r.status_code, r.json()["detail"]), (422, "대화 기록 형식이 올바르지 않습니다"))

    async def test_the_preview_model_of_a_draft(self):
        r = await self.req("POST", "/api/home/agent/model", json={"widget": CHART_SPEC})
        self.assertEqual((r.status_code, r.json()["model"]["chart"]["type"], r.json()["widget"]["title"]), (200, "bar", "월별 매출"))
        r = await self.req("POST", "/api/home/agent/model", json={"widget": {"v": 1}})
        self.assertEqual(r.status_code, 422)

    async def test_refreshing_now_reruns_only_signed_sql_and_returns_a_draft(self):
        r = await self.req("POST", "/api/home/agent/refresh", json={"acting_user_id": "7", "widget": kpi_spec()})
        self.assertEqual((r.status_code, r.json()["changed"]), (200, False))   # 출처가 없다 / no origins
        origin = {"part": "source", "kind": "data", "query": "월별 매출", "view": "chart", "sql": "SELECT 1", "sig": "bad", "tables": ["t"],
                  "refs": [], "fetched_at": "2026-11-19T09:00:00"}
        seen = []

        def fake(spec, eff, force=False):
            seen.append((spec["origins"][0]["sql"], force))
            return {**spec, "title": "새로 가져옴"}
        with patch.object(home_widgets_api.widget_data, "refresh", side_effect=fake), \
                patch.object(home_widgets_api.access, "resolve_eff", return_value=None):
            r = await self.req("POST", "/api/home/agent/refresh", json={"acting_user_id": "7", "widget": {**CHART_SPEC, "origins": [origin]}})
            self.assertEqual((r.status_code, r.json()["changed"], r.json()["widget"]["title"]), (200, True, "새로 가져옴"))
            signed = {**origin, "sig": hw.sign_sql("7", "SELECT 1")}
            await self.req("POST", "/api/home/agent/refresh", json={"acting_user_id": "7", "widget": {**CHART_SPEC, "origins": [signed]}})
        self.assertEqual(seen, [("", True), ("SELECT 1", True)])   # 서명 없는 SQL 은 버린다 / unsigned SQL is dropped
        with patch.object(home_widgets_api.widget_data, "refresh", side_effect=RuntimeError("down")):
            r = await self.req("POST", "/api/home/agent/refresh", json={"acting_user_id": "7", "widget": CHART_SPEC})
        self.assertEqual((r.status_code, r.json()["detail"]), (503, home_widgets_api.REFRESH_DOWN))


class MainWiringTests(unittest.TestCase):
    """app.main 은 들여오지 않는다(들여오기만 해도 실 DB 를 정비한다): 소스를 읽고, /home 함수만 떼어 실행한다.
    app.main is never imported (importing alone repairs the real DB): read its source and run only the /home function."""

    def setUp(self):
        self.tree = ast.parse((ROOT / "app" / "main.py").read_text(encoding="utf-8"))

    def test_store_is_initialized_and_router_included(self):
        imported = {a.name for n in self.tree.body if isinstance(n, ast.ImportFrom) and n.module == "app" for a in n.names}
        self.assertTrue({"home_widgets", "home_widgets_api"} <= imported)
        calls = {ast.unparse(n.value) for n in self.tree.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)}
        self.assertIn("home_widgets.init_home_widgets()", calls)
        self.assertIn("app.include_router(home_widgets_api.router)", calls)

    def test_home_route_injects_chart_drawing_dashboard_and_agent_before_home_live(self):
        pick = [n for n in self.tree.body if isinstance(n, ast.FunctionDef) and n.name in ("home", "_kst_head")]
        self.assertEqual(len(pick), 2)
        for n in pick:
            n.decorator_list = []
        with tempfile.TemporaryDirectory() as tmp:
            static = Path(tmp) / "static"
            static.mkdir()
            (static / "home-live.js").write_text("", encoding="utf-8")
            (static / "report_dash.js").write_text("", encoding="utf-8")
            page = Path(tmp) / "home.html"
            page.write_text("<html><head></head><body><p>홈</p></body></html>", encoding="utf-8")
            ns = {"STATIC_DIR": static, "HOME_PATH": page, "HOME_REPO_PATH": Path(tmp) / "none.html", "re": re}
            exec(compile(ast.Module(body=pick, type_ignores=[]), "main_home_route", "exec"), ns)   # noqa: S102
            live = r'<script src="/static/home-live\.js\?v=\d+"></script></body></html>$'
            tag = lambda name: rf'<script src="/static/{re.escape(name)}\?v=\d+"></script>'   # noqa: E731
            before = ns["home"]()
            self.assertRegex(before, r"<p>홈</p>" + live)   # home_dash.js 가 없으면 종전 그대로 / unchanged without home_dash.js
            self.assertNotIn("report_dash", before)
            (static / "home_dash.js").write_text("", encoding="utf-8")
            self.assertRegex(ns["home"](), r"<p>홈</p>" + tag("report_dash.js") + tag("home_dash.js") + live)
            (static / "widget_agent.js").write_text("", encoding="utf-8")
            self.assertRegex(ns["home"](), r"<p>홈</p>" + tag("report_dash.js") + tag("home_dash.js") + tag("widget_agent.js") + live)


if __name__ == "__main__":
    unittest.main()
