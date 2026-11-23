"""채팅 CRUD API + 파이프라인 SSE 스트림."""
# Chat CRUD API + pipeline SSE stream.

import json
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app import cite, collections_store, db, llm, pipeline, runs

logger = logging.getLogger("ai365.chats")

router = APIRouter(prefix="/api/chats")

TITLE_SYSTEM = (
    "사용자의 첫 질문을 15자 내외의 간결한 한국어 채팅 제목으로 요약하라. "
    "따옴표나 마침표 없이 제목 텍스트만 출력하라."
)


class ChatCreate(BaseModel):
    first_message: str
    scope: Literal["자동", "사내", "외부"] = "자동"
    # 컬렉션(프로젝트) 채팅이면 그 컬렉션 id — 이 태그가 붙은 채팅은 stream이 컬렉션 재료(지침·파일·
    # 쉐어포인트 링크)를 매 질문의 답변 맥락으로 자동 주입한다(후속 질문 포함).
    # For a collection (project) chat, the collection id — tagged chats get the collection material
    # (instructions/files/SharePoint links) auto-injected as answer context on EVERY question.
    coll: str = ""
    # 컴포저 컬렉션 첨부(2026-09-08): 고른 파일 이름(빈 목록 = 컬렉션 전체) + 사용자 말풍선 칩 메타 {coll, coll_name, file}
    # Composer collection attach (2026-09-08): picked file names (empty = whole collection) + user-bubble chip meta
    coll_files: list[str] = []
    attach: dict = {}
    # 워크플로우 모드(2026-09-11): 홈 컴포저 [워크플로우] 알약으로 미리 켠 모드 — 새 채팅에 그대로 실린다(구성원 검사는 실행 시 /api/flows/run)
    # Workflow mode (2026-09-11): pre-selected in the home composer's [Workflow] pill — carried into the new chat (membership is checked at run time)
    flow_id: str = ""
    flow_name: str = ""


class ChatPatch(BaseModel):
    """이름 바꾸기(title) 또는 컬렉션 묶기(coll·coll_files, 2026-09-08) 또는 워크플로우 모드(flow_id·flow_name, 2026-09-11;
    빈 flow_id = 모드 끄기 + 그 채팅의 미완 워크플로우 run 취소) — 보낸 필드만 바꾼다"""
    # Rename (title), collection binding (coll, coll_files) or workflow mode (flow_id, flow_name, 2026-09-11; an empty
    # flow_id turns the mode off and cancels the chat's unfinished workflow runs) — only the fields sent change
    title: str | None = None
    coll: str | None = None
    coll_files: list[str] | None = None
    flow_id: str | None = None
    flow_name: str | None = None


def _clean_files(files) -> list[str]:
    """첨부 파일 이름 정리 — 문자열·비공백·200자·최대 20개 / tidy attachment file names — strings, non-blank, 200 chars, 20 max"""
    out: list[str] = []
    for x in (files or []):
        s = str(x or "").strip()[:200]
        if s and s not in out:
            out.append(s)
    return out[:20]


def _clean_attach(att) -> dict:
    """말풍선 칩 메타 정리 — coll·coll_name·file 문자열만 / tidy the bubble chip meta — coll, coll_name, file strings only"""
    if not isinstance(att, dict) or not str(att.get("coll") or "").strip():
        return {}
    return {k: str(att.get(k) or "").strip()[:200] for k in ("coll", "coll_name", "file")}


def _resolve_flow(flow_id, flow_name) -> tuple[str, str, dict | None]:
    """워크플로우 모드 값 정리(2026-09-11) — 존재하는 워크플로우만, 이름은 서버 저장분으로 교체(표시 스냅샷). 없으면 ('', '', None).
    세 번째 값은 찾은 워크플로우(2026-09-30 — 첫 사용자 행의 워크플로우 칩 meta.flow 가 단계 수를 싣는다)."""
    # Tidy workflow-mode values (2026-09-11) — existing flows only; the name is replaced by the stored one. Else ('', '', None).
    # The third value is the flow found (2026-09-30: the first user row's workflow chip meta.flow carries its stage count).
    fid = str(flow_id or "").strip()[:40]
    if not fid:
        return "", "", None
    from app import flows
    flow = flows.find_flow(fid)
    if flow is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 워크플로우입니다")
    return fid, (flow.get("name") or str(flow_name or "")).strip()[:60], flow


def _clean_flow(flow_id, flow_name) -> tuple[str, str]:
    """_resolve_flow 의 (id, 이름)만 / only the (id, name) of _resolve_flow"""
    fid, fname, _flow = _resolve_flow(flow_id, flow_name)
    return fid, fname


