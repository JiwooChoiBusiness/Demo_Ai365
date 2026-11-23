"""M코스메틱 이메일 에이전트 채팅 MCP 연결(2026-09-30) · 채팅 이메일 분기가 스토어에 닿는 길.

채팅 파이프라인의 업무 자동화 이메일 분기(app/agents/work.py)는 M코스메틱 이메일 에이전트를 그 MCP 서버
(app/mock_mcosmetic_mcp.py, /mock/mcosmetic/mcp)로 부른다(사용자 지시 2026-09-30 "M코스메틱쪽만 채팅 파이프라인에 같이
녹여줄 수 있어?", 워크플로우는 제외). 메일·오류 목록, 메일 상세, 업무 현황 조회(get_work_status), 메일 단위 실행이 모두 도구
호출이고, 채팅 쪽은 app.mcmail 의 정적 상수(ERP_CUSTOMERS · LOOKUP_TARGETS · ERPMETA 등)와 예외 클래스만 쓴다.
워크플로우 업무 자동화 노드(flows._run_auto_node)와 에이전트 화면의 /api/email/ask 는 종전대로 in-process 다.

  - Session: 채팅 실행 1회(확인 카드 실행 1회)마다 하나. 첫 call 때 MCPClient 하나를 열어 핸드셰이크 1번으로 여러 도구를 부른다.
    연결 설정 = builtin_agents.email_connection()(리소스 관리에서 고친 값, 없으면 기본값 — 2026-10-06): 주소의 {{base_url}} 치환 +
    호스트 localhost → 127.0.0.1(Windows 는 ::1 을 먼저 시도해 연결마다 약 2초가 든다), 사설망 가드 flow_api_call.check_url
    (루프백의 /mock/ 는 통과), 인증(기본 Bearer mock_mcosmetic.DEMO_KEY) · 타임아웃(기본 mock_mcosmetic_mcp.TIMEOUT).
    관리자가 '사용 안 함'으로 둔 도구는 부르지 않고 MailValidationError(403)로 돌려준다.
  - call(tool, args) → structuredContent(dict), None 인자는 뺀다. 도구 오류(isError)는 스토어 예외로 되돌린다(404 MailNotFound ·
    409 MailConflict · 그 밖 MailValidationError, 문구는 도구 오류 문장) · 채팅의 except mcmail.MailValidationError 가 그대로 받는다.
    전송·프로토콜 실패(연결 거부 · 시간 초과 · HTTP 오류 · JSON-RPC 오류 · 사설망 가드)는 Unavailable(한국어, 인증 키는 가린다).
    in-process 대체 호출은 하지 않는다.
  - calls / tools(): 서버가 답한 도구 이름(순서대로, tools() 는 중복 제거) · 채팅 결과 extras.mcp_tools(진행 줄의 MCP 표시 재료).
  - TRANSPORT: 테스트용 httpx 전송 주입점(None = 실제 HTTP).

M Cosmetic Email Agent chat MCP link (2026-09-30): how the chat's email branch reaches the store. The work agent's email
branch in the chat pipeline (app/agents/work.py) calls the M Cosmetic Email Agent through its MCP server
(app/mock_mcosmetic_mcp.py, /mock/mcosmetic/mcp; user request 2026-09-30, the workflow excluded). Mail and error lists,
mail details, the work-status read (get_work_status) and the per-mail actions are all tool calls; the chat side keeps only
app.mcmail's static constants (ERP_CUSTOMERS, LOOKUP_TARGETS, ERPMETA, ...) and exception classes. The workflow automation
node (flows._run_auto_node) and the agent page's /api/email/ask stay in-process.
  - Session: one per chat run (or confirm-card run). The first call opens one MCPClient, so one handshake serves several
    tools. The settings come from builtin_agents.email_connection() (edited in Resource Management, else the defaults,
    2026-10-06): the URL with {{base_url}} substituted and a localhost host rewritten to 127.0.0.1 (Windows tries ::1 first,
    about 2 s per connection), the private-network guard flow_api_call.check_url (loopback /mock/ passes), the auth (default
    Bearer mock_mcosmetic.DEMO_KEY) and the timeout (default mock_mcosmetic_mcp.TIMEOUT). A tool the admin disabled is never
    called and raises MailValidationError (403).
  - call(tool, args) → structuredContent (dict), None arguments dropped. Tool errors (isError) come back as the store's
    exceptions (404 MailNotFound, 409 MailConflict, otherwise MailValidationError, with the tool's error text), so the chat's
    except mcmail.MailValidationError keeps working. Transport and protocol failures (refused, timeout, HTTP error, JSON-RPC
    error, private-network guard) raise Unavailable (Korean, auth key masked). There is no in-process fallback call.
  - calls / tools(): the tool names the server answered, in order (tools() deduplicated), for the chat result's
    extras.mcp_tools (the progress line's MCP marker).
  - TRANSPORT: httpx transport seam for tests (None = real HTTP).
"""

