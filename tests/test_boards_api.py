# -*- coding: utf-8 -*-
"""게시판(2026-09-14, 2026-09-18 정리) — 저장소·API 권한 규약·개인 보관소 위임·이전 규칙·템플릿. 실제 LLM·real DB 없음(격리 DB + 패치).
2026-09-18: 공유 종류는 리포트·대시보드만, 게시판 설정·검토·통계 폐지. 2026-09-22: 접근 권한의 게시판 축 폐지 — 소속 그룹 기준 고정 규칙,
전체 게시판 게시·관리·템플릿 관리는 슈퍼만.

Boards (2026-09-14, trimmed 2026-09-18) — store, API permission contract, personal-library delegation, migration rules and
templates. No real LLM or real DB (isolated DB + patches). 2026-09-18: only reports and dashboards are shared; board
settings, review and stats are gone; template management follows the board manage rights."""
import unittest
import tempfile
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from db_fixture import isolate_db
from app import access, boards, boards_api, boards_migrate, db, reports, reports_api

GROUPS = [{"id": "og3", "name": "인사총무 표준", "memberIds": [7], "teams": [], "grants": [], "exceptions": []},
          {"id": "og9", "name": "팀장", "memberIds": [7, 12], "teams": [], "grants": [], "exceptions": []}]
CHART = {"x": ["1월", "2월"], "xLabel": "월", "yLabel": "매출", "series": [{"name": "매출", "type": "bar", "values": [1, 2], "yAxis": 0}]}
REPORT = {"title": "월별 매출", "chart": CHART, "insight": "2월이 높다", "table": {"columns": [], "rows": []}, "source": {}}


def eff_for(nodes: dict):
    """뷰애즈 실효 권한 스텁 — nodes 만 / view-as effective stub"""
    return {"no": 7, "menus": {}, "nodes": dict(nodes), "mgmt": {}, "read": {}}


class BoardsBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        boards.init_boards()
        output = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch("app.docgen.GENERATED_DIR", Path(output)))
        self.stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")))
        self.stack.enter_context(patch.object(access, "list_groups", return_value=[dict(g) for g in GROUPS]))
        self.stack.enter_context(patch.object(access, "list_members", return_value=[{"no": 7, "name": "강수아", "dept": "인사총무팀"},
                                                                                     {"no": 12, "name": "김팀장", "dept": "PMO"}]))
        self.effs: dict = {}   # acting_user_id → eff (없으면 슈퍼) / missing = super
        self.stack.enter_context(patch("app.resources_api._eff", side_effect=lambda aid: self.effs.get(aid)))
        self.app = FastAPI()
        self.app.include_router(boards_api.router)
        self.app.include_router(reports_api.router)

    async def req(self, method, path, json=None):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
            return await client.request(method, path, json=json)


class BoardStoreTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        boards.init_boards()

    def test_posts_list_pinned_first_then_newest_with_search_and_no_tags(self):
        a = boards.add_post("all", {"kind": "report", "title": "A", "tags": ["회의"], "data": {"insight": "첫 글"}})
        b = boards.add_post("all", {"kind": "report", "title": "B", "data": {"insight": "둘째 글"}})
        boards.update_post(a["id"], {"pinned": True})
        ids = [p["id"] for p in boards.list_posts("all")]
        self.assertEqual(ids, [a["id"], b["id"]])
        self.assertEqual([p["id"] for p in boards.list_posts("all", q="둘째")], [b["id"]])
        # 태그 기능 폐지(2026-09-18): 저장하지도, 돌려주지도, 검색하지도 않는다 / tags retired: not stored, returned or searched
        self.assertNotIn("tags", boards.get_post(a["id"]))
        self.assertEqual(boards.list_posts("all", q="회의"), [])
        self.assertFalse(hasattr(boards, "list_tags"))

    def test_retired_kinds_fall_back_to_report_and_leftover_unpublished_rows_stay_hidden(self):
        # 폐지된 종류(답변·파일·템플릿 문서)는 저장소에서 report 로 떨어지고, 옛 검토 대기 글은 목록·건수에서 빠진다
        # Retired kinds fall back to "report" in the store; a leftover pending row is hidden from lists and counts
        for kind in ("answer", "file", "tdoc"):
            self.assertEqual(boards.add_post("me:7", {"kind": kind, "title": kind})["kind"], "report")
        p = boards.add_post("all", {"kind": "report", "title": "옛 대기 글", "status": "pending"})
        self.assertEqual(p["status"], "published")                 # 새 글은 언제나 게시 상태 / new posts are always published
        with db._conn() as conn:
            conn.execute("UPDATE board_posts SET status='pending' WHERE id=?", (p["id"],))
        self.assertEqual(boards.list_posts("all"), [])
        self.assertEqual(boards.count_posts(["all"]), {})

    def test_pin_cap_is_a_constant_per_board(self):
        posts = [boards.add_post("all", {"kind": "report", "title": str(i)}) for i in range(boards.PIN_MAX + 1)]
        for p in posts[:boards.PIN_MAX]:
            boards.update_post(p["id"], {"pinned": True})
        with self.assertRaises(ValueError):
            boards.update_post(posts[-1]["id"], {"pinned": True})
        other = boards.add_post("g:og9", {"kind": "report", "title": "다른 게시판"})
        self.assertTrue(boards.update_post(other["id"], {"pinned": True})["pinned"])   # 게시판마다 따로 센다 / counted per board

    def test_template_crud_bumps_version_and_records_uses(self):
        t = boards.add_template({"name": "주간 보고", "format": "docx", "groups": ["og9"], "sections": [{"title": "요약", "hint": ""}]})
        self.assertEqual(t["version"], 1)
        t2 = boards.update_template(t["id"], {**t, "name": "주간 보고 v2"})
        self.assertEqual((t2["version"], t2["name"]), (2, "주간 보고 v2"))
        self.assertEqual([x["id"] for x in boards.list_templates(group_ids=["og9"])], [t["id"]])
        self.assertEqual(boards.list_templates(group_ids=["og3"]), [])
        boards.record_use(t["id"], 2, "7", True, 1200, "doc_1")
        boards.record_use(t["id"], 2, "12", False, 300)
        usage = boards.template_usage(30)[t["id"]]
        self.assertEqual((usage["uses"], usage["ok"], usage["users"]), (2, 1, 2))
        self.assertEqual(boards.template_usage(30, template_ids=[]), {})


