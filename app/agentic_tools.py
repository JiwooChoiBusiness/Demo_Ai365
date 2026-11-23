"""Agentic 모드 도구(2026-10-19): Gemini 함수 선언 · 권한 판정 · 실행 · 사람이 읽는 이름.

- TOOL_SPECS: read_file · list_dir · glob · grep · write_file · edit_file · bash · task_output · web_search · fetch_page
  (report_agent.TOOL_SPECS 와 같은 JSON 스키마, 대문자 타입). MCP 도구는 1차에서 뺀다(2차 Connectors 와 함께).
- classify(): 허용 폴더 밖 경로 → outside(모든 경로 도구), 차단 명령 → deny_cmd(bash), Auto 의 bash 는 안전 목록
  (is_safe_command)에 없으면 auto_cmd, 묻기 모드의 write_file · edit_file · bash · fetch_page → ask_mode. 세션 rules
  (이 세션에서 항상 허용)는 ask_mode · auto_cmd 만 건너뛴다. outside · deny_cmd 는 늘 묻는다(적대 검토 H1 · M2 반영).
- run_tool(): 실행기를 불러 (ok, summary, detail, extra) 를 돌려준다. extra = diff · output · exit_code · task_id ·
  truncated · duration_ms. 실패는 예외가 아니라 ok=False 와 사람이 읽는 메시지로 돌려 모델이 다음 수를 고르게 한다.
- 웹: web_search = llm.generate_grounded_meta(경량 티어, 구글 검색 그라운딩) 의 요약 + 출처, fetch_page = 사설망 차단
  (flow_api_call.check_url) 뒤 httpx GET(20초, 리다이렉트 따라가지 않음) + 정규식으로 script · style · 태그를 걷어 낸 글.
- 2차(2026-10-19): task(서브에이전트, 실행은 루프가 맡는다) · skill(스킬 본문) · mcp_tool(세션에 켠 MCP 도구). TOOL_SPECS =
  기본 선언 목록(1차 10개 + task), specs_for() 가 세션 · 설정 · 프리셋 · 플랜 모드에 맞춰 고른다. classify 는 플랜 모드의 쓰기
  도구를 plan_mode(묻지 않고 거절), Auto 의 실행형 MCP 도구를 mcp_action 으로 돌려준다.
- 내 컴퓨터 폴더(2026-10-20, kind = browser): 실행기 = agentic_browser.BrowserExecutor(도구 함수는 그대로), bash · task_output 은
  선언하지 않고(그래도 부르면 실행기가 거절, 승인은 묻지 않는다), 허용 폴더 밖(outside) 판정은 건너뛴다(폴더 밖은 브라우저가
  거절한다). 스킬 · 명령의 폴더 인자는 None(전역만), 허용 폴더(allowed_roots)는 [].
"""
# Agentic mode tools (2026-10-19): Gemini function declarations, permission classification, execution and human labels.
# - TOOL_SPECS: the ten phase-1 tools (same JSON schema shape as report_agent.TOOL_SPECS, upper-case types). MCP tools
#   are left out of phase 1 (they come with Connectors in phase 2).
# - classify(): a path outside the allowed folders → outside (every path tool), a denied command → deny_cmd (bash), an
#   Auto bash command off the safe list (is_safe_command) → auto_cmd, write_file, edit_file, bash and fetch_page in ask
#   mode → ask_mode. Session rules (always allow in this session) skip ask_mode and auto_cmd only; outside and deny_cmd
#   always ask (adversarial review H1 and M2).
# - run_tool(): runs the executor and returns (ok, summary, detail, extra) with extra = diff, output, exit_code, task_id,
#   truncated, duration_ms. Failures come back as ok=False with a readable message, never as exceptions, so the model
#   can choose its next move.
# - Web: web_search = the summary and sources of llm.generate_grounded_meta (lite tier, Google Search grounding);
#   fetch_page = the private-network guard (flow_api_call.check_url), then an httpx GET (20 s, no redirects) with
#   scripts, styles and tags stripped by regex.
# - Phase 2 (2026-10-19): task (subagents, run by the loop), skill (a skill's text) and mcp_tool (MCP tools turned on for
#   the session). TOOL_SPECS is the default declaration list (the ten phase-1 tools plus task); specs_for() picks the
#   list for a session, its settings, a preset and plan mode. classify returns plan_mode (refused, never asked) for
#   write tools in plan mode and mcp_action for action-kind MCP tools in Auto.
# - Folders on my computer (2026-10-20, kind = browser): the executor is agentic_browser.BrowserExecutor (the tool
#   functions stay), bash and task_output are not declared (a call anyway is refused by the executor, never asked), and
#   the outside check is skipped (the browser refuses paths leaving the folder). Skills and commands get None as the
#   folder (global ones only) and allowed_roots is [].

import html
import json
import logging
import os
import re
import shlex
import time
from urllib.parse import urlsplit

import httpx

from app import agentic_browser, agentic_exec, flow_api_call, llm
from app.agentic_exec import ExecError

logger = logging.getLogger("ai365.agentic")

GROUPS = {"read_file": "read", "list_dir": "read", "glob": "search", "grep": "search", "write_file": "write",
          "edit_file": "write", "bash": "run", "task_output": "run", "web_search": "web", "fetch_page": "web",
          "task": "agent", "skill": "read", "mcp_tool": "mcp"}
WRITE_TOOLS = ("write_file", "edit_file", "bash")
PATH_TOOLS = ("read_file", "list_dir", "glob", "grep", "write_file", "edit_file")
# 내 컴퓨터 폴더 세션이 선언하지 않는 도구(명령 실행 없음, 2026-10-20) / tools a browser-folder session does not declare
BROWSER_NO_TOOLS = ("bash", "task_output")
ASK_TOOLS = ("write_file", "edit_file", "fetch_page")   # 묻기 모드에서 묻는 bash 밖의 도구(fetch_page = 적대 검토 M2) / ask-mode tools besides bash
# 플랜 모드에서 선언하는 도구(읽기 · 조사만) / the tools declared in plan mode (reading and research only)
PLAN_TOOLS = ("read_file", "list_dir", "glob", "grep", "web_search", "fetch_page", "task", "skill")
PRESETS = ("explorer", "worker", "reviewer")
_EXPLORER = ("read_file", "list_dir", "glob", "grep", "web_search", "fetch_page", "skill")
PLAN_REFUSAL = "플랜 모드에서는 읽기 · 조사만 할 수 있습니다. 계획을 글로 제시하세요"
SUBAGENT_RESULT_MAX = 8000         # task 결과(서브에이전트 최종 글) 상한 / cap of a task result (the subagent's final text)
SKILL_TEXT_MAX = 20000

EVENT_DETAIL_MAX = 4000            # tool_result.detail(화면) 상한 / tool_result.detail cap (screen)
MODEL_DETAIL_MAX = 6000            # 모델에 돌려주는 결과 하나의 기본 상한 / default cap of one result fed to the model
# 도구 명세가 더 큰 본문을 정한 도구 / tools whose spec sets a bigger body
MODEL_DETAIL_BY_TOOL = {"read_file": 60000, "fetch_page": 30000, "skill": SKILL_TEXT_MAX + 2000, "task": SUBAGENT_RESULT_MAX + 200}
DIFF_MAX = 50000
FETCH_TIMEOUT = 20
FETCH_MAX_CHARS = 30000
FETCH_MAX_BYTES = 2_000_000
FETCH_UA = "Mozilla/5.0 (compatible; Ai365-Agentic/1.0)"
TRANSPORT = None   # 테스트 이음새(httpx 전송) / test seam (an httpx transport)

