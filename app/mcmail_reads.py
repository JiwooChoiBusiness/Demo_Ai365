"""엠코스메틱 조회 실행과 근거 보존. 전송 방식(MCP/페이지 내부 조회)은 호출자가 정한다."""
from __future__ import annotations

import copy


def _cell(value) -> str:
    return str(value or "-").replace("|", "\\|").replace("\n", " ").strip()


def mail_answer(detail: dict) -> str:
    """상세조회는 실제 메일의 식별자·상태·본문으로 답하며 어떤 액션도 수행하지 않는다."""
    email = detail.get("email") or {}
    if not email.get("emailId"):
        raise ValueError("메일 상세 응답을 확인하지 못했습니다. 메일 ID를 확인해 주세요.")
    rows = [("메일 ID", email["emailId"]), ("고객사", email.get("customer")),
            ("제목", email.get("subject")), ("수신일", email.get("receivedDate")),
            ("상태", email.get("status")), ("업무 Case", email.get("caseId")),
            ("다음 단계", (email.get("nextStep") or {}).get("title"))]
    text = "### 메일 상세\n| 항목 | 내용 |\n|---|---|\n" + "\n".join(
        f"| {key} | {_cell(value)} |" for key, value in rows)
    body = str(email.get("body") or email.get("summary") or "").strip()
    if body:
        # 메일 원문은 인용 자료다. 원문에 있는 요청을 현재 사용자의 실행 요청으로 취급하지 않는다.
        text += "\n\n메일 내용(참고 자료):\n" + "\n".join("> " + line for line in body[:6000].splitlines())
        if len(body) > 6000:
            text += "\n\n본문은 앞 6,000자만 표시했습니다."
    return text


def execute(queries: list[dict], call) -> tuple[str, list[dict]]:
    """검증된 조회 목록만 실행한다. 하나라도 실패하면 부분 조회를 전체 성공으로 반환하지 않는다."""
    parts, evidence = [], []
    for query in queries:
        target = query["target"]
        if target == "mail":
            detail = call("get_mail", {"email_id": query["email_id"]})
            email = detail.get("email") or {}
            answer = mail_answer(detail)
            got = {"answer": answer, "task": f"메일 {query['email_id']} 상세를 조회했습니다.",
                   "detail": "메일 원문과 현재 상태를 확인했습니다. 실행 작업은 수행하지 않았습니다.",
                   "data": {"target": "mail", "rows": [{key: email.get(key) for key in
                       ("emailId", "receivedDate", "customer", "subject", "status", "caseId")}]}}
        else:
            got = call("get_work_status", copy.deepcopy(query))
            answer = str(got.get("answer") or "").strip()
            if not answer:
                raise ValueError("조회 도구가 답변 근거를 반환하지 않았습니다. 조회 조건을 확인해 주세요.")
            data = got.get("data") or {}
            if data.get("candidates"):
                raise ValueError("고객사를 하나로 지정해 주세요: " + " / ".join(str(x) for x in data["candidates"][:8]))
        parts.append(answer)
        evidence.append({"target": target, "filters": copy.deepcopy(query.get("filters") or {}),
                         "task": got.get("task") or "", "detail": got.get("detail") or "",
                         "data": copy.deepcopy(got.get("data") or {})})
    return "\n\n".join(parts), evidence
