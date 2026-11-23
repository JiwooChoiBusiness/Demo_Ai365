"""홈 대시보드 배치 · 사용자가 만든 위젯 저장소(2026-11-13 1단계, 2026-11-16 위젯 에이전트 — 계약 = docs/widget-agent.md).

홈(/home) 그룹웨어 대시보드의 배치(레이아웃 3종 · 세 열)와 사람마다 만든 위젯(정의 spec + 표시 모델 model)을 SQLite 에
둔다(db._conn 을 호출 시점에 쓴다: 테스트가 임시 DB 로 바꿔 끼운다). 기본 위젯 9개는 저장하지 않는 상수이고 지울 수 없다.
만든 위젯은 만든 사람(owner = acting_user_id, 빈 문자열 = 데모 기본 사용자)만 쓴다.
만든 위젯의 정의는 리포트 에이전트 대시보드의 작은 판이다(데이터 0~1 · 차트 0~1 · KPI 카드 0~4 · 테마 · 인사이트 틀). 숫자는
리포트 에이전트의 계산(report_dash.compute · kpi_value)이 정하고 화면은 그리기만 한다(AI 가 숫자를 지어 넣지 않는다).
데이터는 아직 사용자가 준 표(tool: inline)뿐이다 — 데이터를 가져오는 도구는 다음 단계다.
배치(2026-11-17 4단계)는 3열 격자다: 위젯마다 x · y(칸 위치)와 가로 w · 세로 h(칸 수)를 두고, 위젯별 처음 크기 · 최소 · 최대(SIZES)를
지킨다. 겹치면 아래로 밀고 빈 곳은 위로 당긴다. 옛 세 열 형식(실제 제품 모양)도 읽어서 격자로 바꾼다. 저장할 때 형식 · 레이아웃이 틀리면
ConfigError, 값이 범위를 넘으면 조용히 맞춘다.

Home dashboard layout and user-made widgets store (phase 1 on 2026-11-13, the widget agent on 2026-11-16; contract =
docs/widget-agent.md). Keeps the layout of the home (/home) groupware dashboard (three layouts, three columns) and each
person's made widgets (definition spec plus display model) in SQLite, using db._conn at call time (tests swap it for a
temp DB). The nine built-in widgets are constants, never stored and never deletable. A made widget belongs to its maker
only (owner = acting_user_id; the empty string is the demo default user).
A made widget's definition is a small board of the report agent's dashboard (0..1 data, 0..1 chart, 0..4 KPI cards, a
theme and an insight template). The report agent's math (report_dash.compute / kpi_value) settles the numbers and the
screen only draws (the AI never writes numbers in). The only data so far is a table the user gave (tool: inline); fetching
tools come next. The layout (phase 4, 2026-11-17) is a 3-column grid: each widget has x / y (cell position) and w / h (cells),
within per-widget default, minimum and maximum sizes; overlaps are pushed down and gaps pulled up. The older three-column
shape (the real product's) still reads and becomes a grid. A save with a wrong shape or layout raises ConfigError; out-of-range
values are quietly fitted.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets

from app import db, kst, report_dash as rd

# ────────────────────────────────────────────────────────
# 상수 / constants
# ────────────────────────────────────────────────────────

# 기본 위젯 9개(지금 홈 파일의 위젯, 문서 3절 순서). wx 는 실제 제품의 LOCKED_WIDGETS 처럼 ✕ 가 없다(locked).
# The nine built-in widgets (the home file's widgets today, in the order of section 3). wx has no ✕, like the real
# product's LOCKED_WIDGETS (locked).
BUILTIN: list[dict] = [
    {"key": "wx", "name": "오늘의 날씨", "locked": True},
    {"key": "cal", "name": "일정", "locked": False},
    {"key": "tok", "name": "토큰 사용량", "locked": False},
    {"key": "ask", "name": "AI 질문", "locked": False},
    {"key": "sc", "name": "바로가기", "locked": False},
    {"key": "coll", "name": "컬렉션", "locked": False},
    {"key": "att", "name": "근태관리", "locked": False},
    {"key": "org", "name": "조직도", "locked": False},
    {"key": "gwb", "name": "그룹웨어 게시판", "locked": False},
]
BUILTIN_KEYS: tuple[str, ...] = tuple(w["key"] for w in BUILTIN)

# 레이아웃 = 세 열의 너비 비율(실제 제품과 같다) / layouts = width ratios of the three columns (same as the real product)
LAYOUT_OPTIONS: list[dict] = [
    {"value": "1:1:1", "ratios": [1, 1, 1]},
    {"value": "2:3:3", "ratios": [2, 3, 3]},   # 왼쪽 좁게 / narrow left
    {"value": "1:2:1", "ratios": [1, 2, 1]},   # 가운데 넓게 / wide center
]
LAYOUT_VALUES: tuple[str, ...] = tuple(o["value"] for o in LAYOUT_OPTIONS)
DEFAULT_LAYOUT = "1:1:1"
COLUMN_COUNT = 3
DEFAULT_COLUMNS: tuple[tuple[str, ...], ...] = (("wx", "cal", "tok"), ("ask", "sc", "coll", "att"), ("org", "gwb"))

# 4단계(2026-11-17) 격자: 가로 3칸(열 너비 = 기본 비율), 세로 1칸 = 240px(화면 쪽 값). 위젯 크기 = (처음 가로, 처음 세로, 최소 가로,
# 최대 가로, 최소 세로, 최대 세로) — 2026-11-17 실측(1600px 화면, 열 413px)으로 정했다: 날씨 219 · 일정 401 · 토큰 212 · AI 질문 183 ·
# 바로가기 237 · 컬렉션 185 · 근태 217 · 조직도 524 · 게시판 288px.
# Phase-4 grid: three columns across (widths follow the base ratio), one row = 240px (a screen value). Sizes = (default w,
# default h, min w, max w, min h, max h), set from the 2026-11-17 measurements at 1600px (columns 413px wide).
GRID_COLS = 3
MAX_GRID_ROW = 300
SIZES: dict[str, tuple[int, int, int, int, int, int]] = {
    "wx": (1, 1, 1, 2, 1, 1),     # 날씨: 뺄 수 없다 / weather: cannot be removed
    "cal": (1, 2, 1, 2, 2, 3),    # 일정: 달력 + 그날 일정 / calendar plus the day's events
    "tok": (1, 1, 1, 2, 1, 1),
    "ask": (1, 1, 1, 3, 1, 1),
    "sc": (1, 1, 1, 3, 1, 2),
    "coll": (1, 1, 1, 2, 1, 3),
    "att": (1, 1, 1, 2, 1, 1),
    "org": (1, 2, 1, 3, 2, 3),
    "gwb": (1, 2, 1, 3, 1, 3),
}
CUSTOM_LIMITS = (1, 3, 1, 3)   # 만든 위젯: 가로 1~3 · 세로 1~3 / made widgets
# 처음 배치 = 지금 홈과 같은 순서, 세 열 모두 4칸에서 끝난다 / the default grid: today's order, every column ends at row 4
DEFAULT_ITEMS: tuple[tuple[str, int, int, int, int], ...] = (
    ("wx", 0, 0, 1, 1), ("cal", 0, 1, 1, 2), ("tok", 0, 3, 1, 1),
    ("ask", 1, 0, 1, 1), ("sc", 1, 1, 1, 1), ("coll", 1, 2, 1, 1), ("att", 1, 3, 1, 1),
    ("org", 2, 0, 1, 2), ("gwb", 2, 2, 1, 2))

MAX_WIDGETS = 30                     # 한 사람이 만들 수 있는 위젯 수 / made widgets per owner
SPEC_VERSION = 2                     # 2026-11-16 리포트 에이전트 모양(1단계의 보기 6종은 없어졌다) / the report agent's shape (phase 1's six views are gone)
NEW_TITLE = "새 위젯"                # 작업본의 기본 제목 / a draft's default title
SOURCE_ID, CHART_ID = "s1", "c1"     # 위젯의 데이터 · 차트 id(하나씩뿐) / the widget's only data and chart ids

# 정의 한도(문서 6절) / definition limits (section 6)
MAX_TITLE = 40
MAX_COLUMNS = 12
MAX_COLUMN_NAME = 40
MAX_ROWS = 200
MAX_CELL = rd.MAX_CELL               # 칸 하나의 글자 수 = 리포트 에이전트와 같은 300(그쪽 정규화가 몰래 자르지 않게) / 300 as in the report agent, so its normalization never cuts silently
MAX_SPEC_CHARS = 100_000             # 정규화된 정의 JSON 의 글자 수(표 전체 포함) / characters of the normalized definition JSON (the table included)
MAX_KPIS = 4                         # 위젯 하나의 KPI 카드 수(홈의 한 열에 2 × 2) / KPI cards per widget (2 × 2 in one home column)
MAX_KPI_LABEL = 40
MAX_INSIGHT = 300
_CHART_DROP = ("drill", "notes", "compare")   # 위젯에서 쓰지 않는 리포트 차트 항목 / report chart fields widgets do not use
# 3단계(2026-11-16) 데이터 파이프라인: 내용의 출처(origin)와 숫자가 아닌 내용(blocks: 글 · 목록) / phase 3: where content came from and non-numeric content
ORIGIN_KINDS = ("data", "docs", "web")
ORIGIN_LABEL = {"data": "사내 데이터", "docs": "사내 문서", "web": "웹 검색"}
REF_KINDS = ("data", "doc", "web")
VIEWS = ("kpi", "chart", "list", "text")
# 출처는 위젯의 부분마다 따로(2026-11-16 3단계 검토: 출처 하나를 덮어써 사내 데이터 차트가 웹 출처로 바뀌고 다시 가져오지 못했다)
# one origin per part of the widget (phase-3 review: a single origin was overwritten, so a company-data chart turned 'web' and stopped refreshing)
PARTS = ("source", "cards", "text", "list")   # 표(차트 · 데이터 카드) · 고정 숫자 카드 · 글 · 목록 / table, fixed cards, text, list
MAX_ORIGINS = 8
MAX_SQL = 20_000                     # 넘는 SQL 은 자르지 않고 버린다(잘린 SQL 은 다시 가져오기에서 조용히 실패했다) / longer SQL is dropped, never cut
MAX_REFS = 6
MAX_BLOCK_TEXT = 600
MAX_BLOCK_ITEMS = 8
# 위젯 에이전트 대화 저장(2026-11-19 사용자 결정 "다 넣어줘" — 위젯마다, 다시 열면 이어서) / the widget agent's saved conversation (per widget)
MAX_CHAT_MSGS = 60                   # 대화 줄 수(오래된 것부터 버린다) / conversation entries (oldest dropped)
MAX_CHAT_HIST = 10                   # 변경 기록(되돌리기) 수 = 화면의 MAX_UNDO / history states = the screen's MAX_UNDO
MAX_CHAT_CHARS = 600_000             # 저장본 JSON 글자 수 / characters of the stored JSON
MAX_CHAT_LABEL = 80


class SpecError(ValueError):
    """위젯 정의 오류(메시지 = 사용자에게 보일 문장) / widget definition error (the message is user-facing)."""


class ConfigError(ValueError):
    """대시보드 배치 오류(저장할 때만) / dashboard layout error (on save only)."""


class WidgetError(ValueError):
    """그 밖의 위젯 오류(개수 상한 등) / other widget errors (the per-owner cap and the like)."""


def init_home_widgets() -> None:
    """표 생성(멱등) / create the tables (idempotent)."""
    with db._conn() as conn:  # noqa: SLF001  테스트가 db._conn 을 임시 DB 로 바꾼다 / tests swap db._conn for a temp DB
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS home_dash_config(
              owner TEXT PRIMARY KEY,           -- acting_user_id('' = 데모 기본 사용자 / the demo default user)
              layout_type TEXT NOT NULL,
              columns TEXT NOT NULL,            -- 정규화된 세 열 JSON / the normalized three columns as JSON
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS home_widgets(
              id TEXT PRIMARY KEY,              -- 'cw_' + 16진 8자 / 'cw_' plus eight hex characters
              owner TEXT NOT NULL,
              title TEXT NOT NULL,
              spec TEXT NOT NULL,               -- 정규화된 정의 JSON / the normalized definition as JSON
              model TEXT NOT NULL,              -- 마지막으로 계산한 표시 모델 JSON / the last computed display model as JSON
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_home_widgets_owner ON home_widgets(owner, created_at);
            CREATE TABLE IF NOT EXISTS home_widget_meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS home_widget_chats(
              owner TEXT NOT NULL,
              widget TEXT NOT NULL,             -- home_widgets.id(위젯을 지우면 같이 지운다 / removed with the widget)
              chat TEXT NOT NULL,               -- 정규화된 대화 저장본 JSON / the normalized conversation as JSON
              updated_at TEXT NOT NULL,
              PRIMARY KEY(owner, widget)
            );
            """
        )


