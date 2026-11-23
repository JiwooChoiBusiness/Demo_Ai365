"""그룹웨어 Agent — 사내 M365 가상 API(Outlook 메일·캘린더·To Do·SharePoint + 위젯) 조회.

자동 의도판단(app/pipeline.py)이 라우팅하는 4번째 에이전트다(2026-08-27 사용자 확정 — 종전
groupware.py의 "명시적 라우팅이 있어야만 호출" 결정을 자동 라우팅 편입으로 갱신). Gmail 실연동이
아니라 **우리 가상 API**(smart_seed 시드 + 위젯 9종)에 맥락에 맞게 연결되는 에이전트다. 조회가 기본이며,
실행 요청(일정·회의 생성·할 일 완료/추가·메일 작성)은 extras.action_draft로만 내보내
파이프라인 confirm 카드 → POST /api/actions/{id}/confirm 경유로만 수행된다(자동 실행 없음, 2026-08-27 추가).
실행은 smart_seed 뮤테이터로 실제 상태를 바꾸며 세션 내 지속된다(서버 재시작 시 초기화).

권한: 그룹웨어는 SaaS 기본 패키지로 **기본 제공**(2026-08-24 사용자 확정 — 설정에서 막지 않음).
eff 게이트 없이 답하며, 스마트 실행 설정의 도구별 on/off만 존중한다(_run_groupware_node 경유).

실행 재사용: 대상(namespace·capability key/위젯 key)만 특정하고, 실제 조회·off 처리·항목 렌더는
flows._run_groupware_node(워크플로우 그룹웨어 노드와 동일 코어)를 그대로 재사용한다 — 단일 진실 원천.
리소스 표기 items도 flows._gw_source_items로 만들어 워크플로우 경로와 형태를 고정한다.
"""
# Groupware Agent — reads the internal M365 virtual API (Outlook mail, calendar, To Do,
# SharePoint + 9 widgets). It is the 4th agent the auto intent pipeline (app/pipeline.py) can route
# to (user decision 2026-08-27, updating groupware.py's earlier "explicit routing only" stance). It is
# NOT a real Gmail integration — it connects, context-appropriately, to OUR virtual API (smart_seed +
# widgets). Reads by default; execution requests (create event/meeting, complete/add to-do, compose
# mail) are emitted only as extras.action_draft and run via the confirm card →
# POST /api/actions/{id}/confirm (no automatic execution; added 2026-08-27). Execution mutates the
# smart_seed store for real and persists within the session (reset on server restart).
#
# Permission: groupware ships in the base SaaS package (user decision 2026-08-24 — never gated in
# settings). It answers with no eff gate, honoring only the per-tool on/off of the smart-execution
# config (via _run_groupware_node).
#
# Execution reuse: this module only resolves targets (namespace capability keys / widget keys); the
# actual reads, off-handling, and item rendering are reused verbatim from flows._run_groupware_node
# (the same core as the workflow groupware node) — a single source of truth. The resource-display
# items are likewise built by flows._gw_source_items, locking the shape to the workflow path.

import asyncio
import logging
import re

from app import llm
from app import security_store
from app.agents import AgentResult, Message

logger = logging.getLogger("ai365.agents.groupware")

# M365 네임스페이스(smart_actions capability) 5종
# The five M365 namespaces (smart_actions capabilities)
# Teams는 제거(2026-08-28 사용자 지시 — Graph Teams API가 MFA를 요구해 실연동 불가)
# Teams removed (user decision 2026-08-28 — the Graph Teams API requires MFA, so real integration is impossible)
_NS = ("mail", "calendar", "todo", "sharepoint")

# ── 툴 콜링(function calling) 결정 계층 ──────────────────────────────────────
# 종전 손으로 짠 플래너(GW_PLAN_SYSTEM/_plan/JSON 파싱)를 Gemini 함수 호출로 교체(2026-08-28).
# 모델이 아래 도구 중 하나(또는 read_groupware 다중 대상)를 골라 인자를 채운다 — 받는사람·제목·
# 날짜 등 인자 추출을 스키마가 보장. 실행 도구는 곧장 실행하지 않고 action_draft→confirm 게이트로,
# 조회(read_groupware)는 기존 flows._run_groupware_node로 넘긴다(다운스트림 무변경). 툴콜 실패(429·
# 모델 저하)면 결정적 키워드/위젯 폴백으로 조회를 이어간다.
# ── Tool-calling (function calling) decision layer ───────────────────────────
# Replaces the old hand-rolled planner (GW_PLAN_SYSTEM/_plan/JSON parsing) with Gemini function calling
# (2026-08-28). The model picks one of the tools below (or read_groupware with several targets) and fills
# the args — the schema guarantees recipient/subject/date extraction. Action tools are not executed
# directly (emitted as action_draft → confirm gate); reads (read_groupware) go to the existing
# flows._run_groupware_node (downstream unchanged). If tool calling fails (429 / model degradation), a
# deterministic keyword/widget fallback still handles reads.

_FC_SYSTEM = """너는 그룹웨어(M365 가상 API) 에이전트다. 사용자 요청을 처리할 도구를 정확히 골라 인자를 채워 호출한다.
- 확인·조회(메일함·일정/회의·할 일·사내 문서함, 또는 날씨·조직도·뉴스·새 소식·컬렉션·최근 대화·사용 현황·BI·기능 안내)는 read_groupware 하나로 처리한다(관련된 대상만 targets에 넣는다).
- Microsoft 365 테넌트 보안 현황(보안 상태·위험한 로그인/사용자·점검 항목·사용자/그룹 수·라이선스 할당/잔여·서비스/Teams 활성 사용·저장소/사서함·전역 관리자·신규/삭제 계정·보안 요약)은 read_security 로 조회한다(그룹웨어 위젯이 아니다. 관련된 대상만 targets에 넣는다).
- 새로 만들거나 상태를 바꾸는 요청(일정/회의 생성, 할 일 완료·추가, 메일 작성·발송)은 해당 실행 도구를 호출한다.
- 규정·정책·매뉴얼 등 문서 지식, SQL·집계·BI 분석, 메일 자동분류·보고서 취합·교육 이수율 같은 업무 운영/자동화는 이 에이전트 소관이 아니다 → read_groupware(targets=[]).
- 시간·날짜·참석자·제목은 요청에서 최대한 구체적으로 추출한다. 받는 사람(메일 to)은 요청에 분명히 있을 때만 채우고, 불분명하면 비워 둔다(임의로 지어내지 말 것)."""

# 조회 대상 enum — 네임스페이스 5종 + 위젯 9종(app.groupware.WIDGET_KEYS와 일치)
# Read-target enum — 5 namespaces + 9 widgets (matches app.groupware.WIDGET_KEYS)
_READ_TARGETS = ["mail", "calendar", "todo", "sharepoint",
                 "weather", "org", "news", "alerts", "collections", "recent", "usage", "bi", "actions"]

