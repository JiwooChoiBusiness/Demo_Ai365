"""업무 자동화 에이전트 API(2026-09-22) — 리소스 센터 › 리소스 관리 › 업무 자동화 에이전트 탭의 등록·수정·삭제·열람.

  GET    /api/work-agents?acting_user_id=        목록(인증 키 마스킹, 엔드포인트 명세 포함) + 기본 제공 에이전트(M코스메틱 이메일 에이전트는 MCP 연결 설정 포함, 2026-09-29) + 선택지·데모 채우기
  POST   /api/work-agents                        등록(API 또는 MCP 방식)
  GET    /api/work-agents/{id}
  PUT    /api/work-agents/{id}
  DELETE /api/work-agents/{id}
  POST   /api/work-agents/discover               MCP 도구 목록 조회(저장 없음; 마스킹 키는 agent_id 로 복원)
  POST   /api/work-agents/test                   API 엔드포인트 1개 테스트 호출(저장 없음)
  POST   /api/work-agents/skills                 Skill 파일 업로드(MCP 방식, 주인 없는 상태) → 저장 본문 skill_ids 로 에이전트에 붙는다(2026-09-23)
  DELETE /api/work-agents/skills/{id}            Skill 파일 삭제(주인 없는 파일은 탭 권한, 에이전트의 파일은 그 에이전트 관리 권한)
  PUT    /api/work-agents/builtin/{id}           기본 제공 에이전트(agent_email · agent_edu) 고친 값 저장(2026-10-06, app/builtin_agents.py) — 그 에이전트 관리(2)
  DELETE /api/work-agents/builtin/{id}           기본값으로 되돌리기

권한(리소스 관리 페이지와 같은 기준): 슈퍼관리자(acting_user_id '') 는 전부. 구성원은 업무 자동화 축에 관리(2) 노드가 하나라도
있어야 탭에 들어오므로 목록·도구 조회·테스트는 mgmt.p_auto, 등록은 p_auto 앵커의 관리(2), 수정·삭제는 그 에이전트 노드의 관리(2)다.
변이마다 access.rebuild_universe() 로 접근 권한 업무 자동화 축의 잎을 다시 만든다.

Work-automation agent API (2026-09-22) behind Resource Center › Resource Management › Work-automation agents.
Permissions mirror the management page: super admin ('' acting id) sees everything; members need manage(2) somewhere under
the automation axis for list/discover/test, manage(2) on the p_auto anchor to create, and manage(2) on the agent's own node
to update or delete. Every mutation rebuilds the permission universe so the axis gets its leaves.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app import access, builtin_agents, catalog, connectors, mock_apis, skill_files, work_agents

logger = logging.getLogger("ai365.work_agents")
router = APIRouter(prefix="/api/work-agents", tags=["work-agents"])


def _eff(acting_user_id: str) -> dict | None:
    aid = (acting_user_id or "").strip()
    if not aid or not aid.isdigit():
        return None  # 슈퍼관리자(나) — 게이팅 없음 / super admin — no gating
    try:
        return access.effective(int(aid))
    except Exception:  # noqa: BLE001
        logger.warning("effective 조회 실패(no=%s) — 전부 차단으로 처리", aid, exc_info=True)
        return {"no": None, "menus": {}, "nodes": {}, "mgmt": {}, "read": {}}


def _require_tab(eff: dict | None) -> None:
    """업무 자동화 탭 진입 조건 = 축 안 어딘가의 관리(2) / the tab's own gate: manage(2) anywhere under the axis"""
    if eff is None or (eff.get("mgmt") or {}).get("p_auto"):
        return
    raise HTTPException(status_code=403, detail="업무 자동화 에이전트 관리 권한이 필요합니다")


def _require_node(eff: dict | None, node_id: str) -> None:
    if eff is None or ((eff.get("nodes") or {}).get(node_id, 0)) >= 2:
        return
    raise HTTPException(status_code=403, detail="해당 에이전트의 관리 권한이 필요합니다")


def _rebuild() -> None:
    try:
        access.rebuild_universe()
    except Exception:  # noqa: BLE001 — 재구축 실패가 저장을 막지 않는다 / a rebuild failure never blocks the save
        logger.warning("업무 자동화 에이전트 변경 후 권한 유니버스 재구축 실패", exc_info=True)


