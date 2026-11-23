# -*- coding: utf-8 -*-
"""M코스메틱 이메일 에이전트 — 과거 이력(2026-09-23 ~ 기준일 7일 전) 생성기. 시드 JSON(app/mcmail_seed.json)에 완료된 업무 이력을
덧붙인다(2026-10-13 사용자 지시 "9/23~10/22 데이터로 실제같이 채워줘").

방식: 격리 DB(tests/db_fixture.isolate_db)에 지금 시드를 기준일(ANCHOR)로 넣은 뒤, 영업일마다 서버 날짜(_State.today)를 그날로
두고 app/mcmail.py 의 실제 처리 함수(_new_inbound → _new_case_for/_link → _apply_erp → _run_draft → _apply_send,
_apply_order → Sales Order·출하 등록, _close_mail, _register_error → 재처리)를 그대로 돌린다. 그래서 화면 규칙(상태·다음 단계·
Case 이력·ERP 결과·초안 문구·발신 메일)과 어긋나지 않는다. 끝나면 새 레코드(메일·Case·오류·출하)를 ANCHOR 대비 토큰으로 바꿔
(app.mcmail._tokenize) 시드에 합친다 — 기존 레코드·seq·마스터·시나리오는 그대로, 활동 기록(LOG)은 오늘 것만 둔다(과거 기록은
날짜가 없어 싣지 않는다). 번호는 기존 것보다 작게 둔다(메일 E-0701~, Case 00061~, SO 00061~, INQ 00020~, 오류 ERR-0001~).

재현: 난수 시드 고정(SEED). 실행 뒤 tests/test_mcmail*.py 의 건수 기대값, tests/fixtures/mcmail_api.json(capture_mcmail_fixtures.py),
바탕화면 단독본(export_mcmail_standalone.py --today 2026-10-22)을 함께 갱신한다.

실행:  .venv/Scripts/python.exe scripts/build_mcmail_history.py            (app/mcmail_seed.json 갱신)
       .venv/Scripts/python.exe scripts/build_mcmail_history.py --check    (생성만 하고 통계만 출력)

M Cosmetic Email Agent — history generator (2026-09-23 up to seven days before the anchor). Appends completed work history
to the seed JSON (user request 2026-10-13: "fill 9/23 to 10/22 with realistic data").
Method: the current seed is loaded into an isolated DB anchored to ANCHOR; then, business day by business day, the server's
day (_State.today) is set to that day and app/mcmail.py's real processing functions run as they would in the app (new
inbound → case / link → ERP lookup → draft → send, order entry → sales order and shipment, close, error → retry), so the
result obeys every page rule (status, next step, case history, ERP results, draft wording, outbound mails). The new records
(mails, cases, errors, shipments) are then tokenized relative to ANCHOR (app.mcmail._tokenize) and merged into the seed;
existing records, seq, masters and the scenario stay, and the activity log keeps only today's lines (history lines carry no
date). Ids stay below the existing ones (mails E-0701+, cases 00061+, SOs 00061+, INQ 00020+, errors ERR-0001+).
Deterministic (fixed random SEED). Afterwards update the count expectations in tests/test_mcmail*.py, the fixture
(capture_mcmail_fixtures.py) and the desktop standalone (export_mcmail_standalone.py --today 2026-10-22).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from contextlib import ExitStack
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.stdout.reconfigure(encoding="utf-8")

from db_fixture import isolate_db  # noqa: E402
from app import db, mcmail  # noqa: E402
from app.mcmail import _F, _State  # noqa: E402

SEED_PATH = ROOT / "app" / "mcmail_seed.json"
ANCHOR = date(2026, 10, 22)                 # 바탕화면 단독본의 기준일 / the desktop standalone's anchor day
HISTORY_START = date(2026, 9, 23)
HISTORY_END = ANCHOR - timedelta(days=7)    # 기존 시드가 D-6 부터 쓴다 / the current seed covers D-6 onward
HOLIDAYS = {date(2026, 9, 24), date(2026, 9, 25),   # 추석 연휴 / Chuseok holidays
            date(2026, 10, 5),                      # 개천절 대체공휴일 / substitute holiday for National Foundation Day
            date(2026, 10, 9)}                      # 한글날 / Hangul Day
SEED = 20261013
START_SEQ = {"mail": 700, "case": 60, "so": 60, "err": 0, "msg": 0}
LIMITS = {"mail": 950, "case": 107, "so": 96, "err": 5, "inq": 37}   # 기존 번호보다 작게 / below the existing numbers
# 고객사 → 담당자(기존 시드의 Case 와 같게) / customer → rep, as in the existing cases
REP = {"누리뷰티 02": "김영업", "다온뷰티 04": "김영업", "라온코스메틱 11": "김영업", "다온코스메틱 14": "이수진",
       "누리코스메틱 12": "이수진", "다온글로벌 34": "이수진", "누리글로벌 32": "이수진", "온유리테일 23": "박민호",
       "온유글로벌 33": "박민호", "누리리테일 22": "박민호", "다온리테일 24": "최지원", "온유코스메틱 13": "최지원"}
QTYS = (100, 150, 200, 300, 300, 400, 500, 500, 600, 800, 1000, 1200, 1500, 2000)
HONOR = {"Sarah Kim": "Sarah Kim"}   # 영문 이름은 '님' 없이 / an English name takes no honorific suffix


def business_days(a: date, b: date) -> list[date]:
    out, d = [], a
    while d <= b:
        if d.weekday() < 5 and d not in HOLIDAYS:
            out.append(d)
        d += timedelta(days=1)
    return out


def next_bday(d: date, n: int) -> date:
    """d 뒤 n 번째 영업일 / the n-th business day after d"""
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in HOLIDAYS:
            n -= 1
    return d


def ga(cust: str) -> str:
    """고객사 이름 뒤 주격 조사 — 끝 숫자의 받침(1·3·6·7·8 → 이, 그 밖 → 가), 기존 시드와 같은 규칙
    The subject particle after a customer name: by the final digit's reading (1, 3, 6, 7, 8 → 이, otherwise 가), as in the seed"""
    tail = cust.rstrip()[-1:]
    return "이" if tail in "13678" else "가"


def kdate(d: date) -> str:
    return f"{d.month}월 {d.day}일"


