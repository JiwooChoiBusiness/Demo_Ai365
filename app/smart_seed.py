"""@멘션 조회(Info) 전용 데모 시드 데이터 — 메일·일정·할 일·문서·Teams.

Microsoft Graph 연동 없이 조회 기능을 시연하기 위한 픽스처다. DB에 넣지 않는 이유는
catalog.KNOWLEDGE_TREE와 같다 — 정적 데모 데이터는 코드에 두는 편이 드리프트가 없다.

**모든 날짜는 상대 오프셋**이다. 고정 날짜('08-01')를 쓰면 데모 며칠 뒤 "오늘 일정 0건"이
되고 브리핑이 전부 과거 얘기가 된다. `_at(days, "HH:MM")`이 호출 시점 기준으로 실제 날짜를
만든다.

접근 함수(mail_list/calendar_list/…)는 **Microsoft Graph 엔드포인트와 1:1 대응**하도록
이름과 반환 필드를 잡았다. 나중에 Graph로 갈아끼울 때 이 함수 내부만 교체하면 되고
호출부(smart_actions_api)는 그대로 둔다.

    mail_list      -> GET /me/mailFolders/{folder}/messages
    mail_get       -> GET /me/messages/{id}
    calendar_list  -> GET /me/calendarView?startDateTime&endDateTime
    calendar_free  -> POST /me/findMeetingTimes
    todo_list      -> GET /me/todo/lists/{id}/tasks
    files_list     -> GET /me/drive/root/search(q=) · /me/drive/root:/{path}:/children
    teams_list     -> GET /me/chats · GET /chats/{id}/messages
"""
# Demo seed data for @-mention Info (read) capabilities — mail, calendar, to-dos, files, Teams.
#
# Fixtures that let the read features be demoed without a Microsoft Graph integration. Kept in code
# rather than the DB for the same reason as catalog.KNOWLEDGE_TREE: static demo data drifts if stored.
#
# **Every date is a relative offset.** Hard-coded dates ('08-01') make "today's schedule" empty a few
# days into the demo. `_at(days, "HH:MM")` builds real datetimes from call time.
#
# The accessor functions are named/shaped to map 1:1 onto Microsoft Graph endpoints, so swapping in a
# real Graph client later means replacing function bodies only — callers stay untouched.

from datetime import datetime, timedelta

from app import access, kst

# ── 시간 헬퍼 ────────────────────────────────────────────────────────────────
# ── Time helpers ─────────────────────────────────────────────────────────────


def _today() -> datetime:
    return kst.now().replace(hour=0, minute=0, second=0, microsecond=0)


def _at(days: int, hhmm: str = "09:00") -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return _today() + timedelta(days=days, hours=h, minutes=m)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="minutes")


def _rel_label(dt: datetime) -> str:
    """'오늘 14:00' / '어제' / '8/7(금)' 같은 사람이 읽는 표기."""
    # Human-readable stamp: "오늘 14:00" / "어제" / "8/7(금)".
    delta = (dt.replace(hour=0, minute=0) - _today()).days
    wd = "월화수목금토일"[dt.weekday()]
    if delta == 0:
        return f"오늘 {dt:%H:%M}"
    if delta == -1:
        return f"어제 {dt:%H:%M}"
    if delta == 1:
        return f"내일 {dt:%H:%M}"
    return f"{dt.month}/{dt.day}({wd}) {dt:%H:%M}"


# ── 조직도 연동 — 시드는 이름만 들고, 이메일은 런타임 조회 ──────────────────────
# ── Org-chart binding — the seed stores names only; emails resolve at runtime ──

# 조직도에 없는 발신자·주최자(업무 관리 시안 이름)도 실제 주소로 — _person이 이름을 그대로 내지 않게(리뷰 확정)
# Senders/organizers outside the org chart (work-panel design names) resolve to real addresses too (review finding)
_EXTERNAL = {"박태호": "demo-ee68dab030@workspace.example", "박성호": "demo-80b1c4d6aa@workspace.example",
             "박상민": "demo-d902c8bee6@workspace.example", "김대리": "demo-5bb5313716@workspace.example", "인사팀": "demo-75cefa1478@workspace.example",
             "HR팀": "demo-75cefa1478@workspace.example", "제품기획팀": "demo-726b3e6ff5@workspace.example", "법무팀": "demo-1e9e4bcb2d@workspace.example",
             "재무팀": "demo-40afec3db0@workspace.example", "IT운영팀": "demo-136201db60@workspace.example", "QA팀": "demo-d59895e548@workspace.example",
             "디자인팀": "demo-fdaf4bd284@workspace.example"}

# 이름→이메일 맵 캐시 — 목록 한 건마다 from/to/cc를 풀면 행당 수십 번 조회하게 된다.
# 조직도 편집 반영이 늦어지지 않도록 수명은 짧게 둔다.
# Name->email map cache — resolving from/to/cc per row otherwise costs dozens of lookups per list.
# Kept short-lived so org-chart edits show up promptly.
_EMAIL_CACHE: dict[str, str] = {}
_EMAIL_CACHE_AT = datetime.min
_EMAIL_CACHE_TTL = timedelta(seconds=5)


def _email_map() -> dict[str, str]:
    global _EMAIL_CACHE, _EMAIL_CACHE_AT
    now = kst.now()
    if now - _EMAIL_CACHE_AT > _EMAIL_CACHE_TTL:
        _EMAIL_CACHE = {
            m["name"]: (m.get("email") or m["name"])
            for m in access.list_members()
            if m.get("name") and (m.get("status") or "재직") != "퇴직"
        }
        _EMAIL_CACHE_AT = now
    return _EMAIL_CACHE


def email_of(name: str) -> str:
    """이름 → 조직도 이메일. 퇴직자는 제외되고, 외부 인사·미일치는 별도 처리한다."""
    # Name -> org-chart email. Retired members are excluded; externals and unmatched names handled separately.
    if "@" in name:
        return name
    hit = _email_map().get(name)
    if hit:
        return hit
    return _EXTERNAL.get(name, name)


def _person(name: str) -> dict:
    return {"name": name, "email": email_of(name)}


