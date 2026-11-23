// 실행: Playwright 가 NODE_PATH 에 있을 때 node --test tests/test_agentic_admin_ui.cjs
// 관리 센터 'Agentic' 카드(2026-10-19): 허브 카드 → 설정 페이지(허용 폴더 · 기본값 · 차단 명령 · 예산) → 저장(PUT), 뷰애즈는 읽기 전용,
// 메뉴 권한 m_agentic 이 없으면 홈의 Chat | Agentic 알약이 숨고 Agentic 화면으로 못 간다. 목업 + 어댑터를 가짜 원점에 올리고 API 는 스텁.
// Run with Playwright on NODE_PATH: node --test tests/test_agentic_admin_ui.cjs
// The Admin Center 'Agentic' card (2026-10-19): hub card → settings page (folders, defaults, denied commands, budgets) → save (PUT);
// view-as users read only; without the m_agentic menu permission the home pill hides and the Agentic view is refused.
// 2차(2026-10-19): 탭 [설정 | 명령 · 스킬 | 훅]: 새 예산 3개 · notify_default · 기본 권한 플랜, 전역 명령 · 스킬 편집 카드(이름 규칙은 저장 전에 거른다,
// [저장]은 [확인] 안 한 카드를 먼저 확인한다), 전역 훅 표(명령이 빈 훅은 저장 전에 거른다), 숫자 칸은 서버 범위. 셋 다 같은 [저장](PUT settings 전체)으로
// 나간다. 새 키가 없는 응답도 기본값(빈 목록 · false)으로 채운다.
// Phase 2 (2026-10-19): tabs [Settings | Commands and skills | Hooks]: three new budgets, notify_default and the Plan default mode; an edit card
// for the global commands and skills (the name rule is checked before saving and [Save] confirms an unconfirmed card first); the global hooks
// table (a hook without a command is refused before saving); number fields follow the server ranges. All three go out with the same [Save]
// (the whole settings object). A response without the new keys is filled with defaults (empty lists, false).
// 폴더 고르기(2026-10-19): 설정 응답에 folder_picker 가 있으면 #agFolderIn 옆 [찾아보기](pick-folder → 칸 채움, 추가는 [추가]), 503 · 네트워크
// 실패면 입력칸 아래 작은 탐색기(드라이브부터), 뷰애즈는 꺼진 버튼, EN 라벨.
// Folder picking (2026-10-19): with folder_picker in the settings answer, [Browse] beside #agFolderIn (pick-folder fills the field, [Add]
// adds it); a 503 or a network failure opens the small explorer under the field (drives first); view-as users get a disabled button; EN labels.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const mockup = fs.readFileSync(path.join(__dirname, '../frontend/ai365-mockup.html'), 'utf8').replace(/\r\n/g, '\n');
const adapter = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8').replace(/\r\n/g, '\n');
const ORIGIN = 'http://ag.test';
const HTML = mockup.replace('</body>', '<script src="/static/adapter.js"></script></body>');
const MEMBER = { no: 7, name: '강수아', dept: '인사총무', grade: '사원', empno: 7, email: '' };
// 새 키(notify_default · commands · skills · hooks · 새 예산 3개)가 없는 응답 / a response without the new keys (notify_default, commands, skills, hooks, the three new budgets)
const NO_NEW_KEYS = { allowed_folders: ['C:\\Users\\demo\\Desktop', 'C:\\Users\\demo\\Documents'], default_perm: 'auto', default_model: 'gemini-3.8-flash',
  deny_commands: ['rm\\s+-rf', '\\bformat\\b'], budgets: { max_steps: 200, max_minutes: 120, max_sessions: 3, bash_timeout_sec: 120, max_output_chars: 20000 } };
// 스텁 서버의 기본 응답 = 위 + 새 키 / the stub server's default answer = the above plus the new keys
const SETTINGS = Object.assign(JSON.parse(JSON.stringify(NO_NEW_KEYS)), {
  notify_default: false,
  commands: [{ name: 'review', description: '변경 검토', body: '$ARGUMENTS 의 변경을 검토하고 개선점을 정리하라' }],
  skills: [],
  hooks: [{ event: 'pre_tool', matcher: 'bash', command: 'python hooks/check.py', timeout_sec: 30 }],
});
Object.assign(SETTINGS.budgets, { compact_pct: 80, max_subagents: 3, subagent_max_steps: 60 });
const MODELS = [{ id: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash' }, { id: 'gemini-3.7-flash', label: 'Gemini 3.7 Flash' }, { id: 'gemini-3.5-flash-lite', label: 'Gemini 3.5 Flash-Lite' }];
// 폴더 고르기(2026-10-19) 스텁 탐색기: 슈퍼라 처음 목록에 드라이브 + 허용 폴더 / the stub explorer for folder picking: drives plus allowed folders on top (super)
const TREE = { 'C:\\': ['Users', 'work'], 'C:\\work': ['repo', 'tmp'], 'C:\\work\\repo': [], 'C:\\work\\tmp': [] };
function browseReply(q, json) {
  if (!q) return json({ path: '', parent: '', roots: SETTINGS.allowed_folders, truncated: false, crumbs: [], allowed: false,
    entries: SETTINGS.allowed_folders.map(f => ({ name: f.split('\\').pop(), path: f })), drives: [{ name: 'C:\\', path: 'C:\\' }] });
  if (!TREE[q]) return json({ detail: '폴더가 없습니다' }, 404);
  const join = n => (q.endsWith('\\') ? q : q + '\\') + n;
  return json({ path: q, parent: q === 'C:\\' ? '' : (q.slice(0, q.lastIndexOf('\\')) || 'C:\\').replace(/^C:$/, 'C:\\'), entries: TREE[q].map(n => ({ name: n, path: join(n) })),
    truncated: false, crumbs: [], allowed: false });
}

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

// opts.agentic: 뷰애즈 사용자(7번)의 m_agentic 권한 / the view-as user's m_agentic permission
// opts.settings: 서버가 돌려줄 설정(기본 SETTINGS) / the settings the stub server returns (SETTINGS by default)
// opts.picker: 설정 응답에 folder_picker 를 싣는다(폴더 고르기, 2026-10-19) / the settings answer carries folder_picker (folder picking)
//   srv.pick = 다음 pick-folder 응답 { status, body, delay } · srv.picks = 받은 본문 · srv.browses = 받은 path
//   srv.pick = the next pick-folder reply { status, body, delay }; srv.picks = bodies received; srv.browses = paths received
async function app(t, opts) {
  opts = opts || {};
  const srv = { settings: JSON.parse(JSON.stringify(opts.settings || SETTINGS)), puts: [], pick: { status: 200, body: { cancelled: true } }, picks: [], browses: [] };
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => d.dismiss());
  t.after(async () => { await page.close(); assert.deepEqual(errors, []); });
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), p = decodeURIComponent(url.pathname), method = req.method();
    const json = (obj, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(obj) });
    if (url.origin !== ORIGIN) return route.abort();
    if (p === '/') return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: HTML });
    if (p === '/static/adapter.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: adapter });
    if (p === '/api/access/bootstrap') return json({ pvtree: [], groups: [], members: [MEMBER], teams: [] });
    if (p === '/api/access/effective/7') return json({ super: false, menus: { m_home: true, m_chat: true, m_admin: true, m_agentic: !!opts.agentic }, nodes: {}, mgmt: {}, read: {} });
    if (p === '/api/boards/notifications') return json({ unread: 0, notifications: [] });
    if (p === '/api/agentic/models') return json({ models: MODELS });
    const cap = opts.picker ? { folder_picker: true } : {};
    if (p === '/api/agentic/settings' && method === 'GET') return json(Object.assign({ settings: srv.settings, host: 'DEMO-PC' }, cap));
    if (p === '/api/agentic/settings' && method === 'PUT') { const body = JSON.parse(req.postData()); srv.puts.push(body); srv.settings = body.settings; return json(Object.assign({ settings: srv.settings, host: 'DEMO-PC' }, cap)); }
    if (p === '/api/agentic/pick-folder' && method === 'POST') {
      srv.picks.push(JSON.parse(req.postData()));
      const r = srv.pick;
      if (r.delay) await new Promise(res => setTimeout(res, r.delay));
      return json(r.body, r.status);
    }
    if (p === '/api/agentic/browse') { const q = url.searchParams.get('path') || ''; srv.browses.push(q); return browseReply(q, json); }
    return p.startsWith('/api/') ? json({ detail: 'stub' }, 404) : route.abort();
  });
  await page.goto(ORIGIN + '/');
  await page.waitForSelector('#viewHome.active .ai365-ca');
  page.srv = srv;
  return page;
}
const openCard = async page => {
  await page.click('#navPerm');
  await page.waitForSelector('#pgHubScroll .hub-card');
  await page.click('[data-hubcard="agentic"]');
  await page.waitForSelector('#pgAgenticScroll [data-agfolders] .ag-set-row');
};
const state = page => page.evaluate(() => ({
  visible: getComputedStyle(document.getElementById('pgAgenticScroll')).display !== 'none',
  folders: [...document.querySelectorAll('#agBody [data-agfolders] .ag-set-path')].map(e => e.textContent),
  perm: document.querySelector('#agBody [data-agf="default_perm"]').value, model: document.querySelector('#agBody [data-agf="default_model"]').value,
  modelOptions: [...document.querySelectorAll('#agBody [data-agf="default_model"] option')].map(o => o.textContent),
  deny: document.querySelector('#agBody [data-agf="deny_commands"]').value, steps: document.querySelector('#agBody [data-agb="max_steps"]').value,
  status: document.querySelector('#agFoot .ag-set-st').textContent, saveDisabled: document.querySelector('#agFoot [data-agsave]').disabled,
  disabledInputs: [...document.querySelectorAll('#agBody input, #agBody select, #agBody textarea')].filter(e => e.disabled).length,
  host: (document.querySelector('#agBody .ag-set-hint span[data-i18n-skip]') || {}).textContent }));
