"""워크플로우 "API 요청" 작업(2026-09-09) — 외부 HTTP API 1회 호출.

관리 센터 "API 설정"(구 커넥터 설정)에 등록된 API 1건의 요청/응답 설정이 이 모듈의 config 다(2026-09-09 커넥터 참조 개편 —
워크플로우 API 작업은 노드 인라인 설정 대신 등록된 API(cn_*) 를 참조한다). 실행기(flows.run_flow)와 API 설정 화면의
[Test] 탭(connectors_api /test)이 같은 함수로 호출한다.
  - normalize(raw)         : 설정 검증·정규화(뭉개지 않고 지목해 거부 — flows.normalize 정책) + input_docs(입력값 설명, 2026-09-11)
  - input_specs(config)    : 필요 입력값 명세 [{name, description, example}] — 편집기·실행 확인 팝업·AI 계획·질문 카드 공용
  - build_ctx(...)         : 변수 컨텍스트 {input.*, api_key, base_url, stepN.result[.path], stepN.<출력변수>}
  - substitute(text, ctx)  : {{변수}} 치환(미해결 변수는 빈 문자열)
  - call(config, ctx)      : 요청 조립 → 내부망 차단 검사 → httpx 호출(재시도) → 응답 파싱·결과 추출·출력 변수
실제 답변 파이프라인과 무관하게 동작하며, 데모의 가상 ERP/EMS API(app/mock_apis.py, /mock/…)를 대상으로 쓴다.

Workflow "API request" task (2026-09-09) — one outbound HTTP call.
The request/response config of one API registered in Admin Center › "API settings" (formerly Connectors) is this
module's config (2026-09-09 connector-reference rework — workflow API tasks reference a registered API (cn_*) instead of
inline node config). The runner (flows.run_flow) and the API settings screen's [Test] tab (connectors_api /test) share:
  - normalize(raw)         : validate/normalize the config (reject-and-point, same policy as flows.normalize) + input_docs (2026-09-11)
  - input_specs(config)    : required-input specs [{name, description, example}] shared by the editor, run popup, AI plan, question cards
  - build_ctx(...)         : variable context {input.*, api_key, base_url, stepN.result[.path], stepN.<output>}
  - substitute(text, ctx)  : {{variable}} substitution (unresolved variables become empty strings)
  - call(config, ctx)      : build the request → private-network guard → httpx call (retries) → parse, extract, outputs
Independent of the answer pipeline; in the demo it targets the fictional ERP/EMS APIs (app/mock_apis.py, /mock/…).
"""

from __future__ import annotations

import base64
import ipaddress
import json
import logging
import os
import re
import socket
import time
from urllib.parse import unquote

import httpx

from app import kst

logger = logging.getLogger("ai365.flow_api")

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
AUTH_TYPES = ("none", "api_key", "bearer", "basic")
AUTH_IN = ("header", "query")
CONTENT_TYPES = ("application/json", "text/plain", "application/x-www-form-urlencoded", "none")
RESP_FORMATS = ("auto", "json", "text")
ON_ERROR = ("continue", "stop", "retry")
MAX_NAME, MAX_URL, MAX_KV, MAX_KEY_LEN, MAX_VAL, MAX_PAYLOAD = 80, 500, 20, 80, 500, 4000
MAX_OUTPUTS, MAX_PATH, MAX_SECRET = 10, 200, 500
# 입력값 설명(2026-09-11) — {{input.<이름>}} 마다 자연어 설명·예시. 워크플로우 편집기 API 목록·실행 확인 팝업·
# AI 입력값 추출·정보 부족 질문 카드가 같은 설명을 쓴다. 기본값(2026-09-14)이 있으면 그 입력은 선택 사항이 되고
# 값을 찾지 못했을 때 기본값으로 호출된다(tool_contracts.prepare_inputs 가 채운다).
# Input docs — a natural-language description + example per {{input.<name>}}; shared by the workflow editor's API list,
# the run-confirm popup, AI input extraction and question cards. A default (2026-09-14) makes the input optional: it is
# used when no value could be found (filled by tool_contracts.prepare_inputs).
MAX_INPUT_DOCS, MAX_DOC_DESC, MAX_DOC_EXAMPLE, MAX_DOC_DEFAULT = 20, 200, 120, 120
BODY_KEEP = 8000        # 결과 텍스트로 넘기는 본문 상한 / body chars kept as the result text
TEST_BODY_KEEP = 20000  # [Test] 탭에 돌려주는 본문 상한 / body chars returned to the Test tab
_VAR_RX = re.compile(r"\{\{\s*([A-Za-z0-9_.\[\]-]+)\s*\}\}")
_OUT_NAME_RX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")
_TOKEN_RX = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


# ────────────────────────────────────────────────────────
# 설정 / Config
# ────────────────────────────────────────────────────────

