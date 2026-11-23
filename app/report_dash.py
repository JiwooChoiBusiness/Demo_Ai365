"""리포트 에이전트 대시보드(2026-09-18) — 상태 모델·정규화·집계·세션 저장소.

종전 리포트는 LLM 이 차트 숫자(x·values)까지 만들어 주고 그 그림만 저장했다 — 데이터와 출처가 남지 않아 필터·기준선·
다시 열어 수정이 구조적으로 불가능했다. 여기서는 **데이터(Source)와 차트 설정을 분리**한다.
- Source: 조회 결과 한 덩어리(컬럼·행) + 출처(조회 SQL·원본 테이블·조회 시각·어디서 왔는지).
  **리포트(차트) 하나 = Source 하나**(2026-09-19 사용자 지시 — 실제 제품의 Source 탭이 BI 하나씩이다): 이미 차트가 있는 Source 로
  새 차트를 만들면 그 데이터를 새 Source 로 복제해(출처 유지, origin.clone_of) 새 탭이 생긴다. Source 는 지우지 않는다.
- 차트: "어느 Source 의 어느 컬럼을 어떻게 집계해 어떤 모양으로" 라는 선언. 숫자는 compute() 가 계산한다(프런트의
  ai365RdCompute 와 같은 규칙) — 그래서 필터는 LLM 없이 즉시 반응하고, 계산 실수가 없다.
- 필터: **차트(BI)마다 따로** 갖는다(2026-09-19 사용자 지시 — 대시보드 전체 필터는 기준이 모호했다). 컬럼 + 고른 값이고
  그 차트의 값·표·통계 기준선에만 적용된다. 같은 컬럼을 여러 차트에서 고르고 싶으면 차트마다 하나씩 만든다.
- 세션: 대시보드 하나 = 상태 + 그 대시보드 전용 대화. 첫 지시 전까지는 초안(report_dash.state)이고, 첫 지시 뒤에는
  내 보관함 글(boards 'me:<owner>')이 상태의 단일 원본이 된다. 대화는 세션 행에만 남아 공유·복사로 새지 않는다.
옛 소비자(게시판 카드·상세, 리소스 센터 보관소)가 그대로 그릴 수 있게 저장 데이터에는 계산된 타일(items)을 함께 싣는다.

Visualize Agent 확장(2026-09-21) — 원칙은 같다: LLM 은 무엇을 할지만 고르고 숫자·판정은 여기서 한다(프런트와 같은 규칙, 같은 자료로 테스트).
- 기간 컬럼 판정(source.periods) · 계산 값(y[].calc) · 조건부 강조(chart.highlights → compute().marks) · 드릴다운 순서(chart.drill)
- 복제본은 원본 데이터를 가리키기만 한다(link_clones / pack_state) · 차트 복제 + 비교 묶음(chart.compare) · 메모(chart.notes) · KPI 카드 = 요약 숫자(state.kpis)
- KPI 카드(2026-10-12): 첫 화면에 자동으로 놓지 않는다 — 사용자가 [+ KPI 카드] · [추천 채우기] · 대화로 요청해야 생기고, 카드 편집(put_kpi)으로
  이름 · 데이터(Source · 컬럼 · 집계) 또는 직접 적은 숫자(value) · 단위 · 연결 차트 · 직전 기간 대비 · 설명(note)을 바꾼다
- 추세선·간단한 예측(chart.trend → compute().trend) · 컬럼 종류별 필터(filter.range) · 테마(state.theme, 색 묶음 'theme')
- 버전(2026-10-13): 답변마다 그 시점의 제목 · 차트 설정 · KPI 카드 · 테마를 V1, V2… 로 남긴다(데이터 제외, 최대 MAX_VERSIONS 개).
  미리보기는 지금 데이터(Source)로 그리고, [이 버전으로 이어가기]는 작업본을 그 버전으로 바꾼다(되돌리기 가능)
"""
# Visualize Agent extensions (2026-09-21) keep the principle: the LLM picks what to do, this module does the numbers and the
# judging (same rules as the front end, tested on shared fixtures): period columns, calculated values, conditional highlights,
# the drill path; clones that only point at their root's data, chart duplication with compare groups, notes, summary numbers;
# trend line and simple forecast, filters shaped by the column kind, and the dashboard theme.
# Versions (2026-10-13): each answer keeps that moment's title, chart specs, KPI cards and theme as V1, V2… (no row data,
# up to MAX_VERSIONS). A preview draws one on the current sources; continuing from one makes it the working copy (undoable).
# Report-agent dashboards (2026-09-18) — state model, normalization, aggregation and the session store.
# The old report let the LLM emit the chart numbers and stored only that picture, so filters, reference lines and
# re-editing were impossible. Here data (sources) and chart specs are separate: a source is one query result plus
# its provenance, a chart declares which columns of which source are aggregated how, and compute() does the math
# (same rules as the front end's ai365RdCompute) — filters react without the LLM and the numbers are never guessed.
# One report (chart) = one source (2026-09-19, user decision; the real product's Source tabs hold one BI each): creating
# a chart from a source that already has one clones that data into a new source (provenance kept, origin.clone_of),
# which becomes a new tab. Sources are never removed.
# Filters belong to a chart (2026-09-19, user decision: a dashboard-wide filter had no clear scope): a column plus the
# picked values, applied only to that chart's values, table and statistic reference lines.
# A session is one dashboard = state + its own conversation. It is a draft until the first instruction; after that
# the library post (boards 'me:<owner>') is the single source of truth for the state, while the conversation stays
# in the session row so it never leaks through sharing or copying. Saved data also carries computed tiles (items)
# so older consumers (board cards/detail, the Resource Center library) keep rendering.

import hashlib
import json
import math
import re
import sqlite3
import statistics
import uuid
from datetime import datetime, timedelta

from app import db, kst

CHART_TYPES = ("bar", "hbar", "line", "area", "pie", "donut", "kpi")
AGGS = ("sum", "avg", "count", "min", "max", "first")
PALETTES = ("indigo", "ocean", "sunset", "forest", "mono", "pastel", "theme")   # theme = 대시보드 테마의 대표 색에서 만든 색 / colours derived from the dashboard theme
LEGENDS = ("bottom", "top", "right", "none")
SIZES = ("half", "full")
REF_STATS = ("avg", "median", "min", "max")
SORT_BY = ("none", "x", "y")

# 계산 값(2026-09-21): 데이터에 없는 값을 **코드가** 계산해 계열로 보여 준다 — LLM 은 어떤 계산을 어느 컬럼에 쓸지만 고른다.
# Calculated values (2026-09-21): values that are not in the data are computed by code; the LLM only picks which one.
CALCS = ("share", "cum_share", "cumsum", "pct_prev", "diff_prev", "moving_avg", "yoy", "rank", "ratio", "ratio_pct", "diff")
SEQ_CALCS = ("pct_prev", "diff_prev", "moving_avg", "yoy")      # x 축이 기간일 때만 뜻이 있는 계산 / only meaningful on a period axis
ORDER_CALCS = SEQ_CALCS + ("cumsum", "cum_share")               # 순서에 따라 값이 달라지는 계산(정렬 뒤에 계산) / order-dependent, computed after sorting
PAIR_CALCS = ("ratio", "ratio_pct", "diff")                     # 두 집계 값으로 계산(by) / computed from two aggregates
PCT_CALCS = ("share", "cum_share", "pct_prev", "yoy", "ratio_pct")
CALC_LABEL = {"share": "구성비", "cum_share": "누적 비중", "cumsum": "누계", "pct_prev": "증감률", "diff_prev": "증감",
              "moving_avg": "이동 평균", "yoy": "전년 대비", "rank": "순위", "ratio": "비율", "ratio_pct": "비율", "diff": "차이"}
PERIOD_KINDS = ("year", "quarter", "month", "week", "date")

# 조건부 강조(2026-09-21): 조건에 맞는 막대·점만 색을 달리한다 — 판정은 코드가 한다 / conditional highlights, judged by code
HL_KINDS = ("value", "stat", "ref", "top", "bottom", "items")
HL_OPS = ("lt", "lte", "gt", "gte")
HL_STATS = ("avg", "median")
HL_COLORS = {"red": "#E03131", "green": "#2F9E44", "amber": "#F08C00", "blue": "#1C7ED6", "gray": "#868E96"}

MAX_SOURCES = 12         # = MAX_CHARTS(리포트 하나 = Source 하나) / one source per report
MAX_SOURCE_ROWS = 2000
MAX_SOURCE_COLS = 40
MAX_CELL = 300
MAX_CHARTS = 12
MAX_Y = 6
MAX_GROUP_SERIES = 8
MAX_X_ITEMS = 40
MAX_PIE_SLICES = 8
MAX_REF_LINES = 4
MAX_FILTERS = 4          # 차트 하나의 필터 수 / filters per chart
MAX_UNDO = 10
MAX_VERSIONS = 40        # 답변마다 남기는 버전(V1, V2…) 수: 넘으면 오래된 것부터 버리고 번호는 이어 간다 / versions kept; the oldest go first, numbering continues
MAX_VERSION_LABEL = 40   # 버전 이름 길이 / version label length
MAX_HIGHLIGHTS = 3       # 차트 하나의 강조 규칙 수 / highlight rules per chart
MAX_DRILL = 3            # 드릴다운 단계 수 / drill-down levels
MAX_NOTES = 6            # 차트 하나의 메모(주석) 수 / notes per chart
MAX_NOTE_TEXT = 30
MAX_KPIS = 8             # 대시보드 맨 위 KPI 카드(요약 숫자) 수 / KPI cards (summary numbers) on top of a dashboard
MAX_KPI_NOTE = 40        # KPI 카드 아래 한 줄 설명 / the one-line note under a KPI card
MAX_FORECAST = 6         # 예측으로 이어 그리는 기간 수 / forecast horizon
MIN_FORECAST_POINTS = 6  # 이보다 점이 적으면 예측하지 않는다 / no forecast below this many points
MAX_FILTER_LAST = 120
MAX_FILTER_SELECTED = 200
MAX_MESSAGES = 200
MAX_TITLE = 120
DRAFT_TTL_HOURS = 24
OTHERS_LABEL = "기타"


def _now() -> str:
    return kst.now_iso()


def _s(v, n: int) -> str:
    return str(v if v is not None else "").strip()[:n]


# ────────────────────────────────────────────────────────
# 값 도우미(프런트와 같은 규칙) / value helpers (same rules as the front end)
# ────────────────────────────────────────────────────────

def num(v) -> float | None:
    """숫자로 읽기 — 천 단위 쉼표·끝의 % 허용, 불리언·빈 값은 숫자가 아니다 / parse a number (commas and a trailing % allowed)"""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    if isinstance(v, str):
        s = v.replace(",", "").strip()
        if s.endswith("%"):
            s = s[:-1].strip()
        if not s:
            return None
        try:
            f = float(s)
        except ValueError:
            return None
        return f if math.isfinite(f) else None
    return None