# ── 액션(쓰기) 헬퍼 — 세션 지속(인메모리, 서버 재시작 시 초기화). 2026-08-27 그룹웨어 실행 추가 ──
# ── Action (write) helpers — session-persistent (in-memory; reset on restart). Groupware execution 2026-08-27 ──
DEMO_USER = "최지우"  # 데모 시연 계정 — 뮤테이터 발신/담당 기본값 / demo persona — default sender/assignee for mutators


def _next_id(rows: list, prefix: str) -> str:
    """prefix+숫자 id 중 최대값+1 — 신규 행 id 생성(예: e17, t15, s5, c8)."""
    # Max numeric id with this prefix + 1 — builds the new row id (e.g. e17, t15, s5, c8).
    nums = [int(r["id"][len(prefix):]) for r in rows
            if r["id"].startswith(prefix) and r["id"][len(prefix):].isdigit()]
    return f"{prefix}{(max(nums) + 1) if nums else 1}"


# ── 메일 (16건: 받은 12 / 보낸 4) — 리스트: 액션(mail_send)이 보낸 편지함에 추가 ──────
# ── Mail (16: 12 inbox / 4 sent) — a list so actions (mail_send) can append to Sent ──
_MAIL = [
    # importance: Graph의 message.importance("high"/"normal") — 업무 관리 패널의 긴급 배지·KPI용
    # deadline/sub: 업무 관리 패널 행 부제(시안 문구 그대로) / panel row subtitle (design copy)
    # importance: Graph's message.importance ("high"/"normal") — urgent badge & KPI in the work panel
    {"id": "m1", "folder": "inbox", "from": "박성호", "to": ["최지우"], "cc": ["이서윤"],
     "subject": "[예산] 3분기 예산안 검토 요청", "d": 0, "t": "10:42", "unread": True, "importance": "high",
     "attach": [{"name": "예산안_v2.xlsx", "size": 418_304}], "sub": "CFO 박성호 · 금요일 마감", "deadline": "금요일",
     "preview": "3분기 예산안 v2 검토 및 승인 요청드립니다. 마케팅 예산 +12%, 신규 채용 2건이 포함되어 있습니다.",
     "body": "안녕하세요, CFO 박성호입니다.\n\n3분기 예산안 v2 검토 및 승인 요청드립니다. 마케팅 예산 +12%, 신규 채용 2건이 포함되어 있습니다.\n\n첨부: 예산안_v2.xlsx, 변경내역 요약\n마감: 금요일",
     "summary": ["3분기 예산안 v2 검토 및 승인 요청", "마감: 금요일", "마케팅 예산 +12%, 신규 채용 2건 포함", "첨부: 예산안_v2.xlsx, 변경내역 요약"]},
    {"id": "m2", "folder": "inbox", "from": "인사팀", "to": ["최지우"], "cc": [],
     "subject": "8월 전사 공지 — 보안 교육 안내", "d": 0, "t": "08:51", "unread": True, "attach": [], "sub": "인사팀",
     "preview": "8월 정보보안 필수 교육 일정을 안내드립니다. 이번 주 목요일 13:00, 본사 3층 대회의실.",
     "body": "인사팀입니다.\n\n8월 정보보안 필수 교육 일정을 안내드립니다.\n- 일시: 이번 주 목요일 13:00~14:30\n- 장소: 본사 3층 대회의실\n- 대상: 전 임직원(미이수자 필수)\n\n참석이 어려우면 회신 부탁드립니다.",
     "summary": ["8월 정보보안 필수 교육 — 목요일 13:00~14:30, 본사 3층 대회의실", "대상: 전 임직원(미이수자 필수)", "불참 시 회신 필요"]},
    {"id": "m3", "folder": "inbox", "from": "김대리", "to": ["최지우"], "cc": [],
     "subject": "계약서 수정본 회신 요청", "d": 0, "t": "09:15", "unread": True, "importance": "high",
     "attach": [{"name": "A상사_계약서_v3.docx", "size": 96_256}], "sub": "A상사 김대리",
     "preview": "보내주신 수정 의견을 반영한 계약서 v3를 첨부드립니다. 이번 주 내 회신 부탁드립니다.",
     "body": "안녕하세요, A상사 김대리입니다.\n\n보내주신 수정 의견을 반영한 계약서 v3를 첨부드립니다. 이번 주 내 회신 부탁드립니다.\n\n감사합니다.",
     "summary": ["수정 의견을 반영한 계약서 v3 회신 요청", "첨부: A상사_계약서_v3.docx", "회신 기한: 이번 주"]},
    {"id": "m4", "folder": "inbox", "from": "제품기획팀", "to": ["최지우"], "cc": [],
     "subject": "제품 리뷰 회의 자료 업데이트", "d": 0, "t": "09:15", "unread": True, "attach": [], "sub": "제품기획팀",
     "preview": "오늘 14:00 주간 제품 리뷰 자료를 업데이트했습니다. 데모 환경과 지표 대시보드 캡처를 확인해 주세요.",
     "body": "제품기획팀입니다.\n\n오늘 14:00 주간 제품 리뷰 자료를 업데이트했습니다. 데모 환경과 지표 대시보드 캡처를 확인해 주세요."},
    {"id": "m5", "folder": "inbox", "from": "법무팀", "to": ["최지우"], "cc": [],
     "subject": "A상사 계약 조건 변경사항 안내", "d": 0, "t": "09:15", "unread": True, "attach": [], "sub": "법무팀",
     "preview": "A상사 계약의 지급 조건과 위약금 조항 변경 내용을 안내드립니다.",
     "body": "법무팀입니다.\n\nA상사 계약의 지급 조건(45일→30일)과 위약금 조항 변경 내용을 안내드립니다. 서명 전 검토 부탁드립니다."},
    {"id": "m6", "folder": "inbox", "from": "HR팀", "to": ["최지우"], "cc": [],
     "subject": "9월 교육 일정 참석 여부 확인", "d": 0, "t": "09:15", "unread": True, "attach": [], "sub": "HR팀",
     "preview": "9월 리더십 교육 참석 여부를 이번 주까지 회신 부탁드립니다.",
     "body": "HR팀입니다.\n\n9월 리더십 교육(9/12 금 10:00~17:00) 참석 여부를 이번 주까지 회신 부탁드립니다."},
    {"id": "m7", "folder": "inbox", "from": "재무팀", "to": ["최지우"], "cc": [],
     "subject": "월간 비용 집행 내역 공유", "d": 0, "t": "09:15", "unread": True, "attach": [{"name": "비용_집행_내역_08.xlsx", "size": 204_800}], "sub": "재무팀",
     "preview": "8월 비용 집행 내역을 공유드립니다. 마케팅·외주 항목을 확인해 주세요.",
     "body": "재무팀입니다.\n\n8월 비용 집행 내역을 공유드립니다. 마케팅·외주 항목이 전월 대비 증가했습니다."},
    {"id": "m8", "folder": "inbox", "from": "IT운영팀", "to": ["최지우"], "cc": [],
     "subject": "서비스 장애 대응 결과 공유", "d": 0, "t": "09:15", "unread": True, "attach": [], "sub": "IT운영팀",
     "preview": "어제 발생한 서비스 장애 대응 결과와 재발 방지 조치를 공유드립니다.",
     "body": "IT운영팀입니다.\n\n어제 14:20 발생한 서비스 장애(약 25분)는 DB 커넥션 풀 고갈이 원인이었습니다. 풀 상한 상향과 모니터링 알림을 추가했습니다."},
    {"id": "m9", "folder": "inbox", "from": "QA팀", "to": ["최지우"], "cc": [],
     "subject": "신규 기능 QA 결과 확인 요청", "d": 0, "t": "09:15", "unread": True, "attach": [], "sub": "QA팀",
     "preview": "신규 기능 2건의 QA 결과를 정리했습니다. 이슈 3건 중 1건은 릴리스 전 수정이 필요합니다.",
     "body": "QA팀입니다.\n\n신규 기능 2건의 QA 결과를 정리했습니다. 이슈 3건 중 1건(로그인 세션 만료)은 릴리스 전 수정이 필요합니다."},
    {"id": "m10", "folder": "inbox", "from": "김민준", "to": ["최지우"], "cc": [],
     "subject": "제품 로드맵 변경안 공유", "d": 0, "t": "08:30", "unread": True, "attach": [], "sub": "김민준",
     "preview": "2026H2 제품 로드맵 변경안(11월 릴리스 AI 기능 통합)을 공유드립니다.",
     "body": "김민준입니다.\n\n2026H2 제품 로드맵 변경안(11월 릴리스 AI 기능 통합)을 공유드립니다. 리소스 계획 표도 수정했습니다."},
    {"id": "m11", "folder": "inbox", "from": "홍서연", "to": ["최지우"], "cc": [],
     "subject": "주간 보고 취합 안내", "d": 0, "t": "08:10", "unread": True, "attach": [], "sub": "홍서연",
     "preview": "주간 보고는 수요일 17:00까지 제출 부탁드립니다.",
     "body": "홍서연입니다.\n\n주간 보고는 수요일 17:00까지 제출 부탁드립니다."},
    {"id": "m12", "folder": "inbox", "from": "고서진", "to": ["최지우"], "cc": [],
     "subject": "배포 체크리스트 점검 요청", "d": 0, "t": "07:55", "unread": True, "attach": [], "sub": "고서진",
     "preview": "이번 주 배포 전 체크리스트 점검을 부탁드립니다.",
     "body": "고서진입니다.\n\n이번 주 금요일 배포 전 체크리스트 점검을 부탁드립니다."},
    {"id": "s1", "folder": "sent", "from": "최지우", "to": ["박성호"], "cc": [],
     "subject": "RE: [예산] 2분기 예산 집행 결과", "d": -1, "t": "18:20", "unread": False, "attach": [],
     "preview": "2분기 집행 결과 확인했습니다. 3분기 안은 금주 내 검토하겠습니다.",
     "body": "2분기 집행 결과 확인했습니다. 3분기 안은 금주 내 검토하겠습니다."},
    {"id": "s2", "folder": "sent", "from": "최지우", "to": ["홍서연"], "cc": [],
     "subject": "영업 실적 리뷰 일정 제안", "d": -2, "t": "13:40", "unread": False, "attach": [],
     "preview": "다음 주 화요일 오후 2시 어떠신지요.",
     "body": "말씀 주신 리뷰 일정, 다음 주 화요일 오후 2시 어떠신지요."},
    {"id": "s3", "folder": "sent", "from": "최지우", "to": ["김대리"], "cc": ["법무팀"],
     "subject": "RE: 계약서 수정 의견", "d": -3, "t": "10:05", "unread": False, "attach": [],
     "preview": "수정 의견 전달드립니다. 반영본 회신 부탁드립니다.",
     "body": "수정 의견 전달드립니다. 반영본 회신 부탁드립니다."},
    {"id": "s4", "folder": "sent", "from": "최지우", "to": ["문가은"], "cc": [],
     "subject": "품질 지표 대시보드 접근 권한 요청", "d": -5, "t": "15:30", "unread": False, "attach": [],
     "preview": "품질 지표 대시보드 열람 권한 부여 부탁드립니다.",
     "body": "품질 지표 대시보드 열람 권한 부여 부탁드립니다."},
]


