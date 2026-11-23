import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

# 'python app/main.py'처럼 스크립트로 직접 실행해도 app 패키지를 찾을 수 있게 한다
# Ensure the app package can be found even when run directly as a script like 'python app/main.py'
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

from app import access, access_api, actions_api, agentic_api, agentic_store, analytics, boards, boards_api, boards_migrate, chats_api, collections_api, collections_store, connectors, connectors_api, data_api, db, docgen, docgen_api, edu_agent, edu_api, flow_api_call, flows, flows_api, groupware, groupware_api, gw_work_api, home_widgets, home_widgets_api, kb, kb_log, knowledge_agents, knowledge_agents_api, live_api, live_usage, mcmail, mcmail_api, mcp_api, mcp_servers, mock_apis, mock_kagent, mock_mcosmetic, mock_mcosmetic_mcp, mock_mcp, model_settings, report_dash, reports, reports_api, resources_api, runs, schedules, schedules_api, security_api, security_store, skill_files, smart_actions, smart_actions_api, upload_guard, work_agents, work_agents_api  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
MOCKUP_PATH = BASE_DIR / "frontend" / "ai365-mockup.html"
STATIC_DIR = BASE_DIR / "static"
# 홈 화면 = 바탕화면 시안 파일을 응답 시점에 읽어 서빙(수정 즉시 반영). 바탕화면 파일이 있으면
# 그것이 라이브 편집 원본이고, 없는 환경(다른 PC·클론 직후)에서는 저장소 스냅숏
# (frontend/ai365-home.html)으로 폴백한다(사용자 지시로 스냅숏 커밋 — 2026-08-14).
# 시안을 고치면 저장소 복사본도 함께 갱신해 커밋할 것(스냅숏 동기화는 수동).
# Home = serves the Desktop design file, read at response time (edits show immediately). When the
# Desktop file exists it is the live-editing source; on machines without it (another PC, a fresh
# clone) we fall back to the repo snapshot (frontend/ai365-home.html), committed on user instruction
# (2026-08-14). When the design changes, update and commit the repo copy too (sync is manual).
HOME_PATH = Path.home() / "Desktop" / "ai-365 home example.html"
HOME_REPO_PATH = BASE_DIR / "frontend" / "ai365-home.html"
# 교육 에이전트 = 업무 자동화의 두 번째 기본 제공 에이전트(이메일 다음). 홈 시안과 같은 이중 경로 —
# 바탕화면 원본이 라이브 편집 원본, 없으면 저장소 스냅숏으로 폴백("레포가 되어도 동작되게" — 2026-08-19).
# Education agent = the second built-in work-automation agent (after email). Same dual-path scheme as
# the home design — the Desktop original is the live-editing source, with the repo snapshot as the
# fallback ("must keep working from the repo alone" — user instruction, 2026-08-19).
EDU_PATH = Path.home() / "Desktop" / "knowledge-agent-TEST.html"
EDU_REPO_PATH = BASE_DIR / "frontend" / "ai365-edu-agent.html"
# M코스메틱 이메일 에이전트 = 업무 자동화의 첫 번째 에이전트(2026-09-28 옛 이메일 업무 에이전트를 대체). 저장소의
# 단일 파일(번역 층 포함)을 /email 로 서빙한다 — 옛 화면·바탕화면 경로는 없앴다. 상태는 서버 스토어(app/mcmail.py,
# /api/email)가 가진다.
# M Cosmetic Email Agent = the first work-automation agent (replaced the old email work agent on 2026-09-28). /email
# serves the repo's standalone page (translation layer included); the old page and the Desktop path are gone. State
# lives in the server store (app/mcmail.py, /api/email).
MCMAIL_PAGE_PATH = BASE_DIR / "frontend" / "ai365-mcmail.html"
# /email 은 응답마다 최신 파일을 읽으므로 브라우저·iframe 캐시를 막는다 / /email reads the file per request; forbid caching
NO_CACHE_HEADERS = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache", "Expires": "0"}

ADAPTER_TAG = '<script src="/static/adapter.js"></script>'