def key(v) -> str:
    """범주 키 — JS 의 String(v) 와 같은 글자가 나오게 한다(2025.0 → '2025', True → 'true') / category key matching JS String(v)"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    return str(v)


def _round(v: float) -> float:
    return round(float(v), 6)


def _cell(v):
    if v is None or isinstance(v, (bool, int)):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    return str(v)[:MAX_CELL]


def column_types(columns: list[str], rows: list[list]) -> dict[str, str]:
    """컬럼 종류 추정 — 값의 90% 이상이 숫자면 number, 아니면 text / infer column kinds (number when ≥90% numeric)"""
    out = {}
    for ci, col in enumerate(columns):
        seen = hit = 0
        for r in rows:
            v = r[ci] if ci < len(r) else None
            if v is None or v == "":
                continue
            seen += 1
            if num(v) is not None:
                hit += 1
        out[col] = "number" if seen and hit / seen >= 0.9 else "text"
    return out


# ────────────────────────────────────────────────────────
# 기간 컬럼 판정(2026-09-21) — 전월 대비·누계·추세선·기간 필터의 공통 기반. 프런트 rdParsePeriod 와 같은 규칙이어야 한다.
# 값 모양으로 읽는다: 2026-03-15 · 2026-03 · 2026년 3월 · 3월 · 2026 Q1 · 1분기 · 12주차 · 2026년. 숫자뿐인 값(2026 · 3 · 202603)은
# 뜻이 모호하므로 **컬럼 이름이 알려 준 종류로만** 읽는다(연도 → 연, 월 → 월, 일자 → 일).
# Period columns (2026-09-21) — the shared base for previous-period change, running totals, trend lines and period filters;
# the same rules as the front end's rdParsePeriod. Labels are read by shape; bare digits are ambiguous, so they are read
# only as the kind the column name hints at.
# ────────────────────────────────────────────────────────

_A = re.ASCII | re.I
_P_DATE = re.compile(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})(?:[T ].*)?$", _A)
_P_DATE_KO = re.compile(r"^(\d{4})[ \t]*년[ \t]*(\d{1,2})[ \t]*월[ \t]*(\d{1,2})[ \t]*일$", _A)
_P_YM = re.compile(r"^(\d{4})[-./](\d{1,2})$", _A)
_P_YM_KO = re.compile(r"^(\d{4})[ \t]*년[ \t]*(\d{1,2})[ \t]*월$", _A)
_P_Q = re.compile(r"^(?:(\d{4})[ \t]*년?[ \t]*[-/]?[ \t]*)?(?:Q([1-4])|([1-4])[ \t]*분기|([1-4])Q)$", _A)
_P_W = re.compile(r"^(?:(\d{4})[ \t]*년?[ \t]*[-/]?[ \t]*)?(?:W(\d{1,2})|(\d{1,2})[ \t]*주차?)$", _A)
_P_M = re.compile(r"^(\d{1,2})[ \t]*월$", _A)
_P_Y = re.compile(r"^(\d{4})[ \t]*년$", _A)
_P_DIGITS = re.compile(r"^\d+$", _A)
_PERIOD_HINTS = (("date", re.compile(r"일자|날짜|date|day|일$", re.I)), ("week", re.compile(r"주차|week", re.I)),
                 ("quarter", re.compile(r"분기|quarter|qtr", re.I)), ("month", re.compile(r"월|month", re.I)),
                 ("year", re.compile(r"연도|년도|year|yr|^년$", re.I)))


def period_hint(col: str) -> str:
    """컬럼 이름이 알려 주는 기간 종류('' = 모름) / the period kind a column name hints at"""
    return next((kind for kind, pat in _PERIOD_HINTS if pat.search(str(col))), "")


def parse_period(label, hint: str = "") -> tuple[str, int, int] | None:
    """기간 라벨 → (종류, 연, 순번). 연이 없으면 0, 순번은 분기·월·주 번호 또는 월*100+일. 기간이 아니면 None."""
    # A period label → (kind, year, ordinal): year 0 when absent; the ordinal is the quarter/month/week number or month*100+day.
    s = key(label).strip()
    if not s:
        return None
    m = _P_DATE.match(s) or _P_DATE_KO.match(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return ("date", y, mo * 100 + d) if 1 <= mo <= 12 and 1 <= d <= 31 else None
    m = _P_YM.match(s) or _P_YM_KO.match(s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        return ("month", y, mo) if 1 <= mo <= 12 else None
    m = _P_Q.match(s)
    if m:
        return ("quarter", int(m.group(1) or 0), int(m.group(2) or m.group(3) or m.group(4)))
    m = _P_W.match(s)
    if m:
        w = int(m.group(2) or m.group(3))
        return ("week", int(m.group(1) or 0), w) if 1 <= w <= 53 else None
    m = _P_M.match(s)
    if m:
        return ("month", 0, int(m.group(1))) if 1 <= int(m.group(1)) <= 12 else None
    m = _P_Y.match(s)
    if m:
        return ("year", int(m.group(1)), 0)
    if _P_DIGITS.match(s) and len(s) <= 8:
        n = int(s)
        if hint == "year" and len(s) == 4 and 1900 <= n <= 2100:
            return ("year", n, 0)
        if hint == "month" and len(s) <= 2 and 1 <= n <= 12:
            return ("month", 0, n)
        if hint == "month" and len(s) == 6 and 1 <= n % 100 <= 12:
            return ("month", n // 100, n % 100)
        if hint == "quarter" and len(s) == 1 and 1 <= n <= 4:
            return ("quarter", 0, n)
        if hint == "week" and len(s) <= 2 and 1 <= n <= 53:
            return ("week", 0, n)
        if hint == "date" and len(s) == 8 and 1 <= n // 100 % 100 <= 12 and 1 <= n % 100 <= 31:
            return ("date", n // 10000, n % 10000)
    return None


def period_key(label, kind: str) -> tuple[int, int] | None:
    """그 종류의 기간 컬럼에서 라벨의 정렬 키 / the sort key of a label inside a period column of that kind"""
    p = parse_period(label, kind)
    return (p[1], p[2]) if p is not None and p[0] == kind else None


_DIGITS = re.compile(r"\d+", re.ASCII)


def _ordinal(y: int, md: int) -> int | None:
    try:
        return datetime(y, md // 100, md % 100).toordinal()
    except ValueError:
        return None


def next_period_labels(labels: list[str], kind: str, count: int) -> list[str]:
    """기간 축의 다음 라벨들 — 마지막 라벨의 모양(구분자·자릿수)을 그대로 잇는다: 2026-12 → 2027-01, 12월 → 1월, 2026 Q4 → 2027 Q1.
    일자는 점 사이의 간격(중앙값, 일 단위)만큼 나아간다. 프런트 rdNextPeriodLabels 와 같은 규칙."""
    # The next labels of a period axis, continuing the shape (separators, zero padding) of the last label. Dates advance by the
    # median gap between points, in days. Same rules as the front end's rdNextPeriodLabels.
    parsed = [(lb, parse_period(lb, kind)) for lb in labels]
    parsed = [(lb, p) for lb, p in parsed if p is not None and p[0] == kind]
    if not parsed or count < 1:
        return []
    last, (_, y, n) = parsed[-1]
    groups = _DIGITS.findall(last)
    # 자릿수 맞춤(01, 02 …)은 같은 자리의 어느 라벨이든 0 으로 시작하면 쓴다 / zero padding when any label pads that position
    # — 0 으로 시작하는 라벨이 안 보여도(11, 12 뿐) 한글 단위 없이 늘 두 자리면 맞춤으로 본다(2025-12 → 2026-01, 12월 → 1월)
    #   when no label shows a leading zero (only 11, 12), always-two-digit groups without Korean units count as padded
    found = [_DIGITS.findall(lb) for lb, _ in parsed]
    plain = not re.search(r"[가-힣]", last)
    padded = [any(len(f[i]) > 1 and f[i].startswith("0") for f in found if len(f) > i)
              or (plain and all(len(f[i]) == 2 for f in found if len(f) > i)) for i in range(len(groups))]
    gap = 1
    if kind == "date":
        days = [d for d in (_ordinal(p[1], p[2]) for _, p in parsed) if d is not None]
        diffs = sorted(b - a for a, b in zip(days, days[1:]) if b > a)
        gap = diffs[len(diffs) // 2] if diffs else 1
    out = []
    for _ in range(count):
        if kind == "year":
            y += 1
            nums = [y]
        elif kind in ("month", "quarter", "week"):
            cycle = {"month": 12, "quarter": 4, "week": 52}[kind]
            n += 1
            if n > cycle:
                n, y = 1, (y + 1 if y else 0)
            nums = [y * 100 + n] if kind == "month" and len(groups) == 1 and len(groups[0]) == 6 else ([y, n] if len(groups) >= 2 else [n])
        else:
            day = _ordinal(y, n)
            if day is None:
                break
            d = datetime.fromordinal(day + gap)
            y, n = d.year, d.month * 100 + d.day
            nums = [y * 10000 + n] if len(groups[0]) == 8 else [y, n // 100, n % 100]
        it = iter(enumerate(nums))

        def fill(m, it=it):
            nxt = next(it, None)
            if nxt is None:
                return m.group(0)
            i, v = nxt
            return str(v).zfill(len(m.group(0))) if i < len(padded) and padded[i] else str(v)

        out.append(_DIGITS.sub(fill, last))
    return out


def period_columns(columns: list[str], rows: list[list]) -> dict[str, str]:
    """기간 컬럼 찾기 — 서로 다른 값의 90% 이상이 같은 종류의 기간으로 읽히면 그 종류 / {column: kind} when ≥90% of the distinct labels parse as one kind"""
    out = {}
    for ci, col in enumerate(columns):
        hint, labels, seen = period_hint(col), [], set()
        for r in rows:
            v = r[ci] if ci < len(r) else None
            if v is None or v == "":
                continue
            k = key(v)
            if k not in seen:
                seen.add(k)
                labels.append(k)
                if len(labels) >= 400:
                    break
        kinds = [p[0] for p in (parse_period(k, hint) for k in labels) if p is not None]
        if labels and len(kinds) / len(labels) >= 0.9 and len(set(kinds)) == 1:
            out[col] = kinds[0]
    return out


def _next_id(prefix: str, used: set[str]) -> str:
    n = 1
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


def resolve_col(name, columns: list[str]) -> str | None:
    """LLM 이 준 컬럼 이름을 실제 컬럼으로 — 정확히, 대소문자 무시, 공백·밑줄 무시 순 / map a model-given name to a real column"""
    n = str(name or "").strip()
    if not n:
        return None
    if n in columns:
        return n
    low = {c.lower(): c for c in columns}
    if n.lower() in low:
        return low[n.lower()]
    squash = lambda s: re.sub(r"[\s_\-]+", "", s.lower())   # noqa: E731
    sq = {squash(c): c for c in columns}
    return sq.get(squash(n))


# ────────────────────────────────────────────────────────
# 정규화 / normalization
# ────────────────────────────────────────────────────────

def norm_source(raw: dict, used: set[str]) -> dict:
    """Source 하나 — 컬럼·행 상한, 출처 메타 화이트리스트. 컬럼이 없으면 ValueError."""
    # One source — caps on columns/rows and a whitelist of provenance meta. ValueError when there are no columns.
    raw = raw if isinstance(raw, dict) else {}
    cols_in = [str(c) for c in (raw.get("columns") or []) if str(c).strip()][:MAX_SOURCE_COLS]
    if not cols_in:
        raise ValueError("Source 에 컬럼이 없습니다")
    columns, seen = [], set()
    for c in cols_in:   # 같은 이름은 뒤에 번호 / duplicate names get a numeric suffix
        name, k = c.strip()[:80], 2
        while name in seen:
            name = f"{c.strip()[:76]}_{k}"
            k += 1
        seen.add(name)
        columns.append(name)
    rows = []
    for r in (raw.get("rows") or [])[:MAX_SOURCE_ROWS]:
        r = list(r) if isinstance(r, (list, tuple)) else [r]
        rows.append([_cell(r[i]) if i < len(r) else None for i in range(len(columns))])
    sid = str(raw.get("id") or "")
    if not re.fullmatch(r"s\d{1,3}", sid) or sid in used:
        sid = _next_id("s", used)
    used.add(sid)
    origin = raw.get("origin") if isinstance(raw.get("origin"), dict) else {}
    kind = origin.get("kind") if origin.get("kind") in ("chat", "agent", "legacy") else "chat"
    clone_of = str(origin.get("clone_of") or "")
    return {
        "id": sid,
        "name": f"Source {sid[1:]}",
        "label": _s(raw.get("label"), 80),
        "columns": columns,
        "rows": rows,
        "types": column_types(columns, rows),
        "periods": period_columns(columns, rows),   # 기간 컬럼 {컬럼: year|quarter|month|week|date} / period columns
        "sql": _s(raw.get("sql"), 4000),
        "tables": [_s(t, 80) for t in (raw.get("tables") or []) if _s(t, 80)][:12],
        "fetched_at": _s(raw.get("fetched_at"), 40) or _now(),
        "origin": {"kind": kind, "note": _s(origin.get("note"), 200), "chat_id": _s(origin.get("chat_id"), 60),
                   "clone_of": clone_of if re.fullmatch(r"s\d{1,3}", clone_of) and clone_of != sid else ""},
    }


def lineage(source: dict) -> str:
    """같은 데이터의 뿌리 Source id(복제본이면 원본, 아니면 자기) / the root source of the same data"""
    return source["origin"].get("clone_of") or source["id"]


# 복제본은 원본 데이터를 가리키기만 한다(2026-09-21 사용자 지시) — 메모리에서는 원본의 컬럼·행 객체를 그대로 물고(복사 없음),
# 저장·전송할 때는 행을 비운다(pack_state). 읽을 때 normalize_state 가 다시 잇는다. 리포트를 몇 개 복제해도 데이터는 한 벌이다.
# A clone only points at its root's data (2026-09-21, user decision): in memory it holds the root's column/row objects (no
# copy) and its rows are emptied for storage and transport (pack_state); normalize_state links them again on load.
_LINKED = ("columns", "rows", "types", "periods", "sql", "tables", "fetched_at")


def link_clones(sources: list[dict]) -> None:
    by_id = {s["id"]: s for s in sources}
    for s in sources:
        root = by_id.get(s["origin"].get("clone_of") or "")
        if root is not None and root is not s and not root["origin"].get("clone_of"):
            for k in _LINKED:
                s[k] = root[k]


def pack_sources(sources: list[dict]) -> list[dict]:
    """저장·전송용 — 원본이 함께 있는 복제본은 행을 비운다 / for storage and transport: a clone whose root is present carries no rows"""
    roots = {s["id"] for s in sources if not s["origin"].get("clone_of")}
    return [{**s, "rows": []} if s["origin"].get("clone_of") in roots else s for s in sources]


def pack_state(state: dict) -> dict:
    return {**state, "sources": pack_sources(state["sources"])}


def source_for_new_chart(state: dict, src_id: str) -> tuple[str, bool]:
    """새 리포트(차트)가 쓸 Source — 그 Source 에 아직 차트가 없으면 그대로, 있으면 같은 데이터의 빈 Source 를 찾고, 그것도 없으면
    데이터를 새 Source 로 복제한다(새 탭). 상한에 닿으면 어쩔 수 없이 같은 Source 를 같이 쓴다. 반환: (Source id, 새로 복제했는가)"""
    # The source a new report (chart) uses: the given one while it has no chart, else a chartless source of the same data, else
    # a fresh clone (a new tab). At the cap the source is shared. Returns (source id, whether a clone was made).
    taken = {c["source"] for c in state["charts"]}
    base = next((s for s in state["sources"] if s["id"] == src_id), None)
    if base is None or src_id not in taken:
        return src_id, False
    root = lineage(base)
    free = next((s for s in state["sources"] if lineage(s) == root and s["id"] not in taken), None)
    if free is not None:
        return free["id"], False
    if len(state["sources"]) >= MAX_SOURCES:
        return src_id, False
    root_src = next((s for s in state["sources"] if s["id"] == root), base)
    new_id = _next_id("s", {s["id"] for s in state["sources"]})
    # 데이터는 복사하지 않는다 — 원본의 컬럼·행 객체를 그대로 가리킨다 / no copy: the clone points at the root's column and row objects
    clone = {**root_src, "id": new_id, "name": f"Source {new_id[1:]}", "label": "", "origin": {**base["origin"], "clone_of": root}}
    state["sources"].append(clone)
    return clone["id"], True


_RATE_COL = re.compile(r"률|율|비중|평균|단가|점수|percent|rate|ratio|avg|pct|%", re.I)
# 더하면 틀리는 비율 컬럼 — 도구 호출과 KPI 카드 편집이 sum 을 거절할 때 쓴다(저장분은 그대로 연다)
# Rate columns that are wrong when summed; tool calls and KPI card edits refuse sum (saved dashboards load as they are)
RATE_ONLY = re.compile(r"(률|율|비중)\s*(\(?%\)?)?$|%|(^|[_\s])(rate|ratio|share|pct|percent)([_\s]|$)", re.I)


def _norm_y(raw, columns: list[str], types: dict, default_type: str) -> dict | None:
    raw = raw if isinstance(raw, dict) else {"col": raw}
    name_in = raw.get("col") if raw.get("col") is not None else raw.get("column")
    if str(name_in or "").strip() == "*":
        col, agg = "*", "count"
    else:
        col = resolve_col(name_in, columns)
        if col is None:
            return None
        # 집계를 안 줬으면 이름으로 고른다 — 비율·평균처럼 더하면 안 되는 값은 avg / no agg given: rate-like columns average
        agg = raw.get("agg") if raw.get("agg") in AGGS else ("avg" if _RATE_COL.search(str(col)) else "sum")
        if types.get(col) != "number" and agg != "count":
            agg = "count"   # 숫자가 아닌 컬럼은 셀 수만 있다 / a non-numeric column can only be counted
    base = "건수" if col == "*" else col
    out = {"col": col, "agg": agg, "name": _s(raw.get("name"), 60) or base,
           "type": raw.get("type") if raw.get("type") in ("bar", "line") else default_type,
           "axis": 1 if raw.get("axis") in (1, "1", 1.0) else 0}
    # 계산 값 — 있을 때만 키를 단다(옛 저장분·옛 테스트와 같은 모양 유지) / calc keys exist only when set (older shapes stay valid)
    calc = raw.get("calc") if raw.get("calc") in CALCS else None
    if calc in PAIR_CALCS:
        by_in = raw.get("by") if isinstance(raw.get("by"), dict) else {"col": raw.get("by_column"), "agg": raw.get("by_agg")}
        by = _norm_y({"col": by_in.get("col") if by_in.get("col") is not None else by_in.get("column"), "agg": by_in.get("agg")},
                     columns, types, default_type)
        if by is None:
            raise ValueError("비율·차이 계산에는 둘째 값 컬럼(by_column)이 필요합니다. 쓸 수 있는 컬럼: " + ", ".join(columns))
        out["by"] = {"col": by["col"], "agg": by["agg"]}
        if not _s(raw.get("name"), 60):
            out["name"] = f"{base} {'−' if calc == 'diff' else '÷'} {'건수' if by['col'] == '*' else by['col']}"[:60]
    elif calc and not _s(raw.get("name"), 60):
        out["name"] = f"{base} {CALC_LABEL[calc]}"[:60]
    if calc:
        out["calc"] = calc
    if calc == "moving_avg":
        w = raw.get("window")
        out["window"] = int(w) if isinstance(w, (int, float)) and not isinstance(w, bool) and 2 <= int(w) <= 12 else 3
    unit = "%" if calc in PCT_CALCS else ("위" if calc == "rank" else _s(raw.get("unit"), 8))
    if unit:
        out["unit"] = unit   # 계열 단위 — 없으면 차트 단위를 따른다 / a per-series unit; falls back to the chart's
    return out


def _strip_calc(y: dict) -> dict:
    """계산을 걷어낸 원래 값 계열 — 계산이 붙인 단위와 자동 이름도 되돌린다 / the raw series again: the calc's unit and auto name go too"""
    calc, base = y.get("calc"), ("건수" if y["col"] == "*" else y["col"])
    out = {k: v for k, v in y.items() if k not in ("calc", "window", "by") and not (k == "unit" and (calc in PCT_CALCS or calc == "rank"))}
    tail = " " + CALC_LABEL.get(calc, "")
    if y.get("by"):
        out["name"] = base
    elif calc and out["name"].endswith(tail):   # "실적 합계 증감률" → "실적 합계"
        out["name"] = out["name"][:-len(tail)].strip() or base
    return out


