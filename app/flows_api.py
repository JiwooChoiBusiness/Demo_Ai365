"""워크플로우 셋 API — 목록/저장 + 그룹 팔레트 + 실행(SSE).

GET(acting_user_id로 **그룹 구성원 필터** — ''=슈퍼 전체, 편집기 하위 호환) ·
GET /groups/{id}/resources(그룹 권한으로 게이팅된 편집기 팔레트 — 2026-08-18 그룹 종속 전환) ·
PUT(관리자 저장 — 스키마 검증은 위치 지목 422) ·
POST /run(SSE 스트림 — 비구성원 403, /api/chats/{id}/stream과 동일 이벤트 어휘, 의도판단 미경유) ·
POST /resume(2026-09-11 — 검수 질문·실행 카드 응답으로 같은 run 재개, SSE) · GET /runs/{id}(카드 복원 재검증) ·
GET /{id}/summary(실행 확인 팝업 재료 — 설명 AI 요약·실행 흐름·활용 리소스·생성 파일·필요 입력값).
UI 진입은 목업 관리 센터의 m_admin 게이트가 담당 — 다른 데모 관리 API와 동일하게
서버측 별도 인증 게이팅은 두지 않는다(smart_actions_api와 같은 관례).
"""
# Workflow-set API — list/save + group palette + run (SSE).
#
# GET (member-filtered by acting_user_id — '' = super/full list, editor backward-compat),
# GET /groups/{id}/resources (editor palette gated by the group's permissions — group-scoping
# 2026-08-18), PUT (admin save — schema violations are 422s naming the offending spot),
# POST /run (SSE stream — 403 for non-members, same event vocabulary as /api/chats/{id}/stream,
# no intent detection), POST /resume (2026-09-11 — resume the same run from a review-question / run-card
# reply, SSE), GET /runs/{id} (card re-verification on restore), GET /{id}/summary (run-confirm popup:
# AI summary, flow, resources, output file, required inputs). UI entry is gated by the mockup admin
# center's m_admin check — no extra server-side auth gating, same convention as smart_actions_api.

import logging
import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app import access, catalog, db, flow_api_call, flows, groupware
from app.flows import AGENT_LABELS, FLOW_AGENTS, PALETTE_AXIS

logger = logging.getLogger("ai365.flows")

router = APIRouter(prefix="/api/flows", tags=["flows"])


class FlowsIn(BaseModel):
    flows: list
    acting_user_id: str = ""


class RunIn(BaseModel):
    flow_id: str
    chat_id: str
    message: str
    acting_user_id: str = ""


class ResumeIn(BaseModel):
    """카드 응답 재개(2026-09-11) — reply.kind 는 flow_question(answers:{항목 id: 값}) | flow_gate(action: run|revise|cancel, note).
    revise(2026-09-30) = 방금 끝난 단계를 note(필수)를 반영해 다시 실행"""
    # Card-reply resume (2026-09-11) — reply.kind is flow_question (answers: {item id: value}) | flow_gate (action run|revise|cancel,
    # note). revise (2026-09-30) = run the just-finished stage again with the note (required)
    run_id: str
    chat_id: str
    reply: dict
    acting_user_id: str = ""


def _gw_catalog() -> list[dict]:
    """그룹웨어 작업 카탈로그(A안, 2026-08-24 사용자 확정) — 편집기의 그룹웨어 작업 패널이 쓰는
    "하고 싶은 일" 목록. 액션/정보조회/위젯이라는 내부 분류를 노출하는 대신 도구별 섹션(메일·일정·
    팀즈·할 일·문서·위젯) 아래 자연어 항목으로 펼치고, 조회/실행 구분은 항목 배지(kind)로만 남긴다."""
    # Groupware task catalog (option A) — the "things you can do" list for the editor's groupware
    # panel. Tool sections with natural-language items instead of the internal action/info/widget
    # taxonomy; the read/run distinction survives only as a per-item badge (kind).
    from app.smart_catalog import KEY_INDEX, NAMESPACES, NS_ORDER
    groups = [{"ns": ns, "label": NAMESPACES[ns]["label"],
               "items": [{"key": k, "label": v["label"], "kind": v["kind"]}
                         for k, v in KEY_INDEX.items() if v["ns"] == ns]}
              for ns in NS_ORDER]
    groups.append({"ns": "widget", "label": "위젯",
                   "items": [{"key": k, "label": groupware.WIDGET_LABELS[k], "kind": "info"}
                             for k in groupware.WIDGET_KEYS]})
    return groups