WEB_SYSTEM = "웹 검색 결과를 바탕으로 검색어에 대한 핵심 사실을 한국어로 간결하게 정리하라. 확인되지 않은 내용은 쓰지 않는다."

_PATH_DESC = "작업 폴더 기준 상대 경로 또는 절대 경로"

_BASE_SPECS = [
    {"name": "read_file",
     "description": "텍스트 파일을 줄 번호와 함께 읽는다(기본 2000줄, 최대 60,000자). 큰 파일은 offset(시작 줄, 1부터)과 "
                    "limit(줄 수)으로 나눠 읽는다. 파일을 고치기 전에 반드시 먼저 읽는다.",
     "parameters": {"type": "OBJECT", "properties": {
         "path": {"type": "STRING", "description": _PATH_DESC},
         "offset": {"type": "INTEGER", "description": "시작 줄 번호(1부터, 기본 1)"},
         "limit": {"type": "INTEGER", "description": "읽을 줄 수(기본 2000)"}}, "required": ["path"]}},
    {"name": "list_dir",
     "description": "폴더의 항목(이름 · 종류 · 크기)을 본다(최대 500개). path 를 비우면 작업 폴더.",
     "parameters": {"type": "OBJECT", "properties": {"path": {"type": "STRING", "description": _PATH_DESC}}}},
    {"name": "glob",
     "description": "glob 패턴으로 파일을 찾는다(예: **/*.py, src/**/*.ts, *.md). 최근에 고친 것부터 최대 500개. "
                    ".git · node_modules 같은 무거운 폴더는 건너뛴다.",
     "parameters": {"type": "OBJECT", "properties": {
         "pattern": {"type": "STRING", "description": "glob 패턴(구분자 /, .. 과 절대 경로는 쓸 수 없다)"},
         "path": {"type": "STRING", "description": "찾기 시작할 폴더(기본 작업 폴더)"}}, "required": ["pattern"]}},
    {"name": "grep",
     "description": "파일 내용에서 정규식(Python re)을 찾아 '경로:줄:내용' 목록으로 돌려준다(기본 200개).",
     "parameters": {"type": "OBJECT", "properties": {
         "pattern": {"type": "STRING", "description": "정규식. 대소문자를 무시하려면 앞에 (?i)"},
         "path": {"type": "STRING", "description": "찾을 폴더나 파일(기본 작업 폴더)"},
         "glob": {"type": "STRING", "description": "파일 이름 거르기(예: *.py)"},
         "max": {"type": "INTEGER", "description": "최대 결과 수(기본 200)"}}, "required": ["pattern"]}},
    {"name": "write_file",
     "description": "파일을 새로 만들거나 내용 전체를 바꿔 쓴다(UTF-8). 있는 파일의 일부만 고칠 때는 edit_file 을 쓴다.",
     "parameters": {"type": "OBJECT", "properties": {
         "path": {"type": "STRING", "description": _PATH_DESC},
         "content": {"type": "STRING", "description": "파일 전체 내용"}}, "required": ["path", "content"]}},
    {"name": "edit_file",
     "description": "파일의 old_string 을 new_string 으로 바꾼다. old_string 은 파일에서 정확히 한 곳과 일치해야 한다"
                    "(들여쓰기 · 공백까지 같게). 일치하는 곳을 모두 바꾸려면 replace_all=true.",
     "parameters": {"type": "OBJECT", "properties": {
         "path": {"type": "STRING", "description": _PATH_DESC},
         "old_string": {"type": "STRING", "description": "바꿀 원래 글(read_file 결과의 줄 번호와 탭은 빼고)"},
         "new_string": {"type": "STRING", "description": "새 글"},
         "replace_all": {"type": "BOOLEAN", "description": "일치하는 곳을 모두 바꾼다(기본 false)"}},
         "required": ["path", "old_string", "new_string"]}},
    {"name": "bash",
     "description": "작업 폴더에서 셸 명령을 실행한다(Windows = cmd, 그 밖 = sh). 출력(stdout + stderr)과 종료 코드를 돌려준다. "
                    "빌드 · 테스트 · git 처럼 꼭 필요할 때만 쓰고 파일 읽기 · 찾기 · 검색에는 쓰지 않는다. "
                    "서버처럼 끝나지 않는 명령은 background=true 로 띄운다.",
     "parameters": {"type": "OBJECT", "properties": {
         "command": {"type": "STRING", "description": "실행할 명령 한 줄"},
         "timeout_sec": {"type": "INTEGER", "description": "시간 제한(초, 기본 = 관리자 설정, 최대 600)"},
         "background": {"type": "BOOLEAN", "description": "true 면 백그라운드로 띄우고 작업 id 만 바로 돌려준다"}},
         "required": ["command"]}},
    {"name": "task_output",
     "description": "bash(background=true) 로 띄운 작업의 지금 출력과 상태를 본다.",
     "parameters": {"type": "OBJECT", "properties": {
         "task_id": {"type": "STRING", "description": "bash 가 돌려준 작업 id"}}, "required": ["task_id"]}},
    {"name": "web_search",
     "description": "웹을 검색해 요약과 출처(제목 · 주소)를 돌려준다. 작업 폴더에 없는 바깥 정보가 필요할 때만 쓴다.",
     "parameters": {"type": "OBJECT", "properties": {
         "query": {"type": "STRING", "description": "검색어(한 문장)"},
         "max": {"type": "INTEGER", "description": "출처 수(기본 5)"}}, "required": ["query"]}},
    {"name": "fetch_page",
     "description": "웹 페이지(http · https)의 본문을 글로 읽는다(최대 30,000자). 리다이렉트는 따라가지 않으니 알려 준 새 주소로 "
                    "다시 부른다. 사내망 · 내부 주소는 읽을 수 없다.",
     "parameters": {"type": "OBJECT", "properties": {
         "url": {"type": "STRING", "description": "읽을 주소"}}, "required": ["url"]}},
]
# 2차 도구 / phase-2 tools
SKILL_SPEC = {
    "name": "skill",
    "description": "스킬(작업 방법 안내서)의 본문을 읽는다. 시스템 프롬프트의 [사용 가능한 스킬] 목록에 있는 이름만 쓴다. "
                   "관련된 일을 시작하기 전에 먼저 읽고 그 지침을 따른다.",
    "parameters": {"type": "OBJECT", "properties": {
        "name": {"type": "STRING", "description": "스킬 이름"}}, "required": ["name"]}}
MCP_SPEC = {
    "name": "mcp_tool",
    "description": "관리 센터에 연결된 외부 도구(MCP)를 부른다. connector_id 는 시스템 프롬프트의 [연결된 도구(mcp_tool)] 목록의 id, "
                   "inputs_json 은 그 도구의 입력값을 담은 JSON 객체 문자열이다(입력이 없으면 {}).",
    "parameters": {"type": "OBJECT", "properties": {
        "connector_id": {"type": "STRING", "description": "[연결된 도구(mcp_tool)] 목록의 id"},
        "inputs_json": {"type": "STRING", "description": "입력값 JSON 객체 문자열(예: {\"query\": \"서울\"}), 없으면 {}"}},
        "required": ["connector_id"]}}