def default_config() -> dict:
    """편집기가 새 API 작업에 넣는 기본값 / defaults the editor puts on a new API task"""
    return {
        "name": "", "method": "GET", "url": "", "timeout": 30,
        "auth": {"type": "none", "key": "", "in": "header", "name": "Authorization"},
        "headers": [{"name": "Accept", "value": "application/json"}],
        "params": [],
        "body": {"content_type": "none", "payload": ""},
        "response": {"format": "auto", "path": "", "outputs": [], "ok_status": "2xx", "on_error": "continue",
                     "retries": 0, "retry_wait": 2, "preview_chars": 1200, "include_in_answer": True},
        "input_docs": [],
        "test": None,
    }


def _str(v, cap: int, what: str, required: bool = False) -> str:
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise ValueError(f"{what}은(는) 문자열이어야 합니다")
    v = v.strip()
    if required and not v:
        raise ValueError(f"{what}이(가) 비어 있습니다")
    if len(v) > cap:
        raise ValueError(f"{what}은(는) {cap}자 이하여야 합니다")
    return v


def _int(v, lo: int, hi: int, default: int, what: str) -> int:
    if v in (None, ""):
        return default
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what}은(는) 숫자여야 합니다")
    if n < lo or n > hi:
        raise ValueError(f"{what}은(는) {lo}~{hi} 사이여야 합니다")
    return n


def _kv_list(v, what: str) -> list[dict]:
    if v in (None, ""):
        return []
    if not isinstance(v, list):
        raise ValueError(f"{what}은(는) 배열이어야 합니다")
    if len(v) > MAX_KV:
        raise ValueError(f"{what}은(는) 최대 {MAX_KV}개까지입니다")
    out = []
    for i, row in enumerate(v):
        if not isinstance(row, dict):
            raise ValueError(f"{what}[{i}]은(는) 객체여야 합니다")
        name = _str(row.get("name"), MAX_KEY_LEN, f"{what}[{i}].name")
        val = _str(row.get("value"), MAX_VAL, f"{what}[{i}].value")
        if not name:
            continue   # 이름 없는 행은 버린다(편집기의 빈 행) / nameless rows are dropped (editor blanks)
        out.append({"name": name, "value": val})
    return out


