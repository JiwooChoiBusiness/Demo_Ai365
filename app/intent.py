"""의도해석 계층 — 프롬프트·의도판단·계획 검증·되묻기 재개·문서생성 감지 (2026-08-28 분할).

pipeline.py 1400줄 비대화 해소를 위한 3분할의 1축. 여기의 이름들은 app.pipeline이 재수출하므로
기존 참조 경로(pipeline._judge_intent 등)는 그대로 동작한다.
"""
# Intent layer — prompts, intent judgment, plan validation, re-ask resume, docgen detection
# (2026-08-28 split). One of three axes of the pipeline split; app.pipeline re-exports these names,
# so existing references (pipeline._judge_intent, ...) keep working.

import json
import logging
import re
from datetime import datetime

from app import db, llm
from app.agents import AGENT_REGISTRY, AgentResult

logger = logging.getLogger("ai365.intent")


def _intent_system() -> str:
    from app.decisions import SYSTEM
    from app.tool_contracts import registry
    return SYSTEM + "\n사용 가능한 에이전트:\n" + json.dumps(registry(), ensure_ascii=False)


ANSWER_SYSTEM = """너는 답변 취합 Agent다. 사내 AI 어시스턴트로서, 아래 에이전트 실행 결과를 바탕으로 사용자의 마지막 질문에 대한 하나의 자연스러운 답변을 작성하라.
- 기본은 한국어로 답하되, 사용자가 영어 등 다른 언어로 질문하거나 특정 언어로 답을 요청하면 그 언어로 답한다.
- 성공한 결과의 내용은 충실히 전달한다.
- 실패(not_found)하거나 준비 중인 결과가 있으면, 성공한 부분은 정상적으로 전달하면서 실패 원인과 가능한 대안을 함께 안내한다.
- 결과에 없는 사실을 지어내지 않는다. 마크다운 기호 없이 단락 위주의 평문으로 쓴다."""

ANSWER_SYSTEM_BLEND = ANSWER_SYSTEM + (
    "\n- 사내 자료(에이전트 실행 결과)를 우선 근거로 삼아라. [웹 보완 정보]는 사내 자료가 "
    "다루지 못한 부분을 채우는 데에만 사용하고, 웹에서 가져온 내용은 그 출처가 웹임을 자연스럽게 밝혀라."
)

# '자동' 모드 — 내부 결과만으로 충분한지, 부족하면 웹에서 무엇을 보완할지 판단(경량)
# 'Auto' mode — judge whether internal results alone suffice, and if not, what to supplement from the web (lightweight)
GAP_SYSTEM = """너는 사내 AI 어시스턴트의 '웹 보완 판단' Agent다. 사용자의 마지막 질문과 사내 자료 기반 결과를 보고, 사내 자료만으로 질문이 충분히 답변되는지 JSON으로만 판단한다.

출력 형식:
{"complete": true, "missing": ""}

규칙:
- 사내 자료로 질문의 핵심이 충분히 답변되면 complete=true, missing="".
- 사내 자료가 일부만 답하거나 다루지 못한 부분이 있으면 complete=false, missing에 웹에서 추가로 검색할 내용만 짧은 한국어 질의로 적는다.
- 인사·잡담 등 애초에 자료가 필요 없는 경우도 complete=true."""

WEB_SUPPLEMENT_SYSTEM = (
    "웹 검색 결과를 활용해 다음 내용에 대한 핵심 사실을 한국어 평문으로 간결히 정리하라. "
    "확실하지 않은 내용은 단정하지 않는다."
)

DIRECT_SYSTEM = """너는 사내 AI 어시스턴트다. 대화 맥락을 참고해 사용자의 마지막 메시지에 간결하고 자연스럽게 답하라. 기본은 한국어로 답하되, 사용자가 영어 등 다른 언어로 질문하거나 특정 언어로 답을 요청하면 그 언어로 답한다. 마크다운 기호 없이 평문으로 쓴다."""

EXTERNAL_SYSTEM = """너는 AI 어시스턴트다. 웹 검색 결과를 활용해 사용자의 마지막 질문에 답하라. 기본은 한국어로 답하되, 사용자가 영어 등 다른 언어로 질문하거나 특정 언어로 답을 요청하면 그 언어로 답한다. 마크다운 기호 없이 단락 위주의 평문으로 쓴다."""

