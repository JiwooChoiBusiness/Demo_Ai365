"""@도구 설정 — 도구(@) 단위 **사용 여부**만 영속화 (SQLite).

단일행 JSON blob(id=1), 키는 네임스페이스 5개(mail·calendar·teams·todo·sharepoint).
능력 카탈로그(키·표시명·실행수단·AI 지침)는 app/smart_catalog.py가 단일 출처이고,
이 모듈은 저장만 담당한다 — app/catalog.py ↔ app/access.py 관계와 같다.

**세부 능력도 프롬프트도 저장하지 않는다.** 관리자가 정하는 단위는 "이 도구를 쓸지"이고,
프롬프트는 응답 형식·필드명·렌더러와 함께 움직이는 구현 세부라 코드가 소유한다.

마이그레이션(멱등): 구형 키워드형·능력 단위(mail.new, mail.info.inbox 등) 저장분을 전부
도구 단위로 접는다. 한 도구의 능력이 **모두** 꺼져 있었으면 그 도구를 끈 것으로 본다.
"""
# @-tool settings — persists **per-tool (@) availability** only (SQLite).
#
# Single-row JSON blob (id=1) keyed by the five namespaces (mail, calendar, teams, todo, sharepoint).
# The capability catalog (keys, labels, execution paths, AI guidance) has its single source of truth in
# app/smart_catalog.py; this module only persists — mirroring the app/catalog.py <-> app/access.py relationship.
#
# **Neither individual capabilities nor prompts are stored.** What an admin decides is whether a tool is in
# play; prompts move with the response format, field names, and renderer, so code owns them.
#
# Idempotent migration: legacy keyword-shaped and per-capability entries (mail.new, mail.info.inbox, ...)
# are folded into per-tool entries. A tool counts as disabled only when *every* capability of it was off.

import json
import sqlite3

from app import kst
from app.db import DB_PATH
from app.smart_catalog import CONFIG_KEYS, DEFAULTS, ns_of_stored

__all__ = ["CONFIG_KEYS", "DEFAULTS", "init_smart_actions", "get_config", "put_config"]


def _now() -> str:
    return kst.now_iso()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _write(data: dict) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO smart_actions(id, data, updated) VALUES(1, ?, ?)",
            (json.dumps(data, ensure_ascii=False), _now()),
        )


def init_smart_actions() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS smart_actions(
              id INTEGER PRIMARY KEY CHECK(id = 1),
              data TEXT NOT NULL,
              updated TEXT NOT NULL
            )
            """
        )
        row = conn.execute("SELECT data FROM smart_actions WHERE id = 1").fetchone()
    if not row:
        _write(DEFAULTS)
        return
    try:
        data = json.loads(row["data"])
    except ValueError:
        data = {}
    if not isinstance(data, dict) or not data:
        _write(DEFAULTS)
        return
    # 능력 단위·키워드형 구형 저장분을 도구 단위로 접는다. 한 도구의 능력이 **모두** 꺼져 있었을
    # 때만 그 도구를 끈 것으로 본다 — 일부만 꺼 뒀던 설정이 도구 전체를 막아버리면 안 된다.
    # Fold legacy per-capability/keyword entries into per-tool ones. A tool is treated as disabled only
    # when *every* one of its capabilities was off — a partial opt-out must not silence the whole tool.
    folded, legacy = {}, False
    for k, v in data.items():
        if k in CONFIG_KEYS:
            folded.setdefault(k, False)
            folded[k] = folded[k] or (not isinstance(v, dict)) or (v.get("enabled") is not False)
            continue
        ns = ns_of_stored(k)
        legacy = True
        if not ns:
            continue
        on = (not isinstance(v, dict)) or (v.get("enabled") is not False)
        folded[ns] = folded.get(ns, False) or on
    out = {ns: {"enabled": folded.get(ns, True)} for ns in CONFIG_KEYS}
    if legacy or out != data:
        _write(out)


def get_config() -> dict:
    with _conn() as conn:
        row = conn.execute("SELECT data FROM smart_actions WHERE id = 1").fetchone()
    if not row:
        return json.loads(json.dumps(DEFAULTS, ensure_ascii=False))
    return json.loads(row["data"])


def put_config(actions: dict) -> dict:
    _write(actions)
    return actions
