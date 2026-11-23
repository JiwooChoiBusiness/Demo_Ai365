"""데이터 분석 Agent — DuckDB Text2SQL(시드 SQL+CSV) + BI 대시보드 매칭.

모드 판단(SQL/BI)과 SQL 생성을 한 번의 json_mode 호출로 처리해 호출 수를 아낀다.
"""
# Data analysis Agent — DuckDB Text2SQL (seed SQL + CSV) + BI dashboard matching.
# Handles mode decision (SQL/BI) and SQL generation in a single json_mode call to save the number of calls.

import asyncio
import json
import logging
import re

from app import analytics, catalog, llm
from app.agents import AgentResult, Message

logger = logging.getLogger("ai365.agents.data")

# 2단 플래닝(2026-08-31, 실물 파이프라인 정합): ① 개요 플래너(경량) — 모드 판단(SQL/BI) + 질의 분해
# + 테이블 목록(개요)에서 소스 선택 → ② SQL 작성기 — 선택 테이블의 스키마만 받아 하위 질의별 SQL 작성
# (복합 질문이면 최대 3개). 종전의 단일 호출(모드+SQL 동시)을 다이어그램의 "overview → schema → query"
# 흐름으로 분리했다.
# Two-stage planning (production-pipeline alignment): ① lite overview planner — mode (SQL/BI) + query
# decomposition + table-source selection from the catalog overview → ② SQL writer — receives only the
# selected tables' schemas and writes one SQL per sub-query (up to 3 for compound questions).
OVERVIEW_SYSTEM = """너는 사내 데이터 분석 플래너(1단계)다. 사용자의 질문을 보고 JSON으로만 출력한다.

출력 형식:
{"mode": "sql" | "bi", "bi_file": null, "subqueries": ["하위 질의", ...], "tables": ["테이블명", ...]}

규칙:
- 질문이 대시보드/현황판/Dashboard 화면을 보여달라는 요청이고 [BI 파일 목록]에 적합한 파일이 있으면 mode="bi", bi_file에 해당 파일명을 정확히 그대로 넣는다(subqueries·tables는 빈 배열).
- 그 외 수치 조회·집계·분석이면 mode="sql": 질문이 여러 주제를 담고 있으면 1~3개의 독립 질의로 분해해 subqueries에 넣고, 단순하면 다듬은 1개만 넣는다.
- tables에는 [테이블 목록]에서 필요한 테이블을 이름 그대로 고른다(최대 6개). 확신이 없으면 관련될 법한 것을 넉넉히 고른다."""

SQL_SYSTEM = """너는 사내 데이터 분석 에이전트의 SQL 작성기(2단계)다. JSON으로만 출력한다.

출력 형식:
{"queries": [{"sql": "SELECT ...", "explanation": "쿼리 설명"}, ...]}

규칙:
- [하위 질의] 각각에 대해 [스키마]의 테이블만 사용해 DuckDB SQL을 1개씩 작성한다(최대 3개).
- SQL은 SELECT 단일문만 허용된다(INSERT/UPDATE/DELETE/DDL 금지). 집계·정렬을 적절히 사용하고, 컬럼명·테이블명은 스키마 그대로 쓴다.
- explanation은 무엇을 조회하는지 한 문장의 한국어로 쓴다."""

COMMENT_SYSTEM = """너는 데이터 분석가다. SQL 실행 결과를 보고 사용자의 질문에 대한 한국어 분석 코멘트를 2~4문장으로 작성하라.
수치는 결과 그대로 인용하고, 눈에 띄는 추세·최댓값·증감 등을 짚어라. 마크다운 없이 평문으로 쓴다."""


def _table_overview(allowed_tables: set[str] | None) -> str:
    """1단계용 경량 테이블 목록(개요) — 이름 + 카탈로그 라벨만(전체 스키마는 2단계에서 선택분만)."""
    # Lightweight table overview for stage 1 — names + catalog labels only (full schemas go to stage 2).
    labels = {t: l for _, l, t in catalog.DATA_TABLES}
    names = sorted(catalog.all_table_names() if allowed_tables is None else allowed_tables)
    return "\n".join(f"- {t}" + (f": {labels[t]}" if t in labels else "") for t in names) or "(없음)"