def loc(n: int) -> str:
    return f"{n:,}"


class Sim:
    """격리 DB 위의 시뮬레이션 — 세션마다 _State 를 열고 날짜·시각을 그날로 둔다 / a simulation over the isolated DB"""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.conn = db._conn()  # noqa: SLF001
        self.conn.executescript(mcmail._SCHEMA)  # noqa: SLF001
        mcmail._seed_into(self.conn, ANCHOR)  # noqa: SLF001
        self.conn.commit()
        self.seq = dict(START_SEQ)
        self.inq = 19
        self.existing_cases = {c["caseId"] for c in mcmail._SEED["CASES"]}  # noqa: SLF001
        self.existing_mails = {e["emailId"] for e in mcmail._SEED["EMAILS"]}  # noqa: SLF001
        self.existing_so = set((mcmail._SEED.get("SHIPMENTS") or {}).keys())  # noqa: SLF001
        self.stats = {"inbound": 0, "outbound": 0, "cases": 0, "so": 0, "errors": 0, "triage": 0}

    def open(self, day: date, minutes: int) -> _State:
        self.conn.execute("BEGIN IMMEDIATE")
        st = _State(self.conn)
        st.today = day.isoformat()
        st.items = mcmail._items_for(st.today)  # noqa: SLF001
        st.clock = minutes
        st.seq = dict(self.seq)
        return st

    def close(self, st: _State) -> None:
        st.new_logs = []        # 과거 활동 기록은 싣지 않는다(날짜가 없다) / history log lines are dropped (no date)
        st.outbox = []
        self.seq = dict(st.seq)
        st.save()
        self.conn.commit()

    # ── 레코드 만들기 / building records ──
    def ents(self, cust: str, cc: str, item: str, icode: str, qty, dd: str, addr: str, so: str = "", qref: str = "") -> dict:
        return {"customer": _F(cust, .98), "customerCode": _F(cc, .99, "master"), "itemName": _F(item, .97),
                "itemCode": _F(icode, .98, "master"), "quantity": _F(str(qty) if qty else "", .97), "deliveryDate": _F(dd, .95),
                "currency": _F("KRW", .99, "master"), "shippingAddress": _F(addr, .93, "master"), "quoteRef": _F(qref, .96, "case"),
                "salesOrder": _F(so, .95, "case")}

    def inbound(self, st: _State, day: date, hhmm: str, o: dict) -> dict:
        seq = self.seq["mail"] + 1
        assert seq <= LIMITS["mail"], "mail ids would reach the existing range"
        o = {"emailId": f"E-{seq:04d}", "receivedDate": f"{day.isoformat()} {hhmm}", **o}
        e = mcmail._new_inbound(st, o)  # noqa: SLF001
        self.seq["mail"] = st.seq["mail"]
        st.emails.append(e)
        self.stats["inbound"] += 1
        return e

    def new_inq_case(self, st: _State, e: dict, item: str, icode: str, qty: int, addr: str) -> dict:
        self.inq += 1
        assert self.inq <= LIMITS["inq"]
        cid = f"INQ-2026-{self.inq:05d}"
        c = {"caseId": cid, "caseType": "문의", "title": f"{item} 재고 문의", "customer": e["customer"], "customerCode": e["entities"]["customerCode"]["value"],
             "status": "재고 조회필요", "assignedUser": e["assignee"], "createdDate": e["receivedDate"], "lastUpdatedDate": e["receivedDate"],
             "salesOrderNumber": "", "entity": {"itemName": item, "itemCode": icode, "quantity": qty, "deliveryDate": "", "unitPrice": None,
                                               "shippingAddress": addr}, "request": f"{loc(qty)}EA 재고 확인", "quoteRef": "", "prev": {}, "changes": [], "actions": []}
        st.cases.insert(0, c)
        e["caseId"] = cid
        e["threadId"] = "T-" + cid[-5:]
        self.stats["cases"] += 1
        return c

    def finish_reply(self, st: _State, e: dict, delay: int) -> None:
        """ERP 조회 → 초안 → 발송(완료) / ERP lookup, draft, send (closes the mail)"""
        st.clock += delay
        assert mcmail._apply_erp(st, e), e.get("flow", {}).get("erpError")  # noqa: SLF001
        mcmail._run_draft(st, e, False, "ko")  # noqa: SLF001
        st.clock += self.rng.randrange(8, 70)
        mcmail._apply_send(st, e)  # noqa: SLF001
        self.stats["outbound"] += 1

    def place_order(self, st: _State, e: dict, delay: int, confirm: bool) -> str:
        st.clock += delay
        assert mcmail._apply_order(st, e), e.get("flow", {}).get("orderError")  # noqa: SLF001
        self.seq["so"] = st.seq["so"]
        assert self.seq["so"] <= LIMITS["so"], "SO numbers would reach the existing range"
        self.stats["so"] += 1
        if confirm:   # 주문확인 메일(선택) / the optional order-confirmation mail
            mcmail._run_draft(st, e, False, "ko")  # noqa: SLF001
            st.clock += self.rng.randrange(5, 40)
            mcmail._apply_send(st, e)  # noqa: SLF001
            self.stats["outbound"] += 1
        return e["flow"]["orderResult"]["so"]

    def fail_then(self, st: _State, e: dict, kind: str) -> None:
        """실패 1회 등록(나중 단계에서 성공해 해결됨) — 오류 번호 예산(ERR-0001~0005)을 넘으면 그냥 성공 경로로
        Register one failure, resolved by the later success; past the error-id budget (ERR-0001 to 0005) the step just succeeds."""
        if self.seq["err"] >= LIMITS["err"]:
            return
        f = e.setdefault("flow", {})
        if kind == "erp":
            cat, act, msg = "ERP 조회 실패", mcmail.ERPMETA[e["classification"]]["act"], "ERP API Timeout (응답 대기 30초 초과)"
            f["erp"], f["erpError"], f["erpApi"] = "error", msg, mcmail.ERPMETA[e["classification"]]["api"]
            e["workStatus"] = "ERP 조회 실패"
        elif kind == "order":
            cat, act, msg = "ERP 주문등록 실패", "ERP 주문등록", "ERP API Timeout (응답 대기 30초 초과)"
            f["order"], f["orderError"], f["orderApi"] = "error", msg, mcmail._ORDER_API  # noqa: SLF001
            e["workStatus"] = "ERP 전송 실패"
        else:
            cat, act, msg = "Email 발송 실패", "Email 발송", "SMTP 451 Temporary failure: 수신 서버 응답 지연"
            f["mail"], f["mailError"], f["mailApi"] = "error", msg, mcmail._MAIL_API  # noqa: SLF001
        mcmail._register_error(st, e, cat, act, msg)  # noqa: SLF001
        self.seq["err"] = st.seq["err"]
        self.stats["errors"] += 1

    def set_ship_state(self, st: _State, so: str, day: date) -> None:
        """그날 기준 출하 상태 — 출하예정일 전은 생산 계획·출하 준비, 지나면 배송 중·출하 완료 / the shipment state as of that day"""
        sh = st.shipments.get(so)
        if not sh:
            return
        ship = date.fromisoformat(sh["shipDate"])
        if day < ship - timedelta(days=4):
            sh["state"], sh["shipQty"], sh["tracking"] = "생산 계획", 0, ""
        elif day < ship:
            sh["state"], sh["shipQty"], sh["tracking"] = "출하 준비", 0, ""
        elif day <= ship + timedelta(days=2):
            sh["state"], sh["shipQty"] = "배송 중", sh["orderQty"]
            sh["tracking"] = sh.get("tracking") or self.tracking()
        else:
            sh["state"], sh["shipQty"] = "출하 완료", sh["orderQty"]
            sh["tracking"] = sh.get("tracking") or self.tracking()

    def tracking(self) -> str:
        return f"{self.rng.choice(['CJ', 'HJ', 'LT'])}-{self.rng.randrange(1000, 9999)}-{self.rng.randrange(1000, 9999)}-{self.rng.randrange(1000, 9999)}"


