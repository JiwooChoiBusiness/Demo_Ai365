"""지식관리 Agent — PDF 인덱스 하이브리드 검색 기반 답변.

근거 충분 → answer / 근거 약함 → inference / 도출 불가 → (이때만) 웹 폴백.

로컬 지식 에이전트(2026-09-30): 권한 관문(p_know)을 지난 모든 결과의 extras 에 이 사용자가 쓸 수 있는 로컬 지식 에이전트 id
(local_agents)와 그 에이전트에 물을 질문(local_query)만 싣는다. 로컬 에이전트를 부르는 것은 채팅 답변 단계(app/answers.py)뿐이다
(이 에이전트는 워크플로우 · 파일 생성 조사도 쓰므로 여기서 부르면 안 된다). references 는 계속 Public 문서만 담는다.
로컬 전용(2026-10-28): scope_files.local_agents 로 로컬 에이전트만 고르면 Public 검색 없이 그 에이전트들만 재료로 싣는다(_local_only).
고른 에이전트를 쓸 수 없거나 질문이 비면 넓히지 않고 근거 없음으로 닫는다.
"""
# Knowledge management Agent — answers based on hybrid search over the PDF index.
# Sufficient evidence → answer / weak evidence → inference / cannot derive → (only then) web fallback.
# Local knowledge agents (2026-09-30): every result after the permission gate (p_know) carries in extras the ids of the local
# knowledge agents this user may use (local_agents) and the question to ask them (local_query). Only the chat answer stage
# (app/answers.py) calls those agents: workflows and document research also run this agent, so it must never call them here.
# references still hold Public documents only.
# Local only (2026-10-28): when scope_files.local_agents picks local agents alone, only those ride as material and the Public
# search is skipped (_local_only). When the chosen agents cannot be used or the question is empty, it closes as no evidence
# without widening.

import asyncio
import logging

from app import catalog, kb, knowledge_agents, llm, settings
from app.agents import AgentResult, Message

logger = logging.getLogger("ai365.agents.knowledge")

ANSWER_SYSTEM = """너는 사내 지식관리 에이전트다. 아래 [근거 문서 발췌]만을 근거로 사용자의 질문에 한국어로 답하라.
- 발췌에 있는 내용만 사용하고, 없는 내용은 지어내지 않는다.
- 수치·기간·조건 등은 발췌 그대로 정확히 옮긴다.
- 마크다운 기호 없이 단락 위주의 평문으로 쓴다."""

INFERENCE_NOTE = "\n단, 근거가 충분하지 않으므로 발췌 내용에서 추정 가능한 범위만 조심스럽게 답하고, 정확한 확인이 필요하다는 점을 덧붙여라."

# ── 2단 검색 1단계(2026-08-31, 실물 파이프라인 정합): 질의 분해 + 개요 기반 문서 소스 선택 ──
# 다이어그램의 "Split into multiple sentences → Overview Retrieval → Selecting file sources"를
# 데모 규모로 접합: 경량 호출 1회가 (a) 복합 질문을 하위 검색 질의 1~3개로 분해하고 (b) 문서
# 목록(개요)에서 관련 문서를 관대하게 고른다. 선택은 리콜 보전 폴백과 함께만 적용된다(_run_sync).
# Two-stage search, stage 1 (production-pipeline alignment): one lite call (a) decomposes a compound
# question into 1~3 sub-queries and (b) picks likely source documents from the doc-list overview.
# The selection is applied only together with a recall-preserving fallback (see _run_sync).
OVERVIEW_SYSTEM = """너는 사내 문서 검색 플래너다. 질문을 검색에 유리하게 준비한다. JSON으로만 출력한다.
출력 형식: {"subqueries": ["하위 질의", ...], "files": ["문서명", ...]}
- subqueries: 질문이 여러 주제를 담고 있으면 1~3개의 독립 검색 질의로 분해한다. 단순 질문이면 원문을 다듬은 1개만.
- files: [문서 목록]에서 답이 있을 법한 문서를 고른다(목록의 이름 그대로, 최대 8개). 확신이 없으면 넉넉히 고르고, 판단이 어려우면 빈 배열로 둔다(빈 배열=전체 검색)."""


