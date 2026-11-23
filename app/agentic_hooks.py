"""Agentic 모드 훅(2026-10-19, 3차): 세션 시작 · 요청 · 도구 앞뒤 · 턴 끝에 관리자와 작업 폴더가 정한 명령을 돌린다.

- 훅 = {"event": session_start|user_prompt|pre_tool|post_tool|stop, "matcher": 도구 이름 정규식(비면 전부, 도구 이벤트에만
  쓴다), "command": 한 줄 셸 명령, "timeout_sec": 1~600(기본 60)}. 전역 = 관리 센터 Agentic 카드(settings.hooks),
  폴더 = <폴더>/.ai365/hooks.json {"hooks": [...]}. 폴더 훅은 내용 해시를 사용자가 허용했을 때만 돈다(hooks_trust =
  'allow:<해시>'). 해시는 정규화한 훅 목록의 sha1 앞 12자라 공백만 바꾸면 그대로, 명령 · 조건을 바꾸면 다시 묻는다.
- 실행: 세션 폴더에서 Windows = "cmd" /d /s /c "<명령>", 그 밖 = /bin/sh -c. payload JSON(ASCII, 한글은 유니코드 이스케이프)을
  stdin 과 AI365_HOOK_FILE(임시 JSON 파일, 끝나면 지운다)로 넘기고 AI365_HOOK_EVENT 에 이벤트 이름을 둔다. 자식 환경 =
  agentic_exec._child_env()(API 키 같은 비밀 변수 제외).
- 판정: exit 2 = 막기(이유 = JSON reason > stderr > stdout 의 끝 500자). stdout 의 마지막 줄(없으면 stdout 전체)이 JSON
  객체면 {"decision": "block", "reason"} · {"add_context": "..."} 를 읽는다. 그 밖의 종료 코드는 허용(막지 않는 오류).
  시간 초과 = 프로세스 트리를 끝내고 허용 + timed_out. 화면 출력은 stdout 뒤에 stderr, 앞뒤를 남겨 4,000자.
  너무 깊은 JSON(RecursionError)도 해석 실패로만 본다. run_event 는 훅 하나의 예외를 그 훅의 "error" 로 적고 나머지를 이어 간다.
- 이 모듈은 agentic_store 를 import 하지 않는다(저장소가 설정 검증에 이 모듈을 부른다). agentic_exec 도 함수 안에서 부른다.
"""
# Agentic mode hooks (2026-10-19, phase 3): commands chosen by the admin and the working folder run at session start,
# on each request, around tools and at the end of a turn.
# - A hook = {"event", "matcher" (a tool-name regex, empty = all, used by tool events only), "command" (one shell line),
#   "timeout_sec" (1 to 600, default 60)}. Global hooks come from the Admin Center Agentic card (settings.hooks), folder
#   hooks from <folder>/.ai365/hooks.json {"hooks": [...]}. Folder hooks run only after the user trusted their content
#   hash (hooks_trust = 'allow:<hash>'); the hash is the first 12 hex digits of the sha1 of the normalized list, so a
#   whitespace edit keeps it while a changed command or condition asks again.
# - Running: in the session folder via "cmd" /d /s /c "<command>" on Windows and /bin/sh -c elsewhere. The payload JSON
#   (ASCII, Korean as unicode escapes) goes in on stdin and in AI365_HOOK_FILE (a temporary JSON file, removed
#   afterwards); AI365_HOOK_EVENT names the event. The child env is agentic_exec._child_env() (secrets removed).
# - Verdict: exit 2 blocks (reason = the JSON reason, else stderr, else the last 500 chars of stdout). When the last
#   stdout line (else all of stdout) is a JSON object, {"decision": "block", "reason"} and {"add_context": "..."} are
#   read. Other exit codes allow (a non-blocking error). A timeout kills the process tree and allows with timed_out.
#   The shown output is stdout then stderr, head and tail kept within 4,000 chars. Too deep JSON (RecursionError) is
#   just a failed parse; run_event records one hook's exception as that hook's "error" and carries on with the rest.
# - This module never imports agentic_store (the store calls it to validate settings); agentic_exec is imported lazily.

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time

logger = logging.getLogger("ai365.agentic")

