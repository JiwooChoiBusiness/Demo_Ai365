"""채팅 날씨 위젯 데이터(2026-10-06) — Open-Meteo(키 없음) 7일 예보를 위젯 카드 JSON 으로 정리한다.

- 위치: Open-Meteo 지오코딩(GeoNames, 한국 우선) → 실패 시 구글 Geocoding(월 사용량 카운트) → 그래도 없으면 서울.
  좌표는 카드에 저장하지 않는다(구글 좌표는 장기 저장 금지 — 메모리 캐시만, 하루).
- 예보: current + hourly(7일 × 24시간) + daily(7일), timezone=Asia/Seoul — 앱의 모든 시각은 KST(외국 도시도 한국 시간 축).
- 무료 Open-Meteo 는 비상업 용도 · CC BY 4.0 — 카드에 출처(Open-Meteo)를 표기한다.

Chat weather widget data (2026-10-06) — normalizes the Open-Meteo (keyless) 7-day forecast into widget-card JSON.
Location: Open-Meteo geocoding (GeoNames, Korea first) → Google Geocoding (counted) → Seoul. Coordinates are never
stored in the card (Google coordinates must not be stored long-term — memory cache only, one day). Forecast: current +
hourly (7 days × 24 h) + daily (7 days) with timezone=Asia/Seoul — every app time is KST, foreign cities included.
The free Open-Meteo tier is non-commercial and CC BY 4.0, so the card credits Open-Meteo.
"""
from __future__ import annotations

import logging
import os
import ssl
import threading
import time
from datetime import date as _date

import httpx

from app import kst, live_usage

logger = logging.getLogger(__name__)

TRANSPORT = None   # 테스트 전송 주입점(httpx 전송) · None = 실제 HTTP / test transport seam; None = real HTTP
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
SOURCE = {"name": "Open-Meteo", "url": "https://open-meteo.com/"}
DEFAULT_PLACE = ("서울", 37.5665, 126.9780)
FORECAST_TTL = 600          # 예보 캐시 10분 / forecast cache, 10 min
GOOGLE_GEO_TTL = 86400      # 구글 좌표 메모리 캐시 하루(장기 저장 금지) / Google coordinates kept one day in memory only

# WMO 날씨 코드 → (아이콘, 한국어, 영어). 아이콘 8종은 시안 세트와 같다.
# WMO weather code → (icon, Korean, English). The eight icons match the design set.
WMO: dict[int, tuple[str, str, str]] = {
    0: ("sunny", "맑음", "Clear"),
    1: ("partly", "구름 조금", "Mostly sunny"),
    2: ("mostly", "구름 많음", "Partly cloudy"),
    3: ("cloudy", "흐림", "Cloudy"),
    45: ("cloudy", "안개", "Fog"), 48: ("cloudy", "안개", "Fog"),
    51: ("rain", "이슬비", "Drizzle"), 53: ("rain", "이슬비", "Drizzle"), 55: ("rain", "이슬비", "Drizzle"),
    56: ("rain", "어는 이슬비", "Freezing drizzle"), 57: ("rain", "어는 이슬비", "Freezing drizzle"),
    61: ("rain", "약한 비", "Light rain"), 63: ("rain", "비", "Rain"), 65: ("rain", "강한 비", "Heavy rain"),
    66: ("rain", "어는 비", "Freezing rain"), 67: ("rain", "어는 비", "Freezing rain"),
    71: ("snow", "약한 눈", "Light snow"), 73: ("snow", "눈", "Snow"), 75: ("snow", "많은 눈", "Heavy snow"),
    77: ("snow", "싸락눈", "Snow grains"),
    80: ("shower", "약한 소나기", "Light showers"), 81: ("shower", "소나기", "Showers"),
    82: ("shower", "강한 소나기", "Heavy showers"),
    85: ("snow", "소낙눈", "Snow showers"), 86: ("snow", "소낙눈", "Snow showers"),
    95: ("thunder", "뇌우", "Thunderstorm"), 96: ("thunder", "우박 동반 뇌우", "Thunderstorm with hail"),
    99: ("thunder", "우박 동반 뇌우", "Thunderstorm with hail"),
}
WET_ICONS = ("rain", "shower", "snow", "thunder")
DOW_KO = ["월", "화", "수", "목", "금", "토", "일"]
DOW_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class WeatherError(Exception):
    """날씨 서비스에 닿지 못했다 / the weather service could not be reached."""