class BoardsApiTests(BoardsBase):
    async def test_boards_list_follows_group_membership(self):
        # 2026-09-22 고정 규칙: 전체 게시판은 누구나 읽지만 게시는 슈퍼만, 그룹 게시판은 소속 구성원이 읽고 게시, 관리는 슈퍼뿐
        # Fixed rule since 2026-09-22: all-hands is readable by everyone but only super posts; group boards are read/posted by members; manage is super-only
        self.effs["7"] = eff_for({})
        self.effs["12"] = eff_for({})
        r = await self.req("GET", "/api/boards?acting_user_id=7")
        self.assertEqual(r.status_code, 200)
        ids = {b["id"]: b for b in r.json()["boards"]}
        self.assertEqual(set(ids), {"all", "g:og3", "g:og9"})            # 7 은 og3·og9 소속 / a member of og3 and og9
        self.assertTrue(ids["g:og9"]["canPost"] and ids["g:og9"]["mine"] and not ids["g:og9"]["canManage"])
        self.assertTrue(not ids["all"]["canPost"] and not ids["all"]["canManage"])   # 전체 게시판은 읽기만 / read-only for members
        self.assertNotIn("review", ids["all"])                   # 게시판 설정 폐지 / board settings are gone
        self.assertEqual(r.json()["me"]["id"], "me:7")
        self.assertEqual({b["id"] for b in (await self.req("GET", "/api/boards?acting_user_id=12")).json()["boards"]}, {"all", "g:og9"})
        sup = {b["id"]: b for b in (await self.req("GET", "/api/boards?acting_user_id=")).json()["boards"]}
        self.assertEqual(set(sup), {"all", "g:og3", "g:og9"})
        self.assertTrue(all(b["canManage"] for b in sup.values()))
        self.assertEqual({b: sup[b]["canPost"] for b in sup}, {"all": False, "g:og3": True, "g:og9": True})   # 전체 게시판은 슈퍼도 게시 불가(2026-09-22) / not even super posts to all-hands

    async def test_members_post_only_to_their_own_group_boards(self):
        self.effs["7"] = eff_for({})
        self.effs["12"] = eff_for({})
        post = {"kind": "report", "title": "월별 매출", "data": REPORT}
        r = await self.req("POST", "/api/boards/g:og3/posts", {"acting_user_id": "12", "post": post})
        self.assertEqual(r.status_code, 403)                     # 12 는 og3 소속이 아니다 / not a member of og3
        self.assertIn("속한 그룹", r.json()["detail"])
        r = await self.req("POST", "/api/boards/all/posts", {"acting_user_id": "7", "post": post})
        self.assertEqual(r.status_code, 403)                     # 전체 게시판은 읽기 전용 / the all-hands board is read-only
        self.assertIn("전체 게시판에는", r.json()["detail"])
        r = await self.req("POST", "/api/boards/g:og9/posts", {"acting_user_id": "7", "post": post})
        self.assertEqual(r.status_code, 200)
        saved = r.json()["post"]
        self.assertEqual((saved["kind"], saved["author"]["name"], saved["status"], saved["group"]), ("report", "강수아", "published", "팀장"))
        self.assertNotIn("pending", r.json())                    # 게시 전 검토 폐지 / review is gone
        listed = await self.req("GET", "/api/boards/g:og9/posts?acting_user_id=12")   # 같은 그룹 구성원이 읽는다 / a fellow member reads it
        self.assertEqual([p["id"] for p in listed.json()["posts"]], [saved["id"]])
        self.assertTrue(listed.json()["canPost"] and not listed.json()["canManage"])
        self.assertNotIn("settings", listed.json())
        self.assertNotIn("tags", listed.json())
        r = await self.req("POST", "/api/boards/all/posts", {"acting_user_id": "", "post": post})
        self.assertEqual(r.status_code, 403)                     # 슈퍼관리자도 전체 게시판에는 공유하지 못한다(2026-09-22) / not even super posts to all-hands
        self.assertIn("전체 게시판에는", r.json()["detail"])
        self.assertEqual((await self.req("POST", "/api/boards/g:og3/posts", {"acting_user_id": "", "post": post})).status_code, 200)   # 슈퍼는 그룹 게시판 어디나 / super posts on any group board

    async def test_only_reports_and_dashboards_can_be_shared(self):
        for post in ({"kind": "answer", "title": "답변", "data": {"text": "본문"}},
                     {"kind": "file", "data": {"doc_id": "doc_x"}},
                     {"kind": "tdoc", "data": {"doc_id": "doc_x"}}):
            with self.subTest(kind=post["kind"]):
                r = await self.req("POST", "/api/boards/g:og9/posts", {"acting_user_id": "", "post": post})
                self.assertEqual(r.status_code, 422)
                self.assertIn("리포트와 대시보드만", r.json()["detail"])
        dash = {"kind": "dashboard", "title": "합본", "data": {"type": "dashboard", "title": "합본",
                                                              "items": [{"title": "t", "chart": CHART, "insight": ""}]}}
        r = await self.req("POST", "/api/boards/g:og9/posts", {"acting_user_id": "", "post": dash})
        self.assertEqual((r.status_code, r.json()["post"]["kind"]), (200, "dashboard"))

    async def test_pinning_is_super_only_and_authors_edit_their_text(self):
        self.effs["7"] = eff_for({})
        self.effs["12"] = eff_for({})
        pid = (await self.req("POST", "/api/boards/g:og9/posts", {"acting_user_id": "7", "post": {"kind": "report", "title": "글", "data": REPORT}})).json()["post"]["id"]
        r = await self.req("PATCH", f"/api/boards/posts/{pid}", {"acting_user_id": "7", "patch": {"pinned": True}})
        self.assertEqual(r.status_code, 403)                     # 작성자는 고정 불가 / authors cannot pin
        r = await self.req("PATCH", f"/api/boards/posts/{pid}", {"acting_user_id": "7", "patch": {"title": "고친 제목", "status": "rejected"}})
        self.assertEqual((r.status_code, r.json()["post"]["title"], r.json()["post"]["status"]), (200, "고친 제목", "published"))
        r = await self.req("PATCH", f"/api/boards/posts/{pid}", {"acting_user_id": "12", "patch": {"pinned": True}})
        self.assertEqual(r.status_code, 403)                     # 같은 그룹 구성원도 관리자는 아니다 / a fellow member is no manager
        r = await self.req("PATCH", f"/api/boards/posts/{pid}", {"acting_user_id": "", "patch": {"pinned": True}})
        self.assertEqual((r.status_code, r.json()["post"]["pinned"]), (200, True))   # 슈퍼만 고정 / only super pins

    async def test_move_from_library_copies_to_a_board_and_keeps_the_original(self):
        self.effs["7"] = eff_for({"bd_g_og9": 1})
        mine = boards.add_post("me:7", {"kind": "report", "title": "메모", "data": REPORT, "author": {"id": "7", "name": "강수아"}})
        r = await self.req("POST", f"/api/boards/posts/{mine['id']}/move", {"acting_user_id": "7", "board": "g:og9", "title": "메모(공유)", "summary": "고친 요약"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["post"]["board"], "g:og9")
        self.assertEqual((r.json()["post"]["title"], r.json()["post"]["summary"]), ("메모(공유)", "고친 요약"))   # 미리보기 수정값 반영 / preview edits applied
        self.assertEqual(boards.get_post(mine["id"])["title"], "메모")                                   # 원본은 그대로 / the original is untouched
        self.assertEqual(r.json()["post"]["source"]["from_post"], mine["id"])
        self.assertIsNotNone(boards.get_post(mine["id"]))
        r = await self.req("POST", f"/api/boards/posts/{mine['id']}/move", {"acting_user_id": "12", "board": "g:og9"})
        self.assertEqual(r.status_code, 403)                     # 남의 보관함 / someone else's library

    async def test_take_copies_a_readable_board_post_into_my_library_and_keeps_the_original(self):
        self.effs["7"] = eff_for({})    # og3·og9 소속 / member of og3 and og9
        self.effs["12"] = eff_for({})   # og9 만 / og9 only
        # v2 대시보드(Source + 차트 설정): 가져온 뒤 리포트 에이전트에서 열어 고칠 수 있어야 한다 / a v2 dashboard must stay editable after the copy
        v2 = {"type": "dashboard", "v": 2, "title": "지점 매출", "sources": [{"columns": ["지점", "매출"], "rows": [["강남점", 10], ["광주점", 4]], "sql": "SELECT 1"}],
              "charts": [{"source": "s1", "type": "bar", "x": "지점", "y": ["매출"], "title": "지점별 매출"}]}
        shared = (await self.req("POST", "/api/boards/g:og3/posts", {"acting_user_id": "", "post": {
            "kind": "dashboard", "title": "지점 매출", "summary": "요약", "data": v2, "source": {"chat_id": "c_author"}}})).json()["post"]
        r = await self.req("POST", f"/api/boards/posts/{shared['id']}/take", {"acting_user_id": "12"})
        self.assertEqual(r.status_code, 403)                                                   # og3 소속이 아닌 12 / 12 is not a member of og3
        r = await self.req("POST", f"/api/boards/posts/{shared['id']}/take", {"acting_user_id": "7"})
        self.assertEqual(r.status_code, 200)
        mine = r.json()["post"]
        self.assertEqual((mine["board"], mine["kind"], mine["title"], mine["summary"], mine["author"], r.json()["existed"]),
                         ("me:7", "dashboard", "지점 매출", "요약", {"id": "7", "name": "강수아"}, False))
        self.assertEqual((mine["source"]["from_post"], mine["source"]["from_board"], mine["source"]["from_author"]), (shared["id"], "g:og3", "관리자"))
        self.assertNotIn("chat_id", mine["source"])                                            # 남의 채팅으로 가는 버튼은 만들지 않는다 / no link into someone else's chat
        own = (await self.req("POST", f"/api/boards/posts/{shared['id']}/take", {"acting_user_id": ""})).json()["post"]
        self.assertEqual(own["source"]["chat_id"], "c_author")                                 # 작성자 본인이 가져가면 그대로 / the author keeps the link
        self.assertEqual((len(mine["data"]["sources"][0]["rows"]), mine["data"]["charts"][0]["title"], len(mine["data"]["items"])), (2, "지점별 매출", 1))
        self.assertEqual(boards.get_post(shared["id"])["board"], "g:og3")                      # 원본은 게시판에 그대로 / the original stays on the board
        self.assertEqual((await self.req("GET", "/api/boards/g:og3/posts?acting_user_id=7")).json()["posts"][0]["id"], shared["id"])
        # 가져온 글은 내 것 — 리포트 에이전트 세션으로 열린다 / the copy is mine: it opens as a report-agent session
        from app import report_dash
        report_dash.init_report_dash()
        opened = await self.req("POST", "/api/reports/dash/open", {"acting_user_id": "7", "post_id": mine["id"]})
        self.assertEqual((opened.status_code, [c["title"] for c in opened.json()["session"]["state"]["charts"]]), (200, ["지점별 매출"]))
        # 두 번째는 새로 만들지 않고 그 글을 돌려준다(again 이면 하나 더) / a second take returns the same copy; `again` makes another
        r2 = await self.req("POST", f"/api/boards/posts/{shared['id']}/take", {"acting_user_id": "7"})
        self.assertEqual((r2.json()["existed"], r2.json()["post"]["id"]), (True, mine["id"]))
        r3 = await self.req("POST", f"/api/boards/posts/{shared['id']}/take", {"acting_user_id": "7", "again": True})
        self.assertEqual((r3.json()["existed"], r3.json()["post"]["id"] != mine["id"], len(boards.list_posts("me:7"))), (False, True, 2))
        # 내 보관함의 글은 가져갈 대상이 아니다 / a library post is not something to take
        r4 = await self.req("POST", f"/api/boards/posts/{mine['id']}/take", {"acting_user_id": "7"})
        self.assertEqual(r4.status_code, 422)
        self.assertEqual((await self.req("POST", "/api/boards/posts/bp_none/take", {"acting_user_id": "7"})).status_code, 404)

    async def test_compose_falls_back_to_heuristics_when_the_model_fails(self):
        r = await self.req("POST", "/api/boards/compose", {"acting_user_id": "", "post": {"kind": "report", "data": {"insight": "첫 줄 제목\n둘째 줄"}}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["fill"]["title"], "첫 줄 제목")

    async def test_settings_and_stats_endpoints_are_gone(self):
        self.assertIn((await self.req("GET", "/api/boards/settings")).status_code, (404, 405))
        self.assertIn((await self.req("PUT", "/api/boards/settings/all", {"acting_user_id": "", "settings": {"review": True}})).status_code, (404, 405))
        self.assertIn((await self.req("GET", "/api/boards/stats")).status_code, (404, 405))

    async def test_templates_are_scoped_to_groups_and_use_returns_a_docgen_config(self):
        self.effs["7"] = eff_for({"bd_g_og9": 1})
        tpl = {"name": "주간 보고", "format": "docx", "groups": ["og9"], "sections": [{"title": "핵심 성과", "hint": "수치 포함"}, "다음 주 계획"],
               "instruction": "존댓말", "inputs": [{"name": "보고 기간", "required": True}]}
        r = await self.req("POST", "/api/boards/templates", {"acting_user_id": "7", "template": tpl})
        self.assertEqual(r.status_code, 403)                     # 열람만으로는 관리 불가 / view is not manage
        r = await self.req("POST", "/api/boards/templates", {"acting_user_id": "", "template": tpl})
        self.assertEqual(r.status_code, 200)
        tid = r.json()["template"]["id"]
        mine = await self.req("GET", "/api/boards/templates?acting_user_id=7")
        self.assertEqual([t["id"] for t in mine.json()["templates"]], [tid])
        r = await self.req("POST", f"/api/boards/templates/{tid}/use", {"acting_user_id": "7", "inputs": {}})
        self.assertEqual(r.status_code, 422)                     # 필수 입력 / required input
        r = await self.req("POST", f"/api/boards/templates/{tid}/use", {"acting_user_id": "7", "inputs": {"보고 기간": "9월 2주"}})
        cfg = r.json()["docgen"]
        self.assertEqual((cfg["format"], cfg["source"]), ("docx", "context"))
        self.assertIn("1. 핵심 성과 — 수치 포함", cfg["instruction"])
        self.assertIn("2. 다음 주 계획", cfg["instruction"])
        self.assertIn("보고 기간: 9월 2주", cfg["instruction"])

    async def test_template_management_is_super_only(self):
        # 2026-09-22: 게시판 관리 권한이 슈퍼뿐이라 템플릿 관리(그룹 전용·전체 공용 모두)도 슈퍼만. 쓰는 것은 종전대로 내 그룹 + 공용
        # Manage is super-only since 2026-09-22, so template management (group and shared) is too; using stays my groups + shared
        self.effs["7"] = eff_for({})
        self.effs["12"] = eff_for({})
        base = {"format": "docx", "sections": [{"title": "요약"}]}

        async def create(actor, name, groups):
            return await self.req("POST", "/api/boards/templates", {"acting_user_id": actor, "template": {**base, "name": name, "groups": groups}})

        for actor, groups in (("7", ["og9"]), ("7", []), ("7", ["og3"]), ("12", ["og9"]), ("12", [])):
            self.assertEqual((await create(actor, "시도", groups)).status_code, 403, (actor, groups))
        self.assertEqual((await create("", "팀장 보고", ["og9"])).status_code, 200)
        self.assertEqual((await create("", "전사 공용", [])).status_code, 200)
        self.assertEqual((await self.req("GET", "/api/boards/templates?all=1&acting_user_id=7")).status_code, 403)   # 관리하는 게시판이 없다 / manages no board
        sup = (await self.req("GET", "/api/boards/templates?all=1&acting_user_id=")).json()
        self.assertEqual((sorted(x["name"] for x in sup["templates"]), sup["groups"], sup["can_all"]), (["전사 공용", "팀장 보고"], None, True))
        mine = (await self.req("GET", "/api/boards/templates?acting_user_id=7")).json()
        self.assertEqual(sorted(x["name"] for x in mine["templates"]), ["전사 공용", "팀장 보고"])
        self.effs["3"] = eff_for({})   # 무소속 구성원 / a member of no group
        self.assertEqual((await self.req("GET", "/api/boards/templates?all=1&acting_user_id=3")).status_code, 403)   # 관리 권한 없음 / no manage right
        tid = mine["templates"][0]["id"]
        boards.record_use(tid, 1, "7", True, 900)
        usage = (await self.req("GET", "/api/boards/templates?all=1&acting_user_id=")).json()["usage"]   # 사용 요약은 슈퍼의 관리 목록에 / usage rides the super's management list
        self.assertEqual(usage[tid]["uses"], 1)
        shared = next(x["id"] for x in sup["templates"] if not x.get("groups"))
        self.assertEqual((await self.req("DELETE", f"/api/boards/templates/{shared}?acting_user_id=7")).status_code, 403)
        self.assertEqual((await self.req("DELETE", f"/api/boards/templates/{shared}?acting_user_id=12")).status_code, 403)   # 구성원은 누구도 못 지운다 / no member deletes
        self.assertEqual((await self.req("DELETE", f"/api/boards/templates/{shared}?acting_user_id=")).status_code, 200)

    async def test_personal_library_endpoints_delegate_to_the_board_store(self):
        r = await self.req("POST", "/api/reports/personal", {"acting_user_id": "7", "report": REPORT})
        self.assertEqual(r.status_code, 200)
        rid = r.json()["report"]["id"]
        lib = await self.req("GET", "/api/reports/personal?acting_user_id=7")
        self.assertEqual([x["id"] for x in lib.json()["reports"]], [rid])
        self.assertEqual(lib.json()["reports"][0]["chart"], CHART)
        me = await self.req("GET", "/api/boards/me:7/posts?acting_user_id=7")
        self.assertEqual([p["kind"] for p in me.json()["posts"]], ["report"])
        r = await self.req("DELETE", f"/api/reports/personal/{rid}?acting_user_id=12")
        self.assertEqual(r.status_code, 404)
        r = await self.req("DELETE", f"/api/reports/personal/{rid}?acting_user_id=7")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(reports.list_personal("7"), [])


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        boards.init_boards()
        self.stack.enter_context(patch.object(access, "list_groups", return_value=[dict(g) for g in GROUPS]))
        self.stack.enter_context(patch.object(access, "list_workspaces", return_value=[{"id": "ws_fin", "name": "재무"}]))
        self.stack.enter_context(patch.object(access, "list_members", return_value=[{"no": 7, "name": "강수아", "dept": "인사총무팀"},
                                                                                     {"no": 12, "name": "김팀장", "dept": "PMO"}]))
        self.stack.enter_context(patch.object(access, "descendants", side_effect=lambda ws: [ws]))
        # og9 만 재무 워크스페이스에 접근 / only og9 has access under the finance workspace
        self.stack.enter_context(patch.object(access, "group_map", side_effect=lambda g: {"ws_fin": 1} if g["id"] == "og9" else {}))

    def test_workspace_posts_go_to_the_author_group_and_unknown_authors_to_all(self):
        personal = [{"id": "rp_1", "owner": "7", "created": "2026-09-01T00:00:00", **REPORT}]
        board = [{"id": "bp_1", "ws": "ws_fin", "created": "2026-09-02T00:00:00", **REPORT, "author": {"id": "7", "name": "강수아"}},
                 {"id": "bp_2", "ws": "ws_fin", "created": "2026-09-03T00:00:00", **REPORT, "author": {"id": "", "name": "관리자"}},
                 {"id": "bp_3", "ws": "ws_fin", "created": "2026-09-04T00:00:00", "type": "dashboard", "title": "합본",
                  "items": [{"title": "t", "chart": CHART, "insight": ""}], "author": {"id": "12", "name": "김팀장"}}]
        plan = boards_migrate.migrate_legacy(personal, board, dry_run=True)
        self.assertEqual({p["id"]: p["target"] for p in plan["board"]}, {"bp_1": "g:og9", "bp_2": "all", "bp_3": "g:og9"})
        self.assertEqual(boards.list_posts("g:og9"), [])          # dry run 은 저장하지 않는다 / a dry run writes nothing
        out = boards_migrate.migrate_legacy(personal, board)
        self.assertEqual(out["personal"], 1)
        mine = boards.get_post("rp_1")
        self.assertEqual((mine["board"], mine["kind"], mine["created"]), ("me:7", "report", "2026-09-01T00:00:00"))
        moved = boards.get_post("bp_1")
        self.assertEqual((moved["board"], moved["source"]["ws"], moved["source"]["ws_name"], moved["group"]), ("g:og9", "ws_fin", "재무", "팀장"))
        self.assertNotIn("tags", moved)                            # 출처는 source 에 남는다(태그 폐지) / the origin stays in source (tags retired)
        self.assertEqual(boards.get_post("bp_2")["board"], "all")
        self.assertEqual(boards.get_post("bp_3")["kind"], "dashboard")
        again = boards_migrate.migrate_legacy(personal, board)
        self.assertTrue(again["done"] and again["personal"] == 0)  # 멱등 / idempotent


class TemplateRunTests(BoardsBase):
    """템플릿 → 파일 생성(게시판 2단계, 2026-09-14) — 준비 규칙·항목 순서 고정 개요·사용 기록. 결과 파일의 게시판 공유는 2026-09-18 폐지.
    Template → file generation (boards phase 2): preparation rules, section-fixed outline and usage records. Sharing the
    generated file to a board was retired on 2026-09-18."""

    TPL = {"name": "주간 보고", "format": "docx", "groups": ["og9"], "length": 4,
           "sections": [{"title": "핵심 성과", "hint": "수치 포함"}, "다음 주 계획"],
           "instruction": "존댓말로 쓴다", "inputs": [{"name": "보고 기간", "required": True, "example": "9월 2주"}]}

    def _template(self, **over):
        return boards.add_template(boards_api._validate_template({**self.TPL, **over}))

    def test_prepare_template_run_checks_access_and_inputs_and_builds_the_docgen_config(self):
        from fastapi import HTTPException
        tid = self._template()["id"]
        prep = boards_api.prepare_template_run(tid, "7", {"보고 기간": "9월 2주", "무관": "버림"})
        self.assertEqual((prep["docgen"]["format"], prep["docgen"]["topic"], prep["docgen"]["source"]), ("docx", "주간 보고", "context"))
        self.assertEqual(prep["template"]["inputs"], {"보고 기간": "9월 2주"})              # 선언된 입력만 / declared inputs only
        self.assertEqual([s["title"] for s in prep["template"]["sections"]], ["핵심 성과", "다음 주 계획"])
        self.assertIn("1. 핵심 성과 — 수치 포함", prep["docgen"]["instruction"])
        with self.assertRaises(HTTPException) as cm:                                     # 그룹 밖 사용자 / outsider
            boards_api.prepare_template_run(tid, "99", {"보고 기간": "9월"})
        self.assertEqual(cm.exception.status_code, 403)
        with self.assertRaises(HTTPException) as cm:                                     # 필수 입력 / required input
            boards_api.prepare_template_run(tid, "7", {})
        self.assertEqual(cm.exception.status_code, 422)
        off = self._template(name="비활성", status="off")["id"]
        with self.assertRaises(HTTPException) as cm:
            boards_api.prepare_template_run(off, "7", {"보고 기간": "9월"})
        self.assertEqual(cm.exception.status_code, 404)

    async def test_docgen_run_with_template_fixes_section_pages_and_records_the_use(self):
        from unittest.mock import AsyncMock
        from app import docgen
        docgen.init_docgen()
        chat = db.create_chat("템플릿", "사내")
        tid = self._template()["id"]
        prep = boards_api.prepare_template_run(tid, "7", {"보고 기간": "9월 2주"})
        d = prep["docgen"]

        async def smooth(text):
            yield text

        with patch.object(docgen, "_llm_json", new=AsyncMock(return_value=None)), \
             patch.object(docgen, "collection_material", return_value=""), \
             patch.object(docgen, "build_file"), patch.object(docgen, "_smooth", smooth):
            events = [ev async for ev in docgen.run_docgen(chat, "템플릿으로 만들기", d["format"], d["topic"], d["style"], d["length"],
                                                           d["source"], "7", d["instruction"], True, template=prep["template"])]
        meta = next(e for e in events if e["type"] == "doc_meta")
        self.assertEqual((meta["template"]["id"], meta["template"]["inputs"], meta["total"]), (tid, {"보고 기간": "9월 2주"}, 4))
        titles = [e["title"] for e in events if e["type"] == "doc_page"]
        self.assertEqual(titles, ["주간 보고", "핵심 성과", "다음 주 계획", "요약 및 다음 단계"])   # 표지 + 항목 순서 + 마무리 / cover + sections + closing
        self.assertEqual(events[-1]["type"], "done")
        doc = docgen.get_doc(meta["doc_id"])
        self.assertEqual((doc["status"], doc["template"]["id"], doc["template"]["version"]), ("done", tid, 1))
        usage = boards.template_usage()[tid]
        self.assertEqual((usage["uses"], usage["ok"]), (1, 1))
        # 템플릿으로 만든 파일은 더는 게시판에 올릴 수 없다(2026-09-18) / a template-made file can no longer be posted to a board
        self.effs["7"] = eff_for({"bd_g_og9": 1})
        r = await self.req("POST", "/api/boards/g:og9/posts",
                           {"acting_user_id": "7", "post": {"kind": "tdoc", "title": "주간 보고", "data": {"doc_id": meta["doc_id"]}}})
        self.assertEqual(r.status_code, 422)

    async def test_docgen_api_run_takes_its_config_from_the_template(self):
        from fastapi import HTTPException
        from app import docgen, docgen_api
        docgen.init_docgen()
        chat = db.create_chat("템플릿", "사내")
        tid = self._template()["id"]
        captured = {}

        def fake_run(chat_, cfg):
            captured.update(cfg)
            return "producer"

        with patch("app.artifact_execution.document_run", side_effect=fake_run), \
             patch("app.background_execution.response", side_effect=lambda cid, producer: {"chat": cid, "producer": producer}):
            out = await docgen_api.run(docgen_api.RunIn(chat_id=chat["id"], message="템플릿", format="pptx", topic="", length=99,
                                                        template_id=tid, template_inputs={"보고 기간": "9월"}, acting_user_id="7"))
        self.assertEqual(out, {"chat": chat["id"], "producer": "producer"})
        self.assertEqual((captured["format"], captured["topic"], captured["length"], captured["template"]["id"]), ("docx", "주간 보고", 4, tid))
        self.assertIn("2. 다음 주 계획", captured["instruction"])
        # 이번 작성 요청은 지침(상한 있음)이 아니라 템플릿 참조로 실린다 / the request rides the template reference, not the capped hints
        self.assertEqual(captured["template"]["request"], "템플릿")
        self.assertNotIn("[이번 작성 요청]", captured["instruction"])
        with self.assertRaises(HTTPException) as cm:                                     # 그룹 밖 / outsider → 403 before any run
            await docgen_api.run(docgen_api.RunIn(chat_id=chat["id"], message="템플릿", format="pptx", topic="x",
                                                  template_id=tid, template_inputs={"보고 기간": "9월"}, acting_user_id="99"))
        self.assertEqual(cm.exception.status_code, 403)

    async def test_question_card_is_marked_answered_only_after_the_file_exists(self):
        from app import artifact_execution
        chat = db.create_chat("질문", "사내")
        mid = db.add_message(chat["id"], "assistant", "입력해 주세요", {"kind": "template_question", "actor": "7", "card": {}})
        cfg = {"template_question_id": mid}
        artifact_execution._settle_template_question(cfg, {"snapshot": {}})                       # 실패한 실행 / failed run
        self.assertFalse((db.list_messages(chat["id"])[0].get("meta") or {}).get("answered"))
        artifact_execution._settle_template_question(cfg, {"snapshot": {"artifact": {"id": "doc_x"}}})   # 파일 생성됨 / file exists
        self.assertTrue(db.list_messages(chat["id"])[0]["meta"]["answered"])

    async def test_notification_recipients_share_one_lookup_per_group_set(self):
        self.effs["7"] = eff_for({"bd_all": 1})
        self.effs["12"] = eff_for({"bd_all": 1})
        with patch("app.resources_api._eff", side_effect=lambda aid: self.effs.get(aid)) as eff:
            got = boards_api._notification_recipients("all", {"author": {"id": "7"}})
        self.assertEqual(sorted(got), ["", "12"])
        # 7·12 는 같은 그룹 조합(og9) → 한 번, 7 은 og3 도 → 별도 조합, 슈퍼 1회 / one lookup per distinct group set plus super
        self.assertLessEqual(eff.call_count, 3)
        self.assertEqual(boards_api._notification_recipients("me:7", {"author": {"id": "7"}}), [])   # 개인 보관함은 알리지 않는다 / never for the library


class BoardFeedTests(BoardsBase):
    """게시판 화면 개편(2026-10-06, 사용자 시안): /api/boards/feed — 내 그룹 전체 목록(scope=groups)과 첫 화면의 '내가 최근 추가한 항목'
    (scope=recent). 열람할 수 있는 게시판만 합치고, 남의 보관소는 글쓴이가 나여도 들어가지 않는다.
    Board redesign (2026-10-06): /api/boards/feed — the merged my-groups list (scope=groups) and the hub's recent items
    (scope=recent). Only readable boards are merged; someone else's library never is, even for a post authored by me."""
    NAMES = {"7": "강수아", "12": "김팀장", "": "관리자"}

    def setUp(self):
        super().setUp()
        self.effs["7"] = eff_for({})
        self.effs["12"] = eff_for({})

    def add(self, board, title, author, created, kind="report", pinned=False):
        data = {"insight": title} if kind == "report" else {"type": "dashboard", "items": []}
        p = boards.add_post(board, {"kind": kind, "title": title, "author": {"id": author, "name": self.NAMES[author]}, "data": data},
                            created=created)
        if pinned:
            boards.update_post(p["id"], {"pinned": True})
        return p["id"]

    async def feed(self, query):
        r = await self.req("GET", "/api/boards/feed?" + query)
        return r.status_code, (r.json().get("posts") if r.status_code == 200 else r.json().get("detail"))

    async def test_groups_scope_merges_my_group_boards_pinned_first_and_filters(self):
        a = self.add("g:og3", "인사 월간 보고", "7", "2026-10-01T09:00:00")
        b = self.add("g:og9", "팀장 주간 보고", "12", "2026-10-02T09:00:00", kind="dashboard")
        c = self.add("g:og9", "팀장 고정 공지", "12", "2026-09-01T09:00:00", pinned=True)
        self.add("all", "전체 공지", "", "2026-10-03T09:00:00")
        self.add("me:7", "내 보관 글", "7", "2026-10-04T09:00:00")
        code, posts = await self.feed("scope=groups&acting_user_id=7")
        self.assertEqual((code, [p["id"] for p in posts]), (200, [c, b, a]))   # 그룹 게시판만 · 고정 먼저 · 최신순 / group boards only, pinned first, newest first
        self.assertEqual([p["board"] for p in posts], ["g:og9", "g:og9", "g:og3"])
        code, posts = await self.feed("scope=groups&acting_user_id=12")          # 12 는 og9 만 / 12 is in og9 only
        self.assertEqual([p["id"] for p in posts], [c, b])
        code, posts = await self.feed("scope=groups&group=og9&kind=dashboard&acting_user_id=7")
        self.assertEqual([p["id"] for p in posts], [b])
        code, posts = await self.feed("scope=groups&q=" + "월간" + "&acting_user_id=7")
        self.assertEqual([p["id"] for p in posts], [a])
        code, detail = await self.feed("scope=groups&group=og3&acting_user_id=12")   # 속하지 않은 그룹은 거절 / not a member
        self.assertEqual((code, detail), (403, "이 게시판에 대한 열람 권한이 없습니다"))
        code, posts = await self.feed("scope=groups&acting_user_id=")             # 슈퍼는 모든 그룹 / super sees every group
        self.assertEqual([p["id"] for p in posts], [c, b, a])

    async def test_recent_scope_is_my_own_posts_on_readable_boards_newest_first(self):
        mine_lib = self.add("me:7", "내 보관 글", "7", "2026-10-04T09:00:00")
        mine_grp = self.add("g:og3", "인사 월간 보고", "7", "2026-10-01T09:00:00", pinned=True)
        self.add("g:og9", "팀장 주간 보고", "12", "2026-10-05T09:00:00")          # 남의 글 / someone else's
        self.add("me:12", "남의 보관소", "7", "2026-10-06T09:00:00")               # 글쓴이가 나여도 남의 보관소 / my author id, someone else's library
        self.add("g:og3", "옛 소속 글", "12", "2026-10-03T09:00:00")               # 12 가 지금 못 읽는 게시판 / a board 12 can no longer read
        code, posts = await self.feed("scope=recent&acting_user_id=7")
        self.assertEqual((code, [p["id"] for p in posts]), (200, [mine_lib, mine_grp]))   # 고정과 무관하게 최신순 / newest first regardless of pinning
        code, posts = await self.feed("scope=recent&acting_user_id=12")
        self.assertEqual([p["title"] for p in posts], ["팀장 주간 보고"])
        for i in range(8):
            self.add("me:7", f"추가 {i}", "7", f"2026-10-0{i + 1}T12:00:00")
        code, posts = await self.feed("scope=recent&acting_user_id=7")
        self.assertEqual(len(posts), boards_api.FEED_RECENT_DEFAULT)
        self.assertEqual(posts[0]["title"], "추가 7")
        code, posts = await self.feed("scope=recent&limit=500&acting_user_id=7")
        self.assertEqual(len(posts), 10)                                          # 상한 안의 전부 / everything under the cap
        code, detail = await self.feed("scope=everything&acting_user_id=7")
        self.assertEqual((code, detail), (422, "scope 는 groups 또는 recent 입니다"))

    async def test_library_is_named_like_the_mockup(self):
        r = await self.req("GET", "/api/boards?acting_user_id=7")
        self.assertEqual(r.json()["me"], {"id": "me:7", "name": "내 보관소", "count": 0})


if __name__ == "__main__":
    unittest.main()