def _overview_plan(query: str, context: list[Message],
                   allowed_tables: set[str] | None = None,
                   allowed_bi: set[str] | None = None) -> dict:
    """1단계: 모드 판단 + 질의 분해 + 테이블 소스 선택(개요 기반)."""
    # Stage 1: mode decision + query decomposition + table-source selection over the overview.
    bi_items = analytics.bi_catalog()
    if allowed_bi is not None:
        bi_items = [b for b in bi_items if b.get("file") in allowed_bi]
    bi_text = "\n".join(
        f"- {b['file']}" + (f" (내용: {b['hint'][:120]})" if b["hint"] else "") for b in bi_items
    ) or "(없음)"
    recent = context[:-1][-4:]
    prompt = recent + [
        {
            "role": "user",
            "content": f"[테이블 목록]\n{_table_overview(allowed_tables)}\n\n[BI 파일 목록]\n{bi_text}\n\n[질문]\n{query}",
        }
    ]
    return llm.generate(prompt, system=OVERVIEW_SYSTEM, json_mode=True, tier="lite")


def _sql_plan(subqueries: list[str], context: list[Message],
              allowed_tables: set[str] | None = None) -> list[dict]:
    """2단계: 선택 테이블 스키마만 받아 하위 질의별 SQL 작성(최대 3개)."""
    # Stage 2: writes one SQL per sub-query (≤3) with only the selected tables' schemas.
    schema = analytics.schema_summary(allowed_tables=allowed_tables)
    listing = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(subqueries))
    recent = context[:-1][-4:]
    prompt = recent + [
        {"role": "user", "content": f"[스키마]\n{schema}\n\n[하위 질의]\n{listing}"}
    ]
    out = llm.generate(prompt, system=SQL_SYSTEM, json_mode=True, tier="lite")
    queries = out.get("queries") if isinstance(out, dict) else None
    if not isinstance(queries, list):
        return []
    return [q for q in queries if isinstance(q, dict) and (q.get("sql") or "").strip()][:3]


def _comment(query: str, executed: list[dict]) -> str:
    """분석 코멘트 — 복수 쿼리 결과(질의 분해)를 한 번에 요약한다."""
    # Analysis comment — summarizes multiple query results (decomposition) in one call.
    blocks = []
    for i, r in enumerate(executed, 1):
        preview = {"columns": r["columns"], "rows": r["rows"][:20], "total_rows": len(r["rows"])}
        blocks.append(f"[실행 {i}] SQL: {r['sql']}\n결과: " + json.dumps(preview, ensure_ascii=False))
    return llm.generate(
        f"[질문]\n{query}\n\n" + "\n\n".join(blocks),
        system=COMMENT_SYSTEM,
        tier="lite",  # 중간 산출물(최종 답변은 취합 Agent가 main으로 작성)
        # Intermediate output (the final answer is written by the aggregation Agent with main).
    )


def _denied(label: str) -> AgentResult:
    """현재 사용자에게 해당 도메인/리소스 열람 권한이 없을 때."""
    # When the current user has no read permission for the domain/resource.
    return {
        "status": "blocked", "text": "", "extras": {},
        "fail_reason": f"현재 사용자에게 {label} 접근 권한이 없습니다.",
        "alternative": "권한이 있는 데이터에 한해 질의할 수 있습니다. 관리자에게 권한을 요청하세요.",
    }


def _disallowed_table_refs(sql: str, allowed: set[str]) -> list[str]:
    """게이팅 유니버스 중 허용되지 않은 테이블이 SQL에 참조됐는지 검사(방어).

    스키마를 허용 테이블로 축소하므로 보통 발생하지 않지만, 모델이 비허용 테이블명을
    직접 만들어 내는 경우를 단어 경계 매칭으로 차단한다.
    """
    # Defense: check whether the SQL references any non-allowed table in the gating universe.
    # Usually does not happen since the schema is reduced to allowed tables, but blocks the case
    # where the model fabricates a non-allowed table name, using word-boundary matching.
    low = (sql or "").lower()
    disallowed = catalog.all_table_names() - set(allowed)
    return [t for t in disallowed if re.search(r"\b" + re.escape(t.lower()) + r"\b", low)]


def _match_bi_file(name: str | None) -> str | None:
    if not name:
        return None
    files = {p.name: p.name for p in analytics.list_bi_files()}
    if name in files:
        return name
    lowered = name.lower()
    for f in files:  # 확장자 누락/부분 일치 보정
        # Correction for missing extension / partial match.
        if f.lower() == lowered or lowered in f.lower() or f.lower().startswith(lowered.rsplit(".", 1)[0]):
            return f
    return None