TASK_SPEC = {
    "name": "task",
    "description": "서브에이전트에게 독립적인 일을 맡기고 그 최종 보고 글을 받는다. preset: explorer = 읽기 · 찾기 · 웹 조사만"
                   "(가벼운 모델, 빠름), worker = 파일 고치기 · 명령 실행까지, reviewer = 읽기 + 명령으로 검증하고 판정만. "
                   "서브에이전트는 이 대화를 보지 못하니 prompt 에 목표 · 범위 · 필요한 맥락 · 돌려받을 결과 모양을 모두 적는다. "
                   "서로 독립적인 일은 한 번에 여러 task 로 부르면 동시에 돈다.",
    "parameters": {"type": "OBJECT", "properties": {
        "description": {"type": "STRING", "description": "화면에 보일 짧은 이름(3~6낱말)"},
        "prompt": {"type": "STRING", "description": "서브에이전트에게 줄 지시 전문"},
        "preset": {"type": "STRING", "enum": list(PRESETS), "description": "explorer | worker | reviewer"},
        "model": {"type": "STRING", "description": "(선택) 모델 id: gemini-3.7-flash · gemini-3.5-flash · gemini-3.5-flash-lite"}},
        "required": ["description", "prompt", "preset"]}}
# 내 컴퓨터 폴더 세션의 task 선언: 명령 실행이 없는 프리셋 설명(2026-10-20 검토 반영) / the browser-folder task declaration
TASK_SPEC_BROWSER = {**TASK_SPEC, "description": (
    "서브에이전트에게 독립적인 일을 맡기고 그 최종 보고 글을 받는다. preset: explorer = 읽기 · 찾기 · 웹 조사만(가벼운 모델, 빠름), "
    "worker = 파일 고치기까지, reviewer = 읽어서 검증하고 판정만(명령 실행은 누구도 할 수 없다). "
    "서브에이전트는 이 대화를 보지 못하니 prompt 에 목표 · 범위 · 필요한 맥락 · 돌려받을 결과 모양을 모두 적는다. "
    "서로 독립적인 일은 한 번에 여러 task 로 부르면 동시에 돈다.")}
# 기본 선언 목록(스킬 · 연결 도구가 없는 세션의 맨 위 루프): 1차 10개 + task / the default declaration list
TOOL_SPECS = [*_BASE_SPECS, TASK_SPEC]
ALL_SPECS = [*_BASE_SPECS, SKILL_SPEC, MCP_SPEC, TASK_SPEC]   # specs_for 가 이 순서로 고른다 / specs_for keeps this order
TOOL_NAMES = tuple(s["name"] for s in ALL_SPECS)              # 전체 이름(IMITATION 정규식 · classify) / every name
PRESET_TOOLS = {"explorer": _EXPLORER,
                "worker": tuple(n for n in TOOL_NAMES if n != "task"),
                "reviewer": (*_EXPLORER, "bash")}


# ────────────────────────────────────────────────────────
# 작은 도우미 / small helpers
# ────────────────────────────────────────────────────────

def _int(v, lo: int, hi: int, default: int) -> int:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


def _bool(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(v)


def _short(s, n: int) -> str:
    t = re.sub(r"\s+", " ", str(s if s is not None else "")).strip()
    return t if len(t) <= n else t[:n - 1] + "…"


def clip(s, n: int) -> str:
    """n 자를 넘으면 자르고 생략한 글자 수를 적는다 / cut at n chars and note how much was left out"""
    s = str(s if s is not None else "")
    return s if len(s) <= n else s[:n] + f"\n…({len(s) - n:,}자 생략)"


def _size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n / 1024 / 1024:.1f}MB"


def _secs(ms: int) -> str:
    return f"{(ms or 0) / 1000:.1f}초"


def _req(a: dict, key: str) -> str:
    v = a.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        raise ExecError(f"{key} 인자가 필요합니다")
    return v if isinstance(v, str) else str(v)


def _tokens(command) -> list[str]:
    """명령의 낱말들(맨 앞 낱말이 따옴표로 묶였으면 따옴표를 벗긴다) / command words, the leading quoted word unquoted"""
    s = str(command or "").strip()
    if not s:
        return []
    if s[0] in "\"'":
        j = s.find(s[0], 1)
        if j > 0:
            return [s[1:j], *s[j + 1:].split()]
    return s.split()


def _fold(s: str) -> str:
    return s.lower() if os.name == "nt" else s


# ────────────────────────────────────────────────────────
# 권한 판정 / permission classification
# ────────────────────────────────────────────────────────

def allowed_roots(session: dict, settings: dict) -> list[str]:
    """허용 폴더 = 세션 폴더 + 추가 폴더 + 설정의 허용 폴더. 내 컴퓨터 폴더 세션은 [](서버 경로를 하나도 열지 않는다)
    Session folder + extra folders + configured allowed folders; [] for a browser-folder session (no server path opens)"""
    if agentic_browser.is_browser(session):
        return []
    return [session["folder"], *(session.get("extra_folders") or []), *(settings.get("allowed_folders") or [])]


def make_executor(session: dict, settings: dict) -> agentic_exec.Executor:
    """세션 · 설정으로 실행기를 만든다(시간 제한 · 출력 상한 · background 상한 = 예산). 내 컴퓨터 폴더 세션은 BrowserExecutor.
    Build the session's executor (time limit, output cap and background cap from the budgets); BrowserExecutor for a
    browser-folder session."""
    if agentic_browser.is_browser(session):
        return agentic_browser.BrowserExecutor(session["folder"], session_id=session["id"])
    b = settings.get("budgets") or {}
    return agentic_exec.LocalExecutor(session["folder"], allowed_roots(session, settings), session_id=session["id"],
                                      bash_timeout=int(b.get("bash_timeout_sec") or 120),
                                      max_output=int(b.get("max_output_chars") or 20000),
                                      bg_max_sec=int(b.get("max_minutes") or 120) * 60)


# ── 안전 명령 판정(적대 검토 H1, 2026-10-19): Auto 에서 bash 는 "차단 아니면 허용" 이 아니라 "안전 목록 아니면 승인" ──
# ── Safe-command check (adversarial review H1): in Auto, bash is "approve unless on the safe list", not "allow unless denied" ──
SAFE_COMMANDS = frozenset({"dir", "ls", "tree", "pwd", "cd", "where", "which", "echo", "type", "cat", "head", "tail", "more",
                           "find", "findstr", "grep", "wc", "sort", "mkdir", "md", "git", "npm", "node", "npx", "python", "py", "pip"})
GIT_SAFE = frozenset({"status", "log", "diff", "show", "branch", "rev-parse", "remote", "ls-files", "blame", "describe", "stash"})
GIT_BRANCH_READ = frozenset({"-a", "-r", "-v", "-vv", "-l", "--all", "--remotes", "--list", "--show-current", "--verbose",
                             "--color", "--no-color"})                       # 읽기만 하는 branch 플래그 / read-only branch flags
