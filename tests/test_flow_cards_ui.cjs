// Run with Playwright available on NODE_PATH: node --test tests/test_flow_cards_ui.cjs
// 워크플로우 채팅 카드 · 진행 표시줄 · 단계 파일 카드 · 복원(2026-09-11, 2026-09-30 개편). 어댑터의 실제 함수를 잘라 격리 브라우저에서
// 돌린다. 앱 DB · LLM · 메일 호출 없음(fetch 는 스텁).
// Workflow chat cards, progress bar, stage file card and restore (2026-09-11, redesigned 2026-09-30). Real adapter functions
// sliced from source and run in an isolated browser; no application DB, LLM or mail calls (fetch is stubbed).
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const source = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8').replace(/\r\n/g, '\n');

// Same convention as test_clarify_ui.cjs's fn(), extended with a single-line-function special case:
// a function whose whole body sits on its signature line (e.g. `function ai365FlowKey() { ... }`) never
// reaches a bare column-0 `\n}`, so the plain "search for the next \n}" scan would run past it into
// unrelated later code. Detected by checking whether the signature line itself already ends with `}`
// (an `opts = {}` default parameter ends its line with `{` instead, so it is not mistaken for one).
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
// 위임 리스너 — 짧은 고유 내부 문자열로 찾아 여는 줄부터 '\n});' 까지 / a delegated listener found by a unique interior string
function listener(anchor, opener) {
  const a = source.indexOf(anchor);
  assert.ok(a >= 0, 'anchor: ' + anchor);
  const s = source.lastIndexOf(opener, a);
  assert.ok(s >= 0, 'opener: ' + opener);
  return source.slice(s, source.indexOf('\n});', a) + 4);
}

const FLOW = ['ai365WfActing', 'ai365FlowKey', 'ai365FlowAlive', 'ai365FlowRunStart', 'ai365FlowRunUpdate', 'ai365FlowRunEnsure', 'ai365FlowRunEnd',
  'ai365FlowPersist', 'ai365FlowEnd', 'ai365FlowLocked', 'ai365FlowLock', 'ai365FlowStageLabel', 'ai365FlowTx', 'ai365FlowBarHtml',
  'ai365FlowRenderBar', 'ai365FlowHandle', 'ai365FlowExpireCards', 'ai365FlowCardMount', 'ai365FlowQuestionHtml', 'ai365FlowAnswerValues',
  'ai365FlowQuestionDoneHtml', 'ai365FlowNextItems', 'ai365FlowGateHtml', 'ai365FlowRenderQuestion', 'ai365FlowRenderGate',
  'ai365FlowQuestionValidate', 'ai365FlowUserBubble', 'ai365FlowResumeStream', 'ai365FlowOldGroupEl', 'ai365FlowCollapse',
  'ai365FlowStageBlocks', 'ai365FlowReviseRowHtml', 'ai365FlowReviseRestoreHtml', 'ai365FlowRestoreCard', 'ai365FlowTraceStage',
  'ai365FlowRestorePlan', 'ai365FlowRestorePost', 'ai365FlowFileSize', 'ai365FlowFileHtml', 'ai365FlowFileInit', 'ai365FlowFileMeta',
  'ai365FlowFilePage', 'ai365FlowFileDone', 'ai365FlowFileFail', 'ai365FlowFileStaticEl', 'ai365FlowFileDownload',
  'ai365HandleEvent', 'ai365SelectionSnapshot', 'ai365StreamReply', 'ai365StallSeconds', 'ai365StallMake', 'ai365RunStopServer', 'ai365StopStream',
  'ai365Fetch', 'ai365T', 'ai365AppendAssistant', 'ai365RestoreMessages', 'ai365WfChipInner', 'ai365WfBubbleChipHtml', 'ai365WfBubbleChip'];

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

async function fixture(t) {
  const page = await browser.newPage();
  t.after(() => page.close());
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  t.after(() => assert.deepEqual(errors, []));
  await page.setContent(
    '<div id="viewChat" class="view active"><div id="chatScroll"><div id="chat"></div></div>'
    + '<div class="composer-wrap"><div class="composer"><input id="chatInput" placeholder="원래 안내문구">'
    + '<button id="chatAttBtn" type="button"></button><button id="scopeBtn" type="button"></button><button id="chatSendBtn" type="button"></button>'
    + '</div></div></div>');
  await page.addScriptTag({ content: `
    const chatInner = document.getElementById('chat'), chatScroll = document.getElementById('chatScroll');
    let currentChatId = 'c', chats = [{id: 'c', run_state: 'needs_input'}];
    let ai365StreamRun = null, ai365StreamWrap = null, ai365StreamState = null, ai365Abort = null;
    let AI365_ATTACH_PENDING = null;
    let AI365_FLOW_RUN = null, AI365_FLOW_LAST = null;
    let replyActive = false;
    const AI365_STALL_MS = 20000;
    const AI365_BACKEND_IDS = new Set(['c']), AI365_JSON_HEADERS = {}, FOOT = '<footer class="msg-foot"></footer>';
    ${decl('AI365_KO2EN')}
    ${decl('AI365_DOC_ILTR')}
    ${decl('AI365_DOC_DATA')}
    ${decl('AI365_FLOW_FILE_FMT')}
    ${decl('AI365_WF_ICON')}
    const ai365Esc = s => { const el = document.createElement('span'); el.textContent = s == null ? '' : String(s); return el.innerHTML.replace(/"/g, '&quot;'); };
    const aiHead = () => '<header class="ai-head">사내</header>';
    const ai365MnMd = s => '<p>' + ai365Esc(s) + '</p>';
    const ai365CurrentLang = () => window.__lang || 'ko';
    const ai365CurrentScope = () => '사내', ai365SelectedAgents = () => [];
    const AI365_VALID_AGENTS = ['knowledge', 'data', 'groupware', 'work'];
    const ai365SourceHtml = () => '사내', ai365SourcesBlockHtml = () => '', ai365CardsHtml = () => '', ai365SourceFromString = () => '사내';
    const stickToBottom = () => {}, renderChatLists = () => {}, ai365RunMarkSeen = () => {};
    const ai365SetSending = v => { window.sending = v; };
    const ai365ClearGen = () => {};
    const ai365RenderError = (wrap) => { wrap.insertAdjacentHTML('beforeend', '<div class="err"></div>'); };
    const ai365RenderTaskTree = (wrap) => { wrap.insertAdjacentHTML('beforeend', '<div class="task-tree"></div>'); };
    const ai365RenderConfirm = (wrap) => { wrap.innerHTML = '<div class="ai365-confirm"></div>'; };
    const ai365AppendToken = (state, t) => { state.text = (state.text || '') + t; if (state.body) state.body.textContent = state.text; };
    const ai365AttachChip = () => {};
    const appendUserMessage = text => {
      const w = document.createElement('div'); w.className = 'msg msg-user appear';
      const b = document.createElement('div'); b.className = 'user-bubble'; b.textContent = text;
      w.appendChild(b); chatInner.appendChild(w);
    };
    const toast = m => { window.toasts = (window.toasts || []).concat([m]); };
    const ai365OrigSimulateAiReply = () => {};
    ${FLOW.map(fn).join('\n')}
    ${listener("e.target.closest('.form-card[data-form=\"ai365-flow-q\"]')", "chatInner.addEventListener('input',")}
    ${listener("e.target.closest('[data-flow-q-submit]')", "chatInner.addEventListener('click',")}
    ${listener("e.target.closest('[data-flow-oldtoggle]')", "chatInner.addEventListener('click',")}
    ${listener("e.target.closest('[data-ai365-flowfile-dl]')", "chatInner.addEventListener('click',")}
    ${listener("e.target.closest('[data-ai365-flow-stop]')", "document.addEventListener('click',")}
  ` });
  return page;
}

