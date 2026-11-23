// 실행: Playwright 가 NODE_PATH 에 있을 때 node --test --test-concurrency=1 tests/test_agentic_ui.cjs
// Agentic 모드 셸(static/agentic.js, 2026-10-19 1차): 알약 Agentic → 셸 마운트 · 사이드바 교체, Chat → 원복, 새 세션 대화 상자, 메시지 → 스트림의
// 트랜스크립트 카드(도구 · diff · 승인) → 승인 결정, 실행 중 [중단] · 대기열, 권한 모드 · 모델 PATCH, 환경 패널(폴더 · 브랜치 · 컨텍스트 · 파일 트리 ·
// 터미널 · 백그라운드 작업), EN 라벨. 목업 + adapter + agentic.js 를 가짜 원점에 올리고 /api/agentic/* 는 page.route 메모리 스텁(내부 계약 F 의 모양)이다.
// /stream 은 새 이벤트가 생길 때까지 잠깐 기다렸다가 text/event-stream 본문으로 답하고 끝난다(EventSource 는 끝에서 다시 붙고 after 로 중복이 없다).
// 앱 서버 · DB · LLM 없음. 캡처는 AI365_SHOTS 폴더(있을 때만).
// Run with Playwright on NODE_PATH: node --test --test-concurrency=1 tests/test_agentic_ui.cjs
// The Agentic shell (static/agentic.js, phase 1, 2026-10-19): the Agentic pill mounts the shell and swaps the sidebar, Chat restores it,
// the new-session dialog, a message streamed into transcript cards (tools, diff, approval) and the approval decision, [Stop] and the queue
// while running, permission-mode and model PATCHes, the environment panel (folder, branch, context, file tree, terminal, background tasks)
// and the English labels. The mockup, adapter and agentic.js run on a fake origin; /api/agentic/* is an in-memory page.route stub shaped
// like the internal contract F. /stream waits briefly for new events, answers with a text/event-stream body and ends (EventSource
// reconnects at the end and `after` keeps it free of duplicates). No app server, DB or LLM. Screenshots go to AI365_SHOTS when set.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const read = rel => fs.readFileSync(path.join(__dirname, '..', rel), 'utf8').replace(/\r\n/g, '\n');
const mockup = read('frontend/ai365-mockup.html');
const adapter = read('static/adapter.js');
const agentic = read('static/agentic.js');
const ORIGIN = 'http://ag.test';
const HTML = mockup.replace('</body>', '<script src="/static/adapter.js"></script><script src="/static/agentic.js"></script></body>');
const SHOTS = process.env.AI365_SHOTS || '';

