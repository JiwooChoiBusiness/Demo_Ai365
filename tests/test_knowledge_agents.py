# -*- coding: utf-8 -*-
"""로컬 지식 에이전트(2026-09-29) — 정규화 규칙 · 비밀 가림 왕복 · 시드 · 슈퍼 전용 쓰기 · 목록 필터 · 권한 유니버스(p_klocal) ·
팀장 앵커 · Local 만 가진 사용자 · 연결 확인(Bearer · API Key · OAuth, 전송 주입) · 문서 프록시 · OAuth 토큰 캐시 · og9 이관.
임시 DB, 네트워크 · LLM 없음. 실 DB 에 쓰지 않는다(그룹 저장은 가짜로 바꾼다), 가상 배포는 앱 안 라우터로만 부른다.

Local knowledge agents (2026-09-29): normalization, masking round trips, seed, super-only writes, list filtering, the
permission universe (p_klocal), the team-lead anchor, Local-only users, connection checks (bearer, API key, OAuth via an
injected transport), the document proxy, the OAuth token cache and the og9 migration. Temp DB; no network or LLM; nothing
is written to the real DB (group writes are faked) and the fictional deployment is only reached through the in-app router."""
import base64
import copy
import json
import os
import sqlite3
import tempfile
import time
import unicodedata
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import quote, quote_plus

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import access, catalog, connectors, flow_api_call, knowledge_agents as ka, knowledge_agents_api as kapi, mock_kagent as mk, skill_files
from tests.db_fixture import isolate_db
from tests.test_mock_kagent import mock_transport

BASE = "{{base_url}}/mock/kagent"
MASK = connectors.SECRET_MASK
CHECK_KEYS = ["mcp_chat", "mcp_search", "mcp_get_document", "mcp_sources", "api_list", "api_upload", "api_preview",
              "api_download", "api_delete", "api_status"]
EDITOR_KEYS = {"id", "name", "description", "enabled", "pos", "mcp", "api", "auth", "settings", "status", "skills", "level",
               "created_at", "updated_at"}
LAB_SETTINGS = {"storage": "on_prem", "vector_db": "chroma", "embedding": {"type": "local", "model": "multilingual-e5-large"},
                "llm": {"type": "local", "model": "qwen-3.5-4b"},
                "processing": {"chunk_size": 600, "chunk_overlap": 80, "parser": "ocr"},
                "retrieval": {"top_k": 8, "threshold": 0.3, "reranker": "none"}, "security": {"network": "vpn"}}
OAUTH = {"type": "oauth2", "token_url": f"{BASE}/lab/oauth/token", "client_id": mk.OAUTH_CLIENT_ID,
         "client_secret": mk.OAUTH_CLIENT_SECRET}
V = ka.KnowledgeAgentValidationError


def body(**over) -> dict:
    d = {"name": "연구소 지식 에이전트", "description": "연구 과제와 실험 매뉴얼", "enabled": True,
         "mcp": {"url": f"{BASE}/lab/mcp", "timeout": 20}, "api": {"base_url": f"{BASE}/lab/api/v1", "timeout": 20},
         "auth": {"type": "bearer", "key": mk.DEMO_KEY}, "settings": copy.deepcopy(LAB_SETTINGS)}
    d.update(over)
    return d


def echo(rec: dict, **over) -> dict:
    """편집 레코드를 그대로 되돌려 보내는 PUT 본문(가린 비밀 포함) / a PUT body echoing the editor record (masked secrets included)"""
    d = {k: copy.deepcopy(rec[k]) for k in ("name", "description", "enabled", "mcp", "api", "auth", "settings")}
    d.update(over)
    return d


def member(nodes: dict) -> dict:
    return {"no": 7, "menus": {}, "nodes": nodes, "mgmt": {}, "read": {}}


class _DbCase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        # 정리 순서: 임시 DB 를 닫은 뒤 유니버스를 다시 만든다(실 DB 는 읽기만) / cleanup order: close the temp DB, then rebuild (read-only)
        self.addCleanup(access.rebuild_universe)
        self.addCleanup(self.stack.close)
        self.path = isolate_db(self.stack)
        # {{base_url}} 은 쓰지 않는 포트로 — 전송 주입을 빠뜨려도 사용자 서버(8000 · 8010)에 닿지 않는다
        # {{base_url}} points at an unused port, so a missing transport can never reach the user's servers (8000, 8010)
        self.stack.enter_context(patch.dict(os.environ, {"AI365_BASE_URL": "http://localhost:65531"}))
        ka._TOKENS.clear()
        self.addCleanup(ka._TOKENS.clear)


class NormalizeTests(unittest.TestCase):
    def assertRejects(self, raw, needle, fn=ka.normalize):
        with self.assertRaises(V, msg=needle) as ctx:
            fn(raw)
        self.assertIn(needle, str(ctx.exception))

    def test_required_fields_urls_and_timeouts(self):
        for raw, needle in ((body(name=""), "이름이 비어"), (body(name="가" * 41), "40자"), (body(description="x" * 201), "200자"),
                            (body(mcp={}), "MCP 서버 URL"), (body(mcp={"url": "ftp://kms"}), "http"),
                            (body(mcp="x"), "MCP 설정"), (body(api={"base_url": ""}), "API Base URL"),
                            (body(api={"base_url": "kms.example.com/api"}), "{{base_url}}"),
                            (body(mcp={"url": "https://kms/mcp", "timeout": 4}), "5~120"),
                            (body(api={"base_url": "https://kms/api", "timeout": 121}), "5~120"),
                            (body(mcp={"url": "https://kms/mcp", "timeout": "abc"}), "5~120"),
                            (body(api={"base_url": "https://kms/api", "timeout": True}), "5~120"),
                            (body(mcp={"url": "https://kms/m\ncp"}), "제어 문자"), (body(mcp={"url": "https://" + "a" * 500}), "500자"),
                            (body(enabled="yes"), "true 또는 false"), ([], "객체")):
            self.assertRejects(raw, needle)
        d = ka.normalize(body(mcp={"url": "https://kms.example.com/mcp"}, api={"base_url": "https://kms.example.com/api/v1/"}))
        self.assertEqual(d["config"]["mcp"], {"url": "https://kms.example.com/mcp", "timeout": 30, "tools": [], "server_info": {}, "fetched_at": ""})
        self.assertEqual(d["config"]["api"], {"base_url": "https://kms.example.com/api/v1", "timeout": 30})   # 끝의 / 정리 / trailing slash trimmed
        self.assertEqual(ka.normalize(body())["config"]["mcp"]["url"], f"{BASE}/lab/mcp")   # {{base_url}} 시작 허용 / allowed
        self.assertEqual(ka.normalize(body(enabled=None))["enabled"], True)
        self.assertIsNone(ka.normalize(body())["skill_ids"])

    def test_auth_rules_per_type(self):
        for auth, needle in (({"type": "basic", "key": "k"}, "인증 방식"), ({"type": "api_key"}, "API Key"),
                             ({"type": "api_key", "key": "k", "header": "X Bad"}, "헤더 이름"), ({"type": "bearer", "key": ""}, "Bearer 토큰"),
                             ({"type": "bearer", "key": "a\nb"}, "제어 문자"), ({"type": "bearer", "key": MASK}, "저장된"),
                             ({"type": "oauth2", "client_id": "c", "client_secret": "s"}, "토큰 URL"),
                             ({"type": "oauth2", "token_url": "https://t/token", "client_secret": "s"}, "Client ID"),
                             ({"type": "oauth2", "token_url": "https://t/token", "client_id": "c"}, "Client Secret"),
                             ({"type": "oauth2", "token_url": "ftp://t", "client_id": "c", "client_secret": "s"}, "토큰 URL"),
                             ("bearer", "인증 설정")):
            self.assertRejects(body(auth=auth), needle)
        self.assertEqual(ka.normalize(body(auth={"type": "api_key", "key": " k1 "}))["config"]["auth"],
                         {"type": "api_key", "header": "X-API-Key", "key": "k1", "token_url": "", "client_id": "", "client_secret": ""})
        o = ka.normalize(body(auth={**OAUTH, "key": "stray", "header": "X-Ignored"}))["config"]["auth"]
        self.assertEqual((o["key"], o["header"], o["client_id"]), ("", "", mk.OAUTH_CLIENT_ID))   # 방식 밖 값은 버린다 / off-type fields dropped
        self.assertEqual(ka.normalize(body(auth=None))["config"]["auth"], ka.blank_auth("none"))
        self.assertEqual(ka.normalize(body(auth={"type": "none", "key": "x"}))["config"]["auth"]["key"], "")

    def test_settings_enums_ranges_and_defaults(self):
        self.assertEqual(ka.normalize(body(settings=None))["config"]["settings"], ka.DEFAULT_SETTINGS)
        self.assertEqual(ka.normalize_settings(LAB_SETTINGS), LAB_SETTINGS)
        partial = ka.normalize_settings({"embedding": {"type": "public"}, "llm": {"model": "llama-4"}, "processing": {"chunk_size": 100}})
        self.assertEqual(partial["embedding"], {"type": "public", "model": "text-embedding-3-large"})
        self.assertEqual(partial["llm"], {"type": "local", "model": "llama-4"})
        self.assertEqual(partial["processing"], {"chunk_size": 100, "chunk_overlap": 99, "parser": "layout"})
        self.assertEqual(partial["retrieval"], {"top_k": 5, "threshold": 0.35, "reranker": "bge-reranker"})
        self.assertEqual((partial["storage"], partial["vector_db"], partial["security"]), ("on_prem", "milvus", {"network": "private"}))
        self.assertEqual(ka.normalize_settings({"retrieval": {"threshold": "0.5", "top_k": "7"}})["retrieval"],
                         {"top_k": 7, "threshold": 0.5, "reranker": "bge-reranker"})
        self.assertEqual(ka.normalize_settings({"llm": {"type": "public", "model": "gemini"}})["llm"], {"type": "public", "model": "gemini"})
        for raw, needle in (({"storage": "nas"}, "문서 저장소"), ({"vector_db": "faiss"}, "벡터 DB"),
                            ({"embedding": {"type": "cloud"}}, "임베딩 모델 유형"),
                            ({"embedding": {"type": "local", "model": "text-embedding-3-small"}}, "임베딩 모델(local)"),
                            ({"llm": {"type": "public", "model": "deepseek-v4-pro"}}, "LLM 모델(public)"),
                            ({"processing": {"chunk_size": 99}}, "청크 크기"), ({"processing": {"chunk_size": 8001}}, "청크 크기"),
                            ({"processing": {"chunk_size": 500, "chunk_overlap": 500}}, "청크 크기보다 작아야"),
                            ({"processing": {"chunk_overlap": 2001}}, "청크 겹침"), ({"processing": {"parser": "vision"}}, "문서 파서"),
                            ({"retrieval": {"top_k": 0}}, "Top K"), ({"retrieval": {"top_k": 51}}, "Top K"), ({"retrieval": {"top_k": True}}, "Top K"),
                            ({"retrieval": {"top_k": 2.5}}, "Top K"), ({"retrieval": {"threshold": 1.5}}, "유사도 임계값"),
                            ({"retrieval": {"threshold": "nan"}}, "유사도 임계값"), ({"retrieval": {"reranker": "cohere"}}, "리랭커"),
                            ({"security": {"network": "public"}}, "네트워크 보안"), ({"processing": "x"}, "문서 처리"), ("bad", "settings")):
            self.assertRejects(raw, needle, fn=ka.normalize_settings)


