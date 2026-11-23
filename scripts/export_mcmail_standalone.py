# -*- coding: utf-8 -*-
"""M코스메틱 이메일 에이전트 단독 HTML 내보내기: frontend/ai365-mcmail.html 을 서버 없이 열리는 한 파일로 만든다.

- 조회 스냅숏: 격리 DB(tests/db_fixture.isolate_db, 실 DB data/ai365.db 는 건드리지 않는다)에 app/mcmail.py 시드를 기준일(기본
  오늘)로 새로 넣고, FastAPI TestClient 로 화면이 부르는 /api/email 조회를 모두 받는다: 메타 · 대시보드 · 메뉴별 목록과 탭 ·
  모든 메일 상세 · Case 목록과 상세(이력) · 처리오류 · 알림. 같은 레코드는 id 로 한 번만 담고(mails · cases), 목록·상세는 id 로
  가리킨다. 담기 전에 파이썬에서 캡처 응답을 그대로 되살려 비교해 손실이 없는지 확인한다.
- 응답기: 페이지 스크립트보다 먼저 fetch 를 감싸 /api/email GET 을 스냅숏으로 답한다. 캡처하지 않은 조합(목록 검색어·기간,
  전체검색, 다른 기준일 대시보드)은 app/mcmail.py 의 list_emails · list_cases · list_errors · search · dashboard 와 같은 규칙으로
  스냅숏 전체에서 거른다. 쓰기(POST)는 모두 403 과 안내 문구로 막아 화면이 원래 실패 경로대로 스냅숏으로 다시 그리게 하고,
  그 토스트는 안내 토스트로 보인다. 안내 문구의 EN 사전 항목도 넣는다.
- 글꼴은 Pretendard CDN 링크만 남긴다(file:// 에서는 /static 로컬 대체본이 실패 요청만 만든다). 머리 주석은 보안 에이전트
  단독 파일(바탕화면 ai365-security-agent.html)과 같은 모양으로 단다. 디자인·로고·번역 층은 그대로다. 제목은 그대로 두되
  --title 을 주면 그 문자열로 바꾼다(탭 제목과 언어를 바꿀 때 다시 정하는 제목 모두, 2026-09-29).
실행:  .venv/Scripts/python.exe scripts/export_mcmail_standalone.py                      (바탕화면 ai365-email-agent.html)
       .venv/Scripts/python.exe scripts/export_mcmail_standalone.py --out 경로 --today 2026-09-29
       .venv/Scripts/python.exe scripts/export_mcmail_standalone.py --out 바탕화면/ai365-Mcosmetic.html --title ai365-Mcosmetic
화면 디자인을 바꾼 뒤 다시 실행하면 된다. 페이지의 고정 지점(머리 주석·글꼴 블록·사전·첫 스크립트)이 바뀌면 멈추고 알려 준다.

Standalone HTML export of the M Cosmetic Email Agent: turns frontend/ai365-mcmail.html into one file that opens without a
server. Snapshot: the app/mcmail.py seed is freshly loaded into an isolated DB (tests/db_fixture.isolate_db; the real
data/ai365.db is never touched) anchored to the given day (today by default), and every /api/email read the page makes is
captured through FastAPI's TestClient: meta, dashboard, every menu list and tab, every mail detail, case lists and
details (timelines), processing errors and notifications. Each record is stored once by id (mails, cases) and lists and
details point at ids; before embedding, the captured replies are rebuilt in Python and compared, so nothing is lost.
Responder: a fetch wrapper that runs before the page scripts answers /api/email GETs from the snapshot; uncaptured
variants (list keyword and period, global search, a dashboard on another day) are filtered over the whole snapshot with
the same rules as list_emails, list_cases, list_errors, search and dashboard in app/mcmail.py. Every write (POST) gets a
403 with a notice, so the page takes its own failure path and re-renders from the snapshot; that toast is shown as an
info toast, and EN dictionary entries for the notice are added. Fonts keep only the Pretendard CDN link (under file://
the /static local fallback only produces failed requests). The header comment follows the standalone security agent
file (Desktop ai365-security-agent.html); design, logo and the translation layer stay as they are. The title stays too
unless --title is given, which replaces both the tab title and the title set again on a language switch (2026-09-29). Re-run after
design changes; the script stops with a message when one of the page anchors (header comment, font block, dictionary,
first script) has moved.
"""
import argparse
import json
import re
import sys
from contextlib import ExitStack, contextmanager
from datetime import date
from html import escape as html_escape
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))   # 격리 DB 도우미 db_fixture / the isolated-DB helper
sys.stdout.reconfigure(encoding="utf-8")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from db_fixture import isolate_db  # noqa: E402
from app import mcmail, mcmail_api  # noqa: E402