class AgentIn(BaseModel):
    name: str = ""
    description: str = ""
    method: str = "api"
    enabled: bool = True
    config: dict = {}
    skill_ids: list[str] | None = None   # Skill 파일(2026-09-23, MCP 방식): 목록을 주면 그 파일들만 남고, 없으면 그대로 / files to keep; omitted = unchanged
    acting_user_id: str = ""


class DiscoverIn(BaseModel):
    url: str = ""
    auth: dict = {}
    timeout: int | None = 30
    agent_id: str | None = None   # 마스킹된 키 복원 + 관리자 설정 유지 / restores a masked key and keeps per-tool settings
    acting_user_id: str = ""


class BuiltinIn(BaseModel):
    description: str = ""
    config: dict = {}   # M코스메틱 이메일 에이전트만(MCP 연결) / email agent only (its MCP connection)
    acting_user_id: str = ""


class TestIn(BaseModel):
    agent_id: str | None = None   # 마스킹된 키 복원용 / restores a masked key from the stored agent
    config: dict = {}
    endpoint: dict = {}
    values: dict = {}
    acting_user_id: str = ""


def _demo() -> dict:
    """[데모 채우기] 재료 — 서버 안의 가상 ERP(/mock/erp/v1)와 데모 MCP 서버(/mock/mcp). 주소는 {{base_url}} 로 두어 배포 호스트를 따라간다.
    Demo fill data: the in-app mock ERP (/mock/erp/v1) and demo MCP server (/mock/mcp); URLs keep {{base_url}} so they follow the host."""
    mcp = mock_apis.catalog()["mcp"]
    return {
        "api": {"name": "데모 ERP 에이전트", "description": "가상 ERP 의 매출 요약·재고 조회와 주문 승인을 제공하는 데모 에이전트입니다.",
                "config": {"base_url": "{{base_url}}/mock/erp/v1", "version": "v1", "timeout": 30,
                           "auth": {"type": "bearer", "key": mock_apis.DEMO_KEYS["erp"], "name": "Authorization"},
                           "endpoints": [
                               {"name": "GetSalesSummary", "method": "GET", "path": "/sales/summary", "kind": "read",
                                "description": "기간·지점별 매출 요약(매출·목표·달성률·상위 상품)을 조회합니다.",
                                "params": [{"name": "period", "type": "string", "required": False, "description": "조회 월(YYYY-MM). 비우면 이번 달", "example": "2026-08"},
                                           {"name": "branch", "type": "string", "required": False, "description": "지점 이름. all 이면 전체", "example": "all"}]},
                               {"name": "GetInventory", "method": "GET", "path": "/inventory/{sku}", "kind": "read",
                                "description": "품목 1개의 재고(보유·예약·가용·재주문점)를 조회합니다.",
                                "params": [{"name": "sku", "type": "string", "required": True, "description": "품목 코드", "example": "SKU-1001"}]},
                               {"name": "ApproveOrder", "method": "POST", "path": "/orders/{order_id}/approve", "kind": "action",
                                "description": "주문 1건을 승인합니다(상태를 바꾸는 실행형).",
                                "params": [{"name": "order_id", "type": "string", "required": True, "description": "주문 번호(O-숫자)", "example": "O-100231"},
                                           {"name": "note", "type": "string", "required": False, "description": "승인 메모", "example": "정기 발주 승인"}]}]}},
        "mcp": {"name": "데모 MCP 에이전트", "description": mcp["description"],
                "config": {"url": mcp["url"], "timeout": 30, "auth": dict(mcp["auth"])}},
    }


def _meta() -> dict:
    return {"methods": [{"id": "api", "label": "API"}, {"id": "mcp", "label": "MCP"}],
            "http_methods": list(work_agents.HTTP_METHODS), "param_types": list(work_agents.PARAM_TYPES),
            "kinds": [{"id": "read", "label": "조회"}, {"id": "action", "label": "실행"}],
            "api_auth_types": [{"id": "none", "label": "없음"}, {"id": "api_key", "label": "API 키 헤더"},
                               {"id": "bearer", "label": "Bearer 토큰"}, {"id": "basic", "label": "Basic 인증"}],
            "mcp_auth_types": [{"id": "none", "label": "없음"}, {"id": "bearer", "label": "Bearer 토큰"}, {"id": "header", "label": "헤더 키"}],
            "max": work_agents.MAX_AGENTS, "max_endpoints": work_agents.MAX_ENDPOINTS, "max_params": work_agents.MAX_PARAMS,
            "skill_exts": list(skill_files.ALLOWED_EXT), "skill_max_bytes": skill_files.MAX_FILE_BYTES, "skill_max": skill_files.MAX_PER_OWNER,
            "demo": _demo()}