# ────────────────────────────────────────────────────────
# 조회 SQL 서명(3단계 검토): 정의는 화면이 들고 다니므로 origins[].sql 을 그대로 믿으면 사용자가 지은 SQL 이 /data 에서 실행된다.
# 파이프라인이 만든 SQL 에만 서버 서명(sig = HMAC(신원 + SQL))을 붙이고, 저장할 때 서명이 맞지 않는 SQL 은 버린다(그 부분은 다시 가져오지 않는다).
# Signing the query SQL (phase-3 review): the screen carries the definition, so trusting origins[].sql would run user-written SQL
# in /data. Only SQL made by the pipeline carries a server signature (HMAC over identity + SQL); a save drops SQL whose signature
# does not match (that part then never refreshes).
# ────────────────────────────────────────────────────────

_SECRET: bytes | None = None


def _secret() -> bytes:
    """설치마다 한 번 만들어 DB 에 두는 서명 키(재시작해도 같다) / a per-install signing key kept in the DB (survives restarts)"""
    global _SECRET
    if _SECRET is None:
        with db._conn() as conn:  # noqa: SLF001
            conn.execute("CREATE TABLE IF NOT EXISTS home_widget_meta(k TEXT PRIMARY KEY, v TEXT NOT NULL)")
            conn.execute("INSERT OR IGNORE INTO home_widget_meta(k, v) VALUES('sql_key', ?)", (secrets.token_hex(32),))
            row = conn.execute("SELECT v FROM home_widget_meta WHERE k = 'sql_key'").fetchone()
        _SECRET = bytes.fromhex(row["v"] if hasattr(row, "keys") else row[0])
    return _SECRET


def sign_sql(owner, sql: str) -> str:
    """신원 + SQL 의 서명 / the signature of identity + SQL"""
    return hmac.new(_secret(), f"{_own(owner)}\n{sql}".encode("utf-8"), hashlib.sha256).hexdigest()


def _trusted(owner, origins: list[dict]) -> list[dict]:
    """서명이 맞지 않는 SQL 은 버린다 / drops SQL whose signature does not match"""
    out = []
    for o in origins:
        if o["sql"] and not hmac.compare_digest(o.get("sig") or "", sign_sql(owner, o["sql"])):
            o = {**o, "sql": "", "sig": "", "tables": []}
        out.append(o)
    return out


def _own(owner) -> str:
    """신원 정리: 앞뒤 공백을 뺀 문자열, 없으면 '' / identity: the stripped string, '' when missing."""
    return str(owner or "").strip()


def _dumps(obj) -> str:
    # NaN · 무한대는 정규화에서 이미 걸러진다(allow_nan=False 는 그 약속의 확인) / NaN and infinity never get this far
    return json.dumps(obj, ensure_ascii=False, allow_nan=False)


def _loads(text, fallback):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return fallback


# ────────────────────────────────────────────────────────
# 배치 / layout (문서 4절 / section 4)
# ────────────────────────────────────────────────────────

def size_of(key: str, model=None) -> dict:
    """위젯 크기 {w, h, min_w, max_w, min_h, max_h}(칸). 기본 위젯은 SIZES, 만든 위젯은 가로 1~3 · 세로 1~3 이고 처음 크기는 위젯 에이전트에서
    고른 크기(모델의 size, 2026-11-19), 없으면 차트가 있을 때 1 × 2, 아니면 1 × 1.
    A widget's size in cells: built-ins from SIZES; made widgets 1..3 by 1..3, starting at the size picked in the widget agent
    (the model's size, 2026-11-19), else 1 × 2 with a chart and 1 × 1 without."""
    if key in SIZES:
        w, h, a, b, c, d = SIZES[key]
    else:
        a, b, c, d = CUSTOM_LIMITS
        picked = model.get("size") if isinstance(model, dict) else None
        if isinstance(picked, dict) and all(isinstance(picked.get(k), int) and not isinstance(picked.get(k), bool) for k in ("w", "h")):
            w, h = min(max(picked["w"], a), b), min(max(picked["h"], c), d)
        else:
            chart = isinstance(model, dict) and isinstance(model.get("chart"), dict) and model["chart"].get("type") != "kpi"
            w, h = 1, 2 if chart else 1
    return {"w": w, "h": h, "min_w": a, "max_w": b, "min_h": c, "max_h": d}


def default_config() -> dict:
    """처음 배치: 1:1:1, DEFAULT_ITEMS(지금 홈과 같은 순서)를 격자 차례(y · x)로 — 읽기 정규화를 거쳐도 그대로다
    The default layout: 1:1:1 with DEFAULT_ITEMS in grid order (y, x), unchanged by normalization"""
    items = [{"widget_key": k, "x": x, "y": y, "w": w, "h": h} for k, x, y, w, h in DEFAULT_ITEMS]
    return {"layout_type": DEFAULT_LAYOUT, "items": sorted(items, key=lambda i: (i["y"], i["x"]))}


def _order_value(value) -> float:
    """sort_order 의 정렬 값: 유한한 숫자만 그대로, 없거나 숫자가 아니면 맨 뒤(무한대).
    The sort value of sort_order: finite numbers as they are; missing or non-numeric goes last (infinity)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return math.inf
    try:
        x = float(value)
    except OverflowError:
        return math.inf
    return x if math.isfinite(x) else math.inf


def _int(value, fallback: int) -> int:
    """정수 칸 값(참/거짓 · 글자 · 무한대 · NaN 은 fallback, 소수는 0.5 에서 올림 = 화면 hdInt 의 Math.round 와 같다 — 4단계 검토)
    An integer cell value (booleans, text, infinities and NaN fall back; halves round up, like Math.round in the screen's hdInt)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    try:
        return int(math.floor(float(value) + 0.5))
    except (OverflowError, ValueError):
        return fallback


def _overlap(a: dict, b: dict) -> bool:
    return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]


def settle(items: list[dict]) -> list[dict]:
    """겹침 풀기 + 위로 당기기(화면의 hdSettle 과 같은 규칙): 위에서 아래 · 왼쪽에서 오른쪽 차례로, 앞에 놓인 위젯과 겹치면 그 아래로 밀고,
    다 놓은 뒤 위가 비어 있는 위젯은 위로 당긴다. 결과는 y · x 순. 이미 정리된 배치는 그대로다(멱등).
    Resolves overlaps and pulls gaps up (the same rule as the screen's hdSettle): top to bottom and left to right, an item
    overlapping an earlier one moves below it; afterwards every item rises while the space above is free. Sorted by y, x;
    an already settled layout stays as it is (idempotent)."""
    placed: list[dict] = []
    for it in sorted(items, key=lambda i: (i["y"], i["x"], i.get("_pos", 0))):
        while True:
            hit = next((q for q in placed if _overlap(it, q)), None)
            if hit is None:
                break
            it["y"] = hit["y"] + hit["h"]
        placed.append(it)
    for it in sorted(placed, key=lambda i: (i["y"], i["x"])):
        while it["y"] > 0:
            it["y"] -= 1
            if any(o is not it and _overlap(it, o) for o in placed):
                it["y"] += 1
                break
    return sorted(placed, key=lambda i: (i["y"], i["x"]))