def _overview(query: str, context: list[Message], universe: list[str]) -> dict:
    """1단계: 질의 분해 + 개요(문서 목록) 소스 선택 — 실패는 무해한 기본값(원문 1개·전체)으로."""
    # Stage 1: query decomposition + overview source selection — failures degrade harmlessly.
    try:
        listing = "\n".join(f"- {f}" for f in universe) or "(없음)"
        recent = context[:-1][-2:]
        out = llm.generate(
            recent + [{"role": "user", "content": f"[문서 목록]\n{listing}\n\n[질문]\n{query}"}],
            system=OVERVIEW_SYSTEM, json_mode=True, tier="lite")
        uni = set(universe)
        subs = [str(s).strip() for s in (out.get("subqueries") or []) if str(s).strip()][:3]
        files = [str(f).strip() for f in (out.get("files") or []) if str(f).strip() in uni][:8]
        if subs:
            logger.info("개요 플래너: 하위질의 %d개, 문서 %d개 선택", len(subs), len(files))
        return {"subqueries": subs or [query], "files": files}
    except Exception as e:  # noqa: BLE001 — 플래너 실패가 검색을 죽이면 안 된다 / must not kill the search
        logger.warning("개요 플래너 실패 — 원문 단일 질의로 진행: %s", e)
        return {"subqueries": [query], "files": []}


def _build_prompt(query: str, hits: list[dict], context: list[Message]) -> list[Message]:
    excerpts = "\n\n".join(
        f"[근거 {i + 1}] (문서: {h['doc']}, p.{h['page']})\n{h['text']}" for i, h in enumerate(hits)
    )
    recent = [m for m in context[:-1]][-4:]  # 마지막(현재 질문)은 아래에 직접 포함
    # The last item (the current question) is included directly below.
    return recent + [
        {"role": "user", "content": f"[근거 문서 발췌]\n{excerpts}\n\n[질문]\n{query}"}
    ]


def _references(hits: list[dict]) -> list[dict]:
    seen, refs = set(), []
    for h in hits:
        key = (h["doc"], h["page"])
        if key in seen:
            continue
        seen.add(key)
        refs.append({"doc": h["doc"], "page": h["page"]})
    return refs


# 근거 발췌(2026-10-27, OpenUI 번호 출처): 답에 실제로 쓴 청크의 앞 600자. OpenUI 작성 호출이 [n] 을 정확히 붙이도록 번호 출처마다
# 준다. 취합 프롬프트(answers._slim_extras)와 메시지 meta 에는 싣지 않는다(references 는 그대로).
# Evidence excerpts (2026-10-27, OpenUI numbered sources): the first 600 characters of each chunk the answer actually used, given
# per numbered source so the OpenUI compose call places [n] accurately. Never in the aggregation prompt (answers._slim_extras)
# or in message meta; references stay as they are.
EXCERPT_CHARS = 600


def _excerpts(hits: list[dict]) -> list[dict]:
    seen, out = set(), []
    for h in hits:
        text = str(h.get("text") or "").strip()[:EXCERPT_CHARS]
        key = (h.get("doc"), h.get("page"), text[:60])
        if not text or key in seen:
            continue
        seen.add(key)
        out.append({"doc": h.get("doc"), "page": h.get("page"), "text": text})
    return out


