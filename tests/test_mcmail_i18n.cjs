// M코스메틱 Email Agent 단일 파일(frontend/ai365-mcmail.html) — 서버 상태 화면의 한/영 전환(사전·규칙·EN 잔여·KO 무변화·부모 토글 왕복),
// 서버가 만든 답변 초안의 언어, 완료 메일의 하단 실행 바(CTA) 규칙, #view= 첫 화면, 데모 초기화, 부팅 실패 화면.
// 서버(/api/email)는 픽스처 스텁으로 대신한다: tests/fixtures/mcmail_api.json(FastAPI TestClient 로 캡처, 오늘 2026-10-05 고정 =
// 시드 기준일 + 15일이라 서버가 옮긴 날짜·SO 번호에서도 번역이 맞는지 드러난다)을 Playwright route 로 돌려준다. GET 은 현재 상태의 응답을, POST 는 흐름(flow)의 다음 단계와 본문까지 맞춰 본 뒤 그 단계의 응답을
// 주고 다음 상태로 넘어간다. 픽스처에 없는 요청은 miss 로 모아 테스트를 실패시킨다(화면의 요청이 바뀌면 캡처 스크립트로 다시 만든다).
// 페이지는 가짜 출처(http://mcmail.test)에서 연다(localStorage 가 필요해서 setContent 대신 route 사용).
// Server-state M Cosmetic Email Agent page: KO/EN switching (dictionary, rules, EN residue, unchanged KO, parent toggle), the
// language of server-written drafts, the CTA rules for completed mails, the #view= first screen, the demo reset and the boot
// failure screen. The server is a fixture stub: tests/fixtures/mcmail_api.json (captured with FastAPI's TestClient, today
// pinned to 2026-10-05 = seed base + 15 days, so translation is checked on server-shifted dates and SO numbers) is served
// through a Playwright route. A GET gets the reply for the current state; a POST must match
// the flow's next step, body included, then returns that step's reply and moves to the next state. Requests missing from
// the fixture are collected as misses and fail the test (recapture the fixture when the page's requests change).
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { isDeepStrictEqual } = require('node:util');
const { chromium } = require('playwright');
const html = fs.readFileSync(path.join(__dirname, '../frontend/ai365-mcmail.html'), 'utf8');
const FX = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/mcmail_api.json'), 'utf8'));
const ORIGIN = 'http://mcmail.test';
const PARENT = '<!doctype html><meta charset="utf-8"><body style="margin:0"><iframe id="f" src="/app.html" style="width:1440px;height:900px;border:0"></iframe></body>';

/* 픽스처 풀기 — {"$ref": n} → objs[n] (Node 쪽에서 직렬화만 하므로 공유해도 된다)
   unpack the fixture; {"$ref": n} → objs[n] (shared objects are fine, Node only serializes them) */
const HYD = new Map();
function hydrate(v) {
  if (Array.isArray(v)) return v.map(hydrate);
  if (v && typeof v === 'object') {
    const ks = Object.keys(v);
    if (ks.length === 1 && ks[0] === '$ref') { if (!HYD.has(v.$ref)) HYD.set(v.$ref, hydrate(FX.objs[v.$ref])); return HYD.get(v.$ref); }
    const o = {}; for (const k of ks) o[k] = hydrate(v[k]); return o;
  }
  return v;
}
const GET_IDX = new Map(FX.gets.map((k, i) => [k, i]));
/* 캡처 스크립트와 같은 정규 키 — 빈 값 제외, 이름순, 디코딩한 값 / the capture script's canonical key */
function keyOf(method, u) {
  const p = [...u.searchParams.entries()].filter(([, v]) => v !== '').sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  return method + ' ' + decodeURIComponent(u.pathname) + (p.length ? '?' + p.map(([k, v]) => k + '=' + v).join('&') : '');
}
/* 서버 스텁 — 상태 기계 / server stub state machine */
function makeStub(flow) {
  const steps = flow ? FX.flows[flow] : [];
  assert.ok(steps, 'unknown flow ' + flow);
  const st = { state: 'seed', step: 0, misses: [], posts: [] };
  st.handle = route => {
    const req = route.request(), u = new URL(req.url()), method = req.method();
    const json = (status, body) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (method === 'GET') {
      const k = keyOf('GET', u), i = GET_IDX.get(k), v = i == null ? null : FX.states[st.state][i];
      if (v == null) { st.misses.push(k + ' @' + st.state); return json(404, { detail: 'fixture miss' }); }
      return json(200, hydrate(v));
    }
    const s = steps[st.step], raw = req.postData(), body = raw ? JSON.parse(raw) : null, k = method + ' ' + decodeURIComponent(u.pathname);
    st.posts.push(k.replace('POST /api/email', ''));
    if (!s || s.req !== k || !isDeepStrictEqual(body, s.body)) {
      st.misses.push(`${k} ${JSON.stringify(body)} @${st.state} (expected ${s ? s.req + ' ' + JSON.stringify(s.body) : 'no more steps'})`);
      return json(404, { detail: 'fixture miss' });
    }
    st.step++; st.state = s.state;
    return json(s.status, hydrate(s.res));
  };
  return st;
}

/* 한글 잔여 스캔의 예외 목록 / exception list for the Korean residue scan
   · SKIP: 통째로 데이터인 영역(메일 본문·서명·인용·제목·아바타 이니셜·고객 발주서) / areas that are data as a whole
     (mail body, signature, quotes, subjects, avatar initials, the customer's purchase order)
   · PART: '고객사 · 제목' 은 고객사 쪽만 검사 / for 'customer · subject' only the customer side is checked
   · ALLOWED: 데이터 이름 — 고객사·담당자·주소·품목(용량 뺀 제품명 포함)·발신자명·첨부 파일명 + 고정 조각(서버 META·캐시에서 모은다)
     data names — customers, contacts, addresses, items (incl. product names without size), sender names, attachment names
     + fixed fragments (collected from the server META and the page cache) */
