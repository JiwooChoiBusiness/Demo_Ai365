"""Agentic 모드 슬래시 명령 · 스킬(2026-10-19, 3차): 내장 명령 목록, '/이름 인자' 가르기, 폴더 · 전역 명령과 스킬의
불러오기 · 검증 · 펼치기, 스킬 목록 프롬프트, /help 글.

- 내장 명령(BUILTINS)은 runner 가 LLM 턴 없이 바로 처리한다. 사용자 명령 · 스킬은 내장 이름을 덮을 수 없다(목록 · 찾기에서
  빼고, 전역 저장 때는 거절한다).
- 사용자 명령 = 프롬프트 템플릿: 폴더 <폴더>/.ai365/commands/<이름>.md(파일 이름 = 명령 이름, 소문자로) + 전역(관리 센터
  settings.commands). 이름이 겹치면 폴더가 이긴다. 본문의 $ARGUMENTS 를 인자로 바꾸고, 없으면 끝에 "[인자] …" 를 붙인다.
- 스킬 = 지시 문서: 폴더 <폴더>/.ai365/skills/<이름>/SKILL.md(+ 그 폴더 아래 보조 파일 목록, 상대 경로 200개, 숨김 폴더 제외)
  + 전역(settings.skills). 이름 = front matter 의 name 또는 폴더 이름. 모델은 skills_prompt() 목록을 보고 skill 도구로 읽는다.
  /이름 이 명령과 스킬에 모두 있으면 명령이 이긴다(list_all 도 그 스킬을 빼서 보여 준다).
- front matter = 맨 앞 '---' 블록 안의 'key: value' 줄만(YAML 라이브러리 없이, 여러 줄 값은 없다. 키는 소문자로).
- 이름 규칙 ^[a-z0-9][a-z0-9_-]{0,39}$, 50개 · 본문 20,000자 상한. 폴더 밖을 가리키는 링크 파일은 읽지 않는다.
- 이 모듈은 agentic_store 를 import 하지 않는다(저장소가 설정 검증에 이 모듈을 부른다). agentic_exec 도 함수 안에서 부른다.
"""
# Agentic mode slash commands and skills (2026-10-19, phase 3): the built-in command list, splitting '/name args',
# loading, validating and expanding folder and global commands and skills, the skills prompt and the /help text.
# - Built-ins (BUILTINS) are handled by the runner without an LLM turn. User commands and skills can never shadow a
#   built-in name (left out of lists and lookups, rejected when saving global ones).
# - A user command is a prompt template: <folder>/.ai365/commands/<name>.md (file name = command name, lower-cased) plus
#   the global ones (Admin Center settings.commands); the folder wins on a name clash. $ARGUMENTS in the body becomes
#   the arguments, otherwise "[인자] …" is appended.
# - A skill is an instruction document: <folder>/.ai365/skills/<name>/SKILL.md (plus the helper files below that folder,
#   relative paths, 200 at most, hidden folders skipped) and the global ones (settings.skills). Name = the front-matter
#   name or the folder name. The model sees skills_prompt() and reads a skill with the skill tool. When /name is both a
#   command and a skill the command wins (list_all leaves that skill out).
# - Front matter = the 'key: value' lines of a leading '---' block only (no YAML library, no multi-line values, keys
#   lower-cased).
# - Names match ^[a-z0-9][a-z0-9_-]{0,39}$; 50 items and 20,000-char bodies at most; link files pointing outside the
#   folder are never read.
# - This module never imports agentic_store (the store calls it to validate settings); agentic_exec is imported lazily.

from __future__ import annotations

import os
import re

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
MAX_ITEMS = 50
MAX_BODY = 20_000
MAX_DESC = 300
DESC_FROM_BODY = 120          # 본문 첫 줄로 만든 설명의 상한 / cap of a description taken from the body
MAX_ARGS_HINT = 80
SKILL_FILES_MAX = 200
SKILLS_PROMPT_MAX = 30
FILE_MAX_BYTES = 1024 * 1024  # 명령 · 스킬 파일을 읽는 상한 / bytes read from a command or skill file
COMMANDS_DIR = (".ai365", "commands")
SKILLS_DIR = (".ai365", "skills")
SKILL_FILE = "SKILL.md"

