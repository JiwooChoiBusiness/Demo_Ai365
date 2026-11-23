// Run with Playwright available on NODE_PATH: node --test tests/test_flow_entry_ui.cjs
// 워크플로우 진입(2026-09-30 워크플로우 채팅 개편): 컴포저 + 메뉴 루트 · 선택 모달(목록 · 미리보기 · 검색) · 컴포저 칩(1회성 전송) ·
// 말풍선 칩 · 홈 퀵 아이콘 순서 · 실행 프레임의 현재 단계 트리 · EN 사전. 어댑터의 실제 함수를 잘라 격리 브라우저에서 돌린다(fetch 스텁).
// Workflow entry (2026-09-30 workflow-chat redesign): the composer + menu root, the picker (list, preview, search), the composer
// chip (one-shot send), the bubble chip, the home quick-icon order, the execution frame's current-stage tree and the EN
// dictionary. Real adapter functions sliced from source and run in an isolated browser (fetch is stubbed).
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { chromium } = require('playwright');
const source = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8').replace(/\r\n/g, '\n');

// test_flow_cards_ui.cjs 와 같은 규칙(한 줄 함수 포함) / same conventions as test_flow_cards_ui.cjs (single-line functions too)
function fn(name) {
  const start = source.search(new RegExp('^(?:async )?function ' + name + '\\(', 'm'));
  assert.ok(start >= 0, name);
  const eol = source.indexOf('\n', start);
  const firstLine = source.slice(start, eol);
  if (/\}\s*$/.test(firstLine)) return firstLine;
  return source.slice(start, source.indexOf('\n}', start) + 2);
}
function decl(name) {
  const start = source.search(new RegExp('^(?:const|let) ' + name + ' = ', 'm'));
  assert.ok(start >= 0, name);
  const eol = source.indexOf('\n', start);
  const firstLine = source.slice(start, eol);
  if (/;\s*(\/\/.*)?$/.test(firstLine)) return firstLine;
  return source.slice(start, source.indexOf('\n};', start) + 3);
}
// 이름 붙은 즉시 실행 함수 / a named IIFE
function iife(name) {
  const s = source.indexOf('(function ' + name + '() {');
  assert.ok(s >= 0, name);
  return source.slice(s, source.indexOf('\n})();', s) + 6);
}
function dict() {
  const a = source.indexOf('const AI365_KO2EN = {'), b = source.indexOf('\n};', a);
  return vm.runInNewContext('(' + source.slice(a + 'const AI365_KO2EN = '.length, b + 2) + ')');
}

const ENTRY = ['ai365T', 'ai365Fetch', 'ai365WfActing', 'ai365WfFileLabel', 'ai365WfStageTitle', 'ai365WfFilter', 'ai365WfPickerListHtml',
  'ai365WfPickerPreviewHtml', 'ai365WfPickerEnsure', 'ai365WfPickerPaintList', 'ai365WfPickerPaintPreview', 'ai365WfPickerSelect',
  'ai365WfPickerLoadSummary', 'ai365WfPickerOpen', 'ai365WfPickerClose', 'ai365WfPickerChoose', 'ai365WfChipKey', 'ai365WfChipGet',
  'ai365WfChipSet', 'ai365WfChipTake', 'ai365WfChipTakeForBlank', 'ai365WfChipDropBlank', 'ai365WfChipInner', 'ai365WfChipPaint', 'ai365WfChipPad',
  'ai365WfBubbleChipHtml', 'ai365WfBubbleChip', 'ai365FlowKey', 'ai365FlowAlive', 'ai365FlowRunStart', 'ai365FlowRenderBar',
  'ai365FlowBarHtml', 'ai365FlowTx', 'ai365FlowStageLabel', 'ai365FlowExpireCards', 'ai365FlowHandle'];

const FLOWS = [
  { id: 'fl_brief', name: '월간 영업 브리핑', description: '지점 매출을 모아 브리핑을 만듭니다.', stages: [
    { nodes: [{ agent: 'data', instruction: '지점별 월 매출 조회' }, { agent: 'data', instruction: '파이프라인 조회' }], docgen: { format: 'xlsx' } },
    { nodes: [{ agent: 'knowledge', instruction: '목표 확인' }, { agent: 'groupware', instruction: '회의 일정 확인' }, { agent: 'api', instruction: '', prompt: 'ERP 재고 조회' }] },
    { nodes: [{ agent: 'web', instruction: '업계 동향 조사' }], docgen: { format: 'pptx' } }] },
  { id: 'fl_onboard', name: '신입사원 온보딩 안내', description: '규정과 교육을 정리합니다.', stages: [{ nodes: [{ agent: 'knowledge', instruction: '규정 정리' }] }] },
];
const LABELS = { knowledge: '지식 관리', data: '데이터 분석', groupware: '그룹웨어', auto: '업무 자동화', web: '웹 검색', api: '외부 도구' };

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

