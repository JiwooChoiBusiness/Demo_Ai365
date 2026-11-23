"""MCP 클라이언트(2026-09-15) — 원격 MCP 서버의 도구 목록 조회·도구 호출. Streamable HTTP 전송만 지원한다
(요청 = JSON-RPC POST, 응답 = application/json 또는 text/event-stream). 로컬 프로세스(stdio) 서버는 다루지 않는다
(고객사 테넌트 배포 전제 — 서버가 프로세스를 띄우지 않는다).

  - MCPClient(url, headers, timeout)  : initialize → notifications/initialized → tools/list(커서 페이지) → tools/call
  - normalize_tool(raw)               : 서버 도구 명세 → 우리 명세 {name, title, description, input_schema, annotations, kind_default, unsupported}
                                        (JSON Schema 는 string/integer/number/boolean/object/array 로 단순화, 못 옮긴 항목은 unsupported 에 표시)
  - result_to_common(result)          : tools/call 결과(content 블록·structuredContent·isError) → 공통 결과 {ok, result_text, json, outputs, error}
호출마다 initialize 핸드셰이크를 새로 한다(무상태 — 세션 id 는 서버가 주면 따라 보낸다). 사설망 차단은 호출자가 flow_api_call.check_url 로 한다.

MCP client (2026-09-15) — list and call tools on a remote MCP server. Streamable HTTP only (JSON-RPC POST; the response
is application/json or text/event-stream). Local stdio servers are out of scope (customer-tenant deployment: the server
never spawns processes).
  - MCPClient(url, headers, timeout)  : initialize → notifications/initialized → tools/list (cursor pages) → tools/call
  - normalize_tool(raw)               : server tool spec → our spec (JSON Schema simplified to the six supported types;
                                        anything that could not be mapped is listed under `unsupported`)
  - result_to_common(result)          : tools/call result (content blocks, structuredContent, isError) → the common result shape
Every operation performs a fresh initialize handshake (stateless; a server-issued session id is echoed back). The
private-network guard is the caller's job (flow_api_call.check_url).
"""

from __future__ import annotations

import json
import re
import time

import httpx

PROTOCOL_VERSION = "2025-06-18"
MAX_BODY = 1_000_000          # 응답 본문 상한(바이트) / response body cap (bytes)
MAX_TOOLS = 100               # 서버 1개당 도구 상한 / tools per server
MAX_LIST_PAGES = 20
MAX_OUTPUTS = 20              # structuredContent 최상위 스칼라 → 출력 변수 상한 / top-level scalars → output variables
TYPES = ("string", "integer", "number", "boolean", "object", "array")
_NAME_RX = re.compile(r"^[A-Za-z0-9_.\-]{1,120}$")
_OUT_NAME_RX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")


class MCPError(Exception):
    """서버 오류·전송 오류 — message 는 사용자에게 그대로 보여도 되는 한 줄 / a one-line, user-facing message"""

    def __init__(self, message: str, code: int | None = None, data=None):
        super().__init__(message)
        self.code, self.data = code, data