def _run_sync(query: str, context: list[Message], eff: dict | None = None,
              scope_files: dict | None = None) -> AgentResult:
    analytics.refresh_csv_views()  # 새로 추가된 CSV 즉시 반영
    # Immediately reflect newly added CSV.

    # ---- 권한 게이팅(Phase 3) + 스마트 파일 검색범위 좁히기 (eff=None 슈퍼는 권한 우회) ----
    # ---- Permission gating (Phase 3) + smart-file search narrowing (eff=None super bypasses permission) ----
    # 권한상 허용 테이블/BI — None=슈퍼=전체
    # Permission-allowed tables/BI — None = super = all
    allowed_tables: set[str] | None = None if eff is None else catalog.allowed_tables(eff)
    allowed_bi: set[str] | None = None if eff is None else catalog.allowed_bi_files(eff)
    if eff is not None and not catalog.domain_readable(eff, "p_data"):
        logger.info("데이터 도메인 차단 — 권한 없음")
        return _denied("데이터 분석")
    # 스마트 파일 선택 → 권한 ∩ 선택으로 검색범위 제한(선택 없으면 권한 전체)
    # Smart-file selection → narrow to permission ∩ selection (no selection = full permission)
    sel_t = {t for t in ((scope_files or {}).get("data_tables") or [])}
    if sel_t:
        allowed_tables = sel_t if allowed_tables is None else (allowed_tables & sel_t)
    sel_bi = {b for b in ((scope_files or {}).get("data_bi") or [])}
    if sel_bi:
        allowed_bi = sel_bi if allowed_bi is None else (allowed_bi & sel_bi)
    # 한 축만 선택됐으면 나머지 축은 **제외**(fail-closed) — 테이블만 지정한 워크플로우 노드/스마트 파일
    # 선택에서 비선택 축(BI)이 "선택 없음=전체"로 남아 지정하지 않은 대시보드가 플래너에 노출·호출되던
    # 결함(2026-08-24 사용자 제보: 팀장 워크플로우가 미지정 대시보드를 콜). 반대 방향(BI만 선택 → 전체
    # 테이블 SQL)도 동일하게 막는다. 선택이 전혀 없으면 종전대로 권한 전체.
    # If only one axis was selected, the OTHER axis is excluded (fail-closed) — with tables-only
    # selections (workflow nodes / smart files) the unselected BI axis used to stay "no selection =
    # everything", exposing unchosen dashboards to the planner (user report 2026-08-24). The reverse
    # (BI-only → full-table SQL) is blocked the same way. No selection at all keeps full permission.
    if sel_t and not sel_bi:
        allowed_bi = set()
    elif sel_bi and not sel_t:
        allowed_tables = set()

    try:
        plan = _overview_plan(query, context, allowed_tables, allowed_bi)
    except Exception as e:
        logger.exception("플래너 호출 실패")
        return {
            "status": "failed", "text": "", "extras": {},
            "fail_reason": f"데이터 분석 계획 수립에 실패했습니다: {e}",
            "alternative": "잠시 후 다시 시도해 주세요.",
        }

    # ---- BI 대시보드 ----
    # ---- BI dashboard ----
    if plan.get("mode") == "bi":
        matched = _match_bi_file(plan.get("bi_file"))
        if matched and allowed_bi is not None and matched not in allowed_bi:
            logger.info("BI 차단 — 권한 없는 대시보드(%s)", matched)
            return _denied("해당 대시보드")
        if matched:
            try:
                info = analytics.make_thumb(matched)
            except Exception as e:
                logger.exception("썸네일 생성 실패")
                return {
                    "status": "failed", "text": "", "extras": {},
                    "fail_reason": f"대시보드 썸네일 생성에 실패했습니다: {e}",
                    "alternative": "data/bi/ 파일 형식을 확인해 주세요.",
                }
            return {
                "status": "dashboard",
                "text": f"'{info['title']}' 대시보드를 찾았습니다. 썸네일을 함께 표시합니다.",
                "extras": info,
            }
        logger.info("BI 매칭 실패(bi_file=%r) — SQL 모드 폴백 없음", plan.get("bi_file"))
        return {
            "status": "not_found", "text": "", "extras": {},
            "fail_reason": "요청하신 대시보드에 해당하는 BI 파일을 찾지 못했습니다.",
            "alternative": "보유 대시보드: " + ", ".join(p.stem for p in analytics.list_bi_files()),
        }

    # ---- Text2SQL (2단계: 선택 테이블 스키마 → 하위 질의별 SQL, 최대 3개) ----
    # ---- Text2SQL (stage 2: selected-table schemas → one SQL per sub-query, ≤3) ----
    subqueries = [str(s).strip() for s in (plan.get("subqueries") or []) if str(s).strip()][:3] or [query]
    # 개요가 고른 테이블(검증: 게이팅 유니버스∩권한) — 비면 권한 전체 스키마로
    # Overview-picked tables (validated against the gating universe ∩ permission); empty = full schema
    universe = catalog.all_table_names() if allowed_tables is None else allowed_tables
    sel_tables = {str(t).strip() for t in (plan.get("tables") or []) if str(t).strip() in universe}
    stage2_allowed = sel_tables or allowed_tables

    def _write_and_run(schema_tables: set[str] | None) -> tuple[list[dict], str]:
        """SQL 작성→가드→권한 방어→실행. (성공 결과 목록, 마지막 오류) 반환."""
        # Write→guard→permission defense→execute; returns (successes, last error).
        try:
            qs = _sql_plan(subqueries, context, schema_tables)
        except Exception as e:  # noqa: BLE001
            logger.warning("SQL 작성기 실패: %s", e)
            return [], str(e)
        ok_list, last_err = [], ""
        for q in qs:
            raw_sql = q.get("sql") or ""
            try:
                guarded = analytics.guard_sql(raw_sql, allowed_tables)
                # 권한 게이팅: 방어는 항상 **권한 전체** 기준(개요 좁히기는 소프트 안내일 뿐)
                # Permission defense always checks the FULL permission set (narrowing is soft guidance)
                if allowed_tables is not None:
                    bad = _disallowed_table_refs(guarded, allowed_tables)
                    if bad:
                        logger.info("SQL 차단 — 권한 없는 테이블 참조: %s", bad)
                        last_err = "권한 없는 테이블 참조"
                        continue
                columns, rows = analytics.run_select(guarded, allowed_tables)
                ok_list.append({"sql": guarded, "columns": columns, "rows": rows,
                                "explanation": (q.get("explanation") or "").strip()})
            except Exception as e:  # noqa: BLE001 — 개별 쿼리 실패는 건너뛰고 나머지로 답한다
                logger.warning("SQL 가드/실행 실패: %s / sql=%r", e, raw_sql)
                last_err = str(e)
        return ok_list, last_err

    executed, last_err = _write_and_run(stage2_allowed)
    # 리콜 보전 폴백: 개요가 좁힌 스키마로 전부 실패하면 권한 전체 스키마로 1회 재시도
    # Recall-preserving fallback: if every query failed under the narrowed schema, retry once full
    if not executed and sel_tables and (allowed_tables is None or sel_tables != allowed_tables):
        logger.info("개요 좁히기 실패 — 전체 스키마로 재시도")
        executed, last_err = _write_and_run(allowed_tables)
    if not executed:
        return {
            "status": "failed", "text": "", "extras": {},
            "fail_reason": f"SQL 생성/실행에 실패했습니다: {last_err or '유효한 쿼리가 없습니다'}",
            "alternative": "질문을 더 구체적으로(테이블·기간·항목) 바꿔서 다시 시도해 주세요.",
        }

    try:
        comment = _comment(query, executed)
    except Exception:
        logger.warning("분석 코멘트 생성 실패 — 쿼리 설명으로 대체", exc_info=True)
        comment = executed[0]["explanation"] or f"조회 결과 {len(executed[0]['rows'])}행을 표로 표시합니다."

    # 사용 테이블 목록(단어 경계 매칭, 전 쿼리 합집합) — 리소스 참조 블록의 데이터 그룹 집계용
    # Tables referenced across ALL queries (word-boundary union) — for the resource-block aggregation
    low = " ".join(r["sql"].lower() for r in executed)
    used = sorted(t for t in catalog.all_table_names()
                  if re.search(r"\b" + re.escape(t.lower()) + r"\b", low))
    primary = executed[0]
    extras = {"columns": primary["columns"], "rows": primary["rows"], "sql": primary["sql"], "tables": used}
    if len(executed) > 1:
        # 질의 분해 산출물 — 추가 결과는 별도 표 카드로 렌더된다(answers._collect_cards)
        # Decomposition outputs — additional results render as extra table cards (answers._collect_cards)
        extras["extra_results"] = [{"columns": r["columns"], "rows": r["rows"], "sql": r["sql"]}
                                   for r in executed[1:]]
    return {"status": "analysis", "text": comment, "extras": extras}


async def run(query: str, context: list[Message], allow_web: bool = True,
              eff: dict | None = None, scope_files: dict | None = None) -> AgentResult:
    # 데이터 분석은 웹 폴백이 없어 allow_web을 사용하지 않는다(시그니처 통일용).
    # Data analysis has no web fallback, so allow_web is not used (for signature uniformity).
    return await asyncio.to_thread(_run_sync, query, context, eff, scope_files)
