// 실행: Playwright 가 NODE_PATH 에 있을 때 node --test --test-concurrency=1 tests/test_openui_chat_ui.cjs
// OpenUI 채팅 답(2026-10-27, OpenUI 통합 계약 v1.2 5절): answer_head.format === 'openui' 인 답을 섬(window.AI365_OpenUI)이 그린다.
// 프로그램 스트림(애니메이션 프레임마다 한 번 렌더 · done.program 최종 렌더 · 정밀 각주 재렌더 없음), text 모드 감싸기, kx 실행 프레임,
// format 없는 답은 OpenUI 절을 뺀 어댑터와 HTML 이 같음, 두 복원 경로(일반 · kx) 자리마다 한 번 마운트 · 다시 열기 · 재접속 재생,
// 링크(ai365://kn · ai365://local 디코딩 · ai365://data 표 · BI → 리소스 센터 · http noopener · 그 밖 무시), 후속 질문 액션, 중단 정리, 모델 팝업 [UI 답변] 스위치
// (요청 본문 ui_format · 새로고침 유지), EN 라벨 · 섬 글 미번역 · 복사 = 평문, 번들 로드 실패 = 평문 마크다운.
// 목업 + 어댑터를 가짜 원점에 올린 격리 브라우저. 섬 번들은 스텁 ES 모듈(render 호출 기록 · el 에 글 쓰기 · 콜백 보관)이고,
// /api/chats/<id>/stream(+/attach) 은 fetch 를 감싼 조절 가능한 SSE 스트림, 나머지 /api/* 는 page.route 스텁. 앱 서버 · DB · LLM 없음.
// 캡처는 AI365_SHOTS 폴더(있을 때만).
// Run with Playwright on NODE_PATH: node --test --test-concurrency=1 tests/test_openui_chat_ui.cjs
// OpenUI chat answers (2026-10-27, OpenUI integration contract v1.2 section 5): answers with answer_head.format === 'openui' are painted
// by the island (window.AI365_OpenUI). Covers the program stream (one render per animation frame, the final render from done.program, no
// precise-footnote rerender), text-mode wrapping, the kx execution frame, answers without format producing the same HTML as the adapter
// with the OpenUI section removed, both restore paths (plain and kx) mounting each slot once, reopening and re-attach replay, links
// (ai365://kn and ai365://local decoding, ai365://data tables and BI to the Resource Center, http with noopener, anything else
// ignored), the follow-up action, the stop settle, the
// [UI answers] switch in the model popup (ui_format in the request body, kept across reloads), the EN label, island text left
// untranslated, copy = plain text, and the bundle-failure plain markdown fallback. The mockup and adapter run on a fake origin; the
// island bundle is a stub ES module (records render calls, writes text into el, keeps the callbacks); /api/chats/<id>/stream (+/attach)
// is a controllable SSE stream behind a fetch wrapper and the other /api/* routes are page.route stubs. No app server, DB or LLM.
// Screenshots go to AI365_SHOTS when set.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { chromium } = require('playwright');

const read = rel => fs.readFileSync(path.join(__dirname, '..', rel), 'utf8').replace(/\r\n/g, '\n');
const mockup = read('frontend/ai365-mockup.html');
const ADAPTER = read('static/adapter.js');
const ORIGIN = 'http://oui.test';
const HTML = mockup.replace('</body>', '<script src="/static/adapter.js"></script></body>');
const SHOTS = process.env.AI365_SHOTS || '';

// 비교 기준 = OpenUI 절(머리 주석 ~ 끝 표식)을 뺀 어댑터: 호출부의 typeof 가드가 모두 거짓이 되어 종전 경로만 남는다
// The baseline = the adapter without the OpenUI section (header comment to the end marker): every typeof guard at the call sites is
// false, so only the previous paths remain
function baselineAdapter() {
  const head = ADAPTER.indexOf('   OpenUI 생성형 UI 답변(2026-10-27');
  assert.ok(head > 0, 'OpenUI section header');
  const start = ADAPTER.lastIndexOf('/* =====', head);
  const endMark = ADAPTER.indexOf('/* ── OpenUI 절 끝 / end of the OpenUI section ── */', head);
  assert.ok(start > 0 && endMark > start, 'OpenUI section bounds');
  const out = ADAPTER.slice(0, start) + ADAPTER.slice(ADAPTER.indexOf('\n', endMark) + 1);
  assert.equal(out.indexOf('function ai365OuiLoad('), -1);
  return out;
}

// 섬 스텁(ES 모듈 본문): render 호출을 기록하고 el 에 보이는 글을 쓴다. 콜백(opts)은 el.__opts 로 남겨 시험이 onLink · onAction 을 부른다
// The island stub (ES module body): records render calls and writes visible text into el; the callbacks (opts) stay on el.__opts so
// the tests can call onLink and onAction
function stubIsland() {
  const calls = window.__ouiCalls = [];
  const unmounts = window.__ouiUnmounts = [];
  const wrapText = md => 'root = Card([body])\nbody = TextContent(' + JSON.stringify(String(md || '')) + ')';
  window.AI365_OpenUI = {
    version: 'stub',
    render(el, program, opts) {
      const streaming = !!(opts && opts.streaming);
      calls.push({ id: el.getAttribute('data-ai365-oui'), program: String(program), streaming, lang: opts && opts.lang });
      el.__opts = opts;
      // 표식 + TextContent 글마다 <p> 하나(번역 워커가 글 노드 단위로 맞추므로) / a tag plus one <p> per TextContent (the i18n walker matches whole text nodes)
      el.textContent = '';
      const tag = document.createElement('span');
      tag.className = 'oui-tag';
      tag.textContent = 'OUI[' + (streaming ? 'live' : 'final') + ']';
      el.appendChild(tag);
      const re = /TextContent\(("(?:[^"\\\n]|\\.)*")\)/g;
      let m;
      while ((m = re.exec(String(program)))) {
        const p = document.createElement('p');
        try { p.textContent = JSON.parse(m[1]); } catch (e) { p.textContent = m[1]; }
        el.appendChild(p);
      }
    },
    unmount(el) { unmounts.push(el.getAttribute('data-ai365-oui')); el.textContent = ''; },
    toProgram: t => String(t || '').split('\n').filter(l => !/^\s*\x60{3}/.test(l)).join('\n'),
    isProgram: t => /^\s*[A-Za-z_]\w*\s*=/m.test(String(t || '')),
    wrapText,
  };
}
const STUB = '(' + stubIsland.toString() + ')();\nexport default window.AI365_OpenUI;\n';
const STUB_WRAP = md => 'root = Card([body])\nbody = TextContent(' + JSON.stringify(String(md || '')) + ')';

// fetch 감싸기(init script): 채팅 스트림 · 재접속은 시험이 조절하는 SSE 응답, 요청 본문은 __streamReqs 에. 클립보드는 기록용 스텁
// The fetch wrapper (init script): chat streams and re-attach get an SSE response the test drives, request bodies land in __streamReqs.
// The clipboard is a recording stub (the fake origin is not a secure context).
function pageHooks(init) {
  try {
    if (!sessionStorage.getItem('__ouiInit')) {
      sessionStorage.setItem('__ouiInit', '1');
      if (init.lang) localStorage.setItem('ai365_lang', init.lang);
      if (init.ui) localStorage.setItem('ai365_ui_answers', init.ui);
    }
  } catch (e) { /* noop */ }
  try {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: t => { window.__copied = t; return Promise.resolve(); } } });
  } catch (e) { /* noop */ }
  const orig = window.fetch.bind(window);
  window.__streamReqs = [];
  window.__sse = null;
  window.fetch = function (url, opts) {
    const u = String(url);
    if (/\/api\/chats\/[^/]+\/stream(\/attach)?$/.test(u)) {
      window.__streamReqs.push({ url: u, method: (opts && opts.method) || 'GET', body: opts && opts.body ? JSON.parse(opts.body) : null });
      let ctl = null;
      const enc = new TextEncoder();
      const stream = new ReadableStream({ start(c) { ctl = c; } });
      window.__sse = {
        push(evs) { ctl.enqueue(enc.encode([].concat(evs).map(e => 'data: ' + JSON.stringify(e) + '\n\n').join(''))); },
        end() { try { ctl.close(); } catch (e) { /* closed */ } },
      };
      if (opts && opts.signal) opts.signal.addEventListener('abort', () => { try { ctl.error(new DOMException('aborted', 'AbortError')); } catch (e) { /* closed */ } });
      return Promise.resolve(new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }));
    }
    return orig(url, opts);
  };
}

