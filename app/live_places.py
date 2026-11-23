"""채팅 지도 위젯 데이터(2026-10-06) — 구글 Places API (New)로 장소를 찾아 위젯 카드 JSON 으로 정리한다.

구글 약관에 맞춘 원칙:
- 장소 데이터는 장소 ID 말고는 저장하지 않는다(채팅 기록에는 검색어 · 장소 ID 만). 다시 열면 다시 조회한다.
- 우리 AI 로 구글 후기 · 장소 정보를 요약하지 않는다(구글 장소 요약은 한국 미지원). 후기는 작성자 표기와 함께 그대로 보인다.
- 사진은 작성자 표기를 붙이고, 사진 주소만 브라우저로 넘긴다(서버 키는 브라우저로 가지 않는다).
무료 범위: 검색은 후기를 빼 Enterprise 등급(월 1,000 무료), 가게 정보는 열 때만 Enterprise + Atmosphere(월 1,000 무료),
사진은 보이는 카드만(월 1,000 무료) — 호출 전에 live_usage 가 이번 달 90%에서 막는다.

Chat map widget data (2026-10-06) — finds places with Google Places API (New) and normalizes them into widget JSON.
Following Google's terms: nothing but place IDs is stored (chat history keeps only the query and IDs; reopening
fetches again); our AI never summarizes Google reviews or place content (Google's own summaries are unavailable in
Korea), reviews are shown as-is with author attribution; photos carry author credit and only the photo URI reaches the
browser (the server key never does). Free tier: search omits reviews to stay on the Enterprise SKU (1,000 free/month),
details are fetched only when opened (Enterprise + Atmosphere, 1,000 free/month), photos only for visible cards
(1,000 free/month); live_usage refuses calls at 90% of the month.
"""
from __future__ import annotations

import logging
import os
import re
import ssl
import threading
from datetime import datetime
from urllib.parse import quote

import httpx

from app import kst, live_usage

logger = logging.getLogger(__name__)

TRANSPORT = None   # 테스트 전송 주입점(httpx 전송) · None = 실제 HTTP / test transport seam; None = real HTTP
BASE = "https://places.googleapis.com/v1"
PAGE_SIZE = 10
# 검색 필드 — 후기(reviews) · 소개(editorialSummary)는 빼서 Enterprise 등급에 머문다
# Search fields — reviews and editorialSummary are left out so the call stays on the Enterprise SKU
SEARCH_FIELDS = ",".join("places." + f for f in (
    "id", "displayName", "primaryTypeDisplayName", "rating", "userRatingCount", "priceRange", "priceLevel",
    "location", "shortFormattedAddress", "formattedAddress", "nationalPhoneNumber", "websiteUri", "googleMapsUri",
    "googleMapsLinks", "currentOpeningHours", "photos")) + ",nextPageToken"
# 가게 정보 필드 — 가게 정보를 열 때만(Enterprise + Atmosphere) / detail fields, only when a place is opened
DETAIL_FIELDS = ",".join((
    "id", "displayName", "primaryTypeDisplayName", "rating", "userRatingCount", "priceRange", "priceLevel",
    "location", "shortFormattedAddress", "formattedAddress", "nationalPhoneNumber", "websiteUri", "googleMapsUri",
    "googleMapsLinks", "currentOpeningHours", "regularOpeningHours", "photos", "editorialSummary", "reviews"))
PLACE_ID_RX = re.compile(r"^[A-Za-z0-9_-]{8,300}$")
PHOTO_RX = re.compile(r"^places/[A-Za-z0-9_-]{8,300}/photos/[A-Za-z0-9_-]{8,1500}$")
_SYM = {"KRW": "₩", "USD": "$", "JPY": "¥", "EUR": "€", "CNY": "¥", "GBP": "£"}
_LEVEL = {"INEXPENSIVE": 1, "MODERATE": 2, "EXPENSIVE": 3, "VERY_EXPENSIVE": 4}
_DOW_KO = ["월", "화", "수", "목", "금", "토", "일"]
_DOW_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class PlacesError(Exception):
    """구글 장소 서비스 호출 실패(문구에 키를 싣지 않는다) / a Places call failed (the message never carries the key)."""