# 순차 발송(deliver) — 보고서 서술 지침(_deliver_answer). 발송 도구·받는사람은 그룹웨어 툴 콜링이 정한다.
# Sequential delivery — the report-style note for _deliver_answer. Send tools/recipients are decided by groupware.
_REPORT_NOTE = ("\n- 이 답변은 메일로 전달할 보고서다. 제목 한 줄로 시작하고, 핵심 내용을 항목별로 "
                "간결히 정리하라(불필요한 인사말·맺음말 없이).")

# 스트리밍 중단 안내(429·절단) — _stream_answer가 부분 답변에 덧붙이고, _deliver_answer는 이 표식이
# 보고서에 있으면 발송 confirm을 만들지 않는다(절단 보고서 발송 방지 — 적대 검증 반영).
# Mid-stream interruption note (429/cutoff) — appended to partial answers by _stream_answer; when the
# report contains it, _deliver_answer skips the send confirm (no truncated-report sends).
_INTERRUPT_NOTE = "(연결이 불안정해 응답이 여기서 중단되었습니다. 다시 요청하면 이어서 답변드립니다.)"


def _draft_params(draft: dict) -> list[dict]:
    """confirm 카드의 파라미터 필드 목록 — [{k, label, value, editable}] (2026-08-28 사용자 요청:
    요약 한 줄 대신 필요한 파라미터를 폼으로 보여준다). 메일 단건은 수정 가능(실행 시 override 반영)."""
    # The confirm card's parameter fields — [{k, label, value, editable}] (user request 2026-08-28:
    # show the required parameters as a form instead of a one-line summary). A single mail send is
    # editable (overrides apply at execution).
    kind = str(draft.get("kind") or "")
    p = draft.get("payload") or {}
    if kind == "mail.action.compose":
        return [
            {"k": "to", "label": "받는 사람", "value": str(p.get("to") or ""), "editable": True},
            {"k": "subject", "label": "제목", "value": str(p.get("subject") or ""), "editable": True},
            {"k": "body", "label": "본문", "value": str(p.get("body") or ""), "editable": True, "long": True},
        ]
    if kind == "groupware.send.batch":
        rows: list[dict] = []
        for i, it in enumerate((p.get("sends") or []), 1):
            ip = it.get("payload") or {}
            rows.append({"k": f"to{i}", "label": f"받는 사람 {i}",
                         "value": str(ip.get("to") or ip.get("target") or ""), "editable": False})
        first = next((it.get("payload") or {} for it in (p.get("sends") or [])
                      if it.get("kind") == "mail.action.compose"), {})
        if first.get("subject"):
            rows.append({"k": "subject", "label": "제목", "value": str(first["subject"]), "editable": False})
        return rows
    if kind in ("calendar.action.event", "calendar.action.meeting"):
        when = f"{p.get('start') or ''}~{p.get('end') or ''}".strip("~")
        rows = [
            {"k": "subject", "label": "제목", "value": str(p.get("subject") or ""), "editable": False},
            {"k": "when", "label": "일시", "value": when, "editable": False},
        ]
        if p.get("location"):
            rows.append({"k": "location", "label": "장소", "value": str(p["location"]), "editable": False})
        att = [a for a in (p.get("attendees") or []) if a]
        if att:
            rows.append({"k": "attendees", "label": "참석자", "value": ", ".join(att), "editable": False})
        return rows
    if kind in ("todo.action.complete", "todo.action.create"):
        return [{"k": "title", "label": "할 일", "value": str(p.get("title") or ""), "editable": False}]
    # M코스메틱 이메일 에이전트(2026-09-28) — 주문등록·발송 확인 카드는 실행될 값을 그대로 보여 준다(수정 불가:
    # 실행 때 카드 이후 값이 바뀌었으면 work.execute_action 이 멈춘다)
    # M Cosmetic Email Agent (2026-09-28): the order and send confirm cards show the exact values that will run (read-only;
    # work.execute_action stops when they changed after the card)
    if kind in ("email.action.order", "email.action.send"):
        if kind == "email.action.order":
            f = p.get("fields") or {}
            item = " · ".join(str(x) for x in (f.get("itemName"), f.get("itemCode")) if x)
            rows = [
                {"k": "mail", "label": "대상 메일", "value": f"{p.get('email_id') or ''} · {p.get('customer') or ''}", "editable": False},
                {"k": "subject", "label": "제목", "value": str(p.get("subject") or ""), "editable": False},
                {"k": "item", "label": "품목", "value": item, "editable": False},
                {"k": "qty", "label": "수량", "value": f"{f['quantity']} EA" if f.get("quantity") else "", "editable": False},
                {"k": "due", "label": "납기", "value": str(f.get("deliveryDate") or ""), "editable": False},
            ]
        else:
            rows = [
                {"k": "to", "label": "받는 사람", "value": f"{p.get('customer') or ''} <{p.get('to') or ''}>", "editable": False},
                {"k": "subject", "label": "제목", "value": str(p.get("subject") or ""), "editable": False},
                {"k": "body", "label": "본문", "value": str(p.get("draft") or ""), "editable": False, "long": True},
            ]
        # 처리 오류 재처리 카드(2026-09-28) — 맨 위에 어떤 오류를 다시 처리하는지 / retry card: which error is retried, on top
        if p.get("retry_error_id"):
            rows.insert(0, {"k": "retry", "label": "재처리", "editable": False,
                            "value": " · ".join(str(x) for x in (p["retry_error_id"], p.get("retry_message")) if x)})
        return rows
    return []


