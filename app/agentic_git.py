"""Agentic 모드 git(2026-10-19, 2차): 체크포인트 · 되돌리기 · 변경 목록 · diff · 커밋 · 커밋 메시지 제안.

- 체크포인트 = 임시 인덱스(GIT_INDEX_FILE=<git 폴더>/ai365-index-<pid>-<n>, 끝나면 지운다. 1시간 넘게 남은 것은 다음 스냅샷이
  지운다)에 read-tree HEAD(HEAD 가 없으면 --empty) → add -A --ignore-errors .(읽을 수 없는 파일 하나가 전체를 깨지 않게, 건너뛴
  파일은 로그) → 저장소 밖을 가리키는 링크(정션 · 심볼릭 링크) 아래 파일과 이 서버의 비밀 설정 파일(.env)을 인덱스에서 뺀다 →
  write-tree → commit-tree(-p HEAD, 메시지 "ai365 checkpoint: <이름>") → update-ref refs/ai365/checkpoints/<세션>/<n>
  (n = 그 세션 ref 의 최대 번호 + 1). 실제 인덱스 · 브랜치 · HEAD 는 그대로다.
- 되돌리기 = 임시 인덱스에 read-tree HEAD → 체크포인트의 .gitignore 를 먼저 작업 트리에 써 두고(트리에 없는데 지금 규칙상 보이는
  .gitignore 는 지운다) → add -A --ignore-errors . → 위와 같이 링크 아래 · 비밀 파일을 뺀다 → 바뀔 경로(diff-index + diff-files)가
  저장소 밖 링크를 지나거나 다른 프로그램이 열어 둔 파일이면 아무것도 바꾸지 않고(써 둔 .gitignore 도 원래대로) 거절 →
  read-tree -u --reset <커밋>. 무시 규칙이 체크포인트 시점 것이라, 스냅샷 때 무시되던 파일(.env · node_modules 등)은 그 뒤
  .gitignore 가 바뀌었어도 지우지 않고, 스냅샷 뒤에 생긴 파일은 지운다. 그래도 read-tree 가 중간에 실패하면 일부만 되돌렸을
  수 있다고 알린다.
- 스냅샷 · 되돌리기 안의 호출은 core.autocrlf=false(바이트 그대로 저장 · 복원), 모든 호출은 submodule.recurse=false 이고
  read-tree 는 --no-recurse-submodules(서브모듈 HEAD · 작업 파일을 건드리지 않는다).
- 변경 목록은 HEAD 대비: 파일 상태 = git status --porcelain=v1 -z(이름의 공백 · 한글 안전), 줄 수 = git diff --numstat HEAD,
  추적 안 된 파일은 줄 수를 더한 줄로 센다(이진 = binary). HEAD 가 없는 저장소는 전부 추가로 센다.
- diff 는 git diff HEAD -- <경로>, 추적 안 된 파일은 파일을 읽어 + 줄로 직접 만든다(Windows 에 /dev/null 이 없다).
- 커밋만 실제 인덱스를 바꾼다(add -A . + commit, 사용자 git 설정 그대로). user.name/email 이 없으면 Ai365 Agentic 신원으로.
- 모든 git 호출: -c core.safecrlf=false -c core.quotepath=off, 창 없음, 자식 환경 = agentic_exec._child_env()(비밀 변수 제외,
  GIT_DIR 같은 저장소 바꾸기 변수도 뺀다), 선택적 잠금 끔(GIT_OPTIONAL_LOCKS=0). 커밋이 아닌 호출은 훅을 돌리지 않는다
  (core.hooksPath=널 장치). 시간 제한을 넘으면 git 의 프로세스 트리째 끝낸다(Windows 에서 훅이 매달려도 제한 안에 돌아온다).
  인자에 '^' 를 쓰지 않는다(git 이 .bat 껍데기일 때 cmd 가 지운다). 함수는 동기(호출부가 스레드에서 부른다).
  git 이 없거나 실패하면 GitError(사람이 읽는 한 줄), 시간 초과는 그 하위 GitTimeout.
"""
# Agentic mode git (2026-10-19, phase 2): checkpoints, restore, change list, diff, commit and commit-message suggestions.
# - A checkpoint uses a temporary index (GIT_INDEX_FILE=<git dir>/ai365-index-<pid>-<n>, removed afterwards; leftovers
#   older than an hour are swept by the next snapshot): read-tree HEAD (--empty without a HEAD) → add -A --ignore-errors .
#   (one unreadable file never breaks the whole snapshot; skipped files are logged) → files below a link (junction or
#   symlink) that points outside the repository and this server's secrets file (.env) are removed from the index →
#   write-tree → commit-tree (-p HEAD, "ai365 checkpoint: <label>") → update-ref refs/ai365/checkpoints/<session>/<n>.
#   The real index, branch and HEAD stay untouched.
# - Restore uses a temporary index too: read-tree HEAD → the checkpoint's .gitignore files are written into the work tree
#   first (and .gitignore files the checkpoint lacks but the current rules would read are removed) → add -A --ignore-errors
#   → the same link and secrets filtering → if any path about to change (diff-index plus diff-files) runs through an
#   outside link or is held open by another program, nothing is changed (the pre-written .gitignore files are put back)
#   and the restore is refused → read-tree -u --reset <commit>. Because the ignore rules are the checkpoint's, files that
#   were ignored at snapshot time (.env, node_modules ...) survive even when .gitignore changed later, while files created
#   after the snapshot are removed. If read-tree still fails midway, the error says the restore may be partial.
# - Calls inside snapshot and restore use core.autocrlf=false (bytes stored and restored as they are); every call uses
#   submodule.recurse=false and read-tree gets --no-recurse-submodules (submodule HEADs and files are never touched).
# - The change list is against HEAD (porcelain v1 -z states, numstat line counts, untracked files count every line as
#   added); diff is git diff HEAD -- <path>, untracked files become + lines read directly.
# - Only commit() touches the real index (add -A . + commit with the user's own git config); a missing identity falls
#   back to Ai365 Agentic <agentic@ai365.local>.
# - Every call: core.safecrlf=false, core.quotepath=off, no window, the child env from agentic_exec._child_env() without
#   repository-redirecting variables, GIT_OPTIONAL_LOCKS=0, hooks off except for commit (core.hooksPath = the null
#   device). A timeout kills git's whole process tree (so a hanging hook returns within the limit on Windows). No '^' in
#   arguments (cmd strips it when git is a .bat shim). Synchronous; failures raise GitError, timeouts GitTimeout.

from __future__ import annotations

import itertools
import logging
import os
import posixpath
import re
import shutil
import subprocess
import threading
import time

from app import llm

logger = logging.getLogger("ai365.agentic")

