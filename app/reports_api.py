"""리포트 에이전트 API — 개인 보관소 + 대시보드 세션(도구 호출 에이전트).

권한 규약(합의):
- 개인 보관소: 뷰애즈 신원(owner) 스코프 — 본인 것만 조회/저장/실삭제.
- 게시판(2026-09-14): 워크스페이스별 게시판(bd_{ws})은 폐지 — 공유는 /api/boards(전체·그룹·내 보관함)가 맡고, 개인 보관소는
  게시판 '내 보관함'(boards, 'me:<owner>')에 위임된다(엔드포인트·응답 모양은 그대로).
- 대시보드 세션(2026-09-18): /api/reports/dash — 세션은 본인 것만. 저장된 데이터(스냅샷)를 고치는 일은 자유,
  새 조회(query_data)와 데이터 새로고침은 신원의 허용 테이블로 게이팅한다. 대화 맥락은 그 대시보드 안에서만 이어진다.
  종전 POST /generate(LLM 이 차트 숫자까지 만들던 단일 차트 생성)는 폐지했다.
- 이메일로 공유(2026-09-22): POST /api/reports/dash/{id}/mail · POST /api/reports/personal/{rid}/mail(내 보관함 글) — 제목·요약·차트별 인사이트를 본문으로 **가상 메일함(보낸 편지함)에 기록**하고
  받는 사람·제목·본문이 채워진 Outlook 웹 작성 창 링크를 돌려준다(그룹웨어 메일 발송과 같은 방식 — 자동 발송은 하지 않는다). 대화는 싣지 않는다.
- 버전(2026-10-13): 답변마다 대시보드 시점을 V1, V2… 로 남긴다(첫 차트 · 상태를 바꾼 턴 · 이어가기만; 되돌리기 · 화면 조작 · 저장은 버전이 아니다).
  세션 모양에 versions [{n, label, at}], agent 메시지에 ver(그 시점의 최신 번호). GET /api/reports/dash/{id}/versions/{n} = 미리보기(지금 데이터로),
  POST …/versions/{n}/restore = 그 버전으로 이어가기(되돌리기 가능, 새 버전 'V{n}에서 이어가기').
"""
# Report-agent API — the personal library plus dashboard sessions (tool-calling agent).
# Permission contract (agreed):
# - Personal library: scoped to the view-as identity (owner) — list/save/hard-delete own items only.
# - Boards (2026-09-14): the per-workspace boards (bd_{ws}) are retired — sharing lives in /api/boards (all / group / my library)
#   and the personal library delegates to the board store ('me:<owner>'); endpoints and response shapes are unchanged.
# - Dashboard sessions (2026-09-18): /api/reports/dash — own sessions only. Reshaping saved data is free; new queries
#   (query_data) and data refresh are gated by the identity's allowed tables. The conversation context stays inside
#   that dashboard. The old POST /generate (single chart whose numbers the LLM produced) is retired.
# - Share by email (2026-09-22): POST /api/reports/dash/{id}/mail and POST /api/reports/personal/{rid}/mail (a library post) record a mail (title, summary, per-chart insights) in the
#   virtual mailbox's Sent folder and returns an Outlook-web compose link with recipients, subject and body filled in (the
#   same approach as groupware mail sending — nothing is sent automatically). The conversation never goes along.
# - Versions (2026-10-13): each answer keeps a dashboard moment as V1, V2… (first charts, turns that changed the state and
#   continuing only; undo, UI ops and saving are not versions). The session carries versions [{n, label, at}] and agent
#   messages carry ver (the latest number at that point). GET /api/reports/dash/{id}/versions/{n} previews one on the
#   current data; POST …/versions/{n}/restore continues from it (undoable, a new version 'V{n}에서 이어가기').

import logging
import re
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import access, boards, llm, report_agent, report_dash, report_drill, reports

logger = logging.getLogger("ai365.reports")

router = APIRouter(prefix="/api/reports")

MAX_X_ITEMS = report_dash.MAX_X_ITEMS   # 차트 x 항목 상한 / chart x-item cap
MAX_SERIES = report_dash.MAX_GROUP_SERIES   # 차트 시리즈 상한 / chart series cap
MAX_DASH_ITEMS = 8   # 옛 모양(타일만) 대시보드의 타일 상한 / tile cap of legacy (tiles-only) dashboards
MAX_MESSAGE = 2000


def _eff(acting_user_id: str):
    from app.resources_api import _eff as resolve  # 지연 임포트(순환 회피) / lazy import to avoid cycles
    return resolve(acting_user_id)


def _acting_name(acting_user_id: str) -> str:
    s = (acting_user_id or "").strip()
    if not s:
        return "관리자"
    if s.isdigit():
        m = next((x for x in access.list_members() if x.get("no") == int(s)), None)
        if m and m.get("name"):
            return m["name"]
    return "사용자"


def _is_v2(r: dict) -> bool:
    return isinstance(r, dict) and r.get("v") == 2 and isinstance(r.get("charts"), list) and isinstance(r.get("sources"), list)


