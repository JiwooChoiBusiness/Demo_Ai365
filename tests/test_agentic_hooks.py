# -*- coding: utf-8 -*-
"""Agentic 모드 훅(2026-10-19, 3차): 검증 · 폴더 hooks.json 불러오기와 해시 · 신뢰 판정 · matcher 선택 · 실제 명령 실행
(exit 0/2 · JSON 막기 · add_context · stdin · AI365_HOOK_FILE · 시간 초과). 명령은 이 파이썬(sys.executable)으로 만든다.
실제 LLM · 실 DB · 네트워크 없음.

Agentic mode hooks (phase 3): validation, loading and hashing the folder hooks.json, trust, matcher selection and real
command runs (exit 0/2, JSON block, add_context, stdin, AI365_HOOK_FILE, timeouts). Commands are built from this Python;
no real LLM, real DB or network."""
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from app import agentic_hooks as ah

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fresh_import(name: str) -> list[str]:
    """새 파이썬에서 name 만 import 한 뒤 올라온 app 모듈 / app modules loaded by importing only name in a fresh Python"""
    code = f"import sys, {name}; print(' '.join(sorted(m for m in sys.modules if m.startswith('app.'))))"
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, timeout=120)
    if r.returncode != 0:
        raise AssertionError(r.stderr.decode("utf-8", "replace"))
    return r.stdout.decode("utf-8", "replace").split()


def py(code: str) -> str:
    """이 파이썬으로 code 를 돌리는 명령 한 줄(code 안에는 작은따옴표만) / a command running code with this Python"""
    if os.name == "nt":
        return f'"{sys.executable}" -c "{code}"'
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def hook(code: str, event: str = "pre_tool", matcher: str = "", timeout_sec: int = 30, source: str = "global") -> dict:
    return {"event": event, "matcher": matcher, "command": py(code), "timeout_sec": timeout_sec, "source": source}


def write(path: str, text: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


class FolderCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = os.path.realpath(os.path.join(tmp.name, "작업 폴더"))
        os.makedirs(self.folder)

    def hooks_file(self, doc) -> str:
        return write(os.path.join(self.folder, ".ai365", "hooks.json"),
                     doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False, indent=2))


class ValidateTests(unittest.TestCase):
    def test_validate_normalizes_defaults_and_drops_unknown_keys(self):
        out = ah.validate_hooks([{"event": "pre_tool", "matcher": " ^bash$ ", "command": "  npm test  ", "extra": 1},
                                 {"event": "stop", "matcher": None, "command": "echo 끝", "timeout_sec": "600"},
                                 {"event": "session_start", "command": "x", "timeout_sec": 1.0}])
        self.assertEqual(out, [{"event": "pre_tool", "matcher": "^bash$", "command": "npm test", "timeout_sec": 60},
                               {"event": "stop", "matcher": "", "command": "echo 끝", "timeout_sec": 600},
                               {"event": "session_start", "matcher": "", "command": "x", "timeout_sec": 1}])
        self.assertEqual(ah.validate_hooks(None), [])
        self.assertEqual(ah.validate_hooks([]), [])

    def test_validate_rejects_bad_values_with_a_readable_message(self):
        good = {"event": "pre_tool", "command": "x"}
        cases = [("x", "목록"), ([good] * 51, "50개"), ([1], "객체"), ([{**good, "event": "before"}], "event"),
                 ([{**good, "command": "  "}], "command"), ([{**good, "command": None}], "command"),
                 ([{**good, "command": "a\nb"}], "한 줄"), ([{**good, "matcher": "("}], "정규식"),
                 ([{**good, "matcher": 3}], "matcher"), ([{**good, "matcher": "x" * 301}], "300자"),
                 ([{**good, "timeout_sec": 0}], "timeout_sec"), ([{**good, "timeout_sec": 601}], "timeout_sec"),
                 ([{**good, "timeout_sec": "abc"}], "timeout_sec"), ([{**good, "timeout_sec": True}], "timeout_sec"),
                 ([{**good, "timeout_sec": 1.5}], "timeout_sec"), ([good, {**good, "event": ""}], "훅 2")]
        for raw, needle in cases:
            with self.assertRaises(ValueError, msg=needle) as cm:
                ah.validate_hooks(raw)
            self.assertIn(needle, str(cm.exception))

    def test_select_matches_the_event_and_the_tool_regex_and_ignores_the_matcher_for_other_events(self):
        hooks = [{"event": "pre_tool", "matcher": "^bash$", "command": "a"}, {"event": "pre_tool", "matcher": "", "command": "b"},
                 {"event": "post_tool", "matcher": "edit|write", "command": "c"},
                 {"event": "session_start", "matcher": "bash", "command": "d"}, {"event": "pre_tool", "matcher": "(", "command": "e"}]
        names = lambda xs: [h["command"] for h in xs]
        self.assertEqual(names(ah.select(hooks, "pre_tool", "bash")), ["a", "b"])
        self.assertEqual(names(ah.select(hooks, "pre_tool", "read_file")), ["b"])
        self.assertEqual(names(ah.select(hooks, "post_tool", "edit_file")), ["c"])        # re.search 부분 일치 / partial match
        self.assertEqual(names(ah.select(hooks, "post_tool", "bash")), [])
        self.assertEqual(names(ah.select(hooks, "session_start")), ["d"])                 # 도구 이벤트만 matcher / tool events only
        self.assertEqual(ah.select(hooks, "stop"), [])
        self.assertEqual(ah.select(None, "stop"), [])


