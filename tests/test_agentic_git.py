# -*- coding: utf-8 -*-
"""Agentic 모드 git(2026-10-19, 2차): 체크포인트 · 되돌리기 · 변경 목록 · diff · 커밋 · 커밋 메시지 제안.
실제 git 으로 임시 저장소에서 확인한다. 전역 · 시스템 git 설정은 읽지 않게 막아(GIT_CONFIG_GLOBAL = 빈 파일,
GIT_CONFIG_NOSYSTEM=1) 이 PC 의 autocrlf · 신원 · 훅 설정과 무관하게 돈다. 실제 LLM · 실 DB · 네트워크 없음.

Agentic mode git (phase 2): checkpoints, restore, change list, diff, commit and message suggestions, checked with the
real git in temporary repositories. Global and system git config are blocked (GIT_CONFIG_GLOBAL = an empty file,
GIT_CONFIG_NOSYSTEM=1) so this PC's autocrlf, identity and hook settings never matter. No real LLM, real DB or network."""
import glob
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from app import agentic_exec as ax, agentic_git as ag

GIT = shutil.which("git")


def link_dir(target: str, link: str) -> bool:
    """폴더 링크: Windows 정션(mklink /J 와 같고 권한이 필요 없다), 안 되면 심볼릭 링크 / a junction, else a symlink"""
    try:
        import _winapi
        _winapi.CreateJunction(target, link)
        return True
    except (ImportError, OSError):
        pass
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        return False


def _rmtree(path: str) -> None:
    """git 객체 파일은 Windows 에서 읽기 전용이라 권한을 풀어 가며 지운다 / git objects are read-only on Windows"""
    def fix(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=fix)
    else:   # pragma: no cover
        shutil.rmtree(path, onerror=fix)


def write(path: str, text: str = "", data: bytes | None = None) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if data is not None else text.encode("utf-8"))
    return path


def read(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


@unittest.skipUnless(GIT, "git 이 없는 환경 / git is not installed")
class GitCase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="ai365-git-"))
        self.addCleanup(_rmtree, self.tmp)
        empty = write(os.path.join(self.tmp, "empty.gitconfig"), "")
        env = patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": empty, "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0"})
        env.start()
        self.addCleanup(env.stop)
        self.root = os.path.join(self.tmp, "작업 폴더")   # 한글 · 공백 경로 / a Korean path with a space
        os.makedirs(self.root)

    def git(self, *args, cwd: str | None = None, check: bool = True) -> str:
        r = subprocess.run([GIT, "-c", "core.safecrlf=false", "-c", "core.quotepath=off", *args], cwd=cwd or self.root,
                           capture_output=True)
        if check and r.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} 실패: {r.stderr.decode('utf-8', 'replace')}")
        return r.stdout.decode("utf-8", "replace")

    def init(self, path: str | None = None) -> str:
        path = path or self.root
        os.makedirs(path, exist_ok=True)
        self.git("init", "-q", "-b", "main", cwd=path)
        return path

    def commit_all(self, message: str = "init", path: str | None = None) -> str:
        self.git("add", "-A", ".", cwd=path)
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", message, cwd=path)
        return self.git("rev-parse", "HEAD", cwd=path).strip()

    def p(self, rel: str) -> str:
        return os.path.join(self.root, *rel.split("/"))

    def index_bytes(self) -> bytes:
        return read(os.path.join(self.root, ".git", "index"))

    def leftover_indexes(self) -> list[str]:
        return glob.glob(os.path.join(self.root, ".git", "ai365-index-*"))