def normalize(raw, where: str = "api") -> dict:
    """설정 검증·정규화. 잘못된 값은 ValueError(메시지에 위치) — flows.normalize 가 422 로 바꾼다.
    비어 있는 이름/URL 은 허용(미설정 노드 — 실행 시 실패 결과로 안내)."""
    # Validate/normalize. Bad values raise ValueError (message names the spot) — flows.normalize turns it into 422.
    # Empty name/URL are allowed (unconfigured node — reported as a failed result at run time).
    if raw in (None, ""):
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(f"{where}은(는) 객체여야 합니다")
    d = default_config()
    d["name"] = _str(raw.get("name"), MAX_NAME, f"{where}.name")
    method = (raw.get("method") or "GET")
    if not isinstance(method, str) or method.upper() not in METHODS:
        raise ValueError(f"{where}.method는 {'/'.join(METHODS)} 중 하나여야 합니다")
    d["method"] = method.upper()
    url = _str(raw.get("url"), MAX_URL, f"{where}.url")
    if url and not re.match(r"^(https?://|\{\{\s*base_url\s*\}\})", url, re.I):
        raise ValueError(f"{where}.url은 http:// 또는 https:// 로 시작해야 합니다")
    d["url"] = url
    d["timeout"] = _int(raw.get("timeout"), 1, 120, 30, f"{where}.timeout")

    a_in = raw.get("auth") or {}
    if not isinstance(a_in, dict):
        raise ValueError(f"{where}.auth는 객체여야 합니다")
    a_type = a_in.get("type") or "none"
    if a_type not in AUTH_TYPES:
        raise ValueError(f"{where}.auth.type은 {'/'.join(AUTH_TYPES)} 중 하나여야 합니다")
    a_where = a_in.get("in") or "header"
    if a_where not in AUTH_IN:
        raise ValueError(f"{where}.auth.in은 header/query 중 하나여야 합니다")
    d["auth"] = {"type": a_type, "key": _str(a_in.get("key"), MAX_SECRET, f"{where}.auth.key"),
                 "in": a_where,
                 "name": _str(a_in.get("name"), MAX_KEY_LEN, f"{where}.auth.name") or "Authorization"}

    d["headers"] = _kv_list(raw.get("headers"), f"{where}.headers")
    d["params"] = _kv_list(raw.get("params"), f"{where}.params")

    b_in = raw.get("body") or {}
    if not isinstance(b_in, dict):
        raise ValueError(f"{where}.body는 객체여야 합니다")
    ct = b_in.get("content_type") or "none"
    if ct not in CONTENT_TYPES:
        raise ValueError(f"{where}.body.content_type이 지원되지 않는 값입니다")
    d["body"] = {"content_type": ct, "payload": _str(b_in.get("payload"), MAX_PAYLOAD, f"{where}.body.payload")}

    r_in = raw.get("response") or {}
    if not isinstance(r_in, dict):
        raise ValueError(f"{where}.response는 객체여야 합니다")
    fmt = r_in.get("format") or "auto"
    if fmt not in RESP_FORMATS:
        raise ValueError(f"{where}.response.format은 auto/json/text 중 하나여야 합니다")
    on_err = r_in.get("on_error") or "continue"
    if on_err not in ON_ERROR:
        raise ValueError(f"{where}.response.on_error는 continue/stop/retry 중 하나여야 합니다")
    ok_status = _str(r_in.get("ok_status"), 60, f"{where}.response.ok_status") or "2xx"
    if not re.match(r"^[0-9xX,\-\s]+$", ok_status):
        raise ValueError(f"{where}.response.ok_status 형식이 올바르지 않습니다 (예: 2xx 또는 200,201)")
    outs_in = r_in.get("outputs") or []
    if not isinstance(outs_in, list) or len(outs_in) > MAX_OUTPUTS:
        raise ValueError(f"{where}.response.outputs는 최대 {MAX_OUTPUTS}개의 배열이어야 합니다")
    outs = []
    output_names = set()
    for i, o in enumerate(outs_in):
        if not isinstance(o, dict):
            raise ValueError(f"{where}.response.outputs[{i}]은(는) 객체여야 합니다")
        nm = _str(o.get("name"), 40, f"{where}.response.outputs[{i}].name")
        pth = _str(o.get("path"), MAX_PATH, f"{where}.response.outputs[{i}].path")
        if not nm and not pth:
            continue
        if not _OUT_NAME_RX.match(nm):
            raise ValueError(f"{where}.response.outputs[{i}].name은 영문자로 시작하는 영문·숫자·_ 40자 이하여야 합니다")
        if nm in output_names or nm == "result" or re.fullmatch(r"task\d+", nm):
            raise ValueError(f"{where}.response.outputs[{i}].name은 중복 또는 예약된 출력 이름입니다")
        output_names.add(nm)
        outs.append({"name": nm, "path": pth})
    d["response"] = {
        "format": fmt, "path": _str(r_in.get("path"), MAX_PATH, f"{where}.response.path"), "outputs": outs,
        "ok_status": ok_status, "on_error": on_err,
        "retries": _int(r_in.get("retries"), 0, 3, 0, f"{where}.response.retries"),
        "retry_wait": _int(r_in.get("retry_wait"), 0, 30, 2, f"{where}.response.retry_wait"),
        "preview_chars": _int(r_in.get("preview_chars"), 100, 4000, 1200, f"{where}.response.preview_chars"),
        "include_in_answer": bool(r_in.get("include_in_answer", True)),
    }
    # 입력값 설명(2026-09-11) — 이름은 설정에 실제로 쓰인 {{input.<이름>}}(자동 제공분 제외)만 허용. 편집기가 저장 전에
    # 재스캔하므로 낡은 행은 남지 않는다; 그래도 오면 지목해 거부(뭉개지 않는 정책).
    # Input docs (2026-09-11) — names must be {{input.<name>}} placeholders actually used by the config (auto-filled
    # ones excluded). The editor rescans before saving, so stale rows never arrive; if they do, reject and point.
    docs_in = raw.get("input_docs") or []
    if not isinstance(docs_in, list) or len(docs_in) > MAX_INPUT_DOCS:
        raise ValueError(f"{where}.input_docs는 최대 {MAX_INPUT_DOCS}개의 배열이어야 합니다")
    known = required_inputs(d)
    docs, seen_docs = [], set()
    for i, row in enumerate(docs_in):
        if not isinstance(row, dict):
            raise ValueError(f"{where}.input_docs[{i}]은(는) 객체여야 합니다")
        nm = _str(row.get("name"), MAX_KEY_LEN, f"{where}.input_docs[{i}].name")
        if not nm or nm in seen_docs:
            continue   # 빈 행·중복은 버린다 / blank or duplicate rows are dropped
        if nm not in known:
            raise ValueError(f"{where}.input_docs[{i}].name({nm})은(는) 설정에 쓰인 입력값이 아닙니다")
        seen_docs.add(nm)
        docs.append({"name": nm,
                     "description": _str(row.get("description"), MAX_DOC_DESC, f"{where}.input_docs[{i}].description"),
                     "example": _str(row.get("example"), MAX_DOC_EXAMPLE, f"{where}.input_docs[{i}].example"),
                     # 기본값(2026-09-14): 비어 있지 않으면 선택 입력 / default (2026-09-14): non-empty = optional input
                      "default": _str(row.get("default"), MAX_DOC_DEFAULT, f"{where}.input_docs[{i}].default")})
        if "type" in row:
            if row["type"] not in ("string", "integer", "number", "boolean", "object", "array"):
                raise ValueError(f"{where}.input_docs[{i}].type이 올바르지 않습니다")
            docs[-1]["type"] = row["type"]
        if "required" in row:
            if not isinstance(row["required"], bool):
                raise ValueError(f"{where}.input_docs[{i}].required는 불리언이어야 합니다")
            docs[-1]["required"] = row["required"]
        if docs[-1].get("type") and docs[-1]["default"]:
            from app.tool_contracts import check
            value = docs[-1]["default"]
            if docs[-1]["type"] != "string":
                try:
                    value = json.loads(value)
                except ValueError:
                    raise ValueError(f"{where}.input_docs[{i}].default는 지정한 타입의 JSON 값이어야 합니다")
            check(value, {"type": docs[-1]["type"]}, f"{where}.input_docs[{i}].default")
    d["input_docs"] = docs
    t_in = raw.get("test")
    if isinstance(t_in, dict) and t_in.get("at"):
        d["test"] = {"at": str(t_in.get("at"))[:40], "ok": bool(t_in.get("ok")),
                     "status": (int(t_in["status"]) if str(t_in.get("status") or "").isdigit() else None)}
    else:
        d["test"] = None
    return d


