// Run with Playwright available on NODE_PATH: node --test --test-concurrency=1 tests/test_resource_select_ui.cjs
// 리소스 선택 대화 상자(2026-10-28, static/resource_select.js · Dev 원본 정렬 명세 1.1): 목업 전체 + 어댑터 + 이 모듈을 가짜 원점에 올린
// 격리 브라우저에서 돌린다. 칩 클릭 → 곧바로 대화 상자(#agentMenu 없음) · 구획 5개 순서 · 접힘/펼침 · 전체 선택 · Local 배타 · [선택 완료]
// 비활성/반영(훅 · 칩 라벨 · .agp-active) · [취소] · X · Esc · 바깥 복원 · BI(지금 정책 = 여러 개) · 예약 openMenu 경로(Local 잠금) ·
// scope_files.local_agents 전송 · 스태시/복원 왕복 · 칩 모양 · 홈 코치 툴팁 1회 · EN 라벨. 네트워크는 전부 스텁(서버 · DB · LLM 없음).
// 2026-10-28 검토 반영: 명시 분야(홈 미니 입력)는 로컬 선택을 잇지 않음(컬렉션 컴포저는 이음) · 포커스 가두기 · 다른 팝오버 닫기 · 칩 관찰자 프레임 묶음 · 제목 700.
// Resource picker (2026-10-28, static/resource_select.js, Dev-original alignment spec 1.1): the whole mockup + adapter + this module
// on a fake origin in an isolated browser. Chip click → the dialog at once (no #agentMenu), five sections in order, collapse and
// expand, select all, Local exclusivity, [Done] disabled/applied (hooks, chip label, .agp-active), [Cancel] / X / Esc / outside
// restore, BI (current policy: several), the schedules openMenu path (Local locked), scope_files.local_agents on the stream, the
// stash/restore round trip, the chip look, the one-time home coach tooltip and the EN labels. Every request is stubbed.
// 2026-10-28 review: explicit domains (the home mini composer) never inherit the local pick (the collection composer does), the
// focus trap, closing other popovers, one chip scan per frame and the 700 title.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const mockup = fs.readFileSync(path.join(__dirname, '../frontend/ai365-mockup.html'), 'utf8').replace(/\r\n/g, '\n');
const ADAPTER = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8');
const MODULE = fs.readFileSync(path.join(__dirname, '../static/resource_select.js'), 'utf8');
const ORIGIN = 'http://rs.test';
const HTML = mockup.replace('</body>', '<script src="/static/adapter.js"></script><script src="/static/resource_select.js"></script></body>');
// 예약 창(#cdSchedOv)은 KST 도우미(static/kst.js, 서버가 <head> 맨 앞에 넣는다)를 쓴다 / the schedule dialog needs the KST helpers
const KST = fs.readFileSync(path.join(__dirname, '../static/kst.js'), 'utf8');
const HTML_KST = HTML.replace(/<head(\s[^>]*)?>/i, m => m + '<script src="/static/kst.js"></script>');
const HQ = 'kl_demo_hq', LAB = 'kl_lab0001';
const AGENTS = [{ id: HQ, name: '본사 로컬 에이전트', enabled: true }, { id: LAB, name: '연구소 지식 에이전트', enabled: true },
  { id: 'kl_off0001', name: '꺼진 에이전트', enabled: false }];
const FOLDERS = { [HQ]: [{ id: 'f1', name: '경영 규정', children: [{ id: 'f1a', name: '보안 정책', children: [] }] }], [LAB]: [] };
const WS = [{ id: 'ws_fin', name: '재무 그룹', team: '재무회계파트', desc: '재무 · 회계 데이터 분석',
  sql: [{ name: '매출_월별_집계', table: 'sales_branch_monthly' }],
  bi: [{ name: '월간 손익 대시보드', file: 'pl_monthly.pbix' }, { name: '자금 현황 모니터링', file: 'cash.pbix' }],
  csv: [{ name: '2024_결산_원장.csv', table: 'finance_expenses' }] }];
const PVTREE = [{ id: 'm_res', label: '리소스 센터', kind: 'menu', children: [{ id: 'p_know', label: '지식 관리', kind: 'page', children: [] },
  { id: 'p_klocal', label: '지식 관리 · Local', kind: 'page', children: AGENTS.map(a => ({ id: a.id, label: a.name, kind: 'file' })) }] }];

// fetch 감싸기(init script): 채팅 스트림 요청 본문은 __streamReqs 에, 응답은 곧바로 done / chat streams record bodies and answer done at once
function pageHooks(init) {
  try {
    if (!sessionStorage.getItem('__rsInit')) {
      sessionStorage.setItem('__rsInit', '1');
      localStorage.removeItem('ai365_rs_coach_done');
      if (init.lang) localStorage.setItem('ai365_lang', init.lang);
      if (init.coachDone) localStorage.setItem('ai365_rs_coach_done', '1');
    }
  } catch (e) { /* noop */ }
  if (init.blockStorage) {
    const boom = function () { throw new Error('storage blocked'); };
    Storage.prototype.getItem = boom; Storage.prototype.setItem = boom;
  }
  const orig = window.fetch.bind(window);
  window.__streamReqs = [];
  window.fetch = function (url, opts) {
    const u = String(url);
    if (/\/api\/chats\/[^/]+\/stream$/.test(u)) {
      window.__streamReqs.push({ url: u, body: opts && opts.body ? JSON.parse(opts.body) : null });
      const body = 'data: ' + JSON.stringify({ type: 'done', message_id: 'm1' }) + '\n\n';
      return Promise.resolve(new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }));
    }
    return orig(url, opts);
  };
}

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

