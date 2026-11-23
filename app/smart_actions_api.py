"""@멘션 도구 API — 능력별 사용 여부 조회/저장 + 대화형 조회·실행.

관리 센터가 정하는 것은 **각 능력을 쓸지 말지**뿐이다. AI 지침(프롬프트)은 응답 형식·필드명·
렌더러와 함께 움직이는 구현 세부라 app/smart_catalog.py 코드에 두고 git으로 관리한다.

엔드포인트: GET(설정+카탈로그) · PUT(사용 여부 저장) · POST /converse(대화형 조회·실행) ·
POST /info(단발 조회) · POST /prefill(폼 자동 작성) · GET /capabilities(능력 안내).
전부 채팅 파이프라인을 타지 않는 독립 경로이며, 서버는 절대 실행하지 않는다 — 실행 준비까지만
만들고 실제 앱 열기는 사용자 확인 뒤 클라이언트가 한다. UI 진입은 목업 showView('permission')의
m_admin 게이트가 담당 — 다른 데모 관리 API와 동일하게 서버측 별도 인증 게이팅은 두지 않는다.
"""
# @-mention tool API — read/save per-capability enabled flags plus conversational reads and actions.
#
# All the admin center decides is **whether each capability is available**. AI guidance (prompts) moves
# in lockstep with the response format, field names, and renderer, so it lives in app/smart_catalog.py
# under git.
#
# Endpoints: GET (config + catalog), PUT (save enabled flags), POST /converse (conversational read/run),
# POST /info (one-shot read), POST /prefill (form autofill), GET /capabilities (capability listing).
# All bypass the chat pipeline, and the server never executes — it only reaches a ready state; the client
# opens the actual app after the user confirms. UI entry is gated by the mockup's showView('permission')
# m_admin check — no extra server-side auth gating, same as the other demo admin APIs.

import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import llm, smart_actions, smart_seed
from app.smart_actions import CONFIG_KEYS, DEFAULTS
from app.smart_catalog import KEY_INDEX, NAMESPACES, NS_ORDER, prompt_of

logger = logging.getLogger("ai365.smart_actions")

router = APIRouter(prefix="/api/smart-actions")


# 프리필 시스템 프롬프트 — 액션 지침(관리 센터 설정)+대화 맥락으로 폼 필드를 JSON으로만 채운다
# Prefill system prompt — fills form fields as JSON only, from the action guide (admin setting) + conversation context
PREFILL_SYSTEM = (
    "너는 사내 업무 실행 폼을 채우는 도우미다. 대화 내용과 액션 지침을 바탕으로 각 필드의 값을 "
    'JSON 객체 하나로만 출력한다. 형식: {"values": {"필드k": "값"}}. '
    "select 필드는 반드시 주어진 옵션 문자열 중 하나를 그대로 쓴다. 알 수 없는 값은 빈 문자열로 둔다. "
    "사람 이름은 대화에 등장한 이름을 그대로 쓰고, 날짜·시간은 한국어 관행(예: 8/7(금) 14:00)으로 쓴다."
)


class SmartActionsIn(BaseModel):
    actions: dict


class PrefillIn(BaseModel):
    action: str
    question: str = ""
    answer: str = ""
    fields: list = []


class InfoIn(BaseModel):
    ns: str
    text: str = ""
    question: str = ""
    answer: str = ""
    key: str = ""   # 조회 key 직접 지정(분류 우회) — 그룹웨어 @도구 패널의 결정론 조회용(2026-08-19)
    # direct info-key dispatch (bypasses _classify) — deterministic reads for the groupware tool panel


class ConverseIn(BaseModel):
    ns: str
    text: str = ""
    # 진행 중인 실행 — {key, values}. 있으면 분류를 건너뛰고 슬롯 채우기를 이어간다.
    # An action in progress — {key, values}. When present, classification is skipped and slot filling continues.
    pending: dict | None = None
    # 폼 스키마는 클라이언트 소유(렌더 관심사)라 /prefill과 같게 요청에 실려 온다.
    # Form schemas are client-owned (a rendering concern), so they ride in the request as with /prefill.
    fields: list = []
    history: list = []


