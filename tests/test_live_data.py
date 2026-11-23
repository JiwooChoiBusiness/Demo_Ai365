"""채팅 실시간 위젯 데이터 공급자(2026-10-06) — Open-Meteo · yfinance · 구글 Places 를 가짜 전송으로 검증한다(네트워크 없음).
Chat live-widget data providers (2026-10-06) — Open-Meteo, yfinance and Google Places checked with fake transports (no network)."""
import json
import os
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from unittest.mock import patch

import httpx

from db_fixture import isolate_db

from app import kst, live_fx, live_places, live_usage, live_weather


def _clock(iso_utc: str):
    """kst._clock 을 고정 UTC 시각으로 / pin kst._clock to a fixed UTC instant."""
    t = datetime.fromisoformat(iso_utc).replace(tzinfo=timezone.utc)
    return patch.object(kst, "_clock", lambda: t)


def _forecast_fixture(start="2026-10-06"):
    days = [f"2026-10-{6 + i:02d}" for i in range(7)]
    hours = [f"{d}T{h:02d}:00" for d in days for h in range(24)]
    return {
        "current": {"time": f"{start}T16:45", "temperature_2m": 19.46, "weather_code": 2,
                    "apparent_temperature": 17.4, "relative_humidity_2m": 53},
        "daily": {"time": days, "temperature_2m_max": [22.5, 23.1, 24.0, 21.2, 20.0, 19.5, 18.4],
                  "temperature_2m_min": [10.0, 11.2, 12.5, 13.0, 12.1, 11.4, 10.2],
                  "weather_code": [0, 2, 61, 80, 3, 95, 1], "precipitation_probability_max": [0, 10, 70, 60, 20, 80, 5]},
        "hourly": {"time": hours, "temperature_2m": [15 + (i % 24) / 3 for i in range(168)],
                   "precipitation_probability": [i % 100 for i in range(168)], "weather_code": [2] * 168},
    }


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)

    def test_take_counts_until_the_limit_then_refuses(self):
        with patch.dict(live_usage.LIMITS, {"places_search": (2, "t")}):
            self.assertTrue(live_usage.try_take("places_search"))
            self.assertTrue(live_usage.try_take("places_search"))
            self.assertFalse(live_usage.try_take("places_search"))      # 한도 초과는 올리지 않는다 / no increment past the limit
            with self.assertRaises(live_usage.QuotaExceeded):
                live_usage.take("places_search")
        used = {i["sku"]: i["used"] for i in live_usage.stats()["items"]}
        self.assertEqual(used["places_search"], 2)

    def test_counts_reset_with_the_kst_month(self):
        with patch.dict(live_usage.LIMITS, {"geocode": (1, "t")}):
            with _clock("2026-10-31T14:30:00"):                            # KST 23:30 10월 / 23:30 on Oct 31 KST
                self.assertTrue(live_usage.try_take("geocode"))
                self.assertFalse(live_usage.try_take("geocode"))
            with _clock("2026-10-31T15:30:00"):                            # KST 11월 1일 00:30 / Nov 1 00:30 KST
                self.assertEqual(live_usage.stats()["month"], "2026-11")
                self.assertTrue(live_usage.try_take("geocode"))

    def test_limits_stay_at_ninety_percent_of_googles_free_tier(self):
        self.assertEqual({k: v[0] for k, v in live_usage.LIMITS.items()},
                         {"places_search": 900, "places_detail": 900, "places_photo": 900, "geocode": 9000, "map_load": 9000})


