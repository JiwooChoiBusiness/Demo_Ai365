"""채팅·워크플로우에서 공통으로 사용하는 커넥터 실행 계약."""
import asyncio
import json
from contextvars import ContextVar

from app import flow_api_call
from app.execution import PlanError
from app.tool_contracts import prepare_inputs, check
from app import execution_store
EFFECT_KEY = ContextVar("connector_effect_key", default="")


async def call_connector(connector: dict, message: str, acting_user_id: str,
                          inputs: dict | None = None, prior: list[dict] | None = None,
                          effect_key: str = "", *, base_url: str = "", test_vars: dict | None = None,
                          keep_body: int = flow_api_call.BODY_KEEP) -> dict:
    import copy
    effect_key = effect_key or EFFECT_KEY.get()
    cfg = copy.deepcopy(connector.get("api") or {})
    inputs, missing, spec = prepare_inputs(connector, inputs)
    # 기존 조회 커넥터는 빈 필터로 전체 조회를 지원한다. 현재 등록 형식에는
    # 필수/선택 구분이 없으므로 실행형만 빈 입력을 차단한다.
    if missing:
        raise PlanError("커넥터 필수 입력이 없습니다: " + ", ".join(missing))
    if connector.get("kind") == "action" or not spec.get("retry_safe"):
        cfg.setdefault("response", {})["retries"] = 0
    if effect_key and connector.get("kind") == "action":
        fresh, previous = execution_store.effect_claim(effect_key)
        if not fresh:
            if previous["state"] == "completed":
                return json.loads(previous["result"])
            raise PlanError("이 실행의 외부 처리 결과가 불확실하여 자동 재호출하지 않습니다")
    if connector.get("source") == "work_agent":
        # 등록 업무 자동화 에이전트 도구(2026-09-26): 주소·인증은 저장된 에이전트에 있다. 위의 실행형 효과 키 처리를 그대로 거친 뒤
        # 엔드포인트(API) 또는 tools/call(MCP) 1회, 결과 모양은 API 호출과 동일
        # Registered work-agent tool (2026-09-26): the stored agent holds URL/auth. After the action effect-key handling above,
        # one endpoint call (API) or tools/call (MCP); same result shape as an API call
        from app import work_agents
        result = await asyncio.to_thread(work_agents.call, connector, inputs, keep_body=keep_body)
    elif cfg.get("mcp"):
        # MCP 도구 커넥터(2026-09-15): 서버 주소·인증은 서버 레코드에 있다 — tools/call 1회, 결과 모양은 API 호출과 동일
        # MCP tool connector (2026-09-15): the server record holds URL/auth — one tools/call, same result shape as an API call
        from app import mcp_servers
        result = await asyncio.to_thread(mcp_servers.call_tool, connector, inputs, keep_body=keep_body)
    else:
        values = {f"input.{k}": (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                  for k, v in inputs.items()}
        values = {**(test_vars or {}), **values}
        ctx = flow_api_call.build_ctx(message=message, prior=prior, acting_user_id=acting_user_id,
                                      api_key=(cfg.get("auth") or {}).get("key") or "", vars=values, base_url=base_url)
        if keep_body == flow_api_call.BODY_KEEP:
            result = await asyncio.to_thread(flow_api_call.call, cfg, ctx)
        else:
            result = await asyncio.to_thread(flow_api_call.call, cfg, ctx, keep_body=keep_body)
    if result.get("ok") and spec.get("output_schema"):
        check(result.get("json") if result.get("json") is not None else result.get("result"), spec["output_schema"], "출력")
    if effect_key and connector.get("kind") == "action":
        execution_store.effect_finish(effect_key, result)
    return result


async def run_connector(connector: dict, message: str, acting_user_id: str, inputs: dict, *, effect_key: str = "") -> dict:
    _, missing, _ = prepare_inputs(connector, inputs)
    if missing:
        return {"status": "needs_input", "text": "필수 입력을 알려주세요: " + ", ".join(missing),
                "extras": {"missing_inputs": missing}}
    result = await call_connector(connector, message, acting_user_id, inputs, effect_key=effect_key)
    cfg = connector.get("api") or {}
    keep = int((cfg.get("response") or {}).get("preview_chars") or 1200)
    ok = bool(result.get("ok"))
    extras = {"connector": {"id": connector["id"], "name": connector["name"],
                            "kind": connector.get("kind"), "status": result.get("status"),
                            "elapsed_ms": result.get("elapsed_ms"), "url": result.get("url"),
                            "outputs": result.get("outputs") or {}},
              "data": result.get("json") if result.get("json") is not None else result.get("result")}
    return {"status": "answer" if ok else "failed", "label": f"커넥터 · {connector['name']}",
            "text": (result.get("result_text") or "")[:keep] if ok else "", "extras": extras,
            "fail_reason": None if ok else f"커넥터 '{connector['name']}' 호출 실패",
            "alternative": None if ok else "관리 센터의 커넥터 테스트에서 호출을 확인해 주세요."}