CHECKPOINT_PREFIX = "refs/ai365/checkpoints/"
GIT_TIMEOUT = 60                       # 보통 호출 / ordinary calls
LONG_TIMEOUT = 120                     # add · read-tree -u · commit
JOIN_SEC = 5.0                         # 끝난 뒤 출력 스레드를 기다리는 시간 / wait for the output threads after exit
STALE_INDEX_SEC = 3600                 # 이보다 오래 남은 임시 인덱스는 지운다 / temp indexes older than this are swept
IGNORE_ROUNDS = 10                     # .gitignore 맞추기 반복 상한 / rounds for aligning .gitignore files
MAX_STATUS_FILES = 2000                # 변경 목록에 싣는 파일 수 상한 / files listed in the change list
COUNT_MAX_BYTES = 20 * 1024 * 1024     # 줄 수를 세는 추적 안 된 파일 크기 상한 / untracked files larger than this count 0 lines
NEW_FILE_MAX_BYTES = 10 * 1024 * 1024  # 추적 안 된 파일 diff 로 읽는 상한 / bytes read for an untracked file's diff
BINARY_SNIFF = 8000                    # git 과 같은 이진 판정 범위 / same binary sniff window as git
SUGGEST_DIFF_CHARS = 20_000            # 메시지 제안에 보내는 diff 앞부분 / diff head sent for a suggestion
SUGGEST_FILES = 100
MESSAGE_MAX = 200
LABEL_MAX = 200
FALLBACK_NAME = "Ai365 Agentic"
FALLBACK_EMAIL = "agentic@ai365.local"
NOT_REPO = "git 저장소가 아닙니다"
LINK_ERR = "저장소 밖을 가리키는 링크(정션)가 있어 되돌릴 수 없습니다: "
LOCKED_ERR = "다른 프로그램이 열어 둔 파일이 있어 되돌릴 수 없습니다: "
PARTIAL_NOTE = "일부만 되돌렸을 수 있습니다. '되돌리기 전 자동 저장' 체크포인트로 돌아갈 수 있습니다"

_SID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_REF_RE = re.compile(r"^refs/ai365/checkpoints/[A-Za-z0-9_-]{1,64}/[0-9]{1,9}$")
_BINARY_RE = re.compile(r"^Binary files .* differ$", re.MULTILINE)
_HANGUL_RE = re.compile(r"[가-힣]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_SEQ = itertools.count(1)
# 자식 git 이 다른 저장소 · 인덱스를 보게 만드는 서버 환경 변수는 뺀다 / server variables that would redirect the child git
_DROP_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
             "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_PREFIX", "GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS",
             "GIT_NOGLOB_PATHSPECS", "GIT_ICASE_PATHSPECS")
_LOCK_ERRORS = (32, 33)   # ERROR_SHARING_VIOLATION · ERROR_LOCK_VIOLATION

SUGGEST_SYSTEM = ("너는 git 커밋 메시지를 쓰는 도우미다. 아래 변경 내용을 보고 커밋 메시지 제목 한 줄만 쓴다. 형식은 "
                  "'한국어 요약 / English summary' 이고(가운데 ' / '), 합쳐 100자 안쪽으로, 마침표 · 따옴표 · 코드 블록 · 설명 "
                  "없이 그 한 줄만 답한다.")


class GitError(Exception):
    """사람이 읽는 한 줄(API 가 422 로 돌려준다) / a human-readable one-liner (the API answers 422)"""


class GitTimeout(GitError):
    """시간 제한을 넘겨 git 프로세스 트리를 끝냈다 / git ran past its time limit and its process tree was killed"""


def _ex():
    """agentic_exec 지연 import(agentic_exec → agentic_store 순환을 import 시점에 만들지 않는다) / lazy import, no cycle"""
    from app import agentic_exec
    return agentic_exec


# ────────────────────────────────────────────────────────
# git 실행 / running git
# ────────────────────────────────────────────────────────

def _git_exe() -> str:
    git = shutil.which("git")
    if not git:
        raise GitError("git 을 찾을 수 없습니다(설치되어 있지 않거나 PATH 에 없습니다)")
    return git


