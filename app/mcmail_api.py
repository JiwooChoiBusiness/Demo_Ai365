"""M코스메틱 이메일 에이전트 API — /api/email (2026-09-28, 계획 B1).

화면(frontend/ai365-mcmail.html)이 서버 상태를 쓰도록 스토어(app.mcmail)를 노출한다. 옛 이메일 업무 에이전트와 같은
접두(/api/email)를 이어 쓰며, 옛 라우터·스토어(app.email_api·app.email_agent)는 2026-09-28 에 삭제됐다.
- 조회: meta·dashboard·mails·mails/{id}·cases·cases/{id}·errors·log·search·notifications.
- 액션: 메일별 POST(classify·entity·link-case·new-case·erp·order·draft·draft-save·send·hold·complete·archive·spam),
  assign·errors/{id}/retry·scenario/{n}·reset. 응답 {email, case, errors, log, toast, nav} 을 화면이 그대로 반영한다.
  잘못된 요청은 422, 없는 id 는 404, 이미 다른 내용으로 있는 Sales Order 는 409.
  초안 본문 키는 draft-save·send 모두 'draft' 다(draft-save 는 필수, send 는 없으면 저장된 초안을 보낸다). entity 의
  'value' 도 필수다(키가 빠진 요청이 값을 지우지 않게).
- /ask: 업무 자동화 채팅(adapter.js 의 에이전트 실행 연출)이 쓰는 계약({question, chat_id?, acting_user_id?}
  → {chat_id, title, answer, exec}, 메시지 meta.kind='agent_exec'). 질문을 lite LLM 1회로 조회 대상과 조건에 분해하고(실패 시
  규칙) mcmail_query의 공통 검증을 거쳐 결정적 조회와 표 답변으로 답한다. 고객사·기간·상태·검색어와 복수 조회를 보존한다. 발송 같은 실행은 채팅에서 하지
  않으며, '실행은 화면에서' 안내는 명령·요청 어미('…보내줘', '…발송해 주세요')가 붙은 질문에만 붙인다.
- 권한: acting_user_id 가 숫자면 agent_email 노드 레벨 1 이상(아니면 403), 비었으면 데모 개방(슈퍼).
- 라벨: exec.agent_label·메시지 meta.source·403 문구는 모두 'M코스메틱 이메일 에이전트'(AGENT_LABEL)다.

M Cosmetic Email Agent API (/api/email). Exposes the store to the page under the old email agent's prefix; the old
router and store (app.email_api, app.email_agent) were deleted on 2026-09-28. Reads, per-mail actions and the
scenario/reset controls return payloads the page applies as-is (422 for invalid requests, 404 for unknown ids, 409 for
a Sales Order number already taken by other content). The draft body key is 'draft' for both draft-save (required)
and send (optional: the stored draft when absent), and entity's 'value' is required so a request missing it never
wipes a value. /ask serves the automation chat ({question, chat_id?, acting_user_id?} → {chat_id, title, answer,
exec}, stored with meta.kind='agent_exec'), extracting business targets and constraints with one lite LLM call (rules on
failure), validating the shared query contract, and answering from deterministic lookups; the "execute in the screen" banner is added only for imperative
requests. Gating: a numeric acting_user_id needs agent_email level >= 1 (else 403), empty means the open demo (super).
The exec agent_label, the message meta.source and the 403 text all use AGENT_LABEL, 'M코스메틱 이메일 에이전트'.
"""

import logging
import re

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app import access, db, llm, mcmail

logger = logging.getLogger("ai365.mcmail_api")

router = APIRouter(prefix="/api/email", tags=["email"])

AGENT_LABEL = "M코스메틱 이메일 에이전트"   # 카탈로그·워크플로우·어댑터 레지스트리와 같은 이름 / same name as catalog, flows and adapter


def _gate(acting_user_id: str) -> None:
    """에이전트 노드 게이팅 — agent_email 레벨≥1, ''=슈퍼(데모 개방) / agent-node gating; '' is super (open demo)"""
    eff = access.resolve_eff(acting_user_id)
    if eff is not None and (eff.get("nodes") or {}).get("agent_email", 0) < 1:
        raise HTTPException(status_code=403, detail=f"{AGENT_LABEL} 접근 권한이 없습니다")


def _call(fn, *args, **kwargs):
    """스토어 호출 — MailValidationError 를 HTTP 422/404 로 / store call; MailValidationError becomes 422/404"""
    try:
        return fn(*args, **kwargs)
    except mcmail.MailValidationError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from None


# ─────────────────────────────────────────────────────────────────────────────
# 조회 / reads
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/meta")
def meta(acting_user_id: str = "") -> dict:
    _gate(acting_user_id)
    return _call(mcmail.meta)


