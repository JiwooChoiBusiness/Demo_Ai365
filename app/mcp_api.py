"""MCP 서버 API(2026-09-15) — 관리 센터 "API · MCP 연결" 카드의 MCP 서버 목록·등록·수정·삭제·도구 가져오기.

  GET    /api/mcp/servers?acting_user_id=       슈퍼관리자용 목록(인증 키 마스킹, 도구 스냅샷 포함)
  POST   /api/mcp/servers                       등록(도구 스냅샷은 /discover 결과 + 관리자 설정)
  POST   /api/mcp/discover                      저장 없이 서버에 접속해 도구 목록 조회(마스킹 키는 server_id 로 복원)
  GET    /api/mcp/servers/{id}
  PUT    /api/mcp/servers/{id}
  DELETE /api/mcp/servers/{id}                  서버 + 도구 커넥터 삭제
  POST   /api/mcp/servers/{id}/refresh          저장된 주소·인증으로 다시 가져와 관리자 설정을 유지한 채 병합·저장
  GET    /api/mcp/servers/{id}/usage            이 서버의 도구를 쓰는 워크플로우
  POST   /api/mcp/skills                        Skill 파일 업로드(multipart file, 주인 없는 상태) → 저장 본문 skill_ids 로 서버에 붙는다(2026-09-23)
  DELETE /api/mcp/skills/{id}                   Skill 파일 삭제(주인 없는 파일, 또는 MCP 서버의 파일)

MCP server API (2026-09-15) — list/create/update/delete/discover behind the Admin Center "API · MCP connections" card.
Administrative endpoints use the local demo super-user convention (same as connectors_api).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app import access, connectors, kst, mcp_servers, skill_files

logger = logging.getLogger("ai365.mcp")
router = APIRouter(prefix="/api/mcp", tags=["mcp"])


def _require_admin(acting_user_id: str) -> None:
    # 로컬 데모 식별 관례(connectors_api 와 동일) — 운영은 검증된 세션 신원이 필요 / local demo convention; production needs a verified session
    if (acting_user_id or "").strip():
        raise HTTPException(status_code=403, detail="MCP 연결 설정은 슈퍼관리자 전용입니다")


def _rebuild() -> None:
    try:
        access.rebuild_universe()
    except Exception:  # noqa: BLE001 — 재구축 실패가 저장을 막지 않는다 / a rebuild failure never blocks the save
        logger.warning("MCP 서버 변경 후 권한 유니버스 재구축 실패", exc_info=True)


class ServerIn(BaseModel):
    name: str = ""
    description: str = ""
    category: str = "other"
    url: str = ""
    auth: dict = {}
    timeout: int | None = 30
    enabled: bool = True
    tools: list = []
    server_info: dict = {}
    fetched_at: str = ""
    skill_ids: list[str] | None = None   # Skill 파일(2026-09-23): 목록을 주면 그 파일들만 남고, 없으면 그대로 / the files to keep; omitted = unchanged
    acting_user_id: str = ""


class DiscoverIn(BaseModel):
    url: str = ""
    auth: dict = {}
    timeout: int | None = 30
    server_id: str | None = None   # 마스킹된 키 복원용 / restores a masked key from the stored server
    acting_user_id: str = ""


def _meta() -> dict:
    return {"auth_types": [{"id": "none", "label": "없음"}, {"id": "bearer", "label": "Bearer 토큰"}, {"id": "header", "label": "헤더 키"}],
            "max": mcp_servers.MAX_SERVERS, "max_tools": mcp_servers.MAX_TOOLS,
            "skill_exts": list(skill_files.ALLOWED_EXT), "skill_max_bytes": skill_files.MAX_FILE_BYTES, "skill_max": skill_files.MAX_PER_OWNER}


@router.get("/servers")
def list_all(acting_user_id: str = "") -> dict:
    _require_admin(acting_user_id)
    return {"servers": [mcp_servers.editor_record(s) for s in mcp_servers.list_servers()], **_meta()}


@router.post("/servers")
def create(body: ServerIn) -> dict:
    _require_admin(body.acting_user_id)
    try:
        s = mcp_servers.create(body.model_dump(exclude={"acting_user_id"}))
    except connectors.ConnectorValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    _rebuild()
    return mcp_servers.editor_record(s)


@router.post("/discover")
def discover(body: DiscoverIn) -> dict:
    """저장 없이 도구 목록 조회 — 사설망 차단·타임아웃은 mcp_servers.discover / fetch the tool list without saving"""
    _require_admin(body.acting_user_id)
    previous = mcp_servers.get_server(body.server_id) if body.server_id else None
    if body.server_id and previous is None:
        raise HTTPException(status_code=404, detail="MCP 서버 설정이 삭제되었습니다")
    try:
        probe = mcp_servers.normalize({"name": "probe", "url": body.url, "auth": body.auth, "timeout": body.timeout}, previous)
        out = mcp_servers.discover(probe["url"], probe["auth"], probe["timeout"])
    except connectors.ConnectorValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    tools, gone = mcp_servers.merge_tools(out["tools"], previous.get("tools") if previous else None)
    return {"server_info": out["server_info"], "tools": tools, "removed": gone, "skipped": out["skipped"],
            "fetched_at": kst.now_iso()}


@router.get("/servers/{server_id}")
def get_one(server_id: str, acting_user_id: str = "") -> dict:
    _require_admin(acting_user_id)
    s = mcp_servers.get_server(server_id)
    if s is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 MCP 서버입니다")
    return mcp_servers.editor_record(s)


@router.get("/servers/{server_id}/usage")
def usage(server_id: str, acting_user_id: str = "") -> dict:
    """이 서버의 도구를 참조하는 워크플로우 작업 / workflow tasks referencing any tool of this server"""
    _require_admin(acting_user_id)
    from app import flows
    s = mcp_servers.get_server(server_id)
    if s is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 MCP 서버입니다")
    ids = {mcp_servers.tool_connector_id(server_id, t["name"]): t.get("title") or t["name"] for t in (s.get("tools") or [])}
    rows = []
    for f in flows.get_flows():
        for si, stage in enumerate(f.get("stages") or []):
            for ni, node in enumerate(stage.get("nodes") or []):
                if node.get("agent") != "api":
                    continue
                for r in node.get("resources") or []:
                    if r in ids:
                        rows.append({"id": f["id"], "name": f["name"], "stage": si + 1, "task": ni + 1, "tool": ids[r]})
    return {"workflows": rows}


@router.put("/servers/{server_id}")
def update(server_id: str, body: ServerIn) -> dict:
    _require_admin(body.acting_user_id)
    try:
        s = mcp_servers.update(server_id, body.model_dump(exclude={"acting_user_id"}))
    except connectors.ConnectorValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if s is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 MCP 서버입니다")
    _rebuild()
    return mcp_servers.editor_record(s)


@router.post("/servers/{server_id}/refresh")
def refresh(server_id: str, acting_user_id: str = "") -> dict:
    """저장된 주소·인증으로 도구 목록을 다시 가져와 병합·저장 / re-fetch with the stored URL/auth, merge and save"""
    _require_admin(acting_user_id)
    s = mcp_servers.get_server(server_id)
    if s is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 MCP 서버입니다")
    try:
        out = mcp_servers.discover(s["url"], s["auth"], s["timeout"])
        tools, gone = mcp_servers.merge_tools(out["tools"], s.get("tools"))
        saved = mcp_servers.update(server_id, {**s, "tools": tools, "server_info": out["server_info"],
                                               "fetched_at": kst.now_iso()})
    except connectors.ConnectorValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    _rebuild()
    return {**mcp_servers.editor_record(saved), "removed": gone, "skipped": out["skipped"]}


@router.delete("/servers/{server_id}")
def remove(server_id: str, acting_user_id: str = "") -> dict:
    _require_admin(acting_user_id)
    n = mcp_servers.delete(server_id)
    if n < 0:
        raise HTTPException(status_code=404, detail="존재하지 않는 MCP 서버입니다")
    _rebuild()
    return {"ok": True, "removed_tools": n}


# ────────────────────────────────────────────────────────
# Skill 파일(2026-09-23) / skill files
# ────────────────────────────────────────────────────────

@router.post("/skills")
async def upload_skill(file: UploadFile = File(...), acting_user_id: str = Form("")) -> dict:
    """Skill 파일 1개 업로드 — 주인 없는 상태로 저장되고, 서버를 저장할 때 skill_ids 로 붙는다 / one pending upload, attached on save"""
    _require_admin(acting_user_id)
    data = await file.read(skill_files.MAX_FILE_BYTES + 1)
    try:
        rec = skill_files.add(file.filename or "", data)
    except skill_files.SkillFileError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return skill_files.public(rec)


@router.delete("/skills/{file_id}")
def delete_skill(file_id: str, acting_user_id: str = "") -> dict:
    """주인 없는 파일 또는 MCP 서버의 파일 삭제 / delete a pending file or one attached to an MCP server"""
    _require_admin(acting_user_id)
    if not skill_files.delete(file_id, owner_kind="mcp"):
        raise HTTPException(status_code=404, detail="존재하지 않는 Skill 파일입니다")
    return {"ok": True}
