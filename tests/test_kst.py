# -*- coding: utf-8 -*-
"""한국 시간(KST) 공통 도우미 app.kst 와 그 사용처(2026-10-06) — 시계 이음새(_clock)를 UTC 고정 시각으로 바꿔 끼워 검사한다.
(a) 도우미 자체 · (b) app/ 전체에서 호스트 시계 호출이 다시 들어오지 않았는지 정적 검사 · (c) 대표 사용처가 KST 시계를 따르는지.
DB · 네트워크 · LLM 없음.

KST helpers in app.kst and their call sites (2026-10-06), tested by patching the clock seam (_clock) with a fixed UTC
instant: (a) the helpers themselves, (b) a static scan that no host-clock call creeps back into app/, (c) representative
call sites follow the KST clock. No DB, network or LLM."""
import logging
import re
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app import kst

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"

# 2026-10-06 16:30:05 UTC = 2026-10-07 01:30:05 KST — UTC 날짜와 KST 날짜가 다른 시각
# 2026-10-06 16:30:05 UTC = 2026-10-07 01:30:05 KST, an instant whose UTC and KST dates differ
FIXED_UTC = datetime(2026, 10, 6, 16, 30, 5, 123456, tzinfo=timezone.utc)
FIXED_KST = datetime(2026, 10, 7, 1, 30, 5, 123456)


def at_utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


class KstHelpersTest(unittest.TestCase):
    """(a) 도우미 / the helpers"""

    def clock(self, instant: datetime):
        return patch.object(kst, "_clock", return_value=instant)

    def test_kst_is_fixed_plus_nine_without_dst(self):
        self.assertEqual(kst.KST.utcoffset(None), timedelta(hours=9))
        self.assertIsNone(kst.KST.dst(None))

    def test_now_is_utc_plus_nine_naive(self):
        with self.clock(FIXED_UTC):
            now = kst.now()
            self.assertIsNone(now.tzinfo)
            self.assertEqual(now, FIXED_KST)
            self.assertEqual(kst.now_iso(), "2026-10-07T01:30:05")   # 저장 형식: naive ISO 초 / stored shape: naive ISO seconds

    def test_today_flips_at_15_utc(self):
        with self.clock(at_utc(2026, 10, 6, 14, 59, 59)):
            self.assertEqual(kst.today(), date(2026, 10, 6))
        with self.clock(at_utc(2026, 10, 6, 15, 0, 0)):
            self.assertEqual(kst.today(), date(2026, 10, 7))

    def test_month_follows_the_kst_date(self):
        with self.clock(at_utc(2026, 9, 30, 14, 59, 59)):
            self.assertEqual(kst.month(), "2026-09")
        with self.clock(at_utc(2026, 9, 30, 15, 0, 0)):
            self.assertEqual(kst.month(), "2026-10")
        with self.clock(at_utc(2026, 12, 31, 15, 0, 0)):
            self.assertEqual(kst.month(), "2027-01")

    def test_from_epoch_is_kst_wall_clock(self):
        ts = at_utc(2026, 10, 6, 15, 0, 0).timestamp()
        self.assertEqual(kst.from_epoch(ts), datetime(2026, 10, 7, 0, 0, 0))
        self.assertIsNone(kst.from_epoch(ts).tzinfo)
        self.assertEqual(kst.from_epoch(int(FIXED_UTC.timestamp())), FIXED_KST.replace(microsecond=0))

    def test_to_kst_converts_aware_and_keeps_naive(self):
        self.assertEqual(kst.to_kst(FIXED_UTC), FIXED_KST)
        plus_one = datetime(2026, 10, 6, 17, 30, 5, 123456, tzinfo=timezone(timedelta(hours=1)))
        self.assertEqual(kst.to_kst(plus_one), FIXED_KST)
        naive = datetime(2026, 1, 2, 3, 4, 5)
        self.assertEqual(kst.to_kst(naive), naive)   # naive 는 이미 KST 로 본다 / naive is taken as KST already
        self.assertIsNone(kst.to_kst(FIXED_UTC).tzinfo)

    def test_aware_and_iso_offset(self):
        with self.clock(FIXED_UTC):
            a = kst.aware()
            self.assertEqual(a.utcoffset(), timedelta(hours=9))
            self.assertEqual(a.replace(tzinfo=None), FIXED_KST)
            self.assertEqual(kst.iso_offset(), "2026-10-07T01:30:05+09:00")
        self.assertTrue(kst.iso_offset(datetime(2026, 1, 2, 3, 4, 5)).endswith("+09:00"))
        self.assertEqual(kst.iso_offset(datetime(2026, 1, 2, 3, 4, 5)), "2026-01-02T03:04:05+09:00")
        self.assertEqual(kst.iso_offset(at_utc(2026, 1, 1, 18, 0, 0)), "2026-01-02T03:00:00+09:00")

    def test_struct_time_now_and_epoch(self):
        with self.clock(FIXED_UTC):
            st = kst.struct_time()
        self.assertEqual((st.tm_year, st.tm_mon, st.tm_mday, st.tm_hour, st.tm_min, st.tm_sec), (2026, 10, 7, 1, 30, 5))
        st = kst.struct_time(at_utc(2026, 10, 6, 15, 0, 0).timestamp())
        self.assertEqual((st.tm_year, st.tm_mon, st.tm_mday, st.tm_hour, st.tm_min), (2026, 10, 7, 0, 0))

    def test_struct_time_as_logging_converter(self):
        # 스케줄러 로그 포매터와 같은 연결 / the same wiring as the scheduler log formatter
        fmt = logging.Formatter("%(asctime)s %(message)s")
        fmt.converter = kst.struct_time
        rec = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None)
        rec.created = at_utc(2026, 10, 6, 15, 0, 0).timestamp()
        rec.msecs = 0
        self.assertTrue(fmt.format(rec).startswith("2026-10-07 00:00:00"), fmt.format(rec))


