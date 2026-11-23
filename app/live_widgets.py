"""채팅 실시간 위젯(2026-10-06) — 날씨 · 환율 · 장소(지도) 단순 조회를 의도 판단(LLM 3회) 전에 가로채 위젯 카드로 답한다.

감지: 어휘 1차 거름(+ 제외어) → lite LLM 1회로 종류 · 값 추출(시간 예산 8초, 실패 시 규칙 추출). 메일 · 보고서 · 분석 · 문서 ·
예약 · 일정처럼 다른 작업이 섞이거나 사내 자료 질문이면 가로채지 않고 기존 흐름으로 보낸다. 직전 답변이 위젯(또는 지역 되묻기)
이면 짧은 후속("내일은?", "선릉역")을 이어받는다.
답변: thinking → answer_head(외부) → token → done{cards, sources}. 숫자는 API 값 그대로이고, LLM 은 날씨 요약 한두 문장만 쓴다
(환율 · 장소 글은 템플릿 — 구글 장소 데이터로 AI 글을 만들지 않는다). 장소 카드는 done 에만 전체를 싣고, 채팅 기록(meta)에는
검색어와 장소 ID 만 남긴다(구글 약관).

Chat live widgets (2026-10-06) — intercepts plain weather, exchange-rate and place (map) lookups before intent
planning (three LLM calls) and answers with a widget card. Detection: a vocabulary gate (+ exclusions) → one lite LLM
call extracts kind and values (8-second budget, rule extraction on failure). Requests mixed with other work (mail,
reports, analysis, documents, schedules, calendar) or internal-material questions fall through to the normal flow. A
short follow-up ("내일은?", "선릉역") continues the previous widget answer (or the area question). Answer: thinking →
answer_head (external) → token → done{cards, sources}. Numbers come straight from the APIs; the LLM writes only the
one-or-two-sentence weather summary (FX and place texts are templates — no AI text is made from Google place data).
The place card travels in full only in 'done'; the chat history (meta) keeps just the query and place IDs (Google terms).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import AsyncIterator

from app import db, kst, live_fx, live_places, live_usage, live_weather, llm

logger = logging.getLogger(__name__)

KINDS = ("weather", "fx", "places")
LLM_BUDGET_SEC = 8.0
POOL_SIZE = 6
PENDING_MAX_MIN = 30   # 지역 되묻기는 30분 안의 바로 다음 답만 이어받는다 / the area question only takes the next reply within 30 min
_POOL = ThreadPoolExecutor(max_workers=POOL_SIZE, thread_name_prefix="live-llm")
_inflight = {"n": 0}
_inflight_lock = threading.Lock()

# ── 1차 거름 · 제외어 / gate vocabulary and exclusions ──
# 비 · 눈 · 엔은 앞에 한글이 붙으면 다른 낱말이다(설비가 · 준비가 · 그때엔) / 비, 눈 and 엔 after a Hangul letter belong to other words
_NB = r"(?<![가-힣])"
_RX = {
    "weather": re.compile(
        r"날씨|기온|일기\s*예보|강수\s*확률|몇\s*도(?:야|예요|에요|인가요?|니|일까|\s|\?|$)"
        r"|" + _NB + r"비\s*(?:가|와|와요|올|오(?:나|니|는|려|면)|소식)"
        r"|" + _NB + r"눈\s*(?:이\s*)?(?:와|올|오(?:나|니|는))"
        r"|우산|폭염|한파|\bweather\b|\bforecast\b|\btemperature\b|\brain(?:ing|y)?\b", re.I),
    "fx": re.compile(
        r"환율|환전|환산|exchange\s*rate|\b(?:usd|jpy|eur|cny|gbp|krw)\b|원화로|한화로|원으로\s*(?:얼마|바꾸|환)"
        r"|몇\s*(?:달러|엔|유로|위안|파운드|불)"
        r"|(?:달러|" + _NB + r"엔|유로|위안|파운드)(?:에|는|은)\s*얼마"
        r"|(?:달러|엔화|유로|위안화?|파운드|바트|페소|루피|링깃|프랑|동화)\s*(?:는|은|가|이)?\s*(?:얼마|시세|원화|한화|으로|로|환|가치)", re.I),
    "places": re.compile(
        r"맛집|식당|음식점|레스토랑|카페(?!테리아)|술집|빵집|베이커리|브런치|디저트|이자카야|횟집|고깃집|밥집|가볼\s*만한|가볼만한|명소|관광지"
        r"|핫플|근처|주변|가까운|지도\s*(?:로|에서|에)|위치\s*(?:알려|보여|좀)|가는\s*길|길\s*찾기"
        r"|\brestaurants?\b|\bcafes?\b|\bnear\s+me\b|\bnearby\b|\bon\s+(?:a|the)\s+map\b", re.I),
}
_EXCLUDE = re.compile(
    r"데이터|분석|통계|추이|그래프|차트|보고서|리포트|대시보드|매출|실적|규정|정책|지침|문서|파일|자료|메일|이메일|팀즈|메시지"
    r"|보내|발송|전송|공유해|예약|PPT|피피티|엑셀|워드|PDF|만들어|작성해|요약해|번역해|일정|회의|할\s*일|결재|교육|주문|재고"
    r"|고객|사내|회사|본사|구내|사옥|사무실|자리|연차|휴가|연락처|직원|부서"
    r"|\bAPI\b|\breport\b|\bemail\b|\bmail\b|\bschedule\b|\banaly", re.I)
_CANCEL = re.compile(r"^(?:아니|아냐|됐어|괜찮아|취소|그만|고마워|감사|ㅇㅋ|ok|thanks?)", re.I)
# LLM 없이 받아들일 때 필요한 단서 / the cues the rules need when the LLM is unavailable
_WX_STRONG = re.compile(r"날씨|기온|일기\s*예보|강수\s*확률|몇\s*도|\bweather\b|\bforecast\b|\btemperature\b", re.I)
_FX_STRONG = re.compile(r"환율|환전|exchange\s*rate", re.I)
_PLACE_NOUN = re.compile(r"맛집|식당|음식점|레스토랑|카페(?!테리아)|술집|빵집|베이커리|브런치|디저트|이자카야|횟집|고깃집|밥집"
                         r"|가볼\s*만한|가볼만한|명소|관광지|핫플|\brestaurants?\b|\bcafes?\b", re.I)
_MAP_CUE = re.compile(r"지도\s*(?:로|에서|에)|위치|가는\s*길|길\s*찾기|\bon\s+(?:a|the)\s+map\b", re.I)

# ── 규칙 추출용 어휘 / rule-extraction vocabulary ──
_CITIES = ("서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "수원", "성남", "고양", "용인", "창원", "청주",
           "전주", "천안", "포항", "제주", "서귀포", "강릉", "춘천", "원주", "여수", "경주", "안동", "목포", "평택", "김해",
           "판교", "분당", "일산", "송도", "강남", "여의도", "도쿄", "오사카", "베이징", "상하이", "뉴욕", "런던", "파리",
           "Seoul", "Busan", "Tokyo", "Osaka", "New York", "London", "Paris")
_DAYS = (("오늘", 0), ("내일", 1), ("모레", 2), ("글피", 3), ("today", 0), ("tomorrow", 1))
_WEEK = re.compile(r"이번\s*주|주간|일주일|이번주|한\s*주|this\s+week|weekly|week", re.I)
_DOW = ("월", "화", "수", "목", "금", "토", "일")
_CCY_WORDS = (("홍콩달러", "HKD"), ("홍콩 달러", "HKD"), ("대만달러", "TWD"), ("대만 달러", "TWD"),
              ("싱가포르", "SGD"), ("호주", "AUD"), ("캐나다", "CAD"), ("뉴질랜드", "NZD"), ("스위스", "CHF"),
              ("엔화", "JPY"), ("엔", "JPY"), ("유로", "EUR"), ("위안", "CNY"), ("파운드", "GBP"), ("바트", "THB"),
              ("필리핀", "PHP"), ("페소", "PHP"), ("루피아", "IDR"), ("루피", "INR"), ("링깃", "MYR"),
              ("베트남", "VND"), ("동화", "VND"), ("달러", "USD"), ("usd", "USD"), ("jpy", "JPY"), ("eur", "EUR"),
              ("cny", "CNY"), ("gbp", "GBP"), ("dollar", "USD"), ("yen", "JPY"), ("euro", "EUR"), ("yuan", "CNY"))
_TAIL = re.compile(r"\s*(?:좀|좀\s*)?(?:알려\s*줘|알려\s*주세요|추천해\s*줘|추천\s*좀|추천해\s*주세요|찾아\s*줘|찾아\s*주세요"
                   r"|보여\s*줘|보여\s*주세요|어디야|어디\s*있어|어디\s*있나요|어디|있어|있나요|해\s*줘|주세요|좀|요)?[\s?.!]*$")
_AREA = re.compile(r"([가-힣A-Za-z0-9]{2,15}?(?:역|동|구|시|군|읍|면|로|길|공원|타워|센터|대학교|대학|병원|시청|구청))(?:\s|$|근처|주변|에서|앞|쪽)")
_NEAR = re.compile(r"([가-힣A-Za-z0-9]{2,15})\s*(?:근처|주변|부근|앞|쪽)")
# 후속 질문에서 지울 낱말(날짜 · 조사 · 되묻는 말) / words a follow-up may carry besides the changed value
_FOLLOW_STRIP = re.compile(r"오늘|내일|모레|글피|이번\s*주|다음\s*주|주말|주간|[월화수목금토일]요일|날씨|기온|환율|어때요?|어떨까|어떻게\s*돼"
                           r"|알려\s*줘|보여\s*줘|그럼|그러면|다시|는요|은요|은|는|도|요|이|가|에|의|좀|[?!.,~\s]")
_ASKY = re.compile(r"뭐|어떻게|방법|왜|언제|누구|연락|신청|해줘|할까|먹지|보자|하자|가자")


def gate(message: str) -> list[str]:
    """어휘가 맞는 위젯 종류(제외어가 있으면 빈 목록) / widget kinds whose vocabulary matches (empty with an exclusion)."""
    msg = (message or "").strip()
    if not msg or len(msg) > 200 or _EXCLUDE.search(msg):
        return []
    return [k for k in KINDS if _RX[k].search(msg)]


def _age_min(created_at) -> float:
    try:
        return (kst.now() - kst.to_kst(datetime.fromisoformat(str(created_at)))).total_seconds() / 60
    except (TypeError, ValueError):
        return 10 ** 6


def _prev_widget(chat_id: str) -> dict | None:
    """직전 assistant 답변이 위젯이면 그 조회 값(meta.live) 또는 30분 안의 지역 되묻기(meta.live_pending).
    The previous assistant answer's widget lookup values (meta.live) or its area question within 30 minutes (meta.live_pending)."""
    try:
        rows = db.list_messages(chat_id)
    except Exception:  # noqa: BLE001 — 기록을 못 읽으면 후속 이어받기만 건너뛴다 / only follow-up inheritance is skipped
        return None
    for m in reversed(rows):
        if m.get("role") != "assistant":
            continue
        meta = m.get("meta") or {}
        if meta.get("kind") in ("explore", "explore_note"):
            continue
        if isinstance(meta.get("live_pending"), dict):
            if _age_min(m.get("created_at")) > PENDING_MAX_MIN:
                return None
            return {**meta["live_pending"], "pending": True}
        if isinstance(meta.get("live"), dict):
            return dict(meta["live"])
        return None
    return None