def _y_key(y: dict) -> tuple:
    by = y.get("by") or {}
    return (y["col"], y["agg"], y.get("calc"), by.get("col"), by.get("agg"), y.get("window"))


def default_style(ctype: str) -> dict:
    return {"palette": "indigo", "labels": False, "smooth": True, "fill": ctype == "area",
            "legend": "bottom", "rounded": True, "grid": True}


def norm_style(raw, ctype: str, base: dict | None = None) -> dict:
    out = dict(base or default_style(ctype))
    raw = raw if isinstance(raw, dict) else {}
    if raw.get("palette") in PALETTES:
        out["palette"] = raw["palette"]
    if raw.get("legend") in LEGENDS:
        out["legend"] = raw["legend"]
    for k in ("labels", "smooth", "fill", "rounded", "grid"):
        if isinstance(raw.get(k), bool):
            out[k] = raw[k]
    return out


def norm_ref(raw, used: set[str]) -> dict | None:
    raw = raw if isinstance(raw, dict) else {}
    value = num(raw.get("value"))
    stat = raw.get("stat") if raw.get("stat") in REF_STATS else None
    if value is None and stat is None:
        return None
    rid = str(raw.get("id") or "")
    if not re.fullmatch(r"r\d{1,3}", rid) or rid in used:
        rid = _next_id("r", used)
    used.add(rid)
    color = _s(raw.get("color"), 9)
    return {"id": rid, "label": _s(raw.get("label"), 40) or ("기준선" if stat is None else {"avg": "평균", "median": "중앙값", "min": "최솟값", "max": "최댓값"}[stat]),
            "value": None if stat else _round(value), "stat": stat, "series": _s(raw.get("series"), 60),
            "color": color if re.fullmatch(r"#[0-9a-fA-F]{3,8}", color) else ""}


_OP_WORD = {"lt": "미만", "lte": "이하", "gt": "초과", "gte": "이상"}


def norm_highlight(raw, refs: list[dict], used: set[str]) -> dict | None:
    """강조 규칙 하나 — 조건(고정 값·통계·기준선 대비·상위/하위 N·특정 항목) + 색. 조건이 서지 않으면 None."""
    # One highlight rule: a condition (fixed value, statistic, versus a reference line, top/bottom N, named items) plus a
    # colour. None when the condition cannot stand.
    raw = raw if isinstance(raw, dict) else {}
    value = num(raw.get("value"))
    stat = raw.get("stat") if raw.get("stat") in HL_STATS else None
    want = _s(raw.get("ref") if raw.get("ref") is not None else raw.get("ref_label"), 40)
    ref = next((r for r in refs if want and want in (r["id"], r["label"])), None)
    items = []
    for v in (raw.get("items") or [])[:MAX_X_ITEMS]:
        k = key(v)[:80]
        if k and k not in items:
            items.append(k)
    kind = raw.get("kind") if raw.get("kind") in HL_KINDS else None
    if kind is None:   # 종류를 안 줬으면 준 값으로 짐작한다 / infer the kind from what was given
        kind = "items" if items else "ref" if ref else "stat" if stat else "value" if value is not None else None
    if kind is None or (kind == "value" and value is None) or (kind == "ref" and ref is None) or (kind == "items" and not items):
        return None
    op = raw.get("op") if raw.get("op") in HL_OPS else ("gte" if kind == "stat" else "lt")
    n_in = raw.get("n")
    n = int(n_in) if isinstance(n_in, (int, float)) and not isinstance(n_in, bool) and 1 <= int(n_in) <= MAX_X_ITEMS else 3
    color = _s(raw.get("color"), 9)
    if color.lower() in HL_COLORS:
        color = HL_COLORS[color.lower()]
    elif not re.fullmatch(r"#[0-9a-fA-F]{3,8}", color):
        # 기본 색: 기준에 못 미치면 빨강, 넘으면 초록, 하위는 주황, 상위·특정 항목은 차트 색 그대로('')
        # Default colours: red below a threshold, green above, amber for the bottom, the chart's own colour ('') for top/items
        color = {"bottom": HL_COLORS["amber"], "top": "", "items": ""}.get(kind, HL_COLORS["red" if op in ("lt", "lte") else "green"])
    if kind == "value":
        auto = f"{fmt(value)} {_OP_WORD[op]}"
    elif kind == "stat":
        auto = f"{'평균' if (stat or 'avg') == 'avg' else '중앙값'} {_OP_WORD[op]}"
    elif kind == "ref":
        auto = f"{ref['label']} {'미달' if op in ('lt', 'lte') else '달성'}"
    elif kind in ("top", "bottom"):
        auto = f"{'상위' if kind == 'top' else '하위'} {n}"
    else:
        auto = ", ".join(items[:3]) + (" 외" if len(items) > 3 else "")
    hid = str(raw.get("id") or "")
    if not re.fullmatch(r"h\d{1,3}", hid) or hid in used:
        hid = _next_id("h", used)
    used.add(hid)
    return {"id": hid, "kind": kind, "op": op if kind in ("value", "stat", "ref") else None,
            "value": _round(value) if kind == "value" else None, "stat": (stat or "avg") if kind == "stat" else None,
            "ref": ref["id"] if kind == "ref" else "", "n": n if kind in ("top", "bottom") else None,
            "items": items if kind == "items" else [], "color": color, "label": _s(raw.get("label"), 40) or auto[:40],
            # 상위·하위·특정 항목은 나머지를 흐리게(돋보이게), 기준 비교는 나머지를 그대로 둔다 / top, bottom and items dim the rest
            "dim": raw["dim"] if isinstance(raw.get("dim"), bool) else kind in ("top", "bottom", "items"),
            "series": _s(raw.get("series"), 60)}


def norm_chart(raw: dict, sources: dict[str, dict], used: set[str], strict: bool = False) -> dict:
    """차트 설정 하나 — Source·컬럼이 실제로 있어야 한다. 없으면 ValueError(무엇이 없는지 말한다).
    strict(도구 호출): 쓸 수 없는 계산 값도 ValueError 로 알려 준다. 아니면(저장분을 읽을 때) 그 계산만 걷어내고 차트는 살린다."""
    # One chart spec — its source and columns must exist; ValueError names what is missing. strict (tool calls) also
    # raises on a calculation that cannot apply; otherwise (loading saved data) only that calculation is dropped.
    raw = raw if isinstance(raw, dict) else {}
    src = sources.get(str(raw.get("source") or raw.get("source_id") or ""))
    if src is None:
        raise ValueError("차트가 가리키는 Source 가 없습니다. 쓸 수 있는 Source: " + (", ".join(sources) or "없음"))
    columns, types = src["columns"], src["types"]
    ctype = raw.get("type") if raw.get("type") in CHART_TYPES else "bar"
    x = None
    if ctype != "kpi":
        x = resolve_col(raw.get("x"), columns)
        if x is None:
            if str(raw.get("x") or "").strip():
                raise ValueError(f"'{raw.get('x')}' 컬럼이 없습니다. 쓸 수 있는 컬럼: " + ", ".join(columns))
            x = next((c for c in columns if types.get(c) == "text"), columns[0])
    default_type = "line" if ctype in ("line", "area") else "bar"
    ys, loose = [], set()   # loose: 모양·축을 말하지 않은 계열(자동 배치 대상) / series whose type and axis were not given
    for item in (raw.get("y") if isinstance(raw.get("y"), list) else [raw.get("y")] if raw.get("y") else []):
        y = _norm_y(item, columns, types, default_type)
        if y is None:
            name = item.get("col") or item.get("column") if isinstance(item, dict) else item
            raise ValueError(f"'{name}' 컬럼이 없습니다. 쓸 수 있는 컬럼: " + ", ".join(columns))
        if not any(_y_key(o) == _y_key(y) for o in ys):
            ys.append(y)
            if not isinstance(item, dict) or (item.get("type") not in ("bar", "line") and item.get("axis") is None):
                loose.add(_y_key(y))
    if not ys:
        first_num = next((c for c in columns if types.get(c) == "number" and c != x), None)
        ys = [_norm_y({"col": first_num or "*"}, columns, types, default_type)]
    group = resolve_col(raw.get("group"), columns) if raw.get("group") else None
    if ctype in ("pie", "donut", "kpi"):
        group = None
    if group == x:
        group = None
    if group or ctype in ("pie", "donut", "kpi"):
        ys = ys[:1]
    ys = ys[:MAX_Y]
    # 계산 값 점검 — 원·도넛·숫자 카드에는 못 쓰고, 직전 대비·이동 평균·전년 대비는 x 축이 기간일 때만 뜻이 있다
    # Calculated values: not on pie/donut/KPI, and previous-period change, moving average and year-over-year need a period axis
    periods = src.get("periods") or {}
    pkind = periods.get(x) if x else None
    for i, y in enumerate(ys):
        calc = y.get("calc")
        why = ""
        if calc and ctype in ("pie", "donut", "kpi"):
            why = "원·도넛·숫자 카드에는 계산 값을 쓸 수 없습니다"
        elif calc in SEQ_CALCS and not pkind:
            why = (f"'{CALC_LABEL[calc]}' 계산은 x 축이 기간(연도·분기·월·주·일자) 컬럼일 때만 쓸 수 있습니다. "
                   f"이 Source 의 기간 컬럼: {', '.join(periods) or '없음'}")
        if why and strict:
            raise ValueError(why)
        if why:
            ys[i] = _strip_calc(y)
    # 단위가 다른 계열(% 와 금액)이 섞이면, 모양·축을 말하지 않은 % 계열은 선 + 오른쪽 축으로 보낸다
    # When % series mix with other units, % series whose type and axis were not given become lines on the right axis
    pct = [y for y in ys if y.get("unit") == "%"]
    if pct and len(pct) < len(ys) and ctype in ("bar", "line", "area") and not group:
        ys = [{**y, "type": "line", "axis": 1} if y.get("unit") == "%" and _y_key(y) in loose else y for y in ys]
    if ctype == "hbar":   # 가로 막대는 혼합·이중축을 쓰지 않는다 / horizontal bars have no mixed types or dual axis
        ys = [{**y, "type": "bar", "axis": 0} for y in ys]
    sort_in = raw.get("sort") if isinstance(raw.get("sort"), dict) else {}
    sort_by = sort_in.get("by") if sort_in.get("by") in SORT_BY else "none"
    if pkind and any(y.get("calc") in ORDER_CALCS for y in ys):
        sort_in, sort_by = {"dir": "asc"}, "x"   # 순서가 뜻인 계산은 기간 순으로 고정 / order-dependent calcs pin the period order
    limit = raw.get("limit")
    limit = int(limit) if isinstance(limit, (int, float)) and not isinstance(limit, bool) and 1 <= int(limit) <= MAX_X_ITEMS else None
    cid = str(raw.get("id") or "")
    if not re.fullmatch(r"c\d{1,3}", cid) or cid in used:
        cid = _next_id("c", used)
    used.add(cid)
    ref_used: set[str] = set()
    refs = [r for r in (norm_ref(x_, ref_used) for x_ in (raw.get("ref_lines") or [])[:MAX_REF_LINES]) if r]
    if ctype in ("pie", "donut", "kpi"):
        refs = []
    filters, fused = [], set()
    for f in (raw.get("filters") or []):
        try:
            nf = norm_filter(f, src, fused)
        except ValueError:
            continue   # Source 가 바뀌어 없어진 컬럼의 필터는 버린다 / a filter on a column the source no longer has is dropped
        if not any(o["col"] == nf["col"] for o in filters) and len(filters) < MAX_FILTERS:
            filters.append(nf)
    highlights, hused = [], set()
    if ctype not in ("pie", "donut", "kpi"):
        for h in (raw.get("highlights") or []):
            nh = norm_highlight(h, refs, hused)
            if nh is not None and len(highlights) < MAX_HIGHLIGHTS:
                highlights.append(nh)
    drill = []   # 드릴다운 순서: 막대를 누르면 x 가 이 컬럼들로 차례로 내려간다 / the drill-down path below x
    for d in (raw.get("drill") or []):
        # 받아 둔 컬럼, 또는 조회 SQL 이 있으면 원본 테이블의 컬럼 이름(그 단계는 서버가 조회하며 다시 검사한다 — 도구는 set_drill 에서 먼저 본다)
        # a fetched column, or with query SQL a base-table column name (the server re-checks it when fetching; set_drill checks first)
        col = resolve_col(d, columns) or (_s(d, 80) if src.get("sql") and isinstance(d, str) else None)
        if col and col not in (x, group) and col not in drill and len(drill) < MAX_DRILL and ctype != "kpi":
            drill.append(col)
    # 메모(주석): 사용자가 직접 단다(LLM 없음). 화면 위치가 아니라 x 값에 붙어 정렬·크기·필터가 바뀌어도 따라간다
    # Notes: added by hand (no LLM) and anchored to an x value, so they follow sorting, resizing and filtering
    notes, nused = [], set()
    if ctype not in ("pie", "donut", "kpi"):
        for n in (raw.get("notes") or []):
            n = n if isinstance(n, dict) else {}
            at, text = key(n.get("x"))[:80], _s(n.get("text"), MAX_NOTE_TEXT)
            if not text or any(o["x"] == at for o in notes) or len(notes) >= MAX_NOTES:
                continue
            nid = str(n.get("id") or "")
            if not re.fullmatch(r"n\d{1,3}", nid) or nid in nused:
                nid = _next_id("n", nused)
            nused.add(nid)
            notes.append({"id": nid, "x": at, "text": text})
    # 추세선·간단한 예측: x 축이 기간일 때만. 예측은 그 차트의 지난 값만으로 이어 그린다(외부 요인·AI 추측 없음, 계산은 코드)
    # Trend line and simple forecast: period axes only; the forecast extends the chart's own past values (no outside factors, no AI guess)
    tr_in = raw.get("trend") if isinstance(raw.get("trend"), dict) else {}
    fc_in = tr_in.get("forecast")
    fc = int(fc_in) if isinstance(fc_in, (int, float)) and not isinstance(fc_in, bool) and 1 <= int(fc_in) <= MAX_FORECAST else 0
    trend = {}
    if tr_in.get("line") or fc:
        why = ""
        if ctype not in ("bar", "line", "area"):
            why = "추세선·예측은 세로 막대·선·영역 차트에만 넣을 수 있습니다"
        elif not pkind:
            why = ("추세선·예측은 x 축이 기간(연도·분기·월·주·일자) 컬럼일 때만 쓸 수 있습니다. "
                   f"이 Source 의 기간 컬럼: {', '.join(periods) or '없음'}")
        if why and strict:
            raise ValueError(why)
        if not why:
            trend = {"line": bool(tr_in.get("line")), "forecast": fc,
                     "method": "seasonal" if tr_in.get("method") == "seasonal" else "linear", "series": _s(tr_in.get("series"), 60)}
            sort_in, sort_by = {"dir": "asc"}, "x"   # 마지막 점이 가장 최근 기간이어야 이어 그릴 수 있다 / the last point must be the latest period
    compare = str(raw.get("compare") or "")   # 비교 묶음 id — 같은 묶음의 차트는 값 축 눈금을 맞춘다 / charts of one group share the value-axis scale
    compare = compare if re.fullmatch(r"g\d{1,3}", compare) and ctype not in ("pie", "donut", "kpi") else ""
    extra = {k: v for k, v in (("highlights", highlights), ("drill", drill), ("notes", notes), ("compare", compare), ("trend", trend)) if v}   # 있을 때만(옛 모양 유지) / only when set
    return {
        **extra,
        "id": cid, "source": src["id"], "type": ctype,
        "title": _s(raw.get("title"), MAX_TITLE) or (f"{x}별 {ys[0]['name']}" if x else ys[0]["name"]),
        "subtitle": _s(raw.get("subtitle"), 200),
        "x": x, "y": ys, "group": group,
        # 방향 기본값: x 정렬은 오름차순, 값 정렬은 큰 값부터 / default direction: ascending for x, largest first for values
        "sort": {"by": sort_by, "dir": sort_in.get("dir") if sort_in.get("dir") in ("asc", "desc") else ("asc" if sort_by == "x" else "desc")},
        "limit": limit, "stack": bool(raw.get("stack")) and ctype in ("bar", "hbar", "area"),
        "xLabel": _s(raw.get("xLabel"), 40), "yLabel": _s(raw.get("yLabel"), 40), "unit": _s(raw.get("unit"), 8),
        "ref_lines": refs, "filters": filters, "style": norm_style(raw.get("style"), ctype),
        "insight": _s(raw.get("insight"), 600),
        "size": raw.get("size") if raw.get("size") in SIZES else "half",
    }


