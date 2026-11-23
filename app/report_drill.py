"""리포트 에이전트 드릴다운 하위 조회(2026-09-30).

차트 막대를 눌러 안쪽을 볼 때, 받아 둔 Source 에 더 내려갈 컬럼이 없으면(대부분 채팅 답변의 집계 결과 — 예: 지점별 합계) 그 Source 의
조회 SQL 을 **코드로** 고쳐 다시 조회한다. LLM 은 쓰지 않는다: 누른 값들로 좁히고(WHERE) 다음 컬럼으로 묶는다(GROUP BY).
결과는 화면에만 쓰는 임시 데이터이고 대시보드에 저장하지 않는다.

- 실행은 지금 신원의 허용 테이블로 한다 — analytics.run_select 의 가드(SELECT 단일문 · 허용 테이블 · 허용 함수)를 그대로 지나므로,
  받은 SQL 을 다시 실행하는 새로고침과 같이 권한이 넓어지지 않는다.
- 고치는 조회: 테이블 하나 또는 JOIN 으로 묶은 SELECT(집계 + GROUP BY, 또는 집계 없는 행 조회). WITH · UNION · FROM 의 서브쿼리 ·
  윈도 함수 · DISTINCT 가 있으면 고치지 않는다(DrillUnavailable — 화면은 안내만 한다).
- 다음 컬럼 후보: FROM 의 테이블들에서 글자 · 날짜 · 불리언 컬럼(이름이 기간을 뜻하면 정수도). ID 모양(…_id · uuid)과 이미 묶었거나
  고른 컬럼은 뺀다. 누른 값 안에서 값이 2~40개인 것만(화면의 드릴다운과 같은 규칙), 기간 컬럼을 먼저.
- 조건: CAST(식 AS VARCHAR) = '값'(빈 값은 NULL 또는 빈 글자, 실수 91.0 · 초 소수는 DuckDB 글자 모양도 받는다). 차트의 필터는 화면이
  값 목록으로 바꿔 보낸다 — 값(집계) 컬럼 필터는 누른 값 안에서는 이미 맞으므로 건너뛴다(화면도 서버 단계에서는 다시 걸지 않는다).
  원래 조회의 HAVING 은 다음 단계에 옮기지 않는다(누른 값이 이미 통과했다).
"""
# Report-agent drill-down query (2026-09-30).
# When a clicked mark has no deeper column in the source already fetched (usually an aggregated chat answer, e.g. totals per
# branch), the source's query SQL is rewritten by code, never by the LLM: narrowed by the clicked values (WHERE) and grouped
# by the next column (GROUP BY). The result is transient view data and is never stored in the dashboard.
# - It runs with the current identity's allowed tables through analytics.run_select's guard (single SELECT, allowed tables,
#   allowed functions), exactly like the refresh that re-runs a stored SQL, so no permission widens.
# - Rewritable queries: one table or JOINed tables in a SELECT (aggregates with GROUP BY, or plain rows). WITH, UNION,
#   subqueries in FROM, window functions and DISTINCT are left alone (DrillUnavailable; the UI only shows a notice).
# - Next-column candidates: text, date and boolean columns of the FROM tables (integers too when the name means a period),
#   minus ID-like names and columns already grouped or picked, keeping those with 2 to 40 values inside the clicked value
#   (the same rule as the in-browser drill-down), periods first.
# - Conditions: CAST(expr AS VARCHAR) = 'value' (an empty value means NULL or an empty string; DuckDB's text forms of a
#   double like 91.0 and of fractional seconds are accepted too). The UI turns the chart's filters into value lists; filters
#   on a measure are skipped because the clicked value already satisfies them (the UI does not re-apply them on server
#   levels either). The original query's HAVING is not carried to the next level (the clicked value already passed it).

import logging
import re

import sqlglot
from sqlglot import exp

from app import analytics, catalog
from app import report_dash as rd

logger = logging.getLogger("ai365.report_drill")

MAX_LEVELS = rd.MAX_DRILL          # 드릴다운 단계 수 / drill-down levels
MAX_CANDIDATES = 8
MIN_DISTINCT, MAX_DISTINCT = 2, 40
MAX_VALUE_LEN = 300
MAX_FILTERS = rd.MAX_FILTERS
MAX_FILTER_VALUES = rd.MAX_FILTER_SELECTED
MAX_SQL = 4000