// fetch 스텁 — 호출을 모으고 스트림은 'done' 한 줄로 끝낸다(SSE 가 아닌 요청은 빈 JSON)
// A fetch stub that captures every call; streams end with a single 'done' event (non-SSE calls get empty JSON)
const CAPTURE_FETCH = `
  window.fetches = [];
  window.fetch = async (url, init) => {
    window.fetches.push({ url, method: (init && init.method) || 'GET', body: init && init.body ? JSON.parse(init.body) : null });
    if (/\\/api\\/flows\\/(resume|run)$/.test(url)) return new Response('data: ' + JSON.stringify({ type: 'done' }) + '\\n\\n');
    return new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } });
  };
`;
const GATE = {
  run_id: 'run_g1', stage: 1, next_stage: 2, flow_name: '월간 영업 브리핑', total_stages: 3,
  summary: '1단계 결과 요약입니다.',
  next_tasks: ['지식 관리 · 경영지표 문서에서 목표 확인', '그룹웨어 · 회의 일정 확인'],
  next_items: [{ agent: 'knowledge', label: '지식 관리', task: 'A사 경영지표.pdf · 경영지표 문서에서 목표 확인' }, { agent: 'groupware', label: '그룹웨어', task: '' }],
};

test('flow_question card renders every item with its question, required marker, hint/placeholder and choice options', async t => {
  const page = await fixture(t);
  const card = {
    run_id: 'run_q1', stage: 2,
    title: '추가 확인이 필요합니다',
    intro: '2단계 답변을 작성하기 전에 몇 가지 확인할게요.',
    items: [
      { id: 'q_text', label: '담당자', question: '담당자를 알려주세요', kind: 'text', required: true, placeholder: '예: 홍길동' },
      { id: 'q_hint', label: '기간', question: '조회 기간을 알려주세요', kind: 'text', required: false, hint: '예: 최근 1주' },
      { id: 'q_choice', label: '부서', question: '어느 부서인가요?', kind: 'choice', required: true, options: ['영업팀', '개발팀'] },
    ],
    submit_label: '답변 제출',
  };
  await page.evaluate(c => {
    const wrap = document.createElement('div');
    chatInner.appendChild(wrap);
    ai365FlowRenderQuestion(wrap, c, {});
  }, card);
  const formCard = page.locator('[data-form="ai365-flow-q"]');
  assert.equal(await formCard.getAttribute('data-run-id'), 'run_q1');
  assert.equal(await formCard.getAttribute('data-stage'), '2');
  assert.equal(await page.locator('.form-card-title').textContent(), '추가 확인이 필요합니다');
  assert.equal(await page.locator('.ai365-flow-q-hint').textContent(), '2단계 답변을 작성하기 전에 몇 가지 확인할게요.');
  const questions = page.locator('.form-q');
  assert.equal(await questions.count(), 3);
  assert.equal((await questions.nth(0).textContent()).trim(), '담당자를 알려주세요 *');   // required marker
  assert.equal((await questions.nth(1).textContent()).trim(), '조회 기간을 알려주세요');   // no marker
  assert.equal((await questions.nth(2).textContent()).trim(), '어느 부서인가요? *');
  assert.equal(await page.locator('[data-flow-q="q_text"]').getAttribute('placeholder'), '예: 홍길동');
  assert.equal(await page.locator('[data-flow-q="q_hint"]').getAttribute('placeholder'), '예: 최근 1주');   // falls back to hint
  const group = page.locator('[data-group="q_choice"]');
  assert.equal(await group.getAttribute('data-type'), 'single');
  const options = group.locator('.option-row');
  assert.deepEqual(await options.allTextContents(), ['영업팀', '개발팀']);
  assert.equal(await options.nth(0).getAttribute('data-value'), '영업팀');
  // Two required items (text + choice) are still unanswered — submit stays disabled.
  assert.equal(await page.locator('[data-flow-q-submit]').isDisabled(), true);
});

// 2026-09-30: 제출하면 말풍선 없이 안내 문구 + 회색 한 줄 "✓ N단계 실행 · 값 · 값" 으로 접힌다
// 2026-09-30: a submit collapses the card to its intro plus one grey row "✓ Run stage N · value · value", no bubble
test('submitting a flow_question card waits for required items, resumes the run and collapses to the intro plus an answer row', async t => {
  const page = await fixture(t);
  const card = { run_id: 'run_q2', stage: 2, intro: '2단계 답변을 작성하기 전에 몇 가지 확인할게요.',
    items: [{ id: 'name', question: '이름을 알려주세요', kind: 'text', required: true },
      { id: 'team', question: '팀을 골라 주세요', kind: 'choice', required: false, options: ['영업팀', '개발팀'] }] };
  await page.addScriptTag({ content: CAPTURE_FETCH });
  await page.evaluate(c => {
    const wrap = document.createElement('div');
    chatInner.appendChild(wrap);
    ai365FlowRenderQuestion(wrap, c, {});
  }, card);
  const submit = page.locator('[data-flow-q-submit]');
  assert.equal(await submit.isDisabled(), true);   // required item still empty
  await page.locator('[data-flow-q="name"]').fill('홍길동');
  assert.equal(await submit.isEnabled(), true);
  await page.evaluate(() => document.querySelector('.option-row[data-value="영업팀"]').classList.add('selected'));
  await submit.click();
  await page.waitForFunction(() => window.fetches && window.fetches.length === 1);
  assert.deepEqual(await page.evaluate(() => ({ url: window.fetches[0].url, body: window.fetches[0].body })), {
    url: '/api/flows/resume',
    body: { run_id: 'run_q2', chat_id: 'c', reply: { kind: 'flow_question', answers: { name: '홍길동', team: '영업팀' } }, acting_user_id: '' },
  });
  assert.equal(await page.locator('[data-form="ai365-flow-q"]').count(), 0);   // the card is gone
  assert.equal(await page.locator('.ai365-flow-q-intro').textContent(), '2단계 답변을 작성하기 전에 몇 가지 확인할게요.');
  assert.equal((await page.locator('.ai365-flow-okrow').textContent()).trim(), '2단계 실행 · 홍길동 · 영업팀');
  assert.equal(await page.locator('.ai365-flow-okrow svg').count(), 1);   // check icon
  assert.equal(await page.locator('.msg-user').count(), 0);   // no echo bubble
});