async function app(t, o) {
  o = o || {};
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await ctx.newPage();
  const errors = [], reqs = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => d.dismiss());
  t.after(async () => { await ctx.close(); assert.deepEqual(errors, []); });
  await page.addInitScript(pageHooks, { lang: o.lang || '', coachDone: o.coachDone !== false, blockStorage: !!o.blockStorage });
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), p = decodeURIComponent(url.pathname), method = req.method();
    const json = (obj, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(obj) });
    if (url.origin !== ORIGIN) return route.abort();
    if (p === '/') return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: o.kst ? HTML_KST : HTML });
    if (p === '/static/kst.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: KST });
    if (p === '/static/adapter.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: ADAPTER });
    if (p === '/static/resource_select.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: MODULE });
    if (p.startsWith('/api/')) reqs.push(method + ' ' + p + url.search);
    if (p === '/api/access/bootstrap') return json({ pvtree: PVTREE, workspaces: WS, groups: [], members: [], teams: [] });
    if (p === '/api/knowledge-agents' && method === 'GET') return json({ agents: o.agents || AGENTS, super: true, can_register: true });
    const fo = /^\/api\/knowledge-agents\/([^/]+)\/folders$/.exec(p);
    if (fo) return json({ folders: FOLDERS[fo[1]] || [] });
    if (p === '/api/chats' && method === 'GET') return json([]);
    if (p === '/api/chats' && method === 'POST') return json({ id: 'c_rs1', title: '리소스 시험' });
    if (/^\/api\/chats\/[^/]+\/messages$/.test(p)) return json([]);
    if (p === '/api/health') return json({ ok: true });
    if (p.startsWith('/api/')) return json({ detail: 'stub' }, 404);
    return route.abort();
  });
  await page.goto(ORIGIN + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.AI365_RS && Array.isArray(window.AI365_LOCAL_AGENTS) && (window.AI365_WORKSPACES || [])[0]
    && window.AI365_WORKSPACES[0].bi && window.AI365_WORKSPACES[0].bi[0] && !!window.AI365_WORKSPACES[0].bi[0].file, null, { timeout: 15000 });
  return { page, reqs, errors };
}
const H = (page, expr) => page.evaluate(expr);
async function homeInternal(page) {   // 홈 범위 알약 자동 → 사내 / the home scope pill Auto → Internal
  await page.click('.hero .composer .composer-row .pill-btn:not([data-agentpill])');
  await page.waitForSelector('#homeAgentPill', { state: 'visible' });
}
async function openDialog(page, sel) {
  await page.click(sel || '#homeAgentPill');
  await page.waitForSelector('#ai365RsOv:not([hidden])');
}
const isOpen = page => page.evaluate(() => { const o = document.getElementById('ai365RsOv'); return !!o && !o.hidden; });
const secOpen = (page, sk) => page.click('[data-rs-toggle="' + sk + '"]');
const checked = (page, sel) => page.$eval(sel, el => el.checked);
const state = page => page.evaluate(() => ({ agents: AI365_SMF_HOOKS.agents(), files: AI365_SMF_HOOKS.files(), local: AI365_RS.local(),
  label: document.getElementById('homeAgentPill').firstChild.textContent.trim(),
  active: [...document.querySelectorAll('[data-agentpill]')].map(p => p.classList.contains('agp-active')) }));
async function pickLocal(page, sel) {   // Local 에서 본사 에이전트만 고르고 반영 / choose the HQ agent in Local and apply
  await openDialog(page, sel);
  await secOpen(page, 'klocal');
  await page.waitForSelector('[data-rs-local="' + HQ + '"]');
  await page.check('[data-rs-local="' + HQ + '"]');
  await page.click('[data-rs-done]');
}
const focusIn = page => page.evaluate(() => {
  const a = document.activeElement, c = document.querySelector('.ai365-rs-card');
  return { inside: !!c && c.contains(a), card: a === c, close: !!a && a.matches('[data-rs-close]'), cancel: !!a && a.matches('[data-rs-cancel]'),
    done: !!a && a.matches('[data-rs-done]'), locked: !!a && !!a.closest('.ai365-rs-secwrap.locked') };
});

test('a chip click opens the Dev dialog at once: no #agentMenu, 960 frame, five collapsed sections in order, Done disabled', async t => {
  const { page } = await app(t);
  await homeInternal(page);
  await openDialog(page);
  assert.equal(await page.$eval('#agentMenu', m => m.classList.contains('show')), false);
  assert.equal(await page.textContent('#ai365RsTitle'), '리소스 선택');
  assert.equal(await page.textContent('#ai365RsDesc'), 'AI가 참고할 폴더·파일을 선택하세요');
  // 제목 = 20/28 700(Dev 전역 h1 bold 가 font-semibold 를 이긴다), 구획 이름 = 600 / the title renders 700 as in Dev, section names 600
  assert.deepEqual(await page.$eval('#ai365RsTitle', el => { const s = getComputedStyle(el); return [s.fontSize, s.lineHeight, s.fontWeight]; }),
    ['20px', '28px', '700']);
  assert.equal(await page.$eval('[data-rs-sec="kpub"] .ai365-rs-ttin', el => getComputedStyle(el).fontWeight), '600');
  assert.deepEqual(await page.$$eval('.ai365-rs-foot button', bs => bs.map(b => [b.textContent, b.disabled])), [['취소', false], ['선택 완료', true]]);
  const card = await page.$eval('.ai365-rs-card', el => { const s = getComputedStyle(el); return [s.maxWidth, s.borderTopLeftRadius, el.getBoundingClientRect().width]; });
  assert.deepEqual(card.slice(0, 2), ['960px', '16px']);
  assert.equal(Math.round(card[2]), 960);
  assert.equal(await page.$eval('#ai365RsOv', el => getComputedStyle(el).backgroundColor), 'rgba(0, 0, 0, 0.5)');
  assert.deepEqual(await page.$$eval('[data-rs-sec]', els => els.map(e => e.dataset.rsSec)), ['kpub', 'klocal', 'data', 'groupware', 'work']);
  assert.deepEqual(await page.$$eval('[data-rs-sec] .ai365-rs-ttin', els => els.map(e => e.textContent)),
    ['지식 관리Public', '지식 관리Local', '데이터 분석', '그룹웨어', '업무 자동화']);
  assert.deepEqual(await page.$$eval('.ai365-rs-secbody', els => els.map(e => e.hidden)), [true, true, true, true, true]);
  assert.deepEqual(await page.$$eval('[data-rs-sec] .ai365-rs-sec', els => els.map(e => getComputedStyle(e).borderTopLeftRadius)), ['16px', '16px', '16px', '16px', '16px']);
  // 메뉴로 열던 스마트 파일 모달도 열리지 않는다 / the old smart-file modal stays closed too
  assert.equal(await page.$eval('#smartFileOv', el => el.classList.contains('open')), false);
});

