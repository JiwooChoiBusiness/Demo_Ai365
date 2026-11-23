# -*- coding: utf-8 -*-
"""리포트 에이전트 드릴다운 하위 조회(2026-09-30) — 받아 둔 데이터에 더 내려갈 컬럼이 없을 때 조회 SQL 을 코드로 고쳐 한 단계를 가져온다.
메모리 DuckDB 에 실제와 같은 모양의 테이블을 만들고, 실제 SQL 가드(sql_policy.select_sql)와 허용 테이블을 거쳐 실행한다. LLM · 실 DB 없음.

Report-agent drill-down query (2026-09-30): when the fetched data has no deeper column, the query SQL is rewritten by code to
fetch one level. Tables shaped like the real ones live in an in-memory DuckDB, and every query goes through the real SQL
guard (sql_policy.select_sql) and the allowed tables. No LLM, no real DB."""
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import duckdb
import httpx
from fastapi import FastAPI
from sqlglot import exp

from app import report_agent, report_dash as rd, report_drill as dr, reports_api
from app.sql_policy import select_sql

TABLES = {"sales_branch_monthly", "hr_employees", "shop_orders", "shop_products", "events", "orders2", "items2"}
BRANCHES = (("서울중앙", "수도권"), ("울산", "영남"), ("대구", "영남"), ("수원", "수도권"))

AGG = ("SELECT * FROM (SELECT branch, SUM(sales_amount) AS total_sales, SUM(target_amount) AS total_target, "
       "AVG(achievement_pct) AS avg_pct FROM sales_branch_monthly GROUP BY branch) AS _q LIMIT 200")
HR = ("SELECT * FROM (SELECT dept, COUNT(*) AS employee_count, SUM(annual_salary) AS total_salary FROM hr_employees "
      "GROUP BY dept ORDER BY employee_count DESC) AS _q LIMIT 200")
JOIN = ("SELECT * FROM (SELECT p.category, SUM(o.quantity) AS qty, SUM(o.net_sales) AS sales FROM shop_orders o "
        "JOIN shop_products p ON o.product_id = p.product_id GROUP BY p.category ORDER BY sales DESC) AS _q LIMIT 200")
RAW = "SELECT * FROM (SELECT month, sales_amount FROM sales_branch_monthly ORDER BY month) AS _q LIMIT 200"