def _web_fallback(query: str, context: list[Message]) -> AgentResult:
    """내부 검색 도출 불가 시에만 호출되는 웹 폴백."""
    # Web fallback, invoked only when internal search cannot derive an answer.
    try:
        meta = llm.generate_grounded_meta(
            context[-4:],
            system="웹 검색 결과를 활용해 마지막 질문에 한국어 평문으로 간결히 답하라.",
        )
        return {
            "status": "inference",
            "text": "사내 문서에서는 관련 근거를 찾지 못해 웹 검색 결과로 답변합니다(출처: 웹).\n" + (meta["text"] or ""),
            # web_sources — 채팅 리소스 참조 블록의 외부 칩·패널에 취합된다
            # web_sources — aggregated into the external chips/panel of the chat resource block
            "extras": {"web_fallback": True, "web_sources": meta["sources"]},
        }
    except llm.GroundingUnavailableError as e:
        logger.warning("웹 폴백 실패: %s", e)
        return {
            "status": "not_found",
            "text": "",
            "extras": {},
            "fail_reason": "사내 문서에서 관련 근거를 찾지 못했고, 웹 검색 폴백도 사용할 수 없습니다.",
            "alternative": "질문을 더 구체적으로 바꾸거나, 관련 PDF를 data/knowledge/에 추가한 뒤 다시 시도해 주세요.",
        }


def _internal_not_found() -> AgentResult:
    """내부 자료만 사용(allow_web=False)인데 도출 불가일 때의 결과."""
    # Result for when only internal materials are used (allow_web=False) but nothing can be derived.
    return {
        "status": "not_found", "text": "", "extras": {},
        "fail_reason": "사내 문서에서 관련 근거를 찾지 못했습니다.",
        "alternative": "질문을 더 구체적으로 바꾸거나 관련 PDF를 data/knowledge/에 추가해 주세요.",
    }


def _denied() -> AgentResult:
    """현재 사용자에게 지식관리 열람 권한이 전혀 없을 때(도메인 차단)."""
    # When the current user has no read permission for knowledge management at all (domain blocked).
    return {
        "status": "not_found", "text": "", "extras": {},
        "fail_reason": "현재 사용자에게 지식관리 열람 권한이 없어 사내 문서를 조회할 수 없습니다.",
        "alternative": "권한이 있는 자료에 한해 질의할 수 있습니다. 필요한 문서는 관리자에게 권한을 요청하세요.",
    }


# task_runner 가 작업 질의 뒤에 덧붙이는 맥락 블록 머리(요청 조건 · 선행 결과 · 작업 입력) — 로컬 질문에서는 뺀다
# Context-block headers task_runner appends to a task query (request conditions, prior results, task inputs): left out of the local question
_CONTEXT_MARKERS = ("\n\n[사용자가 요청한 대상과 조건", "\n\n[이 작업의 선행 결과", "\n\n[작업 입력]")
LOCAL_QUERY_MAX = 1000


def _primary_question(query: str) -> str:
    """작업 질의에서 덧붙은 맥락 블록을 뺀 본 질문(로컬 에이전트에 그대로 묻는다) / the task query without appended context blocks"""
    q = str(query or "")
    cut = min((i for i in (q.find(m) for m in _CONTEXT_MARKERS) if i >= 0), default=len(q))
    return q[:cut].strip()[:LOCAL_QUERY_MAX]


def _local_extras(query: str, eff: dict | None, user_scoped: bool) -> dict:
    """채팅 로컬 지식 단계 재료 {local_agents, local_query} — 쓸 수 있는 에이전트가 없거나 질문이 비면 {}.
    사용자가 스마트 파일(또는 탐색 패널)로 Public 문서를 직접 좁혔으면 싣지 않는다(사용자 선택이 곧 소스 선택).
    Material for the chat local-knowledge stage {local_agents, local_query}; {} without usable agents or a question. Nothing is
    added when the user narrowed Public documents themselves (smart files or the explore panel): the user's pick is the source pick."""
    if user_scoped:
        return {}
    try:
        ids = [a["id"] for a in knowledge_agents.readable(eff)]
    except Exception:  # noqa: BLE001 — 로컬 목록 실패가 Public 답변을 막지 않는다 / a local lookup failure never blocks the Public answer
        logger.warning("로컬 지식 에이전트 목록 조회 실패, 로컬 없이 진행", exc_info=True)
        return {}
    q = _primary_question(query)
    return {"local_agents": ids, "local_query": q} if ids and q else {}


