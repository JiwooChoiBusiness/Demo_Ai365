"""로컬 지식 에이전트 API(2026-09-29, 구현 계약 3 · 4절) — 리소스 센터 › 지식 관리(문서 관리 · 리소스 관리 › 지식 관리 에이전트)의
등록 · 수정 · 삭제 · 연결 테스트 · Skills 와 Local 탭(폴더 · 문서 · 미리보기 · 다운로드 · 업로드 · 삭제 프록시).

  GET    /api/knowledge-agents?acting_user_id=                  슈퍼 = 전부(편집 레코드), 구성원 = 열람 가능 · 사용 중 + 관리(2) 인 것
                                                                (공개 레코드 + editable), 응답에 can_register
  POST   /api/knowledge-agents                                  등록(슈퍼 또는 p_klocal 앵커 관리) → 201 {"agent"}
  POST   /api/knowledge-agents/check                            연결 테스트 — id 없는 초안 = 등록 권한, id 있음 = 그 에이전트 관리
  POST   /api/knowledge-agents/skills                           Skill 파일 업로드(슈퍼 또는 mgmt.p_klocal, 주인 없는 상태)
  DELETE /api/knowledge-agents/skills/{file_id}                 Skill 파일 삭제(주인 없음 = mgmt.p_klocal, 붙은 파일 = 그 에이전트 관리)
  GET    /api/knowledge-agents/{id}                             편집 레코드(그 에이전트 관리)
  PUT    /api/knowledge-agents/{id}                             수정(그 에이전트 관리, 가린 비밀 유지, 빠진 항목 = 유지)
  DELETE /api/knowledge-agents/{id}                             삭제(그 에이전트 관리, grant 는 그대로, Skill 파일 삭제)
  GET    /api/knowledge-agents/{id}/folders                     폴더 트리(열람 ≥1)
  GET    /api/knowledge-agents/{id}/documents?folder_id=        문서 목록(열람 ≥1)
  POST   /api/knowledge-agents/{id}/documents                   업로드(관리 = 2, Content-Length 가 상한을 넘으면 본문을 읽기 전에 413)
  GET    /api/knowledge-agents/{id}/documents/{doc}/status      처리 상태(열람 ≥1)
  GET    /api/knowledge-agents/{id}/documents/{doc}/preview     PDF · 텍스트 미리보기(열람 ≥1), 그 밖 형식 415
  GET    /api/knowledge-agents/{id}/documents/{doc}/download    원본(열람 ≥1, attachment · RFC 5987)
  DELETE /api/knowledge-agents/{id}/documents/{doc}             삭제(관리 = 2)

권한(2026-09-29 사용자 결정: 등록은 관리 센터가 아니라 리소스 센터에서, 업무 자동화 에이전트와 같은 방식): acting_user_id 가 비었거나
숫자가 아니면 슈퍼관리자(resources_api._eff 와 같은 규약), 숫자면 access.effective 로 서버가 다시 계산한다. 등록 = p_klocal 앵커
노드의 관리(2), 에이전트 1개의 수정 · 삭제 · 편집 레코드 · 저장된 연결 테스트 = 그 kl_* 노드의 관리(2), Skill 업로드 = 축 어딘가의
관리(mgmt.p_klocal). 프록시는 Public 의 "GET 무검사" 원칙과 달리 GET 도 검사한다(고객 시스템 자격 증명으로 가져오는 자료라서).
사용 중지 = 409, 에이전트 오류 = 502 + 가린 사유. 바깥으로 HTTP 를 보내는 핸들러는 전부 plain def 다 — async def 안의 동기 httpx 가
같은 서버의 /mock 을 부르면 이벤트 루프가 막힌다.

Local knowledge agent API (2026-09-29, contract sections 3 and 4): registration, edits, deletion, the connection test and
skills under Resource Center › Knowledge (document management and Resource management › knowledge agents), plus the Local
tab's folder, document, preview, download, upload and delete proxy.
Permissions (user decision 2026-09-29: register from the Resource Center, not the Admin Center, like work agents): an empty or
non-digit acting_user_id is the super admin (same convention as resources_api._eff); digits are recomputed server-side with
access.effective. Registering needs manage(2) on the p_klocal anchor node; editing, deleting, reading the editor record and
saved checks need manage(2) on that kl_* node; skill uploads need manage anywhere under the axis (mgmt.p_klocal). Unlike the
Public tab's "unchecked GETs", the proxy checks GETs too (the data is fetched with the customer system's credentials).
Disabled = 409, agent failures = 502 with a redacted reason. Every handler that makes outbound HTTP is a plain def: a sync
httpx call inside async def blocks the loop when it calls this server's /mock.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.routing import APIRoute
from starlette.background import BackgroundTask

from app import access, connectors, skill_files
from app import knowledge_agents as ka

logger = logging.getLogger("ai365.knowledge_agents")
MULTIPART_SLACK = 1024 * 1024   # 파일 상한 위 멀티파트 머리 여유(약 1MB) / multipart framing allowance above the file cap (about 1 MB)


def _too_large_detail() -> str:
    return f"파일이 너무 큽니다(최대 {ka.MAX_UPLOAD_BYTES // (1024 * 1024)}MB)"


class _UploadLimitRoute(APIRoute):
    """문서 업로드(POST …/{agent_id}/documents)는 Content-Length 가 상한(50MB + 여유)을 넘으면 본문을 파싱하기 전에 413 을
    돌려준다(2026-09-29) — FastAPI 는 핸들러 전에 멀티파트 본문 전체를 읽어 임시 파일로 옮기므로 핸들러 안의 검사로는 늦다.
    Content-Length 가 없는(청크) 업로드는 핸들러의 크기 검사가 막는다. 다른 경로는 그대로 둔다.
    Document uploads (POST …/{agent_id}/documents) get a 413 before the body is parsed when Content-Length exceeds the cap
    (50 MB plus slack) (2026-09-29): FastAPI reads and spools the whole multipart body before the handler, so a handler check
    comes too late. Chunked uploads without Content-Length are still stopped by the handler's size check. Other routes are untouched."""

    def get_route_handler(self):
        handler = super().get_route_handler()
        if not (self.path.endswith("/{agent_id}/documents") and "POST" in (self.methods or set())):
            return handler

        async def limited(request: Request):
            length = (request.headers.get("content-length") or "").strip()
            if length.isdigit() and int(length) > ka.MAX_UPLOAD_BYTES + MULTIPART_SLACK:
                return JSONResponse(status_code=413, content={"detail": _too_large_detail()})
            return await handler(request)
        return limited


