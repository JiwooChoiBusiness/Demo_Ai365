"""Agentic 모드 브라우저 실행기(2026-10-20): '내 컴퓨터 폴더' 세션의 파일 도구를 사용자의 브라우저가 대신 실행한다.

배포 서버(Azure)의 폴더 선택 창(POST /pick-folder)은 사용자의 컴퓨터를 가리킬 수 없다. 그래서 브라우저가 File System Access
API(showDirectoryPicker)로 사용자 PC 의 폴더를 열고(세션 kind = browser, folder = 폴더 이름), 서버는 도구 호출을 원시 op
(list · read · write · walk · grep)로 쪼개 그 브라우저에 보낸다. 서버의 루프(Gemini 함수 호출)는 그대로다.
계약: docs/agentic-browser-folder-contract.md B 절.

- 요청 레지스트리 PENDING(request_id → 요청): request() 는 워커 스레드(run_tool 과 같은 asyncio.to_thread 자리)에서만 부른다.
  EMIT(러너가 임포트 때 거는 agentic_runner.push_transient)로 transient SSE 이벤트 tool_request 를 보내고 threading.Event 를
  기다린다(BROWSER_TIMEOUT_SEC). 루프 스레드에서 부르면 RuntimeError: 답을 넣는 API 도 같은 루프에서 돌아 데드락이 난다.
- resolve(): API(POST …/tool-results)가 브라우저의 답을 넣고 깨운다. 한 요청은 한 번만 받는다(먼저 온 탭의 답, 늦은 답 = done).
  답했거나 시간 초과 · 취소로 끝난 요청은 {request_id, done: true} 를 다시 보내 다른 탭이 대기 안내를 지운다.
- cancel(): 중단 · 세션 삭제 · 턴 정리 때 그 세션의 대기 요청을 모두 실패로 깨운다. 서버 종료 때는 cancel_all() 이 모두 깨운다
  (워커 스레드가 시간 초과까지 종료를 붙잡지 않게).
- BrowserExecutor: LocalExecutor 와 같은 메서드 · 같은 결과 키라 agentic_tools 의 도구 함수가 그대로 쓴다. 경로는 폴더 기준 상대
  경로 그대로('/' 구분, 절대 경로 · '..' 은 거절, 폴더 이름 접두도 벗기지 않는다: 같은 이름의 하위 폴더가 있을 수 있다. 대신 그런
  경로가 없으면 오류 문구에 안내를 붙인다). 줄 자르기(read_rows) · 바꾸기 규칙(compute_edit) · diff · glob 정규식 · 정렬 · 상한은
  서버가 한다. 명령(bash · task_output)은 거절, .git 안 쓰기 · 편집은 거절(LocalExecutor 와 같은 규칙), 문서 · 이진 · 인코딩을 알 수
  없는(U+FFFD) 파일은 편집을 거절한다.
- grep 의 정규식은 서버가 파이썬 re 로 검사한 뒤 js_pattern 으로 브라우저의 JS RegExp(u 없음)에 맞게 옮긴다: 앞머리 플래그 →
  flags, \\A · \\Z · (?P<이름>) · (?P=이름) · {,n} · 맨 앞 ']' · \\a 번역, \\w · \\W 는 한글이 잡히게 넓힌 범위, JS 에 없는 구문
  (주석 · 원자 그룹 · 조건부 · 소유 수량자 · x · a · L 플래그 · \\U · \\N)은 거절. JS 식 (?<이름>) · \\k<이름> 도 받는다(py_pattern).
- 이 모듈은 러너를 임포트하지 않는다(러너가 임포트 때 EMIT 을 건다, 순환 임포트 회피).
"""
# Agentic mode browser executor (2026-10-20): the user's browser runs the file tools of a "folder on my computer" session.
# On the deployed server (Azure) the server-side folder window (POST /pick-folder) cannot reach the user's computer, so the
# browser opens a local folder through the File System Access API (session kind = browser, folder = the folder name) and
# the server splits each tool call into primitive ops (list, read, write, walk, grep) for that browser. The server loop
# (Gemini function calls) is unchanged. Contract: docs/agentic-browser-folder-contract.md section B.
# - The request registry PENDING (request_id → request): request() is called from worker threads only (the same
#   asyncio.to_thread spot as run_tool). It sends the transient SSE event tool_request through EMIT (the runner hooks in
#   agentic_runner.push_transient at import) and waits on a threading.Event (BROWSER_TIMEOUT_SEC). Called on the loop
#   thread it raises RuntimeError: the API that delivers the answer runs on that loop, so it would deadlock.
# - resolve(): the API (POST …/tool-results) stores the browser's answer and wakes the waiter. A request is answered once
#   (the first tab wins, a late answer gets done). Answered, timed-out and cancelled requests send {request_id, done:
#   true} again so other tabs clear their waiting notice.
# - cancel(): a stop, a session deletion or the turn cleanup fails every pending request of the session at once;
#   cancel_all() wakes them all at server shutdown (so worker threads never hold the exit until their timeout).
# - BrowserExecutor: the same methods and result keys as LocalExecutor, so the tool functions of agentic_tools work as
#   they are. Paths stay relative to the folder as given ('/' separated; absolute paths and '..' are refused; a leading
#   folder-name segment is not stripped either, since a same-named subfolder may exist; a missing path of that shape gets
#   a hint in its error). Slicing (read_rows), the replacement rules (compute_edit), diffs, glob regexes, sorting and caps
#   happen on the server. Commands (bash, task_output) are refused, writes and edits inside .git are refused (the
#   LocalExecutor rule), and documents, binaries and files of unknown encoding (U+FFFD) cannot be edited.
# - grep patterns are checked with Python re on the server, then js_pattern adapts them to the browser's JS RegExp (no u
#   flag): leading flags become flags; \A, \Z, (?P<name>), (?P=name), {,n}, a leading ']' and \a are translated; \w and \W
#   become ranges that match Korean; syntax JS lacks (comments, atomic groups, conditionals, possessive quantifiers, the
#   x, a and L flags, \U, \N) is refused. JS-style (?<name>) and \k<name> are accepted too (py_pattern).
# - This module never imports the runner (the runner sets EMIT at import, avoiding an import cycle).