async function fixture(t, opts = {}) {
  const page = await browser.newPage();
  t.after(() => page.close());
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  t.after(() => assert.deepEqual(errors, []));
  await page.setContent(
    '<style>.composer{position:relative;padding:18px 16px 12px;width:600px}.composer-input{width:100%;box-sizing:border-box;padding:2px 6px 14px}'
    + '.cmp-att-menu{position:fixed;z-index:1200;display:none;background:#fff}.cmp-att-menu.open{display:block}.cmp-mi{display:flex;width:200px;height:36px}</style>'
    + '<div id="viewHome" class="view active" style="padding-top:420px"><div class="composer"><input class="composer-input" id="homeInput">'
    + '<div class="composer-row"><button id="homeAttBtn" type="button">+</button></div></div></div>'
    + '<div id="viewChat" class="view"><div id="chat"></div><div class="composer-wrap"><div class="composer"><input class="composer-input" id="chatInput">'
    + '<div class="composer-row"><button id="chatAttBtn" type="button">+</button><button id="sdPlus" type="button" data-cmpatt>+</button></div></div></div></div>'
    + '<div class="cmp-att-menu" id="cmpAttMenu"></div>');
  await page.addScriptTag({ content: `
    const chatInner = document.getElementById('chat');
    let currentChatId = ${opts.chat === undefined ? "'c1'" : JSON.stringify(opts.chat)};
    let AI365_FLOW_RUN = null, AI365_FLOW_LAST = null;
    const AI365_BACKEND_IDS = new Set(['c1', 'c2']);
    ${decl('AI365_KO2EN')}
    ${decl('AI365_WF_ICON')}
    ${decl('AI365_WFP')}
    ${decl('AI365_WFP_FILE')}
    ${decl('AI365_WF_CHIPS')}
    const ai365Esc = s => { const el = document.createElement('span'); el.textContent = s == null ? '' : String(s); return el.innerHTML.replace(/"/g, '&quot;'); };
    const ai365CurrentLang = () => window.__lang || 'ko';
    const toast = m => { window.toasts = (window.toasts || []).concat([m]); };
    let ai365StreamReply = (text, opts) => { window.sent = (window.sent || []).concat([{ text, opts }]); };
    let openChat = function (id) { currentChatId = id; };
    window.showView = function (name) {
      document.getElementById('viewHome').classList.toggle('active', name === 'home');
      document.getElementById('viewChat').classList.toggle('active', name === 'chat');
    };
    window.AI365_applyEffective = function () {};
    // 목업 + 메뉴 흉내: 루트 두 항목을 버튼 위 8px 에 연다(목업 cmpMenuOpen · cmpMenuPosition 과 같은 규칙)
    // Mockup + menu stand-in: renders the two root items 8px above the button (same rule as the mockup's cmpMenuOpen/cmpMenuPosition)
    const menu = document.getElementById('cmpAttMenu');
    window.renderRoot = function (anchor) {
      menu.innerHTML = '<button type="button" class="cmp-mi" data-cmpmi="coll"><span>컬렉션 첨부</span></button>'
        + '<button type="button" class="cmp-mi" data-cmpmi="file"><span>파일 첨부</span></button>';
      menu.classList.add('open');
      const r = anchor.getBoundingClientRect();
      let top = r.top - menu.offsetHeight - 8; if (top < 8) top = r.bottom + 8;
      menu.style.top = top + 'px'; menu.style.left = r.left + 'px';
    };
    ['homeAttBtn', 'chatAttBtn', 'sdPlus'].forEach(id => document.getElementById(id).addEventListener('click', e => renderRoot(e.currentTarget)));
    window.AI365_ATT_HOOKS = { close: () => menu.classList.remove('open'), open: a => renderRoot(a) };
    ${ENTRY.map(fn).join('\n')}
    ${iife('ai365WfStyle')}
    ${iife('ai365WfMenu')}
    ${iife('ai365WfChipWire')}
    ${iife('ai365TplMenu')}
  ` });
  return page;
}
// 목록 · 요약 fetch 스텁(요약은 약속을 밖에서 풀 수 있다) / flows and summary fetch stub (summaries can be resolved from outside)
const FETCH = (flows, summaries, opts) => `
  window.fetches = [];
  window.pending = {};
  window.fetch = async (url) => {
    window.fetches.push(url);
    if (/^\\/api\\/flows\\?/.test(url)) return new Response(JSON.stringify({ flows: ${JSON.stringify(flows)}, agent_labels: ${JSON.stringify(LABELS)} }), { status: 200 });
    const m = /^\\/api\\/flows\\/([^/]+)\\/summary/.exec(url);
    if (m) {
      const sums = ${JSON.stringify(summaries || {})};
      if (${!!(opts && opts.hold)}) await new Promise(r => { window.pending[m[1]] = r; });
      if (!sums[m[1]]) return new Response('{}', { status: 500 });
      return new Response(JSON.stringify(sums[m[1]]), { status: 200 });
    }
    return new Response('{"templates":[]}', { status: 200 });
  };
`;
const SUMS = { fl_brief: { summary: 'AI 요약입니다.', resources: ['지점별 월 매출', 'A사 경영지표.pdf'] }, fl_onboard: { summary: '온보딩 요약', resources: [] } };