class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        live_weather._geo_cache.clear()
        live_weather._fc_cache.clear()
        self.addCleanup(live_weather._geo_cache.clear)
        self.addCleanup(live_weather._fc_cache.clear)
        self.calls = []
        self.geo = {"부산": [{"name": "부산", "latitude": 35.1, "longitude": 129.04, "population": 3400000}]}
        self.google = {}

        def handler(req: httpx.Request):
            self.calls.append(req)
            if req.url.host == "geocoding-api.open-meteo.com":
                name = req.url.params["name"]
                korea = req.url.params.get("countryCode") == "KR"
                hits = self.geo.get(name, []) if korea or name in self.geo else []
                return httpx.Response(200, json={"results": hits} if hits else {})
            if req.url.host == "api.open-meteo.com":
                return httpx.Response(200, json=_forecast_fixture())
            if req.url.host == "maps.googleapis.com":
                hit = self.google.get(req.url.params["address"])
                return httpx.Response(200, json={"results": [{"geometry": {"location": hit}}]} if hit else {"results": []})
            return httpx.Response(404)
        self.stack.enter_context(patch.object(live_weather, "TRANSPORT", httpx.MockTransport(handler)))
        self.stack.enter_context(patch.dict(os.environ, {"GOOGLE_MAPS_SERVER_KEY": "test-key"}))

    def test_card_is_normalized_without_coordinates_and_in_kst(self):
        with _clock("2026-10-06T07:50:00"):
            card, found = live_weather.get("부산", 1)
        self.assertTrue(found)
        self.assertEqual((card["kind"], card["location"], card["selected"]), ("weather", "부산", 1))
        self.assertEqual(card["fetched_at"], "2026-10-06T16:50:00+09:00")
        self.assertEqual(len(card["days"]), 7)
        self.assertEqual(card["days"][2], {"date": "2026-10-08", "max": 24.0, "min": 12.5, "code": 61, "pop": 70})
        self.assertEqual(len(card["hourly"]["time"]), 168)
        self.assertEqual(card["now"]["t"], 19.5)
        self.assertNotIn("lat", json.dumps(card))                         # 좌표는 저장하지 않는다 / no coordinates stored
        fc = [c for c in self.calls if c.url.host == "api.open-meteo.com"][0]
        self.assertEqual((fc.url.params["timezone"], fc.url.params["forecast_days"]), ("Asia/Seoul", "7"))

    def test_unknown_names_go_to_google_then_fall_back_to_seoul(self):
        self.google["선릉역"] = {"lat": 37.5045, "lng": 127.049}
        _, found = live_weather.get("선릉역")
        self.assertTrue(found)
        used = {i["sku"]: i["used"] for i in live_usage.stats()["items"]}
        self.assertEqual(used["geocode"], 1)                                 # 구글 지오코딩은 사용량에 잡힌다 / counted
        card, found = live_weather.get("없는동네")
        self.assertFalse(found)
        self.assertEqual(card["location"], "서울")

    def test_google_geocoding_errors_never_log_the_key(self):
        # 키가 주소(URL)에 실리는 구글 Geocoding 이 403 이어도 로그에는 상태 코드만 / a 403 logs only the status, never the URL or key
        def handler(req):
            if req.url.host == "maps.googleapis.com":
                return httpx.Response(403, json={"error_message": "The provided API key is invalid."})
            return httpx.Response(200, json={})
        self.stack.enter_context(patch.object(live_weather, "TRANSPORT", httpx.MockTransport(handler)))
        with self.assertLogs("app.live_weather", level="WARNING") as logs:
            card, found = live_weather.get("어딘가없는곳")
        self.assertFalse(found)
        self.assertNotIn("test-key", "\n".join(logs.output))
        self.assertIn("HTTP 403", "\n".join(logs.output))

    def test_forecast_is_cached_for_ten_minutes(self):
        live_weather.get("부산")
        live_weather.get("부산")
        self.assertEqual(len([c for c in self.calls if c.url.host == "api.open-meteo.com"]), 1)

    def test_service_errors_raise_weather_error(self):
        self.stack.enter_context(patch.object(live_weather, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(503))))
        live_weather._fc_cache.clear()
        with self.assertRaises(live_weather.WeatherError):
            live_weather.forecast(35.1, 129.0)

    def test_templates_and_labels(self):
        card = live_weather.card("서울", _forecast_fixture(), 1)
        self.assertEqual(live_weather.template(card, "ko"), "내일 서울은 구름 많음, 최고 23° · 최저 11°, 강수 확률 10%예요.")
        # 10/8(목) 비 · 10/9(금) 소나기 · 10/11(일) 뇌우 / Thu rain, Fri showers, Sun thunderstorm
        self.assertIn("목·금·일요일에 비나 눈 소식", live_weather.template(card, "ko", week=True))
        self.assertTrue(live_weather.template(card, "en", week=True).startswith("This week in 서울, rain or snow is likely on Thu"))
        self.assertEqual((live_weather.josa("부산", "은", "는"), live_weather.josa("제주", "은", "는")), ("은", "는"))
        self.assertEqual((live_weather.icon(95), live_weather.label(81, "en"), live_weather.label(80)), ("thunder", "Showers", "약한 소나기"))


