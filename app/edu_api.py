"""교육 에이전트 API — 업무 자동화 실구축 1차 (2026-08-24).

실물 API가 없어 자체 구축(사용자 확정): edu_agent.py의 실 스토어를 이 라우터가 노출한다.
- 리소스 관리의 API 레지스트리(RM_EDU_API 12종)를 스펙 그대로 구현 — 응답은 {success, data}.
- /ask는 계약({ns?,idx?,question,chat_id?}→{chat_id,title,answer,exec}) 유지, 내부만 실전환:
  경량 의도 계획(llm lite, 실패 시 키워드 규칙) → 스토어 실 조회 → llm main 답변(근거=조회 데이터,
  실패 시 결정적 표 폴백) → exec는 실제 수행한 조회 단계에서 생성(연출이 아니라 기록).
- 권한: agent_edu 노드 레벨≥1(에이전트 노드 단위 게이팅, 사용자 확정) — acting_user_id 신설.
- 구 ns/idx 시드 경로와 /panel 상수는 호환 유지(고아지만 저비용).

Education-agent API — automation real-build round 1. The real store (edu_agent.py) backs this
router; the RM registry (12 endpoints) is implemented as spec with {success, data} envelopes.
/ask keeps its contract but swaps to: lite intent planning (keyword fallback) → real store lookups
→ main-tier answer grounded on the data (deterministic table fallback) → exec built from the steps
actually executed. Gated per agent node (agent_edu ≥ 1) via the new acting_user_id field.
"""

import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import access, db, edu_agent, llm

logger = logging.getLogger("ai365.edu_api")

router = APIRouter(prefix="/api/edu", tags=["edu"])


def _gate(acting_user_id: str) -> None:
    """에이전트 노드 게이팅(2026-08-24 사용자 확정) — agent_edu 레벨≥1, ''=슈퍼 우회."""
    # Per-agent node gating — agent_edu level >= 1; '' = super bypass.
    eff = access.resolve_eff(acting_user_id)
    if eff is not None and (eff.get("nodes") or {}).get("agent_edu", 0) < 1:
        raise HTTPException(status_code=403, detail="교육 에이전트 접근 권한이 없습니다")

# 상태 분포 — 데모 화면 KPI 5종과 동일(오늘 수집 15 · 적재 6 · 검토 4 · 업로드 대기 1 · 보류 4)
# Status distribution — identical to the demo page's five KPIs
_KPI = {"collected": 15, "uploaded": 6, "review": 4, "staged": 1, "held": 4}

# 최근 수집 문서 — lv=라이선스 등급(L1 자유~L5 접근 제한), why=화면의 판정 사유 문구 그대로
# Recently collected documents — lv = license level (L1 free .. L5 restricted), why = the page's verdict text
_DOCS = [
    {"time": "방금", "title": "히트펌프 설치·시운전 실무 가이드", "source": "한국에너지공단 · 공공누리 제1유형",
     "lv": 1, "state": "staged", "state_label": "업로드 대기",
     "why": "L1 자유 이용 — 자동 적재 경로. 업로드 전 유예 구간에서 취소할 수 있습니다."},
    {"time": "10:12", "title": "R-32 냉매 안전 취급 교육 스크립트", "source": "OpenHVAC Education Commons · CC BY-NC 4.0",
     "lv": 2, "state": "review", "state_label": "검토",
     "why": "카탈로그 CC-BY-NC-4.0 표기 인식 — AI 인덱싱·교육 용도가 법무 확정 대기(legal_review)라 자동 적재 금지 [R02·R13]"},
    {"time": "09:41", "title": "저GWP 냉매 전환 F-gas 규제 해설", "source": "환경부 자료실",
     "lv": 1, "state": "uploaded", "state_label": "적재됨",
     "why": "L1 자유 이용 — 자동 적재. SharePoint 업로드와 동시에 RAG·Viva Learning에 배포되었습니다."},
    {"time": "09:20", "title": "상업용 보일러 교체 수요 벤치마크 백서", "source": "Strathorn Consulting",
     "lv": 3, "state": "review", "state_label": "검토",
     "why": "L3 라이선스 불명 — 표기 부재는 자유 이용이 아니라 보호가 기본값 [R02·R08]"},
    {"time": "08:55", "title": "경쟁사 파트너 포털 내부 기술문서", "source": "경쟁사 파트너 포털",
     "lv": 5, "state": "blocked", "state_label": "차단·폐기",
     "why": "L5 접근 제한 — 접근 통제 우회가 필요해 수집 차단, 기록 후 폐기 [R01]"},
]

