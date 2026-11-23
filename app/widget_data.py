"""위젯 데이터 파이프라인(2026-11-16, 위젯 에이전트 전용 — 채팅 파이프라인과 별개, 계약 = docs/widget-agent.md 11절).

2026-11-16 사용자 결정: 데이터 출처 = 사내(권한 안의 사내 데이터 · 사내 문서) & 웹. 위젯은 숫자 위주일 필요가 없다 — 요청 키워드에 맞는
내용(숫자 · 차트 · 목록 · 글)을 만든다. 의도 판단에서 웹이 필요해 보이면 사내 결과를 기다리지 않고 바로 웹을 찾는다. DB 에 없으면 웹 검색
기반으로 채운다. 질문에 맞춰 미리 그릴 수 있는 부분(제목 · 칸 모양)은 먼저 그린다(plan 알림 → 위젯 에이전트가 초안을 보낸다).

흐름: plan_request(의도 판단: 어디서 · 어떤 모양 · 제목 · 카드 이름) → 고른 갈래를 바로 실행(여럿이면 동시에, 기한 하나) → 계획 순서로 처음
찾은 결과를 쓴다 → 고른 사내 갈래가 모두 못 찾았고 웹을 고르지 않았으면 웹으로 한 번 더(DB 에 없으면 웹).
- 사내 데이터: 리포트 에이전트의 Text2SQL(report_agent.query — 신원의 허용 테이블만, p_data) → 표
- 사내 문서: 지식 검색(kb.search) → 신원의 허용 문서만(p_know) → 발췌에서 위젯 내용 뽑기
- 웹: 환율 · 날씨는 실시간 출처(채팅 위젯 모듈), 그 밖은 구글 검색 근거(llm.generate_grounded_meta) → 요약에서 위젯 내용 뽑기
뽑은 숫자는 자료의 본문에 적힌 것만 싣는다(지어낸 숫자는 버린다). 표 → 차트 · 데이터 KPI 카드, 숫자 → 고정 숫자 KPI 카드, 목록 · 글 → 블록.
위젯의 부분마다 출처(origins)를 따로 적고, 새로 가져오기(refresh)는 그 부분만 바꾼다 — 카드는 가져올 때의 이름(key)으로 짝짓는다.

The widget data pipeline (2026-11-16, for the widget agent only and separate from the chat pipeline; contract =
docs/widget-agent.md section 11). User decisions of 2026-11-16: the sources are internal (permission-scoped company data and
documents) and the web; widgets need not be numeric, as the content follows the request's keywords; when the intent step sees a
need for the web it searches the web at once instead of waiting for internal results; what is not in the DB comes from the web;
what can be drawn early (title, slots) is drawn first. Flow: plan → run the picked branches at once (concurrently, one deadline)
→ the first that found something in plan order → one more web search when the picked internal branches found nothing. Numbers are
kept only when the material's body states them. Every part of a widget records its own origin and a refresh changes only that
part; cards are matched by the name they were fetched under, never by position.
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import decimal
import json
import logging
import math
import re
import time

from app import catalog, home_widgets as hw, kb, kst, llm, report_agent as ra, report_dash as rd, settings

logger = logging.getLogger("ai365.widget_data")

SOURCES = ("data", "docs", "web")
VIEWS = ("kpi", "chart", "list", "text")
SOURCE_LABEL = {"data": "사내 데이터", "docs": "사내 문서", "web": "웹 검색"}
PART_OF = {"table": "source", "numbers": "cards", "text": "text", "items": "list"}   # 결과 종류 → 위젯의 부분 / result kind → widget part
MAX_NUMBERS = 4
MAX_ITEMS = 8
MAX_TEXT = 600
MAX_TABLE_ROWS = 24
MAX_REFS = 6
MAX_COLUMNS = 12
MAX_ROWS = 200
MAX_CELL = rd.MAX_CELL
MAX_TABLE_CHARS = 60_000      # 가져온 표의 JSON 글자 수 — 정의 전체 상한(10만)에 걸려 턴을 잃지 않게 / keeps the definition under its 100k cap
DOC_HITS = 6
BRANCH_TIMEOUT = 90           # 갈래 전체의 기한(초) / the deadline for the branches (s)
REFRESH_WAIT = 20             # /data 가 새로 가져오기를 기다리는 시간(초) — 넘으면 예전 내용으로 답하고 뒤에서 마친다 / then the old content answers
MATERIAL_CHARS = 6000

INTENT_SYSTEM = """너는 그룹웨어 홈 위젯의 데이터 플래너다. 사용자 요청을 보고 어디서 무엇을 가져와 어떤 모양으로 보여 줄지 정한다. JSON 으로만 답한다.
출력: {"sources": ["data" | "docs" | "web", ...], "view": "kpi" | "chart" | "list" | "text", "title": "위젯 제목(20자 이내)", "query": "가져올 내용을 한 문장으로(기간 · 대상 · 지표를 분명히)", "labels": ["KPI 카드 이름", ...]}
- data = 사내 데이터베이스(매출 · 실적 · 인원 · 근태 · 재고 · 예산 · 비용 · 프로젝트 · 고객 · 주문 · 품질 · 생산 같은 회사의 숫자와 표)
- docs = 사내 문서(규정 · 정책 · 안내 · 매뉴얼 · 가이드 · 지침 · 복리후생 · 카탈로그 · 경영지표 문서)
- web = 웹 검색(환율 · 주가 · 금리 · 날씨 · 뉴스 · 시장 동향 · 업계 소식 · 경쟁사 소식처럼 회사 밖의 최신 정보). 필요해 보이면 바로 고른다.
- sources 는 가장 알맞은 곳부터 적는다. 회사 숫자면 data, 회사 문서 내용이면 docs, 회사 밖 정보면 web. 여럿이 필요하면 여럿을 적는다.
- view: 숫자 한두 개 → kpi, 기간 · 항목별 비교나 추이 → chart, 여러 건의 목록(뉴스 · 일정 · 항목) → list, 설명 · 요약 → text.
- labels: view 가 kpi 일 때만, 사용자가 요청에 적은 항목의 카드 이름(최대 4개). 요청에 없는 항목을 지어 넣지 않는다 — 항목을 말하지 않았으면 대표 숫자 하나의 이름 1개. view 가 kpi 가 아니면 빈 목록."""

EXTRACT_SYSTEM = """너는 홈 위젯의 내용 작성기다. [자료]에 있는 사실만으로 [요청]에 맞는 위젯 내용을 JSON 으로만 만든다. 자료에 없는 숫자나 사실은 쓰지 않는다.
출력 형식: {"numbers": [{"label": "", "value": "", "unit": "", "note": ""}], "table": {"columns": [], "rows": []}, "items": [{"title": "", "sub": "", "url": ""}], "text": ""}
- [모양]에 맞는 항목만 채우고 나머지는 빈 값으로 둔다.
  kpi → numbers(최대 4개, [카드 이름]이 있으면 그 이름을 label 로) / chart → table(첫 열 = 항목이나 기간, 나머지 열 = 숫자, 행 2~24개) / list → items(최대 8개, sub 는 날짜 · 출처 같은 한 줄, url 은 [자료]에 적힌 주소만) / text → text(3문장 이내 요약)
