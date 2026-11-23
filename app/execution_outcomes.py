"""실행기의 결과를 채팅·예약의 기존 표시 값으로 변환한다."""


def event(run):
    return {"type": "execution_result", "state": run["state"], "run_id": run["id"],
            "artifact": bool(run["snapshot"].get("artifact"))}


def chat_state(state):
    if state in ("ready", "running"):
        return "running"
    if state in ("failed", "blocked", "interrupted", "error"):
        return "error"
    if state in ("needs_input", "needs_confirmation"):
        return "needs_input"
    return "stopped" if state in ("cancelled", "stopped") else "done"


def schedule_result(state, artifact=False):
    ui = chat_state(state)
    return {"running": "interrupted", "error": "error:필수 작업이 완료되지 않았습니다", "needs_input": "needs_input",
            "stopped": "interrupted"}.get(ui, "doc" if artifact else "ok")