EVENTS = ("session_start", "user_prompt", "pre_tool", "post_tool", "stop")
TOOL_EVENTS = ("pre_tool", "post_tool")   # matcher 를 쓰는 이벤트 / events that use the matcher
MAX_HOOKS = 50
DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 600
MAX_COMMAND = 4000
MAX_MATCHER = 300
OUTPUT_MAX = 4000            # 화면에 남기는 출력 / output kept for the screen
REASON_MAX = 500
ADD_CONTEXT_MAX = 10_000     # 모델에 붙이는 add_context 상한 / add_context cap for the model
STDOUT_KEEP = 64_000         # JSON 판정용으로 들고 있는 stdout / stdout kept for the JSON verdict
STDERR_KEEP = 8_000
HOOKS_FILE = (".ai365", "hooks.json")
HOOKS_FILE_MAX = 256 * 1024
JOIN_SEC = 5.0


def _ex():
    """agentic_exec 지연 import(agentic_store → 이 모듈 → agentic_exec → agentic_store 순환 방지) / lazy import, no cycle"""
    from app import agentic_exec
    return agentic_exec


# ────────────────────────────────────────────────────────
# 검증 · 불러오기 / validation and loading
# ────────────────────────────────────────────────────────

def _hook(h, n: int) -> dict:
    """훅 하나 검증 → {"event", "matcher", "command", "timeout_sec"}. 모르는 키는 버린다. 틀리면 ValueError.
    Validate one hook; unknown keys are dropped; ValueError when invalid."""
    if not isinstance(h, dict):
        raise ValueError(f"훅 {n}: 객체여야 합니다")
    event = str(h.get("event") or "").strip()
    if event not in EVENTS:
        raise ValueError(f"훅 {n}: event 는 {', '.join(EVENTS)} 중 하나입니다")
    matcher = h.get("matcher")
    if matcher is None:
        matcher = ""
    if not isinstance(matcher, str):
        raise ValueError(f"훅 {n}: matcher 는 문자열이어야 합니다")
    matcher = matcher.strip()
    if len(matcher) > MAX_MATCHER:
        raise ValueError(f"훅 {n}: matcher 는 {MAX_MATCHER}자까지입니다")
    if matcher:
        try:
            re.compile(matcher)
        except re.error as e:
            raise ValueError(f"훅 {n}: matcher 정규식 오류({matcher}): {e}") from e
    command = h.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError(f"훅 {n}: command 가 비어 있습니다")
    command = command.strip()
    if len(command) > MAX_COMMAND:
        raise ValueError(f"훅 {n}: command 는 {MAX_COMMAND}자까지입니다")
    if any(c in command for c in "\x00\r\n"):
        raise ValueError(f"훅 {n}: command 는 한 줄이어야 합니다")
    t = h.get("timeout_sec")
    if t is None or (isinstance(t, str) and not t.strip()):
        t = DEFAULT_TIMEOUT
    try:
        if isinstance(t, bool):
            raise ValueError
        tv = float(t)
    except (TypeError, ValueError):
        raise ValueError(f"훅 {n}: timeout_sec 은 1~{MAX_TIMEOUT} 사이의 정수입니다") from None
    if not tv.is_integer() or not 1 <= tv <= MAX_TIMEOUT:
        raise ValueError(f"훅 {n}: timeout_sec 은 1~{MAX_TIMEOUT} 사이의 정수입니다")
    return {"event": event, "matcher": matcher, "command": command, "timeout_sec": int(tv)}