const q = s => JSON.stringify(s);
const KN = { title: '보안규정.pdf', page: 3, path: ['지식 관리', '보안'], kind: 'file', folder: 'f_sec' };
const LOCAL = { title: '정보보안 기본 규정.pdf', page: 1, doc_id: 'hq-doc-001', agent_id: 'kl_demo_hq', agent: '본사 지식 에이전트', model: 'Qwen 3.5-4B', kind: 'local' };
const SOURCES = { knowledge: { folders: 1, files: 1, items: [KN] }, local: { agents: 1, files: 1, items: [LOCAL] } };
const KN_URL = 'ai365://kn/' + encodeURIComponent('보안규정.pdf') + '?page=3';
const LOCAL_URL = 'ai365://local/kl_demo_hq/hq-doc-001?page=1&title=' + encodeURIComponent('정보보안 기본 규정.pdf');
const SRC_LINES = 'src1 = {title: ' + q('보안규정.pdf p.3') + ', sourceName: ' + q('지식 관리 › 보안') + ', url: ' + q(KN_URL) + '}\n'
  + 'src2 = {title: ' + q('정보보안 기본 규정.pdf p.1') + ', sourceName: ' + q('본사 지식 에이전트') + ', url: ' + q(LOCAL_URL) + '}\n';
const program = (text, follow) => SRC_LINES + 'root = Card([body, fu], [src1, src2])\nbody = TextContent(' + q(text) + ')\n'
  + 'fu = FollowUpBlock([fu1])\nfu1 = FollowUpItem(' + q(follow || '예외 규정도 알려줘') + ')\n';
const KX_TASKS = [{ id: 'knowledge', label: '지식관리 Agent를 실행합니다', children: [{ id: 'knowledge-q1', label: '비밀번호 변경 주기' }] }];
const CHAT = { id: 'c1', title: 'OpenUI 시험', scope: '자동', knowledge: null, run_state: '', unseen: 0 };

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

async function app(t, o) {
  o = o || {};
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => d.dismiss());
  t.after(async () => { await ctx.close(); assert.deepEqual(errors, []); });
  await page.addInitScript(pageHooks, { lang: o.lang || '', ui: o.ui || '' });
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), p = decodeURIComponent(url.pathname);
    const json = (obj, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(obj) });
    if (url.origin !== ORIGIN) return route.abort();
    if (p === '/') return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: HTML });
    if (p === '/static/adapter.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: o.adapter || ADAPTER });
    // o.bundle = {fail} 는 시험 도중 바꿀 수 있다(재시도 시험) / o.bundle = {fail} can flip during a test (the retry test)
    const bundleDown = !!(o.noBundle || (o.bundle && o.bundle.fail));
    if (p === '/static/openui/openui.js') {
      if (o.bundleReqs) o.bundleReqs.push(url.pathname + url.search);
      return bundleDown ? route.fulfill({ status: 404, contentType: 'text/plain', body: 'missing' })
        : route.fulfill({ status: 200, contentType: 'text/javascript; charset=utf-8', body: STUB });
    }
    if (p === '/static/openui/openui.css') {
      if (o.cssReqs) o.cssReqs.push(url.pathname + url.search);
      return route.fulfill({ status: bundleDown ? 404 : 200, contentType: 'text/css', body: '' });
    }
    if (p === '/api/chats' && req.method() === 'GET') return json(o.chats || [CHAT]);
    const mm = /^\/api\/chats\/([^/]+)\/messages$/.exec(p);
    if (mm) return json((o.messages || {})[mm[1]] || []);
    if (p === '/api/access/bootstrap') return json({ pvtree: [], groups: [], members: [], teams: [] });
    if (p === '/api/boards/notifications') return json({ unread: 0, notifications: [] });
    // 스마트 실행(@도구 대화 · 프리필): 요청 본문을 모으고 정해 둔 답을 준다 / smart actions: record bodies, answer from o.smart
    if (o.smart && Object.prototype.hasOwnProperty.call(o.smart, p) && req.method() === 'POST') {
      (o.smartReqs || []).push({ path: p, body: req.postDataJSON() });
      return json(o.smart[p]);
    }
    return p.startsWith('/api/') ? json({ detail: 'stub' }, 404) : route.abort();
  });
  await page.goto(ORIGIN + '/');
  await page.waitForFunction(() => typeof chats !== 'undefined' && chats.some(c => c.id === 'c1'));
  return page;
}

// 채팅 열기 + 복원 대기(메시지 목록 응답 뒤 한 번 쉰다) / open a chat and wait for the restore (one pause after the messages response)
async function openChatAndWait(page, id) {
  id = id || 'c1';
  const got = page.waitForResponse(r => r.url().endsWith('/api/chats/' + id + '/messages'));
  await page.evaluate(cid => openChat(cid), id);
  await got;
  await frames(page);
}
const frames = page => page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 0)))));
const push = (page, evs) => page.evaluate(e => window.__sse.push(e), evs);
const calls = page => page.evaluate(() => (window.__ouiCalls || []).slice());
async function ask(page, text) {
  const n = await page.evaluate(() => window.__streamReqs.length);
  await page.evaluate(m => { appendUserMessage(m); simulateAiReply(); }, text);
  await page.waitForFunction(k => window.__streamReqs.length > k, n);
  return page.evaluate(() => window.__streamReqs[window.__streamReqs.length - 1]);
}
async function finish(page) {
  await page.evaluate(() => window.__sse.end());
  await page.waitForFunction(() => !replyActive);
}
// format 없는 짧은 답으로 실행을 정상 마감(done) / settle a run normally with a short answer without format (done)
async function plainAnswer(page, text) {
  await push(page, [{ type: 'answer_head', source: '사내' }, { type: 'token', text: text || '답' }, { type: 'done', message_id: 'mx' }]);
  await finish(page);
}
const closeMenus = page => page.evaluate(() => document.body.click());
const shot = async (page, name) => { if (SHOTS) { fs.mkdirSync(SHOTS, { recursive: true }); await page.waitForTimeout(200); await page.screenshot({ path: path.join(SHOTS, name) }); } };

test('EN dictionary: the OpenUI entries are new keys whose English values collide with no existing value (both maps)', () => {
  const lit = (src, head) => { const a = src.indexOf(head), b = src.indexOf('\n};', a); assert.ok(a >= 0 && b > a, head); return vm.runInNewContext('(' + src.slice(a + head.length - 1, b + 2) + ')'); };
  const base = lit(ADAPTER, 'const AI365_KO2EN = {'), sched = lit(ADAPTER, 'const AI365_KO2EN_SCHED = {');
  const head = 'Object.assign(AI365_KO2EN, {';
  const a = ADAPTER.indexOf(head, ADAPTER.indexOf('   OpenUI 생성형 UI 답변(2026-10-27')), b = ADAPTER.indexOf('\n});', a);
  assert.ok(a > 0 && b > a, 'the OpenUI Object.assign block');
  const added = vm.runInNewContext('(' + ADAPTER.slice(a + head.length - 1, b + 2) + ')');
  assert.deepEqual(Object.assign({}, added), { 'UI 답변': 'UI answers', '답변이 복사되었습니다.': 'Answer copied.' });   // vm 객체는 다른 realm / the vm object is from another realm
  const values = new Set(Object.values(base).concat(Object.values(sched)));
  for (const [ko, en] of Object.entries(added)) {
    assert.equal(ko in base || ko in sched, false, ko);
    assert.equal(values.has(en), false, en);
    assert.equal(/\u2014/.test(ko + en), false, 'no em dash: ' + ko);
  }
  // \uc5ed\ubc29\ud5a5 \uc0ac\uc804 \ube14\ub85d\uc740 \uc704 \ube14\ub85d\uc758 \uc815\ud655\ud55c \ub4a4\uc9d1\uae30 / the reverse-map block is the exact inverse of the block above
  const rhead = 'Object.assign(AI365_EN2KO, {';
  const ra = ADAPTER.indexOf(rhead, b), rb = ADAPTER.indexOf('\n  });', ra);
  assert.ok(ra > 0 && rb > ra, 'the OpenUI AI365_EN2KO block');
  const reverse = vm.runInNewContext('(' + ADAPTER.slice(ra + rhead.length - 1, rb + 4) + ')');
  assert.deepEqual(Object.assign({}, reverse), Object.fromEntries(Object.entries(added).map(([ko, en]) => [en, ko])));
});

