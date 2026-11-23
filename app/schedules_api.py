"""컬렉션 예약 API — 목록/생성/수정/삭제/지금 실행 (prefix /api/collections/{coll_id}/schedules).

검증은 여기서 지목(422)하고, 저장·시각 계산·실행은 app.schedules 가 담당한다. 알림은 실행 마감 후 app.notify 가 실발송
(5차) — 예약마다 notify_email(bool, 기본 True) 토글 하나: 켜져 있으면 소유자 본인에게 1통. 구 다중 알림 필드 notifies 는
폐지돼 요청에 와도 무시(pydantic extra=ignore)하고 응답에도 싣지 않는다.
2차: 리소스 선택(agents/scope_files/smf_files — 컬렉션 컴포저의 stream 바디와 같은 형태) + 반복 종료(end_at).
3차: 반복 옵션 확장 — rule once/hourly/daily/weekdays/weekly/monthly/custom + freq(custom 빈도)·interval(1~12)·mday(1~31).
PATCH 의 timing 변경은 값 비교(rule/run_at/days/end_at/freq/interval/mday 가 현재 값과 다를 때만)로 판정하고,
custom 의 간격 기준점(anchor)은 예약 created_at 이다.
2026-09-11: 워크플로우 예약(flow_id/flow_name/flow_query)·커넥터(connectors) 폐지 — 예약은 프롬프트만 실행한다(사용자 확정).
컬럼은 호환용으로 남고 API 는 받지도 돌려주지도 않는다.
"""
# Collection schedule API — list/create/patch/delete/run-now (prefix /api/collections/{coll_id}/schedules).
# Validation (422 with a pointed message) lives here; storage/time math/execution live in app.schedules.
# Notifications are really delivered by app.notify after a run closes (round 5) — one notify_email toggle per
# schedule (bool, default True): when on, one mail goes to the owner. The old multi-notify field `notifies` is
# retired: ignored when sent (pydantic extra=ignore), absent from responses.
# Round 2: resource selection (agents/scope_files/smf_files — same shape as the collection composer's stream
# body) + repeat end (end_at). Round 3: repeat options — rule once/hourly/daily/weekdays/weekly/monthly/custom
# + freq (custom frequency) · interval (1–12) · mday (1–31). A PATCH counts as a timing change only when
# rule/run_at/days/end_at/freq/interval/mday differ from the stored values; the custom interval anchor is the
# schedule's created_at. 2026-09-11: workflow schedules (flow_id/flow_name/flow_query) and connectors are retired —
# schedules run prompts only (user decision); the columns remain for compatibility, the API neither accepts nor returns them.

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import collections_store, schedules

logger = logging.getLogger("ai365.scheduler")

router = APIRouter(prefix="/api/collections")


class SchedCreate(BaseModel):
    name: str = ""
    message: str
    scope: str = "자동"
    rule: str
    run_at: str
    days: list[int] = []
    # 반복 종료 'YYYY-MM-DD' | None — once 외 모든 반복 규칙에 적용(once 는 무시)
    # Repeat end 'YYYY-MM-DD' | None — every repeating rule (ignored for once)
    end_at: str | None = None
    # 반복 옵션(3차) — freq/interval 은 rule=custom 에만, mday 는 monthly·custom-monthly 에만 쓰인다(그 외 무시)
    # Repeat options (round 3) — freq/interval only for rule=custom, mday only for monthly / custom-monthly (ignored otherwise)
    freq: str = ""
    interval: int = 1
    mday: int | None = None
    enabled: bool = True
    # "메일로 알림 보내기" 토글 — 켜져 있으면 실행 마감 후 소유자 본인에게 메일 1통(구 notifies 목록은 폐지·무시)
    # "Email me when it runs" toggle — one mail to the owner after a run (the old `notifies` list is retired / ignored)
    notify_email: bool = True
    # 리소스 선택 — 컴포저가 /api/chats/{id}/stream 바디로 보내는 agents/scope_files 와 같은 형태. 비면 자동 라우팅·전체 범위.
    # smf_files 는 스마트 파일 트리 체크 복원용 키 목록(실행에는 쓰지 않음).
    # Resource selection — same shape as the composer's stream-body agents/scope_files. Empty = auto routing / full scope.
    # smf_files = smart-file tree keys for restoring checks on edit (not used at run time).
    agents: list[str] = []
    scope_files: dict = {}
    smf_files: list[str] = []
    # (워크플로우 예약·커넥터 필드는 2026-09-11 폐지 — 예약은 프롬프트만 실행한다. 보내와도 무시된다(extra=ignore).)
    # (Workflow-schedule and connector fields were retired 2026-09-11 — schedules run prompts only; ignored when sent.)
    # 뷰애즈 신원 — 예약 소유자(''=슈퍼관리자). 실행 시 파이프라인 권한 게이팅에도 그대로 쓰인다.
    # View-as identity — the schedule owner ('' = super admin); reused for pipeline gating at run time.
    acting_user_id: str = ""