def _looks_like_area(msg: str) -> bool:
    """지역 · 장소 이름 하나로 보이는가(되묻기 답 · 장소 후속) / does the reply look like one area or place name."""
    t = _TAIL.sub("", msg or "").strip(" ?.!~")
    if not t or len(t) > 15 or _CANCEL.search(t) or _ASKY.search(t):
        return False
    if _NEAR.search(t) or _AREA.search(t + " ") or any(c in t for c in _CITIES):
        return True
    return bool(re.fullmatch(r"[가-힣A-Za-z0-9]{2,10}", t))


def _followup_only(msg: str, prev: dict) -> bool:
    """날짜 · 지역 · 통화만 바꾸는 짧은 후속인가("내일은?", "부산은?", "엔화는?") / a short follow-up that only changes the day,
    place or currency."""
    t = _TAIL.sub("", msg or "")
    for c in _CITIES:
        t = t.replace(c, " ")
    if prev.get("kind") == "fx":
        for word, _code in _CCY_WORDS:
            t = re.sub(re.escape(word), " ", t, flags=re.I)
        t = re.sub(r"\d[\d,.]*\s*(?:만|천|백)?\s*(?:원|불|\$)?", " ", t)
    rest = _FOLLOW_STRIP.sub("", t)
    if not re.search(r"[가-힣A-Za-z]", rest):
        return True
    # 남은 것이 지역 이름 하나면 위치 후속(역삼동은?) / one remaining area name is a location follow-up
    return prev.get("kind") == "weather" and bool(_AREA.search(rest + " ")) and len(rest) <= 12