// 2차 탭 도우미 / phase 2 tab helpers
const tabs = page => page.$$eval('#agTabs [data-agtab]', els => els.map(b => [b.dataset.agtab, b.textContent, b.classList.contains('active'), b.getAttribute('aria-selected')]));
const panes = page => page.$$eval('#pgAgenticScroll [data-agpane]', els => els.map(p => [p.id, getComputedStyle(p).display !== 'none']));
const foot = page => page.evaluate(() => [getComputedStyle(document.getElementById('agFoot')).display, document.querySelector('#agFoot .ag-set-st').textContent, document.querySelector('#agFoot [data-agsave]').disabled]);
const cmdRows = (page, kind) => page.$$eval('[data-aglist="' + kind + '"] .ag-cmd-row', els => els.map(r => [r.querySelector('.ag-cmd-nm').textContent, r.querySelector('.ag-cmd-ds').textContent]));
const hookRows = page => page.$$eval('#agHookBody [data-aghook]', els => els.map(r => {
  const f = n => r.querySelector('[data-aghf="' + n + '"]');
  return [f('event').value, f('matcher').value, f('matcher').disabled, f('command').value, f('timeout_sec').value];
}));
const texts = (page, sel) => page.$$eval(sel, els => els.map(e => e.textContent));
// [저장] 을 누르고 '저장됨' 까지 기다린 뒤 마지막 PUT 본문 / click [Save], wait for 'saved' and return the last PUT body
async function save(page) {
  const n = page.srv.puts.length;
  await page.click('#agFoot [data-agsave]');
  await page.waitForFunction(() => document.querySelector('#agFoot .ag-set-st').textContent === '저장됨');
  assert.equal(page.srv.puts.length, n + 1);
  return page.srv.puts[n];
}

test('the hub shows the Agentic card in Work and AI settings, and the page renders the stored settings read from the server', async (t) => {
  const page = await app(t);
  await page.click('#navPerm');
  await page.waitForSelector('#pgHubScroll .hub-card');
  assert.deepEqual(await page.$eval('[data-hubcard="agentic"]', c => [c.closest('.hub-sec').querySelector('.hub-sec-tt').textContent, c.querySelector('.hub-card-tt').textContent, c.querySelector('.hub-card-ds').textContent]),
    ['업무 및 AI 설정', 'Agentic', 'Agentic 모드의 작업 폴더 · 권한 모드 · 모델 · 차단 명령 · 예산']);
  await page.click('[data-hubcard="agentic"]');
  await page.waitForSelector('#pgAgenticScroll [data-agfolders] .ag-set-row');
  const s = await state(page);
  assert.deepEqual([s.visible, s.folders, s.perm, s.model, s.modelOptions, s.deny, s.steps, s.status, s.saveDisabled, s.disabledInputs, s.host],
    [true, SETTINGS.allowed_folders, 'auto', 'gemini-3.8-flash', ['Gemini 3.8 Flash', 'Gemini 3.7 Flash', 'Gemini 3.5 Flash-Lite'], 'rm\\s+-rf\n\\bformat\\b', '200', '저장됨', true, 0, 'DEMO-PC']);
  assert.equal(await page.$eval('#pgAgenticScroll .pg-pagetitle', e => e.textContent), 'Agentic 설정');
  await page.click('#pgAgenticScroll .pg-crumb-sys');                                   // 관리 센터로 / back to the hub
  assert.deepEqual([await page.$eval('#pgAgenticScroll', e => getComputedStyle(e).display), await page.$eval('#pgHubScroll', e => getComputedStyle(e).display)], ['none', 'block']);
});

test('edits mark the page dirty and Save sends the whole settings object; a folder can be added and removed', async (t) => {
  const page = await app(t);
  await openCard(page);
  await page.fill('#agFolderIn', 'D:\\work\\repo');
  await page.press('#agFolderIn', 'Enter');
  let s = await state(page);
  assert.deepEqual([s.folders, s.status, s.saveDisabled], [SETTINGS.allowed_folders.concat(['D:\\work\\repo']), '저장하지 않은 변경', false]);
  await page.click('[data-agrm="0"]');
  assert.deepEqual((await state(page)).folders, ['C:\\Users\\demo\\Documents', 'D:\\work\\repo']);
  await page.selectOption('#agBody [data-agf="default_perm"]', 'ask');
  await page.selectOption('#agBody [data-agf="default_model"]', 'gemini-3.7-flash');
  await page.fill('#agBody [data-agb="max_steps"]', '300');
  await page.dispatchEvent('#agBody [data-agb="max_steps"]', 'change');
  await page.fill('#agBody [data-agf="deny_commands"]', 'rm\\s+-rf\nshutdown');
  await page.dispatchEvent('#agBody [data-agf="deny_commands"]', 'change');
  await page.click('#agFoot [data-agsave]');
  await page.waitForFunction(() => document.querySelector('#agFoot .ag-set-st').textContent === '저장됨');
  const put = page.srv.puts[0];
  assert.deepEqual([put.acting_user_id, put.settings.allowed_folders, put.settings.default_perm, put.settings.default_model, put.settings.deny_commands, put.settings.budgets.max_steps],
    ['', ['C:\\Users\\demo\\Documents', 'D:\\work\\repo'], 'ask', 'gemini-3.7-flash', ['rm\\s+-rf', 'shutdown'], 300]);
  s = await state(page);
  assert.deepEqual([s.perm, s.model, s.steps, s.saveDisabled], ['ask', 'gemini-3.7-flash', '300', true]);
});