def _from_columns(columns, sizes: dict) -> list[dict]:
    """옛 세 열 형식 → 격자: 열 i 의 위젯을 x = i 에 차례로 쌓는다(가로는 최소, 세로는 처음 크기). 열마다 sort_order 순(없거나 숫자가 아니면
    맨 뒤) → 원래 순서, 같은 index 가 또 나오면 뒤에 이어 붙인다. The older three-column shape → a grid: column i stacks at x = i
    (minimum width, default height), ordered by sort_order then position; a repeated index appends."""
    buckets: list[list[str]] = [[] for _ in range(COLUMN_COUNT)]
    for col in (columns if isinstance(columns, list) else []):
        if not isinstance(col, dict):
            continue
        idx = col.get("column_index")
        if isinstance(idx, bool) or not isinstance(idx, int) or not 0 <= idx < COLUMN_COUNT:
            continue
        picked = []
        for pos, item in enumerate(col.get("widgets") if isinstance(col.get("widgets"), list) else []):
            key = item.get("widget_key") if isinstance(item, dict) else None
            if isinstance(key, str) and key.strip():
                picked.append((_order_value(item.get("sort_order")), pos, key.strip()))
        picked.sort(key=lambda t: (t[0], t[1]))
        buckets[idx].extend(k for _, _, k in picked)
    out, seen, pos = [], set(), 0
    for i, keys in enumerate(buckets):
        y = 0
        for key in keys:
            if key in sizes and key not in seen:
                seen.add(key)
                size = sizes[key]
                out.append({"widget_key": key, "x": i, "y": y, "w": size["min_w"], "h": size["h"], "_pos": pos})
                y += size["h"]
                pos += 1
    return out


def normalize_config(raw, sizes: dict, strict: bool = False) -> dict:
    """배치 정규화(문서 4절). 출력은 늘 {layout_type, items: [{widget_key, x, y, w, h}]}(y · x 순, 겹침 없음, 위로 당김).
    sizes = {위젯 키: size_of(…)} — 여기 없는 키는 버린다. 새 형식(items)과 옛 세 열 형식(columns)을 다 읽는다.
    - 값은 조용히 맞춘다: 가로 · 세로는 그 위젯의 최소 · 최대(가로는 3칸까지), x 는 0 ~ 3 − 가로, y 는 0 이상, 같은 키는 처음 것만,
      잠근 위젯(날씨)이 없으면 맨 위에 넣는다. 그다음 겹침을 풀고 빈 곳을 당긴다(settle).
    - 저장(strict): layout_type 이 선택지가 아니면, items · columns 가 둘 다 없거나 items(또는 columns)가 목록이 아니면 ConfigError.
    Layout normalization (section 4). The output is always {layout_type, items} (sorted, overlap-free, pulled up). Keys not in
    sizes are dropped; both the new items shape and the older columns shape read. Values are fitted quietly (sizes within the
    widget's limits, x within the grid, y non-negative, a key once, the locked widget added at the top when missing), then
    overlaps are resolved (settle). A strict save raises ConfigError for an unknown layout_type or missing / non-list items
    (or columns)."""
    data = raw if isinstance(raw, dict) else {}
    layout = data.get("layout_type")
    layout = layout.strip() if isinstance(layout, str) else ""
    if layout not in LAYOUT_VALUES:
        if strict:
            raise ConfigError(f"지원하지 않는 레이아웃입니다: {layout[:20]}" if layout else "레이아웃을 골라 주세요")
        layout = DEFAULT_LAYOUT
    items_raw = data.get("items")
    if items_raw is not None or "columns" not in data or data.get("columns") is None:
        if not isinstance(items_raw, list):
            if strict:
                raise ConfigError("배치 형식이 올바르지 않습니다")
            items_raw = []
        picked: list[dict] = []
        for pos, it in enumerate(items_raw):
            if not isinstance(it, dict):
                continue
            key = it.get("widget_key")
            key = key.strip() if isinstance(key, str) else ""
            if key not in sizes or any(q["widget_key"] == key for q in picked):
                continue
            size = sizes[key]
            w = min(max(_int(it.get("w"), size["w"]), size["min_w"]), min(size["max_w"], GRID_COLS))
            h = min(max(_int(it.get("h"), size["h"]), size["min_h"]), size["max_h"])
            picked.append({"widget_key": key, "x": min(max(_int(it.get("x"), 0), 0), GRID_COLS - w),
                           "y": min(max(_int(it.get("y"), 0), 0), MAX_GRID_ROW), "w": w, "h": h, "_pos": pos})
    else:
        if strict and not isinstance(data.get("columns"), list):   # 옛 세 열 모양으로 저장할 때도 목록이어야 / the older shape must be a list too
            raise ConfigError("배치 형식이 올바르지 않습니다")
        picked = _from_columns(data.get("columns"), sizes)
    for b in BUILTIN:   # 잠근 위젯은 늘 홈에 / locked widgets always stay on the home
        if b["locked"] and b["key"] in sizes and all(q["widget_key"] != b["key"] for q in picked):
            size = sizes[b["key"]]
            picked.append({"widget_key": b["key"], "x": 0, "y": 0, "w": size["w"], "h": size["h"], "_pos": -1})
    items = settle(picked)
    return {"layout_type": layout, "items": [{k: it[k] for k in ("widget_key", "x", "y", "w", "h")} for it in items]}


def _read_saved(saved) -> dict:
    """저장된 줄 → 정규화 전 배치(새 형식은 {grid, items}, 옛 형식은 열 목록) / a saved row → the raw layout"""
    stored = _loads(saved["columns"], None)
    if isinstance(stored, dict) and "items" in stored:
        return {"layout_type": saved["layout_type"], "items": stored.get("items")}
    return {"layout_type": saved["layout_type"], "columns": stored}


def _store_value(config: dict) -> str:
    return _dumps({"grid": 1, "items": config["items"]})


def _sizes(conn, owner: str) -> dict:
    """아는 위젯의 크기 = 기본 9개 + 내 위젯(모델로 처음 크기) / sizes of the known widgets: the built-ins plus mine"""
    out = {k: size_of(k) for k in BUILTIN_KEYS}
    for r in conn.execute("SELECT id, model FROM home_widgets WHERE owner = ?", (owner,)):
        out[r["id"]] = size_of(r["id"], _loads(r["model"], {}))
    return out


def get_dashboard(owner: str) -> dict:
    """{layout_options, config, widgets}. config = 저장된 배치(읽기 정규화, 옛 세 열 형식도 격자로) + saved, 저장본이 없으면 처음 배치 +
    saved False. widgets = 기본 9개(BUILTIN 순서) + 내 위젯(created_at 오름차순, 정의 spec 은 빼고 모델만) — 위젯마다 size(처음 크기 ·
    최소 · 최대)를 싣는다. 배치에 없는 위젯이 안 쓰는 위젯(서랍)이다.
    {layout_options, config, widgets}. config = the saved layout (lenient; the older columns shape becomes a grid) plus saved,
    or the default plus saved False. widgets = the nine built-ins plus my widgets (the model without the spec), each with its
    size (default, minimum, maximum). A widget not placed is unused (in the drawer)."""
    owner = _own(owner)
    with db._conn() as conn:  # noqa: SLF001
        rows = conn.execute("SELECT * FROM home_widgets WHERE owner = ? ORDER BY created_at ASC, rowid ASC",
                            (owner,)).fetchall()
        saved = conn.execute("SELECT layout_type, columns FROM home_dash_config WHERE owner = ?", (owner,)).fetchone()
    # 홈은 모델만 그린다: 정의(spec, 표 전체가 들어 있다)는 싣지 않는다(GET /api/home/widgets 가 준다)
    # the home only draws models, so the definition (spec, which holds the whole table) is left out (GET /api/home/widgets has it)
    mine = [{**{k: v for k, v in _row_to_widget(r).items() if k != "spec"}, "size": size_of(r["id"], _loads(r["model"], {}))} for r in rows]
    sizes = {**{k: size_of(k) for k in BUILTIN_KEYS}, **{w["key"]: w["size"] for w in mine}}
    if saved is None:
        config = {**normalize_config(default_config(), sizes), "saved": False}
    else:
        config = {**normalize_config(_read_saved(saved), sizes), "saved": True}
    return {"layout_options": [{"value": o["value"], "ratios": list(o["ratios"])} for o in LAYOUT_OPTIONS],
            "config": config,
            "widgets": [{"key": b["key"], "kind": "builtin", "name": b["name"], "locked": b["locked"], "size": size_of(b["key"])} for b in BUILTIN]
            + mine}


def save_dashboard(owner: str, raw: dict) -> dict:
    """엄격 정규화(형식 · 레이아웃이 틀리면 ConfigError, 모르는 키는 버리고 값은 맞춘다) → 저장(격자 형식) → config(+ saved True).
    Strict normalization (wrong shape or layout raises ConfigError; unknown keys dropped, values fitted), then save in the grid
    shape; returns the config plus saved True."""
    owner = _own(owner)
    with db._conn() as conn:  # noqa: SLF001
        conn.execute("BEGIN IMMEDIATE")   # 아는 키 읽기와 저장을 한 번에 / read the known keys and write in one go
        config = normalize_config(raw, _sizes(conn, owner), strict=True)
        conn.execute("INSERT OR REPLACE INTO home_dash_config(owner, layout_type, columns, updated_at) VALUES(?, ?, ?, ?)",
                     (owner, config["layout_type"], _store_value(config), kst.now_iso()))
    return {**config, "saved": True}


# ────────────────────────────────────────────────────────
# 위젯 정의 v2 / widget definition v2 (문서 6절 / section 6)
# ────────────────────────────────────────────────────────
# 만든 위젯 하나 = 리포트 에이전트 대시보드의 작은 판(데이터 0~1 · 차트 0~1 · KPI 카드 0~4). 차트 · KPI 카드는 리포트 에이전트와
# 같은 모양(report_dash.norm_chart · norm_kpi)이라 그쪽 도구 · 계산을 그대로 쓴다. 데이터를 아직 정하지 않은 KPI 카드
# (pending, '데이터 연결 전')는 이 위젯만의 모양이다.
# One made widget = a small board of the report agent (data 0..1, chart 0..1, KPI cards 0..4). Charts and KPI cards have the
# report agent's shape (report_dash.norm_chart / norm_kpi), so its tools and math apply as they are. A KPI card whose data is
# not decided yet (pending, 'not connected yet') is this widget's own shape.

