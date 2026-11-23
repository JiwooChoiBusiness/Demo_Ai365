"""파이프라인 코어: 의도판단 → 에이전트 실행 → 답변 취합 (SSE 이벤트 제너레이터).

이벤트 계약(docs/plan.md STEP 4):
  thinking_start / task_tree / agent_status / clarify / confirm /
  answer_head / token / done / error
추가(가산) 이벤트/필드:
  {type:'thinking', text} — 진행 단계 표시(스피너 라벨 갱신)
  agent_status.detail — 에이전트 결과 한 줄 요약(작업 트리 하위 행)
  done.references — 참조 문서 목록(STEP 5)
"""
# Pipeline core: intent judgment -> agent execution -> answer aggregation (SSE event generator).
#
# Event contract (docs/plan.md STEP 4):
#   thinking_start / task_tree / agent_status / clarify / confirm /
#   answer_head / token / done / error
# Additional (additive) events/fields:
#   {type:'thinking', text} — progress step display (updates spinner label)
#   agent_status.detail — one-line summary of agent result (task tree child row)
#   done.references — list of referenced documents (STEP 5)

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator

from app import access, catalog, db, flow_api_call, llm, schedules_nl
from app.agents import AGENT_REGISTRY, AgentResult
from app.run_context import with_material
from app.task_runner import legacy_steps, run_tasks

logger = logging.getLogger("ai365.pipeline")

CONTEXT_WINDOW = 10  # 채팅별 컨텍스트로 쓰는 최근 메시지 수
# Number of recent messages used as per-chat context

# ── 3분할 재수출(2026-08-28) — 의도해석(app.intent)·답변 생성(app.answers)으로 분할하며,
#    run_pipeline 본문과 외부 참조(pipeline.<이름>)를 위해 이름을 그대로 재수출한다.
# ── Split re-exports (2026-08-28) — the pipeline is split into intent (app.intent) and answer
#    (app.answers) layers; names are re-exported verbatim for run_pipeline and external references.
from app.intent import (  # noqa: F401,E402
    ANSWER_SYSTEM, ANSWER_SYSTEM_BLEND, DIRECT_SYSTEM, EXTERNAL_SYSTEM, GAP_SYSTEM,
    REWRITE_SYSTEM, WEB_SUPPLEMENT_SYSTEM, _INTERRUPT_NOTE, _REPORT_NOTE, _anaphora_ctx_source,
    _anaphora_send, _await_send_state, _docgen_match, _draft_params, _draft_preview,
    _intent_system, _judge_gap, _judge_intent, _lang_note, _normalize_options, _recipientish,
    _send_intentish, _transform_send, _validate_plan,
)
from app.answers import (  # noqa: F401,E402
    _aggregate_answer, _astream, _auto_answer, _build_sources, _collect_cards,
    _collect_references, _deliver_answer, _extract_sends, _plan_answer, _run_agents,
    _run_external, _slim_extras, _smooth, _status_detail, _stream_answer,
)


def _build_context(chat_id: str, message: str, lane: str = "chat") -> list[dict]:
    """유저 메시지 저장(중복 방지) 후 최근 메시지 컨텍스트 구성."""
    # Store the user message (avoiding duplicates), then build the recent-message context.
    from app.run_context import history as lane_history
    history = lane_history(chat_id, lane)
    # POST /api/chats가 첫 메시지를 이미 저장했으므로 동일 내용이 마지막이면 재저장하지 않는다
    # Since POST /api/chats already stored the first message, do not re-store if the same content is the last one
    if not (history and history[-1]["role"] == "user" and history[-1]["content"] == message):
        db.add_message(chat_id, "user", message)
        history = lane_history(chat_id, lane)
    return [{"role": m["role"], "content": m["content"]} for m in history[-CONTEXT_WINDOW:]]


