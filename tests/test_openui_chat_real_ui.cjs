// 실행: Playwright 가 NODE_PATH 에 있을 때 node --test --test-concurrency=1 tests/test_openui_chat_real_ui.cjs
// OpenUI 채팅 답 실제 섬 번들 끝에서 끝까지(2026-10-27): 스텁 없이 디스크의 static/openui/*(openui.js · openui.css · chunks/)를 그대로 내준다.
// 프로그램 스트림이 .ai365-oui 안에 보이는 한국어 글로 그려지고, done 뒤 출처 줄('출처')이 나오며, 출처 칩(ai365://kn · ai365://local)을 누르면
// 디코딩된 문서로 미리보기 함수가 불리고(데이터 칩 ai365://data 는 그 답의 데이터 출처 항목으로 AI365_navResource) 페이지는 이동하지 않는다.
// 본문 인용 [n] 은 예전 채팅 각주 같은 위첨자 번호 칩이고(2026-10-29) 누르면(Enter · Space 도) 같은 미리보기가 바로 열린다.
// 후속 질문 단추는 그 글로 새 스트림 요청을 보내고, 저장된 OpenUI 답은
// 복원되어 그려지며, 복사는 평문이다. 콘솔 오류가 없고(스텁 API 의 네트워크 실패 줄은 뺀다), 섬 CSS 가 목업의 채팅 CSS(말풍선 · FOOT 단추 ·
// 본문 · 입력창 · 데모 토큰)를 바꾸지 않는다. 프로그램은 app/prompts/openui_system_prompt.txt 의 Example 1 모양(src1 · src2 줄이 먼저,
// 그다음 root = Card([...], [src1, src2]))으로 손으로 쓴다. 앱 서버 · DB · LLM 없음. 캡처는 AI365_SHOTS 폴더(있을 때만).
// Run with Playwright on NODE_PATH: node --test --test-concurrency=1 tests/test_openui_chat_real_ui.cjs
// OpenUI chat answers end to end with the REAL island bundle (2026-10-27): no stub; static/openui/* (openui.js, openui.css, chunks/)
// is served from disk. A program stream renders visible Korean text inside .ai365-oui, the Sources strip ('출처') appears after done,
// clicking a source chip (ai365://kn, ai365://local) calls the preview function with the decoded document (a data chip, ai365://data,
// calls AI365_navResource with the answer's data source item) and does not navigate, inline [n] citations are superscript number
// chips like the old chat footnotes (2026-10-29) that open the same previews on click (Enter and Space too), a
// follow-up item sends a new stream request with its text, a saved OpenUI answer is restored and rendered, copy takes the plain
// text, there are no console errors (network failure lines of the stubbed APIs excepted), and the island CSS leaves the mockup's
// chat CSS (bubble, FOOT buttons, body, composer, demo tokens) unchanged. The programs are hand-written in the shape of Example 1 in
// app/prompts/openui_system_prompt.txt (the src1 and src2 lines first, then root = Card([...], [src1, src2])). No app server, DB or
// LLM. Screenshots go to AI365_SHOTS when set.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const ROOT = path.join(__dirname, '..');
const read = rel => fs.readFileSync(path.join(ROOT, rel), 'utf8').replace(/\r\n/g, '\n');
const mockup = read('frontend/ai365-mockup.html');
const ADAPTER = read('static/adapter.js');
const ORIGIN = 'http://oui-real.test';
const HTML = mockup.replace('</body>', '<script src="/static/adapter.js"></script></body>');
const SHOTS = process.env.AI365_SHOTS || '';
const OUI_DIR = path.join(ROOT, 'static', 'openui');

