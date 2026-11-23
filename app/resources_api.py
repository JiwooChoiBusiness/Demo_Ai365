"""리소스 관리 편집 API — 서버측 권한 강제(콘솔 관할 불변식).

불변식: **생성 = 부모 노드 레벨≥2, 변경·업로드 = 대상 노드 레벨≥2.**
- `acting_user_id` ''(빈 값) → 슈퍼관리자(뷰애즈 규약, 게이팅 우회) / 숫자 → `access.effective` 로 서버가 재계산
- 조회 실패 → 전부 차단 폴백(권한 상승 방지) — app.pipeline._resolve_eff 와 동일 규약
- GET 계열은 검사하지 않는다(데모 원칙: 마스킹은 프론트, 강제는 변이에만)
- 이번 범위(P2)에서 삭제·파일 이름변경은 미구현(사용자 결정 — UI 도 잠금 처리)
"""
# Resource-management edit API — server-side permission enforcement (console jurisdiction invariant).
# Invariant: create = level>=2 on the PARENT node; modify/upload = level>=2 on the TARGET node.
# acting_user_id '' = super admin (view-as convention, bypass); digits = recomputed server-side via
# access.effective; lookup failure = all-blocked fallback (no escalation) — same contract as
# app.pipeline._resolve_eff. GETs are unchecked (demo principle: masking on the frontend, enforcement
# on mutations only). Deletion and file rename are out of scope in P2 (user decision — UI locked too).

import asyncio
import logging
import re
import unicodedata
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import access, analytics, catalog, db, kb, kb_log, kst, upload_guard
from app.kb import KNOWLEDGE_DIR

logger = logging.getLogger("ai365.resources")
router = APIRouter(prefix="/api/resources", tags=["resources"])

MAX_PDF_BYTES = 50_000_000  # 업로드 PDF 상한(50MB) — 디스크 고갈 방지 / upload cap to prevent disk exhaustion
MAX_KN_DEPTH = 3            # 지식 폴더 최대 깊이(LV.1~3) — 목업 트리와 동일 / matches the mockup tree


# ─────────────────────────────────────────────────────────────────────────────
# 권한 헬퍼 — 라우터 전체가 이 세 함수로만 검사한다(불변식 단일화)
# Permission helpers — every route checks through these three only (single invariant)
# ─────────────────────────────────────────────────────────────────────────────

def _eff(acting_user_id: str) -> dict | None:
    aid = (acting_user_id or "").strip()
    if not aid or not aid.isdigit():
        return None  # 슈퍼관리자(나) — 게이팅 없음 / super admin — no gating
    try:
        return access.effective(int(aid))
    except Exception:
        logger.warning("effective 조회 실패(no=%s) — 전부 차단으로 처리", aid, exc_info=True)
        return {"no": None, "menus": {}, "nodes": {}, "mgmt": {},
                "read": {"p_know": False, "p_data": False, "p_auto": False, "p_klocal": False}}   # p_klocal(2026-09-29) 지식 관리 · Local / Knowledge · Local


def _require_super(eff: dict | None) -> None:
    if eff is not None:
        raise HTTPException(status_code=403, detail="슈퍼관리자 전용 기능입니다")


def _require_manage(eff: dict | None, node_id: str) -> None:
    """대상(생성은 부모) 노드 레벨≥2 강제. 슈퍼(eff=None)는 통과."""
    # Enforce level>=2 on the target (parent, for creation). Super (eff=None) passes.
    if eff is None:
        return
    if ((eff.get("nodes") or {}).get(node_id, 0)) >= 2:
        return
    raise HTTPException(status_code=403, detail="해당 리소스의 관리 권한이 필요합니다")


# ─────────────────────────────────────────────────────────────────────────────
# 지식 트리 헬퍼
# Knowledge-tree helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_folder(tree: list[dict], fid: str, depth: int = 1):
    """(폴더 dict, 깊이) 반환 — 없으면 None."""
    for n in tree:
        if n.get("id") == fid:
            return n, depth
        found = _find_folder(n.get("folders") or [], fid, depth + 1)
        if found:
            return found
    return None