# ─────────────────────────────────────────────────────────────────────────────
# 문구 — 기존 시드와 같은 문장 모양(화면 사전이 그 모양을 번역한다) / wording in the shapes the page dictionary knows
# ─────────────────────────────────────────────────────────────────────────────

def q_subject(rng: random.Random, item: str, qty: int) -> str:
    base = item.replace(" 50g", "").replace(" 100g", "").replace(" 150g", "")
    return rng.choice([f"{base} 견적 문의드립니다", f"{base} {loc(qty)}EA 견적 요청", f"{base} 견적 요청드립니다", f"[견적 요청] {base} {loc(qty)}개",
                       f"{base} 단가 문의", f"{base} {loc(qty)}EA 단가 및 납기 문의"])


def q_body(rng: random.Random, item: str, qty: int, dd: date, name: str) -> str:
    who = name.split()[0] if name in HONOR else name.split()[0]
    k = kdate(dd)
    v = rng.randrange(5)
    if v == 0:
        return f"안녕하세요.\n\n{item} {loc(qty)}개 견적 문의드립니다.\n단가와 {k}까지 납품 가능한지 확인 부탁드립니다.\n\n감사합니다.\n{who} 드림"
    if v == 1:
        return f"안녕하세요, M코스메틱 영업팀.\n\n아래 품목 견적 부탁드립니다.\n\n- 품목: {item}\n- 수량: {loc(qty)}EA\n- 희망 납기: {dd.isoformat()}\n\n검토 후 회신 부탁드립니다.\n{who} 드림"
    if v == 2:
        return f"안녕하세요.\n\n{item} {loc(qty)}EA 기준 단가 견적 요청드립니다. 납기는 {k} 전후로 생각하고 있습니다.\n재고 상황도 함께 알려주시면 감사하겠습니다.\n\n{who} 드림"
    if v == 3:
        return f"담당자님 안녕하세요.\n\n이번 시즌 물량으로 {item} {loc(qty)}개를 검토 중입니다.\n{k}까지 입고 가능한 단가 제안 부탁드립니다.\n\n감사합니다.\n{who}"
    return f"안녕하세요.\n\n{item} {loc(qty)}개 견적을 요청합니다.\n납기는 {k}까지 가능하면 좋겠습니다. 수량에 따른 단가 구간도 알려주세요.\n\n{who} 드림"


def o_body(rng: random.Random, item: str, qty: int, dd: date, name: str, from_quote: bool) -> str:
    who = name.split()[0]
    k = kdate(dd)
    if from_quote:
        return rng.choice([f"안녕하세요.\n\n견적 확인했습니다. {item} {loc(qty)}개 주문하겠습니다.\n{k}까지 납품 부탁드립니다.",
                           f"안녕하세요.\n\n보내주신 견적으로 진행하겠습니다. {item} {loc(qty)}EA 발주합니다.\n납기는 {k}로 부탁드리며, 발주서 첨부합니다.\n\n{who} 드림",
                           f"안녕하세요.\n\n내부 검토가 끝나 {item} {loc(qty)}개 주문 확정합니다.\n{k} 납품으로 진행 부탁드립니다.\n\n감사합니다.\n{who} 드림"])
    return rng.choice([f"안녕하세요.\n\n{item} {loc(qty)}개 발주 드립니다. {k}까지 납품 부탁드립니다.\n발주서 첨부합니다.\n\n{who} 드림",
                       f"안녕하세요.\n\n아래와 같이 주문합니다.\n\n- 품목: {item}\n- 수량: {loc(qty)}EA\n- 납기: {dd.isoformat()}\n- 배송지: 기존 등록 주소\n\n확인 회신 부탁드립니다.\n{who} 드림"])


def s_body(rng: random.Random, item: str, qty: int, so: str, name: str) -> str:
    who = name.split()[0]
    return rng.choice([f"안녕하세요.\n\n지난번 주문한 {item} {loc(qty)}개 출하 일정 확인 부탁드립니다.\n입고 계획을 잡아야 해서요.\n\n{who} 드림",
                       f"안녕하세요.\n\n{so} 건 출하가 언제 되는지 알려주세요.\n운송장 번호도 나오면 공유 부탁드립니다.\n\n{who} 드림",
                       f"담당자님,\n\n{item} 주문건({so}) 배송 상태 문의드립니다. 매장 입고 일정 조율이 필요합니다.\n\n감사합니다.\n{who}"])


