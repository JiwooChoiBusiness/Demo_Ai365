// 실행: Playwright 가 NODE_PATH 에 있을 때 node --test --test-concurrency=1 tests/test_agentic_browser_ui.cjs
// Agentic 내 컴퓨터 폴더(브라우저) 세션(static/agentic.js · static/adapter.js, 2026-10-20, docs/agentic-browser-folder-contract.md F · G · H 절과
// 변경 기록 · 프런트 적대 검토 반영): 새 세션 대화 상자의 [내 컴퓨터 폴더 열기…] · 빈 화면 버튼 · 세션 생성(POST 본문 kind · folder) · 사이드바
// 태그 · 환경 패널 · 숨긴 섹션 · 메뉴 · Files 트리와 뷰어(핸들) · 스트림 tool_request 를 받아 list · read · write · walk · grep · 문서 extract 로
// 답함(본문 모양 · mtime 숫자 · '..' 거절 · 경로 접두는 벗기지 않음 · flags · glob_re) · 인코딩 보존(BOM · UTF-16 · cp949 거절) · done 처리 ·
// 답 재전송(네트워크 · 5xx) · 권한(모드별 폴리필, prompt → [허용], 읽기 전용 핸들 쓰기 → denied → 안내 줄, 거부 → [다시 시도]) · 핸들 없음 →
// [폴더 열기] · 세션별 핸들(같은 이름 폴더를 빌리지 않음 · /clear 는 핸들을 옮김) · 다른 이름 다시 연결 = confirm · /extract 413 · 422 ·
// 네트워크 실패 · 원격 클라이언트(서버 폴더 UI 없음) · 지원 안 하는 브라우저 · 주소 안내 · browser_folders false · 선택 창 취소 · EN 라벨 ·
// 느린 첫 목록 경합 · 채팅 컴포저 + 항목 → Agentic 전환 + 세션 생성. 목업 + adapter + agentic.js 를 가짜 원점에 올리고 /api/agentic/* 는
// page.route 메모리 스텁, File System Access API 는 page.addInitScript 의 메모리 폴리필(아래 fsPolyfill)이다. 앱 서버 · DB · LLM ·
// 실제 폴더 없음. 캡처는 AI365_SHOTS 폴더(있을 때만).
// Run with Playwright on NODE_PATH: node --test --test-concurrency=1 tests/test_agentic_browser_ui.cjs
// Agentic browser-folder sessions (static/agentic.js and static/adapter.js, 2026-10-20; sections F, G and H of the contract, its change
// log and the front-end adversarial review): the dialog's [Open a folder on my computer…], the empty-state buttons, session creation
// (POST body kind and folder), the sidebar tag, the environment panel, hidden sections, the menu, the Files tree and viewer (handle),
// stream tool_request events answered with list, read, write, walk, grep and document extraction (body shapes, numeric mtime, '..'
// refused, no prefix stripping, flags, glob_re), encoding kept on write (BOM, UTF-16, cp949 refused), done handling, answer resends
// (network, 5xx), permissions (a mode-aware polyfill: prompt → [Allow], a write on a read-only handle → denied → the bar, denied →
// [Retry]), no handle → [Open folder], per-session handles (same-named folders are never borrowed, /clear carries the handle), relinking
// a differently named folder via confirm, /extract 413, 422 and network failures, remote clients (no server-folder UI), the
// unsupported browser or address note, browser_folders false, picker cancels, English labels, the slow-first-list race, and the chat
// composer's + item switching to Agentic and creating the session. The mockup, adapter and agentic.js run on a fake origin;
// /api/agentic/* is an in-memory page.route stub and the File System Access API an in-memory polyfill from page.addInitScript
// (fsPolyfill below). No app server, DB, LLM or real folder. Screenshots go to AI365_SHOTS when set.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const read = rel => fs.readFileSync(path.join(__dirname, '..', rel), 'utf8').replace(/\r\n/g, '\n');
const mockup = read('frontend/ai365-mockup.html');
const adapter = read('static/adapter.js');
const agentic = read('static/agentic.js');
const ORIGIN = 'http://agbr.test';
const HTML = mockup.replace('</body>', '<script src="/static/adapter.js"></script><script src="/static/agentic.js"></script></body>');
const SHOTS = process.env.AI365_SHOTS || '';

