"""보안 에이전트 스토어(목업, 2026-09-07) — Groupware 상단 탭 → [보안 에이전트] 대시보드의 데이터 공급원.

실제 M365(Graph) 연동 전까지 앱 안에서 그럴듯하게 돌아가는 목업이다. 수치는 사용자 캡처(2026-09-07)를 그대로 시드로
두고, 화면이 바꿀 수 있는 상태(위험 로그인 무시·갱신 시각)만 SQLite `sec_state` 에 남긴다. 응답 모양은 프런트의
옛 `SEC_SEED` 와 같아서(위험 행에 id 추가) 화면 렌더 코드는 그대로 쓴다. 필드 이름은 나중에 Graph 로 바꿀 때 1:1
매핑이 되도록 Graph 용어(riskySignIns·subscribedSkus…)에 가깝게 둔다.

Security Agent store (mock, 2026-09-07) — data source of the [Security Agent] dashboard under the top Groupware tab.

A mock that behaves plausibly inside the app until the real M365 (Graph) connector exists. Figures are seeded verbatim
from the user's capture (2026-09-07); only the state the screen can change (dismissed risky sign-ins, refresh time) is
persisted in SQLite `sec_state`. The response shape equals the front end's former `SEC_SEED` (plus an id per risky
row), so the render code is reused unchanged. Field names stay close to Graph terms (riskySignIns, subscribedSkus…)
so a later swap maps 1:1.
"""

from __future__ import annotations

import copy
import json
import logging
import sqlite3

from app import db, kst, llm
from app.db import DB_PATH

logger = logging.getLogger(__name__)

__all__ = ["init_security", "dashboard", "dismiss", "refresh", "summary"]

