# -*- coding: utf-8 -*-
"""워크플로우 설정 개편 백엔드(2026-09-26) — 등록 업무 자동화 에이전트 도구(wa:)·필수값 추출 게이트·팔레트 명세.
임시 DB 만 쓰고 실제 LLM·HTTP 호출은 없다(전부 패치).

Workflow settings rework, backend (2026-09-26): registered work-agent tools (wa:), the required-value extraction gate and
the palette specs. Temp DB only; no real LLM or HTTP calls (everything is patched)."""
import copy
import json
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from db_fixture import isolate_db
from app import (artifact_execution, connectors, db, execution_store as store, flow_api_call, flows, flows_api,
                 mcp_servers, tool_contracts, work_agents)
from app.agents import AGENT_REGISTRY
from app.tool_runtime import EFFECT_KEY, call_connector


def api_agent_body(**over) -> dict:
    """API 방식 에이전트 — 조회 1개(경로 변수·쿼리), 실행 1개(경로 변수·본문) / API agent: one read, one action"""
    d = {"name": "사내 ERP", "description": "매출·주문", "method": "api", "enabled": True,
         "config": {"base_url": "https://erp.example.invalid/api", "timeout": 20,
                    "auth": {"type": "bearer", "key": "wa-secret-1", "name": "Authorization"},
                    "endpoints": [
                        {"name": "GetSalesSummary", "method": "GET", "path": "/sales/{branch}", "description": "지점 매출 요약",
                         "params": [{"name": "branch", "type": "string", "required": True, "description": "지점 코드", "example": "SEL"},
                                    {"name": "period", "type": "string", "required": False, "description": "조회 월", "example": "2026-08"}]},
                        {"name": "ApproveOrder", "method": "POST", "path": "/orders/{order_id}/approve", "kind": "action",
                         "description": "주문 승인",
                         "params": [{"name": "order_id", "type": "string", "required": True, "description": "주문 번호"},
                                    {"name": "qty", "type": "integer", "required": False},
                                    {"name": "note", "type": "string", "required": False}]}]}}
    d.update(over)
    return d


MCP_TOOLS = [
    {"name": "ems_status", "title": "설비 상태", "description": "설비 가동 상태", "kind": "read", "enabled": True,
     "input_schema": {"type": "object", "properties": {"equipment_id": {"type": "string", "description": "설비 번호"}},
                      "required": ["equipment_id"]},
     "output_schema": {"type": "object", "properties": {"status": {"type": "string"}}}},
    {"name": "ems_control", "title": "설비 제어", "description": "설비 가동·정지", "kind": "action", "enabled": True,
     "input_schema": {"type": "object", "properties": {"equipment_id": {"type": "string"},
                                                        "command": {"type": "string", "enum": ["start", "stop"]}},
                      "required": ["equipment_id", "command"]}},
    {"name": "ems_hidden", "description": "사용 중지 도구", "kind": "read", "enabled": False,
     "input_schema": {"type": "object", "properties": {}, "required": []}},
]


def mcp_agent_body(**over) -> dict:
    d = {"name": "설비 MCP", "description": "설비", "method": "mcp", "enabled": True,
         "config": {"url": "https://mcp.example.invalid/mcp", "timeout": 10,
                    "auth": {"type": "bearer", "key": "wa-secret-2", "name": "Authorization"}, "tools": copy.deepcopy(MCP_TOOLS)}}
    d.update(over)
    return d


def flow_with(nodes, stage2=False) -> dict:
    """정상 최소 플로우(검사할 노드는 마지막 단계) / a minimal valid flow with the nodes under test in the last stage"""
    stages = [{"nodes": nodes, "answer_prompt": ""}]
    if stage2:
        stages = [{"nodes": [{"agent": "data", "resources": [], "instruction": "분석"}], "answer_prompt": ""}] + stages
    return {"id": "fl_t", "name": "테스트", "description": "", "group": "og1", "stages": stages}


class DbCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        # flows 는 임포트 시점에 DB_PATH 를 잡는다 — 실제 DB 오염 방지 / flows binds DB_PATH at import: keep the real DB out
        self.stack.enter_context(patch.object(flows, "DB_PATH", db.DB_PATH))
        self.stack.enter_context(patch("app.llm.stream", side_effect=AssertionError("unexpected LLM stream")))


# ─────────────────────────────────────────────────────────────────────────────
# 정규화 / normalization (순수 함수 / pure)
# ─────────────────────────────────────────────────────────────────────────────

