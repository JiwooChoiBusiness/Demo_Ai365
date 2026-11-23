"""외부 API 목업 — 가상 ERP(전사자원관리)·EMS(설비·에너지 관리 시스템) 데모 서버.
워크플로우 "API 요청" 작업이 실제 외부 호출 없이 호출하는 대상이다. 모든 응답은 요청 파라미터를
해시한 결정적(deterministic) 의사난수 데이터이며, DB·외부 호출 없이 이 프로세스 안에서만 계산된다.

인증: ERP(/mock/erp/v1/...)는 헤더 Authorization: Bearer demo-erp-key-2026, EMS(/mock/ems/v1/...)는
헤더 X-API-Key 또는 쿼리 api_key 로 demo-ems-key-2026 이 필요하다. /mock/catalog(인증 불필요)는
워크플로우 에디터가 그대로 불러올 수 있는 샘플(sample)·테스트 변수(test_vars)를 포함한 13개
엔드포인트 메타데이터를 반환한다(조회 9개 + 실행 4개).
"""
# Mock external APIs — a demo server for a fictional ERP (enterprise resource planning) and EMS
# (equipment/energy management system), called by a workflow's "API request" task instead of a real
# external call. Every response is deterministic pseudo-data derived by hashing the request
# parameters, computed entirely within this process — no database, no external calls.
#
# Auth: ERP (/mock/erp/v1/...) needs header Authorization: Bearer demo-erp-key-2026; EMS
# (/mock/ems/v1/...) needs demo-ems-key-2026 via header X-API-Key or query api_key. /mock/catalog
# (no auth) returns metadata for all 13 endpoints (9 read + 4 action), including an "API request"
# task sample and test_vars ready to load straight into the workflow editor.

import hashlib
import json
import random
import re
from datetime import datetime, timedelta
from typing import Callable

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app import kst

# 데모용 고정 키 — 실제 비밀값이 아니라 목업 인증을 설명하기 위한 표시값이다.
# Fixed demo keys — not real secrets, just display values that document the mock auth scheme.
DEMO_KEYS = {"erp": "demo-erp-key-2026", "ems": "demo-ems-key-2026"}