# 실행 도구 이름 → 카탈로그 액션 키 / action tool name → catalog action key
_ACTION_TOOLS = {
    "create_event": "calendar.action.event",
    "create_meeting": "calendar.action.meeting",
    "complete_todo": "todo.action.complete",
    "create_todo": "todo.action.create",
    "compose_mail": "mail.action.compose",
}

# 발송 계열 액션 키(메일) — 병렬 function call 시 팬아웃(배치) 대상 / send-family action keys (fan-out targets)
_SEND_KEYS = {"mail.action.compose"}

# 일정/회의 공용 인자 스키마 / shared arg schema for event & meeting
_EVENT_PROPS = {
    "subject": {"type": "STRING", "description": "일정 제목"},
    "day": {"type": "INTEGER", "description": "날짜 오프셋(오늘=0, 내일=1, 어제=-1)"},
    "start": {"type": "STRING", "description": "시작 시각 HH:MM(24시간)"},
    "end": {"type": "STRING", "description": "종료 시각 HH:MM(24시간)"},
    "location": {"type": "STRING", "description": "장소(없으면 생략)"},
    "attendees": {"type": "ARRAY", "description": "참석자 이름 목록", "items": {"type": "STRING"}},
}

# 함수 선언(JSON 스키마) — llm.generate_calls가 types.Tool로 변환한다.
# 받는 사람(compose_mail.to)은 required에 넣지 않는다 — 미지정 시 임의 생성 대신
# 비워 두게 하고, _build_action_draft가 본인("나")에게로 기본 처리해 confirm 카드로 확인시킨다.
# Function declarations (JSON schema) — llm.generate_calls converts them to types.Tool.
# The recipient (compose_mail.to) is NOT required — when unspecified the model leaves
# them blank instead of inventing one, and _build_action_draft defaults to self ("나"), verified via the confirm card.
_TOOL_SPECS = [
    {"name": "read_groupware",
     "description": "그룹웨어 조회 — 메일함·일정/회의·할 일·사내 문서함 및 사내 위젯(날씨·조직도·뉴스·새 소식·컬렉션·최근 대화·사용 현황·BI·기능 안내)을 확인한다. 요청과 직접 관련된 대상만 targets에 넣는다(최대 3개). 이 에이전트 소관이 아니면 targets를 빈 배열로 둔다.",
     "parameters": {"type": "OBJECT", "properties": {
         "targets": {"type": "ARRAY", "description": "조회할 대상(관련된 것만)",
                     "items": {"type": "STRING", "enum": _READ_TARGETS}},
         "day": {"type": "INTEGER", "description": "날짜 오프셋(오늘=0, 내일=1, 어제=-1). 날짜 언급이 없으면 생략."},
     }, "required": ["targets"]}},
    # 보안 에이전트(그룹웨어 하위 네임스페이스, 2026-09-07) — 테넌트 보안 현황 조회. 데이터는 app.security_store(목업).
    # Security agent (groupware sub-namespace, 2026-09-07) — tenant security reads backed by app.security_store (mock).
    {"name": "read_security",
     "description": "보안 에이전트 조회 — Microsoft 365 테넌트 보안 현황을 확인한다: status(종합 상태), risky_signins(위험한 사용자/로그인 목록), "
                    "checks(점검 항목: 전역/게스트 관리자·역할 변경·사용자 액세스·암호 만료 설정), users_groups(사용자·게스트·그룹 수), "
                    "licenses(라이선스 할당/잔여), service_usage(서비스·Teams 활성/비활성 사용자), storage(Exchange 사서함·OneDrive·SharePoint 저장소), "
                    "admins(전역 관리자), changes(신규/삭제 사용자·그룹), summary(보안 요약). 요청과 직접 관련된 대상만 targets에 넣는다(최대 3개).",
     "parameters": {"type": "OBJECT", "properties": {
         "targets": {"type": "ARRAY", "description": "조회할 보안 대상(관련된 것만)",
                     "items": {"type": "STRING", "enum": security_store.READ_TARGETS}},
     }, "required": ["targets"]}},
    {"name": "create_event", "description": "새 일정(일반/오프라인)을 만든다.",
     "parameters": {"type": "OBJECT", "properties": _EVENT_PROPS, "required": ["subject"]}},
    {"name": "create_meeting", "description": "Teams 온라인 회의를 만든다(화상 회의).",
     "parameters": {"type": "OBJECT", "properties": _EVENT_PROPS, "required": ["subject"]}},
    {"name": "complete_todo", "description": "할 일(To Do)을 완료 처리한다.",
     "parameters": {"type": "OBJECT", "properties": {
         "title": {"type": "STRING", "description": "완료할 할 일 제목"}}, "required": ["title"]}},
    {"name": "create_todo", "description": "할 일(To Do)을 새로 추가한다.",
     "parameters": {"type": "OBJECT", "properties": {
         "title": {"type": "STRING", "description": "할 일 제목"},
         "due": {"type": "INTEGER", "description": "마감 날짜 오프셋(오늘=0, 내일=1). 없으면 생략."}},
      "required": ["title"]}},
    {"name": "compose_mail", "description": "메일을 작성해 보낸다(보낸 편지함 저장). 받는 사람이 요청에 분명할 때만 to를 채운다.",
     "parameters": {"type": "OBJECT", "properties": {
         "to": {"type": "STRING", "description": "받는 사람 이름(요청에 분명히 있을 때만)"},
         "subject": {"type": "STRING", "description": "제목"},
         "body": {"type": "STRING", "description": "본문. '이 내용을 메일로'처럼 직전 답변을 가리키면 비워 둔다."}}}},
]

# 플래너 실패 시 결정적 폴백 — 네임스페이스별 조회 어휘(정밀 우선)
# Deterministic fallback when the planner fails — per-namespace read vocabulary (precision first)
_NS_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("calendar", ("일정", "미팅", "회의", "스케줄", "캘린더")),
    ("todo", ("할 일", "할일", "태스크", "투두", "to do")),
    ("sharepoint", ("문서함", "쉐어포인트", "sharepoint", "공유 문서", "공유문서")),
    ("mail", ("메일", "메일함", "받은 편지함", "안 읽은", "outlook", "아웃룩")),
)


def _not_found(reason: str, alternative: str) -> AgentResult:
    return {"status": "not_found", "text": "", "extras": {},
            "fail_reason": reason, "alternative": alternative}


def _day_of(text: str) -> int | None:
    if "내일" in text:
        return 1
    if "어제" in text:
        return -1
    if "오늘" in text:
        return 0
    return None


# 실행 가능한 액션 키(카탈로그와 일치) / executable action keys (matching the catalog)
_ACTION_KEYS = {
    "calendar.action.event", "calendar.action.meeting",
    "todo.action.complete", "todo.action.create",
    "mail.action.compose",
}


def _day_label(day: int) -> str:
    return {0: "오늘", 1: "내일", -1: "어제"}.get(day, f"{day}일 후" if day > 0 else f"{-day}일 전")


