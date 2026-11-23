"""AI Batch Log(2026-09-16) — 지식 관리 인덱싱(문서 분석·색인·임베딩) 처리 이력. 리소스 센터 › 지식 관리 › AI Batch Log 페이지의 데이터.

  - kb_batch_log 테이블: 파일 1건의 처리 1회 = 행 1개 — batch_id(BAT-YYYYMMDD-NNNN, 날짜별 일련번호), 상태 pending(대기) |
    running(진행 중) | done(완료) | error(오류), 시작·종료 시각, 등록자(업로드한 사람 또는 '시스템'), 오류 사유, 페이지·청크 수.
  - 기록 지점: 업로드(resources_api — 대기 행을 먼저 남기고 인덱서가 진행 중 → 완료/오류로 바꾼다; 허용 용량 초과는 바로 오류 행),
    부팅 증분 인덱싱(kb.index_all — 등록자 '시스템').
  - 백필: 기동 시 kb_docs 에 있으나 로그가 없는 문서는 완료 행으로 채운다(시작 = 종료 = indexed_at) — 이미 색인된 실 문서가 바로 보인다.
  - 폴더명·파일위치는 지식 트리(access.load_knowledge)에서 조회 시점에 계산한다(파일이 옮겨져도 최신 위치).
  - 매뉴얼/쉐어포인트 열: 로컬 업로드 = 'manual'(매뉴얼). 'sharepoint' 는 외부 동기화가 생기면 쓴다.

AI Batch Log (2026-09-16) — processing history of the knowledge index (document analysis, indexing, embedding); the data
behind Resource Center › Knowledge › AI Batch Log.
  - kb_batch_log: one row per processing run of one file — batch_id (BAT-YYYYMMDD-NNNN, per-day sequence), status
    pending | running | done | error, start/finish times, actor (uploader or 'system'), error reason, pages/chunks.
  - Written by the upload endpoint (a pending row first; the indexer flips it to running → done/error; an oversized
    upload becomes an error row straight away) and by the boot-time incremental indexer (actor 'system').
  - Backfill: at startup, documents present in kb_docs without a log row get a done row (start = finish = indexed_at).
  - Folder and location are resolved from the knowledge tree at query time. Source column: local uploads = 'manual'.
"""

from __future__ import annotations

import logging

from app import db, kst

logger = logging.getLogger("ai365.kb_log")

STATUSES = ("pending", "running", "done", "error")
STATUS_LABELS = {"pending": "대기", "running": "진행 중", "done": "완료", "error": "오류"}
SOURCE_LABELS = {"manual": "매뉴얼", "sharepoint": "쉐어포인트"}
SYSTEM_ACTOR = "시스템"
NO_TEXT_REASON = "텍스트 추출 실패 (이미지 전용 PDF)"
MAX_ERROR = 200
PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _now() -> str:
    return kst.now_iso()


def _day(ts: str) -> str:
    return (ts or _now())[:10].replace("-", "")


