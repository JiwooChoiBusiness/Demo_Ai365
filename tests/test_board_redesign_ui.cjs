// 실행: Playwright 가 NODE_PATH 에 있을 때 node --test tests/test_board_redesign_ui.cjs
// 게시판 화면 개편(2026-10-06, 사용자 시안 5장) — 첫 화면(내 보관소 · 내 그룹 · 전체 게시판 카드 + 내가 최근 추가한 항목) → 목록(조회 줄 +
// 카드 3열) → 상세(경로 · ··· · 공유하기 · 리포트 에이전트에서 열기 / 내 보관소에 저장). 목업 전체 + 어댑터를 가짜 원점에 올린 격리 브라우저,
// 게시판 API 는 메모리 스텁이고 요청 주소를 기록해 조회 조건이 서버로 가는지 본다.
// Run with Playwright on NODE_PATH: node --test tests/test_board_redesign_ui.cjs
// Board redesign (2026-10-06, five user mockups): the hub (my library, my groups and all-hands cards plus items I added recently)
// → lists (filter bar and three-column cards) → the detail (breadcrumb, ···, Share, Open in report agent / Save to my library).
// The whole mockup and adapter on a fake origin; the board API is an in-memory stub that records request URLs.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const mockup = fs.readFileSync(path.join(__dirname, '../frontend/ai365-mockup.html'), 'utf8').replace(/\r\n/g, '\n');
const adapter = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8').replace(/\r\n/g, '\n');
const ORIGIN = 'http://bd.test';
const HTML = mockup.replace('</body>', '<script src="/static/adapter.js"></script></body>');
const CHART = { x: ['1월', '2월', '3월'], series: [{ name: '매출', type: 'bar', values: [3, 5, 4], yAxis: 0 }] };
const LINE = { x: ['1Q', '2Q', '3Q', '4Q'], series: [{ name: '매출', type: 'line', values: [9, 13, 12, 16], yAxis: 0 }] };
const DASH = { type: 'dashboard', items: [{ title: '분기 매출', chart: LINE }, { title: '월 매출', chart: CHART }, { title: '지역 비중', chart: { kind: 'donut', x: ['수도권', '영남'], series: [{ name: '비중', values: [6, 4] }] } }] };
const REP = { chart: CHART, insight: '2월이 가장 높다' };
const MEMBER = { no: 7, name: '강수아', dept: '인사총무', grade: '사원', empno: 7, email: '' };

function seedPosts() {
  return [
    { id: 'me1', board: 'me:', kind: 'dashboard', title: '2025년 지역별 지점 실적 대시보드', summary: '2025년 월별 총 매출은 4월에 19.2억 원으로 가장 높았습니다.', data: DASH, author: { id: '', name: '' }, created: '2026-09-23T07:26:00' },
    { id: 'me2', board: 'me:', kind: 'report', title: 'Lumicart 데이터 구조 요약', summary: 'file_name은(는) 모든 항목에서 1입니다.', data: REP, author: { id: '', name: '' }, created: '2026-09-22T10:00:00' },
    { id: 'g1', board: 'g:og9', group: '팀장', kind: 'dashboard', title: '팀장 월간 대시보드', summary: '영남 매출이 늘었습니다.', data: DASH, author: { id: '12', name: '김지영' }, created: '2026-09-21T09:00:00' },
    { id: 'g2', board: 'g:og3', group: '인사총무 표준', kind: 'report', title: '인사 월간 리포트', summary: '입사자가 늘었습니다.', data: REP, author: { id: '', name: '관리자' }, created: '2026-09-20T09:00:00' },
    { id: 'a1', board: 'all', kind: 'report', title: '전사 공지 리포트', summary: '전사 공지입니다.', data: REP, author: { id: '', name: '관리자' }, created: '2026-09-19T09:00:00' },
  ];
}

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