def _kn_snapshot() -> dict:
    """변이 응답에 싣는 갱신 스냅샷 — 프론트 applyResourceSync 가 그대로 반영한다."""
    # Fresh snapshot returned by mutations — applied verbatim by the frontend's applyResourceSync.
    return {"knowledge": catalog.knowledge_tree()}


class FolderBody(BaseModel):
    name: str
    parent_id: str | None = None
    acting_user_id: str = ""


class RenameBody(BaseModel):
    name: str
    acting_user_id: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# 지식 관리 (P2) — 폴더 생성/이름변경 + 파일 업로드(실 RAG 인덱싱)
# Knowledge (P2) — folder create/rename + file upload (real RAG indexing)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/knowledge/folders")
def create_folder(body: FolderBody) -> dict:
    """폴더 추가 — 하위: 부모 폴더 관리(2) / 루트: p_know 관리(2) (사용자 확정: 슈퍼 아님)."""
    # Create a folder — subfolder: manage(2) on the parent / root: manage(2) on p_know (user decision: not super-only).
    eff = _eff(body.acting_user_id)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="폴더 이름을 입력하세요")
    tree = access.load_knowledge()
    node = {"id": f"f_u{uuid.uuid4().hex[:8]}", "label": name, "folders": [], "files": []}
    if body.parent_id:
        found = _find_folder(tree, body.parent_id)
        if not found:
            raise HTTPException(status_code=404, detail="부모 폴더를 찾을 수 없습니다")
        parent, depth = found
        if depth >= MAX_KN_DEPTH:
            raise HTTPException(status_code=422, detail=f"폴더는 LV.{MAX_KN_DEPTH}까지만 만들 수 있습니다")
        _require_manage(eff, body.parent_id)
        parent.setdefault("folders", []).append(node)
    else:
        _require_manage(eff, "p_know")
        tree.append(node)
    access.save_knowledge(tree)  # 내부에서 rebuild_universe — 새 폴더가 즉시 권한 노드가 된다
    return {"ok": True, "id": node["id"], **_kn_snapshot()}


@router.patch("/knowledge/folders/{fid}")
def rename_folder(fid: str, body: RenameBody) -> dict:
    eff = _eff(body.acting_user_id)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="이름을 입력하세요")
    tree = access.load_knowledge()
    found = _find_folder(tree, fid)
    if not found:
        raise HTTPException(status_code=404, detail="폴더를 찾을 수 없습니다")
    _require_manage(eff, fid)
    found[0]["label"] = name
    access.save_knowledge(tree)
    return {"ok": True, **_kn_snapshot()}