class StoreTests(_DbCase):
    def test_seed_once_and_never_recreated(self):
        agents = ka.list_agents()
        self.assertEqual([a["id"] for a in agents], ["kl_demo_hq"])
        seed = agents[0]
        self.assertEqual((seed["name"], seed["description"], seed["pos"], seed["enabled"]),
                         ("본사 로컬 에이전트", "본사 사내 규정과 영업 자료를 검색하고 답변하는 로컬 에이전트", 0, True))
        cfg = seed["config"]
        self.assertEqual((cfg["mcp"]["url"], cfg["api"]["base_url"]), (f"{BASE}/hq/mcp", f"{BASE}/hq/api/v1"))
        self.assertEqual((cfg["auth"]["type"], cfg["auth"]["key"]), ("bearer", "demo-kagent-key-2026"))
        self.assertEqual(cfg["settings"], ka.DEFAULT_SETTINGS)
        self.assertEqual([(t["name"], t["kind"], t["enabled"]) for t in cfg["mcp"]["tools"]],
                         [("kb_chat", "read", True), ("kb_search", "read", True), ("kb_get_document", "read", True)])
        self.assertEqual(cfg["mcp"]["server_info"], {**mk.TENANTS["hq"]["server_info"], "protocol": mk.PROTOCOL})
        st = seed["status"]
        self.assertEqual((st["state"], st["mcp_ok"], st["api_ok"], st["doc_count"], st["error"]), ("ok", True, True, mk.seed_count("hq"), ""))
        self.assertEqual([c["key"] for c in st["checks"]], CHECK_KEYS)
        self.assertTrue(all(c["ok"] for c in st["checks"]))
        ka.init_knowledge_agents()
        self.assertEqual(len(ka.list_agents()), 1)
        self.assertTrue(ka.delete("kl_demo_hq"))
        ka.init_knowledge_agents()   # 지운 시드는 다시 생기지 않는다 / a deleted seed never comes back
        self.assertEqual(ka.list_agents(), [])
        self.assertFalse(ka.delete("kl_demo_hq"))

    def test_create_and_masking_round_trip(self):
        a = ka.create(body(auth={**OAUTH, "client_secret": "top-secret-1"}))
        self.assertTrue(a["id"].startswith("kl_") and len(a["id"]) == 11)
        self.assertEqual(a["pos"], 1)
        rec = ka.editor_record(a)
        self.assertEqual(set(rec), EDITOR_KEYS)
        self.assertEqual(rec["auth"], {"type": "oauth2", "header": "", "key": "", "token_url": OAUTH["token_url"],
                                       "client_id": mk.OAUTH_CLIENT_ID, "client_secret": MASK})
        self.assertNotIn("top-secret-1", json.dumps(rec, ensure_ascii=False))
        self.assertEqual((rec["status"]["state"], rec["status"]["checks"], rec["level"]), ("unchecked", [], 2))
        self.assertEqual((rec["mcp"]["server_info"], rec["mcp"]["fetched_at"]), (None, None))
        kept = ka.update(a["id"], echo(rec, name="연구소 지식 에이전트 2"))
        self.assertEqual((kept["name"], kept["config"]["auth"]["client_secret"]), ("연구소 지식 에이전트 2", "top-secret-1"))
        self.assertEqual(kept["created_at"], a["created_at"])
        changed = ka.update(a["id"], echo(rec, auth={**rec["auth"], "client_secret": "top-secret-2"}))
        self.assertEqual(changed["config"]["auth"]["client_secret"], "top-secret-2")
        with self.assertRaises(V):   # 가린 값 일부만 고친 것은 거부 / a partially edited mask is refused
            ka.update(a["id"], echo(rec, auth={**rec["auth"], "client_secret": MASK + "x"}))
        k = ka.create(body(name="API 키 에이전트", auth={"type": "api_key", "header": "X-Api-Token", "key": "key-secret-9"}))
        krec = ka.editor_record(k)
        self.assertEqual(krec["auth"], {"type": "api_key", "header": "X-Api-Token", "key": MASK, "token_url": "", "client_id": "", "client_secret": ""})
        self.assertEqual(ka.update(k["id"], echo(krec))["config"]["auth"]["key"], "key-secret-9")
        pub = ka.public_record(ka.get_agent(k["id"]), 1)
        self.assertEqual(set(pub), {"id", "name", "description", "enabled", "level", "pos", "settings", "status"})
        self.assertEqual(set(pub["status"]), {"state", "checked_at", "mcp_ok", "api_ok", "doc_count"})
        self.assertNotIn("key-secret-9", json.dumps(pub, ensure_ascii=False))

    def test_masked_secrets_follow_neither_a_new_auth_type_nor_a_new_destination(self):
        bearer = ka.create(body(name="Bearer 에이전트", auth={"type": "bearer", "key": "bearer-secret-1"}))
        brec = ka.editor_record(bearer)
        # bearer → api_key 에 가린 키 = 422, bearer → bearer 에 가린 키 = 유지 / masked key: bearer→api_key 422, bearer→bearer kept
        with self.assertRaises(V) as ctx:
            ka.update(bearer["id"], echo(brec, auth={"type": "api_key", "header": "X-API-Key", "key": MASK}))
        self.assertEqual(str(ctx.exception), ka.TYPE_CHANGED)
        self.assertEqual(ka.update(bearer["id"], echo(brec))["config"]["auth"], {**ka.blank_auth("bearer"), "key": "bearer-secret-1"})
        keyed = ka.create(body(name="API 키 에이전트 2", auth={"type": "api_key", "key": "api-secret-2"}))
        krec = ka.editor_record(keyed)
        with self.assertRaises(V) as ctx:   # api_key → bearer 에 가린 키 = 422 / masked key on api_key→bearer
            ka.update(keyed["id"], echo(krec, auth={"type": "bearer", "key": MASK}))
        self.assertEqual(str(ctx.exception), ka.TYPE_CHANGED)
        # api_key → bearer 에 새 키 = 받아들인다 / a new key on api_key→bearer is accepted
        self.assertEqual(ka.update(keyed["id"], echo(krec, auth={"type": "bearer", "key": "new-bearer-3"}))["config"]["auth"],
                         {**ka.blank_auth("bearer"), "key": "new-bearer-3"})
        oauth = ka.create(body(name="OAuth 에이전트 2", auth={**OAUTH, "client_secret": "oauth-secret-4"}))
        orec = ka.editor_record(oauth)
        with self.assertRaises(V) as ctx:   # oauth2 → bearer 에 가린 값 / a mask on oauth2→bearer
            ka.update(oauth["id"], echo(orec, auth={"type": "bearer", "key": MASK}))
        self.assertIn("저장된", str(ctx.exception))   # oauth2 에는 key 가 없다 / oauth2 stores no key
        # 주소(origin)가 바뀌면 가린 비밀을 복원하지 않는다: MCP · API · 토큰 URL 각각 / a new origin never gets the stored secret
        for over in ({"mcp": {"url": "https://collector.example.net/mcp"}},
                     {"api": {"base_url": "https://collector.example.net/api"}},
                     {"auth": {**orec["auth"], "token_url": "https://collector.example.net/token"}}):
            src = orec if "token_url" in json.dumps(over) else brec
            target = oauth if src is orec else bearer
            with self.assertRaises(V, msg=over) as ctx:
                ka.update(target["id"], echo(src, **over))
            self.assertEqual(str(ctx.exception), ka.DEST_CHANGED)
        # 같은 origin 의 경로만 바뀌면 유지 / a path change on the same origin keeps the secret
        same = ka.update(bearer["id"], echo(brec, api={"base_url": f"{BASE}/lab/api/v2"}))
        self.assertEqual(same["config"]["auth"]["key"], "bearer-secret-1")
        # 새 비밀을 함께 넣으면 새 주소도 된다 / a freshly typed secret may go anywhere
        moved = ka.update(bearer["id"], echo(brec, mcp={"url": "https://kms.example.com/mcp"}, auth={"type": "bearer", "key": "fresh-5"}))
        self.assertEqual(moved["config"]["mcp"]["url"], "https://kms.example.com/mcp")
        # 초안 확인도 같은 규칙 / draft checks follow the same rule
        with self.assertRaises(V) as ctx:
            ka.check({"mcp": {"url": "https://collector.example.net/mcp"}, "api": {"base_url": f"{BASE}/lab/api/v1"},
                      "auth": {"type": "bearer", "key": MASK}}, ka.get_agent(bearer["id"]))
        self.assertEqual(str(ctx.exception), ka.DEST_CHANGED)

    def test_put_omissions_keep_auth_and_enabled(self):
        a = ka.create(body(name="생략 에이전트", enabled=False, auth={"type": "bearer", "key": "keep-me-6"}))
        rec = ka.editor_record(a)
        partial = {k: rec[k] for k in ("name", "description", "mcp", "api")}
        kept = ka.update(a["id"], partial)   # auth · enabled 없음 / no auth, no enabled
        self.assertEqual((kept["enabled"], kept["config"]["auth"]["key"]), (False, "keep-me-6"))
        with self.assertRaises(V) as ctx:   # auth 없이 주소만 바꾸면 저장 비밀이 따라가지 않는다 / no auth + new origin → 422
            ka.update(a["id"], {**partial, "mcp": {"url": "https://collector.example.net/mcp"}})
        self.assertEqual(str(ctx.exception), ka.DEST_CHANGED)
        none_auth = ka.create(body(name="인증 없음", auth={"type": "none"}))
        moved = ka.update(none_auth["id"], {"name": "인증 없음", "mcp": {"url": "https://kms.example.com/mcp"},
                                            "api": {"base_url": "https://kms.example.com/api"}})
        self.assertEqual(moved["config"]["auth"]["type"], "none")   # 비밀이 없으면 주소를 바꿔도 된다 / no secret, no restriction
        self.assertEqual(ka.create(body(name="새 기본값", enabled=None))["enabled"], True)

    def test_api_key_header_deny_list(self):
        for header in ("Host", "content-length", "Transfer-Encoding", "Connection", "Content-Type", "ACCEPT",
                       "Mcp-Session-Id", "mcp-protocol-version"):
            with self.assertRaises(V, msg=header) as ctx:
                ka.normalize_auth({"type": "api_key", "header": header, "key": "k-1"})
            self.assertIn("인증 헤더로 쓸 수 없습니다", str(ctx.exception))
        self.assertEqual(ka.normalize_auth({"type": "api_key", "header": "Authorization", "key": "k-1"})["header"], "Authorization")
        with self.assertRaises(V):   # 헤더에 실리는 키는 ASCII 만 / header-bound keys are ASCII only
            ka.normalize_auth({"type": "bearer", "key": "토큰값"})

    def test_duplicate_names_are_conflicts(self):
        a = ka.create(body(name="Lab Agent"))
        with self.assertRaises(ka.KnowledgeAgentConflictError):
            ka.create(body(name="lab agent"))   # 대소문자 무시 / case-insensitive
        other = ka.create(body(name="Other"))
        with self.assertRaises(ka.KnowledgeAgentConflictError):
            ka.update(other["id"], body(name="LAB AGENT"))
        self.assertEqual(ka.update(a["id"], body(name="Lab Agent"))["name"], "Lab Agent")   # 자기 이름 유지 / its own name is fine
        # 라틴 확장 · 독일어 ß 는 casefold 로, 한글 조합형(NFD)은 NFC 로 같은 이름 / casefold for Latin, NFC for decomposed Hangul
        ka.create(body(name="Équipe KMS"))
        with self.assertRaises(ka.KnowledgeAgentConflictError):
            ka.create(body(name="équipe kms"))
        ka.create(body(name="Straße"))
        with self.assertRaises(ka.KnowledgeAgentConflictError):
            ka.create(body(name="STRASSE"))
        nfd = unicodedata.normalize("NFD", "본사 로컬 에이전트")
        self.assertNotEqual(nfd, "본사 로컬 에이전트")
        with self.assertRaises(ka.KnowledgeAgentConflictError):
            ka.create(body(name=nfd))
        stored = ka.create(body(name=unicodedata.normalize("NFD", "연구소 새 에이전트")))
        self.assertEqual(stored["name"], "연구소 새 에이전트")   # NFC 로 저장 / stored in NFC
        with patch.object(ka, "MAX_AGENTS", len(ka.list_agents())), self.assertRaises(V):
            ka.create(body(name="하나 더"))

    def test_update_keeps_tools_settings_skills_and_resets_status_on_new_connection(self):
        rec = ka.editor_record(ka.get_agent("kl_demo_hq"))
        tools = rec["mcp"]["tools"]
        tools[2]["enabled"] = False
        a = ka.update("kl_demo_hq", echo(rec, mcp={"url": rec["mcp"]["url"], "timeout": 40, "tools": tools},
                                         settings=copy.deepcopy(LAB_SETTINGS), enabled=False))
        self.assertEqual((a["config"]["mcp"]["timeout"], a["enabled"]), (40, False))
        self.assertFalse(a["config"]["mcp"]["tools"][2]["enabled"])
        self.assertEqual(a["status"]["state"], "ok")   # 주소 · 인증이 그대로면 상태 유지 / same URL and auth keep the status
        b = ka.update("kl_demo_hq", echo(ka.editor_record(a), mcp={"url": rec["mcp"]["url"]}, settings=None))
        self.assertEqual(len(b["config"]["mcp"]["tools"]), 3)          # tools 없음 = 유지 / no tools = kept
        self.assertFalse(b["config"]["mcp"]["tools"][2]["enabled"])
        self.assertEqual(b["config"]["settings"], LAB_SETTINGS)        # settings 없음 = 유지 / no settings = kept
        self.assertEqual(b["config"]["mcp"]["server_info"], rec["mcp"]["server_info"])
        c = ka.update("kl_demo_hq", echo(ka.editor_record(b), mcp={"url": f"{BASE}/lab/mcp"}))
        self.assertEqual(ka.editor_record(c)["status"]["state"], "unchecked")   # 주소가 바뀌면 미확인 / a new URL resets the check
        self.assertIsNone(ka.update("kl_missing", body()))

    def test_skill_files_attach_keep_and_go_with_the_agent(self):
        f1, f2 = skill_files.add("guide.md", b"# guide"), skill_files.add("rules.yaml", b"a: 1")
        a = ka.create(body(skill_ids=[f1["id"], f2["id"]]))
        self.assertEqual([s["id"] for s in ka.editor_record(a)["skills"]], [f1["id"], f2["id"]])
        ka.update(a["id"], body())   # skill_ids 없음 = 유지 / omitted = kept
        self.assertEqual(len(ka.editor_record(ka.get_agent(a["id"]))["skills"]), 2)
        ka.update(a["id"], body(skill_ids=[f1["id"]]))
        self.assertIsNone(skill_files.get(f2["id"]))
        mcp_owned = skill_files.add("x.md", b"x", owner_kind="mcp", owner_id="mcp_1")
        with self.assertRaises(V):
            ka.create(body(name="B", skill_ids=[mcp_owned["id"]]))
        with self.assertRaises(V):
            ka.create(body(name="C", skill_ids=["not-an-id"]))
        self.assertTrue(ka.delete(a["id"]))
        self.assertIsNone(skill_files.get(f1["id"]))

    def test_summaries_is_a_plain_select_and_survives_a_missing_table(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE knowledge_agents SET config='{broken', status='nope' WHERE id='kl_demo_hq'")
        conn.close()
        self.assertEqual(ka.summaries(), [{"id": "kl_demo_hq", "name": "본사 로컬 에이전트"}])
        self.assertEqual(ka.get_agent("kl_demo_hq")["config"], {})   # 깨진 JSON 은 빈 설정 / broken JSON reads as empty
        self.assertEqual(ka.editor_record(ka.get_agent("kl_demo_hq"))["settings"], ka.DEFAULT_SETTINGS)
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "empty.db"
            conns = []

            def connect():
                c = sqlite3.connect(empty)
                c.row_factory = sqlite3.Row
                conns.append(c)
                return c
            with patch.object(ka, "_conn", connect):
                self.assertEqual((ka.summaries(), ka.list_agents(), ka.get_agent("kl_demo_hq")), ([], [], None))
            for c in conns:
                c.close()


class CheckTests(_DbCase):
    def setUp(self):
        super().setUp()
        self.calls: dict = {}
        self.transport = mock_transport(self.calls)

    def draft(self, tenant="lab", auth=None):
        return {"mcp": {"url": f"{BASE}/{tenant}/mcp"}, "api": {"base_url": f"{BASE}/{tenant}/api/v1"},
                "auth": auth or {"type": "bearer", "key": mk.DEMO_KEY}}

    def test_bearer_api_key_and_oauth_paths(self):
        for auth in ({"type": "bearer", "key": mk.DEMO_KEY}, {"type": "api_key", "key": mk.DEMO_KEY}, OAUTH):
            res = ka.check(self.draft(auth=auth), transport=self.transport)
            self.assertEqual(set(res), {"ok", "checked_at", "mcp", "api", "checks"})
            self.assertTrue(res["ok"], res)
            self.assertEqual([c["key"] for c in res["checks"]], CHECK_KEYS)
            self.assertEqual([c["group"] for c in res["checks"]], ["mcp"] * 4 + ["api"] * 6)
            self.assertTrue(all(c["ok"] for c in res["checks"]))
            self.assertEqual(res["api"], {"ok": True, "error": "", "version": "1.0", "doc_count": mk.seed_count("lab"),
                                          "capabilities": ["list", "upload", "preview", "download", "delete", "status"]})
            self.assertEqual(res["mcp"]["server_info"]["name"], mk.TENANTS["lab"]["server_info"]["name"])
            self.assertEqual([t["name"] for t in res["mcp"]["tools"]], ["kb_chat", "kb_search", "kb_get_document"])
        self.assertEqual(self.calls.get("/mock/kagent/lab/oauth/token"), 1)
        self.assertEqual(ka._TOKENS, {})   # 초안 확인은 토큰을 캐시하지 않는다 / draft checks never cache tokens

    def test_failures_are_flagged_and_redacted(self):
        bad = ka.check(self.draft(auth={"type": "bearer", "key": "wrong-secret-77"}), transport=self.transport)
        self.assertFalse(bad["ok"])
        self.assertFalse(any(c["ok"] for c in bad["checks"]))
        self.assertIn("401", bad["mcp"]["error"])
        self.assertIn("401", bad["api"]["error"])
        self.assertNotIn("wrong-secret-77", json.dumps(bad, ensure_ascii=False))
        oauth_bad = ka.check(self.draft(auth={**OAUTH, "client_secret": "nope-secret-5"}), transport=self.transport)
        self.assertIn("OAuth 토큰 발급 실패", oauth_bad["mcp"]["error"])
        self.assertIn("OAuth 토큰 발급 실패", oauth_bad["api"]["error"])
        self.assertNotIn("nope-secret-5", json.dumps(oauth_bad, ensure_ascii=False))
        # 사설 주소는 check_url 이 막고 전송까지 가지 않는다 / private addresses are stopped by check_url before any transport call
        before = dict(self.calls)
        private = ka.check({"mcp": {"url": "http://10.1.2.3/mcp"}, "api": {"base_url": "http://10.1.2.3/api"}, "auth": {"type": "none"}},
                           transport=self.transport)
        self.assertIn("사내망", private["mcp"]["error"])
        self.assertIn("사내망", private["api"]["error"])
        self.assertEqual(self.calls, before)

    def test_partial_server_gets_row_level_verdicts(self):
        def server(with_sources: bool):
            def handle(request: httpx.Request) -> httpx.Response:
                path = request.url.path
                if path.endswith("/health"):
                    return httpx.Response(200, json={"status": "ok", "version": "0.9", "capabilities": ["list", "preview"]})
                if path.endswith("/documents"):
                    return httpx.Response(200, json={"documents": [{"id": "d1", "name": "a.pdf"}]})
                msg = json.loads(request.content)
                if msg.get("id") is None:
                    return httpx.Response(202)
                if msg["method"] == "initialize":
                    res = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "Custom", "version": "2"}}
                elif msg["method"] == "tools/list":
                    schema = {"type": "object", "properties": {"q": {"type": "string"}}}
                    res = {"tools": [{"name": "kb_chat", "inputSchema": schema}, {"name": "kb_search", "inputSchema": schema}]}
                else:
                    data = {"answer": "a", **({"sources": []} if with_sources else {})}
                    res = {"content": [{"type": "text", "text": "a"}], "structuredContent": data}
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg["id"], "result": res})
            return httpx.MockTransport(handle)

        res = ka.check(self.draft(), transport=server(False))
        rows = {c["key"]: c for c in res["checks"]}
        self.assertTrue(rows["mcp_chat"]["ok"] and rows["mcp_search"]["ok"])
        self.assertFalse(rows["mcp_get_document"]["ok"])
        self.assertEqual(rows["mcp_sources"], {"key": "mcp_sources", "group": "mcp", "ok": False, "target": "kb_chat", "detail": "출력에 sources 가 없습니다"})
        self.assertEqual(rows["api_list"]["detail"], "문서 1건")
        self.assertTrue(rows["api_preview"]["ok"])
        self.assertFalse(rows["api_upload"]["ok"])
        self.assertEqual(res["mcp"]["error"], "kb_get_document: 도구가 없습니다")
        self.assertIn("upload", res["api"]["error"])
        self.assertEqual(res["api"]["version"], "0.9")
        # 출력 명세가 없어도 kb_chat 결과에 sources 가 있으면 통과 / no output schema, but sources in the result → ok
        ok = {c["key"]: c for c in ka.check(self.draft(), transport=server(True))["checks"]}
        self.assertEqual((ok["mcp_sources"]["ok"], ok["mcp_sources"]["detail"]), (True, "출력에 sources 가 있습니다"))

    def test_check_saved_persists_status_and_keeps_tool_flags(self):
        rec = ka.editor_record(ka.get_agent("kl_demo_hq"))
        tools = rec["mcp"]["tools"]
        tools[2]["enabled"] = False
        ka.update("kl_demo_hq", echo(rec, mcp={"url": rec["mcp"]["url"], "tools": tools}))
        out = ka.check_saved("kl_demo_hq", transport=self.transport)
        self.assertTrue(out["ok"])
        agent = out["agent"]
        self.assertEqual(set(agent), EDITOR_KEYS)
        self.assertEqual((agent["status"]["state"], agent["status"]["checked_at"], agent["mcp"]["fetched_at"]),
                         ("ok", out["checked_at"], out["checked_at"]))
        self.assertFalse(agent["mcp"]["tools"][2]["enabled"])   # 사용 여부는 기존 값 유지 / admin flags kept
        self.assertEqual(agent["auth"]["key"], MASK)
        ka.update("kl_demo_hq", echo(agent, auth={"type": "bearer", "key": "bad-key-3"}))
        out2 = ka.check_saved("kl_demo_hq", transport=self.transport)
        self.assertEqual(out2["agent"]["status"]["state"], "error")
        self.assertTrue(out2["agent"]["status"]["error"])
        self.assertEqual(len(out2["agent"]["mcp"]["tools"]), 3)   # 접속 실패는 도구를 지우지 않는다 / a failed fetch keeps the tools
        self.assertNotIn("bad-key-3", json.dumps(out2, ensure_ascii=False))
        self.assertIsNone(ka.check_saved("kl_missing", transport=self.transport))


