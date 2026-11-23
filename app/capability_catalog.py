"""계획용 기능 카탈로그. 인증정보/URL은 노출하지 않고 실행 가능한 대상만 제공한다."""
from app.execution import PlanError

BUILTINS = [
    {"id": "agent:knowledge", "name": "사내 지식관리", "system": "AI365 지식관리", "domain": "규정·정책·문서",
     "kinds": ["retrieve"], "dispatch": {"agent": "knowledge"},
     "description": "RAG 근거 검색. 일반 외부 정보 요청도 자동 모드에서는 사내 검색 후 not_found일 때만 기존 웹 보완 사용. 운영 DB 수치나 고객 메일 처리는 담당하지 않는다."},
    {"id": "agent:data", "name": "사내 데이터 분석", "system": "AI365 데이터", "domain": "SQL·CSV·BI",
     "kinds": ["retrieve", "analyze"], "dispatch": {"agent": "data"},
     "description": "등록된 데이터 조회·집계와 선행 자료 분석. 특정 외부 ERP 연결과 동일하다고 추정하지 않는다."},
    {"id": "agent:groupware", "name": "개인 그룹웨어", "system": "M365 그룹웨어", "domain": "개인 메일·일정·할 일·보안",
     "kinds": ["retrieve", "action"], "dispatch": {"agent": "groupware"},
     "description": "내 메일함·일정·할 일과 테넌트 보안. 고객 메일 ERP 자동처리는 업무 이메일 에이전트 담당."},
    {"id": "agent:work:email", "name": "M코스메틱 이메일 업무", "system": "M코스메틱", "domain": "고객 메일·ERP 업무",
     "aliases": ["엠코스메틱", "M Cosmetic", "MCosmetic", "M코스메틱"],
     "kinds": ["retrieve", "action"], "dispatch": {"agent": "work", "worker": "email"},
     "description": "엠코스메틱 고객 메일별 견적·주문·출하·재고·인보이스·처리오류, 고객사·기간·상태별 조회 및 메일(E-ID)/Case 상세. "
                    "메일별 ERP 조회·답변 초안·주문등록·발송을 지원한다. 현황/완료내역 질문은 조회이며 실행으로 바꾸지 않는다. "
                    "일반 보고서를 내게 보내는 도구가 아니다."},
    {"id": "agent:work:edu", "name": "교육 업무", "system": "AI365 교육", "domain": "교육·이수율·권리원장",
     "kinds": ["retrieve"], "dispatch": {"agent": "work", "worker": "edu"},
     "description": "교육 이수·자료·권리 원장·라이선스 조회. 교육 승인/판정은 채팅 실행 미지원."},
    {"id": "delivery:groupware", "name": "보고서 메일 전달", "system": "M365 그룹웨어", "domain": "최종 답변·파일 전달",
     "kinds": ["delivery"], "dispatch": {"agent": "groupware"},
     "description": "완성된 보고서와 파일을 수신자에게 전달. 기존 수신자 질문·발송 확인 경로 사용."},
]


def build(connectors=None, allowed_agents=None, eff=None, scope_files=None):
    import copy
    from app.catalog import domain_readable, allowed_knowledge_files, allowed_tables, allowed_bi_files
    from app.tool_contracts import contract
    rows = []
    for item in BUILTINS:
        agent = item["dispatch"]["agent"]
        # Delivery is the existing post-answer service, not an additional selected retrieval agent.
        if item["kinds"] != ["delivery"] and allowed_agents is not None and agent not in allowed_agents:
            continue
        if agent in ("knowledge", "data") and not domain_readable(eff, "p_know" if agent == "knowledge" else "p_data"):
            continue
        if agent == "work" and isinstance(scope_files, dict) and "workers" in scope_files:
            workers = scope_files["workers"]
            if not isinstance(workers, list) or item["dispatch"]["worker"] not in workers:
                continue
        if agent == "work" and eff is not None and (eff.get("nodes", {}).get("agent_" + item["dispatch"]["worker"]) or 0) < 1:
            continue
        entry = copy.deepcopy(item)
        selected = {}
        fields = ({"knowledge_files": allowed_knowledge_files} if agent == "knowledge" else
                  {"data_tables": allowed_tables, "data_bi": allowed_bi_files} if agent == "data" else {})
        for key, access in fields.items():
            values = (scope_files or {}).get(key)
            if isinstance(values, list) and values:
                allowed = access(eff) if eff is not None else None
                selected[key] = [v for v in values if isinstance(v, str) and (allowed is None or v in allowed)]
        if selected:
            if not any(selected.values()):
                continue
            entry["selected_resources"] = selected
        rows.append(entry)
    for c in connectors or []:
        if c.get("enabled") is False:
            continue
        spec = contract(c)
        rows.append({"id": "connector:" + c["id"], "name": c.get("name") or c["id"],
                     "system": c.get("name") or c["id"], "domain": c.get("category") or "외부 시스템",
                     "description": c.get("description") or "", "kinds": ["action"] if c.get("kind") == "action" else ["retrieve"],
                     "dispatch": {"agent": "connector", "connector_id": c["id"]},
                     "input_schema": spec["input_schema"], "output_schema": spec.get("output_schema", {})})
    if len({r["id"] for r in rows}) != len(rows):
        raise PlanError("기능 카탈로그 id가 중복됩니다")
    return rows


def dispatch(target):
    for item in BUILTINS:
        if item["id"] == target:
            return item["dispatch"]
    if isinstance(target, str) and target.startswith("connector:") and target[10:]:
        return {"agent": "connector", "connector_id": target[10:]}
    raise PlanError("알 수 없는 실행 대상입니다")
