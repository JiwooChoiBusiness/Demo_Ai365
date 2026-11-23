"""Board permission, publication and language regressions; isolated DB, no external calls.
2026-09-18: review, per-board settings, stats and file/answer kinds are gone — the pin cap is a constant and
notifications are always on."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from test_boards_api import BoardsBase, REPORT, eff_for
from app import boards, boards_api, db, docgen

SHARED = {"kind": "report", "title": "공유", "data": REPORT}


class BoardBoundaries(BoardsBase):
    async def post(self, board="all", user="7", post=None):
        return await self.req("POST", f"/api/boards/{board}/posts",
                              {"acting_user_id": user, "post": post or SHARED})

    async def test_old_library_posts_are_revalidated_on_copy(self):
        # 보관함의 옛 글(폐지된 종류의 스냅샷)은 게시판으로 올릴 때 다시 검증돼 거부된다 / stale library snapshots are re-validated on copy
        p = boards.add_post("me:7", {"kind": "report", "title": "old", "data": {"text": "차트 없는 옛 답변"}})
        r = await self.req("POST", f"/api/boards/posts/{p['id']}/move", {"acting_user_id": "7", "board": "g:og9"})
        self.assertEqual(r.status_code, 422)
        self.assertIsNotNone(boards.get_post(p["id"]))

    async def test_zero_pin_limit_and_simultaneous_pin_requests(self):
        posts = [boards.add_post("all", SHARED) for _ in range(2)]
        with patch.object(boards, "PIN_MAX", 0):
            r = await self.req("PATCH", f"/api/boards/posts/{posts[0]['id']}", {"patch": {"pinned": True}})
            self.assertEqual(r.status_code, 422)

        def pin(post):
            try:
                boards.update_post(post["id"], {"pinned": True})
                return True
            except ValueError:
                return False
        with patch.object(boards, "PIN_MAX", 1):
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(sorted(pool.map(pin, posts)), [False, True])
        pinned = next(p for p in boards.list_posts("all") if p["pinned"])
        with patch.object(boards, "PIN_MAX", 0):
            r = await self.req("PATCH", f"/api/boards/posts/{pinned['id']}", {"patch": {"pinned": False}})
        self.assertEqual(r.status_code, 200)

    async def test_notification_lifecycle_permissions_and_deduplication(self):
        self.effs["7"] = eff_for({}); self.effs["12"] = eff_for({}); self.effs["3"] = eff_for({})   # 7·12 는 og9 소속, 3 은 무소속 / 7 and 12 in og9, 3 in no group
        p = (await self.post("g:og9")).json()["post"]

        def unread(user):
            return boards_api.notifications(user)["unread"]
        self.assertEqual((unread("12"), unread("7")), (1, 0))         # 게시 즉시 알림, 작성자 제외 / notified on post, never the author
        self.assertEqual(unread("3"), 0)                              # 소속이 아니면 알림도 열람도 없다 / a non-member gets neither
        self.assertEqual((await self.req("GET", f"/api/boards/posts/{p['id']}?acting_user_id=3")).status_code, 403)
        self.assertEqual(unread("12"), 1)
        await self.req("PATCH", f"/api/boards/posts/{p['id']}", {"acting_user_id": "7", "patch": {"title": "고친 제목"}})
        self.assertEqual(unread("12"), 1)                             # 편집은 다시 알리지 않는다 / edits do not re-notify
        await self.req("GET", f"/api/boards/posts/{p['id']}?acting_user_id=12")
        self.assertEqual(unread("12"), 0)
        with db._conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM board_notifications WHERE post_id=? AND user_id='12'", (p["id"],)).fetchone()[0], 1)

    async def test_library_posts_do_not_notify_and_copy_and_delete(self):
        self.effs["7"] = eff_for({"bd_all": 1})
        self.effs["12"] = eff_for({"bd_all": 1})
        mine = (await self.post("me:7")).json()["post"]
        self.assertEqual(boards_api.notifications("12")["unread"], 0)
        r = await self.req("POST", f"/api/boards/posts/{mine['id']}/move", {"acting_user_id": "7", "board": "g:og9"})
        p = r.json()["post"]
        self.assertEqual(boards_api.notifications("12")["unread"], 1)
        await self.req("DELETE", f"/api/boards/posts/{p['id']}?acting_user_id=7")
        self.assertEqual(boards_api.notifications("12")["unread"], 0)
        with db._conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM board_notifications WHERE post_id=?", (p["id"],)).fetchone()[0], 0)

    async def test_template_language_reaches_real_outline_page_and_sheet_prompts(self):
        docgen.init_docgen()

        async def smooth(text):
            yield text
        for fmt in ("docx", "xlsx"):
            with self.subTest(format=fmt):
                t = boards.add_template(boards_api._validate_template({"name": "보고", "format": fmt, "language": "en",
                    "sections": [{"title": "고정 제목"}], "source": "general", "length": 2}))
                prep = boards_api.prepare_template_run(t["id"], "7", {})
                self.assertIn("[출력 언어] en", prep["docgen"]["instruction"])
                chat = db.create_chat("language", "사내")

                def model(user, **kwargs):
                    if '"columns"' in kwargs["system"]:
                        return {"sheet_name": "Data", "columns": ["Sales"], "rows": [[10]]}
                    return {"doc_title": "Report", "pages": [{"points": ["English content"]}]}
                with patch.object(docgen, "_force_fallback", return_value=False), \
                     patch("app.llm.generate", side_effect=model) as generate, \
                     patch.object(docgen, "collection_material", return_value=""), \
                     patch.object(docgen, "build_file"), patch.object(docgen, "_smooth", smooth):
                    d = prep["docgen"]
                    events = [e async for e in docgen.run_docgen(chat, "만들기", fmt, d["topic"], d["style"], d["length"],
                              "general", "7", d["instruction"], template=prep["template"])]
                self.assertEqual(events[-1]["type"], "done")
                self.assertGreaterEqual(generate.call_count, 1 if fmt == "xlsx" else 3)
                for call in generate.call_args_list:
                    self.assertIn("출력 언어는 en", call.kwargs["system"])
                    self.assertNotIn("한국어", call.kwargs["system"])
                meta = next(e for e in events if e["type"] == "doc_meta")
                self.assertEqual(docgen.get_doc(meta["doc_id"])["template"]["language"], "en")
