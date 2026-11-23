"""채팅 로컬 지식 호출(2026-09-30) — 관리 센터 › 로컬 설정에 등록한 고객 환경 지식 에이전트(MCP 도구 kb_chat)에 채팅 질문을
묻고, 결과를 답변 취합이 쓰는 모양으로 정리한다. 채팅 전용이다: 부르는 곳은 app/answers.py 의 로컬 지식 단계뿐이고,
워크플로우(app/flows.py)와 파일 생성 조사(app/docgen.py)는 부르지 않는다.

  - ask(agent, question, top_k) → {id, name, model, status, answer, sources, error}
      status = 'answer'(출처가 있는 답변) · 'not_found'(출처 없음) · 'failed'(연결 · 도구 오류). 타임아웃 = min(에이전트 MCP 타임아웃, 20초).
      error 는 knowledge_agents.call_tool 이 비밀을 가린 사유를 60자 안으로 줄인 것이다(화면 생각 줄에 그대로 실린다).
  - ask_many(pairs) → 같은 순서의 결과 목록. 스레드 최대 4개로 동시에 부르고, 한 답변의 호출은 최대 6건, 전체 대기 상한을 넘은 호출은
      실패('응답 시간 초과')로 돌려준다(남은 스레드는 자기 타임아웃에 끝난다).
  - TRANSPORT: 테스트 주입 지점(httpx 전송). 운영에서는 항상 None.

Chat local-knowledge calls (2026-09-30): asks the customer-environment knowledge agents registered in Admin Center › Local
settings (MCP tool kb_chat) the chat question and shapes the replies for answer aggregation. Chat only: app/answers.py's
local-knowledge stage is the sole caller; workflows (app/flows.py) and document research (app/docgen.py) never call it.
  - ask(agent, question, top_k) → {id, name, model, status, answer, sources, error}
      status = 'answer' (an answer with sources), 'not_found' (no sources) or 'failed' (connection or tool error). Timeout =
      min(the agent's MCP timeout, 20 s). error is the reason knowledge_agents.call_tool already redacted, cut to 60 chars
      (it is shown as is in the thinking lines).
  - ask_many(pairs) → results in the same order. Up to four threads call at once, at most six calls per answer, and calls
      still running at the overall deadline come back failed ('응답 시간 초과'); leftover threads end on their own timeouts.
  - TRANSPORT: test injection point (an httpx transport). Always None in production.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, wait

from app import knowledge_agents as ka

logger = logging.getLogger("ai365.local_knowledge")

# 전송 주입 지점(테스트 · 진단용 가짜 전송). 운영에서는 항상 None / transport injection point (tests, diagnostics); None in production
TRANSPORT = None

TOOL = "kb_chat"
TOP_K = 3                  # kb_chat 기본 문서 수(1~10) / kb_chat default document count (1-10)
MAX_WORKERS = 4            # 동시 호출 스레드 / concurrent call threads
MAX_CALLS = 6              # 답변 1개당 호출 상한 / calls per answer
CALL_TIMEOUT_MAX = 20      # 호출 1건 타임아웃 상한(초) / per-call timeout cap (seconds)
TOTAL_DEADLINE_SEC = 45    # ask_many 전체 대기 상한(초) / overall wait cap of ask_many (seconds)
MAX_QUESTION = 1000
MAX_ANSWER = 6000
MAX_SOURCES = 10
REASON_MAX = 60
TIMEOUT_REASON = "응답 시간 초과"

_CTRL_RX = re.compile(r"[\x00-\x1f\x7f]+")


def _text(v, cap: int) -> str:
    """표시용 한 줄 문자열(제어 문자 → 공백, 앞뒤 공백 제거, 상한) / a display one-liner (controls → space, trimmed, capped)"""
    if isinstance(v, bool) or not isinstance(v, (str, int, float)):
        return ""
    return _CTRL_RX.sub(" ", str(v)).strip()[:cap]


def _reason(v) -> str:
    """생각 줄에 붙일 짧은 사유(60자 이내, 화면 문구라 em dash 는 '-' 로) / a short reason for the thinking line (60 chars at
    most; it is shown on screen, so an em dash becomes '-')"""
    s = re.sub(r"\s+", " ", str(v or "")).replace("—", "-").strip()
    return s if len(s) <= REASON_MAX else s[: REASON_MAX - 1] + "…"


def _timeout(agent: dict) -> int:
    try:
        t = int((((agent.get("config") or {}).get("mcp") or {}).get("timeout")) or ka.TIMEOUT_DEFAULT)
    except (TypeError, ValueError):
        t = ka.TIMEOUT_DEFAULT
    return max(1, min(t, CALL_TIMEOUT_MAX))


def _top_k(v) -> int:
    try:
        return max(1, min(int(v), 10))
    except (TypeError, ValueError):
        return TOP_K


def _sources(raw) -> list[dict] | None:
    """kb_chat 의 sources → [{doc_id, title, page, snippet}] (최대 10건). 목록이 아니면 None(형식 오류).
    kb_chat sources → [{doc_id, title, page, snippet}] (10 at most); None when it is not a list (malformed)."""
    if not isinstance(raw, list):
        return None
    out: list[dict] = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        doc_id = _text(s.get("doc_id"), 200)
        title = _text(s.get("title"), 300) or doc_id
        if not title:
            continue
        page = s.get("page")
        page = page if isinstance(page, int) and not isinstance(page, bool) and page >= 1 else None
        out.append({"doc_id": doc_id, "title": title, "page": page, "snippet": _text(s.get("snippet"), 300)})
        if len(out) >= MAX_SOURCES:
            break
    return out


def _base(agent: dict) -> dict:
    aid = str((agent or {}).get("id") or "")
    return {"id": aid, "name": _text((agent or {}).get("name"), 80) or aid, "model": "", "status": "failed",
            "answer": "", "sources": [], "error": ""}


def ask(agent: dict, question: str, top_k: int = TOP_K) -> dict:
    """로컬 지식 에이전트 1개에 kb_chat 으로 질문 → {id, name, model, status, answer, sources, error}. 예외를 던지지 않는다.
    Ask one local knowledge agent through kb_chat → {id, name, model, status, answer, sources, error}. Never raises."""
    base = _base(agent)
    q = str(question or "").strip()[:MAX_QUESTION]
    if not q:
        return {**base, "error": "질문이 비어 있습니다"}
    try:
        res = ka.call_tool(agent, TOOL, {"question": q, "top_k": _top_k(top_k)}, timeout=_timeout(agent), transport=TRANSPORT)
    except Exception as e:  # noqa: BLE001 — call_tool 은 던지지 않지만 단계 전체를 지킨다 / call_tool never raises; guard the stage anyway
        logger.warning("로컬 지식 에이전트 호출 오류(%s): %s", base["id"], type(e).__name__)
        return {**base, "error": "호출 중 오류가 났습니다"}
    if not res.get("ok"):
        reason = _reason(res.get("error") or "도구가 오류를 돌려주었습니다")
        logger.info("로컬 지식 에이전트 호출 실패(%s): %s", base["id"], reason)
        return {**base, "error": reason}
    data = res.get("json") if isinstance(res.get("json"), dict) else None
    sources = _sources((data or {}).get("sources"))
    if data is None or sources is None:
        logger.info("로컬 지식 에이전트 응답 형식 오류(%s)", base["id"])
        return {**base, "error": "응답 형식이 올바르지 않습니다"}
    model = _text(data.get("model"), 60)
    answer = str(data.get("answer") or "").strip()[:MAX_ANSWER]
    if not sources or not answer:   # 출처 없는 답변은 쓰지 않는다(찾지 못함) / an answer without sources is not used (not found)
        return {**base, "model": model, "status": "not_found"}
    return {**base, "model": model, "status": "answer", "answer": answer, "sources": sources}


def ask_many(pairs: list[tuple[dict, str]]) -> list[dict]:
    """[(agent, question)] → 같은 순서의 ask() 결과(앞에서 MAX_CALLS 건까지). 스레드 최대 MAX_WORKERS 개로 동시에 부르고,
    TOTAL_DEADLINE_SEC 안에 끝나지 않은 호출은 실패(응답 시간 초과)로 채운다.
    [(agent, question)] → ask() results in the same order (the first MAX_CALLS pairs). Up to MAX_WORKERS threads call at
    once; calls not finished within TOTAL_DEADLINE_SEC are filled in as failed (timed out)."""
    todo = list(pairs or [])[:MAX_CALLS]
    if not todo:
        return []
    out: list[dict] = [{**_base(a), "error": TIMEOUT_REASON} for a, _q in todo]
    pool = ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(todo)), thread_name_prefix="ai365-local-kb")
    try:
        futures = {pool.submit(ask, agent, question): i for i, (agent, question) in enumerate(todo)}
        done, _pending = wait(futures, timeout=TOTAL_DEADLINE_SEC)
        for fut, i in futures.items():
            if fut not in done:
                logger.info("로컬 지식 에이전트 응답 시간 초과(%s)", out[i]["id"])
                continue
            try:
                out[i] = fut.result()
            except Exception as e:  # noqa: BLE001 — ask 는 던지지 않지만 한 건이 나머지를 막지 않게 / one failure never blocks the rest
                logger.warning("로컬 지식 에이전트 호출 오류(%s): %s", out[i]["id"], type(e).__name__)
                out[i] = {**out[i], "error": "호출 중 오류가 났습니다"}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return out