class SchedPatch(BaseModel):
    name: str | None = None
    message: str | None = None
    # 컬렉션 묶음 변경(6차) — ''/None 은 컬렉션 없는 예약으로 / collection binding change (round 6) — ''/None = collection-less
    coll_id: str | None = None
    scope: str | None = None
    rule: str | None = None
    run_at: str | None = None
    days: list[int] | None = None
    end_at: str | None = None
    freq: str | None = None
    interval: int | None = None
    mday: int | None = None
    status: str | None = None
    notify_email: bool | None = None
    agents: list[str] | None = None
    scope_files: dict | None = None
    smf_files: list[str] | None = None


def _coll_or_404(coll_id: str) -> None:
    # 경량 존재 확인(SELECT 1) — 파일 본문·예약까지 읽는 get_collection 을 쓰지 않는다
    # Lightweight existence check (SELECT 1) — avoids get_collection, which loads file bodies and schedules
    if not collections_store.exists_collection(coll_id):
        raise HTTPException(status_code=404, detail="존재하지 않는 컬렉션입니다")


def _sched_or_404(coll_id: str | None, sid: str) -> dict:
    """coll_id 가 None 이면(전역 /api/schedules 라우터) 컬렉션 일치 검사를 생략한다 / None (global router) skips the collection match"""
    s = schedules.get(sid)
    if s is None or (coll_id is not None and s["coll_id"] != coll_id):
        raise HTTPException(status_code=404, detail="존재하지 않는 예약입니다")
    return s


def _check_message(message: str) -> str:
    # 예약은 프롬프트만 실행한다(2026-09-11 워크플로우 예약 폐지) — 프롬프트 필수 / schedules run prompts only — required
    m = (message or "").strip()
    if not m:
        raise HTTPException(status_code=422, detail="프롬프트를 입력하세요.")
    if len(m) > schedules.MAX_MESSAGE:
        raise HTTPException(status_code=422, detail=f"프롬프트는 {schedules.MAX_MESSAGE}자 이내여야 합니다")
    return m


def _check_scope(scope: str) -> str:
    if scope not in schedules.SCOPES:
        raise HTTPException(status_code=422, detail="검색 범위는 자동/사내/외부 중 하나여야 합니다")
    return scope


class Timing:
    """검증·정규화된 반복 설정 — rule/run_at/days/end_at/freq/interval/mday. 저장·비교·next_run 계산에 그대로 쓴다."""
    # Validated, normalized repeat settings — rule/run_at/days/end_at/freq/interval/mday; used as-is for storage,
    # comparison and next_run computation.
    __slots__ = ("rule", "run_at", "days", "end_at", "freq", "interval", "mday")

    def __init__(self, rule: str, run_at: str, days: list[int], end_at: str | None, freq: str, interval: int,
                 mday: int | None):
        self.rule, self.run_at, self.days, self.end_at = rule, run_at, days, end_at
        self.freq, self.interval, self.mday = freq, interval, mday

    def as_patch(self) -> dict:
        return {"rule": self.rule, "run_at": self.run_at, "days": self.days, "end_at": self.end_at,
                "freq": self.freq, "interval": self.interval, "mday": self.mday}

    def differs_from(self, cur: dict) -> bool:
        return (self.rule != cur["rule"] or self.run_at != cur["run_at"]
                or self.days != list(cur.get("days") or []) or self.end_at != (cur.get("end_at") or None)
                or self.freq != (cur.get("freq") or "") or self.interval != int(cur.get("interval") or 1)
                or self.mday != (cur.get("mday") if cur.get("mday") is not None else None))