const DESK = 'C:\\Users\\demo\\Desktop', PA = DESK + '\\proj-a';
const MODELS = [
  { id: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash' },
  { id: 'gemini-3.7-flash', label: 'Gemini 3.7 Flash' },
  { id: 'gemini-3.5-flash-lite', label: 'Gemini 3.5 Flash-Lite' },
];
const T0 = Date.UTC(2026, 9, 20, 1, 0, 0);   // 폴리필 파일의 수정 시각(ms) = 2026-10-20 10:00 KST / the polyfill files' mtime (ms)
const MAXB = 10 * 1024 * 1024;
// '경동' 폴더(문자열 = 글 파일, {bytes} = 이진, 객체 = 폴더) / the '경동' folder (string = text file, {bytes} = binary, object = folder)
const README = '# 경동 프로젝트\n\n안내 문서입니다.\n', PLAN = '# 계획\nTODO 일정 잡기\n', APP = 'console.log(1);\n// TODO 고치기\n', XJS = 'export const x = 1; // todo\n';
const KD = {
  'README.md': README,
  'logo.png': { bytes: [137, 80, 78, 71, 0, 0, 0, 13, 73, 72, 68, 82] },
  docs: { 'report.docx': { bytes: [80, 75, 3, 4, 0, 0, 8, 0] }, 'plan.md': PLAN },
  src: { 'app.js': APP, util: { 'x.js': XJS } },
  node_modules: { dep: { 'index.js': '// TODO 무시\n' } },
};
const B = s => Buffer.byteLength(s);
const bytesOf = (...parts) => [].concat(...parts.map(p => Array.from(typeof p === 'string' ? Buffer.from(p) : p)));
const u16be = s => { const b = Buffer.from(s, 'utf16le'); for (let i = 0; i < b.length; i += 2) { const x = b[i]; b[i] = b[i + 1]; b[i + 1] = x; } return b; };

// 메모리 File System Access 폴리필(페이지 안에서 돈다). 권한은 모드별이다: window.__fsPerm = readwrite, window.__fsRead = read(쓰기 권한이
// 있으면 읽기도 된다). requestPermission({mode:'readwrite'}) 은 window.__fsGrant 로 바뀐다. 읽기(entries · getFile · 열기)는 읽기 권한,
// 쓰기(createWritable · create:true)는 readwrite 가 없으면 NotAllowedError. 선택 창은 window.__fsPickQueue 의 다음 열쇠(없거나 'abort' =
// 취소)를 연다. __fsBuild(열쇠, spec, 이름) 로 이름이 같은 다른 폴더도 만든다. 쓴 바이트는 그대로(Uint8Array) 남는다.
// An in-memory File System Access polyfill (runs in the page). Permissions are per mode: window.__fsPerm = readwrite, window.__fsRead =
// read (readwrite implies read). requestPermission({mode:'readwrite'}) turns into window.__fsGrant. Reads (entries, getFile, opening)
// need read, writes (createWritable, create:true) need readwrite, else NotAllowedError. The picker opens the next key in
// window.__fsPickQueue (none or 'abort' = cancel); __fsBuild(key, spec, name) makes same-named distinct folders; written bytes stay as is.
function fsPolyfill(cfg) {
  const err = (name, msg) => new DOMException(msg || name, name);
  window.__fsPerm = 'granted'; window.__fsRead = 'granted'; window.__fsGrant = 'granted';
  window.__fsPickQueue = []; window.__fsPicks = []; window.__fs = {}; window.__fsCalls = { query: 0, request: 0, modes: [] };
  const dirNode = () => ({ t: 'd', c: {} }), fileNode = d => ({ t: 'f', d: d, m: cfg.t0 });
  window.__fsBuild = function (key, spec, name) {
    const build = s => {
      const n = dirNode();
      Object.keys(s || {}).forEach(k => {
        const v = s[k];
        n.c[k] = typeof v === 'string' ? fileNode(v) : (v && Array.isArray(v.bytes) ? fileNode(new Uint8Array(v.bytes)) : build(v));
      });
      return n;
    };
    const root = build(spec);
    root.name = name || key;
    window.__fs[key] = root;
  };
  // '열쇠/a/b' → 글이면 문자열, 바이트면 숫자 배열, 폴더면 항목 이름들 / 'key/a/b' → a string, a byte array, or a folder's names
  window.__fsGet = function (p) {
    let n = { t: 'd', c: window.__fs };
    for (const part of p.split('/')) { if (!n || n.t !== 'd') return undefined; n = n.c[part]; }
    return n && n.t === 'f' ? (typeof n.d === 'string' ? n.d : Array.from(n.d)) : (n ? Object.keys(n.c) : undefined);
  };
  const canRead = () => window.__fsPerm === 'granted' || window.__fsRead === 'granted';
  const needRead = () => { if (!canRead()) throw err('NotAllowedError', 'The request is not allowed by the user agent.'); };
  const needWrite = () => { if (window.__fsPerm !== 'granted') throw err('NotAllowedError', 'The request is not allowed by the user agent.'); };
  const perms = h => {
    h.queryPermission = async o => {
      window.__fsCalls.query += 1; window.__fsCalls.modes.push(o && o.mode);
      return o && o.mode === 'readwrite' ? window.__fsPerm : (canRead() ? 'granted' : window.__fsRead);
    };
    h.requestPermission = async o => {
      window.__fsCalls.request += 1; window.__fsCalls.modes.push(o && o.mode);
      if (o && o.mode === 'readwrite') { window.__fsPerm = window.__fsGrant; return window.__fsPerm; }
      return canRead() ? 'granted' : window.__fsRead;
    };
  };
  const fileHandle = (name, node) => {
    const h = { kind: 'file', name };
    perms(h);
    h.getFile = async () => { needRead(); return new File([node.d], name, { lastModified: node.m }); };
    h.createWritable = async () => {
      needWrite();
      let buf = '';
      return {
        write: async x => {
          if (typeof x === 'string') buf = x;
          else if (x instanceof Blob) buf = new Uint8Array(await x.arrayBuffer());
          else buf = ArrayBuffer.isView(x) ? new Uint8Array(x.buffer.slice(x.byteOffset, x.byteOffset + x.byteLength)) : new Uint8Array(x);
        },
        close: async () => { node.d = buf; node.m = cfg.t0 + 60000; },
        abort: async () => {},
      };
    };
    return h;
  };
  const dirHandle = (name, node) => {
    const h = { kind: 'directory', name };
    perms(h);
    h.entries = async function* () { needRead(); for (const k of Object.keys(node.c)) { const v = node.c[k]; yield [k, v.t === 'd' ? dirHandle(k, v) : fileHandle(k, v)]; } };
    h.values = async function* () { for await (const pair of h.entries()) yield pair[1]; };
    h.getDirectoryHandle = async (k, o) => {
      needRead();
      let v = node.c[k];
      if (!v) { if (!(o && o.create)) throw err('NotFoundError', 'A requested file or directory could not be found.'); needWrite(); v = node.c[k] = dirNode(); }
      if (v.t !== 'd') throw err('TypeMismatchError', 'The path supplied exists, but was not an entry of requested type.');
      return dirHandle(k, v);
    };
    h.getFileHandle = async (k, o) => {
      needRead();
      let v = node.c[k];
      if (!v) { if (!(o && o.create)) throw err('NotFoundError', 'A requested file or directory could not be found.'); needWrite(); v = node.c[k] = fileNode(''); }
      if (v.t !== 'f') throw err('TypeMismatchError', 'The path supplied exists, but was not an entry of requested type.');
      return fileHandle(k, v);
    };
    return h;
  };
  window.showDirectoryPicker = async function (opts) {
    window.__fsPicks.push(opts === undefined ? null : JSON.parse(JSON.stringify(opts)));
    const next = window.__fsPickQueue.shift();
    if (!next || next === 'abort') throw err('AbortError', 'The user aborted a request.');
    if (!window.__fs[next]) window.__fsBuild(next, {});
    window.__fsPerm = 'granted';   // mode: 'readwrite' 로 고르면 허용된다 / picking with mode readwrite grants access
    const root = window.__fs[next];
    return dirHandle(root.name || next, root);
  };
}

function sess(o) {   // 2차 모양 + kind / the phase-2 shape plus kind
  return Object.assign({ owner: '', kind: 'local', title: '', folder: '', extra_folders: [], model: 'gemini-3.8-flash', effort: 'auto', perm_mode: 'auto', status: 'idle',
    context_pct: 0, rules: [], steps: 0, last_seq: 0, created: '2026-10-20T09:00:00', updated: '2026-10-20T09:00:00',
    connectors: [], notify: false, seen_seq: 0, prev_perm: '', hooks_trust: '', compact_seq: 0 }, o);
}
const light = s => ({ id: s.id, kind: s.kind, title: s.title, folder: s.folder, model: s.model, perm_mode: s.perm_mode, status: s.status, updated: s.updated,
  created: s.created, steps: s.steps, notify: s.notify, seen_seq: s.seen_seq, last_seq: s.last_seq });

function makeDb(tweak) {
  let clock = 0, rn = 0;
  const db = {
    host: 'DEMO-PC', n: 0, calls: [], dialogs: [], acceptDialogs: false, remote: false, bf: true, abortResults: 0, failResults: 0,
    now: () => { clock += 1; return '2026-10-20T10:' + String(10 + Math.floor(clock / 60)).padStart(2, '0') + ':' + String(clock % 60).padStart(2, '0'); },
    settings: { allowed_folders: [DESK], default_perm: 'auto', default_model: 'gemini-3.8-flash', deny_commands: [],
      budgets: { max_steps: 200, max_minutes: 120, max_sessions: 3, bash_timeout_sec: 120, max_output_chars: 20000, compact_pct: 80, max_subagents: 3, subagent_max_steps: 60 },
      notify_default: false, commands: [], skills: [], hooks: [] },
    sessions: [sess({ id: 'ag_a', title: '리포트 정리', folder: PA, updated: '2026-10-20T09:00:00' })],
    events: { ag_a: [] },
    live: {},       // 세션 → 스트림으로 보낼 transient(tool_request) / session → transient payloads for the stream
    reqs: {},       // request_id → {sid, op, args, answered, by, answer}
    results: [],    // 받아들인 POST tool-results 본문 / accepted POST tool-results bodies
    extracts: [],   // POST /extract
    outputs: {},
  };
  db.sess = sid => db.sessions.find(x => x.id === sid);
  db.push = (sid, kind, payload) => {
    const evs = db.events[sid];
    evs.push({ seq: evs.length + 1, ts: db.now(), kind, payload });
    db.sess(sid).last_seq = evs.length;
  };
  // 서버 루프가 브라우저에 도구 요청을 보낸다(계약 B1 · E) / the server loop sends the browser a tool request (contract B1, E)
  db.ask = (sid, op, args) => {
    const id = 'br' + String(++rn).padStart(10, '0');
    db.reqs[id] = { sid, op, args, answered: false };
    (db.live[sid] = db.live[sid] || []).push({ request_id: id, session_id: sid, op, args, ts: db.now() });
    return id;
  };
  // 다른 탭이 먼저 답했다(EMIT done) / another tab answered first (EMIT done)
  db.other = id => {
    const r = db.reqs[id];
    r.answered = true; r.by = 'other';
    (db.live[r.sid] = db.live[r.sid] || []).push({ request_id: id, done: true });
  };
  db.push('ag_a', 'user', { text: 'README 를 요약해 줘' });
  db.push('ag_a', 'assistant', { text: '요약했습니다.' });
  db.push('ag_a', 'status', { state: 'idle' });
  db.sess('ag_a').seen_seq = db.sess('ag_a').last_seq;
  if (tweak) tweak(db);
  return db;
}

async function stream(route, db, sid, afterSeq) {
  const t0 = Date.now(), has = () => (db.events[sid] || []).some(e => e.seq > afterSeq) || (db.live[sid] || []).length > 0;
  while (Date.now() - t0 < 1200 && !has()) await new Promise(r => setTimeout(r, 40));
  const evs = (db.events[sid] || []).filter(e => e.seq > afterSeq), live = (db.live[sid] || []).splice(0);
  let body = evs.map(e => 'id: ' + e.seq + '\ndata: ' + JSON.stringify(e) + '\n\n').join('')
    + live.map(p => 'event: tool_request\ndata: ' + JSON.stringify(p) + '\n\n').join('');   // 계약 E: transient = event: tool_request / contract E
  if (!body) body = ': ping\n\n';
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
  if (rest === '/settings') {   // 서버 2026-10-20: browser_folders · remote(원격이면 folder_picker false) / browser_folders and remote (folder_picker false when remote)
    const out = { settings: db.settings, host: db.host, folder_picker: !db.remote, remote: !!db.remote };
    if (db.bf !== undefined) out.browser_folders = db.bf;
    return json(out);
  }
  if (rest === '/connectors') return json({ connectors: [] });
  if (rest === '/extract' && method === 'POST') {   // multipart file + acting_user_id(계약 E) / contract E
    let raw = null;
    try { raw = req.postDataBuffer(); } catch (e) { raw = null; }
    const txt = raw ? raw.toString('utf8') : '', fm = /filename="([^"]*)"/.exec(txt), am = /name="acting_user_id"\r\n\r\n([^\r]*)\r\n/.exec(txt);
    const name = fm ? fm[1] : null;
    db.extracts.push({ q, filename: name, acting: am ? am[1] : null });
    if (name === 'big.pdf') return json({ detail: '파일이 너무 큽니다(20MB 초과)' }, 413);
    if (name === 'bad.docx') return json({ detail: '지원하지 않는 문서 형식' }, 422);
    if (name === 'net.xlsx') return route.abort('failed');
    return json({ text: '문서 본문', chars: 5, truncated: false });
  }
  if (rest === '/sessions' && method === 'GET') {   // listDelay = 목록을 먼저 만들고 늦게 답한다(느린 첫 응답) / build the list first, answer late (a slow first answer)
    const list = { sessions: db.sessions.slice().sort((a, b) => b.updated.localeCompare(a.updated)).map(light) };
    if (db.listDelay) await new Promise(r => setTimeout(r, db.listDelay));
    return json(list);
  }
  if (rest === '/sessions' && method === 'POST') {
    const kind = body.kind || 'local', folder = String(body.folder || '');
    if (kind !== 'local' && kind !== 'browser') return json({ detail: 'kind 는 local 또는 browser' }, 422);
    if (kind === 'local' && db.remote) return json({ detail: '원격에서는 내 컴퓨터 폴더 세션만 쓸 수 있습니다' }, 403);
    if (kind === 'local' && !folder.toLowerCase().startsWith(DESK.toLowerCase() + '\\')) return json({ detail: '허용 폴더 밖입니다' }, 422);
    if (kind === 'browser' && (!folder || /[\\/:*?"<>|]/.test(folder))) return json({ detail: '폴더 이름이 올바르지 않습니다' }, 422);
    const now = db.now(), s = sess({ id: 'ag_new' + (++db.n), kind, title: body.title || (kind === 'browser' ? folder : folder.split('\\').pop()), folder,
      model: body.model || db.settings.default_model, perm_mode: body.perm_mode || db.settings.default_perm, created: now, updated: now });
    db.sessions.push(s); db.events[s.id] = [];
    return json({ session: s });
  }
  const m = /^\/sessions\/([^/]+)(\/.*)?$/.exec(rest);
  if (!m) return json({ detail: 'no route' }, 404);
  const sid = decodeURIComponent(m[1]), tail = m[2] || '', s = db.sess(sid);
  if (!s) return json({ detail: '세션이 없습니다' }, 404);
  const evs = db.events[sid] || (db.events[sid] = []), br = s.kind === 'browser';
  if (!tail && method === 'GET') return json({ session: s, git: br ? { repo: false, browser: true } : { repo: false } });
  if (!tail && method === 'PATCH') {
    ['title', 'model', 'perm_mode', 'connectors', 'notify'].forEach(k => { if (k in body) s[k] = body[k]; });
    s.updated = db.now();
    return json({ session: s });
  }
  if (!tail && method === 'DELETE') { db.sessions = db.sessions.filter(x => x.id !== sid); return json({ ok: true }); }
  if (tail === '/events') return json({ events: evs.filter(e => e.seq > Number(q.after || 0)).slice(0, Number(q.limit || 500)), last_seq: evs.length });
  if (tail === '/stream') return stream(route, db, sid, Number(q.after || 0));
  if (tail === '/messages' && method === 'POST') {   // /clear = 같은 이름 · 같은 설정의 새 세션(계약 D) / /clear: a new session with the same name and settings (contract D)
    const text = String(body.text || '').trim();
    if (text === '/clear') {
      const now = db.now(), n = sess({ id: 'ag_new' + (++db.n), kind: s.kind, title: s.title, folder: s.folder, model: s.model, perm_mode: s.perm_mode, created: now, updated: now });
      db.sessions.push(n); db.events[n.id] = [];
      db.push(sid, 'user', { text: '/clear', command: 'clear' });
      db.push(sid, 'assistant', { text: '새 세션을 열었습니다.', command: 'clear' });
      return json({ queued: false, command: 'clear', session: n });
    }
    db.push(sid, 'user', { text });
    return json({ queued: false, session: s });
  }
  if (tail === '/files') return br ? json({ detail: '내 컴퓨터 폴더는 브라우저가 직접 읽습니다' }, 409) : json({ kind: 'dir', path: q.path || s.folder, rel: '', entries: [], truncated: false });
  if (tail === '/tasks') return json({ tasks: [] });
  if (tail === '/commands') return json({ commands: [] });
  if (tail === '/seen' && method === 'POST') { s.seen_seq = Math.max(s.seen_seq, Math.min(Number(body.seq) || 0, s.last_seq)); return json({ session: s }); }
  if (tail === '/changes' || tail === '/checkpoints') return br ? json({ detail: '내 컴퓨터 폴더 세션에서는 쓸 수 없습니다' }, 409)
    : json(tail === '/changes' ? { repo: false, branch: null, files: [], added: 0, removed: 0, count: 0, truncated: false, last_checkpoint: null } : { checkpoints: [] });
  if (tail === '/outputs') return json({ outputs: db.outputs[sid] || [] });
  if (tail === '/tool-requests') {
    return json({ requests: Object.keys(db.reqs).filter(k => db.reqs[k].sid === sid && !db.reqs[k].answered)
      .map(k => ({ request_id: k, op: db.reqs[k].op, args: db.reqs[k].args, ts: '2026-10-20T10:00:00' })) });
  }
  if (tail === '/tool-results' && method === 'POST') {   // 계약 E: 200 · 모르는 id 404 · 이미 답함 409 / contract E
    if (db.abortResults > 0) { db.abortResults -= 1; return route.abort('failed'); }   // 네트워크 실패 / a network failure
    if (db.failResults > 0) { db.failResults -= 1; return json({ detail: '잠시 후 다시 시도하세요' }, 503); }
    db.results.push(body);
    const r = db.reqs[body.request_id];
    if (!r || r.sid !== sid) return json({ detail: '요청이 없습니다' }, 404);
    if (r.answered) return json({ detail: '이미 답한 요청입니다' }, 409);
    r.answered = true; r.by = 'browser'; r.answer = body;
    (db.live[sid] = db.live[sid] || []).push({ request_id: body.request_id, done: true });
    return json({ accepted: true });
  }
  return json({ detail: 'no route' }, 404);
}

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });
// 메모리가 빠듯한 PC 에서 브라우저가 죽으면 다음 테스트를 위해 다시 띄운다(죽은 테스트는 그대로 실패) / relaunch when the browser died on a
// memory-starved PC so later tests still run (the test that hit it still fails)
async function liveBrowser() {
  if (!browser || !browser.isConnected()) browser = await chromium.launch({ channel: 'msedge', headless: true });
  return browser;
}