- value 와 표의 숫자는 자료에 적힌 숫자 그대로 쓴다(쉼표는 빼도 된다). 단위는 unit 에 따로 적는다. note 는 기준일 · 출처 같은 짧은 설명.
- text 는 위젯에 그대로 보이는 요약이다. 자료에 있는 내용만 쓰고, "자료에 없다 · 언급되지 않았다" 같은 말은 쓰지 않는다.
- 자료에서 요청에 맞는 내용을 찾지 못했으면 모두 빈 값으로 둔다."""

WEB_SYSTEM = "웹 검색으로 마지막 요청에 필요한 최신 사실을 찾아 한국어로 간결히 정리하라. 숫자 · 날짜 · 기준 시점을 분명히 적는다."

# 의도 판단이 실패했을 때의 낱말 규칙 / the keyword rule when the intent call fails
_WEB_WORDS = re.compile(r"환율|주가|증시|코스피|코스닥|나스닥|시세|날씨|기온|미세먼지|뉴스|헤드라인|속보|금리|유가|비트코인|코인|시장 동향|업계|트렌드|경쟁사")
_DOC_WORDS = re.compile(r"규정|정책|안내|매뉴얼|가이드|지침|복리|후생|휴가|연차|취업규칙|카탈로그|절차|방침|온보딩|채용")
_LIST_WORDS = re.compile(r"뉴스|헤드라인|목록|리스트|소식|일정")
_TEXT_WORDS = re.compile(r"요약|설명|정리|안내|규정")
_CHART_WORDS = re.compile(r"추이|비교|별|차트|그래프|월별|분기별|연도별|지점별|부서별")
_ASK_TAIL = re.compile(r"\s*(?:위젯|카드|차트)?\s*(?:을|를)?\s*(?:만들어|보여|알려|넣어|그려|추가해|띄워)\s*(?:줘|주세요|줄래|줄\s*수\s*있어)?\s*[.!?~]*\s*$")
# 숫자: 부호는 낱말 · 숫자 바로 뒤가 아닐 때만(2026-11-16 의 -11 · -16 은 부호가 아니다) / a sign only when not glued to a word or digit
_NUM = re.compile(r"(?:(?<![\w.])[-+])?\d[\d,]*(?:\.\d+)?")
# 기간 · 번호 꼴 숫자 열(연도 · 월 · id …)은 KPI 카드의 숫자로 쓰지 않는다 / period- or id-like number columns never become KPI values
_PERIOD_COL = re.compile(r"^(?:연도|년도|년|월|일|분기|주차|year|month|day|quarter|week|date|id|no|번호|코드|순위|rank)$|(?:연도|년도|_id|번호|코드)$", re.I)


def _txt(value, n: int) -> str:
    return value.strip()[:n] if isinstance(value, str) else ""


class Cancelled(Exception):
    """화면이 턴을 멈췄다(스트림을 끊었다) — 남은 일을 하지 않는다(2026-11-19) / the screen stopped the turn; the rest is skipped"""


def _emit(emit, kind: str, data: dict) -> None:
    if emit is None:
        return
    try:
        emit(kind, data)
    except Exception:  # noqa: BLE001 — 알림이 실패해도 일은 계속한다 / a failed notice never stops the work
        logger.debug("알림 실패 / emit failed", exc_info=True)


# ────────────────────────────────────────────────────────
# 의도 판단 / intent
# ────────────────────────────────────────────────────────

def _title_of(request: str) -> str:
    """요청 → 위젯 제목(끝의 '위젯을 만들어줘' 같은 말을 뗀다) / a title from the request, without trailing ask phrases"""
    t = _ASK_TAIL.sub("", (request or "").strip()).strip()
    return (t or (request or "").strip())[:20]


def rule_plan(request: str) -> dict:
    """낱말 규칙 계획(의도 판단 호출이 실패했을 때) / the keyword plan (when the intent call fails)"""
    sources = (["web"] if _WEB_WORDS.search(request) else []) + (["docs"] if _DOC_WORDS.search(request) else []) or ["data"]
    view = ("list" if _LIST_WORDS.search(request) else "text" if _TEXT_WORDS.search(request)
            else "chart" if _CHART_WORDS.search(request) else "kpi")
    return {"sources": sources, "view": view, "title": _title_of(request), "query": request.strip()[:300], "labels": []}


def clean_plan(raw, request: str) -> dict:
    """의도 판단 결과 정리: 글자가 아닌 값은 버리고, 모르는 출처 · 모양은 낱말 규칙으로, 제목 20자 · 질의 300자 · 카드 이름 4개까지.
    Cleans the intent output: non-text values are dropped, unknown sources or views fall back to the keyword rule; title 20,
    query 300, up to four labels."""
    raw = raw if isinstance(raw, dict) else {}
    rule = rule_plan(request)
    picked = raw.get("sources") if isinstance(raw.get("sources"), list) else []
    sources = [s for s in dict.fromkeys(x for x in picked if isinstance(x, str)) if s in SOURCES]
    view = raw.get("view") if raw.get("view") in VIEWS else rule["view"]
    labels = [_txt(x, 40) for x in (raw.get("labels") if isinstance(raw.get("labels"), list) else []) if _txt(x, 40)]
    return {"sources": sources or rule["sources"], "view": view, "title": _txt(raw.get("title"), 20) or rule["title"],
            "query": _txt(raw.get("query"), 300) or rule["query"], "labels": list(dict.fromkeys(labels))[:MAX_NUMBERS] if view == "kpi" else []}


def plan_request(request: str) -> dict:
    """의도 판단 1회(경량) — 실패하면 낱말 규칙 / one intent call (lite); the keyword rule on failure"""
    try:
        out = llm.generate(f"[요청]\n{request}", system=INTENT_SYSTEM, json_mode=True, tier="lite")
    except Exception as e:  # noqa: BLE001
        logger.warning("위젯 의도 판단 실패, 낱말 규칙으로: %s", type(e).__name__)
        out = None
    return clean_plan(out, request)


# ────────────────────────────────────────────────────────
# 자료에서 위젯 내용 뽑기 / extracting widget content from material
# ────────────────────────────────────────────────────────

def _numbers_of(text: str) -> set[float]:
    out = set()
    for m in _NUM.findall(text or ""):
        v = rd.num(m)
        if v is not None:
            out.add(round(v, 6))
    return out


def _stated(value, nums: set[float]) -> float | None:
    """자료에 적힌 숫자면 그 값, 아니면 None(지어낸 숫자를 버린다) / the value when the material states it, else None"""
    v = rd.num(value)
    return v if v is not None and round(v, 6) in nums else None


def _safe_url(url, material: str) -> str:
    u = _txt(url, 500)
    return u if u.lower().startswith(("http://", "https://")) and u in material else ""


def extract(query: str, view: str, labels: list[str], material: str, facts: str | None = None) -> dict | None:
    """자료 → 위젯 내용 {kind: numbers | table | items | text, …}. 숫자는 facts(자료의 본문 — 번호 · 쪽 · 파일 이름 · 주소 같은 표식을 뺀 것,
    없으면 자료 전체)에 적힌 것만, 주소는 자료에 있는 것만. 없으면 None.
    Material → widget content. Numbers only when `facts` (the material's body, without markers such as [1], p.3, file names or
    addresses; the whole material when omitted) states them; addresses only when present in the material. None when empty."""
    material = (material or "")[:MATERIAL_CHARS]
    prompt = (f"[요청]\n{query}\n\n[모양]\n{view}" + (f"\n\n[카드 이름]\n{', '.join(labels)}" if labels else "")
              + f"\n\n[자료]\n{material}")
    try:
        out = llm.generate(prompt, system=EXTRACT_SYSTEM, json_mode=True, tier="lite")
    except Exception as e:  # noqa: BLE001
        logger.warning("위젯 내용 뽑기 실패: %s", type(e).__name__)
        return None
    out = out if isinstance(out, dict) else {}
    nums = _numbers_of(material if facts is None else facts[:MATERIAL_CHARS])
    numbers = []
    for i, n in enumerate(out.get("numbers") if isinstance(out.get("numbers"), list) else []):
        if not isinstance(n, dict):
            continue
        v = _stated(n.get("value"), nums)
        label = _txt(n.get("label"), 40) or (labels[i] if i < len(labels) else "")
        if v is None or not label or any(x["label"] == label for x in numbers):
            continue
        numbers.append({"label": label, "value": v, "unit": _txt(n.get("unit"), 8), "note": _txt(n.get("note"), rd.MAX_KPI_NOTE)})
    table = None
    t = out.get("table") if isinstance(out.get("table"), dict) else {}
    cols = [_txt(c, 40) for c in (t.get("columns") if isinstance(t.get("columns"), list) else [])]
    if 2 <= len(cols) <= 6 and all(cols) and len(set(cols)) == len(cols):
        rows = []
        for r in (t.get("rows") if isinstance(t.get("rows"), list) else [])[:MAX_TABLE_ROWS]:
            if not isinstance(r, list) or len(r) != len(cols) or not _txt(str(r[0]) if r[0] is not None else "", 80):
                continue
            vals = [_stated(c, nums) for c in r[1:]]
            if any(v is None for v in vals):
                continue   # 자료에 없는 숫자가 낀 줄은 버린다 / a row with an unstated number is dropped
            rows.append([str(r[0]).strip()[:80]] + vals)
        if rows:
            table = {"columns": cols, "rows": rows}
    items = []
    for it in (out.get("items") if isinstance(out.get("items"), list) else [])[:MAX_ITEMS]:
        if isinstance(it, dict) and _txt(it.get("title"), 120):
            items.append({"title": _txt(it.get("title"), 120), "sub": _txt(it.get("sub"), 160), "url": _safe_url(it.get("url"), material)})
    text = _txt(out.get("text"), MAX_TEXT)
    if text and not all(round(v, 6) in nums for v in (rd.num(x) for x in _NUM.findall(text)) if v is not None):
        text = ""   # 자료에 없는 숫자가 든 요약은 쓰지 않는다 / a summary with an unstated number is dropped
    found = {"numbers": numbers, "table": table, "items": items, "text": text}
    order = {"kpi": ("numbers", "table", "text", "items"), "chart": ("table", "numbers", "items", "text"),
             "list": ("items", "text", "numbers", "table"), "text": ("text", "items", "numbers", "table")}[view if view in VIEWS else "text"]
    kind = next((k for k in order if found[k]), None)
    if kind is None:
        return None
    return {"kind": kind, kind: found[kind]}


# ────────────────────────────────────────────────────────
# 숫자 ↔ 카드 짝짓기(이름으로, 순서가 아니라) / matching numbers to cards by name, never by position
# ────────────────────────────────────────────────────────

def _norm_label(s) -> str:
    return re.sub(r"\s+", "", str(s or "")).lower()


def _score(label: str, number: dict) -> int:
    a, b = _norm_label(label), _norm_label(number.get("label"))
    if not a or not b:
        return 0
    if a == b:
        return 3
    if a in b or b in a:
        return 2
    return 1 if any(_norm_label(x) and _norm_label(x) in a for x in number.get("aliases") or []) else 0


def match_numbers(labels: list[str], numbers: list[dict]) -> dict[int, int]:
    """이름 → 숫자 짝: {이름 위치: 숫자 위치}. 같은 이름 > 한쪽이 다른 쪽을 품음 > 별칭(예: '엔화' ↔ JPY 의 '엔'), 숫자는 한 번만.
    맞는 숫자가 없는 이름은 짝이 없다(순서로 채우지 않는다).
    Pairs names with numbers by exact name, containment, then aliases (e.g. '엔화' ↔ JPY's '엔'); each number once; a name
    without a match stays unpaired (never filled by position)."""
    pairs = sorted(((_score(l, n), i, j) for i, l in enumerate(labels) for j, n in enumerate(numbers)), key=lambda x: (-x[0], x[1], x[2]))
    out: dict[int, int] = {}
    used: set[int] = set()
    for score, i, j in pairs:
        if score <= 0:
            break
        if i not in out and j not in used:
            out[i] = j
            used.add(j)
    return out


def number_columns(columns: list[str], types: dict) -> list[str]:
    """KPI 카드에 쓸 숫자 열: 기간 · 번호 꼴(연도 · 월 · id …)은 뺀다(그것뿐이면 그대로) / number columns fit for KPI cards"""
    nums = [c for c in columns if types.get(c) == "number"]
    good = [c for c in nums if not _PERIOD_COL.search(str(c).strip())]
    return good or nums


def match_columns(labels: list[str], columns: list[str]) -> dict[int, str]:
    """카드 이름 → 열 이름(같은 이름 > 한쪽이 다른 쪽을 품음) / card names to columns by name"""
    got = match_numbers(labels, [{"label": c} for c in columns])
    return {i: columns[j] for i, j in got.items()}


# ────────────────────────────────────────────────────────
# 갈래 / branches
# ────────────────────────────────────────────────────────

def _cell(v):
    """DB 값 → 위젯 칸(글자 · 숫자 · None) / a DB value → a widget cell (text, number or None)"""
    if v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)):
        return v if not (isinstance(v, float) and not math.isfinite(v)) else None
    if isinstance(v, decimal.Decimal):
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, (dt.date, dt.datetime, dt.time)):
        return v.isoformat()[:MAX_CELL]
    return str(v).strip()[:MAX_CELL]


def table_source(columns: list, rows: list) -> dict | None:
    """조회 결과 → 위젯 표(열 12개 · 행 200줄 · 칸 300자, 열 이름은 겹치지 않게). JSON 이 MAX_TABLE_CHARS 를 넘으면 뒤쪽 줄을 덜어 낸다
    (정의 전체의 상한에 걸려 턴을 잃지 않게). A query result → a widget table; trailing rows are dropped while the JSON exceeds
    MAX_TABLE_CHARS, so the definition never hits its cap."""
    cols, seen = [], set()
    for c in list(columns or [])[:MAX_COLUMNS]:
        name = (str(c).strip() or "열")[:40]
        base, k = name, 2
        while name in seen:
            name = f"{base[:36]}_{k}"
            k += 1
        seen.add(name)
        cols.append(name)
    if not cols:
        return None
    out = [[_cell(r[i]) if isinstance(r, (list, tuple)) and i < len(r) else None for i in range(len(cols))] for r in list(rows or [])[:MAX_ROWS]]
    while len(out) > 1 and len(json.dumps({"columns": cols, "rows": out}, ensure_ascii=False)) > MAX_TABLE_CHARS:
        out = out[:max(1, len(out) * 4 // 5)]
    return {"tool": "inline", "columns": cols, "rows": out} if out else None


KO_ALIAS = "\n(위젯에 그대로 보이므로 결과 열 이름은 짧은 한국어 별칭으로 쓴다. 예: SUM(sales_amount) AS \"매출\")"
# 빈 결과면 한 번 더(실검증 2026-11-16: '이번 달'처럼 데이터에 없는 기간으로 좁혀 0행이 나왔다) / one more try on an empty result
# (real check of 2026-11-16: a period the data does not have, such as 'this month', gave zero rows)
RETRY_EMPTY = "\n(앞선 조회 결과가 0행이었다. 기간 조건이 있으면 데이터에 있는 가장 최근 기간(MAX)을 쓰고, 조건을 너무 좁히지 않는다)"
RETRY_NOTE = "요청한 조건에 맞는 데이터가 없어 데이터에 있는 가장 최근 기간으로 조회했습니다"


def run_data(query: str, eff: dict | None) -> dict:
    """사내 데이터 — 리포트 에이전트의 Text2SQL(신원의 허용 테이블만). 위젯 범례 · 카드에 보이는 열 이름은 한국어 별칭을 부탁한다(리포트
    에이전트의 SQL 지시문은 그대로). 결과가 비면 한 번만 다시 묻고, 그랬다고 note 에 적는다. / company data through the report
    agent's Text2SQL; Korean column aliases are requested; an empty result is asked once more, and the note says so"""
    src, sql, note = None, "", ""
    for attempt, hint in enumerate((KO_ALIAS, KO_ALIAS + RETRY_EMPTY)):
        try:
            columns, rows, sql = ra.query(query + hint, eff)
        except ra.AgentError as e:
            return {"ok": False, "why": str(e)}
        except Exception as e:  # noqa: BLE001
            logger.warning("위젯 사내 데이터 조회 실패: %s", type(e).__name__)
            return {"ok": False, "why": "사내 데이터를 조회하지 못했습니다"}
        src = table_source(columns, rows)
        if src is not None:
            note = RETRY_NOTE if attempt else ""
            break
    if src is None:
        return {"ok": False, "why": "사내 데이터에서 찾지 못했습니다"}
    tables = ra.tables_in(sql)
    out = {"ok": True, "kind": "table", "table": src, "sql": sql, "tables": tables,
           "refs": [{"kind": "data", "label": _table_label(t, eff), "url": "", "page": None} for t in tables[:MAX_REFS]]
           or [{"kind": "data", "label": SOURCE_LABEL["data"], "url": "", "page": None}]}
    if note:
        out["note"] = note
    return out


def _table_label(table: str, eff: dict | None) -> str:
    """근거에 보일 이름 = 그 신원이 볼 수 있는 워크스페이스의 데이터 이름(예: 지점별_월매출), 없으면 테이블 이름 — 남의 워크스페이스 이름은
    보이지 않는다. The name shown as a reference: the data name in a workspace the identity can read, else the table name."""
    nodes = (eff or {}).get("nodes") or {}
    try:
        for w in catalog._active_workspaces():  # noqa: SLF001 — data_locate 는 권한을 보지 않는다 / data_locate ignores permissions
            for kind in ("sql", "csv"):
                for it in (w.get(kind) or []):
                    if it.get("table") == table and (eff is None or nodes.get(it.get("node"), 0) >= 1):
                        return str(it.get("name") or table)[:120]
    except Exception:  # noqa: BLE001 — 이름은 덤이다 / the name is a bonus
        pass
    return str(table)[:120]


def run_docs(query: str, eff: dict | None, view: str, labels: list[str]) -> dict:
    """사내 문서 — 지식 검색(신원의 허용 문서만) → 발췌에서 뽑기. 숫자는 발췌 본문에서만 확인한다(번호 · 파일 이름 · 쪽 표식은 빼고).
    Company documents (allowed files only) → extraction; numbers are checked against the excerpts' bodies only."""
    if eff is not None and not catalog.domain_readable(eff, "p_know"):
        return {"ok": False, "why": "사내 문서를 볼 권한이 없습니다", "denied": True}
    allowed = None if eff is None else catalog.allowed_knowledge_files(eff)
    try:
        hits = kb.search(query)
    except Exception as e:  # noqa: BLE001
        logger.warning("위젯 사내 문서 검색 실패: %s", type(e).__name__)
        return {"ok": False, "why": "사내 문서를 검색하지 못했습니다"}
    hits = [h for h in hits if (allowed is None or h.get("doc") in allowed) and h.get("similarity", 0.0) >= settings.KB_WEAK_SIM][:DOC_HITS]
    if not hits:
        return {"ok": False, "why": "사내 문서에서 찾지 못했습니다"}
    bodies = [str(h.get("text") or "")[:1200] for h in hits]
    material = "\n\n".join(f"[{i + 1}] ({h.get('doc')}, p.{h.get('page')})\n{b}" for i, (h, b) in enumerate(zip(hits, bodies)))
    content = extract(query, view, labels, material, facts="\n\n".join(bodies))
    if content is None:
        return {"ok": False, "why": "사내 문서에서 위젯에 넣을 내용을 찾지 못했습니다"}
    refs, seen = [], set()
    for h in hits:
        key_ = (h.get("doc"), h.get("page"))
        if key_ not in seen and len(refs) < MAX_REFS:
            seen.add(key_)
            refs.append({"kind": "doc", "label": str(h.get("doc") or "")[:120], "url": "", "page": h.get("page")})
    return {"ok": True, **content, "refs": refs}


def run_web(query: str, view: str, labels: list[str]) -> dict:
    """웹: 환율 · 날씨는 실시간 출처(채팅 위젯과 같은 야후 파이낸스 · Open-Meteo)에서 먼저, 그 밖은 구글 검색 근거 → 요약에서 뽑기(숫자는
    요약 본문에서만 확인). 그라운딩을 쓸 수 없을 때 모델 지식으로 채우지 않는다(숫자를 지어내지 않게).
    The web: exchange rates and weather come first from the live sources; everything else goes through Google Search grounding
    and extraction (numbers checked against the summary body only). Without grounding nothing is filled from model knowledge."""
    live = run_live(query, view)
    if live is not None and live.get("ok"):
        return {**live, "live": True}   # 실시간 출처(화면의 진행 줄이 구별한다) / a live source (the screen's progress line tells it apart)
    try:
        meta = llm.generate_grounded_meta([{"role": "user", "content": query}], system=WEB_SYSTEM)
    except llm.GroundingUnavailableError:
        return live or {"ok": False, "why": "웹 검색을 쓸 수 없습니다"}
    except Exception as e:  # noqa: BLE001
        logger.warning("위젯 웹 검색 실패: %s", type(e).__name__)
        return live or {"ok": False, "why": "웹 검색에 실패했습니다"}
    text = str((meta or {}).get("text") or "")
    sources = [s for s in ((meta or {}).get("sources") or []) if isinstance(s, dict)]
    if not text.strip():
        return {"ok": False, "why": "웹에서 찾지 못했습니다"}
    material = text + "\n\n[출처]\n" + "\n".join(f"[{i + 1}] {s.get('title', '')} {s.get('url', '')}" for i, s in enumerate(sources[:MAX_REFS]))
    content = extract(query, view, labels, material, facts=text)
    if content is None:
        return {"ok": False, "why": "웹에서 위젯에 넣을 내용을 찾지 못했습니다"}
    refs = [{"kind": "web", "label": str(s.get("title") or s.get("url") or "웹")[:120],
             "url": s.get("url") if str(s.get("url") or "").lower().startswith(("http://", "https://")) else "", "page": None}
            for s in sources[:MAX_REFS]] or [{"kind": "web", "label": "웹 검색", "url": "", "page": None}]
    return {"ok": True, **content, "refs": refs}


# ────────────────────────────────────────────────────────
# 웹의 실시간 출처: 환율 · 날씨(2026-11-16 실검증 — 이 키들의 구글 검색 근거가 3.x 모델에서 한도 초과(429)라 웹 갈래가 늘 비었다).
# 채팅 실시간 위젯의 모듈을 그대로 쓴다. 숫자는 출처의 값 그대로다. 규정 · 정책 같은 문서형 요청("출장비 적용 환율 규정")에는 쓰지 않는다.
# Live web sources for exchange rates and weather (real check of 2026-11-16: grounding answers 429 on these keys with the 3.x
# models). The chat live-widget modules are reused; numbers are the sources' own. Never used for document-like requests.
# ────────────────────────────────────────────────────────

_LIVE_FX = re.compile(r"환율|환전|exchange\s*rate", re.I)
_LIVE_WX = re.compile(r"날씨|기온|일기\s*예보|강수\s*확률|weather|forecast|temperature", re.I)
_WX_ALIASES = {"지금 기온": ["지금", "현재", "기온", "온도"], "최고": ["최고"], "최저": ["최저"], "강수 확률": ["강수", "확률"]}


def run_live(query: str, view: str) -> dict | None:
    """환율 · 날씨 요청이면 실시간 출처의 결과({ok, kind, …, refs}), 아니면 None / the live result for rates or weather, else None"""
    q = query or ""
    if _DOC_WORDS.search(q):
        return None   # 문서형 요청은 실시간 값이 답이 아니다 / a document-like request is not answered by live values
    try:
        if _LIVE_FX.search(q):
            return _live_fx(q, view)
        if _LIVE_WX.search(q):
            return _live_weather(q, view)
    except Exception as e:  # noqa: BLE001 — 실시간 출처가 실패하면 그라운딩으로 / a failed live source falls through to grounding
        logger.warning("위젯 실시간 출처 실패: %s", type(e).__name__)
        return {"ok": False, "why": "실시간 출처에서 받지 못했습니다"}
    return None


def _md_hm(iso: str) -> str:
    m = re.match(r"\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2})", iso or "")
    return f"{m.group(1)}/{m.group(2)} {m.group(3)}:{m.group(4)}" if m else ""


def _live_fx(query: str, view: str) -> dict:
    """원화 환율: 요청에 나온 통화(없으면 달러, 4개까지)마다 '1달러 · 100엔 …' 이 몇 원인가. 숫자에는 짝짓기용 별칭(코드 · 이름 · '엔화')을 붙인다.
    KRW rates per currency named (USD by default); each number carries matching aliases (code, names, '엔화')."""
    from app import live_fx, live_widgets   # 무거운 시세 모듈은 쓸 때만 / the quote module only when used
    codes = [c for c in live_widgets._currency_of(query) if c != "KRW" and c in live_fx.CURRENCIES][:MAX_NUMBERS] or ["USD"]  # noqa: SLF001
    rows = []
    for code in codes:
        try:
            q = live_fx.quote(code, "KRW")
        except live_fx.FxError:
            continue
        name = live_fx.CURRENCIES[code]
        rows.append({"label": f"{name[4]}{name[5]}", "value": round(float(q["quote"]["amount"]), 2), "at": _md_hm(q.get("as_of") or ""),
                     "sentence": live_fx.text(q), "aliases": [code, name[0], name[5], name[5] + "화"]})
    if not rows:
        return {"ok": False, "why": "환율 시세를 받지 못했습니다"}
    refs = [{"kind": "web", "label": live_fx.SOURCE["name"], "url": live_fx.SOURCE["url"], "page": None}]
    if view == "chart":
        return {"ok": True, "kind": "table", "table": {"tool": "inline", "columns": ["통화", "원"], "rows": [[r["label"], r["value"]] for r in rows]},
                "refs": refs}
    if view == "list":
        return {"ok": True, "kind": "items", "refs": refs,
                "items": [{"title": f"{r['label']} = {r['value']:,.2f}원", "sub": f"{r['at']} 기준 · {live_fx.SOURCE['name']}", "url": live_fx.SOURCE["url"]} for r in rows]}
    if view == "text":
        return {"ok": True, "kind": "text", "text": " ".join(r["sentence"].replace("\n", " ") for r in rows)[:MAX_TEXT], "refs": refs}
    return {"ok": True, "kind": "numbers", "refs": refs,
            "numbers": [{"label": r["label"], "value": r["value"], "unit": "원", "note": f"{r['at']} 기준" if r["at"] else "", "aliases": r["aliases"]}
                        for r in rows]}


def _live_weather(query: str, view: str) -> dict:
    """날씨: 요청에 나온 곳(없으면 서울)의 지금 · 오늘 · 이번 주 / weather for the place named (Seoul by default): now, today, the week"""
    from app import live_weather, live_widgets
    card, _found = live_weather.get(live_widgets._location_of(query) or live_widgets._area_of(query), 0)  # noqa: SLF001
    f = live_weather.facts(card)
    refs = [{"kind": "web", "label": live_weather.SOURCE["name"], "url": live_weather.SOURCE["url"], "page": None}]
    days = [d for d in f["days"] if d.get("max") is not None]
    if view == "chart" and days:
        return {"ok": True, "kind": "table", "refs": refs,
                "table": {"tool": "inline", "columns": ["날짜", "최고", "최저"], "rows": [[f"{d['date'][5:]}({d['day']})", d["max"], d["min"]] for d in days]}}
    if view == "list" and days:
        return {"ok": True, "kind": "items", "refs": refs,
                "items": [{"title": f"{d['date'][5:]}({d['day']}) {d['sky']}", "sub": f"최고 {d['max']}° · 최저 {d['min']}°"
                           + (f" · 강수 {d['rain_chance']}%" if d.get("rain_chance") is not None else ""), "url": ""} for d in days]}
    if view == "text":
        return {"ok": True, "kind": "text", "text": live_weather.template(card)[:MAX_TEXT], "refs": refs}
    today = days[0] if days else {}
    numbers = [{"label": "지금 기온", "value": f["now"]["temp"], "unit": "°C", "note": f"{f['location']} · {f['now']['sky']}"},
               {"label": "최고", "value": today.get("max"), "unit": "°C", "note": f["location"]},
               {"label": "최저", "value": today.get("min"), "unit": "°C", "note": f["location"]},
               {"label": "강수 확률", "value": today.get("rain_chance"), "unit": "%", "note": f["location"]}]
    numbers = [{**n, "aliases": _WX_ALIASES[n["label"]]} for n in numbers if isinstance(n["value"], (int, float))]
    if not numbers:
        return {"ok": False, "why": "날씨를 받지 못했습니다"}
    return {"ok": True, "kind": "numbers", "numbers": numbers, "refs": refs}


def _branch(src: str, plan: dict, eff: dict | None) -> dict:
    if src == "data":
        return run_data(plan["query"], eff)
    if src == "docs":
        return run_docs(plan["query"], eff, plan["view"], plan["labels"])
    return run_web(plan["query"], plan["view"], plan["labels"])


def _outcome(src: str, fut: cf.Future) -> dict:
    try:
        out = fut.result(timeout=0)
        return out if isinstance(out, dict) else {"ok": False, "why": f"{SOURCE_LABEL[src]}에서 가져오지 못했습니다"}
    except Exception as e:  # noqa: BLE001
        logger.warning("위젯 갈래 %s 실패: %s", src, type(e).__name__)
        return {"ok": False, "why": f"{SOURCE_LABEL[src]}에서 가져오지 못했습니다"}


def bounded(fn, timeout: float):
    """fn() 을 따로 돌려 timeout 초까지만 기다린다(넘으면 TimeoutError, 일은 뒤에서 마친다) / runs fn with a deadline"""
    pool = cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="widget-bounded")
    try:
        return pool.submit(fn).result(timeout=timeout)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def branch_note(src: str, res: dict) -> dict:
    """갈래 결과의 화면용 요약(스트림 branch 이벤트, 2026-11-19 — 위젯 에이전트 대화의 출처 카드 진행 줄): 찾았는가 · 못 찾은 까닭 · 결과 종류 ·
    근거(문서 · 쪽 / 데이터 이름 / 웹 출처) · 표의 행 수 · 사내 데이터의 조회 SQL(서버가 만든 것) · 실시간 출처 여부.
    A branch result summarized for the screen (the stream's branch event, 2026-11-19 — the progress lines of the conversation's
    source cards): found or why not, the result kind, references, the row count, company data's query SQL (server-made) and
    whether a live source answered."""
    out = {"source": src, "label": SOURCE_LABEL[src], "ok": bool(res.get("ok"))}
    if not out["ok"]:
        out["why"] = _txt(res.get("why"), 200) or f"{SOURCE_LABEL[src]}에서 찾지 못했습니다"
        if res.get("skipped"):
            out["skipped"] = True
        return out
    kind = res.get("kind")
    out["kind"] = kind
    out["refs"] = [{"kind": r.get("kind"), "label": _txt(r.get("label"), 120),
                    "page": r["page"] if isinstance(r.get("page"), int) and not isinstance(r.get("page"), bool) else None,
                    "url": r["url"] if str(r.get("url") or "").lower().startswith(("http://", "https://")) else ""}
                   for r in (res.get("refs") or [])[:MAX_REFS] if isinstance(r, dict) and _txt(r.get("label"), 120)]
    if kind == "table":
        table = res.get("table") or {}
        out["rows"] = len(table.get("rows") or [])
        out["columns"] = [str(c)[:40] for c in (table.get("columns") or [])][:MAX_COLUMNS]
    elif kind in ("numbers", "items"):
        out["count"] = len(res.get(kind) or [])
    if src == "data" and isinstance(res.get("sql"), str) and res["sql"].strip():
        out["sql"] = res["sql"].strip()[:4000]
    if res.get("note"):
        out["note"] = _txt(res["note"], 200)
    if res.get("live"):
        out["live"] = True
    return out