def mail_list(folder: str = "inbox", unread_only: bool = False,
              sender: str | None = None, q: str | None = None, top: int = 10) -> list[dict]:
    """받은/보낸 메일 조회 — Graph: GET /me/mailFolders/{folder}/messages"""
    out = []
    for m in _MAIL:
        if m["folder"] != folder:
            continue
        if unread_only and not m["unread"]:
            continue
        if sender and sender not in m["from"]:
            continue
        if q and q not in (m["subject"] + m["preview"] + m["body"]):
            continue
        out.append(_mail_row(m))
    out.sort(key=lambda x: x["receivedDateTime"], reverse=True)
    return out[:top]


def _mail_row(m: dict, with_body: bool = False) -> dict:
    dt = _at(m["d"], m["t"])
    row = {
        "id": m["id"],
        "from": _person(m["from"]),
        "to": [_person(n) for n in m["to"]],
        "cc": [_person(n) for n in m["cc"]],
        "subject": m["subject"],
        "bodyPreview": m["preview"],
        "receivedDateTime": _iso(dt),
        "when": _rel_label(dt),
        "isRead": not m["unread"],
        "importance": m.get("importance", "normal"),
        "hasAttachments": bool(m["attach"]),
        "attachments": m["attach"],
        "artifacts": m.get("artifacts") or [],
    }
    if with_body:
        row["body"] = m["body"]
    return row