def _opt_str(value, type_msg: str) -> str | None:
    """None 이나 빈 글자 → None, 글자 → 앞뒤 공백을 뺀 값, 그 밖의 형식 → SpecError.
    None or blank → None, text → stripped, any other type → SpecError."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise SpecError(type_msg)
    return value.strip() or None


def _txt(value, n: int) -> str:
    """선택 글자 항목: 글자가 아니면 빈 값, 앞뒤 공백을 빼고 n 자까지 / an optional text field: '' unless text, stripped, n characters"""
    return value.strip()[:n] if isinstance(value, str) else ""


def _next_id(prefix: str, used: set[str]) -> str:
    n = 1
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


def _cell(value):
    """칸 정리: 글자 · 숫자 · None 만 받는다. bool · 목록 · 객체는 SpecError, 글자는 MAX_CELL 자까지, 유한하지 않은 실수는
    None, float 로 못 바꾸는 큰 정수는 글자.
    Cell cleanup: only text, numbers and None are accepted. Bools, lists and objects raise SpecError, text is capped at
    MAX_CELL characters, non-finite floats become None and integers too large for a float become text."""
    if value is None:
        return None
    if isinstance(value, str):
        if len(value) > MAX_CELL:
            raise SpecError(f"칸 하나에는 {MAX_CELL}자까지 넣을 수 있습니다")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpecError("칸에는 글자 · 숫자 · 빈 값만 넣을 수 있습니다")
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    try:
        float(value)
    except OverflowError:
        try:
            text = str(value)
        except ValueError:   # 자릿수가 너무 많은 정수 / an integer with too many digits
            text = ""
        if not text or len(text) > MAX_CELL:
            raise SpecError(f"칸 하나에는 {MAX_CELL}자까지 넣을 수 있습니다") from None
        return text
    return value


def _norm_source(src) -> dict | None:
    """데이터: 없으면 None. inline 표만 받는다 — 열 1~12개(겹치지 않는 이름, 40자 이하), 행 200줄까지, 각 행은 열 수에 맞춰 자르거나
    None 으로 채운다. 데이터를 가져오는 도구(날씨 · 그룹웨어 …)는 다음 단계라 다른 tool 은 아직 거절한다.
    Data: None when absent. Only an inline table: 1 to 12 uniquely named columns (40 characters at most), up to 200 rows,
    each row cut or padded with None to the column count. Fetching tools (weather, groupware, …) come later, so any other
    tool is refused for now."""
    if src is None:
        return None
    if not isinstance(src, dict):
        raise SpecError("데이터 형식이 올바르지 않습니다")
    tool = src.get("tool")
    tool = tool.strip() if isinstance(tool, str) else ""
    if tool != "inline":
        raise SpecError(f"지원하지 않는 데이터 출처입니다: {tool[:40]}" if tool else "지원하지 않는 데이터 출처입니다")
    raw_cols = src.get("columns")
    if not isinstance(raw_cols, list) or not 1 <= len(raw_cols) <= MAX_COLUMNS:
        raise SpecError(f"데이터 열은 1~{MAX_COLUMNS}개여야 합니다")
    columns: list[str] = []
    for c in raw_cols:
        if not isinstance(c, str) or not c.strip():
            raise SpecError("열 이름은 비어 있지 않은 글자여야 합니다")
        name = c.strip()
        if len(name) > MAX_COLUMN_NAME:
            raise SpecError(f"열 이름은 {MAX_COLUMN_NAME}자까지 쓸 수 있습니다")
        if name in columns:
            raise SpecError(f"열 이름이 겹칩니다: {name}")
        columns.append(name)
    raw_rows = src.get("rows")
    if raw_rows is None:
        raw_rows = []
    if not isinstance(raw_rows, list):
        raise SpecError("데이터 행은 목록이어야 합니다")
    if len(raw_rows) > MAX_ROWS:
        raise SpecError(f"데이터는 {MAX_ROWS}줄까지 넣을 수 있습니다")
    rows = []
    width = len(columns)
    for r in raw_rows:
        if not isinstance(r, (list, tuple)):
            raise SpecError("각 데이터 행은 칸의 목록이어야 합니다")
        cells = [_cell(v) for v in list(r)[:width]]
        rows.append(cells + [None] * (width - len(cells)))
    return {"tool": "inline", "columns": columns, "rows": rows}


def _rd_source(source: dict) -> dict:
    """위젯의 데이터 → 리포트 에이전트의 Source(s1). 컬럼 종류 · 기간 컬럼을 리포트 에이전트와 같은 규칙으로 읽는다.
    The widget's data → a report-agent source (s1); column kinds and period columns follow the report agent's rules."""
    return rd.norm_source({"id": SOURCE_ID, "columns": source["columns"], "rows": source["rows"],
                           "origin": {"kind": "agent", "note": "inline"}}, set())


_HANGUL = re.compile(r"[가-힣]")


def _sentence(exc: Exception, fallback: str) -> str:
    """정규화 실패 문장: 리포트 에이전트가 낸 한국어 문장은 그대로, 파이썬의 영어 오류(NaN · 형식)는 우리 문장으로.
    A normalization failure sentence: the report agent's Korean sentence as is, Python's English errors (NaN, types) as ours."""
    text = str(exc)
    return text if isinstance(exc, ValueError) and _HANGUL.search(text) else fallback


def _norm_chart(raw, src: dict, title: str) -> dict:
    """차트 = 리포트 에이전트의 차트 설정(report_dash.norm_chart, 저장분 규칙). id · 데이터 · 제목(= 위젯 제목)은 위젯이 정하고,
    위젯에서 쓰지 않는 드릴다운 · 메모 · 비교 묶음은 뺀다.
    The chart = a report-agent chart spec (report_dash.norm_chart, saved-data rules). The widget fixes its id, data and title
    (= the widget title) and drops drill-down, notes and compare groups, which widgets do not use."""
    if not isinstance(raw, dict):
        raise SpecError("차트 설정 형식이 올바르지 않습니다")
    data = {k: v for k, v in raw.items() if k not in _CHART_DROP}
    data.update({"id": CHART_ID, "source": SOURCE_ID, "title": title, "subtitle": "", "size": "full", "insight": ""})
    try:
        chart = rd.norm_chart(data, {SOURCE_ID: src}, set())
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError) as exc:
        # 형식이 틀린 항목(filters: 5 · limit: Infinity …)도 사용자 문장으로 / mis-shaped fields (filters: 5, limit: Infinity, …) become a user sentence too
        raise SpecError(_sentence(exc, "차트 설정 형식이 올바르지 않습니다")) from None
    for k in _CHART_DROP:
        chart.pop(k, None)
    return chart


def _norm_pending(raw: dict, used: set[str]) -> dict:
    """데이터 연결 전 KPI 카드: 이름(필수) · 단위 · 설명만 있고 숫자가 없다. 리포트 에이전트의 KPI 키를 모두 빈 값으로 갖는다.
    A KPI card whose data is not connected yet: a name (required), a unit and a note, no number. It carries every report-agent
    KPI key, empty."""
    label = _opt_str(raw.get("label"), "KPI 카드 이름은 글자여야 합니다")
    if label is None:
        raise SpecError("KPI 카드 이름을 적어 주세요")
    if len(label) > MAX_KPI_LABEL:
        raise SpecError(f"KPI 카드 이름은 {MAX_KPI_LABEL}자까지 쓸 수 있습니다")
    kid = raw.get("id") if isinstance(raw.get("id"), str) else ""
    if not re.fullmatch(r"k\d{1,3}", kid) or kid in used:
        kid = _next_id("k", used)
    used.add(kid)
    return {"id": kid, "source": "", "col": "", "agg": "", "label": label, "unit": _txt(raw.get("unit"), 8), "link": "",
            "delta": "", "value": None, "note": _txt(raw.get("note"), rd.MAX_KPI_NOTE), "pending": True}


def _url(value) -> str:
    u = _txt(value, 500)
    return u if u.lower().startswith(("http://", "https://")) and len(u) > 8 else ""


def _norm_card_keys(raw) -> list[dict]:
    """가져온 카드 [{id, key}]: id = KPI 카드 id, key = 가져올 때의 이름(다시 가져올 때 이 이름으로 숫자를 찾는다 — 순서로 짝짓지 않는다)
    fetched cards [{id, key}]: the card id and the name it was fetched under (refreshes match numbers by this name, never by position)"""
    out: list[dict] = []
    for c in (raw if isinstance(raw, list) else []):
        cid, key = (c.get("id"), c.get("key")) if isinstance(c, dict) else (c, "")
        if isinstance(cid, str) and re.fullmatch(r"k\d{1,3}", cid) and all(x["id"] != cid for x in out):
            out.append({"id": cid, "key": _txt(key, MAX_KPI_LABEL)})
    return out[:MAX_KPIS]


def _norm_one_origin(raw) -> dict:
    if not isinstance(raw, dict) or raw.get("kind") not in ORIGIN_KINDS:
        raise SpecError("내용의 출처 형식이 올바르지 않습니다")
    kind = raw["kind"]
    view = raw.get("view") if raw.get("view") in VIEWS else ""
    part = raw.get("part")
    if part not in PARTS:   # 부분이 없는 옛 꼴 / an older shape without a part
        part = "cards" if raw.get("cards") else {"list": "list", "text": "text"}.get(view, "source")
    if kind == "data":
        part = "source"     # 사내 데이터는 표만 / company data is always a table
    refs = []
    for r in (raw.get("refs") if isinstance(raw.get("refs"), list) else []):
        if len(refs) >= MAX_REFS:
            break
        if isinstance(r, dict) and r.get("kind") in REF_KINDS and _txt(r.get("label"), 120):
            page = r.get("page")
            refs.append({"kind": r["kind"], "label": _txt(r.get("label"), 120), "url": _url(r.get("url")),
                         "page": page if isinstance(page, int) and not isinstance(page, bool) and 0 < page < 100000 else None})
    sql = raw.get("sql") if kind == "data" and isinstance(raw.get("sql"), str) else ""
    sql = sql.strip() if len(sql.strip()) <= MAX_SQL else ""
    sig = _txt(raw.get("sig"), 64) if sql else ""
    tables = raw.get("tables") if sql and isinstance(raw.get("tables"), list) else []
    return {"part": part, "kind": kind, "query": _txt(raw.get("query"), 300), "view": view, "sql": sql, "sig": sig,
            "tables": [_txt(t, 80) for t in tables if _txt(t, 80)][:12], "refs": refs, "fetched_at": _txt(raw.get("fetched_at"), 40),
            "cards": _norm_card_keys(raw.get("cards")) if part == "cards" else []}


def _norm_origins(raw) -> list[dict]:
    """내용의 출처들(파이프라인이 적는다, 위젯의 부분마다 하나): 표 · 글 · 목록은 하나씩, 고정 숫자 카드는 가져온 요청마다(카드는 한 출처에만).
    없으면 [](사용자가 준 숫자 · 표). The origins (written by the pipeline, one per part): one each for the table, text and list,
    and one per fetch for fixed cards (each card belongs to one origin only). [] for content the user gave."""
    if raw is None:
        return []
    items = [raw] if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise SpecError("내용의 출처 형식이 올바르지 않습니다")
    out: list[dict] = []
    owned: set[str] = set()
    for item in items:
        o = _norm_one_origin(item)
        if o["part"] != "cards" and any(x["part"] == o["part"] for x in out):
            continue   # 표 · 글 · 목록은 하나씩(앞의 것) / one table, text and list (the first)
        if o["part"] == "cards":
            o["cards"] = [c for c in o["cards"] if c["id"] not in owned]
            if not o["cards"]:
                continue
            owned.update(c["id"] for c in o["cards"])
        out.append(o)
    return out[:MAX_ORIGINS]


def refreshable(o: dict) -> bool:
    """다시 가져올 수 있는 출처인가: 질의가 있고, 사내 데이터면 서명된 SQL 이 있다 / can this origin be fetched again"""
    return bool(o.get("kind") in ORIGIN_KINDS and o.get("query") and (o.get("kind") != "data" or o.get("sql")))


def _norm_blocks(raw) -> list[dict]:
    """숫자가 아닌 내용: 글 하나 · 목록 하나까지. 글 600자, 목록 8건(제목 120 · 한 줄 160 · 주소는 http(s) 만).
    Non-numeric content: at most one text and one list; text 600 characters, lists 8 items (title 120, line 160, http(s) links only)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SpecError("위젯 내용 형식이 올바르지 않습니다")
    out: list[dict] = []
    for b in raw:
        if not isinstance(b, dict) or b.get("type") not in ("text", "list"):
            raise SpecError("위젯 내용 형식이 올바르지 않습니다")
        if any(x["type"] == b["type"] for x in out):
            continue
        if b["type"] == "text":
            text = _txt(b.get("text"), MAX_BLOCK_TEXT)
            if text:
                out.append({"type": "text", "text": text})
            continue
        items = [{"title": _txt(it.get("title"), 120), "sub": _txt(it.get("sub"), 160), "url": _url(it.get("url"))}
                 for it in (b.get("items") if isinstance(b.get("items"), list) else []) if isinstance(it, dict) and _txt(it.get("title"), 120)]
        if items:
            out.append({"type": "list", "items": items[:MAX_BLOCK_ITEMS]})
    return out