class ApiTests(_DbCase):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(ka, "DEFAULT_TRANSPORT", mock_transport()))
        app = FastAPI()
        app.include_router(kapi.router)
        self.client = TestClient(app)
        self.base = "/api/knowledge-agents/kl_demo_hq"

    def as_member(self, nodes: dict):
        return patch.object(access, "effective", return_value=member(nodes))

    def test_view_only_member_is_refused_every_write(self):
        c = self.client
        files = {"file": ("s.md", b"# skill", "text/markdown")}
        pending = skill_files.add("p.md", b"p")
        with self.as_member({"kl_demo_hq": 1}):
            register_gated = (c.post("/api/knowledge-agents", json={**body(), "acting_user_id": "7"}),
                              c.post("/api/knowledge-agents", json={**body(), "acting_user_id": 7}),   # 숫자도 구성원 / a number is a member too
                              c.post("/api/knowledge-agents/check", json={"draft": body(), "acting_user_id": "7"}),
                              c.post("/api/knowledge-agents/skills", data={"acting_user_id": "7"}, files=files),
                              c.post("/api/knowledge-agents/skills", params={"acting_user_id": "7"}, files=files),
                              c.delete(f"/api/knowledge-agents/skills/{pending['id']}", params={"acting_user_id": "7"}))
            node_gated = (c.put(self.base, json={**body(), "acting_user_id": "7"}),
                          c.delete(self.base, params={"acting_user_id": "7"}),
                          c.get(self.base, params={"acting_user_id": "7"}),
                          c.post("/api/knowledge-agents/check", json={"id": "kl_demo_hq", "acting_user_id": "7"}),
                          c.post("/api/knowledge-agents/check", json={"id": "kl_demo_hq", "draft": body(), "acting_user_id": "7"}))
        for r in register_gated:
            self.assertEqual((r.status_code, r.json()["detail"]), (403, "로컬 지식 에이전트를 등록할 권한이 없습니다"))
        for r in node_gated:
            self.assertEqual((r.status_code, r.json()["detail"]), (403, "이 에이전트의 관리 권한이 필요합니다"))
        self.assertEqual(ka.get_agent("kl_demo_hq")["name"], "본사 로컬 에이전트")
        self.assertEqual(len(ka.list_agents()), 1)
        self.assertIsNotNone(skill_files.get(pending["id"]))
        with self.as_member({}):   # 없는 에이전트는 권한보다 먼저 404 / a missing agent is 404 before the gate
            self.assertEqual(c.get("/api/knowledge-agents/kl_nope", params={"acting_user_id": "7"}).status_code, 404)


    def test_create_read_update_delete_contract(self):
        c = self.client
        r = c.post("/api/knowledge-agents", json=body())
        self.assertEqual(r.status_code, 201)
        agent = r.json()["agent"]
        self.assertEqual(set(agent), EDITOR_KEYS)
        self.assertEqual((agent["auth"]["key"], agent["level"], agent["settings"]), (MASK, 2, LAB_SETTINGS))
        self.assertEqual(c.post("/api/knowledge-agents", json=body(name=" ")).json(), {"detail": "에이전트 이름이 비어 있습니다"})
        dup = c.post("/api/knowledge-agents", json=body())
        self.assertEqual((dup.status_code, dup.json()["detail"]), (409, "같은 이름의 지식 에이전트가 이미 있습니다: 연구소 지식 에이전트"))
        self.assertEqual(c.post("/api/knowledge-agents", json=body(auth={"type": "oauth2"})).status_code, 422)
        self.assertEqual(c.get(f"/api/knowledge-agents/{agent['id']}").json()["agent"]["id"], agent["id"])
        upd = c.put(f"/api/knowledge-agents/{agent['id']}", json={**echo(agent, description="수정"), "acting_user_id": ""})
        self.assertEqual((upd.status_code, upd.json()["agent"]["description"]), (200, "수정"))
        self.assertEqual(ka.get_agent(agent["id"])["config"]["auth"]["key"], mk.DEMO_KEY)   # 가린 키 유지 / masked key kept
        self.assertEqual(c.put("/api/knowledge-agents/kl_nope", json=body(name="X")).status_code, 404)
        self.assertEqual(c.get("/api/knowledge-agents/kl_nope").status_code, 404)
        self.assertEqual(c.delete(f"/api/knowledge-agents/{agent['id']}").json(), {"ok": True})
        self.assertEqual(c.delete(f"/api/knowledge-agents/{agent['id']}").status_code, 404)

    def test_skills_routes(self):
        c = self.client
        up = c.post("/api/knowledge-agents/skills", files={"file": ("guide.md", "# 사용법".encode("utf-8"), "text/markdown")})
        self.assertEqual(set(up.json()), {"id", "name", "size", "uploaded_at"})
        self.assertEqual(c.post("/api/knowledge-agents/skills", files={"file": ("x.exe", b"x", "application/octet-stream")}).status_code, 422)
        agent = c.post("/api/knowledge-agents", json=body(skill_ids=[up.json()["id"]])).json()["agent"]
        self.assertEqual([s["id"] for s in agent["skills"]], [up.json()["id"]])
        mcp_owned = skill_files.add("m.md", b"m", owner_kind="mcp", owner_id="mcp_1")
        self.assertEqual(c.delete(f"/api/knowledge-agents/skills/{mcp_owned['id']}").status_code, 404)   # 다른 주인 / another owner
        self.assertEqual(c.delete(f"/api/knowledge-agents/skills/{up.json()['id']}").json(), {"ok": True})
        self.assertEqual(c.delete(f"/api/knowledge-agents/skills/{up.json()['id']}").status_code, 404)

    def test_list_filters_by_level_and_enabled(self):
        c = self.client
        a = c.post("/api/knowledge-agents", json=body()).json()["agent"]["id"]
        b = c.post("/api/knowledge-agents", json=body(name="사용 중지 에이전트", enabled=False)).json()["agent"]["id"]
        sup = c.get("/api/knowledge-agents").json()
        self.assertEqual((sup["super"], sup["can_register"]), (True, True))
        self.assertEqual([x["id"] for x in sup["agents"]], ["kl_demo_hq", a, b])
        self.assertTrue(all(set(x) == EDITOR_KEYS | {"editable"} and x["editable"] for x in sup["agents"]))
        c2 = c.post("/api/knowledge-agents", json=body(name="열람만 중지", enabled=False)).json()["agent"]["id"]
        with self.as_member({"kl_demo_hq": 1, a: 2, b: 2, c2: 1}):
            mem = c.get("/api/knowledge-agents", params={"acting_user_id": "7"}).json()
        self.assertEqual((mem["super"], mem["can_register"]), (False, False))
        # 관리(2) 인 사용 중지 에이전트는 다시 켤 수 있게 보이고, 열람(1)만 가진 사용 중지 에이전트는 숨긴다
        # a disabled agent the member manages stays listed (to switch it back on); a disabled view-only one is hidden
        self.assertEqual([(x["id"], x["level"], x["editable"], x["enabled"]) for x in mem["agents"]],
                         [("kl_demo_hq", 1, False, True), (a, 2, True, True), (b, 2, True, False)])
        for x in mem["agents"]:
            self.assertFalse({"mcp", "api", "auth", "skills"} & set(x))
        self.assertEqual([x["status"]["doc_count"] for x in mem["agents"]], [mk.seed_count("hq"), None, None])
        with self.as_member({}):
            self.assertEqual(c.get("/api/knowledge-agents", params={"acting_user_id": "7"}).json(),
                             {"agents": [], "super": False, "can_register": False})
        with self.as_member({"p_klocal": 2}):
            self.assertTrue(c.get("/api/knowledge-agents", params={"acting_user_id": "7"}).json()["can_register"])
        with patch.object(access, "effective", side_effect=RuntimeError("down")), \
                self.assertLogs("ai365.knowledge_agents", level="WARNING"):   # 조회 실패 = 전부 차단 / lookup failure blocks all
            self.assertEqual(c.get("/api/knowledge-agents", params={"acting_user_id": "7"}).json()["agents"], [])

    def test_pvtree_leaf_follows_create_rename_and_delete(self):
        c = self.client
        agent = c.post("/api/knowledge-agents", json=body()).json()["agent"]

        def klocal():
            mres = next(n for n in access.PV_TREE if n["id"] == "m_res")
            self.assertEqual([ch["id"] for ch in mres["children"]][:2], ["p_know", "p_klocal"])
            node = next(ch for ch in mres["children"] if ch["id"] == "p_klocal")
            self.assertEqual((node["label"], node["kind"]), ("지식 관리 · Local", "page"))
            return node["children"]
        self.assertEqual(klocal(), [{"id": "kl_demo_hq", "label": "본사 로컬 에이전트", "kind": "file"},
                                    {"id": agent["id"], "label": "연구소 지식 에이전트", "kind": "file"}])
        self.assertEqual(access.PV_PARENT[agent["id"]], "p_klocal")
        c.put(f"/api/knowledge-agents/{agent['id']}", json=echo(agent, name="연구소 KMS"))
        self.assertEqual(klocal()[1]["label"], "연구소 KMS")
        c.delete(f"/api/knowledge-agents/{agent['id']}")
        self.assertEqual([x["id"] for x in klocal()], ["kl_demo_hq"])
        self.assertNotIn(agent["id"], access.PV_NODES)
        c.delete("/api/knowledge-agents/kl_demo_hq")
        self.assertEqual(klocal(), [])   # 에이전트가 없어도 p_klocal 은 남는다 / p_klocal stays with no agents
        self.assertIn("p_klocal", access.PV_NODES)

    def test_check_route_draft_and_saved(self):
        c = self.client
        seed = c.get(self.base).json()["agent"]
        draft = {"mcp": seed["mcp"], "api": seed["api"], "auth": seed["auth"]}   # 가린 키 그대로 / masked key as is
        r = c.post("/api/knowledge-agents/check", json={"id": "kl_demo_hq", "draft": draft})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertNotIn("agent", r.json())
        self.assertIn("저장된", c.post("/api/knowledge-agents/check", json={"draft": draft}).json()["detail"])
        self.assertEqual(c.post("/api/knowledge-agents/check", json={"id": "kl_nope"}).status_code, 404)
        self.assertEqual(c.post("/api/knowledge-agents/check", json={}).status_code, 422)
        self.assertEqual(c.post("/api/knowledge-agents/check", json={"draft": {"mcp": {"url": "ftp://x"}}}).status_code, 422)
        self.assertEqual(c.post("/api/knowledge-agents/check", json={"draft": "x"}).status_code, 422)
        out = c.post("/api/knowledge-agents/check", json={"id": "kl_demo_hq"}).json()
        self.assertEqual(set(out), {"ok", "checked_at", "mcp", "api", "checks", "agent"})
        self.assertEqual(out["agent"]["status"]["checked_at"], out["checked_at"])

    def test_proxy_reads(self):
        c, base = self.client, self.base
        self.assertEqual([f["name"] for f in c.get(base + "/folders").json()["folders"]], ["경영 규정", "영업 자료"])
        docs = c.get(base + "/documents").json()["documents"]
        self.assertEqual(len(docs), mk.seed_count("hq"))
        self.assertEqual(set(docs[0]), {"id", "name", "folder_id", "size", "mime", "status", "updated_at"})
        self.assertEqual(len(c.get(base + "/documents", params={"folder_id": "hq-sales"}).json()["documents"]), 3)
        r = c.get(base + "/documents/hq-doc-001/preview")
        self.assertEqual((r.status_code, r.headers["content-type"], r.headers["x-content-type-options"]), (200, "application/pdf", "nosniff"))
        self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertTrue(r.headers["content-disposition"].startswith("inline; "))
        r = c.get(base + "/documents/hq-doc-004/preview")
        self.assertEqual(r.headers["content-type"], "text/plain; charset=utf-8")
        self.assertIn("CRM", r.text)
        r = c.get(base + "/documents/hq-doc-005/preview")
        self.assertEqual((r.status_code, r.json()), (415, {"detail": "미리보기를 지원하지 않는 형식입니다"}))
        r = c.get(base + "/documents/hq-doc-003/download")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-disposition"],
                         "attachment; filename=\"document.pdf\"; filename*=UTF-8''2026%20%EC%98%81%EC%97%85%20%EC%A0%84%EB%9E%B5%20%EB%B3%B4%EA%B3%A0%EC%84%9C.pdf")
        self.assertEqual(r.content, bytes(mk.get_doc("hq", "hq-doc-003")["content"]))
        self.assertEqual(c.get(base + "/documents/hq-doc-001/status").json(), {"status": "done", "message": "처리가 끝났습니다"})
        for path in ("/documents/missing/status", "/documents/missing/preview", "/documents/missing/download"):
            self.assertEqual(c.get(base + path).json(), {"detail": "문서를 찾을 수 없습니다"})
        self.assertEqual(c.delete(base + "/documents/missing").status_code, 404)
        self.assertEqual(c.get("/api/knowledge-agents/kl_nope/documents").json(), {"detail": "존재하지 않는 에이전트입니다"})
        with self.assertRaises(ka.AgentCallError):
            ka._doc_path("..")

    def test_proxy_permissions_and_disabled(self):
        c, base = self.client, self.base
        files = {"file": ("메모.txt", "업로드 메모".encode("utf-8"), "text/plain")}
        with self.as_member({}):
            for path in ("/folders", "/documents", "/documents/hq-doc-001/status", "/documents/hq-doc-001/preview",
                         "/documents/hq-doc-001/download"):
                r = c.get(base + path, params={"acting_user_id": "7"})
                self.assertEqual((r.status_code, r.json()["detail"]), (403, "이 에이전트를 볼 권한이 없습니다"))
        with self.as_member({"kl_demo_hq": 1}):
            self.assertEqual(c.get(base + "/documents", params={"acting_user_id": "7"}).status_code, 200)
            for r in (c.post(base + "/documents", params={"acting_user_id": "7"}, files=files),
                      c.post(base + "/documents", data={"acting_user_id": "7"}, files=files),   # 폼 필드로 와도 같다 / same via the form field
                      c.delete(base + "/documents/hq-doc-001", params={"acting_user_id": "7"})):
                self.assertEqual((r.status_code, r.json()["detail"]), (403, "이 에이전트의 관리 권한이 필요합니다"))
        with self.as_member({"kl_demo_hq": 2}):
            up = c.post(base + "/documents", params={"acting_user_id": "7"}, data={"folder_id": "hq-sales"}, files=files)
            self.assertEqual(up.status_code, 200)
            doc = up.json()["document"]
            self.assertEqual((doc["name"], doc["folder_id"], doc["status"], doc["mime"]), ("메모.txt", "hq-sales", "processing", "text/plain"))
            self.assertEqual(c.delete(base + f"/documents/{doc['id']}", params={"acting_user_id": "7"}).json(), {"ok": True})
        self.assertIsNone(mk.get_doc("hq", doc["id"]))
        ka.update("kl_demo_hq", echo(ka.editor_record(ka.get_agent("kl_demo_hq")), enabled=False))
        self.assertEqual(c.get(base + "/documents").json(), {"detail": "사용 중지된 에이전트입니다"})
        with self.as_member({"kl_demo_hq": 2}):
            self.assertEqual(c.get(base + "/folders", params={"acting_user_id": "7"}).status_code, 409)
        with self.as_member({}):   # 권한이 없으면 사용 중지 여부도 알리지 않는다 / no permission: 403 before 409
            self.assertEqual(c.get(base + "/folders", params={"acting_user_id": "7"}).status_code, 403)

    def test_upload_limits_and_agent_failures(self):
        c, base = self.client, self.base

        def up(name, data=b"x", **form):
            return c.post(base + "/documents", data=form, files={"file": (name, data, "application/octet-stream")})
        self.assertIn("지원하지 않는 파일 형식", up("run.exe").json()["detail"])
        self.assertEqual(up("a.txt", b"").json(), {"detail": "빈 파일은 올릴 수 없습니다"})
        with patch.object(ka, "MAX_UPLOAD_BYTES", 8):
            r = up("a.txt", b"123456789")
            self.assertEqual(r.status_code, 413)
            self.assertIn("파일이 너무 큽니다", r.json()["detail"])
        r = up("a.txt", folder_id="no-such-folder")
        self.assertEqual(r.status_code, 422)
        self.assertTrue(r.json()["detail"].startswith("에이전트가 파일을 받지 않았습니다"))
        docx = up("../../견적 요청서.docx", b"PK\x03\x04docx", folder_id="hq-sales").json()["document"]
        self.assertEqual((docx["name"], docx["mime"]), ("견적 요청서.docx", ka.MIME_BY_EXT["docx"]))   # 경로 제거 / path stripped
        # 에이전트 인증 실패 → 502, 비밀 없음 / agent auth failure → 502 without the secret
        ka.update("kl_demo_hq", echo(ka.editor_record(ka.get_agent("kl_demo_hq")), auth={"type": "bearer", "key": "leaky-secret-42"}))
        r = c.get(base + "/documents")
        self.assertEqual(r.status_code, 502)
        self.assertTrue(r.json()["detail"].startswith("에이전트에 연결하지 못했습니다"))
        self.assertNotIn("leaky-secret-42", r.text)
        # 오류 본문이 비밀을 되돌려 보내도 가린다 / a secret echoed in an error body is redacted
        leak = httpx.MockTransport(lambda req: httpx.Response(500, json={"error": {"message": "bad " + req.headers.get("authorization", "")}}))
        with patch.object(ka, "DEFAULT_TRANSPORT", leak):
            r = c.get(base + "/folders")
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("leaky-secret-42", r.text)
        self.assertIn("••••••", r.json()["detail"])
        ka.update("kl_demo_hq", body(name="본사 로컬 에이전트", mcp={"url": "http://192.168.0.10/mcp"}, api={"base_url": "http://192.168.0.10/api"}))
        r = c.get(base + "/documents")
        self.assertEqual(r.status_code, 502)
        self.assertIn("사내망", r.json()["detail"])


