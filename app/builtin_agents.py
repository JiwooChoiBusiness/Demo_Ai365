"""기본 제공 업무 자동화 에이전트 설정(2026-10-06) — M코스메틱 이메일 에이전트 · 교육 에이전트를 리소스 관리에서 고친다.

사용자 지시 "기본 제공 에이전트도 수정 가능하게"(2026-10-06). 등록 에이전트(work_agents 표)와 달리 기본값은 코드 상수이고,
관리자가 고친 값만 work_agent_builtins 표에 덮어쓰기로 남는다(work_agents.builtin_override). [기본값으로 되돌리기] = 그 행 삭제.

  - 이름은 바꾸지 않는다: 접근 권한 축 · 워크플로우 팔레트 · 채팅 표시가 같은 이름을 쓴다.
  - M코스메틱 이메일 에이전트(MCP): 설명 · MCP 서버 주소 · 인증 · 타임아웃 · 도구(다시 가져오기, 사용 여부, 설명 덮어쓰기).
    도구 종류(조회/실행)는 서버 명세(readOnlyHint)를 그대로 쓴다 — 채팅이 확인 카드를 띄우는 기준은 따로 있어 바꿔도 효과가 없다.
    채팅 연결(app/mcmail_link.py)은 실행마다 email_connection() 을 읽어 주소 · 인증 · 타임아웃을 쓰고, 사용하지 않는 도구는 부르지 않는다.
    워크플로우 업무 자동화 노드와 이메일 에이전트 화면은 종전대로 in-process 라 연결 설정과 상관없다.
  - 교육 에이전트(앱 안 API): 설명만. 주소 · 엔드포인트는 앱 안 API 라 바꾸지 않는다.

Built-in work-automation agent settings (2026-10-06): the M Cosmetic Email Agent and the education agent become editable in
Resource Management (user request). Unlike registered agents the defaults are code constants; only the admin's edits are kept
as an overlay in work_agent_builtins, and [Reset to defaults] drops that row.
  - Names stay fixed: the permission axis, the workflow palette and the chat all show them.
  - Email agent (MCP): description, server URL, auth, timeout and tools (re-fetch, enabled, description override). The tool
    kind follows the server spec (readOnlyHint) because the chat decides on confirmation cards elsewhere. The chat link reads
    email_connection() on every run (URL, auth, timeout) and never calls a disabled tool; the workflow node and the email
    screen stay in-process and ignore the connection.
  - Education agent (in-app API): the description only.
"""

from __future__ import annotations

import copy

from app import mcp_servers, mock_mcosmetic, mock_mcosmetic_mcp, work_agents
from app.connectors import SECRET_MASK, ConnectorValidationError

IDS = work_agents.BUILTIN_IDS   # ("agent_email", "agent_edu")
EDU_DESCRIPTION = "교육 콘텐츠 수집 · 라이선스 검증 · 학습 현황 연동"


def _default(agent_id: str) -> dict:
    """기본값(비밀 포함, 서버 안에서만) / the defaults, secrets included (server side only)"""
    if agent_id == "agent_email":
        cfg = mock_mcosmetic_mcp.registry_config()
        cfg["auth"] = {"type": "bearer", "key": mock_mcosmetic.DEMO_KEY, "name": "Authorization"}
        cfg.setdefault("fetched_at", "")
        return {"method": "mcp", "description": mock_mcosmetic_mcp.DESCRIPTION, "config": cfg}
    return {"method": None, "description": EDU_DESCRIPTION, "config": None}


def effective(agent_id: str) -> dict:
    """기본값 + 고친 값 → {method, description, config, edited, updated_at}(비밀 포함) / defaults overlaid with the edits"""
    if agent_id not in IDS:
        raise KeyError(agent_id)
    out = copy.deepcopy(_default(agent_id))
    ov = work_agents.builtin_override(agent_id)
    if ov:
        d = ov["data"]
        if isinstance(d.get("description"), str):
            out["description"] = d["description"]
        if out["config"] is not None and isinstance(d.get("config"), dict):
            out["config"] = d["config"]
    out["edited"] = bool(ov)
    out["updated_at"] = (ov or {}).get("updated_at") or ""
    return out


def public(agent_id: str, label: str) -> dict:
    """업무 자동화 탭 목록 행(인증 키는 가린다) / the automation tab's row with the key masked"""
    e = effective(agent_id)
    row = {"id": agent_id, "label": label, "description": e["description"], "edited": e["edited"], "updated_at": e["updated_at"]}
    if e["config"] is not None:
        cfg = copy.deepcopy(e["config"])
        if (cfg.get("auth") or {}).get("key"):
            cfg["auth"]["key"] = SECRET_MASK
        row.update(method=e["method"], config=cfg)
    return row


def locked_kind(tool: dict) -> str:
    """기본 제공 에이전트의 도구 종류 = 서버 명세(readOnlyHint) / the tool kind of a built-in agent follows the server spec"""
    return "read" if (tool.get("annotations") or {}).get("readOnlyHint") else "action"


def save(agent_id: str, raw: dict) -> dict:
    """고친 값 검증 · 저장 → effective · 잘못된 값은 WorkAgentValidationError(422) / validate and store the edits"""
    if agent_id not in IDS:
        raise KeyError(agent_id)
    raw = raw if isinstance(raw, dict) else {}
    data: dict = {"description": work_agents._str(raw.get("description"), work_agents.MAX_DESC, "설명")}
    if agent_id == "agent_email":
        prev = effective(agent_id)["config"] or {}
        cfg = raw.get("config") if isinstance(raw.get("config"), dict) else {}
        try:
            tools = mcp_servers.normalize_tools(cfg.get("tools"))
        except ConnectorValidationError as e:
            raise work_agents.WorkAgentValidationError(str(e))
        if not tools:
            raise work_agents.WorkAgentValidationError("도구 목록이 비어 있습니다. [도구 다시 가져오기]로 받아 오세요")
        for t in tools:
            t["kind"] = locked_kind(t)
        info = cfg.get("server_info") if isinstance(cfg.get("server_info"), dict) else {}
        data["config"] = {"url": work_agents._url(cfg.get("url"), "MCP 서버 주소"),
                          "auth": work_agents._auth(cfg.get("auth"), work_agents.MCP_AUTH_TYPES, prev.get("auth")),
                          "timeout": work_agents._int(cfg.get("timeout"), 1, 120, mock_mcosmetic_mcp.TIMEOUT, "타임아웃"),
                          "tools": tools,
                          "server_info": {k: str(info[k])[:120] for k in ("name", "version", "protocol") if info.get(k) is not None},
                          "fetched_at": work_agents._str(cfg.get("fetched_at"), 40, "fetched_at")}
    work_agents.save_builtin_override(agent_id, data)
    return effective(agent_id)


def reset(agent_id: str) -> bool:
    if agent_id not in IDS:
        raise KeyError(agent_id)
    return work_agents.delete_builtin_override(agent_id)


def email_connection() -> dict:
    """채팅 연결용 M코스메틱 MCP 설정 — 주소 · 인증(실제 키) · 타임아웃 · 쓰지 않는 도구 이름
    The email agent's MCP settings for the chat link: URL, auth (real key), timeout and the disabled tool names"""
    cfg = effective("agent_email")["config"] or {}
    return {"url": cfg.get("url") or mock_mcosmetic_mcp.URL, "auth": dict(cfg.get("auth") or {}),
            "timeout": int(cfg.get("timeout") or mock_mcosmetic_mcp.TIMEOUT),
            "disabled": frozenset(t["name"] for t in cfg.get("tools") or [] if isinstance(t, dict) and t.get("enabled") is False)}
