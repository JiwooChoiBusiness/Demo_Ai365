"""업무 자동화 에이전트 저장소(2026-09-22) — 리소스 센터 › 리소스 관리 › 업무 자동화 에이전트 탭의 [+ 추가].

관리자가 외부 시스템 1개를 에이전트 1개로 등록한다. 연결 방식은 둘 중 하나:
  - API : 공통 주소·인증을 넣고 엔드포인트(이름·메서드·경로·입력값 표·샘플 응답)를 직접 작성한다. 입력값 표에서
          JSON Schema 를 만들고(endpoint_schema), [테스트 호출]은 flow_api_call.call 로 실제 호출해 응답을 샘플로 남긴다.
  - MCP : 서버 주소·인증만 넣고 [도구 가져오기]로 도구 목록을 받는다(mcp_servers.discover 재사용). 명세는 읽기 전용이고
          관리자는 도구마다 종류(조회/실행)·사용 여부만 정한다.
기본 제공 에이전트(이메일·교육)는 여기 없다(catalog.WORK_AGENTS 상수). 관리자가 고친 값만 work_agent_builtins 표에 남는다(2026-10-06,
app/builtin_agents.py 가 기본값과 합친다).

관리 센터의 "API · MCP 연결"(워크플로우 전용 커넥터)과는 **별개 저장소**다(사용자 결정 2026-09-22): 클라이언트·검증 코드만
재사용하고 커넥터 행에는 들어가지 않는다. 1차 범위 = 등록·저장·열람 + 접근 권한 업무 자동화 축의 잎
(권한 노드 id = 에이전트 id `agent_*`, 기본 제공 agent_email/agent_edu 와 같은 축). 채팅에서의 실제 호출은 다음 단계.
워크플로우(2026-09-26): 엔드포인트·MCP 도구 1개 = 업무 자동화 작업의 도구 1개(키 wa:<에이전트 id>:<이름>). 팔레트 섹션과 실행기는
as_connector(비밀 없는 커넥터 모양 사본)와 call(저장된 주소·인증으로 1회 호출)을 쓴다.

Work-automation agent store (2026-09-22) — behind [+ Add] on Resource Center › Resource Management › Work-automation agents.
An admin registers one external system as one agent, connected either as **API** (shared base URL/auth plus hand-written
endpoints whose parameter table yields a JSON Schema; [Test call] runs flow_api_call.call and keeps the reply as the sample)
or **MCP** (server URL/auth only; [Fetch tools] reuses mcp_servers.discover; specs stay read-only, the admin picks
kind/enabled per tool). Built-in agents (email, education) are not stored here. This is a **separate store** from the
Admin Center's workflow-only "API · MCP connections" (user decision 2026-09-22): shared client/validation code, no
connector rows. Scope for now = register/save/view plus a leaf on the work-automation permission axis
(node id = agent id `agent_*`, the same axis as the built-in agent_email/agent_edu); calling them from chat comes later.
Workflows (2026-09-26): one endpoint or MCP tool = one tool of an automation task (key wa:<agent id>:<name>). The palette
sections and the runner use as_connector (a secret-free, connector-shaped copy) and call (one call with the stored URL/auth).
"""

from __future__ import annotations

import copy
import json
import re
import sqlite3
import uuid
from urllib.parse import quote

from app import flow_api_call, kst, mcp_servers, skill_files
from app.connectors import SECRET_MASK, ConnectorValidationError
from app.db import DB_PATH

METHODS = ("api", "mcp")                       # 연결 방식 / connection method
HTTP_METHODS = flow_api_call.METHODS
API_AUTH_TYPES = ("none", "api_key", "bearer", "basic")
MCP_AUTH_TYPES = mcp_servers.AUTH_TYPES        # none · bearer · header
KINDS = ("read", "action")
PARAM_TYPES = ("string", "integer", "number", "boolean", "object", "array")
MAX_AGENTS, MAX_NAME, MAX_DESC, MAX_URL = 50, 80, 500, 500
MAX_ENDPOINTS, MAX_PARAMS, MAX_SAMPLE, MAX_PATH = 40, 30, 8000, 300
BUILTIN_IDS = ("agent_email", "agent_edu")
_IDENT_RX = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")      # 엔드포인트 이름 / endpoint name
_PARAM_RX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,59}$")      # 입력값 이름 / parameter name
_PATH_VAR_RX = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")    # 경로 변수 {id} / path variable
_URL_RX = re.compile(r"^(https?://|\{\{\s*base_url\s*\}\})", re.I)


class WorkAgentValidationError(ConnectorValidationError):
    """잘못된 입력 — API 층이 422 로 바꾼다 / bad input, turned into 422 by the API layer"""