// noFs = 폴리필 없이(가짜 http 원점이라 showDirectoryPicker 가 없다) / noFs = no polyfill (the fake http origin has no showDirectoryPicker)
async function app(t, opts) {
  opts = opts || {};
  const db = makeDb(opts.tweak);
  const page = await (await liveBrowser()).newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => { db.dialogs.push(d.message()); (db.acceptDialogs ? d.accept() : d.dismiss()).catch(() => {}); });
  t.after(async () => { await page.close(); assert.deepEqual(errors, []); });
  if (!opts.noFs) await page.addInitScript(fsPolyfill, { t0: T0 });
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
    if (p === '/api/flows') return json({ flows: [], agent_labels: {} });
    return p.startsWith('/api/') ? json({ detail: 'stub' }, 404) : route.abort();
  };
  await page.route('**/*', route => handle(route).catch(() => {}));
  await page.goto(ORIGIN + '/');
  await page.waitForSelector('#viewHome.active .ai365-ca');
  await page.evaluate(id => localStorage.setItem('ai365_ag_last', id), opts.last || 'ag_a');
  return { page, db };
}
async function enter(page, sid) {
  await page.click('#viewHome [data-ca="agentic"]');
  if (!sid) { await page.waitForSelector('.ai365-ag-tx .ai365-ag-empty'); return; }
  await page.waitForSelector('.ai365-ag-sess[data-id="' + sid + '"].on');
  await page.waitForSelector('.ai365-ag-tx .ai365-ag-status', { state: 'attached' });
}
async function waitFor(fn, ms) {
  const t0 = Date.now();
  while (Date.now() - t0 < (ms || 15000)) { if (await fn()) return; await new Promise(r => setTimeout(r, 40)); }
  throw new Error('timed out waiting');
}
const answered = (db, ids) => waitFor(() => ids.every(id => db.reqs[id].answered));
const posts = db => db.calls.filter(c => c.method === 'POST' && c.path === '/api/agentic/sessions');
const build = (page, key, spec, name) => page.evaluate(([k, s, n]) => window.__fsBuild(k, s, n), [key, spec, name || '']);
const pick = (page, key) => page.evaluate(k => window.__fsPickQueue.push(k), key);
const texts = (page, sel) => page.$$eval(sel, els => els.map(e => e.textContent.trim()));
const toastIs = (page, text) => page.waitForFunction(t => (document.getElementById('toast') || {}).textContent === t, text);
const fsState = page => page.evaluate(() => window.AI365_agentic.state().fs);
const bar = page => page.evaluate(() => {
  const b = document.querySelector('.ai365-ag-fsbar');
  if (!b || b.hidden) return null;
  const btn = b.querySelector('button');
  return { state: b.dataset.state, text: b.querySelector('.tx').textContent, btn: btn ? [btn.dataset.ag, btn.textContent] : null };
});
const kv = page => page.evaluate(() => [...document.querySelectorAll('.ai365-ag-env .ai365-ag-kv dt')].map(dt => [dt.textContent, dt.nextElementSibling.textContent]));
const shot = async (page, name) => {
  if (!SHOTS) return;
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: path.join(SHOTS, name) });
};
// 내 컴퓨터 폴더 세션을 빈 화면 단추로 만들고 연결될 때까지 / create a browser session from the empty state and wait until it is connected
async function fsSession(page, db, key) {
  const sid = 'ag_new' + (db.n + 1);
  await pick(page, key);
  await page.click('.ai365-ag-tx [data-ag="fsopen"]');
  await page.waitForSelector('.ai365-ag-sess[data-id="' + sid + '"].on');
  await page.waitForSelector('.ai365-ag-env [data-ag-fsst="ok"]');
  return sid;
}
// 대화 상자로 내 컴퓨터 폴더 세션을 만든다 / create a browser session through the dialog
async function fsDialogSession(page, db, key) {
  const sid = 'ag_new' + (db.n + 1);
  await page.click('[data-ag="new"]');
  await pick(page, key);
  await page.click('.ai365-ag-ov [data-ag="fsopen"]');
  await page.waitForSelector('.ai365-ag-sess[data-id="' + sid + '"].on');
  await page.waitForSelector('.ai365-ag-env [data-ag-fsst="ok"]');
  return sid;
}
async function openSess(page, sid) {
  await page.click('.ai365-ag-sess[data-id="' + sid + '"]');
  await page.waitForSelector('.ai365-ag-sess[data-id="' + sid + '"].on');
  await page.waitForFunction(() => !!document.querySelector('.ai365-ag-env [data-ag-fsst]'));
}