def _make_title(first_message: str) -> str:
    payload = TITLE_SYSTEM + "\n" + first_message[:500]
    cached = db.cache_get("title", payload)
    if cached:
        logger.info("제목 캐시 적중")
        return cached
    try:
        title = llm.generate(first_message[:500], system=TITLE_SYSTEM, tier="lite")
        title = (title or "").strip().strip("\"'“”").splitlines()[0].strip()
        if title:
            title = title[:30]
            db.cache_set("title", payload, title)
            return title
    except Exception:
        logger.warning("제목 생성 실패 — 첫 메시지 앞부분으로 대체", exc_info=True)
    return first_message[:15] + ("…" if len(first_message) > 15 else "")  # 폴백은 캐시하지 않음
    # The fallback is not cached


@router.get("")
def get_chats() -> list[dict]:
    return db.list_chats()


@router.post("")
def create_chat(body: ChatCreate) -> dict:
    text = body.first_message.strip()
    if not text:
        raise HTTPException(status_code=422, detail="first_message가 비어 있습니다")
    flow_id, flow_name, flow = _resolve_flow(body.flow_id, body.flow_name)
    # 워크플로우 채팅(2026-09-30 워크플로우 채팅 개편): 제목 = 워크플로우 이름(최대 60자, LLM 제목 요약 없음) — 그 밖은 종전대로 LLM 요약
    # Workflow chat (2026-09-30 workflow-chat redesign): title = the workflow name (60 chars max, no LLM title) — otherwise the LLM summary
    title = flow_name.strip()[:60] if flow_name.strip() else _make_title(text)
    # 존재하지 않는 컬렉션 id는 무시(태그 없이 생성) — 삭제 직후 경합 등에서 채팅 생성 자체는 막지 않는다.
    # An unknown collection id is ignored (created untagged) — e.g. a race right after deletion must not block chat creation.
    coll = body.coll.strip() or None
    if coll and collections_store.get_collection(coll) is None:
        coll = None
    chat = db.create_chat(title=title, scope=body.scope, coll=coll,
                          coll_files=_clean_files(body.coll_files) if coll else None,
                          flow_id=flow_id, flow_name=flow_name)
    # 첫 사용자 메시지를 저장해 새로고침 후에도 대화 복원이 가능하게 한다.
    # Save the first user message so the conversation can be restored even after a refresh.
    # (STEP 4의 스트리밍 질의는 이 메시지를 중복 저장하지 않도록 처리할 것)
    # (STEP 4's streaming query must handle this so the message is not saved twice)
    # 컴포저 컬렉션 첨부 칩(2026-09-08): 첫 사용자 행에 meta.attach — 새로고침 뒤 말풍선 칩 복원용
    # Composer collection attachment chip (2026-09-08): meta.attach on the first user row — restores the bubble chip after reload
    att = _clean_attach(body.attach) if coll else {}
    meta: dict = {"attach": att} if att else {}
    if flow is not None:
        # 워크플로우 칩(2026-09-30): 실행을 시작하는 첫 사용자 행에 meta.flow {id, name, stages(단계 수)} — 이어지는
        # /api/flows/run 은 같은 내용의 마지막 사용자 행을 다시 저장하지 않는다(flows._build_context)
        # Workflow chip (2026-09-30): meta.flow {id, name, stages (stage count)} on the first user row that starts the run;
        # the following /api/flows/run never stores the same last user row again (flows._build_context)
        meta["flow"] = {"id": flow_id, "name": flow_name, "stages": len(flow.get("stages") or [])}
    db.add_message(chat["id"], "user", text, meta or None)
    return {"id": chat["id"], "title": chat["title"]}


