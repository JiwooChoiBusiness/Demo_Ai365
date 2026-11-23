// 실행: Playwright 가 NODE_PATH 에 있을 때 node --test tests/test_report_dash_design_ui.cjs
// 리포트 에이전트 화면 디자인(2026-10-13 사용자 시안 5장): 머리줄 ← · [내 보관소], 제목 줄 ✎ + [공유][되돌리기][저장][⋯], 3열 카드 격자, 카드 [펼치기][⋮] 메뉴,
// 발치 [Bar | Table], 대화 서랍(손잡이) + 답변의 버전 칩 "V1 · … | 시각", 버전 미리보기 막대 + [이 버전으로 이어가기]. 도구 트리는 그대로.
// /api/reports/dash* 는 fetch 스텁(버전 API 포함), Chart.js 는 저장소의 vendored 파일. 앱 서버 · DB · LLM 없음.
// Run with Playwright on NODE_PATH: node --test tests/test_report_dash_design_ui.cjs
// The report-agent screen design (five user mockups, 2026-10-13): header back arrow and [My library], title row pencil + share, undo,
// save and more, a three-column card grid, card [expand][kebab] menu, footer [Bar | Table], the conversation drawer (handle) with a
// version chip under each answer, and the version preview bar with [Continue from this version]. The tool tree stays as it was.
// /api/reports/dash* is a fetch stub (version API included); Chart.js is the vendored file. No app server, DB or LLM.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const ROOT = path.join(__dirname, '..');
const STYLE = { palette: 'indigo', labels: false, smooth: false, fill: false, legend: 'none', rounded: true, grid: true };
const COLS = ['지점', '월', '매출', '달성률'];
const ROWS = [['강남점', '1월', 100, 80], ['광주점', '1월', 50, 70], ['강남점', '2월', 120, 90], ['광주점', '2월', 40, 60], ['강남점', '3월', 90, 85], ['광주점', '3월', 60, 75]];
const SOURCE = { id: 's1', name: 'Source 1', label: '', columns: COLS, rows: ROWS, types: { 지점: 'text', 월: 'text', 매출: 'number', 달성률: 'number' },
  periods: { 월: 'month' }, sql: 'SELECT 1', tables: ['sales'], fetched_at: '2026-10-13T10:00:00', origin: { kind: 'chat', note: '', chat_id: '', clone_of: '' } };
function chart(over) {
  return Object.assign({ type: 'bar', group: null, sort: { by: 'none', dir: 'desc' }, limit: null, stack: false, ref_lines: [], unit: '', filters: [], style: STYLE, size: 'half', insight: '' }, over);
}
const CHARTS = [
  chart({ id: 'c1', source: 's1', title: '월별 매출', x: '월', insight: '3월 매출이 가장 낮습니다.', filters: [{ id: 'f1', col: '지점', label: '지점', selected: ['강남점'] }], y: [{ col: '매출', agg: 'sum', name: '매출', type: 'bar', axis: 0 }] }),
  chart({ id: 'c2', source: 's1', title: '지점별 매출', type: 'pie', x: '지점', y: [{ col: '매출', agg: 'sum', name: '매출', type: 'bar', axis: 0 }] }),
  chart({ id: 'c3', source: 's1', title: '달성률 추이', type: 'line', x: '월', y: [{ col: '달성률', agg: 'avg', name: '달성률', type: 'line', axis: 0 }] }),
];

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