def _plus_hour(hhmm: str) -> str:
    """HH:MM + 1시간(24시간 랩어라운드). 파싱 실패 시 원본 유지."""
    # HH:MM + 1 hour (24h wrap). Returns the input unchanged if it can't be parsed.
    try:
        h, m = hhmm.split(":")
        return f"{(int(h) + 1) % 24:02d}:{int(m):02d}"
    except Exception:  # noqa: BLE001
        return hhmm


# 되묻기 프롬프트 표식 — 본문 참조가 이 되묻기들을 건너뛰고 실제 콘텐츠를 잡게 한다.
# (수신자 되묻기·내용 없음 되묻기 둘 다 — 둘 중 하나라도 빠지면 되묻기 문구가 메일 본문으로 오염된다.)
# Markers of the re-ask prompts — let body references skip BOTH re-asks and grab the real content.
# (Recipient re-ask AND no-content re-ask — missing either lets the re-ask text pollute a mail body.)
_ASK_RECIPIENT_MARK = "누구에게 보낼까요"
_ASK_CONTENT_MARK = "보낼 내용이 없습니다"
_ASK_MARKS = (_ASK_RECIPIENT_MARK, _ASK_CONTENT_MARK)


def _last_content_answer(context: list | None) -> str:
    """직전의 '실질' 어시스턴트 답변 — 되묻기 프롬프트(수신자·내용 없음)는 건너뛴다.

    되묻기 다음 턴('김민준에게 보내줘')에서 원래 콘텐츠를 본문으로 유지하기 위함."""
    # The most recent 'substantive' assistant answer — skips the re-ask prompts (recipient / no-content).
    # Keeps the original content as the body on the follow-up turn ("send it to 김민준").
    for m in reversed(context or []):
        if m.get("role") != "assistant":
            continue
        c = (m.get("content") or "").strip()
        if not c or any(mark in c for mark in _ASK_MARKS):
            continue
        return c
    return ""


def _build_action_draft(a: dict, context: list | None = None, allow_self: bool = False) -> dict | None:
    """플래너 action → confirm용 action_draft{kind, payload, summary}. 필수 인자 없거나 도구 off면 None.

    메일 발송에서 받는 사람이 없고 allow_self=False면 self로 채우지 않고
    {"needs_recipient": True}를 표시해 호출부가 '누구에게?' 되묻기를 하게 한다(_action_result)."""
    # Planner action → the confirm draft. None when required fields are missing or the tool is off.
    # For mail sends with no recipient and allow_self=False, does NOT default to self; instead flags
    # {"needs_recipient": True} so the caller asks "who to?" (see _action_result).
    key = a.get("key") if isinstance(a, dict) else None
    if key not in _ACTION_KEYS:
        return None
    ns = key.split(".", 1)[0]
    from app import smart_actions   # 지연 임포트 / lazy
    if not (smart_actions.get_config().get(ns) or {}).get("enabled", True):
        return None  # 도구 꺼짐 — 실행 초안 미생성 / tool disabled

    if key in ("calendar.action.event", "calendar.action.meeting"):
        subject = (a.get("subject") or "새 일정").strip()
        day = a.get("day") if isinstance(a.get("day"), int) else 0
        # 시작만 주어지면 종료는 +1시간 — 시작 15:00에 고정 종료 10:00이 붙어 역전되던 문제 방지
        # If only start is given, end = start + 1h — avoids a fixed 10:00 end reversing a 15:00 start.
        start = (a.get("start") or "09:00").strip()
        end = (a.get("end") or "").strip()
        if not end or end <= start:
            end = _plus_hour(start)
        online = key.endswith("meeting")
        att = [x for x in (a.get("attendees") or []) if isinstance(x, str) and x.strip()]
        payload = {"subject": subject, "day": day, "start": start, "end": end,
                   "location": a.get("location") or "", "online": online, "attendees": att}
        who = (" · 참석 " + ", ".join(att)) if att else ""
        summary = f"{_day_label(day)} {start} '{subject}' {'Teams 회의' if online else '일정'}를 만듭니다{who}."
        return {"kind": key, "payload": payload, "summary": summary}
    if key == "todo.action.complete":
        title = (a.get("title") or "").strip()
        return {"kind": key, "payload": {"title": title}, "summary": f"'{title}' 할 일을 완료 처리합니다."} if title else None
    if key == "todo.action.create":
        title = (a.get("title") or "").strip()
        due = a.get("due") if isinstance(a.get("due"), int) else None
        return {"kind": key, "payload": {"title": title, "due": due}, "summary": f"'{title}' 할 일을 추가합니다."} if title else None
    if key == "mail.action.compose":
        subject = (a.get("subject") or "(제목 없음)").strip()
        body = (a.get("body") or "").strip()
        # 본문이 비었을 때만(=이전 대화 참조 신호, FC 스키마 계약) 직전 '실질' 답변을 본문으로 사용.
        # "3시 회의 취소"처럼 사용자가 명시한 짧은 본문은 그대로 보존한다.
        # Fill from the most recent substantive answer ONLY when the body is empty (the FC-schema signal
        # for "reference the prior turn"). A short but explicit body like "3시 회의 취소" is preserved.
        if not body:
            prior = _last_content_answer(context)
            if prior:
                body = prior
                if subject == "(제목 없음)":
                    subject = (prior.splitlines()[0][:24]).strip() or subject
        # 보낼 내용이 끝내 없으면 발송을 만들지 않는다 — 빈 메일 confirm 방지(needs_content 되묻기)
        # If there is still nothing to send, do not draft — prevents an empty-mail confirm (needs_content re-ask)
        if not body:
            return {"kind": key, "payload": {"to": "", "subject": subject, "body": ""},
                    "needs_content": True}
        # 받는 사람 미지정: self 자동 지정 대신 '누구에게?' 되묻기(allow_self일 때만 나에게)
        # No recipient: ask "who to?" instead of silently self-defaulting (self only when allow_self)
        to = (a.get("to") or "").strip()
        if not to:
            if not allow_self:
                return {"kind": key, "payload": {"to": "", "subject": subject, "body": body},
                        "needs_recipient": True}
            to = "나"
        return {"kind": key, "payload": {"to": to, "subject": subject, "body": body},
                "summary": f"{to}에게 '{subject}' 메일을 보냅니다."}
    return None


def build_delivery_draft(key: str, target: str | None, body: str) -> dict | None:
    """콘텐츠 취합본(보고서)을 메일로 발송하는 action_draft. 순차 발송(파이프라인 _deliver_answer) 전용.

    실행은 기존 execute_action이 처리한다. 본문이 비면 None(보낼 내용 없음)."""
    # An action_draft that sends the aggregated report via mail. Used by the pipeline's sequential
    # delivery (_deliver_answer). Execution is handled by the existing execute_action. None if body is empty.
    body = (body or "").strip()
    if not body or key != "mail.action.compose":
        return None
    to = (target or "").strip() or "나"
    subject = (body.splitlines()[0][:24]).strip() or "보고서"
    return {"kind": key, "payload": {"to": to, "subject": subject, "body": body},
            "summary": f"{to}에게 '{subject}' 메일(보고서)을 보냅니다."}