router = APIRouter(prefix="/api/knowledge-agents", tags=["knowledge-agents"], route_class=_UploadLimitRoute)

_NO_SNIFF = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}


# ────────────────────────────────────────────────────────
# 권한 / permissions
# ────────────────────────────────────────────────────────

def _eff(acting_user_id: str) -> dict | None:
    """resources_api._eff 와 같은 규약 — 빈 값 · 숫자 아님 = 슈퍼(None), 조회 실패 = 전부 차단 / same contract as resources_api._eff"""
    aid = (acting_user_id or "").strip()
    if not aid or not aid.isdigit():
        return None
    try:
        return access.effective(int(aid))
    except Exception:  # noqa: BLE001
        logger.warning("effective 조회 실패(no=%s), 전부 차단으로 처리", aid, exc_info=True)
        return {"no": None, "menus": {}, "nodes": {}, "mgmt": {},
                "read": {"p_know": False, "p_data": False, "p_auto": False, "p_klocal": False}}


def _actor(value) -> str:
    """본문 · 폼의 acting_user_id → 문자열(숫자로 와도 구성원으로) / body or form acting_user_id → str (a number stays a member)"""
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()


REGISTER_DENIED = "로컬 지식 에이전트를 등록할 권한이 없습니다"
MANAGE_DENIED = "이 에이전트의 관리 권한이 필요합니다"
VIEW_DENIED = "이 에이전트를 볼 권한이 없습니다"
KLOCAL_ANCHOR = "p_klocal"


def _level(eff: dict | None, node_id: str) -> int:
    """노드 레벨(슈퍼 = 2) / node level (super = 2)"""
    if eff is None:
        return 2
    try:
        return int(((eff.get("nodes") or {}).get(node_id, 0)) or 0)
    except (TypeError, ValueError):
        return 0