test('sections expand and collapse; the knowledge tree has LV badges and file counts; select all checks every row and lights the header', async t => {
  const { page } = await app(t);
  await homeInternal(page);
  await openDialog(page);
  await secOpen(page, 'kpub');
  assert.equal(await page.$eval('[data-rs-sec="kpub"] .ai365-rs-secbody', el => el.hidden), false);
  assert.equal(await page.$eval('[data-rs-toggle="kpub"]', el => el.getAttribute('aria-expanded')), 'true');
  const top = await page.$$eval('[data-rs-sec="kpub"] .ai365-rs-tree > .ai365-rs-fnode > .ai365-rs-frow', rows => rows.map(r =>
    [r.querySelector('.ai365-rs-lv').textContent, r.querySelector('.ai365-rs-fname').textContent, r.querySelector('.ai365-rs-fcnt').textContent]));
  assert.deepEqual(top, [['LV.1', '인사 업무영역', '0'], ['LV.1', '재무 업무영역', '1']]);
  // 폴더는 기본 접힘, 캐럿으로 펼친다(파일이 하위 폴더보다 먼저) / folders start collapsed; files come before subfolders
  await page.click('[data-rs-caret="kn:k_fin"]');
  assert.deepEqual(await page.$$eval('[data-rs-sec="kpub"] [data-rs-row]', rs => rs.map(r => r.dataset.rsRow)),
    ['kn:k_hr', 'kn:k_fin', 'knf:k_fin|재무_업무_개요.docx', 'kn:k_settle']);
  await page.check('[data-rs-secall="kpub"]');
  assert.equal(await page.$eval('[data-rs-sec="kpub"] .ai365-rs-sechead', el => el.classList.contains('sel')), true);
  assert.equal(await page.$eval('[data-rs-sec="kpub"] .ai365-rs-sechead', el => getComputedStyle(el).backgroundColor), 'rgb(231, 235, 246)');
  assert.deepEqual(await page.$$eval('[data-rs-sec="kpub"] [data-rs-check]', els => els.every(e => e.checked)), true);
  assert.equal(await page.isDisabled('[data-rs-done]'), false);
  // 파일 하나를 끄면 조상 폴더와 전체 선택이 함께 꺼진다(형제는 그대로) / unchecking one file clears its ancestors and select-all, siblings stay
  await page.uncheck('[data-rs-check="knf:k_fin|재무_업무_개요.docx"]');
  assert.deepEqual(await Promise.all(['kn:k_fin', 'kn:k_settle', 'kn:k_hr'].map(k => checked(page, '[data-rs-check="' + k + '"]'))), [false, true, true]);
  assert.equal(await checked(page, '[data-rs-secall="kpub"]'), false);
  await secOpen(page, 'kpub');
  assert.equal(await page.$eval('[data-rs-sec="kpub"] .ai365-rs-secbody', el => el.hidden), true);
});

test('Local is exclusive: an agent locks and clears the other four sections; unchecking unlocks them without restoring', async t => {
  const { page } = await app(t);
  await homeInternal(page);
  await openDialog(page);
  await secOpen(page, 'data');
  await page.check('[data-rs-secall="data"]');
  await secOpen(page, 'klocal');
  await page.waitForSelector('[data-rs-local="' + HQ + '"]');
  assert.deepEqual(await page.$$eval('[data-rs-sec="klocal"] .ai365-rs-lroot', rs => rs.map(r => r.textContent)),
    ['Local 1본사 로컬 에이전트', 'Local 2연구소 지식 에이전트']);   // 사용 중지 에이전트는 없다 / disabled agents are left out
  await page.waitForSelector('[data-rs-sec="klocal"] .ai365-rs-frow.ro');
  assert.deepEqual(await page.$$eval('[data-rs-sec="klocal"] .ai365-rs-frow.ro', rs => rs.map(r => r.textContent)), ['LV.1경영 규정']);
  await page.click('[data-rs-caret="lf:' + HQ + '/f1"]');
  assert.deepEqual(await page.$$eval('[data-rs-sec="klocal"] .ai365-rs-frow.ro', rs => rs.map(r => r.textContent)), ['LV.1경영 규정', 'LV.2보안 정책']);
  await page.check('[data-rs-local="' + HQ + '"]');
  const locks = await page.$$eval('[data-rs-sec]', els => els.map(e => [e.dataset.rsSec, e.classList.contains('locked'), e.hasAttribute('inert'),
    getComputedStyle(e).opacity, getComputedStyle(e).filter]));
  assert.deepEqual(locks, [['kpub', true, true, '0.4', 'grayscale(1)'], ['klocal', false, false, '1', 'none'], ['data', true, true, '0.4', 'grayscale(1)'],
    ['groupware', true, true, '0.4', 'grayscale(1)'], ['work', true, true, '0.4', 'grayscale(1)']]);
  assert.equal(await checked(page, '[data-rs-secall="data"]'), false);   // 데이터 선택은 지워졌다 / the data choice was cleared
  assert.equal(await page.isDisabled('[data-rs-done]'), false);
  await page.uncheck('[data-rs-local="' + HQ + '"]');
  assert.deepEqual(await page.$$eval('[data-rs-sec]', els => els.map(e => e.classList.contains('locked'))), [false, false, false, false, false]);
  assert.equal(await checked(page, '[data-rs-secall="data"]'), false);   // 되살리지 않는다(Dev 와 같다) / not restored (as in Dev)
  assert.equal(await page.isDisabled('[data-rs-done]'), true);
  // 전체 선택 = 에이전트 전부 / select all = every agent
  await page.check('[data-rs-secall="klocal"]');
  assert.deepEqual(await Promise.all([HQ, LAB].map(id => checked(page, '[data-rs-local="' + id + '"]'))), [true, true]);
});