CANCEL_POLL = 0.5   # 멈춤을 확인하는 간격(초) / how often a stop is checked (s)


def fetch(request: str, eff: dict | None, view: str | None = None, emit=None, plan: dict | None = None,
          sources: list[str] | None = None, cancel=None) -> dict:
    """의도 판단 → 고른 갈래 바로 실행(여럿이면 동시에) → 계획 순서로 처음 찾은 결과, 사내에서 못 찾고 웹을 고르지 않았으면 웹 한 번 더.
    기한은 갈래 전체에 하나(BRANCH_TIMEOUT)이고, 계획 순서로 결과가 정해지면 남은 갈래를 기다리지 않는다.
    sources = 사용자가 허용한 곳(입력 카드의 [자동 ▾] = 사내 · 외부와 리소스 센터, 2026-11-19): 의도 판단이 고른 곳 중 허용한 곳만(없으면 허용한
    곳 모두, SOURCES 차례로) 찾고 웹으로 넘어가지 않는다. cancel() 이 참이면
    (화면이 멈췄다) 기다리기를 그만두고 Cancelled. emit(kind, data) 로 plan(+ forced) · stage(갈래 시작) · branch(갈래 결과마다,
    branch_note) · picked(쓴 갈래)를 알린다.
    반환: {plan, origin(data | docs | web | None), result, tried: {출처: 못 찾은 까닭}, fetched_at}.
    Intent → run the picked branches at once (concurrently when several) → the first result found in plan order; when the picked
    internal branches found nothing and the web was not picked, one more web search. One deadline covers all branches, and the
    rest are not awaited once plan order decides. sources = places the user allows (the input card's [Auto ▾] = internal or external,
    and the resource center, 2026-11-19): the planned places within them (all of them, in SOURCES order, when the plan picked none)
    are searched, with no fallback to the web. When cancel() is true (the screen stopped) waiting ends with Cancelled.
    emit(kind, data) announces plan (+ forced), stage (a branch starts), branch (each branch result) and picked (the branch used)."""
    stopped = cancel if callable(cancel) else (lambda: False)
    plan = plan or plan_request(request)
    if view in VIEWS:
        plan = {**plan, "view": view, "labels": plan["labels"] if view == "kpi" else []}
    allowed = {x for x in (sources or []) if isinstance(x, str) and x in SOURCES}
    chosen = ([s for s in plan["sources"] if s in allowed] or [s for s in SOURCES if s in allowed]) if allowed else []
    if chosen:
        plan = {**plan, "sources": chosen}
    _emit(emit, "plan", {**plan, "forced": bool(chosen)})
    if stopped():
        raise Cancelled()
    for src in plan["sources"]:
        _emit(emit, "stage", {"source": src, "label": SOURCE_LABEL[src]})
    results: dict[str, dict] = {}

    def record(src: str, res: dict) -> None:
        results[src] = res
        _emit(emit, "branch", branch_note(src, res))

    pool = cf.ThreadPoolExecutor(max_workers=len(plan["sources"]), thread_name_prefix="widget-fetch")
    futures = {src: pool.submit(_branch, src, plan, eff) for src in plan["sources"]}
    deadline = time.monotonic() + BRANCH_TIMEOUT
    timed_out = False
    try:
        while True:
            for src in plan["sources"]:   # 끝난 갈래는 차례와 상관없이 바로 알린다 / finished branches are announced at once, in any order
                if src not in results and futures[src].done():
                    record(src, _outcome(src, futures[src]))
            decided = False
            for src in plan["sources"]:   # 계획 순서: 앞 갈래가 끝나야 뒤 갈래를 쓸 수 있다 / plan order: an earlier branch decides first
                if src not in results:
                    break
                if results[src].get("ok"):
                    decided = True
                    break
            else:
                decided = True   # 모두 끝났다 / every branch is done
            left = deadline - time.monotonic()
            if decided:
                break
            if left <= 0:
                timed_out = True
                break
            if stopped():
                raise Cancelled()
            cf.wait([f for s, f in futures.items() if s not in results], timeout=min(left, CANCEL_POLL), return_when=cf.FIRST_COMPLETED)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)   # 늦은 갈래를 기다리지 않는다 / late branches are not awaited
    for src in plan["sources"]:
        if src not in results:   # 시작도 못 하고 취소된 갈래는 기다리지 않은 것이다 / a branch cancelled before it started was simply not awaited
            record(src, _outcome(src, futures[src]) if futures[src].done() and not futures[src].cancelled()
                   else {"ok": False, "why": f"{SOURCE_LABEL[src]} 응답이 늦어 건너뛰었습니다"} if timed_out
                   else {"ok": False, "why": "다른 곳에서 찾아 기다리지 않았습니다", "skipped": True})
    origin = next((s for s in plan["sources"] if results[s].get("ok")), None)
    if origin is None and "web" not in results and not chosen:   # DB 에 없으면 웹(고른 곳이 있으면 넘어가지 않는다) / not in the DB, so the web (never past a chosen place)
        if stopped():
            raise Cancelled()
        _emit(emit, "stage", {"source": "web", "label": SOURCE_LABEL["web"], "fallback": True})
        try:
            web = bounded(lambda: run_web(plan["query"], plan["view"], plan["labels"]), BRANCH_TIMEOUT)
        except cf.TimeoutError:
            web = {"ok": False, "why": "웹 검색 응답이 늦어 건너뛰었습니다"}
        except Exception as e:  # noqa: BLE001
            logger.warning("위젯 웹 대체 실패: %s", type(e).__name__)
            web = {"ok": False, "why": "웹 검색에 실패했습니다"}
        record("web", web)
        origin = "web" if web.get("ok") else None
    _emit(emit, "picked", {"source": origin})
    return {"plan": plan, "origin": origin, "result": results[origin] if origin else None,
            "tried": {s: r.get("why", "") for s, r in results.items() if not r.get("ok")}, "fetched_at": kst.now_iso()}


