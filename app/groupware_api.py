"""그룹웨어 에이전트 API — 위젯 설정 GET/PUT + 위젯 정보 조회.

/query는 클라이언트가 스마트 파일로 그룹웨어를 켠 채팅에서만 부른다(명시적 라우팅).
파이프라인을 경유하지 않고, 무매칭이면 kind='pass'로 되돌려 기존 파이프라인이 처리하게 한다.
"""
# Groupware agent API — widget settings GET/PUT + widget info queries.
#
# /query is only called by the client for chats where groupware was switched on via smart files
# (explicit routing). It bypasses the pipeline; unmatched queries return kind='pass' so the
# normal pipeline handles them.

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import access, catalog, groupware
from app.groupware import DEFAULTS, WIDGET_KEYS, WIDGET_LABELS

logger = logging.getLogger("ai365.groupware")

router = APIRouter(prefix="/api/groupware", tags=["groupware"])


def _eff(acting_user_id: str) -> dict | None:
    """resources_api와 동일 규약: ''/비숫자=슈퍼(None, 게이팅 없음), 숫자=서버가 유효 권한 재계산.
    조회 실패는 전부 차단으로(권한 상승 없음)."""
    # Same contract as resources_api: ''/non-digit = super (None, no gating); digits = effective
    # permissions recomputed server-side. Lookup failure blocks everything (no escalation).
    aid = (acting_user_id or "").strip()
    if not aid or not aid.isdigit():
        return None
    try:
        return access.effective(int(aid))
    except Exception:
        logger.warning("effective 조회 실패(no=%s) — 전부 차단으로 처리", aid, exc_info=True)
        return {"no": None, "menus": {}, "nodes": {}, "mgmt": {},
                "read": {"p_know": False, "p_data": False, "p_auto": False}}


class WidgetsIn(BaseModel):
    widgets: dict
    acting_user_id: str = ""


class QueryIn(BaseModel):
    text: str
    acting_user_id: str = ""


def _normalize(widgets: dict) -> dict:
    """정확히 9키만 허용 — 키 집합 불일치는 이름을 지목해 422 (smart_actions와 동일 정책)."""
    # Exactly the nine keys — mismatches 422 with the offending names (same policy as smart_actions).
    if not isinstance(widgets, dict):
        raise HTTPException(status_code=422, detail="widgets는 객체여야 합니다")
    missing = [k for k in WIDGET_KEYS if k not in widgets]
    extra = [k for k in widgets if k not in WIDGET_KEYS]
    if missing or extra:
        parts = []
        if missing:
            parts.append("누락: " + ", ".join(missing))
        if extra:
            parts.append("허용되지 않음: " + ", ".join(extra))
        raise HTTPException(status_code=422, detail="위젯 키가 올바르지 않습니다 — " + " / ".join(parts))
    # 비-dict 값은 강제 True로 뭉개지 않고 키를 지목해 422 — "끄려던 값이 조용히 켜지는" 결함 방지
    # (smart_actions_api가 명시적으로 고쳐 둔 결함 계열의 재도입을 막는다 — 적대적 리뷰 반영)
    # Non-dict values 422 with the offending keys instead of being coerced to True — prevents
    # "meant to turn it off, silently turned on" (the defect class smart_actions_api explicitly fixed).
    bad = [k for k in WIDGET_KEYS if not isinstance(widgets[k], dict)]
    if bad:
        raise HTTPException(status_code=422, detail="위젯 값이 객체가 아닙니다: " + ", ".join(bad))
    return {k: {"enabled": widgets[k].get("enabled") is not False} for k in WIDGET_KEYS}


@router.get("/widgets")
def get_widgets() -> dict:
    return {
        "widgets": groupware.get_widgets(),
        "order": WIDGET_KEYS,
        "labels": WIDGET_LABELS,
        "defaults": DEFAULTS,
    }


@router.put("/widgets")
def put_widgets(body: WidgetsIn) -> dict:
    # 설정 변경 = 업무 자동화 **관리** 권한(또는 슈퍼) — 클라 화면 게이팅과 별개로 서버가 강제한다
    # Changing settings = 업무 자동화 *manage* permission (or super) — enforced server-side,
    # independent of any client-side screen gating
    eff = _eff(body.acting_user_id)
    if eff is not None and not (eff.get("mgmt") or {}).get("p_auto"):
        raise HTTPException(status_code=403, detail="업무 자동화 관리 권한이 필요합니다")
    saved = groupware.put_widgets(_normalize(body.widgets))
    return {"ok": True, "widgets": saved}


@router.post("/query")
def query(body: QueryIn) -> dict:
    text = (body.text or "").strip()
    if not text:
        return {"kind": "pass"}
    # 조회 = 업무 자동화 **열람** 권한 — 스마트 파일 모달의 클라 게이팅(p_auto)과 같은 축을
    # 서버가 재검증한다(스위처 전환 직후 등 클라 상태가 낡아도 새지 않게).
    # Query = 업무 자동화 *read* permission — the server re-verifies the same axis the smart-file
    # modal gates client-side (p_auto), so stale client state (e.g. right after a user switch) never leaks.
    eff = _eff(body.acting_user_id)
    if not catalog.domain_readable(eff, "p_auto"):
        return {"kind": "denied", "label": "그룹웨어 에이전트",
                "text": "그룹웨어 에이전트를 사용할 권한이 없습니다 — 업무 자동화 열람 권한이 필요합니다."}
    return groupware.query(text)