// fetch 감싸기(init script): 채팅 스트림은 시험이 조절하는 SSE, 클립보드는 기록용 스텁(가짜 원점은 보안 컨텍스트가 아니다)
// The fetch wrapper (init script): chat streams are SSE the test drives; the clipboard is a recording stub (the fake origin is not a
// secure context)
function pageHooks() {
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

// Example 1 모양의 프로그램(출처 문장은 서버가 먼저 보내는 그대로) / an Example 1 shaped program (source lines as the server sends them first)
const q = s => JSON.stringify(s);
const KN_DOC = '보안규정.pdf', LOCAL_TITLE = '정보보안 기본 규정.pdf';
const KN_URL = 'ai365://kn/' + encodeURIComponent(KN_DOC) + '?page=3';
const LOCAL_URL = 'ai365://local/kl_demo_hq/hq-doc-001?page=1&title=' + encodeURIComponent(LOCAL_TITLE);
const SRC_LINES = 'src1 = {title: ' + q(KN_DOC + ' p.3') + ', sourceName: ' + q('지식 관리 › 보안') + ', url: ' + q(KN_URL) + '}\n'
  + 'src2 = {title: ' + q(LOCAL_TITLE + ' p.1') + ', sourceName: ' + q('본사 지식 에이전트') + ', url: ' + q(LOCAL_URL) + '}\n';
const HEAD_LINES = 'root = Card([header, summary, steps, note, followUps], [src1, src2])\n'
  + 'header = CardHeader("비밀번호 변경 주기", "지식 관리 › 보안 기준")\n';
const REST_LINES = 'summary = TextContent("비밀번호는 **90일마다** 바꿉니다 [1]. 사내 시스템도 같은 규칙을 씁니다 [2].")\n'
  + 'steps = Steps([st1, st2])\n'
  + 'st1 = StepsItem("알림 확인", "만료 7일 전에 메일로 알립니다.")\n'
  + 'st2 = StepsItem("변경하기", "사내 포털에서 바꿉니다.")\n'
  + 'note = Callout("info", "확인하세요", "이전 비밀번호 3개는 다시 쓸 수 없습니다.")\n'
  + 'followUps = FollowUpBlock([fu1, fu2])\n'
  + 'fu1 = FollowUpItem("예외 규정도 알려줘")\n'
  + 'fu2 = FollowUpItem("변경 방법을 자세히 알려줘")';
const PROGRAM = SRC_LINES + HEAD_LINES + REST_LINES;
const PLAIN = '비밀번호 변경 주기\n\n비밀번호는 90일마다 바꿉니다 [1]. 사내 시스템도 같은 규칙을 씁니다 [2].\n\n알림 확인: 만료 7일 전에 메일로 알립니다.';
const SOURCES = { knowledge: { folders: 1, files: 1, items: [{ title: KN_DOC, page: 3, path: ['지식 관리', '보안'], kind: 'file', folder: 'f_sec' }] },
  local: { agents: 1, files: 1, items: [{ title: LOCAL_TITLE, page: 1, doc_id: 'hq-doc-001', agent_id: 'kl_demo_hq', agent: '본사 지식 에이전트', model: 'Qwen 3.5-4B', kind: 'local' }] } };
const CHAT = { id: 'c1', title: 'OpenUI 실번들', scope: '자동', knowledge: null, run_state: '', unseen: 0 };
const OUI_SAVED = { id: 'a1', role: 'assistant', content: PROGRAM, meta: { source: '사내', format: 'openui', ui_mode: 'program', plain: PLAIN, sources: SOURCES } };

let browser;
before(async () => {
  assert.ok(fs.existsSync(path.join(OUI_DIR, 'openui.js')), 'static/openui/openui.js must be built');
  browser = await chromium.launch({ channel: 'msedge', headless: true });
});
after(async () => { if (browser) await browser.close(); });

async function app(t, o) {
  o = o || {};
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await ctx.newPage();
  const errors = [], consoleErrors = [], served = [];
  page.on('pageerror', e => errors.push(e.message));
  // 스텁 API 의 404 · 막은 외부 원점은 브라우저가 'Failed to load resource' 로 적는다: 그 줄만 뺀다
  // The stubbed APIs' 404s and the blocked external origins log 'Failed to load resource': only those lines are excluded
  page.on('console', m => { if (m.type() === 'error' && !/^Failed to load resource/.test(m.text())) consoleErrors.push(m.text()); });
  page.on('dialog', d => d.dismiss());
  t.after(async () => {
    await ctx.close();
    assert.deepEqual(errors, [], 'page errors');
    assert.deepEqual(consoleErrors, [], 'console errors');
    assert.ok(o.noIsland || served.some(p => p.endsWith('/openui.js')), 'the real bundle was served');
  });
  await page.addInitScript(pageHooks);
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), p = decodeURIComponent(url.pathname);
    const json = (obj, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(obj) });
    if (url.origin !== ORIGIN) return route.abort();
    if (p === '/') return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: HTML });
    if (p === '/static/adapter.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: ADAPTER });
    if (p.startsWith('/static/openui/')) {   // 실제 번들 파일(디렉터리 밖 경로는 거절) / the real bundle files (paths outside the folder refused)
      const f = path.normalize(path.join(OUI_DIR, p.slice('/static/openui/'.length)));
      // o.bundle = {fail} 이면 번들 전체가 404(재시도 시험이 도중에 되살린다) / with o.bundle = {fail} the whole bundle 404s (the retry test revives it)
      if ((o.bundle && o.bundle.fail) || !f.startsWith(OUI_DIR + path.sep) || !fs.existsSync(f)) return route.fulfill({ status: 404, contentType: 'text/plain', body: '' });
      served.push(p);
      return route.fulfill({ status: 200, contentType: f.endsWith('.css') ? 'text/css; charset=utf-8' : 'text/javascript; charset=utf-8', body: fs.readFileSync(f) });
    }
    if (p === '/api/chats' && req.method() === 'GET') return json([CHAT]);
    if (p === '/api/chats/c1/messages') return json(o.messages || []);
    if (p === '/api/access/bootstrap') return json({ pvtree: [], groups: [], members: [], teams: [] });
    if (p === '/api/boards/notifications') return json({ unread: 0, notifications: [] });
    return p.startsWith('/api/') ? json({ detail: 'stub' }, 404) : route.abort();
  });
  await page.goto(ORIGIN + '/');
  await page.waitForFunction(() => typeof chats !== 'undefined' && chats.some(c => c.id === 'c1'));
  const got = page.waitForResponse(r => r.url().endsWith('/api/chats/c1/messages'));
  await page.evaluate(() => openChat('c1'));
  await got;
  return page;
}