# ────────────────────────────────────────────────────────
# 새로 가져오기 / refreshing a saved widget (부분별 / per part)
# ────────────────────────────────────────────────────────

# 출처별로 다시 가져오는 간격(초): 사내 데이터 = 저장된 SQL 을 다시 실행(가벼움), 사내 문서 · 웹 = 그 갈래를 다시(모델 호출)
# how often each origin is fetched again (s): company data re-runs the stored SQL (cheap); documents and the web re-run the branch (model calls)
REFRESH_TTL = {"data": 60, "docs": 6 * 3600, "web": 30 * 60}


def stale(origin: dict | None) -> bool:
    """이 출처를 다시 가져올 때가 됐는가(다시 가져올 수 있고, 가져온 지 REFRESH_TTL 이 지났다) / due for a refresh"""
    if not isinstance(origin, dict) or not hw.refreshable(origin) or origin.get("kind") not in REFRESH_TTL:
        return False
    try:
        at = dt.datetime.fromisoformat(origin.get("fetched_at") or "")
        return (kst.now() - at).total_seconds() >= REFRESH_TTL[origin["kind"]]
    except (ValueError, TypeError):   # 시각을 못 읽으면(형식 · 시간대) 다시 가져온다 — 새 시각이 적힌다 / unreadable time: fetch again
        return True