NPM_SAFE = frozenset({"test", "run", "ls", "list", "view", "outdated", "-v", "--version"})
NPX_SAFE = frozenset({"vitest", "jest", "mocha", "tsc", "eslint", "prettier", "--version"})
PIP_SAFE = frozenset({"list", "show", "freeze", "check", "--version"})
FIND_ACTIONS = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"})
# 셸 연산자 · 변수: > >> < | & && || ; ` ^ 줄바꿈 $( $변수 %변수% / shell operators and variables
_SHELL_OPS = re.compile(r"[<>|&;`^\r\n$]|%[^%\s]*%")
# 지금 명령의 하위 명령까지 규칙에 담는 프로그램(git commit 을 허용해도 git push 는 다시 묻게) / programs whose rule keeps the subcommand
# node · python · python3 · py 는 뺐다(2026-10-19 사용자 요청): 규칙 = 프로그램만이라 python 하나가 python --version · python -c … ·
# python -m … 를 덮는다(전에는 둘째 낱말까지라 '항상 허용'을 여러 번 눌러야 했다). 차단 명령(deny_cmd)은 규칙과 무관하게 늘 묻는다.
# node, python, python3 and py are out (user request, 2026-10-19): their rule is the program alone, so one python rule covers
# python --version, python -c … and python -m … (keeping the second word made people press 'always allow' again and again).
# Denied commands (deny_cmd) still always ask, whatever the rules.
_SUBCOMMAND_PROGS = frozenset({"git", "npm", "npx", "pnpm", "yarn", "pip", "pip3", "powershell", "pwsh", "cmd", "docker", "uv"})