def input_specs(config: dict) -> list[dict]:
    """필요 입력값 명세 — required_inputs 순서로 {name, description, example, default}(설명이 없으면 빈 문자열).
    편집기 API 목록·실행 확인 팝업·AI 계획 프롬프트·질문 카드가 공용으로 쓴다. default 가 비어 있지 않으면 선택 입력."""
    # Required-input specs — {name, description, example, default} in required_inputs order (empty strings when
    # undocumented). Shared by the editor's API list, the run-confirm popup, the AI planning prompt and question cards.
    # A non-empty default marks an optional input.
    docs = {d.get("name"): d for d in ((config or {}).get("input_docs") or []) if isinstance(d, dict)}
    # MCP 도구(2026-09-15)는 enum(허용값)도 함께 — 편집기 바인딩 표·질문 카드가 선택지로 보여 준다 / MCP tools also carry enum choices
    return [{"name": n, "description": (docs.get(n) or {}).get("description") or "",
             "example": (docs.get(n) or {}).get("example") or "",
             "default": (docs.get(n) or {}).get("default") or "",
             **{k: docs[n][k] for k in ("type", "required", "enum") if k in docs.get(n, {})}}
            for n in required_inputs(config or {})]


# ────────────────────────────────────────────────────────
# 변수 / Variables
# ────────────────────────────────────────────────────────

def variables_in(config: dict) -> list[str]:
    """설정 전체에서 쓰인 {{변수}} 이름(등장 순, 중복 제거) — [Test] 탭 입력 칸용 / variables used anywhere in the config"""
    seen: list[str] = []

    def scan(s):
        for m in _VAR_RX.finditer(s or ""):
            v = m.group(1)
            if v not in seen:
                seen.append(v)

    scan(config.get("url"))
    for row in (config.get("headers") or []) + (config.get("params") or []):
        scan(row.get("name")); scan(row.get("value"))
    scan((config.get("body") or {}).get("payload"))
    return seen


# 실행 환경이 자동으로 채우는 입력 변수 — 이 밖의 {{input.<이름>}} 은 의도 판단·워크플로우 계획기가 값을 뽑아야 한다
# Input variables the runtime fills automatically — any other {{input.<name>}} must be extracted by the intent / flow planner
AUTO_INPUTS = ("input.question", "input.user_name", "input.user_no", "input.date", "input.time", "input.month")


def required_inputs(config: dict) -> list[str]:
    """설정에 쓰인 사용자 입력 변수 중 자동 제공되지 않는 것의 이름(예: {{input.sku}} → "sku") — 커넥터 호출 전 값 추출 대상."""
    # Names of user-input variables the runtime does not fill on its own (e.g. {{input.sku}} → "sku") — extracted before a connector call.
    # MCP 도구 커넥터(2026-09-15): 입력 이름은 도구 명세(tool_contract.input_schema)의 속성 — URL 템플릿이 없다
    # MCP tool connectors (2026-09-15): input names come from the tool's input schema — there is no URL template to scan
    # 등록 업무 자동화 에이전트 도구(2026-09-26, work_agents.as_connector 의 api.work_agent)도 같다 — 요청은 에이전트 설정이 조립한다
    # Registered work-agent tools (2026-09-26, api.work_agent from work_agents.as_connector) too — the agent config builds the request
    if (config or {}).get("mcp") or (config or {}).get("work_agent"):
        schema = ((config or {}).get("tool_contract") or {}).get("input_schema") or {}
        return [n for n in (schema.get("properties") or {}) if isinstance(n, str)]
    return [v[len("input."):] for v in variables_in(config or {})
            if v.startswith("input.") and v not in AUTO_INPUTS]