class MockAPIError(Exception):
    """이 라우터의 요청 처리 실패(인증·검증·조회) 표시용 내부 예외 — MockAPIRoute가 {"error": {...}} 응답으로 변환한다.
    Internal exception marking a request failure (auth, validation, lookup) — MockAPIRoute turns it into a
    {"error": {...}} response."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message


class MockAuthError(MockAPIError):
    """인증 실패 전용 별칭 — 기존 require_erp_key/require_ems_key 호출부와 호환된다.
    Auth-specific alias — kept for compatibility with the existing require_erp_key/require_ems_key call sites."""


class MockAPIRoute(APIRoute):
    """MockAPIError를 이 라우터 전용 에러 JSON으로 바꾼다 — main.py의 전역 핸들러는 건드리지 않는다.
    Turns MockAPIError into this router's own error JSON — main.py's global handlers stay untouched."""

    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request):
            try:
                return await original_route_handler(request)
            except MockAPIError as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"error": {"code": exc.code, "message": exc.message}},
                )

        return custom_route_handler


router = APIRouter(prefix="/mock", tags=["mock-apis"], route_class=MockAPIRoute)


def require_erp_key(authorization: str | None = Header(None)) -> None:
    """ERP 인증: Authorization: Bearer demo-erp-key-2026 헤더가 정확히 있어야 한다.
    ERP auth: the Authorization: Bearer demo-erp-key-2026 header must match exactly."""
    if authorization != f"Bearer {DEMO_KEYS['erp']}":
        raise MockAuthError(401, "unauthorized", "유효한 API 키가 필요합니다 (Authorization: Bearer ...)")


def require_ems_key(x_api_key: str | None = Header(None), api_key: str | None = Query(None)) -> None:
    """EMS 인증: 헤더 X-API-Key 또는 쿼리 api_key 중 하나로 demo-ems-key-2026 을 전달해야 한다.
    EMS auth: demo-ems-key-2026 must be supplied via either the X-API-Key header or the api_key query param."""
    if (x_api_key or api_key) != DEMO_KEYS["ems"]:
        raise MockAuthError(401, "unauthorized",
                             "유효한 API 키가 필요합니다 (X-API-Key 헤더 또는 api_key 쿼리 파라미터)")


def _rng(*parts: object) -> random.Random:
    """파라미터 문자열을 sha256으로 해시해 결정적 난수 생성기를 만든다 — 입력이 같으면 출력도 같다.
    Hash the parameters with sha256 into a deterministic PRNG — identical input always yields identical output."""
    raw = "|".join("" if p is None else str(p) for p in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _parse_period(period: str) -> tuple[int, int]:
    """"YYYY-MM" 문자열에서 연/월을 뽑는다. 형식이 틀리면 이번 달로 대체한다.
    Extract year/month from a "YYYY-MM" string; fall back to the current month on a bad format."""
    try:
        y, m = period.split("-")[:2]
        y, m = int(y), int(m)
        if not 1 <= m <= 12:
            raise ValueError("month out of range")
        return y, m
    except Exception:
        now = kst.now()
        return now.year, now.month


def _parse_date(s: str | None) -> datetime | None:
    """"YYYY-MM-DD" 문자열을 파싱한다. 없거나 형식이 틀리면 None.
    Parse a "YYYY-MM-DD" string; return None when missing or malformed."""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None


# ══════════════════════════════════════════════════════════════════════════
# ERP — 가상 전사자원관리 시스템 / a fictional enterprise resource planning system
# ══════════════════════════════════════════════════════════════════════════

BRANCHES = ("서울", "부산", "대구", "광주", "대전")
DEPTS = ("경영지원", "영업", "개발", "마케팅", "재무", "고객지원")
PRODUCT_NAMES = (
    "스마트 컨트롤러 X1", "산업용 센서 S200", "고효율 인버터 V3",
    "무선 게이트웨이 G7", "정밀 액추에이터 A5", "IoT 허브 H1",
)
CUSTOMERS = (
    ("C-1001", "한빛전자"), ("C-1002", "미래물산"), ("C-1003", "대성중공업"),
    ("C-1004", "청림바이오"), ("C-1005", "서진테크"), ("C-1006", "동아정밀"),
    ("C-1007", "한울에너지"), ("C-1008", "가온소재"), ("C-1009", "은하물류"),
    ("C-1010", "태평양식품"),
)
ORDER_STATUSES = ("open", "shipped", "closed")
WAREHOUSES = (("WH-1", "서울 물류센터"), ("WH-2", "부산 물류센터"), ("WH-3", "대전 물류센터"))
# 주문 승인 엔드포인트가 order_id 형식을 검증할 때 쓰는 패턴("O-" + 4~6자리 숫자).
# Pattern the order-approve endpoint uses to validate order_id shape ("O-" + 4-6 digits).
ORDER_ID_RE = re.compile(r"^O-\d{4,6}$")


def _branch_row(period: str, name: str) -> dict:
    rng = _rng("erp.branch", period, name)
    sales = rng.randint(700, 3800) * 1_000_000
    target = round(sales * rng.uniform(0.82, 1.18) / 1_000_000) * 1_000_000
    achievement_pct = round(sales / target * 100, 1) if target else 0.0
    return {"branch": name, "sales": sales, "target": target, "achievement_pct": achievement_pct}


def _top_products(period: str, branch: str) -> list[dict]:
    rng = _rng("erp.top_products", period, branch)
    picks = rng.sample(PRODUCT_NAMES, 3)
    items = [
        {"sku": f"SKU-{1000 + PRODUCT_NAMES.index(name)}", "name": name, "sales": rng.randint(50, 500) * 1_000_000}
        for name in picks
    ]
    items.sort(key=lambda p: -p["sales"])
    return items


@router.get("/erp/v1/sales/summary")
def erp_sales_summary(
    period: str | None = Query(None),
    branch: str = Query("all"),
    _auth: None = Depends(require_erp_key),
) -> dict:
    period = period or kst.now().strftime("%Y-%m")
    names = BRANCHES if branch == "all" else (branch,)
    by_branch = [_branch_row(period, name) for name in names]
    total_sales = sum(r["sales"] for r in by_branch)
    target = sum(r["target"] for r in by_branch)
    achievement_pct = round(total_sales / target * 100, 1) if target else 0.0
    growth_pct = round(_rng("erp.growth", period, branch).uniform(-8.0, 22.0), 1)
    return {
        "system": "ERP", "period": period, "branch": branch, "currency": "KRW",
        "total_sales": total_sales, "target": target,
        "achievement_pct": achievement_pct, "growth_pct": growth_pct,
        "by_branch": by_branch, "top_products": _top_products(period, branch),
    }


@router.post("/erp/v1/orders/search")
def erp_orders_search(body: dict | None = Body(None), _auth: None = Depends(require_erp_key)) -> dict:
    body = body or {}
    customer_id = body.get("customer_id")
    status = body.get("status")
    date_from, date_to = body.get("from"), body.get("to")
    try:
        limit = max(1, min(50, int(body.get("limit") or 10)))
    except (TypeError, ValueError):
        limit = 10

    rng = _rng("erp.orders", customer_id, status, date_from, date_to, limit)
    pool = [c for c in CUSTOMERS if not customer_id or customer_id in c]
    if not pool:
        # 미상의 customer_id 라도 결정적으로 거래처 한 곳을 만들어 낸다
        # Even an unrecognized customer_id still deterministically gets one counterparty
        pool = [(customer_id, f"{customer_id} 거래처")]

    window_end = _parse_date(date_to) or kst.now()
    window_start = _parse_date(date_from) or (window_end - timedelta(days=60))
    span_days = max(1, (window_end - window_start).days)

    orders = []
    for i in range(limit):
        cust = pool[i % len(pool)]
        st = status if status in ORDER_STATUSES else rng.choice(ORDER_STATUSES)
        ordered_at = window_start + timedelta(
            days=rng.randint(0, span_days), hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
        due_at = ordered_at + timedelta(days=rng.randint(7, 30))
        orders.append({
            "order_id": f"SO-{rng.randint(100000, 999999)}",
            "customer_id": cust[0], "customer": cust[1],
            "amount": rng.randint(5, 800) * 100_000, "status": st,
            "ordered_at": ordered_at.strftime("%Y-%m-%dT%H:%M:%S"),
            "due_at": due_at.strftime("%Y-%m-%d"),
        })
    filters = {"customer_id": customer_id, "status": status, "from": date_from, "to": date_to, "limit": limit}
    return {"system": "ERP", "count": len(orders), "filters": filters, "orders": orders}


def _unit_price(sku: str) -> int:
    """SKU별 결정적 단가(KRW) — 주문 생성 금액 계산에 쓴다.
    Deterministic per-SKU unit price (KRW) — used to compute order amounts."""
    return _rng("erp.unit_price", sku).randint(5, 300) * 1000


@router.post("/erp/v1/orders")
def erp_order_create(body: dict | None = Body(None), _auth: None = Depends(require_erp_key)) -> dict:
    """주문 생성 — customer_id/sku/qty로 신규 주문을 만든다. qty가 없거나 0 이하이면 422.
    Create an order from customer_id/sku/qty. 422 when qty is missing or not positive."""
    body = body or {}
    customer_id = body.get("customer_id") or "C-0000"
    sku = body.get("sku") or "SKU-1000"
    note = body.get("note")
    try:
        qty = int(body.get("qty"))
    except (TypeError, ValueError):
        qty = 0
    if qty <= 0:
        raise MockAPIError(422, "invalid_request", "qty는 1 이상의 숫자여야 합니다")

    order_id = f"O-{_rng('erp.order.create', customer_id, sku, qty, note).randint(100000, 999999)}"
    return {
        "system": "ERP", "action": "order.create", "ok": True,
        "order_id": order_id, "customer_id": customer_id, "sku": sku, "qty": qty,
        "amount": qty * _unit_price(sku), "status": "open",
        "created_at": kst.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "message": "주문이 생성되었습니다.",
    }


@router.post("/erp/v1/orders/{order_id}/approve")
def erp_order_approve(
    order_id: str, body: dict | None = Body(None), _auth: None = Depends(require_erp_key),
) -> dict:
    """주문 승인 — order_id가 "O-"+4~6자리 숫자 형식이 아니면 404.
    Approve an order — 404 when order_id isn't shaped like "O-" plus 4-6 digits."""
    if not ORDER_ID_RE.match(order_id):
        raise MockAPIError(404, "not_found", "주문을 찾을 수 없습니다")
    body = body or {}
    approver = body.get("approver") or "AI 어시스턴트"
    return {
        "system": "ERP", "action": "order.approve", "ok": True,
        "order_id": order_id, "previous_status": "open", "status": "approved",
        "approver": approver, "approved_at": kst.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "message": f"주문 {order_id}이(가) 승인되었습니다.",
    }