from __future__ import annotations

import re
import ssl
import threading

import httpx

from app import builtin_agents, flow_api_call, mcmail, mcp_client, mcp_servers, mock_mcosmetic, mock_mcosmetic_mcp
from app.connectors import SECRET_MASK

TRANSPORT = None   # 테스트 전송 주입점(httpx 전송) · None = 실제 HTTP / test transport seam; None = real HTTP
# 사용자에게 보이는 연결 실패 문장(채팅 fail_reason · 확인 카드 실행 오류) / the user-facing unreachable sentence
UNREACHABLE = "M코스메틱 MCP 서버에 연결하지 못했습니다."
# 실행 도구를 부르다 응답을 못 받은 경우 — 서버에서는 이미 처리됐을 수 있다(2026-09-30 리뷰) / a write tool lost its reply; the
# server may already have done it (2026-09-30 review)
UNANSWERED = "M코스메틱 MCP 서버의 응답을 받지 못했습니다. 처리 여부는 이메일 에이전트 화면에서 확인해 주세요."
# 상태를 바꾸는 도구(readOnlyHint 가 아닌 것) / the state-changing tools (not readOnlyHint)
WRITE_TOOLS = frozenset(t["name"] for t in mock_mcosmetic_mcp.TOOLS if not (t.get("annotations") or {}).get("readOnlyHint"))

_LOCALHOST_RX = re.compile(r"^(https?://(?:[^@/?#]*@)?)localhost(?=[:/?#]|$)", re.I)
# 도구 오류 상태 → 스토어 예외(그 밖은 MailValidationError) / tool-error status → the store's exception (else MailValidationError)
_ERRORS = {404: mcmail.MailNotFound, 409: mcmail.MailConflict}

_SSL: ssl.SSLContext | None = None
_SSL_LOCK = threading.Lock()


class Unavailable(Exception):
    """MCP 서버에 닿지 못했다(연결 거부 · 시간 초과 · HTTP 오류 · JSON-RPC 오류 · 사설망 가드). 문구는 한국어, 인증 키는 가린다.
    write=True 는 실행 도구를 부르던 중이라 서버에서 이미 처리됐을 수 있다는 뜻이다(user_message 가 화면 확인을 안내).
    The MCP server could not be reached (refused, timeout, HTTP error, JSON-RPC error, private-network guard); Korean text,
    auth key masked. write=True means a write tool was in flight, so the server may already have done it (user_message then
    points to the screen)."""

    def __init__(self, message: str, *, write: bool = False) -> None:
        super().__init__(message)
        self.write = write

    @property
    def user_message(self) -> str:
        return UNANSWERED if self.write else UNREACHABLE


def _mask(text, key: str = "") -> str:
    """문구 속 인증 키 가리기(서버 오류 문장이 키를 되풀이할 수 있다) — 기본 키와 고친 키 둘 다 / mask the default and the edited key"""
    out = str(text or "").replace(mock_mcosmetic.DEMO_KEY, SECRET_MASK)
    return out.replace(key, SECRET_MASK) if key else out


def _ssl_context() -> ssl.SSLContext:
    """모듈 공용 SSL 컨텍스트(httpx 기본과 같은 검증). 클라이언트마다 새로 만들면 0.2~0.5초가 든다.
    One shared SSL context (httpx's default verification); building one per client costs 0.2 to 0.5 s."""
    global _SSL
    if _SSL is None:
        with _SSL_LOCK:
            if _SSL is None:
                _SSL = httpx.create_ssl_context()
    return _SSL