test('Done applies through the hooks (routing keys, scope, chip label, agp-active); Cancel, X, Esc and an outside click restore', async t => {
  const { page } = await app(t);
  await homeInternal(page);
  await openDialog(page);
  await secOpen(page, 'data');
  await page.check('[data-rs-secall="data"]');
  await page.click('[data-rs-done]');
  assert.equal(await isOpen(page), false);
  let s = await state(page);
  assert.deepEqual(s.agents, ['data']);
  assert.equal(s.label, '데이터 분석');
  assert.ok(s.active.every(Boolean), JSON.stringify(s.active));
  const scope = await H(page, () => AI365_SMF_HOOKS.scope());
  assert.deepEqual([scope.data_tables.slice().sort(), scope.data_bi.slice().sort()], [['finance_expenses', 'sales_branch_monthly'], ['cash.pbix', 'pl_monthly.pbix']]);
  assert.deepEqual(await H(page, () => AI365_COMPOSER_AGENTS_RAW()), ['data']);
  const before = JSON.stringify(s);
  for (const how of ['cancel', 'x', 'esc', 'outside']) {
    await openDialog(page);
    assert.equal(await checked(page, '[data-rs-secall="data"]'), true);   // 지금 선택이 미리 켜져 있다 / the current choice comes pre-checked
    await secOpen(page, 'groupware');
    await page.check('[data-rs-check="gw:agent"]');
    await secOpen(page, 'data');
    await page.uncheck('[data-rs-secall="data"]');
    if (how === 'cancel') await page.click('[data-rs-cancel]');
    else if (how === 'x') await page.click('[data-rs-close]');
    else if (how === 'esc') await page.keyboard.press('Escape');
    else await page.mouse.click(8, 8);
    assert.equal(await isOpen(page), false, how);
    assert.equal(JSON.stringify(await state(page)), before, how);
  }
  // 카드 안에서 누르고 바깥에서 떼면 닫지 않는다 / a press inside the card released outside does not close
  await openDialog(page);
  const box = await page.$eval('.ai365-rs-title', el => { const r = el.getBoundingClientRect(); return { x: r.left + 4, y: r.top + 4 }; });
  await page.mouse.move(box.x, box.y); await page.mouse.down(); await page.mouse.move(6, 6); await page.mouse.up();
  assert.equal(await isOpen(page), true);
  await page.click('[data-rs-cancel]');
  // 분야를 바꾸는 반영: 그룹웨어 + 업무 자동화 / an apply that changes domains: groupware + work automation
  await openDialog(page);
  await secOpen(page, 'data'); await page.uncheck('[data-rs-secall="data"]');
  await secOpen(page, 'groupware'); await page.check('[data-rs-check="gw:agent"]');
  await secOpen(page, 'work'); await page.check('[data-rs-check="work:edu"]');
  assert.deepEqual(await page.$$eval('[data-rs-sec="work"] .ai365-rs-arow', rs => rs.map(r => [r.textContent, r.classList.contains('on')])),
    [['M코스메틱 이메일 에이전트', false], ['교육 에이전트', true]]);
  await page.click('[data-rs-done]');
  s = await state(page);
  assert.deepEqual([s.agents, s.files.slice().sort()], [['groupware', 'work'], ['gw:agent', 'work:edu']]);
  assert.equal(s.label, '그룹웨어, 업무 자동화');
  assert.deepEqual(await H(page, () => AI365_COMPOSER_AGENTS_RAW()), ['work']);   // 라우팅 계약 그대로(그룹웨어는 gw:agent 로) / routing contract unchanged
  // 모두 풀면 [선택 완료]가 살아 있어 선택을 해제한다(처음부터 빈 상태에서는 비활성 그대로) / unchecking everything keeps Done enabled to clear the choice
  await openDialog(page);
  await secOpen(page, 'groupware'); await page.uncheck('[data-rs-check="gw:agent"]');
  await secOpen(page, 'work'); await page.uncheck('[data-rs-check="work:edu"]');
  assert.equal(await page.$eval('[data-rs-done]', b => b.disabled), false);
  await page.click('[data-rs-done]');
  s = await state(page);
  assert.deepEqual([s.agents, s.files], [[], []]);
  assert.equal(s.label, '리소스 센터');
  assert.ok(s.active.every(a => !a), JSON.stringify(s.active));
  await openDialog(page);
  assert.equal(await page.$eval('[data-rs-done]', b => b.disabled), true);
  await page.click('[data-rs-cancel]');
});