class CheckpointTests(GitCase):
    def setUp(self):
        super().setUp()
        self.init()
        write(self.p("a.txt"), "one\n")
        write(self.p("sub/b.txt"), "two\n")
        write(self.p(".gitignore"), "ignored.log\n*.tmp\n")
        write(self.p("ignored.log"), "keep me\n")
        self.head = self.commit_all()

    def test_snapshot_then_restore_round_trips_the_work_tree_and_keeps_ignored_files_and_the_real_index(self):
        write(self.p("a.txt"), "one changed\n")
        write(self.p("staged.txt"), "staged\n")
        self.git("add", "staged.txt")                                          # 실제 인덱스에 올린 변경 / a real staged change
        write(self.p("new.txt"), "created before snapshot\n")                  # 스냅샷 때의 새 파일 / new at snapshot time
        before = self.index_bytes()
        cp = ag.snapshot(self.root, "ag_test1", "턴 시작 · README 고쳐줘")
        self.assertEqual(self.index_bytes(), before)                           # 실제 인덱스 그대로 / real index untouched
        self.assertEqual(cp["ref"], "refs/ai365/checkpoints/ag_test1/1")
        self.assertEqual(len(cp["commit"]), 40)
        self.assertEqual(cp["label"], "턴 시작 · README 고쳐줘")
        self.assertEqual(cp["files"], 5)                                       # .gitignore a.txt new.txt staged.txt sub/b.txt
        self.assertEqual(self.git("rev-parse", cp["ref"]).strip(), cp["commit"])
        self.assertEqual(self.git("rev-parse", cp["commit"] + "^{tree}").strip(), cp["tree"])
        body = self.git("cat-file", "-p", cp["commit"])
        self.assertIn("parent " + self.head, body)
        self.assertIn("ai365 checkpoint: 턴 시작 · README 고쳐줘", body)
        self.assertEqual(self.git("show", cp["commit"] + ":a.txt"), "one changed\n")
        self.assertEqual(self.git("show", cp["commit"] + ":new.txt"), "created before snapshot\n")
        self.assertNotIn("ignored.log", self.git("ls-tree", "-r", "--name-only", cp["commit"]))
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.head)    # HEAD · 브랜치 그대로 / HEAD and branch kept
        self.assertEqual(self.git("symbolic-ref", "--short", "HEAD").strip(), "main")
        self.assertEqual(self.git("diff", "--cached", "--name-only").split(), ["staged.txt"])

        write(self.p("a.txt"), "broken\n")
        os.remove(self.p("new.txt"))
        write(self.p("later.txt"), "after snapshot\n")                         # 스냅샷 뒤 새 파일 / created after the snapshot
        write(self.p("sub/later/deep.txt"), "deep\n")
        write(self.p("ignored.log"), "ignored changed\n")
        write(self.p("cache.tmp"), "temp\n")
        before = self.index_bytes()
        r = ag.restore(self.root, cp["commit"])
        self.assertEqual(self.index_bytes(), before)
        self.assertEqual(r, {"commit": cp["commit"], "files": 4})              # a.txt new.txt later.txt sub/later/deep.txt
        self.assertEqual(read(self.p("a.txt")), b"one changed\n")              # 고친 파일 복원 / modified file restored
        self.assertEqual(read(self.p("new.txt")), b"created before snapshot\n")  # 지운 새 파일 복원 / deleted new file back
        self.assertFalse(os.path.exists(self.p("later.txt")))                  # 스냅샷 뒤 파일 삭제 / later file removed
        self.assertFalse(os.path.exists(self.p("sub/later/deep.txt")))
        self.assertEqual(read(self.p("ignored.log")), b"ignored changed\n")    # 무시 파일 그대로 / ignored files untouched
        self.assertEqual(read(self.p("cache.tmp")), b"temp\n")
        self.assertEqual(read(self.p("sub/b.txt")), b"two\n")
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.head)
        self.assertEqual(self.git("diff", "--cached", "--name-only").split(), ["staged.txt"])
        self.assertEqual(self.leftover_indexes(), [])                          # 임시 인덱스는 지운다 / temp indexes removed

    def test_numbers_grow_per_session_same_tree_still_makes_a_new_commit_and_refs_can_be_dropped(self):
        a1 = ag.snapshot(self.root, "ag_a")
        a2 = ag.snapshot(self.root, "ag_a", "둘째")
        b1 = ag.snapshot(self.root, "ag_b")
        self.assertEqual([a1["ref"], a2["ref"], b1["ref"]], ["refs/ai365/checkpoints/ag_a/1", "refs/ai365/checkpoints/ag_a/2",
                                                             "refs/ai365/checkpoints/ag_b/1"])
        self.assertEqual(a1["tree"], a2["tree"])                               # 같은 tree / the same tree
        self.assertNotEqual(a1["commit"], a2["commit"])                        # 그래도 새 커밋 / still a new commit
        self.assertIn("ai365 checkpoint\n", self.git("cat-file", "-p", a1["commit"]))   # 이름 없음 / no label
        self.assertEqual(ag.list_refs(self.root, "ag_a"), [a1["ref"], a2["ref"]])
        ag.drop_ref(self.root, a1["ref"])
        self.assertEqual(ag.list_refs(self.root, "ag_a"), [a2["ref"]])
        self.assertEqual(ag.snapshot(self.root, "ag_a")["ref"], "refs/ai365/checkpoints/ag_a/3")   # 최대 + 1 / max + 1
        ag.drop_ref(self.root, a1["ref"])                                      # 없는 ref 도 조용히 / a missing ref is fine
        with self.assertRaises(ag.GitError):
            ag.drop_ref(self.root, "refs/heads/main")                          # 체크포인트 밖은 못 지운다 / never a branch
        self.assertEqual(self.git("rev-parse", "main").strip(), self.head)
        self.assertEqual(ag.drop_refs(self.root, "ag_a"), 2)
        self.assertEqual(ag.list_refs(self.root, "ag_a"), [])
        self.assertEqual(ag.list_refs(self.root, "ag_b"), [b1["ref"]])
        self.assertEqual(ag.drop_refs(self.root, "ag_a"), 0)
        for bad in ("../evil", "a/b", "", "x" * 65):
            with self.assertRaises(ag.GitError):
                ag.snapshot(self.root, bad)
        self.assertEqual(ag.list_refs(self.root, "../evil"), [])

    def test_restore_refuses_bad_or_unknown_commits(self):
        for bad in ("", "-rf", "abc def", "deadbeefdeadbeef"):
            with self.assertRaises(ag.GitError):
                ag.restore(self.root, bad)
        self.assertEqual(self.leftover_indexes(), [])

    def test_info_and_is_repo(self):
        self.assertTrue(ag.is_repo(self.root))
        self.assertEqual(ag.info(self.root), {"repo": True, "branch": "main", "head": self.head[:7]})
        self.git("checkout", "-q", "--detach")
        self.assertEqual(ag.info(self.root)["branch"], None)                   # 분리된 HEAD / detached