def _check_days(days: list[int] | None, label: str) -> list[int]:
    raw = days or []
    if not raw:
        raise HTTPException(status_code=422, detail=f"{label} 반복은 요일을 하나 이상 골라야 합니다")
    if any((not isinstance(d, int)) or isinstance(d, bool) or d < 0 or d > 6 for d in raw):
        raise HTTPException(status_code=422, detail="요일 값은 0(월)~6(일) 사이여야 합니다")
    return sorted(set(raw))


def _check_timing(rule: str, run_at: str, days: list[int] | None, end_at: str | None,
                  freq: str | None = "", interval: int | None = 1, mday: int | None = None) -> Timing:
    """rule/run_at/days/end_at/freq/interval/mday 형식 검증만(다음 실행 시각 계산은 호출자).
    once → days=[]·end_at=None. weekdays → days=[0..4] 고정. weekly/custom-weekly → days 필수(0~6).
    monthly/custom-monthly → mday 필수(1~31). custom → freq 필수(daily/weekly/monthly)·interval 1~12.
    hourly 는 days/mday 를 무시. freq/interval 은 custom 외에서 ''/1, mday 는 monthly 계열 외에서 None 으로 정규화."""
    # Validate rule/run_at/days/end_at/freq/interval/mday formats only (the caller computes next_run_at).
    # once → days=[] and end_at=None. weekdays → days fixed to [0..4]. weekly / custom-weekly → days required (0–6).
    # monthly / custom-monthly → mday required (1–31). custom → freq required (daily/weekly/monthly), interval 1–12.
    # hourly ignores days/mday. freq/interval normalize to ''/1 outside custom, mday to None outside the monthly family.
    if rule not in schedules.RULES:
        raise HTTPException(status_code=422, detail="반복은 once/hourly/daily/weekdays/weekly/monthly/custom 중 하나여야 합니다")
    run_at = (run_at or "").strip()
    try:
        schedules.parse_run_at(rule, run_at)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    freq_v = ""
    interval_v = 1
    if rule == "custom":
        freq_v = (freq or "").strip()
        if freq_v not in schedules.FREQS:
            raise HTTPException(status_code=422, detail="사용자 지정 반복은 빈도(daily/weekly/monthly)를 골라야 합니다")
        iv = 1 if interval is None else interval
        if isinstance(iv, bool) or not isinstance(iv, int) or iv < 1 or iv > schedules.MAX_INTERVAL:
            raise HTTPException(status_code=422, detail=f"간격은 1~{schedules.MAX_INTERVAL} 사이여야 합니다")
        interval_v = iv
    days_l: list[int] = []
    if rule == "weekly":
        days_l = _check_days(days, "매주")
    elif rule == "custom" and freq_v == "weekly":
        days_l = _check_days(days, "사용자 지정(주)")
    elif rule == "weekdays":
        days_l = list(schedules.WEEKDAYS)
    mday_v: int | None = None
    if rule == "monthly" or (rule == "custom" and freq_v == "monthly"):
        if mday is None or isinstance(mday, bool) or not isinstance(mday, int) or mday < 1 or mday > 31:
            raise HTTPException(status_code=422, detail="매월 반복은 날짜(일)를 1~31 사이로 골라야 합니다")
        mday_v = mday
    end_v: str | None = None
    if rule != "once":
        end_v = (end_at or "").strip() or None
        if end_v is not None:
            try:
                schedules.parse_end_at(end_v)
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e)) from None
    return Timing(rule, run_at, days_l, end_v, freq_v, interval_v, mday_v)


def _next_run(t: Timing, anchor=None) -> str | None:
    """Timing → 다음 실행 시각. anchor 는 custom 간격 기준일(생성 시 None=오늘, 수정 시 cur.created_at)."""
    # Timing → next run time. anchor = custom interval base date (None = today on create; cur.created_at on patch).
    try:
        return schedules.compute_next_run(t.rule, t.run_at, t.days, end_at=t.end_at, freq=t.freq,
                                          interval=t.interval, mday=t.mday, anchor=anchor)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None