class MemberGateTests(_DbCase):
    """실제 access.effective 로(그룹 · 구성원만 가짜) 등록 · 수정 관문을 본다 / the gates through the real access.effective (fake groups and members)"""

    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(ka, "DEFAULT_TRANSPORT", mock_transport()))
        self.groups: list = []
        self.stack.enter_context(patch.object(access, "list_groups", side_effect=lambda: copy.deepcopy(self.groups)))
        self.stack.enter_context(patch.object(access, "list_members", return_value=[{"no": 7, "dept": "인사총무"}]))
        self.stack.enter_context(patch.object(access, "replace_groups", side_effect=AssertionError("실 DB 그룹 저장 금지")))
        app = FastAPI()
        app.include_router(kapi.router)
        self.client = TestClient(app)
        access.rebuild_universe()

    def grant(self, *grants):
        self.groups = [{"id": "g7", "name": "테스트", "memberIds": [7], "menus": ["m_home", "m_res"],
                        "grants": [{"node": n, "action": a} for n, a in grants], "exceptions": []}]

    def test_anchor_manager_can_register_and_then_edit(self):
        c = self.client
        self.grant(("p_klocal", "manage"))
        lst = c.get("/api/knowledge-agents", params={"acting_user_id": "7"}).json()
        self.assertTrue(lst["can_register"])
        self.assertEqual([(x["id"], x["editable"]) for x in lst["agents"]], [("kl_demo_hq", True)])
        # 초안 연결 테스트(id 없음) = 등록 관문 / a draft check without id = register gate
        draft = {"mcp": {"url": f"{BASE}/lab/mcp"}, "api": {"base_url": f"{BASE}/lab/api/v1"}, "auth": {"type": "bearer", "key": mk.DEMO_KEY}}
        self.assertTrue(c.post("/api/knowledge-agents/check", json={"draft": draft, "acting_user_id": "7"}).json()["ok"])
        r = c.post("/api/knowledge-agents", json={**body(), "acting_user_id": "7"})
        self.assertEqual(r.status_code, 201)
        new_id = r.json()["agent"]["id"]
        # 앵커 grant 가 새 에이전트로 캐스케이드 → 바로 수정 · 편집 레코드 · 저장된 확인 · 삭제 / the anchor cascades to the new agent
        rec = c.get(f"/api/knowledge-agents/{new_id}", params={"acting_user_id": "7"}).json()["agent"]
        self.assertEqual(rec["auth"]["key"], MASK)
        upd = c.put(f"/api/knowledge-agents/{new_id}", json={**echo(rec, description="팀장 수정"), "acting_user_id": "7"})
        self.assertEqual(upd.json()["agent"]["description"], "팀장 수정")
        self.assertTrue(c.post("/api/knowledge-agents/check", json={"id": new_id, "acting_user_id": "7"}).json()["ok"])
        up = c.post("/api/knowledge-agents/skills", params={"acting_user_id": "7"}, files={"file": ("g.md", b"# g", "text/markdown")})
        self.assertEqual(up.status_code, 200)
        self.assertEqual(c.delete(f"/api/knowledge-agents/{new_id}", params={"acting_user_id": "7"}).json(), {"ok": True})

    def test_agent_manager_edits_only_that_agent(self):
        c = self.client
        other = ka.create(body(name="다른 에이전트"))
        access.rebuild_universe()
        own_skill = skill_files.add("own.md", b"o")
        other_skill = skill_files.add("other.md", b"x")
        ka.update("kl_demo_hq", {**echo(ka.editor_record(ka.get_agent("kl_demo_hq"))), "skill_ids": [own_skill["id"]]})
        ka.update(other["id"], {**echo(ka.editor_record(ka.get_agent(other["id"]))), "skill_ids": [other_skill["id"]]})
        self.grant(("kl_demo_hq", "manage"))
        lst = c.get("/api/knowledge-agents", params={"acting_user_id": "7"}).json()
        self.assertFalse(lst["can_register"])
        self.assertEqual([(x["id"], x["editable"]) for x in lst["agents"]], [("kl_demo_hq", True)])
        # kl_x 관리 → 그 에이전트만 / manage on kl_x → that agent only
        rec = c.get(self.base_url("kl_demo_hq"), params={"acting_user_id": "7"}).json()["agent"]
        self.assertEqual(c.put(self.base_url("kl_demo_hq"), json={**echo(rec, enabled=False), "acting_user_id": "7"}).status_code, 200)
        listed = c.get("/api/knowledge-agents", params={"acting_user_id": "7"}).json()["agents"]
        self.assertEqual([(x["id"], x["enabled"]) for x in listed], [("kl_demo_hq", False)])   # 꺼도 목록에 남는다 / stays listed
        self.assertEqual(c.put(self.base_url("kl_demo_hq"), json={**echo(rec, enabled=True), "acting_user_id": "7"}).status_code, 200)
        for r in (c.get(self.base_url(other["id"]), params={"acting_user_id": "7"}),
                  c.put(self.base_url(other["id"]), json={**body(name="다른 에이전트"), "acting_user_id": "7"}),
                  c.delete(self.base_url(other["id"]), params={"acting_user_id": "7"}),
                  c.post("/api/knowledge-agents/check", json={"id": other["id"], "acting_user_id": "7"}),
                  c.delete(f"/api/knowledge-agents/skills/{other_skill['id']}", params={"acting_user_id": "7"})):
            self.assertEqual((r.status_code, r.json()["detail"]), (403, "이 에이전트의 관리 권한이 필요합니다"))
        r = c.post("/api/knowledge-agents", json={**body(name="새 에이전트"), "acting_user_id": "7"})
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "로컬 지식 에이전트를 등록할 권한이 없습니다"))
        # 축 어딘가의 관리(mgmt.p_klocal)라 Skill 업로드 · 자기 에이전트 파일 삭제는 된다 / the tab gate lets them upload and delete their own
        self.assertEqual(c.post("/api/knowledge-agents/skills", params={"acting_user_id": "7"},
                                files={"file": ("n.md", b"n", "text/markdown")}).status_code, 200)
        self.assertEqual(c.delete(f"/api/knowledge-agents/skills/{own_skill['id']}", params={"acting_user_id": "7"}).json(), {"ok": True})
        self.assertIsNotNone(skill_files.get(other_skill["id"]))
        self.assertEqual(c.delete(self.base_url("kl_demo_hq"), params={"acting_user_id": "7"}).json(), {"ok": True})

    def test_view_only_grant_gets_403_on_every_write_but_can_read(self):
        c = self.client
        self.grant(("p_klocal", "view"))
        lst = c.get("/api/knowledge-agents", params={"acting_user_id": "7"}).json()
        self.assertEqual((lst["can_register"], [(x["id"], x["level"], x["editable"]) for x in lst["agents"]]),
                         (False, [("kl_demo_hq", 1, False)]))
        self.assertEqual(c.get(self.base_url("kl_demo_hq") + "/documents", params={"acting_user_id": "7"}).status_code, 200)
        for r in (c.post("/api/knowledge-agents", json={**body(), "acting_user_id": "7"}),
                  c.post("/api/knowledge-agents/skills", params={"acting_user_id": "7"}, files={"file": ("n.md", b"n", "text/markdown")})):
            self.assertEqual(r.status_code, 403)
        for r in (c.get(self.base_url("kl_demo_hq"), params={"acting_user_id": "7"}),
                  c.put(self.base_url("kl_demo_hq"), json={**body(), "acting_user_id": "7"}),
                  c.delete(self.base_url("kl_demo_hq"), params={"acting_user_id": "7"}),
                  c.post(self.base_url("kl_demo_hq") + "/documents", params={"acting_user_id": "7"},
                         files={"file": ("a.txt", b"a", "text/plain")})):
            self.assertEqual((r.status_code, r.json()["detail"]), (403, "이 에이전트의 관리 권한이 필요합니다"))

    def test_manage_exception_on_the_anchor_cannot_register(self):
        """N5(p27): 앵커 레벨이 캐스케이드하지 않는 manage 예외에서만 오면 등록을 되돌리고 403 / a non-cascading anchor exception is rolled back"""
        c = self.client
        self.groups = [{"id": "gx", "name": "로컬 등록 담당", "memberIds": [7], "menus": ["m_home", "m_res"], "grants": [],
                        "exceptions": [{"node": "p_klocal", "type": "manage"}]}]
        eff = access.effective(7)
        self.assertEqual((eff["nodes"].get("p_klocal"), eff["nodes"].get("kl_demo_hq")), (2, None))   # 앵커만 2 / only the anchor is 2
        self.assertTrue(c.get("/api/knowledge-agents", params={"acting_user_id": "7"}).json()["can_register"])
        before = [a["id"] for a in ka.list_agents()]
        r = c.post("/api/knowledge-agents", json={**body(name="예외만 등록"), "acting_user_id": "7"})
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "로컬 지식 에이전트를 등록할 권한이 없습니다"))
        self.assertEqual([a["id"] for a in ka.list_agents()], before)   # 되돌려졌다 / rolled back
        leaves = [x["id"] for n in access.PV_TREE if n["id"] == "m_res" for m in n["children"] if m["id"] == "p_klocal" for x in m["children"]]
        self.assertEqual(leaves, before)   # 유니버스에서도 없다 / not in the universe either
        self.grant(("p_klocal", "manage"))   # 같은 구성원이 앵커 grant 를 받으면 된다 / with an anchor grant it works
        self.assertEqual(c.post("/api/knowledge-agents", json={**body(name="예외만 등록"), "acting_user_id": "7"}).status_code, 201)

    @staticmethod
    def base_url(agent_id: str) -> str:
        return f"/api/knowledge-agents/{agent_id}"


