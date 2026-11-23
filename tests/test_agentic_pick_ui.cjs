// 실행: Playwright 가 NODE_PATH 에 있을 때 node --test --test-concurrency=1 tests/test_agentic_pick_ui.cjs
// Agentic 셸 폴더 고르기 · 규칙 범위(static/agentic.js, 2026-10-19): 새 세션 대화 상자의 [찾아보기…](POST /pick-folder 200 = 칸 채움 ·
// 허용 폴더 밖 안내 · 취소 · 409 토스트), 503 · 네트워크 실패 = 앱 안 탐색기([data-ag-ov="browse"], 줄 = 들어가기 · 경로 줄 · [위로] ·
// [이 폴더 선택]), "서버 폴더에서 고르기" 링크, 세션 메뉴 "추가 폴더…"(extra_folders PATCH), 승인 카드 [이 세션에서 항상 허용]의 규칙 범위,
// EN 라벨, folder_picker 가 없는 서버는 그대로. 목업 + adapter + agentic.js 를 가짜 원점에 올리고 /api/agentic/* 는 page.route 메모리 스텁이다.
// Run with Playwright on NODE_PATH: node --test --test-concurrency=1 tests/test_agentic_pick_ui.cjs
// Folder picking and rule scopes in the Agentic shell (static/agentic.js, 2026-10-19): [Browse…] in the new-session dialog (POST
// /pick-folder 200 fills the field, an outside folder shows a note, a cancel does nothing, 409 toasts), a 503 or a network failure opens
// the in-app explorer ([data-ag-ov="browse"]: rows enter, breadcrumb, [Up], [Select this folder]), the "Pick from server folders" link,
// the session menu's "Extra folders…" (an extra_folders PATCH), the rule scope on [Always allow in this session], English labels, and a
// server without folder_picker keeping its screen. The mockup, adapter and agentic.js run on a fake origin; /api/agentic/* is an
// in-memory page.route stub. No app server, DB, LLM or real folder window.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const read = rel => fs.readFileSync(path.join(__dirname, '..', rel), 'utf8').replace(/\r\n/g, '\n');
const mockup = read('frontend/ai365-mockup.html');
const adapter = read('static/adapter.js');
const agentic = read('static/agentic.js');
const ORIGIN = 'http://agpick.test';
const HTML = mockup.replace('</body>', '<script src="/static/adapter.js"></script><script src="/static/agentic.js"></script></body>');
const SHOTS = process.env.AI365_SHOTS || '';   // 캡처 폴더(있을 때만) / the screenshot folder, when set

