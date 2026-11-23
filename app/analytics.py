"""데이터 분석 저장소 — DuckDB 초기화/CSV 자동 등록/스키마 요약/안전 실행 + BI 매칭/썸네일.

- data/csv/*.csv → read_csv_auto 기반 VIEW로 파일명 등록(서버 기동/에이전트 실행 시 갱신)
- 시드 테이블: pos_sales(목업 수치), dept_budget
- SELECT 단일문만 허용, LIMIT 기본 200 강제
- BI: data/bi/의 PDF(1페이지 PNG 렌더) 또는 이미지 파일 → static/bi_thumbs/ 캐시
"""
# Data analytics store — DuckDB init / CSV auto-registration / schema summary / safe execution + BI matching/thumbnails.
# - data/csv/*.csv → registered as VIEWs by filename based on read_csv_auto (refreshed on server startup/agent execution)
# - Seed tables: pos_sales (mockup figures), dept_budget
# - Only single SELECT statements allowed, LIMIT defaults to 200 (enforced)
# - BI: PDFs (1-page PNG render) or image files in data/bi/ → cached to static/bi_thumbs/

import logging
import re
import shutil
import threading
import unicodedata
from pathlib import Path

import duckdb

from app import settings

logger = logging.getLogger("ai365.analytics")

BASE_DIR = Path(__file__).resolve().parent.parent
DUCK_PATH = BASE_DIR / "data" / "analytics.duckdb"
CSV_DIR = BASE_DIR / "data" / "csv"
BI_DIR = BASE_DIR / "data" / "bi"
THUMB_DIR = BASE_DIR / "static" / "bi_thumbs"

_lock = threading.Lock()  # DuckDB 파일은 동시 라이터를 허용하지 않음
# DuckDB file does not allow concurrent writers

POS_SALES_SEED = [  # 목업 수치 그대로
# mockup figures as-is
    ("2025-08", 263_685_855, 76_316),
    ("2025-09", 247_976_316, 65_543),
]
DEPT_BUDGET_SEED = [
    ("영업", 120_000_000, 98_500_000),
    ("개발", 200_000_000, 175_200_000),
    ("마케팅", 80_000_000, 81_300_000),
    ("인사", 45_000_000, 36_700_000),
]


_tz_failed_logged = False   # TimeZone 설정 실패 로그는 한 번만 / log a TimeZone failure only once


def _connect() -> duckdb.DuckDBPyConnection:
    global _tz_failed_logged
    DUCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DUCK_PATH))
    # 모델 SQL 의 now() · current_date 도 서버 시간대와 무관하게 KST 로 계산한다(2026-10-06). 실패해도 질의는 계속한다.
    # now() / current_date in model SQL compute in KST regardless of the server zone (2026-10-06); a failure never blocks queries.
    try:
        con.execute("SET TimeZone='Asia/Seoul'")
    except Exception as e:  # noqa: BLE001 — ICU 확장이 없는 환경 등 / e.g. a build without the ICU extension
        if not _tz_failed_logged:
            _tz_failed_logged = True
            logger.debug("DuckDB TimeZone 설정 실패(무시): %s", e)
            # DuckDB TimeZone setting failed (ignored): %s
    return con


def _table_name(stem: str) -> str:
    name = unicodedata.normalize("NFC", stem).strip().lower()
    name = re.sub(r"[^0-9a-z가-힣_]+", "_", name).strip("_") or "t"
    if name[0].isdigit():
        name = "t_" + name
    return name


def _refresh_csv_views(con: duckdb.DuckDBPyConnection) -> list[str]:
    """data/csv/의 모든 CSV를 파일명 기반 VIEW로 등록, 사라진 파일의 VIEW는 제거."""
    # Register all CSVs in data/csv/ as filename-based VIEWs, and remove VIEWs for files that no longer exist.
    con.execute("CREATE TABLE IF NOT EXISTS _csv_registry(name VARCHAR PRIMARY KEY)")
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    current: dict[str, Path] = {_table_name(p.stem): p for p in sorted(CSV_DIR.glob("*.csv"))}
    registered = {r[0] for r in con.execute("SELECT name FROM _csv_registry").fetchall()}

    for name in registered - set(current):
        con.execute(f'DROP VIEW IF EXISTS "{name}"')
        con.execute("DELETE FROM _csv_registry WHERE name = ?", [name])
        logger.info("CSV VIEW 제거(파일 없음): %s", name)
        # Remove CSV VIEW (file missing): %s
    for name, path in current.items():
        esc = str(path).replace("'", "''")
        con.execute(f'CREATE OR REPLACE VIEW "{name}" AS SELECT * FROM read_csv_auto(\'{esc}\')')
        con.execute("INSERT INTO _csv_registry VALUES (?) ON CONFLICT DO NOTHING", [name])
    return sorted(current)