const push = (page, evs) => page.evaluate(e => window.__sse.push(e), evs);
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
const ouiText = page => page.evaluate(() => { const el = document.querySelector('#chatInner > .msg-ai:last-child .ai365-oui'); return el ? el.innerText : ''; });
const shot = async (page, name) => { if (SHOTS) { fs.mkdirSync(SHOTS, { recursive: true }); await page.waitForTimeout(250); await page.screenshot({ path: path.join(SHOTS, name) }); } };

test('live program stream: visible Korean text inside .ai365-oui while streaming, then the Sources strip (출처) after done', async t => {
  const page = await app(t);
  await ask(page, '비밀번호 변경 주기는?');
  await push(page, [{ type: 'answer_head', source: '사내', format: 'openui', ui_mode: 'program' }, { type: 'token', text: SRC_LINES }]);
  await push(page, [{ type: 'token', text: HEAD_LINES }]);
  await page.waitForFunction(() => { const el = document.querySelector('#chatInner > .msg-ai:last-child .ai365-oui'); return el && el.innerText.includes('비밀번호 변경 주기'); }, null, { timeout: 15000 });
  const mid = await page.evaluate(() => {
    const el = document.querySelector('#chatInner > .msg-ai:last-child .ai365-oui');
    const r = el.getBoundingClientRect();
    return { visible: r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden', root: !!el.querySelector('.ai365-oui-root[lang="ko"]'),
      raw: el.innerText.includes('root =') || el.innerText.includes('src1') };
  });
  assert.deepEqual(mid, { visible: true, root: true, raw: false });
  await push(page, [{ type: 'token', text: REST_LINES }]);
  await push(page, [{ type: 'done', format: 'openui', program: PROGRAM, plain: PLAIN, message_id: 'm1', sources: SOURCES, ui_report: { has_root: true, fenced: false, fallback: false } }]);
  await finish(page);
  await page.waitForSelector('#chatInner > .msg-ai:last-child .openui-listed-sources');
  const fin = await page.evaluate(() => {
    const w = document.querySelector('#chatInner > .msg-ai:last-child'), el = w.querySelector('.ai365-oui');
    return { title: el.querySelector('.openui-listed-sources-header__title').textContent,
      chips: Array.from(el.querySelectorAll('.openui-listed-source-item')).map(c => c.innerText.replace(/\s+/g, ' ').trim()),
      follow: Array.from(el.querySelectorAll('.openui-follow-up-item')).map(b => b.innerText.trim()),
      text: el.innerText.includes('90일마다') && el.innerText.includes('알림 확인'), foot: !!w.querySelector('.msg-foot'),
      gen: !!w.querySelector('.ai365-gen') };
  });
  assert.deepEqual(fin, { title: '출처', chips: ['지식 관리 › 보안 보안규정.pdf p.3', '본사 지식 에이전트 정보보안 기본 규정.pdf p.1'],
    follow: ['예외 규정도 알려줘', '변경 방법을 자세히 알려줘'], text: true, foot: true, gen: false });
  await shot(page, 'oui_real_1_live.png');
});