test('program stream: one island render per animation frame while streaming, the final render from done.program, no footnote rerender', async t => {
  const page = await app(t);
  await openChatAndWait(page);
  await ask(page, '비밀번호 변경 주기는?');
  await push(page, [{ type: 'answer_head', source: '사내', format: 'openui', ui_mode: 'program' }]);
  await page.waitForFunction(() => AI365_OUI_API !== null);   // 스텁 번들 로드 완료 / the stub bundle loaded
  assert.notEqual(await page.$('#chatInner .msg-ai:last-child .ai-body .ai365-gen'), null, 'the generating indicator before the first root');
  const toks = [SRC_LINES, 'root = Card([body, fu], [src1, src2])\n', 'body = TextContent("비밀번호는 ', '90일마다 ', '바꿉니다 [1]")\n'];
  await push(page, toks.map(text => ({ type: 'token', text })));
  await page.waitForFunction(() => window.__ouiCalls.length >= 1);
  await frames(page);
  let c = await calls(page);
  assert.equal(c.length, 1, 'five tokens in one chunk → one render');
  assert.deepEqual([c[0].streaming, c[0].program, c[0].lang], [true, toks.join(''), 'ko']);
  assert.equal(await page.$('#chatInner .msg-ai:last-child .ai-body .ai365-gen'), null, 'the root arrived → indicator gone');
  await push(page, [{ type: 'token', text: 'fu = FollowUpBlock([fu1])\n' }, { type: 'token', text: 'fu1 = FollowUpItem("예외 규정도 알려줘")\n' }]);
  await page.waitForFunction(() => window.__ouiCalls.length >= 2);
  await frames(page);
  assert.equal((await calls(page)).length, 2);
  const FINAL = program('비밀번호는 90일마다 바꿉니다 [1]');
  const sources = Object.assign({}, SOURCES, { supports: [{ end: 6, ns: [1] }], cites: [{ n: 1, kind: 'knowledge', title: '보안규정.pdf', page: 3 }] });
  await push(page, [{ type: 'done', format: 'openui', program: FINAL, plain: '비밀번호는 90일마다 바꿉니다 [1]', message_id: 'm1', sources, cards: [],
    ui_report: { has_root: true, fenced: false, fallback: false } }]);
  await finish(page);
  c = await calls(page);
  assert.equal(c.length, 3);
  assert.deepEqual([c[2].streaming, c[2].program], [false, FINAL]);
  const dom = await page.evaluate(() => {
    const w = document.querySelector('#chatInner .msg-ai:last-child'), b = w.querySelector('.ai-body'), el = b.querySelector('.ai365-oui');
    return { skip: el.hasAttribute('data-i18n-skip'), on: el.hasAttribute('data-ai365-oui-on'), text: el.querySelector('.oui-tag').textContent, firstChild: b.firstElementChild === el,
      fn: !!b.querySelector('sup.ai365-fn'), csid: b.hasAttribute('data-ai365-csid'), gen: !!b.querySelector('.ai365-gen'),
      resBlock: !!(b.previousElementSibling && b.previousElementSibling.classList.contains('ai365-res-block')), foot: !!w.querySelector('.msg-foot') };
  });
  assert.deepEqual(dom, { skip: true, on: true, text: 'OUI[final]', firstChild: true, fn: false, csid: false, gen: false, resBlock: true, foot: true });
  await shot(page, 'oui_1_program.png');
});

test('text mode: tokens are markdown wrapped with wrapText(accumulated); done.program is the final render', async t => {
  const page = await app(t);
  await openChatAndWait(page);
  await ask(page, '안녕');
  await push(page, [{ type: 'answer_head', source: '사내', format: 'openui', ui_mode: 'text' }]);
  await page.waitForFunction(() => AI365_OUI_API !== null);
  await push(page, [{ type: 'token', text: '## 인사\n' }, { type: 'token', text: '안녕하세요. "따옴표"와 \\ 도' }]);
  await page.waitForFunction(() => window.__ouiCalls.length >= 1);
  await frames(page);
  let c = await calls(page);
  assert.equal(c.length, 1);
  assert.deepEqual([c[0].streaming, c[0].program], [true, STUB_WRAP('## 인사\n안녕하세요. "따옴표"와 \\ 도')]);
  const FINAL = 'root = Card([body, fu])\nbody = TextContent(' + q('## 인사\n안녕하세요.') + ')\nfu = FollowUpBlock([fu1])\nfu1 = FollowUpItem("더 알려줘")';
  await push(page, [{ type: 'done', format: 'openui', program: FINAL, plain: '인사\n안녕하세요.', message_id: 'm2' }]);
  await finish(page);
  c = await calls(page);
  assert.deepEqual(c.slice(1).map(x => [x.streaming, x.program]), [[false, FINAL]]);
});

test('kx execution frame: the island slot sits in the frame body, the frame settles and the final render is not streaming', async t => {
  const page = await app(t);
  await openChatAndWait(page);
  await ask(page, '비밀번호 변경 주기');
  await push(page, [{ type: 'task_tree', tasks: KX_TASKS, parallel: false }, { type: 'agent_status', task_id: 'knowledge', status: 'running' },
    { type: 'agent_status', task_id: 'knowledge', status: 'done', detail: '근거 2개 확보' },
    { type: 'answer_head', source: '사내', format: 'openui', ui_mode: 'program' }]);
  await page.waitForFunction(() => AI365_OUI_API !== null);
  await push(page, [{ type: 'token', text: program('90일마다 바꿉니다 [1]') }]);
  await page.waitForFunction(() => window.__ouiCalls.length >= 1);
  const FINAL = program('90일마다 바꿉니다 [1][2]');
  await push(page, [{ type: 'done', format: 'openui', program: FINAL, plain: '90일마다 바꿉니다', message_id: 'm3', sources: SOURCES }]);
  await finish(page);
  const out = await page.evaluate(() => {
    const w = document.querySelector('#chatInner .msg-ai:last-child');
    const el = w.querySelector('.ai-body .ai365-oui');
    return { kx: w.classList.contains('ai365-kx'), frame: !!w.querySelector('[data-kx-card="knowledge"]'), slot: !!el, foot: !!w.querySelector('.msg-foot'),
      bodies: w.querySelectorAll('.ai-body').length };
  });
  assert.deepEqual(out, { kx: true, frame: true, slot: true, foot: true, bodies: 1 });
  const c = await calls(page);
  assert.deepEqual([c[c.length - 1].streaming, c[c.length - 1].program], [false, FINAL]);
});

test('answers without format keep the previous HTML and request body (the adapter with the OpenUI section removed is the baseline)', async t => {
  const MD_SAVED = { id: 'a1', role: 'assistant', content: '## 요약\n- **첫째** 항목\n- 둘째 항목', meta: { source: '사내', sources: SOURCES } };
  const CITE_SAVED = { id: 'a2', role: 'assistant', content: '외부 검색 결과입니다.\n두 번째 줄', meta: { source: '외부',
    sources: { external: [{ n: 1, title: '예시', url: 'https://example.com/' }], supports: [{ end: 6, ns: [1] }], cites: [{ n: 1, kind: 'external', title: '예시', url: 'https://example.com/' }] } } };
  const KX_SAVED = { id: 'a3', role: 'assistant', content: '지식 답변 **본문**', meta: { source: '사내', sources: SOURCES,
    trace: { tasks: KX_TASKS, lines: [{ t: 'thinking', text: '지식 문서를 검색하고 있습니다' }] } } };
  const messages = { c1: [{ id: 'u1', role: 'user', content: '질문 하나' }, MD_SAVED, { id: 'u2', role: 'user', content: '질문 둘' }, CITE_SAVED,
    { id: 'u3', role: 'user', content: '질문 셋' }, KX_SAVED] };
  const run = async adapter => {
    const page = await app(t, { messages, adapter });
    await openChatAndWait(page);
    await page.waitForSelector('#chatInner .msg-ai.ai365-kx');
    const req = await ask(page, '새 질문');
    await push(page, [{ type: 'answer_head', source: '외부' }, { type: 'token', text: '외부 답변 ' }, { type: 'token', text: '**굵게** 끝' },
      { type: 'done', message_id: 'm9', sources: CITE_SAVED.meta.sources }]);
    await finish(page);
    const ask2 = await ask(page, '데이터 질문');
    await push(page, [{ type: 'task_tree', tasks: KX_TASKS, parallel: false }, { type: 'answer_head', source: '사내' }, { type: 'token', text: '프레임 답' },
      { type: 'done', message_id: 'm10', sources: SOURCES }]);
    await finish(page);
    return { html: await page.$eval('#chatInner', e => e.innerHTML), reqs: [req.body, ask2.body], slots: await page.$$eval('.ai365-oui', l => l.length) };
  };
  const base = await run(baselineAdapter());
  const now = await run(ADAPTER);
  assert.equal(now.slots, 0);
  assert.ok(base.html.includes('ai365-fn') && base.html.includes('ai365-kx'), 'the baseline really rendered footnotes and the kx frame');
  assert.equal(now.html, base.html);
  assert.deepEqual(now.reqs, base.reqs);
  assert.equal('ui_format' in now.reqs[0], false);
});