def _resolve_eff(acting_user_id: str) -> dict | None:
    """신원 → 실효 권한. 빈 값/비정상=슈퍼관리자(나, 게이팅 우회=None).

    멤버 번호가 오면 access.effective 로 권한을 계산해 챗봇 게이팅에 사용한다.
    조회가 실패하면 안전하게 '전부 차단' 권한으로 떨어뜨린다(권한 상승 방지).
    """
    # Identity → effective permissions. Empty/invalid = super admin (나, gating bypassed = None).
    # If a member number is given, compute permissions via access.effective for chatbot gating.
    # On lookup failure, fall back safely to 'all blocked' permissions (prevents privilege escalation).
    aid = (acting_user_id or "").strip()
    if not aid:
        return None  # 슈퍼관리자(나) — 게이팅 없음
    if not aid.isdigit():
        logger.warning("acting_user_id 형식 오류(%r) — 슈퍼관리자로 처리", acting_user_id)
        return None
    try:
        return access.effective(int(aid))
    except Exception:
        logger.warning("effective 조회 실패(no=%s) — 전부 차단으로 처리", aid, exc_info=True)
        return {"no": None, "menus": {}, "nodes": {}, "mgmt": {},
                "read": {"p_know": False, "p_data": False, "p_auto": False}}


def _clean_scope_files(scope_files: dict | None) -> dict:
    """클라이언트가 보낸 scope_files를 방어적으로 정규화 — 문자열 리스트/불리언만 통과.

    악의·오류 입력(비-리스트, 비-문자열, unhashable 등)으로 에이전트 집합연산이 깨지거나
    오작동하는 것을 막는다. 권한 게이팅은 별도로 항상 적용되므로 정규화는 견고성 목적.
    """
    # Defensively normalize client-sent scope_files — pass only lists of strings / a boolean.
    # Prevents agent set operations from breaking on malformed input. Permission gating always applies
    # separately, so this normalization is for robustness, not security.
    sf = scope_files if isinstance(scope_files, dict) else {}

    def _strs(v) -> list[str]:
        return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []

    clean = {
        "knowledge_files": _strs(sf.get("knowledge_files")),
        "data_tables": _strs(sf.get("data_tables")),
        "data_bi": _strs(sf.get("data_bi")),
        "work": bool(sf.get("work")),
    }
    # 누락은 종전 work 범위, 명시한 빈/비정상 값은 아무 하위 에이전트도 선택하지 않은 상태다.
    # Absence keeps legacy work scope. Explicit empty/malformed values must never widen it.
    if "workers" in sf:
        clean["workers"] = list(dict.fromkeys(x for x in _strs(sf["workers"]) if x in ("email", "edu")))
    # 로컬 지식 에이전트만 묻기(2026-10-28, 리소스 선택 대화 상자 Local 구획): 고른 에이전트 id. 값이 있을 때만 싣는다(종전 모양 그대로).
    # 권한은 지식 에이전트가 knowledge_agents.readable(eff) 와의 교집합으로 다시 거른다.
    # Ask only the chosen local knowledge agents (2026-10-28, the Local section of the resource picker): the chosen agent ids,
    # added only when present so the shape stays as before. The knowledge agent intersects them with knowledge_agents.readable(eff).
    local = list(dict.fromkeys(x.strip() for x in _strs(sf.get("local_agents")) if x.strip()))[:20]
    if local:
        clean["local_agents"] = local
    return clean


def _check_worker_selection(decision: dict, scope_files: dict | None) -> None:
    """구형 계획에도 명시한 업무 에이전트 범위를 적용한다. 권한 검사는 실행기에서 별도로 수행한다."""
    from app.execution import PlanError
    sf = _clean_scope_files(scope_files)
    if "workers" in sf and any(step.get("agent") == "work" and step.get("worker") not in sf["workers"]
                               for step in decision.get("steps", [])):
        raise PlanError("선택한 업무 에이전트 범위와 실행 계획이 다릅니다. 사용할 에이전트를 확인해 주세요.")


async def _run_connectors(chosen: list[dict], message: str, acting_user_id: str,
                          results: dict[str, AgentResult], inputs: dict[str, dict] | None = None) -> AsyncIterator[dict]:
    """이전 호출 경로 호환. 실제 호출은 공통 Tool 실행기를 사용한다."""
    async for event in run_tasks(legacy_steps([], True, message, chosen, inputs), [], results,
                                  connectors=chosen, acting_user_id=acting_user_id, emit_tree=False):
        yield event