def _norm_kpis(raw, sources: dict, charts: list[dict]) -> list[dict]:
    """KPI 카드 0~4개: 데이터 연결 전 카드(pending) 또는 리포트 에이전트의 KPI 카드(고정 숫자 · 데이터 계산). 이름은 겹치지 않는다.
    Zero to four KPI cards: not-connected cards (pending) or report-agent KPI cards (fixed number or computed). Names are unique."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SpecError("KPI 카드 설정 형식이 올바르지 않습니다")
    if len(raw) > MAX_KPIS:
        raise SpecError(f"위젯에는 KPI 카드를 {MAX_KPIS}개까지 넣을 수 있습니다")
    out: list[dict] = []
    used: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise SpecError("KPI 카드 설정 형식이 올바르지 않습니다")
        if item.get("pending") is True:
            kpi = _norm_pending(item, used)
        else:
            try:
                kpi = rd.norm_kpi(item, sources, charts, used, strict=True)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError) as exc:
                raise SpecError(_sentence(exc, "KPI 카드 설정 형식이 올바르지 않습니다")) from None
        if any(k["label"] == kpi["label"] for k in out):
            raise SpecError(f"같은 이름의 KPI 카드가 있습니다: {kpi['label']}")
        out.append(kpi)
    return out


def _norm_size(raw) -> dict | None:
    """만든 위젯의 처음 크기 {w, h}(칸, 2026-11-19 위젯 에이전트의 실제 크기 미리보기에서 고른 것) — 위젯 추가 서랍에서 홈에 놓을 때 이 크기로
    놓인다. 없으면 None(차트면 1 × 2, 아니면 1 × 1). 값은 가로 1~3 · 세로 1~3 으로 맞추고, 숫자가 아니면 SpecError.
    The made widget's first size {w, h} in cells (picked in the widget agent's real-size preview, 2026-11-19): placing it from the
    Add widget drawer uses this size. None when unset. Values fit 1..3 by 1..3; non-numbers raise SpecError."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SpecError("위젯 크기 형식이 올바르지 않습니다")
    a, b, c, d = CUSTOM_LIMITS
    out = {}
    for k, lo, hi in (("w", a, b), ("h", c, d)):
        v = raw.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise SpecError("위젯 크기 형식이 올바르지 않습니다")
        out[k] = min(max(_int(v, lo), lo), hi)
    return out


def normalize_spec(raw, draft: bool = False) -> dict:
    """정의 정규화. 출력: {v: 2, title, source(inline 표 | None), chart(리포트 에이전트 차트 | None), kpis, theme(| None), insight}.
    값이 명시됐는데 틀리면 SpecError. draft(위젯 에이전트의 작업본)는 제목이 없으면 '새 위젯'이고 내용이 비어도 되며, 저장(draft 아님)은
    차트나 KPI 카드가 하나는 있어야 한다. 같은 결과를 다시 넣어도 같은 결과가 나온다(멱등).
    Definition normalization. Output: {v: 2, title, source (inline table | None), chart (a report-agent chart | None), kpis,
    theme (| None), insight}. An explicit but wrong value raises SpecError. A draft (the widget agent's working copy) gets
    '새 위젯' without a title and may be empty; a save (not a draft) needs a chart or a KPI card. Idempotent."""
    if not isinstance(raw, dict):
        raise SpecError("위젯 정의 형식이 올바르지 않습니다")
    version = raw.get("v")
    if version is not None and version != SPEC_VERSION:
        raise SpecError("지원하지 않는 위젯 정의입니다. 위젯 에이전트에서 다시 만들어 주세요")
    title = _opt_str(raw.get("title"), "위젯 제목은 글자여야 합니다")
    if title is None:
        if not draft:
            raise SpecError("위젯 제목을 입력해 주세요")
        title = NEW_TITLE
    if len(title) > MAX_TITLE:
        raise SpecError(f"위젯 제목은 {MAX_TITLE}자까지 쓸 수 있습니다")
    source = _norm_source(raw.get("source"))
    sources = {SOURCE_ID: _rd_source(source)} if source else {}
    chart = None
    if raw.get("chart") is not None:
        if not sources:
            raise SpecError("차트에는 데이터가 필요합니다")
        chart = _norm_chart(raw["chart"], sources[SOURCE_ID], title)
    kpis = _norm_kpis(raw.get("kpis"), sources, [chart] if chart else [])
    theme = rd.norm_theme(raw.get("theme"))   # 대표 색이 없는 테마는 없는 것으로 / a theme without a brand colour reads as none
    insight = _opt_str(raw.get("insight"), "인사이트는 글자여야 합니다") or ""
    if len(insight) > MAX_INSIGHT:
        raise SpecError(f"인사이트는 {MAX_INSIGHT}자까지 쓸 수 있습니다")
    blocks = _norm_blocks(raw.get("blocks"))
    origins = _norm_origins(raw.get("origins") if "origins" in raw else raw.get("origin"))
    kpi_ids = {k["id"] for k in kpis}
    for o in origins:   # 없어진 카드는 출처에서도 뺀다 / cards that are gone leave their origin too
        if o["part"] == "cards":
            o["cards"] = [c for c in o["cards"] if c["id"] in kpi_ids]
    origins = [o for o in origins if o["part"] != "cards" or o["cards"]]
    if not draft and chart is None and not kpis and not blocks:
        raise SpecError("위젯에 보여 줄 내용이 없습니다. 위젯 에이전트로 차트나 KPI 카드를 먼저 만들어 주세요")
    clean = {"v": SPEC_VERSION, "title": title, "source": source, "chart": chart, "kpis": kpis, "theme": theme,
             "insight": insight, "blocks": blocks, "origins": origins}
    size = _norm_size(raw.get("size"))
    if size:   # 고른 크기가 있을 때만 싣는다(없던 정의는 그대로) / carried only when picked (older definitions stay as they were)
        clean["size"] = size
    if len(_dumps(clean)) > MAX_SPEC_CHARS:   # 표 전체가 정의에 들어가므로 크기에 상한을 둔다 / the whole table lives in the definition
        raise SpecError("위젯에 넣은 데이터가 너무 큽니다. 줄 수나 글자 수를 줄여 주세요")
    return clean


def to_state(clean: dict) -> dict:
    """정규화된 정의 → 리포트 에이전트의 대시보드 상태(Source 0~1 · 차트 0~1 · KPI 카드 · 테마). 리포트 에이전트의 도구가 이 상태를
    고치고, 계산(report_dash.compute · kpi_value)도 이 상태로 한다. 고쳐도 정의는 바뀌지 않는다(사본).
    A normalized definition → a report-agent dashboard state (0..1 source, 0..1 chart, KPI cards, theme). The report agent's
    tools edit this state and the math (report_dash.compute / kpi_value) runs on it. It is a copy: editing it leaves the
    definition alone."""
    state = {"v": 2, "title": clean["title"],
             "sources": [_rd_source(clean["source"])] if clean["source"] else [],
             "charts": [json.loads(json.dumps(clean["chart"]))] if clean["chart"] else [],
             "kpis": [dict(k) for k in clean["kpis"]]}
    if clean["theme"]:
        state["theme"] = dict(clean["theme"])
    return state