# 검토 대기(사람 판단) — 데모 화면 검토함 4건과 동일한 판정 사유·근거 스냅샷
# Human-review queue — same four items, verdicts, and evidence snapshots as the demo page
_REVIEWS = [
    {"title": "인버터 히트펌프 신제품 COP 향상 기술 공개", "chip": "저신뢰 58%",
     "reason": "AI 신뢰도 58% < 임계값 70% — 사람 검토로 회부 [R12]",
     "snap": "\"본 보도자료는 비상업적 보도 목적에 한해 자유롭게 인용할 수 있습니다. 기타 이용은 홍보팀 문의…\"",
     "contact": "제조사 홍보팀"},
    {"title": "ASHRAE 환기·실내공기질 가이드 공개 요약본", "chip": "L3 무표기",
     "reason": "L3 라이선스 불명 — 표기 부재는 자유 이용이 아니라 보호가 기본값 [R02·R08]",
     "snap": "요약본에 라이선스·재사용 조건 문구 없음 · 이용약관 링크 발견되지 않음 · 페이월 없음",
     "contact": "standards@ashrae.example"},
    {"title": "상업용 보일러 교체 수요 벤치마크 백서", "chip": "L3 무표기",
     "reason": "L3 라이선스 불명 — '무료 제공'만 명시, 재배포 조건 없음 [R02·R08]",
     "snap": "\"All insights are provided free of charge for registered users…\" · 원본 확보 실패 ×2, 재시도 대기",
     "contact": "insights@strathorn.example"},
    {"title": "R-32 냉매 안전 취급 교육 스크립트", "chip": "법무 확정 대기",
     "reason": "CC BY-NC 4.0 인식 — 교육 용도 법무 확정 대기(legal_review)라 자동 적재 금지, 확정 시 자동 재평가 [R02·R13]",
     "snap": "\"이 자료는 CC BY-NC 4.0에 따라 비영리 목적에 한해 자유롭게 이용할 수 있습니다…\"",
     "contact": "법무팀"},
]

# 학습 현황 — 전사 이수율·마감 관리 목록(데모 교육 대시보드 표본과 동일)
# Learning status — company completion rate and the deadline-management list (same sample as the demo dashboard)
_LEARNING = {
    "overall": 68, "required": 81, "manage": 23,
    "deadlines": [
        {"name": "정우진", "dept": "영업기술지원", "course": "R-32 냉매 안전 취급 교육", "label": "초과 6일", "overdue": True},
        {"name": "한지민", "dept": "구매", "course": "저GWP 냉매 전환 F-gas 규제 해설", "label": "초과 3일", "overdue": True},
        {"name": "오세훈", "dept": "경영지원", "course": "히트펌프 설치·시운전 실무 가이드", "label": "초과 1일", "overdue": True},
        {"name": "최민지", "dept": "생산기술", "course": "저GWP 냉매 전환 F-gas 규제 해설", "label": "D-2", "overdue": False},
        {"name": "박준영", "dept": "품질보증", "course": "콘덴싱 보일러 효율 개선 기술자료", "label": "D-4", "overdue": False},
    ],
    "depts": [
        {"name": "기술연구소", "pct": 84}, {"name": "품질보증", "pct": 77}, {"name": "생산기술", "pct": 71},
        {"name": "영업기술지원", "pct": 63}, {"name": "구매", "pct": 52}, {"name": "경영지원", "pct": 41},
    ],
}

# 파이프라인 요약 — 지금 조치가 필요한 상태 3종(hint=데모 화면 단계 설명 문구)
# Pipeline summary — the three states needing attention now (hint = the demo page's stage description)
_PIPELINE = {
    "stages": "서칭·수집 → 분류·요약 → 검증·판정 → 원본 확보 → 업로드 대기 → SharePoint 업로드 → RAG·Viva 배포",
    # view = 교육 데모 화면의 setView 탭 키(딥링크용) — staging/queue/hold
    # view = the demo page's setView tab key (for deep links) — staging/queue/hold
    "rows": [
        {"t1": "업로드 대기 1건", "t2": "취소할 수 있는 마지막 지점", "view": "staging",
         "hint": "원본 확보·내부 대조를 마친 문서가 업로드 전 유예 상태로 대기합니다. SharePoint 업로드 후에는 회수할 수 없습니다(비가역)."},
        {"t1": "검토 대기 4건", "t2": "사람 판단 필요", "view": "queue",
         "hint": "신뢰도 임계(70%) 미달·라이선스 불명(L3)·법무 확정 대기 문서는 자동 적재 대신 사람 검토로 회부됩니다."},
        {"t1": "보류 4건", "t2": "권리 확보 대기", "view": "hold",
         "hint": "L4 명시적 제한 문서 — 권리 원장에 유효 라이선스가 등록되면 자동으로 재평가되어 재개됩니다."},
    ],
}


@router.get("/panel")
def panel(acting_user_id: str = "") -> dict:
    _gate(acting_user_id)
    return {"kpi": _KPI, "docs": _DOCS, "reviews": _REVIEWS, "learning": _LEARNING, "pipeline": _PIPELINE}


# ─────────────────────────────────────────────────────────────────────────────
# 실 API — RM_EDU_API 레지스트리 12종을 스펙 그대로 구현(응답 {success, data}). 전부 실 스토어.
# Real API — the 12 registry endpoints implemented as spec ({success, data} envelopes), all store-backed.
# ─────────────────────────────────────────────────────────────────────────────

def _ok(data: dict) -> dict:
    return {"success": True, "data": data}


