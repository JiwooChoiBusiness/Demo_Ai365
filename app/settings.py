"""환경 설정. 모델명/한도 관련 상수를 한곳에서 관리한다."""
# Environment settings. Manages model-name and limit constants in one place.

import os

from dotenv import load_dotenv

load_dotenv()

# 모델 2단 구성: 최종 답변·취합은 MAIN, 의도판단·제목요약·Text2SQL·분류 등 경량 작업은 LITE
# Two-tier model setup: MAIN for the final answer/aggregation; LITE for lightweight tasks (intent detection, title summary, Text2SQL, classification, etc.)
# 2026-08-29(사용자 확정 "2.5 쓰지말자"): 2.5 계열 전면 퇴역 — 구키(1~5)도 신규 키(6~9)와 동일 라인업.
# 이로써 전 키가 같은 체인이라 키별 오버라이드(GEMINI_KEY_CHAIN_*)는 불필요해졌다.
# 2026-09-03(사용자 확정): MAIN 을 gemini-3.8-flash 로 올리고 체인을 3.8-flash → 3.7-flash → 3.5-flash-lite 로 교체
# (3.8/3.7 flash 는 전 키 200 확인). LITE 는 3.5-flash-lite 유지 — 체인 끝이라 lite 티어는 자체 폴백 모델이 없다.
# 2026-10-30(사용자 확정): 3.8-flash 가 짧은 질문에도 30~65초 · 504(약 2분)로 '모델 응답을 기다리는 중'이 잦아
# MAIN 을 gemini-3.7-flash 로, 체인을 3.7-flash → 3.5-flash → 3.5-flash-lite 로 바꿨다(같은 날 측정: 3.5-flash 전 키 3~4초).
# 2026-08-29 (user decision "no more 2.5"): the 2.5 family is fully retired — old keys (1~5) run the same
# lineup as the new-account keys (6~9). Every key shares one chain, so the per-key override
# (GEMINI_KEY_CHAIN_*) is no longer needed.
# 2026-09-03 (user decision): MAIN raised to gemini-3.8-flash and the chain replaced with
# 3.8-flash → 3.7-flash → 3.5-flash-lite (3.8/3.7 flash return 200 on every key). LITE stays
# 3.5-flash-lite — it is the chain's tail, so the lite tier has no further fallback model.
# 2026-10-30 (user decision): 3.8-flash took 30-65 s even for short prompts and hit 504s (about 2 min), so 'waiting for the
# model' showed up often. MAIN is now gemini-3.7-flash and the chain 3.7-flash → 3.5-flash → 3.5-flash-lite (measured the
# same day: 3.5-flash answered in 3-4 s on every key).
GEN_MODEL_MAIN = os.getenv("GEN_MODEL_MAIN", "gemini-3.7-flash")
GEN_MODEL_LITE = os.getenv("GEN_MODEL_LITE", "gemini-3.5-flash-lite")
# 한 모델에서 전 키가 429면 같은 키 풀로 다음 모델로 자동 전환하는 폴백 체인
# Fallback chain: when every key returns 429 on one model, auto-switch to the next model using the same key pool
GEN_FALLBACK_CHAIN = [
    m.strip()
    for m in os.getenv(
        # (연혁) 2026-08-24: 종단 gemini-2.0-flash 서비스 종료(404) → 3.6-flash로 교체.
        # 2026-08-28: 신규 계정 키가 2.5 계열 404(retired-for-new-users) → 키별 체인 도입.
        # 2026-08-29: 2.5 계열 전면 퇴역 — 전 키 공통 3.5-flash → 3.5-flash-lite → 3.6-flash.
        # (gemini-3.6-flash-lite는 존재하지 않는 모델 — 구·신 키 모두 404, 2026-08-28 확인.)
        # 2026-09-03: 체인 교체 3.8-flash → 3.7-flash → 3.5-flash-lite(사용자 확정, 두 모델 전 키 200 확인).
        # 2026-10-30: 3.7-flash → 3.5-flash → 3.5-flash-lite(사용자 확정, 3.8-flash 지연 · 504 때문에 뺌).
        # (History) 2026-08-24: terminal gemini-2.0-flash retired (404) → 3.6-flash. 2026-08-28: new-account
        # keys 404 on the 2.5 family → per-key chains. 2026-08-29: 2.5 family fully retired — one shared
        # chain 3.5-flash → 3.5-flash-lite → 3.6-flash for every key. (gemini-3.6-flash-lite does not
        # exist — 404 on both old and new keys, verified 2026-08-28.) 2026-09-03: chain replaced with
        # 3.8-flash → 3.7-flash → 3.5-flash-lite (user decision; both models return 200 on every key). 2026-10-30:
        # 3.7-flash → 3.5-flash → 3.5-flash-lite (user decision; 3.8-flash dropped for its delays and 504s).
        "GEN_FALLBACK_CHAIN", "gemini-3.7-flash,gemini-3.5-flash,gemini-3.5-flash-lite"
    ).split(",")
    if m.strip()
]
EMB_MODEL = os.getenv("EMB_MODEL", "gemini-embedding-001")