def _auto_catalog(geff: dict | None = None) -> list[dict]:
    """업무 자동화 작업 카탈로그 — 그룹웨어 A안과 동형(에이전트별 섹션 + 조회/실행 배지).
    geff가 있으면 그 그룹이 열람(≥1)할 수 있는 에이전트 노드의 섹션만 남긴다(팔레트 게이팅).
    내장 섹션 뒤에 리소스 관리에서 등록한 에이전트 섹션(ns='wa', 2026-09-26)이 붙는다(_work_agent_sections)."""
    # Work-automation task catalog — same shape as the groupware option-A one (per-agent sections +
    # read/run badges). With geff, only sections whose agent node is readable (≥1) survive.
    # Registered agents (ns='wa', 2026-09-26) follow the built-in sections (_work_agent_sections).
    nodes = (geff or {}).get("nodes") or {}
    return [{"ns": sec["ns"], "label": sec["label"],
             "items": [{"key": it["key"], "label": it["label"], "kind": it["kind"]}
                       for it in sec["items"]]}
            for sec in flows.AUTO_CATALOG
            if geff is None or (nodes.get(sec["node"]) or 0) >= 1] + _work_agent_sections(geff)


def _work_agent_sections(geff: dict | None = None) -> list[dict]:
    """등록 업무 자동화 에이전트 섹션(2026-09-26) — {ns:'wa', agent_id, label, method, items:[{key:'wa:<id>:<이름>', label, kind,
    description, inputs, input_schema, output_schema|null, unsupported}]}. 사용 중지된 에이전트·도구는 빼고, 쓸 수 있는 도구가 없는
    섹션은 내보내지 않는다. geff 가 있으면 그 에이전트 노드를 열람(≥1)할 수 있을 때만(None 이면 전부). inputs·input_schema 는
    실행기와 같은 사본(work_agents.as_connector)에서, unsupported(명세 단순화 경고, API 엔드포인트는 [])는 도구 행에서 온다."""
    # Registered work-agent sections (2026-09-26). Disabled agents and tools are left out, and a section with no usable tool is
    # not emitted. With geff, only agents whose node is readable (>= 1); None = all. inputs / input_schema come from the same
    # copy the runner uses (work_agents.as_connector); unsupported (simplified-spec warning, [] for API endpoints) from the tool row.
    from app import work_agents   # 지연 임포트 / lazy import
    from app.execution import PlanError
    from app.tool_contracts import contract
    nodes = (geff or {}).get("nodes") or {}
    try:
        agents = work_agents.list_agents()
    except sqlite3.OperationalError:   # 테이블 미생성(부팅 순서) → 섹션 없음 / table not created yet (boot order) → no sections
        return []
    out = []
    for a in agents:
        if not a.get("enabled", True) or (geff is not None and int(nodes.get(a["id"]) or 0) < 1):
            continue
        items = []
        for t in work_agents.tools_of(a):
            if not t["enabled"]:
                continue
            conn = work_agents.as_connector(a, t["name"])
            try:
                schema = contract(conn)["input_schema"] if conn else None
            except PlanError:   # 명세가 깨진 도구는 실행도 못 하므로 고를 수 없게 뺀다 / a broken schema cannot run, so it is not offered
                schema = None
            if schema is None:
                continue
            items.append({"key": conn["id"], "label": t["name"], "kind": t["kind"], "description": t["description"],
                          "inputs": flow_api_call.input_specs(conn["api"]), "input_schema": schema,
                          "output_schema": t["output_schema"], "unsupported": list(t.get("unsupported") or [])})
        if items:   # 쓸 수 있는 도구가 없는 섹션은 내보내지 않는다 / a section with no usable tool is not emitted
            out.append({"ns": "wa", "agent_id": a["id"], "label": a["name"], "method": a.get("method") or "api", "items": items})
    return out