def _with_local(result: AgentResult, local: dict) -> AgentResult:
    """결과 extras 에 로컬 재료를 덧붙인 사본(원본은 그대로) / a copy of the result with the local material in extras"""
    if not local:
        return result
    return {**result, "extras": {**(result.get("extras") or {}), **local}}


# 로컬 전용 선택(2026-10-28, 리소스 선택 대화 상자 Local 구획): scope_files.local_agents 가 있으면 이 사용자가 쓸 수 있는 에이전트
# (knowledge_agents.readable)와의 교집합만 로컬 재료로 싣고 Public 검색 · 개요 호출은 건너뛴다. 결과는 근거 없음(not_found) 자리다:
# 채팅 답변 단계(app/answers.py)가 그 에이전트들에 묻고, 답이 오면 이 자리를 빼고 로컬 답으로만 취합한다(local_only 표시).
# 명시한 선택은 범위를 넓히지 않는다(pipeline._clean_scope_files 의 workers 원칙과 같다, 2026-10-28 검토 반영): 교집합이 비거나
# (사용 중지 · 삭제 · 권한 없음 · 뷰애즈 전환) 목록을 읽지 못하면 Public 이나 다른 로컬로 가지 않고 근거 없음으로 닫는다. 사유는 어느
# 경우인지 드러내지 않는 한 문장이다. 질문이 비어도 닫는다(물을 본 질문이 없고, Public 으로 가면 고른 범위가 넓어진다).
# Local-only selection (2026-10-28, the Local section of the resource picker): with scope_files.local_agents, only their
# intersection with the agents this user may use (knowledge_agents.readable) rides as local material, and the Public search and
# the overview call are skipped. The result is a no-evidence (not_found) placeholder: the chat answer stage (app/answers.py)
# asks those agents and, when they answer, drops this placeholder and aggregates the local answers alone (the local_only mark).
# An explicit choice never widens (the same rule as workers in pipeline._clean_scope_files; 2026-10-28 review): an empty
# intersection (disabled, deleted, no permission, a view-as switch) or a failed lookup closes as no evidence instead of going to
# Public or other local agents, with one sentence that does not reveal which case it was. An empty question closes too (there is
# no main question to ask, and Public would widen the chosen scope).
LOCAL_ONLY_REASON = "선택한 로컬 지식 에이전트에 질문합니다. Public 문서는 검색하지 않았습니다."
LOCAL_ONLY_ALT = "Public 문서도 찾아보려면 리소스 선택에서 지식 관리 Public 을 골라 다시 질문해 주세요."
LOCAL_ONLY_UNAVAILABLE = "선택한 로컬 지식 에이전트를 지금 쓸 수 없습니다."
LOCAL_ONLY_UNAVAILABLE_ALT = "리소스 선택에서 로컬 지식 에이전트를 다시 고르거나 지식 관리 Public 을 골라 다시 질문해 주세요."
LOCAL_ONLY_NO_QUESTION = "선택한 로컬 지식 에이전트에 물을 질문을 찾지 못했습니다."
LOCAL_ONLY_NO_QUESTION_ALT = "질문을 구체적으로 적어 다시 요청해 주세요."


def _local_closed(reason: str, alternative: str) -> AgentResult:
    """명시한 로컬 선택을 넓히지 않고 닫는 근거 없음 결과. 로컬 재료 · local_only 표시가 없어 카드는 실패로 그려지고, local_closed 표시로
    작업 카드가 로컬 전용 모양(agent_status.local_only, task_runner)이 된다.
    A no-evidence result that closes an explicit local choice without widening. Without local material or the local_only mark the
    card is drawn failed; the local_closed mark gives the card the local-only look (agent_status.local_only, task_runner)."""
    return {"status": "not_found", "text": "", "extras": {"local_closed": True}, "fail_reason": reason, "alternative": alternative}


