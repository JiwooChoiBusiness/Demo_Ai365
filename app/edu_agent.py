"""교육 에이전트 실 스토어 — 업무 자동화 실구축 1차 (2026-08-24, 사용자 확정 "자체 구축").

실물 API가 없어 데모 SPA(frontend/ai365-edu-agent.html)의 in-page DB·판정 엔진을 서버로 이식한다.
리소스 관리의 API 레지스트리(RM_EDU_API 12종)가 엔드포인트 스펙이고, 여기는 스토어·로직 계층
(라우트는 edu_api.py). SPA의 evaluate()를 단순화 이식: 신뢰도 임계 미달→검토(R01), L1 자유
이용→적재, L2 조건 대조(비상업·재배포 × 테넌트 이용 목적)→적재/보류(R06/R07), L3 표기
부재→검토(보호가 기본값, R08), L4 명시적 제한→권리 원장 대조(3용도 충족=적재 R10 · 용도
불충족=보류 R11 · 계약 없음=보류 R09), L5 접근 통제→문서 미저장·감사 기록만(R13=법무 확정 대기).

시드는 SPA SEED 14건(레벨·신뢰도·신호·스냅샷 그대로) + 업로드 대기 1건 + 법무 확정 대기 1건 —
KPI 정합: 수집 15 · 적재 6 · 검토 4 · 대기 1 · 보류 4, L5 1건은 감사 로그만. 액션(검토 판정·재큐)은
실제 상태 전이 + 감사 추가로 영속된다.

Education-agent store — automation real-build round 1. The demo SPA's in-page DB and rules engine
are ported server-side; the RM registry (12 endpoints) is the spec (routes in edu_api.py). Review
verdicts and requeues are real, persisted transitions with audit records. Seed matches the SPA KPIs
(collected 15 / uploaded 6 / review 4 / staged 1 / held 4; the L5 item exists only in the audit log).
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from app import db, kst

logger = logging.getLogger("ai365.edu_agent")

DOC_STATES = ("uploaded", "staged", "review", "held", "rejected")
CONFIDENCE_THRESHOLD = 70
USAGE = {"commercial": False, "redistribute": False, "external": False}   # 테넌트 이용 목적 / tenant usage
LEVEL_ACTIONS = {"1": "auto", "2": "conditional"}
UPLOAD_USES = ("internal", "ai", "education")   # 적재 3용도 — RAG·Viva 동시 전파라 부분 적재 불가

STD_CATALOG = [
    {"id": "KOGL-1", "name": "공공누리 제1유형(출처표시)", "level": 1, "verdict": "자유 이용 — 자동 적재"},
    {"id": "CC-BY-NC-4.0", "name": "CC BY-NC 4.0", "level": 2, "verdict": "비상업 조건부 — 법무 확정 대기(R13)"},
    {"id": "NO-MARKING", "name": "표기 없음", "level": 3, "verdict": "보호가 기본값 — 사람 검토(R08)"},
    {"id": "PUBLISHER-SUB", "name": "구독·유료 저작물", "level": 4, "verdict": "명시적 제한 — 권리 원장 대조"},
]

# 법무 확정된 표준 카탈로그 — 확정되면 R13 게이트를 통과해 조건부 적재 경로로 간다(현재 빈 집합)
# Legally confirmed standard catalogs — once added, R13 documents re-enter the conditional path
LEGAL_CONFIRMED: set[str] = set()

FOLDERS = ["HVAC > 냉난방기", "기술매뉴얼 > 보일러", "HVAC > 성능·시험", "규제·인증 > 국내", "시장·경쟁 > 리포트"]
CAT_MAP = {"HVAC·공조": "HVAC > 냉난방기", "난방·보일러": "기술매뉴얼 > 보일러", "냉방·냉동": "HVAC > 냉난방기",
           "규제·정책": "규제·인증 > 국내", "표준·인증": "HVAC > 성능·시험", "기타": "시장·경쟁 > 리포트"}


def init_edu_agent() -> None:
    with db._conn() as conn:  # noqa: SLF001 — 프로젝트 관례 / project convention
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS edu_docs(
                id TEXT PRIMARY KEY, time TEXT, type TEXT, title TEXT, source TEXT, url TEXT,
                lic TEXT, lv INTEGER, conf INTEGER, cond TEXT, summary TEXT, evidence TEXT,
                signals TEXT, snap_exc TEXT, snap_mark TEXT, aud TEXT, contact TEXT, cat TEXT,
                state TEXT, applied_lic TEXT, eval_why TEXT, rules TEXT, sp_name TEXT,
                uploaded_at TEXT, history TEXT
            );
            CREATE TABLE IF NOT EXISTS edu_audit(
                id INTEGER PRIMARY KEY AUTOINCREMENT, t TEXT, doc TEXT, move TEXT, by TEXT, note TEXT
            );
            CREATE TABLE IF NOT EXISTS edu_uploads(
                id INTEGER PRIMARY KEY AUTOINCREMENT, t TEXT, doc TEXT, name TEXT, hash TEXT, lic TEXT, folder TEXT
            );
            CREATE TABLE IF NOT EXISTS edu_licenses(
                id TEXT PRIMARY KEY, name TEXT, scope TEXT, uses TEXT, start TEXT, end TEXT,
                obligations TEXT, contact TEXT, file TEXT, revoked INTEGER, survival INTEGER
            );
            CREATE TABLE IF NOT EXISTS edu_learn_deadlines(
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, dept TEXT, course TEXT, label TEXT, overdue INTEGER
            );
            CREATE TABLE IF NOT EXISTS edu_learn_depts(
                name TEXT PRIMARY KEY, pct INTEGER
            );
            """
        )
        if conn.execute("SELECT COUNT(*) FROM edu_docs").fetchone()[0] == 0:
            # 자가치유 리시드(리뷰 확정): 문서만 비운 부분 리시드에서도 고정 PK 충돌 없이 전체를
            # 일관 상태로 재시드 — 연관 테이블을 함께 비운다.
            # Self-healing reseed: clear the fixed-PK companion tables so a partial wipe reseeds cleanly.
            for t in ("edu_audit", "edu_uploads", "edu_licenses", "edu_learn_deadlines", "edu_learn_depts"):
                conn.execute(f"DELETE FROM {t}")  # noqa: S608 — 고정 테이블명 목록 / fixed table list
            _seed(conn)