test('restore: plain and kx paths each mount their slot once; reopening the chat unmounts the old slots and mounts the new ones once', async t => {
  const A = { id: 'a1', role: 'assistant', content: program('복원 답 A'), meta: { source: '사내', format: 'openui', ui_mode: 'program', plain: '복원 답 A', sources: SOURCES } };
  const B = { id: 'a2', role: 'assistant', content: program('복원 답 B'), meta: { source: '사내', format: 'openui', ui_mode: 'program', plain: '복원 답 B', sources: SOURCES,
    trace: { tasks: KX_TASKS, lines: [{ t: 'thinking', text: '지식 문서를 검색하고 있습니다' }] } } };
  const page = await app(t, { messages: { c1: [{ id: 'u1', role: 'user', content: '질문 A' }, A, { id: 'u2', role: 'user', content: '질문 B' }, B] } });
  await openChatAndWait(page);
  await page.waitForFunction(() => window.__ouiCalls && window.__ouiCalls.length >= 2);
  await frames(page);
  const first = await page.evaluate(() => Array.from(document.querySelectorAll('#chatInner .ai365-oui')).map(el => ({
    id: el.getAttribute('data-ai365-oui'), on: el.hasAttribute('data-ai365-oui-on'), skip: el.hasAttribute('data-i18n-skip'),
    kx: el.closest('.msg-ai').classList.contains('ai365-kx'), inBody: el.parentElement.classList.contains('ai-body'),
    csid: el.parentElement.hasAttribute('data-ai365-csid') })));
  assert.deepEqual(first.map(x => [x.on, x.skip, x.kx, x.inBody, x.csid]), [[true, true, false, true, false], [true, true, true, true, false]]);
  let c = await calls(page);
  assert.equal(c.length, 2);
  assert.deepEqual(c.map(x => [x.id, x.streaming, x.program]), [[first[0].id, false, A.content], [first[1].id, false, B.content]]);
  // 옮기기(워크플로우 '이전 결과' 묶음처럼 같은 작업 안에서 떼었다 붙이기)는 다시 올리거나 내리지 않는다
  // A move (detach and re-attach in one task, like the workflow previous-result group) neither remounts nor unmounts
  await page.evaluate(() => {
    const w = document.querySelector('#chatInner .ai365-oui').closest('.msg-ai');
    const grp = document.createElement('div');
    grp.className = 'ai365-test-group';
    chatInner.appendChild(grp);
    grp.appendChild(w);
  });
  await frames(page);
  assert.deepEqual([(await calls(page)).length, await page.evaluate(() => window.__ouiUnmounts.length)], [2, 0]);
  await openChatAndWait(page);
  await page.waitForFunction(() => window.__ouiCalls.length >= 4);
  await frames(page);
  c = await calls(page);
  const second = await page.$$eval('#chatInner .ai365-oui', l => l.map(el => el.getAttribute('data-ai365-oui')));
  assert.equal(c.length, 4);
  assert.deepEqual(c.slice(2).map(x => x.id), second);
  assert.equal(second.some(id => first.some(f => f.id === id)), false);
  assert.deepEqual((await page.evaluate(() => window.__ouiUnmounts.slice())).sort(), first.map(f => f.id).sort());
  assert.deepEqual(await page.evaluate(ids => ids.map(id => !!AI365_OUI_REG[id]), first.map(f => f.id)), [false, false]);   // 떨어진 자리의 항목은 지움 / entries of detached slots are dropped
});

test('re-attach replay of a running chat: the saved answer mounts once and the replayed live answer renders without a second mount', async t => {
  const SAVED = { id: 'a1', role: 'assistant', content: program('지난 답'), meta: { source: '사내', format: 'openui', ui_mode: 'program', plain: '지난 답', sources: SOURCES } };
  const RUN = { id: 'c2', title: '진행 중', scope: '자동', knowledge: null, run_state: 'running', unseen: 0 };
  const page = await app(t, { chats: [CHAT, RUN], messages: { c2: [{ id: 'u1', role: 'user', content: '지난 질문' }, SAVED, { id: 'u2', role: 'user', content: '지금 질문' }] } });
  await openChatAndWait(page, 'c2');
  await page.waitForFunction(() => window.__streamReqs.length === 1 && window.__sse);
  const req = await page.evaluate(() => window.__streamReqs[0]);
  assert.deepEqual([req.method, /\/api\/chats\/c2\/stream\/attach$/.test(req.url)], ['GET', true]);
  const LIVE = program('지금 답');
  await push(page, [{ type: 'answer_head', source: '사내', format: 'openui', ui_mode: 'program' }, { type: 'token', text: SRC_LINES },
    { type: 'token', text: LIVE.slice(SRC_LINES.length) }, { type: 'done', format: 'openui', program: LIVE, plain: '지금 답', message_id: 'm2', sources: SOURCES }]);
  await finish(page);
  await frames(page);
  const ids = await page.$$eval('#chatInner .ai365-oui', l => l.map(el => [el.getAttribute('data-ai365-oui'), el.hasAttribute('data-ai365-oui-on')]));
  assert.equal(ids.length, 2);
  assert.ok(ids.every(x => x[1]));
  const c = await calls(page);
  const byId = id => c.filter(x => x.id === id);
  assert.deepEqual(byId(ids[0][0]).map(x => [x.streaming, x.program]), [[false, SAVED.content]]);
  const live = byId(ids[1][0]);
  assert.deepEqual(live[live.length - 1], { id: ids[1][0], program: LIVE, streaming: false, lang: 'ko' });
  assert.ok(live.slice(0, -1).every(x => x.streaming));
  assert.deepEqual(await page.evaluate(() => window.__ouiUnmounts.slice()), []);
});

test('links: ai365://kn and ai365://local open the previews with decoded parts and the answer sources; http opens noopener; others are ignored', async t => {
  const A = { id: 'a1', role: 'assistant', content: program('링크 답'), meta: { source: '사내', format: 'openui', ui_mode: 'program', plain: '링크 답', sources: SOURCES } };
  const page = await app(t, { messages: { c1: [{ id: 'u1', role: 'user', content: '질문' }, A] } });
  await openChatAndWait(page);
  await page.waitForFunction(() => window.__ouiCalls && window.__ouiCalls.length >= 1);
  await page.evaluate(() => {
    window.__spy = [];
    const kn = window.ai365OpenKnowledgePreview, lo = window.ai365OpenLocalPreview;
    window.ai365OpenKnowledgePreview = function () { window.__spy.push(['kn'].concat([].slice.call(arguments))); return kn.apply(this, arguments); };
    window.ai365OpenLocalPreview = function () { window.__spy.push(['local'].concat([].slice.call(arguments))); return lo.apply(this, arguments); };
    window.open = function () { window.__spy.push(['open'].concat([].slice.call(arguments))); return null; };
  });
  const out = await page.evaluate(({ kn, local }) => {
    const el = document.querySelector('#chatInner .ai365-oui'), o = el.__opts;
    o.onLink(kn, el);
    const panel = { title: document.getElementById('artifactTitle').textContent, src: (document.querySelector('#artifactBody iframe') || {}).getAttribute('src'),
      open: document.getElementById('artifactPanel').classList.contains('open') };
    o.onLink(local, el);
    o.onLink('https://example.com/a?b=1', el);
    o.onLink('ai365://data/sales', el);
    o.onLink('javascript:alert(1)', el);
    o.onAction({ type: 'open_url', url: 'http://example.org/x' });
    const sid = window.__spy[0][1];
    return { spy: window.__spy, panel, same: sid && window.__spy[1][1] === sid, reg: JSON.stringify(AI365_SRC_REG[sid]) };
  }, { kn: KN_URL, local: LOCAL_URL });
  assert.deepEqual(out.spy.map(s => (s[0] === 'open' ? s : [s[0]].concat(s.slice(2)))), [   // 미리보기는 sid 를 빼고 비교 / previews compared without the sid
    ['kn', '보안규정.pdf', 3],
    ['local', 'kl_demo_hq', 'hq-doc-001', '정보보안 기본 규정.pdf', 1],
    ['open', 'https://example.com/a?b=1', '_blank', 'noopener'],
    ['open', 'http://example.org/x', '_blank', 'noopener'],
  ]);
  assert.equal(out.same, true);
  assert.equal(out.reg, JSON.stringify(SOURCES));
  assert.deepEqual(out.panel, { title: '보안규정.pdf', src: '/api/resources/knowledge/file/' + encodeURIComponent('보안규정.pdf') + '#page=3', open: true });
});

