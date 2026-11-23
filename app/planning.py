"""LLM/저장 계획을 실행 가능한 작업으로 변환한다. 잘못된 단계를 버리지 않는다."""
from __future__ import annotations

from app.execution import MAX_TASKS, PlanError, Task, validate_tasks

AGENTS = {"knowledge", "data", "work", "groupware", "connector"}

PLAN_SYSTEM = """
[작업 계획 계약 v2 — route/parallel 및 기존 plan 규칙보다 우선]
하나의 요청에 독립 작업이나 결과 의존 작업이 여러 개 있으면 반드시 plan으로 분해한다.
plan={"steps":[{"id":"s1","agent":"knowledge","task":"이 작업만의 구체적인 질의",
"depends_on":[],"inputs":{}}],"send_query":"발송 지시 또는 빈 문자열"}.
plan 사용 시 route=[], connectors=[], deliver=null. refined_query는 전체 요청의 목적을 보존한다.
- id는 고유하다. depends_on=[]인 작업은 병렬 실행된다. 선행 결과가 필요하면 해당 작업 id를 넣는다.
- 사용자에게 명시된 순서도 의존성으로 보존한다. 단순 나열('A도, B도')은 병렬이고,
  'A와 B를 각각 조회해서 그 결과로 C'는 A=[], B=[], C=[A,B]다.
- 같은 에이전트의 작업도 목적이 다르면 별개 id로 만들 수 있다. 각 task에는 그 작업만 맡긴다.
- agent는 knowledge/data/work/groupware/connector 중 하나. groupware 조회도 선행 단계에 가능하다.
- 업무자동화에서 이메일(M코스메틱 고객 메일 업무)과 교육이 함께 필요하면 work 작업을 각각 만들고
  worker="email" 또는 worker="edu"로 지정한다. 이메일/교육 내부를 다시 고르게 하지 않는다.
- 커넥터 작업은 agent="connector", connector_id="연결된 실제 id"를 지정한다.
  inputs에 API 입력을 넣는다. 이전 결과를 쓰려면 {"from":"s1","path":["extras","connector","outputs","sku"]}
  처럼 필드 경로로 참조한다. from은 depends_on에도 있어야 한다. 결과값을 추측해 입력하지 않는다.
- 커넥터와 내부 작업 사이에도 같은 depends_on 규칙을 사용한다. 무조건 병렬로 정하지 않는다.
- 새 콘텐츠를 메일로 보내려면 send_query에 받는 사람·채널을 넣고 콘텐츠 단계만 steps에 둔다.
  기존 답변을 그대로 보내는 요청은 기존 groupware 직접 경로를 유지한다.
- 실제 쓰기/승인 요청은 사용자에게 명시된 것만 계획한다. 실행 확인이 필요한 작업은 마지막에 둔다.
  확인 이후 또 다른 처리가 반드시 필요한 요청은 필요한 절차를 clarify로 확인한다.
- 파일 생성은 기존 docgen 설정 카드 계약을 유지한다. plan.steps에 임의 파일 생성 작업을 만들지 않는다.
- 단일 작업에는 기존 route/deliver도 허용한다. 연결되지 않은 커넥터·허용되지 않은 에이전트를 만들지 않는다.
예: '규정과 교육 이수율을 동시에 조회하고 그 규정 기준으로 사용 현황 분석해줘'
→ plan.steps=[{"id":"rule","agent":"knowledge","task":"교육 규정 조회","depends_on":[]},
{"id":"edu","agent":"work","worker":"edu","task":"교육 이수율 조회","depends_on":[]},
{"id":"analysis","agent":"data","task":"규정과 교육 이수율에 따른 사용 현황 분석","depends_on":["rule","edu"]}].
"""


