"""Agentic 모드 API(2026-10-19, prefix /api/agentic). 모든 요청에 acting_user_id(뷰애즈 신원, '' = 슈퍼).

권한(_guard, 이 라우터만의 규칙 · 적대 검토 C1 반영):
- 원격 클라이언트 정책(2026-10-20, 배포 서버): 루프백(127.0.0.1 · ::1)이 아닌 요청(_is_remote)은 **내 컴퓨터 폴더(browser) 세션만**
  쓴다. 서버 PC 에서 명령을 돌리는 서버 폴더(local) 세션은 만들 수도(403) 열 수도(세션 단위 엔드포인트 전부 403) 없고, 목록에서도
  빠진다. 서버 폴더 고르기(pick-folder · browse)와 설정 PUT 도 403. 모델 · 설정 GET · 연결 도구 · extract 는 된다. 설정 GET 의
  remote 가 이 판정이다. settings.AGENTIC_ALLOW_REMOTE=1 이면 종전처럼 원격도 로컬과 같다. 로컬(루프백) 요청은 종전과 같다.
- acting_user_id 가 비어 있지 않은데 숫자가 아니면 403. 다른 API 의 "비숫자 = 슈퍼" 관례는 여기서 받지 않는다(슈퍼 = 빈 값뿐).
- 그다음 resources_api._eff 의 실효 권한: eff 가 None(슈퍼)이거나 메뉴 권한 m_agentic 이 있으면 통과, 아니면 403
  "Agentic 모드 권한이 없습니다". 세션은 소유자만(남의 세션은 404). 설정 PUT 은 슈퍼만.
세션 · 메시지 · 승인 · 중단 · 이벤트 · SSE 스트림 · 파일 보기 · background 작업 목록을 낸다. 실행은 agentic_runner 가 하고,
이벤트(agentic_events)가 트랜스크립트의 단일 원본이라 스트림은 after 이후를 DB 에서 재생한 뒤 라이브로 잇는다.
2차(2026-10-19): 메시지 mode(auto · steer · queue)와 슬래시 명령(실행 중 409), 연결 도구 · 명령 목록, 화면이 본 seq, 체크포인트
(만들기 · 되돌리기), 산출물(목록 · 내려받기), git 변경 · diff · 커밋 · 커밋 메시지 제안. git 은 agentic_git 을 스레드에서 부른다.
폴더 고르기(2026-10-19): POST /pick-folder = 서버 PC 에 운영체제 폴더 선택 창(자식 프로세스 agentic_pick, 한 번에 하나, 열려
있으면 409, 띄울 수 없거나 시간 초과 · 원격 요청이면 503 → 프런트가 앱 안 탐색기로), GET /browse = 앱 안 탐색기의 하위 폴더 목록
(빈 path = 허용 폴더(슈퍼는 드라이브도), 슈퍼가 아니면 허용 폴더 안만). 설정 응답의 folder_picker=true 가 이 기능이 있다는 표시다.
내 컴퓨터 폴더(2026-10-20, docs/agentic-browser-folder-contract.md E): POST /sessions 의 kind=browser(folder = 폴더 이름, 허용 폴더
검사 없음), 브라우저 실행기의 답 POST …/tool-results · 대기 요청 GET …/tool-requests, 문서 본문 뽑기 POST /extract(multipart),
스트림의 transient 이벤트(event: tool_request). 서버 폴더가 필요한 기능(files · 내려받기 · git · 체크포인트)은 브라우저 세션에 409.
설정 응답의 browser_folders=true 가 이 기능의 표시다.
"""
# Agentic mode API (2026-10-19, prefix /api/agentic). Every request carries acting_user_id (view-as identity, '' = super).
# Permission (_guard, rules of this router only, from adversarial review C1). The remote-client policy (2026-10-20, the
# deployed server): a non-loopback request (_is_remote) may use browser-folder sessions only. Server-folder (local)
# sessions, which run commands on the server PC, can be neither created (403) nor opened (403 on every session endpoint)
# and are left out of the list; picking server folders (pick-folder, browse) and settings PUT are 403 too, while models,
# settings GET, connectors and extract work. remote in the settings answer is this check. settings.AGENTIC_ALLOW_REMOTE=1
# keeps the old behavior (remote = local). Loopback requests behave exactly as before. A non-empty, non-numeric
# acting_user_id gets 403 (the "non-digit = super" convention of other APIs is refused here, super is the empty id only);
# then resources_api._eff: eff None (super) or the m_agentic menu permission passes, anything else is 403. Sessions
# belong to their owner (others get 404). Settings PUT is super only.
# Sessions, messages, approvals, stop, events, the SSE stream, file viewing and background tasks. agentic_runner runs the
# loop; the events table is the transcript's single source, so the stream replays from the DB after `after`, then goes live.
# Phase 2 (2026-10-19): message modes (auto, steer, queue) and slash commands (409 while running), connector and command
# lists, the seen seq, checkpoints (create, restore), outputs (list, download), git changes, diffs, commits and commit
# message suggestions. agentic_git runs in worker threads.
# Folder picking (2026-10-19): POST /pick-folder shows the operating system's folder window on the server PC (the child
# process agentic_pick, one at a time, 409 while one is open, 503 when it cannot open, times out or the request is remote,
# so the front end falls back to the in-app explorer); GET /browse lists subfolders for the in-app explorer (an empty path
# lists the allowed folders, plus the drives for the super admin; others stay inside the allowed folders). folder_picker
# = true in the settings answer advertises the feature.
# Folders on my computer (2026-10-20, docs/agentic-browser-folder-contract.md E): POST /sessions with kind=browser
# (folder = the folder name, no allowed-folder check), the browser executor's answers POST …/tool-results and pending
# requests GET …/tool-requests, document text extraction POST /extract (multipart) and the stream's transient events
# (event: tool_request). Features that need a server folder (files, downloads, git, checkpoints) answer 409 for browser
# sessions. browser_folders = true in the settings answer advertises the feature.

import asyncio
import ipaddress
import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app import agentic_browser, agentic_exec, agentic_runner, agentic_store, agentic_tools, settings

logger = logging.getLogger("ai365.agentic")

router = APIRouter(prefix="/api/agentic", tags=["agentic"])

MENU_KEY = "m_agentic"
MAX_MESSAGE = 20000
MAX_EVENTS_PAGE = 2000
REPLAY_PAGE = 500
FILE_VIEW_BYTES = 512 * 1024
FILE_VIEW_CHARS = 100_000
PING_SEC = 15
MODES = ("auto", "steer", "queue")
BUSY_COMMAND = "실행 중에는 명령을 쓸 수 없습니다"
BUSY_RUN = "실행 중에는 할 수 없습니다. 끝나거나 중단한 뒤 다시 시도하세요"
BUSY_PROCESSING = "명령을 처리하는 중입니다. 잠시 뒤 다시 보내 주세요"
NOT_REPO = "git 저장소가 아닙니다"
# 폴더 고르기(2026-10-19) / folder picking
REPO_ROOT = Path(__file__).resolve().parent.parent
PICK_TIMEOUT_SEC = 600
PICK_TITLE = "폴더 선택"
PICK_TITLE_MAX = 100
PICK_BUSY = "이미 폴더 선택 창이 열려 있습니다"
PICK_UNAVAILABLE = "폴더 선택 창을 띄울 수 없습니다"
BROWSE_MAX = 500
BROWSE_SKIP = frozenset({".git", "node_modules"})   # 이름으로 빼는 폴더 / folders left out by name
_HIDDEN_ATTRS = 0x2 | 0x4                             # FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM
_PICK_LOCK = threading.Lock()                         # 폴더 선택 창은 한 번에 하나 / one folder window at a time
# 내 컴퓨터 폴더(2026-10-20) / folders on my computer
BROWSER_NO_SERVER = "내 컴퓨터 폴더 세션에서는 쓸 수 없습니다"
BROWSER_NO_FILES = "내 컴퓨터 폴더는 브라우저가 직접 읽습니다"
BROWSER_NO_DOWNLOAD = "내 컴퓨터 폴더의 파일은 그 컴퓨터에 있습니다"
BROWSER_NO_EXTRA = "내 컴퓨터 폴더 세션은 추가 폴더를 쓸 수 없습니다"
EXTRACT_MAX_BYTES = 20 * 1024 * 1024                  # /extract 가 받는 파일 상한 / the file cap of /extract
EXTRACT_EXTS = ("pdf", "docx", "pptx", "xlsx")
# 원격 클라이언트 정책(2026-10-20) / the remote-client policy
REMOTE_CREATE_ONLY = "원격에서는 내 컴퓨터 폴더 세션만 만들 수 있습니다"
REMOTE_SESSION_ONLY = "원격에서는 내 컴퓨터 폴더 세션만 쓸 수 있습니다"
REMOTE_NO_PICK = "원격에서는 서버 폴더를 고를 수 없습니다"
REMOTE_NO_SETTINGS = "설정은 서버 PC(로컬)에서만 바꿀 수 있습니다"