test('BI follows the current hooks rule: several dashboards stay checked (multi-select since 2026-08-31)', async t => {
  const { page } = await app(t);
  await homeInternal(page);
  await openDialog(page);
  await secOpen(page, 'data');
  await page.click('[data-rs-caret="ws:ws_fin"]');
  await page.click('[data-rs-caret="ws:ws_fin:bi"]');
  assert.deepEqual(await page.$$eval('[data-rs-sec="data"] .ai365-rs-drow', rs => rs.map(r => r.textContent)),
    ['LV.1재무 그룹', 'LV.2DB', 'LV.2BI', 'BI월간 손익 대시보드', 'BI자금 현황 모니터링', 'LV.2CSV']);
  await page.check('[data-rs-check="wsi:ws_fin:bi:pl_monthly.pbix"]');
  await page.check('[data-rs-check="wsi:ws_fin:bi:cash.pbix"]');
  assert.deepEqual(await Promise.all(['wsi:ws_fin:bi:pl_monthly.pbix', 'wsi:ws_fin:bi:cash.pbix', 'ws:ws_fin:bi', 'ws:ws_fin']
    .map(k => checked(page, '[data-rs-check="' + k + '"]'))), [true, true, true, false]);   // 버킷은 두 항목이 다 켜져 켜진다 / the bucket lights once both are on
  assert.equal(await page.$eval('[data-rs-row="wsi:ws_fin:bi:cash.pbix"] .ai365-rs-type', el => [getComputedStyle(el).color, getComputedStyle(el).backgroundColor].join()), 'rgb(255, 168, 61),rgb(255, 250, 245)');
  await page.click('[data-rs-done]');
  const scope = await H(page, () => AI365_SMF_HOOKS.scope());
  assert.deepEqual([scope.data_bi.slice().sort(), scope.data_tables], [['cash.pbix', 'pl_monthly.pbix'], []]);
});

test('the Local choice reaches the stream as scope_files.local_agents, round-trips stash/restore and yields to a Public pick', async t => {
  const { page } = await app(t);
  await homeInternal(page);
  await openDialog(page);
  await secOpen(page, 'klocal');
  await page.check('[data-rs-local="' + HQ + '"]');
  await page.click('[data-rs-done]');
  let s = await state(page);
  assert.deepEqual([s.agents, s.files, s.local, s.label], [['knowledge'], ['local:' + HQ], [HQ], '지식 관리']);
  assert.deepEqual(await H(page, () => AI365_SMF_HOOKS.scope()), { knowledge_files: [], data_tables: [], data_bi: [], work: false });   // H.scope() 는 그대로(예약 저장 422 방지) / unchanged
  await page.fill('#homeInput', '비밀번호 변경 주기는?');
  await page.press('#homeInput', 'Enter');
  await page.waitForFunction(() => window.__streamReqs.length === 1);
  const body = await H(page, () => window.__streamReqs[0].body);
  assert.deepEqual([body.scope, body.agents, body.scope_files], ['사내', ['knowledge'],
    { knowledge_files: [], data_tables: [], data_bi: [], work: false, local_agents: [HQ] }]);
  // 채팅 입력 카드 칩도 같은 대화 상자 · 같은 상태 / the chat composer chip opens the same dialog with the same state
  await page.waitForSelector('#agentPill', { state: 'visible' });
  await openDialog(page, '#agentPill');
  await secOpen(page, 'klocal');
  await page.waitForSelector('[data-rs-local="' + HQ + '"]');
  assert.equal(await checked(page, '[data-rs-local="' + HQ + '"]'), true);
  assert.equal(await page.$eval('[data-rs-sec="kpub"]', el => el.hasAttribute('inert')), true);
  await page.keyboard.press('Escape');
  // 예약 창 · 예약 페이지의 스태시/복원 왕복 / the stash/restore round trip of the schedule dialog and page
  const trip = await H(page, () => {
    const Hk = AI365_SMF_HOOKS, st = { agents: Hk.agents(), files: Hk.files() };
    Hk.setAgents([]); Hk.setFiles([]);
    const cleared = AI365_RS.local();
    Hk.setAgents(st.agents); Hk.setFiles(st.files);
    return { cleared, restored: AI365_RS.local(), label: document.getElementById('agentPill').firstChild.textContent.trim() };
  });
  assert.deepEqual(trip, { cleared: [], restored: [HQ], label: '지식 관리' });
  // Public 을 고르면 로컬은 꺼진다(배타) → 전송에 local_agents 없음 / a Public pick turns local off, no local_agents in the next send
  const after = await H(page, () => {
    AI365_SMF_HOOKS.setFiles(['kn:k_fin']);
    return { local: AI365_RS.local(), snap: ai365SelectionSnapshot({ scope: '사내' }).scopeFiles };
  });
  assert.deepEqual(after.local, []);
  assert.equal('local_agents' in after.snap, false);
  assert.deepEqual(after.snap.knowledge_files, ['재무_업무_개요.docx', '2025_연간_결산보고서.xlsx']);
});

test('the schedules page opens the same dialog through openMenu (and its own chip) with the Local section locked', async t => {
  const { page } = await app(t);
  await page.evaluate(() => {
    const wrap = document.createElement('div');
    wrap.className = 'composer ai365-sd-composer';
    wrap.innerHTML = '<button type="button" class="pill-btn" id="ai365SdAgent" data-agentpill>리소스 센터<svg width="12" height="12"></svg></button>';
    document.body.appendChild(wrap);
    window.AI365_SMF_HOOKS.openMenu(document.getElementById('ai365SdAgent'));
  });
  assert.equal(await isOpen(page), true);
  assert.equal(await page.$eval('#agentMenu', m => m.classList.contains('show')), false);
  const lock = await page.$eval('[data-rs-sec="klocal"]', el => [el.classList.contains('locked'), el.hasAttribute('inert'), el.title]);
  assert.deepEqual(lock, [true, true, '예약 작업에서는 로컬 지식 에이전트를 쓸 수 없습니다']);
  assert.equal(await page.$eval('[data-rs-sec="kpub"]', el => el.classList.contains('locked')), false);
  await page.keyboard.press('Escape');
  assert.equal(await isOpen(page), false);
  await page.click('#ai365SdAgent');   // 캡처 단계 가로채기 / taken in the capture phase
  assert.equal(await isOpen(page), true);
  await page.evaluate(() => window.AI365_SMF_HOOKS.closeMenu());   // closeMenu 도 대화 상자를 닫는다 / closeMenu closes the dialog too
  assert.equal(await isOpen(page), false);
});