class NoHeadTests(GitCase):
    def test_a_repository_without_commits_snapshots_restores_lists_and_commits(self):
        self.init()
        write(self.p("a.txt"), "first\nsecond\n")
        write(self.p("bin/b.bin"), data=b"\x00\x01\x02binary")
        self.assertTrue(ag.is_repo(self.root))
        self.assertEqual(ag.info(self.root), {"repo": True, "branch": "main", "head": ""})
        st = ag.status(self.root)
        self.assertEqual([(f["path"], f["status"], f["added"], f["binary"]) for f in st["files"]],
                         [("a.txt", "?", 2, False), ("bin/b.bin", "?", 0, True)])
        self.git("add", "a.txt")
        st = ag.status(self.root)
        self.assertEqual([(f["path"], f["status"], f["added"]) for f in st["files"]], [("a.txt", "A", 2), ("bin/b.bin", "?", 0)])
        self.assertEqual((st["added"], st["removed"], st["count"]), (2, 0, 2))
        d = ag.diff(self.root, "a.txt")
        self.assertEqual((d["status"], d["binary"]), ("A", False))
        self.assertIn("+first\n+second\n", d["unified"])

        cp = ag.snapshot(self.root, "ag_nohead", "처음")
        self.assertEqual(cp["files"], 2)
        self.assertEqual(self.git("rev-list", "--parents", "-n", "1", cp["commit"]).split(), [cp["commit"]])   # 부모 없음 / no parent
        write(self.p("a.txt"), "changed\n")
        write(self.p("c.txt"), "later\n")
        self.assertEqual(ag.restore(self.root, cp["commit"])["files"], 2)
        self.assertEqual(read(self.p("a.txt")), b"first\nsecond\n")
        self.assertFalse(os.path.exists(self.p("c.txt")))
        self.assertEqual(self.git("rev-parse", "--verify", "-q", "HEAD", check=False).strip(), "")   # 여전히 커밋 없음 / still no commit

        r = ag.commit(self.root, "첫 커밋 / First commit")
        self.assertEqual(r["files"], 2)
        self.assertEqual(self.git("rev-parse", "HEAD").strip()[:7], r["commit"])


class StatusDiffTests(GitCase):
    def setUp(self):
        super().setUp()
        self.init()
        write(self.p("a.txt"), "1\n2\n3\n4\n5\n")
        write(self.p("b.txt"), "x\ny\n")
        write(self.p("d.txt"), "del\n")
        write(self.p("img.bin"), data=b"\x89PNG\x00\x00old")
        write(self.p(".gitignore"), "*.log\n")
        self.head = self.commit_all()
        write(self.p("a.txt"), "1\n2\nthree\n4\n5\n6\n")                       # +2 -1
        os.remove(self.p("d.txt"))                                             # -1
        self.git("mv", "b.txt", "moved.txt")                                   # 이름 바꿈 / rename
        write(self.p("img.bin"), data=b"\x89PNG\x00\x00new!")                   # 이진 변경 / binary change
        write(self.p("새 폴더/메모 파일.txt"), "첫 줄\n둘째 줄\n셋째")          # 추적 안 됨 · 끝 줄바꿈 없음 / untracked, no final newline
        write(self.p("new.bin"), data=b"\x00\x00\x00")
        write(self.p("debug.log"), "ignored\n")

    def test_status_lists_changes_against_head_with_untracked_lines_and_binaries(self):
        st = ag.status(self.root)
        self.assertEqual((st["repo"], st["branch"], st["truncated"]), (True, "main", False))
        self.assertEqual([(f["path"], f["status"], f["added"], f["removed"], f["binary"]) for f in st["files"]],
                         [("a.txt", "M", 2, 1, False), ("d.txt", "D", 0, 1, False), ("img.bin", "M", 0, 0, True),
                          ("moved.txt", "R", 0, 0, False), ("new.bin", "?", 0, 0, True),
                          ("새 폴더/메모 파일.txt", "?", 3, 0, False)])
        self.assertEqual((st["added"], st["removed"], st["count"]), (5, 2, 6))
        with patch.object(ag, "MAX_STATUS_FILES", 2):
            st = ag.status(self.root)
        self.assertEqual((len(st["files"]), st["count"], st["truncated"]), (2, 6, True))

    def test_diff_covers_tracked_untracked_binary_renamed_deleted_and_unchanged_files(self):
        d = ag.diff(self.root, "a.txt")
        self.assertEqual((d["path"], d["status"], d["binary"], d["truncated"]), ("a.txt", "M", False, False))
        self.assertIn("--- a/a.txt\n+++ b/a.txt\n", d["unified"])
        self.assertIn("-3\n+three\n", d["unified"])
        self.assertIn("+6\n", d["unified"])
        d = ag.diff(self.root, "새 폴더\\메모 파일.txt")                          # 역슬래시도 받는다 / backslashes accepted
        self.assertEqual((d["path"], d["status"], d["binary"]), ("새 폴더/메모 파일.txt", "?", False))
        self.assertEqual(d["unified"], "diff --git a/새 폴더/메모 파일.txt b/새 폴더/메모 파일.txt\nnew file mode 100644\n"
                                       "--- /dev/null\n+++ b/새 폴더/메모 파일.txt\n@@ -0,0 +1,3 @@\n"
                                       "+첫 줄\n+둘째 줄\n+셋째\n\\ No newline at end of file\n")
        for path in ("new.bin", "img.bin"):
            d = ag.diff(self.root, path)
            self.assertEqual((d["binary"], d["unified"]), (True, ""), path)
        d = ag.diff(self.root, "moved.txt")
        self.assertEqual(d["status"], "R")
        self.assertIn("rename from b.txt\nrename to moved.txt", d["unified"])
        d = ag.diff(self.root, "d.txt")
        self.assertEqual(d["status"], "D")
        self.assertIn("-del\n", d["unified"])
        self.assertEqual(ag.diff(self.root, "debug.log"),                      # 무시 파일 = 바뀐 것 없음 / ignored = unchanged
                         {"path": "debug.log", "status": "", "unified": "", "binary": False, "truncated": False})
        self.assertEqual(ag.diff(self.root, os.path.join(self.root, "a.txt"))["path"], "a.txt")   # 절대 경로 / absolute path
        d = ag.diff(self.root, "a.txt", max_chars=60)
        self.assertTrue(d["truncated"])
        self.assertLessEqual(len(d["unified"]), 60)
        self.assertTrue(d["unified"].endswith("\n"))                           # 줄 경계에서 / at a line boundary
        outside = write(os.path.join(self.tmp, "outside.txt"), "x\n")
        for bad in ("../outside.txt", outside, "", "a\x00b"):
            with self.assertRaises(ag.GitError):
                ag.diff(self.root, bad)