def mail_get(mail_id: str | None = None, q: str | None = None) -> dict | None:
    """메일 한 건 — Graph: GET /me/messages/{id}. id가 없으면 제목 부분일치로 찾는다."""
    for m in _MAIL:
        if mail_id and m["id"] == mail_id:
            return _mail_row(m, with_body=True)
        if q and q in m["subject"]:
            return _mail_row(m, with_body=True)
    return None


def mail_unread_count() -> int:
    return sum(1 for m in _MAIL if m["folder"] == "inbox" and m["unread"])


def mail_send(to, subject: str, body: str, artifacts: list | None = None) -> dict:
    """새 메일을 보낸 편지함에 추가(가상 발송) — Graph: POST /me/sendMail. 세션 내 지속."""
    # Append a new mail to Sent (virtual send) — Graph: POST /me/sendMail. Session-persistent.
    tos = [t for t in (to if isinstance(to, list) else [to]) if t]
    row = {"id": _next_id(_MAIL, "s"), "folder": "sent", "from": DEMO_USER, "to": tos or ["나"], "cc": [],
           "subject": subject or "(제목 없음)", "d": 0, "t": kst.now().strftime("%H:%M"),
           "unread": False, "attach": [a["filename"] for a in artifacts or []],
           "artifacts": artifacts or [], "preview": (body or "")[:80], "body": body or ""}
    _MAIL.append(row)
    _persist()
    return _mail_row(row, with_body=True)


# ── 일정 (16건: 지난주 3 / 오늘 3 / 이번주 6 / 다음주 4) ───────────────────────
# ── Calendar (16: last week 3 / today 3 / this week 6 / next week 4) ──────────

_EVENTS = [
    {"id": "e1", "subject": "주간 제품 리뷰", "d": 0, "s": "14:00", "e": "15:00",
     "loc": "회의실 A", "online": False, "organizer": "박상민", "sub": "회의실 A · 참석 8명",
     "att": ["윤지호", "임채원", "한지안", "양도현", "문가은", "김민준", "최지우"], "body": "8월 스프린트 산출물 점검 및 다음 주 우선순위 결정",
     "brief": ["목적: 8월 스프린트 산출물 점검 및 다음 주 우선순위 결정", "참석: 제품·개발·디자인 8명 (박팀장 주재)",
               "지난 회의 액션아이템 3건 중 2건 완료, 1건(QA 시나리오) 오늘 마감", "준비물: 데모 환경, 지표 대시보드 캡처"]},
    {"id": "e2", "subject": "벤더 정기 콜", "d": 0, "s": "15:30", "e": "16:00",
     "loc": "Microsoft Teams 회의", "online": True, "organizer": "최지우", "sub": "Teams 온라인",
     "att": ["박태호"], "body": "벤더 월간 정기 콜 — 납기·이슈 점검"},
    {"id": "e3", "subject": "박상민 팀장 미팅", "d": 0, "s": "17:00", "e": "17:30",
     "loc": "소회의실 2", "online": False, "organizer": "박상민", "sub": "소회의실 2",
     "att": ["최지우"], "body": "하반기 제품 우선순위 1:1"},
    {"id": "e4", "subject": "3분기 실적 리뷰", "d": 1, "s": "11:00", "e": "12:00",
     "loc": "Microsoft Teams 회의", "online": True, "organizer": "김민준",
     "att": ["이서윤", "박도윤", "최지우"], "body": "3분기 실적 초안 검토"},
    {"id": "e5", "subject": "파트너사 정기 미팅", "d": 1, "s": "15:00", "e": "16:00",
     "loc": "Microsoft Teams 회의", "online": True, "organizer": "최지우",
     "att": ["박태호"], "body": "계약 갱신 사전 논의"},
    {"id": "e6", "subject": "제품 로드맵 워크숍", "d": 2, "s": "09:30", "e": "12:00",
     "loc": "본사 5층 세미나실", "online": False, "organizer": "윤지호",
     "att": ["임채원", "한지안", "최지우"], "body": "하반기 로드맵 확정"},
    {"id": "e7", "subject": "월간 보고서 마감", "d": 2, "s": "17:00", "e": "18:00",
     "loc": "", "online": False, "organizer": "홍서연",
     "att": ["최지우"], "body": "월간 경영 보고서 최종 제출"},
    {"id": "e8", "subject": "보안 교육 (필수)", "d": 3, "s": "13:00", "e": "14:30",
     "loc": "본사 3층 대회의실", "online": False, "organizer": "고서진",
     "att": ["최지우"], "body": "연 1회 정보보안 필수 교육"},
    {"id": "e9", "subject": "AI 파트 스프린트 회고", "d": 3, "s": "16:00", "e": "17:00",
     "loc": "Microsoft Teams 회의", "online": True, "organizer": "양도현",
     "att": ["백지윤", "허준서", "최지우"], "body": "스프린트 12 회고"},
    {"id": "e10", "subject": "예산 집행 점검", "d": 4, "s": "10:00", "e": "11:00",
     "loc": "본사 2층 회의실 A", "online": False, "organizer": "이서윤",
     "att": ["김민준", "최지우"], "body": "8월 잔여 예산 계획"},
    {"id": "e11", "subject": "전사 타운홀", "d": 7, "s": "14:00", "e": "15:30",
     "loc": "본사 5층 세미나실", "online": True, "organizer": "홍서연",
     "att": ["최지우"], "body": "3분기 전사 공유"},
    {"id": "e12", "subject": "계약 갱신 협의", "d": 8, "s": "11:00", "e": "12:00",
     "loc": "Microsoft Teams 회의", "online": True, "organizer": "최지우",
     "att": ["박태호", "홍서연"], "body": "파트너코프 계약 갱신"},
    {"id": "e13", "subject": "품질 지표 리뷰", "d": 9, "s": "15:00", "e": "16:00",
     "loc": "Microsoft Teams 회의", "online": True, "organizer": "문가은",
     "att": ["최지우"], "body": "월간 품질 지표 점검"},
    {"id": "e14", "subject": "하반기 교육 설명회", "d": 10, "s": "10:00", "e": "11:00",
     "loc": "본사 3층 대회의실", "online": False, "organizer": "정하준",
     "att": ["최지우"], "body": "하반기 교육 과정 안내"},
    {"id": "e15", "subject": "월간 경영 회의", "d": -5, "s": "10:00", "e": "11:30",
     "loc": "본사 5층 세미나실", "online": False, "organizer": "홍서연",
     "att": ["김민준", "최지우"], "body": "7월 실적 리뷰"},
    {"id": "e16", "subject": "영업 파이프라인 점검", "d": -3, "s": "14:00", "e": "15:00",
     "loc": "Microsoft Teams 회의", "online": True, "organizer": "최지우",
     "att": ["홍서연"], "body": "8월 파이프라인 현황"},
]