# 이 서버 자신의 주소(2026-09-30) · AI365_BASE_URL 이 없을 때 {{base_url}} 의 기본값. main 의 ASGI 미들웨어가 첫 실제 요청의 소켓
# 포트로 채운다(예: 8010 검증 서버가 8000 대신 자기 /mock/… 을 부른다). 채우기 전(기동 직후)이나 테스트 클라이언트는 종전 기본값.
# This server's own origin (2026-09-30): the {{base_url}} default when AI365_BASE_URL is unset. main's ASGI middleware fills it
# from the socket port of the first real request (so an 8010 verification server calls its own /mock/… instead of 8000);
# before that (right after boot) and under test clients the old default applies.
SELF_BASE: str | None = None


def default_base_url() -> str:
    """{{base_url}} 기본값 · AI365_BASE_URL > 이 서버 자신 > http://localhost:8000 / the {{base_url}} default"""
    return (os.getenv("AI365_BASE_URL") or SELF_BASE or "http://localhost:8000").rstrip("/")


def build_ctx(message: str = "", acting_user_id: str = "", prior: list[dict] | None = None,
              api_key: str = "", base_url: str = "", vars: dict | None = None) -> dict:
    """변수 컨텍스트. prior = run_flow 의 단계 출력 목록({stage, text, data, outputs}) / stage outputs from run_flow"""
    now = kst.now()   # {{input.date}} · {{input.time}} · {{input.month}} = KST / filled from the KST clock
    user_name, user_no = "나", ""
    aid = (acting_user_id or "").strip()
    if aid.isdigit():
        user_no = aid
        try:
            from app import access  # 지연 임포트(순환 방지) / lazy import (avoids cycles)
            m = access.member_by_no(int(aid)) if hasattr(access, "member_by_no") else None
            if m and m.get("name"):
                user_name = m["name"]
        except Exception:  # noqa: BLE001 — 이름 조회 실패는 기본값 / name lookup failure keeps the default
            pass
    steps: dict[int, dict] = {}
    for p in prior or []:
        n = p.get("stage")
        if not isinstance(n, int):
            continue
        st = steps.setdefault(n, {"texts": [], "data": [], "outputs": {}, "ambiguous": set(), "nodes": {}})
        if p.get("node") is not None:
            st["nodes"][int(p["node"])] = p
        if p.get("text"):
            st["texts"].append(p["text"])
        if p.get("data") is not None:
            st["data"].append(p["data"])
        for k, v in (p.get("outputs") or {}).items():
            if k in st["outputs"]:
                st["ambiguous"].add(k)
            st["outputs"].setdefault(k, v)
    return {
        "input": {"question": message or "", "user_name": user_name, "user_no": user_no,
                  "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M"), "month": now.strftime("%Y-%m")},
        "api_key": api_key or "", "base_url": (base_url or default_base_url()).rstrip("/"),
        "steps": steps, "vars": dict(vars or {}),
    }


def _tokens(path: str) -> list:
    """JSONPath-lite 토큰: '$.a.items[0].name' → ['a', 'items', 0, 'name'] / tokens of a JSONPath-lite string"""
    p = (path or "").strip()
    if p.startswith("$"):
        p = p[1:]
    toks: list = []
    for m in _TOKEN_RX.finditer(p):
        if m.group(1) is not None:
            toks.append(m.group(1))
        else:
            toks.append(int(m.group(2)))
    return toks


def get_path(obj, path):
    """경로로 값 꺼내기 — 없으면 None / value at the path, None when missing"""
    toks = _tokens(path) if isinstance(path, str) else list(path)
    cur = obj
    for t in toks:
        if isinstance(t, int):
            if isinstance(cur, list) and 0 <= t < len(cur):
                cur = cur[t]
            else:
                return None
        elif isinstance(cur, dict) and t in cur:
            cur = cur[t]
        elif isinstance(cur, list) and t.isdigit() and int(t) < len(cur):
            cur = cur[int(t)]
        else:
            return None
    return cur


