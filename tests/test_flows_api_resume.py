"""워크플로우 API(flows_api.py) HTTP 계약 회귀 — /run·/resume·/runs/{id}·/{id}/summary + 관련 chats_api flow_id.

실제 LLM·외부 API·real DB는 쓰지 않는다(격리 DB + 패치). run_flow의 내부 동작(단계 게이트 메커닉)은
tests/test_flow_stage_gate.py가 이미 두텁게 검증하므로, 여기서는 HTTP 계층(검증 순서·상태 코드·
응답 스키마)에 집중한다.

Workflow API (flows_api.py) HTTP-contract regression — /run, /resume, /runs/{id}, /{id}/summary, plus the
related chats_api flow_id behavior. No real LLM/external API/real DB (isolated DB + patches). run_flow's
internal stage-gate mechanics are already covered thoroughly by tests/test_flow_stage_gate.py, so this file
focuses on the HTTP layer: validation order, status codes, response shape.
"""
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from db_fixture import isolate_db
from app import access, artifact_execution, chats_api, db, execution_store as store, flows, flows_api


FLOW = {"id": "fl_x", "name": "테스트 플로우", "group": "og9", "description": "설명",
        "stages": [{"nodes": [{"agent": "data", "resources": [], "instruction": "a"}], "answer_prompt": ""},
                   {"nodes": [{"agent": "data", "resources": [], "instruction": "b"}], "answer_prompt": "취합"}]}


class FlowsApiTestBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        # 미지정 경로가 실제 서비스에 도달하면 즉시 실패 / any unstubbed path to a real service fails at once
        self.stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")))
        self.stack.enter_context(patch("app.llm.stream", side_effect=AssertionError("unexpected LLM stream")))
        self.stack.enter_context(patch("app.flow_api_call.call", side_effect=AssertionError("unexpected external API")))
        self.app = FastAPI()
        self.app.include_router(flows_api.router)
        self.app.include_router(chats_api.router)
        self.chat = db.create_chat("t", "사내")

    async def post(self, path, json):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
            return await client.post(path, json=json)

    async def get(self, path):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
            return await client.get(path)

    async def patch_chat(self, chat_id, json):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
            return await client.patch(f"/api/chats/{chat_id}", json=json)

    def make_run(self, chat_id, *, waiting=None, state="needs_input", actor="", kind="workflow",
                cursor=0, flow=None):
        snap = {"kind": kind, "flow": flow if flow is not None else FLOW, "message": "q", "actor": actor,
                "eff": None, "results": {}, "cursor": cursor, "stage_state": {}, "attempts": {}}
        if waiting is not None:
            snap["waiting"] = waiting
        run = store.create(chat_id, snap)
        store.save(run, state)
        return run