def _env(index: str | None = None, literal: bool = False) -> dict:
    """자식 환경: 비밀 변수 · 저장소 바꾸기 변수 빼기 + 묻지 않기 + 선택적 잠금 끔 (+ 임시 인덱스 · 글자 그대로 경로)
    The child env: no secrets or redirecting variables, no prompts, no optional locks (+ temp index, literal pathspecs)"""
    env = _ex()._child_env()
    for k in _DROP_ENV:
        env.pop(k, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    if index:
        env["GIT_INDEX_FILE"] = index
    if literal:
        env["GIT_LITERAL_PATHSPECS"] = "1"
    return env


def _decode(b: bytes | None) -> str:
    return (b or b"").decode("utf-8", errors="replace")


def _verb(args) -> str:
    """'-c 키=값' 을 건너뛴 git 하위 명령 이름 / the subcommand, skipping '-c key=value' pairs"""
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a == "-c":
            skip = True
            continue
        if not str(a).startswith("-"):
            return str(a)
    return "git"


def _first_line(r: subprocess.CompletedProcess) -> str:
    """실패 출력에서 사람이 읽을 한 줄(fatal · error 줄 먼저, hint · warning 은 뒤로) / the most telling line of a failure"""
    lines = []
    for raw in (r.stderr, r.stdout):
        lines += [ln.strip() for ln in _decode(raw).splitlines() if ln.strip()]
    for ln in lines:
        if re.match(r"^(?:fatal|error):", ln, re.IGNORECASE):
            return re.sub(r"^(?:fatal|error):\s*", "", ln, flags=re.IGNORECASE)[:300]
    for ln in lines:
        if not re.match(r"^(?:hint|warning):", ln, re.IGNORECASE):
            return ln[:300]
    return lines[0][:300] if lines else f"종료 코드 {r.returncode}"


def _drain(stream, buf: bytearray) -> None:
    """파이프를 끝까지 읽어 buf 에 모은다 / read a pipe to its end into buf"""
    try:
        while True:
            chunk = stream.read1(65536)
            if not chunk:
                break
            buf += chunk
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _feed(stream, data: bytes) -> None:
    """stdin 에 쓰고 닫는다(스레드에서: 큰 입력 · 큰 출력이 서로 막지 않게) / write stdin on a thread so pipes never deadlock"""
    try:
        stream.write(data)
        stream.flush()
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except (OSError, ValueError):
            pass


def _run(folder: str, args, *, index: str | None = None, timeout: float = GIT_TIMEOUT, ok=(0,), data: bytes | None = None,
         hooks: bool = False, literal: bool = False, internal: bool = False) -> subprocess.CompletedProcess:
    """git 한 번 실행(Popen + 출력 스레드 + wait). 시간 제한을 넘으면 agentic_exec._kill_tree 로 프로세스 트리째 끝내고 GitTimeout.
    ok=None 이면 종료 코드를 보지 않는다. hooks=False 면 core.hooksPath 를 널 장치로 돌려 훅을 끈다. internal=True(스냅샷 ·
    되돌리기 안) 면 core.autocrlf=false 로 바이트 그대로 다룬다.
    Run git once (Popen, output threads, wait). Past the limit the whole process tree is killed (agentic_exec._kill_tree)
    and GitTimeout raised. ok=None skips the exit-code check; hooks=False points core.hooksPath at the null device;
    internal=True (inside snapshot and restore) adds core.autocrlf=false so bytes pass through unchanged."""
    ex = _ex()
    cmd = [_git_exe(), "-c", "core.safecrlf=false", "-c", "core.quotepath=off", "-c", "submodule.recurse=false"]
    if internal:
        cmd += ["-c", "core.autocrlf=false"]
    if not hooks:
        cmd += ["-c", "core.hooksPath=" + os.devnull]
    cmd += [str(a) for a in args]
    extra = {"creationflags": ex._NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    try:
        proc = subprocess.Popen(cmd, cwd=folder, env=_env(index, literal),
                                stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, **extra)
    except (OSError, ValueError) as e:
        raise GitError(f"git 을 실행하지 못했습니다: {e}") from e
    out, err = bytearray(), bytearray()
    threads = [threading.Thread(target=_drain, args=(proc.stdout, out), daemon=True, name="ai365-git-out"),
               threading.Thread(target=_drain, args=(proc.stderr, err), daemon=True, name="ai365-git-err")]
    if data is not None:
        threads.append(threading.Thread(target=_feed, args=(proc.stdin, data), daemon=True, name="ai365-git-in"))
    for t in threads:
        t.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        ex._kill_tree(proc)
        try:
            proc.wait(timeout=JOIN_SEC)
        except subprocess.TimeoutExpired:
            pass
        for t in threads:
            t.join(timeout=1.0)
        raise GitTimeout(f"git {_verb(args)} 이(가) {timeout:g}초 안에 끝나지 않아 멈췄습니다") from None
    for t in threads:
        t.join(timeout=JOIN_SEC)   # 훅이 띄운 손자 프로세스가 파이프를 쥐고 있어도 오래 기다리지 않는다 / never wait long
    r = subprocess.CompletedProcess(cmd, proc.returncode, bytes(out), bytes(err))
    if ok is not None and r.returncode not in ok:
        raise GitError(f"git {_verb(args)} 실패: {_first_line(r)}")
    return r


def _split_z(b: bytes | None) -> list[bytes]:
    return [x for x in (b or b"").split(b"\0") if x]


def _repo(folder) -> tuple[str, str]:
    """(작업 트리 맨 위 폴더, git 폴더). 폴더에 .git 이 있고 그 폴더가 저장소의 맨 위일 때만(빈 .git 때문에 부모 저장소를
    잡지 않게). 아니면 GitError.
    (work-tree root, git dir), only when the folder holds .git and is the repository's top level (so a stray .git never
    makes us act on a parent repository); GitError otherwise."""
    raw = str(folder if folder is not None else "").strip()
    if not raw or "\x00" in raw:
        raise GitError(NOT_REPO)
    try:
        root = os.path.realpath(raw)
    except (OSError, ValueError) as e:
        raise GitError(NOT_REPO) from e
    if not os.path.isdir(root) or not os.path.exists(os.path.join(root, ".git")):
        raise GitError(NOT_REPO)
    r = _run(root, ["rev-parse", "--show-toplevel", "--absolute-git-dir"], ok=None, timeout=15)
    if r.returncode != 0:
        raise GitError(f"git 저장소를 열 수 없습니다: {_first_line(r)}")
    lines = [ln.strip() for ln in _decode(r.stdout).splitlines() if ln.strip()]
    if len(lines) < 2:
        raise GitError(NOT_REPO)
    if os.path.normcase(os.path.realpath(lines[0])) != os.path.normcase(root):
        raise GitError("작업 폴더가 git 저장소의 맨 위 폴더가 아닙니다")
    return root, os.path.realpath(lines[1])


def _head(root: str) -> str | None:
    """HEAD 커밋 해시(전체), 첫 커밋 전이면 None('^' 없이) / the full HEAD hash, None before the first commit (no '^')"""
    r = _run(root, ["rev-parse", "--verify", "-q", "HEAD"], ok=None)
    out = _decode(r.stdout).strip()
    return out if r.returncode == 0 and out else None


def _branch(root: str) -> str | None:
    """지금 브랜치 이름(첫 커밋 전이어도), 분리된 HEAD 면 None / the current branch (also before the first commit), None when detached"""
    r = _run(root, ["symbolic-ref", "--short", "-q", "HEAD"], ok=None)
    out = _decode(r.stdout).strip()
    return out if r.returncode == 0 and out else None


def _temp_index(gitdir: str) -> str:
    path = os.path.join(gitdir, f"ai365-index-{os.getpid()}-{next(_SEQ)}")
    _drop_index(path)   # 이전 프로세스가 남긴 같은 이름 / a leftover with the same name
    return path


def _drop_index(path: str) -> None:
    for p in (path, path + ".lock"):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("임시 인덱스를 지우지 못했습니다: %s", p)


def _sweep_indexes(gitdir: str) -> None:
    """한 시간 넘게 남은 임시 인덱스(멈춘 프로세스의 것)를 지운다 / remove temp indexes left for over an hour"""
    cutoff = time.time() - STALE_INDEX_SEC
    try:
        names = os.listdir(gitdir)
    except OSError:
        return
    for n in names:
        if not n.startswith("ai365-index-"):
            continue
        p = os.path.join(gitdir, n)
        try:
            if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                os.remove(p)
        except OSError:
            continue


def _read_tree(head: str | None) -> list[str]:
    return ["read-tree", "--no-recurse-submodules", head] if head else ["read-tree", "--no-recurse-submodules", "--empty"]


def _add_all(root: str, index: str) -> None:
    """임시 인덱스에 작업 트리 전부(무시 파일 제외). 읽을 수 없는 경로(잠긴 파일 · 커밋 없는 안쪽 저장소)는 건너뛰고 로그만.
    The whole work tree into the temp index (ignored files excluded); unreadable paths are skipped and only logged."""
    r = _run(root, ["add", "-A", "--ignore-errors", "."], index=index, timeout=LONG_TIMEOUT, ok=(0, 1), internal=True)
    if r.returncode == 1:
        lines = [ln.strip() for ln in _decode(r.stderr).splitlines() if ln.strip()]
        logger.warning("체크포인트: 읽지 못한 경로를 건너뛰었습니다: %s", " / ".join(lines[:6])[:600])


def _paths(b: bytes | None) -> list[str]:
    return [_decode(p) for p in _split_z(b)]


def _outside(root: str, paths) -> list[str]:
    """부모 폴더의 실제 경로(링크 · 정션을 푼 것, agentic_exec.inside)가 저장소 밖인 경로. 폴더마다 한 번만 본다.
    Paths whose parent folder really lives outside the repository (links resolved, agentic_exec.inside); one check per folder."""
    ex = _ex()
    seen: dict[str, bool] = {}
    out = []
    for p in paths:
        parent = posixpath.dirname(p)
        if not parent:
            continue
        ok = seen.get(parent)
        if ok is None:
            ok = seen[parent] = ex.inside(os.path.join(root, *parent.split("/")), [root])
        if not ok:
            out.append(p)
    return out


def _drop_unsafe(root: str, index: str) -> list[str]:
    """임시 인덱스에서 저장소 밖을 가리키는 링크 아래 경로와 이 서버의 비밀 설정 파일을 뺀다 → 뺀 경로
    Remove paths below outside-pointing links and this server's secrets file from the temp index → the removed paths"""
    ex = _ex()
    raw = _split_z(_run(root, ["ls-files", "-z", "--cached"], index=index, timeout=LONG_TIMEOUT, internal=True).stdout)
    by_path = {_decode(b): b for b in raw}
    drop = set(_outside(root, list(by_path)))
    drop |= {p for p in by_path if ex._maybe_protected(os.path.join(root, *p.split("/")))}
    if drop:
        body = b"".join(by_path[p] + b"\0" for p in sorted(drop))
        _run(root, ["update-index", "--force-remove", "-z", "--stdin"], index=index, data=body, internal=True)
    return sorted(drop)


def _sid(session_id) -> str:
    sid = str(session_id or "").strip()
    if not _SID_RE.match(sid):
        raise GitError("세션 id 가 올바르지 않습니다")
    return sid


def _one_line(s, cap: int) -> str:
    return re.sub(r"\s+", " ", str(s if s is not None else "")).strip()[:cap]


def _read(full: str) -> bytes:
    with open(full, "rb") as f:
        return f.read()


def _tree_entries(root: str, treeish: str) -> list[tuple[str, str, str, str]]:
    """트리의 모든 항목 (모드, 종류, 해시, 경로), ls-tree -r -z / every entry of a tree (mode, type, oid, path)"""
    r = _run(root, ["ls-tree", "-r", "-z", "--full-tree", treeish], timeout=LONG_TIMEOUT)
    out = []
    for rec in _split_z(r.stdout):
        meta, _sep, path = rec.partition(b"\t")
        parts = meta.split()
        if len(parts) == 3 and path:
            out.append((_decode(parts[0]), _decode(parts[1]), _decode(parts[2]), _decode(path)))
    return out


# ────────────────────────────────────────────────────────
# 저장소 정보 / repository info
# ────────────────────────────────────────────────────────

def is_repo(folder) -> bool:
    """폴더에 .git 이 있고 git 을 실행할 수 있으며 그 폴더가 저장소의 맨 위인가 / .git present, git runnable, folder is the top level"""
    try:
        _repo(folder)
    except GitError:
        return False
    return True


def info(folder) -> dict:
    """{"repo", "branch", "head": "<7자>"|""}. 저장소가 아니거나 git 이 없으면 repo=False / repo=False when not a repository"""
    try:
        root, _gitdir = _repo(folder)
        head = _head(root)
        return {"repo": True, "branch": _branch(root), "head": head[:7] if head else ""}
    except GitError:
        return {"repo": False, "branch": None, "head": ""}


# ────────────────────────────────────────────────────────
# 체크포인트 / checkpoints
# ────────────────────────────────────────────────────────

def _refs(root: str, sid: str) -> list[tuple[int, str]]:
    """세션의 체크포인트 ref (번호, 이름), 번호 오름차순 / the session's checkpoint refs (number, name), ascending"""
    r = _run(root, ["for-each-ref", "--format=%(refname)", f"{CHECKPOINT_PREFIX}{sid}/"])
    out = []
    for line in _decode(r.stdout).splitlines():
        ref = line.strip()
        tail = ref.rsplit("/", 1)[-1]
        if ref.startswith(f"{CHECKPOINT_PREFIX}{sid}/") and tail.isdigit():
            out.append((int(tail), ref))
    return sorted(out)


def _new_ref(root: str, sid: str, commit: str) -> str:
    """refs/ai365/checkpoints/<세션>/<최대+1> 을 '없을 때만' 만든다(빈 이전 값). 동시에 같은 번호가 생기면 다음 번호로.
    Create refs/ai365/checkpoints/<session>/<max+1> only if absent (empty old value); retry with the next number on a race."""
    for _ in range(5):
        n = max((k for k, _ref in _refs(root, sid)), default=0) + 1
        ref = f"{CHECKPOINT_PREFIX}{sid}/{n}"
        r = _run(root, ["update-ref", ref, commit, ""], ok=None)
        if r.returncode == 0:
            return ref
        if _run(root, ["rev-parse", "--verify", "-q", ref], ok=None).returncode != 0:
            raise GitError(f"git update-ref 실패: {_first_line(r)}")
    raise GitError("체크포인트 ref 를 만들지 못했습니다")


def snapshot(folder, session_id, label="") -> dict:
    """지금 작업 트리(무시 파일 · 저장소 밖 링크 아래 파일 · 서버 비밀 파일 제외)를 체크포인트 커밋으로 남긴다 →
    {"ref", "commit", "tree", "files": 트리의 파일 수, "label"}. 같은 tree 여도 commit-tree 는 한 번 새로 만든다(재사용 판단은
    호출자가 tree 로). 읽을 수 없는 파일은 건너뛴다. 실제 인덱스 · 브랜치 · HEAD 는 그대로.
    Record the current work tree (no ignored files, nothing below outside links, no server secrets file) as a checkpoint
    commit. A new commit is made even for an unchanged tree (the caller may compare `tree`); unreadable files are skipped;
    the real index, branch and HEAD are untouched."""
    root, gitdir = _repo(folder)
    sid = _sid(session_id)
    text = _one_line(label, LABEL_MAX)
    head = _head(root)
    _sweep_indexes(gitdir)
    index = _temp_index(gitdir)
    try:
        _run(root, _read_tree(head), index=index, internal=True)
        _add_all(root, index)
        dropped = _drop_unsafe(root, index)
        if dropped:
            logger.info("체크포인트: 저장소 밖 링크 아래 · 비밀 파일 %d개를 뺐습니다", len(dropped))
        tree = _decode(_run(root, ["write-tree"], index=index, internal=True).stdout).strip()
    finally:
        _drop_index(index)
    if not tree:
        raise GitError("git write-tree 가 트리를 돌려주지 않았습니다")
    files = len(_tree_entries(root, tree))
    message = f"ai365 checkpoint: {text}" if text else "ai365 checkpoint"
    # 체크포인트는 내부 ref 라 서명하지 않는다(서명 설정이 있으면 매 턴 암호 창이 뜰 수 있다) / internal refs are never signed
    args = ["-c", f"user.name={FALLBACK_NAME}", "-c", f"user.email={FALLBACK_EMAIL}", "commit-tree", "--no-gpg-sign"]
    if head:
        args += ["-p", head]
    commit = _decode(_run(root, [*args, tree], data=(message + "\n").encode("utf-8")).stdout).strip()
    if not commit:
        raise GitError("git commit-tree 가 커밋을 돌려주지 않았습니다")
    ref = _new_ref(root, sid, commit)
    return {"ref": ref, "commit": commit, "tree": tree, "files": files, "label": text}


def _resolve_commit(root: str, commit) -> str:
    """체크포인트 커밋 해시 확인('^{commit}' 대신 cat-file -t: 인자에 '^' 를 쓰지 않는다) / verify a commit without '^'"""
    s = str(commit if commit is not None else "").strip()
    if not s or s.startswith("-") or "\x00" in s or any(c.isspace() for c in s) or "^" in s:
        raise GitError("체크포인트 커밋이 올바르지 않습니다")
    r = _run(root, ["rev-parse", "--verify", "-q", s], ok=None)
    out = _decode(r.stdout).strip()
    if r.returncode != 0 or not out:
        raise GitError(f"체크포인트 커밋을 찾을 수 없습니다: {s[:12]}")
    if _decode(_run(root, ["cat-file", "-t", out], ok=None).stdout).strip() != "commit":
        raise GitError(f"체크포인트 커밋이 아닙니다: {s[:12]}")
    return out


class _Undo:
    """되돌리기 전에 미리 바꾼 파일(.gitignore)을 원래대로 돌리는 기록 / a journal that puts pre-written files back"""

    def __init__(self, root: str):
        self.root = root
        self.ops: list[tuple[str, bytes | None, list[str]]] = []   # (경로, 원래 바이트|None, 새로 만든 폴더들)

    def _rel(self, full: str) -> str:
        return os.path.relpath(full, self.root).replace("\\", "/")

    def write(self, full: str, data: bytes) -> None:
        old = _read(full) if os.path.isfile(full) else None
        created, d = [], os.path.dirname(full)
        while not os.path.isdir(d):
            created.append(d)
            up = os.path.dirname(d)
            if up == d:
                break
            d = up
        self.ops.append((full, old, created))   # 쓰기 전에 적는다(중간에 실패해도 되돌린다) / journal first
        try:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as f:
                f.write(data)
        except OSError as e:
            raise GitError(f"{LOCKED_ERR}{self._rel(full)}" if isinstance(e, PermissionError)
                           else f"{self._rel(full)} 을(를) 쓰지 못했습니다: {e}") from e

    def remove(self, full: str) -> None:
        try:
            old = _read(full)
        except OSError as e:
            raise GitError(f"{self._rel(full)} 을(를) 읽지 못했습니다: {e}") from e
        self.ops.append((full, old, []))
        try:
            os.remove(full)
        except OSError as e:
            raise GitError(f"{LOCKED_ERR}{self._rel(full)}" if isinstance(e, PermissionError)
                           else f"{self._rel(full)} 을(를) 지우지 못했습니다: {e}") from e

    def rollback(self) -> None:
        for full, old, created in reversed(self.ops):
            try:
                if old is None:
                    if os.path.lexists(full):
                        os.remove(full)
                else:
                    with open(full, "wb") as f:
                        f.write(old)
            except OSError:
                logger.warning("되돌리기 취소 중 파일을 원래대로 돌리지 못했습니다: %s", full)
            for d in created:   # 깊은 폴더부터 / deepest first
                try:
                    os.rmdir(d)
                except OSError:
                    pass
        self.ops.clear()


def _apply_ignores(root: str, index: str, entries, undo: _Undo) -> None:
    """체크포인트의 무시 규칙으로 맞춘다(add -A 전에): 트리의 .gitignore 를 그 내용으로 쓰고, 트리에 없는데 지금 규칙으로 git 이
    읽을 .gitignore 는 지운다(지우면 새로 보이는 것이 있어 몇 번 되풀이). 링크인 .gitignore · 밖을 가리키는 폴더는 거절.
    Align the work tree with the checkpoint's ignore rules before add -A: write the tree's .gitignore files and remove
    the .gitignore files git would read that the tree lacks (repeated, since a removal can reveal more). A .gitignore
    that is a link, or a folder pointing outside, refuses the restore."""
    want = {path: oid for _mode, typ, oid, path in entries if typ == "blob" and posixpath.basename(path) == ".gitignore"
            and ".git" not in [part.lower() for part in path.split("/")[:-1]]}   # .git 안은 쓰지 않는다 / never inside .git
    bad = _outside(root, list(want))
    if bad:
        raise GitError(LINK_ERR + bad[0])
    for path in sorted(want):
        full = os.path.join(root, *path.split("/"))
        if os.path.islink(full):
            raise GitError(LINK_ERR + path)
        data = _run(root, ["cat-file", "blob", want[path]]).stdout
        if os.path.isfile(full) and _read(full) == data:
            continue
        undo.write(full, data)
    for _ in range(IGNORE_ROUNDS):
        listed = _paths(_run(root, ["ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", ":(glob)**/.gitignore"],
                             index=index, timeout=LONG_TIMEOUT, internal=True).stdout)
        extra = sorted(p for p in set(listed) - set(want)
                       if posixpath.basename(p) == ".gitignore" and os.path.lexists(os.path.join(root, *p.split("/"))))
        if not extra:
            return
        bad = _outside(root, extra)
        if bad:
            raise GitError(LINK_ERR + bad[0])
        for p in extra:
            full = os.path.join(root, *p.split("/"))
            if os.path.islink(full) or not os.path.isfile(full):
                raise GitError(LINK_ERR + p)
            undo.remove(full)


_CREATE_FILE = None


def _create_file_fn():
    """kernel32.CreateFileW(한 번만 준비) / kernel32.CreateFileW, prepared once"""
    global _CREATE_FILE
    if _CREATE_FILE is None:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        fn = k32.CreateFileW
        fn.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                       wintypes.HANDLE]
        fn.restype = wintypes.HANDLE
        close = k32.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        _CREATE_FILE = (fn, close, ctypes)
    return _CREATE_FILE


def _locked(full: str) -> bool:
    """다른 프로그램이 지우기 · 바꾸기를 막고 있는가. Windows 에서 DELETE 권한으로 열어 보기만 한다(아무것도 바꾸지 않는다,
    공유 위반 · 잠금 위반이면 잠김). 그 밖의 OS 는 열린 파일도 지울 수 있어 늘 False.
    Is the file held so it cannot be removed or replaced? On Windows it is only opened with DELETE access (nothing is
    changed); a sharing or lock violation means locked. Elsewhere open files can be unlinked, so False."""
    if os.name != "nt" or os.path.islink(full) or not os.path.isfile(full):
        return False
    try:
        fn, close, ctypes = _create_file_fn()
    except (OSError, AttributeError, ImportError):
        return False
    path = os.path.abspath(full)
    if len(path) >= 240 and not path.startswith("\\\\?\\"):
        path = "\\\\?\\" + path
    h = fn(path, 0x00010000, 0x7, None, 3, 0x80, None)   # DELETE · 모두 공유 · OPEN_EXISTING · NORMAL
    if h is None or h == ctypes.c_void_p(-1).value:
        return ctypes.get_last_error() in _LOCK_ERRORS
    close(h)
    return False


def restore(folder, commit) -> dict:
    """작업 트리를 체크포인트 커밋으로 되돌린다 → {"commit": 전체 해시, "files": 바뀐(쓰거나 지운) 파일 수}.
    체크포인트 시점의 무시 규칙으로 돌아(스냅샷 때 무시되던 파일은 남는다) 스냅샷 뒤에 생긴 파일은 지운다. 바뀔 경로가 저장소
    밖 링크를 지나거나 다른 프로그램이 열어 둔 파일이면 아무것도 바꾸지 않고 GitError. 실제 인덱스 · 브랜치 · HEAD · 서브모듈은
    그대로 둔다.
    Bring the work tree back to a checkpoint commit → {"commit": full hash, "files": paths written or removed}. The
    checkpoint's ignore rules apply (files ignored at snapshot time survive) and files created after the snapshot are
    removed. A path that runs through an outside link or is held open by another program refuses the restore without
    changing anything. The real index, branch, HEAD and submodules stay as they are."""
    root, gitdir = _repo(folder)
    target = _resolve_commit(root, commit)
    entries = _tree_entries(root, target)
    head = _head(root)
    index = _temp_index(gitdir)
    undo = _Undo(root)
    try:
        try:
            _run(root, _read_tree(head), index=index, internal=True)
            _apply_ignores(root, index, entries, undo)
            _add_all(root, index)
            _drop_unsafe(root, index)
            changed = _paths(_run(root, ["diff-index", "--cached", "--name-only", "-z", "--no-renames", target],
                                  index=index, timeout=LONG_TIMEOUT, internal=True).stdout)
            # 내용은 같아도 add 가 새로 읽지 못한 항목(잠김 등)은 read-tree --reset 이 다시 쓴다 / stale entries get rewritten too
            stale = _paths(_run(root, ["diff-files", "--name-only", "-z", "--ignore-submodules"], index=index,
                                timeout=LONG_TIMEOUT, internal=True).stdout)
            touched = sorted(set(changed) | set(stale))
            bad = _outside(root, touched)
            if bad:
                raise GitError(LINK_ERR + bad[0])
            secret = [p for p in touched if _ex()._maybe_protected(os.path.join(root, *p.split("/")))]
            if secret:   # 예전 체크포인트에 들어 있던 서버 비밀 파일은 덮지 않는다 / never overwrite the server's secrets file
                raise GitError("이 서버의 비밀 설정 파일은 되돌릴 수 없습니다: " + secret[0])
            held = [p for p in touched if _locked(os.path.join(root, *p.split("/")))]
            if held:
                raise GitError(LOCKED_ERR + held[0])
        except BaseException:
            undo.rollback()   # 아무것도 바꾸지 않은 상태로 / back to an unchanged work tree
            raise
        try:
            _run(root, ["read-tree", "-u", "--reset", "--no-recurse-submodules", target], index=index,
                 timeout=LONG_TIMEOUT, internal=True)
        except GitError as e:
            raise GitError(f"{e}. {PARTIAL_NOTE}") from e
    finally:
        _drop_index(index)
    return {"commit": target, "files": len(changed)}


def list_refs(folder, session_id) -> list[str]:
    """세션의 체크포인트 ref 이름(번호 오름차순). 저장소가 아니거나 세션 id 가 이상하면 [] / [] for a non-repository"""
    try:
        root, _gitdir = _repo(folder)
        sid = _sid(session_id)
    except GitError:
        return []
    return [ref for _n, ref in _refs(root, sid)]


def drop_ref(folder, ref) -> None:
    """체크포인트 ref 하나를 지운다(refs/ai365/checkpoints/ 아래만, 없으면 그대로). 저장소가 아니면 아무것도 안 한다.
    Delete one checkpoint ref (only under refs/ai365/checkpoints/; a missing ref is fine); no-op outside a repository."""
    r = str(ref if ref is not None else "").strip()
    if not _REF_RE.match(r):
        raise GitError("체크포인트 ref 가 아닙니다")
    try:
        root, _gitdir = _repo(folder)
    except GitError:
        return
    _run(root, ["update-ref", "-d", r])


def drop_refs(folder, session_id) -> int:
    """세션의 체크포인트 ref 를 모두 지우고 지운 수를 돌려준다(한 번의 update-ref --stdin) / delete all of a session's refs"""
    try:
        root, _gitdir = _repo(folder)
        sid = _sid(session_id)
    except GitError:
        return 0
    refs = [ref for _n, ref in _refs(root, sid)]
    if not refs:
        return 0
    _run(root, ["update-ref", "--stdin"], data="".join(f"delete {ref}\n" for ref in refs).encode("utf-8"))
    return len(refs)


# ────────────────────────────────────────────────────────
# 변경 목록 · diff / change list and diffs
# ────────────────────────────────────────────────────────

def _letter(xy: str, path: str, orig: str) -> tuple[str | None, str]:
    """porcelain 두 글자 → HEAD 대비 한 글자(M · A · D · R · ? · !) 와 보여 줄 경로. None = HEAD 대비 바뀐 것이 없다.
    충돌(병합 안 됨)은 M, ' A'(git add -N 의 추가 예정)는 A 로 본다.
    The porcelain XY pair → one letter against HEAD plus the path to show; None = nothing changed against HEAD.
    Unmerged entries count as M and ' A' (intent to add, git add -N) as A."""
    x, y = xy[0], xy[1]
    if xy == "??":
        return "?", path
    if xy == "!!":
        return "!", path
    if "U" in xy or xy in ("AA", "DD"):
        return "M", path
    if x in "RC":
        if y == "D":   # 이름을 바꾼(복사한) 뒤 지웠다 / renamed (copied) and then deleted
            return ("D", orig) if x == "R" and orig else (None, path)
        return ("R" if x == "R" else "A"), path
    if y in "RC":
        return "R", path
    if x == "A" or y == "A":
        return (None, path) if y == "D" else ("A", path)
    if x == "D" or y == "D":
        return "D", path
    return "M", path


def _changes(root: str) -> list[tuple[str, str, str]]:
    """HEAD 대비 바뀐 파일 [(글자, 경로, 원래 경로)], 경로순 · 경로마다 한 번 / changed files against HEAD, by path, each once"""
    r = _run(root, ["status", "--porcelain=v1", "-z", "--untracked-files=all"], timeout=LONG_TIMEOUT)
    parts = r.stdout.split(b"\0")
    out, seen, i = [], set(), 0
    while i < len(parts):
        rec = parts[i]
        i += 1
        if len(rec) < 4:
            continue
        xy = rec[:2].decode("ascii", errors="replace")
        path = _decode(rec[3:])
        orig = ""
        if "R" in xy or "C" in xy:   # -z 에서는 원래 경로가 다음 칸에 온다 / with -z the original path follows
            if i < len(parts):
                orig = _decode(parts[i])
                i += 1
        letter, shown = _letter(xy, path, orig)
        if letter is None or shown in seen:
            continue
        seen.add(shown)
        out.append((letter, shown, orig))
    out.sort(key=lambda e: e[1])
    return out


def _numstat(root: str) -> dict[str, tuple[int | None, int | None]]:
    """git diff --numstat -z -M HEAD → {경로: (더한 줄, 뺀 줄)}, 이진은 (None, None). 이름 바꿈은 새 경로로.
    git diff --numstat -z -M HEAD → {path: (added, removed)}; binary = (None, None); renames under the new path."""
    r = _run(root, ["diff", "--numstat", "-z", "-M", "--no-color", "--no-ext-diff", "HEAD", "--"], timeout=LONG_TIMEOUT)
    parts = r.stdout.split(b"\0")
    out, i = {}, 0
    while i < len(parts):
        rec = parts[i]
        i += 1
        fields = rec.split(b"\t", 2)
        if len(fields) < 3:
            continue
        a, d, p = fields
        if p == b"":   # 이름 바꿈: 원래 경로 · 새 경로가 다음 두 칸 / a rename: old and new paths follow
            new = parts[i + 1] if i + 1 < len(parts) else b""
            i += 2
            path = _decode(new)
        else:
            path = _decode(p)
        out[path] = (_count(a), _count(d))
    return out


def _count(b: bytes) -> int | None:
    """numstat 의 수 칸: '-' = 이진(None), 숫자가 아니면 0 / a numstat count: '-' means binary (None)"""
    if b == b"-":
        return None
    try:
        return int(b or b"0")
    except ValueError:
        return 0


def _count_lines(full: str) -> tuple[int, bool]:
    """(줄 수, 이진). 앞 8000바이트에 NUL 이 있으면 이진(git 과 같은 판정), 너무 크거나 못 읽으면 (0, False).
    (lines, binary): a NUL in the first 8000 bytes means binary (git's rule); too big or unreadable gives (0, False)."""
    try:
        if not os.path.isfile(full) or os.path.getsize(full) > COUNT_MAX_BYTES:
            return 0, False
        n, last = 0, b""
        with open(full, "rb") as f:
            head = f.read(BINARY_SNIFF)
            if b"\x00" in head:
                return 0, True
            chunk = head
            while chunk:
                n += chunk.count(b"\n")
                last = chunk[-1:]
                chunk = f.read(1 << 20)
        if last and last != b"\n":
            n += 1
        return n, False
    except OSError:
        return 0, False


def status(folder) -> dict:
    """HEAD 대비 변경 → {"repo", "branch", "files": [{"path", "status": M|A|D|R|?|!, "added", "removed", "binary"}],
    "added", "removed", "count", "truncated"}. 저장소가 아니면 repo=False · files=[]. 추적 안 된 파일은 줄 수 = added.
    Changes against HEAD in the /changes shape; repo=False and no files outside a repository. Untracked files count
    their lines as added. "count" is the full number of changed files even when the list is capped."""
    try:
        root, _gitdir = _repo(folder)
    except GitError:
        return {"repo": False, "branch": None, "files": [], "added": 0, "removed": 0, "count": 0, "truncated": False}
    branch = _branch(root)
    head = _head(root)
    entries = _changes(root)
    nums = _numstat(root) if head and entries else {}
    files, added, removed = [], 0, 0
    for letter, path, _orig in entries[:MAX_STATUS_FILES]:
        own_count = letter == "?" or (head is None and letter != "D") or (letter == "A" and path not in nums)
        if own_count:
            a, binary = (0, False) if path.endswith("/") else _count_lines(os.path.join(root, *path.split("/")))
            d = 0
        else:
            a0, d0 = nums.get(path, (0, 0))
            binary = a0 is None or d0 is None
            a, d = (0, 0) if binary else (int(a0), int(d0))
        files.append({"path": path, "status": letter, "added": a, "removed": d, "binary": binary})
        added += a
        removed += d
    return {"repo": True, "branch": branch, "files": files, "added": added, "removed": removed, "count": len(entries),
            "truncated": len(entries) > len(files)}


def _rel(root: str, path) -> str:
    """저장소 안의 상대 경로('/' 구분)로. 밖이거나 밖을 가리키는 링크면 GitError / a repo-relative path; GitError when outside"""
    s = str(path if path is not None else "").strip()
    if not s or "\x00" in s:
        raise GitError("경로가 비어 있습니다")
    s = s.replace("\\", "/")
    if os.path.isabs(s) or re.match(r"^[A-Za-z]:", s) or s.startswith("/"):
        if not _ex().inside(s, [root]):
            raise GitError("저장소 밖 경로입니다")
        s = os.path.relpath(os.path.abspath(s), root).replace("\\", "/")
    rel = posixpath.normpath(s)
    if rel in ("", ".", "..") or rel.startswith("../") or rel.startswith("/"):
        raise GitError("저장소 밖 경로입니다")
    full = os.path.join(root, *rel.split("/"))
    if os.path.lexists(full) and not _ex().inside(full, [root]):
        raise GitError("저장소 밖을 가리키는 경로입니다")
    return rel


def _new_file_diff(root: str, rel: str) -> tuple[str, bool, bool]:
    """추적 안 된(또는 첫 커밋 전) 파일 → (unified, 이진, 잘림). 전체를 + 줄로 / an untracked file as all-added lines"""
    full = os.path.join(root, *rel.split("/"))
    if not os.path.isfile(full):
        return "", False, False
    try:
        size = os.path.getsize(full)
        with open(full, "rb") as f:
            data = f.read(NEW_FILE_MAX_BYTES)
    except OSError as e:
        raise GitError(f"파일을 읽지 못했습니다: {e}") from e
    if b"\x00" in data[:BINARY_SNIFF]:
        return "", True, False
    try:
        text = _ex()._decode_text(data)[0]
    except Exception:  # noqa: BLE001 (이진으로 본다 / treated as binary)
        return "", True, False
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    if text.endswith("\n"):
        lines = lines[:-1]
    out = [f"diff --git a/{rel} b/{rel}\n", "new file mode 100644\n", "--- /dev/null\n", f"+++ b/{rel}\n"]
    if text:
        out.append(f"@@ -0,0 +1,{len(lines)} @@\n")
        out += ["+" + ln + "\n" for ln in lines]
        if not text.endswith("\n"):
            out.append("\\ No newline at end of file\n")
    return "".join(out), False, size > len(data)


def diff(folder, path, max_chars=200_000) -> dict:
    """한 파일의 HEAD 대비 diff → {"path", "status", "unified", "binary", "truncated"}. 추적 안 된 파일은 전체를 + 줄로,
    이진은 binary=True(본문 없음), 바뀐 것이 없으면 status "" · unified "". max_chars 를 넘으면 줄 경계에서 자른다.
    One file's diff against HEAD in the /changes/diff shape: untracked files as all-added lines, binary=True without a
    body for binaries, status "" and an empty diff when unchanged; cut at a line boundary past max_chars."""
    root, _gitdir = _repo(folder)
    rel = _rel(root, path)
    if _ex()._maybe_protected(os.path.join(root, *rel.split("/"))):
        raise GitError("이 서버의 비밀 설정 파일은 열 수 없습니다")
    cap = max(1, int(max_chars or 200_000))
    out = {"path": rel, "status": "", "unified": "", "binary": False, "truncated": False}
    entry = next((e for e in _changes(root) if e[1] == rel or (e[0] == "R" and e[2] == rel)), None)
    if entry is None:
        return out
    letter, shown, orig = entry
    out.update(path=shown, status=letter)
    if letter == "?" or (_head(root) is None and letter != "D"):
        text, binary, truncated = _new_file_diff(root, shown)
    else:
        paths = [orig, shown] if letter == "R" and orig else [shown]
        r = _run(root, ["diff", "--no-color", "--no-ext-diff", "-M", "HEAD", "--", *paths], literal=True,
                 timeout=LONG_TIMEOUT)
        text = _ex()._decode_out(r.stdout).replace("\r\n", "\n")
        binary, truncated = bool(_BINARY_RE.search(text)), False
        if binary:
            text = ""
        elif not text and letter == "A":   # 추가 예정(git add -N) 등 diff 가 비면 파일로 / an empty diff for an added file
            text, binary, truncated = _new_file_diff(root, shown)
    if len(text) > cap:
        cut = text.rfind("\n", 0, cap)
        text = text[:cut + 1] if cut > 0 else text[:cap]
        truncated = True
    out.update(unified=text, binary=binary, truncated=truncated)
    return out


# ────────────────────────────────────────────────────────
# 커밋 · 메시지 제안 / commit and message suggestions
# ────────────────────────────────────────────────────────

def _config(root: str, key: str) -> str:
    r = _run(root, ["config", "--get", key], ok=(0, 1))
    return _decode(r.stdout).strip() if r.returncode == 0 else ""


def _drop_stale_lock(gitdir: str, since: float) -> None:
    """시간 초과로 끝낸 git 이 남긴 index.lock(이번 호출이 시작된 뒤 생긴 것만) 정리 / remove the index.lock a killed git left"""
    lock = os.path.join(gitdir, "index.lock")
    try:
        if os.path.isfile(lock) and os.path.getmtime(lock) >= since - 1:
            os.remove(lock)
            logger.warning("시간 초과로 멈춘 git 의 index.lock 을 지웠습니다: %s", lock)
    except OSError:
        logger.warning("index.lock 을 지우지 못했습니다: %s", lock)


def commit(folder, message) -> dict:
    """add -A . + commit(실제 인덱스 · 브랜치를 바꾸는 유일한 함수, 사용자 git 설정 · 저장소 훅은 그대로) → {"commit": "<7자>",
    "files": n}. 빈 메시지 · 변경 없음 → GitError. user.name/email 이 없으면 -c user.name=Ai365 Agentic -c user.email=
    agentic@ai365.local. 훅이 매달려 시간을 넘기면 프로세스 트리를 끝내고 남은 index.lock 을 지운 뒤 GitTimeout.
    add -A . + commit (the only function that changes the real index and branch; the user's git config and the
    repository's hooks apply) → {"commit": "<7 chars>", "files": n}. An empty message or nothing to commit raises
    GitError; a missing identity falls back to Ai365 Agentic. A hanging hook past the limit kills the process tree,
    removes the index.lock it left and raises GitTimeout."""
    msg = str(message if message is not None else "").strip()
    if not msg:
        raise GitError("커밋 메시지가 비어 있습니다")
    root, gitdir = _repo(folder)
    started = time.time()
    try:
        _run(root, ["add", "-A", "."], timeout=LONG_TIMEOUT)
        staged = _split_z(_run(root, ["diff", "--cached", "--name-only", "-z", "-M"]).stdout)
        if not staged:
            raise GitError("커밋할 변경이 없습니다")
        ident = []
        if not _config(root, "user.name"):
            ident += ["-c", f"user.name={FALLBACK_NAME}"]
        if not _config(root, "user.email"):
            ident += ["-c", f"user.email={FALLBACK_EMAIL}"]
        _run(root, [*ident, "commit", "-q", "-F", "-"], data=(msg + "\n").encode("utf-8"), timeout=LONG_TIMEOUT,
             hooks=True)
    except GitTimeout:
        _drop_stale_lock(gitdir, started)
        raise
    head = _head(root)
    if not head:
        raise GitError("커밋한 뒤 HEAD 를 읽지 못했습니다")
    return {"commit": head[:7], "files": len(staged)}


def _rule_message(n: int) -> str:
    return f"파일 {n}개 변경 / {n} file{'' if n == 1 else 's'} changed"


def _clean_suggestion(raw) -> str:
    """모델 답 → 커밋 제목 한 줄('한국어 / English' 꼴이 아니면 ""). 줄표(em dash)는 '-' 로.
    The model's answer → one subject line, "" unless it reads 'Korean / English'; dashes become '-'."""
    line = ""
    for ln in str(raw if raw is not None else "").replace("\r\n", "\n").split("\n"):
        s = ln.strip()
        if not s or s.startswith("```"):
            continue
        s = re.sub(r"^(?:[-*•]\s+|커밋\s*메시지\s*[:：]\s*|commit\s+message\s*[:：]\s*)", "", s, flags=re.IGNORECASE)
        s = s.strip().strip("`\"'“”‘’").strip()
        if s:
            line = s
            break
    line = re.sub(r"\s+", " ", line.replace(chr(0x2014), "-").replace(chr(0x2013), "-")).strip()   # 줄표 · 짧은 줄표 / dashes
    if " / " not in line:
        return ""
    ko, en = line.split(" / ", 1)
    if not _HANGUL_RE.search(ko) or not _LATIN_RE.search(en):
        return ""
    return line[:MESSAGE_MAX].rstrip()


def _drop_protected(root: str, text: str) -> str:
    """diff 글에서 이 서버의 비밀 설정 파일 블록을 뺀다 / drop this server's secrets-file blocks from a diff"""
    ex = _ex()
    rels = []
    for p in ex.PROTECTED_FILES:
        if ex.inside(p, [root]):
            rels.append(os.path.relpath(p, root).replace("\\", "/").lower())
    if not rels:
        return text
    blocks = re.split(r"(?m)^(?=diff --git )", text)
    keep = [b for b in blocks if not any(b.split("\n", 1)[0].lower().endswith(" b/" + r) for r in rels)]
    return "".join(keep)


def suggest_message(folder) -> dict:
    """커밋 메시지 제안 → {"message": "한국어 / English" 한 줄, "files": n}. 경량 모델(lite) 1회, 실패하거나 꼴이 틀리면
    "파일 n개 변경 / n files changed". 바뀐 것이 없으면 {"message": "", "files": 0}(모델을 부르지 않는다).
    Suggest a commit message → one 'Korean / English' line and the file count. One lite-model call; on failure or a
    malformed answer the rule sentence. Nothing changed → {"message": "", "files": 0} without calling the model."""
    st = status(folder)
    if not st["repo"]:
        raise GitError(NOT_REPO)
    n = int(st["count"])
    if n == 0:
        return {"message": "", "files": 0}
    root = os.path.realpath(str(folder))
    rule = _rule_message(n)
    stat_text = diff_text = ""
    if _head(root):
        stat_text = _decode(_run(root, ["diff", "HEAD", "--stat", "--no-color", "--no-ext-diff", "--"]).stdout).strip()
        raw = _ex()._decode_out(_run(root, ["diff", "HEAD", "--no-color", "--no-ext-diff", "--"],
                                     timeout=LONG_TIMEOUT).stdout)
        diff_text = _drop_protected(root, raw.replace("\r\n", "\n"))[:SUGGEST_DIFF_CHARS]
    rows = [f"{f['status']} {f['path']}" + ("" if f["binary"] else f" (+{f['added']} -{f['removed']})")
            for f in st["files"][:SUGGEST_FILES]]
    prompt = (f"[변경 파일 {n}개]\n" + "\n".join(rows)
              + ("\n\n[git diff --stat]\n" + stat_text if stat_text else "")
              + ("\n\n[diff 앞부분]\n" + diff_text if diff_text else ""))
    try:
        answer = llm.generate(prompt, system=SUGGEST_SYSTEM, tier="lite")
    except Exception:  # noqa: BLE001 (제안 실패는 규칙 문장으로 / a failed suggestion falls back to the rule sentence)
        logger.warning("커밋 메시지 제안 실패, 규칙 문장으로 대신합니다", exc_info=True)
        return {"message": rule, "files": n}
    return {"message": _clean_suggestion(answer) or rule, "files": n}