test('+ menu root on home and chat: upload (coming soon), Collections ›, Workflow, then the template item; the schedules + keeps the old menu', async t => {
  const page = await fixture(t);
  await page.addScriptTag({ content: FETCH(FLOWS, SUMS) });
  const read = () => page.evaluate(() => ({
    items: Array.from(document.querySelectorAll('#cmpAttMenu > .cmp-mi')).map(b => b.textContent.trim()),
    soon: (() => { const b = document.querySelector('[data-ai365-cmpsoon]'); return b ? [b.title, b.getAttribute('aria-disabled'), b.hasAttribute('data-cmpmi')] : null; })(),
    chev: !!document.querySelector('[data-cmpmi="coll"] .ai365-cmp-chev'),
    placed: (() => { const m = document.getElementById('cmpAttMenu').getBoundingClientRect(); return Math.round(m.bottom); })(),
  }));
  await page.click('#homeAttBtn');
  await page.waitForSelector('#cmpAttMenu [data-ai365-tpl]');
  const home = await read();
  assert.deepEqual(home.items, ['이미지 및 파일 업로드', '컬렉션', '워크플로우', '템플릿 가져오기']);
  assert.deepEqual(home.soon, ['준비 중입니다', 'true', false]);   // tooltip, greyed, not a mockup item
  assert.equal(home.chev, true);
  const btnTop = await page.evaluate(() => Math.round(document.getElementById('homeAttBtn').getBoundingClientRect().top));
  assert.equal(home.placed, btnTop - 8);   // re-placed above the + button after the item count changed
  // 준비 중 항목은 아무것도 하지 않는다(메뉴 유지) — aria-disabled 라 강제 클릭 / the coming-soon item does nothing (the menu stays); forced since it is aria-disabled
  await page.click('[data-ai365-cmpsoon]', { force: true });
  assert.equal(await page.evaluate(() => document.getElementById('cmpAttMenu').classList.contains('open')), true);
  // 워크플로우 = 메뉴 닫고 선택 모달(홈 자리) / Workflow closes the menu and opens the picker for home
  await page.click('[data-ai365-wfmi]');
  await page.waitForSelector('#ai365WfpOv.open');
  assert.equal(await page.evaluate(() => document.getElementById('cmpAttMenu').classList.contains('open')), false);
  assert.equal(await page.evaluate(() => AI365_WFP.place), 'home');
  await page.keyboard.press('Escape');
  // 채팅 컴포저도 같은 메뉴 / the chat composer gets the same menu
  await page.evaluate(() => { document.getElementById('viewChat').style.display = 'block'; });
  await page.click('#chatAttBtn');
  await page.waitForSelector('#cmpAttMenu [data-ai365-wfmi]');
  assert.deepEqual((await read()).items.slice(0, 3), ['이미지 및 파일 업로드', '컬렉션', '워크플로우']);
  await page.click('[data-ai365-wfmi]');
  await page.waitForSelector('#ai365WfpOv.open');
  assert.equal(await page.evaluate(() => AI365_WFP.place), 'chat');
  await page.keyboard.press('Escape');
  // 예약 작업 페이지의 + 는 종전 메뉴 그대로 / the schedules page + keeps the old menu
  await page.click('#sdPlus');
  await page.waitForTimeout(30);
  const sd = await read();
  assert.deepEqual(sd.items.slice(0, 2), ['컬렉션 첨부', '파일 첨부']);
  assert.equal(sd.soon, null);
});

test('picker: list with stage counts, first preselected, preview built from the stage definitions and the summary; search filters', async t => {
  const page = await fixture(t);
  await page.addScriptTag({ content: FETCH(FLOWS, SUMS) });
  await page.evaluate(() => ai365WfPickerOpen('home'));
  await page.waitForFunction(() => /AI 요약입니다/.test((document.querySelector('.ai365-wfp-body') || {}).textContent || ''));
  const out = await page.evaluate(() => ({
    rows: Array.from(document.querySelectorAll('.ai365-wfp-it')).map(b => [b.querySelector('.nm').textContent, b.querySelector('.st').textContent, b.classList.contains('on'), b.getAttribute('aria-selected')]),
    ph: document.querySelector('[data-wfp-q]').placeholder,
    eyebrow: document.querySelector('.ai365-wfp-eyebrow').textContent,
    title: document.querySelector('.ai365-wfp-title').textContent,
    labels: Array.from(document.querySelectorAll('.ai365-wfp-lb')).map(l => l.textContent),
    desc: document.querySelectorAll('.ai365-wfp-sec')[0].querySelector('.ai365-wfp-tx').textContent,
    stages: Array.from(document.querySelectorAll('.ai365-wfp-st')).map(s => ({ no: s.querySelector('.ai365-wfp-no').textContent,
      title: s.querySelector('.ai365-wfp-sttt').textContent, tasks: Array.from(s.querySelectorAll('.ai365-wfp-tk')).map(x => x.textContent),
      file: s.querySelector('.ai365-wfp-file').textContent })),
    res: document.querySelectorAll('.ai365-wfp-sec')[2].querySelector('.ai365-wfp-tx').textContent,
    go: document.querySelector('[data-wfp-go]').textContent,
    fetches: window.fetches,
  }));
  assert.deepEqual(out.rows, [['월간 영업 브리핑', '3단계', true, 'true'], ['신입사원 온보딩 안내', '1단계', false, 'false']]);
  assert.equal(out.ph, '워크플로우 검색');
  assert.equal(out.eyebrow, '▶ 워크플로우 미리보기');
  assert.equal(out.title, '월간 영업 브리핑');
  assert.deepEqual(out.labels, ['설명', '실행 흐름', '활용 리소스']);
  assert.equal(out.desc, 'AI 요약입니다.');
  assert.deepEqual(out.stages, [
    { no: '1', title: '데이터 분석 2개', tasks: ['지점별 월 매출 조회', '파이프라인 조회'], file: 'Excel 파일' },
    { no: '2', title: '지식 관리 + 그룹웨어 + 외부 도구', tasks: ['목표 확인', '회의 일정 확인', 'ERP 재고 조회'], file: '-' },
    { no: '3', title: '웹 검색', tasks: ['업계 동향 조사'], file: 'PPT 프레젠테이션' },
  ]);
  assert.equal(out.res, '지점별 월 매출, A사 경영지표.pdf');
  assert.equal(out.go, '이 워크플로우 선택');
  assert.deepEqual(out.fetches, ['/api/flows?acting_user_id=', '/api/flows/fl_brief/summary?acting_user_id=']);
  // 검색 — 이름 · 설명 / search by name or description
  await page.fill('[data-wfp-q]', '규정');
  assert.deepEqual(await page.locator('.ai365-wfp-it .nm').allTextContents(), ['신입사원 온보딩 안내']);
  await page.fill('[data-wfp-q]', 'zzz');
  assert.equal(await page.locator('.ai365-wfp-empty').textContent(), '일치하는 워크플로우가 없습니다');
  await page.fill('[data-wfp-q]', '');
  // 다른 워크플로우 선택 → 그 요약을 한 번만 받는다(캐시) / selecting another fetches its summary once (cached)
  await page.click('[data-wfp-id="fl_onboard"]');
  await page.waitForFunction(() => /온보딩 요약/.test(document.querySelector('.ai365-wfp-body').textContent));
  await page.click('[data-wfp-id="fl_brief"]');
  await page.click('[data-wfp-id="fl_onboard"]');
  assert.equal(await page.evaluate(() => window.fetches.filter(u => /fl_onboard\/summary/.test(u)).length), 1);
  assert.equal(await page.locator('.ai365-wfp-sec').nth(2).locator('.ai365-wfp-tx').textContent(), '-');   // no resources
});