def from_state(state: dict, clean: dict, insight: str | None = None, extra: dict | None = None) -> dict:
    """도구가 고친 상태 → 정의(작업본 규칙으로 다시 정규화). 데이터 · 글/목록 칸 · 출처들은 원래 정의의 것을 쓰고, 데이터 도구가
    바꿨으면 extra({source, blocks, origins} 중 바뀐 것)로 덮는다.
    A tool-edited state → a definition (normalized again as a draft). Data, blocks and origins come from the original definition
    unless the data tool changed them, in which case extra ({source, blocks, origins}) overrides them."""
    charts = state.get("charts") or []
    extra = extra or {}
    return normalize_spec({"v": SPEC_VERSION, "title": state.get("title"), "source": extra.get("source", clean["source"]),
                           "chart": charts[0] if charts else None, "kpis": state.get("kpis") or [],
                           "theme": state.get("theme"), "insight": clean["insight"] if insight is None else insight,
                           "blocks": extra.get("blocks", clean["blocks"]), "origins": extra.get("origins", clean["origins"]),
                           "size": clean.get("size")},   # 고른 크기는 도구가 바꾸지 않는다 / tools never change the picked size
                          draft=True)


# ────────────────────────────────────────────────────────
# 인사이트 = 데이터가 바뀌면 같이 바뀌는 문장 / insights that change with the data (문서 7절 / section 7)
# ────────────────────────────────────────────────────────
# 저장하는 것은 문장이 아니라 틀이다: 숫자와 항목 이름은 {변수}로 두고 그릴 때마다 지금 데이터의 값을 넣는다. 바로 뒤의
# 조사(이/가 · 은/는 · 을/를 · 과/와 · 으로/로)는 들어간 값의 끝소리에 맞춘다.
# What is stored is a template, not a sentence: numbers and item names stay {variables} filled from the current data each
# time it is drawn, and a particle right after one (이/가, 은/는, 을/를, 과/와, 으로/로) follows the final sound of the value.

_VAR = re.compile(r"\{([^{}\s]{1,20})\}")
_PAIRS = (("이가", ("이(가)", "가(이)", "(이)가", "이", "가")), ("은는", ("은(는)", "는(은)", "(은)는", "은", "는")),
          ("을를", ("을(를)", "를(을)", "(을)를", "을", "를")), ("과와", ("과(와)", "와(과)", "(과)와", "과", "와")),
          ("으로", ("(으)로", "으로", "로")))
_PAIR = {tail: pair for pair, tails in _PAIRS for tail in tails}
# 조사는 변수 바로 뒤에 붙고 그 뒤가 띄어쓰기 · 문장 부호 · 끝일 때만 고친다("{최고}가장"의 '가'는 조사가 아니다)
# a particle is fixed only right after a variable and before a space, punctuation or the end (the '가' of "{최고}가장" is no particle)
_SLOT = re.compile(r"\{([^{}\s]{1,20})\}(?:(" + "|".join(re.escape(t) for t in sorted(_PAIR, key=len, reverse=True))
                   + r")(?=[\s.,!?·…:;~)\]」』\"']|$))?")
_DIGIT_FINAL = {"0": "o", "1": "l", "2": "", "3": "o", "4": "", "5": "", "6": "o", "7": "l", "8": "l", "9": ""}
_DIGIT = re.compile(r"\d")
# 증감 = 낱말(앞뒤 말과 이어 쓴다: "{증감}했습니다" → "증가했습니다") — 문장 끝까지 넣으면 모델이 "늘었습니다했습니다"처럼 덧붙였다(2026-11-16 실측)
# the direction is a word to build on ("{증감}했습니다" → "증가했습니다"); a whole verb made the model write "늘었습니다했습니다" (seen 2026-11-16)
INSIGHT_WORDS = {"up": "증가", "down": "감소", "same": "보합"}


def _final(text: str) -> str:
    """값의 끝소리: '' = 받침 없음, 'l' = ㄹ 받침, 'o' = 그 밖의 받침. 숫자는 한국어로 읽은 소리(0 은 십 · 백 · 천 · 만 · 영 모두 받침),
    %는 '퍼센트', 영어 l 은 ㄹ, m · n 은 받침으로 본다. 끝의 닫는 부호는 건너뛴다.
    The final sound of a value: '' none, 'l' ㄹ, 'o' another final consonant. Digits read as Korean (0 ends in a consonant for
    ten, hundred, thousand, ten thousand and zero), % reads 'percent', Latin l is ㄹ and m or n a final consonant; trailing
    closing marks are skipped."""
    t = (text or "").rstrip()
    while t and t[-1] in ")]}'\"」』.,…":
        t = t[:-1].rstrip()
    if not t:
        return ""
    ch = t[-1]
    code = ord(ch) - 0xAC00
    if 0 <= code < 11172:
        jong = code % 28
        return "" if jong == 0 else ("l" if jong == 8 else "o")
    if ch in _DIGIT_FINAL:
        return _DIGIT_FINAL[ch]
    low = ch.lower()
    if low == "l":
        return "l"
    return "o" if low in ("m", "n") else ""


def _josa(pair: str, final: str) -> str:
    if pair == "으로":   # ㄹ 받침과 받침 없음은 '로' / '로' after ㄹ or no final consonant
        return "로" if final in ("", "l") else "으로"
    return pair[0] if final else pair[1]


def render_insight(template: str, values: dict) -> tuple[str, bool]:
    """인사이트 틀 → (문장, 기다림). {변수}를 지금 값으로 바꾸고 바로 뒤 조사를 값에 맞춘다. 값이 없는 변수가 하나라도 있으면
    ('', True) — 깨진 문장 대신 숨기고, 값이 생기면 다시 보인다.
    An insight template → (sentence, waiting). {variables} take their current values and a following particle is fixed to the
    value. Any variable without a value gives ('', True): hidden instead of broken, shown again once the value exists."""
    missing = False

    def put(m: re.Match) -> str:
        nonlocal missing
        value = values.get(m.group(1))
        if value is None:
            missing = True
            return m.group(0)
        tail = m.group(2)
        return value + (_josa(_PAIR[tail], _final(value)) if tail else "")

    text = _SLOT.sub(put, template or "")
    return ("", True) if missing else (text, False)


def fill_values(text: str, values: dict) -> str:
    """글 속의 {변수}를 지금 값으로 바꾼다(바로 뒤 조사 포함) — 위젯 에이전트의 답에 변수가 섞여 나왔을 때 쓴다. 값이 없는 변수는 괄호만 뗀다.
    Fills the {variables} in a text with their current values (a following particle included), for when the widget agent's reply leaks
    variables; a variable without a value just loses its braces."""
    def put(m: re.Match) -> str:
        value = values.get(m.group(1))
        if value is None:
            return m.group(1) + (m.group(2) or "")
        tail = m.group(2)
        return value + (_josa(_PAIR[tail], _final(value)) if tail else "")

    return _SLOT.sub(put, text or "")


def insight_values(state: dict, comp: dict | None) -> dict[str, str]:
    """인사이트 변수의 지금 값(글자). 차트(첫 계열, 보이는 항목) = 최고 · 최고값 · 최저 · 최저값 · 평균 · 개수 · 처음 · 처음값 · 마지막 ·
    마지막값, 더할 수 있는 값이면 합계, x 가 기간이면 직전대비(%) · 증감(증가 · 감소 · 보합) — 기간 축의 처음 · 마지막은
    날짜 순이다. 숫자 카드 차트는 값. KPI 카드는 숫자가 있는 카드마다 그 id(k1 …).
    Current values (text) of the insight variables. The chart (first series, shown items): highest, lowest, average, count,
    first and last items with values; a total when the values add up; on a period axis the change from the previous period
    (%) and its direction (first and last follow time order there). A number-card chart gives 값. KPI cards give their id
    (k1 …) when they have a number."""
    out: dict[str, str] = {}
    charts = state.get("charts") or []
    chart = charts[0] if charts else None
    if chart is not None and comp and comp.get("series"):
        s = comp["series"][0]
        unit = s.get("unit") or chart.get("unit") or ""
        pairs = [(comp["x"][i], v) for i, v in enumerate(s["values"]) if v is not None and i < len(comp["x"])]
        if chart["type"] == "kpi":
            if pairs:
                out["값"] = rd.fmt(pairs[0][1], unit)
        elif pairs:
            pkind = (state["sources"][0].get("periods") or {}).get(chart.get("x")) if state.get("sources") else None
            order = sorted(pairs, key=lambda p: rd.period_key(p[0], pkind) or (0, 0)) if pkind else pairs
            hi, lo = max(pairs, key=lambda p: p[1]), min(pairs, key=lambda p: p[1])
            total = rd._round(sum(v for _, v in pairs))  # noqa: SLF001  리포트 에이전트와 같은 반올림 / the report agent's rounding
            out.update({"최고": hi[0], "최고값": rd.fmt(hi[1], unit), "최저": lo[0], "최저값": rd.fmt(lo[1], unit),
                        "평균": rd.fmt(rd._round(total / len(pairs)), unit), "개수": str(len(pairs)),  # noqa: SLF001
                        "처음": order[0][0], "처음값": rd.fmt(order[0][1], unit),
                        "마지막": order[-1][0], "마지막값": rd.fmt(order[-1][1], unit)})
            y0 = chart["y"][0]
            if y0["agg"] in ("sum", "count") and not y0.get("calc") and unit != "%" and not chart.get("group"):
                out["합계"] = rd.fmt(total, unit)
            if pkind and len(order) >= 2:
                prev, last = order[-2][1], order[-1][1]
                if prev:
                    out["직전대비"] = rd.fmt(abs(round((last - prev) / abs(prev) * 100, 1)), "%")
                out["증감"] = INSIGHT_WORDS["up" if last > prev else ("down" if last < prev else "same")]
    for k in state.get("kpis") or []:
        if k.get("pending"):
            continue
        value = rd.kpi_value(k, state).get("value")
        if value is not None:
            out[k["id"]] = rd.fmt(value, k.get("unit") or "")
    return out


def _item_labels(state: dict) -> list[str]:
    """차트 x 컬럼의 항목 이름(두 글자 이상, '기타' 제외) — 인사이트에 그대로 쓰면 데이터가 바뀔 때 틀린다.
    Item names of the chart's x column (two characters or more, '기타' aside): written literally into an insight they go
    wrong when the data changes."""
    charts, sources = state.get("charts") or [], state.get("sources") or []
    if not charts or not sources or not charts[0].get("x"):
        return []
    src = sources[0]
    ci = src["columns"].index(charts[0]["x"])
    labels = {rd.key(r[ci]).strip() for r in src["rows"]}
    return sorted((x for x in labels if len(x) >= 2 and x != rd.OTHERS_LABEL), key=len, reverse=True)


