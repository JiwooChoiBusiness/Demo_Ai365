"""API 설정(구 커넥터, 2026-09-09 → 2026-09-11 개편) — 특수 목적 외부 API 1개를 등록하는 단위. 예: "ERP 매출 조회", "ERP 주문 실행".
워크플로우의 API 작업이 이 목록에서 API 1개를 지정해 호출한다(2026-09-11 사용자 확정: 채팅에 붙던 커넥터 라우팅·전역 AI 선택 폐지,
API 는 워크플로우 전용). 내부 식별자(cn_*, 테이블·권한 축 p_conn)는 호환을 위해 그대로 둔다.

  - API 설정은 워크플로우 "API 요청" 작업과 같은 규격(flow_api_call.normalize) — 등록 화면도 같은 패널을 쓴다.
  - description 은 워크플로우 편집기·실행 확인 팝업·단계 검수(질문 카드)가 읽는 소개라 필수.
  - api.input_docs(2026-09-11) = {{input.<이름>}} 마다 설명·예시 — AI 입력값 추출과 정보 부족 질문의 재료.
  - kind: read(조회) | action(실행). 실행형은 검수 재실행에서 제외된다(중복 실행 방지).
  - 권한: 관리 센터 접근 권한의 "API" 축 — API 가 생길 때마다 축 항목이 자동으로 늘어난다.

API settings (formerly Connectors; reworked 2026-09-11) — one special-purpose external API registered as a unit, e.g.
"ERP sales lookup", "ERP order execution". A workflow API task picks exactly one API from this list (user decision
2026-09-11: the chat-attached connector routing and the global AI pick are retired; APIs are workflow-only). Internal
identifiers (cn_*, table, permission axis p_conn) stay for compatibility.
  - The API config shares the workflow "API request" task contract (flow_api_call.normalize) and the same editor panel.
  - description is read by the workflow editor, the run-confirm popup and the stage review (question cards), hence required.
  - api.input_docs (2026-09-11) = description + example per {{input.<name>}} — feeds AI input extraction and questions.
  - kind: read | action. Action APIs are excluded from review re-runs (no duplicate execution).
  - Permissions: the "API" axis of Admin Center access control — each new API adds an axis item.
"""

from __future__ import annotations

import json
import copy
import sqlite3
import uuid

from app import flow_api_call, kst
from app.db import DB_PATH

CATEGORIES = ("erp", "ems", "other")
CATEGORY_LABELS = {"erp": "ERP", "ems": "EMS", "other": "기타"}
KINDS = ("read", "action")
KIND_LABELS = {"read": "조회", "action": "실행"}
MAX_CONNECTORS = 50
MAX_NAME, MAX_DESC = 80, 500
SECRET_MASK = "••••••"


def editor_record(c: dict) -> dict:
    """Never return stored credentials in an editor/list response."""
    out = copy.deepcopy(c)
    secret = (out.get("api", {}).get("auth") or {}).get("key") or ""
    out["api"] = flow_api_call.redact(out.get("api") or {}, secret)
    if secret:
        out["api"]["auth"]["key"] = SECRET_MASK
    return out


def restore_credentials(raw: dict, previous: dict | None = None) -> dict:
    """Masked fields keep their previous value; an empty key explicitly clears it."""
    old = (previous or {}).get("api") or {}
    secret = (old.get("auth") or {}).get("key") or ""
    def restore(value, prior):
        if isinstance(value, dict):
            return {k: restore(v, prior.get(k) if isinstance(prior, dict) else None) for k, v in value.items()}
        if isinstance(value, list):
            rows = prior if isinstance(prior, list) else []
            return [restore(v, next((p for p in rows if isinstance(p, dict) and p.get("name") == v["name"]), None)
                            if isinstance(v, dict) and "name" in v else (rows[i] if i < len(rows) else None))
                    for i, v in enumerate(value)]
        if isinstance(value, str) and SECRET_MASK in value:
            if prior is None:
                raise ConnectorValidationError("저장된 인증정보가 없습니다. 인증정보를 다시 입력하세요")
            if value == SECRET_MASK:
                return prior
            if value == flow_api_call.redact(prior, secret):
                return prior
            raise ConnectorValidationError("가려진 인증정보가 포함된 값을 변경하려면 해당 값을 다시 입력하세요")
        return value
    return {**raw, "api": restore(raw.get("api") or {}, old)}


class ConnectorValidationError(ValueError):
    pass


