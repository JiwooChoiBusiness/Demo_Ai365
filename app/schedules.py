"""컬렉션 예약 실행 엔진 — 프롬프트 1개를 주기(한 번/매시간/매일/평일/매주/매월/사용자 지정)에 걸어 정해진 시각에 **그 컬렉션 안의
새 채팅**으로 자동 실행한다(2026-09-02, 사용자 확정 2026-09-01).

- 저장: coll_schedules(예약) 한 테이블. 예약 실행이 만든 채팅은 chats.sched 에 예약 id가 태그돼 프런트가 벨 아이콘을
  그린다. 구 coll_schedule_notifies(다중 알림 설정) 테이블은 폐지 — init 에서 DROP TABLE IF EXISTS 1회(멱등).
- 알림 실발송(5차, 2026-09-02 사용자 최종 확정): 예약마다 "메일로 알림 보내기" 토글 하나(notify_email, 기본 ON).
  켜져 있으면 실행 마감(_close) 직후 **소유자 본인("나")에게 무조건 메일 1통**(결과가 ok/doc/needs_input/429/error
  어느 것이든 — 취소 interrupted 만 제외, 퇴직·컬렉션 없음으로 실행 자체를 안 한 경우도 제외). 꺼져 있으면 아무것도
  하지 않는다(last_notify 도 갱신 안 함). 수신자는 notify.resolve_me(owner), 발송은 app.notify(Outlook COM → 실패 시
  가상 메일함 폴백) 가 맡고, 결과 요약은 coll_schedules.last_notify(JSON {at, to, ok, backend, error, subject}) 에
  저장한다. 알림 실패는 실행 결과(last_result)에 영향 없음.
- 리소스 선택(2차): 예약은 컬렉션 컴포저가 전송하는 것과 같은 두 값 — agents(분야 키 목록)·scope_files
  (스마트 파일 범위 객체) — 를 저장하고 실행 시 파이프라인에 그대로 넘긴다. 비면 자동 라우팅·전체 범위.
  smf_files(스마트 파일 키 목록)는 재편집 시 트리 체크 복원용으로만 저장한다.
- 반복 종료(2차): end_at('YYYY-MM-DD' | NULL). 다음 실행 시각이 end_at 23:59:59 를 넘으면 None → done.
- 반복 옵션(3차, 2026-09-02): rule = once(한 번)·hourly(매시간 :MM)·daily(매일)·weekdays(평일 월~금)·weekly(매주 days)·
  monthly(매월 mday, 그 달에 없는 날은 말일)·custom(freq daily/weekly/monthly + interval 1~12 + days|mday). custom 의
  간격 기준점(anchor)은 예약 created_at 의 날짜 — daily=anchor+k*interval 일, weekly=anchor 주(월요일 시작)로부터
  k*interval 주째의 days, monthly=anchor 월로부터 k*interval 개월째의 mday. interval=1 이면 프리셋과 같다.
  저장 컬럼 freq/interval/mday 는 PRAGMA→ALTER 로 추가하고, 구 rule CHECK(once/daily/weekly)가 남은 DB 는 테이블
  재생성 마이그레이션(새 테이블→복사→교체, FK OFF·트랜잭션, 멱등)으로 새 값을 받게 한다.
- 실행: FastAPI lifespan 이 폴링 루프(_loop)를 띄운다. 매 틱마다 만료 리스(lease)를 복구하고 due 예약을
  claim(선점) 한 뒤 fire 로 순차 실행한다. fire 는 chats_api.stream_chat 의 소비 루프를 헤드리스로 복제한다
  (pipeline.run_pipeline → confirm/clarify 는 '확인 필요'로 남기고 **자동 승인 절대 금지**, docgen 이벤트는
  포맷별 기본 스타일로 docgen.run_docgen 을 이어 소비). 제목 요약 LLM 호출은 하지 않는다(쿼터·루프 차단 회피).
  실행 중 60초마다 리스를 연장(하트비트 태스크 — fire 시작 시 띄우고 finally 에서 취소)하고, 종료(취소) 시에는
  running 행을 즉시 되돌린다. _fire_inner 는 진입 시 행을 재조회해 status='running' 이고 리스가 유효할 때만 진행한다
  (리스 만료로 복구된 행의 유령 실행 방지).
- 놓친 회차 = 건너뜀: 기동 시 next_run_at 이 10분 이상 지난 반복 예약(once 외)은 다음 회차로 전진한다.
  once 는 그대로 두어 첫 틱에 1회 실행된다.
- 시각: next_run_at/run_at/리스/last_run_at 은 **KST(+09:00) 벽시계 기준 naive ISO**(now_kst()/now_kst_str(), 2026-09-03) — 서버 시계 타임존 무관.
- env: SCHED_ENABLED('1' 기본, '0'이면 루프 미기동) · SCHED_POLL_SEC(폴링 간격 초, 기본 10).
- 순환 임포트: collections_store 가 이 모듈을 지연 임포트하므로, 이 모듈은 collections_store·pipeline 등을
  함수 안에서만 지연 임포트한다(상단 임포트는 db · kst 만).
"""
# Collection scheduled-run engine — runs one prompt on a rule (once/hourly/daily/weekdays/weekly/monthly/custom) at the set time as a NEW
# CHAT inside that collection (2026-09-02; user decision 2026-09-01).
#
# - Storage: the single coll_schedules table. Chats created by a run carry chats.sched = schedule id so the front
#   end can draw a bell icon. The old coll_schedule_notifies (multi-notify settings) table is retired — init runs
#   DROP TABLE IF EXISTS once (idempotent).
# - Real notification delivery (round 5, 2026-09-02 final user decision): each schedule has ONE "email me when it
#   runs" toggle (notify_email, default ON). When on, right after the run closes (_close) exactly ONE mail ALWAYS
#   goes to the owner ("me") (whatever the result — ok/doc/needs_input/429/error; only a cancelled 'interrupted'
#   run and runs that never started — retired owner / missing collection — are excluded). When off, nothing happens
#   (last_notify is not touched either). Recipients come from notify.resolve_me(owner); delivery lives in app.notify
#   (Outlook COM → virtual-mailbox fallback); a summary is stored in coll_schedules.last_notify
#   (JSON {at, to, ok, backend, error, subject}). A delivery failure never affects last_result.
# - Resource selection (round 2): a schedule stores the same two values the collection composer sends —
#   agents (field keys) and scope_files (smart-file scope object) — and passes them to the pipeline
#   unchanged at run time. Empty = auto routing / full scope. smf_files (smart-file keys) is stored only
#   to restore the tree checks when the schedule is edited again.
# - Repeat end (round 2): end_at ('YYYY-MM-DD' | NULL). A next run past end_at 23:59:59 → None → done.
# - Repeat options (round 3, 2026-09-02): rule = once · hourly (every hour at :MM) · daily · weekdays (Mon–Fri) ·
#   weekly (days) · monthly (mday; a day missing in that month → last day) · custom (freq daily/weekly/monthly +
#   interval 1–12 + days|mday). The custom interval anchor is the schedule's created_at date — daily = anchor +
#   k*interval days, weekly = the days of the k*interval-th week from the anchor week (Monday start), monthly =
#   mday of the k*interval-th month from the anchor month. interval=1 equals the preset. The freq/interval/mday
#   columns are added via PRAGMA→ALTER; a DB still carrying the old rule CHECK (once/daily/weekly) is migrated by
#   table recreation (new table → copy → swap, FK OFF, in a transaction, idempotent) so the new values are accepted.
# - Execution: the FastAPI lifespan starts a polling loop (_loop). Each tick recovers expired leases,
#   claims due schedules and fires them sequentially. fire replicates chats_api.stream_chat's consumer loop
#   headlessly (pipeline.run_pipeline → confirm/clarify leave 'needs_input' and are NEVER auto-approved;
#   a docgen event continues into docgen.run_docgen with per-format defaults). No title-summary LLM call
#   (quota / event-loop protection). The lease is extended every 60 s (a heartbeat task started when fire
#   begins and cancelled in its finally) while running, and a cancelled run (shutdown) reverts its running
#   row immediately. _fire_inner re-reads the row on entry and proceeds only while status='running' with a
#   live lease (no ghost run of a row already recovered after lease expiry).
# - Missed runs are SKIPPED: at startup, repeating (non-once) rows whose next_run_at is >10 min in the past advance
#   to the next occurrence. 'once' rows are left alone and fire on the first tick.
# - Time: next_run_at/run_at/leases/last_run_at are naive ISO strings on the KST (+09:00) wall clock (now_kst()/now_kst_str(), 2026-09-03) — independent of the server clock's zone.
# - env: SCHED_ENABLED ('1' default; '0' = loop not started) · SCHED_POLL_SEC (poll interval, default 10).
# - Circular imports: collections_store lazily imports this module, so this module imports
#   collections_store/pipeline/etc. only inside functions (top-level imports are db and kst only).

import asyncio
import calendar
import json
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

from app import db, kst

logger = logging.getLogger("ai365.scheduler")
if not logger.handlers:
    # 스케줄러는 백그라운드라 uvicorn 액세스 로그에 안 잡힌다 — INFO 핸들러 1개를 직접 단다(중복 방지 propagate=False)
    # The scheduler runs in the background (no uvicorn access log) — attach one INFO handler (no propagation).
    _h = logging.StreamHandler()
    _h.setLevel(logging.INFO)
    _fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    # 로그 시각도 서버 시간대와 무관하게 KST 로 찍는다 / log timestamps are KST regardless of the server zone
    _fmt.converter = kst.struct_time
    _h.setFormatter(_fmt)
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _poll_sec() -> float:
    """SCHED_POLL_SEC 파싱 — 비정상 값이면 기본 10초(최소 1초)."""
    # Parse SCHED_POLL_SEC — malformed values fall back to 10 s (minimum 1 s).
    try:
        return max(1.0, float(os.getenv("SCHED_POLL_SEC", "10") or 10))
    except (TypeError, ValueError):
        return 10.0


SCHED_ENABLED = os.getenv("SCHED_ENABLED", "1").strip() != "0"
SCHED_POLL_SEC = _poll_sec()
LEASE_MINUTES = 20          # running 선점 리스 — 만료되면 다음 틱이 복구 / running lease; recovered when expired
HEARTBEAT_SEC = 60          # 실행 중 리스 연장 주기 / lease-extension period while running
CLAIM_ADVANCE_MINUTES = 1   # 선점 시 next_run_at 전진 기준(now+1분) / next_run_at advance base at claim
MISSED_GRACE_MINUTES = 10   # 기동 시 이보다 오래 지난 daily/weekly 회차는 건너뜀 / startup skip threshold
RETRY_BACKOFF_MINUTES = 5   # 실행기 오류로 소진 안 한 once 의 재시도 간격 / retry gap for an unconsumed once after an executor error
DUE_BATCH = 3               # 틱당 최대 실행 수 / max runs per tick

RULES = ("once", "hourly", "daily", "weekdays", "weekly", "monthly", "custom")
FREQS = ("daily", "weekly", "monthly")   # custom 의 빈도 / custom frequencies
# 예약 시각 기준 = KST(+09:00) 고정(2026-09-03 사용자 확정) — 서버 시계의 타임존과 무관하게 KST 벽시계로 계산·저장한다.
# KST 는 서머타임이 없어 고정 오프셋이 정확하고 tzdata 의존성이 없다. 저장 형식은 종전과 같은 naive ISO(초 단위).
# 2026-10-06 부터 앱 공통 도우미(app.kst)를 쓰고, 아래 세 이름은 기존 호출부를 위한 별칭으로 남긴다.
# Schedule clock = fixed KST (+09:00) (user decision 2026-09-03) — computed and stored on the KST wall clock regardless
# of the server clock's zone. KST has no DST, so a fixed offset is exact and needs no tzdata. Storage stays naive ISO.
# Since 2026-10-06 the shared helper (app.kst) is used; the three names below stay as aliases for existing callers.
KST = kst.KST