def norm_filter(raw: dict, source: dict, used: set[str]) -> dict:
    """차트 하나의 필터 — 컬럼은 그 차트가 쓰는 Source 에 있어야 한다 / one chart's filter; the column must exist in the chart's source"""
    raw = raw if isinstance(raw, dict) else {}
    name = raw.get("col") if raw.get("col") is not None else raw.get("column")
    col = resolve_col(name, source["columns"])
    if col is None:
        raise ValueError(f"'{name}' 컬럼이 {source['name']} 에 없습니다. 쓸 수 있는 컬럼: " + ", ".join(source["columns"]))
    fid = str(raw.get("id") or "")
    if not re.fullmatch(r"f\d{1,3}", fid) or fid in used:
        fid = _next_id("f", used)
    used.add(fid)
    selected = []
    for v in (raw.get("selected") or [])[:MAX_FILTER_SELECTED]:
        k = key(v)
        if k not in selected:
            selected.append(k)
    out = {"id": fid, "col": col, "label": _s(raw.get("label"), 40) or col, "selected": selected}
    # 필터 모양은 컬럼 종류를 따른다(2026-09-21): 글자 = 값 목록, 기간 = 범위(부터~까지 또는 최근 N개), 숫자 = 이상·이하.
    # 범위는 있을 때만 range 키로 싣고, 그때 값 목록은 비운다 / the filter's shape follows the column kind; a range replaces the list
    rng_in = raw.get("range") if isinstance(raw.get("range"), dict) else raw
    pkind = (source.get("periods") or {}).get(col)
    rng: dict = {}
    if pkind:
        last = rng_in.get("last") if rng_in.get("last") is not None else rng_in.get("last_n")
        lo = key(rng_in.get("from") if rng_in.get("from") is not None else rng_in.get("from_value")).strip()
        hi = key(rng_in.get("to") if rng_in.get("to") is not None else rng_in.get("to_value")).strip()
        lo, hi = (lo if period_key(lo, pkind) else ""), (hi if period_key(hi, pkind) else "")
        if isinstance(last, (int, float)) and not isinstance(last, bool) and 1 <= int(last) <= MAX_FILTER_LAST:
            rng = {"last": int(last)}   # 최근 N개 기간 — 오늘이 아니라 데이터의 마지막 기간 기준 / the last N periods of the data, not of today
        elif lo or hi:
            rng = {"from": lo, "to": hi}
    elif source["types"].get(col) == "number":
        lo, hi = num(rng_in.get("min")), num(rng_in.get("max"))
        if lo is not None or hi is not None:
            rng = {"min": lo, "max": hi}
    if rng:
        out["range"], out["selected"] = rng, []
    return out


_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")


def norm_theme(raw) -> dict | None:
    """대시보드 테마 — 대표 색(필수)과 둘째 색, 그리고 모든 차트에 같이 입힐 디자인 기본값. 새 차트도 이것을 따른다."""
    # The dashboard theme: a brand colour (required), a second colour, and design defaults applied to every chart, new ones included.
    raw = raw if isinstance(raw, dict) else {}
    brand = _s(raw.get("brand") if raw.get("brand") is not None else raw.get("brand_color"), 9)
    if not _HEX.fullmatch(brand):
        return None
    second = _s(raw.get("second") if raw.get("second") is not None else raw.get("second_color"), 9)
    out = {"brand": brand.upper(), "second": second.upper() if _HEX.fullmatch(second) else ""}
    for k in ("rounded", "grid", "labels"):
        if isinstance(raw.get(k), bool):
            out[k] = raw[k]
    if raw.get("legend") in LEGENDS:
        out["legend"] = raw["legend"]
    return out


def theme_style(theme: dict | None) -> dict:
    """테마가 차트 디자인에 주는 값(색 묶음 = theme + 기본값들) / what a theme sets on a chart's style"""
    if not theme:
        return {}
    return {"palette": "theme", **{k: theme[k] for k in ("rounded", "grid", "labels", "legend") if k in theme}}


_AGG_WORD = {"sum": "합계", "avg": "평균", "count": "건수", "min": "최솟값", "max": "최댓값", "first": "첫 값"}


def norm_kpi(raw, sources: dict[str, dict], charts: list[dict], used: set[str], strict: bool = False) -> dict | None:
    """KPI 카드(요약 숫자) 하나 — 대시보드 맨 위의 작은 숫자. 데이터에서 계산하는 카드는 Source 를 가리키기만 하고(탭을 만들지 않는다)
    연결한 차트의 필터를 따라간다. 고정 숫자 카드(value — 사용자가 화면의 카드 편집에 적거나 대화에서 말한 목표치 같은 값, 2026-10-12)는
    그 숫자를 그대로 보여 주며 source 가 비어 있다. note 는 카드 아래 한 줄 설명. strict(도구 · 카드 편집)면 연결 차트가 다른 데이터면 거절."""
    # One KPI card (summary number) on top of the dashboard. A computed card only points at a source (no tab of its own) and
    # follows the filters of the chart it is linked to; a fixed-number card (value: a target the user typed in the card editor or
    # stated in the conversation, 2026-10-12) shows that number as is and has no source. note is the one-line text under the
    # card. strict raises with a sentence for the caller (and refuses a linked chart of other data); otherwise an invalid card is
    # dropped and a mismatched link is cleared.
    raw = raw if isinstance(raw, dict) else {}

    def fail(msg):
        if strict:
            raise ValueError(msg)
        return None

    kid = str(raw.get("id") or "")
    if not re.fullmatch(r"k\d{1,3}", kid) or kid in used:
        kid = _next_id("k", used)
    label, unit, note = _s(raw.get("label"), 40), _s(raw.get("unit"), 8), _s(raw.get("note"), MAX_KPI_NOTE)
    if raw.get("value") is not None and raw.get("value") != "":   # 직접 적은 숫자 / a typed number
        v = num(raw.get("value"))
        if v is None:
            return fail("KPI 카드에 보여 줄 숫자를 적어 주세요")
        if not label:
            return fail("KPI 카드 이름을 적어 주세요")
        used.add(kid)
        return {"id": kid, "source": "", "col": "", "agg": "", "label": label, "unit": unit, "link": "", "delta": "",
                "value": _round(v), "note": note}
    src = sources.get(str(raw.get("source") or raw.get("source_id") or ""))
    if src is None:
        return fail("KPI 카드가 가리키는 Source 가 없습니다. 쓸 수 있는 Source: " + (", ".join(sources) or "없음"))
    name_in = raw.get("col") if raw.get("col") is not None else raw.get("column")
    if str(name_in or "").strip() == "*":
        col, agg = "*", "count"
    else:
        col = resolve_col(name_in, src["columns"])
        if col is None:
            return fail(f"'{name_in}' 컬럼이 {src['name']} 에 없습니다. 쓸 수 있는 컬럼: " + ", ".join(src["columns"]))
        agg = raw.get("agg") if raw.get("agg") in AGGS else ("avg" if (_RATE_COL.search(str(col)) or RATE_ONLY.search(str(col))) else "sum")
        if src["types"].get(col) != "number" and agg != "count":
            agg = "count"
    by_id = {s["id"]: s for s in sources.values()}
    link_in = str(raw.get("link") or raw.get("link_chart_id") or "")
    link = next((c["id"] for c in charts if c["id"] == link_in and lineage(by_id[c["source"]]) == lineage(src)), "")
    if link_in and not link and strict:
        raise ValueError(f"연결 차트 '{link_in}'(이)가 없거나 이 카드의 데이터와 다른 Source 를 씁니다")
    used.add(kid)
    return {"id": kid, "source": src["id"], "col": col, "agg": agg,
            "label": label or ("건수" if col == "*" else f"{col} {_AGG_WORD[agg]}"),
            "unit": unit, "link": link,
            # 직전 기간 대비: 기간 컬럼이 있는 Source 에서만 / change from the previous period needs a period column
            "delta": "prev" if raw.get("delta") in ("prev", True) and src.get("periods") else "", "note": note}


