# -*- coding: utf-8 -*-
"""가상 고객 배포 /mock/kagent(2026-09-29) — JSON-RPC 순수 처리 · 인증 3종 · OAuth · 문서 API · 처리 상태 시간 · 시드.
임시 DB, 네트워크 · LLM 없음.

Fictional customer deployment /mock/kagent (2026-09-29): pure JSON-RPC handling, the three auth kinds, OAuth, the
document API, processing timing and seeds. Temp DB; no network or LLM."""
import io
import json
import sqlite3
import unittest
import zipfile
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import mcp_client, mcp_servers, mock_kagent as mk
from tests.db_fixture import isolate_db

BEARER = {"Authorization": f"Bearer {mk.DEMO_KEY}"}


def rpc(method, params=None, mid=1):
    msg = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def call(tenant, name, args, auth=None):
    return mk.handle(tenant, rpc("tools/call", {"name": name, "arguments": args}), auth or BEARER["Authorization"])


def mock_app() -> FastAPI:
    app = FastAPI()
    app.include_router(mk.router)
    return app


def mock_transport(counter: dict | None = None) -> httpx.MockTransport:
    """httpx 요청을 앱 안의 가상 배포 라우터로 넘기는 전송(실제 포트에 접속하지 않는다). counter 에 경로별 호출 수를 센다.
    A transport that hands httpx requests to the in-process mock router (never touches a real port); counts calls per path."""
    client = TestClient(mock_app())

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode("ascii")
        if counter is not None:
            key = request.url.path
            counter[key] = counter.get(key, 0) + 1
        headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length", "transfer-encoding")}
        r = client.request(request.method, path, headers=headers, content=request.content)
        out_headers = [(k, v) for k, v in r.headers.items() if k.lower() not in ("content-length", "content-encoding", "transfer-encoding")]
        return httpx.Response(r.status_code, headers=out_headers, content=r.content)

    return httpx.MockTransport(handler)


class _DbCase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        isolate_db(self.stack)
        self.addCleanup(self.stack.close)