def label(code: int | None, lang: str = "ko") -> str:
    """WMO 코드 → 날씨 문구 / WMO code → condition text."""
    icon, ko, en = WMO.get(int(code) if code is not None else -1, ("cloudy", "흐림", "Cloudy"))
    return en if lang == "en" else ko


def icon(code: int | None) -> str:
    return WMO.get(int(code) if code is not None else -1, ("cloudy",))[0]


_SSL: ssl.SSLContext | None = None
_SSL_LOCK = threading.Lock()


def _client(timeout: float = 8.0) -> httpx.Client:
    """공용 SSL 컨텍스트로 만든 httpx 클라이언트(테스트 전송이면 그대로) / an httpx client on a shared SSL context."""
    global _SSL
    if TRANSPORT is not None:
        return httpx.Client(transport=TRANSPORT, timeout=timeout)
    if _SSL is None:
        with _SSL_LOCK:
            if _SSL is None:
                _SSL = httpx.create_ssl_context()
    return httpx.Client(timeout=timeout, verify=_SSL)


_geo_cache: dict[str, tuple[float, str, float, float]] = {}   # 이름 → (만료, 이름표, 위도, 경도) / name → (expires, label, lat, lon)
_fc_cache: dict[tuple[float, float], tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def _open_meteo_geocode(name: str, korea: bool) -> tuple[float, float] | None:
    params = {"name": name, "count": 5, "language": "ko", "format": "json"}
    if korea:
        params["countryCode"] = "KR"
    with _client() as c:
        r = c.get(GEOCODE_URL, params=params)
    r.raise_for_status()
    results = (r.json() or {}).get("results") or []
    if not results:
        return None
    # 인구가 가장 많은 곳 우선(같은 이름의 작은 마을보다 도시) / prefer the most populous match (a city over a hamlet)
    best = max(results, key=lambda x: x.get("population") or 0)
    return float(best["latitude"]), float(best["longitude"])


def _google_geocode(name: str) -> tuple[float, float] | None:
    """구글 Geocoding — 키가 주소(URL)에 실리므로 오류는 상태 코드 · 예외 이름만 남긴다(주소 · 키를 로그에 쓰지 않는다).
    Google Geocoding: the key rides in the URL, so failures log only the status code or exception name (never the URL or key)."""
    key = os.getenv("GOOGLE_MAPS_SERVER_KEY", "").strip()
    if not key or not live_usage.try_take("geocode"):
        return None
    try:
        with _client() as c:
            r = c.get(GOOGLE_GEOCODE_URL, params={"address": name, "language": "ko", "region": "kr", "key": key})
    except httpx.HTTPError as e:
        logger.warning("구글 Geocoding 연결 실패 / Google geocoding unreachable: %s", type(e).__name__)
        return None
    if r.status_code != 200:
        logger.warning("구글 Geocoding 실패 / Google geocoding failed: HTTP %s", r.status_code)
        return None
    try:
        results = (r.json() or {}).get("results") or []
        if not results:
            return None
        loc = results[0]["geometry"]["location"]
        return float(loc["lat"]), float(loc["lng"])
    except (ValueError, KeyError, TypeError, IndexError):
        logger.warning("구글 Geocoding 응답 형식 오류 / Google geocoding returned an unexpected body")
        return None


def resolve(name: str | None) -> tuple[str, float, float, bool]:
    """위치 이름 → (이름표, 위도, 경도, 찾음). 이름표는 사용자가 쓴 말 그대로(구글 주소 문자열을 저장하지 않는다).
    못 찾으면 서울(찾음=False) — 답변이 그 사실을 알린다.
    A place name → (label, lat, lon, found). The label is the user's own wording (no Google address string is stored).
    Unknown names fall back to Seoul (found=False) and the answer says so."""
    name = (name or "").strip()
    if not name:
        return DEFAULT_PLACE + (True,)
    now = time.time()
    with _cache_lock:
        hit = _geo_cache.get(name)
    if hit and hit[0] > now:
        return hit[1], hit[2], hit[3], True
    found, ttl = None, 10 ** 9
    try:
        candidates = [name]
        if len(name) > 2 and name[-1] in "시도군":   # '부산시' → '부산' 도 시도 / also try without the admin suffix
            candidates.append(name[:-1])
        for cand in candidates:
            found = _open_meteo_geocode(cand, True) or _open_meteo_geocode(cand, False)
            if found:
                break
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        logger.warning("Open-Meteo 지오코딩 실패 — 구글로 대체 / geocoding failed, falling back to Google", exc_info=True)
    if not found:
        found = _google_geocode(name)   # 오류는 안에서 처리(키가 로그에 남지 않게) / handles its own errors (keeps the key out of logs)
        ttl = GOOGLE_GEO_TTL
    if not found:
        return DEFAULT_PLACE + (False,)
    with _cache_lock:
        _geo_cache[name] = (now + ttl, name, found[0], found[1])
    return name, found[0], found[1], True


def forecast(lat: float, lon: float) -> dict:
    """Open-Meteo 원 응답(10분 캐시) / the raw Open-Meteo response (10-minute cache)."""
    key = (round(lat, 2), round(lon, 2))
    now = time.time()
    with _cache_lock:
        hit = _fc_cache.get(key)
    if hit and now - hit[0] < FORECAST_TTL:
        return hit[1]
    params = {
        "latitude": key[0], "longitude": key[1], "timezone": "Asia/Seoul", "forecast_days": 7,
        "current": "temperature_2m,weather_code,apparent_temperature,relative_humidity_2m",
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
    }
    try:
        with _client() as c:
            r = c.get(FORECAST_URL, params=params)
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise WeatherError(str(e)) from None
    with _cache_lock:
        _fc_cache[key] = (now, data)
    return data


def _r1(v) -> float | None:
    return None if v is None else round(float(v), 1)


def card(label_text: str, raw: dict, selected: int = 0) -> dict:
    """원 응답 → 위젯 카드 JSON(좌표 없음) / raw response → widget card JSON (no coordinates)."""
    cur = raw.get("current") or {}
    d = raw.get("daily") or {}
    h = raw.get("hourly") or {}
    days = []
    for i, date in enumerate(d.get("time") or []):
        days.append({"date": date,
                     "max": _r1((d.get("temperature_2m_max") or [None])[i]),
                     "min": _r1((d.get("temperature_2m_min") or [None])[i]),
                     "code": (d.get("weather_code") or [None])[i],
                     "pop": (d.get("precipitation_probability_max") or [None])[i]})
    return {
        "kind": "weather", "v": 1, "location": label_text, "fetched_at": kst.iso_offset(),
        "now": {"t": _r1(cur.get("temperature_2m")), "code": cur.get("weather_code"),
                "feels": _r1(cur.get("apparent_temperature")), "hum": cur.get("relative_humidity_2m"),
                "time": cur.get("time")},
        "days": days[:7],
        "hourly": {"time": list(h.get("time") or []), "t": [_r1(v) for v in (h.get("temperature_2m") or [])],
                   "pop": list(h.get("precipitation_probability") or []), "code": list(h.get("weather_code") or [])},
        "selected": max(0, min(int(selected or 0), max(0, len(days[:7]) - 1))),
        "source": dict(SOURCE),
    }


def get(location: str | None, day: int = 0) -> tuple[dict, bool]:
    """위치 이름 + 고른 날 → (카드, 위치를 찾았는가) / a place name and the selected day → (card, location found)."""
    label_text, lat, lon, found = resolve(location)
    return card(label_text, forecast(lat, lon), day), found


def _dow(date: str, lang: str) -> str:
    try:
        y, m, dd = (int(x) for x in date.split("-"))
        wd = _date(y, m, dd).weekday()
    except (ValueError, AttributeError):
        return date
    return (DOW_EN if lang == "en" else DOW_KO)[wd]


def josa(word: str, with_final: str, without_final: str) -> str:
    """받침에 맞는 조사(서울은 · 부산은 · 제주는). 한글이 아니면 '은(는)'처럼 둘 다 / the particle that fits the final consonant."""
    ch = (word or "").strip()[-1:] or ""
    if "가" <= ch <= "힣":
        return with_final if (ord(ch) - 0xAC00) % 28 else without_final
    return f"{with_final}({without_final})"


def _i(v):
    return None if v is None else int(round(float(v)))


def facts(c: dict, lang: str = "ko") -> dict:
    """LLM 요약용 압축 사실(숫자는 이것만 쓴다) — 기온은 카드처럼 정수로 / compact facts for the LLM summary (the only numbers
    it may use); temperatures are integers like the card."""
    return {
        "location": c["location"],
        "now": {"temp": _i(c["now"]["t"]), "sky": label(c["now"]["code"], lang)},
        "days": [{"day": _dow(x["date"], lang), "date": x["date"], "sky": label(x["code"], lang),
                  "max": _i(x["max"]), "min": _i(x["min"]), "rain_chance": x["pop"]} for x in c["days"]],
        "focus_day_index": c.get("selected", 0),
    }


def _n(v) -> str:
    return "-" if v is None else str(int(round(float(v))))


def template(c: dict, lang: str = "ko", week: bool = False) -> str:
    """LLM 이 없을 때의 결정적 요약 / the deterministic summary when the LLM is unavailable."""
    days = c.get("days") or []
    if not days:
        return ("No forecast was returned." if lang == "en" else "예보 정보를 받지 못했습니다.")
    loc = c["location"]
    if week:
        wet = [_dow(x["date"], lang) for x in days if icon(x["code"]) in WET_ICONS or (x.get("pop") or 0) >= 60]
        hi = [x["max"] for x in days if x["max"] is not None]
        lo = [x["min"] for x in days if x["min"] is not None]
        rng = f"{_n(min(lo))}~{_n(max(hi))}°C" if hi and lo else "-"
        if lang == "en":
            rain = (f"rain or snow is likely on {', '.join(wet)}" if wet else "no rain is expected")
            rng_en = f"from {_n(min(lo))} to {_n(max(hi))}°C" if hi and lo else "unavailable"
            return f"This week in {loc}, {rain}, with temperatures {rng_en}."
        rain = (f"{'·'.join(wet)}요일에 비나 눈 소식이 있고" if wet else "뚜렷한 비 소식 없이")
        return f"이번 주 {loc}{josa(loc, '은', '는')} {rain}, 기온은 {rng} 사이예요."
    i = c.get("selected", 0) if c.get("selected", 0) < len(days) else 0
    x = days[i]
    if lang == "en":
        when = "Today" if i == 0 else ("Tomorrow" if i == 1 else _dow(x["date"], "en"))
        now = f" It is {_n(c['now']['t'])}°C now." if i == 0 and c["now"].get("t") is not None else ""
        return (f"{when} in {loc}: {label(x['code'], 'en').lower()}, high {_n(x['max'])}° / low {_n(x['min'])}°, "
                f"{x.get('pop') or 0}% chance of precipitation.{now}")
    when = "오늘" if i == 0 else ("내일" if i == 1 else _dow(x["date"], "ko") + "요일")
    now = f" 지금은 {_n(c['now']['t'])}°C예요." if i == 0 and c["now"].get("t") is not None else ""
    return (f"{when} {loc}{josa(loc, '은', '는')} {label(x['code'])}, 최고 {_n(x['max'])}° · 최저 {_n(x['min'])}°, "
            f"강수 확률 {x.get('pop') or 0}%예요.{now}")