from __future__ import annotations

import asyncio
import atexit
import logging
import re
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime
from typing import Callable

from app import agentic_exec, kst
from app.agentic_exec import ExecError, OutsideError, RefusedError

logger = logging.getLogger("ai365.agentic")

# ── 상수 / constants ──
BROWSER_TIMEOUT_SEC = 120
BROWSER_TIMEOUT_MSG = "브라우저가 응답하지 않습니다. 세션을 연 브라우저 탭이 열려 있고 폴더 접근이 허용되어 있어야 합니다"
RULES_TIMEOUT_SEC = 20
NO_BASH_MSG = "내 컴퓨터 폴더 세션에서는 명령을 실행할 수 없습니다"
NO_EDIT_MSG = "문서 · 이진 파일은 편집할 수 없습니다"
LOSSY_MSG = "인코딩을 알 수 없어 편집할 수 없습니다(write_file 로 다시 쓰세요)"
NO_TEXT_MSG = "문서에서 글자를 뽑지 못했습니다(그림 · 암호 문서일 수 있습니다)"
GIT_INTERNAL_MSG = "저장소 내부(.git) 파일은 도구로 고칠 수 없습니다"
STOPPED_MSG = "중단되었습니다"
SHUTDOWN_MSG = "서버가 종료되었습니다"
BAD_REPLY_MSG = "브라우저의 답이 올바르지 않습니다"
EXEC_FALLBACK_MSG = "브라우저에서 실행하지 못했습니다"
RULE_FILES = ("AGENTS.md", "AI365.md")   # = agentic_runner.RULE_FILES (러너를 임포트하지 않는다 / the runner is not imported)
RULES_CHARS = 20000                      # = agentic_runner.RULES_CHARS
OPS = ("list", "read", "write", "walk", "grep")
READ_ENCODINGS = ("utf-8", "utf-8-sig", "utf-16", "cp949")   # read 답의 encoding 으로 받는 값 / accepted read encodings
ERROR_CODES = ("outside", "notfound", "isdir", "notdir", "binary", "toolarge", "denied", "exec")
FINISHED_KEEP = 2000                     # 끝난 요청 id 를 기억하는 수(늦은 답 = done) / finished ids remembered (late answers → done)

# ── 레지스트리 / registry ──
PENDING: dict[str, dict] = {}            # request_id → {id, session, op, args, created, ts, event, result, error, code, done}
EMIT: Callable[[str, dict], None] | None = None   # 러너가 건다 = agentic_runner.push_transient / set by the runner
_LOCK = threading.Lock()
_FINISHED: OrderedDict[str, str] = OrderedDict()   # 끝난 request_id → 세션 id / finished request ids → session id


class BrowserTimeout(ExecError):
    """브라우저가 시간 안에 답하지 않았다(문구 = BROWSER_TIMEOUT_MSG) / the browser did not answer in time"""


class BrowserOpError(ExecError):
    """브라우저가 오류 코드로 답했다(code = 계약 B2 의 코드, 취소는 'cancel') / the browser answered with an error code"""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = str(code or "")


def is_browser(session) -> bool:
    """내 컴퓨터 폴더(브라우저) 세션인가 / is this a browser-folder session"""
    return isinstance(session, dict) and session.get("kind") == "browser"


def server_folder(session):
    """서버 폴더를 받는 함수(명령 · 스킬 · 규칙 · 훅 · git)에 줄 폴더: 브라우저 세션은 None(서버에 그 폴더가 없다)
    The folder for functions that take a server folder (commands, skills, rules, hooks, git): None for browser sessions,
    since the folder is not on the server"""
    if is_browser(session):
        return None
    return (session or {}).get("folder")


def _on_loop_thread() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _emit(session_id: str, payload: dict) -> None:
    fn = EMIT
    if fn is None:
        return
    try:
        fn(session_id, payload)
    except Exception:  # noqa: BLE001 (알림 실패가 요청을 막지 않는다 · 화면은 GET tool-requests 로도 받는다)
        logger.warning("Agentic 브라우저 요청 알림 실패 session=%s", session_id, exc_info=True)


def _remember(request_id: str, session_id: str) -> None:
    """끝난 요청 기록(_LOCK 안에서 부른다) / record a finished request (call under _LOCK)"""
    _FINISHED[request_id] = session_id
    _FINISHED.move_to_end(request_id)
    while len(_FINISHED) > FINISHED_KEEP:
        _FINISHED.popitem(last=False)


def _shown(path) -> str:
    s = str(path if path is not None else "")
    return s or "."