test('restored answer: renders; source chips open the previews with decoded args without navigating; a follow-up item sends a new stream request; copy is plain', async t => {
  const page = await app(t, { messages: [{ id: 'u1', role: 'user', content: '비밀번호 변경 주기' }, OUI_SAVED] });
  await page.waitForSelector('#chatInner .ai365-oui .openui-listed-source-item', { timeout: 15000 });
  assert.ok((await ouiText(page)).includes('비밀번호는 90일마다 바꿉니다'));
  assert.equal(await page.$eval('#chatInner .ai365-oui .openui-listed-sources-header__title', e => e.textContent), '출처');
  // 복사 = 평문 / copy is the plain text
  await page.click('#chatInner .msg-ai .foot-btn[data-copy]');
  await page.waitForFunction(() => window.__copied !== undefined);
  assert.equal(await page.evaluate(() => window.__copied), PLAIN);
  // 출처 칩: 미리보기 함수는 기록만(스텁), 페이지 이동 · 새 창 없음 / source chips: the preview functions only record (stubs); no navigation, no window
  await page.evaluate(() => {
    window.__spy = [];
    window.ai365OpenKnowledgePreview = function () { window.__spy.push(['kn'].concat([].slice.call(arguments))); };
    window.ai365OpenLocalPreview = function () { window.__spy.push(['local'].concat([].slice.call(arguments))); };
    window.open = function () { window.__spy.push(['open'].concat([].slice.call(arguments))); return null; };
  });
  const popups = [], navs = [];
  page.on('popup', p => popups.push(p.url()));
  page.on('framenavigated', f => { if (f === page.mainFrame()) navs.push(f.url()); });
  const url0 = page.url();
  await page.click('#chatInner .ai365-oui .openui-listed-source-item[data-source-id="0"]');
  await page.waitForFunction(() => window.__spy.length >= 1);
  await page.click('#chatInner .ai365-oui .openui-listed-source-item[data-source-id="1"]');
  await page.waitForFunction(() => window.__spy.length >= 2);
  await page.waitForTimeout(200);
  const spy = await page.evaluate(() => window.__spy.map(s => s.slice()));
  const sid = spy[0][1];
  assert.deepEqual(spy, [['kn', sid, KN_DOC, 3], ['local', sid, 'kl_demo_hq', 'hq-doc-001', LOCAL_TITLE, 1]]);
  assert.equal(await page.evaluate(s => JSON.stringify(AI365_SRC_REG[s]), sid), JSON.stringify(SOURCES));
  assert.deepEqual([page.url(), popups, navs], [url0, [], []]);
  // 후속 질문 단추 → 같은 글로 새 스트림 요청 / a follow-up item → a new stream request with its text
  const n = await page.evaluate(() => window.__streamReqs.length);
  await page.click('#chatInner .ai365-oui .openui-follow-up-item');
  await page.waitForFunction(k => window.__streamReqs.length > k, n);
  const sent = await page.evaluate(() => ({ body: window.__streamReqs[window.__streamReqs.length - 1].body,
    bubble: Array.from(document.querySelectorAll('#chatInner .msg-user .user-bubble')).pop().textContent }));
  assert.deepEqual([sent.body.message, sent.bubble], ['예외 규정도 알려줘', '예외 규정도 알려줘']);
  await shot(page, 'oui_real_2_restore.png');
});

