"""채팅 답변 실행 레지스트리(인메모리) — 연결과 실행의 분리(2026-09-04).

답변 생성 중 사용자가 다른 화면으로 나가거나 브라우저를 닫아도 **서버가 끝까지 실행**해 저장한다.
POST /api/chats/{id}/stream 은 파이프라인 소비를 백그라운드 asyncio.Task(프로듀서)로 띄우고,
응답 SSE 는 그 실행의 **구독자**일 뿐이다 — 구독 해제(클라이언트 끊김)는 실행을 중단하지 않고,
중단은 STOP 버튼의 명시적 요청(POST /stop → stop())으로만 일어난다.

- RUNS: chat_id → Run. 채팅당 동시 실행은 하나(이미 running 이면 AlreadyRunning).
- publish: 이벤트를 버퍼에 쌓고 모든 구독 큐에 넣는다. 늦게 붙는 구독자(attach)는 버퍼 재생 + 라이브.
- finish: 종료 상태 확정 → 구독자에게 종료 신호(_END) → 버퍼는 BUFFER_TTL 뒤 정리
  (그 뒤의 늦은 attach 는 404 — DB 메시지 복원으로 충분).
- 서버 기동 시 chats.run_state='running' 잔존 행은 'stopped' 로 리셋(reset_stale_runs).

1차 범위 = 채팅 스트림 경로만(워크플로우 /api/flows/run·문서 생성 /api/docgen/run 은 종전대로).
"""
# In-memory registry of chat-answer runs — decoupling the connection from the execution (2026-09-04).
#
# While an answer is being generated the user may navigate away or close the browser; the SERVER
# keeps running to the end and saves the result. POST /api/chats/{id}/stream launches the pipeline
# consumer as a background asyncio.Task (the producer) and the SSE response is merely a SUBSCRIBER —
# unsubscribing (client disconnect) never stops the run; only the explicit STOP button
# (POST /stop → stop()) does.
#
# - RUNS: chat_id → Run. One run per chat at a time (AlreadyRunning otherwise).
# - publish: append the event to the buffer and push it to every subscriber queue. A late subscriber
#   (attach) gets the buffer replayed, then live events.
# - finish: settle the final state → signal subscribers (_END) → drop the buffer after BUFFER_TTL
#   (a later attach gets 404 — the DB message restore is enough by then).
# - On boot, leftover chats.run_state='running' rows are reset to 'stopped' (reset_stale_runs).
#
# Round-1 scope = the chat stream path only (workflow /api/flows/run and docgen /api/docgen/run unchanged).

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable

from app import db

logger = logging.getLogger("ai365.runs")

# 완료 후 버퍼 보존 시간(초) — 이 안에 붙는 attach 는 재생을 받고, 그 뒤는 DB 복원으로 충분하다
# Buffer retention after completion (seconds) — attaches within it get a replay; afterwards the DB restore suffices.
BUFFER_TTL = 30.0

# 구독 큐 종료 신호 / end-of-stream sentinel for subscriber queues
_END = None

# 종료 상태 어휘(chats.run_state 와 동일) / terminal-state vocabulary (same as chats.run_state)
STATES = ("running", "done", "needs_input", "error", "stopped")


class AlreadyRunning(Exception):
    """같은 채팅에 이미 진행 중인 실행이 있다(핸들러는 409 로 매핑)."""
    # The chat already has a run in progress (handlers map it to 409).


@dataclass
class Run:
    chat_id: str
    task: asyncio.Task | None = None
    events: list[dict] = field(default_factory=list)   # 이벤트 버퍼(재생용) / event buffer (for replay)
    subs: set[asyncio.Queue] = field(default_factory=set)
    done: bool = False
    state: str = "running"
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    # 명시적 STOP 요청 후 마감 대기 중(리뷰 지적: 병렬 에이전트 finally 가 취소를 수 초 지연) — 이 동안은 '진행 중' 으로
    # 보지 않아 재질문이 409 로 막히지 않고, 새 실행이 같은 채팅에 등록될 수 있다(옛 실행은 superseded 로 조용히 마감).
    # Settling after an explicit STOP (review fix: the parallel-agent finally delays cancellation by seconds) — not
    # counted as running meanwhile, so a re-ask is not rejected with 409 and a new run may register on the chat
    # (the old run then settles as superseded).
    stopping: bool = False
    stopped_by_user: bool = False   # STOP 버튼 → 완료 아이콘 없이(unseen=0) 마감 / explicit STOP → no unseen badge
    explore: bool = False           # 탐색 미니채팅 실행 — 채팅 상태·attach 대상 아님 / explore mini-chat run — no chat state, no attach