test('the chip look: 700 text, the Resource Center icon at 21 in a 24 box, no chevron, Dev active colours', async t => {
  const { page } = await app(t);
  await homeInternal(page);
  const look = await page.$eval('#homeAgentPill', el => {
    const s = getComputedStyle(el), b = getComputedStyle(el, '::before');
    return { weight: s.fontWeight, before: [b.width, b.height, b.backgroundSize, /data:image\/svg\+xml/.test(b.backgroundImage) && /%2321242C/i.test(b.backgroundImage)],
      chev: [...el.querySelectorAll('svg')].map(v => getComputedStyle(v).display) };
  });
  assert.deepEqual(look, { weight: '700', before: ['24px', '24px', '21px 21px', true], chev: ['none'] });
  await page.evaluate(() => { AI365_SMF_HOOKS.setAgents(['data']); });
  // 알약에는 바탕 · 글자색 전환(0.13s)이 걸려 있어 끝난 값을 기다린다 / the pill transitions background and colour, so wait for the end value
  await page.waitForFunction(() => getComputedStyle(document.getElementById('homeAgentPill')).backgroundColor === 'rgb(242, 246, 255)', null, { timeout: 3000 }).catch(() => {});
  await page.waitForTimeout(250);
  const active = await page.$eval('#homeAgentPill', el => {
    const s = getComputedStyle(el), b = getComputedStyle(el, '::before');
    return [s.backgroundColor, s.borderTopColor, s.color, /%234450CE/i.test(b.backgroundImage)];
  });
  assert.deepEqual(active, ['rgb(242, 246, 255)', 'rgb(204, 218, 255)', 'rgb(68, 80, 206)', true]);
  await page.hover('#homeAgentPill');
  await page.waitForTimeout(250);
  assert.equal(await page.$eval('#homeAgentPill', el => getComputedStyle(el).backgroundColor), 'rgb(228, 237, 255)');
});

test('the home coach tooltip shows once under the chip (Internal, nothing chosen) and one chip click hides it for good', async t => {
  const { page } = await app(t, { coachDone: false });
  const shown = () => page.evaluate(() => { const c = document.getElementById('ai365RsCoach'); return !!c && c.classList.contains('show'); });
  await page.waitForTimeout(100);
  assert.equal(await shown(), false);   // 자동 = 칩이 없다 / Auto has no chip
  await homeInternal(page);
  await page.waitForSelector('#ai365RsCoach.show');
  const geo = await page.evaluate(() => {
    const c = document.getElementById('ai365RsCoach'), p = document.getElementById('homeAgentPill');
    const cr = c.getBoundingClientRect(), pr = p.getBoundingClientRect(), s = getComputedStyle(c);
    return { text: c.textContent, gapOk: cr.top >= pr.bottom + 5 && cr.top <= pr.bottom + 14, centre: Math.abs((cr.left + cr.width / 2) - (pr.left + pr.width / 2)) <= 1.5,
      look: [s.backgroundColor, s.color, s.fontSize, s.borderTopLeftRadius, s.paddingTop, s.paddingLeft], tail: getComputedStyle(c, '::before').borderBottomColor };
  });
  assert.deepEqual(geo, { text: '리소스를 세부적으로 선택해보세요', gapOk: true, centre: true,
    look: ['rgb(38, 41, 49)', 'rgb(255, 255, 255)', '12px', '4px', '4px', '8px'], tail: 'rgb(38, 41, 49)' });
  // 선택이 생기면 숨고, 비면 다시 / hidden while something is chosen, back when empty
  await page.evaluate(() => AI365_SMF_HOOKS.setAgents(['data']));
  await page.waitForFunction(() => !document.getElementById('ai365RsCoach').classList.contains('show'));
  await page.evaluate(() => AI365_SMF_HOOKS.setAgents([]));
  await page.waitForSelector('#ai365RsCoach.show');
  await openDialog(page);
  assert.equal(await shown(), false);
  assert.equal(await page.evaluate(() => localStorage.getItem('ai365_rs_coach_done')), '1');
  await page.click('[data-rs-cancel]');
  await page.waitForTimeout(80);
  assert.equal(await shown(), false);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.AI365_RS);
  await homeInternal(page);
  await page.waitForTimeout(80);
  assert.equal(await shown(), false);   // 다시 열어도 안 뜬다 / gone after a reload too
});

test('with storage blocked the coach still works and is remembered in the tab', async t => {
  const { page } = await app(t, { coachDone: false, blockStorage: true });
  await homeInternal(page);
  await page.waitForSelector('#ai365RsCoach.show');
  await openDialog(page);
  await page.click('[data-rs-close]');
  await page.waitForTimeout(80);
  assert.equal(await page.evaluate(() => document.getElementById('ai365RsCoach').classList.contains('show')), false);
});

