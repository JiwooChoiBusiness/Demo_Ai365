"""실행 상태와 기존 답변 표현(status)을 분리하는 공통 결과 계약."""
SUCCESS = {"answer", "inference", "dashboard", "analysis", "done"}
TERMINAL = {"completed", "not_found", "failed", "blocked", "cancelled"}
WAITING = {"needs_input", "needs_confirmation"}


def state(result: dict) -> str:
    extras = result.get("extras") or {}
    if extras.get("action_draft"):
        return "needs_confirmation"
    if extras.get("await_recipient") or extras.get("missing_inputs"):
        return "needs_input"
    if result.get("state") in TERMINAL | WAITING:
        return result["state"]
    status = result.get("status")
    return "completed" if status in SUCCESS else status if status in TERMINAL | WAITING else "failed"


def normalize(result: dict) -> dict:
    return {**result, "state": state(result)}


def usable(result: dict) -> bool:
    return state(result) == "completed"


def failure(reason: str, *, blocked: bool = False) -> dict:
    status = "blocked" if blocked else "failed"
    return {"status": status, "state": status, "text": "", "extras": {"blocked": blocked},
            "fail_reason": reason, "alternative": "실패 원인과 입력을 확인한 뒤 다시 요청해 주세요."}