RUNS: dict[str, Run] = {}

_RECANCEL_SEC = 1.0    # 취소 재발행 간격 / re-cancel interval
_RECANCEL_MAX = 8      # 최대 재발행 횟수 / max re-cancels


def get(chat_id: str) -> Run | None:
    return RUNS.get(chat_id)


def is_running(chat_id: str) -> bool:
    run = RUNS.get(chat_id)
    return bool(run and not run.done and not run.stopping)


def is_current(run: Run) -> bool:
    """이 Run 이 채팅의 현재 등록 실행인가(STOP 뒤 새 실행에 밀린 옛 실행은 False) / is this run the chat's current one"""
    return RUNS.get(run.chat_id) is run


def publish(run: Run, ev: dict) -> None:
    """이벤트를 버퍼에 쌓고 모든 구독 큐에 전달한다(동기 — 이벤트 루프 스레드에서만 호출)."""
    # Append the event to the buffer and hand it to every subscriber queue (sync — event-loop thread only).
    if run.done:
        return
    run.events.append(ev)
    for q in list(run.subs):
        q.put_nowait(ev)


def subscribe(chat_id: str) -> tuple[list[dict], asyncio.Queue] | None:
    """(재생할 버퍼 사본, 라이브 큐). 실행이 없으면 None.
    스냅숏과 구독 등록은 await 없이 한 호출에서 이뤄져 이벤트 유실·중복이 없다.
    이미 끝난 실행(TTL 안)은 재생 + 즉시 종료 신호."""
    # (buffer snapshot to replay, live queue); None when there is no run.
    # Snapshot and registration happen in one await-free call, so no event is lost or duplicated.
    # A finished run (within TTL) yields the replay plus an immediate end signal.
    run = RUNS.get(chat_id)
    if run is None:
        return None
    q: asyncio.Queue = asyncio.Queue()
    replay = list(run.events)
    if run.done:
        q.put_nowait(_END)
    else:
        run.subs.add(q)
    return replay, q


def unsubscribe(chat_id: str, q: asyncio.Queue) -> None:
    run = RUNS.get(chat_id)
    if run is not None:
        run.subs.discard(q)


async def drain(q: asyncio.Queue) -> AsyncIterator[dict]:
    """구독 큐를 종료 신호까지 소비한다 — SSE 응답 제너레이터용."""
    # Consume a subscriber queue until the end signal — for SSE response generators.
    while True:
        ev = await q.get()
        if ev is _END:
            return
        yield ev


def finish(run: Run, state: str) -> None:
    """실행 종료 확정: 상태 기록 → 구독자 종료 신호 → TTL 뒤 버퍼 정리 예약."""
    # Settle the run: record the state → signal subscribers → schedule buffer cleanup after TTL.
    if run.done:
        return
    run.done = True
    run.state = state
    run.finished_at = time.time()
    for q in list(run.subs):
        q.put_nowait(_END)
    run.subs.clear()
    try:
        loop = asyncio.get_running_loop()
        loop.call_later(BUFFER_TTL, _evict, run)
    except RuntimeError:  # 루프 밖(테스트 등)이면 즉시 정리 / outside a loop (tests) evict at once
        _evict(run)


def _evict(run: Run) -> None:
    # 같은 채팅에 새 실행이 이미 등록됐으면 그건 건드리지 않는다 / never evict a newer run for the same chat
    if RUNS.get(run.chat_id) is run:
        RUNS.pop(run.chat_id, None)
    run.events.clear()


def _recancel(run: Run, n: int) -> None:
    """취소 재발행 — 파이프라인의 `finally: await gathered` 같은 대기 지점이 첫 취소를 흡수해도 다음 await 에서 다시
    전파되게 한다(리뷰 지적). 태스크가 끝나면 멈춘다."""
    # Re-issue the cancel — waits like the pipeline's `finally: await gathered` may swallow the first one; the next
    # cancel propagates at the following await (review fix). Stops once the task is done.
    if run.task is None or run.task.done() or n >= _RECANCEL_MAX:
        return
    run.task.cancel()
    try:
        asyncio.get_running_loop().call_later(_RECANCEL_SEC, _recancel, run, n + 1)
    except RuntimeError:
        pass