def _can_register(eff: dict | None) -> bool:
    """등록 권한 = 슈퍼 또는 p_klocal 앵커 노드 자체의 관리(2) — work_agents_api 의 p_auto 규칙과 같다.
    May register = super, or manage(2) on the p_klocal anchor node itself (the work_agents_api p_auto rule)."""
    return _level(eff, KLOCAL_ANCHOR) >= 2


def _require_register(eff: dict | None) -> None:
    if not _can_register(eff):
        raise HTTPException(status_code=403, detail=REGISTER_DENIED)


def _require_tab(eff: dict | None) -> None:
    """Skills 관문 = 슈퍼 또는 축 어딘가의 관리(mgmt.p_klocal) / skills gate: super or manage anywhere under the axis"""
    if eff is None or (eff.get("mgmt") or {}).get(KLOCAL_ANCHOR):
        return
    raise HTTPException(status_code=403, detail=REGISTER_DENIED)


def _require_manage(eff: dict | None, agent_id: str) -> None:
    """에이전트 1개의 관리(2) — 슈퍼는 통과 / manage(2) on one agent; super passes"""
    if _level(eff, agent_id) < 2:
        raise HTTPException(status_code=403, detail=MANAGE_DENIED)


def _managed_agent(agent_id: str, eff: dict | None) -> dict:
    """없는 에이전트 404 → 관리 권한 403 / 404 for a missing agent, then 403 without manage"""
    agent = ka.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 에이전트입니다")
    _require_manage(eff, agent_id)
    return agent


def _proxy_agent(agent_id: str, acting_user_id: str, need: int) -> dict:
    """프록시 공통 관문 — 없는 에이전트 404 → 레벨 부족 403 → 사용 중지 409 / proxy gate: 404, then 403, then 409"""
    agent = ka.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 에이전트입니다")
    if _level(_eff(acting_user_id), agent_id) < need:
        raise HTTPException(status_code=403, detail=VIEW_DENIED if need <= 1 else MANAGE_DENIED)
    if not agent.get("enabled"):
        raise HTTPException(status_code=409, detail="사용 중지된 에이전트입니다")
    return agent


def _rebuild() -> None:
    try:
        access.rebuild_universe()
    except Exception:  # noqa: BLE001 — 재구축 실패가 저장을 막지 않는다 / a rebuild failure never blocks the save
        logger.warning("지식 에이전트 변경 후 권한 유니버스 재구축 실패", exc_info=True)


def _invalid(e: connectors.ConnectorValidationError) -> HTTPException:
    return HTTPException(status_code=409 if isinstance(e, ka.KnowledgeAgentConflictError) else 422, detail=str(e))


def _agent_failed(e: ka.AgentCallError, *, doc: bool = False, preview: bool = False, upload: bool = False) -> HTTPException:
    """에이전트 오류 → 응답 상태. 문서 404 · 미리보기 415 · 업로드 413/422 는 그대로, 나머지는 502 + 가린 사유.
    Agent failure → response status: document 404, preview 415 and upload 413/422 pass through; the rest is 502."""
    if doc and e.status == 404:
        return HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")
    if preview and e.status == 415:
        return HTTPException(status_code=415, detail="미리보기를 지원하지 않는 형식입니다")
    if upload and e.status == 413:
        return HTTPException(status_code=413, detail=_too_large_detail())
    if upload and e.status in (400, 415, 422):
        return HTTPException(status_code=422, detail="에이전트가 파일을 받지 않았습니다: " + e.reason)
    logger.info("지식 에이전트 호출 실패: %s", e.reason)
    return HTTPException(status_code=502, detail="에이전트에 연결하지 못했습니다: " + e.reason)


# ────────────────────────────────────────────────────────
# 목록 · 등록 · 연결 테스트 · Skills / list, create, check, skills
# ────────────────────────────────────────────────────────