def _builtin() -> list[dict]:
    """기본 제공 에이전트 행 — 기본값에 리소스 관리에서 고친 값을 얹는다(2026-10-06, app/builtin_agents.py). M코스메틱 이메일 에이전트는
    MCP 연결 설정(주소 · 인증 가림 · 도구 명세)을 함께 싣고, 교육 에이전트는 설명까지. 둘 다 edited · updated_at 을 싣는다.
    Built-in rows: defaults overlaid with the Resource Management edits (2026-10-06). The email agent carries its MCP connection
    (URL, masked auth, tool specs); the education agent its description. Both carry edited and updated_at."""
    return [builtin_agents.public(aid, label) for aid, label in catalog.WORK_AGENTS]


@router.get("")
def list_all(acting_user_id: str = "") -> dict:
    eff = _eff(acting_user_id)
    _require_tab(eff)
    return {"agents": [work_agents.editor_record(a) for a in work_agents.list_agents()], "builtin": _builtin(), **_meta()}


@router.post("")
def create(body: AgentIn) -> dict:
    eff = _eff(body.acting_user_id)
    _require_tab(eff)
    _require_node(eff, "p_auto")   # 새 에이전트 = 축 앵커의 관리 / creating needs manage on the axis anchor
    try:
        a = work_agents.create(body.model_dump(exclude={"acting_user_id"}))
    except connectors.ConnectorValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    _rebuild()
    return work_agents.editor_record(a)


@router.post("/discover")
def discover(body: DiscoverIn) -> dict:
    """MCP 도구 목록 조회(저장 없음) — 사설망 차단·타임아웃은 mcp_servers.discover / fetch the tool list without saving"""
    eff = _eff(body.acting_user_id)
    _require_tab(eff)
    builtin = body.agent_id in work_agents.BUILTIN_IDS
    if builtin:   # 기본 제공 에이전트(2026-10-06): 가린 키 복원 · 도구 설정 유지는 지금 쓰는 설정으로 / built-ins restore from their current settings
        cur = builtin_agents.effective(body.agent_id)
        if cur["config"] is None:
            raise HTTPException(status_code=422, detail="MCP 로 연결하는 에이전트가 아닙니다")
        previous = {"method": cur["method"], "config": cur["config"]}
    else:
        previous = work_agents.get_agent(body.agent_id) if body.agent_id else None
        if body.agent_id and previous is None:
            raise HTTPException(status_code=404, detail="에이전트가 삭제되었습니다")
    prev_cfg = (previous or {}).get("config") or {}
    try:
        auth = work_agents._auth(body.auth, work_agents.MCP_AUTH_TYPES, prev_cfg.get("auth") if (previous or {}).get("method") == "mcp" else None)
        url = work_agents._url(body.url, "MCP 서버 주소")
        timeout = work_agents._int(body.timeout, 1, 120, 30, "타임아웃")
        out = work_agents.discover_tools(url, auth, timeout, prev_cfg.get("tools"))
    except connectors.ConnectorValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if builtin:   # 기본 제공 에이전트의 종류는 서버 명세 그대로 / a built-in's tool kinds follow the server spec
        for t in out["tools"]:
            t["kind"] = builtin_agents.locked_kind(t)
    return out


@router.post("/test")
def test(body: TestIn) -> dict:
    """API 엔드포인트 1개 테스트 호출(저장 없음) — 응답은 편집기가 샘플 응답으로 실을 수 있다 / one test call, nothing saved"""
    eff = _eff(body.acting_user_id)
    _require_tab(eff)
    previous = work_agents.get_agent(body.agent_id) if body.agent_id else None
    if body.agent_id and previous is None:
        raise HTTPException(status_code=404, detail="에이전트가 삭제되었습니다")
    try:
        probe = work_agents.normalize({"name": "probe", "method": "api",
                                       "config": {**body.config, "endpoints": [body.endpoint]}}, previous)
    except connectors.ConnectorValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return work_agents.test_endpoint(probe["config"], probe["config"]["endpoints"][0], body.values)