@router.get("/dashboard")
def dashboard(date: str = "", acting_user_id: str = "") -> dict:
    _gate(acting_user_id)
    return _call(mcmail.dashboard, date or None)


@router.get("/mails")
def mails(view: str = "", filter_: str = Query("todo", alias="filter"), q: str = "",
          date_from: str = Query("", alias="from"), date_to: str = Query("", alias="to"), acting_user_id: str = "") -> dict:
    _gate(acting_user_id)
    return _call(mcmail.list_emails, view or None, filter_, q, date_from or None, date_to or None)


@router.get("/mails/{email_id}")
def mail_detail(email_id: str, acting_user_id: str = "") -> dict:
    _gate(acting_user_id)
    return _call(mcmail.get_email, email_id)


@router.get("/cases")
def cases(filter_: str = Query("all", alias="filter"), q: str = "", date_from: str = Query("", alias="from"),
          date_to: str = Query("", alias="to"), acting_user_id: str = "") -> dict:
    _gate(acting_user_id)
    return _call(mcmail.list_cases, filter_, q, date_from or None, date_to or None)


@router.get("/cases/{case_id}")
def case_detail(case_id: str, acting_user_id: str = "") -> dict:
    _gate(acting_user_id)
    return _call(mcmail.get_case, case_id)


@router.get("/errors")
def errors(status: str = "open", date_from: str = Query("", alias="from"), date_to: str = Query("", alias="to"),
           acting_user_id: str = "") -> dict:
    _gate(acting_user_id)
    return _call(mcmail.list_errors, status, date_from or None, date_to or None)


@router.get("/log")
def log(n: int = 40, acting_user_id: str = "") -> dict:
    _gate(acting_user_id)
    return {"items": _call(mcmail.recent_log, n)}


@router.get("/search")
def search(q: str = "", acting_user_id: str = "") -> dict:
    _gate(acting_user_id)
    return _call(mcmail.search, q)


@router.get("/notifications")
def notifications(acting_user_id: str = "") -> dict:
    _gate(acting_user_id)
    return _call(mcmail.notifications)


# ─────────────────────────────────────────────────────────────────────────────
# 액션 — 본문은 모두 선택(acting_user_id 포함) / actions; every body is optional (acting_user_id included)
# ─────────────────────────────────────────────────────────────────────────────

class ActIn(BaseModel):
    acting_user_id: str = ""


class ClassifyIn(ActIn):
    classification: str
    intent: str | None = None


class EntityIn(ActIn):
    field: str
    # 필수 — 키가 빠진 요청이 값을 빈 문자열로 지우지 않게. 숫자(수량 등)도 받아 문자열로 저장한다.
    # required, so a request missing the key never wipes the value; numbers (quantities, ...) are stored as text
    value: str | int | float
    triage: bool = False


class LinkCaseIn(ActIn):
    caseId: str


class LangIn(ActIn):
    lang: str = "ko"


class DraftIn(ActIn):
    regen: bool = False
    lang: str = "ko"


class DraftSaveIn(ActIn):
    # 본문 키는 /send 와 같은 draft 이고 필수 — 키가 빠진 요청이 초안을 빈 문자열로 덮어쓰지 않게(없으면 422)
    # the body key is 'draft' like /send and required, so a request without it never blanks the draft (422 instead)
    draft: str


class SendIn(ActIn):
    draft: str | None = None   # None = 저장된 초안 그대로 발송 / None sends the stored draft as is


class HoldIn(ActIn):
    on: bool | None = None


class AssignIn(ActIn):
    kind: str
    id: str
    user: str


@router.post("/mails/{email_id}/classify")
def mail_classify(email_id: str, body: ClassifyIn) -> dict:
    _gate(body.acting_user_id)
    return _call(mcmail.classify, email_id, body.classification, body.intent)


@router.post("/mails/{email_id}/entity")
def mail_entity(email_id: str, body: EntityIn) -> dict:
    _gate(body.acting_user_id)
    return _call(mcmail.set_entity, email_id, body.field, body.value, triage=body.triage)


@router.post("/mails/{email_id}/link-case")
def mail_link_case(email_id: str, body: LinkCaseIn) -> dict:
    _gate(body.acting_user_id)
    return _call(mcmail.link_case, email_id, body.caseId)


@router.post("/mails/{email_id}/new-case")
def mail_new_case(email_id: str, body: ActIn | None = None) -> dict:
    _gate((body or ActIn()).acting_user_id)
    return _call(mcmail.new_case, email_id)


@router.post("/mails/{email_id}/erp")
def mail_erp(email_id: str, body: LangIn | None = None) -> dict:
    b = body or LangIn()
    _gate(b.acting_user_id)
    return _call(mcmail.run_erp, email_id, lang=b.lang)