// 데이터 출처 링크(2단계, 계약 9.5): ai365://data/<표>?ws= · ai365://data/bi/<파일>?ws= 는 그 답의 sources.data.items 에서 맞는 항목(표 · 파일,
// 양쪽 다 ws 가 있으면 ws 도)으로 window.AI365_navResource 를 한 번 부른다. 인자와 훅이 없을 때의 안내는 리소스 블록 데이터 항목 클릭과 같다.
// ws 가 어긋나거나 모르는 표 · 파일 · 종류면 부르지 않고 안내도 없다. 복원 답(meta.sources)과 라이브 답(done.sources)이 같고, done 전에는 출처가
// 아직 없어 무시한다.
// Data source links (phase 2, contract 9.5): ai365://data/<table>?ws= and ai365://data/bi/<file>?ws= call window.AI365_navResource once
// with the matching item of the answer's sources.data.items (table or file, plus ws when both sides have one); the argument, and the
// notice without the hook, match the resource block's data item click. A ws mismatch or an unknown table, file or kind calls nothing
// and shows no notice. A restored answer (meta.sources) behaves like a live one (done.sources); before done there are no sources yet,
// so the link is ignored.
const DT = { title: '지점별 월 매출', path: ['데이터 분석', '영업 데이터', 'CSV'], kind: 'table', table: 'sales_branch_monthly', ws: 'ws_sales' };
const DBI = { title: '영업 실적 대시보드', path: ['데이터 분석', '영업 데이터', 'BI'], kind: 'bi', file: '영업 실적 대시보드.png', ws: 'ws_sales' };
const DNOWS = { title: 'hr_employees', path: ['데이터 분석'], kind: 'table', table: 'hr_employees' };   // 카탈로그 밖의 표 = ws 없음 / a table outside the catalog has no ws
const DSOURCES = { data: { groups: 1, resources: 3, items: [DT, DBI, DNOWS] } };
const BI_LINK = 'ai365://data/bi/' + encodeURIComponent(DBI.file);
const DATA_LINKS = [   // [링크, 부른 인자(없으면 null)] / [link, the arguments passed (null when none)]
  ['ai365://data/sales_branch_monthly?ws=ws_sales', [DT]],
  [BI_LINK + '?ws=ws_sales', [DBI]],
  ['ai365://data/sales_branch_monthly', [DT]],                                 // 링크에 ws 없음 = 표만 / no ws in the link: the table alone
  ['ai365://data/hr_employees?ws=ws_hr', [DNOWS]],                             // 항목에 ws 없음 = 표만 / no ws on the item: the table alone
  ['ai365://data/sales_branch_monthly?ws=ws_hr', null],                        // ws 어긋남 / ws mismatch
  [BI_LINK + '?ws=ws_hr', null],
  ['ai365://data/finance_expenses?ws=ws_sales', null],                         // 모르는 표 / unknown table
  ['ai365://data/bi/' + encodeURIComponent('없는 대시보드.png') + '?ws=ws_sales', null],   // 모르는 BI / unknown BI
  ['ai365://data/bi/sales_branch_monthly?ws=ws_sales', null],                  // 표 이름을 BI 로 / a table name as BI
  ['ai365://data/' + encodeURIComponent(DBI.file) + '?ws=ws_sales', null],     // BI 파일을 표로 / a BI file as a table
  ['ai365://data/?ws=ws_sales', null],
];
test('data links: table and BI links call AI365_navResource once with the matching data item like the resource block; mismatches call nothing, no notice; restored = live', async t => {
  const A = { id: 'a1', role: 'assistant', content: program('데이터 답'), meta: { source: '사내', format: 'openui', ui_mode: 'program', plain: '데이터 답', sources: DSOURCES } };
  const page = await app(t, { messages: { c1: [{ id: 'u1', role: 'user', content: '지점별 매출' }, A] } });
  await openChatAndWait(page);
  await page.waitForFunction(() => window.__ouiCalls && window.__ouiCalls.length >= 1);
  await page.evaluate(() => {
    window.__nav = [];
    window.__toasts = [];
    window.AI365_navResource = function (t) { window.__nav.push(t); };
    const t0 = window.toast;
    window.toast = function (m) { window.__toasts.push(m); return t0.apply(this, arguments); };
  });
  // 링크마다 그때 새로 기록된 호출(없으면 null) / the calls recorded by each link (null when none)
  const follow = idx => page.evaluate(({ links, idx }) => links.map(url => {
    const el = document.querySelectorAll('#chatInner .ai365-oui')[idx], n = window.__nav.length;
    el.__opts.onLink(url, el);
    return window.__nav.length === n ? null : window.__nav.slice(n);
  }), { links: DATA_LINKS.map(x => x[0]), idx });
  const restored = await follow(0);
  assert.deepEqual(restored, DATA_LINKS.map(x => x[1]));
  assert.deepEqual(await page.evaluate(() => window.__toasts), []);
  // 리소스 블록(패널)의 데이터 항목 클릭도 같은 인자 / the resource block's (panel's) data item clicks pass the same arguments
  const block = await page.evaluate(() => {
    document.querySelector('#chatInner .ai365-res-open').click();
    const n = window.__nav.length;
    document.querySelectorAll('#artifactBody [data-ai365-navres]').forEach(b => b.click());
    return window.__nav.slice(n);
  });
  assert.deepEqual(block, [DT, DBI, DNOWS]);
  // 훅이 없으면 블록과 같은 안내, 못 찾은 링크는 그래도 안내 없음 / without the hook the block's notice; an unmatched link still shows none
  const noHook = await page.evaluate(() => {
    const hook = window.AI365_navResource;
    window.AI365_navResource = undefined;
    const el = document.querySelector('#chatInner .ai365-oui');
    el.__opts.onLink('ai365://data/sales_branch_monthly?ws=ws_hr', el);
    const quiet = window.__toasts.length === 0;
    el.__opts.onLink('ai365://data/sales_branch_monthly?ws=ws_sales', el);
    document.querySelector('#artifactBody [data-ai365-navres]').click();
    window.AI365_navResource = hook;
    const toasts = window.__toasts.splice(0);
    return { quiet, toasts, nav: window.__nav.length };
  });
  assert.deepEqual(noHook, { quiet: true, toasts: ['리소스 센터에서 확인할 수 있습니다.', '리소스 센터에서 확인할 수 있습니다.'], nav: 7 });
  // 라이브 답: done 전(출처 없음)에는 무시, done.sources 뒤에는 복원 답과 같다 / live answer: ignored before done (no sources), like the restored one after done.sources
  await ask(page, '지점별 매출 다시');
  await push(page, [{ type: 'answer_head', source: '사내', format: 'openui', ui_mode: 'program' }, { type: 'token', text: program('라이브 데이터 답') }]);
  await page.waitForFunction(() => { const l = document.querySelectorAll('#chatInner .ai365-oui'); return l.length === 2 && !!l[1].__opts; });
  assert.deepEqual(await follow(1), DATA_LINKS.map(() => null));
  await push(page, [{ type: 'done', format: 'openui', program: program('라이브 데이터 답'), plain: '라이브 데이터 답', message_id: 'm2', sources: DSOURCES }]);
  await finish(page);
  assert.deepEqual(await follow(1), restored);
  assert.deepEqual(await page.evaluate(() => window.__toasts), []);
});