class CommitTests(GitCase):
    def setUp(self):
        super().setUp()
        self.init()
        write(self.p("README.md"), "# 데모\nteh demo\n")
        self.head = self.commit_all()

    def test_commit_stages_everything_falls_back_to_the_agentic_identity_and_refuses_nothing_to_commit(self):
        write(self.p("README.md"), "# 데모\nthe demo\n")
        write(self.p("docs/new.md"), "새 문서\n")
        r = ag.commit(self.root, "  README 정리 / Tidy README  ")
        head = self.git("rev-parse", "HEAD").strip()
        self.assertEqual(r, {"commit": head[:7], "files": 2})
        self.assertEqual(self.git("log", "-1", "--format=%an|%ae|%s").strip(),
                         "Ai365 Agentic|agentic@ai365.local|README 정리 / Tidy README")
        self.assertEqual(self.git("rev-parse", "HEAD~1").strip(), self.head)
        self.assertEqual(ag.status(self.root)["count"], 0)
        with self.assertRaises(ag.GitError) as cm:
            ag.commit(self.root, "또 / Again")
        self.assertIn("커밋할 변경이 없습니다", str(cm.exception))
        with self.assertRaises(ag.GitError) as cm:
            ag.commit(self.root, "   ")
        self.assertIn("비어 있습니다", str(cm.exception))

    def test_commit_uses_the_configured_identity_when_there_is_one(self):
        self.git("config", "user.name", "김개발")
        self.git("config", "user.email", "dev@example.invalid")
        write(self.p("README.md"), "# 데모\nchanged\n")
        ag.commit(self.root, "수정 / Change")
        self.assertEqual(self.git("log", "-1", "--format=%an|%ae").strip(), "김개발|dev@example.invalid")

    def test_suggest_message_calls_the_lite_model_once_and_falls_back_to_the_rule_sentence(self):
        write(self.p("README.md"), "# 데모\nthe demo\n")
        write(self.p("notes.txt"), "메모\n")
        with patch("app.llm.generate", return_value="README 오타 수정 / Fix README typo") as gen:
            r = ag.suggest_message(self.root)
        self.assertEqual(r, {"message": "README 오타 수정 / Fix README typo", "files": 2})
        self.assertEqual(gen.call_count, 1)
        self.assertEqual(gen.call_args.kwargs["tier"], "lite")
        prompt = gen.call_args.args[0]
        self.assertIn("[변경 파일 2개]", prompt)
        self.assertIn("M README.md (+1 -1)", prompt)
        self.assertIn("? notes.txt (+1 -0)", prompt)
        self.assertIn("+the demo", prompt)
        with patch("app.llm.generate", return_value="```\n커밋 메시지: `문서 정리 — 오타 / Tidy docs`\n```"):
            self.assertEqual(ag.suggest_message(self.root)["message"], "문서 정리 - 오타 / Tidy docs")   # 줄표 금지 / no em dash
        for answer in ("Fix typo", "오타 수정", "", None):
            with patch("app.llm.generate", return_value=answer):
                self.assertEqual(ag.suggest_message(self.root)["message"], "파일 2개 변경 / 2 files changed", answer)
        with patch("app.llm.generate", side_effect=RuntimeError("503")), self.assertLogs("ai365.agentic", "WARNING"):
            self.assertEqual(ag.suggest_message(self.root), {"message": "파일 2개 변경 / 2 files changed", "files": 2})
        os.remove(self.p("notes.txt"))
        with patch("app.llm.generate", side_effect=RuntimeError("down")), self.assertLogs("ai365.agentic", "WARNING"):
            self.assertEqual(ag.suggest_message(self.root)["message"], "파일 1개 변경 / 1 file changed")
        self.git("checkout", "--", "README.md")
        with patch("app.llm.generate") as gen:
            self.assertEqual(ag.suggest_message(self.root), {"message": "", "files": 0})
        gen.assert_not_called()                                                # 바뀐 것이 없으면 부르지 않는다 / no call