def _inventory_of(sku: str) -> dict:
    """SKU 1개의 결정적 재고 레코드 — 단건 조회와 전체 요약이 같은 숫자를 보게 한다."""
    # Deterministic inventory record for one SKU — the single lookup and the summary share the same numbers.
    rng = _rng("erp.inventory", sku)
    warehouses = []
    on_hand = 0
    for code, name in WAREHOUSES:
        qty = rng.randint(10, 900)
        on_hand += qty
        warehouses.append({"code": code, "name": name, "qty": qty})
    reserved = int(on_hand * rng.uniform(0.05, 0.35))
    name_idx = int(hashlib.sha256(sku.encode("utf-8")).hexdigest(), 16) % len(PRODUCT_NAMES)
    return {
        "system": "ERP", "sku": sku, "name": PRODUCT_NAMES[name_idx],
        "on_hand": on_hand, "reserved": reserved, "available": on_hand - reserved,
        "reorder_point": max(20, int(on_hand * rng.uniform(0.1, 0.25))),
        "unit_cost": rng.randint(3, 250) * 1000, "warehouses": warehouses,
    }


@router.get("/erp/v1/inventory")
@router.get("/erp/v1/inventory/")
def erp_inventory_all(_auth: None = Depends(require_erp_key)) -> dict:
    """SKU 없이 부르면 전 품목 재고 요약 — 채팅에서 "재고 조회해줘"처럼 품목을 안 밝힌 요청도 답이 나오게 한다
    (종전엔 빈 {{input.sku}} 가 /inventory/ 로 치환돼 404)."""
    # Called without a SKU → summary of every item, so "check inventory" without naming an item still answers
    # (an empty {{input.sku}} used to resolve to /inventory/ and 404).
    items = [_inventory_of(f"SKU-{1000 + i}") for i in range(len(PRODUCT_NAMES))]
    low = [it["sku"] for it in items if it["available"] < it["reorder_point"]]
    return {
        "system": "ERP", "as_of": kst.now().strftime("%Y-%m-%d"), "item_count": len(items),
        "total_on_hand": sum(it["on_hand"] for it in items),
        "total_available": sum(it["available"] for it in items),
        "below_reorder_point": low,
        "items": [{k: it[k] for k in ("sku", "name", "on_hand", "reserved", "available", "reorder_point", "unit_cost")}
                  for it in items],
    }


@router.get("/erp/v1/inventory/{sku}")
def erp_inventory(sku: str, _auth: None = Depends(require_erp_key)) -> dict:
    return _inventory_of(sku)


@router.get("/erp/v1/hr/headcount")
def erp_hr_headcount(dept: str = Query("all"), _auth: None = Depends(require_erp_key)) -> dict:
    def hc(name: str) -> int:
        return _rng("erp.dept.headcount", name).randint(8, 60)

    if dept == "all":
        by_dept = [{"dept": d, "headcount": hc(d)} for d in DEPTS]
        headcount = sum(r["headcount"] for r in by_dept)
    else:
        headcount = hc(dept)
        by_dept = [{"dept": dept, "headcount": headcount}]

    rng = _rng("erp.hr", dept)
    return {
        "system": "ERP", "dept": dept, "headcount": headcount,
        "hires_mtd": rng.randint(0, 6), "leavers_mtd": rng.randint(0, 4),
        "open_positions": rng.randint(0, 10), "by_dept": by_dept,
    }


