# -*- coding: utf-8 -*-
"""Skill 파일 저장소·업로드 API·MCP 서버/업무 에이전트 붙이기·출력 명세 보존(2026-09-23). 임시 DB, 네트워크·LLM 없음.

Skill-file store, upload APIs, attach through MCP servers and work agents, output-schema passthrough (2026-09-23).
Temp DB; no network or LLM."""
import asyncio
import io
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app import access, mcp_api, mcp_client, mcp_servers, skill_files, work_agents, work_agents_api
from tests.db_fixture import isolate_db
from tests.test_mcp_servers import server_body


def upload(fn, name: str, data: bytes, **kw):
    """비동기 업로드 엔드포인트를 직접 호출 / call the async upload endpoint directly"""
    return asyncio.run(fn(file=UploadFile(file=io.BytesIO(data), filename=name), **kw))


def mcp_agent_body(**over) -> dict:
    d = {"name": "설비 MCP", "description": "설비 도구", "method": "mcp", "enabled": True,
         "config": {"url": "https://mcp.example.invalid/mcp", "auth": {"type": "none"}, "timeout": 30,
                    "tools": [{"name": "ems_alarms", "title": "알람", "description": "알람 조회",
                               "input_schema": {"type": "object", "properties": {"hours": {"type": "integer"}}, "required": []},
                               "kind": "read", "enabled": True}]}}
    d.update(over)
    return d


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        isolate_db(self.stack)
        self.addCleanup(self.stack.close)

    def test_add_validates_extension_size_and_name(self):
        with self.assertRaisesRegex(skill_files.SkillFileError, "형식"):
            skill_files.add("tool.exe", b"x")
        with self.assertRaisesRegex(skill_files.SkillFileError, "빈 파일"):
            skill_files.add("a.yaml", b"")
        with self.assertRaisesRegex(skill_files.SkillFileError, "10MB"):
            skill_files.add("a.yaml", b"x" * (skill_files.MAX_FILE_BYTES + 1))
        with self.assertRaisesRegex(skill_files.SkillFileError, "이름"):
            skill_files.add("", b"x")
        rec = skill_files.add("C:\\tmp\\erp\\salesforce_skills.YAML", "name: 판매\n".encode("utf-8"))
        self.assertEqual(rec["name"], "salesforce_skills.YAML")   # 경로 제거, 대소문자 유지 / path stripped, case kept
        self.assertEqual(rec["size"], len("name: 판매\n".encode("utf-8")))
        self.assertEqual(rec["owner_kind"], "")
        self.assertEqual(skill_files.public(rec), {"id": rec["id"], "name": rec["name"], "size": rec["size"], "uploaded_at": rec["uploaded_at"]})
        self.assertTrue(rec["id"].startswith("sk_") and len(rec["id"]) == 15)
        self.assertEqual(skill_files.get(rec["id"])["content"], "name: 판매\n")

    def test_parse_ids(self):
        self.assertIsNone(skill_files.parse_ids(None))
        self.assertEqual(skill_files.parse_ids(["sk_0123456789ab", "sk_0123456789ab"]), ["sk_0123456789ab"])
        with self.assertRaisesRegex(skill_files.SkillFileError, "배열"):
            skill_files.parse_ids("sk_0123456789ab")
        with self.assertRaisesRegex(skill_files.SkillFileError, "형식"):
            skill_files.parse_ids(["bad"])
        with self.assertRaisesRegex(skill_files.SkillFileError, "최대"):
            skill_files.parse_ids([f"sk_{i:012x}" for i in range(skill_files.MAX_PER_OWNER + 1)])

    def test_attach_keeps_listed_files_and_drops_the_rest(self):
        a = skill_files.add("a.md", b"a")
        b = skill_files.add("b.json", b"{}")
        skill_files.ensure_attachable([a["id"], b["id"]], "mcp", None)
        got = skill_files.attach("mcp", "mcp_1", [a["id"], b["id"]])
        self.assertEqual([f["name"] for f in got], ["a.md", "b.json"])
        self.assertEqual(skill_files.get(a["id"])["owner_id"], "mcp_1")
        # 남의 파일은 붙일 수 없다 / a file owned by another connection cannot be attached
        with self.assertRaisesRegex(skill_files.SkillFileError, "다른 연결"):
            skill_files.ensure_attachable([a["id"]], "mcp", "mcp_2")
        with self.assertRaisesRegex(skill_files.SkillFileError, "다른 연결"):
            skill_files.ensure_attachable([a["id"]], "work_agent", "mcp_1")
        skill_files.ensure_attachable([a["id"]], "mcp", "mcp_1")   # 자기 것은 다시 붙일 수 있다 / re-attaching our own file is fine
        with self.assertRaisesRegex(skill_files.SkillFileError, "알 수 없는"):
            skill_files.ensure_attachable(["sk_ffffffffffff"], "mcp", "mcp_1")
        got = skill_files.attach("mcp", "mcp_1", [a["id"]])   # b 는 목록에서 빠져 지워진다 / b left the list and is deleted
        self.assertEqual([f["id"] for f in got], [a["id"]])
        self.assertIsNone(skill_files.get(b["id"]))

    def test_delete_rules_and_purge(self):
        pending = skill_files.add("p.txt", b"p")
        owned = skill_files.add("o.txt", b"o")
        skill_files.attach("work_agent", "agent_1", [owned["id"]])
        self.assertTrue(skill_files.delete(pending["id"], owner_kind="mcp"))          # 주인 없는 파일은 어느 화면에서든 / pending: any screen
        self.assertFalse(skill_files.delete(owned["id"], owner_kind="mcp"))           # 다른 종류의 주인 / wrong owner kind
        self.assertFalse(skill_files.delete(owned["id"], owner_kind="work_agent", owner_id="agent_2"))
        self.assertTrue(skill_files.delete(owned["id"], owner_kind="work_agent", owner_id="agent_1"))
        self.assertFalse(skill_files.delete("sk_ffffffffffff"))
        old = skill_files.add("old.md", b"old")
        fresh = skill_files.add("fresh.md", b"fresh")
        kept = skill_files.add("kept.md", b"kept")
        skill_files.attach("mcp", "mcp_9", [kept["id"]])
        with skill_files._conn() as conn:   # 오래된 것으로 만든다 / make them old
            conn.execute("UPDATE skill_files SET uploaded_at='2020-01-01T00:00:00' WHERE id IN (?, ?)", (old["id"], kept["id"]))
        self.assertEqual(skill_files.purge_pending(), 1)   # 주인 있는 옛 파일은 남는다 / an old attached file survives
        self.assertIsNone(skill_files.get(old["id"]))
        self.assertIsNotNone(skill_files.get(fresh["id"]))
        self.assertIsNotNone(skill_files.get(kept["id"]))
        self.assertEqual(skill_files.delete_for("mcp", "mcp_9"), 1)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        isolate_db(self.stack)
        self.addCleanup(self.stack.close)
        self.addCleanup(access.rebuild_universe)
        self.stack.enter_context(patch.object(mcp_api, "_rebuild", lambda: None))
        self.stack.enter_context(patch.object(work_agents_api, "_rebuild", lambda: None))

    def test_mcp_upload_attach_on_save_and_delete_with_server(self):
        up = upload(mcp_api.upload_skill, "erp_skills.yaml", b"skills:\n  - sales\n", acting_user_id="")
        self.assertEqual(set(up), {"id", "name", "size", "uploaded_at"})
        with self.assertRaises(HTTPException) as cm:
            upload(mcp_api.upload_skill, "virus.exe", b"x", acting_user_id="")
        self.assertEqual(cm.exception.status_code, 422)
        with self.assertRaises(HTTPException) as cm:
            upload(mcp_api.upload_skill, "a.yaml", b"x", acting_user_id="7")   # 슈퍼관리자 전용 / super admin only
        self.assertEqual(cm.exception.status_code, 403)
        # 없는 파일·남의 파일은 저장이 거부된다 / unknown or foreign files are rejected on save
        with self.assertRaisesRegex(mcp_servers.MCPValidationError, "알 수 없는"):
            mcp_servers.create(server_body(skill_ids=["sk_ffffffffffff"]))
        saved = mcp_api.create(mcp_api.ServerIn(**server_body(skill_ids=[up["id"]])))
        self.assertEqual([f["name"] for f in saved["skills"]], ["erp_skills.yaml"])
        self.assertEqual(skill_files.get(up["id"])["owner_id"], saved["id"])
        self.assertEqual(mcp_servers.public(mcp_servers.get_server(saved["id"]))["skill_count"], 1)
        with self.assertRaisesRegex(mcp_servers.MCPValidationError, "다른 연결"):   # 다른 서버가 같은 파일을 가져가지 못한다 / another server cannot take it
            mcp_servers.create(server_body(name="둘째", skill_ids=[up["id"]]))
        # skill_ids 없이 수정(다시 가져오기 경로)하면 파일이 유지된다 / an update without skill_ids keeps the files
        kept = mcp_servers.update(saved["id"], {**mcp_servers.get_server(saved["id"]), "name": "이름만"})
        self.assertEqual(len(mcp_servers.editor_record(kept)["skills"]), 1)
        # 두 번째 파일 추가 + 첫 파일 제외 / add a second file and drop the first
        up2 = upload(mcp_api.upload_skill, "notes.md", "# 메모".encode("utf-8"), acting_user_id="")
        updated = mcp_api.update(saved["id"], mcp_api.ServerIn(**server_body(name="이름만", skill_ids=[up2["id"]])))
        self.assertEqual([f["name"] for f in updated["skills"]], ["notes.md"])
        self.assertIsNone(skill_files.get(up["id"]))
        # 붙은 파일도 관리 화면에서 지울 수 있고, 없는 id 는 404 / an attached file can be deleted from the admin screen; unknown id → 404
        self.assertEqual(mcp_api.delete_skill(up2["id"], acting_user_id=""), {"ok": True})
        with self.assertRaises(HTTPException) as cm:
            mcp_api.delete_skill(up2["id"], acting_user_id="")
        self.assertEqual(cm.exception.status_code, 404)
        up3 = upload(mcp_api.upload_skill, "later.txt", b"later", acting_user_id="")
        mcp_api.update(saved["id"], mcp_api.ServerIn(**server_body(name="이름만", skill_ids=[up3["id"]])))
        mcp_api.remove(saved["id"], acting_user_id="")
        self.assertIsNone(skill_files.get(up3["id"]))   # 서버 삭제 = 파일도 삭제 / deleting the server deletes its files

    def test_work_agent_upload_attach_and_delete(self):
        up = upload(work_agents_api.upload_skill, "ems_skills.json", b'{"a": 1}', acting_user_id="")
        saved = work_agents_api.create(work_agents_api.AgentIn(**mcp_agent_body(skill_ids=[up["id"]])))
        self.assertEqual([f["name"] for f in saved["skills"]], ["ems_skills.json"])
        # API 방식 에이전트에는 Skill 파일이 없다(skill_ids 무시) / API-based agents have no skill files
        with self.assertRaisesRegex(work_agents.WorkAgentValidationError, "다른 연결"):
            work_agents.create(mcp_agent_body(name="둘째", skill_ids=[up["id"]]))
        with self.assertRaises(HTTPException) as cm:   # 붙은 파일 삭제는 그 에이전트 관리 권한 / deleting an attached file needs manage on that agent
            work_agents_api.delete_skill(up["id"], acting_user_id="7")
        self.assertIn(cm.exception.status_code, (403, 404))
        self.assertEqual(work_agents_api.delete_skill(up["id"], acting_user_id=""), {"ok": True})
        self.assertEqual(work_agents.editor_record(work_agents.get_agent(saved["id"]))["skills"], [])
        up2 = upload(work_agents_api.upload_skill, "more.md", b"more", acting_user_id="")
        work_agents_api.update(saved["id"], work_agents_api.AgentIn(**mcp_agent_body(skill_ids=[up2["id"]])))
        work_agents_api.remove(saved["id"], acting_user_id="")
        self.assertIsNone(skill_files.get(up2["id"]))