def _db():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE sales_branch_monthly (month VARCHAR, branch VARCHAR, region VARCHAR, sales_amount BIGINT, "
                "target_amount BIGINT, achievement_pct DOUBLE)")
    rows = [(f"2025-{m:02d}", b, r, 100 * m + i, 110 * m, 90.0 + m) for m in range(1, 13) for i, (b, r) in enumerate(BRANCHES)]
    rows += [("2025-01", None, "기타", 5, 5, 100.0), ("2025-02", None, "기타", 7, 7, 100.0)]
    con.executemany("INSERT INTO sales_branch_monthly VALUES (?,?,?,?,?,?)", rows)
    con.execute("CREATE TABLE hr_employees (emp_id VARCHAR, name VARCHAR, dept VARCHAR, title VARCHAR, hire_date DATE, "
                "annual_salary BIGINT, status VARCHAR)")
    con.executemany("INSERT INTO hr_employees VALUES (?,?,?,?,?,?,?)", [
        ("E1", "김하나", "인사", "대리", "2017-07-03", 50, "재직"), ("E2", "이두리", "인사", "과장", "2018-01-02", 60, "재직"),
        ("E3", "박세나", "인사", "대리", "2019-03-04", 55, "퇴직"), ("E4", "최네오", "영업", "사원", "2020-05-06", 40, "재직")])
    con.execute("CREATE TABLE shop_products (product_id VARCHAR, product_name VARCHAR, category VARCHAR, launch_date DATE)")
    con.executemany("INSERT INTO shop_products VALUES (?,?,?,?)", [
        ("P1", "Earbuds", "Electronics", "2025-01-15"), ("P2", "Speaker", "Electronics", "2025-02-01"),
        ("P3", "Serum", "Beauty", "2025-03-01")])
    con.execute("CREATE TABLE shop_orders (order_id VARCHAR, product_id VARCHAR, order_date DATE, quantity INTEGER, net_sales DOUBLE)")
    con.executemany("INSERT INTO shop_orders VALUES (?,?,?,?,?)", [
        ("O1", "P1", "2025-01-20", 2, 20.0), ("O2", "P1", "2025-02-03", 1, 10.0), ("O3", "P2", "2025-02-05", 3, 45.0),
        ("O4", "P3", "2025-03-09", 5, 50.0)])
    con.execute("CREATE TABLE events (ts TIMESTAMP, kind VARCHAR, n INTEGER)")   # 초 소수가 있는 시각 / fractional seconds
    con.executemany("INSERT INTO events VALUES (?,?,?)", [
        ("2025-01-01 10:00:00.5", "a", 1), ("2025-01-01 10:00:00.5", "b", 2), ("2025-01-02 09:00:00", "a", 3)])
    # 두 테이블에 같은 이름(day)이 있는 JOIN / a JOIN where both tables have a column named day
    con.execute("CREATE TABLE orders2 (order_id VARCHAR, sku VARCHAR, day VARCHAR, qty INTEGER)")
    con.executemany("INSERT INTO orders2 VALUES (?,?,?,?)", [
        ("A1", "s1", "2025-01-01", 1), ("A2", "s2", "2025-01-01", 2), ("A3", "s1", "2025-01-02", 3)])
    con.execute("CREATE TABLE items2 (sku VARCHAR, cat VARCHAR, day VARCHAR)")
    con.executemany("INSERT INTO items2 VALUES (?,?,?)", [("s1", "X", "2024-12-01"), ("s2", "X", "2024-12-02")])
    return con


class DrillBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = _db()

    def setUp(self):
        self.queries = []
        stack = ExitStack()
        self.addCleanup(stack.close)

        def run(sql, allowed=None):
            self.queries.append(sql)
            s = select_sql(sql, TABLES if allowed is None else allowed)   # 진짜 가드 / the real guard
            cur = self.con.execute(f"SELECT * FROM ({s}) AS _q LIMIT 200")
            return [d[0] for d in cur.description], [list(r) for r in cur.fetchall()]

        def describe(table):
            return [(r[0], r[1]) for r in self.con.execute(f'DESCRIBE "{table}"').fetchall()]

        stack.enter_context(patch("app.analytics.run_select", side_effect=run))
        stack.enter_context(patch("app.analytics.describe_columns", side_effect=describe))
        self.refresh = stack.enter_context(patch("app.analytics.refresh_csv_views"))
        stack.enter_context(patch("app.catalog.all_table_names", return_value=set(TABLES)))
        stack.enter_context(patch("app.catalog.allowed_tables", side_effect=lambda eff: set(eff.get("tables") or [])))
        stack.enter_context(patch("app.catalog.domain_readable", side_effect=lambda eff, d: bool(eff.get("tables"))))

    def rows(self, out):
        return {r[0]: r[1:] for r in out["source"]["rows"]}


