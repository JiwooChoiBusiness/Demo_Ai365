"""채팅 영속화 — SQLite.

데모 대화(목업 하드코딩)는 is_demo=1로 chats에만 시드한다.
메시지는 목업이 자체 렌더하므로 저장하지 않는다.
"""
# Chat persistence — SQLite.
# Demo conversations (hardcoded in the mockup) are seeded only into chats with is_demo=1.
# Messages are not stored because the mockup renders them itself.

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path

from app import kst

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "ai365.db"

# 목업 frontend/ai365-mockup.html의 chats 배열과 동일한 데모 시드
# Demo seed identical to the chats array in the mockup frontend/ai365-mockup.html.
DEMO_CHATS = [
    ("p1", "경영진 보고서 작성", "사내", "영업관리 업무 지식"),
    ("p2", "이미지 구성 프롬프트 요청", "외부", None),
    ("p3", "글 다듬기 요청", "외부", None),
    ("r0", "회사 성과 파악 및 내부 정책 확인", "사내", "영업관리 업무 지식"),
    ("q4", "2025 4Q 매출 성과 파악", "외부", None),
    ("web", "웹사이트 제작", "외부", None),
    ("proj", "프로젝트 확인", "사내", "데이터 분석"),
    ("ppt", "경영진 생산성 및 실적 발표자료 PPT 작성", "사내", "기타 업무 지식"),
]


def _now() -> str:
    return kst.now_iso()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate_chats_scope(conn: sqlite3.Connection) -> None:
    """기존 DB의 chats.scope CHECK 제약에 '자동'을 추가한다.

    SQLite는 CHECK 제약을 ALTER로 바꿀 수 없으므로, 옛 제약('사내','외부'만 허용)이
    남아 있으면 테이블을 재생성(데이터 복사)해 '자동'을 받도록 갱신한다. 채팅 기록은 보존된다.
    """
    # Add '자동' (auto) to the chats.scope CHECK constraint of an existing DB.
    #
    # Since SQLite cannot alter a CHECK constraint via ALTER, if the old constraint
    # (allowing only '사내'/'외부') remains, the table is recreated (copying data) so it
    # accepts '자동'. Chat history is preserved.
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='chats'"
    ).fetchone()
    if not row or "자동" in (row["sql"] or ""):
        return  # 신규 생성이거나 이미 마이그레이션됨
    # Newly created or already migrated.
    # 새 스키마로 재생성 → 복사 → 교체 (FK는 테이블명 'chats'로 그대로 유지된다)
    # Recreate with the new schema → copy → swap (FK stays intact under the table name 'chats').
    conn.executescript(
        """
        PRAGMA foreign_keys=OFF;
        PRAGMA legacy_alter_table=ON;
        CREATE TABLE chats_new(
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          scope TEXT NOT NULL CHECK(scope IN ('자동','사내','외부')),
          knowledge TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          is_demo INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO chats_new(id, title, scope, knowledge, created_at, updated_at, is_demo)
          SELECT id, title, scope, knowledge, created_at, updated_at, is_demo FROM chats;
        DROP TABLE chats;
        ALTER TABLE chats_new RENAME TO chats;
        PRAGMA legacy_alter_table=OFF;
        PRAGMA foreign_keys=ON;
        """
    )


def _migrate_chats_coll(conn: sqlite3.Connection) -> None:
    """기존 DB의 chats에 컬렉션 태그 컬럼(coll)을 추가한다 — 컬렉션 채팅 연동(2026-08-25)."""
    # Add the collection-tag column (coll) to an existing DB's chats — collection chat linkage.
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(chats)").fetchall()}
    if "coll" not in cols:
        conn.execute("ALTER TABLE chats ADD COLUMN coll TEXT")