def _local_only(query: str, eff: dict | None, scope_files: dict | None) -> AgentResult | None:
    """로컬 전용 자리 결과 · 닫는 결과 또는 None(local_agents 를 보내지 않음 = 종전 경로) /
    the local-only placeholder, a closing result, or None (no local_agents sent = the former path)"""
    want = {x for x in ((scope_files or {}).get("local_agents") or []) if isinstance(x, str) and x}
    if not want:
        return None
    try:
        ids = [a["id"] for a in knowledge_agents.readable(eff) if a.get("id") in want]
    except Exception:  # noqa: BLE001 — 목록 실패도 넓히지 않고 닫는다 / a list failure closes too, never widens
        logger.warning("로컬 지식 에이전트 목록 조회 실패, 고른 범위를 넓히지 않고 닫음", exc_info=True)
        return _local_closed(LOCAL_ONLY_UNAVAILABLE, LOCAL_ONLY_UNAVAILABLE_ALT)
    if not ids:
        logger.info("로컬 전용 선택: 쓸 수 있는 에이전트 없음, Public 검색 없이 닫음")
        return _local_closed(LOCAL_ONLY_UNAVAILABLE, LOCAL_ONLY_UNAVAILABLE_ALT)
    q = _primary_question(query)
    if not q:
        logger.info("로컬 전용 선택: 물을 질문 없음, Public 검색 없이 닫음")
        return _local_closed(LOCAL_ONLY_NO_QUESTION, LOCAL_ONLY_NO_QUESTION_ALT)
    logger.info("로컬 전용 선택 — Public 검색 생략, 로컬 에이전트 %d개", len(ids))
    return {"status": "not_found", "text": "",
            "extras": {"local_agents": ids, "local_query": q, "local_only": True},
            "fail_reason": LOCAL_ONLY_REASON, "alternative": LOCAL_ONLY_ALT}