_DIM_TYPES = ("VARCHAR", "CHAR", "TEXT", "STRING", "DATE", "TIMESTAMP", "BOOLEAN", "ENUM")
_INT_TYPES = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT")
_PERIOD_NAME = re.compile(r"(date|month|year|quarter|week|period|day|time|월|연도|년도|분기|주차|일자|기간|날짜)", re.I)
_ID_NAME = re.compile(r"^(id|.+_id|id_.+|.*uuid.*)$", re.I)

# 화면에 그대로 가는 안내 — 화면 사전(report_dash.js DICT)에 영어가 있다 / notices shown as is; the UI dictionary has the English
MSG_SHAPE = "이 조회는 모양이 복잡해 더 내려갈 수 없습니다"
MSG_NO_COLUMN = "이 데이터에는 더 내려갈 컬럼이 없습니다."
MSG_NO_SPLIT = "이 값 안에서는 더 나눠 볼 컬럼이 없습니다"
MSG_NO_ACCESS = "이 데이터의 원본 테이블을 열람할 권한이 없습니다"
MSG_MAX_LEVEL = "드릴다운은 3단계까지입니다"
MSG_FAILED = "하위 데이터를 조회하지 못했습니다"


class DrillUnavailable(ValueError):
    """이 조회·값으로는 더 내려갈 수 없다 — scope 'chart' = 조회 모양 탓(어느 값을 눌러도 같다), 'value' = 이 값에서만."""
    # Nothing further to drill into. scope 'chart' = the query's shape (every value alike), 'value' = only this value.

    def __init__(self, message: str, scope: str = "chart"):
        super().__init__(message)
        self.scope = scope


def _inner(sql: str) -> exp.Select:
    """가드의 감싸기(SELECT * FROM (…) AS _q LIMIT n)를 벗겨 고칠 SELECT 를 꺼낸다 / unwrap the guard's wrapper to the rewritable SELECT"""
    if not sql or len(sql) > MAX_SQL:
        raise DrillUnavailable(MSG_SHAPE)
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except sqlglot.errors.SqlglotError as e:
        raise DrillUnavailable(MSG_SHAPE) from e
    while (isinstance(tree, exp.Select) and len(tree.expressions) == 1 and isinstance(tree.expressions[0], exp.Star)
           and not any(tree.args.get(k) for k in ("where", "group", "having", "joins", "with_"))):
        frm = tree.args.get("from_")
        sub = frm.this if frm is not None else None
        if isinstance(sub, exp.Subquery) and isinstance(sub.this, exp.Select):
            tree = sub.this
            continue
        break
    if not isinstance(tree, exp.Select) or tree.args.get("with_") or tree.args.get("distinct") or tree.find(exp.Window):
        raise DrillUnavailable(MSG_SHAPE)
    if any(isinstance(p, exp.Star) or p.find(exp.Star) and not p.find(exp.AggFunc) for p in tree.expressions):
        raise DrillUnavailable(MSG_SHAPE)
    frm = tree.args.get("from_")
    if frm is None or not isinstance(frm.this, exp.Table):
        raise DrillUnavailable(MSG_SHAPE)
    if any(not isinstance(j.this, exp.Table) for j in tree.args.get("joins") or []):
        raise DrillUnavailable(MSG_SHAPE)
    return tree


def _tables(sel: exp.Select, allowed: set[str] | None) -> list[tuple[str, str]]:
    """FROM · JOIN 의 (별칭, 테이블) — 가드 유니버스 밖이거나 허용 밖이면 멈춘다 / (alias, table) of FROM and JOINs, gated"""
    out = []
    for t in [sel.args["from_"].this] + [j.this for j in sel.args.get("joins") or []]:
        name = t.name
        if t.catalog or t.db not in ("", "main") or name not in catalog.all_table_names():
            raise DrillUnavailable(MSG_SHAPE)
        if allowed is not None and name not in allowed:
            raise DrillUnavailable(MSG_NO_ACCESS)
        out.append((t.alias_or_name, name))
    return out


def _projection(sel: exp.Select, name: str) -> tuple[exp.Expression | None, bool]:
    """출력 이름으로 SELECT 항목의 식 — (식, 값 컬럼인가). 없으면 (None, False) / the expression behind an output name"""
    for p in sel.expressions:
        if p.alias_or_name == name:
            if p.find(exp.AggFunc):
                return None, True
            return (p.this if isinstance(p, exp.Alias) else p).copy(), False
    return None, False