BUILTINS = [
    {"name": "help", "description": "명령과 스킬 목록을 봅니다", "args": ""},
    {"name": "compact", "description": "지난 대화를 요약해 컨텍스트를 줄입니다", "args": ""},
    {"name": "plan", "description": "플랜 모드로 바꿉니다(읽기 · 조사만 하고 계획을 냅니다)", "args": ""},
    {"name": "auto", "description": "Auto 모드로 바꿉니다", "args": ""},
    {"name": "ask", "description": "묻기 모드로 바꿉니다(편집 · 명령마다 승인)", "args": ""},
    {"name": "model", "description": "모델을 바꿉니다", "args": "<모델 id>"},
    {"name": "clear", "description": "같은 폴더 · 모델 · 권한으로 새 세션을 엽니다", "args": ""},
    {"name": "checkpoint", "description": "지금 파일 상태로 체크포인트를 만듭니다", "args": "[이름]"},
    {"name": "undo", "description": "가장 최근 체크포인트로 파일을 되돌립니다", "args": ""},
    {"name": "commit", "description": "변경을 git 커밋합니다(메시지가 없으면 에이전트가 정리)", "args": "[메시지]"},
    {"name": "cost", "description": "도구 호출 수 · 일한 시간 · 토큰 추정을 봅니다", "args": ""},
    {"name": "init", "description": "폴더를 살펴 AGENTS.md 를 만들거나 보완합니다", "args": ""},
    {"name": "notify", "description": "완료 알림(메일)을 켜거나 끕니다", "args": "on|off"},
    {"name": "skills", "description": "쓸 수 있는 스킬 목록을 봅니다", "args": ""},
    {"name": "hooks", "description": "적용 중인 훅 목록을 봅니다", "args": ""},
    {"name": "connectors", "description": "이 세션에 연결된 도구 목록을 봅니다", "args": ""},
]
BUILTIN_NAMES = frozenset(b["name"] for b in BUILTINS)

# '/' 다음 첫 글자는 공백 · '/' 가 아니다(경로 · '//' 주석은 명령이 아니다) / no space or '/' right after the slash
_SLASH_RE = re.compile(r"^\s*/([^\s/]\S*)(?:\s+(.*))?$", re.DOTALL)


def _ex():
    """agentic_exec 지연 import(agentic_store → 이 모듈 → agentic_exec → agentic_store 순환 방지) / lazy import, no cycle"""
    from app import agentic_exec
    return agentic_exec


def _one_line(s, cap: int) -> str:
    return re.sub(r"\s+", " ", str(s if s is not None else "")).strip()[:cap]


# ────────────────────────────────────────────────────────
# 가르기 / parsing
# ────────────────────────────────────────────────────────

def parse_slash(text) -> tuple[str, str] | None:
    """'/name args…' → ("name", "args"). 앞 공백 허용, 이름은 소문자로 바꿔 이름 규칙을 지켜야 한다. '/' 뒤 공백 · '//' ·
    규칙 밖 이름(경로 '/usr/bin' · 한글)은 None. 있는 명령인지는 보지 않는다(호출부가 내장 · 사용자 · 스킬을 찾는다).
    '/name args…' → ("name", "args"); leading spaces allowed; the lower-cased name must follow the naming rule. A space
    or '/' after the slash, or a name off the rule (a path, Korean) gives None. Existence is the caller's check."""
    if not isinstance(text, str):
        return None
    m = _SLASH_RE.match(text)
    if not m:
        return None
    name = m.group(1).lower()
    if not NAME_RE.match(name):
        return None
    return name, (m.group(2) or "").strip()


def parse_front_matter(text) -> tuple[dict, str]:
    """맨 앞 '---' 블록의 'key: value' 줄 → (dict, 본문). 키는 소문자, 값의 바깥 따옴표는 벗긴다. 닫는 '---' 가 없으면
    front matter 가 없는 것으로 본다. 본문은 앞뒤 빈 줄을 뺀다.
    The 'key: value' lines of a leading '---' block → (dict, body); keys lower-cased, outer quotes removed. Without a
    closing '---' there is no front matter. The body loses its leading and trailing blank lines."""
    s = str(text if text is not None else "")
    if s.startswith("﻿"):
        s = s[1:]
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    lines = s.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, s.strip("\n")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), None)
    if end is None:
        return {}, s.strip("\n")
    meta: dict = {}
    for ln in lines[1:end]:
        t = ln.strip()
        if not t or t.startswith("#") or ":" not in t:
            continue
        k, v = t.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if k and k not in meta:
            meta[k] = v
    return meta, "\n".join(lines[end + 1:]).strip("\n")