def _kst_head(html: str) -> str:
    """한국 시간 도우미(static/kst.js)를 <head> 맨 앞에 응답 시점에만 넣는다(2026-10-06) — 원본 HTML 무수정이고,
    페이지의 다른 스크립트가 불러 쓰기 전에 정의된다. mtime 을 ?v= 로 붙여 캐시를 피한다.
    Injects the KST helpers (static/kst.js) first in <head>, only at response time (2026-10-06) — the HTML files stay
    untouched and the helpers exist before any page script calls them. The mtime rides as ?v= to dodge stale caches."""
    try:
        ver = int((STATIC_DIR / "kst.js").stat().st_mtime)
    except OSError:
        return html
    tag = f'<script src="/static/kst.js?v={ver}"></script>'
    m = re.search(r"<head(?:\s[^>]*)?>", html, re.IGNORECASE)   # <header> 와 헷갈리지 않게 / never matches <header>
    return html[:m.end()] + tag + html[m.end():] if m else tag + html

db.init_db()
from app import execution_store
execution_store.recover()
runs.reset_stale_runs()  # 백그라운드 답변 실행(2026-09-04): 이전 프로세스가 남긴 run_state='running' → stopped
# Background answer runs (2026-09-04): run_state='running' left by a previous process → stopped
access.init_access()  # 관리 센터: 조직도·권한 그룹·워크스페이스 시드/영속화
# Management Center: seed/persist the org chart, permission groups, and workspaces
analytics.init_analytics()  # 시드 테이블 + data/csv 자동 등록
# Seed tables + auto-register data/csv
reports.init_reports()  # 리포트 에이전트: 개인 보관소·게시판 영속화
boards.init_boards()  # 게시판(2026-09-14): 전체·그룹·내 보관함 게시글(리포트·대시보드), 문서 템플릿 / board posts (reports, dashboards) and templates
report_dash.init_report_dash()  # 리포트 에이전트 대시보드(2026-09-18): 세션(초안 상태 + 그 대시보드 전용 대화) / report-agent dashboard sessions (draft state + the dashboard-only conversation)
# Report agent: personal library & board persistence
smart_actions.init_smart_actions()  # 스마트 실행 설정: 키워드 구성 영속화
# Smart Actions settings: keyword-config persistence
groupware.init_groupware()  # 그룹웨어 에이전트: 위젯 설정(9키) 영속화
# Groupware agent: widget settings (9 keys) persistence
security_store.init_security()  # 보안 에이전트(목업): 위험 로그인 무시·갱신 시각 상태(sec_state)
connectors.init_connectors()  # 커넥터(2026-09-09): 특수 목적 외부 API 1개 단위 등록 — 채팅에서 AI가 부를 수 있음
# Connectors (2026-09-09): one special-purpose external API per unit — callable by the AI in chat
mcp_servers.init_mcp_servers()  # MCP 서버(2026-09-15): 서버 1개 = 주소·인증·도구 스냅샷, 도구는 커넥터 행(source='mcp')으로 동기화
# MCP servers (2026-09-15): one server = URL/auth/tool snapshot; tools are synced into connector rows (source='mcp')
skill_files.init_skill_files()  # Skill 파일(2026-09-23): MCP 연결·MCP 업무 에이전트에 붙이는 기술 정의 파일 / skill definition files attached to MCP connections and MCP work agents
work_agents.init_work_agents()  # 업무 자동화 에이전트(2026-09-22): 리소스 관리에서 등록한 API·MCP 에이전트 — 접근 권한 업무 자동화 축의 잎 / registered API·MCP work agents, leaves of the automation axis
knowledge_agents.init_knowledge_agents()  # 로컬 지식 에이전트(2026-09-29): 관리 센터 › 로컬 설정 등록분 + 데모 시드 kl_demo_hq 1회 — 지식 관리 · Local 축(p_klocal)의 잎 / local knowledge agents + one-time demo seed, leaves of p_klocal
mock_kagent.init_mock_kagent()  # 가상 고객 배포(/mock/kagent, 2026-09-29): hq · lab 테넌트 시드 문서 1회 / fictional customer deployment: one-time seed documents for hq and lab
access.rebuild_universe()  # 커넥터·에이전트 테이블이 생긴 뒤 권한 유니버스에 p_conn·p_auto·p_klocal 하위 노드를 채운다 / fill the p_conn, p_auto and p_klocal leaves once the tables exist
boards_migrate.migrate_legacy()  # 게시판 이전(2026-09-14, 1회): 개인 보관소·워크스페이스 게시판 글 → 게시판 저장소 / one-time move into board_posts
model_settings.init_model_settings()  # 관리 센터 > 토큰 설정: 답변 기본 모델·답변 버전·토큰 한도(model_settings, 2026-09-08)
# Admin Center > Token Settings: default answer model, answer versions, token limits (model_settings, 2026-09-08)
# Security agent (mock): dismissed risky sign-ins & refresh time state (sec_state)
flows.init_flows()  # 워크플로우 셋: 체인 정의 영속화(시드 4종)
# Workflow sets: chain-definition persistence (4 seeds)
edu_agent.init_edu_agent()  # 교육 에이전트 실 스토어(edu_*): 문서·감사·원장 시드/영속화 (실구축 1차)
# Education-agent real store (edu_*): docs/audit/ledger seed & persistence (real-build round 1)
mcmail.init_mcmail()  # M코스메틱 Email Agent 스토어(mc_*, 2026-09-28): 메일·Case·오류·로그 시드, 이미 있으면 오늘로 날짜 재기준
# M Cosmetic Email Agent store (mc_*): seeds mails/cases/errors/log, or re-anchors existing dates to today
collections_store.init_collections()  # 컬렉션(프로젝트) 실 스토어(coll_*): 컬렉션·파일·링크 시드/영속화
# Collections (projects) real store (coll_*): collections/files/links seed & persistence
schedules.init_schedules()  # 컬렉션 예약 실행(coll_schedules·coll_schedule_notifies): FK 때문에 컬렉션 뒤에 생성
# Collection scheduled runs (coll_schedules / coll_schedule_notifies): created after collections (FK)
docgen.init_docgen()  # 문서 생성(doc_*): 생성 문서·페이지 컷 영속화(PPT/PDF/Docx/Excel)
# Document generation (doc_*): generated docs & page cuts persistence (PPT/PDF/Docx/Excel)
kb_log.init_kb_log()  # AI Batch Log(2026-09-16): 인덱싱 처리 이력 테이블 + 색인된 문서 백필 / indexing history table + backfill of indexed docs
upload_guard.init_upload_guard()  # 업로드 검증(2026-10-01, 관리 센터 › 로컬 설정): 키워드 · 사용 토글, 처음 1회 키워드 10개 · 켬 / upload validation keywords and switch, ten seeded once with validation on
live_usage.init()  # 채팅 위젯(2026-10-06): 구글 지도 · 장소 월 사용량 카운터(무료량의 90%에서 멈춤) / monthly Google Maps usage counters, stopping at 90% of the free tier
agentic_store.init_agentic()  # Agentic 모드(2026-10-19): 세션 · 이벤트 · 작업 · 설정 테이블, 기동 때 running · waiting 세션 → stopped / tables, and leftover running or waiting sessions become stopped on boot
home_widgets.init_home_widgets()  # 홈 대시보드(2026-11-13, docs/widget-agent.md): 사람별 배치(home_dash_config) · 만든 위젯(home_widgets) 표 / per-person layout and made-widget tables
kb.index_all_background()  # data/knowledge/ 변경 자동 감지(증분 인덱싱)
# Automatically detect changes in data/knowledge/ (incremental indexing)