def _now() -> str:
    return kst.now_iso()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_connectors() -> None:
    """테이블 생성(멱등) / create the table (idempotent)"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS connectors(
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              category TEXT NOT NULL DEFAULT 'other',
              kind TEXT NOT NULL DEFAULT 'read',
              enabled INTEGER NOT NULL DEFAULT 1,
              api TEXT NOT NULL,
              pos INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        # source(2026-09-15): 'api'(직접 등록) | 'mcp'(MCP 서버 도구 — mcp_servers.sync_tools 가 만들고 지운다) — 기존 DB 는 열 추가
        # source (2026-09-15): 'api' (registered directly) | 'mcp' (an MCP server tool, created/removed by mcp_servers.sync_tools)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(connectors)").fetchall()}
        if "source" not in cols:
            conn.execute("ALTER TABLE connectors ADD COLUMN source TEXT NOT NULL DEFAULT 'api'")


def _row(r: sqlite3.Row) -> dict:
    try:
        api = json.loads(r["api"] or "{}")
    except ValueError:
        api = {}
    keys = r.keys()
    return {"id": r["id"], "name": r["name"], "description": r["description"] or "",
            "category": r["category"] or "other", "kind": r["kind"] or "read", "enabled": bool(r["enabled"]),
            "source": (r["source"] if "source" in keys else None) or "api",
            "api": api, "pos": r["pos"], "created_at": r["created_at"], "updated_at": r["updated_at"]}


def list_connectors() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM connectors ORDER BY pos, created_at").fetchall()
    return [_row(r) for r in rows]


def get_connector(conn_id: str) -> dict | None:
    with _conn() as conn:
        r = conn.execute("SELECT * FROM connectors WHERE id=?", (conn_id,)).fetchone()
    return _row(r) if r else None


def normalize(raw, where: str = "connector") -> dict:
    """검증·정규화 — 잘못된 값은 지목해 거부(ConnectorValidationError). 이름·설명·API URL 은 필수."""
    # Validate/normalize — reject-and-point. Name, description and API URL are required.
    if not isinstance(raw, dict):
        raise ConnectorValidationError(f"{where}은(는) 객체여야 합니다")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConnectorValidationError("API 이름이 비어 있습니다")
    name = name.strip()
    if len(name) > MAX_NAME:
        raise ConnectorValidationError(f"API 이름은 {MAX_NAME}자 이하여야 합니다")
    desc = raw.get("description") or ""
    if not isinstance(desc, str):
        raise ConnectorValidationError("설명은 문자열이어야 합니다")
    desc = desc.strip()
    if not desc:
        raise ConnectorValidationError("설명이 비어 있습니다. 워크플로우 편집기와 실행 확인 팝업에서 이 API를 소개하는 데 씁니다")
    if len(desc) > MAX_DESC:
        raise ConnectorValidationError(f"설명은 {MAX_DESC}자 이하여야 합니다")
    category = raw.get("category") or "other"
    if category not in CATEGORIES:
        raise ConnectorValidationError(f"분류는 {'/'.join(CATEGORIES)} 중 하나여야 합니다")
    kind = raw.get("kind") or "read"
    if kind not in KINDS:
        raise ConnectorValidationError("종류는 read(조회)/action(실행) 중 하나여야 합니다")
    try:
        api = flow_api_call.normalize(raw.get("api"), f"{where}.api")
        spec = (raw.get("api") or {}).get("tool_contract")
        if spec is not None:
            from app.tool_contracts import validate_contract
            validate_contract(spec)
            api["tool_contract"] = spec
    except ValueError as e:
        raise ConnectorValidationError(str(e))
    if not api.get("url"):
        raise ConnectorValidationError("API URL이 비어 있습니다")
    if not api.get("name"):
        api["name"] = name
    return {"name": name, "description": desc, "category": category, "kind": kind,
            "enabled": bool(raw.get("enabled", True)), "api": api}


def create(raw: dict) -> dict:
    d = normalize(restore_credentials(raw))
    with _conn() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM connectors").fetchone()["n"]
        if n >= MAX_CONNECTORS:
            raise ConnectorValidationError(f"API는 최대 {MAX_CONNECTORS}개까지 등록할 수 있습니다")
        cid = "cn_" + uuid.uuid4().hex[:8]
        now = _now()
        conn.execute(
            "INSERT INTO connectors(id, name, description, category, kind, enabled, api, pos, created_at, updated_at, source)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,'api')",
            (cid, d["name"], d["description"], d["category"], d["kind"], 1 if d["enabled"] else 0,
             json.dumps(d["api"], ensure_ascii=False), n, now, now),
        )
    return get_connector(cid)


def upsert_mcp_tool(row: dict) -> dict | None:
    """MCP 도구 커넥터 행 저장(2026-09-15, mcp_servers.sync_tools 전용) — 있으면 갱신(pos·created_at 유지), 없으면 추가.
    검증은 mcp_servers.normalize 가 이미 마쳤다(도구 명세·종류·이름). / Save an MCP tool connector row (sync only): update
    in place (keeping pos/created_at) or insert. Validation already happened in mcp_servers.normalize."""
    now = _now()
    with _conn() as conn:
        prev = conn.execute("SELECT id FROM connectors WHERE id=?", (row["id"],)).fetchone()
        api = json.dumps(row.get("api") or {}, ensure_ascii=False)
        if prev:
            conn.execute("UPDATE connectors SET name=?, description=?, category=?, kind=?, enabled=?, api=?, source='mcp', updated_at=?"
                         " WHERE id=?", (row["name"], row.get("description") or "", row.get("category") or "other",
                                         row.get("kind") or "action", 1 if row.get("enabled", True) else 0, api, now, row["id"]))
        else:
            n = conn.execute("SELECT COUNT(*) AS n FROM connectors").fetchone()["n"]
            conn.execute("INSERT INTO connectors(id, name, description, category, kind, enabled, api, pos, created_at, updated_at, source)"
                         " VALUES(?,?,?,?,?,?,?,?,?,?,'mcp')",
                         (row["id"], row["name"], row.get("description") or "", row.get("category") or "other",
                          row.get("kind") or "action", 1 if row.get("enabled", True) else 0, api, n, now, now))
    return get_connector(row["id"])


def secret_of(connector: dict | None) -> str:
    """마스킹용 비밀 — API 는 api.auth.key, MCP 도구는 서버 레코드의 인증 키 / the secret to redact: API auth key or the MCP server key"""
    api = (connector or {}).get("api") or {}
    if api.get("mcp"):
        from app import mcp_servers   # 지연 임포트(순환 방지) / lazy import (avoids a cycle)
        return mcp_servers.secret_of(mcp_servers.get_server(str((api.get("mcp") or {}).get("server_id") or "")))
    return str((api.get("auth") or {}).get("key") or "")


def update(conn_id: str, raw: dict) -> dict | None:
    previous = get_connector(conn_id)
    if previous is None:
        return None
    if previous.get("source") == "mcp":
        raise ConnectorValidationError("MCP 서버의 도구는 API · MCP 연결의 MCP 서버 설정에서 관리합니다")
    raw = restore_credentials(raw, previous)
    if "tool_contract" not in (raw.get("api") or {}) and "tool_contract" in previous["api"]:
        raw = {**raw, "api": {**(raw.get("api") or {}), "tool_contract": previous["api"]["tool_contract"]}}
    d = normalize(raw)
    with _conn() as conn:
        conn.execute(
            "UPDATE connectors SET name=?, description=?, category=?, kind=?, enabled=?, api=?, updated_at=? WHERE id=?",
            (d["name"], d["description"], d["category"], d["kind"], 1 if d["enabled"] else 0,
             json.dumps(d["api"], ensure_ascii=False), _now(), conn_id),
        )
    return get_connector(conn_id)


def delete(conn_id: str) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM connectors WHERE id=?", (conn_id,))
    return cur.rowcount > 0


def public(c: dict) -> dict:
    """권한 화면·편집기용 요약(비밀 없음) + 필요 입력값 명세(inputs, 2026-09-11) / summary for permission screens and the
    editor (no secrets) + required-input specs"""
    api = editor_record(c).get("api") or {}
    m = api.get("mcp") or {}   # MCP 도구 커넥터(2026-09-15): 서버·도구 표시 정보 / MCP tool connector: server and tool labels
    return {"id": c["id"], "name": c["name"], "description": c["description"], "category": c["category"],
            "kind": c["kind"], "enabled": c["enabled"], "method": api.get("method"), "url": api.get("url"),
            "source": c.get("source") or "api", "server_id": m.get("server_id") or "", "server_name": m.get("server_name") or "",
            "tool": m.get("tool") or "", "title": m.get("title") or "", "unsupported": m.get("unsupported") or [],
            "test": api.get("test"), "inputs": flow_api_call.input_specs(api)}
