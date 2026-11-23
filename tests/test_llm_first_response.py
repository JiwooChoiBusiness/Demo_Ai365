# -*- coding: utf-8 -*-
"""첫 응답 20초 제한(2026-10-30 사용자 지시 "LLM API키 응답이 20초 동안 없으면 다음 모델로"). 티어 체인에서 다음 모델이 남은 단계는
첫 응답(stream · generate 는 첫 청크, 함수 호출 · 그라운딩은 호출 전체)이 GEMINI_FIRST_RESPONSE_SEC 를 넘으면 그 모델을 모든 키에서
쉬게 하고 바로 다음 모델로 간다. 실제 Gemini 호출은 없다(가짜 클라이언트, 제한은 0.2초로 줄여 빠르게 돈다).

The first-response limit (user instruction 2026-10-30: when a key gives no answer for 20 s, move to the next model). On tier
chains, every stage that still has a next model rests the model on every key and moves straight on once the first response
(the first chunk for stream and generate, the whole call for function calling and grounding) misses GEMINI_FIRST_RESPONSE_SEC.
No real Gemini calls (fake clients; the limit is shrunk to 0.2 s)."""
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from google.genai import errors

from app import llm

MAIN = llm.settings.GEN_MODEL_MAIN
SECOND = "test-second-model"   # 체인 가운데 모델(다음 모델이 남아 제한이 걸린다) / the middle model (still has a next one)
LAST = "test-last-model"       # 체인 마지막 모델(제한 없음) / the chain's last model (no limit)
LIMIT = 0.2                    # 줄인 첫 응답 제한(초) / the shrunken first-response limit in seconds
SLOW = 2.0                     # 제한보다 훨씬 긴 첫 응답 지연 / a first-response delay well past the limit
QUICK = 1.2                    # 제한에 걸려 넘어간 호출은 이보다 빨리 끝난다(느린 호출을 끝까지 기다리지 않았다) / a cut call ends sooner than this


def server_error(code: int = 503, status: str = "UNAVAILABLE") -> errors.APIError:
    return errors.ServerError(code, {"error": {"code": code, "message": "high demand", "status": status}}, None)


class Box:
    """한 테스트의 대본 · 기록. 대기는 release 이벤트로 하므로 테스트가 끝나면 버려진 스레드도 곧바로 끝나고, time.sleep 패치에도
    영향받지 않는다. / Scripts and records of one test. Waits use the release event, so abandoned threads end right after the test
    and time.sleep patches never touch them."""

    def __init__(self):
        self.scripts: dict[str, list] = {}   # 모델 → 호출마다 하나씩 쓰는 대본 / model → one script entry per call
        self.calls: list = []                # (모델, 키 슬롯), 호출을 시작한 순서 / (model, key slot) in the order calls started
        self.log: list = []                  # 호출 방식 · 인자 / call style and arguments
        self.closed: list = []               # 끝났거나 닫힌 스트림의 모델 / models whose stream ended or was closed
        self.streams: list = []              # (모델, 반복자): 참조를 쥐어 GC 가 대신 닫지 못하게 / references keep GC from closing them
        self.release = threading.Event()

    def pause(self, sec: float) -> None:
        if sec > 0:
            self.release.wait(sec)


class FakeModels:
    """generate_content · generate_content_stream · embed_content 가짜. 대본 한 줄 = 예외(바로 실패) 또는
    {"first": 첫 응답 전 대기, "chunks": [글 또는 예외], "gap": 청크 사이 대기}.
    Fake generate_content, generate_content_stream and embed_content. One script entry is an exception (fails at once) or
    {"first": wait before the first response, "chunks": [text or exception], "gap": wait between chunks}."""

    def __init__(self, box: Box, key: int):
        self.box, self.key = box, key

    def _take(self, model, how, contents, config):
        self.box.calls.append((model, self.key))
        self.box.log.append({"model": model, "key": self.key, "how": how, "contents": contents, "config": config})
        steps = self.box.scripts.get(model) or []
        if not steps:
            raise AssertionError(f"뜻밖의 호출 / unexpected call: {model} on key {self.key}")
        return steps.pop(0)

    def generate_content(self, model, contents, config):
        step = self._take(model, "once", contents, config)
        if isinstance(step, BaseException):
            raise step
        self.box.pause(step.get("first", 0.0))
        for item in step.get("chunks", []):
            if isinstance(item, BaseException):
                raise item
        text = "".join(step.get("chunks", ["ok"]))
        return SimpleNamespace(text=text, candidates=None, function_calls=None)

    def generate_content_stream(self, model, contents, config):
        step = self._take(model, "stream", contents, config)
        box = self.box

        def it():
            try:
                if isinstance(step, BaseException):
                    raise step
                box.pause(step.get("first", 0.0))
                for i, item in enumerate(step.get("chunks", ["ok"])):
                    if i:
                        box.pause(step.get("gap", 0.0))
                    if isinstance(item, BaseException):
                        raise item
                    yield SimpleNamespace(text=item)
            finally:
                box.closed.append(model)

        gen = it()
        box.streams.append((model, gen))
        return gen

    def embed_content(self, model, contents):
        step = self._take(model, "embed", contents, None)
        self.box.pause(step.get("first", 0.0))
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.5, 0.25]) for _ in contents])