class OAuthCacheTests(_DbCase):
    def setUp(self):
        super().setUp()
        self.calls: dict = {}
        self.transport = mock_transport(self.calls)
        self.agent = ka.create(body(name="OAuth 에이전트", auth=dict(OAUTH)))

    def token_calls(self) -> int:
        return self.calls.get("/mock/kagent/lab/oauth/token", 0)

    def test_cache_until_30s_before_expiry_retry_on_401_and_drop_on_update(self):
        ka.list_documents(self.agent, transport=self.transport)
        ka.list_folders(self.agent, transport=self.transport)
        self.assertEqual(self.token_calls(), 1)   # 캐시 / cached
        (key, (tok, exp)), = ka._TOKENS.items()
        self.assertEqual((key[0], key[2]), (self.agent["id"], mk.OAUTH_CLIENT_ID))
        self.assertTrue(key[1].startswith("http://127.0.0.1:") and key[1].endswith("/mock/kagent/lab/oauth/token"))
        self.assertRegex(key[3], r"^[0-9a-f]{16}$")   # 비밀 지문(비밀 자체는 아니다) / a secret fingerprint, never the secret
        self.assertNotIn(mk.OAUTH_CLIENT_SECRET, json.dumps(key))
        self.assertGreater(exp, time.time() + 3000)
        # 캐시를 버리지 않은 채 비밀만 바뀌어도 옛 비밀로 받은 토큰은 쓰이지 않는다 / a changed secret never reuses the old token
        changed = copy.deepcopy(self.agent)
        changed["config"]["auth"]["client_secret"] = "rotated-secret"
        with self.assertRaises(ka.AgentCallError):   # 새 비밀은 가상 서버가 거부 → 새 발급 시도가 일어났다 / refused → a new fetch happened
            ka.list_documents(changed, transport=self.transport)
        self.assertEqual(self.token_calls(), 2)
        self.assertEqual(len(ka._TOKENS), 1)
        self.calls["/mock/kagent/lab/oauth/token"] = 1
        ka._TOKENS[key] = (tok, time.time() + 20)   # 만료 30초 안 → 새로 발급 / within 30 s of expiry → refetched
        ka.list_documents(self.agent, transport=self.transport)
        self.assertEqual(self.token_calls(), 2)
        ka._TOKENS[key] = ("kat.lab.1.revoked", time.time() + 3000)   # 거부되는 토큰 → 401 → 1번 새로 받아 재시도 / refused → one refetch
        self.assertEqual(len(ka.list_documents(self.agent, transport=self.transport)), mk.seed_count("lab"))
        self.assertEqual(self.token_calls(), 3)
        ka.update(self.agent["id"], echo(ka.editor_record(ka.get_agent(self.agent["id"]))))
        self.assertEqual(ka._TOKENS, {})   # 수정하면 캐시를 버린다 / an update drops the cache
        out = ka.check_saved(self.agent["id"], transport=self.transport)   # 저장된 확인은 새 토큰을 받아 캐시한다 / saved checks refresh and cache
        self.assertTrue(out["ok"])
        self.assertEqual((self.token_calls(), len(ka._TOKENS)), (4, 1))
        ka.delete(self.agent["id"])
        self.assertEqual(ka._TOKENS, {})