class NormalizeTests(unittest.TestCase):
    def test_extract_prompt_is_trimmed_kept_and_omitted_when_blank(self):
        nodes = [{"agent": "knowledge", "resources": [], "instruction": "규정", "extract_prompt": "  고객사, 기간  "},
                 {"agent": "data", "resources": [], "instruction": "", "extract_prompt": "   "},
                 {"agent": "groupware", "resources": [], "instruction": "", "extract_prompt": "받는 사람"},
                 {"agent": "web", "resources": [], "instruction": "", "extract_prompt": "무시"}]
        out = flows.normalize_flows([flow_with(nodes)])[0]["stages"][0]["nodes"]
        self.assertEqual(out[0]["extract_prompt"], "고객사, 기간")
        self.assertNotIn("extract_prompt", out[1])   # 비면 키 생략 / blank → key omitted
        self.assertEqual(out[2]["extract_prompt"], "받는 사람")
        self.assertNotIn("extract_prompt", out[3])   # 다른 작업 종류에는 두지 않는다 / other task kinds never carry it

    def test_extract_prompt_over_cap_or_not_text_names_the_spot(self):
        long = [{"agent": "data", "resources": [], "instruction": "", "extract_prompt": "x" * (flows.MAX_INSTR + 1)}]
        with self.assertRaises(flows.FlowValidationError) as ctx:
            flows.normalize_flows([flow_with(long)])
        self.assertEqual(str(ctx.exception), f"flows[0].stages[0].nodes[0].extract_prompt: {flows.MAX_INSTR}자 이하로 적어 주세요")
        with self.assertRaises(flows.FlowValidationError) as ctx:
            flows.normalize_flows([flow_with([{"agent": "knowledge", "resources": [], "extract_prompt": 12}])])
        self.assertIn("extract_prompt", str(ctx.exception))
        # 앞뒤 공백을 정리한 뒤 길이를 잰다 / the length is measured after trimming
        padded = [{"agent": "data", "resources": [], "extract_prompt": " " + "x" * flows.MAX_INSTR + " "}]
        self.assertEqual(len(flows.normalize_flows([flow_with(padded)])[0]["stages"][0]["nodes"][0]["extract_prompt"]),
                         flows.MAX_INSTR)

    def test_auto_with_a_registered_tool_takes_exactly_one_and_shares_binding_rules(self):
        key = "wa:agent_ab12cd34:GetSalesSummary"
        node = {"agent": "auto", "resources": [key], "instruction": "매출 확인",
                "input_bindings": {"branch": {"mode": "value", "value": " SEL "}, "period": {"mode": "ask", "value": "x"},
                                   "free": {"mode": "auto"}}}
        out = flows.normalize_flows([flow_with([node])])[0]["stages"][0]["nodes"][0]
        self.assertEqual(out["resources"], [key])
        self.assertEqual(out["input_bindings"], {"branch": {"mode": "value", "value": "SEL"},
                                                 "period": {"mode": "ask", "value": ""}})
        for bad_res in ([key, "email.info.inbox"], [key, "wa:agent_ab12cd34:ApproveOrder"], ["email.info.inbox", key]):
            with self.subTest(res=bad_res), self.assertRaises(flows.FlowValidationError) as ctx:
                flows.normalize_flows([flow_with([{"agent": "auto", "resources": bad_res}])])
            self.assertEqual(str(ctx.exception),
                             "flows[0].stages[0].nodes[0].resources: 등록 에이전트 도구는 1개만 선택할 수 있습니다")
        with self.assertRaises(flows.FlowValidationError) as ctx:   # 키 모양 / key shape
            flows.normalize_flows([flow_with([{"agent": "auto", "resources": ["wa:agent_x"]}])])
        self.assertIn("형식", str(ctx.exception))
        # 외부 도구와 같은 바인딩 검증(api_key 금지·앞 단계만) / the external-tool binding rules
        with self.assertRaises(flows.FlowValidationError) as ctx:
            flows.normalize_flows([flow_with([{**node, "input_bindings": {"branch": {"mode": "value", "value": "{{api_key}}"}}}])])
        self.assertIn("api_key", str(ctx.exception))
        with self.assertRaises(flows.FlowValidationError) as ctx:
            flows.normalize_flows([flow_with([{**node, "input_bindings": {"branch": {"mode": "value", "value": "{{step1.result}}"}}}])])
        self.assertIn("앞 단계", str(ctx.exception))
        ok = flows.normalize_flows([flow_with([{**node, "input_bindings": {"branch": {"mode": "value", "value": "{{step1.result.code}}"}}}],
                                              stage2=True)])
        self.assertEqual(ok[0]["stages"][1]["nodes"][0]["input_bindings"]["branch"]["value"], "{{step1.result.code}}")

    def test_builtin_auto_items_keep_the_old_rules(self):
        node = {"agent": "auto", "resources": ["email.info.inbox", "edu.info.learning"], "instruction": "",
                "input_bindings": {"a": {"mode": "value", "value": "1"}}}
        out = flows.normalize_flows([flow_with([node])])[0]["stages"][0]["nodes"][0]
        self.assertEqual(out["resources"], ["email.info.inbox", "edu.info.learning"])
        self.assertNotIn("input_bindings", out)   # 내장 항목은 바인딩을 받지 않는다(종전 그대로) / built-ins ignore bindings as before


# ─────────────────────────────────────────────────────────────────────────────
# 팔레트 / palette
# ─────────────────────────────────────────────────────────────────────────────