test('the new-session dialog puts [Open a folder on my computer…] on top; a cancel does nothing; a pick creates a browser session with the dialog fields and opens it', async (t) => {
  const { page, db } = await app(t, { tweak: d => { d.outputs.ag_new1 = [{ path: '경동/docs/plan.md', rel: 'docs/plan.md', kind: 'created', bytes: 30, ts: '2026-10-20T10:05:00', exists: true }]; } });
  await build(page, '경동', KD);
  await enter(page, 'ag_a');
  await page.click('[data-ag="new"]');
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="new"]');
  assert.deepEqual(await page.evaluate(() => {
    const ov = document.querySelector('.ai365-ag-ov[data-ag-ov="new"]'), fo = ov.querySelector('[data-ag="fsopen"]');
    return { order: [...ov.querySelector('.ai365-ag-dlg').children].slice(0, 5).map(k => k.tagName === 'H3' ? 'h3' : k.className.split(' ')[0]),
      btn: [fo.textContent, fo.classList.contains('pri')], note: ov.querySelector('.ai365-ag-fsnew .ai365-ag-hint2').textContent, or: ov.querySelector('.ai365-ag-or').textContent,
      focus: document.activeElement.dataset.agF, pick: ov.querySelector('[data-ag="pick"]').textContent, folder: ov.querySelector('[data-ag-f="folder"]').value,
      unsupported: !!ov.querySelector('[data-ag-fsno]'), ok: !!ov.querySelector('[data-ag-dlg="ok"]') };
  }), { order: ['h3', 'ai365-ag-fsnew', 'ai365-ag-or', 'ds', 'ai365-ag-fld'], btn: ['내 컴퓨터 폴더 열기…', true],
    note: '브라우저로 내 컴퓨터의 폴더를 고릅니다. 에이전트가 그 폴더 안의 파일을 읽고 고칩니다(명령 실행 없음).', or: '또는 서버 폴더', focus: 'folder', pick: '찾아보기…', folder: PA,
    unsupported: false, ok: true });
  await shot(page, 'br_1_dialog.png');
  // 취소 = 아무것도 안 함(POST 없음 · 대화 상자 유지) / a cancel does nothing (no POST, the dialog stays)
  await pick(page, 'abort');
  await page.click('[data-ag="fsopen"]');
  await page.waitForFunction(() => window.__fsPicks.length === 1 && !document.querySelector('[data-ag="fsopen"]').disabled);
  assert.deepEqual(await page.evaluate(() => window.__fsPicks), [{ id: 'ai365-agentic', mode: 'readwrite', startIn: 'desktop' }]);
  assert.deepEqual([posts(db).length, await page.locator('.ai365-ag-ov[data-ag-ov="new"]').count()], [0, 1]);
  // 고르면 대화 상자의 제목 · 모델 · 권한 모드로 만든다 / a pick creates with the dialog's title, model and mode
  await page.fill('[data-ag-f="title"]', '경동 정리');
  await page.selectOption('[data-ag-f="model"]', 'gemini-3.7-flash');
  await page.selectOption('[data-ag-f="perm"]', 'ask');
  await pick(page, '경동');
  await page.click('[data-ag="fsopen"]');
  await page.waitForSelector('.ai365-ag-sess[data-id="ag_new1"].on');
  assert.deepEqual(posts(db).map(c => c.body), [{ acting_user_id: '', kind: 'browser', folder: '경동', title: '경동 정리', model: 'gemini-3.7-flash', perm_mode: 'ask' }]);
  await page.waitForSelector('.ai365-ag-env [data-ag-fsst="ok"]');
  await page.waitForSelector('.ai365-ag-outputs .ai365-ag-ofile');
  const ui = await page.evaluate(() => {
    const g = document.querySelector('.ai365-ag-sgrp[data-kind="browser"]');
    return {
      ov: document.querySelectorAll('.ai365-ag-ov').length,
      group: [g.querySelector('.ai365-ag-sgh > span[data-i18n-skip]:not(.tag)').textContent, g.querySelector('.ai365-ag-sgh .tag').textContent, [...g.querySelectorAll('.ai365-ag-sess')].map(b => b.dataset.id)],
      localGroup: document.querySelector('.ai365-ag-sgrp:not([data-kind]) .ai365-ag-sgh').textContent.trim(),
      icons: [...document.querySelectorAll('#viewWork .ai365-ag-hr [data-ag-view]')].map(b => b.dataset.agView),
      sections: window.AI365_agentic.state().sections, bar: document.querySelector('.ai365-ag-fsbar').hidden,
      outputs: [[...document.querySelectorAll('.ai365-ag-outputs .ai365-ag-ofile .nm')].map(e => e.textContent), document.querySelectorAll('.ai365-ag-outputs .ai365-ag-dl').length],
      perm: document.querySelector('[data-ag-perm]').value, model: document.querySelector('[data-ag-model]').value, title: document.querySelector('.ai365-ag-title .t').textContent,
      modes: [...new Set(window.__fsCalls.modes)],
    };
  });
  assert.deepEqual(ui, { ov: 0, group: ['경동', '내 컴퓨터', ['ag_new1']], localGroup: 'proj-a', icons: ['transcript', 'outputs', 'files', 'panel'],
    sections: ['env', 'ctx', 'connectors', 'files', 'outputs', 'tasks'], bar: true, outputs: [['plan.md'], 0], perm: 'ask', model: 'gemini-3.7-flash', title: '경동 정리',
    modes: ['readwrite'] });
  assert.deepEqual(await kv(page), [['호스트', '내 컴퓨터(브라우저)'], ['작업 폴더', '경동연결됨']]);
  await page.click('[data-ag="title"]');
  assert.deepEqual(await texts(page, '.ai365-ag-menu .ai365-ag-mi'), ['이름 바꾸기', '폴더 보기', '폴더 다시 연결…', '완료 알림 켜기', '삭제']);
  await page.keyboard.press('Escape');
  await shot(page, 'br_2_session.png');
  // 산출물 줄 = 핸들에서 미리 보기("<이름>/<rel>" → rel) / an output row previews from the handle ("<name>/<rel>" → rel)
  await page.click('.ai365-ag-outputs .ai365-ag-ofile');
  await page.waitForSelector('.ai365-ag-viewer:not([hidden]) .ai365-ag-code');
  assert.deepEqual(await page.evaluate(() => [document.querySelector('.ai365-ag-vh .p').textContent, [...document.querySelectorAll('.ai365-ag-code .r span')].map(s => s.textContent)]),
    ['docs/plan.md', ['# 계획', 'TODO 일정 잡기']]);
  // 서버의 /files · /changes · /checkpoints 는 부르지 않는다(브라우저 세션은 409) / the server's /files, /changes and /checkpoints are never called (409 for browser sessions)
  assert.deepEqual(db.calls.filter(c => /\/ag_new1\/(files|changes|checkpoints)/.test(c.path)).map(c => c.path), []);
  // 서버 폴더 세션으로 돌아가면 종전 화면 그대로 / back on the server-folder session the old screen is intact
  await page.click('.ai365-ag-sess[data-id="ag_a"]');
  await page.waitForFunction(() => [...document.querySelectorAll('.ai365-ag-kv dt')].some(dt => dt.textContent === '브랜치'));
  assert.deepEqual([await page.evaluate(() => window.AI365_agentic.state().sections), await page.evaluate(() => [...document.querySelectorAll('#viewWork .ai365-ag-hr [data-ag-view]')].map(b => b.dataset.agView))],
    [['env', 'ctx', 'connectors', 'files', 'changes', 'outputs', 'term', 'tasks'], ['transcript', 'terminal', 'outputs', 'files', 'panel']]);
});

test('with no sessions the empty state offers [Open a folder on my computer] and [New session on a server folder]; a pick uses the default model and mode; the Files tree and viewer read the handle', async (t) => {
  const { page, db } = await app(t, { tweak: d => { d.sessions = []; d.events = {}; } });
  await build(page, '경동', KD);
  await enter(page, '');
  assert.deepEqual(await page.evaluate(() => {
    const em = document.querySelector('.ai365-ag-tx .ai365-ag-empty');
    return { h2: em.querySelector('h2').textContent, btns: [...em.querySelectorAll('.acts button')].map(b => [b.dataset.ag, b.textContent, b.classList.contains('pri')]) };
  }), { h2: '작업 폴더를 골라 새 세션을 시작하세요', btns: [['fsopen', '내 컴퓨터 폴더 열기', true], ['newc', '서버 폴더로 새 세션', false]] });
  await shot(page, 'br_3_empty.png');
  await page.click('.ai365-ag-tx [data-ag="newc"]');   // 종전 대화 상자 / the existing dialog
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="new"]');
  await page.keyboard.press('Escape');
  const sid = await fsSession(page, db, '경동');
  assert.deepEqual(posts(db).map(c => c.body), [{ acting_user_id: '', kind: 'browser', folder: '경동', model: 'gemini-3.8-flash', perm_mode: 'auto' }]);
  // 트리: 뿌리 라벨 = 폴더 이름, 폴더 먼저 · 이름순, 폴더를 펴면 그 아래를 읽는다 / tree: the root label is the folder name, folders first by name, opening a folder reads below it
  await page.waitForSelector('.ai365-ag-files .ai365-ag-fnode');
  assert.deepEqual([await page.textContent('.ai365-ag-froot'), await texts(page, '.ai365-ag-files .ai365-ag-fnode .nm')],
    ['경동', ['docs', 'node_modules', 'src', 'logo.png', 'README.md']]);
  assert.deepEqual(await page.$eval('.ai365-ag-fnode[data-ag-file="README.md"] .sz', e => e.textContent), B(README) + ' B');
  await page.click('.ai365-ag-fnode[data-ag-dir="src"]');
  await page.waitForSelector('.ai365-ag-fnode[data-ag-file="src/app.js"]');
  assert.deepEqual(await texts(page, '.ai365-ag-files .ai365-ag-fnode .nm'), ['docs', 'node_modules', 'src', 'util', 'app.js', 'logo.png', 'README.md']);
  await page.click('.ai365-ag-fnode[data-ag-file="README.md"]');
  await page.waitForSelector('.ai365-ag-viewer:not([hidden]) .ai365-ag-code');
  assert.deepEqual(await page.evaluate(() => [document.querySelector('.ai365-ag-vh b').textContent, [...document.querySelectorAll('.ai365-ag-code .r span')].map(s => s.textContent),
    !!document.querySelector('.ai365-ag-fnode.on[data-ag-file="README.md"]')]), ['README.md', ['# 경동 프로젝트', ' ', '안내 문서입니다.'], true]);
  await shot(page, 'br_4_viewer.png');
  await page.click('.ai365-ag-fnode[data-ag-dir="docs"]');
  await page.click('.ai365-ag-fnode[data-ag-file="docs/report.docx"]');   // 문서 = 미리 보지 않는다 / a document has no preview
  await page.waitForFunction(() => (document.querySelector('.ai365-ag-viewer .ai365-ag-vnote') || {}).textContent === '미리 볼 수 없습니다');
  await page.click('.ai365-ag-fnode[data-ag-file="logo.png"]');
  await page.waitForFunction(() => (document.querySelector('.ai365-ag-viewer .ai365-ag-vnote') || {}).textContent === '이진 파일이라 미리 볼 수 없습니다');
  assert.deepEqual(db.calls.filter(c => c.path.indexOf('/' + sid + '/files') >= 0).length, 0);
});