_EXTRACT_SYSTEM = """너는 채팅 질문이 실시간 위젯 하나로 바로 답할 '단순 조회'인지 판단하고 값을 뽑는다. JSON 객체 하나만 출력한다.
kind:
- "weather": 날씨 · 기온 · 비/눈 · 우산 질문. location = 도시 · 지역 · 역 이름(없으면 null). day = 0~6(오늘 0, 내일 1, 모레 2,
  요일은 today 기준 가장 가까운 그 요일). '이번 주' · '주간'이면 day 0, week true.
- "fx": 환율 · 환전 · 통화 환산. base = ISO 4217 코드(달러 USD, 엔 JPY, 유로 EUR, 위안 CNY, 파운드 GBP …), quote = 기본 KRW,
  amount = 기준 통화 금액 숫자(없으면 null). "1만원은 몇 달러"처럼 원화를 바꾸면 base KRW, quote 그 통화. 길이 · 무게 단위 환산은 none.
- "places": 맛집 · 식당 · 카페 등 장소 찾기 · 추천 · 위치 · 지도 · 가는 길. query = 구글 지도 검색어(지역 + 종류, 예 "선릉역 맛집",
  가는 길이면 목적지 이름), area = 지역 이름(없으면 null). '근처'인데 지역이 없으면 area null. 사람 · 회사 안 자리는 none.
- "none": 위 셋이 아니거나, 메일 · 보고서 · 분석 · 문서 · 예약 · 일정 같은 다른 작업이 함께 있거나, 사내 규정 · 데이터 질문.
previous 가 있으면, 이번 메시지가 날짜 · 지역 · 통화만 바꾸는 짧은 후속일 때만 그 조회를 이어받는다(예: 날씨 다음 "내일은?" →
weather, 같은 location, day 1). 다른 이야기면 none. previous.pending 이 places 이고 이번 메시지가 지역 · 장소 이름일 때만
places(area = 메시지, query = 메시지 + " " + previous.what), 아니면 none.
출력 형식: {"kind":"weather|fx|places|none","location":null,"day":0,"week":false,"base":null,"quote":"KRW","amount":null,"query":null,"area":null}"""