def put_kpi(state: dict, raw: dict, kid: str = "", merge: bool = False) -> dict:
    """KPI 카드를 넣거나(kid 없음) 제자리에서 고친다(kid) — 화면의 카드 편집(ops kpi_add · kpi_set)과 도구 add_kpi 가 같이 쓴다.
    merge 면 적은 항목만 바꾸고 나머지는 있던 카드의 값을 지킨다(대화로 고치기 — 이름만 바꾸는 요청 등): 숫자(value)를 말하면 고정 숫자 카드가 되고,
    컬럼을 말하면 데이터에서 계산하는 카드로 돌아간다. 비율 컬럼의 합계와 상한 초과는 거절."""
    # Add (no kid) or edit in place (kid) a KPI card — shared by the card editor (ops kpi_add / kpi_set) and the add_kpi tool.
    # merge keeps the existing card's fields where raw says nothing (conversation edits, e.g. a rename): a stated number makes
    # it a fixed-number card, a named column turns it back into a computed one. Summing a rate column and exceeding the cap
    # are refused. Cards are replaced, never mutated, so undo snapshots stay intact.
    have = list(state.get("kpis") or [])
    cur = next((k for k in have if k["id"] == kid), None) if kid else None
    if kid and cur is None:
        raise ValueError("해당 KPI 카드가 없습니다")
    raw = raw if isinstance(raw, dict) else {}
    # 적은 항목만(None 은 안 적은 것, 빈 문자열은 "지운다") / given fields only: None means "not given", an empty string means "clear"
    given = {k: v for k, v in raw.items() if v is not None and not (k == "value" and v == "")}
    col_in = str(given.get("col") if given.get("col") is not None else given.get("column") or "").strip()
    if given.get("value") is not None and col_in:
        raise ValueError("숫자(value)와 컬럼(column)은 함께 줄 수 없습니다 — 고정 숫자 카드면 column 을, 데이터 카드면 value 를 빼세요")
    if merge and cur is not None:
        base = dict(cur)
        col_changed = bool(col_in) and col_in != cur.get("col")
        if col_in:
            base.pop("value", None)   # 컬럼을 말하면 데이터 계산 카드로 / naming a column makes it a computed card again
            if col_changed and "agg" not in given:
                base.pop("agg", None)   # 집계는 새 컬럼에 맞게 다시 고른다(비율이면 평균) / the aggregation is re-picked for the new column (avg for rates)
        auto = "건수" if cur.get("col") == "*" else (f"{cur['col']} {_AGG_WORD[cur['agg']]}" if cur.get("col") and cur.get("agg") in _AGG_WORD else "")
        if "label" not in given and auto and cur.get("label") == auto and (col_changed or ("agg" in given and given["agg"] != cur.get("agg"))):
            base.pop("label", None)   # 자동으로 붙은 이름은 새 컬럼 · 집계로 다시 짓는다 / an auto-generated name follows the new column and aggregation
        raw = {**base, **given}
    else:
        raw = given
    sources = {s["id"]: s for s in state["sources"]}
    kpi = norm_kpi({**raw, "id": kid}, sources, state["charts"], {k["id"] for k in have if k["id"] != kid}, strict=True)
    if kpi["agg"] == "sum" and kpi["col"] != "*" and RATE_ONLY.search(kpi["col"]):
        raise ValueError(f"'{kpi['col']}'는 비율이라 더하면 틀립니다. avg 로 요약하세요")
    if any(k["id"] != kid and k["label"] == kpi["label"] for k in have):
        raise ValueError(f"같은 이름의 KPI 카드가 이미 있습니다: {kpi['label']}")
    if cur is not None:
        state["kpis"] = [kpi if k["id"] == kid else k for k in have]
    else:
        if len(have) >= MAX_KPIS:
            raise ValueError(f"KPI 카드는 {MAX_KPIS}개까지입니다")
        state["kpis"] = have + [kpi]
    return kpi


def kpi_value(kpi: dict, state: dict) -> dict:
    """요약 숫자의 값 — 연결한 차트가 있으면 그 필터를 적용한다. delta=prev 면 마지막 기간과 그 앞 기간을 비교한다(프런트 rdKpi 와 같은 규칙)."""
    # The value of a summary number, under the linked chart's filters; delta=prev compares the last period with the one
    # before it (same rules as the front end's rdKpi).
    if not kpi.get("source"):   # 직접 적은 숫자는 그대로 / a typed number as is
        return {"value": kpi.get("value"), "rows": 0, "manual": True}
    src = next(s for s in state["sources"] if s["id"] == kpi["source"])
    chart = next((c for c in state["charts"] if c["id"] == kpi.get("link")), None)
    rows = filtered_rows(src, chart["filters"]) if chart is not None else src["rows"]
    ci = None if kpi["col"] == "*" else src["columns"].index(kpi["col"])
    out = {"value": _agg(rows, ci, kpi["agg"]), "rows": len(rows)}
    periods = src.get("periods") or {}
    if kpi.get("delta") == "prev" and periods:
        pcol = chart["x"] if chart is not None and chart.get("x") in periods else next(iter(periods))
        pi, kind = src["columns"].index(pcol), periods[pcol]
        buckets: dict[tuple, tuple[str, list]] = {}
        for r in rows:
            k = period_key(r[pi], kind)
            if k is not None:
                buckets.setdefault(k, (key(r[pi]), []))[1].append(r)
        order = sorted(buckets)
        if len(order) >= 2:
            (last_label, last_rows), (prev_label, prev_rows) = buckets[order[-1]], buckets[order[-2]]
            last, prev = _agg(last_rows, ci, kpi["agg"]), _agg(prev_rows, ci, kpi["agg"])
            out.update({"period": last_label, "prev_period": prev_label, "last": last,
                        "delta": _round((last - prev) / abs(prev) * 100) if prev else None})
    return out


def auto_kpis(state: dict) -> list[dict]:
    """LLM 없이 고르는 추천 KPI 카드 — 첫 Source 의 값 컬럼 최대 3개(기간·번호 컬럼 제외), 그 Source 의 첫 차트에 연결한다.
    2026-10-12 부터 첫 화면에 자동으로 놓지 않고, 화면의 [추천 채우기](ops kpi_auto)가 부른다."""
    # Suggested KPI cards picked without the LLM: up to three value columns of the first source (period and id columns
    # excluded), linked to that source's first chart. Since 2026-10-12 nothing is placed automatically; the on-screen
    # [Fill suggestions] button (ops kpi_auto) calls this.
    src = next((s for s in state["sources"] if not s["origin"].get("clone_of") and s["rows"]), None)
    if src is None:
        return []
    by_id = {s["id"]: s for s in state["sources"]}
    link = next((c["id"] for c in state["charts"] if lineage(by_id[c["source"]]) == src["id"]), "")
    cols = [c for c in src["columns"] if src["types"].get(c) == "number" and c not in (src.get("periods") or {})
            and not _PERIOD_COL.search(c) and not _ID_COL.search(c)][:3]
    return [{"source": src["id"], "col": c, "link": link, "delta": "prev" if i == 0 else ""} for i, c in enumerate(cols)]


def duplicate_chart(state: dict, cid: str) -> dict:
    """차트 복제(버튼, LLM 없음) — 같은 설정의 새 리포트를 원본 바로 뒤에 두고 둘을 비교 묶음(값 축 눈금 맞춤)으로 묶는다.
    복제본은 새 Source 탭이 되지만 데이터는 원본을 가리킨다."""
    # Duplicate a chart (a button, no LLM): the copy sits right after the original and both join one compare group (shared
    # value-axis scale). The copy gets its own Source tab, which only points at the original's data.
    cur = next((c for c in state["charts"] if c["id"] == cid), None)
    if cur is None:
        raise ValueError("해당 차트가 없습니다")
    if len(state["charts"]) >= MAX_CHARTS:
        raise ValueError(f"차트는 {MAX_CHARTS}개까지입니다")
    src_id, cloned = source_for_new_chart(state, cur["source"])
    group = cur.get("compare") or _next_id("g", {c.get("compare") for c in state["charts"] if c.get("compare")})
    comparable = cur["type"] not in ("pie", "donut", "kpi")
    copy = json.loads(json.dumps(cur))
    copy.update({"id": _next_id("c", {c["id"] for c in state["charts"]}), "source": src_id,
                 "title": f"{cur['title'][:MAX_TITLE - 5]} (복사)", "size": "half"})
    if comparable:
        copy["compare"] = cur["compare"] = group
    cur["size"] = "half"
    if cloned:
        state["sources"][-1]["label"] = copy["title"][:80]
    state["charts"].insert(state["charts"].index(cur) + 1, copy)
    return copy


def normalize_state(raw: dict) -> dict:
    """대시보드 상태 전체 — 잘못된 차트·필터는 버린다(깨진 조각 하나가 대시보드 전체를 못 열게 하지 않는다)."""
    # Whole dashboard state — invalid charts/filters are dropped so one broken piece never blocks the dashboard.
    raw = raw if isinstance(raw, dict) else {}
    used: set[str] = set()
    sources = []
    for s in (raw.get("sources") or [])[:MAX_SOURCES]:
        try:
            sources.append(norm_source(s, used))
        except ValueError:
            continue
    link_clones(sources)   # 복제본은 원본의 데이터를 가리킨다(저장분의 빈 행·옛 복사본 모두) / clones point at their root's data
    by_id = {s["id"]: s for s in sources}
    charts, cused = [], set()
    for c in (raw.get("charts") or [])[:MAX_CHARTS]:
        try:
            charts.append(norm_chart(c, by_id, cused))
        except ValueError:
            continue
    # 리포트 하나 = Source 하나: 한 Source 를 여러 차트가 같이 쓰던 저장분은 둘째 차트부터 데이터를 복제해 나눈다
    # One report = one source: saved states whose charts shared a source are split by cloning from the second chart on
    placed: list[dict] = []
    for c in charts:
        sid_, made = source_for_new_chart({"sources": sources, "charts": placed}, c["source"])
        if made:
            sources[-1]["label"] = c["title"][:80]
        c["source"] = sid_
        placed.append(c)
    by_id = {s["id"]: s for s in sources}
    # 옛 모양(대시보드 전체 필터, 2026-09-18 하루치)은 그 Source 를 쓰는 차트마다 하나씩 옮긴다 / the short-lived
    # dashboard-level filters are moved into every chart that uses one of their sources
    for f in (raw.get("filters") or []):
        if not isinstance(f, dict):
            continue
        for c in charts:
            if f.get("sources") and c["source"] not in f["sources"] and lineage(by_id[c["source"]]) not in f["sources"]:
                continue
            try:
                nf = norm_filter({**f, "id": ""}, by_id[c["source"]], {x["id"] for x in c["filters"]})
            except ValueError:
                continue
            if not any(o["col"] == nf["col"] for o in c["filters"]) and len(c["filters"]) < MAX_FILTERS:
                c["filters"].append(nf)
    for c in charts:   # 혼자 남은 비교 묶음은 푼다 / a compare group of one is dissolved
        if c.get("compare") and sum(1 for o in charts if o.get("compare") == c["compare"]) < 2:
            c.pop("compare")
    out = {"v": 2, "title": _s(raw.get("title"), MAX_TITLE) or "새 대시보드", "sources": sources, "charts": charts}
    kpis, kused = [], set()
    for k in (raw.get("kpis") or [])[:MAX_KPIS]:
        nk = norm_kpi(k, by_id, charts, kused)
        if nk is not None:
            kpis.append(nk)
    if kpis:
        out["kpis"] = kpis   # 있을 때만(옛 모양 유지) / only when set
    theme = norm_theme(raw.get("theme"))
    if theme:
        out["theme"] = theme
    return out


# ────────────────────────────────────────────────────────
# 집계 / aggregation (mirrors ai365RdCompute in static/adapter.js)
# ────────────────────────────────────────────────────────

def _range_test(source: dict, col: str, rng: dict):
    """범위 필터 → 값 하나를 통과시킬지 정하는 함수(거를 것이 없으면 None) / a range filter → a predicate on one value, or None"""
    ci = source["columns"].index(col)
    pkind = (source.get("periods") or {}).get(col)
    if pkind:
        if rng.get("last"):
            keys = sorted({k for k in (period_key(r[ci], pkind) for r in source["rows"]) if k is not None})
            if not keys:
                return None
            lo, hi = keys[-min(rng["last"], len(keys))], None
        else:
            lo, hi = period_key(rng.get("from"), pkind), period_key(rng.get("to"), pkind)
            if lo is None and hi is None:
                return None

        def test(v):
            k = period_key(v, pkind)
            return k is not None and (lo is None or k >= lo) and (hi is None or k <= hi)
        return test
    lo, hi = rng.get("min"), rng.get("max")
    if lo is None and hi is None:
        return None

    def test_num(v):
        n = num(v)
        return n is not None and (lo is None or n >= lo) and (hi is None or n <= hi)
    return test_num


def filtered_rows(source: dict, filters: list[dict]) -> list[list]:
    active = []
    for f in filters or []:
        if f.get("col") not in source["columns"]:
            continue
        ci = source["columns"].index(f["col"])
        if f.get("range"):
            test = _range_test(source, f["col"], f["range"])
            if test is not None:
                active.append((ci, test))
        elif f.get("selected"):
            active.append((ci, (lambda sel: lambda v: key(v) in sel)(set(f["selected"]))))
    if not active:
        return source["rows"]
    return [r for r in source["rows"] if all(test(r[ci]) for ci, test in active)]


def _agg(rows: list[list], ci: int | None, how: str) -> float:
    if how == "count":
        return float(len(rows) if ci is None else sum(1 for r in rows if r[ci] is not None and r[ci] != ""))
    vals = [v for v in (num(r[ci]) for r in rows) if v is not None] if ci is not None else []
    if not vals:
        return 0.0
    if how == "avg":
        return _round(sum(vals) / len(vals))
    if how == "min":
        return _round(min(vals))
    if how == "max":
        return _round(max(vals))
    if how == "first":
        return _round(vals[0])
    return _round(sum(vals))


def _cmp_key(labels: list[str], pkind: str | None = None):
    """x 정렬 키 — 기간 컬럼이면 기간 순(1월 < 2월 < 10월), 전부 숫자면 숫자 순, 아니면 글자(코드 포인트) 순"""
    # The x sort key: period order on a period column (1월 < 2월 < 10월), numeric when every label is numeric, else code points
    if pkind and labels and all(period_key(v, pkind) is not None for v in labels):
        return lambda item: period_key(item[0], pkind)
    nums = [num(v) for v in labels]
    if labels and all(n is not None for n in nums):
        return lambda item: num(item[0])
    return lambda item: item[0]


def _calc_point(y: dict, a: list[float], b: list[float] | None) -> list:
    """순서와 무관한 계산(구성비·순위·두 값의 비율·차이) — 정렬 전에 계산해 그 값으로 정렬할 수 있게 한다."""
    # Order-independent calcs (share, rank, ratio, difference) run before sorting so the chart can sort by them.
    calc = y.get("calc")
    if calc == "share":
        total = sum(a)
        return [_round(v / total * 100) if total else None for v in a]
    if calc == "rank":
        return [float(1 + sum(1 for o in a if o > v)) for v in a]
    if calc in ("ratio", "ratio_pct") and b is not None:
        return [_round(v / d * (100 if calc == "ratio_pct" else 1)) if d else None for v, d in zip(a, b)]
    if calc == "diff" and b is not None:
        return [_round(v - d) for v, d in zip(a, b)]
    return a