def build_batch_delivery(sends: list, body: str) -> dict | None:
    """다건 발송(팬아웃)을 한 번의 confirm으로 묶는 action_draft. 1건이면 단건 draft, 0건이면 None.

    각 send={key,target}를 build_delivery_draft로 개별 초안화한 뒤 groupware.send.batch로 묶는다.
    실행은 execute_action의 batch 분기가 순회 처리(ns 라우팅은 groupware.send.batch로 그룹웨어 위임)."""
    # Fan-out delivery bundled into ONE confirm. Single draft if 1 send, None if 0/empty body.
    # Each send={key,target} is drafted via build_delivery_draft, then bundled as groupware.send.batch.
    # Execution loops in execute_action's batch branch (routed to groupware by the groupware.send.batch kind).
    body = (body or "").strip()
    if not body:
        return None
    drafts = [d for sd in (sends or [])
              if isinstance(sd, dict) and (d := build_delivery_draft(sd.get("key", ""), sd.get("target"), body))]
    # 묶음 로직은 _bundle_drafts 단일 원천(1건=단건 draft 그대로 / 2건+=batch)
    # Bundling has a single source of truth in _bundle_drafts (1 = the single draft / 2+ = batch)
    return _bundle_drafts(drafts)


def _fc_messages(query: str, context: list[Message]) -> list[Message]:
    """함수 호출용 메시지 — 최근 맥락 4턴 + 이번 요청('이 내용을 메일로' 같은 참조 해석용)."""
    # Messages for function calling — last 4 turns + this request (to resolve references like "email this").
    recent = context[:-1][-4:] if context else []
    return recent + [{"role": "user", "content": f"[요청]\n{query}"}]


def _pick_action_call(calls: list[dict]) -> tuple[str, dict] | None:
    """함수 호출 목록에서 첫 실행 도구 → (카탈로그 액션 키, args). 실행 도구가 없으면 None."""
    # First action tool in the call list → (catalog action key, args). None if there is no action tool.
    for c in calls:
        key = _ACTION_TOOLS.get(c.get("name"))
        if key:
            return key, (c.get("args") or {})
    return None


def _coerce_action_args(args: dict) -> dict:
    """함수 호출 인자 정규화 — 날짜 오프셋 float→int, 참석자 문자열 배열 정리(스키마 산출물의 타입 흔들림 흡수)."""
    # Normalize function-call args — day/due float→int, attendees to a clean str list (absorbs schema-output type drift).
    out = dict(args or {})
    for k in ("day", "due"):
        v = out.get(k)
        if isinstance(v, bool):
            out[k] = None
        elif isinstance(v, (int, float)):
            out[k] = int(v)
    att = out.get("attendees")
    if isinstance(att, list):
        out["attendees"] = [str(x).strip() for x in att if str(x).strip()]
    return out


def _read_targets_from_calls(calls: list[dict], gw) -> tuple[list[str], int | None]:
    """read_groupware 호출 → (_resolve_keys용 targets, day). 위젯 키는 'widget:<key>'로 접두."""
    # read_groupware calls → (targets for _resolve_keys, day). Widget keys get the 'widget:' prefix.
    targets: list[str] = []
    day: int | None = None
    for c in calls:
        if c.get("name") != "read_groupware":
            continue
        args = c.get("args") or {}
        for t in (args.get("targets") or []):
            if not isinstance(t, str):
                continue
            tt = f"widget:{t}" if t in gw.WIDGET_KEYS else t
            if tt not in targets:
                targets.append(tt)
        d = args.get("day")
        if not isinstance(d, bool) and isinstance(d, (int, float)):
            day = int(d)
    return targets, day


# ── 보안 조회(read_security) 보조 — 툴 콜 결과 → 대상, FC 실패 시 결정적 어휘 폴백, 결과 조립 ──
# ── Security read (read_security) helpers — tool call → targets, deterministic vocabulary fallback, result assembly ──
_SEC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("risky_signins", ("위험 로그인", "위험한 로그인", "위험 사용자", "위험한 사용자", "risky")),
    ("summary", ("보안 요약", "보안 상태 요약", "보안 현황 요약", "보안 상황 요약")),
    ("status", ("보안 상태", "보안 현황", "종합 상태", "테넌트 상태", "보안 점수")),
    ("licenses", ("라이선스", "라이센스", "license", "copilot")),
    ("admins", ("전역 관리자", "글로벌 관리자", "전역관리자")),
    ("changes", ("신규 사용자", "신규 계정", "새 계정", "삭제된 사용자", "삭제 계정", "삭제된 계정")),
    ("storage", ("저장소", "사서함", "스토리지", "onedrive 용량", "sharepoint 용량", "용량")),
    ("service_usage", ("활성 사용자", "비활성 사용자", "서비스 사용", "teams 활성", "활성 팀")),
    ("checks", ("점검 항목", "점검 결과", "암호 만료", "게스트 관리자", "역할 변경", "사용자 액세스")),
    ("users_groups", ("사용자 수", "사용자 몇", "게스트", "그룹 수", "그룹 몇", "총 사용자", "구성원 수")),
)


def _sec_targets_from_calls(calls: list[dict]) -> list[str]:
    """read_security 호출 → 유효 대상(enum 검증, 순서 유지) / read_security calls → valid targets (enum-checked, ordered)"""
    out: list[str] = []
    for c in calls:
        if c.get("name") != "read_security":
            continue
        for t in ((c.get("args") or {}).get("targets") or []):
            if isinstance(t, str) and t in security_store.READ_TARGETS and t not in out:
                out.append(t)
    return out[:3]


def _sec_targets_by_rules(query: str) -> list[str]:
    """FC 저하·미선택 시 결정적 폴백 — 보안 어휘가 있을 때만 / deterministic fallback — only when security vocabulary is present"""
    low = query.lower()
    out = [k for k, kws in _SEC_RULES if any(kw in low for kw in kws)]
    return out[:3]


def _security_result(targets: list[str]) -> AgentResult:
    """보안 조회 결과 — 결정적 서술(security_store.describe) + 리소스 표기 items(그룹웨어 축, ns='security')
    / security read result — deterministic description + resource items on the groupware axis (ns='security')"""
    text = security_store.describe(targets)
    items = [{"title": security_store.READ_LABELS.get(t, t), "path": ["그룹웨어", "보안 에이전트"],
              "kind": "gw", "key": f"security:{t}", "ns": "security"} for t in targets]
    return {"status": "answer", "text": text, "extras": {"gw": items, "security": targets}}


# 발송 의도 결정적 감지 어휘 — FC가 실행을 못 잡았을 때의 구제용(메일 발송 한정)
# Deterministic send-intent vocabulary — rescue when FC misses an action (mail send only)
_SEND_VERBS = ("보내", "발송", "전송")

