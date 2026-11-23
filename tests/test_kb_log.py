# -*- coding: utf-8 -*-
"""AI Batch Log(2026-09-16) — 인덱싱 처리 이력 저장소·백필·인덱서 연동·조회 API. 임시 DB, LLM·PDF 파싱 없음(패치).

AI Batch Log (2026-09-16) — indexing history store, backfill, indexer hooks and the listing API. Temp DB; no LLM or PDF parsing."""
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from app import access, db, kb, kb_log, resources_api
from tests.db_fixture import isolate_db

TREE = [{"id": "f1", "label": "규정", "folders": [{"id": "f11", "label": "인사", "folders": [], "files": [["kf1", "근태_취업규칙.pdf"]]}],
         "files": [["kf2", "A사 사내규정.pdf"]]},
        {"id": "f2", "label": "설비 매뉴얼", "folders": [], "files": [{"node": "kf3", "name": "보일러.pdf"}]}]


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        isolate_db(self.stack)
        self.addCleanup(self.stack.close)
        kb_log.init_kb_log()

    def test_backfill_creates_done_rows_once(self):
        with db._conn() as conn:
            conn.execute("INSERT INTO kb_docs(doc, hash, pages, chunks, indexed_at) VALUES(?,?,?,?,?)", ("a.pdf", "h", 3, 10, "2026-09-01T09:00:00"))
            conn.execute("INSERT INTO kb_docs(doc, hash, pages, chunks, indexed_at) VALUES(?,?,?,?,?)", ("b.pdf", "h", 1, 2, "2026-09-01T09:05:00"))
        self.assertEqual(kb_log.backfill(), 2)
        self.assertEqual(kb_log.backfill(), 0)   # 멱등 / idempotent
        rows = kb_log.list_logs()["rows"]
        self.assertEqual([r["doc"] for r in rows], ["b.pdf", "a.pdf"])   # 최근 처리가 앞 / newest first
        self.assertEqual({r["batch_id"] for r in rows}, {"BAT-20260901-0001", "BAT-20260901-0002"})
        self.assertTrue(all(r["status"] == "done" and r["actor"] == "시스템" and r["started_at"] == r["finished_at"] for r in rows))
        self.assertEqual(rows[1]["pages"], 3)

    def test_pending_start_finish_and_daily_sequence(self):
        p1 = kb_log.pending("x.pdf", "홍길동")
        p2 = kb_log.pending("y.pdf", "홍길동")
        rows = {r["doc"]: r for r in kb_log.list_logs()["rows"]}
        self.assertEqual(rows["x.pdf"]["status"], "pending")
        self.assertNotEqual(rows["x.pdf"]["batch_id"], rows["y.pdf"]["batch_id"])
        self.assertTrue(rows["x.pdf"]["batch_id"].endswith("-0001") and rows["y.pdf"]["batch_id"].endswith("-0002"))
        run_id = kb_log.start("x.pdf", "무시됨")   # 대기 행을 이어 쓴다 / continues the pending row
        self.assertEqual(run_id, p1)
        kb_log.finish(run_id, pages=4, chunks=9)
        kb_log.finish(kb_log.start("y.pdf"), error="임베딩 실패: 429")
        rows = {r["doc"]: r for r in kb_log.list_logs()["rows"]}
        self.assertEqual((rows["x.pdf"]["status"], rows["x.pdf"]["pages"], rows["x.pdf"]["chunks"], rows["x.pdf"]["actor"]), ("done", 4, 9, "홍길동"))
        self.assertTrue(rows["x.pdf"]["started_at"] and rows["x.pdf"]["finished_at"])
        self.assertEqual((rows["y.pdf"]["status"], rows["y.pdf"]["error"]), ("error", "임베딩 실패: 429"))
        self.assertEqual(len(kb_log.list_logs()["rows"]), 2)   # 새 행이 생기지 않았다 / no extra rows
        fid = kb_log.fail("big.pdf", "홍길동", "허용 용량 초과 (312MB/50MB)")
        self.assertTrue(fid > p2)
        self.assertEqual(kb_log.list_logs(status="error")["total"], 2)
        self.assertEqual(kb_log.list_logs()["counts"], {"pending": 0, "running": 0, "done": 1, "error": 2})

    def test_error_reasons(self):
        self.assertEqual(kb_log.error_reason(RuntimeError("cannot decrypt: password required")), "암호가 설정된 파일")
        self.assertTrue(kb_log.error_reason(RuntimeError("HTTP 429 RESOURCE_EXHAUSTED")).startswith("임베딩 실패"))
        self.assertTrue(kb_log.error_reason(ValueError("Failed to open file")).startswith("PDF 열기 실패"))
        self.assertEqual(kb_log.error_reason(ValueError("weird")), "weird")

    def test_list_filters_paging_and_folder_resolution(self):
        with db._conn() as conn:
            for i, (doc, at) in enumerate((("근태_취업규칙.pdf", "2026-09-01T10:00:00"), ("A사 사내규정.pdf", "2026-09-02T10:00:00"),
                                          ("보일러.pdf", "2026-09-03T10:00:00"), ("ghost.pdf", "2026-09-04T10:00:00"))):
                conn.execute("INSERT INTO kb_docs(doc, hash, pages, chunks, indexed_at) VALUES(?,?,?,?,?)", (doc, "h", 1, 1, at))
        kb_log.backfill()
        with patch.object(access, "load_knowledge", return_value=TREE):
            all_rows = kb_log.list_logs()
            page2 = kb_log.list_logs(page=2, size=3)
            ranged = kb_log.list_logs(date_from="2026-09-02", date_to="2026-09-03")
            by = {r["doc"]: r for r in all_rows["rows"]}
        self.assertEqual(all_rows["total"], 4)
        self.assertEqual((by["근태_취업규칙.pdf"]["folder"], by["근태_취업규칙.pdf"]["location"]), ("인사", "/규정/인사"))
        self.assertEqual((by["A사 사내규정.pdf"]["folder"], by["A사 사내규정.pdf"]["location"]), ("규정", "/규정"))
        self.assertEqual(by["보일러.pdf"]["folder"], "설비 매뉴얼")   # dict 형 파일 항목 / dict-shaped file entries
        self.assertEqual((by["ghost.pdf"]["folder"], by["ghost.pdf"]["location"]), ("미분류", "/knowledge"))
        self.assertEqual(by["보일러.pdf"]["source_label"], "매뉴얼")
        self.assertEqual([r["doc"] for r in page2["rows"]], ["근태_취업규칙.pdf"])   # 4건 중 2페이지(3건씩) / page 2 of 3 per page
        self.assertEqual([r["doc"] for r in ranged["rows"]], ["보일러.pdf", "A사 사내규정.pdf"])
        api = resources_api.batch_log(from_="2026-09-04", to="", status="done", page=1, size=20)
        self.assertEqual([r["doc"] for r in api["rows"]], ["ghost.pdf"])

    def test_index_one_records_done_error_and_no_text(self):
        tmp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        good, blank, broken = tmp / "good.pdf", tmp / "blank.pdf", tmp / "broken.pdf"
        for p in (good, blank, broken):
            p.write_bytes(b"%PDF-1.4 " + p.name.encode())
        pages = {"good.pdf": [(1, "안녕하세요 " * 20), (2, "둘째 장")], "blank.pdf": [(1, "  "), (2, "")], "broken.pdf": None}

        def fake_pages(path):
            if pages[path.name] is None:
                raise RuntimeError("cannot open broken file: password required")
            return pages[path.name]

        with patch.object(kb, "_extract_pages", side_effect=fake_pages), \
             patch.object(kb.llm, "embed", side_effect=lambda texts: [[0.1, 0.2] for _ in texts]):
            self.assertTrue(kb._index_one(good, "홍길동"))
            self.assertTrue(kb._index_one(blank, "홍길동"))
            with self.assertRaises(RuntimeError):
                kb._index_one(broken, "홍길동")
            self.assertFalse(kb._index_one(good, "홍길동"))   # 변경 없음 → 스킵, 이력 없음 / unchanged → skipped, no new row
        rows = {r["doc"]: r for r in kb_log.list_logs()["rows"]}
        self.assertEqual((rows["good.pdf"]["status"], rows["good.pdf"]["pages"], rows["good.pdf"]["actor"]), ("done", 2, "홍길동"))
        self.assertGreater(rows["good.pdf"]["chunks"], 0)
        self.assertEqual((rows["blank.pdf"]["status"], rows["blank.pdf"]["error"]), ("error", kb_log.NO_TEXT_REASON))
        self.assertEqual((rows["broken.pdf"]["status"], rows["broken.pdf"]["error"]), ("error", "암호가 설정된 파일"))
        self.assertEqual(kb_log.list_logs()["total"], 3)
        with db._conn() as conn:
            docs = {r["doc"] for r in conn.execute("SELECT doc FROM kb_docs").fetchall()}
        self.assertEqual(docs, {"good.pdf", "blank.pdf"})   # 빈 PDF 도 색인은 남는다(재시도 방지) / the blank PDF stays indexed


if __name__ == "__main__":
    unittest.main()