// 2026-09-30 단계 완료 카드: 머리 ① N단계 완료 · "다음 단계" 줄(next_items, 없으면 next_tasks 풀기) · 입력칸 · [N단계 수정 요청] [N+1단계 실행]. 요약 상자 · 취소 없음
// 2026-09-30 stage-complete card: header ① Stage N done, "Next stage" rows (next_items, else parsed next_tasks), the input and
// [Request changes to stage N] [Run stage N+1]; no summary box, no cancel
test('stage-complete card follows the mockup: numbered header, next-stage rows, note input, revise and run buttons', async t => {
  const page = await fixture(t);
  const read = () => page.evaluate(() => ({
    no: document.querySelector('.ai365-flow-gate-no').textContent,
    title: document.querySelector('.ai365-flow-gate .form-card-title').textContent,
    label: (document.querySelector('.ai365-flow-gate-lb') || {}).textContent || '',
    rows: Array.from(document.querySelectorAll('.ai365-flow-gate-row')).map(r => [r.querySelector('.ai365-flow-gate-ag').textContent, r.querySelector('.ai365-flow-gate-tk').textContent]),
    placeholder: document.querySelector('[data-flow-gate-note]').getAttribute('placeholder'),
    maxlength: document.querySelector('[data-flow-gate-note]').getAttribute('maxlength'),
    revise: document.querySelector('[data-flow-gate-revise]').textContent,
    run: document.querySelector('[data-flow-gate-run]').textContent,
    cancel: document.querySelectorAll('[data-flow-gate-cancel]').length,
    summary: document.querySelectorAll('.ai365-flow-gate-sum').length,
    stage: document.querySelector('.ai365-flow-gate').dataset.stage,
    next: document.querySelector('.ai365-flow-gate').dataset.nextStage,
  }));
  await page.evaluate(c => { chatInner.innerHTML = ai365FlowGateHtml(c); }, GATE);
  assert.deepEqual(await read(), {
    no: '1', title: '1단계 완료', label: '다음 단계',
    rows: [['지식 관리', 'A사 경영지표.pdf · 경영지표 문서에서 목표 확인'], ['그룹웨어', '']],
    placeholder: '2단계 실행 시 추가로 반영할 내용을 입력하세요 (선택)', maxlength: '500',
    revise: '1단계 수정 요청', run: '2단계 실행', cancel: 0, summary: 0, stage: '1', next: '2',
  });
  // 옛 카드(next_items 없음)는 next_tasks 를 첫 ' · ' 에서 나눈다 / older cards split next_tasks at the first ' · '
  await page.evaluate(c => { chatInner.innerHTML = ai365FlowGateHtml(Object.assign({}, c, { next_items: [] })); }, GATE);
  assert.deepEqual((await read()).rows, [['지식 관리', '경영지표 문서에서 목표 확인'], ['그룹웨어', '회의 일정 확인']]);
  // 영어 / English
  await page.evaluate(c => { window.__lang = 'en'; chatInner.innerHTML = ai365FlowGateHtml(c); }, GATE);
  const en = await read();
  assert.deepEqual([en.title, en.label, en.placeholder, en.revise, en.run, en.rows[0][0]],
    ['Stage 1 done', 'Next stage', 'Anything to add when running stage 2 (optional)', 'Request changes to stage 1', 'Run stage 2', 'Knowledge']);
});

test('running the next stage removes the card (and its card-only bubble), adds the stage-run bubble and resumes with the note', async t => {
  const page = await fixture(t);
  await page.addScriptTag({ content: CAPTURE_FETCH });
  await page.evaluate(c => {
    // 단계 파일 뒤 별도 세그먼트로 온 카드(말풍선 = 머리 + 카드) / a card that came as its own segment after a file (bubble = head + card)
    const wrap = document.createElement('div');
    wrap.className = 'msg msg-ai';
    chatInner.appendChild(wrap);
    ai365FlowRenderGate(wrap, c, {});
  }, GATE);
  await page.locator('[data-flow-gate-note]').fill('서울 창고만');
  await page.locator('[data-flow-gate-run]').click();
  await page.waitForFunction(() => window.fetches && window.fetches.length === 1);
  assert.deepEqual(await page.evaluate(() => ({ url: window.fetches[0].url, body: window.fetches[0].body })), {
    url: '/api/flows/resume',
    body: { run_id: 'run_g1', chat_id: 'c', reply: { kind: 'flow_gate', action: 'run', note: '서울 창고만' }, acting_user_id: '' },
  });
  assert.equal(await page.locator('.ai365-flow-gate').count(), 0);
  assert.deepEqual(await page.locator('.msg-user .user-bubble').allTextContents(), ['2단계 실행: 서울 창고만']);   // same as the stored row
  // 카드만 있던 말풍선은 사라지고 재개 스트림의 새 말풍선만 남는다 / the card-only bubble is gone; only the resume stream's new wrap remains
  assert.equal(await page.locator('#chat > .msg-ai').count(), 1);
  assert.equal(await page.locator('#chat .ai-head').count(), 0);
});

test('revise needs text; then the stage answer and file fold into "previous result", a revision row is added and the run resumes with revise', async t => {
  const page = await fixture(t);
  await page.addScriptTag({ content: CAPTURE_FETCH });
  await page.evaluate(c => {
    chatInner.innerHTML = '<div class="msg msg-user"><div class="user-bubble">1단계 실행</div></div>'
      + '<div class="msg msg-ai appear" data-flow-stage="1" data-flow-answer><div class="ai-body">첫 답변</div></div>'
      + '<div class="msg msg-ai" data-flow-stage="1" data-flow-file><div class="ai365-flow-file"></div></div>';
    const wrap = document.createElement('div');
    wrap.className = 'msg msg-ai';
    wrap.setAttribute('data-flow-stage', '1');
    chatInner.appendChild(wrap);
    ai365FlowRenderGate(wrap, c, {});
  }, GATE);
  // 빈 입력 — 안내만, 전송 없음 / empty: the hint only, nothing sent
  await page.locator('[data-flow-gate-revise]').click();
  assert.equal(await page.locator('.ai365-flow-gate-hint').textContent(), '수정할 내용을 입력하세요');
  assert.equal(await page.evaluate(() => document.activeElement && document.activeElement.hasAttribute('data-flow-gate-note')), true);
  assert.equal(await page.evaluate(() => (window.fetches || []).length), 0);
  await page.locator('[data-flow-gate-note]').fill('서울만 표로');
  await page.locator('[data-flow-gate-revise]').click();
  await page.waitForFunction(() => window.fetches && window.fetches.length === 1);
  assert.deepEqual(await page.evaluate(() => window.fetches[0].body.reply), { kind: 'flow_gate', action: 'revise', note: '서울만 표로' });
  const out = await page.evaluate(() => ({
    order: Array.from(chatInner.children).map(n => n.className.split(' ').filter(c => /msg-user|oldgrp|revrow|msg-ai/.test(c)).join(' ')),
    row: document.querySelector('.ai365-flow-oldrow').textContent.trim(),
    folded: Array.from(document.querySelectorAll('.ai365-flow-oldbody > *')).map(n => n.textContent),
    appear: document.querySelectorAll('.ai365-flow-oldbody .appear').length,
    open: document.querySelector('.ai365-flow-oldgrp').classList.contains('open'),
    rev: document.querySelector('.ai365-flow-revrow').textContent.trim(),
    gates: document.querySelectorAll('.ai365-flow-gate').length,
    bubbles: document.querySelectorAll('.msg-user').length,
  }));
  assert.deepEqual(out.order, ['msg-user', 'ai365-flow-oldgrp', 'ai365-flow-revrow', 'msg-ai']);   // bubble, group, revision row, resume wrap
  assert.equal(out.row, '1단계 이전 결과');
  assert.deepEqual(out.folded, ['첫 답변', '']);
  assert.equal(out.appear, 0);   // no replayed entrance animation inside the group
  assert.equal(out.open, false);   // folded until clicked
  assert.equal(out.rev, '1단계 수정 요청: 서울만 표로');
  assert.equal(out.gates, 0);
  assert.equal(out.bubbles, 1);   // no extra bubble for a revision
  await page.locator('[data-flow-oldtoggle]').click();
  assert.equal(await page.locator('.ai365-flow-oldgrp').getAttribute('class'), 'ai365-flow-oldgrp open');
  assert.equal(await page.locator('[data-flow-oldtoggle]').getAttribute('aria-expanded'), 'true');
});