test('a view-as user reads the page without saving, and the home pill follows the m_agentic menu permission', async (t) => {
  const page = await app(t, { agentic: false });
  await page.evaluate(() => AI365_setActingUser(7));
  await page.waitForFunction(() => window.AI365_EFFECTIVE && window.AI365_EFFECTIVE.menus && window.AI365_EFFECTIVE.menus.m_admin === true);
  // 알약 숨김 + Agentic 화면 거부 / the pill hides and the Agentic view is refused
  assert.equal(await page.$eval('#viewHome .ai365-ca', e => getComputedStyle(e).display), 'none');
  await page.evaluate(() => showView('work'));
  assert.deepEqual(await page.$$eval('main.main > .view.active', els => els.map(v => v.id)), ['viewHome']);
  await openCard(page);
  const s = await state(page);
  assert.deepEqual([s.status, s.saveDisabled, s.disabledInputs > 0], ['슈퍼 관리자만 저장할 수 있습니다.', true, true]);
  // 권한이 있는 사용자 / a user with the permission
  const ok = await app(t, { agentic: true });
  await ok.evaluate(() => AI365_setActingUser(7));
  await ok.waitForFunction(() => window.AI365_EFFECTIVE && window.AI365_EFFECTIVE.menus && window.AI365_EFFECTIVE.menus.m_agentic === true);
  assert.notEqual(await ok.$eval('#viewHome .ai365-ca', e => getComputedStyle(e).display), 'none');
  await ok.click('#viewHome [data-ca="agentic"]');
  assert.deepEqual(await ok.$$eval('main.main > .view.active', els => els.map(v => v.id)), ['viewWork']);
});

test('English labels on the card and the page', async (t) => {
  const page = await app(t);
  await page.click('#ai365-lang-toggle');
  await page.waitForFunction(() => document.getElementById('homeInput').placeholder === 'How can I help you?');
  await openCard(page);
  assert.deepEqual([await page.$eval('[data-hubcard="agentic"] .hub-card-ds', e => e.textContent), await page.$eval('#pgAgenticScroll .pg-pagetitle', e => e.textContent),
    await page.$$eval('#agBody .ag-set-tt', els => els.map(e => e.textContent)), await page.$eval('#agFoot [data-agsave]', e => e.textContent)],
    ['Folders, permission mode, model, denied commands and budgets of Agentic mode', 'Agentic settings', ['Allowed folders', 'Default', 'Denied commands (one regular expression per line)', 'Budgets'], 'Save']);
});

/* ── 2차 탭(2026-10-19) / phase 2 tabs ── */
const PANE_NOTE = '작업 폴더의 .ai365/commands/*.md · .ai365/skills/<이름>/SKILL.md 도 같은 이름 규칙으로 읽습니다(폴더 것이 우선).';
const HOOK_HINT = '폴더의 .ai365/hooks.json 훅은 세션 첫 실행 때 승인을 묻습니다. 종료 코드 2 = 차단, 표준 출력 마지막 줄이 JSON 이면 {decision, reason, add_context} 로 읽습니다. 훅은 작업 폴더에서 실행됩니다.';

test('three tabs switch the panes under one shared footer, and entering the page again starts on Settings', async (t) => {
  const page = await app(t);
  await openCard(page);
  assert.deepEqual(await tabs(page), [['settings', '설정', true, 'true'], ['commands', '명령 · 스킬', false, 'false'], ['hooks', '훅', false, 'false']]);
  assert.deepEqual(await panes(page), [['agBody', true], ['agCmdBody', false], ['agHookBody', false]]);
  assert.deepEqual(await foot(page), ['flex', '저장됨', true]);
  await page.click('#agTabs [data-agtab="commands"]');
  assert.deepEqual(await panes(page), [['agBody', false], ['agCmdBody', true], ['agHookBody', false]]);
  assert.deepEqual((await tabs(page)).map(x => [x[2], x[3]]), [[false, 'false'], [true, 'true'], [false, 'false']]);
  assert.deepEqual([await texts(page, '#agCmdBody .ag-set-tt'), await page.$eval('#agCmdBody .ag-pane-note', e => e.textContent), (await foot(page))[0]],
    [['전역 명령', '전역 스킬'], PANE_NOTE, 'flex']);
  await page.click('#agTabs [data-agtab="hooks"]');
  assert.deepEqual(await panes(page), [['agBody', false], ['agCmdBody', false], ['agHookBody', true]]);
  assert.deepEqual((await tabs(page)).map(x => [x[2], x[3]]), [[false, 'false'], [false, 'false'], [true, 'true']]);
  assert.deepEqual([await texts(page, '#agHookBody .ag-set-tt'), (await texts(page, '#agHookBody .ag-set-hint')).includes(HOOK_HINT), (await foot(page))[0]], [['전역 훅'], true, 'flex']);
  // 관리 센터로 나갔다 다시 들어오면 설정 탭부터 / leaving to the hub and coming back starts on Settings
  await page.click('#pgAgenticScroll .pg-crumb-sys');
  await page.click('[data-hubcard="agentic"]');
  await page.waitForSelector('#pgAgenticScroll [data-agfolders] .ag-set-row');
  assert.deepEqual(await panes(page), [['agBody', true], ['agCmdBody', false], ['agHookBody', false]]);
  assert.deepEqual((await tabs(page)).map(x => x[2]), [true, false, false]);
});