def _describe(meta: dict, body: str) -> str:
    """front matter 의 description, 없으면 본문 첫 줄(제목 # 은 벗긴다) / the description, else the body's first line"""
    d = _one_line(meta.get("description"), MAX_DESC)
    if d:
        return d
    for ln in body.split("\n"):
        t = ln.strip().lstrip("#").strip()
        if t:
            return _one_line(t, DESC_FROM_BODY)
    return ""


def _args_hint(meta: dict, body: str) -> str:
    """인자 힌트: front matter 의 args(또는 argument-hint), 없으면 본문에 $ARGUMENTS 가 있을 때 '[인자]' / the args hint"""
    hint = _one_line(meta.get("args") or meta.get("argument-hint"), MAX_ARGS_HINT)
    return hint or ("[인자]" if "$ARGUMENTS" in body else "")


# ────────────────────────────────────────────────────────
# 폴더에서 불러오기 / loading from the folder
# ────────────────────────────────────────────────────────

def _root(folder) -> str:
    """폴더 → realpath. None · '' 은 "폴더 없음"(''): 내 컴퓨터 폴더 세션은 None 을 넘겨 전역 명령 · 스킬만 쓴다(2026-10-20)
    The folder's realpath; None and '' mean "no folder" (''): browser-folder sessions pass None and get global items only"""
    if not folder:
        return ""
    try:
        return os.path.realpath(str(folder))
    except (OSError, ValueError):
        return ""


def _read_text(path: str, root: str) -> str | None:
    """폴더 안의 글 파일만(밖을 가리키는 링크 · 이진 · 못 읽는 파일은 None), 앞 1MB / text files inside the folder only"""
    ex = _ex()
    try:
        if not os.path.isfile(path) or not ex.inside(path, [root]):
            return None
        with open(path, "rb") as f:
            data = f.read(FILE_MAX_BYTES)
        return ex._decode_text(data)[0]
    except (OSError, ex.ExecError):
        return None


def _listdir(path: str) -> list[str]:
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


def load_folder_commands(folder) -> list[dict]:
    """<폴더>/.ai365/commands/*.md → [{"name"(파일 이름, 소문자), "description", "body", "args", "source": "folder"}].
    이름 규칙 밖 · 빈 본문 · 폴더 밖 링크는 건너뛴다(50개까지, 이름순). 내장과 같은 이름도 여기서는 그대로 돌려준다.
    Folder commands; names off the rule, empty bodies and outside links are skipped (50 at most, by name). Built-in
    names are returned as they are here (list_all and find_command leave them out)."""
    root = _root(folder)
    if not root:
        return []
    d = os.path.join(root, *COMMANDS_DIR)
    if not os.path.isdir(d):
        return []
    out, seen = [], set()
    for fn in _listdir(d):
        if len(out) >= MAX_ITEMS:
            break
        stem, ext = os.path.splitext(fn)
        name = stem.lower()
        if ext.lower() != ".md" or not NAME_RE.match(name) or name in seen:
            continue
        text = _read_text(os.path.join(d, fn), root)
        if text is None:
            continue
        meta, body = parse_front_matter(text)
        if not body.strip():
            continue
        seen.add(name)
        out.append({"name": name, "description": _describe(meta, body), "body": body[:MAX_BODY],
                    "args": _args_hint(meta, body), "source": "folder"})
    return out


def _find_skill_md(sdir: str) -> str | None:
    exact = os.path.join(sdir, SKILL_FILE)
    if os.path.isfile(exact):
        return exact
    for n in _listdir(sdir):
        if n.lower() == SKILL_FILE.lower() and os.path.isfile(os.path.join(sdir, n)):
            return os.path.join(sdir, n)
    return None