class NoHostClockTest(unittest.TestCase):
    """(b) app/ 전체 정적 검사 — 시각은 app.kst 만 읽는다 / static scan: only app.kst reads the clock"""

    # 호스트 시간대(또는 UTC)를 읽는 호출 / calls that read the host zone (or UTC)
    PATTERNS = [
        ("datetime.now(", re.compile(r"\bdatetime\.now\(")),
        ("datetime.utcnow(", re.compile(r"\bdatetime\.utcnow\(")),
        ("datetime.today(", re.compile(r"\bdatetime\.today\(")),
        ("date.today(", re.compile(r"\bdate\.today\(")),
        (".fromtimestamp(", re.compile(r"fromtimestamp\(")),               # utcfromtimestamp( 포함 / includes utcfromtimestamp(
        ("time.localtime(", re.compile(r"\btime\.localtime\(")),
        ("CURRENT_TIMESTAMP", re.compile(r"\bCURRENT_(?:TIMESTAMP|DATE|TIME)\b")),   # SQLite 기본값 · 함수 = UTC / SQLite = UTC
        ("'localtime'", re.compile(r"""['"]localtime['"]""")),
        ("SQLite 'now'", re.compile(r"""\b(?:datetime|date|time|julianday|strftime|unixepoch)\([^)]*['"]now['"]""")),
    ]
    # 허용: Text2SQL 이 모델 SQL(DuckDB)에 쓰게 하는 함수 이름 목록일 뿐 시계를 읽지 않는다. DuckDB 연결은 TimeZone 을
    # Asia/Seoul 로 맞춘다(analytics._connect). / Allowed: only the function-name allow-list for model SQL (DuckDB), not a
    # clock read; the DuckDB connection sets TimeZone to Asia/Seoul (analytics._connect).
    ALLOWED = {("app/sql_policy.py", "CURRENT_TIMESTAMP")}

    def test_no_host_clock_calls_outside_kst(self):
        files = sorted(p for p in APP_DIR.rglob("*.py") if p.resolve() != (APP_DIR / "kst.py").resolve())
        self.assertGreater(len(files), 20)   # 검사 대상이 실제로 있다 / the scan really covers the package
        hits = []
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue   # 주석 줄은 실행되지 않는다 / comment-only lines never run
                for label, rx in self.PATTERNS:
                    if rx.search(line) and (rel, label) not in self.ALLOWED:
                        hits.append(f"{rel}:{no}: {label} -> {line.strip()[:160]}")
        self.assertEqual(hits, [], "app.kst 대신 호스트 시계를 읽는 곳 / host-clock reads instead of app.kst:\n" + "\n".join(hits))

    def test_scan_patterns_catch_the_old_forms(self):
        # 검사식이 실제로 옛 형태를 잡는지(헛통과 방지) / the patterns really match the old forms (no vacuous pass)
        samples = {
            "datetime.now(": 'return datetime.now().isoformat(timespec="seconds")',
            "date.today(": "return date.today()",
            ".fromtimestamp(": "cutoff = datetime.fromtimestamp(ts - TTL)",
            "CURRENT_TIMESTAMP": "UPDATE t SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
            "'localtime'": "VALUES(datetime('now','localtime'),?)",
            "SQLite 'now'": "SELECT strftime('%s','now')",
        }
        rx = dict(self.PATTERNS)
        for label, line in samples.items():
            self.assertTrue(rx[label].search(line), label)
        self.assertIsNone(rx["SQLite 'now'"].search("c['now']['t']"))   # 파이썬 키는 아니다 / a Python key is not SQL
        self.assertIsNone(rx["date.today("].search("kst.today()"))


class CallSitesFollowKstTest(unittest.TestCase):
    """(c) 대표 사용처가 KST 시계를 따른다 / representative call sites follow the KST clock"""

    def test_db_now_is_kst_iso(self):
        from app import db
        with patch.object(kst, "_clock", return_value=FIXED_UTC):
            self.assertEqual(db._now(), "2026-10-07T01:30:05")   # UTC 날짜(10-06)가 아니라 KST 날짜 / KST date, not the UTC one

    def test_mcmail_server_today_is_kst_date(self):
        from app import mcmail
        with patch.object(kst, "_clock", return_value=FIXED_UTC):
            self.assertEqual(mcmail._server_today(), date(2026, 10, 7))

    def test_schedules_aliases_use_the_shared_helper(self):
        from app import schedules
        self.assertIs(schedules.KST, kst.KST)   # schedules.KST 는 계속 가져올 수 있다 / still importable
        with patch.object(kst, "_clock", return_value=FIXED_UTC):
            self.assertEqual(schedules.now_kst(), FIXED_KST)
            self.assertEqual(schedules.now_kst_str(), "2026-10-07T01:30:05")


if __name__ == "__main__":
    unittest.main()