def stop(chat_id: str, by_user: bool = True) -> Run | None:
    """명시적 중단(STOP 버튼) — 프로듀서 태스크를 취소하고 즉시 '진행 중' 에서 뺀다(stopping). 실행이 없으면 None.
    호출자는 반환된 run.task 를 잠시 기다려(settle) 응답할 수 있다."""
    # Explicit stop (STOP button) — cancel the producer task and drop it from 'running' at once (stopping).
    # None when nothing is running. Callers may briefly await run.task to settle before responding.
    run = RUNS.get(chat_id)
    if run is None or run.done or run.task is None or run.task.done():
        return None
    run.stopping = True
    run.stopped_by_user = by_user
    run.task.cancel()
    try:
        asyncio.get_running_loop().call_later(_RECANCEL_SEC, _recancel, run, 1)
    except RuntimeError:
        pass
    return run


async def settle(run: Run, timeout: float = 3.0) -> bool:
    """STOP 뒤 태스크 마감을 잠시 기다린다(응답 지연 상한). 끝났으면 True."""
    # Briefly wait for the task to settle after STOP (bounded). True when finished.
    if run.task is None:
        return True
    try:
        await asyncio.wait({run.task}, timeout=timeout)
    except Exception:  # noqa: BLE001
        return False
    return run.task.done()


def _derive_state(events: list[dict]) -> str:
    """정상 종료 상태: error 이벤트 → 'error', confirm/clarify/docgen(사용자 입력 필요) → 'needs_input', 그 외 'done'."""
    # Normal-exit state: an error event → 'error', confirm/clarify/docgen (needs the user) → 'needs_input', else 'done'.
    state = "done"
    for ev in events:
        t = ev.get("type")
        if t == "error":
            return "error"
        if t in ("confirm", "clarify", "docgen", "flow_question", "flow_gate"):
            state = "needs_input"
        if t == "execution_result":
            from app.execution_outcomes import chat_state
            state = chat_state(ev["state"])
    return "error" if state == "running" else state


def start(chat_id: str, producer: AsyncIterator[dict],
          on_finish: Callable[[Run], None] | None = None, explore: bool = False) -> Run:
    """프로듀서(이벤트 async 이터레이터)를 백그라운드 태스크로 띄우고 Run 을 등록한다.

    - 이벤트마다 publish. 정상 종료 → done/needs_input/error(이벤트로 판정), 취소 → stopped,
      프로듀서가 예외를 던지면 error 이벤트를 하나 발행하고 error.
    - on_finish(run) 은 종료 확정 직후(구독자 종료 신호 뒤) 호출 — DB 상태 기록용. 예외는 삼킨다.
    - 이미 진행 중이면 AlreadyRunning."""
    # Launch the producer (async iterator of events) as a background task and register the Run.
    # - Every event is published. Normal exit → done/needs_input/error (judged from events),
    #   cancellation → stopped; a producer exception publishes one error event and ends as error.
    # - on_finish(run) runs right after settling (after subscribers are signalled) — for DB bookkeeping;
    #   its exceptions are swallowed.
    # - AlreadyRunning if a run is already in progress.
    if is_running(chat_id):
        raise AlreadyRunning(chat_id)
    run = Run(chat_id=chat_id, explore=explore)
    RUNS[chat_id] = run   # 끝난 옛 Run(TTL 대기)·STOP 마감 중인 옛 Run 은 덮어쓴다 / replaces a finished or stopping old run

    async def _drive() -> None:
        state = "done"
        try:
            async for ev in producer:
                publish(run, ev)
            state = _derive_state(run.events)
        except asyncio.CancelledError:
            state = "stopped"
            logger.info("실행 중단(명시적 stop) chat=%s", chat_id)
        except Exception as e:  # noqa: BLE001 — 프로듀서 예외는 이벤트로 / producer failures surface as an event
            logger.exception("실행 오류 chat=%s", chat_id)
            publish(run, {"type": "error", "detail": str(e)})
            state = "error"
        finally:
            finish(run, state)
            if on_finish is not None:
                try:
                    import inspect
                    result = on_finish(run)
                    if inspect.isawaitable(result):
                        await result
                except Exception:  # noqa: BLE001
                    logger.warning("실행 종료 후처리 실패 chat=%s", chat_id, exc_info=True)

    run.task = asyncio.create_task(_drive(), name=f"ai365-run-{chat_id}")
    return run


def reset_stale_runs() -> int:
    """서버 기동 시 호출 — 이전 프로세스가 남긴 chats.run_state='running' 행을 'stopped'(unseen=1) 로 리셋.
    인메모리 레지스트리도 비운다. 리셋된 행 수를 돌려준다."""
    # Called on boot — reset chats.run_state='running' rows left by a previous process to 'stopped'
    # (unseen=1) and clear the in-memory registry. Returns the number of rows reset.
    RUNS.clear()
    n = db.reset_running_chats()
    if n:
        logger.info("기동 시 진행 중 표시 리셋: %d건 → stopped", n)
    return n