const SCAN = `
window.__SKIP = ['script', 'style', 'textarea', '.avatar', '.mbody', '.msig', 'blockquote', '.row[data-act="sel"] .r2', '.dh h2',
  '.mh-m dd:last-child', '.th-2', '#gpop .pop-item[data-act="go-mail"] .t', '#notifPop .s', '.m-kv b', '#modalRoot .invdoc'].join(',');
window.__PART = '.todo .tx b';
window.__ALLOWED = () => {
  const s = new Set(['누리', '누리 구매팀', '인천 신규 창고', '글로우 라인', '글로우 50g']);
  Object.values(META.erpCustomers).forEach(v => s.add(v));
  Object.values(META.contacts).forEach(c => { s.add(c.n); if (c.addr) s.add(c.addr); });
  META.users.forEach(u => s.add(u.name));
  Object.values(META.erpItems).forEach(i => { s.add(i.name); s.add(i.short); s.add(i.short.replace(/ \\d+g$/, '')); });
  Object.values(DATA.mails).forEach(e => { if (e.senderName) s.add(e.senderName); (e.attachments || []).forEach(a => s.add(a.name)); });
  return [...s].filter(x => /[\\uac00-\\ud7a3]/.test(x)).sort((a, b) => b.length - a.length);
};
window.__clean = v => { let t = v; for (const a of window.__ALLOWED()) t = t.split(a).join(' '); return t; };
window.__scan = () => {
  const H = /[\\uac00-\\ud7a3]/, out = [];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let n;
  while ((n = w.nextNode())) {
    let v = n.nodeValue; if (!H.test(v)) continue;
    const el = n.parentElement; if (!el || el.closest(window.__SKIP)) continue;
    if (el.closest(window.__PART)) v = v.split(' · ')[0];
    if (H.test(window.__clean(v))) out.push(v.trim());
  }
  document.querySelectorAll('[placeholder],[title],[aria-label],[alt]').forEach(el => {
    if (el.closest(window.__SKIP)) return;
    for (const a of ['placeholder', 'title', 'aria-label', 'alt']) { const v = el.getAttribute(a); if (v && H.test(v) && H.test(window.__clean(v))) out.push(a + '=' + v); }
  });
  return out;
};`;

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

/* 요청·지연 작업·초안 타이핑이 모두 끝날 때까지 / until requests, timers and the draft typing are all done */
const idle = p => p.waitForFunction(() => typeof mcIdle === 'function' && mcIdle(), null, { timeout: 20000 });

/* 픽스처의 시드 상태 GET 응답(복사본 — 풀어 둔 객체는 공유되므로 고치기 전에 복사) / a seed-state GET reply from the fixture (a copy) */
const seedGet = key => JSON.parse(JSON.stringify(hydrate(FX.states.seed[GET_IDX.get(key)])));

/* opts.override: {'METHOD /api/email/경로': body => ({status, json}) | null(=연결 실패)} — 흐름 밖 한두 요청을 테스트가 직접 답한다
   opts.override: the test answers one or two requests outside the flows ({status, json}, or null for a network failure) */
async function open(t, lang, opts = {}) {
  const ctx = await browser.newContext({ viewport: opts.viewport || { width: 1440, height: 900 } });
  t.after(() => ctx.close());
  const body = opts.body || html, stub = makeStub(opts.flow);
  await ctx.route('**/*', route => {
    const req = route.request(), u = req.url();
    if (u === ORIGIN + '/app.html') return route.fulfill({ body, contentType: 'text/html; charset=utf-8' });
    if (u === ORIGIN + '/parent.html') return route.fulfill({ body: PARENT, contentType: 'text/html; charset=utf-8' });
    /* 글꼴: 로컬 대체본(/static/fonts)은 저장소 파일로, Pretendard CDN CSS 는 빈 응답(네트워크 없이 대체 경로를 쓴다)
       fonts: the local fallback (/static/fonts) from the repository files, the Pretendard CDN CSS served empty (no network,
       so the fallback path is what renders) */
    if (u.startsWith(ORIGIN + '/static/fonts/')) {
      const f = path.join(__dirname, '..', decodeURIComponent(new URL(u).pathname));
      return fs.existsSync(f) ? route.fulfill({ body: fs.readFileSync(f), contentType: 'font/woff2' }) : route.abort();
    }
    if (u.startsWith('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@')) return route.fulfill({ body: '', contentType: 'text/css' });
    if (u.startsWith(ORIGIN + '/api/email/')) {
      const ov = opts.override && opts.override[req.method() + ' ' + decodeURIComponent(new URL(u).pathname)];
      if (!ov) return stub.handle(route);
      const raw = req.postData(), r = ov(raw ? JSON.parse(raw) : null);
      return r ? route.fulfill({ status: r.status || 200, contentType: 'application/json', body: JSON.stringify(r.json) }) : route.abort();
    }
    return route.abort();
  });
  await ctx.addInitScript(l => { try { if (l) localStorage.setItem('ai365_lang', l); else localStorage.removeItem('ai365_lang'); } catch (e) {} }, lang || '');
  const page = await ctx.newPage();
  const errors = [], pageErrors = [];
  page.on('pageerror', e => { errors.push(e.message); pageErrors.push(e.message); });
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(ORIGIN + (opts.parent ? '/parent.html' : '/app.html') + (opts.hash || ''));
  if (!opts.parent) await idle(page);
  return { page, errors, pageErrors, stub };
}