class StreamBody(BaseModel):
    message: str
    scope: Literal["자동", "사내", "외부"] = "자동"
    # 컴포저에서 사용자가 직접 고른 라우팅 분야(에이전트 키). 비면 의도판단이 자동 라우팅.
    # The routing field (agent key) the user picked directly in the composer. If empty, intent detection routes automatically.
    agents: list[str] = []
    # 컬렉션(프로젝트) 채팅이면 그 컬렉션의 지침. 답변 시스템 프롬프트에 맥락으로 주입된다.
    # For a collection (project) chat, this is that collection's instructions. Injected as context into the answer system prompt.
    instructions: str = ""
    # 뷰애즈 신원(Phase 3) — 전환된 사용자의 멤버 번호. 빈 값이면 슈퍼관리자(나, 게이팅 우회).
    # View-as identity (Phase 3) — the switched user's member number. Empty means super admin (나, gating bypassed).
    acting_user_id: str = ""
    # 선택 범위(권한 ∩ 선택): knowledge_files/data_tables/data_bi, work:bool, workers:[email|edu].
    # workers 누락은 종전 업무 범위, 명시한 빈 목록은 업무 하위 에이전트 미선택(범위를 넓히지 않음).
    # Worker scope is optional; absence keeps legacy scope, an explicit empty list selects no workers.
    scope_files: dict = {}
    # 예약 작업 페이지 입력창(2026-09-07): true 면 문장을 무조건 예약 요청으로 다룬다(자연어 예약 가로채기 강제)
    # Schedules page input (2026-09-07): true forces the natural-language schedule interception
    schedule: bool = False
    resume_id: str = ""
    # 탐색 미니 채팅(2026-08-23 에이전트 모드 3차): [탐색] 패널에서 참조 문서로 좁혀 묻는 질문. 본 채팅에
    # 그대로 저장되지만(맥락 '이어가기' 보장) meta.kind='explore'로 표시돼 본문 복원에서는 숨겨진다.
    # Explore mini-chat (agent-mode round 3): questions asked in the [Explore] panel, scoped to the
    # referenced documents. Stored in the same chat (context continuity) but tagged meta.kind='explore'
    # so the main-thread restore hides them.
    explore: bool = False
    # 탐색 앵커(2026-08-24 2차): [탐색]이 달린 앵커 답변의 message id — 탐색 하나하나가 자기 히스토리를 갖는다
    # Exploration anchor (round 2): the anchor answer's message id — each exploration keeps its own history
    explore_anchor: str = ""
    # 컴포저 컬렉션 첨부 칩 메타(2026-09-08) — 있으면 이 사용자 행을 meta.attach 와 함께 저장한다(말풍선 칩 복원)
    # Composer collection attachment chip meta (2026-09-08) — when present, this user row is saved with meta.attach (bubble chip restore)
    attach: dict = {}
    # 답 형식(2026-10-27, OpenUI): "auto"/"openui" = 서버 전역 OPENUI_MODE 를 따름, "markdown" = 이 요청은 OpenUI 를 쓰지 않음(화면의 "UI 답변" 끄기)
    # Answer format (2026-10-27, OpenUI): "auto"/"openui" follow the server-wide OPENUI_MODE; "markdown" turns OpenUI off for
    # this request (the page's "UI answers" switch off)
    ui_format: str = "auto"


# 스트림 이벤트에서 실행 트레이스를 모은다 — 어댑터의 실행 블록(진행줄·think 트리)이 새로고침 후에도
# 같은 모습으로 복원되도록 답변 메시지 meta.trace에 덧붙인다(pipeline.py 무수정 — 여기서 관찰만).
# Collects the execution trace from stream events so the adapter's execution block (progress lines,
# think tree) restores identically after refresh — appended to the answer's meta.trace
# (pipeline.py stays frozen; this only observes).
def _trace_collect(trace: dict, ev: dict) -> None:
    t = ev.get("type")
    if t == "thinking" and ev.get("text"):
        # 어댑터는 task_tree 이후(실행 프레임 생성 후)의 thinking만 진행줄로 그린다 — 그 전(의도 분석 등)은 기록하지 않아
        # 복원이 라이브와 같아진다(리뷰 확정).
        # The adapter turns 'thinking' into progress lines only after task_tree (frame exists) — earlier ones
        # (intent analysis etc.) are skipped so restore matches live (review finding).
        if not trace["tasks"]:
            return
        trace["thinking"].append(ev["text"])
        trace["lines"].append({"t": "thinking", "text": ev["text"]})   # 이벤트 순서 보존 / event order kept
    elif t == "task_tree":
        trace["parallel"] = bool(ev.get("parallel"))
        trace["tasks"] = [{"id": x.get("id"), "label": x.get("label"),
                           "children": [c.get("label") for c in (x.get("children") or [])]}
                          for x in (ev.get("tasks") or [])]
        if ev.get("stages"):
            trace["stages"] = ev["stages"]
    elif t == "stage_status":
        trace["lines"].append({"t": "stage", **{k: ev[k] for k in ("stage", "status", "failed") if k in ev}})
    elif t == "agent_status" and ev.get("task_id"):
        cur = trace["status"].setdefault(ev["task_id"], {})
        cur["status"] = ev.get("status")
        if ev.get("detail"):
            cur["detail"] = ev["detail"]
        line = {"t": "status", "task_id": ev["task_id"], "status": ev.get("status"), "detail": ev.get("detail")}
        # 로컬 전용 카드 표시(2026-10-28, task_runner · answers._local_stage 의 agent_status.local_only)도 남겨 복원이 라이브와 같게 그린다.
        # 있을 때만 싣는다(종전 줄 모양 그대로). / the local-only card mark is kept so restore draws as live; only when present
        if ev.get("local_only"):
            cur["local_only"] = True
            line["local_only"] = True
        trace["lines"].append(line)