# lifespan: 컬렉션 예약 폴링 루프 기동/종료(SCHED_ENABLED=0 이면 미기동) / scheduler loop start/stop
app = FastAPI(title="Ai365 3.0 Demo Backend", lifespan=schedules.lifespan)


class _SelfOrigin:
    """이 서버 자신의 주소 기억(2026-09-30) · AI365_BASE_URL 이 없으면 첫 실제 요청의 소켓 주소(루프백 · 모든 주소 바인딩)로
    flow_api_call.SELF_BASE 를 채워 {{base_url}} 이 자기 자신을 가리키게 한다(8010 서버가 8000 의 /mock/… 을 부르지 않게).
    순수 ASGI 라 스트리밍 응답에 끼어들지 않는다. 테스트 클라이언트(testserver)는 건너뛴다.
    Remembers this server's own origin (2026-09-30): without AI365_BASE_URL, the first real request's socket address (loopback
    or all-interfaces binding) fills flow_api_call.SELF_BASE, so {{base_url}} points at this server itself (an 8010 server no
    longer calls 8000's /mock/…). Pure ASGI, so streaming responses are untouched; test clients (testserver) are skipped."""

    _LOCAL = ("127.0.0.1", "localhost", "0.0.0.0", "::1", "::")

    def __init__(self, inner) -> None:
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and flow_api_call.SELF_BASE is None and not os.getenv("AI365_BASE_URL"):
            server = scope.get("server") or ()
            if len(server) == 2 and str(server[0]) in self._LOCAL and isinstance(server[1], int):
                flow_api_call.SELF_BASE = f"http://127.0.0.1:{server[1]}"
        await self.inner(scope, receive, send)


