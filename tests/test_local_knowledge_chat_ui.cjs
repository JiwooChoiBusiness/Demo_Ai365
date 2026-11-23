// Run with Playwright available on NODE_PATH: node --test tests/test_local_knowledge_chat_ui.cjs
// 채팅 로컬 지식 표시(2026-09-30) — 실행 프레임 로컬 카드("로컬"로 시작하는 thinking 줄), done.sources.local 문서 칩, 리소스 블록 ·
// 리소스 패널의 로컬 그룹, 로컬 문서 미리보기(권한 프록시), meta.trace + meta.sources 복원, EN 사전. 어댑터의 실제 함수를 잘라 격리
// 브라우저에서 돌린다. 앱 DB · LLM · 네트워크 없음(fetch 는 스텁).
// Chat local-knowledge display (2026-09-30): the execution frame's local card (thinking lines starting with "로컬"),
// done.sources.local document chips, the local group of the resource block and panel, the local document preview (permission
// proxy), restore from meta.trace + meta.sources, and the EN dictionary. Real adapter functions sliced from source and run in
// an isolated browser; no application DB, LLM or network (fetch is stubbed).
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { chromium } = require('playwright');
const source = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8').replace(/\r\n/g, '\n');

// test_flow_cards_ui.cjs 의 fn() 과 같은 규칙(한 줄 함수 포함) / same convention as test_flow_cards_ui.cjs's fn() (single-line functions too)
function fn(name) {
  const start = source.search(new RegExp('^(?:async )?function ' + name + '\\(', 'm'));
  assert.ok(start >= 0, name);
  const eol = source.indexOf('\n', start);
  const firstLine = source.slice(start, eol);
  if (/\}\s*$/.test(firstLine)) return firstLine;
  return source.slice(start, source.indexOf('\n}', start) + 2);
}
// 최상위 const/let 선언(한 줄이면 그 줄, 여러 줄 객체면 '\n};' 까지) / a top-level const/let (one line, or a multi-line object up to '\n};')
function decl(name) {
  const start = source.search(new RegExp('^(?:const|let) ' + name + ' = ', 'm'));
  assert.ok(start >= 0, name);
  const eol = source.indexOf('\n', start);
  const firstLine = source.slice(start, eol);
  if (/;\s*(\/\/.*)?$/.test(firstLine)) return firstLine;
  return source.slice(start, source.indexOf('\n};', start) + 3);
}
function dict() {   // 어댑터 EN 사전 / the adapter EN dictionary
  const a = source.indexOf('const AI365_KO2EN = {'), b = source.indexOf('\n};', a);
  return vm.runInNewContext('(' + source.slice(a + 'const AI365_KO2EN = '.length, b + 2) + ')');
}
// 위임 클릭 리스너(로컬 문서 · 리소스 열기 · 그룹 접기) — 짧은 고유 내부 문자열로 찾는다 / the delegated click listener, found by a unique interior string
function clickListener() {
  const anchor = source.indexOf("const ld = e.target.closest('[data-ai365-ldoc]');");
  assert.ok(anchor >= 0, 'local click anchor');
  const start = source.lastIndexOf("document.addEventListener('click', e => {", anchor);
  return source.slice(start, source.indexOf('\n});', anchor) + 4);
}

const CONSTS = ['AI365_KO2EN', 'AI365_SRC_REG', 'AI365_SRC_SEQ', 'AI365_RES_ICONS', 'AI365_RES_CHEV', 'AI365_AGX_TASK_IC', 'AI365_AGX_ARROW_IC',
  'AI365_AGX_BRANCH_IC', 'AI365_AGX_CHEV_IC', 'AI365_KX_PEND_IC', 'AI365_KX_FAIL_IC', 'AI365_KX_AGENT', 'AI365_KX_WEB_RE',
  'AI365_KX_LOCAL_RE', 'AI365_KX_WEB_IC', 'AI365_KX_DOCS', 'AI365_KX_STEP_IC', 'AI365_LOCAL_PREV_SEQ'];