def make_client(box: Box, keys: int = 3, chain=(MAIN, SECOND, LAST)) -> llm.GeminiClient:
    c = llm.GeminiClient.__new__(llm.GeminiClient)
    c._pool = [(i + 1, f"FAKE-SECRET-{i + 1}") for i in range(keys)]   # 로그에 나오면 안 되는 값 / must never reach the logs
    c._clients = [SimpleNamespace(models=FakeModels(box, i + 1)) for i in range(keys)]
    c._chains = [list(chain) for _ in range(keys)]
    c._lock = threading.Lock()
    c._cursor = 0
    c._cooldown = {}
    c._unsupported = set()
    return c


class FirstResponseCase(unittest.TestCase):
    def setUp(self):
        self.box = Box()
        self.addCleanup(self.box.release.set)   # 버려진 스레드를 곧바로 끝낸다 / end abandoned threads right away
        for name, value in (("GEMINI_FIRST_RESPONSE_SEC", LIMIT), ("GEMINI_503_COOLDOWN_SEC", 60.0),
                            ("GEMINI_503_COOLDOWN_MAX_SEC", 600.0), ("BACKOFF_BASE_SEC", 0.0)):
            p = patch.object(llm.settings, name, value)
            p.start()
            self.addCleanup(p.stop)

    def script(self, model: str, *steps) -> None:
        self.box.scripts.setdefault(model, []).extend(steps)

    @staticmethod
    def timed(fn, *args, **kwargs):
        t0 = time.perf_counter()
        out = fn(*args, **kwargs)
        return out, time.perf_counter() - t0

    @staticmethod
    def once(client, model):
        return client.models.generate_content(model=model, contents="q", config=None)

    def rest_everywhere(self, client: llm.GeminiClient, *models: str, reason: str = "429") -> None:
        until = time.monotonic() + 60.0
        for p in range(len(client._pool)):
            for m in models:
                client._cooldown[("gen", m, p)] = (until, reason)