# ── 시드(캡처 수치 그대로) / seed (capture figures verbatim) ──
SEED: dict = {
    "tenant": {"company": "엠클라우드브리지", "name": "MCloudBridge"},
    # 위험 로그인 이벤트(riskySignIns) — 캡처 3건 + 스크롤이 보이도록 2건 / capture rows + 2 so the list scrolls
    "risky": [
        {"id": "rs_0825_wilbert", "d": "2026-08-25", "n": "Wilbert Clarence Setiawan", "e": "demo-16ec4200b8@workspace.example"},
        {"id": "rs_0824_wilbert", "d": "2026-08-24", "n": "Wilbert Clarence Setiawan", "e": "demo-16ec4200b8@workspace.example"},
        {"id": "rs_0824_azure", "d": "2026-08-24", "n": "Azure Partner", "e": "demo-a856e50d30@workspace.example"},
        {"id": "rs_0822_azure", "d": "2026-08-22", "n": "Azure Partner", "e": "demo-a856e50d30@workspace.example"},
        {"id": "rs_0821_sophia", "d": "2026-08-21", "n": "Sophia Lee", "e": "demo-89e94ee59b@workspace.example"},
    ],
    "checks": {
        "user": ["전역 관리자", "게스트 관리자", "역할 변경된 사용자"],
        "auth": ["사용자 액세스", "암호가 만료되지 않도록 설정"],
        "ops": ["사용자 액세스"],
        "log": ["위험한 사용자", "위험한 로그인"],
    },
    "users": {"total": 304, "member": 217, "guest": 87},
    "groups": {"total": 216, "m365": 112, "dist": 34, "sec": 61, "mail": 9},
    "services": [["office365", 0, 304, 304], ["exchange", 15, 289, 304], ["teams", 33, 271, 304],
                 ["oneDrive", 13, 291, 304], ["sharePoint", 14, 290, 304]],
    "teams": [31, 3, 0, 3],
    "exchange": {"used": "1.3TB", "quota": [162, 1, 0, 19],
                 "top": [["demo-b432c54173@workspace.example", 100943], ["demo-23898dc74b@workspace.example", 95414],
                         ["demo-5101bbbfa8@workspace.example", 94447], ["demo-399b18c676@workspace.example", 90534],
                         ["demo-699cfa9127@workspace.example", 73339]]},
    "changes": {"newUsers": 25, "delUsers": 0, "newGroups": 3, "delGroups": 0},
    "newUsers": [["2026-09-02", "demo-57dcfded7a@workspace.example"]],
    "delUsers": [],
    "admins": [["AI 365 관리자", "demo-f52de200e4@workspace.example"]],
    # LLM 요약 실패·오프라인 때 쓰는 고정 요약 / fixed summary used when the LLM summary fails or offline
    "summary": [
        {"h": "주요 이슈", "t": "위험 로그인 사용자 3명이 탐지되었습니다."},
        {"h": "라이선스", "t": "Microsoft_365_Copilot 은 10/10 으로 전량 할당되었고, Dynamics 365 Partner Sandbox 2종은 70% 이상 사용 중입니다."},
        {"h": "저장소", "t": "OneDrive 3.3TB · SharePoint 2.7TB · Exchange 1.3TB 를 사용 중이며, 사서함 19개가 보내기/받기 금지 상태입니다."},
        {"h": "사용자·그룹", "t": "총 사용자 304명(구성원 217·게스트 87), 그룹 216개이며 최근 신규 사용자 25명이 추가되었습니다."},
    ],
    # subscribedSkus: [name, available, assigned, total]
    "licenses": [
        ["AAD_PREMIUM_P2", 100, 0, 100], ["CCIBOTS_PRIVPREV_VIRAL", 9973, 27, 10000], ["CPC_E_8C_32GB_512GB", 3, 2, 5],
        ["DYN365_BUSINESS_MARKETING", 9980, 20, 10000], ["DYN365_CUSTOMER_INSIGHTS_VIRAL", 9980, 20, 10000],
        ["DYNAMICS_365_CONTACT_CENTER", 35, 0, 35],
        ["Dynamics_365_Customer_Service_Enterprise_viral_trial", 9958, 42, 10000],
        ["Dynamics_365_Field_Service_Enterprise_viral_trial", 9955, 45, 10000],
        ["Dynamics_365_Operations_Application_Partner_Sandbox", 9, 41, 50],
        ["Dynamics_365_Sales_Field_Service_and_Customer_Service_Partner_Sandbox", 15, 35, 50],
        ["Dynamics_365_Sales_Premium_Viral_Trial", 9991, 9, 10000], ["FLOW_FREE", 9892, 108, 10000],
        ["IDENTITY_THREAT_PROTECTION", 100, 0, 100], ["MDATP_XPLAT", 100, 0, 100], ["Microsoft_365_Copilot", 0, 10, 10],
        ["Microsoft_365_E3_(no_Teams)", 66, 34, 100], ["Microsoft_365_E5_(no_Teams)", 73, 127, 200],
        ["Microsoft_Entra_Suite", 50, 0, 50],
    ],
    "onedrive": {"used": "3.3TB", "stats": [162, 53, 1065591, 2297],
                 "top": [["demo-85675d4846@workspace.example", 252092], ["demo-d6f25187c6@workspace.example", 186732],
                         ["demo-5101bbbfa8@workspace.example", 185180], ["demo-e15540c227@workspace.example", 183752],
                         ["demo-ea704b4ca7@workspace.example", 168003]]},
    "sharepoint": {"used": "2.7TB", "stats": [144, 41, 226319, 19383],
                   "top": [["Data&AI팀 소유자", 825], ["Cloud Infra Team 소유자", 164], ["ERPD365Developer 소유자", 98],
                           ["영업관리 소유자", 81], ["YBK 소유자", 81]]},
}

_SUMMARY_SYSTEM = (
    "당신은 Microsoft 365 테넌트 보안 대시보드의 요약 작성자다. 주어진 사실(JSON)만 사용해 관리자가 30초 안에 읽을 요약을 만든다.\n"
    "출력은 JSON 객체 하나: {\"items\": [{\"h\": 제목, \"t\": 한 문장}]} — 항목은 3~4개, 순서는 주요 이슈 → 라이선스 → 저장소 → 사용자·그룹.\n"
    "h 는 8자 이내 짧은 제목, t 는 70자 이내 한 문장. 사실에 없는 숫자·이름을 만들지 않는다. 위험 로그인이 0건이면 주요 이슈에 '특이 사항 없음'으로 쓴다.\n"
    "언어: {lang}. 다른 설명 없이 JSON 만 출력한다."
)