test('picker: description falls back while the summary loads or fails; empty list; Esc, backdrop and ✕ close it', async t => {
  const page = await fixture(t);
  await page.addScriptTag({ content: FETCH(FLOWS, { fl_brief: { summary: 'AI 요약입니다.', resources: ['r'] } }, { hold: true }) });
  await page.evaluate(() => ai365WfPickerOpen('chat'));
  await page.waitForSelector('.ai365-wfp-it.on');
  const secs = () => page.evaluate(() => Array.from(document.querySelectorAll('.ai365-wfp-sec')).map(s => s.querySelector('.ai365-wfp-tx') ? s.querySelector('.ai365-wfp-tx').textContent : ''));
  let s = await secs();
  assert.deepEqual([s[0], s[2]], ['지점 매출을 모아 브리핑을 만듭니다.', '불러오는 중…']);   // flow description while loading
  await page.evaluate(() => window.pending.fl_brief());
  await page.waitForFunction(() => /AI 요약입니다/.test(document.querySelector('.ai365-wfp-body').textContent));
  // 요약 실패 → 설명 그대로, 리소스 '-' / a failed summary keeps the description and shows '-' for resources
  await page.click('[data-wfp-id="fl_onboard"]');
  await page.evaluate(() => window.pending.fl_onboard());
  await page.waitForFunction(() => document.querySelectorAll('.ai365-wfp-sec')[2].textContent.endsWith('-'));
  s = await secs();
  assert.deepEqual([s[0], s[2]], ['규정과 교육을 정리합니다.', '-']);
  // 닫기 세 가지 / three ways to close
  await page.keyboard.press('Escape');
  assert.equal(await page.evaluate(() => document.getElementById('ai365WfpOv').classList.contains('open')), false);
  await page.evaluate(() => ai365WfPickerOpen('chat'));
  await page.waitForSelector('#ai365WfpOv.open .ai365-wfp-it');
  await page.mouse.click(5, 5);   // backdrop
  assert.equal(await page.evaluate(() => document.getElementById('ai365WfpOv').classList.contains('open')), false);
  await page.evaluate(() => ai365WfPickerOpen('chat'));
  await page.waitForSelector('#ai365WfpOv.open .ai365-wfp-it');
  await page.click('[data-wfp-close]');
  assert.equal(await page.evaluate(() => document.getElementById('ai365WfpOv').classList.contains('open')), false);
  // 빈 목록 / empty list
  await page.addScriptTag({ content: FETCH([], {}) });
  await page.evaluate(() => ai365WfPickerOpen('chat'));
  await page.waitForSelector('.ai365-wfp-empty');
  await page.waitForFunction(() => !AI365_WFP.loading);
  assert.equal(await page.locator('.ai365-wfp-empty').textContent(), '실행할 수 있는 워크플로우가 없습니다');
  assert.equal(await page.locator('[data-wfp-go]').isDisabled(), true);
});

