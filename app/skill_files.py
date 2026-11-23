"""Skill 파일 저장소(2026-09-23, 사용자 시안 "MCP 연결 등록" 4절 Skills) — MCP 연결(관리 센터 API · MCP 연결)과 업무 자동화
에이전트(MCP 방식)에 붙이는 기술(skill) 정의 파일. 에이전트가 이 연결을 어떻게 쓰는지 적은 문서(.yaml .yml .json .md .txt)를
이름·크기·본문·올린 시각으로 보관한다.

  - 올리면 주인이 없는 상태(pending)로 저장되고, 연결을 [저장]할 때 skill_ids 로 주인(owner_kind, owner_id)에게 붙는다.
    저장 목록에서 빠진 주인의 파일은 그때 지워지고, 24시간 지난 주인 없는 파일은 다음 업로드 때 정리된다(취소한 폼의 찌꺼기).
  - 파일당 10MB, 주인당 20개, 허용 확장자 5종. 본문은 UTF-8 텍스트로 저장한다(깨진 바이트는 대체 문자).
  - 아직 파이프라인이 읽지는 않는다 — 워크플로우 외부 도구 계획 프롬프트에 싣는 것은 다음 단계.

Skill file store (2026-09-23, section 4 "Skills" of the user's MCP-connection design) — skill definition files attached to
MCP connections (Admin Center) and MCP-based work agents (Resource Center): documents (.yaml .yml .json .md .txt) that tell
agents how to use the connection, kept as name, size, text body and upload time.
  - An upload is stored without an owner (pending); saving the connection attaches the listed skill_ids to the owner
    (owner_kind, owner_id). The owner's files missing from that list are deleted then; pending files older than 24 hours
    are purged on the next upload (leftovers of cancelled forms).
  - 10MB per file, 20 files per owner, five allowed extensions. The body is stored as UTF-8 text (bad bytes replaced).
  - The pipeline does not read them yet; feeding them into the external-tool planning prompt is a later step.
"""

from __future__ import annotations

import re
import sqlite3
import time
import uuid

from app import kst
from app.db import DB_PATH

ALLOWED_EXT = (".yaml", ".yml", ".json", ".md", ".txt")
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PER_OWNER = 20
MAX_NAME = 120
PENDING_TTL_SEC = 24 * 3600
_ID_RX = re.compile(r"^sk_[0-9a-f]{12}$")


class SkillFileError(ValueError):
    pass


def _now() -> str:
    return kst.now_iso()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_skill_files() -> None:
    """테이블 생성(멱등) / create the table (idempotent)"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_files(
              id TEXT PRIMARY KEY,
              owner_kind TEXT NOT NULL DEFAULT '',
              owner_id TEXT NOT NULL DEFAULT '',
              name TEXT NOT NULL,
              size INTEGER NOT NULL DEFAULT 0,
              content TEXT NOT NULL DEFAULT '',
              uploaded_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_skill_files_owner ON skill_files(owner_kind, owner_id)")


def _row(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "owner_kind": r["owner_kind"] or "", "owner_id": r["owner_id"] or "", "name": r["name"],
            "size": int(r["size"] or 0), "content": r["content"] or "", "uploaded_at": r["uploaded_at"]}


def public(rec: dict) -> dict:
    """화면용 요약(본문·주인 없음) / screen summary without the body or owner"""
    return {"id": rec["id"], "name": rec["name"], "size": rec["size"], "uploaded_at": rec["uploaded_at"]}


def clean_name(name) -> str:
    """경로를 떼고 길이를 자른 파일 이름 / the file name without any path, capped in length"""
    base = str(name or "").replace("\\", "/").split("/")[-1].strip()
    return base[:MAX_NAME]


def add(name, data: bytes, owner_kind: str = "", owner_id: str = "") -> dict:
    """파일 1개 저장 — 확장자·크기·빈 파일 검사, 주인은 보통 비워 둔다(저장 때 attach) / store one file; owner is usually empty until save"""
    fname = clean_name(name)
    if not fname:
        raise SkillFileError("파일 이름이 비어 있습니다")
    if not fname.lower().endswith(ALLOWED_EXT):
        raise SkillFileError("지원하지 않는 파일 형식입니다. .yaml, .yml, .json, .md, .txt 만 올릴 수 있습니다")
    data = data or b""
    if not data:
        raise SkillFileError("빈 파일은 올릴 수 없습니다")
    if len(data) > MAX_FILE_BYTES:
        raise SkillFileError("파일당 최대 10MB 까지 올릴 수 있습니다")
    if owner_kind:
        if len(list_for(owner_kind, owner_id)) >= MAX_PER_OWNER:
            raise SkillFileError(f"Skill 파일은 연결당 최대 {MAX_PER_OWNER}개까지입니다")
    purge_pending()
    rec = {"id": "sk_" + uuid.uuid4().hex[:12], "owner_kind": owner_kind or "", "owner_id": owner_id or "", "name": fname,
           "size": len(data), "content": data.decode("utf-8", errors="replace"), "uploaded_at": _now()}
    with _conn() as conn:
        conn.execute("INSERT INTO skill_files(id, owner_kind, owner_id, name, size, content, uploaded_at) VALUES(?,?,?,?,?,?,?)",
                     (rec["id"], rec["owner_kind"], rec["owner_id"], rec["name"], rec["size"], rec["content"], rec["uploaded_at"]))
    return rec


def get(file_id: str) -> dict | None:
    try:
        with _conn() as conn:
            r = conn.execute("SELECT * FROM skill_files WHERE id=?", (file_id,)).fetchone()
    except sqlite3.OperationalError:   # 테이블 미생성(부팅 순서·격리 DB) / table not created yet
        return None
    return _row(r) if r else None


def list_for(owner_kind: str, owner_id: str) -> list[dict]:
    """주인의 파일 요약 목록(올린 순) / the owner's files (upload order), summaries only"""
    try:
        with _conn() as conn:
            rows = conn.execute("SELECT id, name, size, uploaded_at FROM skill_files WHERE owner_kind=? AND owner_id=?"
                                " ORDER BY uploaded_at, rowid", (owner_kind or "", owner_id or "")).fetchall()   # 같은 초 안에서는 올린 순서(rowid) / same-second uploads keep insertion order
    except sqlite3.OperationalError:
        return []
    return [{"id": r["id"], "name": r["name"], "size": int(r["size"] or 0), "uploaded_at": r["uploaded_at"]} for r in rows]