class ResumeValidationOrderTests(FlowsApiTestBase):
    """POST /api/flows/resume 검증 순서 — 소스의 if/elif 순서를 그대로 따라간다.
    Validation order — walks the source's if/elif chain in the same order."""

    async def test_unknown_chat_is_404(self):
        resp = await self.post("/api/flows/resume",
                               {"run_id": "run_x", "chat_id": "no_such_chat", "reply": {}})
        self.assertEqual(resp.status_code, 404)

    async def test_unknown_run_is_404(self):
        resp = await self.post("/api/flows/resume",
                               {"run_id": "run_missing", "chat_id": self.chat["id"], "reply": {}})
        self.assertEqual(resp.status_code, 404)

    async def test_run_belonging_to_a_different_chat_is_404(self):
        other = db.create_chat("other", "사내")
        run = self.make_run(other["id"], waiting={"kind": "gate", "stage": 0})
        resp = await self.post("/api/flows/resume",
                               {"run_id": run["id"], "chat_id": self.chat["id"],
                                "reply": {"kind": "flow_gate", "action": "cancel"}})
        self.assertEqual(resp.status_code, 404)

    async def test_non_workflow_run_is_422(self):
        non_wf = store.create(self.chat["id"], {"kind": "document"})
        store.save(non_wf, "needs_input")
        resp = await self.post("/api/flows/resume",
                               {"run_id": non_wf["id"], "chat_id": self.chat["id"],
                                "reply": {"kind": "flow_gate", "action": "cancel"}})
        self.assertEqual(resp.status_code, 422)

    async def test_actor_mismatch_is_403(self):
        run = self.make_run(self.chat["id"], waiting={"kind": "gate", "stage": 0}, actor="7")
        resp = await self.post("/api/flows/resume",
                               {"run_id": run["id"], "chat_id": self.chat["id"],
                                "reply": {"kind": "flow_gate", "action": "cancel"}, "acting_user_id": ""})
        self.assertEqual(resp.status_code, 403)

    async def test_state_not_needs_input_is_409(self):
        run = self.make_run(self.chat["id"], waiting={"kind": "gate", "stage": 0}, state="ready")
        resp = await self.post("/api/flows/resume",
                               {"run_id": run["id"], "chat_id": self.chat["id"],
                                "reply": {"kind": "flow_gate", "action": "cancel"}})
        self.assertEqual(resp.status_code, 409)

    async def test_waiting_kind_mismatch_is_409(self):
        run = self.make_run(self.chat["id"], waiting={"kind": "gate", "stage": 0})
        resp = await self.post("/api/flows/resume",
                               {"run_id": run["id"], "chat_id": self.chat["id"],
                                "reply": {"kind": "flow_question", "answers": {}}})
        self.assertEqual(resp.status_code, 409)

    async def test_missing_required_answer_is_422(self):
        run = self.make_run(self.chat["id"], waiting={"kind": "review", "stage": 0, "rerun": [],
                            "questions": [{"id": "q1", "label": "기간", "question": "언제?",
                                          "kind": "text", "required": True}]})
        resp = await self.post("/api/flows/resume",
                               {"run_id": run["id"], "chat_id": self.chat["id"],
                                "reply": {"kind": "flow_question", "answers": {}}})
        self.assertEqual(resp.status_code, 422)

    async def test_choice_not_in_options_is_422(self):
        run = self.make_run(self.chat["id"], waiting={"kind": "review", "stage": 0, "rerun": [],
                            "questions": [{"id": "q1", "label": "기간", "question": "언제?", "kind": "choice",
                                          "options": ["이번 달", "지난 달"], "required": False}]})
        resp = await self.post("/api/flows/resume",
                               {"run_id": run["id"], "chat_id": self.chat["id"],
                                "reply": {"kind": "flow_question", "answers": {"q1": "올해"}}})
        self.assertEqual(resp.status_code, 422)

    async def test_bad_gate_action_is_422(self):
        run = self.make_run(self.chat["id"], waiting={"kind": "gate", "stage": 0})
        resp = await self.post("/api/flows/resume",
                               {"run_id": run["id"], "chat_id": self.chat["id"],
                                "reply": {"kind": "flow_gate", "action": "pause"}})
        self.assertEqual(resp.status_code, 422)

    async def test_revise_without_a_usable_note_is_422(self):
        # 수정 요청(2026-09-30)은 요청 문장이 필수 — 없음·공백·문자열 아님·상한 초과는 422, 스냅샷·메시지는 그대로
        # A revise (2026-09-30) needs its instruction: missing, blank, non-string or over-long notes are 422 and nothing changes
        run = self.make_run(self.chat["id"], waiting={"kind": "gate", "stage": 0}, cursor=1)
        replies = [{"kind": "flow_gate", "action": "revise"},
                   {"kind": "flow_gate", "action": "revise", "note": "   "},
                   {"kind": "flow_gate", "action": "revise", "note": 3},
                   {"kind": "flow_gate", "action": "revise", "note": "가" * (flows.MAX_GATE_NOTE + 1)}]
        for i, reply in enumerate(replies):
            with self.subTest(case=i):
                resp = await self.post("/api/flows/resume",
                                       {"run_id": run["id"], "chat_id": self.chat["id"], "reply": reply})
                self.assertEqual(resp.status_code, 422)
        resp = await self.post("/api/flows/resume",
                               {"run_id": run["id"], "chat_id": self.chat["id"], "reply": replies[0]})
        self.assertEqual(resp.json()["detail"], "수정 요청 내용을 입력해 주세요")
        saved = store.get(run["id"])
        self.assertEqual((saved["state"], saved["snapshot"]["cursor"]), ("needs_input", 1))
        self.assertEqual(db.list_messages(self.chat["id"]), [])

    async def test_revise_with_a_note_rewinds_the_stage_and_resumes_the_same_run(self):
        run = self.make_run(self.chat["id"], waiting={"kind": "gate", "stage": 0}, cursor=1)
        seen = []

        async def fake_workflow_run(flow, chat, message, actor, run_=None):
            seen.append(run_["id"] if run_ else None)
            yield {"type": "done"}

        with patch.object(artifact_execution, "workflow_run", fake_workflow_run):
            resp = await self.post("/api/flows/resume",
                                   {"run_id": run["id"], "chat_id": self.chat["id"],
                                    "reply": {"kind": "flow_gate", "action": "revise", "note": " 표로 정리해줘 "}})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/event-stream", resp.headers["content-type"])
        self.assertEqual(seen, [run["id"]])
        snap = store.get(run["id"])["snapshot"]
        self.assertEqual(snap["cursor"], 0)                                  # 같은 단계로 / back on the same stage
        self.assertEqual(snap["stage_state"]["0"]["revise"], "표로 정리해줘")
        row = db.list_messages(self.chat["id"])[-1]
        self.assertEqual((row["role"], row["content"], row["meta"]),
                         ("user", "1단계 수정 요청: 표로 정리해줘", {"flow_revise": {"stage": 0}}))

    async def test_gate_cancel_succeeds_as_event_stream_and_cancels_the_run(self):
        run = self.make_run(self.chat["id"], waiting={"kind": "gate", "stage": 0})
        resp = await self.post("/api/flows/resume",
                               {"run_id": run["id"], "chat_id": self.chat["id"],
                                "reply": {"kind": "flow_gate", "action": "cancel"}})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/event-stream", resp.headers["content-type"])
        self.assertIn('"type": "execution_result"', resp.text)
        self.assertIn('"state": "cancelled"', resp.text)
        self.assertEqual(store.get(run["id"])["state"], "cancelled")