class HandleTests(_DbCase):
    def test_auth_tenant_and_handshake(self):
        status, body = mk.handle("hq", rpc("tools/list"), None)
        self.assertEqual((status, body["error"]["code"]), (401, -32001))
        self.assertEqual(mk.handle("hq", rpc("tools/list"), "Bearer wrong")[0], 401)
        self.assertEqual(mk.handle("nowhere", rpc("ping"), BEARER["Authorization"])[0], 404)
        status, body = mk.handle("hq", rpc("initialize", {"protocolVersion": "2025-03-26"}), BEARER["Authorization"])
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(body["result"]["serverInfo"], mk.TENANTS["hq"]["server_info"])
        self.assertEqual(mk.handle("hq", rpc("initialize", {"protocolVersion": "1999-01-01"}), BEARER["Authorization"])[1]["result"]["protocolVersion"],
                         mk.PROTOCOL)
        self.assertEqual(mk.handle("hq", {"jsonrpc": "2.0", "method": "notifications/initialized"}, BEARER["Authorization"]), (202, None))
        self.assertEqual(mk.handle("hq", rpc("ping"), None, mk.DEMO_KEY)[1]["result"], {})   # X-API-Key 도 통과 / X-API-Key works too
        self.assertEqual(mk.handle("hq", rpc("nope"), BEARER["Authorization"])[1]["error"]["code"], -32601)
        self.assertEqual(mk.handle("hq", "junk", BEARER["Authorization"])[0], 400)

    def test_tools_list_specs(self):
        status, body = mk.handle("lab", rpc("tools/list"), BEARER["Authorization"])
        tools = {t["name"]: t for t in body["result"]["tools"]}
        self.assertEqual(list(tools), ["kb_chat", "kb_search", "kb_get_document"])
        for t in tools.values():
            self.assertTrue(t["annotations"]["readOnlyHint"])
            self.assertIn("inputSchema", t)
            self.assertIn("outputSchema", t)
        self.assertIn("sources", tools["kb_chat"]["outputSchema"]["properties"])
        self.assertEqual(tools["kb_search"]["inputSchema"]["required"], ["query"])
        # 우리 MCP 정규화를 그대로 통과하고 전부 조회(read) 도구가 된다 / our MCP normalization accepts them all as read tools
        norm = mcp_servers.normalize_tools(mcp_servers.merge_tools([mcp_client.normalize_tool(t) for t in body["result"]["tools"]], None)[0])
        self.assertEqual([(t["name"], t["kind"]) for t in norm], [("kb_chat", "read"), ("kb_search", "read"), ("kb_get_document", "read")])

    def test_kb_search_chat_and_get_document(self):
        hits = call("hq", "kb_search", {"query": "비밀번호 변경 주기는?"})[1]["result"]["structuredContent"]["hits"]
        self.assertEqual(hits[0]["doc_id"], "hq-doc-001")
        self.assertEqual(hits[0]["folder_id"], "hq-rules")
        self.assertIn("비밀번호", hits[0]["snippet"])
        self.assertLessEqual(len(hits[0]["snippet"]), 125)
        self.assertTrue(0 < hits[0]["score"] < 1)
        # 폴더 필터는 하위 폴더를 포함한다 / a folder filter covers its subfolders
        scoped = call("hq", "kb_search", {"query": "개인정보", "folder_ids": ["hq-rules"]})[1]["result"]["structuredContent"]["hits"]
        self.assertEqual({h["folder_id"] for h in scoped} - {"hq-rules", "hq-security"}, set())
        self.assertIn("hq-doc-002", [h["doc_id"] for h in scoped])
        self.assertEqual(call("hq", "kb_search", {"query": "개인정보", "folder_ids": ["hq-sales"]})[1]["result"]["structuredContent"]["hits"][0]["doc_id"],
                         "hq-doc-004")
        res = call("hq", "kb_chat", {"question": "비밀번호는 며칠마다 변경하나요?"})[1]["result"]
        chat = res["structuredContent"]
        self.assertFalse(res["isError"])
        self.assertEqual(chat["model"], "Qwen 3.5-4B")
        self.assertIn("90일", chat["answer"])
        self.assertEqual(chat["sources"][0]["doc_id"], "hq-doc-001")
        self.assertEqual(chat["sources"][0]["page"], 1)
        self.assertEqual(res["content"][0]["text"], chat["answer"])
        self.assertLessEqual(len(call("hq", "kb_chat", {"question": "문서 규정 정책 보안 영업", "top_k": 2})[1]["result"]["structuredContent"]["sources"]), 2)
        lab = call("lab", "kb_chat", {"question": "리튬 화재 소화기"})[1]["result"]["structuredContent"]
        self.assertEqual(lab["model"], "Qwen 3.5-4B")
        self.assertEqual(lab["sources"][0]["doc_id"], "lab-doc-003")
        none = call("lab", "kb_chat", {"question": "zzqqxx"})[1]["result"]["structuredContent"]
        self.assertEqual(none["sources"], [])
        self.assertIn("찾지 못했습니다", none["answer"])
        doc = call("lab", "kb_get_document", {"doc_id": "lab-doc-004"})[1]["result"]["structuredContent"]
        self.assertEqual((doc["title"], doc["folder_id"]), ("장비 사용 매뉴얼.txt", "lab-manual"))
        self.assertIn("충방전", doc["text"])
        # 테넌트는 서로의 문서를 보지 못한다 / tenants never see each other's documents
        self.assertTrue(call("hq", "kb_get_document", {"doc_id": "lab-doc-004"})[1]["result"]["isError"])
        self.assertTrue(call("hq", "kb_chat", {})[1]["result"]["isError"])
        self.assertTrue(call("hq", "kb_search", {"query": "보안", "top_k": 99})[1]["result"]["isError"])
        self.assertTrue(call("hq", "kb_search", {"query": "보안", "folder_ids": "hq-rules"})[1]["result"]["isError"])
        self.assertEqual(call("hq", "kb_delete_all", {})[1]["error"]["code"], -32602)

    def test_search_terms_strip_particles_and_stopwords(self):
        self.assertEqual(mk._terms("정보보안 규정에서 비밀번호 변경 주기는 알려줘"), ["정보보안", "규정", "비밀번호", "변경", "주기"])
        self.assertEqual(mk._terms("비밀번호는 며칠마다 변경하나요?"), ["비밀번호", "며칠", "변경"])
        self.assertEqual(mk._terms("?! 가 a"), [])