def _migrate_chats_sched(conn: sqlite3.Connection) -> None:
    """기존 DB의 chats에 예약 태그 컬럼(sched)을 추가한다 — 컬렉션 예약 실행(2026-09-02).
    예약 실행이 만든 채팅이면 예약 id가 들어가고, 프런트는 이를 보고 벨 아이콘을 표시한다."""
    # Add the schedule-tag column (sched) to an existing DB's chats — collection scheduled runs.
    # Chats created by a scheduled run carry the schedule id; the front end shows a bell icon for them.
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(chats)").fetchall()}
    if "sched" not in cols:
        conn.execute("ALTER TABLE chats ADD COLUMN sched TEXT")
    # 실행 결과(6차, 2026-09-07): 예약 히스토리 표시용 ok|doc|needs_input|429|error:… / run result for the schedule history
    if "sched_result" not in cols:
        conn.execute("ALTER TABLE chats ADD COLUMN sched_result TEXT")
    # 컴포저 컬렉션 첨부(2026-09-08): 첨부 때 고른 파일 이름 JSON 목록(비면 컬렉션 전체) — 맥락 주입을 그 파일로 좁힌다
    # Composer collection attach (2026-09-08): JSON list of the picked file names (empty = whole collection) — narrows the injected context
    if "coll_files" not in cols:
        conn.execute("ALTER TABLE chats ADD COLUMN coll_files TEXT")
    # 커넥터(2026-09-09): 이 채팅에 연결한 커넥터 id JSON 목록 — 채팅 커넥터 알약은 2026-09-11 폐지(컬럼은 호환용으로 유지)
    # Connectors (2026-09-09): JSON list of connector ids — the chat pill was retired 2026-09-11 (column kept for compatibility)
    if "connectors" not in cols:
        conn.execute("ALTER TABLE chats ADD COLUMN connectors TEXT")
    # 워크플로우 모드(2026-09-11): 컴포저 [워크플로우] 알약으로 켠 모드 — 켜져 있으면 이 채팅의 메시지는 그 워크플로우로 실행된다
    # (flow_id 빈 값 = 일반 파이프라인). flow_name 은 표시용 스냅샷.
    # Workflow mode (2026-09-11): turned on from the composer [Workflow] pill — while set, this chat's messages run
    # through that workflow (empty flow_id = normal pipeline). flow_name is a display snapshot.
    if "flow_id" not in cols:
        conn.execute("ALTER TABLE chats ADD COLUMN flow_id TEXT NOT NULL DEFAULT ''")
    if "flow_name" not in cols:
        conn.execute("ALTER TABLE chats ADD COLUMN flow_name TEXT NOT NULL DEFAULT ''")


