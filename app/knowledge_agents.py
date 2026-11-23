"""로컬 지식 에이전트 저장소(2026-09-29, 계획 A1 · 구현 계약 1~4절) — 관리 센터 › 로컬 설정에서 등록하는, 고객 환경에 배포된
지식 관리 에이전트. 에이전트 1개 = MCP 서버 주소(채팅 · 검색 · 문서 조회) + API Base URL(문서 목록 · 업로드 · 미리보기 ·
다운로드 · 삭제 · 상태) + 인증 1벌(없음 / API Key / Bearer / OAuth 2.0 client credentials) + 데모 배포 설정(저장만).

  - 테이블 knowledge_agents(id 'kl_<hex8>', name, description, enabled, config JSON, status JSON, pos, created_at, updated_at)
    + knowledge_agents_meta(시드 플래그). 시드 = 고정 id kl_demo_hq "본사 로컬 에이전트" 1회(지워도 다시 생기지 않는다,
    2026-10-07 옛 이름 "본사 지식 에이전트"에서 바뀜 — 이미 만든 DB 는 _migrate_seed_name 이 1회 바꾼다).
  - 권한: 에이전트 id 가 곧 권한 노드(리소스 센터 › p_klocal 의 잎, catalog.build_pv_tree). summaries() 는 JSON 을 읽지 않는
    단순 SELECT 라 부팅 때 읽기 실패로 grant 가 지워질 위험을 줄인다.
  - 비밀(auth.key · auth.client_secret)은 편집 응답에서 가리고(connectors.SECRET_MASK), 가린 값이 그대로 오면 저장값을 유지한다.
  - check(): MCP initialize + tools/list(규격 도구 3종 · kb_chat 출력의 sources) + API /health · /documents 로 기능 점검표를 만든다.
  - 문서 프록시: 폴더 · 문서 목록 · 상태 · 미리보기 · 다운로드 · 업로드 · 삭제를 저장된 주소 · 인증으로 대신 부른다.
    모든 URL 은 {{base_url}} 치환 뒤 flow_api_call.check_url 을 통과하고, 리다이렉트는 따르지 않으며, 오류 사유는 비밀을 가린다.
    OAuth 토큰은 (에이전트 id, 토큰 URL, client id) 별로 만료 30초 전까지 캐시한다.
  - 호출하는 쪽(API)은 전부 동기 함수다: 같은 서버의 /mock 을 부를 때 async def 안의 동기 httpx 는 이벤트 루프를 막는다.
  - 채팅 연동(2026-09-30): readable(eff) = 채팅 지식 답변에 쓸 수 있는 에이전트(사용 중 + 잎 열람), call_tool() = 저장된
    주소 · 인증으로 MCP 도구 1회 호출. 호출 조율은 app/local_knowledge.py, 채팅 단계는 app/answers.py 가 맡는다.

Local knowledge agent store (2026-09-29, plan A1, contract sections 1-4). Knowledge agents deployed in a customer
environment and registered in Admin Center › Local settings. One agent = an MCP server URL (chat, search, document
lookup) + an API base URL (list, upload, preview, download, delete, status) + one auth setup (none / API key / bearer /
OAuth 2.0 client credentials) + demo deployment settings (stored only).
  - Tables knowledge_agents (ids 'kl_<hex8>') and knowledge_agents_meta (seed flag). The seed is the fixed kl_demo_hq
    "본사 로컬 에이전트" (renamed 2026-10-07 from "본사 지식 에이전트"; existing databases are renamed once by _migrate_seed_name),
    created once and never re-created after deletion.
  - Permissions: the agent id is the permission node (a leaf of p_klocal under the Resource Center). summaries() is a
    plain SELECT without JSON parsing, which keeps a boot-time read failure from wiping grants.
  - Secrets (auth.key, auth.client_secret) are masked in editor payloads; an echoed mask keeps the stored value.
  - check(): MCP initialize + tools/list (the three spec tools, sources in kb_chat's output) + API /health and /documents
    → a capability checklist.
  - Document proxy: folders, document list, status, preview, download, upload and delete through the stored URL/auth.
    Every URL is resolved from {{base_url}} and passes flow_api_call.check_url, redirects are never followed and error
    reasons are redacted. OAuth tokens are cached per (agent id, token URL, client id) until 30 s before expiry.
  - Callers (the API) are plain sync functions: a sync httpx call inside async def blocks the loop when it hits /mock.
  - Chat integration (2026-09-30): readable(eff) = agents usable in chat knowledge answers (enabled + leaf view), call_tool() =
    one MCP tool call with the stored URL and auth. app/local_knowledge.py orchestrates the calls; app/answers.py owns the
    chat stage.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import logging
import math
import re
import sqlite3
import ssl
import threading
import time
import unicodedata
import uuid
from contextlib import closing, contextmanager
from pathlib import Path
from urllib.parse import quote, quote_plus, unquote

import httpx

from app import flow_api_call, kst, mcp_client, mcp_servers, skill_files
from app.connectors import SECRET_MASK, ConnectorValidationError
from app.db import DB_PATH

logger = logging.getLogger("ai365.knowledge_agents")

ID_PREFIX = "kl_"
SEED_ID = "kl_demo_hq"
# 데모 에이전트 이름 · 설명(2026-10-07 사용자 지시로 '지식' → '로컬') + 옛 값(1회 이전용)
# The demo agent's name and description (renamed 2026-10-07) and the old values for the one-time migration
SEED_NAME = "본사 로컬 에이전트"
SEED_DESCRIPTION = "본사 사내 규정과 영업 자료를 검색하고 답변하는 로컬 에이전트"
SEED_NAME_OLD = "본사 지식 에이전트"
SEED_DESCRIPTION_OLD = "본사 사내 규정과 영업 자료를 검색하고 답변하는 로컬 지식 에이전트"
SEED_NAME_FLAG = "seed_name_local_v1"
SEED_FLAG = "seed_demo_hq_v1"
SKILL_OWNER = "kagent"                       # skill_files 의 owner_kind / owner_kind in skill_files
MAX_AGENTS, MAX_NAME, MAX_DESC, MAX_URL = 50, 40, 200, 500
MAX_HEADER, MAX_CLIENT_ID = 80, 200
TIMEOUT_MIN, TIMEOUT_MAX, TIMEOUT_DEFAULT = 5, 120, 30
AUTH_TYPES = ("none", "api_key", "bearer", "oauth2")
REQUIRED_TOOLS = ("kb_chat", "kb_search", "kb_get_document")
CAPABILITIES = ("list", "upload", "preview", "download", "delete", "status")
UPLOAD_EXTS = ("pdf", "txt", "md", "hwp", "hwpx", "docx", "xlsx", "pptx")
MIME_BY_EXT = {
    "pdf": "application/pdf", "txt": "text/plain", "md": "text/markdown",
    "hwp": "application/x-hwp", "hwpx": "application/hwp+zip",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024          # 업로드 상한 / upload cap
MAX_PROXY_BYTES = 200 * 1024 * 1024          # 미리보기 · 다운로드 중계 상한 / cap on relayed previews and downloads
MAX_TEXT_PREVIEW_BYTES = 20 * 1024 * 1024    # 텍스트 미리보기(전체를 읽어 UTF-8 로 바꾼다) / text previews are read whole
MAX_JSON_BYTES = 5 * 1024 * 1024             # JSON 응답 상한 / cap on JSON replies
MAX_DOCS, MAX_FOLDERS = 2000, 500
TOKEN_SKEW_SEC = 30                          # 만료 30초 전부터 새 토큰 / refresh 30 s before expiry
# 응답 본문 전체 읽기 제한 시간(2026-09-29): 조금씩 흘려보내는 서버가 스레드를 붙잡지 못하게. JSON = 타임아웃의 2배,
# 미리보기 · 다운로드 스트림 = 2배와 STREAM_DEADLINE_MIN 중 큰 값(50MB 파일이 느린 망에서도 끝나게).
# Total body-read deadline (2026-09-29) so a trickling server cannot hold a thread: JSON = 2x timeout; preview/download
# streams = the larger of 2x timeout and STREAM_DEADLINE_MIN (room for a 50 MB file on a slow link).
STREAM_DEADLINE_MIN = 300
# API Key 헤더로 쓸 수 없는 이름(대소문자 무시) — 요청 틀을 깨거나 MCP 세션 헤더와 겹친다. Authorization 은 허용.
# Header names refused for API keys (case-insensitive): they break framing or clash with MCP session headers. Authorization is allowed.
DENIED_KEY_HEADERS = frozenset({"host", "content-length", "transfer-encoding", "connection", "content-type", "accept",
                                "mcp-session-id", "mcp-protocol-version"})
DEST_CHANGED = "주소가 바뀌면 인증 정보를 다시 입력해야 합니다"
TYPE_CHANGED = "인증 방식이 바뀌면 인증 정보를 다시 입력해야 합니다"
# 전송 주입 지점(테스트 · 진단용 가짜 전송). 운영에서는 항상 None / transport injection point (tests, diagnostics); None in production
DEFAULT_TRANSPORT = None

# 데모 배포 설정(구현 계약 2절) — 저장만 하고 동작은 없다 / demo deployment settings (contract section 2): stored, no behavior
STORAGES = ("on_prem", "azure_blob", "aws_s3")
VECTOR_DBS = ("milvus", "azure_ai_search", "chroma")
MODEL_TYPES = ("local", "public")
EMBEDDING_MODELS = {"local": ("bge-m3", "multilingual-e5-large"), "public": ("text-embedding-3-large", "text-embedding-3-small")}
# 로컬 LLM 기본 = Qwen 3.5-4B(2026-10-06 사용자 지시 — 옛 'qwen-3.8m' 은 아래 1회 이전으로 바뀐다)
# Default local LLM = Qwen 3.5-4B (user instruction 2026-10-06; the old 'qwen-3.8m' is renamed by the one-time migration below)
LLM_MODELS = {"local": ("qwen-3.5-4b", "deepseek-v4-pro", "llama-4"), "public": ("azure-openai-gpt", "claude", "gemini")}
LLM_MIGRATE_FLAG = "llm_qwen35_v1"
PARSERS = ("default", "layout", "ocr")
RERANKERS = ("none", "bge-reranker", "cross-encoder")
NETWORKS = ("private", "vpn", "allowlist")
DEFAULT_SETTINGS = {
    "storage": "on_prem", "vector_db": "milvus",
    "embedding": {"type": "local", "model": "bge-m3"},
    "llm": {"type": "local", "model": "qwen-3.5-4b"},
    "processing": {"chunk_size": 800, "chunk_overlap": 100, "parser": "layout"},
    "retrieval": {"top_k": 5, "threshold": 0.35, "reranker": "bge-reranker"},
    "security": {"network": "private"},
}

# 연결 확인 항목(구현 계약 3절, 순서 고정) / connection checklist (contract section 3, fixed order)
MCP_TOOL_CHECKS = (("mcp_chat", "kb_chat"), ("mcp_search", "kb_search"), ("mcp_get_document", "kb_get_document"))
API_CAP_CHECKS = (("api_upload", "upload", "POST /documents"), ("api_preview", "preview", "GET /documents/{id}/preview"),
                  ("api_download", "download", "GET /documents/{id}/download"), ("api_delete", "delete", "DELETE /documents/{id}"),
                  ("api_status", "status", "GET /documents/{id}/status"))

_URL_RX = re.compile(r"^(https?://|\{\{\s*base_url\s*\}\})", re.I)
_HEADER_RX = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,80}$")
_CTRL_RX = re.compile(r"[\x00-\x1f\x7f]")
_DOC_ID_RX = re.compile(r"^[\w.:@~+=,\-]{1,200}$")


class KnowledgeAgentValidationError(ConnectorValidationError):
    """잘못된 입력 — API 층이 422 로 바꾼다 / bad input, turned into 422 by the API layer"""


class KnowledgeAgentConflictError(KnowledgeAgentValidationError):
    """같은 이름의 에이전트 — API 층이 409 로 바꾼다 / duplicate agent name, turned into 409 by the API layer"""


class AgentCallError(Exception):
    """에이전트 호출 실패. reason 은 비밀을 가린 한 줄, status 는 에이전트가 준 HTTP 상태(없으면 None).
    An agent call failed. reason is a redacted one-liner; status is the agent's HTTP status (None when there was none)."""

    def __init__(self, reason: str, status: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.status = status


V = KnowledgeAgentValidationError


def _now() -> str:
    return kst.now_iso()


# ────────────────────────────────────────────────────────
# DB
# ────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_agents(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  config TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT '{}',
  pos INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge_agents_meta(k TEXT PRIMARY KEY, v TEXT);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _tx():
    """쓰기 트랜잭션(BEGIN IMMEDIATE — 이름 중복 검사와 저장 사이에 끼어들지 못하게) / write transaction (BEGIN IMMEDIATE)"""
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_knowledge_agents() -> None:
    """테이블 생성(멱등) + 데모 시드 1회 / create the tables (idempotent) and seed the demo agent once"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(_conn()) as conn:
        conn.executescript(_SCHEMA)
    _seed_demo()
    _migrate_local_llm()
    _migrate_seed_name()


def _migrate_local_llm() -> None:
    """로컬 LLM 1회 이전(2026-10-06) — 없어진 'qwen-3.8m' 과 데모 에이전트(kl_demo_hq)의 옛 기본값 'deepseek-v4-pro' 를
    'qwen-3.5-4b' 로. 플래그로 한 번만 돌아 이후 사용자가 고른 모델은 건드리지 않는다.
    One-time local-LLM migration (2026-10-06): the removed 'qwen-3.8m' and the demo agent's (kl_demo_hq) old default
    'deepseek-v4-pro' become 'qwen-3.5-4b'. A flag keeps it to one run, so later user choices are left alone."""
    with _tx() as conn:
        if conn.execute("SELECT 1 FROM knowledge_agents_meta WHERE k=?", (LLM_MIGRATE_FLAG,)).fetchone():
            return
        for r in conn.execute("SELECT id, config FROM knowledge_agents").fetchall():
            cfg = _loads(r["config"], {})
            llm = (cfg.get("settings") or {}).get("llm") or {}
            old = llm.get("model")
            if llm.get("type", "local") == "local" and (old == "qwen-3.8m" or (r["id"] == SEED_ID and old == "deepseek-v4-pro")):
                llm["model"] = "qwen-3.5-4b"
                conn.execute("UPDATE knowledge_agents SET config=? WHERE id=?", (json.dumps(cfg, ensure_ascii=False), r["id"]))
        conn.execute("INSERT OR REPLACE INTO knowledge_agents_meta(k, v) VALUES(?, '1')", (LLM_MIGRATE_FLAG,))


def _migrate_seed_name() -> None:
    """데모 에이전트 이름 1회 변경(2026-10-07 사용자 지시 '본사 로컬 에이전트') — 이름 · 설명이 옛 시드 값 그대로일 때만 바꾼다.
    같은 이름을 다른 에이전트가 이미 쓰면 이름은 두고(이름은 겹칠 수 없다) 설명만. 플래그로 한 번만 돌아 이후 사용자가 고친 이름은 그대로.
    One-time rename of the demo agent (user request 2026-10-07): only values still equal to the old seed text change; the name stays
    when another agent already uses the new one (names are unique). A flag keeps it to one run, so later edits are left alone."""
    with _tx() as conn:
        if conn.execute("SELECT 1 FROM knowledge_agents_meta WHERE k=?", (SEED_NAME_FLAG,)).fetchone():
            return
        r = conn.execute("SELECT name, description FROM knowledge_agents WHERE id=?", (SEED_ID,)).fetchone()
        if r is not None:
            taken = any(_name_key(o["name"]) == _name_key(SEED_NAME)
                        for o in conn.execute("SELECT name FROM knowledge_agents WHERE id<>?", (SEED_ID,)).fetchall())
            if r["name"] == SEED_NAME_OLD and not taken:
                conn.execute("UPDATE knowledge_agents SET name=? WHERE id=?", (SEED_NAME, SEED_ID))
            if r["description"] == SEED_DESCRIPTION_OLD:
                conn.execute("UPDATE knowledge_agents SET description=? WHERE id=?", (SEED_DESCRIPTION, SEED_ID))
        conn.execute("INSERT OR REPLACE INTO knowledge_agents_meta(k, v) VALUES(?, '1')", (SEED_NAME_FLAG,))


def _loads(text, default):
    try:
        v = json.loads(text or "")
    except (TypeError, ValueError):
        return copy.deepcopy(default)
    return v if isinstance(v, type(default)) else copy.deepcopy(default)


def _row(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "name": r["name"], "description": r["description"] or "", "enabled": bool(r["enabled"]),
            "config": _loads(r["config"], {}), "status": _loads(r["status"], {}), "pos": int(r["pos"] or 0),
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


def list_agents() -> list[dict]:
    try:
        with closing(_conn()) as conn:
            rows = conn.execute("SELECT * FROM knowledge_agents ORDER BY pos, created_at").fetchall()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return []
        raise
    return [_row(r) for r in rows]


def get_agent(agent_id: str) -> dict | None:
    try:
        with closing(_conn()) as conn:
            r = conn.execute("SELECT * FROM knowledge_agents WHERE id=?", (agent_id,)).fetchone()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return None
        raise
    return _row(r) if r else None


def summaries() -> list[dict]:
    """권한 축용 요약 [{id, name}] — JSON 을 읽지 않는 단순 SELECT, 표가 없으면 [] (access.rebuild_universe 가 p_klocal 잎으로 쓴다).
    Permission-axis summary [{id, name}]: a plain SELECT without JSON parsing, [] when the table is missing."""
    try:
        with closing(_conn()) as conn:
            rows = conn.execute("SELECT id, name FROM knowledge_agents ORDER BY pos, created_at").fetchall()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return []
        raise
    return [{"id": r["id"], "name": r["name"]} for r in rows]


# ────────────────────────────────────────────────────────
# 검증 · 정규화 / validation
# ────────────────────────────────────────────────────────

def _str(v, cap: int, what: str) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise V(f"{what}은(는) 문자열이어야 합니다")
    v = v.strip()
    if len(v) > cap:
        raise V(f"{what}은(는) {cap}자 이하여야 합니다")
    return v


def _bool(v, default: bool, what: str) -> bool:
    if v is None:
        return default
    if not isinstance(v, bool):
        raise V(f"{what}은(는) true 또는 false 여야 합니다")
    return v


def _int_in(v, lo: int, hi: int, default: int, what: str) -> int:
    msg = f"{what}은(는) {lo}~{hi} 사이의 정수여야 합니다"
    if v is None or (isinstance(v, str) and not v.strip()):
        return default
    if isinstance(v, bool):
        raise V(msg)
    if isinstance(v, float):
        if not v.is_integer():
            raise V(msg)
        v = int(v)
    elif isinstance(v, str):
        try:
            v = int(v.strip())
        except ValueError:
            raise V(msg)
    if not isinstance(v, int) or not lo <= v <= hi:
        raise V(msg)
    return v


def _float_in(v, lo: float, hi: float, default: float, what: str) -> float:
    msg = f"{what}은(는) {lo:g}~{hi:g} 사이의 숫자여야 합니다"
    if v is None or (isinstance(v, str) and not v.strip()):
        return default
    if isinstance(v, bool):
        raise V(msg)
    try:
        x = float(v.strip() if isinstance(v, str) else v)
    except (TypeError, ValueError):
        raise V(msg)
    if math.isnan(x) or not lo <= x <= hi:
        raise V(msg)
    return round(x, 4)


def _choice(v, options: tuple, default: str, what: str) -> str:
    if v is None or (isinstance(v, str) and not v.strip()):
        return default
    if not isinstance(v, str) or v.strip() not in options:
        raise V(f"{what}은(는) {'/'.join(options)} 중 하나여야 합니다")
    return v.strip()


def _url(v, what: str, *, strip_slash: bool = False, no_query: bool = False) -> str:
    u = _str(v, MAX_URL, what)
    if not u:
        raise V(f"{what}이(가) 비어 있습니다")
    if not _URL_RX.match(u):
        raise V(f"{what}은(는) http://, https:// 또는 {{{{base_url}}}} 로 시작해야 합니다")
    if _CTRL_RX.search(u):
        raise V(f"{what}에 줄바꿈이나 제어 문자를 넣을 수 없습니다")
    # 뒤에 경로를 붙이는 주소라 쿼리 · 조각이 있으면 붙인 경로를 삼킨다(2026-09-29) / we append paths, so ?/# would swallow them
    if no_query and ("?" in u or "#" in u):
        raise V(f"{what}에는 쿼리(?)나 조각(#)을 넣을 수 없습니다")
    return u.rstrip("/") if strip_slash else u


def _secret(v, prev: str | None, what: str, *, header: bool = False, same_type: bool = True) -> tuple[str, bool]:
    """비밀 값 → (값, 가린 값에서 복원했는지). 가린 값(SECRET_MASK)이 그대로 오면 저장값 유지(mcp_servers._restore_key 방식)하되,
    인증 방식이 저장값과 같을 때만(same_type — 예: Bearer 토큰이 API Key 로 옮겨 가지 않게, 2026-09-29).
    header=True 는 HTTP 헤더에 실리는 값이라 ASCII 만 받는다(아니면 전송 단계에서 500).
    Secret → (value, restored from the mask?). An echoed SECRET_MASK keeps the stored secret (mcp_servers._restore_key style),
    but only while the auth type is unchanged (same_type, so a bearer token never turns into an API key; 2026-09-29).
    header=True values travel in an HTTP header, so only ASCII is accepted (anything else fails with a 500 when sent)."""
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise V(f"{what}은(는) 문자열이어야 합니다")
    v = v.strip()
    if SECRET_MASK in v:
        if not prev:
            raise V(f"저장된 {what}이(가) 없습니다. {what}을(를) 다시 입력하세요")
        if not same_type:
            raise V(TYPE_CHANGED)
        if v != SECRET_MASK:
            raise V(f"가려진 {what}이(가) 포함된 값을 바꾸려면 {what}을(를) 다시 입력하세요")
        return prev, True
    if len(v) > flow_api_call.MAX_SECRET:
        raise V(f"{what}은(는) {flow_api_call.MAX_SECRET}자 이하여야 합니다")
    if _CTRL_RX.search(v):
        raise V(f"{what}에 줄바꿈이나 제어 문자를 넣을 수 없습니다")
    if header and not v.isascii():
        raise V(f"{what}에는 영문, 숫자, 기호만 쓸 수 있습니다")
    return v, False


def blank_auth(auth_type: str = "none") -> dict:
    return {"type": auth_type, "header": "", "key": "", "token_url": "", "client_id": "", "client_secret": ""}


def _normalize_auth(raw, prev_auth: dict | None = None) -> tuple[dict, bool]:
    """인증 설정 검증 → (인증, 가린 비밀을 저장값으로 복원했는지). 방식별 필수값만 남기고 나머지는 비운다.
    Validate auth → (auth, whether a masked secret was restored from the stored value); only the type's fields are kept."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise V("인증 설정은 객체여야 합니다")
    t = raw.get("type") or "none"
    if t not in AUTH_TYPES:
        raise V(f"인증 방식은 {'/'.join(AUTH_TYPES)} 중 하나여야 합니다")
    prev = prev_auth if isinstance(prev_auth, dict) else {}
    same_type = prev.get("type") == t   # 가린 비밀은 같은 방식으로만 복원 / masked secrets restore only within the same type
    out, restored = blank_auth(t), False
    if t == "api_key":
        header = _str(raw.get("header"), MAX_HEADER, "헤더 이름") or "X-API-Key"
        if not _HEADER_RX.match(header):
            raise V("헤더 이름에는 영문, 숫자와 - _ . 같은 기호만 쓸 수 있습니다")
        if header.lower() in DENIED_KEY_HEADERS:
            raise V(f"이 헤더 이름은 인증 헤더로 쓸 수 없습니다: {header}")
        key, restored = _secret(raw.get("key"), prev.get("key"), "API Key", header=True, same_type=same_type)
        if not key:
            raise V("API Key 값이 비어 있습니다")
        out.update(header=header, key=key)
    elif t == "bearer":
        key, restored = _secret(raw.get("key"), prev.get("key"), "Bearer 토큰", header=True, same_type=same_type)
        if not key:
            raise V("Bearer 토큰이 비어 있습니다")
        out["key"] = key
    elif t == "oauth2":
        out["token_url"] = _url(raw.get("token_url"), "토큰 URL")
        cid = _str(raw.get("client_id"), MAX_CLIENT_ID, "Client ID")
        if not cid:
            raise V("Client ID가 비어 있습니다")
        if _CTRL_RX.search(cid):
            raise V("Client ID에 줄바꿈이나 제어 문자를 넣을 수 없습니다")
        secret, restored = _secret(raw.get("client_secret"), prev.get("client_secret"), "Client Secret", same_type=same_type)
        if not secret:
            raise V("Client Secret이 비어 있습니다")
        out.update(client_id=cid, client_secret=secret)
    return out, restored


def normalize_auth(raw, prev_auth: dict | None = None) -> dict:
    """인증 설정 검증 — 방식별 필수값만 남기고 나머지는 비운다 / validate auth; keep only the fields the type uses"""
    return _normalize_auth(raw, prev_auth)[0]


def _stored_auth(prev_auth) -> dict:
    """저장된 인증을 그대로(방식 밖 칸은 비움) / the stored auth as is, off-type fields blank"""
    prev = prev_auth if isinstance(prev_auth, dict) else {}
    t = prev.get("type") if prev.get("type") in AUTH_TYPES else "none"
    out = blank_auth(t)
    if t != "none":
        out.update({k: str(prev.get(k) or "") for k in ("header", "key", "token_url", "client_id", "client_secret")})
    return out


def _dest_origin(url: str) -> tuple:
    """주소의 origin(scheme, host, port) — {{base_url}} 치환 · localhost 재작성 뒤 / origin after substitution and the localhost rewrite"""
    try:
        u = httpx.URL(_resolve(url))
        return (u.scheme, u.raw_host.lower(), u.port or (443 if u.scheme == "https" else 80))
    except Exception:  # noqa: BLE001 — 해석할 수 없는 주소는 원문으로 비교 / unparsable addresses compare by text
        return ("?", str(url or ""))


def _same_destinations(new: dict, prev_cfg: dict) -> bool:
    """MCP · API · (OAuth) 토큰 주소의 origin 이 저장값과 같은지 / whether the MCP, API and (OAuth) token origins match the stored ones"""
    pm, pa, pauth = prev_cfg.get("mcp") or {}, prev_cfg.get("api") or {}, prev_cfg.get("auth") or {}
    if _dest_origin(new["mcp"]["url"]) != _dest_origin(pm.get("url") or ""):
        return False
    if _dest_origin(new["api"]["base_url"]) != _dest_origin(pa.get("base_url") or ""):
        return False
    if new["auth"]["type"] == "oauth2" and _dest_origin(new["auth"]["token_url"]) != _dest_origin(pauth.get("token_url") or ""):
        return False
    return True


def connection_config(raw, previous: dict | None = None) -> dict:
    """연결 부분만 검증 → {mcp:{url, timeout}, api:{base_url, timeout}, auth}. 가린 비밀은 previous(저장 레코드)에서 복원하되,
    MCP · API · 토큰 주소의 origin 이 저장값과 같을 때만(저장된 비밀이 새 주소로 가지 않게, 2026-09-29). previous 가 있을 때 auth 가
    빠지면 저장된 인증을 유지하고 같은 규칙을 적용한다.
    Validate the connection part. Masked secrets are restored from previous (the stored record) only while the MCP, API and
    token origins match the stored ones, so a stored secret never follows a new destination (2026-09-29). With previous given,
    a missing auth keeps the stored auth under the same rule."""
    if not isinstance(raw, dict):
        raise V("연결 설정은 객체여야 합니다")
    mcp_in, api_in = raw.get("mcp"), raw.get("api")
    if mcp_in is None:
        mcp_in = {}
    if api_in is None:
        api_in = {}
    if not isinstance(mcp_in, dict):
        raise V("MCP 설정은 객체여야 합니다")
    if not isinstance(api_in, dict):
        raise V("API 설정은 객체여야 합니다")
    prev_cfg = (previous or {}).get("config") or {}
    prev_auth = prev_cfg.get("auth") if isinstance(prev_cfg.get("auth"), dict) else None
    # MCP URL 은 뒤에 경로를 붙이지 않으므로 쿼리(?tenant=… 등)를 허용한다. API Base URL 만 no_query(2026-09-29)
    # Nothing is appended to the MCP URL, so a query (?tenant=… etc.) is allowed; only the API base URL is no_query (2026-09-29)
    out = {"mcp": {"url": _url(mcp_in.get("url"), "MCP 서버 URL"),
                   "timeout": _int_in(mcp_in.get("timeout"), TIMEOUT_MIN, TIMEOUT_MAX, TIMEOUT_DEFAULT, "MCP 타임아웃")},
           "api": {"base_url": _url(api_in.get("base_url"), "API Base URL", strip_slash=True, no_query=True),
                   "timeout": _int_in(api_in.get("timeout"), TIMEOUT_MIN, TIMEOUT_MAX, TIMEOUT_DEFAULT, "API 타임아웃")}}
    if raw.get("auth") is None and previous is not None:
        out["auth"] = _stored_auth(prev_auth)   # auth 가 빠지면 저장값 유지 / a missing auth keeps the stored one
        carried = bool(out["auth"]["key"] or out["auth"]["client_secret"])
    else:
        out["auth"], carried = _normalize_auth(raw.get("auth"), prev_auth)
    if carried and previous is not None and not _same_destinations(out, prev_cfg):
        raise V(DEST_CHANGED)
    return out


def _model_setting(raw, table: dict, default_type: str, what: str) -> dict:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise V(f"{what} 설정은 객체여야 합니다")
    kind = _choice(raw.get("type"), MODEL_TYPES, default_type, f"{what} 유형")
    return {"type": kind, "model": _choice(raw.get("model"), table[kind], table[kind][0], f"{what}({kind})")}


def _section(raw, what: str) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise V(f"{what} 설정은 객체여야 합니다")
    return raw


def default_settings() -> dict:
    return copy.deepcopy(DEFAULT_SETTINGS)


def normalize_settings(raw) -> dict:
    """데모 배포 설정 검증(구현 계약 2절) — 누락 키는 기본값, 범위 · 선택지 밖은 422 / missing keys default, bad values are 422"""
    if raw is None:
        return default_settings()
    if not isinstance(raw, dict):
        raise V("배포 설정(settings)은 객체여야 합니다")
    proc = _section(raw.get("processing"), "문서 처리")
    size = _int_in(proc.get("chunk_size"), 100, 8000, 800, "청크 크기")
    # 청크 겹침 기본값은 청크 크기보다 작게 / the default overlap stays below the chunk size
    overlap = _int_in(proc.get("chunk_overlap"), 0, 2000, min(100, size - 1), "청크 겹침")
    if overlap >= size:
        raise V("청크 겹침은 청크 크기보다 작아야 합니다")
    ret = _section(raw.get("retrieval"), "검색")
    sec = _section(raw.get("security"), "보안")
    return {
        "storage": _choice(raw.get("storage"), STORAGES, "on_prem", "문서 저장소"),
        "vector_db": _choice(raw.get("vector_db"), VECTOR_DBS, "milvus", "벡터 DB"),
        "embedding": _model_setting(raw.get("embedding"), EMBEDDING_MODELS, "local", "임베딩 모델"),
        "llm": _model_setting(raw.get("llm"), LLM_MODELS, "local", "LLM 모델"),
        "processing": {"chunk_size": size, "chunk_overlap": overlap,
                       "parser": _choice(proc.get("parser"), PARSERS, "layout", "문서 파서")},
        "retrieval": {"top_k": _int_in(ret.get("top_k"), 1, 50, 5, "Top K"),
                      "threshold": _float_in(ret.get("threshold"), 0.0, 1.0, 0.35, "유사도 임계값"),
                      "reranker": _choice(ret.get("reranker"), RERANKERS, "bge-reranker", "리랭커")},
        "security": {"network": _choice(sec.get("network"), NETWORKS, "private", "네트워크 보안")},
    }


def _server_info(v) -> dict:
    if not isinstance(v, dict):
        return {}
    return {k: str(v[k])[:120] for k in ("name", "version", "protocol") if v.get(k) is not None}


def normalize(raw, previous: dict | None = None) -> dict:
    """에이전트 레코드 검증 · 정규화(구현 계약 3절) → {name, description, enabled, config, skill_ids}. 이름 중복(409)은 저장 때 본다.
    Validate and normalize one agent (contract section 3). The duplicate-name check (409) runs at save time.
    PUT(previous 있음)에서 mcp.tools · server_info · fetched_at · settings · auth · enabled 가 빠지면 저장값을 유지한다.
    이름은 NFC 로 맞춰 저장한다(같은 글자의 조합형 · 완성형이 다른 이름이 되지 않게).
    On PUT (previous given) a missing mcp.tools, server_info, fetched_at, settings, auth or enabled keeps the stored value.
    Names are stored in NFC so composed and decomposed spellings of the same text are one name."""
    if not isinstance(raw, dict):
        raise V("지식 에이전트 설정은 객체여야 합니다")
    name_in = raw.get("name")
    name = _str(unicodedata.normalize("NFC", name_in) if isinstance(name_in, str) else name_in, MAX_NAME, "에이전트 이름")
    if not name:
        raise V("에이전트 이름이 비어 있습니다")
    desc = _str(raw.get("description"), MAX_DESC, "설명")
    enabled = _bool(raw.get("enabled"), bool(previous.get("enabled", True)) if previous else True, "사용 여부")
    conn = connection_config(raw, previous)
    prev_cfg = (previous or {}).get("config") or {}
    prev_mcp = prev_cfg.get("mcp") or {}
    mcp_in = raw.get("mcp") if isinstance(raw.get("mcp"), dict) else {}
    if mcp_in.get("tools") is None:
        tools = copy.deepcopy(prev_mcp.get("tools") or [])
    else:
        try:
            tools = mcp_servers.normalize_tools(mcp_in.get("tools"), "mcp.tools")
        except ConnectorValidationError as e:
            raise V(str(e))
    info = _server_info(mcp_in["server_info"]) if "server_info" in mcp_in else _server_info(prev_mcp.get("server_info"))
    fetched = _str(mcp_in.get("fetched_at"), 40, "fetched_at") if "fetched_at" in mcp_in else str(prev_mcp.get("fetched_at") or "")[:40]
    if raw.get("settings") is None and previous is not None:
        settings = normalize_settings(prev_cfg.get("settings"))
    else:
        settings = normalize_settings(raw.get("settings"))
    try:
        skill_ids = skill_files.parse_ids(raw.get("skill_ids"))   # None = 그대로 / None keeps the current files
    except skill_files.SkillFileError as e:
        raise V(str(e))
    return {"name": name, "description": desc, "enabled": enabled,
            "config": {"mcp": {**conn["mcp"], "tools": tools, "server_info": info, "fetched_at": fetched},
                       "api": conn["api"], "auth": conn["auth"], "settings": settings},
            "skill_ids": skill_ids}


# ────────────────────────────────────────────────────────
# 응답 레코드 / payload records
# ────────────────────────────────────────────────────────

def blank_status() -> dict:
    return {"state": "unchecked", "checked_at": None, "mcp_ok": None, "api_ok": None, "doc_count": None, "error": "", "checks": []}


def _status(agent: dict) -> dict:
    st = blank_status()
    stored = agent.get("status") if isinstance(agent.get("status"), dict) else {}
    st.update({k: stored[k] for k in st if k in stored})
    return st


def _settings(agent: dict) -> dict:
    try:
        return normalize_settings(((agent.get("config") or {}).get("settings")))
    except KnowledgeAgentValidationError:   # 옛 · 손상된 값은 기본값으로 보여 준다 / legacy or damaged values show the defaults
        return default_settings()


def editor_record(agent: dict) -> dict:
    """슈퍼관리자용 편집 레코드(구현 계약 3절) — 인증 키 · Client Secret 은 가린다 / super-admin payload with masked secrets"""
    cfg = agent.get("config") or {}
    mcp, api = cfg.get("mcp") or {}, cfg.get("api") or {}
    auth = {**blank_auth(), **(cfg.get("auth") or {})}
    auth["key"] = SECRET_MASK if auth.get("key") else ""
    auth["client_secret"] = SECRET_MASK if auth.get("client_secret") else ""
    return {"id": agent["id"], "name": agent["name"], "description": agent.get("description") or "",
            "enabled": bool(agent.get("enabled")), "pos": int(agent.get("pos") or 0),
            "mcp": {"url": mcp.get("url") or "", "timeout": int(mcp.get("timeout") or TIMEOUT_DEFAULT),
                    "tools": copy.deepcopy(mcp.get("tools") or []),
                    "server_info": copy.deepcopy(mcp.get("server_info")) or None, "fetched_at": mcp.get("fetched_at") or None},
            "api": {"base_url": api.get("base_url") or "", "timeout": int(api.get("timeout") or TIMEOUT_DEFAULT)},
            "auth": auth, "settings": _settings(agent), "status": _status(agent),
            "skills": skill_files.list_for(SKILL_OWNER, agent["id"]),
            "level": 2, "created_at": agent.get("created_at"), "updated_at": agent.get("updated_at")}


def public_record(agent: dict, level: int) -> dict:
    """구성원용 공개 레코드 — 주소 · 인증 · 도구 없음 / member payload without URLs, auth or tools"""
    st = _status(agent)
    return {"id": agent["id"], "name": agent["name"], "description": agent.get("description") or "",
            "enabled": bool(agent.get("enabled")), "level": int(level), "pos": int(agent.get("pos") or 0),
            "settings": _settings(agent),
            "status": {k: st[k] for k in ("state", "checked_at", "mcp_ok", "api_ok", "doc_count")}}


# ────────────────────────────────────────────────────────
# 저장 / persistence
# ────────────────────────────────────────────────────────

def _name_key(name) -> str:
    """이름 비교 키 — NFC + casefold(SQLite lower() 는 ASCII 만 바꾼다) / NFC + casefold (SQLite lower() only folds ASCII)"""
    return unicodedata.normalize("NFC", str(name or "")).casefold()


def _check_unique_name(conn: sqlite3.Connection, name: str, exclude_id: str | None = None) -> None:
    key = _name_key(name)
    for r in conn.execute("SELECT id, name FROM knowledge_agents").fetchall():
        if r["id"] != (exclude_id or "") and _name_key(r["name"]) == key:
            raise KnowledgeAgentConflictError(f"같은 이름의 지식 에이전트가 이미 있습니다: {name}")


def _skills_check(ids: list[str], agent_id: str | None) -> None:
    try:
        skill_files.ensure_attachable(ids, SKILL_OWNER, agent_id)
    except skill_files.SkillFileError as e:
        raise V(str(e))


def _conn_sig(cfg: dict) -> str:
    """연결 서명(주소 · 인증) — 바뀌면 이전 연결 확인 결과는 무효 / connection signature; a change voids the last check"""
    cfg = cfg or {}
    return json.dumps([(cfg.get("mcp") or {}).get("url"), (cfg.get("api") or {}).get("base_url"), cfg.get("auth") or {}],
                      sort_keys=True, ensure_ascii=False)


def create(raw: dict) -> dict:
    d = normalize(raw)
    ids = d["skill_ids"] or []
    _skills_check(ids, None)
    aid = ID_PREFIX + uuid.uuid4().hex[:8]
    now = _now()
    with _tx() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM knowledge_agents").fetchone()["n"]
        if n >= MAX_AGENTS:
            raise V(f"지식 에이전트는 최대 {MAX_AGENTS}개까지 등록할 수 있습니다")
        _check_unique_name(conn, d["name"])
        pos = conn.execute("SELECT COALESCE(MAX(pos), -1) + 1 AS p FROM knowledge_agents").fetchone()["p"]
        conn.execute("INSERT INTO knowledge_agents(id, name, description, enabled, config, status, pos, created_at, updated_at)"
                     " VALUES(?,?,?,?,?,?,?,?,?)",
                     (aid, d["name"], d["description"], 1 if d["enabled"] else 0, json.dumps(d["config"], ensure_ascii=False),
                      json.dumps(blank_status(), ensure_ascii=False), pos, now, now))
    skill_files.attach(SKILL_OWNER, aid, ids)   # 올려 둔 Skill 파일을 붙인다 / attach the uploaded skill files
    return get_agent(aid)


def update(agent_id: str, raw: dict) -> dict | None:
    prev = get_agent(agent_id)
    if prev is None:
        return None
    d = normalize(raw, prev)
    ids = d["skill_ids"]   # None = 파일 목록 유지 / None keeps the files
    if ids is not None:
        _skills_check(ids, agent_id)
    # 주소 · 인증이 바뀌면 연결 확인 결과를 미확인으로 되돌린다 / a changed URL or auth resets the check to unchecked
    status = prev.get("status") if _conn_sig(d["config"]) == _conn_sig(prev.get("config")) else blank_status()
    with _tx() as conn:
        if conn.execute("SELECT 1 FROM knowledge_agents WHERE id=?", (agent_id,)).fetchone() is None:
            return None
        _check_unique_name(conn, d["name"], agent_id)
        conn.execute("UPDATE knowledge_agents SET name=?, description=?, enabled=?, config=?, status=?, updated_at=? WHERE id=?",
                     (d["name"], d["description"], 1 if d["enabled"] else 0, json.dumps(d["config"], ensure_ascii=False),
                      json.dumps(status or blank_status(), ensure_ascii=False), _now(), agent_id))
    if ids is not None:
        skill_files.attach(SKILL_OWNER, agent_id, ids)
    drop_tokens(agent_id)
    return get_agent(agent_id)


def delete(agent_id: str) -> bool:
    """에이전트 삭제 — 스킬 파일도 함께, 권한 grant 는 건드리지 않는다(고아 grant 는 무해) / skill files go too; grants stay"""
    with _tx() as conn:
        n = conn.execute("DELETE FROM knowledge_agents WHERE id=?", (agent_id,)).rowcount
    if n > 0:
        skill_files.delete_for(SKILL_OWNER, agent_id)
        drop_tokens(agent_id)
    return n > 0


# ────────────────────────────────────────────────────────
# 연결 확인 항목 / connection checklist
# ────────────────────────────────────────────────────────

def build_checks(mcp_error: str, tool_names, sources: tuple[bool, str] | None,
                 health_error: str, capabilities, list_error: str, doc_count: int | None) -> list[dict]:
    """기능 점검표 10행(순서 고정). MCP 3종 = 도구 존재, sources = kb_chat 출력, api_list = 실제 목록 호출, 나머지 = /health capabilities.
    The fixed 10-row checklist: tool presence, sources in kb_chat's output, a real list call, then /health capabilities."""
    names = set(tool_names or ())
    caps = {str(c).lower() for c in capabilities or ()}
    out: list[dict] = []
    for key, tool in MCP_TOOL_CHECKS:
        if mcp_error:
            ok, detail = False, mcp_error
        elif tool in names:
            ok, detail = True, "도구가 있습니다"
        else:
            ok, detail = False, "도구가 없습니다"
        out.append({"key": key, "group": "mcp", "ok": ok, "target": tool, "detail": detail})
    if mcp_error:
        ok, detail = False, mcp_error
    elif "kb_chat" not in names:
        ok, detail = False, "kb_chat 도구가 없습니다"
    else:
        ok, detail = sources if sources else (False, "출력에 sources 가 없습니다")
    out.append({"key": "mcp_sources", "group": "mcp", "ok": ok, "target": "kb_chat", "detail": detail})
    if list_error:
        out.append({"key": "api_list", "group": "api", "ok": False, "target": "GET /documents", "detail": list_error})
    else:
        out.append({"key": "api_list", "group": "api", "ok": True, "target": "GET /documents", "detail": f"문서 {int(doc_count or 0)}건"})
    for key, cap, target in API_CAP_CHECKS:
        if health_error:
            ok, detail = False, health_error
        elif cap in caps:
            ok, detail = True, "지원합니다"
        else:
            ok, detail = False, f"/health 의 capabilities 에 {cap} 이(가) 없습니다"
        out.append({"key": key, "group": "api", "ok": ok, "target": target, "detail": detail})
    return out


def _first_failure(checks: list[dict], group: str) -> str:
    c = next((c for c in checks if c["group"] == group and not c["ok"]), None)
    return f"{c['target']}: {c['detail']}" if c else ""


# ────────────────────────────────────────────────────────
# 시드 / seed
# ────────────────────────────────────────────────────────

def _merge_tools(discovered: list[dict], previous_tools) -> list[dict]:
    """가져온 도구에 관리자 설정(사용 여부 등)을 입히고 하나씩 검증(이상한 도구 1개가 전체를 막지 않게).
    Merge admin settings into the fetched tools, validating one by one so a single odd tool never blocks the rest."""
    merged, _gone = mcp_servers.merge_tools(discovered, previous_tools if isinstance(previous_tools, list) else None)
    out: list[dict] = []
    for t in merged:
        try:
            out.extend(mcp_servers.normalize_tools([t]))
        except ConnectorValidationError:
            logger.info("지식 에이전트 도구 명세 건너뜀: %s", t.get("name"))
    return out[:mcp_servers.MAX_TOOLS]


def _seed_record() -> dict:
    """본사 데모 에이전트(가상 고객 배포 hq) — 도구 · 서버 정보는 가상 서버 상수의 스냅샷, 상태는 확인 완료
    The head-office demo agent (fictional deployment hq): tools and server info snapshot the mock constants; status is ok."""
    from app import mock_kagent   # 지연 임포트(가상 서버 상수만 쓴다) / lazy import, constants only
    now = _now()
    tools = _merge_tools([t for t in (mcp_client.normalize_tool(x) for x in mock_kagent.TOOLS) if t], None)
    info = _server_info({**mock_kagent.TENANTS["hq"]["server_info"], "protocol": mock_kagent.PROTOCOL})
    doc_count = mock_kagent.seed_count("hq")
    checks = build_checks("", [t["name"] for t in tools], (True, "출력 명세에 sources 가 있습니다"), "",
                          mock_kagent.CAPABILITIES, "", doc_count)
    config = {"mcp": {"url": "{{base_url}}/mock/kagent/hq/mcp", "timeout": TIMEOUT_DEFAULT, "tools": tools,
                      "server_info": info, "fetched_at": now},
              "api": {"base_url": "{{base_url}}/mock/kagent/hq/api/v1", "timeout": TIMEOUT_DEFAULT},
              "auth": {**blank_auth("bearer"), "key": mock_kagent.DEMO_KEY},
              "settings": default_settings()}
    status = {"state": "ok", "checked_at": now, "mcp_ok": True, "api_ok": True, "doc_count": doc_count, "error": "", "checks": checks}
    return {"id": SEED_ID, "name": SEED_NAME,
            "description": SEED_DESCRIPTION,
            "config": config, "status": status, "created_at": now}


def _seed_demo() -> None:
    """데모 에이전트 1회 시드 — meta 플래그 + INSERT OR IGNORE(두 서버가 동시에 기동해도 1개, 지운 뒤에는 다시 안 생긴다).
    Seed the demo agent once: meta flag + INSERT OR IGNORE (one copy even with two servers booting; never re-created)."""
    with closing(_conn()) as conn:
        if conn.execute("SELECT 1 FROM knowledge_agents_meta WHERE k=?", (SEED_FLAG,)).fetchone():
            return
    rec = _seed_record()
    with _tx() as conn:
        if conn.execute("SELECT 1 FROM knowledge_agents_meta WHERE k=?", (SEED_FLAG,)).fetchone():
            return
        conn.execute("INSERT OR IGNORE INTO knowledge_agents(id, name, description, enabled, config, status, pos, created_at, updated_at)"
                     " VALUES(?,?,?,1,?,?,0,?,?)",
                     (rec["id"], rec["name"], rec["description"], json.dumps(rec["config"], ensure_ascii=False),
                      json.dumps(rec["status"], ensure_ascii=False), rec["created_at"], rec["created_at"]))
        conn.execute("INSERT OR REPLACE INTO knowledge_agents_meta(k, v) VALUES(?, '1')", (SEED_FLAG,))


# ────────────────────────────────────────────────────────
# 에이전트 접속 / talking to an agent
# ────────────────────────────────────────────────────────

# (에이전트 id, 토큰 URL, client id, Client Secret 지문) → (토큰, 만료 시각). 지문이 들어 있어 비밀을 바꾸면 옛 토큰은 쓰이지 않는다.
# (agent id, token URL, client id, client-secret fingerprint) → (token, expiry); the fingerprint retires tokens fetched with an old secret.
_TOKENS: dict[tuple[str, str, str, str], tuple[str, float]] = {}
_TOKENS_LOCK = threading.Lock()


def drop_tokens(agent_id: str) -> None:
    """에이전트의 캐시된 OAuth 토큰 버리기(수정 · 삭제 때) / forget an agent's cached OAuth tokens (on update or delete)"""
    with _TOKENS_LOCK:
        for k in [k for k in _TOKENS if k[0] == (agent_id or "")]:
            del _TOKENS[k]


def _secret_fingerprint(secret: str) -> str:
    """캐시 키용 비밀 지문(되돌릴 수 없는 해시 앞 16자) / a one-way fingerprint of the secret for the cache key"""
    return hashlib.sha256(("kagent-token-cache:" + (secret or "")).encode("utf-8")).hexdigest()[:16]


_LOCALHOST_RX = re.compile(r"^(https?://(?:[^@/?#]*@)?)localhost(?=[:/?#]|$)", re.I)


def _resolve(url: str) -> str:
    """{{base_url}} 등 치환 + 호스트 localhost → 127.0.0.1(2026-09-29). Windows 에서 localhost 는 ::1 을 먼저 시도해 연결마다
    약 2초가 들었다. 루프백의 /mock/ 경로는 check_url 의 루프백 예외로 그대로 통과한다.
    Substitute {{base_url}} and friends, then rewrite a localhost host to 127.0.0.1 (2026-09-29): on Windows localhost tries ::1
    first and cost about 2 s per connection. Loopback /mock/ paths still pass through check_url's loopback exception."""
    target = flow_api_call.substitute(url or "", flow_api_call.build_ctx()).strip()
    return _LOCALHOST_RX.sub(r"\g<1>127.0.0.1", target, count=1)


_SSL_CONTEXT: ssl.SSLContext | None = None
_SSL_LOCK = threading.Lock()


def _ssl_context() -> ssl.SSLContext:
    """모듈 공용 SSL 컨텍스트(httpx 기본과 같은 인증서 검증). 클라이언트마다 새로 만들면 0.2~0.5초가 든다.
    One shared SSL context (the same verification as httpx's default); building one per client costs 0.2 to 0.5 s."""
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        with _SSL_LOCK:
            if _SSL_CONTEXT is None:
                _SSL_CONTEXT = httpx.create_ssl_context()
    return _SSL_CONTEXT


def _error_detail(body: bytes) -> str:
    """오류 응답에서 사람이 읽을 문장(자르지 않는다 — 비밀을 먼저 가린 뒤 AgentLink.detail 이 자른다).
    A readable sentence from an error reply, uncut: AgentLink.detail redacts first, then truncates."""
    text = body.decode("utf-8", errors="replace") if body else ""
    try:
        j = json.loads(text) if text else None
    except ValueError:
        j = None
    if isinstance(j, dict):
        err = j.get("error")
        for cand in ((err or {}).get("message") if isinstance(err, dict) else None, j.get("error_description"),
                     j.get("detail") if isinstance(j.get("detail"), str) else None, j.get("message"),
                     err if isinstance(err, str) else None):
            if isinstance(cand, str) and cand.strip():
                return cand.strip()
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _deadline(timeout: int, floor: int = 0) -> float:
    """본문 전체 읽기 마감 시각(monotonic) = 지금 + max(타임아웃의 2배, floor) / total body-read deadline"""
    return time.monotonic() + max(2 * int(timeout or TIMEOUT_DEFAULT), floor)


def _read_capped(resp: httpx.Response, cap: int, deadline: float | None = None) -> bytes:
    """본문 읽기 — 크기 상한과 전체 마감 시각을 넘으면 AgentCallError / read the body within a size cap and a total deadline"""
    total, chunks = 0, []
    for chunk in resp.iter_bytes():
        total += len(chunk)
        if total > cap:
            raise AgentCallError("응답이 너무 큽니다")
        if deadline is not None and time.monotonic() > deadline:
            raise AgentCallError("응답이 제한 시간 안에 끝나지 않았습니다")
        chunks.append(chunk)
    return b"".join(chunks)


FRAGMENT_MIN = 8   # 진단 문장 끝에 잘려 남은 비밀 앞부분은 이 길이부터 가린다 / trailing secret prefixes from this length are masked


def _secret_forms(secret: str) -> list[str]:
    """비밀의 모든 표기 — 원문 · Base64 · JSON 이스케이프 · URL 인코딩(quote · quote_plus, 폼 본문을 되돌려 주는 서버 대비).
    Every spelling of a secret: raw, Base64, JSON-escaped and URL-encoded (quote and quote_plus, for servers echoing a form body)."""
    out: list[str] = []
    for form in (secret, base64.b64encode(secret.encode("utf-8")).decode("ascii"), json.dumps(secret)[1:-1],
                 quote(secret, safe=""), quote_plus(secret)):
        if form and form not in out:
            out.append(form)
    return out


def redact_diagnostic(text, secrets) -> str:
    """진단 · 오류 문장 전용 가림(2026-09-29) — 비밀의 모든 표기를 가리고, 앞 단계(MCP 클라이언트의 160 · 300자 자르기 등)에서
    잘려 문장 끝에 남은 앞부분(FRAGMENT_MIN 자 이상)도 가린다. 응답 데이터(json · outputs)에는 쓰지 않는다 — 평범한 값이 비밀의
    앞부분과 우연히 겹칠 수 있어서, 공용 flow_api_call.redact 는 정확한 일치만 가린다.
    Redaction for diagnostic and error sentences only (2026-09-29): every spelling of each secret is masked, plus a prefix of
    FRAGMENT_MIN+ characters left at the end of the sentence by an upstream cut (the MCP client's 160/300-character limits).
    Never used on response data (json, outputs): ordinary values can share a prefix with a secret, so the shared
    flow_api_call.redact keeps masking exact matches only."""
    s = str(text or "")
    for secret in secrets:
        if not secret:
            continue
        forms = _secret_forms(str(secret))
        for form in forms:
            s = s.replace(form, "••••••")
        for form in forms:
            for n in range(min(len(form) - 1, len(s)), FRAGMENT_MIN - 1, -1):
                if s.endswith(form[:n]):
                    s = s[:-n] + "••••••"
                    break
    return s


def _status_label(code: int) -> str:
    """2xx 가 아닌 응답 → 사유 머리말 / the reason prefix for a non-2xx reply"""
    if 300 <= code < 400:
        return f"리다이렉트는 따르지 않습니다(HTTP {code})"
    if code in (401, 403):
        return f"인증에 실패했습니다(HTTP {code})"
    return f"HTTP {code}"


class AgentLink:
    """에이전트 1개와의 연결(주소 · 인증 · 토큰 · 비밀 가림) / one agent connection (URLs, auth, token, redaction)"""

    def __init__(self, agent_id: str, cfg: dict, *, transport=None, cache_token: bool = True):
        self.agent_id = agent_id or ""
        self.mcp = cfg.get("mcp") or {}
        self.api = cfg.get("api") or {}
        self.auth = {**blank_auth(), **(cfg.get("auth") or {})}
        self.transport = transport if transport is not None else DEFAULT_TRANSPORT
        self.cache_token = cache_token
        self._token = ""

    # ── 비밀 가림 / redaction ──
    def redact(self, text, limit: int = 300) -> str:
        """진단 문장: 비밀을 먼저 가리고(모든 표기 · 끝에 잘려 남은 조각) 그 뒤에 자른다 / redact every spelling and trailing fragments first, then cut"""
        return redact_diagnostic(text, (self.auth.get("key"), self.auth.get("client_secret"), self._token))[:limit]

    def detail(self, body: bytes) -> str:
        """오류 본문 → 가린 뒤 160자 / an error body, redacted, then cut to 160 characters"""
        return self.redact(_error_detail(body), 160)

    def fail(self, reason: str, status: int | None = None) -> AgentCallError:
        return AgentCallError(self.redact(reason), status)

    # ── 주소 / URLs ──
    def url(self, raw: str) -> str:
        target = _resolve(raw)
        if not target:
            raise self.fail("주소가 비어 있습니다")
        try:
            flow_api_call.check_url(target)
        except ValueError as e:
            raise self.fail(str(e))
        return target

    def api_url(self, path: str) -> str:
        return self.url((self.api.get("base_url") or "").rstrip("/") + path)

    def client(self, timeout: int | None = None) -> httpx.Client:
        return httpx.Client(timeout=int(timeout or self.api.get("timeout") or TIMEOUT_DEFAULT), follow_redirects=False,
                            transport=self.transport, verify=_ssl_context())

    # ── 인증 / auth ──
    def token(self, force: bool = False) -> str:
        """OAuth client credentials 토큰 — 캐시(만료 30초 전까지) 또는 새로 발급 / cached (until 30 s before expiry) or fresh"""
        if self.auth["type"] != "oauth2":
            return ""
        url = self.url(self.auth["token_url"])
        key = (self.agent_id, url, self.auth["client_id"], _secret_fingerprint(self.auth["client_secret"]))
        now = time.time()
        if not force and self.cache_token:
            with _TOKENS_LOCK:
                hit = _TOKENS.get(key)
            if hit and now < hit[1] - TOKEN_SKEW_SEC:
                self._token = hit[0]
                return self._token
        timeout = int(self.api.get("timeout") or TIMEOUT_DEFAULT)
        try:
            with self.client(timeout) as c:
                r = c.post(url, data={"grant_type": "client_credentials", "client_id": self.auth["client_id"],
                                      "client_secret": self.auth["client_secret"]}, headers={"Accept": "application/json"})
        except httpx.TimeoutException:
            raise self.fail(f"OAuth 토큰 발급 실패: 시간 초과({timeout}초)")
        except httpx.HTTPError as e:
            raise self.fail(f"OAuth 토큰 발급 실패: 연결 실패({type(e).__name__})")
        if not 200 <= r.status_code < 300:
            detail = self.detail(r.content) if r.status_code >= 400 else ""
            raise self.fail("OAuth 토큰 발급 실패: " + _status_label(r.status_code) + (f" {detail}" if detail else ""))
        try:
            body = r.json()
        except ValueError:
            raise self.fail("OAuth 토큰 응답이 JSON 이 아닙니다")
        tok = body.get("access_token") if isinstance(body, dict) else None
        if not isinstance(tok, str) or not tok.strip() or _CTRL_RX.search(tok) or not tok.isascii():
            raise self.fail("OAuth 토큰 응답에 access_token 이 없습니다")
        try:
            ttl = int(body.get("expires_in") or 3600)
        except (TypeError, ValueError):
            ttl = 3600
        ttl = max(1, min(ttl, 86400))
        self._token = tok.strip()
        if self.cache_token:
            with _TOKENS_LOCK:
                _TOKENS[key] = (self._token, now + ttl)
        return self._token

    def _forget_token(self) -> None:
        self._token = ""
        if self.cache_token and self.auth["type"] == "oauth2":
            with _TOKENS_LOCK:
                for k in [k for k in _TOKENS if k[0] == self.agent_id and k[2] == self.auth["client_id"]]:
                    del _TOKENS[k]

    def headers(self) -> dict:
        t = self.auth["type"]
        if t == "api_key":
            return {self.auth.get("header") or "X-API-Key": self.auth["key"]}
        if t == "bearer":
            return {"Authorization": "Bearer " + self.auth["key"]}
        if t == "oauth2":
            return {"Authorization": "Bearer " + (self._token or self.token())}
        return {}

    # ── API ──
    def send(self, method: str, path: str, *, params=None, files=None, data=None) -> tuple[httpx.Response, httpx.Client]:
        """요청 1회(스트림으로 열어 둔다). OAuth 는 401 이면 토큰을 새로 받아 1번 더 / one streamed request; OAuth retries once on 401.
        상태 코드는 호출자가 본다. 돌려받은 응답 · 클라이언트는 호출자가 닫는다. / The caller checks the status and closes both."""
        url = self.api_url(path)
        timeout = int(self.api.get("timeout") or TIMEOUT_DEFAULT)
        for attempt in (0, 1):
            headers = {"Accept": "application/json, */*;q=0.5", **self.headers()}
            client = self.client(timeout)
            try:
                req = client.build_request(method, url, params=params, files=files, data=data, headers=headers)
                resp = client.send(req, stream=True)
            except httpx.TimeoutException:
                client.close()
                raise self.fail(f"시간 초과({timeout}초)")
            except httpx.HTTPError as e:
                client.close()
                raise self.fail(f"연결 실패({type(e).__name__})")
            if resp.status_code == 401 and attempt == 0 and self.auth["type"] == "oauth2":
                resp.close()
                client.close()
                self._forget_token()
                self.token(force=True)
                continue
            return resp, client
        raise self.fail("인증에 실패했습니다")   # 도달하지 않는다 / unreachable

    def call(self, method: str, path: str, *, params=None, files=None, data=None, cap: int = MAX_JSON_BYTES) -> tuple[int, bytes, httpx.Headers]:
        """요청 1회 → (상태, 본문, 헤더). 200~299 가 아니면 AgentCallError(status 포함) — 리다이렉트(3xx)는 따르지 않고 실패로 본다.
        One call → (status, body, headers). Anything outside 200-299 raises with the status; redirects (3xx) are failures."""
        deadline = _deadline(int(self.api.get("timeout") or TIMEOUT_DEFAULT))
        resp, client = self.send(method, path, params=params, files=files, data=data)
        try:
            body = _read_capped(resp, cap, deadline)
        except AgentCallError as e:
            raise self.fail(e.reason)
        except httpx.HTTPError as e:
            raise self.fail(f"응답을 읽지 못했습니다({type(e).__name__})")
        finally:
            resp.close()
            client.close()
        code = resp.status_code
        if not 200 <= code < 300:
            detail = self.detail(body) if code >= 400 else ""
            raise self.fail(_status_label(code) + (f": {detail}" if detail else ""), code)
        return code, body, resp.headers

    def get_json(self, path: str, params=None):
        _status, body, _headers = self.call("GET", path, params=params)
        try:
            return json.loads(body.decode("utf-8")) if body else None
        except (UnicodeDecodeError, ValueError):
            raise self.fail("응답이 올바른 JSON 이 아닙니다")

    # ── MCP ──
    def mcp_probe(self) -> tuple[dict, list[dict], tuple[bool, str] | None]:
        """MCP 접속 → (서버 정보, 가져온 도구(normalize_tool 모양), sources 판정). kb_chat 출력 명세에 sources 가 없으면
        kb_chat 을 한 번 불러 결과에서 확인한다. / connect → (server info, fetched tools, sources verdict); when kb_chat
        declares no sources in its output schema, one kb_chat call checks the actual result."""
        target = self.url(self.mcp.get("url") or "")
        headers = self.headers()
        timeout = int(self.mcp.get("timeout") or TIMEOUT_DEFAULT)
        try:
            with mcp_client.MCPClient(target, headers, timeout=timeout, transport=self.transport, verify=_ssl_context()) as client:
                raw_tools = client.list_tools()
                info = {"name": str(client.server_info.get("name") or "")[:120],
                        "version": str(client.server_info.get("version") or "")[:40], "protocol": client.protocol}
                discovered = [t for t in (mcp_client.normalize_tool(x) for x in raw_tools) if t]
                sources = self._sources(client, discovered)
        except mcp_client.MCPError as e:
            raise self.fail(str(e))
        except httpx.HTTPError as e:   # 본문 읽는 중 끊김 · 시간 초과(MCP 클라이언트 밖으로 샌다) / body-read errors escape the client
            raise self.fail(f"MCP 서버 응답을 읽지 못했습니다({type(e).__name__})")
        return info, discovered, sources

    def _sources(self, client: mcp_client.MCPClient, discovered: list[dict]) -> tuple[bool, str] | None:
        chat = next((t for t in discovered if t["name"] == "kb_chat"), None)
        if chat is None:
            return None
        props = ((chat.get("output_schema") or {}).get("properties")) or {}
        if isinstance(props, dict) and "sources" in props:
            return True, "출력 명세에 sources 가 있습니다"
        try:
            res = client.call_tool("kb_chat", {"question": "연결 확인", "top_k": 1})
        except mcp_client.MCPError as e:
            return False, self.redact(f"kb_chat 호출 실패: {e}")
        except httpx.HTTPError as e:
            return False, f"kb_chat 응답을 읽지 못했습니다({type(e).__name__})"
        data = mcp_client.result_to_common(res).get("json")
        if isinstance(data, dict) and isinstance(data.get("sources"), list):
            return True, "출력에 sources 가 있습니다"
        return False, "출력에 sources 가 없습니다"


def link_for(agent: dict, *, transport=None) -> AgentLink:
    """저장된 에이전트의 연결(토큰 캐시 사용) / the stored agent's connection (token cache on)"""
    cfg = agent.get("config") or {}
    return AgentLink(agent["id"], {"mcp": cfg.get("mcp"), "api": cfg.get("api"), "auth": cfg.get("auth")}, transport=transport)


# ────────────────────────────────────────────────────────
# 채팅 연동(2026-09-30) / chat integration
# ────────────────────────────────────────────────────────

def readable(eff: dict | None) -> list[dict]:
    """채팅 지식 답변에 함께 쓸 수 있는 로컬 지식 에이전트(2026-09-30) — 사용 중이고, 사용자가 그 에이전트의 잎(kl_*)을
    열람(1 이상)할 수 있는 것만 pos 순서로. eff=None = 슈퍼관리자(사용 중인 전부). 앵커(p_klocal)가 아니라 잎으로 판정하므로
    앵커 grant 가 있어도 에이전트 1개에 exclude 가 걸리면 그 에이전트는 빠진다(knowledge_agents_api._proxy_agent 의 열람 관문과 같은 뜻).
    Local knowledge agents that may join chat knowledge answers (2026-09-30): enabled ones whose leaf (kl_*) the user can view
    (level 1 or more), in pos order. eff=None is the super admin (every enabled agent). The leaf decides, not the p_klocal
    anchor, so an exclude on one agent drops it even under an anchor grant (the view gate of knowledge_agents_api._proxy_agent)."""
    nodes = None if eff is None else ((eff or {}).get("nodes") or {})
    out: list[dict] = []
    for a in list_agents():
        if not a.get("enabled"):
            continue
        if nodes is not None:
            try:
                level = int(nodes.get(a["id"], 0) or 0)
            except (TypeError, ValueError):
                level = 0
            if level < 1:
                continue
        out.append(a)
    return out


def call_tool(agent: dict, name: str, args: dict | None = None, *, timeout: int | None = None, transport=None) -> dict:
    """저장된 주소 · 인증으로 MCP 도구 1회 호출(2026-09-30, 채팅 로컬 지식 단계용) → {ok, json, error, elapsed_ms}.
    주소는 AgentLink.url(치환 · 사설망 관문), 헤더는 AgentLink.headers(Bearer · API Key · OAuth 캐시 토큰)를 그대로 쓴다.
    OAuth 토큰을 서버가 거부하면(HTTP 401) 새로 받아 1번만 다시 부른다(AgentLink.send 와 같은 규칙). json = structuredContent
    (없으면 JSON 텍스트), error = 비밀을 가린 한 줄(성공이면 None). 예외를 던지지 않는다.
    One MCP tool call with the stored URL and auth (2026-09-30, for the chat local-knowledge stage) → {ok, json, error,
    elapsed_ms}. The URL goes through AgentLink.url (substitution and the private-network gate) and the headers come from
    AgentLink.headers (bearer, API key or the cached OAuth token). A refused OAuth token (HTTP 401) is fetched again and the call
    retried once (the AgentLink.send rule). json = structuredContent (or the JSON text); error = a redacted one-liner (None on
    success). Never raises."""
    t0 = time.perf_counter()
    out: dict = {"ok": False, "json": None, "error": None, "elapsed_ms": 0}
    link = link_for(agent, transport=transport)
    try:
        wait = int(timeout or link.mcp.get("timeout") or TIMEOUT_DEFAULT)
    except (TypeError, ValueError):
        wait = TIMEOUT_DEFAULT
    wait = max(1, min(wait, TIMEOUT_MAX))
    try:
        target = link.url(link.mcp.get("url") or "")
        res = None
        for attempt in (0, 1):
            try:
                with mcp_client.MCPClient(target, link.headers(), timeout=wait, transport=link.transport,
                                          verify=_ssl_context()) as client:
                    res = client.call_tool(name, args or {})
                break
            except mcp_client.MCPError as e:
                if attempt == 0 and link.auth["type"] == "oauth2" and "HTTP 401" in str(e):
                    link._forget_token()
                    link.token(force=True)
                    continue
                raise link.fail(str(e))
        conv = mcp_client.result_to_common(res or {})
        out["json"] = conv.get("json")
        if conv.get("ok"):
            out["ok"] = True
        else:
            out["error"] = link.redact(conv.get("error") or "도구가 오류를 돌려주었습니다")
    except AgentCallError as e:
        out["error"] = e.reason
    except httpx.HTTPError as e:   # 본문 읽는 중 끊김 · 시간 초과(MCP 클라이언트 밖으로 샌다) / body-read errors escape the client
        out["error"] = f"MCP 서버 응답을 읽지 못했습니다({type(e).__name__})"
    out["elapsed_ms"] = mcp_client.elapsed_ms(t0)
    return out


# ────────────────────────────────────────────────────────
# 연결 확인 / connection check
# ────────────────────────────────────────────────────────

def check(config, previous: dict | None = None, *, agent_id: str = "", transport=None, cache_token: bool = False) -> dict:
    """연결 확인(구현 계약 3절) — 저장하지 않는다. config = {mcp:{url, timeout}, api:{base_url, timeout}, auth}, 가린 비밀은
    previous(저장 레코드)에서 복원. 업로드 · 삭제는 실제로 해 보지 않고 /health capabilities 로 판정한다.
    Connection check (contract section 3), nothing saved. Masked secrets are restored from previous (the stored record).
    Upload and delete are never exercised; /health capabilities decide them."""
    conn_cfg = connection_config(config, previous)
    prev_tools = (((previous or {}).get("config") or {}).get("mcp") or {}).get("tools")
    link = AgentLink(agent_id, conn_cfg, transport=transport, cache_token=cache_token)
    checked_at = _now()
    token_error = ""
    if conn_cfg["auth"]["type"] == "oauth2":
        try:
            link.token(force=True)   # 연결 확인은 항상 새 토큰으로 자격 증명을 검사한다 / the check always validates credentials afresh
        except AgentCallError as e:
            token_error = e.reason
    mcp_error, names, sources, info, tools = token_error, [], None, None, []
    if not token_error:
        try:
            info, discovered, sources = link.mcp_probe()
            names = [t["name"] for t in discovered]
            tools = _merge_tools(discovered, prev_tools)
        except AgentCallError as e:
            mcp_error = e.reason
    health_error = list_error = token_error
    version, caps, doc_count = "", [], None
    if not token_error:
        try:
            h = link.get_json("/health")
            if not isinstance(h, dict):
                raise link.fail("/health 응답 형식이 올바르지 않습니다")
            version = str(h.get("version") or "")[:40]
            raw_caps = h.get("capabilities")   # 배열일 때만 읽는다(문자열 · 객체를 돌면 글자 · 키가 기능이 된다) / lists only
            caps = [c.strip().lower()[:40] for c in (raw_caps if isinstance(raw_caps, list) else []) if isinstance(c, str)][:20]
        except AgentCallError as e:
            health_error = e.reason
        try:
            doc_count = len(_doc_list(link.get_json("/documents")))
        except AgentCallError as e:
            list_error = e.reason
    checks = build_checks(mcp_error, names, sources, health_error, caps, list_error, doc_count)
    mcp_ok = all(c["ok"] for c in checks if c["group"] == "mcp")
    api_ok = all(c["ok"] for c in checks if c["group"] == "api")
    return {"ok": mcp_ok and api_ok, "checked_at": checked_at,
            "mcp": {"ok": mcp_ok, "error": mcp_error or _first_failure(checks, "mcp"), "server_info": info, "tools": tools},
            "api": {"ok": api_ok, "error": health_error or list_error or _first_failure(checks, "api"), "version": version,
                    "capabilities": caps, "doc_count": doc_count},
            "checks": checks}


def check_saved(agent_id: str, *, transport=None) -> dict | None:
    """저장된 설정으로 연결 확인 후 상태 · 도구(사용 여부는 기존 값 유지) · 서버 정보 · 가져온 시각 저장 → 결과 + "agent".
    검사 도중 주소 · 인증이 바뀌었으면 결과를 저장하지 않는다. / Check with the stored config, then save status, tools (admin
    flags kept), server info and fetched time → result + "agent". Nothing is saved if the URL or auth changed meanwhile."""
    agent = get_agent(agent_id)
    if agent is None:
        return None
    cfg = agent.get("config") or {}
    res = check({"mcp": cfg.get("mcp"), "api": cfg.get("api"), "auth": cfg.get("auth")}, agent,
                agent_id=agent_id, transport=transport, cache_token=True)
    status = {"state": "ok" if res["ok"] else "error", "checked_at": res["checked_at"], "mcp_ok": res["mcp"]["ok"],
              "api_ok": res["api"]["ok"], "doc_count": res["api"]["doc_count"],
              "error": res["mcp"]["error"] or res["api"]["error"] or "", "checks": res["checks"]}
    with _tx() as conn:
        row = conn.execute("SELECT config FROM knowledge_agents WHERE id=?", (agent_id,)).fetchone()
        if row is not None:
            fresh = _loads(row["config"], {})
            if _conn_sig(fresh) == _conn_sig(cfg):
                if res["mcp"]["server_info"] is not None:   # MCP 에 접속했을 때만 도구 스냅샷을 바꾼다 / tools only change after a real fetch
                    fresh.setdefault("mcp", {})
                    fresh["mcp"]["tools"] = res["mcp"]["tools"]
                    fresh["mcp"]["server_info"] = res["mcp"]["server_info"]
                    fresh["mcp"]["fetched_at"] = res["checked_at"]
                conn.execute("UPDATE knowledge_agents SET config=?, status=? WHERE id=?",
                             (json.dumps(fresh, ensure_ascii=False), json.dumps(status, ensure_ascii=False), agent_id))
    saved = get_agent(agent_id)
    return {**res, "agent": editor_record(saved) if saved else None}


# ────────────────────────────────────────────────────────
# 문서 프록시 / document proxy
# ────────────────────────────────────────────────────────

_STATUS_ALIASES = {"processing": "processing", "pending": "processing", "queued": "processing", "indexing": "processing",
                   "running": "processing", "done": "done", "ready": "done", "completed": "done", "indexed": "done",
                   "success": "done", "failed": "failed", "fail": "failed", "error": "failed"}


def _norm_status(v) -> str:
    if v is None or (isinstance(v, str) and not v.strip()):
        return "done"
    return _STATUS_ALIASES.get(str(v).strip().lower(), "processing")


def _norm_doc(d, fallback: dict | None = None) -> dict | None:
    if not isinstance(d, dict):
        return None
    fb = fallback or {}
    did = d.get("id", fb.get("id"))
    if did is None or not str(did).strip():
        return None
    try:
        size = max(0, int(d.get("size", fb.get("size")) or 0))
    except (TypeError, ValueError):
        size = 0
    folder = d.get("folder_id") if d.get("folder_id") is not None else fb.get("folder_id")
    return {"id": str(did)[:200], "name": str(d.get("name") or d.get("title") or fb.get("name") or did)[:300],
            "folder_id": str(folder or "")[:200], "size": size,
            "mime": str(d.get("mime") or d.get("content_type") or fb.get("mime") or "")[:120],
            "status": _norm_status(d.get("status")), "updated_at": str(d.get("updated_at") or fb.get("updated_at") or "")[:40]}


def _doc_list(body) -> list[dict]:
    raw = body.get("documents") if isinstance(body, dict) else body
    if not isinstance(raw, list):
        raise AgentCallError("문서 목록 응답 형식이 올바르지 않습니다")
    return [d for d in (_norm_doc(x) for x in raw[:MAX_DOCS]) if d]


def _norm_folders(raw, depth: int = 0, budget: list | None = None) -> list[dict]:
    budget = budget if budget is not None else [MAX_FOLDERS]
    out: list[dict] = []
    if depth >= 8 or not isinstance(raw, list):
        return out
    for f in raw:
        if budget[0] <= 0:
            break
        if not isinstance(f, dict) or f.get("id") is None or not str(f.get("id")).strip():
            continue
        budget[0] -= 1
        out.append({"id": str(f["id"])[:200], "name": str(f.get("name") or f["id"])[:200],
                    "children": _norm_folders(f.get("children") or [], depth + 1, budget)})
    return out


def _doc_path(doc_id: str, suffix: str = "") -> str:
    d = str(doc_id or "")
    if not _DOC_ID_RX.match(d) or d in (".", ".."):
        raise AgentCallError("문서 id 형식이 올바르지 않습니다", 404)
    return "/documents/" + quote(d, safe="") + suffix


def list_folders(agent: dict, *, transport=None) -> list[dict]:
    link = link_for(agent, transport=transport)
    body = link.get_json("/folders")
    raw = body.get("folders") if isinstance(body, dict) else body
    if not isinstance(raw, list):
        raise link.fail("폴더 응답 형식이 올바르지 않습니다")
    return _norm_folders(raw)


def list_documents(agent: dict, folder_id: str | None = None, *, transport=None) -> list[dict]:
    """문서 목록 — folder_id 없음 = 에이전트 전체, 있으면 그 폴더 직속 / all documents, or one folder's direct documents"""
    link = link_for(agent, transport=transport)
    body = link.get_json("/documents", params={"folder_id": folder_id} if folder_id else None)
    try:
        return _doc_list(body)
    except AgentCallError as e:
        raise link.fail(e.reason)


def document_status(agent: dict, doc_id: str, *, transport=None) -> dict:
    link = link_for(agent, transport=transport)
    body = link.get_json(_doc_path(doc_id, "/status"))
    if not isinstance(body, dict):
        raise link.fail("상태 응답 형식이 올바르지 않습니다")
    # 에이전트가 준 문장은 구성원에게 보이므로 비밀을 가린 뒤 자른다 / the agent's message reaches members: redact, then cut
    return {"status": _norm_status(body.get("status")), "message": link.redact(str(body.get("message") or ""))}


def delete_document(agent: dict, doc_id: str, *, transport=None) -> None:
    link = link_for(agent, transport=transport)
    link.call("DELETE", _doc_path(doc_id))


def clean_filename(name) -> str:
    """업로드 파일 이름 — NFC, 경로 제거, 금지 문자 치환, 200자 / NFC, path stripped, forbidden characters replaced, 200 chars"""
    base = Path(unicodedata.normalize("NFC", str(name or "")).replace("\\", "/")).name
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]+', "_", base).strip().strip(".")
    if len(base) > 200:
        stem, dot, ext = base.rpartition(".")
        base = (stem[: 200 - len(ext) - 1] + "." + ext) if dot and len(ext) <= 10 else base[:200]
    return base