class NotARepoTests(GitCase):
    def test_plain_folders_subfolders_and_a_missing_git_are_not_repositories(self):
        plain = self.root
        write(os.path.join(plain, "a.txt"), "x\n")
        self.assertFalse(ag.is_repo(plain))
        self.assertEqual(ag.info(plain), {"repo": False, "branch": None, "head": ""})
        self.assertEqual(ag.status(plain), {"repo": False, "branch": None, "files": [], "added": 0, "removed": 0,
                                            "count": 0, "truncated": False})
        for call in (lambda: ag.snapshot(plain, "ag_x"), lambda: ag.restore(plain, "HEAD"), lambda: ag.diff(plain, "a.txt"),
                     lambda: ag.commit(plain, "x / x"), lambda: ag.suggest_message(plain)):
            with self.assertRaises(ag.GitError):
                call()
        self.assertEqual((ag.list_refs(plain, "ag_x"), ag.drop_refs(plain, "ag_x")), ([], 0))
        self.assertIsNone(ag.drop_ref(plain, "refs/ai365/checkpoints/ag_x/1"))
        # 부모 저장소 안의 하위 폴더 · 빈 .git 폴더는 저장소가 아니다(부모를 건드리지 않는다) / never act on a parent repository
        parent = self.init(os.path.join(self.tmp, "parent"))
        write(os.path.join(parent, "p.txt"), "p\n")
        self.commit_all(path=parent)
        child = os.path.join(parent, "child")
        os.makedirs(os.path.join(child, ".git"))
        write(os.path.join(child, "c.txt"), "c\n")
        self.assertFalse(ag.is_repo(child))
        self.assertFalse(ag.is_repo(os.path.join(parent, "nowhere")))
        with self.assertRaises(ag.GitError):
            ag.snapshot(child, "ag_x")
        self.assertEqual(self.git("for-each-ref", "refs/ai365", cwd=parent), "")
        # git 이 없으면 / without git
        self.assertTrue(ag.is_repo(parent))
        with patch.object(ag.shutil, "which", return_value=None):
            self.assertFalse(ag.is_repo(parent))
            with self.assertRaises(ag.GitError) as cm:
                ag.snapshot(parent, "ag_x")
            self.assertIn("git 을 찾을 수 없습니다", str(cm.exception))


class SafetyCase(GitCase):
    def names(self, treeish: str) -> list[str]:
        return [n for n in self.git("ls-tree", "-r", "-z", "--name-only", treeish).split("\0") if n]


class IgnoreRulesTests(SafetyCase):
    """H1: 되돌리기는 체크포인트 시점의 무시 규칙으로 돈다 / restore runs with the checkpoint's ignore rules"""

    def test_files_ignored_at_snapshot_time_survive_a_later_gitignore_change(self):
        self.init()
        write(self.p(".gitignore"), ".env\nnode_modules/\n")
        write(self.p("a.txt"), "one\n")
        self.commit_all()
        write(self.p(".env"), "TOKEN=placeholder\n")
        write(self.p("node_modules/x/index.js"), "x\n")
        cp = ag.snapshot(self.root, "ag_h1")
        self.assertEqual(sorted(self.names(cp["commit"])), [".gitignore", "a.txt"])
        write(self.p(".gitignore"), "*.log\n")                                  # 턴 안에서 규칙이 바뀌었다 / rules rewritten
        write(self.p("a.txt"), "changed\n")
        write(self.p("sub/.gitignore"), "*.txt\n")                              # 스냅샷 뒤 새 규칙 파일 / a new rules file
        write(self.p("sub/late.txt"), "late\n")                                 # 그 규칙에 숨은 새 파일 / hidden by it
        r = ag.restore(self.root, cp["commit"])
        self.assertEqual(read(self.p(".env")), b"TOKEN=placeholder\n")          # 무시되던 파일은 남는다 / survives
        self.assertEqual(read(self.p("node_modules/x/index.js")), b"x\n")
        self.assertEqual(read(self.p(".gitignore")), b".env\nnode_modules/\n")  # 규칙도 체크포인트 것 / the checkpoint's rules
        self.assertEqual(read(self.p("a.txt")), b"one\n")
        self.assertFalse(os.path.exists(self.p("sub/.gitignore")))             # 스냅샷 뒤 생긴 것은 지운다 / created later
        self.assertFalse(os.path.exists(self.p("sub/late.txt")))
        self.assertGreaterEqual(r["files"], 2)
        self.assertEqual(self.leftover_indexes(), [])


