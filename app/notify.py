"""예약 알림 실발송 — 컬렉션 예약 실행이 끝나면 예약 소유자 본인("나")에게 메일 1통을 보낸다(2026-09-02, 사용자 최종 확정).

- 다중 알림(제목·받는 사람·머리말 행 목록)은 폐지. 예약마다 "메일로 알림 보내기" 토글(notify_email) 하나뿐이며,
  켜져 있으면 실행 마감 후 무조건 소유자에게 1통. 제목은 DEFAULT_SUBJECT 치환, 본문은 평문(머리말 없음).
- 백엔드(SCHED_MAIL_BACKEND): 'outlook'(기본) — 이 PC 세션에 로그인된 **클래식 Outlook 데스크톱**을 COM(pywin32)으로
  자동화해 실제 발송. 실패(새 Outlook·미설치·pywin32 없음·COM 오류)면 앱 내 가상 메일함(smart_seed.mail_send)으로
  폴백하고 사유를 기록한다(backend='virtual(fallback)'). 'virtual' — 가상 메일함만. 'none' — 발송 안 함.
- 수신자 해석(resolve_me): owner 가 숫자(구성원 no) → 조직도 email. '' (슈퍼관리자) → env SCHED_MAIL_TO(쉼표 분리)가
  있으면 그 값, 없으면 특수 토큰 'me'. 'me' 는 발송 백엔드가 치환한다 — Outlook 은 현재 로그인 계정 주소
  (PrimarySmtpAddress → CurrentUser.Address, 둘 다 없으면 항목 제거), 가상 메일함은 smart_seed.email_of(DEMO_USER).
- 제목 치환자: {예약 이름} {컬렉션} {날짜}. 본문 = 실행 문구 + 결과 문구 + 결과 채팅 링크 + 답변 앞 300자.
- send_mail 은 **동기** 함수이며 어떤 경우에도 예외를 던지지 않는다(호출자 schedules 가 to_thread + wait_for 로 감싼다).
- env: SCHED_BASE_URL(결과 채팅 링크의 기준, 기본 http://localhost:8000) · SCHED_MAIL_BACKEND(outlook|virtual|none) ·
  SCHED_MAIL_TO(슈퍼관리자 예약의 수신자 — 비면 'me').
"""
# Scheduled-run notification delivery — after a collection schedule finishes, ONE mail goes to the schedule owner
# ("me") (2026-09-02, final user decision).
#
# - Multi-notify rows (subject / recipients / preface) are retired. Each schedule has a single "email me when it
#   runs" toggle (notify_email); when on, exactly one mail is sent to the owner after the run closes. Subject =
#   DEFAULT_SUBJECT filled in; body is plain text (no preface).
# - Backend (SCHED_MAIL_BACKEND): 'outlook' (default) — automates the CLASSIC Outlook desktop app logged in on this
#   PC session via COM (pywin32) and really sends. On failure (new Outlook, not installed, pywin32 missing, COM
#   error) it falls back to the in-app virtual mailbox (smart_seed.mail_send) and records the reason
#   (backend='virtual(fallback)'). 'virtual' — virtual mailbox only. 'none' — nothing is sent.
# - Recipient resolution (resolve_me): a numeric owner (member no) → that member's org-chart email. '' (super admin)
#   → env SCHED_MAIL_TO (comma-separated) when set, else the special token 'me'. 'me' is substituted by the delivery
#   backend — Outlook uses the logged-in account address (PrimarySmtpAddress → CurrentUser.Address; dropped when
#   neither exists), the virtual mailbox uses smart_seed.email_of(DEMO_USER).
# - Subject placeholders: {예약 이름} {컬렉션} {날짜}. Body = run line + result line + result-chat link + first 300
#   chars of the answer.
# - send_mail is SYNCHRONOUS and never raises (the caller in schedules wraps it in to_thread + wait_for).
# - env: SCHED_BASE_URL (base of the result-chat link, default http://localhost:8000) · SCHED_MAIL_BACKEND ·
#   SCHED_MAIL_TO (recipients for a super-admin schedule — empty → 'me').

import logging
import os
from datetime import datetime

from app import kst

# 알림 시각도 예약과 같은 KST(+09:00) 벽시계 기준(2026-09-03, 2026-10-06 부터 공통 도우미 app.kst 의 별칭)
# Notification timestamps use the same fixed KST wall clock (aliases of the shared app.kst helper since 2026-10-06)
_KST = kst.KST