async function app(t, viewport) {
  const srv = { posts: seedPosts(), urls: [], takes: [] };
  const page = await browser.newPage({ viewport: viewport || { width: 1440, height: 1000 } });
  t.after(() => page.close());
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => d.dismiss());
  // 리포트 에이전트(static/report_dash.js) 대역 — 상세의 [리포트 에이전트에서 열기]가 부르는 것만 / a stand-in for the report agent
  await page.addInitScript(() => {
    window.__rdOpened = [];
    window.AI365_reportDash = { isV2: () => false, openPost: pid => window.__rdOpened.push(pid), viewer: { mount: () => ({ destroy() {} }) } };
  });
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), method = req.method(), p = decodeURIComponent(url.pathname);
    const json = (obj, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(obj) });
    if (url.origin !== ORIGIN) return route.abort();
    if (p === '/') return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: HTML });
    if (p === '/static/adapter.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: adapter });
    if (p === '/api/access/bootstrap') return json({ pvtree: [], groups: [], members: [MEMBER], teams: [] });
    if (p === '/api/access/effective/7') return json({ super: false, menus: { m_home: true, m_chat: true }, nodes: {}, mgmt: {}, read: { p_board: true } });
    if (!p.startsWith('/api/boards')) return p.startsWith('/api/') ? json({ detail: 'stub' }, 404) : route.abort();
    const actor = url.searchParams.get('acting_user_id') || ((req.postData() && JSON.parse(req.postData()).acting_user_id) || '');
    const sup = actor === '';
    srv.urls.push(method + ' ' + p + url.search);
    const pick = (list, q, kind) => list.filter(x => (!kind || x.kind === kind) && (!q || (x.title + x.summary).includes(q)));
    if (p === '/api/boards/notifications') return json({ unread: 0, notifications: [] });
    if (p === '/api/boards') {
      const groups = sup ? [['og3', '인사총무 표준'], ['og9', '팀장']] : [['og9', '팀장']];
      return json({ boards: [{ id: 'all', name: '전체 게시판', count: 1, mine: true, canManage: sup, canPost: false }]
        .concat(groups.map(g => ({ id: 'g:' + g[0], name: g[1], count: 1, mine: true, canManage: sup, canPost: true }))),
      me: { id: 'me:' + actor, name: '내 보관소', count: 2 } });
    }
    if (p === '/api/boards/feed') {
      const q = url.searchParams.get('q') || '', kind = url.searchParams.get('kind') || '';
      if (url.searchParams.get('scope') === 'recent') return json({ posts: srv.posts.filter(x => x.author.id === actor && (x.board === 'me:' + actor || x.board.startsWith('g:'))).slice(0, 6) });
      const g = url.searchParams.get('group');
      return json({ posts: pick(srv.posts.filter(x => x.board.startsWith('g:') && (!g || x.board === 'g:' + g)), q, kind) });
    }
    const list = /^\/api\/boards\/([^/]+)\/posts$/.exec(p);
    if (list && method === 'GET') return json({ posts: pick(srv.posts.filter(x => x.board === list[1]), url.searchParams.get('q') || '', url.searchParams.get('kind') || '') });
    const take = /^\/api\/boards\/posts\/([^/]+)\/take$/.exec(p);
    if (take) {
      const src = srv.posts.find(x => x.id === take[1]), copy = Object.assign({}, src, { id: 'copy_' + src.id, board: 'me:' + actor, author: { id: actor, name: '' } });
      srv.posts.unshift(copy); srv.takes.push(take[1]);
      return json({ ok: true, post: copy, existed: false });
    }
    const one = /^\/api\/boards\/posts\/([^/]+)$/.exec(p);
    if (one && method === 'GET') {
      const post = srv.posts.find(x => x.id === one[1]);
      const name = post.board === 'all' ? '전체 게시판' : post.board.startsWith('g:') ? post.group : '내 보관소';
      return json({ post, canManage: sup, own: post.author.id === actor, board_name: name });
    }
    if (one && method === 'DELETE') { srv.posts = srv.posts.filter(x => x.id !== one[1]); return json({ ok: true }); }   // 삭제 확인 창 시험용 / for the delete confirm test
    return json({ detail: 'stub' }, 404);
  });
  await page.goto(ORIGIN + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => typeof window.AI365_openBoard === 'function' && typeof window.AI365_setActingUser === 'function', null, { timeout: 10000 });
  return { page, errors, srv };
}
async function until(fn) { for (let i = 0; i < 300 && !(await fn()); i++) await new Promise(r => setTimeout(r, 50)); assert.ok(await fn()); }
const texts = (page, sel) => page.$$eval(sel, es => es.map(e => e.textContent.trim()));
const crumbs = page => texts(page, '.ai365-bd-crumbs .lk, .ai365-bd-crumbs .cur');
async function openHub(page) {
  await page.click('#ai365BoardNav');
  await page.waitForSelector('#ai365BdRecent .ai365-bd-card');
}