def _now() -> str:
    return kst.now_iso()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_work_agents() -> None:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS work_agents(
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              method TEXT NOT NULL DEFAULT 'api',
              enabled INTEGER NOT NULL DEFAULT 1,
              config TEXT NOT NULL,
              pos INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        # 기본 제공 에이전트(이메일 · 교육)에서 관리자가 고친 값(2026-10-06) — 기본값은 코드 상수, 행이 없으면 기본값 그대로(app/builtin_agents.py)
        # Admin edits to the built-in agents (email, education, 2026-10-06); defaults live in code, no row = defaults (app/builtin_agents.py)
        conn.execute("CREATE TABLE IF NOT EXISTS work_agent_builtins(id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)")


def builtin_override(agent_id: str) -> dict | None:
    """기본 제공 에이전트의 고친 값 {data, updated_at} · 없으면 None / the stored edits of a built-in agent, None when untouched"""
    try:
        with _conn() as conn:
            r = conn.execute("SELECT data, updated_at FROM work_agent_builtins WHERE id=?", (agent_id,)).fetchone()
    except sqlite3.OperationalError:   # 표가 아직 없는 오래된 DB = 고친 값 없음 / an older DB without the table = no edits
        return None
    if r is None:
        return None
    try:
        data = json.loads(r["data"] or "{}")
    except ValueError:
        data = {}
    return {"data": data if isinstance(data, dict) else {}, "updated_at": r["updated_at"]}


def save_builtin_override(agent_id: str, data: dict) -> str:
    """고친 값 저장(통째로 바꾼다) → 저장 시각 / store the edits (whole replace) → the save time"""
    now = _now()
    with _conn() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS work_agent_builtins(id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)")
        conn.execute("INSERT OR REPLACE INTO work_agent_builtins(id, data, updated_at) VALUES(?,?,?)",
                     (agent_id, json.dumps(data, ensure_ascii=False), now))
    return now


def delete_builtin_override(agent_id: str) -> bool:
    """[기본값으로 되돌리기] — 고친 값 삭제 / reset to the defaults by dropping the edits"""
    try:
        with _conn() as conn:
            return conn.execute("DELETE FROM work_agent_builtins WHERE id=?", (agent_id,)).rowcount > 0
    except sqlite3.OperationalError:
        return False


def _row(r: sqlite3.Row) -> dict:
    try:
        cfg = json.loads(r["config"] or "{}")
    except ValueError:
        cfg = {}
    return {"id": r["id"], "name": r["name"], "description": r["description"] or "", "method": r["method"] or "api",
            "enabled": bool(r["enabled"]), "config": cfg if isinstance(cfg, dict) else {}, "pos": r["pos"],
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


def list_agents() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM work_agents ORDER BY pos, created_at").fetchall()
    return [_row(r) for r in rows]


def get_agent(agent_id: str) -> dict | None:
    with _conn() as conn:
        r = conn.execute("SELECT * FROM work_agents WHERE id=?", (agent_id,)).fetchone()
    return _row(r) if r else None


def summaries() -> list[dict]:
    """권한 축용 요약 [{id, name}] — access.rebuild_universe 가 p_auto 의 잎으로 쓴다 / permission-axis summary"""
    return [{"id": a["id"], "name": a["name"]} for a in list_agents()]


# ────────────────────────────────────────────────────────
# 검증·정규화 / validation
# ────────────────────────────────────────────────────────

def _str(v, cap: int, what: str) -> str:
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise WorkAgentValidationError(f"{what}은(는) 문자열이어야 합니다")
    v = v.strip()
    if len(v) > cap:
        raise WorkAgentValidationError(f"{what}은(는) {cap}자 이하여야 합니다")
    return v


def _int(v, lo: int, hi: int, default: int, what: str) -> int:
    if v in (None, ""):
        return default
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise WorkAgentValidationError(f"{what}은(는) {lo}~{hi} 사이의 정수여야 합니다")
    if not lo <= n <= hi:
        raise WorkAgentValidationError(f"{what}은(는) {lo}~{hi} 사이의 정수여야 합니다")
    return n


def _restore_key(raw_auth: dict, previous_auth: dict | None) -> dict:
    """마스킹된 키가 그대로 오면 저장된 키 유지, 비우면 삭제 / a masked key keeps the stored one; empty clears it"""
    out = dict(raw_auth)
    key = out.get("key")
    if isinstance(key, str) and SECRET_MASK in key:
        prev = (previous_auth or {}).get("key") or ""
        if not prev:
            raise WorkAgentValidationError("저장된 인증 키가 없습니다. 인증 키를 다시 입력하세요")
        out["key"] = prev
    return out


def _auth(raw, types: tuple, previous_auth: dict | None) -> dict:
    a = _restore_key(raw if isinstance(raw, dict) else {}, previous_auth)
    t = a.get("type") or "none"
    if t not in types:
        raise WorkAgentValidationError(f"인증 방식은 {'/'.join(types)} 중 하나여야 합니다")
    key = _str(a.get("key"), flow_api_call.MAX_SECRET, "인증 키")
    name = _str(a.get("name"), 80, "헤더 이름")
    if t != "none" and not key:
        raise WorkAgentValidationError("인증 키가 비어 있습니다")
    if not name:
        name = "X-API-Key" if t == "api_key" else "Authorization"
    return {"type": t, "key": key if t != "none" else "", "name": name}


def _url(v, what: str) -> str:
    url = _str(v, MAX_URL, what)
    if not url:
        raise WorkAgentValidationError(f"{what}이(가) 비어 있습니다")
    if not _URL_RX.match(url):
        raise WorkAgentValidationError(f"{what}은(는) http:// 또는 https:// 로 시작해야 합니다")
    return url.rstrip("/")


def _params(raw, where: str) -> list[dict]:
    if raw in (None, ""):
        raw = []
    if not isinstance(raw, list):
        raise WorkAgentValidationError(f"{where}은(는) 배열이어야 합니다")
    if len(raw) > MAX_PARAMS:
        raise WorkAgentValidationError(f"입력값은 엔드포인트당 최대 {MAX_PARAMS}개까지입니다")
    out, seen = [], set()
    for i, p in enumerate(raw):
        if not isinstance(p, dict):
            raise WorkAgentValidationError(f"{where}[{i}]은(는) 객체여야 합니다")
        name = _str(p.get("name"), 60, f"{where}[{i}].name")
        if not name:
            continue   # 이름 없는 행은 버린다(편집기의 빈 행) / nameless rows are dropped (editor blanks)
        if not _PARAM_RX.match(name):
            raise WorkAgentValidationError(f"입력값 이름은 영문·숫자·밑줄만 쓸 수 있습니다: {name}")
        if name in seen:
            raise WorkAgentValidationError(f"입력값 이름이 중복됩니다: {name}")
        seen.add(name)
        ty = p.get("type") or "string"
        if ty not in PARAM_TYPES:
            raise WorkAgentValidationError(f"입력값 '{name}'의 타입은 {'/'.join(PARAM_TYPES)} 중 하나여야 합니다")
        out.append({"name": name, "type": ty, "required": bool(p.get("required", False)),
                    "description": _str(p.get("description"), 200, f"입력값 '{name}'의 설명"),
                    "example": _str(p.get("example"), 120, f"입력값 '{name}'의 예시")})
    return out


def _endpoints(raw, where: str = "endpoints") -> list[dict]:
    if raw in (None, ""):
        raw = []
    if not isinstance(raw, list):
        raise WorkAgentValidationError("엔드포인트 목록은 배열이어야 합니다")
    if len(raw) > MAX_ENDPOINTS:
        raise WorkAgentValidationError(f"엔드포인트는 최대 {MAX_ENDPOINTS}개까지입니다")
    out, seen = [], set()
    for i, e in enumerate(raw):
        if not isinstance(e, dict):
            raise WorkAgentValidationError(f"{where}[{i}]은(는) 객체여야 합니다")
        name = _str(e.get("name"), MAX_NAME, f"엔드포인트 {i + 1}의 이름")
        if not name:
            raise WorkAgentValidationError(f"엔드포인트 {i + 1}의 이름이 비어 있습니다")
        if not _IDENT_RX.match(name):
            raise WorkAgentValidationError(f"엔드포인트 이름은 영문으로 시작하고 영문·숫자·밑줄만 쓸 수 있습니다: {name}")
        if name in seen:
            raise WorkAgentValidationError(f"엔드포인트 이름이 중복됩니다: {name}")
        seen.add(name)
        method = str(e.get("method") or "GET").upper()
        if method not in HTTP_METHODS:
            raise WorkAgentValidationError(f"엔드포인트 '{name}'의 메서드는 {'/'.join(HTTP_METHODS)} 중 하나여야 합니다")
        path = _str(e.get("path"), MAX_PATH, f"엔드포인트 '{name}'의 경로")
        if not path:
            raise WorkAgentValidationError(f"엔드포인트 '{name}'의 경로가 비어 있습니다")
        if not path.startswith("/"):
            raise WorkAgentValidationError(f"엔드포인트 '{name}'의 경로는 / 로 시작해야 합니다")
        kind = e.get("kind") or ("read" if method == "GET" else "action")
        if kind not in KINDS:
            raise WorkAgentValidationError(f"엔드포인트 '{name}'의 종류는 read/action 중 하나여야 합니다")
        params = _params(e.get("params"), f"엔드포인트 '{name}'의 입력값")
        # 경로 변수 {id} 는 항상 필수 입력값 — 표에 없으면 문자열 필수로 채워 넣는다 / path variables are always required inputs
        have = {p["name"] for p in params}
        for var in _PATH_VAR_RX.findall(path):
            if var not in have:
                params.append({"name": var, "type": "string", "required": True, "description": "", "example": ""})
                have.add(var)
            else:
                next(p for p in params if p["name"] == var)["required"] = True
        out.append({"name": name, "method": method, "path": path, "kind": kind,
                    "description": _str(e.get("description"), MAX_DESC, f"엔드포인트 '{name}'의 설명"),
                    "params": params, "sample": _str(e.get("sample"), MAX_SAMPLE, f"엔드포인트 '{name}'의 샘플 응답"),
                    "tested_at": _str(e.get("tested_at"), 40, "tested_at")})
    return out


def normalize(raw, previous: dict | None = None) -> dict:
    """에이전트 레코드 검증·정규화 — 잘못된 값은 지목해 거부 / validate and normalize one agent record (reject-and-point)"""
    if not isinstance(raw, dict):
        raise WorkAgentValidationError("에이전트 설정은 객체여야 합니다")
    name = _str(raw.get("name"), MAX_NAME, "에이전트 이름")
    if not name:
        raise WorkAgentValidationError("에이전트 이름이 비어 있습니다")
    desc = _str(raw.get("description"), MAX_DESC, "설명")
    method = raw.get("method") or "api"
    if method not in METHODS:
        raise WorkAgentValidationError("연결 방식은 api/mcp 중 하나여야 합니다")
    cfg = raw.get("config") if isinstance(raw.get("config"), dict) else {}
    prev_cfg = (previous or {}).get("config") or {}
    prev_auth = prev_cfg.get("auth") if (previous or {}).get("method") == method else None
    if method == "api":
        config = {"base_url": _url(cfg.get("base_url"), "기본 주소(Base URL)"),
                  "auth": _auth(cfg.get("auth"), API_AUTH_TYPES, prev_auth),
                  "version": _str(cfg.get("version"), 40, "API 버전"),
                  "timeout": _int(cfg.get("timeout"), 1, 120, 30, "타임아웃"),
                  "endpoints": _endpoints(cfg.get("endpoints"))}
    else:
        try:
            tools = mcp_servers.normalize_tools(cfg.get("tools"))
        except ConnectorValidationError as e:
            raise WorkAgentValidationError(str(e))
        info = cfg.get("server_info") if isinstance(cfg.get("server_info"), dict) else {}
        config = {"url": _url(cfg.get("url"), "MCP 서버 주소"),
                  "auth": _auth(cfg.get("auth"), MCP_AUTH_TYPES, prev_auth),
                  "timeout": _int(cfg.get("timeout"), 1, 120, 30, "타임아웃"),
                  "tools": tools,
                  "server_info": {k: str(info[k])[:120] for k in ("name", "version", "protocol") if info.get(k) is not None},
                  "fetched_at": _str(cfg.get("fetched_at"), 40, "fetched_at")}
    try:
        skill_ids = skill_files.parse_ids(raw.get("skill_ids")) if method == "mcp" else None   # Skill 파일은 MCP 방식만(2026-09-23) / MCP only
    except skill_files.SkillFileError as e:
        raise WorkAgentValidationError(str(e))
    return {"name": name, "description": desc, "method": method, "enabled": bool(raw.get("enabled", True)), "config": config,
            "skill_ids": skill_ids}


# ────────────────────────────────────────────────────────
# 엔드포인트 명세 / endpoint spec
# ────────────────────────────────────────────────────────

def endpoint_schema(ep: dict) -> dict:
    """입력값 표 → JSON Schema(도구 명세와 같은 모양) / parameter table → JSON Schema (same shape as a tool spec)"""
    props, required = {}, []
    for p in ep.get("params") or []:
        prop: dict = {"type": p.get("type") or "string"}
        if p.get("description"):
            prop["description"] = p["description"]
        if p.get("example"):
            prop["examples"] = [p["example"]]
        props[p["name"]] = prop
        if p.get("required"):
            required.append(p["name"])
    return {"type": "object", "properties": props, "required": required}


def param_location(ep: dict, name: str) -> str:
    """입력값이 실리는 자리 — 경로 변수 › GET/DELETE 는 쿼리 › 그 외는 JSON 본문 / where a value goes: path › query › JSON body"""
    if name in _PATH_VAR_RX.findall(ep.get("path") or ""):
        return "path"
    return "query" if (ep.get("method") or "GET") in ("GET", "DELETE") else "body"


def editor_record(a: dict) -> dict:
    """목록·수정 응답 — 인증 키는 마스킹, 엔드포인트마다 명세(input_schema)를 덧붙인다 / masked key, schema per endpoint"""
    out = copy.deepcopy(a)
    auth = (out.get("config") or {}).get("auth") or {}
    if auth.get("key"):
        auth["key"] = SECRET_MASK
    if out.get("method") == "api":
        for ep in out["config"].get("endpoints") or []:
            ep["input_schema"] = endpoint_schema(ep)
            ep["locations"] = {p["name"]: param_location(ep, p["name"]) for p in ep.get("params") or []}
        out["count"] = len(out["config"].get("endpoints") or [])
    else:
        out["count"] = len([t for t in (out["config"].get("tools") or []) if t.get("enabled", True)])
        out["skills"] = skill_files.list_for("work_agent", a.get("id") or "")   # Skill 파일 목록(2026-09-23) / attached skill files
    return out


# ────────────────────────────────────────────────────────
# 저장 / persistence
# ────────────────────────────────────────────────────────

def _check_unique_name(conn: sqlite3.Connection, name: str, exclude_id: str | None = None) -> None:
    row = conn.execute("SELECT id FROM work_agents WHERE lower(name)=lower(?)", (name,)).fetchone()
    if row and row["id"] != exclude_id:
        raise WorkAgentValidationError(f"같은 이름의 에이전트가 이미 있습니다: {name}")


def _write(conn: sqlite3.Connection, aid: str, d: dict, now: str, pos: int, created: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO work_agents(id, name, description, method, enabled, config, pos, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (aid, d["name"], d["description"], d["method"], 1 if d["enabled"] else 0,
         json.dumps(d["config"], ensure_ascii=False), pos, created, now))


def _skills_check(ids: list[str], agent_id: str | None) -> None:
    """Skill 파일이 붙일 수 있는 것인지(없거나 남의 것이면 422) / the listed skill files must exist and be free or ours"""
    try:
        skill_files.ensure_attachable(ids, "work_agent", agent_id)
    except skill_files.SkillFileError as e:
        raise WorkAgentValidationError(str(e))


def create(raw: dict) -> dict:
    d = normalize(raw)
    ids = d.get("skill_ids") or []
    _skills_check(ids, None)
    with _conn() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM work_agents").fetchone()["n"]
        if n >= MAX_AGENTS:
            raise WorkAgentValidationError(f"업무 자동화 에이전트는 최대 {MAX_AGENTS}개까지 등록할 수 있습니다")
        _check_unique_name(conn, d["name"])
        # 권한 노드 id = 에이전트 id. 'agent_' 접두는 권한 편집기가 업무 자동화 축으로 판별하는 규칙(isAutoNode)과 맞춘다.
        # The permission node id is the agent id; the 'agent_' prefix matches the editor's automation-axis rule (isAutoNode).
        aid = "agent_" + uuid.uuid4().hex[:8]
        now = _now()
        _write(conn, aid, d, now, n, now)
    skill_files.attach("work_agent", aid, ids)   # 올려 둔 Skill 파일을 이 에이전트에 붙인다(2026-09-23) / attach the uploaded skill files
    return get_agent(aid)


def update(agent_id: str, raw: dict) -> dict | None:
    prev = get_agent(agent_id)
    if prev is None:
        return None
    d = normalize(raw, prev)
    ids = d.get("skill_ids")   # None = 파일 목록 유지 / None keeps the files
    if ids is not None:
        _skills_check(ids, agent_id)
    with _conn() as conn:
        _check_unique_name(conn, d["name"], exclude_id=agent_id)
        _write(conn, agent_id, d, _now(), prev["pos"], prev["created_at"])
    if ids is not None:
        skill_files.attach("work_agent", agent_id, ids)
    return get_agent(agent_id)


def delete(agent_id: str) -> bool:
    with _conn() as conn:
        n = conn.execute("DELETE FROM work_agents WHERE id=?", (agent_id,)).rowcount
    if n > 0:
        skill_files.delete_for("work_agent", agent_id)   # 붙어 있던 Skill 파일도 함께 / the attached skill files go too
    return n > 0


# ────────────────────────────────────────────────────────
# 서버 접속 / talking to the systems
# ────────────────────────────────────────────────────────

def discover_tools(url: str, auth: dict | None, timeout: int = 30, previous_tools: list | None = None, *, transport=None) -> dict:
    """MCP 도구 목록 조회(저장 없음) + 관리자 설정 병합 / fetch the MCP tool list (no save) and keep per-tool admin settings"""
    try:
        out = mcp_servers.discover(url, auth, timeout, transport=transport)
    except ConnectorValidationError as e:
        raise WorkAgentValidationError(str(e))
    tools, gone = mcp_servers.merge_tools(out["tools"], previous_tools)
    return {"server_info": out["server_info"], "tools": tools, "removed": gone, "skipped": out["skipped"],
            "fetched_at": _now()}


def _flow_auth(auth: dict) -> dict:
    t = auth.get("type") or "none"
    return {"type": t, "key": auth.get("key") or "", "in": "header",
            "name": auth.get("name") or ("X-API-Key" if t == "api_key" else "Authorization")}


def _coerce(v, ty: str):
    """테스트 값(문자열) → 입력값 타입에 맞는 JSON 값. 못 바꾸면 문자열 그대로 / test text → typed JSON value, else the string"""
    if not isinstance(v, str):
        return v
    s = v.strip()
    try:
        if ty == "integer":
            return int(s)
        if ty == "number":
            return float(s)
        if ty == "boolean":
            return s.lower() in ("true", "1", "yes", "on")
        if ty in ("object", "array"):
            return json.loads(s)
    except ValueError:
        pass
    return v


def _empty_result(error: str | None = None) -> dict:
    """호출 전 실패의 결과 틀(flow_api_call.call 과 같은 모양) / result frame for failures before any call (flow_api_call.call shape)"""
    return {"ok": False, "status": None, "elapsed_ms": 0, "url": "", "request": {}, "response_headers": {}, "body_text": "",
            "json": None, "result": None, "result_text": "", "outputs": {}, "error": error, "attempts": 0, "variables": {}}


def _call_endpoint(config: dict, ep: dict, values: dict | None, *, keep_body: int = flow_api_call.BODY_KEEP) -> dict:
    """엔드포인트 1개 실제 호출(테스트 호출·워크플로우 실행 공용, 2026-09-26 분리) — 경로 변수·쿼리·JSON 본문을 자리별로 채워
    flow_api_call.call 에 넘기고 그 결과를 그대로 돌려준다. 쿼리·본문 값은 {{input.<이름>}} 자리표시자 + 변수로 넘겨(커넥터 실행과
    같은 방식) 값 안의 {{...}} 가 다시 치환되지 않게 한다. 문자열 값은 문자열로, 타입이 있는 값은 그 JSON 타입으로 실린다."""
    # Call one endpoint (shared by the test call and workflow runs; split out 2026-09-26): fill path variables, query and JSON
    # body by location and return flow_api_call.call's result as is. Query/body values travel as {{input.<name>}} placeholders
    # plus variables (same as the connector runtime), so a {{...}} inside a value is never substituted again. String values
    # stay strings; typed values keep their JSON type.
    values = {k: v for k, v in (values or {}).items() if isinstance(k, str)}
    path = ep.get("path") or ""
    for var in _PATH_VAR_RX.findall(path):
        v = values.get(var)
        if v in (None, ""):
            return _empty_result(f"경로 변수 '{var}' 값이 필요합니다")
        path = path.replace("{" + var + "}", quote(flow_api_call.to_text(v), safe=""))
    query, body_parts, variables = [], [], {}
    for p in ep.get("params") or []:
        loc = param_location(ep, p["name"])
        v = values.get(p["name"])
        if v in (None, ""):
            if p.get("required") and loc != "path":
                return _empty_result(f"필수 입력값 '{p['name']}' 값이 필요합니다")
            continue
        if loc == "path":
            continue
        slot = "{{input." + p["name"] + "}}"
        if loc == "query":
            variables["input." + p["name"]] = v
            query.append({"name": p["name"], "value": slot})
        else:
            typed = _coerce(v, p.get("type") or "string")
            variables["input." + p["name"]] = typed
            # 문자열은 따옴표 안 자리(이스케이프), 타입 있는 값은 따옴표 밖 자리(JSON 타입 보존) / quoted slot for text, bare slot keeps the type
            body_parts.append(json.dumps(p["name"]) + ": " + (f'"{slot}"' if isinstance(typed, str) else slot))
    cfg = {"url": (config.get("base_url") or "").rstrip("/") + path, "method": ep.get("method") or "GET",
           "timeout": int(config.get("timeout") or 30), "auth": _flow_auth(config.get("auth") or {}),
           "headers": [{"name": "Accept", "value": "application/json"}], "params": query,
           "body": {"content_type": "application/json" if body_parts else "none",
                    "payload": ("{" + ", ".join(body_parts) + "}") if body_parts else ""},
           "response": {"format": "auto", "ok_status": "2xx", "path": "", "outputs": [], "on_error": "continue",
                        "retries": 0, "retry_wait": 0}}
    return flow_api_call.call(cfg, flow_api_call.build_ctx(vars=variables), keep_body=keep_body)


def test_endpoint(config: dict, ep: dict, values: dict | None, *, keep_body: int = flow_api_call.TEST_BODY_KEEP) -> dict:
    """엔드포인트 1개를 테스트 값으로 실제 호출 — 경로 변수·쿼리·JSON 본문을 자리별로 채워 flow_api_call.call 에 넘긴다.
    결과는 상태·소요 시간·응답 본문(비밀 가림)이고 저장하지 않는다(샘플 응답은 편집기가 저장 때 싣는다)."""
    # Call one endpoint with the test values — path variables, query and JSON body filled by location, then flow_api_call.call.
    # Returns status/elapsed/body (secrets masked) without saving (the editor stores the sample response on save).
    res = _call_endpoint(config, ep, values, keep_body=keep_body)
    return {"ok": bool(res.get("ok")), "status": res.get("status"), "elapsed_ms": res.get("elapsed_ms") or 0,
            "url": res.get("url") or "", "error": res.get("error"), "request": res.get("request") or {},
            "body_text": res.get("body_text") or "", "json": res.get("json")}


# ────────────────────────────────────────────────────────
# 워크플로우 도구(2026-09-26) — 등록 에이전트의 엔드포인트·MCP 도구 1개 = 도구 1개(키 wa:<에이전트 id>:<이름>)
# Workflow tools (2026-09-26): one endpoint or MCP tool of a registered agent = one tool (key wa:<agent id>:<name>)
# ────────────────────────────────────────────────────────

TOOL_PREFIX = "wa:"


def tool_key(agent_id: str, name: str) -> str:
    """도구 키 = 워크플로우 노드 resources 값·팔레트 항목 key / the tool key used by node resources and palette items"""
    return f"{TOOL_PREFIX}{agent_id}:{name}"


def parse_key(key) -> tuple[str, str] | None:
    """'wa:<에이전트 id>:<이름>' → (에이전트 id, 이름). 모양이 다르면 None(key.split(':', 2)) / parse a tool key, None when malformed"""
    if not isinstance(key, str) or not key.startswith(TOOL_PREFIX):
        return None
    parts = key.split(":", 2)
    if len(parts) != 3 or not parts[1].strip() or not parts[2].strip():
        return None
    return parts[1], parts[2]


def tools_of(agent: dict | None) -> list[dict]:
    """에이전트의 도구 목록(API 엔드포인트·MCP 도구 공통 모양) — [{name, kind, description, input_schema, output_schema, enabled,
    unsupported}]. API 엔드포인트는 입력값 표에서 명세를 만들고(출력 명세 없음, unsupported []), MCP 도구는 저장된 스냅샷을 쓴다
    (종류가 없으면 read, unsupported = 명세를 단순화하며 못 옮긴 항목 — 편집기의 "명세 단순화" 경고 재료)."""
    # The agent's tools in one shape for API endpoints and MCP tools. API endpoints derive the schema from the parameter
    # table (no output schema, unsupported []); MCP tools use the stored snapshot (kind falls back to read; unsupported = the
    # spec parts lost while simplifying, which drive the editor's "simplified spec" warning).
    cfg = (agent or {}).get("config") or {}
    out: list[dict] = []
    if (agent or {}).get("method") == "mcp":
        for t in cfg.get("tools") or []:
            if not isinstance(t, dict) or not t.get("name"):
                continue
            schema = t.get("input_schema") if isinstance(t.get("input_schema"), dict) else {"type": "object", "properties": {}, "required": []}
            unsupported = t.get("unsupported") if isinstance(t.get("unsupported"), list) else []
            out.append({"name": t["name"], "kind": t.get("kind") if t.get("kind") in KINDS else "read",
                        "description": (t.get("description_override") or t.get("description") or "").strip(),
                        "input_schema": schema,
                        "output_schema": t.get("output_schema") if isinstance(t.get("output_schema"), dict) else None,
                        "enabled": bool(t.get("enabled", True)),
                        "unsupported": [u for u in unsupported if isinstance(u, str)]})
        return out
    for ep in cfg.get("endpoints") or []:
        if not isinstance(ep, dict) or not ep.get("name"):
            continue
        kind = ep.get("kind") if ep.get("kind") in KINDS else ("read" if (ep.get("method") or "GET") == "GET" else "action")
        out.append({"name": ep["name"], "kind": kind, "description": (ep.get("description") or "").strip(),
                    "input_schema": endpoint_schema(ep), "output_schema": None, "enabled": True, "unsupported": []})
    return out


def as_connector(agent: dict | None, name: str) -> dict | None:
    """등록 에이전트의 도구 1개 → 워크플로우 실행기가 커넥터처럼 다루는 사본(비밀 없음). 없는 에이전트·도구는 None.
    api = {work_agent 표지, tool_contract(입력 명세), input_docs(입력값 설명)} 라서 tool_contracts.contract·prepare_inputs·
    flow_api_call.input_specs 가 MCP 도구 커넥터와 같은 길로 동작한다. enabled = 에이전트 사용 ∧ 도구 사용."""
    # One tool of a registered agent → a secret-free copy the workflow runner treats like a connector; None when the agent or
    # tool is missing. api = {work_agent marker, tool_contract (input schema), input_docs}, so tool_contracts.contract,
    # prepare_inputs and flow_api_call.input_specs follow the MCP-tool-connector path. enabled = agent enabled AND tool enabled.
    if not agent or not isinstance(name, str):
        return None
    tool = next((t for t in tools_of(agent) if t["name"] == name), None)
    if tool is None:
        return None
    schema = copy.deepcopy(tool["input_schema"])
    kind = tool["kind"]
    return {"id": tool_key(agent["id"], name), "name": f"{agent.get('name') or agent['id']} · {name}",
            "description": tool["description"], "kind": kind, "source": "work_agent",
            "agent_id": agent["id"], "method": agent.get("method") or "api",
            "enabled": bool(agent.get("enabled", True)) and bool(tool["enabled"]),
            "api": {"name": name,
                    "work_agent": {"agent_id": agent["id"], "agent_name": agent.get("name") or "",
                                   "method": agent.get("method") or "api", "tool": name},
                    "tool_contract": {"version": 1, "input_schema": schema, "retry_safe": kind == "read"},
                    "input_docs": mcp_servers.input_docs_of(schema)}}


def connector_for_key(key) -> dict | None:
    """도구 키 → as_connector 사본(저장소 조회). 키 모양이 틀리거나 없으면 None / tool key → the as_connector copy, None when missing"""
    parsed = parse_key(key)
    if parsed is None:
        return None
    return as_connector(get_agent(parsed[0]), parsed[1])


def call(conn: dict, inputs: dict | None, *, keep_body: int = flow_api_call.BODY_KEEP, transport=None) -> dict:
    """워크플로우 실행 — 도구 1개 호출(tool_runtime.call_connector 가 source='work_agent' 를 만나면 여기로 온다). 주소·인증은
    저장된 에이전트에서 다시 읽는다(사본에는 비밀이 없다). API 는 _call_endpoint, MCP 는 mcp_servers.call_tool_at 1회.
    결과는 flow_api_call.call 과 같은 모양이고 에이전트 인증 키는 가린다(오류 본문에 키가 되돌아와도 남지 않게)."""
    # Workflow run: call one tool (tool_runtime.call_connector lands here for source='work_agent'). URL/auth are re-read from
    # the stored agent (the copy carries no secret). API → _call_endpoint, MCP → one mcp_servers.call_tool_at. The result has
    # flow_api_call.call's shape and the agent's key is redacted (even when an error body echoes it back).
    parsed = parse_key((conn or {}).get("id"))
    if parsed is None:
        return _empty_result("업무 자동화 에이전트 도구 형식이 올바르지 않습니다")
    agent_id, name = parsed
    agent = get_agent(agent_id)
    if agent is None:
        return _empty_result("업무 자동화 에이전트가 삭제되었습니다. 리소스 관리에서 다시 등록해 주세요")
    if not agent.get("enabled", True):
        return _empty_result(f"업무 자동화 에이전트 '{agent['name']}'이(가) 비활성입니다")
    cfg = agent.get("config") or {}
    secret = str((cfg.get("auth") or {}).get("key") or "")
    if agent.get("method") == "mcp":
        tool = next((t for t in cfg.get("tools") or [] if isinstance(t, dict) and t.get("name") == name), None)
        if tool is None:
            return _empty_result(f"에이전트 '{agent['name']}'에 도구 '{name}'이(가) 없습니다")
        if not tool.get("enabled", True):
            return _empty_result(f"에이전트 '{agent['name']}'의 도구 '{name}'은(는) 사용 중지 상태입니다")
        res = mcp_servers.call_tool_at(cfg.get("url") or "", cfg.get("auth"), int(cfg.get("timeout") or 30), name, inputs,
                                       keep_body=keep_body, transport=transport)
    else:
        ep = next((e for e in cfg.get("endpoints") or [] if isinstance(e, dict) and e.get("name") == name), None)
        if ep is None:
            return _empty_result(f"에이전트 '{agent['name']}'에 엔드포인트 '{name}'이(가) 없습니다")
        res = _call_endpoint(cfg, ep, inputs, keep_body=keep_body)
    return flow_api_call.redact(res, secret)