def _draft_preview(draft: dict) -> str:
    """confirm 카드 접이식 본문 미리보기 — 메일 발송(단건/배치)의 실제 본문. 그 외 액션은 빈 문자열
    (일정·할일은 summary가 전부라 미리보기 불요)."""
    # Collapsible body preview for the confirm card — the actual body of a mail send (single/batch).
    # Other actions return "" (calendar/todo summaries already carry everything).
    kind = str(draft.get("kind") or "")
    if kind == "mail.action.compose":
        return (draft.get("payload", {}).get("body") or "").strip()
    if kind == "groupware.send.batch":
        for it in (draft.get("payload", {}).get("sends") or []):
            if it.get("kind") == "mail.action.compose":
                return (it.get("payload", {}).get("body") or "").strip()
    return ""


# ── 문서 생성 감지(서버측) — 종전 adapter.js 키워드 가로채기를 파이프라인으로 이전(2026-08-28) ──
# 프론트가 스트림 전에 가로채던 결정 로직(ai365DocMatch)의 서버 포팅 + 의도판단 docgen 필드 보조.
# 매치되면 파이프라인이 {"type":"docgen"} 이벤트를 내고 종료 — 어댑터가 기존 질문 카드 흐름을 연다.
# ── Document-generation detection (server-side) — the adapter's pre-stream keyword interception moved
# into the pipeline (2026-08-28): a port of ai365DocMatch + the intent judge's docgen field as backup.
# On a match the pipeline emits {"type":"docgen"} and returns — the adapter opens the question card.
# 주의: Python의 \b는 한글도 단어문자로 취급해 'PPT로'에서 경계가 생기지 않는다(JS와 다름) —
# 라틴 토큰 뒤 경계는 ASCII 전용 부정 전방탐색 (?![a-z0-9])로 잡는다.
# Note: Python's \b treats Hangul as a word char, so 'PPT로' has no boundary (unlike JS) —
# latin-token boundaries use an ASCII-only negative lookahead (?![a-z0-9]) instead.
_DOC_FMTS = (
    ("pptx", "PPT", re.compile(r"(피피티|파워\s*포인트|슬라이드|발표\s*자료|프레젠테이션|ppt(x)?(?![a-z0-9])|presentation)", re.I)),
    ("xlsx", "Excel", re.compile(r"(엑셀|스프레드\s*시트|xlsx(?![a-z0-9])|excel(?![a-z0-9]))", re.I)),
    ("docx", "Word", re.compile(r"(워드\s*(문서|파일)?|docx(?![a-z0-9])|word(?![a-z0-9]))", re.I)),
    ("pdf", "PDF", re.compile(r"(pdf(?![a-z0-9])|피디에프)", re.I)),
    ("mp4", "영상", re.compile(r"(mp4(?![a-z0-9])|동영상|(교육|홍보|소개|발표)?\s*영상|비디오)", re.I)),
    # 이미지(2026-08-31 신규): '이미지'는 일상어와 겹쳐("브랜드 이미지") 조사/동사 결합형만 매치한다
    # image (new): the bare word collides with everyday usage, so only particle/verb-bound forms match
    ("image", "이미지", re.compile(
        r"(포스터|인포그래픽|썸네일|이미지로|그림으로|이미지(\s*파일)?\s*(을|를)?\s*(만들|생성|제작|뽑아)|png(?![a-z0-9]))", re.I)),
)
_DOC_VERB = re.compile(r"(만들|생성|작성|정리(해|하)|제작|뽑아)")
_DOC_EXCL = re.compile(r"(여는\s*법|사용법|단축키|열어\s*줘|열어줘|요약(해|하)|번역|읽어|첨부(된|한)|업로드(한|된)|변환(해|하)|합쳐|합치|병합)")
_DOC_EXT = re.compile(r"\.(pptx|pdf|docx|xlsx|mp4|png)(?![a-z0-9])", re.I)