@router.post("/{chat_id}/stream")
async def stream_chat(chat_id: str, body: StreamBody) -> EventSourceResponse:
    chat = db.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 채팅입니다")
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="message가 비어 있습니다")
    # 채팅당 실행은 하나(2026-09-04) — 메시지 선저장보다 먼저 거절해 중복 사용자 행을 남기지 않는다
    # One run per chat (2026-09-04) — rejected before the pre-save so no duplicate user row is left behind
    # 탐색 미니채팅은 별도 키(chat_id:explore)로 등록한다(리뷰 반영) — 본문 스레드와 서로 막지 않고, 채팅 run_state·
    # attach(본문 재접속) 대상도 아니다. / Explore mini-chats register under their own key (chat_id:explore) — they
    # neither block the main thread nor touch the chat run_state / attach.
    run_key = _run_key(chat_id, bool(body.explore))
    if runs.is_running(run_key):
        raise HTTPException(status_code=409, detail="이미 답변을 생성 중입니다")
    # 탐색 질문은 사용자 메시지를 먼저 kind='explore'로 저장한다 — 파이프라인의 _build_context는
    # 마지막 사용자 메시지가 같은 내용이면 중복 저장하지 않는다(기존 계약 활용).
    # Explore questions pre-save the user message with kind='explore' — the pipeline's _build_context
    # skips re-saving when the last user message already matches (existing contract).
    # 탐색 히스토리(2026-08-24, 사용자 요청): 행에 에이전트도 함께 남겨 어댑터가 (채팅×에이전트) 단위로
    # 패널 스레드를 복원할 수 있게 한다 — 별도 저장소·표면 없이 기존 숨김 행이 그대로 히스토리가 된다.
    # Explore history (user request): rows also carry the agent so the adapter can restore the panel thread
    # per (chat × agent) — the existing hidden rows ARE the history, no separate store or surface.
    explore_agent = (body.agents[0] if body.agents and body.agents[0] in ("knowledge", "data", "groupware") else "knowledge") if body.explore else ""
    explore_anchor = str(body.explore_anchor or "")[:64] if body.explore else ""
    if body.explore:
        db.add_message(chat_id, "user", message, {"kind": "explore", "agent": explore_agent, "anchor": explore_anchor})
    else:
        # 직전 행이 **숨겨진 탐색 질문**이고 내용이 같으면 보이는 사용자 행을 먼저 저장한다 — 파이프라인의
        # "마지막 사용자 메시지와 같으면 저장 생략" 규칙이 숨은 행에 맞아 본문 질문이 사라지는 것을 막는다(리뷰 확정).
        # If the previous row is a HIDDEN explore question with the same text, save the visible user row first —
        # otherwise the pipeline's "skip if equal to the last user message" rule would match the hidden row and
        # the main-thread question would vanish on restore (review finding).
        prev = db.last_message(chat_id)
        if (prev and prev["role"] == "user" and prev["content"] == message
                and (prev.get("meta") or {}).get("kind") == "explore"):
            db.add_message(chat_id, "user", message)

    # 컴포저 컬렉션 첨부 칩(2026-09-08): 사용자 행을 meta.attach 와 함께 먼저 저장 — 파이프라인의
    # "마지막 사용자 메시지와 같으면 저장 생략" 규칙이 중복 저장을 막는다(탐색 질문 제외).
    # Composer collection attachment chip (2026-09-08): save the user row with meta.attach first — the pipeline's
    # "skip when equal to the last user message" rule prevents a duplicate (explore questions excluded).
    att = _clean_attach(body.attach) if not body.explore else {}
    if att:
        db.add_message(chat_id, "user", message, {"attach": att})

    # 컬렉션 채팅(chats.coll 태그)은 컬렉션 재료(지침·파일 본문·쉐어포인트 링크)를 서버에서 조합해
    # 주입한다 — 클라이언트 전송값과 무관하게 첫 질문·후속 질문 모두 같은 맥락이 유지된다
    # (run_pipeline의 기존 instructions 계약 재사용, pipeline.py 무수정).
    # Collection chats (chats.coll tag) get the collection material (instructions, file bodies,
    # SharePoint links) composed server-side — the same context holds for first and follow-up
    # questions regardless of what the client sends (reuses run_pipeline's instructions contract).
    instructions = body.instructions or ""
    if chat.get("coll"):
        try:
            # coll_files(2026-09-08): 컴포저 첨부에서 파일을 골랐으면 그 파일 본문만 / picked files only, when the composer attachment chose some
            coll_ctx = collections_store.context_for(chat["coll"], chat.get("coll_files") or None)
        except Exception:  # noqa: BLE001 — 맥락 조합 실패가 답변을 막지 않는다 / never blocks the answer
            logger.warning("컬렉션 맥락 조합 실패 — 컬렉션 재료 없이 진행", exc_info=True)
            coll_ctx = ""
        if coll_ctx:
            instructions = coll_ctx + (("\n\n추가 지침:\n" + instructions.strip())
                                       if instructions.strip() else "")

    # 백그라운드 실행(2026-09-04): 파이프라인 소비는 프로듀서 태스크가 끝까지 수행하고(연결과 무관),
    # 이 응답은 그 실행의 구독자다 — 클라이언트가 끊겨도 실행은 계속되며, 중단은 POST /stop 으로만.
    # Background run (2026-09-04): the producer task consumes the pipeline to the end regardless of the
    # connection; this response only subscribes. Client disconnects never stop it — only POST /stop does.
    try:
        run = runs.start(run_key, _produce(chat, chat_id, body, message, instructions, explore_agent, explore_anchor),
                         on_finish=_on_run_finish, explore=bool(body.explore))
    except runs.AlreadyRunning:
        raise HTTPException(status_code=409, detail="이미 답변을 생성 중입니다")
    if not body.explore:
        db.set_run_state(chat_id, "running", unseen=0)
    return _subscribe_response(run)