// 2026-09-30 진행 표시줄: 실행 중에는 컴포저를 숨기고 그 자리에 이름 · 단계 점 · "N단계 중 k단계" · [중단]
// 2026-09-30 progress bar: while running the composer hides and the bar shows name, stage dots, "stage k of N" and [Stop]
test('progress bar replaces the composer with name, dots and stage text, follows updates and goes away at the end', async t => {
  const page = await fixture(t);
  const read = () => page.evaluate(() => {
    const bar = document.getElementById('ai365FlowBar');
    return {
      bar: !!bar,
      composer: document.querySelector('.composer').classList.contains('ai365-flow-hide') ? 'hidden' : 'shown',
      name: bar ? bar.querySelector('.ai365-flow-bar-nm').textContent : '',
      dots: bar ? Array.from(bar.querySelectorAll('.ai365-flow-bar-dots i')).map(i => i.className) : [],
      st: bar ? bar.querySelector('.ai365-flow-bar-st').textContent : '',
      stop: bar ? bar.querySelector('[data-ai365-flow-stop]').textContent : '',
      locked: ai365FlowLocked(),
      before: bar ? bar.nextElementSibling === document.querySelector('.composer') : false,
    };
  });
  await page.evaluate(() => ai365FlowRunStart({ chat: 'c', name: '월간 영업 브리핑', total: 3, stage: 1 }));
  assert.deepEqual(await read(), { bar: true, composer: 'hidden', name: '월간 영업 브리핑', dots: ['cur', 'todo', 'todo'],
    st: '3단계 중 1단계', stop: '중단', locked: true, before: true });
  await page.evaluate(() => ai365FlowRunUpdate({ stage: 2, name: '', total: 0 }));   // empty values never overwrite
  assert.deepEqual((await read()).dots, ['done', 'cur', 'todo']);
  assert.equal((await read()).st, '3단계 중 2단계');
  await page.evaluate(() => { window.__lang = 'en'; ai365FlowRenderBar(); });
  assert.deepEqual([(await read()).st, (await read()).stop], ['Stage 2 of 3', 'Stop']);
  await page.evaluate(() => { window.__lang = 'ko'; ai365FlowRunEnd(); });
  assert.deepEqual(await read(), { bar: false, composer: 'shown', name: '', dots: [], st: '', stop: '', locked: false, before: false });
  // 다른 채팅의 실행은 이 채팅에 표시줄을 띄우지 않는다 / another chat's run shows no bar here
  await page.evaluate(() => { AI365_FLOW_RUN = { chat: 'other', name: 'x', total: 2, stage: 1 }; ai365FlowRenderBar(); });
  assert.equal((await read()).bar, false);
  // 옛 잠금 API 도 같은 표시줄을 켜고 끈다 / the old lock API toggles the same bar
  await page.evaluate(() => ai365FlowLock(true));
  assert.equal((await read()).bar, true);
  await page.evaluate(() => ai365FlowLock(false));
  assert.equal((await read()).bar, false);
});

// 화면 전환마다 표시줄을 지금 채팅 기준으로 다시 맞춘다(새 채팅 · 홈에서 다른 채팅의 표시줄이 남지 않게)
// Every view switch re-syncs the bar with the current chat (another chat's bar never lingers on a new chat or home)
test('a view switch re-syncs the bar: a new chat screen shows no stale bar from the previous chat', async t => {
  const page = await fixture(t);
  const a = source.indexOf('const ai365FlowPrevShowView = window.showView;');
  assert.ok(a >= 0, 'showView re-sync wrapper');
  const s = source.lastIndexOf("if (typeof window.showView === 'function') {", a);
  await page.addScriptTag({ content: 'window.showView = function () {};\n' + source.slice(s, source.indexOf('\n}', a) + 2) });
  const out = await page.evaluate(() => {
    ai365FlowRunStart({ chat: 'c', name: '주간 브리핑', total: 2, stage: 1 });
    const before = !!document.getElementById('ai365FlowBar');
    currentChatId = null;   // openBlankChat: a new chat is on screen
    window.showView('chat');
    const afterNew = [!!document.getElementById('ai365FlowBar'), document.querySelector('.composer').classList.contains('ai365-flow-hide')];
    currentChatId = 'c';    // back to the running chat (the restore re-raises the bar; the state is still there)
    window.showView('chat');
    return { before, afterNew, back: !!document.getElementById('ai365FlowBar') };
  });
  assert.deepEqual(out, { before: true, afterNew: [false, false], back: true });
});

test('[Stop] while waiting cancels the run with PATCH flow_id, expires the waiting card and brings the composer back', async t => {
  const page = await fixture(t);
  await page.addScriptTag({ content: CAPTURE_FETCH });
  await page.evaluate(c => {
    const wrap = document.createElement('div'); chatInner.appendChild(wrap);
    ai365FlowRenderGate(wrap, c, {});
    ai365FlowRunStart({ chat: 'c', name: '월간 영업 브리핑', total: 3, stage: 1 });
  }, GATE);
  await page.locator('[data-ai365-flow-stop]').click();
  await page.waitForFunction(() => window.fetches && window.fetches.length === 1);
  assert.deepEqual(await page.evaluate(() => window.fetches[0]), { url: '/api/chats/c', method: 'PATCH', body: { flow_id: '', flow_name: '' } });
  assert.equal(await page.locator('#ai365FlowBar').count(), 0);
  assert.equal(await page.locator('.ai365-flow-gate .form-submitted-label').textContent(), '취소됨');
  assert.deepEqual(await page.evaluate(() => window.toasts), ['워크플로우 실행을 중단했습니다.']);
});

test('[Stop] while streaming stops the server run first, then cancels it', async t => {
  const page = await fixture(t);
  await page.evaluate(() => {
    window.calls = [];
    window.fetch = async (url, init) => {
      window.calls.push((init && init.method || 'GET') + ' ' + url);
      if (/\/stop$/.test(url)) { await new Promise(r => setTimeout(r, 30)); return new Response('{"ok":true}', { status: 200 }); }
      return new Response('{}', { status: 200 });
    };
    ai365FlowRunStart({ chat: 'c', name: 'x', total: 2, stage: 1 });
    ai365Abort = new AbortController();
    ai365StreamRun = { chatId: 'c', kind: 'chat' };
    ai365StreamWrap = document.createElement('div');
    ai365StreamState = {};
  });
  await page.locator('[data-ai365-flow-stop]').click();
  await page.waitForFunction(() => window.calls.length === 2);
  assert.deepEqual(await page.evaluate(() => window.calls), ['POST /api/chats/c/stop', 'PATCH /api/chats/c']);
  assert.equal(await page.evaluate(() => ai365Abort), null);
  assert.equal(await page.locator('#ai365FlowBar').count(), 0);
});

