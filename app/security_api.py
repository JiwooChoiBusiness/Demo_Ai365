"""보안 에이전트 API(목업, 2026-09-07) — Groupware 상단 탭 → [보안 에이전트] 대시보드용.

  GET  /api/security/dashboard                    화면 전체 취합(상태 스트립·위험 로그인·점검·사용자/그룹·라이선스·사용량·테넌트)
  POST /api/security/risky-signins/{id}/dismiss   위험 로그인 무시(⛔) — 영속, 갱신된 dashboard 반환
  POST /api/security/refresh                      재수집 시뮬레이션(↻) — 무시 상태 초기화 + 갱신 시각
  GET  /api/security/summary?lang=ko|en           Dashboard Summary — 경량 LLM 생성(캐시), 실패 시 시드 요약

데모는 단일 사용자라 접근 게이트는 두지 않는다(실연동 때 슈퍼관리자/보안 담당 역할로 제한 예정).

Security Agent API (mock, 2026-09-07) — for the [Security Agent] dashboard under the top Groupware tab.
The demo is single-user, so there is no access gate yet (to be restricted to super-admin / security roles with the
real connector).
"""

from fastapi import APIRouter, HTTPException

from app import security_store

router = APIRouter(prefix="/api/security", tags=["security"])


@router.get("/dashboard")
def get_dashboard() -> dict:
    return security_store.dashboard()


@router.post("/risky-signins/{sid}/dismiss")
def dismiss_risky(sid: str) -> dict:
    if not security_store.dismiss(sid):
        raise HTTPException(status_code=404, detail="존재하지 않는 위험 로그인 기록입니다")
    return security_store.dashboard()


@router.post("/refresh")
def refresh() -> dict:
    return security_store.refresh()


@router.get("/summary")
def get_summary(lang: str = "ko") -> dict:
    return security_store.summary(lang)


@router.get("/describe")
def get_describe(target: str = "status") -> dict:
    """채팅 참조 자료 미리보기(2026-09-07) — read_security 와 같은 결정적 서술. target 은 쉼표 구분, 모르는 키는 400."""
    # Chat resource preview (2026-09-07) — the same deterministic description as read_security. Comma-separated targets; unknown → 400.
    targets = [t.strip() for t in target.split(",") if t.strip()]
    bad = [t for t in targets if t not in security_store.READ_TARGETS]
    if bad or not targets:
        raise HTTPException(status_code=400, detail="알 수 없는 보안 조회 대상입니다: " + ", ".join(bad or ["(없음)"]))
    return {"targets": targets, "labels": [security_store.READ_LABELS[t] for t in targets],
            "text": security_store.describe(targets)}