@router.post("/erp/v1/analyze")
def erp_analyze(body: dict | None = Body(None), _auth: None = Depends(require_erp_key)) -> dict:
    body = body or {}
    question = body.get("question") or "전반적인 거래 현황"
    customer_id = body.get("customer_id") or "C-0000"
    department = body.get("department") or "영업"
    options = body.get("options") or {}
    language = str(options.get("language") or "ko").lower()

    rng = _rng("erp.analyze", question, customer_id, department, language)
    request_id = "req_" + hashlib.sha256(f"{question}|{customer_id}|{department}".encode("utf-8")).hexdigest()[:8]
    name = next((c[1] for c in CUSTOMERS if c[0] == customer_id), f"{customer_id} 거래처")
    grade = rng.choice(("A", "B", "C"))
    open_orders = rng.randint(0, 20)
    overdue_invoices = rng.randint(0, 5)
    risk_score = rng.randint(5, 95)
    risk_level = "낮음" if risk_score < 34 else ("보통" if risk_score < 67 else "높음")

    if language == "en":
        level_en = {"낮음": "Low", "보통": "Medium", "높음": "High"}[risk_level]
        summary = (
            f"Regarding the {department} team's question (\"{question}\"), {name} is grade {grade} "
            f"with {open_orders} open orders and {overdue_invoices} overdue invoices. "
            f"Overall relationship risk is assessed as {level_en}."
        )
        recommended_actions = [
            f"Have the {department} team review {name}'s overdue invoices this week.",
            "Schedule a follow-up call to confirm the next order timeline.",
            "Re-evaluate the credit limit if overdue invoices persist.",
        ]
    else:
        summary = (
            f"{department} 부서의 질문(\"{question}\")과 관련해 {name}은(는) 등급 {grade}이며 "
            f"미결 주문 {open_orders}건, 연체 청구서 {overdue_invoices}건을 보유하고 있습니다. "
            f"전반적인 거래 위험도는 {risk_level} 수준으로 평가됩니다."
        )
        recommended_actions = [
            f"{department} 팀이 이번 주 내 {name}의 연체 청구서를 점검합니다.",
            "다음 주문 일정 확인을 위한 후속 통화를 예약합니다.",
            "연체가 지속될 경우 여신 한도를 재검토합니다.",
        ]

    return {
        "system": "ERP", "request_id": request_id,
        "customer": {
            "customer_id": customer_id, "name": name, "grade": grade,
            "annual_revenue": rng.randint(3, 120) * 100_000_000,
            "open_orders": open_orders, "overdue_invoices": overdue_invoices,
        },
        "analysis": {
            "summary": summary, "risk_score": risk_score, "risk_level": risk_level,
            "recommended_actions": recommended_actions,
        },
        "echoed_input": body,
    }


# ══════════════════════════════════════════════════════════════════════════
# EMS — 가상 설비·에너지 관리 시스템 / a fictional equipment/energy management system
# ══════════════════════════════════════════════════════════════════════════

EQUIPMENT = (
    ("EQ-001", "냉각기 1호기", "냉각기"), ("EQ-002", "냉각기 2호기", "냉각기"),
    ("EQ-003", "공조기 A-2", "공조기"), ("EQ-004", "공조기 B-1", "공조기"),
    ("EQ-005", "변압기 TR-3", "변압기"), ("EQ-006", "보일러 2호기", "보일러"),
    ("EQ-007", "펌프 P-4", "펌프"), ("EQ-008", "발전기 G-1", "발전기"),
)
EQUIP_STATUSES = ("normal", "warning", "fault")
TEMP_BASE = {"냉각기": 8, "공조기": 22, "변압기": 55, "보일러": 75, "펌프": 40, "발전기": 65}
SEVERITIES = ("info", "warning", "critical")
ALARM_MESSAGES = {
    "info": ("정기 점검 일정이 등록되었습니다", "필터 교체 주기가 도래했습니다", "야간 절전 모드로 전환되었습니다"),
    "warning": ("가동 온도가 임계치에 근접했습니다", "부하율이 90%를 초과했습니다", "진동 센서 값이 평소보다 높습니다"),
    "critical": ("과열로 인한 긴급 정지가 발생했습니다", "전력 공급이 일시 차단되었습니다", "누수 감지 센서가 작동했습니다"),
}
# 알람 풀의 심각도 배합을 고정해 둔다 — 6건 중 심각/경고/정보가 2건씩 섞이게 한다.
# Fix the severity mix of the alarm pool so the 6 slots split evenly across critical/warning/info.
ALARM_SEVERITY_CYCLE = ("critical", "warning", "info", "critical", "warning", "info")


def _energy_usage(site: str, period: str) -> dict:
    rng = _rng("ems.energy", site, period)
    year, month = _parse_period(period)
    kwh_total = rng.randint(80_000, 420_000)
    peak_at = datetime(year, month, rng.randint(1, 28), rng.randint(9, 18), rng.choice((0, 15, 30, 45)))
    by_day = [
        {"date": f"{year:04d}-{month:02d}-{d:02d}", "kwh": _rng("ems.energy.day", site, period, d).randint(2000, 16000)}
        for d in range(1, 8)
    ]
    return {
        "system": "EMS", "site": site, "period": period,
        "kwh_total": kwh_total, "cost_krw": int(kwh_total * rng.uniform(120, 160)),
        "peak_kw": rng.randint(300, 1200), "peak_at": peak_at.strftime("%Y-%m-%dT%H:%M:%S"),
        "vs_last_month_pct": round(rng.uniform(-15.0, 20.0), 1), "by_day": by_day,
    }