app.add_middleware(_SelfOrigin)


class _GzipOpenUI:
    """OpenUI 섬 번들(/static/openui/ 아래, 2026-10-27)만 gzip 으로 보낸다 — 첫 로드 약 1.3MB → 약 0.4MB. 다른 경로(SSE ·
    스트리밍 응답 · 내려받기)는 그대로 지나가므로 압축기의 버퍼링이 스트림에 끼어들 수 없다.
    Gzips only the OpenUI island bundle under /static/openui/ (2026-10-27): the first load drops from about 1.3 MB to about
    0.4 MB. Every other path (SSE, streaming responses, downloads) passes through untouched, so compressor buffering can never
    reach a stream."""

    # 캐시 규칙(2026-10-28): 진입 파일(openui.js · openui.css · version.txt)은 매번 다시 확인(no-cache) — 다시 빌드하면 진입 파일이
    # 새 청크 이름을 가리키므로 옛 진입 파일을 캐시에서 쓰면 지워진 청크를 불러 섬이 깨진다. 해시 이름의 chunks/ 는 오래 캐시.
    # Cache rules (2026-10-28): entry files are always revalidated (a rebuild points them at new chunk names, so a cached old entry
    # imports deleted chunks); content-hashed chunks/ are cached for a long time.
    _ENTRY = ("/static/openui/openui.js", "/static/openui/openui.css", "/static/openui/version.txt")

    def __init__(self, inner) -> None:
        self.inner = inner
        self.gzip = GZipMiddleware(inner, minimum_size=1024)

    async def __call__(self, scope, receive, send):
        path = str(scope.get("path") or "")
        if scope.get("type") == "http" and path.startswith("/static/openui/"):
            cache = ("no-cache" if path in self._ENTRY
                     else "public, max-age=31536000, immutable" if path.startswith("/static/openui/chunks/") else "")

            async def send_with_cache(message):
                if cache and message.get("type") == "http.response.start" and message.get("status") == 200:
                    headers = [h for h in message.get("headers", []) if h[0].lower() != b"cache-control"]
                    headers.append((b"cache-control", cache.encode("latin-1")))
                    message = {**message, "headers": headers}
                await send(message)

            await self.gzip(scope, receive, send_with_cache)
            return
        await self.inner(scope, receive, send)


