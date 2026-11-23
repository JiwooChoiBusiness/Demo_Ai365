"""MCP 서버 저장소(2026-09-15) — 관리 센터 "API · MCP 연결"의 MCP 등록 단위. 서버 1개 = 주소·인증·도구 목록 스냅샷.
도구는 서버에서 가져온 명세(tools/list)를 저장해 두고, 도구마다 사용 여부·종류(조회/실행) 를 관리자가 정한다.

  - 도구 1개 = 커넥터 1건(connectors 테이블, source='mcp', id 는 서버·도구 이름에서 결정적으로 생성) → 권한 축 p_conn 의 잎,
    워크플로우 외부 도구 작업의 선택지, 실행 확인 팝업·질문 카드·입력값 바인딩이 API 와 같은 경로를 탄다.
  - 도구 커넥터의 api 설정 = {mcp:{server_id, tool…}, tool_contract(입력 명세), input_docs(표시용), response(결과 전달)}.
  - 비밀(auth.key)은 서버 레코드에만 있고 도구 커넥터에는 없다. 목록·수정 응답은 마스킹(connectors.SECRET_MASK).
  - discover(): 저장 없이 서버에 접속해 도구 목록을 가져온다. sync_tools(): 스냅샷 ↔ 커넥터 행 동기화(추가·갱신·삭제).
  - call_tool(): 실행기(tool_runtime.call_connector)가 도구 커넥터를 만나면 여기로 온다 — 서버 주소·인증으로 tools/call.

MCP server store (2026-09-15) — the MCP registration unit of Admin Center › "API · MCP connections". One server = URL,
auth and a snapshot of its tool list; per tool the admin decides enabled and kind (read/action).
  - One tool = one connector row (source='mcp', deterministic id from server + tool name) → a p_conn leaf, a choice in
    the workflow external-tool task; the run popup, question cards and input bindings reuse the API paths.
  - A tool connector's api config = {mcp:{server_id, tool…}, tool_contract (input schema), input_docs (display), response}.
  - Secrets live only on the server record (never on tool connectors); list/edit responses are masked.
  - discover() fetches the tool list without saving; sync_tools() reconciles the snapshot with connector rows.
  - call_tool() is where tool_runtime.call_connector lands for a tool connector — tools/call with the server's URL/auth.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
import time
import uuid

from app import flow_api_call, kst, mcp_client, skill_files
from app.connectors import CATEGORIES, SECRET_MASK, ConnectorValidationError
from app.db import DB_PATH

AUTH_TYPES = ("none", "bearer", "header")
MAX_SERVERS = 20
MAX_NAME, MAX_DESC, MAX_URL, MAX_HEADER = 80, 500, 500, 80
MAX_TOOLS = mcp_client.MAX_TOOLS
KINDS = ("read", "action")
MAX_OUT_SCHEMA_CHARS = 20000   # 출력 명세 보존 상한(문자) / cap for the stored output schema


class MCPValidationError(ConnectorValidationError):
    pass


def _now() -> str:
    return kst.now_iso()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_mcp_servers() -> None:
    """테이블 생성(멱등) / create the table (idempotent)"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mcp_servers(
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              category TEXT NOT NULL DEFAULT 'other',
              url TEXT NOT NULL,
              auth TEXT NOT NULL DEFAULT '{}',
              timeout INTEGER NOT NULL DEFAULT 30,
              enabled INTEGER NOT NULL DEFAULT 1,
              tools TEXT NOT NULL DEFAULT '[]',
              server_info TEXT NOT NULL DEFAULT '{}',
              fetched_at TEXT NOT NULL DEFAULT '',
              pos INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )


def _loads(s, default):
    try:
        v = json.loads(s or "")
        return v if isinstance(v, type(default)) else default
    except ValueError:
        return default


def _row(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "name": r["name"], "description": r["description"] or "", "category": r["category"] or "other",
            "url": r["url"], "auth": _loads(r["auth"], {}), "timeout": int(r["timeout"] or 30), "enabled": bool(r["enabled"]),
            "tools": _loads(r["tools"], []), "server_info": _loads(r["server_info"], {}), "fetched_at": r["fetched_at"] or "",
            "pos": r["pos"], "created_at": r["created_at"], "updated_at": r["updated_at"]}