@router.post("/knowledge/files")
async def upload_file(folder_id: str = Form(...), acting_user_id: str = Form(""),
                      file: UploadFile = File(...), force: str = Form("")) -> dict:
    """PDF 업로드 — 대상 폴더 관리(2) 필요. 저장 후 백그라운드 RAG 인덱싱(kb.index_one_background).

    파일명이 시스템 전역 키(kb_docs·NODE_FILE)라 전역 중복은 409. NFC 정규화 + 경로/금지문자 제거."""
    # Upload a PDF — requires manage(2) on the target folder. Saved, then RAG-indexed in the background.
    # The filename is a global key (kb_docs·NODE_FILE), so duplicates are 409. NFC-normalized, path-stripped.
    eff = _eff(acting_user_id)
    tree = access.load_knowledge()
    found = _find_folder(tree, folder_id)
    if not found:
        raise HTTPException(status_code=404, detail="폴더를 찾을 수 없습니다")
    _require_manage(eff, folder_id)
    raw = Path(unicodedata.normalize("NFC", file.filename or "")).name  # 경로 분리자 제거(traversal 방지)
    safe = re.sub(r'[<>:"/\\|?*]+', "_", raw).strip()
    if not safe.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="PDF 파일만 업로드할 수 있습니다")
    if safe in catalog.FILE_NODE or (KNOWLEDGE_DIR / safe).exists():
        raise HTTPException(status_code=409, detail=f"같은 이름의 문서가 이미 있습니다: {safe} — 이름을 바꿔 업로드하세요")
    data = await file.read()
    actor = _actor_name(acting_user_id)   # AI Batch Log 의 등록자 / the uploader shown in the AI Batch Log
    if len(data) > MAX_PDF_BYTES:
        # 용량 초과는 인덱싱 전 거부 — 이력에는 오류 행으로 남긴다(2026-09-16) / rejected before indexing, logged as an error row
        kb_log.fail(safe, actor, f"허용 용량 초과 ({len(data) / 1_000_000:.0f}MB/{MAX_PDF_BYTES // 1_000_000}MB)")
        raise HTTPException(status_code=422, detail=f"파일이 너무 큽니다(최대 {MAX_PDF_BYTES // 1_000_000}MB)")
    if not data:
        raise HTTPException(status_code=422, detail="빈 파일입니다")
    # 업로드 검증(2026-10-01, 관리 센터 › 로컬 설정 › 업로드 검증): 보안 키워드가 든 문서는 일반 사용자 · 관리자 = 차단(키워드는 알리지 않음,
    # AI Batch Log 에 오류 행), 슈퍼어드민 = 경고(키워드 · 설명 · 위치) 후 force 로 다시 보내면 업로드. force 도 슈퍼인지 다시 본다.
    # Upload validation (2026-10-01): documents with a security keyword are blocked for users and admins (keywords withheld,
    # an error row in the AI Batch Log); the super admin is warned and may resend with force, re-checked as super here.
    check = await asyncio.to_thread(upload_guard.verdict, safe, data, eff is None, force.strip().lower() in ("1", "true"))
    if check["result"] == "blocked":
        kb_log.fail(safe, actor, upload_guard.BLOCK_LOG_REASON)
        raise HTTPException(status_code=403, detail={"code": "upload_blocked", "file": safe})
    if check["result"] == "warn":
        raise HTTPException(status_code=409, detail={"code": "upload_warn", "file": safe, "hits": check["hits"]})
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    path = KNOWLEDGE_DIR / safe
    path.write_bytes(data)
    node_id = f"kf_u{uuid.uuid4().hex[:8]}"
    found[0].setdefault("files", []).append([node_id, safe])
    access.save_knowledge(tree)  # 트리 등재 → 부모 폴더 grant 캐스케이드로 권한 자동 상속
    kb_log.pending(safe, actor)   # 대기 행 → 인덱서가 진행 중/완료/오류로 바꾼다 / pending row, flipped by the indexer
    kb.index_one_background(path, actor)
    return {"ok": True, "node": node_id, "file": safe, **_kn_snapshot()}


def _actor_name(acting_user_id: str) -> str:
    """뷰애즈 사용자 번호 → 조직도 이름(없으면 '관리자'; 빈 값 = 슈퍼관리자) / view-as member number → org-chart name"""
    aid = (acting_user_id or "").strip()
    if not aid.isdigit():
        return "관리자"
    try:
        for m in access.list_members():
            if str(m.get("no")) == aid:
                return str(m.get("name") or aid)
    except Exception:  # noqa: BLE001
        pass
    return aid


@router.get("/knowledge/batch-log")
def batch_log(from_: str = Query("", alias="from"), to: str = "", status: str = "", page: int = 1, size: int = 20) -> dict:
    """AI Batch Log(2026-09-16): 인덱싱 처리 이력 — 처리 시작일 범위·상태 필터, 페이지(기본 20건) / indexing history with filters and paging"""
    return kb_log.list_logs(from_, to, status, page, size)


@router.get("/knowledge/index-status")
def index_status() -> dict:
    """인덱싱 완료된 문서 파일명 목록 — 프론트 idxState 폴링용(kb_docs 등재 = done)."""
    # Filenames of fully indexed documents — for frontend idxState polling (present in kb_docs = done).
    with db._conn() as conn:
        docs = [r["doc"] for r in conn.execute("SELECT doc FROM kb_docs").fetchall()]
    return {"docs": docs}