@router.post("/mails/{email_id}/order")
def mail_order(email_id: str, body: ActIn | None = None) -> dict:
    _gate((body or ActIn()).acting_user_id)
    return _call(mcmail.create_order, email_id)


@router.post("/mails/{email_id}/draft")
def mail_draft(email_id: str, body: DraftIn | None = None) -> dict:
    b = body or DraftIn()
    _gate(b.acting_user_id)
    return _call(mcmail.draft, email_id, regen=b.regen, lang=b.lang)


@router.post("/mails/{email_id}/draft-save")
def mail_draft_save(email_id: str, body: DraftSaveIn) -> dict:
    _gate(body.acting_user_id)
    return _call(mcmail.save_draft, email_id, body.draft)


@router.post("/mails/{email_id}/send")
def mail_send(email_id: str, body: SendIn | None = None) -> dict:
    b = body or SendIn()
    _gate(b.acting_user_id)
    return _call(mcmail.send, email_id, text=b.draft)


@router.post("/mails/{email_id}/hold")
def mail_hold(email_id: str, body: HoldIn | None = None) -> dict:
    b = body or HoldIn()
    _gate(b.acting_user_id)
    return _call(mcmail.hold, email_id, b.on)


@router.post("/mails/{email_id}/complete")
def mail_complete(email_id: str, body: ActIn | None = None) -> dict:
    _gate((body or ActIn()).acting_user_id)
    return _call(mcmail.complete, email_id)


@router.post("/mails/{email_id}/archive")
def mail_archive(email_id: str, body: ActIn | None = None) -> dict:
    _gate((body or ActIn()).acting_user_id)
    return _call(mcmail.archive, email_id)


@router.post("/mails/{email_id}/spam")
def mail_spam(email_id: str, body: ActIn | None = None) -> dict:
    _gate((body or ActIn()).acting_user_id)
    return _call(mcmail.spam, email_id)


@router.post("/assign")
def assign(body: AssignIn) -> dict:
    _gate(body.acting_user_id)
    return _call(mcmail.assign, body.kind, body.id, body.user)


@router.post("/errors/{error_id}/retry")
def error_retry(error_id: str, body: LangIn | None = None) -> dict:
    b = body or LangIn()
    _gate(b.acting_user_id)
    return _call(mcmail.retry, error_id, lang=b.lang)


@router.post("/scenario/{n}")
def scenario(n: int, body: LangIn | None = None) -> dict:
    b = body or LangIn()
    _gate(b.acting_user_id)
    return _call(mcmail.inject_scenario, n, lang=b.lang)


@router.post("/reset")
def reset(body: ActIn | None = None) -> dict:
    _gate((body or ActIn()).acting_user_id)
    return _call(mcmail.reset)


# ─────────────────────────────────────────────────────────────────────────────
# /ask — 업무 자동화 채팅. 계약: {question, chat_id?, acting_user_id?} → {chat_id, title, answer, exec},
# 메시지 meta(kind='agent_exec')로 영속화(새로고침 복원). 분류는 lite LLM 1회, 실패하면 키워드 규칙.
# /ask — the automation chat: {question, chat_id?, acting_user_id?} → {chat_id, title, answer, exec}, persisted as
# message meta (kind='agent_exec') for refresh restore; one lite LLM call picks the lookup target, keyword rules back it up.
# ─────────────────────────────────────────────────────────────────────────────

# 쓰기(실행) 요청 판정 — 명령·요청 어미가 붙은 동사만 본다. '오늘 처리해야 할 메일', '인보이스 보내달라는 메일 있어?' 같은
# 조회 질문은 걸리지 않는다. 문장 끝 반말 명령('…발송해', '…보내라')과 영어 명령문 첫머리도 잡는다.
# Write-intent check — only verbs carrying an imperative or request ending count, so lookups such as '오늘 처리해야 할
# 메일' or '인보이스 보내달라는 메일 있어?' pass; a sentence-final casual imperative and a leading English imperative count too.
_WRITE_VERB = r"(?:보내|(?:발송|처리|등록|승인|반려|실행|회신|답장|전송)\s*해)"
_WRITE_RE = re.compile(
    _WRITE_VERB + r"\s*(?:줘|주세요|주십시오|줄래|주실래|주시겠|주라)"
    r"|" + _WRITE_VERB + r"\s*라?\s*[.!~]*\s*$"
    r"|^\s*(?:please\s+)?(?:send|approve|reject|register|submit|execute|process)\b",
    re.I)


