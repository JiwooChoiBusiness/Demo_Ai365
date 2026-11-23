# -*- coding: utf-8 -*-
"""업로드 검증(2026-10-01, 관리 센터 › 로컬 설정 › 업로드 검증) — 키워드 저장소 · 본문 글자 · 판정 · 슈퍼어드민 전용 설정 API ·
Public 업로드(리소스 관리 지식 탭) 차단/경고/강행 · 문서 관리 사전 검사(/check). 임시 DB, 지식 트리 · 파일 폴더 · 인덱서는 패치.

Upload validation (2026-10-01, Admin Center › Local settings › Upload validation): the keyword store, document text, the
verdict, the super-admin-only settings API, the Public upload (block, warn, force) and the document-management pre-check
(/check). Temp DB; the knowledge tree, the file folder and the indexer are patched."""
import copy
import io
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz
import httpx
from fastapi import FastAPI

from app import access, catalog, db, kb, kb_log, resources_api, upload_guard as ug
from tests.db_fixture import isolate_db

TREE = [{"id": "f1", "label": "규정", "folders": [], "files": []}]
MANAGER = {"no": 7, "menus": {}, "nodes": {"f1": 2}, "mgmt": {}, "read": {"p_know": True}}   # 그 폴더를 관리하는 관리자 / an admin managing the folder


def pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 72), text, fontname="korea")
    return doc.tobytes()


def docx(*runs: str) -> bytes:
    import docx as pydocx
    d = pydocx.Document()
    p = d.add_paragraph()
    for r in runs:
        p.add_run(r)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def pptx(text: str) -> bytes:
    from pptx import Presentation
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[5])
    slide.shapes.title.text = text
    buf = io.BytesIO()
    deck.save(buf)
    return buf.getvalue()


def xlsx(*cells: str) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    for i, c in enumerate(cells, start=1):
        wb.active.cell(row=i, column=1, value=c)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)

    def test_ten_keywords_are_seeded_once_with_validation_on(self):
        rows = ug.list_keywords()
        self.assertEqual([r["keyword"] for r in rows], [w for w, _ in ug.SEED])
        self.assertEqual((rows[0]["description"], all(r["enabled"] for r in rows), ug.is_enabled()), ("개인정보 관련 문서", True, True))
        ug.delete_keyword(rows[0]["id"])
        ug.set_enabled(False)
        ug.init_upload_guard()   # 다시 기동해도 지운 키워드 · 끈 토글이 돌아오지 않는다 / a restart restores neither
        self.assertEqual((len(ug.list_keywords()), ug.is_enabled()), (9, False))

    def test_add_update_delete_with_validation(self):
        row = ug.add_keyword("  Confidential ", "영문 기밀 표시")
        self.assertEqual((row["keyword"], row["description"], row["enabled"]), ("Confidential", "영문 기밀 표시", True))
        with self.assertRaises(LookupError):
            ug.add_keyword("confidential")   # 대소문자만 다른 중복 / a duplicate differing in case only
        for bad in ("", "  ", "가" * (ug.MAX_KEYWORD_LEN + 1), "줄\n바꿈"):
            with self.assertRaises(ValueError):
                ug.add_keyword(bad)
        with self.assertRaises(ValueError):
            ug.add_keyword("새 키워드", "설" * (ug.MAX_DESC_LEN + 1))
        upd = ug.update_keyword(row["id"], keyword="CONFIDENTIAL", description="  대외비  표시 ", enabled=False)
        self.assertEqual((upd["keyword"], upd["description"], upd["enabled"]), ("CONFIDENTIAL", "대외비 표시", False))
        with self.assertRaises(LookupError):
            ug.update_keyword(row["id"], keyword="기밀")
        self.assertIsNone(ug.update_keyword("ug_none", keyword="x"))
        self.assertTrue(ug.delete_keyword(row["id"]))
        self.assertFalse(ug.delete_keyword(row["id"]))


class TextAndVerdictTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)

    def test_text_comes_out_of_pdf_word_powerpoint_excel_and_txt(self):
        self.assertIn("고객정보", ug.document_text("a.pdf", pdf("분기 고객정보 목록")))
        self.assertIn("개인정보", ug.document_text("a.docx", docx("개인", "정보 처리 방침")))   # 조각난 글자도 문단으로 잇는다 / runs are joined
        self.assertIn("대외비", ug.document_text("a.pptx", pptx("대외비 전략 회의")))
        self.assertIn("계좌번호", ug.document_text("a.xlsx", xlsx("이름", "계좌번호")))
        self.assertIn("재무정보", ug.document_text("a.txt", "재무정보 요약".encode("cp949")))
        self.assertEqual(ug.document_text("a.pdf", pdf("")), "")         # 그림 PDF = 글자 없음 / an image PDF has no text
        self.assertEqual(ug.document_text("a.docx", b"not a zip"), "")    # 깨진 파일 = 파일명만 / a broken file: name only
        self.assertEqual(ug.document_text("a.hwp", b"..."), "")

    def test_verdict_blocks_users_and_warns_the_super_admin(self):
        clean, hot = pdf("일반 업무 안내"), pdf("분기 고객정보와 개인정보 목록")
        self.assertEqual(ug.verdict("안내.pdf", clean, False), {"result": "ok"})
        self.assertEqual(ug.verdict("안내.pdf", hot, False), {"result": "blocked"})   # 키워드를 알려 주지 않는다 / no keywords
        warn = ug.verdict("고객 계약서.pdf", hot, True)
        self.assertEqual(warn["result"], "warn")
        self.assertEqual([(h["keyword"], h["description"], h["where"]) for h in warn["hits"]],
                         [("개인정보", "개인정보 관련 문서", ["문서 내용"]), ("고객정보", "고객 관련 민감정보", ["문서 내용"]),
                          ("계약서", "계약 관련 민감문서", ["파일명"])])   # 표 순서 / table order
        self.assertEqual(ug.verdict("고객 계약서.pdf", hot, True, force=True), {"result": "ok", "forced": True})
        self.assertEqual(ug.verdict("안내.pdf", hot, False, force=True)["result"], "blocked")   # 일반 사용자의 force 는 무시 / ignored for users
        self.assertEqual(ug.verdict("신용카드_내역.pdf", pdf(""), False)["result"], "blocked")    # 그림 PDF 도 파일명은 본다 / the name still counts

    def test_disabled_keywords_and_the_switch_turn_checks_off(self):
        hot = pdf("고객정보")
        kid = next(k["id"] for k in ug.list_keywords() if k["keyword"] == "고객정보")
        ug.update_keyword(kid, enabled=False)
        self.assertEqual(ug.verdict("a.pdf", hot, False), {"result": "ok"})
        ug.update_keyword(kid, enabled=True)
        ug.set_enabled(False)
        with patch.object(ug, "document_text", side_effect=AssertionError("꺼져 있으면 본문을 읽지 않는다")):
            self.assertEqual(ug.verdict("a.pdf", hot, False), {"result": "ok"})

    def test_matching_ignores_case_but_not_spacing(self):
        ug.add_keyword("Confidential", "")
        self.assertEqual([h["keyword"] for h in ug.scan("REPORT-confidential.pdf", "")], ["Confidential"])
        self.assertEqual(ug.scan("a.pdf", "개인 정보"), [])   # 띄어쓰기는 맞춰 주지 않는다 / spacing is not normalized
        self.assertEqual([h["keyword"] for h in ug.scan("a.pdf", "줄 끝의\n개인정보")], ["개인정보"])


class ApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        kb_log.init_kb_log()
        self.folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.tree = copy.deepcopy(TREE)
        self.index = MagicMock()
        self.stack.enter_context(patch.object(resources_api, "KNOWLEDGE_DIR", self.folder))
        self.stack.enter_context(patch.object(kb, "index_one_background", self.index))
        self.stack.enter_context(patch.object(access, "load_knowledge", side_effect=lambda: copy.deepcopy(self.tree)))
        self.stack.enter_context(patch.object(access, "save_knowledge", side_effect=lambda t: setattr(self, "tree", copy.deepcopy(t))))
        self.stack.enter_context(patch.object(access, "list_members", return_value=[{"no": 7, "name": "김관리"}]))
        self.stack.enter_context(patch.object(catalog, "knowledge_tree", return_value=[]))
        self.stack.enter_context(patch.object(catalog, "FILE_NODE", {}))
        self.stack.enter_context(patch.object(resources_api, "_eff", side_effect=lambda a: None if not a else copy.deepcopy(MANAGER)))
        app = FastAPI()
        app.include_router(resources_api.router)
        app.include_router(ug.router)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.client.aclose)

    async def upload(self, name, data, actor="", force=""):
        return await self.client.post("/api/resources/knowledge/files", data={"folder_id": "f1", "acting_user_id": actor, "force": force},
                                      files={"file": (name, data, "application/pdf")})

    async def test_settings_are_for_the_super_admin_only(self):
        r = await self.client.get("/api/upload-guard", params={"acting_user_id": "7"})
        self.assertEqual(r.status_code, 403)
        r = await self.client.get("/api/upload-guard")
        self.assertEqual((r.status_code, r.json()["enabled"], len(r.json()["keywords"])), (200, True, 10))
        r = await self.client.post("/api/upload-guard/keywords", json={"acting_user_id": "7", "keyword": "x"})
        self.assertEqual(r.status_code, 403)
        r = await self.client.post("/api/upload-guard/keywords", json={"keyword": "Confidential", "description": "영문 기밀"})
        kid = r.json()["keyword"]["id"]
        self.assertEqual(r.status_code, 200)
        self.assertEqual((await self.client.post("/api/upload-guard/keywords", json={"keyword": "confidential"})).status_code, 409)
        self.assertEqual((await self.client.post("/api/upload-guard/keywords", json={"keyword": " "})).status_code, 422)
        r = await self.client.patch(f"/api/upload-guard/keywords/{kid}", json={"enabled": False})
        self.assertEqual((r.status_code, r.json()["keyword"]["enabled"]), (200, False))
        self.assertEqual((await self.client.patch("/api/upload-guard/keywords/ug_none", json={"enabled": False})).status_code, 404)
        self.assertEqual((await self.client.delete(f"/api/upload-guard/keywords/{kid}", params={"acting_user_id": "7"})).status_code, 403)
        self.assertEqual((await self.client.delete(f"/api/upload-guard/keywords/{kid}")).json(), {"ok": True})
        r = await self.client.put("/api/upload-guard/enabled", json={"enabled": False})
        self.assertEqual((r.status_code, r.json(), ug.is_enabled()), (200, {"enabled": False}, False))
        self.assertEqual((await self.client.put("/api/upload-guard/enabled", json={"acting_user_id": "7", "enabled": True})).status_code, 403)

    async def test_an_admin_is_blocked_without_learning_the_keywords_and_it_is_logged(self):
        r = await self.upload("분기 보고.pdf", pdf("고객정보 목록"), actor="7", force="1")   # force 도 무시 / force is ignored
        self.assertEqual((r.status_code, r.json()["detail"]), (403, {"code": "upload_blocked", "file": "분기 보고.pdf"}))
        self.assertEqual(list(self.folder.iterdir()), [])          # 저장하지 않는다 / nothing stored
        self.assertEqual(self.tree[0]["files"], [])
        self.index.assert_not_called()
        log = kb_log.list_logs()["rows"][0]
        self.assertEqual((log["doc"], log["status"], log["error"], log["actor"]), ("분기 보고.pdf", "error", ug.BLOCK_LOG_REASON, "김관리"))

    async def test_the_super_admin_is_warned_and_can_upload_anyway(self):
        data = pdf("개인정보 처리 현황")
        r = await self.upload("현황.pdf", data)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"], {"code": "upload_warn", "file": "현황.pdf",
                                              "hits": [{"keyword": "개인정보", "description": "개인정보 관련 문서", "where": ["문서 내용"]}]})
        self.assertEqual(list(self.folder.iterdir()), [])
        r = await self.upload("현황.pdf", data, force="1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([p.name for p in self.folder.iterdir()], ["현황.pdf"])
        self.assertEqual(self.tree[0]["files"][0][1], "현황.pdf")
        self.index.assert_called_once()

    async def test_clean_files_and_a_disabled_switch_upload_as_before(self):
        r = await self.upload("안내.pdf", pdf("일반 업무 안내"), actor="7")
        self.assertEqual(r.status_code, 200)
        ug.set_enabled(False)
        r = await self.upload("고객정보 목록.pdf", pdf("고객정보"), actor="7")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ["고객정보 목록.pdf", "안내.pdf"])

    async def test_the_pre_check_answers_without_storing_and_keeps_keywords_from_users(self):
        files = {"file": ("전략.pptx", pptx("대외비 전략"), "application/octet-stream")}
        r = await self.client.post("/api/upload-guard/check", data={"acting_user_id": "7"}, files=files)
        self.assertEqual(r.json(), {"file": "전략.pptx", "result": "blocked"})
        r = await self.client.post("/api/upload-guard/check", data={"acting_user_id": ""}, files=files)
        self.assertEqual(r.json(), {"file": "전략.pptx", "result": "warn",
                                    "hits": [{"keyword": "대외비", "description": "외부 공개 금지 문서", "where": ["문서 내용"]}]})
        r = await self.client.post("/api/upload-guard/check", data={"acting_user_id": "7"}, files={"file": ("메모.txt", "회의 메모".encode(), "text/plain")})
        self.assertEqual(r.json(), {"file": "메모.txt", "result": "ok"})
        self.assertEqual(list(self.folder.iterdir()), [])
        self.assertEqual(kb_log.list_logs()["total"], 0)   # 사전 검사는 기록하지 않는다 / the pre-check logs nothing


if __name__ == "__main__":
    unittest.main()