def _prog(word: str) -> str:
    """첫 낱말 → 프로그램 이름(경로면 basename, 소문자, .exe 제거) / the program name of the first word"""
    name = re.split(r"[\\/]", str(word or "").strip("\"'"))[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _abs_or_up(word: str) -> bool:
    """절대 경로([A-Za-z]: · \\ · / · ~ 로 시작)이거나 .. 이 들어 있는가 / absolute (drive, slash, backslash, ~) or containing .."""
    w = str(word or "").strip("\"'")
    return bool(re.match(r"^(?:[A-Za-z]:|[\\/~])", w)) or ".." in w


def _words(command: str) -> list[str] | None:
    """따옴표를 지킨 낱말 나누기(바깥 따옴표는 벗긴다). 따옴표가 짝이 안 맞으면 None / quote-aware split, None when unbalanced"""
    try:
        words = shlex.split(command, posix=False)
    except ValueError:
        return None
    return [w[1:-1] if len(w) >= 2 and w[0] == w[-1] and w[0] in "\"'" else w for w in words]


def _git_safe(args: list[str]) -> bool:
    if not args or args[0].lower() not in GIT_SAFE:
        return False
    sub, rest = args[0].lower(), [a.lower() for a in args[1:]]
    if any(a.startswith("--output") for a in rest):   # diff · log 의 --output 은 파일을 쓴다 / --output writes a file
        return False
    if sub == "stash":
        return rest == ["list"]
    if sub == "branch":   # 목록 보기만(-d · -D · -m · 새 이름 = 쓰기) / listing only
        return all(a in GIT_BRANCH_READ for a in rest)
    if sub == "remote":   # 보기만(add · remove · set-url = 쓰기) / viewing only
        return not rest or rest in (["-v"], ["--verbose"]) or (len(rest) == 2 and rest[0] in ("show", "get-url"))
    return True


def _script_safe(prog: str, args: list[str]) -> bool:
    """node · python · py: 다른 플래그 없이 상대 경로 스크립트, 또는 테스트 실행(python -m unittest|pytest, node --test)
    node, python, py: a relative script with no flags before it, or a test run"""
    if not args:
        return False
    first = args[0].lower()
    if prog in ("python", "py") and first == "-m":
        return len(args) >= 2 and args[1].lower() in ("unittest", "pytest") and not any(_abs_or_up(a) for a in args[2:])
    if prog == "node" and first == "--test":
        return not any(_abs_or_up(a) for a in args[1:])
    return not first.startswith("-") and not _abs_or_up(args[0])   # -c · -e · -p · --eval · --print · -m 등 / any flag first


def is_safe_command(command) -> bool:
    """Auto 에서 승인 없이 돌려도 되는 명령인가(순수 함수). 셸 연산자 · 변수가 있으면 불안전, 첫 낱말이 안전 목록이고 하위 조건
    (git · npm · npx · pip 하위 명령, node · python 스크립트, 읽기 명령과 그 밖의 인자에 절대 경로 · .. 없음)을 지켜야 안전.
    Whether Auto may run the command without an approval (pure). Shell operators or variables make it unsafe; the first
    word must be on the safe list and meet its sub-conditions (git, npm, npx, pip subcommands; node and python scripts;
    no absolute paths or .. in the arguments of the reading and plain commands)."""
    cmd = str(command or "").strip()
    if not cmd or _SHELL_OPS.search(cmd):
        return False
    words = _words(cmd)
    if not words:
        return False
    prog, args = _prog(words[0]), words[1:]
    if prog not in SAFE_COMMANDS:
        return False
    if prog == "git":
        return _git_safe(args)
    if prog == "npm":
        return bool(args) and args[0].lower() in NPM_SAFE
    if prog == "npx":
        return bool(args) and args[0].lower() in NPX_SAFE
    if prog == "pip":
        return bool(args) and args[0].lower() in PIP_SAFE
    if prog in ("node", "python", "py"):
        return _script_safe(prog, args)
    if prog == "find" and any(a.lower() in FIND_ACTIONS for a in args):   # POSIX find 의 지우기 · 실행 / POSIX find actions
        return False
    if prog == "sort" and any(a.lower() in ("-o", "--output") or a.lower().startswith("--output=") for a in args):
        return False
    return not any(_abs_or_up(a) for a in args)


def rule_for(tool: str, args: dict) -> dict:
    """'항상 허용' 규칙: bash 는 명령 첫 낱말(git · npm · pip · docker 처럼 하위 명령을 받는 프로그램은 둘째 낱말까지,
    python · node 는 프로그램만), mcp_tool 은 커넥터 id, 그 밖은 도구 이름.
    The always-allow rule: bash by its first word (plus the second for programs with subcommands such as git, npm, pip and
    docker, so allowing `git commit` does not allow `git push`; python and node by the program alone), mcp_tool by
    connector id, other tools by name."""
    if tool == "bash":
        words = _tokens((args or {}).get("command"))
        if not words:
            return {"tool": "bash", "prefix": ""}
        prefix = words[0] if (len(words) < 2 or _prog(words[0]) not in _SUBCOMMAND_PROGS) else f"{words[0]} {words[1]}"
        return {"tool": "bash", "prefix": prefix}
    if tool == "mcp_tool":
        return {"tool": "mcp_tool", "connector": str((args or {}).get("connector_id") or "").strip()}
    return {"tool": tool}


def rule_matches(rules, tool: str, args: dict) -> bool:
    """세션 규칙에 맞는가. bash 규칙은 명령이 prefix(낱말 단위)로 시작해야 맞고, prefix 가 빈 bash 규칙은 아무것도 허용하지 않는다.
    mcp_tool 규칙은 같은 커넥터 id 만(빈 id 는 아무것도 허용하지 않는다).
    Do the session rules cover this call? A bash rule needs the command to start with its prefix, word by word; a bash rule
    with an empty prefix allows nothing; an mcp_tool rule covers its own connector id only."""
    words = " ".join(_tokens((args or {}).get("command"))) if tool == "bash" else ""
    conn = str((args or {}).get("connector_id") or "").strip() if tool == "mcp_tool" else ""
    for r in rules or []:
        if not isinstance(r, dict) or r.get("tool") != tool:
            continue
        if tool == "mcp_tool":
            if conn and str(r.get("connector") or "") == conn:
                return True
            continue
        if tool != "bash":
            return True
        prefix = " ".join(_tokens(r.get("prefix")))
        if not prefix:
            continue
        w, p = _fold(words), _fold(prefix)
        if w == p or w.startswith(p + " "):
            return True
    return False


def allowed_connector_ids(owner) -> set[str] | None:
    """권한 축 p_conn(워크플로우와 같은 access.allowed_connectors): 소유자가 쓸 수 있는 커넥터 id 집합. 슈퍼('') = None(전체).
    숫자가 아닌 신원 · 조회 실패는 빈 집합(닫힌 쪽, 적대 검토 M2).
    The p_conn axis (access.allowed_connectors, as workflows use it): connector ids the owner may use; super ('') = None
    (all); a non-numeric identity or a lookup failure gives the empty set (fails closed, adversarial review M2)."""
    o = str(owner or "").strip()
    if not o:
        return None
    if not o.isdigit():
        return set()
    try:
        from app import access   # 지연 임포트 / lazy import
        allowed = access.allowed_connectors(o)
    except Exception:  # noqa: BLE001
        logger.warning("Agentic 연결 도구 권한을 읽지 못함 owner=%s", o, exc_info=True)
        return set()
    return set() if allowed is None else {str(x) for x in allowed}


def mcp_kind(connector_id) -> str:
    """MCP 도구 커넥터의 종류 read | action | ''(없음). agentic_mcp 를 지연 임포트한다 / the connector kind, lazily imported"""
    try:
        from app import agentic_mcp
        return str(agentic_mcp.kind_of(str(connector_id or "").strip()) or "")
    except Exception:  # noqa: BLE001 (모듈이 없거나 DB 오류면 모른다 / unknown when the module or DB fails)
        logger.warning("MCP 도구 종류를 읽지 못함 connector=%s", connector_id, exc_info=True)
        return ""


def classify(session: dict, tool: str, args: dict, settings: dict) -> str | None:
    """승인이 필요하면 이유, 아니면 None. 플랜 모드의 쓰기 도구(write_file · edit_file · bash · 실행형 mcp_tool)는 plan_mode
    (runner 가 묻지 않고 거절한다). 경로 도구가 허용 폴더 밖이면 outside. bash 는 차단 명령이면 deny_cmd(규칙도 못 넘는다) →
    세션 규칙에 맞으면 None → 묻기 모드면 ask_mode → Auto 는 안전 명령이면 None, 아니면 auto_cmd. 묻기 모드의 write_file ·
    edit_file · fetch_page 는 규칙이 없으면 ask_mode. mcp_tool 은 세션에 켠 커넥터만 다루고(아니면 None, 실행이 거절한다)
    묻기 모드면 ask_mode, Auto 의 실행형(action)은 mcp_action(커넥터 규칙이 있으면 None). task · skill 은 묻지 않는다.
    내 컴퓨터 폴더 세션(2026-10-20)은 outside 를 보지 않고(폴더 밖은 브라우저가 거절한다) bash · task_output 은 None(실행기가
    거절한다, 승인 카드를 띄우지 않는다). 플랜 모드 · 묻기 모드 · 규칙은 그대로다.
    The reason an approval is needed, else None. In plan mode the write tools (write_file, edit_file, bash, action MCP
    tools) give plan_mode, which the runner refuses without asking. Path tools outside the allowed folders → outside.
    bash: a denied command → deny_cmd (no rule passes it), a matching session rule → None, ask mode → ask_mode, Auto →
    None for a safe command else auto_cmd. In ask mode write_file, edit_file and fetch_page ask (ask_mode) unless a rule
    covers them. mcp_tool handles the session's own connectors only (others → None, the run refuses them): ask mode →
    ask_mode, an action tool in Auto → mcp_action (None under a connector rule). task and skill never ask. A
    browser-folder session (2026-10-20) skips outside (the browser refuses paths leaving the folder) and gives None for
    bash and task_output (the executor refuses them, no approval card); plan mode, ask mode and rules stay."""
    a = args if isinstance(args, dict) else {}
    plan = session.get("perm_mode") == "plan"
    browser = agentic_browser.is_browser(session)
    if tool == "mcp_tool":
        cid = str(a.get("connector_id") or "").strip()
        if not cid or cid not in (session.get("connectors") or []):
            return None
        kind = mcp_kind(cid)
        if plan and kind != "read":
            return "plan_mode"
        if rule_matches(session.get("rules"), tool, a):
            return None
        if session.get("perm_mode") == "ask":
            return "ask_mode"
        return "mcp_action" if kind != "read" else None
    if plan and tool in WRITE_TOOLS:
        return "plan_mode"
    if browser and tool in BROWSER_NO_TOOLS:
        return None   # 실행기가 거절한다(묻지 않는다) / the executor refuses it, never asked
    if tool in PATH_TOOLS and not browser:
        try:
            target = agentic_exec.real_target(session["folder"], a.get("path"))
        except ExecError:
            target = None   # 잘못된 경로는 실행이 실패 메시지를 낸다 / a bad path fails at run time with a message
        # 저장소 내부(.git) 쓰기는 묻지 않고 실행기가 거절한다(적대 검토 H1) / .git writes are refused by the executor, never asked
        if target is not None and tool in ("write_file", "edit_file") and agentic_exec.in_git_dir(target):
            return None
        if target is not None and not agentic_exec.inside(target, allowed_roots(session, settings)):
            return "outside"
    ask = session.get("perm_mode") == "ask"
    rules = session.get("rules")
    if tool == "bash":
        cmd = str(a.get("command") or "")
        if agentic_exec.matches_deny(cmd, settings.get("deny_commands") or []):
            return "deny_cmd"
        if rule_matches(rules, tool, a):
            return None
        if ask:
            return "ask_mode"
        return None if is_safe_command(cmd) else "auto_cmd"
    if ask and tool in ASK_TOOLS and not rule_matches(rules, tool, a):
        return "ask_mode"
    return None


# ────────────────────────────────────────────────────────
# 선언 목록 고르기(2차) / picking the declaration list (phase 2)
# ────────────────────────────────────────────────────────

def has_skills(session: dict, settings: dict) -> bool:
    """전역(설정) 또는 폴더(.ai365/skills)에 스킬이 하나라도 있는가(내 컴퓨터 폴더 세션은 전역만)
    Is there at least one global or folder skill (global ones only for a browser-folder session)"""
    if settings.get("skills"):
        return True
    folder = agentic_browser.server_folder(session)
    if not folder:
        return False
    try:
        from app import agentic_commands
        return bool(agentic_commands.load_folder_skills(folder))
    except Exception:  # noqa: BLE001 (모듈이 없거나 폴더를 못 읽으면 없는 셈 / none when the module or folder fails)
        return False


def specs_for(session: dict, settings: dict, preset: str | None = None, *, skills: bool | None = None) -> list[dict]:
    """이번 라운드에 선언할 도구: 1차 10개 + skill(스킬이 있을 때) + mcp_tool(세션 connectors 가 있을 때) + task(맨 위 루프만).
    preset(서브에이전트)이면 그 프리셋의 도구만(task 없음), 플랜 모드면 읽기 도구(PLAN_TOOLS)만. 순서는 ALL_SPECS 그대로라
    스킬 · 연결 도구가 없는 맨 위 루프는 TOOL_SPECS 와 같다. skills 를 주면 스킬 확인을 건너뛴다. 내 컴퓨터 폴더 세션은 bash ·
    task_output 을 빼고, task 는 명령 실행이 없는 설명(TASK_SPEC_BROWSER)으로 선언한다(프리셋 · 플랜 규칙은 그대로).
    The tools to declare this round: the ten phase-1 tools, skill (when skills exist), mcp_tool (when the session has
    connectors) and task (top-level loop only). A preset (subagent) keeps that preset's tools (never task); plan mode keeps
    the read tools only. The ALL_SPECS order is kept, so a top-level loop without skills or connectors equals TOOL_SPECS.
    A browser-folder session leaves out bash and task_output and declares task with the command-free description
    (TASK_SPEC_BROWSER); preset and plan rules stay."""
    with_skills = has_skills(session, settings) if skills is None else bool(skills)
    with_mcp = bool(session.get("connectors"))
    plan = session.get("perm_mode") == "plan"
    browser = agentic_browser.is_browser(session)
    allowed = PRESET_TOOLS.get(preset) if preset else None
    out = []
    for spec in ALL_SPECS:
        name = spec["name"]
        if (name == "skill" and not with_skills) or (name == "mcp_tool" and not with_mcp):
            continue
        if browser and name in BROWSER_NO_TOOLS:
            continue
        if name == "task" and preset:
            continue
        if allowed is not None and name not in allowed:
            continue
        if plan and name not in PLAN_TOOLS:
            continue
        out.append(TASK_SPEC_BROWSER if (browser and name == "task") else spec)
    return out


# ────────────────────────────────────────────────────────
# 이름 · 요약 / labels and summaries
# ────────────────────────────────────────────────────────

def _base(p) -> str:
    s = str(p or "").replace("\\", "/").rstrip("/")
    if s in ("", "."):
        return ""
    return s.rsplit("/", 1)[-1] or s


def label(name: str, args: dict) -> str:
    """사람이 읽는 한 줄 이름(예: 'README.md 편집', 'npm test 실행') / a human one-liner"""
    a = args if isinstance(args, dict) else {}
    if name == "read_file":
        return f"{_base(a.get('path')) or '파일'} 읽기"
    if name == "list_dir":
        return f"{_base(a.get('path')) or '작업 폴더'} 목록 보기"
    if name == "glob":
        return f"'{_short(a.get('pattern'), 40)}' 파일 찾기"
    if name == "grep":
        return f"'{_short(a.get('pattern'), 40)}' 검색"
    if name == "write_file":
        return f"{_base(a.get('path')) or '파일'} 쓰기"
    if name == "edit_file":
        return f"{_base(a.get('path')) or '파일'} 편집"
    if name == "bash":
        return f"{_short(a.get('command'), 60) or '명령'} 실행" + (" (백그라운드)" if _bool(a.get("background")) else "")
    if name == "task_output":
        return f"작업 {_short(a.get('task_id'), 20)} 출력 보기".replace("  ", " ")
    if name == "web_search":
        return f"'{_short(a.get('query'), 40)}' 웹 검색"
    if name == "fetch_page":
        url = str(a.get("url") or "")
        return f"{urlsplit(url).netloc or _short(url, 40) or '웹'} 페이지 읽기"
    if name == "task":
        return f"서브에이전트: {_short(a.get('description'), 60) or '작업'}"
    if name == "skill":
        return f"스킬 '{_short(a.get('name'), 40)}' 읽기"
    if name == "mcp_tool":
        return f"{mcp_label(a.get('connector_id'))} 호출"
    if name == "continue":
        return "작업 계속하기"
    return name


def mcp_label(connector_id) -> str:
    """MCP 도구 커넥터 이름(모르면 id) / the connector's name, or its id when unknown"""
    cid = str(connector_id or "").strip()
    try:
        from app import agentic_mcp
        return str(agentic_mcp.label(cid) or cid or "MCP 도구")
    except Exception:  # noqa: BLE001
        return cid or "MCP 도구"


def budget_label(budgets: dict) -> str:
    """예산 승인 카드의 이름 / the label of the budget approval card"""
    return f"작업 계속하기(한도: 도구 {budgets.get('max_steps')}회 · {budgets.get('max_minutes')}분)"


def args_summary(name: str, args: dict) -> str:
    """모델에 되돌려 줄 호출 요약 'name(k=v, …)'. 긴 본문은 길이만 / the call echoed back to the model; long bodies by length"""
    a = args if isinstance(args, dict) else {}
    parts = []
    for k, v in a.items():
        if k == "content":
            parts.append(f"content=<{len(str(v or '')):,}자>")
        elif k in ("old_string", "new_string"):
            parts.append(f"{k}={_short(v, 80)!r}")
        elif k == "command":
            parts.append(f"command={_short(v, 300)!r}")
        else:
            parts.append(f"{k}={_short(v, 120)}")
    return f"{name}({', '.join(parts)})"


def feedback(name: str, detail: str, settings: dict) -> str:
    """모델에 돌려줄 결과 본문(도구별 상한) / the result body fed back to the model, capped per tool"""
    cap = MODEL_DETAIL_BY_TOOL.get(name)
    if cap is None:
        if name in ("bash", "task_output"):
            cap = int((settings.get("budgets") or {}).get("max_output_chars") or 20000) + 500
        else:
            cap = MODEL_DETAIL_MAX
    return clip(detail, cap)


# ────────────────────────────────────────────────────────
# 도구 실행 / tool execution
# ────────────────────────────────────────────────────────

def _t_read(a, ex, settings, approved):
    r = ex.read(_req(a, "path"), offset=a.get("offset") or 1, limit=a.get("limit") or agentic_exec.READ_DEFAULT_LINES,
                allow_outside=approved)
    if r["lines"] == 0:
        return True, "빈 파일", "(빈 파일)", {}
    shown = (r["end"] - r["start"] + 1) if r["text"] else 0
    body = r["text"] or f"(offset {r['start']} 은 파일 끝을 넘었습니다. 파일은 {r['lines']}줄입니다)"
    partial = r["truncated"] or r["more"]
    if partial:
        body += f"\n(파일은 총 {r['lines']}줄입니다. 다음 부분은 offset={r['end'] + 1} 로 읽으세요)"
    return True, f"{shown}줄 읽음" + (" · 일부" if partial else ""), body, {"truncated": bool(r["truncated"])}


def _t_list(a, ex, settings, approved):
    r = ex.list_dir(a.get("path"), allow_outside=approved)
    rows = [("[폴더] " + e["name"]) if e["type"] == "dir" else f"[파일] {e['name']}  {_size(e['size'])}" for e in r["entries"]]
    body = f"{r['rel']} ({r['total']}개)\n" + ("\n".join(rows) or "(비어 있음)")
    if r["truncated"]:
        body += f"\n({agentic_exec.MAX_LIST}개까지만 보여 줍니다)"
    return True, f"{r['total']}개 항목", body, {"truncated": bool(r["truncated"])}


def _t_glob(a, ex, settings, approved):
    r = ex.glob(_req(a, "pattern"), a.get("path"), allow_outside=approved)
    body = "\n".join(r["paths"]) or "(일치하는 파일이 없습니다)"
    if r["truncated"]:
        body += f"\n(결과가 많아 {len(r['paths'])}개만 보여 줍니다" + (". 파일이 너무 많아 일부 폴더만 훑었습니다" if r["scan_capped"] else "") + ")"
    return True, f"{r['count']}개 파일", body, {"truncated": bool(r["truncated"])}


def _t_grep(a, ex, settings, approved):
    r = ex.grep(_req(a, "pattern"), a.get("path"), a.get("glob"), a.get("max") or agentic_exec.GREP_DEFAULT,
                allow_outside=approved)
    body = "\n".join(r["matches"]) or "(일치하는 곳이 없습니다)"
    if r["truncated"]:
        body += "\n(결과가 상한에 닿아 일부만 보여 줍니다)"
    summary = f"{r['count']}곳 일치" + (f" · 파일 {r['files']}개" if r["files"] else "")
    return True, summary, body, {"truncated": bool(r["truncated"])}


def _t_write(a, ex, settings, approved):
    path = _req(a, "path")
    if "content" not in a:
        raise ExecError("content 인자가 필요합니다")
    r = ex.write(path, a.get("content"), allow_outside=approved)
    # written(2차): 루프가 산출물(agentic_outputs)로 기록한다. 이벤트에는 싣지 않는다 / recorded as an output by the loop, not an event key
    written = {"path": r["path"], "kind": "created" if r["created"] else "modified", "bytes": r["bytes"]}
    if r["created"]:
        return True, f"새 파일 · {r['bytes']:,}바이트", f"{r['rel']} 파일을 만들었습니다({r['bytes']:,}바이트)", {"written": written}
    extra = {"written": written}
    if r["diff"] is not None:
        extra.update({"diff": {"path": r["rel"], "unified": clip(r["diff"], DIFF_MAX)}, "truncated": len(r["diff"]) > DIFF_MAX})
    return (True, f"덮어씀 · +{r['added']} -{r['removed']}",
            f"{r['rel']} 을(를) 덮어썼습니다({r['bytes']:,}바이트, +{r['added']} -{r['removed']}줄)", extra)


def _t_edit(a, ex, settings, approved):
    r = ex.edit(_req(a, "path"), a.get("old_string"), a.get("new_string"), _bool(a.get("replace_all")),
                allow_outside=approved)
    changed = max(r["added"], r["removed"])
    body = f"{r['rel']} 편집 완료({r['replaced']}곳, +{r['added']} -{r['removed']}줄)\n{r['diff']}"
    if "bytes" in r:   # 내 컴퓨터 폴더: 파일이 서버에 없어 실행기가 크기를 준다 / browser folders: the executor reports the size
        size = int(r.get("bytes") or 0)
    else:
        try:
            size = os.path.getsize(r["path"])
        except OSError:
            size = 0
    return (True, f"{changed}줄 바뀜", body,
            {"diff": {"path": r["rel"], "unified": clip(r["diff"], DIFF_MAX)}, "truncated": len(r["diff"]) > DIFF_MAX,
             "written": {"path": r["path"], "kind": "modified", "bytes": size}})


def _t_bash(a, ex, settings, approved):
    cmd = _req(a, "command")
    background = _bool(a.get("background"))
    r = ex.run(cmd, timeout_sec=a.get("timeout_sec"), background=background)
    if background:
        tid = r["task_id"]
        return (True, f"백그라운드 작업 {tid}",
                f"백그라운드로 띄웠습니다. 작업 id = {tid}. task_output 으로 출력과 상태를 확인하세요.", {"task_id": tid})
    code = r["exit_code"]
    if r["timed_out"]:
        ok, head, summary = False, f"시간 초과({r['timeout_sec']}초)로 명령을 끝냈습니다", f"시간 초과({r['timeout_sec']}초)"
    else:
        ok, head, summary = code == 0, f"종료 코드 {code}", f"종료 코드 {code} · {_secs(r['duration_ms'])}"
    detail = head + "\n" + (r["output"] or "(출력 없음)")
    return ok, summary, detail, {"output": r["output"], "exit_code": code, "truncated": bool(r["truncated"]),
                                 "duration_ms": r["duration_ms"]}


_TASK_STATE = {"running": "실행 중", "done": "완료", "error": "실패", "stopped": "중지됨"}


def _t_task_output(a, ex, settings, approved):
    r = ex.task_output(_req(a, "task_id"))
    state = _TASK_STATE.get(r["status"], r["status"])
    summary = state + (f" · 종료 코드 {r['exit_code']}" if r["exit_code"] is not None else "")
    detail = f"작업 {r['task_id']}: {summary}\n" + (r["output"] or "(아직 출력 없음)")
    return True, summary, detail, {"output": r["output"], "exit_code": r["exit_code"], "task_id": r["task_id"],
                                   "truncated": bool(r["truncated"])}


def _t_web_search(a, ex, settings, approved):
    q = _req(a, "query").strip()
    mx = _int(a.get("max"), 1, 10, 5)
    try:
        meta = llm.generate_grounded_meta(q, system=WEB_SYSTEM, tier="lite")
    except llm.GroundingUnavailableError as e:
        raise ExecError(f"웹 검색을 쓸 수 없습니다: {e}") from e
    text = str((meta or {}).get("text") or "").strip()
    srcs = [s for s in ((meta or {}).get("sources") or []) if isinstance(s, dict) and s.get("url")][:mx]
    rows = [f"{i}. {s.get('title') or s['url']} · {s['url']}" for i, s in enumerate(srcs, 1)]
    detail = "[요약]\n" + (text or "(요약 없음)") + "\n\n[출처]\n" + ("\n".join(rows) or "(출처 없음)")
    return bool(text or srcs), f"출처 {len(srcs)}개", detail, {}


_HEAD_RE = re.compile(r"<(script|style|noscript|template|svg|head)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_BREAK_RE = re.compile(r"<\s*(?:br|/p|/div|/li|/tr|/h[1-6]|/section|/article|/header|/footer|/table|/ul|/ol|/blockquote|/pre)\b[^>]*>",
                       re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title\s*>", re.IGNORECASE | re.DOTALL)
_SPACES_RE = re.compile(r"[ \t\r\f\v ]+")


def html_text(src: str) -> tuple[str, str]:
    """HTML → (제목, 본문 글): script · style · head · 주석을 걷고 태그를 지운 뒤 공백을 정리한다(정규식, 파서 없음).
    HTML → (title, text): drop scripts, styles, head and comments, strip tags, tidy whitespace (regex, no parser)."""
    m = _TITLE_RE.search(src or "")
    title = _SPACES_RE.sub(" ", html.unescape(_TAG_RE.sub("", m.group(1)))).strip() if m else ""
    s = _COMMENT_RE.sub(" ", src or "")
    s = _HEAD_RE.sub(" ", s)
    s = _BREAK_RE.sub("\n", s)
    s = _TAG_RE.sub(" ", s)
    s = html.unescape(s)
    lines = [_SPACES_RE.sub(" ", ln).strip() for ln in s.split("\n")]
    return title, "\n".join(ln for ln in lines if ln)


def _decode_page(data: bytes, charset: str | None) -> str:
    for enc in ([charset] if charset else []) + ["utf-8", "cp949"]:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


_TEXTUAL = ("text/", "application/json", "application/xml", "application/xhtml", "application/javascript", "+xml", "+json")


def _t_fetch_page(a, ex, settings, approved):
    url = _req(a, "url").strip()
    try:
        flow_api_call.check_url(url)   # 사설망 · 루프백 차단 / private-network and loopback guard
    except ValueError as e:
        raise ExecError(f"이 주소는 읽을 수 없습니다: {e}") from e
    try:
        with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=False, transport=TRANSPORT,
                          headers={"User-Agent": FETCH_UA, "Accept": "text/html,text/plain;q=0.9,*/*;q=0.5"}) as client:
            with client.stream("GET", url) as r:
                if 300 <= r.status_code < 400:
                    loc = r.headers.get("location") or ""
                    target = str(r.url.join(loc)) if loc else "(주소 없음)"
                    raise ExecError(f"HTTP {r.status_code} 리다이렉트: {target}. 리다이렉트는 따라가지 않으니 그 주소로 다시 부르세요")
                if r.status_code >= 400:
                    raise ExecError(f"HTTP {r.status_code}")
                ctype = (r.headers.get("content-type") or "").lower()
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf += chunk
                    if len(buf) >= FETCH_MAX_BYTES:
                        break
                charset = r.charset_encoding
    except httpx.TimeoutException as e:
        raise ExecError(f"시간 초과({FETCH_TIMEOUT}초)") from e
    except httpx.HTTPError as e:
        raise ExecError(f"연결 실패: {type(e).__name__}") from e
    data = bytes(buf)
    if ctype and not any(t in ctype for t in _TEXTUAL):
        raise ExecError(f"글이 아닌 내용입니다({ctype.split(';')[0]})")
    if b"\x00" in data[:8192]:
        raise ExecError("글이 아닌 내용입니다(이진)")
    raw = _decode_page(data, charset)
    title = ""
    if "html" in ctype or raw.lstrip()[:1] == "<":
        title, text = html_text(raw)
    else:
        text = "\n".join(ln.rstrip() for ln in raw.replace("\r\n", "\n").split("\n")).strip()
    truncated = len(text) > FETCH_MAX_CHARS
    text = text[:FETCH_MAX_CHARS]
    head = f"[{title}] {url}" if title else url
    body = head + "\n\n" + (text or "(본문 글이 없습니다)") + ("\n(30,000자에서 잘림)" if truncated else "")
    return True, f"{len(text):,}자 읽음" + (" · 일부" if truncated else ""), body, {"truncated": truncated}


def _t_skill(a, ex, settings, approved, session):
    """스킬 본문(폴더 스킬이 전역보다 앞선다, 내 컴퓨터 폴더 세션은 전역만) / a skill's text (folder skills win over global ones;
    global ones only for a browser-folder session)"""
    name = _req(a, "name").strip()
    from app import agentic_commands   # 지연 임포트 / lazy import
    sk = agentic_commands.find_skill(name, agentic_browser.server_folder(session), settings)
    if sk is None:
        raise ExecError(f"스킬을 찾지 못했습니다: {name}. 시스템 프롬프트의 [사용 가능한 스킬] 목록에 있는 이름을 쓰세요")
    text = clip(agentic_commands.skill_text(sk), SKILL_TEXT_MAX + 2000)
    return True, f"스킬 {_short(name, 40)} · {len(text):,}자", text, {}


def _t_mcp(a, ex, settings, approved, session):
    """세션에 켠 MCP 도구 호출(agentic_mcp.call). 세션 connectors 에 없는 id 는 거절 / call an MCP tool turned on for the session"""
    cid = _req(a, "connector_id").strip()
    if cid not in (session.get("connectors") or []):
        raise agentic_exec.RefusedError(f"이 세션에 연결되지 않은 도구입니다: {cid}. 환경 패널 Connectors 에서 켜야 쓸 수 있습니다")
    allowed = allowed_connector_ids(session.get("owner"))   # 호출 때마다 다시 본다(권한을 거둔 뒤에도) / re-checked per call
    if allowed is not None and cid not in allowed:
        raise agentic_exec.RefusedError(f"이 연결 도구를 쓸 권한이 없습니다: {cid}. 관리 센터 › 접근 권한 설정의 API 권한이 필요합니다")
    raw = a.get("inputs_json")
    if isinstance(raw, (dict, list)):   # 모델이 문자열 대신 객체로 준 경우 / the model sent an object instead of a string
        raw = json.dumps(raw, ensure_ascii=False)
    from app import agentic_mcp   # 지연 임포트 / lazy import
    ok, summary, detail, extra = agentic_mcp.call(cid, "" if raw is None else str(raw))
    return bool(ok), str(summary or ""), str(detail or ""), dict(extra or {})


_TOOLS = {"read_file": _t_read, "list_dir": _t_list, "glob": _t_glob, "grep": _t_grep, "write_file": _t_write,
          "edit_file": _t_edit, "bash": _t_bash, "task_output": _t_task_output, "web_search": _t_web_search,
          "fetch_page": _t_fetch_page}
_SESSION_TOOLS = {"skill": _t_skill, "mcp_tool": _t_mcp}   # 세션(폴더 · connectors)이 필요한 도구 / tools that need the session


def run_tool(session: dict, name: str, args: dict, executor: agentic_exec.Executor, settings: dict,
             approved: bool = False) -> tuple[bool, str, str, dict]:
    """도구 1회 실행 → (ok, summary, detail, extra). approved=True 는 승인 카드에서 허용된 호출(허용 폴더 밖도 다룬다).
    실패는 ok=False + 사람이 읽는 메시지(예외를 올리지 않는다). 동기 함수라 호출부가 스레드에서 부른다.
    One tool call → (ok, summary, detail, extra). approved=True marks a call allowed on an approval card (it may touch
    paths outside the allowed folders). Failures return ok=False with a readable message instead of raising. Synchronous:
    callers run it in a worker thread."""
    t0 = time.monotonic()
    a = args if isinstance(args, dict) else {}
    try:
        if name == "task":   # 서브에이전트는 루프가 돌린다 / subagents are run by the loop
            raise ExecError("task 는 이 자리에서 실행할 수 없습니다(서브에이전트 안에서는 task 를 쓸 수 없습니다)")
        if name in _SESSION_TOOLS:
            ok, summary, detail, extra = _SESSION_TOOLS[name](a, executor, settings, approved, session)
        else:
            fn = _TOOLS.get(name)
            if fn is None:
                raise ExecError(f"알 수 없는 도구입니다: {name}")
            ok, summary, detail, extra = fn(a, executor, settings, approved)
    except ExecError as e:
        msg = str(e) or "도구 실행에 실패했습니다"
        # refused = 정책상 거절(루프가 연속 거절로 센다) / refused = a policy refusal, counted by the loop
        ok, summary, detail, extra = False, _short(msg, 80), msg, ({"refused": True} if isinstance(e, agentic_exec.RefusedError) else {})
    except Exception as e:  # noqa: BLE001 (도구 하나의 오류가 루프를 죽이지 않는다 / one tool error never kills the loop)
        logger.exception("Agentic 도구 오류 tool=%s", name)
        ok, summary, detail, extra = False, "도구 실행 오류", f"도구 실행 중 오류가 났습니다: {type(e).__name__}: {_short(e, 300)}", {}
    extra = dict(extra or {})
    extra.setdefault("duration_ms", int((time.monotonic() - t0) * 1000))
    extra.setdefault("truncated", False)
    return ok, summary, detail, extra
