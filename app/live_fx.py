"""채팅 환율 위젯 데이터(2026-10-06) — yfinance(야후 파이낸스)로 원화 기준 환율을 받아 위젯 카드 JSON 으로 정리한다.

한국 은행 고시처럼 달러 기준 재정 환율로 계산한다: 1 기준통화 = (1달러당 상대통화) ÷ (1달러당 기준통화). 그래서 필요한 시세는
'{통화}=X'(1달러당 그 통화) 뿐이고, 모든 통화쌍이 같은 방식으로 나온다. 기준 시각은 마지막 1분봉 시각을 KST 로 바꾼 값이다
(주말엔 시장이 쉬어 마지막 거래 시각이 나온다). 엔화 · 동 · 루피아는 은행처럼 100 단위로 보인다.
yfinance 는 비공식 도구이고 야후 데이터는 개인용이라고 밝히므로, 판매 제품에 넣을 때는 이 모듈의 _FETCH 만 유료 API 로 바꾼다.

Chat exchange-rate widget data (2026-10-06) — fetches KRW-based rates with yfinance (Yahoo Finance) into widget-card
JSON. Like Korean bank postings it uses USD cross rates: 1 base = (quote per USD) ÷ (base per USD), so only '{CCY}=X'
(units per USD) is needed and every pair works the same way. The as-of time is the last one-minute bar converted to
KST (weekends show the last trade). JPY, VND and IDR are shown per 100 like the banks. yfinance is unofficial and says
Yahoo data is for personal use, so a product build swaps only this module's _FETCH for a paid API.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app import kst

logger = logging.getLogger(__name__)

SOURCE = {"name": "Yahoo Finance", "url": "https://finance.yahoo.com/markets/currencies/"}
TTL = 60   # 시세 캐시 60초 / quote cache, 60 s

# 코드 → (한국어 이름, 영어 이름, 국가 코드, 기호, 기본 단위, 한국어 단위 낱말)
# code → (Korean name, English name, country code, symbol, default unit, Korean unit word)
CURRENCIES: dict[str, tuple[str, str, str, str, int, str]] = {
    "KRW": ("대한민국 원", "South Korean won", "KR", "₩", 1, "원"),
    "USD": ("미국 달러", "US dollar", "US", "$", 1, "달러"),
    "JPY": ("일본 엔", "Japanese yen", "JP", "¥", 100, "엔"),
    "EUR": ("유로", "Euro", "EU", "€", 1, "유로"),
    "CNY": ("중국 위안", "Chinese yuan", "CN", "¥", 1, "위안"),
    "GBP": ("영국 파운드", "British pound", "GB", "£", 1, "파운드"),
    "HKD": ("홍콩 달러", "Hong Kong dollar", "HK", "HK$", 1, "홍콩달러"),
    "TWD": ("대만 달러", "New Taiwan dollar", "TW", "NT$", 1, "대만달러"),
    "SGD": ("싱가포르 달러", "Singapore dollar", "SG", "S$", 1, "싱가포르달러"),
    "AUD": ("호주 달러", "Australian dollar", "AU", "A$", 1, "호주달러"),
    "CAD": ("캐나다 달러", "Canadian dollar", "CA", "C$", 1, "캐나다달러"),
    "NZD": ("뉴질랜드 달러", "New Zealand dollar", "NZ", "NZ$", 1, "뉴질랜드달러"),
    "CHF": ("스위스 프랑", "Swiss franc", "CH", "CHF", 1, "스위스프랑"),
    "VND": ("베트남 동", "Vietnamese dong", "VN", "₫", 100, "동"),
    "THB": ("태국 바트", "Thai baht", "TH", "฿", 1, "바트"),
    "PHP": ("필리핀 페소", "Philippine peso", "PH", "₱", 1, "페소"),
    "INR": ("인도 루피", "Indian rupee", "IN", "₹", 1, "루피"),
    "IDR": ("인도네시아 루피아", "Indonesian rupiah", "ID", "Rp", 100, "루피아"),
    "MYR": ("말레이시아 링깃", "Malaysian ringgit", "MY", "RM", 1, "링깃"),
    "MXN": ("멕시코 페소", "Mexican peso", "MX", "MX$", 1, "멕시코페소"),
}


class FxError(Exception):
    """환율 시세를 받지 못했다 / the quote could not be fetched."""


def _yf_last(symbol: str) -> tuple[float, float]:
    """yfinance 마지막 1분봉 → (값, epoch 초). 1일이 비면(주말 직후 등) 5일로 다시 / last 1-minute bar; retry with 5 days."""
    import yfinance as yf   # 무거운 의존성이라 처음 쓸 때 불러온다 / heavy dependency, imported on first use
    tk = yf.Ticker(symbol)
    for period in ("1d", "5d"):
        h = tk.history(period=period, interval="1m")
        if h is not None and len(h):
            return float(h["Close"].iloc[-1]), float(h.index[-1].timestamp())
    raise FxError(f"시세 없음: {symbol}")


_FETCH = _yf_last   # 테스트 · 유료 API 교체 이음새 / seam for tests and a paid-API swap
_cache: dict[str, tuple[float, float, float]] = {}   # 기호 → (받은 시각, 값, 시세 epoch) / symbol → (fetched, value, quote epoch)
_lock = threading.Lock()


def usd_rate(code: str) -> tuple[float, float]:
    """1달러당 그 통화(값, 시세 epoch). USD 는 1 / units of `code` per USD (value, quote epoch); USD is 1."""
    if code == "USD":
        return 1.0, time.time()
    sym = f"{code}=X"
    now = time.time()
    with _lock:
        hit = _cache.get(sym)
    if hit and now - hit[0] < TTL:
        return hit[1], hit[2]
    try:
        val, ts = _FETCH(sym)
    except FxError:
        raise
    except Exception as e:  # noqa: BLE001 — yfinance 는 다양한 예외(429 · 파싱)를 던진다 / yfinance raises many kinds
        raise FxError(f"{sym}: {type(e).__name__}: {e}") from None
    if not val or val <= 0:
        raise FxError(f"잘못된 시세: {sym}")
    with _lock:
        _cache[sym] = (now, val, ts)
    return val, ts


def quote(base: str = "USD", quote_ccy: str = "KRW", amount: float | None = None) -> dict:
    """환율 카드 JSON / the exchange-rate card JSON."""
    base, quote_ccy = (base or "USD").upper(), (quote_ccy or "KRW").upper()
    if base not in CURRENCIES or quote_ccy not in CURRENCIES:
        raise FxError(f"지원하지 않는 통화: {base}/{quote_ccy}")
    if base == quote_ccy:
        quote_ccy = "KRW" if base != "KRW" else "USD"
    unit = CURRENCIES[base][4]
    amt = float(amount) if amount and float(amount) > 0 else float(unit)
    codes = [c for c in {base, quote_ccy} if c != "USD"]
    with ThreadPoolExecutor(max_workers=2) as ex:   # 두 시세를 함께 받는다(각 1~3초) / fetch both quotes together
        got = dict(zip(codes, ex.map(usd_rate, codes)))
    got["USD"] = (1.0, max([t for _, t in got.values()] or [time.time()]))
    (qv, qt), (bv, bt) = got[quote_ccy], got[base]
    rate = qv / bv
    as_of = kst.from_epoch(min(qt, bt))
    return {"kind": "fx", "v": 1,
            "base": {"code": base, "amount": amt},
            "quote": {"code": quote_ccy, "amount": round(amt * rate, 6)},
            "rate": round(rate, 8), "unit": unit,
            "as_of": kst.iso_offset(as_of), "fetched_at": kst.iso_offset(),
            "source": dict(SOURCE)}


def fmt_num(v: float) -> str:
    """표시 숫자 — 1 이상은 소수 둘째 자리, 1 미만은 유효 숫자 4자리 / 2 decimals at ≥1, four significant digits below."""
    v = float(v)
    if abs(v) >= 1:
        return f"{v:,.2f}"
    return f"{v:.4g}"


def _amt(v: float) -> str:
    return f"{int(v):,}" if float(v).is_integer() else fmt_num(v)


def text(c: dict, lang: str = "ko") -> str:
    """시안 문장 그대로의 결정적 답변 / the deterministic answer, worded like the design."""
    b, q = c["base"], c["quote"]
    bn, qn = CURRENCIES[b["code"]], CURRENCIES[q["code"]]
    p = kst.aware(_parse(c["as_of"]))
    if lang == "en":
        when = f"{_MON[p.month - 1]} {p.day}, {p.year} {p:%H:%M} KST"
        return (f"As of now, {_amt(b['amount'])} {bn[1]} ({b['code']}) ≈ {fmt_num(q['amount'])} {qn[1]} ({q['code']}).\n"
                f"Rate as of {when}.")
    when = f"{p.year}년 {p.month}월 {p.day}일 {p:%H:%M} KST"
    return (f"현재 기준으로 {_amt(b['amount'])}{bn[5]}({b['code']}) ≈ {fmt_num(q['amount'])}{qn[5]}({q['code']}) 입니다.\n"
            f"{when} 기준 환율입니다.")


_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _parse(iso: str):
    from datetime import datetime
    return datetime.fromisoformat(iso)