test('tool requests from the stream run in the folder: list, read (text, document via /extract, binary), write, walk and grep with the contract shapes, numeric mtime, codes and refusals; paths are taken as sent', async (t) => {
  const { page, db } = await app(t, { tweak: d => { d.sessions = []; d.events = {}; } });
  // 폴더 안에 같은 이름의 하위 폴더 '경동'(서버가 이미 접두를 벗겨 보낸다, 계약 변경 기록) / a same-named subfolder (the server already strips the prefix; contract change log)
  await build(page, '경동', Object.assign({}, KD, { '경동': { 'inner.txt': '안쪽\n' } }));
  await enter(page, '');
  const sid = await fsSession(page, db, '경동');
  const R = 10485760;
  const ids = {
    list: db.ask(sid, 'list', { path: '' }),
    listSub: db.ask(sid, 'list', { path: 'src' }),
    same: db.ask(sid, 'list', { path: '경동' }),                  // 접두를 다시 벗기지 않는다 = 하위 폴더 / not stripped again = the subfolder
    inner: db.ask(sid, 'read', { path: '경동/inner.txt', max_bytes: R }),
    rules: db.ask(sid, 'read', { path: 'AGENTS.md', max_bytes: R }),   // 턴 시작의 규칙 파일 = 바로 notfound / the turn's rules file: notfound at once
    text: db.ask(sid, 'read', { path: 'README.md', max_bytes: R }),
    doc: db.ask(sid, 'read', { path: 'docs\\report.docx', max_bytes: R }),   // '\' → '/'
    bin: db.ask(sid, 'read', { path: './logo.png', max_bytes: R }),
    up: db.ask(sid, 'read', { path: '../secret.txt', max_bytes: R }),
    abs: db.ask(sid, 'read', { path: 'C:\\Windows\\win.ini', max_bytes: R }),
    root: db.ask(sid, 'list', { path: '/etc' }),
    missing: db.ask(sid, 'read', { path: 'nope.txt', max_bytes: R }),
    dir: db.ask(sid, 'read', { path: 'src', max_bytes: R }),
    notdir: db.ask(sid, 'list', { path: 'README.md' }),
    nolist: db.ask(sid, 'list', { path: 'nope' }),
    big: db.ask(sid, 'read', { path: 'README.md', max_bytes: 5 }),
    odd: db.ask(sid, 'rename', { path: 'a' }),
  };
  await answered(db, Object.values(ids));
  const A = k => db.reqs[ids[k]].answer, res = k => A(k).result, code = k => [A(k).ok, A(k).code];
  // mtime = File.lastModified 숫자(ms), 폴더 · 모름 = null(적대 검토 2026-10-20) / mtime is the numeric File.lastModified (ms); folders and unknown are null
  assert.deepEqual(A('list'), { acting_user_id: '', request_id: ids.list, ok: true, error: '', code: '', result: { truncated: false, total: 6, entries: [
    { name: 'docs', type: 'dir', size: 0, mtime: null }, { name: 'node_modules', type: 'dir', size: 0, mtime: null }, { name: 'src', type: 'dir', size: 0, mtime: null },
    { name: '경동', type: 'dir', size: 0, mtime: null }, { name: 'logo.png', type: 'file', size: 12, mtime: T0 }, { name: 'README.md', type: 'file', size: B(README), mtime: T0 }] } });
  assert.deepEqual(res('listSub').entries.map(e => [e.name, e.type]), [['util', 'dir'], ['app.js', 'file']]);
  assert.deepEqual([res('same').entries.map(e => e.name), res('inner').text, code('rules'), A('rules').error], [['inner.txt'], '안쪽\n', [false, 'notfound'], '파일이 없습니다: AGENTS.md']);
  assert.deepEqual(res('text'), { text: README, size: B(README), binary: false, extracted: false, truncated: false, encoding: 'utf-8' });
  assert.deepEqual(res('doc'), { text: '문서 본문', size: 8, binary: false, extracted: true, truncated: false });
  assert.deepEqual(db.extracts, [{ q: { acting_user_id: '' }, filename: 'report.docx', acting: '' }]);   // multipart file + acting_user_id 폼 필드 / form field
  assert.deepEqual(res('bin'), { text: '', size: 12, binary: true, extracted: false, truncated: false });
  assert.deepEqual([code('up'), code('abs'), code('root'), code('missing'), code('dir'), code('notdir'), code('nolist'), code('big'), code('odd')],
    [[false, 'outside'], [false, 'outside'], [false, 'outside'], [false, 'notfound'], [false, 'isdir'], [false, 'notdir'], [false, 'notfound'], [false, 'toolarge'], [false, 'exec']]);
  assert.deepEqual([A('up').result, A('missing').error, A('nolist').error, A('odd').error], [null, '파일이 없습니다: nope.txt', '폴더가 없습니다: nope', '알 수 없는 요청입니다: rename']);

  // 쓰기(먼저 끝낸 뒤 훑기 · 검색) / writes first, then walk and grep
  const w = {
    created: db.ask(sid, 'write', { path: 'notes/new.md', text: '새 파일\n' }),            // 빠진 상위 폴더도 만든다 / missing parent folders too
    edited: db.ask(sid, 'write', { path: 'README.md', text: '# 경동\n고침\n' }),
    binary: db.ask(sid, 'write', { path: 'logo.png', text: 'x' }),                        // 이진 덮어쓰기 = old_text null · UTF-8 / overwriting a binary: old_text null, UTF-8
    onDir: db.ask(sid, 'write', { path: 'src', text: 'x' }),
  };
  await answered(db, Object.values(w));
  Object.assign(w, {
    walk: db.ask(sid, 'walk', { path: '', skip: ['node_modules', '.git'], max: 50000 }),
    walkSub: db.ask(sid, 'walk', { path: 'src', skip: [], max: 50000 }),
    walkCap: db.ask(sid, 'walk', { path: '', skip: ['node_modules'], max: 2 }),
    walkFile: db.ask(sid, 'walk', { path: 'README.md', skip: [], max: 50000 }),
    grep: db.ask(sid, 'grep', { path: '', pattern: 'TODO', glob: '', by_path: false, max_results: 200, skip: ['node_modules'] }),
    grepGlob: db.ask(sid, 'grep', { path: '', pattern: 'todo', glob: 'src/**/*.js', by_path: true, max_results: 200, skip: ['node_modules'] }),
    grepSub: db.ask(sid, 'grep', { path: 'src', pattern: 'TODO|todo', glob: '*.js', by_path: false, max_results: 200, skip: [] }),
    grepFile: db.ask(sid, 'grep', { path: 'docs/plan.md', pattern: '계획', glob: '', by_path: false, max_results: 200, skip: [] }),
    grepMax: db.ask(sid, 'grep', { path: '', pattern: '.', glob: '*.md', by_path: false, max_results: 1, skip: ['node_modules'] }),
    grepBad: db.ask(sid, 'grep', { path: '', pattern: '(', glob: '', by_path: false, max_results: 200, skip: [] }),
    // 서버가 옮겨 준 flags · glob_re(u 플래그 없이, 파이썬 re.escape 의 \- 포함) / the server's flags and glob_re (no u flag, with re.escape's \-)
    grepFlags: db.ask(sid, 'grep', { path: '', pattern: 'todo', flags: 'i', glob: '*.js', glob_re: '^[^/]*\\.js$', by_path: false, max_results: 200, skip: ['node_modules'] }),
    grepEsc: db.ask(sid, 'grep', { path: '', pattern: '계획', flags: '', glob: 'p-lan.md', glob_re: '^p\\-?lan\\.md$', by_path: false, max_results: 200, skip: ['node_modules'] }),
    grepByPath: db.ask(sid, 'grep', { path: 'src', pattern: 'TODO', flags: 'i', glob: 'util/*.js', glob_re: '^util/[^/]*\\.js$', by_path: true, max_results: 200, skip: [] }),
  });
  await answered(db, Object.values(w));
  const W = k => db.reqs[w[k]].answer;
  assert.deepEqual([W('created').ok, W('created').result], [true, { created: true, bytes: B('새 파일\n'), old_text: null }]);
  assert.deepEqual(W('edited').result, { created: false, bytes: B('# 경동\n고침\n'), old_text: README });
  assert.deepEqual(W('binary').result, { created: false, bytes: 1, old_text: null });
  assert.deepEqual([W('onDir').ok, W('onDir').code], [false, 'isdir']);
  assert.deepEqual(await page.evaluate(() => [window.__fsGet('경동/notes/new.md'), window.__fsGet('경동/README.md'), window.__fsGet('경동/logo.png'), window.__fsGet('경동/notes')]),
    ['새 파일\n', '# 경동\n고침\n', 'x', ['new.md']]);
  const walk = W('walk').result;
  assert.deepEqual([walk.capped, walk.files.map(f => f.rel).sort()],
    [false, ['README.md', 'docs/plan.md', 'docs/report.docx', 'logo.png', 'notes/new.md', 'src/app.js', 'src/util/x.js', '경동/inner.txt']]);
  assert.deepEqual(walk.files.find(f => f.rel === 'docs/plan.md'), { rel: 'docs/plan.md', size: B(PLAN), mtime: T0 });
  assert.deepEqual(walk.files.find(f => f.rel === 'README.md').mtime, T0 + 60000);   // 쓴 파일의 새 수정 시각 / the written file's new mtime
  assert.deepEqual(W('walkSub').result.files.map(f => f.rel).sort(), ['app.js', 'util/x.js']);   // path 기준 / relative to `path`
  assert.deepEqual([W('walkCap').result.capped, W('walkCap').result.files.length, W('walkFile').code], [true, 2, 'notdir']);
  assert.deepEqual(W('grep').result, { matches: ['docs/plan.md:2:TODO 일정 잡기', 'src/app.js:2:// TODO 고치기'], count: 2, files: 2, truncated: false });
  assert.deepEqual(W('grepGlob').result, { matches: ['src/util/x.js:1:export const x = 1; // todo'], count: 1, files: 1, truncated: false });
  assert.deepEqual(W('grepSub').result.matches, ['src/app.js:2:// TODO 고치기', 'src/util/x.js:1:export const x = 1; // todo']);   // 세션 폴더 기준 / session-relative
  assert.deepEqual(W('grepFile').result.matches, ['docs/plan.md:1:# 계획']);
  assert.deepEqual([W('grepMax').result.count, W('grepMax').result.truncated], [1, true]);
  assert.deepEqual([W('grepBad').ok, W('grepBad').code, /^정규식 오류: /.test(W('grepBad').error)], [false, 'exec', true]);
  assert.deepEqual(W('grepFlags').result.matches, ['src/app.js:2:// TODO 고치기', 'src/util/x.js:1:export const x = 1; // todo']);
  assert.deepEqual(W('grepEsc').result.matches, ['docs/plan.md:1:# 계획']);
  assert.deepEqual(W('grepByPath').result.matches, ['src/util/x.js:1:export const x = 1; // todo']);   // by_path = grep path 기준 · 결과 = 세션 기준 / by_path relative to grep's path, results session-relative
  // 스트림의 done(우리 답의 메아리)은 아무것도 다시 보내지 않는다 / the stream's done (our own answers echoed) sends nothing again
  const n = db.results.length;
  await page.waitForTimeout(4500);
  assert.deepEqual([db.results.length, (await fsState(page)).waiting, (await fsState(page)).running, (await fsState(page)).unsent], [n, 0, 0, 0]);
});