test('stream events drive the bar: staged tree raises it, stage_status and cards update it, terminal states, send confirm and errors drop it', async t => {
  const page = await fixture(t);
  const out = await page.evaluate(() => {
    const snap = () => AI365_FLOW_RUN ? Object.assign({}, AI365_FLOW_RUN) : null;
    const wrap = document.createElement('div'); chatInner.appendChild(wrap);
    const state = { body: null, text: '', tree: false };
    const H = ev => ai365HandleEvent(ev, wrap, state);
    const r = {};
    AI365_FLOW_LAST = { chat: 'c', name: '복원된 이름', total: 3 };   // 복원이 본 칩 / the chip the restore saw
    H({ type: 'execution_result', state: 'running', run_id: 'run7' });
    r.beforeTree = snap();   // execution_result alone never creates the bar (document runs send it too)
    H({ type: 'task_tree', tasks: [], parallel: true, stages: [{ no: 1, tasks: [] }, { no: 2, tasks: [] }, { no: 3, tasks: [] }] });
    r.afterTree = snap();
    H({ type: 'stage_status', stage: 1, status: 'done' });   // replayed done is ignored
    H({ type: 'stage_status', stage: 2, status: 'running', cards: [] });
    r.afterStage = snap();
    r.tag = wrap.getAttribute('data-flow-stage');
    H({ type: 'flow_gate', card: { run_id: 'run7', stage: 2, next_stage: 3, flow_name: '월간 영업 브리핑', total_stages: 3 } });
    r.afterGate = snap();
    H({ type: 'execution_result', state: 'needs_input', run_id: 'run7' });
    r.waiting = !!document.getElementById('ai365FlowBar');
    H({ type: 'execution_result', state: 'completed', run_id: 'run7' });
    r.completed = snap();
    ai365FlowRunStart({ chat: 'c', name: 'n', total: 2 });
    H({ type: 'confirm', action_id: 'a1', summary: '보낼까요?' });
    r.confirm = snap();
    ai365FlowRunStart({ chat: 'c', name: 'n', total: 2 });
    H({ type: 'error', detail: 'x' });
    r.error = snap();
    return r;
  });
  assert.equal(out.beforeTree, null);
  assert.deepEqual(out.afterTree, { chat: 'c', name: '복원된 이름', total: 3, stage: 1, runId: 'run7', flowId: '', actor: '' });
  assert.equal(out.afterStage.stage, 2);
  assert.equal(out.tag, '2');
  assert.deepEqual([out.afterGate.name, out.afterGate.total, out.afterGate.stage], ['월간 영업 브리핑', 3, 2]);
  assert.equal(out.waiting, true);
  assert.equal(out.completed, null);
  assert.equal(out.confirm, null);
  assert.equal(out.error, null);
});

// 2026-09-30 리뷰: 탐색 미니채팅 스트림의 이벤트(실행 결과 · 오류 · 발송 확인)는 본 채팅의 워크플로우 진행 표시줄을 건드리지 않는다
// 2026-09-30 review: explore mini-chat stream events (execution result, error, send confirm) never touch the main chat's workflow bar
test('explore mini-chat stream events leave the workflow bar and its run id alone', async t => {
  const page = await fixture(t);
  const out = await page.evaluate(() => {
    ai365FlowRunStart({ chat: 'c', name: '주간 브리핑', total: 3, stage: 2, runId: 'run_main' });
    const wrap = document.createElement('div'); chatInner.appendChild(wrap);
    const state = { body: null, text: '', tree: false, explore: true };
    ['running', 'completed'].forEach(s => ai365HandleEvent({ type: 'execution_result', state: s, run_id: 'run_explore' }, wrap, state));
    ai365HandleEvent({ type: 'answer_head', source: '워크플로우|다른 이름' }, wrap, state);
    ai365HandleEvent({ type: 'error', detail: 'x' }, wrap, state);
    return { run: AI365_FLOW_RUN && [AI365_FLOW_RUN.runId, AI365_FLOW_RUN.name], bar: !!document.getElementById('ai365FlowBar') };
  });
  assert.deepEqual(out, { run: ['run_main', '주간 브리핑'], bar: true });
});

// 2026-09-30 리뷰: AI365_applyEffective 는 리소스 센터 동기화 · 부팅에서도 불린다 — 신원이 바뀐 때만 실행을 끝낸다(PATCH), 같으면 그대로
// 2026-09-30 review: AI365_applyEffective also runs on Resource Center syncs and at boot; only a real identity change ends the run (PATCH)
test('the view-as hook ends a waiting run only when the acting user really changed', async t => {
  const page = await fixture(t);
  const a = source.indexOf('AI365_FLP_PREV_CACHE = {};   // 뷰애즈 전환');
  assert.ok(a >= 0, 'view-as hook');
  const s = source.lastIndexOf('(function () {', a);
  await page.addScriptTag({ content: 'let AI365_FLP_PREV_CACHE = {}, AI365_FLOW_LAUNCH = null;\nwindow.AI365_applyEffective = function () {};\n'
    + source.slice(s, source.indexOf('\n})();', a) + 6) });
  await page.addScriptTag({ content: CAPTURE_FETCH });
  const out = await page.evaluate(async () => {
    ai365FlowRunStart({ chat: 'c', name: '주간 브리핑', total: 3, stage: 1 });
    window.AI365_applyEffective();   // 리소스 동기화 · 부팅 — 같은 신원 / resource sync or boot, same identity
    const same = { run: !!AI365_FLOW_RUN, fetches: window.fetches.length };
    window.AI365_ACTING_USER = { no: 12 };   // 뷰애즈 전환 / view-as switch
    window.AI365_applyEffective();
    await new Promise(r => setTimeout(r, 30));
    return { same, run: !!AI365_FLOW_RUN, fetches: window.fetches.map(f => f.method + ' ' + f.url + ' ' + JSON.stringify(f.body)) };
  });
  assert.deepEqual(out.same, { run: true, fetches: 0 });
  assert.equal(out.run, false);
  assert.deepEqual(out.fetches, ['PATCH /api/chats/c {"flow_id":"","flow_name":""}']);
});

test('restore shows cards the server closed without a user reply as "취소됨"', async t => {
  const page = await fixture(t);
  const gate = { run_id: 'r5', stage: 1, next_stage: 2, next_items: [{ agent: 'web', label: '웹 검색', task: '동향' }] };
  const question = { run_id: 'r6', stage: 1, intro: '1단계 답변을 작성하기 전에 몇 가지 확인할게요.', items: [{ id: 'q', question: '지점?', kind: 'text', required: true }] };
  await page.evaluate(({ gate, question }) => {
    window.fetch = async url => new Response(JSON.stringify([
      { id: 'u1', role: 'user', content: '질문', meta: { flow: { id: 'f', name: 'F', stages: 2 } } },
      { id: 'q1', role: 'assistant', content: '확인', meta: { kind: 'flow_question', card: question, resume_id: 'r6', answered: true } },
      { id: 'g1', role: 'assistant', content: '1단계 완료', meta: { kind: 'flow_gate', card: gate, resume_id: 'r5', answered: true } },
    ]), { status: 200 });
    ai365RestoreMessages('c');
  }, { gate, question });
  await page.waitForSelector('.ai365-flow-gate');
  const out = await page.evaluate(() => ({
    labels: Array.from(document.querySelectorAll('.form-submitted-label')).map(l => l.textContent),
    buttons: Array.from(document.querySelectorAll('.form-card button')).map(b => b.disabled),
    bar: !!document.getElementById('ai365FlowBar'),
  }));
  assert.deepEqual(out.labels, ['취소됨', '취소됨']);
  assert.ok(out.buttons.every(Boolean));
  assert.equal(out.bar, false);
});