def _run_sync(query: str, context: list[Message], allow_web: bool = True,
              eff: dict | None = None, scope_files: dict | None = None) -> AgentResult:
    # ---- 권한 게이팅(Phase 3) + 스마트 파일 검색범위 좁히기 (eff=None 슈퍼는 권한 우회) ----
    # ---- Permission gating (Phase 3) + smart-file search narrowing (eff=None super bypasses permission) ----
    # 권한상 열람 가능한 파일집합 — None=슈퍼=전체
    # Set of files readable by permission — None = super = all
    allowed = None if eff is None else catalog.allowed_knowledge_files(eff)
    if eff is not None and not catalog.domain_readable(eff, "p_know"):
        logger.info("지식 도메인 차단 — 권한 없음")
        return _denied()
    # 로컬 지식 에이전트만 고른 선택(2026-10-28) — 관문 뒤, Public 검색 앞 / a local-only selection: after the gate, before the Public search
    only = _local_only(query, eff, scope_files)
    if only:
        return only
    # 스마트 파일 선택 → 권한 ∩ 선택으로 검색범위 제한(선택 없으면 권한 전체)
    # Smart-file selection → narrow search to permission ∩ selection (no selection = full permission)
    sel = {f for f in ((scope_files or {}).get("knowledge_files") or [])}
    if sel:
        allowed = sel if allowed is None else (allowed & sel)
    user_scoped = bool(sel)
    # 로컬 지식 재료(2026-09-30) — 관문 뒤 모든 반환에 싣는다(부르지는 않는다) / local material on every return after the gate (no calls here)
    local = _local_extras(query, eff, user_scoped)

    # ── 1단계: 질의 분해 + 개요 소스 선택(2026-08-31) — 목록은 권한∩선택 범위로 제시 ──
    # ── Stage 1: decomposition + overview source selection — the listing honors permission∩selection ──
    universe = sorted(allowed) if allowed is not None else sorted(set(catalog.NODE_FILE.values()))
    ov = _overview(query, context, universe)

    # ── 2단계: 하위 질의별 하이브리드 검색 → 병합(청크 중복 제거, 유사도 내림차순) ──
    # ── Stage 2: hybrid search per sub-query → merge (dedup chunks, sort by similarity) ──
    merged, seen = [], set()
    for sq in ov["subqueries"]:
        for h in kb.search(sq):
            key = (h.get("doc"), h.get("page"), (h.get("text") or "")[:60])
            if key in seen:
                continue
            seen.add(key)
            merged.append(h)
    hits = sorted(merged, key=lambda h: h.get("similarity", 0.0), reverse=True)
    if allowed is not None:
        before = len(hits)
        hits = [h for h in hits if h.get("doc") in allowed]
        if before != len(hits):
            logger.info("지식 필터(권한∩선택): 히트 %d→%d (허용 %d파일)", before, len(hits), len(allowed))
    # 개요가 고른 문서로 좁히되, 좁힌 결과가 약하면 전체 히트 유지(리콜 보전 — 개요 오탐 방어).
    # 사용자가 스마트 파일로 직접 좁힌 경우에는 개요 선택을 적용하지 않는다(사용자 선택이 소스 선택).
    # Narrow to overview-picked docs, but keep the full hits when the narrowed set is weak (recall
    # preservation — guards against overview misses). A user's own smart-file narrowing wins outright.
    if not user_scoped and ov["files"]:
        pool = set(ov["files"])
        narrowed = [h for h in hits if h.get("doc") in pool]
        if narrowed and max(h["similarity"] for h in narrowed) >= settings.KB_WEAK_SIM:
            if len(narrowed) != len(hits):
                logger.info("개요 좁히기: 히트 %d→%d (%d문서)", len(hits), len(narrowed), len(pool))
            hits = narrowed
    if not hits:
        logger.info("근거 없음 — %s", "웹 폴백" if allow_web else "내부만(not_found)")
        return _with_local(_web_fallback(query, context) if allow_web else _internal_not_found(), local)

    # 정렬은 하이브리드 점수 기준이므로, 근거 강도는 전체 후보의 최대 코사인으로 판단한다
    # Sorting is by hybrid score, so evidence strength is judged by the max cosine across all candidates.
    top_sim = max(h["similarity"] for h in hits)
    logger.info("검색 결과: top_sim=%.3f, hits=%s", top_sim, [(h["doc"], h["page"], round(h["similarity"], 3)) for h in hits[:3]])

    if top_sim < settings.KB_WEAK_SIM:
        # 도출 불가 — allow_web일 때만 웹 폴백, 아니면 내부 not_found
        # Cannot derive — web fallback only when allow_web, otherwise internal not_found.
        return _with_local(_web_fallback(query, context) if allow_web else _internal_not_found(), local)

    strong = top_sim >= settings.KB_STRONG_SIM
    # 근거 강도에 따라 사용할 청크 선별(약한 꼬리는 제외)
    # Select the chunks to use based on evidence strength (exclude the weak tail).
    # 병합 검색으로 후보가 늘 수 있어 프롬프트 예산 보호를 위해 상위 8개로 캡(질의 분해 대응)
    # Multi-query merging can grow the pool — cap at the top 8 to protect the prompt budget
    used = ([h for h in hits if h["similarity"] >= settings.KB_WEAK_SIM] or hits[:3])[:8]
    system = ANSWER_SYSTEM if strong else ANSWER_SYSTEM + INFERENCE_NOTE
    text = llm.generate(_build_prompt(query, used, context), system=system)
    return _with_local({
        "status": "answer" if strong else "inference",
        "text": text,
        "extras": {"references": _references(used), "excerpts": _excerpts(used)},
    }, local)


async def run(query: str, context: list[Message], allow_web: bool = True,
              eff: dict | None = None, scope_files: dict | None = None) -> AgentResult:
    return await asyncio.to_thread(_run_sync, query, context, allow_web, eff, scope_files)
