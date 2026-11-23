# -*- coding: utf-8 -*-
"""Agentic 모드 슬래시 명령 · 스킬(2026-10-19, 3차): '/이름 인자' 가르기 경계값 · front matter · 폴더 불러오기(이름 소문자화 ·
잘못된 이름 무시 · 폴더 밖 링크 무시) · 전역 검증 · $ARGUMENTS 펼치기 · 목록 우선순위(내장 > 폴더 > 전역, 내장 보호) ·
스킬 프롬프트 상한 · 찾기 · /help 글. 임시 폴더만 쓴다(실제 LLM · 실 DB · 네트워크 없음).

Agentic mode slash commands and skills (phase 3): parse_slash edge cases, front matter, folder loading (lower-cased
names, bad names ignored, outside links ignored), global validation, $ARGUMENTS expansion, list priority (built-in >
folder > global, built-ins protected), the skills prompt cap, lookups and the /help text. Temp folders only."""
import os
import subprocess
import sys
import tempfile
import unittest

from app import agentic_commands as ac

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT_BUILTINS = ["help", "compact", "plan", "auto", "ask", "model", "clear", "checkpoint", "undo", "commit", "cost",
                     "init", "notify", "skills", "hooks", "connectors"]


def write(path: str, text: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def link_dir(target: str, link: str) -> bool:
    """폴더 링크(심볼릭 링크, 안 되면 Windows 정션) / a directory link (symlink, else a Windows junction)"""
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        try:
            import _winapi
            _winapi.CreateJunction(target, link)
            return True
        except (ImportError, OSError):
            return False


class FolderCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.folder = os.path.join(self.tmp, "작업 폴더")
        os.makedirs(self.folder)

    def p(self, rel: str) -> str:
        return os.path.join(self.folder, *rel.split("/"))


class ParseTests(unittest.TestCase):
    def test_parse_slash_edge_cases(self):
        good = {"/help": ("help", ""), "  /model  gemini-3.7-flash  ": ("model", "gemini-3.7-flash"), "/Help": ("help", ""),
                "/commit 첫 줄\n둘째 줄": ("commit", "첫 줄\n둘째 줄"), "/review-pr 12": ("review-pr", "12"), "/a": ("a", ""),
                "/x_y-z 1  2": ("x_y-z", "1  2"), "/help\n": ("help", ""), "\n/plan": ("plan", ""), "/9lives x": ("9lives", "x"),
                "/" + "a" * 40: ("a" * 40, "")}
        for text, want in good.items():
            self.assertEqual(ac.parse_slash(text), want, repr(text))
        for text in ("/", "/ help", "//help", "// 주석", "help", "", "   ", None, 3, "/usr/bin/python 오류", "/한글",
                     "/" + "a" * 41, "/-x", "/_x", "a /help", "/help:", "/.hidden", "/a.b", "/a/c"):
            self.assertIsNone(ac.parse_slash(text), repr(text))

    def test_parse_front_matter_reads_key_value_lines_only(self):
        meta, body = ac.parse_front_matter("---\nname: Review\ndescription: '코드 리뷰'\n# 주석\n아무 줄\nurl: http://x:1/y\n"
                                           "args: \"<PR 번호>\"\nname: 두 번째\n---\n\n본문 첫 줄\n  들여쓴 줄\n\n")
        self.assertEqual(meta, {"name": "Review", "description": "코드 리뷰", "url": "http://x:1/y", "args": "<PR 번호>"})
        self.assertEqual(body, "본문 첫 줄\n  들여쓴 줄")
        self.assertEqual(ac.parse_front_matter("그냥 본문\n"), ({}, "그냥 본문"))
        self.assertEqual(ac.parse_front_matter("---\nname: x\n본문"), ({}, "---\nname: x\n본문"))      # 닫히지 않음 / unclosed
        self.assertEqual(ac.parse_front_matter("﻿---\r\nDescription: 설명\r\n---\r\n본문\r\n"), ({"description": "설명"}, "본문"))
        self.assertEqual(ac.parse_front_matter("---\n---\n본문"), ({}, "본문"))
        self.assertEqual(ac.parse_front_matter(None), ({}, ""))


class BuiltinTests(unittest.TestCase):
    def test_builtins_follow_the_contract_and_carry_korean_descriptions(self):
        self.assertEqual([b["name"] for b in ac.BUILTINS], CONTRACT_BUILTINS)
        self.assertEqual(ac.BUILTIN_NAMES, frozenset(CONTRACT_BUILTINS))
        for b in ac.BUILTINS:
            self.assertEqual(set(b), {"name", "description", "args"})
            self.assertTrue(b["description"])
            self.assertNotIn("—", b["description"] + b["args"])                       # 줄표 금지 / no em dash
        self.assertEqual({b["name"]: b["args"] for b in ac.BUILTINS if b["args"]},
                         {"model": "<모델 id>", "checkpoint": "[이름]", "commit": "[메시지]", "notify": "on|off"})


class ValidateTests(unittest.TestCase):
    def test_validate_normalizes_names_descriptions_and_bodies(self):
        out = ac.validate_commands([{"name": " Review ", "description": " 코드\n리뷰 ", "body": "\n본문 $ARGUMENTS\n", "extra": 1},
                                    {"name": "deploy_check-2", "body": "x"}])
        self.assertEqual(out, [{"name": "review", "description": "코드 리뷰", "body": "본문 $ARGUMENTS"},
                               {"name": "deploy_check-2", "description": "", "body": "x"}])
        self.assertEqual(ac.validate_commands(None), [])
        self.assertEqual(ac.validate_skills([{"name": "pdf", "description": "PDF 보고서", "body": "지시"}]),
                         [{"name": "pdf", "description": "PDF 보고서", "body": "지시"}])

    def test_validate_rejects_bad_items(self):
        ok = {"name": "x", "body": "b"}
        cases = [("x", "목록"), ([ok] * 51, "50개"), ([1], "객체"), ([{**ok, "name": "Bad Name"}], "이름"),
                 ([{**ok, "name": ""}], "이름"), ([{**ok, "name": None}], "이름"), ([{**ok, "name": "-x"}], "이름"),
                 ([{**ok, "name": "a" * 41}], "이름"), ([{**ok, "name": "help"}], "내장"), ([{**ok, "name": "Commit"}], "내장"),
                 ([ok, {**ok, "name": "X"}], "겹칩니다"), ([{**ok, "description": "가" * 301}], "300자"),
                 ([{**ok, "description": 3}], "문자열"), ([{**ok, "body": "  "}], "본문"), ([{**ok, "body": None}], "본문"),
                 ([{**ok, "body": "가" * 20001}], "20,000자"), ([ok, {**ok, "name": "y", "body": ""}], "명령 2")]
        for raw, needle in cases:
            with self.assertRaises(ValueError, msg=needle) as cm:
                ac.validate_commands(raw)
            self.assertIn(needle, str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            ac.validate_skills([{"name": "s", "body": ""}])
        self.assertIn("스킬 1", str(cm.exception))
        self.assertEqual(len(ac.validate_commands([{"name": f"c{i}", "body": "b"} for i in range(50)])), 50)


class ExpandTests(unittest.TestCase):
    def test_expand_replaces_arguments_or_appends_them(self):
        self.assertEqual(ac.expand("리뷰: $ARGUMENTS 끝", "PR 12"), "리뷰: PR 12 끝")
        self.assertEqual(ac.expand("A $ARGUMENTS B $ARGUMENTS", " x "), "A x B x")
        self.assertEqual(ac.expand("리뷰해줘", "PR 12"), "리뷰해줘\n\n[인자] PR 12")
        self.assertEqual(ac.expand("리뷰해줘", ""), "리뷰해줘")
        self.assertEqual(ac.expand("리뷰해줘", "   "), "리뷰해줘")
        self.assertEqual(ac.expand("$ARGUMENTS 만", ""), " 만")
        self.assertEqual(ac.expand(None, None), "")


class FolderLoadTests(FolderCase):
    def test_folder_commands_lowercase_names_skip_bad_ones_and_read_front_matter(self):
        write(self.p(".ai365/commands/Review.md"), "---\ndescription: 코드 리뷰\nargs: <PR 번호>\n---\n$ARGUMENTS 를 리뷰하라\n")
        write(self.p(".ai365/commands/fix-bug.md"), "# 버그 고치기\n재현하고 고친다 $ARGUMENTS\n")
        write(self.p(".ai365/commands/plain.md"), "설명 없는 명령\n")
        write(self.p(".ai365/commands/help.md"), "내장을 덮으려는 명령\n")
        for bad in ("bad name.md", "한글.md", ".hidden.md", "notes.txt", "empty.md", "-dash.md"):
            write(self.p(".ai365/commands/" + bad), "" if bad == "empty.md" else "본문\n")
        with open(self.p(".ai365/commands/bin.md"), "wb") as f:
            f.write(b"\x00\x01binary")
        cmds = {c["name"]: c for c in ac.load_folder_commands(self.folder)}
        self.assertEqual(sorted(cmds), ["fix-bug", "help", "plain", "review"])
        self.assertEqual(cmds["review"], {"name": "review", "description": "코드 리뷰", "body": "$ARGUMENTS 를 리뷰하라",
                                          "args": "<PR 번호>", "source": "folder"})
        self.assertEqual((cmds["fix-bug"]["description"], cmds["fix-bug"]["args"]), ("버그 고치기", "[인자]"))
        self.assertEqual((cmds["plain"]["description"], cmds["plain"]["args"]), ("설명 없는 명령", ""))
        self.assertEqual(ac.load_folder_commands(os.path.join(self.tmp, "없음")), [])
        self.assertEqual(ac.load_folder_commands(""), [])

    def test_folder_skills_take_the_front_matter_name_or_the_folder_name_and_list_helper_files(self):
        write(self.p(".ai365/skills/pdf-report/SKILL.md"), "---\nname: PDF\ndescription: PDF 보고서 만들기\n---\n지시 본문\n")
        for rel in ("templates/a.md", "scripts/run.py", ".env.example", ".hidden/secret.txt", "node_modules/x.js"):
            write(self.p(".ai365/skills/pdf-report/" + rel), "x\n")
        write(self.p(".ai365/skills/Deploy/SKILL.md"), "# 배포 순서\n1. 테스트\n")
        write(self.p(".ai365/skills/bad-front/SKILL.md"), "---\nname: Bad Name!\n---\n이름이 틀리면 폴더 이름\n")
        write(self.p(".ai365/skills/empty/SKILL.md"), "")
        write(self.p(".ai365/skills/no-skill-file/README.md"), "x\n")
        write(self.p(".ai365/skills/.hidden/SKILL.md"), "숨김\n")
        write(self.p(".ai365/skills/loose.md"), "폴더가 아닌 파일\n")
        skills = {s["name"]: s for s in ac.load_folder_skills(self.folder)}
        self.assertEqual(sorted(skills), ["bad-front", "deploy", "pdf"])
        pdf = skills["pdf"]
        self.assertEqual((pdf["description"], pdf["body"], pdf["source"]), ("PDF 보고서 만들기", "지시 본문", "folder"))
        self.assertEqual(os.path.normcase(pdf["dir"]), os.path.normcase(os.path.realpath(self.p(".ai365/skills/pdf-report"))))
        self.assertEqual(pdf["files"], [".env.example", "scripts/run.py", "templates/a.md"])   # 숨김 · 무거운 폴더 제외 / skipped
        self.assertEqual((skills["deploy"]["description"], skills["deploy"]["files"]), ("배포 순서", []))
        for i in range(ac.SKILL_FILES_MAX + 5):
            write(self.p(f".ai365/skills/Deploy/many/f{i:03d}.txt"), "x")
        self.assertEqual(len(ac.find_skill("deploy", self.folder, {})["files"]), ac.SKILL_FILES_MAX)

    def test_links_that_point_outside_the_folder_are_not_read(self):
        outside = os.path.join(self.tmp, "outside")
        write(os.path.join(outside, "cmds", "evil.md"), "밖의 명령\n")
        write(os.path.join(outside, "skill", "SKILL.md"), "밖의 스킬\n")
        os.makedirs(self.p(".ai365/skills"))
        if not (link_dir(os.path.join(outside, "cmds"), self.p(".ai365/commands"))
                and link_dir(os.path.join(outside, "skill"), self.p(".ai365/skills/evil"))):
            self.skipTest("심볼릭 링크 · 정션을 만들 수 없는 환경 / cannot create a symlink or junction here")
        self.assertEqual(ac.load_folder_commands(self.folder), [])
        self.assertEqual(ac.load_folder_skills(self.folder), [])


class MergeTests(FolderCase):
    def setUp(self):
        super().setUp()
        write(self.p(".ai365/commands/review.md"), "---\ndescription: 폴더 리뷰\n---\n폴더 본문 $ARGUMENTS\n")
        write(self.p(".ai365/commands/help.md"), "내장을 덮으려는 명령\n")
        write(self.p(".ai365/skills/pdf/SKILL.md"), "---\ndescription: 폴더 PDF\n---\n폴더 PDF 본문\n")
        write(self.p(".ai365/skills/pdf/form.md"), "양식\n")
        self.settings = {
            "commands": [{"name": "review", "description": "전역 리뷰", "body": "전역 본문"},
                         {"name": "deploy-check", "description": "전역 배포 점검", "body": "점검 $ARGUMENTS"},
                         {"name": "help", "description": "덮기", "body": "x"}, {"name": "Bad Name", "body": "x"}],
            "skills": [{"name": "pdf", "description": "전역 PDF", "body": "전역 PDF 본문"},
                       {"name": "style", "description": "글 스타일", "body": "스타일 본문"},
                       {"name": "deploy-check", "description": "명령과 겹치는 스킬", "body": "겹침"}]}

    def test_list_all_puts_builtins_first_folder_over_global_and_protects_builtins(self):
        items = ac.list_all(self.folder, self.settings, connectors_count=2)
        names = [(x["name"], x["source"]) for x in items]
        self.assertEqual(names[:16], [(n, "builtin") for n in sorted(CONTRACT_BUILTINS)])
        self.assertEqual(names[16:], [("deploy-check", "global"), ("pdf", "skill"), ("review", "folder"), ("style", "skill")])
        by = {(x["name"], x["source"]): x for x in items}
        self.assertEqual(by[("review", "folder")], {"name": "review", "description": "폴더 리뷰", "source": "folder", "args": "[인자]"})
        self.assertEqual(by[("deploy-check", "global")]["args"], "[인자]")
        self.assertEqual(by[("pdf", "skill")], {"name": "pdf", "description": "폴더 PDF", "source": "skill", "args": "[요청]"})
        self.assertEqual(by[("help", "builtin")]["description"], "명령과 스킬 목록을 봅니다")      # 내장은 덮이지 않는다 / protected
        self.assertEqual(by[("skills", "builtin")]["description"], "쓸 수 있는 스킬 목록을 봅니다 · 2개")
        self.assertEqual(by[("connectors", "builtin")]["description"], "이 세션에 연결된 도구 목록을 봅니다 · 연결 2개")
        plain = {x["name"]: x for x in ac.list_all(None, {})}
        self.assertEqual(len(plain), 16)
        self.assertEqual(plain["connectors"]["description"], "이 세션에 연결된 도구 목록을 봅니다")
        for x in items:
            self.assertEqual(set(x), {"name", "description", "source", "args"})

    def test_find_command_and_find_skill(self):
        self.assertEqual(ac.find_command("review", self.folder, self.settings)["body"], "폴더 본문 $ARGUMENTS")   # 폴더 > 전역 / folder wins
        self.assertEqual(ac.find_command("/Review", self.folder, self.settings)["source"], "folder")
        self.assertEqual(ac.find_command("review", None, self.settings)["body"], "전역 본문")
        self.assertEqual(ac.find_command("deploy-check", self.folder, self.settings)["source"], "global")
        for name in ("help", "nope", "bad name", "", None):
            self.assertIsNone(ac.find_command(name, self.folder, self.settings), name)
        pdf = ac.find_skill("pdf", self.folder, self.settings)
        self.assertEqual((pdf["body"], pdf["source"], pdf["files"]), ("폴더 PDF 본문", "folder", ["form.md"]))
        style = ac.find_skill("style", self.folder, self.settings)
        self.assertEqual((style["body"], style["source"], style["dir"], style["files"]), ("스타일 본문", "global", "", []))
        self.assertEqual(ac.find_skill("deploy-check", self.folder, self.settings)["body"], "겹침")   # skill 도구로는 읽힌다 / still readable
        self.assertIsNone(ac.find_skill("help", self.folder, self.settings))
        self.assertIsNone(ac.find_skill("nope", self.folder, self.settings))

    def test_skills_prompt_lists_name_and_description_up_to_thirty(self):
        self.assertEqual(ac.skills_prompt(None, {}), "")
        self.assertEqual(ac.skills_prompt(self.folder, self.settings),
                         "[사용 가능한 스킬]\n- deploy-check: 명령과 겹치는 스킬\n- pdf: 폴더 PDF\n- style: 글 스타일")
        many = {"skills": [{"name": f"s{i:02d}", "description": f"설명 {i}" if i % 2 else "", "body": "b"} for i in range(35)]}
        lines = ac.skills_prompt(None, many).split("\n")
        self.assertEqual(len(lines), 31)
        self.assertEqual(lines[:3], ["[사용 가능한 스킬]", "- s00", "- s01: 설명 1"])

    def test_skill_text_adds_the_helper_files_of_folder_skills_and_caps_the_body(self):
        pdf = ac.find_skill("pdf", self.folder, self.settings)
        self.assertEqual(ac.skill_text(pdf), f"폴더 PDF 본문\n\n같은 폴더의 파일({pdf['dir']}): form.md")
        self.assertEqual(ac.skill_text(ac.find_skill("style", self.folder, self.settings)), "스타일 본문")
        long = ac.skill_text({"body": "가" * (ac.MAX_BODY + 10)})
        self.assertTrue(long.startswith("가" * ac.MAX_BODY + "\n…("))
        self.assertIn("잘랐습니다", long)
        self.assertEqual(ac.skill_text(None), "")

    def test_help_text_lists_builtins_user_commands_and_skills(self):
        text = ac.help_text(self.folder, self.settings, connectors=1)
        for needle in ("**내장 명령**", "- `/model <모델 id>` 모델을 바꿉니다", "- `/notify on|off` 완료 알림(메일)을 켜거나 끕니다",
                       "**사용자 명령**", "- `/review [인자]` 폴더 리뷰 (폴더)", "- `/deploy-check [인자]` 전역 배포 점검 (전역)",
                       "**스킬**", "- `/pdf [요청]` 폴더 PDF", "- `/style [요청]` 글 스타일", ".ai365/commands/<이름>.md",
                       "연결 1개"):
            self.assertIn(needle, text)
        self.assertNotIn("—", text)
        empty = ac.help_text(None, {})
        self.assertEqual(empty.count("- 없음"), 2)


class ImportTests(unittest.TestCase):
    def test_importing_the_module_pulls_in_neither_the_store_nor_the_executor(self):
        """agentic_store 가 설정 검증에 이 모듈을 불러도 순환 import 가 생기지 않는다 / no import cycle with agentic_store"""
        code = "import sys, app.agentic_commands; print(' '.join(sorted(m for m in sys.modules if m.startswith('app.'))))"
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        mods = r.stdout.decode("utf-8", "replace").split()
        self.assertIn("app.agentic_commands", mods)
        self.assertNotIn("app.agentic_store", mods)
        self.assertNotIn("app.agentic_exec", mods)


if __name__ == "__main__":
    unittest.main()