class PermissionTests(_DbCase):
    def setUp(self):
        super().setUp()
        self.groups: list = []
        # access 는 실 DB 경로를 직접 쓴다 — 그룹 · 구성원은 가짜로, 저장은 금지 / access binds the real DB: fake groups and members, forbid writes
        self.stack.enter_context(patch.object(access, "list_groups", side_effect=lambda: copy.deepcopy(self.groups)))
        self.stack.enter_context(patch.object(access, "list_members", return_value=[{"no": 7, "dept": "인사총무"}, {"no": 8, "dept": "PMO파트"}]))
        self.stack.enter_context(patch.object(access, "replace_groups", side_effect=AssertionError("실 DB 그룹 저장 금지")))

    def test_team_lead_anchor_cascades_to_new_agents(self):
        self.groups = [{"id": "og9", "name": "팀장", "memberIds": [7], "menus": ["m_home", "m_chat", "m_coll", "m_res"],
                        "grants": [{"node": "p_klocal", "action": "manage"}], "exceptions": []}]
        a = ka.create(body())
        access.rebuild_universe()
        eff = access.effective(7)
        self.assertEqual((eff["nodes"][a["id"]], eff["nodes"]["kl_demo_hq"]), (2, 2))
        self.assertEqual((eff["mgmt"]["p_klocal"], eff["read"]["p_klocal"]), (True, True))
        self.assertEqual((eff["mgmt"]["p_know"], eff["read"]["p_know"]), (False, False))   # p_know 는 그대로 / p_know unchanged
        self.groups[0]["exceptions"] = [{"node": a["id"], "type": "exclude"}]
        eff = access.effective(7)
        self.assertNotIn(a["id"], eff["nodes"])
        self.assertEqual(eff["nodes"]["kl_demo_hq"], 2)
        self.assertFalse(access.effective(8)["read"]["p_klocal"])

    def test_local_only_view_grant_opens_read_klocal_but_not_p_know(self):
        self.groups = [{"id": "og3", "name": "인사총무 표준", "teams": ["인사총무"], "memberIds": [], "menus": ["m_home", "m_chat", "m_res"],
                        "grants": [{"node": "kl_demo_hq", "action": "view"}], "exceptions": []}]
        access.rebuild_universe()
        eff = access.effective(7)
        self.assertEqual(eff["nodes"], {"kl_demo_hq": 1})
        self.assertEqual(eff["read"], {"p_know": False, "p_data": False, "p_auto": False, "p_conn": False, "p_klocal": True})
        self.assertEqual(eff["mgmt"], {"p_know": False, "p_data": False, "p_auto": False, "p_klocal": False})
        self.assertFalse(catalog.domain_readable(eff, "p_know"))

    def test_seed_groups_and_two_argument_set_dynamic(self):
        lead = next(g for g in access.seed_groups(access.seed_members()) if g["id"] == "og9")
        self.assertEqual(lead["name"], "팀장")
        self.assertIn({"node": "p_klocal", "action": "manage"}, lead["grants"])
        catalog.set_dynamic(None, None)   # catalog 모듈 끝의 인자 2개 호출 / the two-argument call at the end of catalog
        mres = next(n for n in catalog.build_pv_tree() if n["id"] == "m_res")
        self.assertEqual(next(ch for ch in mres["children"] if ch["id"] == "p_klocal")["children"], [])

    def test_og9_migration_runs_once_and_only_with_p_know_manage(self):
        conns = []

        def connect():
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            conns.append(conn)
            return conn
        self.stack.enter_context(patch.object(access, "_conn", connect))   # access_meta 도 임시 DB / access_meta on the temp DB too
        self.addCleanup(lambda: [cn.close() for cn in conns])
        with connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS access_meta(k TEXT PRIMARY KEY, v TEXT)")
        saved = []

        def replace(groups):
            saved.append(copy.deepcopy(groups))
            self.groups = copy.deepcopy(groups)

        def reset_flag():
            with connect() as conn:
                conn.execute("DELETE FROM access_meta WHERE k='klocal_og9_v1'")
        with patch.object(access, "replace_groups", side_effect=replace):
            self.groups = [{"id": "og1", "grants": [{"node": "p_know", "action": "manage"}]},
                           {"id": "og9", "grants": [{"node": "p_know", "action": "manage"}, {"node": "p_conn", "action": "view"}]}]
            access._migrate_klocal_og9_v1()
            self.assertEqual(self.groups[1]["grants"][-1], {"node": "p_klocal", "action": "manage"})
            self.assertEqual(self.groups[0]["grants"], [{"node": "p_know", "action": "manage"}])   # og9 만 / og9 only
            access._migrate_klocal_og9_v1()   # 플래그 → 다시 하지 않는다 / flagged: never again
            self.assertEqual(len(saved), 1)
            reset_flag()
            self.groups = [{"id": "og9", "grants": [{"node": "p_know", "action": "view"}]}]   # p_know 관리가 없으면 그대로 / no p_know manage
            access._migrate_klocal_og9_v1()
            reset_flag()
            self.groups = [{"id": "og9", "grants": [{"node": "p_know", "action": "manage"}, {"node": "p_klocal", "action": "view"}]}]
            access._migrate_klocal_og9_v1()   # 이미 p_klocal grant 가 있으면 그대로 / an existing p_klocal grant is left alone
            self.assertEqual(len(saved), 1)


# ────────────────────────────────────────────────────────
# 리뷰 수정(2026-09-29) 회귀 테스트 / regression tests for the review fixes (2026-09-29)
# ────────────────────────────────────────────────────────

def leaked_prefix(text: str, secret: str) -> int:
    """text 안에 남은 secret 앞부분의 최대 길이 / the longest prefix of secret still present in text"""
    return max((n for n in range(len(secret), 0, -1) if secret[:n] in text), default=0)


def leaked_suffix(text: str, secret: str) -> int:
    """text 안에 남은 secret 뒷부분의 최대 길이 / the longest suffix of secret still present in text"""
    return max((n for n in range(len(secret), 0, -1) if secret[-n:] in text), default=0)


def recorder(calls: list, reply=None):
    """요청을 기록하는 가짜 전송 / a fake transport that records requests"""
    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return reply(request) if reply else httpx.Response(200, text="INTERNAL-ONLY")
    return httpx.MockTransport(handle)


class UrlGuardTests(_DbCase):
    """M1: check_url 은 httpx 가 실제로 보낼 경로로 판정한다 / check_url judges the path httpx will actually send"""

    def test_check_url_normalized_path_rules(self):
        with patch.dict(os.environ, {"AI365_BASE_URL": "http://localhost:8000", "FLOW_API_ALLOW_PRIVATE": "0"}):
            for ok in ("http://localhost:8000/mock/erp/v1/inventory", "http://127.0.0.1:8023/mock/kagent/hq/api/v1/documents",
                       "http://127.0.0.1:1/x/../mock/y"):
                flow_api_call.check_url(ok)
            for bad in ("http://127.0.0.1:1/mock/../internal/admin?ignore=", "http://127.0.0.1:1/mock/%2e%2e/internal",
                        "http://127.0.0.1:1/mock/%2E%2E/internal", "http://127.0.0.1:1/mock\\..\\internal",
                        "http://127.0.0.1:1/mock/..;/internal", "http://127.0.0.1:1/mock%2f..%2finternal",
                        "http://127.0.0.1:1/mock/%2e/internal", "http://127.0.0.1:99999/mock/x", "http://127.0.0.1:1/admin",
                        "https://93.184.216.34:0/x", "ftp://x/y", "http:///nohost"):
                with self.assertRaises(ValueError, msg=bad):
                    flow_api_call.check_url(bad)
            # 공인 주소의 인코딩된 / · 일반 인코딩 점(N2) · 쿼리의 역슬래시는 허용 / %2F, ordinary encoded dots (N2), query backslashes pass
            for ok in ("https://93.184.216.34/v1/files/report%2Etxt", "https://93.184.216.34/v1/users/john%2Edoe%40corp.com",
                       "https://93.184.216.34/v1/files/report%2etxt", "https://93.184.216.34/.well-known/openid-configuration"):
                flow_api_call.check_url(ok)
            with patch.object(flow_api_call.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]):
                flow_api_call.check_url("https://erp.example.com/inventory/SKU%2010%2F1?q=a\\b")

    def test_dot_segment_base_url_never_reaches_an_internal_path(self):
        calls: list = []
        a = ka.create(body(name="우회 시도", mcp={"url": "http://127.0.0.1:1/mock/x"}, api={"base_url": "http://127.0.0.1:1/mock/../internal/admin"},
                           auth={"type": "none"}))
        app = FastAPI()
        app.include_router(kapi.router)
        client = TestClient(app)
        with patch.object(ka, "DEFAULT_TRANSPORT", recorder(calls)), \
                patch.object(access, "effective", return_value=member({a["id"]: 1})):
            for path in ("/documents/anything/download", "/documents/anything/preview", "/folders"):
                r = client.get(f"/api/knowledge-agents/{a['id']}{path}", params={"acting_user_id": "7"})
                self.assertEqual(r.status_code, 502, path)
                self.assertNotIn("INTERNAL", r.text)
        self.assertEqual(calls, [])   # check_url 이 막아 전송까지 가지 않는다 / check_url stops it before the transport

    def test_query_in_api_base_url_is_refused_but_allowed_in_mcp_url(self):
        for over in ({"api": {"base_url": "https://kms.example.com/api/v1?ignore="}}, {"api": {"base_url": "https://kms.example.com/api#x"}}):
            with self.assertRaises(V, msg=over) as ctx:
                ka.normalize(body(**over))
            self.assertIn("API Base URL", str(ctx.exception))
            self.assertIn("쿼리", str(ctx.exception))
        # N3: MCP URL 은 뒤에 경로를 붙이지 않으므로 쿼리를 받는다(테넌트 지정 등) / the MCP URL takes a query (tenant selection etc.)
        d = ka.normalize(body(mcp={"url": "https://kms.example.com/mcp?tenant=abc"}))
        self.assertEqual(d["config"]["mcp"]["url"], "https://kms.example.com/mcp?tenant=abc")
        seen = []

        def mcp_server(req):
            seen.append(str(req.url))
            msg = json.loads(req.content)
            if msg.get("id") is None:
                return httpx.Response(202)
            res = {"serverInfo": {"name": "T"}} if msg["method"] == "initialize" else {"tools": []}
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg["id"], "result": res})
        with patch.object(flow_api_call, "check_url"):
            link = ka.AgentLink("", {"mcp": {"url": "https://kms.example.com/mcp?tenant=abc"}, "auth": {"type": "none"}},
                                transport=httpx.MockTransport(mcp_server))
            info, tools, _ = link.mcp_probe()
        self.assertEqual((info["name"], tools), ("T", []))
        self.assertTrue(seen and all(u.endswith("/mcp?tenant=abc") for u in seen))   # 쿼리가 그대로 간다 / the query goes through