def now_kst() -> datetime:
    """현재 KST 벽시계(naive) / current KST wall-clock time (naive)."""
    return kst.now()


def now_kst_str() -> str:
    """KST 현재 시각 ISO(초 단위) / KST now as ISO seconds."""
    return now_kst().isoformat(timespec="seconds")


MAX_INTERVAL = 12                        # custom 간격 상한 / custom interval cap
WEEKDAYS = [0, 1, 2, 3, 4]               # 평일(월~금) 고정 days / fixed days for 'weekdays' (Mon–Fri)
SCOPES = ("자동", "사내", "외부")
STATUSES = ("active", "paused", "running", "done")
NOTIFY_TIMEOUT_SEC = 90     # 알림 1건 발송 대기 상한(Outlook COM 멈춤 방어) / per-mail delivery wait cap (guards a hung Outlook COM)
AGENT_KEYS = ("knowledge", "data", "work")   # 컴포저 routable 키(groupware 는 자동 의도판단 전용) / composer routable keys (groupware = auto intent only)
SCOPE_FILE_LISTS = ("knowledge_files", "data_tables", "data_bi")   # scope_files 의 리스트 키 / list keys of scope_files
MAX_MESSAGE = 2000
MAX_PER_COLL = 10
MAX_FILE_KEYS = 200         # smf_files·scope_files 각 리스트 상한 / per-list cap for smf_files / scope_files
INST_CAP_DOCGEN = 500       # docgen 자동 생성에 넘기는 컬렉션 지침 길이 / collection-instruction cap passed to docgen
TITLE_CAP = 28

_UNSET = object()           # create(next_run=...) 생략 표지 / sentinel for an omitted create(next_run=...)

_RX_ONCE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
_RX_HM = re.compile(r"^\d{2}:\d{2}$")
_RX_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ─────────────────────────────────────────────────────────────────────────────
# 테이블
# Tables
# ─────────────────────────────────────────────────────────────────────────────

# coll_schedules 정의 — CREATE 와 CHECK 재생성 마이그레이션이 같은 본문을 쓴다(테이블명만 치환)
# coll_schedules definition — shared by CREATE and the CHECK-recreation migration (only the table name is substituted)
_SCHEDULES_TABLE_BODY = """(
  id TEXT PRIMARY KEY,
  coll_id TEXT REFERENCES coll_collections(id) ON DELETE CASCADE,
  owner TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL DEFAULT '',
  message TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT '자동' CHECK(scope IN ('자동','사내','외부')),
  rule TEXT NOT NULL CHECK(rule IN ('once','hourly','daily','weekdays','weekly','monthly','custom')),
  run_at TEXT NOT NULL,
  days TEXT NOT NULL DEFAULT '[]',
  next_run_at TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','running','done')),
  prior_status TEXT NOT NULL DEFAULT 'active',
  lease_until TEXT,
  last_run_at TEXT,
  last_chat_id TEXT,
  last_result TEXT NOT NULL DEFAULT '',
  agents TEXT NOT NULL DEFAULT '[]',
  scope_files TEXT NOT NULL DEFAULT '{}',
  smf_files TEXT NOT NULL DEFAULT '[]',
  flow_id TEXT NOT NULL DEFAULT '',        -- 2026-09-11 폐지(워크플로우 예약) — 호환용 잔존 / retired (workflow schedules), kept for compatibility
  flow_name TEXT NOT NULL DEFAULT '',      -- 2026-09-11 폐지 / retired
  flow_query TEXT NOT NULL DEFAULT '',     -- 2026-09-11 폐지 / retired
  connectors TEXT NOT NULL DEFAULT '[]',   -- 2026-09-11 폐지(예약 커넥터) / retired (schedule connectors)
  end_at TEXT,
  freq TEXT NOT NULL DEFAULT '',
  interval INTEGER NOT NULL DEFAULT 1,
  mday INTEGER,
  last_notify TEXT,
  notify_email INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)"""