test('dictionary: no duplicate KO keys, every English value is filled, English values carry no em dash', async t => {
  const { page, errors, stub } = await open(t, 'en');
  await page.addScriptTag({ content: SCAN });
  const r = await page.evaluate(() => {
    const keys = I18N.pairs.map(p => p[0]);
    const dup = keys.filter((k, i) => keys.indexOf(k) !== i);
    const empty = I18N.pairs.filter(p => typeof p[1] !== 'string' || !p[1].trim()).map(p => p[0]);
    const dash = I18N.pairs.filter(p => p[1].includes('\u2014')).map(p => p[0]);
    const korean = I18N.pairs.filter(p => /[\uac00-\ud7a3]/.test(window.__clean(p[1]))).map(p => p[1]);
    return { n: I18N.pairs.length, rules: I18N.rules.length, dup, empty, dash, korean, rev: I18N.back('Inbox'), dead: typeof I18N.draftEn,
      tok: { size: I18N.tok.dict.size, conflicts: I18N.tok.conflicts, skipped: I18N.tok.skipped } };
  });
  /* 날짜·주문번호 자리 사전 — 항목마다 자리를 만들 수 있고 서로 부딪히지 않는다 / token-slot dictionary: every entry templated, no clashes */
  assert.ok(r.tok.size >= 10, 'token entries ' + r.tok.size);
  assert.deepEqual(r.tok.conflicts, []);
  assert.deepEqual(r.tok.skipped, []);
  assert.ok(r.n > 400, 'dictionary size ' + r.n);
  assert.ok(r.rules > 90, 'rule count ' + r.rules);
  assert.deepEqual(r.dup, []);
  assert.deepEqual(r.empty, []);
  assert.deepEqual(r.dash, []);
  assert.deepEqual(r.korean, []);
  assert.equal(r.rev, '수신메일');   // 역방향 사전 / reverse dictionary
  assert.equal(r.dead, 'undefined');   // 초안은 서버가 lang 으로 만든다 / drafts come from the server per lang
  assert.deepEqual(stub.misses, []);
  assert.deepEqual(errors, []);
});