// 본문 인용 번호 칩(2026-10-29): 실제 섬 + adapter 에서 [1] · [2] 가 예전 채팅 각주(.ai365-fn)처럼 위첨자 번호 칩(title = 출처 제목)으로
// 그려지고, 붙은 [1][2] 와 쉼표 나열 [1], [2] 는 칩 둘(한 묶음)이며 칩은 문장 끝 구두점 뒤에 바로 붙는다. 누르면(Enter · Space 도) 출처
// 띠 카드와 같은 미리보기가 바로 열리고 말풍선 · 이동 · 새 창은 없다. 띠 카드의 종류 아이콘은 그대로, 언어 토글은 칩 이름을
// "Source n: 제목" 으로 바꾼다.
// Inline citation number chips (2026-10-29): with the real island and the adapter, [1] and [2] are superscript number chips like
// the old chat footnotes (.ai365-fn) with the source title as their title; adjacent [1][2] and a comma list [1], [2] give two chips
// (one group), and chips sit right after the sentence punctuation. A click (Enter and Space too) opens the same preview as the
// strip card, with no popover, navigation or window. The strip card kind icons stay, and the language toggle renames the chips
// "Source n: title".
test('citation number chips: superscript numbers with titles open the knowledge and local previews by click and keyboard; adjacent [1][2] and comma lists are two chips after the punctuation; strip icons stay', async t => {
  // 단계 = 붙은 [1][2], 콜아웃 = 쉼표 나열 [1], [2](8011 에서 본 모델 글 모양) / the step = adjacent [1][2], the callout = a comma
  // list [1], [2] (the model text seen on 8011)
  const CITE_PROGRAM = PROGRAM.replace('"만료 7일 전에 메일로 알립니다."', '"만료 7일 전에 메일로 알립니다 [1][2]."')
    .replace('"이전 비밀번호 3개는 다시 쓸 수 없습니다."', '"이전 비밀번호 3개는 다시 쓸 수 없습니다 [1], [2]."');
  assert.equal(CITE_PROGRAM.split('[1]').length - 1, 3);
  const page = await app(t, { messages: [{ id: 'u1', role: 'user', content: '비밀번호 변경 주기' }, Object.assign({}, OUI_SAVED, { content: CITE_PROGRAM })] });
  await page.waitForSelector('#chatInner .ai365-oui .ai365-oui-cite', { timeout: 15000 });
  const out = await page.evaluate(() => {
    const el = document.querySelector('#chatInner .ai365-oui');
    const s = getComputedStyle(el.querySelector('.ai365-oui-cite'));
    return {
      groups: Array.from(el.querySelectorAll('.ai365-oui-cites')).map(g => Array.from(g.children).map(c => [c.tagName, c.textContent, c.getAttribute('title'), c.getAttribute('aria-label'), c.getAttribute('role'), c.tabIndex])),
      strip: Array.from(el.querySelectorAll('.openui-listed-source-item .ai365-oui-doc')).map(d => d.getAttribute('data-source-kind')),
      look: [s.fontSize, s.fontWeight, s.color, s.backgroundColor, s.borderTopLeftRadius, s.marginLeft, s.verticalAlign, s.cursor],
    };
  });
  const KN_T = KN_DOC + ' p.3', LOCAL_T = LOCAL_TITLE + ' p.1';
  assert.deepEqual(out.groups, [
    [['SUP', '1', KN_T, '출처 1: ' + KN_T, 'button', 0]],
    [['SUP', '2', LOCAL_T, '출처 2: ' + LOCAL_T, 'button', 0]],
    [['SUP', '1', KN_T, '출처 1: ' + KN_T, 'button', 0], ['SUP', '2', LOCAL_T, '출처 2: ' + LOCAL_T, 'button', 0]],   // [1][2] = 칩 둘 / two chips
    [['SUP', '1', KN_T, '출처 1: ' + KN_T, 'button', 0], ['SUP', '2', LOCAL_T, '출처 2: ' + LOCAL_T, 'button', 0]],   // [1], [2] = 한 묶음 / one group
  ]);
  assert.deepEqual(out.strip, ['kn', 'local']);                                   // 띠 카드 아이콘은 그대로 / strip icons stay
  assert.deepEqual(out.look, ['10px', '700', 'rgb(68, 80, 206)', 'rgb(242, 246, 255)', '4px', '2px', 'super', 'pointer']);   // .ai365-fn 값 / its values
  // 칩 자리 = 예전 각주처럼 문장 끝 구두점 뒤에 바로, 앞 공백 없음(칩 = "^n") / chip placement = right after the sentence
  // punctuation like the old footnotes, no space before (a chip = "^n")
  const placed = await page.evaluate(() => {
    const inline = node => Array.from(node.childNodes).map(n => n.nodeType === 3 ? n.nodeValue : n.nodeType !== 1 ? ''
      : n.classList.contains('ai365-oui-cite') ? '^' + n.textContent : inline(n)).join('');
    const el = document.querySelector('#chatInner .ai365-oui');
    return [inline(el.querySelector('.openui-text-content')), inline(el.querySelector('.openui-step-details')), inline(el.querySelector('.openui-callout-description'))]
      .map(s => s.replace(/\s+/g, ' ').trim());
  });
  assert.deepEqual(placed, ['비밀번호는 90일마다 바꿉니다.^1 사내 시스템도 같은 규칙을 씁니다.^2', '만료 7일 전에 메일로 알립니다.^1^2',
    '이전 비밀번호 3개는 다시 쓸 수 없습니다.^1^2']);                                 // 쉼표 나열: 구분 쉼표 없이 / a comma list loses its commas
  await shot(page, 'oui_real_6_cite_numbers.png');

  // 미리보기 함수는 기록만(스텁) / the preview functions only record (stubs)
  await page.evaluate(() => {
    window.__spy = [];
    window.ai365OpenKnowledgePreview = function () { window.__spy.push(['kn'].concat([].slice.call(arguments))); };
    window.ai365OpenLocalPreview = function () { window.__spy.push(['local'].concat([].slice.call(arguments))); };
    window.open = function () { window.__spy.push(['open'].concat([].slice.call(arguments))); return null; };
  });
  const popups = [], navs = [];
  page.on('popup', p => popups.push(p.url()));
  page.on('framenavigated', f => { if (f === page.mainFrame()) navs.push(f.url()); });
  const url0 = page.url();
  const reqs0 = await page.evaluate(() => window.__streamReqs.length);
  const chip = (g, i) => page.locator('#chatInner .ai365-oui .ai365-oui-cites').nth(g).locator('.ai365-oui-cite').nth(i);
  await chip(0, 0).click();                                                       // 본문 [1] / the body's [1]
  await chip(1, 0).click();                                                       // 본문 [2] / the body's [2]
  assert.equal(await page.$('.openui-citation-tooltip, .openui-citation'), null); // 말풍선 없음 / no popover
  await chip(2, 0).focus();                                                       // 단계의 [1][2]: 키보드 / the step's [1][2]: keyboard
  await page.keyboard.press('Enter');
  await chip(2, 1).focus();
  await page.keyboard.press('Space');
  await page.waitForFunction(() => window.__spy.length >= 4);
  await page.waitForTimeout(200);
  const spy = await page.evaluate(() => window.__spy.map(s => s.slice()));
  const sid = spy[0][1];
  const KN = ['kn', sid, KN_DOC, 3], LOCAL = ['local', sid, 'kl_demo_hq', 'hq-doc-001', LOCAL_TITLE, 1];
  assert.deepEqual(spy, [KN, LOCAL, KN, LOCAL]);                                   // 띠 카드와 같은 미리보기 / the strip card's previews
  assert.deepEqual([page.url(), popups, navs], [url0, [], []]);
  // 칩의 Enter · Space 는 입력창 전송을 부르지 않는다 / Enter and Space on a chip never trigger the composer's send
  assert.equal(await page.evaluate(() => window.__streamReqs.length), reqs0);

  // 언어 토글: 칩 이름 "Source n: 제목", title 은 그대로 / the language toggle: chip names "Source n: title", the titles unchanged
  await page.click('#ai365-lang-toggle');
  await page.waitForFunction(() => document.querySelector('#chatInner .ai365-oui .ai365-oui-cite').getAttribute('aria-label').startsWith('Source '));
  assert.deepEqual(await page.$$eval('#chatInner .ai365-oui .ai365-oui-cite', cs => cs.map(c => [c.getAttribute('aria-label'), c.getAttribute('title')])), [
    ['Source 1: ' + KN_T, KN_T], ['Source 2: ' + LOCAL_T, LOCAL_T], ['Source 1: ' + KN_T, KN_T], ['Source 2: ' + LOCAL_T, LOCAL_T],
    ['Source 1: ' + KN_T, KN_T], ['Source 2: ' + LOCAL_T, LOCAL_T]]);
  await page.click('#ai365-lang-toggle');
  await page.waitForFunction(() => document.querySelector('#chatInner .ai365-oui .ai365-oui-cite').getAttribute('aria-label').startsWith('출처 '));
});