def _now_kst() -> datetime:
    return kst.now()

logger = logging.getLogger("ai365.scheduler")

BACKENDS = ("outlook", "onedrive", "virtual", "none")
# onedrive 백엔드(2026-09-03, **대안** — 새 Outlook 환경·인프라 승인 없이 회사 계정 명의 발송; 기본은 outlook): 실행 결과를 OneDrive 동기화
# 폴더(기본 <OneDriveCommercial|OneDrive>\Ai365\outbox)에 "<제목>.txt" 로 떨어뜨리면, 사용자가 만든 Power Automate 흐름
# ("OneDrive for Business — 파일이 만들어지면" → "메일 보내기(V2)")이 파일 이름을 제목·파일 내용을 본문으로 본인에게 발송한다.
# onedrive backend (2026-09-03, user choice — company-account delivery under new Outlook without any IT approval): the run
# result is dropped into the OneDrive sync folder (default <OneDriveCommercial|OneDrive>\Ai365\outbox) as "<subject>.txt";
# the user's Power Automate flow ("OneDrive for Business — When a file is created" → "Send an email (V2)") mails it
# (file name = subject, file content = body) to themselves.
OUTBOX_SUBDIR = ("Ai365", "outbox")
STAGING_SUBDIR = ("Ai365", ".staging")   # 같은 볼륨의 임시 폴더 → os.replace 로 원자적 이동(부분 파일 트리거 방지) / same-volume staging → atomic move
ME = "me"                   # 수신자 특수 토큰 — 백엔드가 현재 계정 주소로 치환 / recipient token replaced by the backend with the current account
MAX_TO = 20                 # SCHED_MAIL_TO 해석 후 수신자 상한 / recipient cap after SCHED_MAIL_TO parsing
PREVIEW_CAP = 300           # 본문에 싣는 답변 앞부분 길이 / answer excerpt length in the body
DEFAULT_SUBJECT = "[Ai365] {예약 이름} 실행 결과 · {날짜}"
SIGNATURE = "— Ai365 예약 알림"

# 결과 코드 → 본문 결과 문구(result 는 'ok'/'doc'/'needs_input'/'429'/'error:…') / result code → body line
RESULT_LINES = {
    "ok": "아래는 답변 앞부분입니다.",
    "doc": "문서 파일이 함께 생성되었습니다.",
    "needs_input": "확인이 필요합니다 — 채팅을 열어 이어가 주세요.",
    "429": "AI 호출량이 몰려 이번 실행이 미뤄졌습니다. 채팅을 열어 같은 요청을 다시 보내 주세요.",
    "error": "실행 중 오류가 발생했습니다.",
}


def base_url() -> str:
    """SCHED_BASE_URL — 끝의 '/' 제거, 비면 기본값."""
    # SCHED_BASE_URL — trailing '/' stripped; default when empty.
    return (os.getenv("SCHED_BASE_URL", "") or "http://localhost:8000").strip().rstrip("/") or "http://localhost:8000"


def mail_backend() -> str:
    """SCHED_MAIL_BACKEND — outlook(기본)|virtual|none. 알 수 없는 값은 outlook."""
    # SCHED_MAIL_BACKEND — outlook (default) | virtual | none; unknown values → outlook.
    v = (os.getenv("SCHED_MAIL_BACKEND", "") or "outlook").strip().lower()
    return v if v in BACKENDS else "outlook"


# ─────────────────────────────────────────────────────────────────────────────
# 수신자 해석 — 예약 소유자 본인("나")
# Recipient resolution — the schedule owner ("me")
# ─────────────────────────────────────────────────────────────────────────────

def _members() -> list[dict]:
    try:
        from app import access   # 지연 임포트 / lazy import
        return access.list_members()
    except Exception as e:  # noqa: BLE001
        logger.warning("알림 수신자 해석 — 구성원 조회 실패: %s", e)
        return []


def _dedupe(items: list[str], cap: int = MAX_TO) -> list[str]:
    """트림·빈값 제거·대소문자 무시 중복 제거·상한. 'me' 토큰은 그대로 통과."""
    # Trim, drop empties, case-insensitive de-dup, cap. The 'me' token passes through unchanged.
    out: list[str] = []
    seen: set[str] = set()
    for x in items:
        e = str(x or "").strip()
        if not e or e.lower() in seen:
            continue
        seen.add(e.lower())
        out.append(e)
    return out[:cap]


