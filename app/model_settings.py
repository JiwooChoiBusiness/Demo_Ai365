"""답변 모델 설정(관리 센터 > 토큰 설정, 2026-09-08).

관리자가 정하는 세 가지를 SQLite 한 행(JSON)에 영속한다.
  - default  : 새 채팅을 열 때 컴포저 모델 칸에 기본으로 들어갈 모델 — auto | gemini | claude | gpt
  - versions : 제공사별 "답변 버전" — 사용자가 그 제공사를 골랐을 때 답변한다고 표시할 버전(표시·저장 전용).
               실제 답변은 전부 Gemini 로 돈다(사용자 확정 2026-09-08 "실제는 gemini로만") — settings.GEN_MODEL_* 는 건드리지 않는다.
  - tokens   : 제공사별 총 토큰 한도(제한 없음/있음·한도)와 부서별 할당(이름·할당량). 사용량은 화면 시드값이라 저장하지 않는다.
응답 모양은 GET/PUT 이 같다: {default, versions, tokens, catalog, choices}.

Answer-model settings (Admin Center > Token Settings, 2026-09-08).

Three admin-controlled things persist in one SQLite row (JSON):
  - default  : the model pre-selected in the composer when a new chat opens — auto | gemini | claude | gpt
  - versions : per-provider "answer version" — the version shown as answering when a user picks that provider
               (display/persist only). Every real answer still runs on Gemini (user decision 2026-09-08);
               settings.GEN_MODEL_* is untouched.
  - tokens   : per-provider total limit (unlimited/limited + cap) and per-department allocations (name, alloc).
               Usage numbers are front-end seed values and are not stored.
GET and PUT share one response shape: {default, versions, tokens, catalog, choices}.
"""

from __future__ import annotations

import copy
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import db

router = APIRouter(prefix="/api/model-settings", tags=["model-settings"])

PROVIDERS = ("gemini", "claude", "gpt")
CHOICES = ("auto",) + PROVIDERS
# 표시용 버전 카탈로그 — 첫 항목이 기본값. GPT 목록은 사용자 지정(2026-09-08), Claude 는 캡처, Gemini 는 실제 체인.
# Display catalog — the first entry is the default. GPT names per the user (2026-09-08), Claude per the capture,
# Gemini mirrors the real fallback chain.
CATALOG: dict[str, list[str]] = {
    "gemini": ["gemini-3.7-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"],   # 2026-10-30 체인과 같게 / mirrors the 2026-10-30 chain
    "claude": ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-4-8", "claude-opus-5", "claude-fable-5"],
    "gpt": ["gpt-astra", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"],
}
MAX_DEPTS = 50
_KEY = "settings"


def _defaults() -> dict:
    return {"default": "auto", "versions": {p: CATALOG[p][0] for p in PROVIDERS}, "tokens": {}}


def init_model_settings() -> None:
    """상태 테이블 생성(멱등) / create the settings table (idempotent)"""
    with db._conn() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS model_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)")


def _load() -> dict:
    with db._conn() as conn:
        row = conn.execute("SELECT value FROM model_settings WHERE key = ?", (_KEY,)).fetchone()
    doc = _defaults()
    if not row:
        return doc
    try:
        saved = json.loads(row["value"])
    except ValueError:
        return doc
    if isinstance(saved, dict):
        if saved.get("default") in CHOICES:
            doc["default"] = saved["default"]
        vers = saved.get("versions") or {}
        for p in PROVIDERS:
            v = vers.get(p) if isinstance(vers, dict) else None
            if isinstance(v, str) and v.strip():
                doc["versions"][p] = v.strip()
        toks = saved.get("tokens") or {}
        if isinstance(toks, dict):
            doc["tokens"] = {p: copy.deepcopy(toks[p]) for p in PROVIDERS if isinstance(toks.get(p), dict)}
    return doc


def _save(doc: dict) -> None:
    payload = {"default": doc["default"], "versions": doc["versions"], "tokens": doc.get("tokens") or {}}
    with db._conn() as conn:
        conn.execute("INSERT OR REPLACE INTO model_settings(key, value) VALUES(?, ?)",
                     (_KEY, json.dumps(payload, ensure_ascii=False)))


def get_settings() -> dict:
    doc = _load()
    doc["catalog"] = copy.deepcopy(CATALOG)
    doc["choices"] = list(CHOICES)
    return doc


def _clean_tokens(raw: dict) -> dict:
    """제공사별 {limited, limit, depts:[{name, alloc}]} 만 남기고 숫자를 정규화 / keep the per-provider shape, normalize numbers"""
    out: dict[str, dict] = {}
    for p in PROVIDERS:
        t = raw.get(p)
        if not isinstance(t, dict):
            continue
        depts_in = t.get("depts") if isinstance(t.get("depts"), list) else []
        if len(depts_in) > MAX_DEPTS:
            raise HTTPException(status_code=422, detail="부서는 최대 50개까지 저장할 수 있습니다")
        depts = []
        for d in depts_in:
            if not isinstance(d, dict):
                continue
            name = str(d.get("name") or "").strip()[:80]
            if not name:
                continue
            try:
                alloc = max(0, int(d.get("alloc") or 0))
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail="할당 토큰은 숫자여야 합니다")
            depts.append({"name": name, "alloc": alloc})
        try:
            limit = max(0, int(t.get("limit") or 0))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="총 토큰 한도는 숫자여야 합니다")
        out[p] = {"limited": bool(t.get("limited")), "limit": limit, "depts": depts}
    return out


class ModelSettingsBody(BaseModel):
    default: str | None = None
    versions: dict[str, str] | None = None
    tokens: dict | None = None


@router.get("")
def read_settings() -> dict:
    return get_settings()


@router.put("")
def write_settings(body: ModelSettingsBody) -> dict:
    """부분 갱신 — 보낸 필드만 바꾼다 / partial update — only the fields sent are changed"""
    doc = _load()
    if body.default is not None:
        if body.default not in CHOICES:
            raise HTTPException(status_code=422, detail="기본 모델은 auto·gemini·claude·gpt 중 하나여야 합니다")
        doc["default"] = body.default
    if body.versions is not None:
        for p, v in body.versions.items():
            if p not in PROVIDERS:
                raise HTTPException(status_code=422, detail=f"알 수 없는 모델입니다: {p}")
            v = (v or "").strip()
            if not v or len(v) > 80:
                raise HTTPException(status_code=422, detail="답변 버전이 비어 있습니다")
            doc["versions"][p] = v
    if body.tokens is not None:
        doc["tokens"] = _clean_tokens(body.tokens)
    _save(doc)
    return get_settings()