def validate_hooks(raw) -> list[dict]:
    """훅 목록 검증 · 정규화(50개 상한, 정규식 컴파일 검사, timeout_sec 1~600 · 기본 60). None = []. 틀리면 ValueError.
    Validate and normalize a hook list (50 at most, regexes compiled, timeout_sec 1 to 600 with 60 by default)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("hooks 는 목록이어야 합니다")
    if len(raw) > MAX_HOOKS:
        raise ValueError(f"훅은 {MAX_HOOKS}개까지입니다")
    return [_hook(h, i) for i, h in enumerate(raw, 1)]


def _lenient(raw) -> list[dict]:
    """저장된 전역 훅 읽기: 틀린 항목만 건너뛴다(저장 때 검증했지만 방어) / stored global hooks, skipping bad items"""
    if not isinstance(raw, list):
        return []
    out = []
    for h in raw[:MAX_HOOKS]:
        try:
            out.append(_hook(h, len(out) + 1))
        except ValueError:
            continue
    return out


def _hash(hooks: list[dict]) -> str:
    return hashlib.sha1(json.dumps(hooks, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def load_folder_hooks(folder) -> dict:
    """<폴더>/.ai365/hooks.json → {"hooks": [...], "hash": "<sha1 12자>"|"", "error": ""|"<사람이 읽는 오류>"}.
    파일이 없거나 훅이 없으면 hooks=[] · hash="". 파싱 · 검증 오류면 훅 없이 error 만(하나라도 틀리면 전부 쓰지 않는다).
    폴더 밖을 가리키는 링크 파일은 읽지 않는다.
    Load the folder hooks file; no file or no hooks gives hooks=[] and hash=""; a parse or validation error gives no
    hooks and the error (one bad hook disables the file); a link pointing outside the folder is not read."""
    empty = {"hooks": [], "hash": "", "error": ""}
    if not folder:
        return empty
    try:
        base = os.path.realpath(str(folder))
    except (OSError, ValueError):
        return empty
    path = os.path.join(base, *HOOKS_FILE)
    if not os.path.lexists(path):
        return empty
    if not _ex().inside(path, [base]):
        return {**empty, "error": "폴더 밖을 가리키는 hooks.json 은 읽지 않습니다"}
    if not os.path.isfile(path):
        return {**empty, "error": "hooks.json 이 파일이 아닙니다"}
    try:
        if os.path.getsize(path) > HOOKS_FILE_MAX:
            return {**empty, "error": f"hooks.json 이 너무 큽니다({HOOKS_FILE_MAX // 1024}KB 초과)"}
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        return {**empty, "error": f"hooks.json 을 읽지 못했습니다: {e}"}
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return {**empty, "error": "hooks.json 은 UTF-8 이어야 합니다"}
    if not text.strip():
        return empty
    try:
        doc = json.loads(text)
    except RecursionError:   # 너무 깊게 중첩된 JSON(ValueError 가 아니다) / nested too deep, not a ValueError
        return {**empty, "error": "hooks.json 파싱 오류: 너무 깊게 중첩되어 있습니다"}
    except ValueError as e:
        where = f" ({e.lineno}줄 {e.colno}칸)" if hasattr(e, "lineno") else ""
        return {**empty, "error": f"hooks.json 파싱 오류: {getattr(e, 'msg', str(e))}{where}"}
    if isinstance(doc, dict):
        if "hooks" not in doc:
            return {**empty, "error": "hooks.json 에 hooks 목록이 없습니다"}
        raw = doc.get("hooks")
    elif isinstance(doc, list):
        raw = doc
    else:
        return {**empty, "error": "hooks.json 은 {\"hooks\": [...]} 객체여야 합니다"}
    try:
        hooks = validate_hooks(raw)
    except ValueError as e:
        return {**empty, "error": f"hooks.json: {e}"}
    if not hooks:
        return empty
    return {"hooks": hooks, "hash": _hash(hooks), "error": ""}


def active_hooks(settings, folder, hooks_trust) -> list[dict]:
    """지금 도는 훅 = 전역(설정) + 폴더(hooks_trust 가 'allow:<지금 해시>' 일 때만). 항목마다 "source": "global"|"folder".
    The hooks in force: global ones plus folder ones only when hooks_trust is 'allow:<current hash>'; each item carries
    its source."""
    hooks = [{**h, "source": "global"} for h in _lenient((settings or {}).get("hooks"))]
    if folder:
        loaded = load_folder_hooks(folder)
        if loaded["hooks"] and loaded["hash"] and str(hooks_trust or "") == "allow:" + loaded["hash"]:
            hooks += [{**h, "source": "folder"} for h in loaded["hooks"]]
    return hooks


def select(hooks, event, tool="") -> list[dict]:
    """이벤트가 같고(도구 이벤트면) matcher 가 비었거나 re.search(matcher, tool) 인 훅. 도구 이벤트가 아니면 matcher 를 보지
    않는다(도구 이름이 없다).
    Hooks of the event whose matcher is empty or matches the tool name; non-tool events ignore the matcher (no tool)."""
    out = []
    for h in hooks or []:
        if not isinstance(h, dict) or h.get("event") != event:
            continue
        matcher = str(h.get("matcher") or "")
        if matcher and event in TOOL_EVENTS:
            try:
                if not re.search(matcher, str(tool or "")):
                    continue
            except re.error:
                continue
        out.append(h)
    return out


# ────────────────────────────────────────────────────────
# 실행 / running
# ────────────────────────────────────────────────────────

def _timeout(v) -> int:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        n = DEFAULT_TIMEOUT
    return max(1, min(MAX_TIMEOUT, n))


def _clip_middle(s: str, n: int) -> str:
    """n 자를 넘으면 앞뒤를 남기고 가운데를 생략(표시까지 n 자 안) / keep head and tail within n chars"""
    if len(s) <= n:
        return s
    mark = f"\n… (출력이 길어 가운데를 생략했습니다. 전체 {len(s):,}자) …\n"
    half = max(1, (n - len(mark)) // 2)
    return s[:half] + mark + s[-half:]


def _spawn(command: str, cwd: str, env: dict) -> subprocess.Popen:
    """Windows = "cmd" /d /s /c "<명령>"(따옴표 그대로), 그 밖 = /bin/sh -c(새 세션: 시간 초과 때 그룹째 끝낸다).
    Windows: "cmd" /d /s /c "<command>" with quotes as typed; elsewhere /bin/sh -c in a new session (killed as a group)."""
    pipes = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    if os.name == "nt":
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        return subprocess.Popen(f'"{comspec}" /d /s /c "{command}"', cwd=cwd, env=env,
                                creationflags=_ex()._NO_WINDOW, **pipes)
    return subprocess.Popen(["/bin/sh", "-c", command], cwd=cwd, env=env, start_new_session=True, **pipes)


def _feed(stream, body: bytes) -> None:
    """stdin 에 payload 를 쓰고 닫는다(훅이 읽지 않고 끝나도 막히지 않게 스레드에서) / write the payload on a thread"""
    try:
        stream.write(body)
        stream.flush()
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except (OSError, ValueError):
            pass


def _json_out(stdout: str) -> dict | None:
    """stdout 의 마지막 줄(없으면 전체)이 JSON 객체면 그 dict / the last stdout line (else all of it) as a JSON object"""
    s = stdout.strip()
    if not s:
        return None
    for cand in (s.splitlines()[-1].strip(), s):
        if cand.startswith("{") and cand.endswith("}"):
            try:
                v = json.loads(cand)
            except (ValueError, RecursionError):   # 깊은 JSON 은 RecursionError / deep JSON raises RecursionError
                continue
            if isinstance(v, dict):
                return v
    return None


def _result(h: dict) -> dict:
    """훅 결과의 빈 틀(허용) / the empty result frame of a hook (allowed)"""
    return {"event": str(h.get("event") or ""), "source": str(h.get("source") or ""), "matcher": str(h.get("matcher") or ""),
            "command": str(h.get("command") or "").strip(), "exit_code": None, "output": "", "duration_ms": 0,
            "timed_out": False, "decision": "allow", "reason": "", "add_context": ""}


def run_hook(hook, payload: dict, folder) -> dict:
    """훅 하나 실행 → {"event", "source", "matcher", "command", "exit_code", "output", "duration_ms", "timed_out",
    "decision": "allow"|"block", "reason", "add_context"}. 동기 함수(호출부가 스레드에서 부른다). 시작 실패도 허용으로 돌려준다.
    payload JSON(stdin · AI365_HOOK_FILE)은 ASCII 로 쓴다(한글은 \\uXXXX): 훅이 cp949 같은 기본 인코딩으로 파일을 읽어도 깨지지 않는다.
    Run one hook (synchronous; callers use a worker thread); a failed start is reported and allowed. The payload JSON
    (stdin and AI365_HOOK_FILE) is ASCII with \\uXXXX escapes, so a hook reading the file in a locale encoding still works."""
    ex = _ex()
    h = hook if isinstance(hook, dict) else {}
    event = str(h.get("event") or "")
    command = str(h.get("command") or "").strip()
    timeout = _timeout(h.get("timeout_sec", DEFAULT_TIMEOUT))
    result = _result(h)
    if not command:
        result["output"] = "훅 명령이 비어 있습니다"
        return result
    data = dict(payload) if isinstance(payload, dict) else {"payload": payload}
    data.setdefault("event", event)
    try:
        text = json.dumps(data, ensure_ascii=True, default=str)
    except (TypeError, ValueError, RecursionError):   # 순환 참조 · 너무 깊은 payload / a cyclic or too deep payload
        text = json.dumps({"event": event}, ensure_ascii=True)
    body = (text + "\n").encode("utf-8")
    t0 = time.monotonic()
    tmp = ""
    try:
        fd, tmp = tempfile.mkstemp(prefix="ai365-hook-", suffix=".json")
        with os.fdopen(fd, "wb") as f:
            f.write(body)
    except OSError as e:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass
        result["output"] = f"훅을 시작하지 못했습니다(임시 파일): {e}"
        return result
    timed_out = False
    try:
        env = ex._child_env()
        env["AI365_HOOK_EVENT"] = event
        env["AI365_HOOK_FILE"] = tmp
        try:
            proc = _spawn(command, os.path.realpath(str(folder or ".")), env)
        except (OSError, ValueError) as e:
            result.update(output=f"훅을 시작하지 못했습니다: {e}", duration_ms=int((time.monotonic() - t0) * 1000))
            return result
        out, err = ex._Output(STDOUT_KEEP), ex._Output(STDERR_KEEP)
        threads = [threading.Thread(target=ex._pump, args=(proc.stdout, out), daemon=True, name="ai365-hook-out"),
                   threading.Thread(target=ex._pump, args=(proc.stderr, err), daemon=True, name="ai365-hook-err"),
                   threading.Thread(target=_feed, args=(proc.stdin, body), daemon=True, name="ai365-hook-in")]
        for t in threads:
            t.start()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            ex._kill_tree(proc)
            try:
                proc.wait(timeout=JOIN_SEC)
            except subprocess.TimeoutExpired:
                pass
        for t in threads:
            t.join(timeout=JOIN_SEC)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    code = None if timed_out else proc.returncode
    stdout, _ = out.text()
    stderr, _ = err.text()
    shown = stdout.rstrip("\n")
    if stderr.strip():
        shown = (shown + "\n" if shown else "") + stderr.rstrip("\n")
    if timed_out:
        shown = (shown + "\n" if shown else "") + f"[시간 초과({timeout}초)로 끝냈습니다]"
    result.update(exit_code=code, output=_clip_middle(shown, OUTPUT_MAX), timed_out=timed_out,
                  duration_ms=int((time.monotonic() - t0) * 1000))
    if timed_out:   # 시간 초과는 막지 않는다 / a timeout never blocks
        return result
    obj = _json_out(stdout)
    decision, reason, add_context = "allow", "", ""
    if obj is not None:
        if str(obj.get("decision") or "").strip().lower() in ("block", "deny"):
            decision = "block"
        reason = str(obj.get("reason") or "").strip()[:REASON_MAX]
        ac = obj.get("add_context")
        if ac is not None and not isinstance(ac, str):
            try:
                ac = json.dumps(ac, ensure_ascii=False)
            except (TypeError, ValueError, RecursionError):
                ac = ""
        add_context = (ac or "").strip()[:ADD_CONTEXT_MAX]
    if code == 2:
        decision = "block"
        if not reason:
            reason = (stderr.strip() or ("" if obj is not None else stdout.strip()))[-REASON_MAX:].strip()
    if decision == "block" and not reason:
        reason = f"exit {code}" if code == 2 else "decision=block"
    result.update(decision=decision, reason=reason, add_context=add_context)
    return result


def run_event(hooks, event, payload, folder, tool="") -> dict:
    """이벤트의 훅을 차례로 모두 돌린다(첫 막기에서 멈추지 않는다) → {"results": [...], "block": 하나라도 막았나,
    "reason": 막은 이유들(줄바꿈), "add_context": 이어 붙인 add_context}. payload 에 event(· tool)를 채워 넘긴다.
    훅 하나가 예외를 내도 다른 훅의 막기 판정은 남는다(그 훅은 "error" 와 허용으로 적는다).
    Run every hook of the event in order (no stop at the first block) → results, whether any blocked, the joined
    reasons and the joined add_context. The payload gets event (and tool) filled in. One hook raising never erases the
    others' blocks (that hook is recorded with "error" and allowed)."""
    data = dict(payload) if isinstance(payload, dict) else {}
    data.setdefault("event", event)
    if tool:
        data.setdefault("tool", tool)
    results = []
    for h in select(hooks, event, tool):
        try:
            results.append(run_hook(h, data, folder))
        except Exception as e:  # noqa: BLE001 (한 훅의 오류가 다른 훅을 지우지 않는다 / one hook's error spares the others)
            logger.warning("Agentic 훅 실행 오류 event=%s command=%s", event, str(h.get("command") or "")[:80], exc_info=True)
            msg = f"{type(e).__name__}: {str(e)[:300]}"
            results.append({**_result(h), "output": f"훅 실행 중 오류: {msg}", "error": msg})
    blocks = [r for r in results if r["decision"] == "block"]
    return {"results": results, "block": bool(blocks),
            "reason": "\n".join(r["reason"] for r in blocks if r["reason"]),
            "add_context": "\n\n".join(r["add_context"] for r in results if r["add_context"])}