def st_body(rng: random.Random, item: str, qty: int, name: str) -> str:
    who = name.split()[0]
    return rng.choice([f"안녕하세요.\n\n{item} {loc(qty)}개 재고 있나요? 있으면 바로 출고 가능한지도 확인 부탁드립니다.\n\n{who} 드림",
                       f"안녕하세요.\n\n{item} {loc(qty)}EA 즉시 출고 가능한 수량이 얼마나 되는지 재고 확인 부탁드립니다.\n\n{who} 드림",
                       f"담당자님,\n\n급하게 {item} {loc(qty)}개가 필요합니다. 현재 재고와 입고 예정일 알려주세요.\n\n{who}"])


def i_body(rng: random.Random, so: str, name: str) -> str:
    who = name.split()[0]
    return rng.choice([f"안녕하세요.\n\n{so} 인보이스 보내주세요.\n회계 마감 때문에 이번 주 내로 필요합니다.\n\n{who} 드림",
                       f"안녕하세요.\n\n{so} 건 세금계산서/인보이스 발행 부탁드립니다.\n정산 처리에 필요합니다.\n\n{who} 드림",
                       f"담당자님,\n\n입고 확인했습니다. {so} 인보이스 발행 부탁드립니다.\n\n감사합니다.\n{who}"])


ETC_MAILS = [
    {"subject": "추석 연휴 휴무 안내", "intent": "정보제공", "summary": "추석 연휴 휴무 안내",
     "ai": "고객사가 추석 연휴 휴무 일정을 안내했습니다. 처리할 업무는 없습니다.",
     "body": "안녕하세요.\n\n저희 구매팀은 추석 연휴로 9월 24일부터 9월 27일까지 휴무입니다.\n연휴 기간 문의는 9월 28일 이후 순차 회신드리겠습니다.\n\n즐거운 명절 보내세요.", "close": "보관"},
    {"subject": "담당자 변경 안내", "intent": "정보제공", "summary": "구매 담당자 변경 안내",
     "ai": "고객사가 구매 담당자 변경을 안내했습니다. 연락처만 갱신하면 됩니다.",
     "body": "안녕하세요.\n\n10월부터 저희 쪽 구매 담당이 변경되어 안내드립니다. 앞으로 견적·발주 관련 메일은 본 주소로 보내주시면 됩니다.\n\n잘 부탁드립니다.", "close": "보관"},
    {"subject": "Re: 샘플 수령 확인", "intent": "단순회신", "summary": "샘플 수령 확인 회신",
     "ai": "고객사가 보낸 샘플을 잘 받았다고 회신했습니다. 추가로 할 일은 없습니다.",
     "body": "안녕하세요.\n\n보내주신 샘플 잘 받았습니다. 내부 테스트 후 결과 공유드리겠습니다.\n\n감사합니다.", "close": "처리완료"},
    {"subject": "(광고) 수출 물류비 20% 절감 솔루션", "intent": "뉴스레터", "summary": "물류 서비스 광고",
     "ai": "물류 서비스를 홍보하는 광고 메일입니다.", "customer": "(외부 발신)", "sender": "demo-1e7f7b99b5@workspace.example", "senderName": "패스트로지스 마케팅",
     "body": "안녕하세요, 패스트로지스입니다.\n\n지금 계약하시면 첫 3개월 물류비 20% 할인!\n▶ 상담 신청하기\n\n수신거부는 여기를 클릭하세요.", "close": "스팸 처리"},
    {"subject": "2026 코스메틱 박람회 초대", "intent": "정보제공", "summary": "박람회 초대장",
     "ai": "박람회 초대 안내 메일입니다. 처리할 업무는 없습니다.", "customer": "(외부 발신)", "sender": "demo-f0f7578a85@workspace.example", "senderName": "K-뷰티 엑스포 사무국",
     "body": "안녕하세요.\n\n11월 코엑스에서 열리는 2026 코스메틱 박람회에 귀사를 초대합니다.\n참가 신청은 첨부 안내문을 참고해 주세요.", "close": "보관"},
    {"subject": "거래처 등록 서류 요청", "intent": "정보제공", "summary": "거래처 등록 서류 요청",
     "ai": "고객사가 거래처 등록용 사업자등록증 사본을 요청했습니다. 영업지원팀에 전달했습니다.",
     "body": "안녕하세요.\n\n저희 시스템에 거래처 등록을 위해 사업자등록증 사본과 통장 사본을 회신 부탁드립니다.\n\n감사합니다.", "close": "처리완료"},
    {"subject": "Re: 납품 완료 확인", "intent": "단순회신", "summary": "납품 완료 확인 회신",
     "ai": "고객사가 납품이 정상 완료되었다고 회신했습니다. 추가로 할 일은 없습니다.",
     "body": "안녕하세요.\n\n어제 물량 이상 없이 입고 확인했습니다. 감사합니다.\n다음 시즌 물량도 곧 문의드리겠습니다.", "close": "처리완료"},
    {"subject": "주간 뷰티 트렌드 뉴스레터 제41호", "intent": "뉴스레터", "summary": "업계 뉴스레터",
     "ai": "업계 뉴스레터입니다. 처리할 업무는 없습니다.", "customer": "(외부 발신)", "sender": "demo-91602a1004@workspace.example", "senderName": "뷰티인사이트",
     "body": "이번 주 뷰티 트렌드\n\n1. 클린 뷰티 성분 트렌드\n2. 리테일 채널별 판매 동향\n\n구독 해지는 하단 링크를 이용하세요.", "close": "보관"},
]


# ─────────────────────────────────────────────────────────────────────────────
# 이력 일정 만들기 / scheduling the history
# ─────────────────────────────────────────────────────────────────────────────

# 견적의 결말 순환 — 주문 · 검토 회신 · 수량 변경 뒤 주문 · 회신 없음 / how quotes end, cycling: order, review reply, change then order, nothing
OUTCOME = ("order", "order", "review", "order", "delta", "order", "none", "order", "review", "order", "order", "none")
QUOTES_PER_DAY = (2, 2, 3, 2, 1, 3, 2, 2, 3, 2, 2, 3, 2)


