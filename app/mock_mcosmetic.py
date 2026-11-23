"""M코스메틱 가상 ERP·메일 API — Email Agent 의 외부 시스템 목업 (2026-09-28, 계획 B1).

화면(frontend/ai365-mcmail.html)이 보여 주는 가상 호출(GET /api/erp/v1/prices 등)을 실제 HTTP 로 노출한다.
응답은 app.mcmail 의 가상 ERP 함수(erp_price·erp_stock·erp_sales_order·erp_shipment·erp_create_sales_order)와
가상 메일 발송(mail_send)을 그대로 부른 결과이고, 스토어(run_erp·create_order·send)도 HTTP 홉 없이 같은 함수를
부른다. 데이터는 Email Agent 스토어(mc_* 테이블)의 Sales Order·Case 를 공유한다. 메일 발송은 외부로 보내지 않고
발신함에 저장만 한다.

인증: 헤더 Authorization: Bearer demo-mcosmetic-key-2026 (데모 표시값, 실제 비밀값이 아니다).
오류: {"error": {"code", "message"}} — 401 인증, 404 조회 결과 없음, 409 이미 다른 내용으로 있는 Sales Order,
422 입력 오류(대표 시나리오 Case 로 주문 등록 시도 포함, mock_apis 와 같은 모양).

M Cosmetic fictional ERP and mail API — the Email Agent's external systems. Exposes the calls the page shows as real
HTTP routes; each route calls the same virtual ERP / mail functions in app.mcmail that the store uses without an HTTP
hop, over the Email Agent store's sales orders and cases. Mail send only stores the message in an outbox.
Auth: Authorization: Bearer demo-mcosmetic-key-2026 (a demo display value). Errors use mock_apis' error shape:
401 auth, 404 not found, 409 a Sales Order already taken by other content, 422 invalid input (the scenario case too).
"""

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from app import mcmail
from app.mock_apis import MockAPIError, MockAPIRoute

# 데모용 고정 키 — 목업 인증 설명용 표시값 / fixed demo key, a display value documenting the mock auth
DEMO_KEY = "demo-mcosmetic-key-2026"


def require_key(authorization: str | None = Header(None)) -> None:
    """Authorization: Bearer demo-mcosmetic-key-2026 이 정확히 있어야 한다 / the bearer header must match exactly"""
    if authorization != f"Bearer {DEMO_KEY}":
        raise MockAPIError(401, "unauthorized", "유효한 API 키가 필요합니다 (Authorization: Bearer ...)")


router = APIRouter(prefix="/mock/mcosmetic", tags=["mock-mcosmetic"], route_class=MockAPIRoute,
                   dependencies=[Depends(require_key)])


def _found(r: dict) -> dict:
    """가상 ERP 의 {error} 결과 → 404 / a virtual-ERP {error} result becomes a 404"""
    if r.get("error"):
        raise MockAPIError(404, "not_found", r["error"])
    return r


def _qty(qty: str, required: bool = True):
    q = mcmail._number(qty)  # noqa: SLF001 — 화면과 같은 Number() 규칙 / the page's Number() rule
    if q is None or (required and (not (q > 0) or not mcmail._is_int(q))):  # noqa: SLF001
        raise MockAPIError(422, "invalid", "수량 값이 올바르지 않습니다.")
    return q


@router.get("/erp/v1/prices")
def prices(customer: str, item: str, qty: str) -> dict:
    """단가 조회 — 구간 할인(300/500/1000EA → 5/8/12%) / price lookup with tier discounts"""
    return _found(mcmail.erp_price(customer, item, _qty(qty)))


@router.get("/erp/v1/shipments")
def shipments(so: str = "", customer: str = "", item: str = "", case: str = "") -> dict:
    """출하내역 — 매칭 4순위(so → customer+item → customer 최근 주문 → case 의 주문) / shipments, 4 match priorities"""
    return _found(mcmail.erp_shipment(so or None, customer or None, item or None, case or None))


@router.get("/erp/v1/inventory/on-hand")
def on_hand(item: str, qty: str = "") -> dict:
    """On-hand·할당·가용 재고와 다음 입고 / on-hand, allocated and available stock with the next inbound"""
    return _found(mcmail.erp_stock(item, _qty(qty, required=False) if qty else None))


@router.get("/erp/v1/sales-orders/{so}")
def sales_order(so: str, customer: str = "") -> dict:
    """Sales Order → 인보이스 금액(공급가·VAT·합계) / sales order → invoice amounts"""
    return _found(mcmail.erp_sales_order(so, customer or None))


class SalesOrderIn(BaseModel):
    customerCode: str
    itemCode: str
    quantity: int | float | str
    deliveryDate: str
    itemName: str = ""
    caseId: str = ""


_ERR_CODE = {404: "not_found", 409: "conflict"}


@router.post("/erp/v1/sales-orders", status_code=201)
def create_sales_order(body: SalesOrderIn) -> dict:
    """Sales Order 생성(검증 4종 → 순번 → 출하 준비 등록). 대표 시나리오 Case 는 고정 번호(…-00125)를 가로채지 못하게 422 로
    거부하고, 번호는 Case 와 무관하게 순번으로만 배정한다. 이미 다른 내용으로 있는 번호면 409.
    Create a sales order (validate → sequence number → shipment entry). The scenario case is refused with 422 so the
    API can never take its fixed number (…-00125); numbers come from the sequence regardless of caseId. A number that
    already exists with other content is a 409."""
    if body.caseId.strip() == mcmail.SCN_CASE:
        raise MockAPIError(422, "invalid", f"{mcmail.SCN_CASE} 는 대표 시나리오 Case라 가상 ERP API로 주문을 등록할 수 없습니다.")
    try:
        return mcmail.erp_create_sales_order(body.customerCode, body.itemCode, body.quantity, body.deliveryDate,
                                             body.itemName, None)
    except mcmail.MailValidationError as e:
        raise MockAPIError(e.status, _ERR_CODE.get(e.status, "invalid"), str(e)) from None


class MailSendIn(BaseModel):
    to: str
    subject: str
    body: str
    cc: str = ""
    attachments: list[str] = []


@router.post("/mail/v1/send")
def send_mail(body: MailSendIn) -> dict:
    """가상 메일 발송 — 발신함에 저장만 한다 / virtual mail send: stored in the outbox only"""
    try:
        return mcmail.mail_send(body.to, body.subject, body.body, body.cc, body.attachments)
    except mcmail.MailValidationError as e:
        raise MockAPIError(422, "invalid", str(e)) from None