# ─────────────────────────────────────────────────────────────────────────────
# 판정 엔진 (SPA evaluate() 이식)
# Rules engine (ported from the SPA)
# ─────────────────────────────────────────────────────────────────────────────

def _lic_valid(lic: dict) -> bool:
    if lic.get("revoked"):
        return False
    try:
        return date.fromisoformat(lic["end"]) >= kst.today()
    except (KeyError, ValueError):
        return False


def _lic_for(doc: dict, licenses: list[dict]) -> tuple[dict | None, list[str]]:
    """scope 문자열 매칭으로 문서에 걸리는 유효 계약과 3용도 미충족 목록을 돌려준다."""
    for lic in licenses:
        if not _lic_valid(lic):
            continue
        if lic["scope"] and lic["scope"] in (doc.get("source") or ""):
            uses = json.loads(lic["uses"]) if isinstance(lic["uses"], str) else lic["uses"]
            gap = [u for u in UPLOAD_USES if not uses.get(u)]
            return lic, gap
    return None, []


def evaluate(doc: dict, licenses: list[dict]) -> dict:
    """→ {route, rules[], why, lic?} — 기본 레벨은 덮어쓰지 않고 (레벨 ⊕ 계약 ⊕ 테넌트 정책)으로 계산."""
    rules: list[str] = []
    if doc["conf"] < CONFIDENCE_THRESHOLD:
        # SPA 규칙표: R12=신뢰도 임계 미달(R01은 '접근 통제 - 수집 차단') — 이식 오류 교정(리뷰 확정)
        # SPA rule table: R12 = confidence shortfall (R01 means access-control block) — porting fix
        rules.append("R12")
        return {"route": "review", "rules": rules,
                "why": f"AI 신뢰도 {doc['conf']}% < 임계값 {CONFIDENCE_THRESHOLD}% - 사람 검토로 회부 [R12]"}
    # R13 법무 확정 게이트(SPA legal_review 이식 — 리뷰 확정): CC BY-NC 계열 표기는 법무 확정 전까지
    # 자동 적재 금지 — 재판정(requeue)으로도 검토를 벗어나지 않는다. 확정 시 LEGAL_CONFIRMED에 추가.
    # R13 legal-confirmation gate (ported from the SPA): CC BY-NC markings never auto-upload until
    # legal signs off — requeue cannot escape review. Confirmed catalogs go into LEGAL_CONFIRMED.
    mark = ((doc.get("lic") or "") + " " + (doc.get("snap_mark") or "")).upper()
    if "BY-NC" in mark and "CC-BY-NC-4.0" not in LEGAL_CONFIRMED:
        return {"route": "review", "rules": ["R13"],
                "why": "표준 카탈로그 CC-BY-NC-4.0 감지 - 법무 확정 전 검토 대기 [R13]"}
    lv = doc["lv"]
    if lv == 1:
        if LEVEL_ACTIONS.get("1") == "review":
            return {"route": "review", "rules": ["R12"], "why": "보수 모드 - L1도 검토로 강등 [R12]"}
        return {"route": "uploaded", "rules": ["R02"], "why": "L1 자유 이용 - 자동 적재 경로 [R02]"}
    if lv == 2:
        cond = doc.get("cond") or []
        if "nc" in cond and USAGE["commercial"]:
            return {"route": "held", "rules": ["R07"], "why": "L2 조건 불일치 - 비상업 한정 자료인데 상업적 이용이 설정됨 [R07]"}
        if "no-redist" in cond and USAGE["redistribute"]:
            return {"route": "held", "rules": ["R07"], "why": "L2 조건 불일치 - 재배포 금지 자료인데 재배포 이용이 설정됨 [R07]"}
        return {"route": "uploaded", "rules": ["R06"],
                "why": f"L2 조건({', '.join(cond) or 'attribution'})이 현재 이용 목적과 부합 - 조건부 적재 경로 [R06]"}
    if lv == 3:
        return {"route": "review", "rules": ["R08"], "why": "L3 라이선스 불명 - 표기 부재는 자유 이용이 아니라 보호가 기본값 [R08]"}
    lic, gap = _lic_for(doc, licenses)
    if lic and not gap:
        return {"route": "uploaded", "rules": ["R10"], "lic": lic["id"],
                "why": f"L4 - {lic['id']} 계약이 적재 3용도(사내·AI·교육)를 모두 충족 - 계약 기반 적재 [R10]"}
    if lic:
        return {"route": "held", "rules": ["R11"], "lic": lic["id"],
                "why": f"L4 - {lic['id']} 계약은 있으나 용도 불충족({', '.join(gap)}). 적재는 RAG·Viva 동시 전파라 부분 적재가 불가능 - 용도 추가 협상 필요 [R11]"}
    return {"route": "held", "rules": ["R09"], "why": "L4 명시적 제한 - 유효한 라이선스 없음, 권리 확보 대기 [R09]"}