class LockedFileTests(SafetyCase):
    """M3: 다른 프로그램이 연 파일이 있으면 아무것도 바꾸지 않고 거절 / a file held open refuses the restore unchanged"""

    @unittest.skipUnless(os.name == "nt", "열린 파일을 지울 수 없는 것은 Windows 만 / only Windows blocks deleting open files")
    def test_an_open_file_refuses_the_restore_and_the_pre_written_gitignore_is_put_back(self):
        self.init()
        for n in ("a", "b", "c"):
            write(self.p(n + ".txt"), n + "1\n")
        write(self.p(".gitignore"), ".env\n")
        self.commit_all()
        cp = ag.snapshot(self.root, "ag_m3")
        for n in ("a", "b", "c"):
            write(self.p(n + ".txt"), n + "2\n")
        write(self.p(".gitignore"), "*.log\n")
        write(self.p(".env"), "TOKEN=placeholder\n")
        fh = open(self.p("b.txt"), "rb")                                          # 삭제 공유 없이 연다 / no FILE_SHARE_DELETE
        try:
            with self.assertRaises(ag.GitError) as cm:
                ag.restore(self.root, cp["commit"])
        finally:
            fh.close()
        self.assertIn("다른 프로그램이 열어 둔 파일", str(cm.exception))
        self.assertIn("b.txt", str(cm.exception))
        for n in ("a", "b", "c"):
            self.assertEqual(read(self.p(n + ".txt")), (n + "2\n").encode())   # 아무것도 안 바뀜 / nothing changed
        self.assertEqual(read(self.p(".gitignore")), b"*.log\n")                # 먼저 써 둔 규칙은 원래대로 / put back
        self.assertTrue(os.path.exists(self.p(".env")))
        self.assertEqual(self.leftover_indexes(), [])
        ag.restore(self.root, cp["commit"])                                      # 닫은 뒤에는 된다 / works once closed
        self.assertEqual([read(self.p(n + ".txt")) for n in ("a", "b", "c")], [b"a1\n", b"b1\n", b"c1\n"])
        self.assertEqual(read(self.p(".env")), b"TOKEN=placeholder\n")

    def test_a_failure_inside_read_tree_says_the_restore_may_be_partial(self):
        self.init()
        write(self.p("a.txt"), "one\n")
        self.commit_all()
        cp = ag.snapshot(self.root, "ag_m3b")
        write(self.p("a.txt"), "two\n")
        real = ag._run

        def fake(folder, args, **kw):
            if list(args[:2]) == ["read-tree", "-u"]:
                raise ag.GitError("git read-tree 실패: unable to create file a.txt")
            return real(folder, args, **kw)
        with patch.object(ag, "_run", side_effect=fake), self.assertRaises(ag.GitError) as cm:
            ag.restore(self.root, cp["commit"])
        self.assertIn("일부만 되돌렸을 수 있습니다", str(cm.exception))
        self.assertIn("되돌리기 전 자동 저장", str(cm.exception))
        self.assertEqual(self.leftover_indexes(), [])


class LinkTests(SafetyCase):
    """H3: 저장소 밖을 가리키는 정션 · 링크 / junctions and links pointing outside the repository"""

    def test_a_junction_made_after_the_snapshot_is_left_alone_and_never_enters_a_tree(self):
        outside = os.path.join(self.tmp, "shared_vendor")
        write(os.path.join(outside, "lib.js"), "outside file\n")
        write(os.path.join(outside, "deep", "x.js"), "outside deep\n")
        self.init()
        write(self.p("a.txt"), "one\n")
        self.commit_all()
        cp = ag.snapshot(self.root, "ag_h3")
        if not link_dir(outside, self.p("vendor")):
            self.skipTest("정션 · 심볼릭 링크를 만들 수 없는 환경 / cannot create a junction or symlink here")
        cp2 = ag.snapshot(self.root, "ag_h3")
        self.assertEqual(self.names(cp2["commit"]), ["a.txt"])                  # 정션 안은 트리에 없다 / nothing below it
        write(self.p("a.txt"), "changed\n")
        ag.restore(self.root, cp["commit"])
        self.assertEqual(read(self.p("a.txt")), b"one\n")
        self.assertEqual(read(os.path.join(outside, "lib.js")), b"outside file\n")   # 밖의 파일은 그대로 / outside intact
        self.assertEqual(read(os.path.join(outside, "deep", "x.js")), b"outside deep\n")
        self.assertTrue(os.path.isdir(self.p("vendor")))                         # 정션도 그대로 / the junction stays

    def test_a_restore_that_would_write_through_a_junction_is_refused_without_changes(self):
        self.init()
        write(self.p("docs/spec.md"), "v1\n")
        write(self.p("a.txt"), "one\n")
        self.commit_all()
        cp = ag.snapshot(self.root, "ag_h3b")                                  # docs 는 진짜 폴더였다 / docs was a real folder
        outside = os.path.join(self.tmp, "shared_docs")
        write(os.path.join(outside, "spec.md"), "outside v2\n")
        _rmtree(self.p("docs"))
        if not link_dir(outside, self.p("docs")):
            self.skipTest("정션 · 심볼릭 링크를 만들 수 없는 환경 / cannot create a junction or symlink here")
        write(self.p("a.txt"), "changed\n")
        with self.assertRaises(ag.GitError) as cm:
            ag.restore(self.root, cp["commit"])
        self.assertIn("저장소 밖을 가리키는 링크", str(cm.exception))
        self.assertIn("docs/spec.md", str(cm.exception))
        self.assertEqual(read(os.path.join(outside, "spec.md")), b"outside v2\n")   # 밖은 그대로 / outside untouched
        self.assertEqual(read(self.p("a.txt")), b"changed\n")                    # 안도 그대로 / nothing changed inside
        self.assertEqual(self.leftover_indexes(), [])