class PaletteTests(DbCase):
    def test_connectors_carry_input_and_output_schemas_for_both_sources(self):
        api = connectors.create({"name": "재고 API", "description": "재고", "kind": "read",
                                 "api": {"url": "https://erp.example.invalid/stock/{{input.sku}}",
                                         "input_docs": [{"name": "sku", "description": "품목 코드", "example": "SKU-1"}],
                                         "response": {"outputs": [{"name": "qty", "path": "data.qty"}]}}})
        plain = connectors.create({"name": "날씨 API", "description": "날씨", "kind": "read",
                                   "api": {"url": "https://x.example.invalid/weather"}})
        server = mcp_servers.create({"name": "데모 MCP", "url": "https://mcp.example.invalid/mcp", "auth": {"type": "none"},
                                     "tools": copy.deepcopy(MCP_TOOLS[:2])})
        status_id = mcp_servers.tool_connector_id(server["id"], "ems_status")
        control_id = mcp_servers.tool_connector_id(server["id"], "ems_control")
        geff = {"nodes": {api["id"]: 1, plain["id"]: 1, status_id: 1, control_id: 1}}
        pal = {c["id"]: c for c in flows_api._group_connectors(geff)}
        self.assertEqual(pal[api["id"]]["input_schema"], tool_contracts.contract(api)["input_schema"])
        self.assertEqual(pal[api["id"]]["output_schema"],
                         {"type": "object", "properties": {"qty": {"type": "string", "description": "응답 경로 data.qty"}}})
        self.assertIsNone(pal[plain["id"]]["output_schema"])
        self.assertEqual(pal[status_id]["output_schema"], MCP_TOOLS[0]["output_schema"])   # 서버의 도구 행 / the server's tool row
        self.assertIsNone(pal[control_id]["output_schema"])
        self.assertEqual(pal[control_id]["input_schema"]["required"], ["equipment_id", "command"])
        # 표시 전용 — 실행 계약에는 출력 명세가 없다(있으면 tool_runtime 이 응답을 검증한다) / display only, not in the contract
        self.assertNotIn("output_schema", connectors.get_connector(status_id)["api"]["tool_contract"])

    def test_auto_catalog_adds_registered_agent_sections_with_gating(self):
        a = work_agents.create(api_agent_body())
        m = work_agents.create(mcp_agent_body())
        work_agents.create(api_agent_body(name="중지 ERP", enabled=False))
        full = flows_api._auto_catalog(None)
        self.assertEqual([s["ns"] for s in full[:2]], ["email", "edu"])      # 내장 섹션이 먼저 / built-ins first
        self.assertEqual(set(full[0]), {"ns", "label", "items"})            # 내장 섹션 모양은 그대로 / built-in shape unchanged
        wa = {s["agent_id"]: s for s in full if s["ns"] == "wa"}
        self.assertEqual(set(wa), {a["id"], m["id"]})                       # 사용 중지 에이전트 제외 / disabled agent left out
        sec = wa[a["id"]]
        self.assertEqual((sec["label"], sec["method"]), ("사내 ERP", "api"))
        sales = sec["items"][0]
        self.assertEqual(sales["key"], f"wa:{a['id']}:GetSalesSummary")
        self.assertEqual(sales["key"].split(":", 2), ["wa", a["id"], "GetSalesSummary"])
        self.assertEqual((sales["label"], sales["kind"], sales["description"]), ("GetSalesSummary", "read", "지점 매출 요약"))
        self.assertEqual(sales["input_schema"]["required"], ["branch"])
        self.assertEqual([(i["name"], i.get("required"), i.get("type")) for i in sales["inputs"]],
                         [("branch", True, "string"), ("period", False, "string")])
        self.assertEqual((sales["inputs"][0]["description"], sales["inputs"][0]["example"]), ("지점 코드", "SEL"))
        self.assertIsNone(sales["output_schema"])
        self.assertEqual(sec["items"][1]["kind"], "action")
        tools = {i["label"]: i for i in wa[m["id"]]["items"]}
        self.assertEqual(set(tools), {"ems_status", "ems_control"})          # 사용 중지 도구 제외 / disabled tool left out
        self.assertEqual(tools["ems_status"]["output_schema"], MCP_TOOLS[0]["output_schema"])
        self.assertEqual((tools["ems_status"]["kind"], tools["ems_control"]["kind"]), ("read", "action"))
        self.assertEqual([i["name"] for i in tools["ems_control"]["inputs"]], ["equipment_id", "command"])
        self.assertEqual(tools["ems_control"]["inputs"][1]["enum"], ["start", "stop"])
        # 게이팅: 그 에이전트 노드를 열람(≥1)할 수 있을 때만 / gated on the agent node
        gated = flows_api._auto_catalog({"nodes": {"agent_email": 1, m["id"]: 1, a["id"]: 0}})
        self.assertEqual([s.get("agent_id") or s["ns"] for s in gated], ["email", m["id"]])

    def test_wa_items_carry_unsupported_and_sections_without_usable_tools_are_dropped(self):
        # 리뷰 1: 항목마다 unsupported(명세 단순화 경고) — MCP 는 도구 행 그대로, API 엔드포인트는 []
        # Review 1: every item carries unsupported (simplified-spec warning): MCP as stored on the tool row, [] for API endpoints
        tools = copy.deepcopy(MCP_TOOLS[:2])
        tools[0]["input_schema"]["properties"]["memo"] = {"description": "타입 없는 메모"}   # 단순화되며 경고가 남는다 / leaves a warning
        m = work_agents.create(mcp_agent_body(config={**mcp_agent_body()["config"], "tools": tools}))
        a = work_agents.create(api_agent_body())
        # 리뷰 5: 쓸 수 있는 도구가 없는 섹션은 내보내지 않는다 — 도구가 모두 사용 중지인 MCP, 엔드포인트가 없는 API
        # Review 5: sections with no usable tool are not emitted: an MCP agent with every tool off, an API agent with no endpoints
        off_tools = [dict(t, enabled=False) for t in copy.deepcopy(MCP_TOOLS)]
        idle_mcp = work_agents.create(mcp_agent_body(name="전부 중지 MCP", config={**mcp_agent_body()["config"], "tools": off_tools}))
        empty_api = work_agents.create(api_agent_body(name="빈 ERP", config={**api_agent_body()["config"], "endpoints": []}))
        wa = {s["agent_id"]: s for s in flows_api._auto_catalog(None) if s["ns"] == "wa"}
        self.assertEqual(set(wa), {m["id"], a["id"]})
        self.assertNotIn(idle_mcp["id"], wa)
        self.assertNotIn(empty_api["id"], wa)
        mcp_items = {i["label"]: i for i in wa[m["id"]]["items"]}
        self.assertEqual(mcp_items["ems_status"]["unsupported"], ["memo: 타입이 없어 문자열로 처리"])
        self.assertEqual(mcp_items["ems_control"]["unsupported"], [])
        self.assertEqual([i["unsupported"] for i in wa[a["id"]]["items"]], [[], []])
        self.assertTrue(all(i["items"] for i in wa.values()))


# ─────────────────────────────────────────────────────────────────────────────
# 필수값 추출 게이트 / extraction gate
# ─────────────────────────────────────────────────────────────────────────────