const DESK = 'C:\\Users\\demo\\Desktop', DOCS = 'C:\\Users\\demo\\Documents';
const PA = DESK + '\\proj-a', NOTES = DOCS + '\\notes', PC = DESK + '\\proj-c';
const MODELS = [
  { id: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash' },
  { id: 'gemini-3.7-flash', label: 'Gemini 3.7 Flash' },
  { id: 'gemini-3.5-flash-lite', label: 'Gemini 3.5 Flash-Lite' },
];
const DIFF = '--- a/README.md\n+++ b/README.md\n@@ -1,3 +1,3 @@\n # 프로젝트 A\n \n-teh quick brown fox\n+the quick brown fox\n';

function sess(o) {
  return Object.assign({ owner: '', title: '', folder: '', extra_folders: [], model: 'gemini-3.8-flash', effort: 'auto', perm_mode: 'auto', status: 'idle',
    context_pct: 0, rules: [], steps: 0, last_seq: 0, created: '2026-10-19T09:00:00', updated: '2026-10-19T09:00:00' }, o);
}
const dir = (p, entries) => ({ kind: 'dir', path: p, entries });
const file = (p, content) => ({ kind: 'file', path: p, content, truncated: false, size: Buffer.byteLength(content) });

// 계약 F 를 흉내 낸 작은 서버 / a tiny server imitating contract F
function makeDb() {
  let clock = 0;
  const db = {
    host: 'DEMO-PC', n: 0, calls: [], queued: [],
    now: () => { clock += 1; return '2026-10-19T14:' + String(10 + Math.floor(clock / 60)).padStart(2, '0') + ':' + String(clock % 60).padStart(2, '0'); },
    settings: { allowed_folders: [DESK, DOCS], default_perm: 'auto', default_model: 'gemini-3.8-flash', deny_commands: ['rm\\s+-rf'],
      budgets: { max_steps: 200, max_minutes: 120, max_sessions: 3, bash_timeout_sec: 120, max_output_chars: 20000 } },
    sessions: [
      sess({ id: 'ag_a1', title: '리포트 정리', folder: PA, perm_mode: 'ask', context_pct: 12, steps: 2, last_seq: 10, updated: '2026-10-19T13:41:00' }),
      sess({ id: 'ag_b2', title: '메모 정리', folder: NOTES, updated: '2026-10-18T09:00:00' }),
      sess({ id: 'ag_a3', title: '테스트 고치기', folder: PA, status: 'error', updated: '2026-10-17T09:00:00' }),
    ],
    events: { ag_a1: [], ag_b2: [], ag_a3: [] },
    git: { ag_a1: { repo: true, branch: 'main' }, ag_b2: { repo: false }, ag_a3: { repo: true, branch: 'fix/tests' } },
    tasks: { ag_a1: [
      { id: 't1', kind: 'bash', label: 'npm run dev', status: 'running', started: '2026-10-19T13:30:00', ended: null, exit_code: null },
      { id: 't0', kind: 'bash', label: 'npm ci', status: 'done', started: '2026-10-19T13:20:00', ended: '2026-10-19T13:21:00', exit_code: 0 },
    ] },
    files: {
      [PA]: dir(PA, [{ name: 'README.md', type: 'file', size: 1200 }, { name: 'src', type: 'dir', size: 0 }, { name: 'package.json', type: 'file', size: 310 }]),
      [PA + '\\src']: dir(PA + '\\src', [{ name: 'app.js', type: 'file', size: 820 }, { name: 'util', type: 'dir', size: 0 }]),
      [PA + '\\src\\util']: dir(PA + '\\src\\util', []),
      [PA + '\\README.md']: file(PA + '\\README.md', '# 프로젝트 A\n\nteh quick brown fox\n'),
      [PA + '\\package.json']: file(PA + '\\package.json', '{ "name": "proj-a" }\n'),
      [PA + '\\src\\app.js']: file(PA + '\\src\\app.js', 'console.log(1);\n'),
      [NOTES]: dir(NOTES, [{ name: 'todo.md', type: 'file', size: 12 }]),
      [PC]: dir(PC, []),
    },
  };
  db.push = (sid, kind, payload, ts) => {
    const evs = db.events[sid];
    evs.push({ seq: evs.length + 1, ts: ts || db.now(), kind, payload });
    const s = db.sessions.find(x => x.id === sid);
    if (s) s.last_seq = evs.length;
  };
  db.snap = sid => JSON.parse(JSON.stringify(db.sessions.find(x => x.id === sid)));
  // 지난 턴(읽기 · 명령 · 답 · 요약) / a previous turn: a read, a command, the answer and the summary
  const at = n => '2026-10-19T13:40:' + String(n).padStart(2, '0');
  db.push('ag_a1', 'user', { text: 'README 를 요약해 줘' }, at(1));
  db.push('ag_a1', 'status', { state: 'running', note: 'README.md 읽는 중', step: 1 }, at(2));
  db.push('ag_a1', 'tool_call', { call_id: 'c1', tool: 'read_file', args: { path: 'README.md' }, label: 'README.md 읽기', group: 'read' }, at(3));
  db.push('ag_a1', 'tool_result', { call_id: 'c1', tool: 'read_file', ok: true, summary: '3줄', detail: '1\t# 프로젝트 A\n2\t\n3\tteh quick brown fox', duration_ms: 35, truncated: false }, at(4));
  db.push('ag_a1', 'tool_call', { call_id: 'c2', tool: 'bash', args: { command: 'git status' }, label: 'git status 실행', group: 'run' }, at(5));
  db.push('ag_a1', 'tool_result', { call_id: 'c2', tool: 'bash', ok: true, summary: '변경 없음', output: 'On branch main\nnothing to commit, working tree clean', exit_code: 0, duration_ms: 420, truncated: false }, at(6));
  db.push('ag_a1', 'assistant', { text: '## 요약\n\n- **프로젝트 A** 의 소개 문서입니다.\n- 오타가 한 곳 있습니다.' }, at(7));
  db.push('ag_a1', 'summary', { text: 'README 요약', steps: 2, duration_ms: 5200, tokens_est: 3100 }, at(8));
  db.push('ag_a1', 'context', { pct: 12 }, at(9));
  db.push('ag_a1', 'status', { state: 'idle' }, at(10));
  db.sessions[0].updated = '2026-10-19T13:41:00';
  // 오류로 끝난 세션 / a session that ended in an error
  db.push('ag_a3', 'user', { text: '테스트를 고쳐 줘' }, '2026-10-17T08:59:00');
  db.push('ag_a3', 'status', { state: 'running', step: 1 }, '2026-10-17T08:59:01');
  db.push('ag_a3', 'error', { message: 'Gemini 호출이 계속 실패했습니다' }, '2026-10-17T08:59:30');
  db.push('ag_a3', 'status', { state: 'error' }, '2026-10-17T08:59:31');
  db.sessions[2].updated = '2026-10-17T09:00:00';
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

async function agenticRoute(route, db, url, p) {
  const req = route.request(), method = req.method(), q = Object.fromEntries(url.searchParams);
  let body = null;
  try { body = req.postData() ? JSON.parse(req.postData()) : null; } catch (e) { body = null; }
  db.calls.push({ method, path: p, q, body });
  const json = (obj, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(obj) });
  const rest = p.slice('/api/agentic'.length);
  if (rest === '/models') return json({ models: MODELS });
  if (rest === '/settings') return json({ settings: db.settings, host: db.host });
  if (rest === '/sessions' && method === 'GET') {
    return json({ sessions: db.sessions.slice().sort((a, b) => b.updated.localeCompare(a.updated))
      .map(s => ({ id: s.id, title: s.title, folder: s.folder, model: s.model, perm_mode: s.perm_mode, status: s.status, updated: s.updated, created: s.created, steps: s.steps })) });
  }
  if (rest === '/sessions' && method === 'POST') {
    const folder = String(body.folder || '');
    if (!db.settings.allowed_folders.some(f => folder.toLowerCase().startsWith(f.toLowerCase() + '\\'))) return json({ detail: '허용 폴더 밖의 경로입니다: ' + folder }, 422);
    const now = db.now();
    const s = sess({ id: 'ag_new' + (++db.n), title: body.title || folder.split('\\').pop(), folder, model: body.model || db.settings.default_model,
      perm_mode: body.perm_mode || db.settings.default_perm, created: now, updated: now });
    db.sessions.push(s); db.events[s.id] = []; db.git[s.id] = { repo: false };
    return json({ session: s });
  }
  const m = /^\/sessions\/([^/]+)(\/.*)?$/.exec(rest);
  if (!m) return json({ detail: 'no route' }, 404);
  const sid = decodeURIComponent(m[1]), tail = m[2] || '', s = db.sessions.find(x => x.id === sid);
  if (!s) return json({ detail: '세션이 없습니다' }, 404);
  const evs = db.events[sid] || (db.events[sid] = []);
  if (!tail && method === 'GET') return json({ session: s, git: db.git[sid] || { repo: false } });
  if (!tail && method === 'PATCH') {
    ['title', 'model', 'perm_mode', 'extra_folders'].forEach(k => { if (k in body) s[k] = body[k]; });
    s.updated = db.now();
    return json({ session: s });
  }
  if (!tail && method === 'DELETE') { db.sessions = db.sessions.filter(x => x.id !== sid); return json({ ok: true }); }
  if (tail === '/events') {
    const from = Number(q.after || 0), lim = Number(q.limit || 500);
    return json({ events: evs.filter(e => e.seq > from).slice(0, lim), last_seq: evs.length });
  }
  if (tail === '/stream') return stream(route, db, sid, Number(q.after || 0));
  if (tail === '/files') { const f = db.files[q.path || s.folder]; return f ? json(f) : json({ detail: '허용 폴더 밖의 경로입니다' }, 403); }
  if (tail === '/tasks') return json({ tasks: db.tasks[sid] || [] });
  if (tail === '/messages') {
    if (s.status === 'running' || s.status === 'waiting') { db.queued.push(body.text); return json({ queued: true, session: s }); }
    const text = String(body.text || '');
    db.push(sid, 'user', { text });
    s.status = 'running'; s.updated = db.now();
    db.push(sid, 'status', { state: 'running', note: /오래/.test(text) ? '테스트 실행 중' : 'README.md 고치는 중', step: 1 });
    const snap = db.snap(sid);   // 서버가 실제로 돌려줄 시점의 모양 / the shape a real server returns at this point
    if (/오래/.test(text)) {
      db.push(sid, 'tool_call', { call_id: 'c9', tool: 'bash', args: { command: 'npm test -- --watch' }, label: 'npm test 실행', group: 'run' });
    } else if (/예산/.test(text)) {   // 예산 초과 → 계속할까요? / budget exceeded → continue?
      db.push(sid, 'approval', { approval_id: 'b1', tool: 'continue', args: {}, label: '계속', reason: 'budget', decision: 'pending' });
      db.push(sid, 'status', { state: 'waiting', step: 200 });
      s.status = 'waiting';
    } else {
      db.push(sid, 'tool_call', { call_id: 'c3', tool: 'edit_file', args: { path: 'README.md', old_string: 'teh', new_string: 'the' }, label: 'README.md 편집', group: 'write' });
      db.push(sid, 'tool_result', { call_id: 'c3', tool: 'edit_file', ok: true, summary: '1줄 바뀜', detail: '', diff: { path: 'README.md', unified: DIFF }, duration_ms: 18, truncated: false });
      db.push(sid, 'tool_call', { call_id: 'c4', tool: 'bash', args: { command: 'npm test' }, label: 'npm test 실행', group: 'run' });
      db.push(sid, 'approval', { approval_id: 'a1', call_id: 'c4', tool: 'bash', args: { command: 'npm test' }, label: 'npm test 실행',
        reason: s.perm_mode === 'ask' ? 'ask_mode' : 'deny_cmd', decision: 'pending' });
      db.push(sid, 'status', { state: 'waiting', step: 2 });
      s.status = 'waiting';
    }
    return json({ queued: false, session: snap });
  }
  if (tail === '/stop') {
    db.push(sid, 'status', { state: 'stopped', note: '사용자가 중단함' });
    s.status = 'stopped'; s.updated = db.now();
    return json({ session: s });
  }
  const am = /^\/approvals\/([^/]+)$/.exec(tail);
  if (am && method === 'POST') {
    const aid = decodeURIComponent(am[1]);
    const last = evs.filter(e => e.kind === 'approval' && e.payload.approval_id === aid).pop();
    if (!last || last.payload.decision !== 'pending') return json({ detail: '이미 결정된 승인입니다' }, 409);
    const dec = body.decision;
    db.push(sid, 'approval', Object.assign({}, last.payload, { decision: dec, decided_at: db.now() }));
    if (last.payload.reason === 'budget' && dec === 'deny') {   // 예산 거부 = 멈춤 / a denied budget = stop
      db.push(sid, 'status', { state: 'stopped' });
      s.status = 'stopped'; s.updated = db.now();
      return json({ session: s });
    }
    if (dec === 'always') s.rules.push({ tool: 'bash', prefix: 'npm' });
    s.status = 'running';
    const snap = db.snap(sid);
    db.push(sid, 'status', { state: 'running', note: 'npm test 실행 중', step: 3 });
    if (dec === 'deny') db.push(sid, 'tool_result', { call_id: last.payload.call_id, tool: 'bash', ok: false, summary: '거부됨', detail: '사용자가 거부했습니다', duration_ms: 0 });
    else db.push(sid, 'tool_result', { call_id: last.payload.call_id, tool: 'bash', ok: true, summary: '12개 통과', output: 'PASS  test/readme.test.js\nTests: 12 passed, 12 total', exit_code: 0, duration_ms: 1240, truncated: false });
    db.push(sid, 'assistant', { text: dec === 'deny' ? '명령을 실행하지 않았습니다.' : 'README 의 오타 **teh** 를 **the** 로 고쳤고 테스트 12개가 모두 통과했습니다.' });
    db.push(sid, 'summary', { text: '오타 수정', steps: 3, duration_ms: 48210, tokens_est: 12400 });
    db.push(sid, 'context', { pct: 37 });
    db.push(sid, 'status', { state: 'idle' });
    s.status = 'idle'; s.context_pct = 37; s.steps += 3; s.updated = db.now();
    return json({ session: snap });
  }
  return json({ detail: 'no route' }, 404);
}

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

async function app(t) {
  const db = makeDb();
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
  // 페이지가 닫힌 뒤 늦게 끝나는 응답은 버린다 / replies that land after the page closed are dropped
  await page.route('**/*', route => handle(route).catch(() => {}));
  await page.goto(ORIGIN + '/');
  await page.waitForSelector('#viewHome.active .ai365-ca');
  return { page, db };
}
async function enter(page, sid) {
  await page.click('#viewHome [data-ca="agentic"]');
  await page.waitForSelector('.ai365-ag-sess[data-id="' + sid + '"].on');
  await page.waitForFunction(() => !document.querySelector('.ai365-ag-tx .ai365-ag-hint') || !!document.querySelector('.ai365-ag-status'));   // 세션 본문이 그려진 뒤 / once the session body is drawn
}
async function waitFor(fn, ms) {
  const t0 = Date.now();
  while (Date.now() - t0 < (ms || 5000)) { if (await fn()) return; await new Promise(r => setTimeout(r, 30)); }
  throw new Error('timed out waiting');
}
const callsTo = (db, method, tail) => db.calls.filter(c => c.method === method && c.path.endsWith(tail));
const shot = async (page, name) => { if (SHOTS) { fs.mkdirSync(SHOTS, { recursive: true }); await page.waitForTimeout(300); await page.screenshot({ path: path.join(SHOTS, name) }); } };
const texts = (page, sel) => page.$$eval(sel, els => els.map(e => e.textContent.trim()));

test('the Agentic pill mounts the shell, swaps the sidebar and reopens the last session; Chat restores everything', async (t) => {
  const { page, db } = await app(t);
  await page.evaluate(() => localStorage.setItem('ai365_ag_last', 'ag_b2'));
  assert.equal(await page.locator('.ai365-ag-side').count(), 0);
  await enter(page, 'ag_b2');
  const geo = await page.evaluate(() => {
    const side = document.getElementById('sidebar'), vis = el => !!el && el.getClientRects().length > 0;
    const blank = document.querySelector('#viewWork .ai365-ca-blank');
    return {
      body: document.body.classList.contains('ai365-ag-on'), first: side.firstElementChild.className,
      mockHidden: [...side.children].filter(c => !c.classList.contains('ai365-ag-side')).every(c => !vis(c)), newChatVisible: vis(document.getElementById('newChatBtn')),
      shell: !!blank.querySelector(':scope > .ai365-ag'), cols: getComputedStyle(blank.querySelector('.ai365-ag')).gridTemplateColumns.split(' ').length,
      groups: [...document.querySelectorAll('.ai365-ag-sgrp')].map(g => [g.querySelector('.ai365-ag-sgh').textContent.trim(), [...g.querySelectorAll('.ai365-ag-sess')].map(b => b.dataset.id)]),
      errDot: !!document.querySelector('.ai365-ag-sess[data-id="ag_a3"] .dot.error'),
      title: document.querySelector('#viewWork .ai365-ag-title .t').textContent, pill: !!document.querySelector('#viewWork .sub-header .ai365-ca'),
      icons: [...document.querySelectorAll('#viewWork .ai365-ag-hr [data-ag-view]')].map(b => b.dataset.agView),
      hint: (document.querySelector('.ai365-ag-tx .ai365-ag-hint') || {}).textContent || '',
    };
  });
  assert.deepEqual(geo, { body: true, first: 'ai365-ag-side', mockHidden: true, newChatVisible: false, shell: true, cols: 2,
    groups: [['proj-a', ['ag_a1', 'ag_a3']], ['notes', ['ag_b2']]], errDot: true, title: '메모 정리', pill: true,
    icons: ['transcript', 'terminal', 'files', 'panel'], hint: '아직 대화가 없습니다. 아래 입력창에 맡길 작업을 적어 보세요.' });

  // 다른 세션 열기: 지난 턴이 카드로 그려지고 스트림이 after=마지막 seq 로 붙는다 / open another session: the previous turn renders and the stream attaches after the last seq
  await page.click('.ai365-ag-sess[data-id="ag_a1"]');
  await page.waitForSelector('.ai365-ag-tool[data-call="c2"]');
  const tx = await page.evaluate(() => ({
    user: [...document.querySelectorAll('.ai365-ag-msg.user')].map(e => e.textContent),
    agentBold: (document.querySelector('.ai365-ag-msg.agent b') || {}).textContent,
    tools: [...document.querySelectorAll('.ai365-ag-tool')].map(e => [e.dataset.call, e.dataset.state, e.querySelector('.lb').textContent, e.querySelector('.du').textContent]),
    sum: document.querySelector('.ai365-ag-sum').textContent, statusHidden: document.querySelector('.ai365-ag-status').hidden,
  }));
  assert.deepEqual(tx, { user: ['README 를 요약해 줘'], agentBold: '프로젝트 A', tools: [['c1', 'ok', 'README.md 읽기', '35ms'], ['c2', 'ok', 'git status 실행', '420ms']],
    sum: '완료·2스텝·5.2초·토큰 약 3.1k', statusHidden: true });
  await waitFor(() => callsTo(db, 'GET', '/ag_a1/stream').some(c => c.q.after === '10' && c.q.acting_user_id === ''));
  assert.equal(await page.evaluate(() => localStorage.getItem('ai365_ag_last')), 'ag_a1');
  await shot(page, 'ag_1_shell.png');

  // ← → = 열어 본 세션 사이 이동 / back and forward move through the visited sessions
  await page.click('[data-ag="back"]');
  await page.waitForSelector('.ai365-ag-sess[data-id="ag_b2"].on');
  assert.equal(await page.$eval('[data-ag="fwd"]', b => b.disabled), false);
  await page.click('[data-ag="fwd"]');
  await page.waitForSelector('.ai365-ag-sess[data-id="ag_a1"].on');
  await page.waitForSelector('.ai365-ag-tool[data-call="c1"]');

  // 접힌 사이드바: 세션은 아이콘만, 아이콘을 누르면 펼치지 않고 그 세션을 연다 / collapsed sidebar: icons only; an icon opens its session without expanding
  await page.click('.ai365-ag-side [data-ag="collapse"]');
  const rail = await page.evaluate(() => {
    const vis = el => !!el && el.getClientRects().length > 0;
    const a3 = document.querySelector('.ai365-ag-sess[data-id="ag_a3"]');
    return { collapsed: document.getElementById('sidebar').classList.contains('collapsed'), av: vis(a3.querySelector('.av')), title: vis(a3.querySelector('.tt')), av3: a3.querySelector('.av').textContent };
  });
  assert.deepEqual(rail, { collapsed: true, av: true, title: false, av3: '테' });
  await shot(page, 'ag_6_collapsed.png');
  await page.click('.ai365-ag-sess[data-id="ag_a3"]');
  await page.waitForSelector('.ai365-ag-sess[data-id="ag_a3"].on');
  assert.equal(await page.evaluate(() => document.getElementById('sidebar').classList.contains('collapsed')), true);
  await page.waitForSelector('.ai365-ag-err');   // 오류 이벤트 = 빨간 줄, status error = 표시 줄 / an error event is a red line, status error a marker
  assert.deepEqual(await page.evaluate(() => [document.querySelector('.ai365-ag-err').textContent, document.querySelector('.ai365-ag-mark.error').textContent,
    document.querySelector('.ai365-ag-status').hidden, document.querySelector('[data-ag="send"]').hidden]), ['Gemini 호출이 계속 실패했습니다', '오류로 멈췄습니다', true, false]);
  await page.click('.ai365-ag-slist', { position: { x: 30, y: 400 } });   // 빈 곳 = 펼치기(목업 핸들러) / an empty spot expands (the mockup's handler)
  assert.equal(await page.evaluate(() => document.getElementById('sidebar').classList.contains('collapsed')), false);

  // Chat = 원복 / Chat restores everything
  await page.click('#viewWork [data-ca="chat"]');
  const back = await page.evaluate(() => {
    const vis = el => !!el && el.getClientRects().length > 0;
    return { body: document.body.classList.contains('ai365-ag-on'), side: !!document.querySelector('.ai365-ag-side'), newChat: vis(document.getElementById('newChatBtn')),
      scroll: vis(document.querySelector('#sidebar .sidebar-scroll')), blank: document.querySelector('#viewWork .ai365-ca-blank').innerHTML,
      head: !!document.querySelector('.ai365-ag-hl, .ai365-ag-hr, .ai365-ag-menu'), home: document.getElementById('viewHome').classList.contains('active'), st: window.AI365_agentic.state() };
  });
  assert.deepEqual([back.body, back.side, back.newChat, back.scroll, back.blank, back.head, back.home], [false, false, true, true, '', false, true]);
  assert.deepEqual([back.st.on, back.st.streaming, back.st.reconnecting, back.st.taskPolling], [false, false, false, false]);
  await enter(page, 'ag_a3');   // 다시 들어오면 마지막 세션 / re-entering opens the last session
});

test('the new-session dialog lists the allowed folders, shows a 422 inline and POSTs the chosen fields', async (t) => {
  const { page, db } = await app(t);
  await enter(page, 'ag_a1');
  await page.click('[data-ag="new"]');
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="new"]');
  const dlg = await page.evaluate(() => {
    const ov = document.querySelector('.ai365-ag-ov');
    return { folder: ov.querySelector('[data-ag-f="folder"]').value, list: [...ov.querySelectorAll('#ai365AgFolders option')].map(o => o.value),
      chips: [...ov.querySelectorAll('[data-ag-pick]')].map(c => c.textContent), model: ov.querySelector('[data-ag-f="model"]').value, perm: ov.querySelector('[data-ag-f="perm"]').value,
      focus: document.activeElement.dataset.agF };
  });
  assert.deepEqual(dlg, { folder: PA, list: [DESK, DOCS], chips: ['Desktop', 'Documents'], model: 'gemini-3.8-flash', perm: 'auto', focus: 'folder' });
  await shot(page, 'ag_4_new_dialog.png');
  await page.fill('[data-ag-f="folder"]', 'C:\\Windows\\System32');
  await page.click('[data-ag-dlg="ok"]');
  await page.waitForSelector('.ai365-ag-derr:not([hidden])');
  assert.equal(await page.textContent('.ai365-ag-derr'), '허용 폴더 밖의 경로입니다: C:\\Windows\\System32');
  assert.equal(await page.locator('.ai365-ag-ov').count(), 1);
  await page.locator('[data-ag-pick]').first().click();
  assert.equal(await page.inputValue('[data-ag-f="folder"]'), DESK);
  await page.locator('[data-ag-f="folder"]').press('End');
  await page.keyboard.type('\\proj-c');
  await page.fill('[data-ag-f="title"]', '새 작업');
  await page.selectOption('[data-ag-f="model"]', 'gemini-3.7-flash');
  await page.selectOption('[data-ag-f="perm"]', 'ask');
  assert.equal(await page.textContent('[data-ag-permhint]'), '묻기: 편집과 명령을 모두 먼저 묻습니다');
  await page.locator('[data-ag-f="title"]').press('Enter');   // 입력칸의 Enter = 만들기 / Enter in a field submits
  await page.waitForSelector('.ai365-ag-sess[data-id="ag_new1"].on');
  const posts = callsTo(db, 'POST', '/api/agentic/sessions');
  assert.deepEqual(posts.map(c => c.body), [
    { acting_user_id: '', folder: 'C:\\Windows\\System32', model: 'gemini-3.8-flash', perm_mode: 'auto' },
    { acting_user_id: '', folder: PC, title: '새 작업', model: 'gemini-3.7-flash', perm_mode: 'ask' },
  ]);
  await page.waitForFunction(() => !document.querySelector('.ai365-ag-ov') && document.querySelector('[data-ag-perm]').value === 'ask' && !!document.querySelector('.ai365-ag-status'));
  const after1 = await page.evaluate(() => ({
    groups: [...document.querySelectorAll('.ai365-ag-sgh')].map(g => g.textContent.trim()), title: document.querySelector('.ai365-ag-title .t').textContent,
    perm: document.querySelector('[data-ag-perm]').value, model: document.querySelector('[data-ag-model]').value, hint: document.querySelector('.ai365-ag-tx .ai365-ag-hint').textContent,
  }));
  assert.deepEqual(after1, { groups: ['proj-c', 'proj-a', 'notes'], title: '새 작업', perm: 'ask', model: 'gemini-3.7-flash', hint: '아직 대화가 없습니다. 아래 입력창에 맡길 작업을 적어 보세요.' });
  await page.click('[data-ag="new"]');
  await page.waitForSelector('.ai365-ag-ov');
  assert.equal(await page.inputValue('[data-ag-f="folder"]'), PC);   // 가장 최근 세션의 폴더부터 / prefilled with the latest session's folder
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.ai365-ag-ov').count(), 0);
});