def _validate_report(r: dict) -> dict:
    """저장·게시 공통 검증 — 단일 리포트(chart 필수)와 대시보드(type='dashboard')를 허용.

    v2(2026-09-18, Source+차트 설정)는 상태를 정규화한 뒤 **서버가 타일·차트 값을 다시 계산**한다 — 클라이언트가 보낸
    그림은 믿지 않는다. 옛 모양 대시보드는 타일별 chart 를 _sanitize_chart 로 재정규화하고 {type,title,items}만 남긴다.
    옛 모양 단일 리포트는 기존 계약 그대로 pass-through(회귀 없음)."""
    # Shared validation for save/post — a single report (chart required) or a dashboard (type='dashboard').
    # v2 (2026-09-18, sources + chart specs): the state is normalized and the server recomputes tiles and values — the
    # client's picture is never trusted. Legacy dashboards re-normalize each tile chart and keep {type,title,items};
    # legacy single reports pass through unchanged (no regression).
    if not r.get("title"):
        raise HTTPException(status_code=422, detail="title·chart는 필수입니다")
    if _is_v2(r):
        state = report_dash.normalize_state(r)
        if not state["charts"]:
            raise HTTPException(status_code=422, detail="차트가 없는 대시보드는 저장하거나 공유할 수 없습니다")
        if r.get("type") == "dashboard":
            return report_dash.dashboard_data(state)
        return report_dash.report_data(state, state["charts"][0]["id"], all_sources=True)
    if r.get("type") == "dashboard":
        items = r.get("items")
        if not isinstance(items, list) or not (1 <= len(items) <= MAX_DASH_ITEMS):
            raise HTTPException(status_code=422, detail=f"대시보드 타일은 1~{MAX_DASH_ITEMS}개여야 합니다")
        norm = []
        for it in items:
            it = it if isinstance(it, dict) else {}
            try:
                chart = _sanitize_chart(it.get("chart"))
            except ValueError as e:
                raise HTTPException(status_code=422, detail=f"타일 차트가 올바르지 않습니다: {e}")
            norm.append({"title": str(it.get("title") or "리포트"), "chart": chart,
                         "insight": str(it.get("insight") or "")})
        return {"type": "dashboard", "title": r["title"], "items": norm}
    if not r.get("chart"):
        raise HTTPException(status_code=422, detail="title·chart는 필수입니다")
    return r


class PersonalIn(BaseModel):
    acting_user_id: str = ""
    report: dict


class PersonalPatch(BaseModel):
    acting_user_id: str = ""
    report: dict


@router.get("/personal")
def list_personal(acting_user_id: str = "") -> dict:
    return {"reports": reports.list_personal(acting_user_id or "")}


@router.post("/personal")
def save_personal(body: PersonalIn) -> dict:
    r = _validate_report(body.report or {})
    saved = reports.add_personal(body.acting_user_id or "", r)
    return {"ok": True, "report": saved}


def _legacy_edit_of_v2(cur: dict, raw: dict) -> dict:
    """옛 화면(리소스 센터 보관소)의 이름 변경·타일 순서·타일 제거를 v2 상태에 옮긴다 — 타일의 cid 로 차트를 찾는다."""
    # Map the legacy screen's rename / tile reorder / tile removal onto a v2 state (tiles carry the chart id as cid).
    state = report_dash.state_of(cur)
    if raw.get("type") == "dashboard" and isinstance(raw.get("items"), list):
        cids = [str(it.get("cid")) for it in raw["items"] if isinstance(it, dict) and it.get("cid")]
        by_id = {c["id"]: c for c in state["charts"]}
        kept = [by_id[c] for c in cids if c in by_id]
        if not kept:
            raise HTTPException(status_code=422, detail="대시보드 타일은 1개 이상이어야 합니다")
        state["charts"] = kept
    state["title"] = str(raw.get("title") or state["title"])[:report_dash.MAX_TITLE]
    state = report_dash.normalize_state(state)
    if cur.get("type") == "dashboard":
        return report_dash.dashboard_data(state)
    return report_dash.report_data(state, state["charts"][0]["id"], all_sources=True)


@router.patch("/personal/{rid}")
def update_personal(rid: str, body: PersonalPatch) -> dict:
    """개인 보관소 항목 갱신(전체 교체) — 대시보드 담기·이름 변경·타일 편집이 사용. owner 스코프."""
    # Update a personal-library item (full replace) — used by dashboard append/rename/tile edits. Owner-scoped.
    owner = body.acting_user_id or ""
    raw = body.report or {}
    cur = reports.get_personal(owner, rid)
    if cur is not None and _is_v2(cur) and not _is_v2(raw):
        if not raw.get("title"):
            raise HTTPException(status_code=422, detail="title·chart는 필수입니다")
        r = _legacy_edit_of_v2(cur, raw)
    else:
        r = _validate_report(raw)
    saved = reports.update_personal(owner, rid, r)
    if saved is None:
        raise HTTPException(status_code=404, detail="해당 리포트가 없거나 소유자가 아닙니다")
    return {"ok": True, "report": saved}


@router.delete("/personal/{rid}")
def delete_personal(rid: str, acting_user_id: str = "") -> dict:
    if not reports.delete_personal(acting_user_id or "", rid):
        raise HTTPException(status_code=404, detail="해당 리포트가 없거나 소유자가 아닙니다")
    return {"ok": True}


def _sanitize_chart(chart: dict) -> dict:
    """차트 그림(x·values) 방어적 정규화 — 길이 정렬·숫자 강제·상한 적용. 불능이면 ValueError."""
    # Defensive normalization of a chart picture (x / values) — align lengths, coerce numbers, apply caps.
    if not isinstance(chart, dict):
        raise ValueError("chart 스펙이 없습니다")
    x = [str(v) for v in (chart.get("x") or [])][:MAX_X_ITEMS]
    if not x:
        raise ValueError("x 라벨이 없습니다")
    series_in = [s for s in (chart.get("series") or []) if isinstance(s, dict)][:MAX_SERIES]
    series = []
    for s in series_in:
        vals = []
        for v in (s.get("values") or [])[:len(x)]:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                vals.append(0.0)
        vals += [0.0] * (len(x) - len(vals))  # 부족분 0 패딩 / zero-pad shortfalls
        series.append({
            "name": str(s.get("name") or "값"),
            "type": "line" if s.get("type") == "line" else "bar",
            "values": vals,
            "yAxis": 1 if s.get("yAxis") == 1 else 0,
        })
    if not series:
        raise ValueError("series가 없습니다")
    out = {"x": x, "xLabel": str(chart.get("xLabel") or ""), "yLabel": str(chart.get("yLabel") or ""),
           "series": series}
    if chart.get("kind") in report_dash.CHART_TYPES:   # 미리보기가 원·도넛·가로 막대를 구분해 그린다 / previews tell pie, donut and hbar apart
        out["kind"] = chart["kind"]
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 대시보드 세션 / dashboard sessions
# ─────────────────────────────────────────────────────────────────────────────