def _docgen_match(text: str) -> dict | None:
    """문서 생성 요청 감지 + 주제 추출 — adapter.js ai365DocMatch와 동일 규칙(단일 진실 원천은 이제 서버)."""
    # Detect a docgen request and extract the topic — same rules as adapter.js ai365DocMatch
    # (the single source of truth now lives on the server).
    t = str(text or "")
    if not t.strip() or "@" in t or _DOC_EXCL.search(t):
        return None
    best = None
    for fmt, label, rx in _DOC_FMTS:
        m = rx.search(t)
        if m and (best is None or m.start() < best[3]):
            best = (fmt, label, m.group(0), m.start())
    if best is None:
        return None
    if not _DOC_VERB.search(t) and not _DOC_EXT.search(t):
        return None
    fmt, label, phrase, _ = best
    topic = t.replace(phrase, " ")
    topic = re.sub(r"(으로|로)?\s*(만들어|만들|생성|작성|정리|제작|뽑아)\S*", " ", topic)
    topic = re.sub(r"(해당|위|방금|이|지금까지|앞의|아까)\s*(내용|대화|결과|정리|자료|답변|채팅)(을|를)?\s*(가지고|바탕으로|기반으로|참고(해|하여)?)?", " ", topic)
    topic = re.sub(r"(을|를|좀|해\s*줘(요)?|주세요|부탁해(요)?)", " ", topic)
    topic = re.sub(r"\s+", " ", topic).strip()
    if len(topic) < 2:
        topic = ""
    return {"fmt": fmt, "label": label, "topic": topic}


def _validate_plan(intent: dict) -> dict | None:
    """v1 순차 계획과 v2 의존성 계획을 검증한다. 잘못된 단계는 보정 대상으로 남긴다."""
    from app.planning import normalize_plan
    return normalize_plan(intent.get("plan"))


def _await_send_state(chat_id: str) -> dict | None:
    """직전 어시스턴트 메시지가 받는사람 되묻기(meta.await_recipient)였는지 — 결정적 재개의 신뢰 원천.

    문구 매칭이 아니라 meta를 읽으므로 취합 LLM의 재서술과 무관하게 동작한다."""
    # Whether the most recent assistant message was a recipient re-ask (meta.await_recipient) — the trusted
    # source for deterministic resume. Reads meta, not prose, so aggregation-LLM paraphrasing can't break it.
    for m in reversed(db.list_messages(chat_id)):
        if m.get("role") == "assistant":
            meta = m.get("meta") or {}
            return meta if meta.get("await_recipient") else None
    return None


