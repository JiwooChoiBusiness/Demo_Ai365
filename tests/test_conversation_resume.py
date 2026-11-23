# -*- coding: utf-8 -*-
"""실행 재개(2026-09-16 수정) — 액션 확인·파일 생성 승인·예약이 부르는 resume_events 가 폐지된 채팅 커넥터 헬퍼를 임포트하지 않는다.
사용자 제보: "cannot import name '_chat_connectors' from 'app.chats_api'". 더불어 chats_api 에서 가져오는 이름이 실제로 있는지 정적으로 확인한다.

Run resume (fixed 2026-09-16) — resume_events, used by action confirms, file-generation approvals and schedules, must not import the
retired chat-connector helper (user report: ImportError on every resume). Also checks statically that every name imported from
chats_api still exists."""
import importlib
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from app import conversation_execution, db, pipeline

APP_DIR = Path(__file__).resolve().parent.parent / "app"


class ResumeTests(unittest.IsolatedAsyncioTestCase):
    async def test_resume_passes_empty_connectors_without_importing_retired_helper(self):
        seen = {}

        async def fake_drive(run, chat, connectors, eff):
            seen["connectors"] = connectors
            seen["chat"] = chat
            yield {"type": "done"}

        run = {"chat_id": "c1", "snapshot": {"actor": "7"}}
        with patch.object(db, "get_chat", return_value={"id": "c1"}), \
             patch.object(pipeline, "_resolve_eff", return_value=None), \
             patch.object(conversation_execution, "drive", fake_drive):
            events = [ev async for ev in conversation_execution.resume_events(run)]
        self.assertEqual([e["type"] for e in events], ["thinking_start", "done"])
        self.assertEqual(seen["connectors"], [])   # 채팅 커넥터 폐지 → 항상 빈 목록 / retired chat connectors → always empty
        self.assertEqual(seen["chat"]["id"], "c1")

    async def test_resume_of_a_deleted_chat_yields_nothing(self):
        with patch.object(db, "get_chat", return_value=None):
            events = [ev async for ev in conversation_execution.resume_events({"chat_id": "gone", "snapshot": {"actor": ""}})]
        self.assertEqual(events, [])


class ImportGuardTests(unittest.TestCase):
    def test_every_name_imported_from_chats_api_exists(self):
        """`from app.chats_api import X` 가 가리키는 이름이 모두 존재해야 한다(지연 임포트는 호출 때만 터져 회귀가 숨는다)."""
        # Every `from app.chats_api import X` must resolve (lazy imports only fail at call time, hiding regressions).
        mod = importlib.import_module("app.chats_api")
        rx = re.compile(r"^\s*from app\.chats_api import ([A-Za-z0-9_, ]+)", re.M)
        missing = []
        for path in sorted(APP_DIR.glob("*.py")):
            if path.name == "chats_api.py":
                continue
            for m in rx.finditer(path.read_text(encoding="utf-8")):
                for name in (n.strip() for n in m.group(1).split(",")):
                    if name and not hasattr(mod, name):
                        missing.append(f"{path.name}: {name}")
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
