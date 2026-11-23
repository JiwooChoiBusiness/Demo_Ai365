# -*- coding: utf-8 -*-
"""로컬 전용 선택(2026-10-28, 리소스 선택 대화 상자 Local 구획) — scope_files.local_agents 계약.
pipeline._clean_scope_files 통과 · 지식 에이전트의 로컬 전용 자리(Public 검색 · 개요 호출 생략, readable 교집합) · answers 로컬 단계의
자리 정리(로컬이 답하면 자리를 빼고 로컬 답만 취합, 못 찾으면 사유 교체) · OpenUI 취합 · 실행기 상태(실패로 그리지 않음).
2026-10-28 검토 반영: 명시 선택은 넓히지 않음(교집합 0 · 조회 실패 · 빈 질문 = 닫기) · 사유 3종(실패 · 묻지 못함 · 못 찾음)과 카드 다시 그리기 ·
로컬 답 뒤 발송 확인 · 파일 생성 후속(못 찾음 · 실패는 보류) · 로컬 선택 채팅의 자연어 예약 거절(한국어 · 영어).
임시 DB, 가상 배포는 앱 안 라우터(mock_transport)로만 부르고, LLM 은 가짜다. 실 DB · 실제 포트 · 네트워크에 닿지 않는다.

Local-only selection (2026-10-28, the Local section of the resource picker): the scope_files.local_agents contract.
pipeline._clean_scope_files passes it; the knowledge agent returns a local-only placeholder (no Public search, no overview
call, intersected with readable); the answers local stage settles the placeholder (dropped when local answers, so only the
local answers are aggregated; its reason replaced when local finds nothing); the OpenUI aggregation; the runner status (not
drawn as a failure). 2026-10-28 review: an explicit choice never widens (empty intersection, failed lookup, empty question =
closed); three reasons (failed, not asked, not found) and the card redraw; the send confirm and file follow-up after a local
answer (held on a miss or failure); a chat with a local choice refuses natural-language schedules (Korean, English). Temp DB;
the fictional deployment is reached only through the in-app router (mock_transport) and the LLM is faked. Neither the real
DB, a real port nor the network is touched."""
import asyncio
import copy
import os
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import httpx

from app import answers, db, knowledge_agents as ka, local_knowledge as lk, mock_kagent as mk, openui, pipeline
from app.agents import knowledge
from tests.db_fixture import isolate_db
from tests.test_mock_kagent import mock_transport

BASE = "{{base_url}}/mock/kagent"
Q_HIT = "비밀번호 변경 주기는?"
Q_MISS = "zzqqxx"
HQ = "kl_demo_hq"
HQ_NAME = "본사 로컬 에이전트"
HIT = [{"doc": "보안규정.pdf", "page": 2, "text": "비밀번호는 90일마다 변경한다", "similarity": 0.9, "score": 0.9}]
MEMBER = {"no": 7, "menus": {}, "mgmt": {}, "read": {"p_know": True}, "nodes": {HQ: 1}}


def lab_body(**over) -> dict:
    d = {"name": "연구소 지식 에이전트", "description": "", "enabled": True,
         "mcp": {"url": f"{BASE}/lab/mcp", "timeout": 20}, "api": {"base_url": f"{BASE}/lab/api/v1", "timeout": 20},
         "auth": {"type": "bearer", "key": mk.DEMO_KEY}}
    d.update(over)
    return d


async def collect(stream) -> list[dict]:
    return [e async for e in stream]


def thinking(events) -> list[str]:
    return [e["text"] for e in events if e.get("type") == "thinking"]


def statuses(events, running=False) -> list[tuple]:
    """agent_status (카드, 상태, 사유) — running 은 기본으로 뺀다 / (card, status, detail), running left out by default"""
    return [(e["task_id"], e["status"], e.get("detail")) for e in events
            if e.get("type") == "agent_status" and (running or e["status"] != "running")]