_SCHEDULES_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_coll_sched_due ON coll_schedules(status, next_run_at);
CREATE INDEX IF NOT EXISTS idx_coll_sched_coll ON coll_schedules(coll_id, created_at);
"""


def _migrate_schedule_cols(conn) -> None:
    """기존 DB 의 coll_schedules 에 2차(agents·scope_files·smf_files·end_at)·3차(freq·interval·mday)·4차(last_notify)·
    5차(notify_email) 컬럼을 추가한다 — db._migrate_chats_coll 패턴."""
    # Add the round-2 (agents / scope_files / smf_files / end_at), round-3 (freq / interval / mday), round-4
    # (last_notify) and round-5 (notify_email) columns to an existing DB — same pattern as db._migrate_chats_coll.
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(coll_schedules)").fetchall()}
    for name, ddl in (("agents", "TEXT NOT NULL DEFAULT '[]'"),
                      ("scope_files", "TEXT NOT NULL DEFAULT '{}'"),
                      ("smf_files", "TEXT NOT NULL DEFAULT '[]'"),
                      ("flow_id", "TEXT NOT NULL DEFAULT ''"),
                      ("flow_name", "TEXT NOT NULL DEFAULT ''"),
                      ("flow_query", "TEXT NOT NULL DEFAULT ''"),
                      ("connectors", "TEXT NOT NULL DEFAULT '[]'"),
                      ("end_at", "TEXT"),
                      ("freq", "TEXT NOT NULL DEFAULT ''"),
                      ("interval", "INTEGER NOT NULL DEFAULT 1"),
                      ("mday", "INTEGER"),
                      ("last_notify", "TEXT"),
                      ("notify_email", "INTEGER NOT NULL DEFAULT 1")):
        if name not in cols:
            conn.execute(f"ALTER TABLE coll_schedules ADD COLUMN {name} {ddl}")  # noqa: S608 — 상수 / constants


def _drop_notifies_table(conn) -> None:
    """폐지된 다중 알림 테이블 coll_schedule_notifies(+인덱스) 삭제 — 없으면 아무 일도 없다(멱등). rule CHECK 재생성보다
    먼저 호출해 부모 교체 시 자식 FK 를 신경 쓰지 않아도 되게 한다."""
    # Drop the retired multi-notify table coll_schedule_notifies (+ its index) — no-op when absent (idempotent).
    # Called before the rule CHECK recreation so the parent swap has no child FK to worry about.
    conn.execute("DROP INDEX IF EXISTS idx_coll_sched_notify")
    conn.execute("DROP TABLE IF EXISTS coll_schedule_notifies")


def _migrate_schedule_rule_check(conn) -> bool:
    """구 rule CHECK(once/daily/weekly)가 남은 coll_schedules 를 재생성한다 — SQLite 는 ALTER 로 CHECK 를 못 바꾸므로
    새 테이블 생성→복사→교체(db._migrate_chats_scope 패턴). sqlite_master 의 sql 에 'hourly' 가 있으면 이미 새 정의(멱등).
    PRAGMA foreign_keys=OFF 로 DROP 의 연쇄 삭제를 막고 legacy_alter_table=ON 으로 rename 이 다른 정의를 건드리지 않게
    한 채 한 트랜잭션에서 교체한다(자식 coll_schedule_notifies 는 폐지돼 앞서 DROP 됐지만 보호 PRAGMA 는 그대로 둔다).
    executescript 는 진행 중 트랜잭션을 먼저 커밋하므로 PRAGMA 가 트랜잭션 밖에서 적용된다. 반환: 재생성 수행 여부."""
    # Recreate coll_schedules when it still carries the old rule CHECK (once/daily/weekly) — SQLite cannot ALTER a
    # CHECK, so create new → copy → swap (db._migrate_chats_scope pattern). 'hourly' present in the sqlite_master
    # sql means the new definition is already in place (idempotent). foreign_keys=OFF prevents DROP from cascading,
    # legacy_alter_table=ON keeps the rename from rewriting other definitions, and the swap runs in one transaction
    # (the child coll_schedule_notifies is retired and dropped beforehand; the guard PRAGMAs are kept). executescript
    # commits any pending transaction first, so the PRAGMAs apply outside a transaction. Returns whether a recreation happened.
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='coll_schedules'").fetchone()
    sql = (row["sql"] if row else "") or ""
    # 재생성 조건: 구 rule CHECK(hourly 없음) 또는 구 coll_id NOT NULL(6차 2026-09-07 — 컬렉션 없는 예약 허용)
    # Recreate when: the old rule CHECK (no 'hourly') or the old coll_id NOT NULL (round 6, 2026-09-07 — collection-less schedules)
    if not sql or ("'hourly'" in sql and "coll_id TEXT NOT NULL" not in sql):
        return False
    old_cols = [r["name"] for r in conn.execute("PRAGMA table_info(coll_schedules)").fetchall()]
    conn.execute("DROP TABLE IF EXISTS coll_schedules_new")
    conn.execute("CREATE TABLE coll_schedules_new" + _SCHEDULES_TABLE_BODY)
    new_cols = [r["name"] for r in conn.execute("PRAGMA table_info(coll_schedules_new)").fetchall()]
    conn.execute("DROP TABLE coll_schedules_new")
    common = ", ".join(c for c in new_cols if c in old_cols)   # 컬럼명은 PRAGMA 결과(상수) / column names from PRAGMA (constants)
    conn.executescript(
        "PRAGMA foreign_keys=OFF;\n"
        "PRAGMA legacy_alter_table=ON;\n"
        "BEGIN;\n"
        "CREATE TABLE coll_schedules_new" + _SCHEDULES_TABLE_BODY + ";\n"
        f"INSERT INTO coll_schedules_new({common}) SELECT {common} FROM coll_schedules;\n"  # noqa: S608
        "DROP TABLE coll_schedules;\n"
        "ALTER TABLE coll_schedules_new RENAME TO coll_schedules;\n"
        "COMMIT;\n"
        "PRAGMA legacy_alter_table=OFF;\n"
        "PRAGMA foreign_keys=ON;\n"
    )
    logger.info("coll_schedules rule CHECK 재생성 마이그레이션 완료(컬럼 %d개 복사)", len(new_cols))
    return True


def init_schedules() -> None:
    """coll_collections 가 먼저 있어야 한다(FK) — main.py 에서 collections_store.init_collections() 뒤에 호출.
    순서: CREATE IF NOT EXISTS → 컬럼 ALTER 마이그레이션 → 폐지된 coll_schedule_notifies DROP → rule CHECK 재생성(필요 시)
    → 인덱스(재생성 후에도 보장)."""
    # coll_collections must exist first (FK) — main.py calls this after collections_store.init_collections().
    # Order: CREATE IF NOT EXISTS → column ALTER migration → drop the retired coll_schedule_notifies → rule CHECK
    # recreation (when needed) → indexes (ensured after a recreation too).
    with db._conn() as conn:
        conn.executescript("CREATE TABLE IF NOT EXISTS coll_schedules" + _SCHEDULES_TABLE_BODY + ";\n")
        _migrate_schedule_cols(conn)
        _drop_notifies_table(conn)
        _migrate_schedule_rule_check(conn)
        conn.executescript(_SCHEDULES_INDEXES)


# ─────────────────────────────────────────────────────────────────────────────
# 시각 계산
# Time computation
# ─────────────────────────────────────────────────────────────────────────────

def parse_run_at(rule: str, run_at: str) -> tuple:
    """run_at 형식 검증 — once='YYYY-MM-DDTHH:MM' → datetime, 그 외 반복='HH:MM' → (h, m)(hourly 는 분만 쓴다). ValueError 로 지목."""
    # Validate run_at — once='YYYY-MM-DDTHH:MM' → datetime, every other rule 'HH:MM' → (h, m) (hourly uses the minute only). Raises ValueError.
    s = (run_at or "").strip()
    if rule == "once":
        if not _RX_ONCE.match(s):
            raise ValueError("실행 날짜/시각 형식이 올바르지 않습니다 (YYYY-MM-DDTHH:MM)")
        try:
            return (datetime.strptime(s, "%Y-%m-%dT%H:%M"),)
        except ValueError:
            raise ValueError("실행 날짜/시각이 올바르지 않습니다") from None
    if not _RX_HM.match(s):
        raise ValueError("실행 시각 형식이 올바르지 않습니다 (HH:MM)")
    h, m = int(s[:2]), int(s[3:5])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("실행 시각이 올바르지 않습니다")
    return (h, m)


def parse_end_at(end_at: str | None) -> datetime | None:
    """end_at('YYYY-MM-DD' | None/빈값) → 그날 23:59:59 datetime | None. 형식 오류는 ValueError."""
    # end_at ('YYYY-MM-DD' | None/empty) → that day's 23:59:59 as datetime | None. Format errors raise ValueError.
    s = (end_at or "").strip()
    if not s:
        return None
    if not _RX_DATE.match(s):
        raise ValueError("반복 종료 날짜 형식이 올바르지 않습니다 (YYYY-MM-DD)")
    try:
        d = datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        raise ValueError("반복 종료 날짜가 올바르지 않습니다") from None
    return d.replace(hour=23, minute=59, second=59, microsecond=0)


def norm_interval(v) -> int:
    """custom 간격 정규화 — 정수 1~MAX_INTERVAL 로 클램프(비정상 값은 1)."""
    # Normalize the custom interval — clamped to 1..MAX_INTERVAL (malformed → 1).
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 1
    return min(max(n, 1), MAX_INTERVAL)


def norm_mday(v) -> int | None:
    """월의 일(1~31) 정규화 — 범위 밖·비정상 값은 None."""
    # Normalize the day of month (1..31) — out of range / malformed → None.
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 31 else None


def _anchor_date(anchor, after: datetime) -> date:
    """custom 간격 기준일 — created_at 문자열('YYYY-MM-DD…') 또는 datetime/date; None·파싱 실패면 after 의 날짜."""
    # Custom-interval anchor date — created_at string ('YYYY-MM-DD…') or datetime/date; None / unparsable → after's date.
    if isinstance(anchor, datetime):
        return anchor.date()
    if isinstance(anchor, date):
        return anchor
    if isinstance(anchor, str) and _RX_DATE.match(anchor.strip()[:10]):
        try:
            return datetime.strptime(anchor.strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    return after.date()


def _month_day(year: int, month: int, mday: int) -> date:
    """그 달의 mday — 없는 날(31일·2월 30일 등)은 말일로 당긴다."""
    # mday of that month — a day the month lacks (the 31st, Feb 30 …) is pulled to the last day.
    return date(year, month, min(mday, calendar.monthrange(year, month)[1]))


def _effective_rule(rule: str, freq: str, interval) -> tuple[str, int]:
    """실행 규칙 정규화 — custom 은 (freq, interval), weekdays 는 ('weekly', 1)(days 는 호출자가 고정), 그 외 (rule, 1).
    custom 의 freq 가 비정상이면 ValueError."""
    # Normalize the effective rule — custom → (freq, interval); weekdays → ('weekly', 1) (days fixed by the caller);
    # anything else → (rule, 1). A custom with a bad freq raises ValueError.
    if rule == "custom":
        if freq not in FREQS:
            raise ValueError("사용자 지정 반복은 빈도(daily/weekly/monthly)를 골라야 합니다")
        return freq, norm_interval(interval)
    if rule == "weekdays":
        return "weekly", 1
    return rule, 1


def compute_next_run(rule: str, run_at: str, days: list | None, after: datetime | None = None,
                     end_at: str | None = None, freq: str = "", interval: int = 1, mday: int | None = None,
                     anchor=None) -> str | None:
    """다음 실행 시각(KST 벽시계 naive, isoformat 초단위). 기준 시각(after 기본값)은 항상 KST(app.kst)라 서버 시계의 시간대와 무관하다.

    once     → 그 시각(초 ':00'); after 이하(이미 지남)면 None. end_at 무시.
    hourly   → after 이후 첫 'HH:MM' 경계(매 시 MM분 — run_at 의 분만 사용).
    daily    → 오늘 HH:MM 이 after 보다 뒤면 오늘, 아니면 내일.
    weekdays → 월~금 HH:MM(days 는 [0..4] 로 고정, 넘어온 값 무시).
    weekly   → days(0=월…6=일) 중 다음 해당 요일(오늘 포함; 오늘 시각이 지났으면 그다음). days 비면 None.
    monthly  → 매월 mday 일 HH:MM(그 달에 없는 날은 말일). mday 없으면 ValueError.
    custom   → freq(daily/weekly/monthly) × interval(1~12). 기준일 anchor(created_at 날짜; None 이면 after 날짜):
               daily = anchor + k*interval 일, weekly = anchor 주(월요일 시작)로부터 k*interval 주째의 days,
               monthly = anchor 월로부터 k*interval 개월째의 mday. interval=1 이면 프리셋과 같다.
    end_at   → once 외 모든 규칙의 결과가 end_at 23:59:59 를 넘으면 None(반복 종료).
    형식 오류는 ValueError.
    """
    # Next run time (naive KST wall clock, isoformat seconds). `after` defaults to KST now (app.kst), so the server clock's zone does not matter.
    # once → that time (':00' seconds); None if <= after; end_at ignored. hourly → the first 'HH:MM' boundary
    # after `after` (every hour at MM — only the minute of run_at is used). daily → today at HH:MM if still ahead,
    # else tomorrow. weekdays → Mon–Fri at HH:MM (days forced to [0..4]). weekly → the next matching weekday in
    # days (0=Mon…6=Sun; today counts if the time is still ahead); empty days → None. monthly → mday of every
    # month at HH:MM (a missing day → last day); no mday → ValueError. custom → freq × interval from the anchor
    # (created_at date; None → after's date): daily = anchor + k*interval days, weekly = the days of the
    # k*interval-th week from the anchor week (Monday start), monthly = mday of the k*interval-th month from the
    # anchor month; interval=1 equals the preset. end_at → any non-once result past end_at 23:59:59 → None
    # (repeat ended). Format errors raise ValueError.
    after = after or now_kst()
    parsed = parse_run_at(rule, run_at)
    if rule == "once":
        dt = parsed[0].replace(second=0, microsecond=0)
        return dt.isoformat(timespec="seconds") if dt > after else None
    if rule not in RULES:
        raise ValueError("반복 규칙이 올바르지 않습니다")
    cap = parse_end_at(end_at)
    h, m = parsed
    eff, step = _effective_rule(rule, freq, interval)
    anchor_d = _anchor_date(anchor, after)
    base = after.replace(hour=h, minute=m, second=0, microsecond=0)
    cand = None
    if eff == "hourly":
        c = after.replace(minute=m, second=0, microsecond=0)
        cand = c if c > after else c + timedelta(hours=1)
    elif eff == "daily":
        if step == 1:
            cand = base if base > after else base + timedelta(days=1)
        else:
            # anchor + k*step 일 — k0 = after 날짜까지의 경과일 // step 부터 두 후보면 충분 / two candidates from k0 suffice
            k0 = max(0, (after.date() - anchor_d).days // step)
            for k in (k0, k0 + 1, k0 + 2):
                c = datetime.combine(anchor_d + timedelta(days=k * step), base.time())
                if c > after:
                    cand = c
                    break
    elif eff == "weekly":
        wanted = WEEKDAYS if rule == "weekdays" else sorted({int(d) for d in (days or []) if 0 <= int(d) <= 6})
        if not wanted:
            return None
        if step == 1:
            for i in range(0, 8):
                c = base + timedelta(days=i)
                if c.weekday() in wanted and c > after:
                    cand = c
                    break
        else:
            # anchor 주(월요일)로부터 주 번호가 step 의 배수인 주의 days — 하루씩 최대 step*7+7 일 탐색
            # days in weeks whose index from the anchor Monday is a multiple of step — scanned day by day, at most step*7+7 days
            monday = anchor_d - timedelta(days=anchor_d.weekday())
            start = max(after.date(), monday)
            for i in range(0, step * 7 + 8):
                d = start + timedelta(days=i)
                widx = (d - monday).days // 7
                if widx % step == 0 and d.weekday() in wanted:
                    c = datetime.combine(d, base.time())
                    if c > after:
                        cand = c
                        break
    elif eff == "monthly":
        md = norm_mday(mday)
        if md is None:
            raise ValueError("매월 반복은 날짜(일)를 1~31 사이로 골라야 합니다")
        # anchor 월로부터 step 개월 간격의 달 — k0 부터 몇 달만 보면 된다 / months step apart from the anchor month — a few from k0 suffice
        a_idx = anchor_d.year * 12 + (anchor_d.month - 1)
        n_idx = after.year * 12 + (after.month - 1)
        k0 = max(0, (n_idx - a_idx) // step)
        for k in (k0, k0 + 1, k0 + 2):
            idx = a_idx + k * step
            c = datetime.combine(_month_day(idx // 12, idx % 12 + 1, md), base.time())
            if c > after:
                cand = c
                break
    if cand is None:
        return None
    if cap is not None and cand > cap:
        return None
    return cand.isoformat(timespec="seconds")


def _rule_kwargs(row) -> dict:
    """저장 행 → compute_next_run 의 반복 옵션 인자(freq/interval/mday/anchor=created_at)."""
    # Stored row → compute_next_run's repeat-option kwargs (freq / interval / mday / anchor=created_at).
    keys = row.keys()
    return {"freq": (row["freq"] if "freq" in keys else "") or "",
            "interval": norm_interval(row["interval"] if "interval" in keys else 1),
            "mday": norm_mday(row["mday"] if "mday" in keys else None),
            "anchor": row["created_at"]}


def _days_list(raw) -> list[int]:
    try:
        v = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except Exception:  # noqa: BLE001
        v = []
    out = []
    for d in v if isinstance(v, list) else []:
        try:
            di = int(d)
        except (TypeError, ValueError):
            continue
        if 0 <= di <= 6 and di not in out:
            out.append(di)
    return sorted(out)


# ─────────────────────────────────────────────────────────────────────────────
# 리소스 선택 정규화 — 컴포저 계약(agents / scope_files / smf_files)과 같은 형태로만 저장
# Resource-selection normalization — stored only in the composer's shape (agents / scope_files / smf_files)
# ─────────────────────────────────────────────────────────────────────────────

def _str_list(v, cap: int = MAX_FILE_KEYS) -> list[str]:
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:  # noqa: BLE001
            v = []
    out: list[str] = []
    for x in v if isinstance(v, list) else []:
        if isinstance(x, str) and x.strip() and x not in out:
            out.append(x)
    return out[:cap]


def norm_agents(v) -> list[str]:
    """분야 키 목록 — AGENT_KEYS 만, 순서 유지·중복 제거. 비면 [](자동 라우팅)."""
    # Field keys — AGENT_KEYS only, order kept, de-duplicated. Empty = [] (auto routing).
    return [k for k in _str_list(v, 10) if k in AGENT_KEYS]


def norm_scope_files(v) -> dict:
    """scope_files — pipeline._clean_scope_files 와 같은 형태({knowledge_files, data_tables, data_bi, work})."""
    # scope_files — the same shape as pipeline._clean_scope_files ({knowledge_files, data_tables, data_bi, work}).
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:  # noqa: BLE001
            v = {}
    sf = v if isinstance(v, dict) else {}
    out = {k: _str_list(sf.get(k)) for k in SCOPE_FILE_LISTS}
    out["work"] = bool(sf.get("work"))
    return out


def norm_smf_files(v) -> list[str]:
    return _str_list(v)


def scope_files_is_empty(sf: dict) -> bool:
    return not any(sf.get(k) for k in SCOPE_FILE_LISTS) and not sf.get("work")


# ─────────────────────────────────────────────────────────────────────────────
# 조회/CRUD
# Reads / CRUD
# ─────────────────────────────────────────────────────────────────────────────

def _owner_names() -> dict:
    """구성원 no → 이름(access.list_members). 실패 시 빈 dict(이름 대신 id 노출)."""
    # Member no → name via access.list_members. Empty dict on failure (id shown instead).
    try:
        from app import access  # 지연 임포트 / lazy import
        return {str(m.get("no")): str(m.get("name") or "") for m in access.list_members()}
    except Exception as e:  # noqa: BLE001
        logger.warning("구성원 조회 실패 — owner_name 생략: %s", e)
        return {}


def _owner_name(owner: str, names: dict) -> str:
    owner = (owner or "").strip()
    if not owner:
        return "관리자"
    return names.get(owner) or owner


def _notify_email_flag(row) -> bool:
    """notify_email 컬럼 → bool. 컬럼이 없거나(구 행 재생성 전) NULL 이면 기본 True."""
    # notify_email column → bool. Missing column (pre-migration row) or NULL → default True.
    if "notify_email" not in row.keys():
        return True
    v = row["notify_email"]
    return True if v is None else bool(v)


def _last_notify_dict(raw) -> dict | None:
    """last_notify 컬럼(JSON 문자열) → dict | None(없음·파싱 실패)."""
    # last_notify column (JSON string) → dict | None (absent / unparsable).
    if not raw:
        return None
    try:
        v = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    return v if isinstance(v, dict) else None


def _sched_dict(row, names: dict) -> dict:
    return {
        "id": row["id"], "coll_id": row["coll_id"] or None, "owner": row["owner"] or "",
        # 컬렉션 이름(6차) — list_all 의 LEFT JOIN 결과에만 있음, 컬렉션 없는 예약은 '' / collection name (round 6) — only from list_all's LEFT JOIN
        "coll_name": (row["coll_name"] if "coll_name" in row.keys() else None) or "",
        "owner_name": _owner_name(row["owner"], names),
        "name": row["name"] or "", "message": row["message"], "scope": row["scope"],
        "rule": row["rule"], "run_at": row["run_at"], "days": _days_list(row["days"]),
        "end_at": row["end_at"] or None,
        # 반복 옵션(3차) — custom 의 freq/interval, monthly·custom-monthly 의 mday / repeat options (round 3)
        "freq": row["freq"] or "", "interval": norm_interval(row["interval"]), "mday": norm_mday(row["mday"]),
        "next_run_at": row["next_run_at"], "status": row["status"],
        "last_run_at": row["last_run_at"], "last_chat_id": row["last_chat_id"],
        "last_result": row["last_result"] or "",
        # 메일 알림 토글(5차) — 켜져 있으면 실행 마감 후 소유자 본인에게 1통 / email-me toggle (round 5) — one mail to the owner after a run
        "notify_email": _notify_email_flag(row),
        # 마지막 알림 발송 요약(4차) — {at, to, ok, backend, error, subject} | None / last delivery summary (round 4)
        "last_notify": _last_notify_dict(row["last_notify"] if "last_notify" in row.keys() else None),
        # 리소스 선택(2차) — 컴포저가 stream 바디로 보내는 agents/scope_files 와 같은 형태 + 트리 복원용 smf_files
        # Resource selection (round 2) — same shape as the composer's stream-body agents/scope_files + smf_files for tree restore
        "agents": norm_agents(row["agents"]),
        "scope_files": norm_scope_files(row["scope_files"]),
        "smf_files": norm_smf_files(row["smf_files"]),
        # (flow_id/flow_name/flow_query/connectors 컬럼은 2026-09-11 폐지 — 응답에 싣지 않는다 / retired columns are not exposed)
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def list_for_coll(coll_id: str, names: dict | None = None) -> list[dict]:
    """컬렉션의 예약 목록 — GET .../schedules 용. names(구성원 이름 사전)를 넘기면 재조회하지 않는다."""
    # Schedules of one collection — for GET .../schedules. Pass `names` (member-name dict) to skip the lookup.
    with db._conn() as conn:
        rows = conn.execute("SELECT * FROM coll_schedules WHERE coll_id=? ORDER BY created_at, rowid",
                            (coll_id,)).fetchall()
    if not rows:
        return []
    if names is None:
        names = _owner_names()
    return [_sched_dict(r, names) for r in rows]


def list_for_colls(coll_ids: list[str]) -> dict[str, list[dict]]:
    """여러 컬렉션의 예약을 한 번에(예약 1쿼리 + 이름 사전 1회) — GET /api/collections 의 N+1 제거."""
    # Schedules of many collections at once (1 schedule query + 1 name lookup) — removes the N+1 of GET /api/collections.
    ids = [c for c in dict.fromkeys(coll_ids or []) if c]
    out: dict[str, list[dict]] = {c: [] for c in ids}
    if not ids:
        return out
    with db._conn() as conn:
        q = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT * FROM coll_schedules WHERE coll_id IN ({q}) ORDER BY created_at, rowid", ids  # noqa: S608 — 플레이스홀더만 / placeholders only
        ).fetchall()
    if not rows:
        return out
    names = _owner_names()
    for r in rows:
        out.setdefault(r["coll_id"], []).append(_sched_dict(r, names))
    return out


def get(sched_id: str) -> dict | None:
    """단건 — 컬렉션 이름(coll_name)까지 LEFT JOIN 으로 채운다(6차; 예약 작업 페이지·모달이 list_all 과 같은 모양을 기대)"""
    # Single row — coll_name filled via LEFT JOIN (round 6; the schedules page/modal expect the list_all shape)
    with db._conn() as conn:
        r = conn.execute("SELECT s.*, c.name AS coll_name FROM coll_schedules s LEFT JOIN coll_collections c ON c.id = s.coll_id"
                         " WHERE s.id=?", (sched_id,)).fetchone()
    if not r:
        return None
    return _sched_dict(r, _owner_names())


def _get_raw(sched_id: str):
    with db._conn() as conn:
        return conn.execute("SELECT * FROM coll_schedules WHERE id=?", (sched_id,)).fetchone()


def count_for_coll(coll_id: str) -> int:
    """컬렉션당 상한(MAX_PER_COLL) 계산용 — 완료(done) 예약은 세지 않는다."""
    # For the per-collection cap (MAX_PER_COLL) — done schedules are not counted.
    with db._conn() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM coll_schedules WHERE coll_id=? AND status!='done'",
                            (coll_id,)).fetchone()["n"]


# ── 6차(2026-09-07): 예약 메뉴 — 컬렉션 없는 예약·전체 목록·실행 히스토리·보관 정리 ──
# ── Round 6 (2026-09-07): schedules menu — collection-less schedules, global list, run history, retention ──
MAX_GLOBAL = 30      # 컬렉션 없는 예약 상한 / cap for collection-less schedules
KEEP_RUNS = 30       # 예약당 보관하는 결과 채팅 수 / result chats kept per schedule


def count_global() -> int:
    """컬렉션 없는 예약 수(done 제외) / collection-less schedules (excluding done)"""
    with db._conn() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM coll_schedules WHERE coll_id IS NULL AND status!='done'").fetchone()["n"]


def list_all(active_only: bool = False) -> list[dict]:
    """전체 예약(컬렉션 이름 포함, 최근 생성 순) — 예약 작업 페이지 목록. active_only=True 면 done 제외."""
    # Every schedule (with the collection name, newest first) — the schedules page list. active_only drops done rows.
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT s.*, c.name AS coll_name FROM coll_schedules s LEFT JOIN coll_collections c ON c.id = s.coll_id"
            + (" WHERE s.status!='done'" if active_only else "") + " ORDER BY s.created_at DESC, s.rowid DESC"
        ).fetchall()
    if not rows:
        return []
    names = _owner_names()
    return [_sched_dict(r, names) for r in rows]


def run_history(sched_id: str, limit: int = KEEP_RUNS) -> list[dict]:
    """예약이 만든 결과 채팅 목록(최근순) — {id, title, created_at, result, run_state}. 사이드바에서는 숨겨지고 여기서만 연다."""
    # Result chats created by the schedule (newest first) — hidden from the sidebar, opened from here only.
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at, run_state, sched_result FROM chats WHERE sched=? ORDER BY created_at DESC LIMIT ?",
            (sched_id, int(limit))).fetchall()
    return [{"id": r["id"], "title": r["title"], "created_at": r["created_at"], "run_state": r["run_state"] or "",
             "result": r["sched_result"] or ""} for r in rows]


def _prune_runs(sched_id: str, keep: int = KEEP_RUNS) -> int:
    """예약당 결과 채팅을 최근 keep 개만 남기고 오래된 것을 삭제(메시지 포함). 삭제 건수 반환."""
    # Keep only the newest `keep` result chats per schedule; older ones are deleted with their messages.
    from app import execution_store
    execution_store.init_store()
    with db._conn() as conn:
        old = conn.execute("SELECT id FROM chats WHERE sched=? ORDER BY created_at DESC, rowid DESC LIMIT -1 OFFSET ?",
                           (sched_id, int(keep))).fetchall()
        ids = [r["id"] for r in old if not conn.execute(
            "SELECT 1 FROM execution_runs WHERE chat_id=? AND state IN "
            "('ready','running','needs_input','needs_confirmation','interrupted')", (r["id"],)).fetchone()]
        for cid in ids:
            db.delete_chat(cid)
    if ids:
        logger.info("예약 %s 결과 채팅 정리: %d개 삭제(보관 %d)", sched_id, len(ids), keep)
    return len(ids)


def norm_days_for(rule: str, freq: str, days) -> list[int]:
    """규칙별 days 정규화 — weekly/custom-weekly 는 입력 days, weekdays 는 [0..4] 고정, 그 외 []."""
    # Per-rule days normalization — weekly / custom-weekly keep the given days, weekdays force [0..4], others [].
    if rule == "weekdays":
        return list(WEEKDAYS)
    if rule == "weekly" or (rule == "custom" and freq == "weekly"):
        return _days_list(days)
    return []


def create(coll_id: str, owner: str, name: str, message: str, scope: str, rule: str, run_at: str,
           days: list | None, enabled: bool, notify_email: bool = True, *,
           agents: list | None = None, scope_files: dict | None = None, smf_files: list | None = None,
           end_at: str | None = None, freq: str = "", interval: int = 1, mday: int | None = None,
           next_run: str | None | object = _UNSET) -> dict:
    """예약 생성 — 검증(형식·상한·과거 시각)은 schedules_api 가 끝냈다는 전제. next_run 은 API 가 검증 시 계산한 값을
    그대로 받아 저장한다(여기서 재계산하면 분 경계에서 검증 통과 후 None 이 되는 레이스). 인자를 생략하면 지금 기준 계산
    (custom 의 anchor = 지금 날짜 = created_at 날짜). end_at 은 once 외 규칙에만 저장. freq/interval 은 custom 에만,
    mday 는 monthly·custom-monthly 에만 저장(그 외 ''/1/NULL). next 가 None(반복 종료 등)이면 status='done'.
    notify_email(기본 True) = "메일로 알림 보내기" 토글."""
    # Create a schedule — validation (format/caps/past time) done by schedules_api. `next_run` is the value the API
    # computed during validation, stored as-is (recomputing here could flip to None at a minute boundary after the
    # check passed). When omitted it is computed from now (custom anchor = today = the created_at date). end_at is
    # stored for every non-once rule; freq/interval only for custom, mday only for monthly / custom-monthly
    # (otherwise ''/1/NULL). next None (repeat ended, ...) → status='done'. notify_email (default True) = the
    # "email me when it runs" toggle.
    sid = "cs_" + uuid.uuid4().hex[:10]
    now = now_kst_str()
    freq_v = freq if (rule == "custom" and freq in FREQS) else ""
    interval_v = norm_interval(interval) if rule == "custom" else 1
    mday_v = norm_mday(mday) if (rule == "monthly" or freq_v == "monthly") else None
    days_l = norm_days_for(rule, freq_v, days)
    end_v = (end_at or "").strip() or None
    if rule == "once":
        end_v = None
    if next_run is _UNSET:
        next_run = compute_next_run(rule, run_at, days_l, end_at=end_v, freq=freq_v, interval=interval_v,
                                    mday=mday_v, anchor=now)
    status = "active" if enabled else "paused"
    if next_run is None:
        status = "done"
    with db._conn() as conn:
        conn.execute(
            "INSERT INTO coll_schedules(id, coll_id, owner, name, message, scope, rule, run_at, days,"
            " next_run_at, status, prior_status, agents, scope_files, smf_files,"
            " end_at, freq, interval, mday, notify_email, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, coll_id, (owner or "").strip(), (name or "").strip(), message, scope, rule,
             run_at.strip(), json.dumps(days_l), next_run, status, status,
             json.dumps(norm_agents(agents)), json.dumps(norm_scope_files(scope_files), ensure_ascii=False),
             json.dumps(norm_smf_files(smf_files), ensure_ascii=False),
             end_v, freq_v, interval_v, mday_v, 1 if notify_email else 0, now, now),
        )
    logger.info("예약 생성: %s coll=%s rule=%s next=%s agents=%s notify_email=%s", sid, coll_id, rule, next_run,
                norm_agents(agents), bool(notify_email))
    return get(sid)


def update(sched_id: str, patch: dict) -> dict | None:
    """예약 수정 — patch 는 화이트리스트 컬럼만(name/message/scope/rule/run_at/days/end_at/freq/interval/mday/status/
    next_run_at/prior_status/agents/scope_files/smf_files/notify_email). 빈 patch 면 저장 없이 현재 값을 돌려준다."""
    # Update a schedule — patch limited to whitelisted columns; an empty patch returns the current row unchanged.
    allowed = ("name", "message", "scope", "rule", "run_at", "days", "end_at", "freq", "interval", "mday", "status",
               "next_run_at", "prior_status", "agents", "scope_files", "smf_files", "notify_email", "coll_id")
    fields = {k: v for k, v in patch.items() if k in allowed}
    if "notify_email" in fields:
        fields["notify_email"] = 1 if fields["notify_email"] else 0
    if "days" in fields:
        fields["days"] = json.dumps(_days_list(fields["days"]))
    if "freq" in fields:
        fields["freq"] = fields["freq"] if fields["freq"] in FREQS else ""
    if "interval" in fields:
        fields["interval"] = norm_interval(fields["interval"])
    if "mday" in fields:
        fields["mday"] = norm_mday(fields["mday"])
    if "agents" in fields:
        fields["agents"] = json.dumps(norm_agents(fields["agents"]))
    if "scope_files" in fields:
        fields["scope_files"] = json.dumps(norm_scope_files(fields["scope_files"]), ensure_ascii=False)
    if "smf_files" in fields:
        fields["smf_files"] = json.dumps(norm_smf_files(fields["smf_files"]), ensure_ascii=False)
    if "end_at" in fields:
        fields["end_at"] = (fields["end_at"] or "").strip() or None
    with db._conn() as conn:
        exists = conn.execute("SELECT 1 FROM coll_schedules WHERE id=?", (sched_id,)).fetchone()
        if not exists:
            return None
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(
                f"UPDATE coll_schedules SET {sets}, updated_at=? WHERE id=?",  # noqa: S608 — 키는 화이트리스트 / whitelisted keys
                (*fields.values(), now_kst_str(), sched_id),
            )
    return get(sched_id)


def delete(sched_id: str) -> bool:
    """삭제 — running 중이어도 허용. fire 의 마감 UPDATE 는 WHERE status='running' 이라 rowcount 0 으로 조용히 끝난다.
    예약에 종속된 결과 채팅(chats.sched, 6차)도 함께 지운다 — 사이드바에서 숨겨져 있어 예약이 없어지면 닿을 길이 없다."""
    # Delete — allowed even while running; fire's closing UPDATE (WHERE status='running') then affects 0 rows and exits
    # quietly. The schedule's result chats (chats.sched, round 6) go with it — hidden from the sidebar, they would be unreachable.
    with db._conn() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM chats WHERE sched=?", (sched_id,)).fetchall()]
        for cid in ids:
            db.delete_chat(cid)
        cur = conn.execute("DELETE FROM coll_schedules WHERE id=?", (sched_id,))
    if ids:
        logger.info("예약 %s 삭제 — 결과 채팅 %d개 함께 삭제", sched_id, len(ids))
    return cur.rowcount > 0


# ─────────────────────────────────────────────────────────────────────────────
# 엔진 — 선점/복구/실행
# Engine — claim / recover / fire
# ─────────────────────────────────────────────────────────────────────────────

_sem: asyncio.Semaphore | None = None
_bg_tasks: set = set()   # run-now 태스크 참조 보관(GC 방지) / keep references to run-now tasks
_active_fires: dict[str, asyncio.Task] = {}


async def delete_with_runs(sched_id: str) -> bool:
    task = _active_fires.get(sched_id)
    if task is not None and task is not asyncio.current_task():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    from app import runs
    for chat in run_history(sched_id, limit=1000000):
        for key in (chat["id"], chat["id"] + ":explore"):
            active = runs.stop(key)
            if active:
                await runs.settle(active)
    return await asyncio.to_thread(delete, sched_id)


def _semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(1)   # fire 동시 실행 억제(LLM 쿼터 보호) / one fire at a time (quota protection)
    return _sem


def _recover_stale() -> int:
    """리스가 만료된 running 행을 이전 상태로 복구(서버 재시작·크래시 후). once 이고 next_run_at 이 이미 소진(NULL)된
    행은 'done' 으로 닫는다(active 로 되돌리면 영원히 안 도는 좀비가 되므로). 리스가 살아 있는 행은 다른 프로세스가
    실행 중일 수 있으므로(공유 DB) 건드리지 않는다."""
    # Restore running rows whose lease expired (after restart/crash) to their prior status. A 'once' row whose
    # next_run_at was already consumed (NULL) closes as 'done' (reviving it as active would leave a zombie).
    # Rows with a live lease may belong to another process (shared DB) and are left alone.
    now = now_kst_str()
    with db._conn() as conn:
        cur = conn.execute(
            "UPDATE coll_schedules SET status=CASE WHEN rule='once' AND next_run_at IS NULL THEN 'done'"
            " ELSE prior_status END, lease_until=NULL, updated_at=?"
            " WHERE status='running' AND (lease_until IS NULL OR lease_until < ?)",
            (now, now),
        )
    if cur.rowcount:
        logger.info("만료 리스 복구: %d건", cur.rowcount)
    return cur.rowcount


def _skip_missed() -> int:
    """놓친 회차 건너뜀(기동 시) — active 인 반복 예약(once 외) 중 next_run_at 이 10분 이상 지난 행을 다음 회차로 전진.
    end_at 을 넘으면 done. once 는 그대로 둔다(첫 틱에 1회 실행)."""
    # Skip missed runs (startup) — active repeating rows (non-once) whose next_run_at is >10 min past advance to the
    # next occurrence; past end_at → done. 'once' rows are left alone (they fire on the first tick).
    now_dt = now_kst()
    threshold = (now_dt - timedelta(minutes=MISSED_GRACE_MINUTES)).isoformat(timespec="seconds")
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT id, rule, run_at, days, end_at, freq, interval, mday, created_at FROM coll_schedules"
            " WHERE status='active' AND rule!='once' AND next_run_at IS NOT NULL AND next_run_at < ?",
            (threshold,)).fetchall()
        n = 0
        for r in rows:
            try:
                nxt = compute_next_run(r["rule"], r["run_at"], _days_list(r["days"]), after=now_dt, end_at=r["end_at"],
                                       **_rule_kwargs(r))
            except ValueError:
                nxt = None
            if nxt is None:
                conn.execute("UPDATE coll_schedules SET status='done', next_run_at=NULL, updated_at=? WHERE id=?",
                             (now_kst_str(), r["id"]))
            else:
                conn.execute("UPDATE coll_schedules SET next_run_at=?, updated_at=? WHERE id=?",
                             (nxt, now_kst_str(), r["id"]))
            n += 1
    if n:
        logger.info("놓친 회차 건너뜀: %d건", n)
    return n


def _due_ids() -> list[str]:
    now = now_kst_str()
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT id FROM coll_schedules WHERE status='active' AND next_run_at IS NOT NULL AND next_run_at<=?"
            " ORDER BY next_run_at LIMIT ?", (now, DUE_BATCH)).fetchall()
    return [r["id"] for r in rows]


def claim(sched_id: str, force: bool = False) -> bool:
    """실행 선점 — status='running' + 리스 20분 + next_run_at 전진(once 는 NULL, end_at 초과면 NULL). force(지금 실행)는
    paused 도 받고 next_run_at 을 건드리지 않는다. 조건 불일치(이미 running 등)면 False."""
    # Claim a run — status='running' + 20-min lease + advance next_run_at (once → NULL; past end_at → NULL). force (run now)
    # also accepts paused and leaves next_run_at untouched. False when the row no longer qualifies (e.g. already running).
    row = _get_raw(sched_id)
    if not row:
        return False
    now_dt = now_kst()
    now = now_dt.isoformat(timespec="seconds")
    lease = (now_dt + timedelta(minutes=LEASE_MINUTES)).isoformat(timespec="seconds")
    if force:
        next_run = row["next_run_at"]
    elif row["rule"] == "once":
        next_run = None   # 한 번 예약은 이 실행으로 소진 / a one-off is consumed by this run
    else:
        try:
            next_run = compute_next_run(row["rule"], row["run_at"], _days_list(row["days"]),
                                        after=now_dt + timedelta(minutes=CLAIM_ADVANCE_MINUTES),
                                        end_at=row["end_at"], **_rule_kwargs(row))
        except ValueError:
            next_run = None
    statuses = "('active','paused')" if force else "('active')"
    with db._conn() as conn:
        # SET 의 prior_status=status 는 갱신 전 값으로 평가된다(SQLite 표준 의미) / evaluated on the pre-update row
        cur = conn.execute(
            f"UPDATE coll_schedules SET status='running', prior_status=status, lease_until=?, next_run_at=?,"
            f" updated_at=? WHERE id=? AND status IN {statuses} AND (? OR next_run_at<=?)",  # noqa: S608 — 상수 문자열 / constant literal
            (lease, next_run, now, sched_id, 1 if force else 0, now),
        )
    return cur.rowcount == 1


def _extend_lease(sched_id: str) -> bool:
    """리스 하트비트 — running 행의 lease_until 을 now+LEASE 로 연장."""
    # Lease heartbeat — push a running row's lease_until to now+LEASE.
    lease = (now_kst() + timedelta(minutes=LEASE_MINUTES)).isoformat(timespec="seconds")
    with db._conn() as conn:
        cur = conn.execute("UPDATE coll_schedules SET lease_until=? WHERE id=? AND status='running'",
                           (lease, sched_id))
    return cur.rowcount == 1


async def _heartbeat(sched_id: str) -> None:
    """리스 하트비트 태스크 — fire 시작 시 띄워 HEARTBEAT_SEC 마다 _extend_lease. 세마포어 대기 중에도 돈다(대기가
    길어져 리스가 만료되는 일 방지). 연장이 0건(삭제·리스 만료 복구)이면 조용히 멈춘다. fire 의 finally 가 취소한다."""
    # Lease heartbeat task — started when fire begins; calls _extend_lease every HEARTBEAT_SEC, including while
    # waiting on the semaphore (a long wait must not let the lease expire). Stops quietly once an extension hits
    # 0 rows (deleted / recovered after lease expiry). Cancelled by fire's finally.
    while True:
        await asyncio.sleep(HEARTBEAT_SEC)
        try:
            ok = await asyncio.to_thread(_extend_lease, sched_id)
        except Exception:  # noqa: BLE001
            logger.warning("리스 연장 실패: %s", sched_id, exc_info=True)
            continue
        if not ok:
            logger.info("예약 %s: 리스 연장 0건(행 없음 — 삭제 또는 리스 만료 복구됨) — 하트비트 중단", sched_id)
            return


def _restore_once_next(row, now_dt: datetime, backoff: bool) -> tuple[str, str | None]:
    """소진되지 않은 once 의 next_run_at 복원 — run_at 이 미래면 그 시각. 이미 지났으면 backoff=True 일 때 now+5분
    (실행기 오류 재시도), False 면 None 유지(퇴직 일시정지 — 재개 시 API 가 422 로 지목). 반환 (status, next_run)."""
    # Restore an unconsumed once's next_run_at — the run_at time when still ahead. When already past: now+5 min
    # with backoff=True (executor-error retry), or None with backoff=False (retired pause — a resume gets 422
    # from the API). Returns (status, next_run).
    status = row["prior_status"] or "active"
    try:
        restored = parse_run_at("once", row["run_at"])[0]
    except ValueError:
        return "done", None
    if restored > now_dt:
        return status, restored.isoformat(timespec="seconds")
    if backoff:
        return status, (now_dt + timedelta(minutes=RETRY_BACKOFF_MINUTES)).isoformat(timespec="seconds")
    return status, None


def _close(sched_id: str, last_result: str, chat_id: str | None, status_override: str | None = None,
           consume_once: bool = True) -> bool:
    """마감 — 리스 해제 + 결과 기록. running 이 아니면(삭제·리스 만료 복구) 0건.

    status = override | once→'done'(소진) | prior_status.
    once: 지금 실행(force)으로 돌았고 예정 회차가 남아 있으면(next_run_at not None) prior_status 로 닫고 next_run 을
    유지한다(_interrupt 와 같은 규칙). next_run_at 이 NULL(선점 때 소진)이면 'done'.
    consume_once=False(실행기 오류·컬렉션 없음·퇴직): once 를 소진하지 않고 선점 때 NULL 이 된 next_run_at 을 run_at
    시각으로 복원. 이미 지났으면 실행기 오류는 now+5분 백오프(매 틱 재시도 방지), 퇴직(status_override) 은 NULL 유지.
    반복 규칙(once 외): next_run_at 이 비었거나 지났으면(지금 실행·end_at 도달) compute_next_run(after=now+1분) 으로 전진 —
    연속 2회 실행 방지. 전진 결과가 None(end_at 초과)이면 'done'. status_override 가 있으면 그 상태로 닫는다.
    """
    # Close — release the lease + record the result. 0 rows if not running (deleted / recovered after lease expiry).
    # status = override | 'done' for a consumed once | prior_status.
    # once: after a run-now (force) with a pending occurrence (next_run_at not None) close as prior_status and keep
    # next_run (same rule as _interrupt); a NULL next_run_at (consumed at claim) → 'done'.
    # consume_once=False (executor error / missing collection / retired): do not consume a once — restore
    # next_run_at (NULLed at claim) to the run_at time; when already past, an executor error backs off now+5 min
    # (no per-tick retry) while a retired pause (status_override) keeps NULL. Repeating rules (non-once): an empty/past
    # next_run_at (run-now, end_at reached) advances via compute_next_run(after=now+1 min) — prevents two
    # back-to-back runs; None (past end_at) → 'done'. status_override closes with that status.
    now_dt = now_kst()
    now = now_dt.isoformat(timespec="seconds")
    result = last_result[:220]
    row = _get_raw(sched_id)
    if not row or row["status"] != "running":
        return False
    rule = row["rule"]
    next_run = row["next_run_at"]
    if status_override:
        status = status_override
        if not consume_once and rule == "once" and next_run is None:
            _, next_run = _restore_once_next(row, now_dt, backoff=False)
    elif not consume_once:
        status = row["prior_status"] or "active"
        if rule == "once" and next_run is None:
            status, next_run = _restore_once_next(row, now_dt, backoff=True)
    elif rule == "once":
        # force(지금 실행)로 돌아 예정 회차가 남았으면 유지, 선점 때 소진(NULL)됐으면 done — _interrupt 와 동일
        # Kept when a run-now left the pending occurrence; done when consumed (NULL) at claim — same as _interrupt
        if next_run is None:
            status = "done"
        else:
            status = row["prior_status"] or "active"
    else:
        status = row["prior_status"] or "active"
        if next_run is None or next_run <= now:
            try:
                next_run = compute_next_run(rule, row["run_at"], _days_list(row["days"]),
                                            after=now_dt + timedelta(minutes=CLAIM_ADVANCE_MINUTES),
                                            end_at=row["end_at"], **_rule_kwargs(row))
            except ValueError:
                next_run = None
            if next_run is None:
                status = "done"
    with db._conn() as conn:
        cur = conn.execute(
            "UPDATE coll_schedules SET status=?, next_run_at=?, lease_until=NULL, last_run_at=?, last_chat_id=?,"
            " last_result=?, updated_at=? WHERE id=? AND status='running'",
            (status, next_run, now, chat_id, result, now, sched_id))
    return cur.rowcount == 1


def _interrupt(sched_id: str, chat_id: str | None) -> bool:
    """취소(종료·--reload) 시 running 행 즉시 되돌리기 — 리스 만료를 기다리지 않는다. 소진된 once 는 done."""
    # Revert a running row right away on cancellation (shutdown / --reload) — no waiting for lease expiry. A consumed once → done.
    now = now_kst_str()
    with db._conn() as conn:
        cur = conn.execute(
            "UPDATE coll_schedules SET status=CASE WHEN rule='once' AND next_run_at IS NULL THEN 'done'"
            " ELSE prior_status END, lease_until=NULL, last_result='interrupted',"
            " last_chat_id=COALESCE(?, last_chat_id), updated_at=? WHERE id=? AND status='running'",
            (chat_id, now, sched_id))
    return cur.rowcount == 1


def _is_quota_error(es: str) -> bool:
    return ("429" in es or "RESOURCE_EXHAUSTED" in es or "쿨다운" in es or "quota" in es.lower())


async def fire(sched_id: str) -> None:
    """예약 1건 실행(선점된 행 전제) — 세마포어로 직렬화. try 가 세마포어 획득까지 감싸므로 대기 중 취소돼도 _interrupt 가
    돈다. 시작 시 하트비트 태스크(60초 주기 리스 연장)를 띄우고 finally 에서 취소한다. 취소되면 DB 를 즉시 되돌리고,
    실행기 오류면 소진 없이 닫는다."""
    # Run one claimed schedule — serialized by the semaphore. The try also wraps the semaphore acquisition, so a
    # cancel while waiting still runs _interrupt. A heartbeat task (lease extension every 60 s) starts here and is
    # cancelled in finally. On cancel revert the DB at once; on an executor error close without consuming.
    state: dict = {"chat_id": None}
    _active_fires[sched_id] = asyncio.current_task()
    hb_task = asyncio.create_task(_heartbeat(sched_id), name=f"ai365-sched-hb-{sched_id}")
    # 알림은 세마포어·하트비트 밖에서 보낸다(리뷰 지적: Outlook COM 지연이 다른 예약 실행·루프 틱을 막지 않게).
    # _fire_inner 는 마감(_close)이 실제로 이뤄졌을 때만 (result, chat_id, preview) 를 돌려준다.
    # Notifications go out outside the semaphore/heartbeat (review fix: Outlook COM delays must not stall other runs
    # or the loop tick). _fire_inner returns (result, chat_id, preview) only when _close really closed the row.
    notify_args = None
    try:
        async with _semaphore():
            notify_args = await _fire_inner(sched_id, state)
    except asyncio.CancelledError:
        try:
            _interrupt(sched_id, state["chat_id"])
        except Exception:  # noqa: BLE001
            logger.warning("취소 되돌리기 실패: %s", sched_id, exc_info=True)
        logger.info("예약 실행 취소(종료): %s — running 되돌림", sched_id)
        raise
    except Exception:  # noqa: BLE001 — 실행기 자체 오류도 루프를 죽이지 않는다 / never kills the loop
        logger.exception("예약 실행기 오류: %s", sched_id)
        closed = _close(sched_id, "error:실행기 오류", state["chat_id"], consume_once=False)
        # 실행기 오류도 "실행 마감" — 채팅이 만들어졌다면(실행에 들어간 뒤 실패) 알림을 보낸다 / an executor error is
        # still a closed run — notify when a chat exists (the run had started)
        if closed and state.get("chat_id"):
            notify_args = ("error:실행기 오류", state["chat_id"], state.get("answer_preview") or "")
            try:
                db.set_chat_sched_result(state["chat_id"], "error:실행기 오류")
            except Exception:  # noqa: BLE001
                pass
    finally:
        hb_task.cancel()
        _active_fires.pop(sched_id, None)
    if notify_args:
        try:
            await _notify_after_run(sched_id, *notify_args)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — 알림 실패는 실행 결과에 영향 없음 / a notification failure never affects the run
            logger.warning("알림 발송 단계 오류: %s", sched_id, exc_info=True)


def _running_row(sched_id: str):
    """행 재조회 — status='running' 이고 lease_until 이 아직 유효할 때만 행을 돌려준다(그 외 None — 리스 만료로 복구·삭제된
    행의 유령 실행 방지)."""
    # Re-read the row — returned only while status='running' with a live lease_until (else None — no ghost run of a row
    # recovered after lease expiry or deleted).
    row = _get_raw(sched_id)
    if not row or row["status"] != "running":
        return None
    lease = row["lease_until"]
    return row if (lease and lease >= now_kst_str()) else None


# ─────────────────────────────────────────────────────────────────────────────
# 알림 발송(5차) — 마감 직후, notify_email 이 켜진 예약은 소유자 본인에게 무조건 1통
# Notification delivery (round 5) — right after close, one mail to the owner whenever notify_email is on
# ─────────────────────────────────────────────────────────────────────────────

def _coll_name(coll_id: str) -> str:
    """컬렉션 이름만 경량 조회 — 없으면 ''."""
    # Lightweight read of the collection name only — '' when missing (or no collection at all).
    if not coll_id:
        return ""
    with db._conn() as conn:
        r = conn.execute("SELECT name FROM coll_collections WHERE id=?", (coll_id,)).fetchone()
    return "" if r is None else (r["name"] or "")


def _set_last_notify(sched_id: str, summary: dict) -> bool:
    """last_notify 저장 — status 조건 없음(마감 뒤 호출되므로 running 이 아니다). 삭제된 행이면 0건."""
    # Store last_notify — no status condition (called after close, so the row is no longer running). 0 rows if deleted.
    with db._conn() as conn:
        cur = conn.execute("UPDATE coll_schedules SET last_notify=? WHERE id=?",
                           (json.dumps(summary, ensure_ascii=False), sched_id))
    return cur.rowcount == 1


async def _send_one(to: list[str], subject: str, body: str) -> dict:
    """notify.send_mail 을 스레드에서 NOTIFY_TIMEOUT_SEC 까지 기다린다. 시간 초과(Outlook COM 멈춤)면 그 사유를 기록하고
    가상 메일함으로 한 번 더 시도한다(backend='virtual(fallback)'). 어떤 예외도 밖으로 내지 않는다."""
    # Run notify.send_mail on a thread with a NOTIFY_TIMEOUT_SEC cap. On timeout (hung Outlook COM) record the reason
    # and retry once via the virtual mailbox (backend='virtual(fallback)'). Never raises.
    from app import notify   # 지연 임포트 / lazy import
    try:
        return await asyncio.wait_for(asyncio.to_thread(notify.send_mail, to, subject, body), NOTIFY_TIMEOUT_SEC)
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        first = f"timeout({NOTIFY_TIMEOUT_SEC}s) — Outlook COM 응답 없음 / no response"
        logger.warning("알림 발송 시간 초과 — 가상 메일함으로 폴백: %s", subject[:60])
        try:
            r = await asyncio.wait_for(asyncio.to_thread(notify.send_mail, to, subject, body, "virtual"), 15)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "backend": "virtual(fallback)", "error": first + " | virtual: " + str(e)[:200]}
        return {"ok": bool(r.get("ok")), "backend": "virtual(fallback)",
                "error": first + ((" | virtual: " + r["error"]) if r.get("error") else "")}
    except Exception as e:  # noqa: BLE001 — send_mail 은 예외를 안 던지지만 스레드 실패 등 방어 / defensive
        return {"ok": False, "backend": "?", "error": str(e)[:300]}


async def _notify_after_run(sched_id: str, result: str, chat_id: str | None, answer_preview: str) -> None:
    """마감 직후 알림 발송 — row.notify_email 이 꺼져 있으면 아무것도 하지 않는다(last_notify 도 갱신 안 함). 켜져 있으면
    수신자 = notify.resolve_me(owner) → 제목·본문 = notify.build_mail → _send_one(스레드) → 요약을 last_notify
    ({at, to, ok, backend, error, subject}) 에 저장. 실패는 logger.warning 만 — 실행 결과(last_result)에는 영향 없다.
    취소(CancelledError)는 그대로 전파."""
    # Deliver the notification right after close — nothing happens when row.notify_email is off (last_notify is not
    # touched). When on: recipients = notify.resolve_me(owner) → subject/body = notify.build_mail → _send_one (on a
    # thread) → summary stored in last_notify ({at, to, ok, backend, error, subject}). Failures only log a warning —
    # last_result is untouched. Cancellation propagates.
    try:
        from app import notify   # 지연 임포트 / lazy import
        row = await asyncio.to_thread(_get_raw, sched_id)
        if row is None:
            return   # 삭제됨 / deleted meanwhile
        if not _notify_email_flag(row):
            return   # 토글 꺼짐 — 발송도 기록도 없음 / toggle off — no mail, no record
        if notify.mail_backend() == "none":
            logger.info("예약 %s: SCHED_MAIL_BACKEND=none — 알림 발송 생략", sched_id)
            return
        sched = dict(row)
        if chat_id:
            from app import execution_store
            key = f"schedule-notify:{chat_id}:" + ("waiting" if result == "needs_input" else "final")
            fresh, _ = execution_store.effect_claim(key)
            if not fresh:
                return
        coll_name = await asyncio.to_thread(_coll_name, row["coll_id"])
        owner = (row["owner"] or "").strip()
        to = await asyncio.to_thread(notify.resolve_me, owner)
        subject, body = notify.build_mail(sched, coll_name, chat_id, result, answer_preview)
        r = await _send_one(to, subject, body)
        if chat_id:
            execution_store.effect_finish(key, r)
        if not r.get("ok"):
            logger.warning("예약 %s 알림 발송 실패(backend=%s): %s", sched_id, r.get("backend"), r.get("error"))
        summary = {"at": now_kst_str(), "to": to, "ok": bool(r.get("ok")), "backend": r.get("backend") or "",
                   "error": (r.get("error") or "")[:300], "subject": subject[:200]}
        await asyncio.to_thread(_set_last_notify, sched_id, summary)
        logger.info("예약 %s 알림 발송: ok=%s (backend=%s)", sched_id, summary["ok"], summary["backend"])
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — 알림 실패는 실행 결과에 영향 없음 / never affects the run result
        logger.warning("예약 %s 알림 처리 실패", sched_id, exc_info=True)


async def complete_resumed(chat_id: str, state: str, artifact: bool = False, run_id: str = "") -> None:
    """재개한 회차를 마감한다. 다른 회차의 결과와 다음 예약 시각은 보존한다."""
    chat = db.get_chat(chat_id)
    if not chat or not chat.get("sched") or not chat.get("sched_result"):
        return
    if run_id:
        # 결과 채팅에서 시작한 별도 후속 질문이 원래 예약 회차를 바꾸지 않는다.
        with db._conn() as conn:
            first = conn.execute("SELECT id FROM execution_runs WHERE chat_id=? ORDER BY rowid LIMIT 1", (chat_id,)).fetchone()
        if not first or first["id"] != run_id:
            return
    from app.execution_outcomes import schedule_result
    result = schedule_result(state, artifact)
    if result == chat["sched_result"]:
        return
    sid = chat["sched"]
    with db._conn() as conn:
        changed = conn.execute("UPDATE chats SET sched_result=? WHERE id=? AND sched_result=?",
                               (result, chat_id, chat["sched_result"])).rowcount
        if not changed:
            return
        conn.execute("UPDATE coll_schedules SET last_result=? WHERE id=? AND last_chat_id=? AND status!='running'",
                     (result, sid, chat_id))
    from app.run_context import history
    preview = next((m["content"] for m in reversed(history(chat_id)) if m["role"] == "assistant"), "")[:300]
    await _notify_after_run(sid, result, chat_id, preview)


def _coll_inst(coll_id: str) -> str | None:
    """컬렉션 지침(inst)만 경량 조회 — 없으면 None(파일 본문·예약까지 읽는 get_collection 을 쓰지 않는다)."""
    # Lightweight read of the collection instructions (inst) only — None when missing (avoids get_collection, which loads file bodies and schedules).
    with db._conn() as conn:
        r = conn.execute("SELECT inst FROM coll_collections WHERE id=?", (coll_id,)).fetchone()
    return None if r is None else (r["inst"] or "")


async def _fire_inner(sched_id: str, state: dict) -> None:
    # 지연 임포트 — 순환 임포트 회피(collections_store → schedules) + 무거운 파이프라인 모듈은 실행 시점에만
    # Lazy imports — avoid the circular import (collections_store → schedules); heavy pipeline modules only at run time
    from app import access, chats_api, cite, collections_store, docgen, flows, pipeline

    # 0) 세마포어 대기 뒤 재검증 — running 이 아니거나 리스가 만료됐으면(복구·삭제) 실행하지 않는다
    # 0) Re-validate after the semaphore wait — skip when no longer running or the lease expired (recovered / deleted)
    row = await asyncio.to_thread(_running_row, sched_id)
    if row is None:
        logger.info("예약 %s: running/유효 리스 상태가 아니라 실행 생략(행 없음 — 삭제 또는 리스 만료 복구됨)", sched_id)
        return
    # 컬렉션 없는 예약(6차, 2026-09-07)은 일반 채팅으로 실행 — 지침·파일 맥락 없이 자동 라우팅 / a collection-less schedule runs as a plain chat
    coll_id = row["coll_id"] or None
    coll_inst = (await asyncio.to_thread(_coll_inst, coll_id)) if coll_id else ""
    if coll_inst is None:
        _close(sched_id, "error:컬렉션이 없습니다", None, consume_once=False)
        return
    owner = (row["owner"] or "").strip()
    # 예약은 프롬프트만 실행한다(2026-09-11 — 워크플로우 예약·커넥터 폐지, 사용자 확정) / schedules run prompts only (2026-09-11)
    message = (row["message"] or "").strip()
    if not message:
        _close(sched_id, "error:프롬프트가 비어 있습니다", None, status_override="paused", consume_once=False)
        return
    scope = row["scope"] if row["scope"] in SCOPES else "자동"
    # 리소스 선택(2차) — 컴포저 stream 바디와 같은 형태로 파이프라인에 전달. 비면 자동 라우팅([])·전체 범위({}).
    # Resource selection (round 2) — passed to the pipeline in the composer's stream-body shape. Empty = auto routing ([]) / full scope ({}).
    agents = norm_agents(row["agents"])
    scope_files = norm_scope_files(row["scope_files"])

    # 1) 퇴직자 예약은 실행하지 않고 일시정지로 닫는다(once 는 소진하지 않음 — next_run_at 을 run_at 으로 복원, 과거면 NULL)
    # 1) A retired owner's schedule pauses instead of running (a once is not consumed — next_run_at restored to run_at, NULL if past)
    if owner.isdigit():
        try:
            members = await asyncio.to_thread(access.list_members)
        except Exception:  # noqa: BLE001
            members = []
        m = next((x for x in members if str(x.get("no")) == owner), None)
        if m and m.get("status") == "퇴직":
            logger.info("예약 %s: 소유자(no=%s) 퇴직 — 일시정지", sched_id, owner)
            _close(sched_id, "retired", None, status_override="paused", consume_once=False)
            return

    # 2) 헤드리스 채팅 생성 — 제목은 LLM 요약 없이 (이름 또는 프롬프트) 앞부분 / headless chat, no LLM title
    title = ((row["name"] or "").strip() or message.strip())[:TITLE_CAP]
    chat = db.create_chat(title, scope, coll=coll_id, sched=sched_id)
    chat_id = chat["id"]
    state["chat_id"] = chat_id   # 외부 예외·취소 마감에 전달 / handed to the outer error/cancel close
    db.add_message(chat_id, "user", message, meta={"kind": "scheduled", "schedule_id": sched_id})
    chat = db.get_chat(chat_id) or chat
    logger.info("예약 %s 실행 시작 → 채팅 %s (coll=%s, scope=%s, agents=%s, files=%s)", sched_id, chat_id, coll_id,
                scope, agents or "auto", "none" if scope_files_is_empty(scope_files) else "narrowed")

    # 3) 컬렉션 맥락(지침·파일·링크) / collection context
    try:
        instructions = (await asyncio.to_thread(collections_store.context_for, coll_id)) if coll_id else ""
    except Exception:  # noqa: BLE001
        logger.warning("컬렉션 맥락 조합 실패 — 재료 없이 진행", exc_info=True)
        instructions = ""

    # 4) 파이프라인 소비 — chats_api.stream_chat 의 루프를 헤드리스로 복제 / headless copy of stream_chat's loop
    trace = {"thinking": [], "tasks": [], "parallel": False, "status": {}, "lines": []}
    answer_id = None
    answer_text: list[str] = []
    enriched_sources = None
    result = "ok"
    docgen_ev = None
    gen = doc_stream = None
    try:
        gen = pipeline.run_pipeline(chat, message, scope, agents, instructions, owner, scope_files)
        async for ev in gen:
            chats_api._trace_collect(trace, ev)
            t = ev.get("type")
            if t == "execution_result":
                from app.execution_outcomes import schedule_result
                if ev["state"] != "running":
                    result = schedule_result(ev["state"], ev.get("artifact", False))
            elif t == "segment_start" and (ev.get("doc") or ev.get("replace")):
                answer_text = []
                enriched_sources = None
            elif t == "doc_meta":
                if result != "needs_input":
                    result = "doc"
            elif t == "token":
                answer_text.append(ev.get("text") or "")
            elif t == "done":
                if ev.get("message_id"):
                    answer_id = ev["message_id"]
                if ev.get("format") == "openui":
                    # OpenUI 답(2026-10-27): 토큰은 화면 프로그램 조각이라 알림 본문 미리보기는 평문(done.plain)으로 바꾸고,
                    # 본문 위치 각주(cite)는 붙이지 않는다(chats_api 와 같은 규칙)
                    # OpenUI answer (2026-10-27): the tokens are program fragments, so the mail preview uses done.plain, and no
                    # body-offset footnotes are attached (same rule as chats_api)
                    answer_text = [str(ev.get("plain") or "")]
                else:
                    try:
                        enriched_sources = cite.enrich_sources(ev.get("sources"), ev.get("references"),
                                                               "".join(answer_text))
                    except Exception:  # noqa: BLE001
                        logger.warning("각주 귀속 실패", exc_info=True)
            elif t in ("confirm", "clarify"):
                # 카드·pending_actions 는 파이프라인이 이미 저장했다 — 자동 승인 절대 금지, 사용자가 채팅에서 이어간다
                # The pipeline already saved the card/pending action — NEVER auto-approve; the user continues in the chat.
                result = "needs_input"
            elif t == "docgen":
                docgen_ev = ev
            elif t == "error":
                raise RuntimeError(ev.get("detail") or "파이프라인 오류")

        if docgen_ev is not None:
            # 문서 생성 요청 — 질문 카드 대신 포맷별 기본 스타일·분량으로 바로 생성(flows 의 코드단 기본값 재사용).
            # 컬렉션 지침(inst) 앞 500자를 최우선 스타일 지침(instruction)으로 전달 — 파일 본문은 넣지 않는다.
            # 파이프라인 이벤트 필드: fmt(pptx/pdf/docx/xlsx/mp4/image)·label·topic·message.
            # Docgen request — skip the question card and generate with per-format defaults (flows' baked-in
            # values). The first 500 chars of the collection instructions (inst) go in as the top-priority
            # `instruction` — file bodies are NOT included. Pipeline event fields: fmt, label, topic, message.
            fmt = docgen_ev.get("fmt") or docgen_ev.get("format") or ""
            if fmt not in flows._DOCGEN_STYLE:
                raise RuntimeError(f"지원하지 않는 문서 형식입니다: {fmt or '(없음)'}")
            topic = str(docgen_ev.get("topic") or "").strip()
            style = flows._DOCGEN_STYLE[fmt]
            length = flows._DOCGEN_LEN[fmt]
            source = "internal" if scope in ("자동", "사내") else "general"
            inst = str(coll_inst or "").strip()[:INST_CAP_DOCGEN]
            answer_text = []
            if docgen_ev.get("resume_id"):
                from app import conversation_execution, execution_store
                saved = execution_store.get(docgen_ev["resume_id"])
                saved["snapshot"]["doc_cfg"] = {"format": fmt, "topic": topic, "style": style, "length": length,
                                                "source": source, "instruction": inst}
                conversation_execution.resolve_cards(saved)
                execution_store.save(saved, "ready")
                doc_stream = conversation_execution.resume_events(saved)
            else:
                doc_stream = docgen.run_docgen(chat, message, fmt, topic, style, length, source, owner, inst, save_user=False)
            async for ev in doc_stream:
                t = ev.get("type")
                if t == "execution_result":
                    from app.execution_outcomes import schedule_result
                    if ev["state"] != "running":
                        result = schedule_result(ev["state"], ev.get("artifact", False))
                elif t == "token":
                    answer_text.append(ev.get("text") or "")
                elif t == "done":
                    if ev.get("message_id"):
                        answer_id = ev["message_id"]
                    enriched_sources = None   # docgen 은 meta.sources 를 스스로 저장 / docgen saves meta.sources itself
                elif t in ("confirm", "clarify"):
                    result = "needs_input"
                elif t == "error":
                    raise RuntimeError(ev.get("detail") or "문서 생성 오류")
            if result not in ("needs_input", "interrupted") and not result.startswith("error:"):
                result = "doc"
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        es = str(e)
        if _is_quota_error(es):
            # 쿼터 소진은 오류가 아니라 안내로(chats_api 패턴) / quota exhaustion is guidance, not an error
            logger.warning("예약 %s: 429/쿨다운 — 안내 저장", sched_id)
            note = ("지금 AI 호출량이 몰려 잠시 응답이 어렵습니다. 1~2분 뒤 같은 요청을 "
                    "다시 보내주시면 이어서 처리하겠습니다.")
            result = "429"
        else:
            logger.exception("예약 %s 파이프라인 오류", sched_id)
            note = "예약 실행 중 오류가 발생했습니다: " + es[:200]
            result = "error:" + es[:200]
        try:
            db.add_message(chat_id, "assistant", note, meta={"source": "사내", "schedule_id": sched_id})
        except Exception:  # noqa: BLE001
            logger.warning("안내 메시지 저장 실패", exc_info=True)
    finally:
        # 오류 이벤트에서 소비를 멈춰도 공통 실행기의 체크포인트 정리를 끝낸다.
        for stream in (doc_stream, gen):
            if stream is not None:
                await stream.aclose()
        # 알림 본문용 답변 앞부분 — 외부 예외 마감(fire)에서도 쓰도록 state 에 보관 / answer excerpt for the mail body, kept in state
        state["answer_preview"] = "".join(answer_text)[:300]
        if answer_id:
            try:
                patch: dict = {"trace": trace, "schedule_id": sched_id}
                if enriched_sources is not None:
                    patch["sources"] = enriched_sources
                db.update_message_meta(answer_id, patch)
            except Exception:  # noqa: BLE001
                logger.warning("실행 트레이스 저장 실패", exc_info=True)

    # 5) 마감 → 알림 발송(notify_email 이 켜져 있으면 소유자에게 무조건 1통 — 결과 불문, 취소만 제외) / close → notify (one mail to the owner when notify_email is on, any result; cancel excluded)
    closed = _close(sched_id, result, chat_id)
    logger.info("예약 %s 실행 종료: result=%s chat=%s%s", sched_id, result, chat_id,
                "" if closed else " (행 없음 — 삭제 또는 리스 만료 복구됨)")
    # 결과 채팅에 실행 결과를 남기고(히스토리 표시용) 오래된 결과 채팅을 정리한다(6차) / stamp the result on the chat, prune old runs
    try:
        db.set_chat_sched_result(chat_id, result)
        await asyncio.to_thread(_prune_runs, sched_id)
    except Exception:  # noqa: BLE001
        logger.warning("결과 채팅 기록/정리 실패: %s", sched_id, exc_info=True)
    # 실제로 마감된 실행만 알림 대상(리스 만료로 이미 interrupted 처리된 행은 제외 — 리뷰 지적) / notify only a run that really closed
    return (result, chat_id, state.get("answer_preview") or "") if closed else None


# ─────────────────────────────────────────────────────────────────────────────
# 루프/lifespan
# Loop / lifespan
# ─────────────────────────────────────────────────────────────────────────────

async def _loop() -> None:
    logger.info("스케줄러 루프 시작 (poll=%ss)", SCHED_POLL_SEC)
    while True:
        try:
            _recover_stale()
            for sid in _due_ids():
                if claim(sid):
                    await asyncio.gather(asyncio.create_task(fire(sid)), return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — 틱 예외는 기록 후 계속 / log and keep ticking
            logger.warning("스케줄러 틱 오류", exc_info=True)
        await asyncio.sleep(SCHED_POLL_SEC)


def run_now(sched_id: str) -> asyncio.Task:
    """지금 실행 — claim(force) 은 호출자가 끝냈다는 전제. 태스크 참조를 보관해 GC 를 막는다."""
    # Run now — caller has already claimed with force. Keeps the task reference to prevent GC.
    task = asyncio.create_task(fire(sched_id), name=f"ai365-sched-run-{sched_id}")
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


@asynccontextmanager
async def lifespan(app):
    """FastAPI lifespan — 기동 시 만료 리스 복구(리스 만료 행만 — 공유 DB 의 다른 프로세스 고려) + 놓친 회차 건너뜀
    + 폴링 루프, 종료 시 루프·run-now 태스크를 취소하고 최대 5초 동안 되돌리기 핸들러가 돌게 둔다.
    SCHED_ENABLED=0 이면 루프 미기동."""
    # FastAPI lifespan — at startup recover expired leases only (another process may share the DB), skip missed
    # runs, start the polling loop; at shutdown cancel the loop and run-now tasks and give their revert handlers
    # up to 5 s. SCHED_ENABLED=0 skips the loop.
    task = None
    if SCHED_ENABLED:
        try:
            _recover_stale()
        except Exception:  # noqa: BLE001
            logger.warning("기동 시 리스 복구 실패", exc_info=True)
        try:
            _skip_missed()
        except Exception:  # noqa: BLE001
            logger.warning("기동 시 놓친 회차 건너뜀 실패", exc_info=True)
        task = asyncio.create_task(_loop(), name="ai365-scheduler")
    else:
        logger.info("SCHED_ENABLED=0 — 스케줄러 루프 미기동")
    try:
        yield
    finally:
        pending = list(_bg_tasks)
        for t in pending:
            t.cancel()
        if task is not None:
            task.cancel()
            pending.append(task)
        if pending:
            try:
                await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), 5)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        logger.info("스케줄러 루프 종료")