def server_url(url: str | None = None) -> str:
    """연결 주소 · {{base_url}} 치환 뒤 호스트 localhost → 127.0.0.1(주소를 안 주면 리소스 관리에서 고친 값 · 기본값)
    The server URL: {{base_url}} substituted, localhost rewritten to 127.0.0.1 (no argument = the edited URL or the default)"""
    raw = url if url is not None else builtin_agents.email_connection()["url"]
    target = flow_api_call.substitute(raw, flow_api_call.build_ctx()).strip()
    return _LOCALHOST_RX.sub(r"\g<1>127.0.0.1", target, count=1)


class Session:
    """채팅 실행 1회의 MCP 연결 · with 문으로 쓰고, 첫 call 때 연결한다. 연결 설정은 실행 1회 동안 한 번만 읽는다.
    One chat run's MCP link, used in a with block and connected lazily on the first call; the settings are read once per run."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._client: mcp_client.MCPClient | None = None
        self._conf: dict | None = None

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _config(self) -> dict:
        if self._conf is None:
            self._conf = builtin_agents.email_connection()
        return self._conf

    def _key(self) -> str:
        return str((self._config().get("auth") or {}).get("key") or "")

    def _connect(self) -> mcp_client.MCPClient:
        if self._client is None:
            conf = self._config()
            url = server_url(conf["url"])
            try:
                flow_api_call.check_url(url)
            except ValueError as e:
                raise Unavailable(f"M코스메틱 MCP 서버 주소를 쓸 수 없습니다: {_mask(e, self._key())}") from None
            # 테스트 전송이면 SSL 컨텍스트를 만들지 않는다 / no SSL context with a test transport
            self._client = mcp_client.MCPClient(
                url, mcp_servers.auth_headers(conf["auth"]), timeout=conf["timeout"],
                transport=TRANSPORT, verify=True if TRANSPORT is not None else _ssl_context())
        return self._client

    def call(self, tool: str, args: dict | None = None) -> dict:
        """도구 1회 호출 → structuredContent. 도구 오류는 스토어 예외, 전송·프로토콜 실패는 Unavailable,
        관리자가 쓰지 않게 한 도구는 부르지 않고 MailValidationError(403).
        One tool call → structuredContent; tool errors raise the store's exceptions, transport and protocol failures
        raise Unavailable, and a tool the admin disabled raises MailValidationError (403) without a call."""
        if tool in self._config()["disabled"]:
            raise mcmail.MailValidationError(f"관리자가 사용하지 않도록 설정한 도구라 부를 수 없습니다: {tool}", 403)
        clean = {k: v for k, v in (args or {}).items() if v is not None}
        client = self._connect()
        try:
            res = client.call_tool(tool, clean)
        except (mcp_client.MCPError, httpx.HTTPError) as e:
            # 응답 본문을 읽다 끊긴 httpx 오류(ReadTimeout 등)는 MCPClient 가 감싸지 않으므로 함께 받는다(2026-09-30 리뷰)
            # httpx errors while reading the reply body (ReadTimeout, ...) are not wrapped by MCPClient, so catch them too
            raise Unavailable(f"M코스메틱 MCP 도구 {tool} 호출 실패: {_mask(e, self._key()) or type(e).__name__}",
                              write=tool in WRITE_TOOLS) from None
        self.calls.append(tool)
        conv = mcp_client.result_to_common(res)
        data = conv.get("json")
        if not conv["ok"]:
            info = data.get("error") if isinstance(data, dict) else None
            info = info if isinstance(info, dict) else {}
            status = info.get("status")
            status = status if isinstance(status, int) and not isinstance(status, bool) else None
            message = str(info.get("message") or conv.get("error") or "도구가 오류를 돌려주었습니다")
            raise _ERRORS.get(status, mcmail.MailValidationError)(message, status)
        if not isinstance(data, dict):
            raise Unavailable(f"M코스메틱 MCP 도구 {tool} 응답에 구조화 결과가 없습니다")
        return data

    def tools(self) -> list[str]:
        """서버가 답한 도구 이름(부른 순서, 중복 제거) / the tools the server answered, in call order, deduplicated"""
        return list(dict.fromkeys(self.calls))

    def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            client.close()