def resolve_me(owner: str) -> list[str]:
    """예약 소유자 → 수신자 목록. owner 가 숫자(구성원 no) 면 그 구성원의 조직도 email(퇴직자도 소유자면 그대로; 이메일이
    없으면 []). '' (슈퍼관리자) 면 env SCHED_MAIL_TO(쉼표 분리)가 있으면 그 값, 없으면 ['me'](백엔드가 현재 계정으로 치환)."""
    # Schedule owner → recipients. A numeric owner (member no) → that member's org-chart email (retired owners
    # included; [] when it has no email). '' (super admin) → env SCHED_MAIL_TO (comma-separated) when set, else
    # ['me'] (the backend substitutes the current account).
    owner = (owner or "").strip()
    if owner.isdigit():
        m = next((x for x in _members() if str(x.get("no")) == owner), None)
        e = str((m or {}).get("email") or "").strip()
        return [e] if "@" in e else []
    env_to = (os.getenv("SCHED_MAIL_TO", "") or "").strip()
    if env_to:
        out = _dedupe([p for p in env_to.split(",")])
        if out:
            return out
    return [ME]


# ─────────────────────────────────────────────────────────────────────────────
# 메일 조립
# Mail composition
# ─────────────────────────────────────────────────────────────────────────────

def _sched_name(sched: dict) -> str:
    name = str(sched.get("name") or "").strip()
    return name or str(sched.get("message") or "").strip()[:30]


def _fill(tpl: str, name: str, coll_name: str, when: datetime) -> str:
    return (tpl.replace("{예약 이름}", name).replace("{컬렉션}", coll_name)
            .replace("{날짜}", f"{when.month}/{when.day}"))


def _result_line(result: str) -> str:
    r = (result or "").strip()
    key = "error" if r.startswith("error") else r
    return RESULT_LINES.get(key, RESULT_LINES["error"])


def build_mail(sched: dict, coll_name: str, chat_id: str | None, result: str, answer_preview: str,
               when: datetime | None = None) -> tuple[str, str]:
    """(제목, 평문 본문). 제목 = DEFAULT_SUBJECT 치환({예약 이름}·{컬렉션}·{날짜}).
    본문 = 실행 문구 + 결과 문구 + [결과 채팅 링크] + 빈 줄 + 답변 앞 300자 + 서명."""
    # (subject, plain body). Subject = DEFAULT_SUBJECT with placeholders filled.
    # Body = run line + result line + [result chat link] + blank + answer excerpt + signature.
    when = when or _now_kst()
    name = _sched_name(sched)
    coll_name = (coll_name or "").strip()   # 컬렉션 없는 예약(6차)은 '' / '' for a collection-less schedule (round 6)
    subject = _fill(DEFAULT_SUBJECT, name, coll_name or "(컬렉션 없음)", when).strip()
    lines: list[str] = []
    lines.append((f"{coll_name} 컬렉션의 " if coll_name else "")
                 + f"예약 '{name}'이 {when.month}월 {when.day}일 {when:%H:%M}에 실행되었습니다.")
    lines.append(_result_line(result))
    if chat_id:
        owner = str(sched.get("owner") or "").strip()
        link = f"{base_url()}/?chat={chat_id}" + (f"&as={owner}" if owner else "")
        lines.append("결과 채팅: " + link)
    preview = (answer_preview or "").strip()[:PREVIEW_CAP]
    if preview:
        lines.append("")
        lines.append(preview)
    lines.append("")
    lines.append("")
    lines.append(SIGNATURE)
    return subject, "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 발송
# Delivery
# ─────────────────────────────────────────────────────────────────────────────

def _outlook_me(app) -> str:
    """Outlook 현재 로그인 계정의 주소 — Exchange 면 PrimarySmtpAddress, 아니면 CurrentUser.Address. 둘 다 실패면 ''."""
    # Address of the logged-in Outlook account — PrimarySmtpAddress on Exchange, else CurrentUser.Address; '' if both fail.
    try:
        entry = app.Session.CurrentUser.AddressEntry
        try:
            exu = entry.GetExchangeUser()
            addr = str(getattr(exu, "PrimarySmtpAddress", "") or "").strip() if exu is not None else ""
        except Exception:  # noqa: BLE001
            addr = ""
        if "@" in addr:
            return addr
    except Exception:  # noqa: BLE001
        pass
    try:
        addr = str(app.Session.CurrentUser.Address or "").strip()
        return addr if "@" in addr else ""
    except Exception:  # noqa: BLE001
        return ""