test('a message streams user, tool and diff cards and an approval; Allow posts the decision and the turn finishes', async (t) => {
  const { page, db } = await app(t);
  await enter(page, 'ag_a1');
  await page.click('#ai365AgInput');
  await page.keyboard.type('README 오타 고쳐 줘');
  await page.keyboard.press('Shift+Enter');
  await page.keyboard.type('테스트도 돌려 줘');
  await page.keyboard.press('Enter');
  await page.waitForSelector('.ai365-ag-approval[data-aid="a1"]');
  assert.deepEqual(callsTo(db, 'POST', '/ag_a1/messages').map(c => c.body), [{ acting_user_id: '', text: 'README 오타 고쳐 줘\n테스트도 돌려 줘' }]);
  await page.waitForFunction(() => document.querySelector('.ai365-ag-status.waiting'));
  const mid = await page.evaluate(() => {
    const a = document.querySelector('.ai365-ag-approval[data-aid="a1"]'), vis = el => !!el && el.getClientRects().length > 0;
    return {
      users: [...document.querySelectorAll('.ai365-ag-msg.user')].map(e => e.textContent), pend: document.querySelectorAll('.ai365-ag-msg.pend').length,
      tools: [...document.querySelectorAll('.ai365-ag-tool')].map(e => [e.dataset.call, e.dataset.state]),
      c3: [document.querySelector('[data-call="c3"] .lb').textContent, document.querySelector('[data-call="c3"] .sm').textContent, document.querySelector('[data-call="c3"] .ds').textContent],
      appr: { dec: a.dataset.dec, title: a.querySelector('.hd b').textContent, reason: a.querySelector('.rs').textContent, args: a.querySelector('.ar').textContent,
        btns: [...a.querySelectorAll('[data-ag-dec]')].map(b => [b.dataset.agDec, b.textContent]) },
      status: document.querySelector('.ai365-ag-status').textContent, stop: vis(document.querySelector('[data-ag="stop"]')), send: vis(document.querySelector('[data-ag="send"]')),
    };
  });
  assert.deepEqual(mid, {
    users: ['README 를 요약해 줘', 'README 오타 고쳐 줘\n테스트도 돌려 줘'], pend: 0,
    tools: [['c1', 'ok'], ['c2', 'ok'], ['c3', 'ok'], ['c4', 'wait']],
    c3: ['README.md 편집', '1줄 바뀜', '+1 -1'],
    appr: { dec: 'pending', title: 'npm test 실행', reason: '묻기 모드라 승인이 필요합니다', args: '$ npm test',
      btns: [['allow', '허용'], ['deny', '거부'], ['always', '이 세션에서 항상 허용']] },
    status: '승인을 기다리는 중', stop: true, send: false,
  });
  await shot(page, 'ag_2_approval.png');

  // diff 카드 펼치기 / expand the diff card
  await page.click('[data-call="c3"] .ai365-ag-trow');
  await page.waitForSelector('[data-call="c3"].open .ai365-ag-diff');
  const diff = await page.$$eval('[data-call="c3"] .ai365-ag-diff .l', ls => ls.map(l => [l.className.replace('l', '').trim(), l.querySelector('i').textContent, l.querySelector('span').textContent]));
  assert.deepEqual(diff, [['h', '', '--- a/README.md'], ['h', '', '+++ b/README.md'], ['k', '', '@@ -1,3 +1,3 @@'], ['', '1', ' # 프로젝트 A'], ['', '2', ' '],
    ['d', '3', '-teh quick brown fox'], ['a', '3', '+the quick brown fox']]);
  assert.equal(await page.$eval('[data-call="c3"] .ai365-ag-trow', b => b.getAttribute('aria-expanded')), 'true');
  await shot(page, 'ag_3_diff.png');

  await page.click('.ai365-ag-approval[data-aid="a1"] [data-ag-dec="allow"]');
  await page.waitForSelector('.ai365-ag-approval[data-aid="a1"][data-dec="allow"]');
  assert.deepEqual(callsTo(db, 'POST', '/ag_a1/approvals/a1').map(c => c.body), [{ acting_user_id: '', decision: 'allow' }]);
  await page.waitForFunction(() => document.querySelectorAll('.ai365-ag-sum').length === 2 && document.querySelector('.ai365-ag-status').hidden);
  const done = await page.evaluate(() => {
    const vis = el => !!el && el.getClientRects().length > 0, a = document.querySelector('.ai365-ag-approval[data-aid="a1"]');
    const agents = [...document.querySelectorAll('.ai365-ag-msg.agent')];
    return {
      res: a.querySelector('.res').textContent, btns: a.querySelectorAll('[data-ag-dec]').length, cards: document.querySelectorAll('.ai365-ag-approval').length,
      users: document.querySelectorAll('.ai365-ag-msg.user').length, agents: agents.length, bold: [...agents[1].querySelectorAll('b')].map(b => b.textContent),
      c4: document.querySelector('[data-call="c4"]').dataset.state, sum: document.querySelectorAll('.ai365-ag-sum')[1].textContent,
      ctx: document.querySelector('[data-ag-ctx]').textContent, send: vis(document.querySelector('[data-ag="send"]')), stop: vis(document.querySelector('[data-ag="stop"]')),
      term: [...document.querySelectorAll('.ai365-ag-term .cmd')].map(e => e.textContent), c3open: !!document.querySelector('[data-call="c3"].open .ai365-ag-diff'),
    };
  });
  assert.deepEqual(done, { res: '허용함' + done.res.slice(3), btns: 0, cards: 1, users: 2, agents: 2, bold: ['teh', 'the'], c4: 'ok', sum: '완료·3스텝·48초·토큰 약 12.4k',
    ctx: '37%', send: true, stop: false, term: ['$ git status', '$ npm test'], c3open: true });
  assert.match(done.res, /^허용함\d{2}:\d{2}$/);
  assert.equal(await page.evaluate(() => window.AI365_agentic.state().lastSeq), db.events.ag_a1.length);
  // 다시 붙을 때마다 after 가 마지막으로 본 seq 로 올라간다(중복 없음) / each reconnect moves `after` up to the last seen seq (no duplicates)
  const afters = callsTo(db, 'GET', '/ag_a1/stream').map(c => Number(c.q.after));
  assert.deepEqual(afters.slice().sort((a, b) => a - b), afters);
  assert.ok(afters.includes(10) && afters.includes(17), JSON.stringify(afters));
});

