"""모든 채팅 실행의 서버 소유 수명. SSE 구독 종료는 실행을 취소하지 않는다."""
from fastapi import HTTPException
from app import db, runs


async def trace_events(producer):
    from contextlib import aclosing
    from app.chats_api import _trace_collect
    trace = {"thinking": [], "tasks": [], "parallel": False, "status": {}, "lines": []}
    async with aclosing(producer):
        async for event in producer:
            if event.get("type") == "segment_start":
                trace = {"thinking": [], "tasks": [], "parallel": False, "status": {}, "lines": []}
            _trace_collect(trace, event)
            if event.get("type") == "done" and event.get("message_id") and trace["tasks"]:
                # 질문/확인 후 재개한 답변도 새로고침 시 실행 트리를 복원한다.
                db.update_message_meta(event["message_id"], {"trace": trace})
            yield event


def start(chat_id, producer):
    from app.chats_api import _on_run_finish
    if runs.is_running(chat_id):
        raise HTTPException(status_code=409, detail="이미 실행 중인 작업이 있습니다")
    run = runs.start(chat_id, trace_events(producer), on_finish=_on_run_finish)
    db.set_run_state(chat_id, "running", unseen=0)
    return run


def response(chat_id, producer):
    from app.chats_api import _subscribe_response
    return _subscribe_response(start(chat_id, producer))