class NoKey(PlacesError):
    """서버 키(GOOGLE_MAPS_SERVER_KEY)가 없다 / no server key configured."""


def server_key() -> str:
    return os.getenv("GOOGLE_MAPS_SERVER_KEY", "").strip()


_warned = {"browser": False}


def browser_key() -> str:
    """지도(Maps JavaScript)용 키 — 브라우저 전용 키가 없으면 서버 키로 대체(경고 1회). 브라우저 키는 화면 소스에 보이므로
    웹사이트 제한을 건 지도 전용 키를 권한다.
    The map (Maps JavaScript) key — falls back to the server key with a one-time warning. A browser key is visible in
    the page source, so a map-only key with website restrictions is recommended."""
    k = os.getenv("GOOGLE_MAPS_BROWSER_KEY", "").strip()
    if k:
        return k
    s = server_key()
    if s and not _warned["browser"]:
        _warned["browser"] = True
        logger.warning("GOOGLE_MAPS_BROWSER_KEY 가 없어 서버 키를 지도에 씁니다 — 지도 전용 키(웹사이트 제한)를 권합니다 / "
                       "no browser key; the server key is used for maps — a website-restricted map key is recommended")
    return s


# 데모 프로젝트의 지도 ID(2026-10-27 사용자 제공 — 지도 ID 는 페이지 소스에 그대로 보이는 공개 값이라 키가 아니다).
# GOOGLE_MAPS_MAP_ID 가 있으면 그것이 우선이다. 다른 구글 클라우드 프로젝트의 키를 쓰면 그 프로젝트의 지도 ID 를 넣어야 한다.
# The demo project's map ID (given by the user on 2026-10-27; map IDs are public values visible in the page source, not keys).
# GOOGLE_MAPS_MAP_ID overrides it; a key from another Google Cloud project needs that project's own map ID.
DEFAULT_MAP_ID = "1fd5384d963ac782387a959a"


def map_id() -> str:
    """고급 마커용 지도 ID(환경 변수 → 데모 프로젝트 지도 ID) / the map ID for advanced markers (env, then the demo project's ID)."""
    return os.getenv("GOOGLE_MAPS_MAP_ID", "").strip() or DEFAULT_MAP_ID


_SSL: ssl.SSLContext | None = None
_SSL_LOCK = threading.Lock()


def _client(timeout: float = 10.0) -> httpx.Client:
    global _SSL
    if TRANSPORT is not None:
        return httpx.Client(transport=TRANSPORT, timeout=timeout)
    if _SSL is None:
        with _SSL_LOCK:
            if _SSL is None:
                _SSL = httpx.create_ssl_context()
    return httpx.Client(timeout=timeout, verify=_SSL)


def _call(method: str, url: str, mask: str | None = None, body: dict | None = None,
          params: dict | None = None) -> dict:
    key = server_key()
    if not key:
        raise NoKey("no_key")
    headers = {"X-Goog-Api-Key": key}
    if mask:
        headers["X-Goog-FieldMask"] = mask
    try:
        with _client() as c:
            r = c.request(method, url, headers=headers, json=body, params=params)
    except httpx.HTTPError as e:
        raise PlacesError(f"{type(e).__name__}") from None
    if r.status_code >= 400:
        try:
            msg = ((r.json() or {}).get("error") or {}).get("message") or ""
        except ValueError:
            msg = ""
        raise PlacesError(f"HTTP {r.status_code} {msg}".replace(key, "***")[:300])
    try:
        return r.json() or {}
    except ValueError:
        raise PlacesError("응답 형식 오류 / bad response") from None


def _money(m: dict) -> str:
    return f"{int(m.get('units') or 0):,}"