# 조회 서술 — 도구가 돌려준 데이터만 근거로 자연어 답변을 쓴다(카드 대신)
# Info narration — writes a natural-language answer grounded only in what the tool returned (instead of a card)
NARRATE_SYSTEM = (
    "너는 사내 Microsoft 365 도구의 조회 결과를 사용자에게 설명하는 비서다. "
    "주어진 [데이터]에 있는 내용만 근거로 답한다. 데이터에 없는 사실을 지어내지 마라. "
    "사용자가 물어본 것에 먼저 답하고, 필요한 만큼만 항목을 나열한다. "
    "항목을 나열할 때는 '1. **제목** — 보낸사람 · 시각' 처럼 번호와 굵은 글씨를 쓰고, 한 줄 요약을 덧붙인다. "
    "결과가 없으면 없다고 분명히 말한다. 한국어로, 군더더기 없이 답하라."
)

# 실행 대화 — 필요한 값이 다 찰 때까지 되묻고, 다 차면 실행 준비 상태로 넘긴다
# Action dialogue — keeps asking until every required value is filled, then hands off ready-to-run
SLOT_SYSTEM = (
    "너는 사내 업무 실행을 돕는 비서다. 사용자가 하려는 작업에 필요한 값을 대화로 채운다. "
    'JSON 객체 하나로만 답한다. 형식: {"values": {"필드k": "값"}, "message": "사용자에게 할 말"}. '
    "규칙: "
    "(1) 대화에서 알아낼 수 있는 값만 채운다. "
    "(2) **자리표시자를 절대 쓰지 마라.** '[여기에 내용을 작성하세요]', 'OOO', '(미정)' 같은 값은 금지다. "
    "용건·주제를 모르면 그 값을 아예 비우고 message에서 무엇에 대한 것인지 되물어라. "
    "(3) 용건이 파악되면 본문·메시지는 네가 직접 완성된 문장으로 작성한다(되묻지 마라). "
    "(4) 사람 이름은 '김민준'처럼 이름만 쓴다 — '님·씨·책임' 같은 호칭이나 존칭을 붙이지 마라. "
    "쉼표로 구분해 여러 명을 넣을 수 있다. "
    "(5) 필수 값이 다 찼으면 message에 무엇을 실행할지 한 문장으로 요약한다. "
    "(6) 이미 채워진 값은 사용자가 바꾸라고 하지 않는 한 그대로 유지한다."
)

# 자리표시자로 채운 값은 '빈 값'으로 취급 — 안 그러면 미완성 초안이 실행 준비로 넘어간다
# Values filled with placeholders count as empty — otherwise an unfinished draft reaches ready state
PLACEHOLDER_HINTS = ("여기에", "작성해 주세요", "작성하세요", "내용을 입력", "OOO", "XXX",
                     "미정", "TBD", "todo", "[본문", "(본문")


# 능력 질의 판별 — "@mail로 뭐 할 수 있어?" 류는 조회가 아니라 카탈로그 안내로 답한다
# Capability-question detection — "what can @mail do?" is answered from the catalog, not by a lookup
CAPABILITY_PATTERNS = (
    "뭐 할 수", "뭘 할 수", "무엇을 할 수", "뭐 돼", "뭐 되", "기능", "도움말",
    "어떻게 써", "사용법", "what can", "help", "capabilit",
)

# 조회 분류 시스템 프롬프트 — 규칙으로 못 고른 문장만 여기로 온다
# Info-classification system prompt — only sentences the rule pass could not resolve reach here
INFO_SYSTEM = (
    "너는 사내 도구 요청을 분류하는 라우터다. 주어진 능력 목록 중 사용자 요청에 가장 맞는 것 하나를 고르고 "
    '필요한 인자를 추출해 JSON 객체 하나로만 출력한다. 형식: {"key": "능력키", "args": {"인자": "값"}}. '
    "목록에 없는 키를 만들지 마라. 확신이 없으면 목록의 첫 번째 조회 능력을 고른다. "
    "args는 필요한 것만 넣는다: sender(사람 이름) · q(검색어) · path(폴더 경로) · day(오늘=0, 내일=1, 어제=-1) · minutes(분)."
)


