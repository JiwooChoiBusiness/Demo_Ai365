// Run with Playwright available on NODE_PATH: node --test --test-concurrency=1 tests/test_live_widgets_ui.cjs
// 채팅 실시간 위젯(2026-10-06) — static/live_widgets.js 를 격리 브라우저(뉴욕 시간대)에서 돌린다: 날씨(7일 · 선택 · °F · 강수 확률 막대),
// 환율(금액 · 100엔), 지도(지도 막힘 → 목록, 크게 보기 목록 · 더 보기 · 다음 페이지 · 가게 정보 후기 작성자 · 시간 펼치기 · Esc),
// 복원 자리표시 → 다시 불러오기, 팝업 위치, 본문 뒤 삽입. 구글 지도 · 서버 · 네트워크 없음(ai365Fetch 스텁).
// Chat live widgets (2026-10-06) — runs static/live_widgets.js in an isolated browser (New York time zone): weather (7 days,
// selection, °F, rain-chance bars), FX (amounts, per 100 yen), map (blocked map → list, expanded list, more, next page,
// place details with review authors, hours toggle, Esc), restore placeholder → reload, popup position, insertion after the
// body. No Google Maps, server or network (ai365Fetch is stubbed).
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const KST = fs.readFileSync(path.join(__dirname, '../static/kst.js'), 'utf8');
const WG = fs.readFileSync(path.join(__dirname, '../static/live_widgets.js'), 'utf8');

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

function weatherCard(selected) {
  const days = [], time = [], t = [], pop = [], code = [];
  for (let i = 0; i < 7; i++) {
    const date = '2026-10-' + String(6 + i).padStart(2, '0');
    days.push({ date, max: 22 + i, min: 10 + i, code: [0, 2, 61, 80, 3, 95, 1][i], pop: [0, 10, 70, 60, 20, 80, 5][i] });
    for (let h = 0; h < 24; h++) { time.push(date + 'T' + String(h).padStart(2, '0') + ':00'); t.push(10 + h / 2); pop.push((h * 7) % 100); code.push(2); }
  }
  return { kind: 'weather', v: 1, location: '서울', fetched_at: '2026-10-06T16:50:00+09:00', now: { t: 19.5, code: 2 },
           days, hourly: { time, t, pop, code }, selected: selected || 0, source: { name: 'Open-Meteo', url: 'https://open-meteo.com/' } };
}

function place(i) {
  return { id: 'ChIJplace' + String(i).padStart(4, '0'), name: '가게 ' + i, cat: '한식당', rating: 4.5, count: 10, price: '₩10,000~20,000',
           lat: 37.5 + i / 1000, lng: 127 + i / 1000, addr: '강남구 ' + i, phone: '02-000-000' + i, web: '', maps: '',
           dir: 'https://www.google.com/maps/dir/?api=1', open: { now: true, label: '영업 중 · 오후 10:00에 영업 종료' },
           photo: { name: 'places/ChIJplace/photos/AUc' + i, author: '작가' + i, author_uri: 'https://maps.google.com/x' } };
}

// 뉴욕 시간대 페이지 + 스텁(ai365Fetch 응답은 경로별) / a New York page with stubs (ai365Fetch answers by path)
async function fixture(t, opts) {
  opts = opts || {};
  const ctx = await browser.newContext({ timezoneId: 'America/New_York' });
  const page = await ctx.newPage();
  t.after(() => ctx.close());
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  t.after(() => assert.deepEqual(errors, []));
  await page.setContent('<div class="main" style="position:relative;width:1200px;height:800px"><div id="chatInner"><div class="msg"><div class="ai-body">본문</div></div></div></div>');
  await page.addScriptTag({ content: KST });
  await page.addScriptTag({ content: `
    window.__lang = ${JSON.stringify(opts.lang || 'ko')};
    window.__calls = [];
    window.__routes = ${JSON.stringify(opts.routes || {})};
    function ai365CurrentLang() { return window.__lang; }
    function toast(m) { window.__toast = m; }
    function ai365Fetch(url, o) {
      window.__calls.push(url);
      const key = Object.keys(window.__routes).find(k => url.indexOf(k) === 0);
      if (!key) return Promise.reject(new Error(url + ' → HTTP 404'));
      const v = window.__routes[key];
      if (v && v.__status) return Promise.reject(new Error(url + ' → HTTP ' + v.__status));
      return Promise.resolve(JSON.parse(JSON.stringify(v)));
    }
    function showView(name) { window.__view = name; }` });
  await page.addScriptTag({ content: WG });
  return page;
}

