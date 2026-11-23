"""채팅 실시간 위젯 API(2026-10-06) — 지도 카드가 화면에서 부르는 길(지도 로드 허가 · 다시 불러오기 · 더 보기 · 가게 정보 · 사진)과
이번 달 무료 사용량 조회. 서버 키는 응답에 싣지 않는다(지도 로드에는 지도용 키만).

Chat live-widget API (2026-10-06) — the routes the map card calls from the page (map-load permit, reload, more, place
details, photos) plus this month's free usage. The server key is never returned (map loads get only the map key).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query

from app import live_places, live_usage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/live", tags=["live"])


def _lang(lang: str) -> str:
    return "en" if (lang or "").lower() == "en" else "ko"


def _fail(e: Exception) -> HTTPException:
    """예외 → 화면이 구분할 수 있는 응답 / map an exception to a response the page can tell apart."""
    if isinstance(e, live_usage.QuotaExceeded):
        return HTTPException(status_code=429, detail={"reason": "quota", "sku": e.sku})
    if isinstance(e, live_places.NoKey):
        return HTTPException(status_code=503, detail={"reason": "no_key"})
    if isinstance(e, ValueError):
        return HTTPException(status_code=422, detail={"reason": "invalid", "message": str(e)})
    return HTTPException(status_code=502, detail={"reason": "upstream"})


@router.post("/map-load")
def map_load() -> dict:
    """지도 1개를 띄우기 전에 부른다 — 이번 달 지도 로드 한도 안이면 +1 하고 지도용 키 · 지도 ID 를 준다.
    Called before creating one map: within this month's map-load limit it counts +1 and returns the map key and map ID."""
    key = live_places.browser_key()
    if not key:
        return {"ok": False, "reason": "no_key"}
    if not live_usage.try_take("map_load"):
        return {"ok": False, "reason": "quota"}
    return {"ok": True, "key": key, "map_id": live_places.map_id()}


@router.get("/places")
async def places(q: str = Query(..., min_length=1, max_length=200), lang: str = "ko",
                 page: str | None = Query(None, max_length=2000), area: str = Query("", max_length=60)) -> dict:
    """검색(다시 불러오기 · 더 많은 장소) — page 가 있으면 {items, next}, 없으면 라이브 카드 전체.
    Search (reload / more places): with page → {items, next}; without → the whole live card."""
    lg = _lang(lang)
    try:
        res = await asyncio.to_thread(live_places.search, q, lg, page)
    except (live_usage.QuotaExceeded, live_places.PlacesError, ValueError) as e:
        raise _fail(e) from None
    if page:
        return res
    return live_places.card(q, area, lg, res)


@router.get("/places/{place_id}")
async def place_detail(place_id: str, lang: str = "ko") -> dict:
    """가게 정보(후기 · 소개 · 요일별 시간) — 가게 정보 패널을 열 때만 / place details, only when the panel opens."""
    try:
        return await asyncio.to_thread(live_places.detail, place_id, _lang(lang))
    except (live_usage.QuotaExceeded, live_places.PlacesError, ValueError) as e:
        raise _fail(e) from None


@router.get("/photo")
async def photo(name: str = Query(..., max_length=1900), w: int = Query(480, ge=80, le=1200)) -> dict:
    """사진 주소(짧게 유효) — 보이는 카드만 부른다 / a short-lived photo URI, requested only for visible cards."""
    try:
        return await asyncio.to_thread(live_places.photo, name, w)
    except (live_usage.QuotaExceeded, live_places.PlacesError, ValueError) as e:
        raise _fail(e) from None


@router.get("/usage")
def usage() -> dict:
    """이번 달(KST) 사용량과 한도(무료량의 90%) / this KST month's usage and limits (90% of the free amounts)."""
    return live_usage.stats()