class SessionIn(BaseModel):
    acting_user_id: str = ""
    folder: str = ""
    title: str = ""
    model: str = ""
    perm_mode: str = ""
    kind: str = "local"                     # local(서버 폴더) | browser(내 컴퓨터 폴더, folder = 이름) / folder = the name


class SessionPatch(BaseModel):
    acting_user_id: str = ""
    title: str | None = None
    model: str | None = None
    perm_mode: str | None = None
    extra_folders: list[str] | None = None
    connectors: list[str] | None = None     # 2차: 이 세션이 쓰는 MCP 도구 커넥터 id / MCP tool connector ids
    notify: bool | None = None              # 2차: 완료 알림 / completion mail


class MessageIn(BaseModel):
    acting_user_id: str = ""
    text: str = ""
    mode: str = "auto"                      # 2차: auto | steer | queue (실행 중일 때만 뜻이 있다 / only matters while running)


class SeenIn(BaseModel):
    acting_user_id: str = ""
    seq: int = 0


class CheckpointIn(BaseModel):
    acting_user_id: str = ""
    label: str = ""


class CommitIn(BaseModel):
    acting_user_id: str = ""
    message: str = ""


class ActIn(BaseModel):
    acting_user_id: str = ""


class DecisionIn(BaseModel):
    acting_user_id: str = ""
    decision: str = ""


class SettingsIn(BaseModel):
    acting_user_id: str = ""
    settings: dict = {}


class PickIn(BaseModel):
    acting_user_id: str = ""
    start: str = ""      # 처음 열 폴더(있는 폴더일 때만, 아니면 첫 허용 폴더) / the folder to open first (when it exists)
    title: str = ""      # 창 제목 / the window title


class ToolResultIn(BaseModel):
    """브라우저 실행기의 답(계약 E) / the browser executor's answer"""
    acting_user_id: str = ""
    request_id: str = ""
    ok: bool = False
    result: dict | None = None
    error: str = ""
    code: str = ""


# ────────────────────────────────────────────────────────
# 권한 / permissions
# ────────────────────────────────────────────────────────

def _eff(acting_user_id: str):
    from app.resources_api import _eff as resolve   # 지연 임포트(순환 회피, reports_api 와 같은 방식) / lazy import like reports_api
    return resolve(acting_user_id)


def _is_loopback(host: str) -> bool:
    """127.0.0.0/8 · ::1 · IPv4 대응 IPv6(::ffff:127.x) 만 루프백. 이름(testclient 등)은 아니다 / loopback IPs only, never names"""
    try:
        ip = ipaddress.ip_address(str(host or "").strip())
    except ValueError:
        return False
    if ip.is_loopback:
        return True
    mapped = getattr(ip, "ipv4_mapped", None)
    return bool(mapped is not None and mapped.is_loopback)


def _is_remote(request: Request) -> bool:
    """원격 클라이언트 정책(2026-10-20)을 받는 요청인가: 클라이언트가 루프백이 아니고 AGENTIC_ALLOW_REMOTE 가 꺼져 있다. 원격
    요청은 내 컴퓨터 폴더(browser) 세션만 쓴다(설정 GET 의 remote 도 이 값). AGENTIC_ALLOW_REMOTE=1 이면 늘 False(종전처럼 전부)
    Is this request under the remote-client policy (2026-10-20): a non-loopback client with AGENTIC_ALLOW_REMOTE off. Such
    requests use browser-folder sessions only (settings GET reports it as remote); always False with AGENTIC_ALLOW_REMOTE=1"""
    if settings.AGENTIC_ALLOW_REMOTE:
        return False
    return not _is_loopback(request.client.host if request.client else "")


def _guard(request: Request, acting_user_id: str) -> str:
    """신원 모양 · 메뉴 권한 m_agentic 검사 → 소유자 키. 원격 여부는 여기서 막지 않고(2026-10-20) 원격에서 막는 자리마다 _is_remote
    로 본다(_session_of · 세션 만들기 · 서버 폴더 고르기 · 설정 PUT)
    The id shape and the m_agentic permission → the owner key. Remote clients are no longer refused here (2026-10-20);
    the places that refuse them check _is_remote (_session_of, session creation, server-folder picking, settings PUT)"""
    owner = (acting_user_id or "").strip()
    if owner and not owner.isdigit():
        raise HTTPException(status_code=403, detail="acting_user_id 는 비우거나(슈퍼) 숫자여야 합니다")
    eff = _eff(owner)
    if eff is None or (eff.get("menus") or {}).get(MENU_KEY):
        return owner
    raise HTTPException(status_code=403, detail="Agentic 모드 권한이 없습니다")


def _require_super(owner: str) -> None:
    """_guard 를 지난 소유자 키가 슈퍼(빈 값)인가 / is the owner key (after _guard) the super admin"""
    if owner or _eff(owner) is not None:
        raise HTTPException(status_code=403, detail="슈퍼관리자 전용 기능입니다")


def _local_only(request: Request, detail: str) -> None:
    """원격 요청이면 403(서버 폴더 고르기 · 설정 바꾸기) / 403 for remote requests (server-folder picking, settings changes)"""
    if _is_remote(request):
        raise HTTPException(status_code=403, detail=detail)


def _owned(sid: str, owner: str) -> dict:
    s = agentic_store.get_session(sid, owner)
    if s is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다")
    return s


def _session_of(request: Request, sid: str, acting_user_id: str) -> dict:
    """세션 단위 엔드포인트의 공통 검사: _guard → 소유자(남의 세션 404) → 원격이면 내 컴퓨터 폴더 세션만(아니면 403)
    The shared check of session endpoints: _guard, the owner (404 for others), then browser sessions only for remote requests"""
    session = _owned(sid, _guard(request, acting_user_id))
    if _is_remote(request) and not agentic_browser.is_browser(session):
        raise HTTPException(status_code=403, detail=REMOTE_SESSION_ONLY)
    return session


def _check_folder(raw, roots) -> str:
    """있는 절대 경로이고 허용 폴더 안이어야 한다(아니면 422) → 정규화한 경로 / must exist, be absolute and allowed (422)"""
    try:
        real = agentic_store.norm_folder(raw)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if not agentic_exec.inside(real, roots):
        raise HTTPException(status_code=422, detail="허용 폴더 밖입니다. 관리 센터 › Agentic 설정의 허용 폴더 안에서 고르세요")
    return real


def _idle(sid: str) -> None:
    """실행 중이거나 명령을 처리 중이면 409 / 409 while running or processing a command"""
    if agentic_runner.busy(sid):
        raise HTTPException(status_code=409, detail=BUSY_RUN)


def _server_only(session: dict, detail: str = BROWSER_NO_SERVER) -> None:
    """서버 폴더가 필요한 기능: 내 컴퓨터 폴더 세션이면 409 / a feature that needs a server folder: 409 for browser sessions"""
    if agentic_browser.is_browser(session):
        raise HTTPException(status_code=409, detail=detail)


def _git():
    """agentic_git 지연 임포트(없으면 422) / lazily import agentic_git (422 when missing)"""
    try:
        from app import agentic_git
    except ImportError as e:
        raise HTTPException(status_code=422, detail="git 기능을 쓸 수 없습니다") from e
    return agentic_git


