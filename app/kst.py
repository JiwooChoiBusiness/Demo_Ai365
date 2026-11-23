"""한국 시간(KST) 공통 도우미 — 앱의 모든 시각은 서버 시계의 시간대와 무관하게 KST 벽시계로 계산한다(2026-10-06 사용자 지시).

KST 는 서머타임이 없어 고정 +09:00 오프셋이 정확하고 tzdata 가 필요 없다(Windows 의 zoneinfo 는 tzdata 없이 실패).
저장 형식은 종전과 같은 naive ISO(초 단위, 오프셋 없음)이며, 그 값은 항상 KST 벽시계다. UTC 호스트(Azure 등)에서도 같다.
예약 기능(schedules.py)이 2026-09-03 에 먼저 이 방식을 썼고, 이제 앱 전체가 이 모듈을 쓴다.

Korea Standard Time helpers — every time in the app is computed on the KST wall clock regardless of the server
clock's zone (user instruction 2026-10-06). KST has no DST, so a fixed +09:00 offset is exact and needs no tzdata
(zoneinfo fails on Windows without it). Storage stays the same naive ISO (seconds, no offset) and that value is
always the KST wall clock, on a UTC host too. The scheduler (schedules.py) adopted this first on 2026-09-03; now
the whole app uses this module.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), name="KST")


def _clock() -> datetime:
    """현재 UTC 시각(테스트가 바꿔 끼우는 이음새) / current UTC time (the seam tests patch)."""
    return datetime.now(timezone.utc)


def now() -> datetime:
    """현재 KST 벽시계(naive) / current KST wall-clock time (naive)."""
    return _clock().astimezone(KST).replace(tzinfo=None)


def now_iso() -> str:
    """KST 현재 시각 ISO(초 단위, 오프셋 없음) — 저장 시각의 표준 형식 / KST now as naive ISO seconds — the stored-time format."""
    return now().isoformat(timespec="seconds")


def today() -> date:
    """KST 오늘 날짜 / today's date in KST."""
    return now().date()


def month() -> str:
    """KST 이번 달 'YYYY-MM' / the current KST month as 'YYYY-MM'."""
    return now().strftime("%Y-%m")


def from_epoch(ts: float) -> datetime:
    """epoch 초 → KST 벽시계(naive) — fromtimestamp() 대신 쓴다 / epoch seconds → KST wall clock (naive), replaces fromtimestamp()."""
    return datetime.fromtimestamp(float(ts), KST).replace(tzinfo=None)


def to_kst(dt: datetime) -> datetime:
    """임의 시각 → KST 벽시계(naive). 시간대가 있으면 변환하고, naive 는 이미 KST 로 본다.
    Any datetime → KST wall clock (naive). Aware values are converted; naive values are taken as KST already."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(KST).replace(tzinfo=None)


def aware(dt: datetime | None = None) -> datetime:
    """KST 시간대가 붙은 시각(기본 = 지금). naive 는 KST 벽시계로 본다.
    A KST-aware datetime (default = now). Naive values are taken as the KST wall clock."""
    if dt is None:
        return _clock().astimezone(KST)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def iso_offset(dt: datetime | None = None) -> str:
    """'+09:00' 이 붙은 ISO(초 단위) — 화면이 브라우저 시간대와 무관하게 읽도록 위젯 등 새 값에 쓴다.
    ISO seconds with '+09:00' — used for new values (widgets etc.) so the browser reads them zone-independently."""
    return aware(dt).isoformat(timespec="seconds")


def struct_time(secs: float | None = None) -> time.struct_time:
    """logging.Formatter.converter 용 KST struct_time / a KST struct_time for logging.Formatter.converter."""
    base = _clock() if secs is None else datetime.fromtimestamp(float(secs), timezone.utc)
    return base.astimezone(KST).timetuple()