test('widgets go right after the answer body, not inside it', async (t) => {
  const page = await fixture(t);
  const out = await page.evaluate((card) => {
    const body = document.querySelector('.ai-body');
    ai365WgInsert(body, [{ kind: 'table', rows: [] }, card]);
    const holder = body.nextElementSibling;
    return { cls: holder.className, inBody: !!body.querySelector('.ai365-wg'), kinds: [...holder.children].map(c => c.getAttribute('data-wg')) };
  }, weatherCard());
  assert.deepEqual(out, { cls: 'ai365-wgs', inBody: false, kinds: ['weather'] });
});

test('weather: seven days, the asked day selected, °F toggle, rain-chance bars and KST footer', async (t) => {
  const page = await fixture(t);
  const out = await page.evaluate((card) => {
    const body = document.querySelector('.ai-body');
    ai365WgInsert(body, [card]);
    const el = document.querySelector('.ai365-wg-wx');
    const read = () => ({
      days: [...el.querySelectorAll('.wx-day')].map(d => d.querySelector('.d').textContent + d.querySelector('.hi').textContent + '/' + d.querySelector('.lo').textContent),
      sel: [...el.querySelectorAll('.wx-day')].findIndex(d => d.classList.contains('sel')),
      temp: el.querySelector('.wx-temp').textContent,
      points: el.querySelectorAll('.wx-chart circle').length,
      firstLabel: el.querySelector('.wx-chart text:last-of-type') ? [...el.querySelectorAll('.wx-chart text')].map(x => x.textContent).filter(s => /[ap]m$/.test(s))[0] : '',
    });
    const a = read();
    el.querySelector('[data-unit]').click();
    const f = read();
    el.querySelector('[data-mode]').click();
    el.querySelector('[data-set="pop"]').click();
    const bars = el.querySelectorAll('.wx-chart rect').length;
    const pct = [...el.querySelectorAll('.wx-chart text')].map(x => x.textContent).filter(s => /%$/.test(s)).length;
    el.querySelector('[data-day="3"]').click();
    return { a, f, bars, pct, sel3: [...el.querySelectorAll('.wx-day')].findIndex(d => d.classList.contains('sel')),
             mode: el.querySelector('[data-mode]').textContent.trim(), foot: el.querySelector('.ai365-wg-foot').textContent };
  }, weatherCard(1));
  assert.deepEqual(out.a.days.slice(0, 3), ['화22°/10°', '수23°/11°', '목24°/12°']);   // 2026-10-06 = 화요일 / Tuesday
  assert.equal(out.a.sel, 1);
  assert.equal(out.a.temp, '20°');
  assert.equal(out.a.points, 8);                                  // 3시간 간격 8점 / eight points at 3-hour steps
  assert.equal(out.a.firstLabel, '12am');                         // 내일 = 0시부터 / tomorrow starts at midnight
  assert.equal(out.f.temp, '67°');                                // 19.5°C → 67°F
  assert.equal(out.f.days[0], '화72°/50°');
  assert.equal(out.bars, 24);
  assert.equal(out.pct, 8);
  assert.equal(out.sel3, 3);
  assert.equal(out.mode, '강수 확률');
  assert.equal(out.foot, 'Open-Meteo· 10월 6일 16:50 기준');
});