async def _repo(folder: str):
    """저장소 확인(스레드) → agentic_git. 저장소가 아니면 422 / check the repository in a thread (422 when it is not one)"""
    git = _git()
    if not await asyncio.to_thread(git.is_repo, folder):
        raise HTTPException(status_code=422, detail=NOT_REPO)
    return git


def _session_path(session: dict, raw: str, inside_folder: bool = False) -> str:
    """요청 경로 → realpath. 허용 폴더(inside_folder 면 세션 폴더) 밖 · 비밀 파일은 403, 잘못된 경로는 422.
    A request path → realpath; outside the allowed folders (the session folder with inside_folder) or a secrets file → 403."""
    try:
        real = agentic_exec.real_target(session["folder"], raw)
    except agentic_exec.ExecError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    roots = [session["folder"]] if inside_folder else agentic_tools.allowed_roots(session, agentic_store.get_settings())
    if not agentic_exec.inside(real, roots):
        raise HTTPException(status_code=403, detail="허용 폴더 밖입니다")
    if os.path.normcase(real) in agentic_exec.PROTECTED_FILES:
        raise HTTPException(status_code=403, detail="이 서버의 비밀 설정 파일은 열 수 없습니다")
    return real


# ────────────────────────────────────────────────────────
# 모델 · 설정 / models and settings
# ────────────────────────────────────────────────────────

@router.get("/models")
def list_models(request: Request, acting_user_id: str = "") -> dict:
    _guard(request, acting_user_id)
    return {"models": [dict(m) for m in agentic_store.MODELS]}


@router.get("/settings")
def get_settings(request: Request, acting_user_id: str = "") -> dict:
    _guard(request, acting_user_id)
    remote = _is_remote(request)
    # folder_picker: 폴더 고르기(pick-folder · browse)가 있다는 표시. 프런트는 이 값이 있을 때만 [찾아보기] 등을 보인다. 원격이면
    # false(서버 폴더 고르기는 원격에서 403). browser_folders(2026-10-20): 내 컴퓨터 폴더 세션(kind=browser)을 받는다는 표시.
    # remote(2026-10-20): 이 요청이 원격 정책을 받는가(서버 폴더 UI 를 숨긴다)
    # folder_picker advertises folder picking (pick-folder, browse) and is false for remote requests (403 there);
    # browser_folders advertises browser-folder sessions; remote tells whether the remote policy applies (hide server-folder UI)
    return {"settings": agentic_store.get_settings(), "host": socket.gethostname(), "folder_picker": not remote,
            "browser_folders": True, "remote": remote}


@router.put("/settings")
def put_settings(request: Request, body: SettingsIn) -> dict:
    _require_super(_guard(request, body.acting_user_id))
    _local_only(request, REMOTE_NO_SETTINGS)   # 설정은 서버 PC 에서만(2026-10-20) / settings change on the server PC only
    try:
        saved = agentic_store.put_settings(body.settings)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"settings": saved, "host": socket.gethostname(), "folder_picker": True, "browser_folders": True,
            "remote": False}


@router.get("/connectors")
def list_connectors(request: Request, acting_user_id: str = "") -> dict:
    """관리 센터 › API · MCP 연결의 MCP 도구 커넥터 중 켜진 것 ∩ 요청자의 권한 축 p_conn(적대 검토 M2, 슈퍼 '' 는 전부)
    Enabled MCP tool connectors the requester may use on the p_conn axis (adversarial review M2; super '' sees all)"""
    owner = _guard(request, acting_user_id)
    try:
        from app import agentic_mcp
    except ImportError:
        return {"connectors": []}
    allowed = agentic_tools.allowed_connector_ids(owner)
    return {"connectors": [c for c in (agentic_mcp.available() or []) if allowed is None or c.get("id") in allowed]}


# ────────────────────────────────────────────────────────
# 폴더 고르기(2026-10-19) / folder picking
# ────────────────────────────────────────────────────────

def _is_super(owner: str) -> bool:
    """_guard 를 지난 소유자 키가 슈퍼(빈 값)인가 / is the owner key (after _guard) the super admin"""
    return not owner and _eff(owner) is None


def _picker_python() -> str:
    """폴더 선택 창을 돌릴 파이썬: 저장소 .venv 의 pythonw.exe(콘솔 창이 깜빡이지 않게), 없으면 이 서버의 파이썬
    The Python for the folder window: the repository's .venv pythonw.exe (no console flash), else this server's own"""
    pyw = REPO_ROOT / ".venv" / "Scripts" / "pythonw.exe"
    return str(pyw) if pyw.is_file() else sys.executable


def _pick_start(raw: str, roots: list[str]) -> str:
    """처음 열 폴더: 요청의 start 가 있는 절대 경로 폴더면 그것, 아니면 첫 허용 폴더(있는 것), 없으면 ''
    The folder to open first: the requested start when it is an existing absolute folder, else the first existing allowed one"""
    s = (raw or "").strip()
    if s and "\x00" not in s and os.path.isabs(s) and os.path.isdir(s):
        return os.path.realpath(s)
    for r in roots or []:
        if r and os.path.isdir(r):
            return os.path.realpath(r)
    return ""


def _run_picker(start: str, title: str) -> str | None:
    """자식 프로세스(app.agentic_pick)로 폴더 선택 창 → 고른 경로('' = 취소). 띄우지 못했거나(종료 코드 ≠ 0 · 출력을 못 읽음 ·
    실행 실패) 시간 초과면 None. 자식 환경에서는 비밀 변수를 뺀다. 끝나면(성공 · 실패 · 시간 초과 모두) 잠금을 푼다.
    Run the folder window in a child process (app.agentic_pick) → the chosen path ('' = cancelled); None when it could not
    run (exit code ≠ 0, unreadable output, launch failure) or timed out. Secrets are kept out of the child's environment.
    The lock is released when the child is over, whatever the outcome."""
    try:
        cmd = [_picker_python(), "-m", "app.agentic_pick", start, title]
        try:
            r = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, timeout=PICK_TIMEOUT_SEC,
                               creationflags=agentic_exec._NO_WINDOW, env=agentic_exec._child_env())
        except subprocess.TimeoutExpired:
            logger.warning("Agentic 폴더 선택 창 시간 초과(%s초)", PICK_TIMEOUT_SEC)
            return None
        except OSError:
            logger.warning("Agentic 폴더 선택 창을 시작하지 못함", exc_info=True)
            return None
        if r.returncode != 0:
            err = (r.stderr or b"").decode("utf-8", "replace").strip()[-500:]
            logger.warning("Agentic 폴더 선택 창 실패 exit=%s %s", r.returncode, err)
            return None
        try:
            lines = [ln for ln in (r.stdout or b"").decode("utf-8", "replace").splitlines() if ln.strip()]
            path = json.loads(lines[-1])["path"]
        except (IndexError, ValueError, KeyError, TypeError):
            logger.warning("Agentic 폴더 선택 창의 출력을 읽지 못함")
            return None
        return path.strip() if isinstance(path, str) else None
    finally:
        _PICK_LOCK.release()


