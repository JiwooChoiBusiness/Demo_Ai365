"""워크플로우 단계 게이트(2026-09-11) 회귀 — 검수 질문 카드·단계 보고·실행 카드·체크포인트 재개.

실제 LLM·외부 API 는 쓰지 않는다(전부 패치). run_flow 의 외부 의존(권한·맥락·노드 실행·스트리밍·
리소스 표기)을 스텁으로 대체하고, 단계 게이트의 계약만 검증한다.

Stage-gate regression (2026-09-11) — the review question card, the stage report, the run card and the
checkpoint resumption. No real LLM or external API calls: run_flow's externals (permissions, context,
node execution, streaming, resource display) are stubbed so only the gate contract is exercised.
"""
import asyncio
import copy
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from db_fixture import isolate_db
from app import artifact_execution, db, execution_store as store, flows

# 실제 _build_context — stub_flow 가 가리는 사용자 행 저장(워크플로우 칩 meta.flow, 2026-09-30)을 볼 때 다시 끼운다
# The real _build_context: re-inserted when a test checks the user-row save (workflow chip meta.flow, 2026-09-30) that stub_flow hides
REAL_BUILD_CONTEXT = flows._build_context


async def collect(stream):
    return [event async for event in stream]


def two_stage_flow(**over) -> dict:
    """2단계(각 1작업) — 1단계는 게이트에서 멈추고, 마지막 단계는 게이트 없이 그 답변이 최종 답변이다(2026-09-29).
    Two stages (one task each) — stage 1 stops at the run card; the last stage has no gate and its answer is final."""
    return {"id": "fl_test", "name": "단계 테스트", "group": "og9", "description": "단계 게이트 데모",
            "stages": [
                {"nodes": [{"agent": "data", "resources": [], "instruction": "1단계 작업"}],
                 "answer_prompt": "1단계 보고 지침"},
                {"nodes": [{"agent": "data", "resources": [], "instruction": "2단계 작업"}],
                 "answer_prompt": "2단계 답변 지침"}], **over}


def three_stage_flow() -> dict:
    """3단계(각 1작업, 1단계는 파일 생성) — 앞 단계 기록이 쌓이는지 본다 / three stages to watch the record accumulate"""
    return {"id": "fl_three", "name": "세 단계", "group": "og9", "description": "",
            "stages": [
                {"nodes": [{"agent": "data", "resources": [], "instruction": "1단계 작업"}],
                 "answer_prompt": "", "docgen": {"format": "docx", "instruction": ""}},
                {"nodes": [{"agent": "data", "resources": [], "instruction": "2단계 작업"}], "answer_prompt": ""},
                {"nodes": [{"agent": "data", "resources": [], "instruction": "3단계 작업"}], "answer_prompt": ""}]}


# API 작업(입력값 부족) + 데이터 작업 1단계 — 검수 카드(결정적 항목 + LLM 항목) 재료
# One stage with an API task missing an input plus a data task — material for the review card
REVIEW_FLOW = {"id": "fl_api", "name": "재고 점검", "group": "og9", "description": "",
               "stages": [{"nodes": [{"agent": "api", "resources": ["cn_x"], "instruction": "", "prompt": "재고 조회"},
                                     {"agent": "data", "resources": [], "instruction": "재고 추이 분석"}],
                           "answer_prompt": ""}],
               "aggregate_instruction": "취합 지침", "docgen": None}

NEEDS_INPUT = {"status": "needs_input", "label": "재고 API", "text": "필수 입력을 알려주세요: year",
               "extras": {"missing_inputs": ["year"], "connector_id": "cn_x", "inputs": {},
                          "connector": {"id": "cn_x", "name": "재고 API", "kind": "read", "inputs": {}}}}

CONNECTOR = {"id": "cn_x", "name": "재고 API", "kind": "read", "enabled": True, "description": "재고 조회",
             "api": {"url": "https://erp.invalid/stock?year={{input.year}}",
                     "input_docs": [{"name": "year", "description": "조회 연도", "example": "2025"}]}}

LLM_QUESTIONS = {"questions": [{"id": "q1", "label": "기간", "question": "어느 기간?", "kind": "choice",
                                "options": ["이번 달", "지난 달"], "task_ids": ["stage1_1"]}]}


class StageGateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        # flows 는 임포트 시점에 DB_PATH 를 잡는다 — 실제 DB 오염 방지 / flows binds DB_PATH at import: keep the real DB out
        self.stack.enter_context(patch.object(flows, "DB_PATH", db.DB_PATH))
        self.chat = db.create_chat("워크플로우", "사내")
        # 미지정 경로가 실제 서비스에 도달하면 즉시 실패 / any unstubbed path to a real service fails at once
        self.stack.enter_context(patch("app.llm.stream", side_effect=AssertionError("unexpected LLM stream")))
        self.stack.enter_context(patch("app.flow_api_call.call", side_effect=AssertionError("unexpected external API")))
        self.astream: list[tuple] = []

    # ── 스텁 / stubs ────────────────────────────────────────────────────────
    def stub_flow(self, worker, review=None):
        """run_flow 의 외부 의존을 전부 대체한다. review = 검수 LLM(JSON) 응답 / replace run_flow's externals"""
        async def tokens(messages, system=None):
            self.astream.append((messages, system))
            yield "단계 보고 본문"

        async def smooth(text):
            yield text

        self.generate = self.stack.enter_context(
            patch("app.llm.generate", return_value=review if review is not None else {"questions": []}))
        self.stack.enter_context(patch.object(flows, "_resolve_eff", return_value=None))
        self.stack.enter_context(patch.object(flows, "_build_context", return_value=[{"role": "user", "content": "q"}]))
        self.stack.enter_context(patch.object(flows, "_run_step_node", side_effect=worker))
        self.stack.enter_context(patch.object(flows, "_astream", tokens))
        self.stack.enter_context(patch.object(flows, "_smooth", smooth))
        self.stack.enter_context(patch.object(flows, "_flow_sources", return_value=None))

    @staticmethod
    def recording_worker(calls: list, results: dict | None = None):
        """노드 실행 스텁 — 호출 인자를 기록하고 지침(없으면 종류)별 결과를 돌려준다. 예외 값이면 그대로 raise.
        Node-execution stub — records the call args and returns the mapped result (raises a mapped exception)."""
        async def worker(node, message, context, eff, prior, actor=""):
            key = (node.get("instruction") or "").strip() or node.get("agent")
            calls.append({"key": key, "message": message, "context": context,
                          "node": copy.deepcopy(node), "prior": copy.deepcopy(prior)})
            value = (results or {}).get(key)
            if isinstance(value, BaseException):
                raise value
            return copy.deepcopy(value) if value else {"status": "done", "label": key, "text": f"{key} 결과"}
        return worker

    def make_run(self, flow: dict, message: str = "q") -> dict:
        return store.create(self.chat["id"],
                            {"kind": "workflow", "flow": flow, "message": message, "actor": "", "eff": None,
                             "results": {}, "cursor": 0, "stage_state": {}, "attempts": {}})

    async def run_to_gate(self, flow: dict) -> dict:
        """1단계 실행 → 보고 → 실행 카드에서 정지한 run / run stage 1, report, stop at the run card"""
        run = self.make_run(flow)
        await collect(artifact_execution.workflow_run(flow, self.chat, "q", "", run))
        return store.get(run["id"])

    def messages(self) -> list[dict]:
        return db.list_messages(self.chat["id"])

    # ── 실행 카드(게이트) / run card ─────────────────────────────────────────
    async def test_gate_pauses_after_stage_report_and_persists_cursor(self):
        flow = two_stage_flow()
        calls: list = []
        self.stub_flow(self.recording_worker(calls))
        run = self.make_run(flow)
        events = await collect(artifact_execution.workflow_run(flow, self.chat, "q", "", run))

        types = [e["type"] for e in events]
        self.assertEqual([t for t in types if t in ("answer_head", "flow_gate", "done", "execution_result")],
                         ["execution_result", "answer_head", "flow_gate", "done", "execution_result"])
        self.assertLess(types.index("token"), types.index("flow_gate"))   # 보고 본문 → 카드 순서 / report then card
        self.assertEqual(events[-1]["state"], "needs_input")
        self.assertEqual([c["key"] for c in calls], ["1단계 작업"])        # 2단계 작업자는 실행되지 않는다 / stage-2 worker never ran
        saved = store.get(run["id"])
        self.assertEqual(saved["state"], "needs_input")
        self.assertEqual(saved["snapshot"]["waiting"], {"kind": "gate", "stage": 0})
        self.assertEqual(saved["snapshot"]["cursor"], 1)
        report = saved["snapshot"]["stage_state"]["0"]["report"]
        rows = {m["id"]: m for m in self.messages()}
        self.assertEqual(rows[report["message_id"]]["meta"]["flow_stage"], 1)
        self.assertEqual(rows[report["message_id"]]["meta"]["flow_attempt"], 1)   # 첫 답변(2026-09-30) / the first answer
        self.assertEqual(rows[report["message_id"]]["content"], report["text"])
        card = next(m for m in rows.values() if (m.get("meta") or {}).get("kind") == "flow_gate")
        self.assertEqual(card["meta"]["card"]["run_id"], run["id"])
        self.assertEqual(card["meta"]["card"]["next_tasks"], ["데이터 분석 · 2단계 작업"])

    async def test_gate_run_resumes_next_stage_with_note_and_stage_scoped_cards(self):
        flow = two_stage_flow()
        calls: list = []
        self.stub_flow(self.recording_worker(calls))
        run = await self.run_to_gate(flow)
        self.assertFalse(artifact_execution.resume_workflow(run, {"kind": "flow_gate", "action": "run", "note": "서울만"}))
        calls.clear()

        run = store.get(run["id"])
        events = await collect(artifact_execution.workflow_run(run["snapshot"]["flow"], self.chat, "q", "", run))

        # 재개 세그먼트는 1단계를 트리에만 완료로 표시하고(카드 재생 없음 — 카드는 단계별로만, 2026-09-11) 2단계만 실제로 실행한다
        # The resumed segment marks stage 1 done in the tree only (no card replay: cards are per stage, 2026-09-11)
        # and really runs only stage 2
        self.assertEqual([(e["stage"], e["status"]) for e in events if e["type"] == "stage_status"],
                         [(1, "done"), (2, "running"), (2, "done")])
        tree = next(e for e in events if e["type"] == "task_tree")
        self.assertEqual([t["id"] for t in tree["tasks"]], ["data"])          # 이 세그먼트가 실행할 단계의 카드만 / only this segment's stage
        self.assertEqual(tree["query"], "q")
        start = next(e for e in events if e["type"] == "stage_status" and e["status"] == "running")
        self.assertEqual([c["id"] for c in start["cards"]], ["data"])         # 단계 시작 이벤트가 카드를 싣는다 / stage start carries its cards
        self.assertEqual([e["status"] for e in events if e["type"] == "agent_status"], ["running", "done"])
        self.assertEqual([c["key"] for c in calls], ["2단계 작업"])
        self.assertIn("서울만", calls[0]["message"])
        self.assertTrue(any("[사용자 추가 지시] 서울만" in m["content"] for m in calls[0]["context"]))
        # 사용자 행(2026-09-30): "N단계 실행: 지시" + meta.flow_step(실행할 단계, 0부터) / "N단계 실행: note" + meta.flow_step (0-based)
        row = next(m for m in self.messages() if m["role"] == "user" and m["content"] == "2단계 실행: 서울만")
        self.assertEqual(row["meta"], {"flow_step": {"stage": 1}})
        self.assertEqual(store.get(run["id"])["state"], "completed")

    async def test_gate_cancel_ends_the_run_with_a_notice(self):
        flow = two_stage_flow()
        calls: list = []
        self.stub_flow(self.recording_worker(calls))
        run = await self.run_to_gate(flow)

        self.assertTrue(artifact_execution.resume_workflow(run, {"kind": "flow_gate", "action": "cancel"}))
        self.assertEqual(store.get(run["id"])["state"], "cancelled")
        self.assertTrue(any(m["role"] == "assistant" and m["content"] == "워크플로우 실행을 중단했습니다."
                            for m in self.messages()))
        card = next(m for m in self.messages() if (m.get("meta") or {}).get("kind") == "flow_gate")
        self.assertTrue(card["meta"]["answered"])
        self.assertEqual(await collect(artifact_execution.cancelled_events(run)),
                         [{"type": "execution_result", "state": "cancelled", "run_id": run["id"], "artifact": False}])
        self.assertEqual([c["key"] for c in calls], ["1단계 작업"])   # 2단계는 실행되지 않는다 / stage 2 never ran

    async def test_last_stage_answers_with_its_prompt_and_every_earlier_record(self):
        # 2026-09-29: 별도 최종 취합 없이 마지막 단계의 답변이 최종 답변이다. 재료 = 앞 단계 기록(작업 결과·단계 답변) + 이 단계
        # 추가 지시 + 이 단계 결과. 게이트 카드는 없다.
        # 2026-09-29: no separate final aggregation; the last stage's answer is the final answer, built from the earlier-stage
        # record (task results, stage answers) + this stage's note + this stage's results. No run card.
        flow = two_stage_flow()
        calls: list = []
        self.stub_flow(self.recording_worker(calls))
        run = await self.run_to_gate(flow)
        artifact_execution.resume_workflow(run, {"kind": "flow_gate", "action": "run", "note": "서울만"})
        self.astream.clear()

        run = store.get(run["id"])
        events = await collect(artifact_execution.workflow_run(run["snapshot"]["flow"], self.chat, "q", "", run))

        self.assertNotIn("flow_gate", [e["type"] for e in events])
        self.assertEqual(len(self.astream), 1)                          # 마지막 단계 답변 1회뿐 / only the last stage's answer
        messages, system = self.astream[0]
        body = messages[-1]["content"]
        self.assertIn("[앞 단계 기록]\n[1단계]", body)
        self.assertIn("  지침: 1단계 작업", body)
        self.assertIn("1단계 작업 결과", body)
        self.assertIn("- 1단계 답변:\n단계 보고 본문", body)            # 앞 단계 답변이 재료 / the earlier stage answer is material
        self.assertIn("[사용자 추가 지시] 서울만", body)
        self.assertIn("[2단계 실행 결과]\n- 작업 1 · 2단계 작업 · 완료", body)
        self.assertIn("[최종 답변]", system)
        self.assertIn("[답변 지침] 2단계 답변 지침", system)
        self.assertNotIn("[단계 보고]", system)
        self.assertNotIn("1단계 보고 지침", system)
        self.assertEqual(events[-1]["state"], "completed")
        saved = store.get(run["id"])
        report = saved["snapshot"]["stage_state"]["1"]["report"]
        self.assertEqual(saved["snapshot"]["answer"], report)            # 발송 확인 본문 슬롯 / the send-confirm body slot
        self.assertEqual(saved["snapshot"]["cursor"], 1)                  # 커서는 마지막 단계를 넘지 않는다 / never past the last stage
        row = next(m for m in self.messages() if m["id"] == report["message_id"])
        self.assertEqual(row["meta"]["flow_stage"], 2)
        # 파일 재료(meta.steps)는 누적 — 이번 단계가 먼저, 그다음 앞 단계(답변 → 작업) / cumulative file material, this stage first
        self.assertEqual([s["label"] for s in row["meta"]["steps"]], ["2단계 2단계 작업", "1단계 보고", "1단계 1단계 작업"])

    async def test_each_stage_answer_uses_its_own_prompt(self):
        flow = two_stage_flow()
        calls: list = []
        self.stub_flow(self.recording_worker(calls))
        run = await self.run_to_gate(flow)

        stage_messages, stage_system = self.astream[0]
        self.assertIn("[답변 지침] 1단계 보고 지침", stage_system)
        self.assertIn("[단계 보고]", stage_system)
        self.assertNotIn("2단계 답변 지침", stage_system)       # 다른 단계의 지침은 섞이지 않는다 / no other stage's prompt
        self.assertNotIn("[최종 답변]", stage_system)
        self.assertIn("[1단계 실행 결과]", stage_messages[-1]["content"])
        self.assertNotIn("[앞 단계 기록]", stage_messages[-1]["content"])   # 1단계에는 앞 단계가 없다 / nothing before stage 1
        self.assertNotIn("2단계", stage_messages[-1]["content"])

        artifact_execution.resume_workflow(run, {"kind": "flow_gate", "action": "run", "note": ""})
        run = store.get(run["id"])
        await collect(artifact_execution.workflow_run(run["snapshot"]["flow"], self.chat, "q", "", run))
        self.assertIn("[답변 지침] 2단계 답변 지침", self.astream[-1][1])
        self.assertNotIn("1단계 보고 지침", self.astream[-1][1])

    async def test_stage_three_holds_every_record_of_stages_one_and_two(self):
        # 2026-09-29 사용자 지시: 3단계는 1·2단계의 모든 메타데이터를 가진다 — 작업 결과(원문 전체)·검수 답변·추가 지시·
        # 단계 답변·생성 파일. 종전 6,000자 자르기가 없어졌는지도 본다.
        # User request 2026-09-29: stage 3 holds all metadata of stages 1 and 2: full raw results, review answers, notes, stage
        # answers and files. Also checks that the old 6,000-character cut is gone.
        flow = three_stage_flow()
        calls: list = []
        long_text = "가" * 9000 + "끝"
        results = {"1단계 작업": {"status": "done", "label": "1단계 작업", "text": long_text}}
        reviews = iter([{"questions": [{"id": "q1", "label": "기간", "question": "어느 기간?", "kind": "text",
                                         "task_ids": []}]}])
        self.stub_flow(self.recording_worker(calls, results))
        self.generate.side_effect = lambda *a, **k: next(reviews, {"questions": []})
        self.stub_docgen()
        run = self.make_run(flow)
        events = await collect(artifact_execution.workflow_run(flow, self.chat, "q", "", run))
        self.assertIn("flow_question", [e["type"] for e in events])      # 1단계 검수 질문 / the stage-1 review question
        run = store.get(run["id"])
        self.assertFalse(artifact_execution.resume_workflow(run, {"kind": "flow_question", "answers": {"q1": "지난 달"}}))
        run = store.get(run["id"])
        await collect(artifact_execution.workflow_run(run["snapshot"]["flow"], self.chat, "q", "", run))   # 1단계 답변·파일·카드
        run = store.get(run["id"])
        self.assertEqual(run["snapshot"]["waiting"], {"kind": "gate", "stage": 0})
        artifact_execution.resume_workflow(run, {"kind": "flow_gate", "action": "run", "note": "서울만"})
        run = store.get(run["id"])
        await collect(artifact_execution.workflow_run(run["snapshot"]["flow"], self.chat, "q", "", run))   # 2단계 → 카드
        run = store.get(run["id"])
        artifact_execution.resume_workflow(run, {"kind": "flow_gate", "action": "run", "note": ""})
        calls.clear()
        self.astream.clear()
        run = store.get(run["id"])
        await collect(artifact_execution.workflow_run(run["snapshot"]["flow"], self.chat, "q", "", run))   # 3단계 → 최종

        self.assertEqual([c["key"] for c in calls], ["3단계 작업"])
        ctx = next(m["content"] for m in calls[0]["context"] if m["content"].startswith("[앞 단계 기록]"))
        for part in ("[1단계]", long_text, "- 검수 질문에 대한 사용자 답변:\n  - 어느 기간?: 지난 달",
                     "- 1단계 답변:\n단계 보고 본문", "- 생성 파일: Word · stage.docx",
                     "[2단계]", "- 실행 전 사용자 추가 지시: 서울만", "2단계 작업 결과", "- 2단계 답변:\n단계 보고 본문"):
            self.assertIn(part, ctx)
        self.assertLess(ctx.index("[1단계]"), ctx.index("[2단계]"))
        # 마지막 단계 답변도 같은 기록을 받는다 / the last stage's answer gets the same record
        self.assertIn("- 실행 전 사용자 추가 지시: 서울만", self.astream[0][0][-1]["content"])
        self.assertIn(long_text, self.astream[0][0][-1]["content"])
        self.assertEqual(store.get(run["id"])["state"], "completed")

    async def test_last_stage_file_uses_the_final_slot_and_the_flow_name(self):
        # 마지막 단계 파일(2026-09-29) = 종전 최종 파일 경로(done.docgen → 서버 래퍼 최종 슬롯, 발송 첨부), 이름은 워크플로우 이름
        # The last stage's file (2026-09-29) takes the old final-file path (done.docgen → the wrapper's final slot, the
        # delivery attachment) and is named after the workflow
        flow = two_stage_flow()
        flow["stages"][1]["docgen"] = {"format": "pptx", "instruction": "간결하게"}
        calls: list = []
        self.stub_flow(self.recording_worker(calls))
        doc_calls = self.stub_docgen()
        run = await self.run_to_gate(flow)
        self.assertEqual(doc_calls, [])                                   # 1단계에는 파일이 없다 / no file on stage 1
        artifact_execution.resume_workflow(run, {"kind": "flow_gate", "action": "run", "note": ""})
        run = store.get(run["id"])
        events = await collect(artifact_execution.workflow_run(run["snapshot"]["flow"], self.chat, "q", "", run))

        self.assertEqual(doc_calls, [{"fmt": "pptx", "topic": "단계 테스트", "source": "context",
                                      "instruction": "간결하게", "save_user": False}])
        self.assertFalse(any(e.get("docgen") for e in events))            # 래퍼가 명세를 소비한다 / consumed by the wrapper
        saved = store.get(run["id"])
        self.assertEqual(saved["snapshot"]["artifact"]["id"], "d_stage")  # 최종 슬롯 / the final slot
        self.assertNotIn("artifact", saved["snapshot"]["stage_state"].get("1", {}))
        self.assertEqual(saved["state"], "completed")

    async def test_last_stage_file_needs_every_stage_clean_like_the_old_final_file(self):
        # 마지막 단계 파일은 종전 최종 파일 조건(전 단계 작업 정상)을 따른다 — 1단계 실패면 만들지 않는다(2026-09-29 리뷰)
        # The last stage's file keeps the old final-file condition (every stage clean): a stage-1 failure means no file
        flow = two_stage_flow()
        flow["stages"][1]["docgen"] = {"format": "pptx", "instruction": ""}
        calls: list = []
        self.stub_flow(self.recording_worker(calls, {"1단계 작업": {"status": "failed", "label": "1단계 작업", "text": "실패"}}))
        doc_calls = self.stub_docgen()
        run = await self.run_to_gate(flow)
        artifact_execution.resume_workflow(run, {"kind": "flow_gate", "action": "run", "note": ""})
        run = store.get(run["id"])
        await collect(artifact_execution.workflow_run(run["snapshot"]["flow"], self.chat, "q", "", run))
        self.assertEqual(doc_calls, [])
        self.assertNotIn("artifact", store.get(run["id"])["snapshot"])

    async def test_api_result_excluded_from_answers_never_reaches_later_prompts(self):
        # '답변에 포함'을 끈 API 결과(글 없음 + 데이터·출력값)는 뒷 단계 맥락·단계 답변에 실리지 않는다 — 종전 단계 결과 블록과 같다
        # An API result excluded from answers (no text + data/outputs) never reaches later contexts or answers, as before
        flow = two_stage_flow()
        secret = {"status": "done", "label": "인사 API", "text": "", "data": {"rrn": "900101-1234567"},
                  "outputs": {"rrn": "900101-1234567"}, "extras": {"api": {"include_in_answer": False}}}
        calls: list = []
        self.stub_flow(self.recording_worker(calls, {"1단계 작업": secret}))
        run = await self.run_to_gate(flow)
        self.assertNotIn("900101", self.astream[0][0][-1]["content"])      # 1단계 답변 / the stage-1 answer
        artifact_execution.resume_workflow(run, {"kind": "flow_gate", "action": "run", "note": ""})
        calls.clear()
        run = store.get(run["id"])
        await collect(artifact_execution.workflow_run(run["snapshot"]["flow"], self.chat, "q", "", run))
        ctx = "\n".join(m["content"] for m in calls[0]["context"])
        self.assertNotIn("900101", ctx)                                     # 2단계 작업 맥락 / the stage-2 task context
        self.assertIn("(API 설정에 따라 답변 재료에서 뺀 결과입니다)", ctx)
        self.assertNotIn("900101", self.astream[-1][0][-1]["content"])      # 최종 답변 / the final answer
        # {{stepN}} 변수 재료는 그대로 / the {{stepN}} variable material is unchanged
        self.assertEqual(calls[0]["prior"][0]["data"], {"rrn": "900101-1234567"})

    async def test_legacy_final_prompt_and_file_move_onto_the_last_stage(self):
        # 폐지 전 스냅샷(flow.aggregate_instruction·flow.docgen)으로 재개해도 마지막 단계가 그 지침과 파일을 쓴다(2026-09-29)
        # A snapshot from before the retirement (flow.aggregate_instruction/docgen) still uses them on the last stage
        flow = two_stage_flow(aggregate_instruction="옛 최종 지침 — 표로", docgen={"format": "pdf", "instruction": ""})
        flow["stages"][1]["answer_prompt"] = ""
        calls: list = []
        self.stub_flow(self.recording_worker(calls))
        doc_calls = self.stub_docgen()
        run = await self.run_to_gate(flow)
        artifact_execution.resume_workflow(run, {"kind": "flow_gate", "action": "run", "note": ""})
        run = store.get(run["id"])
        await collect(artifact_execution.workflow_run(run["snapshot"]["flow"], self.chat, "q", "", run))
        self.assertIn("[답변 지침] 옛 최종 지침: 표로", self.astream[-1][1])   # em dash 는 ': ' 로 / the em dash becomes ': '
        self.assertEqual([c["fmt"] for c in doc_calls], ["pdf"])
        self.assertEqual(store.get(run["id"])["state"], "completed")

    async def test_old_snapshot_parked_in_the_final_aggregation_reuses_its_answer(self):
        # 종전 최종 취합 중이던 스냅샷(cursor == 단계 수, snapshot.answer)은 마지막 단계로 다시 들어가 저장된 답변을 그대로 쓴다(LLM 없음)
        # An old snapshot parked in the final aggregation (cursor == stage count, snapshot.answer) re-enters the last stage and
        # reuses the saved answer (no LLM)
        flow = two_stage_flow(aggregate_instruction="옛 최종 지침")
        calls: list = []
        self.stub_flow(self.recording_worker(calls))
        mid = db.add_message(self.chat["id"], "assistant", "옛 최종 답변", {"source": "워크플로우|단계 테스트"})
        run = store.create(self.chat["id"], {
            "kind": "workflow", "flow": flow, "message": "q", "actor": "", "eff": None,
            "results": {"stage1_1": {"status": "done", "label": "1단계 작업", "text": "a"},
                        "stage2_1": {"status": "done", "label": "2단계 작업", "text": "b"}},
            "cursor": 2, "stage_state": {"0": {"reviewed": True, "report": {"text": "1단계 답변", "message_id": None}},
                                         "1": {"reviewed": True}},
            "attempts": {}, "answer": {"text": "옛 최종 답변", "message_id": mid}})

        events = await collect(artifact_execution.workflow_run(flow, self.chat, "q", "", run))

        self.assertEqual(calls, [])                                       # 저장 결과 재사용 / saved results reused
        self.assertEqual(self.astream, [])                                # 답변을 다시 만들지 않는다 / no regeneration
        self.assertIn({"type": "token", "text": "옛 최종 답변"}, events)
        self.assertEqual(next(e for e in events if e["type"] == "done")["message_id"], mid)
        self.assertEqual(events[-1]["state"], "completed")

    # ── 검수 질문 카드 / review question card ────────────────────────────────
    async def test_review_merges_missing_inputs_with_llm_questions(self):
        calls: list = []
        self.stub_flow(self.recording_worker(calls, {"api": NEEDS_INPUT}), review=LLM_QUESTIONS)
        self.stack.enter_context(patch("app.connectors.get_connector", return_value=CONNECTOR))
        run = self.make_run(REVIEW_FLOW)

        events = await collect(artifact_execution.workflow_run(REVIEW_FLOW, self.chat, "q", "", run))

        cards = [e for e in events if e["type"] == "flow_question"]
        self.assertEqual(len(cards), 1)                     # 부족 항목은 카드 1장에 모인다 / one card gathers every item
        items = cards[0]["card"]["items"]
        self.assertEqual([i["id"] for i in items], ["in_1_year", "q1"])   # 결정적 항목이 먼저 / deterministic items first
        self.assertTrue(items[0]["required"])
        self.assertEqual((items[0]["hint"], items[0]["placeholder"]), ("조회 연도", "2025"))
        self.assertEqual(items[1], {"id": "q1", "label": "기간", "question": "어느 기간?", "kind": "choice",
                                    "options": ["이번 달", "지난 달"], "required": False, "hint": "", "placeholder": ""})
        self.assertEqual(self.generate.call_count, 1)       # 검수 LLM 은 단계당 1회 / one review call per stage
        saved = store.get(run["id"])
        self.assertEqual(saved["state"], "needs_input")
        self.assertEqual(saved["snapshot"]["waiting"]["kind"], "review")
        self.assertEqual(saved["snapshot"]["waiting"]["stage"], 0)
        row = next(m for m in self.messages() if (m.get("meta") or {}).get("kind") == "flow_question")
        self.assertEqual(row["meta"]["card"]["run_id"], run["id"])

    async def test_review_answers_rerun_only_the_flagged_task(self):
        calls: list = []
        results = {"api": NEEDS_INPUT}
        self.stub_flow(self.recording_worker(calls, results), review=LLM_QUESTIONS)
        self.stack.enter_context(patch("app.connectors.get_connector", return_value=CONNECTOR))
        run = self.make_run(REVIEW_FLOW)
        await collect(artifact_execution.workflow_run(REVIEW_FLOW, self.chat, "q", "", run))

        run = store.get(run["id"])
        self.assertFalse(artifact_execution.resume_workflow(
            run, {"kind": "flow_question", "answers": {"in_1_year": "2026", "q1": "지난 달"}}))
        snap = store.get(run["id"])["snapshot"]
        self.assertNotIn("stage1_1", snap["results"])       # 표시된 작업만 결과를 버린다 / only flagged results are dropped
        self.assertIn("stage1_2", snap["results"])
        self.assertEqual(snap["attempts"], {"stage1_1": 1})
        node = snap["flow"]["stages"][0]["nodes"][0]
        self.assertEqual(node["_provided_inputs"], {"year": "2026"})
        self.assertEqual(node["_resolved_connector"], "cn_x")
        self.assertTrue(snap["stage_state"]["0"]["reviewed"])

        # 재개 — 검수는 다시 하지 않고(LLM 재호출 금지) 표시되지 않은 작업은 저장 결과를 재사용한다
        # Resume — no second review (LLM must not be called) and the unflagged task reuses its saved result
        results["api"] = {"status": "done", "label": "재고 API", "text": "재고 42"}
        calls.clear()
        run = store.get(run["id"])
        with patch("app.llm.generate", side_effect=AssertionError("검수 LLM 재호출 금지")):
            await collect(artifact_execution.workflow_run(run["snapshot"]["flow"], self.chat, "q", "", run))
        self.assertEqual([c["key"] for c in calls], ["api"])
        self.assertEqual(calls[0]["node"]["_provided_inputs"], {"year": "2026"})
        self.assertEqual(store.get(run["id"])["state"], "completed")

    def test_review_llm_cannot_flag_an_action_api_task(self):
        # 실행형 API 작업은 검수 답변으로 재실행되지 않는다(외부 효과 중복 방지) / action APIs are never re-run from a review answer
        nodes = [{"agent": "api", "resources": ["cn_act"], "prompt": "주문 실행"},
                 {"agent": "data", "resources": [], "instruction": "매출 분석"}]
        finished = [{"_ni": 0, "_node": nodes[0], "status": "done", "text": "주문 완료", "label": "주문 API",
                     "extras": {"connector": {"id": "cn_act", "name": "주문 API", "kind": "action"}}},
                    {"_ni": 1, "_node": nodes[1], "status": "done", "text": "분석 결과", "label": "데이터 분석"}]
        out = {"questions": [{"id": "q1", "label": "대상", "question": "어느 지점?", "kind": "text",
                              "task_ids": ["stage1_1", "stage1_2"]}]}
        with patch("app.llm.generate", return_value=out):
            questions = flows._review_llm(0, nodes, finished, "주문해줘", [], [])
        self.assertEqual(questions[0]["task_ids"], ["stage1_2"])
        self.assertFalse(questions[0]["required"])

    async def test_review_llm_failure_still_asks_for_missing_inputs(self):
        calls: list = []
        self.stub_flow(self.recording_worker(calls, {"api": NEEDS_INPUT}))
        self.stack.enter_context(patch("app.connectors.get_connector", return_value=CONNECTOR))
        run = self.make_run(REVIEW_FLOW)

        with patch("app.llm.generate", side_effect=RuntimeError("model error")), \
                self.assertLogs("ai365.flows", level="WARNING"):
            events = await collect(artifact_execution.workflow_run(REVIEW_FLOW, self.chat, "q", "", run))

        card = next(e for e in events if e["type"] == "flow_question")["card"]
        self.assertEqual([i["id"] for i in card["items"]], ["in_1_year"])
        self.assertTrue(card["items"][0]["required"])
        self.assertEqual(store.get(run["id"])["state"], "needs_input")

    # ── 체크포인트 / checkpoints ─────────────────────────────────────────────
    async def test_stop_mid_stage_keeps_results_and_cursor(self):
        flow = two_stage_flow()
        calls: list = []
        results: dict = {}
        self.stub_flow(self.recording_worker(calls, results))
        run = await self.run_to_gate(flow)
        artifact_execution.resume_workflow(run, {"kind": "flow_gate", "action": "run", "note": ""})
        results["2단계 작업"] = asyncio.CancelledError()   # STOP = 작업 취소 / STOP cancels the running task

        run = store.get(run["id"])
        with self.assertRaises(asyncio.CancelledError):
            await collect(artifact_execution.workflow_run(run["snapshot"]["flow"], self.chat, "q", "", run))

        saved = store.get(run["id"])
        self.assertEqual(saved["state"], "interrupted")
        self.assertEqual(saved["snapshot"]["cursor"], 1)                 # 커서는 앞으로 가지 않는다 / cursor never advances
        self.assertEqual(saved["snapshot"]["results"]["stage1_1"]["text"], "1단계 작업 결과")
        self.assertNotIn("stage2_1", saved["snapshot"]["results"])
        self.assertEqual(saved["snapshot"]["stage_state"]["0"]["report"]["text"], "단계 보고 본문")

    # ── 단계별 파일 생성(2026-09-14) / per-stage file output ─────────────────────────────────────────
    def stub_docgen(self, fail=False):
        """run_docgen 스텁 — 호출 인자를 기록하고 doc_meta + done(또는 error)을 낸다 / run_docgen stub recording its call"""
        calls: list = []

        async def fake_run_docgen(chat, message, fmt, topic, style, length, source="general", acting_user_id="",
                                  instruction="", save_user=True):
            calls.append({"fmt": fmt, "topic": topic, "source": source, "instruction": instruction, "save_user": save_user})
            if fail:
                yield {"type": "error", "detail": "생성 실패"}
                return
            yield {"type": "doc_meta", "doc_id": "d_stage", "format": fmt, "filename": "stage.docx", "topic": topic,
                   "style": style, "total": 1, "source": source}
            yield {"type": "done", "message_id": None}
        self.stack.enter_context(patch.object(artifact_execution.docgen, "run_docgen", fake_run_docgen))
        return calls

    async def test_stage_docgen_runs_after_the_report_and_before_the_gate_card(self):
        flow = two_stage_flow()
        flow["stages"][0]["docgen"] = {"format": "docx", "instruction": "표 중심"}
        calls: list = []
        self.stub_flow(self.recording_worker(calls))
        doc_calls = self.stub_docgen()
        run = self.make_run(flow)
        events = await collect(artifact_execution.workflow_run(flow, self.chat, "q", "", run))

        types = [e["type"] for e in events]
        # 보고 done → 파일 세그먼트(doc) → 빈 세그먼트 → 실행 카드 → needs_input / report done → file segment → new segment → run card
        self.assertEqual([t for t in types if t in ("answer_head", "done", "segment_start", "doc_meta", "flow_gate", "execution_result")],
                         ["execution_result", "answer_head", "done", "segment_start", "doc_meta", "done", "segment_start", "flow_gate", "execution_result"])
        self.assertNotIn("stage_docgen", types)   # 래퍼가 소비한다 / consumed by the wrapper
        seg_doc = next(e for e in events if e["type"] == "segment_start" and e.get("doc"))
        self.assertEqual((seg_doc["doc"]["format"], seg_doc["doc"]["topic"], seg_doc["doc"]["save_user"]),
                         ("docx", "단계 테스트 (1단계)", False))
        self.assertEqual(doc_calls, [{"fmt": "docx", "topic": "단계 테스트 (1단계)", "source": "context",
                                      "instruction": "표 중심", "save_user": False}])
        saved = store.get(run["id"])
        self.assertEqual(saved["state"], "needs_input")
        self.assertEqual(saved["snapshot"]["stage_state"]["0"]["artifact"]["id"], "d_stage")   # 단계 슬롯 / stage slot
        self.assertNotIn("artifact", saved["snapshot"])                                          # 최종 슬롯은 비어 있다 / final slot untouched
        self.assertEqual([c["key"] for c in calls], ["1단계 작업"])

    async def test_stage_docgen_is_skipped_when_a_stage_task_failed(self):
        # 옛 flow.docgen 은 마지막 단계로 옮겨지므로(2026-09-29) 1단계 실패와 무관하다 / the legacy flow.docgen moves to the last stage
        flow = two_stage_flow(docgen={"format": "pptx", "instruction": ""})
        flow["stages"][0]["docgen"] = {"format": "docx", "instruction": ""}
        calls: list = []
        self.stub_flow(self.recording_worker(calls, {"1단계 작업": {"status": "failed", "label": "1단계 작업", "text": "실패"}}))
        doc_calls = self.stub_docgen()
        run = self.make_run(flow)
        events = await collect(artifact_execution.workflow_run(flow, self.chat, "q", "", run))
        self.assertEqual(doc_calls, [])                                   # 실패한 단계는 파일을 만들지 않는다 / no file for a failed stage
        self.assertEqual([e["type"] for e in events if e["type"] in ("flow_gate", "done")], ["flow_gate", "done"])   # 종전 순서 유지 / old order kept
        self.assertEqual(store.get(run["id"])["state"], "needs_input")

    async def test_stage_docgen_failure_still_shows_the_gate_card(self):
        flow = two_stage_flow()
        flow["stages"][0]["docgen"] = {"format": "pdf", "instruction": ""}
        calls: list = []
        self.stub_flow(self.recording_worker(calls))
        self.stub_docgen(fail=True)
        run = self.make_run(flow)
        events = await collect(artifact_execution.workflow_run(flow, self.chat, "q", "", run))
        types = [e["type"] for e in events]
        self.assertIn("error", types)
        self.assertLess(types.index("error"), types.index("flow_gate"))   # 파일 오류 뒤에도 실행 카드가 온다 / the card still follows
        saved = store.get(run["id"])
        self.assertEqual(saved["state"], "needs_input")
        self.assertNotIn("artifact", saved["snapshot"]["stage_state"]["0"])

    async def test_legacy_snapshot_without_stage_keys_resumes(self):
        # 단계 게이트 이전 스냅샷(cursor/stage_state/attempts 없음)도 KeyError 없이 재개된다
        # A pre-gate snapshot (no cursor/stage_state/attempts) resumes without a KeyError
        flow = two_stage_flow()
        calls: list = []
        self.stub_flow(self.recording_worker(calls))
        run = store.create(self.chat["id"],
                           {"kind": "workflow", "flow": flow, "message": "q", "actor": "", "eff": None,
                            "results": {"stage1_1": {"status": "done", "label": "1단계 작업", "text": "저장된 결과"}}})

        events = await collect(artifact_execution.workflow_run(flow, self.chat, "q", "", run))

        self.assertEqual(calls, [])                                      # 저장된 1단계 결과 재사용 / saved result reused
        self.assertEqual([e["type"] for e in events if e["type"] == "flow_gate"], ["flow_gate"])
        snap = store.get(run["id"])["snapshot"]
        self.assertEqual(snap["cursor"], 1)
        self.assertTrue(snap["stage_state"]["0"]["reviewed"])
        self.assertEqual(snap["attempts"], {})

    # ── 추가 케이스(2026-09-11 브리핑 세부 계약) / additional cases (fine-grained contract details) ──────

    async def test_gate_card_full_shape_and_done_message_id_matches_the_report(self):
        flow = two_stage_flow()
        calls: list = []
        self.stub_flow(self.recording_worker(calls))
        run = self.make_run(flow)

        events = await collect(artifact_execution.workflow_run(flow, self.chat, "q", "", run))

        done_ev = next(e for e in events if e["type"] == "done")
        report = store.get(run["id"])["snapshot"]["stage_state"]["0"]["report"]
        self.assertEqual(done_ev["message_id"], report["message_id"])   # done은 방금 저장한 단계 보고를 가리킨다

        card = next(e for e in events if e["type"] == "flow_gate")["card"]
        self.assertEqual(card["run_id"], run["id"])
        self.assertEqual(card["resume_id"], run["id"])
        self.assertEqual(card["stage"], 1)
        self.assertEqual(card["next_stage"], 2)
        self.assertEqual(card["title"], "1단계 완료")
        self.assertEqual(card["question"], "다음 단계를 실행할까요?")
        self.assertEqual(card["summary"], "단계 보고 본문")
        self.assertEqual(card["next_label"], "2단계")
        self.assertEqual(card["next_tasks"], ["데이터 분석 · 2단계 작업"])
        self.assertEqual(card["cancel_label"], "취소")
        self.assertEqual(card["submit_label"], "실행")
        # 진행 표시·다음 단계 작업 목록(2026-09-30) / progress fields and the structured next-stage tasks
        self.assertEqual((card["flow_name"], card["total_stages"]), ("단계 테스트", 2))
        self.assertEqual(card["next_items"], [{"agent": "data", "label": "데이터 분석", "task": "2단계 작업"}])

    async def test_question_card_carries_title_intro_and_submit_label(self):
        calls: list = []
        self.stub_flow(self.recording_worker(calls, {"api": NEEDS_INPUT}), review=LLM_QUESTIONS)
        self.stack.enter_context(patch("app.connectors.get_connector", return_value=CONNECTOR))
        run = self.make_run(REVIEW_FLOW)

        events = await collect(artifact_execution.workflow_run(REVIEW_FLOW, self.chat, "q", "", run))

        card = next(e for e in events if e["type"] == "flow_question")["card"]
        self.assertEqual(card["run_id"], run["id"])
        self.assertEqual(card["resume_id"], run["id"])
        self.assertEqual(card["stage"], 1)
        self.assertEqual(card["title"], "추가 확인이 필요합니다")
        self.assertEqual(card["intro"], "1단계 답변을 작성하기 전에 몇 가지 확인할게요.")   # 2026-09-30 문구 / new wording
        self.assertEqual(card["submit_label"], "답변 제출")
        self.assertEqual((card["flow_name"], card["total_stages"]), ("재고 점검", 1))   # 진행 표시 / progress fields

    async def test_deterministic_items_at_or_above_cap_skip_the_review_llm(self):
        # 결정적 항목(API 필수 입력값) 자체에는 상한이 없다 — 이미 MAX_REVIEW_QUESTIONS에 도달했으면
        # LLM 항목 병합 단계를 건너뛴다(검수 LLM 자체를 호출하지 않는다).
        # The deterministic-item loop has no cap of its own — once it already reaches MAX_REVIEW_QUESTIONS,
        # the LLM-merge step is skipped entirely (the review LLM is never called).
        calls: list = []
        many_missing = {"status": "needs_input", "label": "다중 입력 API", "text": "필수 입력 여러 개",
                        "extras": {"missing_inputs": ["a", "b", "c", "d"], "connector_id": "cn_x", "inputs": {},
                                  "connector": {"id": "cn_x", "name": "다중 입력 API", "kind": "read", "inputs": {}}}}
        self.assertEqual(len(many_missing["extras"]["missing_inputs"]), flows.MAX_REVIEW_QUESTIONS)
        self.stub_flow(self.recording_worker(calls, {"api": many_missing}))
        self.stack.enter_context(patch("app.connectors.get_connector", return_value=CONNECTOR))
        with patch("app.llm.generate", side_effect=AssertionError("cap 도달 시 검수 LLM 호출 금지")):
            run = self.make_run(REVIEW_FLOW)
            events = await collect(artifact_execution.workflow_run(REVIEW_FLOW, self.chat, "q", "", run))

        card = next(e for e in events if e["type"] == "flow_question")["card"]
        self.assertEqual({i["id"] for i in card["items"]}, {"in_1_a", "in_1_b", "in_1_c", "in_1_d"})

    async def test_all_needs_input_results_skip_the_review_llm_entirely(self):
        # 이 단계에 '사용 가능한'(needs_input이 아닌) 결과가 하나도 없으면 검수 LLM은 호출되지 않는다
        # (결정적 항목만으로 카드를 만든다). 두 작업 모두 재실행 대상(rerun)에는 오른다.
        # With no usable (non-needs_input) result in the stage, the review LLM is never called (the card is
        # built from deterministic items alone). Both tasks still land in the re-run list.
        calls: list = []
        needs_input_2 = {"status": "needs_input", "label": "데이터 분석", "text": "추가 정보가 필요합니다", "extras": {}}
        self.stub_flow(self.recording_worker(calls, {"api": NEEDS_INPUT, "재고 추이 분석": needs_input_2}))
        self.stack.enter_context(patch("app.connectors.get_connector", return_value=CONNECTOR))
        with patch("app.llm.generate", side_effect=AssertionError("사용 가능한 결과가 없으면 검수 LLM 호출 금지")):
            run = self.make_run(REVIEW_FLOW)
            events = await collect(artifact_execution.workflow_run(REVIEW_FLOW, self.chat, "q", "", run))

        card = next(e for e in events if e["type"] == "flow_question")["card"]
        self.assertEqual([i["id"] for i in card["items"]], ["in_1_year"])   # api 노드의 결정적 항목만
        saved = store.get(run["id"])
        self.assertEqual(set(saved["snapshot"]["waiting"]["rerun"]), {"stage1_1", "stage1_2"})

    # ── 워크플로우 채팅 개편(2026-09-30) / workflow-chat redesign ─────────────────────────────────────
    async def test_run_start_row_carries_the_workflow_chip_once(self):
        # 실행을 시작하는 사용자 행에 meta.flow — 재개는 저장된 맥락을 써서 그 행을 다시 저장하지 않고, 실행 카드 응답은 "2단계 실행"
        # meta.flow on the user row that starts the run; a resume never stores it again, and the run-card reply is "2단계 실행"
        flow = two_stage_flow()
        calls: list = []
        self.stub_flow(self.recording_worker(calls))
        self.stack.enter_context(patch.object(flows, "_build_context", REAL_BUILD_CONTEXT))
        run = self.make_run(flow, message="재고 점검해줘")
        await collect(artifact_execution.workflow_run(flow, self.chat, "재고 점검해줘", "", run))
        users = [m for m in self.messages() if m["role"] == "user"]
        self.assertEqual([(m["content"], m["meta"]) for m in users],
                         [("재고 점검해줘", {"flow": {"id": "fl_test", "name": "단계 테스트", "stages": 2}})])

        artifact_execution.resume_workflow(store.get(run["id"]), {"kind": "flow_gate", "action": "run", "note": "  "})
        run = store.get(run["id"])
        await collect(artifact_execution.workflow_run(run["snapshot"]["flow"], self.chat, "재고 점검해줘", "", run))
        users = [m for m in self.messages() if m["role"] == "user"]
        self.assertEqual([(m["content"], m["meta"]) for m in users],
                         [("재고 점검해줘", {"flow": {"id": "fl_test", "name": "단계 테스트", "stages": 2}}),
                          ("2단계 실행", {"flow_step": {"stage": 1}})])
        self.assertEqual(store.get(run["id"])["state"], "completed")

    def test_build_context_adds_the_chip_to_an_existing_first_row_without_storing_it_again(self):
        # 새 채팅의 첫 메시지(POST /api/chats 가 저장)와 같은 내용이면 행을 다시 저장하지 않고, 없는 meta 키만 덧붙인다
        # Same text as a new chat's first message (stored by POST /api/chats): no second row, only missing meta keys are added
        chip = {"flow": {"id": "fl_test", "name": "단계 테스트", "stages": 2}}
        db.add_message(self.chat["id"], "user", "첫 질문", {"attach": {"coll": "c1", "coll_name": "자료", "file": ""}})
        ctx = REAL_BUILD_CONTEXT(self.chat["id"], "첫 질문", chip)
        REAL_BUILD_CONTEXT(self.chat["id"], "첫 질문", {"flow": {"id": "other", "name": "다른 흐름", "stages": 9}})
        self.assertEqual(ctx, [{"role": "user", "content": "첫 질문"}])
        self.assertEqual([(m["content"], m["meta"]) for m in self.messages()],
                         [("첫 질문", {"attach": {"coll": "c1", "coll_name": "자료", "file": ""}, **chip})])

    def test_next_items_carry_full_task_sentences_in_next_tasks_order(self):
        # 실행 카드 next_items — next_tasks(트리 라벨, 앞부분만)와 같은 순서·같은 재료, 지침은 자르지 않고 300자 상한
        # The run card's next_items: same order and material as next_tasks (tree labels, cut), uncut up to a 300-character cap
        prompt = "창고별 재고 수량을 품목 코드 기준으로 빠짐없이 모두 조회하고 부족 품목을 표시해 주세요"
        long_instr = "가" * 320
        flow = {"stages": [{"nodes": [{"agent": "data", "resources": [], "instruction": "a"}]}, {"nodes": [
            {"agent": "api", "resources": ["cn_x"], "instruction": "", "prompt": prompt},
            {"agent": "knowledge", "resources": [], "instruction": long_instr},
            {"agent": "web", "resources": [], "instruction": ""},
            {"agent": "auto", "resources": ["wa:wa_gone:GetSales"], "instruction": "매출 확인"}]}]}
        with patch("app.connectors.list_connectors", return_value=[{"id": "cn_x", "name": "재고 API"}]):
            items = flows._stage_task_items(flow, 1)
            tasks = flows._flow_stages(flow)[1]["tasks"]
        self.assertEqual(items, [
            {"agent": "api", "label": "외부 도구", "task": "재고 API · " + prompt},
            {"agent": "knowledge", "label": "지식 관리", "task": "가" * 299 + "…"},
            {"agent": "web", "label": "웹 검색", "task": ""},
            {"agent": "auto", "label": "업무 자동화", "task": "GetSales · 매출 확인"}])
        # 트리 라벨은 종전 그대로 자른다 / the tree labels are cut as before
        self.assertEqual(tasks, ["외부 도구 · 재고 API · " + prompt[:30] + "…", "지식 관리 · " + "가" * 40 + "…", "웹 검색",
                                 "업무 자동화 · GetSales · 매출 확인"])
        self.assertEqual(flows._stage_task_items(flow, 2), [])

    async def test_review_reply_rows_carry_the_answer_values(self):
        # 검수 답변 사용자 행(2026-09-30) — 글은 그대로, meta.flow_answers {stage(0부터), values(항목 순서, 답한 값만)}
        # Review-answer user rows (2026-09-30): same text, meta.flow_answers {stage (0-based), values (item order, answered only)}
        calls: list = []
        self.stub_flow(self.recording_worker(calls, {"api": NEEDS_INPUT}), review=LLM_QUESTIONS)
        self.stack.enter_context(patch("app.connectors.get_connector", return_value=CONNECTOR))
        run = self.make_run(REVIEW_FLOW)
        await collect(artifact_execution.workflow_run(REVIEW_FLOW, self.chat, "q", "", run))
        artifact_execution.resume_workflow(store.get(run["id"]),
                                           {"kind": "flow_question", "answers": {"q1": "지난 달", "in_1_year": " 2026 "}})
        row = [m for m in self.messages() if m["role"] == "user"][-1]
        self.assertEqual(row["content"], "조회 연도: 2026; 기간: 지난 달")
        self.assertEqual(row["meta"], {"flow_answers": {"stage": 0, "values": ["2026", "지난 달"]}})

        flow = two_stage_flow()
        run = self.make_run(flow)
        await collect(artifact_execution.workflow_run(flow, self.chat, "q", "", run))
        artifact_execution.resume_workflow(store.get(run["id"]), {"kind": "flow_question", "answers": {}})
        row = [m for m in self.messages() if m["role"] == "user"][-1]
        self.assertEqual((row["content"], row["meta"]), ("추가 답변 없이 진행", {"flow_answers": {"stage": 0, "values": []}}))

    async def test_revise_reruns_the_same_stage_with_the_request(self):
        # 실행 카드 [1단계 수정 요청](2026-09-30): 같은 단계의 작업·답변을 요청과 함께 새로 만들고 검수 답변은 유지(질문 없음), 직전
        # 답변은 prev_reports, 커서는 넘어가지 않고 같은 단계의 새 실행 카드로 멈춘다
        # Run card [revise stage 1] (2026-09-30): the same stage's tasks and answer are rebuilt with the request, review answers
        # are kept (no questions again), the previous answer goes to prev_reports, and the run stops at a fresh card for the stage
        flow = two_stage_flow()
        calls: list = []
        self.stub_flow(self.recording_worker(calls), review=LLM_QUESTIONS)
        run = self.make_run(flow)
        await collect(artifact_execution.workflow_run(flow, self.chat, "q", "", run))      # 1단계 → 검수 질문 / review card
        artifact_execution.resume_workflow(store.get(run["id"]), {"kind": "flow_question", "answers": {"q1": "지난 달"}})
        run = store.get(run["id"])
        await collect(artifact_execution.workflow_run(flow, self.chat, "q", "", run))      # 답변 → 실행 카드 / answer, run card
        run = store.get(run["id"])
        self.assertEqual(run["snapshot"]["waiting"], {"kind": "gate", "stage": 0})
        first = run["snapshot"]["stage_state"]["0"]["report"]
        tries = int(run["snapshot"]["attempts"].get("stage1_1") or 0)
        calls.clear()
        self.astream.clear()
        self.generate.side_effect = AssertionError("수정 요청 재실행에서 검수 LLM 재호출 금지")

        self.assertFalse(artifact_execution.resume_workflow(
            run, {"kind": "flow_gate", "action": "revise", "note": "  표로 정리해줘 "}))
        saved = store.get(run["id"])
        snap = saved["snapshot"]
        self.assertEqual(saved["state"], "ready")
        self.assertNotIn("waiting", snap)
        self.assertEqual(snap["cursor"], 0)                                   # 같은 단계에 머문다 / parked on the same stage
        self.assertNotIn("stage1_1", snap["results"])
        self.assertEqual(snap["attempts"]["stage1_1"], tries + 1)
        st = snap["stage_state"]["0"]
        self.assertEqual(st["prev_reports"], [first])
        self.assertNotIn("report", st)
        self.assertEqual((st["revise"], st["revise_history"]), ("표로 정리해줘", ["표로 정리해줘"]))
        self.assertTrue(st["reviewed"])
        self.assertEqual([q["answer"] for q in st["qa"]], ["지난 달"])
        row = [m for m in self.messages() if m["role"] == "user"][-1]
        self.assertEqual((row["content"], row["meta"]), ("1단계 수정 요청: 표로 정리해줘", {"flow_revise": {"stage": 0}}))
        old_card = next(m for m in self.messages() if (m.get("meta") or {}).get("kind") == "flow_gate")
        self.assertTrue(old_card["meta"]["answered"])

        run = store.get(run["id"])
        events = await collect(artifact_execution.workflow_run(run["snapshot"]["flow"], self.chat, "q", "", run))

        self.assertNotIn("flow_question", [e["type"] for e in events])
        self.assertEqual([c["key"] for c in calls], ["1단계 작업"])          # 같은 단계만 다시 / only the same stage runs again
        self.assertIn("(수정 요청: 표로 정리해줘)", calls[0]["message"])
        self.assertIn("어느 기간?: 지난 달", calls[0]["message"])             # 검수 답변은 그대로 실린다 / review answers still ride
        self.assertTrue(any("[사용자 수정 요청] 표로 정리해줘" in m["content"] for m in calls[0]["context"]))
        self.assertEqual(len(self.astream), 1)                               # 답변을 새로 만든다 / the answer is regenerated
        body = self.astream[0][0][-1]["content"]
        for part in ("[사용자 수정 요청] 표로 정리해줘", "[사용자 추가 답변]\n- 어느 기간?: 지난 달",
                     "[이전 답변]\n단계 보고 본문", "[사용자 수정 요청]을 반영해 1단계의 결과를 다시 보고하라."):
            self.assertIn(part, body)
        self.assertEqual([e["card"]["stage"] for e in events if e["type"] == "flow_gate"], [1])   # 같은 단계의 새 카드 / fresh card
        saved = store.get(run["id"])
        self.assertEqual(saved["state"], "needs_input")
        self.assertEqual(saved["snapshot"]["waiting"], {"kind": "gate", "stage": 0})
        self.assertEqual(saved["snapshot"]["cursor"], 1)                     # 수정 요청 전과 같다 / same as before the revise
        st = saved["snapshot"]["stage_state"]["0"]
        self.assertEqual(st["prev_reports"], [first])
        self.assertNotEqual(st["report"]["message_id"], first["message_id"])
        rows = {m["id"]: m for m in self.messages()}
        self.assertEqual((rows[first["message_id"]]["meta"]["flow_stage"], rows[first["message_id"]]["meta"]["flow_attempt"]), (1, 1))
        new = rows[st["report"]["message_id"]]["meta"]
        self.assertEqual((new["flow_stage"], new["flow_attempt"]), (1, 2))
        self.assertEqual(sum(1 for m in rows.values() if (m.get("meta") or {}).get("kind") == "flow_gate"), 2)

    async def test_second_revise_keeps_the_earlier_request(self):
        # 두 번째 수정 요청은 앞선 요청을 잃지 않는다(작업을 처음부터 다시 부르므로) — revise 는 최신, revise_history 는 모두
        # A second revision keeps the earlier request (tasks run from scratch) — revise holds the latest, revise_history all
        flow = two_stage_flow()
        calls: list = []
        self.stub_flow(self.recording_worker(calls))
        run = await self.run_to_gate(flow)
        for note in ("서울만", "표로"):
            artifact_execution.resume_workflow(store.get(run["id"]), {"kind": "flow_gate", "action": "revise", "note": note})
            run = store.get(run["id"])
            calls.clear()
            await collect(artifact_execution.workflow_run(run["snapshot"]["flow"], self.chat, "q", "", run))
        self.assertIn("(수정 요청: 표로 (앞선 수정 요청: 서울만))", calls[0]["message"])
        st = store.get(run["id"])["snapshot"]["stage_state"]["0"]
        self.assertEqual((st["revise"], st["revise_history"]), ("표로", ["서울만", "표로"]))
        self.assertEqual(len(st["prev_reports"]), 2)
        answers = [m for m in self.messages() if (m.get("meta") or {}).get("flow_stage") == 1]
        self.assertEqual([m["meta"]["flow_attempt"] for m in answers], [1, 2, 3])

    async def test_revise_of_the_last_stage_ends_without_a_gate(self):
        # 마지막 단계는 실행 카드가 없어 보통은 수정 요청이 오지 않지만, 오면 평소처럼 게이트 없이 최종 답변으로 끝난다(최종 슬롯도 비운다)
        # The last stage has no run card, but a revise there ends like a normal run: no gate, the final answer (final slots cleared)
        flow = two_stage_flow()
        calls: list = []
        self.stub_flow(self.recording_worker(calls))
        run = await self.run_to_gate(flow)
        artifact_execution.resume_workflow(run, {"kind": "flow_gate", "action": "run", "note": ""})
        run = store.get(run["id"])
        await collect(artifact_execution.workflow_run(run["snapshot"]["flow"], self.chat, "q", "", run))
        run = store.get(run["id"])
        self.assertEqual(run["state"], "completed")
        final = run["snapshot"]["stage_state"]["1"]["report"]
        run["snapshot"]["waiting"] = {"kind": "gate", "stage": 1}           # 마지막 단계 카드를 흉내 / emulate a last-stage card
        store.save(run, "needs_input")
        calls.clear()
        self.astream.clear()

        artifact_execution.resume_workflow(run, {"kind": "flow_gate", "action": "revise", "note": "세 줄로 요약"})
        snap = store.get(run["id"])["snapshot"]
        self.assertEqual(snap["cursor"], 1)
        self.assertNotIn("answer", snap)                                     # 최종 슬롯도 비운다 / the final slot is cleared
        self.assertIn("stage1_1", snap["results"])                           # 앞 단계는 그대로 / earlier stages untouched
        run = store.get(run["id"])
        events = await collect(artifact_execution.workflow_run(run["snapshot"]["flow"], self.chat, "q", "", run))

        self.assertNotIn("flow_gate", [e["type"] for e in events])
        self.assertEqual([c["key"] for c in calls], ["2단계 작업"])
        messages, system = self.astream[0]
        self.assertIn("[최종 답변]", system)
        self.assertIn("[사용자 수정 요청] 세 줄로 요약", messages[-1]["content"])
        self.assertIn("최종 답변을 다시 작성하라.", messages[-1]["content"])
        self.assertEqual(events[-1]["state"], "completed")
        saved = store.get(run["id"])
        report = saved["snapshot"]["stage_state"]["1"]["report"]
        self.assertEqual(saved["snapshot"]["answer"], report)
        self.assertEqual(saved["snapshot"]["stage_state"]["1"]["prev_reports"], [final])
        row = next(m for m in self.messages() if m["id"] == report["message_id"])
        self.assertEqual((row["meta"]["flow_stage"], row["meta"]["flow_attempt"]), (2, 2))

    def test_revise_keeps_results_of_action_tools_that_already_ran(self):
        # 이미 외부 효과를 낸 실행형 도구 작업은 수정 요청으로 다시 부르지 않는다(검수 재실행과 같은 규칙) — 저장 결과를 그대로 쓴다
        # An action-kind tool call that already had its effect is not called again on revise (same rule as review re-runs)
        flow = {"id": "fl_act", "name": "주문", "group": "og9", "stages": [
            {"nodes": [{"agent": "api", "resources": ["cn_act"], "instruction": "", "prompt": "주문 등록"},
                       {"agent": "data", "resources": [], "instruction": "매출 분석"},
                       {"agent": "api", "resources": ["cn_read"], "instruction": "", "prompt": "재고 조회"}]},
            {"nodes": [{"agent": "data", "resources": [], "instruction": "b"}]}]}
        action = {"status": "done", "label": "주문 API", "text": "주문 완료",
                  "extras": {"connector": {"id": "cn_act", "name": "주문 API", "kind": "action"}}}
        read = {"status": "done", "label": "재고 API", "text": "재고 3",
                "extras": {"connector": {"id": "cn_read", "name": "재고 API", "kind": "read"}}}
        run = store.create(self.chat["id"], {
            "kind": "workflow", "flow": flow, "message": "q", "actor": "", "eff": None,
            "results": {"stage1_1": action, "stage1_2": {"status": "done", "label": "매출 분석", "text": "매출"},
                        "stage1_3": read, "stage2_1": {"status": "done", "label": "b", "text": "b"}},
            "cursor": 1, "waiting": {"kind": "gate", "stage": 0},
            "stage_state": {"0": {"reviewed": True, "report": {"text": "1단계 답변", "message_id": "m_x"}}}, "attempts": {}})
        store.save(run, "needs_input")
        artifact_execution.resume_workflow(run, {"kind": "flow_gate", "action": "revise", "note": "다시"})
        snap = store.get(run["id"])["snapshot"]
        self.assertEqual(snap["results"], {"stage1_1": action, "stage2_1": {"status": "done", "label": "b", "text": "b"}})
        self.assertEqual(snap["attempts"], {"stage1_2": 1, "stage1_3": 1})

    async def test_stage_file_size_rides_on_done_and_the_file_message(self):
        # 단계 파일 크기(2026-09-30) — 실 파일 바이트 수가 파일 세그먼트 done.size 와 문서 메시지 meta.doc.size 에 실린다
        # Stage-file size (2026-09-30): the real file's byte count lands on the file segment's done.size and meta.doc.size
        out_dir = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(artifact_execution.docgen, "GENERATED_DIR", out_dir))
        (out_dir / "d_size").mkdir()
        (out_dir / "d_size" / "stage.docx").write_bytes(b"x" * 1234)
        chat_id = self.chat["id"]

        async def fake_run_docgen(chat, message, fmt, topic, style, length, source="general", acting_user_id="",
                                  instruction="", save_user=True):
            yield {"type": "doc_meta", "doc_id": "d_size", "format": fmt, "filename": "stage.docx", "topic": topic,
                   "style": style, "total": 1, "source": source}
            mid = db.add_message(chat_id, "assistant", "파일을 만들었습니다",
                                 {"kind": "doc", "doc": {"id": "d_size", "format": fmt, "filename": "stage.docx"}})
            yield {"type": "done", "message_id": mid}
        self.stack.enter_context(patch.object(artifact_execution.docgen, "run_docgen", fake_run_docgen))
        flow = two_stage_flow()
        flow["stages"][0]["docgen"] = {"format": "docx", "instruction": ""}
        calls: list = []
        self.stub_flow(self.recording_worker(calls))
        run = self.make_run(flow)
        events = await collect(artifact_execution.workflow_run(flow, self.chat, "q", "", run))

        dones = [e for e in events if e["type"] == "done"]
        self.assertNotIn("size", dones[0])                                   # 단계 답변의 done / the stage answer's done
        self.assertEqual(dones[1]["size"], 1234)                             # 파일 세그먼트 done / the file segment's done
        row = next(m for m in self.messages() if m["id"] == dones[1]["message_id"])
        self.assertEqual(row["meta"]["doc"], {"id": "d_size", "format": "docx", "filename": "stage.docx", "size": 1234})
        self.assertEqual(store.get(run["id"])["snapshot"]["stage_state"]["0"]["artifact"],
                         {"id": "d_size", "format": "docx", "filename": "stage.docx"})   # 산출물 슬롯 모양은 그대로 / slot unchanged
        self.assertIn("flow_gate", [e["type"] for e in events])


