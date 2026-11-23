"""자연어 예약(2026-09-07) — 채팅 문장에서 예약을 만들고 확인 답변을 낸다.

사용자가 어떤 채팅(일반·컬렉션·예약 작업 페이지 입력창)에서든 "gpt 업데이트 내용을 주마다 보고해줘"처럼 반복/시점
실행을 요청하면 파이프라인이 이 모듈로 가로챈다(pipeline.run_pipeline, 문서 생성 가로채기보다 앞):
  1) looks_like — 반복·시점 어휘 + 요청 어휘가 함께 있을 때만(또는 '예약해' 같은 명시어) LLM 추출을 부른다(오탐·비용 방지).
  2) parse — 경량 모델(json_mode)이 {is_schedule, name, prompt, rule, time, days, mday, date, points} 를 뽑는다.
     시각이 없으면 기본값(매주=월요일 09:00, 매일/평일=09:00, 매월=1일 09:00, 매시간=정각) — 사용자 확정 2026-09-07.
  3) create_from_spec — 즉시 생성(확인 카드 없음, 사용자 확정). 컬렉션 채팅이면 그 컬렉션에, 아니면 컬렉션 없이(coll_id NULL).
  4) confirm_events — "설정했습니다 👍 …" 확인 답변(사진 시안) + 하단 예약 칩 이벤트(type='schedule') + done.
     답변 메시지 meta = {kind:'schedule', sched:{id,name,label,rule_label,next_run_at}} → 새로고침 복원에서 칩을 다시 그린다.

Natural-language schedules (2026-09-07) — create a schedule from a chat sentence and answer with a confirmation.
Intercepted by run_pipeline (before the docgen interception): looks_like (deterministic vocabulary gate) → parse
(lite model, json_mode; defaults when no time is given) → create_from_spec (created immediately; bound to the chat's
collection when there is one, otherwise collection-less) → confirm_events (confirmation text + a `schedule` chip event
+ done; the saved message meta carries the chip for restore).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

from app import db, llm, schedules

logger = logging.getLogger("ai365.schedules_nl")

__all__ = ["looks_like", "parse", "create_from_spec", "confirm_events", "chip_of", "rule_label", "local_chosen",
           "local_blocked_text"]

# ── 결정적 선별 / deterministic gate ──
_RX_REPEAT = re.compile(
    r"(매일|매주|매월|매달|매시간|매년|주마다|달마다|날마다|시간마다|평일|주말|월요일|화요일|수요일|목요일|금요일|토요일|일요일"
    r"|정기적|아침마다|저녁마다|매\s*\d+\s*(?:일|주|시간|분)|\d+\s*(?:일|주|시간)\s*마다"
    r"|(?:오늘|내일|모레)\s*(?:오전|오후)?\s*\d{1,2}\s*시|\d{1,2}\s*시(?:\s*\d{1,2}\s*분)?\s*(?:에|마다))"
)
_RX_ASK = re.compile(r"(알려|보고|보내|정리|요약|모니터링|업데이트|알림|확인해|체크|수집|리마인드|remind|예약|스케줄|schedule|점검)")
_RX_EXPLICIT = re.compile(r"(예약해|예약 걸|예약으로|스케줄 걸|스케줄해|리마인더|reminder)", re.IGNORECASE)
_RX_HM = re.compile(r"^\d{2}:\d{2}$")
_RX_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_DAY_NAMES = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
_DAY_SHORT = ["월", "화", "수", "목", "금", "토", "일"]
_RULES_NL = ("once", "hourly", "daily", "weekdays", "weekly", "monthly")
MAX_POINTS = 6


def looks_like(message: str) -> bool:
    """LLM 추출을 부를 만한 문장인가 — 명시어가 있거나, 반복/시점 어휘와 요청 어휘가 함께 있을 때"""
    # Worth an LLM extraction — an explicit word, or repeat/time vocabulary together with a request word
    m = (message or "").strip()
    if not m or len(m) > 500:
        return False
    if _RX_EXPLICIT.search(m):
        return True
    return bool(_RX_REPEAT.search(m) and _RX_ASK.search(m))


_SYSTEM = """너는 예약(스케줄) 추출기다. 사용자 문장이 "정해진 시각에 / 반복해서 어떤 작업을 실행해 달라"는 예약 요청인지 판단하고, 맞으면 예약 항목을 JSON 으로 만든다.
출력은 JSON 객체 하나:
{"is_schedule": true|false, "name": "예약 이름(20자 이내, 핵심 주제)", "prompt": "실행 때 AI 에게 보낼 한 번 실행용 질문/작업 지시(반복·시각 표현은 뺀다)", "rule": "once|hourly|daily|weekdays|weekly|monthly", "time": "HH:MM", "days": [요일 번호 0~6, 0=월요일], "mday": 1~31 또는 null, "date": "YYYY-MM-DD" 또는 null, "points": ["매번 다룰 내용 3~6개"]}
규칙:
- 지금 한 번 해 달라는 요청("이번 주 보고서 만들어줘", "지금 알려줘"), 일반 질문, 단순 조회는 is_schedule=false 로 두고 나머지는 비워도 된다.
- 주마다/매주=weekly, 매일=daily, 평일=weekdays, 매월/매달=monthly, 매시간=hourly, 특정 날짜에 한 번=once(date 필수). 요일만 말하면("월요일마다") weekly.
- 시각이 없으면 weekly→월요일 09:00, daily/weekdays→09:00, monthly→1일 09:00, hourly→분 00, once→09:00 을 쓴다. 요일이 없는 weekly 는 [0].
- 오전/오후·저녁·아침을 24시간제로 바꾼다("저녁 9시"→"21:00", "아침"→"09:00").
- prompt 는 실행 때 그대로 보낼 완전한 문장으로 쓴다(예: "GPT/OpenAI 관련 최신 업데이트를 정리해서 보고해줘").
- points 는 이 작업이 매번 다룰 내용을 주제에서 추론해 3~6개, 각 25자 이내.
- 오늘은 {today}(한국시간, {weekday}). 다른 설명 없이 JSON 만 출력한다."""


def _defaults_for(rule: str) -> tuple[str, list[int], int | None]:
    """규칙별 기본 시각·요일·일 / per-rule default time, days, mday"""
    if rule == "hourly":
        return "00:00", [], None
    if rule == "weekly":
        return "09:00", [0], None
    if rule == "monthly":
        return "09:00", [], 1
    return "09:00", [], None


def parse(message: str, force: bool = False) -> dict | None:
    """경량 모델 추출 → 정규화된 spec | None. force=True(예약 작업 페이지 입력)면 is_schedule=false 여도 예약으로 만든다
    (규칙을 못 잡으면 daily 09:00). / lite-model extraction → normalized spec | None; force treats the text as a schedule anyway."""
    m = (message or "").strip()
    if not m:
        return None
    now = schedules.now_kst()
    system = _SYSTEM.replace("{today}", now.strftime("%Y-%m-%d")).replace("{weekday}", _DAY_NAMES[now.weekday()])
    try:
        res = llm.generate(m, system=system, json_mode=True, tier="lite")
    except Exception:  # noqa: BLE001 — 추출 실패는 일반 파이프라인으로 / extraction failure → normal pipeline
        logger.warning("자연어 예약 추출 실패", exc_info=True)
        if not force:
            return None
        res = {}
    if isinstance(res, str):
        try:
            res = json.loads(res.strip().strip("`").removeprefix("json"))
        except ValueError:
            res = {}
    if not isinstance(res, dict):
        res = {}
    if not force and not res.get("is_schedule"):
        return None
    return _normalize(res, m, now)


def _normalize(res: dict, message: str, now: datetime) -> dict:
    rule = str(res.get("rule") or "").strip().lower()
    if rule not in _RULES_NL:
        rule = "daily"
    def_time, def_days, def_mday = _defaults_for(rule)
    time_s = str(res.get("time") or "").strip()
    if not _RX_HM.match(time_s):
        time_s = def_time
    hh, mm = time_s.split(":")
    if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
        time_s = def_time
    days = [d for d in (res.get("days") or []) if isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6]
    days = sorted(set(days)) or def_days
    mday = res.get("mday")
    if not (isinstance(mday, int) and not isinstance(mday, bool) and 1 <= mday <= 31):
        mday = def_mday
    run_at = time_s
    if rule == "once":
        date_s = str(res.get("date") or "").strip()
        if not _RX_DATE.match(date_s):
            date_s = now.strftime("%Y-%m-%d")
        now_naive = now.replace(tzinfo=None)
        try:
            when = datetime.strptime(f"{date_s}T{time_s}", "%Y-%m-%dT%H:%M")
        except ValueError:
            when = now_naive.replace(second=0, microsecond=0)
        if when <= now_naive:
            # 지난 시각의 한 번 실행 → 오늘 같은 시각, 그것도 지났으면 내일 / a past once → today at that time, else tomorrow
            when = now_naive.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            if when <= now_naive:
                when = when + timedelta(days=1)
        run_at = when.strftime("%Y-%m-%dT%H:%M")
    prompt = str(res.get("prompt") or "").strip() or message
    name = str(res.get("name") or "").strip()[:schedules.TITLE_CAP] or prompt[:schedules.TITLE_CAP]
    points = [str(p).strip() for p in (res.get("points") or []) if str(p).strip()][:MAX_POINTS]
    return {"name": name, "prompt": prompt[:schedules.MAX_MESSAGE], "rule": rule, "run_at": run_at,
            "days": days if rule == "weekly" else [], "mday": mday if rule == "monthly" else None, "points": points}


def create_from_spec(spec: dict, chat: dict, owner: str, scope: str, agents: list | None,
                     scope_files: dict | None) -> dict | None:
    """spec → 예약 생성(즉시). 컬렉션 채팅이면 그 컬렉션에 묶는다. 상한 초과·회차 없음·로컬 지식 에이전트 선택이면 None."""
    # spec → create the schedule now; bound to the chat's collection when there is one. None when capped, without an
    # occurrence, or with a local knowledge agent choice.
    if local_chosen(scope_files):
        # 예약은 local_agents 를 저장하지 않아 실행 때 Public 전체 · 모든 로컬로 넓어진다 — 만들지 않는다(confirm_events 가 안내)
        # Schedules never store local_agents, so the run would widen to all of Public and every local agent: not created
        logger.info("자연어 예약 생략: 로컬 지식 에이전트 선택")
        return None
    coll_id = (chat.get("coll") or "").strip() or None
    if coll_id and schedules.count_for_coll(coll_id) >= schedules.MAX_PER_COLL:
        return None
    if not coll_id and schedules.count_global() >= schedules.MAX_GLOBAL:
        return None
    scope_v = scope if scope in schedules.SCOPES else "자동"
    try:
        return schedules.create(coll_id, owner or "", spec["name"], spec["prompt"], scope_v, spec["rule"], spec["run_at"],
                                spec["days"], True, True, agents=agents or [], scope_files=scope_files or {},
                                mday=spec.get("mday"))
    except ValueError:
        logger.warning("자연어 예약 생성 실패(시각 계산): %s", spec, exc_info=True)
        return None


def _ampm(hm: str) -> str:
    h, m = hm.split(":")
    h, m = int(h), int(m)
    part = "오전" if h < 12 else "오후"
    h12 = h if 1 <= h <= 12 else (h - 12 if h > 12 else 12)
    return f"{part} {h12}시" + (f" {m}분" if m else "")


def rule_label(s: dict) -> str:
    """사람이 읽는 반복 설명 — '매주 월요일 오전 9시' 등 / human-readable repeat description"""
    rule, run_at, days = s.get("rule"), s.get("run_at") or "", s.get("days") or []
    if rule == "once":
        try:
            when = datetime.strptime(run_at, "%Y-%m-%dT%H:%M")
            return f"{when.month}월 {when.day}일 {_ampm(when.strftime('%H:%M'))}(한 번)"
        except ValueError:
            return run_at
    if rule == "hourly":
        mm = run_at.split(":")[-1] if ":" in run_at else "00"
        return "매시간 정각" if mm == "00" else f"매시간 {int(mm)}분"
    t = _ampm(run_at) if _RX_HM.match(run_at) else run_at
    if rule == "daily":
        return f"매일 {t}"
    if rule == "weekdays":
        return f"평일 {t}"
    if rule == "weekly":
        return "매주 " + "·".join(_DAY_NAMES[d] for d in days if 0 <= d <= 6) + f" {t}"
    if rule == "monthly":
        return f"매월 {s.get('mday') or 1}일 {t}"
    if rule == "custom":
        return f"{s.get('interval') or 1}{ {'daily': '일', 'weekly': '주', 'monthly': '개월'}.get(s.get('freq') or '', '') }마다 {t}"
    return t


def chip_of(s: dict) -> dict:
    """채팅 하단 예약 칩 — 사진 시안 '월요일 · GPT 주간 업데이트' / the chip under the answer"""
    rule, days = s.get("rule"), s.get("days") or []
    if rule == "weekly":
        head = "·".join(_DAY_NAMES[d] for d in days if 0 <= d <= 6) or "매주"
    elif rule == "daily":
        head = "매일"
    elif rule == "weekdays":
        head = "평일"
    elif rule == "monthly":
        head = f"매월 {s.get('mday') or 1}일"
    elif rule == "hourly":
        head = "매시간"
    elif rule == "once":
        try:
            when = datetime.strptime(s.get("run_at") or "", "%Y-%m-%dT%H:%M")
            head = f"{when.month}/{when.day}"
        except ValueError:
            head = "한 번"
    else:
        head = "반복"
    return {"id": s["id"], "name": s.get("name") or "", "label": f"{head} · {s.get('name') or ''}",
            "rule_label": rule_label(s), "next_run_at": s.get("next_run_at"), "coll_id": s.get("coll_id") or None}


def confirmation_text(spec: dict, sched: dict, coll_name: str) -> str:
    """확인 답변(사진 시안): 설정했습니다 👍 → 언제 무엇을 → 주요 내용 → 결과 확인 안내"""
    # Confirmation answer (per the design capture): set → when/what → key points → where to find results
    lines = ["설정했습니다 👍", "",
             f"**{rule_label(sched)}(한국시간)**에 「{spec['prompt']}」를 실행해 정리해서 알려드릴게요."]
    if coll_name:
        lines.append(f"「{coll_name}」 컬렉션의 자료와 지침을 함께 참고합니다.")
    if spec.get("points"):
        lines += ["", "주요 내용은:"] + [f"- {p}" for p in spec["points"]]
    lines += ["", f"실행 결과는 예약 작업 › {sched.get('name') or spec['name']} 히스토리에서 확인할 수 있고, 실행이 끝나면 메일로도 알려드립니다."]
    return "\n".join(lines)


def _cap_text(chat: dict) -> str:
    if (chat.get("coll") or "").strip():
        return f"이 컬렉션에는 예약을 {schedules.MAX_PER_COLL}개까지 둘 수 있어요. 예약 작업에서 기존 예약을 정리한 뒤 다시 요청해 주세요."
    return f"예약은 {schedules.MAX_GLOBAL}개까지 둘 수 있어요. 예약 작업에서 기존 예약을 정리한 뒤 다시 요청해 주세요."


# 로컬 지식 에이전트를 고른 채팅의 자연어 예약(2026-10-28 검토 반영): 예약은 local_agents 를 저장하지 않으므로(schedules.norm_scope_files)
# 만들면 실행 때 Public 전체 · 모든 로컬로 넓어진다. 예약 대화 상자가 Local 구획을 잠그는 것과 같게, 예약을 만들지 않고 이유와 방법을
# 안내한다. 언어는 intent._lang_note 규칙(한글이 있으면 한국어, 한글 없이 영문이면 영어)을 따른다.
# A natural-language schedule from a chat that chose local knowledge agents (2026-10-28 review): schedules never store local_agents
# (schedules.norm_scope_files), so the run would widen to all of Public and every local agent. Like the schedule dialog locking
# the Local section, no schedule is created and the reply says why and what to do. The language follows the intent._lang_note
# rule (Hangul = Korean, Latin letters without Hangul = English).
LOCAL_BLOCKED_KO = ("예약 작업에서는 로컬 지식 에이전트를 쓸 수 없어 예약을 만들지 않았습니다. "
                    "리소스 선택에서 지식 관리 Local 선택을 풀고 다시 요청해 주세요.")
LOCAL_BLOCKED_EN = ("Local knowledge agents are not available for schedules, so no schedule was created. "
                    "Clear the Knowledge Management Local choice in Select Resources and ask again.")


def local_chosen(scope_files: dict | None) -> bool:
    """로컬 지식 에이전트를 고른 범위인가 / whether the scope chose local knowledge agents"""
    sf = scope_files if isinstance(scope_files, dict) else {}
    return bool(sf.get("local_agents"))


def local_blocked_text(message: str) -> str:
    t = message or ""
    english = not re.search(r"[가-힣]", t) and bool(re.search(r"[A-Za-z]", t))
    return LOCAL_BLOCKED_EN if english else LOCAL_BLOCKED_KO


async def confirm_events(chat: dict, spec: dict, scope: str, agents: list | None, scope_files: dict | None,
                         owner: str, message: str = ""):
    """예약 생성 + 확인 답변 이벤트(answer_head/token/schedule/done). 상한이면 안내만, 로컬 지식 에이전트를 골랐으면 만들지 않고 안내만.
    message = 사용자 원문(안내 언어 판단용, 없으면 spec 의 prompt)."""
    # Create the schedule and emit the confirmation events; only a note when capped, and only a note (no schedule) when local
    # knowledge agents were chosen. message = the user's text (for the note's language; spec's prompt when empty).
    import asyncio
    chat_id = chat["id"]
    if local_chosen(scope_files):
        note = local_blocked_text(message or spec.get("prompt") or "")
        mid = db.add_message(chat_id, "assistant", note, meta={"source": "사내"})
        yield {"type": "answer_head", "source": "사내"}
        yield {"type": "token", "text": note}
        yield {"type": "done", "message_id": mid}
        return
    sched = await asyncio.to_thread(create_from_spec, spec, chat, owner, scope, agents, scope_files)
    if sched is None:
        note = _cap_text(chat)
        mid = db.add_message(chat_id, "assistant", note, meta={"source": "사내"})
        yield {"type": "answer_head", "source": "사내"}
        yield {"type": "token", "text": note}
        yield {"type": "done", "message_id": mid}
        return
    coll_name = ""
    if sched.get("coll_id"):
        coll_name = await asyncio.to_thread(schedules._coll_name, sched["coll_id"])  # noqa: SLF001
    text = confirmation_text(spec, sched, coll_name)
    chip = chip_of(sched)
    mid = db.add_message(chat_id, "assistant", text, meta={"source": "사내", "kind": "schedule", "sched": chip})
    yield {"type": "answer_head", "source": "사내"}
    yield {"type": "token", "text": text}
    yield {"type": "schedule", "sched": chip, "message_id": mid}
    yield {"type": "done", "message_id": mid}