test('weather in English uses English labels', async (t) => {
  const page = await fixture(t, { lang: 'en' });
  const out = await page.evaluate((card) => {
    ai365WgInsert(document.querySelector('.ai-body'), [card]);
    const el = document.querySelector('.ai365-wg-wx');
    return { day: el.querySelector('.wx-day .d').textContent, desc: el.querySelector('.wx-desc').textContent, mode: el.querySelector('[data-mode]').textContent.trim() };
  }, weatherCard());
  assert.deepEqual(out, { day: 'Tue', desc: 'Partly cloudy', mode: 'Temperature' });
});

test('fx: currency rows, rounded amounts and the KST as-of line', async (t) => {
  const page = await fixture(t);
  const out = await page.evaluate(() => {
    ai365WgInsert(document.querySelector('.ai-body'), [
      { kind: 'fx', v: 1, base: { code: 'USD', amount: 1 }, quote: { code: 'KRW', amount: 1341.26 }, rate: 1341.26, unit: 1,
        as_of: '2026-10-06T16:41:00+09:00', source: { name: 'Yahoo Finance', url: 'https://finance.yahoo.com/' } },
      { kind: 'fx', v: 1, base: { code: 'JPY', amount: 100 }, quote: { code: 'KRW', amount: 848.13 }, rate: 8.4813, unit: 100,
        as_of: '2026-10-06T16:41:00+09:00', source: { name: 'Yahoo Finance', url: 'https://finance.yahoo.com/' } }]);
    return [...document.querySelectorAll('.ai365-wg-fx')].map(el => [...el.querySelectorAll('.fx-row')].map(r => r.textContent).concat(el.querySelector('.ai365-wg-foot').textContent));
  });
  assert.deepEqual(out[0], ['US미국 달러$ 1', 'KR대한민국 원₩ 1,341', 'Yahoo Finance· 2026년 10월 6일 16:41 KST 기준']);
  assert.deepEqual(out[1].slice(0, 2), ['JP일본 엔¥ 100', 'KR대한민국 원₩ 848']);
});

test('map blocked → list with a note; expanded view lists four, then more, then the next page, then fewer', async (t) => {
  const items = [1, 2, 3, 4, 5, 6].map(place);
  const page = await fixture(t, { routes: {
    '/api/live/map-load': { ok: false, reason: 'quota' },
    '/api/live/photo': { uri: 'https://lh3.googleusercontent.com/p' },
    '/api/live/places?': { items: [place(7)], next: null },
  } });
  const out = await page.evaluate(async (card) => {
    ai365WgInsert(document.querySelector('.ai-body'), [card]);
    await new Promise(r => setTimeout(r, 120));
    const el = document.querySelector('.ai365-wg-pl');
    const res = { noMap: el.classList.contains('no-map'), note: el.querySelector('.pl-note').textContent, cards: el.querySelectorAll('.pl-card').length };
    el.querySelector('[data-expand]').click();
    await new Promise(r => setTimeout(r, 60));
    const x = document.querySelector('.ai365-mapx');
    const side = () => ({ head: x.querySelector('.mx-head').textContent, rows: x.querySelectorAll('.mx-item').length, btn: (x.querySelector('[data-x="more"]') || {}).textContent || '' });
    res.inMain = x.parentNode === document.querySelector('.main');
    res.s1 = side();
    x.querySelector('[data-x="more"]').click();
    res.s2 = side();
    x.querySelector('[data-x="more"]').click();
    await new Promise(r => setTimeout(r, 60));
    res.s3 = side();
    x.querySelector('[data-x="more"]').click();
    res.s4 = side();
    res.calls = window.__calls.slice();
    return res;
  }, { kind: 'places', v: 1, query: '선릉역 맛집', area: '선릉역', lang: 'ko', fetched_at: '2026-10-06T16:50:00+09:00', items, next: 'tok2',
       source: { name: 'Google 지도', url: 'https://www.google.com/maps/search/?api=1&query=x' } });
  assert.equal(out.noMap, true);
  assert.equal(out.note, '이번 달 무료 지도 사용량을 다 써서 목록만 보여 드려요.');
  assert.equal(out.cards, 6);
  assert.equal(out.inMain, true);
  assert.deepEqual(out.s1, { head: '6개의 장소', rows: 4, btn: '더 많은 장소 보기' });
  assert.deepEqual(out.s2, { head: '6개의 장소', rows: 6, btn: '더 많은 장소 보기' });   // 다음 페이지가 남았다 / a next page remains
  assert.deepEqual(out.s3, { head: '7개의 장소', rows: 7, btn: '더 적게 보기' });
  assert.deepEqual(out.s4, { head: '7개의 장소', rows: 4, btn: '더 많은 장소 보기' });
  assert.ok(out.calls.some(u => u.indexOf('/api/live/places?q=%EC%84%A0%EB%A6%89%EC%97%AD%20%EB%A7%9B%EC%A7%91&lang=ko&page=tok2') === 0));
});