class RunStatusTests(FlowsApiTestBase):
    """GET /api/flows/runs/{id} — 카드 복원 재검증. Card re-verification on restore."""

    async def test_unknown_run_is_404(self):
        resp = await self.get("/api/flows/runs/run_missing")
        self.assertEqual(resp.status_code, 404)

    async def test_non_workflow_run_is_404(self):
        non_wf = store.create(self.chat["id"], {"kind": "document"})
        resp = await self.get(f"/api/flows/runs/{non_wf['id']}")
        self.assertEqual(resp.status_code, 404)

    async def test_reports_waiting_kind_and_one_based_stage(self):
        run = self.make_run(self.chat["id"], waiting={"kind": "review", "stage": 1})
        resp = await self.get(f"/api/flows/runs/{run['id']}")
        self.assertEqual(resp.status_code, 200)
        # name·total_stages·stage_index(0부터)는 2026-09-30 진행 표시용 / progress fields added 2026-09-30
        self.assertEqual(resp.json(), {"run_id": run["id"], "chat_id": self.chat["id"], "state": "needs_input",
                                       "waiting_kind": "review", "stage": 2,
                                       "flow_id": FLOW["id"], "flow_name": FLOW["name"],
                                       "name": FLOW["name"], "total_stages": 2, "stage_index": 1})

    async def test_without_waiting_reports_cursor_as_stage_and_blank_waiting_kind(self):
        run = self.make_run(self.chat["id"], waiting=None, state="ready", cursor=1)
        resp = await self.get(f"/api/flows/runs/{run['id']}")
        body = resp.json()
        self.assertEqual(body["waiting_kind"], "")
        self.assertEqual(body["stage"], 1)
        self.assertEqual((body["name"], body["total_stages"], body["stage_index"]), (FLOW["name"], 2, 1))

    async def test_stage_index_is_zero_based_and_clamped_to_the_last_stage(self):
        # stage 는 종전 값(카드 대기 중이면 card.stage 와 같은 1부터 번호), stage_index 는 0부터 — 옛 스냅샷의 cursor == 단계 수는 마지막 단계로
        # stage keeps its old value (card.stage while a card waits); stage_index is 0-based, an old cursor == stage count clamps
        gate = self.make_run(self.chat["id"], waiting={"kind": "gate", "stage": 0}, cursor=1)
        body = (await self.get(f"/api/flows/runs/{gate['id']}")).json()
        self.assertEqual((body["stage"], body["stage_index"], body["total_stages"]), (1, 0, 2))
        parked = self.make_run(self.chat["id"], waiting=None, state="completed", cursor=2)
        body = (await self.get(f"/api/flows/runs/{parked['id']}")).json()
        self.assertEqual((body["stage"], body["stage_index"]), (2, 1))