class ExtractGateTests(unittest.IsolatedAsyncioTestCase):
    NODE = {"agent": "knowledge", "resources": ["규정.pdf"], "instruction": "계약 조건 확인",
            "extract_prompt": "고객사 이름과 계약 연도를 찾는다"}

    def test_missing_values_become_needs_input_and_deterministic_review_items(self):
        captured = {}

        def fake_generate(prompt, **kw):
            captured["prompt"], captured["kw"] = prompt, kw
            return {"values": {"고객사": "A사", "계약 연도": None}}
        with patch.object(flows.llm, "generate", side_effect=fake_generate):
            found, pending = flows._extract_required(self.NODE, "A사 계약 조건 알려줘",
                                                     [{"label": "1단계 데이터 분석", "text": "앞 결과"}])
        self.assertEqual((captured["kw"].get("tier"), captured["kw"].get("json_mode")), ("lite", True))
        self.assertIn("[추출 지침]\n고객사 이름과 계약 연도를 찾는다", captured["prompt"])
        self.assertIn("[사용자 요청]\nA사 계약 조건 알려줘", captured["prompt"])
        self.assertIn("앞 결과", captured["prompt"])
        self.assertIn('"values"', captured["kw"]["system"])
        self.assertEqual(found, {"고객사": "A사"})
        self.assertEqual(pending["status"], "needs_input")
        self.assertEqual(pending["text"], "필수값을 알려주세요: 계약 연도")
        self.assertEqual(set(pending["extras"]), {"missing_inputs", "inputs", "questions"})   # connector_id 없음 / no connector_id
        self.assertEqual((pending["extras"]["missing_inputs"], pending["extras"]["inputs"]), (["계약 연도"], {"고객사": "A사"}))
        question = pending["extras"]["questions"]["계약 연도"]
        self.assertIn("'계약 연도'", question)
        # 단계 검수 → 결정적 항목(도구 없음) / stage review → a deterministic item (no tool)
        ev = {**pending, "_ni": 1, "_node": self.NODE}
        flow = {"stages": [{"nodes": [{"agent": "data"}, self.NODE]}]}
        with patch.object(flows, "_review_llm", side_effect=AssertionError("검수 LLM 불필요")):
            questions, rerun = flows._stage_review(flow, 0, [ev], "q", [], [])
        self.assertEqual(rerun, ["stage1_2"])
        self.assertEqual(questions, [{"id": "in_2_계약 연도", "label": "계약 연도", "question": question, "kind": "text",
                                      "options": [], "required": True, "hint": "고객사 이름과 계약 연도를 찾는다",
                                      "placeholder": "", "input": "계약 연도", "node": 1, "inputs": {"고객사": "A사"},
                                      "task_ids": ["stage1_2"]}])

    def test_llm_failure_asks_without_names_and_shows_the_whole_prompt(self):
        prompt = "필수값: " + "가" * 200
        node = {**self.NODE, "extract_prompt": prompt}
        with patch.object(flows.llm, "generate", side_effect=RuntimeError("model down")), \
                self.assertLogs("ai365.flows", level="WARNING"):
            found, pending = flows._extract_required(node, "q", [])
        self.assertEqual(found, {})
        self.assertEqual(pending["status"], "needs_input")   # 게이트를 건너뛰지 않는다 / the gate is never skipped
        self.assertEqual(pending["extras"], {"missing_inputs": [flows._EXTRACT_UNKNOWN], "inputs": {}, "questions": {}})
        with patch.object(flows, "_review_llm", side_effect=AssertionError):
            questions, _ = flows._stage_review({"stages": [{"nodes": [node]}]}, 0,
                                               [{**pending, "_ni": 0, "_node": node}], "q", [], [])
        self.assertEqual(questions[0]["hint"], prompt)       # 지침 전문 / the whole prompt
        self.assertTrue(questions[0]["required"])
        # 모양이 다른 응답(values 없음)·이름 없는 응답도 같은 처리 / a malformed or empty reply is treated the same
        for reply in ({"answer": "x"}, {"values": {}}, ["x"]):
            with self.subTest(reply=reply), patch.object(flows.llm, "generate", return_value=reply):
                self.assertEqual(flows._extract_required(node, "q", [])[1]["extras"]["missing_inputs"], [flows._EXTRACT_UNKNOWN])

    def test_names_are_capped_at_the_maximum(self):
        many = {f"값{i}": str(i) for i in range(flows.MAX_EXTRACT_VALUES + 3)}
        with patch.object(flows.llm, "generate", return_value={"values": many}):
            found, pending = flows._extract_required(self.NODE, "q", [])
        self.assertIsNone(pending)
        self.assertEqual(len(found), flows.MAX_EXTRACT_VALUES)

    async def test_provided_values_skip_the_llm_and_reach_the_agent_query(self):
        node = {**self.NODE, "_provided_inputs": {"고객사": "A사", "계약 연도": "2025"}}
        run = AsyncMock(return_value={"status": "answer", "text": "계약 조건", "extras": {}})
        with patch.object(flows.llm, "generate", side_effect=AssertionError("LLM 불필요")), \
                patch.dict(AGENT_REGISTRY["knowledge"], {"run": run}):
            result = await flows._run_step_node(node, "계약 조건 알려줘", [], None, [])
        self.assertEqual(result["status"], "done")
        query = run.await_args.args[0]
        self.assertIn("계약 조건 확인\n[필수값] 고객사: A사; 계약 연도: 2025", query)
        self.assertIn("(사용자 질문: 계약 조건 알려줘)", query)
        self.assertNotIn("[필수값]", node["instruction"])     # 저장된 노드는 그대로 / the stored node is untouched

    async def test_needs_input_stops_before_the_agent_runs(self):
        run = AsyncMock()
        with patch.object(flows.llm, "generate", return_value={"values": {"고객사": "  "}}), \
                patch.dict(AGENT_REGISTRY["data"], {"run": run}):
            result = await flows._run_step_node({**self.NODE, "agent": "data", "resources": []}, "q", [], None, [])
        self.assertEqual((result["status"], result["label"]), ("needs_input", "데이터 분석"))
        run.assert_not_awaited()

    async def test_data_resource_check_runs_before_the_gate(self):
        # 리뷰 2: 카탈로그에 없는 데이터 리소스는 추출 게이트(LLM·질문 카드)보다 먼저 실패로 닫힌다
        # Review 2: unknown data resources fail closed before the extraction gate (no LLM, no question card)
        run = AsyncMock()
        node = {**self.NODE, "agent": "data", "resources": ["no_such_table"]}
        with patch.object(flows.llm, "generate", side_effect=AssertionError("리소스 검사가 먼저 / resource check first")), \
                patch.dict(AGENT_REGISTRY["data"], {"run": run}):
            result = await flows._run_step_node(node, "q", [], None, [])
        self.assertEqual(result["status"], "failed")
        self.assertIn("카탈로그에서 찾지 못했습니다", result["text"])
        run.assert_not_awaited()

    def test_nameless_question_carries_the_prompt_in_its_wording(self):
        # 리뷰 3: 이름을 모를 때(LLM 실패·모양 오류·빈 values) 질문 문구 자체에 지침 앞 160자, 안내(hint)는 지침 전문 그대로
        # Review 3: with unknown names (LLM failure, malformed or empty values) the question carries the first 160 chars of the
        # prompt; the hint keeps the whole prompt
        prompt = "고객사와 계약 연도, " + "나" * 300
        node = {**self.NODE, "extract_prompt": prompt}
        for label, patcher in (("failure", patch.object(flows.llm, "generate", side_effect=RuntimeError("down"))),
                               ("malformed", patch.object(flows.llm, "generate", return_value={"answer": "x"})),
                               ("empty", patch.object(flows.llm, "generate", return_value={"values": {}}))):
            with self.subTest(case=label), patcher:
                found, pending = flows._extract_required(node, "q", [])
                self.assertEqual((found, pending["status"]), ({}, "needs_input"))   # 통과로 바꾸지 않는다 / never a pass
                with patch.object(flows, "_review_llm", side_effect=AssertionError):
                    questions, _ = flows._stage_review({"stages": [{"nodes": [node]}]}, 0,
                                                       [{**pending, "_ni": 0, "_node": node}], "q", [], [])
                self.assertEqual(len(questions), 1)
                self.assertEqual(questions[0]["question"], f"지식 관리 작업에 필요한 값을 알려주세요: {prompt[:160]}")
                self.assertEqual(questions[0]["hint"], prompt)
                self.assertEqual(questions[0]["input"], flows._EXTRACT_UNKNOWN)
        # 이름을 아는 경우의 문구는 그대로 / the wording for known names is unchanged
        with patch.object(flows.llm, "generate", return_value={"values": {"고객사": None}}):
            _, pending = flows._extract_required(node, "q", [])
        with patch.object(flows, "_review_llm", side_effect=AssertionError):
            questions, _ = flows._stage_review({"stages": [{"nodes": [node]}]}, 0, [{**pending, "_ni": 0, "_node": node}], "q", [], [])
        self.assertEqual(questions[0]["question"], "지식 관리 작업에 필요한 '고객사' 값을 알려주세요.")
        self.assertEqual(questions[0]["hint"], prompt[:120])

    async def test_groupware_query_carries_the_found_values(self):
        seen = {}

        def fake_gw(node, query, label):
            seen["query"] = query
            return {"label": label, "status": "done", "text": "ok"}
        node = {"agent": "groupware", "resources": ["mail.action.compose"], "instruction": "보고서 메일 발송",
                "extract_prompt": "받는 사람"}
        with patch.object(flows.llm, "generate", return_value={"values": {"받는 사람": "김철수\n(영업팀)"}}), \
                patch.object(flows, "_run_groupware_node", side_effect=fake_gw):
            result = await flows._run_step_node(node, "김철수에게 보내줘", [], None, [])
        self.assertEqual(result["status"], "done")
        self.assertIn("보고서 메일 발송\n[필수값] 받는 사람: 김철수 (영업팀)", seen["query"])   # 한 줄로 / one line