def _message(op: str, args: dict, code, error) -> str:
    """오류 코드 → 서버 문구(계약 B2). exec · 모르는 코드는 브라우저 문구 그대로 / an error code → the server wording"""
    p = _shown((args or {}).get("path"))
    c = str(code or "")
    if c == "outside":
        return f"폴더 밖 경로는 쓸 수 없습니다: {p}"
    if c == "notfound":
        if op in ("list", "walk"):
            return f"폴더가 없습니다: {p}"
        if op == "grep":
            return f"경로가 없습니다: {p}"
        return f"파일이 없습니다: {p}"
    if c == "isdir":
        return f"폴더입니다: {p}"
    if c == "notdir":
        return f"폴더가 아닙니다: {p}"
    if c == "binary":
        return "이진 파일은 읽을 수 없습니다"
    if c == "toolarge":
        return "파일이 너무 큽니다(10MB 초과)"
    if c == "denied":
        return "브라우저가 폴더 접근을 거부했습니다. 화면의 [허용] 을 누르세요"
    if c == "cancel":
        return str(error or "") or STOPPED_MSG
    return str(error or "").strip()[:2000] or EXEC_FALLBACK_MSG


# ────────────────────────────────────────────────────────
# 요청 · 답 / requests and answers
# ────────────────────────────────────────────────────────

def request(session_id: str, op: str, args: dict | None = None, timeout: float | None = None) -> dict:
    """브라우저에 원시 op 하나를 맡기고 답을 기다린다 → result(dict). 워커 스레드에서만(루프 스레드면 RuntimeError).
    오류 답은 코드별 문구의 ExecError, 시간 초과(timeout, 기본 BROWSER_TIMEOUT_SEC 을 부를 때 읽는다)는 BrowserTimeout,
    취소는 그 사유의 ExecError. 끝나면(답 · 시간 초과 · 취소) PENDING 에서 뺀다.
    Hand one primitive op to the browser and wait → the result dict. Worker threads only (RuntimeError on the loop
    thread). An error answer raises ExecError with the code's wording, a timeout (default BROWSER_TIMEOUT_SEC, read at
    call time) BrowserTimeout, a cancel an ExecError with its reason. The request leaves PENDING when it is over."""
    if _on_loop_thread():
        raise RuntimeError("브라우저 요청은 이벤트 루프 스레드에서 부를 수 없습니다(asyncio.to_thread 안에서 부르세요) / "
                           "browser requests cannot run on the event-loop thread")
    if op not in OPS:
        raise ValueError(f"모르는 op 입니다: {op}")
    wait = BROWSER_TIMEOUT_SEC if timeout is None else timeout
    sid = str(session_id or "")
    rid = "br" + uuid.uuid4().hex[:10]
    req = {"id": rid, "session": sid, "op": op, "args": dict(args or {}), "created": time.monotonic(),
           "ts": kst.now_iso(), "event": threading.Event(), "result": None, "error": None, "code": None, "done": False}
    with _LOCK:
        PENDING[rid] = req
    _emit(sid, {"request_id": rid, "session_id": sid, "op": op, "args": req["args"], "ts": req["ts"]})
    req["event"].wait(max(0.0, float(wait)))
    with _LOCK:
        PENDING.pop(rid, None)
        answered = req["done"]
        if not answered:   # 시간 초과: 늦은 답은 done(409) / timed out: a late answer gets done (409)
            req["done"] = True
            _remember(rid, sid)
    if not answered:
        _emit(sid, {"request_id": rid, "done": True})
        raise BrowserTimeout(BROWSER_TIMEOUT_MSG)
    if req["code"] is not None:
        raise BrowserOpError(_message(op, req["args"], req["code"], req["error"]), req["code"])
    res = req["result"]
    return res if isinstance(res, dict) else {}


def resolve(session_id: str, request_id: str, ok: bool, result: dict | None = None, error: str = "", code: str = "") -> str:
    """브라우저의 답(API 가 부른다) → "ok" | "unknown"(모르는 id · 다른 세션, 404) | "done"(이미 끝남, 409).
    답한 요청은 PENDING 에서 빼고 {request_id, done: true} 를 보낸다(다른 탭이 안내를 지운다).
    The browser's answer (called by the API) → "ok", "unknown" (unknown id or another session, 404) or "done" (already
    over, 409). The answered request leaves PENDING and {request_id, done: true} goes out for the other tabs."""
    rid = str(request_id or "")
    sid = str(session_id or "")
    with _LOCK:
        req = PENDING.get(rid)
        if req is None:
            return "done" if _FINISHED.get(rid) == sid else "unknown"
        if req["session"] != sid:
            return "unknown"
        if req["done"]:
            return "done"
        if ok:
            req["result"] = dict(result) if isinstance(result, dict) else {}
        else:
            req["code"] = str(code or "").strip() or "exec"
            req["error"] = str(error or "")
        req["done"] = True
        PENDING.pop(rid, None)
        _remember(rid, sid)
        req["event"].set()
    _emit(sid, {"request_id": rid, "done": True})
    return "ok"


def pending(session_id: str) -> list[dict]:
    """아직 답하지 않은 요청 [{request_id, op, args, ts}] (만든 순서) / unanswered requests in creation order"""
    sid = str(session_id or "")
    with _LOCK:
        rows = [r for r in PENDING.values() if r["session"] == sid and not r["done"]]
    rows.sort(key=lambda r: r["created"])
    return [{"request_id": r["id"], "op": r["op"], "args": r["args"], "ts": r["ts"]} for r in rows]