def _check_agents(agents: list[str] | None) -> list[str]:
    items = agents or []
    if not isinstance(items, list) or any(not isinstance(a, str) for a in items):
        raise HTTPException(status_code=422, detail="분야 목록 형식이 올바르지 않습니다")
    bad = [a for a in items if a not in schedules.AGENT_KEYS]
    if bad:
        raise HTTPException(status_code=422, detail="분야 키는 knowledge/data/work 중에서만 고를 수 있습니다")
    return schedules.norm_agents(items)


def _check_scope_files(sf: dict | None) -> dict:
    """키 화이트리스트(knowledge_files/data_tables/data_bi: 문자열 리스트, work: bool) + 값 타입·상한 검사."""
    # Key whitelist (knowledge_files/data_tables/data_bi: string lists, work: bool) + value type / cap checks.
    sf = sf or {}
    if not isinstance(sf, dict):
        raise HTTPException(status_code=422, detail="scope_files 형식이 올바르지 않습니다")
    allowed = set(schedules.SCOPE_FILE_LISTS) | {"work"}
    extra = [k for k in sf if k not in allowed]
    if extra:
        raise HTTPException(status_code=422, detail="scope_files 에 허용되지 않는 키가 있습니다: " + ", ".join(sorted(map(str, extra)))[:100])
    for k in schedules.SCOPE_FILE_LISTS:
        v = sf.get(k, [])
        if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
            raise HTTPException(status_code=422, detail=f"scope_files.{k} 는 문자열 목록이어야 합니다")
        if len(v) > schedules.MAX_FILE_KEYS:
            raise HTTPException(status_code=422, detail=f"scope_files.{k} 는 {schedules.MAX_FILE_KEYS}개 이내여야 합니다")
    if "work" in sf and not isinstance(sf["work"], bool):
        raise HTTPException(status_code=422, detail="scope_files.work 는 true/false 여야 합니다")
    return schedules.norm_scope_files(sf)


def _check_smf_files(keys: list[str] | None) -> list[str]:
    items = keys or []
    if not isinstance(items, list) or any(not isinstance(k, str) for k in items):
        raise HTTPException(status_code=422, detail="smf_files 는 문자열 목록이어야 합니다")
    if len(items) > schedules.MAX_FILE_KEYS:
        raise HTTPException(status_code=422, detail=f"smf_files 는 {schedules.MAX_FILE_KEYS}개 이내여야 합니다")
    return schedules.norm_smf_files(items)


@router.get("/{coll_id}/schedules")
def list_schedules(coll_id: str) -> list[dict]:
    _coll_or_404(coll_id)
    return schedules.list_for_coll(coll_id)


@router.post("/{coll_id}/schedules")
def create_schedule(coll_id: str, body: SchedCreate) -> dict:
    _coll_or_404(coll_id)
    return _create(coll_id, body)


def _create(coll_id: str | None, body: SchedCreate) -> dict:
    """생성 공통(컬렉션 라우터·전역 라우터) — coll_id None 은 컬렉션 없는 예약(6차, 상한 MAX_GLOBAL)"""
    # Shared create (collection + global routers) — coll_id None = collection-less schedule (round 6, cap MAX_GLOBAL)
    message = _check_message(body.message)
    scope = _check_scope(body.scope)
    t = _check_timing(body.rule, body.run_at, body.days, body.end_at, body.freq, body.interval, body.mday)
    next_run = _next_run(t)   # 생성 시 anchor=None(오늘) = created_at 날짜 / anchor None (today) = the created_at date
    # 회차가 하나도 없으면 저장하지 않는다 — once 는 과거 시각, 반복 규칙은 end_at 초과. 계산한 next_run 은 create 에
    # 그대로 넘겨 재계산하지 않는다(분 경계 레이스 방지).
    # Nothing to run → do not save — a past once, or a repeating rule past end_at. The computed next_run is handed to
    # create as-is (no recomputation → no minute-boundary race).
    if next_run is None:
        raise HTTPException(status_code=422, detail=_no_run_detail(t.rule))
    agents = _check_agents(body.agents)
    scope_files = _check_scope_files(body.scope_files)
    smf_files = _check_smf_files(body.smf_files)
    # 상한은 done 을 제외하고 센다 / the cap excludes done schedules
    if coll_id and schedules.count_for_coll(coll_id) >= schedules.MAX_PER_COLL:
        raise HTTPException(status_code=422, detail=f"컬렉션당 예약은 {schedules.MAX_PER_COLL}개까지 등록할 수 있습니다")
    if not coll_id and schedules.count_global() >= schedules.MAX_GLOBAL:
        raise HTTPException(status_code=422, detail=f"예약은 {schedules.MAX_GLOBAL}개까지 등록할 수 있습니다")
    return schedules.create(coll_id, body.acting_user_id, body.name, message, scope, t.rule, t.run_at, t.days,
                            body.enabled, bool(body.notify_email), agents=agents, scope_files=scope_files,
                            smf_files=smf_files, end_at=t.end_at, freq=t.freq, interval=t.interval, mday=t.mday,
                            next_run=next_run)