test('a command is added through the edit card and goes out with Save; a bad, built-in or duplicate name and an empty body are refused before saving', async (t) => {
  const page = await app(t);
  await openCard(page);
  await page.click('#agTabs [data-agtab="commands"]');
  assert.deepEqual([await cmdRows(page, 'commands'), await texts(page, '[data-agcmd="0"] button')], [[['/review', '변경 검토']], ['수정', '삭제']]);
  await page.click('[data-agcadd="commands"]');
  const form = '#agCmdBody [data-agcform="commands"]';
  await page.waitForSelector(form);
  assert.equal(await page.evaluate(() => document.activeElement.dataset.agcf), 'name');   // 이름 칸에 초점 / the name field has focus
  assert.ok((await texts(page, form + ' .ag-set-hint')).includes('$ARGUMENTS 자리에 사용자가 적은 인자가 들어갑니다.'));
  const tryOk = async (name, body) => {
    await page.fill(form + ' [data-agcf="name"]', name);
    await page.fill(form + ' [data-agcf="body"]', body);
    await page.click(form + ' [data-agcok]');
    return page.$eval('#agCmdBody [data-agcerr]', e => e.hidden ? '' : e.textContent);
  };
  assert.equal(await tryOk('', '본문'), '이름을 입력하세요.');
  assert.equal(await tryOk('Fix Bug', '본문'), '이름이 규칙에 맞지 않습니다.');
  assert.equal(await tryOk('-fix', '본문'), '이름이 규칙에 맞지 않습니다.');
  assert.equal(await tryOk('help', '본문'), '내장 명령과 같은 이름은 쓸 수 없습니다.');
  assert.equal(await tryOk('review', '본문'), '같은 이름이 이미 있습니다.');
  assert.equal(await tryOk('fix-bug', '   '), '본문을 입력하세요.');
  // 거절은 제자리 표시: 입력은 그대로, 목록은 그대로, 발치는 '확인하지 않은 편집' / refusals show in place: the typed values and the list stay, the footer says unconfirmed edit
  assert.deepEqual([await page.$eval(form + ' [data-agcf="name"]', e => e.value), (await foot(page)).slice(1), page.srv.puts.length, (await cmdRows(page, 'commands')).length],
    ['fix-bug', ['확인하지 않은 편집', false], 0, 1]);
  await page.fill(form + ' [data-agcf="name"]', 'fix-bug');                                // 다시 쓰면 오류가 사라진다 / typing again clears the error
  assert.equal(await page.$eval('#agCmdBody [data-agcerr]', e => e.hidden), true);
  await page.fill(form + ' [data-agcf="description"]', '버그 수정');
  await page.fill(form + ' [data-agcf="body"]', '$ARGUMENTS 버그를 재현하고 고친 뒤 테스트를 돌려라');
  await page.click(form + ' [data-agcok]');
  assert.equal(await page.$(form), null);
  assert.deepEqual([await cmdRows(page, 'commands'), (await foot(page)).slice(1)], [[['/review', '변경 검토'], ['/fix-bug', '버그 수정']], ['저장하지 않은 변경', false]]);
  const put = await save(page);
  assert.deepEqual(put.settings.commands, [SETTINGS.commands[0], { name: 'fix-bug', description: '버그 수정', body: '$ARGUMENTS 버그를 재현하고 고친 뒤 테스트를 돌려라' }]);
  assert.deepEqual([put.settings.skills, put.settings.hooks, put.settings.allowed_folders], [[], SETTINGS.hooks, SETTINGS.allowed_folders]);   // 다른 키도 함께 / the other keys go along
  assert.deepEqual(await cmdRows(page, 'commands'), [['/review', '변경 검토'], ['/fix-bug', '버그 수정']]);   // 서버 응답으로 다시 그림 / redrawn from the server answer
});

test('skills are added, edited, cancelled and removed; built-in names are refused for skills too, and Save sends settings.skills', async (t) => {
  const page = await app(t);
  await openCard(page);
  await page.click('#agTabs [data-agtab="commands"]');
  assert.equal(await page.$eval('[data-aglist="skills"]', e => e.textContent), '등록한 스킬이 없습니다.');
  const form = '#agCmdBody [data-agcform="skills"]', BODY = '\n# 릴리스 노트\n1. git log 를 읽는다\n2. 변경을 묶어 정리한다';
  const add = async (name, description, body) => {
    await page.click('[data-agcadd="skills"]');
    await page.fill(form + ' [data-agcf="name"]', name);
    await page.fill(form + ' [data-agcf="description"]', description);
    await page.fill(form + ' [data-agcf="body"]', body);
    await page.click(form + ' [data-agcok]');
  };
  await page.click('[data-agcadd="skills"]');
  assert.equal((await texts(page, form + ' .ag-set-hint')).some(s => s.includes('$ARGUMENTS')), false);   // 스킬엔 $ARGUMENTS 안내가 없다 / no $ARGUMENTS note for skills
  await page.click(form + ' [data-agccancel]');
  assert.equal(await page.$(form), null);
  await add('release-notes', '릴리스 노트 작성', BODY);
  await add('commit', '', '커밋 전에 변경을 요약한다');                                 // 스킬도 내장 이름은 못 쓴다(서버와 같은 규칙) / skills cannot take built-in names either (the server's rule)
  assert.equal(await page.$eval('#agCmdBody [data-agcerr]', e => e.textContent), '내장 명령과 같은 이름은 쓸 수 없습니다.');
  await page.fill(form + ' [data-agcf="name"]', 'commit-summary');
  await page.click(form + ' [data-agcok]');
  assert.deepEqual(await cmdRows(page, 'skills'), [['release-notes', '릴리스 노트 작성'], ['commit-summary', '']]);
  // 고치다 취소하면 그대로(첫 빈 줄도 남는다) / editing then cancelling changes nothing (the leading blank line survives)
  await page.click('[data-agcedit="skills:0"]');
  assert.deepEqual([await page.$eval(form + ' [data-agcf="name"]', e => e.value), await page.$eval(form + ' [data-agcf="body"]', e => e.value), await page.$eval('[data-agskill="0"]', e => e.classList.contains('on'))],
    ['release-notes', BODY, true]);
  await page.fill(form + ' [data-agcf="description"]', '바뀐 설명');
  await page.click(form + ' [data-agccancel]');
  assert.deepEqual(await cmdRows(page, 'skills'), [['release-notes', '릴리스 노트 작성'], ['commit-summary', '']]);
  // 고치고 확인(자기 이름은 중복이 아니다) / edit and confirm (its own name is not a duplicate)
  await page.click('[data-agcedit="skills:0"]');
  await page.fill(form + ' [data-agcf="description"]', '릴리스 노트 초안');
  await page.click(form + ' [data-agcok]');
  // 다른 스킬 이름으로 바꾸면 중복 / renaming onto another skill is a duplicate
  await page.click('[data-agcedit="skills:1"]');
  await page.fill(form + ' [data-agcf="name"]', 'release-notes');
  await page.click(form + ' [data-agcok]');
  assert.equal(await page.$eval('#agCmdBody [data-agcerr]', e => e.textContent), '같은 이름이 이미 있습니다.');
  await page.click(form + ' [data-agccancel]');
  await page.click('[data-agcrm="skills:1"]');
  assert.deepEqual(await cmdRows(page, 'skills'), [['release-notes', '릴리스 노트 초안']]);
  const put = await save(page);
  assert.deepEqual([put.settings.skills, put.settings.commands], [[{ name: 'release-notes', description: '릴리스 노트 초안', body: BODY }], SETTINGS.commands]);
});

