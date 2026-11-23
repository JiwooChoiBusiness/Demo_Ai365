"""채팅 위젯 외부 API 월 사용량 카운터 — 무료 범위 안에서만 쓰기 위한 앱 쪽 안전장치(2026-10-06 사용자 요청 "무료로만").

구글 지도 플랫폼은 호출 종류(SKU)마다 월 무료량이 있다(Essentials 10,000 · Pro 5,000 · Enterprise 1,000, 2025-03 개편).
여기서 이번 달(KST) 사용량을 세다가 무료량의 90%에 닿으면 호출 전에 막는다. 콘솔의 하루 한도(Places · Geocoding)와
별개로 동작하고, 하루 한도를 걸 수 없는 지도 로드(Maps JavaScript)도 여기서 막는다. 구글의 달은 미국 서부 기준이라
월 경계에서 몇 시간 어긋나지만 10% 여유가 흡수한다.

Monthly usage counters for the chat widgets' external APIs — the app-side guard for "free tier only" (user request
2026-10-06). Google Maps Platform gives each SKU a monthly free amount (Essentials 10,000, Pro 5,000, Enterprise 1,000
since 2025-03). This counts the current KST month and refuses a call once 90% of the free amount is used. It works
independently of the console's daily quotas (Places, Geocoding) and also covers map loads (Maps JavaScript), which
have no daily quota. Google's month follows US Pacific time, so the boundary is a few hours off; the 10% margin
absorbs it.
"""
from __future__ import annotations

import logging

from app import db, kst

logger = logging.getLogger(__name__)

# SKU → (한도, 설명). 한도 = 월 무료량의 90% / SKU → (limit, label); limit = 90% of the monthly free amount
LIMITS: dict[str, tuple[int, str]] = {
    "places_search": (900, "Places Text Search (Enterprise, 무료 1,000/월)"),
    "places_detail": (900, "Places Place Details (Enterprise + Atmosphere, 무료 1,000/월)"),
    "places_photo": (900, "Places Place Details Photos (무료 1,000/월)"),
    "geocode": (9000, "Geocoding (무료 10,000/월)"),
    "map_load": (9000, "Maps JavaScript 지도 로드 (Dynamic Maps, 무료 10,000/월)"),
}


class QuotaExceeded(Exception):
    """이번 달 무료 범위(90%)를 다 썼다 / this month's free allowance (90%) is used up."""

    def __init__(self, sku: str) -> None:
        super().__init__(sku)
        self.sku = sku


def init() -> None:
    """표 생성(멱등) / create the table (idempotent)."""
    with db._conn() as conn:  # noqa: SLF001 — 테스트가 db._conn 을 임시 DB 로 바꾼다 / tests swap db._conn for a temp DB
        conn.execute("CREATE TABLE IF NOT EXISTS live_usage("
                     "month TEXT NOT NULL, sku TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, "
                     "PRIMARY KEY(month, sku))")


def try_take(sku: str, n: int = 1) -> bool:
    """한도 안이면 원자적으로 n 만큼 올리고 True, 넘으면 올리지 않고 False.
    Atomically adds n and returns True when within the limit; returns False without adding when it would exceed."""
    limit = LIMITS[sku][0]
    month = kst.month()
    init()
    with db._conn() as conn:  # noqa: SLF001
        conn.execute("INSERT OR IGNORE INTO live_usage(month, sku, count) VALUES(?, ?, 0)", (month, sku))
        cur = conn.execute("UPDATE live_usage SET count = count + ? WHERE month = ? AND sku = ? AND count + ? <= ?",
                           (n, month, sku, n, limit))
        ok = cur.rowcount == 1
    if not ok:
        logger.warning("무료 사용량 한도 도달 — 호출 생략: %s (%s) / free allowance reached, call skipped", sku, month)
    return ok


def take(sku: str, n: int = 1) -> None:
    """try_take 의 예외판 / try_take that raises QuotaExceeded."""
    if not try_take(sku, n):
        raise QuotaExceeded(sku)


def stats() -> dict:
    """이번 달 사용량 · 한도 / this month's usage and limits."""
    month = kst.month()
    init()
    with db._conn() as conn:  # noqa: SLF001
        rows = {r["sku"]: r["count"] for r in conn.execute("SELECT sku, count FROM live_usage WHERE month = ?", (month,))}
    return {"month": month,
            "items": [{"sku": k, "used": rows.get(k, 0), "limit": lim, "label": label}
                      for k, (lim, label) in LIMITS.items()]}