@router.get("/knowledge/file/{doc}")
def knowledge_file(doc: str) -> FileResponse:
    """지식 원본 PDF 서빙 — 리소스 패널의 청크 원본 미리보기용.

    data/knowledge/ 에 실존하는 .pdf 파일명만 허용(경로 조각·상위 이동 차단)."""
    # Serves the original knowledge PDF — for the resource panel's chunk-source preview.
    # Only .pdf filenames that actually exist in data/knowledge/ are allowed (path segments / traversal rejected).
    name = Path(doc).name
    path = KNOWLEDGE_DIR / name
    if name != doc or not name.lower().endswith(".pdf") or not path.is_file():
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")
    return FileResponse(path, media_type="application/pdf")


@router.get("/data/preview")
def data_preview(table: str, acting_user_id: str = "", limit: int = 5) -> dict:
    """테이블 샘플 미리보기(상위 5행) — 데이터 3분할 런처의 '체크 즉시 미리보기'용(2026-08-19).

    ⚠ 이 라우터의 "GET 미검사" 관례의 **첫 예외** — 실제 데이터 내용을 내려보내므로
    권한(∩ allowed_tables)을 검사한다(트리 게이팅과 독립인 서버측 이중 방어).
    table은 all_table_names() 유니버스 검증을 통과한 값만 SQL에 들어간다(식별자 안전).
    """
    # Table sample preview (top 5 rows) — for the data launcher's check-to-preview (2026-08-19).
    # ⚠ The FIRST exception to this router's "GETs are unchecked" convention — it returns actual
    # data content, so it enforces permissions (∩ allowed_tables; server-side defense independent
    # of the tree's gating). `table` only reaches SQL after the all_table_names() universe check.
    t = (table or "").strip()
    if t not in catalog.all_table_names():
        raise HTTPException(status_code=404, detail="존재하지 않는 테이블입니다")
    eff = _eff(acting_user_id)
    if eff is not None and t not in catalog.allowed_tables(eff):
        raise HTTPException(status_code=403, detail="이 데이터를 열람할 권한이 없습니다")
    analytics.refresh_csv_views()   # CSV 테이블은 VIEW 자가 등록(데이터 에이전트와 동일 관례)
    # CSV tables self-register as views (same convention as the data agent)
    n = max(1, min(int(limit or 5), 50))   # 데이터 탐색기(3차)는 최대 50행 / the data explorer (round 3) reads up to 50 rows
    cols, rows = analytics.run_select(f'SELECT * FROM "{t}" LIMIT {n}')
    # 스키마 탭(3차 데이터 탐색기) — information_schema는 뷰(CSV)도 포함. 비면 컬럼명만으로 폴백.
    # Schema tab (round-3 data explorer) — information_schema covers views (CSV) too; falls back to column names.
    schema: list[dict] = []
    try:
        lit = t.replace("'", "''")
        _, srows = analytics.run_select(
            "SELECT column_name, data_type FROM information_schema.columns "
            f"WHERE table_name = '{lit}' ORDER BY ordinal_position LIMIT 200")
        schema = [{"name": str(r[0]), "type": str(r[1])} for r in srows]
    except Exception:  # noqa: BLE001 — 스키마 조회 실패는 미리보기에 영향 없음 / never blocks the preview
        schema = []
    if not schema:
        schema = [{"name": c, "type": ""} for c in cols]
    loc = catalog.data_locate(table=t) or {}
    return {"table": t, "label": loc.get("label") or t, "ws": loc.get("wsName") or "",
            "kind": loc.get("kind") or "DB", "columns": cols, "rows": rows, "schema": schema}


# ─────────────────────────────────────────────────────────────────────────────
# 데이터 2계층 (P3) — 연결(슈퍼) · CSV 풀(워크스페이스 관리자) · 워크스페이스 생성(슈퍼) · 슬롯(ws 관리)
# Two-tier data ops (P3) — connections (super) · CSV pool (workspace managers) ·
# workspace creation (super) · slot curation (manage on that workspace)
# ─────────────────────────────────────────────────────────────────────────────