def _has_prior_answer(context: list[dict]) -> bool:
    """현재 메시지 이전에 어시스턴트 답변이 있는가 — 지시어("해당 내용") 발송이 가리킬 대상이 있는지."""
    # Is there an assistant answer before the current message — i.e. something an anaphora send can refer to.
    return any(m.get("role") == "assistant" and str(m.get("content") or "").strip()
               for m in (context or [])[:-1])


async def run_pipeline(chat: dict, message: str, scope: str,
                       agents: list[str] | None = None,
                       instructions: str = "",
                       acting_user_id: str = "",
                       scope_files: dict | None = None,
                       allow_schedule: bool = False,
                       force_schedule: bool = False,
                       connectors: list[dict] | None = None,
                       resume_id: str = "", execution_lane: str = "chat",
                       ui_format: str = "auto") -> AsyncIterator[dict]:
    # ui_format(2026-10-27, OpenUI): "auto"/"openui" = 서버 전역 OPENUI_MODE 를 따름, "markdown" = 이 요청은 OpenUI 끔.
    # 실행 스냅숏에 담겨 drive · 재개로 흐르고, 외부 모드의 _run_external 에는 여기서 바로 넘긴다.
    # ui_format (2026-10-27, OpenUI): "auto"/"openui" follow the server-wide OPENUI_MODE, "markdown" turns OpenUI off for this
    # request. It is kept in the run snapshot (drive and resumes) and handed straight to _run_external in external mode.
    chat_id = chat["id"]
    # 커넥터(2026-09-09): 채팅에 연결된 커넥터(권한·활성 필터 완료, chats_api) 중 의도 판단이 고른 것 / connectors the intent picked
    # 신원(뷰애즈) → 실효 권한. 슈퍼관리자(나)면 None(게이팅 우회).
    # Identity (view-as) → effective permissions. None for super admin (나) (gating bypassed).
    eff = await asyncio.to_thread(_resolve_eff, acting_user_id)
    scope_files = _clean_scope_files(scope_files)   # 방어적 정규화(문자열 리스트/불리언만)
    # Defensive normalization (only lists of strings / a boolean)
    yield {"type": "thinking_start"}
    context = with_material(await asyncio.to_thread(_build_context, chat_id, message, execution_lane), instructions)
    lang_note = _lang_note(message)  # 영어 등 비한국어 질문이면 모든 답변 경로에서 그 언어로 강제
    # If the question is non-Korean (e.g., English), force that language across all answer paths
    # 컬렉션(프로젝트) 채팅의 지침 — 모든 답변 경로의 시스템 프롬프트에 함께 흐르도록 lang_note에 덧붙인다.
    # Collection (project) chat instructions — append to lang_note so they flow into the system prompt of every answer path.
    if (instructions or "").strip():
        lang_note += ("\n\n[컬렉션 지침] 이 대화는 아래 지침을 우선 따른다(사용자 질문과 충돌하지 않는 범위에서):\n"
                      + instructions.strip())

    # ---- 자연어 예약 가로채기(2026-09-07) — 사용자 턴(chats_api)에서만(allow_schedule). 예약 실행 자체(schedules.fire)는
    #      끄고 들어오므로 예약 프롬프트가 다시 예약을 만들지 않는다. force_schedule(예약 작업 페이지 입력)이면 어휘 선별 없이
    #      무조건 예약으로 만든다. 문서 생성 가로채기보다 앞 — "매주 매출 보고서 PPT 만들어줘"는 예약이 되고, 실행 때 docgen 이 돈다. ----
    # ---- Natural-language schedule interception (2026-09-07) — only on user turns (allow_schedule; scheduled runs
    #      come in with it off so a schedule prompt never re-creates a schedule). force_schedule (schedules page input)
    #      skips the vocabulary gate. Placed before docgen so a weekly "make the sales PPT" becomes a schedule whose runs docgen. ----
    if not resume_id and allow_schedule and (force_schedule or schedules_nl.looks_like(message)):
        spec = await asyncio.to_thread(schedules_nl.parse, message, force_schedule)
        if spec:
            # 로컬 지식 에이전트를 골랐으면(scope_files.local_agents) 예약을 만들지 않고 안내만 한다(2026-10-28, schedules_nl)
            # With local knowledge agents chosen (scope_files.local_agents) no schedule is made, only a note (2026-10-28, schedules_nl)
            async for ev in schedules_nl.confirm_events(chat, spec, scope, agents, scope_files, acting_user_id,
                                                        message=message):
                yield ev
            return

    from app import conversation_execution as execution, execution_store
    from app.decisions import from_legacy, validate
    from app.execution import PlanError
    explicit = [a for a in (agents or []) if a in AGENT_REGISTRY]
    try:
        pending = execution_store.get(resume_id) if resume_id else execution_store.pending(chat_id, execution_lane)
        if resume_id and not pending:
            raise PlanError("질문 카드에 해당하는 실행을 찾지 못했습니다. 새 요청으로 진행해 주세요.")
        # v2에서 이미 저장한 수신자 질문만 호환한다. 새 질문은 체크포인트를 사용한다.
        legacy = await asyncio.to_thread(_await_send_state, chat_id) if not pending and not resume_id and execution_lane == "chat" and scope != "외부" else None
        if legacy and isinstance(legacy.get("content_results"), dict) and _recipientish(message):
            if legacy.get("content_eff") != eff:
                raise PlanError("권한이 변경됐습니다")
            async for ev in _deliver_answer(chat_id, "사내", context, legacy["content_results"],
                    (legacy.get("send_query") or "메일로 보내줘") + " → " + message, lang_note, eff=eff,
                    user_msg=message, content_plan=legacy.get("content_plan")):
                yield ev
            return
        if pending:
            if pending["chat_id"] != chat_id or pending["snapshot"]["actor"] != acting_user_id:
                raise PlanError("현재 사용자와 채팅의 실행만 재개할 수 있습니다")
            if pending["snapshot"].get("lane", "chat") != execution_lane:
                raise PlanError("질문 카드의 대화 영역이 일치하지 않습니다")
            if pending["snapshot"].get("kind") in ("workflow", "document"):
                from app import artifact_execution
                snap = pending["snapshot"]
                if snap["eff"] != eff:
                    raise PlanError("권한이 변경됐습니다")
                is_reply = pending["state"] == "needs_input" and snap.get("waiting") and bool(resume_id)
                if is_reply or (pending["state"] == "interrupted" and (resume_id or message.strip() in ("계속", "재개", "계속해줘", "이어서 해줘"))):
                    if is_reply:
                        await asyncio.to_thread(artifact_execution.fill_workflow, pending, message)
                    stream = (artifact_execution.workflow_run(snap["flow"], chat, snap["message"], acting_user_id, pending)
                              if snap["kind"] == "workflow" else artifact_execution.document_run(chat, snap["cfg"], pending))
                    async for ev in stream:
                        yield ev
                    return
                if resume_id:
                    raise PlanError("현재 실행은 재개할 수 없습니다")
                execution_store.save(pending, "cancelled")
                pending = None
            if pending and pending["snapshot"]["eff"] != eff:
                raise PlanError("권한이 변경됐습니다. 새 요청으로 진행해 주세요.")
            # 재개는 카드 생성 시점의 선택 범위를 쓴다. 전송 후 비워진 composer 선택값으로 바꾸지 않는다.
            # If an implicit reply is a new request, fill_reply returns False and the current selection is used below.
            if pending:
                _check_worker_selection(pending["snapshot"]["decision"], pending["snapshot"].get("scope_files"))
            if pending and pending["state"] == "needs_input" and pending["snapshot"]["decision"].get("clarify"):
                resumed = await asyncio.to_thread(execution.fill_reply, pending, message,
                                                  explicit=bool(resume_id), connectors=connectors)
            else:
                resumed = bool(pending) and pending["state"] == "interrupted" and (bool(resume_id) or message.strip() in ("계속", "재개", "계속해줘", "이어서 해줘"))
            if resumed:
                async for ev in execution.drive(pending, chat, connectors or [], eff):
                    yield ev
                return
            if resume_id:
                raise PlanError("현재 실행은 이 질문 카드로 재개할 수 없습니다")
            if pending:
                execution_store.save(pending, "cancelled")

        # 실시간 위젯(2026-10-06) — 날씨 · 환율 · 장소 단순 조회는 의도 판단(LLM 3회) 전에 위젯 카드로 답한다. 사내 · 외부 모드
        # 모두 먼저 보며('외부 = 바로 웹'의 예외), 탐색 미니채팅과 질문 카드 재개는 제외한다. 다른 작업이 섞이면 detect 가 None.
        # Live widgets (2026-10-06) — plain weather, exchange-rate and place lookups are answered with a widget card before
        # intent planning (three LLM calls), in internal and external modes alike (an exception to "external = straight to
        # the web"); explore mini-chats and question-card resumes are excluded. Mixed requests make detect return None.
        # 컴포저에서 지식 · 데이터 · 업무를 직접 고르거나 파일 · 표를 골랐으면 사내 자료를 먼저 본다(그룹웨어만 고른 홈 질문은 위젯 허용).
        # An explicit knowledge/data/work pick or a file/table selection means internal sources first (a groupware-only home question still gets widgets).
        picked = bool(set(explicit) & {"knowledge", "data", "work"}) or any(
            scope_files.get(k) for k in ("knowledge_files", "data_tables", "data_bi"))
        if not resume_id and execution_lane == "chat" and not picked:
            from app import live_widgets
            hit = await asyncio.to_thread(live_widgets.detect, chat_id, message)
            if hit:
                async for ev in live_widgets.answer(chat, hit, message):
                    yield ev
                return

        # 외부 검색은 의도판단/사내 조회를 스킵하되 기존 파일 설정 요청을 보존한다.
        if scope == "외부":
            doc = _docgen_match(message)
            if doc:
                decision = {"version": 3, "query": message, "steps": [], "send_query": "", "clarify": None,
                            "document": {"format": doc["fmt"], "topic": doc["topic"]}, "use_previous": False, "web": False}
                run = execution.create(chat, decision, message, context, scope, eff, scope_files, acting_user_id, lang_note,
                                       ui_format=ui_format)
                run["snapshot"]["lane"] = execution_lane
                execution_store.save(run)
                async for ev in execution.drive(run, chat, [], eff):
                    yield ev
            else:
                from app import openui
                async for ev in _run_external(chat_id, context, lang_note,
                                              **openui.fmt_kw(openui.resolve(ui_format, execution_lane))):
                    yield ev
            return
        yield {"type": "thinking", "text": "질문 의도를 분석하고 있습니다"}
        raw = await asyncio.to_thread(_judge_intent, context, connectors or None, explicit or None,
                                      eff=eff, scope_files=scope_files)
        decision = validate(from_legacy(raw, message), connector_ids={c["id"] for c in connectors or []},
                            allowed_agents=set(explicit) if explicit else None)
        if decision["web"] and not decision["steps"] and not decision.get("clarify") and not decision.get("request_spec"):
            agent = explicit[0] if explicit else "knowledge"
            decision["steps"] = [{"id": "internal", "agent": agent, "task": decision["query"], "depends_on": [], "inputs": {}}]
            if agent == "work":
                workers = scope_files.get("workers", ["email"])
                if len(workers) != 1:
                    raise PlanError("조회할 업무 에이전트를 하나 지정해 주세요.")
                decision["steps"][0]["worker"] = workers[0]
        _check_worker_selection(decision, scope_files)
        run = execution.create(chat, decision, message, context, scope, eff, scope_files, acting_user_id, lang_note,
                               ui_format=ui_format)
        run["snapshot"]["allowed_agents"] = explicit
        run["snapshot"]["lane"] = execution_lane
        execution_store.save(run)
        async for ev in execution.drive(run, chat, connectors or [], eff):
            yield ev
    except Exception:
        logger.exception("계획 또는 재개 실패")
        yield {"type": "error", "detail": "실행 계획 또는 추가 입력을 확인하지 못했습니다. 내용을 확인해 다시 요청해 주세요."}