def _editor_resources() -> dict:
    """편집기용 리소스 목록 — 노드 유니버스 전체(동적 포함). 게이팅용 allowed_*는 쓰지 않는다
    (eff=None은 빈 집합을 돌려주는 게이팅 함수라 편집기 목록에 부적합)."""
    # Editor resource lists — the full node universe (dynamic included). Not the allowed_* gating
    # helpers (those return an empty set for eff=None, which is wrong for an editor listing).
    tbl_labels = {t: l for _, l, t in catalog.DATA_TABLES}
    bi_labels = {f: l for _, l, f in catalog.DATA_BI}
    return {
        "knowledge_files": sorted(set(catalog.NODE_FILE.values())),
        "tables": [{"name": t, "label": tbl_labels.get(t, t)}
                   for t in sorted(set(catalog.NODE_TABLE.values()))],
        "bi": [{"file": f, "label": bi_labels.get(f, f)}
               for f in sorted(set(catalog.NODE_BI.values()))],
        "widgets": [{"key": k, "label": groupware.WIDGET_LABELS[k]} for k in groupware.WIDGET_KEYS],
        "gw_catalog": _gw_catalog(),
        "auto_catalog": _auto_catalog(),
    }


@router.get("")
def list_flows(acting_user_id: str = "") -> dict:
    """목록 — 숫자 acting_user_id면 소속 그룹의 워크플로우만(고아 그룹은 자연 탈락), ''=슈퍼 전체."""
    # List — numeric acting_user_id filters to the member's groups (orphans drop out naturally);
    # '' = super/full list.
    all_flows = flows.get_flows()
    aid = (acting_user_id or "").strip()
    if aid.isdigit():
        gids = {g.get("id") for g in access.member_groups(int(aid))}
        all_flows = [f for f in all_flows if f.get("group") in gids]
    # 진입점 배정(entry_domains) 어휘는 2026-08-22 에이전트 모드 개편으로 폐지 — 워크플로우는
    # 업무 자동화 모드 전속이라 응답에서도 내리지 않는다.
    # The entry-assignment vocabulary was retired with the agent-mode rework (2026-08-22) —
    # workflows belong to the Automation mode only, so the response no longer carries it.
    return {
        "flows": all_flows,
        "agents": list(FLOW_AGENTS),
        "agent_labels": AGENT_LABELS,
        "resources": _editor_resources(),
    }


@router.get("/groups/{group_id}/resources")
def group_resources(group_id: str) -> dict:
    """편집기 그룹 팔레트 — 그룹 권한 안의 리소스·진입점만. 게이팅 원천은 access.group_effective."""
    # Editor palette for one group — only resources/entries within the group's permissions.
    geff = access.group_effective(group_id)
    if geff is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 권한 그룹입니다")
    # 축이 None인 도메인(그룹웨어=기본 제공, 2026-08-24)은 항상 열람 — 게이팅 자체가 없다
    # Domains with a None axis (groupware = base package) are always readable — no gating at all
    readable = {d: (True if ax is None else catalog.domain_readable(geff, ax)) for d, ax in PALETTE_AXIS.items()}
    tbl_labels = {t: l for _, l, t in catalog.DATA_TABLES}
    bi_labels = {f: l for _, l, f in catalog.DATA_BI}
    return {
        "readable": readable,
        "resources": {
            "knowledge_files": sorted(catalog.allowed_knowledge_files(geff)),
            "tables": [{"name": t, "label": tbl_labels.get(t, t)}
                       for t in sorted(catalog.allowed_tables(geff))],
            "bi": [{"file": f, "label": bi_labels.get(f, f)}
                   for f in sorted(catalog.allowed_bi_files(geff))],
            # 그룹웨어는 기본 제공(2026-08-24 사용자 확정) — 위젯·작업 카탈로그 모두 전 그룹 노출
            # Groupware ships in the base package (user decision) — widgets and the task catalog
            # are exposed to every group
            "widgets": [{"key": k, "label": groupware.WIDGET_LABELS[k]} for k in groupware.WIDGET_KEYS],
            "gw_catalog": _gw_catalog(),
            # 업무 자동화는 에이전트 노드(agent_email/agent_edu) 열람 그룹에만 섹션 노출(p_auto 게이팅)
            # + 등록 에이전트 섹션(ns='wa', 2026-09-26)도 그 에이전트 노드(agent_*) 열람 그룹에만
            # Automation sections appear only for groups that can read the agent node (p_auto gating),
            # including the registered-agent sections (ns='wa', 2026-09-26) gated on their agent_* node
            "auto_catalog": _auto_catalog(geff),
            # 커넥터(2026-09-09): 워크플로우 API 작업이 고르는 목록 — 이 그룹에 허용(cn_* lvl≥1, p_conn 앵커는 캐스케이드)된 것만
            # Connectors (2026-09-09): the list the workflow API task picks from — only those granted to this group
            "connectors": _group_connectors(geff),
        },
    }


