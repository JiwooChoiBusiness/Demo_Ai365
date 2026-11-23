"""Agentic 모드 저장소(2026-10-19): 세션 · 이벤트 · 백그라운드 작업 · 설정(SQLite, 다른 스토어와 같은 db._conn() 패턴).

- agentic_sessions: 세션 1개 = 한 작업 폴더에서 이어지는 대화. 소유자는 뷰애즈 신원(acting_user_id, '' = 슈퍼).
- agentic_events: 트랜스크립트의 단일 원본. seq 는 세션 안에서 1부터 늘고(세션 행의 last_seq 와 한 트랜잭션), 스트리밍과
  이어 보기가 모두 여기서 읽는다. 한 번 쓴 이벤트는 고치지 않는다(승인 결정도 같은 approval_id 로 새 이벤트를 쓴다).
- agentic_tasks: background 로 띄운 명령의 상태 · 출력 · 종료 코드.
- agentic_settings: 관리 센터 'Agentic' 카드의 설정(키마다 JSON 값). get_settings() 가 기본값을 합쳐 돌려준다.
기동 정리: init_agentic() 이 이전 프로세스가 남긴 running · waiting 세션을 stopped 로 바꾸고 status 이벤트를 남긴다
(대기 중이던 승인은 거부로 닫고, 돌던 background 작업 행은 stopped 로 바꾼다).
2차(2026-10-19): 세션 열 connectors · notify · seen_seq · prev_perm · hooks_trust · compact_seq(없는 열만 ALTER), 플랜 모드,
agentic_checkpoints(git 체크포인트) · agentic_outputs(세션이 만들거나 고친 파일), 설정 notify_default · commands · skills · hooks
와 예산 compact_pct · max_subagents · subagent_max_steps. commands · skills · hooks 검증은 agentic_commands · agentic_hooks 가 한다.
내 컴퓨터 폴더(2026-10-20): 세션 열 kind = local(서버 폴더, 종전) | browser(사용자의 브라우저가 연 폴더). browser 세션의 folder 는
폴더 이름(표시용, realpath 하지 않는다)이고 extra_folders 는 늘 [] 이다(docs/agentic-browser-folder-contract.md A).
"""
# Agentic mode store (2026-10-19): sessions, events, background tasks and settings (SQLite, the same db._conn()
# pattern as the other stores).
# - agentic_sessions: one session = one conversation in one working folder, owned by the view-as identity ('' = super).
# - agentic_events: the single source of the transcript. seq grows from 1 inside a session (in one transaction with the
#   session row's last_seq); streaming and resume both read it. Events are never edited: an approval decision is a new
#   event with the same approval_id.
# - agentic_tasks: state, output and exit code of commands started in the background.
# - agentic_settings: the Admin Center 'Agentic' card (one JSON value per key); get_settings() merges the defaults.
# Boot cleanup: init_agentic() turns running and waiting sessions left by a previous process into stopped with a status
# event (pending approvals are closed as denied, running background task rows become stopped).
# Phase 2 (2026-10-19): session columns connectors, notify, seen_seq, prev_perm, hooks_trust and compact_seq (ALTER only
# the missing ones), plan mode, agentic_checkpoints (git checkpoints) and agentic_outputs (files the session created or
# changed), the settings notify_default, commands, skills and hooks, and the budgets compact_pct, max_subagents and
# subagent_max_steps. agentic_commands and agentic_hooks validate commands, skills and hooks.
# Folders on my computer (2026-10-20): the session column kind = local (a server folder, as before) | browser (a folder
# the user's browser opened). A browser session's folder is the folder name (for display, never realpathed) and its
# extra_folders stay [] (docs/agentic-browser-folder-contract.md A).

import json
import os
import re
import sqlite3
import uuid
from pathlib import Path

from app import db, kst

# 모델(Gemini 만, 2026-10-19 사용자 결정). 체인은 세션 모델부터 아래로. 2026-10-30 채팅과 같은 3.7 → 3.5 → 3.5-lite(3.8 지연 · 504 로 뺌,
# 옛 세션의 3.8 은 목록에 없어 체인 맨 앞부터 돈다) / Gemini only; the chain runs down from the session model. Since 2026-10-30 the same
# 3.7 → 3.5 → 3.5-lite as chat (3.8 dropped for delays and 504s; an old session's 3.8 is not listed, so its chain starts at the top)
MODELS = [
    {"id": "gemini-3.7-flash", "label": "Gemini 3.7 Flash"},
    {"id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash"},
    {"id": "gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash-Lite"},
]
MODEL_IDS = tuple(m["id"] for m in MODELS)
PERM_MODES = ("auto", "ask", "plan")   # plan(2차) = 읽기 · 조사만, 계획을 글로 낸다 / plan (phase 2) reads only and writes a plan
# 세션 종류(2026-10-20): local = 서버 폴더(종전), browser = 내 컴퓨터 폴더(브라우저가 연 폴더, 도구는 브라우저가 실행)
# Session kinds (2026-10-20): local = a server folder (as before), browser = a folder on my computer (the browser runs the tools)
KINDS = ("local", "browser")
BROWSER_NAME_MAX = 200
_BROWSER_NAME_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')   # 경로 문자 · 제어 문자 / path and control characters

MAX_TITLE = 120
MAX_FOLDERS = 20          # 허용 폴더 · 추가 폴더 수 / allowed and extra folders
MAX_DENY = 100            # 차단 명령 정규식 수 / denied-command patterns
MAX_PATTERN = 300         # 정규식 하나의 길이 / one pattern's length
MAX_TASK_OUTPUT = 400_000 # 작업 출력 저장 상한(글자) / stored task output (chars)
MAX_CONNECTORS = 20       # 세션 하나가 켜는 MCP 도구 수 / MCP tools one session turns on
MAX_CHECKPOINTS = 50      # 세션당 남기는 체크포인트 수 / checkpoints kept per session
RESTART_NOTE = "서버가 다시 시작되어 중단됨"