def file_ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in (name or "") else ""


def upload_document(agent: dict, filename: str, data: bytes, folder_id: str = "", *, transport=None) -> dict:
    """업로드 1건 중계 → 문서 레코드(에이전트가 {id, status} 만 주면 나머지는 올린 파일로 채운다).
    Relay one upload → a document record (when the agent returns only {id, status}, the rest comes from the upload)."""
    link = link_for(agent, transport=transport)
    mime = MIME_BY_EXT.get(file_ext(filename), "application/octet-stream")
    _status, body, _headers = link.call("POST", "/documents", files={"file": (filename, data, mime)},
                                        data={"folder_id": folder_id} if folder_id else None)
    try:
        j = json.loads(body.decode("utf-8")) if body else None
    except (UnicodeDecodeError, ValueError):
        raise link.fail("업로드 응답이 올바른 JSON 이 아닙니다")
    raw = j.get("document") if isinstance(j, dict) and isinstance(j.get("document"), dict) else j
    doc = _norm_doc(raw, {"name": filename, "folder_id": folder_id, "size": len(data), "mime": mime, "updated_at": _now()})
    if doc is None:
        raise link.fail("업로드 응답에 문서 id 가 없습니다")
    if not (isinstance(raw, dict) and raw.get("status")):
        doc["status"] = "processing"
    return doc


