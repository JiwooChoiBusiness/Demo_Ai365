"""채팅 실시간 위젯 가로채기(2026-10-06) — 감지 · 추출 · 답변 이벤트 · 저장 meta · 파이프라인 순서(LLM · 네트워크 없음).
Chat live-widget interception (2026-10-06) — detection, extraction, answer events, saved meta and pipeline order (no LLM, no network)."""
import asyncio
import json
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

from db_fixture import isolate_db

from app import live_fx, live_places, live_usage, live_weather, live_widgets as lw, pipeline
from app.agents import AGENT_REGISTRY


async def collect(stream):
    return [event async for event in stream]


def _weather_card(selected=0):
    days = [{"date": f"2026-10-{6 + i:02d}", "max": 22.0 + i, "min": 11.0, "code": 2, "pop": 10} for i in range(7)]
    return {"kind": "weather", "v": 1, "location": "서울", "fetched_at": "2026-10-06T16:50:00+09:00",
            "now": {"t": 19.5, "code": 2}, "days": days, "hourly": {"time": [], "t": [], "pop": [], "code": []},
            "selected": selected, "source": dict(live_weather.SOURCE)}


ITEM = {"id": "ChIJabcdefgh1234", "name": "스시이안앤 선릉역점", "cat": "일본 음식점", "rating": 5, "count": 320,
        "price": "₩10,000~20,000", "lat": 37.5, "lng": 127.0, "addr": "강남구", "phone": "050-1", "web": "",
        "maps": "", "dir": "", "open": None, "photo": None}


class GateTests(unittest.TestCase):
    def test_gate_and_exclusions(self):
        cases = {
            "이번주 서울 날씨 알려줘": ["weather"], "내일 비 와?": ["weather"], "우산 챙겨야 해?": ["weather"],
            "지금 기준 달러 환율 알려줘": ["fx"], "엔화 얼마야": ["fx"], "100달러 원화로": ["fx"], "1만원은 몇 달러야": ["fx"],
            "선릉역 근처 맛집 알려줘": ["places"], "강남 카페 추천해줘": ["places"], "서울시청 지도로 보여줘": ["places"],
            # 다른 작업 · 사내 자료가 섞이면 가로채지 않는다 / mixed work or internal material is never intercepted
            "서울 날씨 알려주고 김민준에게 메일로 보내줘": [], "날씨 데이터 분석해줘": [], "환율 규정 알려줘": [],
            "달러 매출 보고서 만들어줘": [], "회의실 근처 카페": [], "사내 식당 메뉴": [], "인사 규정 어디 있어?": [],
            "내일 일정 알려줘": [], "날씨 API 연결해줘": [],
            # 다른 낱말 속 비 · 엔, 회사 안 장소, 카페테리아 (2026-10-06 리뷰) / 비 and 엔 inside words, in-company places, cafeterias
            "설비가 고장났어": [], "준비가 되면 알려줘": [], "구내식당 메뉴 알려줘": [], "본사 근처 주차장 있어?": [],
            "카페테리아 운영시간": [], "김민준 자리 위치 알려줘": [],
            # 놓치던 질문 / questions that used to be missed
            "오늘 서울 몇 도야": ["weather"], "1달러에 얼마야": ["fx"],
        }
        for msg, want in cases.items():
            self.assertEqual(lw.gate(msg), want, msg)

    def test_rule_extraction(self):
        r = lw._rules_extract("이번주 서울 날씨 알려줘", ["weather"], None)
        self.assertEqual((r["location"], r["day"], r["week"]), ("서울", 0, True))
        self.assertEqual(lw._rules_extract("내일 부산 날씨는?", ["weather"], None)["day"], 1)
        self.assertEqual(lw._rules_extract("100달러 원화로", ["fx"], None), {"kind": "fx", "base": "USD", "quote": "KRW", "amount": 100.0})
        self.assertEqual(lw._rules_extract("1만원은 몇 달러야", ["fx"], None), {"kind": "fx", "base": "KRW", "quote": "USD", "amount": 10000.0})
        self.assertEqual(lw._rules_extract("홍콩달러 환율", ["fx"], None)["base"], "HKD")
        p = lw._rules_extract("선릉역 근처 맛집 알려줘", ["places"], None)
        self.assertEqual((p["query"], p["area"]), ("선릉역 근처 맛집", "선릉역"))
        # 후속: 단서가 없으면 이어받지 않는다 / follow-ups need a cue
        prev = {"kind": "weather", "location": "부산"}
        self.assertEqual(lw._rules_extract("내일은?", [], prev), {"kind": "weather", "location": "부산", "day": 1, "week": False})
        self.assertIsNone(lw._rules_extract("고마워", [], prev))
        pend = {"kind": "places", "what": "맛집", "pending": True}
        self.assertEqual(lw._rules_extract("선릉역", [], pend), {"kind": "places", "area": "선릉역", "query": "선릉역 맛집"})
        self.assertIsNone(lw._rules_extract("아니야 됐어", [], pend))


class DetectTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        self.rows = []
        self.stack.enter_context(patch("app.db.list_messages", side_effect=lambda cid: self.rows))

    def _llm_down(self):
        return patch("app.llm.generate", side_effect=RuntimeError("429 RESOURCE_EXHAUSTED"))

    def _pending(self, minutes_ago=1):
        from datetime import timedelta
        from app import kst
        at = (kst.now() - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
        self.rows = [{"role": "assistant", "content": "어느 지역 근처를 찾을까요?", "created_at": at,
                      "meta": {"live_pending": {"kind": "places", "what": "맛집"}}}]

    def test_rules_fallback_only_accepts_concrete_values(self):
        # LLM 이 막혀도 평범한 질문을 위젯으로 가로채지 않는다(2026-10-06 리뷰) / ordinary questions are not hijacked when the LLM is down
        with self._llm_down():
            for msg in ("설비가 고장났어", "준비가 되면 알려줘", "구내식당 메뉴 알려줘", "본사 근처 주차장 있어?", "카페테리아 운영시간",
                        "김민준 자리 위치 알려줘", "단위 환산해줘 5km를 마일로", "비 와?", "강남 근처 주차장"):
                self.assertIsNone(lw.detect("c1", msg), msg)
            self.assertEqual(lw.detect("c1", "오늘 서울 몇 도야")["location"], "서울")
            self.assertEqual(lw.detect("c1", "1달러에 얼마야")["base"], "USD")
            self.assertEqual(lw.detect("c1", "선릉역 근처 맛집 알려줘")["area"], "선릉역")
            self.assertEqual(lw.detect("c1", "서울시청 지도로 보여줘")["area"], "서울시청")

    def test_area_question_takes_only_an_area_and_expires(self):
        self._pending()
        with patch("app.llm.generate", side_effect=AssertionError("no LLM for non-area replies")):
            for msg in ("연차 신청 방법", "김민준 연락처", "오늘 뭐 먹지", "아니야 됐어"):
                self.assertIsNone(lw.detect("c1", msg), msg)
        with self._llm_down():
            self.assertEqual(lw.detect("c1", "선릉역"), {"kind": "places", "area": "선릉역", "query": "선릉역 맛집"})
        self._pending(minutes_ago=120)   # 오래된 되묻기는 잇지 않는다 / a stale area question is not continued
        with patch("app.llm.generate", side_effect=AssertionError("no LLM")):
            self.assertIsNone(lw.detect("c1", "선릉역"))

    def test_weather_follow_ups_must_only_change_the_day_or_place(self):
        self.rows = [{"role": "assistant", "content": "…", "created_at": "2026-10-06T17:00:00",
                      "meta": {"live": {"kind": "weather", "location": "서울"}}}]
        with patch("app.llm.generate", side_effect=AssertionError("no LLM for unrelated replies")):
            for msg in ("주말에 뭐 할까", "월요일에 보자", "내일 출근해?", "고마워"):
                self.assertIsNone(lw.detect("c1", msg), msg)
        with self._llm_down():
            self.assertEqual(lw.detect("c1", "부산은?")["location"], "부산")
            self.assertEqual(lw.detect("c1", "내일은 어때?")["day"], 1)

    def test_llm_result_is_used_and_none_falls_through(self):
        with patch("app.llm.generate", return_value={"kind": "weather", "location": "제주", "day": 2, "week": False}) as gen:
            hit = lw.detect("c1", "모레 제주 날씨 어때?")
        self.assertEqual((hit["kind"], hit["location"], hit["day"]), ("weather", "제주", 2))
        self.assertEqual(gen.call_args.args[4] if len(gen.call_args.args) > 4 else gen.call_args.kwargs.get("tier"), "lite")
        with patch("app.llm.generate", return_value={"kind": "none"}):
            self.assertIsNone(lw.detect("c1", "날씨 같은 기분이야"))

    def test_llm_failure_falls_back_to_rules(self):
        with patch("app.llm.generate", side_effect=RuntimeError("429")):
            hit = lw.detect("c1", "엔화 환율")
        self.assertEqual((hit["kind"], hit["base"]), ("fx", "JPY"))

    def test_unrelated_messages_never_call_the_llm(self):
        with patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")):
            for msg in ("인사 규정 알려줘", "2분기 매출 분석해줘", "서울 날씨 알려주고 메일로 보내줘", "안녕하세요 오늘 회의 몇 시야?"):
                self.assertIsNone(lw.detect("c1", msg))

    def test_short_follow_up_after_a_widget_answer(self):
        self.rows = [{"role": "user", "content": "서울 날씨", "meta": None},
                     {"role": "assistant", "content": "…", "meta": {"live": {"kind": "weather", "location": "서울"}}},
                     {"role": "user", "content": "내일은?", "meta": None}]
        with patch("app.llm.generate", side_effect=RuntimeError("down")):
            hit = lw.detect("c1", "내일은?")
        self.assertEqual((hit["kind"], hit["location"], hit["day"]), ("weather", "서울", 1))
        self.rows[1]["meta"] = {"source": "사내"}                               # 위젯이 아니면 이어받지 않는다 / not a widget answer
        with patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")):
            self.assertIsNone(lw.detect("c1", "내일은?"))


class AnswerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        self.saved = []

        def add_message(chat_id, role, content, meta=None):
            self.saved.append({"role": role, "content": content, "meta": meta})
            return "m_test"
        self.stack.enter_context(patch("app.db.add_message", side_effect=add_message))
        self.stack.enter_context(patch("app.answers._smooth", side_effect=self._one))
        self.stack.enter_context(patch("app.llm.generate", side_effect=RuntimeError("no LLM in tests")))

    @staticmethod
    async def _one(text):
        yield text

    async def test_weather_answer_streams_and_saves_the_full_card(self):
        with patch.object(live_weather, "get", return_value=(_weather_card(1), True)):
            ev = await collect(lw.answer({"id": "c1"}, {"kind": "weather", "location": "서울", "day": 1}, "내일 서울 날씨 알려줘"))
        self.assertEqual([e["type"] for e in ev], ["thinking", "answer_head", "token", "done"])
        self.assertEqual(ev[1]["source"], "외부")
        self.assertEqual(ev[2]["text"], "내일 서울은 구름 많음, 최고 23° · 최저 11°, 강수 확률 10%예요.")   # LLM 실패 → 템플릿 / template
        self.assertEqual(ev[-1]["cards"][0]["kind"], "weather")
        self.assertEqual(ev[-1]["sources"]["external"][0]["title"], "Open-Meteo")
        meta = self.saved[0]["meta"]
        self.assertEqual((meta["cards"][0]["selected"], meta["live"]), (1, {"kind": "weather", "location": "서울"}))

    async def test_places_saves_only_ids_and_sends_the_full_card_live(self):
        res = {"items": [ITEM], "next": "tok"}
        with patch.object(live_places, "search", return_value=res):
            ev = await collect(lw.answer({"id": "c1"}, {"kind": "places", "query": "선릉역 맛집", "area": "선릉역"}, "선릉역 근처 맛집 알려줘"))
        live = ev[-1]["cards"][0]
        self.assertEqual((live["items"][0]["name"], live["next"]), ("스시이안앤 선릉역점", "tok"))
        saved = self.saved[0]["meta"]["cards"][0]
        self.assertEqual(saved, {"kind": "places", "v": 1, "query": "선릉역 맛집", "area": "선릉역", "lang": "ko",
                                 "ids": ["ChIJabcdefgh1234"], "count": 1})
        # 결과가 1곳이어도 저장 글에 구글 장소 이름을 쓰지 않는다 / no Google place name in the stored text, even for one result
        self.assertNotIn("스시", self.saved[0]["content"])
        self.assertEqual(self.saved[0]["content"], "‘선릉역 맛집’ 검색 결과 1곳을 지도에 표시했어요. 장소를 누르면 영업시간과 후기를 볼 수 있어요.")
        self.assertNotIn("스시", json.dumps(self.saved[0]["meta"], ensure_ascii=False))
        self.assertIn("지도에 표시했어요", self.saved[0]["content"])

    async def test_places_without_an_area_asks_back(self):
        with patch.object(live_places, "search", side_effect=AssertionError("must not search")):
            ev = await collect(lw.answer({"id": "c1"}, {"kind": "places", "query": "근처 맛집", "area": None}, "근처 맛집 알려줘"))
        self.assertNotIn("cards", ev[-1])
        self.assertIn("어느 지역", ev[2]["text"])
        self.assertEqual(self.saved[0]["meta"]["live_pending"], {"kind": "places", "what": "맛집"})

    async def test_quota_and_errors_answer_without_a_card(self):
        with patch.object(live_places, "search", side_effect=live_usage.QuotaExceeded("places_search")):
            ev = await collect(lw.answer({"id": "c1"}, {"kind": "places", "query": "선릉역 맛집", "area": "선릉역"}, "선릉역 맛집"))
        self.assertIn("무료 사용량", ev[2]["text"])
        self.assertNotIn("cards", ev[-1])
        with patch.object(live_fx, "quote", side_effect=live_fx.FxError("down")):
            ev = await collect(lw.answer({"id": "c1"}, {"kind": "fx", "base": "USD"}, "달러 환율"))
        self.assertIn("환율 정보를 가져오지 못했습니다", ev[2]["text"])

    async def test_english_question_gets_an_english_answer(self):
        card = {"kind": "fx", "v": 1, "base": {"code": "USD", "amount": 1.0}, "quote": {"code": "KRW", "amount": 1341.26},
                "rate": 1341.26, "unit": 1, "as_of": "2026-10-06T16:41:00+09:00", "fetched_at": "2026-10-06T16:41:05+09:00",
                "source": dict(live_fx.SOURCE)}
        with patch.object(live_fx, "quote", return_value=card):
            ev = await collect(lw.answer({"id": "c1"}, {"kind": "fx", "base": "USD"}, "What is the dollar exchange rate?"))
        self.assertEqual(ev[0]["text"], "Checking the exchange rate")
        self.assertTrue(ev[2]["text"].startswith("As of now, 1 US dollar (USD) ≈ 1,341.26 South Korean won (KRW)."))


class PipelineOrderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        self.stack.enter_context(patch("app.llm.stream", side_effect=AssertionError("unexpected stream")))
        self.stack.enter_context(patch("app.db.add_message", return_value="m_test"))
        self.stack.enter_context(patch("app.db.list_messages", return_value=[]))
        self.stack.enter_context(patch.object(pipeline, "_resolve_eff", return_value=None))
        self.stack.enter_context(patch.object(pipeline, "_build_context", side_effect=lambda cid, msg, lane="chat": [{"role": "user", "content": msg}]))
        self.stack.enter_context(patch.object(pipeline, "_await_send_state", return_value=None))
        self.stack.enter_context(patch("app.answers._smooth", side_effect=AnswerTests._one))
        for name in AGENT_REGISTRY:
            self.stack.enter_context(patch.dict(AGENT_REGISTRY[name], {"run": AsyncMock(return_value={"status": "answer", "text": name, "extras": {}})}))
        self.stack.enter_context(patch.object(live_weather, "get", return_value=(_weather_card(), True)))

    async def test_widget_runs_before_intent_planning_in_both_scopes(self):
        with patch("app.llm.generate", return_value={"kind": "weather", "location": "서울", "day": 0}), \
             patch.object(pipeline, "_judge_intent", side_effect=AssertionError("planner must not run")), \
             patch.object(pipeline, "_run_external", side_effect=AssertionError("web must not run")):
            for scope in ("사내", "외부", "자동"):
                ev = await collect(pipeline.run_pipeline({"id": "c"}, "서울 날씨 알려줘", scope))
                self.assertEqual(ev[-1]["type"], "done", scope)
                self.assertEqual(ev[-1]["cards"][0]["kind"], "weather")

    async def test_explore_lane_and_resume_skip_widgets(self):
        with patch.object(lw, "detect", side_effect=AssertionError("detect must not run")), \
             patch.object(pipeline, "_judge_intent", return_value={"route": ["knowledge"]}), \
             patch.object(pipeline, "_aggregate_answer", self._stub):
            await collect(pipeline.run_pipeline({"id": "c"}, "서울 날씨 알려줘", "사내", execution_lane="explore"))

    async def test_an_explicit_internal_pick_skips_widgets_but_groupware_only_does_not(self):
        with patch.object(lw, "detect", side_effect=AssertionError("detect must not run")), \
             patch.object(pipeline, "_judge_intent", return_value={"route": ["knowledge"]}) as judge, \
             patch.object(pipeline, "_aggregate_answer", self._stub):
            await collect(pipeline.run_pipeline({"id": "c"}, "서울 날씨 알려줘", "사내", agents=["knowledge"]))
            await collect(pipeline.run_pipeline({"id": "c"}, "달러 환율 보여줘", "사내", scope_files={"data_tables": ["fx_rates"]}))
        self.assertEqual(judge.call_count, 2)
        with patch("app.llm.generate", return_value={"kind": "weather", "location": "서울", "day": 0}), \
             patch.object(pipeline, "_judge_intent", side_effect=AssertionError("planner must not run")):
            ev = await collect(pipeline.run_pipeline({"id": "c"}, "서울 날씨 알려줘", "사내", agents=["groupware"]))
        self.assertEqual(ev[-1]["cards"][0]["kind"], "weather")   # 홈 'AI 질문'(그룹웨어 프리셋) / the home question preset

    async def test_mixed_requests_reach_the_planner(self):
        with patch("app.llm.generate", side_effect=AssertionError("widget LLM must not run")), \
             patch.object(pipeline, "_judge_intent", return_value={"route": ["knowledge"]}) as judge, \
             patch.object(pipeline, "_aggregate_answer", self._stub):
            await collect(pipeline.run_pipeline({"id": "c"}, "서울 날씨 알려주고 김민준에게 메일로 보내줘", "사내"))
        judge.assert_called_once()

    @staticmethod
    async def _stub(*args, **kwargs):
        yield {"type": "answer_head", "source": "사내"}
        yield {"type": "done", "message_id": "x"}


if __name__ == "__main__":
    unittest.main()