@router.post("/pick-folder")
async def pick_folder(request: Request, body: PickIn) -> dict:
    """서버 PC 에 폴더 선택 창을 띄우고 고를 때까지 기다린다(최대 10분) → {path, cancelled: false, allowed} 또는
    {cancelled: true}. 한 번에 하나(열려 있으면 409). 창을 띄울 수 없거나 시간 초과면 503, 원격 요청(AGENTIC_ALLOW_REMOTE)도
    창이 서버 화면에 뜨므로 503 이다(프런트가 앱 안 탐색기로 넘어간다). allowed = 설정의 허용 폴더 안인가. 원격 정책(2026-10-20,
    AGENTIC_ALLOW_REMOTE 꺼짐)의 원격 요청은 403 이다.
    Show a folder window on the server PC and wait for the choice (10 minutes at most) → {path, cancelled: false, allowed}
    or {cancelled: true}. One at a time (409 while one is open). 503 when the window cannot open or times out, and for
    remote requests (AGENTIC_ALLOW_REMOTE) too since the window would open on the server's screen (the front end then
    falls back to the in-app explorer). allowed = whether the path is inside the configured allowed folders. Remote
    requests under the remote policy (2026-10-20, AGENTIC_ALLOW_REMOTE off) get 403."""
    _guard(request, body.acting_user_id)
    _local_only(request, REMOTE_NO_PICK)   # 원격 정책(2026-10-20): 서버 폴더는 고를 수 없다 / remote policy: no server folders
    if not _is_loopback(request.client.host if request.client else ""):   # AGENTIC_ALLOW_REMOTE=1 의 원격 / remote with the flag
        raise HTTPException(status_code=503, detail=PICK_UNAVAILABLE)
    roots = agentic_store.get_settings()["allowed_folders"]
    start = _pick_start(body.start, roots)
    title = re.sub(r"\s+", " ", body.title or "").strip()[:PICK_TITLE_MAX] or PICK_TITLE
    if not _PICK_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=PICK_BUSY)
    # 잠금은 자식이 끝날 때 스레드가 푼다(요청이 끊겨도 창이 열려 있는 동안은 409) / the thread releases it when the child ends
    path = await asyncio.to_thread(_run_picker, start, title)
    if path is None:
        raise HTTPException(status_code=503, detail=PICK_UNAVAILABLE)
    if not path:
        return {"cancelled": True}
    real = os.path.realpath(path)
    return {"path": real, "cancelled": False, "allowed": agentic_exec.inside(real, roots)}


def _drives() -> list[str]:
    """드라이브 루트(Windows = C:\\ 등, 그 밖 = /) / drive roots (C:\\ and so on on Windows, / elsewhere)"""
    if os.name != "nt":
        return ["/"]
    lister = getattr(os, "listdrives", None)   # 3.12+
    if lister is not None:
        try:
            return list(lister())
        except OSError:
            pass
    try:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
    except Exception:  # noqa: BLE001
        return []
    return [f"{chr(65 + i)}:\\" for i in range(26) if mask >> i & 1]


def _named(path: str) -> dict:
    """{name, path}: 이름 = 마지막 조각(드라이브 루트는 경로 그대로) / the last segment as the name (a drive root keeps its path)"""
    return {"name": os.path.basename(path.rstrip("\\/")) or path, "path": path}


def _hidden(entry: os.DirEntry) -> bool:
    """숨김 · 시스템 폴더인가(Windows = 파일 속성, 그 밖 = 점으로 시작) / hidden or system (attributes on Windows, a dot elsewhere)"""
    if os.name == "nt":
        attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
        return bool(attrs & _HIDDEN_ATTRS)
    return entry.name.startswith(".")


def _subfolders(real: str) -> tuple[list[dict], bool]:
    """하위 폴더만(숨김 · 시스템 · .git · node_modules 빼고), 이름순, 500개 상한 → (목록, 잘렸나)
    Subfolders only (no hidden, system, .git or node_modules), by name, capped at 500 → (rows, truncated)"""
    rows = []
    with os.scandir(real) as it:
        for e in it:
            if e.name in BROWSE_SKIP:
                continue
            try:
                if not e.is_dir() or _hidden(e):
                    continue
            except OSError:
                continue
            rows.append({"name": e.name, "path": os.path.join(real, e.name)})
    rows.sort(key=lambda x: (x["name"].casefold(), x["name"]))
    return rows[:BROWSE_MAX], len(rows) > BROWSE_MAX


def _home_root(real: str, roots: list[str]) -> str:
    """real 을 품은 허용 폴더 중 가장 깊은 것(없으면 '') / the deepest allowed folder holding real ('' when none)"""
    best = ""
    for r in roots or []:
        if r and agentic_exec.inside(real, [r]):
            rr = os.path.realpath(r)
            if len(rr) > len(best):
                best = rr
    return best


def _crumbs(real: str, sup: bool, roots: list[str]) -> list[dict]:
    """경로 줄 조각 [{name, path}]: 슈퍼는 드라이브 루트부터, 아니면 품은 허용 폴더부터
    Breadcrumb pieces: from the drive root for the super admin, else from the allowed folder that holds the path"""
    base = "" if sup else _home_root(real, roots)
    if not base:
        anchor = Path(real).anchor
        base = anchor or real
    out = [_named(base)]
    try:
        rel = os.path.relpath(real, base) if os.path.normcase(real) != os.path.normcase(base) else "."
    except ValueError:   # 다른 드라이브(일어나지 않아야 한다) / another drive (should not happen)
        return [_named(real)]
    cur = base
    for part in ([] if rel == "." else Path(rel).parts):
        cur = os.path.join(cur, part)
        out.append({"name": part, "path": cur})
    return out


def _browse_parent(real: str, sup: bool, roots: list[str]) -> str:
    """[위로] 갈 곳: 상위 폴더(슈퍼가 아니면 허용 폴더 안일 때만), 드라이브 루트 · 허용 폴더 맨 위면 ''(처음 목록)
    Where [Up] goes: the parent (inside the allowed folders unless super); '' (the top list) at a drive root or an allowed root"""
    parent = os.path.dirname(real)
    if not parent or os.path.normcase(parent) == os.path.normcase(real):
        return ""
    if not sup and not agentic_exec.inside(parent, roots):
        return ""
    return parent


@router.get("/browse")
def browse(request: Request, acting_user_id: str = "", path: str = "") -> dict:
    """앱 안 탐색기: path 가 비면 허용 폴더 목록(슈퍼는 drives 도), 있으면 그 폴더의 하위 폴더(슈퍼가 아니면 허용 폴더 안만,
    밖은 403 · 없음 404 · 파일 422). 응답 = {path, parent, entries, truncated, crumbs, allowed}(처음 목록은 roots · drives).
    The in-app explorer: an empty path lists the allowed folders (plus drives for the super admin); a path lists its
    subfolders (non-super users stay inside the allowed folders: outside 403, missing 404, a file 422). The answer is
    {path, parent, entries, truncated, crumbs, allowed} (the top list adds roots and drives).
    원격 정책(2026-10-20): 원격 요청은 403 / the remote policy: 403 for remote requests."""
    owner = _guard(request, acting_user_id)
    _local_only(request, REMOTE_NO_PICK)
    sup = _is_super(owner)
    configured = agentic_store.get_settings()["allowed_folders"]
    roots = [os.path.realpath(r) for r in configured if r and os.path.isdir(r)]
    raw = (path or "").strip()
    if not raw:
        out = {"path": "", "parent": "", "roots": roots, "entries": [_named(r) for r in roots], "truncated": False,
               "crumbs": [], "allowed": False}
        if sup:
            out["drives"] = [_named(d) for d in _drives()]
        return out
    if "\x00" in raw or not os.path.isabs(raw):
        raise HTTPException(status_code=422, detail="절대 경로가 아닙니다")
    real = os.path.realpath(raw)
    if not sup and not agentic_exec.inside(real, configured):   # 있는지보다 먼저(밖의 존재를 알리지 않는다) / before existence
        raise HTTPException(status_code=403, detail="허용 폴더 밖입니다")
    if not os.path.exists(real):
        raise HTTPException(status_code=404, detail="폴더가 없습니다")
    if not os.path.isdir(real):
        raise HTTPException(status_code=422, detail="폴더가 아닙니다")
    try:
        entries, truncated = _subfolders(real)
    except OSError as e:
        raise HTTPException(status_code=422, detail=f"폴더를 읽지 못했습니다: {e.strerror or e}") from e
    return {"path": real, "parent": _browse_parent(real, sup, configured), "entries": entries, "truncated": truncated,
            "crumbs": _crumbs(real, sup, configured), "allowed": agentic_exec.inside(real, configured)}


# ────────────────────────────────────────────────────────
# 세션 / sessions
# ────────────────────────────────────────────────────────

