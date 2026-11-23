"""Validated, read-only constraints for M Cosmetic work-status queries.

The store owns customer resolution and row selection. This module only normalizes the
public filter contract, so chat and MCP can share it without creating database sessions.
"""
from __future__ import annotations

from datetime import date


FIELDS = frozenset({"date_from", "date_to", "status", "customer", "q"})
MAIL_TARGETS = frozenset({"inbox", "today", "quotes", "orders", "shipments", "stock", "invoices"})
STATUSES = {
    **{target: {"all", "todo", "done", "err"} for target in MAIL_TARGETS},
    "cases": {"all", "open", "done"},
    "errors": {"all", "open", "resolved", "done"},
    "customer": {"all", "todo", "done"},
    "case": set(),
}


def normalize(target: str, value: object) -> dict[str, str]:
    """Raise ValueError for unsupported conditions instead of widening the query."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("조회 filters는 객체여야 합니다.")
    unknown = set(value) - FIELDS
    if unknown:
        raise ValueError("지원하지 않는 조회 조건입니다: " + ", ".join(sorted(str(x) for x in unknown)))
    clean = {}
    for key, raw in value.items():
        if raw in (None, ""):
            continue
        if not isinstance(raw, str):
            raise ValueError(f"조회 조건 {key}는 문자열이어야 합니다.")
        raw = raw.strip()
        if raw:
            clean[key] = raw
    if target == "case" and clean:
        raise ValueError("Case 상세 조회는 case_id로 지정합니다. 기간·상태 조건은 cases 목록 조회에서 사용해 주세요.")
    for key in ("date_from", "date_to"):
        if key not in clean:
            continue
        try:
            if date.fromisoformat(clean[key]).isoformat() != clean[key]:
                raise ValueError
        except ValueError:
            raise ValueError(f"{key} 형식은 YYYY-MM-DD 입니다.") from None
    if clean.get("date_from") and clean.get("date_to") and clean["date_from"] > clean["date_to"]:
        raise ValueError("조회 시작일은 종료일보다 늦을 수 없습니다.")
    status = clean.get("status")
    if status and status not in STATUSES.get(target, set()):
        allowed = ", ".join(sorted(STATUSES.get(target, set())))
        raise ValueError(f"{target} 조회에서 지원하는 상태는 {allowed or '없음'}입니다.")
    if target == "errors" and status == "done":
        clean["status"] = "resolved"
    return clean


def scope_label(target: str, filters: dict[str, str]) -> str:
    parts = []
    if filters.get("customer"):
        parts.append("고객사 " + filters["customer"])
    lo, hi = filters.get("date_from"), filters.get("date_to")
    if lo or hi:
        basis = {"cases": "Case 최종 수정일", "errors": "오류 발생일", "customer": "메일 수신일·Case 최종 수정일"}.get(
            target, "메일 수신일")
        parts.append(f"{basis} {lo or '제한 없음'} ~ {hi or '제한 없음'}")
    if filters.get("status"):
        names = {"all": "전체", "todo": "미완료", "done": "완료", "err": "오류", "open": "진행 중/미해결", "resolved": "해결"}
        parts.append("상태 " + names[filters["status"]])
    if filters.get("q"):
        parts.append("검색어 " + filters["q"])
    return " · ".join(parts)