def _require_ws_manage(eff: dict | None) -> None:
    """CSV 풀 반입 권한: 워크스페이스 관리(2) 보유자 누구나(=mgmt.p_data) — 안 A(확정)."""
    # CSV-pool intake permission: anyone holding manage(2) on any workspace (= mgmt.p_data) — option A (decided).
    if eff is None:
        return
    if (eff.get("mgmt") or {}).get("p_data"):
        return
    raise HTTPException(status_code=403, detail="데이터 워크스페이스의 관리 권한이 필요합니다")


def _data_snapshot() -> dict:
    return {"workspaces": access.list_workspaces(), "datasets": catalog.datasets(),
            "tables_catalog": sorted(catalog.all_table_names())}


class ConnectionsIn(BaseModel):
    connections: list[dict]
    acting_user_id: str = ""


class CsvPoolIn(BaseModel):
    name: str
    content: str
    acting_user_id: str = ""


class WorkspaceIn(BaseModel):
    name: str
    team: str = ""
    desc: str = ""
    acting_user_id: str = ""


class SlotIn(BaseModel):
    kind: str                 # 'bi' | 'sql' | 'csv'
    name: str
    src: str = ""
    upd: str = ""
    table: str | None = None  # sql·csv 슬롯의 DuckDB 테이블 / DuckDB table for sql·csv slots
    file: str | None = None   # csv=풀 파일명, bi=BI 파일명(선택) / csv=pool filename, bi=BI filename (optional)
    workspaceId: str = ""     # BI 임베드 정보(모의) / mock Power BI embed info
    reportId: str = ""
    pageId: str = ""
    desc: str = ""
    acting_user_id: str = ""


@router.get("/connections")
def get_connections() -> dict:
    return {"connections": access.list_connections()}


@router.put("/connections")
def put_connections(body: ConnectionsIn) -> dict:
    """데이터셋 연결 카드 전체 교체 — 슈퍼 전용(자격증명 계층)."""
    # Replace all dataset-connection cards — super only (the credential tier).
    _require_super(_eff(body.acting_user_id))
    access.replace_connections(body.connections)
    return {"ok": True, "connections": access.list_connections()}


@router.get("/csv-pool")
def get_csv_pool() -> dict:
    return {"pool": access.list_csv_pool()}


@router.post("/csv-pool")
def upload_csv_pool(body: CsvPoolIn) -> dict:
    """CSV 풀 반입 — 워크스페이스 관리 보유자 누구나. 풀 항목은 노드가 없어 큐레이션(슬롯 배치) 전까지
    뷰어·챗봇에 노출되지 않지만, SQL 가드 유니버스(all_table_names)에는 포함돼 우회 질의도 차단된다."""
    # CSV-pool intake — any workspace manager. Pool entries have no node, so they stay invisible to the
    # viewer/chatbot until curated into a slot, yet they ARE in the SQL-guard universe (all_table_names),
    # so bypass queries are blocked too.
    from app import analytics
    eff = _eff(body.acting_user_id)
    _require_ws_manage(eff)
    try:
        table = analytics.register_csv(body.name, body.content)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    access.add_csv_pool({"name": body.name, "table": table,
                         "uploaded_by": (eff or {}).get("no") if eff else "super",
                         "ts": kst.now_iso()})
    return {"ok": True, "table": table, "pool": access.list_csv_pool()}


@router.post("/workspaces")
def create_workspace(body: WorkspaceIn) -> dict:
    """워크스페이스 생성 — 슈퍼 전용(확정). 빈 BI/CSV/DB 슬롯으로 시작."""
    # Create a workspace — super only (decided). Starts with empty BI/CSV/DB slots.
    _require_super(_eff(body.acting_user_id))
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="워크스페이스 이름을 입력하세요")
    ws = access.list_workspaces()
    new = {"id": f"ws_u{uuid.uuid4().hex[:8]}", "name": name, "team": body.team,
           "desc": body.desc or "사용자 정의 워크스페이스", "bi": [], "csv": [], "sql": []}
    ws.append(new)
    access.replace_workspaces(ws)
    return {"ok": True, "id": new["id"], **_data_snapshot()}