def _recipientish(message: str) -> bool:
    """되묻기 답이 받는사람 지정으로 보이는가 — '<이름>에게/한테/께'(경계 검사) 또는 본인 지정 어휘.

    단순 부분문자열('함께'·'께서'·'에게서' 오탐)이 아니라 그룹웨어의 수신자 추출 정규식을 재사용한다 —
    오탐이면 결정적 재개가 사용자의 새 요청을 하이재킹한다(적대 검증 반영)."""
    # Does the reply look like a recipient designation — '<name>에게/한테/께' (boundary-checked) or an
    # explicit self word. Reuses groupware's recipient regex instead of naive substrings ('함께'/'께서'/
    # '에게서' false positives) — a false positive lets deterministic resume hijack a fresh request.
    from app.agents import groupware as groupware_agent  # 지연 임포트 / lazy
    return bool(groupware_agent._extract_recipient(message)          # noqa: SLF001
                or groupware_agent._is_self_send(message))           # noqa: SLF001


# 재작성 Agent 프롬프트 — 지시어 발송 중 '재작성/요약/정리해서 보내줘'의 콘텐츠 단계(새 조회 없음).
# Rewrite-agent prompt — the content stage of "rewrite/summarize this and send it" (no new lookups).
REWRITE_SYSTEM = """너는 재작성 Agent다. 대화에서 사용자가 가리키는 직전 어시스턴트 답변(기존 내용)을 사용자의 재작성 요청(형식·톤·대상 — 예: 경영진 보고용, 요약본)에 맞춰 다시 작성하라.
- 새로운 조회·사실 추가 없이 기존 내용만 재구성한다.
- 마크다운 기호 없이 평문으로 쓴다."""

# 변형 어휘 — 지시어 발송이 '그대로 발송'이 아니라 '재작성 후 발송'인지 판별.
# Transform vocabulary — whether an anaphora send wants a REWRITE before sending, not a verbatim send.
_TRANSFORM_WORDS = ("재작성", "다시 작성", "다시 써", "요약", "정리해", "다듬", "바꿔", "고쳐", "수정해", "번역")


def _transform_send(text: str) -> bool:
    return any(w in text for w in _TRANSFORM_WORDS)


def _anaphora_ctx_source(context: list[dict], message: str) -> str:
    """되묻기 답변 턴에서 원 지시어 발송 요청을 복원 — 재제출 텍스트("누구에게 … 보낼까요? → 답")에는
    '해당 내용' 지시어가 사라지므로, 최근 사용자 메시지에서 지시어 발송 원문을 찾아 돌려준다."""
    # Recover the original anaphora-send request on a clarify-answer turn — the resubmitted text
    # ("who should I send it to? → answer") no longer carries the "this content" reference, so scan
    # recent user messages for the original anaphora send and return it.
    # 되묻기 답변 턴 감지 — 어댑터 재제출 형식('질문 → 답')이 1차 신호(문구 무관·결정적),
    # '누구에게…보낼/보내드릴…' 문구는 보조 신호(LLM이 질문 문구를 바꿔도 견디게).
    # Clarify-answer detection — the adapter's resubmission format ('question → answer') is the primary,
    # deterministic signal; the '누구에게 … 보낼' phrasing is secondary (robust to LLM wording changes).
    if not ((" → " in message) or ("누구에게" in message and "보낼" in message)):
        return ""
    seen = 0
    for m in reversed(context or []):
        if m.get("role") != "user":
            continue
        c = (m.get("content") or "").strip()
        if c == message:
            continue
        if _anaphora_send(c):
            return c
        seen += 1
        if seen >= 3:
            break
    return ""


def _anaphora_send(message: str) -> bool:
    """'해당/이/위 내용(으로) … 메일 보내줘' — 기존 답변을 가리키는 발송인가(콘텐츠 재생성 불필요).

    이 경우 deliver(콘텐츠 재실행→보고서)가 아니라 그룹웨어 직접 발송으로 보내야 한다:
    본문은 직전 답변(_last_content_answer)에서 오고, 파이프라인이 다시 돌지 않는다(2026-08-28 사용자 지적)."""
    # "Send this/that content by mail" — a send that references the EXISTING answer (no content regen).
    # Must go to the direct groupware send, not deliver (which re-runs content agents into a report):
    # the body comes from the previous answer, and the pipeline does not run again (user feedback 2026-08-28).
    low = message.lower()
    refs = ("이 내용", "해당 내용", "위 내용", "방금 내용", "그 내용", "이걸", "그걸", "위 답변", "방금 답변")
    return (any(r in message for r in refs)
            and any(v in message for v in ("보내", "발송", "전송"))
            and (any(k in message for k in ("메일", "이메일")) or "mail" in low or "outlook" in low))