PAGE = ROOT / "frontend" / "ai365-mcmail.html"
OUT = Path.home() / "Desktop" / "ai365-email-agent.html"
P = "/api/email"
MAIL_VIEWS = ("inbox", "quote", "order", "ship", "stock", "invoice", "etc")
CASE_FILTERS = ("all", "견적", "주문", "문의", "open", "done")
EM = "—"
# 막힌 처리의 안내 문구(토스트 제목·본문과 전체 문장) / the blocked-action notice (toast title, body and the whole sentence)
BLOCKED_T = "단독 파일에서는 처리 기능을 쓸 수 없습니다."
BLOCKED_M = "Ai365 이메일 에이전트 화면에서 진행해 주세요."
BLOCKED = f"{BLOCKED_T} {BLOCKED_M}"
BLOCKED_EN = (("Actions are not available in this standalone file.", "Please continue in the Ai365 email agent screen."))


def mail_filters(view: str) -> tuple:
    return ("todo", "all") if view == "inbox" else ("todo", "err", "done", "all")


@contextmanager
def serve(today: date):
    """격리 DB + 기준일 고정 + 실제 LLM 금지 상태의 TestClient / a TestClient on an isolated DB with a pinned day and no LLM"""
    with ExitStack() as stack:
        isolate_db(stack)
        stack.enter_context(patch.object(mcmail, "_server_today", return_value=today))
        stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected LLM")))
        mcmail.init_mcmail()
        app = FastAPI()
        app.include_router(mcmail_api.router)
        yield TestClient(app)


def _get(client: TestClient, path: str, params: dict | None = None) -> dict:
    r = client.get(P + path, params=params)
    if r.status_code != 200:
        raise SystemExit(f"GET {path} {params} -> {r.status_code} {r.text[:200]}")
    return r.json()


def capture(client: TestClient) -> tuple[dict, dict]:
    """화면이 부르는 조회를 모두 받아 (정규화한 스냅숏, 원래 응답) 을 돌려준다
    Capture every read the page makes; returns (the normalized snapshot, the raw replies)."""
    raw: dict[str, dict] = {}

    def rec(path, params=None):
        out = _get(client, path, params)
        raw[path + ("?" + "&".join(f"{k}={v}" for k, v in sorted(params.items())) if params else "")] = out
        return out

    with mcmail._session() as st:  # noqa: SLF001  행 순서(목록 정렬의 동률 순서와 검색) / row orders (sort ties and search)
        mail_order = [e["emailId"] for e in st.emails]
        case_order = [c["caseId"] for c in st.cases]
        today = st.today
    meta = rec("/meta")
    dash = rec("/dashboard", {"date": meta["today"]})
    mails: dict[str, dict] = {}
    cases: dict[str, dict] = {}

    def keep(store: dict, rid: str, obj: dict, what: str) -> str:
        """같은 id 는 한 번만 담고, 다시 나오면 같은지 확인 / store once per id; a repeat must be identical"""
        if rid in store and store[rid] != obj:
            raise SystemExit(f"{what} {rid} differs between replies")
        store[rid] = obj
        return rid

    snap = {"today": today, "mailOrder": mail_order, "caseOrder": case_order, "meta": meta,
            "dashboard": {**dash, "todo": [keep(mails, m["emailId"], m, "mail") for m in dash["todo"]]},
            "mailLists": {}, "details": {}, "caseLists": {}, "caseDetails": {}}
    for v in MAIL_VIEWS:
        for f in mail_filters(v):
            r = rec("/mails", {"view": v, "filter": f})
            if r["total"] != len(r["items"]) or r["view"] != v or r["filter"] != f:
                raise SystemExit(f"unexpected list reply for {v}/{f}")
            snap["mailLists"][f"{v}|{f}"] = {"ids": [keep(mails, m["emailId"], m, "mail") for m in r["items"]], "counts": r["counts"]}
    for eid in mail_order:
        r = rec(f"/mails/{eid}")
        keep(mails, eid, r["email"], "mail")
        cid = keep(cases, r["case"]["caseId"], r["case"], "case") if r["case"] else None
        snap["details"][eid] = {"case": cid, "thread": [keep(mails, m["emailId"], m, "mail") for m in r["thread"]],
                                "openErrors": r["openErrors"]}
    for f in CASE_FILTERS:
        r = rec("/cases", {"filter": f})
        snap["caseLists"][f] = {"ids": [keep(cases, c["caseId"], c, "case") for c in r["items"]]}
    for cid in case_order:
        r = rec(f"/cases/{cid}")
        keep(cases, cid, r["case"], "case")
        snap["caseDetails"][cid] = {"mails": [keep(mails, m["emailId"], m, "mail") for m in r["mails"]], "timeline": r["timeline"]}
    snap["errors"] = rec("/errors", {"status": "all"})["items"]
    snap["notifications"] = rec("/notifications")
    snap["mails"], snap["cases"] = mails, cases
    missing = [i for i in mail_order if i not in mails] + [i for i in case_order if i not in cases]
    if missing:
        raise SystemExit(f"records missing from the snapshot: {missing}")
    return snap, raw