def _classify(question: str) -> tuple[list[dict], str]:
    """조회 종류와 조건을 함께 추출하고 메인 채팅과 동일한 계약으로 검증한다."""
    from app import mcmail_query
    try:
        system = ("너는 M코스메틱 영업 메일 조회 계획기다. 실행 도구를 호출하지 않고 조회만 계획한다.\n" +
                  mcmail_query.QUERY_RULES +
                  f"\n상대 날짜 해석 기준일: {mcmail._server_today().isoformat()} (한국 시간)." +
                  "\n고객사 목록: " + ", ".join(mcmail.ERP_CUSTOMERS.values()))
        out = llm.generate([{"role": "user", "content": question or "오늘 처리 현황을 알려줘"}],
                           system=system, json_mode=True, tier="lite")
    except Exception:
        logger.warning("Email Agent /ask 분류 실패, 확인 가능한 조건으로 조회합니다.")
        return mcmail_query.queries_from_plan(question, {}), "rule"
    return mcmail_query.queries_from_plan(question, out if isinstance(out, dict) else {}), "llm"


def _read_tool(name: str, args: dict) -> dict:
    """페이지 /ask의 기존 내부 조회 경로. 읽기 두 종류만 허용한다."""
    if name == "get_mail":
        return mcmail.get_email(args["email_id"])
    if name != "get_work_status":
        raise ValueError("지원하지 않는 조회입니다.")
    target = args["target"]
    values = {k: v for k, v in args.items() if k != "target"}
    data, task, detail = mcmail.lookup(target, values or None)
    return {"target": target, "task": task, "detail": detail,
            "answer": mcmail.fallback_answer(data, task), "data": data}


def _answer(question: str) -> tuple[str, dict]:
    from app import mcmail_reads
    try:
        queries, how = _classify(question)
        answer, evidence = mcmail_reads.execute(queries, _read_tool)
        label = " · ".join(dict.fromkeys(mcmail.TARGET_LABELS.get(q["target"], "메일 상세") for q in queries))
        task = " / ".join(e["task"] for e in evidence)
        line = " / ".join(e["detail"] for e in evidence)
    except (ValueError, mcmail.MailValidationError) as exc:
        answer = str(exc)
        label, how = "조회 조건 확인", "clarify"
        task, line = "조회 조건을 확인하고 있습니다.", "조건을 임의로 생략해 전체 자료를 조회하지 않았습니다."
    write_intent = bool(_WRITE_RE.search((question or "").strip()))
    if write_intent:
        answer = ("> 발송이나 주문등록 같은 **실행**은 채팅에서 바로 처리하지 않습니다. Email Agent 화면에서 진행해 주세요. "
                  "아래는 판단에 필요한 현황입니다.\n\n") + answer
    exec_block = {
        "agent": "email", "agent_label": AGENT_LABEL,
        "tasks": [f"질문을 분석해 '{label}' 조회로 정했습니다.", task, "조회 결과를 근거로 답변을 정리했습니다."],
        "think": {"title": "업무 데이터를 조회합니다", "groups": [
            {"label": "질문을 분석합니다.", "lines": [
                f"AI가 질문을 '{label}' 조회로 분류했습니다." if how == "llm" else
                ("조회 조건을 더 구체적으로 알려주세요." if how == "clarify" else f"키워드 규칙으로 '{label}' 조회를 선택했습니다."),
                "조회 대상에 맞는 Email Agent 데이터를 골랐습니다."]},
            {"label": "실 데이터를 조회합니다.", "lines": [task, line]},
            {"label": "답변을 작성합니다.", "lines": [
                "추가 조건을 확인한 뒤 조회하겠습니다." if how == "clarify" else "조회한 데이터만 근거로 표와 요약을 만들었습니다.",
                "발송이나 주문등록 같은 실행은 Email Agent 화면에서 진행하도록 안내했습니다." if write_intent
                else "처리할 항목이 먼저 보이도록 정리했습니다."]},
        ]},
    }
    return answer, exec_block


class AskIn(BaseModel):
    question: str = ""
    chat_id: str = ""
    acting_user_id: str = ""


@router.post("/ask")
def ask(body: AskIn) -> dict:
    _gate(body.acting_user_id)
    question = body.question.strip()
    if body.chat_id and db.get_chat(body.chat_id) is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 채팅입니다")
    answer, exec_block = _answer(question)
    q = question or "브리핑해줘"
    meta_ = {"source": AGENT_LABEL, "kind": "agent_exec", "agent": "email", "exec": exec_block}
    if body.chat_id:
        chat = db.get_chat(body.chat_id)
    else:
        chat = db.create_chat(title=q[:15] + ("…" if len(q) > 15 else ""), scope="사내")
    db.add_message(chat["id"], "user", q)
    db.add_message(chat["id"], "assistant", answer, meta_)
    return {"chat_id": chat["id"], "title": chat["title"], "answer": answer, "exec": exec_block}