def _equipment_list(site: str) -> list[dict]:
    rows = []
    for eid, name, etype in EQUIPMENT:
        rng = _rng("ems.equipment", site, eid)
        status = rng.choices(EQUIP_STATUSES, weights=(70, 22, 8), k=1)[0]
        spread = 4 if status == "normal" else 10
        rows.append({
            "equipment_id": eid, "name": name, "type": etype, "status": status,
            "temp_c": round(TEMP_BASE.get(etype, 30) + rng.uniform(-4, spread), 1),
            "load_pct": rng.randint(0, 15) if status == "fault" else rng.randint(30, 98),
            "last_maintenance": (kst.now() - timedelta(days=rng.randint(5, 240))).strftime("%Y-%m-%d"),
        })
    return rows


def _alarm_list(hours: int) -> list[dict]:
    now = kst.now()
    alarms = []
    for i, sev in enumerate(ALARM_SEVERITY_CYCLE):
        rng = _rng("ems.alarm", hours, i)
        minutes_ago = int((i + 1) / (len(ALARM_SEVERITY_CYCLE) + 1) * hours * 60) + rng.randint(0, 10)
        at = now - timedelta(minutes=min(minutes_ago, hours * 60))
        alarms.append({
            "alarm_id": f"ALM-{100000 + i * 137 + rng.randint(0, 99)}",
            "severity": sev, "equipment_id": EQUIPMENT[rng.randrange(len(EQUIPMENT))][0],
            "message": rng.choice(ALARM_MESSAGES[sev]),
            "at": at.strftime("%Y-%m-%dT%H:%M:%S"), "acknowledged": rng.random() < 0.4,
        })
    return alarms


@router.get("/ems/v1/energy/usage")
def ems_energy_usage(
    site: str = Query("HQ"), period: str | None = Query(None), _auth: None = Depends(require_ems_key),
) -> dict:
    return _energy_usage(site, period or kst.now().strftime("%Y-%m"))


@router.get("/ems/v1/equipment")
def ems_equipment(
    site: str = Query("HQ"), status: str = Query("all"), _auth: None = Depends(require_ems_key),
) -> dict:
    rows = _equipment_list(site)
    if status != "all":
        rows = [r for r in rows if r["status"] == status]
    return {"system": "EMS", "site": site, "count": len(rows), "items": rows}


EQUIP_CONTROL_COMMANDS = ("start", "stop", "restart")
EQUIP_CONTROL_VERBS = {"start": "가동", "stop": "정지", "restart": "재시작"}


@router.post("/ems/v1/equipment/{equipment_id}/control")
def ems_equipment_control(
    equipment_id: str, body: dict | None = Body(None), _auth: None = Depends(require_ems_key),
) -> dict:
    """설비 제어 — start/stop/restart 중 하나가 아니면 422.
    Control equipment (start/stop/restart) — 422 for any other command."""
    body = body or {}
    command = str(body.get("command") or "").lower()
    if command not in EQUIP_CONTROL_COMMANDS:
        raise MockAPIError(422, "invalid_request", "command은 start/stop/restart 중 하나여야 합니다")

    previous_status = "stopped" if command == "start" else "running"
    status = "stopped" if command == "stop" else "running"
    return {
        "system": "EMS", "action": "equipment.control", "ok": True,
        "equipment_id": equipment_id, "command": command,
        "previous_status": previous_status, "status": status,
        "executed_at": kst.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "message": f"{equipment_id} 설비를 {EQUIP_CONTROL_VERBS[command]}했습니다.",
    }


@router.get("/ems/v1/alarms")
def ems_alarms(
    severity: str = Query("all"), hours: int = Query(24), _auth: None = Depends(require_ems_key),
) -> dict:
    hours = max(1, min(hours, 720))
    alarms = _alarm_list(hours)
    if severity in SEVERITIES:
        alarms = [a for a in alarms if a["severity"] == severity]
    return {"system": "EMS", "window_hours": hours, "count": len(alarms), "alarms": alarms}


@router.post("/ems/v1/alarms/{alarm_id}/ack")
def ems_alarm_ack(alarm_id: str, body: dict | None = Body(None), _auth: None = Depends(require_ems_key)) -> dict:
    """알람 확인 처리 — alarm_id는 형식 검증 없이 그대로 반영한다.
    Acknowledge an alarm — alarm_id is echoed back with no shape validation."""
    body = body or {}
    note = body.get("note")
    return {
        "system": "EMS", "action": "alarm.ack", "ok": True,
        "alarm_id": alarm_id, "acknowledged": True,
        "acknowledged_at": kst.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "note": note,
        "message": f"알람 {alarm_id}을(를) 확인 처리했습니다.",
    }