class RotationLimitTests(FirstResponseCase):
    """_with_rotation 의 감시(비스트림 호출 = 호출 전체) / the watcher in _with_rotation (non-stream call = the whole call)"""

    def test_a_slow_first_model_is_tried_once_rests_on_every_key_and_the_next_model_answers(self):
        self.script(MAIN, {"first": SLOW, "chunks": ["late"]})
        self.script(SECOND, {"chunks": ["from-second"]}, {"chunks": ["again"]})
        client = make_client(self.box)
        resp, took = self.timed(client._with_rotation, self.once)
        self.assertEqual(resp.text, "from-second")
        self.assertLess(took, QUICK)                                     # 느린 호출을 끝까지 기다리지 않았다 / no wait for the slow call
        self.assertEqual(self.box.calls, [(MAIN, 1), (SECOND, 1)])       # MAIN 은 한 번만(키 2 · 3 없이) / MAIN once, keys 2 and 3 skipped
        self.assertTrue(all(client._cooling("gen", MAIN, p) for p in range(3)))
        self.assertEqual({r for (_k, m, _p), (_u, r) in client._cooldown.items() if m == MAIN}, {"504"})
        left = client._cooldown[("gen", MAIN, 2)][0] - time.monotonic()
        self.assertAlmostEqual(left, 60.0, delta=2)                      # max(60초, 2 x 0.2초) / max(60 s, twice 0.2 s)
        self.assertEqual(client._with_rotation(self.once).text, "again")   # 다음 호출도 MAIN 을 건너뛴다 / the next call skips MAIN too
        self.assertEqual(self.box.calls[-1][0], SECOND)

    def test_a_first_response_within_the_limit_is_kept(self):
        self.script(MAIN, {"first": 0.02, "chunks": ["main"]})
        client = make_client(self.box)
        self.assertEqual(client._with_rotation(self.once).text, "main")
        self.assertEqual(self.box.calls, [(MAIN, 1)])
        self.assertEqual(client._cooldown, {})

    def test_the_last_model_of_the_chain_is_never_cut(self):
        self.script(MAIN, {"first": 0.5, "chunks": ["only-model"]})
        self.script(LAST, {"first": 0.5, "chunks": ["slow-last"]})
        single = make_client(self.box, chain=(MAIN,))                    # 모델 하나뿐인 체인 / a one-model chain
        self.assertEqual(single._with_rotation(self.once).text, "only-model")
        longer = make_client(self.box)
        self.rest_everywhere(longer, MAIN, SECOND)                       # 앞 두 모델은 쉬는 중 / the first two models rest
        self.assertEqual(longer._with_rotation(self.once).text, "slow-last")
        self.assertEqual(self.box.calls, [(MAIN, 1), (LAST, 1)])
        self.assertFalse(any(r == "504" for (_u, r) in longer._cooldown.values()))

    def test_explicit_models_agentic_and_embeddings_are_never_cut(self):
        self.script(MAIN, {"first": 0.5, "chunks": ["agentic"]})
        self.script(llm.settings.EMB_MODEL, {"first": 0.5})
        client = make_client(self.box)
        out = client.generate_calls("q", models=[MAIN, SECOND])          # Agentic 세션 체인 / an Agentic session chain
        self.assertEqual(out, {"calls": [], "text": ""})
        self.assertEqual(client.embed(["a", "b"]), [[0.5, 0.25], [0.5, 0.25]])
        self.assertEqual(self.box.calls, [(MAIN, 1), (llm.settings.EMB_MODEL, 2)])
        self.assertEqual(client._cooldown, {})

    def test_a_zero_limit_disables_the_watch(self):
        self.script(MAIN, {"first": 0.5, "chunks": ["slow-main"]}, {"first": 0.5, "chunks": ["slow-", "stream"]})
        client = make_client(self.box)
        with patch.object(llm.settings, "GEMINI_FIRST_RESPONSE_SEC", 0.0):
            self.assertEqual(client._with_rotation(self.once).text, "slow-main")
            self.assertEqual("".join(client.stream("q")), "slow-stream")
        self.assertEqual(self.box.calls, [(MAIN, 1), (MAIN, 2)])
        self.assertEqual(client._cooldown, {})

    def test_errors_inside_the_watcher_keep_their_rotation_rules(self):
        with self.subTest("503 은 그 조합만 쉬고 같은 모델의 다음 키로 / a 503 rests its combo, the next key of the same model answers"):
            self.script(MAIN, server_error(), {"chunks": ["main-key2"]})
            client = make_client(self.box)
            self.assertEqual(client._with_rotation(self.once).text, "main-key2")
            self.assertTrue(client._cooling("gen", MAIN, 0))
            self.assertFalse(client._cooling("gen", MAIN, 1))
        with self.subTest("504 는 모든 키에서 쉬고 다음 모델로 / a 504 rests the model everywhere, the next model answers"):
            self.script(MAIN, server_error(504, "DEADLINE_EXCEEDED"))
            self.script(SECOND, {"chunks": ["after-504"]})
            client = make_client(self.box)
            self.assertEqual(client._with_rotation(self.once).text, "after-504")
            self.assertTrue(all(client._cooling("gen", MAIN, p) for p in range(3)))
        with self.subTest("넘길 수 없는 오류는 그대로 / a non-rotatable error is raised as is"):
            bad = errors.APIError(400, {"error": {"code": 400, "message": "bad request", "status": "INVALID_ARGUMENT"}}, None)
            self.script(MAIN, bad)
            client = make_client(self.box)
            before = len(self.box.calls)
            with self.assertRaises(errors.APIError):
                client._with_rotation(self.once)
            self.assertEqual(self.box.calls[before:], [(MAIN, 1)])

    def test_logs_name_the_cause_and_only_the_key_slot(self):
        self.script(MAIN, {"first": SLOW, "chunks": ["late"]})
        self.script(SECOND, {"chunks": ["ok"]})
        client = make_client(self.box)
        with self.assertLogs("ai365.llm", level="WARNING") as logs:
            client._with_rotation(self.once)
        text = "\n".join(logs.output)
        self.assertIn(f"모델 {MAIN} 키 #1 첫 응답 {LIMIT:g}초 없음: 다음 모델로 전환", text)
        self.assertIn(f"모델 {MAIN} 첫 응답 지연({LIMIT:g}초 없음): 모든 키에서 60초 건너뜀(키 #1 에서 발생)", text)
        self.assertNotIn("504(", text)                                    # 504 로 찍히지 않는다 / not logged as a 504
        self.assertNotIn("FAKE-SECRET", text)                             # 키 값은 없다 / no key values
        other = make_client(self.box)
        self.script(MAIN, server_error(504, "DEADLINE_EXCEEDED"))
        self.script(SECOND, {"chunks": ["ok"]})
        with self.assertLogs("ai365.llm", level="WARNING") as logs:
            other._with_rotation(self.once)
        self.assertIn(f"모델 {MAIN} 504(DEADLINE_EXCEEDED)", "\n".join(logs.output))   # 진짜 504 는 종전 문구 / a real 504 keeps its line

    def test_every_later_model_resting_after_a_timeout_raises_the_busy_notice(self):
        self.script(MAIN, *[{"first": SLOW, "chunks": ["late"]} for _ in range(3)])
        entry_points = {
            "rotation": lambda c: c._with_rotation(self.once),
            "generate": lambda c: c.generate("q"),
            "stream": lambda c: "".join(c.stream("q")),
        }
        for name, call in entry_points.items():
            with self.subTest(name):
                client = make_client(self.box)
                self.rest_everywhere(client, SECOND, LAST)                # 뒤 모델은 쿼터로 쉬는 중 / later models rest on quota
                before = len(self.box.calls)
                with self.assertRaises(llm.ModelBusyError) as ctx:
                    call(client)
                self.assertIn("503", str(ctx.exception))                  # 호출부의 '503' 판정 유지 / callers' '503' check still matches
                self.assertIn(f"모델 응답 {LIMIT:g}초 없음", str(ctx.exception))
                self.assertIsInstance(ctx.exception.__cause__, llm.FirstResponseTimeout)
                self.assertEqual(self.box.calls[before:], [(MAIN, 1)])
                with self.assertRaises(llm.ModelBusyError):               # 다음 호출은 시도 없이 혼잡 안내 / next call: busy notice, no attempt
                    call(client)
                self.assertEqual(len(self.box.calls), before + 1)