test('the hub shows the three board cards, the recent items without footers, and a recent card opens with its board path', async t => {
  const { page, errors, srv } = await app(t);
  await openHub(page);
  assert.equal(await page.$eval('.ai365-bd-hubhead h1', el => el.textContent), '게시판');
  assert.deepEqual(await texts(page, '.ai365-bd-hubcard b'), ['내 보관소', '내 그룹', '전체 게시판']);   // 전체 게시판 카드는 두 카드 옆 / the all-hands card next to the two
  assert.equal(await page.$eval('.ai365-bd-recent h2', el => el.textContent), '내가 최근 추가한 항목');
  assert.deepEqual(await texts(page, '#ai365BdRecent .ai365-bd-title'), ['2025년 지역별 지점 실적 대시보드', 'Lumicart 데이터 구조 요약', '인사 월간 리포트']);
  assert.equal(await page.$$eval('#ai365BdRecent .ai365-bd-cfoot', es => es.length), 0);   // 첫 화면 카드엔 날짜 줄이 없다(시안) / no footer on the hub (mockup)
  assert.deepEqual(await texts(page, '#ai365BdRecent .ai365-bd-chip'), ['대시보드', '리포트', '리포트']);
  assert.equal(await page.$$eval('#ai365BdRecent .ai365-bd-thumb.dash.n3 > span svg', es => es.length), 3);   // 대시보드 미리보기 = 차트 3개 / three charts
  assert.ok(await page.$('[data-bd-admin]'));   // 슈퍼는 게시판 관리 버튼 / the super admin gets board management
  assert.ok(srv.urls.includes('GET /api/boards/feed?scope=recent&limit=8&acting_user_id='));
  await page.click('#ai365BdRecent .ai365-bd-card:nth-child(3)');
  await page.waitForSelector('.ai365-bd-dthead');
  assert.deepEqual(await crumbs(page), ['게시판', '내 그룹', '인사총무 표준', '인사 월간 리포트']);
  assert.match(await page.$eval('.ai365-bd-dthead .meta', el => el.textContent), /리포트2026-09-20 09:00관리자님이 추가/);
  await page.click('[data-bd-back]');   // 첫 화면에서 열었으면 첫 화면으로 / back to where it was opened
  await page.waitForSelector('.ai365-bd-hubcards');
  assert.deepEqual(errors, []);
});