@router.get("")
def list_agents(acting_user_id: str = "") -> dict:
    """슈퍼 = 전부(사용 중지 포함, 편집 레코드). 구성원 = 레벨 ≥1 이고 사용 중인 것 + 관리(2) 인 것은 사용 중지여도(다시 켤 수 있게)
    공개 레코드로, 레코드마다 editable(레벨 = 2). can_register = 등록 권한. 순서 = pos.
    Super: everything (disabled too) as editor records. Members: level >= 1 and enabled, plus disabled ones they manage (so they
    can switch them back on), as public records with editable (level == 2). can_register = may register. Ordered by pos."""
    eff = _eff(acting_user_id)
    agents = ka.list_agents()
    if eff is None:
        return {"agents": [{**ka.editor_record(a), "editable": True} for a in agents], "super": True, "can_register": True}
    out = []
    for a in agents:
        lvl = _level(eff, a["id"])
        if lvl >= 2 or (lvl >= 1 and a.get("enabled")):
            out.append({**ka.public_record(a, lvl), "editable": lvl >= 2})
    return {"agents": out, "super": False, "can_register": _can_register(eff)}


@router.post("", status_code=201)
def create_agent(body: dict = Body(...)) -> dict:
    """등록 — 슈퍼 또는 p_klocal 앵커 관리. 새 에이전트는 앵커 grant 캐스케이드로 등록자가 바로 관리할 수 있다.
    앵커 레벨이 캐스케이드하지 않는 manage '예외'에서만 온 구성원은 만든 에이전트를 관리하지 못하므로, 등록 뒤 새 에이전트에
    관리(2)가 없으면 되돌리고(삭제) 403(2026-09-29).
    Register: super or manage on the p_klocal anchor; the anchor grant cascades, so the registrant manages the new agent.
    A member whose anchor level comes only from a non-cascading manage exception could not manage what they created, so the
    registration is rolled back (deleted) with a 403 when the registrant lacks manage(2) on the new agent (2026-09-29)."""
    actor = _actor(body.get("acting_user_id"))
    eff = _eff(actor)
    _require_register(eff)
    try:
        a = ka.create({k: v for k, v in body.items() if k != "acting_user_id"})
    except connectors.ConnectorValidationError as e:
        raise _invalid(e)
    _rebuild()
    if eff is not None and _level(_eff(actor), a["id"]) < 2:   # 새 유니버스로 다시 계산 / recomputed on the new universe
        ka.delete(a["id"])
        _rebuild()
        raise HTTPException(status_code=403, detail=REGISTER_DENIED)
    return {"agent": ka.editor_record(a)}


@router.post("/check")
def check_agent(body: dict = Body(...)) -> dict:
    """연결 테스트 — draft 가 있으면 초안 검사(가린 비밀은 id 의 저장값으로 복원, 저장 안 함), 없으면 저장된 설정 검사 후 결과 저장.
    id 없는 초안 = 등록 권한, id 있음(초안 · 저장 검사) = 그 에이전트의 관리.
    Connection test: a draft is checked without saving (masked secrets restored from id); otherwise the stored config is
    checked and the result saved. A draft without id needs the register gate; anything with id needs manage on that agent."""
    eff = _eff(_actor(body.get("acting_user_id")))
    agent_id = body.get("id")
    if agent_id is not None and not isinstance(agent_id, str):
        raise HTTPException(status_code=422, detail="id 는 문자열이어야 합니다")
    previous = _managed_agent(agent_id, eff) if agent_id else None
    if not agent_id:
        _require_register(eff)
    draft = body.get("draft")
    try:
        if draft is not None:
            if not isinstance(draft, dict):
                raise HTTPException(status_code=422, detail="draft 는 객체여야 합니다")
            return ka.check(draft, previous, agent_id=agent_id or "")
        if not agent_id:
            raise HTTPException(status_code=422, detail="검사할 설정(draft) 또는 에이전트 id 가 필요합니다")
        res = ka.check_saved(agent_id)
    except connectors.ConnectorValidationError as e:
        raise _invalid(e)
    if res is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 에이전트입니다")
    return res