test('an existing file keeps its encoding on write: a UTF-8 BOM and UTF-16 LE/BE (with BOM) are rewritten as such, a cp949 file is refused, new files are UTF-8', async (t) => {
  const { page, db } = await app(t, { tweak: d => { d.sessions = []; d.events = {}; } });
  await build(page, '경동', {
    'bom.txt': { bytes: bytesOf([0xEF, 0xBB, 0xBF], '가나\n') },
    'le.txt': { bytes: bytesOf([0xFF, 0xFE], Buffer.from('AB\n', 'utf16le')) },
    'be.txt': { bytes: bytesOf([0xFE, 0xFF], u16be('AB\n')) },
    'kr.txt': { bytes: [0xB0, 0xA1, 0x0A] },   // cp949 '가\n'
    'plain.txt': 'x\n',
  });
  await enter(page, '');
  const sid = await fsSession(page, db, '경동');
  const R = 10485760;
  const r = {
    bom: db.ask(sid, 'read', { path: 'bom.txt', max_bytes: R }), le: db.ask(sid, 'read', { path: 'le.txt', max_bytes: R }),
    be: db.ask(sid, 'read', { path: 'be.txt', max_bytes: R }), kr: db.ask(sid, 'read', { path: 'kr.txt', max_bytes: R }),
  };
  await answered(db, Object.values(r));
  assert.deepEqual(Object.keys(r).map(k => [db.reqs[r[k]].answer.result.text, db.reqs[r[k]].answer.result.encoding]),
    [['가나\n', 'utf-8-sig'], ['AB\n', 'utf-16'], ['AB\n', 'utf-16'], ['가\n', 'cp949']]);
  const w = {
    bom: db.ask(sid, 'write', { path: 'bom.txt', text: '다라\n' }), le: db.ask(sid, 'write', { path: 'le.txt', text: 'C가\n' }),
    be: db.ask(sid, 'write', { path: 'be.txt', text: 'C가\n' }), kr: db.ask(sid, 'write', { path: 'kr.txt', text: '나\n' }),
    plain: db.ask(sid, 'write', { path: 'plain.txt', text: 'y\n' }), fresh: db.ask(sid, 'write', { path: 'new.txt', text: '새\n' }),
  };
  await answered(db, Object.values(w));
  const W = k => db.reqs[w[k]].answer;
  assert.deepEqual([W('bom').result, W('le').result, W('be').result], [
    { created: false, bytes: 3 + B('다라\n'), old_text: '가나\n' }, { created: false, bytes: 8, old_text: 'AB\n' }, { created: false, bytes: 8, old_text: 'AB\n' }]);
  assert.deepEqual([W('kr').ok, W('kr').code, W('kr').error], [false, 'exec', 'cp949 파일은 브라우저 세션에서 다시 쓸 수 없습니다. UTF-8 로 바꿔 두세요']);
  assert.deepEqual([W('plain').result, W('fresh').result], [{ created: false, bytes: 2, old_text: 'x\n' }, { created: true, bytes: B('새\n'), old_text: null }]);
  const got = await page.evaluate(() => ['bom.txt', 'le.txt', 'be.txt', 'kr.txt', 'plain.txt', 'new.txt'].map(f => window.__fsGet('경동/' + f)));
  assert.deepEqual(got, [bytesOf([0xEF, 0xBB, 0xBF], '다라\n'), bytesOf([0xFF, 0xFE], Buffer.from('C가\n', 'utf16le')), bytesOf([0xFE, 0xFF], u16be('C가\n')),
    [0xB0, 0xA1, 0x0A], 'y\n', '새\n']);   // cp949 파일은 그대로 / the cp949 file is untouched
});

test('permission prompt: the bar asks and counts waiting requests, another tab\'s answer (done) drops one, [Allow] grants and runs the rest; a denied answer shows [Retry]', async (t) => {
  const { page, db } = await app(t);
  await build(page, '경동', KD);
  await enter(page, 'ag_a');
  await fsDialogSession(page, db, '경동');
  // 권한이 사라진 채로 다시 열면 = 안내 줄 prompt / reopening without the permission shows the prompt bar
  await page.evaluate(() => { window.__fsPerm = 'prompt'; window.__fsRead = 'prompt'; });
  await page.click('.ai365-ag-sess[data-id="ag_a"]');
  await page.waitForSelector('.ai365-ag-sess[data-id="ag_a"].on');
  await page.click('.ai365-ag-sess[data-id="ag_new1"]');
  await page.waitForSelector('.ai365-ag-fsbar[data-state="prompt"]:not([hidden])');
  assert.deepEqual(await bar(page), { state: 'prompt', text: "폴더 '경동' 접근을 허용해 주세요", btn: ['fsgrant', '허용'] });
  assert.deepEqual([await kv(page), await page.textContent('.ai365-ag-files .ai365-ag-fnote')], [[['호스트', '내 컴퓨터(브라우저)'], ['작업 폴더', '경동허용 필요']], '허용 필요']);
  const r1 = db.ask('ag_new1', 'list', { path: 'src' }), r2 = db.ask('ag_new1', 'read', { path: 'README.md', max_bytes: MAXB });
  await page.waitForFunction(() => /\(2\)$/.test((document.querySelector('.ai365-ag-fsbar .tx') || {}).textContent || ''));
  assert.equal((await bar(page)).text, "폴더 '경동' 접근을 허용해 주세요 · 에이전트가 폴더를 기다리고 있습니다(2)");
  await shot(page, 'br_5_prompt.png');
  db.other(r2);   // 다른 탭이 먼저 답했다 → done / another tab answered first → done
  await page.waitForFunction(() => /\(1\)$/.test((document.querySelector('.ai365-ag-fsbar .tx') || {}).textContent || ''));
  assert.deepEqual(db.results, []);   // 권한 전에는 아무것도 보내지 않는다 / nothing is sent before the permission
  await page.click('.ai365-ag-fsbar [data-ag="fsgrant"]');
  await answered(db, [r1]);
  await page.waitForSelector('.ai365-ag-fsbar[hidden]', { state: 'attached' });
  assert.deepEqual([db.reqs[r1].by, db.reqs[r1].answer.result.entries.map(e => e.name), db.results.map(b => b.request_id)], ['browser', ['util', 'app.js'], [r1]]);
  assert.deepEqual([await page.evaluate(() => [window.__fsCalls.request, [...new Set(window.__fsCalls.modes)]]), (await kv(page))[1]], [[1, ['readwrite']], ['작업 폴더', '경동연결됨']]);
  await page.waitForSelector('.ai365-ag-files .ai365-ag-fnode');
  // 몰래 거부되면 요청은 denied 로 답하고 안내 줄은 [다시 시도] / a silent denial answers denied and the bar offers [Retry]
  await page.evaluate(() => { window.__fsPerm = 'denied'; window.__fsRead = 'denied'; window.__fsGrant = 'denied'; });
  const r3 = db.ask('ag_new1', 'read', { path: 'README.md', max_bytes: MAXB });
  await answered(db, [r3]);
  assert.deepEqual([db.reqs[r3].answer.ok, db.reqs[r3].answer.code], [false, 'denied']);
  await page.waitForSelector('.ai365-ag-fsbar[data-state="denied"]:not([hidden])');
  assert.deepEqual(await bar(page), { state: 'denied', text: '폴더 접근이 거부되었습니다', btn: ['fsgrant', '다시 시도'] });
  await shot(page, 'br_6_denied.png');
  await page.click('.ai365-ag-fsbar [data-ag="fsgrant"]');   // 여전히 거부 = 그대로 / still denied: unchanged
  await page.waitForFunction(() => window.__fsCalls.request === 2 && !document.querySelector('.ai365-ag-fsbar [data-ag="fsgrant"]').disabled);
  assert.equal((await bar(page)).state, 'denied');
  await page.evaluate(() => { window.__fsGrant = 'granted'; window.__fsRead = 'granted'; });
  await page.click('.ai365-ag-fsbar [data-ag="fsgrant"]');
  await page.waitForSelector('.ai365-ag-fsbar[hidden]', { state: 'attached' });
  assert.equal((await fsState(page)).perm, 'granted');
});

test('a read-only handle still reads but a write answers denied and raises the bar; /extract 413, 422 and network failures answer toolarge and exec', async (t) => {
  const { page, db } = await app(t, { tweak: d => { d.sessions = []; d.events = {}; } });
  await build(page, '경동', Object.assign({}, KD, { 'big.pdf': { bytes: [37, 80, 68, 70] }, 'bad.docx': { bytes: [80, 75, 3, 4] }, 'net.xlsx': { bytes: [80, 75, 3, 4] } }));
  await enter(page, '');
  const sid = await fsSession(page, db, '경동');
  const x = {
    big: db.ask(sid, 'read', { path: 'big.pdf', max_bytes: MAXB }), bad: db.ask(sid, 'read', { path: 'bad.docx', max_bytes: MAXB }),
    net: db.ask(sid, 'read', { path: 'net.xlsx', max_bytes: MAXB }),
  };
  await answered(db, Object.values(x));
  const X = k => db.reqs[x[k]].answer;
  assert.deepEqual([[X('big').ok, X('big').code], [X('bad').ok, X('bad').code, X('bad').error], [X('net').ok, X('net').code, X('net').error]],
    [[false, 'toolarge'], [false, 'exec', '지원하지 않는 문서 형식'], [false, 'exec', '문서 본문을 읽지 못했습니다(네트워크 오류)']]);
  // 읽기 전용(readwrite 만 사라짐): 읽기는 되고 쓰기는 denied → 다시 물어 prompt 안내 줄 / read only (readwrite gone): reads work, a write is denied → re-queried → the prompt bar
  await page.evaluate(() => { window.__fsPerm = 'prompt'; window.__fsRead = 'granted'; });
  const rd = db.ask(sid, 'read', { path: 'README.md', max_bytes: MAXB }), wr = db.ask(sid, 'write', { path: 'docs/plan.md', text: '고침\n' });
  await answered(db, [rd, wr]);
  assert.deepEqual([db.reqs[rd].answer.ok, db.reqs[rd].answer.result.text, db.reqs[wr].answer.ok, db.reqs[wr].answer.code], [true, README, false, 'denied']);
  await page.waitForSelector('.ai365-ag-fsbar[data-state="prompt"]:not([hidden])');
  assert.deepEqual([(await bar(page)).btn, await page.evaluate(() => window.__fsGet('경동/docs/plan.md'))], [['fsgrant', '허용'], PLAN]);
});

test('an answer whose POST fails on the network or with a 5xx is kept and resent with backoff until it lands exactly once', async (t) => {
  const { page, db } = await app(t, { tweak: d => { d.sessions = []; d.events = {}; } });
  await build(page, '경동', KD);
  await enter(page, '');
  const sid = await fsSession(page, db, '경동');
  db.abortResults = 1; db.failResults = 1;   // 첫 POST = 네트워크 실패, 둘째 = 503 / the first POST fails on the network, the second answers 503
  const r = db.ask(sid, 'read', { path: 'README.md', max_bytes: MAXB });
  await answered(db, [r]);
  await page.waitForTimeout(2500);   // 도착한 뒤에는 더 보내지 않는다 / nothing more after it landed
  const tries = db.calls.filter(c => c.method === 'POST' && c.path.endsWith('/' + sid + '/tool-results') && c.body && c.body.request_id === r);
  assert.deepEqual([tries.length, db.results.filter(b => b.request_id === r).length, db.reqs[r].answer.result.text, (await fsState(page)).unsent], [3, 1, README, 0]);
});