def _substitute_me(to: list[str], me_addr: str) -> list[str]:
    """'me' 토큰 → me_addr 치환(비면 항목 제거). 순서 유지·중복 제거."""
    # Replace the 'me' token with me_addr (dropped when empty). Order kept, de-duplicated.
    return _dedupe([(me_addr if x == ME else x) for x in to if not (x == ME and not me_addr)])


def _send_outlook(to: list[str], subject: str, body: str) -> None:
    """클래식 Outlook 데스크톱 COM 발송(동기·블로킹). pywin32 미설치면 ImportError, 새 Outlook·미설치·오류는 COM 예외 —
    모두 호출자(send_mail)가 잡는다. 스레드에서 호출되므로 CoInitialize/CoUninitialize 를 쌍으로 맞춘다.
    to 의 'me' 는 현재 로그인 계정 주소로 치환(주소를 못 얻으면 제거 — 수신자가 비면 ValueError → 폴백)."""
    # Classic Outlook desktop COM send (sync, blocking). pywin32 missing → ImportError; new Outlook / not installed /
    # errors → COM exceptions — all caught by send_mail. Called on a thread, so CoInitialize/CoUninitialize are paired.
    # 'me' in `to` becomes the logged-in account address (dropped when unavailable; no recipients left → ValueError → fallback).
    import pythoncom            # noqa: PLC0415 — 선택 의존성 / optional dependency
    import win32com.client      # noqa: PLC0415

    def _inner() -> None:
        # COM 프록시(app/mail)는 이 내부 함수가 반환되며 해제된다 — CoUninitialize 보다 먼저 Release 되도록(리뷰 지적)
        # The COM proxies (app/mail) are released when this inner function returns — before CoUninitialize (review fix)
        app = win32com.client.Dispatch("Outlook.Application")
        mail = None
        try:
            rcpts = _substitute_me(to, _outlook_me(app)) if ME in to else list(to)
            if not rcpts:
                raise ValueError("현재 Outlook 계정 주소를 얻지 못했습니다 / could not resolve the current Outlook address")
            mail = app.CreateItem(0)   # 0 = olMailItem
            mail.To = "; ".join(rcpts)
            mail.Subject = subject
            mail.Body = body
            mail.Send()
        finally:
            mail = None
            app = None

    pythoncom.CoInitialize()
    try:
        _inner()
    finally:
        pythoncom.CoUninitialize()


def outbox_dir() -> str:
    """OneDrive 발송함 폴더 — env SCHED_MAIL_OUTBOX 가 있으면 그 경로, 없으면 OneDriveCommercial → OneDrive 환경변수 아래
    Ai365\\outbox. 둘 다 없으면 ''(→ 폴백)."""
    # OneDrive outbox folder — env SCHED_MAIL_OUTBOX when set, else Ai365\outbox under the OneDriveCommercial → OneDrive
    # environment variable. '' when neither exists (→ fallback).
    custom = (os.getenv("SCHED_MAIL_OUTBOX", "") or "").strip()
    if custom:
        return custom
    root = (os.getenv("OneDriveCommercial", "") or os.getenv("OneDrive", "") or "").strip()
    return os.path.join(root, *OUTBOX_SUBDIR) if root else ""


def _safe_filename(s: str, cap: int = 100) -> str:
    """파일 이름에 못 쓰는 문자(\\ / : * ? " < > | 제어문자)를 '-' 로, 공백 정리, 길이 상한."""
    # Replace characters not allowed in file names with '-', collapse whitespace, cap the length.
    out = "".join("-" if (ch in '\\/:*?"<>|' or ord(ch) < 32) else ch for ch in s)
    out = " ".join(out.split()).strip(" .")
    return (out[:cap].rstrip(" .")) or "Ai365 알림"