_CD_STAR = re.compile(r"filename\*\s*=\s*([^']*)'[^']*'([^;]+)", re.I)
_CD_PLAIN = re.compile(r'filename\s*=\s*(?:"([^"]*)"|([^;]+))', re.I)


def _disposition_name(header: str) -> str:
    """Content-Disposition 의 파일 이름(filename* 우선) / the file name from Content-Disposition (filename* first)"""
    if not header:
        return ""
    m = _CD_STAR.search(header)
    if m:
        try:
            return clean_filename(unquote(m.group(2).strip().strip('"'), encoding=(m.group(1) or "utf-8").strip() or "utf-8"))
        except (LookupError, ValueError):
            pass
    m = _CD_PLAIN.search(header)
    if m:
        return clean_filename((m.group(1) if m.group(1) is not None else m.group(2) or "").strip())
    return ""


def content_disposition(kind: str, name: str) -> str:
    """RFC 5987 Content-Disposition(ASCII 대체 이름 + filename*) / RFC 5987 header with an ASCII fallback and filename*"""
    name = clean_filename(name) or "document"
    ext = file_ext(name)
    if name.isascii() and not re.search(r'["\\;]', name):
        fallback = name
    else:
        fallback = "document." + ext if ext and ext.isascii() and ext.isalnum() else "document"
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"