class FolderHooksTests(FolderCase):
    def test_no_file_gives_no_hooks_and_no_hash(self):
        self.assertEqual(ah.load_folder_hooks(self.folder), {"hooks": [], "hash": "", "error": ""})
        self.assertEqual(ah.load_folder_hooks(""), {"hooks": [], "hash": "", "error": ""})

    def test_the_hash_follows_the_normalized_hooks_not_the_whitespace(self):
        doc = {"hooks": [{"event": "pre_tool", "matcher": "bash", "command": "python check.py"}]}
        self.hooks_file(doc)
        a = ah.load_folder_hooks(self.folder)
        self.assertEqual(a["error"], "")
        self.assertEqual(a["hooks"], [{"event": "pre_tool", "matcher": "bash", "command": "python check.py", "timeout_sec": 60}])
        self.assertRegex(a["hash"], r"^[0-9a-f]{12}$")
        self.hooks_file("﻿" + json.dumps(doc))                                       # BOM · 공백만 다름 / BOM, whitespace only
        self.assertEqual(ah.load_folder_hooks(self.folder)["hash"], a["hash"])
        self.hooks_file({"hooks": [{**doc["hooks"][0], "command": "python other.py"}]})
        self.assertNotEqual(ah.load_folder_hooks(self.folder)["hash"], a["hash"])          # 명령이 바뀌면 다시 묻는다 / asks again
        self.hooks_file(doc["hooks"])                                                     # 목록만 있어도 / a bare list works too
        self.assertEqual(ah.load_folder_hooks(self.folder)["hash"], a["hash"])
        self.hooks_file({"hooks": []})
        self.assertEqual(ah.load_folder_hooks(self.folder), {"hooks": [], "hash": "", "error": ""})

    def test_parse_and_validation_errors_disable_the_whole_file(self):
        for text, needle in (('{"hooks": [', "파싱 오류"), ('{"other": 1}', "hooks 목록"), ("3", "객체"),
                             ('{"hooks": [{"event": "nope", "command": "x"}]}', "event"),
                             ('{"hooks": [{"event": "stop", "command": "ok"}, {"event": "stop", "command": ""}]}', "훅 2")):
            self.hooks_file(text)
            r = ah.load_folder_hooks(self.folder)
            self.assertEqual((r["hooks"], r["hash"]), ([], ""), text)
            self.assertIn(needle, r["error"], text)

    def test_active_hooks_add_folder_hooks_only_for_the_trusted_hash(self):
        settings = {"hooks": [{"event": "stop", "command": "echo 전역"}, {"event": "bad"}]}   # 틀린 전역 항목은 건너뛴다 / skipped
        self.hooks_file({"hooks": [{"event": "pre_tool", "command": "echo 폴더"}]})
        h = ah.load_folder_hooks(self.folder)["hash"]
        only_global = [{"event": "stop", "matcher": "", "command": "echo 전역", "timeout_sec": 60, "source": "global"}]
        self.assertEqual(ah.active_hooks(settings, self.folder, ""), only_global)
        self.assertEqual(ah.active_hooks(settings, self.folder, "deny:" + h), only_global)
        self.assertEqual(ah.active_hooks(settings, self.folder, "allow:000000000000"), only_global)   # 해시가 다르다 / stale hash
        both = ah.active_hooks(settings, self.folder, "allow:" + h)
        self.assertEqual([(x["command"], x["source"]) for x in both], [("echo 전역", "global"), ("echo 폴더", "folder")])
        self.hooks_file({"hooks": [{"event": "pre_tool", "command": "echo 바뀜"}]})
        self.assertEqual(ah.active_hooks(settings, self.folder, "allow:" + h), only_global)    # 내용이 바뀌면 다시 신뢰 필요 / re-trust
        self.assertEqual(ah.active_hooks({}, None, ""), [])


