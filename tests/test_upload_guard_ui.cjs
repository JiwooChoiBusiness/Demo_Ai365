// 실행: Playwright 가 NODE_PATH 에 있을 때 node --test tests/test_upload_guard_ui.cjs
// 업로드 검증 화면(2026-10-01) — 관리 센터 › 로컬 설정 메뉴(지식 에이전트 | 업로드 검증, 슈퍼어드민만)와 리소스 센터 업로드 경고 창(일반 = 파일 업로드 제한,
// 슈퍼어드민 = 보안 정책 위반 확인 → [예, 업로드]). 목업 전체 + 어댑터를 가짜 원점에 올린 격리 브라우저, 네트워크는 전부 스텁.
// Run with Playwright on NODE_PATH: node --test tests/test_upload_guard_ui.cjs
// Upload validation screens (2026-10-01): the Admin Center Local settings menu (Knowledge agents | Upload validation, super admin only)
// and the Resource Center upload dialogs (users: Upload restricted; the super admin: Security policy violation → [Yes, upload]). The whole
// mockup and adapter on a fake origin in an isolated browser; every network call is stubbed.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const mockup = fs.readFileSync(path.join(__dirname, '../frontend/ai365-mockup.html'), 'utf8').replace(/\r\n/g, '\n');
const adapter = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8').replace(/\r\n/g, '\n');
const ORIGIN = 'http://ug.test';
const HTML = mockup.replace('</body>', '<script src="/static/adapter.js"></script></body>');
const SEED = [['개인정보', '개인정보 관련 문서'], ['주민등록번호', '개인 식별 정보'], ['계좌번호', '금융정보'], ['신용카드', '금융정보'], ['고객정보', '고객 관련 민감정보'],
  ['기밀', '회사 기밀정보'], ['대외비', '외부 공개 금지 문서'], ['인사정보', '임직원 관련 정보'], ['계약서', '계약 관련 민감문서'], ['재무정보', '재무 및 회계 정보']];
const MEMBER = { no: 7, name: '강수아', dept: '인사총무', grade: '사원', empno: 7, email: '' };
// 서버 카탈로그 모양의 작은 지식 트리(bootstrap.knowledge → applyResourceSync, 폴더 · 파일 node 포함) / a small catalog-shaped knowledge tree
const KNOWLEDGE = [{ id: 'k_hr', lv: 1, name: '인사 업무영역', node: 'f_hr', files: [{ name: '인사 규정.pdf', node: 'kf_hr1' }], children: [] }];
const MANAGER = { super: false, menus: { m_home: true, m_chat: true, m_res: true }, nodes: { p_know: 2, f_hr: 2, kf_hr1: 2 }, mgmt: { p_know: true }, read: { p_know: true } };
const field = (raw, name) => { const m = new RegExp('name="' + name + '"\\r?\\n\\r?\\n([^\\r\\n]*)').exec(raw || ''); return m ? m[1] : null; };
const fileName = raw => { const m = /filename="([^"]*)"/.exec(raw || ''); return m ? m[1] : null; };

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