test('while running the composer shows [Stop], queues a second message, and Stop posts and marks the run stopped', async (t) => {
  const { page, db } = await app(t);
  await enter(page, 'ag_a1');
  await page.fill('#ai365AgInput', '오래 걸리는 테스트를 돌려 줘');
  await page.click('[data-ag="send"]');
  await page.waitForSelector('[data-ag="stop"]:not([hidden])');
  await page.waitForSelector('.ai365-ag-tool[data-call="c9"]');
  const run = await page.evaluate(() => ({
    status: document.querySelector('.ai365-ag-status').textContent, cls: document.querySelector('.ai365-ag-status').className, c9: document.querySelector('[data-call="c9"]').dataset.state,
    dot: !!document.querySelector('.ai365-ag-sess[data-id="ag_a1"] .dot.running'), send: document.querySelector('[data-ag="send"]').hidden,
    ph: document.getElementById('ai365AgInput').placeholder, poll: window.AI365_agentic.state().taskPolling,
  }));
  assert.deepEqual(run, { status: '테스트 실행 중스텝 1', cls: 'ai365-ag-status running', c9: 'run', dot: true, send: true,
    ph: '실행 중에도 보낼 수 있습니다. 지금 작업이 끝나면 이어서 처리합니다', poll: true });
  await page.fill('#ai365AgInput', '끝나면 커밋 메시지도 적어 줘');
  await page.press('#ai365AgInput', 'Enter');
  await page.waitForSelector('.ai365-ag-queue:not([hidden]) .ai365-ag-qi');
  assert.deepEqual(await texts(page, '.ai365-ag-qi'), ['대기 중끝나면 커밋 메시지도 적어 줘']);
  assert.deepEqual(db.queued, ['끝나면 커밋 메시지도 적어 줘']);
  await page.click('[data-ag="stop"]');
  await page.waitForSelector('.ai365-ag-mark.stopped');
  assert.deepEqual(callsTo(db, 'POST', '/ag_a1/stop').map(c => c.body), [{ acting_user_id: '' }]);
  await page.waitForSelector('[data-ag="send"]:not([hidden])');
  const stopped = await page.evaluate(() => ({
    mark: document.querySelector('.ai365-ag-mark.stopped').textContent, c9: document.querySelector('[data-call="c9"]').dataset.state,
    statusHidden: document.querySelector('.ai365-ag-status').hidden, stopHidden: document.querySelector('[data-ag="stop"]').hidden,
    queueHidden: document.querySelector('.ai365-ag-queue').hidden, dot: !!document.querySelector('.ai365-ag-sess[data-id="ag_a1"] .dot.running'),
    term: [...document.querySelectorAll('.ai365-ag-term .ai365-ag-titem')].map(e => [e.querySelector('.cmd').textContent, e.querySelector('.st').className]),
  }));
  assert.deepEqual(stopped, { mark: '실행을 중단했습니다 · 사용자가 중단함', c9: 'stop', statusHidden: true, stopHidden: true, queueHidden: true, dot: false,
    term: [['$ git status', 'st ok'], ['$ npm test -- --watch', 'st stop']] });

  // 예산 초과 = '계속할까요?' 카드(계속 · 멈추기, 항상 허용 없음) → 멈추기 / the budget card (continue or stop, no always-allow) → stop here
  await page.fill('#ai365AgInput', '예산을 넘겨 봐');
  await page.press('#ai365AgInput', 'Enter');
  await page.waitForSelector('.ai365-ag-approval[data-aid="b1"]');
  await page.waitForFunction(() => document.querySelector('.ai365-ag-status.waiting'));
  const budget = await page.evaluate(() => {
    const a = document.querySelector('.ai365-ag-approval[data-aid="b1"]');
    return { title: a.querySelector('.hd b').textContent, reason: a.querySelector('.rs').textContent, args: !!a.querySelector('.ar'),
      btns: [...a.querySelectorAll('[data-ag-dec]')].map(b => [b.dataset.agDec, b.textContent]), status: document.querySelector('.ai365-ag-status').textContent };
  });
  assert.deepEqual(budget, { title: '계속할까요?', reason: '스텝 또는 시간 예산을 다 썼습니다', args: false, btns: [['allow', '계속'], ['deny', '멈추기']], status: '계속할지 기다리는 중' });
  await page.click('.ai365-ag-approval[data-aid="b1"] [data-ag-dec="deny"]');
  await page.waitForSelector('.ai365-ag-approval[data-aid="b1"][data-dec="deny"]');
  await page.waitForFunction(() => document.querySelectorAll('.ai365-ag-mark.stopped').length === 2);
  assert.deepEqual(callsTo(db, 'POST', '/ag_a1/approvals/b1').map(c => c.body), [{ acting_user_id: '', decision: 'deny' }]);
  assert.match(await page.textContent('.ai365-ag-approval[data-aid="b1"] .res'), /^멈춤\d{2}:\d{2}$/);
  assert.equal(await page.$eval('[data-ag="send"]', b => b.hidden), false);
});