class GenerateLimitTests(FirstResponseCase):
    """generate() 는 내부가 스트림: 첫 청크만 재고, 모으는 도중 오류는 처음부터 다시 / generate() streams inside: only the first
    chunk is timed, and an error while collecting restarts from scratch"""

    def test_a_fast_first_chunk_is_kept_even_when_the_rest_is_slow(self):
        self.script(MAIN, {"chunks": ["가", "나", "다", "라"], "gap": 0.15})
        client = make_client(self.box)
        out, took = self.timed(client.generate, "q", system="s")
        self.assertEqual(out, "가나다라")
        self.assertGreater(took, LIMIT)                                   # 전체는 제한보다 길었다 / the whole call outlasted the limit
        self.assertEqual(self.box.calls, [(MAIN, 1)])
        self.assertEqual([e["how"] for e in self.box.log], ["stream"])     # 내부는 스트림 / streams inside
        self.assertEqual(client._cooldown, {})

    def test_a_late_first_chunk_moves_to_the_next_model(self):
        self.script(MAIN, {"first": SLOW, "chunks": ["late"]})
        self.script(SECOND, {"chunks": ["두 번째 ", "모델"]})
        client = make_client(self.box)
        out, took = self.timed(client.generate, "q")
        self.assertEqual(out, "두 번째 모델")
        self.assertLess(took, QUICK)
        self.assertEqual(self.box.calls, [(MAIN, 1), (SECOND, 1)])
        self.assertTrue(all(client._cooling("gen", MAIN, p) for p in range(3)))

    def test_json_mode_parses_the_streamed_json(self):
        self.script(MAIN, {"chunks": ['{"intent": "kn', 'owledge", "n": [1, ', '2]}']})
        client = make_client(self.box)
        self.assertEqual(client.generate("q", json_mode=True), {"intent": "knowledge", "n": [1, 2]})
        self.assertEqual(self.box.log[0]["config"].response_mime_type, "application/json")

    def test_a_mid_collect_503_restarts_from_scratch_on_the_next_key_without_duplicates(self):
        self.script(MAIN, {"chunks": ["AB", server_error()]}, {"chunks": ["AB", "C"]})
        client = make_client(self.box)
        self.assertEqual(client.generate([{"role": "user", "content": "q"}]), "ABC")   # "ABAB…" 가 아니다 / not "ABAB…"
        self.assertEqual(self.box.calls, [(MAIN, 1), (MAIN, 2)])
        self.assertTrue(client._cooling("gen", MAIN, 0))                  # 끊긴 조합만 쉰다 / only the combo that broke rests
        self.assertFalse(client._cooling("gen", MAIN, 1))
        self.assertEqual([c.role for c in self.box.log[1]["contents"]], ["user"])   # 이어쓰기 지시 없음 / no continuation turns

    def test_a_mid_collect_504_restarts_on_the_next_model_and_json_stays_whole(self):
        self.script(MAIN, {"chunks": ['{"a": ', server_error(504, "DEADLINE_EXCEEDED")]})
        self.script(SECOND, {"chunks": ['{"a": ', "2}"]})
        client = make_client(self.box)
        self.assertEqual(client.generate("q", json_mode=True), {"a": 2})
        self.assertEqual([m for m, _k in self.box.calls], [MAIN, SECOND])
        self.assertTrue(all(client._cooling("gen", MAIN, p) for p in range(3)))

    def test_a_read_timeout_while_collecting_restarts_too(self):
        self.script(MAIN, {"chunks": ["half", httpx.ReadTimeout("read timed out")]}, {"chunks": ["whole"]})
        client = make_client(self.box)
        self.assertEqual(client.generate("q"), "whole")
        self.assertEqual(self.box.calls, [(MAIN, 1), (MAIN, 2)])

    def test_two_failed_restarts_raise_the_one_line_notices(self):
        self.script(MAIN, *[{"chunks": ["x", server_error()]} for _ in range(3)])
        client = make_client(self.box)
        with self.assertRaises(llm.ModelBusyError) as ctx:
            client.generate("q")
        self.assertIn("503", str(ctx.exception))
        self.assertEqual(self.box.calls, [(MAIN, 1), (MAIN, 2), (MAIN, 3)])   # 처음 + 다시 2회 / first + two restarts
        self.script(SECOND, *[{"chunks": ["y", httpx.RemoteProtocolError("peer closed")]} for _ in range(3)])
        with self.assertRaises(llm.ModelUnreachableError):
            client.generate("q")

    def test_a_non_rotatable_error_while_collecting_is_raised_as_is(self):
        bad = errors.APIError(400, {"error": {"code": 400, "message": "bad request", "status": "INVALID_ARGUMENT"}}, None)
        self.script(MAIN, {"chunks": ["x", bad]})
        client = make_client(self.box)
        with self.assertRaises(errors.APIError):
            client.generate("q")
        self.assertEqual(self.box.calls, [(MAIN, 1)])

    def test_tools_or_a_zero_limit_keep_the_non_stream_call(self):
        self.script(MAIN, {"chunks": ["with-tools"]}, {"chunks": ["limit-off"]})
        client = make_client(self.box)
        tools = [llm.types.Tool(google_search=llm.types.GoogleSearch())]
        self.assertEqual(client.generate("q", tools=tools), "with-tools")
        with patch.object(llm.settings, "GEMINI_FIRST_RESPONSE_SEC", 0.0):
            self.assertEqual(client.generate("q"), "limit-off")
        self.assertEqual([e["how"] for e in self.box.log], ["once", "once"])


