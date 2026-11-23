"""모델 SQL은 허용된 관계와 분석 함수만 사용하는 읽기 질의여야 한다."""
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope

FUNCTIONS = set("""SUM AVG COUNT MIN MAX COALESCE NULLIF IF CASE CAST TRY_CAST
ABS ROUND CEIL CEILING FLOOR POW POWER SQRT MOD SIGN
UPPER LOWER LENGTH CHAR_LENGTH CONCAT CONCAT_WS SUBSTRING TRIM LTRIM RTRIM REPLACE
DATE_TRUNC TIMESTAMP_TRUNC DATE_PART EXTRACT STRFTIME STRPTIME TIME_TO_STR STR_TO_TIME
CURRENT_DATE CURRENT_TIMESTAMP CURRENT_TIME NOW YEAR MONTH DAY DAY_OF_MONTH
DATE_DIFF DATEDIFF DATE_ADD DATE_SUB TS_OR_DS_ADD TS_OR_DS_DIFF
ROW_NUMBER RANK DENSE_RANK LAG LEAD FIRST_VALUE LAST_VALUE NTILE
STDDEV STDDEV_POP STDDEV_SAMP VARIANCE VAR_POP VAR_SAMP MEDIAN QUANTILE
PERCENTILE_CONT PERCENTILE_DISC STRING_AGG GROUP_CONCAT ARRAY_AGG ARRAY_SIZE
GREATEST LEAST BOOL_AND BOOL_OR FILTER IFNULL ISNULL ILIKE LIKE
""".split())

# 함수 허용 목록 검사에서 빼는 노드 — 호출 가능한 함수가 아니라 연산자·술어인데 sqlglot 이 Func 로도 모델링하는 구문(2026-09-26).
# sqlglot 30.18.0(requirements 고정)에서 논리 연결자 And/Or/Xor(exp.Connector 하위)가 Func 를 함께 상속해, 이름(AND/OR)이
# 허용 목록에 없다는 이유로 조건이 둘 이상인 WHERE·HAVING·CASE WHEN·FILTER 가 전부 거부됐다(채팅·워크플로우 Text2SQL 실패).
# EXISTS(exp.Exists — SubqueryPredicate 이면서 Func)도 같은 모양의 술어라 함께 뺀다(같은 술어인 IN·ANY·ALL 은 원래 Func 가 아님).
# 빠지는 것은 이 노드 자체의 이름 검사뿐이다: walk() 가 하위 노드를 모두 돌아 피연산자·서브쿼리 안의 함수는 그대로 허용 목록으로
# 검사되고, 서브쿼리의 테이블은 traverse_scope 가 허용 테이블인지 본다(외부 소스·비승인 함수 차단 의도는 그대로).
# 이 버전에서 NOT·IS·LIKE·ILIKE·IN·BETWEEN 은 Func 가 아니고, CASE·CAST·TRY_CAST·IF 는 Func 이지만 이름이 허용 목록에 있다.
# JSON(->, ->>)·배열(@>, &&)·정규식·COLLATE 처럼 연산자 모양이어도 기능 호출에 가까운 Func 는 종전대로 허용 목록이 정한다.
# Nodes skipped by the function allow-list check: operators and predicates that sqlglot also models as Func (2026-09-26).
# In sqlglot 30.18.0 (pinned in requirements) the logical connectors And/Or/Xor (exp.Connector subclasses) also inherit Func,
# so any WHERE / HAVING / CASE WHEN / FILTER with two or more conditions was rejected because AND/OR is not an allowed
# function name (Text2SQL failed in both chat and workflows). EXISTS (exp.Exists, a SubqueryPredicate that is also a Func) is
# the same kind of predicate and is skipped too (IN / ANY / ALL are not Func at all). Only this node's own name check is
# skipped: walk() still visits every descendant, so functions inside operands and subqueries are checked against the allow
# list, and traverse_scope still checks subquery tables (the external-source / unapproved-function blocking is unchanged).
# In this version NOT / IS / LIKE / ILIKE / IN / BETWEEN are not Func, and CASE / CAST / TRY_CAST / IF are Func whose names are
# allowed. Operator-shaped Func nodes that behave like feature calls (JSON ->, ->>, array @>, &&, regex, COLLATE) stay governed
# by the allow list as before.
NON_FUNCTION_NODES = (exp.Connector, exp.SubqueryPredicate)


def select_sql(sql, allowed):
    try:
        statements = sqlglot.parse(sql, read="duckdb")
        if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.SetOperation)):
            raise ValueError("SELECT 단일 질의만 허용됩니다")
        tree = statements[0]
        allowed = {t.lower() for t in allowed}
        for node in tree.walk():
            if isinstance(node, (exp.DDL, exp.DML, exp.Into, exp.Command)):
                raise ValueError("읽기 질의만 허용됩니다")
            if isinstance(node, exp.Func) and not isinstance(node, NON_FUNCTION_NODES):
                name = node.name.upper() if isinstance(node, exp.Anonymous) else node.sql_name()
                if name not in FUNCTIONS:
                    raise ValueError(f"허용되지 않는 SQL 함수: {name}")
        # 테이블 검사(2026-11-16 위젯 3단계 검토): selected_sources 는 SEMI · ANTI JOIN 의 오른쪽 테이블을 빼서, 금지된 테이블이나
        # 따옴표 친 파일 경로("C:/x.csv")를 ON 조건으로 한 비트씩 읽을 수 있었다 → 스코프의 모든 소스(sources)를 검사하고, 트리의 모든
        # 테이블 노드가 검사된 실제 테이블이거나 CTE · 파생 테이블 참조인지 다시 대조한다(어느 스코프에도 잡히지 않은 테이블은 거절).
        # Table checks (widget phase-3 review, 2026-11-16): selected_sources leaves out the right side of SEMI / ANTI JOINs, so a
        # blocked table or a quoted file path could be read one bit at a time through the ON condition. Every scope source is now
        # checked, and every table node in the tree must be a checked real table or a CTE / derived-table reference.
        accounted: set[int] = set()
        for scope in traverse_scope(tree):
            for source in scope.sources.values():
                if isinstance(source, Scope):
                    continue
                if (not isinstance(source, exp.Table) or not isinstance(source.this, exp.Identifier)
                        or source.catalog or source.db not in ("", "main") or source.name.lower() not in allowed):
                    raise ValueError("허용된 테이블만 조회할 수 있습니다")
                accounted.add(id(source))
            for table in scope.tables:
                if isinstance(scope.sources.get(table.alias_or_name), Scope):
                    accounted.add(id(table))   # CTE · 파생 테이블 참조 / a CTE or derived-table reference
        if any(id(t) not in accounted for t in tree.find_all(exp.Table)):
            raise ValueError("허용된 테이블만 조회할 수 있습니다")
        return tree.sql(dialect="duckdb")
    except sqlglot.errors.SqlglotError as exc:
        raise ValueError("SQL 문법 또는 조회 범위가 올바르지 않습니다") from exc