def _fail_all(rows: list[dict], reason: str) -> None:
    """_LOCK 안에서: 요청들을 취소로 끝내고 깨운다 / under _LOCK: end the requests as cancelled and wake them"""
    for r in rows:
        r["code"], r["error"], r["done"] = "cancel", reason, True
        PENDING.pop(r["id"], None)
        _remember(r["id"], r["session"])
        r["event"].set()


def cancel(session_id: str, reason: str = "") -> int:
    """그 세션의 대기 요청을 모두 실패로 깨운다(중단 · 삭제 · 턴 정리) → 깨운 수 / fail every pending request of a session"""
    sid = str(session_id or "")
    msg = str(reason or "") or STOPPED_MSG
    with _LOCK:
        hit = [r for r in PENDING.values() if r["session"] == sid and not r["done"]]
        _fail_all(hit, msg)
    for r in hit:
        _emit(sid, {"request_id": r["id"], "done": True})
    return len(hit)


def cancel_all(reason: str = "") -> int:
    """모든 대기 요청을 깨운다(서버 종료, 알림은 보내지 않는다) → 깨운 수 / wake every pending request at shutdown (no notices)"""
    with _LOCK:
        hit = [r for r in PENDING.values() if not r["done"]]
        _fail_all(hit, str(reason or "") or SHUTDOWN_MSG)
    return len(hit)


# 서버 종료: 스레드 풀이 워커 스레드를 기다리기 전에 깨운다(threading._register_atexit 는 concurrent.futures 도 쓰는 자리,
# 없으면 atexit) / at shutdown, wake the workers before the thread pool joins them (threading._register_atexit is where
# concurrent.futures hooks in; atexit otherwise)
try:
    (getattr(threading, "_register_atexit", None) or atexit.register)(cancel_all, SHUTDOWN_MSG)
except RuntimeError:   # 이미 종료 중 / already shutting down
    pass


# ────────────────────────────────────────────────────────
# 값 다듬기 / value helpers
# ────────────────────────────────────────────────────────

def _int(v, default: int = 0) -> int:
    if isinstance(v, bool):
        return default
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return default
    return max(0, n)


def _mtime_num(v) -> float:
    """mtime(브라우저 lastModified 밀리초 · 초 · ISO 글) → epoch 초, 모르면 0. 시간대가 없는 ISO 는 KST 벽시계로 본다(서버가 UTC
    호스트여도 같은 값) / an mtime as epoch seconds (0 when unknown); a naive ISO string is read as the KST wall clock, so a
    UTC host gives the same value"""
    if isinstance(v, bool):
        return 0.0
    if isinstance(v, (int, float)):
        x = float(v)
        return x / 1000.0 if x > 1e11 else max(0.0, x)
    if isinstance(v, str) and v.strip():
        try:
            return kst.aware(datetime.fromisoformat(v.strip().replace("Z", "+00:00"))).timestamp()
        except (ValueError, OverflowError, OSError):
            return 0.0
    return 0.0


def _mtime_iso(v) -> str:
    n = _mtime_num(v)
    if n <= 0:
        return v if isinstance(v, str) else ""
    try:
        return kst.from_epoch(n).isoformat(timespec="seconds")
    except (ValueError, OverflowError, OSError):
        return ""


def _text_of(r: dict) -> str:
    """글 답(이진 아님)의 본문. text 가 없거나 문자열이 아니면 빈 파일이 아니라 틀린 답이다(BAD_REPLY_MSG)
    The body of a text (non-binary) answer; a missing or non-string text is a malformed answer, not an empty file"""
    t = r.get("text")
    if not isinstance(t, str):
        raise ExecError(BAD_REPLY_MSG)
    return t


def _clean_rel(raw) -> str:
    """브라우저가 준 상대 경로 다듬기('\\' → '/', 앞 './' · '/' 제거) / tidy a relative path from the browser"""
    s = str(raw if raw is not None else "").replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    return s.lstrip("/")


# ── grep 정규식: 파이썬 re → 브라우저 JS RegExp(u 플래그 없음) / grep regexes: Python re → the browser's JS RegExp (no u) ──
# \w 의 JS 근사: u 없는 JS 의 \w 는 ASCII 뿐이라 한글이 안 잡힌다 → À(U+00C0) 부터 U+FFFF 까지 더한다(\u 이스케이프로 적는다)
# A JS approximation of \w: JS \w without u is ASCII only and misses Korean, so U+00C0 to U+FFFF is added (as \u escapes)
WORD_SET = "A-Za-z0-9_\\u00C0-\\uFFFF"
UNSUPPORTED_MSG = "정규식 오류: 브라우저에서 쓸 수 없는 구문입니다: "
_FLAG_GROUP = re.compile(r"\(\?([a-zA-Z]+)\)")                 # 앞머리 전역 플래그 묶음 / a leading global flag group
_SCOPED_FLAGS = re.compile(r"\(\?([a-zA-Z]*)(?:-([a-zA-Z]*))?:")   # (?i:…) · (?-i:…) · (?:…)
_REPEAT = re.compile(r"\{(\d*)(,?)(\d*)\}")                      # {m} · {m,} · {,n} · {m,n} (파이썬 규칙 / Python's rule)


def _unsupported(what: str) -> ExecError:
    return ExecError(UNSUPPORTED_MSG + what)