class DrillTests(DrillBase):
    def test_an_aggregated_branch_goes_down_to_its_months_with_the_same_measures(self):
        out = dr.drill(AGG, [{"col": "branch", "value": "울산"}])
        self.assertEqual((out["status"], out["next"]), ("ok", "month"))   # region 은 지점마다 하나라 후보가 아니다 / region is 1:1 with branch
        src = out["source"]
        self.assertEqual(src["columns"], ["month", "total_sales", "total_target", "avg_pct"])
        self.assertEqual(src["periods"], {"month": "month"})
        self.assertEqual(self.rows(out)["2025-03"], [301, 330, 93.0])   # 울산 = BRANCHES 의 1번 / index 1 of BRANCHES
        self.assertEqual([r[0] for r in src["rows"]], [f"2025-{m:02d}" for m in range(1, 13)])   # 다음 컬럼 순서 / in next-column order
        self.assertIn("GROUP BY", src["sql"])
        self.assertNotIn("_q", src["sql"])   # 가드의 감싸기는 벗겨 고친다 / the guard wrapper is unwrapped

    def test_several_columns_ask_the_user_with_periods_first_and_no_id_columns(self):
        out = dr.drill(HR, [{"col": "dept", "value": "인사"}])
        self.assertEqual(out["status"], "choose")
        self.assertEqual([c["column"] for c in out["candidates"]], ["hire_date", "name", "title", "status"])
        self.assertTrue(out["candidates"][0]["period"])
        picked = dr.drill(HR, [{"col": "dept", "value": "인사"}], next_col="title")
        self.assertEqual(self.rows(picked), {"대리": [2, 105], "과장": [1, 60]})
        self.assertEqual([r[0] for r in picked["source"]["rows"]], ["과장", "대리"])   # 원래의 인원순 정렬은 버린다 / the old count order is dropped

    def test_the_last_level_says_there_is_nothing_to_split(self):
        with self.assertRaises(dr.DrillUnavailable) as e:
            dr.drill(AGG, [{"col": "branch", "value": "울산"}, {"col": "month", "value": "2025-03"}])
        self.assertEqual((str(e.exception), e.exception.scope), (dr.MSG_NO_SPLIT, "value"))

    def test_joined_tables_are_qualified_by_their_alias(self):
        out = dr.drill(JOIN, [{"col": "category", "value": "Electronics"}])
        self.assertEqual(out["status"], "choose")
        self.assertEqual([c["column"] for c in out["candidates"]], ["order_date", "launch_date", "product_name"])
        picked = dr.drill(JOIN, [{"col": "category", "value": "Electronics"}], next_col="product_name")
        self.assertEqual(self.rows(picked), {"Earbuds": [3, 30.0], "Speaker": [3, 45.0]})
        self.assertIn('"p"."product_name"', picked["source"]["sql"])

    def test_chart_filters_become_conditions_and_measure_filters_are_skipped(self):
        out = dr.drill(AGG, [{"col": "branch", "value": "울산"}], next_col="month",
                       filters=[{"col": "branch", "values": ["서울중앙"]}, {"col": "total_sales", "values": ["1"]}])
        self.assertEqual(out["source"]["rows"], [])   # 울산은 고른 지점이 아니다 / 울산 is not among the picked branches
        kept = dr.drill(AGG, [{"col": "branch", "value": "울산"}], next_col="month",
                        filters=[{"col": "region", "values": ["영남"]}])
        self.assertEqual(len(kept["source"]["rows"]), 12)

    def test_an_empty_label_means_null(self):
        out = dr.drill(AGG, [{"col": "branch", "value": ""}], next_col="month")
        self.assertEqual(self.rows(out), {"2025-01": [5, 5, 100.0], "2025-02": [7, 7, 100.0]})

    def test_values_stay_literals_and_unknown_columns_stop(self):
        out = dr.drill(AGG, [{"col": "branch", "value": "x' OR '1'='1"}], next_col="month")
        self.assertEqual(out["source"]["rows"], [])
        with self.assertRaises(dr.DrillUnavailable):
            dr.drill(AGG, [{"col": "branch; DROP TABLE hr_employees", "value": "a"}])
        with self.assertRaises(dr.DrillUnavailable):
            dr.drill(AGG, [{"col": "total_sales", "value": "1"}])   # 값(집계) 컬럼은 축이 될 수 없다 / a measure is no axis
        with self.assertRaises(dr.DrillUnavailable):
            dr.drill(AGG, [{"col": "branch", "value": "울산"}], next_col="없는컬럼")

    def test_complex_queries_are_left_alone(self):
        for sql in ("SELECT * FROM (WITH m AS (SELECT month, SUM(sales_amount) AS s FROM sales_branch_monthly GROUP BY month) "
                    "SELECT * FROM m) AS _q LIMIT 200",
                    "SELECT month, SUM(sales_amount) AS s FROM sales_branch_monthly GROUP BY month UNION ALL "
                    "SELECT month, SUM(target_amount) FROM sales_branch_monthly GROUP BY month",
                    "SELECT month, SUM(sales_amount) OVER (PARTITION BY branch) AS s FROM sales_branch_monthly",
                    "SELECT m, s FROM (SELECT month AS m, sales_amount AS s FROM sales_branch_monthly) AS t"):
            with self.assertRaises(dr.DrillUnavailable) as e:
                dr.drill(sql, [{"col": "month", "value": "2025-01"}])
            self.assertEqual(e.exception.scope, "chart", sql)

    def test_permissions_follow_the_caller(self):
        with self.assertRaises(dr.DrillUnavailable) as e:
            dr.drill(AGG, [{"col": "branch", "value": "울산"}], eff={"tables": []})
        self.assertEqual(str(e.exception), dr.MSG_NO_ACCESS)
        with self.assertRaises(dr.DrillUnavailable):   # JOIN 의 한쪽이라도 허용 밖이면 멈춘다 / one table outside the permission stops it
            dr.drill(JOIN, [{"col": "category", "value": "Electronics"}], eff={"tables": ["shop_products"]})
        ok = dr.drill(AGG, [{"col": "branch", "value": "울산"}], eff={"tables": ["sales_branch_monthly"]})
        self.assertEqual(ok["status"], "ok")

    def test_expressions_ordinals_and_row_queries(self):
        expr = ("SELECT SUBSTR(month, 1, 4) AS yr, SUM(sales_amount) AS s FROM sales_branch_monthly GROUP BY 1")
        out = dr.drill(expr, [{"col": "yr", "value": "2025"}], next_col="branch")
        self.assertEqual(list(self.rows(out)), ["대구", "서울중앙", "수원", "울산", None])   # 지점이 빈 행도 2025년이다(빈 값은 끝) / the rows without a branch are 2025 too (blank last)
        raw = dr.drill(RAW, [{"col": "month", "value": "2025-03"}])
        self.assertEqual(raw["status"], "choose")   # 행 조회: 컬럼을 하나 더 붙여 화면이 묶는다 / row query: one more column, the UI aggregates
        picked = dr.drill(RAW, [{"col": "month", "value": "2025-03"}], next_col="branch")
        self.assertEqual(picked["source"]["columns"], ["branch", "month", "sales_amount"])
        self.assertEqual([r[0] for r in picked["source"]["rows"]], ["대구", "서울중앙", "수원", "울산"])
        self.assertIn('ORDER BY "sales_branch_monthly"."branch", month', picked["source"]["sql"])   # 원래 정렬이 뒤를 잇는다 / the original order follows

    def test_having_stays_on_the_top_level(self):
        # 지점 합계 조건은 누른 지점이 이미 통과했다 — 월별로 다시 걸면 비거나(1000 미만인 달) 오류가 난다(묶지 않은 branch)
        # The branch-total condition was passed by the clicked branch; re-applied per month it would empty or break the query
        sql = ("SELECT branch, SUM(sales_amount) AS s FROM sales_branch_monthly GROUP BY branch "
               "HAVING SUM(sales_amount) > 1000 AND branch <> '대구'")
        out = dr.drill(sql, [{"col": "branch", "value": "울산"}])
        self.assertEqual((out["status"], out["next"], len(out["source"]["rows"])), ("ok", "month", 12))
        self.assertNotIn("HAVING", out["source"]["sql"])

    def test_numbers_timestamps_and_blanks_match_the_text_on_screen(self):
        dbl = "SELECT achievement_pct, SUM(sales_amount) AS s FROM sales_branch_monthly GROUP BY achievement_pct"
        out = dr.drill(dbl, [{"col": "achievement_pct", "value": "91"}], next_col="branch")   # 화면은 실수 91.0 을 '91' 로 적는다 / the UI writes 91.0 as '91'
        self.assertEqual(list(self.rows(out)), ["대구", "서울중앙", "수원", "울산"])
        ts = "SELECT ts, SUM(n) AS n FROM events GROUP BY ts"
        out = dr.drill(ts, [{"col": "ts", "value": "2025-01-01 10:00:00.500000"}])   # 파이썬 str 의 소수 6자리 / Python str's six digits
        self.assertEqual((out["next"], self.rows(out)), ("kind", {"a": [1], "b": [2]}))
        blank = dr._one_of(exp.column("b"), ["", "x"]).sql(dialect="duckdb")   # 필터의 빈 값 = 누른 빈 값과 같은 규칙 / a blank filter value = the clicked-blank rule
        self.assertIn("b IS NULL", blank)
        self.assertIn("CAST(b AS TEXT) = ''", blank)

    def test_a_join_goes_two_levels_down_through_a_name_both_tables_share(self):
        sql = "SELECT i.cat, SUM(o.qty) AS q FROM orders2 o JOIN items2 i ON o.sku = i.sku GROUP BY i.cat"
        first = dr.drill(sql, [{"col": "cat", "value": "X"}], next_col="day")
        self.assertIn('"o"."day"', first["source"]["sql"])   # 두 테이블에 다 있는 이름 = FROM 의 첫 테이블 / a shared name = the first table
        second = dr.drill(sql, [{"col": "cat", "value": "X"}, {"col": "day", "value": "2025-01-01"}])
        self.assertEqual((second["status"], second["next"], self.rows(second)), ("ok", "sku", {"s1": [1], "s2": [2]}))
        self.assertTrue(dr.probe(sql, [{"col": "cat", "value": "X"}], "day"))

    def test_csv_views_are_registered_only_when_a_table_is_missing(self):
        dr.drill(AGG, [{"col": "branch", "value": "울산"}])
        self.refresh.assert_not_called()   # 뷰가 있으면 요청마다 다시 등록하지 않는다 / no re-registration while the views exist
        seen = []

        def flaky(table):   # 처음 한 번은 아직 없는 CSV 뷰 / a CSV view not registered yet, once
            seen.append(table)
            if len(seen) == 1:
                raise duckdb.CatalogException(f"Table with name {table} does not exist!")
            return [(r[0], r[1]) for r in self.con.execute(f'DESCRIBE "{table}"').fetchall()]

        with patch("app.analytics.describe_columns", side_effect=flaky):
            out = dr.drill(AGG, [{"col": "branch", "value": "울산"}])
        self.assertEqual(out["status"], "ok")
        self.refresh.assert_called_once()

    def test_the_agent_path_may_name_base_table_columns_the_fetched_data_lacks(self):
        # 받은 드릴다운 코드처럼 에이전트가 계층을 정하되, 집계된 답변에서도 되게 원본 테이블 컬럼을 받는다(누를 때 서버가 그 단계를 조회)
        # As in the reviewed drill-down code the agent declares the hierarchy, and base-table columns work on aggregated answers too
        self.assertEqual(dr.dimensions_of(AGG), ["month", "branch", "region"])
        self.assertEqual(dr.dimensions_of(HR), ["name", "dept", "title", "hire_date", "status"])   # id · 숫자 컬럼은 단계가 아니다 / no ids or numbers
        self.assertEqual(dr.dimensions_of("SELECT * FROM (WITH m AS (SELECT 1 AS a) SELECT * FROM m) AS _q"), [])
        self.assertEqual(dr.dimensions_of(AGG, {"tables": []}), [])
        st = rd.normalize_state({"sources": [{"columns": ["branch", "total_sales"], "rows": [["울산", 1], ["대구", 2]], "sql": AGG}],
                                 "charts": [{"source": "s1", "x": "branch", "y": ["total_sales"]}]})
        report_agent.run_tool(st, "set_drill", {"chart_id": "c1", "columns": ["Month", "region"]}, None)
        self.assertEqual(st["charts"][0]["drill"], ["month", "region"])
        self.assertEqual(rd.normalize_state(st)["charts"][0]["drill"], ["month", "region"])   # 저장 · 다시 읽기에도 남는다 / kept on save and load
        with self.assertRaises(ValueError) as e:
            report_agent.run_tool(st, "set_drill", {"chart_id": "c1", "columns": ["sales_amount"]}, None)
        self.assertIn("month", str(e.exception))   # 쓸 수 있는 컬럼에 원본 컬럼도 나온다 / the usable list names base columns too
        with self.assertRaises(ValueError):        # 권한 밖이면 원본 컬럼은 못 쓴다 / not outside the permission
            report_agent.run_tool(st, "set_drill", {"chart_id": "c1", "columns": ["month"]}, {"tables": []})
        with self.assertRaises(dr.DrillUnavailable) as e:   # 이 조회로 내려갈 곳이 아닌 컬럼 = 차트 단위 거절 / not a level of this query: the whole chart
            dr.drill(AGG, [{"col": "branch", "value": "울산"}], next_col="sales_amount")
        self.assertEqual(e.exception.scope, "chart")

    def test_depth_is_capped_and_an_empty_path_is_an_error(self):
        with self.assertRaises(dr.DrillUnavailable) as e:
            dr.drill(AGG, [{"col": "branch", "value": "울산"}] * 4)
        self.assertEqual(str(e.exception), dr.MSG_MAX_LEVEL)
        with self.assertRaises(ValueError):
            dr.drill(AGG, [])

    def test_probe_answers_whether_any_value_on_the_level_can_go_down(self):
        self.assertTrue(dr.probe(AGG, [], "branch"))
        self.assertFalse(dr.probe(AGG, [{"col": "branch", "value": "울산"}], "month"))
        self.assertTrue(dr.probe(HR, [], "dept"))
        self.assertFalse(dr.probe(HR, [], "total_salary"))
        self.assertFalse(dr.probe("SELECT * FROM (WITH m AS (SELECT 1 AS a) SELECT * FROM m) AS _q", [], "a"))
        self.assertFalse(dr.probe(AGG, [], "branch", eff={"tables": []}))