test('permission mode and model selects PATCH the session; the title menu renames and deletes', async (t) => {
  const { page, db } = await app(t);
  await enter(page, 'ag_a1');
  assert.deepEqual(await page.evaluate(() => [document.querySelector('[data-ag-perm]').value, document.querySelector('[data-ag-model]').value,
    [...document.querySelectorAll('[data-ag-perm] option')].map(o => o.textContent), [...document.querySelectorAll('[data-ag-model] option')].map(o => o.textContent)]),
  ['ask', 'gemini-3.8-flash', ['Auto', '묻기'], ['Gemini 3.8 Flash', 'Gemini 3.7 Flash', 'Gemini 3.5 Flash-Lite']]);
  await page.selectOption('[data-ag-perm]', 'auto');
  await waitFor(() => callsTo(db, 'PATCH', '/sessions/ag_a1').length === 1);
  await page.selectOption('[data-ag-model]', 'gemini-3.5-flash-lite');
  await waitFor(() => callsTo(db, 'PATCH', '/sessions/ag_a1').length === 2);
  assert.deepEqual(callsTo(db, 'PATCH', '/sessions/ag_a1').map(c => c.body), [{ acting_user_id: '', perm_mode: 'auto' }, { acting_user_id: '', model: 'gemini-3.5-flash-lite' }]);
  await page.waitForFunction(() => document.querySelector('[data-ag-model]').value === 'gemini-3.5-flash-lite');
  assert.equal(await page.$eval('[data-ag-perm]', s => s.value), 'auto');

  // Auto 모드의 차단 명령 승인: '항상 허용'은 없고(규칙이 건너뛰지 못한다) 거부하면 도구 카드가 실패로 / a deny-list approval in Auto: no always-allow (a rule cannot skip it); Deny fails the tool card
  await page.fill('#ai365AgInput', 'README 오타 고쳐 줘');
  await page.press('#ai365AgInput', 'Enter');
  await page.waitForSelector('.ai365-ag-approval[data-aid="a1"]');
  assert.deepEqual(await page.$$eval('.ai365-ag-approval[data-aid="a1"] [data-ag-dec]', bs => bs.map(b => b.dataset.agDec)), ['allow', 'deny']);
  assert.equal(await page.textContent('.ai365-ag-approval[data-aid="a1"] .rs'), '차단 목록에 있는 명령입니다');
  await page.click('.ai365-ag-approval[data-aid="a1"] [data-ag-dec="deny"]');
  await page.waitForFunction(() => document.querySelector('[data-call="c4"]').dataset.state === 'fail' && document.querySelector('.ai365-ag-status').hidden);
  assert.deepEqual(callsTo(db, 'POST', '/ag_a1/approvals/a1').map(c => c.body), [{ acting_user_id: '', decision: 'deny' }]);
  assert.match(await page.textContent('.ai365-ag-approval[data-aid="a1"] .res'), /^거부함\d{2}:\d{2}$/);
  assert.equal(await page.evaluate(() => [...document.querySelectorAll('.ai365-ag-msg.agent')].pop().textContent), '명령을 실행하지 않았습니다.');
  await page.click('[data-call="c4"] .ai365-ag-trow');
  assert.equal(await page.textContent('[data-call="c4"] .ai365-ag-out'), '$ npm test\n사용자가 거부했습니다');

  await page.click('[data-ag="title"]');
  assert.deepEqual(await texts(page, '.ai365-ag-menu .ai365-ag-mi'), ['이름 바꾸기', '폴더 보기', '삭제']);
  await page.click('[data-ag-menu="rename"]');
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="rename"]');
  await page.fill('[data-ag-f="title"]', '리포트 최종 정리');
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => !document.querySelector('.ai365-ag-ov') && document.querySelector('.ai365-ag-title .t').textContent === '리포트 최종 정리');
  assert.deepEqual(callsTo(db, 'PATCH', '/sessions/ag_a1').pop().body, { acting_user_id: '', title: '리포트 최종 정리' });
  assert.equal(await page.textContent('.ai365-ag-sess[data-id="ag_a1"] .tt'), '리포트 최종 정리');

  await page.click('[data-ag="title"]');
  await page.click('[data-ag-menu="delete"]');
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="delete"]');
  assert.equal(await page.textContent('.ai365-ag-dname'), '리포트 최종 정리');
  await page.click('[data-ag-dlg="ok"]');
  await page.waitForSelector('.ai365-ag-sess[data-id="ag_b2"].on');
  assert.equal(callsTo(db, 'DELETE', '/sessions/ag_a1').length, 1);
  assert.equal(await page.locator('.ai365-ag-sess[data-id="ag_a1"]').count(), 0);
  assert.equal(await page.evaluate(() => localStorage.getItem('ai365_ag_last')), 'ag_b2');
});