def _now() -> str:
    return kst.now_iso()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_security() -> None:
    """상태 테이블 생성(멱등) + 첫 갱신 시각 기록 / create the state table (idempotent) + stamp the first refresh time"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS sec_state(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    if _get("generated_at") is None:
        _set("generated_at", _now())


def _get(key: str, default=None):
    with _conn() as conn:
        row = conn.execute("SELECT value FROM sec_state WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except ValueError:
        return default


def _set(key: str, value) -> None:
    with _conn() as conn:
        conn.execute("INSERT OR REPLACE INTO sec_state(key, value) VALUES(?, ?)",
                     (key, json.dumps(value, ensure_ascii=False)))


def _status(risky_rows: list[dict]) -> list[dict]:
    """종합 상태 스트립 — 위험 로그인이 남아 있으면 주의/확인 필요, 아니면 전부 안전(점검 4종은 시드상 이슈 없음)
    / status strip — caution/needs-review while risky sign-ins remain, otherwise all safe (the four checks have no issue in the seed)"""
    risky = len(risky_rows) > 0
    return [
        {"key": "overall", "lb": "종합 상태", "v": "주의" if risky else "안전", "tone": "warn" if risky else "ok"},
        {"key": "risky", "lb": "위험한 사용자/로그인", "v": "확인 필요" if risky else "안전", "tone": "bad" if risky else "ok"},
        {"key": "user", "lb": "사용자 관리", "v": "안전", "tone": "ok"},
        {"key": "auth", "lb": "인증 관리", "v": "안전", "tone": "ok"},
        {"key": "ops", "lb": "운영 관리", "v": "안전", "tone": "ok"},
        {"key": "log", "lb": "로그 관리", "v": "안전", "tone": "ok"},
    ]


def dashboard() -> dict:
    """화면 전체 취합 응답 — 시드 + 무시된 위험 로그인 제외 + 상태 스트립 + 갱신 시각
    / whole-screen aggregate — seed minus dismissed risky sign-ins + status strip + refresh time"""
    data = copy.deepcopy(SEED)
    dismissed = set(_get("dismissed", []) or [])
    data["risky"] = [r for r in data["risky"] if r["id"] not in dismissed]
    data["status"] = _status(data["risky"])
    data["generated_at"] = _get("generated_at") or _now()
    return data


def dismiss(sid: str) -> bool:
    """위험 로그인 무시(Graph 의 dismiss 의미) — 알 수 없는 id 면 False / dismiss a risky sign-in — False for an unknown id"""
    if not any(r["id"] == sid for r in SEED["risky"]):
        return False
    dismissed = list(_get("dismissed", []) or [])
    if sid not in dismissed:
        dismissed.append(sid)
        _set("dismissed", dismissed)
    return True


def refresh() -> dict:
    """재수집 시뮬레이션 — 무시 상태를 비우고 갱신 시각을 찍는다 / simulated re-collection — clears dismissals, stamps the time"""
    _set("dismissed", [])
    _set("generated_at", _now())
    return dashboard()


def _facts(data: dict) -> dict:
    """LLM 에 넘길 압축 사실 — 화면의 숫자만 추려 토큰을 아낀다 / compact facts for the LLM — only the on-screen figures"""
    risky_users = sorted({r["n"] for r in data["risky"]})
    tight = [[n, a, t] for n, avail, a, t in data["licenses"] if t and (a / t >= 0.7 or avail == 0)]
    return {
        "위험_로그인_건수": len(data["risky"]),
        "위험_로그인_사용자": risky_users,
        "점검_이슈": "없음",
        "사용자": data["users"], "그룹": data["groups"], "신규_삭제": data["changes"],
        "라이선스_여유없음_또는_70%이상": tight,
        "저장소": {"onedrive": data["onedrive"]["used"], "sharepoint": data["sharepoint"]["used"], "exchange": data["exchange"]["used"]},
        "사서함_보내기받기_금지": data["exchange"]["quota"][3],
    }


def summary(lang: str = "ko") -> dict:
    """Dashboard Summary — 경량 모델이 현재 사실로 3~4항목 JSON 을 만든다. 같은 사실+언어는 llm_cache 재사용, 실패하면 시드 요약.
    / Dashboard Summary — the lite model writes 3-4 items from the current facts; identical facts+language reuse
    llm_cache, and any failure falls back to the seed summary."""
    data = dashboard()
    lang = "en" if lang == "en" else "ko"
    facts = _facts(data)
    payload = json.dumps({"lang": lang, "facts": facts}, ensure_ascii=False, sort_keys=True)
    cached = db.cache_get("security_summary", payload)
    if cached:
        try:
            items = json.loads(cached)
            if _valid_items(items):
                return {"items": items, "source": "cache", "generated_at": data["generated_at"]}
        except ValueError:
            pass
    try:
        system = _SUMMARY_SYSTEM.replace("{lang}", "English" if lang == "en" else "한국어")
        text = llm.generate(json.dumps(facts, ensure_ascii=False), system=system, json_mode=True, tier="lite")
        items = _parse_items(text)
        if _valid_items(items):
            db.cache_set("security_summary", payload, json.dumps(items, ensure_ascii=False))
            return {"items": items, "source": "llm", "generated_at": data["generated_at"]}
        logger.warning("보안 요약 응답 형식 불일치 — 시드 요약으로 대체")
    except Exception:  # noqa: BLE001 — 요약 실패가 화면을 막지 않는다 / a failed summary never blocks the screen
        logger.warning("보안 요약 LLM 호출 실패 — 시드 요약으로 대체", exc_info=True)
    return {"items": copy.deepcopy(SEED["summary"]), "source": "seed", "generated_at": data["generated_at"]}


# ── 채팅 조회(그룹웨어 에이전트 read_security 도구, 2026-09-07) ──
# 대상 키 → 대시보드 데이터를 취합 LLM 이 근거로 쓸 결정적 한국어 줄로 서술한다(내부 프롬프트는 한국어 기준).
# ── Chat reads (groupware agent read_security tool, 2026-09-07) ──
# Target key → deterministic Korean lines from the dashboard data for the aggregation LLM to ground on.
READ_TARGETS = ["status", "risky_signins", "checks", "users_groups", "licenses", "service_usage", "storage",
                "admins", "changes", "summary"]
READ_LABELS = {
    "status": "종합 상태", "risky_signins": "위험한 사용자/로그인", "checks": "점검 항목", "users_groups": "사용자·그룹 현황",
    "licenses": "라이선스", "service_usage": "서비스 사용 현황", "storage": "저장소·사서함", "admins": "전역 관리자",
    "changes": "신규/삭제 계정", "summary": "보안 요약",
}
_CHECK_LABELS = {"user": "사용자 관리", "auth": "인증 관리", "ops": "운영 관리", "log": "로그 관리"}


def describe(targets: list[str]) -> str:
    """조회 대상들을 한 텍스트로 — 첫 줄은 출처·갱신 시각, 대상마다 [라벨] 블록 / one text for the targets — header line + one block per target"""
    data = dashboard()
    keys = [t for t in READ_TARGETS if t in targets] or ["status"]
    out = [f"[보안 에이전트 — Microsoft 365 테넌트 '{data['tenant']['name']}' 보안 현황, 갱신 {data['generated_at']}]"]
    for k in keys:
        out.append(f"[{READ_LABELS[k]}]")
        out.extend(_describe_one(k, data))
    return "\n".join(out)


def _describe_one(k: str, d: dict) -> list[str]:  # noqa: C901 — 대상별 단순 분기 / simple per-target branches
    n = lambda v: f"{v:,}" if isinstance(v, int) else str(v)  # noqa: E731
    if k == "status":
        return [" · ".join(f"{s['lb']}: {s['v']}" for s in d["status"])]
    if k == "risky_signins":
        rows = d["risky"]
        if not rows:
            return ["위험한 로그인 기록 없음(모두 처리됨)."]
        users = sorted({r["n"] for r in rows})
        lines = [f"위험한 로그인 {len(rows)}건, 사용자 {len(users)}명({', '.join(users)})."]
        lines += [f"- {r['d']} {r['n']} ({r['e']})" for r in rows]
        return lines
    if k == "checks":
        return [f"- {_CHECK_LABELS[g]}: " + ", ".join(f"{it} No Issue" for it in items) for g, items in d["checks"].items()]
    if k == "users_groups":
        u, g = d["users"], d["groups"]
        return [f"총 사용자 {n(u['total'])}명(구성원 {n(u['member'])}, 게스트 {n(u['guest'])}). "
                f"총 그룹 {n(g['total'])}개(M365 그룹 {n(g['m365'])}, 배포 그룹 {n(g['dist'])}, 보안 그룹 {n(g['sec'])}, 메일 그룹 {n(g['mail'])})."]
    if k == "licenses":
        lines = []
        for name, avail, used, total in d["licenses"]:
            pct = round(used / total * 100) if total else 0
            flag = " ← 여유 없음" if avail == 0 else (" ← 70% 이상 사용" if pct >= 70 else "")
            lines.append(f"- {name}: 할당 {n(used)}/{n(total)} ({pct}%), 사용 가능 {n(avail)}{flag}")
        return lines
    if k == "service_usage":
        lines = [f"- {s}: 활성 {n(a)} / 비활성 {n(i)} / 총 {n(t)}" for s, a, i, t in d["services"]]
        tm = d["teams"]
        lines.append(f"- Teams: 비공개 팀 {n(tm[0])}(활성 {n(tm[1])}), 공개 팀 {n(tm[2])}(활성 {n(tm[3])})")
        return lines
    if k == "storage":
        ex, od, sp = d["exchange"], d["onedrive"], d["sharepoint"]
        q = ex["quota"]
        lines = [f"- Exchange 사용 {ex['used']} — 사서함 정상 {n(q[0])}, 경고 {n(q[1])}, 보내기 금지 {n(q[2])}, 보내기/받기 금지 {n(q[3])}",
                 "  사서함 상위: " + ", ".join(f"{u} {n(m)}MB" for u, m in ex["top"]),
                 f"- OneDrive 사용 {od['used']} — 계정 {n(od['stats'][0])}(활성 {n(od['stats'][1])}), 파일 {n(od['stats'][2])}(활성 {n(od['stats'][3])})",
                 "  OneDrive 상위: " + ", ".join(f"{u} {n(m)}MB" for u, m in od["top"]),
                 f"- SharePoint 사용 {sp['used']} — 사이트 {n(sp['stats'][0])}(활성 {n(sp['stats'][1])}), 파일 {n(sp['stats'][2])}(활성 {n(sp['stats'][3])})",
                 "  SharePoint 상위: " + ", ".join(f"{s} {n(g)}GB" for s, g in sp["top"])]
        return lines
    if k == "admins":
        return [f"- {name} ({acct})" for name, acct in d["admins"]] or ["전역 관리자 없음"]
    if k == "changes":
        c = d["changes"]
        lines = [f"신규 사용자 {n(c['newUsers'])}, 삭제된 사용자 {n(c['delUsers'])}, 신규 그룹 {n(c['newGroups'])}, 삭제된 그룹 {n(c['delGroups'])}."]
        lines += [f"- 신규: {dt} {acct}" for dt, acct in d["newUsers"]]
        lines += [f"- 삭제: {r[0]} {r[2]}" for r in d["delUsers"]]
        return lines
    if k == "summary":
        s = summary("ko")
        return [f"- {it['h']}: {it['t']}" for it in s["items"]]
    return []


def _parse_items(res) -> list | None:
    """llm.generate(json_mode=True) 는 파싱된 객체를 주지만, 문자열(코드펜스 포함)도 받아 준다
    / llm.generate(json_mode=True) returns a parsed object; a string (code fences included) is accepted too"""
    obj = res
    if isinstance(res, str):
        raw = res.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
        try:
            obj = json.loads(raw)
        except ValueError:
            return None
    items = obj.get("items") if isinstance(obj, dict) else obj
    return items if isinstance(items, list) else None


def _valid_items(items) -> bool:
    if not isinstance(items, list) or not 1 <= len(items) <= 6:
        return False
    return all(isinstance(i, dict) and str(i.get("h", "")).strip() and str(i.get("t", "")).strip() for i in items)