def _group_connectors(geff: dict) -> list[dict]:
    """그룹에 허용된 활성 API 요약(id·name·description·kind·category + inputs 명세) — 편집기 API 작업의 선택지.
    inputs(2026-09-11) = 필요 입력값 [{name, description, example}] — 편집기가 항목 아래에 표시한다."""
    # Enabled APIs granted to the group (public summary + input specs) — the editor's API-task choices.
    # inputs (2026-09-11) = required inputs [{name, description, example}] shown under each item in the editor.
    from app import connectors as connector_store  # 지연 임포트 / lazy import
    nodes = geff.get("nodes") or {}
    # outputs(2026-09-14) = 응답 설정의 출력 변수 이름 — 편집기 바인딩 변수 메뉴의 {{stepN.<출력>}} 후보
    # outputs (2026-09-14) = the response settings' output variable names — the editor's {{stepN.<output>}} menu candidates
    # source·server·tool(2026-09-15) = MCP 도구 커넥터 표시용 — 편집기가 API 와 "MCP · 서버" 묶음으로 나눠 보여 준다
    # source / server / tool (2026-09-15) identify MCP tool connectors — the editor groups them under "MCP · server"
    # input_schema·output_schema(2026-09-26) = 편집기 명세 보기용(표시 전용) — _connector_schemas 참조
    # input_schema / output_schema (2026-09-26) = display-only specs for the editor (see _connector_schemas)
    tool_rows = _mcp_tool_rows()
    return [{"id": c["id"], "name": c.get("name"), "description": c.get("description"),
             "kind": c.get("kind"), "category": c.get("category"),
             "source": c.get("source") or "api",
             "server": ((c.get("api") or {}).get("mcp") or {}).get("server_name") or "",
             "server_id": ((c.get("api") or {}).get("mcp") or {}).get("server_id") or "",
             "tool": ((c.get("api") or {}).get("mcp") or {}).get("title") or ((c.get("api") or {}).get("mcp") or {}).get("tool") or "",
             "unsupported": ((c.get("api") or {}).get("mcp") or {}).get("unsupported") or [],
             "inputs": flow_api_call.input_specs(c.get("api") or {}),
             "outputs": [o.get("name") for o in (((c.get("api") or {}).get("response") or {}).get("outputs") or [])
                         if isinstance(o, dict) and o.get("name")],
             **_connector_schemas(c, tool_rows)}
            for c in connector_store.list_connectors()
            if c.get("enabled", True) and int(nodes.get(c["id"], 0) or 0) >= 1]


def _mcp_tool_rows() -> dict:
    """MCP 서버별 도구 행 색인 {server_id: {도구 이름: 도구 행}} — 출력 명세 조회용 / per-server tool rows, for output-schema lookups"""
    from app import mcp_servers   # 지연 임포트 / lazy import
    return {s["id"]: {t.get("name"): t for t in (s.get("tools") or []) if isinstance(t, dict)}
            for s in mcp_servers.list_servers()}


def _connector_schemas(c: dict, tool_rows: dict) -> dict:
    """팔레트 커넥터의 입력·출력 명세(2026-09-26, 표시 전용). input_schema = 실행 계약(tool_contracts.contract)의 입력 명세.
    output_schema = MCP 도구는 서버에 저장된 그 도구 행의 출력 명세(없으면 null — 실행 계약에는 넣지 않는다: 넣으면 tool_runtime 이
    응답 검증을 해 버린다), API 는 응답 설정의 출력 변수가 있으면 {이름: 문자열 · "응답 경로 <path>"} 객체, 없으면 null."""
    # Palette connector specs (2026-09-26, display only). input_schema = the runtime contract's input schema.
    # output_schema = for MCP tools the stored tool row's output schema (null when absent; never put into the runtime
    # contract, where tool_runtime would start validating responses); for APIs an object of the response output variables
    # ({name: string, "응답 경로 <path>"}), or null when there are none.
    from app.execution import PlanError
    from app.tool_contracts import contract
    api = c.get("api") or {}
    try:
        input_schema = contract(c)["input_schema"]
    except PlanError:   # 저장된 명세가 깨졌어도 팔레트는 열린다 / a broken stored spec never breaks the palette
        input_schema = {"type": "object", "properties": {}, "required": []}
    output_schema = None
    if (c.get("source") or "api") == "mcp":
        m = api.get("mcp") or {}
        row = (tool_rows.get(m.get("server_id")) or {}).get(m.get("tool")) or {}
        output_schema = row.get("output_schema") if isinstance(row.get("output_schema"), dict) else None
    else:
        outs = [o for o in ((api.get("response") or {}).get("outputs") or []) if isinstance(o, dict) and o.get("name")]
        if outs:
            output_schema = {"type": "object",
                             "properties": {o["name"]: {"type": "string", "description": f"응답 경로 {o.get('path') or ''}".strip()}
                                            for o in outs}}
    return {"input_schema": input_schema, "output_schema": output_schema}