@router.get("/sessions")
def list_sessions(request: Request, acting_user_id: str = "") -> dict:
    """소유자의 세션 목록(가벼운 모양). 원격 요청이면 내 컴퓨터 폴더 세션만 / the owner's sessions; browser ones only when remote"""
    owner = _guard(request, acting_user_id)
    remote = _is_remote(request)
    return {"sessions": [agentic_store.light(s) for s in agentic_store.list_sessions(owner)
                         if not remote or agentic_browser.is_browser(s)]}


@router.post("/sessions")
def create_session(request: Request, body: SessionIn) -> dict:
    """세션 만들기. kind=local(기본, 빈 값도) = 허용 폴더 안의 서버 폴더, kind=browser = 내 컴퓨터 폴더(folder = 폴더 이름, 허용
    폴더 검사 없음, 이름 검증 실패는 422). 그 밖의 kind 는 422. 원격 요청은 browser 만(local 은 403, 2026-10-20).
    Create a session: kind=local (the default, empty too) = a server folder inside the allowed folders; kind=browser = a
    folder on my computer (folder = its name, no allowed-folder check, a bad name is 422); any other kind is 422. Remote
    requests may create browser sessions only (local is 403, 2026-10-20)."""
    owner = _guard(request, body.acting_user_id)
    kind = (body.kind or "local").strip().lower()
    if kind not in agentic_store.KINDS:
        raise HTTPException(status_code=422, detail="kind 는 local 또는 browser")
    if kind != "browser" and _is_remote(request):   # 원격 정책(2026-10-20) / the remote policy
        raise HTTPException(status_code=403, detail=REMOTE_CREATE_ONLY)
    if kind == "browser":
        folder = body.folder
    else:
        folder = _check_folder(body.folder, agentic_store.get_settings()["allowed_folders"])
    try:
        session = agentic_store.create_session(owner, folder, body.title, body.model, body.perm_mode, kind=kind)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"session": session}


@router.get("/sessions/{sid}")
def get_session(request: Request, sid: str, acting_user_id: str = "") -> dict:
    session = _session_of(request, sid, acting_user_id)
    if agentic_browser.is_browser(session):   # 서버에 폴더가 없다 / the folder is not on the server
        return {"session": session, "git": {"repo": False, "browser": True}}
    return {"session": session, "git": agentic_exec.git_info(session["folder"])}


@router.patch("/sessions/{sid}")
def patch_session(request: Request, sid: str, body: SessionPatch) -> dict:
    session = _session_of(request, sid, body.acting_user_id)
    fields: dict = {}
    if body.title is not None:
        title = body.title.strip()[:agentic_store.MAX_TITLE]
        if not title:
            raise HTTPException(status_code=422, detail="제목이 비어 있습니다")
        fields["title"] = title
    if body.model is not None:
        if body.model not in agentic_store.MODEL_IDS:
            raise HTTPException(status_code=422, detail=f"모델은 {', '.join(agentic_store.MODEL_IDS)} 중 하나입니다")
        fields["model"] = body.model
    if body.perm_mode is not None and body.perm_mode not in agentic_store.PERM_MODES:
        raise HTTPException(status_code=422, detail="권한 모드는 auto · ask · plan 중 하나입니다")
    if body.extra_folders is not None and agentic_browser.is_browser(session):
        if body.extra_folders:   # 빈 목록은 그대로([]) 둔다 / an empty list keeps []
            raise HTTPException(status_code=422, detail=BROWSER_NO_EXTRA)
    elif body.extra_folders is not None:
        if len(body.extra_folders) > agentic_store.MAX_FOLDERS:
            raise HTTPException(status_code=422, detail=f"추가 폴더는 {agentic_store.MAX_FOLDERS}개까지입니다")
        roots = agentic_store.get_settings()["allowed_folders"]
        fields["extra_folders"] = agentic_store.dedupe_folders([_check_folder(p, roots) for p in body.extra_folders])
    if body.connectors is not None:
        fields["connectors"] = _check_connectors(body.connectors, session["owner"])
    if body.notify is not None:
        fields["notify"] = bool(body.notify)
    if fields:
        session = agentic_store.update_session(sid, **fields)
    if body.perm_mode is not None:   # plan 으로 들어가면 prev_perm 에 이전 모드 / entering plan keeps the previous mode
        session = agentic_store.set_perm_mode(sid, body.perm_mode)
    return {"session": session}


def _check_connectors(raw: list, owner: str) -> list[str]:
    """있는(켜진) MCP 도구 커넥터 id 이고 소유자가 권한 축 p_conn 으로 쓸 수 있는 것만(중복 제거 · 20개 상한), 아니면 422
    Existing (enabled) MCP tool connector ids the owner may use on the p_conn axis only (deduped, 20 max), else 422"""
    ids: list[str] = []
    for c in raw:
        cid = str(c or "").strip()
        if cid and cid not in ids:
            ids.append(cid)
    if len(ids) > agentic_store.MAX_CONNECTORS:
        raise HTTPException(status_code=422, detail=f"연결 도구는 {agentic_store.MAX_CONNECTORS}개까지입니다")
    if not ids:
        return []
    try:
        from app import agentic_mcp
    except ImportError as e:
        raise HTTPException(status_code=422, detail="연결 도구(MCP)를 쓸 수 없습니다") from e
    missing = [cid for cid in ids if agentic_mcp.get(cid) is None]
    if missing:
        raise HTTPException(status_code=422, detail=f"없는 연결 도구입니다: {', '.join(missing)}")
    allowed = agentic_tools.allowed_connector_ids(owner)
    denied = [cid for cid in ids if allowed is not None and cid not in allowed]
    if denied:
        raise HTTPException(status_code=422, detail=f"권한이 없는 연결 도구입니다: {', '.join(denied)}")
    return ids


@router.delete("/sessions/{sid}")
async def delete_session(request: Request, sid: str, acting_user_id: str = "") -> dict:
    """세션 삭제(실행 중이면 중단) + 체크포인트 ref 정리. 주의: 체크포인트 커밋 객체는 ref 를 지운 뒤에도 git gc 전까지 .git/objects 에
    남고, ref 가 있는 동안에는 clone --mirror · push --mirror 로 함께 나갈 수 있다(적대 검토 L5).
    Delete a session (stopping it first) and drop its checkpoint refs. Note: checkpoint commit objects stay in
    .git/objects until git gc after the refs go, and while the refs exist a clone --mirror or push --mirror carries them."""
    session = _session_of(request, sid, acting_user_id)
    browser = agentic_browser.is_browser(session)
    if browser:   # 기다리던 브라우저 요청을 먼저 실패로 / pending browser requests fail first
        agentic_browser.cancel(sid, "세션이 삭제되었습니다")
    await agentic_runner.stop(sid)   # 실행 중이면 먼저 중단 / stop first when running
    agentic_runner.forget(sid)
    await asyncio.to_thread(agentic_exec.kill_session_tasks, sid)
    agentic_store.delete_session(sid)
    if not browser:   # 내 컴퓨터 폴더에는 체크포인트 ref 가 없다 / browser folders have no checkpoint refs
        await asyncio.to_thread(_drop_refs, session["folder"], sid)   # 체크포인트 ref 정리(2차) / drop the checkpoint refs
    return {"ok": True}


def _drop_refs(folder: str, sid: str) -> None:
    """세션의 체크포인트 ref 를 지운다(git 이 없거나 실패하면 로그만) / drop the session's checkpoint refs, logging failures"""
    try:
        from app import agentic_git
        if os.path.exists(os.path.join(folder, ".git")):
            agentic_git.drop_refs(folder, sid)
    except Exception:  # noqa: BLE001
        logger.warning("Agentic 체크포인트 ref 정리 실패 session=%s", sid, exc_info=True)