// 데이터 출처 칩(2단계, 계약 9.5): 출처 줄의 표 · BI 칩(ai365://data/… url)을 누르면 그 답의 데이터 출처 항목으로 AI365_navResource(기록 스텁)가
// 한 번씩 불리고, 페이지 이동 · 새 창은 없다
// Data source chips (phase 2, contract 9.5): clicking the table and BI chips (ai365://data/… urls) in the Sources strip calls
// AI365_navResource (a recording stub) once each with the answer's data source item, with no navigation and no window
test('data source chips: the table and BI chips in the Sources strip call AI365_navResource with the matching data items without navigating', async t => {
  const TABLE = { title: '지점별 월 매출', path: ['데이터 분석', '영업 데이터', 'CSV'], kind: 'table', table: 'sales_branch_monthly', ws: 'ws_sales' };
  const BI = { title: '영업 실적 대시보드', path: ['데이터 분석', '영업 데이터', 'BI'], kind: 'bi', file: '영업 실적 대시보드.png', ws: 'ws_sales' };
  const D_PROGRAM = 'src1 = {title: ' + q(TABLE.title) + ', sourceName: ' + q('데이터 분석 › 영업 데이터 › CSV') + ', url: ' + q('ai365://data/' + TABLE.table + '?ws=ws_sales') + '}\n'
    + 'src2 = {title: ' + q(BI.title) + ', sourceName: ' + q('데이터 분석 › 영업 데이터 › BI') + ', url: ' + q('ai365://data/bi/' + encodeURIComponent(BI.file) + '?ws=ws_sales') + '}\n'
    + 'root = Card([header, summary], [src1, src2])\n'
    + 'header = CardHeader("지점별 월 매출", "데이터 분석 › 영업 데이터")\n'
    + 'summary = TextContent("서울중앙 지점의 매출이 가장 높습니다 [1]. 대시보드도 같은 흐름입니다 [2].")';
  const SAVED = { id: 'a1', role: 'assistant', content: D_PROGRAM, meta: { source: '사내', format: 'openui', ui_mode: 'program', plain: '서울중앙 지점의 매출이 가장 높습니다.',
    sources: { data: { groups: 1, resources: 2, items: [TABLE, BI] } } } };
  const page = await app(t, { messages: [{ id: 'u1', role: 'user', content: '지점별 매출' }, SAVED] });
  await page.waitForSelector('#chatInner .ai365-oui .openui-listed-source-item', { timeout: 15000 });
  const chips = await page.$$eval('#chatInner .ai365-oui .openui-listed-source-item', l => l.map(c => c.innerText.replace(/\s+/g, ' ').trim()));
  assert.deepEqual(chips, ['데이터 분석 › 영업 데이터 › CSV 지점별 월 매출', '데이터 분석 › 영업 데이터 › BI 영업 실적 대시보드']);
  await page.evaluate(() => {
    window.__nav = [];
    window.AI365_navResource = function (t) { window.__nav.push(t); };
    window.open = function () { window.__nav.push(['open'].concat([].slice.call(arguments))); return null; };
  });
  const popups = [], navs = [];
  page.on('popup', p => popups.push(p.url()));
  page.on('framenavigated', f => { if (f === page.mainFrame()) navs.push(f.url()); });
  const url0 = page.url();
  await page.click('#chatInner .ai365-oui .openui-listed-source-item[data-source-id="0"]');
  await page.waitForFunction(() => window.__nav.length >= 1);
  await page.click('#chatInner .ai365-oui .openui-listed-source-item[data-source-id="1"]');
  await page.waitForFunction(() => window.__nav.length >= 2);
  await page.waitForTimeout(200);
  assert.deepEqual(await page.evaluate(() => window.__nav), [TABLE, BI]);
  assert.deepEqual([page.url(), popups, navs], [url0, [], []]);
  await shot(page, 'oui_real_5_data_chips.png');
});