def _column(alias: str, name: str) -> exp.Column:
    return exp.column(name, table=alias, quoted=True)


def _base(tables, cols: dict, name: str) -> exp.Column | None:
    """원본 테이블의 컬럼 — 같은 이름이 여러 테이블에 있으면 FROM · JOIN 순서의 첫 테이블(후보를 고른 _dimensions 와 같은 규칙이라
    한 단계 더 내려가도 같은 컬럼을 가리킨다). 정확한 이름을 먼저, 없으면 대소문자 무시.
    A base column. When several tables have the name, the first in FROM/JOIN order wins (the rule _dimensions used to offer it,
    so the next level points at the same column). Exact names first, then case-insensitive."""
    for same in (lambda c: c == name, lambda c: c.lower() == name.lower()):
        for alias, _ in tables:
            for c, _t in cols[alias]:
                if same(c):
                    return _column(alias, c)
    return None


def _as_text(e: exp.Expression) -> exp.Cast:
    return exp.Cast(this=e.copy(), to=exp.DataType.build("VARCHAR"))


_INTEGRAL = re.compile(r"^-?\d{1,15}$")
_FRACTION_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\.(\d+)$")


def _texts(v: str) -> list[str]:
    """한 값의 글자 모양들 — 화면의 값은 JS String(v)(실수 91.0 → '91') · 파이썬 str(초 소수 6자리 '.500000')이고, 조건은
    DuckDB 의 CAST(… AS VARCHAR)('91.0' · '.5')와 비교한다. 둘 다 받아 준다.
    The text forms of one value: the UI's values come from JS String(v) (the double 91.0 → '91') or Python str (six fraction
    digits '.500000'), while conditions compare DuckDB's CAST(… AS VARCHAR) ('91.0', '.5'). Both are accepted."""
    out = [v]
    if _INTEGRAL.match(v):
        out.append(v + ".0")
    m = _FRACTION_TS.match(v)
    if m:
        frac = m.group(2).rstrip("0")
        out.append(m.group(1) + ("." + frac if frac else ""))
    return list(dict.fromkeys(out))


def _blank(e: exp.Expression) -> exp.Expression:
    """빈 값 = NULL 또는 빈 글자(화면의 '(빈 값)'은 둘을 한 값으로 센다) / blank = NULL or an empty string, one value on screen"""
    return exp.paren(exp.or_(exp.Is(this=e.copy(), expression=exp.Null()),
                             exp.EQ(this=_as_text(e), expression=exp.Literal.string(""))))


def _equals(e: exp.Expression, value) -> exp.Expression:
    v = rd.key(value)[:MAX_VALUE_LEN]
    if v == "":
        return _blank(e)
    forms = _texts(v)
    if len(forms) == 1:
        return exp.EQ(this=_as_text(e), expression=exp.Literal.string(v))
    return exp.In(this=_as_text(e), expressions=[exp.Literal.string(t) for t in forms])


def _one_of(e: exp.Expression, values: list[str]) -> exp.Expression:
    forms = list(dict.fromkeys(t for v in values if v != "" for t in _texts(v)))
    parts = ([exp.In(this=_as_text(e), expressions=[exp.Literal.string(t) for t in forms])] if forms else []) + (
        [_blank(e)] if "" in values else [])
    return exp.paren(exp.or_(*parts)) if len(parts) > 1 else parts[0]


def _period(name: str, typ: str) -> bool:
    return typ.upper().startswith(("DATE", "TIMESTAMP")) or bool(_PERIOD_NAME.search(name))


def _dimensions(tables, cols: dict, used: set[str]) -> list[dict]:
    """다음 컬럼이 될 수 있는 원본 컬럼(이름 중복은 첫 테이블) / base columns that can be the next level"""
    out, seen = [], set()
    for alias, _ in tables:
        for name, typ in cols[alias]:
            low, t = name.lower(), typ.upper()
            if low in used or low in seen or _ID_NAME.match(name):
                continue
            period = _period(name, t)
            if not (t.startswith(_DIM_TYPES) or (period and t.startswith(_INT_TYPES))):
                continue
            seen.add(low)
            out.append({"column": name, "alias": alias, "period": period})
    return out