test('handles are per session: a same-named folder is never borrowed, /clear carries its own handle to the new session, a session without its handle asks to reopen', async (t) => {
  const { page, db } = await app(t, { last: 'ag_br9', tweak: d => {
    d.sessions.push(sess({ id: 'ag_br9', kind: 'browser', title: '다른 경동', folder: '경동', updated: '2026-10-20T09:30:00' }));
    d.events.ag_br9 = [];
  } });
  await build(page, 'kdA', { 'README.md': 'A 폴더\n' }, '경동');   // 이름이 같은 다른 두 폴더 / two different folders with the same name
  await build(page, 'kdB', { 'README.md': 'B 폴더\n' }, '경동');
  await enter(page, 'ag_br9');
  await page.waitForSelector('.ai365-ag-fsbar[data-state="nohandle"]:not([hidden])');
  const s1 = await fsDialogSession(page, db, 'kdA'), s2 = await fsDialogSession(page, db, 'kdB');
  // 세션 2 에서 /clear → 새 세션(같은 이름 '경동')은 세션 2 의 폴더 / /clear in session 2: the new session (same name) gets session 2's folder
  await page.fill('#ai365AgInput', '/clear');
  await page.click('[data-ag="send"]');
  await page.waitForSelector('.ai365-ag-sess[data-id="ag_new3"].on');
  await page.waitForSelector('.ai365-ag-env [data-ag-fsst="ok"]');
  const r3 = db.ask('ag_new3', 'read', { path: 'README.md', max_bytes: MAXB });
  await answered(db, [r3]);
  assert.equal(db.reqs[r3].answer.result.text, 'B 폴더\n');
  // 세션 1 · 2 는 제 폴더 그대로 / sessions 1 and 2 keep their own folders
  await openSess(page, s1);
  const r1 = db.ask(s1, 'read', { path: 'README.md', max_bytes: MAXB });
  await answered(db, [r1]);
  await openSess(page, s2);
  const r2 = db.ask(s2, 'read', { path: 'README.md', max_bytes: MAXB });
  await answered(db, [r2]);
  assert.deepEqual([db.reqs[r1].answer.result.text, db.reqs[r2].answer.result.text], ['A 폴더\n', 'B 폴더\n']);
  // 같은 이름 '경동'이어도 핸들이 없던 세션은 빌리지 않는다 → nohandle / a same-named session that never had a handle borrows none → nohandle
  await page.click('.ai365-ag-sess[data-id="ag_br9"]');
  await page.waitForSelector('.ai365-ag-fsbar[data-state="nohandle"]:not([hidden])');
  const r9 = db.ask('ag_br9', 'read', { path: 'README.md', max_bytes: MAXB });
  await page.waitForFunction(() => /\(1\)$/.test(document.querySelector('.ai365-ag-fsbar .tx').textContent));
  assert.deepEqual([db.reqs[r9].answered, (await fsState(page)).handle, (await kv(page))[1]], [false, false, ['작업 폴더', '경동연결 안 됨']]);
});

test('a browser session without a handle here: the bar asks to reopen the folder, requests from GET …/tool-requests run after [Open folder]; a differently named folder connects only after confirm', async (t) => {
  const { page, db } = await app(t, { last: 'ag_br', tweak: d => {
    d.sessions.push(sess({ id: 'ag_br', kind: 'browser', title: '현장 점검', folder: '현장', updated: '2026-10-20T09:30:00' }));
    d.events.ag_br = [];
    d.push('ag_br', 'user', { text: '목록을 보여 줘' });
    d.push('ag_br', 'status', { state: 'running', step: 1 });
    d.sess('ag_br').status = 'running';
    d.reqs.br_wait = { sid: 'ag_br', op: 'list', args: { path: '' }, answered: false };   // 새로고침 전에 온 요청 / a request from before the reload
  } });
  await build(page, '현장', { '점검표.md': '- [ ] 안전모\n' });
  await build(page, '현장2', { 'a.txt': 'A\n', sub: {} });
  await enter(page, 'ag_br');
  await page.waitForSelector('.ai365-ag-fsbar[data-state="nohandle"]:not([hidden])');
  await page.waitForFunction(() => /\(1\)$/.test(document.querySelector('.ai365-ag-fsbar .tx').textContent));
  assert.deepEqual(await bar(page), { state: 'nohandle', text: "이 세션의 폴더 '현장' 을(를) 이 브라우저에서 다시 열어 주세요 · 에이전트가 폴더를 기다리고 있습니다(1)", btn: ['fsrelink', '폴더 열기'] });
  assert.deepEqual([(await kv(page))[1], await page.textContent('.ai365-ag-files .ai365-ag-fnote'), await page.textContent('.ai365-ag-froot')], [['작업 폴더', '현장연결 안 됨'], '연결 안 됨', '현장']);
  assert.ok(db.calls.some(c => c.method === 'GET' && c.path.endsWith('/ag_br/tool-requests')));
  await shot(page, 'br_7_nohandle.png');
  // 선택 창 취소 = 그대로 / a cancelled picker changes nothing
  await pick(page, 'abort');
  await page.click('.ai365-ag-fsbar [data-ag="fsrelink"]');
  await page.waitForFunction(() => window.__fsPicks.length === 1 && !document.querySelector('.ai365-ag-fsbar [data-ag="fsrelink"]').disabled);
  assert.deepEqual([(await bar(page)).state, db.reqs.br_wait.answered], ['nohandle', false]);
  await pick(page, '현장');
  await page.click('.ai365-ag-fsbar [data-ag="fsrelink"]');
  await answered(db, ['br_wait']);
  assert.deepEqual(db.reqs.br_wait.answer.result.entries.map(e => e.name), ['점검표.md']);
  await page.waitForSelector('.ai365-ag-fsbar[hidden]', { state: 'attached' });
  await page.waitForSelector('.ai365-ag-fnode[data-ag-file="점검표.md"]');
  assert.deepEqual([(await kv(page))[1], db.dialogs], [['작업 폴더', '현장연결됨'], []]);   // 같은 이름 = 묻지 않는다 / the same name: no question
  // 메뉴 '폴더 다시 연결…' 로 다른 이름 = confirm, 취소하면 그대로 / a different name via the menu asks; dismissing keeps the old folder
  const ask = "세션 폴더 '현장' 과 이름이 다른 폴더입니다: 현장2. 이 폴더를 연결할까요?";
  await pick(page, '현장2');
  await page.click('[data-ag="title"]');
  await page.click('[data-ag-menu="fsrelink"]');
  await waitFor(() => db.dialogs.length === 1);
  await page.waitForTimeout(300);
  assert.deepEqual([db.dialogs, (await fsState(page)).name, await texts(page, '.ai365-ag-files .ai365-ag-fnode .nm')], [[ask], '현장', ['점검표.md']]);
  // 확인하면 연결하고 실제 폴더 이름으로 저장(트리 뿌리 라벨 · 세션 이름은 그대로) / accepting connects, stored under the real name (root label and session name stay)
  db.acceptDialogs = true;
  await pick(page, '현장2');
  await page.click('[data-ag="title"]');
  await page.click('[data-ag-menu="fsrelink"]');
  await page.waitForSelector('.ai365-ag-fnode[data-ag-file="a.txt"]');
  assert.deepEqual([db.dialogs, (await fsState(page)).name, await texts(page, '.ai365-ag-files .ai365-ag-fnode .nm'), await page.textContent('.ai365-ag-froot'),
    await page.textContent('.ai365-ag-title .t')], [[ask, ask], '현장2', ['sub', 'a.txt'], '현장', '현장 점검']);
  const r = db.ask('ag_br', 'read', { path: 'a.txt', max_bytes: MAXB }), r2 = db.ask('ag_br', 'read', { path: '현장/a.txt', max_bytes: MAXB });   // 접두는 벗기지 않는다 / no prefix stripping
  await answered(db, [r, r2]);
  assert.deepEqual([db.reqs[r].answer.ok, db.reqs[r].answer.result.text, db.reqs[r2].answer.code], [true, 'A\n', 'notfound']);
});

test('a remote client gets no server-folder UI: the empty state and the dialog offer only the folder on this computer, Enter opens the picker, and the session is a browser one', async (t) => {
  const { page, db } = await app(t, { tweak: d => { d.remote = true; d.sessions = []; d.events = {}; } });
  await build(page, '경동', KD);
  await enter(page, '');
  assert.deepEqual(await page.evaluate(() => [...document.querySelectorAll('.ai365-ag-empty .acts button')].map(b => b.dataset.ag)), ['fsopen']);
  await page.click('[data-ag="new"]');
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="new"]');
  assert.deepEqual(await page.evaluate(() => {
    const ov = document.querySelector('.ai365-ag-ov[data-ag-ov="new"]'), has = sel => !!ov.querySelector(sel);
    return { fsopen: has('[data-ag="fsopen"]'), server: ['[data-ag-f="folder"]', '[data-ag="pick"]', '[data-ag="browse"]', '.ai365-ag-chips', '.ai365-ag-or', '.ds', '[data-ag-dlg="ok"]'].filter(has),
      fields: ['[data-ag-f="title"]', '[data-ag-f="model"]', '[data-ag-f="perm"]', '[data-ag-dlg="cancel"]'].filter(has).length, focus: document.activeElement.dataset.agF };
  }), { fsopen: true, server: [], fields: 4, focus: 'title' });
  await shot(page, 'br_10_remote.png');
  await page.fill('[data-ag-f="title"]', '원격 작업');
  await pick(page, '경동');
  await page.press('[data-ag-f="title"]', 'Enter');   // Enter = 선택 창 / Enter opens the picker
  await page.waitForSelector('.ai365-ag-sess[data-id="ag_new1"].on');
  await page.waitForSelector('.ai365-ag-env [data-ag-fsst="ok"]');
  assert.deepEqual([posts(db).map(c => c.body), await page.evaluate(() => window.AI365_agentic.state().fs.remote)],
    [[{ acting_user_id: '', kind: 'browser', folder: '경동', title: '원격 작업', model: 'gemini-3.8-flash', perm_mode: 'auto' }], true]);
});

