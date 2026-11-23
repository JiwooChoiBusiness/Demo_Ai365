"""Agentic 모드 실행기(2026-10-19): 파일 읽기 · 쓰기 · 편집 · 목록 · 찾기 · 검색 · 명령 실행.

Executor 는 실행 위치를 바꿔 끼우는 인터페이스다(1차 = LocalExecutor: 이 서버 PC, 2차 이후 샌드박스 · 컴패니언).
LocalExecutor 는 허용 폴더 안에서만 일한다: 상대 경로는 세션 폴더 기준으로 절대화하고, os.path.realpath 로 심볼릭 링크 ·
정션을 푼 뒤 허용 폴더 접두사를 본다(대소문자는 os.path.normcase, 즉 Windows 규칙). 승인 카드에서 허용된 호출만
allow_outside=True 로 밖을 다룬다. 이진 파일과 10MB 넘는 파일은 읽지 않고, 이 서버의 비밀 설정 파일(.env)은 열지 않는다.
명령은 세션 폴더에서 Windows = cmd /d /s /c, 그 밖 = /bin/sh -c 로 돌린다. 시간 제한을 넘으면 프로세스 트리를 끝내고,
출력은 상한을 넘으면 앞뒤를 남기고 가운데를 생략한다. background 명령은 스레드가 끝까지 지켜보며 agentic_tasks 행을 갱신한다.
자식 프로세스 환경에서는 API 키 · 토큰 같은 비밀 변수를 뺀다(서버의 Gemini 키가 명령 출력으로 새지 않게).
저장소 내부(.git) 파일은 쓰기 · 편집을 거절한다(RefusedError, 2026-10-19 적대 검토 H1). 읽기 · 검색은 그대로.
read_rows(줄 번호 · 줄 자르기)와 compute_edit(CRLF 맞춤 · 0곳 · 여러 곳 규칙)은 모듈 함수라 내 컴퓨터 폴더 세션의
agentic_browser.BrowserExecutor 도 같은 규칙을 쓴다(2026-10-20).
"""
# Agentic mode executor (2026-10-19): read, write, edit, list, glob, grep and run commands.
# Executor is the swappable interface for where work happens (phase 1 = LocalExecutor on this server PC; sandboxes or
# a companion later). LocalExecutor works inside the allowed folders only: relative paths are made absolute against the
# session folder, os.path.realpath resolves symlinks and junctions, then the allowed-folder prefix is checked (case by
# os.path.normcase, i.e. Windows rules). Only calls approved on an approval card pass allow_outside=True. Binary files
# and files over 10 MB are not read, and this server's own secrets file (.env) is never opened.
# Commands run in the session folder via cmd /d /s /c on Windows and /bin/sh -c elsewhere; a timeout kills the process
# tree and output over the cap keeps its head and tail with the middle omitted. Background commands are watched by a
# thread that keeps the agentic_tasks row current. Secret variables (API keys, tokens) are removed from the child
# environment so the server's Gemini keys cannot leak through command output.
# Writes and edits inside a repository's .git are refused (RefusedError, adversarial review H1); reads and searches stay.
# read_rows (line numbers and slicing) and compute_edit (CRLF matching, the zero and many match rules) are module
# functions, so agentic_browser.BrowserExecutor of browser-folder sessions follows the same rules (2026-10-20).

from __future__ import annotations

import codecs
import difflib
import locale
import logging
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from app import agentic_store, kst

logger = logging.getLogger("ai365.agentic")

MAX_FILE_BYTES = 10 * 1024 * 1024   # 읽기 · 편집 · 쓰기 상한 / read, edit and write cap
READ_MAX_CHARS = 60_000             # read 본문 상한 / read body cap
READ_DEFAULT_LINES = 2000
READ_MAX_LINES = 100_000
LINE_MAX_CHARS = 2000               # 한 줄 상한 / one line's cap
MAX_LIST = 500
MAX_GLOB = 500
SCAN_MAX = 50_000                   # 찾기 · 검색이 훑는 파일 수 상한 / files visited by glob and grep
GREP_DEFAULT = 200
GREP_MAX = 1000
GREP_LINE_CHARS = 300
GREP_FILE_BYTES = 5 * 1024 * 1024
GREP_TIME_SEC = 30.0
MAX_TIMEOUT_SEC = 600               # 앞에서 도는 명령의 시간 제한 상한 / foreground command timeout cap
BG_FLUSH_SEC = 1.0                  # background 출력을 DB 에 옮기는 간격 / how often background output reaches the DB
JOIN_SEC = 5.0
SKIP_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", ".tox"})
# 자식 환경에서 빼는 비밀 변수 이름(적대 검토 M1 로 연결 문자열 · DSN · 개인 키 · 서명 키까지) / secret names dropped from the child env
_SECRET_ENV = re.compile(r"API_?KEY|ACCESS_KEY|SECRET|TOKEN|PASSW|CREDENTIAL|CONN(?:ECTION)?_?STR|_DSN|DATABASE_URL|PRIVATE|_AUTH"
                         r"|SESSION_SECRET|SIGNING|^GEMINI_|^GOOGLE_|^TAVILY", re.IGNORECASE)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# 이 서버의 비밀 설정 파일: 허용 폴더 안이어도 읽기 · 쓰기 · 편집을 거절하고 검색에서 뺀다 / this server's secrets file
PROTECTED_FILES = {os.path.normcase(os.path.realpath(str(Path(__file__).resolve().parent.parent / ".env")))}