const DESK = 'C:\\Users\\demo\\Desktop', DOCS = 'C:\\Users\\demo\\Documents';
const PA = DESK + '\\proj-a', PB = DESK + '\\proj-b', SITE = DESK + '\\site', NOTES = DOCS + '\\notes';
const MODELS = [
  { id: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash' },
  { id: 'gemini-3.7-flash', label: 'Gemini 3.7 Flash' },
  { id: 'gemini-3.5-flash-lite', label: 'Gemini 3.5 Flash-Lite' },
];
const CONNS = [{ id: 'mcp_b', name: '메일 보내기', description: '메일을 보냅니다', kind: 'action', server_name: '메일 MCP', tool: 'send', inputs: [] }];
// 스텁 탐색기의 폴더 나무(허용 폴더 안) / the stub explorer's folder tree (inside the allowed folders)
const TREE = { [DESK]: ['proj-a', 'proj-b', 'site'], [PA]: ['src'], [PA + '\\src']: [], [PB]: [], [SITE]: ['web', 'docs'], [SITE + '\\web']: [], [SITE + '\\docs']: [],
  [DOCS]: ['notes'], [NOTES]: [] };
const ROOTS = [DESK, DOCS];
const base = p => p.split('\\').pop();
const rootOf = p => ROOTS.find(r => p === r || p.startsWith(r + '\\'));

function sess(o) {   // 2차 모양(notify · seen_seq · connectors) / the phase-2 shape
  return Object.assign({ owner: '', title: '', folder: '', extra_folders: [], model: 'gemini-3.8-flash', effort: 'auto', perm_mode: 'auto', status: 'idle',
    context_pct: 0, rules: [], steps: 0, last_seq: 0, created: '2026-10-19T09:00:00', updated: '2026-10-19T09:00:00',
    connectors: [], notify: false, seen_seq: 0, prev_perm: '', hooks_trust: '', compact_seq: 0 }, o);
}
const light = s => ({ id: s.id, title: s.title, folder: s.folder, model: s.model, perm_mode: s.perm_mode, status: s.status, updated: s.updated, created: s.created,
  steps: s.steps, notify: s.notify, seen_seq: s.seen_seq, last_seq: s.last_seq });

function makeDb() {
  let clock = 0;
  const db = {
    host: 'DEMO-PC', n: 0, calls: [], picker: true, picks: [], pick: { status: 200, body: { cancelled: true } },
    now: () => { clock += 1; return '2026-10-19T16:' + String(10 + Math.floor(clock / 60)).padStart(2, '0') + ':' + String(clock % 60).padStart(2, '0'); },
    settings: { allowed_folders: ROOTS.slice(), default_perm: 'auto', default_model: 'gemini-3.8-flash', deny_commands: [],
      budgets: { max_steps: 200, max_minutes: 120, max_sessions: 3, bash_timeout_sec: 120, max_output_chars: 20000, compact_pct: 80, max_subagents: 3, subagent_max_steps: 60 },
      notify_default: false, commands: [], skills: [], hooks: [] },
    sessions: [
      sess({ id: 'ag_a', title: '리포트 정리', folder: PA, extra_folders: [NOTES], updated: '2026-10-19T15:00:00' }),
      sess({ id: 'ag_w', title: '승인 대기', folder: PB, status: 'waiting', updated: '2026-10-19T14:00:00' }),
    ],
    events: { ag_a: [], ag_w: [] },
  };
  db.push = (sid, kind, payload) => {
    const evs = db.events[sid];
    evs.push({ seq: evs.length + 1, ts: db.now(), kind, payload });
    db.sessions.find(x => x.id === sid).last_seq = evs.length;
  };
  db.sess = sid => db.sessions.find(x => x.id === sid);
  db.push('ag_a', 'user', { text: 'README 를 요약해 줘' });
  db.push('ag_a', 'assistant', { text: '요약했습니다.' });
  db.push('ag_a', 'status', { state: 'idle' });
  db.sess('ag_a').seen_seq = db.sess('ag_a').last_seq;
  // ag_w: 규칙이 실린 승인 셋 · 규칙 없는 옛 승인 · 차단 명령 승인이 대기 중 / three approvals with rules, an old one without, a denied-command one
  const W = (kind, payload) => db.push('ag_w', kind, payload);
  W('user', { text: '테스트를 돌리고 메일로 알려 줘' });
  W('status', { state: 'running', step: 1 });
  const ask = (n, tool, args, label, reason, rule) => {
    W('tool_call', { call_id: 'c' + n, tool, args, label, group: tool === 'mcp_tool' ? 'mcp' : (tool === 'bash' ? 'run' : 'write') });
    W('approval', Object.assign({ approval_id: 'a' + n, call_id: 'c' + n, tool, args, label, reason, decision: 'pending', decided_at: '' }, rule ? { rule } : {}));
  };
  ask(1, 'bash', { command: 'python --version' }, 'python --version 실행', 'auto_cmd', { tool: 'bash', prefix: 'python' });
  ask(2, 'edit_file', { path: 'README.md', old_string: 'a', new_string: 'b' }, 'README.md 편집', 'ask_mode', { tool: 'edit_file' });
  ask(3, 'mcp_tool', { connector_id: 'mcp_b', inputs_json: '{}' }, '메일 보내기 호출', 'mcp_action', { tool: 'mcp_tool', connector: 'mcp_b' });
  ask(4, 'write_file', { path: 'x.txt', content: 'x' }, 'x.txt 쓰기', 'ask_mode', null);
  ask(5, 'bash', { command: 'rm -rf build' }, 'rm -rf build 실행', 'deny_cmd', null);
  W('status', { state: 'waiting', step: 1 });
  db.sess('ag_w').seen_seq = db.sess('ag_w').last_seq;
  return db;
}

async function stream(route, db, sid, afterSeq) {
  const t0 = Date.now();
  while (Date.now() - t0 < 1200 && !(db.events[sid] || []).some(e => e.seq > afterSeq)) await new Promise(r => setTimeout(r, 40));
  const evs = (db.events[sid] || []).filter(e => e.seq > afterSeq);
  const body = evs.length ? evs.map(e => 'id: ' + e.seq + '\ndata: ' + JSON.stringify(e) + '\n\n').join('') : ': ping\n\n';
  try {
    await route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream; charset=utf-8', 'cache-control': 'no-cache' }, body });
  } catch (e) { /* 페이지 · 요청이 먼저 닫힘 / the page or the request closed first */ }
}

// GET /browse 스텁(슈퍼 모양): 처음 목록 = 허용 폴더 + 드라이브, 안 = 하위 폴더 · 경로 줄 · 상위 / the GET /browse stub (super shape)
function browseReply(q) {
  if (!q) return [200, { path: '', parent: '', roots: ROOTS, entries: ROOTS.map(r => ({ name: base(r), path: r })), drives: [{ name: 'C:\\', path: 'C:\\' }],
    truncated: false, crumbs: [], allowed: false }];
  if (!TREE[q]) return [404, { detail: '폴더가 없습니다' }];
  const root = rootOf(q), crumbs = [{ name: base(root), path: root }];
  q.slice(root.length + 1).split('\\').filter(Boolean).reduce((acc, part) => { const p = acc + '\\' + part; crumbs.push({ name: part, path: p }); return p; }, root);
  return [200, { path: q, parent: q === root ? '' : q.slice(0, q.lastIndexOf('\\')), entries: TREE[q].map(n => ({ name: n, path: q + '\\' + n })),
    truncated: false, crumbs, allowed: true }];
}

async function agenticRoute(route, db, url, p) {
  const req = route.request(), method = req.method(), q = Object.fromEntries(url.searchParams);
  let body = null;
  try { body = req.postData() ? JSON.parse(req.postData()) : null; } catch (e) { body = null; }
  db.calls.push({ method, path: p, q, body });
  const json = (obj, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(obj) });
  const rest = p.slice('/api/agentic'.length);
  if (rest === '/models') return json({ models: MODELS });
  if (rest === '/settings') return json(Object.assign({ settings: db.settings, host: db.host }, db.picker ? { folder_picker: true } : {}));
  if (rest === '/connectors') return json({ connectors: CONNS });
  if (rest === '/pick-folder' && method === 'POST') {
    db.picks.push(body);
    const r = db.pick;
    if (r.abort) return route.abort();
    if (r.delay) await new Promise(res => setTimeout(res, r.delay));
    return json(r.body, r.status);
  }
  if (rest === '/browse') { const [code, obj] = browseReply(q.path || ''); return json(obj, code); }
  if (rest === '/sessions' && method === 'GET') return json({ sessions: db.sessions.slice().sort((a, b) => b.updated.localeCompare(a.updated)).map(light) });
  if (rest === '/sessions' && method === 'POST') {
    const folder = String(body.folder || '');
    if (!rootOf(folder)) return json({ detail: '허용 폴더 밖입니다. 관리 센터 › Agentic 설정의 허용 폴더 안에서 고르세요' }, 422);
    const now = db.now(), s = sess({ id: 'ag_new' + (++db.n), title: body.title || base(folder), folder, model: body.model, perm_mode: body.perm_mode, created: now, updated: now });
    db.sessions.push(s); db.events[s.id] = [];
    return json({ session: s });
  }
  const m = /^\/sessions\/([^/]+)(\/.*)?$/.exec(rest);
  if (!m) return json({ detail: 'no route' }, 404);
  const sid = decodeURIComponent(m[1]), tail = m[2] || '', s = db.sess(sid);
  if (!s) return json({ detail: '세션이 없습니다' }, 404);
  const evs = db.events[sid] || (db.events[sid] = []);
  if (!tail && method === 'GET') return json({ session: s, git: { repo: false } });
  if (!tail && method === 'PATCH') {
    if (body.extra_folders && body.extra_folders.some(f => !rootOf(f))) return json({ detail: '허용 폴더 밖입니다. 관리 센터 › Agentic 설정의 허용 폴더 안에서 고르세요' }, 422);
    ['title', 'model', 'perm_mode', 'extra_folders', 'connectors', 'notify'].forEach(k => { if (k in body) s[k] = body[k]; });
    s.updated = db.now();
    return json({ session: s });
  }
  if (tail === '/events') return json({ events: evs.filter(e => e.seq > Number(q.after || 0)).slice(0, Number(q.limit || 500)), last_seq: evs.length });
  if (tail === '/stream') return stream(route, db, sid, Number(q.after || 0));
  if (tail === '/files') return json({ kind: 'dir', path: q.path || s.folder, rel: '', entries: [], truncated: false });
  if (tail === '/tasks') return json({ tasks: [] });
  if (tail === '/commands') return json({ commands: [] });
  if (tail === '/seen' && method === 'POST') { s.seen_seq = Math.max(s.seen_seq, Math.min(Number(body.seq) || 0, s.last_seq)); return json({ session: s }); }
  if (tail === '/changes') return json({ repo: false, branch: null, files: [], added: 0, removed: 0, count: 0, truncated: false, last_checkpoint: null });
  if (tail === '/outputs') return json({ outputs: [] });
  if (tail === '/checkpoints') return json({ checkpoints: [] });
  const am = /^\/approvals\/([^/]+)$/.exec(tail);
  if (am && method === 'POST') {
    const aid = decodeURIComponent(am[1]), last = evs.filter(e => e.kind === 'approval' && e.payload.approval_id === aid).pop();
    if (!last || last.payload.decision !== 'pending') return json({ detail: '대기 중인 승인이 아닙니다' }, 409);
    db.push(sid, 'approval', Object.assign({}, last.payload, { decision: body.decision, decided_at: db.now() }));
    return json({ session: s });
  }
  return json({ detail: 'no route' }, 404);
}

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