def plan(rng: random.Random) -> list[dict]:
    """영업일마다 사건을 배치한 목록(날짜순). 종류·실패·확인 필요는 번호 패턴으로 고정하고(재현 가능), 고객 · 품목 · 수량 · 시각 · 문장만 난수.
    A date-ordered list of events over the business days. Kinds, failures and triage follow fixed index patterns (reproducible);
    only customers, items, quantities, times and wording are random."""
    days = business_days(HISTORY_START, HISTORY_END)
    customers = list(REP.keys())
    items = list(mcmail._ITEMS_T.items())  # noqa: SLF001
    events: list[dict] = []
    orders: list[tuple[date, dict]] = []
    deal_no = 0
    stock_no = 0

    def add(day: date, ev: dict) -> None:
        if day <= HISTORY_END:
            events.append({"day": day, **ev})

    def new_deal(day: date, early: bool, direct: bool) -> dict:
        nonlocal deal_no
        deal_no += 1
        icode, it = rng.choice(items)
        lead = rng.randrange(8, 14) if (early and direct) else rng.randrange(9, 15) if early else rng.randrange(12, 28)
        return {"id": deal_no, "cust": rng.choice(customers), "icode": icode, "item": it["short"],
                "qty": rng.choice(QTYS[:9] if direct else QTYS), "dd": day + timedelta(days=lead)}

    etc_pool = list(ETC_MAILS)
    for i, day in enumerate(days):
        early = i < 5
        for _ in range(QUOTES_PER_DAY[i % len(QUOTES_PER_DAY)]):
            deal = new_deal(day, early, False)
            n = deal["id"]
            add(day, {"kind": "quote", "deal": deal, "triage": n % 9 == 4, "err": "erp" if n % 13 == 6 else ""})
            outcome = OUTCOME[(n - 1) % len(OUTCOME)]
            if outcome == "review":
                add(next_bday(day, rng.randrange(1, 3)), {"kind": "review", "deal": deal})
            elif outcome == "delta":
                d2 = next_bday(day, rng.randrange(1, 3))
                new_qty = rng.choice([q for q in QTYS if q != deal["qty"]])
                add(d2, {"kind": "delta", "deal": deal, "qty": new_qty})
                d3 = next_bday(d2, rng.randrange(1, 3))
                add(d3, {"kind": "order", "deal": deal, "qty": new_qty, "confirm": n % 2 == 0, "err": ""})
                orders.append((d3, deal))
            elif outcome == "order":
                d2 = next_bday(day, rng.randrange(1, 3) if early else rng.randrange(2, 5))
                add(d2, {"kind": "order", "deal": deal, "qty": deal["qty"], "confirm": n % 3 != 0, "err": "order" if n % 11 == 8 else ""})
                orders.append((d2, deal))
        if i % 2 == 0:   # 견적 없는 발주 / a direct purchase order every other day
            deal = new_deal(day, i < 6, True)
            add(day, {"kind": "direct", "deal": deal, "qty": deal["qty"], "confirm": i % 4 == 0, "err": ""})
            orders.append((day, deal))
        if i % 3 != 1:   # 재고 문의 / a stock inquiry
            stock_no += 1
            icode, it = rng.choice(items)
            add(day, {"kind": "stock", "cust": rng.choice(customers), "icode": icode, "item": it["short"], "qty": rng.choice(QTYS[:9]),
                      "err": "mail" if stock_no == 3 else ""})
        if etc_pool and (i == 0 or i % 2 == 1):   # 기타 — 첫날은 추석 휴무 안내 / miscellaneous; the first day carries the Chuseok notice
            m = etc_pool.pop(0) if i == 0 else etc_pool.pop(rng.randrange(len(etc_pool)))
            add(day, {"kind": "etc", "mail": m, "cust": rng.choice(customers)})
    # 주문 뒤 출하 문의 · 납품 뒤 인보이스 요청 / shipping inquiries after orders, invoice requests after delivery
    for j, (od, deal) in enumerate(orders):
        if j % 5 != 4:
            add(next_bday(od, rng.randrange(1, 5)), {"kind": "ship", "deal": deal, "err": "erp" if j == 3 else ""})
        if j % 6 != 5:
            di = deal["dd"] + timedelta(days=rng.randrange(0, 3))
            while di.weekday() >= 5 or di in HOLIDAYS:
                di += timedelta(days=1)
            add(di, {"kind": "invoice", "deal": deal, "err": "mail" if j == 1 else ""})
    events.sort(key=lambda x: x["day"])
    return events


def clock_for(rng: random.Random, slot: int) -> int:
    """하루 안의 수신 시각(분) — 오전·오후 묶음 / a received time within the day, morning or afternoon cluster"""
    base = 9 * 60 + rng.randrange(0, 170) if slot % 2 == 0 else 13 * 60 + 30 + rng.randrange(0, 230)
    return base


def run(sim: Sim, rng: random.Random, events: list[dict]) -> None:
    by_day: dict[date, list[dict]] = {}
    for ev in events:
        by_day.setdefault(ev["day"], []).append(ev)
    for day in sorted(by_day):
        evs = by_day[day]
        times = sorted(clock_for(rng, i) for i in range(len(evs)))
        for ev, t in zip(evs, times):
            st = sim.open(day, t)
            try:
                handle(sim, rng, st, day, ev, t)
            finally:
                sim.close(st)