def check_insight(text, state: dict, comp: dict | None) -> str:
    """도구가 쓰는 인사이트 틀 검사(엄격, ValueError = LLM 과 화면에 그대로 갈 문장). 빈 글자 = 지우기. 변수가 하나 이상 있고 모두
    지금 쓸 수 있어야 하며, 숫자와 항목 이름을 글자로 쓰면 거절한다(데이터가 바뀌면 틀리므로).
    Checks an insight template from a tool (strict; the ValueError sentence goes to the LLM and the screen). Blank clears it.
    It needs at least one variable, all usable now; literal digits and item names are refused (they go wrong when the data
    changes)."""
    text = str(text if text is not None else "").strip()
    if not text:
        return ""
    if len(text) > MAX_INSIGHT:
        raise ValueError(f"인사이트는 {MAX_INSIGHT}자까지 쓸 수 있습니다")
    values = insight_values(state, comp)
    if not values:
        raise ValueError("인사이트에 쓸 값이 없습니다. 차트나 숫자가 있는 KPI 카드가 있어야 합니다")
    listed = "쓸 수 있는 변수: " + ", ".join("{" + k + "}" for k in values)
    names = [m.group(1) for m in _VAR.finditer(text)]
    if not names:
        raise ValueError("인사이트에는 데이터 값 변수를 하나 이상 넣어 주세요(데이터가 바뀌면 같이 바뀌게). " + listed)
    unknown = [n for n in dict.fromkeys(names) if n not in values]
    if unknown:
        raise ValueError("쓸 수 없는 변수입니다: " + ", ".join("{" + n + "}" for n in unknown) + ". " + listed)
    bare = _VAR.sub(" ", text)
    if _DIGIT.search(bare):
        raise ValueError("숫자는 직접 쓰지 말고 변수로 써 주세요(데이터가 바뀌면 같이 바뀌게). " + listed)
    for label in _item_labels(state):
        if label in bare:
            raise ValueError(f"'{label}' 같은 항목 이름은 데이터가 바뀌면 달라집니다. 변수로 써 주세요. " + listed)
    return text


# ────────────────────────────────────────────────────────
# 표시 모델 / display model (문서 7절 / section 7)
# ────────────────────────────────────────────────────────

def _filter_text(f: dict) -> str:
    """필터 조건 글 — 리포트 에이전트와 같은 표기 / filter condition text, as the report agent writes it"""
    r = f.get("range") or {}
    if r.get("last"):
        return f"최근 {r['last']}개"
    if "from" in r:
        return f"{r.get('from') or '처음'}~{r.get('to') or '끝'}"
    if "min" in r:
        return f"{'' if r.get('min') is None else rd.fmt(r['min'])}~{'' if r.get('max') is None else rd.fmt(r['max'])}"
    return ", ".join(f["selected"]) if f.get("selected") else "전체"


def _chart_model(chart: dict, comp: dict) -> dict:
    """차트 모델: 화면은 config(리포트 에이전트 차트 설정)와 data(계산 값)를 리포트 에이전트의 그리기(rdChartConfig)에 그대로 넘긴다.
    The chart model: the screen hands config (the report-agent chart spec) and data (the computed values) to the report
    agent's drawing (rdChartConfig) as they are."""
    active = [f for f in chart.get("filters") or [] if f.get("selected") or f.get("range")]
    out = {"type": chart["type"], "config": chart, "data": comp,
           "empty": not comp["x"] or not any(v is not None for s in comp["series"] for v in s["values"]),
           "filters": [f"{f['label']}: {_filter_text(f)}" for f in active]}
    if chart["type"] == "kpi":
        series = comp["series"][0] if comp["series"] else {"name": "", "values": []}
        value = series["values"][0] if series["values"] else None
        out.update({"text": rd.fmt(value, chart.get("unit") or "") if value is not None else "", "label": series["name"]})
    return out


def _kpi_model(kpi: dict, state: dict) -> dict:
    base = {"id": kpi["id"], "label": kpi["label"], "unit": kpi.get("unit") or "", "note": kpi.get("note") or ""}
    if kpi.get("pending"):
        return {**base, "pending": True, "text": "", "manual": False, "delta": None, "period": ""}
    v = rd.kpi_value(kpi, state)
    value = v.get("value")
    return {**base, "pending": False, "text": rd.fmt(value, base["unit"]) if value is not None else "",
            "manual": bool(v.get("manual")), "delta": v.get("delta"), "period": v.get("period") or ""}


def model_of(clean: dict) -> dict:
    """정규화된 정의 → 표시 모델. 숫자는 여기서(리포트 에이전트의 계산으로) 정하고 화면은 그리기만 한다.
    A normalized definition → the display model. Numbers are settled here (with the report agent's math); the screen only draws."""
    state = to_state(clean)
    chart = state["charts"][0] if state["charts"] else None
    comp = rd.compute(chart, state["sources"][0]) if chart is not None else None
    insight, waiting = render_insight(clean["insight"], insight_values(state, comp)) if clean["insight"] else ("", False)
    kpis = [_kpi_model(k, state) for k in state["kpis"]]
    origins, refs = [], []
    for o in clean["origins"]:   # 출처 종류별 하나(가장 늦게 가져온 시각), 근거는 겹치지 않게 / one entry per kind (latest time), unique references
        hit = next((x for x in origins if x["kind"] == o["kind"]), None)
        if hit is None:
            origins.append({"kind": o["kind"], "label": ORIGIN_LABEL[o["kind"]], "fetched_at": o["fetched_at"]})
        elif o["fetched_at"] > hit["fetched_at"]:
            hit["fetched_at"] = o["fetched_at"]
        for r in o["refs"]:
            if r not in refs and len(refs) < MAX_REFS:
                refs.append(dict(r))
    model = {"v": SPEC_VERSION, "title": clean["title"], "kpis": kpis,
             "chart": _chart_model(chart, comp) if chart is not None else None,
             "theme": clean["theme"], "insight": insight, "insight_wait": waiting,
             "blocks": [dict(b) for b in clean["blocks"]], "refs": refs, "origins": origins,
             "refresh": any(refreshable(o) for o in clean["origins"]),
             "needs_data": any(k["pending"] for k in kpis), "empty": chart is None and not kpis and not clean["blocks"]}
    if clean.get("size"):   # 홈의 처음 크기(size_of 가 읽는다) / the first size on the home (read by size_of)
        model["size"] = dict(clean["size"])
    return model


def resolve(spec, draft: bool = False) -> dict:
    """표시 모델: 정의를 정규화한 뒤(틀리면 SpecError) 지금 데이터로 그릴 값을 계산한다. 모든 모델에 v · empty 가 있다.
    The display model: normalizes the definition (SpecError when wrong) and computes what to draw from the current data.
    Every model carries v and empty."""
    return model_of(normalize_spec(spec, draft=draft))


# ────────────────────────────────────────────────────────
# 만든 위젯 저장소 / made-widget store
# ────────────────────────────────────────────────────────

def _row_to_widget(r) -> dict:
    return {"key": r["id"], "kind": "custom", "name": r["title"], "spec": _loads(r["spec"], {}),
            "model": _loads(r["model"], {}), "created_at": r["created_at"], "updated_at": r["updated_at"]}


def _new_key(conn) -> str:
    for _ in range(20):
        key = "cw_" + secrets.token_hex(4)
        if conn.execute("SELECT 1 FROM home_widgets WHERE id = ?", (key,)).fetchone() is None:
            return key
    raise WidgetError("위젯 키를 만들지 못했습니다. 다시 시도해 주세요")


def list_widgets(owner: str) -> list[dict]:
    """내 위젯만, created_at 오름차순(같은 초면 만든 순서) / my widgets only, created_at ascending (creation order within a second)."""
    with db._conn() as conn:  # noqa: SLF001
        rows = conn.execute("SELECT * FROM home_widgets WHERE owner = ? ORDER BY created_at ASC, rowid ASC",
                            (_own(owner),)).fetchall()
    return [_row_to_widget(r) for r in rows]


def get_widget(owner: str, key: str) -> dict | None:
    """내 위젯 하나. 없거나 남의 위젯이면 None / one of my widgets; None when missing or someone else's."""
    with db._conn() as conn:  # noqa: SLF001
        r = conn.execute("SELECT * FROM home_widgets WHERE id = ? AND owner = ?", (key, _own(owner))).fetchone()
    return _row_to_widget(r) if r else None


def create_widget(owner: str, spec) -> dict:
    """위젯 만들기: 개수 상한(WidgetError) → 정의 정규화(SpecError, 차트나 KPI 카드가 있어야 한다) → 표시 모델 계산 → 저장.
    배치에는 넣지 않는다(배치 편집의 위젯 추가 서랍 = 안 쓰는 위젯).
    Creates a widget: the cap (WidgetError), then normalization (SpecError), the display model and the insert. It is not
    placed, so it lands in the Add widget drawer of layout editing (the unused widgets)."""
    owner = _own(owner)
    with db._conn() as conn:  # noqa: SLF001
        conn.execute("BEGIN IMMEDIATE")   # 개수 확인과 추가를 한 번에 / count and insert in one go
        count = conn.execute("SELECT COUNT(*) FROM home_widgets WHERE owner = ?", (owner,)).fetchone()[0]
        if count >= MAX_WIDGETS:
            raise WidgetError(f"위젯은 한 사람당 {MAX_WIDGETS}개까지 만들 수 있습니다")
        clean = normalize_spec(spec)
        clean["origins"] = _trusted(owner, clean["origins"])
        model = model_of(clean)
        key = _new_key(conn)
        now = kst.now_iso()
        conn.execute("INSERT INTO home_widgets(id, owner, title, spec, model, created_at, updated_at)"
                     " VALUES(?, ?, ?, ?, ?, ?, ?)",
                     (key, owner, clean["title"], _dumps(clean), _dumps(model), now, now))
    return get_widget(owner, key)