test('follow-up action: while streaming only a notice; afterwards it adds the user bubble and sends a new stream request with that text', async t => {
  const page = await app(t);
  await openChatAndWait(page);
  await ask(page, '첫 질문');
  await push(page, [{ type: 'answer_head', source: '사내', format: 'openui', ui_mode: 'program' }]);
  await page.waitForFunction(() => AI365_OUI_API !== null);
  await push(page, [{ type: 'token', text: program('첫 답', '다음 질문') }]);
  await page.waitForFunction(() => window.__ouiCalls.length >= 1);
  const busy = await page.evaluate(() => {
    const el = document.querySelector('#chatInner .ai365-oui');
    el.__opts.onAction({ type: 'continue_conversation', text: '다음 질문' });
    return { toast: document.querySelector('#toast .toast-tx').textContent, reqs: window.__streamReqs.length, bubbles: document.querySelectorAll('#chatInner .msg-user').length };
  });
  assert.deepEqual(busy, { toast: '답변이 끝난 뒤 질문해 주세요.', reqs: 1, bubbles: 1 });
  await push(page, [{ type: 'done', format: 'openui', program: program('첫 답', '다음 질문'), plain: '첫 답', message_id: 'm1' }]);
  await finish(page);
  await page.evaluate(() => {
    const el = document.querySelector('#chatInner .ai365-oui');
    window.__opts1 = el.__opts;
    el.__opts.onAction({ type: 'continue_conversation', text: '다음 질문' });
  });
  await page.waitForFunction(() => window.__streamReqs.length === 2);
  const out = await page.evaluate(() => ({ body: window.__streamReqs[1].body, last: Array.from(document.querySelectorAll('#chatInner .msg-user .user-bubble')).pop().textContent }));
  assert.deepEqual([out.body.message, out.last], ['다음 질문', '다음 질문']);
  await page.evaluate(() => window.__opts1.onAction({ type: 'something_else', text: 'x' }));
  assert.equal(await page.evaluate(() => window.__streamReqs.length), 2);
});

test('stop while streaming: the island leaves streaming mode with the program so far', async t => {
  const page = await app(t);
  await openChatAndWait(page);
  await ask(page, '긴 질문');
  await push(page, [{ type: 'answer_head', source: '사내', format: 'openui', ui_mode: 'program' }]);
  await page.waitForFunction(() => AI365_OUI_API !== null);
  const PART = SRC_LINES + 'root = Card([body], [src1, src2])\nbody = TextContent("중간까지';
  await push(page, [{ type: 'token', text: PART }]);
  await page.waitForFunction(() => window.__ouiCalls.length >= 1);
  await page.evaluate(() => finishReply());
  await page.waitForFunction(() => !replyActive);
  await page.waitForFunction(() => window.__ouiCalls.some(x => !x.streaming));
  const c = await calls(page);
  assert.deepEqual([c[c.length - 1].streaming, c[c.length - 1].program], [false, PART]);
  assert.equal(await page.$$eval('#chatInner .msg-ai:last-child .msg-foot', l => l.length), 1);
});

test('the [UI answers] switch: last row of both model popups, off sends ui_format markdown, on sends no field, kept across a reload', async t => {
  const page = await app(t);
  await openChatAndWait(page);
  await page.click('[data-model-btn="chat"]');
  const row = await page.evaluate(() => {
    const m = document.querySelector('[data-model-menu="chat"]'), sw = m.querySelector('[data-ai365-oui-sw]');
    return { last: m.lastElementChild === sw, afterEffort: !!(sw.previousElementSibling && sw.previousElementSibling.classList.contains('ai365-effort')),
      label: sw.querySelector('.lb').textContent, checked: sw.querySelector('[data-ai365-oui-tg]').getAttribute('aria-checked'),
      role: sw.querySelector('[data-ai365-oui-tg]').getAttribute('role'), home: !!document.querySelector('[data-model-menu="home"] [data-ai365-oui-sw]') };
  });
  assert.deepEqual(row, { last: true, afterEffort: true, label: 'UI 답변', checked: 'true', role: 'switch', home: true });
  await shot(page, 'oui_2_switch_on.png');
  await page.click('[data-model-menu="chat"] [data-ai365-oui-sw] .lb');
  const off = await page.evaluate(() => ({ checked: document.querySelector('[data-model-menu="chat"] [data-ai365-oui-tg]').getAttribute('aria-checked'),
    stored: localStorage.getItem('ai365_ui_answers'), open: document.querySelector('[data-model-menu="chat"]').classList.contains('show') }));
  assert.deepEqual(off, { checked: 'false', stored: 'off', open: true });
  await shot(page, 'oui_3_switch_off.png');
  await closeMenus(page);
  let req = await ask(page, '꺼진 상태 질문');
  assert.equal(req.body.ui_format, 'markdown');
  await plainAnswer(page);
  await page.reload();
  await page.waitForFunction(() => typeof chats !== 'undefined' && chats.some(c => c.id === 'c1'));
  await openChatAndWait(page);
  await page.click('[data-model-btn="chat"]');
  assert.equal(await page.getAttribute('[data-model-menu="chat"] [data-ai365-oui-tg]', 'aria-checked'), 'false');
  await page.click('[data-model-menu="chat"] [data-ai365-oui-tg]');
  assert.equal(await page.evaluate(() => localStorage.getItem('ai365_ui_answers')), 'on');
  await closeMenus(page);
  req = await ask(page, '켜진 상태 질문');
  assert.equal('ui_format' in req.body, false);
  await plainAnswer(page);
  // 모델을 고르면 목업이 메뉴를 다시 그린다: 스위치는 다시 붙고 상태를 지킨다 / picking a model rebuilds the menu: the switch comes back with its state
  await page.click('[data-model-btn="chat"]');
  await page.click('[data-model-menu="chat"] .model-item[data-id="gemini"]');
  await page.click('[data-model-btn="chat"]');
  assert.deepEqual(await page.evaluate(() => { const m = document.querySelector('[data-model-menu="chat"]'); return [m.querySelectorAll('[data-ai365-oui-sw]').length, m.lastElementChild.hasAttribute('data-ai365-oui-sw'), m.querySelector('[data-ai365-oui-tg]').getAttribute('aria-checked')]; }), [1, true, 'true']);
});

test('EN: the switch reads UI answers, island text is not translated, and copy takes the plain text', async t => {
  // 섬 글 '리소스 센터' 는 EN 사전의 키다(자리 밖이면 'Resource Center' 로 바뀐다) / the island text '리소스 센터' is an EN dictionary key
  const A = { id: 'a1', role: 'assistant', content: program('리소스 센터'), meta: { source: '사내', format: 'openui', ui_mode: 'program', plain: '리소스 센터에서 확인하세요 (평문)', sources: SOURCES } };
  const page = await app(t, { lang: 'en', messages: { c1: [{ id: 'u1', role: 'user', content: '질문' }, A] } });
  await openChatAndWait(page);
  await page.waitForFunction(() => window.__ouiCalls && window.__ouiCalls.length >= 1);
  await page.click('[data-model-btn="chat"]');
  const sw = await page.evaluate(() => { const s = document.querySelector('[data-model-menu="chat"] [data-ai365-oui-sw]'); return [s.querySelector('.lb').textContent, s.querySelector('[data-ai365-oui-tg]').getAttribute('aria-label')]; });
  assert.deepEqual(sw, ['UI answers', 'UI answers']);
  assert.equal((await calls(page))[0].lang, 'en');
  // 역방향 사전에도 들어 있다(EN → KO 전환용) / present in the reverse map too (for EN back to KO)
  assert.deepEqual(await page.evaluate(() => [AI365_EN2KO['UI answers'], AI365_EN2KO['Answer copied.']]), ['UI 답변', '답변이 복사되었습니다.']);
  await shot(page, 'oui_4_switch_en.png');
  await closeMenus(page);
  const tr = await page.evaluate(() => {
    ai365ApplyLang('en');
    const probe = document.createElement('div');
    probe.innerHTML = '<p>리소스 센터</p>';
    document.getElementById('chatInner').appendChild(probe);
    window.AI365_translateRoot(document.getElementById('chatInner'));
    const out = { probe: probe.textContent, island: document.querySelector('#chatInner .ai365-oui p').textContent };
    probe.remove();
    return out;
  });
  assert.deepEqual(tr, { probe: 'Resource Center', island: '리소스 센터' });
  await page.click('#chatInner .msg-ai .foot-btn[data-copy]');
  await page.waitForFunction(() => window.__copied !== undefined);
  assert.equal(await page.evaluate(() => window.__copied), '리소스 센터에서 확인하세요 (평문)');
  assert.equal(await page.textContent('#toast .toast-tx'), 'Answer copied.');
});