class SummaryTests(FlowsApiTestBase):
    """GET /api/flows/{flow_id}/summary — AI 요약 캐싱 + 비구성원 403. AI-summary caching + 403 for non-members."""

    async def test_unknown_flow_is_404(self):
        resp = await self.get("/api/flows/fl_missing/summary")
        self.assertEqual(resp.status_code, 404)

    async def test_non_member_numeric_actor_is_403(self):
        with patch.object(flows, "find_flow", return_value=FLOW), \
             patch.object(access, "member_groups", return_value=[]):
            resp = await self.get(f"/api/flows/{FLOW['id']}/summary?acting_user_id=42")
        self.assertEqual(resp.status_code, 403)

    async def test_member_actor_passes_and_llm_summary_is_cached(self):
        with patch.object(flows, "find_flow", return_value=FLOW), \
             patch.object(access, "member_groups", return_value=[{"id": "og9"}]), \
             patch.object(flows.llm, "generate", return_value="한 줄 요약") as gen:
            r1 = await self.get(f"/api/flows/{FLOW['id']}/summary?acting_user_id=42")
            r2 = await self.get(f"/api/flows/{FLOW['id']}/summary?acting_user_id=42")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["summary"], "한 줄 요약")
        self.assertEqual(r2.json()["summary"], "한 줄 요약")
        gen.assert_called_once()   # 두번째 호출은 llm_cache 적중 / the second call hits llm_cache

    async def test_llm_exception_falls_back_to_flow_description(self):
        flow = {**FLOW, "id": "fl_fallback", "description": "설명 폴백 문장"}
        with patch.object(flows, "find_flow", return_value=flow), \
             patch.object(flows.llm, "generate", side_effect=RuntimeError("model down")):
            resp = await self.get(f"/api/flows/{flow['id']}/summary")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["summary"], "설명 폴백 문장")


