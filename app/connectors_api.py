"""커넥터 API(2026-09-09) — 관리 센터 "커넥터 설정" 카드의 목록·등록·수정·삭제·테스트.

  GET    /api/connectors?acting_user_id=   슈퍼관리자용 목록(인증정보 마스킹)
  POST   /api/connectors                   등록(422: 이름·설명·URL 등 지목)
  GET    /api/connectors/{id}
  PUT    /api/connectors/{id}
  DELETE /api/connectors/{id}
  POST   /api/connectors/test              등록 전 테스트(저장 없음) — 워크플로우 api-test 와 같은 결과 모양

Connector API (2026-09-09) — list/create/update/delete/test behind the Admin Center "Connector settings" card.
Administrative endpoints use the local demo super-user convention. Available APIs are permission-filtered.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import access, connectors, flow_api_call
from app.tool_runtime import call_connector
from app.tool_contracts import prepare_workflow_inputs

logger = logging.getLogger("ai365.connectors")
router = APIRouter(prefix="/api/connectors", tags=["connectors"])


def _require_admin(acting_user_id: str) -> None:
    # Existing local-demo identity convention. Production must supply a verified session identity.
    if (acting_user_id or "").strip():
        raise HTTPException(status_code=403, detail="API 설정은 슈퍼관리자 전용입니다")


def _rebuild() -> None:
    """변이 뒤 권한 유니버스 재구축 — 커넥터 1개 = p_conn 하위 노드 1개(3단계) / rebuild the permission universe after a mutation"""
    try:
        access.rebuild_universe()
    except Exception:  # noqa: BLE001 — 재구축 실패가 저장을 막지 않는다 / a rebuild failure never blocks the save
        logger.warning("커넥터 변경 후 권한 유니버스 재구축 실패", exc_info=True)


class ConnectorIn(BaseModel):
    name: str = ""
    description: str = ""
    category: str = "other"
    kind: str = "read"
    enabled: bool = True
    api: dict = {}
    acting_user_id: str = ""


class ConnectorTestIn(BaseModel):
    api: dict
    vars: dict = {}
    acting_user_id: str = ""
    kind: str = "action"  # Unknown callers default to no automatic retries.
    connector_id: str | None = None


def _meta() -> dict:
    return {"categories": [{"id": k, "label": v} for k, v in connectors.CATEGORY_LABELS.items()],
            "kinds": [{"id": k, "label": v} for k, v in connectors.KIND_LABELS.items()],
            "max": connectors.MAX_CONNECTORS,
            # 실행 환경이 자동으로 채우는 입력 이름(2026-09-14) — 입력값 설명 표가 제외할 목록의 단일 원천(프런트 하드코딩 대체)
            # Auto-filled input names (2026-09-14) — the single source for what the input table excludes (replaces the front-end constant)
            "auto_inputs": [v[len("input."):] for v in flow_api_call.AUTO_INPUTS]}


@router.get("")
def list_all(acting_user_id: str = "") -> dict:
    _require_admin(acting_user_id)
    # mcp_servers(2026-09-15): 목록 화면이 한 번의 조회로 API 행과 MCP 서버·도구 행을 함께 그린다 / one fetch draws API rows and MCP servers/tools
    from app import mcp_servers
    return {"connectors": [connectors.editor_record(c) for c in connectors.list_connectors()],
            "mcp_servers": [mcp_servers.public(s) for s in mcp_servers.list_servers()], **_meta()}


@router.get("/available")
def available(acting_user_id: str = "") -> dict:
    """뷰애즈 사용자가 쓸 수 있는 API 목록 — 활성 + 권한(access.allowed_connectors) 통과분만, 비밀 없는 요약(+ inputs).
    슈퍼('')는 활성 전체. (채팅 커넥터 알약은 2026-09-11 폐지 — 워크플로우 실행기가 같은 함수로 다시 검사한다.)"""
    # APIs the view-as user may use — enabled ∩ permitted (access.allowed_connectors), secrets stripped (+ inputs).
    # Super ('') sees every enabled API. (The chat connector pill was retired 2026-09-11; the workflow runner re-checks.)
    allowed = access.allowed_connectors(acting_user_id)
    items = [connectors.public(c) for c in connectors.list_connectors()
             if c.get("enabled") and (allowed is None or c["id"] in allowed)]
    return {"connectors": items}


@router.post("")
def create(body: ConnectorIn) -> dict:
    _require_admin(body.acting_user_id)
    try:
        c = connectors.create(body.model_dump())
    except connectors.ConnectorValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    _rebuild()
    return connectors.editor_record(c)


@router.post("/test")
async def test(body: ConnectorTestIn) -> dict:
    """저장 없이 설정 그대로 1회 호출(서버 대리 호출·내부망 차단은 flow_api_call) / one unsaved call made by the server"""
    _require_admin(body.acting_user_id)
    previous = connectors.get_connector(body.connector_id) if body.connector_id else None
    if body.connector_id and previous is None:
        raise HTTPException(status_code=404, detail="테스트할 API가 삭제되었습니다")
    try:
        raw = connectors.restore_credentials({"api": body.api}, previous)
        c = connectors.normalize({**raw, "name": "API 테스트", "description": "등록 전 실행 검증", "kind": body.kind})
        cfg = c["api"]
        inputs = {k[6:]: v for k, v in body.vars.items() if k.startswith("input.")
                  and k not in flow_api_call.AUTO_INPUTS and v is not None and v != ""}
        inputs, missing, _ = prepare_workflow_inputs(c, inputs)
        if missing:
            raise ValueError("필수 입력을 알려주세요: " + ", ".join(missing))
        r = await call_connector(c, str(body.vars.get("input.question") or ""), body.acting_user_id, inputs,
                                 test_vars={k: v for k, v in body.vars.items()
                                            if k in flow_api_call.variables_in(cfg) and k not in ("api_key", "base_url")},
                                 keep_body=flow_api_call.TEST_BODY_KEEP)
        r["variables_used"] = flow_api_call.variables_in(cfg)
        return flow_api_call.redact(r, (cfg.get("auth") or {}).get("key") or "")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/{conn_id}")
def get_one(conn_id: str, acting_user_id: str = "") -> dict:
    _require_admin(acting_user_id)
    c = connectors.get_connector(conn_id)
    if c is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 커넥터입니다")
    return connectors.editor_record(c)


@router.get("/{conn_id}/usage")
def usage(conn_id: str, acting_user_id: str = "") -> dict:
    _require_admin(acting_user_id)
    from app import flows
    return {"workflows": [{"id": f["id"], "name": f["name"], "stage": si + 1, "task": ni + 1}
                          for f in flows.get_flows() for si, stage in enumerate(f.get("stages") or [])
                          for ni, node in enumerate(stage.get("nodes") or [])
                          if node.get("agent") == "api" and conn_id in (node.get("resources") or [])]}


@router.put("/{conn_id}")
def update(conn_id: str, body: ConnectorIn) -> dict:
    _require_admin(body.acting_user_id)
    try:
        c = connectors.update(conn_id, body.model_dump())
    except connectors.ConnectorValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if c is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 커넥터입니다")
    _rebuild()
    return connectors.editor_record(c)


@router.delete("/{conn_id}")
def remove(conn_id: str, acting_user_id: str = "") -> dict:
    _require_admin(acting_user_id)
    c = connectors.get_connector(conn_id)
    if c is not None and c.get("source") == "mcp":
        raise HTTPException(status_code=409, detail="MCP 서버의 도구는 MCP 서버 설정에서 사용 여부를 끄거나 서버를 삭제하세요")
    if not connectors.delete(conn_id):
        raise HTTPException(status_code=404, detail="존재하지 않는 커넥터입니다")
    _rebuild()
    return {"ok": True}