def _no_run_detail(rule: str) -> str:
    """next_run 이 None 일 때의 422 문구 — once 는 과거 시각, 반복 규칙은 반복 종료 초과."""
    # 422 message when next_run is None — a past once vs. a repeating rule past the repeat end.
    return "예약 시각이 지났습니다" if rule == "once" else "반복 종료 날짜가 지났습니다"


def _plan_patch(cur: dict, raw: dict) -> dict:
    """PATCH 본문 → 저장 patch. 순수 함수(검증은 HTTPException) — 단위 확인용으로 분리.

    - timing_changed = rule/run_at/days/end_at/freq/interval/mday 의 **결과값**이 현재 저장값과 다를 때만. 같으면 timing
      키를 patch 에서 뺀다.
    - running 중 timing 이 실제로 바뀌면 422. status 변경은 running 중 항상 422.
    - next_run_at 재계산 = timing_changed 또는 재개(status=active). custom 의 anchor 는 cur.created_at. once 가 과거면
      결과 status 가 active 일 때만 422 "예약 시각이 지났습니다". 반복 규칙의 next 가 None(end_at 초과)이면 항상 422
      "반복 종료 날짜가 지났습니다"(done 재개 포함 — next 가 None 인 채 active 로 저장되는 경로 없음).
    - 재계산 경로에서는 결과 status/prior_status 를 항상 patch 에 반영한다.
    - 완료(done)된 예약의 timing 을 새로 잡으면(명시 status 없음) active 로 되살린다.
    """
    # PATCH body → stored patch. Pure (validation raises HTTPException) — split out for unit checks.
    # - timing_changed only when the RESULTING rule/run_at/days/end_at/freq/interval/mday differ from the stored
    #   values; otherwise the timing keys are dropped from the patch.
    # - An actual timing change while running → 422. A status change while running → always 422.
    # - next_run_at is recomputed on a timing change or a resume (status=active); the custom anchor is
    #   cur.created_at. A past once → 422 only when the resulting status would be active. A repeating rule's next
    #   None (past end_at) → always 422 "repeat end has passed" (including a resume of a done row — no path stores
    #   active with next None).
    # - On the recompute path the resulting status/prior_status are always written into the patch.
    # - Re-timing a done schedule (no explicit status) revives it as active.
    patch: dict = {}
    if "name" in raw:
        patch["name"] = (raw["name"] or "").strip()
    if "message" in raw:
        patch["message"] = _check_message(raw["message"])
    if "coll_id" in raw:
        cid = (raw["coll_id"] or "").strip() or None
        if cid and not collections_store.exists_collection(cid):
            raise HTTPException(status_code=404, detail="존재하지 않는 컬렉션입니다")
        patch["coll_id"] = cid
    if "scope" in raw:
        patch["scope"] = _check_scope(raw["scope"])
    if "agents" in raw:
        patch["agents"] = _check_agents(raw["agents"])
    if "scope_files" in raw:
        patch["scope_files"] = _check_scope_files(raw["scope_files"])
    if "smf_files" in raw:
        patch["smf_files"] = _check_smf_files(raw["smf_files"])
    if raw.get("notify_email") is not None:
        # 메일 알림 토글 — running 중에도 변경 허용(마감 시점의 저장값으로 발송 여부 판정); null 은 미지정으로 취급
        # Toggle allowed while running (the stored value at close time decides); null counts as "not sent"
        patch["notify_email"] = bool(raw["notify_email"])

    # 실행 중에는 상태 전환을 받지 않는다(리스·prior_status 꼬임 방지) — 이름/프롬프트/알림 토글/리소스 수정은 허용
    # No status change while running (would corrupt the lease/prior_status) — name/prompt/notify toggle/resource edits are fine
    if "status" in raw and cur["status"] == "running":
        raise HTTPException(status_code=422, detail="실행 중에는 변경할 수 없습니다")
    if "status" in raw and raw["status"] not in ("active", "paused"):
        raise HTTPException(status_code=422, detail="상태는 active/paused 중 하나여야 합니다")

    timing_keys = ("rule", "run_at", "days", "end_at", "freq", "interval", "mday")
    rule = raw["rule"] if "rule" in raw else cur["rule"]
    run_at = raw["run_at"] if "run_at" in raw else cur["run_at"]
    days = raw["days"] if "days" in raw else cur["days"]
    end_at = raw["end_at"] if "end_at" in raw else cur.get("end_at")
    freq = raw["freq"] if "freq" in raw else cur.get("freq") or ""
    interval = raw["interval"] if "interval" in raw else cur.get("interval") or 1
    mday = raw["mday"] if "mday" in raw else cur.get("mday")
    timing_changed = False
    # 현재 저장값 그대로의 Timing(재개 시 재계산용) — 검증 없이 조립 / Timing of the stored values (for a resume recompute) — assembled without validation
    t = Timing(cur["rule"], cur["run_at"], list(cur.get("days") or []), cur.get("end_at") or None,
               cur.get("freq") or "", int(cur.get("interval") or 1), cur.get("mday"))
    if any(k in raw for k in timing_keys):
        t = _check_timing(rule, run_at, days, end_at, freq, interval, mday)
        timing_changed = t.differs_from(cur)
    rule = t.rule
    if timing_changed and cur["status"] == "running":
        raise HTTPException(status_code=422, detail="실행 중에는 변경할 수 없습니다")

    resume = raw.get("status") == "active"
    if "status" in raw:
        result_status = raw["status"]
    elif timing_changed and cur["status"] == "done":
        result_status = "active"   # 완료 예약의 재예약 → 되살림 / re-timing a done one revives it
    else:
        result_status = cur["status"]

    if "status" in raw:
        patch["status"] = raw["status"]
        patch["prior_status"] = raw["status"]

    if timing_changed or resume:
        next_run = _next_run(t, anchor=cur.get("created_at"))
        if next_run is None:
            # once 는 결과 status 가 active 일 때만(paused 로 두는 과거 once 는 허용), 반복 규칙은 end_at 초과면 항상 422
            # — next 가 None 인 채 active 로 저장되는 경로를 없앤다(done 재개 포함).
            # A once → 422 only when the result would be active (a past once left paused is allowed); a repeating rule
            # past end_at → always 422 — no path stores active with next None (a resume of a done row included).
            if rule != "once" or result_status == "active":
                raise HTTPException(status_code=422, detail=_no_run_detail(rule))
        patch.update(t.as_patch())
        patch["next_run_at"] = next_run
        # 재계산 경로는 결과 status 를 항상 반영(여기서 result_status 는 active/paused 뿐 — running/done 은 위에서 걸러짐)
        # The recompute path always writes the resulting status (only active/paused reach here — running/done were filtered above)
        patch["status"] = result_status
        patch["prior_status"] = result_status
    return patch