def due(spec: dict) -> bool:
    """다시 가져올 때가 된 출처가 하나라도 있는가 / is any origin due"""
    return any(stale(o) for o in (spec or {}).get("origins") or [])


def _refetch_table(origin: dict, eff: dict | None) -> tuple[str, dict | None]:
    """사내 데이터: 저장된(서명된) 조회 SQL 을 지금 신원의 권한 · SQL 가드로 다시 실행 → ("ok", 표) · ("denied", None) · ("fail", None)
    company data: re-run the stored (signed) SQL under today's permissions and the SQL guard"""
    sql = origin.get("sql") or ""
    if not sql:
        return "fail", None
    allowed = ra.allowed_tables(eff)
    if eff is not None and (not catalog.domain_readable(eff, "p_data") or not allowed
                            or any(t not in allowed for t in ra.tables_in(sql))):
        return "denied", None
    try:
        from app import analytics   # 무거운 모듈은 쓸 때만 / the heavy module only when used
        analytics.refresh_csv_views()
        columns, rows = analytics.run_select(analytics.guard_sql(sql, allowed), allowed)
    except Exception as e:  # noqa: BLE001
        logger.warning("위젯 사내 데이터 다시 조회 실패: %s", type(e).__name__)
        return "fail", None
    table = table_source(columns, rows)
    return ("ok", table) if table is not None else ("fail", None)