const FUNCS = ['ai365Esc', 'ai365T', 'ai365SrcRegister', 'ai365LocalBadgeHtml', 'ai365LocalFiles', 'ai365LocalDocAttrs', 'ai365LocalChipsHtml',
  'ai365SourcesBlockHtml', 'ai365OpenSources', 'ai365OpenKnowledgePreview', 'ai365LocalPreviewUrl', 'ai365LocalPreviewKind', 'ai365OpenLocalPreview',
  'ai365HandleEvent', 'ai365KxAgentIcon', 'ai365KxEligible', 'ai365KxAddCards', 'ai365KxEn', 'ai365KxLineText', 'ai365KxCard', 'ai365KxAllLists',
  'ai365KxPush', 'ai365KxLine', 'ai365KxScopeCounts', 'ai365KxSubLabel', 'ai365KxFinalGroup', 'ai365KxGroupsFromNames', 'ai365KxBiPhrase',
  'ai365KxItemKind', 'ai365KxGroupsFromSources', 'ai365KxAllGroups', 'ai365KxThinkHtml', 'ai365KxLineHtml', 'ai365KxExtChips', 'ai365KxExploreBtn',
  'ai365KxTileLineHtml', 'ai365KxCardHtml', 'ai365KxWebHtml', 'ai365KxLocalHtml', 'ai365KxFrameHtml', 'ai365KxStagesHtml', 'ai365KxPaint',
  'ai365KxInit', 'ai365KxStatus', 'ai365KxStage', 'ai365KxAnswerHead', 'ai365KxSplitCards', 'ai365KxBiHtml', 'ai365KxDone',
  'ai365KxSettleGroups', 'ai365KxApplySources', 'ai365KxStaticEl', 'ai365KxDocList'];

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

async function fixture(t) {
  const page = await browser.newPage();
  t.after(() => page.close());
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  t.after(() => assert.deepEqual(errors, []));
  await page.setContent('<div id="chat"></div><aside id="artifactPanel"><div id="artifactIcon"></div><div id="artifactTitle"></div><div id="artifactBody"></div></aside>');
  await page.addScriptTag({ content: `
    const chatInner = document.getElementById('chat');
    const $ = s => document.querySelector(s);
    const artifactPanel = document.getElementById('artifactPanel');
    const FOOT = '<footer class="msg-foot"></footer>';
    const aiHead = () => '<header class="ai-head"></header>';
    const ai365CurrentLang = () => window.__lang || 'ko';
    const ai365MnMd = s => '<p>' + ai365Esc(s) + '</p>', ai365CardsHtml = () => '', ai365BiEmbHtml = () => '';
    const stickToBottom = () => {}, toast = m => { window.toasts = (window.toasts || []).concat([m]); }, ai365ClearGen = () => {};
    const ai365AppendToken = (state, t) => { state.text = (state.text || '') + t; if (state.body) state.body.textContent = state.text; };
    ${CONSTS.map(decl).join('\n')}
    ${FUNCS.map(fn).join('\n')}
    ${clickListener()}
  ` });
  return page;
}

const QUESTION = '비밀번호 변경 주기';
const HQ = { title: '정보보안 기본 규정.pdf', page: 1, doc_id: 'hq-doc-001', agent_id: 'kl_demo_hq', agent: '본사 지식 에이전트', model: 'Qwen 3.5-4B', kind: 'local' };
const SOURCES = {
  knowledge: { folders: 1, files: 1, items: [{ title: '보안규정.pdf', page: 3, path: ['지식 관리', '보안'], kind: 'file', folder: 'f_sec' }] },
  local: { agents: 1, files: 1, items: [HQ] },
};
const START = '로컬 지식 에이전트에 질문하고 있습니다 · 본사 지식 에이전트, 웹 문서 에이전트';
const ANSWERED = '로컬 · 본사 지식 에이전트(Qwen 3.5-4B) 답변 확보 · 출처 1건';
const FAILED = '로컬 · 웹 문서 에이전트 연결 실패 · 시간 초과';
const TASKS = [{ id: 'knowledge', label: '지식관리 Agent를 실행합니다', children: [{ id: 'knowledge-q1', label: QUESTION }] }];