def rebuild(snap: dict, key: str) -> dict:
    """캡처한 조회 하나를 스냅숏에서 되살린다(페이지 응답기와 같은 방식) / rebuild one captured read the way the page responder does"""
    M, C = snap["mails"].__getitem__, snap["cases"].__getitem__
    path, _, query = key.partition("?")
    q = dict(x.split("=", 1) for x in query.split("&")) if query else {}
    if path == "/meta":
        return snap["meta"]
    if path == "/dashboard":
        return {**snap["dashboard"], "todo": [M(i) for i in snap["dashboard"]["todo"]]}
    if path == "/mails":
        L = snap["mailLists"][f"{q['view']}|{q['filter']}"]
        return {"view": q["view"], "filter": q["filter"], "items": [M(i) for i in L["ids"]], "counts": L["counts"],
                "total": len(L["ids"])}
    if path == "/cases":
        ids = snap["caseLists"][q["filter"]]["ids"]
        return {"filter": q["filter"], "items": [C(i) for i in ids], "total": len(ids)}
    if path == "/errors":
        rows = snap["errors"]
        return {"status": "all", "items": rows, "counts": {"open": sum(x["status"] == "open" for x in rows),
                                                           "done": sum(x["status"] != "open" for x in rows), "all": len(rows)}}
    if path == "/notifications":
        return snap["notifications"]
    kind, _, rid = path[1:].partition("/")
    if kind == "mails":
        d = snap["details"][rid]
        return {"email": M(rid), "case": C(d["case"]) if d["case"] else None, "thread": [M(i) for i in d["thread"]],
                "openErrors": d["openErrors"]}
    d = snap["caseDetails"][rid]
    return {"case": C(rid), "mails": [M(i) for i in d["mails"]], "timeline": d["timeline"]}