class RunTests(FolderCase):
    def run_one(self, code: str, payload=None, **kw) -> dict:
        return ah.run_hook(hook(code, **kw), payload or {"tool": "bash"}, self.folder)

    def test_exit_zero_allows_and_reports_output_cwd_and_timing(self):
        r = self.run_one("import os; print('안녕'); print(os.getcwd())")
        self.assertEqual((r["exit_code"], r["decision"], r["timed_out"], r["reason"], r["add_context"]), (0, "allow", False, "", ""))
        first, cwd = r["output"].splitlines()
        self.assertEqual(first, "안녕")
        self.assertEqual(os.path.normcase(os.path.realpath(cwd)), os.path.normcase(self.folder))   # 세션 폴더에서 / in the folder
        self.assertEqual((r["event"], r["source"], r["matcher"]), ("pre_tool", "global", ""))
        self.assertGreaterEqual(r["duration_ms"], 0)
        r = self.run_one("import sys; sys.stderr.write('경고'); sys.exit(1)")
        self.assertEqual((r["exit_code"], r["decision"], r["output"]), (1, "allow", "경고"))    # 다른 종료 코드는 허용 / allowed

    def test_exit_two_blocks_with_the_stderr_or_stdout_tail_as_the_reason(self):
        r = self.run_one("import sys; print('검사 중'); sys.stderr.write('위험한 명령입니다'); sys.exit(2)")
        self.assertEqual((r["exit_code"], r["decision"], r["reason"]), (2, "block", "위험한 명령입니다"))
        self.assertEqual(r["output"], "검사 중\n위험한 명령입니다")                            # stdout 뒤에 stderr / stdout then stderr
        r = self.run_one("import sys; print('x' * 800); sys.exit(2)")
        self.assertEqual((r["decision"], r["reason"]), ("block", "x" * 500))                 # 끝 500자 / the last 500 chars
        r = self.run_one("import sys; sys.exit(2)")
        self.assertEqual((r["decision"], r["reason"]), ("block", "exit 2"))

    def test_a_json_last_line_can_block_or_add_context(self):
        r = self.run_one("import json; print('로그'); print(json.dumps({'decision': 'block', 'reason': '정책 위반'}))")
        self.assertEqual((r["exit_code"], r["decision"], r["reason"]), (0, "block", "정책 위반"))
        r = self.run_one("import json; print(json.dumps({'add_context': '테스트는 npm test 로'}))")
        self.assertEqual((r["decision"], r["add_context"]), ("allow", "테스트는 npm test 로"))
        r = self.run_one("import json; print(json.dumps({'decision': 'block'}, indent=2))")   # 여러 줄 JSON / pretty JSON
        self.assertEqual((r["decision"], r["reason"]), ("block", "decision=block"))
        r = self.run_one("import json, sys; print(json.dumps({'reason': 'JSON 이유'})); sys.exit(2)")
        self.assertEqual((r["decision"], r["reason"]), ("block", "JSON 이유"))
        r = self.run_one("print('{not json}')")
        self.assertEqual((r["decision"], r["add_context"]), ("allow", ""))
        r = self.run_one("import json; print('x' * 10000); print(json.dumps({'add_context': '끝'}))")
        self.assertEqual(r["add_context"], "끝")                                            # 긴 출력 뒤 JSON / JSON after long output
        self.assertLessEqual(len(r["output"]), ah.OUTPUT_MAX)
        self.assertIn("생략", r["output"])

    def test_the_payload_arrives_on_stdin_and_in_the_hook_file_which_is_removed(self):
        code = ("import json, os, sys; d = json.load(sys.stdin); f = os.environ['AI365_HOOK_FILE']; "
                "e = json.load(open(f, encoding='utf-8')); print(d['tool'], d['n'], d['event'], e['note'], "
                "os.environ['AI365_HOOK_EVENT']); print(f)")
        r = self.run_one(code, payload={"tool": "edit_file", "n": 7, "note": "한글"}, event="post_tool")
        line, path = r["output"].splitlines()
        self.assertEqual(line, "edit_file 7 post_tool 한글 post_tool")
        self.assertFalse(os.path.exists(path))                                              # 임시 파일 삭제 / temp file removed

    def test_secret_variables_never_reach_the_hook(self):
        with patch.dict(os.environ, {"AI365_FAKE_API_KEY": "x", "AI365_PLAIN": "kept"}):
            r = self.run_one("import os; print('AI365_FAKE_API_KEY' in os.environ, os.environ.get('AI365_PLAIN'))")
        self.assertEqual(r["output"], "False kept")

    def test_a_timeout_kills_the_hook_and_allows(self):
        t0 = time.monotonic()
        r = self.run_one("import time; print('start', flush=True); time.sleep(20)", timeout_sec=1)
        self.assertLess(time.monotonic() - t0, 15)
        self.assertEqual((r["timed_out"], r["decision"], r["exit_code"], r["reason"]), (True, "allow", None, ""))
        self.assertIn("시간 초과(1초)", r["output"])

    def test_a_hook_that_cannot_start_is_reported_and_allowed(self):
        r = ah.run_hook(hook("print(1)"), {}, os.path.join(self.folder, "없는 폴더"))
        self.assertEqual((r["decision"], r["exit_code"]), ("allow", None))
        self.assertIn("훅을 시작하지 못했습니다", r["output"])
        r = ah.run_hook({"event": "stop", "command": " "}, {}, self.folder)
        self.assertEqual((r["decision"], r["output"]), ("allow", "훅 명령이 비어 있습니다"))

    def test_run_event_runs_every_matching_hook_and_ors_the_blocks(self):
        hooks = [hook("import sys; sys.stderr.write('첫째가 막음'); sys.exit(2)", matcher="^bash$"),
                 hook("import json; print(json.dumps({'add_context': '둘째 맥락'}))"),
                 hook("import json, sys; d = json.load(sys.stdin); print(json.dumps({'add_context': d['tool'] + ' 셋째'}))"),
                 hook("print('다른 이벤트')", event="post_tool")]
        r = ah.run_event(hooks, "pre_tool", {"args": {"command": "ls"}}, self.folder, tool="bash")
        self.assertEqual(len(r["results"]), 3)                                              # 막아도 끝까지 / runs all three
        self.assertEqual((r["block"], r["reason"]), (True, "첫째가 막음"))
        self.assertEqual(r["add_context"], "둘째 맥락\n\nbash 셋째")
        r = ah.run_event(hooks, "pre_tool", {}, self.folder, tool="read_file")
        self.assertEqual((len(r["results"]), r["block"], r["reason"]), (2, False, ""))
        r = ah.run_event(hooks, "stop", {}, self.folder)
        self.assertEqual(r, {"results": [], "block": False, "reason": "", "add_context": ""})