@router.post("/workspaces/{wid}/slots")
def add_slot(wid: str, body: SlotIn) -> dict:
    """슬롯 큐레이션 — 그 워크스페이스 관리(2). DB는 any-table(화이트리스트 없음, 큐레이터 신뢰),
    CSV는 풀에서 선택, BI는 1연결=1대시보드(동일 리포트/파일 중복 409)."""
    # Slot curation — manage(2) on that workspace. DB slots accept any table (no whitelist — curator trust);
    # CSV slots pick from the pool; BI is one dashboard per connection (duplicate report/file → 409).
    eff = _eff(body.acting_user_id)
    ws = access.list_workspaces()
    w = next((x for x in ws if x.get("id") == wid), None)
    if not w:
        raise HTTPException(status_code=404, detail="워크스페이스를 찾을 수 없습니다")
    _require_manage(eff, wid)
    kind = (body.kind or "").strip()
    if kind not in ("bi", "sql", "csv"):
        raise HTTPException(status_code=422, detail="kind 는 bi/sql/csv 중 하나여야 합니다")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="이름을 입력하세요")
    item: dict = {"name": name, "src": body.src or "", "upd": body.upd or ""}
    if kind == "sql":
        table = (body.table or "").strip()
        if not table:
            raise HTTPException(status_code=422, detail="테이블을 선택하거나 입력하세요")
        item["table"] = table
    elif kind == "csv":
        table = (body.table or "").strip()
        pool_tables = {e.get("table") for e in access.list_csv_pool()}
        if not table or table not in pool_tables:
            raise HTTPException(status_code=422, detail="CSV 풀에 있는 파일만 선택할 수 있습니다")
        item["table"] = table
        if body.file:
            item["file"] = body.file
    else:  # bi — 1연결 = 1대시보드 / one connection = one dashboard
        dup = any(
            (body.reportId and it.get("reportId") == body.reportId) or
            (body.file and it.get("file") == body.file)
            for it in (w.get("bi") or [])
        )
        if dup:
            raise HTTPException(status_code=409, detail="같은 리포트가 이미 이 워크스페이스에 등록돼 있습니다 (BI 1연결=1대시보드)")
        for k in ("workspaceId", "reportId", "pageId", "desc"):
            v = getattr(body, k)
            if v:
                item[k] = v
        if body.file:
            item["file"] = body.file
    item["node"] = f"sl_u{uuid.uuid4().hex[:8]}"
    w.setdefault(kind, []).append(item)
    access.replace_workspaces(ws)
    return {"ok": True, "node": item["node"], **_data_snapshot()}


@router.delete("/workspaces/{wid}/slots/{node_id}")
def delete_slot(wid: str, node_id: str, acting_user_id: str = "") -> dict:
    """슬롯 제거(큐레이션 항목 — 물리 자원 삭제 아님) — 대상 슬롯 노드 관리(2)."""
    # Remove a slot (a curated entry — no physical deletion) — manage(2) on the slot node.
    eff = _eff(acting_user_id)
    ws = access.list_workspaces()
    w = next((x for x in ws if x.get("id") == wid), None)
    if not w:
        raise HTTPException(status_code=404, detail="워크스페이스를 찾을 수 없습니다")
    _require_manage(eff, node_id)
    removed = False
    for kind in ("bi", "sql", "csv"):
        items = w.get(kind) or []
        keep = [it for it in items if it.get("node") != node_id]
        if len(keep) != len(items):
            w[kind] = keep
            removed = True
    if not removed:
        raise HTTPException(status_code=404, detail="슬롯을 찾을 수 없습니다")
    access.replace_workspaces(ws)
    return {"ok": True, **_data_snapshot()}