test('page file: no em dash anywhere (it is exported on its own), Pretendard with a local fallback, tabular figures', async t => {
  /* 파일 전체(주석·사전 포함)에 em dash 가 없고, 글꼴은 Pretendard CDN + 로컬 대체본(400·600·700)이다
     no em dash anywhere in the file (comments and dictionary included); the typeface is the Pretendard CDN plus the local
     fallback (400, 600, 700) */
  assert.equal(html.includes('\u2014'), false);
  assert.ok(html.includes('<link rel="stylesheet" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard-dynamic-subset.min.css">'));
  for (const w of ['Regular', 'SemiBold', 'Bold']) assert.ok(html.includes(`url(/static/fonts/pretendard/Pretendard-${w}.woff2)`), w);
  const { page, errors, stub } = await open(t, 'ko');
  await page.evaluate(() => goMail('E-1001')); await idle(page);
  const r = await page.evaluate(async () => {
    await document.fonts.ready;
    const cs = el => getComputedStyle(document.querySelector(el));
    return { family: cs('body').fontFamily, size: cs('body').fontSize, line: cs('body').lineHeight,
      local: [...document.fonts].filter(f => f.family.replace(/"/g, '') === 'Pretendard Local' && f.status === 'loaded').map(f => f.weight).sort(),
      time: cs('.row .r1 time').fontVariantNumeric, count: cs('.nav-i .c').fontVariantNumeric, id: cs('.mh-r .mono').fontFamily,
      dash: document.body.innerText.includes('\u2014') };
  });
  assert.match(r.family, /^"?Pretendard"?, "Pretendard Local", -apple-system/);
  assert.deepEqual([r.size, r.line], ['13.5px', '20.25px']);
  assert.ok(r.local.length >= 2, 'local Pretendard faces in use: ' + r.local.join());
  assert.deepEqual([r.time, r.count], ['tabular-nums', 'tabular-nums']);
  assert.match(r.id, /Cascadia Mono/);                                              // ID 는 고정폭 글꼴 유지 / IDs keep the monospace stack
  assert.equal(r.dash, false);
  assert.deepEqual(stub.misses, []);
  assert.deepEqual(errors, []);
});

test('rules: counts, composed phrases, dates, currency, context words and server messages', async t => {
  const { page } = await open(t, 'en');
  const samples = [
    ['확인 필요 3건', 'Needs review: 3'],
    ['12건 · 전체 기간', '12 items · All time'],
    ['5건 · 최종 업데이트 오늘 · 9월 20일 (일)', '5 items · Last updated: Today · Sun, Sep 20'],
    ['32건 · 처음 ~ 현재', '32 items · Start ~ Now'],
    ['시도 2회 · 최지원', '2 attempts · 최지원'],
    ['11,410원', 'KRW 11,410'],
    ['2026년 9월 18일 (금) 오후 2:20', 'Fri, Sep 18, 2026, 2:20 PM'],
    ['요청 수량 대비 270EA 부족', '270EA short of the requested quantity'],
    ['예상 납기 2026-10-12 ≤ 요청 납기 2026-10-15', 'Estimated 2026-10-12 ≤ requested 2026-10-15'],
    ['ERP 단가 조회 완료 · 적용단가 11,410원 / 재고 2,000EA', 'ERP price lookup done · Unit price KRW 11,410 / Stock 2,000EA'],
    ['라온코스메틱 11 · 수량 변경 감지 (500EA → 1,000EA)', '라온코스메틱 11 · Quantity change detected (500EA → 1,000EA)'],
    ['누리뷰티 02 메일 수신 · 견적요청 / 확인 / 보류', 'Mail received from 누리뷰티 02 · Quote request / Acknowledgment / Hold'],
    ['견적요청 / 확인 / 보류 · STEP 1까지 남은 작업은 자동 완료했습니다.', 'Quote request / Acknowledgment / Hold · Remaining work through STEP 1 was completed automatically.'],
    ['요청 납기가 없어 예상 납기를 안내합니다', 'No requested date, so the estimated delivery is quoted'],
    ['SMTP 451 Temporary failure: 수신 서버 응답 지연', 'SMTP 451 Temporary failure: the receiving server responded late'],
    ['Sales Order (번호 없음) 를 ERP에서 찾을 수 없습니다.', 'Sales Order (no number) was not found in the ERP.'],
    ['SO-20260916-00109 는 다른 고객(누리코스메틱 12)의 주문입니다. 인보이스를 발송할 수 없습니다.', 'SO-20260916-00109 is an order of another customer (누리코스메틱 12). The invoice cannot be sent.'],
    ['견적요청 / 확인 / 보류', 'Quote request / Acknowledgment / Hold'],
    ['카밍 세럼 견적 및 주문 건', '카밍 세럼 quote and order'],
    ['300EA 기준 9,500원 / 예상 납기 10월 12일', 'KRW 9,500 for 300EA / Est. delivery Oct 12'],
    ['메일에서 배송지 값을 찾지 못했습니다. 주문등록 처리에 꼭 필요한 값입니다.', 'No ship-to was found in the mail. It is required for the order entry workflow.'],
    ['모두 확인하면 견적요청 메뉴에서 바로 처리할 수 있습니다.', 'Once all are reviewed, you can handle it right away in the Quote request menu.'],
    ['누리 (고객 미확정)', '누리 (customer TBD)'],
    ['ERP API Timeout (응답 대기 30초 초과) 주문은 등록되지 않았습니다.', 'ERP API Timeout (no response within 30 seconds) The order was not registered.'],
    /* 서버 검증 메시지·데모 초기화 / server validation messages and the demo reset */
    ['STEP 3부터 진행해 주세요.', 'Start from STEP 3.'],
    ['시작일 형식은 YYYY-MM-DD 입니다.', 'Start date must be in YYYY-MM-DD format.'],
    ['보류 중인 메일입니다. 보류를 해제해 주세요.', 'This mail is on hold. Please release the hold.'],
    ['Sales Order SO-20260920-00126 는 이미 다른 내용으로 등록되어 있습니다.', 'Sales Order SO-20260920-00126 is already registered with different details.'],
    ['메일·Case·처리오류·활동 기록을 처음 상태로 되돌립니다. 지금까지 처리한 내용은 모두 사라집니다.', 'Mails, cases, processing errors and the activity log go back to their initial state. Everything handled so far will be lost.'],
    ['데모 데이터를 초기화했습니다', 'Demo data reset'],
    ['M코스메틱 이메일 에이전트 접근 권한이 없습니다', 'You have no access to the M Cosmetic email agent'],   /* 서버 403 / the server's 403 */
    /* 서버가 오늘 기준으로 옮긴 시드 날짜·SO 번호 — 자리 사전으로 맞춘다 / seed dates and SO numbers shifted by the server */
    ['누리뷰티 02가 카밍 세럼 50g 300EA의 단가와 11월 2일 납품 가능 여부를 문의했습니다.', '누리뷰티 02 asked for the unit price of 카밍 세럼 50g 300EA and whether it can be delivered by Nov 2.'],
    ['다온뷰티 04가 SO-20261003-00102(카밍 크림 50g 800EA)의 인보이스 발행을 요청했습니다.', '다온뷰티 04 requested an invoice for SO-20261003-00102 (카밍 크림 50g 800EA).'],
    ['600EA 기준 단가 및 11/7 납기 문의', 'Price for 600EA and delivery by 11/7'],
    ['견적요청 / 카밍 세럼 50g · 300EA · 납기 10/30', 'Quote request / 카밍 세럼 50g · 300EA · Due 10/30']
  ];
  const got = await page.evaluate(s => s.map(([ko]) => I18N.tr(ko)), samples);
  got.forEach((g, i) => assert.equal(g, samples[i][1], samples[i][0]));
  /* 옛 403 문구 쌍은 사전에서 뺐다 / the old 403 pair is gone from the dictionary */
  assert.equal(await page.evaluate(() => I18N.dict.has('이메일 업무 에이전트 접근 권한이 없습니다')), false);
  /* 같은 한국어가 자리에 따라 다르게: 버튼·상태 배지·Intent 칩·토스트 제목 / same Korean, different by place */
  const ctx = await page.evaluate(() => {
    const mk = (tag, cls) => { const el = document.createElement(tag); if (cls) el.className = cls; document.body.appendChild(el); return el; };
    const toastB = mk('div', 'toast').appendChild(document.createElement('b'));
    const feed = mk('ul', 'feed').appendChild(document.createElement('li')).appendChild(document.createElement('span'));
    const todo = mk('div', 'todo').appendChild(document.createElement('span'));
    return [I18N.tr('보류', mk('button')), I18N.tr('보류', mk('span', 'stt')), I18N.tr('확인', mk('span', 'chip')), I18N.tr('확인', mk('button')), I18N.tr('확인 완료', toastB), I18N.tr('확인 완료', mk('button')),
      I18N.tr('누리뷰티 02 · 확인 완료', feed), I18N.tr('11:52 · 확인 완료', todo), I18N.tr('다온뷰티 04 · 보관', feed), I18N.tr('10/03 11:52 · 보관', todo)];
  });
  assert.deepEqual(ctx, ['Put on hold', 'On hold', 'Acknowledgment', 'Confirm', 'Review complete', 'Mark as done',
    '누리뷰티 02 · Marked as done', '11:52 · Mark as done', '다온뷰티 04 · Archived', '10/03 11:52 · Archive']);
});

test('EN render leaves no Korean outside the data exceptions across views, rows, modals, drawers and popups', async t => {
  const { page, errors, stub } = await open(t, 'en', { flow: 'enscan' });
  await page.addScriptTag({ content: SCAN });
  assert.equal(await page.evaluate(() => document.documentElement.lang), 'en');
  assert.equal(await page.title(), 'M Cosmetic Email Agent');
  const residue = new Map();
  const scan = async label => {
    await idle(page);
    for (const x of await page.evaluate(() => window.__scan())) if (!residue.has(x)) residue.set(x, label);
    if (await page.evaluate(() => document.body.innerText.includes('\u2014')) && !residue.has('em dash')) residue.set('em dash', label);
  };
  await scan('dashboard');
  for (const v of ['inbox', 'quote', 'order', 'ship', 'stock', 'invoice', 'etc']) {
    await page.click(`[data-act="nav"][data-v="${v}"]`); await idle(page);
    await page.click('.fchip[data-v="all"]'); await idle(page);
    for (const id of await page.$$eval('.row[data-act="sel"]', els => els.map(e => e.dataset.id))) {
      await page.click(`.row[data-id="${id}"]`); await idle(page);
      await page.$$eval('details', ds => ds.forEach(d => { d.open = true; }));
      await scan('mail ' + id);
    }
  }
  await page.click('[data-act="nav"][data-v="cases"]'); await idle(page);
  for (const id of await page.$$eval('.row[data-act="sel-case"]', els => els.map(e => e.dataset.id))) {
    await page.click(`.row[data-id="${id}"]`); await idle(page); await page.$$eval('details', ds => ds.forEach(d => { d.open = true; })); await scan('case ' + id);
  }
  await page.click('[data-act="nav"][data-v="errors"]'); await idle(page);
  for (const id of await page.$$eval('.row[data-act="sel-err"]', els => els.map(e => e.dataset.id))) { await page.click(`.row[data-id="${id}"]`); await scan('error ' + id); }
  await page.click('[data-act="toggle-notif"]'); await scan('notifications'); await page.click('[data-act="toggle-notif"]');
  await page.fill('#gq', '누리'); await scan('global search'); await page.fill('#gq', 'zzzz'); await scan('global search empty'); await page.fill('#gq', '');
  await page.evaluate(() => goMail('E-1004'));
  for (const a of ['reclass', 'link-case', 'assign-cur', 'complete']) { await page.evaluate(x => ACT[x]({}), a); await scan('modal ' + a); await page.evaluate(() => closeModal()); }
  await page.evaluate(() => modalAttachment('E-1004', 0)); await scan('modal po'); await page.evaluate(() => closeModal());
  await page.click('[data-act="demo-reset"]'); await scan('modal reset'); await page.evaluate(() => closeModal());   /* 사이드바 발치의 [데모 초기화](2026-10-13) / the sidebar-foot reset */
  await page.evaluate(() => openDrawer('case', 'RFQ-2026-00120')); await scan('drawer case');
  await page.evaluate(() => openDrawer('so', 'SO-20260930-00102')); await scan('drawer so');   /* 픽스처 오늘 기준으로 옮겨진 번호 / number shifted to the fixture's today */
  assert.ok(await page.$eval('#drawerRoot .drw', el => el.textContent.includes('카밍 크림 50g')));
  await page.evaluate(() => closeDrawer());
  /* 처리 흐름: 인보이스 ERP 조회(서버 EN 초안) → 미리보기 드로어 → 발송(시나리오 드로어는 2026-10-13 제거)
     flow: invoice ERP lookup (server EN draft), preview drawer, send (the scenario drawer is gone since 2026-10-13) */
  await page.evaluate(async () => { await goMail('E-1022'); await ACT.erp(); });
  await idle(page);
  assert.equal(await page.evaluate(() => curMail().flow.draftState), 'ready');
  await scan('invoice after erp');
  await page.evaluate(() => openDrawer('inv', 'E-1022')); await scan('drawer invoice'); await page.evaluate(() => closeDrawer());
  await page.evaluate(() => ACT.send()); await scan('send modal'); await page.click('[data-act="modal-ok"]');
  await idle(page);
  assert.equal(await page.evaluate(() => curMail().flow.mail), 'sent'); await scan('sent');
  assert.equal(await page.evaluate(() => !!document.querySelector('[data-act="open-scenario"], [data-act="scn-inject"], #btnScn')), false);   /* 데모 시나리오 진입점 없음 / no scenario entry point */
  assert.deepEqual(stub.posts, ['/mails/E-1022/erp', '/mails/E-1022/send']);
  assert.deepEqual(stub.misses, []);
  assert.deepEqual([...residue.entries()], []);
  assert.deepEqual(errors, []);
});

test('server drafts arrive in English in EN (quote and invoice, both variants) and in Korean in KO, because the page sends lang', async t => {
  const en = await open(t, 'en', { flow: 'drafts' });
  await en.page.addScriptTag({ content: SCAN });
  const grab = async () => { await idle(en.page); return en.page.evaluate(() => ({ ta: document.querySelector('#draftTa').value, srv: curMail().flow.draft })); };
  const d = [];
  await en.page.evaluate(async () => { await goMail('E-1001'); await ACT.erp(); }); d.push(await grab());
  await en.page.evaluate(() => ACT.regen()); d.push(await grab());
  await en.page.evaluate(async () => { await goMail('E-1022'); await ACT.erp(); }); d.push(await grab());
  await en.page.evaluate(() => ACT.regen()); d.push(await grab());
  d.forEach((x, i) => assert.equal(x.ta, x.srv, 'textarea shows the server draft ' + i));   /* 타이핑 연출이 끝나면 서버 초안 그대로 / after typing, exactly the server draft */
  const t0 = d.map(x => x.ta);
  /* 픽스처 오늘 2026-10-05 → 요청 납기 10/30, SO·INV 번호 20260930 / fixture today 2026-10-05: due 10/30, SO and INV 20260930 */
  assert.match(t0[0], /^Dear 박지현 대리,\n\nThe unit price for 카밍 세럼 50g 300EA is KRW 9,500,\nand we can deliver by your requested date of October 30\./);
  assert.match(t0[0], /\n\nBest regards,\n김영업\nM Cosmetic$/);
  assert.match(t0[1], /Please find our quote below\.\n\n■ Item: M코스메틱 카밍 세럼 50g \(MC-CAL-SR050\)\n■ Quantity: 300EA\n■ Unit price: KRW 9,500 \(base price KRW 10,000\)\n■ Delivery: October 30, deliverable/);
  assert.match(t0[2], /^Dear 한지우 과장,\n\nPlease find attached the invoice \(INV-20260930-00102\) for SO-20260930-00102, as requested\.\n\n카밍 크림 50g 800EA, total KRW 9,715,200 \(VAT included\)\./);
  assert.match(t0[3], /■ Supply amount: KRW 8,832,000\n■ VAT: KRW 883,200\n■ Total: KRW 9,715,200/);
  assert.deepEqual(await en.page.evaluate(ds => ds.map(x => /[\uac00-\ud7a3]/.test(window.__clean(x))), t0), [false, false, false, false]);
  assert.deepEqual(en.stub.misses, []);
  assert.deepEqual(en.errors, []);
  const ko = await open(t, 'ko', { flow: 'kodraft' });
  await ko.page.evaluate(async () => { await goMail('E-1001'); await ACT.erp(); }); await idle(ko.page);
  assert.match(await ko.page.evaluate(() => document.querySelector('#draftTa').value), /^안녕하세요, 누리뷰티 02 박지현 대리님\.\n\n문의하신 카밍 세럼 50g 300EA 기준 단가는 9,500원이며,/);
  assert.deepEqual(ko.stub.misses, []);
  assert.deepEqual(ko.errors, []);
});

test('KO default render is identical to the app without the translation layer', async t => {
  /* 번역 층 스크립트를 빈 스텁으로 바꾼 사본과 KO 화면을 비교 / compare KO screens against a copy whose layer is a no-op stub */
  const start = html.indexOf('<script>\n/* ====='), end = html.indexOf('window.I18N = I18N;\n</script>');
  assert.ok(start > 0 && end > start, 'translation layer block');
  const stub = html.slice(0, start) + '<script>const I18N = { install() {}, apply() {} };</script>' + html.slice(end + 'window.I18N = I18N;\n</script>'.length);
  const a = await open(t, '', { flow: 'koid' }), b = await open(t, '', { body: stub, flow: 'koid' });
  const snap = p => p.evaluate(() => { document.querySelectorAll('.toast').forEach(x => x.remove()); return { lang: document.documentElement.lang, title: document.title, body: [...document.body.children].filter(el => el.tagName !== 'SCRIPT').map(el => el.outerHTML).join('\n') }; });
  const steps = [async p => {}, async p => p.click('[data-act="nav"][data-v="inbox"]'), async p => p.evaluate(() => goMail('E-1016')),
    async p => p.click('[data-act="tri-class"][data-k="stock"]'), async p => p.evaluate(async () => { await goMail('E-1005'); ACT.order(); }),
    async p => p.evaluate(async () => { closeModal(); await openDrawer('scn'); }), async p => p.evaluate(async () => { closeDrawer(); await go('cases'); }),
    async p => p.click('[data-act="toggle-notif"]')];
  for (const [i, step] of steps.entries()) {
    await step(a.page); await idle(a.page); await step(b.page); await idle(b.page);
    assert.deepEqual(await snap(a.page), await snap(b.page), 'step ' + i);
  }
  assert.equal(await a.page.evaluate(() => I18N.lang), 'ko');
  assert.deepEqual(a.stub.misses, []);
  assert.deepEqual(b.stub.misses, []);
  assert.deepEqual(a.errors, []);
});

test('parent localStorage toggle switches KO and EN in place, with no residue on the first painted frame', async t => {
  const { page, errors, stub } = await open(t, '', { parent: true });
  const frame = page.frames().find(f => f.url().endsWith('/app.html'));
  await frame.waitForFunction(() => typeof I18N === 'object' && document.querySelector('#nav .nav-i') && typeof mcIdle === 'function' && mcIdle());
  await frame.addScriptTag({ content: SCAN });
  await frame.evaluate(async () => { await goMail('E-1011'); await openDrawer('scn'); });   /* 상세·드로어·모달이 열린 채로 전환 / switch with detail, drawer and modal open */
  await frame.waitForFunction(() => mcIdle());
  await frame.evaluate(() => {
    ACT['assign-cur']();
    window.__ko = document.body.innerHTML; window.__log = [];
    /* I18N 리스너 다음에 등록 → 번역이 끝난 뒤 첫 rAF(그리기 직전)에 기록 / registered after I18N's listener: records at the first rAF before paint */
    window.addEventListener('storage', ev => { if (ev.key !== 'ai365_lang') return; requestAnimationFrame(() => window.__log.push({ v: ev.newValue, lang: document.documentElement.lang, residue: ev.newValue === 'en' ? window.__scan().length : -1, same: document.body.innerHTML === window.__ko, modal: document.querySelector('#modalRoot h3').textContent })); });
  });
  for (const [i, v] of ['en', 'ko', 'en', 'ko'].entries()) {
    await page.evaluate(x => localStorage.setItem('ai365_lang', x), v);
    await frame.waitForFunction(n => window.__log.length > n, i);
  }
  const log = await frame.evaluate(() => window.__log);
  assert.deepEqual(log.map(x => [x.v, x.lang, x.residue, x.same, x.modal]), [
    ['en', 'en', 0, false, 'Assign owner'], ['ko', 'ko', -1, true, '담당자 지정'], ['en', 'en', 0, false, 'Assign owner'], ['ko', 'ko', -1, true, '담당자 지정']]);
  assert.deepEqual(stub.misses, []);
  assert.deepEqual(errors, []);
});

test('CTA: a completed non-order mail offers no send, regenerate, save or re-query; an order confirmation can still be sent', async t => {
  const { page, errors, stub } = await open(t, 'ko', { flow: 'cta' });
  const RISKY = ['send', 'regen', 'save-draft', 'erp', 'retry'];
  const ctaActs = () => page.$$eval('#cta [data-act]', els => els.map(e => e.dataset.act));
  const cardActs = () => page.$$eval('#tasks [data-act="erp"], #tasks [data-act="regen"], #tasks [data-act="send"], #tasks [data-act="save-draft"]', els => els.map(e => e.dataset.act));
  const state = () => page.evaluate(() => { const e = curMail(); return { closed: e.closed, cls: e.classification, draft: !!e.flow.draft, mail: e.flow.mail, stale: !!e.flow.erpStale, ro: document.querySelector('#draftTa').readOnly, hint: document.querySelector('#cta .hint').textContent.trim() }; });
  /* 1) 발송 실패한 출하 메일(E-1012)을 완료처리 → 초안이 남아 있어도 발송·재생성·임시저장·재시도 없음
        a failed-send shipping mail (E-1012) marked complete: no send, regenerate, save or retry even with a draft left */
  await page.evaluate(async () => { await goMail('E-1012'); ACT.complete(); });
  await page.click('[data-act="modal-ok"]'); await idle(page);
  let s = await state();
  assert.deepEqual([s.closed, s.cls, s.draft, s.mail, s.ro, s.hint], [true, 'ship', true, 'error', true, '처리가 완료되었습니다.']);
  assert.deepEqual((await ctaActs()).filter(a => RISKY.includes(a)), []);
  assert.deepEqual(await cardActs(), []);
  /* 2) 주문 메일(E-1005): 주문등록(완료 상태) → 주문확인 초안 → 발송 세트가 남는다
        an order mail (E-1005): order entry closes it, the confirmation draft still offers the send set */
  await page.evaluate(async () => { await goMail('E-1005'); ACT.order(); });
  await page.click('[data-act="modal-ok"]'); await idle(page);
  await page.click('#orderCard [data-act="draft"]'); await idle(page);
  s = await state();
  assert.deepEqual([s.closed, s.cls, s.draft, s.ro, s.hint], [true, 'order', true, false, '주문등록 완료']);
  assert.deepEqual((await ctaActs()).filter(a => RISKY.includes(a)), ['send', 'regen', 'save-draft']);
  /* 3) 견적 메일(E-1001): 조회 → 수량 수정(재조회 표시) → 완료처리 → '다시 조회'·발송 버튼 없음
        a quote mail (E-1001): lookup, quantity edit (re-query notice), completion: no re-query and no send buttons */
  await page.evaluate(async () => { await goMail('E-1001'); await ACT.erp(); }); await idle(page);
  await page.fill('#ef-quantity', '400'); await idle(page);
  assert.equal(await page.evaluate(() => curMail().flow.erpStale), true);
  assert.ok((await cardActs()).includes('erp'), 'the stale notice offers a re-query before completion');
  await page.evaluate(() => ACT.complete()); await page.click('[data-act="modal-ok"]'); await idle(page);
  s = await state();
  assert.deepEqual([s.closed, s.cls, s.stale, s.ro, s.hint], [true, 'quote', true, true, '처리가 완료되었습니다.']);
  assert.deepEqual(await cardActs(), []);
  assert.deepEqual((await ctaActs()).filter(a => RISKY.includes(a)), []);
  assert.deepEqual(stub.posts, ['/mails/E-1012/complete', '/mails/E-1005/order', '/mails/E-1005/draft', '/mails/E-1001/erp', '/mails/E-1001/entity', '/mails/E-1001/complete']);
  assert.deepEqual(stub.misses, []);
  assert.deepEqual(errors, []);
});

test('a saved draft on a failed-send mail shows the saved mark while the CTA keeps the server retry step', async t => {
  /* 스토어 save_draft 규칙 그대로의 응답(픽스처 E-1012 값 사용): 발송 실패(mail='error') 메일은 초안과 draftSaved 만 바뀌고
     상태 '오류'·다음 단계 retry·mailError 는 그대로 / the store's save_draft reply for a failed-send mail (built from the
     fixture's E-1012): only the draft and draftSaved change; status '오류', the retry step and mailError stay */
  const detail = seedGet('GET /api/email/mails/E-1012'), meta = seedGet('GET /api/email/meta');
  const openErrs = seedGet('GET /api/email/errors?status=all').items.filter(x => x.status === 'open'), saves = [];
  const { page, errors, stub } = await open(t, 'ko', { override: { 'POST /api/email/mails/E-1012/draft-save': b => {
    saves.push(b);
    const email = JSON.parse(JSON.stringify(detail.email)); email.flow.draft = b.draft; email.flow.draftSaved = true;
    return { json: { email, case: detail.case, errors: openErrs, log: [], toast: { type: 'success', title: '임시저장 완료', msg: '' }, nav: meta.nav } };
  } } });
  const view = () => page.evaluate(() => { const e = curMail(); return { st: e.status, ns: e.nextStep.k, mail: e.flow.mail, saved: !!document.querySelector('#replyCard .stt.done'), fail: !!document.querySelector('#replyCard .msg.err'), cta: [...document.querySelectorAll('#cta [data-act]')].map(b => b.dataset.act) }; });
  await page.evaluate(() => goMail('E-1012')); await idle(page);
  let v = await view();
  assert.deepEqual([v.st, v.ns, v.mail, v.saved, v.fail, v.cta], ['오류', 'retry', 'error', false, true, ['retry']]);
  await page.fill('#draftTa', '고친 답변 본문');
  await page.evaluate(() => ACT['save-draft']()); await idle(page);
  assert.deepEqual(saves, [{ draft: '고친 답변 본문' }]);
  v = await view();
  /* 임시저장됨 표시 + 발송 실패 안내 유지, 하단 실행 바는 서버 nextStep(retry) 그대로 — 발송 세트로 바뀌지 않는다
     saved mark shown, failure notice kept, and the CTA still follows the server nextStep (retry), not the send set */
  assert.deepEqual([v.st, v.ns, v.mail, v.saved, v.fail, v.cta], ['오류', 'retry', 'error', true, true, ['retry']]);
  assert.equal(await page.$eval('#draftTa', el => el.value), '고친 답변 본문');
  assert.ok((await page.$$eval('.toast b', els => els.map(x => x.textContent))).includes('임시저장 완료'));
  assert.deepEqual(stub.misses, []);
  assert.deepEqual(errors, []);
});

test('#view=<menu> picks the first view (and a hash change switches it), and the sidebar reset button resets the demo data after a confirmation', async t => {
  const h = await open(t, 'ko', { hash: '#view=quote' });
  assert.equal(await h.page.evaluate(() => S.view), 'quote');
  assert.ok(await h.page.$eval('[data-act="nav"][data-v="quote"]', el => el.classList.contains('on')));
  const badges = await h.page.$$eval('.row[data-act="sel"] .bdg', els => els.map(e => e.textContent));
  assert.ok(badges.length > 0 && badges.every(x => x === '견적요청'), badges.join());
  await h.page.evaluate(() => { location.hash = '#view=errors'; });
  await h.page.waitForFunction(() => S.view === 'errors'); await idle(h.page);
  assert.ok((await h.page.$$eval('.row[data-act="sel-err"]', els => els.length)) > 0);
  assert.deepEqual(h.stub.misses, []);
  assert.deepEqual(h.errors, []);
  /* 데모 초기화 — 보류해 둔 메일이 시드 상태로 돌아온다 / demo reset: a held mail returns to its seed state */
  const { page, errors, stub } = await open(t, 'ko', { flow: 'reset' });
  await page.evaluate(async () => { await goMail('E-1020'); await ACT.hold(); }); await idle(page);
  assert.equal(await page.evaluate(() => getMail('E-1020').hold), true);
  await page.click('.nav-foot [data-act="demo-reset"]');
  assert.equal(await page.$eval('#modalRoot h3', el => el.textContent), '데모 데이터를 초기화할까요?');
  await page.click('[data-act="modal-ok"]'); await idle(page);
  assert.ok((await page.$$eval('.toast b', els => els.map(e => e.textContent))).includes('데모 데이터를 초기화했습니다'));
  assert.equal(await page.evaluate(() => getMail('E-1020').hold), false);
  assert.ok(await page.$('.nav-foot [data-act="demo-reset"]'), 'the reset button is still there after the reset');
  assert.deepEqual(stub.posts, ['/mails/E-1020/hold', '/reset']);
  assert.deepEqual(stub.misses, []);
  assert.deepEqual(errors, []);
});

test('boot failure (network or 403) shows a translated retry state instead of a blank page', async t => {
  /* 연결 실패와 서버 403(권한 없음) — 오류 문구는 서버 detail 을 그대로 번역해 보인다
     a network failure and the server's 403 (no access); the message is the server detail, translated */
  const cases = [[{ 'GET /api/email/meta': () => null }, /Cannot reach the server/],
    [{ 'GET /api/email/meta': () => ({ status: 403, json: { detail: 'M코스메틱 이메일 에이전트 접근 권한이 없습니다' } }) }, /You have no access to the M Cosmetic email agent/]];
  for (const [override, want] of cases) {
    const { page, pageErrors } = await open(t, 'en', { override });
    /* /meta 가 없으니 허용 목록은 머리글의 고정 프로필 이름만 / without /meta the allow-list is just the header's static profile name */
    await page.addScriptTag({ content: "window.META = { erpCustomers: {}, contacts: {}, users: [{ name: '김영업' }], erpItems: {} };" });
    await page.addScriptTag({ content: SCAN.replace(/META\./g, 'window.META.') });
    const txt = await page.$eval('#main', el => el.innerText);
    assert.match(txt, want);
    assert.match(txt, /Please try again in a moment\./);
    assert.ok(await page.$('#main [data-act="boot-retry"]'));
    assert.deepEqual(await page.evaluate(() => window.__scan()), []);
    assert.deepEqual(pageErrors, []);
  }
});