test('my library list: breadcrumb, kind filter on [조회], Enter search keeps focus, reset, and dates without author', async t => {
  const { page, errors, srv } = await app(t);
  await openHub(page);
  await page.click('[data-bd-go="me"]');
  await page.waitForSelector('#ai365BdList .ai365-bd-card');
  assert.deepEqual(await crumbs(page), ['게시판', '내 보관소']);
  assert.deepEqual([await page.$eval('.ai365-bd-phead h1', el => el.textContent), await page.$eval('.ai365-bd-phead p', el => el.textContent)], ['내 보관소', '내가 저장한 리포트와 대시보드를 모아 봅니다.']);
  assert.equal(await page.$eval('.ai365-bd-filter .lb', el => el.textContent), '내 보관소');
  assert.equal(await page.$('#ai365BdGroup'), null);   // 그룹 고르기는 내 그룹에만 / the group picker is for my groups only
  assert.deepEqual(await texts(page, '#ai365BdList .ai365-bd-cfoot'), ['2026-09-23', '2026-09-22']);   // 내 글이라 누가 추가는 없다 / no author on my own
  await page.selectOption('#ai365BdKind', 'report');
  assert.equal(await page.$$eval('#ai365BdList .ai365-bd-card', es => es.length), 2);   // [조회] 전에는 그대로 / unchanged until [조회]
  await page.click('[data-bd-query]');
  await until(async () => (await page.$$eval('#ai365BdList .ai365-bd-card', es => es.length)) === 1);
  assert.ok(srv.urls.includes('GET /api/boards/me:/posts?acting_user_id=&q=&kind=report'));
  await page.fill('#ai365BdSearch', '없는 글');
  await page.press('#ai365BdSearch', 'Enter');
  await page.waitForSelector('#ai365BdList .ai365-bd-empty b');
  assert.equal(await page.$eval('#ai365BdList .ai365-bd-empty b', el => el.textContent), '검색 결과가 없습니다.');
  assert.equal(await page.evaluate(() => document.activeElement && document.activeElement.id), 'ai365BdSearch');   // Enter 뒤에도 검색창 / focus stays in the search box
  await page.click('[data-bd-reset]');
  await until(async () => (await page.$$eval('#ai365BdList .ai365-bd-card', es => es.length)) === 2);
  assert.deepEqual([await page.$eval('#ai365BdKind', el => el.value), await page.$eval('#ai365BdSearch', el => el.value)], ['', '']);
  assert.deepEqual(errors, []);
});

test('my groups: merged list with authors, the group picker narrows it and renames the bar, and the detail saves to my library', async t => {
  const { page, errors, srv } = await app(t);
  await openHub(page);
  await page.click('[data-bd-go="group"]');
  await page.waitForSelector('#ai365BdList .ai365-bd-card');
  assert.equal(await page.$eval('.ai365-bd-filter .lb', el => el.textContent), '내 그룹 전체');
  assert.deepEqual(await page.$$eval('#ai365BdGroup option', os => os.map(o => o.textContent)), ['전체 그룹', '인사총무 표준', '팀장']);
  assert.deepEqual(await texts(page, '#ai365BdList .ai365-bd-cfoot .who'), ['김지영님이 추가', '관리자님이 추가']);
  assert.ok(srv.urls.includes('GET /api/boards/feed?scope=groups&group=&acting_user_id=&q=&kind='));
  await page.selectOption('#ai365BdGroup', 'og9');
  await page.click('[data-bd-query]');
  await until(async () => (await page.$eval('.ai365-bd-filter .lb', el => el.textContent)) === '팀장');
  await until(async () => (await page.$$eval('#ai365BdList .ai365-bd-card', es => es.length)) === 1);
  assert.ok(srv.urls.includes('GET /api/boards/feed?scope=groups&group=og9&acting_user_id=&q=&kind='));
  await page.click('#ai365BdList .ai365-bd-card');
  await page.waitForSelector('.ai365-bd-dthead');
  assert.deepEqual(await crumbs(page), ['게시판', '내 그룹', '팀장', '팀장 월간 대시보드']);
  await page.click('[data-bd-more]');
  assert.deepEqual(await texts(page, '[data-bd-smenu] button'), ['상단 고정', '삭제']);
  assert.equal(await page.$eval('[data-bd-more]', el => el.getAttribute('aria-expanded')), 'true');
  await page.keyboard.press('Escape');
  assert.equal(await page.$('[data-bd-smenu]'), null);
  await page.click('[data-bd-take]');
  await page.waitForSelector('[data-bd-gome]');
  assert.deepEqual(srv.takes, ['g1']);
  assert.equal(await page.$eval('[data-bd-gome]', el => el.textContent), '내 보관소에서 보기');
  await page.click('[data-bd-gome]');
  await until(async () => (await crumbs(page)).join('/') === '게시판/내 보관소/팀장 월간 대시보드');
  await page.click('[data-bd-sharemenu]');
  assert.deepEqual(await texts(page, '[data-bd-smenu] button'), ['게시판으로 공유', '메일로 공유']);
  await page.click('.ai365-bd-dthead h1');
  assert.equal(await page.$('[data-bd-smenu]'), null);   // 바깥을 누르면 닫힌다 / closes on an outside click
  await page.click('[data-bd-rdopen]');
  assert.deepEqual(await page.evaluate(() => window.__rdOpened), ['copy_g1']);
  await page.click('[data-bd-back]');   // 내 보관소에서 보기로 왔으면 내 보관소 목록으로 / back to the library list
  await page.waitForSelector('.ai365-bd-filter');
  assert.equal(await page.$eval('.ai365-bd-phead h1', el => el.textContent), '내 보관소');
  assert.deepEqual(errors, []);
});

