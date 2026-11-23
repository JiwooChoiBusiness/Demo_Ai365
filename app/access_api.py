"""접근 통제(관리 센터) API — 조직도 구성원·권한 그룹·워크스페이스 영속화 + 실효 권한.

프론트(관리/리소스 센터)는 부팅 시 GET /api/access/bootstrap 으로 하이드레이션하고,
생성/수정/삭제 시 아래 엔드포인트로 동기화한다. 데모는 localhost 단일 사용자 기준.
"""
# Access control (Admin Center) API — persistence of org-chart members / permission groups / workspaces + effective permissions.
# The frontend (Admin/Resource Center) hydrates on boot via GET /api/access/bootstrap,
# and syncs via the endpoints below on create/update/delete. The demo assumes a single localhost user.

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import access

logger = logging.getLogger("ai365.access")

router = APIRouter(prefix="/api/access")


class GroupsIn(BaseModel):
    groups: list[dict]


class WorkspacesIn(BaseModel):
    workspaces: list[dict]
    acting_user_id: str = ""  # 뷰애즈 신원 — 빈 값=슈퍼관리자 / view-as identity; '' = super admin


@router.get("/bootstrap")
def get_bootstrap() -> dict:
    """구성원·팀·조직도 트리·권한 그룹·워크스페이스를 한 번에 반환(하이드레이션용)."""
    # Returns members, teams, org-chart tree, permission groups, and workspaces all at once (for hydration).
    return access.bootstrap()


@router.post("/members")
def add_member(member: dict) -> dict:
    if not (member.get("name") and member.get("dept")):
        raise HTTPException(status_code=422, detail="name·dept는 필수입니다")
    no = member.get("no")
    if no is not None:
        # no는 정수만 허용(테이블 PK가 INTEGER) — 잘못된 값은 500이 아니라 422로
        # no allows integers only (the table PK is INTEGER) — an invalid value returns 422, not 500
        if isinstance(no, bool) or (isinstance(no, float) and not no.is_integer()):
            raise HTTPException(status_code=422, detail="no는 정수여야 합니다")
        try:
            member["no"] = int(no)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="no는 정수여야 합니다")
    saved = access.upsert_member(member)
    return {"ok": True, "member": saved}


@router.patch("/members/{member_no}")
def patch_member(member_no: int, fields: dict) -> dict:
    """구성원 부분 수정 — 부서 변경이 팀 파생 그룹 멤버십(effective)에 즉시 반영된다."""
    # Partial member update — dept changes reflect immediately in team-derived group membership (effective).
    saved = access.update_member(member_no, fields or {})
    if saved is None:
        raise HTTPException(status_code=404, detail="구성원이 없습니다")
    return {"ok": True, "member": saved}


@router.put("/groups")
def put_groups(body: GroupsIn) -> dict:
    access.replace_groups(body.groups)
    return {"ok": True, "count": len(body.groups)}


@router.put("/workspaces")
def put_workspaces(body: WorkspacesIn) -> dict:
    """워크스페이스 전체 교체 — P3부터 슈퍼 전용(슬롯 단위 강제를 우회하지 못하게).

    부서 관리자의 슬롯 편집은 /api/resources/workspaces/{wid}/slots 를 사용한다."""
    # Replace all workspaces — super-only since P3 (so slot-level enforcement can't be bypassed).
    # Department managers edit slots via /api/resources/workspaces/{wid}/slots.
    from app.resources_api import _eff, _require_super  # 지연 임포트(순환 회피) / lazy import to avoid cycles
    _require_super(_eff(body.acting_user_id))
    access.replace_workspaces(body.workspaces)
    return {"ok": True, "count": len(body.workspaces)}


@router.get("/effective/{member_no}")
def get_effective(member_no: int) -> dict:
    """한 사용자의 서버 계산 실효 권한(권위 엔진 — 챗봇 게이팅·미리보기가 같은 결과를 소비)."""
    # Server-computed effective permissions for a single user (the authoritative engine — chatbot gating and the preview consume the same result).
    return access.effective(member_no)


@router.get("/preview")
def get_preview() -> dict:
    """실효 권한 미리보기 데이터 — 실제 권한 유니버스(PV_TREE) + 권한 보유자 실효 권한 + 팀 단위 권한.

    프론트 '실효 권한 미리보기' 페이지가 렌더 전용으로 소비한다. 계산은 effective_full
    (= effective 와 동일 엔진)이므로 미리보기 결과가 곧 실제 인가 결과다.
    people 은 권한이 있는(≥1 그룹 매칭) 구성원만 — 무권한자는 검색 대상에서 제외(사용자 확정).
    teams 는 '부서 전체'로 등록된 팀별 합집합 권한(effective_for_team) — 팀 검색이 소비한다."""
    # Effective-permission preview payload — the real permission universe (PV_TREE), effective permissions
    # for permission holders, and team-unit permissions. The frontend preview page is render-only; the
    # computation is effective_full (the same engine as effective), so what the preview shows IS the
    # enforced result. `people` includes only members matched by ≥1 group (user decision: members without
    # any permission are not searchable). `teams` carries the per-team union (effective_for_team) for
    # groups that registered the team as '부서 전체' — consumed by the team search.
    members = access.list_members()
    groups = access.list_groups()
    people = [{
        "no": m["no"], "name": m.get("name", ""), "dept": m.get("dept", ""),
        # 멤버십 = 개인 ∪ 부서 전체(teams) — access.is_member 단일 술어(effective_full 과 동일 규칙)
        # Membership = individual ∪ whole-team — the single access.is_member predicate (same rule as effective_full)
        "groups": [g.get("name") or g.get("id") or ""
                   for g in groups if access.is_member(g, m["no"], m.get("dept"))],
    } for m in members]
    people = [p for p in people if p["groups"]]
    team_names = sorted({t for g in groups for t in (g.get("teams") or [])})
    teams = [{
        "team": t,
        "cnt": sum(1 for m in members if m.get("dept") == t),
        "groups": [g.get("name") or g.get("id") or "" for g in groups if t in (g.get("teams") or [])],
        "eff": access.effective_for_team(t, groups),
    } for t in team_names]
    return {
        "tree": access.PV_TREE,
        "people": people,
        "teams": teams,
        "eff": {str(p["no"]): access.effective_full(p["no"], groups) for p in people},
    }
