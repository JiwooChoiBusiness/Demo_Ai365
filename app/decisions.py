"""의도판단 v3: 새 계획은 하나의 형식, 구형 응답은 경계에서만 변환한다."""
import copy
from app.planning import normalize_plan
from app.execution import PlanError

SYSTEM = """너는 사내 AI 작업 계획기다. 한국어 지침에 따라 아래 JSON 객체만 반환한다.
{"version":3,"query":"사용자가 이루려는 전체 목적","steps":[],"send_query":"",
 "clarify":null,"document":null,"use_previous":false,"web":false}
steps의 각 작업은 {"id":"s1","agent":"knowledge|data|work|groupware|connector",
 "task":"이 작업만의 질의","depends_on":[],"inputs":{}} 형식이다.
모든 작업에 id, depends_on, inputs를 반드시 명시한다. route/parallel/deliver/plan 필드는 쓰지 않는다.
- 독립 조회들은 depends_on=[]로 병렬이다. 이전 결과로 처리하는 작업만 그 id에 의존한다.
  명시된 실행 순서도 보존한다. A와 B 조회 후 C는 A=[], B=[], C=[A,B]다.
- 같은 에이전트도 서로 다른 작업은 별도 id다. 전체 사용자 요청을 매 task에 반복하지 않는다.
- 지식=RAG, 데이터=Text2SQL. M코스메틱 고객 메일 업무(확인 필요 메일, 견적요청·주문등록·출하일정·재고문의·
  인보이스 메일 현황, 업무 Case, ERP 처리 오류, 메일별 ERP 조회·주문등록·답변 초안·발송·재처리)는 work(worker=email),
  교육 이수율·교육 자료 권리원장은 work(worker=edu). 개인 메일(내 받은편지함)·일정·할일 조회/실행은 groupware.
  work의 이메일과 교육은 별개 작업으로 나눈다. work 작업에는 반드시 "worker":"email" 또는 "worker":"edu" 필드를 넣는다.
- 사용자가 두 조회 결과를 기준으로 별도의 분석을 요청하면 분석 작업도 steps에 포함한다.
  최종 답변 취합으로 분석 작업을 대체하지 않는다. 예: 규정 조회와 이수율 조회는 병렬,
  두 결과로 미이수 현황 분석은 data 작업으로 만들고 두 조회 id를 depends_on에 모두 넣는다.
- 커넥터는 agent=connector와 실제 connector_id를 쓴다. 입력 타입/필수 필드는 제공된 명세를 따른다.
  이전 결과 참조: inputs={"sku":{"from":"s1","path":["extras","connector","outputs","sku"]}}.
  from은 depends_on에 포함해야 한다. 값이나 커넥터 id를 지어내지 않는다.
- 새 조회 결과를 보고서로 만들어 메일로 보내는 요청: steps에 조회 작업을 모두 보존하고
  send_query에 수신자와 발송 지시를 둔다. 취합·최종 발송을 별도 조회 작업으로 중복 생성하지 않는다.
- 받는 사람이 빠졌으면 누구에게 보낼지 실행 전에 clarify한다. 임의로 본인·팀장을 수신자로 정하지 않는다.
  부족한 정보가 여러 개면 한 카드로 묻는다. 이미 정한 steps와 발송 목적은 그대로 보존한다.
  clarify={"question":"...","options":["나에게","직접 지정"],"slots":[
    {"key":"recipient","target":"send_query"}]}.
  특정 작업 조건은 {"key":"period","target":"task","task_id":"s1"},
  API 필수 입력은 {"key":"sku","target":"input","task_id":"s1","input":"sku"}로 받는다.
  목적 자체가 모호해 작업을 정할 수 없을 때만 steps=[]와 target=query로 묻는다.
- 확인이 필요한 액션도 작업으로 계획한다. 실행 확인은 실행기가 처리한다. 확인 이후 후속 작업도
  정상적으로 depends_on으로 연결한다. 실제 쓰기 작업은 사용자가 요청한 것만 포함한다.
- 기존 답변을 그대로 보내거나 재작성해 보내면 use_previous=true, steps=[], send_query를 사용한다.
  같은 요청에서 새로 조회하는 자료를 '그 내용'이라 부른 경우에는 use_previous=false다.
- 파일 생성은 document={"format":"pptx|pdf|docx|xlsx|mp4|image","topic":"..."}로 표시한다.
  자료 조회가 필요하면 steps에 보존한다. 메일 발송도 함께 요청하면 send_query를 보존한다.
  단순 '보고서 형식으로 답변'은 파일 요청이 아니다. 파일 설정 카드는 실행기가 처리한다.
- 인사·잡담·자료 조회 없는 글쓰기는 steps=[]다. 외부 정보가 필요하면 web=true로 표시한다.
  내부 우선/외부 검색 정책은 서버가 결정한다. 대화의 이전 질문에 대한 짧은 답도 전체 목적에 연결한다.
"""