class DashCreateIn(BaseModel):
    acting_user_id: str = ""
    sources: list[dict] = []   # [{columns, rows, sql}] — 채팅 답변의 조회 결과들 / the query results of one chat answer
    chat_id: str = ""
    chat_title: str = ""
    blank: bool = False        # 데이터 없이 시작(에이전트가 조회) / start without data (the agent queries)


class DashOpenIn(BaseModel):
    acting_user_id: str = ""
    post_id: str


class DashTurnIn(BaseModel):
    acting_user_id: str = ""
    message: str
    focus: str = ""
    view: str = ""   # 보고 있는 탭: '' = 전체 대시보드, 's1' = 그 Source 의 개별 대시보드 / the tab in view
    drill: dict = {}  # 드릴다운 중인 화면 상태 {chart, path:[{col,value}], level} — 맥락으로만 쓴다 / the drilled view, context only


class DashOpsIn(BaseModel):
    acting_user_id: str = ""
    ops: list[dict] = []


class DrillIn(BaseModel):
    acting_user_id: str = ""
    sql: str = ""               # 그 차트 Source 의 조회 SQL / the chart source's query SQL
    path: list[dict] = []       # 맨 위부터 [{col, value}] — 첫 항목의 col 이 차트의 x / from the top; the first col is the chart's x
    next: str = ""              # 고른 다음 컬럼(비우면 후보를 찾는다) / the picked next column (blank = look up candidates)
    filters: list[dict] = []    # 차트 필터를 값 목록으로 [{col, values}] / the chart's filters as value lists
    probe: bool = False         # 확인만: 이 단계(path, 축 x)에 내려갈 수 있는 값이 있는가 / check only: can any value on this level drill
    x: str = ""                 # probe 의 축 컬럼 / the axis column of a probe


class DashActIn(BaseModel):
    acting_user_id: str = ""


def _owned(sid: str, acting_user_id: str) -> dict:
    s = report_dash.get_session(sid, acting_user_id or "")
    if s is None:
        raise HTTPException(status_code=404, detail="대시보드를 찾을 수 없습니다")
    return s


def _public(s: dict, **extra) -> dict:
    state = s["state"]
    # 복제본의 행은 싣지 않는다 — 화면이 원본의 행을 가리키게 다시 잇는다 / clone rows are not sent; the screen links them to the root's
    return {"session": {"id": s["id"], "post_id": s["post_id"], "saved": s["saved"], "kind": s["kind"],
                        "origin": s["origin"], "state": report_dash.pack_state(state), "messages": s["messages"], "updated": s["updated"],
                        "can_undo": bool(s.get("can_undo")),
                        "dirty": bool(s.get("dirty")), "saved_at": s.get("saved_at") or "",   # 명시 저장(2026-09-22) / explicit save
                        "versions": s.get("versions") or [],   # 버전 [{n, label, at}] 오래된 것부터, 스냅 없음(2026-10-13) / versions, oldest first, no snaps
                        "pending_auto": bool(state["sources"]) and not state["charts"] and not s["messages"]},
            **extra}


def _tag_ver(sid: str, msg: dict) -> dict:
    """agent 메시지에 그 시점의 최신 버전 번호(ver)를 단다. 버전이 하나도 없으면 키를 두지 않는다(2026-10-13)."""
    # Tag an agent message with the latest version number at that point; no key while there is no version (2026-10-13).
    vers = report_dash.list_versions(sid)
    return {**msg, "ver": vers[-1]["n"]} if vers else msg


def _version_label(trace: list[dict]) -> str:
    """상태를 바꾼 턴의 버전 이름: 성공한 도구 이름을 순서대로 겹치지 않게 ' · ' 로 2개까지 잇고, 더 있으면 ' 외 N'. 없으면 '변경'.
    길이 상한(MAX_VERSION_LABEL)은 push_version 이 지킨다."""
    # The version label of a turn that changed the state: the labels of the tools that succeeded, in order and without
    # repeats, two at most joined by ' · ' plus ' 외 N' for the rest; '변경' when none. push_version enforces the length cap.
    names: list[str] = []
    for t in trace or []:
        name = str(t.get("label") or t.get("tool") or "").strip()
        if t.get("ok") and name and name not in names:
            names.append(name)
    if not names:
        return "변경"
    return " · ".join(names[:2]) + (f" 외 {len(names) - 2}" if len(names) > 2 else "")


def _llm_error(e: Exception) -> HTTPException:
    if isinstance(e, (llm.ModelBusyError, llm.ModelUnreachableError)):
        return HTTPException(status_code=503, detail=str(e) or "AI 모델이 혼잡합니다. 잠시 후 다시 시도해 주세요.")
    logger.exception("리포트 에이전트 호출 실패")
    return HTTPException(status_code=502, detail="리포트 에이전트가 응답하지 못했습니다. 잠시 후 다시 시도해 주세요.")


@router.post("/dash")
def dash_create(body: DashCreateIn) -> dict:
    """채팅 답변의 조회 결과들로 대시보드를 시작한다 — 같은 답변에서 다시 열면 그 세션을 잇는다(대화는 넘기지 않는다)."""
    # Start a dashboard from one answer's query results; reopening the same answer resumes its session. Only the data
    # crosses over — never the chat conversation.
    owner = body.acting_user_id or ""
    raws = [s for s in (body.sources or []) if isinstance(s, dict) and s.get("columns")][:report_dash.MAX_SOURCES]
    if not raws and not body.blank:
        raise HTTPException(status_code=422, detail="대시보드를 시작할 데이터가 없습니다")
    key = report_dash.origin_key(body.chat_id, [str(s.get("sql") or "") for s in raws])
    found = report_dash.find_by_origin(owner, key)
    if found is not None:
        return _public(found, resumed=True)
    note = str(body.chat_title or "")[:200]
    state = report_dash.normalize_state({"sources": [
        {"columns": s.get("columns"), "rows": s.get("rows") or [], "sql": s.get("sql") or "", "label": s.get("label") or "",
         "tables": report_agent.tables_in(str(s.get("sql") or "")),
         "origin": {"kind": "chat", "note": note, "chat_id": body.chat_id}} for s in raws]})
    origin = {"chat_id": body.chat_id, "chat_title": note} if body.chat_id else {}
    return _public(report_dash.create_session(owner, state, key, origin), resumed=False)


