// Run with Playwright available on NODE_PATH: node --test tests/test_clarify_ui.cjs
// Actual adapter functions in an isolated browser; no application DB, LLM, or mail calls.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const source = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8').replace(/\r\n/g, '\n');
function fn(name) {
  const start = source.search(new RegExp('^(?:async )?function ' + name + '\\(', 'm'));
  assert.ok(start >= 0, name);
  return source.slice(start, source.indexOf('\n}', start) + 2);
}
const card = { question: '취합한 보고서를 누구에게 메일로 보낼까요?',
  options: [{ label: '나에게', value: '나에게' }, { label: '팀장님에게', value: '팀장님에게' }], allow_detail: true };
const message = { id: 'clarify-test', role: 'assistant', content: card.question + '\n선택지: 나에게 / 팀장님에게',
  meta: { kind: 'clarify', card } };
let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

async function fixture(t) {
  const page = await browser.newPage();
  t.after(() => page.close());
  await page.setContent('<div id="chat"></div>');
  await page.addScriptTag({ content: `
    const chatInner = document.getElementById('chat'), chatScroll = chatInner;
    let currentChatId = 'c', chats = [{id: 'c', run_state: 'needs_input'}];
    let ai365StreamRun = null, ai365StreamWrap = null, ai365StreamState = null, ai365Abort = null;
    let AI365_ATTACH_PENDING = null;
    const AI365_BACKEND_IDS = new Set(['c']), AI365_JSON_HEADERS = {}, FOOT = '<footer></footer>';
    const AI365_CUSTOM_OPTS = ['직접 입력할게요', 'Enter it myself'];
    const ai365Esc = s => { const el = document.createElement('span'); el.textContent = s || ''; return el.innerHTML.replace(/"/g, '&quot;'); };
    const aiHead = () => '<header>사내</header>', ai365SourceHtml = () => '사내';
    const ai365MnMd = ai365Esc, ai365CardsHtml = () => '', ai365T = s => s;
    const stickToBottom = () => {}, renderChatLists = () => {}, ai365RunMarkSeen = () => {};
    const ai365CurrentScope = () => '사내', ai365SelectedAgents = () => [];
    const AI365_VALID_AGENTS = ['knowledge', 'data', 'groupware', 'work'];
    const ai365SetSending = v => { window.sending = v; };
    const appendUserMessage = text => { const el = document.createElement('p'); el.textContent = text; chatInner.appendChild(el); };
    let submitForm = () => {};
    ${['ai365IsCustom', 'ai365RenderClarify', 'ai365AppendAssistant', 'ai365RestoreMessages',
       'ai365ClarifyValidate', 'ai365CollectClarify', 'ai365SelectionSnapshot', 'ai365StreamReply'].map(fn).join('\n')}
    ${source.slice(source.indexOf('const ai365OrigSubmitForm = submitForm;'),
      source.indexOf('\n};', source.indexOf('const ai365OrigSubmitForm = submitForm;')) + 3)}
  ` });
  return page;
}

test('saved clarification restores options and free text; submitting sends the selected answer once', async t => {
  const page = await fixture(t);
  await page.evaluate(m => {
    window.ai365Fetch = async () => [m];
    window.sent = [];
    ai365StreamReply = text => window.sent.push(text);
    ai365RestoreMessages('c');
  }, message);
  await page.waitForSelector('[data-form="ai365-clarify"]');
  assert.equal(await page.locator('.option-row').count(), 2);
  assert.equal(await page.locator('[data-detail-input]').count(), 1);
  assert.equal(await page.locator('[data-form-submit]').isDisabled(), true);
  await page.evaluate(() => {
    const form = document.querySelector('.form-card');
    form.querySelector('.option-row').classList.add('selected');
    ai365ClarifyValidate(form);
  });
  assert.equal(await page.locator('[data-form-submit]').isEnabled(), true);
  await page.evaluate(() => { const form = document.querySelector('.form-card'); submitForm(form); submitForm(form); });
  assert.deepEqual(await page.evaluate(() => window.sent), [card.question + ' → 나에게']);
});

test('a later user turn disables the historical card while a new clarification remains active', async t => {
  const page = await fixture(t);
  await page.evaluate(m => {
    window.ai365Fetch = async () => [m, {role: 'user', content: '나에게'}, {...m, id: 'next'}];
    ai365RestoreMessages('c');
  }, message);
  await page.waitForSelector('.form-card.submitted');
  assert.equal(await page.locator('.form-card').count(), 2);
  assert.equal(await page.locator('.form-card').first().locator('.option-row').first().isDisabled(), true);
  assert.equal(await page.locator('.form-card').first().locator('[data-form-submit]').count(), 0);
  assert.equal(await page.locator('.form-card').last().locator('.option-row').first().isEnabled(), true);
});

test('exploration turns do not consume a pending clarification; free text remains submittable', async t => {
  const page = await fixture(t);
  await page.evaluate(m => {
    window.ai365Fetch = async () => [m, {role: 'user', content: '탐색', meta: {kind: 'explore'}}];
    ai365RestoreMessages('c');
  }, message);
  await page.waitForSelector('.form-card');
  await page.locator('[data-detail-input]').fill('담당자@example.com');
  await page.evaluate(() => ai365ClarifyValidate(document.querySelector('.form-card')));
  assert.equal(await page.locator('[data-form-submit]').isEnabled(), true);
});