# 명령 낱말 앞 구분자(적대 검토 H1): 줄 처음 · 공백 · ; & | ( " ' = , 뒤의 명령도 잡는다(cmd /c "del /q x" 처럼 따옴표 뒤).
# 낱말 중간(model /s · --format)은 잡지 않는다 / separators before a command word: also after quotes, never mid-word
_SEP = r"(?:^|[\s;&|(\"'=,])"
DEFAULT_DENY = [
    _SEP + r"rm\s+(?:-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\b",          # rm -r · -rf · -fr · --recursive
    _SEP + r"(?:rmdir|rd)\s+(?:[^\n]*\s)?/s\b",                       # rmdir /s · rd /s(스위치 위치와 무관 / anywhere)
    _SEP + r"(?:del|erase)\s+(?:[^\n]*\s)?/[sq]\b",                   # del /s · del x /q · erase
    _SEP + r"format(?:\.com)?\s+[A-Za-z]:",                           # format C: (npm run format 같은 오탐 없이 / no false hit)
    _SEP + r"diskpart\b",
    _SEP + r"mkfs",
    _SEP + r"shutdown\b",
    _SEP + r"reg(?:\.exe)?\s+(?:add|delete)\b",
    _SEP + r"git\s+push\b[^\n]*\s(?:--force(?:-with-lease)?|-f)\b",   # --force · --force-with-lease · -f
    _SEP + r"(?:curl|wget)\b[^\n]*\|\s*(?:sh|bash|zsh)\b",
    _SEP + r"Remove-Item\b[^\n]*-Recurse",
    _SEP + r"(?:powershell|pwsh)(?:\.exe)?\b[^\n]*(?:\b(?:Remove-Item|del|rm|Clear-Content)\b|-Recurse)",
    # 설계 3절(2026-10-19): 삭제는 한 파일이라도 Auto 에서 승인을 묻는다 · 서버 비밀이 든 .env 는 명령으로도 승인 뒤에만
    # Design section 3: any deletion asks even in Auto; the .env holding server secrets needs approval even through a command
    _SEP + r"(?:rm|del|erase|rmdir|rd|remove-item|ri)(?:\.exe)?\s",
    r"(?:^|[\s;&|(\"'=,/\\])\.env(?:\b|$)",
]
# 2차 예산: compact_pct = 컨텍스트 압축 임계(%) · max_subagents = 한 라운드에 동시에 도는 서브에이전트 · subagent_max_steps =
# 서브에이전트 하나의 라운드 상한 / phase-2 budgets: the compaction threshold (%), concurrent subagents per round, rounds per subagent
DEFAULT_BUDGETS = {"max_steps": 200, "max_minutes": 120, "max_sessions": 3, "bash_timeout_sec": 120, "max_output_chars": 20000,
                   "compact_pct": 80, "max_subagents": 3, "subagent_max_steps": 60}
BUDGET_RANGES = {"max_steps": (1, 10000), "max_minutes": (1, 1440), "max_sessions": (1, 20),
                 "bash_timeout_sec": (1, 600), "max_output_chars": (1000, 200000),
                 "compact_pct": (30, 95), "max_subagents": (1, 8), "subagent_max_steps": (5, 500)}
SETTING_KEYS = ("allowed_folders", "default_perm", "default_model", "deny_commands", "budgets",
                "notify_default", "commands", "skills", "hooks")

_SESSION_FIELDS = ("title", "folder", "extra_folders", "model", "effort", "perm_mode", "status", "context_pct", "rules", "steps",
                   "connectors", "notify", "seen_seq", "prev_perm", "hooks_trust", "compact_seq")
_JSON_FIELDS = ("extra_folders", "rules", "connectors")
_TASK_FIELDS = ("status", "ended", "output", "exit_code", "label")
# 2차에서 더한 세션 열(이전 DB 에는 없는 것만 ALTER 로 더한다) + kind(2026-10-20, 종전 행은 전부 local)
# Session columns added in phase 2 (ALTERed in when missing) plus kind (2026-10-20; existing rows all become local)
_NEW_COLUMNS = (("connectors", "TEXT NOT NULL DEFAULT '[]'"), ("notify", "INTEGER NOT NULL DEFAULT 0"),
                ("seen_seq", "INTEGER NOT NULL DEFAULT 0"), ("prev_perm", "TEXT NOT NULL DEFAULT ''"),
                ("hooks_trust", "TEXT NOT NULL DEFAULT ''"), ("compact_seq", "INTEGER NOT NULL DEFAULT 0"),
                ("kind", "TEXT NOT NULL DEFAULT 'local'"))


class SessionGone(KeyError):
    """세션이 없다(지워졌다) / the session does not exist (deleted)"""


def _now() -> str:
    return kst.now_iso()


def _loads(raw, default):
    try:
        v = json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default
    return v if isinstance(v, type(default)) else default


# ────────────────────────────────────────────────────────
# 스키마 · 기동 정리 / schema and boot cleanup
# ────────────────────────────────────────────────────────