def init_analytics() -> None:
    """서버 기동 시 호출 — 시드 테이블 생성 + CSV VIEW 갱신."""
    # Called on server startup — create seed tables + refresh CSV VIEWs.
    with _lock, _connect() as con:
        con.execute("CREATE TABLE IF NOT EXISTS pos_sales(month VARCHAR, sales BIGINT, qty BIGINT)")
        if con.execute("SELECT COUNT(*) FROM pos_sales").fetchone()[0] == 0:
            con.executemany("INSERT INTO pos_sales VALUES (?, ?, ?)", POS_SALES_SEED)
        con.execute(
            "CREATE TABLE IF NOT EXISTS dept_budget(dept VARCHAR, budget BIGINT, spent BIGINT)"
        )
        if con.execute("SELECT COUNT(*) FROM dept_budget").fetchone()[0] == 0:
            con.executemany("INSERT INTO dept_budget VALUES (?, ?, ?)", DEPT_BUDGET_SEED)
        views = _refresh_csv_views(con)
        logger.info("DuckDB 초기화 완료 — CSV VIEW %d개: %s", len(views), views)
        # DuckDB initialization complete — %d CSV VIEWs: %s


def refresh_csv_views() -> None:
    """에이전트 실행 직전 호출 — 새로 추가된 CSV 반영."""
    # Called right before agent execution — reflect newly added CSVs.
    with _lock, _connect() as con:
        _refresh_csv_views(con)


MAX_CSV_CHARS = 20_000_000  # 업로드 CSV 최대 크기(약 20MB) — 디스크 고갈 방지
# Max uploaded-CSV size (~20MB) — prevent disk exhaustion


def register_csv(filename: str, content: str) -> str:
    """업로드된 CSV를 data/csv/에 저장하고 DuckDB VIEW로 등록. 반환: 테이블명(데이터 에이전트가 질의).

    기본(시드/카탈로그) 테이블은 덮어쓰지 않는다. 크기 상한 초과 시 거부. ValueError로 거부 사유 전달.
    """
    # Save an uploaded CSV to data/csv/ and register it as a DuckDB VIEW. Returns the table name (queried by the data agent).
    # Never overwrite built-in (seed/catalog) tables. Reject if over the size cap. Rejection reasons are raised as ValueError.
    from app import catalog  # 시드 테이블 보호용(지연 임포트로 순환 방지)
    # For seed-table protection (lazy import to avoid cycles)

    if content is not None and len(content) > MAX_CSV_CHARS:
        raise ValueError(f"파일이 너무 큽니다(최대 {MAX_CSV_CHARS // 1_000_000}MB)")
    safe = Path(unicodedata.normalize("NFC", filename or "").strip()).name  # 경로 분리자 제거(traversal 방지)
    safe = re.sub(r'[<>:"/\\|?*]+', "_", safe).strip() or "upload"  # 파일시스템 금지문자 치환
    if not safe.lower().endswith(".csv"):
        safe += ".csv"
    table = _table_name(Path(safe).stem)
    # 덮어쓰기 거부 대상: ① 시드 테이블 ② 이미 큐레이션된(워크스페이스 슬롯에 걸린) 테이블.
    # 시드는 불변 집합, 큐레이션 테이블은 동적 NODE_TABLE(슬롯→테이블)의 값으로 판정한다.
    # 아직 슬롯에 안 걸린 순수 풀(스테이징) 테이블은 동명 재업로드로 '업데이트'가 허용된다(의도된 dup 동작).
    # ②가 없으면: 워크스페이스에 큐레이션된 데이터를 다른 관리자가 동명 CSV 재업로드로 조용히 바꿀 수 있다(리뷰 confirmed 결함).
    # Reject overwrite of: ① seed tables ② already-curated tables (bound to a workspace slot).
    # Seeds are the immutable set; curated tables are judged by the values of the dynamic NODE_TABLE (slot→table).
    # A pure pool (staging) table not yet bound to a slot may be 'updated' by a same-name re-upload (the intended dup flow).
    # Without ②, one manager could silently replace another workspace's curated data via a same-name re-upload (confirmed finding).
    if table in catalog.SEED_TABLE_NAMES:
        raise ValueError(f"기본 데이터셋 '{table}'은(는) 덮어쓸 수 없습니다")
    if table in set(catalog.NODE_TABLE.values()):
        raise ValueError(f"'{table}'은(는) 워크스페이스에 큐레이션된 데이터라 덮어쓸 수 없습니다")
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    path = CSV_DIR / safe
    path.write_text(content, encoding="utf-8")
    with _lock, _connect() as con:
        _refresh_csv_views(con)
    return table