def evaluate_license(url: str, text: str = "") -> dict:
    """수집 전 사전 판정 — 소스 URL·표기 문구를 표준 카탈로그 규칙에 대조(결정적)."""
    s = (url or "") + " " + (text or "")
    low = s.lower()
    if any(k in low for k in ("login", "partner.", "signin")):
        return {"level": 5, "catalog": None, "verdict": "수집 차단",
                "why": "접근 통제(로그인 게이트) 감지 - 수집 시도 자체가 접근 통제 우회에 해당"}
    if any(k in s for k in ("공공누리", "go.kr", "kogl")):
        return {"level": 1, "catalog": "KOGL-1", "verdict": "자동 적재", "why": "공공누리 제1유형 - 자유 이용"}
    if any(k in low for k in ("cc-by-nc", "creativecommons", "by-nc")):
        return {"level": 2, "catalog": "CC-BY-NC-4.0", "verdict": "법무 확정 대기",
                "why": "CC BY-NC 표기 감지 - 표준 카탈로그 법무 확정 후 조건부 적재 [R13]"}
    if any(k in low for k in ("subscription", "subscriber", "all rights reserved", "구독", "유료")):
        return {"level": 4, "catalog": "PUBLISHER-SUB", "verdict": "권리 원장 대조",
                "why": "명시적 제한 표기 - 유효 계약이 있어야 적재 가능"}
    return {"level": 3, "catalog": "NO-MARKING", "verdict": "사람 검토",
            "why": "라이선스 표기를 찾지 못함 - 보호가 기본값이라 검토로 회부 [R08]"}


# ─────────────────────────────────────────────────────────────────────────────
# 조회
# Reads
# ─────────────────────────────────────────────────────────────────────────────

def _row_doc(r) -> dict:
    d = dict(r)
    for k in ("cond", "evidence", "signals", "aud", "rules", "history"):
        d[k] = json.loads(d.get(k) or "[]")
    return d


def list_docs(route: str = "", level: int = 0) -> list[dict]:
    sql, args, conds = "SELECT * FROM edu_docs", [], []
    if route in DOC_STATES:
        conds.append("state = ?"); args.append(route)
    if level:
        conds.append("lv = ?"); args.append(int(level))
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    with db._conn() as conn:  # noqa: SLF001
        return [_row_doc(r) for r in conn.execute(sql + " ORDER BY id", args).fetchall()]


def get_doc(doc_id: str) -> dict | None:
    with db._conn() as conn:  # noqa: SLF001
        r = conn.execute("SELECT * FROM edu_docs WHERE id = ?", (doc_id,)).fetchone()
    return _row_doc(r) if r else None


def kpi() -> dict:
    with db._conn() as conn:  # noqa: SLF001
        by = dict(conn.execute("SELECT state, COUNT(*) FROM edu_docs GROUP BY state").fetchall())
        total = conn.execute("SELECT COUNT(*) FROM edu_docs").fetchone()[0]
    return {"collected": total, "uploaded": by.get("uploaded", 0), "review": by.get("review", 0),
            "staged": by.get("staged", 0), "held": by.get("held", 0), "rejected": by.get("rejected", 0)}


def pipeline_status() -> dict:
    k = kpi()
    stages = [
        {"stage": "서칭·수집", "count": k["collected"], "state": "ok"},
        {"stage": "분류·요약", "count": k["collected"], "state": "ok"},
        {"stage": "검증·판정", "count": k["review"], "state": "attention" if k["review"] else "ok"},
        {"stage": "권리 보류", "count": k["held"], "state": "attention" if k["held"] else "ok"},
        {"stage": "업로드 대기", "count": k["staged"], "state": "attention" if k["staged"] else "ok"},
        {"stage": "SharePoint 업로드", "count": k["uploaded"], "state": "ok"},
    ]
    return {"stages": stages, "kpi": k}


def list_audit(top: int = 30) -> list[dict]:
    with db._conn() as conn:  # noqa: SLF001
        rows = conn.execute("SELECT * FROM edu_audit ORDER BY id DESC LIMIT ?",
                            (max(1, min(int(top or 30), 200)),)).fetchall()
    return [dict(r) for r in rows]


def license_catalog() -> dict:
    with db._conn() as conn:  # noqa: SLF001
        ledger = [dict(r) for r in conn.execute("SELECT * FROM edu_licenses ORDER BY id").fetchall()]
    for lic in ledger:
        lic["uses"] = json.loads(lic["uses"] or "{}")
        lic["revoked"] = bool(lic["revoked"])
        lic["survival"] = bool(lic["survival"])
        lic["status"] = "valid" if _lic_valid({**lic, "uses": "{}"}) else "expired"
    return {"standard": STD_CATALOG, "ledger": ledger}


def tenant_settings() -> dict:
    return {"usage": USAGE, "confidenceThreshold": CONFIDENCE_THRESHOLD, "levelActions": LEVEL_ACTIONS,
            "folders": FOLDERS, "catMap": CAT_MAP, "uploadDelaySec": 60,
            "domainDesc": "HVAC(냉난방공조)·보일러·히트펌프 제조사의 기술 자료, 규제·표준 동향, 시장 조사",
            "keywords": ["히트펌프", "냉매", "보일러", "EPBD", "COP", "콘덴싱"],
            "sources": [
                {"name": "국가법령정보 OPEN API", "kind": "OpenAPI", "auth": "••••3A9F", "licenseId": None, "schedule": "1일 1회", "on": True},
                {"name": "국가기술표준원 KS", "kind": "OpenAPI", "auth": "••••8B12", "licenseId": None, "schedule": "1일 1회", "on": True},
                {"name": "CrossRef 학술 메타", "kind": "REST API", "auth": "", "licenseId": None, "schedule": "6시간", "on": True},
                {"name": "Journal of HVAC&R", "kind": "REST API", "auth": "••••5D44", "licenseId": "LIC-001", "schedule": "1일 1회", "on": True},
                {"name": "Apex Market Intelligence", "kind": "REST API", "auth": "••••7C21", "licenseId": "LIC-002", "schedule": "30분", "on": True},
                {"name": "제조사 보도자료 RSS", "kind": "RSS", "auth": "", "licenseId": None, "schedule": "1시간", "on": False}]}