@router.post("/ems/v1/report")
def ems_report(body: dict | None = Body(None), _auth: None = Depends(require_ems_key)) -> dict:
    body = body or {}
    site = body.get("site") or "HQ"
    period = body.get("period") or kst.now().strftime("%Y-%m")
    usage = _energy_usage(site, period)
    equipment = _equipment_list(site)
    alarms = _alarm_list(24)
    alarms_critical = sum(1 for a in alarms if a["severity"] == "critical")
    equipment_fault = sum(1 for e in equipment if e["status"] == "fault")
    report_id = "rpt_" + hashlib.sha256(f"{site}|{period}".encode("utf-8")).hexdigest()[:8]
    return {
        "system": "EMS", "report_id": report_id, "site": site, "period": period,
        "kpis": {
            "kwh_total": usage["kwh_total"], "cost_krw": usage["cost_krw"], "peak_kw": usage["peak_kw"],
            "alarms_critical": alarms_critical, "equipment_fault": equipment_fault,
        },
        "findings": [
            f"{site} 사이트의 {period} 총 사용량은 {usage['kwh_total']:,}kWh로 전월 대비 "
            f"{usage['vs_last_month_pct']}% 변동했습니다.",
            f"설비 {len(equipment)}대 중 {equipment_fault}대가 고장 상태로 점검이 필요합니다.",
            f"최근 24시간 내 심각(critical) 알람이 {alarms_critical}건 발생했습니다.",
        ],
        "recommendations": [
            "피크 시간대(오전 9시~오후 6시) 부하 분산으로 최대수요전력을 낮추는 방안을 검토합니다.",
            "고장·경고 상태 설비를 우선순위로 정기 점검 일정을 재조정합니다.",
            "심각 등급 알람이 발생한 설비에 대해 예방 정비 계획을 수립합니다.",
        ],
    }


# ══════════════════════════════════════════════════════════════════════════
# 카탈로그 — 워크플로우 "API 요청" 작업 에디터가 그대로 불러오는 메타데이터
# Catalog — metadata the workflow "API request" task editor loads as-is
# ══════════════════════════════════════════════════════════════════════════

# 샘플의 {{input.xxx}} 변수명 -> 견본 값. 카탈로그 항목은 실제로 쓰는 변수만 골라 test_vars 로 낸다.
# {{input.xxx}} variable name -> sample value. Each catalog item's test_vars picks only the vars it uses.
VAR_VALUES = {
    "input.period": "2026-08",
    "input.site": "HQ",
    "input.question": "이번 달 매출 어때?",
    "input.customer_id": "C-1042",
    "input.department": "영업",
    "input.sku": "SKU-1001",
}


def _test_vars(*names: str) -> dict:
    """카탈로그 샘플이 실제로 참조하는 변수만 견본 값과 함께 추린다.
    Pick out only the variables a catalog sample actually references, with their sample values."""
    return {n: VAR_VALUES[n] for n in names}


# 입력값 설명(2026-09-14) — 샘플 불러오기가 API 설정의 입력값 표(api.input_docs)를 미리 채우는 재료. 자동 제공 변수
# (question·user_name 등)는 제외되고 예시는 test_vars 의 견본 값을 그대로 쓴다. 기본값은 관리자가 정한다(넣지 않음).
# Input descriptions (2026-09-14) — what "Load sample" pre-fills into the API settings input table (api.input_docs).
# Auto-filled variables (question, user_name, ...) are excluded; the example is the test_vars sample value. No defaults
# (a default is the admin's business decision).
INPUT_DOC_DESC = {
    "period": "조회 기간(월, YYYY-MM)", "site": "사업장 코드", "customer_id": "고객 코드", "department": "부서명",
    "sku": "품목 코드", "qty": "주문 수량", "order_id": "주문 번호", "equipment_id": "설비 번호",
    "command": "제어 명령(start/stop/restart)", "alarm_id": "알람 번호",
}


def _item_input_docs(test_vars: dict) -> list[dict]:
    """test_vars 의 {{input.<이름>}} 중 자동 제공분을 뺀 것을 입력값 설명 행으로 / test_vars minus auto inputs → input-doc rows"""
    from app.flow_api_call import AUTO_INPUTS  # 지연 임포트(순환 방지) / lazy import (avoids cycles)
    rows = []
    for var, val in (test_vars or {}).items():
        if not var.startswith("input.") or var in AUTO_INPUTS:
            continue
        name = var[len("input."):]
        rows.append({"name": name, "description": INPUT_DOC_DESC.get(name, ""), "example": str(val)})
    return rows


def _body(payload: dict | None) -> dict:
    """워크플로우 편집기용 body 블록 — JSON은 2칸 들여쓰기 문자열로 미리 렌더링해 둔다.
    The body block for the workflow editor — JSON is pre-rendered as a 2-space indented string."""
    if payload is None:
        return {"content_type": "none", "payload": ""}
    return {"content_type": "application/json", "payload": json.dumps(payload, ensure_ascii=False, indent=2)}


def _response(outputs: list[dict] | None) -> dict:
    """모든 샘플이 공유하는 response 옵션 골격.
    The response option skeleton shared by every sample."""
    return {
        "format": "auto", "path": "", "outputs": outputs or [],
        "ok_status": "2xx", "on_error": "continue", "retries": 0, "retry_wait": 2,
        "preview_chars": 1200, "include_in_answer": True,
    }


def _erp_sample(name: str, method: str, path: str, params: list[dict] | None = None,
                payload: dict | None = None, outputs: list[dict] | None = None) -> dict:
    """ERP 샘플 공통 골격 — 인증은 전 항목이 Bearer 로 동일하다.
    Common ERP sample skeleton — auth is Bearer across every ERP item."""
    return {
        "name": name, "method": method, "url": "{{base_url}}" + path, "timeout": 30,
        "auth": {"type": "bearer", "key": DEMO_KEYS["erp"], "in": "header", "name": "Authorization"},
        "headers": [{"name": "Accept", "value": "application/json"}],
        "params": params or [], "body": _body(payload), "response": _response(outputs),
    }


