"""Gemini 클라이언트 — 다키 라운드로빈 + **키별** 모델 폴백 체인 + 생성/스트리밍/그라운딩/임베딩.

- tier='main'(최종 답변·취합) | 'lite'(의도판단·제목요약·Text2SQL 등 경량 작업)
- 키마다 자기 체인을 단계별로 강등(GEMINI_KEY_CHAIN_<슬롯> 오버라이드가 없으면 전역 체인 —
  현재 전 키 공통 3.7-flash → 3.5-flash → 3.5-flash-lite, 2026-10-30). 429는 (호출종류,모델,키) 쿨다운, 404(retired)는 조합 영구 스킵.
- 503 UNAVAILABLE 도 (호출종류,모델,키) 쿨다운(기본 60초, 연속이면 2배씩 최대 600초 — GEMINI_503_COOLDOWN_SEC/_MAX_SEC), 연결 오류·시간 초과는 다음 키/모델로 로테이션,
  요청마다 HTTP 타임아웃(기본 120초, GEMINI_HTTP_TIMEOUT_SEC) — 2026-09-14 배포 점검(보고가 도중에 조용히 멈추던 현상).
- 504 DEADLINE_EXCEEDED 도 503 처럼 넘긴다(2026-10-27 사용자 지시) — 단 504 는 모델 쪽 장애라 **그 모델을 모든 키에서** 쿨다운하고
  바로 다음 모델로 간다(키마다 약 2분씩 기다리지 않게). 쿨다운 시작 길이 = max(503 설정, 그 504 를 기다린 시간의 2배), 연속은 2배씩.
- 첫 응답 20초 제한(2026-10-30 사용자 지시, GEMINI_FIRST_RESPONSE_SEC, 0 이면 끔): 티어 체인에서 다음 모델이 남은 단계는 첫 응답(stream ·
  generate 는 첫 청크, 함수 호출 · 그라운딩은 호출 전체)을 감시 스레드로 재고, 넘으면 504 처럼 그 모델을 모든 키에서 쉬게 하고 바로 다음 모델로
  간다(체인 마지막 모델 · 명시 models(Agentic · 임베딩)는 제외). SDK 시간 제한은 X-Server-Timeout 으로 서버도 끊으므로 그대로 둔다.
  / First-response limit (user instruction 2026-10-30): on tier chains every stage with a next model gets GEMINI_FIRST_RESPONSE_SEC for its
  first response (the first chunk for stream and generate, the whole call for function calling and grounding), timed by a watcher thread;
  past it the model rests on every key like a 504 and the call moves straight to the next model. The last model, explicit `models`
  (Agentic, embeddings) are exempt, and the SDK timeout stays as is because it also cuts the request on the server (X-Server-Timeout).
- 로깅에는 키 인덱스 번호와 모델명만 남긴다. 키 값을 코드/로그/대화에 출력 금지.
"""
# Gemini client — 5-key round-robin + model fallback chain + generation/streaming/grounding/embedding.
#
# - tier='main' (final answer / aggregation) | 'lite' (intent detection, title summarization, Text2SQL, and other lightweight tasks)
# - When all keys for one model exceed the limit (429), automatically switch to the next model in the fallback chain using the same key pool.
# - Only key index numbers and model names are kept in logs. Do not output key values to code/logs/conversation.

import contextvars
import json
import logging
import re
import threading
import time
from collections.abc import Iterator
from typing import Any, Callable

import httpx
from google import genai
from google.genai import errors, types

from app import settings

logger = logging.getLogger("ai365.llm")

Message = dict[str, str]  # {"role": "user"|"assistant", "content": str}


class GroundingUnavailableError(Exception):
    """Google Search grounding 호출 불가(미지원/한도 초과). 호출부는 일반 generate로 폴백한다."""
    # Google Search grounding call unavailable (unsupported / limit exceeded). The caller falls back to regular generate.


class ModelBusyError(RuntimeError):
    """전 키·모델이 503 UNAVAILABLE(모델 혼잡)로 끝났을 때 — 원문 JSON 대신 사용자에게 보여줄 수 있는 한 줄 메시지.
    문자열에 '503'을 남겨 호출부의 문자열 판정(chats_api 안내문)이 그대로 동작한다."""
    # Every key/model ended in 503 UNAVAILABLE (model overloaded) — a one-line, user-facing message instead of the raw
    # JSON. The string keeps "503" so callers' substring checks (chats_api retry note) keep working.
    code = 503
    status = "UNAVAILABLE"

    def __init__(self, detail: str = ""):
        super().__init__("AI 모델이 혼잡해 응답하지 못했습니다(503 UNAVAILABLE). 잠시 후 다시 시도해 주세요."
                         + (f" [{detail}]" if detail else ""))


class ModelUnreachableError(RuntimeError):
    """전 키·모델이 네트워크 오류(연결 실패·상대 끊김·시간 초과)로 끝났을 때 — 원문 대신 사용자에게 보여줄 한 줄 메시지(2026-09-14 배포 점검).
    chats_api 의 재시도 안내는 '네트워크 오류' 문자열로 판정한다."""
    # Every key/model ended in a transport error (connect failure, peer close, timeout) — a one-line user-facing message
    # (2026-09-14 deployment review). chats_api's retry note matches on the "네트워크 오류" substring.

    def __init__(self, detail: str = ""):
        super().__init__("AI 모델 서버에 연결하지 못했습니다(네트워크 오류 또는 시간 초과). 잠시 후 다시 시도해 주세요."
                         + (f" [{detail}]" if detail else ""))


class FirstResponseTimeout(RuntimeError):
    """첫 응답(첫 토큰)이 GEMINI_FIRST_RESPONSE_SEC 안에 오지 않음(2026-10-30 사용자 지시). _with_rotation 안에서만 쓰고, 밖으로는
    ModelBusyError 로 바뀌어 나간다(호출부의 '503' 문자열 판정이 그대로 동작).
    No first response (first token) within GEMINI_FIRST_RESPONSE_SEC (user instruction 2026-10-30). Used inside _with_rotation only;
    it leaves as a ModelBusyError, so callers' '503' substring checks keep working."""

    def __init__(self, sec: float, model: str = ""):
        self.sec = float(sec)
        self.model = model
        super().__init__(f"모델 응답 {self.sec:g}초 없음")


def _is_unavailable(e: Exception) -> bool:
    return isinstance(e, errors.APIError) and (e.code == 503 or "UNAVAILABLE" in (e.status or "").upper())


def _is_deadline(e: Exception) -> bool:
    """504 DEADLINE_EXCEEDED — 모델이 서버 기한 안에 답하지 못함(2026-10-27: 3.8 · 3.7-flash 가 전 키에서 약 2분 뒤 504).
    503 처럼 넘기되, 모델 단위 장애라 그 모델을 모든 키에서 건너뛴다. / the model missed the server deadline; rotate like a 503,
    but skip that model on every key, since the failure belongs to the model"""
    return isinstance(e, errors.APIError) and (e.code == 504 or "DEADLINE_EXCEEDED" in (e.status or "").upper())