@router.put("")
def save_flows(body: FlowsIn) -> dict:
    try:
        normalized = flows.normalize_flows(body.flows)
    except flows.FlowValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, "flows": flows.put_flows(normalized)}


def _member_or_403(flow: dict, acting_user_id: str) -> None:
    """그룹 구성원만(2026-08-18) — 프론트 필터와 독립인 서버측 최종 방어. ''=슈퍼 통과."""
    # Members only (2026-08-18) — the server-side defense independent of front-end filtering. '' = super passes.
    aid = (acting_user_id or "").strip()
    if aid.isdigit():
        gids = {g.get("id") for g in access.member_groups(int(aid))}
        if flow.get("group") not in gids:
            raise HTTPException(status_code=403, detail="이 워크플로우를 실행할 권한이 없습니다")


def _cancel_stale_runs(chat_id: str) -> None:
    """새 워크플로우 실행 전 — 그 채팅의 카드 대기·중단 워크플로우 run 을 취소하고 카드를 응답 완료 처리(2026-09-11)."""
    # Before a new workflow run — cancel the chat's card-waiting/interrupted workflow runs and mark their cards answered.
    from app import execution_store
    from app.conversation_execution import resolve_cards
    for rid in execution_store.cancel_workflow_runs(chat_id):
        run = execution_store.get(rid)
        if run:
            resolve_cards(run)