class MCPClient:
    def __init__(self, url: str, headers: dict | None = None, timeout: int = 30, transport=None, verify=True):
        # verify(2026-09-29): 호출자가 공용 SSL 컨텍스트를 넘기면 클라이언트마다 새로 만드는 비용(0.2~0.5초)이 없다. 기본값은 httpx 기본 검증.
        # verify (2026-09-29): a caller-supplied shared SSL context skips the per-client build (0.2 to 0.5 s); the default is httpx's own.
        self.url = url
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.session_id: str | None = None
        self.protocol = PROTOCOL_VERSION
        self.server_info: dict = {}
        self.capabilities: dict = {}
        self._initialized = False
        self._seq = 0
        self._client = httpx.Client(timeout=timeout, follow_redirects=False, transport=transport, verify=verify)

    # ── 수명 / lifecycle ──
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        """세션이 있으면 DELETE 로 종료(실패 무시) 후 연결 닫기 / end a server session (best effort), then close"""
        try:
            if self.session_id:
                self._client.request("DELETE", self.url, headers=self._base_headers())
        except Exception:  # noqa: BLE001 — 종료 실패는 무시 / termination failures are ignored
            pass
        finally:
            self._client.close()

    # ── 전송 / transport ──
    def _base_headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        h.update(self.headers)
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        if self._initialized:
            h["MCP-Protocol-Version"] = self.protocol
        return h

    def _post(self, msg: dict) -> dict | None:
        """JSON-RPC 메시지 1건 전송 → 같은 id 의 응답(알림이면 None). JSON·SSE 응답 모두 처리."""
        # Send one JSON-RPC message → the response with the same id (None for notifications). Handles JSON and SSE.
        req = self._client.build_request("POST", self.url, headers=self._base_headers(),
                                         content=json.dumps(msg, ensure_ascii=False).encode("utf-8"))
        try:
            r = self._client.send(req, stream=True)
        except httpx.TimeoutException:
            raise MCPError(f"MCP 서버가 {self.timeout}초 안에 응답하지 않았습니다")
        except httpx.HTTPError as e:
            raise MCPError(f"MCP 서버에 연결할 수 없습니다: {e.__class__.__name__}")
        try:
            sid = r.headers.get("mcp-session-id")
            if sid:
                self.session_id = sid[:200]
            want = msg.get("id")
            if want is None:   # 알림 — 202/204 를 기대하되 본문은 무시 / notification: expect 202/204, ignore any body
                if r.status_code >= 400:
                    raise MCPError(f"MCP 서버 오류 HTTP {r.status_code}")
                return None
            if r.status_code >= 400:
                text = self._read_capped(r)
                detail = ""
                try:
                    j = json.loads(text) if text else {}
                    detail = (j.get("error") or {}).get("message") if isinstance(j, dict) else ""
                except ValueError:
                    detail = text[:160]
                raise MCPError(f"MCP 서버 오류 HTTP {r.status_code}" + (f": {detail}" if detail else ""))
            ctype = (r.headers.get("content-type") or "").lower()
            if "text/event-stream" in ctype:
                return self._read_sse(r, want)
            text = self._read_capped(r)
            if not text.strip():
                raise MCPError("MCP 서버가 빈 응답을 보냈습니다")
            try:
                body = json.loads(text)
            except ValueError:
                raise MCPError("MCP 서버 응답이 JSON 이 아닙니다")
            found = self._match(body, want)
            if found is None:
                raise MCPError("MCP 서버 응답에 요청 id 가 없습니다")
            return found
        finally:
            r.close()

    @staticmethod
    def _match(body, want):
        if isinstance(body, dict) and body.get("id") == want and ("result" in body or "error" in body):
            return body
        if isinstance(body, list):
            for item in body:
                if isinstance(item, dict) and item.get("id") == want and ("result" in item or "error" in item):
                    return item
        return None

    @staticmethod
    def _read_capped(r: httpx.Response) -> str:
        total, chunks = 0, []
        for chunk in r.iter_bytes():
            total += len(chunk)
            if total > MAX_BODY:
                raise MCPError(f"MCP 서버 응답이 너무 큽니다({MAX_BODY // 1000}KB 초과)")
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")

    def _read_sse(self, r: httpx.Response, want) -> dict:
        """SSE 스트림에서 우리 요청 id 의 응답이 나오면 즉시 반환(서버→클라이언트 요청·알림은 무시)."""
        # Read the SSE stream until the response for our id shows up (server-side requests/notifications are ignored).
        total, data_lines = 0, []
        for line in r.iter_lines():
            total += len(line) + 1
            if total > MAX_BODY:
                raise MCPError(f"MCP 서버 응답이 너무 큽니다({MAX_BODY // 1000}KB 초과)")
            if line == "":
                if data_lines:
                    raw = "\n".join(data_lines)
                    data_lines = []
                    try:
                        body = json.loads(raw)
                    except ValueError:
                        continue
                    found = self._match(body, want)
                    if found is not None:
                        return found
                continue
            if line.startswith(":"):
                continue   # 주석 / comment
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if data_lines:   # 마지막 이벤트가 빈 줄 없이 끝난 경우 / a final event without the trailing blank line
            try:
                found = self._match(json.loads("\n".join(data_lines)), want)
                if found is not None:
                    return found
            except ValueError:
                pass
        raise MCPError("MCP 서버가 응답 없이 스트림을 끝냈습니다")

    # ── JSON-RPC ──
    def _rpc(self, method: str, params: dict | None = None) -> dict:
        self._seq += 1
        msg = {"jsonrpc": "2.0", "id": self._seq, "method": method}
        if params is not None:
            msg["params"] = params
        res = self._post(msg)
        if res is None:
            raise MCPError("MCP 서버가 응답하지 않았습니다")
        if "error" in res:
            err = res.get("error") or {}
            raise MCPError(str(err.get("message") or "MCP 오류")[:300], err.get("code"), err.get("data"))
        result = res.get("result")
        return result if isinstance(result, dict) else {}

    def _notify(self, method: str, params: dict | None = None) -> None:
        msg = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        self._post(msg)

    # ── 절차 / operations ──
    def initialize(self) -> dict:
        res = self._rpc("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                       "clientInfo": {"name": "ai365-unified", "version": "3.0"}})
        ver = str(res.get("protocolVersion") or PROTOCOL_VERSION)[:20]
        self.protocol = ver
        self.server_info = res.get("serverInfo") if isinstance(res.get("serverInfo"), dict) else {}
        self.capabilities = res.get("capabilities") if isinstance(res.get("capabilities"), dict) else {}
        self._initialized = True
        self._notify("notifications/initialized")
        return res

    def list_tools(self) -> list[dict]:
        if not self._initialized:
            self.initialize()
        tools: list[dict] = []
        cursor, pages = None, 0
        while True:
            res = self._rpc("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(t for t in (res.get("tools") or []) if isinstance(t, dict))
            cursor = res.get("nextCursor")
            pages += 1
            if not cursor or pages >= MAX_LIST_PAGES or len(tools) >= MAX_TOOLS:
                break
        return tools[:MAX_TOOLS]

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        if not self._initialized:
            self.initialize()
        return self._rpc("tools/call", {"name": name, "arguments": arguments or {}})


# ────────────────────────────────────────────────────────
# 도구 명세 정규화 / tool spec normalization
# ────────────────────────────────────────────────────────

def _pick_type(prop: dict) -> tuple[str | None, str | None]:
    """속성의 type 을 우리 6종으로 → (type, 문제) / map a property type to our six → (type, problem)"""
    t = prop.get("type")
    if isinstance(t, list):
        cands = [x for x in t if x in TYPES]
        if cands:
            return cands[0], ("여러 타입 중 첫 번째만 사용" if len([x for x in t if x != "null"]) > 1 else None)
        return None, "지원하지 않는 타입 목록"
    if isinstance(t, str):
        if t in TYPES:
            return t, None
        if t == "null":
            return "string", "null 타입은 문자열로 처리"
        return None, f"지원하지 않는 타입 {t}"
    if isinstance(prop.get("enum"), list):
        return "string", None
    for k in ("anyOf", "oneOf", "allOf", "$ref", "not"):
        if k in prop:
            return "string", f"{k} 명세는 문자열(JSON 텍스트)로 처리"
    return "string", "타입이 없어 문자열로 처리"


def normalize_schema(schema, path: str = "") -> tuple[dict, list[str]]:
    """JSON Schema(객체) → 우리 형식. 반환 (schema, unsupported["경로: 사유"…])."""
    # JSON Schema (object) → our shape. Returns (schema, unsupported ["path: reason", ...]).
    unsupported: list[str] = []
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}, "required": []}, ["입력 명세가 객체가 아니어서 비웠습니다"]
    props_in = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    props: dict = {}
    for name, prop in props_in.items():
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(prop, dict):
            prop = {}
        here = f"{path}.{name}" if path else name
        out, problems = _normalize_prop(prop, here)
        props[name] = out
        unsupported.extend(problems)
    req_in = schema.get("required") if isinstance(schema.get("required"), list) else []
    required = [r for r in req_in if isinstance(r, str) and r in props]
    out_schema = {"type": "object", "properties": props, "required": required}
    if isinstance(schema.get("description"), str) and schema["description"].strip():
        out_schema["description"] = schema["description"].strip()[:500]
    return out_schema, unsupported