def init_kb_log() -> int:
    """테이블 생성(멱등) + 백필 → 백필 행 수 / create the table (idempotent) and backfill → rows added"""
    with db._conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS kb_batch_log(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              batch_id TEXT NOT NULL,
              doc TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending',
              source TEXT NOT NULL DEFAULT 'manual',
              actor TEXT NOT NULL DEFAULT '',
              started_at TEXT NOT NULL DEFAULT '',
              finished_at TEXT NOT NULL DEFAULT '',
              error TEXT NOT NULL DEFAULT '',
              pages INTEGER NOT NULL DEFAULT 0,
              chunks INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_kb_batch_log_doc ON kb_batch_log(doc, id);
            """
        )
    return backfill()


def _batch_id(conn, day: str) -> str:
    n = conn.execute("SELECT COUNT(*) AS n FROM kb_batch_log WHERE batch_id LIKE ?", (f"BAT-{day}-%",)).fetchone()["n"]
    return f"BAT-{day}-{n + 1:04d}"


def _insert(conn, doc: str, status: str, source: str, actor: str, started: str, finished: str, error: str,
            pages: int, chunks: int, created: str) -> int:
    cur = conn.execute(
        "INSERT INTO kb_batch_log(batch_id, doc, status, source, actor, started_at, finished_at, error, pages, chunks, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (_batch_id(conn, _day(started or created)), doc, status, source, actor or SYSTEM_ACTOR, started, finished,
         (error or "")[:MAX_ERROR], int(pages or 0), int(chunks or 0), created))
    return int(cur.lastrowid)


def backfill() -> int:
    """kb_docs 에 있는데 로그가 없는 문서 → 완료 행(시작 = 종료 = indexed_at) / done rows for indexed docs that have no log yet"""
    added = 0
    with db._conn() as conn:
        try:
            docs = conn.execute("SELECT doc, pages, chunks, indexed_at FROM kb_docs ORDER BY indexed_at, doc").fetchall()
        except Exception:  # noqa: BLE001 — kb 테이블이 아직 없는 격리 DB / isolated DB without the kb tables yet
            return 0
        logged = {r["doc"] for r in conn.execute("SELECT DISTINCT doc FROM kb_batch_log").fetchall()}
        for r in docs:
            if r["doc"] in logged:
                continue
            at = r["indexed_at"] or _now()
            _insert(conn, r["doc"], "done", "manual", SYSTEM_ACTOR, at, at, "", r["pages"], r["chunks"], at)
            added += 1
    if added:
        logger.info("AI Batch Log 백필: 완료 행 %d건", added)
    return added


# ────────────────────────────────────────────────────────
# 기록 / recording
# ────────────────────────────────────────────────────────

def pending(doc: str, actor: str = SYSTEM_ACTOR, source: str = "manual") -> int:
    """업로드 직후의 대기 행 / the pending row written right after an upload"""
    now = _now()
    with db._conn() as conn:
        return _insert(conn, doc, "pending", source, actor, "", "", "", 0, 0, now)


def start(doc: str, actor: str = SYSTEM_ACTOR, source: str = "manual") -> int:
    """진행 중 행 — 같은 문서의 대기 행이 있으면 그 행을 이어 쓴다(업로드 → 인덱싱 한 건으로) / running row (continues a pending one)"""
    now = _now()
    with db._conn() as conn:
        row = conn.execute("SELECT id FROM kb_batch_log WHERE doc=? AND status='pending' ORDER BY id DESC LIMIT 1", (doc,)).fetchone()
        if row:
            conn.execute("UPDATE kb_batch_log SET status='running', started_at=? WHERE id=?", (now, row["id"]))
            return int(row["id"])
        return _insert(conn, doc, "running", source, actor, now, "", "", 0, 0, now)


def finish(log_id: int, pages: int = 0, chunks: int = 0, error: str | None = None) -> None:
    """완료 또는 오류로 마감 / close the row as done or error"""
    with db._conn() as conn:
        conn.execute("UPDATE kb_batch_log SET status=?, finished_at=?, error=?, pages=?, chunks=? WHERE id=?",
                     ("error" if error else "done", _now(), (error or "")[:MAX_ERROR], int(pages or 0), int(chunks or 0), int(log_id)))


def fail(doc: str, actor: str, error: str, source: str = "manual") -> int:
    """인덱싱 전에 거부된 처리(허용 용량 초과 등)의 오류 행 / an error row for a run rejected before indexing"""
    now = _now()
    with db._conn() as conn:
        return _insert(conn, doc, "error", source, actor, now, now, error, 0, 0, now)


def error_reason(exc: BaseException) -> str:
    """예외 → 화면에 보일 사유 한 줄 / exception → a one-line reason for the screen"""
    msg = (str(exc) or exc.__class__.__name__).strip()
    low = msg.lower()
    if "password" in low or "encrypted" in low:
        return "암호가 설정된 파일"
    if "cannot open" in low or "failed to open" in low or "no objects found" in low or "not a pdf" in low or "filedataerror" in low:
        return "PDF 열기 실패 (손상되었거나 PDF 가 아님)"
    if "embed" in low or "quota" in low or "429" in low or "resource_exhausted" in low or "503" in low:
        return ("임베딩 실패: " + msg)[:MAX_ERROR]
    return msg[:MAX_ERROR]


# ────────────────────────────────────────────────────────
# 조회 / listing
# ────────────────────────────────────────────────────────

def folder_index(tree: list | None = None) -> dict:
    """지식 트리 → {파일명: (폴더명, 파일위치)} / knowledge tree → {file name: (folder label, location path)}"""
    if tree is None:
        from app import access   # 지연 임포트(순환 방지) / lazy import (avoids a cycle)
        try:
            tree = access.load_knowledge()
        except Exception:  # noqa: BLE001 — 트리 없음(격리 DB) / no tree (isolated DB)
            tree = []
    out: dict = {}

    def walk(nodes, path):
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            label = str(n.get("label") or n.get("name") or "")
            here = path + [label]
            for f in n.get("files") or []:
                name = None
                if isinstance(f, (list, tuple)) and len(f) > 1:
                    name = f[1]
                elif isinstance(f, dict):
                    name = f.get("name") or f.get("file")
                elif isinstance(f, str):
                    name = f
                if name and name not in out:
                    out[name] = (label, "/" + "/".join(x for x in here if x))
            walk(n.get("folders") or n.get("children") or [], here)

    walk(tree, [])
    return out


def list_logs(date_from: str = "", date_to: str = "", status: str = "", page: int = 1, size: int = PAGE_SIZE) -> dict:
    """필터(처리 시작일 범위·상태) + 페이지 → {rows, total, page, size, counts}. 대기 행은 등록 시각으로 날짜를 잰다."""
    # Filters (start-date range, status) + paging → {rows, total, page, size, counts}. Pending rows use created_at.
    where, args = [], []
    if status in STATUSES:
        where.append("status=?")
        args.append(status)
    ts = "COALESCE(NULLIF(started_at,''), created_at)"
    if date_from:
        where.append(f"substr({ts},1,10) >= ?")
        args.append(date_from[:10])
    if date_to:
        where.append(f"substr({ts},1,10) <= ?")
        args.append(date_to[:10])
    sql_where = (" WHERE " + " AND ".join(where)) if where else ""
    try:
        page = max(1, int(page or 1))
        size = max(1, min(MAX_PAGE_SIZE, int(size or PAGE_SIZE)))
    except (TypeError, ValueError):
        page, size = 1, PAGE_SIZE
    with db._conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS n FROM kb_batch_log{sql_where}", args).fetchone()["n"]
        counts = {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) AS n FROM kb_batch_log GROUP BY status").fetchall()}
        rows = conn.execute(f"SELECT * FROM kb_batch_log{sql_where} ORDER BY {ts} DESC, id DESC LIMIT ? OFFSET ?",
                            (*args, size, (page - 1) * size)).fetchall()
    folders = folder_index()
    items = []
    for r in rows:
        folder, location = folders.get(r["doc"], ("", ""))
        items.append({"id": r["id"], "batch_id": r["batch_id"], "doc": r["doc"], "folder": folder or "미분류",
                      "location": location or "/knowledge", "source": r["source"],
                      "source_label": SOURCE_LABELS.get(r["source"], r["source"]), "status": r["status"],
                      "status_label": STATUS_LABELS.get(r["status"], r["status"]), "started_at": r["started_at"] or "",
                      "finished_at": r["finished_at"] or "", "actor": r["actor"] or "", "error": r["error"] or "",
                      "pages": r["pages"], "chunks": r["chunks"]})
    return {"rows": items, "total": total, "page": page, "size": size, "counts": {s: counts.get(s, 0) for s in STATUSES}}
