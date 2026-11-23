"""게시판 영속화(2026-09-14) — 전체·그룹·개인 보관함 게시글, 문서 템플릿, 템플릿 사용 기록(SQLite, db._conn 공용).

게시판 id: 'all'(전체 게시판) | 'g:<og_id>'(권한 그룹 게시판) | 'me:<owner>'(개인 보관함, owner = 뷰애즈 신원, ''=슈퍼).
게시글: {id, board, kind, status, pinned, views, title, summary, data, author{id,name}, group, source, thumb, created, updated}
  kind = report(차트 리포트) | dashboard(차트 합본)
  status = published
  data = 종류별 스냅샷(리포트: chart·insight·table·source / 대시보드: items)
게시글은 저장 시점 스냅샷으로 고정된다(리포트 에이전트 규약 유지). 권한·검증은 boards_api 가 담당하고 여기는 저장만 한다.

2026-09-18 정리(사용자 결정): 게시판에는 리포트·대시보드만 올린다 — 채팅 답변·생성 파일·템플릿 결과 파일 종류를 없앴고,
게시판별 설정(게시 정책·게시 전 검토·보관 기간·알림 끄기·고정 최대·허용 종류)과 통계도 없앴다. 새 글 알림은 항상 켜져 있고
고정 글은 게시판마다 PIN_MAX 개까지다. 옛 DB 의 board_settings 테이블과 board_template_uses.posted 열은 쓰지 않고 그대로 둔다.
태그 기능도 없앴다(같은 날 사용자 지시) — 옛 글 JSON 에 남은 tags 값은 일부러 지우지는 않지만(그 글을 고치면 빠진다) 응답에서 빼고, 검색·필터에도 쓰지 않는다.
"""
# Board persistence (2026-09-14) — posts for the all/group/personal boards, document templates and template-usage records
# (SQLite via the shared db._conn).
# board id: 'all' | 'g:<og_id>' (permission-group board) | 'me:<owner>' (personal library; owner = view-as identity, '' = super).
# Posts are frozen snapshots at save time (same rule as the report agent). Permissions/validation live in boards_api;
# this module only stores.
# 2026-09-18 cleanup (user decision): only reports and dashboards are posted — the answer, file and template-document kinds
# are gone, and so are the per-board settings (posting policy, review, retention, notification switch, pin cap, allowed
# kinds) and the stats. New-post notifications are always on and each board pins up to PIN_MAX posts. The board_settings
# table and the board_template_uses.posted column of older databases are left in place, unused. Tags are gone too (same day,
# user request): tags left in the JSON of older posts are not purged (they drop out when that post is edited), are stripped
# from responses and are never searched.

import json
import uuid
from datetime import timedelta

from app import db, kst

KINDS = ("report", "dashboard")
STATUSES = ("published",)
PIN_MAX = 3                                  # 게시판별 고정 글 최대 수 / max pinned posts per board
TEMPLATE_FORMATS = ("docx", "pptx", "xlsx", "pdf")
TEMPLATE_MODES = ("outline", "fill")
MAX_POSTS_LIST = 300


def _now() -> str:
    return kst.now_iso()