@router.get("/documents")
def documents(route: str = "", level: str = "", acting_user_id: str = "") -> dict:
    _gate(acting_user_id)
    # 레지스트리 스펙은 level을 'L2' 같은 문자열로 예시한다 — 'L2'/'2' 모두 수용(리뷰 확정)
    # The registry samples level as a string ('L2') — accept both 'L2' and '2'
    lv = 0
    v = level.strip().upper().lstrip("L")
    if v:
        if not v.isdigit():
            raise HTTPException(status_code=422, detail="level은 'L1'~'L5' 또는 1~5여야 합니다")
        lv = int(v)
    return _ok({"documents": edu_agent.list_docs(route=route, level=lv)})


@router.get("/documents/{doc_id}")
def document_detail(doc_id: str, acting_user_id: str = "") -> dict:
    _gate(acting_user_id)
    doc = edu_agent.get_doc(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 문서입니다")
    return _ok({"document": doc})


@router.get("/licenses/catalog")
def licenses_catalog(acting_user_id: str = "") -> dict:
    _gate(acting_user_id)
    return _ok(edu_agent.license_catalog())


class EvaluateIn(BaseModel):
    url: str
    text: str = ""
    acting_user_id: str = ""


@router.post("/licenses/evaluate")
def licenses_evaluate(body: EvaluateIn) -> dict:
    _gate(body.acting_user_id)
    if not body.url.strip():
        raise HTTPException(status_code=422, detail="url이 비어 있습니다")
    return _ok(edu_agent.evaluate_license(body.url, body.text))


@router.get("/pipeline/status")
def pipeline_status(acting_user_id: str = "") -> dict:
    _gate(acting_user_id)
    return _ok(edu_agent.pipeline_status())


class RequeueIn(BaseModel):
    documentId: str
    acting_user_id: str = ""


@router.post("/pipeline/requeue")
def pipeline_requeue(body: RequeueIn) -> dict:
    _gate(body.acting_user_id)
    out = edu_agent.requeue(body.documentId)
    if out is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 문서입니다")
    if out.get("error"):
        raise HTTPException(status_code=out.get("status", 422), detail=out["error"])
    return _ok(out)


class ReviewIn(BaseModel):
    verdict: str   # approve | reject
    note: str = ""
    acting_user_id: str = ""


@router.post("/documents/{doc_id}/review")
def submit_review(doc_id: str, body: ReviewIn) -> dict:
    _gate(body.acting_user_id)
    out = edu_agent.submit_review(doc_id, body.verdict, body.note)
    if out is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 문서입니다")
    if out.get("error"):
        raise HTTPException(status_code=out.get("status", 422), detail=out["error"])
    return _ok(out)


@router.get("/audit")
def audit(top: int = 30, acting_user_id: str = "") -> dict:
    _gate(acting_user_id)
    return _ok({"events": edu_agent.list_audit(top)})


@router.get("/tenants/{tenant_id}/settings")
def tenant_settings(tenant_id: str, acting_user_id: str = "") -> dict:
    _gate(acting_user_id)
    return _ok({"tenant": tenant_id, "settings": edu_agent.tenant_settings()})


@router.get("/learning/records")
def learning_records(userId: str = "", acting_user_id: str = "") -> dict:  # noqa: N803 — 레지스트리 스펙 파라미터명 유지
    _gate(acting_user_id)
    return _ok({"records": edu_agent.learning_records(userId)})


@router.get("/learning/org")
def learning_org(dept: str = "", acting_user_id: str = "") -> dict:
    _gate(acting_user_id)
    return _ok({"completion": edu_agent.org_completion(dept)})


@router.get("/contents/search")
def contents_search(q: str, acting_user_id: str = "") -> dict:
    _gate(acting_user_id)
    return _ok({"contents": edu_agent.search_contents(q)})


# ─────────────────────────────────────────────────────────────────────────────
# 패널 질의 버튼 = 데모 응답(사용자 확정 2026-08-20) — 버튼이 실제 파이프라인(LLM·웹) 대신 아래
# 시드 답변으로 채팅을 만든다. **실 연동 작업 때 이 /ask 내부만 갈아끼우면 된다**(어댑터 계약:
# POST /ask {ns, idx, question} → {chat_id, title}). 답변은 마크다운 — 어댑터 렌더러가 그린다.
# Panel query buttons = demo answers (user decision 2026-08-20) — instead of the real pipeline
# (LLM/web), a button creates a chat from the seed answers below. **Real integration later only
# swaps the inside of /ask** (adapter contract: POST /ask {ns, idx, question} → {chat_id, title}).
# Answers are markdown, drawn by the adapter's renderer.
_LEARN_ANSWERS = {
    "R-32 냉매 안전 취급 교육": (
        "### R-32 냉매 안전 취급 — 과정 요약\n"
        "- **냉매 특성**: R-32는 A2L(약가연성) 등급 — 누설 시 체류하지 않도록 환기가 핵심입니다.\n"
        "- **취급 절차**: 회수→진공→충전 순서를 지키고, 전용 게이지·회수기를 사용합니다.\n"
        "- **누설 대응**: 감지기 경보 시 화기 차단 → 환기 → 누설 부위 격리 순으로 조치합니다.\n"
        "- **이수 요건**: 취급 실습 평가 포함, 법정 보수 교육 2년 주기."
    ),
    "저GWP 냉매 전환 F-gas 규제 해설": (
        "### 저GWP 냉매 전환 F-gas 규제 — 과정 요약\n"
        "- **규제 골자**: HFC 냉매의 단계적 감축 쿼터와 GWP 상한이 도입되어 신규 장비의 냉매 선택이 제한됩니다.\n"
        "- **전환 일정**: 고GWP 냉매 신규 충전 제한 → 저GWP(R-32·R-454B 등) 전환이 순차 적용됩니다.\n"
        "- **실무 영향**: 서비스·유지보수 시 회수·재생 의무와 기록 관리가 강화됩니다.\n"
        "- **핵심 체크**: 보유 장비의 냉매별 규제 일정을 대장으로 관리하세요."
    ),
    "히트펌프 설치·시운전 실무 가이드": (
        "### 히트펌프 설치·시운전 — 과정 요약\n"
        "- **설치 전**: 실외기 이격 거리·배관 길이 한계·전원 용량을 먼저 확인합니다.\n"
        "- **시운전**: 기밀 시험 → 진공 → 냉매 충전량 확인 → 모드별 압력·온도 점검 순서로 진행합니다.\n"
        "- **성능 점검**: 정격 조건 COP 측정과 외기 온도별 능력 곡선 기록이 필수입니다.\n"
        "- **안전**: 냉매 배관 작업은 자격 보유자가 수행하고 작업 기록을 남깁니다."
    ),
    "콘덴싱 보일러 효율 개선 기술자료": (
        "### 콘덴싱 보일러 효율 개선 — 과정 요약\n"
        "- **원리**: 배기 잠열 회수로 효율을 높이므로 낮은 환수 온도 유지가 성능의 관건입니다.\n"
        "- **개선 포인트**: 난방 곡선(외기 보상) 최적화, 순환 펌프 유량 조정, 응축수 배관 점검.\n"
        "- **점검 주기**: 열교환기 스케일·응축수 트랩은 시즌 전 점검이 표준입니다."
    ),
}

_ANSWERS = {
    "docs": [
        _LEARN_ANSWERS["히트펌프 설치·시운전 실무 가이드"],
        _LEARN_ANSWERS["R-32 냉매 안전 취급 교육"],
        _LEARN_ANSWERS["저GWP 냉매 전환 F-gas 규제 해설"],
        (
            "### 상업용 보일러 교체 수요 벤치마크 — 주제 브리핑\n"
            "- **교체 주기**: 상업용 보일러는 통상 12~15년 주기로 교체 수요가 발생합니다.\n"
            "- **수요 동인**: 효율 규제 강화, 연료비 상승, 노후 설비 고장률 증가가 3대 동인입니다.\n"
            "- **ROI 관점**: 콘덴싱 전환 시 연료비 절감으로 3~5년 내 회수가 일반적 벤치마크입니다.\n"
            "> 이 문서는 라이선스 불명(L3) 상태라 원문 인용 없이 일반 지식 기준으로 정리했습니다."
        ),
        (
            "### 경쟁사 파트너 포털 문서 — 안내\n"
            "이 문서는 **접근 통제 우회가 필요한 L5 소스**라 수집이 차단되고 기록 후 폐기되었습니다.\n"
            "- 원문 없이 답변할 수 없는 항목이며, 감사 로그에서 차단 이력을 확인할 수 있습니다.\n"
            "- 유사 주제가 필요하면 공개 소스(표준·협회 자료) 기반 수집을 요청하세요."
        ),
    ],
    "review": [
        (
            "### 검토 포인트 — 인버터 히트펌프 COP 보도자료\n"
            "- **판정 상태**: AI 신뢰도 58%로 임계값(70%) 미달 — 사람 판단이 필요합니다.\n"
            "- **확인할 것**: \"비상업적 보도 목적\" 문구가 사내 교육 이용을 허용하는지 홍보팀 확인이 필요합니다.\n"
            "- **권고**: 성능 수치만 발췌 인용하는 경우에도 출처 표기와 이용 범위 확인이 선행돼야 합니다."
        ),
        (
            "### 검토 포인트 — ASHRAE 요약본\n"
            "- **판정 상태**: 라이선스 표기가 없음 — 표기 부재는 자유 이용이 아니라 **보호가 기본값**입니다.\n"
            "- **확인할 것**: standards@ashrae.example로 재사용 조건을 문의하고 회신을 원장에 기록하세요.\n"
            "- **권고**: 회신 전까지는 링크 공유만 하고 원문 재배포는 보류합니다."
        ),
        (
            "### 검토 포인트 — 보일러 교체 수요 백서\n"
            "- **판정 상태**: '무료 제공'만 명시되고 재배포 조건이 없음(L3) + 등록 게이트 존재.\n"
            "- **확인할 것**: 등록 사용자 한정 제공 조건이 사내 시스템 적재를 허용하는지 문의가 필요합니다.\n"
            "- **권고**: 원본 확보도 2회 실패 상태 — 문의 회신 후 재수집을 권장합니다."
        ),
        (
            "### 검토 포인트 — R-32 교육 스크립트\n"
            "- **판정 상태**: CC BY-NC 4.0 표기 인식 — 다만 AI 인덱싱·교육 용도가 **법무 확정 대기**입니다.\n"
            "- **확인할 것**: 비영리 조건이 사내 교육(영리 법인 내부 이용)에 적용 가능한지 법무 판단이 핵심입니다.\n"
            "- **권고**: 법무 확정 시 자동 재평가로 업로드 대기로 이동하므로 별도 조치는 불필요합니다."
        ),
    ],
    "pipe": (
        "### 왜 라이선스 검증이 필요한가 — 정책 브리핑\n"
        "- **비가역 배포**: SharePoint 업로드 순간 RAG·Viva에 동시 배포되어 회수가 불가능합니다.\n"
        "- **법적 리스크**: 무단 수집 자료가 AI 답변에 인용되면 저작권 침해가 조직 전체로 확산됩니다.\n"
        "- **보호 기본값**: 표기가 없는 자료는 자유 이용이 아니라 보호가 기본 — L3는 반드시 사람이 검토합니다.\n"
        "- **원칙**: 등급 상향은 **라이선스 확보로만** 가능하며, 판정 근거는 감사 로그에 남습니다."
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# 에이전트 모드 실행 연출(2026-08-23, 2차 개편) — email_api와 같은 계약. exec = 어댑터가 그리는
# 실행 블록(작업 진행줄 + 병렬 think 트리) 시드, 자유 질문은 키워드 매칭(_FREE) → 기본 답변,
# chat_id가 오면 기존 채팅에 이어 붙인다. **실 연동 때 이 /ask 내부만 교체.**
# Agent-mode execution staging (2026-08-23, rework round 2) — same contract as email_api.
# exec seeds the adapter-drawn execution block; free questions match keywords then fall back to the
# default answer; chat_id appends to an existing chat. **Real integration swaps only /ask's inside.**
_AGENT_LABEL = "교육 에이전트"

_EXEC_DEFAULT = {
    "agent": "edu",
    "agent_label": _AGENT_LABEL,
    "tasks": [
        "오늘 수집된 문서 15건을 조회했습니다.",
        "라이선스 등급과 판정 상태를 분석했습니다.",
        "검토 대기·보류·차단 문서를 분류했습니다.",
        "학습 현황과 마감 임박 과정을 집계했습니다.",
        "조치가 필요한 항목을 정리했습니다.",
    ],
    "think": {
        "title": "작업을 병렬로 실행",
        "groups": [
            {"label": "수집 문서를 분석합니다.", "lines": [
                "오늘 수집 15건 중 적재 6건·업로드 대기 1건을 확인했습니다.",
                "라이선스 등급(L1~L5)과 판정 사유를 검토했습니다.",
                "차단·폐기된 L5 소스 1건을 감사 로그에 기록했습니다."]},
            {"label": "검토·보류 문서를 확인합니다.", "lines": [
                "사람 판단이 필요한 검토 대기 4건을 확인했습니다.",
                "저신뢰·라이선스 불명·법무 확정 대기 사유를 정리했습니다.",
                "권리 확보 대기(보류) 4건의 재평가 조건을 확인했습니다."]},
            {"label": "분석 결과를 통합합니다.", "lines": [
                "전사 이수율과 부서별 현황을 집계했습니다.",
                "마감 초과·임박 대상자를 우선순위로 배치했습니다.",
                "요약 답변을 작성했습니다."]},
        ],
    },
}

_ANSWER_DEFAULT = (
    "교육 지식 파이프라인 현황을 정리했습니다. 오늘 **수집 15건** — 적재 6건, 검토 대기 4건, "
    "업로드 대기 1건, 보류 4건입니다.\n\n"
    "| 구분 | 건수 | 상태 |\n"
    "|---|---|---|\n"
    "| 적재됨 | 6 | L1 자유 이용 — RAG·Viva Learning 배포 완료 |\n"
    "| 검토 대기 | 4 | 저신뢰·라이선스 불명·법무 확정 대기 — 사람 판단 필요 |\n"
    "| 업로드 대기 | 1 | 업로드 전 유예 — 취소 가능한 마지막 지점 |\n"
    "| 보류 | 4 | L4 명시적 제한 — 권리 확보 시 자동 재평가 |\n\n"
    "### 권장 조치\n"
    "1. 검토 대기 4건부터 판정하세요 — 법무 확정 대기 건은 확정 시 자동 재평가됩니다.\n"
    "2. 업로드 대기 1건은 업로드 후 회수가 불가능하니 배포 범위를 확인하세요."
)

_ANSWER_LEARN = (
    "학습 현황을 정리했습니다 — **전사 이수율 68%**, 필수 과정 81%, 마감 관리 대상 23명.\n\n"
    "| 대상자 | 부서 | 과정 | 상태 |\n"
    "|---|---|---|---|\n"
    "| 정우진 | 영업기술지원 | R-32 냉매 안전 취급 교육 | 초과 6일 |\n"
    "| 한지민 | 구매 | 저GWP 냉매 전환 F-gas 규제 해설 | 초과 3일 |\n"
    "| 오세훈 | 경영지원 | 히트펌프 설치·시운전 실무 가이드 | 초과 1일 |\n"
    "| 최민지 | 생산기술 | 저GWP 냉매 전환 F-gas 규제 해설 | D-2 |\n"
    "| 박준영 | 품질보증 | 콘덴싱 보일러 효율 개선 기술자료 | D-4 |\n\n"
    "### 부서별 이수율\n"
    "기술연구소 84% · 품질보증 77% · 생산기술 71% · 영업기술지원 63% · 구매 52% · 경영지원 41%\n\n"
    "### 권장 조치\n"
    "1. 마감 초과 3명에게 이수 독려 안내를 발송하세요.\n"
    "2. 이수율 하위 부서(경영지원·구매)는 부서장 공유를 권장합니다."
)

_ANSWER_REVIEW = (
    "검토 대기 문서 **4건**의 판정 포인트를 정리했습니다.\n\n"
    "| 문서 | 사유 | 확인할 것 |\n"
    "|---|---|---|\n"
    "| 인버터 히트펌프 COP 보도자료 | AI 신뢰도 58% < 70% | 보도 목적 문구의 사내 교육 적용 여부 |\n"
    "| ASHRAE 요약본 | L3 라이선스 불명 | 재사용 조건 문의 회신 대기 |\n"
    "| 보일러 교체 수요 백서 | L3 무표기 + 등록 게이트 | 사내 적재 허용 여부 문의 |\n"
    "| R-32 교육 스크립트 | CC BY-NC 법무 확정 대기 | 확정 시 자동 재평가 — 별도 조치 불필요 |\n\n"
    "> 표기가 없는 자료는 자유 이용이 아니라 **보호가 기본값**입니다. 판정 근거는 감사 로그에 남습니다."
)

_FREE = [
    {"kw": ["이수", "학습", "교육 현황", "마감"], "answer": _ANSWER_LEARN},
    {"kw": ["검토", "판정", "라이선스"], "answer": _ANSWER_REVIEW},
    {"kw": ["수집", "파이프라인", "적재"], "answer": _ANSWER_DEFAULT},
]


# ─────────────────────────────────────────────────────────────────────────────
# /ask 실전환(2026-08-24) — 규칙 우선 도구 선택(오분류해도 기본 폴백) → 실 스토어 조회 →
# llm main 답변(근거=조회 데이터만, 실패 시 결정적 표 폴백) → exec는 실행한 단계의 기록.
# 쓰기 의도(승인·반려 등)는 실행하지 않고 화면·API 경로를 안내한다(무단 변이 방지 — 플랜 확정).
# /ask real engine — rules-first tool selection, real store lookups, main-tier grounded answer with
# a deterministic fallback; exec records the steps actually run. Write intents are never executed
# from chat: the answer points to the screen/API actions instead (approved plan).
# ─────────────────────────────────────────────────────────────────────────────

_ASK_SYSTEM = (
    "너는 사내 교육 지식 파이프라인을 관리하는 교육 에이전트다. 주어진 [데이터]에 있는 내용만 근거로 "
    "사용자 질문에 한국어 마크다운으로 답한다. 수치·문서명·판정 사유는 데이터에 있는 그대로 쓰고, "
    "데이터에 없는 사실은 지어내지 않는다. 표가 어울리면 마크다운 표를 쓰고, 마지막에 '권장 조치'를 "
    "1~3개 제안한다. 실행(승인·반려·재판정)이 필요하면 검토 화면이나 API에서 하도록 안내만 한다."
)

_WRITE_KWS = ("승인", "반려", "처리해", "실행해", "올려줘", "재큐", "재판정해", "적재해")


def _ask_lookups(question: str) -> list[str]:
    """규칙 우선 도구 선택 — 매칭 없으면 파이프라인+검토 기본 세트."""
    q = question or ""
    picks: list[str] = []
    if any(k in q for k in ("이수", "학습", "교육 현황", "마감", "부서")):
        picks.append("learning")
    if any(k in q for k in ("검토", "판정")):
        picks.append("review")
    if any(k in q for k in ("보류", "권리", "계약", "라이선스", "만료")):
        picks += ["held", "licenses"]
    if any(k in q for k in ("감사", "차단", "로그", "이력")):
        picks.append("audit")
    if any(k in q for k in ("적재", "업로드", "배포")):
        picks.append("uploaded")
    if any(k in q for k in ("수집", "파이프라인", "현황", "브리핑")):
        picks.append("pipeline")
    if not picks:
        picks = ["pipeline", "review"]
    seen: set[str] = set()
    return [p for p in picks if not (p in seen or seen.add(p))][:4]


def _doc_brief(d: dict) -> dict:
    return {"id": d["id"], "title": d["title"], "type": d["type"], "source": d["source"],
            "level": f"L{d['lv']}", "conf": d["conf"], "state": d["state"], "why": d["eval_why"]}


def _run_lookup(name: str, question: str) -> tuple[dict, str, str]:
    """→ (데이터, 작업 진행줄, think 줄) — 진행줄·think는 실측 수치를 담는다."""
    if name == "pipeline":
        data = edu_agent.pipeline_status()
        k = data["kpi"]
        return ({"pipeline": data},
                f"파이프라인 현황을 조회했습니다 — 수집 {k['collected']}건.",
                f"수집 {k['collected']} · 적재 {k['uploaded']} · 검토 {k['review']} · 대기 {k['staged']} · 보류 {k['held']}를 집계했습니다.")
    if name == "review":
        docs = [_doc_brief(d) for d in edu_agent.list_docs(route="review")]
        return ({"review_docs": docs}, f"검토 대기 {len(docs)}건을 조회했습니다.",
                f"사람 판단이 필요한 검토 대기 {len(docs)}건과 판정 사유를 확인했습니다.")
    if name == "held":
        docs = [_doc_brief(d) for d in edu_agent.list_docs(route="held")]
        return ({"held_docs": docs}, f"권리 보류 {len(docs)}건을 조회했습니다.",
                f"권리 확보 대기(보류) {len(docs)}건의 재평가 조건을 확인했습니다.")
    if name == "uploaded":
        docs = [_doc_brief(d) for d in edu_agent.list_docs(route="uploaded")]
        return ({"uploaded_docs": docs}, f"적재 완료 {len(docs)}건을 조회했습니다.",
                f"RAG·Viva로 배포된 적재 문서 {len(docs)}건을 확인했습니다.")
    if name == "learning":
        rec, org = edu_agent.learning_records(), edu_agent.org_completion()
        return ({"learning_deadlines": rec, "org_completion": org},
                f"학습 현황과 마감 대상 {len(rec)}명을 집계했습니다.",
                f"전사 이수율 {org['overall']}%와 부서 {len(org['depts'])}곳 현황을 집계했습니다.")
    if name == "audit":
        ev = edu_agent.list_audit(10)
        return ({"audit_events": ev}, f"감사 로그 최근 {len(ev)}건을 조회했습니다.",
                "수집·차단·판정 이력을 감사 로그에서 확인했습니다.")
    if name == "licenses":
        cat = edu_agent.license_catalog()
        return ({"licenses": cat}, f"권리 원장 계약 {len(cat['ledger'])}건을 대조했습니다.",
                "계약별 허용 용도(사내·AI·교육)와 만료일을 대조했습니다.")
    return ({}, "", "")


def _fallback_answer(data: dict) -> str:
    """LLM 전면 장애 시 결정적 요약(시연 내성) — 조회 데이터만으로 표를 만든다."""
    parts = ["조회 결과를 정리했습니다."]
    if "pipeline" in data:
        k = data["pipeline"]["kpi"]
        parts.append(f"**파이프라인** — 수집 {k['collected']} · 적재 {k['uploaded']} · 검토 {k['review']} · "
                     f"업로드 대기 {k['staged']} · 보류 {k['held']}")
    for key, label in (("review_docs", "검토 대기"), ("held_docs", "권리 보류"), ("uploaded_docs", "적재 완료")):
        if data.get(key):
            rows = "\n".join(f"| {d['title']} | {d['level']} | {d['why'][:40]} |" for d in data[key])
            parts.append(f"### {label} {len(data[key])}건\n| 문서 | 등급 | 사유 |\n|---|---|---|\n{rows}")
    if data.get("learning_deadlines"):
        rows = "\n".join(f"| {r['name']} | {r['dept']} | {r['course']} | {r['label']} |" for r in data["learning_deadlines"])
        parts.append(f"### 마감 관리 대상\n| 대상자 | 부서 | 과정 | 상태 |\n|---|---|---|---|\n{rows}")
    # 전사 이수율 — learning 조회가 함께 담는 근거(리뷰 확정: 미렌더로 '전사 이수율' 질문의 근거가 탈락했었다)
    # Org completion rides along with the learning lookup (review finding: it was silently dropped)
    if data.get("org_completion"):
        org = data["org_completion"]
        rows = "\n".join(f"| {d['name']} | {d['pct']}% |" for d in (org.get("depts") or []))
        parts.append(f"### 전사 이수 현황 — 전체 {org.get('overall')}% · 필수 {org.get('required')}% · 관리 대상 {org.get('manage')}건"
                     + (f"\n| 부서 | 이수율 |\n|---|---|\n{rows}" if rows else ""))
    # 권리 계약 — licenses 조회의 결정적 표(리뷰 확정: 미렌더 키라 원시 JSON이 노출됐었다)
    # License ledger tables (review finding: an unrendered key used to surface as raw JSON)
    if data.get("licenses"):
        cat = data["licenses"]
        std = "\n".join(f"| {s['name']} | L{s['level']} | {s['verdict']} |" for s in (cat.get("standard") or []))
        led = "\n".join(
            f"| {li['name']} | {li['scope']} | ~{li.get('end') or '무기한'} | "
            + ("만료" if li.get("status") == "expired" else "유효") + " |"
            for li in (cat.get("ledger") or []))
        if std:
            parts.append(f"### 표준 카탈로그 판정\n| 라이선스 | 등급 | 판정 |\n|---|---|---|\n{std}")
        if led:
            parts.append(f"### 권리 원장 계약\n| 계약 | 범위 | 만료 | 상태 |\n|---|---|---|---|\n{led}")
    if data.get("audit_events"):
        parts.append("### 최근 감사 이력\n" + "\n".join(f"- {e['move']} — {e['doc']}" for e in data["audit_events"][:5]))
    return "\n\n".join(parts)


def _real_ask(question: str) -> tuple[str, dict]:
    lookups = _ask_lookups(question)
    data: dict = {}
    tasks: list[str] = []
    think1: list[str] = []
    for name in lookups:
        d, task, line = _run_lookup(name, question)
        data.update(d)
        if task:
            tasks.append(task)
            think1.append(line)
    write_intent = any(k in (question or "") for k in _WRITE_KWS)
    try:
        text = llm.generate(
            [{"role": "user", "content": f"[데이터]\n{json.dumps(data, ensure_ascii=False)}\n\n[질문]\n{question or '현황을 브리핑해줘'}"}],
            system=_ASK_SYSTEM, tier="main")
        answer, src = (text if isinstance(text, str) else str(text)).strip(), "live"
    except Exception:  # noqa: BLE001 — 시연 내성 / demo resilience
        logger.warning("교육 /ask LLM 실패 — 결정적 폴백", exc_info=True)
        answer, src = _fallback_answer(data), "seed"
    if write_intent:
        answer = ("> 승인·반려 같은 **실행**은 채팅에서 바로 처리하지 않습니다 — 교육 에이전트 화면의 검토 큐 "
                  "또는 검토 API에서 진행해 주세요. 아래는 판단에 필요한 현황입니다.\n\n") + answer
    tasks.append("조회 결과를 근거로 답변을 정리했습니다.")
    exec_block = {
        "agent": "edu", "agent_label": _AGENT_LABEL,
        "tasks": tasks[:5],
        "think": {"title": "작업을 병렬로 실행", "groups": [
            {"label": "실 데이터를 조회합니다.", "lines": think1 or ["파이프라인 현황을 조회했습니다."]},
            {"label": "근거를 정리합니다.", "lines": [
                f"조회 {len(lookups)}종의 결과를 대조해 근거를 추렸습니다.",
                "수치·문서명·판정 사유는 스토어 값 그대로 사용합니다.",
                "실행이 필요한 조치는 화면·API 경로로 안내합니다." if write_intent else "조치가 필요한 항목을 우선순위로 배치했습니다."]},
            {"label": "답변을 작성합니다.", "lines": [
                "조회 데이터만 근거로 답변을 생성했습니다." if src == "live" else "LLM 폴백 — 조회 데이터를 결정적 요약으로 정리했습니다.",
                "권장 조치를 덧붙였습니다."]},
        ]},
    }
    return answer, exec_block


class AskIn(BaseModel):
    ns: str = ""
    idx: int = 0
    question: str = ""
    chat_id: str = ""
    acting_user_id: str = ""


@router.post("/ask")
def ask(body: AskIn) -> dict:
    _gate(body.acting_user_id)
    exec_block = _EXEC_DEFAULT
    if body.ns == "learn":
        rows = _LEARNING["deadlines"]
        if not (0 <= body.idx < len(rows)):
            raise HTTPException(status_code=404, detail="항목을 찾을 수 없습니다")
        answer = _LEARN_ANSWERS.get(rows[body.idx]["course"], _ANSWERS["pipe"])
    elif body.ns == "pipe":
        answer = _ANSWERS["pipe"]
    elif body.ns:
        rows = _ANSWERS.get(body.ns)
        if not rows or not (0 <= body.idx < len(rows)):
            raise HTTPException(status_code=404, detail="항목을 찾을 수 없습니다")
        answer = rows[body.idx]
    else:
        answer, exec_block = _real_ask(body.question.strip())
    q = body.question.strip() or "브리핑해줘"
    meta = {"source": _AGENT_LABEL, "kind": "agent_exec", "agent": "edu", "exec": exec_block}
    if body.chat_id:
        chat = db.get_chat(body.chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="존재하지 않는 채팅입니다")
    else:
        title = q[:15] + ("…" if len(q) > 15 else "")
        chat = db.create_chat(title=title, scope="사내")
    db.add_message(chat["id"], "user", q)
    db.add_message(chat["id"], "assistant", answer, meta)
    return {"chat_id": chat["id"], "title": chat["title"], "answer": answer, "exec": exec_block}
