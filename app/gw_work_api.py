"""그룹웨어 에이전트 모드 — 업무 관리 패널 + 행 액션 데모 응답 (2026-08-24, 에이전트 모드 4차).

시안(15장) 기준: 우측 "업무 관리" 패널(오늘 업무 요약 KPI 3 + 도구 카드 4: Outlook 메일·Outlook 일정·
Microsoft To Do·SharePoint — Teams는 2026-08-28 제거, 행별 액션 칩)과, 칩을 눌렀을 때 채팅에 찍히는 구조화 결과 카드
(카드형 / 텍스트+카드 / 텍스트+카드+액션 버튼). 데이터는 스마트 실행 시드(smart_seed — @도구 조회와
같은 원천)에서 읽고, 결과는 시드 문안으로 만든다. 일정 변경만 2턴(후보 시간 → "N번" 회신 → 변경).
**실 연동 작업 때는 이 모듈의 /ask 내부만 갈아끼우면 된다**(어댑터 계약: panel 응답 형태와
/ask {ns,item_id,action,chat_id,choice} → {chat_id,title,user,text,card,pending} 불변).

Groupware agent mode — "Work management" panel + row-action demo answers (agent-mode rework round 4).
Per the 15 reference designs: the right panel (today's KPI tiles + five tool cards with per-row action
chips) and the structured result cards a chip posts into the chat (card / text+card / text+card+button).
Data comes from the smart-execution seeds (smart_seed — the same source as the @tool queries); results
are seeded copy. Only "reschedule" is two-turn (candidate slots → "N번" reply → applied).
**Real integration later swaps only the inside of /ask** — the adapter contract stays.
"""

from datetime import timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import db, kst, smart_seed as S

router = APIRouter(prefix="/api/gwwork", tags=["gwwork"])

# Teams는 제거(2026-08-28 — Graph Teams API가 MFA를 요구해 실연동 불가, 사용자 지시로 전면 삭제)
# Teams removed (2026-08-28 — the Graph Teams API requires MFA; deleted entirely per user decision)
TOOL_LABEL = {"mail": "Outlook 메일", "calendar": "Outlook 일정", "todo": "Microsoft To Do", "sharepoint": "SharePoint"}
ACTIONS = {
    "mail": [("summary", "요약"), ("reply", "답장 작성"), ("todo", "할 일 추가")],
    "calendar": [("brief", "회의 브리핑"), ("todo", "할 일 추가"), ("reschedule", "일정 변경")],
    "todo": [("plan", "세부 계획"), ("complete", "완료 처리"), ("defer", "내일로 미루기")],
    "sharepoint": [("changes", "변경 내역 요약"), ("summary", "문서 요약"), ("share", "공유 링크")],
}
_WEEKDAY = ["월", "화", "수", "목", "금", "토", "일"]


def _acts(ns: str) -> list[dict]:
    return [{"key": k, "label": lbl} for k, lbl in ACTIONS[ns]]


# ── 패널 데이터(시드 → 행) ────────────────────────────────────────────────────
# ── Panel data (seeds → rows) ────────────────────────────────────────────────
def _mail_rows() -> list[dict]:
    rows = [m for m in S._MAIL if m["folder"] == "inbox" and m["unread"]]
    rows.sort(key=lambda m: (m["d"], m["t"]), reverse=True)
    return [{"id": m["id"], "time": m["t"], "title": m["subject"], "sub": m.get("sub") or m["from"],
             "urgent": m.get("importance") == "high"} for m in rows]


def _event_rows() -> list[dict]:
    rows = [e for e in S._EVENTS if e["d"] == 0]
    rows.sort(key=lambda e: e["s"])
    return [{"id": e["id"], "time": e["s"], "title": e["subject"], "sub": e.get("sub") or e["loc"]} for e in rows]


def _task_rows() -> list[dict]:
    # 기한 지난 항목은 패널(시안 7건)에서 제외 — @todo 기한 초과 조회용 시드는 유지 / overdue seeds stay for @todo, panel keeps the design's 7
    rows = [t for t in S._TASKS if t["done"] is None and (t["due"] is None or t["due"] >= 0)]
    rows.sort(key=lambda t: t["due"] if t["due"] is not None else 99)   # 같은 기한은 시드 순서 유지(시안 순) / same due keeps seed order
    return [{"id": t["id"], "time": t.get("t") or "", "title": t["title"], "sub": t.get("note") or S._LIST_NAME[t["list"]]} for t in rows]