# 조회 어휘 — 이게 있으면 '발송한 메일 보여줘'류 조회이지 발송이 아니다(rescue 선제 실행 가드).
# Read vocabulary — with these, "show the mail I sent" is a read, not a send (guards the early rescue).
_READ_WORDS = ("보여", "확인", "조회", "알려", "찾아", "검색", "받은", "왔", "목록", "현황")


def _send_over_read(query: str) -> bool:
    """명백한 메일 발송 지시인가 — 발송 어휘 + 메일 + 조회 어휘 없음(조회로 새지 않게 rescue 우선)."""
    # Is this clearly a mail-send instruction — send verb + mail word + no read words
    # (so the rescue outranks widget/read paths).
    low = query.lower()
    return (any(v in query for v in _SEND_VERBS)
            and (any(k in query for k in ("메일", "이메일")) or "mail" in low or "outlook" in low)
            and not any(w in query for w in _READ_WORDS))

# 본인 지정 어휘 — 명시적으로 나에게 보낼 때만 self 허용(그 외엔 받는사람 되묻기)
# Self-reference vocabulary — allow self-send only when explicitly addressed to me (else re-ask recipient)
_SELF_WORDS = ("나에게", "나한테", "내게", "내 메일", "본인에게", "제게", "저에게", "스스로")


def _is_self_send(query: str) -> bool:
    return any(w in query for w in _SELF_WORDS)


def _action_result(draft: dict | None) -> AgentResult | None:
    """action_draft → AgentResult. 받는사람 미지정(needs_recipient)·본문 없음(needs_content)이면
    confirm 대신 되묻기 답변을 만든다(extras.await_recipient로 파이프라인이 원문 그대로 표시·저장)."""
    # action_draft → AgentResult. Missing recipient (needs_recipient) / nothing to send (needs_content)
    # produce a re-ask answer instead of a confirm (extras.await_recipient → pipeline stores it verbatim).
    if draft is None:
        return None
    if draft.get("needs_recipient"):
        q = ("메일을 누구에게 보낼까요? 받는 사람 이름을 함께 알려주세요 "
             "(예: \"김민준에게 보내줘\"). 본인에게 보내려면 \"나에게 보내줘\"라고 해주세요.")
        return {"status": "answer", "text": q, "extras": {"auto_agent": "groupware", "await_recipient": True}}
    if draft.get("needs_content"):
        # 문구에 _ASK_CONTENT_MARK("보낼 내용이 없습니다") 포함 — _last_content_answer가 이 되묻기를
        # 실질 답변으로 오인해 다음 턴 메일 본문에 오염되는 것을 막는 스킵 표식이다.
        # The phrase carries _ASK_CONTENT_MARK so _last_content_answer skips this re-ask and it can never
        # pollute the next turn's mail body as a "substantive answer".
        q = f"메일로 {_ASK_CONTENT_MARK}. 보낼 내용을 알려주시거나, 먼저 자료를 조회한 뒤 다시 요청해 주세요."
        return {"status": "answer", "text": q, "extras": {"auto_agent": "groupware", "await_recipient": True}}
    return {"status": "answer", "text": draft["summary"] + " 실행 확인이 필요합니다.",
            "extras": {"action_draft": draft, "auto_agent": "groupware"}}


def _bundle_drafts(drafts: list[dict]) -> dict | None:
    """발송 초안들 → 단건 그대로 / 2건 이상은 groupware.send.batch로 묶는다(팬아웃 한 번 confirm)."""
    # Send drafts → single as-is / 2+ bundled as groupware.send.batch (fan-out, one confirm).
    if not drafts:
        return None
    if len(drafts) == 1:
        return drafts[0]
    inner = [{"kind": d["kind"], "payload": d["payload"]} for d in drafts]
    summary = f"{len(drafts)}건을 보냅니다 — " + " · ".join(d["summary"].rstrip(".") for d in drafts)
    return {"kind": "groupware.send.batch", "payload": {"sends": inner}, "summary": summary}


# '<이름>에게/한테/께' — 결정적 받는사람 추출(rescue용). self 어휘·일반 명사는 제외.
# '께서'(존칭 주격)·'에게서'(출처격)는 수신 조사가 아니므로 (?!서)로 배제하고,
# '월말께'·'10시께'(시간 근사)도 스톱 목록·숫자시각 필터로 제외한다(적대 검증 반영).
# '<name>에게/한테/께' — deterministic recipient extraction (for rescue). Excludes self words/generic
# nouns; '께서' (honorific subject) and '에게서' (source case) are cut by (?!서), and '월말께'/'10시께'
# (approximate-time '께') by the stop list + numeric-time filter (adversarial-verify findings).
_RECIPIENT_RE = re.compile(r"([가-힣A-Za-z0-9]{2,10})\s*(?:에게|한테|께)(?!서)")
_RECIPIENT_STOP = {"누구", "나", "저", "본인", "우리", "그", "이거", "내용",
                   "월말", "월초", "주말", "연말", "연초", "오전", "오후"}
_TIMEISH_RE = re.compile(r"\d+(?:시|분|일|월)$")


def _extract_recipient(query: str) -> str:
    """질의에서 '<이름>에게'류 받는사람을 결정적으로 추출. 여러 매치면 **마지막**(발송 대상은 대개
    문장 뒤쪽 — '고객에게 보낼 안내문을 김민준에게'). 명시적 본인 지정이 있으면 빈 문자열(self 우선)."""
    # Deterministically extract the '<name>에게'-style recipient. With several matches take the LAST
    # (the send target usually comes later — '고객에게 보낼 안내문을 김민준에게'). An explicit self
    # designation wins → "" (allow_self handles it).
    if _is_self_send(query):
        return ""
    found = ""
    for m in _RECIPIENT_RE.finditer(query):
        name = m.group(1)
        if name in _RECIPIENT_STOP or _TIMEISH_RE.search(name):
            continue
        if _is_self_send(name + "에게"):
            continue
        found = name
    return found


def _rescue_action(query: str, context: list[Message]) -> dict | None:
    """FC가 실행 도구를 못 고르고 조회 대상도 없을 때의 결정적 발송 구제(메일).

    '이 내용을 메일로 보내줘'류를 직전 답변 본문으로 초안화한다. 질의에 '<이름>에게'가 있으면
    받는사람을 보존한다. 받는사람 미지정이면 needs_recipient 표식만 달고 되묻기는 _action_result가
    처리한다. 일정·할 일 생성은 제목·시각 등 인자가 필요해 구제하지 않는다."""
    # Deterministic mail-send rescue when FC picks no action tool and there is no read target either.
    # Drafts "send this by mail" with the prior answer as the body, preserving an explicit '<name>에게'
    # recipient. Missing recipient only flags needs_recipient (_action_result re-asks).
    if not any(v in query for v in _SEND_VERBS):
        return None
    low = query.lower()
    if not (any(k in query for k in ("메일", "이메일", "메일함")) or "mail" in low or "outlook" in low):
        return None
    self_ok = _is_self_send(query)
    recipient = _extract_recipient(query)
    d = _build_action_draft({"key": "mail.action.compose", "to": recipient}, context, allow_self=self_ok)
    return d  # needs_recipient/needs_content 표식 포함 그대로 — 되묻기는 _action_result가 처리
    # (returned as-is incl. needs_recipient/needs_content flags — _action_result does the re-ask)