test('the environment panel shows host, folder, branch and context; Files load lazily and preview; Terminal and Background tasks list', async (t) => {
  const { page, db } = await app(t);
  await enter(page, 'ag_a1');
  await page.waitForSelector('.ai365-ag-files .ai365-ag-fnode');
  await page.waitForSelector('.ai365-ag-tasks .ai365-ag-task');   // /tasks 는 따로 온다 / /tasks arrives on its own
  const env = await page.evaluate(() => ({
    titles: [...document.querySelectorAll('.ai365-ag-env .ai365-ag-sech > span:first-child')].map(e => e.textContent),
    kv: [...document.querySelectorAll('.ai365-ag-env .ai365-ag-kv dt')].map(dt => [dt.textContent, dt.nextElementSibling.textContent]),
    ctx: document.querySelector('[data-ag-ctx]').textContent, files: [...document.querySelectorAll('.ai365-ag-files .ai365-ag-fnode .nm')].map(e => e.textContent),
    root: document.querySelector('.ai365-ag-froot').textContent, term: [...document.querySelectorAll('.ai365-ag-term .cmd')].map(e => e.textContent),
    tasks: [...document.querySelectorAll('.ai365-ag-tasks .ai365-ag-task .lb')].map(e => e.textContent), cnt: document.querySelector('.ai365-ag-tasks .cnt').textContent,
  }));
  assert.deepEqual(env, {
    titles: ['Environment', 'Context', 'Files', 'Terminal', 'Background tasks'],
    kv: [['호스트', 'DEMO-PC'], ['작업 폴더', PA], ['추가 폴더', '없음'], ['브랜치', 'main']],
    ctx: '12%', files: ['src', 'package.json', 'README.md'], root: 'proj-a', term: ['$ git status'], tasks: ['npm run dev'], cnt: '1',
  });
  const fileGets = () => callsTo(db, 'GET', '/ag_a1/files').map(c => c.q.path);
  assert.deepEqual(fileGets(), [PA]);   // 처음엔 뿌리만 / only the root at first
  await page.locator('.ai365-ag-fnode .nm', { hasText: /^src$/ }).click();
  await page.waitForSelector('.ai365-ag-fnode[data-ag-file$="app.js"]');
  await page.locator('.ai365-ag-fnode .nm', { hasText: /^util$/ }).click();
  await page.waitForFunction(() => [...document.querySelectorAll('.ai365-ag-fnote')].some(e => e.textContent === '빈 폴더'));
  assert.deepEqual(fileGets(), [PA, PA + '\\src', PA + '\\src\\util']);
  assert.deepEqual(await texts(page, '.ai365-ag-files .ai365-ag-fnode .nm'), ['src', 'util', 'app.js', 'package.json', 'README.md']);
  await page.locator('.ai365-ag-fnode .nm', { hasText: /^README\.md$/ }).click();
  await page.waitForSelector('.ai365-ag-viewer:not([hidden]) .ai365-ag-code');
  const view = await page.evaluate(() => ({
    lines: [...document.querySelectorAll('.ai365-ag-code .r')].map(r => [r.querySelector('i').textContent, r.querySelector('span').textContent]),
    name: document.querySelector('.ai365-ag-vh b').textContent, scrollHidden: document.querySelector('.ai365-ag-scroll').hidden,
    filesOn: document.querySelector('[data-ag-view="files"]').classList.contains('on'), sel: !!document.querySelector('.ai365-ag-fnode.on[data-ag-file$="README.md"]'),
  }));
  assert.deepEqual(view, { lines: [['1', '# 프로젝트 A'], ['2', ' '], ['3', 'teh quick brown fox']], name: 'README.md', scrollHidden: true, filesOn: true, sel: true });
  await page.click('[data-ag-view="transcript"]');   // 트랜스크립트 아이콘 = 돌아가기 / the transcript icon goes back
  await page.waitForSelector('.ai365-ag-viewer[hidden]', { state: 'attached' });
  assert.equal(await page.$eval('.ai365-ag-scroll', e => e.hidden), false);

  await page.click('.ai365-ag-term .ai365-ag-tih');
  assert.equal(await page.textContent('.ai365-ag-term .ai365-ag-out'), 'On branch main\nnothing to commit, working tree clean');
  await page.click('[data-ag-view="panel"]');
  assert.deepEqual(await page.evaluate(() => [document.querySelector('.ai365-ag').classList.contains('noenv'), getComputedStyle(document.querySelector('.ai365-ag-env')).display]), [true, 'none']);
  await page.click('[data-ag-view="terminal"]');   // 터미널 아이콘이 패널을 다시 펴고 그 섹션으로 / the terminal icon reopens the panel at that section
  assert.equal(await page.evaluate(() => document.querySelector('.ai365-ag').classList.contains('noenv')), false);
  await page.click('[data-ag-sec="files"]');
  assert.equal(await page.evaluate(() => document.querySelector('.ai365-ag-files').classList.contains('shut')), true);
  await page.click('.ai365-ag-sess[data-id="ag_b2"]');
  await page.waitForFunction(() => [...document.querySelectorAll('.ai365-ag-kv dd')].some(d => d.textContent === 'git 저장소 아님'));
  assert.deepEqual(await texts(page, '.ai365-ag-tasks .ai365-ag-none'), ['실행 중인 작업이 없습니다']);
});