def _file_rows() -> list[dict]:
    rows = [f for f in S._FILES if f.get("recent")]
    rows.sort(key=lambda f: (f["d"], f.get("t") or ""), reverse=True)
    return [{"id": f["id"], "time": f.get("t") or "", "title": f["name"], "sub": f.get("sub") or f["by"]} for f in rows]


def _next_meeting() -> str:
    now = kst.now().strftime("%H:%M")
    todays = sorted([e for e in S._EVENTS if e["d"] == 0], key=lambda e: e["s"])
    # 오늘 일정이 모두 지났으면 지난 시각 대신 '-'(리뷰 확정: "다음 회의"에 지난 시간 표기 금지)
    # Once today's meetings are over show '-' instead of a past start time (review finding)
    return next((e["s"] for e in todays if e["s"] >= now), "-")


@router.get("/panel")
def panel() -> dict:
    mails, events, tasks, files = _mail_rows(), _event_rows(), _task_rows(), _file_rows()
    urgent = sum(1 for r in mails if r["urgent"])
    due_today = sum(1 for t in S._TASKS if t["done"] is None and t["due"] == 0)
    pending_share = sum(1 for f in S._FILES if f.get("pending_share"))
    return {
        "kpi": [{"label": "긴급 메일", "value": str(urgent)}, {"label": "다음 회의", "value": _next_meeting()},
                {"label": "오늘 마감", "value": str(due_today)}],
        "tools": [
            {"ns": "mail", "label": TOOL_LABEL["mail"], "sub": f"안 읽음 **{len(mails)}** · 긴급 **{urgent}**",
             "rows": mails, "more": f"안 읽은 메일 {max(0, len(mails) - 3)}건 더 보기", "actions": _acts("mail")},
            {"ns": "calendar", "label": TOOL_LABEL["calendar"], "sub": f"오늘 **{len(events)}건** · 다음 일정 **{_next_meeting()}**",
             "rows": events, "more": "오늘 일정 전체 보기", "actions": _acts("calendar")},
            {"ns": "todo", "label": TOOL_LABEL["todo"], "sub": f"오늘 마감 **{due_today}** · 전체 **{len(tasks)}**",
             "rows": tasks, "more": f"전체 할 일 {len(tasks)}건 보기", "actions": _acts("todo")},
            {"ns": "sharepoint", "label": TOOL_LABEL["sharepoint"], "sub": f"최근 변경 **{len(files)}** · 공유 대기 **{pending_share}**",
             "rows": files, "more": "최근 문서 전체 보기", "actions": _acts("sharepoint")},
        ],
    }


# ── 행 액션 → 결과 카드 ───────────────────────────────────────────────────────
# ── Row actions → result cards ───────────────────────────────────────────────
class AskIn(BaseModel):
    ns: str
    item_id: str
    action: str
    chat_id: str = ""
    choice: int = 0   # reschedule_apply의 후보 번호(1~) / candidate number for reschedule_apply


def _find(ns: str, item_id: str) -> dict | None:
    table = {"mail": S._MAIL, "calendar": S._EVENTS, "todo": S._TASKS, "sharepoint": S._FILES}[ns]
    return next((x for x in table if x["id"] == item_id), None)


def _stem(name: str) -> str:
    return name.rsplit(".", 1)[0] if "." in name else name


def _deadline_label(days: int | None) -> str:
    if days is None:
        return "기한 없음"
    d = S._today() + timedelta(days=days)
    return {0: "오늘", 1: "내일"}.get(days, f"{_WEEKDAY[d.weekday()]}요일")


def _slots() -> list[str]:
    d1 = S._today() + timedelta(days=1)
    d2 = d1 + timedelta(days=1)
    w1, w2 = _WEEKDAY[d1.weekday()], _WEEKDAY[d2.weekday()]
    return [f"내일({w1}) 10:00–10:30", f"내일({w1}) 15:00–15:30", f"{w2}요일 11:00–11:30"]