// 2026-09-30 E2E: [중단] 뒤 같은 채팅에서 새 워크플로우를 시작하면 앞 실행의 닫힌 카드가 마지막 사용자 행보다 앞에 놓인다 — 그래도 응답한
// 카드가 아니므로 '취소됨'으로 남고, 응답 행(flow_step)이 뒤따르는 카드만 숨는다
// 2026-09-30 E2E: after [Stop], a new run in the same chat puts the earlier run's closed card before the last user row; it was never
// answered, so it stays as '취소됨', while a card followed by its reply row (flow_step) is still hidden
test('restore keeps a card closed by a later new run as "취소됨" and still hides a replied card', async t => {
  const page = await fixture(t);
  const stopped = { run_id: 'r7', stage: 1, next_stage: 2, next_items: [{ agent: 'data', label: '데이터 분석', task: '파이프라인 조회' }] };
  const replied = { run_id: 'r8', stage: 1, next_stage: 2, next_items: [] };
  const question = { run_id: 'r9', stage: 1, intro: '1단계 답변을 작성하기 전에 몇 가지 확인할게요.', items: [{ id: 'q', question: '지점?', kind: 'text', required: true }] };
  await page.evaluate(({ stopped, replied, question }) => {
    window.runLookups = [];
    window.fetch = async url => {
      if (String(url).indexOf('/api/flows/runs/') >= 0) { window.runLookups.push(String(url)); return new Response('{}', { status: 200 }); }
      return new Response(JSON.stringify([
        { id: 'u1', role: 'user', content: '질문', meta: { flow: { id: 'f', name: 'F', stages: 2 } } },
        { id: 'q1', role: 'assistant', content: '확인', meta: { kind: 'flow_question', card: question, resume_id: 'r9' } },
        { id: 'u2', role: 'user', content: '다시 질문', meta: { flow: { id: 'f', name: 'F', stages: 2 } } },
        { id: 'g1', role: 'assistant', content: '1단계 완료', meta: { kind: 'flow_gate', card: stopped, resume_id: 'r7', answered: true } },
        { id: 'u3', role: 'user', content: '또 질문', meta: { flow: { id: 'f', name: 'F', stages: 2 } } },
        { id: 'g2', role: 'assistant', content: '1단계 완료', meta: { kind: 'flow_gate', card: replied, resume_id: 'r8', answered: true } },
        { id: 'u4', role: 'user', content: '2단계 실행', meta: { flow_step: { stage: 1 } } },
      ]), { status: 200 });
    };
    ai365RestoreMessages('c');
  }, { stopped, replied, question });
  await page.waitForSelector('.ai365-flow-gate');
  const out = await page.evaluate(() => ({
    gates: document.querySelectorAll('.ai365-flow-gate').length,
    questions: document.querySelectorAll('.form-card[data-form="ai365-flow-q"]').length,
    labels: Array.from(document.querySelectorAll('.form-submitted-label')).map(l => l.textContent),
    buttons: Array.from(document.querySelectorAll('.form-card button')).map(b => b.disabled),
    lookups: window.runLookups.length,
  }));
  assert.equal(out.gates, 1);   // g1 만(응답한 g2 는 숨김) / only g1 (the replied g2 stays hidden)
  assert.equal(out.questions, 1);   // 답 없이 새 실행에 밀린 질문 카드도 남는다 / the unanswered question card stays too
  assert.deepEqual(out.labels, ['취소됨', '취소됨']);
  assert.ok(out.buttons.every(Boolean));
  assert.equal(out.lookups, 0);   // 닫힌 카드는 실행 상태를 다시 묻지 않는다 / closed cards never re-check the run
});

// 2026-09-30 단계 파일: 워크플로우 스트림의 파일 세그먼트 = 할 일 목록 · 분할 화면 대신 작은 카드(만드는 중 → 이름 · 종류 · 크기 · 다운로드)
// 2026-09-30 stage file: a workflow stream's file segment is a small card (loading → name, kind, size, download) instead of the todo list and split view
test('a workflow file segment renders the stage file card: loading, then name, kind, size and download, with no completion text', async t => {
  const page = await fixture(t);
  const out = await page.evaluate(async () => {
    const events = [
      { type: 'execution_result', state: 'running', run_id: 'run1' },
      { type: 'stage_status', stage: 1, status: 'running', cards: [] },
      { type: 'answer_head', source: '워크플로우|주간 브리핑' },
      { type: 'token', text: '1단계 답변' },
      { type: 'done', message_id: 'm1' },
      { type: 'segment_start', doc: { format: 'xlsx', topic: '주간 브리핑 (1단계)' } },
      { type: 'doc_meta', doc_id: 'doc1', format: 'xlsx', filename: '주간 브리핑 (1단계).xlsx', topic: '주간 브리핑 (1단계)', total: 1 },
      { type: 'doc_page', idx: 1, total: 1, title: '시트', sheet: { columns: ['a'], rows: [] }, csv: 'a' },
      { type: 'answer_head', source: '문서 생성|Excel' },
      { type: 'token', text: '엑셀 파일을 생성했습니다. 오른쪽에서 확인하세요.' },
      { type: 'done', message_id: 'm2', size: 3355443 },
      { type: 'execution_result', state: 'completed', run_id: 'run1' },
    ];
    // 파일 세그먼트 시작 직후(만드는 중) 모양도 잡는다 / also capture the card right after the segment starts (loading)
    let loading = null;
    const realHandle = ai365HandleEvent;
    ai365HandleEvent = function (ev, wrap, state) {
      const r = realHandle.apply(this, arguments);
      if (ev.type === 'thinking_start' && state.doc && !loading) loading = wrap.innerHTML;
      return r;
    };
    window.fetch = async () => new Response(events.map(e => 'data: ' + JSON.stringify(e) + '\n\n').join(''));
    ai365FlowRunStart({ chat: 'c', name: '주간 브리핑', total: 2, stage: 1 });
    await ai365StreamReply('보고해 줘', { flowId: 'fl1' });
    const wraps = Array.from(chatInner.querySelectorAll('.msg-ai'));
    const fileWrap = wraps[wraps.length - 1];
    const box = document.createElement('div'); box.innerHTML = loading || '';
    return {
      wraps: wraps.length,
      loading: { cls: (box.querySelector('.ai365-flow-file') || {}).className, name: (box.querySelector('.ai365-flow-file-tx b') || {}).textContent,
        sub: (box.querySelector('.ai365-flow-file-tx span') || {}).textContent, spinner: !!box.querySelector('.spinner') },
      cls: fileWrap.querySelector('.ai365-flow-file').className,
      tags: [fileWrap.getAttribute('data-flow-stage'), fileWrap.hasAttribute('data-flow-file')],
      name: fileWrap.querySelector('.ai365-flow-file-tx b').textContent,
      sub: fileWrap.querySelector('.ai365-flow-file-tx span').textContent,
      icon: fileWrap.querySelector('.ai365-doc-chip-ic').textContent,
      open: fileWrap.querySelector('[data-ai365-docopen]').getAttribute('data-ai365-docopen'),
      dl: fileWrap.querySelector('[data-ai365-flowfile-dl]').getAttribute('data-ai365-flowfile-dl'),
      text: fileWrap.textContent.includes('오른쪽에서'),
      todo: document.querySelectorAll('.ai365-doc-todo').length,
      foot: fileWrap.querySelectorAll('.msg-foot').length,
      snapshot: !!AI365_DOC_DATA.doc1 && AI365_DOC_DATA.doc1.pages.length,
      bar: !!document.getElementById('ai365FlowBar'),
    };
  });
  assert.equal(out.wraps, 2);
  assert.deepEqual(out.loading, { cls: 'ai365-flow-file loading', name: '주간 브리핑 (1단계)', sub: '파일을 만들고 있습니다', spinner: true });
  assert.equal(out.cls, 'ai365-flow-file done');
  assert.deepEqual(out.tags, ['1', true]);
  assert.equal(out.name, '주간 브리핑 (1단계).xlsx');
  assert.equal(out.sub, 'Excel · 3.2MB');
  assert.equal(out.icon, 'X');
  assert.equal(out.open, 'doc1');
  assert.equal(out.dl, 'doc1');
  assert.equal(out.text, false);   // no completion text
  assert.equal(out.todo, 0);
  assert.equal(out.foot, 0);
  assert.equal(out.snapshot, 1);   // reopen snapshot for the split view
  assert.equal(out.bar, false);    // completed → the bar went away
});