def _send_onedrive(to: list[str], subject: str, body: str) -> str:
    """OneDrive 발송함에 "<제목>_<시각>.txt" 를 원자적으로 생성한다(스테이징 폴더에 쓴 뒤 os.replace). 반환=생성 경로.
    본문은 UTF-8(BOM 없음) 평문 — Power Automate 흐름이 파일 이름을 제목, 내용을 본문으로 발송한다. 수신자는 흐름에
    고정된 본인 주소이므로 to 는 본문 끝에 참고로만 적는다."""
    # Create "<subject>_<time>.txt" atomically in the OneDrive outbox (write to staging, then os.replace). Returns the path.
    # Body is plain UTF-8 (no BOM) — the Power Automate flow mails it (file name = subject, content = body). The recipient
    # is fixed in the flow (the owner's own address), so `to` is only appended as a reference line.
    root = outbox_dir()
    if not root:
        raise RuntimeError("OneDrive 폴더를 찾지 못했습니다(OneDrive/OneDriveCommercial 환경변수·SCHED_MAIL_OUTBOX 없음) / OneDrive folder not found")
    base = os.path.dirname(root) if os.path.basename(root).lower() == OUTBOX_SUBDIR[-1] else root
    staging = os.path.join(base, STAGING_SUBDIR[-1]) if base.lower().endswith(OUTBOX_SUBDIR[0].lower()) else os.path.join(root, ".staging")
    os.makedirs(root, exist_ok=True)
    os.makedirs(staging, exist_ok=True)
    stamp = _now_kst().strftime("%Y%m%d-%H%M%S")
    name = f"{_safe_filename(subject)}_{stamp}.txt"
    tmp = os.path.join(staging, name)
    final = os.path.join(root, name)
    rcpt_note = ", ".join("나" if x == ME else x for x in to)
    text = body.rstrip() + f"\n\n(수신자: {rcpt_note})\n"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, final)
    return final


def _send_virtual(to: list[str], subject: str, body: str) -> None:
    """앱 내 가상 메일함 발송 — 'me' 는 smart_seed.email_of(DEMO_USER) 로 치환."""
    # In-app virtual mailbox send — 'me' becomes smart_seed.email_of(DEMO_USER).
    from app import smart_seed   # 지연 임포트 / lazy import
    rcpts = list(to)
    if ME in rcpts:
        me_addr = ""
        try:
            e = smart_seed.email_of(smart_seed.DEMO_USER)
            me_addr = e if "@" in e else ""
        except Exception as ex:  # noqa: BLE001
            logger.warning("알림 수신자 해석 — 데모 계정 이메일 조회 실패: %s", ex)
        rcpts = _substitute_me(rcpts, me_addr or smart_seed.DEMO_USER)
    smart_seed.mail_send(rcpts, subject, body)


def _err(e: BaseException) -> str:
    s = f"{type(e).__name__}: {e}".strip()
    return s[:300]


def send_mail(to: list[str], subject: str, body: str, backend: str | None = None) -> dict:
    """메일 발송 — {ok, backend, error}. backend 생략 시 env. 'outlook' 실패는 error 를 기록한 뒤 가상 메일함으로 폴백
    (backend='virtual(fallback)'); 폴백도 실패하면 ok=False 에 두 사유를 잇는다. 'none' 은 {ok:False, backend:'none',
    error:'disabled'}. 수신자가 비면 ok=False 'no recipients'. 어떤 경우에도 예외를 던지지 않는다."""
    # Send a mail — {ok, backend, error}. backend defaults to env. An 'outlook' failure records the error and falls
    # back to the virtual mailbox (backend='virtual(fallback)'); if that fails too, ok=False with both reasons.
    # 'none' → {ok:False, backend:'none', error:'disabled'}. Empty recipients → ok=False 'no recipients'. Never raises.
    be = backend if backend in BACKENDS else mail_backend()
    to = [str(x).strip() for x in (to or []) if str(x or "").strip()]
    if be == "none":
        return {"ok": False, "backend": "none", "error": "disabled"}
    if not to:
        return {"ok": False, "backend": be, "error": "no recipients"}
    if be in ("outlook", "onedrive"):
        try:
            if be == "outlook":
                _send_outlook(to, subject, body)
            else:
                path = _send_onedrive(to, subject, body)
                logger.info("알림 OneDrive 발송함 기록: %s", path)
            return {"ok": True, "backend": be, "error": ""}
        except ImportError as e:
            first = "pywin32 미설치 / pywin32 not installed: " + _err(e)
        except Exception as e:  # noqa: BLE001 — COM 오류·새 Outlook·폴더 오류 등 전부 폴백 / every failure falls back
            first = _err(e)
        logger.warning("알림 %s 발송 실패 — 가상 메일함으로 폴백: %s", be, first)
        try:
            _send_virtual(to, subject, body)
            return {"ok": True, "backend": "virtual(fallback)", "error": first}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "backend": "virtual(fallback)", "error": first + " | virtual: " + _err(e)}
    try:
        _send_virtual(to, subject, body)
        return {"ok": True, "backend": "virtual", "error": ""}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "backend": "virtual", "error": _err(e)}