class ExecError(Exception):
    """사람이 읽는 실패(도구 결과로 모델에 돌려준다) / a human-readable failure, fed back to the model"""


class OutsideError(ExecError):
    """허용 폴더 밖 경로 / a path outside the allowed folders"""


class RefusedError(ExecError):
    """정책상 거절(아무것도 실행하지 않았다). 루프가 연속 거절로 센다(2026-10-19 적대 검토 L4)
    A policy refusal (nothing ran); the loop counts it toward the consecutive-refusal stop (adversarial review L4)"""


GIT_INTERNAL = "저장소 내부(.git) 파일은 도구로 고칠 수 없습니다. git 명령을 쓰세요"


# ────────────────────────────────────────────────────────
# 경로 / paths
# ────────────────────────────────────────────────────────

def _clamp(v, lo: int, hi: int, default: int | None = None) -> int:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        n = lo if default is None else default
    return max(lo, min(hi, n))


def inside(path: str, roots) -> bool:
    """path 가 roots 중 하나와 같거나 그 아래인가(realpath + normcase) / is the path one of the roots or below one"""
    try:
        p = os.path.normcase(os.path.realpath(path))
    except (OSError, ValueError):
        return False
    for r in roots or []:
        if not r:
            continue
        try:
            root = os.path.normcase(os.path.realpath(r))
        except (OSError, ValueError):
            continue
        base = root.rstrip("\\/")
        if p == root or p == base or p.startswith(base + os.sep):
            return True
    return False


def real_target(folder: str, raw) -> str:
    """경로 → 절대 경로(상대 경로는 folder 기준) → realpath. 검사는 하지 않는다 / resolve a path without checking it"""
    s = str(raw if raw is not None else "").strip()
    if "\x00" in s:
        raise ExecError("경로가 올바르지 않습니다")
    p = os.path.realpath(folder) if not s else (s if os.path.isabs(s) else os.path.join(folder, s))
    try:
        return os.path.realpath(p)
    except (OSError, ValueError) as e:
        raise ExecError(f"경로가 올바르지 않습니다: {s}") from e


def _protected(real: str) -> bool:
    return os.path.normcase(real) in PROTECTED_FILES


def _maybe_protected(full: str) -> bool:
    """검색용 빠른 판정: 이름이 같을 때만 realpath 로 확인한다 / quick check for search, realpath only on a name match"""
    name = os.path.normcase(os.path.basename(full))
    if not any(os.path.basename(p) == name for p in PROTECTED_FILES):
        return False
    try:
        return _protected(os.path.realpath(full))
    except (OSError, ValueError):
        return False


def _guard_protected(real: str) -> None:
    if _protected(real):
        raise ExecError("이 서버의 비밀 설정 파일은 열 수 없습니다")


def in_git_dir(real: str) -> bool:
    """realpath 의 경로 구성 요소에 .git 이 있는가(<폴더>/.git/… · 하위 저장소의 …/.git/… · .git 파일 자체). Windows 는 대소문자 ·
    끝의 점 · 공백 · ':' 뒤 스트림 이름을 무시한다(.GIT · '.git.' · '.git::$DATA' 도 같은 폴더를 연다).
    Does a component of the realpath name .git (the folder's own, a nested repository's, or a .git file itself)? On
    Windows case, trailing dots and spaces and an NTFS stream suffix are ignored, since they open the same folder."""
    for part in re.split(r"[\\/]+", str(real or "")):
        name = part
        if os.name == "nt":
            name = name.split(":", 1)[0].rstrip(" .").lower()
        if name == ".git":
            return True
    return False


def _guard_git_internal(real: str) -> None:
    """저장소 내부(.git) 쓰기 · 편집 거절(적대 검토 H1: .git/config 의 filter · fsmonitor · hooks 를 고치면 체크포인트의 git add 가
    다음 턴에 명령을 돌린다). 읽기 · 검색은 막지 않는다.
    Refuse writes and edits inside a repository's .git (adversarial review H1: a changed filter, fsmonitor or hook in
    .git would make the checkpoint's git add run a command next turn). Reads and searches stay allowed."""
    if in_git_dir(real):
        raise RefusedError(GIT_INTERNAL)


def _iso(ts: float) -> str:
    return kst.from_epoch(ts).isoformat(timespec="seconds")


def matches_deny(command: str, patterns) -> str | None:
    """명령이 걸리는 첫 차단 정규식(대소문자 무시), 없으면 None. 컴파일 안 되는 정규식은 건너뛴다.
    The first denied-command pattern the command matches (case-insensitive) or None; broken patterns are skipped."""
    cmd = str(command or "")
    for p in patterns or []:
        try:
            if re.search(str(p), cmd, re.IGNORECASE):
                return str(p)
        except re.error:
            continue
    return None


# ────────────────────────────────────────────────────────
# 글자 · diff / text and diffs
# ────────────────────────────────────────────────────────

def _decode_text(data: bytes) -> tuple[str, str, bool]:
    """바이트 → (본문, 인코딩, 손실 여부). NUL 이 있으면 이진으로 보고 ExecError. UTF-8 → cp949 → 대체 문자 순.
    Bytes → (text, encoding, lossy). A NUL byte means binary (ExecError). UTF-8, then cp949, then replacement."""
    if data.startswith(codecs.BOM_UTF8):
        try:
            return data[3:].decode("utf-8"), "utf-8-sig", False
        except UnicodeDecodeError:
            return data[3:].decode("utf-8", errors="replace"), "utf-8-sig", True
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return data.decode("utf-16"), "utf-16", False
        except UnicodeDecodeError:
            pass
    if b"\x00" in data[:8192]:
        raise ExecError("이진 파일은 읽을 수 없습니다")
    try:
        return data.decode("utf-8"), "utf-8", False
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp949"), "cp949", False
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace"), "utf-8", True