test('bundle load failure: restored and live OpenUI answers show their plain text as markdown, never the raw program', async t => {
  const A = { id: 'a1', role: 'assistant', content: program('복원 **굵게**'), meta: { source: '사내', format: 'openui', ui_mode: 'program', plain: '복원 **굵게** 평문', sources: SOURCES } };
  const page = await app(t, { noBundle: true, messages: { c1: [{ id: 'u1', role: 'user', content: '질문' }, A] } });
  await openChatAndWait(page);
  await page.waitForFunction(() => AI365_OUI_FAILED === true);
  await frames(page);
  assert.equal(await page.$eval('#chatInner .ai365-oui', el => el.innerHTML), '<p>복원 <b>굵게</b> 평문</p>');
  await ask(page, '새 질문');
  await push(page, [{ type: 'answer_head', source: '사내', format: 'openui', ui_mode: 'program' }, { type: 'token', text: program('라이브 답') }]);
  await frames(page);
  const mid = await page.evaluate(() => { const b = document.querySelector('#chatInner .msg-ai:last-child .ai-body'); return { gen: !!b.querySelector('.ai365-gen'), raw: b.textContent.includes('root =') }; });
  assert.deepEqual(mid, { gen: true, raw: false });
  await push(page, [{ type: 'done', format: 'openui', program: program('라이브 답'), plain: '라이브 답 **평문**', message_id: 'm2', sources: SOURCES }]);
  await finish(page);
  const fin = await page.evaluate(() => { const b = document.querySelector('#chatInner .msg-ai:last-child .ai-body'); return { html: b.querySelector('.ai365-oui').innerHTML, gen: !!b.querySelector('.ai365-gen'), raw: b.textContent.includes('root =') }; });
  assert.deepEqual(fin, { html: '<p>라이브 답 <b>평문</b></p>', gen: false, raw: false });
  assert.equal(await page.evaluate(() => window.__ouiCalls), undefined);
});

// 서버 429/503 안내(chats_api): 모델이 첫 토큰 전에 실패하면 OpenUI 머리(+ 서버가 먼저 보낸 출처 문장) 뒤에 format 없는 머리 · 안내 · done 이 온다.
// 섬을 내리고 나머지는 처음부터 마크다운이던 답과 같은 HTML 이어야 한다(작업 트리 없음 · kx 실행 프레임 두 경우).
// The server's 429/503 note (chats_api): when the model fails before its first token, a format-less head, the note and done follow the
// OpenUI head (and the source lines the server sent first). The island goes away and the rest must match the HTML of an answer that was
// markdown from the start (without a task tree and with the kx execution frame).
test('a format-less answer_head after an OpenUI head drops the island and renders the rest exactly like the markdown path', async t => {
  const page = await app(t);
  await openChatAndWait(page);
  const NOTE = '지금 AI 호출량이 몰려 잠시 응답이 어렵습니다. 1~2분 뒤 같은 요청을 다시 보내주시면 이어서 처리하겠습니다.';
  const tail = [{ type: 'answer_head', source: '사내' }, { type: 'token', text: NOTE }, { type: 'done', message_id: 'm-note' }];
  const lastWrap = () => page.$eval('#chatInner > .msg-ai:last-child', w => w.outerHTML);
  const run = async (pre, openui) => {
    await ask(page, '질문');
    if (openui) {
      await push(page, pre.concat([{ type: 'answer_head', source: '사내', format: 'openui', ui_mode: 'program' }]));
      await page.waitForFunction(() => AI365_OUI_API !== null);
      const before = await page.evaluate(() => window.__ouiCalls.length);
      await push(page, [{ type: 'token', text: SRC_LINES }]);   // 서버가 모델 호출 전에 보낸 출처 문장 / source lines sent before the model call
      await page.waitForFunction(k => window.__ouiCalls.length > k, before);
      const id = await page.$eval('#chatInner > .msg-ai:last-child .ai365-oui', el => el.getAttribute('data-ai365-oui'));
      await push(page, tail);
      await finish(page);
      return { id, html: await lastWrap() };
    }
    await push(page, pre.concat(tail));
    await finish(page);
    return { html: await lastWrap() };
  };
  const KX = [{ type: 'task_tree', tasks: KX_TASKS, parallel: false }];
  const plainA = await run([], true), mdA = await run([], false);
  const plainB = await run(KX, true), mdB = await run(KX.concat([{ type: 'answer_head', source: '사내' }]), false);
  assert.equal(plainA.html, mdA.html, 'no task tree');
  assert.equal(plainB.html, mdB.html, 'kx execution frame');
  assert.ok(mdA.html.includes(NOTE) && mdB.html.includes('ai365-kx') && !plainB.html.includes('ai365-oui'));
  const out = await page.evaluate(ids => ({ unmounted: window.__ouiUnmounts.slice().sort(), reg: ids.map(id => id in AI365_OUI_REG), slots: document.querySelectorAll('#chatInner .ai365-oui').length }),
    [plainA.id, plainB.id]);
  assert.deepEqual(out, { unmounted: [plainA.id, plainB.id].sort(), reg: [false, false], slots: 0 });
});

