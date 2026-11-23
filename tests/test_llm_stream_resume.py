# -*- coding: utf-8 -*-
"""llm.stream 이어쓰기(2026-09-14) — 스트림 도중 503 이 나면 다음 키/모델로 다시 열어 이어 쓴다(실제 Gemini 호출 없음).
Mid-stream continuation for llm.stream (2026-09-14) — a 503 on a later chunk reopens the stream on the next key/model
and continues (no real Gemini calls)."""
import threading
import unittest
from types import SimpleNamespace

from google.genai import errors

from app import llm


def server_error(code: int = 503, status: str = "UNAVAILABLE") -> errors.APIError:
    return errors.ServerError(code, {"error": {"code": code, "message": "high demand", "status": status}}, None)


class FakeModels:
    """generate_content_stream 스텁 — 호출마다 대본(청크 목록 또는 예외)을 하나씩 소비하고 호출 인자를 기록한다.
    Stub for generate_content_stream — consumes one script entry per call and records the call arguments."""

    def __init__(self, scripts: list, calls: list):
        self.scripts = scripts
        self.calls = calls

    def generate_content_stream(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents})
        script = self.scripts.pop(0)

        def it():
            for item in script:
                if isinstance(item, BaseException):
                    raise item
                yield SimpleNamespace(text=item)
        return it()


def make_client(scripts: list, calls: list, keys: int = 2) -> llm.GeminiClient:
    c = llm.GeminiClient.__new__(llm.GeminiClient)
    c._pool = [(i + 1, f"k{i + 1}") for i in range(keys)]
    c._clients = [SimpleNamespace(models=FakeModels(scripts, calls)) for _ in range(keys)]
    c._chains = [[llm.settings.GEN_MODEL_MAIN, llm.settings.GEN_FALLBACK_CHAIN[1]] for _ in range(keys)]   # 메인 + 체인의 다음 모델 / main + the chain's next model
    c._lock = threading.Lock()
    c._cursor = 0
    c._cooldown = {}
    c._unsupported = set()
    return c


class StreamResumeTests(unittest.TestCase):
    def test_mid_stream_503_resumes_on_next_key_and_trims_overlap(self):
        calls: list = []
        first, second = "1. 핵심 요약\n- 재무: 1분기 누적 매출은 ", "142.3억 원(목표 대비 102%)"
        # 1차: 두 청크를 보낸 뒤 503 / 2차(이어쓰기): 꼬리 일부를 반복하고 이어 감
        # first stream: two chunks then 503 / continuation: repeats part of the tail, then continues
        client = make_client([[first, second, server_error()],
                              ["(목표 대비 102%)", "\n- 운영: 납기 준수율 97%"]], calls)
        out = "".join(client.stream([{"role": "user", "content": "q"}], system="s"))
        self.assertEqual(out, first + second + "\n- 운영: 납기 준수율 97%")
        self.assertEqual(len(calls), 2)
        # 이어쓰기 요청 = 원 대화 + 보낸 본문(모델 턴) + 이어쓰기 지시(사용자 턴) / continuation = base + model(sent) + user(note)
        resumed = calls[1]["contents"]
        self.assertEqual([c.role for c in resumed], ["user", "model", "user"])
        self.assertEqual(resumed[1].parts[0].text, first + second)
        self.assertIn("이어서", resumed[2].parts[0].text)
        # 다음 키로 넘어갔다(라운드로빈 커서) / moved on to the next key (round-robin cursor)
        self.assertEqual(client._cursor, 2 % len(client._pool))

    def test_full_restart_head_is_trimmed(self):
        calls: list = []
        sent = "1. 핵심 요약\n- 재무 및 주요 KPI 초과 달성: 2026년 1분기 누적 매출은 142.3억 원(목표 대비 102%)"
        cont = sent + "\n- 운영 지표: 납기 준수율 97%"
        client = make_client([[sent, server_error()], [cont]], calls)
        out = "".join(client.stream("q"))
        self.assertEqual(out, sent + "\n- 운영 지표: 납기 준수율 97%")

    def test_error_before_any_text_restarts_from_scratch(self):
        calls: list = []
        client = make_client([["", server_error()], ["X", "Y"]], calls)
        out = "".join(client.stream("q"))
        self.assertEqual(out, "XY")
        self.assertEqual([c.role for c in calls[1]["contents"]], ["user"])   # 이어쓰기 지시 없음 / no continuation turns

    def test_resume_budget_exhausted_raises_model_busy(self):
        calls: list = []
        scripts = [["A", server_error()], ["B", server_error()], ["C", server_error()]]
        client = make_client(scripts, calls)
        got = []
        with self.assertRaises(llm.ModelBusyError) as ctx:
            for t in client.stream("q"):
                got.append(t)
        # 1차 본문은 그대로 남고, 이어쓰기 중 죽은 청크는 겹침 판정 버퍼(200자)에 있어 내보내지 않는다
        # The first stream's text stays; chunks of a continuation that died stay in the overlap buffer (200 chars)
        self.assertEqual(got, ["A"])
        self.assertIn("503", str(ctx.exception))
        self.assertEqual(len(calls), 3)                    # 1차 + 이어쓰기 2회 / first + two continuations

    def test_non_rotatable_error_is_not_resumed(self):
        calls: list = []
        bad = errors.APIError(400, {"error": {"code": 400, "message": "bad request", "status": "INVALID_ARGUMENT"}}, None)
        client = make_client([["A", bad]], calls)
        with self.assertRaises(errors.APIError):
            list(client.stream("q"))
        self.assertEqual(len(calls), 1)

    def test_all_keys_503_on_open_raises_model_busy(self):
        calls: list = []
        scripts = [[server_error()]] * 8   # 키 2 × 체인 2단계 × 백오프 재시도 1회 / 2 keys x 2 chain stages x 1 backoff round
        client = make_client(list(scripts), calls)
        with unittest.mock.patch.object(llm.time, "sleep"):
            with self.assertRaises(llm.ModelBusyError):
                client.stream("q")

    def test_trim_overlap_cases(self):
        self.assertEqual(llm._trim_overlap("abcdefgh", "efgh-next"), "-next")    # 접미=접두 겹침(4자 이상) / suffix==prefix (4+ chars)
        self.assertEqual(llm._trim_overlap("abcdefgh", "gh-next"), "gh-next")    # 3자 이하는 겹침으로 보지 않음 / 3 chars or fewer are not an overlap
        self.assertEqual(llm._trim_overlap("abc", "xyz"), "xyz")                 # 겹침 없음 / no overlap
        self.assertEqual(llm._trim_overlap("", "xyz"), "xyz")
        tail = "이 문장은 겹침 탐지용 꼬리 문장입니다. 충분히 길어야 합니다."
        self.assertEqual(llm._trim_overlap("앞부분. " + tail, "앞부분. " + tail + " 이어지는 본문"), " 이어지는 본문")


import unittest.mock  # noqa: E402 — 테스트 본문에서 patch 사용 / patch used inside a test


if __name__ == "__main__":
    unittest.main()