def js_pattern(pattern: str) -> tuple[str, str]:
    """파이썬 re 패턴(서버가 re.compile 로 검사한 것) → (JS 패턴, JS 플래그). 브라우저는 new RegExp(패턴, 플래그) 로 쓴다(u 없음).
    (a) 앞머리 전역 플래그 묶음을 모두 벗긴다: i · m · s → 플래그, u 는 버린다(파이썬 str 패턴은 늘 유니코드), x · a · L 은 거절.
    (b) 번역: \\A → ^, \\Z → $, (?P<이름> → (?<이름>, (?P=이름) → \\k<이름>, {,n} → {0,n}, 클래스 맨 앞 ']' → '\\]', \\a → \\x07.
    (c) 거절(UNSUPPORTED_MSG): (?#…) · (?>…) · 조건부 (?( · 소유 수량자(*+ ++ ?+ }+) · x · a · L 플래그 · \\U · \\N · 클래스 안 \\W.
    (d) \\w → [WORD_SET], \\W → [^WORD_SET], 클래스 안 \\w → WORD_SET(괄호 없이). 이스케이프된 \\\\w 는 건드리지 않는다. \\b 는
    그대로(JS 에서는 ASCII 낱말 경계, 시스템 프롬프트가 알린다). 범위 플래그 (?i:…) 는 그대로 넘긴다(u 는 뺀다).
    A Python re pattern (already checked with re.compile) → (JS pattern, JS flags) for new RegExp(pattern, flags), no u.
    (a) Every leading global flag group is stripped: i, m and s become flags, u is dropped (Python str patterns are
    always Unicode), x, a and L are refused. (b) Translations: \\A → ^, \\Z → $, (?P<name> → (?<name>, (?P=name) →
    \\k<name>, {,n} → {0,n}, a class's leading ']' → '\\]', \\a → \\x07. (c) Refused: (?#…), (?>…), conditionals (?(,
    possessive quantifiers, the x, a and L flags, \\U, \\N and \\W inside a class. (d) \\w → [WORD_SET], \\W → [^WORD_SET],
    \\w inside a class → WORD_SET without brackets; an escaped \\\\w stays. \\b stays (an ASCII word boundary in JS; the
    system prompt says so). Scoped flags (?i:…) pass through (u removed)."""
    s = str(pattern if pattern is not None else "")
    n = len(s)
    flags: set[str] = set()
    i = 0
    while True:   # (a) 앞머리 전역 플래그 묶음, 여러 개 / leading global flag groups, as many as there are
        m = _FLAG_GROUP.match(s, i)
        if not m:
            break
        for c in m.group(1):
            if c in "ims":
                flags.add(c)
            elif c != "u":
                raise _unsupported(f"(?{c})")
        i = m.end()
    out: list[str] = []
    in_class = False
    class_body = 0   # 클래스 본문이 시작하는 자리(여기의 ']' 는 글자) / where the class body starts (a ']' here is literal)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:   # 이스케이프는 두 글자 한 덩어리 / an escape is one two-character unit
            d = s[i + 1]
            i += 2
            if d == "w":
                out.append(WORD_SET if in_class else f"[{WORD_SET}]")
            elif d == "W":
                if in_class:
                    raise _unsupported("[\\W]")
                out.append(f"[^{WORD_SET}]")
            elif d in "AZ" and not in_class:
                out.append("^" if d == "A" else "$")
            elif d == "a":
                out.append("\\x07")
            elif d in "UN":
                raise _unsupported("\\" + d)
            else:
                out.append("\\" + d)
            continue
        if in_class:
            if c == "]" and i == class_body:   # 맨 앞 ']' = 글자(JS 는 빈 클래스로 읽는다) / literal; JS reads an empty class
                out.append("\\]")
            else:
                if c == "]":
                    in_class = False
                out.append(c)
            i += 1
            continue
        if c == "[":
            j = i + 2 if s.startswith("[^", i) else i + 1
            out.append(s[i:j])
            in_class, class_body, i = True, j, j
            continue
        if s.startswith("(?", i):
            if s.startswith("(?P<", i):
                out.append("(?<")
                i += 4
                continue
            if s.startswith("(?P=", i):
                j = s.find(")", i)
                out.append("\\k<" + s[i + 4:j] + ">")
                i = j + 1
                continue
            nxt = s[i + 2:i + 3]
            if nxt in ("#", ">", "("):
                raise _unsupported("(?" + nxt)
            m = _SCOPED_FLAGS.match(s, i)
            if m and (m.group(1) or m.group(2)):   # 범위 플래그 (?i:…) · (?-i:…) / scoped flags
                on, off = m.group(1), m.group(2) or ""
                for ch in on + off:
                    if ch not in "imsu":
                        raise _unsupported(f"(?{ch}:")
                on = on.replace("u", "")
                out.append("(?:" if not (on or off) else f"(?{on}" + (f"-{off}" if off else "") + ":")
                i = m.end()
                continue
            out.append("(?")
            i += 2
            continue
        quant, j = None, i + 1
        if c in "*+?":
            quant = c
        elif c == "{":
            m = _REPEAT.match(s, i)
            if m and (m.group(1) or m.group(2)):   # '{}' · '{x}' 는 글자 / '{}' and '{x}' are literals
                quant = "{" + (m.group(1) or "0") + m.group(2) + m.group(3) + "}"
                j = m.end()
        if quant is not None:
            if j < n and s[j] == "+":   # 소유 수량자 / a possessive quantifier
                raise _unsupported(s[i:j + 1])
            if j < n and s[j] == "?":   # 게으른 수량자 / a lazy quantifier
                quant += "?"
                j += 1
            out.append(quant)
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out), "".join(ch for ch in "ims" if ch in flags)