@router.get("/dash/library")
def dash_library(acting_user_id: str = "") -> dict:
    """내 보관소 목록(가벼운 모양) — 행 데이터는 싣지 않고 미리보기용 계산 값만 / my library, light: previews only, no row data"""
    owner = acting_user_id or ""
    out = []
    for p in boards.list_posts(f"me:{owner}", kinds=("report", "dashboard")):
        d = p.get("data") if isinstance(p.get("data"), dict) else {}
        tiles = d.get("items") if d.get("type") == "dashboard" else [d]
        thumbs = [t["chart"] for t in (tiles or []) if isinstance(t, dict) and isinstance(t.get("chart"), dict)][:4]
        out.append({"id": p["id"], "kind": p["kind"], "title": p.get("title") or "", "summary": p.get("summary") or "",
                    "created": p["created"], "updated": p["updated"], "v2": _is_v2(d),
                    "charts": len(d.get("charts") or tiles or []), "sources": len(d.get("sources") or []),
                    "thumbs": thumbs})
    out.sort(key=lambda x: x["updated"], reverse=True)
    return {"items": out}


@router.get("/dash/tools")
def dash_tools() -> dict:
    """리포트 에이전트에 붙은 도구 트리(에이전트 › 묶음 › 도구) — 화면의 도구 트리가 그린다 / the attached tools as a tree for the UI"""
    return {"root": "리포트 에이전트", "agents": report_agent.tool_tree()}


@router.post("/dash/open")
def dash_open(body: DashOpenIn) -> dict:
    """내 보관소의 리포트·대시보드를 세션으로 연다 — 있던 세션(대화 포함)을 잇고, 없으면 만든다. 옛 모양은 열 때 바꾼다."""
    # Open a library item as a session: resume the existing one (with its conversation) or create one; the legacy
    # shape is converted on open.
    owner = body.acting_user_id or ""
    if reports.get_personal(owner, body.post_id) is None:
        raise HTTPException(status_code=404, detail="해당 리포트가 없거나 소유자가 아닙니다")
    s = report_dash.find_by_post(owner, body.post_id)
    if s is not None and not s["dirty"]:
        s = report_dash.reload_from_post(s["id"]) or s   # 저장 안 된 변경이 없으면 글의 최신 내용을 따른다 / no unsaved changes → follow the post
    if s is None:
        s = report_dash.create_session(owner, {}, post_id=body.post_id)
    return _public(s, resumed=True)


@router.get("/dash/{sid}")
def dash_get(sid: str, acting_user_id: str = "") -> dict:
    return _public(_owned(sid, acting_user_id))


@router.post("/dash/{sid}/auto")
def dash_auto(sid: str, body: DashActIn) -> dict:
    """첫 차트 — Source 마다 하나씩(LLM, 실패하면 규칙). 초안은 초안으로 남는다(보관함에 올리지 않는다)."""
    # First charts, one per source (LLM, rule-based on failure). A draft stays a draft — nothing reaches the library.
    s = _owned(sid, body.acting_user_id)
    if s["state"]["charts"] or not s["state"]["sources"]:
        return _public(s)
    out = report_agent.auto_charts(s["state"], _eff(body.acting_user_id))
    n = len(out["state"]["charts"])
    text = f"Source {len(out['state']['sources'])}개로 첫 차트 {n}개를 만들었습니다. 아래 입력창에서 차트 추가, 기준선, 디자인, 필터를 요청해 보세요."
    if n:   # 첫 차트가 생기면 버전(보통 V1, 2026-10-13) / the first charts become a version (usually V1)
        report_dash.push_version(sid, out["state"], "대시보드 생성")
    report_dash.append_messages(sid, [_tag_ver(sid, {"role": "agent", "text": text, "trace": out["trace"], "ts": report_dash._now()})])
    return _public(report_dash.save_state(sid, out["state"], touch=False), reply=text, trace=out["trace"])


def _turn(sid: str, acting_user_id: str, message: str, focus: str, shown: str = "", view: str = "",
          drill: dict | None = None) -> dict:
    s = _owned(sid, acting_user_id)
    try:
        out = report_agent.run_turn(s["state"], s["messages"], message, _eff(acting_user_id), focus, view, drill)
    except Exception as e:  # noqa: BLE001 — 상태는 바뀌지 않았다 / the state is untouched
        raise _llm_error(e) from e
    keys = ("charts", "title", "kpis", "theme")
    if [out["state"].get(k) for k in keys] != [s["state"].get(k) for k in keys]:
        report_dash.push_undo(sid, s["state"])   # 바뀐 턴만 되돌리기 대상 / only turns that changed something can be undone
        report_dash.push_version(sid, out["state"], _version_label(out["trace"]))   # 바뀐 턴만 새 버전(2026-10-13) / only changing turns add a version
    now = report_dash._now()
    report_dash.append_messages(sid, [{"role": "user", "text": shown or message, "focus": focus, "ts": now},
                                      _tag_ver(sid, {"role": "agent", "text": out["reply"], "trace": out["trace"], "ts": now})])
    return _public(report_dash.save_state(sid, out["state"], touch=True), reply=out["reply"], trace=out["trace"])