test('stage file card: size only when provided, failed state, and the download button saves the file', async t => {
  const page = await fixture(t);
  const out = await page.evaluate(async () => {
    const html = d => { const b = document.createElement('div'); b.innerHTML = ai365FlowFileHtml(d); return b.querySelector('.ai365-flow-file'); };
    const noSize = html({ state: 'done', id: 'd1', format: 'pptx', filename: '보고.pptx' });
    const failed = html({ state: 'failed', format: 'docx', topic: '가이드' });
    const saved = [];
    window.fetch = async url => { saved.push(url); return new Response(new Blob(['x'])); };
    const realCreate = document.createElement.bind(document);
    let anchor = null;
    document.createElement = function (tag) { const el = realCreate(tag); if (tag === 'a') { anchor = el; el.click = () => {}; } return el; };
    chatInner.innerHTML = '<div class="msg msg-ai">' + ai365FlowFileHtml({ state: 'done', id: 'd9', format: 'xlsx', filename: '표.xlsx', size: 2048 }) + '</div>';
    chatInner.querySelector('[data-ai365-flowfile-dl]').click();
    await new Promise(r => setTimeout(r, 30));
    document.createElement = realCreate;
    return {
      noSize: noSize.querySelector('.ai365-flow-file-tx span').textContent,
      failed: [failed.className, failed.querySelector('.ai365-flow-file-tx span').textContent, !!failed.querySelector('[data-ai365-flowfile-dl]'), !!failed.querySelector('[data-ai365-docopen]')],
      small: chatInner.querySelector('.ai365-flow-file-tx span').textContent,
      saved, download: anchor && anchor.download, toasts: window.toasts,
      sizes: [ai365FlowFileSize(0), ai365FlowFileSize(512), ai365FlowFileSize(10240), ai365FlowFileSize(3355443)],
    };
  });
  assert.equal(out.noSize, 'PPT');
  assert.deepEqual(out.failed, ['ai365-flow-file failed', '파일을 만들지 못했습니다', false, false]);
  assert.equal(out.small, 'Excel · 2KB');
  assert.deepEqual(out.saved, ['/api/docgen/d9/file']);
  assert.equal(out.download, '표.xlsx');
  assert.deepEqual(out.toasts, ['파일이 다운로드되었습니다.']);
  assert.deepEqual(out.sizes, ['', '512B', '10KB', '3.2MB']);
});