test('choosing puts a chip inside the composer before the text; ✕ and Backspace in an empty input remove it; chat chips are per chat', async t => {
  const page = await fixture(t);
  await page.addScriptTag({ content: FETCH(FLOWS, SUMS) });
  await page.evaluate(() => ai365WfPickerOpen('home'));
  await page.waitForSelector('.ai365-wfp-it.on');
  await page.click('[data-wfp-go]');
  const chip = await page.evaluate(() => {
    const el = document.getElementById('ai365WfChip-home');
    const inp = document.getElementById('homeInput');
    return { first: el.parentElement.firstElementChild === el, text: el.textContent, pad: inp.style.paddingLeft, width: el.offsetWidth,
      chipped: el.parentElement.classList.contains('ai365-wf-chipped'), focused: document.activeElement === inp,
      open: document.getElementById('ai365WfpOv').classList.contains('open'), skip: el.hasAttribute('data-i18n-skip'),
      x: el.querySelector('[data-wf-chip-x]').getAttribute('aria-label') };
  });
  assert.deepEqual([chip.first, chip.text, chip.chipped, chip.focused, chip.open, chip.skip, chip.x],
    [true, '월간 영업 브리핑3단계', true, true, false, true, '워크플로우 제거']);
  assert.equal(chip.pad, (chip.width + 14) + 'px');   // typed text starts after the chip
  // Backspace — 글자가 있으면 그대로, 비어 있으면 칩을 뗀다 / Backspace keeps the chip while text remains, removes it when empty
  await page.fill('#homeInput', 'a');
  await page.press('#homeInput', 'End');
  await page.press('#homeInput', 'Backspace');
  assert.equal(await page.locator('#ai365WfChip-home').count(), 1);
  await page.press('#homeInput', 'Backspace');
  assert.equal(await page.locator('#ai365WfChip-home').count(), 0);
  assert.equal(await page.evaluate(() => document.getElementById('homeInput').style.paddingLeft), '');
  // ✕ / the ✕ button
  await page.evaluate(() => ai365WfChipSet('home', { id: 'fl_onboard', name: '신입사원 온보딩 안내', stages: 1 }));
  await page.evaluate(() => document.querySelector('[data-wf-chip-x]').click());
  assert.equal(await page.locator('#ai365WfChip-home').count(), 0);
  // 채팅 칩은 채팅별 / chat chips belong to their chat
  await page.evaluate(() => { document.getElementById('viewChat').style.display = 'block'; ai365WfChipSet('chat', { id: 'fl_brief', name: '월간 영업 브리핑', stages: 3 }); });
  assert.equal(await page.locator('#ai365WfChip-chat').count(), 1);
  await page.evaluate(() => openChat('c2'));
  assert.equal(await page.locator('#ai365WfChip-chat').count(), 0);
  await page.evaluate(() => openChat('c1'));
  assert.equal(await page.locator('#ai365WfChip-chat').count(), 1);
  // 같은 신원의 AI365_applyEffective(리소스 동기화 · 부팅)는 칩을 그대로 두고, 뷰애즈 전환(신원 변경)은 모두 비운다(2026-09-30 리뷰)
  // AI365_applyEffective with the same identity (resource sync, boot) keeps the chips; a view-as switch (new identity) clears them all
  await page.evaluate(() => window.AI365_applyEffective());
  assert.equal(await page.locator('#ai365WfChip-chat').count(), 1);
  await page.evaluate(() => { window.AI365_ACTING_USER = { no: 12 }; window.AI365_applyEffective(); });
  assert.equal(await page.locator('#ai365WfChip-chat').count(), 0);
});

// 2026-09-30 리뷰: 새 채팅이 만들어질 때 채팅 없는 화면('_new')의 남은 칩은 넘어가지 않는다
// 2026-09-30 review: a leftover chip of the chat-less screen ('_new') never carries over to a new chat
test('a leftover chat-less chip is dropped when a new chat is created', async t => {
  const page = await fixture(t, { chat: null });
  const out = await page.evaluate(() => {
    document.getElementById('viewChat').style.display = 'block';
    ai365WfChipSet('chat', { id: 'fl_brief', name: '월간 영업 브리핑', stages: 3 });   // key '_new'
    const before = !!document.getElementById('ai365WfChip-chat');
    ai365WfChipDropBlank();
    return { before, after: !!document.getElementById('ai365WfChip-chat'), store: Object.keys(AI365_WF_CHIPS.chat) };
  });
  assert.deepEqual(out, { before: true, after: false, store: [] });
});

// 2026-09-30 리뷰: 템플릿 칩과 워크플로우 칩은 한 자리에 하나만 — 나중에 고른 쪽이 앞의 것을 뗀다
// 2026-09-30 review: one of template or workflow chip per place; the later pick removes the earlier one
test('template and workflow chips are mutually exclusive in a composer', async t => {
  const page = await fixture(t);
  await page.addScriptTag({ content: FETCH(FLOWS, SUMS) });
  await page.evaluate(() => {
    window.tplCalls = [];
    window.AI365_templateTake = place => { window.tplCalls.push('take:' + place); return null; };
    window.AI365_templateAttach = (t, anchor) => { window.tplCalls.push('attach:' + t.id + ':' + (anchor && anchor.id)); };
    const realFetch = window.fetch;
    window.fetch = async url => /\/api\/boards\/templates/.test(url)
      ? new Response(JSON.stringify({ templates: [{ id: 'tp1', name: '주간 보고', format: 'docx', groups: [] }] }), { status: 200 })
      : realFetch(url);
  });
  // 워크플로우 선택 → 그 자리의 템플릿을 뗀다 / choosing a workflow removes that place's template
  await page.evaluate(() => ai365WfPickerOpen('home'));
  await page.waitForSelector('.ai365-wfp-it.on');
  await page.click('[data-wfp-go]');
  assert.deepEqual(await page.evaluate(() => window.tplCalls), ['take:home']);
  assert.equal(await page.locator('#ai365WfChip-home').count(), 1);
  // 템플릿 선택 → 그 자리의 워크플로우 칩을 뗀다 / choosing a template removes that place's workflow chip
  await page.click('#homeAttBtn');
  await page.waitForSelector('#cmpAttMenu [data-ai365-tpl]');
  await page.click('[data-ai365-tpl]');
  await page.waitForSelector('[data-ai365-tplpick="tp1"]');
  await page.click('[data-ai365-tplpick="tp1"]');
  assert.deepEqual(await page.evaluate(() => window.tplCalls), ['take:home', 'attach:tp1:homeAttBtn']);
  assert.equal(await page.locator('#ai365WfChip-home').count(), 0);
});