class SubmoduleTests(SafetyCase):
    """H2: submodule.recurse=true 여도 서브모듈 HEAD · 작업 파일을 건드리지 않는다 / submodules are never touched"""

    def test_restore_leaves_a_submodule_alone_even_with_recurse_on(self):
        lib = self.init(os.path.join(self.tmp, "libsrc"))
        write(os.path.join(lib, "l.txt"), "v1\n")
        self.commit_all(path=lib)
        self.init()
        write(self.p("a.txt"), "one\n")
        self.commit_all()
        self.git("-c", "protocol.file.allow=always", "submodule", "add", "-q", lib.replace("\\", "/"), "lib")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "add sub")
        self.git("config", "submodule.recurse", "true")
        sub = self.p("lib")
        cp = ag.snapshot(self.root, "ag_h2")
        write(os.path.join(sub, "l.txt"), "v2\n")
        self.commit_all("sub work", path=sub)
        moved = self.git("rev-parse", "HEAD", cwd=sub).strip()
        branch = self.git("symbolic-ref", "-q", "--short", "HEAD", cwd=sub, check=False).strip()
        write(os.path.join(sub, "l.txt"), "v2 + 커밋 안 한 수정\n")             # 커밋 안 한 수정 / an uncommitted edit
        write(self.p("a.txt"), "changed\n")
        ag.restore(self.root, cp["commit"])
        self.assertEqual(read(self.p("a.txt")), b"one\n")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=sub).strip(), moved)            # HEAD 그대로 / HEAD kept
        self.assertEqual(self.git("symbolic-ref", "-q", "--short", "HEAD", cwd=sub, check=False).strip(), branch)
        self.assertEqual(read(os.path.join(sub, "l.txt")), "v2 + 커밋 안 한 수정\n".encode("utf-8"))   # 수정도 그대로 / kept


class BytesAndSkipsTests(SafetyCase):
    def test_line_endings_round_trip_byte_for_byte_under_autocrlf(self):
        """L1: 스냅샷 · 되돌리기 안은 core.autocrlf=false / snapshot and restore bypass autocrlf"""
        self.init()
        self.git("config", "core.autocrlf", "true")
        write(self.p("lf.txt"), "one\ntwo\n")
        write(self.p("a.txt"), "a\n")
        self.commit_all()
        write(self.p("new_lf.py"), "print(1)\nprint(2)\n")
        write(self.p("new_crlf.txt"), "w1\r\nw2\r\n")
        cp = ag.snapshot(self.root, "ag_l1")
        for rel in ("lf.txt", "new_lf.py", "new_crlf.txt"):
            write(self.p(rel), "broken\n")
        ag.restore(self.root, cp["commit"])
        self.assertEqual(read(self.p("lf.txt")), b"one\ntwo\n")
        self.assertEqual(read(self.p("new_lf.py")), b"print(1)\nprint(2)\n")
        self.assertEqual(read(self.p("new_crlf.txt")), b"w1\r\nw2\r\n")

    def test_unreadable_paths_are_skipped_instead_of_breaking_the_snapshot(self):
        """M4: 커밋 없는 안쪽 저장소 · 잠긴 파일 하나가 스냅샷을 깨지 않는다 / one bad path never breaks a snapshot"""
        self.init()
        write(self.p("a.txt"), "one\n")
        self.commit_all()
        os.makedirs(self.p("scratch"))
        self.git("init", "-q", cwd=self.p("scratch"))                         # 커밋 없는 안쪽 저장소 / no commit inside
        write(self.p("scratch/x.txt"), "x\n")
        locked = None
        if os.name == "nt":
            import msvcrt
            write(self.p("app.db"), "x" * 4096)
            locked = open(self.p("app.db"), "r+b")
            msvcrt.locking(locked.fileno(), msvcrt.LK_NBLCK, 4096)              # SQLite 같은 바이트 잠금 / like SQLite
        try:
            with self.assertLogs("ai365.agentic", "WARNING"):
                cp = ag.snapshot(self.root, "ag_m4")
        finally:
            if locked is not None:
                import msvcrt
                locked.seek(0)
                msvcrt.locking(locked.fileno(), msvcrt.LK_UNLCK, 4096)
                locked.close()
        names = self.names(cp["commit"])
        self.assertIn("a.txt", names)
        self.assertNotIn("app.db", names)
        self.assertFalse([n for n in names if n.startswith("scratch")])
        self.assertEqual(self.leftover_indexes(), [])

    def test_the_servers_secrets_file_never_enters_a_checkpoint_and_is_never_overwritten(self):
        self.init()
        write(self.p("a.txt"), "one\n")
        self.commit_all()
        env = write(self.p(".env"), "TOKEN=placeholder\n")                     # 무시 규칙 없음 / not ignored
        old = ag.snapshot(self.root, "ag_env")                                  # 보호 전 체크포인트 / before protection
        self.assertIn(".env", self.names(old["commit"]))
        with patch.object(ax, "PROTECTED_FILES", {os.path.normcase(os.path.realpath(env))}):
            cp = ag.snapshot(self.root, "ag_env")
            self.assertNotIn(".env", self.names(cp["commit"]))
            write(env, "TOKEN=changed\n")
            write(self.p("a.txt"), "changed\n")
            ag.restore(self.root, cp["commit"])
            self.assertEqual((read(env), read(self.p("a.txt"))), (b"TOKEN=changed\n", b"one\n"))   # .env 그대로 / untouched
            write(self.p("a.txt"), "again\n")
            with self.assertRaises(ag.GitError) as cm:                         # 예전 체크포인트에는 있다 / an old one has it
                ag.restore(self.root, old["commit"])
            self.assertIn("비밀 설정 파일", str(cm.exception))
            self.assertEqual((read(env), read(self.p("a.txt"))), (b"TOKEN=changed\n", b"again\n"))