app.add_middleware(_GzipOpenUI)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(chats_api.router)
app.include_router(actions_api.router)
app.include_router(access_api.router)
app.include_router(data_api.router)
app.include_router(resources_api.router)  # 리소스 관리 편집(서버측 권한 강제)
# Resource-management edits (server-side permission enforcement)
app.include_router(reports_api.router)  # 리포트 에이전트(개인 보관소·게시판·차트 생성)
app.include_router(boards_api.router)  # 게시판(2026-09-14): 사이드바 게시판·공유·템플릿(게시판 관리) / boards, sharing, templates (board management)
# Report agent (personal library, boards, chart generation)
app.include_router(smart_actions_api.router)  # 스마트 실행 설정(키워드 구성)
# Smart Actions settings (keyword config)
app.include_router(groupware_api.router)  # 그룹웨어 에이전트(위젯 설정·정보 조회)
# Groupware agent (widget settings & info queries)
app.include_router(security_api.router)  # 보안 에이전트(목업) — 대시보드 취합·위험 로그인 무시·재수집·LLM 요약
app.include_router(connectors_api.router)  # 커넥터 — 관리 센터 "커넥터 설정" 목록·등록·수정·삭제·테스트(2026-09-09)
# Connectors — Admin Center "Connector settings" list/create/update/delete/test (2026-09-09)
app.include_router(mock_apis.router)  # 데모 가상 외부 API(ERP·EMS, /mock/…) — 워크플로우 "API 요청" 작업의 호출 대상(2026-09-09)
# Demo fictional external APIs (ERP/EMS under /mock/…) — the targets of workflow "API request" tasks (2026-09-09)
app.include_router(mock_mcosmetic.router)  # M코스메틱 가상 ERP·메일 API(/mock/mcosmetic/…, 2026-09-28) — Email Agent 스토어와 같은 함수
# M Cosmetic fictional ERP and mail API (/mock/mcosmetic/...) — the same functions the Email Agent store calls
app.include_router(mock_mcosmetic_mcp.router)  # M코스메틱 이메일 에이전트 MCP 서버(/mock/mcosmetic/mcp, 2026-09-29) · 업무 자동화 탭의 MCP 연결 대상
# M Cosmetic Email Agent MCP server (/mock/mcosmetic/mcp, 2026-09-29), the MCP connection shown in the automation tab
app.include_router(mcp_api.router)  # MCP 서버 — 관리 센터 "API · MCP 연결" 목록·등록·수정·삭제·도구 가져오기(2026-09-15)
app.include_router(work_agents_api.router)  # 업무 자동화 에이전트 — 리소스 관리 › 업무 자동화 탭 등록(API·MCP)·수정·삭제·도구 가져오기·테스트 호출(2026-09-22)
app.include_router(knowledge_agents_api.router)  # 로컬 지식 에이전트(2026-09-29) — 로컬 설정 등록·연결 테스트·Skills + 리소스 센터 Local 탭 문서 프록시 / local settings + Local-tab document proxy
# MCP servers — Admin Center "API · MCP connections" list/create/update/delete/discover (2026-09-15)
app.include_router(mock_mcp.router)  # 데모 MCP 서버(/mock/mcp) — 가상 ERP·EMS 도구 6종을 MCP 로 노출(2026-09-15)
# Demo MCP server (/mock/mcp) — exposes six fictional ERP/EMS tools over MCP (2026-09-15)
app.include_router(mock_kagent.router)  # 가상 고객 배포(/mock/kagent/{hq|lab}, 2026-09-29) — 지식 에이전트 MCP · API · OAuth / fictional deployment: knowledge-agent MCP, API and OAuth
app.include_router(model_settings.router)  # 관리 센터 > 토큰 설정 — 답변 기본 모델·답변 버전·토큰 한도 영속(2026-09-08)
# Admin Center > Token Settings — default answer model, answer versions, token limits (2026-09-08)
app.include_router(upload_guard.router)  # 업로드 검증(2026-10-01) — 슈퍼어드민 전용 키워드 · 토글 설정 + 문서 관리 업로드 사전 검사(/check) / upload validation
app.include_router(live_api.router)  # 채팅 위젯(2026-10-06) — 지도 로드 허가 · 장소 다시 불러오기 · 가게 정보 · 사진 · 사용량 / chat widgets: map-load permit, places, details, photos, usage
# Security agent (mock) — dashboard aggregate, risky sign-in dismiss, refresh, LLM summary
app.include_router(flows_api.router)  # 워크플로우 셋(정의 CRUD + 체인 실행 SSE)
# Workflow sets (definition CRUD + chain-run SSE)
app.include_router(edu_api.router)  # 교육 에이전트 패널 시드(열람 전용 상수)
# Education-agent panel seed (read-only constants)
app.include_router(mcmail_api.router)  # M코스메틱 이메일 에이전트(/api/email, 2026-09-28) — 옛 이메일 업무 에이전트 라우터·스토어를 대체(옛 모듈은 삭제)
# M Cosmetic Email Agent (/api/email) — replaces the old email work agent router and store (the old modules are deleted)
app.include_router(gw_work_api.router)  # 그룹웨어 에이전트 모드 — 업무 관리 패널·행 액션 데모 응답
# Groupware agent mode — work-management panel & row-action demo answers
app.include_router(collections_api.router)  # 컬렉션(프로젝트) — CRUD·파일·쉐어포인트 링크(채팅 연동은 chats.coll)
# Collections (projects) — CRUD/files/SharePoint links (chat linkage rides chats.coll)
app.include_router(docgen_api.router)  # 문서 생성 — 실행(SSE)·조회·실 파일 다운로드
# Document generation — run (SSE), read, real-file download
app.include_router(schedules_api.router_global)  # 예약 작업(사이드바 예약 메뉴, 6차) — 전체 목록·컬렉션 없는 예약·히스토리 / schedules page (round 6)
app.include_router(schedules_api.router)  # 컬렉션 예약 — CRUD·지금 실행(실행은 schedules.lifespan 루프)
# Collection schedules — CRUD & run-now (execution rides the schedules.lifespan loop)
app.include_router(agentic_api.router)  # Agentic 모드(2026-10-19): 세션 · 메시지 · 승인 · 이벤트 SSE · 파일 · 작업 · 설정 / sessions, messages, approvals, event SSE, files, tasks, settings
app.include_router(home_widgets_api.router)  # 홈 대시보드(2026-11-13): 배치 저장 · 만든 위젯 만들기 · 고치기 · 지우기 · 데이터(/api/home) / home dashboard layout and made widgets


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    # 목업 파일은 무수정 원칙 — 어댑터 스크립트는 응답 시점에만 삽입한다.
    # Mockup file follows a no-modification principle — the adapter script is injected only at response time.
    html = MOCKUP_PATH.read_text(encoding="utf-8")
    # 어댑터 캐시 무효화(2026-08-25): 파일 mtime을 버전 쿼리로 동봉 — 브라우저가 강력 새로고침 없이도
    # 항상 최신 adapter.js를 로드한다(스테일 메모리 캐시 함정 해소).
    # Adapter cache busting: the file mtime rides as a version query so browsers always load the
    # current adapter.js without a hard refresh (fixes the stale in-memory cache trap).
    try:
        ver = int((STATIC_DIR / "adapter.js").stat().st_mtime)
    except OSError:
        ver = 0
    # OpenUI 섬 번들 버전(2026-10-28): static/openui/version.txt 를 응답 시점에 실어 adapter 가 늘 지금 빌드를 부른다 — 번들을
    # 다시 빌드하고 adapter 상수를 안 올리면 브라우저가 옛 openui.js(지워진 청크를 부름)를 캐시에서 써서 답이 평문으로 깨졌다.
    # OpenUI island bundle version (2026-10-28): version.txt rides on the page so the adapter always imports the current build; a
    # rebuild without bumping the adapter constant let browsers reuse a cached old openui.js that imports deleted chunks.
    try:
        oui_ver = re.sub(r"[^0-9A-Za-z]", "", (STATIC_DIR / "openui" / "version.txt").read_text(encoding="utf-8"))[:32]
    except OSError:
        oui_ver = ""
    tag = (f'<script>window.AI365_OUI_LIVE_VER="{oui_ver}";</script>' if oui_ver else "") \
        + f'<script src="/static/adapter.js?v={ver}"></script>'
    template_ver = int((STATIC_DIR / "template_chat.js").stat().st_mtime)
    tag += f'<script src="/static/template_chat.js?v={template_ver}"></script>'
    # 게시판 관리(2026-09-18): 게시판 메뉴 안 관리 화면의 템플릿 목록·등록 패널 — 관리 센터 "게시판 설정" 카드에서 옮겨 왔다
    # Board management (2026-09-18): the template list and editor panel inside the board menu, moved out of the Admin Center card
    board_admin_ver = int((STATIC_DIR / "board_admin.js").stat().st_mtime)
    tag += f'<script src="/static/board_admin.js?v={board_admin_ver}"></script>'
    # 리포트 에이전트 대시보드(2026-09-18): 채팅 옆 패널(Source 탭·차트 카드·필터·전용 대화) + 게시판 상세의 읽기 전용 뷰어. Chart.js 는 처음 열 때 불러온다
    # Report-agent dashboards (2026-09-18): the chat-side panel (Source tabs, chart cards, filters, its own conversation) and the
    # read-only viewer of the board detail. Chart.js is loaded on first open
    report_dash_ver = int((STATIC_DIR / "report_dash.js").stat().st_mtime)
    tag += f'<script src="/static/report_dash.js?v={report_dash_ver}"></script>'
    # 채팅 실시간 위젯(2026-10-06): 날씨 · 환율 · 지도 카드와 지도 크게 보기 — adapter.js 가 답변 본문 뒤에 ai365WgInsert 로 넣는다
    # Chat live widgets (2026-10-06): weather, FX and map cards plus the expanded map — adapter.js inserts them via ai365WgInsert
    live_ver = int((STATIC_DIR / "live_widgets.js").stat().st_mtime)
    tag += f'<script src="/static/live_widgets.js?v={live_ver}"></script>'
    # Agentic 모드(2026-10-19): 홈 알약 Chat | Agentic 의 Agentic 셸(세션 사이드바 · 트랜스크립트 · 환경 패널), 파일이 있을 때만
    # Agentic mode (2026-10-19): the Agentic shell behind the home pill (session sidebar, transcript, environment panel), only when the file exists
    agentic_js = STATIC_DIR / "agentic.js"
    if agentic_js.exists():
        tag += f'<script src="/static/agentic.js?v={int(agentic_js.stat().st_mtime)}"></script>'
    # 리소스 선택 대화 상자(2026-10-28, Dev 원본 정렬 명세 1.1): 입력 카드 "리소스 센터" 칩 → Dev "리소스 선택" 대화 상자 · 칩 모양 · 홈 코치 툴팁.
    # adapter.js 뒤에 둔다(AI365_SMF_HOOKS 와 ai365SelectionSnapshot 을 감싼다), 파일이 있을 때만
    # Resource picker (2026-10-28, Dev-original alignment spec 1.1): the composer "Resource Center" chip opens the Dev "Select
    # Resources" dialog, plus the chip look and the home coach tooltip. After adapter.js (it wraps AI365_SMF_HOOKS and
    # ai365SelectionSnapshot), only when the file exists
    resource_js = STATIC_DIR / "resource_select.js"
    if resource_js.exists():
        tag += f'<script src="/static/resource_select.js?v={int(resource_js.stat().st_mtime)}"></script>'
    return _kst_head(html.replace("</body>", f"{tag}\n</body>", 1))