test('sending with the chip runs the workflow once: bubble chip, progress bar and /api/flows/run; the next message is a normal one', async t => {
  const page = await fixture(t);
  const out = await page.evaluate(() => {
    document.getElementById('viewChat').style.display = 'block';
    chatInner.innerHTML = '<div class="msg msg-user"><div class="user-bubble">3월 기준으로</div></div>';
    ai365WfChipSet('chat', { id: 'fl_brief', name: '월간 영업 브리핑', stages: 3 });
    const first = ai365FlowHandle('3월 기준으로');
    const r = {
      first, sent: window.sent.map(s => ({ text: s.text, flowId: s.opts.flowId })),
      chip: document.querySelector('.msg-user .ai365-wf-uchip') ? document.querySelector('.msg-user .ai365-wf-uchip').textContent : '',
      chipBeforeBubble: !!document.querySelector('.ai365-wf-uchip + .user-bubble'),
      composerChip: document.querySelectorAll('#ai365WfChip-chat').length,
      run: Object.assign({}, AI365_FLOW_RUN),
      bar: document.getElementById('ai365FlowBar') ? document.getElementById('ai365FlowBar').textContent : '',
    };
    r.second = ai365FlowHandle('다음 질문');   // one-shot: no chip anymore
    // 백엔드 채팅이 아니면 칩을 쓰지 않고 남겨 둔다 / outside a backend chat the chip is left in place
    currentChatId = 'demo';
    ai365WfChipSet('chat', { id: 'fl_brief', name: '월간 영업 브리핑', stages: 3 });
    r.demo = ai365FlowHandle('데모');
    r.demoChip = !!ai365WfChipGet('chat');
    return r;
  });
  assert.equal(out.first, true);
  assert.deepEqual(out.sent, [{ text: '3월 기준으로', flowId: 'fl_brief' }]);
  assert.equal(out.chip, '월간 영업 브리핑3단계');
  assert.equal(out.chipBeforeBubble, true);
  assert.equal(out.composerChip, 0);
  assert.deepEqual(out.run, { chat: 'c1', name: '월간 영업 브리핑', total: 3, stage: 1, runId: '', flowId: 'fl_brief', actor: '' });
  assert.equal(out.bar, '월간 영업 브리핑3단계 중 1단계중단');
  assert.equal(out.second, false);
  assert.equal(out.demo, false);
  assert.equal(out.demoChip, true);
});

test('a new chat takes the home chip on home and the chat-less screen chip on that screen, nothing elsewhere', async t => {
  const page = await fixture(t, { chat: null });
  const out = await page.evaluate(() => {
    ai365WfChipSet('home', { id: 'h', name: 'H', stages: 1 });
    ai365WfChipSet('chat', { id: 'n', name: 'N', stages: 2 });   // key '_new' (no chat yet)
    const r = [ai365WfChipTakeForBlank()];
    window.showView('chat');
    r.push(ai365WfChipTakeForBlank());
    window.showView('collection');
    ai365WfChipSet('home', { id: 'h2', name: 'H2', stages: 1 });
    r.push(ai365WfChipTakeForBlank());
    return r.map(x => x && x.id);
  });
  assert.deepEqual(out, ['h', 'n', null]);
});

test('English: picker, menu and chip labels translate; stage counts use their own template', async t => {
  const page = await fixture(t);
  await page.addScriptTag({ content: FETCH(FLOWS, SUMS) });
  await page.evaluate(() => { window.__lang = 'en'; });
  await page.click('#homeAttBtn');
  await page.waitForSelector('#cmpAttMenu [data-ai365-wfmi]');
  assert.deepEqual((await page.locator('#cmpAttMenu > .cmp-mi').allTextContents()).slice(0, 3), ['Upload images and files', 'Collections', 'Workflow']);
  assert.equal(await page.locator('[data-ai365-cmpsoon]').getAttribute('title'), 'Not available yet');
  await page.click('[data-ai365-wfmi]');
  await page.waitForFunction(() => /AI 요약입니다/.test((document.querySelector('.ai365-wfp-body') || {}).textContent || ''));
  const en = await page.evaluate(() => ({
    ph: document.querySelector('[data-wfp-q]').placeholder,
    st: document.querySelector('.ai365-wfp-it .st').textContent,
    eyebrow: document.querySelector('.ai365-wfp-eyebrow').textContent,
    labels: Array.from(document.querySelectorAll('.ai365-wfp-lb')).map(l => l.textContent),
    titles: Array.from(document.querySelectorAll('.ai365-wfp-sttt')).map(x => x.textContent),
    files: Array.from(document.querySelectorAll('.ai365-wfp-file')).map(x => x.textContent),
    go: document.querySelector('[data-wfp-go]').textContent,
  }));
  assert.deepEqual(en, { ph: 'Search workflows', st: '3 stages', eyebrow: '▶ Workflow preview', labels: ['Description', 'Execution Flow', 'Resources used'],
    titles: ['Data Analysis ×2', 'Knowledge + Groupware + External tool', 'Web search'], files: ['Excel file', '-', 'PPT presentation'], go: 'Use this workflow' });
  await page.click('[data-wfp-id="fl_onboard"]');
  await page.click('[data-wfp-go]');
  assert.equal(await page.locator('#ai365WfChip-home').textContent(), '신입사원 온보딩 안내1 stage');
});