test('hooks are edited in place: a tool-less event clears and locks the matcher, the timeout stays within 1..600, and Save sends settings.hooks', async (t) => {
  const page = await app(t);
  await openCard(page);
  await page.click('#agTabs [data-agtab="hooks"]');
  assert.deepEqual(await hookRows(page), [['pre_tool', 'bash', false, 'python hooks/check.py', '30']]);
  assert.deepEqual(await texts(page, '#agHookBody .ag-hook-head span'), ['이벤트', '도구 이름(정규식)', '명령', '시간 제한(초)', '']);
  assert.deepEqual(await page.$$eval('[data-aghook="0"] [data-aghf="event"] option', els => els.map(o => [o.value, o.textContent])),
    [['session_start', '세션 시작 (session_start)'], ['user_prompt', '요청 받음 (user_prompt)'], ['pre_tool', '도구 실행 전 (pre_tool)'], ['post_tool', '도구 실행 뒤 (post_tool)'], ['stop', '턴 끝 (stop)']]);
  await page.click('[data-aghadd]');
  assert.deepEqual(await hookRows(page), [['pre_tool', 'bash', false, 'python hooks/check.py', '30'], ['pre_tool', '', false, '', '60']]);
  assert.deepEqual([await page.evaluate(() => document.activeElement.dataset.aghf), ...(await foot(page)).slice(1)], ['command', '저장하지 않은 변경', false]);
  const r0 = f => '[data-aghook="0"] [data-aghf="' + f + '"]', r1 = f => '[data-aghook="1"] [data-aghf="' + f + '"]';
  await page.fill(r1('matcher'), 'edit_file');
  await page.selectOption(r1('event'), 'session_start');                       // 도구 없는 이벤트 = matcher 비우고 잠금 / a tool-less event clears and locks the matcher
  await page.fill(r1('command'), 'python hooks/start.py');
  await page.fill(r1('timeout_sec'), '900');
  await page.dispatchEvent(r1('timeout_sec'), 'change');                     // 범위 밖은 되돌린다 / out of range snaps back
  assert.deepEqual((await hookRows(page))[1], ['session_start', '', true, 'python hooks/start.py', '60']);
  await page.fill(r1('timeout_sec'), '15');
  await page.click('[data-aghadd]');                                           // 칸을 고친 채 칸 안의 버튼도 첫 클릭에 / a pane button works on the first click right after typing
  assert.equal((await hookRows(page)).length, 3);
  await page.click('[data-aghrm="2"]');
  assert.equal((await hookRows(page)).length, 2);
  await page.fill(r0('matcher'), 'bash|edit_file');
  await page.selectOption(r0('event'), 'post_tool');                           // 도구 이벤트끼리는 matcher 유지 / between tool events the matcher stays
  // 칸을 고친 채 바로 [저장]: 첫 클릭이 먹혀야 한다 / Save right after typing: the first click must land
  await page.fill(r0('command'), 'python hooks/after.py');
  const put = await save(page);
  assert.deepEqual(put.settings.hooks, [
    { event: 'post_tool', matcher: 'bash|edit_file', command: 'python hooks/after.py', timeout_sec: 30 },
    { event: 'session_start', matcher: '', command: 'python hooks/start.py', timeout_sec: 15 }]);
  assert.deepEqual(put.settings.commands, SETTINGS.commands);
  assert.deepEqual(await hookRows(page), [['post_tool', 'bash|edit_file', false, 'python hooks/after.py', '30'], ['session_start', '', true, 'python hooks/start.py', '15']]);
});

test('the three new budgets and notify_default sit in the settings tab and go out with Save; a response without the new keys is filled with defaults', async (t) => {
  const page = await app(t);
  await openCard(page);
  assert.deepEqual((await page.$$eval('#agBody [data-agb]', els => els.map(e => [e.dataset.agb, e.closest('.ag-set-row').querySelector('.ag-set-lb').textContent, e.value]))).slice(5),
    [['compact_pct', '컨텍스트 압축 임계(%)', '80'], ['max_subagents', '동시 서브에이전트', '3'], ['subagent_max_steps', '서브에이전트 최대 스텝', '60']]);
  assert.deepEqual(await page.$eval('#agBody [data-agf="notify_default"]', e => [e.type, e.checked, e.closest('.bl-card').querySelector('.ag-set-tt').textContent, document.querySelector('#agBody label[for="agNotifyDef"]').textContent]),
    ['checkbox', false, '기본값', '새 세션 완료 알림 기본값']);
  for (const [k, v] of [['compact_pct', '70'], ['max_subagents', '5'], ['subagent_max_steps', '120']]) {
    await page.fill('#agBody [data-agb="' + k + '"]', v);
    await page.dispatchEvent('#agBody [data-agb="' + k + '"]', 'change');
  }
  await page.click('#agBody label[for="agNotifyDef"]');                         // 글자를 눌러도 켜진다 / clicking the label toggles it
  assert.equal(await page.$eval('#agNotifyDef', e => e.checked), true);
  const put = await save(page);
  assert.deepEqual([put.settings.budgets, put.settings.notify_default], [Object.assign({}, SETTINGS.budgets, { compact_pct: 70, max_subagents: 5, subagent_max_steps: 120 }), true]);
  assert.equal(await page.$eval('#agNotifyDef', e => e.checked), true);
  // 새 키가 없는 응답도 기본값으로 채운다 / a response without the new keys is filled with defaults
  const old = await app(t, { settings: NO_NEW_KEYS });
  await openCard(old);
  assert.deepEqual([await old.$eval('#agBody [data-agb="compact_pct"]', e => e.value), await old.$eval('#agNotifyDef', e => e.checked)], ['', false]);
  await old.selectOption('#agBody [data-agf="default_perm"]', 'ask');
  const p2 = await save(old);
  assert.deepEqual([p2.settings.commands, p2.settings.skills, p2.settings.hooks, p2.settings.notify_default, p2.settings.budgets], [[], [], [], false, NO_NEW_KEYS.budgets]);
  await old.click('#agTabs [data-agtab="commands"]');
  assert.deepEqual([await old.$eval('[data-aglist="commands"]', e => e.textContent), await old.$eval('[data-aglist="skills"]', e => e.textContent)], ['등록한 명령이 없습니다.', '등록한 스킬이 없습니다.']);
  await old.click('#agTabs [data-agtab="hooks"]');
  assert.deepEqual([await old.$eval('[data-aghooks]', e => e.textContent), await old.$('#agHookBody .ag-hook-head')], ['등록한 훅이 없습니다.', null]);
});

test('a view-as user browses the three tabs with every field and button disabled', async (t) => {
  const page = await app(t);
  await page.evaluate(() => AI365_setActingUser(7));
  await page.waitForFunction(() => window.AI365_EFFECTIVE && window.AI365_EFFECTIVE.menus && window.AI365_EFFECTIVE.menus.m_admin === true);
  await openCard(page);
  const dis = sel => page.$$eval(sel, els => els.map(e => e.disabled));
  assert.deepEqual(await dis('#agBody [data-agf="notify_default"], #agBody [data-agb="compact_pct"], #agBody [data-agb="max_subagents"], #agBody [data-agb="subagent_max_steps"]'), [true, true, true, true]);
  await page.click('#agTabs [data-agtab="commands"]');
  const c = await dis('#agCmdBody button, #agCmdBody input, #agCmdBody textarea');
  assert.deepEqual([c.length, c.every(Boolean)], [4, true]);                       // [수정] [삭제] [명령 추가] [스킬 추가] / edit, delete, add command, add skill
  await page.click('#agTabs [data-agtab="hooks"]');
  const h = await dis('#agHookBody button, #agHookBody input, #agHookBody select');
  assert.deepEqual([h.length, h.every(Boolean)], [6, true]);                       // 이벤트 · matcher · 명령 · 시간 제한 · [삭제] · [훅 추가] / event, matcher, command, timeout, delete, add hook
  assert.deepEqual((await foot(page)).slice(1), ['슈퍼 관리자만 저장할 수 있습니다.', true]);
});