def _calc_seq(y: dict, vals: list, labels: list[str], pkind: str | None) -> list:
    """순서가 뜻인 계산(누계·누적 비중·직전 대비·이동 평균·전년 대비) — 정렬이 끝난 값에 적용한다."""
    # Order-dependent calcs (running total, cumulative share, change from the previous point, moving average,
    # year over year) run on the sorted values.
    calc = y.get("calc")
    if calc in ("cumsum", "cum_share"):
        total, run, out = sum(v or 0.0 for v in vals), 0.0, []
        for v in vals:
            run += v or 0.0
            out.append(_round(run) if calc == "cumsum" else (_round(run / total * 100) if total else None))
        return out
    if calc in ("pct_prev", "diff_prev"):
        out = [None]
        for prev, v in zip(vals, vals[1:]):
            if prev is None or v is None or (calc == "pct_prev" and not prev):
                out.append(None)
            else:
                out.append(_round(v - prev) if calc == "diff_prev" else _round((v - prev) / abs(prev) * 100))
        return out[:len(vals)]
    if calc == "moving_avg":
        w = y.get("window") or 3
        return [_round(sum(vals[i - w + 1:i + 1]) / w) if i >= w - 1 and all(v is not None for v in vals[i - w + 1:i + 1]) else None
                for i in range(len(vals))]
    if calc == "yoy":
        keys = [period_key(lb, pkind) if pkind else None for lb in labels]
        at = {k: v for k, v in zip(keys, vals) if k is not None}
        out = []
        for k, v in zip(keys, vals):
            prev = at.get((k[0] - 1, k[1])) if k is not None and k[0] > 0 else None
            out.append(_round((v - prev) / abs(prev) * 100) if prev and v is not None else None)
        return out
    return vals


_CYCLE = {"month": 12, "quarter": 4}


