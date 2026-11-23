"""그룹웨어 에이전트 — 위젯 설정(9키 on/off) + 위젯 정보 조회.

위젯 9키 {enabled}를 SQLite 단일행 JSON blob으로 영속화한다(app/smart_actions.py와 동일 패턴).
조회(classify+answer)는 스마트 파일로 그룹웨어 에이전트를 켠 채팅에서 클라이언트가 호출하거나,
자동 의도판단 파이프라인이 라우팅한 그룹웨어 에이전트(app/agents/groupware.py)가 재사용한다
(2026-08-27 자동 라우팅 편입 — 종전 "명시적 라우팅이 있어야만 호출" 결정을 갱신. 이 모듈의
분류·응답 함수 자체는 그대로이며, 자동 경로는 app/agents/groupware.py가 대상만 특정해 재사용한다).

위젯 off의 의미(사용자 확정): **이 API의 조회만 차단**한다. 홈(Groupware Agent) 화면의 위젯
표시는 건드리지 않고, 전역 @ 도구도 꺼지지 않는다 — 'actions' 위젯 off는 그룹웨어 경유의
액션 능력 안내만 막는다.

분류는 규칙 우선 최장일치(@멘션 분류기와 동일 철학, LLM 0회). 무매칭이면 kind='pass'로
반환해 클라이언트가 기존 파이프라인에 그대로 넘긴다(그룹웨어는 얹히는 기능 — 대체가 아님).
"""
# Groupware agent — widget settings (9 on/off keys) + widget info queries.
#
# The nine widget keys persist as {enabled} in a single-row SQLite JSON blob (same pattern as
# app/smart_actions.py). Queries (classify + answer) are called by the client when the chat has the
# groupware agent switched on via smart files, and are also reused by the groupware agent that the
# auto intent pipeline routes to (app/agents/groupware.py). (2026-08-27 auto-routing integration —
# updating the earlier "explicit routing only" decision. The classify/answer functions here are
# unchanged; the auto path in app/agents/groupware.py only resolves targets and reuses them.)
#
# Widget off means (user decision): only this API's queries are blocked. The home (Groupware Agent)
# screen keeps showing its widgets, and the global @ tools stay on — 'actions' off only silences the
# groupware-side capability answer.
#
# Classification is rule-first longest-match (same philosophy as the @-mention classifier, zero LLM
# calls). No match returns kind='pass' so the client hands the message to the normal pipeline
# (groupware is additive, not a replacement).

import json
import re
import sqlite3
import time
import urllib.request

from app import access, db, kst, smart_actions
from app.db import DB_PATH
from app.smart_catalog import NAMESPACES

__all__ = ["WIDGET_KEYS", "WIDGET_LABELS", "DEFAULTS", "init_groupware", "get_widgets", "put_widgets", "query"]

# 순서 = 설정 화면 표시 순서(사용자 제시 순서 그대로)
# Order = display order in the settings pane (exactly as the user listed them)
WIDGET_KEYS = ["actions", "weather", "org", "collections", "recent", "usage", "news", "alerts", "bi"]
WIDGET_LABELS = {
    "actions": "액션 버튼",
    "weather": "날씨",
    "org": "조직도",
    "collections": "컬렉션",
    "recent": "최근 대화",
    "usage": "사용 현황",
    "news": "오늘의 뉴스",
    "alerts": "새 소식",
    "bi": "BI 하이라이트",
}
DEFAULTS = {k: {"enabled": True} for k in WIDGET_KEYS}


def _now() -> str:
    return kst.now_iso()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _write(data: dict) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO groupware_widgets(id, data, updated) VALUES(1, ?, ?)",
            (json.dumps(data, ensure_ascii=False), _now()),
        )