class OutputSchemaTests(unittest.TestCase):
    def test_normalize_tool_keeps_output_schema(self):
        raw = {"name": "erp_sales", "inputSchema": {"type": "object", "properties": {}}, "outputSchema": {"type": "object", "properties": {"total": {"type": "number"}}}}
        t = mcp_client.normalize_tool(raw)
        self.assertEqual(t["output_schema"], {"type": "object", "properties": {"total": {"type": "number"}}})
        self.assertIsNone(mcp_client.normalize_tool({"name": "x", "outputSchema": "not-a-dict"})["output_schema"])

    def test_normalize_tools_keeps_and_caps_output_schema(self):
        tools = mcp_servers.normalize_tools([{"name": "a", "input_schema": {"type": "object", "properties": {}}, "output_schema": {"type": "object"}},
                                             {"name": "b", "input_schema": {"type": "object", "properties": {}}, "output_schema": {"big": "x" * 30000}},
                                             {"name": "c", "input_schema": {"type": "object", "properties": {}}}])
        self.assertEqual(tools[0]["output_schema"], {"type": "object"})
        self.assertIsNone(tools[1]["output_schema"])   # 너무 크면 버린다 / oversized schemas are dropped
        self.assertIsNone(tools[2]["output_schema"])


if __name__ == "__main__":
    unittest.main()