@app.get("/home", response_class=HTMLResponse)
def home() -> str:
    src = HOME_PATH if HOME_PATH.exists() else HOME_REPO_PATH
    if not src.exists():
        return ("<h3>홈 시안 파일을 찾을 수 없습니다</h3>"
                "<p>바탕화면의 'ai-365 home example.html' 또는 frontend/ai365-home.html이 필요합니다.</p>")
    # EN 번역 + Teams 액션 제거 스크립트를 응답 시점에만 주입(원본 무수정 — edu/email과 동일 관례).
    # 캐시 무효화(2026-09-03): 파일 수정 시각을 ?v= 로 붙인다 — 사전을 고쳐도 iframe 이 옛 스크립트를 캐시해 새 문자열이
    # 번역되지 않던 문제(adapter.js 의 ?v= 관례와 동일).
    # Inject the EN-translation + Teams-removal script only at response time (originals untouched).
    # Cache busting (2026-09-03): append the file mtime as ?v= — the iframe kept a cached copy after dictionary
    # edits, so new strings stayed untranslated (same convention as adapter.js's ?v=).
    live = STATIC_DIR / "home-live.js"
    ver = int(live.stat().st_mtime) if live.exists() else 0
    # 홈 대시보드 배치 · 만든 위젯 · 위젯 에이전트(2026-11-13 · 2026-11-16, docs/widget-agent.md 9절): static/home_dash.js 가
    # 있을 때만 home-live.js 앞에 넣는다(mtime 을 ?v= 로) — 그 앞에 차트를 그릴 report_dash.js(리포트 에이전트의 그리기),
    # 뒤에 위젯 에이전트 화면 widget_agent.js. home_dash.js 가 없으면 응답은 종전과 같다.
    # Home layout, made widgets and the widget agent (2026-11-13, 2026-11-16, docs/widget-agent.md section 9): static/home_dash.js
    # goes in before home-live.js only when the file exists (mtime as ?v=), preceded by report_dash.js (the report agent's
    # chart drawing) and followed by the widget agent screen widget_agent.js; without home_dash.js the response is unchanged.
    dash_tag = ""
    if (STATIC_DIR / "home_dash.js").exists():
        for name in ("report_dash.js", "home_dash.js", "widget_agent.js"):
            try:
                dash_tag += f'<script src="/static/{name}?v={int((STATIC_DIR / name).stat().st_mtime)}"></script>'
            except OSError:
                continue
    return _kst_head(src.read_text(encoding="utf-8").replace(
        "</body>", f'{dash_tag}<script src="/static/home-live.js?v={ver}"></script></body>', 1))