def update_widget(owner: str, key: str, spec) -> dict | None:
    """정의 바꾸기(created_at 유지). 없거나 남의 위젯이면 None(정의 검사보다 먼저), 정의가 틀리면 SpecError.
    Replaces the definition (created_at kept). None when missing or someone else's (checked before the definition),
    SpecError when the definition is wrong."""
    owner = _own(owner)
    if get_widget(owner, key) is None:
        return None
    clean = normalize_spec(spec)
    clean["origins"] = _trusted(owner, clean["origins"])
    model = model_of(clean)
    with db._conn() as conn:  # noqa: SLF001
        cur = conn.execute("UPDATE home_widgets SET title = ?, spec = ?, model = ?, updated_at = ? WHERE id = ? AND owner = ?",
                           (clean["title"], _dumps(clean), _dumps(model), kst.now_iso(), key, owner))
    if cur.rowcount == 0:   # 그 사이 지워졌다 / deleted in the meantime
        return None
    return get_widget(owner, key)


def delete_widget(owner: str, key: str) -> bool:
    """내 위젯 지우기. 저장된 배치에서도 그 키를 빼고(읽기 정규화로) 빈 곳은 위로 당긴다. 기본 위젯 · 없는 위젯 · 남의 위젯이면 False.
    Deletes one of my widgets and strips its key from the saved layout (via the lenient normalization), pulling the gap up.
    False for a built-in, a missing or someone else's widget."""
    owner = _own(owner)
    with db._conn() as conn:  # noqa: SLF001
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute("DELETE FROM home_widgets WHERE id = ? AND owner = ?", (key, owner))
        if cur.rowcount == 0:
            return False
        conn.execute("DELETE FROM home_widget_chats WHERE owner = ? AND widget = ?", (owner, key))   # 그 위젯의 대화도 / its conversation too
        saved = conn.execute("SELECT layout_type, columns FROM home_dash_config WHERE owner = ?", (owner,)).fetchone()
        if saved is not None:
            config = normalize_config(_read_saved(saved), _sizes(conn, owner))
            conn.execute("UPDATE home_dash_config SET layout_type = ?, columns = ?, updated_at = ? WHERE owner = ?",
                         (config["layout_type"], _store_value(config), kst.now_iso(), owner))
    return True


def store_refresh(owner: str, key: str, spec: dict, read: dict) -> dict | None:
    """새로 가져온 내용(데이터 파이프라인)을 저장한다: 정의 · 모델을 바꾸되 updated_at 은 그대로(사용자가 고친 것이 아니므로). 그 사이
    정의가 바뀌었으면 쓰지 않고 None — 읽은 위젯(read)의 updated_at 과 정의 글자를 둘 다 대조한다(updated_at 은 초 단위라 같은 초의 수정을
    놓쳤다, 3단계 검토). 반환 = 새 모델.
    Stores content fetched again: spec and model change while updated_at stays (no user edit). When the definition changed
    meanwhile nothing is written and None is returned; both updated_at and the definition text of the widget as read are compared
    (updated_at has whole seconds and missed an edit within the same second, phase-3 review). Returns the new model."""
    clean = normalize_spec(spec)
    model = model_of(clean)
    with db._conn() as conn:  # noqa: SLF001
        cur = conn.execute("UPDATE home_widgets SET spec = ?, model = ? WHERE id = ? AND owner = ? AND updated_at = ? AND spec = ?",
                           (_dumps(clean), _dumps(model), key, _own(owner), read["updated_at"], _dumps(read["spec"])))
    return model if cur.rowcount else None


def widget_data(owner: str, key: str) -> dict | None:
    """{key, model, fetched_at}: 정의 안의 데이터로 표시 모델을 다시 계산하고 저장된 model 도 바꾼다(updated_at 은 정의가 바뀔
    때만 바뀌므로 그대로) — 인사이트도 그 값으로 다시 쓰인다. 출처의 내용을 새로 가져오는 일은 API(/data)가 widget_data.refresh 로 먼저 한다.
    없거나 남의 위젯이면 None.
    {key, model, fetched_at}: recomputes the display model from the data inside the definition and refreshes the stored model
    (updated_at tracks definition changes only, so it stays); the insight is rewritten too. Fetching fresh content is done
    first by the API (/data) through widget_data.refresh. None when missing or someone else's."""
    owner = _own(owner)
    widget = get_widget(owner, key)
    if widget is None:
        return None
    model = resolve(widget["spec"])
    fetched = kst.now_iso()
    with db._conn() as conn:  # noqa: SLF001
        # 그 사이 정의가 바뀌었으면(updated_at 이 다르면) 옛 정의로 계산한 모델을 덮어쓰지 않는다
        # a definition changed in the meantime (a different updated_at) is never overwritten with the model of the old one
        conn.execute("UPDATE home_widgets SET model = ? WHERE id = ? AND owner = ? AND updated_at = ? AND spec = ?",
                     (_dumps(model), key, owner, widget["updated_at"], _dumps(widget["spec"])))
    return {"key": key, "model": model, "fetched_at": fetched}


# ────────────────────────────────────────────────────────
# 위젯 에이전트 대화 저장(2026-11-19, 문서 13절) — 위젯마다 하나. 화면이 저장하는 때: 위젯을 저장했을 때, 그리고 저장본과 같은 상태에서 턴이
# 끝났을 때(저장하지 않은 변경이 있으면 대화도 저장하지 않는다 — 다시 열면 저장한 위젯과 대화가 맞는다).
# The widget agent's saved conversation (2026-11-19, section 13), one per widget. The screen saves it when the widget is saved
# and when a turn ends with nothing unsaved (unsaved changes keep the conversation unsaved too, so reopening matches the saved widget).
# ────────────────────────────────────────────────────────

def _chat_text(chat: dict) -> str:
    """대화 저장본의 JSON — 화면(JSON.stringify)과 같은 촘촘한 꼴이라 화면이 잰 크기와 서버가 잰 크기가 같다(독립 검토 2026-11-19)
    the saved conversation as compact JSON, the same shape the screen measures with JSON.stringify (independent review)"""
    return json.dumps(chat, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def normalize_chat(raw) -> dict:
    """대화 저장본 정리: {v: 1, msgs, hist, label, at}. msgs = 화면이 그린 대화(dict 목록, 마지막 MAX_CHAT_MSGS 개 — 화면이 이스케이프해
    그린다), hist = 변경 기록(마지막 MAX_CHAT_HIST 개, 정의는 작업본 규칙으로 정규화하고 틀린 것은 버린다), label · at = 지금 모습의 이름 · 시각.
    틀린 모양이나 MAX_CHAT_CHARS 를 넘으면 WidgetError.
    Cleans a saved conversation: msgs = the drawn conversation (dicts, the last MAX_CHAT_MSGS; the screen escapes what it draws),
    hist = the history states (the last MAX_CHAT_HIST, definitions normalized as drafts, broken ones dropped), label and at = the
    current state's name and time. A wrong shape or more than MAX_CHAT_CHARS raises WidgetError."""
    if not isinstance(raw, dict) or not isinstance(raw.get("msgs"), list) or not all(isinstance(m, dict) for m in raw["msgs"]):
        raise WidgetError("대화 기록 형식이 올바르지 않습니다")
    # 역할이 사용자 · 에이전트이고 글이 글자인 줄만(화면은 다시 그릴 때 칸마다 다시 짓는다 — 독립 검토 2026-11-19)
    # only user / agent entries with text as text (the screen rebuilds every field when it draws again — independent review)
    msgs = [m for m in raw["msgs"] if m.get("role") in ("user", "agent") and isinstance(m.get("text", ""), str)]
    hist = []
    for h in (raw.get("hist") if isinstance(raw.get("hist"), list) else [])[-MAX_CHAT_HIST:]:
        if not isinstance(h, dict):
            continue
        try:
            spec = normalize_spec(h.get("widget"), draft=True)
        except SpecError:
            continue
        hist.append({"id": _txt(h.get("id"), 40), "label": _txt(h.get("label"), MAX_CHAT_LABEL), "at": _txt(h.get("at"), 40), "widget": spec})
    chat = {"v": 1, "msgs": msgs[-MAX_CHAT_MSGS:], "hist": hist, "label": _txt(raw.get("label"), MAX_CHAT_LABEL), "at": _txt(raw.get("at"), 40)}
    try:
        text = _chat_text(chat)
    except (TypeError, ValueError):
        raise WidgetError("대화 기록 형식이 올바르지 않습니다") from None
    if len(text) > MAX_CHAT_CHARS:
        raise WidgetError("대화 기록이 너무 큽니다. 오래된 대화를 줄여 주세요")
    return chat


def get_chat(owner: str, key: str) -> dict | None:
    """{key, chat(저장본 | None), updated_at}. 없거나 남의 위젯이면 None / the saved conversation; None for a missing or foreign widget"""
    owner = _own(owner)
    if get_widget(owner, key) is None:
        return None
    with db._conn() as conn:  # noqa: SLF001
        r = conn.execute("SELECT chat, updated_at FROM home_widget_chats WHERE owner = ? AND widget = ?", (owner, key)).fetchone()
    return {"key": key, "chat": _loads(r["chat"], None) if r else None, "updated_at": r["updated_at"] if r else ""}


def save_chat(owner: str, key: str, raw) -> dict | None:
    """대화 저장(덮어쓰기) → {key, updated_at}. 없거나 남의 위젯이면 None, 틀린 저장본은 WidgetError.
    Saves (replaces) the conversation → {key, updated_at}; None for a missing or foreign widget, WidgetError for a wrong one."""
    owner = _own(owner)
    chat = normalize_chat(raw)
    now = kst.now_iso()
    with db._conn() as conn:  # noqa: SLF001
        conn.execute("BEGIN IMMEDIATE")   # 위젯 확인과 저장을 한 번에(그 사이 지워진 위젯에 남지 않게) / check and write at once
        if conn.execute("SELECT 1 FROM home_widgets WHERE id = ? AND owner = ?", (key, owner)).fetchone() is None:
            return None
        conn.execute("INSERT OR REPLACE INTO home_widget_chats(owner, widget, chat, updated_at) VALUES(?, ?, ?, ?)",
                     (owner, key, _chat_text(chat), now))
    return {"key": key, "updated_at": now}