def _card(ns: str, title: str, lines: list[str], btn: str | None = None) -> dict:
    return {"ns": ns, "title": title, "lines": lines, "btn": btn}


def _reply_body(to: str, subject: str | None) -> list[str]:
    lines = [f"받는 사람: {to}"]
    if subject:
        lines.append(f"제목: RE: {subject}")
    lines += ["", "안녕하세요,", "", "요청 주신 건 확인했습니다. 검토 후 목요일 오후까지 의견 회신드리겠습니다.",
              "추가로 필요한 자료가 있으면 말씀해 주세요.", "", "감사합니다."]
    return lines


def _pending_of(chat_id: str) -> dict | None:
    """채팅의 마지막 gw_card가 남긴 대기 상태 — 일정 변경 적용은 이 후보 목록을 써야 한다(리뷰 확정: 재계산 금지)."""
    # The pending state left by the chat's last gw_card — reschedule_apply must use these options (review: never recompute).
    for m in reversed(db.list_messages(chat_id)):
        meta = m.get("meta") or {}
        if m["role"] == "assistant" and meta.get("kind") == "gw_card":
            return meta.get("pending")
    return None


def _build(ns: str, item: dict, action: str, choice: int, options: list | None = None) -> tuple[str, str, dict, dict | None, str]:
    """→ (action_label, text, card, pending, title)"""
    pending = None
    if ns == "mail":
        subj = item["subject"]
        if action == "summary":
            lines = [f"- {x}" for x in item.get("summary") or [item["preview"], f"보낸 사람: {item['from']}"]]
            return "요약", "", _card(ns, f"요약 · {subj}", lines), None, subj
        if action == "reply":
            return "답장 작성", "답장 초안을 작성했습니다. 검토 후 발송해 주세요.", \
                _card(ns, f"답장 초안 · {subj}", _reply_body(item.get("sub", "").split(" · ")[0] or item["from"], subj), "Outlook 메일 전송"), None, f"RE: {subj}"
        if action == "todo":
            dl = item.get("deadline") or "내일"
            return "할 일 추가", "할 일로 추가했습니다.", \
                _card(ns, "할 일 추가", [f"**{subj}**", f"- 마감: {dl} · 목록: 업무", "- 원본: Outlook 메일 항목에서 생성 (링크 연결됨)"], "To Do 추가"), None, subj
    if ns == "calendar":
        subj = item["subject"]
        if action == "brief":
            lines = [f"- {x}" for x in item.get("brief") or [f"목적: {item['body']}", f"참석: {len(item['att']) + 1}명 ({item['organizer']} 주재)",
                                                              f"장소: {item['loc'] or 'Teams 온라인'} · {item['s']}~{item['e']}", "준비물: 관련 자료, 지난 회의 액션아이템"]]
            return "회의 브리핑", "", _card(ns, f"회의 브리핑 · {subj}", lines), None, subj
        if action == "todo":
            return "할 일 추가", "할 일로 추가했습니다.", \
                _card(ns, f"할 일 추가 · {subj}", [f"**{subj}**", "- 마감: 금요일 · 목록: 업무", "- 원본: Outlook 일정 항목에서 생성 (링크 연결됨)"], "To Do 추가"), None, subj
        if action == "reschedule":
            slots = _slots()
            lines = [f"『{subj}』 조정 가능 시간입니다.", "", "참석자 전원 가능:"] \
                + [f"{'①②③'[i]} {s}" for i, s in enumerate(slots)] \
                + ["", "원하는 시간을 말씀하시면 일정 변경과 안내 메일까지 처리합니다."]
            pending = {"kind": "reschedule", "ns": ns, "item_id": item["id"], "options": slots}
            return "일정 변경", "", _card(ns, f"일정 변경 · {subj}", lines), pending, subj
        if action == "reschedule_apply":
            slots = options or _slots()
            if not (1 <= choice <= len(slots)):
                raise HTTPException(status_code=422, detail="후보 번호가 올바르지 않습니다")
            return "일정 변경", "일정을 변경했습니다.", \
                _card(ns, f"일정 변경 · {subj}", [f"『{subj}』 일정을 {slots[choice - 1]}으로 변경했습니다.", "참석자에게 변경된 일정이 업데이트되었습니다."]), None, subj
    if ns == "todo":
        title = item["title"]
        if action == "plan":
            lines = [f"『{title}』 세부 계획입니다.", ""] + [f"- {x}" for x in item.get("plan") or ["현황 파악 (20분)", "초안 작성 (40분)", "검토 요청 (10분)"]] \
                + ["", item.get("plan_note") or "오늘 안에 완료하려면 오후 일찍 시작을 권장합니다."]
            return "세부 계획", "", _card(ns, f"세부 계획 · {title}", lines), None, title
        if action == "complete":
            return "완료 처리", "완료 처리했습니다.", \
                _card(ns, f"완료 처리 · {title}", [f"**{title}**", "", "- 상태: 완료", "- 완료 시간: 방금", "- Microsoft To Do에 반영됨"]), None, title
        if action == "defer":
            return "내일로 미루기", "", _card(ns, f"내일로 미루기 · {title}", [f"『{title}』 마감을 내일로 변경했습니다.", "", "내일 오전 9시에 다시 알립니다."]), None, title
    if ns == "sharepoint":
        name = item["name"]
        stem = _stem(name)
        if action == "changes":
            lines = [f"『{name}』 변경 내역입니다.", ""] + [f"- {x}" for x in item.get("changes") or [f"수정자: {item['by']}"]]
            return "변경 내역 요약", "", _card(ns, f"변경 내역 요약 · {stem}", lines, "SharePoint 열기"), None, name
        if action == "summary":
            lines = [f"『{name}』 요약입니다.", ""] + [f"- {x}" for x in item.get("summary") or [f"{item['path']}에 있는 {item['ext']} 문서", f"마지막 수정: {item['by']}"]]
            return "문서 요약", "", _card(ns, f"문서 요약 · {stem}", lines, "SharePoint 열기"), None, name
        if action == "share":
            return "공유 링크", "공유 링크를 생성했습니다.", \
                _card(ns, f"공유 링크 · {stem}", ["- 권한: 조직 내 보기 가능 (편집 불가)", "- 만료: 30일", "- 링크: [https://ai365.sharepoint.com/](https://ai365.sharepoint.com/)"], "SharePoint 열기"), None, name
    raise HTTPException(status_code=422, detail="지원하지 않는 액션입니다")