def learning_records(user: str = "") -> list[dict]:
    with db._conn() as conn:  # noqa: SLF001
        if user:
            rows = conn.execute("SELECT * FROM edu_learn_deadlines WHERE name LIKE ? ORDER BY id",
                                (f"%{user}%",)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM edu_learn_deadlines ORDER BY id").fetchall()
    out = [dict(r) for r in rows]
    for r in out:
        r["overdue"] = bool(r["overdue"])
    return out


def org_completion(dept: str = "") -> dict:
    with db._conn() as conn:  # noqa: SLF001
        if dept:
            rows = conn.execute("SELECT * FROM edu_learn_depts WHERE name LIKE ?", (f"%{dept}%",)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM edu_learn_depts ORDER BY pct DESC").fetchall()
    return {"overall": 68, "required": 81, "manage": 23, "depts": [dict(r) for r in rows]}


def search_contents(q: str) -> list[dict]:
    """승인(적재)된 콘텐츠만 검색 — 어시스턴트 근거용."""
    with db._conn() as conn:  # noqa: SLF001
        rows = conn.execute(
            "SELECT id, title, type, source, summary, sp_name FROM edu_docs "
            "WHERE state = 'uploaded' AND (title LIKE ? OR summary LIKE ?) ORDER BY id",
            (f"%{q}%", f"%{q}%")).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# 액션 — 실제 상태 전이 + 감사
# Actions — real transitions + audit
# ─────────────────────────────────────────────────────────────────────────────

ROUTE_LABEL = {"uploaded": "SharePoint 업로드", "staged": "업로드 대기", "review": "검토 대기",
               "held": "권리 보류", "rejected": "반려"}


def _stamp() -> str:
    """감사·업로드 시각 = KST 'YYYY-MM-DD HH:MM:SS'(종전 SQLite 로컬 시각 값과 같은 모양, 호스트 시간대 무관)
    Audit/upload time as KST 'YYYY-MM-DD HH:MM:SS' (same shape as the former SQLite local-time value, host-zone independent)."""
    return kst.now().strftime("%Y-%m-%d %H:%M:%S")


def _audit(conn, doc_title: str, move: str, by: str, note: str = "") -> None:
    conn.execute("INSERT INTO edu_audit(t, doc, move, by, note) VALUES(?,?,?,?,?)",
                 (_stamp(), doc_title, move, by, note))


def _transition(conn, doc: dict, to: str, by: str, note: str = "") -> bool:
    """상태 조건부 전이(경합 방어 — 리뷰 확정): 기대 상태에서만 전이하고 경합 패배 시 False."""
    # Conditional transition (race guard): only from the expected state; False when the race is lost.
    frm = doc["state"]
    hist = doc["history"] + [{"t": "", "from": frm, "to": to, "by": by, "note": note}]
    cur = conn.execute("UPDATE edu_docs SET state = ?, history = ? WHERE id = ? AND state = ?",
                       (to, json.dumps(hist, ensure_ascii=False), doc["id"], frm))
    if cur.rowcount != 1:
        return False
    _audit(conn, doc["title"], f"{ROUTE_LABEL.get(frm, frm)} → {ROUTE_LABEL.get(to, to)}", by, note)
    return True


def _do_upload(conn, doc: dict, by: str, note: str = "") -> str | None:
    """전이를 먼저 원자적으로 확정한 뒤에만 원장·메타를 기록 — 경합 패배 시 None(원장 중복 방지)."""
    # Claim the transition atomically FIRST; ledger/meta only after — None when the race is lost.
    sp_name = f"{doc['title'][:34]} [AI365-{doc['id']}·L{doc['lv']}{('·' + doc['applied_lic']) if doc.get('applied_lic') else ''}].pdf"
    folder = CAT_MAP.get(doc.get("cat") or "", FOLDERS[0])
    if not _transition(conn, doc, "uploaded", by,
                       f"SharePoint 업로드 확정(비가역) · 파일명 {sp_name}{(' · ' + note) if note else ''}"):
        return None
    at = _stamp()
    conn.execute("UPDATE edu_docs SET sp_name = ?, uploaded_at = ? WHERE id = ?",
                 (sp_name, at, doc["id"]))
    conn.execute("INSERT INTO edu_uploads(t, doc, name, hash, lic, folder) "
                 "VALUES(?,?,?,?,?,?)",
                 (at, doc["title"], sp_name, f"sha256:{doc['id'].lower()}9f3a…", doc.get("applied_lic") or "-", folder))
    return sp_name


def submit_review(doc_id: str, verdict: str, note: str = "") -> dict | None:
    """검토 판정 — approve=적재(원장 기록·비가역, 업로드 대기 확정 포함) / reject=반려(검토만).
    검토·대기 외 상태와 경합 패배는 409 — 동시 승인 2건이 원장에 중복 기록되는 결함 방어(리뷰 확정)."""
    # approve = upload (review or staged), reject = review only. Non-eligible states and lost races
    # return 409 — guards the double-approval ledger duplication found in review.
    doc = get_doc(doc_id)
    if doc is None:
        return None
    if doc["state"] not in ("review", "staged"):
        return {"error": f"검토·대기 상태가 아닙니다(현재: {ROUTE_LABEL.get(doc['state'], doc['state'])})", "status": 409}
    with db._conn() as conn:  # noqa: SLF001
        if verdict == "approve":
            by = "사람 검토(승인)" if doc["state"] == "review" else "업로드 대기 확정"
            sp = _do_upload(conn, doc, by, note)
            if sp is None:
                return {"error": "다른 요청이 먼저 처리했습니다 — 상태를 새로고침하세요", "status": 409}
            return {"id": doc_id, "verdict": "approve", "state": "uploaded", "spName": sp}
        if verdict == "reject":
            if doc["state"] != "review":
                return {"error": "반려는 검토 상태에서만 가능합니다", "status": 409}
            if not _transition(conn, doc, "rejected", "사람 검토(반려)", note or "검토자 판단 - 적재 부적합"):
                return {"error": "다른 요청이 먼저 처리했습니다 — 상태를 새로고침하세요", "status": 409}
            return {"id": doc_id, "verdict": "reject", "state": "rejected"}
    return {"error": "verdict는 approve/reject 중 하나여야 합니다", "status": 422}


def requeue(doc_id: str) -> dict | None:
    """보류·반려 문서 재판정 — 권리 원장·정책 변화를 반영해 evaluate()를 다시 태운다."""
    doc = get_doc(doc_id)
    if doc is None:
        return None
    if doc["state"] not in ("held", "rejected"):
        return {"error": f"재판정 대상이 아닙니다(현재: {ROUTE_LABEL.get(doc['state'], doc['state'])})", "status": 409}
    with db._conn() as conn:  # noqa: SLF001
        licenses = [dict(r) for r in conn.execute("SELECT * FROM edu_licenses").fetchall()]
        ev = evaluate(doc, licenses)
        conn.execute("UPDATE edu_docs SET eval_why = ?, rules = ?, applied_lic = ? WHERE id = ?",
                     (ev["why"], json.dumps(ev["rules"], ensure_ascii=False), ev.get("lic"), doc_id))
        doc["applied_lic"] = ev.get("lic")
        if ev["route"] == "uploaded":
            sp = _do_upload(conn, doc, "시스템(재판정)", ev["why"])
            if sp is None:
                return {"error": "다른 요청이 먼저 처리했습니다 — 상태를 새로고침하세요", "status": 409}
            return {"id": doc_id, "state": "uploaded", "why": ev["why"], "spName": sp}
        if ev["route"] != doc["state"]:
            if not _transition(conn, doc, ev["route"], "시스템(재판정)", ev["why"]):
                return {"error": "다른 요청이 먼저 처리했습니다 — 상태를 새로고침하세요", "status": 409}
        else:
            _audit(conn, doc["title"], "재판정 - 상태 유지", "시스템(재판정)", ev["why"])
    return {"id": doc_id, "state": ev["route"], "why": ev["why"]}


# ─────────────────────────────────────────────────────────────────────────────
# 시드 — SPA SEED 14건 + 업로드 대기 1건 + 법무 확정 대기 1건 (KPI 15·6·4·1·4 정합)
# ─────────────────────────────────────────────────────────────────────────────

def _seed(conn) -> None:
    today = kst.today()
    for lic in [
        {"id": "LIC-001", "name": "J. HVAC&R 사내 교육 라이선스", "scope": "Journal of HVAC&R",
         "uses": {"internal": True, "ai": True, "education": True, "redistribute": False, "commercial": False},
         "start": (today - timedelta(days=120)).isoformat(), "end": (today + timedelta(days=214)).isoformat(),
         "obligations": "출처표기 의무: “© Journal of HVAC&R, 사내 라이선스 이용”",
         "contact": "permissions@jhvacr.example", "file": "계약서_JHVACR_2026.pdf", "revoked": False, "survival": True},
        {"id": "LIC-002", "name": "Apex MI 엔터프라이즈 구독", "scope": "Apex Market Intelligence",
         "uses": {"internal": True, "ai": True, "education": False, "redistribute": True, "commercial": False},
         "start": (today - timedelta(days=356)).isoformat(), "end": (today + timedelta(days=9)).isoformat(),
         "obligations": "사내 시스템 내 재배포 허용 · 외부 공개 금지",
         "contact": "sales@apex-mi.example", "file": "계약서_Apex_Enterprise.pdf", "revoked": False, "survival": False},
    ]:
        conn.execute("INSERT INTO edu_licenses VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (lic["id"], lic["name"], lic["scope"], json.dumps(lic["uses"], ensure_ascii=False),
                      lic["start"], lic["end"], lic["obligations"], lic["contact"], lic["file"],
                      int(lic["revoked"]), int(lic["survival"])))
    licenses = [dict(r) for r in conn.execute("SELECT * FROM edu_licenses").fetchall()]

    for i, s in enumerate(_SEED_DOCS):
        doc = {**s, "id": f"D{i + 1:02d}", "cat": s.get("cat") or "기타", "history": []}
        if s.get("lv") == 5:
            # L5 접근 통제 — 문서 레코드를 남기지 않는다: 감사 기록만 하고 폐기(SPA 동일)
            _audit(conn, s["title"], "수집 차단 - 기록 후 폐기", "시스템(수집 필터)",
                   f"L5 접근 통제 - 수집 시도 자체가 통제 우회 · 출처 {s['source']} · 원문 미저장, 사람 검토 없이 종료")
            continue
        if s.get("_state"):   # 시나리오 고정 상태(업로드 대기·법무 확정 대기)
            ev = {"route": s["_state"], "rules": s.get("_rules", []), "why": s.get("_why", "")}
        else:
            ev = evaluate(doc, licenses)
        hist = [{"t": s["time"], "from": "-", "to": "수집·분류·요약 완료", "by": "AI 엔진",
                 "note": f"AI 분석 · 신뢰도 {s['conf']}% · L{s['lv']} 판정"},
                {"t": s["time"], "from": "검증", "to": ROUTE_LABEL.get(ev["route"], ev["route"]), "by": "AI 엔진", "note": ev["why"]}]
        conn.execute(
            "INSERT INTO edu_docs(id,time,type,title,source,url,lic,lv,conf,cond,summary,evidence,signals,"
            "snap_exc,snap_mark,aud,contact,cat,state,applied_lic,eval_why,rules,sp_name,uploaded_at,history) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (doc["id"], s["time"], s["type"], s["title"], s["source"], s.get("url", ""), s.get("lic", ""),
             s["lv"], s["conf"], json.dumps(s.get("cond", []), ensure_ascii=False), s.get("summary", ""),
             json.dumps(s.get("evidence", []), ensure_ascii=False), json.dumps(s.get("signals", []), ensure_ascii=False),
             s.get("snap_exc", ""), s.get("snap_mark", ""), json.dumps(s.get("aud", []), ensure_ascii=False),
             s.get("contact", ""), doc["cat"], ev["route"], ev.get("lic"), ev["why"],
             json.dumps(ev["rules"], ensure_ascii=False), None, None, json.dumps(hist, ensure_ascii=False)))
        if ev["route"] == "uploaded":
            d2 = {**doc, "state": "uploaded", "applied_lic": ev.get("lic"), "history": hist}
            sp_name = f"{s['title'][:34]} [AI365-{doc['id']}·L{s['lv']}{('·' + ev['lic']) if ev.get('lic') else ''}].pdf"
            conn.execute("UPDATE edu_docs SET sp_name = ?, uploaded_at = ? WHERE id = ?", (sp_name, s["time"], doc["id"]))
            conn.execute("INSERT INTO edu_uploads(t, doc, name, hash, lic, folder) VALUES(?,?,?,?,?,?)",
                         (s["time"], s["title"], sp_name, f"sha256:{doc['id'].lower()}9f3a…",
                          ev.get("lic") or "-", CAT_MAP.get(doc["cat"], FOLDERS[0])))
            _audit(conn, s["title"], "SharePoint 업로드(비가역)", "시스템", f"파일명 {sp_name}")
        else:
            _audit(conn, s["title"], ROUTE_LABEL.get(ev["route"], ev["route"]), "AI 엔진", ev["why"])

    for r in [("정우진", "영업기술지원", "R-32 냉매 안전 취급 교육", "초과 6일", 1),
              ("한지민", "구매", "저GWP 냉매 전환 F-gas 규제 해설", "초과 3일", 1),
              ("오세훈", "경영지원", "히트펌프 설치·시운전 실무 가이드", "초과 1일", 1),
              ("최민지", "생산기술", "저GWP 냉매 전환 F-gas 규제 해설", "D-2", 0),
              ("박준영", "품질보증", "콘덴싱 보일러 효율 개선 기술자료", "D-4", 0)]:
        conn.execute("INSERT INTO edu_learn_deadlines(name,dept,course,label,overdue) VALUES(?,?,?,?,?)", r)
    for r in [("기술연구소", 84), ("품질보증", 77), ("생산기술", 71), ("영업기술지원", 63), ("구매", 52), ("경영지원", 41)]:
        conn.execute("INSERT INTO edu_learn_depts(name,pct) VALUES(?,?)", r)