def _skill_files(sdir: str, root: str, skill_md: str) -> list[str]:
    """스킬 폴더 아래 보조 파일(SKILL.md 제외, 숨김 · 무거운 폴더와 폴더 밖 링크 제외) 상대 경로, 200개까지
    Helper files below the skill folder as relative paths (no SKILL.md, hidden or heavy folders, or outside links)"""
    ex = _ex()
    skip = ex.SKIP_DIRS
    own = os.path.normcase(os.path.realpath(skill_md))
    files: list[str] = []
    for cur, dirs, names in os.walk(sdir):
        dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x not in skip
                         and ex.inside(os.path.join(cur, x), [root]))
        for n in sorted(names):
            full = os.path.join(cur, n)
            if os.path.normcase(os.path.realpath(full)) == own or not ex.inside(full, [root]):
                continue
            files.append(os.path.relpath(full, sdir).replace("\\", "/"))
            if len(files) >= SKILL_FILES_MAX:
                return sorted(files)
    return sorted(files)


def load_folder_skills(folder) -> list[dict]:
    """<폴더>/.ai365/skills/*/SKILL.md → [{"name", "description", "body", "dir"(절대 경로), "files": [상대 경로],
    "source": "folder"}]. name = front matter 의 name(규칙에 맞을 때) 또는 폴더 이름(소문자). 숨김 폴더 · 빈 본문은 건너뛴다.
    Folder skills; name = the front-matter name when valid, else the folder name (lower-cased); hidden folders and empty
    bodies are skipped (50 at most)."""
    root = _root(folder)
    if not root:
        return []
    d = os.path.join(root, *SKILLS_DIR)
    if not os.path.isdir(d):
        return []
    ex = _ex()
    out, seen = [], set()
    for entry in _listdir(d):
        if len(out) >= MAX_ITEMS:
            break
        sdir = os.path.join(d, entry)
        if entry.startswith(".") or not os.path.isdir(sdir) or not ex.inside(sdir, [root]):
            continue
        skill_md = _find_skill_md(sdir)
        text = _read_text(skill_md, root) if skill_md else None
        if text is None:
            continue
        meta, body = parse_front_matter(text)
        if not body.strip():
            continue
        name = str(meta.get("name") or "").strip().lower()
        if not NAME_RE.match(name):
            name = entry.lower()
        if not NAME_RE.match(name) or name in seen:
            continue
        seen.add(name)
        real = os.path.realpath(sdir)
        out.append({"name": name, "description": _describe(meta, body), "body": body[:MAX_BODY], "dir": real,
                    "files": _skill_files(real, root, skill_md), "source": "folder"})
    return out


# ────────────────────────────────────────────────────────
# 검증(전역 설정) / validation (global settings)
# ────────────────────────────────────────────────────────

def _item(item, i: int, label: str) -> dict:
    """명령 · 스킬 하나 검증 → {"name", "description", "body"}. 이름은 소문자로. 틀리면 ValueError / validate one item"""
    if not isinstance(item, dict):
        raise ValueError(f"{label} {i}: 객체여야 합니다")
    raw = item.get("name")
    name = raw.strip().lower() if isinstance(raw, str) else ""
    if not NAME_RE.match(name):
        raise ValueError(f"{label} {i}: 이름은 영문 소문자 · 숫자 · _ · - 로 1~40자이고 영문 소문자나 숫자로 시작합니다")
    if name in BUILTIN_NAMES:
        raise ValueError(f"{label} {i}: 내장 명령과 같은 이름은 쓸 수 없습니다: {name}")
    desc = item.get("description")
    if desc is None:
        desc = ""
    if not isinstance(desc, str):
        raise ValueError(f"{label} {i}: 설명은 문자열이어야 합니다")
    desc = _one_line(desc, MAX_DESC + 1)
    if len(desc) > MAX_DESC:
        raise ValueError(f"{label} {i}: 설명은 {MAX_DESC}자까지입니다")
    body = item.get("body")
    if not isinstance(body, str) or not body.strip():
        raise ValueError(f"{label} {i}: 본문이 비어 있습니다")
    body = body.replace("\r\n", "\n").strip()
    if len(body) > MAX_BODY:
        raise ValueError(f"{label} {i}: 본문은 {MAX_BODY:,}자까지입니다")
    return {"name": name, "description": desc, "body": body}