async function app(t, last, tweak) {
  const db = makeDb();
  if (tweak) tweak(db);
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => d.dismiss());
  t.after(async () => { await page.close(); assert.deepEqual(errors, []); });
  const handle = async route => {
    const url = new URL(route.request().url()), p = decodeURIComponent(url.pathname);
    const json = (obj, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(obj) });
    if (url.origin !== ORIGIN) return route.abort();
    if (p === '/') return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: HTML });
    if (p === '/static/adapter.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: adapter });
    if (p === '/static/agentic.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: agentic });
    if (p.startsWith('/api/agentic/')) return agenticRoute(route, db, url, p);
    if (p === '/api/access/bootstrap') return json({ pvtree: [], groups: [], members: [], teams: [] });
    if (p === '/api/boards/notifications') return json({ unread: 0, notifications: [] });
    return p.startsWith('/api/') ? json({ detail: 'stub' }, 404) : route.abort();
  };
  await page.route('**/*', route => handle(route).catch(() => {}));
  await page.goto(ORIGIN + '/');
  await page.waitForSelector('#viewHome.active .ai365-ca');
  await page.evaluate(id => localStorage.setItem('ai365_ag_last', id), last || 'ag_a');
  return { page, db };
}
async function enter(page, sid) {
  await page.click('#viewHome [data-ca="agentic"]');
  await page.waitForSelector('.ai365-ag-sess[data-id="' + sid + '"].on');
  await page.waitForSelector('.ai365-ag-tx .ai365-ag-status', { state: 'attached' });
}
const texts = (page, sel) => page.$$eval(sel, els => els.map(e => e.textContent.trim()));
const shot = async (page, name) => {
  if (!SHOTS) return;
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.evaluate(() => { document.scrollingElement.scrollTop = 0; });
  await page.waitForTimeout(250);
  await page.screenshot({ path: path.join(SHOTS, name) });
};
const toastIs = (page, text) => page.waitForFunction(t => (document.getElementById('toast') || {}).textContent === t, text);
const browseCalls = db => db.calls.filter(c => c.path === '/api/agentic/browse').map(c => c.q.path);
// 탐색기의 지금 모양 / the explorer's current look
const explorer = page => page.evaluate(() => {
  const ov = document.querySelector('.ai365-ag-ov[data-ag-ov="browse"]');
  if (!ov) return null;
  return { rows: [...ov.querySelectorAll('[data-ag-bdir]')].map(e => e.textContent), groups: [...ov.querySelectorAll('.ai365-ag-bgrp')].map(e => e.textContent),
    crumbs: [...ov.querySelectorAll('[data-ag-bcrumb]')].map(e => [e.getAttribute('data-ag-bcrumb'), e.textContent]), note: [...ov.querySelectorAll('.ai365-ag-bnote')].map(e => e.textContent),
    up: ov.querySelector('[data-ag="browse-up"]').disabled, ok: ov.querySelector('[data-ag="browse-ok"]').disabled };
});
const waitPath = (page, p) => page.waitForFunction(want => {
  const ov = document.querySelector('.ai365-ag-ov[data-ag-ov="browse"]'), last = ov && [...ov.querySelectorAll('[data-ag-bcrumb]')].pop();
  return !!last && last.getAttribute('data-ag-bcrumb') === want && ov.querySelector('[data-ag-blist]').getAttribute('aria-busy') === 'false';
}, p);
const hint = page => page.evaluate(() => { const h = document.querySelector('.ai365-ag-ov [data-ag-pickhint]'); return h.hidden ? '' : (h.classList.contains('bad') ? '!' : '') + h.textContent; });