def _is_transport_error(e: Exception) -> bool:
    """네트워크 단 오류(연결 실패·상대가 연결 끊음·읽기/쓰기 오류·시간 초과) — 503 처럼 다음 키/모델로 로테이션(2026-09-14 배포 점검:
    첫 응답 전 ConnectError/RemoteProtocolError 가 그대로 작업 실패로 빠졌다). / transport-level failures rotate like a 503"""
    return isinstance(e, (httpx.TransportError, ConnectionError))


def _first_response_sec() -> float:
    """설정된 첫 응답 제한(초, 2026-10-30). 0 이하 · 잘못된 값이면 0(끔).
    The configured first-response limit in seconds; 0 (off) when it is 0, negative or invalid."""
    try:
        return max(0.0, float(getattr(settings, "GEMINI_FIRST_RESPONSE_SEC", 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _first_response_limit(stage: int, chain_len: int) -> float:
    """이 단계의 첫 응답 제한(초). 다음 모델이 남은 단계만 걸고, 체인 마지막 모델은 0(기다릴 다음 모델이 없다).
    This stage's limit: only stages that still have a next model; the chain's last model gets 0 (there is nothing to move to)."""
    return 0.0 if stage >= chain_len - 1 else _first_response_sec()


def _close_late(result: Any) -> None:
    """버려진 시도가 늦게 돌려준 스트림 반복자를 닫는다(HTTP 연결을 돌려주고 서버 쪽 생성도 멈추게).
    Close stream iterators that an abandoned attempt returned late (frees the HTTP connection and stops the generation)."""
    for item in (result if isinstance(result, tuple) else (result,)):
        if hasattr(item, "__next__") and callable(getattr(item, "close", None)):
            try:
                item.close()
            except Exception:  # noqa: BLE001 - 정리 실패는 무시 / a failed cleanup is ignored
                logger.debug("늦게 온 스트림 닫기 실패", exc_info=True)


def _call_with_first_response_limit(fn: Callable[[genai.Client, str], Any], client: genai.Client, model: str,
                                    limit: float) -> Any:
    """fn(client, model) 을 데몬 스레드에서 돌리고 첫 응답을 limit 초까지만 기다린다(2026-10-30 사용자 지시). 넘으면
    FirstResponseTimeout 을 내고 그 스레드는 버린다: 늦게 온 결과는 무시하고(스트림이면 닫는다) 늦게 난 오류도 무시한다. 그 스레드는
    GEMINI_HTTP_TIMEOUT_SEC(기본 120초) 안에 저절로 끝난다. SDK 시간 제한(HttpOptions.timeout)을 20초로 줄이지 않는 까닭: google-genai 는
    그 값을 X-Server-Timeout 헤더로 서버에도 보내 서버가 스트림까지 통째로 끊는다(긴 답이 잘린다).
    Run fn(client, model) on a daemon thread and wait at most `limit` seconds for the first response. Past it, raise
    FirstResponseTimeout and abandon the thread: a late result is dropped (a late stream is closed) and a late error ignored; the
    thread ends by itself within GEMINI_HTTP_TIMEOUT_SEC. The SDK timeout is not lowered to 20 s because google-genai also sends it to
    the server as X-Server-Timeout, and the server would then cut whole streams (long answers would be truncated)."""
    done = threading.Event()
    gate = threading.Lock()
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            out, err = fn(client, model), None
        except BaseException as e:  # noqa: BLE001 - 기다리는 쪽에서 다시 던진다 / re-raised on the waiting side
            out, err = None, e
        with gate:
            late = bool(box.get("abandoned"))
            if not late:
                box["out"], box["err"] = out, err
            done.set()
        if late and err is None:
            _close_late(out)

    # 컨텍스트 변수는 그대로 넘긴다(호출 스레드와 같은 값을 보게) / carry the caller's context variables over
    ctx = contextvars.copy_context()
    threading.Thread(target=ctx.run, args=(run,), name=f"gemini-first-response:{model}", daemon=True).start()
    if not done.wait(limit):
        with gate:
            if not done.is_set():   # 막 끝난 결과는 살린다 / a result that landed just now is kept
                box["abandoned"] = True
        if box.get("abandoned"):
            raise FirstResponseTimeout(limit, model)
    if box["err"] is not None:
        raise box["err"]
    return box["out"]


# 스트림 이어쓰기(2026-09-14, 사용자 제보 "키 다 돌기 전에 503이 뜬다"): 첫 청크만 로테이션 안에서 받았기 때문에 그 뒤
# 청크에서 난 503은 다음 키/모델을 시도하지 않고 답변을 끊었다. 이제 스트림 도중 오류는 다음 키/모델로 스트림을 다시 열어
# **이어쓰기**한다 — 이미 내보낸 본문을 모델 턴으로 붙이고 "반복 없이 이어 쓰라"고 지시하며, 겹치는 앞머리는 잘라 낸다.
# Stream continuation (2026-09-14, user report "503 shows before all keys were tried"): only the first chunk was
# received inside the rotation, so a 503 on a later chunk cut the answer without trying the next key/model. A
# mid-stream failure now reopens the stream on the next key/model as a **continuation** — the text already sent rides
# along as a model turn with a "continue, don't repeat" instruction, and an overlapping head is trimmed.
_STREAM_RESUME_MAX = 2          # 한 스트림당 이어쓰기 최대 횟수 / continuation attempts per stream
_RESUME_NOTE = ("[시스템] 위 답변 생성이 모델 오류로 중단되었습니다. 이미 쓴 내용을 반복하지 말고, 끊긴 지점부터 자연스럽게 "
                "이어서 답변을 끝까지 작성하세요. 인사말이나 설명 없이 본문만 이어 쓰세요.")
_RESUME_PROBE = 40              # 겹침 탐지용 꼬리 길이 / tail length used to detect a repeated head
_RESUME_OVERLAP_MAX = 120       # 접미·접두 겹침 최대 길이 / max suffix/prefix overlap
_RESUME_BUFFER = 200            # 겹침 판정 전 모아 두는 글자 수 / chars buffered before the overlap check


def _trim_overlap(sent: str, cont: str) -> str:
    """이어쓰기 앞머리가 이미 보낸 본문과 겹치면 잘라 낸다 — ① 꼬리(40자)가 앞머리 어딘가에 다시 나오면 그 뒤부터
    (처음부터 다시 쓴 경우 포함) ② 아니면 접미=접두 겹침(4~120자) 제거. 겹침이 없으면 그대로."""
    # Trim a continuation head that repeats what was already sent — (1) the 40-char tail reappears in the head
    # (covers a full restart) → resume after it; (2) otherwise drop a suffix==prefix overlap (4..120 chars).
    if not sent or not cont:
        return cont
    probe = sent[-_RESUME_PROBE:].strip()
    if len(probe) >= 12:
        idx = cont[:3000].find(probe)
        if idx >= 0:
            return cont[idx + len(probe):]
    head = cont.lstrip()
    for k in range(min(_RESUME_OVERLAP_MAX, len(sent)), 3, -1):   # 4자 이상 겹침만 / overlaps of 4+ chars only
        if head.startswith(sent[-k:]):
            return head[k:]
    return cont


def _resume_texts(texts: Iterator[str], sent: str) -> Iterator[str]:
    """이어쓰기 청크 — 앞머리 200자를 모아 겹침을 한 번 잘라 낸 뒤 나머지는 그대로 통과시킨다.
    Continuation chunks — buffer the first 200 chars, trim the overlap once, pass the rest through."""
    buf = ""
    trimmed = False
    for t in texts:
        if trimmed:
            yield t
            continue
        buf += t
        if len(buf) >= _RESUME_BUFFER:
            trimmed = True
            out = _trim_overlap(sent, buf)
            if out:
                yield out
    if not trimmed:
        out = _trim_overlap(sent, buf)
        if out:
            yield out


def _is_rotatable_error(e: errors.APIError) -> bool:
    """다음 키로 넘겨볼 가치가 있는 키 단위 오류인지 판단.

    429/RESOURCE_EXHAUSTED(한도)뿐 아니라 잘못된 키(400 API_KEY_INVALID)·인증 오류(401/403),
    일시적 과부하(503 UNAVAILABLE)도 다음 키/백오프 재시도로 해소될 수 있어 로테이션 대상으로 본다.
    """
    # Determine whether this is a per-key error worth retrying with the next key.
    #
    # Not only 429/RESOURCE_EXHAUSTED (limit) but also an invalid key (400 API_KEY_INVALID), auth errors (401/403),
    # and temporary overload (503 UNAVAILABLE) can be resolved by retrying with the next key/backoff, so they are treated as rotation targets.
    if e.code in (429, 401, 403, 503, 504):
        return True
    status = (e.status or "").upper()
    if any(s in status for s in ("RESOURCE_EXHAUSTED", "PERMISSION_DENIED", "UNAUTHENTICATED", "UNAVAILABLE",
                                 "DEADLINE_EXCEEDED")):
        return True
    if e.code == 400 and ("API key not valid" in str(e) or "API_KEY_INVALID" in str(e)):
        return True
    # 모델 미제공 404 — 신규 계정 키는 구세대 모델(2.5 계열)을 못 쓴다("no longer available to new users").
    # 키·모델 조합의 문제이므로 다음 키/모델로 로테이션한다(_with_rotation이 조합을 영구 스킵 목록에 기록).
    # Model-unavailable 404 — new-account keys cannot serve retired models ("no longer available to new
    # users"). It is a (key, model) combo problem, so rotate on (the combo is added to a permanent skip list).
    if e.code == 404 or "NOT_FOUND" in status:
        return True
    return False


def _tier_chain(chain: list[str], tier: str) -> list[str]:
    """한 키의 체인을 tier 1순위부터 시작하도록 정렬 — 1순위가 그 키 체인에 없으면(신규 계정 키의
    2.5 계열처럼) 체인을 설정된 순서 그대로 쓴다(키별 체인 오버라이드, 2026-08-28)."""
    # Order one key's chain to start from the tier's primary — when the primary isn't in that key's
    # chain (e.g. the 2.5 family on new-account keys), use the chain exactly as configured
    # (per-key chain override, 2026-08-28).
    primary = settings.GEN_MODEL_LITE if tier == "lite" else settings.GEN_MODEL_MAIN
    if primary in chain:
        return chain[chain.index(primary):]
    return list(chain)


def _to_contents(messages: list[Message] | str) -> list[types.Content]:
    """메시지 → Gemini Content 목록. 모양 세 가지(앞의 둘은 종전 그대로):
    - 문자열 하나 = user 글 하나, {"role": "user"|"assistant", "content": 글} = 글 파트 하나
    - 함수 호출(Agentic, 2026-10-19): {"role": "assistant", "content"?: 글, "calls": [{"name", "args", "id"?, "thought_signature"?}]}
      → role="model", parts = [글(있을 때만), function_call …]. thought_signature 는 받은 그대로 되돌린다(Gemini 3 계열은
      현재 턴의 함수 호출에 서명이 없으면 400 으로 거절한다)
    - 함수 응답: {"role": "tool", "results": [{"name", "response": dict, "id"?}]} → role="user"(SDK 자동 함수 호출과 같은 역할),
      parts = [function_response …] (호출 순서 그대로)
    Messages → Gemini contents in three shapes (the first two unchanged): plain text; a model turn of function calls
    (optional text first, each call keeping its thought_signature, which Gemini 3 requires for function calls of the
    current turn); and function responses as a user turn (the role the SDK's automatic function calling uses), in call order."""
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    contents = []
    for m in messages:
        if m.get("role") == "tool":
            parts = []
            for r in m.get("results") or []:
                resp = r.get("response")
                fr = types.FunctionResponse(name=r["name"], response=resp if isinstance(resp, dict) else {"output": resp},
                                            id=r.get("id") or None)
                parts.append(types.Part(function_response=fr))   # = Part.from_function_response + id
            contents.append(types.Content(role="user", parts=parts))
            continue
        if m.get("role") == "assistant" and m.get("calls"):
            parts = [types.Part.from_text(text=m["content"])] if m.get("content") else []
            for c in m["calls"]:
                fc = types.FunctionCall(name=c["name"], args=dict(c.get("args") or {}), id=c.get("id") or None)
                parts.append(types.Part(function_call=fc, thought_signature=c.get("thought_signature") or None))
            contents.append(types.Content(role="model", parts=parts))
            continue
        role = "model" if m["role"] == "assistant" else "user"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
    return contents


# 429 응답의 'Please retry in Ns' 파싱 — 쿨다운 기간 산정(모델·키 조합별)
# Parses 'Please retry in Ns' from a 429 response — determines the cooldown span (per model+key combo)
_RETRY_IN_RE = re.compile(r"retry in ([0-9.]+)s", re.IGNORECASE)
_COOLDOWN_DEFAULT_SEC = 30.0   # RetryInfo가 없을 때 기본 쿨다운 / default cooldown when no RetryInfo
_COOLDOWN_MAX_SEC = 3600.0     # 일당 쿼터 소진 등 과대값 상한 / cap for daily-quota style huge values


class GeminiClient:
    def __init__(self) -> None:
        self._pool = settings.load_key_pool()
        # HTTP 타임아웃(2026-09-14 배포 점검): SDK 기본은 None(무한) — 매달린 요청이 스트림·워크플로우를 영원히 멈추게 했다.
        # HTTP timeout (2026-09-14 deployment review): the SDK default is None (infinite) — a hung request stalled streams and workflows forever.
        http_options = (types.HttpOptions(timeout=int(settings.GEMINI_HTTP_TIMEOUT_SEC * 1000))
                        if settings.GEMINI_HTTP_TIMEOUT_SEC > 0 else None)
        self._clients = [genai.Client(api_key=key, http_options=http_options) for _, key in self._pool]
        # 키별 폴백 체인(GEMINI_KEY_CHAIN_<슬롯> 오버라이드) — 오버라이드가 없는 키는 전역 체인(settings.GEN_FALLBACK_CHAIN).
        # Per-key fallback chains (GEMINI_KEY_CHAIN_<slot> override) — keys without an override use the
        # global chain (settings.GEN_FALLBACK_CHAIN).
        self._chains = settings.load_key_chains(self._pool)
        self._lock = threading.Lock()
        self._cursor = 0
        # (호출종류, 모델, pool pos) → (쿨다운 해제 시각 monotonic, 사유 '429'|'503'). 429·503 시 기록해 무의미한 재시도를 건너뛴다.
        # (kind, model, pool pos) → (cooldown-until monotonic, reason '429'|'503'). Recorded on 429/503 so pointless retries are skipped.
        self._cooldown: dict[tuple[str, str, int], tuple[float, str]] = {}
        # 미제공 (model, pool pos) — 신규 계정 키의 구모델 404("retired for new users") 조합. 영구 스킵.
        # Unsupported (model, pool pos) — retired-model 404 combos on new-account keys. Skipped permanently.
        self._unsupported: set[tuple[str, int]] = set()

    def _next_start(self) -> int:
        """라운드로빈: 호출마다 시작 키를 순환시켜 부하를 분산한다."""
        # Round-robin: rotate the starting key on each call to distribute load.
        with self._lock:
            pos = self._cursor
            self._cursor = (self._cursor + 1) % len(self._pool)
        return pos

    def _cooling(self, kind: str, model: str, pos: int) -> bool:
        with self._lock:
            until = self._cooldown.get((kind, model, pos), (0.0, ""))[0]
            return time.monotonic() < until

    def _cooling_reasons(self, kind: str) -> set[str]:
        """이 호출 종류에서 지금 쿨다운 중인 조합들의 사유('429'·'503') / reasons of the combos currently cooling for this kind"""
        now = time.monotonic()
        with self._lock:
            return {reason for (k, _m, _p), (until, reason) in self._cooldown.items() if k == kind and now < until}

    def _set_cooldown(self, kind: str, model: str, pos: int, e: Exception, default_sec: float | None = None,
                      reason: str = "429") -> None:
        """429의 RetryInfo(‘retry in Ns’)를 읽어 쿨다운 기록. 없으면 기본 30초, 상한 1시간.

        키에 호출 종류(kind)를 포함한다 — grounding(웹 검색) 쿼터는 일반 생성과 별도라, grounded 429가
        일반 generate/stream까지 마비시키면 안 된다(적대 검증 반영)."""
        # Record the cooldown from the 429's RetryInfo ('retry in Ns'); default 30s, capped at 1h.
        # The key includes the call kind — the grounding (web-search) quota is separate from normal
        # generation, so a grounded 429 must not paralyze regular generate/stream (adversarial-verify finding).
        m = _RETRY_IN_RE.search(str(e))
        base = _COOLDOWN_DEFAULT_SEC if default_sec is None else float(default_sec)
        if reason == "503" and base > 0:
            # 연속 503 이면 2배씩(상한 GEMINI_503_COOLDOWN_MAX_SEC) — 죽은 조합 한 바퀴보다 짧은 쿨다운은 다음 호출이 또 전부 밟는다
            # Consecutive 503s double the span (capped) — a cooldown shorter than one walk of the dead combos gets re-walked
            strikes = self._strike(kind, model, pos, bump=True)
            base = min(base * (2 ** (strikes - 1)), settings.GEMINI_503_COOLDOWN_MAX_SEC)
        sec = min(float(m.group(1)) if m else base, _COOLDOWN_MAX_SEC)
        if sec <= 0:
            return   # 쿨다운 끔(GEMINI_503_COOLDOWN_SEC=0) / cooldown disabled
        with self._lock:
            self._cooldown[(kind, model, pos)] = (time.monotonic() + sec, reason)

    def _set_model_cooldown(self, kind: str, model: str, pos: int, e: Exception, waited: float = 0.0) -> None:
        """504(DEADLINE_EXCEEDED, 2026-10-27): 그 모델을 **모든 키에서** 쿨다운한다 — 모델 쪽 장애라 다른 키도 같은 시간(약 2분)을
        기다린 뒤 504 를 낸다. 시작 길이 = max(GEMINI_503_COOLDOWN_SEC, 이번 504 를 기다린 시간의 2배) — 504 는 확인에만 약 2분이 걸려
        60초 쿨다운은 그 호출이 끝나기도 전에 풀리고 다음 질문이 또 2분을 기다렸다(실측). 연속이면 2배씩 GEMINI_503_COOLDOWN_MAX_SEC
        까지, 연속 횟수는 모델 단위(pos -1)로 센다. / Cool the model on every key. The first span is max(GEMINI_503_COOLDOWN_SEC, twice the
        time this 504 took): a 504 takes about two minutes to surface, so a 60-second cooldown expired before the call even finished and
        the next question waited again (measured). Consecutive 504s double it up to GEMINI_503_COOLDOWN_MAX_SEC; the streak counts per model.

        첫 응답 지연(FirstResponseTimeout, 2026-10-30)도 같은 규칙으로 쉬게 한다. 사유는 '504' 로 기록해 _cooling_reasons 의 혼잡 판정에 걸리고,
        로그 문구만 사유(504 / 첫 응답 지연)를 나눠 적는다. / A first-response timeout (2026-10-30) rests the model by the same rule; the reason
        is recorded as '504' so the busy check of _cooling_reasons sees it, and only the log line names the cause (504 or first-response delay)."""
        base = float(settings.GEMINI_503_COOLDOWN_SEC)
        if base <= 0:
            return   # 쿨다운 끔 — 이번 호출 안에서만 다음 모델로 / cooldown disabled: only this call moves on
        base = max(base, 2.0 * max(0.0, float(waited or 0.0)))
        strikes = self._strike(kind, model, -1, bump=True)
        sec = min(base * (2 ** (strikes - 1)), settings.GEMINI_503_COOLDOWN_MAX_SEC, _COOLDOWN_MAX_SEC)
        until = time.monotonic() + sec
        with self._lock:
            for p in range(len(self._pool)):
                self._cooldown[(kind, model, p)] = (until, "504")
        key_no = self._pool[pos][0] if 0 <= pos < len(self._pool) else -1
        if isinstance(e, FirstResponseTimeout):
            logger.warning("모델 %s 첫 응답 지연(%g초 없음): 모든 키에서 %.0f초 건너뜀(키 #%d 에서 발생)", model, e.sec, sec, key_no)
        else:
            logger.warning("모델 %s 504(%s) — 모든 키에서 %.0f초 건너뜀(키 #%d 에서 발생)", model, getattr(e, "status", "") or "504", sec,
                           key_no)

    def _strike(self, kind: str, model: str, pos: int, bump: bool = False, clear: bool = False) -> int:
        """연속 503 횟수(조합별) — bump 로 +1, clear 로 초기화(성공 응답). 지연 초기화라 테스트 픽스처가 몰라도 된다.
        Consecutive-503 count per combo — bump adds one, clear resets it (successful response). Lazily created so fixtures need not know."""
        with self._lock:
            strikes = self.__dict__.setdefault("_strikes", {})
            key = (kind, model, pos)
            if clear:
                strikes.pop(key, None)
                return 0
            if bump:
                strikes[key] = strikes.get(key, 0) + 1
            return strikes.get(key, 0)

    def _with_rotation(self, fn: Callable[[genai.Client, str], Any], tier: str = "main",
                       kind: str = "gen", models: list[str] | None = None) -> Any:
        """키 라운드로빈 × **키별** 모델 폴백 체인 + 429 쿨다운 (2026-08-28 키별 체인 도입).

        단계(stage) 우선 순회: 각 키의 자기 체인 s번째 모델을 전 키에 시도하고, 실패하면 다음 단계로.
        키마다 체인이 달라도(구키=2.5 계열, 신규키=3.5/3.6 계열) 각자 자기 순서대로 강등된다.
        429가 났던 조합은 retry 힌트만큼, 404 조합은 영구 스킵. 시도할 조합이 없으면 즉시 실패.
        models가 오면(임베딩 등) 전 키 동일 체인으로 취급한다.
        첫 응답 제한(2026-10-30): 티어 체인 호출에서 다음 모델이 남은 단계는 fn 을 감시 스레드로 돌려 GEMINI_FIRST_RESPONSE_SEC 까지만
        기다리고, 넘으면 504 와 같이 그 모델을 모든 키에서 쉬게 하고 바로 다음 모델로 간다(models 명시 · 마지막 모델은 제한 없음).
        """
        # Key round-robin x PER-KEY model fallback chains + 429 cooldown (per-key chains, 2026-08-28).
        #
        # Stage-major traversal: try stage s of each key's own chain across all keys, then advance.
        # Keys with different chains (old = 2.5 family, new = 3.5/3.6 family) each degrade in their own
        # order. 429 combos are skipped for the retry hint, 404 combos forever. No tryable combo → fail
        # fast. An explicit `models` list (e.g. embeddings) is used uniformly for every key.
        # First-response limit (2026-10-30): on tier chains, a stage that still has a next model runs fn on a watcher thread and
        # waits at most GEMINI_FIRST_RESPONSE_SEC; past it the model rests on every key like a 504 and the call moves straight to
        # the next model (explicit `models` and the last model have no limit).
        n = len(self._pool)
        start = self._next_start()
        chains = ([list(models)] * n) if models else [_tier_chain(c, tier) for c in self._chains]
        stages = max(len(c) for c in chains)
        last_exc: Exception | None = None
        # 이번 호출에서 504 · 첫 응답 지연(2026-10-30)을 낸 모델: 나머지 키는 건너뛰고 다음 모델로(쿨다운을 꺼 둬도)
        # models that returned a 504 or missed the first-response limit (2026-10-30) in this call
        deadline_models: set[str] = set()
        for round_no in range(2):
            if round_no > 0:
                delay = settings.BACKOFF_BASE_SEC * (2 ** (round_no - 1))
                logger.warning("전 모델·키 소진 — %.1fs 백오프 후 재시도", delay)
                time.sleep(delay)
            tried = 0
            for stage in range(stages):
                for offset in range(n):
                    pos = (start + offset) % n
                    chain = chains[pos]
                    if stage >= len(chain):
                        continue
                    model = chain[stage]
                    key_idx = self._pool[pos][0]
                    if (model, pos) in self._unsupported:
                        continue  # 이 키가 못 쓰는 모델 — 영구 스킵 / model this key cannot serve — skip forever
                    if model in deadline_models:
                        continue  # 이번 호출에서 504 — 다음 모델로 / 504 in this call: on to the next model
                    if self._cooling(kind, model, pos):
                        continue  # 쿨다운 중 — 헛시도 생략 / cooling down — skip the pointless attempt
                    tried += 1
                    t_call = time.monotonic()   # 504 를 기다린 시간 → 그 모델의 쿨다운 길이 / time a 504 took sets the model's cooldown
                    # 첫 응답 제한(2026-10-30): 티어 체인에서 다음 모델이 남은 단계만, 명시 models · 마지막 모델은 0(제한 없음)
                    # First-response limit (2026-10-30): tier chains only, stages with a next model; explicit models and the last model get 0
                    limit = 0.0 if models else _first_response_limit(stage, len(chain))
                    try:
                        if limit > 0:
                            result = _call_with_first_response_limit(fn, self._clients[pos], model, limit)
                        else:
                            result = fn(self._clients[pos], model)
                        self._strike(kind, model, pos, clear=True)   # 성공 — 연속 503 초기화 / success resets the 503 streak
                        self._strike(kind, model, -1, clear=True)    # 모델 단위 504 연속도 초기화 / and the model-level 504 streak
                        if stage == 0:
                            logger.info("응답 모델: %s (키 #%d)", model, key_idx)
                        else:
                            logger.warning("폴백 모델로 응답: %s (키 #%d, %d단계)", model, key_idx, stage + 1)
                        return result
                    except FirstResponseTimeout as e:
                        # 504 와 같게(2026-10-30 사용자 지시 "20초 동안 없으면 다음 모델로"): 그 모델을 모든 키에서 쉬게 하고 바로 다음 모델로
                        # Like a 504 (user instruction 2026-10-30): rest this model on every key and move straight to the next model
                        self._set_model_cooldown(kind, model, pos, e, waited=time.monotonic() - t_call)
                        deadline_models.add(model)
                        logger.warning("모델 %s 키 #%d 첫 응답 %g초 없음: 다음 모델로 전환", model, key_idx, limit)
                        last_exc = e
                        continue
                    except errors.APIError as e:
                        if _is_rotatable_error(e):
                            if e.code == 429 or "RESOURCE_EXHAUSTED" in (e.status or "").upper():
                                self._set_cooldown(kind, model, pos, e)
                            elif e.code == 404 or "NOT_FOUND" in (e.status or "").upper():
                                with self._lock:
                                    self._unsupported.add((model, pos))
                            elif _is_unavailable(e):
                                # 503 쿨다운(2026-09-14 배포 점검): 혼잡한 조합을 잠시 건너뛴다 — 종전엔 호출마다 죽은 조합 18개를 다시 밟아
                                # 수십 초씩 조용했다. / 503 cooldown (2026-09-14 review): skip the overloaded combo for a while — every call
                                # used to re-walk all 18 dead combos and go silent for tens of seconds.
                                self._set_cooldown(kind, model, pos, e, default_sec=settings.GEMINI_503_COOLDOWN_SEC, reason="503")
                            elif _is_deadline(e):
                                # 504(2026-10-27 사용자 지시 "504도 503처럼 다음 모델로"): 이 모델을 모든 키에서 쿨다운하고 바로 다음 모델로
                                # 504 (user instruction 2026-10-27): cool this model on every key and move straight to the next model
                                self._set_model_cooldown(kind, model, pos, e, waited=time.monotonic() - t_call)
                                deadline_models.add(model)
                            logger.warning(
                                "모델 %s 키 #%d 오류(code=%s, status=%s) — 다음으로 전환",
                                model, key_idx, e.code, e.status,
                            )
                            last_exc = e
                            continue
                        raise
                    except (httpx.TransportError, ConnectionError) as e:
                        # 네트워크 단 오류(2026-09-14 배포 점검): 연결 실패·상대 끊김·시간 초과도 다음 키/모델로 — 종전엔 그대로 작업 실패
                        # Transport failures (2026-09-14 review): connect errors, peer closes and timeouts rotate too (they used to fail the task outright)
                        logger.warning("모델 %s 키 #%d 연결 오류(%s) — 다음으로 전환", model, key_idx, type(e).__name__)
                        last_exc = e
                        continue
            if tried == 0:
                # 전 조합이 쿨다운 — 백오프를 기다려도 소용없으므로 즉시 실패(호출부 폴백이 턴을 살린다). 503 쿨다운이면 혼잡 안내.
                # Every combo is cooling — waiting out the backoff is pointless; fail fast (caller fallbacks keep the turn alive).
                # Cooling because of 503s → the busy notice.
                busy = bool({"503", "504"} & self._cooling_reasons(kind))
                logger.warning("전 모델·키 쿨다운 중 — 즉시 실패(%s)", "모델 혼잡" if busy else "쿼터 소진")
                if last_exc is None and busy:
                    last_exc = ModelBusyError("전 키·모델 쿨다운 중")
                break
        if last_exc is None:
            last_exc = RuntimeError("모든 모델·키가 쿨다운 중입니다(쿼터 소진) — 잠시 후 다시 시도해 주세요.")
        if isinstance(last_exc, (ModelBusyError, ModelUnreachableError)):
            raise last_exc
        if _is_unavailable(last_exc):
            # 전부 503 — 원문 JSON 대신 한 줄 안내(화면·error 이벤트에 그대로 실린다) / all 503 — a one-line notice, not the raw JSON
            raise ModelBusyError() from last_exc
        if _is_deadline(last_exc):
            # 마지막이 504 — 같은 혼잡 안내(문자열의 '503' 판정을 쓰는 호출부가 그대로 동작) / last was a 504: the same busy notice
            raise ModelBusyError("504 DEADLINE_EXCEEDED") from last_exc
        if isinstance(last_exc, FirstResponseTimeout):
            # 마지막이 첫 응답 지연(뒤 모델이 전부 쉬는 중): 504 와 같은 혼잡 안내 / last was a first-response timeout: the same busy notice
            raise ModelBusyError(str(last_exc)) from last_exc
        if _is_transport_error(last_exc):
            # 전부 네트워크 오류 — 원문 대신 한 줄 안내 / all transport errors — a one-line notice instead of the raw message
            raise ModelUnreachableError(type(last_exc).__name__) from last_exc
        raise last_exc

    def generate(
        self,
        messages: list[Message] | str,
        system: str | None = None,
        json_mode: bool = False,
        tools: list | None = None,
        tier: str = "main",
    ) -> Any:
        """동기 1회 호출. json_mode=True면 JSON으로 받아 파싱한 객체를 반환.

        첫 응답 제한이 켜져 있고(GEMINI_FIRST_RESPONSE_SEC > 0) tools 가 없으면 내부는 스트림이다(2026-10-30): 첫 청크까지만 제한을 재고
        나머지는 다 모아 종전과 같은 값(글 · json.loads 결과)을 돌려준다. 제한이 꺼졌거나 tools 가 있으면 종전 비스트림 경로(그때 제한은
        호출 전체에 걸린다).
        """
        # Single synchronous call. If json_mode=True, receive as JSON and return the parsed object.
        # With the first-response limit on and no tools, the call streams internally (2026-10-30): only the first chunk is timed, the
        # rest is collected and the same value as before (text or the json.loads result) is returned. With the limit off or with tools,
        # the old non-stream path runs (the limit then covers the whole call).
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json" if json_mode else None,
            tools=tools,
        )
        contents = _to_contents(messages)

        if tools is None and _first_response_sec() > 0:
            text = self._generate_streamed(contents, config, tier)
        else:
            def call(client: genai.Client, model: str):
                return client.models.generate_content(model=model, contents=contents, config=config)

            resp = self._with_rotation(call, tier=tier)
            text = resp.text or ""
        if json_mode:
            return json.loads(text)
        return text

    def _generate_streamed(self, contents: list[types.Content], config: types.GenerateContentConfig, tier: str) -> str:
        """generate() 의 스트림 경로(2026-10-30 첫 응답 제한). 첫 청크까지만 로테이션(과 감시) 안에서 받고 나머지는 밖에서 모은다.
        모으는 도중 오류(503 · 504 · 전송 오류 · 읽기 시간 초과 등)는 stream() 처럼 그 조합을 쉬게 하고 **처음부터 다시** 받는다
        (이어쓰기가 아니다: JSON 이 깨지지 않게, 최대 _STREAM_RESUME_MAX 회). 그래도 실패하면 stream() 과 같은 규칙으로
        ModelBusyError(503 · 504) / ModelUnreachableError(전송 오류), 다음으로 넘길 수 없는 API 오류는 그대로 던진다.
        The stream path of generate() (2026-10-30 first-response limit): only the first chunk is received inside the rotation (and
        the watcher); the rest is collected outside it. An error while collecting (503, 504, transport error, read timeout) cools what
        served the stream like stream() does and restarts **from scratch** (no continuation, so JSON never breaks; at most
        _STREAM_RESUME_MAX times). Past that, the stream() rules apply: ModelBusyError for 503/504, ModelUnreachableError for transport
        errors, and a non-rotatable API error is raised as is."""
        def call(client: genai.Client, model: str):
            it = client.models.generate_content_stream(model=model, contents=contents, config=config)
            head = next(it, None)
            return head, it, model, next((i for i, c in enumerate(self._clients) if c is client), -1)

        restarts = 0
        while True:
            head, chunks, model, pos = self._with_rotation(call, tier=tier)
            parts = [head.text] if head is not None and head.text else []
            try:
                for chunk in chunks:
                    if chunk.text:
                        parts.append(chunk.text)
                return "".join(parts)
            except Exception as e:  # noqa: BLE001 - 모으는 도중 오류는 처음부터 다시 / errors while collecting restart the call
                if isinstance(e, errors.APIError) and not _is_rotatable_error(e):
                    raise
                self._cool_stream_source(model, pos, e)
                if restarts >= _STREAM_RESUME_MAX:
                    if _is_unavailable(e) or _is_deadline(e):
                        raise ModelBusyError(f"다시 받기 {restarts}회 실패") from e
                    if _is_transport_error(e):
                        raise ModelUnreachableError(f"다시 받기 {restarts}회 실패") from e
                    raise
                restarts += 1
                logger.warning("응답 모으기 중단(%s): 모델 %s, 처음부터 다시 %d/%d (받은 글 %d자는 버림)",
                               e.__class__.__name__, model, restarts, _STREAM_RESUME_MAX, sum(len(p) for p in parts))

    def _cool_stream_source(self, model: str | None, pos: int, e: Exception) -> None:
        """스트림 도중 오류 때 그 스트림을 주던 쪽을 쉬게 한다(stream() · generate() 공통): 503 은 그 (모델, 키) 조합, 504 는 그 모델을
        모든 키에서. 다른 오류는 쉬게 하지 않는다(다시 여는 호출은 라운드로빈으로 다음 키부터 간다).
        After a mid-stream error, cool what served the stream (shared by stream() and generate()): a 503 cools that (model, key) combo,
        a 504 the model on every key; other errors cool nothing (the reopening call starts at the next key of the round-robin)."""
        if not model or pos < 0:
            return
        if _is_unavailable(e):
            self._set_cooldown("gen", model, pos, e, default_sec=settings.GEMINI_503_COOLDOWN_SEC, reason="503")
        elif _is_deadline(e):
            self._set_model_cooldown("gen", model, pos, e)

    def generate_calls(
        self,
        messages: list[Message] | str,
        system: str | None = None,
        tools: list | None = None,
        tier: str = "main",
        models: list[str] | None = None,
    ) -> dict:
        """함수 호출(툴 콜링) 1회 — 모델이 고른 function_call 목록을 반환한다.

        tools는 함수 선언(JSON 스키마) dict 목록. 반환: {"calls": [{"name": str, "args": dict}, ...]}.
        키 라운드로빈·모델 폴백 체인은 generate와 동일하게 재사용한다(_with_rotation).
        function_call이 없으면(모델이 텍스트만 반환) calls=[] — 호출부가 결정적 폴백을 태운다.
        첫 응답 제한(2026-10-30)은 비스트림 그대로라 호출 전체에 걸린다(함수 호출 응답은 짧다). models 를 명시하면(Agentic) 제한이 없다.
        """
        # One function-calling (tool-calling) call — returns the function_calls the model chose.
        #
        # `tools` is a list of function-declaration (JSON-schema) dicts. Returns {"calls": [{"name", "args"}, ...]}.
        # Key round-robin / model fallback chain are reused exactly as in generate (_with_rotation).
        # If there is no function_call (the model returned text only), calls=[] — the caller runs a deterministic fallback.
        # The first-response limit (2026-10-30) stays non-streaming here, so it covers the whole call (function-call replies are
        # short); an explicit `models` chain (Agentic) has no limit.
        tool_objs = [types.Tool(function_declarations=tools)] if tools else None
        config = types.GenerateContentConfig(system_instruction=system, tools=tool_objs)
        contents = _to_contents(messages)

        def call(client: genai.Client, model: str):
            return client.models.generate_content(model=model, contents=contents, config=config)

        resp = self._with_rotation(call, tier=tier, models=models)   # models: 세션이 고른 모델 체인(Agentic) / the session's own chain
        # 호출은 첫 후보의 파트에서 모은다(2026-10-19): 함수 호출 파트의 thought_signature · id 를 함께 돌려줘야 호출부가 다음 라운드에
        # 그대로 되돌릴 수 있다(_to_contents 의 calls 모양). 파트가 없는 응답만 편의 접근자(function_calls)로 대신한다.
        # Calls come from the first candidate's parts (2026-10-19) so each call keeps its thought_signature and id for the
        # caller to send back next round (the `calls` shape of _to_contents); the function_calls accessor covers part-less responses.
        calls: list[dict] = []
        text = ""
        for cand in (getattr(resp, "candidates", None) or []):
            content = getattr(cand, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                fc = getattr(part, "function_call", None)
                if fc is not None and getattr(fc, "name", None):
                    entry = {"name": fc.name, "args": dict(getattr(fc, "args", None) or {})}
                    if getattr(fc, "id", None):
                        entry["id"] = fc.id
                    if getattr(part, "thought_signature", None):
                        entry["thought_signature"] = part.thought_signature
                    calls.append(entry)
            # 함께 온 글(2026-09-18, 리포트 에이전트 도구 루프의 마무리 답변): resp.text 는 함수 호출 파트가 섞이면 경고를 내므로 파트에서 직접 모은다
            # Text that came along (2026-09-18, the closing reply of the report agent's tool loop): resp.text warns when
            # function-call parts are mixed in, so the text parts are collected directly
            text = "".join(getattr(p, "text", None) or "" for p in parts if not getattr(p, "thought", False))
            break
        if not calls:
            for fc in (getattr(resp, "function_calls", None) or []):
                if getattr(fc, "name", None):
                    calls.append({"name": fc.name, "args": dict(getattr(fc, "args", None) or {})})
        return {"calls": calls, "text": text.strip()}

    def stream(self, messages: list[Message] | str, system: str | None = None,
               tier: str = "main") -> Iterator[str]:
        """토큰 제너레이터(yield str). SSE 연계용.

        첫 청크를 로테이션 구간 안에서 받아 키/모델 오류 시 다음으로 재시도한다. 그 뒤 청크에서 난 오류(503 등)는
        다음 키/모델로 스트림을 다시 열어 이어쓰기한다(최대 _STREAM_RESUME_MAX회; 본문이 없었으면 처음부터 다시).
        첫 응답 제한(2026-10-30)도 그래서 첫 청크까지만 잰다. 그 뒤 청크는 종전대로 제한 없이 받는다.
        """
        # Token generator (yield str). For SSE integration.
        #
        # The first chunk is received inside the rotation block so a key/model error retries with the next one. An
        # error on a later chunk (503 etc.) reopens the stream on the next key/model as a continuation (at most
        # _STREAM_RESUME_MAX times; a restart from scratch when nothing was sent yet).
        # The first-response limit (2026-10-30) therefore times only the first chunk; later chunks run as before, with no limit.
        config = types.GenerateContentConfig(system_instruction=system)
        base = _to_contents(messages)

        used: dict = {}   # 지금 스트림을 주는 (모델, 키 위치) — 스트림 도중 503 이면 그 조합을 쿨다운(2026-09-14) / the combo serving this stream

        def opener(contents: list[types.Content]):
            def call(client: genai.Client, model: str):
                it = client.models.generate_content_stream(model=model, contents=contents, config=config)
                head = next(it, None)
                return head, it, model, next((i for i, c in enumerate(self._clients) if c is client), -1)
            return call

        def open_stream(contents: list[types.Content]):
            # (모델, 키 위치)는 받아들인 시도에서만 적는다: 첫 응답 제한으로 버려진 시도가 늦게 끝나 덮어쓰지 않게(2026-10-30)
            # Record (model, key position) from the accepted attempt only, so an attempt abandoned by the first-response limit
            # cannot overwrite it when it finishes late (2026-10-30)
            head, chunks, used["model"], used["pos"] = self._with_rotation(opener(contents), tier=tier)
            return head, chunks

        first, it = open_stream(base)

        def texts(head, chunks) -> Iterator[str]:
            if head is not None and head.text:
                yield head.text
            for chunk in chunks:
                if chunk.text:
                    yield chunk.text

        def gen() -> Iterator[str]:
            sent = ""                       # 지금까지 내보낸 본문 / text yielded so far
            source = texts(first, it)
            resumes = 0
            while True:
                try:
                    for t in source:
                        sent += t
                        yield t
                    return
                except Exception as e:  # noqa: BLE001 — 스트림 도중 오류는 이어쓰기 대상 / mid-stream failures are resumable
                    if isinstance(e, errors.APIError) and not _is_rotatable_error(e):
                        raise
                    # 스트림을 주던 쪽을 쉬게 한다: 503 은 그 조합(이어쓰기가 같은 조합으로 되돌아가지 않게, 2026-09-14), 504 는 그 모델을
                    # 모든 키에서(이어쓰기가 다음 모델로, 2026-10-27) / cool what served the stream: a 503 its combo, a 504 the model on every key
                    self._cool_stream_source(used.get("model"), used.get("pos", -1), e)
                    if resumes >= _STREAM_RESUME_MAX:
                        if _is_unavailable(e) or _is_deadline(e):
                            raise ModelBusyError(f"이어쓰기 {resumes}회 실패") from e
                        if _is_transport_error(e):
                            raise ModelUnreachableError(f"이어쓰기 {resumes}회 실패") from e
                        raise
                    resumes += 1
                    logger.warning("스트림 중단(%s) — 다음 키/모델로 이어쓰기 %d/%d (보낸 본문 %d자)",
                                   e.__class__.__name__, resumes, _STREAM_RESUME_MAX, len(sent))
                    if sent.strip():
                        contents = base + [types.Content(role="model", parts=[types.Part.from_text(text=sent)]),
                                           types.Content(role="user", parts=[types.Part.from_text(text=_RESUME_NOTE)])]
                        head, chunks = open_stream(contents)
                        source = _resume_texts(texts(head, chunks), sent)
                    else:
                        head, chunks = open_stream(base)
                        source = texts(head, chunks)

        return gen()

    def generate_grounded(self, messages: list[Message] | str, system: str | None = None,
                          tier: str = "main") -> str:
        """Google Search grounding을 켠 호출(웹 검색 폴백용).

        미지원/한도 초과 시 GroundingUnavailableError를 던져 호출부가 일반 generate로 폴백한다.
        """
        # Call with Google Search grounding enabled (for web search fallback).
        #
        # On unsupported / limit exceeded, raise GroundingUnavailableError so the caller falls back to regular generate.
        return self.generate_grounded_meta(messages, system=system, tier=tier)["text"]

    def generate_grounded_meta(self, messages: list[Message] | str, system: str | None = None,
                               tier: str = "main") -> dict:
        """grounding 호출 + 출처 메타데이터 추출 — {text, sources, supports}.

        sources=[{title,url}] (웹 근거 목록), supports=[{end, ns:[1-기반 소스 번호]}] —
        end는 본문 '문자' 오프셋(Gemini의 바이트 오프셋을 변환). 채팅 리소스 참조 UI의 유일한 웹 출처원.
        메타데이터 추출 실패는 답변을 막지 않는다(빈 목록으로 폴백).
        첫 응답 제한(2026-10-30)은 비스트림 그대로라 호출 전체에 걸린다(그라운딩은 검색 시간까지 포함된다)."""
        # Grounded call + source-metadata extraction — {text, sources, supports}.
        # sources=[{title,url}]; supports=[{end, ns:[1-based source numbers]}] with `end` as a CHARACTER
        # offset into the text (converted from Gemini's byte offsets). The sole origin of web sources for
        # the chat resource-reference UI. Metadata-extraction failures never block the answer (empty fallback).
        # The first-response limit (2026-10-30) stays non-streaming here, so it covers the whole call, search time included.
        tools = [types.Tool(google_search=types.GoogleSearch())]
        config = types.GenerateContentConfig(system_instruction=system, tools=tools)
        contents = _to_contents(messages)

        def call(client: genai.Client, model: str):
            return client.models.generate_content(model=model, contents=contents, config=config)

        try:
            # kind="grounded" — 웹 검색 쿼터의 429 쿨다운을 일반 생성과 분리(일반 채팅 마비 방지)
            # kind="grounded" — isolates web-search 429 cooldowns from normal generation (no chat paralysis)
            resp = self._with_rotation(call, tier=tier, kind="grounded")
        except errors.APIError as e:
            raise GroundingUnavailableError(f"grounding 호출 실패(code={e.code}, status={e.status})") from e
        except RuntimeError as e:
            # 전 조합 쿨다운 즉시 실패 — grounding 불가로 승격해 호출부의 일반 생성 폴백을 태운다
            # All-cooldown fail-fast — promoted to GroundingUnavailable so callers fall back to plain generation
            raise GroundingUnavailableError(str(e)) from e
        text = resp.text or ""
        sources: list[dict] = []
        supports: list[dict] = []
        try:
            gm = getattr((resp.candidates or [None])[0], "grounding_metadata", None)
            for ch in (getattr(gm, "grounding_chunks", None) or []):
                web = getattr(ch, "web", None)
                url = str(getattr(web, "uri", None) or "")
                title = str(getattr(web, "title", None) or url or "웹 출처")
                sources.append({"title": title, "url": url})
            # 바이트 오프셋 → 문자 오프셋 변환 테이블(한글 3바이트 대응)
            # Byte-offset → character-offset table (handles 3-byte Hangul)
            b2c: dict[int, int] = {}
            bi = 0
            for ci, ch_ in enumerate(text):
                b2c[bi] = ci
                bi += len(ch_.encode("utf-8"))
            b2c[bi] = len(text)
            for sp in (getattr(gm, "grounding_supports", None) or []):
                seg = getattr(sp, "segment", None)
                end = getattr(seg, "end_index", None) if seg is not None else None
                if end is None:
                    continue
                idxs = [i for i in (getattr(sp, "grounding_chunk_indices", None) or [])
                        if isinstance(i, int) and 0 <= i < len(sources)]
                if not idxs:
                    continue
                end_c = b2c.get(int(end))
                if end_c is None:  # 경계 불일치 시 문자 인덱스로 간주(범위 내) 또는 스킵
                    # On boundary mismatch, treat as a char index (if in range) or skip
                    end_c = int(end) if 0 <= int(end) <= len(text) else None
                if end_c is None:
                    continue
                supports.append({"end": end_c, "ns": sorted({i + 1 for i in idxs})})
        except Exception:
            logger.warning("grounding 메타데이터 추출 실패 — 본문만 사용", exc_info=True)
            sources, supports = [], []
        return {"text": text, "sources": sources, "supports": supports}

    def embed(self, texts: list[str]) -> list[list[float]]:
        """gemini-embedding-001 배치 임베딩. 무료 티어 한도를 고려해 보수적 배치 + sleep."""
        # gemini-embedding-001 batch embedding. Conservative batching + sleep to account for the free-tier limit.
        vectors: list[list[float]] = []
        batch_size = settings.EMBED_BATCH_SIZE
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]

            def call(client: genai.Client, model: str, _batch=batch):
                return client.models.embed_content(model=model, contents=_batch)

            resp = self._with_rotation(call, models=[settings.EMB_MODEL])  # 임베딩은 폴백 체인 없음
            # Embedding has no fallback chain
            vectors.extend([list(e.values) for e in resp.embeddings])
            if i + batch_size < len(texts):
                time.sleep(settings.EMBED_SLEEP_SEC)
        return vectors


_client: GeminiClient | None = None
_client_lock = threading.Lock()


def get_client() -> GeminiClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = GeminiClient()
    return _client


def generate(messages, system=None, json_mode=False, tools=None, tier="main"):
    return get_client().generate(messages, system=system, json_mode=json_mode, tools=tools, tier=tier)


def generate_calls(messages, system=None, tools=None, tier="main", models=None):
    # models(2026-10-19, Agentic 모드): 세션이 고른 모델부터 아래로 내려가는 체인을 명시한다(없으면 tier 체인) / an explicit chain starting at the chosen model
    return get_client().generate_calls(messages, system=system, tools=tools, tier=tier, models=models)


def stream(messages, system=None, tier="main"):
    return get_client().stream(messages, system=system, tier=tier)


def generate_grounded(messages, system=None, tier="main"):
    return get_client().generate_grounded(messages, system=system, tier=tier)


def generate_grounded_meta(messages, system=None, tier="main"):
    return get_client().generate_grounded_meta(messages, system=system, tier=tier)


def embed(texts: list[str]) -> list[list[float]]:
    return get_client().embed(texts)