def _run_key(chat_id: str, explore: bool) -> str:
    """실행 레지스트리 키 — 본문 스레드는 chat_id, 탐색 미니채팅은 chat_id:explore"""
    # Registry key — main thread: chat_id, explore mini-chat: chat_id:explore
    return chat_id + ":explore" if explore else chat_id


async def _produce(chat: dict, chat_id: str, body: StreamBody, message: str, instructions: str,
                   explore_agent: str, explore_anchor: str):
    """프로듀서 — 종전 stream_chat 제너레이터 본문 그대로(이벤트 dict 를 낸다; JSON 직렬화는 구독 응답에서).
    취소(STOP)는 CancelledError 로 흘러 들어와 finally 만 돈다 — 부분 답변 저장은 파이프라인 예외 경로 담당
    (answers._stream_answer 는 Exception 만 잡으므로 취소 시엔 저장 없이 조용히 끝난다)."""
    # Producer — the former stream_chat generator body verbatim (yields event dicts; JSON happens in the
    # subscriber response). A STOP arrives as CancelledError and only runs the finally — saving a partial
    # answer belongs to the pipeline's exception path (answers._stream_answer catches Exception only, so a
    # cancellation ends quietly without a save).
    trace = {"thinking": [], "tasks": [], "parallel": False, "status": {}, "lines": []}
    answer_id = None   # 파이프라인이 done에 실어 주는 저장 답변 id / the saved answer id carried by 'done'
    answer_text = []   # 토큰 누적 — 각주 귀속(cite)용 / token accumulation for footnote attribution
    enriched_sources = None
    from app.run_context import MESSAGE_LANE
    lane_token = MESSAGE_LANE.set("explore" if body.explore else "chat")
    try:
        # 채팅 커넥터 라우팅은 2026-09-11 폐지(API 는 워크플로우 전용) — 파이프라인에 커넥터를 넘기지 않는다
        # Chat connector routing was retired 2026-09-11 (APIs are workflow-only) — no connectors reach the pipeline
        async for ev in pipeline.run_pipeline(chat, message, body.scope, body.agents,
                                              instructions, body.acting_user_id, body.scope_files,
                                              allow_schedule=not body.explore, force_schedule=bool(body.schedule),
                                              connectors=[], resume_id=body.resume_id,
                                              execution_lane="explore" if body.explore else "chat",
                                              ui_format=body.ui_format):
            if ev.get("type") == "segment_start":
                if answer_id:
                    saved_meta = {"trace": trace}
                    if enriched_sources is not None:
                        saved_meta["sources"] = enriched_sources
                    db.update_message_meta(answer_id, saved_meta)
                trace = {"thinking": [], "tasks": [], "parallel": False, "status": {}, "lines": []}
                answer_id, answer_text, enriched_sources = None, [], None
            _trace_collect(trace, ev)
            if ev.get("type") == "token":
                answer_text.append(ev.get("text") or "")
            if ev.get("type") == "done":
                if ev.get("message_id"):
                    answer_id = ev["message_id"]
                # 사내 문서 각주(2026-08-24): done.sources에 cites/supports를 덧붙여 라이브·복원이 같은 각주를 본다
                # Internal-document footnotes: enrich done.sources with cites/supports so live and restore agree
                # OpenUI 답(2026-10-27)은 건너뛴다: 본문 위치 각주가 프로그램 글과 맞지 않고, 인용은 프로그램 안의 [n] 출처 칩이 맡는다.
                # OpenUI answers (2026-10-27) skip it: body-offset footnotes do not fit a program, whose [n] source chips cite.
                try:
                    if ev.get("format") != "openui":
                        enriched_sources = cite.enrich_sources(ev.get("sources"), ev.get("references"), "".join(answer_text))
                        if enriched_sources is not None:
                            ev = dict(ev)
                            ev["sources"] = enriched_sources
                except Exception:  # noqa: BLE001 — 귀속 실패는 답변에 영향 없음 / attribution failure never blocks the answer
                    logger.warning("각주 귀속 실패", exc_info=True)
            yield ev
    except Exception as e:
        logger.exception("파이프라인 오류")
        # 쿼터 소진(429·쿨다운)은 오류가 아니라 안내로 — 사용자에겐 '무언의 실패' 대신
        # 잠시 후 재시도를 답변 형태로 알린다(메시지로 저장돼 새로고침에도 남음).
        # Quota exhaustion (429/cooldown) is guidance, not an error — instead of a silent failure the
        # user gets a retry note as an answer (saved as a message, so it survives refresh).
        es = str(e)
        # 503 UNAVAILABLE(모델 혼잡, 2026-09-14)도 같은 안내 — 원문 JSON 오류 대신 재시도 안내를 답변으로 남긴다
        # 503 UNAVAILABLE (model overloaded, 2026-09-14) gets the same note — a retry hint instead of the raw JSON error
        if ("429" in es or "RESOURCE_EXHAUSTED" in es or "쿨다운" in es or "quota" in es.lower()
                or "503" in es or "UNAVAILABLE" in es or "네트워크 오류" in es):
            note = ("지금 AI 호출량이 몰려 잠시 응답이 어렵습니다. 1~2분 뒤 같은 요청을 "
                    "다시 보내주시면 이어서 처리하겠습니다.")
            try:
                mid = db.add_message(chat_id, "assistant", note, meta={"source": "사내"})
            except Exception:  # noqa: BLE001 — 저장 실패해도 안내는 표시 / show the note even if saving fails
                mid = None
            yield {"type": "answer_head", "source": "사내"}
            yield {"type": "token", "text": note}
            done_ev: dict = {"type": "done"}
            if mid:
                done_ev["message_id"] = mid
            yield done_ev
        else:
            yield {"type": "error", "detail": es}
    finally:
        MESSAGE_LANE.reset(lane_token)
        # 이번 실행이 저장한 답변(done.message_id)에만 트레이스(+탐색 표시)를 덧붙인다 — 반문/확인/중단/오류로
        # 답변이 없으면 건너뛴다. "마지막 메시지" 추정은 스트림 중 끼어든 안내 카드를 오염시켰다(리뷰 확정).
        # Attach the trace (+explore tag) only to the answer this run saved (done.message_id) — skipped on
        # clarify/confirm/abort/error. Guessing "the last message" corrupted a note card inserted mid-stream.
        if answer_id:
            try:
                patch: dict = {"trace": trace}
                if body.explore:
                    patch["kind"] = "explore"
                    patch["agent"] = explore_agent
                    patch["anchor"] = explore_anchor
                if enriched_sources is not None:
                    patch["sources"] = enriched_sources
                db.update_message_meta(answer_id, patch)
            except Exception:  # noqa: BLE001 — 트레이스 저장 실패는 답변에 영향 없음 / never affects the answer
                logger.warning("실행 트레이스 저장 실패", exc_info=True)