def _normalize(actions) -> dict:
    """PUT 본문 검증·정규화 — 도구 5개 키 정확 일치 + 사용 여부만."""
    # Validate/normalize the PUT body — exactly the five tool keys, enabled flag only.
    if not isinstance(actions, dict):
        raise HTTPException(status_code=422, detail="actions는 객체여야 합니다")
    if set(actions.keys()) != set(CONFIG_KEYS):
        missing = sorted(set(CONFIG_KEYS) - set(actions.keys()))
        unknown = sorted(set(actions.keys()) - set(CONFIG_KEYS))
        parts = []
        if missing:
            parts.append("누락: " + ", ".join(missing))
        if unknown:
            parts.append("알 수 없음: " + ", ".join(unknown[:5]) + ("…" if len(unknown) > 5 else ""))
        raise HTTPException(
            status_code=422,
            detail=f"actions에는 도구 키 {len(CONFIG_KEYS)}개가 정확히 있어야 합니다 (" + " / ".join(parts) + ")",
        )
    norm = {}
    for key in CONFIG_KEYS:
        entry = actions.get(key)
        if not isinstance(entry, dict):
            raise HTTPException(status_code=422, detail=f"{key} 항목이 올바르지 않습니다")
        # bool(entry) 대신 `is not False` — 문자열 "false"가 True로 뒤집히던 결함을 막는다
        # `is not False` instead of bool(entry) — guards the defect where the string "false" flipped to True
        norm[key] = {"enabled": entry.get("enabled") is not False}
    return norm


def _ns_enabled(ns: str) -> bool:
    """도구 사용 여부 — 게이팅의 단일 기준."""
    # Whether a tool is available — the single gating criterion.
    cfg = smart_actions.get_config().get(ns)
    return (not isinstance(cfg, dict)) or cfg.get("enabled") is not False


def _catalog_payload() -> list[dict]:
    """관리 센터·멘션 UI가 행을 그리는 데 필요한 메타만 추려 내보낸다(프롬프트는 actions에 있음)."""
    # Ship only the metadata the admin center / mention UI needs to render rows (prompts live in `actions`).
    return [
        {
            "key": k, "ns": v["ns"], "kind": v["kind"], "label": v["label"],
            "desc": v["desc"], "exec": v["exec"], "view": v["view"],
            "examples": list(v.get("examples") or ()),
        }
        for k, v in KEY_INDEX.items()
    ]


@router.get("")
def get_smart_actions() -> dict:
    return {
        "actions": smart_actions.get_config(),
        "defaults": DEFAULTS,
        "catalog": _catalog_payload(),
        "namespaces": [{"ns": n, **NAMESPACES[n]} for n in NS_ORDER],
    }


@router.put("")
def put_smart_actions(body: SmartActionsIn) -> dict:
    norm = _normalize(body.actions)
    smart_actions.put_config(norm)
    return {"ok": True, "actions": norm}


@router.post("/prefill")
def prefill(body: PrefillIn) -> dict:
    """액션 폼 자동 작성 — 경량 LLM 단발 호출(채팅 파이프라인 미경유).

    액션 지침(관리 센터 프롬프트)+해당 답변의 대화 맥락으로 필드 값을 추출한다.
    실패는 오류가 아니라 프리필 생략(수동 입력 폴백)이다."""
    # Auto-fills an action form — single lightweight LLM call (bypasses the chat pipeline).
    # Extracts field values from the action guide (admin prompt) + that reply's conversation
    # context. Failure means "skip prefill" (manual-input fallback), not an error.
    meta = KEY_INDEX.get(body.action)
    if meta is None:
        raise HTTPException(status_code=422, detail="알 수 없는 액션입니다")
    # 프리필은 '폼을 채우는' 동작이라 Action 전용 — 조회(info) 키는 폼이 없어 여기 들어오면 안 된다
    # Prefill fills a form, so it is action-only — info keys have no form and must not reach here
    if meta["kind"] != "action":
        raise HTTPException(status_code=422, detail="조회 항목은 프리필 대상이 아닙니다")
    if not _ns_enabled(meta["ns"]):
        raise HTTPException(status_code=422, detail="사용하지 않는 도구입니다")
    guide = _guide(body.action)
    fields_desc = []
    for f in body.fields[:8]:
        if not isinstance(f, dict) or not f.get("k"):
            continue
        line = f"- {f.get('k')}: {f.get('label', '')}"
        opts = f.get("options")
        if isinstance(opts, list) and opts:
            line += " (옵션 중 택1: " + " | ".join(str(o) for o in opts[:12]) + ")"
        fields_desc.append(line)
    if not fields_desc:
        return {"ok": False, "values": {}}
    prompt = (
        f"[액션 지침]\n{guide}\n\n"
        f"[사용자 질문]\n{(body.question or '')[:1500]}\n\n"
        f"[AI 답변]\n{(body.answer or '')[:2500]}\n\n"
        "[채울 필드]\n" + "\n".join(fields_desc)
        + "\n\n위 대화를 근거로 각 필드 값을 채워 JSON으로만 답하라."
    )
    try:
        # json_mode=True는 이미 파싱된 객체를 반환한다(llm.py generate 계약)
        # json_mode=True returns an already-parsed object (llm.py generate contract)
        data = llm.generate(prompt, system=PREFILL_SYSTEM, json_mode=True, tier="lite")
        if not isinstance(data, dict):
            data = {}
        values = data.get("values")
        if not isinstance(values, dict):
            values = data
        clean = {str(k): str(v).strip() for k, v in values.items()
                 if isinstance(v, (str, int, float)) and str(v).strip()}
        return {"ok": True, "values": clean}
    except Exception as e:  # noqa: BLE001 — LLM 실패는 폴백 처리
        logger.warning("prefill 실패: %s", e)
        return {"ok": False, "values": {}}