class FxTests(unittest.TestCase):
    def setUp(self):
        live_fx._cache.clear()
        self.addCleanup(live_fx._cache.clear)
        self.asked = []
        ts = datetime(2026, 10, 6, 7, 41, tzinfo=timezone.utc).timestamp()   # KST 16:41

        def fetch(symbol):
            self.asked.append(symbol)
            return {"KRW=X": 1341.26, "JPY=X": 158.143, "EUR=X": 0.8902}[symbol], ts
        patcher = patch.object(live_fx, "_FETCH", fetch)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_usd_to_krw_with_kst_as_of(self):
        c = live_fx.quote("USD", "KRW")
        self.assertEqual((c["base"], c["quote"]["code"], c["as_of"]), ({"code": "USD", "amount": 1.0}, "KRW", "2026-10-06T16:41:00+09:00"))
        self.assertAlmostEqual(c["quote"]["amount"], 1341.26, places=4)
        self.assertEqual(live_fx.text(c, "ko"), "현재 기준으로 1달러(USD) ≈ 1,341.26원(KRW) 입니다.\n2026년 10월 6일 16:41 KST 기준 환율입니다.")
        self.assertEqual(live_fx.text(c, "en"), "As of now, 1 US dollar (USD) ≈ 1,341.26 South Korean won (KRW).\nRate as of Oct 6, 2026 16:41 KST.")

    def test_yen_is_per_hundred_and_uses_the_usd_cross(self):
        c = live_fx.quote("JPY")
        self.assertEqual(c["base"]["amount"], 100.0)
        self.assertAlmostEqual(c["quote"]["amount"], 100 * 1341.26 / 158.143, places=4)
        self.assertTrue(live_fx.text(c, "ko").startswith("현재 기준으로 100엔(JPY) ≈ 848.13원(KRW)"))

    def test_won_to_dollar_and_cache(self):
        c = live_fx.quote("KRW", "USD", 10000)
        self.assertAlmostEqual(c["quote"]["amount"], 10000 / 1341.26, places=4)
        self.assertIn("10,000원(KRW) ≈ 7.46달러(USD)", live_fx.text(c, "ko"))
        live_fx.quote("USD", "KRW")
        self.assertEqual(self.asked.count("KRW=X"), 1)                        # 60초 캐시 / cached for 60 s

    def test_failures_and_unknown_currencies(self):
        with self.assertRaises(live_fx.FxError):
            live_fx.quote("XYZ", "KRW")
        live_fx._cache.clear()
        with patch.object(live_fx, "_FETCH", side_effect=RuntimeError("429 Too Many Requests")):
            with self.assertRaises(live_fx.FxError):
                live_fx.quote("USD", "KRW")