test('without showDirectoryPicker (an insecure address) the dialog explains where it works and the + item is absent; browser_folders false hides every folder-on-this-computer button', async (t) => {
  // 폴리필 없음 = 가짜 http 원점이라 API 가 없다 / no polyfill: the fake http origin has no API
  const a = await app(t, { noFs: true, tweak: d => { d.sessions = []; d.events = {}; } });
  await a.page.click('#homeAttBtn');
  await a.page.waitForSelector('#cmpAttMenu [data-ai365-wfmi]');
  assert.equal(await a.page.locator('#cmpAttMenu [data-ai365-fsmi]').count(), 0);
  await a.page.keyboard.press('Escape');
  await enter(a.page, '');
  assert.deepEqual(await a.page.evaluate(() => [...document.querySelectorAll('.ai365-ag-empty button')].map(b => b.dataset.ag)), ['newc']);   // 종전 화면 / the old screen
  await a.page.click('[data-ag="new"]');
  await a.page.waitForSelector('.ai365-ag-ov[data-ag-ov="new"] [data-ag-fsno]');
  assert.deepEqual([await a.page.textContent('[data-ag-fsno]'), await a.page.locator('.ai365-ag-ov [data-ag="fsopen"]').count()],
    ['이 브라우저 · 주소에서는 내 컴퓨터 폴더 열기를 쓸 수 없습니다(Edge · Chrome 의 https 또는 localhost 에서만)', 0]);
  await a.page.keyboard.press('Escape');
  await a.page.click('#ai365-lang-toggle');
  await a.page.waitForFunction(() => document.querySelector('[data-ag="new"]').textContent === 'New session');
  await a.page.click('[data-ag="new"]');
  await a.page.waitForSelector('.ai365-ag-ov [data-ag-fsno]');
  assert.equal(await a.page.textContent('[data-ag-fsno]'), 'Folders on your computer cannot be opened in this browser or at this address (Edge or Chrome over https or localhost only)');
  // 서버가 끈 경우(browser_folders false): 버튼 · 안내 모두 없음, + 항목도 셸이 설정을 받은 뒤 사라진다 / turned off by the server: no buttons or note; the + item goes once the shell has the settings
  const b = await app(t, { tweak: d => { d.bf = false; d.sessions = []; d.events = {}; } });
  await b.page.click('#homeAttBtn');
  await b.page.waitForSelector('#cmpAttMenu [data-ai365-fsmi]');   // 아직 설정을 모른다 / settings not known yet
  await b.page.keyboard.press('Escape');
  await enter(b.page, '');
  assert.deepEqual(await b.page.evaluate(() => [...document.querySelectorAll('.ai365-ag-empty button')].map(x => x.dataset.ag)), ['newc']);
  await b.page.click('[data-ag="new"]');
  await b.page.waitForSelector('.ai365-ag-ov[data-ag-ov="new"]');
  assert.deepEqual(await b.page.evaluate(() => ['[data-ag="fsopen"]', '[data-ag-fsno]', '.ai365-ag-or'].map(s => document.querySelectorAll('.ai365-ag-ov ' + s).length)), [0, 0, 0]);
  await b.page.keyboard.press('Escape');
  await b.page.click('#viewWork [data-ca="chat"]');
  await b.page.click('#homeAttBtn');
  await b.page.waitForSelector('#cmpAttMenu [data-ai365-wfmi]');
  assert.equal(await b.page.locator('#cmpAttMenu [data-ai365-fsmi]').count(), 0);
});

test('English labels for the dialog block, the empty state, the sidebar tag, the panel, the bar, the menu and the + item', async (t) => {
  const { page, db } = await app(t, { tweak: d => { d.sessions = []; d.events = {}; } });
  await build(page, '경동', KD);
  await page.click('#ai365-lang-toggle');
  await page.waitForFunction(() => document.getElementById('homeInput').placeholder === 'How can I help you?');
  await page.click('#homeAttBtn');
  await page.waitForSelector('#cmpAttMenu [data-ai365-fsmi]');
  assert.equal(await page.textContent('#cmpAttMenu [data-ai365-fsmi]'), 'Open a folder on my computer');
  await page.keyboard.press('Escape');
  await enter(page, '');
  assert.deepEqual(await page.evaluate(() => [document.querySelector('.ai365-ag-empty p').textContent, [...document.querySelectorAll('.ai365-ag-empty .acts button')].map(b => b.textContent)]),
    ['Pick a folder on your computer in the browser. The agent reads and edits the files in it (no commands).', ['Open a folder on my computer', 'New session on a server folder']]);
  await page.click('.ai365-ag-tx [data-ag="newc"]');
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="new"]');
  assert.deepEqual(await page.evaluate(() => [document.querySelector('.ai365-ag-ov [data-ag="fsopen"]').textContent, document.querySelector('.ai365-ag-fsnew .ai365-ag-hint2').textContent, document.querySelector('.ai365-ag-or').textContent]),
    ['Open a folder on my computer…', 'Pick a folder on your computer in the browser. The agent reads and edits the files in it (no commands).', 'Or a server folder']);
  await page.keyboard.press('Escape');
  await fsSession(page, db, '경동');
  assert.deepEqual([await page.textContent('.ai365-ag-sgrp[data-kind="browser"] .tag'), await kv(page)], ['My computer', [['Host', 'My computer (browser)'], ['Working folder', '경동Connected']]]);
  await page.click('[data-ag="title"]');
  assert.deepEqual(await texts(page, '.ai365-ag-menu .ai365-ag-mi'), ['Rename', 'Show folder', 'Reconnect folder…', 'Turn on completion notices', 'Delete']);
  await page.keyboard.press('Escape');
  // 권한 prompt 안내 줄 / the prompt bar
  await page.evaluate(() => { window.__fsPerm = 'prompt'; window.__fsRead = 'prompt'; });
  const r = db.ask('ag_new1', 'read', { path: 'README.md', max_bytes: MAXB });
  await answered(db, [r]);   // 권한이 없어 denied 로 답하고 다시 묻는다 / answered denied (no permission), then re-queried
  await page.waitForSelector('.ai365-ag-fsbar[data-state="prompt"]:not([hidden])');
  db.ask('ag_new1', 'list', { path: '' });
  await page.waitForFunction(() => /\(1\)$/.test(document.querySelector('.ai365-ag-fsbar .tx').textContent));
  assert.deepEqual(await bar(page), { state: 'prompt', text: "Allow access to the folder '경동' · The agent is waiting for the folder (1)", btn: ['fsgrant', 'Allow'] });
  assert.deepEqual([db.reqs[r].answer.code, (await kv(page))[1]], ['denied', ['Working folder', '경동Permission needed']]);
  await shot(page, 'br_8_en.png');
  // 다시 한국어 / back to Korean
  await page.click('#ai365-lang-toggle');
  await page.waitForFunction(() => (document.querySelector('.ai365-ag-fsbar [data-ag="fsgrant"]') || {}).textContent === '허용');
  assert.deepEqual([(await bar(page)).text, await page.textContent('.ai365-ag-sgrp[data-kind="browser"] .tag')], ["폴더 '경동' 접근을 허용해 주세요 · 에이전트가 폴더를 기다리고 있습니다(1)", '내 컴퓨터']);
});

test('a browser session made in the dialog while the first session list is still loading stays open when the late list arrives', async (t) => {
  const { page, db } = await app(t, { tweak: d => { d.listDelay = 2500; } });
  await build(page, '경동', KD);
  await page.click('#viewHome [data-ca="agentic"]');
  await page.click('[data-ag="new"]');                       // 목록이 오기 전 / before the list arrives
  await pick(page, '경동');
  await page.click('.ai365-ag-ov [data-ag="fsopen"]');
  await page.waitForSelector('.ai365-ag-sess[data-id="ag_new1"].on');
  await page.waitForSelector('.ai365-ag-env [data-ag-fsst="ok"]');
  await waitFor(() => db.calls.filter(c => c.method === 'GET' && c.path === '/api/agentic/sessions').length >= 1);
  await page.waitForFunction(() => !!document.querySelector('.ai365-ag-sess[data-id="ag_a"]'));   // 늦은 목록이 도착 / the late list arrived
  await page.waitForTimeout(400);
  assert.deepEqual(await page.evaluate(() => [window.AI365_agentic.state().session, [...document.querySelectorAll('.ai365-ag-sess')].map(b => b.dataset.id).sort(),
    !!document.querySelector('.ai365-ag-env [data-ag-fsst="ok"]')]), ['ag_new1', ['ag_a', 'ag_new1'], true]);
  assert.equal(db.calls.filter(c => c.path.indexOf('/sessions/ag_a/') >= 0).length, 0);   // 마지막 세션을 다시 열지 않았다 / the last session was not reopened
});

test('the chat composer + menu: [Open a folder on my computer] sits below upload; a cancel stays home; a pick switches to Agentic and opens the new browser session', async (t) => {
  const { page, db } = await app(t);
  await build(page, '경동', KD);
  await page.click('#homeAttBtn');
  await page.waitForSelector('#cmpAttMenu [data-ai365-fsmi]');
  assert.deepEqual((await page.locator('#cmpAttMenu > .cmp-mi').allTextContents()).slice(0, 4), ['이미지 및 파일 업로드', '내 컴퓨터 폴더 열기', '컬렉션', '워크플로우']);
  await shot(page, 'br_9_menu.png');
  await pick(page, 'abort');
  await page.click('#cmpAttMenu [data-ai365-fsmi]');
  await page.waitForFunction(() => window.__fsPicks.length === 1);
  await page.waitForTimeout(200);
  assert.deepEqual(await page.evaluate(() => [document.getElementById('cmpAttMenu').classList.contains('open'), document.getElementById('viewHome').classList.contains('active'),
    document.body.classList.contains('ai365-ag-on')]), [false, true, false]);
  assert.equal(posts(db).length, 0);
  await page.click('#homeAttBtn');
  await pick(page, '경동');
  await page.click('#cmpAttMenu [data-ai365-fsmi]');
  await page.waitForSelector('.ai365-ag-sess[data-id="ag_new1"].on');
  await page.waitForSelector('.ai365-ag-env [data-ag-fsst="ok"]');
  assert.deepEqual(posts(db).map(c => c.body), [{ acting_user_id: '', kind: 'browser', folder: '경동', model: 'gemini-3.8-flash', perm_mode: 'auto' }]);
  assert.deepEqual(await page.evaluate(() => [document.getElementById('viewWork').classList.contains('active'), document.body.classList.contains('ai365-ag-on'), localStorage.getItem('ai365_ag_last')]),
    [true, true, 'ag_new1']);
  // 마지막 세션(ag_a)을 먼저 열지 않고 바로 새 세션 / the new session opens directly, without opening the last one (ag_a) first
  assert.equal(db.calls.filter(c => c.path.indexOf('/sessions/ag_a/') >= 0).length, 0);
  const r = db.ask('ag_new1', 'read', { path: 'src/app.js', max_bytes: MAXB });
  await answered(db, [r]);
  assert.equal(db.reqs[r].answer.result.text, APP);
  // 폴더 열기를 모르는 브라우저에는 + 항목이 없다 / a browser without folder access gets no + item
  await page.click('#viewWork [data-ca="chat"]');
  await page.evaluate(() => { delete window.showDirectoryPicker; });
  await page.click('#homeAttBtn');
  await page.waitForSelector('#cmpAttMenu [data-ai365-wfmi]');
  assert.equal(await page.locator('#cmpAttMenu [data-ai365-fsmi]').count(), 0);
});