# ── @멘션 조회(Info) ──────────────────────────────────────────────────────────
# ── @-mention Info (read) ────────────────────────────────────────────────────

DEMO_USER = "최지우"  # 데모 시연 계정 — '내게 배정된' 같은 1인칭 조회의 기준 / demo persona for first-person queries

# 조회 키 → 시드 접근 함수. args는 규칙 추출 또는 LLM이 채운다.
# Info key -> seed accessor. args come from rule extraction or the LLM.
INFO_DISPATCH = {
    "mail.info.inbox": lambda a: smart_seed.mail_list(),
    "mail.info.unread": lambda a: smart_seed.mail_list(unread_only=True),
    "mail.info.from": lambda a: smart_seed.mail_list(sender=a.get("sender") or ""),
    "mail.info.search": lambda a: smart_seed.mail_list(q=a.get("q") or None),
    "mail.info.detail": lambda a: smart_seed.mail_get(q=a.get("q") or None),
    "mail.info.digest": lambda a: smart_seed.mail_list(),
    "calendar.info.today": lambda a: smart_seed.calendar_list(0, 0),
    "calendar.info.week": lambda a: smart_seed.calendar_list(0, 6),
    "calendar.info.next": lambda a: smart_seed.calendar_next(),
    "calendar.info.range": lambda a: smart_seed.calendar_list(_int(a.get("day"), 0), _int(a.get("day"), 0) + 1),
    "calendar.info.free": lambda a: smart_seed.calendar_free(_int(a.get("day"), 0), _int(a.get("minutes"), 60)),
    "todo.info.list": lambda a: smart_seed.todo_list(status="notStarted"),
    "todo.info.today": lambda a: smart_seed.todo_list(due_within=0),
    "todo.info.overdue": lambda a: smart_seed.todo_list(overdue=True),
    "todo.info.assigned": lambda a: smart_seed.todo_list(status="notStarted", assignee=DEMO_USER),
    "todo.info.completed": lambda a: smart_seed.todo_list(status="completed"),
    "sharepoint.info.recent": lambda a: smart_seed.files_list(),
    "sharepoint.info.search": lambda a: smart_seed.files_list(q=a.get("q") or None),
    "sharepoint.info.browse": lambda a: smart_seed.files_list(path=a.get("path") or None),
    "sharepoint.info.shared": lambda a: smart_seed.files_list(shared_only=True),
}

# 인자가 있어야 의미가 있는 조회 — 규칙으로 인자를 못 뽑으면 LLM에 넘긴다
# Lookups that are meaningless without args — hand off to the LLM when rules extract nothing
NEEDS_ARG = {"mail.info.from": "sender", "mail.info.search": "q",
             "mail.info.detail": "q", "sharepoint.info.search": "q",
             "sharepoint.info.browse": "path"}