def normalize_plan(raw: object, *, connector_ids: set[str] | None = None,
                   allowed_agents: set[str] | None = None) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise PlanError("plan은 객체여야 합니다")
    steps = raw.get("steps", [])
    send = raw.get("send_query", "")
    if not isinstance(steps, list) or not isinstance(send, str):
        raise PlanError("plan.steps는 목록, send_query는 문자열이어야 합니다")
    if len(steps) > MAX_TASKS:
        raise PlanError(f"작업은 최대 {MAX_TASKS}개까지입니다")
    if not steps:
        return None  # 기존 send_query-only → deliver 호환
    out, previous = [], []
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            raise PlanError(f"steps[{idx}]가 객체가 아닙니다")
        agent, query = step.get("agent"), step.get("task")
        if not isinstance(agent, str) or agent not in AGENTS:
            raise PlanError(f"steps[{idx}]의 agent가 지원되지 않습니다")
        if allowed_agents is not None and agent != "connector" and agent not in allowed_agents:
            raise PlanError(f"steps[{idx}]의 agent가 사용자의 선택 범위 밖입니다")
        if not isinstance(query, str) or not query.strip() or len(query) > 12000:
            raise PlanError(f"steps[{idx}]의 task가 비었거나 너무 깁니다")
        key = step.get("id", f"s{idx + 1}")
        if not isinstance(key, str) or not key.strip() or len(key) > 80:
            raise PlanError(f"steps[{idx}]의 id가 올바르지 않습니다")
        # v1: 의존성이 없으면 기존처럼 모든 앞 단계 결과를 순서대로 전달한다.
        deps = step.get("depends_on", list(previous))
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps):
            raise PlanError(f"{key}: depends_on은 작업 id 목록이어야 합니다")
        inputs = step.get("inputs", {})
        if not isinstance(inputs, dict) or any(not isinstance(k, str) for k in inputs):
            raise PlanError(f"{key}: inputs는 객체여야 합니다")
        item = {"id": key, "agent": agent, "task": query.strip(),
                "depends_on": list(dict.fromkeys(deps)), "inputs": inputs}
        if agent == "connector":
            cid = step.get("connector_id")
            if not isinstance(cid, str) or not cid or (connector_ids is not None and cid not in connector_ids):
                raise PlanError(f"{key}: 연결된 커넥터 id가 필요합니다")
            item["connector_id"] = cid
        if "worker" in step:
            if agent != "work" or step["worker"] not in ("email", "edu"):
                raise PlanError(f"{key}: 업무자동화 worker가 올바르지 않습니다")
            item["worker"] = step["worker"]
        out.append(item)
        previous.append(key)
    validate_tasks(to_tasks(out))
    return {"steps": out, "send_query": send.strip()}


def to_tasks(steps: list[dict]) -> list[Task]:
    return [Task(s["id"], s["agent"], s["task"], tuple(s.get("depends_on", [])),
                 inputs=s.get("inputs", {})) for s in steps]


def validate_intent(value: object, *, connector_ids: set[str], allowed_agents: set[str] | None = None) -> dict:
    if not isinstance(value, dict):
        raise PlanError("의도판단은 JSON 객체여야 합니다")
    out = dict(value)
    for key in ("route", "connectors"):
        items = out.get(key, [])
        if items is None:
            items = []
        if not isinstance(items, list) or any(not isinstance(i, str) for i in items):
            raise PlanError(f"{key}는 문자열 목록이어야 합니다")
        permitted = connector_ids if key == "connectors" else (allowed_agents if allowed_agents is not None else AGENTS - {"connector"})
        if any(i not in permitted for i in items):
            raise PlanError(f"{key}에 사용할 수 없는 실행 대상이 있습니다")
        out[key] = list(dict.fromkeys(items))
    for key in ("parallel", "web"):
        if key in out and not isinstance(out[key], bool):
            raise PlanError(f"{key}는 불리언이어야 합니다")
    if out.get("refined_query") is not None and not isinstance(out["refined_query"], str):
        raise PlanError("refined_query는 문자열이어야 합니다")
    for key in ("clarify", "deliver", "docgen", "connector_inputs"):
        if out.get(key) is not None and not isinstance(out[key], dict):
            raise PlanError(f"{key}는 객체여야 합니다")
    if out.get("deliver") is not None:
        send = out["deliver"].get("send_query")
        if not isinstance(send, str) or not send.strip():
            raise PlanError("deliver.send_query에 발송 지시가 필요합니다")
    if out.get("clarify") is not None:
        question = out["clarify"].get("question")
        options = out["clarify"].get("options")
        if not isinstance(question, str) or not question.strip() or not isinstance(options, list):
            raise PlanError("clarify에 질문과 선택지 목록이 필요합니다")
    if out.get("docgen") is not None:
        doc = out["docgen"]
        if doc.get("format") not in ("pptx", "pdf", "docx", "xlsx", "mp4", "image"):
            raise PlanError("docgen.format이 지원되지 않습니다")
        if not isinstance(doc.get("topic"), str):
            raise PlanError("docgen.topic은 문자열이어야 합니다")
    ci = out.get("connector_inputs") or {}
    if any(key not in connector_ids or not isinstance(value, dict) for key, value in ci.items()):
        raise PlanError("connector_inputs에 연결된 커넥터의 입력 객체가 필요합니다")
    normalized = normalize_plan(out.get("plan"), connector_ids=connector_ids, allowed_agents=allowed_agents)
    if normalized:
        # 계획 + 별도 route/connector의 혼합은 작업 누락을 초래하므로 모델에 보정을 요청한다.
        if out["route"] or out["connectors"] or out.get("deliver"):
            raise PlanError("plan이 있으면 route/connectors는 비우고 발송은 plan.send_query에 넣어 주세요")
        out["plan"] = normalized
    if out.get("docgen") and (out["route"] or out["connectors"] or normalized or out.get("deliver")):
        raise PlanError("파일 설정 카드와 실행 계획을 동시에 내보낼 수 없습니다")
    if out.get("clarify") and (out["route"] or out["connectors"] or normalized or out.get("deliver")):
        raise PlanError("되묻기와 실행 계획을 동시에 내보낼 수 없습니다")
    return out
