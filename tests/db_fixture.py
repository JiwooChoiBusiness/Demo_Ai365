"""DB를 쓰는 회귀 테스트는 임시 파일만 사용하고 연결을 명시적으로 닫는다."""
import tempfile
import gc
import sqlite3

import httpx
from pathlib import Path
from unittest.mock import patch


def isolate_db(stack):
    from app import db, connectors, knowledge_agents, mcp_servers, mock_kagent, skill_files, work_agents
    temp = stack.enter_context(tempfile.TemporaryDirectory())
    path = Path(temp) / "test.db"
    stack.enter_context(patch.object(db, "DB_PATH", path))
    stack.enter_context(patch.object(connectors, "DB_PATH", path))
    stack.enter_context(patch.object(mcp_servers, "DB_PATH", path))   # MCP 서버 저장소(2026-09-15)도 임시 DB / MCP store on the temp DB too
    stack.enter_context(patch.object(work_agents, "DB_PATH", path))
    stack.enter_context(patch.object(skill_files, "DB_PATH", path))   # Skill 파일 저장소(2026-09-23)도 임시 DB / skill-file store on the temp DB too   # 업무 자동화 에이전트 저장소(2026-09-22)도 임시 DB / work-agent store on the temp DB too
    # 로컬 지식 에이전트 저장소 · 가상 고객 배포(2026-09-29)도 임시 DB / local knowledge agents and the fictional deployment on the temp DB too
    stack.enter_context(patch.object(knowledge_agents, "DB_PATH", path))
    stack.enter_context(patch.object(mock_kagent, "DB_PATH", path))
    connections = []
    def connect():
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        connections.append(conn)
        return conn
    stack.enter_context(patch.object(db, "_conn", connect))
    stack.enter_context(patch.object(connectors, "_conn", connect))
    stack.enter_context(patch.object(mcp_servers, "_conn", connect))
    stack.enter_context(patch.object(work_agents, "_conn", connect))
    stack.enter_context(patch.object(skill_files, "_conn", connect))
    stack.enter_context(patch.object(knowledge_agents, "_conn", connect))
    stack.enter_context(patch.object(mock_kagent, "_conn", connect))
    def close():
        for conn in connections:
            conn.close()
        gc.collect()
    stack.callback(close)
    db.init_db()
    from app import upload_guard
    upload_guard.init_upload_guard()   # 업로드 검증(2026-10-01): 키워드 10개 · 켬 시드 / upload validation, ten keywords seeded with validation on
    connectors.init_connectors()
    mcp_servers.init_mcp_servers()
    work_agents.init_work_agents()
    skill_files.init_skill_files()
    knowledge_agents.init_knowledge_agents()   # 데모 에이전트 kl_demo_hq 시드 포함 / includes the kl_demo_hq demo seed
    mock_kagent.init_mock_kagent()             # 테넌트 hq · lab 시드 문서 / seed documents of tenants hq and lab
    # 채팅이 부르는 MCP(M코스메틱 이메일 에이전트 · 로컬 지식 에이전트, 2026-09-30)는 기본으로 실제 네트워크에 닿지 않는다 — 테스트가
    # 자기 전송을 넣지 않으면 연결 거부로 끝나, 사용자 서버(localhost:8000)와 실 DB 에 닿을 일이 없다.
    # Chat-side MCP (M Cosmetic Email Agent, local knowledge agents; 2026-09-30) never reaches the real network by default:
    # unless a test injects its own transport, calls end as refused connections, so nothing reaches the user's server or DB.
    from app import local_knowledge, mcmail_link

    def refuse(request):
        raise httpx.ConnectError("테스트에서는 실제 네트워크를 쓰지 않습니다 / no real network in tests", request=request)
    offline = httpx.MockTransport(refuse)
    stack.enter_context(patch.object(mcmail_link, "TRANSPORT", offline))
    stack.enter_context(patch.object(local_knowledge, "TRANSPORT", offline))
    # 채팅 실시간 위젯(2026-10-06)도 기본은 네트워크 없음 — Open-Meteo · 구글 장소는 연결 거부, 야후 시세는 실패
    # Chat live widgets (2026-10-06) are offline by default too: Open-Meteo and Google Places refuse, Yahoo quotes fail
    from app import live_fx, live_places, live_weather

    def no_quote(symbol):
        raise live_fx.FxError("테스트에서는 실제 네트워크를 쓰지 않습니다 / no real network in tests")
    stack.enter_context(patch.object(live_weather, "TRANSPORT", offline))
    stack.enter_context(patch.object(live_places, "TRANSPORT", offline))
    stack.enter_context(patch.object(live_fx, "_FETCH", no_quote))
    return path