test('English labels on the tabs, the new settings, the commands tab with its edit card and the hooks tab, and back to Korean', async (t) => {
  const page = await app(t);
  await page.click('#ai365-lang-toggle');
  await page.waitForFunction(() => document.getElementById('homeInput').placeholder === 'How can I help you?');
  await openCard(page);
  assert.deepEqual([(await tabs(page)).map(x => x[1]), (await foot(page)).slice(1)], [['Settings', 'Commands and skills', 'Hooks'], ['All changes saved', true]]);
  const lbs = await texts(page, '#agBody .ag-set-lb');
  assert.deepEqual([lbs.slice(-3), lbs.includes('Completion notices on for new sessions'), await texts(page, '#agBody [data-agf="default_perm"] option')],
    [['Context compaction threshold (%)', 'Concurrent subagents', 'Max steps per subagent'], true, ['Auto', 'Ask', 'Plan']]);
  // 범위 알림은 언어별로 만든다 / the range note is built per language
  await page.fill('#agBody [data-agb="compact_pct"]', '100');
  await page.locator('#agBody [data-agb="compact_pct"]').blur();
  assert.deepEqual([await page.$eval('#agBody [data-agb="compact_pct"]', e => e.value), await page.$eval('#agBody [data-agb="compact_pct"] + [data-agnumtip]', e => e.hidden ? '' : e.textContent),
    (await foot(page)).slice(1)], ['80', 'Enter a value from 30 to 95', ['Unsaved changes', false]]);
  await page.click('#agTabs [data-agtab="commands"]');
  assert.deepEqual([await texts(page, '#agCmdBody .ag-set-tt'), await texts(page, '#agCmdBody .ag-set-hint')], [['Global commands', 'Global skills'], [
    'Commands and skills in the working folder (.ai365/commands/*.md, .ai365/skills/<name>/SKILL.md) are read with the same name rule, and the folder ones win.',
    'Prompt templates called with /name in the input line. They apply to every session.',
    'Work instructions the agent reads and follows when needed. /name applies one directly.', 'No skills yet.']]);
  assert.deepEqual([await texts(page, '[data-agcmd="0"] button'), await texts(page, '#agCmdBody .ag-cmd-add button'), await cmdRows(page, 'commands')],
    [['Edit', 'Delete'], ['Add command', 'Add skill'], [['/review', '변경 검토']]]);           // 이름 · 설명은 데이터 그대로 / names and descriptions stay as data
  await page.click('[data-agcadd="commands"]');
  const form = '#agCmdBody [data-agcform="commands"]';
  assert.deepEqual([await texts(page, form + ' .ag-set-lb'), await page.$$eval(form + ' input', els => els.map(e => e.placeholder)), await texts(page, form + ' .ag-set-hint'), await texts(page, form + ' button')],
    [['Name', 'Description', 'Body'], ['e.g. review', 'One-line description'],
      ['Lowercase letters, digits, _ and -, up to 40 characters (starting with a letter or digit)', '$ARGUMENTS is replaced with the arguments the user typed.'], ['Cancel', 'Confirm']]);
  await page.fill(form + ' [data-agcf="name"]', 'Bad');
  await page.fill(form + ' [data-agcf="body"]', 'x');
  await page.click(form + ' [data-agcok]');
  assert.deepEqual([await page.$eval('#agCmdBody [data-agcerr]', e => e.textContent), (await foot(page)).slice(1)], ['The name does not follow the rule.', ['Unconfirmed edit', false]]);
  await page.click('#agTabs [data-agtab="hooks"]');
  assert.deepEqual([await texts(page, '#agHookBody .ag-set-tt'), await texts(page, '#agHookBody .ag-hook-head span'), await texts(page, '[data-aghook="0"] option'),
    await page.$$eval('[data-aghook="0"] input[placeholder]', els => els.map(e => e.placeholder)), await texts(page, '#agHookBody button'), await texts(page, '#agHookBody .ag-set-hint')],
    [['Global hooks'], ['Event', 'Tool name (regex)', 'Command', 'Time limit (seconds)', ''],
      ['Session start (session_start)', 'Prompt received (user_prompt)', 'Before a tool (pre_tool)', 'After a tool (post_tool)', 'Turn end (stop)'],
      ['Empty means every tool', 'Command to run'], ['Delete', 'Add hook'],
      ['The tool name regex applies to the before and after tool hooks only.',
        'Hooks in the folder’s .ai365/hooks.json ask for approval on the session’s first run. Exit code 2 blocks, and when the last line of standard output is JSON it is read as {decision, reason, add_context}. Hooks run in the working folder.']]);
  await page.fill('[data-aghook="0"] [data-aghf="command"]', 'python hooks/x.py');   // 확인 안 한 카드가 있는 동안 발치는 그 상태 / while a card is unconfirmed the footer says so
  assert.deepEqual((await foot(page)).slice(1), ['Unconfirmed edit', false]);
  // 어댑터 관찰자의 40ms 지연 EN 번역이 끝난 뒤 전환(사람은 입력 40ms 안에 토글을 누르지 못한다). 칸을 벗어날 때(change) 발치가 다시 쓰이지 않아야 KO 가 유지된다
  // Toggle after the adapter observer's 40 ms EN pass (a person cannot toggle within 40 ms of typing). The field exit (change) must not rewrite the footer, or KO is lost
  await page.waitForTimeout(120);
  // 한국어로 되돌리면 역방향 사전으로 원문 / back to Korean through the reverse map
  await page.click('#ai365-lang-toggle');
  await page.waitForFunction(() => document.querySelector('#agTabs [data-agtab="settings"]').textContent === '설정');
  assert.deepEqual([(await tabs(page)).map(x => x[1]), await texts(page, '#agHookBody .ag-set-tt'), await texts(page, '[data-agcmd="0"] button'), await page.$eval('#agCmdBody [data-agcerr]', e => e.textContent),
    (await foot(page))[1]], [['설정', '명령 · 스킬', '훅'], ['전역 훅'], ['수정', '삭제'], '이름이 규칙에 맞지 않습니다.', '확인하지 않은 편집']);
});

/* ── 적대 검토 반영(2026-10-19): M1 확인 안 한 편집 카드 · L3 플랜 기본값 · L4 숫자 범위와 빈 훅 명령 / review fixes: unconfirmed card, Plan default, number ranges and empty hook commands ── */
test('Save confirms a typed edit card first: the command goes out with the PUT and the card closes; a bad name blocks the save with the card error; an untouched card just closes', async (t) => {
  const page = await app(t);
  await openCard(page);
  await page.click('#agTabs [data-agtab="commands"]');
  await page.click('[data-agcadd="commands"]');
  const form = '#agCmdBody [data-agcform="commands"]';
  assert.deepEqual((await foot(page)).slice(1), ['저장됨', true]);                                 // 열기만 해서는 그대로 / opening alone changes nothing
  await page.fill(form + ' [data-agcf="name"]', 'Bad Name');
  await page.fill(form + ' [data-agcf="body"]', '$ARGUMENTS 를 배포하라');
  assert.deepEqual((await foot(page)).slice(1), ['확인하지 않은 편집', false]);
  // 다른 탭에서 저장해도 막고 명령 탭의 그 카드에 오류 / Save from another tab is refused and the commands tab shows the card's error
  await page.click('#agTabs [data-agtab="settings"]');
  await page.click('#agFoot [data-agsave]');
  assert.deepEqual([page.srv.puts.length, (await panes(page))[1][1], await page.$eval('#agCmdBody [data-agcerr]', e => e.hidden ? '' : e.textContent), await page.evaluate(() => document.activeElement.dataset.agcf)],
    [0, true, '이름이 규칙에 맞지 않습니다.', 'name']);
  await page.fill(form + ' [data-agcf="name"]', 'deploy');
  const put = await save(page);
  assert.deepEqual(put.settings.commands, [SETTINGS.commands[0], { name: 'deploy', description: '', body: '$ARGUMENTS 를 배포하라' }]);
  assert.deepEqual([await page.$(form), await cmdRows(page, 'commands')], [null, [['/review', '변경 검토'], ['/deploy', '']]]);
  // 손대지 않은 카드는 저장 때 닫히기만 한다 / an untouched card just closes on Save
  await page.click('[data-agcedit="commands:0"]');
  await page.click('#agTabs [data-agtab="settings"]');
  await page.selectOption('#agBody [data-agf="default_perm"]', 'ask');
  const p2 = await save(page);
  assert.deepEqual([p2.settings.default_perm, p2.settings.commands, await page.$(form)], ['ask', put.settings.commands, null]);
});