// 프레임 모양 요약(카드 · 줄 · 칩 · 트리) / a summary of the frame (cards, lines, chips, tree)
const FRAME = `(root => {
  const box = root.querySelector('[data-kx-card="local"]');
  const lines = sel => Array.from(root.querySelectorAll(sel)).map(l => ({ text: l.textContent, done: l.classList.contains('done'), fail: l.classList.contains('fail') }));
  return {
    web: !!root.querySelector('[data-kx-card="web"]'),
    knowledge: !!root.querySelector('[data-kx-card="knowledge"]'),
    local: !!box,
    title: box ? box.querySelector('.ai365-kx-card b').textContent : '',
    badge: box ? box.querySelector('.ai365-local-badge').textContent : '',
    sub: box ? box.querySelector('.ai365-kx-sub').textContent : '',
    cap: (root.querySelector('.ai365-kx-localcap') || {}).textContent || '',
    localLines: lines('[data-kx-card="local"] .ai365-kx-line'),
    common: lines('.ai365-kx-common .ai365-kx-line').map(l => l.text),
    chips: Array.from(root.querySelectorAll('[data-kx-card="local"] .ai365-local-chip')).map(c => ({ text: c.textContent,
      agent: c.dataset.ai365Lagent, doc: c.dataset.ai365Ldoc, page: c.dataset.ai365Lpage, title: c.dataset.ai365Ltitle, sid: c.dataset.ai365Lsid })),
    tree: Array.from(root.querySelectorAll('.ai365-agx-tkline span')).map(s => s.textContent),
  };
})`;

test('live stream: "로컬" lines build the local card (even with 웹 in a name), result lines settle at once and done.sources.local adds chips', async t => {
  const page = await fixture(t);
  const out = await page.evaluate(({ tasks, start, answered, failed, sources, FRAME }) => {
    const frame = eval(FRAME);
    const wrap = document.createElement('div');
    chatInner.appendChild(wrap);
    const state = { body: null, text: '', tree: false };
    const H = ev => ai365HandleEvent(ev, wrap, state);
    H({ type: 'task_tree', tasks, parallel: false });
    H({ type: 'agent_status', task_id: 'knowledge', status: 'running' });
    H({ type: 'agent_status', task_id: 'knowledge', status: 'done', detail: '근거 3개 청크 확보' });
    const before = frame(wrap);
    H({ type: 'thinking', text: start });
    const asking = frame(wrap);
    H({ type: 'thinking', text: answered });
    H({ type: 'thinking', text: failed });
    H({ type: 'thinking', text: '결과를 취합해 답변을 작성하고 있습니다' });
    H({ type: 'answer_head', source: '사내' });
    H({ type: 'token', text: '비밀번호는 90일마다 바꿉니다 (로컬 · 본사 지식 에이전트)' });
    H({ type: 'done', message_id: 'm1', sources });
    return { before, asking, after: frame(wrap), body: wrap.querySelector('.ai-body').textContent, foot: !!wrap.querySelector('.msg-foot') };
  }, { tasks: TASKS, start: START, answered: ANSWERED, failed: FAILED, sources: SOURCES, FRAME });

  assert.equal(out.before.local, false);
  // 시작 줄만 온 동안: 로컬 카드(진행 중), 웹 카드는 생기지 않는다('웹 문서 에이전트' 이름에도) / while asking: the local card only, no web card
  assert.equal(out.asking.local, true);
  assert.equal(out.asking.web, false);
  assert.equal(out.asking.title, '로컬 지식 에이전트 로컬');
  assert.equal(out.asking.badge, '로컬');
  assert.equal(out.asking.sub, '로컬 에이전트에 질문 중');
  assert.deepEqual(out.asking.localLines, [{ text: START + '..', done: false, fail: false }]);
  // 끝난 뒤: 시작 줄은 과거형, 결과 줄은 완료, 연결 실패는 실패 표시 / afterwards: past tense, settled result lines, the failure marked
  const a = out.after;
  assert.equal(a.web, false);
  assert.equal(a.knowledge, true);
  assert.deepEqual(a.localLines, [
    { text: '로컬 지식 에이전트에 질문했습니다 · 본사 지식 에이전트, 웹 문서 에이전트', done: true, fail: false },
    { text: ANSWERED, done: true, fail: false },
    { text: FAILED, done: true, fail: true },
  ]);
  assert.deepEqual(a.common, ['결과를 취합해 답변을 작성했습니다']);   // 취합 줄은 로컬 카드 밖 / aggregation lines stay outside
  assert.equal(a.sub, '에이전트 1 · 파일 1');
  assert.equal(a.cap, '로컬 리소스 1개');
  assert.equal(a.chips.length, 1);
  assert.deepEqual(a.chips.map(c => [c.agent, c.doc, c.page, c.title]), [['kl_demo_hq', 'hq-doc-001', '1', '정보보안 기본 규정.pdf']]);
  assert.ok(a.chips[0].sid, 'chips carry the registered sid');
  assert.equal(a.chips[0].text, '정보보안 기본 규정.pdf p.1 · 본사 지식 에이전트');
  assert.ok(a.tree.includes('로컬 지식 에이전트'), a.tree.join());
  assert.ok(out.body.includes('(로컬 · 본사 지식 에이전트)'));
  assert.equal(out.foot, true);
});