async def _on_run_finish(run: runs.Run) -> None:
    """실행 종료 → chats.run_state 기록(done|needs_input|error|stopped), unseen=1(사이드바 완료 아이콘).
    사용자가 보고 있던 채팅은 어댑터가 done 수신 즉시 POST /seen 으로 되돌린다.
    예외(리뷰 반영): 탐색 실행은 채팅 상태를 건드리지 않고, STOP 뒤 새 실행에 밀린 옛 실행은 기록하지 않으며
    (새 실행의 'running' 을 덮어쓰지 않도록), 사용자가 직접 멈춘 실행은 완료 아이콘 없이(unseen=0) 마감한다."""
    # Run finished → record chats.run_state (done|needs_input|error|stopped) with unseen=1 (sidebar done icon).
    # For the chat the user is watching, the adapter posts /seen right after receiving done.
    # Exceptions (review fixes): explore runs never touch the chat state; a run superseded by a newer one after
    # STOP records nothing (so it cannot overwrite the new run's 'running'); a user-stopped run ends without the
    # done badge (unseen=0).
    if run.explore or not runs.is_current(run):
        return
    db.set_run_state(run.chat_id, run.state, unseen=0 if run.stopped_by_user else 1)
    from app import schedules
    outcome = next((e for e in reversed(run.events) if e.get("type") == "execution_result"), {})
    if outcome.get("run_id"):
        await schedules.complete_resumed(run.chat_id,
            run.state if run.state in ("error", "stopped", "needs_input") else outcome.get("state", run.state),
            outcome.get("artifact", False), outcome["run_id"])