def _send_result(calls: list[dict], query: str, context: list) -> AgentResult | None:
    """발송 액션 콜(들) → action_draft(단건/배치) 또는 받는사람 되묻기 결과.

    툴 콜링이 고른 발송 도구(compose_mail)를 그대로 초안화한다. 여러 발송 콜이면(예: '김팀장과
    나에게 각각 메일로') groupware.send.batch로 묶어 팬아웃한다. 받는사람 미지정이면
    되묻기(_action_result). 발송 콜이 없으면 None(단건 액션 경로로)."""
    # Send action call(s) → action_draft (single/batch) or a recipient re-ask. Drafts the send tool(s) the
    # tool-calling chose; multiple send calls fan out as groupware.send.batch. Missing recipient → re-ask.
    send_calls = [(_ACTION_TOOLS[c["name"]], _coerce_action_args(c.get("args") or {}))
                  for c in calls if _ACTION_TOOLS.get(c.get("name")) in _SEND_KEYS]
    if not send_calls:
        return None
    allow_self = _is_self_send(query)
    drafts: list[dict] = []
    for k, a in send_calls:
        d = _build_action_draft({"key": k, **a}, context, allow_self=allow_self)
        if d is None:
            continue
        if d.get("needs_recipient") or d.get("needs_content"):
            return _action_result(d)  # 미충족 → 되묻기(첫 건 기준) / unmet requirement → re-ask (first one)
        drafts.append(d)
    draft = _bundle_drafts(drafts)
    if draft is None:
        return None
    return {"status": "answer", "text": draft["summary"] + " 실행 확인이 필요합니다.",
            "extras": {"action_draft": draft, "auto_agent": "groupware"}}


def _resolve_keys(targets: list[str], query: str, day: int | None) -> tuple[list[str], dict]:
    """타깃(ns 또는 widget:<key>) → 구체 capability/위젯 키 + args. 도구 off·미해결은 조용히 스킵."""
    # Targets (ns or widget:<key>) → concrete capability/widget keys + args. Disabled/unresolved: skip.
    from app import smart_actions_api as saa   # 지연 임포트(순환 방지) / lazy (avoid cycle)
    keys: list[str] = []
    args_map: dict[str, dict] = {}
    for tgt in targets:
        if tgt.startswith("widget:"):
            wkey = tgt.split(":", 1)[1]
            from app import groupware as gw
            if wkey in gw.WIDGET_KEYS and wkey not in keys:
                keys.append(wkey)
            continue
        if tgt not in _NS:
            continue
        # 날짜가 있는 캘린더 요청은 range로 고정("내일 일정"→range day=1) — 규칙 분류가 today로 새는 것 방지
        # A dated calendar request pins to range ("내일 일정"→range day=1) so the rule classifier can't drift to today.
        if tgt == "calendar" and day is not None and day != 0:
            if "calendar.info.range" not in keys:
                keys.append("calendar.info.range")
                args_map["calendar.info.range"] = {"day": day}
            continue
        key, args, _how = saa._classify(tgt, query)   # noqa: SLF001 — 조회 분류기 재사용 / reuse the info classifier
        if not key or ".action." in key:              # 조회 전용 — 실행 키는 방어적으로 제외 / read-only: exclude action keys
            continue
        if day is not None and key == "calendar.info.range":
            args = {**(args or {}), "day": day}
        if key not in keys:
            keys.append(key)
            if args:
                args_map[key] = args
    return keys[:4], args_map