test('restore: meta.trace lines + meta.sources rebuild the same local card; sources alone still give the card with its chips', async t => {
  const page = await fixture(t);
  // 서버가 남긴 이벤트 순서 그대로(chats_api._trace_collect) / the server-recorded event order (chats_api._trace_collect)
  const lines = [{ t: 'status', task_id: 'knowledge', status: 'running' }, { t: 'status', task_id: 'knowledge', status: 'done', detail: '근거 3개 청크 확보' },
    { t: 'thinking', text: START }, { t: 'thinking', text: ANSWERED }, { t: 'thinking', text: FAILED },
    { t: 'thinking', text: '결과를 취합해 답변을 작성하고 있습니다' }];
  const out = await page.evaluate(({ lines, sources, FRAME }) => {
    const frame = eval(FRAME);
    const tasks = [{ id: 'knowledge', label: '지식관리 Agent를 실행합니다', children: ['비밀번호 변경 주기'] }];
    const full = ai365KxStaticEl({ id: 'm1', content: '답변', meta: { trace: { tasks, lines }, sources } });
    const bare = ai365KxStaticEl({ id: 'm2', content: '답변', meta: { trace: { tasks, lines: lines.slice(0, 2) }, sources } });
    const none = ai365KxStaticEl({ id: 'm3', content: '답변', meta: { trace: { tasks, lines: lines.slice(0, 2) }, sources: { knowledge: sources.knowledge } } });
    [full, bare, none].forEach(el => chatInner.appendChild(el));
    return { full: frame(full), bare: frame(bare), none: frame(none) };
  }, { lines, sources: SOURCES, FRAME });
  assert.deepEqual(out.full.localLines.map(l => [l.text, l.done, l.fail]), [
    ['로컬 지식 에이전트에 질문했습니다 · 본사 지식 에이전트, 웹 문서 에이전트', true, false], [ANSWERED, true, false], [FAILED, true, true]]);
  assert.equal(out.full.web, false);
  assert.equal(out.full.sub, '에이전트 1 · 파일 1');
  assert.deepEqual(out.full.chips.map(c => c.doc), ['hq-doc-001']);
  assert.deepEqual(out.full.common, ['결과를 취합해 답변을 작성했습니다']);
  // 진행줄 없이 sources.local 만 있어도 카드 + 칩 / sources.local alone still builds the card and chips
  assert.equal(out.bare.local, true);
  assert.deepEqual(out.bare.localLines, []);
  assert.deepEqual(out.bare.chips.map(c => c.doc), ['hq-doc-001']);
  // 로컬이 없는 답변은 종전 모양(단일 카드, 로컬 카드 없음) / answers without local keep the former single-card look
  assert.equal(out.none.local, false);
  assert.equal(out.none.cap, '');
});

