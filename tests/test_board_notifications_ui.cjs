// Isolated browser fixture: real notification UI functions, no application DB or network.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const source = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8').replace(/\r\n/g, '\n');
const start = source.indexOf('  // Persistent notices;');
const end = source.indexOf('  // ── 렌더 / render ──', start);
const detailStart = source.indexOf('  function openDetail(pid) {', source.indexOf('(function ai365Boards()'));
const detail = source.slice(detailStart, source.indexOf('\n  }', detailStart) + 4);
let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

async function fixture(t) {
  const page = await browser.newPage();
  t.after(() => page.close());
  await page.setContent('<span id="ai365BdUnread" hidden></span><div id="ai365BdNotices"></div>');
  await page.evaluate(code => {
    window.user = '7'; window.pending = [];
    window.acting = () => window.user;
    window.T = s => s;
    window.E = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    window.B = {}; window.render = () => {}; window.toast = () => {};
    window.ai365Fetch = url => new Promise(resolve => window.pending.push({url, resolve}));
    window.setTimeout = () => 1; window.clearTimeout = () => {};
    window.eval(code + '\nwindow.poll = pollNotices; window.reset = resetNotices; window.openPost = openDetail;');
  }, source.slice(start, end) + '\n' + detail);
  return page;
}

test('unread badge and safe title render; opening a post refreshes read state', async t => {
  const page = await fixture(t);
  await page.evaluate(() => { poll(); pending.shift().resolve({unread: 1, notifications: [{post_id:'bp_1',title:'<img src=x onerror=alert(1)>'}]}); });
  await page.waitForFunction(() => document.getElementById('ai365BdUnread').textContent === '1');
  assert.equal(await page.locator('#ai365BdUnread').isVisible(), true);
  assert.equal(await page.locator('#ai365BdNotices img').count(), 0);
  assert.equal(await page.locator('[data-bd-open]').textContent(), '<img src=x onerror=alert(1)>');
  await page.evaluate(() => {
    document.getElementById('ai365BdNotices').addEventListener('click', e => openPost(e.target.closest('[data-bd-open]').dataset.bdOpen));
  });
  await page.locator('[data-bd-open]').click();
  assert.match(await page.evaluate(() => pending[0].url), /posts\/bp_1\?acting_user_id=7/);
  await page.evaluate(() => pending.shift().resolve({post:{id:'bp_1'}}));
  await page.waitForFunction(() => pending.length === 1);
  await page.evaluate(() => pending.shift().resolve({unread:0,notifications:[]}));
  await page.waitForFunction(() => document.getElementById('ai365BdUnread').hidden);
  assert.equal(await page.locator('[data-bd-open]').count(), 0);
});

test('responses from a previous identity or older poll cannot restore private notices', async t => {
  const page = await fixture(t);
  await page.evaluate(() => {
    poll(); user = '12'; reset(); poll();
    pending[1].resolve({unread:1, notifications:[{post_id:'new',title:'Current user'}]});
  });
  await page.waitForFunction(() => document.querySelector('[data-bd-open="new"]'));
  await page.evaluate(() => pending[0].resolve({unread:1, notifications:[{post_id:'old',title:'Previous user'}]}));
  assert.equal(await page.locator('[data-bd-open="old"]').count(), 0);
  await page.evaluate(() => {
    pending = []; poll(); poll();
    pending[1].resolve({unread:0,notifications:[]});
  });
  await page.waitForFunction(() => document.getElementById('ai365BdUnread').hidden);
  await page.evaluate(() => pending[0].resolve({unread:1,notifications:[{post_id:'stale',title:'Stale'}]}));
  assert.equal(await page.locator('[data-bd-open]').count(), 0);
});