# 페이지 응답기(내보낸 파일의 첫 스크립트) / the page responder (the first script of the exported file)
RESPONDER = r"""<script>
/* =====================================================================
   단독 파일 응답기(scripts/export_mcmail_standalone.py 가 넣음): 서버 대신 위 mcmail-snapshot 으로 /api/email 조회에 답한다.
   · 캡처한 조회(메타 · 대시보드 · 메뉴별 목록과 탭 · 메일 상세 · Case · 이력 · 처리오류 · 알림)는 그 응답을 그대로 돌려준다.
   · 캡처하지 않은 조합(목록 검색어·기간, 전체검색, 다른 기준일 대시보드)은 app/mcmail.py 의 list_emails · list_cases ·
     list_errors · search · dashboard 와 같은 규칙으로 스냅숏 전체에서 거른다.
   · 쓰기(POST)는 모두 막는다. 403 과 안내 문구를 받으면 화면은 원래 실패 경로대로 스냅숏으로 다시 그리고 토스트를 띄우므로
     아무것도 바뀌지 않는다. 그 토스트는 안내 토스트로 바꿔 보인다.
   Standalone responder (added by scripts/export_mcmail_standalone.py): answers /api/email reads from the mcmail-snapshot
   above instead of a server.
   · Captured reads (meta, dashboard, every menu list and tab, mail details, cases, timelines, errors, notifications)
     return the captured reply as is.
   · Uncaptured variants (list keyword and period, global search, a dashboard on another day) are filtered over the
     whole snapshot with the same rules as list_emails, list_cases, list_errors, search and dashboard in app/mcmail.py.
   · Every write (POST) is refused. On the 403 with the notice the page takes its own failure path, re-renders from the
     snapshot and shows a toast, so nothing changes; that toast is shown as an info toast.
   ===================================================================== */
(() => {
  'use strict';
  const SNAP = JSON.parse(document.getElementById('mcmail-snapshot').textContent);
  const BLOCKED = __BLOCKED__, BLOCKED_T = __BLOCKED_T__, BLOCKED_M = __BLOCKED_M__;
  const S = v => (v == null ? '' : String(v));                                          /* 서버 _s / the server's _s */
  const val = (en, k) => { const f = (en || {})[k]; return f && typeof f === 'object' ? f.value : null; };   /* 서버 _val / _val */
  /* 문자열 내림차순(안정 정렬, 서버의 sorted(reverse=True) 와 같다) / descending string order, stable like sorted(reverse=True) */
  const desc = k => (a, b) => { const x = S(a[k]), y = S(b[k]); return x < y ? 1 : x > y ? -1 : 0; };
  const inRange = (dt, lo, hi) => { const d = S(dt).slice(0, 10); return (!lo || d >= lo) && (!hi || d <= hi); };
  const M = id => SNAP.mails[id], C = id => SNAP.cases[id];
  const inbound = () => SNAP.mailOrder.map(M).filter(e => e.direction === 'in');
  /* 서버 _list_base: inbox(또는 없음)=수신 전체, 업무 메뉴=그 분류 중 확인 필요 밖 / the server's _list_base */
  const listBase = v => (!v || v === 'inbox' ? inbound() : inbound().filter(e => e.classification === v && !e.inTriage)).sort(desc('receivedDate'));
  /* 서버 _hay / the server's _hay */
  const hay = e => { const c = C(e.caseId) || {}, en = e.entities || {}, f = e.flow || {};
    return [e.customer, e.senderName, e.sender, e.subject, val(en, 'itemName'), val(en, 'itemCode'), (c.entity || {}).itemName,
      val(en, 'salesOrder'), c.salesOrderNumber, (f.orderResult || {}).so, e.caseId, e.emailId].map(S).join(' ').toLowerCase(); };
  const caseHay = (c, withUser) => [c.caseId, c.customer, c.title, (c.entity || {}).itemName, c.salesOrderNumber]
    .concat(withUser ? [c.assignedUser] : []).map(S).join(' ').toLowerCase();
  const kw = p => (p.get('q') || '').trim().toLowerCase();
  const period = p => [p.get('from') || null, p.get('to') || null];

  /* 서버 list_emails / the server's list_emails */
  function mails(p) {
    const view = p.get('view') || null, filter = p.get('filter') || 'todo', q = kw(p), [lo, hi] = period(p);
    const L = !q && !lo && !hi && SNAP.mailLists[view + '|' + filter];
    if (L) return { view, filter, items: L.ids.map(M), counts: L.counts, total: L.ids.length };
    const base = listBase(view).filter(e => inRange(e.receivedDate, lo, hi));
    const match = e => filter === 'all' || (view === 'inbox' ? !!e.inTriage
      : filter === 'todo' ? e.status !== '완료' : filter === 'err' ? e.status === '오류' : e.status === '완료');
    const items = base.filter(e => match(e) && (!q || hay(e).includes(q)));
    const counts = view === 'inbox' ? { todo: base.filter(e => e.inTriage).length, all: base.length }
      : { todo: base.filter(e => !e.closed).length, err: base.filter(e => e.status === '오류').length, done: base.filter(e => e.closed).length, all: base.length };
    return { view, filter, items, counts, total: items.length };
  }
  /* 서버 list_cases / the server's list_cases */
  function cases(p) {
    const filter = p.get('filter') || 'all', q = kw(p), [lo, hi] = period(p);
    const L = !q && !lo && !hi && SNAP.caseLists[filter];
    if (L) return { filter, items: L.ids.map(C), total: L.ids.length };
    const match = c => filter === 'all' || (filter === 'open' ? !c.done : filter === 'done' ? !!c.done : S(c.caseType).includes(filter));
    const items = SNAP.caseOrder.map(C).filter(c => inRange(c.lastUpdatedDate, lo, hi) && match(c) && (!q || caseHay(c, true).includes(q)))
      .sort(desc('lastUpdatedDate'));
    return { filter, items, total: items.length };
  }
  /* 서버 list_errors / the server's list_errors */
  function errors(p) {
    const status = p.get('status') || 'open', [lo, hi] = period(p), rows = SNAP.errors.filter(x => inRange(x.time, lo, hi));
    return { status, items: rows.filter(x => status === 'all' || ((x.status === 'open') === (status === 'open'))),
      counts: { open: rows.filter(x => x.status === 'open').length, done: rows.filter(x => x.status !== 'open').length, all: rows.length } };
  }
  /* 서버 search: Case 5건 + 메일 6건 / the server's search: up to 5 cases and 6 mails */
  function search(p) {
    const q = p.get('q') || '', ql = q.trim().toLowerCase();
    if (!ql) return { q: '', cases: [], mails: [] };
    return { q, cases: SNAP.caseOrder.map(C).filter(c => caseHay(c, false).includes(ql)).slice(0, 5),
      mails: listBase(null).filter(e => hay(e).includes(ql)).slice(0, 6) };
  }
  /* 서버 dashboard: 기준일에 따라 바뀌는 것은 그날 수신 KPI(recv · auto · erp)뿐 / only the day's KPIs depend on the date */
  function dashboard(p) {
    const D = SNAP.dashboard, today = SNAP.today;
    let d = p.get('date') || today; if (d > today) d = today;
    const out = Object.assign({}, D, { todo: D.todo.map(M) });
    if (d === D.date) return out;
    const td = inbound().filter(e => S(e.receivedDate).startsWith(d)), fl = e => e.flow || {};
    return Object.assign(out, { date: d, isToday: d === today, kpi: Object.assign({}, D.kpi, { recv: td.length,
      auto: td.filter(e => e.classification && !e.inTriage).length, erp: td.filter(e => fl(e).erp === 'done' || fl(e).order === 'done').length }) });
  }
  function answer(path, p) {
    if (path === '/meta') return SNAP.meta;
    if (path === '/dashboard') return dashboard(p);
    if (path === '/mails') return mails(p);
    if (path === '/cases') return cases(p);
    if (path === '/errors') return errors(p);
    if (path === '/notifications') return SNAP.notifications;
    if (path === '/search') return search(p);
    let m = /^\/mails\/([^/]+)$/.exec(path);
    if (m) { const id = decodeURIComponent(m[1]), d = SNAP.details[id];
      return d ? { email: M(id), case: d.case ? C(d.case) : null, thread: d.thread.map(M), openErrors: d.openErrors } : [404, '메일을 찾을 수 없습니다.']; }
    m = /^\/cases\/([^/]+)$/.exec(path);
    if (m) { const id = decodeURIComponent(m[1]), d = SNAP.caseDetails[id];
      return d ? { case: C(id), mails: d.mails.map(M), timeline: d.timeline } : [404, 'Case를 찾을 수 없습니다.']; }
    return [404, '알 수 없는 조회 대상입니다.'];
  }
  const reply = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  const net = window.fetch ? window.fetch.bind(window) : null;
  window.fetch = async (input, init) => {
    const raw = typeof input === 'string' ? input : (input && input.url) || '';
    const at = raw.indexOf('/api/email/');
    if (at < 0) return net ? net(input, init) : Promise.reject(new TypeError('offline'));
    if (String((init && init.method) || 'GET').toUpperCase() !== 'GET') return reply(403, { detail: BLOCKED });
    const u = new URL(raw.slice(at), 'http://mcmail.local'), out = answer(u.pathname.slice('/api/email'.length), u.searchParams);
    return Array.isArray(out) ? reply(out[0], { detail: out[1] }) : reply(200, out);
  };
  /* 막힌 처리의 실패 토스트는 안내 토스트로 보인다. 번역 층이 toast 를 감싼 뒤(페이지 스크립트 끝)에 감싼다
     the blocked-action error toast is shown as an info toast; wrapped after the translation layer wraps toast (end of the page script) */
  document.addEventListener('DOMContentLoaded', () => {
    const show = window.toast;
    if (typeof show !== 'function') return;
    window.toast = function (type, title, msg) { return msg === BLOCKED ? show.call(this, 'info', BLOCKED_T, BLOCKED_M) : show.apply(this, arguments); };
  });
  window.MCMAIL_STANDALONE = { today: SNAP.today, answer, blocked: BLOCKED };
})();
</script>
"""