@router.post("/dash/{sid}/turn")
def dash_turn(sid: str, body: DashTurnIn) -> dict:
    """대화 한 턴 — 에이전트가 도구를 불러 대시보드를 고친다. 변경은 세션의 작업본에만 쌓이고, 보관함 글은 [저장](…/save)을 눌러야 갱신된다(2026-09-22)."""
    # One conversation turn: the agent calls tools to edit the dashboard. Changes accumulate in the session's working
    # copy; the library post is updated only by [Save] (…/save), since 2026-09-22.
    message = (body.message or "").strip()[:MAX_MESSAGE]
    if not message:
        raise HTTPException(status_code=422, detail="요청 내용이 비어 있습니다")
    return _turn(sid, body.acting_user_id, message, body.focus, view=body.view, drill=body.drill)


@router.post("/dash/{sid}/charts/{cid}/regen")
def dash_regen(sid: str, cid: str, body: DashActIn) -> dict:
    s = _owned(sid, body.acting_user_id)
    chart = next((c for c in s["state"]["charts"] if c["id"] == cid), None)
    if chart is None:
        raise HTTPException(status_code=404, detail="해당 차트가 없습니다")
    shown = f"'{chart['title']}' 차트를 다시 만들어 줘."   # 대화에는 이 문장만 남긴다(내부 지시문은 LLM 에만) / only this sentence is kept in the conversation
    return _turn(sid, body.acting_user_id, shown + " " + report_agent.REGEN_INSTRUCTION, cid, shown)


@router.post("/dash/{sid}/ops")
def dash_ops(sid: str, body: DashOpsIn) -> dict:
    """화면에서 직접 한 조작(LLM 없음) — 필터 값 고르기·필터 지우기·차트 지우기·차트 크기·제목 등. 어떤 조작이든 작업본을 바꾸고
    '저장하지 않은 변경'이 된다 — 보관함 글은 [저장]에서만 갱신된다(2026-09-22)."""
    # Direct UI manipulation (no LLM): filter selection/removal, chart removal, chart size, title and more. Every op changes
    # the working copy and counts as an unsaved change; the library post is updated only by [Save] (2026-09-22).
    s = _owned(sid, body.acting_user_id)
    state, undo = s["state"], False
    before = {"title": state["title"], "charts": [dict(c) for c in state["charts"]], "kpis": list(state.get("kpis") or []),
              "theme": dict(state.get("theme") or {})}

    def chart_of(op):
        return next((c for c in state["charts"] if c["id"] == op.get("chart")), None)

    for op in (body.ops or [])[:20]:
        kind = op.get("op") if isinstance(op, dict) else None
        if kind == "filter_select":
            c = chart_of(op)
            f = next((f for f in (c or {}).get("filters", []) if f["id"] == op.get("id")), None)
            if f is not None:
                f["selected"] = [report_dash.key(v) for v in (op.get("selected") or [])][:report_dash.MAX_FILTER_SELECTED]
                f.pop("range", None)
                if isinstance(op.get("range"), dict):   # 기간·숫자 범위 — 정규화가 컬럼 종류에 맞는 것만 남긴다 / normalization keeps what fits the column kind
                    f["range"] = op["range"]
            continue
        try:
            if kind == "filter_remove":
                c = chart_of(op)
                if c is not None:
                    c["filters"] = [f for f in c["filters"] if f["id"] != op.get("id")]
            elif kind == "filter_add":   # 카드의 [+ 필터]: 컬럼을 골라 바로 만든다(LLM 없음) / the card's [+ filter]: pick a column, no LLM
                report_agent.run_tool(state, "add_filter", {"chart_id": op.get("chart"), "column": op.get("col")}, None)
            elif kind == "chart_remove":
                undo = True
                report_agent.run_tool(state, "remove_chart", {"chart_id": op.get("id")}, None)
            elif kind == "chart_duplicate":   # 카드의 [복제] — 새 리포트(Source 탭) + 원본과 비교 묶음 / the card's [duplicate]
                undo = True
                report_dash.duplicate_chart(state, str(op.get("id") or ""))
            elif kind == "compare_clear":   # 비교 묶음에서 빼기(둘뿐이면 묶음이 풀린다) / leave the compare group
                report_agent._chart(state, op.get("id")).pop("compare", None)
            elif kind == "note_add":   # 메모 달기(LLM 없음) — 같은 x 에 다시 달면 글만 바뀐다 / add a note by hand; the same x replaces the text
                c = report_agent._chart(state, op.get("chart"))
                if c["type"] in ("pie", "donut", "kpi"):
                    raise ValueError("원·도넛·숫자 카드에는 메모를 달 수 없습니다")
                at, text = report_dash.key(op.get("x"))[:80], report_dash._s(op.get("text"), report_dash.MAX_NOTE_TEXT)
                if not text:
                    raise ValueError("메모 내용이 비어 있습니다")
                notes = [n for n in c.get("notes") or [] if n["x"] != at]
                if len(notes) >= report_dash.MAX_NOTES:
                    raise ValueError(f"메모는 차트마다 {report_dash.MAX_NOTES}개까지입니다")
                c["notes"] = notes + [{"x": at, "text": text}]
            elif kind == "note_remove":
                c = chart_of(op)
                if c is not None:
                    c["notes"] = [n for n in c.get("notes") or [] if n["id"] != op.get("id")]
            elif kind == "trend_clear":   # 추세·예측 칩의 ✕ / the ✕ on the trend chip
                report_agent._chart(state, op.get("id")).pop("trend", None)
            elif kind == "theme_set":   # 머리줄의 대표 색 고르기(LLM 없음) / the brand-colour picker in the header, no LLM
                undo = True
                report_agent.run_tool(state, "set_theme", {"brand_color": op.get("brand")}, None)
            elif kind == "theme_clear":
                undo = True
                report_agent.run_tool(state, "set_theme", {"clear": True}, None)
            elif kind == "kpi_add":   # KPI 카드 편집 폼의 [적용] — 새 카드(LLM 없음) / the KPI card editor's apply: a new card, no LLM
                undo = True
                report_dash.put_kpi(state, op.get("kpi") or {})
            elif kind == "kpi_set":   # 있는 카드를 제자리에서 고친다(폼이 전체 설정을 보낸다) / edit a card in place (the form sends the whole spec)
                undo = True
                if not op.get("id"):
                    raise ValueError("고칠 KPI 카드의 id 가 없습니다")
                report_dash.put_kpi(state, op.get("kpi") or {}, str(op.get("id")))
            elif kind == "kpi_auto":   # [추천 채우기] — 규칙으로 고른 값 컬럼 카드(LLM 없음), 못 넣는 추천은 건너뛴다 / [Fill suggestions]: rule-based cards, no LLM; a failing pick is skipped
                undo = True
                had = {(k["source"], k["col"]) for k in state.get("kpis") or []}
                added = 0
                for pick in report_dash.auto_kpis(state):
                    if (pick["source"], pick["col"]) in had:
                        continue
                    try:
                        report_dash.put_kpi(state, pick)
                    except ValueError:   # 같은 이름 · 상한 등 / e.g. a clashing name or the cap
                        continue
                    added += 1
                if not added:
                    raise ValueError("추천할 값 컬럼이 없습니다")
            elif kind == "kpi_remove":   # KPI 카드의 ✕ / the ✕ on a KPI card
                undo = True
                if not any(k["id"] == op.get("id") for k in state.get("kpis") or []):
                    raise ValueError("해당 KPI 카드가 없습니다")
                state["kpis"] = [k for k in state.get("kpis") or [] if k["id"] != op.get("id")]
            elif kind == "hl_remove":   # 강조 범례의 ✕ / the ✕ on a highlight chip
                c = chart_of(op)
                if c is not None:
                    c["highlights"] = [h for h in c.get("highlights") or [] if h["id"] != op.get("id")]
            elif kind == "chart_size":
                report_agent._chart(state, op.get("id"))["size"] = op.get("size") if op.get("size") in report_dash.SIZES else "half"
            elif kind == "title":
                report_agent.run_tool(state, "rename_dashboard", {"title": op.get("title")}, None)
            else:
                raise ValueError("알 수 없는 조작입니다")
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    if undo:
        report_dash.push_undo(sid, before)
    return _public(report_dash.save_state(sid, state, touch=bool(body.ops)))