test('the island stylesheet leaves the mockup chat styles (bubble, body, FOOT buttons, resource block, composer, demo tokens) unchanged', async t => {
  const MD = { id: 'a0', role: 'assistant', content: '## 요약\n- **첫째** 항목\n\n본문 문단입니다.', meta: { source: '사내', sources: SOURCES } };
  const page = await app(t, { messages: [{ id: 'u0', role: 'user', content: '마크다운 질문' }, MD] });
  await page.waitForSelector('#chatInner .msg-ai .msg-foot');
  const SELS = ['#chatInner .msg-user', '#chatInner .msg-user .user-bubble', '#chatInner .msg-ai', '#chatInner .msg-ai .ai-head', '#chatInner .msg-ai .ai-body',
    '#chatInner .msg-ai .ai-body p', '#chatInner .msg-ai .ai-body ul', '#chatInner .msg-ai .ai-body li', '#chatInner .msg-ai .ai-body .ai365-md-h',
    '#chatInner .msg-ai .msg-foot', '#chatInner .msg-ai .foot-btn', '#chatInner .ai365-res-block', '#chatInner .ai365-res-card', '#chatInner',
    '#chatInput', '#chatSendBtn', '#viewChat .composer', 'body'];
  const TOKENS = ['--primary', '--ink', '--ink-2', '--ink-3', '--muted', '--muted-2', '--border', '--border-2', '--sidebar-bg', '--primary-soft', '--soft-3', '--shadow-pop'];
  const measure = () => page.evaluate(({ sels, tokens }) => {
    // 등장 애니메이션(목업 .appear) 중간값을 재지 않게 끝이 있는 애니메이션은 끝낸다(스피너 같은 무한 반복은 그대로)
    // Finish finite animations (the mockup's .appear entrance) so no mid-animation value is sampled; infinite ones (spinners) stay
    document.getAnimations().forEach(a => { try { if (a.effect && a.effect.getComputedTiming().endTime !== Infinity) a.finish(); } catch (e) { /* noop */ } });
    const out = {};
    // 내용이 늘면 바뀌는 크기 값(새 답이 붙은 #chatInner 높이 등)은 CSS 가 아니므로 뺀다 / content-size values (e.g. #chatInner growing
    // with the new answer) are not CSS, so they are left out
    const GEOM = ['height', 'width', 'block-size', 'inline-size', 'perspective-origin', 'transform-origin'];
    sels.forEach(s => {
      const el = document.querySelector(s);
      if (!el) { out[s] = null; return; }
      const cs = getComputedStyle(el), o = {};
      for (let i = 0; i < cs.length; i++) { const k = cs[i]; if (!k.startsWith('--') && GEOM.indexOf(k) < 0) o[k] = cs.getPropertyValue(k); }
      out[s] = o;
    });
    const rs = getComputedStyle(document.documentElement);
    out[':root tokens'] = tokens.map(k => k + '=' + rs.getPropertyValue(k).trim());
    return out;
  }, { sels: SELS, tokens: TOKENS });
  const before = await measure();
  assert.equal(await page.$('link[data-ai365-oui-css]'), null, 'no island stylesheet yet');
  assert.deepEqual(SELS.filter(s => !before[s]), [], 'every measured element exists');
  // 실제 OpenUI 답 하나 → 섬 CSS · 번들이 실리고 섬이 그려진다 / one real OpenUI answer loads the island CSS and bundle and paints the island
  await ask(page, '비밀번호 변경 주기는?');
  await push(page, [{ type: 'answer_head', source: '사내', format: 'openui', ui_mode: 'program' }, { type: 'token', text: PROGRAM },
    { type: 'done', format: 'openui', program: PROGRAM, plain: PLAIN, message_id: 'm2', sources: SOURCES }]);
  await finish(page);
  await page.waitForSelector('#chatInner > .msg-ai:last-child .openui-listed-sources', { timeout: 15000 });
  await page.waitForFunction(() => { const l = document.querySelector('link[data-ai365-oui-css]'); return !!(l && l.sheet && l.sheet.cssRules.length > 100); });
  const afterLoad = await measure();
  for (const s of Object.keys(before)) assert.deepEqual(afterLoad[s], before[s], s);
  await shot(page, 'oui_real_3_css.png');
});