test('EN labels follow the Dev dictionary and a language switch repaints the open dialog', async t => {
  const { page } = await app(t, { lang: 'en', coachDone: false });
  await homeInternal(page);
  await page.waitForSelector('#ai365RsCoach.show');
  assert.equal(await page.textContent('#ai365RsCoach'), 'Select resources in detail');
  const chipText = () => page.evaluate(() => document.getElementById('homeAgentPill').firstChild.textContent.trim());
  await page.waitForFunction(() => document.getElementById('homeAgentPill').firstChild.textContent.trim() === 'Resource Center');   // Dev menu.2
  // 칩 라벨도 영어(Dev 사전) / the chip label is English too (Dev dictionary)
  await openDialog(page);
  await secOpen(page, 'groupware');
  await page.check('[data-rs-secall="groupware"]');
  await page.click('[data-rs-done]');
  await page.waitForFunction(() => document.getElementById('homeAgentPill').firstChild.textContent.trim() === 'Groupware');
  await page.evaluate(() => AI365_SMF_HOOKS.setAgents(['knowledge', 'data', 'work']));
  await page.waitForFunction(() => document.getElementById('homeAgentPill').firstChild.textContent.trim() === 'Knowledge Management, Data Analysis +1');
  await page.evaluate(() => { AI365_SMF_HOOKS.setAgents([]); AI365_SMF_HOOKS.setFiles([]); });
  assert.equal(await page.evaluate(() => new Promise(r => requestAnimationFrame(() => r(document.getElementById('homeAgentPill').firstChild.textContent.trim())))), 'Resource Center');
  await openDialog(page);
  assert.equal(await page.textContent('#ai365RsTitle'), 'Select Resources');
  assert.equal(await page.textContent('#ai365RsDesc'), 'Select the folders/files for AI to reference');
  assert.deepEqual(await page.$$eval('.ai365-rs-foot button', bs => bs.map(b => b.textContent)), ['Cancel', 'Done']);
  assert.equal(await page.getAttribute('[data-rs-close]', 'aria-label'), 'Close');
  assert.deepEqual(await page.$$eval('[data-rs-sec] .ai365-rs-ttin', els => els.map(e => e.textContent)),
    ['Knowledge ManagementPublic', 'Knowledge ManagementLocal', 'Data Analysis', 'Groupware', 'Work Automation']);
  await secOpen(page, 'groupware');
  await secOpen(page, 'work');
  assert.deepEqual(await page.$$eval('[data-rs-sec="groupware"] .ai365-rs-arow, [data-rs-sec="work"] .ai365-rs-arow', rs => rs.map(r => r.textContent)),
    ['Groupware Agent', 'M Cosmetic Email Agent', 'Education Agent']);
  // 덮개가 토글을 가리므로 요소 click() 으로 누른다(키보드 단축 같은 경로) / the overlay covers the toggle, so click it programmatically
  await page.evaluate(() => document.getElementById('ai365-lang-toggle').click());
  await page.waitForFunction(() => document.getElementById('ai365RsTitle').textContent === '리소스 선택');
  assert.deepEqual(await page.$$eval('.ai365-rs-foot button', bs => bs.map(b => b.textContent)), ['취소', '선택 완료']);
  assert.equal(await isOpen(page), true);
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => document.getElementById('homeAgentPill').firstChild.textContent.trim() === '리소스 센터');
  assert.equal(await chipText(), '리소스 센터');
});

// ── 2026-10-28 적대 검토 반영 / 2026-10-28 adversarial review ──
test('explicit domains (the groupware home mini composer preset) never carry the composer Local pick; the collection composer path keeps it', async t => {
  const { page } = await app(t);
  await homeInternal(page);
  await pickLocal(page);
  const snaps = await H(page, () => ({
    preset: ai365SelectionSnapshot({ scope: '사내', agents: ['knowledge'] }).scopeFiles,
    // 컬렉션 컴포저(cdSubmit)는 AI365_COMPOSER_AGENTS_RAW() 배열을 그대로 openBlankChat 에 넘긴다 / cdSubmit hands the RAW() array as is
    collection: ai365SelectionSnapshot(Object.assign({}, { scope: '사내', agents: AI365_COMPOSER_AGENTS_RAW(), coll: 'c1' }, { scope: '사내' })).scopeFiles,
    implicit: ai365SelectionSnapshot({ scope: '사내' }).scopeFiles,
    copied: ai365SelectionSnapshot({ scope: '사내', agents: AI365_COMPOSER_AGENTS_RAW().slice() }).scopeFiles,
    raw: AI365_COMPOSER_AGENTS_RAW()
  }));
  assert.equal('local_agents' in snaps.preset, false);
  assert.equal('local_agents' in snaps.copied, false);   // 컴포저가 돌려준 배열이 아니면 명시로 본다 / not the composer's array = explicit
  assert.deepEqual(snaps.collection.local_agents, [HQ]);
  assert.deepEqual(snaps.implicit.local_agents, [HQ]);
  assert.deepEqual(snaps.raw, ['knowledge']);              // 감싼 RAW 도 같은 키 / the wrapped RAW returns the same keys
  // 그룹웨어 홈 미니 입력(분야 = 지식 관리)으로 새 채팅: 첫 전송에 local_agents 없음 / a new chat from the mini composer sends none
  await H(page, () => ai365HomeAskStart('규정 질문', '사내', '지식 관리'));
  await page.waitForFunction(() => window.__streamReqs.length >= 1, null, { timeout: 5000 });
  const body = await H(page, () => window.__streamReqs[0].body);
  assert.deepEqual([body.scope, body.agents, 'local_agents' in body.scope_files], ['사내', ['knowledge'], false]);
  assert.deepEqual(await H(page, () => AI365_RS.local()), []);
});

// 컬렉션 컴포저와 같은 시작(openBlankChat 에 RAW() 배열 그대로): adapter openBlankChat 이 배열을 복사하게 바뀌면 여기서 걸린다
// The collection composer's start (the RAW() array straight into openBlankChat): fails here if adapter openBlankChat ever copies it
test('a new chat started with the composer RAW() array (the collection composer path) still sends the Local pick', async t => {
  const { page } = await app(t);
  await homeInternal(page);
  await pickLocal(page);
  await H(page, () => openBlankChat('규정 질문', { scope: '사내', agents: AI365_COMPOSER_AGENTS_RAW() }));
  await page.waitForFunction(() => window.__streamReqs.length >= 1, null, { timeout: 5000 });
  const body = await H(page, () => window.__streamReqs[0].body);
  assert.deepEqual([body.scope, body.agents, body.scope_files.local_agents], ['사내', ['knowledge'], [HQ]]);
});