test('local only (2026-10-28): the server flag local_only drops the Public search copy from the knowledge card, live and on restore', async t => {
  const page = await fixture(t);
  const REASON = '선택한 로컬 지식 에이전트에 질문합니다. Public 문서는 검색하지 않았습니다.';
  const out = await page.evaluate(({ tasks, start, answered, reason, hq }) => {
    const card = root => {
      const c = root.querySelector('[data-kx-card="knowledge"]');
      return c ? { sub: c.querySelector('.ai365-kx-sub').textContent, lines: Array.from(c.querySelectorAll('.ai365-kx-line')).map(l => l.textContent), text: c.textContent,
        explore: !!c.querySelector('[data-kx-explore]') } : null;
    };
    const sources = { local: { agents: 1, files: 1, items: [hq] } };
    const wrap = document.createElement('div');
    chatInner.appendChild(wrap);
    const state = { body: null, text: '', tree: false };
    const H = ev => ai365HandleEvent(ev, wrap, state);
    H({ type: 'task_tree', tasks, parallel: false });
    H({ type: 'agent_status', task_id: 'knowledge', status: 'running' });
    H({ type: 'agent_status', task_id: 'knowledge', status: 'done', detail: reason, local_only: true });
    H({ type: 'thinking', text: start });
    H({ type: 'thinking', text: answered });
    H({ type: 'answer_head', source: '사내' });
    H({ type: 'token', text: '답변 (로컬 · 본사 지식 에이전트)' });
    H({ type: 'done', message_id: 'm1', sources });
    const lines = [{ t: 'status', task_id: 'knowledge', status: 'running' },
      { t: 'status', task_id: 'knowledge', status: 'done', detail: reason, local_only: true },
      { t: 'thinking', text: start }, { t: 'thinking', text: answered }];
    const el = ai365KxStaticEl({ id: 'm2', content: '답변', meta: { trace: { tasks: [{ id: 'knowledge', label: '지식관리 Agent를 실행합니다', children: ['q'] }], lines }, sources } });
    chatInner.appendChild(el);
    return { live: card(wrap), restored: card(el) };
  }, { tasks: TASKS, start: START, answered: ANSWERED, reason: REASON, hq: HQ });
  for (const [name, c] of [['live', out.live], ['restored', out.restored]]) {
    assert.ok(c, name);
    assert.equal(c.sub, 'Local', name);
    assert.deepEqual(c.lines, [REASON], name);
    assert.ok(!/권한 범위의 문서|검색 범위의 문서|참조 문단|전체 문서/.test(c.text), name + ': ' + c.text);
    assert.equal(c.explore, false, name + ': no [Explore] on a local-only card (explore searches Public)');
  }
});