def handle(sim: Sim, rng: random.Random, st: _State, day: date, ev: dict, t: int) -> None:  # noqa: C901 — 사건 종류별 분기 / one branch per event kind
    hhmm = mcmail._hhmm(t)  # noqa: SLF001
    kind = ev["kind"]
    if kind == "etc":
        m = ev["mail"]
        cust = m.get("customer") or ev["cust"]
        ct = mcmail.CONTACTS.get(cust) or {}
        e = sim.inbound(st, day, hhmm, {"customer": cust, "sender": m.get("sender") or ct.get("m", ""), "senderName": m.get("senderName") or ct.get("n", ""),
                                        "subject": m["subject"], "body": m["body"], "classification": "etc", "intent": m["intent"], "confidence": rng.choice((93, 95, 96, 97, 98)),
                                        "summary": m["summary"], "ai": m["ai"], "reason": "", "workStatus": "기타 분류", "needs": [], "entities": {},
                                        "assignee": REP.get(cust, "정하늘"), "hadIssues": False})
        st.clock += rng.randrange(10, 180)
        mcmail._close_mail(st, e, m["close"] if m["close"] != "처리완료" else None)  # noqa: SLF001
        return
    deal = ev.get("deal") or {}
    cust = deal.get("cust") or ev["cust"]
    cc = next(k for k, v in mcmail.ERP_CUSTOMERS.items() if v == cust)
    ct = mcmail.CONTACTS[cust]
    rep = REP[cust]
    if kind == "quote":
        item, icode, qty, dd = deal["item"], deal["icode"], deal["qty"], deal["dd"]
        triage = ev["triage"]
        ents = sim.ents(cust, cc, item, icode, "" if triage else qty, dd.isoformat(), ct["addr"])
        e = sim.inbound(st, day, hhmm, {"customer": cust, "subject": q_subject(rng, item, qty), "body": q_body(rng, item, qty, dd, ct["n"]),
                                        "classification": "quote", "intent": "신규요청", "confidence": 71 if triage else rng.choice((94, 95, 96, 96, 97, 97, 98, 98, 99, 99)),
                                        "summary": f"{item} / {loc(qty)}EA / {rng.choice(['단가 및 납기 문의', '견적 요청'])}",
                                        "ai": rng.choice([f"{cust}{ga(cust)} {item} {loc(qty)}EA 견적을 요청했습니다.", f"{cust}{ga(cust)} {item} {loc(qty)}EA의 단가와 {kdate(dd)} 납품 가능 여부를 문의했습니다."]),
                                        "reason": "", "workStatus": "견적작성 필요", "needs": ["erp", "reply"], "entities": ents, "assignee": rep, "hadIssues": triage})
        c = mcmail._new_case_for(st, e)  # noqa: SLF001
        sim.seq["case"] = st.seq["case"]
        assert sim.seq["case"] <= LIMITS["case"], "case numbers would reach the existing range"
        sim.stats["cases"] += 1
        c["status"] = "견적작성 필요"
        c["request"] = f"{loc(qty)}EA 기준 단가 및 {dd.month}/{dd.day} 납기 가능 여부 확인"
        c["entity"]["quantity"] = qty
        e["entities"]["quoteRef"] = _F(c["caseId"], .96, "case")
        deal["case"] = c["caseId"]
        if triage:   # 수량이 비어 담당자가 확인한 흔적 / the quantity was missing and a person confirmed it
            e["summary"] = f"{item} / 수량 미기재 / 단가 문의"
            e["ai"] = f"{cust}{ga(cust)} {item} 단가를 문의했습니다. 수량이 적혀 있지 않아 확인이 필요합니다."
            e["reason"] = "견적요청으로 분류했지만 필수값인 수량이 메일에 없습니다."
            st.clock += rng.randrange(15, 90)
            e["entities"]["quantity"] = _F(str(qty), 1, "user")
            e["userConfirmed"] = True
            mcmail._after_triage(st, e)  # noqa: SLF001
            sim.stats["triage"] += 1
        if ev["err"] == "erp":
            st.clock += rng.randrange(5, 30)
            sim.fail_then(st, e, "erp")
        sim.finish_reply(st, e, rng.randrange(5, 120))
        return
    if kind == "review":
        c = st.case(deal.get("case"))
        if not c or c.get("status") != "견적 회신 완료":
            return
        e = sim.inbound(st, day, hhmm, {"customer": cust, "caseId": c["caseId"], "subject": "Re: " + q_subject(rng, deal["item"], deal["qty"]),
                                        "body": rng.choice(["고맙습니다.\n내부 검토 후 회신드리겠습니다.", "견적 잘 받았습니다. 검토 후 주문 여부 알려드리겠습니다.", "확인했습니다. 상사 보고 후 회신드릴게요."]),
                                        "classification": "quote", "intent": "확인", "confidence": rng.randrange(90, 97), "summary": '"내부 검토 후 회신드리겠습니다."',
                                        "ai": f"{cust}{ga(cust)} 견적을 받았고 내부 검토 후 회신하겠다고 알려왔습니다. 추가로 할 일은 없습니다.",
                                        "reason": "", "workStatus": "고객 검토 중", "needs": [], "caseStatus": "고객 검토 중", "hadIssues": False, "assignee": rep})
        e.pop("caseStatus", None)
        mcmail._apply_inbound(st, {**e, "caseStatus": "고객 검토 중"})  # noqa: SLF001
        st.clock += rng.randrange(5, 60)
        mcmail._close_mail(st, e, None)  # noqa: SLF001
        return
    if kind == "delta":
        c = st.case(deal.get("case"))
        if not c:
            return
        qty = ev["qty"]
        e = sim.inbound(st, day, hhmm, {"customer": cust, "caseId": c["caseId"], "subject": "Re: " + q_subject(rng, deal["item"], deal["qty"]) + " · 수량 변경",
                                        "body": f"안녕하세요.\n\n지난번 견적 관련하여, 수량을 {loc(qty)}개로 변경하면 단가가 얼마일까요?\n납기는 기존과 동일하게 부탁드립니다.",
                                        "classification": "quote", "intent": "변경요청", "confidence": rng.randrange(90, 97),
                                        "summary": f"수량 {loc(deal['qty'])}EA → {loc(qty)}EA",
                                        "ai": f"{cust}{ga(cust)} 기존 견적의 수량을 {loc(deal['qty'])}EA에서 {loc(qty)}EA로 바꾸면 단가가 얼마인지 문의했습니다.",
                                        "reason": "", "workStatus": "수정견적 필요", "needs": ["erp", "reply"], "hadIssues": False, "assignee": rep,
                                        "ent": {"quantity": _F(str(qty), .97)}})
        mcmail._link(st, e, c["caseId"])  # noqa: SLF001
        deal["qty"] = qty
        sim.finish_reply(st, e, rng.randrange(5, 90))
        return
    if kind in ("order", "direct"):
        qty, dd, item, icode = ev["qty"], deal["dd"], deal["item"], deal["icode"]
        c = st.case(deal.get("case")) if kind == "order" else None
        if kind == "order" and (not c or c.get("salesOrderNumber")):
            return
        if dd < day + timedelta(days=3):   # 주문 시점에 납기가 지났거나 너무 가까우면 새 납기 / a passed or too-close date gets a new one at order time
            dd = day + timedelta(days=rng.randrange(6, 13))
            deal["dd"] = dd
        base = {"customer": cust, "subject": rng.choice([f"{item} {loc(qty)}EA 주문", f"주문 요청", f"{item} {loc(qty)}개 발주 드립니다", f"Re: {q_subject(rng, item, qty)}" if c else f"{item} 발주서 송부"]),
                "body": o_body(rng, item, qty, dd, ct["n"], c is not None), "classification": "order", "intent": "주문전환",
                "confidence": rng.choice((94, 95, 96, 96, 97, 97, 98, 98, 99, 99)), "summary": f"{item} / {loc(qty)}EA / {kdate(dd)} 납기 주문 확정",
                "ai": (f"{cust}{ga(cust)} 견적 받은 {item} {loc(qty)}EA를 {kdate(dd)} 납기로 주문 확정했습니다." if c else f"{cust}{ga(cust)} {item} {loc(qty)}EA를 주문했습니다."),
                "reason": "", "workStatus": "ERP 전송대기", "needs": ["order"], "hadIssues": False, "assignee": rep,
                "attachments": [{"name": f"발주서_{cust.split()[0]}_{item.replace(' ', '')}.pdf", "size": f"{rng.randrange(150, 260)}KB", "type": "po"}]}
        if c:
            e = sim.inbound(st, day, hhmm, {**base, "caseId": c["caseId"], "ent": {"quantity": _F(str(qty), .97), "deliveryDate": _F(dd.isoformat(), .95)}})
            mcmail._apply_inbound(st, e)  # noqa: SLF001
        else:
            e = sim.inbound(st, day, hhmm, {**base, "entities": sim.ents(cust, cc, item, icode, qty, dd.isoformat(), ct["addr"])})
            c = mcmail._new_case_for(st, e)  # noqa: SLF001
            sim.seq["case"] = st.seq["case"]
            assert sim.seq["case"] <= LIMITS["case"]
            sim.stats["cases"] += 1
            c["status"] = "ERP 전송대기"
            deal["case"] = c["caseId"]
        if ev["err"] == "order":
            st.clock += rng.randrange(5, 30)
            sim.fail_then(st, e, "order")
        so = sim.place_order(st, e, rng.randrange(5, 90), ev["confirm"])
        deal["so"] = so
        return
    if kind == "ship":
        c = st.case(deal.get("case"))
        so = deal.get("so")
        if not c or not so or so not in st.shipments:
            return
        sim.set_ship_state(st, so, day)
        e = sim.inbound(st, day, hhmm, {"customer": cust, "caseId": c["caseId"], "subject": rng.choice([f"{deal['item']} 출하 일정 문의", "출하문의", f"{so} 출하 일정 확인 요청"]),
                                        "body": s_body(rng, deal["item"], deal["qty"], so, ct["n"]), "classification": "ship", "intent": "일정문의",
                                        "confidence": rng.choice((94, 95, 96, 97, 97, 98, 98)), "summary": f"{deal['item']} / {loc(deal['qty'])}EA 출하 일정 문의",
                                        "ai": rng.choice([f"{cust}{ga(cust)} 지난 주문({deal['item']} {loc(deal['qty'])}EA)의 출하 일정을 문의했습니다.", f"{cust}{ga(cust)} {so}의 도착 일정을 문의했습니다."]),
                                        "reason": "", "workStatus": "ERP 조회필요", "needs": ["erp", "reply"], "hadIssues": False, "assignee": rep})
        c["status"] = "출하 문의 접수"
        if ev["err"] == "erp":
            st.clock += rng.randrange(5, 20)
            sim.fail_then(st, e, "erp")
        sim.finish_reply(st, e, rng.randrange(5, 60))
        return
    if kind == "invoice":
        c = st.case(deal.get("case"))
        so = deal.get("so")
        if not c or not so or so not in st.shipments or day < deal["dd"]:   # 납품 전 인보이스 요청은 없다 / no invoice request before delivery
            return
        sim.set_ship_state(st, so, day)
        e = sim.inbound(st, day, hhmm, {"customer": cust, "caseId": c["caseId"], "subject": rng.choice([f"{so} 인보이스 요청", "인보이스 발행 부탁드립니다", f"{so} 세금계산서/인보이스 요청"]),
                                        "body": i_body(rng, so, ct["n"]), "classification": "invoice", "intent": "발행요청", "confidence": rng.choice((94, 95, 96, 97, 97, 98, 98)),
                                        "summary": f"{so} 인보이스 요청", "ai": f"{cust}{ga(cust)} {so}({deal['item']} {loc(deal['qty'])}EA)의 인보이스 발행을 요청했습니다.",
                                        "reason": "", "workStatus": "주문정보 조회필요", "needs": ["erp", "reply"], "hadIssues": False, "assignee": rep})
        if ev["err"] == "mail":
            st.clock += rng.randrange(5, 60)
            assert mcmail._apply_erp(st, e)  # noqa: SLF001
            mcmail._run_draft(st, e, False, "ko")  # noqa: SLF001
            st.clock += rng.randrange(5, 30)
            sim.fail_then(st, e, "mail")
            st.clock += rng.randrange(20, 120)
            mcmail._apply_send(st, e)  # noqa: SLF001
            sim.stats["outbound"] += 1
        else:
            sim.finish_reply(st, e, rng.randrange(5, 90))
        return
    if kind == "stock":
        item, icode, qty = ev["item"], ev["icode"], ev["qty"]
        e = sim.inbound(st, day, hhmm, {"customer": cust, "subject": rng.choice([f"{item} 재고 문의", f"{item} 즉시 출고 가능 수량 문의", f"{item} 재고 확인"]),
                                        "body": st_body(rng, item, qty, ct["n"]), "classification": "stock", "intent": "재고확인", "confidence": rng.choice((94, 95, 96, 97, 97, 98, 98)),
                                        "summary": f"{item} / {loc(qty)}EA 재고 문의", "ai": f"{cust}{ga(cust)} {item} {loc(qty)}EA 재고를 문의했습니다.",
                                        "reason": "", "workStatus": "재고 조회필요", "needs": ["erp", "reply"], "hadIssues": False, "assignee": rep,
                                        "entities": sim.ents(cust, cc, item, icode, qty, "", ct["addr"])})
        sim.new_inq_case(st, e, item, icode, qty, ct["addr"])
        if ev["err"] == "mail":
            st.clock += rng.randrange(5, 40)
            assert mcmail._apply_erp(st, e)  # noqa: SLF001
            mcmail._run_draft(st, e, False, "ko")  # noqa: SLF001
            st.clock += rng.randrange(5, 30)
            sim.fail_then(st, e, "mail")
            st.clock += rng.randrange(20, 90)
            mcmail._apply_send(st, e)  # noqa: SLF001
            sim.stats["outbound"] += 1
        else:
            sim.finish_reply(st, e, rng.randrange(5, 60))
        return