def to_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    try:
        return json.dumps(v, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(v)


def resolve(var: str, ctx: dict) -> str:
    """변수 하나 해결. 우선순위: 명시 값(vars) → api_key/base_url → input.* → stepN.result[.path] / stepN.<출력>"""
    # Resolve one variable. Priority: explicit vars → api_key/base_url → input.* → stepN.result[.path] / stepN.<output>
    vars_ = ctx.get("vars") or {}
    if var in vars_:
        return to_text(vars_[var])
    if var == "api_key":
        return ctx.get("api_key") or ""
    if var == "base_url":
        return ctx.get("base_url") or ""
    parts = var.split(".")
    if parts[0] == "input":
        return to_text((ctx.get("input") or {}).get(".".join(parts[1:]), ""))
    m = re.match(r"^step(\d+)$", parts[0])
    if m:
        st = (ctx.get("steps") or {}).get(int(m.group(1)))
        if not st:
            return ""
        task = re.match(r"^step\d+\.task(\d+)\.(.+)$", var)
        if task:
            node = st.get("nodes", {}).get(int(task.group(1)))
            if node is None:
                raise ValueError(f"{var}: 이전 작업 결과가 없습니다")
            path = task.group(2)
            if path == "result":
                return to_text(node.get("data") if node.get("data") is not None else node.get("text"))
            if path.startswith("result.") or path.startswith("result["):
                value = get_path(node.get("data"), path[6:])
            else:
                value = get_path(node.get("outputs") or {}, path)
            if value is None:
                raise ValueError(f"{var}: 출력 경로가 없습니다")
            return to_text(value)
        if len(parts) == 1 or (parts[1] == "result" and len(parts) == 2):
            return "\n".join(st["texts"])
        if parts[1] == "result" or parts[1].startswith("result["):
            matches = []
            for d in st["data"]:
                v = get_path(d, var[var.index("result") + 6:])
                if v is not None:
                    matches.append(v)
            if len(matches) > 1:
                raise ValueError(f"{var}: 여러 작업에 같은 경로가 있습니다. stepN.taskM.result 경로를 사용하세요")
            if not matches:
                return ""  # A missing fixed binding is collected by the workflow question card.
            return to_text(matches[0])
        if parts[1] in st.get("ambiguous", set()):
            raise ValueError(f"{var}: 출력 이름이 중복됩니다. stepN.taskM.<출력>을 사용하세요")
        return to_text(st["outputs"].get(parts[1], ""))
    return ""


def substitute(text: str, ctx: dict) -> str:
    if not text:
        return ""
    return _VAR_RX.sub(lambda m: resolve(m.group(1), ctx), text)


def json_payload(template: str, ctx: dict):
    """JSON 문자열 안의 값은 이스케이프하고, 문자열 밖의 변수는 JSON 타입을 보존한다."""
    chunks, pos, quoted, escaped = [], 0, False, False
    for match in _VAR_RX.finditer(template):
        prefix = template[pos:match.start()]
        for char in prefix:
            if escaped:
                escaped = False
            elif char == "\\" and quoted:
                escaped = True
            elif char == '"':
                quoted = not quoted
        chunks.append(prefix)
        value = resolve(match.group(1), ctx)
        if quoted:
            chunks.append(json.dumps(value, ensure_ascii=False)[1:-1])
        else:
            try:
                value = json.loads(value)
            except ValueError:
                pass
            chunks.append(json.dumps(value, ensure_ascii=False))
        pos = match.end()
    chunks.append(template[pos:])
    return json.loads("".join(chunks))


# ────────────────────────────────────────────────────────
# 호출 / Call
# ────────────────────────────────────────────────────────

def _allow_private() -> bool:
    return (os.getenv("FLOW_API_ALLOW_PRIVATE") or "").strip().lower() in ("1", "true", "yes")


def _origin(u: httpx.URL) -> tuple:
    return (u.scheme, u.raw_host.lower(), u.port or (443 if u.scheme == "https" else 80))


def check_url(url: str) -> None:
    """내부망 차단 — 사설·루프백·링크로컬 주소는 거부. 예외: 데모 가상 API(/mock/…) 또는 FLOW_API_ALLOW_PRIVATE=1.
    리다이렉트를 따르지 않으므로(call) 우회도 막힌다.
    판정은 httpx 가 실제로 보낼 모양(httpx.URL — 점 경로 조각을 지운 경로)으로 한다(2026-09-29): 원문 경로로 /mock/ 예외를 보면
    '/mock/../internal' 이 예외를 받은 뒤 httpx 가 '/internal' 로 바꿔 보내던 우회가 있었다. 경로(? 앞)의 역슬래시와, 퍼센트
    디코딩 뒤 남는 . / .. / ..; 조각을 거부한다(%2e%2e 같은 인코딩된 점 경로도 여기서 걸린다 — 디코딩하는 서버 쪽 경로 이동 방지).
    report%2Etxt 같은 일반 인코딩 점과 %2F 같은 인코딩된 구분자는 허용한다(업무 자동화 경로 변수가 quote(safe='') 로 싣는다)."""
    # Private-network guard — private/loopback/link-local targets are refused, except the demo mock APIs
    # (/mock/…) or FLOW_API_ALLOW_PRIVATE=1. Redirects are never followed (call), so they cannot bypass it.
    # The verdict uses the URL httpx will actually send (httpx.URL, dot segments removed; 2026-09-29): checking the raw path let
    # '/mock/../internal' pass the /mock/ exception and then go out as '/internal'. Backslashes in the path (before '?') are
    # refused, as are . / .. / ..; segments left after percent-decoding (this also catches encoded dot segments such as %2e%2e,
    # i.e. traversal on servers that decode). Ordinary encoded dots (report%2Etxt) and encoded separators such as %2F stay
    # allowed (work-agent path variables are sent with quote(safe='')).
    raw = str(url or "")
    if "\\" in re.split(r"[?#]", raw, maxsplit=1)[0]:
        raise ValueError("URL 경로에 역슬래시(\\)를 넣을 수 없습니다")
    try:
        parts = httpx.URL(raw)
    except Exception:  # noqa: BLE001 — httpx.InvalidURL 등 / httpx.InvalidURL and friends
        raise ValueError("URL 형식이 올바르지 않습니다")
    if parts.scheme not in ("http", "https") or not parts.raw_host:
        raise ValueError("URL은 http:// 또는 https:// 주소여야 합니다")
    # 포트 0 도 '없음'이 아니라 잘못된 값이다 / port 0 is an invalid value, not "no port"
    port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
    if not 0 < port < 65536:
        raise ValueError("URL 포트가 올바르지 않습니다")
    path = parts.raw_path.split(b"?", 1)[0].decode("ascii", "replace")   # httpx 가 보낼 경로(점 조각 제거됨) / the path httpx sends
    if any(seg in (".", "..") or seg.startswith(("..;", ".;")) for seg in re.split(r"[/\\]", unquote(path))):
        raise ValueError("URL 경로에 . 또는 .. 경로 조각을 넣을 수 없습니다")
    host = parts.raw_host.decode("ascii", "replace")
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OverflowError):
        raise ValueError(f"주소를 찾을 수 없습니다: {host}")
    try:
        base_origin = _origin(httpx.URL(default_base_url()))
    except Exception:  # noqa: BLE001 — 잘못된 설정값이면 같은 origin 예외 없음 / a malformed setting disables the same-origin exception
        base_origin = None
    # 데모 예외: 설정된 데모 origin 의 /mock/… 만. 루프백(localhost) 의 /mock/… 도 허용(2026-09-15) — 검증용 8010 처럼 다른 포트로 띄운
    # 이 서버 자신을 가리키는 경우(같은 호스트의 데모 경로만, 사설망 일반 주소는 여전히 차단).
    # Demo exception: /mock/… on the configured demo origin, plus /mock/… on loopback (2026-09-15) — e.g. this app on another local
    # port such as the 8010 verification server (demo path on the same host only; other private addresses stay blocked).
    mock_path = path.startswith("/mock/")
    mock = mock_path and _origin(parts) == base_origin
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            if mock or (mock_path and ip.is_loopback) or _allow_private():
                continue
            raise ValueError("사내망·내부 주소로는 호출할 수 없습니다 (데모 가상 API /mock/… 는 허용)")


