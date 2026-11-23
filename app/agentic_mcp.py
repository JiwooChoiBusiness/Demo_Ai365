"""Agentic 모드 연결 도구(2026-10-19, 2차 Connectors): 관리 센터 'API · MCP 연결' 에 등록된 MCP 도구 커넥터를 세션에서 쓴다.

- available(): connectors.list_connectors() 중 source == "mcp" 이고 enabled 인 행만 /api/agentic/connectors 모양으로
  {"id", "name", "description", "kind": read|action, "server_name", "tool", "inputs": [{"name", "type", "required",
  "description"}]}. inputs = api.input_docs(없으면 mcp_servers.input_docs_of(api.tool_contract.input_schema)).
- get · kind_of · label: 한 도구의 같은 모양 · 종류(없거나 꺼졌으면 None · "") · 이름(꺼진 도구도 이름, 모르면 id).
- prompt_text(ids): 시스템 프롬프트에 넣는 "[연결된 도구(mcp_tool)]" 목록(id · 이름 · 종류 · 설명 · 입력).
- call(id, inputs_json): inputs_json(JSON 객체 문자열, 빈 문자열 = {}) 을 풀어 mcp_servers.call_tool(..., transport=TRANSPORT)
  1회 → (ok, summary, detail, extra={}). 성공 detail = result_text(6,000자 상한, 비면 json 을 글로), 실패 detail = error.
  없거나 꺼진 도구 · JSON 오류도 예외가 아니라 ok=False 와 사람이 읽는 안내. 동기 함수(호출부가 스레드에서 부른다).
- 세션에 연결된 도구인지 · 조회/실행 승인은 agentic_tools(classify · run) 가 판정한다. TRANSPORT = 테스트 이음새(httpx 전송).
"""
# Agentic mode connected tools (2026-10-19, phase-2 Connectors): sessions use the MCP tool connectors registered in
# Admin Center › 'API · MCP connections'.
# - available(): the rows of connectors.list_connectors() with source == "mcp" and enabled, in the /api/agentic/connectors
#   shape; inputs come from api.input_docs, else mcp_servers.input_docs_of(api.tool_contract.input_schema).
# - get, kind_of, label: one tool in the same shape, its kind (None or "" when missing or disabled) and its name (also
#   for a disabled tool; the id when unknown).
# - prompt_text(ids): the "[연결된 도구(mcp_tool)]" list for the system prompt (id, name, kind, description, inputs).
# - call(id, inputs_json): parse inputs_json (a JSON object string, empty = {}) and make one
#   mcp_servers.call_tool(..., transport=TRANSPORT) call → (ok, summary, detail, extra={}). Success: detail = result_text
#   (6,000 chars at most, the JSON as text when empty); failure: detail = the error. Missing or disabled tools and bad JSON
#   come back as ok=False with a readable message, never as exceptions. Synchronous (callers use a worker thread).
# - Whether the tool is connected to the session and the read/action approvals are decided by agentic_tools.
#   TRANSPORT is the test seam (an httpx transport).

from __future__ import annotations

import json
import logging
import re
import sqlite3

from app import connectors, mcp_servers

logger = logging.getLogger("ai365.agentic")

TRANSPORT = None          # 테스트 이음새(httpx 전송) / test seam (an httpx transport)
DETAIL_MAX = 6000         # 모델에 돌려주는 결과 상한 / result cap fed back to the model
KINDS = ("read", "action")


def _one_line(s, cap: int) -> str:
    return re.sub(r"\s+", " ", str(s if s is not None else "")).strip()[:cap]


def _connector(connector_id) -> dict | None:
    """MCP 도구 커넥터 행(꺼진 것도), MCP 가 아니거나 없으면 None / the MCP tool connector row (disabled too) or None"""
    cid = str(connector_id if connector_id is not None else "").strip()
    if not cid:
        return None
    try:
        c = connectors.get_connector(cid)
    except sqlite3.Error:   # 테이블이 아직 없다(부팅 순서 · 격리 DB) / table not created yet
        return None
    return c if c and c.get("source") == "mcp" else None


def _inputs(api: dict) -> list[dict]:
    docs = api.get("input_docs")
    if not isinstance(docs, list) or not docs:
        schema = (api.get("tool_contract") or {}).get("input_schema")
        try:
            docs = mcp_servers.input_docs_of(schema) if isinstance(schema, dict) else []
        except Exception:  # noqa: BLE001 (명세가 이상하면 입력 없음 / a broken schema means no inputs)
            docs = []
    out = []
    for d in docs or []:
        if isinstance(d, dict) and d.get("name"):
            out.append({"name": str(d["name"]), "type": str(d.get("type") or "string"), "required": bool(d.get("required")),
                        "description": str(d.get("description") or "")})
    return out


def _public(c: dict) -> dict:
    api = c.get("api") if isinstance(c.get("api"), dict) else {}
    m = api.get("mcp") if isinstance(api.get("mcp"), dict) else {}
    kind = c.get("kind") if c.get("kind") in KINDS else "action"   # 모르는 종류는 실행으로(승인을 묻는다) / unknown = action
    return {"id": c["id"], "name": c.get("name") or c["id"], "description": c.get("description") or "", "kind": kind,
            "server_name": str(m.get("server_name") or ""), "tool": str(m.get("tool") or ""), "inputs": _inputs(api)}


def available() -> list[dict]:
    """켜진 MCP 도구 커넥터 목록(/api/agentic/connectors 모양, 관리 센터 순서) / enabled MCP tool connectors"""
    try:
        rows = connectors.list_connectors()
    except sqlite3.Error:
        return []
    return [_public(c) for c in rows if c.get("source") == "mcp" and c.get("enabled")]