test('place details show attributed reviews, the hours toggle, and Esc goes back then closes', async (t) => {
  const it = place(1);
  const page = await fixture(t, { routes: {
    '/api/live/map-load': { ok: false, reason: 'no_key' },
    '/api/live/photo': { uri: 'https://lh3.googleusercontent.com/p' },
    ['/api/live/places/' + it.id]: Object.assign({}, it, { addr_full: '서울 강남구 1', about: '',
      hours: [{ day: '월요일', time: '오전 11:00~오후 9:00' }, { day: '화요일', time: '휴무일' }],
      reviews: [{ author: '홍길동', author_uri: 'https://maps.google.com/a', avatar: '', rating: 5, when: '2주 전', text: '맛있어요', uri: '' }],
      reviews_uri: 'https://maps.google.com/r' }),
  } });
  const out = await page.evaluate(async (card) => {
    ai365WgInsert(document.querySelector('.ai-body'), [card]);
    await new Promise(r => setTimeout(r, 60));
    document.querySelector('.pl-card').click();
    await new Promise(r => setTimeout(r, 80));
    const x = document.querySelector('.ai365-mapx');
    const res = { head: x.querySelector('.mx-head span').textContent, name: x.querySelector('.mx-dt h3').textContent,
                  review: x.querySelector('.rv-h a').textContent, more: x.querySelector('.rv-more').textContent,
                  credit: x.querySelector('.credit').textContent, hoursHidden: x.querySelector('.hours').hidden,
                  acts: [...x.querySelectorAll('.mx-dt .acts .ai365-wg-btn')].map(a => a.textContent) };
    x.querySelector('[data-x="hours"]').click();
    res.hoursShown = !x.querySelector('.hours').hidden;
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    res.afterEsc1 = (document.querySelector('.ai365-mapx .mx-head span') || {}).textContent;
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    res.closed = !document.querySelector('.ai365-mapx');
    return res;
  }, { kind: 'places', v: 1, query: '선릉역 맛집', area: '선릉역', lang: 'ko', items: [it], next: null, source: { name: 'Google 지도', url: '' } });
  assert.equal(out.head, '가게 정보');
  assert.equal(out.name, '가게 1');
  assert.equal(out.review, '홍길동');
  assert.equal(out.more, 'Google 지도에서 후기 더 보기');
  assert.equal(out.credit, '사진: 작가1');
  assert.deepEqual(out.acts, ['경로', '전화']);
  assert.equal(out.hoursHidden, true);
  assert.equal(out.hoursShown, true);
  assert.equal(out.afterEsc1, '1개의 장소');
  assert.equal(out.closed, true);
});