test('English: the redrawn screens use the dictionary, the author template and a direct [Search] label', async t => {
  const { page, errors } = await app(t);
  await openHub(page);
  await page.click('#ai365-lang-toggle');
  await until(async () => (await page.$eval('.ai365-bd-hubhead h1', el => el.textContent)) === 'Boards');
  assert.deepEqual(await texts(page, '.ai365-bd-hubcard b'), ['My library', 'My groups', 'All-hands board']);
  assert.equal(await page.$eval('.ai365-bd-recent h2', el => el.textContent), 'Recently added by me');
  await page.click('[data-bd-go="group"]');
  await page.waitForSelector('#ai365BdList .ai365-bd-card');
  assert.deepEqual(await crumbs(page), ['Boards', 'My groups']);
  assert.equal(await page.$eval('.ai365-bd-filter .lb', el => el.textContent), 'All my groups');
  assert.equal(await page.$eval('[data-bd-query]', el => el.textContent), 'Search');
  assert.equal(await page.$eval('#ai365BdSearch', el => el.placeholder), 'Search');
  assert.deepEqual(await texts(page, '#ai365BdList .ai365-bd-cfoot .who'), ['Added by 김지영', 'Added by 관리자']);
  await page.click('#ai365BdList .ai365-bd-card');
  await page.waitForSelector('[data-bd-take]');
  assert.equal(await page.$eval('[data-bd-take]', el => el.textContent), 'Save to my library');
  await page.click('#ai365-lang-toggle');   // 다시 한국어 — 틀 문구도 되돌아온다 / back to Korean, templates included
  await until(async () => (await page.$eval('[data-bd-take]', el => el.textContent)) === '내 보관소에 저장');
  assert.match(await page.$eval('.ai365-bd-dthead .meta', el => el.textContent), /김지영님이 추가/);
  assert.deepEqual(errors, []);
});

test('a view-as switch to a member returns to the hub, hides board management and asks as that member', async t => {
  const { page, errors, srv } = await app(t);
  await openHub(page);
  await page.click('[data-bd-go="all"]');
  await page.waitForSelector('#ai365BdList .ai365-bd-card');
  await page.click('#ai365BdList .ai365-bd-card');
  await page.waitForSelector('.ai365-bd-dthead');
  assert.deepEqual(await crumbs(page), ['게시판', '전체 게시판', '전사 공지 리포트']);
  await page.evaluate(() => window.AI365_setActingUser(7));
  await page.waitForSelector('.ai365-bd-hubcards');   // 이전 신원의 글을 남겨 두지 않는다 / the previous identity's post does not stay
  await until(async () => srv.urls.includes('GET /api/boards/feed?scope=recent&limit=8&acting_user_id=7'));
  assert.equal(await page.$('[data-bd-admin]'), null);
  await page.click('[data-bd-go="group"]');
  await page.waitForSelector('#ai365BdList .ai365-bd-card');
  assert.deepEqual(await page.$$eval('#ai365BdGroup option', os => os.map(o => o.textContent)), ['전체 그룹', '팀장']);
  await page.click('#ai365BdList .ai365-bd-card');
  await page.waitForSelector('.ai365-bd-dthead');
  assert.equal(await page.$('[data-bd-more]'), null);   // 관리 권한도 내 글도 아니면 ··· 없음 / no ··· without manage or ownership
  assert.ok(await page.$('[data-bd-take]'));
  assert.deepEqual(errors, []);
});