test('[Browse…] in the new-session dialog waits for the server window and fills the folder; an outside folder warns, a cancel keeps the field, a busy window toasts', async (t) => {
  const { page, db } = await app(t);
  await enter(page, 'ag_a');
  await page.click('[data-ag="new"]');
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="new"]');
  assert.deepEqual(await page.evaluate(() => {
    const ov = document.querySelector('.ai365-ag-ov[data-ag-ov="new"]'), inp = ov.querySelector('[data-ag-f="folder"]');
    return { pick: ov.querySelector('[data-ag="pick"]').textContent, link: ov.querySelector('[data-ag="browse"]').textContent, value: inp.value, focus: document.activeElement.dataset.agF,
      label: ov.querySelector('label[for="ai365AgFolder"]').textContent, nextToInput: inp.nextElementSibling.dataset.ag, hint: ov.querySelector('[data-ag-pickhint]').hidden };
  }), { pick: '찾아보기…', link: '서버 폴더에서 고르기', value: PA, focus: 'folder', label: '작업 폴더', nextToInput: 'pick', hint: true });
  db.pick = { status: 200, body: { path: SITE, cancelled: false, allowed: true }, delay: 500 };
  await page.click('[data-ag="pick"]');
  // 기다리는 동안 스피너 · 안내 · 버튼 잠김 / a spinner, the note and a locked button while waiting
  assert.deepEqual(await page.evaluate(() => { const b = document.querySelector('[data-ag="pick"]'); return [b.disabled, !!b.querySelector('.ai365-ag-spin')]; }), [true, true]);
  assert.equal(await hint(page), '폴더 선택 창을 열었습니다. 창이 보이지 않으면 작업 표시줄을 확인하세요');
  await shot(page, 'pick_1_waiting.png');
  await page.waitForFunction(v => document.querySelector('[data-ag-f="folder"]').value === v, SITE);
  assert.deepEqual([await hint(page), await page.evaluate(() => { const b = document.querySelector('[data-ag="pick"]'); return [b.disabled, !!b.querySelector('.ai365-ag-spin'), document.activeElement.dataset.agF]; })],
    ['', [false, false, 'folder']]);
  assert.deepEqual(db.picks, [{ acting_user_id: '', start: PA, title: '작업 폴더 선택' }]);
  // 허용 폴더 밖 = 칸은 채우고 경고, 칸을 고치면 경고가 사라진다 / outside: filled with a warning that goes away on edit
  db.pick = { status: 200, body: { path: 'D:\\other', cancelled: false, allowed: false } };
  await page.click('[data-ag="pick"]');
  await page.waitForFunction(() => document.querySelector('[data-ag-f="folder"]').value === 'D:\\other' && !document.querySelector('[data-ag="pick"]').disabled);
  assert.equal(await hint(page), '!허용 폴더 밖입니다. 관리 센터 › Agentic 설정에서 추가하세요');
  await shot(page, 'pick_2_outside.png');
  await page.locator('[data-ag-f="folder"]').press('End');
  await page.keyboard.type('x');
  assert.equal(await hint(page), '');
  // 취소 = 그대로, 409 = 토스트 / a cancel changes nothing; 409 toasts
  await page.fill('[data-ag-f="folder"]', PB);
  db.pick = { status: 200, body: { cancelled: true } };
  await page.click('[data-ag="pick"]');
  await page.waitForFunction(() => !document.querySelector('[data-ag="pick"]').disabled);
  assert.deepEqual([await page.inputValue('[data-ag-f="folder"]'), await hint(page), db.picks[2].start], [PB, '', PB]);
  db.pick = { status: 409, body: { detail: '이미 폴더 선택 창이 열려 있습니다' } };
  await page.click('[data-ag="pick"]');
  await toastIs(page, '이미 폴더 선택 창이 열려 있습니다');
  assert.deepEqual([await page.inputValue('[data-ag-f="folder"]'), await page.locator('.ai365-ag-ov').count()], [PB, 1]);   // 탐색기는 열리지 않는다 / no explorer
  // 고른 폴더로 만든다 / create with the picked folder
  db.pick = { status: 200, body: { path: SITE, cancelled: false, allowed: true } };
  await page.click('[data-ag="pick"]');
  await page.waitForFunction(v => document.querySelector('[data-ag-f="folder"]').value === v && !document.querySelector('[data-ag="pick"]').disabled, SITE);
  await page.click('[data-ag-dlg="ok"]');
  await page.waitForSelector('.ai365-ag-sess[data-id="ag_new1"].on');
  assert.equal(db.calls.filter(c => c.method === 'POST' && c.path === '/api/agentic/sessions').pop().body.folder, SITE);
});