class ExtractResumeTests(DbCase):
    def make(self):
        chat = db.create_chat("워크플로우", "사내")
        node = {"agent": "knowledge", "resources": [], "instruction": "계약 조건", "extract_prompt": "고객사, 계약 연도"}
        flow = {"id": "fl_e", "name": "추출", "group": "og9", "description": "",
                "stages": [{"nodes": [node], "answer_prompt": ""}]}
        run = store.create(chat["id"], {"kind": "workflow", "flow": flow, "message": "A사 계약 조건", "actor": "", "eff": None,
                                        "results": {}, "cursor": 0, "stage_state": {}, "attempts": {}})
        return chat, flow, run

    async def test_workflow_run_asks_then_reruns_with_the_answer_and_no_llm(self):
        chat, flow, run = self.make()

        async def tokens(messages, system=None):
            yield "최종 답변"

        async def smooth(text):
            yield text
        agent = AsyncMock(return_value={"status": "answer", "text": "계약 조건 결과", "extras": {}})
        self.stack.enter_context(patch.object(flows, "_resolve_eff", return_value=None))
        self.stack.enter_context(patch.object(flows, "_build_context", return_value=[{"role": "user", "content": "q"}]))
        self.stack.enter_context(patch.object(flows, "_astream", tokens))
        self.stack.enter_context(patch.object(flows, "_smooth", smooth))
        self.stack.enter_context(patch.object(flows, "_flow_sources", return_value=None))
        self.stack.enter_context(patch.dict(AGENT_REGISTRY["knowledge"], {"run": agent}))

        with patch.object(flows.llm, "generate", return_value={"values": {"고객사": "A사", "계약 연도": None}}):
            events = [e async for e in artifact_execution.workflow_run(flow, chat, "A사 계약 조건", "", run)]
        card = next(e for e in events if e["type"] == "flow_question")["card"]
        self.assertEqual([(i["id"], i["required"], i["hint"]) for i in card["items"]], [("in_1_계약 연도", True, "고객사, 계약 연도")])
        agent.assert_not_awaited()
        run = store.get(run["id"])
        self.assertEqual(run["state"], "needs_input")

        # 답변 → 그 작업의 _provided_inputs(찾은 값 + 답), 도구 표지는 없다 / answer → _provided_inputs (found + answer), no tool
        self.assertFalse(artifact_execution.resume_workflow(run, {"kind": "flow_question", "answers": {"in_1_계약 연도": "2025"}}))
        saved = store.get(run["id"])
        node = saved["snapshot"]["flow"]["stages"][0]["nodes"][0]
        self.assertEqual(node["_provided_inputs"], {"고객사": "A사", "계약 연도": "2025"})
        self.assertFalse(node.get("_resolved_connector"))
        with patch.object(flows.llm, "generate", side_effect=AssertionError("재실행은 LLM 없이 / re-run without the LLM")):
            await self._drain(artifact_execution.workflow_run(saved["snapshot"]["flow"], chat, "A사 계약 조건", "", saved))
        self.assertEqual(store.get(run["id"])["state"], "completed")
        self.assertIn("[필수값] 고객사: A사; 계약 연도: 2025", agent.await_args.args[0])

    @staticmethod
    async def _drain(stream):
        return [e async for e in stream]