class RunCancelsStaleRunsTests(FlowsApiTestBase):
    """POST /api/flows/run — 새 실행 전 카드 대기 run 취소 + 카드 응답 완료 처리.
    Before a new run, cancel card-waiting runs and mark their cards answered."""

    async def test_stale_card_waiting_run_is_cancelled_and_its_card_marked_answered(self):
        old = self.make_run(self.chat["id"], waiting={"kind": "gate", "stage": 0})
        db.add_message(self.chat["id"], "assistant", "이전 카드",
                       {"kind": "flow_gate", "card": {}, "resume_id": old["id"]})

        async def fake_run_flow(*a, **kw):
            yield {"type": "done"}

        with patch.object(flows, "find_flow", return_value=FLOW), \
             patch.object(flows, "run_flow", fake_run_flow):
            resp = await self.post("/api/flows/run",
                                   {"flow_id": FLOW["id"], "chat_id": self.chat["id"], "message": "질문"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/event-stream", resp.headers["content-type"])
        self.assertEqual(store.get(old["id"])["state"], "cancelled")
        row = next(m for m in db.list_messages(self.chat["id"]) if (m.get("meta") or {}).get("kind") == "flow_gate")
        self.assertTrue(row["meta"]["answered"])

    async def test_unknown_flow_404_and_empty_message_422(self):
        resp = await self.post("/api/flows/run",
                               {"flow_id": "fl_ghost", "chat_id": self.chat["id"], "message": "질문"})
        self.assertEqual(resp.status_code, 404)
        with patch.object(flows, "find_flow", return_value=FLOW):
            resp = await self.post("/api/flows/run",
                                   {"flow_id": FLOW["id"], "chat_id": self.chat["id"], "message": "   "})
        self.assertEqual(resp.status_code, 422)

    async def test_non_member_numeric_actor_is_403(self):
        with patch.object(flows, "find_flow", return_value=FLOW), \
             patch.object(access, "member_groups", return_value=[]):
            resp = await self.post("/api/flows/run",
                                   {"flow_id": FLOW["id"], "chat_id": self.chat["id"], "message": "질문",
                                    "acting_user_id": "42"})
        self.assertEqual(resp.status_code, 403)


class ChatFlowModeTests(FlowsApiTestBase):
    """PATCH/POST /api/chats — 워크플로우 모드(flow_id/flow_name) 저장·해제. Persisting/clearing workflow mode."""

    async def test_patch_flow_id_empty_clears_mode_and_cancels_pending_runs(self):
        chat = db.create_chat("워크플로우 채팅", "사내", flow_id=FLOW["id"], flow_name=FLOW["name"])
        old = self.make_run(chat["id"], waiting={"kind": "gate", "stage": 0})
        db.add_message(chat["id"], "assistant", "카드", {"kind": "flow_gate", "card": {}, "resume_id": old["id"]})

        resp = await self.patch_chat(chat["id"], {"flow_id": ""})

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["flow_id"], "")
        self.assertEqual(body["flow_name"], "")
        self.assertEqual(db.get_chat(chat["id"])["flow_id"], "")
        self.assertEqual(store.get(old["id"])["state"], "cancelled")
        row = next(m for m in db.list_messages(chat["id"]) if (m.get("meta") or {}).get("kind") == "flow_gate")
        self.assertTrue(row["meta"]["answered"])

    async def test_patch_flow_id_sets_name_from_the_stored_flow_not_the_request(self):
        chat = db.create_chat("채팅", "사내")
        with patch.object(flows, "find_flow", return_value=FLOW):
            resp = await self.patch_chat(chat["id"], {"flow_id": FLOW["id"], "flow_name": "요청측 이름(무시됨)"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["flow_id"], FLOW["id"])
        self.assertEqual(body["flow_name"], FLOW["name"])
        self.assertEqual(db.get_chat(chat["id"])["flow_name"], FLOW["name"])

    async def test_patch_unknown_flow_id_is_404(self):
        chat = db.create_chat("채팅", "사내")
        with patch.object(flows, "find_flow", return_value=None):
            resp = await self.patch_chat(chat["id"], {"flow_id": "fl_ghost"})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(db.get_chat(chat["id"])["flow_id"], "")

    async def test_create_chat_with_flow_id_stores_it(self):
        with patch.object(flows, "find_flow", return_value=FLOW), \
             patch.object(chats_api, "_make_title", return_value="t"):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                resp = await client.post("/api/chats", json={"first_message": "안녕", "flow_id": FLOW["id"]})
        self.assertEqual(resp.status_code, 200)
        chat = db.get_chat(resp.json()["id"])
        self.assertEqual(chat["flow_id"], FLOW["id"])
        self.assertEqual(chat["flow_name"], FLOW["name"])

    async def test_workflow_chat_is_titled_with_the_flow_name_and_its_first_row_carries_the_chip(self):
        # 2026-09-30: 워크플로우 채팅 제목 = 워크플로우 이름(최대 60자, LLM 없음), 첫 사용자 행 meta.flow {id, name, stages}.
        # 이어지는 실행의 맥락 구성은 같은 행을 다시 저장하지 않는다.
        # 2026-09-30: a workflow chat is titled with the flow name (60 chars max, no LLM) and its first user row carries
        # meta.flow {id, name, stages}; the following run's context build never stores that row again.
        long_flow = {**FLOW, "name": "  " + "가" * 70}
        with patch.object(flows, "find_flow", return_value=long_flow), \
             patch.object(chats_api, "_make_title", side_effect=AssertionError("LLM 제목 금지")) as make_title, \
             patch.object(chats_api.llm, "generate", side_effect=AssertionError("LLM 제목 금지")) as generate:
            resp = await self.post("/api/chats", {"first_message": " 재고 점검해줘 ", "flow_id": FLOW["id"],
                                                  "flow_name": "요청측 이름"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["title"], "가" * 60)
        make_title.assert_not_called()
        generate.assert_not_called()
        chat_id = resp.json()["id"]
        chip = {"flow": {"id": FLOW["id"], "name": "가" * 60, "stages": 2}}
        self.assertEqual([(m["role"], m["content"], m["meta"]) for m in db.list_messages(chat_id)],
                         [("user", "재고 점검해줘", chip)])
        flows._build_context(chat_id, "재고 점검해줘", chip)
        self.assertEqual(len(db.list_messages(chat_id)), 1)

    async def test_chat_without_a_flow_keeps_the_summarised_title(self):
        # flow_id 가 없으면(flow_name 만 와도) 종전대로 LLM 제목 요약, 첫 행에 meta 없음
        # Without a flow_id (even with a flow_name) the LLM title summary stays and the first row has no meta
        with patch.object(chats_api, "_make_title", return_value="요약 제목") as make_title:
            resp = await self.post("/api/chats", {"first_message": "안녕하세요", "flow_name": "가짜 흐름"})
        self.assertEqual(resp.json()["title"], "요약 제목")
        make_title.assert_called_once_with("안녕하세요")
        self.assertIsNone(db.list_messages(resp.json()["id"])[0]["meta"])


if __name__ == "__main__":
    unittest.main()