def price(p: dict) -> str:
    """가격대 '₩10,000~20,000' (없으면 가격 수준 '₩₩', 그것도 없으면 '') / the price range, else the level, else ''."""
    pr = p.get("priceRange") or {}
    s, e = pr.get("startPrice"), pr.get("endPrice")
    if s or e:
        cur = (s or e).get("currencyCode") or "KRW"
        sym = _SYM.get(cur, cur + " ")
        if s and e:
            return f"{sym}{_money(s)}~{_money(e)}"
        return f"{sym}{_money(s)}~" if s else f"~{sym}{_money(e)}"
    lvl = _LEVEL.get(str(p.get("priceLevel") or "").replace("PRICE_LEVEL_", ""))
    return "₩" * lvl if lvl else ""


def _kst_time(rfc: str | None) -> datetime | None:
    if not rfc:
        return None
    try:
        return kst.to_kst(datetime.fromisoformat(str(rfc).replace("Z", "+00:00")))
    except ValueError:
        return None


def _ampm(t: datetime, lang: str) -> str:
    h12 = t.hour % 12 or 12
    if lang == "en":
        return f"{h12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"
    return f"{'오전' if t.hour < 12 else '오후'} {h12}:{t.minute:02d}"


def open_state(h: dict | None, lang: str = "ko") -> dict | None:
    """영업 상태 라벨(시각은 KST) — {now, label} / the opening-state label (times in KST)."""
    if not h:
        return None
    now_open = h.get("openNow")
    t = _kst_time(h.get("nextCloseTime") if now_open else h.get("nextOpenTime"))
    if now_open is None and t is None:
        return None
    day = ""
    if t is not None and t.date() != kst.today():
        day = (_DOW_EN if lang == "en" else _DOW_KO)[t.weekday()] + " "
    if lang == "en":
        if now_open:
            return {"now": True, "label": "Open" + (f" · Closes {day}{_ampm(t, 'en')}" if t else "")}
        return {"now": False, "label": "Closed" + (f" · Opens {day}{_ampm(t, 'en')}" if t else "")}
    if now_open:
        return {"now": True, "label": "영업 중" + (f" · {day}{_ampm(t, 'ko')}에 영업 종료" if t else "")}
    return {"now": False, "label": "영업 종료" + (f" · {day}{_ampm(t, 'ko')}에 영업 시작" if t else "")}


def _photo(p: dict) -> dict | None:
    photos = p.get("photos") or []
    if not photos or not photos[0].get("name"):
        return None
    a = (photos[0].get("authorAttributions") or [{}])[0]
    return {"name": photos[0]["name"], "author": a.get("displayName") or "", "author_uri": a.get("uri") or ""}


def norm(p: dict, lang: str = "ko") -> dict:
    """장소 1건 → 카드 항목 / one place → a card item."""
    loc = p.get("location") or {}
    links = p.get("googleMapsLinks") or {}
    return {
        "id": p.get("id") or "",
        "name": (p.get("displayName") or {}).get("text") or "",
        "cat": (p.get("primaryTypeDisplayName") or {}).get("text") or "",
        "rating": p.get("rating"), "count": p.get("userRatingCount"),
        "price": price(p),
        "lat": loc.get("latitude"), "lng": loc.get("longitude"),
        "addr": p.get("shortFormattedAddress") or p.get("formattedAddress") or "",
        "phone": p.get("nationalPhoneNumber") or "",
        "web": p.get("websiteUri") or "",
        "maps": links.get("placeUri") or p.get("googleMapsUri") or "",
        "dir": links.get("directionsUri") or "",
        "open": open_state(p.get("currentOpeningHours") or p.get("regularOpeningHours"), lang),
        "photo": _photo(p),
    }