def _submit(fn, *args):
    """LLM 호출을 풀에 넣는다 — 풀이 꽉 차면(멈춘 호출들) None 이라 규칙으로 간다 / queue an LLM call; None when the pool is
    saturated by stuck calls, so the caller uses its fallback."""
    with _inflight_lock:
        if _inflight["n"] >= POOL_SIZE:
            return None
        _inflight["n"] += 1
    fut = _POOL.submit(fn, *args)

    def _done(_f):
        with _inflight_lock:
            _inflight["n"] -= 1
    fut.add_done_callback(_done)
    return fut


def _llm_extract(msg: str, kinds: list[str], prev: dict | None) -> dict | None:
    today = kst.today()
    payload = {"message": msg, "candidates": kinds, "previous": prev,
               "today": today.isoformat(), "weekday": _DOW[today.weekday()]}
    fut = _submit(llm.generate, json.dumps(payload, ensure_ascii=False), _EXTRACT_SYSTEM, True, None, "lite")
    if fut is None:
        logger.warning("위젯 추출 LLM 풀이 가득 참 — 규칙 추출로 / widget extraction pool saturated, using rules")
        return None
    try:
        out = fut.result(timeout=LLM_BUDGET_SEC)
    except FutureTimeout:
        fut.cancel()   # 아직 줄에 있으면 취소(쿼터 낭비 방지) / cancel if still queued (saves quota)
        logger.warning("위젯 추출 LLM 시간 초과 — 규칙 추출로 / widget extraction LLM timed out, using rules")
        return None
    except Exception as e:  # noqa: BLE001 — 429 · 파싱 실패 등은 규칙 추출로 / 429 or parse failures fall back to rules
        logger.warning("위젯 추출 LLM 실패 — 규칙 추출로 / widget extraction LLM failed, using rules: %s: %s",
                       type(e).__name__, str(e)[:200])
        return None
    if not isinstance(out, dict) or out.get("kind") not in KINDS + ("none",):
        return None
    return out


