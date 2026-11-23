"""M코스메틱 이메일 에이전트 MCP 서버(2026-09-29) · /mock/mcosmetic/mcp.

리소스 센터 › 리소스 관리 › 업무 자동화 에이전트 탭에서 M코스메틱 이메일 에이전트는 MCP 방식으로 연결된다(사용자 지시
2026-09-29, 종전 열람 전용 API 레지스트리를 대체). 이 모듈이 그 연결 대상 서버다. 도구는 /api/email 의 조회와 메일 처리
기능에 1:1 로 대응하고(화면 초기화 meta, 데모 시나리오·초기화, 채팅 /ask 의 LLM 답변은 뺐다) 같은 스토어(app.mcmail)를
부르므로, MCP 로 처리한 결과가 /email 화면에 그대로 보인다.

채팅 파이프라인도 이 서버를 쓴다(사용자 지시 2026-09-30): 업무 자동화 에이전트의 이메일 분기(app/agents/work.py)는
app/mcmail_link.py 로 이 서버에 붙어 메일·오류 목록, 메일 상세, 업무 현황 조회(get_work_status), 메일 단위 실행을 모두
도구로 부른다. 워크플로우 업무 자동화 노드(flows._run_auto_node)와 에이전트 화면의 /api/email/ask 는 종전대로 in-process 다.

  - 전송: Streamable HTTP(JSON-RPC POST, 응답은 JSON). 인증: Authorization: Bearer demo-mcosmetic-key-2026
    (가상 ERP·메일 API 와 같은 데모 표시값이며 실제 비밀값이 아니다).
  - 메서드: initialize · notifications/initialized(202) · ping · tools/list · tools/call. 그 밖은 -32601.
  - 도구 25종: 조회 10(readOnlyHint, 맨 앞이 채팅의 주 조회인 get_work_status = mcmail.lookup + fallback_answer 결정적 표) ·
    실행 15. 필수 인자·enum 위반, 없는 id, 업무 규칙 위반은 isError 결과로 돌려준다(문구는 스토어 그대로). isError 결과의
    structuredContent.error 에 상태(404 없음 · 409 충돌 · 422 입력·규칙 오류)와 문구를 함께 실어, 채팅 연결이 스토어 예외로
    되돌린다.
  - handle(msg, authorization) 은 HTTP 없이 부르는 처리 함수다(테스트가 그대로 부른다). registry_config() 는 업무 자동화
    탭이 보여 줄 연결 설정(주소 · 인증(키 가림) · 도구 명세)이며, 도구 명세는 tools/list 와 같은 목록을 우리 명세로 옮긴 것이다.

M Cosmetic Email Agent MCP server (2026-09-29) at /mock/mcosmetic/mcp. In Resource Center › Resource Management ›
Work-automation agents the M Cosmetic Email Agent is now connected over MCP (user request 2026-09-29, replacing the
read-only API registry); this module is the server it connects to. The tools map 1:1 to the /api/email reads and mail
actions (the page bootstrap meta, the demo scenario/reset and the chat /ask LLM answer are left out) and call the same
store (app.mcmail), so anything done over MCP shows up on the /email screen.

The chat pipeline uses this server too (user request 2026-09-30): the work agent's email branch (app/agents/work.py)
connects through app/mcmail_link.py and calls the mail and error lists, mail details, the work-status read
(get_work_status) and the per-mail actions as tools. The workflow automation node (flows._run_auto_node) and the agent
page's /api/email/ask stay in-process.
  - Transport: Streamable HTTP (JSON-RPC POST, JSON responses). Auth: Authorization: Bearer demo-mcosmetic-key-2026 (the
    same demo display value as the fictional ERP and mail API, not a real secret).
  - Methods: initialize, notifications/initialized (202), ping, tools/list, tools/call; anything else is -32601.
  - 25 tools: 10 reads (readOnlyHint; first is the chat's main read, get_work_status = the deterministic
    mcmail.lookup + fallback_answer tables) and 15 actions. Missing required arguments, enum violations, unknown ids and
    business rule violations come back as isError results carrying the store's message; their structuredContent.error
    carries the status (404 not found, 409 conflict, 422 input or rule error) and the message, so the chat link can raise
    the store's exception again.
  - handle(msg, authorization) is the HTTP-free handler that tests call directly. registry_config() is the connection the
    automation tab shows (URL, masked auth, tool specs normalized from the same list tools/list serves).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from app import mcmail, mcp_client
from app.connectors import SECRET_MASK
from app.mock_mcosmetic import DEMO_KEY

router = APIRouter(prefix="/mock/mcosmetic", tags=["mock-mcosmetic-mcp"])

URL = "{{base_url}}/mock/mcosmetic/mcp"   # 업무 자동화 탭에 보이는 서버 주소(배포 호스트를 따라간다) / the server URL shown in the tab
TIMEOUT = 30
PROTOCOL = "2025-06-18"
SUPPORTED = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "M코스메틱 이메일 에이전트 MCP 서버", "version": "1.0.0"}
# 업무 자동화 탭의 에이전트 설명 — 종전 API 레지스트리와 같은 문장(EN 사전 키 공유) / the tab's description, same sentence as the old registry
DESCRIPTION = "M코스메틱 이메일 에이전트 · 고객 메일 분류와 견적·주문·출하·재고·인보이스 업무, 가상 ERP 연동"

# ── 입력 명세 조각 / schema pieces ──
_EMAIL_ID = {"type": "string", "description": "메일 ID", "examples": ["E-1001"]}
_CASE_ID = {"type": "string", "description": "업무 Case ID", "examples": ["RFQ-2026-00123"]}
_LANG = {"type": "string", "description": "답변 초안 언어(ko 한국어 · en 영어)", "enum": ["ko", "en"], "default": "ko"}
_FROM = {"type": "string", "description": "시작일(YYYY-MM-DD)"}
_TO = {"type": "string", "description": "종료일(YYYY-MM-DD)"}
_READ = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
_SET = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
_ACT = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}


def _tool(name: str, title: str, description: str, props: dict | None = None, required: list | None = None,
          ann: dict | None = None) -> dict:
    return {"name": name, "title": title, "description": description,
            "inputSchema": {"type": "object", "properties": props or {}, "required": required or []},
            "annotations": {"title": title, **(ann or _READ)}}


TOOLS: list[dict] = [
    # 조회 10종 · 맨 앞은 채팅 이메일 분기의 주 조회(2026-09-30) / ten reads; the first is the chat email branch's main read
    _tool("get_work_status", "업무 현황 조회",
          "담당자 확인 필요 메일 · 오늘 처리 현황 · 유형별 메일 · 업무 Case · 처리오류 · 고객사 거래 현황 · Case 상세를 조회해, "
          "표로 정리한 답변(answer)과 원본 데이터(data)를 함께 돌려줍니다.",
          {"target": {"type": "string", "enum": list(mcmail.LOOKUP_TARGETS),
                      "description": "조회 대상(inbox 담당자 확인 필요 메일 · today 오늘 처리 현황 · quotes 견적요청 · "
                                     "orders 주문등록 · shipments 출하일정 · stock 재고 · invoices 인보이스 발행요청 · "
                                     "cases 업무 Case · errors 처리오류 · customer 고객사 거래 현황 · case 업무 Case 상세)"},
           "customer": {"type": "string", "description": "고객사 이름 또는 코드(target 이 customer 일 때 필수)",
                        "examples": ["누리뷰티 02"]},
           "case_id": {**_CASE_ID, "description": "업무 Case ID(target 이 case 일 때 필수)"},
           "filters": {"type": "object", "additionalProperties": False,
                       "description": "조회 조건. 조건 적용 후 건수를 집계합니다. 재고·출하의 기간/메일상태 조건은 해당 문의메일만 조회하며 ERP 과거 재고나 출하일 조건이 아닙니다. case 상세는 필터를 지원하지 않습니다.",
                       "properties": {
                           "date_from": _FROM, "date_to": _TO,
                           "customer": {"type": "string", "description": "해당 고객사만 조회(정확한 이름 또는 코드)"},
                           "q": {"type": "string", "description": "제목·품목·ID 검색어. 자연어 질문 전체 대신 실제 검색어만 입력"},
                           "status": {"type": "string", "enum": ["all", "todo", "done", "err", "open", "resolved"],
                                      "description": "메일 all/todo/done/err, cases all/open/done, errors all/open/resolved(done), customer all/todo/done"}}}},
          ["target"]),
    _tool("get_dashboard", "대시보드 조회",
          "기준일(기본 오늘)에 받은 메일의 처리 KPI, 업무 유형별 현황, 먼저 처리할 메일을 조회합니다.",
          {"date": {"type": "string", "description": "기준일(YYYY-MM-DD). 비우면 오늘"}}),
    _tool("list_mails", "메일 목록 조회",
          "메뉴와 처리 상태로 받은 메일을 조회합니다. 검색어와 수신 기간으로 좁힐 수 있습니다.",
          {"view": {"type": "string", "enum": list(mcmail.MAIL_VIEWS),
                    "description": "메뉴(inbox 수신메일 · quote 견적요청 · order 주문등록 · ship 출하일정 · stock 재고문의 · "
                                   "invoice 인보이스 발행요청 · etc 기타). 비우면 받은 메일 전체"},
           "filter": {"type": "string", "enum": ["todo", "err", "done", "all"], "default": "todo",
                      "description": "처리 상태(todo 할 일 · err 오류 · done 완료 · all 전체). inbox 는 todo · all 만"},
           "q": {"type": "string", "description": "검색어(고객사 · 제목 · 품목 · Case 번호)"},
           "date_from": _FROM, "date_to": _TO}),
    _tool("get_mail", "메일 상세 조회",
          "메일 1건의 본문 · 추출값 · 처리 단계와 연결된 Case, 같은 Case 의 다른 메일, 미해결 오류를 조회합니다.",
          {"email_id": _EMAIL_ID}, ["email_id"]),
    _tool("list_cases", "업무 Case 목록 조회",
          "업무 Case 를 최근 업데이트 순으로 조회합니다. 진행 상태 · 유형 · 검색어 · 기간으로 좁힐 수 있습니다.",
          {"filter": {"type": "string", "enum": ["all", "open", "done", "견적", "주문", "문의"], "default": "all",
                      "description": "all 전체 · open 진행 중 · done 완료 · 견적 · 주문 · 문의(유형)"},
           "q": {"type": "string", "description": "검색어(Case 번호 · 고객사 · 품목 · Sales Order · 담당자)"},
           "date_from": _FROM, "date_to": _TO}),
    _tool("get_case", "업무 Case 상세 조회",
          "업무 Case 1건의 요청 내용, 메일(시간순), ERP 처리 이력을 조회합니다.",
          {"case_id": _CASE_ID}, ["case_id"]),
    _tool("list_errors", "처리오류 조회",
          "ERP · 메일 API 호출이 실패한 처리오류를 조회합니다.",
          {"status": {"type": "string", "enum": ["open", "done", "all"], "default": "open",
                      "description": "open 미해결 · done 해결 · all 전체"},
           "date_from": _FROM, "date_to": _TO}),
    _tool("search", "통합 검색",
          "고객사 · 제목 · 품목 · Case 번호 · Sales Order 로 업무 Case(최대 5건)와 메일(최대 6건)을 찾습니다.",
          {"q": {"type": "string", "description": "검색어", "examples": ["누리뷰티"]}}, ["q"]),
    _tool("get_activity_log", "처리 로그 조회",
          "에이전트의 최근 처리 기록을 최신순으로 조회합니다.",
          {"limit": {"type": "integer", "description": "가져올 건수(1~40)", "default": 20}}),
    _tool("get_notifications", "알림 조회",
          "미해결 API 오류와 담당자 확인이 필요한 메일을 한 번에 조회합니다."),
    # 실행 15종 / fifteen actions
    _tool("classify_mail", "업무 유형 지정",
          "메일의 업무 유형을 정하거나 바꿉니다. 의도(intent)를 함께 바꿀 수 있습니다.",
          {"email_id": _EMAIL_ID,
           "classification": {"type": "string", "enum": list(mcmail.CLS),
                              "description": "quote 견적요청 · order 주문등록 · ship 출하일정 · stock 재고문의 · invoice 인보이스 발행요청 · etc 기타"},
           "intent": {"type": "string", "enum": list(mcmail.INTENTS), "description": "메일 의도(비우면 그대로)"}},
          ["email_id", "classification"], _SET),
    _tool("update_entity", "추출값 수정",
          "메일에서 추출한 값(고객사 · 품목 · 수량 · 납기 등)을 고칩니다. triage 를 켜면 확인 필요 항목을 해결합니다.",
          {"email_id": _EMAIL_ID,
           "field": {"type": "string", "enum": list(mcmail.FIELDS), "description": "고칠 항목"},
           "value": {"type": "string", "description": "새 값(수량도 글자로)", "examples": ["300"]},
           "triage": {"type": "boolean", "description": "확인 필요 항목 해결로 처리", "default": False}},
          ["email_id", "field", "value"], _SET),
    _tool("link_case", "Case 연결",
          "메일을 기존 업무 Case 에 연결합니다. 수량이 바뀐 메일은 견적 변경으로 처리합니다.",
          {"email_id": _EMAIL_ID, "case_id": _CASE_ID}, ["email_id", "case_id"], _SET),
    _tool("new_case", "새 Case 시작",
          "메일로 새 업무 Case 를 만듭니다.",
          {"email_id": _EMAIL_ID}, ["email_id"], _ACT),
    _tool("run_erp", "ERP 처리",
          "가상 ERP 에서 단가 · 재고 · 출하 · 주문 정보를 조회하고, 회신이 필요한 메일이면 답변 초안까지 만듭니다.",
          {"email_id": _EMAIL_ID, "lang": _LANG}, ["email_id"], _ACT),
    _tool("create_order", "ERP 주문등록",
          "주문 메일의 필수값을 확인한 뒤 가상 ERP 에 Sales Order 를 등록합니다.",
          {"email_id": _EMAIL_ID}, ["email_id"], _ACT),
    _tool("draft_reply", "답변 초안 작성",
          "메일에 보낼 답변 초안을 작성합니다. regen 을 켜면 다른 표현으로 다시 씁니다.",
          {"email_id": _EMAIL_ID, "regen": {"type": "boolean", "description": "다른 표현으로 다시 쓰기", "default": False},
           "lang": _LANG}, ["email_id"], _ACT),
    _tool("save_draft", "초안 저장",
          "고친 답변 초안을 저장합니다.",
          {"email_id": _EMAIL_ID, "draft": {"type": "string", "description": "저장할 초안 본문"}}, ["email_id", "draft"], _SET),
    _tool("send_reply", "답변 발송",
          "답변을 가상 메일 API 로 보내고 메일을 완료합니다. draft 를 비우면 저장된 초안을 보냅니다.",
          {"email_id": _EMAIL_ID, "draft": {"type": "string", "description": "보낼 본문(비우면 저장된 초안)"}}, ["email_id"],
          {**_ACT, "destructiveHint": True}),
    _tool("hold_mail", "보류 · 해제",
          "메일을 보류하거나 보류를 풉니다. on 을 비우면 지금 상태를 뒤집습니다.",
          {"email_id": _EMAIL_ID, "on": {"type": "boolean", "description": "true 보류 · false 해제"}}, ["email_id"], _SET),
    _tool("complete_mail", "완료 처리",
          "메일을 완료로 닫습니다.",
          {"email_id": _EMAIL_ID}, ["email_id"], _SET),
    _tool("archive_mail", "보관",
          "기타 유형 메일을 보관 처리합니다.",
          {"email_id": _EMAIL_ID}, ["email_id"], _SET),
    _tool("spam_mail", "스팸 처리",
          "기타 유형 메일을 스팸으로 처리합니다.",
          {"email_id": _EMAIL_ID}, ["email_id"], _SET),
    _tool("assign_owner", "담당자 지정",
          "메일이나 업무 Case 에 담당자를 지정합니다. Case 의 열린 메일과 미해결 오류에도 함께 반영됩니다.",
          {"kind": {"type": "string", "enum": ["mail", "case"], "description": "mail 메일 · case 업무 Case"},
           "id": {"type": "string", "description": "메일 ID 또는 Case ID", "examples": ["E-1001"]},
           "user": {"type": "string", "enum": [u.get("name") for u in mcmail.USERS], "description": "담당자"}},
          ["kind", "id", "user"], _SET),
    _tool("retry_error", "오류 재처리",
          "실패한 API 호출(ERP 조회 · 주문등록 · 메일 발송)을 다시 실행합니다.",
          {"error_id": {"type": "string", "description": "처리오류 ID", "examples": ["ERR-0008"]}, "lang": _LANG},
          ["error_id"], _ACT),
]


class ToolError(Exception):
    pass


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _opt(v) -> str | None:
    """빈 값은 None(스토어 기본값을 쓴다) / blanks become None so the store default applies"""
    s = _s(v)
    return s or None


def _flag(v) -> bool | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    s = _s(v).lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    raise ToolError("참/거짓 값이 올바르지 않습니다")


def _act(out: dict) -> tuple[str, dict]:
    """메일 처리 결과 → (요약 문장, 구조화 결과). 요약은 화면 알림(toast)과 같은 문장 / action payload → summary + data"""
    t = out.get("toast") or {}
    title, msg = _s(t.get("title")), _s(t.get("msg"))
    return (f"{title}. {msg}" if title and msg else title or msg or "처리했습니다."), out


def _count(d: dict) -> int:
    """건수(total) · 없으면 목록 길이(요약 문장은 빠진 키에 흔들리지 않는다) / the total, else the list length (summaries
    tolerate missing keys)"""
    v = d.get("total")
    return v if isinstance(v, int) else len(d.get("items") or [])


def _run(name: str, a: dict) -> tuple[str, dict]:
    """도구 실행 → (요약 문장, 구조화 결과). 입력·업무 규칙 오류는 ToolError / run a tool → (summary, structured result)"""
    if name == "get_work_status":
        # 기존 customer/case_id 계약을 유지하고 명시한 filters는 모든 조회 대상으로 전달한다.
        # Keep legacy customer/case_id arguments; forward explicit filters to every lookup target.
        target = _s(a.get("target"))
        if target == "customer" and not _s(a.get("customer")):
            raise ToolError("target 이 customer 이면 'customer' 인자가 필요합니다")
        if target == "case" and not _s(a.get("case_id")):
            raise ToolError("target 이 case 이면 'case_id' 인자가 필요합니다")
        largs = ({"customer": _s(a.get("customer"))} if target == "customer"
                 else {"case_id": _s(a.get("case_id"))} if target == "case" else None)
        if "filters" in a:
            largs = {**(largs or {}), "filters": a["filters"]}
        data, task, detail = mcmail.lookup(target, largs)
        return (f"{task} {detail}".strip() if detail else task), {
            "target": target, "task": task, "detail": detail, "answer": mcmail.fallback_answer(data, task), "data": data}
    if name == "get_dashboard":
        d = mcmail.dashboard(_opt(a.get("date")))
        k = d.get("kpi") or {}
        return (f"{_s(d.get('date'))} 수신 {k.get('recv', 0)}건 · 자동분류 {k.get('auto', 0)}건 · 확인 필요 {k.get('review', 0)}건 · "
                f"ERP 처리 {k.get('erp', 0)}건 · API 오류 {k.get('err', 0)}건입니다."), d
    if name == "list_mails":
        d = mcmail.list_emails(_opt(a.get("view")), _s(a.get("filter")) or "todo", _s(a.get("q")),
                               _opt(a.get("date_from")), _opt(a.get("date_to")))
        return f"메일 {_count(d)}건을 찾았습니다.", d
    if name == "get_mail":
        d = mcmail.get_email(_s(a.get("email_id")))
        e = d.get("email") or {}
        return f"{_s(e.get('emailId'))} · {_s(e.get('customer'))} · {_s(e.get('subject'))} · 상태 {_s(e.get('status'))}", d
    if name == "list_cases":
        d = mcmail.list_cases(_s(a.get("filter")) or "all", _s(a.get("q")), _opt(a.get("date_from")), _opt(a.get("date_to")))
        return f"업무 Case {_count(d)}건을 찾았습니다.", d
    if name == "get_case":
        d = mcmail.get_case(_s(a.get("case_id")).upper())
        c = d.get("case") or {}
        return (f"{_s(c.get('caseId'))} · {_s(c.get('customer'))} · 상태 {_s(c.get('status'))} · "
                f"메일 {len(d.get('mails') or [])}통"), d
    if name == "list_errors":
        d = mcmail.list_errors(_s(a.get("status")) or "open", _opt(a.get("date_from")), _opt(a.get("date_to")))
        return f"처리오류 {len(d.get('items') or [])}건을 찾았습니다(미해결 {(d.get('counts') or {}).get('open', 0)}건).", d
    if name == "search":
        d = mcmail.search(_s(a.get("q")))
        return (f"'{_s(d.get('q'))}' 검색 결과 · 업무 Case {len(d.get('cases') or [])}건 · "
                f"메일 {len(d.get('mails') or [])}건"), d
    if name == "get_activity_log":
        raw = a.get("limit")
        try:
            n = int(raw) if raw not in (None, "") else 20
        except (TypeError, ValueError):
            raise ToolError("limit 는 정수여야 합니다")
        items = mcmail.recent_log(max(1, min(n, 40)))
        return f"최근 처리 기록 {len(items)}건입니다.", {"items": items}
    if name == "get_notifications":
        d = mcmail.notifications()
        return (f"알림 {d.get('count', 0)}건 · 미해결 오류 {len(d.get('errors') or [])}건 · "
                f"확인 필요 메일 {len(d.get('triage') or [])}건"), d
    email_id = _s(a.get("email_id"))
    if name == "classify_mail":
        return _act(mcmail.classify(email_id, _s(a.get("classification")), _opt(a.get("intent"))))
    if name == "update_entity":
        return _act(mcmail.set_entity(email_id, _s(a.get("field")), a.get("value"), triage=bool(_flag(a.get("triage")))))
    if name == "link_case":
        return _act(mcmail.link_case(email_id, _s(a.get("case_id")).upper()))
    if name == "new_case":
        return _act(mcmail.new_case(email_id))
    if name == "run_erp":
        return _act(mcmail.run_erp(email_id, lang=_s(a.get("lang")) or "ko"))
    if name == "create_order":
        return _act(mcmail.create_order(email_id))
    if name == "draft_reply":
        return _act(mcmail.draft(email_id, regen=bool(_flag(a.get("regen"))), lang=_s(a.get("lang")) or "ko"))
    if name == "save_draft":
        return _act(mcmail.save_draft(email_id, a.get("draft") if isinstance(a.get("draft"), str) else None))
    if name == "send_reply":
        text = a.get("draft")
        return _act(mcmail.send(email_id, text=text if isinstance(text, str) and text.strip() else None))
    if name == "hold_mail":
        return _act(mcmail.hold(email_id, _flag(a.get("on"))))
    if name == "complete_mail":
        return _act(mcmail.complete(email_id))
    if name == "archive_mail":
        return _act(mcmail.archive(email_id))
    if name == "spam_mail":
        return _act(mcmail.spam(email_id))
    if name == "assign_owner":
        return _act(mcmail.assign(_s(a.get("kind")), _s(a.get("id")), _s(a.get("user"))))
    if name == "retry_error":
        return _act(mcmail.retry(_s(a.get("error_id")), lang=_s(a.get("lang")) or "ko"))
    raise ToolError(f"알 수 없는 도구: {name}")


def _check_args(tool: dict, args: dict) -> None:
    """필수 인자·enum 검사(형식 오류는 isError 결과) / required + enum checks (violations become isError results)"""
    if not isinstance(args, dict):
        raise ToolError("arguments 는 객체여야 합니다")
    schema = tool["inputSchema"]
    for req in schema.get("required") or []:
        v = args.get(req)
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ToolError(f"필수 인자 '{req}' 가 없습니다")
    for k, prop in (schema.get("properties") or {}).items():
        if k in args and args[k] not in (None, "") and isinstance(prop.get("enum"), list) and args[k] not in prop["enum"]:
            raise ToolError(f"'{k}' 값은 {', '.join(map(str, prop['enum']))} 중 하나여야 합니다")


def _err(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _tool_error(mid, status, message: str) -> dict:
    """도구 오류 결과(isError) · 문구는 content 에, 상태(404 · 409 · 422)와 문구는 structuredContent.error 에 싣는다(2026-09-30,
    채팅 연결이 스토어 예외로 되돌린다). An isError tool result: the message in content, the status (404, 409, 422) and the
    message in structuredContent.error (2026-09-30; the chat link raises the store's exception again)."""
    code = status if isinstance(status, int) and not isinstance(status, bool) else 422
    return {"jsonrpc": "2.0", "id": mid,
            "result": {"content": [{"type": "text", "text": message}],
                       "structuredContent": {"error": {"status": code, "message": message}}, "isError": True}}


def handle(msg, authorization: str | None) -> tuple[int, dict | None]:
    """JSON-RPC 메시지 1건 → (HTTP 상태, 응답 본문 또는 None). 인증 실패는 401 + -32001."""
    # One JSON-RPC message → (HTTP status, body or None). Auth failures → 401 + -32001.
    if authorization != f"Bearer {DEMO_KEY}":
        return 401, _err(msg.get("id") if isinstance(msg, dict) else None, -32001,
                         "유효한 인증 키가 필요합니다 (Authorization: Bearer ...)")   # 키 값은 되풀이하지 않는다(REST 목업과 같다) / never echo the key
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return 400, _err(msg.get("id") if isinstance(msg, dict) else None, -32600, "잘못된 JSON-RPC 요청입니다")
    method, mid, params = msg["method"], msg.get("id"), msg.get("params") if isinstance(msg.get("params"), dict) else {}
    if mid is None:   # 알림 / notification
        return 202, None
    if method == "initialize":
        want = str(params.get("protocolVersion") or PROTOCOL)
        return 200, {"jsonrpc": "2.0", "id": mid,
                     "result": {"protocolVersion": want if want in SUPPORTED else PROTOCOL,
                                "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO,
                                "instructions": "M코스메틱 영업 메일을 조회하고 처리하는 도구입니다. 데이터는 데모용 가상 값입니다."}}
    if method == "ping":
        return 200, {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return 200, {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = str(params.get("name") or "")
        tool = next((t for t in TOOLS if t["name"] == name), None)
        if tool is None:
            return 200, _err(mid, -32602, f"알 수 없는 도구입니다: {name}")
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        try:
            _check_args(tool, args)
            summary, data = _run(name, args)
        except ToolError as e:   # 인자 형식 오류 = 422 / argument errors are 422
            return 200, _tool_error(mid, 422, str(e))
        except mcmail.MailValidationError as e:   # 스토어 규칙(422) · 없는 id(404) · 충돌(409) / store rules, unknown ids, conflicts
            return 200, _tool_error(mid, e.status, str(e))
        return 200, {"jsonrpc": "2.0", "id": mid,
                     "result": {"content": [{"type": "text", "text": summary}], "structuredContent": data, "isError": False}}
    return 200, _err(mid, -32601, f"지원하지 않는 메서드입니다: {method}")


def registry_config() -> dict:
    """업무 자동화 탭이 보여 줄 연결 설정 · 도구는 tools/list 와 같은 목록을 우리 명세로 옮기고 종류는 읽기 전용 힌트로 정한다.
    The connection the automation tab shows; tools are the tools/list specs normalized, with the kind from the read-only hint."""
    tools = []
    for raw in TOOLS:
        t = mcp_client.normalize_tool(raw)
        if t is not None:
            tools.append({**t, "kind": t["kind_default"], "enabled": True, "description_override": ""})
    return {"url": URL, "auth": {"type": "bearer", "key": SECRET_MASK, "name": "Authorization"}, "timeout": TIMEOUT,
            "tools": tools, "server_info": {**SERVER_INFO, "protocol": PROTOCOL}}


@router.post("/mcp")
async def mcp_endpoint(request: Request, authorization: str | None = Header(None)) -> Response:
    try:
        body = json.loads((await request.body()) or b"null")
    except ValueError:
        return JSONResponse(status_code=400, content=_err(None, -32700, "JSON 파싱 오류"))
    # 스토어는 SQLite 를 쓰므로 스레드 풀에서 처리한다 / the store uses SQLite, so handle in the thread pool
    if isinstance(body, list):   # 배치 / batch
        results = [await run_in_threadpool(handle, m, authorization) for m in body]
        out = [b for _, b in results if b is not None]
        status = max((s for s, _ in results), default=200)
        return JSONResponse(status_code=200 if status < 400 else status, content=out) if out else Response(status_code=202)
    status, out = await run_in_threadpool(handle, body, authorization)
    if out is None:
        return Response(status_code=status)
    return JSONResponse(status_code=status, content=out)


@router.get("/mcp")
def mcp_get() -> Response:
    """GET 스트림(서버→클라이언트 알림)은 제공하지 않는다 / no server-initiated stream"""
    return Response(status_code=405)


@router.delete("/mcp")
def mcp_delete() -> dict:
    return {"ok": True}
