"""데이터 업로드 API — 데이터셋 연결에서 CSV 업로드 → data/csv/ 저장 + DuckDB 등록.

업로드된 CSV는 실제 테이블(VIEW)로 적재되어 워크스페이스가 참조하고 데이터 에이전트가 질의할 수 있다.
데모는 localhost 단일 사용자 기준 — 인증 없음.
"""
# Data upload API — upload a CSV from a dataset connection → save to data/csv/ + register in DuckDB.
# The uploaded CSV is loaded as a real table (VIEW) that workspaces reference and the data agent can query.
# The demo assumes a single localhost user — no auth.

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import analytics, kst

logger = logging.getLogger("ai365.data")

router = APIRouter(prefix="/api/data")


class CsvUpload(BaseModel):
    name: str
    content: str
    acting_user_id: str = ""  # 뷰애즈 신원 / view-as identity


@router.post("/upload-csv")
def upload_csv(body: CsvUpload) -> dict:
    """CSV 업로드 — 파일 저장 + DuckDB 등록 + **공용 CSV 풀 기록**, 테이블명 반환.

    P3: 워크스페이스 관리(2) 보유자만(안 A) — /api/resources/csv-pool 과 동일 규칙·동일 처리.
    풀 기록(add_csv_pool→rebuild_universe→set_extra_tables)을 반드시 함께 해야 업로드 테이블이
    SQL 가드 유니버스(all_table_names)에 들어가 큐레이션 전 비허가 질의가 차단된다. (리뷰 confirmed 결함 수정)"""
    # Upload a CSV — save + DuckDB register + **record in the shared CSV pool**, returning the table name.
    # P3: workspace managers only (option A) — same rule AND same handling as /api/resources/csv-pool.
    # The pool record (add_csv_pool→rebuild_universe→set_extra_tables) is required so the uploaded table enters
    # the SQL-guard universe (all_table_names); otherwise gated pre-curation queries would not be blocked.
    # (fixes a confirmed review finding)
    from app import access
    from app.resources_api import _eff, _require_ws_manage  # 지연 임포트(순환 회피) / lazy import to avoid cycles

    eff = _eff(body.acting_user_id)
    _require_ws_manage(eff)
    name = (body.name or "").strip()
    if not name.lower().endswith(".csv"):
        raise HTTPException(status_code=422, detail="CSV 파일만 업로드할 수 있습니다")
    if not (body.content or "").strip():
        raise HTTPException(status_code=422, detail="빈 파일입니다")
    try:
        table = analytics.register_csv(name, body.content)
    except ValueError as e:
        # 시드/큐레이션 테이블 충돌·크기 초과 등 거부 사유 → 409
        # Rejection reasons (seed/curated-table collision, size limit, etc.) → 409
        raise HTTPException(status_code=409, detail=str(e))
    access.add_csv_pool({"name": name, "table": table,
                         "uploaded_by": (eff or {}).get("no") if eff else "super",
                         "ts": kst.now_iso()})
    logger.info("CSV 업로드 등록(풀): %s → 테이블 %s", name, table)
    return {"ok": True, "name": name, "table": table}