test('home quick icons show groupware first by CSS order only (DOM order unchanged)', async t => {
  const page = await browser.newPage();
  t.after(() => page.close());
  await page.setContent('<div class="quick-actions" style="display:flex;gap:10px">'
    + '<button class="quick-action">지식 관리</button><button class="quick-action">데이터 분석</button>'
    + '<button class="quick-action" data-qa="groupware">그룹웨어</button><button class="quick-action">업무 자동화</button></div>');
  await page.addScriptTag({ content: iife('ai365WfStyle') });
  const out = await page.evaluate(() => {
    const all = Array.from(document.querySelectorAll('.quick-actions .quick-action'));
    return { dom: all.map(b => b.textContent), visual: all.slice().sort((a, b) => a.getBoundingClientRect().x - b.getBoundingClientRect().x).map(b => b.textContent) };
  });
  assert.deepEqual(out.dom, ['지식 관리', '데이터 분석', '그룹웨어', '업무 자동화']);
  assert.deepEqual(out.visual, ['그룹웨어', '지식 관리', '데이터 분석', '업무 자동화']);
});

// 실행 프레임(2026-09-30): 워크플로우 세그먼트의 하단 트리 = "작업을 병렬로 실행" + 현재 단계의 작업만(라이브 · 복원)
// Execution frame (2026-09-30): a workflow segment's bottom tree = "Running tasks in parallel" + only the current stage's tasks (live and restore)
const KX_CONSTS = ['AI365_KO2EN', 'AI365_SRC_REG', 'AI365_SRC_SEQ', 'AI365_RES_ICONS', 'AI365_RES_CHEV', 'AI365_AGX_TASK_IC', 'AI365_AGX_ARROW_IC',
  'AI365_AGX_BRANCH_IC', 'AI365_AGX_CHEV_IC', 'AI365_KX_PEND_IC', 'AI365_KX_FAIL_IC', 'AI365_KX_AGENT', 'AI365_KX_WEB_RE',
  'AI365_KX_LOCAL_RE', 'AI365_KX_WEB_IC', 'AI365_KX_DOCS', 'AI365_KX_STEP_IC'];
const KX_FUNCS = ['ai365T', 'ai365SrcRegister', 'ai365LocalBadgeHtml', 'ai365LocalFiles', 'ai365LocalDocAttrs', 'ai365LocalChipsHtml',
  'ai365HandleEvent', 'ai365KxAgentIcon', 'ai365KxEligible', 'ai365KxAddCards', 'ai365KxEn', 'ai365KxLineText', 'ai365KxCard', 'ai365KxAllLists',
  'ai365KxPush', 'ai365KxLine', 'ai365KxScopeCounts', 'ai365KxSubLabel', 'ai365KxFinalGroup', 'ai365KxGroupsFromNames', 'ai365KxBiPhrase',
  'ai365KxItemKind', 'ai365KxGroupsFromSources', 'ai365KxAllGroups', 'ai365KxThinkHtml', 'ai365KxLineHtml', 'ai365KxExtChips', 'ai365KxExploreBtn',
  'ai365KxTileLineHtml', 'ai365KxCardHtml', 'ai365KxWebHtml', 'ai365KxLocalHtml', 'ai365KxFrameHtml', 'ai365KxStagesHtml', 'ai365KxPaint',
  'ai365KxInit', 'ai365KxStatus', 'ai365KxStage', 'ai365KxAnswerHead', 'ai365KxSplitCards', 'ai365KxBiHtml', 'ai365KxDone',
  'ai365KxSettleGroups', 'ai365KxApplySources', 'ai365KxStaticEl', 'ai365KxDocList'];