# ─────────────────────────────────────────────────────────────────────────────
# 등록 에이전트 도구 실행 / registered agent tools at run time
# ─────────────────────────────────────────────────────────────────────────────

class WorkAgentRuntimeTests(DbCase):
    def setUp(self):
        super().setUp()
        self.agent = work_agents.create(api_agent_body())
        self.key = f"wa:{self.agent['id']}:GetSalesSummary"
        self.action_key = f"wa:{self.agent['id']}:ApproveOrder"

    def test_tool_record_resolves_both_id_kinds(self):
        c = connectors.create({"name": "재고 API", "description": "재고", "api": {"url": "https://erp.example.invalid/x"}})
        self.assertEqual(flows._tool_record(c["id"])["name"], "재고 API")
        self.assertEqual(flows._tool_record(c["id"], {c["id"]: {"name": "색인"}})["name"], "색인")   # 목록이 오면 그 목록 / given listing wins
        rec = flows._tool_record(self.key)
        self.assertEqual((rec["id"], rec["name"], rec["source"], rec["kind"], rec["agent_id"], rec["method"], rec["enabled"]),
                         (self.key, "사내 ERP · GetSalesSummary", "work_agent", "read", self.agent["id"], "api", True))
        self.assertEqual((rec["api"]["tool_contract"]["version"], rec["api"]["tool_contract"]["retry_safe"]), (1, True))
        self.assertNotIn("output_schema", rec["api"]["tool_contract"])
        self.assertNotIn("wa-secret-1", json.dumps(rec, ensure_ascii=False))   # 비밀 없음 / no secret
        # 계약·입력 명세가 MCP 도구 커넥터와 같은 길로 동작 / contract and input specs work like MCP tool connectors
        self.assertEqual(flow_api_call.required_inputs(rec["api"]), ["branch", "period"])
        self.assertEqual([s["name"] for s in flow_api_call.input_specs(rec["api"])], ["branch", "period"])
        _, missing, _ = tool_contracts.prepare_workflow_inputs(rec, {"period": "2026-08"})
        self.assertEqual(missing, ["branch"])
        self.assertEqual(flows._tool_record(self.action_key)["api"]["tool_contract"]["retry_safe"], False)
        for bad in (f"wa:{self.agent['id']}:Nope", "wa:agent_missing:GetSalesSummary", "wa:bad", "cn_missing", "", None, "x"):
            with self.subTest(bad=bad):
                self.assertIsNone(flows._tool_record(bad))

    async def test_api_endpoint_call_is_assembled_from_the_stored_agent(self):
        seen = []

        def fake_call(cfg, ctx, keep_body=flow_api_call.BODY_KEEP):
            seen.append((cfg, ctx))
            return {"ok": True, "status": 200, "elapsed_ms": 4, "url": cfg["url"], "attempts": 1, "request": {},
                    "json": {"total": 9, "echo": "wa-secret-1"}, "result": {"total": 9}, "result_text": "합계 9 wa-secret-1",
                    "outputs": {}, "error": None, "body_text": "", "variables": {}}
        node = {"agent": "auto", "resources": [self.key], "instruction": "서울 매출 확인",
                "input_bindings": {"branch": {"mode": "value", "value": "SEL"}}}
        with patch.object(flow_api_call, "call", side_effect=fake_call), \
                patch.object(flows.llm, "generate", return_value={"inputs": {"period": "2026-08"}}):
            result = await flows._run_step_node(node, "8월 서울 매출", [], None, [], "")
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["label"], "사내 ERP · GetSalesSummary")
        self.assertEqual(result["extras"]["connector"]["source"], "work_agent")
        self.assertEqual(result["extras"]["connector"]["inputs"], {"branch": "SEL", "period": "2026-08"})
        self.assertEqual(result["note"], "서울 매출 확인")      # 작업 지침이 취합으로 / the instruction reaches the aggregation
        cfg, ctx = seen[0]
        self.assertEqual((cfg["method"], cfg["url"]), ("GET", "https://erp.example.invalid/api/sales/SEL"))
        self.assertEqual(cfg["auth"], {"type": "bearer", "key": "wa-secret-1", "in": "header", "name": "Authorization"})
        self.assertEqual(cfg["params"], [{"name": "period", "value": "{{input.period}}"}])
        self.assertEqual(ctx["vars"], {"input.period": "2026-08"})
        self.assertEqual((cfg["body"]["content_type"], cfg["response"]["retries"]), ("none", 0))
        self.assertNotIn("wa-secret-1", json.dumps(result, ensure_ascii=False))   # 되돌아온 키는 가린다 / echoed key redacted

    async def test_action_endpoint_keeps_body_types_and_the_effect_key_makes_it_idempotent(self):
        conn = flows._tool_record(self.action_key)
        calls = []

        def fake_call(cfg, ctx, keep_body=flow_api_call.BODY_KEEP):
            calls.append((cfg, ctx))
            return {"ok": True, "status": 200, "json": {"approved": True}, "result": {"approved": True},
                    "result_text": "승인", "outputs": {}}
        token = EFFECT_KEY.set("run_x:stage1_1")
        try:
            with patch.object(flow_api_call, "call", side_effect=fake_call):
                inputs, missing, _ = tool_contracts.prepare_workflow_inputs(conn, {"order_id": "O-1", "qty": "3", "note": "{{api_key}}"})
                self.assertEqual(missing, [])
                first = await call_connector(conn, "주문 승인", "", inputs)
                second = await call_connector(conn, "주문 승인", "", inputs)
        finally:
            EFFECT_KEY.reset(token)
        self.assertEqual(len(calls), 1)   # 같은 효과 키 → 두 번째는 저장된 결과 / same effect key → the stored result
        self.assertEqual(first["result_text"], second["result_text"])
        cfg, ctx = calls[0]
        self.assertEqual((cfg["method"], cfg["url"]), ("POST", "https://erp.example.invalid/api/orders/O-1/approve"))
        self.assertEqual(cfg["body"]["content_type"], "application/json")
        # 타입 보존 + 값 안의 변수는 다시 치환되지 않는다 / types kept; a variable inside a value is never substituted again
        self.assertEqual(flow_api_call.json_payload(cfg["body"]["payload"], {**ctx, "api_key": "wa-secret-1"}),
                         {"qty": 3, "note": "{{api_key}}"})

    def test_test_endpoint_sends_values_literally(self):
        cfg = work_agents.get_agent(self.agent["id"])["config"]
        client = MagicMock()
        client.__enter__.return_value = client
        client.request.return_value = httpx.Response(200, json={"ok": 1})
        with patch.object(flow_api_call, "check_url"), patch.object(flow_api_call.httpx, "Client", return_value=client):
            out = work_agents.test_endpoint(cfg, cfg["endpoints"][0], {"branch": "{{api_key}}", "period": "{{api_key}}"})
        self.assertTrue(out["ok"])
        self.assertEqual(set(out), {"ok", "status", "elapsed_ms", "url", "error", "request", "body_text", "json"})   # 응답 모양 그대로 / same shape
        self.assertEqual(client.request.call_args.kwargs["params"], [("period", "{{api_key}}")])
        self.assertTrue(client.request.call_args.args[1].endswith("/sales/%7B%7Bapi_key%7D%7D"))
        self.assertEqual(client.request.call_args.kwargs["headers"]["Authorization"], "Bearer wa-secret-1")

    async def test_permission_disabled_and_missing_tools_fail_closed_without_calling(self):
        node = {"agent": "auto", "resources": [self.key], "instruction": ""}
        call = AsyncMock()
        with patch.object(flows, "call_connector", call), patch.object(flows.llm, "generate", side_effect=AssertionError):
            denied = await flows._run_step_node(node, "q", [], {"nodes": {"agent_email": 1}}, [], "7")
            self.assertEqual((denied["status"], denied["label"]), ("failed", "업무 자동화"))
            self.assertEqual(denied["text"], "[사내 ERP · GetSalesSummary] 이 에이전트에 대한 권한이 없어 실행하지 않았습니다.")
            # eff 를 넘기지 않으면 행위자로 다시 계산한다(기본값이 슈퍼로 열리지 않는다) / no eff → recomputed from the actor
            with patch.object(flows, "_resolve_eff", return_value={"nodes": {}}) as resolve:
                again = await flows._run_api_node(node, "q", [], "7")
            resolve.assert_called_once_with("7")
            self.assertIn("권한이 없어", again["text"])
            allowed = {"nodes": {self.agent["id"]: 1}}
            gone = await flows._run_step_node({**node, "resources": [f"wa:{self.agent['id']}:Nope"]}, "q", [], allowed, [], "7")
            self.assertEqual(gone["status"], "failed")
            self.assertIn("찾지 못했습니다", gone["text"])
            work_agents.update(self.agent["id"], {**work_agents.editor_record(self.agent), "enabled": False})
            off = await flows._run_step_node(node, "q", [], allowed, [], "7")
            self.assertEqual(off["status"], "failed")
            self.assertIn("사용 중지", off["text"])
        call.assert_not_awaited()

    async def test_missing_input_asks_with_the_tool_docs_and_the_answer_reruns_the_same_tool(self):
        node = {"agent": "auto", "resources": [self.key], "instruction": ""}
        call = AsyncMock()
        with patch.object(flows, "call_connector", call), patch.object(flows.llm, "generate", return_value={"inputs": {}}):
            result = await flows._run_step_node(node, "매출", [], None, [], "")
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual((result["extras"]["missing_inputs"], result["extras"]["connector_id"]), (["branch"], self.key))
        call.assert_not_awaited()
        with patch.object(flows, "_review_llm", side_effect=AssertionError):
            questions, rerun = flows._stage_review({"stages": [{"nodes": [node]}]}, 0,
                                                   [{**result, "_ni": 0, "_node": node}], "q", [], [])
        self.assertEqual((questions[0]["id"], questions[0]["connector_id"], rerun), ("in_1_branch", self.key, ["stage1_1"]))
        self.assertTrue(questions[0]["question"].startswith("사내 ERP · GetSalesSummary 호출에 필요한 'branch' 값을 알려주세요."))
        self.assertEqual((questions[0]["hint"], questions[0]["placeholder"]), ("지점 코드", "SEL"))
        answered = {**node, "_resolved_connector": self.key, "_provided_inputs": {"branch": "SEL"}}
        ok = AsyncMock(return_value={"ok": True, "status": 200, "result_text": "ok", "outputs": {}})
        with patch.object(flows, "call_connector", ok), patch.object(flows.llm, "generate", side_effect=AssertionError):
            done = await flows._run_step_node(answered, "매출", [], None, [], "")
        self.assertEqual(done["status"], "done")
        self.assertEqual((ok.await_args.args[0]["id"], ok.await_args.args[3]), (self.key, {"branch": "SEL"}))

    def test_review_llm_never_reruns_an_action_agent_tool(self):
        nodes = [{"agent": "auto", "resources": [self.action_key]}, {"agent": "data", "resources": [], "instruction": "분석"}]
        finished = [{"_ni": 0, "_node": nodes[0], "status": "done", "text": "승인 완료", "label": "사내 ERP · ApproveOrder",
                     "extras": {"connector": {"id": self.action_key, "name": "사내 ERP · ApproveOrder", "kind": "action"}}},
                    {"_ni": 1, "_node": nodes[1], "status": "done", "text": "분석", "label": "데이터 분석"}]
        out = {"questions": [{"id": "q1", "label": "대상", "question": "어느 주문?", "kind": "text",
                              "task_ids": ["stage1_1", "stage1_2"]}]}
        with patch("app.llm.generate", return_value=out):
            questions = flows._review_llm(0, nodes, finished, "승인해줘", [], [])
        self.assertEqual(questions[0]["task_ids"], ["stage1_2"])

    def test_flow_summary_lists_registered_tool_inputs_like_external_tools(self):
        flow = {"id": "fl_s", "name": "요약", "stages": [{"nodes": [
            {"agent": "auto", "resources": [self.key], "instruction": "",
             "input_bindings": {"branch": {"mode": "value", "value": "SEL"}}},
            {"agent": "knowledge", "resources": [], "instruction": "", "extract_prompt": "고객사"}]}]}
        with patch.object(flows, "_flow_ai_summary", return_value="요약"):
            out = flows.flow_summary(flow)
        rows = [(r["connector_name"], r["name"], r["source"], r["value"], r["connector_source"]) for r in out["inputs"]]
        self.assertEqual(rows, [("사내 ERP · GetSalesSummary", "branch", "value", "SEL", "work_agent"),
                                ("사내 ERP · GetSalesSummary", "period", "auto", "", "work_agent")])   # 추출 게이트 값은 싣지 않음
        self.assertEqual(out["flow"][0]["labels"], ["업무 자동화", "지식 관리"])
        self.assertIn("사내 ERP · GetSalesSummary", out["resources"])

    def test_flow_summary_skips_input_rows_of_a_disabled_tool(self):
        # 리뷰 6: 사용 중지된 등록 도구는 입력값 행을 싣지 않는다(실행 때는 fail-closed 문구로 실패) / no rows for a disabled tool
        work_agents.update(self.agent["id"], {**work_agents.editor_record(self.agent), "enabled": False})
        flow = {"id": "fl_s", "name": "요약", "stages": [{"nodes": [
            {"agent": "auto", "resources": [self.key], "instruction": "",
             "input_bindings": {"branch": {"mode": "ask", "value": ""}}}]}]}
        with patch.object(flows, "_flow_ai_summary", return_value="요약"):
            out = flows.flow_summary(flow)
        self.assertEqual(out["inputs"], [])
        self.assertIn("사내 ERP · GetSalesSummary", out["resources"])   # 활용 리소스 표기는 남는다 / still listed as a resource

    def test_flow_stages_name_the_registered_tool(self):
        # 리뷰 4: 단계 트리·실행 카드 다음 작업 목록에 '<에이전트> · <도구>' 이름 / the stage tree names the tool
        other = work_agents.create(api_agent_body(name="삭제될 ERP"))
        gone_key = f"wa:{other['id']}:GetSalesSummary"
        work_agents.delete(other["id"])
        flow = {"stages": [{"nodes": [
            {"agent": "auto", "resources": [self.key], "instruction": "서울 지점 매출을 확인"},
            {"agent": "auto", "resources": [self.action_key], "instruction": ""},
            {"agent": "auto", "resources": [gone_key], "instruction": "x" * 40},
            {"agent": "auto", "resources": ["email.info.inbox"], "instruction": "확인 필요 메일"}]}]}
        self.assertEqual(flows._flow_stages(flow)[0]["tasks"], [
            "업무 자동화 · 사내 ERP · GetSalesSummary · 서울 지점 매출을 확인",
            "업무 자동화 · 사내 ERP · ApproveOrder",
            "업무 자동화 · GetSalesSummary · " + "x" * 30 + "…",   # 지워진 도구는 도구 이름만 / a deleted tool shows its name
            "업무 자동화 · 확인 필요 메일"])                          # 내장 항목은 종전 그대로 / built-ins unchanged

    def test_mcp_agent_tool_calls_tools_call_with_the_stored_url_and_auth(self):
        m = work_agents.create(mcp_agent_body())
        seen = {}

        def handle(request):
            body = json.loads(request.content)
            if body.get("id") is None:
                return httpx.Response(202)
            if body["method"] == "initialize":
                res = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "Fake", "version": "1"}}
            else:
                seen.update(auth=request.headers.get("authorization"), url=str(request.url), params=body["params"])
                res = {"content": [{"type": "text", "text": "가동 중 wa-secret-2"}], "structuredContent": {"status": "running"}}
            return httpx.Response(200, headers={"content-type": "application/json"},
                                  json={"jsonrpc": "2.0", "id": body["id"], "result": res})
        transport = httpx.MockTransport(handle)
        conn = flows._tool_record(f"wa:{m['id']}:ems_status")
        with patch.object(flow_api_call, "check_url"):
            r = work_agents.call(conn, {"equipment_id": "EQ-1", "blank": ""}, transport=transport)
        self.assertTrue(r["ok"])
        self.assertEqual((seen["auth"], seen["url"]), ("Bearer wa-secret-2", "https://mcp.example.invalid/mcp"))
        self.assertEqual(seen["params"], {"name": "ems_status", "arguments": {"equipment_id": "EQ-1"}})   # 빈 값은 보내지 않음
        self.assertEqual(r["outputs"], {"status": "running"})
        self.assertTrue(r["url"].endswith("#ems_status"))
        self.assertNotIn("wa-secret-2", json.dumps(r, ensure_ascii=False))
        # 사용 중지 도구·삭제된 에이전트는 호출 없이 실패 / disabled tool and deleted agent fail without a call
        hidden = work_agents.as_connector(work_agents.get_agent(m["id"]), "ems_hidden")
        self.assertFalse(hidden["enabled"])
        self.assertIn("사용 중지", work_agents.call(hidden, {}, transport=transport)["error"])
        work_agents.delete(m["id"])
        gone = work_agents.call(conn, {})
        self.assertIn("삭제", gone["error"])
        self.assertEqual(set(gone), set(work_agents._empty_result()))   # flow_api_call.call 과 같은 모양 / same shape


if __name__ == "__main__":
    unittest.main()