def py_pattern(pattern: str) -> str:
    """JS 식 이름 있는 그룹 (?<이름>…) · \\k<이름> → 파이썬 식 (?P<이름>…) · (?P=이름)(클래스 · 이스케이프 밖에서만, 뒤보기
    (?<= · (?<! 는 그대로). 시스템 프롬프트가 JS 식을 안내하므로 grep 은 이것으로 바꾼 뒤 re.compile 로 검사한다.
    JS-style named groups (?<name>…) and \\k<name> → Python's (?P<name>…) and (?P=name), outside classes and escapes only
    (lookbehinds (?<= and (?<! stay). The system prompt teaches the JS form, so grep converts before re.compile."""
    s = str(pattern if pattern is not None else "")
    n = len(s)
    out: list[str] = []
    i, in_class, class_body = 0, False, 0
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            if not in_class and s.startswith("k<", i + 1):
                j = s.find(">", i + 3)
                if j > 0:
                    out.append("(?P=" + s[i + 3:j] + ")")
                    i = j + 1
                    continue
            out.append(s[i:i + 2])
            i += 2
            continue
        if in_class:
            if c == "]" and i != class_body:
                in_class = False
            out.append(c)
            i += 1
            continue
        if c == "[":
            j = i + 2 if s.startswith("[^", i) else i + 1
            out.append(s[i:j])
            in_class, class_body, i = True, j, j
            continue
        if s.startswith("(?<", i) and i + 3 < n and s[i + 3] not in "=!":
            out.append("(?P<")
            i += 3
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _git_part(rel: str) -> bool:
    """상대 경로의 조각에 .git 이 있는가(사용자 PC 규칙: 대소문자 · 끝의 점 · 공백 · ':' 스트림 무시)
    Does a segment name .git (user-PC rules: case, trailing dots and spaces and an NTFS stream suffix are ignored)"""
    return any(p.split(":", 1)[0].rstrip(" .").lower() == ".git" for p in str(rel or "").split("/"))


# ────────────────────────────────────────────────────────
# 실행기 / the executor
# ────────────────────────────────────────────────────────