test('a 503 or a network failure opens the in-app explorer over the dialog: rows enter, the breadcrumb and Up go back, Select fills the field; the link opens it directly', async (t) => {
  const { page, db } = await app(t);
  await enter(page, 'ag_a');
  await page.click('[data-ag="new"]');
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="new"]');
  db.pick = { status: 503, body: { detail: '폴더 선택 창을 띄울 수 없습니다' } };
  await page.click('[data-ag="pick"]');
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="browse"]');
  await waitPath(page, PA);                                                                  // 칸의 폴더에서 연다 / opens at the field's folder
  assert.deepEqual(await explorer(page), { rows: ['src'], groups: [], crumbs: [['', ''], [DESK, 'Desktop'], [PA, 'proj-a']], note: [], up: false, ok: false });
  await shot(page, 'pick_3_explorer.png');
  assert.deepEqual([await page.locator('.ai365-ag-ov').count(), await page.evaluate(() => document.activeElement.getAttribute('data-ag-bdir')), await hint(page)], [2, PA + '\\src', '']);
  await page.click('[data-ag-bcrumb="' + DESK.replace(/\\/g, '\\\\') + '"]');                // 경로 줄 / the breadcrumb
  await waitPath(page, DESK);
  assert.deepEqual((await explorer(page)).rows, ['proj-a', 'proj-b', 'site']);
  await page.click('[data-ag-bdir="' + SITE.replace(/\\/g, '\\\\') + '"]');
  await waitPath(page, SITE);
  assert.deepEqual((await explorer(page)).rows, ['web', 'docs']);
  // 키보드: 새 목록의 첫 줄에 초점, Enter = 들어가기, 빈 폴더면 [이 폴더 선택]에 초점 / keyboard: focus on the new first row, Enter enters, an empty folder focuses Select
  assert.equal(await page.evaluate(() => document.activeElement.getAttribute('data-ag-bdir')), SITE + '\\web');
  await page.keyboard.press('Enter');
  await waitPath(page, SITE + '\\web');
  assert.equal(await page.evaluate(() => document.activeElement.dataset.ag), 'browse-ok');
  await page.click('[data-ag="browse-up"]');
  await waitPath(page, SITE);
  await page.click('[data-ag="browse-up"]');
  await waitPath(page, DESK);
  await page.click('[data-ag-bcrumb=""]');                                                    // 처음 목록 / the top list
  await page.waitForFunction(() => document.querySelectorAll('.ai365-ag-ov[data-ag-ov="browse"] .ai365-ag-bgrp').length === 2);
  assert.deepEqual(await explorer(page), { rows: ['Desktop', 'Documents', 'C:\\'], groups: ['허용 폴더', '드라이브'], crumbs: [['', '']], note: [], up: true, ok: true });
  await shot(page, 'pick_4_explorer_top.png');
  await page.click('[data-ag-bdir="' + DOCS.replace(/\\/g, '\\\\') + '"]');
  await waitPath(page, DOCS);
  await page.click('[data-ag-bdir="' + NOTES.replace(/\\/g, '\\\\') + '"]');
  await waitPath(page, NOTES);
  assert.deepEqual((await explorer(page)).note, ['하위 폴더가 없습니다']);
  await page.click('[data-ag="browse-ok"]');
  await page.waitForFunction(() => !document.querySelector('.ai365-ag-ov[data-ag-ov="browse"]'));
  assert.deepEqual([await page.inputValue('[data-ag-f="folder"]'), await page.locator('.ai365-ag-ov[data-ag-ov="new"]').count(), await page.evaluate(() => document.activeElement.dataset.agF)],
    [NOTES, 1, 'folder']);
  assert.deepEqual(browseCalls(db), [PA, DESK, SITE, SITE + '\\web', SITE, DESK, '', DOCS, NOTES]);
  // 링크 = pick-folder 없이 바로 탐색기, 못 여는 시작 경로는 처음 목록으로 / the link skips pick-folder; an unknown start falls back to the top list
  const picks = db.picks.length;
  await page.fill('[data-ag-f="folder"]', 'C:\\nope');
  await page.click('[data-ag="browse"]');
  await page.waitForFunction(() => document.querySelectorAll('.ai365-ag-ov[data-ag-ov="browse"] .ai365-ag-bgrp').length === 2);
  assert.deepEqual([db.picks.length, browseCalls(db).slice(-2)], [picks, ['C:\\nope', '']]);
  // Esc = 탐색기만 닫는다, 한 번 더 = 대화 상자 / Esc closes the explorer only; again closes the dialog
  await page.keyboard.press('Escape');
  assert.deepEqual([await page.locator('.ai365-ag-ov[data-ag-ov="browse"]').count(), await page.locator('.ai365-ag-ov[data-ag-ov="new"]').count()], [0, 1]);
  // 네트워크 실패도 탐색기 / a network failure opens it too
  db.pick = { abort: true };
  await page.click('[data-ag="pick"]');
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="browse"] [data-ag-bdir]');
  await page.click('.ai365-ag-ov[data-ag-ov="browse"] [data-ag="browse-cancel"]');
  assert.deepEqual([await page.locator('.ai365-ag-ov[data-ag-ov="browse"]').count(), await page.inputValue('[data-ag-f="folder"]')], [0, 'C:\\nope']);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.ai365-ag-ov').count(), 0);
});