def _run_sync(query: str, context: list[Message], eff: dict | None = None,
              scope_files: dict | None = None) -> AgentResult:
    # 게이트 없음 — 그룹웨어는 기본 제공(2026-08-24 사용자 확정). eff·scope_files는 시그니처 통일용 수용 후 미사용
    # (그룹웨어는 스마트 파일 하위 선택지가 없다 — 도구 on/off는 flows._run_groupware_node가 존중).
    # No gate — groupware ships in the base package (user decision 2026-08-24). eff/scope_files are
    # accepted for signature uniformity and unused (no smart-file sub-selection; per-tool on/off is
    # honored inside flows._run_groupware_node).
    from app import flows, groupware as gw   # 지연 임포트 — flows가 app.agents를 임포트하므로 순환 방지 / lazy: flows imports app.agents

    # 0) 툴 콜링 1회(lite) — 실행/조회 도구를 모델이 고르고 인자를 채운다. 실패 시 결정적 폴백.
    # One tool-calling call (lite) — the model picks an action/read tool and fills args. On failure, deterministic fallback.
    calls: list[dict] = []
    try:
        res = llm.generate_calls(_fc_messages(query, context), system=_FC_SYSTEM,
                                 tools=_TOOL_SPECS, tier="lite")
        calls = res.get("calls") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("그룹웨어 툴콜링 실패 — 조회 폴백: %s", e)
        calls = []

    # 1) 실행(action) 경로 — action_draft만 방출(파이프라인 confirm 게이트가 처리).
    #    메일 발송에 받는사람이 없으면 self로 새지 않고 '누구에게?' 되묻기(_action_result).
    # Execution path — emit only action_draft (the pipeline confirm gate handles it).
    #    If a mail send has no recipient, re-ask "who to?" instead of leaking to self (_action_result).
    action = _pick_action_call(calls)
    if action is not None:
        key, raw = action
        # 발송(메일)은 단건/다건(팬아웃)을 _send_result가 처리 — 툴 콜링이 고른 도구·받는사람 그대로.
        # Sends (mail) go through _send_result for single/fan-out — using the tools/recipients the tool-calling chose.
        if key in _SEND_KEYS:
            res = _send_result(calls, query, context)
            if res is not None:
                return res
        draft = _build_action_draft({"key": key, **_coerce_action_args(raw)}, context,
                                    allow_self=_is_self_send(query))
        res = _action_result(draft)
        if res is not None:
            return res
        return _not_found(
            "실행할 작업을 구체적으로 파악하지 못했습니다.",
            "무엇을(제목)·언제·누구에게처럼 실행에 필요한 정보를 함께 알려주세요.",
        )

    # 1.5) 명백한 발송인데 FC가 발송을 못 잡았으면 — 위젯/조회로 새기 전에 결정적 구제를 먼저 태운다.
    #      실사례: refined_query "이전 대화 내용 최지우에게 이메일 발송" → 위젯 프리패스가 '이전 대화'로
    #      recent를 잡아 조회로 새고, targets가 차 있어 아래 rescue가 실행 기회를 잃었다(2026-08-28).
    #      '발송한 메일 보여줘' 같은 조회는 조회 어휘 가드(_READ_WORDS)로 구제 대상에서 제외한다.
    # 1.5) A clear send that FC failed to catch — run the deterministic rescue BEFORE widget/read paths.
    #      Real case: refined_query "이전 대화 내용 최지우에게 이메일 발송" — the widget pre-pass matched
    #      '이전 대화' → recent, targets filled up, and the rescue below never got a chance (2026-08-28).
    #      Reads like "show the mail I sent" are excluded via the read-word guard (_READ_WORDS).
    if _send_over_read(query):
        res = _action_result(_rescue_action(query, context))
        if res is not None:
            return res

    # 2) 조회(read) 경로 / read path
    day = _day_of(query)
    targets: list[str] = []

    # 1.7) 보안 조회(read_security, 2026-09-07) — 툴 콜 결과 우선, 없으면 결정적 어휘 폴백. 보안 질문이면 위젯 프리패스는
    #      건너뛴다('라이선스'가 사용 현황 위젯으로 새는 것 방지). 그룹웨어 조회 대상이 함께 있으면 아래에서 텍스트를 합친다.
    # 1.7) Security read (read_security, 2026-09-07) — tool call first, else the deterministic vocabulary. Security
    #      questions skip the widget pre-pass (so 'license' does not leak into the usage widget). Groupware targets
    #      requested alongside are merged below.
    sec_targets = _sec_targets_from_calls(calls) or _sec_targets_by_rules(query)
    sec_res = _security_result(sec_targets) if sec_targets else None

    # 위젯 룰 프리패스 — 0 LLM 정밀 분류(날씨·조직도·뉴스 등) / widget rule pre-pass (0 LLM)
    wkey = None if sec_res else gw._classify(query)  # noqa: SLF001 — 위젯 규칙 분류기 재사용 / reuse the widget rule classifier
    if wkey:
        targets.append(f"widget:{wkey}")

    # read_groupware 호출 결과 반영(다중 대상 지원) / apply the read_groupware call (supports multiple targets)
    r_targets, r_day = _read_targets_from_calls(calls, gw)
    for t in r_targets:
        if t not in targets:
            targets.append(t)
    if r_day is not None:
        day = r_day

    # 조회 대상을 못 잡았으면: (1) 발송 의도면 결정적 실행 구제, (2) 아니면 결정적 키워드 조회 폴백.
    # FC 저하(429)·빈 결과를 모두 흡수한다. 발송 구제를 키워드 조회 폴백보다 먼저 본다('메일로 보내줘'가
    # 메일함 조회로 새지 않도록).
    # No read target yet: (1) if it's a send intent, deterministically rescue the action; (2) otherwise run the
    # deterministic keyword read fallback. Absorbs both FC degradation (429) and empty results. The send rescue
    # runs before the keyword read fallback so "send by mail" doesn't leak into a mailbox read.
    if not targets and sec_res is not None:
        return sec_res   # 보안 조회만 요청됨 / a security-only read

    if not targets:
        rescue = _rescue_action(query, context)
        res = _action_result(rescue)
        if res is not None:
            return res
        low = query.lower()
        for ns, kws in _NS_RULES:
            if any(kw in low for kw in kws) and ns not in targets:
                targets.append(ns)

    if not targets:
        return _not_found(
            "그룹웨어에서 조회할 자료를 특정하지 못했습니다.",
            "일정·할 일·사내 문서함·메일함·테넌트 보안 현황 등 확인할 대상을 구체적으로 알려주세요.",
        )

    # 3) 구체 키 확정 / resolve concrete keys
    keys, args_map = _resolve_keys(targets, query, day)
    if not keys:
        if sec_res is not None:
            return sec_res   # 그룹웨어 쪽 키가 없으면 보안 결과만 / no groupware key resolved → security result alone
        return _not_found(
            "그룹웨어에서 조회할 자료를 특정하지 못했습니다.",
            "일정·할 일·사내 문서함·메일함·테넌트 보안 현황 등 확인할 대상을 구체적으로 알려주세요.",
        )

    # 4) 실행(단일 진실 원천 재사용) / execute (reuse the single source of truth)
    node = {"resources": keys, "args": args_map}
    # want_rows: 채팅 OpenUI 2단계의 목록 행(row_lists)도 받는다. 워크플로우 경로는 이 인자를 넘기지 않아 종전 그대로다
    # want_rows: also take the list rows (row_lists) for chat OpenUI phase 2; the workflow path never passes it
    out = flows._run_groupware_node(node, query, "그룹웨어", want_rows=True)   # noqa: SLF001 — 그룹웨어 노드 코어 재사용 / reuse node core
    items = flows._gw_source_items(node)                       # noqa: SLF001 — 워크플로우 경로와 동일 리소스 items

    if out.get("status") != "done":
        if sec_res is not None:
            return sec_res   # 그룹웨어 조회는 실패했어도 보안 결과는 답한다 / answer with the security part even if the groupware read failed
        return _not_found(
            (out.get("text") or "").strip() or "그룹웨어에서 관련 자료를 찾지 못했습니다.",
            "리소스 관리의 그룹웨어 에이전트 설정을 확인하거나 확인할 대상을 바꿔 질문해 주세요.",
        )

    text = (out.get("text") or "").strip()
    # 위젯 응답의 부가 항목(items)을 결정적 줄로 접어 취합 LLM이 근거로 쓰게 한다
    # Fold widget item lines in deterministically so the aggregation LLM can ground on them
    wlines = [f"- {i.get('t', '')} — {i.get('s', '')}".rstrip(" —")
              for i in (out.get("items") or []) if i.get("t")]
    if wlines:
        text = (text + "\n" + "\n".join(wlines)).strip()
    # OpenUI 2단계(2026-10-27, 계약 9.2절 + 조정): 조회한 키마다 목록 하나(능력 조회: 메일 · 일정 · 할 일 · 문서함, 그리고 위젯)
    # [{key, title, left, right, rows: [{t, s}]}](row_lists, 행은 글자 · 최대 30행). 서버가 목록마다 gw{m} 데이터 문장으로 프로그램 앞에
    # 넣고 모델은 참조만 한다. 위 text 의 줄과 같은 내용이라 취합 프롬프트(answers._slim_extras)와 메시지 meta(answers._without_excerpts)
    # 에서는 뺀다.
    # OpenUI phase 2 (2026-10-27, contract 9.2 + adjustment): one list per read key, capability reads (mail, calendar, to-do,
    # documents) and widgets alike: [{key, title, left, right, rows: [{t, s}]}] (row_lists; string rows, at most 30). The server
    # puts each list ahead of the program as a gw{m} data statement and the model only references it. The rows repeat the text
    # lines above, so the aggregation prompt (answers._slim_extras) and message meta (answers._without_excerpts) leave them out.
    gw_rows = [g for g in (out.get("row_lists") or []) if isinstance(g, dict) and g.get("rows")]

    # 보안 조회가 함께 있으면 텍스트·리소스 표기를 합친다 / merge the security part when requested alongside
    if sec_res is not None:
        text = (text + "\n\n" + sec_res["text"]).strip()
        items = list(items) + list(sec_res["extras"]["gw"])

    return {"status": "answer", "text": text or "조회 결과가 없습니다.",
            "extras": {"gw": items, "gw_keys": keys, **({"gw_rows": gw_rows} if gw_rows else {}),
                       **({"security": sec_targets} if sec_res else {})}}