@router.post("/sessions/{sid}/messages")
async def post_message(request: Request, sid: str, body: MessageIn) -> dict:
    """메시지 → 턴 시작 · 스티어링 · 대기 큐(mode), 또는 슬래시 명령(실행 중이면 409) / a message, or a slash command"""
    session = _session_of(request, sid, body.acting_user_id)
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="메시지가 비어 있습니다")
    if len(text) > MAX_MESSAGE:
        raise HTTPException(status_code=422, detail=f"메시지가 너무 깁니다(최대 {MAX_MESSAGE:,}자)")
    mode = (body.mode or "auto").strip().lower()
    if mode not in MODES:
        raise HTTPException(status_code=422, detail="mode 는 auto · steer · queue 중 하나입니다")
    try:
        cmd = agentic_runner.match_command(session, text)
        if cmd is not None:
            if agentic_runner.is_running(sid):
                raise HTTPException(status_code=409, detail=BUSY_COMMAND)
            out = await agentic_runner.run_command(sid, cmd[0], cmd[1], text)
            return {"command": out["command"], "queued": bool(out.get("queued")), "steered": False,
                    "session": out.get("session") or agentic_store.get_session(sid)}
        out = agentic_runner.start_turn(sid, text, mode)
    except agentic_runner.TooManySessions as e:
        raise HTTPException(status_code=409, detail=f"동시 실행 상한({e.args[0]}개)에 닿았습니다. 다른 세션이 끝난 뒤 다시 보내 주세요") from e
    except agentic_runner.Busy as e:
        raise HTTPException(status_code=409, detail=BUSY_PROCESSING if not agentic_runner.is_running(sid) else BUSY_COMMAND) from e
    except agentic_store.SessionGone as e:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다") from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"queued": bool(out.get("queued")), "steered": bool(out.get("steered")), "session": agentic_store.get_session(sid)}


@router.post("/sessions/{sid}/stop")
async def stop_session(request: Request, sid: str, body: ActIn) -> dict:
    _session_of(request, sid, body.acting_user_id)
    await agentic_runner.stop(sid)
    return {"session": agentic_store.get_session(sid)}


@router.post("/sessions/{sid}/approvals/{aid}")
async def decide_approval(request: Request, sid: str, aid: str, body: DecisionIn) -> dict:
    _session_of(request, sid, body.acting_user_id)
    try:
        agentic_runner.decide(sid, aid, body.decision)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except agentic_runner.NotPending as e:
        raise HTTPException(status_code=409, detail="대기 중인 승인이 아닙니다(없거나 이미 결정됨)") from e
    return {"session": agentic_store.get_session(sid)}


# ────────────────────────────────────────────────────────
# 이벤트 · 스트림 / events and the stream
# ────────────────────────────────────────────────────────

@router.get("/sessions/{sid}/events")
def list_events(request: Request, sid: str, acting_user_id: str = "", after: int = 0, limit: int = 500) -> dict:
    session = _session_of(request, sid, acting_user_id)
    events = agentic_store.list_events(sid, max(0, after), max(1, min(MAX_EVENTS_PAGE, limit)))
    return {"events": events, "last_seq": session["last_seq"]}


@router.get("/sessions/{sid}/stream")
async def stream(request: Request, sid: str, acting_user_id: str = "", after: int = 0,
                 last_event_id: str | None = Header(default=None)) -> EventSourceResponse:
    """SSE: after 이후를 DB 에서 재생하고 라이브로 잇는다(id = seq). 15초마다 ping, 클라이언트가 끊으면 구독 해제.
    브라우저 EventSource 가 스스로 다시 붙을 때 보내는 Last-Event-ID 가 after 보다 크면 그 뒤부터 잇는다.
    SSE: replay from the DB after `after`, then live (id = seq); a ping every 15 s; a client disconnect unsubscribes.
    When the browser's EventSource reconnects by itself, a Last-Event-ID beyond `after` wins.
    내 컴퓨터 폴더(2026-10-20): 라이브 구간의 transient 이벤트는 seq 검사 없이 event: tool_request(data = payload JSON, id 없음)로
    보낸다. DB 에 없으니 재생 구간에는 없다(다시 붙은 화면은 GET …/tool-requests 로 받는다).
    Browser folders (2026-10-20): live transient events go out as event: tool_request (data = the payload JSON, no id)
    without the seq check; they are not in the DB, so a replay never has them (a reconnecting screen uses GET …/tool-requests)."""
    _session_of(request, sid, acting_user_id)
    resume = int(last_event_id) if (last_event_id or "").strip().isdigit() else 0
    start = max(0, int(after or 0), resume)

    async def gen():
        q = agentic_runner.subscribe(sid)   # 먼저 등록하고 재생한다. 겹치는 이벤트는 seq 로 거른다 / register, then replay; dedupe by seq
        last = start
        try:
            while True:
                page = agentic_store.list_events(sid, last, REPLAY_PAGE)
                for ev in page:
                    last = ev["seq"]
                    yield {"id": str(ev["seq"]), "data": json.dumps(ev, ensure_ascii=False)}
                if len(page) < REPLAY_PAGE:
                    break
            while True:
                ev = await q.get()
                if ev is agentic_runner.CLOSE:
                    return
                if ev.get("transient"):   # 브라우저 실행기 요청(DB 밖, seq 없음) / a browser-executor request (no seq)
                    yield {"event": "tool_request", "data": json.dumps(ev.get("payload") or {}, ensure_ascii=False)}
                    continue
                if ev["seq"] <= last:
                    continue
                last = ev["seq"]
                yield {"id": str(ev["seq"]), "data": json.dumps(ev, ensure_ascii=False)}
        finally:
            agentic_runner.unsubscribe(sid, q)

    return EventSourceResponse(gen(), ping=PING_SEC)


# ────────────────────────────────────────────────────────
# 내 컴퓨터 폴더: 브라우저 실행기(2026-10-20) / folders on my computer: the browser executor
# ────────────────────────────────────────────────────────

@router.post("/sessions/{sid}/tool-results")
async def tool_results(request: Request, sid: str, body: ToolResultIn) -> dict:
    """브라우저 실행기의 답(소유자만) → 200 {accepted: true}. 모르는 요청 · 다른 세션의 요청은 404, 이미 끝난 요청(다른 탭이 먼저
    답함 · 시간 초과 · 취소)은 409. 루프 스레드에서 답을 넣어 워커 스레드를 깨운다.
    The browser executor's answer (owner only) → 200 {accepted: true}; an unknown request or another session's is 404,
    one already over (another tab answered first, a timeout, a cancel) is 409. Runs on the loop thread and wakes the worker."""
    _session_of(request, sid, body.acting_user_id)
    out = agentic_browser.resolve(sid, body.request_id, bool(body.ok), body.result, body.error or "", body.code or "")
    if out == "unknown":
        raise HTTPException(status_code=404, detail="대기 중인 요청이 아닙니다")
    if out == "done":
        raise HTTPException(status_code=409, detail="이미 끝난 요청입니다")
    return {"accepted": True}


@router.get("/sessions/{sid}/tool-requests")
def tool_requests(request: Request, sid: str, acting_user_id: str = "") -> dict:
    """아직 답하지 않은 브라우저 요청 [{request_id, op, args, ts}] (새로고침 · 다른 탭 보완) / pending browser requests"""
    _session_of(request, sid, acting_user_id)
    return {"requests": agentic_browser.pending(sid)}


def _extract_text(name: str, data: bytes) -> str:
    from app import upload_guard   # 지연 임포트(pymupdf · lxml) / lazy import (pymupdf, lxml)
    return upload_guard.document_text(name, data)