def header_comment(exported: str, today: str) -> str:
    return (
        f"<!-- Ai365 3.0 M코스메틱 이메일 에이전트 화면 단독 파일({exported} 내보냄, 기준일 {today}). frontend/ai365-mcmail.html 화면을\n"
        "     그대로 옮겼고, 서버(/api/email) 없이 아래 mcmail-snapshot 시드로 그린다. 시드는 app/mcmail.py 의 초기 시드\n"
        "     (app/mcmail_seed.json)를 기준일로 새로 넣어 화면이 부르는 조회(메타 · 대시보드 · 메뉴별 목록과 탭 · 모든 메일 상세 ·\n"
        "     Case 와 이력 · 처리오류 · 알림)를 모두 담은 스냅숏이고, 목록 검색어 · 기간 · 전체검색 · 다른 기준일은 같은 규칙으로\n"
        "     파일 안에서 거른다. 처리 기능(분류 · 값 수정 · ERP 조회 · 주문등록 · 초안 · 임시저장 · 발송 · 보류 · 완료 · 보관 ·\n"
        "     스팸 · 재처리 · 시나리오 메일 수신 · 초기화)은 막혀 있어 아무것도 바뀌지 않는다(안내 토스트만 보인다). 외부 스크립트는\n"
        "     없고 글꼴 Pretendard 만 CDN 으로 받는다(없으면 시스템 글꼴). 기본은 한국어이고 localStorage 'ai365_lang' 이 'en' 이면\n"
        "     영어다. 다른 앱에 올려 보여 주기용. 다시 만들기: scripts/export_mcmail_standalone.py\n"
        f"     Standalone Ai365 3.0 M Cosmetic Email Agent screen (exported {exported}, anchored to {today}): frontend/ai365-mcmail.html\n"
        "     as is, rendered without a server (/api/email) from the mcmail-snapshot seed below. The snapshot is the app/mcmail.py\n"
        "     seed (app/mcmail_seed.json) freshly loaded for the anchor day, holding every read the page makes (meta, dashboard,\n"
        "     every menu list and tab, every mail detail, cases and timelines, processing errors, notifications); list keywords,\n"
        "     periods, global search and other dashboard days are filtered inside the file with the same rules. Actions\n"
        "     (classify, edit values, ERP lookup, order entry, draft, save, send, hold, complete, archive, spam, retry,\n"
        "     reset) are disabled and change nothing (only a notice toast appears). No external script; only the\n"
        "     Pretendard font comes from the CDN (system fonts otherwise). Korean by default, English when localStorage\n"
        "     'ai365_lang' is 'en'. Meant for display inside another app. Rebuild with scripts/export_mcmail_standalone.py -->\n")