class StageLedgerTests(unittest.TestCase):
    """앞 단계 기록(2026-09-29) 순수 함수 — _stage_ledger 예산·표시, _meta_steps 순서, _record_text 우선순위.
    Earlier-stage record (2026-09-29) pure helpers: _stage_ledger budget and layout, _meta_steps order, _record_text precedence."""

    @staticmethod
    def task(stage: int, node: int, text: str, **extra) -> dict:
        return {"label": f"{stage}단계 작업{node}", "agent": "data", "text": text, "stage": stage, "node": node,
                "data": None, "outputs": {}, "note": "", "name": f"작업{node}", "instruction": f"{stage}-{node} 지침",
                "status": "done", "refs": [], **extra}

    @staticmethod
    def report(stage: int, text: str) -> dict:
        return {"label": f"{stage}단계 보고", "agent": "", "text": text, "stage": stage, "kind": "report"}

    def test_ledger_lists_every_stage_in_order_with_answers_notes_and_files(self):
        prior = [self.task(1, 1, "첫 결과", refs=["인사규정.pdf p.3"], outputs={"total": 3}), self.report(1, "첫 답변"),
                 self.task(2, 1, "", data={"rows": [1, 2]}, status="failed"), self.report(2, "둘째 답변")]
        state = {"0": {"qa": [{"question": "어느 지점?", "answer": "서울"}, {"question": "빈 답", "answer": " "}],
                       "artifact": {"id": "d1", "format": "pdf", "filename": "첫.pdf"}},
                 "1": {"note": "재고만", "doc_cfg": {"format": "xlsx"}}}
        text = flows._stage_ledger(prior, state)
        self.assertEqual(text.split("\n\n")[0].splitlines()[0], "[1단계]")
        for part in ("- 작업 1 · 작업1 · 완료\n  지침: 1-1 지침\n  참고 자료: 인사규정.pdf p.3\n  출력값: {\"total\": 3}\n  결과:\n첫 결과",
                     "- 검수 질문에 대한 사용자 답변:\n  - 어느 지점?: 서울", "- 1단계 답변:\n첫 답변", "- 생성 파일: PDF · 첫.pdf",
                     "[2단계]\n- 실행 전 사용자 추가 지시: 재고만", "- 작업 1 · 작업1 · 실패\n  지침: 2-1 지침\n  결과:\n(결과 없음)",
                     "- 2단계 답변:\n둘째 답변", "- 생성 파일: Excel (만들지 못했습니다)"):
            self.assertIn(part, text)
        self.assertNotIn("빈 답", text)
        self.assertNotIn('"rows"', text)   # 응답 데이터(JSON)는 싣지 않는다 / response data (JSON) is never added
        self.assertLess(text.index("[1단계]"), text.index("[2단계]"))
        self.assertEqual(flows._stage_ledger([]), "")

    def test_revision_requests_reach_the_record_of_later_stages(self):
        # 수정 요청(2026-09-30)은 뒷 단계의 앞 단계 기록에도 실린다 — 여러 번이면 최신 요청 + 앞선 요청
        # Revision requests (2026-09-30) reach the later stages' record too: the latest plus the earlier ones
        prior = [self.task(1, 1, "결과"), self.report(1, "고친 답변")]
        state = {"0": {"note": "서울만", "revise": "표로", "revise_history": ["짧게", "표로"]}}
        text = flows._stage_ledger(prior, state)
        self.assertIn("- 실행 전 사용자 추가 지시: 서울만\n- 사용자 수정 요청: 표로 (앞선 수정 요청: 짧게)", text)
        self.assertEqual(flows._revise_text({"revise": "하나만"}), "하나만")              # 기록 목록이 없어도 / without a history
        self.assertEqual(flows._revise_text({}), "")
        self.assertNotIn("수정 요청", flows._stage_ledger(prior, {"0": {"note": "서울만"}}))

    def test_results_excluded_from_answers_stay_out_of_the_record(self):
        # API 설정에서 '답변에 포함'을 끈 결과(hidden) — 글이 비어 있고 출력값도 싣지 않는다(2026-09-29 리뷰) / hidden results stay out
        prior = [self.task(1, 1, "", data={"rrn": "900101-1234567"}, outputs={"rrn": "900101-1234567"}, hidden=True)]
        text = flows._stage_ledger(prior)
        self.assertNotIn("900101", text)
        self.assertIn("  결과:\n(API 설정에 따라 답변 재료에서 뺀 결과입니다)", text)

    def test_budget_shortens_the_oldest_results_first_and_never_the_answers(self):
        prior = [self.task(1, 1, "가" * 500), self.report(1, "답" * 800), self.task(2, 1, "나" * 500), self.task(3, 1, "다" * 100)]
        text = flows._stage_ledger(prior, budget=200)   # 결과 합 1100자 → 900자 초과 / 1,100 chars of results, 900 over
        self.assertIn("(분량이 많아 결과 원문을 생략했습니다. 이 단계 답변을 참고하세요)", text)   # 1단계 결과는 통째로 / stage 1 dropped
        self.assertNotIn("가", text)
        self.assertIn("나" * 100 + "\n(분량이 많아 뒷부분을 줄였습니다)", text)                    # 2단계는 앞부분만 / stage 2 cut
        self.assertNotIn("나" * 101, text)
        self.assertIn("다" * 100, text)                                                             # 최근 결과는 그대로 / newest kept
        self.assertIn("답" * 800, text)                                                             # 답변은 줄이지 않는다 / answers uncut
        self.assertNotIn("분량이 많아", flows._stage_ledger(prior))                                  # 기본 예산은 넉넉하다 / default budget

    def test_meta_steps_put_this_stage_first_then_newer_stages(self):
        prior = [self.task(1, 1, "a"), self.report(1, "r1"), self.task(2, 1, "b"), self.task(2, 2, ""), self.report(2, "r2"),
                 self.task(3, 1, "c")]
        self.assertEqual([s["label"] for s in flows._meta_steps(prior, 3)],
                         ["3단계 작업1", "2단계 보고", "2단계 작업1", "1단계 보고", "1단계 작업1"])

    def test_record_text_prefers_the_running_stage_record(self):
        prior = [{"label": "1단계 데이터 분석", "text": "앞 결과"}]   # 단계 번호 없는 항목도 싣는다 / entries without a stage number
        self.assertEqual(flows._record_text(prior), "[1단계 데이터 분석]\n앞 결과")
        self.assertEqual(flows._record_text([]), "(없음)")
        token = flows._STAGE_RECORD.set("[1단계]\n전체 기록")
        try:
            self.assertEqual(flows._record_text(prior), "[1단계]\n전체 기록")
        finally:
            flows._STAGE_RECORD.reset(token)


if __name__ == "__main__":
    unittest.main()
