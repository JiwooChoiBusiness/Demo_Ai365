"""에이전트 레지스트리 + 결과 인터페이스.

AgentResult 인터페이스는 고정이다. STEP 5~7에서 각 에이전트가 본 구현으로
교체되더라도 이 형태를 그대로 반환해야 한다.
"""
# Agent registry + result interface.
#
# The AgentResult interface is fixed. Even if each agent is replaced with its
# real implementation in STEP 5~7, it must still return this exact shape.

from typing import Any, Awaitable, Callable, Literal, TypedDict

AgentStatus = Literal["answer", "inference", "dashboard", "analysis", "not_found", "failed", "blocked", "cancelled", "needs_input", "needs_confirmation"]


class AgentResult(TypedDict, total=False):
    status: AgentStatus
    state: str
    text: str
    extras: dict[str, Any]
    fail_reason: str  # status='not_found'일 때 실패 원인
    # failure reason when status='not_found'
    alternative: str  # status='not_found'일 때 대안 제시
    # suggested alternative when status='not_found'


Message = dict[str, str]
# run(query, context, allow_web=True). allow_web=False면 내부 자료만 사용하고 웹 폴백을 하지 않는다
# (knowledge만 실제로 사용; data/work는 시그니처 통일을 위해 받기만 한다).
# run(query, context, allow_web=True). If allow_web=False, use only internal sources and do not fall back to web search
# (only knowledge actually uses it; data/work merely accept it to unify the signature).
AgentRun = Callable[..., Awaitable[AgentResult]]


AGENT_REGISTRY: dict[str, dict[str, Any]] = {
    "knowledge": {
        "label": "지식관리",
        "description": "사내 문서(규정·정책·매뉴얼·제품자료 등 PDF 지식)에서 근거를 찾아 답변",
        "run": None,  # 아래에서 본 구현으로 바인딩 (STEP 5)
        # bound to the real implementation below (STEP 5)
    },
    "data": {
        "label": "데이터분석",
        "description": "사내 데이터(SQL/CSV 테이블 조회·집계·분석, BI 대시보드 표시) 질의 처리",
        "run": None,  # 아래에서 본 구현으로 바인딩 (STEP 6)
        # bound to the real implementation below (STEP 6)
    },
    "groupware": {
        "label": "그룹웨어",   # flows._flow_kx_tasks의 kx 카드 라벨과 일치 / matches the kx card label in flows
        "description": "그룹웨어(M365 가상 API) 조회·개인 실행 — [조회] 메일함(Outlook)·일정·회의(캘린더)·"
                       "Teams 대화·멘션·할 일(To Do)·사내 문서함(SharePoint), 그리고 날씨·조직도·구성원 "
                       "연락처·컬렉션·사내 새 소식·오늘의 뉴스·사용 현황·BI 목록 등 사내 위젯. [실행] 새 일정·"
                       "Teams 회의 만들기, 할 일 완료 처리·추가, 메일 작성·발송, Teams 메시지 보내기 등 "
                       "내 그룹웨어 개인 실행(M코스메틱 고객 메일 업무·ERP 처리·교육 관리 등 업무 운영/자동화는 업무자동화 담당). "
                       "[보안] 보안 에이전트(그룹웨어 하위) — Microsoft 365 테넌트 보안 현황 조회: 종합 상태·위험한 사용자/"
                       "로그인·점검 항목·사용자/그룹 수·라이선스 할당/잔여·서비스/Teams 활성 사용·저장소/사서함·전역 관리자·"
                       "신규/삭제 계정·보안 요약",
        "run": None,  # 아래에서 본 구현으로 바인딩 (2026-08-27 자동 라우팅 편입)
        # bound to the real implementation below (added 2026-08-27 for auto routing)
    },
    "work": {
        "label": "업무자동화",
        # 2026-09-28: 이메일 워커(worker=email)는 M코스메틱 이메일 에이전트(app/mcmail)로 대체 / the email worker is now the M Cosmetic Email Agent
        "description": "업무 자동화(사내 가상 API) — M코스메틱 이메일 에이전트(M코스메틱 영업팀 고객 메일 업무: 고객 메일 "
                       "자동 분류·담당자 확인 필요 메일·견적요청/주문등록/출하일정/재고문의/인보이스 발행요청 메일 현황·업무 Case·"
                       "ERP/메일 API 처리 오류 조회, 메일별 ERP 조회·답변 초안·오류 재처리 실행과 사용자 확인 후 ERP 주문등록·"
                       "답변 메일 발송)와 교육 에이전트"
                       "(교육 자료 파이프라인·검토 대기·권리 보류·권리 원장(저작권 대조)·적재 문서·이수율·라이선스·감사 로그 조회)의 운영. "
                       "개인 메일 조회·작성·발송, 일정·할 일 조회·실행은 그룹웨어 소관",
        "run": None,  # 아래에서 본 구현으로 바인딩 (STEP 7)
        # bound to the real implementation below (STEP 7)
    },
}

# 본 구현 바인딩 (모듈 하단 import — AgentResult 정의 후라 순환 import 안전)
# Bind real implementations (imported at module bottom — safe from circular import since it's after AgentResult is defined)
from app.agents import data as _data  # noqa: E402
from app.agents import groupware as _groupware  # noqa: E402
from app.agents import knowledge as _knowledge  # noqa: E402
from app.agents import work as _work  # noqa: E402

AGENT_REGISTRY["knowledge"]["run"] = _knowledge.run
AGENT_REGISTRY["data"]["run"] = _data.run
AGENT_REGISTRY["groupware"]["run"] = _groupware.run
AGENT_REGISTRY["work"]["run"] = _work.run