class DocStream:
    """미리보기 · 다운로드 응답 스트림(끝나면 스스로 닫는다) / a preview/download stream that closes itself when done"""

    def __init__(self, resp: httpx.Response, client: httpx.Client, link: AgentLink, cap: int = MAX_PROXY_BYTES,
                 deadline: float | None = None):
        self.resp, self.client, self.link, self.cap = resp, client, link, cap
        self.deadline = deadline   # 본문 전체 마감 시각(monotonic) / total body deadline (monotonic)
        self.content_type = resp.headers.get("content-type") or ""
        self.filename = _disposition_name(resp.headers.get("content-disposition") or "")

    @property
    def mime(self) -> str:
        return self.content_type.split(";")[0].strip().lower()

    @property
    def charset(self) -> str:
        m = re.search(r"charset\s*=\s*\"?([\w.:-]+)", self.content_type, re.I)
        return m.group(1) if m else "utf-8"

    def iter_bytes(self):
        """동기 제너레이터 — 크기 상한 · 전체 마감 시각을 넘으면 중단(연결을 끊어 잘린 파일이 성공처럼 보이지 않게).
        Sync generator; aborts past the size cap or the total deadline (the connection drops, so a cut file never looks complete)."""
        total = 0
        try:
            for chunk in self.resp.iter_bytes(65536):
                total += len(chunk)
                if total > self.cap:
                    raise AgentCallError("파일이 너무 큽니다")
                if self.deadline is not None and time.monotonic() > self.deadline:
                    raise AgentCallError("응답이 제한 시간 안에 끝나지 않았습니다")
                yield chunk
        finally:
            self.close()

    def read(self, cap: int | None = None) -> bytes:
        try:
            return _read_capped(self.resp, cap or self.cap, self.deadline)
        except httpx.HTTPError as e:
            raise self.link.fail(f"응답을 읽지 못했습니다({type(e).__name__})")
        finally:
            self.close()

    def close(self) -> None:
        try:
            self.resp.close()
        finally:
            self.client.close()