class RobustnessTests(FolderCase):
    """M1 · L2(적대 검토): 깊은 JSON · 훅 하나의 예외 · ASCII payload / deep JSON, one hook raising, ASCII payload"""

    DEEP_LIST = "[" * 3000 + "]" * 3000
    DEEP_OBJECT = '{"a":' * 3000 + "1" + "}" * 3000

    def test_a_deep_hooks_json_is_a_parse_error_and_the_global_hooks_stay(self):
        self.hooks_file('{"hooks": ' + self.DEEP_LIST + "}")
        r = ah.load_folder_hooks(self.folder)
        self.assertEqual((r["hooks"], r["hash"]), ([], ""))
        self.assertIn("깊게", r["error"])
        settings = {"hooks": [{"event": "pre_tool", "command": "echo 전역"}]}
        self.assertEqual([h["command"] for h in ah.active_hooks(settings, self.folder, "")], ["echo 전역"])

    def test_a_deep_json_last_line_is_simply_not_a_verdict(self):
        path = os.path.join(self.folder, "deep.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.DEEP_OBJECT)
        arg = f'"{path}"' if os.name == "nt" else shlex.quote(path)
        r = ah.run_hook({"event": "pre_tool", "command": py("import sys; sys.stdout.write(open(sys.argv[1]).read())") + " " + arg,
                         "timeout_sec": 30}, {"tool": "bash"}, self.folder)
        self.assertEqual((r["exit_code"], r["decision"], r["reason"], r["add_context"]), (0, "allow", "", ""))
        self.assertLessEqual(len(r["output"]), ah.OUTPUT_MAX)

    def test_one_hook_raising_keeps_the_block_of_another(self):
        hooks = [hook("import sys; sys.exit(2)"), hook("print('둘째')"), hook("print('셋째')")]
        real = ah.run_hook
        seen = []

        def flaky(h, payload, folder):
            seen.append(h["command"])
            if len(seen) == 2:
                raise RuntimeError("훅 실행기 고장")
            return real(h, payload, folder)
        with patch.object(ah, "run_hook", side_effect=flaky), self.assertLogs("ai365.agentic", "WARNING"):
            r = ah.run_event(hooks, "pre_tool", {}, self.folder, tool="bash")
        self.assertEqual(len(r["results"]), 3)                                     # 끝까지 돈다 / all three ran
        self.assertTrue(r["block"])                                                # 첫 훅의 막기는 남는다 / block kept
        self.assertEqual((r["results"][1]["decision"], r["results"][1]["exit_code"]), ("allow", None))
        self.assertIn("RuntimeError", r["results"][1]["error"])
        self.assertIn("훅 실행 중 오류", r["results"][1]["output"])
        self.assertEqual(r["results"][2]["output"], "셋째")

    def test_the_payload_is_ascii_so_a_hook_reading_with_its_locale_encoding_still_works(self):
        code = ("import json, os, sys; raw = sys.stdin.buffer.read(); d = json.load(open(os.environ['AI365_HOOK_FILE'])); "
                "print(all(b < 128 for b in raw), d['args']['path'] == '보고서/요약.md')")
        r = ah.run_hook(hook(code), {"tool": "write_file", "args": {"path": "보고서/요약.md"}}, self.folder)
        self.assertEqual((r["exit_code"], r["output"]), (0, "True True"))


class ImportTests(unittest.TestCase):
    def test_importing_the_module_pulls_in_neither_the_store_nor_the_executor(self):
        """agentic_store 가 설정 검증에 이 모듈을 불러도 순환 import 가 생기지 않는다 / no import cycle with agentic_store"""
        mods = fresh_import("app.agentic_hooks")
        self.assertIn("app.agentic_hooks", mods)
        self.assertNotIn("app.agentic_store", mods)
        self.assertNotIn("app.agentic_exec", mods)


if __name__ == "__main__":
    unittest.main()