class SecretLeakTests(_DbCase):
    """M2: 앞 단계에서 잘린 비밀 조각도 가린다(API · MCP · OAuth) / truncated secret fragments are masked on every path"""
    KEY = "sk-" + "Q7w" * 60   # 183자 / 183 characters

    def test_shared_redact_leaves_ordinary_response_data_untouched(self):
        """N1: 공용 redact 는 정확한 일치(+ Base64 · JSON)만 가린다 — 응답 데이터 · 출력 변수를 망가뜨리지 않는다.
        N1: the shared redact masks exact matches (+ Base64/JSON) only, so response data and outputs stay intact."""
        key = "20260315A7c9Qx2Lm"
        res = {"ok": True, "json": {"order_no": "20260315-0042"}, "outputs": {"order_no": "20260315-0042"},
               "body_text": '{"order_no": "20260315-0042"}', "result_text": "주문 20260315-0042"}
        self.assertEqual(flow_api_call.redact(res, key), res)
        self.assertEqual(flow_api_call.redact("Your password reset link expired", "password123!"), "Your password reset link expired")
        self.assertEqual(flow_api_call.redact("expected a key like sk-proj-... here", "sk-proj-9fQ2mZ7xR1"), "expected a key like sk-proj-... here")
        self.assertEqual(flow_api_call.redact("key=" + key, key), "key=••••••")   # 정확한 일치는 그대로 가린다 / exact matches still masked
        self.assertEqual(flow_api_call.redact("Basic " + base64.b64encode(key.encode()).decode(), key), "Basic ••••••")
        # 워크플로우 API 작업 경로 그대로: 응답에 키 앞 8자가 있어도 결과 데이터가 남는다(flows.py 가 결과 전체를 redact 한다)
        # The workflow API task path as is: a response containing the key's first 8 characters survives (flows.py redacts the whole result)
        api_key = "demo-erp-rotated-2027"
        client = MagicMock()
        client.__enter__.return_value = client
        client.request.return_value = httpx.Response(200, json={"systems": [{"id": "demo-erp", "label": "ERP"}], "total": 1})
        cfg = flow_api_call.normalize({"url": "https://erp.example.com/catalog", "method": "GET",
                                       "auth": {"type": "api_key", "key": api_key, "in": "header", "name": "X-Api-Key"}})
        with patch.object(flow_api_call, "check_url"), patch.object(flow_api_call.httpx, "Client", return_value=client):
            out = flow_api_call.redact(flow_api_call.call(cfg, flow_api_call.build_ctx()), api_key)
        self.assertEqual(out["json"], {"systems": [{"id": "demo-erp", "label": "ERP"}], "total": 1})
        self.assertIn("demo-erp", out["body_text"])
        self.assertNotIn(api_key, json.dumps(out, ensure_ascii=False))

    def test_diagnostic_redaction_forms_and_trailing_fragments(self):
        secret = "abcdefghijKLMNOPQRSTUV"
        self.assertEqual(ka.redact_diagnostic("error Bearer abcdefghijKLMNOP", [secret]), "error Bearer ••••••")   # 끝에 잘린 조각 / cut at the end
        self.assertEqual(ka.redact_diagnostic("x " + secret + " y", [secret]), "x •••••• y")
        self.assertEqual(ka.redact_diagnostic("ends abcdefg", ["abcdefgh"]), "ends abcdefg")   # 8자 미만 조각은 둔다 / < 8 chars stays
        # 문장 중간의 우연한 앞부분 일치는 건드리지 않는다 / an accidental prefix match mid-sentence is left alone
        self.assertEqual(ka.redact_diagnostic("Your password reset failed", ["password123!"]), "Your password reset failed")
        plus = "Zx9Kq2Lm+Pw7/Rt4Yv8=Nb3Hc6Jd1"
        for form in (plus, quote(plus, safe=""), quote_plus(plus), base64.b64encode(plus.encode()).decode(), json.dumps(plus)[1:-1]):
            self.assertEqual(ka.redact_diagnostic("body: client_secret=" + form + "&x=1", [plus]), "body: client_secret=••••••&x=1", form)
        self.assertEqual(ka.redact_diagnostic("cut: " + quote_plus(plus)[:14], [plus]), "cut: ••••••")

    def test_long_bearer_key_on_the_api_and_mcp_paths(self):
        a = ka.create(body(name="유출 점검", mcp={"url": "https://kms.example.com/mcp"}, api={"base_url": "https://kms.example.com/api"},
                           auth={"type": "bearer", "key": self.KEY}))

        def echo_api(req):
            return httpx.Response(401, json={"error": {"message": "invalid credentials: " + req.headers.get("authorization", "")}})
        app = FastAPI()
        app.include_router(kapi.router)
        client = TestClient(app)
        with patch.object(ka, "DEFAULT_TRANSPORT", httpx.MockTransport(echo_api)), patch.object(flow_api_call, "check_url"), \
                patch.object(access, "effective", return_value=member({a["id"]: 1})):
            r = client.get(f"/api/knowledge-agents/{a['id']}/documents", params={"acting_user_id": "7"})
        self.assertEqual(r.status_code, 502)
        self.assertLess(leaked_prefix(r.json()["detail"], self.KEY), ka.FRAGMENT_MIN)

        def echo_mcp(req):
            if req.url.path.endswith("/health"):
                return httpx.Response(200, json={"status": "ok", "capabilities": ["list"]})
            if not req.content:
                return httpx.Response(200, json=[])
            msg = json.loads(req.content)
            if msg.get("id") is None:
                return httpx.Response(202)
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg["id"],
                                             "error": {"code": -32001, "message": "x" * 200 + " bad token " + req.headers.get("authorization", "")}})
        with patch.object(flow_api_call, "check_url"):
            res = ka.check({"mcp": {"url": "https://kms.example.com/mcp"}, "api": {"base_url": "https://kms.example.com/api"},
                            "auth": {"type": "bearer", "key": self.KEY}}, transport=httpx.MockTransport(echo_mcp))
            saved = ka.check_saved(a["id"], transport=httpx.MockTransport(echo_mcp))
        self.assertLess(leaked_prefix(json.dumps(res, ensure_ascii=False), self.KEY), ka.FRAGMENT_MIN)
        self.assertLess(leaked_prefix(json.dumps(saved, ensure_ascii=False), self.KEY), ka.FRAGMENT_MIN)
        stored = json.dumps(ka.get_agent(a["id"])["status"], ensure_ascii=False)   # 저장된 상태에도 없다 / not in the stored status
        self.assertLess(leaked_prefix(stored, self.KEY), ka.FRAGMENT_MIN)

    def test_long_oauth_secret_and_token_are_masked(self):
        secret = "cs-" + "Z9y" * 60
        token = "tok-" + "M3n" * 70

        def server(req):
            p = req.url.path
            if p.endswith("/token"):   # 토큰 엔드포인트가 받은 비밀을 오류에 되돌려 준다 / the token endpoint echoes the secret
                sent = dict(x.split("=", 1) for x in req.content.decode().split("&"))
                if sent.get("client_secret") != secret:
                    return httpx.Response(401, json={"error": "invalid_client", "error_description": "bad secret " + sent.get("client_secret", "")})
                return httpx.Response(200, json={"access_token": token, "expires_in": 3600})
            if p.endswith("/mcp"):   # MCP 서버가 받은 토큰을 오류에 되돌려 준다 / the MCP server echoes the token
                msg = json.loads(req.content)
                if msg.get("id") is None:
                    return httpx.Response(202)
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg["id"],
                                                 "error": {"code": -32001, "message": "y" * 200 + " " + req.headers.get("authorization", "")}})
            return httpx.Response(500, text="echo " + req.headers.get("authorization", ""))
        draft = {"mcp": {"url": "https://kms.example.com/mcp"}, "api": {"base_url": "https://kms.example.com/api"},
                 "auth": {"type": "oauth2", "token_url": "https://kms.example.com/token", "client_id": "c1", "client_secret": secret}}
        with patch.object(flow_api_call, "check_url"):
            good = ka.check(draft, transport=httpx.MockTransport(server))
            bad = ka.check({**draft, "auth": {**draft["auth"], "client_secret": secret[:-1] + "X"}}, transport=httpx.MockTransport(server))
        text = json.dumps([good, bad], ensure_ascii=False)
        self.assertIn("OAuth 토큰 발급 실패", bad["api"]["error"])
        for s in (secret, secret[:-1] + "X", token):
            self.assertLess(leaked_prefix(text, s), ka.FRAGMENT_MIN)

    def test_url_encoded_secret_echoed_by_the_token_endpoint(self):
        """N4(p26): 폼 본문(URL 인코딩)을 그대로 되돌려 주는 토큰 엔드포인트 / a token endpoint echoing the url-encoded form"""
        secret = "Zx9Kq2Lm+Pw7/Rt4Yv8=Nb3Hc6Jd1"

        def echo_form(req):
            if req.url.path.endswith("/token"):
                return httpx.Response(400, json={"error": "invalid_client", "error_description": "rejected body: " + req.content.decode()})
            return httpx.Response(200, json=[])
        draft = {"mcp": {"url": "https://idp.example.com/mcp"}, "api": {"base_url": "https://idp.example.com/api"},
                 "auth": {"type": "oauth2", "token_url": "https://idp.example.com/oauth/token", "client_id": "ai365", "client_secret": secret}}
        with patch.object(flow_api_call, "check_url"):
            res = ka.check(draft, transport=httpx.MockTransport(echo_form))
        text = json.dumps(res, ensure_ascii=False)
        self.assertIn("rejected body", res["mcp"]["error"])
        self.assertEqual(leaked_suffix(res["mcp"]["error"], quote_plus(secret)), 0)   # p26 의 측정 그대로 / p26's own measure
        for form in (secret, quote(secret, safe=""), quote_plus(secret)):
            self.assertLess(leaked_prefix(text, form), ka.FRAGMENT_MIN, form)
            self.assertLess(leaked_suffix(text, form), 3, form)


class NonSuccessStatusTests(_DbCase):
    """M3: 2xx 가 아닌 응답(리다이렉트 포함)과 미리보기 · 다운로드의 204 는 실패 / non-2xx (redirects too) and 204 on files are failures"""

    def setUp(self):
        super().setUp()
        app = FastAPI()
        app.include_router(kapi.router)
        self.client = TestClient(app)
        self.base = "/api/knowledge-agents/kl_demo_hq"

    def test_redirects_and_empty_bodies(self):
        c = self.client
        redirect = httpx.MockTransport(lambda req: httpx.Response(302, headers={"location": "https://blob.example.com/signed?sig=abc"}))
        with patch.object(ka, "DEFAULT_TRANSPORT", redirect):
            for r in (c.get(self.base + "/documents/hq-doc-003/download"), c.delete(self.base + "/documents/hq-doc-003"),
                      c.get(self.base + "/documents/hq-doc-003/preview"), c.get(self.base + "/documents")):
                self.assertEqual(r.status_code, 502)
                self.assertIn("리다이렉트는 따르지 않습니다(HTTP 302)", r.json()["detail"])
        with patch.object(ka, "DEFAULT_TRANSPORT", httpx.MockTransport(lambda req: httpx.Response(204))):
            for path in ("/documents/hq-doc-003/download", "/documents/hq-doc-003/preview"):
                r = c.get(self.base + path)
                self.assertEqual((r.status_code, r.json()["detail"]), (502, "에이전트에 연결하지 못했습니다: 에이전트가 빈 응답을 보냈습니다(HTTP 204)"))
            self.assertEqual(c.delete(self.base + "/documents/hq-doc-003").json(), {"ok": True})   # 삭제의 204 는 성공 / 204 on delete is fine


class LatencyTests(unittest.TestCase):
    """M4: localhost → 127.0.0.1 재작성 · 공용 SSL 컨텍스트 / the localhost rewrite and the shared SSL context"""

    def test_resolve_rewrites_only_the_localhost_host(self):
        with patch.dict(os.environ, {"AI365_BASE_URL": "http://localhost:9999"}):
            self.assertEqual(ka._resolve("{{base_url}}/mock/kagent/hq/api/v1"), "http://127.0.0.1:9999/mock/kagent/hq/api/v1")
        for raw, want in (("http://LOCALHOST/x", "http://127.0.0.1/x"), ("https://u:p@localhost:8443/x", "https://u:p@127.0.0.1:8443/x"),
                          ("http://localhost", "http://127.0.0.1"), ("http://localhost.example.com/x", "http://localhost.example.com/x"),
                          ("http://mylocalhost:1/x", "http://mylocalhost:1/x"), ("http://kms/localhost/x", "http://kms/localhost/x")):
            self.assertEqual(ka._resolve(raw), want)

    def test_one_ssl_context_is_built_and_shared(self):
        with patch.object(ka, "_SSL_CONTEXT", None), patch.object(ka.httpx, "create_ssl_context", wraps=httpx.create_ssl_context) as made:
            first = ka._ssl_context()
            self.assertIs(ka._ssl_context(), first)
            link = ka.AgentLink("x", {"api": {"base_url": "https://kms.example.com/api"}})
            with link.client() as c1, link.client() as c2:
                self.assertIsNot(c1, c2)
            self.assertEqual(made.call_count, 1)