test('a restored map card is a placeholder until reloaded, and navigation closes the expanded view', async (t) => {
  const page = await fixture(t, { routes: {
    '/api/live/map-load': { ok: false, reason: 'quota' },
    '/api/live/places?': { kind: 'places', v: 1, query: '선릉역 맛집', area: '선릉역', lang: 'ko', items: [place(1), place(2)], next: null, source: { name: 'Google 지도', url: '' } },
  } });
  const out = await page.evaluate(async () => {
    ai365WgInsert(document.querySelector('.ai-body'), [{ kind: 'places', v: 1, query: '선릉역 맛집', area: '선릉역', lang: 'ko', ids: ['a', 'b'], count: 2 }]);
    const el = document.querySelector('.ai365-wg-pl');
    const res = { title: el.querySelector('.pl-stale b').textContent, btn: el.querySelector('[data-reload]').textContent, calls0: window.__calls.length };
    el.querySelector('[data-reload]').click();
    await new Promise(r => setTimeout(r, 120));
    const fresh = document.querySelector('.ai365-wg-pl');
    res.cards = fresh.querySelectorAll('.pl-card').length;
    res.reloadUrl = window.__calls[0];
    fresh.querySelector('[data-expand]').click();
    showView('chat');
    res.closedByNav = !document.querySelector('.ai365-mapx');
    return res;
  });
  assert.equal(out.title, '‘선릉역 맛집’ 장소 2곳');
  assert.equal(out.btn, '지도 다시 불러오기');
  assert.equal(out.calls0, 0);                                    // 누르기 전엔 아무것도 부르지 않는다 / nothing is fetched before the click
  assert.equal(out.cards, 2);
  assert.ok(out.reloadUrl.startsWith('/api/live/places?q='));
  assert.equal(out.closedByNav, true);
});

test('after a key auth failure the map card lists places without counting another map load', async (t) => {
  const page = await fixture(t, { routes: { '/api/live/map-load': { ok: true, key: 'k', map_id: 'DEMO_MAP_ID' },
                                            '/api/live/photo': { uri: 'https://lh3.googleusercontent.com/p' } } });
  const out = await page.evaluate(async (card) => {
    AI365_WG.authFailed = true;
    ai365WgInsert(document.querySelector('.ai-body'), [card]);
    await new Promise(r => setTimeout(r, 150));
    const el = document.querySelector('.ai365-wg-pl');
    ai365WgNoMap(el, 'auth');   // 두 번째 호출은 아무것도 바꾸지 않는다 / a second call changes nothing
    return { noMap: el.classList.contains('no-map'), notes: el.querySelectorAll('.pl-note').length, note: el.querySelector('.pl-note').textContent,
             mapLoads: window.__calls.filter(u => u.indexOf('/api/live/map-load') === 0).length,
             canvas: getComputedStyle(el.querySelector('.pl-canvas')).display };
  }, { kind: 'places', v: 1, query: '선릉역 맛집', area: '선릉역', lang: 'ko', items: [place(1), place(2)], next: null, source: { name: 'Google 지도', url: '' } });
  assert.deepEqual(out, { noMap: true, notes: 1, note: '지도를 불러오지 못해 목록만 보여 드려요.', mapLoads: 0, canvas: 'none' });
});

test('popup sits above the pin, flips below near the top edge, and stays inside the box', async (t) => {
  const page = await fixture(t);
  const out = await page.evaluate(() => [
    ai365WgPopPos({ left: 500, top: 400, width: 60, height: 40 }, { w: 260, h: 120 }, { w: 1200, h: 800 }),
    ai365WgPopPos({ left: 500, top: 100, width: 60, height: 40 }, { w: 260, h: 120 }, { w: 1200, h: 800 }),
    ai365WgPopPos({ left: 1180, top: 400, width: 20, height: 40 }, { w: 260, h: 120 }, { w: 1200, h: 800 }),
  ]);
  assert.deepEqual(out[0], { left: 400, top: 270, below: false });
  assert.deepEqual(out[1], { left: 400, top: 150, below: true });
  assert.equal(out[2].left, 932);
});