test('clarify-only SSE finishes as needs_input without scheduling a reconnect', async t => {
  const page = await fixture(t);
  await page.evaluate(async c => {
    window.ai365HandleEvent = (ev, wrap) => ai365RenderClarify(wrap, ev.card);
    window.fetch = async () => new Response('data: ' + JSON.stringify({type: 'clarify', card: c}) + '\n\n');
    window.reconnects = 0;
    window.setTimeout = () => { window.reconnects++; };
    await ai365StreamReply('보고서를 메일로 보내줘');
  }, card);
  assert.equal(await page.locator('.form-card').count(), 1);
  assert.equal(await page.evaluate(() => chats[0].run_state), 'needs_input');
  assert.equal(await page.evaluate(() => window.sending), false);
  assert.equal(await page.evaluate(() => window.reconnects), 0);
});

test('stream preserves selected groupware, worker and resources across asynchronous attachment preparation', async t => {
  const page = await fixture(t);
  const payload = await page.evaluate(async () => {
    const selection = {agents:['work', 'groupware'], files:['work:email', 'gw:agent'],
      scope:{knowledge_files:['policy.pdf'], data_tables:[], data_bi:[], work:true}};
    window.AI365_SMF_HOOKS = {agents:()=>selection.agents, files:()=>selection.files, scope:()=>selection.scope};
    let release;
    AI365_ATTACH_PENDING = {chatId:'c', att:{}, done:new Promise(resolve=>{release=resolve;})};
    window.ai365HandleEvent = (ev, wrap, state) => { if (ev.type === 'done') state.done = true; };
    let sent;
    window.fetch = async (url, init) => {
      sent = {url, body:JSON.parse(init.body)};
      return new Response('data: ' + JSON.stringify({type:'done'}) + '\n\n');
    };
    const running = ai365StreamReply('인보이스를 취합해서 Outlook으로 보내줘');
    selection.agents.splice(0,2,'data');
    selection.files.splice(0,2,'work:edu');
    selection.scope.knowledge_files.push('new.pdf');
    release();
    await running;
    return sent;
  });
  assert.equal(payload.url, '/api/chats/c/stream');
  assert.deepEqual(payload.body.agents, ['work','groupware']);
  assert.deepEqual(payload.body.scope_files.workers, ['email']);
  assert.deepEqual(payload.body.scope_files.knowledge_files, ['policy.pdf']);
});

test('server document segment uses a new message and initializes document state without a second request', async t => {
  const page = await fixture(t);
  await page.evaluate(async () => {
    window.requests = 0;
    window.docReady = false;
    window.ai365HandleEvent = (ev, wrap, state) => {
      if (ev.type === 'token') wrap.textContent = ev.text;
      if (ev.type === 'done') state.done = true;
      if (ev.type === 'doc_meta') window.docReady = state.doc.cfg.format === 'pdf';
    };
    const events = [{type: 'token', text: '취합 보고서'}, {type: 'done'},
      {type: 'segment_start', doc: {format: 'pdf'}}, {type: 'doc_meta'},
      {type: 'token', text: '파일 생성 완료'}, {type: 'done'}];
    window.fetch = async () => { window.requests++; return new Response(events.map(e => 'data: ' + JSON.stringify(e) + '\n\n').join('')); };
    await ai365StreamReply('PDF 보고서');
  });
  assert.equal(await page.locator('.msg-ai').count(), 2);
  assert.equal(await page.locator('.msg-ai').first().textContent(), '취합 보고서');
  assert.equal(await page.locator('.msg-ai').last().textContent(), '파일 생성 완료');
  assert.equal(await page.evaluate(() => window.requests), 1);
  assert.equal(await page.evaluate(() => window.docReady), true);
});

test('restored question submits its run id with the answer', async t => {
  const page = await fixture(t);
  await page.evaluate(m => {
    ai365AppendAssistant(chats[0], m);
    window.sent = [];
    ai365StreamReply = (text, opts) => window.sent.push({text, opts});
    const form = document.querySelector('.form-card');
    form.querySelector('[data-detail-input]').value = '나에게';
    submitForm(form);
  }, {...message, meta: {kind: 'clarify', card: {...card, resume_id: 'run_test'}}});
  assert.equal(await page.evaluate(() => window.sent[0].opts.resumeId), 'run_test');
});

test('confirm response attaches to the server continuation without sending a new user request', async t => {
  const page = await fixture(t);
  const anchor = source.indexOf('  const actionId = card.dataset.actionId;');
  const start = source.lastIndexOf("chatInner.addEventListener('click', async e => {", anchor);
  await page.addScriptTag({content: source.slice(start, source.indexOf('\n});', anchor) + 4)});
  await page.evaluate(() => {
    chatInner.innerHTML = '<div class="ai365-confirm" data-action-id="a_test"><div class="form-foot"><button data-ai365-confirm>실행</button></div></div>';
    window.sent = [];
    ai365StreamReply = (text, opts) => window.sent.push({text, opts});
    window.ai365Fetch = async () => ({ok: true, text: '실행 완료', resume_chat_id: 'c'});
  });
  await page.locator('[data-ai365-confirm]').click();
  await page.waitForFunction(() => window.sent.length === 1);
  assert.deepEqual(await page.evaluate(() => window.sent), [{text: '', opts: {attach: true}}]);
});

test('server-resolved card stays disabled even without a later user message', async t => {
  const page = await fixture(t);
  await page.evaluate(m => {
    window.ai365Fetch = async () => [{...m, meta: {...m.meta, answered: true}}];
    ai365RestoreMessages('c');
  }, message);
  await page.waitForSelector('[data-form="ai365-clarify"]');
  assert.equal(await page.locator('.option-row').first().isDisabled(), true);
  assert.equal(await page.locator('[data-form-submit]').count(), 0);
  assert.equal(await page.locator('.form-card.submitted').count(), 1);
});