async function app(t, opts) {
  const o = Object.assign({ check: null, upload: null, effective: {} }, opts || {});
  const srv = { enabled: true, keywords: SEED.map((k, i) => ({ id: 'ug_' + i, keyword: k[0], description: k[1], enabled: true })), seq: 100 };
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  t.after(() => page.close());
  const errors = [], calls = [], uploads = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), method = req.method(), p = url.pathname;
    const json = (obj, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(obj) });
    if (url.origin !== ORIGIN) return route.abort();
    if (p === '/') return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: HTML });
    if (p === '/static/adapter.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: adapter });
    if (p === '/api/access/bootstrap') return json({ pvtree: [], groups: [], members: [MEMBER], teams: [], knowledge: KNOWLEDGE });
    const eff = /^\/api\/access\/effective\/(\d+)$/.exec(p);
    if (eff) return json(o.effective[eff[1]] || { super: false, menus: {}, nodes: {}, mgmt: {}, read: {} });
    if (p === '/api/knowledge-agents' && method === 'GET') return json({ agents: [], super: true, can_register: true });
    if (p.indexOf('/api/upload-guard') === 0) {
      const body = /json/.test(req.headers()['content-type'] || '') ? JSON.parse(req.postData()) : null;
      const actor = body ? body.acting_user_id : (url.searchParams.get('acting_user_id') || field(req.postData(), 'acting_user_id') || '');
      calls.push({ method, path: p, body, actor });
      if (p === '/api/upload-guard/check') return json(Object.assign({ file: fileName(req.postData()) }, o.check(actor, fileName(req.postData()))));
      if (actor) return json({ detail: '슈퍼관리자 전용 기능입니다' }, 403);
      if (p === '/api/upload-guard' && method === 'GET') return json({ enabled: srv.enabled, keywords: srv.keywords, limits: { keyword: 40, description: 100 } });
      if (p === '/api/upload-guard/enabled') { srv.enabled = !!body.enabled; return json({ enabled: srv.enabled }); }
      if (p === '/api/upload-guard/keywords' && method === 'POST') {
        const row = { id: 'ug_' + (++srv.seq), keyword: body.keyword, description: body.description || '', enabled: true };
        srv.keywords.push(row); return json({ keyword: row });
      }
      const one = /^\/api\/upload-guard\/keywords\/([^/]+)$/.exec(p), k = one && srv.keywords.find(x => x.id === one[1]);
      if (k && method === 'DELETE') { srv.keywords = srv.keywords.filter(x => x !== k); return json({ ok: true }); }
      if (k && method === 'PATCH') { ['keyword', 'description', 'enabled'].forEach(f => { if (body[f] !== undefined && body[f] !== null) k[f] = body[f]; }); return json({ keyword: k }); }
      return json({ detail: '키워드를 찾을 수 없습니다' }, 404);
    }
    if (p === '/api/resources/knowledge/files' && method === 'POST') {
      const raw = req.postData(), up = { actor: field(raw, 'acting_user_id'), force: field(raw, 'force'), file: fileName(raw) };
      uploads.push(up);
      const r = o.upload(up);
      return json(r.body, r.status);
    }
    if (p === '/api/resources/knowledge/index-status') return json({ docs: uploads.map(u => u.file) });
    if (p.startsWith('/api/')) return json({ detail: 'stub' }, 404);
    return route.abort();
  });
  await page.goto(ORIGIN + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => typeof window.AI365_setActingUser === 'function' && typeof window.openDocMgr === 'function'
    && (window.AI365_KNOWLEDGE || [])[0] && window.AI365_KNOWLEDGE[0].node === 'f_hr', null, { timeout: 10000 });
  return { page, errors, calls, uploads, srv };
}
async function until(fn) { for (let i = 0; i < 300 && !(await fn()); i++) await new Promise(r => setTimeout(r, 50)); assert.ok(await fn()); }
const visible = (page, sel) => page.$eval(sel, el => !el.closest('[hidden]') && !!el.offsetParent).catch(() => false);
async function guardTab(page) {
  await page.evaluate(() => { document.getElementById('navPerm').click(); document.querySelector('[data-hubcard="llm"]').click(); });
  await page.click('#llmTabs [data-llmtab="guard"]');
  await page.waitForSelector('#ugList table tbody tr');
}
const rows = page => page.$$eval('#ugList tbody tr:not(.ug-editing)', trs => trs.map(tr => [tr.querySelector('td b').textContent, tr.cells[1].textContent, tr.querySelector('[data-ugon]').checked]));
async function actAs(page, no) {
  await page.evaluate(n => window.AI365_setActingUser(n), no);
  await page.waitForFunction(n => n === null ? !window.AI365_ACTING_USER : window.AI365_ACTING_USER && window.AI365_ACTING_USER.no === n, no);
}
/* 업로드 모달에 파일을 넣고 '검증 완료'까지 기다린 뒤 [업로드] / add files to the upload modal, wait for validation, then [Upload] */
async function uploadVia(page, opener, files) {
  await page.evaluate(sel => document.querySelector(sel).click(), opener);
  await page.waitForSelector('#rmUploadOv.open');
  await page.setInputFiles('#rmFileInput', files.map(name => ({ name, mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 test') })));
  await page.waitForFunction(n => document.querySelectorAll('#rmUpList .rm-up-status.ok').length === n, files.length);
  await page.click('#rmUploadConfirm');
}
async function dialog(page) {
  await page.waitForSelector('#ugdOv');
  return page.$eval('#ugdOv', ov => ({
    kind: ov.querySelector('.ugd-ic').classList.contains('warn') ? 'warn' : 'block',
    title: ov.querySelector('.ugd-tt').textContent,
    msg: [...ov.querySelectorAll('.ugd-msg span')].map(s => s.textContent),
    files: [...ov.querySelectorAll('.ugd-files span')].map(s => s.textContent),
    info: [...ov.querySelectorAll('.ugd-info dt')].map(dt => [dt.textContent, [...dt.nextElementSibling.querySelectorAll('.kw')].map(k => k.textContent)]),
    buttons: [...ov.querySelectorAll('.ugd-acts button')].map(b => b.textContent),
  }));
}

test('Local LLM & DB setting shows the Upload validation menu to the super admin only, with the switch, the ten keywords and the crumb', async t => {
  const { page, errors, calls } = await app(t);
  await page.evaluate(() => { document.getElementById('navPerm').click(); document.querySelector('[data-hubcard="llm"]').click(); });
  await page.waitForSelector('#llmTabs:not([hidden])');
  assert.deepEqual(await page.$$eval('#llmTabs [data-llmtab]', bs => bs.map(b => [b.textContent, b.classList.contains('active')])), [['로컬 에이전트', true], ['업로드 검증', false]]);
  assert.equal(await visible(page, '#llmCrumbTab'), false);
  await page.click('#llmTabs [data-llmtab="guard"]');
  await page.waitForSelector('#ugList table tbody tr');
  assert.equal(await visible(page, '#llmPaneAgents'), false);
  assert.equal(await page.textContent('#llmCrumbTab'), '업로드 검증');
  assert.equal(await page.$eval('#pgLlmScroll [data-llmsub="guard"]', el => el.hidden), false);
  assert.deepEqual(await page.$$eval('#llmPaneGuard .bl-card-tt > span:first-child', els => els.map(e => e.textContent)), ['업로드 검증 설정', '검증 키워드']);
  assert.deepEqual(await page.$eval('#ugEnabled', el => [el.checked, document.getElementById('ugEnabledLbl').textContent]), [true, 'ON']);
  assert.deepEqual(await page.$$eval('#ugList thead th', ths => ths.map(th => th.textContent)), ['키워드', '설명', '상태', '관리']);
  assert.deepEqual(await rows(page), SEED.map(k => [k[0], k[1], true]));
  assert.deepEqual(await page.$eval('#ugCnt', e => e.textContent), '10개');
  assert.equal(await page.textContent('#ugList .ug-foot span'), '총 10개');
  assert.equal(await page.$('#ugList .pg-pager'), null);   // 10개 = 한 쪽 / ten fit on one page
  assert.equal(await page.getAttribute('#ugSearch', 'placeholder'), '키워드 검색');
  assert.ok(await page.$('#llmPaneGuard .pg-search.pg-search-sm #ugSearch'));   // 다른 관리 화면과 같은 검색창 / the admin search box
  await page.click('#llmCrumbRoot');   // 경로의 '로컬 설정' = 지식 에이전트로 / the crumb goes back to agents
  assert.equal(await visible(page, '#llmPaneAgents'), true);
  assert.equal(await visible(page, '#llmPaneGuard'), false);
  // 일반 사용자 · 관리자: 메뉴도 목록 요청도 없다 / users and admins: no menu and no list request
  const before = calls.length;
  await actAs(page, 7);
  await page.evaluate(() => { document.getElementById('navPerm').click(); const c = document.querySelector('[data-hubcard="llm"]'); if (c) c.click(); });
  assert.equal(await page.$eval('#llmTabs', el => el.hidden), true);
  assert.equal(await page.$eval('#llmPaneGuard', el => el.hidden), true);
  assert.equal(calls.length, before);
  assert.deepEqual(errors, []);
});

test('keywords are added, searched, edited, switched, deleted and the Public switch is saved, all on the server', async t => {
  const { page, errors, calls, srv } = await app(t);
  await guardTab(page);
  // 추가: 새 줄에 바로 입력 · Enter = 저장 → 표 끝(2쪽)으로 / add: type in the new row, Enter saves, the view moves to the end (page 2)
  await page.click('#ugAdd');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'ugEdWord');
  await page.keyboard.type('Confidential');
  await page.fill('#ugEdDesc', '영문 기밀 표시');
  await page.press('#ugEdDesc', 'Enter');
  await page.waitForFunction(() => [...document.querySelectorAll('#ugList td b')].some(b => b.textContent === 'Confidential'));
  assert.deepEqual(calls.at(-1), { method: 'POST', path: '/api/upload-guard/keywords', body: { acting_user_id: '', keyword: 'Confidential', description: '영문 기밀 표시' }, actor: '' });
  assert.deepEqual(await rows(page), [['Confidential', '영문 기밀 표시', true]]);
  assert.deepEqual(await page.$$eval('#ugList .pg-pager [data-ugpg]', bs => bs.map(b => b.textContent || b.dataset.ugpg)), ['prev', '1', '2', 'next']);
  assert.equal(await page.textContent('#ugCnt'), '11개');
  // 검색: 설명으로도 걸러지고, 입력하는 동안 검색창 포커스가 남는다 / search: by description too, focus stays in the box
  await page.click('#ugSearch');
  await page.keyboard.type('금융');
  assert.deepEqual((await rows(page)).map(r => r[0]), ['계좌번호', '신용카드']);
  assert.equal(await page.evaluate(() => document.activeElement.id), 'ugSearch');
  assert.equal(await page.textContent('#ugList .ug-foot span'), '총 2개');
  await page.fill('#ugSearch', '없는말');
  assert.equal(await page.textContent('#ugList .llm-empty b'), '검색 결과가 없습니다.');
  await page.fill('#ugSearch', '');
  // 수정 / edit
  await page.click('#ugList [data-ugedit="ug_5"]');
  await page.fill('#ugEdDesc', '회사 기밀 문서');
  await page.click('#ugList [data-ugsave]');
  await page.waitForFunction(() => !document.querySelector('#ugList .ug-editing'));
  assert.deepEqual(calls.at(-1).body, { acting_user_id: '', keyword: '기밀', description: '회사 기밀 문서' });
  assert.equal(calls.at(-1).method + ' ' + calls.at(-1).path, 'PATCH /api/upload-guard/keywords/ug_5');
  // 사용 끄기 / switch one off
  await page.click('#ugList [data-ugon="ug_6"] + span');
  await page.waitForFunction(() => document.querySelector('#ugList tr[data-ugrow="ug_6"]').classList.contains('ug-off'));
  assert.deepEqual(calls.at(-1).body, { acting_user_id: '', enabled: false });
  // 삭제 = 확인 창 / delete asks first
  await page.click('#ugList [data-ugdel="ug_8"]');
  await page.waitForSelector('#klConfirmOv.open');
  assert.equal(await page.textContent('#klConfirmOv .kl-del-name'), '계약서');
  await page.click('#klConfirmOk');
  await page.waitForFunction(() => !document.querySelector('#ugList tr[data-ugrow="ug_8"]'));
  assert.equal(calls.at(-1).method + ' ' + calls.at(-1).path, 'DELETE /api/upload-guard/keywords/ug_8');
  assert.equal(srv.keywords.some(k => k.id === 'ug_8'), false);
  // Public 업로드 검증 사용 끄기 / turn Public validation off
  await page.click('#ugEnabled + span');
  await page.waitForFunction(() => document.getElementById('ugEnabledLbl').textContent === 'OFF');
  assert.deepEqual([calls.at(-1).method, calls.at(-1).path, calls.at(-1).body], ['PUT', '/api/upload-guard/enabled', { acting_user_id: '', enabled: false }]);
  assert.equal(srv.enabled, false);
  assert.deepEqual(errors, []);
});

test('the menu, the table and the counts read in English', async t => {
  const { page, errors } = await app(t);
  await guardTab(page);
  await page.evaluate(() => { localStorage.setItem('ai365_lang', 'en'); ai365ApplyLang('en'); });
  await page.waitForFunction(() => document.querySelector('#ugList .ug-foot span').textContent === '10 total');
  assert.deepEqual(await page.$$eval('#llmTabs [data-llmtab]', bs => bs.map(b => b.textContent)), ['Local agents', 'Upload validation']);
  assert.deepEqual(await page.$$eval('#llmPaneGuard .bl-card-tt > span:first-child', els => els.map(e => e.textContent)), ['Upload validation settings', 'Validation keywords']);
  assert.deepEqual(await page.$$eval('#ugList thead th', ths => ths.map(th => th.textContent)), ['Keyword', 'Description', 'Status', 'Manage']);
  assert.equal(await page.getAttribute('#ugSearch', 'placeholder'), 'Search keywords');
  assert.equal(await page.textContent('#ugAdd'), '+ Add keyword');
  assert.equal(await page.textContent('#ugCnt'), '10');
  assert.equal((await rows(page))[0][0], '개인정보');   // 키워드 · 설명은 번역하지 않는다 / keywords and descriptions stay as entered
  await page.evaluate(() => { localStorage.setItem('ai365_lang', 'ko'); ai365ApplyLang('ko'); });
  await page.waitForFunction(() => document.querySelector('#ugList .ug-foot span').textContent === '총 10개');
  assert.deepEqual(errors, []);
});

test('document management: a user is told the upload is restricted, the super admin sees keywords and may upload anyway', async t => {
  const hit = { keyword: '고객정보', description: '고객 관련 민감정보', where: ['파일명'] };
  const { page, errors, calls } = await app(t, { effective: { 7: MANAGER },
    check: (actor, name) => (/고객정보/.test(name) ? (actor ? { result: 'blocked' } : { result: 'warn', hits: [hit] }) : { result: 'ok' }) });
  await page.evaluate(() => { openResourceCenter(); window.openDocMgr(); });
  await page.waitForSelector('#docTree [data-docnode]');
  await page.click('#docTree [data-docnode]');
  const listed = () => page.$$eval('#docMgrScroll', els => els.map(e => e.textContent).join(' '));
  // 슈퍼어드민: 경고 → [아니요] = 올리지 않는다 / super admin: warning, [No] uploads nothing
  await uploadVia(page, '#docUploadBtn', ['분기 고객정보.pdf']);
  let d = await dialog(page);
  assert.deepEqual(d, { kind: 'warn', title: '보안 정책 위반 확인', msg: ['해당 문서가 보안 정책을 위반합니다.', '그래도 이 문서를 업로드하시겠습니까?'], files: [],
    info: [['대상 파일', ['분기 고객정보.pdf']], ['탐지 키워드', ['고객정보고객 관련 민감정보']], ['탐지 위치', ['파일명']]], buttons: ['아니요', '예, 업로드'] });
  assert.equal(await page.$eval('#ugdOv [data-ugd="no"]', b => b === document.activeElement), true);   // 기본 초점 = 아니요 / focus starts on No
  await page.click('#ugdOv [data-ugd="no"]');
  await until(async () => !(await page.$('#ugdOv')) && !(await page.$('#rmUploadOv.open')));
  assert.equal((await listed()).includes('분기 고객정보.pdf'), false);
  // 슈퍼어드민: [예, 업로드] = 올린다 / super admin: [Yes, upload] uploads
  await uploadVia(page, '#docUploadBtn', ['분기 고객정보.pdf', '회의록.pdf']);
  await dialog(page);
  await page.click('#ugdOv [data-ugd="yes"]');
  await until(async () => (await listed()).includes('분기 고객정보.pdf') && (await listed()).includes('회의록.pdf'));
  assert.deepEqual(calls.filter(c => c.path === '/api/upload-guard/check').map(c => c.actor), ['', '', '']);
  // 일반 사용자 · 관리자(그 폴더 관리): 파일 업로드 제한(키워드는 보이지 않는다) / users and admins (managing the folder): Upload restricted, no keywords shown
  await actAs(page, 7);
  await page.evaluate(() => { openResourceCenter(); window.openDocMgr(); });
  await page.waitForSelector('#docTree [data-docnode]');
  await page.click('#docTree [data-docnode]');
  await uploadVia(page, '#docUploadBtn', ['주간 고객정보.pdf']);
  d = await dialog(page);
  assert.deepEqual(d, { kind: 'block', title: '파일 업로드 제한', msg: ['보안에 문제가 있어 해당 문서를 업로드할 수 없습니다.', '업로드가 필요하면 관리자에게 문의해 주세요.'],
    files: ['주간 고객정보.pdf'], info: [], buttons: ['확인'] });
  await page.click('#ugdOv [data-ugd="ok"]');
  await until(async () => !(await page.$('#ugdOv')));
  assert.equal((await listed()).includes('주간 고객정보.pdf'), false);
  assert.equal(calls.filter(c => c.path === '/api/upload-guard/check').at(-1).actor, '7');
  assert.deepEqual(errors, []);
});

test('resource management: the server warns, the super admin confirms and the file is resent with force; blocked files are told together', async t => {
  const { page, errors, uploads } = await app(t, {
    upload: up => {
      if (/차단/.test(up.file)) return { status: 403, body: { detail: { code: 'upload_blocked', file: up.file } } };
      if (/경고/.test(up.file) && up.force !== '1') return { status: 409, body: { detail: { code: 'upload_warn', file: up.file, hits: [{ keyword: '대외비', description: '외부 공개 금지 문서', where: ['파일명', '문서 내용'] }] } } };
      return { status: 200, body: { ok: true, node: 'kf_t' + uploads.length, file: up.file } };
    } });
  await page.evaluate(() => { openResourceCenter(); document.getElementById('rcManageBtn').click(); });
  await page.waitForSelector('#rmTree [data-rmnode]');
  await page.click('#rmTree [data-rmnode]');
  await uploadVia(page, '#rmUploadBtn', ['차단 문서.pdf', '경고 대외비.pdf', '안내.pdf']);
  const d = await dialog(page);
  assert.equal(d.title, '보안 정책 위반 확인');
  assert.deepEqual(d.info, [['대상 파일', ['경고 대외비.pdf']], ['탐지 키워드', ['대외비외부 공개 금지 문서']], ['탐지 위치', ['파일명', '문서 내용']]]);
  await page.click('#ugdOv [data-ugd="yes"]');
  await page.waitForFunction(() => { const o = document.getElementById('ugdOv'); return o && o.querySelector('.ugd-ic.block'); });
  const b = await dialog(page);
  assert.deepEqual([b.title, b.files], ['파일 업로드 제한', ['차단 문서.pdf']]);   // 차단은 모아서 한 번 / blocks are reported once, together
  await page.click('#ugdOv [data-ugd="ok"]');
  await until(async () => !(await page.$('#rmUploadOv.open')));
  assert.deepEqual(uploads.map(u => [u.file, u.force]), [['차단 문서.pdf', null], ['경고 대외비.pdf', null], ['경고 대외비.pdf', '1'], ['안내.pdf', null]]);
  assert.deepEqual(errors, []);
});