def list_servers() -> list[dict]:
    try:
        with _conn() as conn:
            rows = conn.execute("SELECT * FROM mcp_servers ORDER BY pos, created_at").fetchall()
    except sqlite3.OperationalError:   # 테이블 미생성(부팅 순서·격리 DB) → 빈 목록 / table not created yet (boot order, isolated DB) → empty
        return []
    return [_row(r) for r in rows]


def get_server(server_id: str) -> dict | None:
    try:
        with _conn() as conn:
            r = conn.execute("SELECT * FROM mcp_servers WHERE id=?", (server_id,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return _row(r) if r else None


# ────────────────────────────────────────────────────────
# 마스킹 / masking
# ────────────────────────────────────────────────────────

def secret_of(server: dict | None) -> str:
    return str(((server or {}).get("auth") or {}).get("key") or "")


def editor_record(s: dict) -> dict:
    """목록·수정 응답 — 인증 키는 마스킹, 도구 스냅샷은 그대로 / list/edit payload: masked key, tools as stored"""
    out = copy.deepcopy(s)
    if secret_of(s):
        out["auth"]["key"] = SECRET_MASK
    out["tool_count"] = len(s.get("tools") or [])
    out["enabled_tools"] = len([t for t in (s.get("tools") or []) if t.get("enabled", True)])
    out["skills"] = skill_files.list_for("mcp", s.get("id") or "")   # Skill 파일 목록(2026-09-23) / attached skill files
    return out


def _restore_key(raw_auth: dict, previous: dict | None) -> dict:
    """마스킹된 키가 그대로 오면 저장된 키 유지, 비우면 삭제 / a masked key keeps the stored one; empty clears it"""
    a = dict(raw_auth or {})
    key = a.get("key")
    if isinstance(key, str) and SECRET_MASK in key:
        prev = secret_of(previous)
        if not prev:
            raise MCPValidationError("저장된 인증 키가 없습니다. 키를 다시 입력하세요")
        if key != SECRET_MASK:
            raise MCPValidationError("가려진 인증 키가 포함된 값을 변경하려면 키를 다시 입력하세요")
        a["key"] = prev
    return a


# ────────────────────────────────────────────────────────
# 검증 / validation
# ────────────────────────────────────────────────────────

def _str(v, cap: int, what: str) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise MCPValidationError(f"{what}은(는) 문자열이어야 합니다")
    v = v.strip()
    if len(v) > cap:
        raise MCPValidationError(f"{what}은(는) {cap}자 이하여야 합니다")
    return v


def _out_schema(v):
    """출력 명세는 객체이고 너무 크지 않을 때만 보존(표시 전용) / keep the output schema only when it is an object of sane size (display only)"""
    if not isinstance(v, dict):
        return None
    try:
        return v if len(json.dumps(v, ensure_ascii=False)) <= MAX_OUT_SCHEMA_CHARS else None
    except (TypeError, ValueError):
        return None


def normalize_tools(raw_tools, where: str = "tools") -> list[dict]:
    """도구 스냅샷 검증 — 명세는 mcp_client.normalize_schema 로 다시 단순화하고 tool_contracts.validate_schema 로 확인."""
    # Validate the tool snapshot — schemas are re-simplified and checked with tool_contracts.validate_schema.
    from app.tool_contracts import validate_schema
    from app.execution import PlanError
    if raw_tools in (None, ""):
        raw_tools = []
    if not isinstance(raw_tools, list):
        raise MCPValidationError(f"{where}은(는) 배열이어야 합니다")
    if len(raw_tools) > MAX_TOOLS:
        raise MCPValidationError(f"{where}은(는) 최대 {MAX_TOOLS}개까지입니다")
    out, seen = [], set()
    for i, t in enumerate(raw_tools):
        if not isinstance(t, dict):
            raise MCPValidationError(f"{where}[{i}]은(는) 객체여야 합니다")
        name = _str(t.get("name"), 120, f"{where}[{i}].name")
        if not name or not mcp_client._NAME_RX.match(name):
            raise MCPValidationError(f"{where}[{i}].name 이 비어 있거나 형식이 올바르지 않습니다")
        if name in seen:
            continue   # 중복 이름은 첫 항목만 / duplicates keep the first row
        seen.add(name)
        schema, unsupported = mcp_client.normalize_schema(t.get("input_schema") or {"type": "object", "properties": {}})
        try:
            validate_schema(schema)
        except PlanError as e:
            raise MCPValidationError(f"{where}[{i}].input_schema: {e}")
        kind = t.get("kind") or t.get("kind_default") or "action"
        if kind not in KINDS:
            raise MCPValidationError(f"{where}[{i}].kind 는 read/action 중 하나여야 합니다")
        ann_in = t.get("annotations") if isinstance(t.get("annotations"), dict) else {}
        ann = {k: bool(ann_in[k]) for k in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
               if isinstance(ann_in.get(k), bool)}
        extra = [u for u in (t.get("unsupported") or []) if isinstance(u, str)] if isinstance(t.get("unsupported"), list) else []
        out.append({"name": name, "title": _str(t.get("title"), 80, f"{where}[{i}].title") or name,
                    "description": _str(t.get("description"), MAX_DESC, f"{where}[{i}].description"),
                    "description_override": _str(t.get("description_override"), MAX_DESC, f"{where}[{i}].description_override"),
                    "input_schema": schema, "output_schema": _out_schema(t.get("output_schema")), "annotations": ann, "kind": kind,
                    "enabled": bool(t.get("enabled", True)),
                    "unsupported": (unsupported or extra)[:20]})
    return out


def normalize(raw, previous: dict | None = None) -> dict:
    """서버 레코드 검증·정규화 — 잘못된 값은 지목해 거부 / validate and normalize a server record (reject-and-point)"""
    if not isinstance(raw, dict):
        raise MCPValidationError("MCP 서버 설정은 객체여야 합니다")
    name = _str(raw.get("name"), MAX_NAME, "서버 이름")
    if not name:
        raise MCPValidationError("MCP 서버 이름이 비어 있습니다")
    desc = _str(raw.get("description"), MAX_DESC, "설명")
    category = raw.get("category") or "other"
    if category not in CATEGORIES:
        raise MCPValidationError(f"분류는 {'/'.join(CATEGORIES)} 중 하나여야 합니다")
    url = _str(raw.get("url"), MAX_URL, "서버 주소")
    if not url:
        raise MCPValidationError("MCP 서버 주소가 비어 있습니다")
    if not re.match(r"^(https?://|\{\{\s*base_url\s*\}\})", url, re.I):
        raise MCPValidationError("MCP 서버 주소는 http:// 또는 https:// 로 시작해야 합니다")
    a_in = _restore_key(raw.get("auth") if isinstance(raw.get("auth"), dict) else {}, previous)
    a_type = a_in.get("type") or "none"
    if a_type not in AUTH_TYPES:
        raise MCPValidationError(f"인증 방식은 {'/'.join(AUTH_TYPES)} 중 하나여야 합니다")
    key = _str(a_in.get("key"), flow_api_call.MAX_SECRET, "인증 키")
    header = _str(a_in.get("name"), MAX_HEADER, "헤더 이름") or "Authorization"
    if a_type != "none" and not key:
        raise MCPValidationError("인증 키가 비어 있습니다")
    auth = {"type": a_type, "key": key if a_type != "none" else "", "name": header}
    try:
        timeout = int(raw.get("timeout") if raw.get("timeout") not in (None, "") else 30)
    except (TypeError, ValueError):
        raise MCPValidationError("타임아웃은 1~120 사이의 정수여야 합니다")
    if not 1 <= timeout <= 120:
        raise MCPValidationError("타임아웃은 1~120 사이의 정수여야 합니다")
    tools = normalize_tools(raw.get("tools"))
    info = raw.get("server_info") if isinstance(raw.get("server_info"), dict) else {}
    info = {k: str(info[k])[:120] for k in ("name", "version", "protocol") if info.get(k) is not None}
    try:
        skill_ids = skill_files.parse_ids(raw.get("skill_ids"))   # None = 그대로 / None keeps the current files
    except skill_files.SkillFileError as e:
        raise MCPValidationError(str(e))
    return {"name": name, "description": desc, "category": category, "url": url, "auth": auth, "timeout": timeout,
            "enabled": bool(raw.get("enabled", True)), "tools": tools, "server_info": info,
            "fetched_at": _str(raw.get("fetched_at"), 40, "fetched_at"), "skill_ids": skill_ids}


# ────────────────────────────────────────────────────────
# 도구 커넥터 동기화 / tool-connector sync
# ────────────────────────────────────────────────────────

def tool_connector_id(server_id: str, tool_name: str) -> str:
    """서버·도구 이름에서 결정적으로 — 다시 가져와도 권한·바인딩이 유지된다 / deterministic, so re-fetches keep permissions and bindings"""
    return "cn_m" + hashlib.sha1(f"{server_id}:{tool_name}".encode("utf-8")).hexdigest()[:11]


def _example_of(prop: dict) -> str:
    ex = prop.get("examples")
    if isinstance(ex, list) and ex:
        v = ex[0]
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return ""


def _default_of(prop: dict) -> str:
    if "default" not in prop or prop["default"] is None:
        return ""
    v = prop["default"]
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def input_docs_of(schema: dict) -> list[dict]:
    """도구 입력 명세 → 입력값 설명 행(API 와 같은 모양) / tool input schema → input-doc rows (same shape as APIs)"""
    rows = []
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    for name, prop in props.items():
        row = {"name": name, "description": (prop.get("description") or "")[:flow_api_call.MAX_DOC_DESC],
               "example": _example_of(prop)[:flow_api_call.MAX_DOC_EXAMPLE], "default": _default_of(prop)[:flow_api_call.MAX_DOC_DEFAULT],
               "type": prop.get("type") or "string", "required": name in required}
        if isinstance(prop.get("enum"), list):
            row["enum"] = prop["enum"]
        rows.append(row)
    return rows[:flow_api_call.MAX_INPUT_DOCS]


def tool_api_config(server: dict, tool: dict) -> dict:
    """도구 커넥터의 api 설정 — 실행기·편집기·팝업이 읽는 모양(API 설정과 호환) / the tool connector's api config"""
    schema = copy.deepcopy(tool.get("input_schema") or {"type": "object", "properties": {}, "required": []})
    return {"name": tool.get("title") or tool["name"],
            "mcp": {"server_id": server["id"], "server_name": server.get("name") or "", "tool": tool["name"],
                    "title": tool.get("title") or tool["name"], "annotations": tool.get("annotations") or {},
                    "unsupported": tool.get("unsupported") or []},
            "tool_contract": {"version": 1, "input_schema": schema, "retry_safe": tool.get("kind") == "read"},
            "input_docs": input_docs_of(schema),
            "response": {"format": "auto", "path": "", "outputs": [], "ok_status": "2xx", "on_error": "continue",
                         "retries": 0, "retry_wait": 2, "preview_chars": 1200, "include_in_answer": True},
            "test": None}


def tool_connector_row(server: dict, tool: dict) -> dict:
    """도구 1개 → 커넥터 행(이름 = "서버 › 도구", 설명 = 관리자 덮어쓰기 > 서버 설명 > 제목)."""
    # One tool → a connector row (name = "server › tool"; description = override > server text > title).
    title = tool.get("title") or tool["name"]
    name = f"{server['name']} › {title}"[:80]
    desc = (tool.get("description_override") or tool.get("description") or f"MCP 도구 {title}")[:500]
    return {"id": tool_connector_id(server["id"], tool["name"]), "name": name, "description": desc,
            "category": server.get("category") or "other", "kind": tool.get("kind") or "action",
            "enabled": bool(server.get("enabled", True)) and bool(tool.get("enabled", True)),
            "source": "mcp", "api": tool_api_config(server, tool)}


def sync_tools(server: dict) -> dict:
    """스냅샷 ↔ 커넥터 행 동기화 → {"added": [...], "updated": [...], "removed": [...]}(도구 이름)."""
    # Reconcile the snapshot with connector rows → names added / updated / removed.
    from app import connectors as connector_store
    existing = {c["id"]: c for c in connector_store.list_connectors()
                if c.get("source") == "mcp" and ((c.get("api") or {}).get("mcp") or {}).get("server_id") == server["id"]}
    added, updated, keep = [], [], set()
    for tool in server.get("tools") or []:
        row = tool_connector_row(server, tool)
        keep.add(row["id"])
        if row["id"] in existing:
            updated.append(tool["name"])
        else:
            added.append(tool["name"])
        connector_store.upsert_mcp_tool(row)
    removed = []
    for cid, c in existing.items():
        if cid not in keep:
            connector_store.delete(cid)
            removed.append(((c.get("api") or {}).get("mcp") or {}).get("tool") or cid)
    return {"added": added, "updated": updated, "removed": removed}


def merge_tools(discovered: list[dict], previous: list[dict] | None) -> tuple[list[dict], list[str]]:
    """다시 가져온 명세에 관리자 설정(사용·종류·설명 덮어쓰기)을 입힌다 → (도구 목록, 사라진 도구 이름)."""
    # Re-fetched specs keep the admin's per-tool settings → (tools, names that disappeared).
    prev = {t["name"]: t for t in (previous or []) if isinstance(t, dict) and t.get("name")}
    out = []
    for t in discovered:
        p = prev.get(t["name"])
        merged = dict(t)
        merged["kind"] = (p or {}).get("kind") or t.get("kind_default") or "action"
        merged["enabled"] = bool((p or {}).get("enabled", True))
        merged["description_override"] = (p or {}).get("description_override") or ""
        out.append(merged)
    gone = [n for n in prev if n not in {t["name"] for t in discovered}]
    return out, gone


# ────────────────────────────────────────────────────────
# 저장 / persistence
# ────────────────────────────────────────────────────────

def _write(conn: sqlite3.Connection, sid: str, d: dict, now: str, pos: int | None = None, created: str | None = None) -> None:
    fields = (d["name"], d["description"], d["category"], d["url"], json.dumps(d["auth"], ensure_ascii=False), d["timeout"],
              1 if d["enabled"] else 0, json.dumps(d["tools"], ensure_ascii=False), json.dumps(d["server_info"], ensure_ascii=False),
              d.get("fetched_at") or "")
    if created is None:
        conn.execute("INSERT INTO mcp_servers(id, name, description, category, url, auth, timeout, enabled, tools, server_info,"
                     " fetched_at, pos, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (sid, *fields, pos or 0, now, now))
    else:
        conn.execute("UPDATE mcp_servers SET name=?, description=?, category=?, url=?, auth=?, timeout=?, enabled=?, tools=?,"
                     " server_info=?, fetched_at=?, updated_at=? WHERE id=?", (*fields, now, sid))


def _check_unique_name(conn: sqlite3.Connection, name: str, exclude_id: str | None = None) -> None:
    """같은 이름의 서버 거부(2026-09-16 디자인 점검): 서버 이름이 도구 커넥터 이름·편집기 묶음 제목이라 겹치면 구분이 안 된다.
    Reject duplicate server names: the name prefixes every tool connector and titles the editor group, so duplicates are indistinguishable."""
    row = conn.execute("SELECT id FROM mcp_servers WHERE name=? AND id<>?", (name, exclude_id or "")).fetchone()
    if row:
        raise MCPValidationError(f"같은 이름의 MCP 서버가 이미 있습니다: {name}")


def _skills_check(ids: list[str], server_id: str | None) -> None:
    """Skill 파일이 붙일 수 있는 것인지(없거나 남의 것이면 422) / the listed skill files must exist and be free or ours"""
    try:
        skill_files.ensure_attachable(ids, "mcp", server_id)
    except skill_files.SkillFileError as e:
        raise MCPValidationError(str(e))


def create(raw: dict) -> dict:
    d = normalize(raw)
    ids = d.get("skill_ids") or []
    _skills_check(ids, None)
    with _conn() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM mcp_servers").fetchone()["n"]
        if n >= MAX_SERVERS:
            raise MCPValidationError(f"MCP 서버는 최대 {MAX_SERVERS}개까지 등록할 수 있습니다")
        _check_unique_name(conn, d["name"])
        sid = "mcp_" + uuid.uuid4().hex[:8]
        _write(conn, sid, d, _now(), pos=n)
    skill_files.attach("mcp", sid, ids)   # 올려 둔 Skill 파일을 이 서버에 붙인다(2026-09-23) / attach the uploaded skill files
    server = get_server(sid)
    sync_tools(server)
    return server


def update(server_id: str, raw: dict) -> dict | None:
    previous = get_server(server_id)
    if previous is None:
        return None
    d = normalize(raw, previous)
    ids = d.get("skill_ids")   # None = 파일 목록 유지(다시 가져오기 등) / None keeps the files (refresh etc.)
    if ids is not None:
        _skills_check(ids, server_id)
    with _conn() as conn:
        _check_unique_name(conn, d["name"], server_id)
        _write(conn, server_id, d, _now(), created=previous["created_at"])
    if ids is not None:
        skill_files.attach("mcp", server_id, ids)
    server = get_server(server_id)
    sync_tools(server)
    return server


def delete(server_id: str) -> int:
    """서버 + 도구 커넥터 삭제 → 지운 도구 수(-1 = 서버 없음) / delete the server and its tool connectors → removed tools (-1 = missing)"""
    from app import connectors as connector_store
    server = get_server(server_id)
    if server is None:
        return -1
    removed = 0
    for c in connector_store.list_connectors():
        if c.get("source") == "mcp" and ((c.get("api") or {}).get("mcp") or {}).get("server_id") == server_id:
            connector_store.delete(c["id"])
            removed += 1
    with _conn() as conn:
        conn.execute("DELETE FROM mcp_servers WHERE id=?", (server_id,))
    skill_files.delete_for("mcp", server_id)   # 붙어 있던 Skill 파일도 함께 / the attached skill files go too
    return removed


def public(s: dict) -> dict:
    """비밀 없는 요약(목록 화면의 서버 행) / secret-free summary for the list screen"""
    return {"id": s["id"], "name": s["name"], "description": s.get("description") or "", "category": s.get("category") or "other",
            "url": s["url"], "auth_type": (s.get("auth") or {}).get("type") or "none", "timeout": s.get("timeout") or 30,
            "enabled": bool(s.get("enabled", True)), "fetched_at": s.get("fetched_at") or "", "server_info": s.get("server_info") or {},
            "skill_count": len(skill_files.list_for("mcp", s["id"])),
            "tools": [{"name": t["name"], "title": t.get("title") or t["name"], "kind": t.get("kind") or "action",
                       "enabled": bool(t.get("enabled", True)), "connector_id": tool_connector_id(s["id"], t["name"]),
                       "unsupported": t.get("unsupported") or []} for t in (s.get("tools") or [])]}


# ────────────────────────────────────────────────────────
# 서버 접속 / talking to the server
# ────────────────────────────────────────────────────────

def _resolve_url(url: str) -> str:
    ctx = flow_api_call.build_ctx()
    return flow_api_call.substitute(url or "", ctx).strip()


def auth_headers(auth: dict | None) -> dict:
    a = auth or {}
    t, key = a.get("type") or "none", a.get("key") or ""
    if t == "bearer" and key:
        return {"Authorization": "Bearer " + key}
    if t == "header" and key:
        return {(a.get("name") or "Authorization"): key}
    return {}


def discover(url: str, auth: dict | None, timeout: int = 30, *, transport=None) -> dict:
    """저장 없이 도구 목록 조회 → {"server_info", "protocol", "tools": [normalize_tool…], "skipped": n}."""
    # Fetch the tool list without saving → server info, negotiated protocol, normalized tools, skipped count.
    target = _resolve_url(url)
    if not target:
        raise MCPValidationError("MCP 서버 주소가 비어 있습니다")
    try:
        flow_api_call.check_url(target)
    except ValueError as e:
        raise MCPValidationError(str(e))
    try:
        with mcp_client.MCPClient(target, auth_headers(auth), timeout=timeout, transport=transport) as client:
            raw_tools = client.list_tools()
            info = {"name": str(client.server_info.get("name") or "")[:120],
                    "version": str(client.server_info.get("version") or "")[:40], "protocol": client.protocol}
    except mcp_client.MCPError as e:
        raise MCPValidationError(str(e))
    tools, skipped = [], 0
    for raw in raw_tools:
        t = mcp_client.normalize_tool(raw)
        if t is None:
            skipped += 1
            continue
        tools.append(t)
    return {"server_info": info, "protocol": info["protocol"], "tools": tools, "skipped": skipped}


def _call_result(tool) -> dict:
    """tools/call 결과의 빈 틀(flow_api_call.call 과 같은 모양) / the empty result frame, same shape as flow_api_call.call"""
    return {"ok": False, "status": None, "elapsed_ms": 0, "url": "", "request": {"method": "MCP", "tool": tool},
            "response_headers": {}, "body_text": "", "json": None, "result": None, "result_text": "", "outputs": {},
            "error": None, "attempts": 0, "variables": {}}


def call_tool(connector: dict, inputs: dict | None, *, keep_body: int = flow_api_call.BODY_KEEP, transport=None) -> dict:
    """도구 커넥터 실행 — 서버 레코드의 주소·인증으로 tools/call 1회. 결과는 flow_api_call.call 과 같은 모양."""
    # Run a tool connector — one tools/call with the server's URL/auth. Same result shape as flow_api_call.call.
    cfg = connector.get("api") or {}
    m = cfg.get("mcp") or {}
    server = get_server(str(m.get("server_id") or ""))
    if server is None:
        out = _call_result(m.get("tool"))
        out["error"] = "MCP 서버 설정이 삭제되었습니다. 관리 센터 › API · MCP 연결에서 다시 등록해 주세요"
        return out
    if not server.get("enabled", True):
        out = _call_result(m.get("tool"))
        out["error"] = f"MCP 서버 '{server['name']}'이(가) 비활성입니다"
        return out
    return call_tool_at(server["url"], server.get("auth"), int(server.get("timeout") or 30), m.get("tool"), inputs,
                        keep_body=keep_body, transport=transport)


def call_tool_at(url: str, auth: dict | None, timeout: int, tool, inputs: dict | None, *,
                 keep_body: int = flow_api_call.BODY_KEEP, transport=None) -> dict:
    """주소·인증을 직접 받아 tools/call 1회(2026-09-26 분리) — MCP 서버 도구 커넥터(call_tool)와 업무 자동화 에이전트의 MCP 도구
    (work_agents.call)가 같이 쓴다. 사설망 차단·빈 인자 제거·결과 변환은 그대로. 결과는 flow_api_call.call 과 같은 모양."""
    # One tools/call against an explicit URL/auth (split out 2026-09-26): shared by MCP server tool connectors (call_tool) and
    # the MCP tools of registered work agents (work_agents.call). Same private-network guard, blank-argument filter and conversion.
    out = _call_result(tool)
    target = _resolve_url(url)
    out["url"] = flow_api_call._mask(target, secret_of({"auth": auth})) + "#" + str(tool or "")
    try:
        flow_api_call.check_url(target)
    except ValueError as e:
        out["error"] = str(e)
        return out
    args = {k: v for k, v in (inputs or {}).items() if v is not None and not (isinstance(v, str) and not v.strip())}
    out["request"]["arguments"] = args
    t0 = time.perf_counter()
    out["attempts"] = 1
    try:
        with mcp_client.MCPClient(target, auth_headers(auth), timeout=int(timeout or 30), transport=transport) as client:
            res = client.call_tool(str(tool or ""), args)
    except mcp_client.MCPError as e:
        out["elapsed_ms"] = mcp_client.elapsed_ms(t0)
        out["error"] = str(e)
        return out
    out["elapsed_ms"] = mcp_client.elapsed_ms(t0)
    out["status"] = 200
    conv = mcp_client.result_to_common(res, keep_body=keep_body)
    out.update({"ok": conv["ok"], "result_text": conv["result_text"], "json": conv["json"], "result": conv["result"],
                "outputs": conv["outputs"], "error": conv["error"], "body_text": conv["result_text"]})
    return out
