"""SQLite 실행 체크포인트와 외부 효과 중복 방지. 커넥터 인증 설정은 저장하지 않는다."""
import json
import uuid
from contextlib import closing
from app import db, kst


def _stamp():
    """updated_at = KST 'YYYY-MM-DD HH:MM:SS'(종전 SQLite 기본값과 같은 모양이되 UTC 대신 KST, 2026-10-06).
    모든 쓰기가 이 값을 직접 넣는다 — 옛 DB 테이블에 남은 기본값 절은 더는 쓰이지 않는다.
    updated_at as KST 'YYYY-MM-DD HH:MM:SS' (same shape as the former SQLite default, but KST instead of UTC, 2026-10-06).
    Every write passes this value explicitly, so the default clause left on older databases' tables is never used."""
    return kst.now().strftime("%Y-%m-%d %H:%M:%S")


def init_store():
    with closing(db._conn()) as conn, conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS execution_runs (
          id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, state TEXT NOT NULL,
          snapshot TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS execution_chat ON execution_runs(chat_id, updated_at);
        CREATE TABLE IF NOT EXISTS execution_effects (
          key TEXT PRIMARY KEY, state TEXT NOT NULL, result TEXT);
        CREATE TABLE IF NOT EXISTS execution_actions (
          action_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, task_id TEXT NOT NULL);
        """)


def create(chat_id, snapshot):
    init_store()
    rid = "run_" + uuid.uuid4().hex[:16]
    with closing(db._conn()) as conn, conn:
        conn.execute("INSERT INTO execution_runs(id,chat_id,state,snapshot,updated_at) VALUES(?,?,?,?,?)",
                     (rid, chat_id, "ready", json.dumps(snapshot, ensure_ascii=False), _stamp()))
    return get(rid)


def get(rid):
    init_store()
    with closing(db._conn()) as conn:
        row = conn.execute("SELECT * FROM execution_runs WHERE id=?", (rid,)).fetchone()
    if not row:
        return None
    return {**dict(row), "snapshot": json.loads(row["snapshot"])}


def pending(chat_id, lane="chat"):
    init_store()
    with closing(db._conn()) as conn:
        row = conn.execute("SELECT id FROM execution_runs WHERE chat_id=? AND state IN "
                           "('needs_input','needs_confirmation','interrupted') "
                           "AND COALESCE(json_extract(snapshot,'$.lane'),'chat')=? ORDER BY rowid DESC LIMIT 1",
                           (chat_id, lane)).fetchone()
    return get(row["id"]) if row else None


def save(run, status=None):
    if status:
        run["state"] = status
    with closing(db._conn()) as conn, conn:
        conn.execute("UPDATE execution_runs SET state=?,snapshot=?,updated_at=? WHERE id=?",
                     (run["state"], json.dumps(run["snapshot"], ensure_ascii=False), _stamp(), run["id"]))


def claim_run(rid):
    with closing(db._conn()) as conn, conn:
        return conn.execute("UPDATE execution_runs SET state='running' WHERE id=? AND state IN "
                            "('ready','needs_input','needs_confirmation','interrupted')", (rid,)).rowcount == 1


def effect_claim(key):
    init_store()
    with closing(db._conn()) as conn, conn:
        fresh = conn.execute("INSERT OR IGNORE INTO execution_effects(key,state) VALUES(?,'running')", (key,)).rowcount
        row = conn.execute("SELECT * FROM execution_effects WHERE key=?", (key,)).fetchone()
    return bool(fresh), dict(row)


def effect_finish(key, result):
    with closing(db._conn()) as conn, conn:
        conn.execute("UPDATE execution_effects SET state='completed',result=? WHERE key=?",
                     (json.dumps(result, ensure_ascii=False), key))


def effect_get(key):
    init_store()
    with closing(db._conn()) as conn:
        row = conn.execute("SELECT * FROM execution_effects WHERE key=?", (key,)).fetchone()
    return dict(row) if row else None


def link_action(action_id, run_id, task_id):
    with closing(db._conn()) as conn, conn:
        conn.execute("INSERT OR REPLACE INTO execution_actions VALUES(?,?,?)", (action_id, run_id, task_id))


def action_link(action_id):
    init_store()
    with closing(db._conn()) as conn:
        row = conn.execute("SELECT * FROM execution_actions WHERE action_id=?", (action_id,)).fetchone()
    return dict(row) if row else None


def recover():
    init_store()
    with closing(db._conn()) as conn, conn:
        conn.execute("UPDATE execution_runs SET state='interrupted' WHERE state='running'")


def cancel_workflow_runs(chat_id):
    """채팅의 미완 워크플로우 run(카드 대기·중단·준비) 전부 cancelled — 새 워크플로우 실행·모드 종료 때 낡은 카드가 /stream 의
    pending 분기를 오염하지 않게(2026-09-11). 취소한 run id 목록을 돌려준다(호출자가 카드 answered 처리)."""
    # Cancel every unfinished workflow run of the chat (waiting on a card / interrupted / ready) — so a new workflow run or
    # a mode exit never leaves a stale card for /stream's pending branch (2026-09-11). Returns the cancelled run ids.
    init_store()
    with closing(db._conn()) as conn, conn:
        rows = conn.execute("SELECT id FROM execution_runs WHERE chat_id=? AND state IN ('ready','needs_input','interrupted') "
                            "AND json_extract(snapshot,'$.kind')='workflow'", (chat_id,)).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            conn.execute(f"UPDATE execution_runs SET state='cancelled',updated_at=? WHERE id IN ({','.join('?' * len(ids))})", [_stamp(), *ids])
    return ids


def remove_chat(chat_id, conn=None):
    """대화 삭제 시 저장된 결과와 해당 실행의 효과 기록도 함께 삭제한다."""
    if conn is None:
        init_store()
        with closing(db._conn()) as connection, connection:
            remove_chat(chat_id, connection)
        return
    conn.execute("DELETE FROM execution_effects WHERE key IN ("
                     "SELECT 'action:' || a.action_id FROM execution_actions a JOIN execution_runs r ON r.id=a.run_id WHERE r.chat_id=?) "
                     "OR key IN (SELECT 'action:' || id FROM pending_actions WHERE chat_id=?) "
                     "OR substr(key,1,length(?))=? "
                     "OR EXISTS (SELECT 1 FROM execution_runs r WHERE r.chat_id=? "
                     "AND substr(execution_effects.key,1,length(r.id)+1)=r.id || ':')",
                 (chat_id, chat_id, f"schedule-notify:{chat_id}:", f"schedule-notify:{chat_id}:", chat_id))
    conn.execute("DELETE FROM execution_actions WHERE run_id IN (SELECT id FROM execution_runs WHERE chat_id=?)", (chat_id,))
    conn.execute("DELETE FROM execution_runs WHERE chat_id=?", (chat_id,))