# 키별 폴백 체인 오버라이드(2026-08-28) — GEMINI_KEY_CHAIN_<슬롯>이 있으면 그 키는 자신만의 체인을 쓴다.
# 2026-08-29 2.5 전면 퇴역으로 전 키가 전역 체인과 동일해져 현재 .env에는 오버라이드가 없다
# (메커니즘은 향후 키별 차등을 위해 유지).
# Per-key fallback-chain override (2026-08-28) — a key with GEMINI_KEY_CHAIN_<slot> uses its own chain.
# With the 2.5 family fully retired (2026-08-29) every key matches the global chain, so .env currently
# carries no overrides (the mechanism stays for future per-key divergence).


def load_key_chains(pool: list[tuple[int, str]]) -> list[list[str]]:
    """풀 위치별 모델 체인 — GEMINI_KEY_CHAIN_<슬롯> 오버라이드, 없으면 전역 GEN_FALLBACK_CHAIN."""
    # Per-pool-position model chains — GEMINI_KEY_CHAIN_<slot> override, else the global GEN_FALLBACK_CHAIN.
    chains: list[list[str]] = []
    for idx, _key in pool:
        raw = (os.getenv(f"GEMINI_KEY_CHAIN_{idx}") or "").strip()
        chain = [m.strip() for m in raw.split(",") if m.strip()] if raw else list(GEN_FALLBACK_CHAIN)
        chains.append(chain)
    return chains

# 임베딩 무료 티어 분당 한도를 고려한 보수적 배치/대기
# Conservative batch size / wait given the embedding free-tier per-minute limit
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "16"))
EMBED_SLEEP_SEC = float(os.getenv("EMBED_SLEEP_SEC", "1.5"))

# 전 키 소진 시 지수 백오프(초): 1회 더 시도하기 전 대기
# Exponential backoff (sec) when all keys are exhausted: wait before trying once more
BACKOFF_BASE_SEC = float(os.getenv("BACKOFF_BASE_SEC", "4.0"))

# 503 UNAVAILABLE(모델 혼잡) 쿨다운(초): 같은 (호출종류·모델·키) 조합을 이 시간 동안 건너뛴다 — 호출마다 죽은 조합을 전부 다시 밟아
# 수십 초씩 조용해지던 결함(2026-09-14 배포 점검). 0 이면 끔.
# 503 UNAVAILABLE (model overloaded) cooldown in seconds: skip the same (kind, model, key) combo for this long — every call
# used to re-walk every dead combo and go silent for tens of seconds (2026-09-14 deployment review). 0 disables it.
GEMINI_503_COOLDOWN_SEC = float(os.getenv("GEMINI_503_COOLDOWN_SEC", "60.0"))
# 같은 조합이 연속으로 503이면 쿨다운을 2배씩 늘린다(상한). 폭주 때 죽은 조합 한 바퀴(약 2분)보다 짧은 쿨다운은 다음 호출이 또 전부
# 밟게 하므로(로컬 프로브 확인) 지속되는 폭주에서는 상한까지 늘어난다. 성공하면 초기화.
# Consecutive 503s on the same combo double the cooldown up to this cap. A cooldown shorter than one walk of the dead combos
# (~2 min in a storm) lets the next call re-walk them all (seen in the local probe), so a sustained storm escalates to the cap. Reset on success.
GEMINI_503_COOLDOWN_MAX_SEC = float(os.getenv("GEMINI_503_COOLDOWN_MAX_SEC", "600"))
# Gemini HTTP 타임아웃(초): 연결·읽기(스트림은 청크 사이) 대기 상한 — 없으면 매달린 요청이 영원히 기다린다(SDK 기본 None). 0 이면 끔.
# Gemini HTTP timeout in seconds (connect and read; between chunks for streams) — without it a hung request waits forever
# (the SDK default is None). 0 disables it.
GEMINI_HTTP_TIMEOUT_SEC = float(os.getenv("GEMINI_HTTP_TIMEOUT_SEC", "120"))
# 첫 응답 시간 제한(초, 2026-10-30 사용자 지시 "LLM API키 응답이 20초 동안 없으면 다음 모델로"): 3.7 · 3.8-flash 가 짧은 질문에도
# 30~120초를 끌거나 504 를 내 '모델 응답을 기다리는 중'이 길어졌다. 티어 체인 호출에서 다음 모델이 남은 단계만 첫 응답(스트림은 첫 청크)을
# 이 시간까지 기다리고, 넘으면 504 처럼 그 모델을 모든 키에서 쉬게 하고 바로 다음 모델로 간다(체인 마지막 모델 · Agentic 명시 체인 ·
# 임베딩은 제한 없음). GEMINI_HTTP_TIMEOUT_SEC 와 별개다: SDK 는 그 값을 X-Server-Timeout 헤더로 서버에도 보내 긴 답을 통째로 끊으므로
# 그 값은 줄이지 않고 llm.py 의 감시 스레드가 따로 잰다. 0 이면 끔.
# First-response limit in seconds (user instruction 2026-10-30: when a key gives no answer for 20 s, move to the next model): 3.7 and
# 3.8-flash took 30-120 s even for short prompts or hit 504s, so 'waiting for the model' dragged on. On tier-chain calls, every stage
# that still has a next model waits this long for the first response (the first chunk for streams); past it the model rests on every
# key like a 504 and the call moves straight to the next model (the chain's last model, Agentic's explicit chains and embeddings have
# no limit). Separate from GEMINI_HTTP_TIMEOUT_SEC: the SDK also sends that value to the server as X-Server-Timeout, which would cut
# long answers, so it stays and a watcher thread in llm.py measures this limit instead. 0 disables it.
GEMINI_FIRST_RESPONSE_SEC = float(os.getenv("GEMINI_FIRST_RESPONSE_SEC", "20"))

