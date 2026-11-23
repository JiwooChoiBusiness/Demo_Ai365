// Real schedule modal, mocked HTTP only: no application DB or outgoing actions.
// Workflow mode (2026-09-11): the schedule modal dropped the workflow (flow_id/flow_query) select and the
// connector pill entirely — a schedule now runs a prompt only. This file replaces the old flow/connector
// coverage with assertions that the create/edit payloads carry `message` and never the retired keys, and
// that an empty prompt is rejected before any network call (frontend/ai365-mockup.html cdSaveSched()).
const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
// 서버(app/main.py _kst_head)처럼 한국 시간 도우미(static/kst.js)를 <head> 맨 앞에 넣는다. 예약 모달의 기본 시각·지난 시각 검사가 쓴다.
// Inject the KST helpers (static/kst.js) first in <head>, as the server does; the schedule modal's default time and past-time check use them.
const kst = fs.readFileSync(path.join(__dirname, '../static/kst.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../frontend/ai365-mockup.html'), 'utf8')
  .replace(/<head[^>]*>/i, m => m + '<script>' + kst + '</script>');
let browser;
before(async () => { browser = await chromium.launch({channel: 'msedge', headless: true}); });
after(async () => { if (browser) await browser.close(); });

async function modal(t, opts = {}) {
  const page = await browser.newPage();
  t.after(() => page.close());
  const patches = [];
  await page.route('**/*', route => {
    if (route.request().method() === 'PATCH' ||
        (route.request().method() === 'POST' && route.request().url().endsWith('/api/schedules'))) {
      patches.push(route.request().postDataJSON());
      return route.fulfill({contentType: 'application/json', body: '{"id":"s_test"}'});
    }
    const root = route.request().url() === 'http://review.local/';
    return route.fulfill({contentType: root ? 'text/html' : 'application/json', body: root ? html : '[]'});
  });
  await page.goto('http://review.local/');
  await page.waitForFunction(() => typeof AI365_SCHED_EDIT === 'function');
  await page.evaluate(opts => {
    document.body.appendChild(document.getElementById('cdSchedOv'));
    if (opts.create) { AI365_SCHED_CREATE({}); return; }
    AI365_SCHED_EDIT({id: 's_test', name: 'review', message: '재고 조회', scope: '자동', status: 'active',
      rule: 'daily', run_at: '09:00', days: [], agents: [], smf_files: [],
      scope_files: {knowledge_files: [], data_tables: [], data_bi: [], work: false}, notify_email: true,
      ...opts.schedule}, {});
  }, opts);
  return {page, patches};
}

// Keys the 2026-09-11 workflow-mode change retired from the schedule payload — the modal must never send them.
const RETIRED_KEYS = ['connectors', 'flow_id', 'flow_name', 'flow_query'];

test('name-only edit leaves the cadence and resources untouched and carries no workflow/connector keys', async t => {
  const {page, patches} = await modal(t);
  await page.locator('#cdSchedTitleIn').fill('이름만 수정');
  const saved = page.waitForRequest(request => request.method() === 'PATCH');
  await page.locator('#cdSchedSave').click();
  await saved;
  assert.equal(patches.length, 1);
  assert.equal(patches[0].name, '이름만 수정');
  assert.equal(patches[0].message, '재고 조회');   // message always rides along, unchanged here
  const untouched = [...RETIRED_KEYS, 'rule', 'run_at', 'days', 'end_at', 'freq', 'interval', 'mday',
    'agents', 'scope_files', 'smf_files', 'notify_email', 'coll_id', 'status'];
  for (const key of untouched) assert.equal(Object.hasOwn(patches[0], key), false, key);
});

test('editing the prompt saves the new message with no workflow/connector keys', async t => {
  const {page, patches} = await modal(t);
  await page.locator('#cdSchedMsg').fill('창고별 재고 조회');
  const saved = page.waitForRequest(request => request.method() === 'PATCH');
  await page.locator('#cdSchedSave').click();
  await saved;
  assert.equal(patches.length, 1);
  assert.equal(patches[0].message, '창고별 재고 조회');
  for (const key of RETIRED_KEYS) assert.equal(Object.hasOwn(patches[0], key), false, key);
});

test('empty prompt is rejected client-side on edit and does not save', async t => {
  const {page, patches} = await modal(t);
  await page.locator('#cdSchedMsg').fill('');
  await page.locator('#cdSchedSave').click();
  assert.equal(patches.length, 0);
  assert.equal(await page.locator('#cdSchedOv').isVisible(), true);   // save was blocked — modal stays open
});

test('create requires a prompt, then saves a plain message payload with no workflow/connector keys', async t => {
  const {page, patches} = await modal(t, {create: true});
  await page.locator('#cdSchedSave').click();   // blank prompt on a fresh form — blocked, no request
  assert.equal(patches.length, 0);
  assert.equal(await page.locator('#cdSchedOv').isVisible(), true);
  await page.locator('#cdSchedMsg').fill('신규 예약 프롬프트');
  const saved = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/api/schedules'));
  await page.locator('#cdSchedSave').click();
  await saved;
  assert.equal(patches.length, 1);
  assert.equal(patches[0].message, '신규 예약 프롬프트');
  for (const key of RETIRED_KEYS) assert.equal(Object.hasOwn(patches[0], key), false, key);
});