@app.get("/edu", response_class=HTMLResponse)
def edu() -> str:
    src = EDU_PATH if EDU_PATH.exists() else EDU_REPO_PATH
    if not src.exists():
        return ("<h3>교육 에이전트 시안 파일을 찾을 수 없습니다</h3>"
                "<p>바탕화면의 'knowledge-agent-TEST.html' 또는 frontend/ai365-edu-agent.html이 필요합니다.</p>")
    # 실구축 1차(2026-08-24): 서버 동기화 스크립트를 응답 시점에만 주입 — 바탕화면 원본·스냅숏 모두
    # 무수정(GET / 의 adapter.js 주입 관례). SPA in-page DB에 실 스토어 상태를 입히고 판정을 미러한다.
    # Real-build round 1: the server-sync script is injected only at response time (same convention
    # as GET /'s adapter.js) — neither the Desktop original nor the snapshot is modified.
    return _kst_head(src.read_text(encoding="utf-8").replace(
        "</body>", '<script src="/static/edu-sync.js"></script></body>', 1))


@app.get("/email", response_class=HTMLResponse)
def email() -> HTMLResponse:
    src = MCMAIL_PAGE_PATH
    if not src.exists():
        return HTMLResponse("<h3>이메일 에이전트 화면 파일을 찾을 수 없습니다</h3>"
                            "<p>frontend/ai365-mcmail.html이 필요합니다.</p>",
                            headers=NO_CACHE_HEADERS)
    # 번역 층이 파일 안에 있어 번역 스크립트는 주입하지 않는다(종전 email-live.js 주입 제거, 2026-09-28). 한국 시간 도우미만 넣는다.
    # The translation layer lives in the file, so no translation script is injected (email-live.js is gone); only the KST helpers are.
    return HTMLResponse(_kst_head(src.read_text(encoding="utf-8")), headers=NO_CACHE_HEADERS)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


if __name__ == "__main__":
    # VS Code ▶ 실행용. 코드 자동 재시작(--reload)이 필요하면 터미널에서
    # `uvicorn app.main:app --reload --port 8000`을 사용한다.
    # For running via VS Code ▶. If automatic code reload (--reload) is needed, use
    # `uvicorn app.main:app --reload --port 8000` from the terminal.
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