def _validate(raw, key: str, label: str) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{key} 는 목록이어야 합니다")
    if len(raw) > MAX_ITEMS:
        raise ValueError(f"{label}은(는) {MAX_ITEMS}개까지입니다")
    out, seen = [], set()
    for i, item in enumerate(raw, 1):
        x = _item(item, i, label)
        if x["name"] in seen:
            raise ValueError(f"{label} 이름이 겹칩니다: {x['name']}")
        seen.add(x["name"])
        out.append(x)
    return out


def validate_commands(raw) -> list[dict]:
    """전역 명령 목록 검증 → [{"name", "description", "body"}]. 이름 규칙 · 내장 이름 금지 · 중복 금지 · 50개 · 설명 300자 ·
    본문 20,000자(비면 안 됨). None = []. 틀리면 ValueError.
    Validate the global commands: naming rule, no built-in names, no duplicates, 50 items, 300-char descriptions,
    non-empty bodies up to 20,000 chars; None = []; ValueError otherwise."""
    return _validate(raw, "commands", "명령")


def validate_skills(raw) -> list[dict]:
    """전역 스킬 목록 검증(명령과 같은 규칙) / validate the global skills (same rules as commands)"""
    return _validate(raw, "skills", "스킬")


def _lenient(raw, label: str) -> list[dict]:
    """저장된 전역 항목 읽기: 틀리거나 겹치는 항목만 건너뛴다 / stored global items, skipping bad or duplicate ones"""
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for item in raw[:MAX_ITEMS]:
        try:
            x = _item(item, len(out) + 1, label)
        except ValueError:
            continue
        if x["name"] not in seen:
            seen.add(x["name"])
            out.append(x)
    return out


# ────────────────────────────────────────────────────────
# 합치기 · 찾기 / merging and lookups
# ────────────────────────────────────────────────────────

def _commands(folder, settings) -> dict:
    """사용자 명령 = 전역 위에 폴더(같은 이름은 폴더), 내장 이름 제외 / user commands, the folder over the global ones"""
    merged = {}
    for c in _lenient((settings or {}).get("commands"), "명령"):
        merged[c["name"]] = {**c, "args": _args_hint({}, c["body"]), "source": "global"}
    for c in load_folder_commands(folder):
        if c["name"] not in BUILTIN_NAMES:
            merged[c["name"]] = c
    return merged


def _skills(folder, settings) -> dict:
    """스킬 = 전역 위에 폴더(같은 이름은 폴더), 내장 이름 제외 / skills, the folder over the global ones"""
    merged = {}
    for s in _lenient((settings or {}).get("skills"), "스킬"):
        merged[s["name"]] = {**s, "dir": "", "files": [], "source": "global"}
    for s in load_folder_skills(folder):
        if s["name"] not in BUILTIN_NAMES:
            merged[s["name"]] = s
    return merged


def _key(name) -> str:
    n = str(name if name is not None else "").strip().lower()
    return n[1:] if n.startswith("/") else n


def find_command(name, folder, settings) -> dict | None:
    """사용자 명령 하나(폴더 > 전역), 내장 이름 · 없는 이름이면 None / one user command, None for built-ins and unknowns"""
    n = _key(name)
    if not NAME_RE.match(n) or n in BUILTIN_NAMES:
        return None
    return _commands(folder, settings).get(n)


def find_skill(name, folder, settings) -> dict | None:
    """스킬 하나(폴더 > 전역): {"name", "description", "body", "dir", "files", "source"}, 없으면 None / one skill or None"""
    n = _key(name)
    if not NAME_RE.match(n) or n in BUILTIN_NAMES:
        return None
    return _skills(folder, settings).get(n)


def list_all(folder, settings, connectors_count=0) -> list[dict]:
    """/commands 목록 [{"name", "description", "source": builtin|folder|global|skill, "args"}]: 내장 먼저(이름순) 다음 사용자
    명령과 스킬(이름순). 내장과 겹치는 사용자 이름은 빼고, 명령과 겹치는 스킬도 뺀다(/이름 은 명령이 이긴다).
    The /commands list: built-ins first (by name), then user commands and skills (by name). User names clashing with a
    built-in are left out, and so are skills clashing with a command (/name runs the command)."""
    cmds = _commands(folder, settings)
    skills = [s for s in _skills(folder, settings).values() if s["name"] not in cmds]   # 명령이 이긴다 / commands win
    try:
        n_conn = int(connectors_count or 0)
    except (TypeError, ValueError):
        n_conn = 0
    out = []
    for b in sorted(BUILTINS, key=lambda x: x["name"]):
        desc = b["description"]
        if b["name"] == "skills" and skills:
            desc += f" · {len(skills)}개"
        elif b["name"] == "connectors" and n_conn > 0:
            desc += f" · 연결 {n_conn}개"
        out.append({"name": b["name"], "description": desc, "source": "builtin", "args": b["args"]})
    rest = [{"name": c["name"], "description": c["description"], "source": c["source"], "args": c.get("args") or ""}
            for c in cmds.values()]
    rest += [{"name": s["name"], "description": s["description"], "source": "skill", "args": "[요청]"} for s in skills]
    return out + sorted(rest, key=lambda x: x["name"])