def _normalize_prop(prop: dict, here: str) -> tuple[dict, list[str]]:
    problems: list[str] = []
    typ, problem = _pick_type(prop)
    if typ is None:
        typ = "string"
        problems.append(f"{here}: {problem or '지원하지 않는 명세'}")
    elif problem:
        problems.append(f"{here}: {problem}")
    out: dict = {"type": typ}
    desc = prop.get("description")
    if isinstance(desc, str) and desc.strip():
        out["description"] = desc.strip()[:500]
    elif isinstance(prop.get("title"), str) and prop["title"].strip():
        out["description"] = prop["title"].strip()[:500]
    if isinstance(prop.get("enum"), list) and prop["enum"]:
        vals = [v for v in prop["enum"] if isinstance(v, (str, int, float)) and not isinstance(v, bool)]
        if vals:
            out["enum"] = vals[:50]
    if "default" in prop and prop["default"] is not None:
        out["default"] = prop["default"]
    ex = prop.get("examples")
    if isinstance(ex, list) and ex:
        out["examples"] = ex[:3]
    if typ == "object":
        sub, sub_problems = normalize_schema(prop, here)
        out["properties"], out["required"] = sub["properties"], sub["required"]
        problems.extend(sub_problems)
    elif typ == "array":
        items = prop.get("items")
        if isinstance(items, dict):
            item_out, item_problems = _normalize_prop(items, here + "[]")
            out["items"] = item_out
            problems.extend(item_problems)
        else:
            out["items"] = {"type": "string"}
            if items is not None:
                problems.append(f"{here}[]: 항목 명세를 문자열로 처리")
    return out, problems