test('the session menu "Extra folders…" lists, adds (window or explorer), refuses outside and duplicate folders, deletes and PATCHes extra_folders', async (t) => {
  const { page, db } = await app(t);
  await enter(page, 'ag_a');
  await page.click('[data-ag="title"]');
  assert.deepEqual(await texts(page, '.ai365-ag-menu .ai365-ag-mi'), ['이름 바꾸기', '폴더 보기', '추가 폴더…', '완료 알림 켜기', '삭제']);
  await page.click('[data-ag-menu="folders"]');
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="folders"]');
  const rows = () => page.$$eval('[data-ag-ov="folders"] [data-ag-xf]', els => els.map(e => [e.dataset.agXf, e.querySelector('code').textContent, e.querySelector('[data-ag-xfrm]').textContent]));
  assert.deepEqual([await rows(), await page.evaluate(() => document.activeElement.dataset.ag), await texts(page, '[data-ag-ov="folders"] h3')], [[['0', NOTES, '삭제']], 'pick', ['추가 폴더']]);
  db.pick = { status: 200, body: { path: SITE, cancelled: false, allowed: true } };
  await page.click('[data-ag-ov="folders"] [data-ag="pick"]');
  await page.waitForFunction(() => document.querySelectorAll('[data-ag-ov="folders"] [data-ag-xf]').length === 2);
  assert.deepEqual(db.picks.pop(), { acting_user_id: '', start: PA, title: '추가 폴더 선택' });   // 세션 폴더에서 연다 / starts at the session folder
  await page.waitForFunction(() => !document.querySelector('[data-ag-ov="folders"] [data-ag="pick"]').disabled);
  await page.click('[data-ag-ov="folders"] [data-ag="pick"]');                               // 같은 폴더 = 안내만 / the same folder: a note only
  await page.waitForFunction(() => !document.querySelector('[data-ag-ov="folders"] [data-ag="pick"]').disabled);
  assert.deepEqual([(await rows()).length, await hint(page)], [2, '!이미 목록에 있는 폴더입니다']);
  db.pick = { status: 200, body: { path: 'D:\\other', cancelled: false, allowed: false } };
  await page.click('[data-ag-ov="folders"] [data-ag="pick"]');
  await page.waitForFunction(() => !document.querySelector('[data-ag-ov="folders"] [data-ag="pick"]').disabled);
  assert.deepEqual([(await rows()).length, await hint(page)], [2, '!허용 폴더 밖입니다. 관리 센터 › Agentic 설정에서 추가하세요']);
  await shot(page, 'pick_5_folders.png');
  await page.click('[data-ag-xfrm="0"]');
  assert.deepEqual([await rows(), await hint(page)], [[['0', SITE, '삭제']], '']);
  // 503 → 탐색기(세션 폴더에서) → proj-b / 503 → the explorer at the session folder → proj-b
  db.pick = { status: 503, body: { detail: '폴더 선택 창을 띄울 수 없습니다' } };
  await page.click('[data-ag-ov="folders"] [data-ag="pick"]');
  await waitPath(page, PA);
  await page.click('[data-ag-bcrumb="' + DESK.replace(/\\/g, '\\\\') + '"]');
  await waitPath(page, DESK);
  await page.click('[data-ag-bdir="' + PB.replace(/\\/g, '\\\\') + '"]');
  await waitPath(page, PB);
  await page.click('[data-ag="browse-ok"]');
  await page.waitForFunction(() => document.querySelectorAll('[data-ag-ov="folders"] [data-ag-xf]').length === 2);
  assert.deepEqual((await rows()).map(r => r[1]), [SITE, PB]);
  await page.click('[data-ag-ov="folders"] [data-ag-dlg="ok"]');
  await page.waitForFunction(() => !document.querySelector('.ai365-ag-ov'));
  const patches = db.calls.filter(c => c.method === 'PATCH' && c.path.endsWith('/sessions/ag_a')).map(c => c.body);
  assert.deepEqual(patches, [{ acting_user_id: '', extra_folders: [SITE, PB] }]);
  // 환경 패널의 '추가 폴더' 줄 / the environment panel's extra folders row
  await page.waitForFunction(() => [...document.querySelectorAll('.ai365-ag-kv dt')].some(dt => dt.textContent === '추가 폴더' && dt.nextElementSibling.querySelectorAll('.ln').length === 2));
  assert.deepEqual(await page.evaluate(() => [...document.querySelectorAll('.ai365-ag-kv dt')].filter(dt => dt.textContent === '추가 폴더')[0].nextElementSibling.textContent), SITE + PB);
  // 서버가 거절하면 대화 상자에 오류 / a server refusal shows in the dialog
  await page.click('[data-ag="title"]');
  await page.click('[data-ag-menu="folders"]');
  db.pick = { status: 200, body: { path: 'C:\\Windows', cancelled: false, allowed: true } };   // 서버만 아는 거절 / only the server refuses it
  await page.click('[data-ag-ov="folders"] [data-ag="pick"]');
  await page.waitForFunction(() => document.querySelectorAll('[data-ag-ov="folders"] [data-ag-xf]').length === 3);
  await page.click('[data-ag-ov="folders"] [data-ag-dlg="ok"]');
  await page.waitForSelector('[data-ag-ov="folders"] .ai365-ag-derr:not([hidden])');
  assert.equal(await page.textContent('[data-ag-ov="folders"] .ai365-ag-derr'), '허용 폴더 밖입니다. 관리 센터 › Agentic 설정의 허용 폴더 안에서 고르세요');
});