@router.post("/skills")
def upload_skill(file: UploadFile = File(...), acting_user_id: str = Form(""),
                 acting_user_query: str = Query("", alias="acting_user_id")) -> dict:
    """Skill 파일 1개 업로드(주인 없는 상태) — 저장 본문 skill_ids 로 에이전트에 붙는다(/api/mcp/skills 와 같은 규칙).
    관문 = 슈퍼 또는 mgmt.p_klocal. / One pending skill-file upload, attached through skill_ids on save (same rules as
    /api/mcp/skills). Gate: super or mgmt.p_klocal."""
    _require_tab(_eff(_actor(acting_user_query) or _actor(acting_user_id)))
    data = file.file.read(skill_files.MAX_FILE_BYTES + 1)
    try:
        rec = skill_files.add(file.filename or "", data)
    except skill_files.SkillFileError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return skill_files.public(rec)


@router.delete("/skills/{file_id}")
def delete_skill(file_id: str, acting_user_id: str = "") -> dict:
    """주인 없는 파일 = mgmt.p_klocal, 지식 에이전트에 붙은 파일 = 그 에이전트의 관리(work_agents_api 와 같은 규칙).
    Pending files need mgmt.p_klocal; files attached to a knowledge agent need manage on that agent (the work_agents_api rule)."""
    eff = _eff(acting_user_id)
    _require_tab(eff)
    rec = skill_files.get(file_id)
    if rec is None or (rec["owner_kind"] and rec["owner_kind"] != ka.SKILL_OWNER):
        raise HTTPException(status_code=404, detail="존재하지 않는 Skill 파일입니다")
    if rec["owner_kind"]:
        _require_manage(eff, rec["owner_id"])
    if not skill_files.delete(file_id, owner_kind=ka.SKILL_OWNER):
        raise HTTPException(status_code=404, detail="존재하지 않는 Skill 파일입니다")
    return {"ok": True}


# ────────────────────────────────────────────────────────
# 에이전트 1개 / one agent
# ────────────────────────────────────────────────────────

@router.get("/{agent_id}")
def get_agent(agent_id: str, acting_user_id: str = "") -> dict:
    """편집 레코드(비밀 가림) — 그 에이전트의 관리 / the masked editor record; needs manage on that agent"""
    return {"agent": ka.editor_record(_managed_agent(agent_id, _eff(acting_user_id)))}


@router.put("/{agent_id}")
def update_agent(agent_id: str, body: dict = Body(...)) -> dict:
    _managed_agent(agent_id, _eff(_actor(body.get("acting_user_id"))))
    try:
        a = ka.update(agent_id, {k: v for k, v in body.items() if k != "acting_user_id"})
    except connectors.ConnectorValidationError as e:
        raise _invalid(e)
    if a is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 에이전트입니다")
    _rebuild()
    return {"agent": ka.editor_record(a)}


@router.delete("/{agent_id}")
def delete_agent(agent_id: str, acting_user_id: str = "") -> dict:
    _managed_agent(agent_id, _eff(acting_user_id))
    if not ka.delete(agent_id):
        raise HTTPException(status_code=404, detail="존재하지 않는 에이전트입니다")
    _rebuild()
    return {"ok": True}


# ────────────────────────────────────────────────────────
# 문서 프록시 / document proxy
# ────────────────────────────────────────────────────────

@router.get("/{agent_id}/folders")
def folders(agent_id: str, acting_user_id: str = "") -> dict:
    agent = _proxy_agent(agent_id, acting_user_id, 1)
    try:
        return {"folders": ka.list_folders(agent)}
    except ka.AgentCallError as e:
        raise _agent_failed(e)


@router.get("/{agent_id}/documents")
def documents(agent_id: str, folder_id: str = "", acting_user_id: str = "") -> dict:
    """folder_id 없음 = 에이전트 전체 문서, 있으면 그 폴더 직속 문서 / all documents, or one folder's direct documents"""
    agent = _proxy_agent(agent_id, acting_user_id, 1)
    try:
        return {"documents": ka.list_documents(agent, folder_id.strip() or None)}
    except ka.AgentCallError as e:
        raise _agent_failed(e)