@router.post("/extract")
async def extract(request: Request, file: UploadFile = File(...), acting_user_id: str = Form("")) -> dict:
    """문서(pdf · docx · pptx · xlsx) 본문 뽑기(multipart: file + acting_user_id): 내 컴퓨터 폴더의 문서를 브라우저가 올려 read 의
    본문으로 쓴다. 저장하지 않는다. 20MB 초과 413, 그 밖의 확장자 422. → {text(상한 READ_MAX_CHARS × 4), chars(= len(text)),
    truncated}. 글자를 뽑지 못한 문서(그림 · 암호 · 깨진 파일)는 200 + text "".
    Extract a document's text (pdf, docx, pptx, xlsx; multipart file + acting_user_id): the browser uploads a document
    from the local folder to use as the read body. Nothing is stored. Over 20 MB is 413, other extensions 422. Returns
    {text (capped at READ_MAX_CHARS × 4), chars (= len(text)), truncated}; a document without extractable text (images,
    a password, a broken file) is 200 with text ""."""
    _guard(request, acting_user_id)
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > EXTRACT_MAX_BYTES + 1024 * 1024:   # 본문을 다 받기 전에 거절 / refuse before reading the body
        raise HTTPException(status_code=413, detail=f"파일이 너무 큽니다(최대 {EXTRACT_MAX_BYTES // (1024 * 1024)}MB)")
    name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in EXTRACT_EXTS:
        raise HTTPException(status_code=422, detail="지원하지 않는 문서 형식")
    data = await file.read(EXTRACT_MAX_BYTES + 1)
    if len(data) > EXTRACT_MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"파일이 너무 큽니다(최대 {EXTRACT_MAX_BYTES // (1024 * 1024)}MB)")
    text = await asyncio.to_thread(_extract_text, name, data)
    cap = agentic_exec.READ_MAX_CHARS * 4
    text = str(text or "")
    truncated = len(text) > cap
    text = text[:cap]
    return {"text": text, "chars": len(text), "truncated": truncated}


# ────────────────────────────────────────────────────────
# 파일 · 작업 / files and tasks
# ────────────────────────────────────────────────────────

@router.get("/sessions/{sid}/files")
def files(request: Request, sid: str, acting_user_id: str = "", path: str = "") -> dict:
    """폴더면 항목 목록, 파일이면 본문 미리보기(이진은 binary=true). 허용 폴더 밖은 403.
    A folder lists its entries; a file returns a text preview (binary=true for binaries). Outside the allowed folders: 403.
    내 컴퓨터 폴더 세션은 409(브라우저가 핸들에서 직접 읽는다) / 409 for browser sessions (the browser reads its handle)."""
    session = _session_of(request, sid, acting_user_id)
    _server_only(session, BROWSER_NO_FILES)
    ex = agentic_tools.make_executor(session, agentic_store.get_settings())
    try:
        real = ex.resolve(path or None)
    except agentic_exec.OutsideError as e:
        raise HTTPException(status_code=403, detail="허용 폴더 밖입니다") from e
    except agentic_exec.ExecError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if not os.path.exists(real):
        raise HTTPException(status_code=404, detail="파일이나 폴더가 없습니다")
    if os.path.isdir(real):
        try:
            listing = ex.list_dir(real)
        except agentic_exec.ExecError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return {"kind": "dir", "path": real, "rel": listing["rel"], "entries": listing["entries"],
                "truncated": listing["truncated"]}
    if real and os.path.normcase(real) in agentic_exec.PROTECTED_FILES:
        raise HTTPException(status_code=403, detail="이 서버의 비밀 설정 파일은 열 수 없습니다")
    try:
        view = agentic_exec.read_preview(real, FILE_VIEW_BYTES, FILE_VIEW_CHARS)
    except OSError as e:
        raise HTTPException(status_code=422, detail=f"파일을 읽지 못했습니다: {e}") from e
    return {"kind": "file", "path": real, "rel": ex.rel(real), **view}


@router.get("/sessions/{sid}/tasks")
def list_tasks(request: Request, sid: str, acting_user_id: str = "") -> dict:
    _session_of(request, sid, acting_user_id)
    return {"tasks": agentic_store.list_tasks(sid)}


@router.get("/sessions/{sid}/tasks/{tid}")
def get_task(request: Request, sid: str, tid: str, acting_user_id: str = "") -> dict:
    _session_of(request, sid, acting_user_id)
    task = agentic_store.get_task(tid, sid)
    if task is None:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    live = agentic_exec.live_task(tid)   # 도는 중이면 메모리의 최신 출력 / the freshest output while running
    if live is not None:
        task["output"] = live["output"]
    return {"task": task}


# ────────────────────────────────────────────────────────
# 2차: 명령 · 화면이 본 seq / phase 2: commands and the seen seq
# ────────────────────────────────────────────────────────

@router.get("/sessions/{sid}/commands")
def list_commands(request: Request, sid: str, acting_user_id: str = "") -> dict:
    """슬래시 팝업 목록: 내장 + 폴더 · 전역 명령 + 스킬(이름순, 내장 먼저). 내 컴퓨터 폴더 세션은 전역만(폴더 인자 None)
    The slash popup list: built-ins, folder and global commands, skills (by name, built-ins first); global only for a
    browser-folder session (folder None)"""
    session = _session_of(request, sid, acting_user_id)
    try:
        from app import agentic_commands
    except ImportError:
        return {"commands": []}
    rows = agentic_commands.list_all(agentic_browser.server_folder(session), agentic_store.get_settings(),
                                     len(session.get("connectors") or []))
    return {"commands": list(rows or [])}


@router.post("/sessions/{sid}/seen")
def mark_seen(request: Request, sid: str, body: SeenIn) -> dict:
    """화면이 본 seq(last_seq 상한, 뒤로 가지 않는다) → 사이드바 미확인 점 / the seen seq for the sidebar's unseen dot"""
    _session_of(request, sid, body.acting_user_id)
    return {"session": agentic_store.mark_seen(sid, body.seq)}


# ────────────────────────────────────────────────────────
# 2차: 체크포인트 / phase 2: checkpoints
# ────────────────────────────────────────────────────────

@router.get("/sessions/{sid}/checkpoints")
def list_checkpoints(request: Request, sid: str, acting_user_id: str = "") -> dict:
    _session_of(request, sid, acting_user_id)
    return {"checkpoints": agentic_store.list_checkpoints(sid)}


@router.post("/sessions/{sid}/checkpoints")
async def create_checkpoint(request: Request, sid: str, body: CheckpointIn) -> dict:
    """수동 체크포인트(실행 중 409 · 저장소가 아니면 422 · 내 컴퓨터 폴더 409). checkpoint create 이벤트(seq 없음) / a manual checkpoint"""
    _server_only(_session_of(request, sid, body.acting_user_id))
    _idle(sid)
    label = (body.label or "").strip()[:120] or agentic_runner.CHECKPOINT_MANUAL_LABEL
    try:
        cp = await agentic_runner.make_checkpoint(sid, label)
    except agentic_runner.NotRepo as e:
        raise HTTPException(status_code=422, detail=str(e) or NOT_REPO) from e
    except agentic_store.SessionGone as e:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다") from e
    except Exception as e:  # noqa: BLE001 (git 오류는 사람이 읽는 한 줄로 / git errors as one readable line)
        raise HTTPException(status_code=422, detail=f"체크포인트를 만들지 못했습니다: {str(e)[:300]}") from e
    return {"checkpoint": cp}


@router.post("/sessions/{sid}/checkpoints/{cid}/restore")
async def restore_checkpoint(request: Request, sid: str, cid: str, body: ActIn) -> dict:
    """체크포인트로 되돌리기(실행 중 409). 되돌리기 전 지금 상태를 자동 저장하고 checkpoint restore 이벤트를 쓴다.
    Restore a checkpoint (409 while running); the current state is saved first, then a checkpoint restore event.
    내 컴퓨터 폴더 세션은 409 / 409 for browser sessions."""
    _server_only(_session_of(request, sid, body.acting_user_id))
    _idle(sid)
    if agentic_store.get_checkpoint(cid, sid) is None:
        raise HTTPException(status_code=404, detail="체크포인트를 찾을 수 없습니다")
    try:
        cp = await agentic_runner.restore_checkpoint(sid, cid)
    except agentic_runner.BackgroundBusy as e:   # L7
        raise HTTPException(status_code=409, detail=str(e)) from e
    except agentic_runner.NotRepo as e:
        raise HTTPException(status_code=422, detail=str(e) or NOT_REPO) from e
    except agentic_runner.SafetySaveError as e:   # L2: 안전 저장이 없으면 되돌리지 않았다 / nothing restored
        raise HTTPException(status_code=422, detail=str(e)) from e
    except agentic_runner.RestoreError as e:   # L2: 일부만 되돌렸을 수 있다 → 안전 저장 id 를 싣는다 / carries the safety id
        return JSONResponse(status_code=422, content={"detail": str(e), "safety_checkpoint_id": e.safety_id})
    except agentic_store.SessionGone as e:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다") from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"되돌리지 못했습니다: {str(e)[:300]}") from e
    if cp is None:
        raise HTTPException(status_code=404, detail="체크포인트를 찾을 수 없습니다")
    return {"checkpoint": cp, "session": agentic_store.get_session(sid)}