def _subscribe_response(run: runs.Run) -> EventSourceResponse:
    """실행 구독 SSE — 버퍼 재생 + 라이브 전달. 클라이언트 끊김은 구독 해제일 뿐 실행을 취소하지 않는다.
    이벤트 JSON 직렬화·ping 은 종전과 동일."""
    # Subscriber SSE — replay the buffer, then live events. A client disconnect only unsubscribes; it never
    # cancels the run. Event JSON serialisation and ping are unchanged.
    sub = runs.subscribe(run.chat_id)
    if sub is None:  # 방금 start 했으니 없을 수 없다 / cannot happen right after start
        raise HTTPException(status_code=404, detail="진행 중인 답변이 없습니다")
    replay, queue = sub

    async def gen():
        try:
            for ev in replay:
                yield {"data": json.dumps(ev, ensure_ascii=False)}
            async for ev in runs.drain(queue):
                yield {"data": json.dumps(ev, ensure_ascii=False)}
        finally:
            runs.unsubscribe(run.chat_id, queue)

    return EventSourceResponse(gen(), ping=15)


@router.get("/{chat_id}/stream/attach")
async def attach_stream(chat_id: str) -> EventSourceResponse:
    """진행 중인 답변에 재접속(2026-09-04) — 버퍼 재생 + 라이브. 실행이 없으면 404."""
    # Re-attach to an answer in progress (2026-09-04) — replay + live. 404 when nothing is running.
    if db.get_chat(chat_id) is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 채팅입니다")
    run = runs.get(chat_id)
    if run is None or run.done or run.stopping:   # STOP 마감 중인 실행에는 붙지 않는다 / never attach to a stopping run
        raise HTTPException(status_code=404, detail="진행 중인 답변이 없습니다")
    return _subscribe_response(run)


@router.post("/{chat_id}/stop")
async def stop_stream(chat_id: str, explore: bool = False) -> dict:
    """명시적 중단(STOP 버튼) — 실행 중이면 프로듀서 취소 → {ok:true, settled}, 아니면 {ok:false}.
    취소 즉시 '진행 중' 에서 빠지므로(runs.stop) 바로 재질문해도 409 가 아니고, 태스크 마감은 최대 3초만 기다린다
    (settled=false 면 백그라운드에서 마저 정리). 상태 기록(stopped, unseen=0)은 _on_run_finish 가 한다.
    explore=1 이면 탐색 미니채팅 실행을 중단한다."""
    # Explicit stop (STOP button) — cancel the producer when running → {ok:true, settled}, else {ok:false}.
    # The run leaves 'running' at once (runs.stop), so an immediate re-ask is not a 409; the task settle is awaited
    # for at most 3 s (settled=false → it finishes in the background). _on_run_finish records stopped/unseen=0.
    # explore=1 stops the explore mini-chat run instead.
    run = runs.stop(_run_key(chat_id, explore))
    if run is None:
        return {"ok": False}
    settled = await runs.settle(run, 3.0)
    return {"ok": True, "settled": settled}


