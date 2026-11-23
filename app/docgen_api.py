"""문서 생성 API — 실행(SSE)·조회·실 파일 다운로드.

POST /run 은 /api/chats/{id}/stream 과 같은 이벤트 어휘의 SSE(+ 신규 doc_meta/doc_page)를 낸다
(/api/flows/run 선례). GET /{doc_id}는 패널 재열기/복원용, GET /{doc_id}/file 은 lazy 빌드 후
FileResponse(한글 파일명은 starlette가 filename*=utf-8''로 처리).
"""
# Docgen API — run (SSE), read, and real-file download.
# POST /run emits the same SSE vocabulary as /api/chats/{id}/stream plus doc_meta/doc_page
# (the /api/flows/run precedent). GET /{doc_id} feeds panel-reopen/restore; GET /{doc_id}/file
# builds lazily and returns a FileResponse (starlette encodes Korean names as filename*=utf-8'').

import logging
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app import db, docgen

logger = logging.getLogger("ai365.docgen")

router = APIRouter(prefix="/api/docgen")

_DOC_ID_RE = re.compile(r"^doc_[0-9a-f]{12}$")


class RunIn(BaseModel):
    chat_id: str
    message: str
    format: str
    topic: str
    style: str = "dark"
    length: int = 8
    # 자료 출처(STEP 1.5, 카드에서 확정): general=일반 지식 / internal=사내 지식·데이터 조회 / context=대화 내용
    # Material source (decided on the card): general knowledge / internal agent lookup / conversation context
    source: str = "general"
    # 뷰애즈 신원 — 사내 조회 시 권한 게이팅(stream/flows와 동일 계약, 빈 값=슈퍼)
    # View-as identity — permission gating for internal lookups (same contract as stream/flows)
    acting_user_id: str = ""
    # 작성 지침(선택, 2026-08-29) — 파일 생성 시에만 적용되는 최우선 스타일·형식 지침
    # (워크플로우 파일 생성 결정 체인이 채워 보낸다; 채팅 질문 카드 경로는 빈 값).
    # Optional instruction (2026-08-29) — top-priority style/format hints applied only at
    # file-generation time (filled by the workflow file-output chain; the chat card path sends '').
    instruction: str = ""
    # 사용자 메시지 저장 여부 — 워크플로우 체인은 False(질문은 flows가 이미 저장, 중복 말풍선 방지)
    # Whether to save the user message — the workflow chain sends False (flows already saved it)
    save_user: bool = True
    resume_id: str = ""
    # 문서 템플릿(게시판 2026-09-14) — 지정하면 format·topic·style·length·source·instruction 은 템플릿이 정한다
    # (권한·필수 입력 검사는 boards_api.prepare_template_run). template_inputs = 템플릿 입력 항목 값.
    # Document template (boards, 2026-09-14) — when set, the template decides format/topic/style/length/source/
    # instruction (access + required-input checks in boards_api.prepare_template_run); template_inputs = its input values.
    template_id: str = ""
    template_inputs: dict = {}
    template_version: int = 0
    template_question_id: str = ""