test('English labels after the language toggle, fixed English section titles, and back to Korean', async (t) => {
  const { page } = await app(t);
  await enter(page, 'ag_a1');
  await page.fill('#ai365AgInput', 'README 오타 고쳐 줘');
  await page.press('#ai365AgInput', 'Enter');
  await page.waitForSelector('.ai365-ag-approval[data-aid="a1"] [data-ag-dec="always"]');
  await page.click('#ai365-lang-toggle');
  // 사이드바는 adapter 가 바로 옮기고, 셸 본문은 80ms 뒤 다시 그린다(report_dash 와 같은 방식) → 둘 다 기다린다
  // The adapter translates the sidebar at once and the shell body re-renders 80 ms later (the report_dash way), so wait for both
  await page.waitForFunction(() => document.querySelector('[data-ag="new"]').textContent === 'New session'
    && document.querySelector('.ai365-ag-approval [data-ag-dec="allow"]').textContent === 'Allow');
  const en = await page.evaluate(() => ({
    search: document.querySelector('[data-ag="search"]').placeholder, ph: document.getElementById('ai365AgInput').placeholder,
    perm: [...document.querySelectorAll('[data-ag-perm] option')].map(o => o.textContent), titles: [...document.querySelectorAll('.ai365-ag-sech > span:first-child')].map(e => e.textContent),
    dt: [...document.querySelectorAll('.ai365-ag-kv dt')].map(e => e.textContent), btns: [...document.querySelectorAll('.ai365-ag-approval [data-ag-dec]')].map(b => b.textContent),
    reason: document.querySelector('.ai365-ag-approval .rs').textContent, status: document.querySelector('.ai365-ag-status').textContent,
    tips: [...document.querySelectorAll('.ai365-ag-hr [data-ag-view]')].map(b => b.dataset.tip), pill: [...document.querySelectorAll('#viewWork .ai365-ca [data-ca]')].map(b => b.textContent),
    sum: document.querySelector('.ai365-ag-sum').textContent, ctx: document.querySelector('.ai365-ag-ctxs .ai365-ag-mu').textContent, brand: document.querySelector('.ai365-ag-stop .nm').textContent,
  }));
  assert.deepEqual(en, {
    search: 'Search sessions', ph: 'You can send while it runs. It is handled after the current task', perm: ['Auto', 'Ask'],
    titles: ['Environment', 'Context', 'Files', 'Terminal', 'Background tasks'], dt: ['Host', 'Working folder', 'Extra folders', 'Branch'],
    btns: ['Allow', 'Deny', 'Always allow in this session'], reason: 'Ask mode needs your approval', status: 'Waiting for approval',
    tips: ['Transcript', 'Terminal', 'Files', 'Hide panel'], pill: ['Chat', 'Agentic'], sum: 'Complete·2 steps·5.2s·~3.1k tokens', ctx: 'Context used', brand: 'Agentic',
  });
  await shot(page, 'ag_5_en.png');
  await page.click('#ai365-lang-toggle');
  await page.waitForFunction(() => document.querySelector('[data-ag="new"]').textContent === '새 세션'
    && document.querySelector('.ai365-ag-approval [data-ag-dec="allow"]').textContent === '허용');
  assert.deepEqual(await page.evaluate(() => [[...document.querySelectorAll('.ai365-ag-sech > span:first-child')].map(e => e.textContent),
    document.querySelector('.ai365-ag-approval [data-ag-dec]').textContent, document.querySelector('[data-ag-perm] option[value="auto"]').textContent]),
  [['Environment', 'Context', 'Files', 'Terminal', 'Background tasks'], '허용', 'Auto']);
});