def _rerun(origin: dict, eff: dict | None, view: str, labels: list[str]) -> dict:
    return (run_docs(origin["query"], eff, view, labels) if origin["kind"] == "docs"
            else run_web(origin["query"], view, labels))


def _refresh_part(new: dict, o: dict, eff: dict | None) -> str:
    """출처 하나의 부분만 다시 가져와 new 를 고친다 → "ok" · "denied"(권한이 없어졌다) · "fail"(그대로 둔다)
    refreshes one origin's part in `new` → "ok", "denied" (permission gone) or "fail" (left as it was)"""
    part = o["part"]
    if part == "source":
        current = new.get("source") or {}
        if o["kind"] == "data":
            status, table = _refetch_table(o, eff)
            if status != "ok":
                return status
        else:
            res = _rerun(o, eff, "chart", [])
            if res.get("denied"):
                return "denied"
            if not res.get("ok") or res.get("kind") != "table":
                return "fail"
            t = res["table"]
            table = t if t.get("tool") == "inline" else table_source(t["columns"], t["rows"])
            o["refs"] = res.get("refs") or o["refs"]
        if table is None or table["columns"] != current.get("columns"):
            return "fail"   # 열이 바뀌면 차트 설정이 맞지 않는다 / changed columns no longer fit the chart settings
        new["source"] = table
        return "ok"
    if part == "cards":
        res = _rerun(o, eff, "kpi", [c["key"] for c in o["cards"] if c["key"]])
        if res.get("denied"):
            return "denied"
        if not res.get("ok") or res.get("kind") != "numbers":
            return "fail"
        got = match_numbers([c["key"] for c in o["cards"]], res["numbers"])
        cards = {k["id"]: k for k in new["kpis"]}
        hit = 0
        for i, j in got.items():
            card = cards.get(o["cards"][i]["id"])
            if card is None or card.get("source") or card.get("col"):
                continue   # 없어졌거나 데이터 카드가 됐다 / gone, or turned into a computed card
            n = res["numbers"][j]
            card.pop("pending", None)   # 권한 때문에 감췄던 카드도 다시 채운다 / a card withheld for permissions is filled again
            card.update({"value": n["value"], "unit": n["unit"] or card.get("unit") or "", "note": n["note"] or card.get("note") or ""})
            hit += 1
        o["refs"] = res.get("refs") or o["refs"]
        return "ok" if hit else "fail"
    res = _rerun(o, eff, part, [])
    if res.get("denied"):
        return "denied"
    want = "text" if part == "text" else "items"
    if not res.get("ok") or res.get("kind") != want:
        return "fail"
    block = {"type": "text", "text": res["text"]} if part == "text" else {"type": "list", "items": res["items"]}
    new["blocks"] = [b for b in new["blocks"] if b["type"] != block["type"]] + [block]   # 없으면 더한다 / added when missing
    o["refs"] = res.get("refs") or o["refs"]
    return "ok"