# ─────────────────────────────────────────────────────────────────────────────
# 시드에 합치기 / merging into the seed
# ─────────────────────────────────────────────────────────────────────────────

def collect(sim: Sim) -> dict:
    conn = sim.conn
    emails = [json.loads(r[0]) for r in conn.execute("SELECT data FROM mc_emails ORDER BY rowid")]
    cases = [json.loads(r[0]) for r in conn.execute("SELECT data FROM mc_cases ORDER BY rowid DESC")]
    errors = [json.loads(r[0]) for r in conn.execute("SELECT data FROM mc_errors ORDER BY rowid DESC")]
    ships = json.loads(conn.execute("SELECT value FROM mc_meta WHERE key='shipments'").fetchone()[0])
    new_e = [e for e in emails if e["emailId"] not in sim.existing_mails]
    new_c = [c for c in cases if c["caseId"] not in sim.existing_cases]
    new_x = [x for x in errors if int(x["id"].split("-")[1]) <= LIMITS["err"]]
    new_s = {k: v for k, v in ships.items() if k not in sim.existing_so}
    # 발신 메일 번호 네 자리 맞춤(E-702 → E-0702) / pad outbound ids to four digits
    for e in new_e:
        n = e["emailId"].split("-")[1]
        if len(n) < 4:
            e["emailId"] = f"E-{int(n):04d}"
    # 기준일 시점의 출하 상태 / shipment states as of the anchor
    st = sim.open(ANCHOR, 540)
    for so in new_s:
        sim.set_ship_state(st, so, ANCHOR)
        new_s[so] = st.shipments[so]
    conn.rollback()
    for x in new_x:
        assert x.get("status") != "open", f"history error left open: {x['id']}"
    for e in new_e:
        assert e.get("closed"), f"history mail left open: {e['emailId']}"
    tok = lambda o: mcmail._tokenize(o, ANCHOR)  # noqa: E731, SLF001
    return {"EMAILS": tok(new_e), "CASES": tok(new_c), "ERRORS": tok(new_x), "SHIPMENTS": tok(new_s)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="시드를 고치지 않고 통계만 / statistics only, the seed is left alone")
    args = ap.parse_args()
    rng = random.Random(SEED)
    random.seed(SEED)   # _apply_erp 의 erpMs / the erpMs jitter
    seed_text = SEED_PATH.read_text(encoding="utf-8")
    seed = json.loads(seed_text)
    existing_history = [e for e in seed["EMAILS"] if e["emailId"] < "E-0951"]
    if existing_history:
        # 이력이 이미 있으면 그 위에 다시 만들지 않는다: --check 는 들어 있는 이력의 통계만, 그 밖엔 멈춘다
        # With the history already in the seed nothing is generated on top of it: --check reports what is there, anything else stops.
        hist_in = [e for e in existing_history if e.get("direction") == "in"]
        hist_c = [c for c in seed["CASES"] if c["caseId"][-5:] < ("00108" if c["caseId"].startswith(("RFQ", "ORD")) else "00038")]
        hist_x = [x for x in seed["ERRORS"] if x.get("status") != "open"]
        hist_s = [k for k in seed["SHIPMENTS"] if k[-5:] < "00097"]
        print(f"seed already holds the history: inbound {len(hist_in)}, outbound {len(existing_history) - len(hist_in)}, cases {len(hist_c)}, "
              f"sales orders {len(hist_s)}, resolved errors {len(hist_x)}")
        from collections import Counter
        print("by type:", dict(Counter(e.get("classification") for e in hist_in)))
        if args.check:
            return
        print("시드를 2026-10-13 이전 판(이력 없음)으로 되돌린 뒤 다시 실행하세요. / restore the pre-history seed first")
        sys.exit(1)
    with ExitStack() as stack:
        isolate_db(stack)   # 격리 DB — 실 DB(data/ai365.db)는 건드리지 않는다 / an isolated DB; the real one is never touched
        sim = Sim(rng)
        events = plan(rng)
        run(sim, rng, events)
        out = collect(sim)
        sim.conn.close()
    hist_in = [e for e in out["EMAILS"] if e.get("direction") == "in"]
    print(f"history: inbound {len(hist_in)}, outbound {len(out['EMAILS']) - len(hist_in)}, cases {len(out['CASES'])}, "
          f"sales orders {len(out['SHIPMENTS'])}, resolved errors {len(out['ERRORS'])}, triage {sim.stats['triage']}, "
          f"days {business_days(HISTORY_START, HISTORY_END)[0]} .. {business_days(HISTORY_START, HISTORY_END)[-1]}")
    from collections import Counter
    print("by type:", dict(Counter(e.get("classification") for e in hist_in)))
    if args.check:
        return
    seed["EMAILS"] = out["EMAILS"] + seed["EMAILS"]
    seed["CASES"] = seed["CASES"] + out["CASES"]
    seed["ERRORS"] = seed["ERRORS"] + out["ERRORS"]
    seed["SHIPMENTS"] = {**out["SHIPMENTS"], **seed["SHIPMENTS"]}
    seed["_about"].append("이력(2026-09-23 ~ 기준일 7일 전)은 scripts/build_mcmail_history.py 가 서버 처리 함수를 돌려 만든 것이다(2026-10-13). "
                          "메일 E-0701~, Case 00061~, SO 00061~, INQ 00020~, 오류 ERR-0001~. / The history (2026-09-23 up to seven days before the anchor) "
                          "was generated by scripts/build_mcmail_history.py through the server's own processing functions (2026-10-13).")
    SEED_PATH.write_text(json.dumps(seed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {SEED_PATH}: mails {len(seed['EMAILS'])}, cases {len(seed['CASES'])}, errors {len(seed['ERRORS'])}, shipments {len(seed['SHIPMENTS'])}")


if __name__ == "__main__":
    main()