@router.post("/skills")
async def upload_skill(file: UploadFile = File(...), acting_user_id: str = Form("")) -> dict:
    """Skill 파일 1개 업로드(MCP 방식 에이전트용) — 주인 없는 상태로 저장, 에이전트 저장 때 skill_ids 로 붙는다 / pending upload, attached on save"""
    eff = _eff(acting_user_id)
    _require_tab(eff)
    data = await file.read(skill_files.MAX_FILE_BYTES + 1)
    try:
        rec = skill_files.add(file.filename or "", data)
    except skill_files.SkillFileError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return skill_files.public(rec)


@router.delete("/skills/{file_id}")
def delete_skill(file_id: str, acting_user_id: str = "") -> dict:
    """주인 없는 파일은 탭 권한으로, 에이전트에 붙은 파일은 그 에이전트의 관리 권한으로 삭제 / pending: tab gate; attached: manage on that agent"""
    eff = _eff(acting_user_id)
    _require_tab(eff)
    rec = skill_files.get(file_id)
    if rec is None or (rec["owner_kind"] and rec["owner_kind"] != "work_agent"):
        raise HTTPException(status_code=404, detail="존재하지 않는 Skill 파일입니다")
    if rec["owner_kind"]:
        _require_node(eff, rec["owner_id"])
    skill_files.delete(file_id, owner_kind="work_agent")
    return {"ok": True}


def _builtin_label(agent_id: str) -> str:
    if agent_id not in work_agents.BUILTIN_IDS:
        raise HTTPException(status_code=404, detail="기본 제공 에이전트가 아닙니다")
    return dict(catalog.WORK_AGENTS).get(agent_id, agent_id)


@router.put("/builtin/{agent_id}")
def update_builtin(agent_id: str, body: BuiltinIn) -> dict:
    """기본 제공 에이전트 고친 값 저장(2026-10-06) — 그 에이전트 노드의 관리(2). 이름은 바꾸지 않는다.
    Store the edits of a built-in agent (2026-10-06); manage(2) on its node. The name never changes."""
    label = _builtin_label(agent_id)
    eff = _eff(body.acting_user_id)
    _require_tab(eff)
    _require_node(eff, agent_id)
    try:
        builtin_agents.save(agent_id, body.model_dump(exclude={"acting_user_id"}))
    except connectors.ConnectorValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return builtin_agents.public(agent_id, label)


@router.delete("/builtin/{agent_id}")
def reset_builtin(agent_id: str, acting_user_id: str = "") -> dict:
    """[기본값으로 되돌리기] — 고친 값을 지우고 기본값 행을 돌려준다 / drop the edits and return the default row"""
    label = _builtin_label(agent_id)
    eff = _eff(acting_user_id)
    _require_tab(eff)
    _require_node(eff, agent_id)
    builtin_agents.reset(agent_id)
    return builtin_agents.public(agent_id, label)


@router.get("/{agent_id}")
def get_one(agent_id: str, acting_user_id: str = "") -> dict:
    eff = _eff(acting_user_id)
    _require_tab(eff)
    a = work_agents.get_agent(agent_id)
    if a is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 에이전트입니다")
    return work_agents.editor_record(a)


@router.put("/{agent_id}")
def update(agent_id: str, body: AgentIn) -> dict:
    eff = _eff(body.acting_user_id)
    _require_tab(eff)
    _require_node(eff, agent_id)
    try:
        a = work_agents.update(agent_id, body.model_dump(exclude={"acting_user_id"}))
    except connectors.ConnectorValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if a is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 에이전트입니다")
    _rebuild()
    return work_agents.editor_record(a)


@router.delete("/{agent_id}")
def remove(agent_id: str, acting_user_id: str = "") -> dict:
    eff = _eff(acting_user_id)
    _require_tab(eff)
    _require_node(eff, agent_id)
    if not work_agents.delete(agent_id):
        raise HTTPException(status_code=404, detail="존재하지 않는 에이전트입니다")
    _rebuild()
    return {"ok": True}