def _once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"page anchor not found exactly once (the page changed?): {old[:90]!r}")
    return text.replace(old, new)


def build_page(page: str, snap: dict, exported: str, title: str = "") -> str:
    """페이지 → 단독 파일(머리 주석 · 글꼴 · 사전 · 스냅숏 · 응답기) / page → standalone file
    title: 비우면 페이지 제목 그대로, 주면 탭 제목과 언어 전환(setLang)의 제목을 모두 그 문자열로 / empty keeps the page title;
    otherwise both the tab title and the one setLang sets become this string"""
    today = snap["today"]
    # 1) 서버 상태 화면 설명(맨 앞 주석)을 빼고, 제목 뒤에 단독 파일 머리 주석 / drop the server-page comment, add the standalone header
    m = re.match(r"<!DOCTYPE html>\n<!--.*?-->\n", page, re.S)
    if not m:
        raise SystemExit("page anchor not found: the leading comment")
    h = "<!DOCTYPE html>\n" + page[m.end():]
    head_title = html_escape(title) if title else "M코스메틱 Email Agent"
    h = _once(h, "<title>M코스메틱 Email Agent</title>\n", f"<title>{head_title}</title>\n" + header_comment(exported, today))
    if title:
        # 언어를 바꿀 때도 같은 제목(한·영 공통) / the same title after a language switch (KO and EN alike)
        h = _once(h, "document.title = cur === 'en' ? 'M Cosmetic Email Agent' : 'M코스메틱 Email Agent';",
                  "document.title = " + json.dumps(title, ensure_ascii=False).replace("<", "\\u003c") + ";")
    # 2) 글꼴: CDN 링크만(로컬 대체본 @font-face 와 스택 이름 제거) / fonts: the CDN link only (no local @font-face, no stack name)
    a = h.index("/* ---------- 글꼴: Pretendard(위 CDN 동적 서브셋) + 저장소 로컬 대체본")
    b = h.index('src:url(/static/fonts/pretendard/Pretendard-Bold.woff2) format("woff2")}\n', a)
    b += len('src:url(/static/fonts/pretendard/Pretendard-Bold.woff2) format("woff2")}\n')
    h = (h[:a] + "/* ---------- 글꼴: Pretendard(위 CDN 동적 서브셋, 받지 못하면 시스템 글꼴). 숫자·시각·ID 는 고정폭 숫자\n"
         "   Typeface: Pretendard (the CDN dynamic subset above, else system fonts); counts, times and IDs use tabular figures ---------- */\n"
         + h[b:])
    h = _once(h, '--sans:"Pretendard","Pretendard Local",', '--sans:"Pretendard",')
    # 3) 안내 문구 EN 사전 / EN dictionary entries for the notice
    h = _once(h, "    /* 서버 검증 메시지(422·404·409): 토스트 본문으로 보인다",
              "    /* 단독 파일 안내(내보내기 스크립트가 넣음) / standalone notice (added by the exporter) */\n"
              f"    [{json.dumps(BLOCKED, ensure_ascii=False)}, {json.dumps(' '.join(BLOCKED_EN))}],\n"
              f"    [{json.dumps(BLOCKED_T, ensure_ascii=False)}, {json.dumps(BLOCKED_EN[0])}], "
              f"[{json.dumps(BLOCKED_M, ensure_ascii=False)}, {json.dumps(BLOCKED_EN[1])}],\n"
              "    /* 서버 검증 메시지(422·404·409): 토스트 본문으로 보인다")
    # 4) 스냅숏 + 응답기를 페이지 스크립트 앞에 / the snapshot and the responder before the page scripts
    data = json.dumps(snap, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    responder = (RESPONDER.replace("__BLOCKED__", json.dumps(BLOCKED, ensure_ascii=False))
                 .replace("__BLOCKED_T__", json.dumps(BLOCKED_T, ensure_ascii=False))
                 .replace("__BLOCKED_M__", json.dumps(BLOCKED_M, ensure_ascii=False)))
    h = _once(h, '<script>const LOGO_FULL="', f'<script type="application/json" id="mcmail-snapshot">{data}</script>\n'
              + responder + '<script>const LOGO_FULL="')
    # 남으면 안 되는 것: em dash, 앱 서버의 /static 참조(CDN 주소의 .../web/static/... 은 제외), 외부 스크립트
    # must not remain: an em dash, a root-relative /static reference (the CDN's .../web/static/... is fine), an external script
    for rx, why in ((EM, "an em dash"), (r"""[("'=]\s*/static/""", "a /static reference"), (r"<script[^>]*\bsrc=", "an external script")):
        if re.search(rx, h):
            raise SystemExit(f"the export still holds {why}")
    return h


def main() -> None:
    ap = argparse.ArgumentParser(description="M코스메틱 이메일 에이전트 단독 HTML 내보내기 / export the standalone email agent HTML")
    ap.add_argument("--out", type=Path, default=OUT, help="출력 경로(기본 바탕화면) / output path (Desktop by default)")
    ap.add_argument("--today", default="", help="기준일 YYYY-MM-DD(기본 오늘) / anchor day (today by default)")
    ap.add_argument("--title", default="", help="탭 제목(기본 페이지 제목 그대로) / tab title (the page title by default)")
    args = ap.parse_args()
    day = date.fromisoformat(args.today) if args.today else date.today()
    with serve(day) as client:
        snap, raw = capture(client)
    bad = [k for k, v in raw.items() if rebuild(snap, k) != v]
    if bad:
        raise SystemExit(f"snapshot does not rebuild these replies: {bad[:5]}")
    html = build_page(PAGE.read_text(encoding="utf-8"), snap, date.today().isoformat(), args.title.strip())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        f.write(html)
    size = args.out.stat().st_size
    print(f"wrote {args.out} ({size:,} bytes, {size / 1024:.0f} KB): anchor {snap['today']}, {len(raw)} reads captured and "
          f"rebuilt, {len(snap['mails'])} mails, {len(snap['cases'])} cases, {len(snap['errors'])} errors")


if __name__ == "__main__":
    main()
