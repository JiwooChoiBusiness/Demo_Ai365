"""실행 확인 액션 API — 확인 카드의 [실행]/[취소] 버튼이 호출한다.

업무 자동화 실행(이메일 자동분류·요약·업무 추출 등)은 이 모듈의 confirm 엔드포인트를 통해서만
일어난다(자동 실행 금지). 실제 수행은 work.execute_action(kind, payload)에 위임한다.
"""
# Execution-confirmation action API — invoked by the [Run]/[Cancel] buttons on the confirmation card.
# Work-automation execution (mail auto-classify/summarize/task-extract, ...) happens only through this
# module's confirm endpoint (no automatic execution); the work is delegated to work.execute_action.

import logging
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import db
from app.agents import groupware as groupware_agent
from app.agents import work

# 액션 kind의 네임스페이스 head로 실행기 라우팅: M365(mail/calendar/teams/todo/sharepoint)=그룹웨어,
# 그 외(email/edu)=업무 자동화(work). 두 도메인이 중간 `.action.` 세그먼트를 공유하므로 ns head로 가른다.
# Route the executor by the kind's namespace head: M365 (mail/calendar/teams/todo/sharepoint) → groupware,
# else (email/edu) → work. Both share the middle `.action.` segment, so split on the namespace head.
_GW_NS = ("mail.", "calendar.", "todo.", "sharepoint.", "groupware.")

logger = logging.getLogger("ai365.actions")

router = APIRouter(prefix="/api/actions")