class StreamLimitTests(FirstResponseCase):
    """stream() 은 첫 청크까지만 잰다 / stream() times the first chunk only"""

    def test_a_late_first_chunk_moves_on_and_slow_later_chunks_stay(self):
        self.script(MAIN, {"first": SLOW, "chunks": ["late"]})
        self.script(SECOND, {"chunks": ["X", "Y", "Z"], "gap": 0.15})     # 다음 모델도 제한이 걸린 단계 / SECOND is a watched stage too
        client = make_client(self.box)
        it, opened = self.timed(client.stream, "q")
        out, joined = self.timed("".join, it)
        self.assertEqual(out, "XYZ")
        self.assertLess(opened, QUICK)
        self.assertGreater(joined, LIMIT)                                  # 뒤 청크는 제한보다 길어도 끊지 않았다 / slow later chunks were not cut
        self.assertEqual(self.box.calls, [(MAIN, 1), (SECOND, 1)])
        self.assertTrue(all(client._cooling("gen", MAIN, p) for p in range(3)))
        self.assertFalse(any(client._cooling("gen", SECOND, p) for p in range(3)))

    def test_slow_later_chunks_of_the_first_model_are_never_cut(self):
        self.script(MAIN, {"chunks": ["1", "2", "3", "4"], "gap": 0.12})
        client = make_client(self.box)
        self.assertEqual("".join(client.stream("q")), "1234")
        self.assertEqual(self.box.calls, [(MAIN, 1)])
        self.assertEqual(client._cooldown, {})

    def test_a_mid_stream_503_after_a_timeout_cools_the_serving_combo_not_the_abandoned_one(self):
        # 버려진 MAIN 시도가 늦게(0.3초) 끝나도 지금 스트림을 주는 (SECOND, 키 1) 기록을 덮어쓰지 않는다
        # The abandoned MAIN attempt finishing late (0.3 s) must not overwrite the record of the serving combo (SECOND, key 1)
        self.script(MAIN, {"first": 0.3, "chunks": ["late"]})
        self.script(SECOND, {"chunks": ["A", server_error()], "gap": 0.6}, {"chunks": ["B"]})
        client = make_client(self.box)
        self.assertEqual("".join(client.stream("q")), "AB")
        self.assertTrue(client._cooling("gen", SECOND, 0))                # 스트림을 주던 조합 / the combo that served the stream
        self.assertFalse(client._cooling("gen", SECOND, 1))
        self.assertEqual({r for (_k, m, _p), (_u, r) in client._cooldown.items() if m == MAIN}, {"504"})
        self.assertEqual([(m, k) for m, k in self.box.calls], [(MAIN, 1), (SECOND, 1), (SECOND, 2)])

    def test_a_late_stream_from_an_abandoned_attempt_is_closed(self):
        self.script(MAIN, {"first": 0.5, "chunks": ["late", "more"]})
        self.script(SECOND, {"chunks": ["ok"]})
        client = make_client(self.box)
        self.assertEqual("".join(client.stream("q")), "ok")
        main_stream = next(g for m, g in self.box.streams if m == MAIN)
        self.box.release.set()                                            # 버려진 시도의 첫 청크를 지금 내보낸다 / land it now
        deadline = time.monotonic() + 3.0
        while MAIN not in self.box.closed and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertIn(MAIN, self.box.closed)                              # 늦게 온 스트림은 닫혔다(연결 반환) / the late stream was closed
        self.assertIsNone(main_stream.gi_frame)