def schema_summary(sample_rows: int = 3, max_cell: int = 40,
                   allowed_tables: set[str] | None = None) -> str:
    """전체 스키마(CREATE TABLE 요약 + 테이블별 샘플 N행) — Text2SQL 프롬프트용.

    allowed_tables 가 주어지면(Phase 3 게이팅) 그 집합의 테이블만 노출한다.
    """
    # Full schema (CREATE TABLE summary + N sample rows per table) — for the Text2SQL prompt.
    # If allowed_tables is given (Phase 3 gating), only tables in that set are exposed.
    out = []
    with _lock, _connect() as con:
        tables = [
            r[0]
            for r in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' AND table_name NOT LIKE '\\_%' ESCAPE '\\' "
                "ORDER BY table_name"
            ).fetchall()
        ]
        if allowed_tables is not None:
            tables = [t for t in tables if t in allowed_tables]
        for t in tables:
            cols = con.execute(f'DESCRIBE "{t}"').fetchall()
            col_desc = ", ".join(f"{c[0]} {c[1]}" for c in cols)
            out.append(f'테이블 "{t}" ({col_desc})')
            try:
                cur = con.execute(f'SELECT * FROM "{t}" LIMIT {sample_rows}')
                names = [d[0] for d in cur.description]
                for row in cur.fetchall():
                    cells = ", ".join(
                        f"{n}={str(v)[:max_cell]}" for n, v in zip(names, row)
                    )
                    out.append(f"  샘플: {cells}")
            except Exception:
                logger.exception("샘플 조회 실패: %s", t)
                # Sample query failed: %s
    return "\n".join(out)


def describe_columns(table: str) -> list[tuple[str, str]]:
    """테이블의 (컬럼, DuckDB 타입) — 리포트 드릴다운이 다음 컬럼 후보를 고를 때 쓴다(2026-09-30). SQL 가드 유니버스의 테이블만 받는다."""
    # (column, DuckDB type) of a table, for picking the report drill-down's next column (2026-09-30). Only tables in the
    # SQL guard's universe are accepted.
    from app import catalog
    if table not in catalog.all_table_names():
        raise ValueError("존재하지 않는 테이블입니다")
    with _lock, _connect() as con:
        rows = con.execute('DESCRIBE "' + table.replace('"', '""') + '"').fetchall()
    return [(str(r[0]), str(r[1])) for r in rows]


def guard_sql(sql: str, allowed_tables: set[str] | None = None) -> str:
    """SELECT 단일문만 허용 + LIMIT 기본 200 강제. 위반 시 ValueError."""
    # Only single SELECT statements allowed + LIMIT defaults to 200 (enforced). Raises ValueError on violation.
    from app.sql_policy import select_sql
    from app import catalog
    s = select_sql(sql or "", catalog.all_table_names() if allowed_tables is None else allowed_tables)
    return f"SELECT * FROM ({s}) AS _q LIMIT {settings.SQL_ROW_LIMIT}"


def _jsonable(v):
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    return str(v)  # 날짜/Decimal 등
    # dates/Decimal, etc.


def run_select(sql: str, allowed_tables: set[str] | None = None) -> tuple[list[str], list[list]]:
    """가드를 통과한 SELECT 실행 → (컬럼, 행)."""
    # Execute a SELECT that passed the guard → (columns, rows).
    guarded = guard_sql(sql, allowed_tables)
    with _lock, _connect() as con:
        cur = con.execute(guarded)
        columns = [d[0] for d in cur.description]
        rows = [[_jsonable(v) for v in row] for row in cur.fetchmany(settings.SQL_ROW_LIMIT)]
    return columns, rows


# ---------------------------------------------------------------------------
# BI 대시보드
# BI dashboard
# ---------------------------------------------------------------------------

BI_EXTS = {".pdf", ".png", ".jpg", ".jpeg"}


def list_bi_files() -> list[Path]:
    BI_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(p for p in BI_DIR.iterdir() if p.suffix.lower() in BI_EXTS)


def bi_catalog() -> list[dict]:
    """라우팅 프롬프트용 — 파일명 + (PDF면) 첫 페이지 텍스트 일부."""
    # For the routing prompt — filename + (if PDF) a portion of the first page text.
    items = []
    for p in list_bi_files():
        entry = {"file": p.name, "hint": ""}
        if p.suffix.lower() == ".pdf":
            try:
                import fitz

                with fitz.open(p) as doc:
                    entry["hint"] = re.sub(r"\s+", " ", doc[0].get_text("text"))[:300]
            except Exception:
                logger.exception("BI PDF 텍스트 추출 실패: %s", p.name)
                # BI PDF text extraction failed: %s
        items.append(entry)
    return items


def make_thumb(file_name: str) -> dict:
    """BI 파일 1페이지 PNG 썸네일 생성(캐시) → {title, thumb_url, file}."""
    # Generate a 1-page PNG thumbnail of the BI file (cached) → {title, thumb_url, file}.
    src = BI_DIR / file_name
    if not src.exists():
        raise FileNotFoundError(file_name)
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    out = THUMB_DIR / (src.stem + ".png")
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        if src.suffix.lower() == ".pdf":
            import fitz

            with fitz.open(src) as doc:
                doc[0].get_pixmap(dpi=110).save(out)
        else:
            shutil.copyfile(src, out)
        logger.info("BI 썸네일 생성: %s", out.name)
        # BI thumbnail generated: %s
    return {"title": src.stem, "thumb_url": f"/static/bi_thumbs/{out.name}", "file": src.name}
