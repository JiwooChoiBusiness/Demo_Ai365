# -*- coding: utf-8 -*-
"""{{base_url}} 기본값 = 이 서버 자신(2026-09-30) — AI365_BASE_URL 이 없으면 main 의 ASGI 미들웨어가 첫 실제 요청의 소켓 포트로
flow_api_call.SELF_BASE 를 채운다(8010 검증 서버가 8000 의 /mock/… 을 부르지 않게). 테스트 클라이언트(testserver)는 건너뛴다.

The {{base_url}} default is this server itself (2026-09-30): without AI365_BASE_URL, main's ASGI middleware fills
flow_api_call.SELF_BASE from the socket port of the first real request (an 8010 verification server no longer calls 8000's
/mock/…); test clients (testserver) are skipped."""
import asyncio
import os
import unittest
from unittest.mock import patch

from app import flow_api_call


def _middleware():
    """app.main 을 들여오지 않고(실 DB 초기화를 피한다) 미들웨어 클래스 소스만 평가한다 / evaluate only the middleware class"""
    import pathlib
    import re
    src = (pathlib.Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(encoding="utf-8")
    m = re.search(r"^class _SelfOrigin:.*?(?=^\S)", src, re.S | re.M)
    assert m, "_SelfOrigin not found"
    ns = {"flow_api_call": flow_api_call, "os": os}
    exec(m.group(0), ns)   # noqa: S102 — 저장소의 자기 코드 / the repository's own code
    return ns["_SelfOrigin"]


class SelfOriginTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, flow_api_call, "SELF_BASE", flow_api_call.SELF_BASE)
        flow_api_call.SELF_BASE = None
        env = {k: v for k, v in os.environ.items() if k != "AI365_BASE_URL"}
        p = patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def call(self, server):
        seen = []

        async def inner(scope, receive, send):
            seen.append(scope["path"])
        mw = _middleware()(inner)
        asyncio.run(mw({"type": "http", "path": "/api/health", "server": server}, None, None))
        return seen

    def test_default_order(self):
        self.assertEqual(flow_api_call.default_base_url(), "http://localhost:8000")
        flow_api_call.SELF_BASE = "http://127.0.0.1:8010"
        self.assertEqual(flow_api_call.default_base_url(), "http://127.0.0.1:8010")
        self.assertEqual(flow_api_call.build_ctx()["base_url"], "http://127.0.0.1:8010")
        with patch.dict(os.environ, {"AI365_BASE_URL": "http://127.0.0.1:8011/"}):
            self.assertEqual(flow_api_call.default_base_url(), "http://127.0.0.1:8011")   # 설정값이 이긴다 / the setting wins

    def test_middleware_remembers_a_local_port_once(self):
        self.assertEqual(self.call(("127.0.0.1", 8010)), ["/api/health"])   # 요청은 그대로 넘긴다 / the request passes through
        self.assertEqual(flow_api_call.SELF_BASE, "http://127.0.0.1:8010")
        self.call(("127.0.0.1", 8020))
        self.assertEqual(flow_api_call.SELF_BASE, "http://127.0.0.1:8010")   # 처음 값 유지 / the first value stays
        self.assertEqual(flow_api_call.substitute("{{base_url}}/mock/mcp", flow_api_call.build_ctx()),
                         "http://127.0.0.1:8010/mock/mcp")

    def test_middleware_skips_test_clients_other_hosts_and_a_configured_url(self):
        self.call(("testserver", 80))
        self.call(("10.1.2.3", 8000))
        self.assertIsNone(flow_api_call.SELF_BASE)
        with patch.dict(os.environ, {"AI365_BASE_URL": "http://127.0.0.1:8011"}):
            self.call(("127.0.0.1", 8010))
        self.assertIsNone(flow_api_call.SELF_BASE)
        self.call(("0.0.0.0", 8030))   # 모든 주소 바인딩 → 루프백 / all-interfaces binding → loopback
        self.assertEqual(flow_api_call.SELF_BASE, "http://127.0.0.1:8030")


if __name__ == "__main__":
    unittest.main()