test('approval buttons name the rule scope (bash prefix, connector name, tool name); approvals without a rule and denied commands keep their buttons', async (t) => {
  const { page, db } = await app(t, 'ag_w');
  await enter(page, 'ag_w');
  await page.waitForSelector('.ai365-ag-approval[data-aid="a5"]');
  const btns = () => page.evaluate(() => Object.fromEntries([...document.querySelectorAll('.ai365-ag-approval')].map(a => [a.dataset.aid,
    [...a.querySelectorAll('[data-ag-dec]')].map(b => [b.dataset.agDec, b.textContent])])));
  await page.waitForFunction(() => /메일 보내기/.test((document.querySelector('.ai365-ag-approval[data-aid="a3"] [data-ag-dec="always"]') || {}).textContent || ''));
  assert.deepEqual(await btns(), {
    a1: [['allow', '허용'], ['deny', '거부'], ['always', '이 세션에서 항상 허용 (python …)']],
    a2: [['allow', '허용'], ['deny', '거부'], ['always', '이 세션에서 항상 허용 (edit_file)']],
    a3: [['allow', '허용'], ['deny', '거부'], ['always', '이 세션에서 항상 허용 (메일 보내기)']],
    a4: [['allow', '허용'], ['deny', '거부'], ['always', '이 세션에서 항상 허용']],
    a5: [['allow', '허용'], ['deny', '거부']],
  });
  assert.deepEqual(await page.$eval('.ai365-ag-approval[data-aid="a1"] [data-ag-dec="always"] .sc', e => [e.title, e.hasAttribute('data-i18n-skip')]), ['python …', true]);
  // 괄호와 범위 사이에 버튼의 flex 간격이 끼지 않는다(라벨 = 한 덩어리) / no flex gap between the parentheses and the scope (one label item)
  assert.deepEqual(await page.$eval('.ai365-ag-approval[data-aid="a3"] [data-ag-dec="always"]', b => [...b.children].map(c => c.tagName + (c.className ? '.' + c.className : ''))), ['SPAN']);
  await page.evaluate(() => { document.querySelector('.ai365-ag-scroll').scrollTop = 0; });
  await shot(page, 'pick_6_approvals.png');
  await page.click('.ai365-ag-approval[data-aid="a1"] [data-ag-dec="always"]');
  await page.waitForSelector('.ai365-ag-approval[data-aid="a1"][data-dec="always"]');
  assert.deepEqual(db.calls.filter(c => c.method === 'POST' && c.path.endsWith('/approvals/a1')).map(c => c.body), [{ acting_user_id: '', decision: 'always' }]);
  assert.match(await page.textContent('.ai365-ag-approval[data-aid="a1"] .res'), /^이 세션에서 항상 허용함\d{2}:\d{2}$/);
  // EN: 고정 글만 바뀌고 범위는 데이터 그대로 / English: the fixed words change, the scope stays as data
  await page.click('#ai365-lang-toggle');
  await page.waitForFunction(() => (document.querySelector('.ai365-ag-approval[data-aid="a2"] [data-ag-dec="always"]') || {}).textContent === 'Always allow in this session (edit_file)');
  const en = await btns();
  assert.deepEqual([en.a3[2][1], en.a4[2][1], en.a5.length], ['Always allow in this session (메일 보내기)', 'Always allow in this session', 2]);
});