def _migrate_chats_run(conn: sqlite3.Connection) -> None:
    """기존 DB의 chats에 실행 상태 컬럼(run_state·unseen)을 추가한다 — 백그라운드 답변 실행(2026-09-04).
    run_state: ''|running|done|needs_input|error|stopped, unseen: 끝난 뒤 아직 열어보지 않았으면 1."""
    # Add the run-state columns (run_state, unseen) to an existing DB's chats — background answer runs.
    # run_state: ''|running|done|needs_input|error|stopped; unseen = 1 until the chat is opened after finishing.
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(chats)").fetchall()}
    if "run_state" not in cols:
        conn.execute("ALTER TABLE chats ADD COLUMN run_state TEXT NOT NULL DEFAULT ''")
    if "unseen" not in cols:
        conn.execute("ALTER TABLE chats ADD COLUMN unseen INTEGER NOT NULL DEFAULT 0")


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chats(
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              scope TEXT NOT NULL CHECK(scope IN ('자동','사내','외부')),
              knowledge TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              is_demo INTEGER NOT NULL DEFAULT 0,
              coll TEXT,
              coll_files TEXT,
              connectors TEXT,
              sched TEXT,
              sched_result TEXT,
              run_state TEXT NOT NULL DEFAULT '',
              unseen INTEGER NOT NULL DEFAULT 0,
              flow_id TEXT NOT NULL DEFAULT '',
              flow_name TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS messages(
              id TEXT PRIMARY KEY,
              chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
              role TEXT NOT NULL CHECK(role IN ('user','assistant')),
              content TEXT NOT NULL,
              meta TEXT,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, created_at);
            CREATE TABLE IF NOT EXISTS kb_docs(
              doc TEXT PRIMARY KEY,
              hash TEXT NOT NULL,
              pages INTEGER NOT NULL,
              chunks INTEGER NOT NULL,
              indexed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS kb_chunks(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              doc TEXT NOT NULL,
              page INTEGER NOT NULL,
              text TEXT NOT NULL,
              vector BLOB NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_kb_chunks_doc ON kb_chunks(doc);
            CREATE TABLE IF NOT EXISTS llm_cache(
              cache_key TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              value TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pending_actions(
              id TEXT PRIMARY KEY,
              chat_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              payload TEXT NOT NULL,
              summary TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','executed','cancelled','failed')),
              created_at TEXT NOT NULL,
              executed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS gw_state(
              id INTEGER PRIMARY KEY CHECK(id = 1),
              data TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        _migrate_chats_scope(conn)
        _migrate_chats_coll(conn)
        _migrate_chats_sched(conn)
        _migrate_chats_run(conn)
        now = _now()
        conn.executemany(
            "INSERT OR IGNORE INTO chats(id, title, scope, knowledge, created_at, updated_at, is_demo)"
            " VALUES(?, ?, ?, ?, ?, ?, 1)",
            [(cid, title, scope, knowledge, now, now) for cid, title, scope, knowledge in DEMO_CHATS],
        )


def _chat_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["is_demo"] = bool(d["is_demo"])
    # 실행 상태(2026-09-04): 사이드바 스피너/완료 아이콘용 — SELECT * 라 자동 포함, 타입만 정규화
    # Run state (2026-09-04): for the sidebar spinner / done icon — included via SELECT *, types normalised here
    d["run_state"] = d.get("run_state") or ""
    d["unseen"] = bool(d.get("unseen"))
    # 컬렉션 첨부 파일 목록(2026-09-08) — JSON 문자열 → 리스트 / collection attachment file list — JSON string → list
    try:
        files = json.loads(d.get("coll_files") or "[]")
    except (TypeError, ValueError):
        files = []
    d["coll_files"] = [str(x) for x in files] if isinstance(files, list) else []
    d.pop("connectors", None)   # 채팅 커넥터 알약 폐지(2026-09-11) — 컬럼은 남되 응답에서 뺀다 / pill retired; column kept, not exposed
    # 워크플로우 모드(2026-09-11) — 켜져 있으면 flow_id/flow_name / workflow mode (2026-09-11)
    d["flow_id"] = d.get("flow_id") or ""
    d["flow_name"] = d.get("flow_name") or ""
    return d


def list_chats(include_sched: bool = False) -> list[dict]:
    """채팅 목록. 예약 실행이 만든 결과 채팅(sched)은 기본 제외(6차, 2026-09-07 — 예약에 종속: 예약 히스토리·메일 링크로만 연다)."""
    # Chat list. Result chats created by scheduled runs (sched) are excluded by default (round 6 — owned by the
    # schedule: opened only from the schedule history or the mail link).
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM chats" + ("" if include_sched else " WHERE sched IS NULL")
                            + " ORDER BY is_demo DESC, created_at ASC").fetchall()
    return [_chat_dict(r) for r in rows]


def set_chat_sched_result(chat_id: str, result: str) -> bool:
    """예약 결과 채팅에 실행 결과 기록(6차) — updated_at 무변경 / stamp the run result on a schedule's result chat"""
    with _conn() as conn:
        cur = conn.execute("UPDATE chats SET sched_result = ? WHERE id = ?", ((result or "")[:220], chat_id))
    return cur.rowcount > 0


def get_chat(chat_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
    return _chat_dict(row) if row else None


def create_chat(title: str, scope: str, knowledge: str | None = None, coll: str | None = None,
                sched: str | None = None, coll_files: list[str] | None = None,
                flow_id: str = "", flow_name: str = "") -> dict:
    """채팅 생성. sched(2026-09-02)=예약 실행이 만든 채팅이면 그 예약 id(벨 아이콘 표시용).
    coll_files(2026-09-08)=컴포저 컬렉션 첨부에서 고른 파일 이름(비면 컬렉션 전체).
    flow_id/flow_name(2026-09-11)=홈 컴포저에서 미리 켜 둔 워크플로우 모드."""
    # Create a chat. sched = the schedule id when a scheduled run created the chat (bell-icon marker).
    # coll_files = file names picked in the composer's collection attachment (empty = whole collection).
    # flow_id/flow_name (2026-09-11) = workflow mode pre-selected in the home composer.
    chat_id = "c_" + uuid.uuid4().hex[:12]
    now = _now()
    files_json = json.dumps(list(coll_files), ensure_ascii=False) if (coll and coll_files) else None
    with _conn() as conn:
        conn.execute(
            "INSERT INTO chats(id, title, scope, knowledge, created_at, updated_at, is_demo, coll, sched, coll_files, flow_id, flow_name)"
            " VALUES(?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)",
            (chat_id, title, scope, knowledge, now, now, coll, sched, files_json,
             (flow_id or "").strip(), (flow_name or "").strip()),
        )
    return get_chat(chat_id)


def set_chat_flow(chat_id: str, flow_id: str, flow_name: str) -> bool:
    """워크플로우 모드 켜기/끄기(2026-09-11, 컴포저 [워크플로우] 알약·모드 바 ✕) — flow_id 빈 값 = 끄기 / turn workflow mode on/off"""
    with _conn() as conn:
        cur = conn.execute("UPDATE chats SET flow_id = ?, flow_name = ? WHERE id = ?",
                           ((flow_id or "").strip(), (flow_name or "").strip() if flow_id else "", chat_id))
    return cur.rowcount > 0


def set_chat_coll(chat_id: str, coll: str | None, coll_files: list[str] | None = None) -> bool:
    """진행 중 채팅을 컬렉션에 묶는다(컴포저 컬렉션 첨부, 2026-09-08) — coll=None 이면 해제. 이후 질문부터 맥락 주입."""
    # Bind a running chat to a collection (composer attach, 2026-09-08) — coll=None unbinds. Context injection starts with the next question.
    files_json = json.dumps(list(coll_files), ensure_ascii=False) if (coll and coll_files) else None
    with _conn() as conn:
        cur = conn.execute("UPDATE chats SET coll = ?, coll_files = ? WHERE id = ?", (coll, files_json, chat_id))
    return cur.rowcount > 0


def update_chat_title(chat_id: str, title: str) -> bool:
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE chats SET title = ?, updated_at = ? WHERE id = ?", (title, _now(), chat_id)
        )
    return cur.rowcount > 0


def delete_chat(chat_id: str) -> bool:
    from app import execution_store
    execution_store.init_store()
    with _conn() as conn:
        execution_store.remove_chat(chat_id, conn)
        conn.execute("DELETE FROM pending_actions WHERE chat_id=?", (chat_id,))
        cur = conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    return cur.rowcount > 0


RUN_STATES = ("", "running", "done", "needs_input", "error", "stopped")


def set_run_state(chat_id: str, state: str | None, unseen: bool | int | None = None) -> bool:
    """채팅의 실행 상태 기록(2026-09-04). state=None 이면 상태는 그대로 두고 unseen 만 바꾼다(읽음 처리).
    updated_at 은 건드리지 않는다(목록 정렬·'최근' 표시에 영향 없음)."""
    # Record a chat's run state (2026-09-04). state=None leaves the state alone and only changes unseen
    # (mark-as-read). updated_at is untouched (no effect on ordering / 'recent' display).
    sets, args = [], []
    if state is not None:
        if state not in RUN_STATES:
            raise ValueError(f"unknown run_state: {state}")
        sets.append("run_state = ?")
        args.append(state)
    if unseen is not None:
        sets.append("unseen = ?")
        args.append(1 if unseen else 0)
    if not sets:
        return False
    args.append(chat_id)
    with _conn() as conn:
        cur = conn.execute(f"UPDATE chats SET {', '.join(sets)} WHERE id = ?", args)
    return cur.rowcount > 0


def reset_running_chats() -> int:
    """서버 기동 시: 이전 프로세스가 남긴 run_state='running' 행을 'stopped'(unseen=0) 로 리셋. 리셋 건수 반환.
    unseen=0 — 재기동으로 끊긴 실행에 '완료' 아이콘을 띄우지 않는다(리뷰 반영)."""
    # On boot: reset run_state='running' rows left by a previous process to 'stopped' (unseen=0). Returns the count.
    # unseen=0 — a run cut off by the restart must not show the 'done' badge (review fix).
    with _conn() as conn:
        cur = conn.execute("UPDATE chats SET run_state = 'stopped', unseen = 0 WHERE run_state = 'running'")
    return cur.rowcount


def add_message(chat_id: str, role: str, content: str, meta: dict | None = None) -> str:
    from app.run_context import MESSAGE_LANE
    if MESSAGE_LANE.get() == "explore":
        meta = {**(meta or {}), "execution_lane": "explore"}
    msg_id = "m_" + uuid.uuid4().hex[:12]
    with _conn() as conn:
        conn.execute(
            "INSERT INTO messages(id, chat_id, role, content, meta, created_at) VALUES(?, ?, ?, ?, ?, ?)",
            (msg_id, chat_id, role, content, json.dumps(meta, ensure_ascii=False) if meta else None, _now()),
        )
        conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (_now(), chat_id))
    return msg_id


def last_message(chat_id: str) -> dict | None:
    """채팅의 마지막 메시지(역할 무관) — 스트림 전후 비교로 "이번 실행이 저장한 답변"을 식별하는 데 쓴다."""
    # The chat's last message (any role) — compared before/after a stream to identify the answer this run saved.
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM messages WHERE chat_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1", (chat_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["meta"] = json.loads(d["meta"]) if d["meta"] else None
    return d


def update_message_meta(msg_id: str, patch: dict) -> bool:
    """메시지 meta에 키를 병합(얕은 병합) — 실행 트레이스(kind/trace)처럼 저장 후에 확정되는 값용.
    pipeline.py는 무수정 원칙이라 저장 시점에 넣을 수 없는 메타를 chats_api가 뒤에서 덧붙인다."""
    # Shallow-merge keys into a message's meta — for values settled after the save (kind/trace).
    # pipeline.py is frozen, so chats_api appends such meta afterwards.
    with _conn() as conn:
        row = conn.execute("SELECT meta FROM messages WHERE id = ?", (msg_id,)).fetchone()
        if not row:
            return False
        meta = json.loads(row["meta"]) if row["meta"] else {}
        meta.update(patch)
        conn.execute("UPDATE messages SET meta = ? WHERE id = ?", (json.dumps(meta, ensure_ascii=False), msg_id))
    return True


def create_action(chat_id: str, kind: str, payload: dict, summary: str) -> str:
    """실행 확인 대기 액션 저장 — 실행은 오직 /api/actions/{id}/confirm을 통해서만."""
    # Store an action pending execution confirmation — execution only via /api/actions/{id}/confirm.
    action_id = "a_" + uuid.uuid4().hex[:12]
    with _conn() as conn:
        conn.execute(
            "INSERT INTO pending_actions(id, chat_id, kind, payload, summary, status, created_at)"
            " VALUES(?, ?, ?, ?, ?, 'pending', ?)",
            (action_id, chat_id, kind, json.dumps(payload, ensure_ascii=False), summary, _now()),
        )
    return action_id


def get_action(action_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM pending_actions WHERE id = ?", (action_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["payload"] = json.loads(d["payload"])
    return d


def update_action_payload(action_id: str, payload: dict) -> None:
    """액션 payload 갱신 — confirm 카드에서 사용자가 파라미터(받는 사람 등)를 수정해 실행할 때(2026-08-28)."""
    # Update an action's payload — when the user edits parameters (recipient, ...) on the confirm card.
    with _conn() as conn:
        conn.execute("UPDATE pending_actions SET payload = ? WHERE id = ?",
                     (json.dumps(payload, ensure_ascii=False), action_id))


def set_action_status(action_id: str, status: str) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE pending_actions SET status = ?, executed_at = ? WHERE id = ?",
            (status, _now() if status == "executed" else None, action_id),
        )


def _cache_key(kind: str, payload: str) -> str:
    return hashlib.sha256(f"{kind}\n{payload}".encode("utf-8")).hexdigest()


def gw_state_get() -> dict | None:
    """그룹웨어 시드 상태(메일·일정·할일) 로드 — 재시작 내구성(2026-08-28). 없으면 None(기본 시드 사용)."""
    # Load the groupware seed state (mail/events/tasks) — restart durability (2026-08-28). None = default seeds.
    try:
        with _conn() as conn:
            row = conn.execute("SELECT data FROM gw_state WHERE id = 1").fetchone()
        return json.loads(row["data"]) if row else None
    except Exception:  # noqa: BLE001 — 테이블 미생성 등은 기본 시드로 / missing table etc. → default seeds
        return None


def gw_state_set(data: dict) -> None:
    """그룹웨어 시드 상태 저장 — 뮤테이터가 상태를 바꿀 때마다 통째로 기록(단일행 JSON)."""
    # Persist the groupware seed state — written wholesale on every mutator call (single-row JSON).
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO gw_state(id, data, updated_at) VALUES(1, ?, ?)",
            (json.dumps(data, ensure_ascii=False), _now()),
        )


def gw_state_clear() -> None:
    """그룹웨어 시드 상태 초기화 — 기본 시드로 되돌린다(데모 리셋용)."""
    # Clear the groupware seed state — reverts to the default seeds (demo reset).
    with _conn() as conn:
        conn.execute("DELETE FROM gw_state WHERE id = 1")


def cache_get(kind: str, payload: str) -> str | None:
    """동일 입력에 대한 LLM 호출 결과 캐시 조회(의도판단/제목요약 등 호출 절약용)."""
    # Look up the cached LLM call result for identical input (to save calls for intent detection/title summarization, etc.).
    with _conn() as conn:
        row = conn.execute(
            "SELECT value FROM llm_cache WHERE cache_key = ?", (_cache_key(kind, payload),)
        ).fetchone()
    return row["value"] if row else None


def cache_set(kind: str, payload: str, value: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO llm_cache(cache_key, kind, value, created_at) VALUES(?, ?, ?, ?)",
            (_cache_key(kind, payload), kind, value, _now()),
        )


def list_messages(chat_id: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE chat_id = ? ORDER BY created_at ASC, rowid ASC", (chat_id,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["meta"] = json.loads(d["meta"]) if d["meta"] else None
        out.append(d)
    return out