def validate(raw, *, connector_ids=None, allowed_agents=None):
    if not isinstance(raw, dict) or raw.get("version") != 3:
        raise PlanError("의도판단 version=3 객체가 필요합니다")
    if any(k in raw for k in ("route", "parallel", "deliver", "plan", "connectors", "docgen")):
        raise PlanError("v3에서는 steps/send_query/clarify/document만 사용합니다")
    out = copy.deepcopy(raw)
    for k in ("query", "send_query"):
        if not isinstance(out.get(k), str):
            raise PlanError(f"{k}는 문자열이어야 합니다")
    for k in ("use_previous", "web"):
        if not isinstance(out.get(k), bool):
            raise PlanError(f"{k}는 불리언이어야 합니다")
    steps = out.get("steps")
    if not isinstance(steps, list):
        raise PlanError("steps는 목록이어야 합니다")
    for step in steps:
        if not isinstance(step, dict) or any(k not in step for k in ("id", "depends_on", "inputs")):
            raise PlanError("새 작업은 id, depends_on, inputs를 명시해야 합니다")
        if step.get("agent") == "work" and step.get("worker") not in ("email", "edu"):
            raise PlanError("work 작업에는 worker=email 또는 worker=edu가 반드시 필요합니다")
    p = normalize_plan({"steps": steps, "send_query": out["send_query"]}, connector_ids=connector_ids,
                       allowed_agents=allowed_agents)
    out["steps"] = p["steps"] if p else []
    if out["use_previous"] and steps:
        raise PlanError("기존 답변 재사용과 새 조회 작업을 혼합하지 마세요")
    doc = out.get("document")
    if doc is not None and (not isinstance(doc, dict) or doc.get("format") not in
                            ("pptx", "pdf", "docx", "xlsx", "mp4", "image") or not isinstance(doc.get("topic"), str)):
        raise PlanError("document 형식 또는 주제가 올바르지 않습니다")
    ask = out.get("clarify")
    if ask is not None:
        if not isinstance(ask, dict) or not isinstance(ask.get("question"), str) or not ask["question"].strip() \
                or not isinstance(ask.get("options"), list) or not isinstance(ask.get("slots"), list) or not ask["slots"]:
            raise PlanError("clarify에는 question/options/slots가 필요합니다")
        seen, ids = set(), {s["id"] for s in out["steps"]}
        for slot in ask["slots"]:
            if not isinstance(slot, dict) or not isinstance(slot.get("key"), str) or not slot["key"] or slot["key"] in seen:
                raise PlanError("입력 슬롯 key는 고유해야 합니다")
            seen.add(slot["key"])
            target = slot.get("target")
            if target not in ("query", "send_query", "task", "input", "routing"):
                raise PlanError("입력 슬롯 target이 올바르지 않습니다")
            if target == "routing" and not out.get("planning_pending"):
                raise PlanError("대상 선택은 계획 작성 전 단계에서만 가능합니다")
            if target == "query" and steps:
                raise PlanError("작업이 정해진 계획은 작업별 입력 슬롯을 사용합니다")
            if target in ("task", "input") and slot.get("task_id") not in ids:
                raise PlanError("입력 슬롯의 작업을 찾을 수 없습니다")
            if target == "input" and (not isinstance(slot.get("input"), str) or not slot["input"]):
                raise PlanError("입력 슬롯의 필드명이 필요합니다")
    from app.request_planning import validate_attachment
    validate_attachment(out)
    return out


def from_legacy(raw, query):
    """저장된 구형 계획/내부 호출 호환. 모델에는 이 형식을 가르치지 않는다."""
    if raw.get("version") == 3:
        return raw
    from app.task_runner import legacy_steps
    p = normalize_plan(raw.get("plan"))
    steps = p["steps"] if p else legacy_steps(raw.get("route") or [], bool(raw.get("parallel")),
                                               raw.get("refined_query") or query,
                                               [{"id": cid} for cid in raw.get("connectors") or []], raw.get("connector_inputs"))
    ask = raw.get("clarify")
    for step in steps:
        if step["agent"] == "work" and "worker" not in step:
            step["worker"] = "edu" if any(word in step["task"] for word in ("교육", "권리", "이수")) else "email"
    if ask:
        ask = {**ask, "slots": [{"key": "request", "target": "query"}]}
    return {"version": 3, "query": raw.get("refined_query") or query, "steps": steps,
            "send_query": (p or raw.get("plan") or raw.get("deliver") or {}).get("send_query", ""),
            "clarify": ask, "document": raw.get("docgen"), "use_previous": False, "web": bool(raw.get("web"))}


def fill(decision, values):
    """계획 구조를 변경하지 않고 선언된 슬롯만 채운다."""
    out = copy.deepcopy(decision)
    slots = out["clarify"]["slots"]
    if not isinstance(values, dict) or set(values) != {s["key"] for s in slots}:
        raise PlanError("필수 입력을 모두 확인하지 못했습니다")
    for slot in slots:
        value = values[slot["key"]]
        if value is None or (isinstance(value, str) and not value.strip()):
            raise PlanError("빈 입력으로 실행을 재개할 수 없습니다")
        target = slot["target"]
        if target in ("query", "send_query"):
            out[target] += "\n[사용자 추가 입력] " + str(value)
        else:
            step = next(s for s in out["steps"] if s["id"] == slot["task_id"])
            if target == "input":
                step["inputs"][slot["input"]] = value
            else:
                step["task"] += "\n[사용자 추가 입력] " + str(value)
    out["clarify"] = None
    return out