def _encode_text(text: str, encoding: str) -> bytes:
    if encoding == "utf-8-sig":
        return codecs.BOM_UTF8 + text.encode("utf-8")
    if encoding == "utf-16":
        return text.encode("utf-16")
    if encoding == "cp949":
        try:
            return text.encode("cp949")
        except UnicodeEncodeError as e:
            raise ExecError("이 파일의 인코딩(cp949)으로 쓸 수 없는 글자가 있습니다") from e
    return text.encode("utf-8")


def is_binary(path: str) -> bool:
    """앞 8KB 에 NUL 이 있으면 이진(UTF-16 BOM 은 글) / binary when the first 8 KB hold a NUL byte (UTF-16 BOM is text)"""
    try:
        with open(path, "rb") as f:
            head = f.read(8192)
    except OSError:
        return False
    if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return False
    return b"\x00" in head


def read_preview(real: str, max_bytes: int, max_chars: int) -> dict:
    """화면 미리보기용 읽기: 앞 max_bytes 만 읽고, 이진이면 binary=True(본문 없음).
    A preview read for the screen: only the first max_bytes; binary files come back as binary=True without content."""
    size = os.path.getsize(real)
    with open(real, "rb") as f:
        data = f.read(max_bytes)
    partial = size > len(data)
    text = None
    if partial and not data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) and b"\x00" not in data[:8192]:
        for k in range(4):   # 잘린 마지막 UTF-8 글자를 뺀다 / drop a cut last UTF-8 character
            try:
                text = data[:len(data) - k].decode("utf-8")
                break
            except UnicodeDecodeError:
                continue
    if text is None:
        try:
            text = _decode_text(data)[0]
        except ExecError:
            return {"binary": True, "size": size, "truncated": False}
    text = text.replace("\r\n", "\n")
    return {"binary": False, "content": text[:max_chars], "truncated": partial or len(text) > max_chars, "size": size}


def read_rows(text: str, offset, limit) -> tuple[str, int, int, int, bool]:
    """read_file 의 줄 자르기: 본문 → (줄 번호를 붙인 글, 전체 줄 수, 시작 줄, 끝 줄, 글자 상한에서 잘렸나). offset 은 1부터,
    limit 은 READ_MAX_LINES 상한, 한 줄은 LINE_MAX_CHARS, 글은 READ_MAX_CHARS 상한(상수는 부를 때 읽는다).
    read_file's slicing: text → (numbered rows, total lines, start, end, cut at the character cap). offset starts at 1,
    limit is capped at READ_MAX_LINES, one line at LINE_MAX_CHARS and the text at READ_MAX_CHARS (read at call time)."""
    lines = str(text if text is not None else "").splitlines()
    total = len(lines)
    start = _clamp(offset, 1, max(1, total + 1), default=1)
    count = _clamp(limit, 1, READ_MAX_LINES, default=READ_DEFAULT_LINES)
    rows, used, truncated = [], 0, False
    for n, line in enumerate(lines[start - 1:start - 1 + count], start):
        if len(line) > LINE_MAX_CHARS:
            line = line[:LINE_MAX_CHARS] + " …(줄이 길어 잘림)"
        row = f"{n:6d}\t{line}"
        if used + len(row) + 1 > READ_MAX_CHARS:
            truncated = True
            break
        rows.append(row)
        used += len(row) + 1
    end = start + len(rows) - 1
    return "\n".join(rows), total, start, end, truncated


def compute_edit(text: str, old_string, new_string, replace_all: bool = False) -> tuple[str, int]:
    """edit_file 의 바꾸기 규칙 → (바꾼 본문, 바꾼 곳 수). old_string 이 비었거나 new_string 과 같으면 ExecError. CRLF 본문에 LF 로
    준 글은 CRLF 로 맞춰 본 뒤 없으면 그대로 다시 본다. 0곳이면 ExecError, 여러 곳인데 replace_all 이 아니면 ExecError.
    edit_file's replacement rules → (updated text, places replaced). An empty old_string or one equal to new_string is
    an ExecError. LF strings against a CRLF text are tried as CRLF first, then as given. Zero matches is an ExecError,
    and so are several matches without replace_all."""
    old = "" if old_string is None else str(old_string)
    new = "" if new_string is None else str(new_string)
    if not old:
        raise ExecError("old_string 이 비어 있습니다")
    if old == new:
        raise ExecError("old_string 과 new_string 이 같습니다")
    o, n = old, new
    if "\r\n" in text and "\r\n" not in old:   # CRLF 파일에 LF 로 준 경우 / LF strings against a CRLF file
        o, n = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
    count = text.count(o)
    if count == 0 and o != old:
        o, n = old, new
        count = text.count(o)
    if count == 0:
        raise ExecError("old_string 을 파일에서 찾지 못했습니다. read_file 로 지금 내용을 확인한 뒤 정확히 옮겨 쓰세요")
    if count > 1 and not replace_all:
        raise ExecError(f"old_string 이 {count}곳과 일치합니다. 앞뒤 줄을 더 넣어 한 곳만 맞게 하거나 replace_all=true 를 쓰세요")
    updated = text.replace(o, n) if replace_all else text.replace(o, n, 1)
    return updated, (count if replace_all else 1)