WORK_START, WORK_END = "09:00", "18:00"
LUNCH_START, LUNCH_END = "12:00", "13:00"


def _event_row(e: dict) -> dict:
    s, t = _at(e["d"], e["s"]), _at(e["d"], e["e"])
    return {
        "id": e["id"],
        "subject": e["subject"],
        "start": _iso(s),
        "end": _iso(t),
        "when": _rel_label(s),
        "timeRange": f"{s:%H:%M}~{t:%H:%M}",
        "location": e["loc"] or ("Microsoft Teams 회의" if e["online"] else ""),
        "isOnlineMeeting": e["online"],
        "organizer": _person(e["organizer"]),
        "attendees": [_person(n) for n in e["att"]],
        "bodyPreview": e["body"],
    }


def calendar_list(day_from: int = 0, day_to: int = 0, top: int = 20) -> list[dict]:
    """기간 일정 — Graph: GET /me/calendarView?startDateTime&endDateTime (오프셋 기준 일수)"""
    rows = [_event_row(e) for e in _EVENTS if day_from <= e["d"] <= day_to]
    rows.sort(key=lambda x: x["start"])
    return rows[:top]


def calendar_next() -> dict | None:
    now = kst.now()
    upcoming = [r for r in (_event_row(e) for e in _EVENTS)
                if datetime.fromisoformat(r["start"]) > now]
    upcoming.sort(key=lambda x: x["start"])
    return upcoming[0] if upcoming else None