test('workflow frames list only the current stage under "Running tasks in parallel", live and restored (object children read as labels)', async t => {
  const page = await browser.newPage();
  t.after(() => page.close());
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.setContent('<div id="chat"></div>');
  await page.addScriptTag({ content: `
    const chatInner = document.getElementById('chat');
    const FOOT = '<footer class="msg-foot"></footer>';
    const aiHead = () => '<header class="ai-head"></header>';
    const ai365Esc = s => { const el = document.createElement('span'); el.textContent = s == null ? '' : String(s); return el.innerHTML.replace(/"/g, '&quot;'); };
    const ai365CurrentLang = () => 'ko';
    const ai365MnMd = s => '<p>' + ai365Esc(s) + '</p>', ai365CardsHtml = () => '', ai365BiEmbHtml = () => '';
    const stickToBottom = () => {}, ai365ClearGen = () => {};
    const ai365AppendToken = (state, t) => { state.text = (state.text || '') + t; if (state.body) state.body.textContent = state.text; };
    ${KX_CONSTS.map(decl).join('\n')}
    ${KX_FUNCS.map(fn).join('\n')}
  ` });
  const out = await page.evaluate(() => {
    const stages = [{ no: 1, tasks: ['데이터 분석 · 매출 조회'] }, { no: 2, tasks: ['지식 관리 · 목표 확인', '그룹웨어 · 일정 확인'] }, { no: 3, tasks: ['웹 검색 · 동향'] }];
    const card = (id, label) => ({ id, label, children: [{ id: id + '-q', label: '3월 기준' }] });
    const wrap = document.createElement('div'); chatInner.appendChild(wrap);
    const state = { body: null, text: '', tree: false };
    const H = ev => ai365HandleEvent(ev, wrap, state);
    H({ type: 'task_tree', tasks: [card('knowledge', '지식 관리'), card('groupware', '그룹웨어')], parallel: true, stages, query: '3월 기준' });
    H({ type: 'stage_status', stage: 1, status: 'done' });
    H({ type: 'stage_status', stage: 2, status: 'running', cards: [card('knowledge', '지식 관리'), card('groupware', '그룹웨어')] });
    const tree = el => ({ head: el.querySelector('.ai365-agx-tkhd span').textContent, lines: Array.from(el.querySelectorAll('.ai365-agx-tkline span')).map(s => s.textContent),
      byStage: el.textContent.includes('작업을 단계별로 실행'), objects: el.textContent.includes('[object Object]') });
    const live = tree(wrap);
    const restored = ai365KxStaticEl({ id: 'm1', content: '답변', meta: { trace: { tasks: [card('knowledge', '지식 관리'), card('groupware', '그룹웨어')], stages, query: '',
      lines: [{ t: 'stage', stage: 1, status: 'done' }, { t: 'stage', stage: 2, status: 'running', cards: [card('knowledge', '지식 관리'), card('groupware', '그룹웨어')] }] } } });
    chatInner.appendChild(restored);
    const single = ai365KxStaticEl({ id: 'm2', content: '답변', meta: { trace: { tasks: [card('data', '데이터 분석')], stages: [stages[0]],
      lines: [{ t: 'stage', stage: 1, status: 'running', cards: [card('data', '데이터 분석')] }] } } });
    return { live, restored: tree(restored), single: tree(single), title: restored.querySelector('.ai365-kx-title') ? restored.querySelector('.ai365-kx-title').textContent : '',
      // 한 단계짜리도 타일 배치 — 생각 그룹 줄이 카드 안에 남는다(2026-09-30 리뷰) / one-stage flows use tiles too, keeping think-group lines in the card
      singleTile: !!single.querySelector('.ai365-kx-tile[data-kx-card="data"]'), tileLines: single.querySelectorAll('.ai365-kx-tile .ai365-kx-line.tile').length };
  });
  assert.deepEqual(errors, []);
  assert.deepEqual(out.live, { head: '작업을 병렬로 실행', lines: ['지식 관리 · 목표 확인', '그룹웨어 · 일정 확인'], byStage: false, objects: false });
  assert.deepEqual(out.restored, { head: '작업을 병렬로 실행', lines: ['지식 관리 · 목표 확인', '그룹웨어 · 일정 확인'], byStage: false, objects: false });
  assert.deepEqual(out.single, { head: '작업을 병렬로 실행', lines: ['데이터 분석 · 매출 조회'], byStage: false, objects: false });   // single-stage flows too
  assert.equal(out.title, '3월 기준');   // the shared card title from {id, label} children
  assert.equal(out.singleTile, true);
  assert.ok(out.tileLines >= 1, 'think-group lines inside the one-stage tile');
});

test('EN dictionary: the new workflow strings have unique English values and the new UI code has no em dash', () => {
  const en = dict();
  const want = {
    '이미지 및 파일 업로드': 'Upload images and files', '준비 중입니다': 'Not available yet', '워크플로우 검색': 'Search workflows',
    '워크플로우 미리보기': 'Workflow preview', '이 워크플로우 선택': 'Use this workflow', '실행할 수 있는 워크플로우가 없습니다': 'No workflows available to run',
    '일치하는 워크플로우가 없습니다': 'No matching workflows', 'Excel 파일': 'Excel file', '영상': 'Video', '이미지': 'Image',
    '워크플로우 제거': 'Remove workflow', '다음 단계': 'Next stage', '수정할 내용을 입력하세요': 'Enter the changes you want', '중단': 'Stop',
    '파일을 만들고 있습니다': 'Creating the file', '파일을 만들지 못했습니다': 'Could not create the file',
  };
  Object.entries(want).forEach(([k, v]) => {
    assert.equal(en[k], v, k);
    assert.deepEqual(Object.keys(en).filter(x => en[x] === v), [k], 'unique EN value for ' + k);
  });
  // 새 화면 코드의 문자열 리터럴에 em dash 가 없다 / no em dash inside the string literals of the new UI code
  const names = ['ai365WfPickerListHtml', 'ai365WfPickerPreviewHtml', 'ai365WfChipInner', 'ai365WfChipPaint', 'ai365WfBubbleChipHtml', 'ai365FlowTx',
    'ai365FlowBarHtml', 'ai365FlowGateHtml', 'ai365FlowQuestionDoneHtml', 'ai365FlowReviseRowHtml', 'ai365FlowOldGroupEl', 'ai365FlowFileHtml',
    'ai365FlowFileDownload', 'ai365FlowEnd'];
  const code = names.map(fn).join('\n') + iife('ai365WfMenu') + iife('ai365WfStyle');
  const literals = [...code.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '').matchAll(/'([^'\\\n]*(?:\\.[^'\\\n]*)*)'/g)].map(m => m[1]);
  assert.ok(literals.length > 50, 'literals found');
  literals.forEach(s => assert.ok(!s.includes('—'), s));
  // 이 코드가 ai365T 로 부르는 한국어 문구는 모두 사전에 있다 / every Korean string this code passes to ai365T is in the dictionary
  const called = [...code.matchAll(/ai365T\('([^']+)'\)/g)].map(m => m[1]).filter(s => /[가-힣]/.test(s));
  assert.ok(called.length >= 10, 'ai365T calls found');
  called.forEach(s => assert.ok(s in en, 'EN key for ' + s));
});
