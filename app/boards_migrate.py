"""게시판 이전(2026-09-14, 1회) — 리포트 에이전트의 개인 보관소(reports_personal)와 워크스페이스별 리포트 게시판(reports_board)을
게시판 저장소(board_posts)로 옮긴다. board_meta 'legacy_reports_v1' 로 멱등.

규칙(사용자 확정 2026-09-14 "워크스페이스별 리포트 게시판 글은 그룹 게시판으로 옮기고 원래 게시판은 삭제"):
- 개인 보관소 → 'me:<owner>' (id·작성 시각 유지 — /report/<id> 링크 보존).
- 워크스페이스 게시판 글 → 작성자의 권한 그룹 게시판. 그룹이 여럿이면 그 워크스페이스에 접근이 있던 그룹, 그래도 여럿이면 첫 그룹.
  작성자를 찾을 수 없거나 슈퍼 계정이면 전체 게시판. 태그 "구 <워크스페이스명> 게시판"과 source.ws 를 남긴다.
- 원본 테이블은 지우지 않는다(읽지 않을 뿐).
"""
# One-time board migration (2026-09-14) — moves the report agent's personal library (reports_personal) and per-workspace
# report boards (reports_board) into board_posts. Idempotent via board_meta 'legacy_reports_v1'.
# Personal items → 'me:<owner>' (id and timestamp preserved). Workspace posts → the author's group board (prefer a group
# with access under that workspace, else the first); unknown/super authors → the all-hands board. The old tables are kept.

import logging

from app import boards

logger = logging.getLogger("ai365.boards")
FLAG = "legacy_reports_v1"


def _author_name(aid: str) -> str:
    from app.reports_api import _acting_name
    return _acting_name(aid)


def _target(aid: str, ws: str, groups: list[dict]) -> str:
    from app import access
    if not aid.isdigit():
        return "all"
    mine = access.member_groups(int(aid), groups)
    if not mine:
        return "all"
    if len(mine) > 1:
        with_ws = [g for g in mine if any(access.group_map(g).get(n, 0) >= 1 for n in access.descendants(ws))]
        mine = with_ws or mine
    return "g:" + str(mine[0].get("id"))


def migrate_legacy(personal_rows: list[dict] | None = None, board_rows: list[dict] | None = None,
                   dry_run: bool = False) -> dict:
    """이전 실행(또는 dry_run=True 로 계획만) — {done, personal, board:[{id, title, ws, target}]}"""
    # Run the migration (or plan it with dry_run=True).
    if not dry_run and boards.meta_get(FLAG) == "1":
        return {"done": True, "personal": 0, "board": []}
    from app import access, reports
    personal_rows = reports.legacy_personal_rows() if personal_rows is None else personal_rows
    board_rows = reports.legacy_board_rows() if board_rows is None else board_rows
    groups = access.list_groups()
    ws_names = {str(w.get("id")): (w.get("name") or str(w.get("id"))) for w in access.list_workspaces()}
    gnames = {str(g.get("id")): (g.get("name") or str(g.get("id"))) for g in groups}
    n_personal = 0
    for r in personal_rows:
        r = dict(r)
        owner, rid, created = str(r.pop("owner", "") or ""), r.pop("id"), r.pop("created")
        if boards.get_post(rid):
            continue
        post = reports._post_of(owner, r)
        post["author"]["name"] = _author_name(owner)
        if not dry_run:
            boards.add_post(f"me:{owner}", post, post_id=rid, created=created)
        n_personal += 1
    plan = []
    for r in board_rows:
        r = dict(r)
        ws, rid, created = str(r.pop("ws", "") or ""), r.pop("id"), r.pop("created")
        author = r.get("author") if isinstance(r.get("author"), dict) else {}
        aid = str(author.get("id") or "")
        target = _target(aid, ws, groups)
        item = {"id": rid, "title": r.get("title") or "", "ws": ws, "target": target}
        plan.append(item)
        if boards.get_post(rid):
            item["skipped"] = True
            continue
        kind = "dashboard" if r.get("type") == "dashboard" else "report"
        post = {"kind": kind, "title": str(r.get("title") or "")[:120], "summary": str(r.get("insight") or "")[:300],
                "data": r,   # 출처는 source.ws_name 에 남는다(태그 기능 폐지, 2026-09-18) / the origin stays in source.ws_name (tags retired)
                "author": {"id": aid, "name": author.get("name") or _author_name(aid)},
                "group": gnames.get(target[2:], "") if target.startswith("g:") else "",
                "source": {"ws": ws, "ws_name": ws_names.get(ws, ws)}, "status": "published"}
        if not dry_run:
            boards.add_post(target, post, post_id=rid, created=created)
    if not dry_run:
        boards.meta_set(FLAG, "1")
        if n_personal or plan:
            logger.info("게시판 이전 완료: 개인 %d건, 워크스페이스 게시글 %d건", n_personal, len(plan))
    return {"done": not dry_run, "personal": n_personal, "board": plan}