test('resource block and panel: a local group with Local badges; rows open the permission proxy preview (PDF page, text body, other kinds without a request)', async t => {
  const page = await fixture(t);
  const txt = { title: '고객 미팅 기록 가이드.txt', page: null, doc_id: 'hq-doc-004', agent_id: 'kl_demo_hq', agent: '본사 지식 에이전트', model: 'Qwen 3.5-4B', kind: 'local' };
  const hwp = { title: '고객사 제안서 양식.hwp', page: null, doc_id: 'hq-doc-005', agent_id: 'kl_demo_hq', agent: '본사 지식 에이전트', model: '', kind: 'local' };
  const out = await page.evaluate(async ({ sources, txt, hwp }) => {
    window.AI365_ACTING_USER = { no: 7 };
    window.fetches = [];
    window.fetch = async url => { window.fetches.push(url); return new Response('CRM 등록 기한은 24시간입니다', { status: 200, headers: { 'content-type': 'text/plain; charset=utf-8' } }); };
    const all = { ...sources, local: { agents: 1, files: 3, items: [sources.local.items[0], txt, hwp] } };
    chatInner.innerHTML = ai365SourcesBlockHtml(all, 'm1');
    const block = {
      caps: Array.from(document.querySelectorAll('.ai365-res-cap')).map(c => c.textContent),
      chips: Array.from(document.querySelectorAll('.ai365-local-chip')).map(c => [c.querySelector('.ai365-local-badge').textContent, c.dataset.ai365Ldoc]),
    };
    const localOnly = ai365SourcesBlockHtml({ local: sources.local }, 'm2');   // Public 없이 로컬만 / local without Public
    document.querySelector('.ai365-local-chip').click();   // PDF 칩 → 미리보기 / the PDF chip → preview
    const pdf = { title: document.getElementById('artifactTitle').textContent, src: document.querySelector('#artifactBody iframe').getAttribute('src'),
      badge: document.querySelector('#artifactBody .ai365-local-badge').textContent, open: artifactPanel.classList.contains('open') };
    document.querySelector('#artifactBody [data-ai365-resopen]').click();   // ← 리소스 목록 → 패널 / back to the resource list
    const panel = {
      sech: Array.from(document.querySelectorAll('.ai365-src-sech span:first-child')).map(s => s.textContent),
      groups: Array.from(document.querySelectorAll('.ai365-src-group')).map(g => g.querySelector('span:not(.ic):not(.cnt):not(.chev)').textContent),
      rows: Array.from(document.querySelectorAll('.ai365-local-item')).map(r => [r.querySelector('.t').textContent, r.querySelector('.bc').textContent]),
    };
    document.querySelectorAll('.ai365-local-item')[1].click();   // 텍스트 문서 / the text document
    await new Promise(r => setTimeout(r, 50));
    const text = document.querySelector('.ai365-local-text') ? document.querySelector('.ai365-local-text').textContent : '';
    const fetched = window.fetches.slice();
    document.querySelector('#artifactBody [data-ai365-resopen]').click();
    document.querySelectorAll('.ai365-local-item')[2].click();   // hwp — 요청 없이 안내 / hwp: a notice, no request
    const other = { note: document.querySelector('.ai365-local-prev').textContent, fetches: window.fetches.length, iframe: !!document.querySelector('#artifactBody iframe') };
    return { block, localOnly: localOnly.length > 0 && localOnly.includes('ai365-local-chip'), pdf, panel, text, fetched, other };
  }, { sources: SOURCES, txt, hwp });
  assert.deepEqual(out.block.caps, ['사내 리소스 1개', '로컬 리소스 3개']);
  assert.deepEqual(out.block.chips, [['로컬', 'hq-doc-001'], ['로컬', 'hq-doc-004'], ['로컬', 'hq-doc-005']]);
  assert.equal(out.localOnly, true);
  assert.deepEqual(out.pdf, { title: '정보보안 기본 규정.pdf', src: '/api/knowledge-agents/kl_demo_hq/documents/hq-doc-001/preview?acting_user_id=7#page=1',
    badge: '로컬', open: true });
  assert.deepEqual(out.panel.sech, ['사내', '로컬 리소스']);
  assert.deepEqual(out.panel.groups, ['지식 관리', '로컬 지식 로컬']);
  assert.deepEqual(out.panel.rows, [['로컬 정보보안 기본 규정.pdf p.1', '본사 지식 에이전트 · Qwen 3.5-4B'],
    ['로컬 고객 미팅 기록 가이드.txt', '본사 지식 에이전트 · Qwen 3.5-4B'], ['로컬 고객사 제안서 양식.hwp', '본사 지식 에이전트']]);
  assert.equal(out.text, 'CRM 등록 기한은 24시간입니다');
  assert.deepEqual(out.fetched, ['/api/knowledge-agents/kl_demo_hq/documents/hq-doc-004/preview?acting_user_id=7']);
  assert.deepEqual(out.other, { note: '미리보기를 지원하지 않는 형식입니다', fetches: 1, iframe: false });
});

// 2026-09-30 리뷰: 문서 id 가 없는 로컬 항목은 미리보기를 열 수 없으므로 칩 · 목록 행을 누를 수 없게(미리보기 속성 없음) 그린다
// 2026-09-30 review: a local item without a doc_id cannot open a preview, so its chip and panel row render non-clickable (no preview attributes)
test('local items without a doc_id render as non-clickable chips and rows; clicking them opens nothing', async t => {
  const page = await fixture(t);
  const out = await page.evaluate(({ sources }) => {
    window.fetches = [];
    window.fetch = async url => { window.fetches.push(url); return new Response('', { status: 200 }); };
    const noId = { title: '출처 제목만 있는 문서', page: 2, doc_id: '', agent_id: 'kl_demo_hq', agent: '본사 지식 에이전트', model: '', kind: 'local' };
    const all = { local: { agents: 1, files: 2, items: [sources.local.items[0], noId] } };
    chatInner.innerHTML = ai365SourcesBlockHtml(all, 'm1');
    const chips = Array.from(document.querySelectorAll('.ai365-local-chip')).map(c => [c.tagName, c.classList.contains('static'), c.hasAttribute('data-ai365-ldoc')]);
    document.querySelectorAll('.ai365-local-chip')[1].click();
    const afterChip = { open: artifactPanel.classList.contains('open'), fetches: window.fetches.length };
    ai365OpenSources(document.querySelector('[data-ai365-resopen]').getAttribute('data-ai365-resopen'));
    const rows = Array.from(document.querySelectorAll('.ai365-local-item')).map(r => [r.tagName, r.classList.contains('static'), r.hasAttribute('data-ai365-ldoc')]);
    const body = document.getElementById('artifactBody').innerHTML;
    document.querySelectorAll('.ai365-local-item')[1].click();
    return { chips, afterChip, rows, same: document.getElementById('artifactBody').innerHTML === body };
  }, { sources: SOURCES });
  assert.deepEqual(out.chips, [['BUTTON', false, true], ['SPAN', true, false]]);
  assert.deepEqual(out.afterChip, { open: false, fetches: 0 });
  assert.deepEqual(out.rows, [['BUTTON', false, true], ['DIV', true, false]]);
  assert.equal(out.same, true);   // the panel stays on the resource list
});