@router.patch("/{coll_id}/schedules/{sid}")
def patch_schedule(coll_id: str, sid: str, body: SchedPatch) -> dict:
    _coll_or_404(coll_id)
    cur = _sched_or_404(coll_id, sid)
    raw = body.model_dump(exclude_unset=True)
    patch = _plan_patch(cur, raw)
    out = schedules.update(sid, patch)
    if out is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 예약입니다")
    return out


@router.delete("/{coll_id}/schedules/{sid}")
async def delete_schedule(coll_id: str, sid: str) -> dict:
    _coll_or_404(coll_id)
    _sched_or_404(coll_id, sid)
    if not await schedules.delete_with_runs(sid):
        raise HTTPException(status_code=404, detail="존재하지 않는 예약입니다")
    logger.info("예약 삭제: %s", sid)
    return {"ok": True}


def _validate_and_claim_run(coll_id: str | None, sid: str) -> None:
    """지금 실행의 동기 검증 + claim(force) — 스레드에서 실행(이벤트 루프의 SQLite 블로킹 회피). 실패는 HTTPException."""
    # Synchronous validation + claim(force) for run-now — executed on a thread (keeps SQLite off the event loop). Failures raise HTTPException.
    if coll_id is not None:
        _coll_or_404(coll_id)
    cur = _sched_or_404(coll_id, sid)
    if cur["status"] == "running":
        raise HTTPException(status_code=409, detail="이미 실행 중입니다")
    if cur["status"] not in ("active", "paused"):
        raise HTTPException(status_code=422, detail="완료된 예약은 실행할 수 없습니다")
    if not schedules.claim(sid, force=True):
        # 경합(다른 틱이 방금 선점) — 실행 중 처리 / race with a tick that just claimed it → treat as running
        raise HTTPException(status_code=409, detail="이미 실행 중입니다")