def search(q: str, lang: str = "ko", page: str | None = None) -> dict:
    """Text Search 1회 → {items, next}. 이번 달 한도를 넘으면 QuotaExceeded / one Text Search; QuotaExceeded past the limit."""
    q = (q or "").strip()[:200]
    if not q:
        raise ValueError("검색어가 비어 있습니다")
    if not server_key():   # 키가 없으면 사용량을 올리지 않는다 / no key, no count
        raise NoKey("no_key")
    live_usage.take("places_search")
    body = {"textQuery": q, "languageCode": "en" if lang == "en" else "ko", "regionCode": "KR", "pageSize": PAGE_SIZE}
    if page:
        body["pageToken"] = str(page)[:2000]
    data = _call("POST", f"{BASE}/places:searchText", SEARCH_FIELDS, body=body)
    items = [norm(p, lang) for p in (data.get("places") or []) if p.get("id")]
    return {"items": items, "next": data.get("nextPageToken") or None}


def detail(pid: str, lang: str = "ko") -> dict:
    """가게 정보 1건(후기 · 소개 · 요일별 시간 포함) / one place's details (reviews, summary, weekly hours)."""
    if not PLACE_ID_RX.match(pid or ""):
        raise ValueError("잘못된 장소 ID")
    if not server_key():
        raise NoKey("no_key")
    live_usage.take("places_detail")
    p = _call("GET", f"{BASE}/places/{pid}", DETAIL_FIELDS,
              params={"languageCode": "en" if lang == "en" else "ko", "regionCode": "KR"})
    out = norm(p, lang)
    out["addr_full"] = p.get("formattedAddress") or out["addr"]
    hours = []
    for line in ((p.get("regularOpeningHours") or {}).get("weekdayDescriptions") or []):
        day, _, time_txt = str(line).partition(": ")
        hours.append({"day": day, "time": time_txt or ""})
    out["hours"] = hours
    out["about"] = (p.get("editorialSummary") or {}).get("text") or ""
    reviews = []
    for rv in (p.get("reviews") or [])[:3]:
        a = rv.get("authorAttribution") or {}
        txt = (rv.get("text") or {}).get("text") or (rv.get("originalText") or {}).get("text") or ""
        reviews.append({"author": a.get("displayName") or "", "author_uri": a.get("uri") or "",
                        "avatar": a.get("photoUri") or "", "rating": rv.get("rating"),
                        "when": rv.get("relativePublishTimeDescription") or "", "text": txt[:700],
                        "uri": rv.get("googleMapsUri") or ""})
    out["reviews"] = reviews
    out["reviews_uri"] = (p.get("googleMapsLinks") or {}).get("reviewsUri") or out["maps"]
    return out


def photo(name: str, width: int = 480) -> dict:
    """사진 주소(짧게 유효한 photoUri)만 돌려준다 / returns only the (short-lived) photo URI."""
    if not PHOTO_RX.match(name or ""):
        raise ValueError("잘못된 사진 이름")
    w = max(80, min(int(width or 480), 1200))
    if not server_key():
        raise NoKey("no_key")
    live_usage.take("places_photo")
    data = _call("GET", f"{BASE}/{name}/media", params={"maxWidthPx": w, "skipHttpRedirect": "true"})
    uri = data.get("photoUri") or ""
    if not uri.startswith("https://"):
        raise PlacesError("사진 주소 없음 / no photo URI")
    return {"uri": uri}


def search_url(q: str) -> str:
    return "https://www.google.com/maps/search/?api=1&query=" + quote(q or "")


def card(q: str, area: str, lang: str, res: dict) -> dict:
    """라이브 카드(화면 전용 — 저장하지 않는다) / the live card (screen only, never stored)."""
    return {"kind": "places", "v": 1, "query": q, "area": area or "", "lang": lang, "fetched_at": kst.iso_offset(),
            "items": res.get("items") or [], "next": res.get("next"),
            "source": {"name": "Google Maps" if lang == "en" else "Google 지도", "url": search_url(q)}}


def saved(c: dict) -> dict:
    """채팅 기록에 남기는 카드 — 검색어와 장소 ID 만(구글 약관) / the stored card: only the query and place IDs (Google terms)."""
    ids = [i["id"] for i in c.get("items") or [] if i.get("id")]
    return {"kind": "places", "v": 1, "query": c.get("query") or "", "area": c.get("area") or "",
            "lang": c.get("lang") or "ko", "ids": ids, "count": len(ids)}