# 데이터 분석 설정
# Data analysis settings
SQL_ROW_LIMIT = int(os.getenv("SQL_ROW_LIMIT", "200"))
# 리포트 에이전트 도구 루프의 모델 티어(2026-09-18): 기본 lite(라운드당 1~2초), main 으로 바꾸면 품질 우선. 고른 티어가 실패하면 다른 티어로 1회 재시도.
# Model tier of the report agent's tool loop (2026-09-18): lite by default (1-2 s per round), main favours quality;
# when the chosen tier fails the other one is tried once.
REPORT_AGENT_TIER = os.getenv("REPORT_AGENT_TIER", "lite")
# Agentic 모드(2026-10-19): 이 서버 PC 에서 명령을 돌리므로 기본은 루프백(127.0.0.1 · ::1) 요청만 받는다. 1 이면 원격 요청도 받는다.
# Agentic mode (2026-10-19) runs commands on this server PC, so only loopback requests are served by default; 1 allows remote ones.
AGENTIC_ALLOW_REMOTE = os.getenv("AGENTIC_ALLOW_REMOTE", "").strip().lower() in ("1", "true", "yes")

# 지식관리(KB) 설정
# Knowledge management (KB) settings
KB_CHUNK_SIZE = int(os.getenv("KB_CHUNK_SIZE", "600"))
KB_CHUNK_OVERLAP = int(os.getenv("KB_CHUNK_OVERLAP", "120"))
KB_TOP_K = int(os.getenv("KB_TOP_K", "6"))
KB_VECTOR_WEIGHT = float(os.getenv("KB_VECTOR_WEIGHT", "0.65"))  # 하이브리드 가중치(벡터)
# Hybrid weight (vector)
KB_STRONG_SIM = float(os.getenv("KB_STRONG_SIM", "0.74"))  # 이상이면 근거 충분(answer)
# At or above this, evidence is sufficient (answer)
KB_WEAK_SIM = float(os.getenv("KB_WEAK_SIM", "0.62"))  # 이상이면 근거 약함(inference), 미만은 웹 폴백
# At or above this, evidence is weak (inference); below it, web fallback


def load_key_pool() -> list[tuple[int, str]]:
    """(키 인덱스, 키 값) 풀 — GEMINI_API_KEY_1~12 스캔(빈 슬롯 스킵). 중복 키 값은 한 번만 넣는다
    (같은 키를 두 슬롯에 넣어도 쿼터는 하나 — 헛 로테이션 방지). 키 값은 절대 로그/출력에 노출 금지."""
    # (key index, key value) pool — scans GEMINI_API_KEY_1~12 (empty slots skipped). Duplicate key values
    # are pooled once (two slots with the same key share one quota — avoids pointless rotation).
    # Never expose key values in logs/output.
    pool = []
    seen: set[str] = set()
    for i in range(1, 13):
        key = (os.getenv(f"GEMINI_API_KEY_{i}") or "").strip()
        if key and key not in seen:
            pool.append((i, key))
            seen.add(key)
    if not pool:
        raise RuntimeError("GEMINI_API_KEY_1~12 중 사용 가능한 키가 없습니다 (.env 확인)")
    return pool