test('wide screens follow the Dev original: the hub is one 800px column, lists use the full width, cards stay at three columns', async t => {
  // 2026-10-28 Dev 원본 정렬(사용자 "원본기준으로"): 첫 화면 = Dev BoardPage 800 단일 열, 카드 = Dev 3열 고정. 2026-10-06 의 넓은 화면 4열 · 넓은 첫 화면은 접었고
  // 좁은 화면의 2열 · 1열만 데모 반응형으로 남는다 / the hub is Dev's 800px column and cards stay at three; only the narrow steps remain as demo responsiveness
  const { page, errors } = await app(t, { width: 1920, height: 1080 });
  await openHub(page);
  const width = () => page.$eval('#ai365BdInner', el => el.getBoundingClientRect().width);
  assert.equal(await width(), 800);
  const cols = sel => page.$eval(sel, el => getComputedStyle(el).gridTemplateColumns.split(' ').length);
  assert.equal(await cols('#ai365BdRecent .ai365-bd-grid3'), 3);
  assert.equal(await cols('.ai365-bd-hubcards'), 3);
  await page.click('[data-bd-go="me"]');
  await page.waitForSelector('#ai365BdList .ai365-bd-card');
  assert.equal(await cols('#ai365BdList .ai365-bd-grid3'), 3);
  assert.ok((await width()) > 800);
  await page.setViewportSize({ width: 1100, height: 1000 });   // 안쪽 780 → 2열(데모 반응형) / 780 inside → two columns (demo responsiveness)
  await until(async () => (await cols('#ai365BdList .ai365-bd-grid3')) === 2);
  assert.deepEqual(errors, []);
});

test('the Dev look: hub cards, 60px breadcrumb row, 64px filter bar, r12 cards with pill chips and the 28/36 heads', async t => {
  const { page, errors } = await app(t);
  await openHub(page);
  const css = (sel, props, pseudo) => page.$eval(sel, (el, a) => { const s = getComputedStyle(el, a[1] || null); return a[0].map(p => s.getPropertyValue(p)); }, [props, pseudo]);
  // 첫 화면(Dev BoardPage · Category · RecentItems) / the hub
  assert.deepEqual(await css('.ai365-bd-hubhead h1', ['font-size', 'line-height', 'font-weight', 'color']), ['28px', '36px', '700', 'rgb(62, 66, 75)']);
  assert.deepEqual(await css('.ai365-bd-hubcard', ['min-height', 'background-color', 'border-top-color', 'border-top-left-radius', 'padding-top', 'padding-left']),
    ['98px', 'rgb(242, 246, 255)', 'rgb(228, 237, 255)', '16px', '16px', '12px']);
  assert.equal(await page.$eval('.ai365-bd-hubcard .ic', el => getComputedStyle(el).color), 'rgb(97, 116, 245)');
  assert.deepEqual(await css('#ai365BdRecent .ai365-bd-card', ['border-top-left-radius', 'border-top-color']), ['12px', 'rgb(220, 224, 235)']);
  assert.deepEqual(await css('#ai365BdRecent .ai365-bd-thumb', ['height']), ['160px']);
  assert.deepEqual(await css('#ai365BdRecent .ai365-bd-chip', ['font-size', 'font-weight', 'border-top-left-radius', 'background-color', 'color']),
    ['13px', '700', '9999px', 'rgb(242, 251, 242)', 'rgb(19, 161, 14)']);
  // 목록(Dev Breadcrumb · BoardLibrary · Filter · Library) / a list
  await page.click('[data-bd-go="me"]');
  await page.waitForSelector('#ai365BdList .ai365-bd-card');
  assert.deepEqual(await css('.ai365-bd-crumbs', ['height', 'font-size']), ['60px', '14px']);
  assert.deepEqual(await css('.ai365-bd-crumbs .back svg', ['width']), ['20px']);
  assert.deepEqual(await css('.ai365-bd-phead h1', ['font-size', 'line-height', 'font-weight']), ['28px', '36px', '600']);
  assert.deepEqual(await css('.ai365-bd-phead p', ['font-size', 'line-height']), ['14px', '22px']);
  assert.deepEqual(await page.$eval('.ai365-bd-filter', el => [el.getBoundingClientRect().height, getComputedStyle(el).borderTopColor, getComputedStyle(el).borderTopLeftRadius]),
    [64, 'rgb(205, 209, 220)', '16px']);
  assert.deepEqual(await css('#ai365BdKind', ['height', 'width', 'background-color']), ['32px', '120px', 'rgb(239, 242, 250)']);
  assert.deepEqual(await css('.ai365-bd-reset', ['width', 'height', 'border-top-left-radius']), ['32px', '32px', '50%']);
  assert.deepEqual(await css('#ai365BdList .ai365-bd-thumb', ['height']), ['266px']);
  // 상세 오른쪽 버튼 40 · 본문 상자 r12 / detail buttons 40 high and the r12 body box
  await page.click('#ai365BdList .ai365-bd-card');
  await page.waitForSelector('.ai365-bd-dthead');
  assert.deepEqual(await page.$$eval('.ai365-bd-act', bs => bs.map(b => b.getBoundingClientRect().height)), [40, 40]);
  assert.deepEqual(await css('.ai365-bd-dthead .meta', ['font-size']), ['16px']);
  assert.deepEqual(await css('.ai365-bd-body', ['border-top-left-radius', 'border-top-color']), ['12px', 'rgb(220, 224, 235)']);
  assert.deepEqual(errors, []);
});