test('English labels for Browse…, the server-folder link, the waiting note, the explorer and the menu item', async (t) => {
  const { page, db } = await app(t);
  await page.click('#ai365-lang-toggle');
  await page.waitForFunction(() => document.getElementById('homeInput').placeholder === 'How can I help you?');
  await enter(page, 'ag_a');
  await page.click('[data-ag="new"]');
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="new"]');
  assert.deepEqual([await page.textContent('[data-ag="pick"]'), await page.textContent('[data-ag="browse"]'), await page.textContent('label[for="ai365AgFolder"]')],
    ['Browse…', 'Pick from server folders', 'Working folder']);
  db.pick = { status: 503, body: { detail: '폴더 선택 창을 띄울 수 없습니다' }, delay: 400 };
  await page.click('[data-ag="pick"]');
  assert.equal(await hint(page), 'The folder window is open. If you cannot see it, check the taskbar');
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="browse"] [data-ag-bdir]');
  await page.click('[data-ag-bcrumb=""]');
  await page.waitForFunction(() => document.querySelectorAll('.ai365-ag-ov[data-ag-ov="browse"] .ai365-ag-bgrp').length === 2);
  assert.deepEqual([await texts(page, '#ai365AgBrT'), (await explorer(page)).groups, await texts(page, '.ai365-ag-ov[data-ag-ov="browse"] .acts button'),
    await page.getAttribute('[data-ag-bcrumb=""]', 'aria-label'), db.picks[0].title],
  [['Choose a folder'], ['Allowed folders', 'Drives'], ['Up', 'Cancel', 'Select this folder'], 'Top', 'Choose a working folder']);
  await page.keyboard.press('Escape');
  await page.keyboard.press('Escape');
  await page.click('[data-ag="title"]');
  assert.deepEqual(await texts(page, '.ai365-ag-menu .ai365-ag-mi'), ['Rename', 'Show folder', 'Extra folders…', 'Turn on completion notices', 'Delete']);
});

test('a server without folder_picker keeps the new-session dialog and the session menu as they were', async (t) => {
  const { page, db } = await app(t, 'ag_a', d => { d.picker = false; });
  await enter(page, 'ag_a');
  await page.click('[data-ag="new"]');
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="new"]');
  assert.deepEqual([await page.locator('[data-ag="pick"], [data-ag="browse"], [data-ag-pickhint]').count(), await page.evaluate(() => document.activeElement.dataset.agF)], [0, 'folder']);
  await page.keyboard.press('Escape');
  await page.click('[data-ag="title"]');
  assert.deepEqual(await texts(page, '.ai365-ag-menu .ai365-ag-mi'), ['이름 바꾸기', '폴더 보기', '완료 알림 켜기', '삭제']);
  assert.deepEqual([db.picks.length, browseCalls(db)], [0, []]);
});