def _status_ok(status: int, spec: str) -> bool:
    """'2xx' · '200,201' · '200-299' 조합 / status spec matcher"""
    for part in re.split(r"[,\s]+", (spec or "2xx").strip()):
        if not part:
            continue
        p = part.lower()
        if "-" in p:
            a, b = p.split("-", 1)
            if a.isdigit() and b.isdigit() and int(a) <= status <= int(b):
                return True
        elif "x" in p:
            if len(p) == 3 and str(status)[0] == p[0]:
                return True
        elif p.isdigit() and int(p) == status:
            return True
    return False


def _mask(url: str, secret: str) -> str:
    return url.replace(secret, "••••••") if secret and secret in url else url


def redact(value, secret: str = ""):
    """Sanitize diagnostics, including encoded Basic credentials and embedded JSON secrets."""
    if isinstance(value, dict):
        sensitive = r"authorization|cookie|password|secret|token|api[-_]?key"
        secret_row = bool(re.search(sensitive, str(value.get("name", "")), re.I))
        return {k: ("••••••" if (re.search(sensitive, str(k), re.I) or (k == "value" and secret_row)) and v
                    else redact(v, secret)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secret) for v in value]
    if isinstance(value, tuple):
        return tuple(redact(v, secret) for v in value)
    if isinstance(value, str) and secret:
        for encoded in (secret, base64.b64encode(secret.encode()).decode(), json.dumps(secret)[1:-1]):
            value = value.replace(encoded, "••••••")
    return value