@router.post("/dash/{sid}/undo")
def dash_undo(sid: str, body: DashActIn) -> dict:
    """직전 변경 되돌리기 — 대화로 고친 턴과 차트 삭제를 한 단계씩(최대 10). 제목과 차트 설정만 돌아가고 데이터(Source)는 그대로다."""
    # Undo the last change (an agent turn or a chart deletion), one step at a time (up to 10). Only the title and the
    # chart specs go back; sources stay.
    s = _owned(sid, body.acting_user_id)
    snap = report_dash.pop_undo(sid)
    if snap is None:
        raise HTTPException(status_code=409, detail="되돌릴 변경이 없습니다")
    state = {**s["state"], "title": snap.get("title") or s["state"]["title"], "charts": snap.get("charts") or [],
             "kpis": snap["kpis"] if "kpis" in snap else (s["state"].get("kpis") or []),
             "theme": snap["theme"] if "theme" in snap else (s["state"].get("theme") or {})}
    text = "직전 변경을 되돌렸습니다."
    # 되돌리기는 버전을 만들지도 지우지도 않고, 안내 메시지에 버전 칩(ver)도 달지 않는다(되돌린 상태는 최신 버전과 다르므로, 2026-10-13)
    # Undo neither adds nor removes versions, and its notice carries no version chip (the undone state differs from the latest version)
    report_dash.append_messages(sid, [{"role": "agent", "text": text, "trace": [], "ts": report_dash._now()}])
    return _public(report_dash.save_state(sid, state, touch=True), reply=text)


@router.get("/dash/{sid}/versions/{n}")
def dash_version(sid: str, n: int, acting_user_id: str = "") -> dict:
    """버전 미리보기(2026-10-13): 그 답변 시점의 제목 · 차트 설정 · KPI 카드 · 테마를 지금 데이터(Source)로 그린 상태. 작업본은 그대로다."""
    # Version preview (2026-10-13): that answer's title, chart specs, KPI cards and theme drawn on the current sources; the
    # working copy is untouched.
    s = _owned(sid, acting_user_id)
    v = report_dash.get_version(s["id"], n)
    if v is None:
        raise HTTPException(status_code=404, detail="해당 버전이 없습니다")
    state = report_dash.version_state(v.get("snap") or {}, s["state"])
    return {"version": {"n": v["n"], "label": v.get("label") or "", "at": v.get("at") or ""},
            "state": report_dash.pack_state(state)}


@router.post("/dash/{sid}/versions/{n}/restore")
def dash_version_restore(sid: str, n: int, body: DashActIn) -> dict:
    """[이 버전으로 이어가기](2026-10-13): 작업본을 그 버전으로 바꾼다(바뀌면 되돌리기 가능). 새 버전 'V{n}에서 이어가기' 와 안내
    메시지가 생기고 저장하지 않은 변경이 된다. 보관함 글은 [저장]에서만 갱신된다."""
    # [Continue from this version] (2026-10-13): the working copy becomes that version (undoable when it changed). A new
    # version 'V{n}에서 이어가기' and a notice are added and the change is unsaved; the library post changes only on [Save].
    s = _owned(sid, body.acting_user_id)
    restored = report_dash.restore_version(s["id"], n)
    if restored is None:
        raise HTTPException(status_code=404, detail="해당 버전이 없습니다")
    return _public(restored, reply=report_dash.VERSION_RESTORE_TEXT.format(n=n))