class DrillApiTests(DrillBase, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        DrillBase.setUp(self)
        app = FastAPI()
        app.include_router(reports_api.router)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.client.aclose)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(reports_api, "_eff", return_value=None))

    async def post(self, **body):
        r = await self.client.post("/api/reports/drill", json={"acting_user_id": "7", **body})
        return r.status_code, r.json()

    async def test_the_endpoint_answers_ok_choose_none_and_probe(self):
        code, d = await self.post(sql=AGG, path=[{"col": "branch", "value": "울산"}])
        self.assertEqual((code, d["status"], d["next"], len(d["source"]["rows"])), (200, "ok", "month", 12))
        _, d = await self.post(sql=HR, path=[{"col": "dept", "value": "인사"}])
        self.assertEqual(d["status"], "choose")
        _, d = await self.post(sql="SELECT 1 UNION SELECT 2", path=[{"col": "a", "value": "1"}])
        self.assertEqual((d["status"], d["scope"], d["reason"]), ("none", "chart", dr.MSG_SHAPE))
        _, d = await self.post(sql=AGG, probe=True, x="branch")
        self.assertEqual(d, {"status": "probe", "drillable": True})
        code, d = await self.post(sql=AGG, path=[])
        self.assertEqual(code, 422)

    async def test_an_execution_error_is_one_notice(self):
        with patch("app.report_drill.drill", side_effect=RuntimeError("duckdb boom")):
            code, d = await self.post(sql=AGG, path=[{"col": "branch", "value": "울산"}])
        self.assertEqual((code, d), (200, {"status": "none", "reason": dr.MSG_FAILED, "scope": "value"}))


if __name__ == "__main__":
    unittest.main()