# ────────────────────────────────────────────────────────
# 2차: 산출물 / phase 2: outputs
# ────────────────────────────────────────────────────────

@router.get("/sessions/{sid}/outputs")
def list_outputs(request: Request, sid: str, acting_user_id: str = "") -> dict:
    """세션이 만들거나 고친 파일(write_file · edit_file, 서브에이전트 포함). 내 컴퓨터 폴더 세션의 행은 path = '<이름>/<상대 경로>',
    exists = true(서버는 그 컴퓨터를 볼 수 없다)
    Files the session created or modified (subagents included); a browser session's rows have path '<name>/<relative>'
    and exists = true (the server cannot look at that computer)"""
    session = _session_of(request, sid, acting_user_id)
    browser = agentic_browser.is_browser(session)
    ex = agentic_tools.make_executor(session, agentic_store.get_settings())
    out = []
    for o in agentic_store.list_outputs(sid):
        out.append({"path": o["path"], "rel": ex.rel(o["path"]), "kind": o["kind"], "bytes": o["bytes"], "ts": o["ts"],
                    "exists": True if browser else os.path.isfile(o["path"])})
    return {"outputs": out}


@router.get("/sessions/{sid}/outputs/download")
def download_output(request: Request, sid: str, acting_user_id: str = "", path: str = ""):
    """산출물 내려받기(attachment). 그 세션의 agentic_outputs 에 있는 경로만(realpath 비교, 이진도 된다) 내려 주고 그 밖은 404
    (적대 검토 H2: 허용 폴더 안 아무 파일이나 원본 바이트로 나가지 않게). 비밀 파일 403, 파일이 없으면 404.
    Download an output (attachment): only paths recorded in this session's agentic_outputs (realpath compare, binaries
    included); anything else is 404 (adversarial review H2: no arbitrary file inside the allowed folders goes out as raw
    bytes). The secrets file is 403; a missing file is 404. 내 컴퓨터 폴더 세션은 409 / 409 for browser sessions."""
    session = _session_of(request, sid, acting_user_id)
    _server_only(session, BROWSER_NO_DOWNLOAD)
    if not (path or "").strip():
        raise HTTPException(status_code=422, detail="path 가 필요합니다")
    try:
        real = agentic_exec.real_target(session["folder"], path)
    except agentic_exec.ExecError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if os.path.normcase(real) in agentic_exec.PROTECTED_FILES:
        raise HTTPException(status_code=403, detail="이 서버의 비밀 설정 파일은 열 수 없습니다")
    recorded = {os.path.normcase(os.path.realpath(o["path"])) for o in agentic_store.list_outputs(sid)}
    if os.path.normcase(real) not in recorded:
        raise HTTPException(status_code=404, detail="이 세션의 산출물이 아닙니다")
    if not os.path.isfile(real):
        raise HTTPException(status_code=404, detail="파일이 없습니다")
    return FileResponse(real, filename=os.path.basename(real))


# ────────────────────────────────────────────────────────
# 2차: git 변경 · 커밋 / phase 2: git changes and commits
# ────────────────────────────────────────────────────────

def _latest_checkpoint(sid: str) -> dict | None:
    cps = agentic_store.list_checkpoints(sid)
    return cps[0] if cps else None


@router.get("/sessions/{sid}/changes")
async def changes(request: Request, sid: str, acting_user_id: str = "") -> dict:
    """작업 폴더의 git 변경(HEAD 대비). 저장소가 아니면 repo=false · files=[], 내 컴퓨터 폴더 세션은 409 / git changes against HEAD"""
    session = _session_of(request, sid, acting_user_id)
    _server_only(session)
    empty = {"repo": False, "branch": None, "files": [], "added": 0, "removed": 0, "count": 0, "truncated": False,
             "last_checkpoint": _latest_checkpoint(sid)}
    try:
        from app import agentic_git
    except ImportError:
        return empty
    if not await asyncio.to_thread(agentic_git.is_repo, session["folder"]):
        return empty
    try:
        st = await asyncio.to_thread(agentic_git.status, session["folder"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"변경 사항을 읽지 못했습니다: {str(e)[:300]}") from e
    return {"repo": True, "branch": st.get("branch"), "files": list(st.get("files") or []),
            "added": int(st.get("added") or 0), "removed": int(st.get("removed") or 0),
            "count": int(st.get("count") if st.get("count") is not None else len(st.get("files") or [])),
            "truncated": bool(st.get("truncated")), "last_checkpoint": _latest_checkpoint(sid)}


@router.get("/sessions/{sid}/changes/diff")
async def change_diff(request: Request, sid: str, acting_user_id: str = "", path: str = "") -> dict:
    """파일 하나의 diff(HEAD 대비, 추적 안 된 파일은 전체가 + 줄). 세션 폴더 밖 · 비밀 파일 403, 내 컴퓨터 폴더 409 / one file's diff"""
    session = _session_of(request, sid, acting_user_id)
    _server_only(session)
    if not (path or "").strip():
        raise HTTPException(status_code=422, detail="path 가 필요합니다")
    real = _session_path(session, path, inside_folder=True)
    # git 에는 저장소 기준 낱말 경로를 준다(링크를 푼 경로는 안 바깥 검사에만) / git gets the lexical repo path
    try:
        rel = os.path.relpath(os.path.normpath(os.path.join(session["folder"], path.strip())), session["folder"])
    except ValueError:
        rel = ".."
    if rel.startswith(".."):
        rel = os.path.relpath(real, session["folder"])
    git = await _repo(session["folder"])
    try:
        d = await asyncio.to_thread(git.diff, session["folder"], rel.replace("\\", "/"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"diff 를 읽지 못했습니다: {str(e)[:300]}") from e
    return {"path": d.get("path") or rel.replace("\\", "/"), "status": d.get("status") or "", "unified": d.get("unified") or "",
            "binary": bool(d.get("binary")), "truncated": bool(d.get("truncated"))}


@router.post("/sessions/{sid}/commit")
async def commit(request: Request, sid: str, body: CommitIn) -> dict:
    """git 커밋(add -A + commit). 실행 중 · 내 컴퓨터 폴더 409, 빈 메시지 · 변경 없음 · 저장소 아님 422 / commit everything"""
    session = _session_of(request, sid, body.acting_user_id)
    _server_only(session)
    _idle(sid)
    if agentic_runner.bg_busy(sid):   # L7: background 명령이 도는 동안은 커밋하지 않는다 / no commit while one runs
        raise HTTPException(status_code=409, detail=agentic_runner.BG_BUSY)
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=422, detail="커밋 메시지가 비어 있습니다")
    git = await _repo(session["folder"])
    try:
        res = await asyncio.to_thread(git.commit, session["folder"], message)
    except Exception as e:  # noqa: BLE001 (GitError = 변경 없음 등 / GitError, e.g. nothing to commit)
        raise HTTPException(status_code=422, detail=str(e)[:300] or "커밋하지 못했습니다") from e
    return {"ok": True, "commit": str(res.get("commit") or ""), "files": int(res.get("files") or 0), "message": message}


@router.get("/sessions/{sid}/commit/suggest")
async def commit_suggest(request: Request, sid: str, acting_user_id: str = "") -> dict:
    """커밋 메시지 제안(경량 모델, 실패하면 규칙 문장, 내 컴퓨터 폴더 409) / a commit message suggestion (lite model, rule fallback)"""
    session = _session_of(request, sid, acting_user_id)
    _server_only(session)
    git = await _repo(session["folder"])
    try:
        res = await asyncio.to_thread(git.suggest_message, session["folder"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"제안을 만들지 못했습니다: {str(e)[:300]}") from e
    return {"message": str(res.get("message") or ""), "files": int(res.get("files") or 0)}