def calendar_free(day: int = 0, minutes: int = 60) -> list[dict]:
    """빈 시간대 — Graph: POST /me/findMeetingTimes. 업무시간 내, 점심시간 제외."""
    busy = sorted(
        ((_at(e["d"], e["s"]), _at(e["d"], e["e"])) for e in _EVENTS if e["d"] == day),
        key=lambda x: x[0],
    )
    busy.append((_at(day, LUNCH_START), _at(day, LUNCH_END)))
    busy.sort(key=lambda x: x[0])
    slots, cursor = [], _at(day, WORK_START)
    end_of_day = _at(day, WORK_END)
    for s, e in busy:
        if s > cursor and (s - cursor).total_seconds() >= minutes * 60:
            slots.append((cursor, s))
        cursor = max(cursor, e)
    if end_of_day > cursor and (end_of_day - cursor).total_seconds() >= minutes * 60:
        slots.append((cursor, end_of_day))
    return [
        {"start": _iso(s), "end": _iso(e), "when": _rel_label(s),
         "timeRange": f"{s:%H:%M}~{e:%H:%M}",
         "minutes": int((e - s).total_seconds() // 60)}
        for s, e in slots
    ]


def calendar_add(subject: str, day: int = 0, start: str = "09:00", end: str = "10:00",
                 loc: str = "", online: bool = False, attendees=()) -> dict:
    """새 일정/회의 추가 — Graph: POST /me/events. day는 오늘 기준 오프셋. 세션 내 지속."""
    # Add a new event/meeting — Graph: POST /me/events. day is an offset from today. Session-persistent.
    att = [DEMO_USER] + [a for a in (attendees or []) if a and a != DEMO_USER]
    row = {"id": _next_id(_EVENTS, "e"), "subject": subject or "새 일정", "d": int(day),
           "s": start, "e": end, "loc": loc, "online": bool(online), "organizer": DEMO_USER,
           "att": att, "body": subject or ""}
    _EVENTS.append(row)
    _persist()
    return _event_row(row)


# ── 할 일 (14건: 미완료 9 / 완료 5) ──────────────────────────────────────────
# ── To-dos (14: 9 open / 5 done) ─────────────────────────────────────────────

TODO_LISTS = ({"id": "l1", "name": "업무"}, {"id": "l2", "name": "개인"}, {"id": "l3", "name": "PMO 공유"})

_TASKS = [
    # note/t: 업무 관리 패널 행 부제·시각(시안) / panel row subtitle & time (design)
    {"id": "t1", "list": "l1", "title": "QA 시나리오 검토", "due": 0, "done": None,
     "importance": "high", "assignee": "최지우", "mail": "m9", "note": "제품 리뷰 준비", "t": "10:42",
     "plan": ["기존 시나리오 12건 중 변경 기능 관련 4건 식별 (30분)", "신규 기능 2건 시나리오 초안 작성 (1시간)", "QA팀 검토 요청 전달 (10분)"],
     "plan_note": "14:00 회의 전 완료하려면 지금 시작을 권장합니다."},
    {"id": "t2", "list": "l1", "title": "주간 보고 초안 작성", "due": 0, "done": None,
     "importance": "normal", "assignee": "최지우", "mail": "m11", "note": "매주 수요일 반복", "t": "08:51",
     "plan": ["지난주 주요 성과 3건 정리 (20분)", "이번 주 이슈·리스크 기입 (20분)", "다음 주 계획 작성 후 제출 (15분)"],
     "plan_note": "수요일 17:00 제출 기한입니다."},
    {"id": "t3", "list": "l1", "title": "배포 체크리스트 점검", "due": 1, "done": None,
     "importance": "normal", "assignee": "최지우", "mail": "m12", "note": "금요일 배포 전", "t": "09:15",
     "plan": ["체크리스트 항목 18개 중 미확인 5개 점검 (40분)", "롤백 절차 확인 (15분)", "운영팀에 결과 공유 (10분)"],
     "plan_note": "금요일 배포 전날까지 완료가 필요합니다."},
    {"id": "t4", "list": "l1", "title": "3분기 예산안 v2 검토 의견 회신", "due": 2, "done": None,
     "importance": "high", "assignee": "최지우", "mail": "m1", "note": "CFO 요청 · 금요일 마감", "t": "10:45"},
    {"id": "t5", "list": "l1", "title": "A상사 계약서 v3 회신", "due": 1, "done": None,
     "importance": "normal", "assignee": "최지우", "mail": "m3", "note": "법무 검토 후 회신", "t": "09:20"},
    {"id": "t6", "list": "l2", "title": "보안 교육 이수", "due": 3, "done": None,
     "importance": "normal", "assignee": "최지우", "mail": "m2", "note": "목요일 13:00", "t": "08:55"},
    {"id": "t7", "list": "l3", "title": "9월 교육 참석 여부 회신", "due": 2, "done": None,
     "importance": "normal", "assignee": "최지우", "mail": "m6", "note": "HR팀 요청", "t": "09:16"},
    # 기한 초과 미완료 2건 — @todo 기한 초과 조회용(업무 관리 패널은 제외, 리뷰 확정) / overdue open tasks for @todo queries (hidden from the panel)
    {"id": "t8", "list": "l3", "title": "하반기 교육 수요 조사 회신", "due": -2, "done": None,
     "importance": "normal", "assignee": "최지우", "mail": None},
    {"id": "t9", "list": "l1", "title": "신규 모델 벤치마크 검토", "due": -1, "done": None,
     "importance": "normal", "assignee": "최지우", "mail": None},
    {"id": "t10", "list": "l1", "title": "지난주 주간보고 제출", "due": -1, "done": -1,
     "importance": "normal", "assignee": "최지우", "mail": None},
    {"id": "t11", "list": "l1", "title": "채용 공고 검토", "due": -2, "done": -2,
     "importance": "normal", "assignee": "강수아", "mail": None},
    {"id": "t12", "list": "l1", "title": "거래처 계약서 회신", "due": -3, "done": -3,
     "importance": "high", "assignee": "최지우", "mail": None},
    {"id": "t13", "list": "l3", "title": "스프린트 12 회고 정리", "due": -4, "done": -4,
     "importance": "normal", "assignee": "양도현", "mail": None},
    {"id": "t14", "list": "l2", "title": "연차 사용 계획 제출", "due": -6, "done": -5,
     "importance": "normal", "assignee": "최지우", "mail": None},
]

_LIST_NAME = {lst["id"]: lst["name"] for lst in TODO_LISTS}


def _task_row(t: dict) -> dict:
    due = _at(t["due"], "18:00") if t["due"] is not None else None
    done = _at(t["done"], "18:00") if t["done"] is not None else None
    overdue = bool(due and done is None and due < kst.now())
    return {
        "id": t["id"],
        "title": t["title"],
        "listId": t["list"],
        "listName": _LIST_NAME[t["list"]],
        "status": "completed" if done else "notStarted",
        "importance": t["importance"],
        "dueDateTime": _iso(due) if due else None,
        "due": _rel_label(due).split()[0] if due else "기한 없음",
        "isOverdue": overdue,
        # 달력 일수로 센다 — 시각 차이로 재면 어제 기한이 "0일 지남"으로 나온다
        # Counted in calendar days — a time-delta would render yesterday's deadline as "0 days overdue"
        "overdueDays": (_today() - due.replace(hour=0, minute=0)).days if overdue else 0,
        "assignee": _person(t["assignee"]),
        "linkedMailId": t["mail"],
        "completedDateTime": _iso(done) if done else None,
    }


def todo_list(status: str | None = None, due_within: int | None = None,
              overdue: bool = False, assignee: str | None = None, top: int = 20) -> list[dict]:
    """할 일 조회 — Graph: GET /me/todo/lists/{id}/tasks"""
    rows = []
    for t in _TASKS:
        r = _task_row(t)
        if status and r["status"] != status:
            continue
        if overdue and not r["isOverdue"]:
            continue
        if assignee and assignee not in r["assignee"]["name"]:
            continue
        if due_within is not None:
            # 기한 없는 항목과 완료분은 '기한 임박' 조회에서 제외
            # Undated and completed items are excluded from due-soon queries
            if t["due"] is None or t["due"] > due_within or r["status"] == "completed":
                continue
        rows.append(r)
    # 미완료 먼저, 그다음 기한순(없는 건 뒤) / open first, then by due date (undated last)
    rows.sort(key=lambda r: (r["status"] == "completed", r["dueDateTime"] or "9999"))
    return rows[:top]


def todo_add(title: str, list_id: str = "l1", due: int | None = None,
             assignee: str = DEMO_USER, importance: str = "normal") -> dict:
    """새 할 일 추가 — Graph: POST /me/todo/lists/{id}/tasks. due는 오프셋. 세션 내 지속."""
    # Add a new to-do — Graph: POST /me/todo/lists/{id}/tasks. due is an offset. Session-persistent.
    row = {"id": _next_id(_TASKS, "t"), "list": list_id if list_id in _LIST_NAME else "l1",
           "title": title or "새 할 일", "due": due, "done": None,
           "importance": importance if importance in ("high", "normal") else "normal",
           "assignee": assignee or DEMO_USER, "mail": None}
    _TASKS.append(row)
    _persist()
    return _task_row(row)


def todo_complete(target: str) -> dict | None:
    """할 일 완료 처리 — id·제목으로 미완료 태스크를 특정해 done=0(오늘). Graph: PATCH …/tasks/{id}.

    제목 매칭은 관대하게: 공백 무시 양방향 부분일치 → 토큰 과반 겹침 폴백('수요조사' vs '수요 조사 회신' 등 흡수)."""
    # Complete a to-do — resolve an open task by id/title, set done=0. Lenient title matching:
    # whitespace-insensitive bidirectional substring → majority token-overlap fallback.
    tgt = (target or "").strip()
    if not tgt:
        return None
    opens = [t for t in _TASKS if t["done"] is None]
    ntgt = tgt.replace(" ", "")
    # 1) id 정확 일치 / 2) 공백 무시 양방향 부분일치
    match = next((t for t in opens if t["id"] == tgt), None)
    if match is None:
        match = next((t for t in opens
                      if ntgt and (ntgt in t["title"].replace(" ", "")
                                   or t["title"].replace(" ", "") in ntgt)), None)
    # 3) 토큰 과반 겹침 폴백 / majority token-overlap fallback
    if match is None:
        toks = [w for w in tgt.split() if len(w) >= 2]
        if toks:
            best = max(opens, key=lambda t: sum(1 for w in toks if w in t["title"]), default=None)
            if best is not None and sum(1 for w in toks if w in best["title"]) > len(toks) / 2:
                match = best
    if match is None:
        return None
    match["done"] = 0
    _persist()
    return _task_row(match)


# ── SharePoint 문서 (24건: 폴더 6 / 파일 18) ─────────────────────────────────
# ── SharePoint items (24: 6 folders / 18 files) ──────────────────────────────

_FILES = (
    {"id": "f1", "kind": "folder", "name": "보고서", "path": "내 문서", "ext": "", "size": 0, "d": -1, "by": "최지우", "shared": False},
    {"id": "f2", "kind": "folder", "name": "프로젝트", "path": "내 문서", "ext": "", "size": 0, "d": -3, "by": "최지우", "shared": False},
    {"id": "f3", "kind": "folder", "name": "회의록", "path": "내 문서", "ext": "", "size": 0, "d": -2, "by": "최지우", "shared": False},
    {"id": "f4", "kind": "folder", "name": "경영지원", "path": "공유 문서", "ext": "", "size": 0, "d": -5, "by": "홍서연", "shared": True},
    {"id": "f5", "kind": "folder", "name": "팀 자료", "path": "공유 문서", "ext": "", "size": 0, "d": -8, "by": "윤지호", "shared": True},
    {"id": "f6", "kind": "folder", "name": "계약", "path": "공유 문서 > 경영지원", "ext": "", "size": 0, "d": -10, "by": "이서윤", "shared": True},
    {"id": "f7", "kind": "file", "name": "2026-07_경영보고서_초안.pdf", "path": "내 문서 > 보고서", "ext": "pdf", "size": 842_112, "d": -1, "by": "홍서연", "shared": True},
    {"id": "f8", "kind": "file", "name": "3분기_실적_집계.xlsx", "path": "내 문서 > 보고서", "ext": "xlsx", "size": 318_464, "d": 0, "by": "최지우", "shared": False},
    {"id": "f9", "kind": "file", "name": "모델_벤치마크_비교.xlsx", "path": "내 문서 > 프로젝트", "ext": "xlsx", "size": 231_424, "d": -3, "by": "양도현", "shared": True},
    # recent/site/t/sub: 업무 관리 패널 '최근 변경' 행(시안) / work-panel "recent changes" rows (design)
    {"id": "f10", "kind": "file", "name": "제품 로드맵_2026H2.pptx", "path": "내 문서 > 프로젝트", "ext": "pptx", "size": 1_284_096, "d": 0, "by": "김민준", "shared": True,
     "recent": True, "t": "10:42", "sub": "김민준 수정 · 제품기획 사이트", "site": "제품기획 사이트",
     "changes": ["슬라이드 8: 11월 릴리즈 범위에 AI 기능 추가", "슬라이드 12: 리소스 계획 표 수정 (개발 +2명)", "수정자: 김민준 · 오늘 11:34"],
     "summary": ["2026 하반기 로드맵: 3개 릴리즈 (9월/11월/1월)", "핵심 변경: AI 기능 통합이 11월 릴리즈로 이동", "마지막 수정: 김민준 · 오늘 11:34 (슬라이드 8, 12 변경)"]},
    {"id": "f23", "kind": "file", "name": "A상사 계약서_v3.docx", "path": "공유 문서 > 경영지원 > 계약", "ext": "docx", "size": 96_256, "d": 0, "by": "법무팀", "shared": True,
     "recent": True, "t": "08:51", "sub": "법무팀 공유 요청", "site": "법무 사이트", "pending_share": True,
     "changes": ["지급 조건: 45일 → 30일", "위약금 조항 신설 (계약금액의 5%)", "수정자: 법무팀 · 오늘 08:40"],
     "summary": ["A상사 공급 계약서 v3 — 수정 의견 반영본", "핵심 조건: 지급 30일, 위약금 5%, 계약 기간 1년", "법무팀 검토 완료, 공유 승인 대기"]},
    {"id": "f24", "kind": "file", "name": "Q3 실적 보고_초안.xlsx", "path": "내 문서 > 보고서", "ext": "xlsx", "size": 318_464, "d": -1, "by": "최지우", "shared": False,
     "recent": True, "t": "어제", "sub": "본인 업로드 · 재무 사이트", "site": "재무 사이트",
     "changes": ["시트 '요약': 3분기 매출·영업이익 집계 추가", "시트 '부서별': 비용 집행률 열 추가", "수정자: 최지우 · 어제 17:10"],
     "summary": ["3분기 실적 보고 초안 — 매출 16,744천 달러, 영업이익 2,657천 달러 전망", "부서별 비용 집행률 포함", "검토 후 재무 사이트에 최종본 업로드 예정"]},
    {"id": "f11", "kind": "file", "name": "주간회의록_08월.docx", "path": "내 문서 > 회의록", "ext": "docx", "size": 74_240, "d": 0, "by": "최지우", "shared": False},
    {"id": "f12", "kind": "file", "name": "스프린트12_회고.docx", "path": "내 문서 > 회의록", "ext": "docx", "size": 52_736, "d": -4, "by": "양도현", "shared": False},
    {"id": "f13", "kind": "file", "name": "8월_예산_집행현황.xlsx", "path": "공유 문서 > 경영지원", "ext": "xlsx", "size": 196_608, "d": -6, "by": "이서윤", "shared": True},
    {"id": "f14", "kind": "file", "name": "인사규정_v3.pdf", "path": "공유 문서 > 경영지원", "ext": "pdf", "size": 623_616, "d": -7, "by": "정하준", "shared": True},
    {"id": "f15", "kind": "file", "name": "파트너코프_계약서_2025.pdf", "path": "공유 문서 > 경영지원 > 계약", "ext": "pdf", "size": 1_048_576, "d": -10, "by": "이서윤", "shared": True},
    {"id": "f16", "kind": "file", "name": "표준계약서_양식.docx", "path": "공유 문서 > 경영지원 > 계약", "ext": "docx", "size": 88_064, "d": -14, "by": "이서윤", "shared": True},
    {"id": "f17", "kind": "file", "name": "품질지표_대시보드_정의서.pdf", "path": "공유 문서 > 팀 자료", "ext": "pdf", "size": 412_672, "d": -5, "by": "문가은", "shared": True},
    {"id": "f18", "kind": "file", "name": "보안교육_자료.pptx", "path": "공유 문서 > 팀 자료", "ext": "pptx", "size": 2_097_152, "d": -8, "by": "고서진", "shared": True},
    {"id": "f19", "kind": "file", "name": "하반기_교육과정_안내.pdf", "path": "공유 문서 > 팀 자료", "ext": "pdf", "size": 274_432, "d": -4, "by": "정하준", "shared": True},
    {"id": "f20", "kind": "file", "name": "영업_파이프라인_08월.xlsx", "path": "내 문서 > 보고서", "ext": "xlsx", "size": 156_672, "d": -3, "by": "최지우", "shared": False},
    {"id": "f21", "kind": "file", "name": "채용공고_AI파트.docx", "path": "공유 문서 > 경영지원", "ext": "docx", "size": 43_008, "d": -2, "by": "강수아", "shared": True},
    {"id": "f22", "kind": "file", "name": "서버점검_안내문.docx", "path": "공유 문서 > 팀 자료", "ext": "docx", "size": 31_744, "d": -2, "by": "고서진", "shared": True},
)


def _file_row(f: dict) -> dict:
    dt = _at(f["d"], "16:00")
    return {
        "id": f["id"],
        "name": f["name"],
        "kind": f["kind"],
        "path": f["path"],
        "ext": f["ext"],
        "size": f["size"],
        "sizeLabel": _size_label(f["size"]) if f["kind"] == "file" else "",
        "lastModifiedDateTime": _iso(dt),
        "when": _rel_label(dt).split()[0],
        "lastModifiedBy": _person(f["by"]),
        "isShared": f["shared"],
    }


def _size_label(n: int) -> str:
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f}MB"
    if n >= 1024:
        return f"{n // 1024}KB"
    return f"{n}B"


def files_list(q: str | None = None, path: str | None = None,
               shared_only: bool = False, top: int = 12) -> list[dict]:
    """문서 조회 — Graph: GET /me/drive/root/search(q=) 또는 :/{path}:/children"""
    rows = []
    for f in _FILES:
        if q and q not in f["name"]:
            continue
        if path and f["path"] != path:
            continue
        if shared_only and not f["shared"]:
            continue
        rows.append(_file_row(f))
    # 폴더 먼저, 각 그룹 안에서는 최신 수정순 / folders first, most recently modified within each group
    rows.sort(key=lambda r: (r["kind"] != "folder", _neg_iso(r["lastModifiedDateTime"])))
    return rows[:top]


def _neg_iso(s: str) -> tuple:
    """ISO 문자열을 내림차순 정렬 키로 — 오름차순 sort 안에서 최신순을 만든다."""
    # Turn an ISO string into a descending sort key so an ascending sort yields newest-first.
    return tuple(-ord(c) for c in s)


# ── Teams (채팅 7 / 메시지 24 / 채널) ────────────────────────────────────────
# ── Teams (7 chats / 24 messages / channels) ─────────────────────────────────

# Teams 시드·조회·전송은 제거(2026-08-28 사용자 지시 — Graph Teams API가 MFA를 요구해 실연동 불가).
# Teams seeds/reads/sends removed (user decision 2026-08-28 — the Graph Teams API requires MFA).


# ── 재시작 내구성(2026-08-28) — 뮤테이션(_MAIL·_EVENTS·_TASKS)을 SQLite gw_state에 영속화 ──
# 종전 "무DB·재시작=리셋" 설계를 사용자 지시로 갱신: 데모 중 재시작해도 보낸 메일·생성 일정·완료
# 할 일이 유지된다. 리셋이 필요하면 db.gw_state_clear() 후 재시작. 접근자·행 변환은 무변경(리스트
# 내용만 통째 교체 — 모듈 참조(S._MAIL 등)가 살아 있도록 in-place 치환).
# ── Restart durability (2026-08-28) — mutations (_MAIL/_EVENTS/_TASKS) persist to SQLite gw_state ──
# Updates the old "no-DB, restart = reset" design per user decision: sent mail / created events /
# completed to-dos now survive restarts. To reset, call db.gw_state_clear() and restart. Accessors and
# row builders are unchanged (list CONTENTS are swapped in place so module references like S._MAIL stay valid).

def _persist() -> None:
    """현재 시드 상태 저장 — 뮤테이터가 상태를 바꿀 때마다 호출(실패는 조용히 무시 — 데모 지속성 편의)."""
    # Persist the current seed state — called by every mutator (failures ignored quietly — a convenience).
    try:
        from app import db   # 지연 임포트(순환 방지) / lazy (avoid cycles)
        db.gw_state_set({"mail": _MAIL, "events": _EVENTS, "tasks": _TASKS})
    except Exception:  # noqa: BLE001
        pass


def _restore() -> None:
    """저장된 시드 상태 복원(있으면) — 리스트 내용을 통째로 교체(참조 유지)."""
    # Restore the persisted seed state (if any) — replace list contents wholesale (references preserved).
    try:
        from app import db   # 지연 임포트 / lazy
        saved = db.gw_state_get()
    except Exception:  # noqa: BLE001
        return
    if not isinstance(saved, dict):
        return
    for lst, key in ((_MAIL, "mail"), (_EVENTS, "events"), (_TASKS, "tasks")):
        rows = saved.get(key)
        if isinstance(rows, list) and rows:
            lst[:] = rows


_restore()