def open_document(agent: dict, doc_id: str, kind: str, *, transport=None) -> DocStream:
    """미리보기(kind='preview') · 다운로드(kind='download') 스트림 열기. 200~299 가 아니거나(리다이렉트 포함) 204(본문 없음) ·
    상한 초과는 AgentCallError. / Open a preview or download stream; a status outside 200-299 (redirects included), 204 (no
    body) or an oversized Content-Length raises AgentCallError."""
    link = link_for(agent, transport=transport)
    timeout = int(link.api.get("timeout") or TIMEOUT_DEFAULT)
    deadline = _deadline(timeout, STREAM_DEADLINE_MIN)
    resp, client = link.send("GET", _doc_path(doc_id, "/preview" if kind == "preview" else "/download"))
    code = resp.status_code
    if not 200 <= code < 300 or code == 204:
        try:
            body = _read_capped(resp, 64 * 1024, _deadline(timeout)) if code >= 400 else b""
        except (AgentCallError, httpx.HTTPError):
            body = b""
        finally:
            resp.close()
            client.close()
        if code == 204:
            raise link.fail("에이전트가 빈 응답을 보냈습니다(HTTP 204)", code)
        detail = link.detail(body) if code >= 400 else ""
        raise link.fail(_status_label(code) + (f": {detail}" if detail else ""), code)
    try:
        length = int(resp.headers.get("content-length") or 0)
    except ValueError:
        length = 0
    if length > MAX_PROXY_BYTES:
        resp.close()
        client.close()
        raise link.fail("파일이 너무 큽니다")
    return DocStream(resp, client, link, deadline=deadline)


def decode_text(raw: bytes, charset: str = "utf-8") -> str:
    """텍스트 미리보기 본문 → str(선언된 문자셋, 실패하면 UTF-8 대체) / text preview bytes → str"""
    for enc in (charset or "utf-8", "utf-8"):
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")