@router.post("/{chat_id}/seen")
async def mark_seen(chat_id: str) -> dict:
    """읽음 처리 — 채팅을 열면 완료 아이콘이 사라진다(unseen=0, run_state 는 유지)."""
    # Mark as read — opening the chat clears the done icon (unseen=0; run_state kept).
    if not db.set_run_state(chat_id, None, unseen=0):
        raise HTTPException(status_code=404, detail="존재하지 않는 채팅입니다")
    return {"ok": True}


@router.get("/{chat_id}")
def get_chat(chat_id: str) -> dict:
    """채팅 1건(2026-09-07) — 목록(GET "")에서 빠진 예약 결과 채팅을 히스토리·메일 딥링크에서 열 때 프런트가 등록용으로 조회한다."""
    # One chat (2026-09-07) — lets the front end register a schedule result chat (absent from the list) when opened
    # from the history or the mail deep link.
    c = db.get_chat(chat_id)
    if c is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 채팅입니다")
    return c


@router.get("/{chat_id}/messages")
def get_messages(chat_id: str) -> list[dict]:
    if db.get_chat(chat_id) is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 채팅입니다")
    return db.list_messages(chat_id)


@router.patch("/{chat_id}")
def patch_chat(chat_id: str, body: ChatPatch) -> dict:
    """title = 이름 바꾸기 / coll = 컬렉션 묶기(빈 문자열 = 해제, 없는 컬렉션 404; 2026-09-08 컴포저 컬렉션 첨부) /
    flow_id = 워크플로우 모드(2026-09-11; 빈 문자열 = 끄기 + 미완 워크플로우 run 취소, 없는 워크플로우 404)"""
    # title = rename / coll = collection binding (empty string = unbind, unknown collection → 404; composer attach 2026-09-08) /
    # flow_id = workflow mode (2026-09-11; empty = off + cancel unfinished workflow runs, unknown flow → 404)
    if body.title is None and body.coll is None and body.flow_id is None:
        raise HTTPException(status_code=422, detail="바꿀 항목이 없습니다")
    if body.flow_id is not None:
        fid, fname = _clean_flow(body.flow_id, body.flow_name)
        if not db.set_chat_flow(chat_id, fid, fname):
            raise HTTPException(status_code=404, detail="존재하지 않는 채팅입니다")
        if not fid:
            # 모드 종료 — 카드 대기 중인 워크플로우 run 을 취소하고 카드를 응답 완료 처리(일반 메시지가 낡은 run 을 재개하지 않게)
            # Mode exit — cancel card-waiting workflow runs and mark their cards answered (no stale resume from a normal message)
            from app import execution_store
            from app.conversation_execution import resolve_cards
            for rid in execution_store.cancel_workflow_runs(chat_id):
                run = execution_store.get(rid)
                if run:
                    resolve_cards(run)
    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise HTTPException(status_code=422, detail="title이 비어 있습니다")
        if not db.update_chat_title(chat_id, title):
            raise HTTPException(status_code=404, detail="존재하지 않는 채팅입니다")
    if body.coll is not None:
        cid = body.coll.strip() or None
        if cid and not collections_store.exists_collection(cid):
            raise HTTPException(status_code=404, detail="존재하지 않는 컬렉션입니다")
        if not db.set_chat_coll(chat_id, cid, _clean_files(body.coll_files) if cid else None):
            raise HTTPException(status_code=404, detail="존재하지 않는 채팅입니다")
    chat = db.get_chat(chat_id)
    return {"ok": True, "coll": chat.get("coll") if chat else None, "coll_files": chat.get("coll_files") if chat else [],
            "flow_id": chat.get("flow_id") if chat else "", "flow_name": chat.get("flow_name") if chat else ""}


@router.delete("/{chat_id}")
async def remove_chat(chat_id: str) -> dict:
    # 진행 중인 답변(본문·탐색)이 있으면 먼저 중단하고 잠시 마감을 기다린다(2026-09-04) — 삭제 뒤 옛 태스크가 행을
    # 더 쓰는 것을 줄인다. async 핸들러라 태스크 취소가 이벤트 루프 스레드에서 일어난다.
    # Stop an in-progress answer (main + explore) first and briefly wait for it to settle (2026-09-04) — fewer
    # rows written by the old task after the delete. Async handler so the cancel runs on the loop thread.
    for key in (chat_id, _run_key(chat_id, True)):
        run = runs.stop(key)
        if run is not None:
            await runs.settle(run, 3.0)
    if not db.delete_chat(chat_id):
        raise HTTPException(status_code=404, detail="존재하지 않는 채팅입니다")
    return {"ok": True}