_SEED_DOCS = [
    {"time": "06:02", "type": "규제·고시", "title": "저GWP 냉매 전환 의무화 F-gas 규제 개정안", "source": "환경부 고시",
     "url": "https://www.me.go.kr/", "lic": "공공누리 제1유형", "lv": 1, "conf": 97, "cat": "규제·정책",
     "summary": "고GWP 냉매의 단계적 사용 제한과 저GWP 대체냉매 전환 일정을 규정한 개정안이 고시되어 냉동·공조설비 설계 반영이 필요하다.",
     "evidence": ["p.2 §1 개정 목적", "p.5 표3 전환 일정"],
     "signals": [["라이선스 표기", "공공누리 제1유형 배지 확인"], ["robots.txt", "수집 허용"], ["페이월", "없음"]],
     "snap_exc": "이 저작물은 「공공누리 제1유형: 출처표시」 조건에 따라 이용할 수 있습니다.", "snap_mark": "공공누리 제1유형",
     "aud": ["친환경설비팀", "공조설계팀"]},
    {"time": "06:18", "type": "표준·규격", "title": "건물 공조설비 에너지효율 등급 KS 기준 개정", "source": "국가기술표준원",
     "url": "https://www.kats.go.kr/", "lic": "공공누리 제1유형", "lv": 1, "conf": 96, "cat": "표준·인증",
     "summary": "중앙공조기·팬코일유닛의 에너지효율 측정법과 등급 구간이 개정되어 신규 설비 선정 기준이 강화되었다.",
     "evidence": ["p.1 고시문", "p.7 부표1 등급 구간"], "signals": [["라이선스 표기", "공공누리 제1유형"], ["페이월", "없음"]],
     "snap_exc": "본 개정 고시는 공공누리 제1유형에 따라 자유롭게 이용할 수 있으며…", "snap_mark": "공공누리 제1유형",
     "aud": ["설비기술팀", "에너지관리팀"]},
    {"time": "06:51", "type": "규제·고시", "title": "보일러 질소산화물(NOx) 배출허용기준 강화 고시", "source": "환경부",
     "url": "https://www.me.go.kr/", "lic": "공공누리 제1유형", "lv": 1, "conf": 95, "cat": "규제·정책",
     "summary": "산업·상업용 보일러의 NOx 배출허용기준이 강화되어 저NOx 버너 교체 및 인증 대응이 요구된다.",
     "evidence": ["p.3 별표2 허용기준"], "signals": [["라이선스 표기", "공공누리 제1유형"], ["robots.txt", "수집 허용"]],
     "snap_exc": "공공누리 제1유형(출처표시)에 따라 이용 가능.", "snap_mark": "공공누리 제1유형", "aud": ["시설관리팀", "친환경설비팀"]},
    {"time": "07:14", "type": "공공데이터", "title": "지역별 난방도일(HDD)·냉방도일(CDD) 통계 갱신", "source": "한국에너지공단",
     "url": "https://www.energy.or.kr/", "lic": "공공누리 제1유형", "lv": 1, "conf": 94, "cat": "HVAC·공조",
     "summary": "지역별 냉난방 부하 산정에 쓰이는 도일 통계가 갱신되어 냉난방 용량 설계 검증에 활용 가능하다.",
     "evidence": ["데이터셋 메타 §이용조건"], "signals": [["라이선스 표기", "공공누리 제1유형"], ["데이터 API", "공식 제공"]],
     "snap_exc": "본 데이터는 공공누리 제1유형으로 개방되며 상업적 이용 및 2차 가공이 가능합니다.", "snap_mark": "공공누리 제1유형",
     "aud": ["에너지관리팀"]},
    {"time": "07:39", "type": "기술문서", "title": "콘덴싱 보일러 효율 개선 기술자료(협회 공개)", "source": "한국설비기술협회",
     "url": "https://www.sarek.or.kr/", "lic": "협회 공개 · 출처표기 조건", "lv": 2, "cond": ["attribution"], "conf": 88,
     "cat": "난방·보일러",
     "summary": "잠열 회수율을 높이는 콘덴싱 보일러 열교환기 설계와 응축수 처리 가이드가 공개되었다.",
     "evidence": ["p.4 그림2 열교환 구조", "p.9 §5 응축수 처리"],
     "signals": [["라이선스 표기", "출처표기 조건부 공개"], ["페이월", "없음"]],
     "snap_exc": "본 기술자료는 출처를 명시하는 조건으로 자유롭게 열람·활용하실 수 있습니다.", "snap_mark": "출처를 명시하는 조건",
     "aud": ["설비기술팀"]},
    {"time": "06:33", "type": "뉴스", "title": "인버터 히트펌프 신제품 COP 향상 기술 공개", "source": "제조사 보도자료",
     "url": "https://vendor.example/press", "lic": "벤더 공개 · 비상업 조건", "lv": 2, "cond": ["attribution", "nc"], "conf": 58,
     "cat": "HVAC·공조",
     "summary": "부분부하 효율을 개선한 인버터 히트펌프가 출시되어 한랭지 난방 COP가 향상된 성능 데이터가 공개되었다.",
     "evidence": ["보도자료 ¶3 성능 수치"], "signals": [["라이선스 표기", "보도자료 이용 안내(비상업)"], ["표기 명확성", "낮음 - 문구 모호"]],
     "snap_exc": "본 보도자료는 비상업적 보도 목적에 한해 자유롭게 인용할 수 있습니다.", "snap_mark": "비상업적 보도 목적에 한해",
     "aud": ["공조설계팀", "R&D팀"]},
    {"time": "08:05", "type": "기술문서", "title": "ASHRAE 환기·실내공기질 가이드 공개 요약본", "source": "표준화기구 공개 요약",
     "url": "https://www.ashrae.org/", "lic": "표기 없음 · 조건 불명", "lv": 3, "conf": 81, "cat": "표준·인증",
     "summary": "실내공기질 확보를 위한 환기율 산정과 공조 운전 권장사항의 개정 핵심이 공개 요약본으로 배포되었다.",
     "evidence": ["요약본 p.2 환기율 산식"],
     "signals": [["라이선스 표기", "없음 - 보호가 기본값"], ["이용약관 링크", "발견되지 않음"], ["페이월", "없음"]],
     "snap_exc": "This executive summary highlights key changes… (라이선스·재사용 조건 문구 없음)", "snap_mark": "",
     "aud": ["공조설계팀", "품질경영팀"], "contact": "standards@ashrae.example"},
    {"time": "09:10", "type": "백서", "title": "상업용 보일러 교체 수요 벤치마크 백서", "source": "Strathorn Consulting 백서",
     "url": "https://strathorn.example/", "lic": "등록 후 무료 · 재배포 조건 불명확", "lv": 3, "conf": 74, "cat": "기타",
     "summary": "노후 보일러 교체 주기와 고효율 전환 투자수익을 산업별로 진단한 벤치마크 결과를 제시한다.",
     "evidence": ["p.6 표4 교체주기", "p.11 ROI 모델"],
     "signals": [["라이선스 표기", "불명확 - '무료 제공'만 명시"], ["재배포 조건", "명시 없음"], ["등록 게이트", "이메일 등록 후 다운로드"]],
     "snap_exc": "Download our complimentary benchmark whitepaper. © Strathorn Consulting.", "snap_mark": "free of charge for registered users",
     "aud": ["전략기획팀", "시설관리팀"], "contact": "insights@strathorn.example"},
    {"time": "07:02", "type": "논문", "title": "지열 히트펌프 시스템의 계간 성능계수 실증 연구", "source": "Journal of HVAC&R (구독 저널)",
     "url": "https://jhvacr.example/article/8817", "lic": "© All Rights Reserved · 구독", "lv": 4, "conf": 93, "cat": "HVAC·공조",
     "summary": "상업건물 8개소의 24개월 데이터로 지열 히트펌프의 계절 성능계수(SCOP)와 회수기간을 정량 분석했다.",
     "evidence": ["p.4 표2 SCOP 실측", "p.9 회수기간 모델"],
     "signals": [["저작권 고지", "© All Rights Reserved"], ["페이월", "구독 필요"], ["재사용 조건", "별도 허락 요구"]],
     "snap_exc": "© 2026 Journal of HVAC&R. All rights reserved.", "snap_mark": "All rights reserved",
     "aud": ["R&D팀", "에너지관리팀"], "contact": "permissions@jhvacr.example"},
    {"time": "08:22", "type": "리포트", "title": "글로벌 HVAC·히트펌프 시장 2026 전망 리포트", "source": "Apex Market Intelligence (유료)",
     "url": "https://apex-mi.example/reports/hvac-2026", "lic": "유료 구독 · 좌석당 라이선스", "lv": 4, "conf": 91, "cat": "기타",
     "summary": "히트펌프 난방 전환과 데이터센터 냉각 수요로 2026년 HVAC 시장이 성장할 것으로 전망하며 5년 예측 모델을 포함한다.",
     "evidence": ["p.12 그림7 성장 전망", "p.30 예측 모델 가정"],
     "signals": [["저작권 고지", "named-seat 구독 약관"], ["페이월", "구독 필요"], ["재배포", "약관상 금지"]],
     "snap_exc": "This report is licensed to named subscribers only.", "snap_mark": "Redistribution … is prohibited",
     "aud": ["전략기획팀", "구매팀"], "contact": "sales@apex-mi.example"},
    {"time": "08:47", "type": "논문", "title": "냉매 누출이 칠러 효율에 미치는 영향 메타분석", "source": "Refrigeration Science Review (저널)",
     "url": "https://refsci.example/article/12345", "lic": "© 저작권 보유", "lv": 4, "conf": 92, "cat": "냉방·냉동",
     "summary": "다수 현장연구를 종합해 냉매 충전량 편차와 누출이 칠러 COP·소비전력에 미치는 영향을 정량 분석했다.",
     "evidence": ["p.5 그림3 COP 저하 곡선"],
     "signals": [["저작권 고지", "© 표기 확인"], ["페이월", "기관 구독"], ["그림·표 재사용", "허락 필요"]],
     "snap_exc": "© Refrigeration Science Review. Reuse of figures and tables requires permission…", "snap_mark": "requires permission",
     "aud": ["설비기술팀", "정비교육팀"], "contact": "rights@refsci.example"},
    {"time": "09:34", "type": "서적", "title": "냉동·공조 설비 설계 실무 핸드북(전자책)", "source": "기술출판사 전자책",
     "url": "https://ebook.techpub.example/hvac", "lic": "© 출판사 저작권", "lv": 4, "conf": 90, "cat": "HVAC·공조",
     "summary": "냉매 사이클·열부하 계산·덕트 설계 등 냉동공조 실무 전반을 다루는 전자서적으로 설계 표준 참고자료로 적합하다.",
     "evidence": ["목차 기반 범위 평가"],
     "signals": [["저작권 고지", "출판사 ©"], ["DRM", "적용"], ["발췌·가공", "이용 허락 필요"]],
     "snap_exc": "© 기술출판사. 이 책의 무단 전재와 복제를 금합니다.", "snap_mark": "무단 전재와 복제를 금합니다",
     "aud": ["공조설계팀", "신입교육"], "contact": "rights@techpub.example"},
    {"time": "09:28", "type": "데이터셋", "title": "국가별 냉난방 설비 설치 현황 프리미엄 데이터셋", "source": "ChainData Pro (유료 데이터)",
     "url": "https://chaindata.example/hvac-install", "lic": "재배포 명시 금지", "lv": 4, "conf": 95, "cat": "기타",
     "summary": "국가·건물용도별 냉난방기·히트펌프·보일러 설치 대수와 교체 주기를 제공하는 프리미엄 데이터셋이다.",
     "evidence": ["데이터 사전 v3.2"], "signals": [["약관", "재배포 명시적 금지"], ["페이월", "유료 구독"]],
     "snap_exc": "License terms: Data may not be redistributed…", "snap_mark": "may not be redistributed",
     "aud": ["구매팀", "전략기획팀"], "contact": "data-license@chaindata.example"},
    {"time": "09:41", "type": "기술문서", "title": "경쟁사 파트너 포털 내부 기술문서", "source": "경쟁사 파트너 포털",
     "url": "https://partner.rival.example/docs", "lic": "로그인 필요 · 접근 통제", "lv": 5, "conf": 98,
     "summary": "파트너 인증 로그인 뒤에만 접근 가능한 자료로, 수집 시도 자체가 접근 통제 우회에 해당한다.",
     "signals": [["접근 통제", "파트너 로그인 필수"], ["robots.txt", "수집 금지"], ["판정", "수집 단계에서 차단"]],
     "snap_exc": "(수집 차단 - 스냅샷 없음) 로그인 게이트 감지."},
    # 시나리오 고정 2건 — 업로드 대기(취소 가능 마지막 지점) · 법무 확정 대기(R13)
    {"time": "10:05", "type": "기술문서", "title": "히트펌프 설치·시운전 실무 가이드", "source": "한국에너지공단",
     "url": "https://www.energy.or.kr/guide", "lic": "공공누리 제1유형", "lv": 1, "conf": 96, "cat": "HVAC·공조",
     "summary": "히트펌프 실외기 배치·배관 시공·시운전 점검 항목을 정리한 실무 가이드로, 설치 교육 표준 자료로 적합하다.",
     "evidence": ["p.5 점검 체크리스트"], "signals": [["라이선스 표기", "공공누리 제1유형"], ["페이월", "없음"]],
     "snap_exc": "이 가이드는 공공누리 제1유형에 따라 자유롭게 이용할 수 있습니다.", "snap_mark": "공공누리 제1유형",
     "aud": ["신입교육"], "_state": "staged", "_rules": ["R02"],
     "_why": "L1 자유 이용 - 원본 확보·대조 완료, 업로드 대기(이 구간에서만 취소 가능)"},
    # SPA의 R13 데모 문서와 제목 정합(리뷰 확정) — edu-sync.js가 제목으로 매칭·미러하므로 동일해야 한다
    # Title matches the SPA's R13 demo doc — edu-sync.js matches and mirrors by title
    {"time": "10:22", "type": "강의자료", "title": "R-32 냉매 안전 취급 교육 스크립트", "source": "HVAC Open Courseware",
     "url": "https://opencourse.hvac.example/r32-script", "lic": "CC BY-NC 4.0", "lv": 2, "cond": ["attribution", "nc"], "conf": 90,
     "cat": "냉방·냉동",
     "summary": "R-32 냉매의 A2L 특성과 취급·누설 대응 절차를 다루는 교육 스크립트로 CC BY-NC 표기가 확인되었다.",
     "evidence": ["표지 라이선스 배지"], "signals": [["라이선스 표기", "CC BY-NC 4.0"], ["페이월", "없음"]],
     "snap_exc": "This work is licensed under CC BY-NC 4.0.", "snap_mark": "CC BY-NC 4.0",
     "aud": ["신입교육", "정비교육팀"], "_state": "review", "_rules": ["R13"],
     "_why": "표준 카탈로그 CC-BY-NC-4.0 감지 - 법무 확정 전 검토 대기 [R13]"},
]