def _day_of(msg: str) -> tuple[int, bool]:
    low = msg.lower()
    for word, d in _DAYS:
        if word in low:
            return d, False
    m = re.search(r"([월화수목금토일])요일", msg)
    if m:
        target = _DOW.index(m.group(1))
        return (target - kst.today().weekday()) % 7, False
    return 0, bool(_WEEK.search(msg)) or "주말" in msg


def _location_of(msg: str) -> str | None:
    for c in _CITIES:
        if c.lower() in msg.lower():
            return c
    m = re.search(r"([가-힣A-Za-z]{2,12}?)\s*(?:의\s*)?(?:(?:오늘|내일|모레|이번\s*주|주간|지금)\s*)?(?:날씨|기온)", msg)
    if m and m.group(1) not in ("오늘", "내일", "모레", "지금", "이번", "요즘", "현재", "주간", "이번주"):
        return m.group(1)
    m = _AREA.search(msg + " ")
    return m.group(1) if m else None


def _currency_of(msg: str) -> list[str]:
    low = msg.lower()
    found: list[tuple[int, str]] = []
    for word, code in _CCY_WORDS:
        i = low.find(word.lower())
        if i >= 0 and code not in [c for _, c in found]:
            found.append((i, code))
    return [c for _, c in sorted(found)]


def _amount_of(msg: str) -> float | None:
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(만|천|백)?\s*(?:원|달러|엔|유로|위안|파운드|불|\$|usd|jpy|eur)", msg, re.I)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return v * {"만": 10000, "천": 1000, "백": 100}.get(m.group(2) or "", 1)


def _area_of(msg: str) -> str | None:
    m = _NEAR.search(msg) or _AREA.search(msg + " ")
    return m.group(1) if m else next((c for c in _CITIES if c in msg), None)