def get(connector_id) -> dict | None:
    """켜진 MCP 도구 하나(available() 의 한 항목 모양), 없거나 꺼졌거나 MCP 가 아니면 None / one enabled MCP tool or None"""
    c = _connector(connector_id)
    return _public(c) if c and c.get("enabled") else None


def kind_of(connector_id) -> str:
    """"read" | "action", 없거나 꺼졌으면 "" / the tool's kind, "" when missing or disabled"""
    c = get(connector_id)
    return c["kind"] if c else ""


def label(connector_id) -> str:
    """사람이 읽는 이름("서버 › 도구", 꺼진 도구도), 모르면 id / the human name, also for disabled tools; the id when unknown"""
    c = _connector(connector_id)
    return (c.get("name") if c else "") or str(connector_id if connector_id is not None else "")


def prompt_text(ids) -> str:
    """"[연결된 도구(mcp_tool)]\\n- <id> · <name> (<kind>): <description>\\n  입력: name(type, 필수) 설명, …". 없거나 꺼진 id 는
    빼고, 남는 것이 없으면 "" / the connected-tools block for the system prompt; unknown or disabled ids are skipped"""
    rows, seen = [], set()
    for cid in ids or []:
        c = get(cid)
        if c is not None and c["id"] not in seen:
            seen.add(c["id"])
            rows.append(c)
    if not rows:
        return ""
    lines = ["[연결된 도구(mcp_tool)]"]
    for c in rows:
        desc = _one_line(c["description"], 300)
        lines.append(f"- {c['id']} · {c['name']} ({c['kind']})" + (f": {desc}" if desc else ""))
        parts = []
        for x in c["inputs"]:
            d = _one_line(x["description"], 120)
            parts.append(f"{x['name']}({x['type']}" + (", 필수" if x["required"] else "") + ")" + (f" {d}" if d else ""))
        lines.append("  입력: " + (", ".join(parts) if parts else "없음"))
    return "\n".join(lines)


def _parse_inputs(v) -> tuple[dict, str]:
    """inputs_json → (dict, 오류 글). None · 빈 문자열 = {}, dict 는 그대로 받는다 / inputs_json → (dict, error text)"""
    if v is None:
        return {}, ""
    if isinstance(v, dict):
        return v, ""
    if not isinstance(v, str):
        return {}, "inputs_json 은 JSON 객체여야 합니다"
    s = v.strip()
    if not s:
        return {}, ""
    try:
        obj = json.loads(s)
    except RecursionError:   # 너무 깊게 중첩된 JSON(ValueError 가 아니다) / nested too deep, not a ValueError
        return {}, "inputs_json 을 JSON 으로 읽지 못했습니다(너무 깊게 중첩되어 있습니다). JSON 객체 문자열로 다시 주세요"
    except ValueError as e:
        return {}, (f"inputs_json 을 JSON 으로 읽지 못했습니다({getattr(e, 'msg', e)}, 위치 {getattr(e, 'pos', '?')}). "
                    "JSON 객체 문자열로 다시 주세요")
    if not isinstance(obj, dict):
        return {}, "inputs_json 은 JSON 객체여야 합니다"
    return obj, ""


def _cap(s: str) -> str:
    """DETAIL_MAX 안으로(자른 표시까지 포함) / cut within DETAIL_MAX, the note included"""
    if len(s) <= DETAIL_MAX:
        return s
    note = f"\n…(결과가 길어 {len(s):,}자 중 앞부분만 보여 줍니다)"
    return s[:DETAIL_MAX - len(note)] + note


def call(connector_id, inputs_json) -> tuple[bool, str, str, dict]:
    """MCP 도구 1회 호출 → (ok, summary "결과 n자" | 오류 요약, detail = 결과 글(6,000자) | 오류, {}). 예외를 올리지 않는다.
    One MCP tool call → (ok, summary, detail, {}); never raises."""
    cid = str(connector_id if connector_id is not None else "").strip()
    if not cid:
        return False, "connector_id 없음", "connector_id 인자가 필요합니다", {}
    c = _connector(cid)
    if c is None:
        return False, "없는 도구", f"연결된 도구를 찾을 수 없습니다: {cid}", {}
    if not c.get("enabled"):
        return False, "꺼진 도구", f"관리 센터에서 꺼 둔 도구입니다: {c.get('name') or cid}", {}
    inputs, err = _parse_inputs(inputs_json)
    if err:
        return False, "입력 JSON 오류", err, {}
    try:
        r = mcp_servers.call_tool(c, inputs, transport=TRANSPORT)
    except Exception as e:  # noqa: BLE001 (도구 하나의 오류가 루프를 죽이지 않는다 / one tool error never kills the loop)
        logger.exception("Agentic MCP 도구 호출 오류 connector=%s", cid)
        return False, "도구 호출 오류", f"도구를 부르는 중 오류가 났습니다: {type(e).__name__}: {_one_line(e, 300)}", {}
    if r.get("ok"):
        text = str(r.get("result_text") or "")
        if not text and r.get("json") is not None:
            try:
                text = json.dumps(r["json"], ensure_ascii=False)
            except (TypeError, ValueError, RecursionError):   # 이상하거나 너무 깊은 결과 / odd or too deep
                text = "(결과를 글로 바꾸지 못했습니다)"
        return True, f"결과 {len(text):,}자", _cap(text) if text else "(결과 없음)", {}
    msg = str(r.get("error") or "도구 호출에 실패했습니다")
    return False, _one_line(msg, 80), _cap(msg), {}