@router.post("/run")
async def run(body: RunIn) -> EventSourceResponse:
    flow = flows.find_flow(body.flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 워크플로우입니다")
    _member_or_403(flow, body.acting_user_id)
    chat = db.get_chat(body.chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 채팅입니다")
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="message가 비어 있습니다")

    from app import artifact_execution, background_execution
    # 낡은 카드 대기 run 은 새 실행이 대체한다(모드 중 새 메시지 = 새 실행) / a stale card-waiting run is replaced by the new run
    _cancel_stale_runs(chat["id"])
    return background_execution.response(chat["id"], artifact_execution.workflow_run(flow, chat, message, body.acting_user_id))


@router.post("/resume")
async def resume(body: ResumeIn) -> EventSourceResponse:
    """카드 응답으로 재개(2026-09-11, SSE) — 검증 순서: 채팅 404 → run 404/채팅 불일치 → kind≠workflow 422 → actor 403 →
    state≠needs_input 409 → waiting.kind≠reply.kind 409 → 필수 항목 미답 422 / 게이트 action 이 run·revise·cancel 이 아니면 422 /
    revise 인데 요청이 비었거나 너무 길면 422(2026-09-30). 게이트 취소는 run_flow 재진입 없이 마감, revise 는 같은 단계부터 재진입."""
    # Resume from a card reply (2026-09-11, SSE) — validation order: chat 404 → run 404/mismatch → kind≠workflow 422 →
    # actor 403 → state≠needs_input 409 → waiting.kind≠reply.kind 409 → unanswered required items 422 / a gate action other
    # than run, revise or cancel 422 / revise with a blank or too long note 422 (2026-09-30). A gate cancel settles without
    # re-entering run_flow; revise re-enters from the same stage.
    from app import artifact_execution, background_execution, execution_store
    chat = db.get_chat(body.chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 채팅입니다")
    run_ = execution_store.get(body.run_id)
    if run_ is None or run_["chat_id"] != chat["id"]:
        raise HTTPException(status_code=404, detail="존재하지 않는 실행입니다")
    snap = run_["snapshot"]
    if snap.get("kind") != "workflow":
        raise HTTPException(status_code=422, detail="워크플로우 실행이 아닙니다")
    if (snap.get("actor") or "") != (body.acting_user_id or ""):
        raise HTTPException(status_code=403, detail="현재 사용자의 실행만 재개할 수 있습니다")
    if run_["state"] != "needs_input":
        raise HTTPException(status_code=409, detail="이미 처리된 카드입니다")
    reply = body.reply if isinstance(body.reply, dict) else {}
    waiting = snap.get("waiting") or {}
    if reply.get("kind") not in ("flow_question", "flow_gate") or waiting.get("kind") != {"flow_question": "review", "flow_gate": "gate"}[reply["kind"]]:
        raise HTTPException(status_code=409, detail="이 실행이 기다리는 카드가 아닙니다")
    if reply["kind"] == "flow_question":
        answers = reply.get("answers") if isinstance(reply.get("answers"), dict) else {}
        missing = [q.get("label") or q.get("id") for q in waiting.get("questions") or []
                   if q.get("required") and (answers.get(q.get("id")) is None
                                             or (isinstance(answers.get(q.get("id")), str) and not answers.get(q.get("id")).strip()))]
        if missing:
            raise HTTPException(status_code=422, detail="필수 항목에 답해 주세요: " + ", ".join(str(m) for m in missing))
        for q in waiting.get("questions") or []:
            v = answers.get(q.get("id"))
            if q.get("kind") == "choice" and v not in (None, "") and v not in (q.get("options") or []):
                raise HTTPException(status_code=422, detail=f"'{q.get('label') or q.get('id')}'은(는) 선택지 중에서 골라 주세요")
    elif reply.get("action") not in ("run", "cancel", "revise"):
        raise HTTPException(status_code=422, detail="action은 run, revise 또는 cancel이어야 합니다")
    elif reply.get("action") == "revise":
        # 수정 요청(2026-09-30): 요청 문장이 반드시 있어야 한다(앞뒤 공백 제외, MAX_GATE_NOTE 자 이하 — 넘으면 자르지 않고 거부)
        # Revision request (2026-09-30): the instruction is required (trimmed, at most MAX_GATE_NOTE characters; longer is rejected, not cut)
        raw = reply.get("note")
        note = raw.strip() if isinstance(raw, str) else ""
        if not note:
            raise HTTPException(status_code=422, detail="수정 요청 내용을 입력해 주세요")
        if len(note) > flows.MAX_GATE_NOTE:
            raise HTTPException(status_code=422, detail=f"수정 요청은 {flows.MAX_GATE_NOTE}자 이하로 입력해 주세요")
    if artifact_execution.resume_workflow(run_, reply):
        return background_execution.response(chat["id"], artifact_execution.cancelled_events(run_))
    return background_execution.response(
        chat["id"], artifact_execution.workflow_run(snap["flow"], chat, snap["message"], body.acting_user_id, run_))


@router.get("/runs/{run_id}")
def run_status(run_id: str) -> dict:
    """카드 복원 재검증(2026-09-11) — {run_id, chat_id, state, waiting_kind, stage, flow_id, flow_name}
    + 진행 표시(2026-09-30) {name, total_stages, stage_index(0부터)} — artifact_execution.run_status 참조"""
    # Card re-verification on restore (2026-09-11), plus progress fields (2026-09-30) {name, total_stages, stage_index (0-based)}.
    from app import artifact_execution, execution_store
    run_ = execution_store.get(run_id)
    if run_ is None or run_["snapshot"].get("kind") != "workflow":
        raise HTTPException(status_code=404, detail="존재하지 않는 실행입니다")
    return artifact_execution.run_status(run_)


@router.get("/{flow_id}/summary")
def summary(flow_id: str, acting_user_id: str = "") -> dict:
    """실행 확인 팝업(2026-09-11) — 설명(AI 요약)·실행 흐름·활용 리소스·단계별 생성 파일(2026-09-29 최종 파일 폐지)·필요 입력값.
    비구성원 403."""
    # Run-confirm popup (2026-09-11) — AI summary, flow, resources, per-stage output files (the final file is retired on
    # 2026-09-29), required inputs. 403 for non-members.
    flow = flows.find_flow(flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 워크플로우입니다")
    _member_or_403(flow, acting_user_id)
    return flows.flow_summary(flow)
