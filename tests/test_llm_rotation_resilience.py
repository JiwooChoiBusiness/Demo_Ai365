# -*- coding: utf-8 -*-
"""LLM 호출 회복력(2026-09-14 배포 점검 "1단계 보고가 뜨다 만다") — 연결 오류 로테이션, 503 쿨다운, 스트림 도중 503 의 조합 쿨다운,
전부 실패 시 한 줄 안내. 실제 Gemini 호출은 없다(스텁).

LLM call resilience (2026-09-14 deployment review "the stage-1 report stops mid-way") — transport-error rotation, the 503
cooldown, cooling of the combo that served a stream that died with a 503, and one-line notices when everything fails.
No real Gemini calls (stubs)."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from google.genai import errors

from app import llm

MAIN = llm.settings.GEN_MODEL_MAIN
SECOND = llm.settings.GEN_FALLBACK_CHAIN[1]   # 체인의 다음 모델(2026-10-30 = 3.5-flash) / the chain's next model


def server_error(code: int = 503, status: str = "UNAVAILABLE") -> errors.APIError:
    return errors.ServerError(code, {"error": {"code": code, "message": "high demand", "status": status}}, None)


class FakeModels:
    """generate_content / generate_content_stream 스텁 — 호출마다 대본 하나(문자열·예외·청크 목록)를 소비하고 (모델, 키) 를 기록한다.
    Stub for both call styles — consumes one script entry per call and records (model, key)."""

    def __init__(self, scripts: list, calls: list, key: int):
        self.scripts, self.calls, self.key = scripts, calls, key

    def generate_content(self, model, contents, config):
        self.calls.append((model, self.key))
        item = self.scripts.pop(0)
        if isinstance(item, BaseException):
            raise item
        return SimpleNamespace(text=item)

    def generate_content_stream(self, model, contents, config):
        self.calls.append((model, self.key))
        script = self.scripts.pop(0)
        if isinstance(script, BaseException):
            raise script

        def it():
            for item in script:
                if isinstance(item, BaseException):
                    raise item
                yield SimpleNamespace(text=item)
        return it()


def make_client(scripts: list, calls: list, keys: int = 2, chain=(MAIN, SECOND)) -> llm.GeminiClient:
    c = llm.GeminiClient.__new__(llm.GeminiClient)
    c._pool = [(i + 1, f"k{i + 1}") for i in range(keys)]
    c._clients = [SimpleNamespace(models=FakeModels(scripts, calls, i + 1)) for i in range(keys)]
    c._chains = [list(chain) for _ in range(keys)]
    c._lock = threading.Lock()
    c._cursor = 0
    c._cooldown = {}
    c._unsupported = set()
    return c


class RotationResilienceTests(unittest.TestCase):
    @staticmethod
    def call(client, model):
        return client.models.generate_content(model=model, contents="q", config=None)

    def test_transport_error_rotates_to_the_next_key(self):
        calls: list = []
        client = make_client([httpx.ConnectError("refused"), "ok"], calls)
        self.assertEqual(client._with_rotation(self.call).text, "ok")
        self.assertEqual(calls, [(MAIN, 1), (MAIN, 2)])

    def test_503_cools_the_combo_so_the_next_call_skips_it(self):
        calls: list = []
        client = make_client([server_error(), "ok-2nd", "ok-2nd-again"], calls, keys=1)
        self.assertEqual(client._with_rotation(self.call).text, "ok-2nd")
        self.assertTrue(client._cooling("gen", MAIN, 0))
        self.assertEqual(client._with_rotation(self.call).text, "ok-2nd-again")   # 쿨다운 중인 MAIN 은 건너뛴다 / MAIN is skipped
        self.assertEqual(calls, [(MAIN, 1), (SECOND, 1), (SECOND, 1)])

    def test_repeated_503_escalates_the_cooldown_and_success_resets_it(self):
        calls: list = []
        client = make_client([server_error(), "ok", server_error(), "ok", "ok-main", server_error(), "ok"], calls, keys=1)
        left = lambda: client._cooldown[("gen", MAIN, 0)][0] - llm.time.monotonic()   # noqa: E731
        with patch.object(llm.settings, "GEMINI_503_COOLDOWN_SEC", 60.0), patch.object(llm.settings, "GEMINI_503_COOLDOWN_MAX_SEC", 600.0):
            client._with_rotation(self.call)
            self.assertAlmostEqual(left(), 60.0, delta=2)
            client._cooldown[("gen", MAIN, 0)] = (0.0, "503")          # 만료시켜 다시 시도하게 / expire it so MAIN is tried again
            client._with_rotation(self.call)
            self.assertAlmostEqual(left(), 120.0, delta=2)                   # 연속 2회 → 2배 / second strike doubles
            client._cooldown[("gen", MAIN, 0)] = (0.0, "503")
            self.assertEqual(client._with_rotation(self.call).text, "ok-main")   # 성공 → 초기화 / success resets the streak
            client._with_rotation(self.call)
            self.assertAlmostEqual(left(), 60.0, delta=2)

    def test_zero_setting_disables_the_503_cooldown(self):
        calls: list = []
        client = make_client([server_error(), "ok"], calls, keys=1)
        with patch.object(llm.settings, "GEMINI_503_COOLDOWN_SEC", 0.0):
            client._with_rotation(self.call)
        self.assertFalse(client._cooling("gen", MAIN, 0))

    def test_all_transport_errors_raise_a_one_line_notice(self):
        calls: list = []
        client = make_client([httpx.ConnectError("a"), httpx.RemoteProtocolError("b")], calls, keys=1, chain=(MAIN,))
        with patch.object(llm.time, "sleep"), self.assertRaises(llm.ModelUnreachableError) as ctx:
            client._with_rotation(self.call)
        self.assertIn("연결하지 못했습니다", str(ctx.exception))
        self.assertEqual(len(calls), 2)   # 라운드 2회 모두 시도 / both rounds tried

    def test_all_cooling_because_of_503_fails_fast_with_the_busy_notice(self):
        calls: list = []
        client = make_client([server_error(), server_error()], calls, keys=1, chain=(MAIN,))
        with patch.object(llm.time, "sleep"), self.assertRaises(llm.ModelBusyError):
            client._with_rotation(self.call)
        n = len(calls)
        with self.assertRaises(llm.ModelBusyError):   # 쿨다운 중 — 호출 없이 즉시 실패 / cooling — fails at once, no call
            client._with_rotation(self.call)
        self.assertEqual(len(calls), n)

    def test_mid_stream_503_cools_the_serving_combo(self):
        calls: list = []
        client = make_client([["A", server_error()], ["B"]], calls)
        self.assertEqual("".join(client.stream("q")), "AB")
        self.assertTrue(client._cooling("gen", MAIN, 0))    # 1차 스트림을 주던 키 1 / key 1 served the first stream
        self.assertFalse(client._cooling("gen", MAIN, 1))


def deadline_error() -> errors.APIError:
    return server_error(504, "DEADLINE_EXCEEDED")


class DeadlineRotationTests(unittest.TestCase):
    """504 DEADLINE_EXCEEDED(2026-10-27 사용자 지시 "504도 503처럼 다음 모델로") — 그 모델을 모든 키에서 쿨다운하고 바로 다음 모델로.
    504 (user instruction 2026-10-27): the model is cooled on every key and the call moves straight to the next model."""

    call = staticmethod(RotationResilienceTests.call)

    def test_504_skips_the_model_on_every_key_and_moves_to_the_next_model(self):
        calls: list = []
        client = make_client([deadline_error(), "ok-second", "ok-second-again"], calls, keys=3)
        with patch.object(llm.settings, "GEMINI_503_COOLDOWN_SEC", 60.0):
            self.assertEqual(client._with_rotation(self.call).text, "ok-second")
        # 키 2 · 3 의 MAIN 은 시도하지 않는다(키마다 약 2분씩 기다리지 않게) / MAIN is not tried on keys 2 and 3
        self.assertEqual(calls, [(MAIN, 1), (SECOND, 1)])
        self.assertTrue(all(client._cooling("gen", MAIN, p) for p in range(3)))
        self.assertEqual({r for (_k, _m, _p), (_u, r) in client._cooldown.items()}, {"504"})
        self.assertEqual(client._with_rotation(self.call).text, "ok-second-again")   # 다음 호출도 MAIN 을 건너뛴다 / skipped next call too
        self.assertEqual(calls[-1][0], SECOND)

    def test_504_cooldown_escalates_per_model_and_success_resets_it(self):
        calls: list = []
        client = make_client([deadline_error(), "ok", deadline_error(), "ok", "ok-main", deadline_error(), "ok"], calls, keys=2)
        left = lambda p: client._cooldown[("gen", MAIN, p)][0] - llm.time.monotonic()   # noqa: E731

        def expire():
            for p in range(2):
                client._cooldown[("gen", MAIN, p)] = (0.0, "504")

        with patch.object(llm.settings, "GEMINI_503_COOLDOWN_SEC", 60.0), patch.object(llm.settings, "GEMINI_503_COOLDOWN_MAX_SEC", 600.0):
            client._with_rotation(self.call)
            self.assertAlmostEqual(left(0), 60.0, delta=2)
            self.assertAlmostEqual(left(1), 60.0, delta=2)      # 504 가 나지 않은 키도 같은 길이 / the other key gets the same span
            expire()
            client._with_rotation(self.call)
            self.assertAlmostEqual(left(1), 120.0, delta=2)     # 모델 단위 연속 2회 → 2배 / second model-level strike doubles
            expire()
            self.assertEqual(client._with_rotation(self.call).text, "ok-main")   # 성공 → 초기화 / success resets the streak
            client._with_rotation(self.call)
            self.assertAlmostEqual(left(0), 60.0, delta=2)

    def test_504_cooldown_covers_twice_the_time_it_took(self):
        # 실측(2026-10-27): 504 는 약 2분 뒤에 온다 — 60초 쿨다운은 그 호출이 끝나기 전에 풀려 다음 질문이 또 2분을 기다렸다
        # Measured: a 504 arrives after about two minutes; a 60-second cooldown expired before the call ended
        now = [1000.0]
        calls: list = []
        client = make_client([], calls, keys=2)

        def slow_504(model, contents, config):
            calls.append(model)
            if model == MAIN:
                now[0] += 120.0
                raise deadline_error()
            return SimpleNamespace(text="ok")

        for cl in client._clients:
            cl.models.generate_content = slow_504
        with patch.object(llm.time, "monotonic", lambda: now[0]), \
                patch.object(llm.settings, "GEMINI_503_COOLDOWN_SEC", 60.0), patch.object(llm.settings, "GEMINI_503_COOLDOWN_MAX_SEC", 600.0):
            self.assertEqual(client._with_rotation(self.call).text, "ok")
            self.assertAlmostEqual(client._cooldown[("gen", MAIN, 1)][0] - now[0], 240.0, delta=1)   # 2 × 120초 / twice the wait
            now[0] += 120.0                                       # 2분 뒤 다음 질문 / the next question two minutes later
            self.assertEqual(client._with_rotation(self.call).text, "ok")
        self.assertEqual(calls, [MAIN, SECOND, SECOND])          # 다음 질문은 MAIN 을 기다리지 않는다 / no second wait on MAIN

    def test_zero_setting_still_moves_on_without_a_cooldown(self):
        calls: list = []
        client = make_client([deadline_error(), "ok-second"], calls, keys=2)
        with patch.object(llm.settings, "GEMINI_503_COOLDOWN_SEC", 0.0):
            self.assertEqual(client._with_rotation(self.call).text, "ok-second")
        self.assertEqual(calls, [(MAIN, 1), (SECOND, 1)])     # 이번 호출 안에서는 다음 모델로 / this call still moves on
        self.assertFalse(any(client._cooling("gen", MAIN, p) for p in range(2)))

    def test_all_504_raises_the_busy_notice_once(self):
        calls: list = []
        client = make_client([deadline_error()], calls, keys=2, chain=(MAIN,))
        with patch.object(llm.settings, "GEMINI_503_COOLDOWN_SEC", 60.0), patch.object(llm.time, "sleep"), \
                self.assertRaises(llm.ModelBusyError) as ctx:
            client._with_rotation(self.call)
        self.assertIn("503", str(ctx.exception))               # 호출부의 '503' 문자열 판정 유지 / callers' '503' check still matches
        self.assertIn("504", str(ctx.exception))
        self.assertEqual(calls, [(MAIN, 1)])                     # 두 번째 키 · 두 번째 라운드 없이 / no second key, no second round
        with self.assertRaises(llm.ModelBusyError):              # 쿨다운 중 — 호출 없이 혼잡 안내 / cooling: busy notice, no call
            client._with_rotation(self.call)
        self.assertEqual(len(calls), 1)

    def test_mid_stream_504_cools_the_model_and_continues_on_the_next_model(self):
        calls: list = []
        client = make_client([["A", deadline_error()], ["B"]], calls)
        with patch.object(llm.settings, "GEMINI_503_COOLDOWN_SEC", 60.0):
            self.assertEqual("".join(client.stream("q")), "AB")
        self.assertTrue(all(client._cooling("gen", MAIN, p) for p in range(2)))
        self.assertEqual([m for m, _k in calls], [MAIN, SECOND])

    def test_other_server_errors_still_raise_untouched(self):
        calls: list = []
        client = make_client([server_error(500, "INTERNAL")], calls, keys=2)
        with self.assertRaises(errors.ServerError):
            client._with_rotation(self.call)
        self.assertEqual(calls, [(MAIN, 1)])


if __name__ == "__main__":
    unittest.main()