test('delete asks in the Dev-shaped confirm (no window.confirm): [취소] keeps the post, [삭제] deletes it and goes back', async t => {
  const { page, errors, srv } = await app(t);
  const dialogs = [];
  page.on('dialog', d => dialogs.push(d.type()));
  await openHub(page);
  await page.click('[data-bd-go="all"]');
  await page.waitForSelector('#ai365BdList .ai365-bd-card');
  await page.click('#ai365BdList .ai365-bd-card');
  await page.waitForSelector('[data-bd-more]');
  await page.click('[data-bd-more]');
  await page.click('[data-bd-del]');
  await page.waitForSelector('#ai365DcOv.show');
  assert.deepEqual(await page.evaluate(() => {
    const ov = document.getElementById('ai365DcOv');
    return [ov.querySelector('.dialog-title').textContent, ov.querySelector('.dialog-body').textContent,
      [...ov.querySelectorAll('.dialog-actions .btn')].map(b => b.textContent), getComputedStyle(ov.querySelector('.dialog')).width,
      getComputedStyle(ov.querySelector('.btn-danger')).backgroundColor, document.activeElement && document.activeElement.textContent];
  }), ['삭제', '이 차트를 삭제하시겠습니까?', ['취소', '삭제'], '480px', 'rgb(204, 38, 53)', '취소']);
  await page.click('#ai365DcOv .btn-ghost');
  await page.waitForSelector('#ai365DcOv:not(.show)', { state: 'attached' });
  assert.ok(!srv.urls.some(u => u.startsWith('DELETE ')));
  await page.click('[data-bd-more]');
  await page.click('[data-bd-del]');
  await page.waitForSelector('#ai365DcOv.show');
  await page.keyboard.press('Escape');   // Esc 도 취소 / Esc cancels too
  await page.waitForSelector('#ai365DcOv:not(.show)', { state: 'attached' });
  assert.ok(!srv.urls.some(u => u.startsWith('DELETE ')));
  await page.click('[data-bd-more]');
  await page.click('[data-bd-del]');
  await page.click('#ai365DcOv .btn-danger');
  await until(() => srv.urls.some(u => u.startsWith('DELETE /api/boards/posts/a1')));
  await page.waitForSelector('.ai365-bd-filter');   // 보던 목록으로 / back to the list
  assert.deepEqual(dialogs, []);   // 브라우저 확인 창은 뜨지 않는다 / no native dialog
  assert.deepEqual(errors, []);
});