async def run(query: str, context: list[Message], allow_web: bool = False,
              eff: dict | None = None, scope_files: dict | None = None) -> AgentResult:
    # 그룹웨어는 웹 폴백이 없어 allow_web을 사용하지 않는다(시그니처 통일용).
    # Groupware has no web fallback, so allow_web is unused (kept for signature consistency).
    return await asyncio.to_thread(_run_sync, query, context, eff, scope_files)


# ---------------------------------------------------------------------------
# 실행 — 오직 POST /api/actions/{id}/confirm 에서만 호출된다 (자동 실행 금지).
# smart_seed 뮤테이터로 실제 상태를 바꾼다(세션 지속, 재시작 초기화).
# Execution — called only from POST /api/actions/{id}/confirm (no automatic execution).
# Mutates the smart_seed store for real (session-persistent, reset on restart).
# ---------------------------------------------------------------------------

def execute_action(kind: str, payload: dict) -> str:
    """그룹웨어 액션 7종을 smart_seed 뮤테이터로 실행하고 결과 문구를 반환. 시그니처(kind, payload)->str 고정."""
    # Run the 7 groupware actions via smart_seed mutators, returning a result line. Fixed (kind, payload)->str contract.
    from app import smart_seed as s
    p = payload or {}
    if kind == "groupware.send.batch":
        # 다건 발송(팬아웃) — 각 send를 기존 단건 execute_action으로 순회 실행하고 결과를 합친다.
        # Fan-out delivery — run each send through the existing single execute_action and join the results.
        lines: list[str] = []
        for sd in (p.get("sends") or []):
            if not isinstance(sd, dict):
                continue
            try:
                lines.append(execute_action(sd.get("kind", ""), sd.get("payload") or {}))
            except Exception as e:  # noqa: BLE001
                lines.append(f"발송 실패: {e}")
        return "\n".join(lines) if lines else "보낼 항목이 없습니다."
    if kind in ("calendar.action.event", "calendar.action.meeting"):
        row = s.calendar_add(p.get("subject") or "새 일정", day=p.get("day", 0),
                             start=p.get("start", "09:00"), end=p.get("end", "10:00"),
                             loc=p.get("location", ""), online=bool(p.get("online")),
                             attendees=p.get("attendees") or ())
        att = ", ".join(a["name"] for a in row["attendees"])
        day_label = (row["when"] or "").split()[0] if row.get("when") else ""
        base = f"일정을 추가했습니다 — {row['subject']} · {day_label} {row['timeRange']}".replace("  ", " ")
        return base + (f" · 참석 {att}" if att else "")
    if kind == "todo.action.complete":
        row = s.todo_complete(p.get("title") or "")
        if row is None:
            return f"'{p.get('title', '')}'에 해당하는 미완료 할 일을 찾지 못했습니다. 제목을 확인해 주세요."
        return f"완료 처리했습니다 — {row['title']}"
    if kind == "todo.action.create":
        row = s.todo_add(p.get("title") or "새 할 일", due=p.get("due"))
        return f"할 일을 추가했습니다 — {row['title']}"
    if kind == "mail.action.compose":
        artifacts = p.get("artifacts") or []
        if artifacts:
            from app import docgen
            for artifact in artifacts:
                doc = docgen.get_doc(artifact["id"])
                if not doc or doc["status"] != "done":
                    raise ValueError("첨부할 파일 생성이 완료되지 않았습니다")
                docgen.build_file(artifact["id"])
        row = s.mail_send(p.get("to") or "", p.get("subject") or "(제목 없음)", p.get("body") or "", artifacts=artifacts)
        to = ", ".join(x["name"] for x in row["to"])
        return f"메일을 보냈습니다(보낸 편지함에 저장) — {to}에게 '{row['subject']}'" + (f" · 첨부 {len(artifacts)}개" if artifacts else "")
    raise ValueError(f"알 수 없는 액션 종류: {kind}")


# ---------------------------------------------------------------------------
# Outlook 프리필 — 발송 confirm의 [실행]이 내용이 채워진 실제 Outlook 새 메일 창을 함께 연다.
# 딥링크(URL 열기)라 Graph API·MFA가 필요 없다. 이름→이메일은 조직도(smart_seed.email_of)로 해석.
# Outlook prefill — the send confirm's [Run] also opens a real Outlook compose window with the content
# filled in. It is a deeplink (URL open), so no Graph API/MFA is needed. Names resolve to org emails.
# ---------------------------------------------------------------------------

_OUTLOOK_COMPOSE = "https://outlook.office.com/mail/deeplink/compose"
_OUTLOOK_BODY_MAX = 1800  # URL 길이 한계 대비 본문 상한 / body cap against practical URL length limits


def outlook_compose_url(payload: dict) -> str:
    """mail.action.compose payload → 받는사람·제목·본문이 채워진 Outlook 웹 compose 딥링크."""
    # mail.action.compose payload → an Outlook-web compose deeplink with to/subject/body prefilled.
    from urllib.parse import quote
    from app import smart_seed as s
    to = s.email_of((payload.get("to") or "").strip() or "나")
    if to == "나":
        to = ""  # 본인 발송 — 주소 미지정으로 열어 기본 계정에서 채우게 / self-send: open without an address
    body = (payload.get("body") or "").strip()
    if len(body) > _OUTLOOK_BODY_MAX:
        body = body[:_OUTLOOK_BODY_MAX] + "…"
    return (_OUTLOOK_COMPOSE + "?to=" + quote(to)
            + "&subject=" + quote((payload.get("subject") or "").strip())
            + "&body=" + quote(body))


def outlook_urls(draft: dict | None) -> list[str]:
    """발송 초안(단건/배치) → 열어야 할 Outlook compose 딥링크 목록(메일 발송만, 그 외 [])."""
    # Send draft (single/batch) → the Outlook compose deeplinks to open (mail sends only; else []).
    if not isinstance(draft, dict):
        return []
    if draft.get("kind") == "mail.action.compose":
        return [outlook_compose_url(draft.get("payload") or {})]
    if draft.get("kind") == "groupware.send.batch":
        return [outlook_compose_url(it.get("payload") or {})
                for it in (draft.get("payload", {}).get("sends") or [])
                if it.get("kind") == "mail.action.compose"]
    return []
