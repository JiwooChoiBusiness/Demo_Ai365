"""데모 MCP 서버(2026-09-15) — 서버 안에 두는 "외부" MCP 서버(/mock/mcp). 가상 ERP·EMS(app/mock_apis.py)의 조회·실행 6종을
MCP 도구로 노출해 관리 센터 "API · MCP 연결"의 MCP 등록 → 도구 가져오기 → 워크플로우 외부 도구 작업까지 실 서버 없이 시연한다.

  - 전송: Streamable HTTP(JSON-RPC POST, 응답은 JSON). 인증: Authorization: Bearer demo-mcp-key-2026.
  - 메서드: initialize · notifications/initialized(202) · ping · tools/list · tools/call. 그 밖은 -32601.
  - 도구 명세에 annotations(readOnlyHint 등)를 넣어 조회/실행 기본 종류가 자동으로 잡히는 것을 보여 준다.
  - handle(msg, authorization) 은 순수 함수 — 테스트가 HTTP 없이 그대로 부른다.

Demo MCP server (2026-09-15) — an "external" MCP server hosted inside the app (/mock/mcp). Exposes six read/action
tools over the fictional ERP/EMS (app/mock_apis.py) so the Admin Center MCP registration → tool discovery → workflow
external-tool task can be demonstrated without a real server.
  - Transport: Streamable HTTP (JSON-RPC POST, JSON responses). Auth: Authorization: Bearer demo-mcp-key-2026.
  - Methods: initialize · notifications/initialized (202) · ping · tools/list · tools/call; anything else → -32601.
  - Tool specs carry annotations (readOnlyHint etc.) so the read/action default kind is derived automatically.
  - handle(msg, authorization) is a pure function — tests call it directly, no HTTP needed.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, Response

from app import kst, mock_apis

router = APIRouter(prefix="/mock", tags=["mock-mcp"])

DEMO_MCP_KEY = "demo-mcp-key-2026"
PROTOCOL = "2025-06-18"
SUPPORTED = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "Ai365 데모 MCP 서버 (ERP·EMS)", "version": "1.0.0"}

TOOLS: list[dict] = [
    {"name": "erp_sales_summary", "title": "ERP 매출 요약 조회",
     "description": "지점별 매출·목표·달성률과 주력 상품 매출을 조회합니다.",
     "inputSchema": {"type": "object",
                     "properties": {"period": {"type": "string", "description": "조회 월(YYYY-MM)", "examples": ["2026-08"]},
                                    "branch": {"type": "string", "description": "지점 이름 또는 all(전체)",
                                               "enum": ["all", *mock_apis.BRANCHES], "default": "all"}},
                     "required": ["period"]},
     # 출력 명세(2026-09-23): 화면의 [명세 보기]용 — 결과 모양을 알려 준다 / output schema (2026-09-23) for the screen's [View schema]
     "outputSchema": {"type": "object",
                      "properties": {"period": {"type": "string"},
                                     "branches": {"type": "array", "items": {"type": "object", "properties": {
                                         "branch": {"type": "string"}, "sales": {"type": "number"}, "target": {"type": "number"},
                                         "achievement_pct": {"type": "number"}}}},
                                     "top_products": {"type": "array", "items": {"type": "object", "properties": {
                                         "product": {"type": "string"}, "sales": {"type": "number"}}}}}},
     "annotations": {"title": "ERP 매출 요약 조회", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}},
    {"name": "erp_inventory", "title": "ERP 재고 조회",
     "description": "SKU별 수량·가용 재고·창고별 보유량을 조회합니다. SKU를 비우면 전체 요약입니다.",
     "inputSchema": {"type": "object",
                     "properties": {"sku": {"type": "string", "description": "품목 코드(비우면 전체 요약)", "examples": ["SKU-1001"]}},
                     "required": []},
     "outputSchema": {"type": "object",
                      "properties": {"sku": {"type": "string"}, "qty": {"type": "integer"}, "available": {"type": "integer"},
                                     "warehouses": {"type": "array", "items": {"type": "object", "properties": {
                                         "name": {"type": "string"}, "qty": {"type": "integer"}}}}}},
     "annotations": {"title": "ERP 재고 조회", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}},
    {"name": "erp_order_approve", "title": "ERP 주문 승인",
     "description": "주문 번호로 주문을 승인 처리합니다(상태를 바꾸는 실행 도구).",
     "inputSchema": {"type": "object",
                     "properties": {"order_id": {"type": "string", "description": "주문 번호(O-+4~6자리)", "examples": ["O-100231"]},
                                    "approver": {"type": "string", "description": "승인자 이름", "default": "AI 어시스턴트"}},
                     "required": ["order_id"]},
     "annotations": {"title": "ERP 주문 승인", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}},
    {"name": "ems_energy_usage", "title": "EMS 에너지 사용량 조회",
     "description": "사업장별 전력 사용량·요금·피크와 최근 7일 추이를 조회합니다.",
     "inputSchema": {"type": "object",
                     "properties": {"site": {"type": "string", "description": "사업장 코드", "default": "HQ", "examples": ["HQ"]},
                                    "period": {"type": "string", "description": "조회 월(YYYY-MM)", "examples": ["2026-08"]}},
                     "required": ["period"]},
     "outputSchema": {"type": "object",
                      "properties": {"site": {"type": "string"}, "period": {"type": "string"}, "kwh": {"type": "number"},
                                     "cost": {"type": "number"}, "peak_kw": {"type": "number"},
                                     "daily": {"type": "array", "items": {"type": "object", "properties": {
                                         "date": {"type": "string"}, "kwh": {"type": "number"}}}}}},
     "annotations": {"title": "EMS 에너지 사용량 조회", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}},
    {"name": "ems_alarms", "title": "EMS 알람 조회",
     "description": "최근 N시간의 설비 알람을 심각도별로 조회합니다.",
     "inputSchema": {"type": "object",
                     "properties": {"severity": {"type": "string", "description": "심각도", "enum": ["all", *mock_apis.SEVERITIES], "default": "all"},
                                    "hours": {"type": "integer", "description": "조회 범위(시간, 1~720)", "default": 24}},
                     "required": []},
     "annotations": {"title": "EMS 알람 조회", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}},
    {"name": "ems_equipment_control", "title": "EMS 설비 제어",
     "description": "설비를 가동·정지·재시작합니다(상태를 바꾸는 실행 도구).",
     "inputSchema": {"type": "object",
                     "properties": {"equipment_id": {"type": "string", "description": "설비 번호", "examples": ["EQ-101"]},
                                    "command": {"type": "string", "description": "제어 명령", "enum": list(mock_apis.EQUIP_CONTROL_COMMANDS)}},
                     "required": ["equipment_id", "command"]},
     "annotations": {"title": "EMS 설비 제어", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False}},
]


class ToolError(Exception):
    pass


def _month(period) -> str:
    p = str(period or "").strip()
    return p or kst.month()


def _run(name: str, args: dict) -> tuple[str, dict]:
    """도구 실행 → (요약 문장, 구조화 결과). 잘못된 입력은 ToolError."""
    # Run a tool → (summary sentence, structured result). Bad input raises ToolError.
    if name == "erp_sales_summary":
        period, branch = _month(args.get("period")), str(args.get("branch") or "all")
        if branch != "all" and branch not in mock_apis.BRANCHES:
            raise ToolError(f"branch 는 all 또는 {', '.join(mock_apis.BRANCHES)} 중 하나여야 합니다")
        d = mock_apis.erp_sales_summary(period=period, branch=branch, _auth=None)
        return (f"{period} {('전체' if branch == 'all' else branch)} 매출 {d['total_sales']:,}원, 목표 {d['target']:,}원, "
                f"달성률 {d['achievement_pct']}%, 전월 대비 {d['growth_pct']}%."), d
    if name == "erp_inventory":
        sku = str(args.get("sku") or "").strip()
        if not sku:
            d = mock_apis.erp_inventory_all(_auth=None)
            return (f"전 품목 {d['item_count']}건 재고 요약: 보유 {d['total_on_hand']:,}, 가용 {d['total_available']:,}, "
                    f"재주문점 미달 {len(d['below_reorder_point'])}건."), d
        d = mock_apis._inventory_of(sku)
        return f"{sku} {d['name']}: 보유 {d['on_hand']:,}, 예약 {d['reserved']:,}, 가용 {d['available']:,}.", d
    if name == "erp_order_approve":
        order_id = str(args.get("order_id") or "").strip()
        try:
            d = mock_apis.erp_order_approve(order_id, body={"approver": args.get("approver") or "AI 어시스턴트"}, _auth=None)
        except mock_apis.MockAPIError as e:
            raise ToolError(e.message)
        return d["message"], d
    if name == "ems_energy_usage":
        site, period = str(args.get("site") or "HQ"), _month(args.get("period"))
        d = mock_apis._energy_usage(site, period)
        return (f"{period} {site} 전력 {d['kwh_total']:,} kWh, 요금 {d['cost_krw']:,}원, 피크 {d['peak_kw']} kW"
                f"({d['peak_at']}), 전월 대비 {d['vs_last_month_pct']}%."), d
    if name == "ems_alarms":
        sev = str(args.get("severity") or "all")
        try:
            hours = int(args.get("hours") if args.get("hours") not in (None, "") else 24)
        except (TypeError, ValueError):
            raise ToolError("hours 는 정수여야 합니다")
        if sev != "all" and sev not in mock_apis.SEVERITIES:
            raise ToolError(f"severity 는 all 또는 {', '.join(mock_apis.SEVERITIES)} 중 하나여야 합니다")
        d = mock_apis.ems_alarms(severity=sev, hours=hours, _auth=None)
        return f"최근 {d['window_hours']}시간 알람 {d['count']}건.", d
    if name == "ems_equipment_control":
        eid, cmd = str(args.get("equipment_id") or "").strip(), str(args.get("command") or "").strip()
        if not eid:
            raise ToolError("equipment_id 가 비어 있습니다")
        try:
            d = mock_apis.ems_equipment_control(eid, body={"command": cmd}, _auth=None)
        except mock_apis.MockAPIError as e:
            raise ToolError(e.message)
        return d["message"], d
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


def handle(msg, authorization: str | None) -> tuple[int, dict | None]:
    """JSON-RPC 메시지 1건 → (HTTP 상태, 응답 본문 또는 None). 인증 실패는 401 + -32001."""
    # One JSON-RPC message → (HTTP status, body or None). Auth failures → 401 + -32001.
    if authorization != f"Bearer {DEMO_MCP_KEY}":
        return 401, _err(msg.get("id") if isinstance(msg, dict) else None, -32001,
                         "유효한 인증 키가 필요합니다 (Authorization: Bearer demo-mcp-key-2026)")
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
                                "instructions": "Ai365 데모용 가상 ERP·EMS 도구입니다. 데이터는 입력값으로 결정되는 가상 값입니다."}}
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
        except ToolError as e:
            return 200, {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": str(e)}], "isError": True}}
        return 200, {"jsonrpc": "2.0", "id": mid,
                     "result": {"content": [{"type": "text", "text": summary}], "structuredContent": data, "isError": False}}
    return 200, _err(mid, -32601, f"지원하지 않는 메서드입니다: {method}")


@router.post("/mcp")
async def mcp_endpoint(request: Request, authorization: str | None = Header(None)) -> Response:
    try:
        body = json.loads((await request.body()) or b"null")
    except ValueError:
        return JSONResponse(status_code=400, content=_err(None, -32700, "JSON 파싱 오류"))
    if isinstance(body, list):   # 배치 / batch
        results = [handle(m, authorization) for m in body]
        out = [b for _, b in results if b is not None]
        status = max((s for s, _ in results), default=200)
        return JSONResponse(status_code=200 if status < 400 else status, content=out) if out else Response(status_code=202)
    status, out = handle(body, authorization)
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