class OAuthTests(_DbCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(mock_app())

    def token(self, tenant="hq", **over):
        form = {"grant_type": "client_credentials", "client_id": mk.OAUTH_CLIENT_ID, "client_secret": mk.OAUTH_CLIENT_SECRET, **over}
        return self.client.post(f"/mock/kagent/{tenant}/oauth/token", data=form)

    def test_token_flow(self):
        r = self.token()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual((body["token_type"], body["expires_in"]), ("Bearer", 3600))
        tok = {"Authorization": "Bearer " + body["access_token"]}
        self.assertEqual(self.client.get("/mock/kagent/hq/api/v1/health", headers=tok).status_code, 200)
        self.assertEqual(self.client.post("/mock/kagent/hq/mcp", json=rpc("ping"), headers=tok).status_code, 200)
        # 다른 테넌트 · 변조 · 만료 토큰은 거부 / another tenant's, tampered and expired tokens are refused
        self.assertEqual(self.client.get("/mock/kagent/lab/api/v1/health", headers=tok).status_code, 401)
        auth = tok["Authorization"]
        tampered = auth[:-1] + ("1" if auth[-1] == "0" else "0")   # 항상 다른 글자로 바꾼다(끝이 0 이면 그대로였다) / always a different char
        self.assertNotEqual(tampered, auth)
        self.assertEqual(self.client.get("/mock/kagent/hq/api/v1/health", headers={"Authorization": tampered}).status_code, 401)
        with patch.object(mk, "_clock", return_value=mk._clock() + mk.TOKEN_TTL + 5):
            self.assertEqual(self.client.get("/mock/kagent/hq/api/v1/health", headers=tok).status_code, 401)
        self.assertEqual(self.token(client_secret="wrong").status_code, 401)
        self.assertEqual(self.token(client_secret="wrong").json()["error"], "invalid_client")
        self.assertEqual(self.token(client_id="someone").status_code, 401)
        self.assertEqual(self.token(grant_type="password").status_code, 400)
        self.assertEqual(self.token(tenant="nowhere").status_code, 404)


class DocumentApiTests(_DbCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(mock_app())

    def url(self, path, tenant="hq"):
        return f"/mock/kagent/{tenant}/api/v1{path}"

    def test_auth_health_folders_and_listing(self):
        self.assertEqual(self.client.get(self.url("/health")).status_code, 401)
        self.assertEqual(self.client.get(self.url("/health"), headers={"X-API-Key": "wrong"}).status_code, 401)
        self.assertEqual(self.client.get(self.url("/health"), headers={"X-API-Key": mk.DEMO_KEY}).json(),
                         {"status": "ok", "version": "1.0", "capabilities": ["list", "upload", "preview", "download", "delete", "status"]})
        self.assertEqual(self.client.get(self.url("/health", "nowhere"), headers=BEARER).status_code, 404)
        folders = self.client.get(self.url("/folders", "lab"), headers=BEARER).json()
        self.assertEqual([f["name"] for f in folders], ["연구 과제", "실험 매뉴얼"])
        self.assertEqual(folders[0]["children"][0]["name"], "배터리 소재")
        docs = self.client.get(self.url("/documents"), headers=BEARER).json()
        self.assertEqual(len(docs), mk.seed_count("hq"))
        self.assertEqual(set(docs[0]), {"id", "name", "folder_id", "size", "mime", "status", "updated_at"})
        sales = self.client.get(self.url("/documents"), headers=BEARER, params={"folder_id": "hq-sales"}).json()
        self.assertEqual(sorted(d["name"] for d in sales), ["2026 영업 전략 보고서.pdf", "고객 미팅 기록 가이드.txt", "고객사 제안서 양식.hwp"])
        # 폴더 필터는 직속 문서만 / the folder filter returns direct documents only
        self.assertEqual([d["id"] for d in self.client.get(self.url("/documents"), headers=BEARER, params={"folder_id": "hq-rules"}).json()],
                         ["hq-doc-001"])

    def test_preview_download_status(self):
        r = self.client.get(self.url("/documents/hq-doc-001/preview"), headers=BEARER)
        self.assertEqual((r.status_code, r.headers["content-type"]), (200, "application/pdf"))
        self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertIn("inline", r.headers["content-disposition"])
        r = self.client.get(self.url("/documents/hq-doc-004/preview"), headers=BEARER)
        self.assertEqual(r.headers["content-type"], "text/plain; charset=utf-8")
        self.assertIn("CRM", r.text)
        r = self.client.get(self.url("/documents/hq-doc-005/preview"), headers=BEARER)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (415, "unsupported_media_type"))
        r = self.client.get(self.url("/documents/lab-doc-005/download", "lab"), headers=BEARER)
        self.assertEqual(r.headers["content-type"], mk.EXT_MIME["xlsx"])
        self.assertEqual(r.headers["content-disposition"],
                         "attachment; filename=\"document.xlsx\"; filename*=UTF-8''%ED%8A%B9%ED%97%88%20%EC%B6%9C%EC%9B%90%20%ED%98%84%ED%99%A9.xlsx")
        self.assertEqual(self.client.get(self.url("/documents/hq-doc-001/status"), headers=BEARER).json(),
                         {"status": "done", "message": "처리가 끝났습니다"})
        self.assertEqual(self.client.get(self.url("/documents/missing/status"), headers=BEARER).status_code, 404)
        self.assertEqual(self.client.get(self.url("/documents/hq-doc-001/download", "lab"), headers=BEARER).status_code, 404)

    def test_upload_processing_to_done_then_delete(self):
        t0 = datetime(2026, 9, 29, 10, 0, 0)
        with patch.object(mk, "_now", return_value=t0):
            r = self.client.post(self.url("/documents"), headers=BEARER, data={"folder_id": "hq-security"},
                                 files={"file": ("보안 점검 체크리스트.txt", "분기 보안 점검 항목: 방화벽 규칙 검토".encode("utf-8"), "text/plain")})
            self.assertEqual(r.status_code, 201)
            doc = r.json()
            self.assertEqual((doc["name"], doc["folder_id"], doc["status"], doc["mime"]),
                             ("보안 점검 체크리스트.txt", "hq-security", "processing", "text/plain"))
            # 처리 중 문서는 검색에 나오지 않는다 / documents still processing are not searchable
            self.assertEqual(mk.search("hq", "방화벽"), [])
        with patch.object(mk, "_now", return_value=t0 + timedelta(seconds=4)):
            self.assertEqual(self.client.get(self.url(f"/documents/{doc['id']}/status"), headers=BEARER).json()["status"], "processing")
        with patch.object(mk, "_now", return_value=t0 + timedelta(seconds=5)):
            self.assertEqual(self.client.get(self.url(f"/documents/{doc['id']}/status"), headers=BEARER).json()["status"], "done")
            listed = {d["id"]: d for d in self.client.get(self.url("/documents"), headers=BEARER).json()}
            self.assertEqual(listed[doc["id"]]["status"], "done")
            self.assertEqual(mk.search("hq", "방화벽")[0]["doc_id"], doc["id"])
        self.assertEqual(self.client.delete(self.url(f"/documents/{doc['id']}"), headers=BEARER).json(), {"ok": True})
        self.assertEqual(self.client.delete(self.url(f"/documents/{doc['id']}"), headers=BEARER).status_code, 404)
        self.assertEqual(self.client.get(self.url(f"/documents/{doc['id']}/status"), headers=BEARER).status_code, 404)

    def test_upload_validation(self):
        def up(name, data=b"x", folder=""):
            return self.client.post(self.url("/documents"), headers=BEARER, data={"folder_id": folder} if folder else {},
                                    files={"file": (name, data, "application/octet-stream")})
        self.assertEqual(up("tool.exe").status_code, 422)
        self.assertEqual(up("a.txt", folder="no-such-folder").json()["error"]["code"], "folder_not_found")
        self.assertEqual(up("a.txt", b"").status_code, 422)
        with patch.object(mk, "MAX_UPLOAD_BYTES", 4):
            self.assertEqual(up("a.txt", b"12345").status_code, 413)
        pdf = mk._seed_payload("hq", "hq-doc-001")[2]
        r = up("복사본.pdf", pdf, "hq-rules")
        self.assertEqual(r.status_code, 201)
        # 올린 PDF 도 본문을 뽑아 검색된다(처리 완료 뒤) / an uploaded PDF is text-extracted and searchable once done
        # 모듈 자신의 시계(KST) 기준 10초 뒤 — 호스트 시계와 섞지 않는다 / 10 s past the module's own KST clock, never the host clock
        with patch.object(mk, "_now", return_value=mk._now() + timedelta(seconds=10)):
            self.assertIn(r.json()["id"], [h["doc_id"] for h in mk.search("hq", "악성코드", 10)])
        self.assertEqual(self.client.post(self.url("/documents"), data={}, files={"file": ("a.txt", b"x", "text/plain")}).status_code, 401)

    def test_mcp_http_route_and_our_client(self):
        c = self.client
        self.assertEqual(c.post("/mock/kagent/hq/mcp", json=rpc("ping")).status_code, 401)
        self.assertEqual(c.get("/mock/kagent/hq/mcp").status_code, 405)
        self.assertEqual(c.post("/mock/kagent/hq/mcp", content=b"{bad", headers=BEARER).status_code, 400)
        batch = c.post("/mock/kagent/hq/mcp", json=[rpc("ping", mid=1), rpc("tools/list", mid=2)], headers=BEARER).json()
        self.assertEqual([b["id"] for b in batch], [1, 2])
        with mcp_client.MCPClient("http://localhost:65531/mock/kagent/lab/mcp", {"X-API-Key": mk.DEMO_KEY}, transport=mock_transport()) as client:
            names = [t["name"] for t in client.list_tools()]
            res = client.call_tool("kb_search", {"query": "양극재"})
        self.assertEqual(names, ["kb_chat", "kb_search", "kb_get_document"])
        conv = mcp_client.result_to_common(res)
        self.assertTrue(conv["ok"])
        self.assertEqual(conv["json"]["hits"][0]["folder_id"].split("-")[0], "lab")


class SeedTests(_DbCase):
    def test_seed_formats_once_and_deleted_seed_stays_deleted(self):
        import fitz
        for tenant, want in (("hq", {"pdf": 3, "txt": 1, "hwp": 1}), ("lab", {"pdf": 3, "txt": 1, "xlsx": 1})):
            docs = mk.list_docs(tenant)
            got: dict = {}
            for d in docs:
                ext = d["name"].rsplit(".", 1)[-1]
                got[ext] = got.get(ext, 0) + 1
            self.assertEqual(got, want)
        pdf = bytes(mk.get_doc("hq", "hq-doc-002")["content"])
        with fitz.open(stream=pdf, filetype="pdf") as doc:
            text = doc[0].get_text().replace("\xa0", " ")
        self.assertIn("개인정보 처리 지침", text)   # 한글 글꼴이 실제로 박혀 텍스트가 나온다 / the Korean font is embedded, so text extracts
        xlsx = bytes(mk.get_doc("lab", "lab-doc-005")["content"])
        self.assertIn("xl/workbook.xml", zipfile.ZipFile(io.BytesIO(xlsx)).namelist())
        self.assertTrue(bytes(mk.get_doc("hq", "hq-doc-005")["content"]).startswith(b"\xd0\xcf\x11\xe0"))
        mk.init_mock_kagent()
        self.assertEqual(len(mk.list_docs("hq")), mk.seed_count("hq"))
        self.assertTrue(mk.delete_doc("hq", "hq-doc-003"))
        mk.init_mock_kagent()
        self.assertIsNone(mk.get_doc("hq", "hq-doc-003"))

    def test_listing_and_search_never_read_the_blob(self):
        seen = []
        real = mk._rows

        def spy(sql, args=()):
            seen.append(sql)
            return real(sql, args)
        with patch.object(mk, "_rows", side_effect=spy):
            self.assertEqual(len(mk.list_docs("hq")), mk.seed_count("hq"))
            mk.list_docs("hq", "hq-sales")
            self.assertTrue(mk.search("hq", "비밀번호"))
        self.assertEqual(len(seen), 3)
        for sql in seen:
            self.assertNotIn("*", sql)
            self.assertNotIn("content", sql)

    def test_text_extraction_runs_outside_the_write_lock(self):
        path = mk.DB_PATH
        free = []

        def probe(ext, data):
            # 다른 연결이 쓰기 잠금을 곧바로 잡을 수 있어야 한다(추출 중 잠금 없음) / another writer must get the lock at once
            conn = sqlite3.connect(path, timeout=0)
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.rollback()
                free.append(True)
            finally:
                conn.close()
            return "추출한 본문"
        with patch.object(mk, "_extract_text", side_effect=probe):
            doc = mk.add_doc("hq", "잠금 확인.pdf", b"%PDF-1.4 fake", "hq-rules")
        self.assertEqual(free, [True])
        self.assertEqual(mk.get_doc("hq", doc["id"])["text"], "추출한 본문")

    def test_pdf_falls_back_to_text_without_font(self):
        mk._seed_payload.cache_clear()
        self.addCleanup(mk._seed_payload.cache_clear)
        with patch.object(mk, "FONT_DIR", Path("Z:/no/such/fonts")), self.assertLogs("ai365.mock_kagent", level="WARNING"):
            name, mime, content, text = mk._seed_payload("hq", "hq-doc-001")
        self.assertEqual((name, mime), ("정보보안 기본 규정.txt", "text/plain"))
        self.assertIn("비밀번호", content.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