test('Tab and Shift+Tab stay inside the aria-modal dialog, wrap at both ends and skip locked sections', async t => {
  const { page } = await app(t);
  await homeInternal(page);
  await openDialog(page);
  assert.equal((await focusIn(page)).card, true);          // 처음 포커스 = 카드 / the card has the first focus
  await page.keyboard.press('Shift+Tab');
  assert.equal((await focusIn(page)).cancel, true);        // 카드에서 뒤로 = 마지막(선택 완료는 비활성) / back from the card = the last (Done disabled)
  await page.keyboard.press('Tab');
  assert.equal((await focusIn(page)).close, true);         // 끝에서 앞으로 = 처음(X) / forward from the end = the first (X)
  await page.keyboard.press('Shift+Tab');
  assert.equal((await focusIn(page)).cancel, true);
  for (let i = 0; i < 30; i++) {
    await page.keyboard.press(i % 3 === 2 ? 'Shift+Tab' : 'Tab');
    assert.equal((await focusIn(page)).inside, true, 'key #' + (i + 1));
  }
  // Local 을 고르면 다른 구획은 잠기고(inert) 포커스가 들어가지 않는다, 선택 완료가 마지막이 된다 / locked sections are skipped, Done becomes the last
  await secOpen(page, 'klocal');
  await page.waitForSelector('[data-rs-local="' + HQ + '"]');
  await page.check('[data-rs-local="' + HQ + '"]');
  await page.focus('[data-rs-close]');
  let sawDone = false;
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press('Tab');
    const f = await focusIn(page);
    assert.equal(f.inside, true, 'locked key #' + (i + 1));
    assert.equal(f.locked, false, 'locked key #' + (i + 1));
    if (f.done) { sawDone = true; await page.keyboard.press('Tab'); assert.equal((await focusIn(page)).close, true); break; }
  }
  assert.equal(sawDone, true);
  await page.keyboard.press('Escape');
  assert.equal(await isOpen(page), false);
  assert.equal(await page.evaluate(() => document.activeElement && document.activeElement.id), 'homeAgentPill');   // 칩으로 돌아간다 / focus returns
});

test('opening the dialog closes other open popovers (the + attach menu) but never the schedule dialog it sits on', async t => {
  const { page } = await app(t, { kst: true });
  await homeInternal(page);
  await page.click('#homeAttBtn');
  assert.equal(await page.$eval('#cmpAttMenu', m => m.classList.contains('open')), true);
  await page.click('#homeAgentPill', { force: true });
  await page.waitForSelector('#ai365RsOv:not([hidden])');
  assert.equal(await page.$eval('#cmpAttMenu', m => m.classList.contains('open')), false);
  assert.equal(await page.$eval('#agentMenu', m => m.classList.contains('show')), false);
  await page.keyboard.press('Escape');
  assert.equal(await page.$eval('#cmpAttMenu', m => m.classList.contains('open')), false);
  // 예약 창 안의 칩: 리소스 선택은 그 위에 열리고 예약 창은 그대로(Esc 도 리소스 선택만 닫는다) / the schedule dialog stays
  await page.evaluate(() => { const ov = document.getElementById('cdSchedOv'); document.body.appendChild(ov); window.AI365_SCHED_CREATE({}); });
  await page.waitForSelector('#cdSchedOv.open');
  await page.click('#cdSchedScopeBtn');
  await page.waitForSelector('#cdSchedAgentPill', { state: 'visible' });
  await page.click('#cdSchedAgentPill');
  assert.equal(await isOpen(page), true);
  assert.equal(await page.$eval('#cdSchedOv', el => el.classList.contains('open')), true);
  await page.keyboard.press('Escape');
  assert.equal(await isOpen(page), false);
  assert.equal(await page.$eval('#cdSchedOv', el => el.classList.contains('open')), true);
  await page.click('#cdSchedCancel');
});

test('new chips are still painted after streamed nodes, with one scan per frame instead of one per added node', async t => {
  const { page } = await app(t, { lang: 'en' });
  await homeInternal(page);
  await page.waitForFunction(() => document.getElementById('homeAgentPill').firstChild.textContent.trim() === 'Resource Center');
  const r = await page.evaluate(async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const frame = () => new Promise(res => requestAnimationFrame(() => res()));
    const orig = Element.prototype.querySelector;
    let calls = 0;
    Element.prototype.querySelector = function (s) { if (s === '[data-agentpill]') calls++; return orig.call(this, s); };
    try {
      await frame();
      // 한 프레임 안에서 40번 다시 그린 답변(매번 앞 노드를 갈아 끼움) / an answer re-rendered 40 times within one frame
      for (let i = 0; i < 40; i++) { host.innerHTML = '<p>part ' + i + '</p><ul><li>a</li><li>b</li></ul>'; await Promise.resolve(); }
      await frame(); await frame();
      const streamed = calls;
      host.innerHTML = '<div><button type="button" class="pill-btn" data-agentpill>리소스 센터<svg width="12" height="12"></svg></button></div>';
      await frame(); await frame();
      const later = host.querySelector('[data-agentpill]').firstChild.textContent.trim();
      // 한 번에 많이 붙으면(200개 넘음) 모으지 않고 한 번 칠한다 / a big burst (over 200) paints once instead of collecting
      calls = 0;
      host.innerHTML = '<span></span>'.repeat(250) + '<button type="button" class="pill-btn" data-agentpill>리소스 센터</button>';
      await frame(); await frame();
      return { streamed, later, burst: host.querySelector('button[data-agentpill]').firstChild.textContent.trim(), burstCalls: calls };
    } finally {
      Element.prototype.querySelector = orig;
      host.remove();
    }
  });
  // 종전 = 다시 그릴 때마다 노드 2개씩(80회). 지금 = 그 프레임에 남은 노드만(마지막 그리기 2개 + 다른 화면 갱신 몇 개)
  // Formerly 2 per render (80 calls); now only the nodes left at the frame (the last render's 2 plus a few other screen updates)
  assert.ok(r.streamed <= 8, 'querySelector calls for the streamed nodes: ' + r.streamed);
  assert.equal(r.later, 'Resource Center');
  assert.equal(r.burst, 'Resource Center');
  assert.equal(r.burstCalls, 0, 'querySelector calls for the burst');
});