def normalize_tool(raw: dict) -> dict | None:
    """서버가 준 도구 1개 → 우리 명세. 이름이 없거나 형식이 틀리면 None."""
    # One server tool → our spec. None when the name is missing or malformed.
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not _NAME_RX.match(name):
        return None
    ann_in = raw.get("annotations") if isinstance(raw.get("annotations"), dict) else {}
    title = raw.get("title") or ann_in.get("title") or name
    title = str(title).strip()[:80] or name
    desc = str(raw.get("description") or "").strip()[:500]
    schema, unsupported = normalize_schema(raw.get("inputSchema") or {"type": "object", "properties": {}})
    ann = {k: bool(ann_in[k]) for k in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
           if isinstance(ann_in.get(k), bool)}
    # 종류 기본값: 읽기 전용 힌트가 참일 때만 조회, 나머지는 실행(안전 쪽) / default kind: read only when readOnlyHint is true, else action (safe side)
    kind_default = "read" if ann.get("readOnlyHint") is True else "action"
    # 출력 명세(outputSchema, MCP 2025-06-18)는 화면의 [명세 보기]용으로 그대로 보존한다(실행에는 쓰지 않는다, 2026-09-23)
    # The output schema (outputSchema, MCP 2025-06-18) is kept as-is for the screen's [View schema]; the runtime does not use it (2026-09-23)
    out_schema = raw.get("outputSchema") if isinstance(raw.get("outputSchema"), dict) else None
    return {"name": name, "title": title, "description": desc, "input_schema": schema, "output_schema": out_schema,
            "annotations": ann, "kind_default": kind_default, "unsupported": unsupported[:20]}


# ────────────────────────────────────────────────────────
# 결과 변환 / result conversion
# ────────────────────────────────────────────────────────

def _scalar(v) -> bool:
    return isinstance(v, (str, int, float, bool)) or v is None


def result_to_common(res: dict, keep_body: int = 8000) -> dict:
    """tools/call 결과 → 공통 결과. 텍스트 블록은 이어 붙이고, structuredContent(없으면 JSON 텍스트)는 data 로,
    최상위 스칼라는 출력 변수로 옮긴다. 이미지·오디오·리소스 블록은 세어서 안내만 남긴다."""
    # tools/call result → the common shape. Text blocks are joined; structuredContent (or JSON text) becomes data and
    # its top-level scalars become output variables. Image/audio/resource blocks are only counted.
    content = res.get("content") if isinstance(res, dict) else None
    content = content if isinstance(content, list) else []
    texts, skipped = [], 0
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and block.get("text") is not None:
            texts.append(str(block.get("text")))
        else:
            skipped += 1
    text = "\n".join(texts)
    structured = res.get("structuredContent") if isinstance(res, dict) else None
    data = structured if isinstance(structured, (dict, list)) else None
    if data is None and text.strip()[:1] in ("{", "["):
        try:
            data = json.loads(text)
        except ValueError:
            data = None
    is_error = bool(isinstance(res, dict) and res.get("isError"))
    outputs: dict = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(k, str) and _OUT_NAME_RX.match(k) and _scalar(v) and k != "result":
                outputs[k] = v
                if len(outputs) >= MAX_OUTPUTS:
                    break
    result_text = text if text else (json.dumps(data, ensure_ascii=False) if data is not None else "")
    if skipped:
        result_text = (result_text + "\n" if result_text else "") + f"(텍스트가 아닌 블록 {skipped}개는 생략했습니다)"
    return {"ok": not is_error, "result_text": result_text[:keep_body], "json": data,
            "result": data if data is not None else text, "outputs": outputs,
            "error": ((text.strip()[:300] or "도구가 오류를 돌려주었습니다") if is_error else None),
            "blocks": len(content), "skipped_blocks": skipped}


def elapsed_ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)