class BootSanitizeTests(_DbCase):
    """M5: 읽기에 실패한 동적 축의 grant · 예외는 부팅 정리가 지우지 않는다 / boot sanitize keeps items of a failed loader"""

    def setUp(self):
        super().setUp()
        conns = []

        def connect():
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            conns.append(conn)
            return conn
        # access 도 임시 DB 로(실 DB 에 쓰지 않는다) / access on the temp DB too (never the real DB)
        self.stack.enter_context(patch.object(access, "DB_PATH", self.path))
        self.stack.enter_context(patch.object(access, "_conn", connect))
        self.addCleanup(lambda: [c.close() for c in conns])

    def edit_group(self, gid: str, **fields):
        groups = access.list_groups()
        for g in groups:
            if g["id"] == gid:
                g.update(fields)
        access.replace_groups(groups)

    def group(self, gid: str) -> dict:
        return next(g for g in access.list_groups() if g["id"] == gid)

    def test_locked_summaries_at_boot_keep_the_exclude(self):
        access.init_access()
        og3 = self.group("og3")
        self.edit_group("og3", grants=og3["grants"] + [{"node": "p_klocal", "action": "view"}],
                        exceptions=[{"node": "kl_demo_hq", "type": "exclude"}, {"node": "kl_gone0000", "type": "exclude"}])
        with patch.object(ka, "summaries", side_effect=sqlite3.OperationalError("database is locked")), \
                self.assertLogs("ai365.access", level="WARNING"):
            access.init_access()
        self.assertEqual(access._LOADER_GAPS, {"kl_"})
        self.assertEqual(self.group("og3")["exceptions"], [{"node": "kl_demo_hq", "type": "exclude"}, {"node": "kl_gone0000", "type": "exclude"}])
        access.init_access()   # 정상 부팅은 진짜 고아(kl_gone0000)만 지운다 / a healthy boot prunes only the real orphan
        self.assertEqual(access._LOADER_GAPS, set())
        self.assertEqual(self.group("og3")["exceptions"], [{"node": "kl_demo_hq", "type": "exclude"}])
        leads = set(self.group("og9")["memberIds"])
        m = next(x for x in access.list_members() if x.get("dept") == "인사총무" and x["no"] not in leads)
        self.assertNotIn("kl_demo_hq", access.effective(m["no"])["nodes"])   # 예외가 살아 있다 / the exclude still holds

    def test_knowledge_loader_failure_keeps_public_folder_excludes(self):
        """p25: 지식 트리 읽기 실패(잠김)로 부팅하면 f_/kf_/ws_/sl_ 정리 보류, 정상 부팅은 진짜 고아만 지운다.
        A boot with the knowledge-tree read failing (locked) holds f_/kf_/ws_/sl_ pruning; a normal boot prunes real orphans only."""
        access.init_access()
        tree = access.load_knowledge()
        tree.append({"id": "f_custom", "label": "사용자 폴더", "folders": [], "files": []})
        access.save_knowledge(tree)
        self.assertIn("f_custom", access.PV_NODES)
        excludes = [{"node": "f_custom", "type": "exclude"}, {"node": "f_gone0000", "type": "exclude"}]
        self.edit_group("og4", exceptions=list(excludes))
        with patch.object(access, "load_knowledge", side_effect=sqlite3.OperationalError("database is locked")), \
                self.assertLogs("ai365.access", level="WARNING"):
            access.init_access()
        self.assertEqual(access._LOADER_GAPS, {"f_", "kf_", "ws_", "sl_"})
        self.assertEqual(self.group("og4")["exceptions"], excludes)
        access.init_access()
        self.assertEqual(access._LOADER_GAPS, set())
        self.assertEqual(self.group("og4")["exceptions"], [{"node": "f_custom", "type": "exclude"}])   # 진짜 고아만 / the real orphan only
        # 표가 없는 것(최초 부팅)은 정리 보류 대상이 아니다 / a missing table (first boot) is not a gap
        with patch.object(access, "load_knowledge", side_effect=sqlite3.OperationalError("no such table: access_knowledge")):
            access.rebuild_universe()
        self.assertEqual(access._LOADER_GAPS, set())
        with patch.object(access, "list_workspaces", side_effect=sqlite3.OperationalError("disk I/O error")), \
                self.assertLogs("ai365.access", level="WARNING"):
            access.rebuild_universe()
        self.assertEqual(access._LOADER_GAPS, {"f_", "kf_", "ws_", "sl_"})
        access.rebuild_universe()

    def test_connector_and_work_agent_loader_failures_are_recorded(self):
        with patch.object(connectors, "list_connectors", side_effect=sqlite3.OperationalError("database is locked")), \
                patch("app.work_agents.summaries", side_effect=RuntimeError("boom")):
            access.rebuild_universe()
            self.assertEqual(access._LOADER_GAPS, {"cn_", "agent_"})
        access.rebuild_universe()
        self.assertEqual(access._LOADER_GAPS, set())


class RobustCheckTests(_DbCase):
    """L1: MCP 본문 읽기 오류와 이상한 /health 는 500 이 아니라 실패 행 / body-read errors and odd /health are failed rows, not 500s"""

    class Stall(httpx.SyncByteStream):
        def __iter__(self):
            raise httpx.ReadTimeout("timed out")
            yield b""   # noqa — 제너레이터로 만든다 / makes it a generator

    def test_stalled_mcp_body_and_malformed_capabilities(self):
        def stalled(req):
            if req.url.path.endswith("/mcp"):
                return httpx.Response(200, headers={"content-type": "application/json"}, stream=self.Stall())
            if req.url.path.endswith("/health"):
                return httpx.Response(200, json={"status": "ok", "capabilities": list(ka.CAPABILITIES)})
            return httpx.Response(200, json=[])
        draft = {"mcp": {"url": "https://kms.example.com/mcp"}, "api": {"base_url": "https://kms.example.com/api"}, "auth": {"type": "none"}}
        app = FastAPI()
        app.include_router(kapi.router)
        client = TestClient(app, raise_server_exceptions=False)
        with patch.object(ka, "DEFAULT_TRANSPORT", httpx.MockTransport(stalled)), patch.object(flow_api_call, "check_url"):
            r = client.post("/api/knowledge-agents/check", json={"draft": draft})
            self.assertEqual(r.status_code, 200)
            self.assertIn("ReadTimeout", r.json()["mcp"]["error"])
            self.assertTrue(r.json()["api"]["ok"])
            a = ka.create(body(name="멈춘 MCP", **draft))
            r = client.post("/api/knowledge-agents/check", json={"id": a["id"]})
            self.assertEqual((r.status_code, r.json()["agent"]["status"]["state"]), (200, "error"))

        def health(caps):
            def handle(req):
                if req.url.path.endswith("/health"):
                    return httpx.Response(200, json={"status": "ok", "capabilities": caps})
                return httpx.Response(200, json=[])
            return httpx.MockTransport(handle)
        for caps in (5, {"list": True, "upload": True}, None, "list,upload"):
            with patch.object(ka, "DEFAULT_TRANSPORT", health(caps)), patch.object(flow_api_call, "check_url"):
                r = client.post("/api/knowledge-agents/check", json={"draft": draft})
            self.assertEqual(r.status_code, 200, caps)
            self.assertEqual(r.json()["api"]["capabilities"], [], caps)   # 배열만 읽는다 / lists only
            self.assertFalse(r.json()["api"]["ok"], caps)


class UploadLimitTests(_DbCase):
    """L4: Content-Length 가 상한을 넘으면 본문 파싱 · 권한 판정 전에 413 / 413 before parsing when Content-Length is over the cap"""

    def test_oversize_content_length_is_refused_before_the_handler(self):
        app = FastAPI()
        app.include_router(kapi.router)
        client = TestClient(app)
        with patch.object(ka, "MAX_UPLOAD_BYTES", 8), patch.object(kapi, "_proxy_agent", side_effect=AssertionError("핸들러까지 오면 안 된다")):
            r = client.post("/api/knowledge-agents/kl_demo_hq/documents", files={"file": ("big.txt", b"x" * (kapi.MULTIPART_SLACK + 64), "text/plain")})
            expected = kapi._too_large_detail()
        self.assertEqual((r.status_code, r.json()["detail"]), (413, expected))
        with patch.object(ka, "MAX_UPLOAD_BYTES", 8), patch.object(ka, "DEFAULT_TRANSPORT", mock_transport()):
            r = client.post("/api/knowledge-agents/kl_demo_hq/documents", files={"file": ("small.txt", b"123456789", "text/plain")})
        self.assertEqual(r.status_code, 413)   # 여유 안의 본문은 핸들러의 크기 검사가 막는다 / within the slack, the handler's own check applies
        other = client.get("/api/knowledge-agents")   # 다른 경로는 그대로 / other routes are untouched
        self.assertEqual(other.status_code, 200)


class DeadlineTests(unittest.TestCase):
    """L9: 본문 전체 읽기 마감 시각 / the total body-read deadline"""

    def test_read_capped_and_stream_stop_after_the_deadline(self):
        resp = httpx.Response(200, content=b"abc")
        with self.assertRaises(ka.AgentCallError) as ctx:
            ka._read_capped(resp, 100, time.monotonic() - 1)
        self.assertIn("제한 시간", ctx.exception.reason)
        self.assertEqual(ka._read_capped(httpx.Response(200, content=b"abc"), 100, time.monotonic() + 60), b"abc")
        client = MagicMock()
        stream = ka.DocStream(httpx.Response(200, content=b"abc"), client, ka.AgentLink("x", {}), deadline=time.monotonic() - 1)
        with self.assertRaises(ka.AgentCallError):
            list(stream.iter_bytes())
        client.close.assert_called_once()   # 중단해도 연결을 닫는다 / the connection is closed on abort
        self.assertGreaterEqual(ka._deadline(30) - time.monotonic(), 59)
        self.assertGreaterEqual(ka._deadline(30, ka.STREAM_DEADLINE_MIN) - time.monotonic(), ka.STREAM_DEADLINE_MIN - 1)


class LocalLlmMigrationTests(_DbCase):
    """로컬 LLM = Qwen 3.5-4B(2026-10-06 사용자 지시) — 기본값 · 데모 시드 · 옛 qwen-3.8m 1회 이전, 사용자가 고른 모델은 그대로.
    Local LLM = Qwen 3.5-4B (user instruction 2026-10-06): default, demo seed and a one-time move off qwen-3.8m; user picks stay."""

    def _set_model(self, agent_id, model):
        with ka._tx() as conn:
            cfg = json.loads(conn.execute("SELECT config FROM knowledge_agents WHERE id=?", (agent_id,)).fetchone()["config"])
            cfg["settings"]["llm"]["model"] = model
            conn.execute("UPDATE knowledge_agents SET config=? WHERE id=?", (json.dumps(cfg), agent_id))

    def _model(self, agent_id):
        return ka.get_agent(agent_id)["config"]["settings"]["llm"]["model"]

    def test_default_and_seed_use_qwen(self):
        self.assertEqual(ka.default_settings()["llm"], {"type": "local", "model": "qwen-3.5-4b"})
        self.assertEqual(ka.LLM_MODELS["local"][0], "qwen-3.5-4b")
        self.assertNotIn("qwen-3.8m", ka.LLM_MODELS["local"])
        self.assertEqual(self._model(ka.SEED_ID), "qwen-3.5-4b")
        self.assertEqual(ka.normalize_settings({"llm": {"type": "local"}})["llm"]["model"], "qwen-3.5-4b")

    def test_migration_runs_once_and_keeps_later_choices(self):
        rec = ka._seed_record()
        with ka._tx() as conn:   # 옛 상태 재현: 옛 기본값 시드 + 없어진 모델을 쓰는 에이전트 / the old state
            conn.execute("DELETE FROM knowledge_agents_meta WHERE k=?", (ka.LLM_MIGRATE_FLAG,))
            conn.execute("INSERT INTO knowledge_agents(id, name, description, enabled, config, status, pos, created_at, updated_at)"
                         " VALUES('kl_old38m','옛 에이전트','',1,?,?,1,?,?)",
                         (json.dumps(rec["config"]), json.dumps(rec["status"]), rec["created_at"], rec["created_at"]))
        self._set_model(ka.SEED_ID, "deepseek-v4-pro")
        self._set_model("kl_old38m", "qwen-3.8m")
        ka._migrate_local_llm()
        self.assertEqual((self._model(ka.SEED_ID), self._model("kl_old38m")), ("qwen-3.5-4b", "qwen-3.5-4b"))
        self._set_model(ka.SEED_ID, "deepseek-v4-pro")   # 이후 사용자가 고른 값은 다시 바꾸지 않는다 / later picks stay
        ka._migrate_local_llm()
        self.assertEqual(self._model(ka.SEED_ID), "deepseek-v4-pro")


class SeedNameMigrationTests(_DbCase):
    """데모 에이전트 이름 '본사 지식 에이전트' → '본사 로컬 에이전트'(2026-10-07 사용자 지시) — 새 시드, 옛 DB 1회 변경,
    사용자가 고친 이름 · 이미 쓰인 이름은 그대로, 플래그로 한 번만.
    The demo agent is renamed (user request 2026-10-07): the new seed, a one-time rename of old databases, user edits and a taken
    name left alone, and a flag so it runs once."""

    def _old_state(self, name=None, description=None):
        with ka._tx() as conn:   # 이름 변경 전 DB 재현 / an old database before the rename
            conn.execute("DELETE FROM knowledge_agents_meta WHERE k=?", (ka.SEED_NAME_FLAG,))
            conn.execute("UPDATE knowledge_agents SET name=?, description=? WHERE id=?",
                         (name or ka.SEED_NAME_OLD, description or ka.SEED_DESCRIPTION_OLD, ka.SEED_ID))

    def _seed(self):
        a = ka.get_agent(ka.SEED_ID)
        return a["name"], a["description"]

    def test_new_seed_uses_the_local_name(self):
        self.assertEqual(self._seed(), ("본사 로컬 에이전트", "본사 사내 규정과 영업 자료를 검색하고 답변하는 로컬 에이전트"))
        self.assertEqual((ka._seed_record()["name"], ka._seed_record()["description"]), (ka.SEED_NAME, ka.SEED_DESCRIPTION))

    def test_old_database_is_renamed_once(self):
        self._old_state()
        ka._migrate_seed_name()
        self.assertEqual(self._seed(), (ka.SEED_NAME, ka.SEED_DESCRIPTION))
        with ka._tx() as conn:   # 다시 옛 이름으로 고쳐도(사용자가 고친 것) 두 번째는 돌지 않는다 / a later edit back is kept
            conn.execute("UPDATE knowledge_agents SET name=? WHERE id=?", (ka.SEED_NAME_OLD, ka.SEED_ID))
        ka._migrate_seed_name()
        self.assertEqual(self._seed()[0], ka.SEED_NAME_OLD)

    def test_user_edits_and_a_taken_name_are_left_alone(self):
        self._old_state(name="우리 회사 에이전트", description="직접 쓴 설명")
        ka._migrate_seed_name()
        self.assertEqual(self._seed(), ("우리 회사 에이전트", "직접 쓴 설명"))
        self._old_state()
        ka.create(body(name="본사 로컬 에이전트"))   # 새 이름을 다른 에이전트가 이미 쓴다 / another agent already has the new name
        ka._migrate_seed_name()
        self.assertEqual(self._seed(), (ka.SEED_NAME_OLD, ka.SEED_DESCRIPTION))   # 이름은 두고 설명만 / description only


if __name__ == "__main__":
    unittest.main()