def init_agentic() -> None:
    """테이블 생성 + 기동 정리(이전 프로세스의 running · waiting → stopped) / create tables and run the boot cleanup"""
    with db._conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS agentic_sessions(
              id TEXT PRIMARY KEY,                       -- 'ag_' + uuid4 hex[:10]
              owner TEXT NOT NULL,                       -- 뷰애즈 신원('' = 슈퍼) / view-as identity
              title TEXT NOT NULL,                       -- 비면 폴더 이름 / folder name when empty
              folder TEXT NOT NULL,                      -- 절대 경로(정규화) / normalized absolute path
              extra_folders TEXT NOT NULL DEFAULT '[]',
              model TEXT NOT NULL,
              effort TEXT NOT NULL DEFAULT 'auto',
              perm_mode TEXT NOT NULL DEFAULT 'auto',    -- auto | ask | plan
              status TEXT NOT NULL DEFAULT 'idle',       -- idle | running | waiting | done | stopped | error
              context_pct INTEGER NOT NULL DEFAULT 0,
              rules TEXT NOT NULL DEFAULT '[]',          -- 이 세션에서 항상 허용 / always-allow rules of this session
              steps INTEGER NOT NULL DEFAULT 0,          -- 누적 도구 호출 수 / cumulative tool calls
              last_seq INTEGER NOT NULL DEFAULT 0,
              created TEXT NOT NULL,
              updated TEXT NOT NULL,
              connectors TEXT NOT NULL DEFAULT '[]',     -- 이 세션이 쓰는 MCP 도구 커넥터 id / MCP tool connector ids this session uses
              notify INTEGER NOT NULL DEFAULT 0,         -- 완료 알림(메일) / completion mail
              seen_seq INTEGER NOT NULL DEFAULT 0,       -- 화면이 마지막으로 본 seq / the last seq the screen saw
              prev_perm TEXT NOT NULL DEFAULT '',        -- 플랜 모드 전 모드 / the mode before plan mode
              hooks_trust TEXT NOT NULL DEFAULT '',      -- 'allow:<hash>' | 'deny:<hash>' | ''
              compact_seq INTEGER NOT NULL DEFAULT 0,    -- 마지막 히스토리 압축 이벤트 seq / seq of the last history compaction
              kind TEXT NOT NULL DEFAULT 'local'         -- local(서버 폴더) | browser(내 컴퓨터 폴더, folder = 이름) / folder = the name
            );
            CREATE INDEX IF NOT EXISTS idx_agentic_sessions_owner ON agentic_sessions(owner, updated);
            CREATE TABLE IF NOT EXISTS agentic_events(
              session TEXT, seq INTEGER, ts TEXT, kind TEXT, payload TEXT,
              PRIMARY KEY(session, seq)
            );
            CREATE TABLE IF NOT EXISTS agentic_tasks(
              id TEXT PRIMARY KEY, session TEXT, kind TEXT, label TEXT, status TEXT,
              started TEXT, ended TEXT, output TEXT, exit_code INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_agentic_tasks_session ON agentic_tasks(session, started);
            CREATE TABLE IF NOT EXISTS agentic_settings(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS agentic_checkpoints(
              id TEXT PRIMARY KEY,                       -- 'cp_' + hex[:10]
              session TEXT, seq INTEGER, ref TEXT, commit_hash TEXT, tree_hash TEXT, label TEXT, files INTEGER, ts TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_agentic_checkpoints_session ON agentic_checkpoints(session, ts);
            CREATE TABLE IF NOT EXISTS agentic_outputs(
              session TEXT, path TEXT, kind TEXT, bytes INTEGER, ts TEXT,   -- kind created | modified
              PRIMARY KEY(session, path)
            );
            """
        )
        _migrate(conn)
        _cleanup_stale(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """이전 DB 에 2차 세션 열 · kind 를 더한다(없는 열만, PRAGMA table_info 로 확인) / add the missing phase-2 columns and kind"""
    have = {r[1] for r in conn.execute("PRAGMA table_info(agentic_sessions)").fetchall()}
    for name, decl in _NEW_COLUMNS:
        if name not in have:
            conn.execute(f"ALTER TABLE agentic_sessions ADD COLUMN {name} {decl}")


def _cleanup_stale(conn: sqlite3.Connection) -> int:
    """이전 프로세스가 남긴 running · waiting 세션 → stopped(+ status 이벤트). 대기 중 승인은 거부로 닫는다.
    정리는 사용자 활동이 아니므로 세션의 updated 는 건드리지 않는다. 바꾼 세션 수를 돌려준다."""
    # running/waiting sessions left by a previous process → stopped (+ a status event); pending approvals close as denied.
    # Cleanup is not user activity, so the session's `updated` stays. Returns the number of sessions changed.
    now = _now()
    rows = conn.execute("SELECT id FROM agentic_sessions WHERE status IN ('running', 'waiting')").fetchall()
    for r in rows:
        sid = r["id"]
        latest: dict[str, dict] = {}
        for e in conn.execute("SELECT payload FROM agentic_events WHERE session=? AND kind='approval' ORDER BY seq", (sid,)):
            p = _loads(e["payload"], {})
            if p.get("approval_id"):
                latest[p["approval_id"]] = p
        for p in latest.values():
            if p.get("decision") == "pending":
                _append(conn, sid, "approval", {**p, "decision": "deny", "decided_at": now}, touch=False)
        _append(conn, sid, "status", {"state": "stopped", "note": RESTART_NOTE}, touch=False)
        conn.execute("UPDATE agentic_sessions SET status='stopped' WHERE id=?", (sid,))
    conn.execute("UPDATE agentic_tasks SET status='stopped', ended=? WHERE status='running'", (now,))
    return len(rows)


# ────────────────────────────────────────────────────────
# 설정 / settings
# ────────────────────────────────────────────────────────

def default_folders() -> list[str]:
    """기본 허용 폴더 = <홈>/Desktop · <홈>/Documents 중 있는 것 / the default allowed folders that exist"""
    out = []
    for p in (Path.home() / "Desktop", Path.home() / "Documents"):
        if p.is_dir():
            out.append(os.path.realpath(str(p)))
    return out


def norm_folder(path) -> str:
    """절대 경로이고 있는 폴더만, realpath 로 정규화(심볼릭 링크 · 정션을 푼다). 아니면 ValueError.
    Absolute, existing directories only, normalized with realpath (links resolved); ValueError otherwise."""
    s = str(path or "").strip()
    if not s:
        raise ValueError("폴더 경로가 비어 있습니다")
    if "\x00" in s:
        raise ValueError("폴더 경로가 올바르지 않습니다")
    if not os.path.isabs(s):
        raise ValueError(f"절대 경로가 아닙니다: {s}")
    real = os.path.realpath(s)
    if not os.path.isdir(real):
        raise ValueError(f"폴더가 없습니다: {s}")
    return real


def dedupe_folders(paths: list[str]) -> list[str]:
    """같은 폴더(normcase 기준)는 한 번만, 순서 유지 / each folder once (by normcase), order kept"""
    seen, out = set(), []
    for p in paths:
        k = os.path.normcase(p)
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def get_settings() -> dict:
    """설정 = 기본값 + 저장값(키마다). budgets 는 키별로 합친다 / defaults merged with the stored values (budgets per key)"""
    with db._conn() as conn:
        rows = conn.execute("SELECT key, value FROM agentic_settings").fetchall()
    stored = {}
    for r in rows:
        try:
            stored[r["key"]] = json.loads(r["value"])
        except (TypeError, ValueError):
            continue
    out = {"allowed_folders": default_folders(), "default_perm": "auto", "default_model": MODEL_IDS[0],
           "deny_commands": list(DEFAULT_DENY), "budgets": dict(DEFAULT_BUDGETS),
           "notify_default": False, "commands": [], "skills": [], "hooks": []}
    if isinstance(stored.get("allowed_folders"), list):
        out["allowed_folders"] = [str(p) for p in stored["allowed_folders"]]
    if stored.get("default_perm") in PERM_MODES:
        out["default_perm"] = stored["default_perm"]
    if stored.get("default_model") in MODEL_IDS:
        out["default_model"] = stored["default_model"]
    if isinstance(stored.get("deny_commands"), list):
        out["deny_commands"] = [str(p) for p in stored["deny_commands"]]
    if isinstance(stored.get("budgets"), dict):
        for k, v in stored["budgets"].items():
            if k in DEFAULT_BUDGETS and isinstance(v, int) and not isinstance(v, bool):
                out["budgets"][k] = v
    if isinstance(stored.get("notify_default"), bool):
        out["notify_default"] = stored["notify_default"]
    for k in ("commands", "skills", "hooks"):   # 저장 때 검증을 마친 목록(객체만 남긴다) / lists validated on save
        if isinstance(stored.get(k), list):
            out[k] = [x for x in stored[k] if isinstance(x, dict)]
    return out


def _int_in(name: str, v, lo: int, hi: int) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not v.is_integer()):
        raise ValueError(f"{name} 은(는) 정수여야 합니다")
    v = int(v)
    if not lo <= v <= hi:
        raise ValueError(f"{name} 은(는) {lo}~{hi} 사이여야 합니다")
    return v


def validate_settings(values: dict, current: dict | None = None) -> dict:
    """저장할 값 검증 · 정규화(주어진 키만). 폴더는 있는 절대 경로만, 정규식은 컴파일되는 것만. commands · skills 는
    agentic_commands, hooks 는 agentic_hooks 가 검증한다(그 ValueError 를 그대로 올린다). 틀리면 ValueError.
    Validate and normalize the given keys only: folders must be existing absolute paths, patterns must compile; commands
    and skills go to agentic_commands, hooks to agentic_hooks (their ValueError passes through)."""
    if not isinstance(values, dict):
        raise ValueError("settings 는 객체여야 합니다")
    unknown = [k for k in values if k not in SETTING_KEYS]
    if unknown:
        raise ValueError(f"알 수 없는 설정입니다: {', '.join(map(str, unknown))}")
    cur = current or get_settings()
    out: dict = {}
    if "allowed_folders" in values:
        raw = values["allowed_folders"]
        if not isinstance(raw, list):
            raise ValueError("allowed_folders 는 목록이어야 합니다")
        if len(raw) > MAX_FOLDERS:
            raise ValueError(f"허용 폴더는 {MAX_FOLDERS}개까지입니다")
        out["allowed_folders"] = dedupe_folders([norm_folder(p) for p in raw])
    if "default_perm" in values:
        if values["default_perm"] not in PERM_MODES:
            raise ValueError("default_perm 은 auto · ask · plan 중 하나입니다")
        out["default_perm"] = values["default_perm"]
    if "default_model" in values:
        if values["default_model"] not in MODEL_IDS:
            raise ValueError(f"default_model 은 {', '.join(MODEL_IDS)} 중 하나입니다")
        out["default_model"] = values["default_model"]
    if "deny_commands" in values:
        raw = values["deny_commands"]
        if not isinstance(raw, list):
            raise ValueError("deny_commands 는 목록이어야 합니다")
        pats = []
        for p in raw:
            p = str(p if p is not None else "").strip()
            if not p:
                continue
            if len(p) > MAX_PATTERN:
                raise ValueError(f"정규식이 너무 깁니다(최대 {MAX_PATTERN}자): {p[:40]}")
            try:
                re.compile(p)
            except re.error as e:
                raise ValueError(f"정규식 오류({p}): {e}") from e
            if p not in pats:
                pats.append(p)
        if len(pats) > MAX_DENY:
            raise ValueError(f"차단 명령은 {MAX_DENY}개까지입니다")
        out["deny_commands"] = pats
    if "budgets" in values:
        raw = values["budgets"]
        if not isinstance(raw, dict):
            raise ValueError("budgets 는 객체여야 합니다")
        bad = [k for k in raw if k not in DEFAULT_BUDGETS]
        if bad:
            raise ValueError(f"알 수 없는 예산 항목입니다: {', '.join(map(str, bad))}")
        merged = dict(cur["budgets"])
        for k, v in raw.items():
            lo, hi = BUDGET_RANGES[k]
            merged[k] = _int_in(k, v, lo, hi)
        out["budgets"] = merged
    if "notify_default" in values:
        if not isinstance(values["notify_default"], bool):
            raise ValueError("notify_default 는 true 또는 false 입니다")
        out["notify_default"] = values["notify_default"]
    if "commands" in values or "skills" in values:
        from app import agentic_commands   # 지연 임포트(그 모듈은 이 모듈을 부르지 않는다) / lazy import, no cycle
        if "commands" in values:
            out["commands"] = agentic_commands.validate_commands(values["commands"])
        if "skills" in values:
            out["skills"] = agentic_commands.validate_skills(values["skills"])
    if "hooks" in values:
        from app import agentic_hooks   # 지연 임포트 / lazy import
        out["hooks"] = agentic_hooks.validate_hooks(values["hooks"])
    return out


def put_settings(values: dict) -> dict:
    """설정 저장(주어진 키만 바꾼다) → 합친 설정. 검증 실패는 ValueError / save the given keys and return the merged settings"""
    clean = validate_settings(values)
    with db._conn() as conn:
        for k, v in clean.items():
            conn.execute("INSERT INTO agentic_settings(key, value) VALUES(?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, json.dumps(v, ensure_ascii=False)))
    return get_settings()


def model_chain(model: str) -> list[str]:
    """세션 모델부터 아래로: 3.8 → [3.8, 3.7, lite], 3.7 → [3.7, lite], lite → [lite]. 모르는 값은 첫 모델부터.
    From the session model downward; an unknown value starts at the first model."""
    i = MODEL_IDS.index(model) if model in MODEL_IDS else 0
    return list(MODEL_IDS[i:])


# ────────────────────────────────────────────────────────
# 세션 / sessions
# ────────────────────────────────────────────────────────

def _session(row) -> dict | None:
    if row is None:
        return None
    return {"id": row["id"], "owner": row["owner"], "title": row["title"], "folder": row["folder"],
            "extra_folders": _loads(row["extra_folders"], []), "model": row["model"], "effort": row["effort"],
            "perm_mode": row["perm_mode"], "status": row["status"], "context_pct": int(row["context_pct"] or 0),
            "rules": _loads(row["rules"], []), "steps": int(row["steps"] or 0), "last_seq": int(row["last_seq"] or 0),
            "created": row["created"], "updated": row["updated"],
            "connectors": [str(c) for c in _loads(row["connectors"], [])], "notify": bool(row["notify"]),
            "seen_seq": int(row["seen_seq"] or 0), "prev_perm": row["prev_perm"] or "",
            "hooks_trust": row["hooks_trust"] or "", "compact_seq": int(row["compact_seq"] or 0),
            "kind": row["kind"] if row["kind"] in KINDS else "local"}


def light(session: dict) -> dict:
    """목록용 가벼운 모양(사이드바 미확인 점용 notify · seen_seq · last_seq, 종류 kind 포함) / the light shape for lists, with the
    fields the sidebar's unseen dot needs and the kind"""
    return {k: session[k] for k in ("id", "title", "folder", "model", "perm_mode", "status", "updated", "created", "steps",
                                    "notify", "seen_seq", "last_seq", "kind")}


def browser_folder_name(raw) -> str:
    """내 컴퓨터 폴더 세션의 폴더 이름 검증(2026-10-20): 비었거나 200자를 넘거나 경로 문자(\\ / : * ? " < > |) · 제어 문자가
    있거나 '.' · '..' 이면 ValueError. 앞뒤 공백까지 그대로 돌려준다(브라우저 핸들의 이름과 같아야 한다).
    Validate a browser session's folder name: empty, over 200 chars, path or control characters, '.' or '..' raise
    ValueError; the name comes back as it is, spaces included (it must equal the browser handle's name)."""
    name = str(raw if raw is not None else "")
    if not name.strip():
        raise ValueError("폴더 이름이 비어 있습니다")
    if len(name) > BROWSER_NAME_MAX:
        raise ValueError(f"폴더 이름이 너무 깁니다(최대 {BROWSER_NAME_MAX}자)")
    if _BROWSER_NAME_BAD.search(name) or name.strip() in (".", ".."):
        raise ValueError(f"폴더 이름에 쓸 수 없는 글자가 있습니다: {name}")
    return name


def create_session(owner: str, folder: str, title: str = "", model: str = "", perm_mode: str = "",
                   notify: bool | None = None, kind: str = "local") -> dict:
    """세션 생성. local 의 folder 는 호출부가 허용 폴더 검사를 마친 경로(여기서는 realpath 정규화만), browser 의 folder 는 폴더
    이름(browser_folder_name 으로 검증만, realpath 하지 않는다). model · perm_mode 가 비면 설정 기본값, notify 가 None 이면
    설정의 notify_default, 제목이 비면 폴더 이름. 모르는 kind 는 ValueError.
    Create a session. A local folder has already been checked against the allowed folders by the caller (only realpath
    here); a browser folder is the folder name (validated, never realpathed). An empty model or perm_mode takes the
    settings default, notify None takes notify_default, an empty title the folder name; an unknown kind is a ValueError."""
    if kind not in KINDS:
        raise ValueError("kind 는 local 또는 browser")
    settings = get_settings()
    model = model or settings["default_model"]
    perm_mode = perm_mode or settings["default_perm"]
    if model not in MODEL_IDS:
        raise ValueError(f"모델은 {', '.join(MODEL_IDS)} 중 하나입니다")
    if perm_mode not in PERM_MODES:
        raise ValueError("권한 모드는 auto · ask · plan 중 하나입니다")
    if kind == "browser":
        real = base = browser_folder_name(folder)
    else:
        real = os.path.realpath(str(folder))
        base = os.path.basename(real.rstrip("\\/")) or real
    name = str(title or "").strip()[:MAX_TITLE] or base[:MAX_TITLE]
    sid = "ag_" + uuid.uuid4().hex[:10]
    now = _now()
    on = bool(settings.get("notify_default")) if notify is None else bool(notify)
    with db._conn() as conn:
        conn.execute("INSERT INTO agentic_sessions(id, owner, title, folder, extra_folders, model, effort, perm_mode, status,"
                     " context_pct, rules, steps, last_seq, created, updated, notify, kind) "
                     "VALUES(?,?,?,?,'[]',?,'auto',?,'idle',0,'[]',0,0,?,?,?,?)",
                     (sid, owner or "", name, real, model, perm_mode, now, now, 1 if on else 0, kind))
    return get_session(sid)


def set_perm_mode(session_id: str, mode: str) -> dict:
    """권한 모드 전환(API PATCH · 슬래시 명령 공통). plan 으로 들어가면 prev_perm 에 이전 모드를 두고, plan 에서 나오면 비운다.
    같은 모드면 그대로. 모르는 모드는 ValueError, 세션이 없으면 SessionGone.
    Switch the permission mode (shared by PATCH and the slash commands): entering plan keeps the previous mode in
    prev_perm, leaving plan clears it; the same mode is a no-op."""
    if mode not in PERM_MODES:
        raise ValueError("권한 모드는 auto · ask · plan 중 하나입니다")
    s = get_session(session_id)
    if s is None:
        raise SessionGone(session_id)
    if s["perm_mode"] == mode:
        return s
    prev = s["perm_mode"] if mode == "plan" else ""
    return update_session(session_id, perm_mode=mode, prev_perm=prev)


def mark_seen(session_id: str, seq) -> dict | None:
    """화면이 본 seq 를 남긴다(last_seq 상한, 뒤로 가지 않는다). 활동이 아니므로 updated 는 그대로.
    Record the seq the screen has seen (capped at last_seq, never moving back); not activity, so `updated` stays."""
    try:
        n = max(0, int(seq))
    except (TypeError, ValueError):
        n = 0
    with db._conn() as conn:
        conn.execute("UPDATE agentic_sessions SET seen_seq = MAX(seen_seq, MIN(?, last_seq)) WHERE id=?", (n, session_id))
    return get_session(session_id)


def get_session(session_id: str, owner: str | None = None) -> dict | None:
    """세션 1개. owner 를 주면 그 소유자의 것만 / one session; with owner, only that owner's"""
    with db._conn() as conn:
        row = conn.execute("SELECT * FROM agentic_sessions WHERE id=?", (session_id,)).fetchone()
    if row is None or (owner is not None and row["owner"] != owner):
        return None
    return _session(row)


def list_sessions(owner: str) -> list[dict]:
    """소유자의 세션(전체 모양), updated 내림차순 / the owner's sessions, newest activity first"""
    with db._conn() as conn:
        rows = conn.execute("SELECT * FROM agentic_sessions WHERE owner=? ORDER BY updated DESC, rowid DESC",
                            (owner or "",)).fetchall()
    return [_session(r) for r in rows]


def _set_fields(conn: sqlite3.Connection, session_id: str, fields: dict, touch: bool) -> None:
    sets, vals = [], []
    for k, v in fields.items():
        if k not in _SESSION_FIELDS:
            raise ValueError(f"바꿀 수 없는 세션 필드입니다: {k}")
        sets.append(f"{k}=?")
        vals.append(json.dumps(v, ensure_ascii=False) if k in _JSON_FIELDS else v)
    if touch:
        sets.append("updated=?")
        vals.append(_now())
    if sets:
        conn.execute(f"UPDATE agentic_sessions SET {', '.join(sets)} WHERE id=?", (*vals, session_id))


def update_session(session_id: str, touch: bool = True, **fields) -> dict | None:
    """세션 필드 갱신(목록 · 객체는 JSON 으로). touch=True 면 updated 도 지금으로 / update fields; touch bumps `updated`"""
    with db._conn() as conn:
        _set_fields(conn, session_id, fields, touch)
    return get_session(session_id)


def delete_session(session_id: str) -> bool:
    """세션과 그 이벤트 · 작업 · 체크포인트 · 산출물 행을 지운다(git ref 는 호출부가 agentic_git.drop_refs 로)
    Delete a session with its events, tasks, checkpoints and outputs (the caller drops the git refs)"""
    with db._conn() as conn:
        n = conn.execute("DELETE FROM agentic_sessions WHERE id=?", (session_id,)).rowcount
        conn.execute("DELETE FROM agentic_events WHERE session=?", (session_id,))
        conn.execute("DELETE FROM agentic_tasks WHERE session=?", (session_id,))
        conn.execute("DELETE FROM agentic_checkpoints WHERE session=?", (session_id,))
        conn.execute("DELETE FROM agentic_outputs WHERE session=?", (session_id,))
    return bool(n)


# ────────────────────────────────────────────────────────
# 이벤트 / events
# ────────────────────────────────────────────────────────

def _append(conn: sqlite3.Connection, session_id: str, kind: str, payload: dict | None, touch: bool = True) -> dict:
    """같은 트랜잭션에서 last_seq += 1 → 그 번호로 이벤트를 넣는다 / bump last_seq and insert the event in one transaction"""
    ts = _now()
    if touch:
        cur = conn.execute("UPDATE agentic_sessions SET last_seq = last_seq + 1, updated = ? WHERE id = ?", (ts, session_id))
    else:
        cur = conn.execute("UPDATE agentic_sessions SET last_seq = last_seq + 1 WHERE id = ?", (session_id,))
    if cur.rowcount == 0:
        raise SessionGone(session_id)
    seq = int(conn.execute("SELECT last_seq FROM agentic_sessions WHERE id = ?", (session_id,)).fetchone()["last_seq"])
    body = json.dumps(payload or {}, ensure_ascii=False, default=str)
    conn.execute("INSERT INTO agentic_events(session, seq, ts, kind, payload) VALUES(?,?,?,?,?)",
                 (session_id, seq, ts, kind, body))
    return {"seq": seq, "ts": ts, "kind": kind, "payload": json.loads(body)}


def record_event(session_id: str, kind: str, payload: dict | None) -> dict:
    """이벤트를 쓰고 쓴 모양 {seq, ts, kind, payload} 을 돌려준다. 세션이 없으면 SessionGone.
    Write an event and return it as stored; SessionGone when the session no longer exists."""
    with db._conn() as conn:
        return _append(conn, session_id, kind, payload)


def append_event(session_id: str, kind: str, payload: dict | None) -> int:
    """이벤트를 쓰고 seq 를 돌려준다(last_seq 갱신과 한 트랜잭션) / write an event and return its seq"""
    return record_event(session_id, kind, payload)["seq"]


def record_events(session_id: str, items: list[tuple[str, dict]], bump_steps: int = 0, **fields) -> list[dict]:
    """세션 필드 갱신(+ 누적 도구 수 증가) + 이벤트 여러 개를 한 트랜잭션(커밋 한 번)으로. 루프가 이벤트 루프 스레드에서
    쓰므로 커밋 수를 줄인다(Windows 에서 커밋 하나에 10ms 남짓). 세션이 없으면 SessionGone(아무것도 남기지 않는다).
    Session fields (plus a step bump) and several events in one transaction (one commit): the loop writes on the
    event-loop thread, so fewer commits matter (about 10 ms each on Windows). SessionGone leaves nothing behind."""
    with db._conn() as conn:
        if fields:
            _set_fields(conn, session_id, fields, touch=False)   # updated 는 _append 가 만진다 / _append bumps `updated`
        if bump_steps:
            conn.execute("UPDATE agentic_sessions SET steps = steps + ? WHERE id=?", (int(bump_steps), session_id))
        return [_append(conn, session_id, kind, payload) for kind, payload in items]


def _event(row) -> dict:
    return {"seq": int(row["seq"]), "ts": row["ts"], "kind": row["kind"], "payload": _loads(row["payload"], {})}


def list_events(session_id: str, after: int = 0, limit: int = 500, kinds: tuple[str, ...] | None = None) -> list[dict]:
    """seq > after 인 이벤트를 오름차순으로 limit 개까지(kinds 로 종류 거르기) / events after a seq, ascending"""
    sql = "SELECT seq, ts, kind, payload FROM agentic_events WHERE session=? AND seq>?"
    args: list = [session_id, int(after or 0)]
    if kinds:
        sql += f" AND kind IN ({', '.join('?' for _ in kinds)})"
        args.extend(kinds)
    sql += " ORDER BY seq LIMIT ?"
    args.append(max(1, int(limit or 1)))
    with db._conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_event(r) for r in rows]


# ────────────────────────────────────────────────────────
# 백그라운드 작업 / background tasks
# ────────────────────────────────────────────────────────

def _task(row, with_output: bool = True) -> dict | None:
    if row is None:
        return None
    out = {"id": row["id"], "session": row["session"], "kind": row["kind"], "label": row["label"], "status": row["status"],
           "started": row["started"], "ended": row["ended"] or "",
           "exit_code": row["exit_code"] if row["exit_code"] is None else int(row["exit_code"])}
    if with_output:
        out["output"] = row["output"] or ""
    return out


def create_task(session_id: str, kind: str, label: str) -> dict:
    """작업 행 생성(status running) / create a task row in the running state"""
    tid = "tk_" + uuid.uuid4().hex[:10]
    with db._conn() as conn:
        conn.execute("INSERT INTO agentic_tasks(id, session, kind, label, status, started, ended, output, exit_code)"
                     " VALUES(?,?,?,?,'running',?,'','',NULL)", (tid, session_id, kind, str(label or "")[:300], _now()))
    return get_task(tid)


def update_task(task_id: str, **fields) -> None:
    """작업 행 갱신(status · ended · output · exit_code · label) / update a task row"""
    sets, vals = [], []
    for k, v in fields.items():
        if k not in _TASK_FIELDS:
            raise ValueError(f"바꿀 수 없는 작업 필드입니다: {k}")
        if k == "output":
            v = str(v or "")[-MAX_TASK_OUTPUT:]
        sets.append(f"{k}=?")
        vals.append(v)
    if not sets:
        return
    with db._conn() as conn:
        conn.execute(f"UPDATE agentic_tasks SET {', '.join(sets)} WHERE id=?", (*vals, task_id))


def get_task(task_id: str, session_id: str | None = None, with_output: bool = True) -> dict | None:
    """작업 1개(session_id 를 주면 그 세션의 것만) / one task, optionally scoped to a session"""
    with db._conn() as conn:
        row = conn.execute("SELECT * FROM agentic_tasks WHERE id=?", (task_id,)).fetchone()
    if row is None or (session_id is not None and row["session"] != session_id):
        return None
    return _task(row, with_output)


def list_tasks(session_id: str, limit: int = 100) -> list[dict]:
    """세션의 작업(출력 제외), 시작 시각 내림차순 / a session's tasks without output, newest first"""
    with db._conn() as conn:
        rows = conn.execute("SELECT * FROM agentic_tasks WHERE session=? ORDER BY started DESC, rowid DESC LIMIT ?",
                            (session_id, int(limit))).fetchall()
    return [_task(r, with_output=False) for r in rows]


# ────────────────────────────────────────────────────────
# 체크포인트 · 산출물(2차) / checkpoints and outputs (phase 2)
# ────────────────────────────────────────────────────────

def _checkpoint(row) -> dict | None:
    if row is None:
        return None
    return {"id": row["id"], "seq": int(row["seq"] or 0), "ref": row["ref"] or "", "commit": row["commit_hash"] or "",
            "tree": row["tree_hash"] or "", "label": row["label"] or "", "files": int(row["files"] or 0), "ts": row["ts"]}


def add_checkpoint(session_id: str, seq: int, ref: str, commit: str, tree: str, label: str, files: int) -> dict:
    """체크포인트 행 추가(id 'cp_' + hex[:10]). seq = 그 턴(또는 /checkpoint 명령)의 user seq, 수동(API) · 되돌리기 전 자동
    저장은 0(/undo 는 seq 있는 행만 본다)
    Add a checkpoint row; seq is the user seq of the turn (or /checkpoint command), 0 for manual (API) and before-restore
    saves (/undo only considers rows with a seq)"""
    cid = "cp_" + uuid.uuid4().hex[:10]
    with db._conn() as conn:
        conn.execute("INSERT INTO agentic_checkpoints(id, session, seq, ref, commit_hash, tree_hash, label, files, ts)"
                     " VALUES(?,?,?,?,?,?,?,?,?)", (cid, session_id, int(seq or 0), str(ref or ""), str(commit or ""),
                                                   str(tree or ""), str(label or "")[:200], int(files or 0), _now()))
    return get_checkpoint(cid)


def list_checkpoints(session_id: str) -> list[dict]:
    """세션의 체크포인트, 최근 것부터 / a session's checkpoints, newest first"""
    with db._conn() as conn:
        rows = conn.execute("SELECT * FROM agentic_checkpoints WHERE session=? ORDER BY ts DESC, rowid DESC",
                            (session_id,)).fetchall()
    return [_checkpoint(r) for r in rows]


def get_checkpoint(cid: str, session_id: str | None = None) -> dict | None:
    """체크포인트 1개(session_id 를 주면 그 세션의 것만) / one checkpoint, optionally scoped to a session"""
    with db._conn() as conn:
        row = conn.execute("SELECT * FROM agentic_checkpoints WHERE id=?", (cid,)).fetchone()
    if row is None or (session_id is not None and row["session"] != session_id):
        return None
    return _checkpoint(row)


def trim_checkpoints(session_id: str, keep: int | None = None) -> list[str]:
    """최근 keep 개(기본 MAX_CHECKPOINTS, 부를 때 읽는다)만 남기고 행을 지운다 → 지운 행의 ref(호출부가 agentic_git.drop_ref 로
    지운다). 다른 행이 같은 ref 를 쓰면 그 ref 는 돌려주지 않는다 / keep the newest rows (MAX_CHECKPOINTS read at call time)
    and return the refs of the deleted ones (refs still used are kept)"""
    keep = MAX_CHECKPOINTS if keep is None else keep
    with db._conn() as conn:
        rows = conn.execute("SELECT id, ref FROM agentic_checkpoints WHERE session=? ORDER BY ts DESC, rowid DESC",
                            (session_id,)).fetchall()
        old = rows[max(0, int(keep)):]
        if not old:
            return []
        conn.executemany("DELETE FROM agentic_checkpoints WHERE id=?", [(r["id"],) for r in old])
        still = {r["ref"] for r in rows[:max(0, int(keep))]}
    return [r["ref"] for r in old if r["ref"] and r["ref"] not in still]


def upsert_output(session_id: str, path: str, kind: str, nbytes: int) -> None:
    """세션이 만들거나 고친 파일 기록(경로 = realpath, 내 컴퓨터 폴더 세션은 '<폴더 이름>/<상대 경로>'). 한 번 created 면 나중에
    고쳐도 created 로 둔다.
    Record a file the session created or modified (realpath; '<folder name>/<relative path>' for a browser session);
    once created it stays created after later edits."""
    k = "created" if kind == "created" else "modified"
    with db._conn() as conn:
        conn.execute("INSERT INTO agentic_outputs(session, path, kind, bytes, ts) VALUES(?,?,?,?,?) "
                     "ON CONFLICT(session, path) DO UPDATE SET bytes=excluded.bytes, ts=excluded.ts, "
                     "kind=CASE WHEN agentic_outputs.kind='created' THEN 'created' ELSE excluded.kind END",
                     (session_id, str(path), k, int(nbytes or 0), _now()))


def list_outputs(session_id: str) -> list[dict]:
    """세션의 산출물 {path, kind, bytes, ts}, 최근 것부터 / a session's outputs, newest first"""
    with db._conn() as conn:
        rows = conn.execute("SELECT path, kind, bytes, ts FROM agentic_outputs WHERE session=? ORDER BY ts DESC, rowid DESC",
                            (session_id,)).fetchall()
    return [{"path": r["path"], "kind": r["kind"], "bytes": int(r["bytes"] or 0), "ts": r["ts"]} for r in rows]