@router.post("/drill")
def dash_drill(body: DrillIn) -> dict:
    """드릴다운 하위 조회(2026-09-30) — 받아 둔 데이터에 더 내려갈 컬럼이 없을 때 그 Source 의 조회 SQL 을 코드로 고쳐(누른 값으로 좁히고
    다음 컬럼으로 묶기) **지금 신원의 권한으로** 다시 조회한다(LLM 없음, app/report_drill.py). 패널과 게시판 뷰어가 같이 쓰고, 결과는 화면
    상태일 뿐 저장하지 않는다. 응답: status ok(source) · choose(candidates) · none(reason, scope) · probe(drillable — 확인만, 돋보기 커서용)."""
    # Drill-down query (2026-09-30): when the fetched data has no deeper column, the source's SQL is rewritten by code
    # (narrowed by the clicked values, grouped by the next column) and re-run under the current identity's permissions
    # (no LLM, app/report_drill.py). Shared by the panel and the board viewer; the result is view state, never stored.
    # probe=true only answers whether any value on that level can drill (for the zoom cursor).
    try:
        if body.probe:
            return {"status": "probe", "drillable": report_drill.probe(body.sql, body.path, body.x, body.filters, _eff(body.acting_user_id))}
        return report_drill.drill(body.sql, body.path, body.next, body.filters, _eff(body.acting_user_id))
    except report_drill.DrillUnavailable as e:
        return {"status": "none", "reason": str(e), "scope": e.scope}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception:  # noqa: BLE001 — 실행 오류(DuckDB 등)는 안내 한 줄 / execution errors (DuckDB etc.) become one notice
        logger.warning("드릴다운 조회 실패", exc_info=True)
        return {"status": "none", "reason": report_drill.MSG_FAILED, "scope": "value"}


@router.post("/dash/{sid}/refresh")
def dash_refresh(sid: str, body: DashActIn) -> dict:
    """데이터 새로고침 — 저장된 조회 SQL 을 **지금 신원의 권한**으로 다시 실행한다 / re-run the stored SQL under the current identity's permissions"""
    s = _owned(sid, body.acting_user_id)
    state, report = report_agent.refresh_sources(s["state"], _eff(body.acting_user_id))
    return _public(report_dash.save_state(sid, state, touch=True), refreshed=report)   # 새 데이터도 저장 전까지는 작업본 / refreshed data is unsaved until [Save]


@router.post("/dash/{sid}/save")
def dash_save(sid: str, body: DashActIn) -> dict:
    """[저장] — 작업본을 내 보관함 글로(처음이면 새 글, 다시면 그 글 갱신). 2026-09-22 사용자 결정: 자동 저장 대신 저장 버튼."""
    # [Save]: the working copy becomes the library post (created the first time, updated afterwards). User decision
    # 2026-09-22: a save button instead of autosave.
    s = _owned(sid, body.acting_user_id)
    try:
        saved = report_dash.save_to_library(s["id"])
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if saved is None:
        raise HTTPException(status_code=404, detail="대시보드를 찾을 수 없습니다")
    return _public(saved, created=not s["saved"])


@router.post("/dash/{sid}/discard")
def dash_discard(sid: str, body: DashActIn) -> dict:
    """저장하지 않고 닫기 — 글이 있으면 마지막 저장본으로 되돌리고(되돌리기 스택 비움), 한 번도 저장하지 않은 초안은 세션째 지운다(session=null)."""
    # Close without saving: back to the last saved copy when a post exists (undo cleared); a never-saved draft is deleted
    # with its session (session = null).
    s = _owned(sid, body.acting_user_id)
    kept = report_dash.discard_changes(s["id"])
    if kept is None:
        return {"session": None, "deleted": True}
    return _public(kept, deleted=False)


class MailIn(BaseModel):
    acting_user_id: str = ""
    chart: str = ""              # 차트 하나(리포트)면 그 id, 비면 대시보드 전체 / one chart (a report) or, when empty, the whole dashboard
    people: list[dict] = []      # [{name, email}] 조직도 구성원·외부 주소 / org members and external addresses
    teams: list[str] = []        # 부서 이름 → 그 부서 재직자 전원 / department names → every active member of that department


MAX_MAIL_TO = 50
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_CHART_KIND = {"bar": "막대", "hbar": "가로 막대", "line": "선", "area": "영역", "pie": "원", "donut": "도넛", "kpi": "숫자"}


def _mail_recipients(people: list[dict], teams: list[str]) -> list[str]:
    """받는 사람 주소 — 고른 사람의 이메일 + 고른 부서의 재직 구성원 이메일(조직도), 중복·잘못된 주소 제외, 최대 MAX_MAIL_TO.
    The chosen people's addresses plus every active member of the chosen departments (org chart); deduplicated, invalid dropped."""
    out: list[str] = []

    def add(email: str) -> None:
        email = (email or "").strip()
        if _EMAIL_RE.match(email) and email.lower() not in {x.lower() for x in out}:
            out.append(email)

    for p in people or []:
        if isinstance(p, dict):
            add(str(p.get("email") or ""))
    wanted = {str(t).strip() for t in (teams or []) if str(t).strip()}
    if wanted:
        for m in access.list_members():
            if str(m.get("status") or "재직") == "퇴직" or str(m.get("dept") or "").strip() not in wanted:
                continue
            add(str(m.get("email") or ""))
    return out[:MAX_MAIL_TO]


def _mail_body(state: dict, charts: list[dict], title: str, summary: str, sender: str) -> str:
    """메일 본문(평문) — 제목·요약·차트별 인사이트·데이터 출처. 대화는 싣지 않는다 / plain-text body: title, summary, per-chart insights and sources; never the conversation"""
    lines = [title, ""]
    if summary:
        lines += [summary, ""]
    lines.append("[리포트]")
    for c in charts:
        kind = _CHART_KIND.get(c.get("type"), c.get("type") or "")
        insight = str(c.get("insight") or "").strip()
        lines.append(f"- {c.get('title') or ''}" + (f" ({kind})" if kind else "") + (f": {insight}" if insight else ""))
    used = {c.get("source") for c in charts}
    srcs = [x for x in state.get("sources") or [] if x.get("id") in used]
    if srcs:
        lines += ["", "[데이터 출처]"]
        for x in srcs:
            name = ", ".join(x.get("tables") or []) or x.get("label") or x.get("name") or ""
            when = str(x.get("fetched_at") or "").replace("T", " ")[:16]
            lines.append(f"- {name}" + (f" · {when}" if when else ""))
    lines += ["", f"Ai365 리포트 에이전트에서 {sender}님이 공유했습니다."]
    return "\n".join(lines)