// 패널을 덮개로 연다. 스텁 서버: 턴마다 버전이 하나 늘고, 버전 조회 · 이어가기를 흉내 낸다 / open the panel as an overlay; the stub adds a version per turn and serves preview and restore
async function fixture(t, opts) {
  opts = opts || {};
  const page = await browser.newPage({ viewport: { width: opts.width || 1400, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  t.after(async () => { await page.close(); assert.deepEqual(errors, []); });
  await page.setContent('<div id="v"></div>');
  await page.addScriptTag({ path: path.join(ROOT, 'static', 'vendor', 'chart.umd.min.js') });
  await page.evaluate(({ src, charts, messages, versions }) => {
    window.toasts = []; window.toast = m => window.toasts.push(String(m)); window.calls = [];
    window.AI365_KO2EN = {}; window.AI365_EN2KO = {}; window.__lang = 'ko';
    window.ai365CurrentLang = () => window.__lang;
    window.ai365T = ko => (window.__lang === 'en' && window.AI365_KO2EN[ko]) || ko;
    const clone = x => JSON.parse(JSON.stringify(x));
    const db = { state: { v: 2, title: '매출 대시보드', sources: [src], charts: clone(charts), kpis: [] }, undo: 0, messages: clone(messages), versions: clone(versions),
      snaps: {} };
    versions.forEach(v => { db.snaps[v.n] = { title: '버전 ' + v.n + ' 제목', charts: clone(charts).slice(0, 1), kpis: [], theme: {} }; });
    const light = () => db.versions.map(v => ({ n: v.n, label: v.label, at: v.at }));
    const session = () => ({ id: 'd1', post_id: null, saved: false, kind: 'chat', origin: {}, state: clone(db.state), messages: clone(db.messages), updated: '',
      can_undo: db.undo > 0, dirty: db.undo > 0, saved_at: '', pending_auto: false, versions: light() });
    const json = (d, status) => new Response(JSON.stringify(d), { status: status || 200, headers: { 'content-type': 'application/json' } });
    window.fetch = async (url, init2) => {
      const body = init2 && init2.body ? JSON.parse(init2.body) : {};
      window.calls.push({ url, body });
      let m;
      if (url === '/api/reports/dash') return json({ session: session() });
      if (/\/ops$/.test(url)) {
        for (const op of body.ops) {
          if (op.op === 'chart_remove') db.state.charts = db.state.charts.filter(c => c.id !== op.id);
          else if (op.op === 'filter_add') { const c = db.state.charts.find(c => c.id === op.chart); c.filters.push({ id: 'f' + (c.filters.length + 1), col: op.col, label: op.col, selected: [] }); }
          else if (op.op === 'title') db.state.title = op.title;
          else return json({ detail: '알 수 없는 조작입니다' }, 422);
        }
        db.undo += 1;
        return json({ session: session() });
      }
      if (/\/turn$/.test(url)) {   // 턴 = 차트 하나 추가 + 버전 하나 / a turn adds a chart and a version
        const n = db.versions.length ? db.versions[db.versions.length - 1].n + 1 : 1;
        db.snaps[n] = { title: db.state.title, charts: clone(db.state.charts), kpis: [], theme: {} };
        db.versions.push({ n, label: '차트 추가', at: '2026-10-13T10:0' + n + ':00' });
        db.undo += 1;
        const trace = [{ agent: 'Visualize Agent', group: '리포트', tool: 'create_chart', label: '차트 추가', ok: true, detail: '', say: '' }];
        db.messages.push({ role: 'user', text: body.message, focus: body.focus, ts: '2026-10-13T10:0' + n + ':00' },
          { role: 'agent', text: '**월별 매출** 차트를 추가했습니다.', trace, ts: '2026-10-13T10:0' + n + ':00', ver: n });
        return json({ session: session(), reply: '차트를 추가했습니다.', trace });
      }
      if ((m = /\/versions\/(\d+)\/restore$/.exec(url))) {
        const from = +m[1], snap = db.snaps[from];
        if (!snap) return json({ detail: '없는 버전입니다' }, 404);
        db.state = Object.assign({}, db.state, clone(snap));
        const n = db.versions[db.versions.length - 1].n + 1;
        db.snaps[n] = clone(snap);
        db.versions.push({ n, label: 'V' + from + '에서 이어가기', at: '2026-10-13T11:00:00' });
        db.messages.push({ role: 'agent', text: 'V' + from + ' 시점의 대시보드로 되돌렸습니다. 이어서 요청해 주세요.', trace: [], ts: '2026-10-13T11:00:00', ver: n });
        db.undo += 1;
        return json({ session: session(), reply: '되돌렸습니다.' });
      }
      if ((m = /\/versions\/(\d+)\?/.exec(url))) {
        const v = db.versions.find(x => x.n === +m[1]);
        if (!v) return json({ detail: '없는 버전입니다' }, 404);
        return json({ version: { n: v.n, label: v.label, at: v.at }, state: Object.assign({ v: 2, sources: [src] }, clone(db.snaps[v.n])) });
      }
      return json({ detail: 'no ' + url }, 404);
    };
  }, { src: SOURCE, charts: opts.charts || CHARTS, messages: opts.messages || [], versions: opts.versions || [] });
  await page.addScriptTag({ path: path.join(ROOT, 'static', 'report_dash.js') });
  await page.evaluate(() => window.AI365_reportDash.open({ sources: [], host: 'overlay' }));
  await page.waitForSelector('#ai365RdRoot .ai365-rd-grid');
  await mounted(page, (opts.charts || CHARTS).length);
  return page;
}
const mounted = (page, n) => page.waitForFunction(n => [...document.querySelectorAll('canvas[data-rd-canvas]')].filter(c => window.Chart.getChart(c)).length === n, n);
const texts = (page, sel) => page.$$eval(sel, els => els.map(e => e.textContent.trim()));
const has = (page, sel) => page.evaluate(sel => !!document.querySelector(sel), sel);
const order = page => page.$$eval('.ai365-rd-grid [data-rd-card]', els => els.map(e => e.dataset.rdCard));
const menuItems = page => page.$$eval('[data-rd-smenu] button', els => els.map(e => [e.querySelector('span').textContent, e.disabled]));
const ask = async (page, text) => { await page.fill('#ai365RdInput', text); await page.press('#ai365RdInput', 'Enter'); };

test('header, title row and card grid follow the mockup: back arrow, library, pencil + share/undo/save/more, three columns, type tab, insight block', async (t) => {
  const page = await fixture(t);
  assert.deepEqual([await has(page, '.ai365-rd-hd .ai365-rd-back[data-rd="back"]'), await page.$eval('.ai365-rd-hd .t', e => e.textContent), await texts(page, '.ai365-rd-hd .ai365-rd-hbtn span')],
    [true, '리포트 에이전트', ['내 보관소']]);
  // 제목 줄: 제목 · 연필 · 오른쪽 아이콘 네 개(공유 · 되돌리기 · 저장 · 그 밖의 작업) / the title row: title, pencil, then four icons
  assert.deepEqual(await page.$$eval('.ai365-rd-top button', els => els.map(e => e.dataset.rd)), ['rename', 'sharedash', 'undo', 'save', 'more']);
  assert.deepEqual(await page.$$eval('.ai365-rd-top button', els => els.map(e => e.disabled)), [false, false, true, false, false]);   // 되돌릴 것이 없다 / nothing to undo yet
  assert.equal(await has(page, '.ai365-rd-top [data-rd-kpiadd], .ai365-rd-top .ai365-rd-kbtn, .ai365-rd-ref, [data-rd-size], .ai365-rd-hd [data-rd-sst]'), false);
  // 격자는 1400px 에서 3열, 카드마다 [펼치기][⋮] 두 개와 [종류 | Table] 발치 / three columns at 1400px; two header tools; the type and Table tabs
  assert.equal(await page.$eval('.ai365-rd-grid', e => getComputedStyle(e).gridTemplateColumns.split(' ').length), 3);
  assert.deepEqual(await page.$$eval('[data-rd-card="c1"] .tools button', els => els.map(e => e.dataset.rdExpand ? 'expand' : (e.dataset.rdCmenu ? 'menu' : '?'))), ['expand', 'menu']);
  assert.deepEqual([await texts(page, '[data-rd-card="c1"] .ai365-rd-vt span'), await texts(page, '[data-rd-card="c2"] .ai365-rd-vt span'), await texts(page, '[data-rd-card="c3"] .ai365-rd-vt span')],
    [['Bar', 'Table'], ['Pie', 'Table'], ['Line', 'Table']]);
  assert.deepEqual(await page.$eval('[data-rd-card="c1"] .ai365-rd-ins', e => [e.querySelector('b').textContent, e.querySelector('span').textContent, getComputedStyle(e.querySelector('b')).display]),
    ['Insight', '3월 매출이 가장 낮습니다.', 'block']);
  // 대화가 없으면 서랍도 손잡이도 없다 / no conversation: no drawer, no handle
  assert.deepEqual([await page.$eval('#ai365RdChat', e => e.hidden), await page.$eval('.ai365-rd-handle', e => e.hidden), await has(page, '.ai365-rd-main.chat-open')], [true, true, false]);
  // 좁은 화면에서는 2열 / two columns on a narrower screen
  const narrow = await fixture(t, { width: 900 });
  assert.equal(await narrow.$eval('.ai365-rd-grid', e => getComputedStyle(e).gridTemplateColumns.split(' ').length), 2);
});

test('the card kebab menu holds filter, note, duplicate, run again, download, share, save and delete; filter opens the column picker and delete removes the chart', async (t) => {
  const page = await fixture(t);
  await page.click('[data-rd-cmenu="c1"]');
  assert.deepEqual(await menuItems(page), [['필터', false], ['메모 달기', false], ['복제', false], ['다시 실행', false], ['다운로드', false], ['게시판으로 공유', false], ['메일로 공유', false], ['저장', false], ['삭제', false]]);
  await page.click('[data-rd-cmenu="c1"]');                                                    // 다시 누르면 닫힌다 / a second click closes
  assert.equal(await has(page, '[data-rd-smenu]'), false);
  await page.click('[data-rd-cmenu="c2"]');                                                    // 원 차트에는 메모 항목이 없다 / a pie has no note item
  assert.deepEqual((await menuItems(page)).map(x => x[0]), ['필터', '복제', '다시 실행', '다운로드', '게시판으로 공유', '메일로 공유', '저장', '삭제']);
  await page.keyboard.press('Escape');
  assert.equal(await has(page, '[data-rd-smenu]'), false);
  await page.click('[data-rd-cmenu="c1"]');
  await page.click('[data-rd-smenu] [data-rdf-add="c1"]');
  assert.deepEqual([await has(page, '[data-rd-smenu]'), await texts(page, '[data-rd-cf="c1"] [data-rdf-colpick]')], [false, ['월', '매출', '달성률']]);   // 이미 걸린 지점은 빠진다 / the filtered column is left out
  await page.click('[data-rd-cf="c1"] [data-rdf-colpick][data-col="월"]');
  await page.waitForSelector('[data-rd-cf="c1"] [data-rdf-open="c1:f2"]');
  await page.click('[data-rd-cmenu="c3"]');
  await page.click('[data-rd-smenu] [data-rd-del="c3"]');
  await page.waitForFunction(() => !document.querySelector('[data-rd-card="c3"]'));
  assert.deepEqual([await order(page), (await page.evaluate(() => window.toasts)).length], [['c1', 'c2'], 1]);
});

test('expanding lifts the card to the top at full width and targets it; collapse and Escape put the grid back', async (t) => {
  const page = await fixture(t);
  await page.click('[data-rd-expand="c2"]');
  await mounted(page, 3);
  assert.deepEqual([await order(page), await page.$eval('[data-rd-card="c2"]', e => [e.classList.contains('expanded'), e.classList.contains('focus'), getComputedStyle(e).gridColumnStart]),
    await page.$eval('[data-rd-expand="c2"]', e => e.title)], [['c2', 'c1', 'c3'], [true, true, '1'], '카드 접기']);
  assert.equal(await page.$eval('[data-rd-card="c2"] .ai365-rd-canvas', e => e.getBoundingClientRect().height), 340);
  await page.click('[data-rd-expand="c2"]');
  await mounted(page, 3);
  assert.deepEqual([await order(page), await has(page, '.ai365-rd-card.expanded')], [['c1', 'c2', 'c3'], false]);
  await page.click('[data-rd-expand="c3"]');
  await mounted(page, 3);
  await page.keyboard.press('Escape');
  await mounted(page, 3);
  assert.deepEqual([await order(page), await has(page, '.ai365-rd-card.expanded')], [['c1', 'c2', 'c3'], false]);
});

test('sending opens the conversation drawer with the answer, its tool tree and a version chip; the handle folds and unfolds it', async (t) => {
  const page = await fixture(t);
  await ask(page, '월별 매출 차트 추가해줘');
  await page.waitForFunction(() => document.querySelectorAll('#ai365RdChat .ai365-rd-msg.agent').length === 1);
  assert.deepEqual([await has(page, '.ai365-rd-main.chat-open'), await page.$eval('#ai365RdChat', e => e.hidden), await page.$eval('.ai365-rd-handle', e => e.hidden)], [true, false, false]);
  assert.deepEqual(await texts(page, '#ai365RdChat .ai365-rd-msg.user'), ['월별 매출 차트 추가해줘']);
  assert.deepEqual(await page.$eval('#ai365RdChat .ai365-rd-msg.agent .tx', e => [e.textContent, e.querySelector('b').textContent]), ['월별 매출 차트를 추가했습니다.', '월별 매출']);
  assert.deepEqual(await texts(page, '#ai365RdChat .ai365-rd-msg.agent .ai365-rd-tree .tn.leaf .lb'), ['차트 추가']);                 // 도구 트리는 그대로 / the tool tree stays
  assert.deepEqual(await page.$eval('#ai365RdChat .ai365-rd-ver', e => [e.dataset.rdVer, e.querySelector('.vn').textContent, e.querySelector('.at').textContent]), ['1', 'V1 · 차트 추가', '2026.10.13 10:01']);
  assert.equal(await has(page, '#ai365RdDock .ai365-rd-ans, #ai365RdDock [data-rd="hist"]'), false);
  await page.click('[data-rd="chat"]');
  assert.deepEqual([await has(page, '.ai365-rd-main.chat-open'), await page.$eval('#ai365RdChat', e => e.hidden)], [false, true]);
  await page.click('[data-rd="chat"]');
  assert.deepEqual([await has(page, '.ai365-rd-main.chat-open'), await page.$eval('#ai365RdChat', e => e.hidden)], [true, false]);
  // 되돌리기는 제목 줄 아이콘 / undo lives in the title row
  assert.equal(await page.$eval('.ai365-rd-top [data-rd="undo"]', e => e.disabled), false);
});

test('a version chip previews that version read-only with the floating bar; close returns, and continue makes it the working copy with a new version', async (t) => {
  const msgs = [{ role: 'user', text: '대시보드로 만들어줘', ts: '2026-09-28T09:45:00' }, { role: 'agent', text: '대시보드를 만들었습니다.', trace: [], ts: '2026-09-28T09:45:00', ver: 1 }];
  const page = await fixture(t, { messages: msgs, versions: [{ n: 1, label: '대시보드 생성', at: '2026-09-28T09:45:00' }] });
  assert.deepEqual([await page.$eval('#ai365RdChat', e => e.hidden), await page.$eval('.ai365-rd-handle', e => e.hidden)], [true, false]);   // 대화가 있으면 손잡이만, 서랍은 접힌 채 / with a conversation: handle shown, drawer folded
  await page.click('[data-rd="chat"]');
  assert.equal(await page.$eval('#ai365RdChat .ai365-rd-ver .vn', e => e.textContent), 'V1 · 대시보드 생성');
  await page.click('[data-rd-ver="1"]');
  await page.waitForSelector('[data-rd-pvbar]');
  await mounted(page, 1);
  assert.deepEqual([await page.$eval('.ai365-rd-top h2', e => e.textContent), await page.$eval('[data-rd-pvbar] .lb', e => e.textContent), await order(page), await has(page, '[data-rd-ver="1"].on')],
    ['버전 1 제목', '"대시보드 생성" 미리보기', ['c1'], true]);
  assert.deepEqual(await page.$$eval('.ai365-rd-top button', els => els.map(e => [e.dataset.rd, e.disabled])), [['sharedash', true], ['undo', true], ['save', true], ['more', true]]);   // 연필도 없다 / no pencil either
  assert.deepEqual([await page.$eval('#ai365RdInput', e => e.disabled), await page.$eval('[data-rd="send"]', e => e.disabled)], [true, true]);
  await page.click('[data-rd-cmenu="c1"]');
  assert.deepEqual(await menuItems(page), [['필터', true], ['메모 달기', true], ['복제', true], ['다시 실행', true], ['다운로드', false], ['게시판으로 공유', true], ['메일로 공유', true], ['저장', true], ['삭제', true]]);
  await page.keyboard.press('Escape');
  await page.click('[data-rd="pvx"]');
  await mounted(page, 3);
  assert.deepEqual([await page.$eval('.ai365-rd-top h2', e => e.textContent), await has(page, '[data-rd-pvbar]'), await order(page), await page.$eval('#ai365RdInput', e => e.disabled)], ['매출 대시보드', false, ['c1', 'c2', 'c3'], false]);
  await page.click('[data-rd-ver="1"]');
  await page.waitForSelector('[data-rd-pvbar]');
  await page.click('[data-rd="pvgo"]');
  await page.waitForFunction(() => !document.querySelector('[data-rd-pvbar]') && document.querySelectorAll('#ai365RdChat .ai365-rd-ver').length === 2);
  await mounted(page, 1);
  assert.deepEqual([await page.$eval('.ai365-rd-top h2', e => e.textContent), await order(page), await texts(page, '#ai365RdChat .ai365-rd-ver .vn'), await page.$eval('#ai365RdInput', e => e.disabled)],
    ['버전 1 제목', ['c1'], ['V1 · 대시보드 생성', 'V2 · V1에서 이어가기'], false]);
  assert.match((await page.evaluate(() => window.toasts)).pop(), /V1/);
  assert.equal(await page.$eval('.ai365-rd-top [data-rd="undo"]', e => e.disabled), false);
  assert.equal(await page.evaluate(() => window.calls.some(c => /\/versions\/1\/restore$/.test(c.url))), true);
});

test('English labels: header, menu items and the version chip, while the footer tabs stay English words', async (t) => {
  const msgs = [{ role: 'user', text: 'hi', ts: '2026-09-28T09:45:00' }, { role: 'agent', text: 'done', trace: [], ts: '2026-09-28T09:45:00', ver: 2 }];
  const page = await fixture(t, { messages: msgs, versions: [{ n: 1, label: '대시보드 생성', at: '2026-09-28T09:40:00' }, { n: 2, label: 'V1에서 이어가기', at: '2026-09-28T09:45:00' }] });
  await page.evaluate(() => { window.__lang = 'en'; document.body.insertAdjacentHTML('beforeend', '<button id="ai365-lang-toggle"></button>'); document.getElementById('ai365-lang-toggle').click(); });
  await page.waitForFunction(() => (document.querySelector('.ai365-rd-hd .t') || {}).textContent === 'Report agent');
  await mounted(page, 3);
  assert.deepEqual([await texts(page, '.ai365-rd-hd .ai365-rd-hbtn span'), await texts(page, '[data-rd-card="c1"] .ai365-rd-vt span'), await page.$eval('.ai365-rd-top [data-rd="more"]', e => e.title)],
    [['My library'], ['Bar', 'Table'], 'More actions']);
  await page.click('[data-rd-cmenu="c1"]');
  assert.deepEqual((await menuItems(page)).map(x => x[0]), ['Filters', 'Add note', 'Duplicate', 'Run again', 'Download', 'Share to board', 'Share by email', 'Save', 'Delete']);
  await page.keyboard.press('Escape');
  await page.click('[data-rd="chat"]');
  assert.deepEqual([await page.$eval('#ai365RdChat .ai365-rd-ver .vn', e => e.textContent), await page.$eval('[data-rd="chat"]', e => e.title)], ['V2 · Continued from V1', 'Hide conversation']);
  await page.click('[data-rd-ver="2"]');
  await page.waitForSelector('[data-rd-pvbar]');
  assert.deepEqual([await page.$eval('[data-rd-pvbar] .lb', e => e.textContent), await page.$eval('[data-rd-pvbar] .go', e => e.textContent), await page.$eval('#ai365RdInput', e => e.placeholder)],
    ['Previewing "Continued from V1"', 'Continue from this version', 'Previewing. Press [Continue from this version] to keep editing.']);
});
