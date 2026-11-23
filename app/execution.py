"""공통 작업 실행기. UI 이벤트/LLM/DB와 독립적으로 의존성·취소·결과를 관리한다.

의존성은 단순 실행 순서(after)와 필수 결과(depends_on)를 구분한다.
확인 대기 결과는 완료된 업무 결과로 취급하지 않는다.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
from contextlib import aclosing
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from app.task_results import SUCCESS as SUCCESS_STATUSES, WAITING, failure, usable, state, normalize

logger = logging.getLogger("ai365.execution")
MAX_TASKS = 32


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class Task:
    id: str
    agent: str
    task: str
    depends_on: tuple[str, ...] = ()
    after: tuple[str, ...] = ()
    inputs: dict = field(default_factory=dict)


def validate_tasks(tasks: list[Task]) -> None:
    if len(tasks) > MAX_TASKS:
        raise PlanError(f"작업은 최대 {MAX_TASKS}개까지입니다")
    ids = [t.id for t in tasks]
    if any(not isinstance(i, str) or not i.strip() for i in ids) or len(set(ids)) != len(ids):
        raise PlanError("작업 id는 비어 있지 않고 서로 달라야 합니다")
    all_ids = set(ids)
    for t in tasks:
        deps = (*t.depends_on, *t.after)
        if t.id in deps or any(d not in all_ids for d in deps):
            raise PlanError(f"{t.id}: 존재하지 않거나 자기 자신인 선행 작업입니다")
        for value in t.inputs.values():
            if isinstance(value, dict) and "from" in value:
                if not isinstance(value["from"], str):
                    raise PlanError(f"{t.id}: 입력 참조 from은 작업 id 문자열입니다")
                if value["from"] not in t.depends_on:
                    raise PlanError(f"{t.id}: 입력 참조는 depends_on의 작업만 사용합니다")
                path = value.get("path", [])
                if not isinstance(path, list) or any(type(p) not in (str, int) for p in path):
                    raise PlanError(f"{t.id}: 입력 참조 path는 필드명/배열 번호 목록입니다")
    visited: set[str] = set()
    while len(visited) < len(tasks):
        ready = {t.id for t in tasks if t.id not in visited
                 and set((*t.depends_on, *t.after)) <= visited}
        if not ready:
            raise PlanError("작업 의존성에 순환이 있습니다")
        visited.update(ready)


def resolve_inputs(task: Task, results: dict[str, dict]) -> dict:
    resolved = {}
    for name, spec in task.inputs.items():
        if isinstance(spec, dict) and "from" in spec:
            try:
                value = results[spec["from"]]
                for part in spec.get("path", []):
                    if isinstance(value, list) and type(part) is int and part >= 0:
                        value = value[part]
                    elif isinstance(value, dict) and isinstance(part, str):
                        value = value[part]
                    else:
                        raise KeyError(part)
                if value is None:
                    raise KeyError(name)
            except (KeyError, IndexError, TypeError) as exc:
                raise PlanError(f"{task.id}: 입력 '{name}'의 선행 결과를 찾지 못했습니다") from exc
            resolved[name] = copy.deepcopy(value)
        else:
            resolved[name] = copy.deepcopy(spec)
    return resolved


def dependency_text(results: dict[str, dict], cap: int = 6000) -> str:
    """호출별로 필요한 선행 결과만 제공. 실행 지시와 외부 자료를 구분한다."""
    blocks = []
    for key, result in results.items():
        extras = result.get("extras") or {}
        data = {k: extras[k] for k in ("columns", "rows", "references", "extra_results") if k in extras}
        connector = extras.get("connector") or {}
        if connector.get("outputs"):
            data["outputs"] = connector["outputs"]
        text = result.get("text") or result.get("fail_reason") or ""
        if data:
            text += "\n" + json.dumps(data, ensure_ascii=False, default=str)
        blocks.append(f"[{key} · {result.get('label') or result.get('agent') or '작업 결과'}]\n{text[:cap]}")
    return "\n\n".join(blocks)


async def execute(tasks: list[Task], run: Callable[[Task, dict, dict], Awaitable[dict]],
                  *, concurrency: int = 4, completed: dict | None = None) -> AsyncIterator[dict]:
    """검증 후 실행. 소비자가 종료되면 실행 중인 코루틴을 취소하고 후속 작업을 시작하지 않는다.

    동기 외부 API를 to_thread로 호출한 경우 이미 시작된 HTTP 요청은 되돌릴 수 없다.
    실행기는 자동 재시도를 하지 않는다(실행형 Tool의 중복 처리를 피한다).
    """
    validate_tasks(tasks)
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    completed = {k: normalize(v) for k, v in (completed or {}).items() if k in {t.id for t in tasks}}
    pending = {t.id: t for t in tasks if t.id not in completed}
    running: dict[str, asyncio.Task] = {}

    async def invoke(task: Task) -> dict:
        try:
            deps = {d: copy.deepcopy(completed[d]) for d in task.depends_on}
            result = await run(task, deps, resolve_inputs(task, completed))
            if (not isinstance(result, dict)
                    or result.get("status") not in SUCCESS_STATUSES | {"not_found", "failed", "blocked", "cancelled"} | WAITING):
                raise PlanError("작업 실행 결과 형식이 올바르지 않습니다")
            return normalize(result)
        except asyncio.CancelledError:
            raise
        except PlanError as exc:
            return failure(str(exc))
        except Exception:
            logger.exception("작업 실행 실패(id=%s, agent=%s)", task.id, task.agent)
            return failure("작업 실행 중 오류가 발생했습니다")

    try:
        while pending or running:
            for key, task in list(pending.items()):
                if not set((*task.depends_on, *task.after)) <= completed.keys():
                    continue
                if any(state(completed[d]) in WAITING for d in (*task.depends_on, *task.after)):
                    continue  # 입력·확인 후 같은 계획을 재개한다. 실패로 바꾸지 않는다.
                bad = [d for d in task.depends_on if not usable(completed[d])]
                if bad:
                    del pending[key]
                    result = failure("필수 선행 작업이 완료되지 않아 실행하지 않았습니다: " + ", ".join(bad), blocked=True)
                    completed[key] = result
                    yield {"type": "finished", "task": task, "result": result}
                    continue
                if len(running) >= concurrency:
                    break
                del pending[key]
                # started를 소비한 이후에만 실제 호출을 생성한다.
                yield {"type": "started", "task": task}
                running[key] = asyncio.create_task(invoke(task), name=f"ai365-task-{key}")
            if not running:
                break
            done, _ = await asyncio.wait(running.values(), return_when=asyncio.FIRST_COMPLETED)
            # 같은 tick에 완료된 결과도 계획 순서대로 전달한다.
            for task in tasks:
                future = running.get(task.id)
                if future not in done:
                    continue
                del running[task.id]
                result = future.result()
                completed[task.id] = result
                yield {"type": "finished", "task": task, "result": result}
    finally:
        for future in running.values():
            future.cancel()
        if running:
            await asyncio.gather(*running.values(), return_exceptions=True)


async def stream_task(task: Task, produce: Callable[[], AsyncIterator[dict]]) -> AsyncIterator[dict]:
    """파일 생성처럼 자체 SSE를 내는 작업도 같은 취소/실행 수명으로 관리한다."""
    validate_tasks([task])
    queue: asyncio.Queue = asyncio.Queue(maxsize=32)

    async def invoke(spec, deps, inputs):
        async with aclosing(produce()) as source:
            async for event in source:
                await queue.put(event)
        return {"status": "answer"}

    async def drive():
        async with aclosing(execute([task], invoke)) as events:
            async for event in events:
                if event["type"] == "finished" and not usable(event["result"]):
                    await queue.put({"type": "error", "detail": event["result"]["fail_reason"]})
        await queue.put(None)

    future = asyncio.create_task(drive(), name=f"ai365-stream-{task.id}")
    reader = None
    try:
        while True:
            reader = asyncio.create_task(queue.get())
            await asyncio.wait((reader, future), return_when=asyncio.FIRST_COMPLETED)
            if not reader.done():
                # producer가 취소/예외로 끝나도 소비자가 영원히 큐를 기다리지 않는다.
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)
                await future
                return
            event = reader.result()
            if event is None:
                await future
                return
            yield event
    finally:
        if reader is not None:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        future.cancel()
        await asyncio.gather(future, return_exceptions=True)