PLACE = {
    "id": "ChIJabcdefgh1234", "displayName": {"text": "스시이안앤 선릉역점"}, "primaryTypeDisplayName": {"text": "일본 음식점"},
    "rating": 5, "userRatingCount": 320,
    "priceRange": {"startPrice": {"currencyCode": "KRW", "units": "10000"}, "endPrice": {"currencyCode": "KRW", "units": "20000"}},
    "location": {"latitude": 37.505, "longitude": 127.05}, "shortFormattedAddress": "강남구 선릉로86길 10",
    "nationalPhoneNumber": "050-71365-1134", "googleMapsLinks": {"directionsUri": "https://maps.google.com/dir", "placeUri": "https://maps.google.com/p"},
    "currentOpeningHours": {"openNow": True, "nextCloseTime": "2026-10-06T13:00:00Z"},
    "photos": [{"name": "places/ChIJabcdefgh1234/photos/AUc7abcdefgh", "authorAttributions": [{"displayName": "김사진", "uri": "https://maps.google.com/u"}]}],
}


class PlacesTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        self.stack.enter_context(patch.dict(os.environ, {"GOOGLE_MAPS_SERVER_KEY": "secret-key-123"}))
        self.calls = []

        def handler(req: httpx.Request):
            self.calls.append(req)
            if req.url.path == "/v1/places:searchText":
                return httpx.Response(200, json={"places": [PLACE], "nextPageToken": "tok2"})
            if req.url.path.endswith("/media"):
                return httpx.Response(200, json={"photoUri": "https://lh3.googleusercontent.com/x"})
            if req.url.path.startswith("/v1/places/"):
                return httpx.Response(200, json={**PLACE, "formattedAddress": "대한민국 서울특별시 강남구 선릉로86길 10 2층",
                                                 "regularOpeningHours": {"weekdayDescriptions": ["월요일: 오전 11:00~오후 9:00", "화요일: 휴무일"]},
                                                 "reviews": [{"rating": 5, "relativePublishTimeDescription": "2주 전", "text": {"text": f"후기 {i}"},
                                                              "authorAttribution": {"displayName": f"작성자{i}", "uri": "https://maps.google.com/c", "photoUri": "https://lh3/a"}}
                                                             for i in range(5)]})
            return httpx.Response(404)
        self.stack.enter_context(patch.object(live_places, "TRANSPORT", httpx.MockTransport(handler)))

    def test_search_stays_on_the_enterprise_sku_and_normalizes(self):
        with _clock("2026-10-06T07:50:00"):
            res = live_places.search("선릉역 맛집", "ko")
        req = self.calls[0]
        mask = req.headers["X-Goog-FieldMask"]
        self.assertNotIn("reviews", mask)                                       # 후기 빼고 Enterprise / no reviews
        self.assertNotIn("editorialSummary", mask)
        self.assertEqual(json.loads(req.content), {"textQuery": "선릉역 맛집", "languageCode": "ko", "regionCode": "KR", "pageSize": 10})
        it = res["items"][0]
        self.assertEqual((it["name"], it["cat"], it["price"], it["dir"]), ("스시이안앤 선릉역점", "일본 음식점", "₩10,000~20,000", "https://maps.google.com/dir"))
        self.assertEqual(it["open"], {"now": True, "label": "영업 중 · 오후 10:00에 영업 종료"})
        self.assertEqual(it["photo"], {"name": "places/ChIJabcdefgh1234/photos/AUc7abcdefgh", "author": "김사진", "author_uri": "https://maps.google.com/u"})
        self.assertEqual(res["next"], "tok2")
        live_places.search("선릉역 맛집", "ko", page="tok2")
        self.assertEqual(json.loads(self.calls[1].content)["pageToken"], "tok2")

    def test_detail_returns_hours_and_three_attributed_reviews(self):
        d = live_places.detail("ChIJabcdefgh1234", "ko")
        self.assertIn("reviews", self.calls[0].headers["X-Goog-FieldMask"])
        self.assertEqual(d["hours"], [{"day": "월요일", "time": "오전 11:00~오후 9:00"}, {"day": "화요일", "time": "휴무일"}])
        self.assertEqual([r["author"] for r in d["reviews"]], ["작성자0", "작성자1", "작성자2"])
        self.assertEqual(d["addr_full"], "대한민국 서울특별시 강남구 선릉로86길 10 2층")
        with self.assertRaises(ValueError):
            live_places.detail("../../etc", "ko")

    def test_photo_returns_only_the_uri_and_validates_the_name(self):
        out = live_places.photo("places/ChIJabcdefgh1234/photos/AUc7abcdefgh", 480)
        self.assertEqual(out, {"uri": "https://lh3.googleusercontent.com/x"})
        self.assertEqual((self.calls[0].url.params["skipHttpRedirect"], self.calls[0].url.params["maxWidthPx"]), ("true", "480"))
        with self.assertRaises(ValueError):
            live_places.photo("https://evil.example/x", 480)
        self.assertEqual(len(self.calls), 1)                                    # 잘못된 이름은 호출하지 않는다 / no call for bad names

    def test_quota_and_missing_key_stop_before_any_call(self):
        with patch.dict(live_usage.LIMITS, {"places_search": (0, "t")}):
            with self.assertRaises(live_usage.QuotaExceeded):
                live_places.search("선릉역 맛집")
        with patch.dict(os.environ, {"GOOGLE_MAPS_SERVER_KEY": ""}):
            with self.assertRaises(live_places.NoKey):
                live_places.search("선릉역 맛집")
            with self.assertRaises(live_places.NoKey):
                live_places.photo("places/ChIJabcdefgh1234/photos/AUc7abcdefgh", 480)
        self.assertEqual(self.calls, [])
        used = {i["sku"]: i["used"] for i in live_usage.stats()["items"]}
        self.assertEqual((used["places_search"], used["places_photo"]), (0, 0))   # 키가 없으면 세지 않는다 / no key, no count

    def test_errors_never_echo_the_key(self):
        self.stack.enter_context(patch.object(live_places, "TRANSPORT", httpx.MockTransport(
            lambda r: httpx.Response(403, json={"error": {"message": "API key secret-key-123 is not valid"}}))))
        with self.assertRaises(live_places.PlacesError) as cm:
            live_places.search("선릉역 맛집")
        self.assertNotIn("secret-key-123", str(cm.exception))

    def test_saved_card_keeps_only_the_query_and_ids(self):
        c = live_places.card("선릉역 맛집", "선릉역", "ko", {"items": [live_places.norm(PLACE)], "next": None})
        saved = live_places.saved(c)
        self.assertEqual(saved, {"kind": "places", "v": 1, "query": "선릉역 맛집", "area": "선릉역", "lang": "ko",
                                 "ids": ["ChIJabcdefgh1234"], "count": 1})
        self.assertNotIn("스시", json.dumps(saved, ensure_ascii=False))           # 장소 이름 · 후기는 저장하지 않는다 / no names stored

    def test_price_level_fallback_and_browser_key(self):
        self.assertEqual(live_places.price({"priceLevel": "PRICE_LEVEL_MODERATE"}), "₩₩")
        self.assertEqual(live_places.price({}), "")
        with patch.dict(os.environ, {"GOOGLE_MAPS_BROWSER_KEY": "map-key"}):
            self.assertEqual(live_places.browser_key(), "map-key")
        with patch.dict(os.environ, {"GOOGLE_MAPS_BROWSER_KEY": ""}):
            self.assertEqual(live_places.browser_key(), "secret-key-123")     # 없으면 서버 키 대체 / server key fallback
        # 지도 ID: 환경 변수가 우선, 없으면 데모 프로젝트 지도 ID(2026-10-27) / env first, else the demo project's map ID
        with patch.dict(os.environ, {"GOOGLE_MAPS_MAP_ID": ""}):
            self.assertEqual(live_places.map_id(), live_places.DEFAULT_MAP_ID)
            self.assertEqual(live_places.DEFAULT_MAP_ID, "1fd5384d963ac782387a959a")
        with patch.dict(os.environ, {"GOOGLE_MAPS_MAP_ID": "other-map-id"}):
            self.assertEqual(live_places.map_id(), "other-map-id")


if __name__ == "__main__":
    unittest.main()