def _trend(chart: dict, source: dict, labels: list[str], series: list[dict]) -> dict | None:
    """추세선(최소제곱 직선)과 간단한 예측 — 보이는 값만으로 계산한다. 예측은 점이 MIN_FORECAST_POINTS 개 이상일 때만,
    길이는 점 수의 1/3 까지. 범위(low~high)는 지난 값이 직선에서 벗어난 정도(±2σ)이고 멀수록 넓어진다. 프런트 rdTrend 와 같은 규칙."""
    # A least-squares trend line and a simple forecast from the visible values only. The forecast needs MIN_FORECAST_POINTS
    # points and spans at most a third of them; its band is ±2σ of the past residuals, widening with distance. Mirrors rdTrend.
    tr = chart.get("trend") or {}
    pkind = (source.get("periods") or {}).get(chart.get("x"))
    if not tr or not pkind or not series:
        return None
    si = next((i for i, s in enumerate(series) if s["name"] == tr.get("series")), 0)
    vals = series[si]["values"]
    pts = [(i, v) for i, v in enumerate(vals) if v is not None]
    n = len(pts)
    if n < 3:
        return None
    xb, yb = sum(i for i, _ in pts) / n, sum(v for _, v in pts) / n
    sxx = sum((i - xb) ** 2 for i, _ in pts)
    b = sum((i - xb) * (v - yb) for i, v in pts) / sxx
    a = yb - b * xb
    out = {"series": si, "slope": _round(b), "points": n}
    if tr.get("line"):
        out["values"] = [_round(a + b * i) for i in range(len(vals))]
    want = int(tr.get("forecast") or 0)
    if want and n >= MIN_FORECAST_POINTS:
        h, size = min(want, max(1, n // 3), MAX_FORECAST), len(vals)
        sd = math.sqrt(sum((v - (a + b * i)) ** 2 for i, v in pts) / (n - 2))
        cycle = _CYCLE.get(pkind)
        seasonal = bool(tr.get("method") == "seasonal" and cycle and n == size and size >= 2 * cycle
                        and sum(vals[size - 2 * cycle:size - cycle]))
        if seasonal:   # 작년 같은 기간 × 최근 한 해의 증가율 / the same period a year ago times the latest yearly growth
            g = sum(vals[size - cycle:]) / sum(vals[size - 2 * cycle:size - cycle])
            fvals = [vals[size - cycle + (k % cycle)] * g ** (1 + k // cycle) for k in range(h)]
        else:
            fvals = [a + b * (size + k) for k in range(h)]
        new = next_period_labels(labels, pkind, h)
        fvals = fvals[:len(new)]
        if new:
            out["forecast"] = {"labels": new, "values": [_round(v) for v in fvals], "method": "seasonal" if seasonal else "linear",
                               "low": [_round(v - 2 * sd * math.sqrt(k + 1)) for k, v in enumerate(fvals)],
                               "high": [_round(v + 2 * sd * math.sqrt(k + 1)) for k, v in enumerate(fvals)]}
    return out


def _sort_val(v) -> float:
    return float("-inf") if v is None else v


def _marks(chart: dict, series: list[dict], refs: list[dict], labels: list[str]) -> list[dict]:
    """강조 규칙 → 규칙마다 맞는 x 위치. 여러 규칙에 걸리면 앞 규칙이 이긴다 / highlight rules → hit positions; the first matching rule wins"""
    out, taken = [], set()
    for h in chart.get("highlights") or []:
        si = next((i for i, s in enumerate(series) if s["name"] == h.get("series")), 0)
        vals = series[si]["values"] if series else []
        idx = [i for i, v in enumerate(vals) if v is not None]
        hits: list[int] = []
        if h["kind"] in ("value", "stat", "ref"):
            th = h.get("value")
            if h["kind"] == "stat" and idx:
                picked = [vals[i] for i in idx]
                th = _round(statistics.median(picked) if h.get("stat") == "median" else sum(picked) / len(picked))
            elif h["kind"] == "ref":
                th = next((r["value"] for r in refs if r["id"] == h.get("ref")), None)
            if th is not None:
                test = {"lt": lambda v: v < th, "lte": lambda v: v <= th, "gt": lambda v: v > th, "gte": lambda v: v >= th}[h.get("op") or "lt"]
                hits = [i for i in idx if test(vals[i])]
        elif h["kind"] == "top":
            hits = sorted(sorted(idx, key=lambda i: (-vals[i], i))[:h.get("n") or 3])
        elif h["kind"] == "bottom":
            hits = sorted(sorted(idx, key=lambda i: (vals[i], i))[:h.get("n") or 3])
        elif h["kind"] == "items":
            hits = [i for i, lb in enumerate(labels) if lb in h.get("items", [])]
        hits = [i for i in hits if i not in taken]
        taken.update(hits)
        out.append({"id": h["id"], "label": h["label"], "color": h.get("color") or "", "dim": bool(h.get("dim")),
                    "series": si, "hits": hits})
    return out


def compute(chart: dict, source: dict, filters: list[dict] | None = None) -> dict:
    """차트 설정 + Source(+필터) → 그릴 값. 반환: {kind, x, series:[{name,type,axis,values}], refs:[{id,label,value,color}], rows}"""
    # Chart spec + source → values to draw. The chart's own filters apply unless `filters` overrides them.
    rows = filtered_rows(source, chart.get("filters") if filters is None else filters)
    cols = source["columns"]
    ys = chart["y"]
    ctype = chart["type"]

    def ci_of(col):
        return None if col == "*" else cols.index(col)

    if ctype == "kpi" or not chart.get("x"):
        y = ys[0]
        value = _agg(rows, ci_of(y["col"]), y["agg"])
        return {"kind": ctype, "x": [y["name"]], "rows": len(rows), "refs": [],
                "series": [{"name": y["name"], "type": "bar", "axis": 0, "values": [value]}]}

    xi = cols.index(chart["x"])
    buckets: dict[str, list[list]] = {}
    for r in rows:
        buckets.setdefault(key(r[xi]), []).append(r)

    def one(y, name, pick):
        """계열 하나 — 버킷마다 집계하고(짝 계산이면 둘째 값도), 순서와 무관한 계산까지 끝낸다 / one series: aggregate per bucket, then the order-independent calc"""
        a = [_agg(pick(rs), ci_of(y["col"]), y["agg"]) for rs in buckets.values()]
        b = [_agg(pick(rs), ci_of(y["by"]["col"]), y["by"]["agg"]) for rs in buckets.values()] if y.get("by") else None
        s = {"name": name, "type": y["type"], "axis": y["axis"], "values": _calc_point(y, a, b)}
        if y.get("unit"):
            s["unit"] = y["unit"]
        if y.get("calc"):
            s["calc"] = y["calc"]
        return s

    series, specs = [], []
    if chart.get("group"):
        gi, y = cols.index(chart["group"]), ys[0]
        groups: list[str] = []
        for r in rows:
            g = key(r[gi])
            if g not in groups:
                groups.append(g)
        for g in groups[:MAX_GROUP_SERIES]:
            series.append(one(y, g or "(빈 값)", lambda rs, g=g: [r for r in rs if key(r[gi]) == g]))
            specs.append(y)
    else:
        for y in ys:
            series.append(one(y, y["name"], lambda rs: rs))
            specs.append(y)

    pkind = (source.get("periods") or {}).get(chart["x"])
    items = [(label, [s["values"][i] for s in series]) for i, label in enumerate(buckets)]
    sort = chart.get("sort") or {}
    if sort.get("by") == "x":
        items.sort(key=_cmp_key([it[0] for it in items], pkind), reverse=sort.get("dir") == "desc")
    elif sort.get("by") == "y":
        items.sort(key=lambda it: _sort_val(it[1][0]) if it[1] else 0.0, reverse=sort.get("dir") != "asc")
    if any(y.get("calc") in ORDER_CALCS for y in specs):   # 순서가 뜻인 계산은 정렬 뒤, 자르기(limit) 전에 / after sorting, before the limit
        labels = [it[0] for it in items]
        cols_ = [_calc_seq(y, [it[1][si] for it in items], labels, pkind) for si, y in enumerate(specs)]
        items = [(it[0], [c[i] for c in cols_]) for i, it in enumerate(items)]
    if ctype in ("pie", "donut"):
        if sort.get("by") != "x":
            items.sort(key=lambda it: it[1][0] if it[1] else 0.0, reverse=True)
        cap = min(chart.get("limit") or MAX_PIE_SLICES, MAX_PIE_SLICES)
        if len(items) > cap:
            rest = _round(sum(it[1][0] for it in items[cap - 1:]))
            items = items[:cap - 1] + [(OTHERS_LABEL, [rest])]
    else:
        items = items[:min(chart.get("limit") or MAX_X_ITEMS, MAX_X_ITEMS)]
    for si, s in enumerate(series):
        s["values"] = [it[1][si] for it in items]

    refs = []
    for ref in chart.get("ref_lines") or []:
        value = ref.get("value")
        if ref.get("stat"):
            target = next((s for s in series if s["name"] == ref.get("series")), series[0] if series else None)
            vals = [v for v in (target["values"] if target else []) if v is not None]   # 계산 값의 빈 칸은 뺀다 / skip the gaps of calculated values
            if not vals:
                continue
            value = _round({"avg": lambda v: sum(v) / len(v), "median": statistics.median,
                            "min": min, "max": max}[ref["stat"]](vals))
        if value is not None:
            refs.append({"id": ref["id"], "label": ref["label"], "value": value, "color": ref.get("color") or ""})
    out = {"kind": ctype, "x": [it[0] for it in items], "series": series, "refs": refs, "rows": len(rows)}
    marks = _marks(chart, series, refs, out["x"]) if ctype not in ("pie", "donut") else []
    if marks:
        out["marks"] = marks
    trend = _trend(chart, source, out["x"], series)
    if trend:
        out["trend"] = trend
    return out


def legacy_chart(chart: dict, source: dict, filters: list[dict] | None = None) -> dict:
    """옛 렌더러(ai365RepChartSvg)가 그리는 모양 — 계열은 bar/line 뿐이고, 새 렌더러용으로 kind·refs·unit 을 덧붙인다."""
    # The shape the legacy SVG renderer draws (bar/line series only), plus kind/refs/unit for newer renderers.
    c = compute(chart, source, filters)
    return {"x": c["x"][:MAX_X_ITEMS], "xLabel": chart.get("xLabel") or (chart.get("x") or ""),
            "yLabel": chart.get("yLabel") or "", "kind": c["kind"], "unit": chart.get("unit") or "",
            "stack": bool(chart.get("stack")), "refs": c["refs"],
            # 옛 렌더러는 빈 칸을 모른다 — 계산 값의 빈 칸(첫 달의 전월 대비 등)은 0 으로 / the legacy renderer has no gaps: None → 0
            "series": [{"name": s["name"], "type": "line" if s["type"] == "line" else "bar",
                        "values": [0.0 if v is None else v for v in s["values"]], "yAxis": s["axis"]} for s in c["series"]]}


def fmt(v: float, unit: str = "") -> str:
    a = abs(v)
    if a >= 1e8:
        text = f"{v / 1e8:,.1f}억"
    elif a >= 1e4 or float(v).is_integer():
        text = f"{round(v):,}"
    else:
        text = f"{v:,.2f}".rstrip("0").rstrip(".")
    return text + unit


def auto_insight(chart: dict, computed: dict) -> str:
    """LLM 이 인사이트를 못 썼을 때의 결정적 한 줄 — 최댓값·최솟값 / deterministic one-liner (max and min) when the LLM wrote none"""
    series = computed.get("series") or []
    if not series or not series[0]["values"]:
        return ""
    s, x, unit = series[0], computed["x"], series[0].get("unit") or chart.get("unit") or ""
    seen = [i for i in range(len(x)) if s["values"][i] is not None]   # 계산 값의 빈 칸은 뺀다 / skip the gaps of calculated values
    if not seen:
        return ""
    if computed["kind"] == "kpi" or len(seen) == 1:
        return f"{s['name']}은(는) {fmt(s['values'][seen[0]], unit)}입니다."
    hi = max(seen, key=lambda i: s["values"][i])
    lo = min(seen, key=lambda i: s["values"][i])
    if s["values"][hi] == s["values"][lo]:
        return f"{s['name']}은(는) 모든 항목에서 {fmt(s['values'][hi], unit)}입니다."
    return (f"{s['name']} 기준으로 {x[hi]}이(가) {fmt(s['values'][hi], unit)}로 가장 높고, "
            f"{x[lo]}이(가) {fmt(s['values'][lo], unit)}로 가장 낮습니다.")


_PERIOD = re.compile(r"(^\d{4}([-./]\d{1,2}){0,2}$)|월$|분기$|년$|주$", re.I)
_PERIOD_COL = re.compile(r"date|month|year|week|quarter|일자|날짜|연도|년도|월|분기|기간|주차", re.I)
_ID_COL = re.compile(r"(^|_)(id|no|code|seq)$|번호|코드|사번", re.I)


def auto_chart_spec(source: dict) -> dict:
    """LLM 없이 고르는 첫 차트 — 첫 글자 컬럼이 x, 첫 숫자 컬럼이 y. 기간처럼 보이면 선, 아니면 큰 값 순 막대."""
    # The first chart picked without the LLM: first text column as x, first numeric column as y; a line when x looks
    # like a period, otherwise bars sorted by value.
    cols, types = source["columns"], source["types"]
    x = next((c for c in cols if types.get(c) == "text"), cols[0])
    # 값 후보에서 기간·번호처럼 생긴 숫자 컬럼(연도·월·id·코드)은 뺀다 — "부서별 연도 합계" 같은 차트가 나오지 않게
    # Numeric columns that look like a period or an identifier (year, month, id, code) are not value candidates
    nums = [c for c in cols if types.get(c) == "number" and c != x]
    ycol = next((c for c in nums if not _PERIOD_COL.search(c) and not _ID_COL.search(c)), None) or (nums[0] if nums else None)
    sample = [key(r[cols.index(x)]) for r in source["rows"][:12]]
    detected = x in (source.get("periods") or {})
    period = detected or bool(_PERIOD_COL.search(x)) or (sample and all(_PERIOD.search(v) for v in sample))
    spec = {"source": source["id"], "type": "line" if period else "bar", "x": x,
            "y": [{"col": ycol or "*"}], "title": f"{x}별 {ycol or '건수'}"}
    if detected:
        spec["sort"] = {"by": "x", "dir": "asc"}   # 기간으로 읽힌 x 는 기간 순(1월 < 2월 < 10월) / a detected period axis sorts by period
    if not period:
        spec["sort"] = {"by": "y", "dir": "desc"}
        spec["limit"] = 20
    return spec


# ────────────────────────────────────────────────────────
# 저장 데이터 ↔ 상태 / saved data ↔ state
# ────────────────────────────────────────────────────────

def items_of(state: dict) -> list[dict]:
    by_id = {s["id"]: s for s in state["sources"]}
    return [{"cid": c["id"], "title": c["title"], "insight": c.get("insight") or "",
             "chart": legacy_chart(c, by_id[c["source"]])} for c in state["charts"]]


def summary_of(state: dict) -> str:
    return " ".join(c["insight"] for c in state["charts"] if c.get("insight"))[:300]


def dashboard_data(state: dict) -> dict:
    """게시판·보관함에 저장되는 대시보드 데이터 — v2 상태 + 옛 소비자용 타일(items) / dashboard post data: v2 state + legacy tiles"""
    return {"type": "dashboard", "v": 2, "title": state["title"], "items": items_of(state),
            "sources": pack_sources(state["sources"]), "charts": state["charts"], "kpis": state.get("kpis") or [],
            "theme": state.get("theme") or {}}


def report_data(state: dict, chart_id: str, all_sources: bool = False) -> dict:
    """차트 하나만 리포트로 — 기본은 그 차트가 쓰는 Source 와 필터만 담는다(all_sources: 세션이 물고 있는 리포트는 전부 유지)."""
    # One chart as a report — by default only its source and filters (all_sources keeps everything for a session-backed report).
    chart = next((c for c in state["charts"] if c["id"] == chart_id), None)
    if chart is None:
        raise ValueError("해당 차트가 없습니다")
    src = next(s for s in state["sources"] if s["id"] == chart["source"])
    # 차트 하나만 떼어 낼 때는 그 Source 가 데이터를 직접 갖는다(복제본이어도 원본 없이 혼자 선다) / a lone chart's source carries its own data
    alone = {**src, "origin": {**src["origin"], "clone_of": ""}}
    return {"v": 2, "title": state["title"] if all_sources else chart["title"], "chart": legacy_chart(chart, src),
            "insight": chart.get("insight") or "",
            "table": {"columns": src["columns"], "rows": filtered_rows(src, chart["filters"])[:200]},
            "source": {"sql": src.get("sql") or None},
            "sources": pack_sources(state["sources"]) if all_sources else [alone], "charts": [chart],
            "kpis": (state.get("kpis") or []) if all_sources else [], "theme": state.get("theme") or {}}


def _legacy_pair(title: str, chart: dict, insight: str) -> tuple[dict, dict]:
    """옛 차트(x·values) → 그 값으로 만든 Source + 같은 그림이 나오는 차트 설정 / a legacy chart → a source built from its values + an equivalent spec"""
    xcol = _s(chart.get("xLabel"), 60) or "항목"
    series = [s for s in (chart.get("series") or []) if isinstance(s, dict)]
    names = []
    for s in series:
        name, k = _s(s.get("name"), 60) or "값", 2
        while name in names or name == xcol:
            name = f"{_s(s.get('name'), 56) or '값'}_{k}"
            k += 1
        names.append(name)
    x = [str(v) for v in (chart.get("x") or [])]
    rows = [[label] + [(s.get("values") or [])[i] if i < len(s.get("values") or []) else None for s in series]
            for i, label in enumerate(x)]
    source = {"columns": [xcol] + names, "rows": rows, "label": title,
              "origin": {"kind": "legacy", "note": "저장 당시의 차트 값"}}
    kind = chart.get("kind") if chart.get("kind") in CHART_TYPES else ("line" if series and all(s.get("type") == "line" for s in series) else "bar")
    spec = {"type": kind, "x": xcol, "title": title, "insight": insight, "yLabel": chart.get("yLabel") or "",
            "unit": chart.get("unit") or "", "stack": bool(chart.get("stack")),
            "y": [{"col": n, "agg": "sum", "name": n, "type": s.get("type"), "axis": s.get("yAxis")} for n, s in zip(names, series)]}
    return source, spec


def state_of(data: dict) -> dict:
    """저장 데이터 → 상태. v2 면 그대로 정규화, 옛 모양(차트 그림만)은 그 값으로 Source 를 만들어 바꾼다(출처 없음)."""
    # Saved data → state. v2 normalizes as is; the legacy shape (pictures only) is converted by building sources from
    # the chart values (no provenance).
    data = data if isinstance(data, dict) else {}
    if data.get("v") == 2 and isinstance(data.get("charts"), list) and isinstance(data.get("sources"), list):
        return normalize_state(data)
    sources, charts = [], []
    tiles = data.get("items") if data.get("type") == "dashboard" else [data]
    for t in (tiles or [])[:MAX_CHARTS]:
        if not isinstance(t, dict) or not isinstance(t.get("chart"), dict):
            continue
        src, spec = _legacy_pair(_s(t.get("title"), MAX_TITLE) or "리포트", t["chart"], _s(t.get("insight"), 600))
        src["id"] = f"s{len(sources) + 1}"
        spec["source"] = src["id"]
        sources.append(src)
        charts.append(spec)
    table = data.get("table") if isinstance(data.get("table"), dict) else {}
    if data.get("type") != "dashboard" and table.get("columns") and len(sources) < MAX_SOURCES:
        sql = (data.get("source") or {}).get("sql") if isinstance(data.get("source"), dict) else ""
        sources.append({"id": f"s{len(sources) + 1}", "columns": table.get("columns"), "rows": table.get("rows") or [],
                        "label": "원본 표", "sql": sql or "", "origin": {"kind": "legacy", "note": "저장 당시의 표"}})
    return normalize_state({"title": data.get("title"), "sources": sources, "charts": charts})


# ────────────────────────────────────────────────────────
# 세션 저장소 / session store
# ────────────────────────────────────────────────────────

def init_report_dash() -> None:
    with db._conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS report_dash(
              id TEXT PRIMARY KEY,
              owner TEXT NOT NULL,              -- 뷰애즈 신원(''=슈퍼) / view-as identity
              post_id TEXT,                     -- 내 보관함 글 id — [저장]으로 만들고 갱신하는 글 / the library post created and updated by [Save]
              origin_key TEXT NOT NULL DEFAULT '',  -- 같은 답변에서 다시 열면 이어가기 / resume key for the same answer
              origin TEXT NOT NULL DEFAULT '{}',
              state TEXT NOT NULL DEFAULT '{}',     -- 작업본(저장 전 상태; 글이 생겨도 유지) / the working copy (unsaved state, kept once a post exists)
              messages TEXT NOT NULL DEFAULT '[]',  -- 이 대시보드 전용 대화(공유·복사에 실리지 않는다) / dashboard-only conversation
              created TEXT NOT NULL,
              updated TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_report_dash_owner ON report_dash(owner, updated);
            CREATE INDEX IF NOT EXISTS idx_report_dash_post ON report_dash(post_id);
            """
        )
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(report_dash)").fetchall()}
        # 되돌리기(2026-09-19): 직전 차트 묶음(제목+차트 설정, 데이터 제외) 최대 MAX_UNDO 개 / undo stack of chart sets (no row data)
        if "undo" not in cols:
            conn.execute("ALTER TABLE report_dash ADD COLUMN undo TEXT NOT NULL DEFAULT '[]'")
        # 명시 저장(2026-09-22 사용자 결정 "자동 저장 말고 저장 버튼"): state 는 항상 작업본, dirty = 보관함 글과 다른 저장 안 된 변경, saved_at = 마지막 저장 시각
        # Explicit save (user decision 2026-09-22, "a save button instead of autosave"): `state` is always the working copy,
        # dirty = unsaved changes relative to the library post, saved_at = the last save
        if "dirty" not in cols:
            conn.execute("ALTER TABLE report_dash ADD COLUMN dirty INTEGER NOT NULL DEFAULT 0")
        if "saved_at" not in cols:
            conn.execute("ALTER TABLE report_dash ADD COLUMN saved_at TEXT NOT NULL DEFAULT ''")
        # 버전(2026-10-13): [{n, label, at, snap}] 오래된 것부터, snap = 되돌리기와 같은 모양(데이터 제외), 최대 MAX_VERSIONS 개
        # Versions (2026-10-13): [{n, label, at, snap}] oldest first, snap = the undo shape (no row data), up to MAX_VERSIONS
        if "versions" not in cols:
            conn.execute("ALTER TABLE report_dash ADD COLUMN versions TEXT NOT NULL DEFAULT '[]'")
    purge_drafts()


def origin_key(chat_id: str, sqls: list[str]) -> str:
    """같은 채팅의 같은 조회 결과 묶음이면 같은 키 — 다시 누르면 그 세션을 잇는다 / same chat + same queries → same key (resume)"""
    sqls = [s for s in (sqls or []) if s]
    if not chat_id or not sqls:
        return ""
    return hashlib.sha1((chat_id + "\n" + "\n".join(sqls)).encode("utf-8")).hexdigest()[:24]


def _board(owner: str) -> str:
    return f"me:{owner}"


def _own_post(owner: str, post_id: str | None) -> dict | None:
    if not post_id:
        return None
    from app import boards
    p = boards.get_post(post_id)
    return p if p is not None and p.get("board") == _board(owner) else None


def _post_state(post: dict) -> dict:
    """보관함 글 → 상태(제목은 글의 것) / library post → state, titled after the post"""
    state = state_of(post.get("data") or {})
    state["title"] = _s(post.get("title"), MAX_TITLE) or state["title"]
    return state


def _session(row) -> dict | None:
    """세션 행 → 세션(상태 포함). 상태는 세션의 **작업본**이다(2026-09-22 명시 저장: 보관함 글은 [저장]을 눌렀을 때 찍은 사본).
    보관함 글이 지워졌으면 세션도 없는 것으로 본다. 명시 저장 전에 만든 옛 행(작업본 비어 있음)은 글에서 작업본을 되살린다."""
    # row → session. The state is the session's **working copy** (explicit save since 2026-09-22: the library post is the copy
    # taken when [Save] was pressed). A deleted library post ends the session. Rows from before explicit save (empty working
    # copy) rebuild it from the post.
    if row is None:
        return None
    post = None
    if row["post_id"]:
        post = _own_post(row["owner"], row["post_id"])
        if post is None:
            delete_session(row["id"])
            return None
    raw = json.loads(row["state"] or "{}")
    state = normalize_state(raw) if (raw or post is None) else _post_state(post)
    keys = row.keys()
    return {"id": row["id"], "owner": row["owner"], "post_id": row["post_id"] or None,
            "saved": bool(row["post_id"]), "kind": (post or {}).get("kind") or "dashboard",
            "dirty": bool(row["dirty"]) if "dirty" in keys else False,
            "saved_at": (row["saved_at"] if "saved_at" in keys else "") or ((post or {}).get("updated") or ""),
            "can_undo": bool(json.loads(row["undo"] or "[]")) if "undo" in keys else False,
            # 버전 목록(가벼운 모양, 2026-10-13): 열이 없는 옛 행은 버전 없음 / the light version list; old rows without the column have none
            "versions": _light_versions(row["versions"]) if "versions" in keys else [],
            "origin": json.loads(row["origin"] or "{}"), "state": state,
            "messages": json.loads(row["messages"] or "[]"), "created": row["created"], "updated": row["updated"]}


def create_session(owner: str, state: dict, key_: str = "", origin: dict | None = None, post_id: str | None = None) -> dict:
    """세션 생성 — post_id 가 있으면(보관함 글 열기) 그 글이 작업본의 출발점이다 / new session; with post_id the post seeds the working copy"""
    sid = "rd_" + uuid.uuid4().hex[:10]
    now = _now()
    post = _own_post(owner, post_id) if post_id else None
    if post is not None:
        state = _post_state(post)
    packed = json.dumps(pack_state(state), ensure_ascii=False) if (post is not None or not post_id) else "{}"
    with db._conn() as conn:
        conn.execute("INSERT INTO report_dash(id, owner, post_id, origin_key, origin, state, messages, created, updated, saved_at)"
                     " VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (sid, owner, post_id, key_, json.dumps(origin or {}, ensure_ascii=False), packed, "[]", now, now,
                      (post or {}).get("updated") or ""))
    return get_session(sid)


def get_session(sid: str, owner: str | None = None) -> dict | None:
    with db._conn() as conn:
        row = conn.execute("SELECT * FROM report_dash WHERE id=?", (sid,)).fetchone()
    if row is None or (owner is not None and row["owner"] != owner):
        return None
    return _session(row)


def find_by_origin(owner: str, key_: str) -> dict | None:
    if not key_:
        return None
    with db._conn() as conn:
        row = conn.execute("SELECT * FROM report_dash WHERE owner=? AND origin_key=? ORDER BY updated DESC LIMIT 1",
                           (owner, key_)).fetchone()
    return _session(row)


def find_by_post(owner: str, post_id: str) -> dict | None:
    with db._conn() as conn:
        row = conn.execute("SELECT * FROM report_dash WHERE owner=? AND post_id=? ORDER BY updated DESC LIMIT 1",
                           (owner, post_id)).fetchone()
    return _session(row)


def save_state(sid: str, state: dict, touch: bool = True) -> dict | None:
    """작업본 저장(세션 행에만) — 보관함 글은 건드리지 않는다(2026-09-22 명시 저장: 글은 save_to_library 가 [저장]에서만 쓴다).
    touch 면 '저장하지 않은 변경'(dirty)으로 표시한다 — 첫 자동 차트처럼 사용자가 바꾼 게 아닌 것은 touch=False."""
    # Write the working copy to the session row only; the library post is untouched (explicit save since 2026-09-22:
    # save_to_library writes the post on [Save]). touch flags the session dirty (unsaved changes); the first automatic
    # charts are not the user's change, so they pass touch=False.
    state = normalize_state(state)
    with db._conn() as conn:
        cur = conn.execute("UPDATE report_dash SET state=?, dirty=CASE WHEN ? THEN 1 ELSE dirty END, updated=? WHERE id=?",
                           (json.dumps(pack_state(state), ensure_ascii=False), 1 if touch else 0, _now(), sid))
    if cur.rowcount == 0:
        return None
    return get_session(sid)


def save_to_library(sid: str) -> dict | None:
    """[저장] — 작업본을 내 보관함 글로 만든다(처음) 또는 그 글을 갱신한다(다시). 대화는 싣지 않는다. 차트가 없으면 ValueError.
    글이 있고 종류가 리포트였는데 차트가 하나면 리포트로, 아니면 대시보드로 저장한다."""
    # [Save]: create the library post from the working copy (first time) or update it (again). The conversation never goes
    # along. No charts → ValueError. An existing report post with a single chart stays a report; otherwise dashboard.
    from app import boards
    with db._conn() as conn:
        row = conn.execute("SELECT * FROM report_dash WHERE id=?", (sid,)).fetchone()
    s = _session(row)
    if s is None:
        return None
    state = s["state"]
    if not state["charts"]:
        raise ValueError("차트가 없는 대시보드는 저장할 수 없습니다")
    owner, post_id = s["owner"], s["post_id"]
    post = _own_post(owner, post_id)
    kind = "report" if post is not None and post.get("kind") == "report" and len(state["charts"]) == 1 else "dashboard"
    data = report_data(state, state["charts"][0]["id"], all_sources=True) if kind == "report" else dashboard_data(state)
    patch = {"kind": kind, "title": state["title"], "summary": summary_of(state), "data": data}
    if post is None:
        origin = s["origin"]
        saved = boards.add_post(_board(owner), {**patch, "author": {"id": owner, "name": ""},
                                                 "source": {k: str(v)[:200] for k, v in origin.items() if v}})
        post_id = saved["id"]
    else:
        boards.update_post(post_id, patch)
    now = _now()
    with db._conn() as conn:
        conn.execute("UPDATE report_dash SET post_id=?, dirty=0, saved_at=?, updated=? WHERE id=?", (post_id, now, now, sid))
    return get_session(sid)


def reload_from_post(sid: str, clear_undo: bool = False) -> dict | None:
    """작업본을 보관함 글(마지막 저장본)로 되돌린다. 글이 없으면 None / reset the working copy to the library post; None without a post"""
    with db._conn() as conn:
        row = conn.execute("SELECT * FROM report_dash WHERE id=?", (sid,)).fetchone()
    if row is None:
        return None
    post = _own_post(row["owner"], row["post_id"]) if row["post_id"] else None
    if post is None:
        return None
    with db._conn() as conn:
        conn.execute("UPDATE report_dash SET state=?, dirty=0, undo=CASE WHEN ? THEN '[]' ELSE undo END, updated=? WHERE id=?",
                     (json.dumps(pack_state(_post_state(post)), ensure_ascii=False), 1 if clear_undo else 0, _now(), sid))
    return get_session(sid)


def discard_changes(sid: str) -> dict | None:
    """저장하지 않고 닫기 — 글이 있으면 작업본을 마지막 저장본(글)으로 되돌리고 되돌리기 스택을 비운다. 한 번도 저장하지 않은 초안은 세션째 지운다(None)."""
    # Close without saving: with a post, the working copy goes back to the last saved copy (the post) and the undo stack is
    # cleared; a never-saved draft is deleted with its session (returns None).
    kept = reload_from_post(sid, clear_undo=True)
    if kept is None:
        delete_session(sid)
    return kept


def append_messages(sid: str, new: list[dict]) -> None:
    with db._conn() as conn:
        row = conn.execute("SELECT messages FROM report_dash WHERE id=?", (sid,)).fetchone()
        if row is None:
            return
        msgs = (json.loads(row["messages"] or "[]") + list(new))[-MAX_MESSAGES:]
        conn.execute("UPDATE report_dash SET messages=?, updated=? WHERE id=?",
                     (json.dumps(msgs, ensure_ascii=False), _now(), sid))


def _snap(state: dict) -> dict:
    """되돌리기 · 버전이 남기는 모양: 제목 + 차트 설정 + KPI 카드 + 테마(데이터는 빼고) / what undo and versions keep (no row data)"""
    return {"title": state["title"], "charts": state["charts"], "kpis": state.get("kpis") or [], "theme": state.get("theme") or {}}


def push_undo(sid: str, state: dict) -> None:
    """바꾸기 직전의 제목+차트 설정을 쌓는다(데이터는 빼고 — Source 는 늘기만 한다) / stack the title and chart specs before a change"""
    snap = _snap(state)
    with db._conn() as conn:
        row = conn.execute("SELECT undo FROM report_dash WHERE id=?", (sid,)).fetchone()
        if row is None:
            return
        stack = json.loads(row["undo"] or "[]")
        if stack and stack[-1] == snap:
            return
        conn.execute("UPDATE report_dash SET undo=? WHERE id=?", (json.dumps((stack + [snap])[-MAX_UNDO:], ensure_ascii=False), sid))


def pop_undo(sid: str) -> dict | None:
    with db._conn() as conn:
        row = conn.execute("SELECT undo FROM report_dash WHERE id=?", (sid,)).fetchone()
        stack = json.loads(row["undo"] or "[]") if row is not None else []
        if not stack:
            return None
        snap = stack.pop()
        conn.execute("UPDATE report_dash SET undo=? WHERE id=?", (json.dumps(stack, ensure_ascii=False), sid))
    return snap


# ────────────────────────────────────────────────────────
# 버전(2026-10-13) / versions
# 채팅의 답변마다 "V1 · 대시보드 생성" 칩이 붙고, 누르면 그 시점의 대시보드를 미리 보고, [이 버전으로 이어가기]로 작업본을 그 버전으로 바꾼다.
# 버전이 생기는 때: 첫 차트(대시보드 생성) · 상태를 바꾼 턴(성공한 도구 이름) · 이어가기. 되돌리기 · 화면 조작 · 저장 · discard 는 버전을
# 만들지 않고 목록도 지우지 않는다(이력이다). 스냅은 되돌리기와 같은 모양(데이터 제외), 미리보기 · 이어가기는 지금 데이터(Source)로 그린다.
# Every answer in the chat gets a "V1 · 대시보드 생성" chip; it previews that moment's dashboard and [Continue from this version]
# makes it the working copy. Versions come from the first charts, turns that changed the state (named after the tools that
# succeeded) and continuing; undo, UI ops, saving and discard neither add nor remove any (it is history). A snap has the undo
# shape (no row data); previews and continuing draw it on the current sources.
# ────────────────────────────────────────────────────────

VERSION_RESTORE_LABEL = "V{n}에서 이어가기"
VERSION_RESTORE_TEXT = "V{n} 시점의 대시보드로 되돌렸습니다. 이어서 요청해 주세요."


def _light_versions(raw: str | None) -> list[dict]:
    """저장된 버전 목록 → 가벼운 모양 [{n, label, at}](스냅 없음, 오래된 것부터) / stored versions → the light list, no snaps"""
    return [{"n": v.get("n"), "label": v.get("label") or "", "at": v.get("at") or ""}
            for v in json.loads(raw or "[]") if isinstance(v, dict)]


def push_version(sid: str, state: dict, label: str) -> int:
    """버전 하나 추가: 그 시점의 제목 · 차트 설정 · KPI 카드 · 테마(데이터 제외)를 남기고 새 번호를 돌려준다. MAX_VERSIONS 를 넘으면
    가장 오래된 것부터 버리되 번호는 이어 간다(마지막 번호 + 1). 이름은 MAX_VERSION_LABEL 자까지, 비면 '변경'. 세션이 없으면 0."""
    # Add a version: keep that moment's title, chart specs, KPI cards and theme (no row data) and return its number. Past
    # MAX_VERSIONS the oldest are dropped while numbering continues (last number + 1). The label is capped at
    # MAX_VERSION_LABEL characters ('변경' when blank). 0 when the session is gone.
    with db._conn() as conn:
        row = conn.execute("SELECT versions FROM report_dash WHERE id=?", (sid,)).fetchone()
        if row is None:
            return 0
        vers = json.loads(row["versions"] or "[]")
        n = (int(vers[-1].get("n") or 0) if vers else 0) + 1
        vers.append({"n": n, "label": _s(label, MAX_VERSION_LABEL) or "변경", "at": _now(), "snap": _snap(state)})
        conn.execute("UPDATE report_dash SET versions=? WHERE id=?", (json.dumps(vers[-MAX_VERSIONS:], ensure_ascii=False), sid))
    return n


def list_versions(sid: str) -> list[dict]:
    """버전 목록(가벼운 모양 {n, label, at}, 오래된 것부터) / the version list, light and oldest first"""
    with db._conn() as conn:
        row = conn.execute("SELECT versions FROM report_dash WHERE id=?", (sid,)).fetchone()
    return _light_versions(row["versions"]) if row is not None else []


def get_version(sid: str, n: int) -> dict | None:
    """버전 하나(스냅 포함). 없거나 상한으로 밀려난 번호면 None / one version with its snap; None when unknown or trimmed"""
    with db._conn() as conn:
        row = conn.execute("SELECT versions FROM report_dash WHERE id=?", (sid,)).fetchone()
    if row is None:
        return None
    return next((v for v in json.loads(row["versions"] or "[]") if isinstance(v, dict) and v.get("n") == n), None)


def version_state(snap: dict, state: dict) -> dict:
    """버전 스냅(제목 · 차트 · KPI 카드 · 테마) + 지금 데이터(state 의 Source) → 상태. Source 는 늘기만 하므로 그 시점의 차트가
    쓰던 데이터가 남아 있다(복제본은 원본을 다시 가리킨다)."""
    # A version snap (title, charts, KPI cards, theme) on top of the current sources of `state`. Sources only ever grow, so
    # the data the charts of that moment used is still there (clones are linked to their root again).
    return normalize_state({**snap, "sources": pack_sources(state["sources"])})


def restore_version(sid: str, n: int) -> dict | None:
    """[이 버전으로 이어가기]: 작업본을 버전 n 의 스냅 + 지금 데이터로 바꾼다. 지금 상태와 다르면 되돌리기에 쌓고, 새 버전
    'V{n}에서 이어가기' 와 안내 메시지(ver = 새 번호)를 남기며, 저장하지 않은 변경(dirty)이 된다. 세션이나 버전이 없으면 None."""
    # [Continue from this version]: the working copy becomes version n's snap on the current sources. When that differs from
    # the current state it is pushed to undo first; a new version 'V{n}에서 이어가기' and a notice (ver = the new number) are
    # added and the session turns dirty. None when the session or the version is missing.
    s = get_session(sid)
    v = get_version(sid, n) if s is not None else None
    if v is None:
        return None
    cur = s["state"]
    state = version_state(v.get("snap") or {}, cur)
    if _snap(state) != _snap(cur):
        push_undo(sid, cur)
    ver = push_version(sid, state, VERSION_RESTORE_LABEL.format(n=n))
    append_messages(sid, [{"role": "agent", "text": VERSION_RESTORE_TEXT.format(n=n), "trace": [], "ts": _now(), "ver": ver}])
    return save_state(sid, state, touch=True)


def delete_session(sid: str) -> None:
    with db._conn() as conn:
        conn.execute("DELETE FROM report_dash WHERE id=?", (sid,))


def delete_by_post(post_id: str) -> None:
    try:
        with db._conn() as conn:
            conn.execute("DELETE FROM report_dash WHERE post_id=?", (post_id,))
    except sqlite3.OperationalError:   # 세션 테이블이 없는 DB(옛 DB·격리 테스트) — 지울 세션도 없다 / no session table yet, so nothing to delete
        pass


def purge_drafts(hours: int = DRAFT_TTL_HOURS) -> int:
    """열어만 보고 닫은 초안 정리 / drop drafts that were only opened"""
    limit = (kst.now() - timedelta(hours=hours)).isoformat(timespec="seconds")
    with db._conn() as conn:
        cur = conn.execute("DELETE FROM report_dash WHERE post_id IS NULL AND updated < ?", (limit,))
    return cur.rowcount