@router.post("/{agent_id}/documents")
def upload_document(agent_id: str, file: UploadFile = File(...), folder_id: str = Form(""),
                    acting_user_id: str = Query(""), acting_user_form: str = Form("", alias="acting_user_id")) -> dict:
    """업로드(관리 = 2) — 확장자 pdf · txt · md · hwp · hwpx · docx · xlsx · pptx, 50MB / upload (manage), allowed types, 50MB"""
    agent = _proxy_agent(agent_id, _actor(acting_user_id) or _actor(acting_user_form), 2)
    name = ka.clean_filename(file.filename)
    if not name:
        raise HTTPException(status_code=422, detail="파일 이름이 비어 있습니다")
    if ka.file_ext(name) not in ka.UPLOAD_EXTS:
        raise HTTPException(status_code=422, detail="지원하지 않는 파일 형식입니다. " + ", ".join(ka.UPLOAD_EXTS) + " 만 올릴 수 있습니다")
    data = file.file.read(ka.MAX_UPLOAD_BYTES + 1)
    if len(data) > ka.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=_too_large_detail())
    if not data:
        raise HTTPException(status_code=422, detail="빈 파일은 올릴 수 없습니다")
    try:
        return {"document": ka.upload_document(agent, name, data, (folder_id or "").strip())}
    except ka.AgentCallError as e:
        raise _agent_failed(e, upload=True)


@router.get("/{agent_id}/documents/{doc_id}/status")
def document_status(agent_id: str, doc_id: str, acting_user_id: str = "") -> dict:
    agent = _proxy_agent(agent_id, acting_user_id, 1)
    try:
        return ka.document_status(agent, doc_id)
    except ka.AgentCallError as e:
        raise _agent_failed(e, doc=True)


@router.get("/{agent_id}/documents/{doc_id}/preview")
def document_preview(agent_id: str, doc_id: str, acting_user_id: str = "") -> Response:
    """PDF 는 inline 스트림, 텍스트는 UTF-8 text/plain, 그 밖 형식은 415 / PDF streams inline, text becomes UTF-8, others 415"""
    agent = _proxy_agent(agent_id, acting_user_id, 1)
    try:
        stream = ka.open_document(agent, doc_id, "preview")
    except ka.AgentCallError as e:
        raise _agent_failed(e, doc=True, preview=True)
    if stream.mime == "application/pdf":
        name = stream.filename or f"{doc_id}.pdf"
        # 스트림을 시작하기 전에 연결이 끊겨도 에이전트 응답을 닫는다(닫기는 여러 번 해도 된다)
        # Close the agent response even when the client leaves before streaming starts (closing twice is fine)
        return StreamingResponse(stream.iter_bytes(), media_type="application/pdf",
                                 headers={"Content-Disposition": ka.content_disposition("inline", name), **_NO_SNIFF},
                                 background=BackgroundTask(stream.close))
    if stream.mime in ("text/plain", "text/markdown"):
        try:
            raw = stream.read(ka.MAX_TEXT_PREVIEW_BYTES)
        except ka.AgentCallError as e:
            raise _agent_failed(e)
        return Response(content=ka.decode_text(raw, stream.charset).encode("utf-8"), media_type="text/plain; charset=utf-8",
                        headers=dict(_NO_SNIFF))
    stream.close()
    raise HTTPException(status_code=415, detail="미리보기를 지원하지 않는 형식입니다")


@router.get("/{agent_id}/documents/{doc_id}/download")
def document_download(agent_id: str, doc_id: str, acting_user_id: str = "") -> Response:
    """원본 다운로드 — Content-Disposition: attachment(RFC 5987 filename*) / original bytes as an attachment"""
    agent = _proxy_agent(agent_id, acting_user_id, 1)
    try:
        stream = ka.open_document(agent, doc_id, "download")
    except ka.AgentCallError as e:
        raise _agent_failed(e, doc=True)
    return StreamingResponse(stream.iter_bytes(), media_type=stream.content_type or "application/octet-stream",
                             headers={"Content-Disposition": ka.content_disposition("attachment", stream.filename or doc_id),
                                      **_NO_SNIFF},
                             background=BackgroundTask(stream.close))


@router.delete("/{agent_id}/documents/{doc_id}")
def delete_document(agent_id: str, doc_id: str, acting_user_id: str = "") -> dict:
    agent = _proxy_agent(agent_id, acting_user_id, 2)
    try:
        ka.delete_document(agent, doc_id)
    except ka.AgentCallError as e:
        raise _agent_failed(e, doc=True)
    return {"ok": True}