def _send_intentish(message: str) -> bool:
    """발송 요청으로 보이는가(결정적) — 의도판단 완전 실패 시 잡담 취급을 막는 최소 가드."""
    # Does the message look like a send request (deterministic) — the minimal guard so that a total
    # intent-judgment failure doesn't treat a send request as small talk.
    low = message.lower()
    return (any(v in message for v in ("보내", "발송", "전송"))
            and (any(k in message for k in ("메일", "이메일")) or "mail" in low or "outlook" in low))


def _connectors_block(connectors: list[dict] | None) -> str:
    from app.tool_contracts import registry
    return "\n연결된 커넥터 명세:\n" + json.dumps(
        [r for r in registry(connectors) if r["kind"] != "agent"], ensure_ascii=False)


def _judge_intent(context: list[dict], connectors: list[dict] | None = None,
                  allowed_agents: list[str] | None = None, eff: dict | None = None,
                  scope_files: dict | None = None) -> dict:
    """요구사항을 먼저 보존하고, 사용 가능한 대상을 선택한 뒤 v3 실행 계획을 만든다."""
    from app.request_planning import judge
    return judge(context, connectors, allowed_agents, eff, scope_files)


def _judge_gap(context: list[dict], results: dict[str, AgentResult]) -> dict:
    """'자동' 모드 — 내부 결과만으로 충분한지, 부족하면 웹에서 무엇을 보완할지 판단(경량).

    실패하면 보완을 생략(complete=True)해 내부 답변을 그대로 쓴다.
    """
    # 'Auto' mode — judge whether internal results alone suffice, and if not, what to supplement from the web (lightweight).
    #
    # On failure, skip supplementation (complete=True) and use the internal answer as is.
    internal = [
        {
            "agent": k,
            "status": r.get("status"),
            "text": (r.get("text") or "")[:1500],
            "fail_reason": r.get("fail_reason"),
        }
        for k, r in results.items()
    ]
    prompt = context + [
        {
            "role": "user",
            "content": "[사내 자료 결과]\n"
            + json.dumps(internal, ensure_ascii=False)
            + "\n\n위 사내 자료만으로 바로 앞 질문이 충분히 답변되는지 판단하라.",
        }
    ]
    try:
        out = llm.generate(prompt, system=GAP_SYSTEM, json_mode=True, tier="lite")
        if isinstance(out, dict):
            return out
    except Exception:
        logger.warning("웹 보완 판단 실패 — 내부 답변 유지", exc_info=True)
    return {"complete": True, "missing": ""}


def _normalize_options(options) -> list[dict]:
    out = []
    for o in options or []:
        if isinstance(o, dict):
            label = str(o.get("label") or o.get("value") or "").strip()
            value = str(o.get("value") or label).strip()
        else:
            label = value = str(o).strip()
        if label:
            out.append({"value": value, "label": label})
    return out[:4]


def _lang_note(text: str) -> str:
    """사용자 질문 언어에 맞춰 최종 답변 언어를 강제하는 시스템 지시.

    취합 단계에서는 모델에 전달되는 마지막 입력이 한국어 결과 블록이라 한국어로 쏠리기 쉽다.
    질문이 한글이 아니면(영어 등) 결과·중간노트 언어와 무관하게 그 언어로 답하도록 명시한다.
    """
    # System instruction that forces the final answer language to match the user's question language.
    #
    # In the aggregation step, the last input passed to the model is the Korean result block, so it tends to lean toward Korean.
    # If the question is not Korean (e.g., English), explicitly instruct answering in that language regardless of the language of results/intermediate notes.
    t = text or ""
    if re.search(r"[가-힣]", t):
        return ""  # 한국어 질문 — 기본값(한국어), 별도 지시 불필요
        # Korean question — default (Korean), no separate instruction needed
    if re.search(r"[A-Za-z]", t):
        return ("\n\n[LANGUAGE] The user's request is written in English. Write the ENTIRE final "
                "answer in English, regardless of the language of the source materials or intermediate notes.")
    return ""