def init_groupware() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS groupware_widgets(
              id INTEGER PRIMARY KEY CHECK(id = 1),
              data TEXT NOT NULL,
              updated TEXT NOT NULL
            )
            """
        )
        row = conn.execute("SELECT data FROM groupware_widgets WHERE id = 1").fetchone()
    if not row:
        _write(DEFAULTS)
        return
    try:
        data = json.loads(row["data"])
    except ValueError:
        data = {}
    # 키 결손·과잉을 기본값 기준으로 정합(부분 손상 자가 치유, 멱등)
    # Reconcile missing/extra keys against defaults (self-heals partial damage, idempotent)
    if not isinstance(data, dict):
        data = {}
    out = {k: {"enabled": (not isinstance(data.get(k), dict)) or (data[k].get("enabled") is not False)}
           for k in WIDGET_KEYS}
    if out != data:
        _write(out)


def get_widgets() -> dict:
    with _conn() as conn:
        row = conn.execute("SELECT data FROM groupware_widgets WHERE id = 1").fetchone()
    if not row:
        return json.loads(json.dumps(DEFAULTS, ensure_ascii=False))
    return json.loads(row["data"])


def put_widgets(widgets: dict) -> dict:
    _write(widgets)
    return widgets


def _enabled(cfg: dict, key: str) -> bool:
    v = cfg.get(key)
    return (not isinstance(v, dict)) or (v.get("enabled") is not False)


# ── 분류: 규칙 우선 최장일치 ─────────────────────────────────────────
# ── Classification: rule-first longest match ─────────────────────────
# 정밀도 우선(적대적 리뷰 반영): 못 잡으면 pass가 정답이다 — 파이프라인이 받는다.
# 그래서 지식/데이터/리포트 질문에 흔히 섞이는 광폭 명사('부서'·'공지'·'알림'·'폭염'·
# '대시보드'·'하이라이트'·'할 수 있어' 등)는 넣지 않는다. 'bi'는 영문 2글자라 부분문자열이면
# mobile/BigQuery까지 오탐하므로 단어 경계 정규식으로만 잡는다.
# Precision first (from the adversarial review): an unmatched query passing to the pipeline is
# the correct outcome. Broad nouns that routinely appear inside knowledge/data/report questions
# ('부서', '공지', '알림', '폭염', '대시보드', '하이라이트', '할 수 있어', ...) are deliberately
# excluded. 'bi' is two Latin letters — substring matching would hit mobile/BigQuery, so it is
# matched only with word boundaries.
_MATCH = {
    "weather": ("날씨", "기온", "미세먼지", "우산"),
    "org": ("조직도", "연락처", "구성원", "재직", "몇 명", "몇명"),
    "collections": ("컬렉션",),
    "recent": ("최근 대화", "최근 채팅", "지난 대화", "이전 대화"),
    "usage": ("사용 현황", "크레딧", "토큰 사용"),
    "news": ("뉴스",),
    "alerts": ("새 소식", "새소식"),
    "bi": ("대시보드 목록", "대시보드 보여"),
    "actions": ("뭐 할 수", "뭘 할 수", "무엇을 할", "어떤 기능", "기능이 뭐", "액션 목록", "액션 모드"),
}
_BI_RE = re.compile(r"(?<![a-z0-9])bi(?![a-z0-9])")


def _classify(text: str) -> str | None:
    low = text.lower()
    best, best_len = None, 0
    for key, kws in _MATCH.items():
        for kw in kws:
            if kw in low and len(kw) > best_len:
                best, best_len = key, len(kw)
    if best is None and _BI_RE.search(low):
        return "bi"
    return best


# ── 위젯별 응답 ──────────────────────────────────────────────────────
# ── Per-widget answers ───────────────────────────────────────────────
_WMO = {0: "맑음", 1: "대체로 맑음", 2: "구름 조금", 3: "흐림", 45: "안개", 48: "안개",
        51: "이슬비", 53: "이슬비", 55: "이슬비", 61: "비", 63: "비", 65: "강한 비",
        71: "눈", 73: "눈", 75: "폭설", 80: "소나기", 81: "소나기", 82: "강한 소나기",
        95: "뇌우", 96: "뇌우", 99: "뇌우"}
_wx_cache: dict = {"at": 0.0, "data": None}


def _weather() -> dict:
    """서울 현재 날씨 — Open-Meteo(무키), 10분 캐시, 실패 시 시드 폴백(홈 위젯과 동일 정책)."""
    # Current Seoul weather — Open-Meteo (keyless), 10-min cache, seed fallback on failure
    # (same policy as the home widget).
    if _wx_cache["data"] and time.time() - _wx_cache["at"] < 600:
        return _wx_cache["data"]
    try:
        url = ("https://api.open-meteo.com/v1/forecast?latitude=37.57&longitude=126.98"
               "&current=temperature_2m,weather_code"
               "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
               "&timezone=Asia%2FSeoul&forecast_days=1")
        with urllib.request.urlopen(url, timeout=3) as r:
            j = json.loads(r.read())
        cur, day = j["current"], j["daily"]
        out = {"temp": round(cur["temperature_2m"]), "desc": _WMO.get(cur["weather_code"], "흐림"),
               "hi": round(day["temperature_2m_max"][0]), "lo": round(day["temperature_2m_min"][0]),
               "rain": day["precipitation_probability_max"][0], "source": "live"}
    except Exception:
        out = {"temp": 31, "desc": "맑음", "hi": 33, "lo": 26, "rain": 10, "source": "seed"}
    _wx_cache.update(at=time.time(), data=out)
    return out


# 뉴스·새 소식은 실 소스가 없어 시드 유지(2026-08-27 위젯 현실화 시 확인 — 컬렉션·BI는 실 스토어로 전환).
# News/alerts have no real store, so they stay seeded (verified 2026-08-27; collections/BI moved to real stores).
_NEWS = [
    {"tag": "경제", "title": "반도체 수출 3개월 연속 증가 — 3분기 전망 상향 조정"},
    {"tag": "IT", "title": "국내 기업 AI 도입률 60% 돌파, 업무 자동화 확산 가속"},
    {"tag": "사회", "title": "전국 폭염 특보 지속 — 전력 수요 사상 최고치 경신"},
]
_ALERTS = [
    {"title": "인사 규정 v3 문서가 업데이트됐어요", "ago": "2시간 전"},
    {"title": "영업 그룹에 새 BI '분기 판매 대시보드' 추가", "ago": "어제"},
    {"title": "재무 그룹 게시판에 새 리포트 1건", "ago": "어제"},
]


def _ans_weather() -> dict:
    w = _weather()
    text = (f"현재 서울은 {w['desc']}, {w['temp']}°C입니다. 오늘 최고 {w['hi']}° · 최저 {w['lo']}°, "
            f"강수 확률은 {w['rain']}%입니다.")
    if w["source"] == "seed":
        text += " (예시 데이터 — 날씨 서비스에 연결하지 못했습니다)"
    return {"text": text, "items": []}


def _ans_org(text: str) -> dict:
    members = access.list_members()
    active = [m for m in members if m.get("status") != "퇴직"]
    named = [m for m in active if m.get("name") and m["name"] in text]
    if named:
        items = [{"t": m["name"], "s": f"{m.get('dept', '')} · {m.get('grade', '') or m.get('role', '')} · {m.get('email', '')}"}
                 for m in named[:5]]
        return {"text": f"조직도에서 {len(named)}명을 찾았습니다.", "items": items}
    by_dept: dict = {}
    for m in active:
        by_dept[m.get("dept", "기타")] = by_dept.get(m.get("dept", "기타"), 0) + 1
    top = sorted(by_dept.items(), key=lambda x: -x[1])[:8]
    items = [{"t": d, "s": f"{c}명"} for d, c in top]
    return {"text": f"현재 재직 구성원은 총 {len(active)}명, 부서는 {len(by_dept)}개입니다. 인원이 많은 부서 순으로 보여드릴게요.",
            "items": items}


def _ans_collections() -> dict:
    # 실 컬렉션 스토어 연결(2026-08-27) — 하드코딩 시드 대신 collections_store 사용
    # Wired to the real collections store (2026-08-27) — uses collections_store instead of a hardcoded seed
    from app import collections_store   # 지연 임포트 / lazy
    cols = collections_store.list_collections()
    if not cols:
        return {"text": "아직 컬렉션이 없습니다.", "items": []}
    items = [{"t": c["name"], "s": (f"파일 {len(c.get('files') or [])}개 · {c.get('time_label') or ''}").rstrip(" ·")}
             for c in cols[:8]]
    return {"text": f"컬렉션은 {len(cols)}개가 있습니다.", "items": items}


def _ans_recent() -> dict:
    chats = db.list_chats()
    latest = list(reversed(chats))[:5]
    if not latest:
        return {"text": "아직 저장된 대화가 없습니다.", "items": []}
    return {"text": f"최근 대화 {len(latest)}건입니다.",
            "items": [{"t": c.get("title") or "(제목 없음)", "s": ""} for c in latest]}


def _ans_usage() -> dict:
    total = len(db.list_chats())
    items = [
        {"t": "내가 쓴 크레딧", "s": "12,400 / 30,000 (41%)"},
        {"t": "부서(인사총무) 크레딧", "s": "84,200 / 200,000 (42%)"},
        {"t": "저장된 대화", "s": f"{total}건"},
    ]
    return {"text": "이번 달 사용 현황입니다. 한도는 관리 센터 › 토큰 설정 기준입니다.", "items": items}


def _ans_news() -> dict:
    return {"text": "오늘의 주요 뉴스입니다.",
            "items": [{"t": n["title"], "s": n["tag"]} for n in _NEWS]}


def _ans_alerts() -> dict:
    return {"text": "내 권한 범위의 새 소식입니다.",
            "items": [{"t": a["title"], "s": a["ago"]} for a in _ALERTS]}


def _ans_bi() -> dict:
    # 실 BI 레지스트리 연결(2026-08-27) — catalog.DATA_BI(4개). 위젯 빌더는 eff 미수용이라
    # 권한 스코프 없이 전체 표시(기본 위젯 성격상 허용).
    # Wired to the real BI registry (2026-08-27) — catalog.DATA_BI. The widget builder takes no eff,
    # so it lists all dashboards without permission scoping (acceptable for a base widget).
    from app import catalog   # 지연 임포트 / lazy
    bis = catalog.DATA_BI
    items = [{"t": label, "s": "Power BI"} for (_node, label, _file) in bis]
    return {"text": f"열람 가능한 Power BI 대시보드는 {len(bis)}개입니다. "
                    "리소스 센터 › 데이터 분석 › BI 대시보드에서 열 수 있습니다.",
            "items": items}


def _ans_actions() -> dict:
    cfg = smart_actions.get_config()
    labels = {ns: meta["label"] for ns, meta in NAMESPACES.items()}   # NAMESPACES는 dict {ns: 메타}
    on = [ns for ns in labels if _enabled(cfg, ns)]
    if not on:
        return {"text": "지금 켜져 있는 M365 도구가 없습니다. 리소스 관리의 그룹웨어 에이전트 › 액션에서 켤 수 있습니다.",
                "items": []}
    items = [{"t": f"@{ns}", "s": labels[ns]} for ns in on]
    return {"text": f"사용할 수 있는 M365 도구는 {len(on)}개입니다. 입력창에 @도구명을 붙여 조회하거나 실행할 수 있어요.",
            "items": items}


_ANSWERS = {
    "weather": lambda text: _ans_weather(),
    "org": _ans_org,
    "collections": lambda text: _ans_collections(),
    "recent": lambda text: _ans_recent(),
    "usage": lambda text: _ans_usage(),
    "news": lambda text: _ans_news(),
    "alerts": lambda text: _ans_alerts(),
    "bi": lambda text: _ans_bi(),
    "actions": lambda text: _ans_actions(),
}


def query(text: str) -> dict:
    """위젯 질의 응답. 반환 kind: 'answer'(조회 성공) | 'off'(위젯 꺼짐) | 'pass'(그룹웨어 소관 아님)."""
    # Widget query. kind: 'answer' (served) | 'off' (widget disabled) | 'pass' (not groupware's business).
    key = _classify(text or "")
    if not key:
        return {"kind": "pass"}
    cfg = get_widgets()
    label = WIDGET_LABELS[key]
    if not _enabled(cfg, key):
        return {"kind": "off", "widget": key, "label": label,
                "text": f"'{label}' 위젯이 꺼져 있어 조회할 수 없습니다. "
                        "리소스 관리 › 업무 자동화 › 그룹웨어 에이전트의 위젯 설정에서 켤 수 있습니다."}
    ans = _ANSWERS[key](text)
    return {"kind": "answer", "widget": key, "label": label, **ans}