// 2026-09-30 복원: 칩(meta.flow) · 접힌 답변 줄(flow_answers, 말풍선 없음) · 단계 실행 말풍선(flow_step) · 수정 요청 줄(flow_revise) ·
// 밀려난 답변(더 큰 flow_attempt) + 그 단계 파일 = 이전 결과 묶음 · 응답한 단계 완료 카드 숨김 · 대기 카드 재무장 + 진행 표시줄
// 2026-09-30 restore: chip (meta.flow), collapsed answer row (flow_answers, no bubble), stage-run bubble (flow_step), revision row
// (flow_revise), a superseded answer (larger flow_attempt) plus its stage file = the previous-result group, answered stage cards
// hidden, the waiting card re-armed with the progress bar
test('restore rebuilds the workflow thread from message meta and re-arms the waiting card with the progress bar', async t => {
  const page = await fixture(t);
  const trace = stage => ({ tasks: [], stages: [{ no: 1, tasks: [] }, { no: 2, tasks: [] }], lines: [{ t: 'stage', stage, status: 'running', cards: [] }] });
  const gate = (stage, run) => ({ run_id: run, stage, next_stage: stage + 1, flow_name: '주간 브리핑', total_stages: 3,
    next_items: [{ agent: 'web', label: '웹 검색', task: '업계 동향 조사' }] });
  const messages = [
    { id: 'u1', role: 'user', content: '3월 기준으로', meta: { flow: { id: 'fl1', name: '주간 브리핑', stages: 3 } } },
    { id: 'a1', role: 'assistant', content: '첫 답변', meta: { trace: trace(1), flow_stage: 1, flow_attempt: 1 } },
    { id: 'd1', role: 'assistant', content: '파일', meta: { kind: 'doc', doc: { id: 'doc1', format: 'xlsx', filename: '첫.xlsx', status: 'done', size: 3355443 } } },
    { id: 'g1', role: 'assistant', content: '1단계 완료', meta: { kind: 'flow_gate', card: gate(1, 'r1'), resume_id: 'r1', answered: true } },
    { id: 'u2', role: 'user', content: '1단계 수정 요청: 서울만', meta: { flow_revise: { stage: 0 } } },
    { id: 'a2', role: 'assistant', content: '고친 답변', meta: { trace: trace(1), flow_stage: 1, flow_attempt: 2 } },
    { id: 'd2', role: 'assistant', content: '파일', meta: { kind: 'doc', doc: { id: 'doc2', format: 'xlsx', filename: '고친.xlsx', status: 'done' } } },
    { id: 'g2', role: 'assistant', content: '1단계 완료', meta: { kind: 'flow_gate', card: gate(1, 'r1'), resume_id: 'r1', answered: true } },
    { id: 'u3', role: 'user', content: '2단계 실행: 표로', meta: { flow_step: { stage: 1 } } },
    { id: 'q1', role: 'assistant', content: '2단계 답변을 작성하기 전에 몇 가지 확인할게요.', meta: { kind: 'flow_question', resume_id: 'r1',
      card: { run_id: 'r1', stage: 2, intro: '2단계 답변을 작성하기 전에 몇 가지 확인할게요.', items: [{ id: 'q', question: '지점?', kind: 'text', required: true }] } } },
    { id: 'u4', role: 'user', content: '지점: 서울', meta: { flow_answers: { stage: 1, values: ['서울'] } } },
    { id: 'a3', role: 'assistant', content: '2단계 답변', meta: { trace: trace(2), flow_stage: 2, flow_attempt: 1 } },
    { id: 'g3', role: 'assistant', content: '2단계 완료', meta: { kind: 'flow_gate', card: gate(2, 'r1'), resume_id: 'r1' } },
  ];
  await page.evaluate(ms => {
    window.fetches = [];
    window.fetch = async url => {
      window.fetches.push(url);
      if (/\/messages$/.test(url)) return new Response(JSON.stringify(ms), { status: 200 });
      if (/\/api\/flows\/runs\/r1$/.test(url)) return new Response(JSON.stringify({ run_id: 'r1', state: 'needs_input', waiting_kind: 'gate',
        stage: 2, name: '주간 브리핑', flow_name: '주간 브리핑', total_stages: 3, stage_index: 1 }), { status: 200 });
      return new Response('{}', { status: 200 });
    };
    chats[0].run_state = 'needs_input';
    ai365RestoreMessages('c');
  }, messages);
  await page.waitForSelector('.ai365-flow-gate [data-flow-gate-run]:not([disabled])');
  const out = await page.evaluate(() => ({
    order: Array.from(chatInner.children).map(n => n.classList.contains('msg-user') ? 'user:' + n.querySelector('.user-bubble').textContent
      : n.classList.contains('ai365-flow-oldgrp') ? 'old:' + n.querySelector('.ai365-flow-oldrow').textContent.trim() + '[' + Array.from(n.querySelectorAll('.ai365-flow-oldbody > *')).map(x => x.textContent.trim()).join('|') + ']'
      : n.classList.contains('ai365-flow-revrow') ? 'rev:' + n.textContent.trim()
      : n.querySelector('.ai365-flow-okrow') ? 'q:' + n.querySelector('.ai365-flow-q-intro').textContent + '/' + n.querySelector('.ai365-flow-okrow').textContent.trim()
      : n.querySelector('.ai365-flow-file') ? 'file:' + n.querySelector('.ai365-flow-file-tx').textContent
      : n.querySelector('.ai365-flow-gate') ? 'gate:' + n.querySelector('.ai365-flow-gate').dataset.stage
      : 'ai:' + n.textContent.trim() + ':' + n.getAttribute('data-flow-stage')),
    chip: Array.from(document.querySelectorAll('.msg-user .ai365-wf-uchip')).map(c => c.textContent),
    bar: document.getElementById('ai365FlowBar') ? [document.querySelector('.ai365-flow-bar-nm').textContent,
      Array.from(document.querySelectorAll('.ai365-flow-bar-dots i')).map(i => i.className).join(','), document.querySelector('.ai365-flow-bar-st').textContent] : null,
    run: AI365_FLOW_RUN && AI365_FLOW_RUN.runId,
    last: AI365_FLOW_LAST,
  }));
  assert.deepEqual(out.order, [
    'user:3월 기준으로',
    'old:1단계 이전 결과[사내첫 답변|X첫.xlsxExcel · 3.2MB]',
    'rev:1단계 수정 요청: 서울만',
    'ai:사내고친 답변:1',
    'file:고친.xlsxExcel',
    'user:2단계 실행: 표로',
    'q:2단계 답변을 작성하기 전에 몇 가지 확인할게요./2단계 실행 · 서울',
    'ai:사내2단계 답변:2',
    'gate:2',
  ]);
  assert.deepEqual(out.chip, ['주간 브리핑3단계']);   // only the run-start row gets the chip
  assert.deepEqual(out.bar, ['주간 브리핑', 'done,cur,todo', '3단계 중 2단계']);
  assert.equal(out.run, 'r1');
  assert.deepEqual(out.last, { chat: 'c', name: '주간 브리핑', total: 3 });
});

test('restore plan: only a later flow_attempt within the same run folds an answer, older chats without meta stay as they were', async t => {
  const page = await fixture(t);
  const out = await page.evaluate(() => {
    const tr = n => ({ lines: [{ t: 'stage', stage: n, status: 'running' }] });
    const plan = ai365FlowRestorePlan([
      { role: 'user', content: 'a', meta: { flow: { id: 'f', name: 'F', stages: 2 } } },
      { role: 'assistant', content: 's1', meta: { trace: tr(1), flow_stage: 1, flow_attempt: 1 } },
      { role: 'user', content: 'b', meta: { flow: { id: 'f', name: 'F', stages: 2 } } },   // a new run in the same chat
      { role: 'assistant', content: 's1 again', meta: { trace: tr(1), flow_stage: 1, flow_attempt: 1 } },
      { role: 'user', content: '보통 질문' },
      { role: 'assistant', content: '문서', meta: { kind: 'doc', doc: { id: 'x' } } },   // outside a run span: a regular doc
      { role: 'assistant', content: 'legacy 1', meta: { trace: tr(1), flow_stage: 1 } },
      { role: 'assistant', content: 'legacy 2', meta: { trace: tr(1), flow_stage: 1 } },   // no flow_attempt: never folds
    ]);
    return plan.map(p => [!!p.superseded, !!p.file, p.stage || 0, !!p.flow]);
  });
  assert.deepEqual(out, [[false, false, 0, true], [false, false, 1, false], [false, false, 0, true], [false, false, 1, false],
    [false, false, 0, false], [false, false, 0, false], [false, false, 1, false], [false, false, 1, false]]);
});

// 스트림 무응답 안내(2026-09-14): 데이터가 지연되면 "모델 응답을 기다리는 중입니다 · n초" 줄이 붙고, 다음 데이터(재무장)·종료(clear)에 지워진다
// Stream stall notice (2026-09-14): a delayed stream gets a "Waiting for the model to respond · ns" row, removed on the next event (re-arm) or at the end (clear)
test('stream stall notice appears after the delay and disappears on the next event', async t => {
  const page = await fixture(t);
  const out = await page.evaluate(async () => {
    const wrap = document.createElement('div'); document.getElementById('chat').appendChild(wrap);
    const stall = ai365StallMake(60);
    stall.arm(wrap);
    await new Promise(r => setTimeout(r, 160));
    const shown = !!wrap.querySelector('.ai365-stall-note');
    const text = shown ? wrap.querySelector('.ai365-stall-note').textContent : '';
    stall.arm(wrap);                                   // 다음 데이터 = 재무장 → 즉시 제거 / the next event re-arms and removes it
    const afterRearm = !!wrap.querySelector('.ai365-stall-note');
    await new Promise(r => setTimeout(r, 160));
    const shownAgain = !!wrap.querySelector('.ai365-stall-note');
    stall.clear();
    return { shown, text, afterRearm, shownAgain, afterClear: !!wrap.querySelector('.ai365-stall-note') };
  });
  assert.equal(out.shown, true);
  assert.ok(out.text.startsWith('모델 응답을 기다리는 중입니다'), out.text);
  assert.ok(/[0-9]초$/.test(out.text.trim()), out.text);
  assert.equal(out.afterRearm, false);
  assert.equal(out.shownAgain, true);
  assert.equal(out.afterClear, false);
});