def _rules_extract(msg: str, kinds: list[str], prev: dict | None) -> dict | None:
    """LLM 없이 뽑는다 — 보수적: 구체적인 값(지역 · 날짜 · 통화 · 장소 종류)이 있을 때만 받아들이고, 후속은 날짜 · 지역 · 통화만
    바꾸는 말일 때만 이어받는다. / Extraction without the LLM, conservative: accepted only with a concrete value (area, day,
    currency, place type); follow-ups only when they change just the day, place or currency."""
    if prev and prev.get("pending") and prev.get("kind") == "places" and not kinds:
        if not _looks_like_area(msg):
            return None
        area = _TAIL.sub("", msg).strip(" ?.!~")
        return {"kind": "places", "area": area, "query": f"{area} {prev.get('what') or '맛집'}".strip()}
    kind = kinds[0] if kinds else (prev or {}).get("kind")
    if kind == "weather":
        day, week = _day_of(msg)
        loc = _location_of(msg)
        if kinds and not (_WX_STRONG.search(msg) or loc or day or week):
            return None   # '비 와?' 같은 말만으로는 LLM 없이 받지 않는다 / a bare rain cue is not enough without the LLM
        if not kinds and not (prev and _followup_only(msg, prev)):
            return None
        return {"kind": "weather", "location": loc or (prev or {}).get("location"), "day": day, "week": week}
    if kind == "fx":
        ccys = _currency_of(msg)
        amount = _amount_of(msg)
        if kinds and not (_FX_STRONG.search(msg) or ccys):
            return None   # '단위 환산' 같은 말은 받지 않는다 / unit conversions are not exchange rates
        if not kinds and not (prev and _followup_only(msg, prev) and (ccys or amount)):
            return None
        if re.search(r"\d[\d,]*\s*(?:만|천)?\s*원", msg) and ccys:   # "1만원은 몇 달러" → 원화를 바꾼다 / converting won
            return {"kind": "fx", "base": "KRW", "quote": ccys[0], "amount": amount}
        base = ccys[0] if ccys else (prev or {}).get("base") or "USD"
        return {"kind": "fx", "base": base, "quote": "KRW", "amount": amount}
    if kind == "places":
        if not kinds:
            if not (prev and _looks_like_area(msg)):
                return None
            area = _TAIL.sub("", msg).strip(" ?.!~")
            return {"kind": "places", "area": area, "query": f"{area} {_what_of(prev.get('query'), prev.get('area'))}".strip()}
        area = _area_of(msg)
        if not area or not (_PLACE_NOUN.search(msg) or _MAP_CUE.search(msg)):
            return None   # 지역과 장소 종류(또는 지도 요청)가 다 있어야 / needs an area and a place type (or a map request)
        query = _TAIL.sub("", msg).strip()
        if prev and prev.get("pending") and prev.get("what") and prev["what"] not in query:
            query = f"{query} {prev['what']}"   # 되묻기 답에 종류를 붙인다 / add the category to the area reply
        return {"kind": "places", "query": query, "area": area}
    return None


def detect(chat_id: str, message: str) -> dict | None:
    """위젯으로 답할 질문이면 추출 값, 아니면 None / the extracted values when a widget should answer, else None."""
    msg = (message or "").strip()
    if not msg or len(msg) > 200 or _EXCLUDE.search(msg):
        return None
    kinds = gate(msg)
    prev = None
    if not kinds:
        if len(msg) > 30:
            return None
        prev = _prev_widget(chat_id)
        if not prev:
            return None
        # 후속처럼 보이지 않으면 LLM 도 부르지 않는다 / no LLM call unless the message looks like a follow-up
        if prev.get("pending") or prev.get("kind") == "places":
            if not _looks_like_area(msg):
                return None
        elif not _followup_only(msg, prev):
            return None
    else:
        prev = _prev_widget(chat_id) if len(msg) <= 30 else None
    hit = _llm_extract(msg, kinds or [prev["kind"]], prev)
    if hit is None:
        hit = _rules_extract(msg, kinds, prev)
    if not hit or hit.get("kind") not in KINDS:
        return None
    if hit["kind"] == "places" and not (hit.get("query") or "").strip():
        hit["query"] = _TAIL.sub("", msg).strip()
    return hit


# ── 답변 / answers ──
def _lang(message: str) -> str:
    return "ko" if re.search(r"[가-힣]", message or "") else "en"


_SUMMARY_SYSTEM = """너는 날씨 위젯 바로 위에 붙는 1~2문장 요약을 쓴다. 아래 JSON 의 사실만 쓰고 새 숫자를 만들지 않는다.
질문이 특정 날(focus_day_index)을 물으면 그날 중심으로, '이번 주'면 주간 흐름(비 · 눈 오는 요일, 기온 흐름)을 쓴다.
존댓말(~예요/~이에요), 기온은 °C, 목록 · 제목 · 이모지 · 인사말 없이 문장만."""


def _weather_summary(c: dict, message: str, lang: str, week: bool) -> str:
    system = _SUMMARY_SYSTEM + ("\nWrite in English." if lang == "en" else "")
    payload = {"question": message, "week": week, **live_weather.facts(c, lang)}
    fut = _submit(llm.generate, json.dumps(payload, ensure_ascii=False), system, False, None, "lite")
    out = ""
    if fut is not None:
        try:
            out = str(fut.result(timeout=LLM_BUDGET_SEC) or "").strip()
        except FutureTimeout:
            fut.cancel()
        except Exception:  # noqa: BLE001 — 429 등은 템플릿으로 / 429 and the like fall back to the template
            out = ""
    if out and len(out) <= 400 and not out.startswith("{"):
        return out
    return live_weather.template(c, lang, week)