class NonStreamLimitTests(FirstResponseCase):
    """함수 호출 · 그라운딩은 비스트림 그대로, 감시는 호출 전체 / function calling and grounding stay non-streaming and time the whole call"""

    def test_generate_calls_on_the_tier_chain_times_the_whole_call(self):
        self.script(MAIN, {"first": SLOW, "chunks": ["late"]})
        self.script(SECOND, {"chunks": ["calls"]})
        client = make_client(self.box)
        out, took = self.timed(client.generate_calls, "q")
        self.assertEqual(out, {"calls": [], "text": ""})
        self.assertLess(took, QUICK)
        self.assertEqual([(e["model"], e["how"]) for e in self.box.log], [(MAIN, "once"), (SECOND, "once")])
        self.assertTrue(all(client._cooling("gen", MAIN, p) for p in range(3)))

    def test_grounding_times_the_whole_call_and_rests_only_the_grounded_kind(self):
        self.script(MAIN, {"first": SLOW, "chunks": ["late"]})
        self.script(SECOND, {"chunks": ["웹 답"]})
        client = make_client(self.box)
        out, took = self.timed(client.generate_grounded_meta, "q")
        self.assertEqual(out, {"text": "웹 답", "sources": [], "supports": []})
        self.assertLess(took, QUICK)
        self.assertTrue(all(client._cooling("grounded", MAIN, p) for p in range(3)))
        self.assertFalse(any(client._cooling("gen", MAIN, p) for p in range(3)))   # 일반 생성은 그대로 / plain generation unaffected


if __name__ == "__main__":
    unittest.main()