def call(config: dict, ctx: dict, keep_body: int = BODY_KEEP) -> dict:
    """요청 1회(재시도 포함) → 결과 dict.
    {ok, status, elapsed_ms, url(비밀 가림), request:{method, headers(가림), body}, response_headers, body_text,
     json, result, result_text, outputs, error, attempts, variables}"""
    # One call (with retries) → result dict.
    cfg = config
    auth, resp = cfg.get("auth") or {}, cfg.get("response") or {}
    secret = auth.get("key") or ""
    ctx = dict(ctx)
    ctx["api_key"] = secret or ctx.get("api_key") or ""
    used_vars = {v: resolve(v, ctx) for v in variables_in(cfg)}
    url = substitute(cfg.get("url") or "", ctx)
    out: dict = {"ok": False, "status": None, "elapsed_ms": 0, "url": _mask(url, secret), "request": {},
                 "response_headers": {}, "body_text": "", "json": None, "result": None, "result_text": "",
                 "outputs": {}, "error": None, "attempts": 0,
                 "variables": {k: (("••••••" if k == "api_key" else v)) for k, v in used_vars.items()}}
    if not url:
        out["error"] = "API URL이 비어 있습니다"
        return out
    try:
        check_url(url)
    except ValueError as e:
        out["error"] = str(e)
        return out

    method = cfg.get("method") or "GET"
    headers = {h["name"]: substitute(h["value"], ctx) for h in (cfg.get("headers") or [])}
    params = [(p["name"], substitute(p["value"], ctx)) for p in (cfg.get("params") or [])]
    a_type = auth.get("type") or "none"
    if a_type == "bearer" and secret:
        headers["Authorization"] = "Bearer " + secret
    elif a_type == "basic" and secret:
        headers["Authorization"] = "Basic " + base64.b64encode(secret.encode("utf-8")).decode("ascii")
    elif a_type == "api_key" and secret:
        if (auth.get("in") or "header") == "query":
            params.append((auth.get("name") or "api_key", secret))
        else:
            headers[auth.get("name") or "Authorization"] = secret

    body = cfg.get("body") or {}
    ct, payload = body.get("content_type") or "none", substitute(body.get("payload") or "", ctx)
    send: dict = {}
    body_note = ""
    if method in ("POST", "PUT", "PATCH", "DELETE") and ct != "none" and payload.strip():
        if ct == "application/json":
            try:
                send["json"] = json_payload(body.get("payload") or "", ctx)
                payload = json.dumps(send["json"], ensure_ascii=False)
            except ValueError:
                out["error"] = "본문이 올바른 JSON이 아닙니다. 입력값과 본문 형식을 확인하세요"
                return out
        elif ct == "application/x-www-form-urlencoded":
            try:
                obj = json.loads(payload)
                send["data"] = obj if isinstance(obj, dict) else {"payload": payload}
            except ValueError:
                send["data"] = dict(p.split("=", 1) for p in payload.split("&") if "=" in p)
        else:
            headers.setdefault("Content-Type", "text/plain; charset=utf-8")
            send["content"] = payload.encode("utf-8")
    out["request"] = {"method": method, "url": _mask(url, secret),
                      "headers": redact(headers, secret),
                      "params": [(k, ("••••••" if secret and v == secret else v)) for k, v in params],
                      "body": (redact(payload, secret)[:2000] if send else ""), "note": body_note}

    attempts = 1 + (int(resp.get("retries") or 0) if resp.get("on_error") == "retry" else 0)
    wait = int(resp.get("retry_wait") or 0)
    timeout = int(cfg.get("timeout") or 30)
    last_err = None
    for i in range(attempts):
        out["attempts"] = i + 1
        t0 = time.perf_counter()
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                r = client.request(method, url, headers=headers, params=params, **send)
            out["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            out["status"] = r.status_code
            out["response_headers"] = {k: v for k, v in list(r.headers.items())[:20]}
            text = r.text or ""
            out["body_text"] = text[:keep_body]
            fmt = resp.get("format") or "auto"
            parsed = None
            ctype = (r.headers.get("content-type") or "").lower()
            if fmt == "json" or (fmt == "auto" and ("json" in ctype or text.lstrip()[:1] in ("{", "["))):
                try:
                    parsed = r.json()
                except ValueError:
                    parsed = None
                    if fmt == "json":
                        last_err = "응답이 JSON이 아닙니다"
            out["json"] = parsed
            ok = _status_ok(r.status_code, resp.get("ok_status") or "2xx") and not (fmt == "json" and parsed is None)
            out["ok"] = ok
            if not ok and last_err is None:
                last_err = f"HTTP {r.status_code}"
            if ok:
                last_err = None
                break
        except httpx.TimeoutException:
            out["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            last_err = f"시간 초과({timeout}초)"
        except httpx.HTTPError as e:
            out["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            last_err = f"연결 실패: {type(e).__name__}"
        if i < attempts - 1 and wait:
            time.sleep(wait)
    out["error"] = last_err

    # 결과 추출·출력 변수(JSON 일 때만 경로 적용) / result extraction and outputs (paths apply to JSON only)
    parsed = out["json"]
    path = (resp.get("path") or "").strip()
    if parsed is not None:
        val = get_path(parsed, path) if path else parsed
        out["result"] = val
        out["result_text"] = to_text(val)[:keep_body] if val is not None else ""
        if path and val is None:
            out["ok"] = False
            out["error"] = out["error"] or f"응답에서 경로 {path} 를 찾지 못했습니다"
        for o in resp.get("outputs") or []:
            v = get_path(parsed, o.get("path") or "")
            if v is None:
                out["ok"] = False
                out["error"] = out["error"] or f"출력 변수 {o['name']}의 경로를 찾지 못했습니다"
            out["outputs"][o["name"]] = v if v is not None else ""
    else:
        out["result"] = out["body_text"]
        out["result_text"] = out["body_text"]
        for o in resp.get("outputs") or []:
            out["outputs"][o["name"]] = ""
        if path or resp.get("outputs"):
            out["ok"] = False
            out["error"] = out["error"] or "JSON 응답이 없어 출력 경로를 추출할 수 없습니다"
    return out