def _withhold(new: dict, o: dict) -> None:
    """권한이 없어진 부분의 내용을 정의에서 뺀다(출처는 남겨 권한이 돌아오면 다시 채운다) — 표는 줄만, 카드는 '데이터 연결 전'으로, 글 · 목록은 칸째.
    Removes a part's content once the permission is gone (the origin stays, so it refills when access returns): table rows,
    cards back to not-connected, text and list blocks."""
    if o["part"] == "source" and new.get("source"):
        new["source"] = {**new["source"], "rows": []}
    elif o["part"] == "cards":
        ids = {c["id"] for c in o["cards"]}
        new["kpis"] = [{"id": k["id"], "label": k["label"], "unit": k.get("unit") or "", "note": k.get("note") or "", "pending": True}
                       if k["id"] in ids else k for k in new["kpis"]]
    else:
        kind = "text" if o["part"] == "text" else "list"
        new["blocks"] = [b for b in new["blocks"] if b["type"] != kind]


def refresh(spec: dict, eff: dict | None, force: bool = False) -> dict | None:
    """저장된 위젯에서 때가 된 출처만 다시 가져와 새 정의를 돌려준다(바뀐 것이 없으면 None — 예전 내용을 그대로 쓴다). 부분마다 따로:
    사내 데이터 표 = 서명된 SQL 을 다시(열이 그대로일 때만), 문서 · 웹 표 · 글 · 목록 = 같은 질의 · 모양으로 그 갈래를 다시, 고정 숫자 카드 =
    가져올 때의 이름(key)으로 숫자를 찾아 그 카드만(못 찾으면 그대로). 권한이 없어졌으면 그 부분의 내용을 뺀다. 차트 설정 · 디자인 · 인사이트
    틀은 그대로라 숫자 · 문장이 새 데이터를 따른다.
    Fetches only the due origins of a saved widget and returns the new definition (None when nothing changed; the old content
    then stays). Per part: the company-data table re-runs its signed SQL (same columns only); document or web tables, texts and
    lists re-run the branch; fixed cards take numbers matched by the name they were fetched under (unmatched cards stay). A part
    whose permission is gone loses its content. Chart settings, design and the insight template stay, so numbers follow."""
    origins = [dict(o, cards=[dict(c) for c in o.get("cards") or []]) for o in (spec or {}).get("origins") or []]
    # force = 위젯 에이전트의 [지금 새로 가져오기](2026-11-19): 때와 상관없이 다시 가져올 수 있는 출처 모두 / every refreshable origin, due or not
    todo = [o for o in origins if ((hw.refreshable(o) and o.get("kind") in REFRESH_TTL) if force else stale(o))]
    if not todo:
        return None
    new = {**spec, "kpis": [dict(k) for k in spec.get("kpis") or []], "blocks": [dict(b) for b in spec.get("blocks") or []], "origins": origins}
    changed = False
    for o in todo:
        try:
            status = _refresh_part(new, o, eff)
        except Exception as e:  # noqa: BLE001 — 한 부분의 실패가 다른 부분을 막지 않는다 / one failed part never blocks the others
            logger.warning("위젯 부분 다시 가져오기 실패: %s", type(e).__name__)
            status = "fail"
        if status == "denied":
            _withhold(new, o)
        if status in ("ok", "denied"):
            o["fetched_at"] = kst.now_iso()
            changed = True
    return new if changed else None