// 스마트 실행(@도구): /converse 의 history 는 도구 세션의 말만 담는다(채팅 답은 들어가지 않음). 답 맥락이 들어가는 곳은 답에서 연 목록의
// 프리필 맥락(AI365_SMART.ctx → /prefill answer) 하나뿐이고, OpenUI 답이면 평문이 간다.
// Smart actions (@ tools): the /converse history holds only the tool session's turns (no chat answer). The one place an answer's
// context enters is the prefill context of a list opened from that answer (AI365_SMART.ctx, sent as /prefill's answer); for an OpenUI
// answer it is the plain text.
test('smart actions: an OpenUI answer gives its plain text to the prefill context, and the converse history never carries the program', async t => {
  const A = { id: 'a1', role: 'assistant', content: program('메일로 보낼 요약'), meta: { source: '사내', format: 'openui', ui_mode: 'program', plain: '요약 평문: 비밀번호는 90일마다 바꿉니다.', sources: SOURCES } };
  const MD = { id: 'a2', role: 'assistant', content: '**마크다운** 답', meta: { source: '사내' } };
  const smartReqs = [];
  const smart = { '/api/smart-actions/converse': { kind: 'info', text: '받은 메일 3건이 있습니다.', source: 'seed' }, '/api/smart-actions/prefill': { ok: true, values: {} } };
  const page = await app(t, { smart, smartReqs, messages: { c1: [{ id: 'u1', role: 'user', content: '비밀번호 규정 요약' }, A, { id: 'u2', role: 'user', content: '두 번째 질문' }, MD] } });
  await openChatAndWait(page);
  await page.waitForFunction(() => window.__ouiCalls && window.__ouiCalls.length >= 1);
  const ctx = await page.evaluate(() => {
    const msgs = document.querySelectorAll('#chatInner > .msg-ai');
    ai365SmartLaunchMenu(msgs[0].querySelector('.foot-btn'));
    const oui = Object.assign({}, AI365_SMART.ctx);
    ai365SmartLaunchMenu(msgs[1].querySelector('.foot-btn'));
    const md = Object.assign({}, AI365_SMART.ctx);
    ai365SmartLaunchMenu(msgs[0].querySelector('.foot-btn'));
    ai365SmartCloseLaunch();
    // 프리필 요청 본문 = 이 맥락(모달 대신 최소 상태) / the prefill body carries this context (minimal state instead of the modal)
    const dlg = document.createElement('div');
    dlg.id = 'ai365SmartDlg';
    document.body.appendChild(dlg);
    AI365_SMART.cur = { act: AI365_SMART_SERVICES.mail.actions[0] };
    ai365SmartPrefill();
    return { oui, md };
  });
  assert.deepEqual(ctx.oui, { q: '비밀번호 규정 요약', a: '요약 평문: 비밀번호는 90일마다 바꿉니다.' });
  assert.deepEqual(ctx.md, { q: '두 번째 질문', a: '마크다운 답' });   // 마크다운 답은 종전대로 본문 글 / a markdown answer keeps its body text
  const until = async (ok, what) => { for (let i = 0; i < 100 && !ok(); i++) await page.waitForTimeout(30); assert.ok(ok(), what); };
  await until(() => smartReqs.some(r => r.path === '/api/smart-actions/prefill'), 'the prefill request');
  const pre = smartReqs.filter(r => r.path === '/api/smart-actions/prefill');
  assert.equal(pre.length, 1);
  assert.deepEqual([pre[0].body.question, pre[0].body.answer], ['비밀번호 규정 요약', '요약 평문: 비밀번호는 90일마다 바꿉니다.']);
  // @도구 대화 두 턴: 두 번째 history = 첫 턴의 말 두 개뿐 / two @-tool turns: the second history is the first turn's two lines only
  await page.evaluate(() => { appendUserMessage('@mail 받은 메일 알려줘'); simulateAiReply(); });
  await page.waitForFunction(() => document.querySelector('#chatInner > .msg-ai:last-child[data-ai365-mn] .ai-body'));
  await page.evaluate(() => { appendUserMessage('첫 번째 메일 요약해줘'); simulateAiReply(); });
  await until(() => smartReqs.filter(r => r.path === '/api/smart-actions/converse').length === 2, 'two converse requests');
  const conv = smartReqs.filter(r => r.path === '/api/smart-actions/converse').map(r => r.body.history);
  assert.deepEqual(conv, [[], [{ role: 'user', content: '받은 메일 알려줘' }, { role: 'assistant', content: '받은 메일 3건이 있습니다.' }]]);
  assert.equal(/root =|src1 =|TextContent\(/.test(JSON.stringify(smartReqs)), false);
});

// 번들 import 실패는 페이지 끝까지 가지 않는다: 대기(AI365_OUI_RETRY_MS) 동안은 다시 받지 않고 평문, 대기 뒤 다음 OpenUI 답이 다시 받는다.
// 성공하면 실패 표시가 풀리고, 평문으로 그렸던 자리도 섬으로 다시 그린다. 실패한 스타일시트는 &r= 주소로 다시 받는다.
// A failed bundle import no longer lasts for the page: during the wait (AI365_OUI_RETRY_MS) nothing is refetched and plain text shows;
// after it the next OpenUI answer refetches. On success the failure state clears and slots drawn as plain text are repainted with the
// island. A failed stylesheet is refetched at an &r= URL.
test('bundle import retry: no refetch during the wait, the next answer after it loads the island and earlier fallbacks are upgraded', async t => {
  const A = { id: 'a1', role: 'assistant', content: program('복원 답'), meta: { source: '사내', format: 'openui', ui_mode: 'program', plain: '복원 **평문**', sources: SOURCES } };
  const bundle = { fail: true }, bundleReqs = [], cssReqs = [];
  const page = await app(t, { bundle, bundleReqs, cssReqs, messages: { c1: [{ id: 'u1', role: 'user', content: '질문' }, A] } });
  await openChatAndWait(page);
  await page.waitForFunction(() => AI365_OUI_FAILED === true && AI365_OUI_P === null && AI365_OUI_FAIL !== null);
  await frames(page);
  assert.equal(await page.$eval('#chatInner .ai365-oui', el => el.innerHTML), '<p>복원 <b>평문</b></p>');
  // 대기 안의 새 OpenUI 답: 다시 받지 않고 평문 / a new OpenUI answer within the wait: no refetch, plain text
  await ask(page, '두 번째');
  await push(page, [{ type: 'answer_head', source: '사내', format: 'openui', ui_mode: 'program' }, { type: 'token', text: program('두 번째 답') }]);
  await frames(page);
  await push(page, [{ type: 'done', format: 'openui', program: program('두 번째 답'), plain: '두 번째 평문', message_id: 'm2' }]);
  await finish(page);
  assert.equal(await page.$eval('#chatInner > .msg-ai:last-child .ai365-oui', el => el.innerHTML), '<p>두 번째 평문</p>');
  assert.deepEqual([bundleReqs.length, cssReqs.length], [1, 1]);
  // 경로가 살아나고 대기가 지나면(시각을 당겨 흉내) 다음 OpenUI 답이 다시 받는다 / the route recovers and the wait passes (time rewound): the next answer refetches
  bundle.fail = false;
  await page.evaluate(() => { AI365_OUI_FAIL.at -= AI365_OUI_RETRY_MS; });
  await ask(page, '세 번째');
  await push(page, [{ type: 'answer_head', source: '사내', format: 'openui', ui_mode: 'program' }]);
  await page.waitForFunction(() => AI365_OUI_API !== null);
  await push(page, [{ type: 'token', text: program('세 번째 답') }, { type: 'done', format: 'openui', program: program('세 번째 답'), plain: '세 번째 평문', message_id: 'm3' }]);
  await finish(page);
  await frames(page);
  const out = await page.evaluate(() => {
    const slots = Array.from(document.querySelectorAll('#chatInner .ai365-oui'));
    const ids = slots.map(el => el.getAttribute('data-ai365-oui'));
    const link = document.querySelector('link[data-ai365-oui-css]');
    return { failed: AI365_OUI_FAILED, fail: AI365_OUI_FAIL, island: slots.map(el => !!el.querySelector('.oui-tag')),
      finals: ids.map(id => window.__ouiCalls.filter(c => c.id === id && !c.streaming).length),
      css: [link.getAttribute('data-ai365-oui-css'), /&r=2$/.test(link.getAttribute('href'))] };
  });
  assert.deepEqual(out, { failed: false, fail: null, island: [true, true, true], finals: [1, 1, 1], css: ['ok', true] });
  assert.deepEqual([bundleReqs.length, cssReqs.length], [2, 2]);
});

// 언어 전환: 붙어 있고 스트리밍이 끝난 섬은 새 언어로 다시 그린다. 스트리밍 중인 섬은 다음 프레임에, 같은 언어로 다시 부르면 그리지 않는다
// Language switch: attached islands that finished streaming repaint in the new language; a streaming one on its next frame; calling
// again with the same language paints nothing
test('language switch repaints attached finished islands with the new lang; a streaming island picks it up on its next frame', async t => {
  const A = { id: 'a1', role: 'assistant', content: program('복원 답'), meta: { source: '사내', format: 'openui', ui_mode: 'program', plain: '복원 답', sources: SOURCES } };
  const page = await app(t, { messages: { c1: [{ id: 'u1', role: 'user', content: '질문' }, A] } });
  await openChatAndWait(page);
  await page.waitForFunction(() => window.__ouiCalls && window.__ouiCalls.length >= 1);
  const restored = await page.$eval('#chatInner .ai365-oui', el => el.getAttribute('data-ai365-oui'));
  await ask(page, '진행 중');
  await push(page, [{ type: 'answer_head', source: '사내', format: 'openui', ui_mode: 'program' }, { type: 'token', text: SRC_LINES + 'root = Card([body])\n' }]);
  await page.waitForFunction(() => window.__ouiCalls.length >= 2);
  const live = await page.$eval('#chatInner > .msg-ai:last-child .ai365-oui', el => el.getAttribute('data-ai365-oui'));
  const n0 = (await calls(page)).length;
  await page.click('#ai365-lang-toggle');
  await frames(page);
  let c = (await calls(page)).slice(n0);
  assert.deepEqual(c.map(x => [x.id, x.lang, x.streaming]), [[restored, 'en', false]]);   // 스트리밍 중인 섬은 아직 / not the streaming one yet
  await push(page, [{ type: 'token', text: 'body = TextContent("계속")\n' }]);
  await page.waitForFunction(k => window.__ouiCalls.length > k, n0 + 1);
  await frames(page);
  c = (await calls(page)).slice(n0 + 1);
  assert.deepEqual(c.map(x => [x.id, x.lang, x.streaming]), [[live, 'en', true]]);
  const n1 = (await calls(page)).length;
  await page.evaluate(() => ai365ApplyLang(ai365CurrentLang()));   // 같은 언어 = 다시 그리지 않음 / same language: no repaint
  await frames(page);
  assert.equal((await calls(page)).length, n1);
  await push(page, [{ type: 'done', format: 'openui', program: program('진행 중 답'), plain: '진행 중 답', message_id: 'm2' }]);
  await finish(page);
  const n2 = (await calls(page)).length;
  await page.click('#ai365-lang-toggle');
  await frames(page);
  c = (await calls(page)).slice(n2);
  assert.deepEqual(c.map(x => [x.id, x.lang, x.streaming]).sort(), [[live, 'ko', false], [restored, 'ko', false]].sort());
});