test('the default permission mode offers Plan; a stored plan stays selected and each choice goes out with Save', async (t) => {
  const page = await app(t, { settings: Object.assign({}, SETTINGS, { default_perm: 'plan' }) });
  await openCard(page);
  const sel = '#agBody [data-agf="default_perm"]';
  assert.deepEqual(await page.$$eval(sel + ' option', els => els.map(o => [o.value, o.textContent, o.selected])),
    [['auto', '자동(Auto)', false], ['ask', '묻기', false], ['plan', '플랜(Plan)', true]]);
  await page.selectOption(sel, 'auto');
  assert.equal((await save(page)).settings.default_perm, 'auto');
  await page.selectOption(sel, 'plan');
  assert.equal((await save(page)).settings.default_perm, 'plan');
  assert.equal(await page.$eval(sel, e => e.value), 'plan');
});

test('number fields follow the server ranges: an out-of-range value, even typed key by key, snaps back to its value on entry with a brief range note', async (t) => {
  const page = await app(t);
  await openCard(page);
  assert.deepEqual(await page.$$eval('#agBody [data-agb]', els => els.map(e => [e.dataset.agb, e.min, e.max])), [
    ['max_steps', '1', '10000'], ['max_minutes', '1', '1440'], ['max_sessions', '1', '20'], ['bash_timeout_sec', '1', '600'], ['max_output_chars', '1000', '200000'],
    ['compact_pct', '30', '95'], ['max_subagents', '1', '8'], ['subagent_max_steps', '5', '500']]);
  const field = k => '#agBody [data-agb="' + k + '"]', note = k => field(k) + ' + [data-agnumtip]';
  const shown = sel => page.$eval(sel, e => e.hidden ? '' : e.textContent);
  await page.fill(field('compact_pct'), '100');
  await page.locator(field('compact_pct')).blur();
  assert.deepEqual([await page.$eval(field('compact_pct'), e => e.value), await shown(note('compact_pct'))], ['80', '30~95 사이로 입력하세요']);
  await page.fill(field('max_output_chars'), '999');
  await page.locator(field('max_output_chars')).blur();
  assert.deepEqual([await page.$eval(field('max_output_chars'), e => e.value), await shown(note('max_output_chars'))], ['20000', '1,000~200,000 사이로 입력하세요']);
  await page.waitForFunction(() => document.querySelector('#agBody [data-agb="compact_pct"] + [data-agnumtip]').hidden, null, { timeout: 6000 });   // 잠깐 뒤 사라진다 / it fades after a moment
  await page.fill(field('compact_pct'), '90');
  await page.locator(field('compact_pct')).blur();
  // 훅 시간 제한: 900 을 한 글자씩 쳐도 앞자리 90 이 아니라 들어올 때 값 30 으로 / hook timeout: 900 typed key by key snaps back to 30 on entry, not the valid prefix 90
  await page.click('#agTabs [data-agtab="hooks"]');
  const to = '[data-aghook="0"] [data-aghf="timeout_sec"]';
  await page.fill(to, '');
  await page.locator(to).pressSequentially('900');
  await page.locator(to).blur();
  assert.deepEqual([await page.$eval(to, e => [e.min, e.max, e.value]), await shown('[data-aghook="0"] [data-agnumtip]')], [['1', '600', '30'], '1~600 사이로 입력하세요']);
  await page.fill(to, '45');
  await page.locator(to).blur();
  const put = await save(page);
  assert.deepEqual([put.settings.budgets.compact_pct, put.settings.budgets.max_output_chars, put.settings.hooks[0].timeout_sec], [90, 20000, 45]);
});

test('Save refuses a hook without a command: the hooks tab opens on that row with its error and focus, and typing clears it', async (t) => {
  const page = await app(t);
  await openCard(page);
  await page.click('#agTabs [data-agtab="hooks"]');
  await page.click('[data-aghadd]');
  await page.click('#agTabs [data-agtab="settings"]');
  await page.click('#agFoot [data-agsave]');
  const err = '[data-aghook="1"] [data-aghookerr]';
  assert.deepEqual([page.srv.puts.length, (await panes(page))[2][1], await page.$eval(err, e => e.hidden ? '' : e.textContent),
    await page.evaluate(() => document.activeElement.dataset.aghf + ':' + document.activeElement.closest('[data-aghook]').dataset.aghook)],
    [0, true, '명령이 비어 있습니다.', 'command:1']);
  await page.fill('[data-aghook="1"] [data-aghf="command"]', 'echo ok');
  assert.equal(await page.$eval(err, e => e.hidden), true);
  const put = await save(page);
  assert.deepEqual(put.settings.hooks, [SETTINGS.hooks[0], { event: 'pre_tool', matcher: '', command: 'echo ok', timeout_sec: 60 }]);
});

/* ── 폴더 고르기(2026-10-19): [찾아보기] = 서버 PC 의 폴더 선택 창, 503 이면 입력칸 아래 작은 탐색기 / folder picking: [Browse] opens the server
   PC's folder window; a 503 opens the small explorer under the field ── */
const pickState = page => page.evaluate(() => {
  const b = document.querySelector('#agBody [data-agpick]'), h = document.querySelector('#agBody [data-agpickhint]');
  return { disabled: b.disabled, hint: h.hidden ? '' : h.textContent, value: document.getElementById('agFolderIn').value };
});
const browseRows = page => page.$$eval('#agBody [data-agbrowse] [data-agbdir]', els => els.map(e => e.textContent));