def _ext(title: str, url: str) -> dict:
    return {"external": [{"n": 1, "title": title, "url": url}]}


async def _weather(hit: dict, message: str, lang: str) -> tuple[str, dict | None, dict | None, dict | None, dict]:
    day = int(hit.get("day") or 0) if str(hit.get("day") or "0").lstrip("-").isdigit() else 0
    week = bool(hit.get("week"))
    try:
        c, found = await asyncio.to_thread(live_weather.get, hit.get("location"), max(0, min(day, 6)))
    except live_weather.WeatherError:
        logger.warning("날씨 조회 실패 / weather fetch failed", exc_info=True)
        return (("I couldn't reach the weather service. Please ask again in a moment." if lang == "en"
                 else "지금 날씨 정보를 가져오지 못했습니다. 잠시 후 다시 물어봐 주세요."), None, None, None, {})
    text = await asyncio.to_thread(_weather_summary, c, message, lang, week)
    if not found and hit.get("location"):
        loc = hit["location"]
        text = ((f"I couldn't find “{loc}”, so here is the weather for Seoul.\n" if lang == "en"
                 else f"‘{loc}’ 위치를 찾지 못해 서울 날씨를 보여 드려요.\n") + text)
    live = {"kind": "weather", "location": c["location"] if found else None}
    return text, c, c, _ext("Open-Meteo", live_weather.SOURCE["url"]), live


async def _fx(hit: dict, message: str, lang: str) -> tuple[str, dict | None, dict | None, dict | None, dict]:
    base = str(hit.get("base") or "USD").upper()
    quote_ccy = str(hit.get("quote") or "KRW").upper()
    try:
        amount = float(hit["amount"]) if hit.get("amount") not in (None, "") else None
    except (TypeError, ValueError):
        amount = None
    if base not in live_fx.CURRENCIES or quote_ccy not in live_fx.CURRENCIES:
        return (("That currency isn't supported yet." if lang == "en"
                 else "아직 지원하지 않는 통화입니다. 달러 · 엔 · 유로 · 위안 · 파운드 등 주요 통화로 물어봐 주세요."),
                None, None, None, {})
    try:
        c = await asyncio.to_thread(live_fx.quote, base, quote_ccy, amount)
    except live_fx.FxError:
        logger.warning("환율 조회 실패 / FX fetch failed", exc_info=True)
        return (("I couldn't get the exchange rate right now. Please ask again in a moment." if lang == "en"
                 else "지금 환율 정보를 가져오지 못했습니다. 잠시 후 다시 물어봐 주세요."), None, None, None, {})
    live = {"kind": "fx", "base": c["base"]["code"], "quote": c["quote"]["code"]}
    return live_fx.text(c, lang), c, c, _ext("Yahoo Finance", live_fx.SOURCE["url"]), live


def _what_of(query: str, area: str | None) -> str:
    rest = query or ""
    if area:   # 빈 문자열 replace 는 글자마다 공백을 끼운다 / replacing '' would insert a space between every character
        rest = rest.replace(area, " ")
    rest = re.sub(r"근처|주변|부근|에서|의|좀", " ", rest)
    return re.sub(r"\s+", " ", rest).strip() or "맛집"