def _load_pending(action_id: str) -> dict:
    action = db.get_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 작업입니다")
    if action["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"이미 처리된 작업입니다(status={action['status']})")
    return action


@router.get("/{action_id}")
def get_action(action_id: str) -> dict:
    """액션 상태 조회 — 새로고침 후 confirm 카드 복원용(pending이면 버튼 재무장, 처리됐으면 라벨)."""
    # Action status lookup — for restoring the confirm card after a refresh (re-arm buttons when pending,
    # show the outcome label otherwise).
    action = db.get_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 작업입니다")
    from app.execution_store import effect_get
    effect = effect_get("action:" + action_id)
    if action["status"] == "pending" and effect:
        action["status"] = "running"
    return {"id": action["id"], "status": action["status"],
            "kind": action["kind"], "summary": action.get("summary") or ""}


class ConfirmIn(BaseModel):
    """confirm 카드에서 수정한 파라미터 — 메일 단건(to/subject/body)만 반영(2026-08-28 파라미터 폼)."""
    # Parameters edited on the confirm card — applied to single mail sends (to/subject/body) only.
    overrides: dict = {}


# 수정 허용 필드(메일 단건) — 그 외 kind/필드는 무시(방어적)
# Editable fields (single mail send) — other kinds/fields are ignored (defensive)
_OVERRIDABLE = {"mail.action.compose": ("to", "subject", "body")}


@router.post("/{action_id}/confirm")
async def confirm_action(action_id: str, body: ConfirmIn | None = None) -> dict:
    action = _load_pending(action_id)
    from app import runs, execution_store
    link = execution_store.action_link(action_id)
    if link and runs.is_running(action["chat_id"]):
        raise HTTPException(status_code=409, detail="현재 응답이 마무리된 뒤 실행해 주세요")
    if link:
        from app.pipeline import _resolve_eff
        saved = execution_store.get(link["run_id"])
        if saved is None or saved["state"] != "needs_confirmation":
            raise HTTPException(status_code=409, detail="이 계획은 더 이상 확인 대기 중이 아닙니다")
        if saved["snapshot"].get("eff") != await asyncio.to_thread(_resolve_eff, saved["snapshot"].get("actor", "")):
            raise HTTPException(status_code=403, detail="실행 계획의 권한이 변경됐습니다")
    claimed, _ = execution_store.effect_claim("action:" + action_id)
    if not claimed:
        raise HTTPException(status_code=409, detail="이미 처리 중이거나 처리된 작업입니다")
    # 카드에서 수정한 파라미터 반영 — 문자열 필드만, 허용 목록 한정(수정본은 DB에도 기록해 기록 정합 유지)
    # Apply card-edited parameters — string fields only, allowlisted (persisted so the record stays truthful)
    ov = (body.overrides if body else {}) or {}
    allowed = _OVERRIDABLE.get(str(action["kind"]), ())
    changed = {k: v.strip() for k, v in ov.items()
               if k in allowed and isinstance(v, str) and v.strip()}
    if changed:
        action["payload"] = {**action["payload"], **changed}
        db.update_action_payload(action_id, action["payload"])
    try:
        executor = groupware_agent if str(action["kind"]).startswith(_GW_NS) else work
        result_text = await asyncio.to_thread(executor.execute_action, action["kind"], action["payload"])
        db.set_action_status(action_id, "executed")
        ok = True
    except Exception as e:
        logger.exception("액션 실행 실패: %s", action_id)
        db.set_action_status(action_id, "failed")
        result_text = f"실행에 실패했습니다: {e}\n잠시 후 다시 요청해 주세요."
        ok = False
    message_id = _save_result(action, result_text, "action_result")
    execution_store.effect_finish("action:" + action_id, {"ok": ok, "text": result_text})
    return {"ok": ok, "text": result_text, "message_id": message_id, **await _resume(action_id, ok, result_text)}


async def _resume(action_id, ok, text, cancelled=False):
    from app import conversation_execution, background_execution
    run = conversation_execution.action_finished(action_id, ok, text, cancelled)
    if not run:
        from app import execution_store, schedules
        from app.execution_outcomes import chat_state
        link = execution_store.action_link(action_id)
        saved = execution_store.get(link["run_id"]) if link else None
        if saved and saved["state"] in ("completed", "failed", "cancelled"):
            db.set_run_state(saved["chat_id"], chat_state(saved["state"]), unseen=1)
            await schedules.complete_resumed(saved["chat_id"], saved["state"],
                                             bool(saved["snapshot"].get("artifact")), saved["id"])
        return {}
    from app import runs, execution_store
    if runs.is_running(run["chat_id"]):
        execution_store.save(run, "interrupted")
        return {"resume_pending": True, "resume_id": run["id"]}
    background_execution.start(run["chat_id"], conversation_execution.resume_events(run))
    return {"resume_chat_id": run["chat_id"], "resume_id": run["id"]}


def _save_result(action: dict, text: str, kind: str) -> str | None:
    """결과를 채팅에 어시스턴트 메시지로 저장(채팅이 삭제됐으면 건너뜀)."""
    # Save the result to the chat as an assistant message (skip if the chat has been deleted).
    try:
        return db.add_message(
            action["chat_id"], "assistant", text,
            meta={"source": "사내", "kind": kind, "action_id": action["id"]},
        )
    except Exception:
        logger.warning("결과 메시지 저장 실패(채팅 삭제됨?) — chat_id=%s", action["chat_id"])
        return None


@router.post("/{action_id}/cancel")
async def cancel_action(action_id: str) -> dict:
    action = _load_pending(action_id)
    from app import execution_store, runs
    if execution_store.action_link(action_id) and runs.is_running(action["chat_id"]):
        raise HTTPException(status_code=409, detail="현재 응답이 마무리된 뒤 취소해 주세요")
    claimed, _ = execution_store.effect_claim("action:" + action_id)
    if not claimed:
        raise HTTPException(status_code=409, detail="이미 처리 중이거나 처리된 작업입니다")
    db.set_action_status(action_id, "cancelled")
    text = "요청하신 작업 실행을 취소했습니다. 실행된 것은 없습니다."
    message_id = _save_result(action, text, "action_cancelled")
    execution_store.effect_finish("action:" + action_id, {"ok": False, "cancelled": True})
    return {"ok": True, "text": text, "message_id": message_id, **await _resume(action_id, False, text, True)}