# ────────────────────────────────────────────────────────
# 펼치기 · 프롬프트 · 글 / expansion, prompts and texts
# ────────────────────────────────────────────────────────

def expand(body, args) -> str:
    """명령 본문 펼치기: $ARGUMENTS 를 인자로 바꾼다. 자리가 없으면 끝에 '\\n\\n[인자] <인자>' 를 붙이고, 인자가 비면 그대로.
    Expand a command body: $ARGUMENTS becomes the arguments; without the placeholder '\\n\\n[인자] <args>' is appended,
    and empty arguments leave the body as it is."""
    b = str(body if body is not None else "")
    a = str(args if args is not None else "").strip()
    if "$ARGUMENTS" in b:
        return b.replace("$ARGUMENTS", a)
    return f"{b}\n\n[인자] {a}" if a else b


def skills_prompt(folder, settings) -> str:
    """시스템 프롬프트용 스킬 목록 "[사용 가능한 스킬]\\n- name: description"(이름순 30개), 스킬이 없으면 ""
    The skills list for the system prompt (30 by name), "" without skills"""
    skills = sorted(_skills(folder, settings).values(), key=lambda s: s["name"])
    if not skills:
        return ""
    lines = ["[사용 가능한 스킬]"]
    for s in skills[:SKILLS_PROMPT_MAX]:
        d = _one_line(s.get("description"), 200)
        lines.append(f"- {s['name']}: {d}" if d else f"- {s['name']}")
    return "\n".join(lines)


def skill_text(skill) -> str:
    """skill 도구 결과: 본문(20,000자, 넘으면 자른 표시) + 폴더 스킬이면 '같은 폴더의 파일(<폴더>): a, b'
    The skill tool's result: the body (20,000 chars, a note when cut) plus the helper files of a folder skill"""
    s = skill if isinstance(skill, dict) else {}
    body = str(s.get("body") or "")
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY] + f"\n…(본문이 길어 {MAX_BODY:,}자에서 잘랐습니다)"
    files = [str(f) for f in (s.get("files") or [])][:SKILL_FILES_MAX]
    if not files:
        return body
    where = str(s.get("dir") or "")
    return body + "\n\n같은 폴더의 파일" + (f"({where})" if where else "") + ": " + ", ".join(files)


def help_text(folder, settings, connectors=0) -> str:
    """/help 글(마크다운): 내장 명령 · 사용자 명령(폴더 · 전역 표시) · 스킬과 폴더에 더하는 방법
    The /help text (Markdown): built-ins, user commands (marked folder or global), skills and how to add them"""
    items = list_all(folder, settings, connectors)

    def row(x: dict) -> str:
        cmd = f"/{x['name']}" + (f" {x['args']}" if x["args"] else "")
        return f"- `{cmd}` {x['description']}".rstrip()

    builtin = [row(x) for x in items if x["source"] == "builtin"]
    user = [row(x) + (" (폴더)" if x["source"] == "folder" else " (전역)") for x in items if x["source"] in ("folder", "global")]
    skills = [row(x) for x in items if x["source"] == "skill"]
    parts = ["**내장 명령**", *builtin, "", "**사용자 명령**", *(user or ["- 없음"]), "", "**스킬**", *(skills or ["- 없음"]), "",
             "작업 폴더의 `.ai365/commands/<이름>.md` 는 명령, `.ai365/skills/<이름>/SKILL.md` 는 스킬이 됩니다. "
             "명령 본문의 `$ARGUMENTS` 는 명령 뒤에 쓴 글로 바뀝니다."]
    return "\n".join(parts)