def unified_diff(label: str, old: str, new: str) -> tuple[str, int, int]:
    """unified diff(줄바꿈은 LF 로 맞춰 비교) → (본문, 더한 줄, 뺀 줄) / unified diff with LF-normalized lines → (text, added, removed)"""
    a = old.replace("\r\n", "\n").splitlines(keepends=True)
    b = new.replace("\r\n", "\n").splitlines(keepends=True)
    lines = list(difflib.unified_diff(a, b, fromfile=f"a/{label}", tofile=f"b/{label}", n=3))
    added = removed = 0
    out = []
    for i, line in enumerate(lines):
        if not line.endswith("\n"):
            line += "\n"
        if i >= 2:   # 앞 두 줄은 머리(---, +++) / the first two lines are the headers
            if line.startswith("+"):
                added += 1
            elif line.startswith("-"):
                removed += 1
        out.append(line)
    return "".join(out), added, removed


def _glob_body(pat: str) -> str:
    out, i, n = [], 0, len(pat)
    while i < n:
        c = pat[i]
        if c == "*":
            if pat.startswith("**", i):
                if pat.startswith("/", i + 2):   # '**/' = 0개 이상의 폴더 / zero or more folders
                    out.append("(?:.*/)?")
                    i += 3
                    continue
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = pat.find("]", i + 1)
            if j < 0:
                out.append(re.escape(c))
            else:
                cls = pat[i + 1:j]
                if cls.startswith("!"):
                    cls = "^" + cls[1:]
                out.append("[" + cls.replace("\\", "\\\\") + "]")
                i = j + 1
                continue
        elif c == "{":
            j = pat.find("}", i + 1)
            if j < 0:
                out.append(re.escape(c))
            else:
                out.append("(?:" + "|".join(_glob_body(a) for a in pat[i + 1:j].split(",")) + ")")
                i = j + 1
                continue
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


def glob_regex(pattern: str) -> re.Pattern:
    """glob 패턴(**, *, ?, [...], {a,b}) → 정규식. 경로 구분자는 '/', Windows 는 대소문자 무시.
    A glob pattern → a regex over '/'-separated relative paths; case-insensitive on Windows."""
    pat = str(pattern or "").replace("\\", "/")
    try:
        return re.compile("^" + _glob_body(pat) + "$", re.IGNORECASE if os.name == "nt" else 0)
    except re.error as e:
        raise ExecError(f"pattern 이 올바르지 않습니다: {e}") from e


def _skip_dirs(pattern: str) -> frozenset:
    named = set(str(pattern or "").replace("\\", "/").split("/"))
    return frozenset(d for d in SKIP_DIRS if d not in named)


# ────────────────────────────────────────────────────────
# 명령 출력 · 프로세스 / command output and processes
# ────────────────────────────────────────────────────────

def _decode_out(b: bytes) -> str:
    if not b:
        return ""
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        pass
    enc = locale.getpreferredencoding(False) or "utf-8"
    try:
        return b.decode(enc)
    except (UnicodeDecodeError, LookupError):
        return b.decode("utf-8", errors="replace")