@router.post("/{coll_id}/schedules/{sid}/run")
async def run_schedule(coll_id: str, sid: str) -> dict:
    """지금 실행 — 검증·claim(force) 을 스레드에서 끝낸 뒤 백그라운드 태스크로 fire. paused 면 1회 실행 후 paused 로 복귀
    (prior_status). done(완료) 은 422 유지(프론트가 버튼을 숨긴다). once 는 예정 회차를 소진하지 않는다(next_run_at 유지)."""
    # Run now — validation + claim(force) on a thread, then fire on a background task. A paused schedule runs once and
    # returns to paused. done stays 422 (the front end hides the button). A once keeps its pending occurrence (next_run_at).
    await asyncio.to_thread(_validate_and_claim_run, coll_id, sid)
    schedules.run_now(sid)
    return {"ok": True, "status": "running"}


# ─────────────────────────────────────────────────────────────────────────────
# 전역 라우터(6차, 2026-09-07) — 사이드바 '예약' 메뉴의 예약 작업 페이지. 컬렉션과 무관하게 전체 예약을 다룬다.
#   GET  /api/schedules?status=all|active      전체 목록(컬렉션 이름 포함, 최근 생성 순)
#   POST /api/schedules                        생성 — coll_id 선택(없으면 컬렉션 없는 예약, 일반 채팅으로 실행)
#   PATCH/DELETE /api/schedules/{sid}          수정·삭제(컬렉션 라우터와 같은 검증)
#   POST /api/schedules/{sid}/run              지금 실행
#   GET  /api/schedules/{sid}/runs             실행 히스토리(예약이 만든 결과 채팅, 최근 30개)
# Global router (round 6, 2026-09-07) — the sidebar 'Schedules' page; handles every schedule regardless of collection.
# ─────────────────────────────────────────────────────────────────────────────
router_global = APIRouter(prefix="/api/schedules", tags=["schedules"])


class SchedCreateGlobal(SchedCreate):
    coll_id: str | None = None


@router_global.get("")
def list_all_schedules(status: str = "all") -> list[dict]:
    return schedules.list_all(active_only=(status == "active"))


@router_global.post("")
def create_global(body: SchedCreateGlobal) -> dict:
    coll_id = (body.coll_id or "").strip() or None
    if coll_id:
        _coll_or_404(coll_id)
    return _create(coll_id, body)


@router_global.get("/{sid}")
def get_global(sid: str) -> dict:
    return _sched_or_404(None, sid)


@router_global.patch("/{sid}")
def patch_global(sid: str, body: SchedPatch) -> dict:
    cur = _sched_or_404(None, sid)
    patch = _plan_patch(cur, body.model_dump(exclude_unset=True))
    out = schedules.update(sid, patch)
    if out is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 예약입니다")
    return out


@router_global.delete("/{sid}")
async def delete_global(sid: str) -> dict:
    _sched_or_404(None, sid)
    if not await schedules.delete_with_runs(sid):
        raise HTTPException(status_code=404, detail="존재하지 않는 예약입니다")
    logger.info("예약 삭제: %s", sid)
    return {"ok": True}


@router_global.post("/{sid}/run")
async def run_global(sid: str) -> dict:
    await asyncio.to_thread(_validate_and_claim_run, None, sid)
    schedules.run_now(sid)
    return {"ok": True, "status": "running"}


@router_global.get("/{sid}/runs")
def runs_global(sid: str) -> list[dict]:
    _sched_or_404(None, sid)
    return schedules.run_history(sid)