@router.post("/run")
async def run(body: RunIn) -> EventSourceResponse:
    if body.template_question_id and not body.template_id:
        raise HTTPException(status_code=422, detail="템플릿 질문에는 template_id가 필요합니다")
    chat = db.get_chat(body.chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 채팅입니다")
    cfg = body.model_dump()
    if body.template_id:
        # 템플릿 실행(게시판 2026-09-14): 템플릿이 실행 설정을 정한다 — 권한·필수 입력은 여기서 404/403/422
        # Template run (boards, 2026-09-14): the template decides the run config; access/required inputs raise 404/403/422 here
        from app import boards_api
        if body.template_question_id:
            checked = boards_api.prepare_template_chat(body.template_id, boards_api.TemplateChatIn(
                acting_user_id=body.acting_user_id, chat_id=body.chat_id, message=body.message,
                version=body.template_version, inputs=body.template_inputs, question_id=body.template_question_id))
            if checked.get("missing"):
                raise HTTPException(status_code=422, detail="필수 입력을 채워 주세요")
            body.message = checked["message"]
            cfg["message"] = body.message
            cfg["save_user"] = False
        prep = boards_api.prepare_template_run(body.template_id, body.acting_user_id, body.template_inputs, body.template_version)
        cfg.update(prep["docgen"])
        cfg["template"] = prep["template"]
        # 이번 작성 요청은 지침이 아니라 재료로 전달(지침 상한에 잘리지 않게, 2026-09-15 점검) / the request rides the material, not the capped hints
        cfg["template"]["request"] = body.message[:6000]
        # 요청이 사내 자료를 새로 조회하라고 말하면 템플릿 설정과 상관없이 조회한다(2026-09-21 자료 출처 개편, 권한 게이팅은 그대로)
        # A request that asks for a fresh internal lookup gets one whatever the template says (permission gating unchanged)
        cfg["template"]["lookup"] = boards_api.wants_lookup(body.message)
    fmt, topic, length, source = cfg["format"], str(cfg.get("topic") or "").strip(), int(cfg["length"]), cfg["source"]
    if fmt not in docgen.FORMATS:
        raise HTTPException(status_code=422, detail="지원하지 않는 형식입니다")
    if not topic:
        raise HTTPException(status_code=422, detail="topic이 비어 있습니다")
    # image는 1장 고정(포스터) / image is fixed at a single poster page
    lo, hi = (5, 100) if fmt == "xlsx" else ((1, 1) if fmt == "image" else (2, 15))
    if not (lo <= length <= hi):
        raise HTTPException(status_code=422, detail="length가 허용 범위를 벗어났습니다")
    if source not in docgen.SOURCES:
        raise HTTPException(status_code=422, detail="지원하지 않는 자료 출처입니다")

    from app import artifact_execution, background_execution, conversation_execution, execution_store, runs
    if runs.is_running(chat["id"]):
        raise HTTPException(status_code=409, detail="이미 실행 중인 작업이 있습니다")
    if body.resume_id:
        saved = execution_store.get(body.resume_id)
        if not saved or saved["chat_id"] != chat["id"] or saved["state"] != "needs_input" \
                or saved["snapshot"].get("actor") != body.acting_user_id:
            raise HTTPException(status_code=409, detail="현재 파일 설정 대기 중인 실행이 아닙니다")
        decision = saved["snapshot"].get("decision") or {}
        if (decision.get("document") or {}).get("format") != fmt:
            raise HTTPException(status_code=422, detail="계획의 파일 형식과 일치하지 않습니다")
        from app.pipeline import _resolve_eff
        eff = _resolve_eff(body.acting_user_id)
        if eff != saved["snapshot"]["eff"]:
            raise HTTPException(status_code=403, detail="권한이 변경됐습니다")
        saved["snapshot"]["doc_cfg"] = cfg
        conversation_execution.resolve_cards(saved)
        execution_store.save(saved, "ready")
        producer = conversation_execution.resume_events(saved)
    else:
        producer = artifact_execution.document_run(chat, cfg)
    # 질문 카드의 답변 완료 표시는 파일이 실제로 만들어진 뒤(artifact_execution) — 실패하면 카드에서 다시 제출할 수 있다(2026-09-15 점검)
    # The question card is marked answered only once the file exists (artifact_execution); a failed run stays answerable
    return background_execution.response(chat["id"], producer)


@router.get("/{doc_id}")
def get_doc(doc_id: str) -> dict:
    if not _DOC_ID_RE.fullmatch(doc_id):
        raise HTTPException(status_code=404, detail="존재하지 않는 문서입니다")
    doc = docgen.get_doc(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 문서입니다")
    return {"doc": doc, "pages": docgen.list_pages(doc_id)}


@router.get("/{doc_id}/file")
def get_file(doc_id: str) -> FileResponse:
    if not _DOC_ID_RE.fullmatch(doc_id):
        raise HTTPException(status_code=404, detail="존재하지 않는 문서입니다")
    doc = docgen.get_doc(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 문서입니다")
    if doc["status"] not in ("done", "partial"):
        raise HTTPException(status_code=409, detail="생성이 완료되지 않았습니다")
    try:
        path = docgen.build_file(doc_id)
    except Exception as e:  # noqa: BLE001 — 빌더 실패는 상세와 함께 500 / builder failures 500 with detail
        logger.exception("docgen 파일 빌드 실패: %s", doc_id)
        raise HTTPException(status_code=500, detail=f"파일 생성에 실패했습니다: {e}") from e
    return FileResponse(path, media_type=docgen.MIME[doc["format"]], filename=doc["filename"])