@router.post("/ask")
def ask(body: AskIn) -> dict:
    if body.ns not in ACTIONS:
        raise HTTPException(status_code=422, detail="알 수 없는 도구입니다")
    item = _find(body.ns, body.item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="항목을 찾을 수 없습니다")
    options = None
    if body.action == "reschedule_apply":
        p = _pending_of(body.chat_id) if body.chat_id else None
        if not p or p.get("kind") != "reschedule" or p.get("item_id") != body.item_id:
            raise HTTPException(status_code=409, detail="변경 대기 중인 일정이 없습니다")
        options = p.get("options") or []
    action_label, text, card, pending, title = _build(body.ns, item, body.action, body.choice, options)
    item_title = item.get("subject") or item.get("title") or item.get("name") or item.get("last") or ""
    user_text = f"{TOOL_LABEL[body.ns]} · {action_label}\n{item_title}"
    user_meta = {"kind": "gw_user", "ns": body.ns, "action": body.action, "item_id": body.item_id, "item_title": item_title}
    if body.action == "reschedule_apply":
        user_text = f"{body.choice}번"
        user_meta = None   # 사용자가 실제로 타이핑한 회신 — 일반 말풍선 / a typed reply — plain bubble
    if body.chat_id:
        chat = db.get_chat(body.chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="존재하지 않는 채팅입니다")
    else:
        chat = db.create_chat(title=title[:40], scope="자동")
    db.add_message(chat["id"], "user", user_text, user_meta)
    meta = {"kind": "gw_card", "ns": body.ns, "text": text, "card": card, "pending": pending}
    db.add_message(chat["id"], "assistant", text or card["title"], meta)
    return {"chat_id": chat["id"], "title": chat["title"], "user": user_text, "text": text, "card": card, "pending": pending}