def _int(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _enabled_keys(ns: str) -> list[str]:
    """도구가 켜져 있으면 그 도구의 능력 전부, 꺼져 있으면 없음 — 게이팅은 도구 단위다."""
    # All of a tool's capabilities when the tool is on, none when off — gating is per tool.
    if not _ns_enabled(ns):
        return []
    return [k for k, v in KEY_INDEX.items() if v["ns"] == ns]


def _extract_args(key: str, text: str) -> dict:
    """규칙 기반 인자 추출 — 조직도 이름, 검색어, 상대 날짜."""
    # Rule-based arg extraction — org-chart names, search terms, relative dates.
    args: dict = {}
    for name in smart_seed._email_map():
        if name in text and name != DEMO_USER:
            args["sender"] = name
            break
    if "내일" in text:
        args["day"] = 1
    elif "어제" in text:
        args["day"] = -1
    elif "오늘" in text:
        args["day"] = 0
    # 검색어 — 동사·조사류를 걷어낸 뒤 남는 가장 긴 토큰
    # Search term — longest token left after stripping verbs/particles
    stop = ("검색", "찾아", "찾아줘", "보여줘", "보여", "관련", "메일", "문서", "파일",
            "알려줘", "줘", "해줘", "있어", "뭐", "좀", "내", "그", "저")
    toks = [t for t in text.replace("?", " ").replace(",", " ").split()
            if t not in stop and len(t) >= 2 and not t.startswith("@")]
    toks = [t for t in toks if not any(s in t for s in ("보여", "찾아", "알려"))]
    if toks:
        args["q"] = max(toks, key=len)
    return args


def _classify(ns: str, text: str) -> tuple[str | None, dict, str]:
    """능력 키 판별 — 규칙 우선, 미해결 시에만 경량 LLM. 반환: (key, args, how)."""
    # Resolve the capability key — rules first, lightweight LLM only when unresolved. Returns (key, args, how).
    allowed = _enabled_keys(ns)
    if not allowed:
        return None, {}, "none"
    low = text.lower()
    # 가장 **구체적인**(= 가장 긴) 키워드가 이긴다. 카탈로그 순서에 기대면 '일정 잡아줘'가
    # 넓은 키워드 '일정'에, '빈 시간'이 '오늘'에 먼저 걸린다. 동점은 카탈로그 순서로 정리.
    # The most *specific* (longest) keyword wins. Relying on catalog order lets "일정 잡아줘" match the
    # broad "일정" and "빈 시간" match "오늘" first. Ties fall back to catalog order.
    best, best_score = None, 0
    for key in allowed:
        hit = max((len(m) for m in KEY_INDEX[key].get("match", ()) if m.lower() in low), default=0)
        if hit > best_score:
            best, best_score = key, hit
    if best:
        args = _extract_args(best, text)
        need = NEEDS_ARG.get(best)
        # 인자가 비면 규칙 판정을 버리고 LLM으로 / drop the rule hit and ask the LLM
        if not (need and not args.get(need)):
            return best, args, "rule"
    lines = [f"- {k}: {KEY_INDEX[k]['label']} — {KEY_INDEX[k]['desc']}" for k in allowed]
    prompt = f"[사용자 요청]\n{text[:500]}\n\n[선택 가능한 능력]\n" + "\n".join(lines)
    try:
        data = llm.generate(prompt, system=INFO_SYSTEM, json_mode=True, tier="lite")
        key = (data or {}).get("key")
        if key in allowed:
            args = (data or {}).get("args")
            return key, (args if isinstance(args, dict) else {}), "llm"
    except Exception as e:  # noqa: BLE001 — 분류 실패는 기본 조회로 폴백
        logger.warning("info 분류 실패: %s", e)
    infos = [k for k in allowed if KEY_INDEX[k]["kind"] == "info"]
    return (infos[0] if infos else None), _extract_args("", text), "fallback"


def _capability_payload(ns: str) -> dict:
    """능력 안내 — 카탈로그 문자열을 그대로 내보낸다(LLM 미사용, 환각 0)."""
    # Capability listing — catalog strings verbatim (no LLM, zero hallucination).
    allowed = set(_enabled_keys(ns))
    meta = NAMESPACES[ns]

    def rows(kind: str) -> list[dict]:
        return [
            {"key": k, "label": KEY_INDEX[k]["label"], "desc": KEY_INDEX[k]["desc"],
             "examples": list(KEY_INDEX[k].get("examples") or ())}
            for k in KEY_INDEX if KEY_INDEX[k]["ns"] == ns and KEY_INDEX[k]["kind"] == kind and k in allowed
        ]

    return {
        "ok": True, "kind": "capability", "ns": ns, "label": meta["label"],
        "action": rows("action"), "info": rows("info"),
        "limits": meta["limits"], "app_url": meta["app_url"],
    }


def _summarize(key: str, items) -> str:
    """결과 한 줄 요약 — 기본은 템플릿, narrate 키만 경량 LLM."""
    # One-line result summary — template by default; only narrate keys use the lightweight LLM.
    meta = KEY_INDEX[key]
    n = len(items) if isinstance(items, list) else (0 if items is None else 1)
    if not n:
        return f"{meta['label']}에 해당하는 항목이 없습니다."
    if meta.get("narrate"):
        try:
            lines = [f"- {i.get('subject') or i.get('title') or i.get('name')}: "
                     f"{i.get('bodyPreview') or i.get('lastMessage') or ''}" for i in items[:8]]
            out = llm.generate("[지침]\n" + _guide(key) + "\n\n[항목]\n" + "\n".join(lines)
                               + "\n\n위 항목을 3줄 이내 한국어로 요약하라. JSON이 아닌 평문으로 답하라.",
                               tier="lite")
            if isinstance(out, str) and out.strip():
                return out.strip()
        except Exception as e:  # noqa: BLE001 — 요약 실패는 템플릿으로 폴백
            logger.warning("info 요약 실패: %s", e)
    return f"{meta['label']} {n}건입니다."


def _guide(key: str) -> str:
    """능력별 AI 지침 — 코드(smart_catalog)가 단일 출처. 조회는 서술 방침, 실행은 작성 방침."""
    # The capability's AI guidance — single-sourced from code (smart_catalog).
    # Narration policy for reads, drafting policy for actions.
    return prompt_of(key).strip()


def _hist_text(history, limit: int = 6) -> str:
    lines = []
    for h in (history or [])[-limit:]:
        if not isinstance(h, dict):
            continue
        who = "사용자" if h.get("role") == "user" else "비서"
        lines.append(f"{who}: {str(h.get('content') or '')[:400]}")
    return "\n".join(lines)


def _narrate(key: str, question: str, items, history) -> str:
    """조회 결과를 자연어로 서술 — 고정 카드 대신 사용자가 물은 것에 맞춰 답한다."""
    # Narrate read results — answering what was actually asked instead of rendering a fixed card.
    meta = KEY_INDEX[key]
    if not items:
        return f"{meta['label']}에 해당하는 항목이 없습니다."
    prompt = (
        f"[사용자 질문]\n{question}\n\n"
        + (f"[이전 대화]\n{_hist_text(history)}\n\n" if history else "")
        + f"[조회한 능력]\n{meta['label']} — {meta['desc']}\n\n"
        f"[서술 지침]\n{_guide(key)}\n\n"
        f"[데이터]\n{json.dumps(items[:12], ensure_ascii=False)}\n\n"
        "위 데이터만 근거로 사용자 질문에 답하라."
    )
    try:
        out = llm.generate(prompt, system=NARRATE_SYSTEM, tier="main")
        if isinstance(out, str) and out.strip():
            return out.strip()
    except Exception as e:  # noqa: BLE001 — 서술 실패는 템플릿으로 폴백
        logger.warning("서술 실패(%s): %s", key, e)
    return f"{meta['label']} {len(items)}건입니다."


def _slot_fill(key: str, values: dict, fields: list, text: str, history) -> dict:
    """실행에 필요한 값을 대화로 채운다 — 부족하면 되묻고(ask), 다 차면 실행 준비(ready)."""
    # Fill the values an action needs through conversation — ask while incomplete, ready when full.
    meta = KEY_INDEX[key]
    spec, required = [], []
    for f in fields[:10]:
        if not isinstance(f, dict) or not f.get("k"):
            continue
        line = f"- {f['k']}: {f.get('label', '')}" + ("" if f.get("req") else " (선택)")
        opts = f.get("options")
        if isinstance(opts, list) and opts:
            line += " (옵션 중 택1: " + " | ".join(str(o) for o in opts[:12]) + ")"
        spec.append(line)
        if f.get("req"):
            required.append(f["k"])
    prompt = (
        f"[하려는 작업]\n{meta['label']} — {meta['desc']}\n\n"
        f"[작성 지침]\n{_guide(key)}\n\n"
        + (f"[이전 대화]\n{_hist_text(history)}\n\n" if history else "")
        + f"[사용자의 새 요청]\n{text}\n\n"
        f"[이미 채워진 값]\n{json.dumps(values, ensure_ascii=False)}\n\n"
        "[채워야 할 값]\n" + "\n".join(spec)
        + "\n\n값을 채우고, 아직 알 수 없는 필수 값이 있으면 되물어라."
    )
    msg = ""
    try:
        data = llm.generate(prompt, system=SLOT_SYSTEM, json_mode=True, tier="main")
        if isinstance(data, dict):
            got = data.get("values")
            if isinstance(got, dict):
                for k, v in got.items():
                    if not isinstance(v, (str, int, float)):
                        continue
                    sv = str(v).strip()
                    if not sv:
                        continue
                    # 자리표시자는 버린다 — 미완성 초안이 '실행 준비'로 넘어가는 걸 막는다
                    # Drop placeholders so an unfinished draft never reaches the ready state
                    if any(h.lower() in sv.lower() for h in PLACEHOLDER_HINTS):
                        values.pop(str(k), None)
                        continue
                    values[str(k)] = sv
            msg = str(data.get("message") or "").strip()
    except Exception as e:  # noqa: BLE001 — LLM 실패는 수동 되묻기로 폴백
        logger.warning("슬롯 채우기 실패(%s): %s", key, e)
    missing = [k for k in required if not values.get(k)]
    if missing:
        labels = {f["k"]: f.get("label", f["k"]) for f in fields if isinstance(f, dict) and f.get("k")}
        return {
            "ok": True, "kind": "ask", "key": key, "label": meta["label"],
            "values": values, "missing": missing,
            "text": msg or ("이어서 진행하려면 " + ", ".join(labels.get(m, m) for m in missing) + "을(를) 알려주세요."),
        }
    return {
        "ok": True, "kind": "ready", "key": key, "label": meta["label"],
        "values": values, "missing": [],
        "text": msg or f"{meta['label']}을(를) 실행할 준비가 되었습니다. 내용을 확인해 주세요.",
    }


@router.post("/converse")
def converse(body: ConverseIn) -> dict:
    """@멘션 대화 — 조회는 자연어로 답하고, 실행은 값이 다 찰 때까지 되물으며 이어간다.

    채팅 파이프라인 미경유(/prefill·/info와 같은 계약). 서버는 절대 실행하지 않는다 —
    kind='ready'까지만 만들고 실제 앱 열기는 클라이언트가 사용자 확인 뒤에 한다."""
    # @-mention dialogue — reads answer in natural language; actions keep asking until every value is filled.
    # Bypasses the chat pipeline (same contract as /prefill and /info). The server never executes: it only
    # reaches kind='ready', and the client opens the app after the user confirms.
    ns = body.ns
    if ns not in NAMESPACES:
        raise HTTPException(status_code=422, detail="알 수 없는 도구입니다")
    meta_ns = NAMESPACES[ns]
    text = (body.text or "").strip()

    # 진행 중인 실행이 있으면 분류를 건너뛰고 그 작업을 이어간다 — @를 다시 칠 필요가 없다
    # With an action in progress, skip classification and continue it — no need to retype @
    pend = body.pending if isinstance(body.pending, dict) else None
    if pend and pend.get("key") in KEY_INDEX and KEY_INDEX[pend["key"]]["kind"] == "action":
        vals = pend.get("values")
        return _slot_fill(pend["key"], dict(vals) if isinstance(vals, dict) else {},
                          body.fields, text, body.history)

    if not text or any(p in text.lower() for p in CAPABILITY_PATTERNS):
        cap = _capability_payload(ns)
        acts = ", ".join(r["label"] for r in cap["action"]) or "없음"
        infos = ", ".join(r["label"] for r in cap["info"]) or "없음"
        cap["text"] = (f"**{cap['label']}**에서 할 수 있는 일입니다.\n\n"
                       f"**실행**: {acts}\n**조회**: {infos}"
                       + (f"\n\n{cap['limits']}" if cap["limits"] else ""))
        return cap

    key, args, how = _classify(ns, text)
    if not key:
        return {"ok": False, "kind": "unsupported", "ns": ns,
                "text": f"{meta_ns['label']}에서 사용할 수 있는 기능이 없습니다. 관리 센터에서 사용 여부를 확인해 주세요.",
                "app_url": meta_ns["app_url"]}
    meta = KEY_INDEX[key]
    if meta["kind"] == "action":
        out = _slot_fill(key, {}, body.fields, text, body.history)
        out["ns"] = ns
        out["how"] = how
        return out
    try:
        result = INFO_DISPATCH[key](args)
    except Exception as e:  # noqa: BLE001 — 조회 실패는 빈 결과로 안내
        logger.warning("converse 조회 실패(%s): %s", key, e)
        result = None
    items = result if isinstance(result, list) else ([] if result is None else [result])
    return {
        "ok": True, "kind": "answer", "ns": ns, "key": key, "how": how,
        "label": meta["label"], "items": items,
        "text": _narrate(key, text, items, body.history),
        "app_url": meta_ns["app_url"], "source": "seed",
    }


@router.get("/capabilities")
def capabilities(ns: str) -> dict:
    if ns not in NAMESPACES:
        raise HTTPException(status_code=422, detail="알 수 없는 도구입니다")
    return _capability_payload(ns)


@router.post("/info")
def info(body: InfoIn) -> dict:
    """@멘션 조회 처리 — 규칙/경량 LLM으로 능력을 고르고 시드에서 결과를 만든다.

    채팅 파이프라인을 타지 않는 독립 경로다(/prefill과 같은 계약). 실행(Action)으로 판정되면
    결과 대신 kind='action'을 돌려주고, 폼 작성은 클라이언트 모달이 이어받는다."""
    # Handles @-mention reads — picks a capability by rule/lightweight LLM and builds results from the seed.
    # Independent of the chat pipeline (same contract as /prefill). If it resolves to an Action, returns
    # kind='action' instead of results and the client modal takes over the form.
    ns = body.ns
    if ns not in NAMESPACES:
        raise HTTPException(status_code=422, detail="알 수 없는 도구입니다")
    text = (body.text or "").strip()
    meta_ns = NAMESPACES[ns]
    # key 직접 지정(그룹웨어 @도구 패널) — 분류를 건너뛰고 결정론 조회. 조회(info) 키만 허용.
    # Direct key dispatch (groupware tool panel) — deterministic read, no classification. Info keys only.
    if body.key:
        meta_d = KEY_INDEX.get(body.key)
        if meta_d is None or meta_d["ns"] != ns or meta_d["kind"] != "info":
            raise HTTPException(status_code=422, detail="지정할 수 없는 조회 키입니다")
        if not _ns_enabled(ns):
            return {"ok": False, "kind": "disabled", "ns": ns,
                    "message": f"{meta_ns['label']} 도구가 꺼져 있습니다. 리소스 관리에서 켤 수 있습니다.",
                    "app_url": meta_ns["app_url"]}
        try:
            result = INFO_DISPATCH[body.key]({})
        except Exception as e:  # noqa: BLE001 — 조회 실패는 빈 결과로 안내
            logger.warning("info 직접 조회 실패(%s): %s", body.key, e)
            result = None
        items = result if isinstance(result, list) else ([] if result is None else [result])
        return {"ok": True, "kind": "info", "ns": ns, "key": body.key, "how": "direct",
                "label": meta_d["label"], "view": meta_d["view"], "items": items,
                "summary": _summarize(body.key, items),
                "app_url": meta_ns["app_url"], "limits": meta_ns["limits"], "source": "seed"}
    if not text or any(p in text.lower() for p in CAPABILITY_PATTERNS):
        return _capability_payload(ns)
    key, args, how = _classify(ns, text)
    if not key:
        return {"ok": False, "kind": "unsupported", "ns": ns,
                "message": f"{meta_ns['label']}에서 사용할 수 있는 기능이 없습니다. 관리 센터에서 사용 여부를 확인해 주세요.",
                "app_url": meta_ns["app_url"]}
    meta = KEY_INDEX[key]
    if meta["kind"] == "action":
        # 실행은 서버가 대신하지 않는다 — 폼·확인 화면은 클라이언트 모달의 몫
        # The server never executes — the form and confirmation screen belong to the client modal
        return {"ok": True, "kind": "action", "ns": ns, "key": key,
                "label": meta["label"], "args": args, "how": how}
    try:
        result = INFO_DISPATCH[key](args)
    except Exception as e:  # noqa: BLE001 — 조회 실패는 빈 결과로 안내
        logger.warning("info 조회 실패(%s): %s", key, e)
        result = None
    items = result if isinstance(result, list) else ([] if result is None else [result])
    return {
        "ok": True, "kind": "info", "ns": ns, "key": key, "how": how,
        "label": meta["label"], "view": meta["view"], "items": items,
        "summary": _summarize(key, items),
        "app_url": meta_ns["app_url"], "limits": meta_ns["limits"],
        "source": "seed",
    }