@router.post("/dash/{sid}/mail")
def dash_mail(sid: str, body: MailIn) -> dict:
    """이메일로 공유(2026-09-22 사용자 지시) — 대시보드 전체 또는 차트 하나(리포트)를 제목·요약·인사이트 본문으로 가상 메일함(보낸 편지함)에
    기록하고, 받는 사람·제목·본문이 채워진 Outlook 웹 작성 창 링크(open_urls)를 돌려준다. 그룹웨어 메일 발송과 같은 방식이며 자동 발송은 없다.
    받는 사람 = 고른 사람 + 고른 부서의 재직자 전원. 공유는 대시보드의 변경이 아니다(dirty 유지)."""
    # Share by email (user direction 2026-09-22): the whole dashboard or one chart (a report) becomes a mail (title, summary,
    # insights) in the virtual mailbox's Sent folder, and an Outlook-web compose link with recipients/subject/body filled in
    # is returned (open_urls) — the same approach as groupware mail sending, nothing is sent automatically. Recipients = the
    # chosen people plus every active member of the chosen departments. Sharing is not a change to the dashboard.
    s = _owned(sid, body.acting_user_id)
    state = s["state"]
    if not state["charts"]:
        raise HTTPException(status_code=422, detail="차트가 없는 대시보드는 공유할 수 없습니다")
    charts, title, summary = state["charts"], state["title"], report_dash.summary_of(state)
    if body.chart:
        chart = next((c for c in charts if c["id"] == body.chart), None)
        if chart is None:
            raise HTTPException(status_code=404, detail="해당 차트가 없습니다")
        charts, title, summary = [chart], chart["title"], (str(chart.get("insight") or "").strip() or summary)
    return _mail_out(state, charts, title, summary, body)


def _mail_out(state: dict, charts: list[dict], title: str, summary: str, body: MailIn) -> dict:
    """받는 사람 해석 → 본문 작성 → 가상 메일함(보낸 편지함) 기록 → Outlook 웹 작성 링크. 대시보드 세션과 내 보관함 글이 같이 쓴다.
    Resolve recipients, compose, record in the virtual mailbox's Sent folder and build the Outlook compose link — shared by
    dashboard sessions and library posts."""
    from app import smart_seed
    to = _mail_recipients(body.people, body.teams)
    if not to:
        raise HTTPException(status_code=422, detail="받는 사람이 없습니다. 이메일, 이름 또는 부서를 추가해 주세요")
    subject = f"[Ai365 리포트] {title}"
    text = _mail_body(state, charts, title, summary, _acting_name(body.acting_user_id))
    sent = smart_seed.mail_send(to, subject, text)
    url = ("https://outlook.office.com/mail/deeplink/compose?to=" + quote(",".join(to), safe="")
           + "&subject=" + quote(subject, safe="") + "&body=" + quote(text[:1500], safe=""))
    return {"ok": True, "to": to, "subject": subject, "mail_id": (sent or {}).get("id"), "open_urls": [url]}


@router.post("/personal/{rid}/mail")
def personal_mail(rid: str, body: MailIn) -> dict:
    """내 보관함 글(리포트·대시보드)을 메일로 공유(2026-09-22 사용자 지시) — 게시판 › 내 보관함 상세의 [공유하기] › 메일로 공유.
    대시보드 세션의 …/mail 과 같은 메일(가상 메일함 기록 + Outlook 웹 작성 링크)이고 본인 글만. 옛 저장분(v1)은 차트 값으로 만든 상태를 쓴다."""
    # Share a library post by email (user direction 2026-09-22): the [Share] › email item of the board's library detail. The
    # same mail as the dashboard session's …/mail (virtual mailbox row + Outlook compose link); own posts only. Legacy (v1)
    # items use the state rebuilt from their chart values.
    owner = body.acting_user_id or ""
    p = boards.get_post(rid)
    if p is None or p.get("board") != f"me:{owner}":
        raise HTTPException(status_code=404, detail="해당 리포트가 없거나 소유자가 아닙니다")
    state = report_dash.state_of(p.get("data") or {})
    if not state["charts"]:
        raise HTTPException(status_code=422, detail="차트가 없는 글은 공유할 수 없습니다")
    title = str(p.get("title") or state["title"] or "")
    summary = str(p.get("summary") or "").strip() or report_dash.summary_of(state)
    return _mail_out(state, state["charts"], title, summary, body)


@router.get("/dash/{sid}/snapshot")
def dash_snapshot(sid: str, acting_user_id: str = "", chart: str = "") -> dict:
    """공유·저장용 데이터 — chart 가 있으면 그 차트 하나(리포트), 없으면 대시보드 전체. 대화는 싣지 않는다."""
    # Post-ready data: one chart (a report) when `chart` is given, else the whole dashboard. Never the conversation.
    s = _owned(sid, acting_user_id)
    state = s["state"]
    if not state["charts"]:
        raise HTTPException(status_code=422, detail="차트가 없는 대시보드는 저장하거나 공유할 수 없습니다")
    try:
        data = report_dash.report_data(state, chart) if chart else report_dash.dashboard_data(state)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"kind": "report" if chart else "dashboard", "title": data["title"],
            "summary": data.get("insight") or report_dash.summary_of(state), "data": data}


@router.post("/dash/{sid}/charts/{cid}/save")
def dash_save_chart(sid: str, cid: str, body: DashActIn) -> dict:
    """차트 하나를 내 보관소에 리포트로 저장(그 차트의 Source·필터 포함 — 나중에 다시 열어 고칠 수 있다)."""
    # Save one chart to my library as a report, with its source and filters so it can be reopened and edited.
    s = _owned(sid, body.acting_user_id)
    try:
        data = report_dash.report_data(s["state"], cid)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"ok": True, "report": reports.add_personal(body.acting_user_id or "", data)}