test('English: the badge says Local, static labels translate, server progress lines stay as sent', async t => {
  const page = await fixture(t);
  const out = await page.evaluate(({ tasks, start, answered, sources, FRAME }) => {
    window.__lang = 'en';
    const frame = eval(FRAME);
    const el = ai365KxStaticEl({ id: 'm1', content: 'answer', meta: { trace: { tasks: [{ id: 'knowledge', label: 'x', children: ['q'] }],
      lines: [{ t: 'thinking', text: start }, { t: 'thinking', text: answered }] }, sources } });
    chatInner.appendChild(el);
    const block = document.createElement('div');
    block.innerHTML = ai365SourcesBlockHtml(sources, 'm1');
    return { f: frame(el), cap: block.querySelector('.ai365-res-cap.local').textContent, chipBadge: block.querySelector('.ai365-local-chip .ai365-local-badge').textContent };
  }, { tasks: TASKS, start: START, answered: ANSWERED, sources: SOURCES, FRAME });
  assert.equal(out.f.title, 'Local knowledge agent Local');
  assert.equal(out.f.badge, 'Local');
  assert.equal(out.f.cap, 'Local resources 1');
  assert.equal(out.f.sub, 'Agents 1 · Files 1');
  // 알려진 제약: 이름이 든 서버 줄은 원문 그대로(시작 줄만 과거형) / known limitation: server lines with names stay as sent (start line in past tense)
  assert.deepEqual(out.f.localLines.map(l => l.text), ['로컬 지식 에이전트에 질문했습니다 · 본사 지식 에이전트, 웹 문서 에이전트', ANSWERED]);
  assert.ok(out.f.tree.includes('Local knowledge agent'), out.f.tree.join());
  assert.equal(out.cap, 'Local resources 1');
  assert.equal(out.chipBadge, 'Local');
});

test('EN dictionary: every new local string has a unique English value and there is no bare 로컬 ↔ Local pair', () => {
  const en = dict();
  const want = { '로컬 지식 에이전트': 'Local knowledge agent', '로컬 리소스': 'Local resources', '로컬 지식': 'Local knowledge',
    '참조한 로컬 문서 없음': 'No local documents referenced', '로컬 에이전트에 질문 중': 'Asking local agents' };
  Object.entries(want).forEach(([k, v]) => {
    assert.equal(en[k], v, k);
    assert.deepEqual(Object.keys(en).filter(x => en[x] === v), [k], 'unique EN value for ' + k);
  });
  assert.ok(!('로컬' in en), 'no bare 로컬 key');
  assert.deepEqual(Object.keys(en).filter(x => en[x] === 'Local'), [], 'no key translates to a bare Local');
  // 이 기능이 만든 화면 문구에는 em dash 가 없다 / no em dash in the UI strings this feature renders
  const fnSrc = ['ai365KxLocalHtml', 'ai365LocalChipsHtml', 'ai365LocalBadgeHtml', 'ai365OpenLocalPreview'].map(fn).join('\n');
  const literals = [...fnSrc.matchAll(/'([^'\\\n]*(?:\\.[^'\\\n]*)*)'/g)].map(m => m[1]);
  literals.forEach(s => assert.ok(!s.includes('—'), s));
  // 한국어 정적 문구는 모두 사전에 있다(배지 '로컬' 은 코드가 언어별로 고른다) / every static Korean string is in the dictionary (the badge is chosen in code)
  literals.filter(s => /[가-힣]/.test(s) && !/[<>=]/.test(s) && s !== '로컬' && !/^(에이전트 |파일 |질문하고|질문했습니다)/.test(s) && s !== ' · 파일 ')
    .forEach(s => assert.ok(s in en, 'EN key for ' + s));
});