def parse_ids(raw) -> list[str] | None:
    """저장 본문의 skill_ids — None 은 '그대로 둔다', 목록은 형식 검사·중복 제거·상한 / None keeps the current files; a list is validated"""
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise SkillFileError("skill_ids 는 배열이어야 합니다")
    out: list[str] = []
    for v in raw:
        if not isinstance(v, str) or not _ID_RX.match(v):
            raise SkillFileError("skill_ids 항목의 형식이 올바르지 않습니다")
        if v not in out:
            out.append(v)
    if len(out) > MAX_PER_OWNER:
        raise SkillFileError(f"Skill 파일은 연결당 최대 {MAX_PER_OWNER}개까지입니다")
    return out


def ensure_attachable(ids: list[str], owner_kind: str, owner_id: str | None) -> None:
    """붙일 수 있는지 미리 확인 — 없는 파일, 다른 주인의 파일은 거부 / reject unknown files and files owned by someone else"""
    for fid in ids:
        rec = get(fid)
        if rec is None:
            raise SkillFileError(f"알 수 없는 Skill 파일입니다: {fid}")
        if rec["owner_kind"] and not (rec["owner_kind"] == owner_kind and owner_id is not None and rec["owner_id"] == owner_id):
            raise SkillFileError(f"다른 연결에 붙어 있는 Skill 파일입니다: {rec['name']}")


def attach(owner_kind: str, owner_id: str, ids: list[str]) -> list[dict]:
    """목록의 파일을 주인에게 붙이고, 목록에서 빠진 주인의 파일은 지운다 → 주인의 파일 요약 / attach the listed files, drop the rest"""
    keep = set(ids)
    with _conn() as conn:
        for fid in ids:
            conn.execute("UPDATE skill_files SET owner_kind=?, owner_id=? WHERE id=?", (owner_kind, owner_id, fid))
        rows = conn.execute("SELECT id FROM skill_files WHERE owner_kind=? AND owner_id=?", (owner_kind, owner_id)).fetchall()
        for r in rows:
            if r["id"] not in keep:
                conn.execute("DELETE FROM skill_files WHERE id=?", (r["id"],))
    return list_for(owner_kind, owner_id)


def delete(file_id: str, owner_kind: str | None = None, owner_id: str | None = None) -> bool:
    """파일 1개 삭제 — 주인 없는 파일은 누구나(관리 화면), 주인 있는 파일은 그 주인 종류일 때만 / pending files freely, owned files only by that owner kind"""
    rec = get(file_id)
    if rec is None:
        return False
    if rec["owner_kind"]:
        if owner_kind is not None and rec["owner_kind"] != owner_kind:
            return False
        if owner_id is not None and rec["owner_id"] != owner_id:
            return False
    with _conn() as conn:
        conn.execute("DELETE FROM skill_files WHERE id=?", (file_id,))
    return True


def delete_for(owner_kind: str, owner_id: str) -> int:
    """주인의 파일 전부 삭제(연결 삭제 때) → 지운 수 / delete all of an owner's files (when the connection is deleted)"""
    with _conn() as conn:
        n = conn.execute("DELETE FROM skill_files WHERE owner_kind=? AND owner_id=?", (owner_kind, owner_id)).rowcount
    return int(n or 0)


def purge_pending(now_ts: float | None = None) -> int:
    """24시간 지난 주인 없는 파일 정리 → 지운 수 / drop pending files older than a day"""
    cutoff = kst.from_epoch((now_ts if now_ts is not None else time.time()) - PENDING_TTL_SEC).isoformat(timespec="seconds")
    try:
        with _conn() as conn:
            n = conn.execute("DELETE FROM skill_files WHERE owner_kind='' AND uploaded_at < ?", (cutoff,)).rowcount
    except sqlite3.OperationalError:
        return 0
    return int(n or 0)