test('[Browse] waits for the server folder window and fills the field (Add adds it); a cancel keeps the field, a busy window toasts; no picker means no button', async (t) => {
  const page = await app(t, { picker: true });
  await openCard(page);
  assert.deepEqual([await page.$eval('#agBody [data-agpick]', b => [b.textContent, b.disabled, b.previousElementSibling.id, b.nextElementSibling.dataset.agadd]),
    await page.$eval('#agBody [data-agbrowse]', e => e.hidden)], [['찾아보기', false, 'agFolderIn', ''], true]);
  page.srv.pick = { status: 200, body: { path: 'D:\\work\\repo', cancelled: false, allowed: false }, delay: 500 };
  await page.click('#agBody [data-agpick]');
  assert.deepEqual(await pickState(page), { disabled: true, hint: '폴더 선택 창을 열었습니다. 창이 보이지 않으면 작업 표시줄을 확인하세요', value: '' });   // 기다리는 동안 / while waiting
  await page.waitForFunction(() => document.getElementById('agFolderIn').value === 'D:\\work\\repo');
  assert.deepEqual(await pickState(page), { disabled: false, hint: '', value: 'D:\\work\\repo' });
  assert.deepEqual([page.srv.picks, await page.evaluate(() => document.activeElement.id), (await foot(page)).slice(1)],
    [[{ acting_user_id: '', start: '', title: '허용할 폴더 선택' }], 'agFolderIn', ['저장됨', true]]);   // 채우기만, 추가는 [추가] / fill only; [Add] adds
  page.srv.pick = { status: 200, body: { cancelled: true } };
  await page.click('#agBody [data-agpick]');
  await page.waitForFunction(() => !document.querySelector('#agBody [data-agpick]').disabled);
  assert.deepEqual([(await pickState(page)).value, page.srv.picks[1].start], ['D:\\work\\repo', 'D:\\work\\repo']);   // 칸의 값이 시작 폴더 / the field is the start
  page.srv.pick = { status: 409, body: { detail: '이미 폴더 선택 창이 열려 있습니다' } };
  await page.click('#agBody [data-agpick]');
  await page.waitForFunction(() => (document.getElementById('toast') || {}).textContent === '이미 폴더 선택 창이 열려 있습니다');
  assert.equal(await page.$eval('#agBody [data-agbrowse]', e => e.hidden), true);
  await page.click('#agBody [data-agadd]');
  assert.deepEqual([(await state(page)).folders, (await foot(page)).slice(1)], [SETTINGS.allowed_folders.concat(['D:\\work\\repo']), ['저장하지 않은 변경', false]]);
  assert.equal((await save(page)).settings.allowed_folders.pop(), 'D:\\work\\repo');
  // folder_picker 가 없는 서버(기본 스텁) = 버튼 없음 / a server without folder_picker (the default stub) shows no button
  const old = await app(t);
  await openCard(old);
  assert.deepEqual([await old.$('#agBody [data-agpick]'), await old.$('#agBody [data-agbrowse]')], [null, null]);
});

test('a 503 opens the small explorer under the field, drives first: rows enter, Up goes back, Select fills the field, Close hides it; view-as users get a disabled button', async (t) => {
  const page = await app(t, { picker: true });
  await openCard(page);
  page.srv.pick = { status: 503, body: { detail: '폴더 선택 창을 띄울 수 없습니다' } };
  await page.click('#agBody [data-agpick]');
  await page.waitForSelector('#agBody [data-agbrowse]:not([hidden]) [data-agbdir]');
  assert.deepEqual([await texts(page, '#agBody [data-agbrowse] .ag-bgrp'), await browseRows(page), await page.$eval('#agBody [data-agbrowse] .ag-bpath', e => e.textContent),
    await page.$eval('[data-agbup]', b => b.disabled), await page.$eval('[data-agbok]', b => b.disabled), page.srv.browses],
  [['드라이브', '허용 폴더'], ['C:\\', 'Desktop', 'Documents'], '폴더 고르기', true, true, ['']]);
  await page.click('[data-agbdir="C:\\\\"]');
  await page.waitForFunction(() => document.querySelector('#agBody [data-agbrowse] code.ag-bpath') && document.querySelector('#agBody [data-agbrowse] code.ag-bpath').textContent === 'C:\\');
  assert.deepEqual(await browseRows(page), ['Users', 'work']);
  await page.click('[data-agbdir="C:\\\\work"]');
  await page.waitForFunction(() => (document.querySelector('#agBody [data-agbrowse] code.ag-bpath') || {}).textContent === 'C:\\work');
  assert.deepEqual([await browseRows(page), await page.$eval('[data-agbup]', b => b.disabled), await page.$eval('[data-agbok]', b => b.disabled)], [['repo', 'tmp'], false, false]);
  await page.click('[data-agbdir="C:\\\\work\\\\repo"]');
  await page.waitForFunction(() => (document.querySelector('#agBody [data-agbrowse] code.ag-bpath') || {}).textContent === 'C:\\work\\repo');
  assert.deepEqual(await texts(page, '#agBody [data-agbrowse] .ag-bnote'), ['하위 폴더가 없습니다']);
  await page.click('[data-agbup]');                                                               // 위로 / up
  await page.waitForFunction(() => (document.querySelector('#agBody [data-agbrowse] code.ag-bpath') || {}).textContent === 'C:\\work');
  await page.click('[data-agbdir="C:\\\\work\\\\tmp"]');
  await page.waitForFunction(() => (document.querySelector('#agBody [data-agbrowse] code.ag-bpath') || {}).textContent === 'C:\\work\\tmp');
  await page.click('[data-agbok]');
  assert.deepEqual([await page.$eval('#agBody [data-agbrowse]', e => e.hidden), await page.inputValue('#agFolderIn'), await page.evaluate(() => document.activeElement.id)],
    [true, 'C:\\work\\tmp', 'agFolderIn']);
  assert.deepEqual(page.srv.browses, ['', 'C:\\', 'C:\\work', 'C:\\work\\repo', 'C:\\work', 'C:\\work\\tmp']);
  // 네트워크 실패도 탐색기, [닫기]는 숨기기만 / a network failure opens it too; [Close] only hides it
  await page.route('**/api/agentic/pick-folder', route => route.abort());
  await page.click('#agBody [data-agpick]');
  await page.waitForSelector('#agBody [data-agbrowse]:not([hidden]) [data-agbdir]');
  await page.click('[data-agbx]');
  assert.deepEqual([await page.$eval('#agBody [data-agbrowse]', e => e.hidden), await page.inputValue('#agFolderIn'), (await foot(page)).slice(1)], [true, 'C:\\work\\tmp', ['저장됨', true]]);
  // 뷰애즈 사용자는 [찾아보기]가 꺼져 있다 / a view-as user gets a disabled [Browse]
  const viewer = await app(t, { picker: true });
  await viewer.evaluate(() => AI365_setActingUser(7));
  await viewer.waitForFunction(() => window.AI365_EFFECTIVE && window.AI365_EFFECTIVE.menus && window.AI365_EFFECTIVE.menus.m_admin === true);
  await openCard(viewer);
  assert.equal(await viewer.$eval('#agBody [data-agpick]', b => b.disabled), true);
});

test('English labels for [Browse], the waiting note and the explorer', async (t) => {
  const page = await app(t, { picker: true });
  await page.click('#ai365-lang-toggle');
  await page.waitForFunction(() => document.getElementById('homeInput').placeholder === 'How can I help you?');
  await openCard(page);
  page.srv.pick = { status: 503, body: { detail: '폴더 선택 창을 띄울 수 없습니다' }, delay: 400 };
  await page.click('#agBody [data-agpick]');
  assert.deepEqual([await page.$eval('#agBody [data-agpick]', b => b.textContent), (await pickState(page)).hint],
    ['Browse', 'The folder window is open. If you cannot see it, check the taskbar']);
  await page.waitForSelector('#agBody [data-agbrowse]:not([hidden]) [data-agbdir]');
  assert.deepEqual([await texts(page, '#agBody [data-agbrowse] .ag-bgrp'), await page.$eval('#agBody [data-agbrowse] .ag-bpath', e => e.textContent),
    await texts(page, '#agBody [data-agbrowse] button.ag-btn'), page.srv.picks[0].title],
  [['Drives', 'Allowed folders'], 'Choose a folder', ['Up', 'Close', 'Select this folder'], 'Choose a folder to allow']);
});