def _where(sel: exp.Select, conds: list[exp.Expression]) -> exp.Expression | None:
    base = sel.args.get("where")
    parts = ([exp.paren(base.this.copy())] if base is not None else []) + [exp.paren(c) if isinstance(c, exp.Connector) else c for c in conds]
    return exp.and_(*parts) if parts else None


def _run(sql: str, allowed) -> tuple[list, list]:
    """가드를 지나 실행 — 가드가 거절한 고친 조회는 안내로 바꾼다 / run through the guard; a rejected rewrite becomes a notice"""
    try:
        return analytics.run_select(sql, allowed)
    except ValueError as e:
        raise DrillUnavailable(MSG_SHAPE) from e


def _counted(sel: exp.Select, where, dims: list[dict], allowed) -> list[dict]:
    """누른 값 안에서 후보마다 값 개수를 한 번에 센다 / count the distinct values of every candidate inside the clicked value"""
    q = exp.Select(expressions=[exp.Count(this=exp.Distinct(expressions=[_as_text(_column(d["alias"], d["column"]))])).as_(f"n{i}")
                                for i, d in enumerate(dims)])
    q.set("from_", sel.args["from_"].copy())
    q.set("joins", [j.copy() for j in sel.args.get("joins") or []] or None)
    if where is not None:
        q.set("where", exp.Where(this=where.copy()))
    _, rows = _run(q.sql(dialect="duckdb"), allowed)
    counts = rows[0] if rows else [0] * len(dims)
    kept = [dict(d, count=int(n or 0)) for d, n in zip(dims, counts) if MIN_DISTINCT <= int(n or 0) <= MAX_DISTINCT]
    return sorted(kept, key=lambda d: not d["period"])[:MAX_CANDIDATES]   # 기간 먼저, 나머지는 스키마 순서 / periods first, then schema order


def _rewritten(sel: exp.Select, where, nxt: exp.Column, name: str) -> str:
    """누른 값으로 좁히고 다음 컬럼으로 묶은 조회 / the query narrowed by the clicked values and grouped by the next column"""
    q = sel.copy()
    q.set("where", exp.Where(this=where) if where is not None else None)
    head = exp.alias_(nxt.copy(), name, quoted=True)
    order = [exp.Ordered(this=nxt.copy())]
    if any(p.find(exp.AggFunc) for p in sel.expressions):   # 집계 조회: 다음 컬럼 + 값(집계)만 / aggregate query: next column + measures
        q.set("expressions", [head] + [p.copy() for p in sel.expressions if p.find(exp.AggFunc)])
        q.set("group", exp.Group(expressions=[nxt.copy()]))
    else:                                                    # 행 조회: 컬럼을 하나 더 / row query: one more column
        q.set("expressions", [head] + [p.copy() for p in sel.expressions if p.alias_or_name.lower() != name.lower()])
        # 원래 정렬은 다음 컬럼 뒤에 둔다(번호 정렬은 컬럼 자리가 바뀌어 뺀다) / the original order follows (ordinals shift, so they go)
        order += [o.copy() for o in (sel.args.get("order") or exp.Order(expressions=[])).expressions
                  if not isinstance(o.this, exp.Literal)]
    # HAVING 은 누른 값이 이미 통과했다 — 윗단계 조건(예: 지점 합계 > 10억)을 월별 묶음에 걸면 비거나 오류가 난다. 자르기는 가드가 한다
    # HAVING was already passed by the clicked value; applied to the next level's groups it empties or breaks them. The guard limits
    for k in ("having", "limit", "offset", "qualify"):
        q.set(k, None)
    # 다음 컬럼 순서 — Table 보기가 차트와 같은 순서로 읽히고, 가드의 200행 자르기도 매번 같은 행을 남긴다
    # Ordered by the next column: the Table view reads like the chart, and the guard's 200-row cut keeps the same rows every time
    q.set("order", exp.Order(expressions=order))
    return q.sql(dialect="duckdb")


def _axis(sel, tables, cols: dict, col: str) -> exp.Expression:
    """출력 이름 또는 원본 컬럼의 식 — 값(집계) 컬럼이나 없는 이름이면 멈춘다 / the expression of an output or base column"""
    e, measure = _projection(sel, col)
    e = e if e is not None or measure else _base(tables, cols, col)
    if e is None:
        raise DrillUnavailable(MSG_SHAPE)
    return e