def refused(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


class CleanScopeTests(unittest.TestCase):
    """pipeline._clean_scope_files 가 local_agents 를 문자열 목록으로만 통과시킨다 / only string lists pass"""

    def test_strings_are_trimmed_deduplicated_and_capped(self):
        sf = pipeline._clean_scope_files({"local_agents": [" kl_a ", "kl_a", "", "  ", 3, None, {}, "kl_b"]})
        self.assertEqual(sf["local_agents"], ["kl_a", "kl_b"])
        many = pipeline._clean_scope_files({"local_agents": [f"kl_{i:03d}" for i in range(30)]})
        self.assertEqual(len(many["local_agents"]), 20)

    def test_absent_empty_or_malformed_keeps_the_former_shape(self):
        for raw in ({}, {"local_agents": []}, {"local_agents": "kl_a"}, {"local_agents": None}, {"local_agents": [1, {}]}):
            self.assertNotIn("local_agents", pipeline._clean_scope_files(raw), raw)
        self.assertEqual(pipeline._clean_scope_files({"knowledge_files": ["a.pdf"]}),
                         {"knowledge_files": ["a.pdf"], "data_tables": [], "data_bi": [], "work": False})


class _DbCase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        # {{base_url}} 은 쓰지 않는 포트로 — 전송 주입을 빠뜨려도 사용자 서버(8000 · 8010)에 닿지 않는다
        # {{base_url}} points at an unused port, so a missing transport can never reach the user's servers (8000, 8010)
        self.stack.enter_context(patch.dict(os.environ, {"AI365_BASE_URL": "http://localhost:65531"}))
        self.calls: dict = {}
        self.stack.enter_context(patch.object(lk, "TRANSPORT", mock_transport(self.calls)))
        ka._TOKENS.clear()
        self.addCleanup(ka._TOKENS.clear)


class KnowledgeLocalOnlyTests(_DbCase):
    """지식 에이전트: 로컬 전용이면 검색 · LLM 없이 자리 결과만 / the knowledge agent returns only a placeholder, no search or LLM"""

    def run_agent(self, query, scope_files, eff=None, hits=HIT):
        with patch.object(knowledge.kb, "search", side_effect=AssertionError("no Public search")) as search, \
                patch.object(knowledge.llm, "generate", side_effect=AssertionError("no LLM call")), \
                patch.object(lk, "ask_many", side_effect=AssertionError("no local calls in the knowledge agent")):
            return knowledge._run_sync(query, [{"role": "user", "content": query}], False, eff, scope_files), search

    def run_public(self, query, scope_files, eff=None):
        """종전 경로(검색 · LLM 가짜) / the former path with a fake search and LLM"""
        def generate(messages, system=None, json_mode=False, tier=None, **kw):
            return {"subqueries": [Q_HIT], "files": []} if json_mode else "공개 규정 답변입니다."
        with patch.object(knowledge.kb, "search", return_value=HIT) as search, \
                patch.object(knowledge.llm, "generate", side_effect=generate):
            return knowledge._run_sync(query, [{"role": "user", "content": query}], False, eff, scope_files), search

    def test_local_only_skips_the_public_search_and_marks_the_placeholder(self):
        query = Q_HIT + "\n\n[사용자가 요청한 대상과 조건 — 이 범위를 보존]\n{\"a\": 1}"
        res, search = self.run_agent(query, {"local_agents": [HQ]})
        search.assert_not_called()
        self.assertEqual(res["status"], "not_found")
        self.assertEqual(res["extras"], {"local_agents": [HQ], "local_query": Q_HIT, "local_only": True})
        self.assertEqual(res["fail_reason"], knowledge.LOCAL_ONLY_REASON)
        self.assertNotIn("—", res["fail_reason"] + res["alternative"])

    def test_only_the_readable_intersection_in_pos_order(self):
        lab = ka.create(lab_body())
        res, _ = self.run_agent(Q_HIT, {"local_agents": [lab["id"], HQ, "kl_nope"]})   # 슈퍼 = 사용 중인 전부 / super = every enabled agent
        self.assertEqual(res["extras"]["local_agents"], [HQ, lab["id"]])                 # pos 순서 / pos order
        res, _ = self.run_agent(Q_HIT, {"local_agents": [lab["id"], HQ]}, MEMBER)        # 구성원: 본사 잎만 / member: the HQ leaf only
        self.assertEqual(res["extras"]["local_agents"], [HQ])
        ka.update(HQ, {**ka.editor_record(ka.get_agent(HQ)), "enabled": False})          # 사용 중지는 빠진다 / disabled drops out
        res, _ = self.run_agent(Q_HIT, {"local_agents": [HQ, lab["id"]]})
        self.assertEqual(res["extras"]["local_agents"], [lab["id"]])

    # 2026-10-28 검토 반영: 명시한 local_agents 는 범위를 넓히지 않는다(pipeline._clean_scope_files 의 workers 원칙). 교집합이 비거나
    # (권한 없음 · 뷰애즈 · 없는 id · 사용 중지 · 삭제) 목록 조회가 실패하면 Public 이나 다른 로컬로 가지 않고 근거 없음으로 닫는다.
    # 질문이 비어도 닫는다. local_agents 를 보내지 않으면 종전 경로 그대로다.
    # 2026-10-28 review: an explicit local_agents never widens (the workers rule of pipeline._clean_scope_files). An empty
    # intersection (no permission, view-as, unknown id, disabled, deleted) or a failed lookup closes as no evidence instead of
    # going to Public or other local agents; an empty question closes too. Without local_agents the former path is unchanged.
    def test_empty_intersection_failed_lookup_or_empty_question_closes_without_widening(self):
        lab = ka.create(lab_body())

        def closed(res, reason):
            # 로컬 재료 · local_only 없음(카드 = 실패), local_closed = 카드 로컬 전용 모양 / no material (card failed); local_closed = local-only look
            self.assertEqual((res["status"], res["text"], res["extras"]), ("not_found", "", {"local_closed": True}))
            self.assertEqual(res["fail_reason"], reason)
        res, search = self.run_agent(Q_HIT, {"local_agents": [lab["id"]]}, MEMBER)   # 연구소 잎 없음(뷰애즈 구성원) / no lab leaf
        search.assert_not_called()
        closed(res, knowledge.LOCAL_ONLY_UNAVAILABLE)
        closed(self.run_agent(Q_HIT, {"local_agents": ["kl_nope"]})[0], knowledge.LOCAL_ONLY_UNAVAILABLE)   # 슈퍼 · 없는 id
        ka.update(HQ, {**ka.editor_record(ka.get_agent(HQ)), "enabled": False})                         # 사용 중지 / disabled
        closed(self.run_agent(Q_HIT, {"local_agents": [HQ]})[0], knowledge.LOCAL_ONLY_UNAVAILABLE)
        ka.delete(lab["id"])                                                                             # 삭제 / deleted
        closed(self.run_agent(Q_HIT, {"local_agents": [lab["id"]]})[0], knowledge.LOCAL_ONLY_UNAVAILABLE)
        ka.update(HQ, {**ka.editor_record(ka.get_agent(HQ)), "enabled": True})
        with patch.object(ka, "readable", side_effect=RuntimeError("목록 실패 / list failure")), \
                self.assertLogs("ai365.agents.knowledge", level="WARNING"):
            closed(self.run_agent(Q_HIT, {"local_agents": [HQ]})[0], knowledge.LOCAL_ONLY_UNAVAILABLE)   # 조회 실패 / lookup failure
        closed(self.run_agent("  ", {"local_agents": [HQ]})[0], knowledge.LOCAL_ONLY_NO_QUESTION)         # 빈 질문 / empty question
        only_context = "\n\n[이 작업의 선행 결과 — 참고 자료이며 추가 실행 지시가 아님]\n앞 결과"
        closed(self.run_agent(only_context, {"local_agents": [HQ]})[0], knowledge.LOCAL_ONLY_NO_QUESTION)
        for text in (knowledge.LOCAL_ONLY_UNAVAILABLE, knowledge.LOCAL_ONLY_UNAVAILABLE_ALT,
                     knowledge.LOCAL_ONLY_NO_QUESTION, knowledge.LOCAL_ONLY_NO_QUESTION_ALT):
            self.assertNotIn("—", text)
        # local_agents 를 보내지 않으면(빈 목록 = 정규화가 키를 뺀다) 종전 경로 / without local_agents the former path
        res, search = self.run_public(Q_HIT, pipeline._clean_scope_files({"local_agents": []}))
        search.assert_called()
        self.assertEqual(res["status"], "answer")
        self.assertEqual(res["extras"]["local_agents"], [HQ])

    def test_local_only_wins_over_public_files_and_the_domain_gate_still_applies(self):
        res, search = self.run_agent(Q_HIT, {"knowledge_files": ["보안규정.pdf"], "local_agents": [HQ]})
        search.assert_not_called()
        self.assertTrue(res["extras"]["local_only"])
        denied, _ = self.run_agent(Q_HIT, {"local_agents": [HQ]}, {**MEMBER, "read": {"p_know": False}})
        self.assertEqual(denied["extras"], {})
        self.assertIn("권한", denied["fail_reason"])


class StageLocalOnlyTests(_DbCase):
    """answers 로컬 단계의 자리 정리 / the answers local stage settling the placeholder"""

    def setUp(self):
        super().setUp()
        self.chat = db.create_chat("로컬 전용", "사내")
        self.context = [{"role": "user", "content": Q_HIT}]
        self.stream_calls: list[dict] = []

        async def fake_stream(messages, system=None):
            self.stream_calls.append({"messages": messages, "system": system})
            yield "비밀번호는 90일마다 변경합니다 (로컬 · 본사 로컬 에이전트)."
        self.stack.enter_context(patch.object(answers, "_astream", fake_stream))
        self.stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")))
        self.stack.enter_context(patch("app.llm.stream", side_effect=AssertionError("unexpected LLM stream")))
        self.stack.enter_context(patch("app.llm.generate_grounded_meta", side_effect=AssertionError("unexpected web")))

    def placeholder(self, query=Q_HIT, ids=(HQ,)):
        res = knowledge._local_only(query, None, {"local_agents": list(ids)})
        self.assertIsNotNone(res)
        return {**res, "agent": "knowledge", "task_id": "knowledge", "label": "지식관리"}

    def run_stream(self, stream) -> list[dict]:
        return asyncio.run(collect(stream))

    def test_a_local_answer_replaces_the_placeholder_in_the_aggregation(self):
        results = {"knowledge": self.placeholder()}
        before = copy.deepcopy(results)
        events = self.run_stream(answers._aggregate_answer(self.chat["id"], "사내", self.context, results))
        self.assertEqual(thinking(events), [f"로컬 지식 에이전트에 질문하고 있습니다 · {HQ_NAME}",
                                            f"로컬 · {HQ_NAME}(Qwen 3.5-4B) 답변 확보 · 출처 1건"])
        self.assertEqual(results, before)   # 호출자 dict 는 그대로 / the caller's dict is untouched
        self.assertEqual(len(self.stream_calls), 1)
        prompt = self.stream_calls[0]["messages"][-1]["content"]
        self.assertIn(f"로컬 지식 에이전트 · {HQ_NAME}", prompt)
        self.assertIn("90일", prompt)
        self.assertNotIn(knowledge.LOCAL_ONLY_REASON, prompt)   # "Public 검색 안 함" 안내는 답에 끼지 않는다 / no placeholder note
        self.assertNotIn("not_found", prompt)
        self.assertNotIn("local_only", prompt)
        done = events[-1]
        self.assertNotIn("references", done)                    # Public 출처 없음 / no Public sources
        self.assertNotIn("knowledge", done["sources"])
        self.assertEqual(done["sources"]["local"]["items"][0]["doc_id"], "hq-doc-001")
        self.assertEqual([s["id"] for s in db.list_messages(self.chat["id"])[-1]["meta"]["steps"]], [f"local:{HQ}"])
        self.assertEqual(statuses(events), [])   # 메웠으면 카드를 다시 그리지 않는다 / a filled placeholder never redraws the card

    def test_no_local_hit_keeps_the_placeholder_with_a_not_found_reason(self):
        events = self.run_stream(answers._aggregate_answer(self.chat["id"], "사내", self.context,
                                                           {"knowledge": self.placeholder(Q_MISS)}))
        self.assertEqual(thinking(events), [f"로컬 지식 에이전트에 질문하고 있습니다 · {HQ_NAME}",
                                            f"로컬 · {HQ_NAME} 관련 문서를 찾지 못했습니다"])
        prompt = self.stream_calls[0]["messages"][-1]["content"]
        self.assertIn(answers.LOCAL_ONLY_MISS, prompt)
        self.assertNotIn(knowledge.LOCAL_ONLY_REASON, prompt)
        self.assertNotIn("local", events[-1].get("sources") or {})
        self.assertEqual(statuses(events), [("knowledge", "failed", answers.LOCAL_ONLY_MISS)])   # 카드 = 결과 / the card follows

    # 2026-10-28 검토 반영: 실패 · 묻지 못함 · 못 찾음을 나누고, 메우지 못한 자리의 카드는 로컬 단계 끝에 failed 로 다시 그린다
    # 2026-10-28 review: failed, not asked and not found are told apart; an unfilled card is redrawn failed after the local stage
    def test_agent_disabled_at_answer_time_is_not_asked(self):
        results = {"knowledge": self.placeholder()}
        ka.update(HQ, {**ka.editor_record(ka.get_agent(HQ)), "enabled": False})
        events = self.run_stream(answers._aggregate_answer(self.chat["id"], "사내", self.context, results))
        self.assertEqual(thinking(events), [])
        self.assertEqual(self.calls, {})
        prompt = self.stream_calls[0]["messages"][-1]["content"]
        self.assertIn(answers.LOCAL_ONLY_UNASKED, prompt)
        self.assertNotIn(answers.LOCAL_ONLY_MISS, prompt)
        self.assertEqual(statuses(events), [("knowledge", "failed", answers.LOCAL_ONLY_UNASKED)])

    def test_failure_or_timeout_is_a_failure_not_a_miss(self):
        timeout = [{"id": HQ, "name": HQ_NAME, "model": "", "status": "failed", "answer": "", "sources": [], "error": lk.TIMEOUT_REASON}]
        for label, ctx in (("timeout", patch.object(lk, "ask_many", return_value=timeout)),
                           ("refused", patch.object(lk, "TRANSPORT", httpx.MockTransport(refused))),
                           ("ask_many raised", patch.object(lk, "ask_many", side_effect=RuntimeError("boom")))):
            self.stream_calls.clear()
            logs = self.assertLogs("ai365.answers", level="WARNING") if label == "ask_many raised" else ExitStack()
            with self.subTest(label), ctx, logs:
                events = self.run_stream(answers._aggregate_answer(self.chat["id"], "사내", self.context,
                                                                   {"knowledge": self.placeholder()}))
                prompt = self.stream_calls[0]["messages"][-1]["content"]
                self.assertIn(answers.LOCAL_ONLY_FAILED, prompt)
                self.assertNotIn(answers.LOCAL_ONLY_MISS, prompt)
                self.assertEqual(statuses(events), [("knowledge", "failed", answers.LOCAL_ONLY_FAILED)])
                self.assertTrue(any("연결 실패" in t for t in thinking(events)), thinking(events))

    def test_outcome_rank_per_question_and_per_card(self):
        lab = ka.create(lab_body())
        two = [(HQ, "not_found"), (lab["id"], "failed")]

        def outs(pairs):
            return [{"id": aid, "name": aid, "model": "", "status": st, "answer": "답" if st == "answer" else "",
                     "sources": [{"doc_id": "d1", "title": "t", "page": 1}] if st == "answer" else [], "error": ""}
                    for aid, st in pairs]
        with patch.object(lk, "ask_many", return_value=outs(two)):   # 못 찾음 + 실패 → 실패(찾기가 끝나지 않았다) / not found + failed → failed
            events = self.run_stream(answers._aggregate_answer(self.chat["id"], "사내", self.context,
                                                               {"knowledge": self.placeholder(ids=(HQ, lab["id"]))}))
        self.assertEqual(statuses(events), [("knowledge", "failed", answers.LOCAL_ONLY_FAILED)])
        self.stream_calls.clear()
        with patch.object(lk, "ask_many", return_value=outs([(HQ, "failed"), (lab["id"], "answer")])):   # 하나라도 답 = 메움 / any answer fills it
            events = self.run_stream(answers._aggregate_answer(self.chat["id"], "사내", self.context,
                                                               {"knowledge": self.placeholder(ids=(HQ, lab["id"]))}))
        self.assertEqual(statuses(events), [])
        self.assertNotIn(answers.LOCAL_ONLY_FAILED, self.stream_calls[0]["messages"][-1]["content"])
        # 카드 하나에 자리가 여럿: 실패 > 묻지 못함 > 못 찾음, 하나라도 메웠으면 카드는 그대로 / several placeholders on one card
        base = self.placeholder()
        merged = {"k1": {**base, "task_id": "k1", "extras": {**base["extras"], "local_query": "q1"}},
                  "k2": {**base, "task_id": "k2", "extras": {**base["extras"], "local_query": "q2"}},
                  "k3": {**base, "task_id": "k3", "extras": {**base["extras"], "local_query": "q3"}}}
        changed, resolved, cards = answers._settle_local_only(merged, {"q1": "not_found", "q2": "failed"})
        self.assertEqual((changed, resolved, cards), (True, [], {"knowledge": answers.LOCAL_ONLY_FAILED}))
        self.assertEqual([merged[k]["fail_reason"] for k in ("k1", "k2", "k3")],
                         [answers.LOCAL_ONLY_MISS, answers.LOCAL_ONLY_FAILED, answers.LOCAL_ONLY_UNASKED])
        merged = {"k1": {**base, "extras": {**base["extras"], "local_query": "q1"}},
                  "k2": {**base, "extras": {**base["extras"], "local_query": "q2"}}}
        self.assertEqual(answers._settle_local_only(merged, {"q1": "answer"}), (True, ["k1"], {}))
        self.assertEqual(list(merged), ["k2"])
        self.assertEqual(answers._settle_local_only({"knowledge": {"agent": "knowledge", "status": "answer", "extras": {}}}, {}),
                         (False, [], {}))
        for text in (answers.LOCAL_ONLY_FAILED, answers.LOCAL_ONLY_FAILED_ALT, answers.LOCAL_ONLY_UNASKED,
                     answers.LOCAL_ONLY_UNASKED_ALT, answers.LOCAL_ONLY_MISS, answers.LOCAL_ONLY_MISS_ALT):
            self.assertNotIn("—", text)

    def test_auto_mode_local_answer_aggregates_internally_without_web(self):
        with patch.object(answers, "_judge_gap", side_effect=AssertionError("no gap judgment")), \
                patch.object(answers, "_run_external", side_effect=AssertionError("no web answer")):
            events = self.run_stream(answers._auto_answer(self.chat["id"], "사내", self.context, Q_HIT,
                                                          {"knowledge": self.placeholder()}))
        self.assertEqual(sum(t.startswith("로컬 지식 에이전트에 질문하고 있습니다") for t in thinking(events)), 1)
        self.assertEqual(len(self.stream_calls), 1)
        self.assertNotIn(knowledge.LOCAL_ONLY_REASON, self.stream_calls[0]["messages"][-1]["content"])
        self.assertEqual(events[-1]["sources"]["local"]["items"][0]["doc_id"], "hq-doc-001")

    def test_openui_aggregation_sees_only_the_local_source(self):
        seen: dict = {}

        async def fake_program(chat_id, source, messages, system, **kw):
            seen.update(kw, messages=messages)
            yield {"type": "done", "format": openui.FORMAT, "plain": "로컬 답"}
        with patch.object(answers.openui, "stream_program", fake_program):
            events = self.run_stream(answers._aggregate_answer(self.chat["id"], "사내", self.context,
                                                               {"knowledge": self.placeholder()}, fmt=openui.FORMAT))
        self.assertEqual(events[-1]["format"], openui.FORMAT)
        self.assertEqual([n["kind"] for n in seen["numbered"]], ["local"])   # 지식(Public) 번호 출처 없음 / no Public numbered source
        self.assertEqual(seen["references"], [])
        body = "\n".join(str(m.get("content") or "") for m in seen["messages"])
        self.assertNotIn(knowledge.LOCAL_ONLY_REASON, body)
        self.assertEqual(self.stream_calls, [])   # 마크다운 취합은 돌지 않는다 / the markdown aggregation does not run

    def test_chat_run_draws_the_handover_as_done_and_keeps_the_snapshot(self):
        from app import conversation_execution as conversation, execution_store as store
        d = {"version": 3, "query": Q_HIT, "steps": [{"id": "knowledge", "agent": "knowledge", "task": Q_HIT, "depends_on": [], "inputs": {}}],
             "send_query": "", "clarify": None, "document": None, "use_previous": False, "web": False}
        scope = pipeline._clean_scope_files({"local_agents": [HQ, HQ, 5]})
        run = conversation.create(self.chat, d, Q_HIT, self.context, "사내", None, scope, "", "")
        with patch.object(knowledge.kb, "search", side_effect=AssertionError("no Public search")):
            events = self.run_stream(conversation.drive(run, self.chat, [], None))
        status = [e for e in events if e["type"] == "agent_status" and e["task_id"] == "knowledge" and e["status"] != "running"]
        self.assertEqual([(e["status"], e["detail"]) for e in status], [("done", knowledge.LOCAL_ONLY_REASON)])
        self.assertIn(f"로컬 · {HQ_NAME}(Qwen 3.5-4B) 답변 확보 · 출처 1건", thinking(events))
        done = next(e for e in events if e["type"] == "done")
        self.assertEqual(done["sources"]["local"]["items"][0]["doc_id"], "hq-doc-001")
        snap = store.get(run["id"])["snapshot"]
        self.assertEqual(snap["scope_files"]["local_agents"], [HQ])
        self.assertEqual(snap["results"]["knowledge"]["status"], "not_found")   # 실행 상태는 그대로 / the run state is unchanged
        self.assertTrue(snap["results"]["knowledge"]["extras"]["local_only"])
        self.assertEqual(snap["local_resolved"], ["knowledge"])                  # 로컬이 메운 자리 / the placeholder local filled
        self.assertEqual(store.get(run["id"])["state"], "completed")

    def test_chat_run_redraws_the_card_failed_when_local_fails(self):
        from app import conversation_execution as conversation, execution_store as store
        d = {"version": 3, "query": Q_HIT, "steps": [{"id": "knowledge", "agent": "knowledge", "task": Q_HIT, "depends_on": [], "inputs": {}}],
             "send_query": "", "clarify": None, "document": None, "use_previous": False, "web": False}
        run = conversation.create(self.chat, d, Q_HIT, self.context, "사내", None, pipeline._clean_scope_files({"local_agents": [HQ]}), "", "")
        with patch.object(knowledge.kb, "search", side_effect=AssertionError("no Public search")), \
                patch.object(lk, "TRANSPORT", httpx.MockTransport(refused)):
            events = self.run_stream(conversation.drive(run, self.chat, [], None))
        self.assertEqual(statuses(events), [("knowledge", "done", knowledge.LOCAL_ONLY_REASON),
                                            ("knowledge", "failed", answers.LOCAL_ONLY_FAILED)])
        types = [e["type"] for e in events]
        self.assertLess(max(i for i, e in enumerate(events) if e["type"] == "agent_status"), types.index("answer_head"))
        snap = store.get(run["id"])
        self.assertEqual(snap["snapshot"]["local_resolved"], [])
        self.assertEqual(snap["state"], "completed")   # 후속이 없는 질문은 종전처럼 완료 / no follow-up: completed as before


class LocalOnlyCardFlagTests(_DbCase):
    """지식 카드 agent_status 의 local_only: true(2026-10-28, 조정자 요청 — 화면이 로컬 전용 모양으로 그린다): 넘김 done · 다시 이어 쓰기 ·
    로컬 단계 뒤 failed · 쓸 수 없어 닫힘 failed 에 싣고, 그 밖(실행 중 · Public)에는 키가 없다. 트레이스(meta.trace)에도 같은 키가 남는다.
    local_only: true on the knowledge card's agent_status (2026-10-28, coordinator request; the screen draws the local-only look): on
    the handover done, the resume replay, the failed after the local stage and the failed of a closed choice; no key elsewhere
    (running, Public). The trace (meta.trace) keeps the same key."""

    def setUp(self):
        super().setUp()
        self.chat = db.create_chat("카드 표시", "사내")

        async def fake_stream(messages, system=None):
            yield "답"
        self.stack.enter_context(patch.object(answers, "_astream", fake_stream))
        self.stack.enter_context(patch("app.llm.stream", side_effect=AssertionError("unexpected LLM stream")))
        self.stack.enter_context(patch("app.llm.generate_grounded_meta", side_effect=AssertionError("unexpected web")))

    def drive(self, scope_files, query=Q_HIT):
        from app import conversation_execution as conversation
        d = {"version": 3, "query": query, "steps": [{"id": "knowledge", "agent": "knowledge", "task": query, "depends_on": [], "inputs": {}}],
             "send_query": "", "clarify": None, "document": None, "use_previous": False, "web": False}
        run = conversation.create(self.chat, d, query, [{"role": "user", "content": query}], "사내", None,
                                  pipeline._clean_scope_files(scope_files), "", "")
        return asyncio.run(collect(conversation.drive(run, self.chat, [], None)))

    def flagged(self, events):
        return [(e["status"], e.get("detail"), e.get("local_only")) for e in events if e.get("type") == "agent_status"]

    def test_the_flag_rides_the_final_card_states_only(self):
        with patch.object(knowledge.kb, "search", side_effect=AssertionError("no Public search")):
            handed = self.flagged(self.drive({"local_agents": [HQ]}))
            missed = self.flagged(self.drive({"local_agents": [HQ]}, Q_MISS))
            closed = self.flagged(self.drive({"local_agents": ["kl_nope"]}))
        self.assertEqual(handed, [("running", None, None), ("done", knowledge.LOCAL_ONLY_REASON, True)])
        self.assertEqual(missed, [("running", None, None), ("done", knowledge.LOCAL_ONLY_REASON, True),
                                  ("failed", answers.LOCAL_ONLY_MISS, True)])
        self.assertEqual(closed, [("running", None, None), ("failed", knowledge.LOCAL_ONLY_UNAVAILABLE, True)])

        def generate(messages, system=None, json_mode=False, tier=None, **kw):
            return {"subqueries": [Q_HIT], "files": []} if json_mode else "공개 규정 답변입니다."
        with patch.object(knowledge.kb, "search", return_value=HIT), patch.object(knowledge.llm, "generate", side_effect=generate), \
                patch.object(knowledge.catalog, "allowed_knowledge_files", return_value={"보안규정.pdf"}):
            public = [e for e in self.drive({}) if e.get("type") == "agent_status"]
        self.assertTrue(public)
        self.assertTrue(all("local_only" not in e for e in public), public)   # Public = 키 없음(종전 모양) / no key

    def test_the_resume_replay_carries_the_flag(self):
        from app import task_runner
        steps = [{"id": "knowledge", "agent": "knowledge", "task": Q_HIT, "depends_on": [], "inputs": {}}]
        saved = {"knowledge": {**knowledge._local_only(Q_HIT, None, {"local_agents": [HQ]}), "agent": "knowledge", "task_id": "knowledge"}}
        events = asyncio.run(collect(task_runner.run_tasks(steps, [], saved)))
        self.assertEqual(self.flagged(events), [("done", "저장된 실행 결과를 이어서 사용합니다", True)])
        public = {"knowledge": {"status": "answer", "text": "공개", "extras": {}, "agent": "knowledge", "task_id": "knowledge"}}
        events = asyncio.run(collect(task_runner.run_tasks(steps, [], public)))
        self.assertEqual(self.flagged(events), [("done", "저장된 실행 결과를 이어서 사용합니다", None)])
        self.assertNotIn("local_only", [e for e in events if e["type"] == "agent_status"][0])

    def test_the_trace_keeps_the_flag_for_restore(self):
        from app import chats_api
        trace = {"thinking": [], "tasks": [], "parallel": False, "status": {}, "lines": []}
        for ev in ({"type": "agent_status", "task_id": "knowledge", "status": "running"},
                   {"type": "agent_status", "task_id": "knowledge", "status": "done", "detail": knowledge.LOCAL_ONLY_REASON, "local_only": True},
                   {"type": "agent_status", "task_id": "knowledge", "status": "failed", "detail": answers.LOCAL_ONLY_FAILED, "local_only": True},
                   {"type": "agent_status", "task_id": "data", "status": "done", "detail": "SQL 실행 완료"}):
            chats_api._trace_collect(trace, ev)
        self.assertEqual(trace["status"], {"knowledge": {"status": "failed", "detail": answers.LOCAL_ONLY_FAILED, "local_only": True},
                                           "data": {"status": "done", "detail": "SQL 실행 완료"}})
        self.assertEqual(trace["lines"], [
            {"t": "status", "task_id": "knowledge", "status": "running", "detail": None},
            {"t": "status", "task_id": "knowledge", "status": "done", "detail": knowledge.LOCAL_ONLY_REASON, "local_only": True},
            {"t": "status", "task_id": "knowledge", "status": "failed", "detail": answers.LOCAL_ONLY_FAILED, "local_only": True},
            {"t": "status", "task_id": "data", "status": "done", "detail": "SQL 실행 완료"}])


class LocalOnlyFollowUpTests(_DbCase):
    """로컬 전용 질문 + 발송 · 파일 생성 후속(2026-10-28 검토 반영): 로컬이 답을 메우면 후속이 이어지고, 못 찾거나 실패하면 보류된다.
    A local-only question with a send or file follow-up (2026-10-28 review): when local fills the answer the follow-up proceeds;
    when local finds nothing or fails it is held."""

    DRAFT = {"kind": "mail.action.compose", "payload": {"to": "me@example.invalid", "subject": "보고"}, "summary": "나에게 메일 보내기"}
    HOLD = "필수 작업이 실패하여 발송을 보류했음을 알린다"

    def setUp(self):
        super().setUp()
        from app import conversation_execution as conversation
        self.chat = db.create_chat("로컬 전용 후속", "사내")
        self.prompts: list[dict] = []

        async def fake_stream(messages, system=None):
            self.prompts.append({"messages": messages, "system": system or ""})
            yield "비밀번호는 90일마다 변경합니다 (로컬 · 본사 로컬 에이전트)."
        self.stack.enter_context(patch.object(answers, "_astream", fake_stream))
        self.stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")))
        self.stack.enter_context(patch("app.llm.stream", side_effect=AssertionError("unexpected LLM stream")))
        self.stack.enter_context(patch("app.llm.generate_grounded_meta", side_effect=AssertionError("unexpected web")))
        self.stack.enter_context(patch.object(knowledge.kb, "search", side_effect=AssertionError("no Public search")))
        draft = self.DRAFT

        async def probe(query, context, allow_web=False, eff=None, **kw):
            return {"status": "answer", "text": "", "extras": {"action_draft": draft}}
        self.stack.enter_context(patch("app.agents.groupware.run", probe))
        self.stack.enter_context(patch("app.agents.groupware.build_batch_delivery",
                                       lambda sends, body: {**draft, "payload": {**draft["payload"], "body": body}}))
        self.doc_calls: list[dict] = []

        async def fake_document(chat, cfg, run):
            self.doc_calls.append(cfg)
            run["snapshot"]["artifact"] = {"id": "doc_local_only", "fmt": cfg.get("format")}
            yield {"type": "doc_done"}
        self.stack.enter_context(patch("app.artifact_execution.document_events", fake_document))
        self.conversation = conversation

    def drive(self, query=Q_HIT, *, send="", document=None, scope_files=None, pre=None):
        from app import execution_store as store
        d = {"version": 3, "query": query, "steps": [{"id": "knowledge", "agent": "knowledge", "task": query, "depends_on": [], "inputs": {}}],
             "send_query": send, "clarify": None, "document": document, "use_previous": False, "web": False}
        sf = pipeline._clean_scope_files({"local_agents": [HQ]} if scope_files is None else scope_files)
        run = self.conversation.create(self.chat, d, query, [{"role": "user", "content": query}], "사내", None, sf, "", "")
        if document:
            run["snapshot"]["doc_cfg"] = {"format": document["format"], "topic": document["topic"], "style": "", "length": "",
                                          "source": "internal"}
        if pre:
            run["snapshot"]["results"].update(copy.deepcopy(pre))
        store.save(run)
        events = self.run_stream(self.conversation.drive(run, self.chat, [], None))
        return events, store.get(run["id"])

    def run_stream(self, stream) -> list[dict]:
        return asyncio.run(collect(stream))

    def held(self) -> bool:
        return any(self.HOLD in p["system"] for p in self.prompts)

    def test_local_answer_lets_the_mail_send_reach_its_confirm_and_complete(self):
        events, row = self.drive(send="나에게 메일로 보내줘")
        confirms = [e for e in events if e["type"] == "confirm"]
        self.assertEqual(len(confirms), 1)
        self.assertFalse(self.held())
        self.assertEqual(row["state"], "needs_confirmation")
        self.assertEqual(row["snapshot"]["local_resolved"], ["knowledge"])
        self.assertIn("90일", next(p for p in confirms[0]["params"] if p["k"] == "body")["value"])   # 본문 = 로컬 답 보고서 / the local report
        self.assertNotIn("error", [e["type"] for e in events])
        self.conversation.action_finished(confirms[0]["action_id"], True, "보냈습니다")
        from app import execution_store as store
        self.assertEqual(store.get(row["id"])["state"], "completed")

    def test_local_answer_lets_the_document_follow_up_run_and_complete(self):
        events, row = self.drive(document={"format": "pptx", "topic": "비밀번호 규정"})
        self.assertEqual(len(self.doc_calls), 1)
        self.assertEqual(self.doc_calls[0]["source"], "context")
        self.assertEqual(row["state"], "completed")
        self.assertEqual(events[-1], {"type": "execution_result", "state": "completed", "run_id": row["id"], "artifact": True})

    def test_local_miss_or_failure_still_holds_the_send_and_the_document(self):
        events, row = self.drive(Q_MISS, send="나에게 메일로 보내줘")
        self.assertEqual([e for e in events if e["type"] == "confirm"], [])
        self.assertTrue(self.held())
        self.assertEqual(row["state"], "failed")
        self.assertIn(("knowledge", "failed", answers.LOCAL_ONLY_MISS), statuses(events))
        self.prompts.clear()
        with patch.object(lk, "TRANSPORT", httpx.MockTransport(refused)):
            events, row = self.drive(document={"format": "pptx", "topic": "비밀번호 규정"})
        self.assertEqual(self.doc_calls, [])
        self.assertEqual(row["state"], "failed")
        self.assertIn(("knowledge", "failed", answers.LOCAL_ONLY_FAILED), statuses(events))

    def test_public_runs_keep_the_former_path(self):
        public = {"knowledge": {"status": "answer", "text": "공개 규정 답변입니다.", "extras": {}, "agent": "knowledge",
                                "task_id": "knowledge", "label": "지식관리"}}
        with patch.object(answers, "_local_plan", side_effect=AssertionError("no local calls without local material")):
            events, row = self.drive(send="나에게 메일로 보내줘", scope_files={}, pre=public)
        self.assertEqual(len([e for e in events if e["type"] == "confirm"]), 1)
        self.assertNotIn("local_resolved", row["snapshot"])   # 로컬 전용 자리가 없으면 선실행하지 않는다 / no pre-run without placeholders
        self.assertFalse(self.held())


class NlScheduleLocalTests(_DbCase):
    """로컬 지식 에이전트를 고른 채팅의 자연어 예약(2026-10-28 검토 반영): 예약을 만들지 않고 이유와 방법을 안내한다(한국어 기본, 영어 질문엔 영어).
    A natural-language schedule from a chat that chose local agents (2026-10-28 review): no schedule, a note on why and how
    (Korean by default, English for an English request)."""

    SPEC = {"name": "보안 규정 요약", "prompt": "보안 규정 변경 사항을 요약해서 알려줘", "rule": "weekly", "run_at": "09:00",
            "days": [0], "mday": None, "points": []}

    def setUp(self):
        super().setUp()
        from app import collections_store, schedules
        collections_store.init_collections()
        schedules.init_schedules()
        self.schedules = schedules
        self.chat = db.create_chat("예약 시험", "사내")
        self.stack.enter_context(patch.object(schedules, "_owner_names", return_value={}))
        self.stack.enter_context(patch.object(pipeline, "_resolve_eff", return_value=None))
        self.stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")))
        self.stack.enter_context(patch("app.llm.stream", side_effect=AssertionError("unexpected LLM stream")))
        self.stack.enter_context(patch.object(pipeline, "_judge_intent", side_effect=AssertionError("no intent planning")))
        self.parse = self.stack.enter_context(patch.object(pipeline.schedules_nl, "parse", return_value=dict(self.SPEC)))

    def run_pipeline(self, message, scope_files):
        return asyncio.run(collect(pipeline.run_pipeline(self.chat, message, "사내", agents=["knowledge"],
                                                          scope_files=scope_files, allow_schedule=True)))

    def test_a_local_choice_never_creates_a_schedule_and_says_why(self):
        events = self.run_pipeline("매주 월요일 9시에 보안 규정 변경 사항을 요약해서 알려줘", {"local_agents": [HQ]})
        self.parse.assert_called_once()
        self.assertEqual([e["type"] for e in events], ["thinking_start", "answer_head", "token", "done"])
        self.assertEqual(events[2]["text"], pipeline.schedules_nl.LOCAL_BLOCKED_KO)
        self.assertEqual(self.schedules.count_global(), 0)
        last = db.list_messages(self.chat["id"])[-1]
        self.assertEqual((last["role"], last["content"], last["id"]), ("assistant", pipeline.schedules_nl.LOCAL_BLOCKED_KO,
                                                                         events[-1]["message_id"]))
        # 영어 요청엔 영어 / English for an English request
        events = self.run_pipeline("Set a reminder every Monday at 9 to review the security policy", {"local_agents": [HQ]})
        self.assertEqual(events[2]["text"], pipeline.schedules_nl.LOCAL_BLOCKED_EN)
        self.assertEqual(self.schedules.count_global(), 0)
        for text in (pipeline.schedules_nl.LOCAL_BLOCKED_KO, pipeline.schedules_nl.LOCAL_BLOCKED_EN):
            self.assertNotIn("—", text)
        # 만드는 함수도 넓히지 않는다 / the creator itself never widens
        self.assertIsNone(pipeline.schedules_nl.create_from_spec(dict(self.SPEC), self.chat, "", "사내", ["knowledge"],
                                                                 {"local_agents": [HQ]}))
        self.assertEqual(self.schedules.count_global(), 0)

    def test_without_a_local_choice_the_schedule_is_created_as_before(self):
        events = self.run_pipeline("매주 월요일 9시에 보안 규정 변경 사항을 요약해서 알려줘", {})
        self.assertIn("schedule", [e["type"] for e in events])
        self.assertEqual(self.schedules.count_global(), 1)


if __name__ == "__main__":
    unittest.main()