def _ems_sample(name: str, method: str, path: str, params: list[dict] | None = None,
                 payload: dict | None = None, outputs: list[dict] | None = None) -> dict:
    """EMS 샘플 공통 골격 — api_key 인증만 ERP와 다르다.
    Common EMS sample skeleton — only the api_key auth differs from ERP."""
    return {
        "name": name, "method": method, "url": "{{base_url}}" + path, "timeout": 30,
        "auth": {"type": "api_key", "key": DEMO_KEYS["ems"], "in": "header", "name": "X-API-Key"},
        "headers": [{"name": "Accept", "value": "application/json"}],
        "params": params or [], "body": _body(payload), "response": _response(outputs),
    }


_CATALOG_ITEMS = [
    {
        "id": "erp.sales_summary", "system": "erp", "label": "ERP 매출 요약 조회", "kind": "read",
        "description": "지점별 매출·목표·달성률과 주력 상품 매출을 조회합니다.",
        "sample": _erp_sample(
            "ERP 매출 요약 조회", "GET", "/mock/erp/v1/sales/summary",
            params=[{"name": "period", "value": "{{input.period}}"}, {"name": "branch", "value": "all"}],
            outputs=[
                {"name": "total_sales", "path": "$.total_sales"},
                {"name": "achievement_pct", "path": "$.achievement_pct"},
                {"name": "growth_pct", "path": "$.growth_pct"},
            ],
        ),
        "test_vars": _test_vars("input.period"),
    },
    {
        "id": "erp.orders_search", "system": "erp", "label": "ERP 주문 검색", "kind": "read",
        "description": "고객·상태·기간 조건으로 주문 목록을 검색합니다.",
        "sample": _erp_sample(
            "ERP 주문 검색", "POST", "/mock/erp/v1/orders/search",
            payload={"customer_id": "{{input.customer_id}}", "status": "open", "limit": 10},
            outputs=[{"name": "count", "path": "$.count"}, {"name": "orders", "path": "$.orders"}],
        ),
        "test_vars": _test_vars("input.customer_id"),
    },
    {
        "id": "erp.inventory", "system": "erp", "label": "ERP 재고 조회", "kind": "read",
        "description": "SKU별 재고 수량·가용 재고·창고별 보유량을 조회합니다. SKU를 비우면 전 품목 재고 요약을 돌려줍니다.",
        "sample": _erp_sample(
            "ERP 재고 조회", "GET", "/mock/erp/v1/inventory/{{input.sku}}",
            outputs=[
                {"name": "available", "path": "$.available"},
                {"name": "on_hand", "path": "$.on_hand"},
                {"name": "unit_cost", "path": "$.unit_cost"},
            ],
        ),
        "test_vars": _test_vars("input.sku"),
    },
    {
        "id": "erp.hr_headcount", "system": "erp", "label": "ERP 인원 현황 조회", "kind": "read",
        "description": "부서별 인원 수·입사·퇴사·채용 진행 현황을 조회합니다.",
        "sample": _erp_sample(
            "ERP 인원 현황 조회", "GET", "/mock/erp/v1/hr/headcount",
            params=[{"name": "dept", "value": "{{input.department}}"}],
            outputs=[
                {"name": "headcount", "path": "$.headcount"},
                {"name": "open_positions", "path": "$.open_positions"},
            ],
        ),
        "test_vars": _test_vars("input.department"),
    },
    {
        "id": "erp.analyze", "system": "erp", "label": "ERP 고객 분석", "kind": "read",
        "description": "질문·고객·부서를 바탕으로 거래 위험도와 권고 조치를 생성합니다.",
        "sample": _erp_sample(
            "ERP 고객 분석", "POST", "/mock/erp/v1/analyze",
            payload={
                "question": "{{input.question}}", "customer_id": "{{input.customer_id}}",
                "department": "{{input.department}}",
                "options": {"include_summary": True, "language": "ko"},
            },
            outputs=[
                {"name": "summary", "path": "$.analysis.summary"},
                {"name": "risk_level", "path": "$.analysis.risk_level"},
                {"name": "risk_score", "path": "$.analysis.risk_score"},
            ],
        ),
        "test_vars": _test_vars("input.question", "input.customer_id", "input.department"),
    },
    {
        "id": "erp.order_create", "system": "erp", "label": "ERP 주문 생성", "kind": "action",
        "description": "고객·품목·수량으로 ERP 주문을 생성합니다. 주문 넣어줘, 발주해줘 같은 요청에 사용합니다.",
        "sample": _erp_sample(
            "ERP 주문 생성", "POST", "/mock/erp/v1/orders",
            payload={
                "customer_id": "{{input.customer_id}}", "sku": "{{input.sku}}",
                "qty": "{{input.qty}}", "note": "{{input.question}}",
            },
            outputs=[
                {"name": "order_id", "path": "$.order_id"},
                {"name": "status", "path": "$.status"},
            ],
        ),
        "test_vars": {
            "input.customer_id": "C-1042", "input.sku": "SKU-1001",
            "input.qty": "10", "input.question": "SKU-1001 10개 주문 넣어줘",
        },
    },
    {
        "id": "erp.order_approve", "system": "erp", "label": "ERP 주문 승인", "kind": "action",
        "description": "주문 번호로 ERP 주문을 승인 처리합니다. 주문 승인해줘 요청에 사용합니다.",
        "sample": _erp_sample(
            "ERP 주문 승인", "POST", "/mock/erp/v1/orders/{{input.order_id}}/approve",
            payload={"approver": "{{input.user_name}}", "comment": "{{input.question}}"},
            outputs=[{"name": "status", "path": "$.status"}],
        ),
        "test_vars": {
            "input.order_id": "O-100231", "input.user_name": "홍서연",
            "input.question": "주문 O-100231 승인해줘",
        },
    },
    {
        "id": "ems.energy_usage", "system": "ems", "label": "EMS 에너지 사용량 조회", "kind": "read",
        "description": "사업장별 전력 사용량·요금·최대수요전력을 조회합니다.",
        "sample": _ems_sample(
            "EMS 에너지 사용량 조회", "GET", "/mock/ems/v1/energy/usage",
            params=[{"name": "site", "value": "{{input.site}}"}, {"name": "period", "value": "{{input.period}}"}],
            outputs=[
                {"name": "kwh_total", "path": "$.kwh_total"},
                {"name": "cost_krw", "path": "$.cost_krw"},
                {"name": "peak_kw", "path": "$.peak_kw"},
            ],
        ),
        "test_vars": _test_vars("input.site", "input.period"),
    },
    {
        "id": "ems.equipment", "system": "ems", "label": "EMS 설비 현황 조회", "kind": "read",
        "description": "사업장 내 설비 상태·온도·부하율을 조회합니다.",
        "sample": _ems_sample(
            "EMS 설비 현황 조회", "GET", "/mock/ems/v1/equipment",
            params=[{"name": "site", "value": "{{input.site}}"}, {"name": "status", "value": "all"}],
            outputs=[{"name": "count", "path": "$.count"}, {"name": "items", "path": "$.items"}],
        ),
        "test_vars": _test_vars("input.site"),
    },
    {
        "id": "ems.alarms", "system": "ems", "label": "EMS 알람 조회", "kind": "read",
        "description": "최근 발생한 설비 알람을 심각도별로 조회합니다.",
        "sample": _ems_sample(
            "EMS 알람 조회", "GET", "/mock/ems/v1/alarms",
            params=[{"name": "severity", "value": "all"}, {"name": "hours", "value": "24"}],
            outputs=[{"name": "count", "path": "$.count"}, {"name": "alarms", "path": "$.alarms"}],
        ),
        "test_vars": {},
    },
    {
        "id": "ems.report", "system": "ems", "label": "EMS 보고서 생성", "kind": "read",
        "description": "사업장·기간을 지정해 에너지·설비 종합 보고서를 생성합니다.",
        "sample": _ems_sample(
            "EMS 보고서 생성", "POST", "/mock/ems/v1/report",
            payload={"site": "{{input.site}}", "period": "{{input.period}}"},
            outputs=[{"name": "kpis", "path": "$.kpis"}, {"name": "findings", "path": "$.findings"}],
        ),
        "test_vars": _test_vars("input.site", "input.period"),
    },
    {
        "id": "ems.equipment_control", "system": "ems", "label": "EMS 설비 제어", "kind": "action",
        "description": "설비를 가동·정지·재시작합니다. 설비 꺼줘, 재시작해줘 요청에 사용합니다.",
        "sample": _ems_sample(
            "EMS 설비 제어", "POST", "/mock/ems/v1/equipment/{{input.equipment_id}}/control",
            payload={"command": "{{input.command}}", "reason": "{{input.question}}"},
            outputs=[{"name": "status", "path": "$.status"}],
        ),
        "test_vars": {
            "input.equipment_id": "CH-01", "input.command": "restart",
            "input.question": "냉각기 1호기 재시작해줘",
        },
    },
    {
        "id": "ems.alarm_ack", "system": "ems", "label": "EMS 알람 확인 처리", "kind": "action",
        "description": "알람을 확인 처리합니다. 알람 확인했다고 처리해줘 요청에 사용합니다.",
        "sample": _ems_sample(
            "EMS 알람 확인 처리", "POST", "/mock/ems/v1/alarms/{{input.alarm_id}}/ack",
            payload={"note": "{{input.question}}"},
            outputs=[{"name": "acknowledged", "path": "$.acknowledged"}],
        ),
        "test_vars": {
            "input.alarm_id": "AL-2043", "input.question": "알람 AL-2043 확인 처리해줘",
        },
    },
]