def _prepare(sql: str, steps: list[dict], filters: list | None, eff: dict | None):
    """조회를 읽고 권한을 보고 누른 값 · 필터를 조건으로 — (SELECT, 테이블, 컬럼, 조건들, 쓴 컬럼, 허용 테이블)
    Parse, check permissions and turn the clicked values and filters into conditions."""
    allowed = None if eff is None else catalog.allowed_tables(eff)
    if eff is not None and (not catalog.domain_readable(eff, "p_data") or not allowed):
        raise DrillUnavailable(MSG_NO_ACCESS)
    if len(steps) > MAX_LEVELS:
        raise DrillUnavailable(MSG_MAX_LEVEL, "value")
    sel = _inner(sql)
    tables = _tables(sel, allowed)
    cols = _describe(tables)
    conds, used = [], set()
    for step in steps:
        col = str(step["col"]).strip()
        e = _axis(sel, tables, cols, col)
        conds.append(_equals(e, step.get("value")))
        used |= {c.name.lower() for c in e.find_all(exp.Column)} | {col.lower()}
    for f in (filters or [])[:MAX_FILTERS]:
        col = str((f or {}).get("col") or "").strip()
        values = [rd.key(v)[:MAX_VALUE_LEN] for v in ((f or {}).get("values") or [])][:MAX_FILTER_VALUES]
        if not col or not values:
            continue
        e, measure = _projection(sel, col)
        if measure:   # 값(집계) 필터는 누른 값 안에서는 이미 맞다 / a measure filter is already met inside the clicked value
            continue
        e = e if e is not None else _base(tables, cols, col)
        if e is not None:
            conds.append(_one_of(e, values))
    return sel, tables, cols, conds, used, allowed


def _describe(tables) -> dict:
    """원본 테이블의 컬럼 — CSV 뷰가 아직 없을 때만 다시 등록한다(등록은 전역 잠금을 쥔 DDL 이고 사전 확인은 차트마다 불리므로
    요청마다 하지 않는다). / The base tables' columns. CSV views are re-registered only when one is missing (registration is DDL
    under the global lock and probes run once per chart, so not on every request)."""
    try:
        return {alias: analytics.describe_columns(table) for alias, table in tables}
    except Exception:  # noqa: BLE001 — 아직 없는 CSV 뷰(CatalogException 등) / a CSV view not registered yet (CatalogException and the like)
        analytics.refresh_csv_views()
        return {alias: analytics.describe_columns(table) for alias, table in tables}


def _steps(path) -> list[dict]:
    return [p for p in (path or []) if isinstance(p, dict) and str(p.get("col") or "").strip()]


def probe(sql: str, path: list, x: str, filters: list | None = None, eff: dict | None = None) -> bool:
    """이 단계(path 로 좁힌 자리, 축 = x)에서 눌러서 내려갈 수 있는 값이 하나라도 있는가 — 쿼리 한 번(축 값마다 후보 컬럼의 값 개수를 세어
    2~40개인 값이 있는지). 화면은 이것으로 돋보기 커서를 켜고 끈다. 고칠 수 없는 조회 · 권한 밖이면 False.
    Whether any value on this level (narrowed by path, axis = x) can be drilled: one query counting each candidate's distinct
    values per axis value and checking for a 2-40 split. The UI uses it for the zoom cursor. False for queries it cannot
    rewrite or tables outside the permission."""
    try:
        sel, tables, cols, conds, used, allowed = _prepare(sql, _steps(path), filters, eff)
        axis = _axis(sel, tables, cols, str(x or "").strip())
    except DrillUnavailable:
        return False
    used = used | {c.name.lower() for c in axis.find_all(exp.Column)} | {str(x or "").strip().lower()}
    dims = _dimensions(tables, cols, used)
    if not dims:
        return False
    inner = exp.Select(expressions=[exp.Count(this=exp.Distinct(expressions=[_as_text(_column(d["alias"], d["column"]))])).as_(f"n{i}")
                                    for i, d in enumerate(dims)])
    inner.set("from_", sel.args["from_"].copy())
    inner.set("joins", [j.copy() for j in sel.args.get("joins") or []] or None)
    where = _where(sel, conds)
    if where is not None:
        inner.set("where", exp.Where(this=where))
    inner.set("group", exp.Group(expressions=[axis.copy()]))
    sums = ", ".join(f"SUM(CASE WHEN n{i} BETWEEN {MIN_DISTINCT} AND {MAX_DISTINCT} THEN 1 ELSE 0 END) AS k{i}" for i in range(len(dims)))
    try:
        _, rows = _run(f"SELECT {sums} FROM ({inner.sql(dialect='duckdb')}) AS t", allowed)
    except DrillUnavailable:
        return False
    return bool(rows) and any(int(k or 0) > 0 for k in rows[0])