class BrowserExecutor(agentic_exec.Executor):
    """내 컴퓨터 폴더 세션의 실행기: 원시 op 를 브라우저에 맡기고 결과를 LocalExecutor 와 같은 모양으로 조립한다.
    The executor of a browser-folder session: primitive ops go to the browser, results are assembled in LocalExecutor's shape."""

    def __init__(self, folder_name: str, *, session_id: str):
        self.folder = str(folder_name or "")
        self.session_id = str(session_id or "")
        self._cancelled = False   # 중단 뒤에는 새 요청을 내지 않는다 / no new requests after a stop
        self._lock = threading.Lock()

    # ── 경로 / paths ──
    def resolve(self, path, allow_outside: bool = False) -> str:
        """폴더 기준 상대 경로로 정규화('' = 폴더 자체): '\\' → '/', 빈 조각 · '.' 조각을 뺀다. 절대 경로(/ · X:) · '..' 은
        OutsideError. 폴더 이름 접두는 벗기지 않는다(폴더 안에 같은 이름의 하위 폴더가 있을 수 있다, 2026-10-20 검토 반영).
        allow_outside 는 뜻이 없다(폴더 밖은 브라우저가 다룰 수 없다).
        Normalize to a folder-relative path ('' = the folder itself): '\\' → '/', empty and '.' segments dropped; absolute
        paths and '..' raise OutsideError. A leading folder-name segment is not stripped, since the folder may hold a
        same-named subfolder (review, 2026-10-20). allow_outside has no meaning (the browser cannot leave the folder)."""
        raw = "" if path is None else str(path)
        if "\x00" in raw:
            raise ExecError("경로가 올바르지 않습니다")
        s = raw.strip().replace("\\", "/")
        if s.startswith("/") or re.match(r"^[A-Za-z]:", s):
            raise OutsideError(f"폴더 밖 경로는 쓸 수 없습니다: {raw.strip()}")
        parts = [p for p in s.split("/") if p not in ("", ".")]
        if ".." in parts:
            raise OutsideError(f"폴더 밖 경로는 쓸 수 없습니다: {raw.strip()}")
        return "/".join(parts)

    def rel(self, path) -> str:
        """산출물 경로('<폴더 이름>/<상대 경로>', _named 가 만든 것) → 화면용 상대 경로('.' = 폴더). 맨 앞 폴더 이름 한 조각만
        벗긴다. 잘못된 경로는 받은 그대로 / an output path ('<folder name>/<relative>', made by _named) → the display path;
        only the one leading folder-name segment is removed"""
        try:
            r = self.resolve(path)
        except ExecError:
            return str(path if path is not None else "")
        parts = r.split("/") if r else []
        if parts and self.folder and parts[0] == self.folder:
            parts = parts[1:]
        return "/".join(parts) or "."

    def _named(self, rel: str) -> str:
        """'<폴더 이름>/<상대 경로>'(산출물 · 결과의 path) / '<folder name>/<relative path>' (outputs and result paths)"""
        return f"{self.folder}/{rel}" if rel else self.folder

    def prefix_hint(self) -> str:
        """폴더 이름을 앞에 붙인 경로가 없을 때 덧붙이는 안내 / the hint added when a folder-name-prefixed path is missing"""
        return f"(경로는 작업 폴더 '{self.folder}' 기준 상대 경로입니다. 폴더 이름을 앞에 붙이지 마세요)"

    def _req(self, op: str, args: dict, timeout: float | None = None) -> dict:
        with self._lock:
            if self._cancelled:
                raise ExecError(STOPPED_MSG)
        try:
            return request(self.session_id, op, args, timeout)
        except BrowserOpError as e:
            # 첫 조각이 폴더 이름인 경로가 없다 = 모델이 폴더 이름을 앞에 붙였을 가능성 / likely a folder-name prefix
            first = str((args or {}).get("path") or "").split("/", 1)[0]
            if e.code in ("notfound", "notdir", "isdir") and self.folder and first == self.folder:
                raise BrowserOpError(f"{e} {self.prefix_hint()}", e.code) from None
            raise

    def _read_op(self, rel: str, timeout: float | None = None) -> dict:
        return self._req("read", {"path": rel, "max_bytes": agentic_exec.MAX_FILE_BYTES}, timeout)

    # ── 읽기 · 쓰기 · 편집 / read, write, edit ──
    def read(self, path, offset: int = 1, limit: int = agentic_exec.READ_DEFAULT_LINES, allow_outside: bool = False) -> dict:
        rel = self.resolve(path)
        r = self._read_op(rel)
        if r.get("binary"):
            raise ExecError("이진 파일은 읽을 수 없습니다")
        text = _text_of(r)
        extracted = bool(r.get("extracted"))
        if extracted and not text.strip():
            raise ExecError(NO_TEXT_MSG)
        body, total, start, end, truncated = agentic_exec.read_rows(text, offset, limit)
        # 브라우저가 잘라 준 본문(문서 본문 240,000자 상한)도 잘림으로 알린다 / a body the browser cut (the document cap) counts too
        truncated = truncated or bool(r.get("truncated"))
        # 인코딩은 브라우저가 알아낸 값 그대로(아는 값만, 없으면 utf-8) / the encoding the browser detected (known values, else utf-8)
        enc = r.get("encoding")
        return {"path": self._named(rel), "rel": rel or ".", "text": body, "lines": total, "start": start, "end": end,
                "truncated": truncated, "more": end < total, "size": _int(r.get("size")),
                "encoding": enc if enc in READ_ENCODINGS else "utf-8", "extracted": extracted}

    def write(self, path, content, allow_outside: bool = False) -> dict:
        if path is None or not str(path).strip():
            raise ExecError("path 가 비어 있습니다")
        rel = self.resolve(path)
        if not rel:
            raise ExecError("폴더입니다: .")
        if _git_part(rel):
            raise RefusedError(GIT_INTERNAL_MSG)
        text = "" if content is None else str(content)
        nbytes = len(text.encode("utf-8"))
        if nbytes > agentic_exec.MAX_FILE_BYTES:
            raise ExecError("내용이 너무 큽니다(10MB 초과)")
        r = self._req("write", {"path": rel, "text": text})
        created = bool(r.get("created"))
        out = {"path": self._named(rel), "rel": rel, "bytes": _int(r.get("bytes"), nbytes), "created": created,
               "diff": None, "added": 0, "removed": 0}
        old = r.get("old_text")
        if not created and isinstance(old, str):
            diff, added, removed = agentic_exec.unified_diff(rel, old, text)
            out.update(diff=diff, added=added, removed=removed)
        return out

    def edit(self, path, old_string, new_string, replace_all: bool = False, allow_outside: bool = False) -> dict:
        rel = self.resolve(path)
        if not rel:
            raise ExecError("폴더입니다: .")
        if _git_part(rel):
            raise RefusedError(GIT_INTERNAL_MSG)
        r = self._read_op(rel)
        if r.get("binary") or r.get("extracted"):
            raise ExecError(NO_EDIT_MSG)
        text = _text_of(r)
        if "\ufffd" in text:   # 브라우저가 UTF-8 로 못 읽은 글자(cp949 등): 다시 쓰면 깨진다 / undecodable bytes would be lost
            raise ExecError(LOSSY_MSG)
        updated, replaced = agentic_exec.compute_edit(text, old_string, new_string, replace_all)
        w = self._req("write", {"path": rel, "text": updated})
        diff, added, removed = agentic_exec.unified_diff(rel, text, updated)
        return {"path": self._named(rel), "rel": rel, "replaced": replaced, "diff": diff, "added": added,
                "removed": removed, "bytes": _int(w.get("bytes"), len(updated.encode("utf-8")))}

    # ── 목록 · 찾기 · 검색 / list, glob, grep ──
    def list_dir(self, path=None, allow_outside: bool = False) -> dict:
        rel = self.resolve(path)
        r = self._req("list", {"path": rel})
        raw = r.get("entries")
        if not isinstance(raw, list):
            raise ExecError(BAD_REPLY_MSG)
        entries = []
        for e in raw:
            if not isinstance(e, dict) or not str(e.get("name") or ""):
                continue
            is_dir = e.get("type") == "dir"
            entries.append({"name": str(e["name"]), "type": "dir" if is_dir else "file",
                            "size": 0 if is_dir else _int(e.get("size")), "mtime": _mtime_iso(e.get("mtime"))})
        entries.sort(key=lambda x: (x["type"] != "dir", x["name"].lower()))
        total = max(len(entries), _int(r.get("total")))
        cap = agentic_exec.MAX_LIST
        return {"path": self._named(rel), "rel": rel or ".", "entries": entries[:cap], "total": total,
                "truncated": total > cap or bool(r.get("truncated"))}

    def glob(self, pattern, path=None, allow_outside: bool = False) -> dict:
        pat = str(pattern or "").strip().replace("\\", "/")
        while pat.startswith("./"):
            pat = pat[2:]
        if not pat:
            raise ExecError("pattern 이 비어 있습니다")
        if pat.startswith("/") or re.match(r"^[A-Za-z]:", pat) or ".." in pat.split("/"):
            raise ExecError("pattern 에는 절대 경로나 .. 을 쓸 수 없습니다. 시작 폴더는 path 로 주세요")
        base = self.resolve(path)
        # 사용자 PC(Windows · macOS)는 대소문자를 가리지 않는다: 서버 OS 와 무관하게 무시 / user PCs ignore case, whatever the server OS
        rx = re.compile(agentic_exec.glob_regex(pat).pattern, re.IGNORECASE)
        r = self._req("walk", {"path": base, "skip": sorted(agentic_exec._skip_dirs(pat)), "max": agentic_exec.SCAN_MAX})
        files = r.get("files")
        if not isinstance(files, list):
            raise ExecError(BAD_REPLY_MSG)
        hits = []
        for f in files:
            if not isinstance(f, dict):
                continue
            inner = _clean_rel(f.get("rel"))   # walk 의 rel = path 기준 / walk's rel is relative to `path`
            if inner and rx.match(inner):
                hits.append((_mtime_num(f.get("mtime")), inner))
        hits.sort(key=lambda h: (-h[0], h[1]))
        capped = bool(r.get("capped"))
        cap = agentic_exec.MAX_GLOB
        # 돌려주는 경로는 세션 폴더 기준 / returned paths are relative to the session folder
        paths = [f"{base}/{h[1]}" if base else h[1] for h in hits[:cap]]
        return {"base": self._named(base), "rel_base": base or ".", "paths": paths, "count": len(hits),
                "truncated": capped or len(hits) > cap, "scan_capped": capped}

    def grep(self, pattern, path=None, glob=None, max_results: int = agentic_exec.GREP_DEFAULT,
             allow_outside: bool = False) -> dict:
        pat = "" if pattern is None else str(pattern)
        if not pat:
            raise ExecError("pattern 이 비어 있습니다")
        pyp = py_pattern(pat)   # JS 식 (?<이름>) · \k<이름> 도 받는다 / the JS-style named forms are accepted too
        try:
            re.compile(pyp)
        except re.error as e:
            raise ExecError(f"정규식 오류: {e}") from e
        js, flags = js_pattern(pyp)   # 브라우저에서 못 쓰는 구문은 여기서 거절(요청 전) / unsupported syntax fails here, before a request
        base = self.resolve(path)
        mx = agentic_exec._clamp(max_results, 1, agentic_exec.GREP_MAX, default=agentic_exec.GREP_DEFAULT)
        g = str(glob or "").strip().replace("\\", "/")
        glob_re = agentic_exec.glob_regex(g).pattern if g else ""
        r = self._req("grep", {"path": base, "pattern": js, "flags": flags, "glob": g, "glob_re": glob_re,
                               "by_path": "/" in g, "max_results": mx, "skip": sorted(agentic_exec._skip_dirs(g))})
        raw = r.get("matches")
        if not isinstance(raw, list):
            raise ExecError(BAD_REPLY_MSG)
        matches = [m for m in raw if isinstance(m, str)][:mx]
        return {"base": self._named(base), "rel_base": base or ".", "matches": matches, "count": len(matches),
                "files": _int(r.get("files")), "truncated": bool(r.get("truncated")) or len(raw) > mx}

    # ── 명령 / commands ──
    def run(self, command, timeout_sec=None, background: bool = False) -> dict:
        raise RefusedError(NO_BASH_MSG)

    def task_output(self, task_id) -> dict:
        raise RefusedError(NO_BASH_MSG)

    def cancel_running(self) -> None:
        """중단: 이 실행기는 새 요청을 내지 않고, 그 세션의 대기 요청은 모두 실패로 깨운다 / stop: no new requests, pending ones fail"""
        with self._lock:
            self._cancelled = True
        cancel(self.session_id, STOPPED_MSG)

    # ── 규칙 파일 / the rules file ──
    def read_rules(self) -> tuple[str, str]:
        """AGENTS.md, 없으면 AI365.md → (이름, 본문 2만 자). 없거나 읽지 못하면 다음 파일, 시간 초과(RULES_TIMEOUT_SEC) · 취소면
        바로 ("", ""). 워커 스레드에서 부른다.
        AGENTS.md, else AI365.md → (name, text capped at 20,000 chars). Missing or unreadable → the next file; a timeout
        (RULES_TIMEOUT_SEC) or a cancel → ("", "") at once. Call from a worker thread."""
        for name in RULE_FILES:
            try:
                r = self._read_op(name, timeout=RULES_TIMEOUT_SEC)
            except BrowserTimeout:
                return "", ""
            except ExecError as e:
                if self._cancelled or getattr(e, "code", "") == "cancel":   # 중단 · 삭제 / a stop or a deletion
                    return "", ""
                continue
            text = r.get("text")
            if r.get("binary") or r.get("extracted") or not isinstance(text, str):
                continue
            text = text.lstrip("\ufeff").strip()
            if len(text) > RULES_CHARS:
                text = text[:RULES_CHARS] + "\n…(규칙 파일이 길어 잘림)"
            return name, text
        return "", ""