// 언어 토글(KO/EN): 그려진 섬의 섬 글자('출처' · '관련 질문')가 영어로 바뀌고 모델 글은 그대로, 다시 누르면 한국어로
// The language toggle (KO/EN): the drawn island's own labels ('출처', '관련 질문') turn English while the model text stays; a second
// press brings Korean back
test('the KO/EN toggle repaints a drawn island: Sources and Related Queries in English, the model text unchanged, and back', async t => {
  const page = await app(t, { messages: [{ id: 'u1', role: 'user', content: '비밀번호 변경 주기' }, OUI_SAVED] });
  await page.waitForSelector('#chatInner .ai365-oui .openui-listed-sources', { timeout: 15000 });
  const read = () => page.evaluate(() => {
    const el = document.querySelector('#chatInner .ai365-oui');
    return { sources: el.querySelector('.openui-listed-sources-header__title').textContent, related: el.querySelector('.openui-follow-up-block__header').textContent,
      lang: el.querySelector('.ai365-oui-root').getAttribute('lang'), model: ['비밀번호 변경 주기', '비밀번호는 90일마다 바꿉니다', '예외 규정도 알려줘', '보안규정.pdf p.3'].every(s => el.innerText.includes(s)) };
  });
  assert.deepEqual(await read(), { sources: '출처', related: '관련 질문', lang: 'ko', model: true });
  await page.click('#ai365-lang-toggle');
  await page.waitForFunction(() => document.querySelector('#chatInner .ai365-oui .openui-listed-sources-header__title').textContent === 'Sources');
  assert.deepEqual(await read(), { sources: 'Sources', related: 'Related Queries', lang: 'en', model: true });
  await shot(page, 'oui_real_4_en.png');
  await page.click('#ai365-lang-toggle');
  await page.waitForFunction(() => document.querySelector('#chatInner .ai365-oui .openui-listed-sources-header__title').textContent === '출처');
  assert.deepEqual(await read(), { sources: '출처', related: '관련 질문', lang: 'ko', model: true });
});

// 번들 로드 실패 뒤 회복: 처음엔 평문(마크다운) 대체, 경로가 살아나고 대기가 지나면 다음 OpenUI 답이 실제 섬으로 그려지고, 평문으로 그렸던
// 복원 답도 실제 섬(React)으로 다시 그려진다. 실패했던 스타일시트도 다시 받는다.
// Recovery after a failed bundle load: plain (markdown) fallback first; once the route recovers and the wait passes, the next OpenUI
// answer renders through the real island and the restored answer drawn as plain text is repainted by the real island (React). The
// failed stylesheet is refetched too.
test('bundle 404 then recovery: plain fallback first, then the next answer and the earlier fallback render through the real island', async t => {
  const bundle = { fail: true };
  const page = await app(t, { bundle, messages: [{ id: 'u1', role: 'user', content: '비밀번호 변경 주기' }, OUI_SAVED] });
  await page.waitForFunction(() => AI365_OUI_FAILED === true && AI365_OUI_P === null);
  await page.waitForFunction(() => { const el = document.querySelector('#chatInner .ai365-oui'); return el && el.querySelector('p'); });
  const fb = await page.evaluate(() => { const el = document.querySelector('#chatInner .ai365-oui'); return { root: !!el.querySelector('.ai365-oui-root'), text: el.innerText.includes('비밀번호는 90일마다 바꿉니다') }; });
  assert.deepEqual(fb, { root: false, text: true });
  bundle.fail = false;
  await page.evaluate(() => { AI365_OUI_FAIL.at -= AI365_OUI_RETRY_MS; });
  await ask(page, '다시 물어봅니다');
  await push(page, [{ type: 'answer_head', source: '사내', format: 'openui', ui_mode: 'program' }, { type: 'token', text: PROGRAM },
    { type: 'done', format: 'openui', program: PROGRAM, plain: PLAIN, message_id: 'm2', sources: SOURCES }]);
  await finish(page);
  await page.waitForFunction(() => document.querySelectorAll('#chatInner .ai365-oui .openui-listed-sources').length === 2, null, { timeout: 15000 });
  const out = await page.evaluate(() => {
    const link = document.querySelector('link[data-ai365-oui-css]');
    return { failed: AI365_OUI_FAILED, roots: Array.from(document.querySelectorAll('#chatInner .ai365-oui')).map(el => el.querySelectorAll(':scope > .ai365-oui-root').length),
      leftover: Array.from(document.querySelectorAll('#chatInner .ai365-oui')).map(el => Array.from(el.children).filter(c => !c.classList.contains('ai365-oui-root')).length),
      css: [link.getAttribute('data-ai365-oui-css'), !!(link.sheet && link.sheet.cssRules.length > 100)] };
  });
  assert.deepEqual(out, { failed: false, roots: [1, 1], leftover: [0, 0], css: ['ok', true] });
});