def drill(sql: str, path: list, next_col: str = "", filters: list | None = None, eff: dict | None = None) -> dict:
    """한 단계 내려간 데이터. path = 맨 위부터 [{col, value}](첫 항목의 col 이 차트의 x), next_col = 고른 컬럼(없으면 후보를 찾는다).
    반환: {"status": "ok", "next", "source", "candidates"} | {"status": "choose", "candidates"}. 더 내려갈 수 없으면 DrillUnavailable."""
    # One level down. path = [{col, value}] from the top (the first col is the chart's x); next_col = the picked column
    # (candidates are looked up when blank). Returns ok with the source or choose with the candidates; DrillUnavailable
    # when nothing further is possible.
    steps = _steps(path)
    if not steps:
        raise ValueError("누른 값이 없습니다")
    sel, tables, cols, conds, used, allowed = _prepare(sql, steps, filters, eff)
    where = _where(sel, conds)

    dims = _dimensions(tables, cols, used)
    want = str(next_col or "").strip()
    candidates: list[dict] = []
    if want:
        chosen = next((d for d in dims if d["column"] == want), None) or next((d for d in dims if d["column"].lower() == want.lower()), None)
        if chosen is None:   # 정해 둔 순서의 컬럼이 이 조회로 내려갈 곳이 아니다 — 어느 값을 눌러도 같다 / not a level of this query, whatever the value
            raise DrillUnavailable(MSG_NO_COLUMN)
    else:
        if not dims:
            raise DrillUnavailable(MSG_NO_COLUMN)
        candidates = _counted(sel, where, dims, allowed)
        if not candidates:
            raise DrillUnavailable(MSG_NO_SPLIT, "value")
        if len(candidates) > 1:
            return {"status": "choose", "candidates": [_public(c) for c in candidates]}
        chosen = candidates[0]
    query = _rewritten(sel, where, _column(chosen["alias"], chosen["column"]), chosen["column"])
    columns, rows = _run(query, allowed)
    src = rd.norm_source({"columns": columns, "rows": rows, "sql": query, "tables": [t for _, t in tables],
                          "label": chosen["column"], "origin": {"kind": "agent", "note": "드릴다운"}}, set())
    return {"status": "ok", "next": chosen["column"], "source": src, "candidates": [_public(c) for c in candidates]}


def _public(c: dict) -> dict:
    return {"column": c["column"], "period": c["period"], "count": c.get("count")}


def dimensions_of(sql: str, eff: dict | None = None) -> list[str]:
    """이 조회로 서버가 내려갈 수 있는 원본 컬럼들 — 에이전트가 정하는 드릴다운 순서(set_drill)가 받아 둔 데이터에 없는 컬럼을 쓸 때 검사한다.
    고칠 수 없는 조회 · 권한 밖 · 조회 실패면 빈 목록(도구는 받아 둔 컬럼만 받는다).
    The base columns the server can drill into for this query, used to check an agent drill path (set_drill) that names
    columns the fetched data lacks. Empty when the query cannot be rewritten, the tables are outside the permission or the
    lookup fails (the tool then accepts fetched columns only)."""
    try:
        allowed = None if eff is None else catalog.allowed_tables(eff)
        if eff is not None and (not catalog.domain_readable(eff, "p_data") or not allowed):
            return []
        sel = _inner(sql)
        tables = _tables(sel, allowed)
        return [d["column"] for d in _dimensions(tables, _describe(tables), set())]
    except Exception:  # noqa: BLE001 — 도구 호출이 끊기지 않게(검사 실패 = 받아 둔 컬럼만) / never break the tool call
        logger.warning("드릴다운 원본 컬럼 조회 실패", exc_info=True)
        return []