def init_boards() -> None:
    with db._conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS board_posts(
              id TEXT PRIMARY KEY,
              board TEXT NOT NULL,            -- 'all' | 'g:<og>' | 'me:<owner>'
              kind TEXT NOT NULL,
              status TEXT NOT NULL,
              pinned INTEGER NOT NULL DEFAULT 0,
              views INTEGER NOT NULL DEFAULT 0,
              author_id TEXT NOT NULL DEFAULT '',
              created TEXT NOT NULL,
              updated TEXT NOT NULL,
              data TEXT NOT NULL              -- 제목·요약·스냅샷·출처 JSON / title, summary, snapshot, source
            );
            CREATE INDEX IF NOT EXISTS idx_board_posts_board ON board_posts(board, created);
            CREATE TABLE IF NOT EXISTS board_templates(
              id TEXT PRIMARY KEY,
              ord INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL DEFAULT 'active',
              created TEXT NOT NULL,
              updated TEXT NOT NULL,
              data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS board_template_uses(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              template_id TEXT NOT NULL,
              version INTEGER NOT NULL DEFAULT 1,
              user_id TEXT NOT NULL DEFAULT '',
              ok INTEGER NOT NULL DEFAULT 1,
              ms INTEGER NOT NULL DEFAULT 0,
              doc_id TEXT NOT NULL DEFAULT '',
              posted INTEGER NOT NULL DEFAULT 0,  -- 2026-09-18 부터 미사용(템플릿 결과 파일 게시 폐지) / unused since 2026-09-18
              created TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS board_meta(k TEXT PRIMARY KEY, v TEXT);
            CREATE TABLE IF NOT EXISTS board_notifications(
              post_id TEXT NOT NULL REFERENCES board_posts(id) ON DELETE CASCADE,
              user_id TEXT NOT NULL,
              created TEXT NOT NULL,
              read_at TEXT,
              PRIMARY KEY(post_id, user_id)
            );
            """
        )


# ────────────────────────────────────────────────────────
# 메타(마이그레이션 멱등 플래그) / meta (idempotent migration flags)
# ────────────────────────────────────────────────────────

def meta_get(k: str) -> str | None:
    with db._conn() as conn:
        r = conn.execute("SELECT v FROM board_meta WHERE k = ?", (k,)).fetchone()
    return r["v"] if r else None


def meta_set(k: str, v: str) -> None:
    with db._conn() as conn:
        conn.execute("INSERT OR REPLACE INTO board_meta(k, v) VALUES(?, ?)", (k, v))


# ────────────────────────────────────────────────────────
# 게시글 / posts
# ────────────────────────────────────────────────────────

def _row_to_post(r) -> dict:
    d = json.loads(r["data"])
    d.pop("tags", None)   # 태그 기능 폐지(2026-09-18): 옛 글의 값은 응답에 싣지 않는다 / tags retired: never exposed
    d.update({"id": r["id"], "board": r["board"], "kind": r["kind"], "status": r["status"],
              "pinned": bool(r["pinned"]), "views": int(r["views"] or 0),
              "created": r["created"], "updated": r["updated"]})
    d.setdefault("author", {"id": r["author_id"], "name": ""})
    return d


def _body(post: dict) -> dict:
    """저장용 본문 — 컬럼으로 빠지는 키는 제외 / the JSON body (column-backed keys stripped)"""
    return {k: v for k, v in post.items()
            if k not in ("id", "board", "kind", "status", "pinned", "views", "created", "updated", "tags")}


def add_post(board: str, post: dict, post_id: str | None = None, created: str | None = None,
             recipients: list[str] | None = None) -> dict:
    pid = post_id or ("bp_" + uuid.uuid4().hex[:8])
    now = _now()
    kind = post.get("kind") if post.get("kind") in KINDS else "report"
    author = post.get("author") if isinstance(post.get("author"), dict) else {"id": "", "name": ""}
    with db._conn() as conn:
        conn.execute(
            "INSERT INTO board_posts(id, board, kind, status, pinned, views, author_id, created, updated, data)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (pid, board, kind, "published", 1 if post.get("pinned") else 0, 0, str(author.get("id") or ""),
             created or now, now, json.dumps({**_body(post), "author": author}, ensure_ascii=False)),
        )
        _notify(conn, pid, board, recipients)
    return get_post(pid)


def get_post(pid: str) -> dict | None:
    with db._conn() as conn:
        r = conn.execute("SELECT * FROM board_posts WHERE id = ?", (pid,)).fetchone()
    return _row_to_post(r) if r else None


def list_posts(board: str, kinds: tuple | list | None = None, q: str = "",
               limit: int = MAX_POSTS_LIST) -> list[dict]:
    """게시판 목록 — 고정 글 먼저, 최신순. q 는 제목·요약·본문 텍스트 부분 일치.
    게시(published) 상태만 나온다 — 옛 검토 대기·반려·보관 글이 DB 에 남아 있어도 목록에는 보이지 않는다."""
    # Board listing — pinned first, newest first. q matches title/summary/body text.
    # Only published posts are listed; leftover pending/rejected/archived rows of older databases stay hidden.
    with db._conn() as conn:
        rows = conn.execute("SELECT * FROM board_posts WHERE board = ? AND status = 'published'"
                            " ORDER BY pinned DESC, created DESC", (board,)).fetchall()
    return _pick(rows, kinds, q, limit)


def list_posts_in(board_ids: list[str], kinds: tuple | list | None = None, q: str = "", author_id: str | None = None,
                  pinned_first: bool = True, limit: int = MAX_POSTS_LIST) -> list[dict]:
    """여러 게시판의 글을 한 목록으로(2026-10-06 게시판 화면 개편) — 내 그룹 전체(고정 먼저, 최신순)와 내가 최근 추가한 항목
    (author_id 로 거르고 최신순만). 어떤 게시판을 넣을지(열람 권한)는 boards_api 가 정한다.
    Posts of several boards in one list (2026-10-06 board redesign): all my groups (pinned first, newest first) and the items I
    added recently (filtered by author_id, newest first only). boards_api decides which boards are readable."""
    if not board_ids:
        return []
    marks = ",".join("?" for _ in board_ids)
    sql = f"SELECT * FROM board_posts WHERE board IN ({marks}) AND status = 'published'"
    args: list = list(board_ids)
    if author_id is not None:
        sql += " AND author_id = ?"
        args.append(author_id)
    sql += " ORDER BY " + ("pinned DESC, " if pinned_first else "") + "created DESC"
    with db._conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    return _pick(rows, kinds, q, limit)


def _pick(rows, kinds, q: str, limit: int) -> list[dict]:
    """종류 · 검색어로 거르고 limit 개까지 / filter by kind and query, up to limit"""
    out = []
    ql = (q or "").strip().lower()
    for r in rows:
        if kinds and r["kind"] not in kinds:
            continue
        p = _row_to_post(r)
        if ql:
            hay = " ".join([str(p.get("title") or ""), str(p.get("summary") or ""), _text_of(p)]).lower()
            if ql not in hay:
                continue
        out.append(p)
        if len(out) >= limit:
            break
    return out


def _text_of(p: dict) -> str:
    """검색용 본문 텍스트 — 종류별 스냅샷에서 뽑는다 / searchable body text per kind"""
    d = p.get("data") or {}
    if not isinstance(d, dict):
        return ""
    if p.get("kind") == "dashboard":
        return " ".join(str(it.get("title") or "") + " " + str(it.get("insight") or "") for it in (d.get("items") or []) if isinstance(it, dict))
    return str(d.get("insight") or "")


def update_post(pid: str, patch: dict) -> dict | None:
    """부분 갱신 — title/summary/data/source/thumb 는 본문, board/pinned/kind 는 컬럼. created 유지."""
    # Partial update — body keys vs. column keys; created is preserved.
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM board_posts WHERE id=?", (pid,)).fetchone()
        if row is None:
            return None
        cur = _row_to_post(row)
        body = _body(cur)
        for k in ("title", "summary", "data", "source", "thumb", "author", "group"):
            if k in patch:
                body[k] = patch[k]
        board = patch.get("board", cur["board"])
        pinned = 1 if patch.get("pinned", cur["pinned"]) else 0
        kind = patch["kind"] if patch.get("kind") in KINDS else cur["kind"]
        if pinned and (not cur["pinned"] or board != cur["board"]):
            count = conn.execute("SELECT COUNT(*) FROM board_posts WHERE board=? AND pinned=1 AND id<>?",
                                 (board, pid)).fetchone()[0]
            if count >= PIN_MAX:
                raise ValueError(f"고정 글은 게시판마다 {PIN_MAX}개까지입니다")
        conn.execute(
            "UPDATE board_posts SET board=?, kind=?, pinned=?, updated=?, data=? WHERE id=?",
            (board, kind, pinned, _now(), json.dumps(body, ensure_ascii=False), pid),
        )
    return get_post(pid)


def _notify(conn, pid, board, recipients):
    """새 글 알림 — 개인 보관함 글은 알리지 않고, 수신자마다 글 하나에 한 번만 / notify once per recipient; never for the personal library"""
    if board.startswith("me:"):
        return
    conn.executemany("INSERT OR IGNORE INTO board_notifications(post_id,user_id,created) VALUES(?,?,?)",
                     [(pid, uid, _now()) for uid in set(recipients or [])])


def unread_notifications(user_id: str, board_ids: list[str]) -> list[dict]:
    if not board_ids:
        return []
    marks = ",".join("?" for _ in board_ids)
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT p.* FROM board_notifications n JOIN board_posts p ON p.id=n.post_id "
            f"WHERE n.user_id=? AND n.read_at IS NULL AND p.status='published' AND p.board IN ({marks}) "
            "ORDER BY n.created DESC", [user_id, *board_ids]).fetchall()
    return [_row_to_post(r) for r in rows]


def read_notification(pid: str, user_id: str) -> None:
    with db._conn() as conn:
        conn.execute("UPDATE board_notifications SET read_at=? WHERE post_id=? AND user_id=?",
                     (_now(), pid, user_id))


def delete_post(pid: str) -> bool:
    with db._conn() as conn:
        cur = conn.execute("DELETE FROM board_posts WHERE id = ?", (pid,))
    return cur.rowcount > 0


def bump_views(pid: str) -> None:
    with db._conn() as conn:
        conn.execute("UPDATE board_posts SET views = views + 1 WHERE id = ?", (pid,))


def count_posts(boards: list[str] | None = None) -> dict[str, int]:
    """게시판별 글 수(게시 상태) / published post counts per board"""
    with db._conn() as conn:
        rows = conn.execute("SELECT board, COUNT(*) AS c FROM board_posts WHERE status='published' GROUP BY board").fetchall()
    return {r["board"]: int(r["c"]) for r in rows if boards is None or r["board"] in boards}


# ────────────────────────────────────────────────────────
# 문서 템플릿 / document templates
# ────────────────────────────────────────────────────────

def _row_to_template(r) -> dict:
    d = json.loads(r["data"])
    d.update({"id": r["id"], "status": r["status"], "created": r["created"], "updated": r["updated"]})
    d.setdefault("version", 1)
    return d


def list_templates(group_ids: list[str] | None = None, status: str | None = None) -> list[dict]:
    """템플릿 목록 — group_ids 가 오면 그 그룹에 적용된 것만(빈 groups = 전체 그룹 공용) / templates; group filter (empty groups = shared)"""
    with db._conn() as conn:
        rows = conn.execute("SELECT * FROM board_templates ORDER BY ord ASC, created ASC").fetchall()
    out = []
    for r in rows:
        t = _row_to_template(r)
        if status and t["status"] != status:
            continue
        if group_ids is not None:
            tg = t.get("groups") or []
            if tg and not any(g in tg for g in group_ids):
                continue
        out.append(t)
    return out


def get_template(tid: str) -> dict | None:
    with db._conn() as conn:
        r = conn.execute("SELECT * FROM board_templates WHERE id = ?", (tid,)).fetchone()
    return _row_to_template(r) if r else None


def add_template(data: dict) -> dict:
    tid = "tp_" + uuid.uuid4().hex[:8]
    now = _now()
    body = {k: v for k, v in data.items() if k not in ("id", "status", "created", "updated")}
    body["version"] = 1
    with db._conn() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM board_templates").fetchone()["n"]
        conn.execute("INSERT INTO board_templates(id, ord, status, created, updated, data) VALUES(?,?,?,?,?,?)",
                     (tid, n, data.get("status") if data.get("status") in ("active", "off") else "active", now, now,
                      json.dumps(body, ensure_ascii=False)))
    return get_template(tid)


def update_template(tid: str, data: dict) -> dict | None:
    """전체 교체(버전 +1, created·ord 유지) / full replace (version +1; created and ord preserved)"""
    cur = get_template(tid)
    if cur is None:
        return None
    body = {k: v for k, v in data.items() if k not in ("id", "status", "created", "updated")}
    body["version"] = int(cur.get("version") or 1) + 1
    with db._conn() as conn:
        conn.execute("UPDATE board_templates SET status=?, updated=?, data=? WHERE id=?",
                     (data.get("status") if data.get("status") in ("active", "off") else cur["status"], _now(),
                      json.dumps(body, ensure_ascii=False), tid))
    return get_template(tid)


def delete_template(tid: str) -> bool:
    with db._conn() as conn:
        cur = conn.execute("DELETE FROM board_templates WHERE id = ?", (tid,))
    return cur.rowcount > 0


def record_use(tid: str, version: int, user_id: str, ok: bool, ms: int, doc_id: str = "") -> None:
    with db._conn() as conn:
        conn.execute("INSERT INTO board_template_uses(template_id, version, user_id, ok, ms, doc_id, posted, created)"
                     " VALUES(?,?,?,?,?,?,0,?)", (tid, int(version or 1), user_id or "", 1 if ok else 0, int(ms or 0), doc_id or "", _now()))


def template_usage(days: int = 30, template_ids: list[str] | None = None) -> dict[str, dict]:
    """템플릿별 사용 요약(최근 days 일) — 게시판 관리의 템플릿 목록에 실린다 / per-template usage shown in the template list"""
    since = (kst.now() - timedelta(days=days)).isoformat(timespec="seconds")
    where, params = "created >= ?", [since]
    if template_ids is not None:
        where += " AND template_id IN (" + (",".join("?" for _ in template_ids) or "NULL") + ")"
        params.extend(template_ids)
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT template_id, COUNT(*) AS uses, SUM(ok) AS oks, AVG(ms) AS avg_ms,"
            " COUNT(DISTINCT user_id) AS users, MAX(created) AS last_used"
            " FROM board_template_uses WHERE " + where + " GROUP BY template_id", params).fetchall()
    return {r["template_id"]: {"uses": int(r["uses"]), "ok": int(r["oks"] or 0), "avg_ms": int(r["avg_ms"] or 0),
                               "users": int(r["users"] or 0), "last_used": r["last_used"]} for r in rows}