async def _places(hit: dict, message: str, lang: str) -> tuple[str, dict | None, dict | None, dict | None, dict]:
    query = (hit.get("query") or "").strip()[:200]
    area = (hit.get("area") or "").strip()
    has_area = bool(area) or bool(_AREA.search(query + " ")) or any(c in query for c in _CITIES)
    if not has_area and re.search(r"근처|주변|부근|가까운|near\s+me|nearby", message, re.I):
        what = _what_of(query, None)
        text = ("Which area should I search near? For example, “restaurants near Seolleung Station”." if lang == "en"
                else "어느 지역 근처를 찾을까요? ‘선릉역 근처 맛집’처럼 지역을 함께 알려 주세요.")
        return text, None, None, None, {"live_pending": {"kind": "places", "what": what}}
    try:
        res = await asyncio.to_thread(live_places.search, query, lang)
    except live_usage.QuotaExceeded:
        return (("This month's free map allowance is used up, so I can't search places now." if lang == "en"
                 else "이번 달 무료 사용량을 다 써서 장소를 찾을 수 없습니다. 다음 달에 다시 이용해 주세요."), None, None, None, {})
    except live_places.NoKey:
        return (("The Google Maps key isn't configured, so I can't search places." if lang == "en"
                 else "구글 지도 키가 설정되지 않아 장소를 찾을 수 없습니다."), None, None, None, {})
    except (live_places.PlacesError, ValueError):
        logger.warning("장소 검색 실패 / place search failed", exc_info=True)
        return (("I couldn't reach Google Maps right now. Please ask again in a moment." if lang == "en"
                 else "지금 장소 정보를 가져오지 못했습니다. 잠시 후 다시 물어봐 주세요."), None, None, None, {})
    items = res.get("items") or []
    live = {"kind": "places", "query": query, "area": area}
    if not items:
        return ((f"No places matched “{query}”. Try another area or type." if lang == "en"
                 else f"‘{query}’(으)로 찾은 장소가 없어요. 지역이나 종류를 바꿔 다시 물어봐 주세요."), None, None, None, live)
    c = live_places.card(query, area, lang, res)
    n = len(items)
    # 글에는 검색어와 개수만 — 구글 장소 이름은 채팅 기록(content)에 남기지 않는다 / only the query and count go into the
    # text; Google place names never reach the stored message content
    text = (f"I found {n} place{'s' if n > 1 else ''} for “{query}” on the map. Open a place to see its hours and reviews."
            if lang == "en" else f"‘{query}’ 검색 결과 {n}곳을 지도에 표시했어요. 장소를 누르면 영업시간과 후기를 볼 수 있어요.")
    return text, c, live_places.saved(c), _ext(c["source"]["name"], c["source"]["url"]), live


def _thinking(hit: dict, lang: str) -> str:
    k = hit["kind"]
    if lang == "en":
        return {"weather": "Checking the weather", "fx": "Checking the exchange rate", "places": "Searching places"}[k]
    if k == "weather":
        loc = (hit.get("location") or "").strip()
        return f"{loc} 날씨를 확인하고 있어요" if loc else "날씨를 확인하고 있어요"
    return {"fx": "환율을 확인하고 있어요", "places": "장소를 찾고 있어요"}[k]


async def answer(chat: dict, hit: dict, message: str) -> AsyncIterator[dict]:
    """위젯 답변 이벤트 — 저장은 여기서 한 번(done.message_id) / widget answer events, saved once here (done.message_id)."""
    from app.answers import _smooth
    lang = _lang(message)
    yield {"type": "thinking", "text": _thinking(hit, lang)}
    runner = {"weather": _weather, "fx": _fx, "places": _places}[hit["kind"]]
    try:
        text, live_card, saved_card, sources, extra = await runner(hit, message, lang)
    except Exception:  # noqa: BLE001 — 예상 밖 오류도 안내 글로 마감(채팅이 오류 이벤트로 끝나지 않게) / close with a note, not an error event
        logger.warning("위젯 답변 실패 / widget answer failed: %s", hit.get("kind"), exc_info=True)
        text = ("I couldn't fetch that right now. Please ask again in a moment." if lang == "en"
                else "지금 정보를 가져오지 못했습니다. 잠시 후 다시 물어봐 주세요.")
        live_card = saved_card = sources = None
        extra = {}
    yield {"type": "answer_head", "source": "외부"}
    async for piece in _smooth(text):
        yield {"type": "token", "text": piece}
    meta: dict = {"source": "외부"}
    if saved_card:
        meta["cards"] = [saved_card]
    if sources:
        meta["sources"] = sources
    if extra.get("live_pending"):
        meta["live_pending"] = extra["live_pending"]
    elif extra:
        meta["live"] = extra
    done: dict = {"type": "done", "message_id": await asyncio.to_thread(db.add_message, chat["id"], "assistant", text, meta)}
    if live_card:
        done["cards"] = [live_card]
    if sources:
        done["sources"] = sources
    yield done