class SmallFixesTests(SafetyCase):
    def test_intent_to_add_counts_as_added(self):
        """L4: porcelain ' A'(git add -N) = A / intent to add is 'A'"""
        self.init()
        write(self.p("a.txt"), "one\n")
        self.commit_all()
        write(self.p("new.txt"), "n1\nn2\n")
        self.git("add", "-N", "new.txt")
        st = ag.status(self.root)
        self.assertEqual([(f["path"], f["status"], f["added"], f["removed"]) for f in st["files"]], [("new.txt", "A", 2, 0)])
        d = ag.diff(self.root, "new.txt")
        self.assertEqual(d["status"], "A")
        self.assertIn("+n1\n+n2\n", d["unified"])

    def test_stale_temp_indexes_are_swept_but_fresh_ones_stay(self):
        """L5: 한 시간 넘은 임시 인덱스만 지운다 / only temp indexes older than an hour are removed"""
        self.init()
        write(self.p("a.txt"), "one\n")
        self.commit_all()
        old = write(self.p(".git/ai365-index-999-1"), "stale")
        fresh = write(self.p(".git/ai365-index-999-2"), "busy")
        t = time.time() - 7200
        os.utime(old, (t, t))
        ag.snapshot(self.root, "ag_l5")
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh))

    def test_restore_refuses_a_caret_and_verifies_the_object_type(self):
        """L3: 인자에 '^' 를 쓰지 않는다 / no '^' in arguments"""
        self.init()
        write(self.p("a.txt"), "one\n")
        head = self.commit_all()
        for bad in ("HEAD^", head + "^{commit}"):
            with self.assertRaises(ag.GitError):
                ag.restore(self.root, bad)
        tree = self.git("rev-parse", head + "^{tree}").strip()
        with self.assertRaises(ag.GitError) as cm:
            ag.restore(self.root, tree)                                          # 트리는 커밋이 아니다 / a tree is not a commit
        self.assertIn("커밋이 아닙니다", str(cm.exception))

    @unittest.skipUnless(os.name == "nt", "git.bat 껍데기는 Windows 만 / the git.bat shim is Windows only")
    def test_a_bat_shim_for_git_still_works(self):
        """L3: git 이 .bat 껍데기여도 HEAD 를 읽고 체크포인트를 왕복한다 / a .bat shim still round-trips"""
        self.init()
        write(self.p("a.txt"), "one\n")
        head = self.commit_all()
        bindir = tempfile.mkdtemp(prefix="ai365-shim-")   # TEMP 그대로(짧은 이름) / TEMP as is, usually the short 8.3 path
        self.addCleanup(_rmtree, bindir)
        shim = write(os.path.join(bindir, "git.bat"), f'@"{GIT}" %*\r\n')
        if " " not in shim and any(c in shim for c in "()&^%!"):   # 따옴표 없는 괄호 경로는 cmd 가 못 연다 / cmd limitation
            self.skipTest("cmd 가 따옴표 없는 괄호 경로를 열지 못한다 / cmd cannot start an unquoted path with parentheses")
        with patch.object(ag, "_git_exe", return_value=shim):
            self.assertEqual(ag.info(self.root)["head"], head[:7])
            cp = ag.snapshot(self.root, "ag_shim")
            write(self.p("a.txt"), "changed\n")
            ag.restore(self.root, cp["commit"])
            self.assertEqual(read(self.p("a.txt")), b"one\n")
            self.assertEqual(ag.list_refs(self.root, "ag_shim"), [cp["ref"]])


class TimeoutTests(SafetyCase):
    def test_a_hanging_commit_hook_returns_within_the_limit_and_leaves_no_index_lock(self):
        """M2: 시간 제한을 넘기면 git 프로세스 트리째 끝낸다 / the whole process tree is killed past the limit"""
        self.init()
        write(self.p("a.txt"), "one\n")
        self.commit_all()
        hook = self.p(".git/hooks/pre-commit")
        with open(hook, "w", encoding="utf-8", newline="\n") as f:
            f.write("#!/bin/sh\nsleep 30\nexit 1\n")
        write(self.p("a.txt"), "two\n")
        t0 = time.monotonic()
        with patch.object(ag, "LONG_TIMEOUT", 2), self.assertRaises(ag.GitTimeout) as cm:
            ag.commit(self.root, "수정 / Change")
        self.assertLess(time.monotonic() - t0, 15)
        self.assertIsInstance(cm.exception, ag.GitError)
        self.assertIn("2초", str(cm.exception))
        self.assertFalse(os.path.exists(self.p(".git/index.lock")))               # 남은 잠금 없음 / no stale lock
        self.git("status", "--porcelain")                                        # git 이 계속 된다 / git still works


if __name__ == "__main__":
    unittest.main()