class _Output:
    """명령 출력 모으기: 앞 · 뒤를 각각 상한까지만 들고(메모리 보호), 글자 상한을 넘으면 가운데를 생략한다.
    Collects command output: head and tail are kept up to a cap each (memory bound), and the middle is omitted when the
    text exceeds the character cap."""

    def __init__(self, max_chars: int):
        self.max_chars = max(200, int(max_chars))
        self.cap = self.max_chars * 4
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0
        self.lock = threading.Lock()

    def feed(self, chunk: bytes) -> None:
        with self.lock:
            self.total += len(chunk)
            room = self.cap - len(self.head)
            if room > 0:
                self.head += chunk[:room]
                chunk = chunk[room:]
            if chunk:
                self.tail += chunk
                if len(self.tail) > self.cap:
                    del self.tail[:len(self.tail) - self.cap]

    def text(self) -> tuple[str, bool]:
        with self.lock:
            head, tail, total = bytes(self.head), bytes(self.tail), self.total
        dropped = total - len(head) - len(tail)
        if dropped <= 0:
            s = _decode_out(head + tail)
        else:
            k = 0
            while k < min(3, len(tail)) and 0x80 <= tail[k] <= 0xBF:   # 잘린 UTF-8 이음 바이트 / cut UTF-8 continuation bytes
                k += 1
            s = _decode_out(head) + _decode_out(tail[k:])
        s = s.replace("\r\n", "\n")
        if len(s) <= self.max_chars and dropped <= 0:
            return s, False
        mark = f"\n… (출력이 길어 가운데를 생략했습니다. 전체 {total:,}바이트) …\n"
        half = max(1, (self.max_chars - len(mark)) // 2)   # 표시까지 합쳐 max_chars 안 / the marker counts toward max_chars
        return s[:half] + mark + s[-half:], True


def _pump(stream, out: _Output) -> None:
    try:
        while True:
            chunk = stream.read1(65536)
            if not chunk:
                break
            out.feed(chunk)
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _child_env() -> dict:
    """자식 환경 = 서버 환경 - 비밀 변수(API 키 · 토큰 · 비밀번호 · GEMINI_*) / the server environment minus secrets"""
    env = {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _spawn(command: str, cwd: str) -> subprocess.Popen:
    """명령 시작: Windows = "cmd" /d /s /c "<명령>"(따옴표를 그대로 넘긴다), 그 밖 = /bin/sh -c (새 세션).
    Start a command: on Windows "cmd" /d /s /c "<command>" (quotes pass through as typed), elsewhere /bin/sh -c in a new session."""
    env = _child_env()
    if os.name == "nt":
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        return subprocess.Popen(f'"{comspec}" /d /s /c "{command}"', cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=_NO_WINDOW)
    return subprocess.Popen(["/bin/sh", "-c", command], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)


def _kill_tree(proc: subprocess.Popen) -> None:
    """프로세스와 그 자식까지 끝낸다(Windows = taskkill /T, 그 밖 = 프로세스 그룹) / kill the process and its children"""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=15, creationflags=_NO_WINDOW)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass


@dataclass
class _Bg:
    task_id: str
    session_id: str
    proc: subprocess.Popen
    out: _Output
    killed: threading.Event = field(default_factory=threading.Event)


_BG: dict[str, _Bg] = {}
_BG_LOCK = threading.Lock()


def _watch_bg(bg: _Bg, limit_sec: int) -> None:
    """background 명령을 끝까지 지켜보며 작업 행을 갱신한다(출력은 BG_FLUSH_SEC 마다) / watch a background command to the end"""
    reader = threading.Thread(target=_pump, args=(bg.proc.stdout, bg.out), daemon=True, name=f"ai365-agentic-out-{bg.task_id}")
    reader.start()
    deadline = time.monotonic() + limit_sec
    last_flush = time.monotonic()
    note = ""
    try:
        while True:
            try:
                bg.proc.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                pass
            if bg.killed.is_set():
                _kill_tree(bg.proc)
                break
            if time.monotonic() >= deadline:
                note = f"시간 초과({limit_sec}초)로 끝냈습니다"
                _kill_tree(bg.proc)
                break
            if time.monotonic() - last_flush >= BG_FLUSH_SEC:
                last_flush = time.monotonic()
                try:
                    agentic_store.update_task(bg.task_id, output=bg.out.text()[0])
                except Exception:  # noqa: BLE001 (갱신 실패가 작업을 멈추지 않는다 / a failed update never stops the task)
                    logger.warning("background 출력 갱신 실패 task=%s", bg.task_id, exc_info=True)
        try:
            bg.proc.wait(timeout=JOIN_SEC)
        except subprocess.TimeoutExpired:
            pass
        reader.join(timeout=JOIN_SEC)
    finally:
        text, _ = bg.out.text()
        code = bg.proc.returncode
        if bg.killed.is_set():
            status, note = "stopped", note or "중지했습니다"
        elif note:
            status = "stopped"
        else:
            status = "done" if code == 0 else "error"
        if note:
            text = (text + "\n" if text else "") + f"[{note}]"
        try:
            agentic_store.update_task(bg.task_id, status=status, ended=kst.now_iso(), output=text, exit_code=code)
        except Exception:  # noqa: BLE001
            logger.warning("background 작업 마감 기록 실패 task=%s", bg.task_id, exc_info=True)
        with _BG_LOCK:
            _BG.pop(bg.task_id, None)


def live_task(task_id: str) -> dict | None:
    """이 프로세스에서 도는 background 작업의 지금 출력 {status, output, truncated}, 없으면 None / live output, else None"""
    with _BG_LOCK:
        bg = _BG.get(task_id)
    if bg is None:
        return None
    text, truncated = bg.out.text()
    return {"status": "running", "output": text, "truncated": truncated, "session": bg.session_id}


def kill_task(task_id: str) -> bool:
    """background 작업 중지 / stop a background task"""
    with _BG_LOCK:
        bg = _BG.get(task_id)
    if bg is None:
        return False
    bg.killed.set()
    _kill_tree(bg.proc)
    return True


def kill_session_tasks(session_id: str) -> int:
    """세션의 background 작업을 모두 중지 / stop every background task of a session"""
    with _BG_LOCK:
        ids = [tid for tid, bg in _BG.items() if bg.session_id == session_id]
    return sum(1 for tid in ids if kill_task(tid))


def live_session_tasks(session_id: str) -> int:
    """이 프로세스에서 도는 그 세션의 background 작업 수(복원 · 커밋 전 확인, 적대 검토 L7)
    Running background tasks of a session in this process (checked before restore and commit, adversarial review L7)"""
    with _BG_LOCK:
        return sum(1 for bg in _BG.values() if bg.session_id == session_id)


def _git_branch(folder: str) -> str | None:
    """git rev-parse --abbrev-ref HEAD(5초), 실패하면 None / the current branch, None on failure"""
    git = shutil.which("git")
    if not git:
        return None
    try:
        r = subprocess.run([git, "rev-parse", "--abbrev-ref", "HEAD"], cwd=folder, capture_output=True, timeout=5,
                           creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", errors="replace").strip() or None


def git_info(folder: str) -> dict:
    """세션 폴더 안에 .git 이 있고 git 이 있을 때만 브랜치를 읽는다. 아니면 {"repo": False}.
    Reads the branch only when the folder holds .git and git is installed; {"repo": False} otherwise."""
    try:
        if not os.path.exists(os.path.join(folder, ".git")):
            return {"repo": False}
    except (OSError, ValueError):
        return {"repo": False}
    branch = _git_branch(folder)
    return {"repo": True, "branch": branch} if branch else {"repo": False}


# ────────────────────────────────────────────────────────
# 실행기 / executors
# ────────────────────────────────────────────────────────

class Executor(ABC):
    """실행 위치 인터페이스(1차 = LocalExecutor) / where tools run (phase 1 = LocalExecutor)"""

    folder: str

    @abstractmethod
    def resolve(self, path, allow_outside: bool = False) -> str: ...

    @abstractmethod
    def read(self, path, offset: int = 1, limit: int = READ_DEFAULT_LINES, allow_outside: bool = False) -> dict: ...

    @abstractmethod
    def write(self, path, content, allow_outside: bool = False) -> dict: ...

    @abstractmethod
    def edit(self, path, old_string, new_string, replace_all: bool = False, allow_outside: bool = False) -> dict: ...

    @abstractmethod
    def list_dir(self, path=None, allow_outside: bool = False) -> dict: ...

    @abstractmethod
    def glob(self, pattern, path=None, allow_outside: bool = False) -> dict: ...

    @abstractmethod
    def grep(self, pattern, path=None, glob=None, max_results: int = GREP_DEFAULT, allow_outside: bool = False) -> dict: ...

    @abstractmethod
    def run(self, command, timeout_sec=None, background: bool = False) -> dict: ...

    @abstractmethod
    def task_output(self, task_id) -> dict: ...

    def cancel_running(self) -> None:
        """앞에서 도는 명령을 끝낸다(중단 버튼) / kill the foreground command (stop button)"""


class LocalExecutor(Executor):
    """이 서버 PC 에서 허용 폴더 안의 파일과 명령을 다룬다 / files and commands on this server PC, inside the allowed folders"""

    def __init__(self, folder: str, allowed=None, *, session_id: str = "", bash_timeout: int = 120,
                 max_output: int = 20000, bg_max_sec: int = 7200):
        self.folder = os.path.realpath(str(folder))
        roots, seen = [], set()
        for r in [self.folder, *(allowed or [])]:
            if not r:
                continue
            real = os.path.realpath(str(r))
            if os.path.normcase(real) not in seen:
                seen.add(os.path.normcase(real))
                roots.append(real)
        self.allowed = roots
        self.session_id = session_id
        self.bash_timeout = _clamp(bash_timeout, 1, MAX_TIMEOUT_SEC)
        self.max_output = max(200, int(max_output))
        self.bg_max_sec = max(1, int(bg_max_sec))
        self._fg: subprocess.Popen | None = None
        self._cancelled = False   # 중단이 먼저 오면 명령을 시작하지 않는다 / a stop that comes first prevents the start
        self._lock = threading.Lock()

    # ── 경로 / paths ──
    def resolve(self, path, allow_outside: bool = False) -> str:
        real = real_target(self.folder, path)
        if not allow_outside and not inside(real, self.allowed):
            raise OutsideError(f"허용 폴더 밖 경로입니다: {real}")
        return real

    def rel(self, real: str) -> str:
        """세션 폴더 기준 상대 경로(밖이면 절대 경로) / relative to the session folder, absolute when outside"""
        if inside(real, [self.folder]):
            r = os.path.relpath(real, self.folder)
            return "." if r == "." else r.replace("\\", "/")
        return real

    # ── 읽기 · 쓰기 · 편집 / read, write, edit ──
    def _text_file(self, real: str) -> tuple[str, str, bool, int]:
        _guard_protected(real)
        if not os.path.exists(real):
            raise ExecError(f"파일이 없습니다: {self.rel(real)}")
        if os.path.isdir(real):
            raise ExecError(f"폴더입니다(list_dir 를 쓰세요): {self.rel(real)}")
        size = os.path.getsize(real)
        if size > MAX_FILE_BYTES:
            raise ExecError(f"파일이 너무 큽니다(10MB 초과, {size:,}바이트): {self.rel(real)}")
        try:
            with open(real, "rb") as f:
                data = f.read()
        except OSError as e:
            raise ExecError(f"파일을 읽지 못했습니다: {e}") from e
        text, enc, lossy = _decode_text(data)
        return text, enc, lossy, size

    def read(self, path, offset: int = 1, limit: int = READ_DEFAULT_LINES, allow_outside: bool = False) -> dict:
        real = self.resolve(path, allow_outside)
        text, enc, _lossy, size = self._text_file(real)
        body, total, start, end, truncated = read_rows(text, offset, limit)
        return {"path": real, "rel": self.rel(real), "text": body, "lines": total, "start": start,
                "end": end, "truncated": truncated, "more": end < total, "size": size, "encoding": enc}

    def write(self, path, content, allow_outside: bool = False) -> dict:
        if path is None or not str(path).strip():
            raise ExecError("path 가 비어 있습니다")
        _guard_git_internal(real_target(self.folder, path))   # 허용 폴더 검사보다 먼저(늘 같은 거절) / before the folder check
        real = self.resolve(path, allow_outside)
        _guard_protected(real)
        if os.path.isdir(real):
            raise ExecError(f"폴더입니다: {self.rel(real)}")
        text = "" if content is None else str(content)
        data = text.encode("utf-8")
        if len(data) > MAX_FILE_BYTES:
            raise ExecError("내용이 너무 큽니다(10MB 초과)")
        existed = os.path.exists(real)
        old = None
        if existed:
            try:
                if os.path.getsize(real) <= MAX_FILE_BYTES:
                    with open(real, "rb") as f:
                        old = _decode_text(f.read())[0]
            except (OSError, ExecError):
                old = None   # 이진 파일을 덮어쓰면 diff 없음 / no diff when overwriting a binary file
        try:
            os.makedirs(os.path.dirname(real), exist_ok=True)
            with open(real, "wb") as f:
                f.write(data)
        except OSError as e:
            raise ExecError(f"파일을 쓰지 못했습니다: {e}") from e
        out = {"path": real, "rel": self.rel(real), "bytes": len(data), "created": not existed,
               "diff": None, "added": 0, "removed": 0}
        if existed and old is not None:
            diff, added, removed = unified_diff(out["rel"], old, text)
            out.update(diff=diff, added=added, removed=removed)
        return out

    def edit(self, path, old_string, new_string, replace_all: bool = False, allow_outside: bool = False) -> dict:
        _guard_git_internal(real_target(self.folder, path))   # 허용 폴더 검사보다 먼저(늘 같은 거절) / before the folder check
        real = self.resolve(path, allow_outside)
        text, enc, lossy, _size = self._text_file(real)
        if lossy:
            raise ExecError("인코딩을 알 수 없어 편집할 수 없습니다(write_file 로 다시 쓰세요)")
        updated, replaced = compute_edit(text, old_string, new_string, replace_all)
        data = _encode_text(updated, enc)
        try:
            with open(real, "wb") as f:
                f.write(data)
        except OSError as e:
            raise ExecError(f"파일을 쓰지 못했습니다: {e}") from e
        rel = self.rel(real)
        diff, added, removed = unified_diff(rel, text, updated)
        return {"path": real, "rel": rel, "replaced": replaced, "diff": diff,
                "added": added, "removed": removed}

    # ── 목록 · 찾기 · 검색 / list, glob, grep ──
    def list_dir(self, path=None, allow_outside: bool = False) -> dict:
        real = self.resolve(path, allow_outside)
        if not os.path.isdir(real):
            raise ExecError(f"폴더가 아닙니다: {self.rel(real)}" if os.path.exists(real) else f"폴더가 없습니다: {self.rel(real)}")
        entries = []
        try:
            with os.scandir(real) as it:
                for e in it:
                    try:
                        is_dir = e.is_dir(follow_symlinks=False)
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    entries.append({"name": e.name, "type": "dir" if is_dir else "file",
                                    "size": 0 if is_dir else int(st.st_size), "mtime": _iso(st.st_mtime)})
        except OSError as e:
            raise ExecError(f"폴더를 읽지 못했습니다: {e}") from e
        entries.sort(key=lambda x: (x["type"] != "dir", x["name"].lower()))
        return {"path": real, "rel": self.rel(real), "entries": entries[:MAX_LIST], "total": len(entries),
                "truncated": len(entries) > MAX_LIST}

    def _walk(self, base: str, pattern: str = ""):
        """(전체 경로, base 기준 상대 경로). 무거운 폴더(.git · node_modules 등)는 건너뛴다 / walk, pruning heavy folders"""
        if os.path.isfile(base):
            yield base, os.path.basename(base)
            return
        skip = _skip_dirs(pattern)
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in skip]
            rel_root = os.path.relpath(root, base)
            prefix = "" if rel_root == "." else rel_root.replace("\\", "/") + "/"
            for name in files:
                yield os.path.join(root, name), prefix + name

    def glob(self, pattern, path=None, allow_outside: bool = False) -> dict:
        pat = str(pattern or "").strip().replace("\\", "/")
        while pat.startswith("./"):
            pat = pat[2:]
        if not pat:
            raise ExecError("pattern 이 비어 있습니다")
        if pat.startswith("/") or re.match(r"^[A-Za-z]:", pat) or ".." in pat.split("/"):
            raise ExecError("pattern 에는 절대 경로나 .. 을 쓸 수 없습니다. 시작 폴더는 path 로 주세요")
        base = self.resolve(path, allow_outside)
        if not os.path.isdir(base):
            raise ExecError(f"폴더가 없습니다: {self.rel(base)}")
        rx = glob_regex(pat)
        hits, scanned, capped = [], 0, False
        for full, rel in self._walk(base, pat):   # 패턴은 path 기준으로 맞춘다 / the pattern matches relative to `path`
            scanned += 1
            if scanned > SCAN_MAX:
                capped = True
                break
            if rx.match(rel):
                try:
                    mt = os.stat(full).st_mtime
                except OSError:
                    mt = 0.0
                hits.append((mt, rel, full))
        hits.sort(key=lambda h: (-h[0], h[1]))
        # 돌려주는 경로는 세션 폴더 기준(밖이면 절대 경로) / returned paths are relative to the session folder (absolute outside it)
        return {"base": base, "rel_base": self.rel(base), "paths": [self.rel(h[2]) for h in hits[:MAX_GLOB]],
                "count": len(hits), "truncated": capped or len(hits) > MAX_GLOB, "scan_capped": capped}

    def grep(self, pattern, path=None, glob=None, max_results: int = GREP_DEFAULT, allow_outside: bool = False) -> dict:
        pat = "" if pattern is None else str(pattern)
        if not pat:
            raise ExecError("pattern 이 비어 있습니다")
        try:
            rx = re.compile(pat)
        except re.error as e:
            raise ExecError(f"정규식 오류: {e}") from e
        base = self.resolve(path, allow_outside)
        if not os.path.exists(base):
            raise ExecError(f"경로가 없습니다: {self.rel(base)}")
        mx = _clamp(max_results, 1, GREP_MAX, default=GREP_DEFAULT)
        g = str(glob or "").strip().replace("\\", "/")
        name_rx = glob_regex(g) if g else None
        by_path = "/" in g
        matches: list[str] = []
        files_hit = scanned = 0
        truncated = False
        deadline = time.monotonic() + GREP_TIME_SEC
        for full, rel in self._walk(base, g):
            scanned += 1
            if scanned > SCAN_MAX or time.monotonic() > deadline:
                truncated = True
                break
            if name_rx is not None and not name_rx.match(rel if by_path else rel.rsplit("/", 1)[-1]):
                continue
            if _maybe_protected(full):
                continue
            try:
                if os.path.getsize(full) > GREP_FILE_BYTES:
                    continue
                with open(full, "rb") as f:
                    data = f.read()
                text = _decode_text(data)[0]
            except (OSError, ExecError):
                continue
            hit = False
            shown = None   # 세션 폴더 기준 경로(일치한 파일만 계산) / session-relative path, computed for hits only
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    shown = shown or self.rel(full)
                    matches.append(f"{shown}:{i}:{line[:GREP_LINE_CHARS]}")
                    hit = True
                    if len(matches) >= mx:
                        truncated = True
                        break
            files_hit += int(hit)
            if len(matches) >= mx:
                break
        return {"base": base, "rel_base": self.rel(base), "matches": matches, "count": len(matches), "files": files_hit,
                "truncated": truncated}

    # ── 명령 / commands ──
    def run(self, command, timeout_sec=None, background: bool = False) -> dict:
        cmd = str(command or "").strip()
        if not cmd:
            raise ExecError("command 가 비어 있습니다")
        if "\x00" in cmd:
            raise ExecError("명령이 올바르지 않습니다")
        if background:
            return self._start_background(cmd, timeout_sec)
        timeout = _clamp(timeout_sec, 1, MAX_TIMEOUT_SEC, default=self.bash_timeout) if timeout_sec else self.bash_timeout
        out = _Output(self.max_output)
        t0 = time.monotonic()
        with self._lock:
            if self._cancelled:
                raise ExecError("중단되었습니다")
        try:
            proc = _spawn(cmd, self.folder)
        except OSError as e:
            raise ExecError(f"명령을 시작하지 못했습니다: {e}") from e
        with self._lock:
            self._fg = proc
            cancelled = self._cancelled
        if cancelled:   # 시작하는 사이에 중단이 왔다 / the stop arrived while starting
            _kill_tree(proc)
        reader = threading.Thread(target=_pump, args=(proc.stdout, out), daemon=True, name="ai365-agentic-out")
        reader.start()
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            try:
                proc.wait(timeout=JOIN_SEC)
            except subprocess.TimeoutExpired:
                pass
        finally:
            with self._lock:
                self._fg = None
        reader.join(timeout=JOIN_SEC)
        text, truncated = out.text()
        return {"output": text, "exit_code": None if timed_out else proc.returncode, "timed_out": timed_out,
                "truncated": truncated, "duration_ms": int((time.monotonic() - t0) * 1000), "timeout_sec": timeout}

    def _start_background(self, cmd: str, timeout_sec) -> dict:
        """background 명령: 작업 행을 만들고 스레드가 지켜본다. 시간 상한 = timeout_sec(주면) 또는 세션 시간 예산.
        A background command: create the task row and let a thread watch it; the time cap is timeout_sec when given,
        else the session time budget."""
        if not self.session_id:
            raise ExecError("세션 없이 background 명령을 띄울 수 없습니다")
        limit = _clamp(timeout_sec, 1, self.bg_max_sec, default=self.bg_max_sec) if timeout_sec else self.bg_max_sec
        task = agentic_store.create_task(self.session_id, "bash", cmd)
        try:
            proc = _spawn(cmd, self.folder)
        except OSError as e:
            agentic_store.update_task(task["id"], status="error", ended=kst.now_iso(), output=f"명령을 시작하지 못했습니다: {e}")
            raise ExecError(f"명령을 시작하지 못했습니다: {e}") from e
        bg = _Bg(task["id"], self.session_id, proc, _Output(self.max_output))
        with _BG_LOCK:
            _BG[task["id"]] = bg
        threading.Thread(target=_watch_bg, args=(bg, limit), daemon=True, name=f"ai365-agentic-{task['id']}").start()
        return {"task_id": task["id"], "background": True, "limit_sec": limit}

    def task_output(self, task_id) -> dict:
        tid = str(task_id or "").strip()
        if not tid:
            raise ExecError("task_id 가 비어 있습니다")
        live = live_task(tid)
        if live is not None and (not self.session_id or live["session"] == self.session_id):
            row = agentic_store.get_task(tid, with_output=False) or {}
            return {"task_id": tid, "status": "running", "output": live["output"], "exit_code": None,
                    "truncated": live["truncated"], "label": row.get("label", "")}
        row = agentic_store.get_task(tid, self.session_id or None)
        if row is None:
            raise ExecError(f"작업을 찾을 수 없습니다: {tid}")
        return {"task_id": tid, "status": row["status"], "output": row["output"], "exit_code": row["exit_code"],
                "truncated": False, "label": row["label"]}

    def cancel_running(self) -> None:
        with self._lock:
            self._cancelled = True
            proc = self._fg
        if proc is not None:
            _kill_tree(proc)