def catalog() -> dict:
    """/mock/catalog 응답과 동일한 객체 — 다른 모듈에서 임포트해 재사용할 수 있다.
    The same object returned by /mock/catalog — importable and reusable from other modules."""
    return {
        "systems": [
            {"id": "erp", "label": "ERP", "key_hint": f"Authorization: Bearer {DEMO_KEYS['erp']}"},
            {"id": "ems", "label": "EMS", "key_hint": f"X-API-Key: {DEMO_KEYS['ems']}"},
        ],
        # input_docs(2026-09-14) = 샘플 불러오기가 입력값 표를 채우는 재료 / what "Load sample" pre-fills into the input table
        "items": [{**it, "input_docs": _item_input_docs(it.get("test_vars") or {})} for it in _CATALOG_ITEMS],
        # 데모 MCP 서버(2026-09-15) — MCP 등록 패널의 "데모 서버 채우기" 재료(주소는 {{base_url}} 로 두어 배포 호스트를 따라간다)
        # Demo MCP server (2026-09-15) — what the MCP panel's "fill demo server" button uses (URL keeps {{base_url}} so it follows the host)
        "mcp": {"label": "데모 MCP 서버 (ERP·EMS)", "url": "{{base_url}}/mock/mcp", "category": "other",
                "description": "가상 ERP·EMS 의 조회·실행 도구 6종을 MCP 로 제공하는 데모 서버입니다.",
                "auth": {"type": "bearer", "key": "demo-mcp-key-2026", "name": "Authorization"}},
    }


@router.get("/catalog")
def get_catalog() -> dict:
    return catalog()
