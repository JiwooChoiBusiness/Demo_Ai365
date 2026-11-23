// 실행: Playwright 가 NODE_PATH 에 있을 때 node --test tests/test_chat_agentic_toggle_ui.cjs
// Chat | Agentic 토글(2026-10-16 사용자 지시): 홈 머리줄 가운데 알약, Agentic 은 아무것도 없는 빈 화면(#viewWork), Chat 은 홈으로.
// 목업 전체 + 어댑터를 가짜 원점에 올린 격리 브라우저, API 는 스텁. 캡처는 scratchpad 의 AI365_SHOTS 폴더(있을 때만).
// Run with Playwright on NODE_PATH: node --test tests/test_chat_agentic_toggle_ui.cjs
// The Chat | Agentic toggle (user request 2026-10-16): a pill centred in the home sub-header; Agentic shows an empty view (#viewWork)
// only; Chat returns home. The whole mockup and adapter on a fake origin with stubbed APIs. Screenshots go to AI365_SHOTS when set.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const mockup = fs.readFileSync(path.join(__dirname, '../frontend/ai365-mockup.html'), 'utf8').replace(/\r\n/g, '\n');
const adapter = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8').replace(/\r\n/g, '\n');
const ORIGIN = 'http://ca.test';
const HTML = mockup.replace('</body>', '<script src="/static/adapter.js"></script></body>');
const SHOTS = process.env.AI365_SHOTS || '';

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

async function app(t) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => d.dismiss());
  t.after(async () => { await page.close(); assert.deepEqual(errors, []); });
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), p = decodeURIComponent(url.pathname);
    const json = (obj, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(obj) });
    if (url.origin !== ORIGIN) return route.abort();
    if (p === '/') return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: HTML });
    if (p === '/static/adapter.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: adapter });
    if (p === '/api/access/bootstrap') return json({ pvtree: [], groups: [], members: [], teams: [] });
    if (p === '/api/boards/notifications') return json({ unread: 0, notifications: [] });
    return p.startsWith('/api/') ? json({ detail: 'stub' }, 404) : route.abort();
  });
  await page.goto(ORIGIN + '/');
  await page.waitForSelector('#viewHome.active .ai365-ca');
  return page;
}
const state = page => page.evaluate(() => {
  const act = [...document.querySelectorAll('main.main > .view.active')].map(v => v.id);
  const on = el => [...el.querySelectorAll('[data-ca]')].filter(b => b.classList.contains('on')).map(b => b.dataset.ca);
  const home = document.querySelector('#viewHome .ai365-ca'), work = document.querySelector('#viewWork .ai365-ca');
  return { active: act, homeOn: home ? on(home) : null, workOn: work ? on(work) : null, workText: (document.getElementById('viewWork') || { textContent: '' }).textContent.replace(/\s+/g, ''),
    chatHasPill: !!document.querySelector('#viewChat .ai365-ca') };
});
const shot = async (page, name) => { if (SHOTS) { fs.mkdirSync(SHOTS, { recursive: true }); await page.waitForTimeout(250); await page.screenshot({ path: path.join(SHOTS, name) }); } };   // 뷰 전환 페이드가 끝난 뒤 / after the view fade-in

test('the pill sits centred in the home sub-header with Chat selected, labelled Chat / Agentic, and the chat view has none', async (t) => {
  const page = await app(t);
  const geo = await page.evaluate(() => {
    const pill = document.querySelector('#viewHome .ai365-ca').getBoundingClientRect(), bar = document.querySelector('#viewHome .sub-header').getBoundingClientRect();
    return { dx: Math.round(Math.abs((pill.left + pill.right) / 2 - (bar.left + bar.right) / 2)), inside: pill.top >= bar.top && pill.bottom <= bar.bottom, labels: [...document.querySelectorAll('#viewHome .ai365-ca [data-ca]')].map(b => b.textContent) };
  });
  assert.deepEqual([geo.dx <= 2, geo.inside, geo.labels], [true, true, ['Chat', 'Agentic']]);
  assert.deepEqual(await state(page), { active: ['viewHome'], homeOn: ['chat'], workOn: ['chat'], workText: 'ChatAgentic', chatHasPill: false });
  await shot(page, 'ca_1_home.png');
});

// 2026-10-20 DEV 정렬: 전역 머리줄(Home/Workspace 탭)이 없어져 홈 진입은 사이드바 '새 채팅'(#newChatBtn → 홈 화면)과
// '홈'(#navHome → 인앱 그룹웨어 화면, 어댑터가 클릭을 붙인다)이 맡는다. 두 버튼을 실제로 눌러 본다.
// 2026-10-20 DEV alignment: the global header (Home/Workspace tabs) is gone, so the sidebar 'New chat' (#newChatBtn, the home view)
// and 'Home' (#navHome, the in-app groupware view; the adapter binds the click) take over. Both are really clicked here.
test('Agentic opens an empty view holding only the pill; Chat and sidebar New chat return home, sidebar Home opens the groupware view', async (t) => {
  const page = await app(t);
  await page.click('#viewHome [data-ca="agentic"]');
  assert.deepEqual(await state(page), { active: ['viewWork'], homeOn: ['agentic'], workOn: ['agentic'], workText: 'ChatAgentic', chatHasPill: false });
  assert.equal(await page.$eval('#viewWork', e => e.children.length), 2);   // 머리줄 + 빈 본문뿐 / the sub-header and the empty body only
  await shot(page, 'ca_2_agentic.png');
  await page.click('#viewWork [data-ca="chat"]');
  assert.deepEqual((await state(page)).active, ['viewHome']);
  assert.deepEqual((await state(page)).homeOn, ['chat']);
  await page.click('#viewHome [data-ca="agentic"]');
  assert.deepEqual((await state(page)).active, ['viewWork']);
  await page.click('#newChatBtn');                                         // 사이드바 '새 채팅' = showView('home') / the sidebar New chat
  assert.deepEqual([(await state(page)).active, (await state(page)).homeOn, (await state(page)).workOn], [['viewHome'], ['chat'], ['chat']]);
  await page.click('#viewHome [data-ca="agentic"]');
  await page.click('#navHome');                                            // 사이드바 '홈' = 인앱 그룹웨어 화면 / the sidebar Home opens the groupware view
  assert.deepEqual([(await state(page)).active, (await state(page)).workOn], [['ai365GwView'], ['chat']]);
  assert.equal(await page.$eval('#navHome', e => e.classList.contains('selected')), true);
  await page.click('#newChatBtn');
  assert.deepEqual((await state(page)).active, ['viewHome']);
  assert.equal(await page.$eval('#navHome', e => e.classList.contains('selected')), false);
  await page.click('#viewHome [data-ca="agentic"]');
  await page.evaluate(() => { showView('resource'); });                   // 다른 화면으로 가면 빈 화면도 숨는다 / another view hides the empty one too
  assert.deepEqual((await state(page)).active, ['viewResource']);
});

test('the labels stay English after the language toggle and keyboard focus reaches both segments', async (t) => {
  const page = await app(t);
  await page.click('#ai365-lang-toggle');
  await page.waitForFunction(() => document.getElementById('homeInput').placeholder === 'How can I help you?');   // 영어로 바뀐 뒤 / once the page is English
  assert.deepEqual(await page.$$eval('#viewHome .ai365-ca [data-ca]', els => els.map(b => b.textContent)), ['Chat', 'Agentic']);
  await page.focus('#viewHome [data-ca="chat"]');
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement.dataset.ca), 'agentic');
  await page.keyboard.press('Enter');
  assert.deepEqual((await state(page)).active, ['viewWork']);
});
