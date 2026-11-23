"""리포트 에이전트 영속화 — SQLite.

개인 보관소(reports_personal, 뷰애즈 사용자별)와 워크스페이스 게시판(reports_board)을 저장했다 — 2026-09-14 게시판 축 도입 후
두 테이블은 이전 원본으로만 남고, 개인 보관소 함수는 게시판 저장소(boards, 'me:<owner>')에 위임한다.
리포트는 저장 시점 스냅샷(차트 스펙 + 데이터 + 인사이트)으로 고정된다 — 열람 시 재실행 없음.
"""
# Report-agent persistence — SQLite.
# Stores the personal library (reports_personal, per view-as user) and workspace boards (reports_board).
# A report is frozen as a snapshot at save time (chart spec + data + insight) — never re-executed on view.

import json
import sqlite3
import uuid
from pathlib import Path

from app import kst

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "ai365.db"


def _now() -> str:
    return kst.now_iso()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_reports() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS reports_personal(
              id TEXT PRIMARY KEY,
              owner TEXT NOT NULL,          -- 뷰애즈 신원(acting_user_id: ''=슈퍼, 그 외 구성원 no 문자열)
              created TEXT NOT NULL,
              data TEXT NOT NULL            -- 리포트 스냅샷 JSON
            );
            CREATE TABLE IF NOT EXISTS reports_board(
              id TEXT PRIMARY KEY,
              ws TEXT NOT NULL,             -- 워크스페이스 id (게시판 노드 bd_{ws}의 anchor)
              created TEXT NOT NULL,
              data TEXT NOT NULL            -- 게시물 JSON (author 포함)
            );
            """
        )


def _row_to_report(r: sqlite3.Row) -> dict:
    d = json.loads(r["data"])
    d["id"] = r["id"]
    d["created"] = r["created"]
    return d


# ── 개인 보관소 = 게시판 '내 보관함'(2026-09-14) — reports_personal·reports_board 는 이전 원본으로만 남고 저장·조회는 boards 가 맡는다.
#    워크스페이스별 게시판(list_board·add_board)은 폐지(boards_migrate 가 그룹·전체 게시판으로 옮겼다). ──
# ── The personal library is now the board's 내 보관함 (2026-09-14) — reports_personal/reports_board remain only as the migration
#    source; storage and reads go through boards. The per-workspace board functions are retired (boards_migrate moved the posts). ──

def _legacy_shape(p: dict) -> dict:
    """게시글 → 리포트 에이전트가 기대하는 항목 모양({...report, id, created}) / board post → the report agent's item shape"""
    data = p.get("data") if isinstance(p.get("data"), dict) else {}
    out = dict(data)
    out["title"] = p.get("title") or data.get("title") or ""
    out["id"] = p["id"]
    out["created"] = p["created"]
    return out


def _post_of(owner: str, report: dict) -> dict:
    """리포트 스냅샷 → 게시글 본문(종류는 type 으로) / report snapshot → post body (kind from type)"""
    kind = "dashboard" if report.get("type") == "dashboard" else "report"
    # 요약: 리포트는 인사이트, 대시보드는 타일 인사이트를 이어 붙인다 / summary: the insight, or the tile insights joined
    summary = str(report.get("insight") or "") or " ".join(
        str(it.get("insight") or "") for it in (report.get("items") or []) if isinstance(it, dict)).strip()
    return {"kind": kind, "title": str(report.get("title") or "")[:120],
            "summary": summary[:300], "data": report,
            "author": {"id": owner, "name": ""},
            "source": report.get("source") if isinstance(report.get("source"), dict) else {}}


def list_personal(owner: str) -> list[dict]:
    from app import boards
    return [_legacy_shape(p) for p in boards.list_posts(f"me:{owner}", kinds=("report", "dashboard"))]


def add_personal(owner: str, report: dict) -> dict:
    from app import boards
    body = {k: v for k, v in report.items() if k not in ("id", "created")}
    return _legacy_shape(boards.add_post(f"me:{owner}", _post_of(owner, body)))


def delete_personal(owner: str, rid: str) -> bool:
    """개인 보관함 항목 삭제(본인 소유만) — 개인 공간이라 실삭제 / delete an own library item (real deletion)"""
    from app import boards
    p = boards.get_post(rid)
    if p is None or p.get("board") != f"me:{owner}":
        return False
    from app import report_dash
    report_dash.delete_by_post(rid)   # 그 글을 물고 있던 대시보드 세션(대화)도 함께 / the dashboard session (conversation) bound to it goes too
    return boards.delete_post(rid)


def update_personal(owner: str, rid: str, report: dict) -> dict | None:
    """개인 보관함 항목 데이터 전체 교체(본인 소유만) — created 유지. 대시보드 편집(담기·이름·타일)이 사용."""
    # Replace an own library item's data — created is preserved. Used by dashboard edits (append/rename/tiles).
    from app import boards
    p = boards.get_post(rid)
    if p is None or p.get("board") != f"me:{owner}":
        return None
    body = {k: v for k, v in report.items() if k not in ("id", "created")}
    np = _post_of(owner, body)
    return _legacy_shape(boards.update_post(rid, {"kind": np["kind"], "title": np["title"], "summary": np["summary"], "data": body}))


def get_personal(owner: str, rid: str) -> dict | None:
    from app import boards
    p = boards.get_post(rid)
    if p is None or p.get("board") != f"me:{owner}":
        return None
    return _legacy_shape(p)


# ── 이전 원본 읽기(boards_migrate 1회 이전용) / legacy readers (one-time migration by boards_migrate) ──

def legacy_personal_rows() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT id, owner, created, data FROM reports_personal ORDER BY created ASC").fetchall()
    return [{**_row_to_report(r), "owner": r["owner"]} for r in rows]


def legacy_board_rows() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT id, ws, created, data FROM reports_board ORDER BY created ASC").fetchall()
    return [{**_row_to_report(r), "ws": r["ws"]} for r in rows]
