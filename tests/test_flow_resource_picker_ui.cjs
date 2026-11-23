// 실행: Playwright 가 NODE_PATH 에 있을 때 node --test tests/test_flow_resource_picker_ui.cjs
// 관리 센터 › 워크플로우 설정의 리소스 선택 팝업(2026-10-08 사용자 시안). 지식 관리 · 데이터 분석 · 그룹웨어 · 업무 자동화 작업의 [리소스 선택]이
// 팝업을 연다: 분야 카드(전체 체크 · 접기) + 트리(LV 배지 · 세 상태 체크 · 폴더 오른쪽 숫자 · 작업 조회/실행 · 맨 위 줄 'N 선택').
// 고른 것은 팝업 안 초안에만 있고 [선택 완료] 때 작업에 들어간다([취소] · Esc · 바깥 클릭 = 버림). 업무 자동화는 에이전트 1개만.
// 외부 도구는 종전처럼 그 자리에서 펼친다. 저장 값은 페이지 [저장]이 보내는 PUT /api/flows 본문으로 확인한다. 실제 목업 + 어댑터, 네트워크는 전부 스텁.
// Run with Playwright on NODE_PATH: node --test tests/test_flow_resource_picker_ui.cjs
// Admin Center › Workflow settings resource picker dialog (user mockups 2026-10-08). [Choose a resource] on knowledge, data, groupware and
// automation tasks opens a dialog: a domain card (select-all, fold) over a tree (LV badges, tri-state checks, folder counts, read/run tags,
// 'N selected' on top rows). Picks stay in the dialog's draft until [Done] (Cancel, Esc and a backdrop click discard them); automation
// allows one agent. External tools still expand in place. Saved values are read from the PUT /api/flows body the page [Save] sends.
// The real mockup and adapter run; every network call is stubbed.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const mockup = fs.readFileSync(path.join(__dirname, '../frontend/ai365-mockup.html'), 'utf8').replace(/\r\n/g, '\n');
const adapter = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8').replace(/\r\n/g, '\n');
const kst = fs.readFileSync(path.join(__dirname, '../static/kst.js'), 'utf8');
const ORIGIN = 'http://flrm.test';
// 서버처럼 응답 시점에 kst.js(<head> 맨 앞)와 adapter.js(</body> 앞)를 넣는다 / inject like the server does at response time
const HTML = mockup.replace('<head>', '<head><script src="/static/kst.js"></script>').replace('</body>', '<script src="/static/adapter.js"></script></body>');

// 지식 트리: 인사(LV.1) › 채용(LV.2) › 채용 공고 문서 · 온보딩 자료(LV.3), 급여 복리후생(허용 파일 없음 = 숨김), 경영(취업규칙.pdf 를 인사와 함께 가진다),
// 재무(숨김), 특수 문자 id 폴더. / The knowledge tree: HR › Hiring › two LV.3 folders, Payroll (no allowed file = hidden), Management (shares
// 취업규칙.pdf with HR), Finance (hidden) and a folder whose id carries quotes.
const QID = 'n_q\'"x';
const KNOWLEDGE = [
  { id: 'k1', lv: 1, name: '인사 업무 영역', node: 'n_hr', files: [{ name: '취업규칙.pdf', node: 'f1' }], children: [
    { id: 'k11', lv: 2, name: '채용', node: 'n_hr_rec', files: [{ name: '면접_평가_가이드.docx', node: 'f2' }, { name: '직무기술서_PM_v3.docx', node: 'f3' }], children: [
      { id: 'k111', lv: 3, name: '채용 공고 문서', node: 'n_hr_post', files: [{ name: '채용공고_2026.pdf', node: 'f4' }, { name: '채용공고_2025.pdf', node: 'f5' }], children: [] },
      { id: 'k112', lv: 3, name: '온보딩 자료', node: 'n_hr_onb', files: [{ name: '온보딩_체크리스트.xlsx', node: 'f6' }], children: [] }] },
    { id: 'k12', lv: 2, name: '급여 복리후생', node: 'n_hr_pay', files: [{ name: '급여규정.pdf', node: 'f7' }], children: [] }] },
  { id: 'k2', lv: 1, name: '경영 업무 영역', node: 'n_mgmt', files: [{ name: '경영계획.pptx', node: 'f8' }, { name: '취업규칙.pdf', node: 'f1b' }], children: [] },
  { id: 'k3', lv: 1, name: '재무 업무 영역', node: 'n_fin', files: [{ name: '비공개_재무.xlsx', node: 'f9' }], children: [] },
  { id: 'k4', lv: 1, name: '특수 "따옴표" 폴더', node: QID, files: [{ name: '특수_문서.pdf', node: 'f10' }], children: [] }];
// 워크스페이스: 경영 그룹은 같은 테이블(중복)과 허용 밖 테이블뿐이라 숨는다 / the management workspace only repeats a table or holds a denied one, so it hides
const WORKSPACES = [
  { id: 'ws_fin', name: '재무 그룹', sql: [{ table: 'sales_monthly', name: '매출_월별_집계' }, { table: 'acct_balance', name: '계정별_잔액_조회' }],
    csv: [{ table: 'csv_budget', name: '예산_계획' }], bi: [{ file: 'fin_dash.pbix', name: '재무 대시보드' }] },
  { id: 'ws_mgmt', name: '경영 그룹', sql: [{ table: 'sales_monthly', name: '매출(경영)' }, { table: 'hr_secret', name: '인사_기밀' }], csv: [], bi: [] }];
const PALETTE = { readable: { knowledge: true, data: true, groupware: true, auto: true }, resources: {
  knowledge_files: ['취업규칙.pdf', '면접_평가_가이드.docx', '직무기술서_PM_v3.docx', '채용공고_2026.pdf', '채용공고_2025.pdf', '온보딩_체크리스트.xlsx', '경영계획.pptx', '특수_문서.pdf', '외부_자료.pdf'],
  tables: [{ name: 'sales_monthly', label: '매출_월별_집계' }, { name: 'acct_balance', label: '계정별_잔액_조회' }, { name: 'csv_budget', label: '예산_계획' }, { name: 'staging_tmp', label: '스테이징' }],
  bi: [{ file: 'fin_dash.pbix', label: '재무 대시보드' }],
  gw_catalog: [
    { ns: 'mail', label: 'Outlook 메일', items: [{ key: 'mail.info.unread', label: '안 읽은 메일', kind: 'info' }, { key: 'mail.info.sender', label: '발신자별 메일', kind: 'info' }, { key: 'mail.action.compose', label: '새 메일 작성', kind: 'action' }] },
    { ns: 'cal', label: 'Outlook 일정', items: [{ key: 'cal.info.today', label: '오늘 일정', kind: 'info' }] },
    { ns: 'todo', label: 'Microsoft To Do', items: [{ key: 'todo.info.list', label: '할 일 목록', kind: 'info' }] },
    { ns: 'sp', label: 'SharePoint', items: [{ key: 'sp.info.recent', label: '최근 문서', kind: 'info' }] },
    { ns: 'widget', label: '위젯', items: [{ key: 'widget.info.weather', label: '날씨', kind: 'info' }] }],
  auto_catalog: [
    { ns: 'email', label: '이메일 업무 에이전트', items: [{ key: 'email.info.unread', label: '안 읽은 메일', kind: 'info' }, { key: 'email.info.sender', label: '발신자별 메일', kind: 'info' }, { key: 'email.action.compose', label: '새 메일 작성', kind: 'action' }] },
    { ns: 'edu', label: '교육 에이전트', items: [{ key: 'edu.info.audit', label: '수강 현황', kind: 'info' }] },
    { ns: 'wa', agent_id: 'agent_ab12cd34', label: '사내 ERP', method: 'api', items: [
      { key: 'wa:agent_ab12cd34:GetSalesSummary', label: 'GetSalesSummary', kind: 'read', description: '기간별 매출 요약',
        inputs: [{ name: 'period', description: '조회 월', required: true }], input_schema: { type: 'object', properties: { period: { type: 'string' } }, required: ['period'] },
        output_schema: { type: 'object', properties: { total: { type: 'number' } } } },
      { key: 'wa:agent_ab12cd34:ApproveOrder', label: 'ApproveOrder', kind: 'action', description: '주문 승인', inputs: [], input_schema: { type: 'object', properties: {} }, output_schema: null }] }],
  connectors: [{ id: 'cn_1', name: 'ERP 조회', description: '매출 조회', kind: 'read', source: 'api', inputs: [], outputs: [], input_schema: null, output_schema: null }] } };
// 그룹웨어 · 업무 자동화 작업엔 그룹 권한 밖 키(빨간 칩)가 하나씩 남아 있다 / the groupware and automation tasks each keep one out-of-permission key (red chip)
const FLOWS = { flows: [{ id: 'fl_a', name: '월간 영업 브리핑', description: '', group: 'g1', stages: [
  { nodes: [
    { agent: 'knowledge', resources: ['면접_평가_가이드.docx', '삭제된_문서.pdf'], instruction: '규정 확인' },
    { agent: 'data', resources: [], instruction: '매출 집계' },
    { agent: 'groupware', resources: ['mail.info.unread', 'mail.info.retired'], instruction: '메일 확인' },
    { agent: 'auto', resources: ['email.info.unread', 'email.info.retired'], instruction: '취합 지침' }], answer_prompt: '' },
  { nodes: [{ agent: 'api', resources: ['cn_1'], instruction: '' }], answer_prompt: '' }] }],
  agents: ['knowledge', 'data', 'groupware', 'auto', 'web', 'api'],
  agent_labels: { knowledge: '지식 관리', data: '데이터 분석', groupware: '그룹웨어', auto: '업무 자동화', web: '웹 검색', api: '외부 도구' } };

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

async function app(t, opts) {
  opts = opts || {};
  const page = await browser.newPage({ viewport: opts.viewport || { width: 1440, height: 1000 } });
  t.after(() => page.close());
  const errors = [], puts = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/*', route => {
    const req = route.request(), url = new URL(req.url()), p = url.pathname;
    const json = (obj, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(obj) });
    if (url.origin !== ORIGIN) return route.abort();
    if (p === '/') return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: HTML });
    if (p === '/static/adapter.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: adapter });
    if (p === '/static/kst.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: kst });
    if (p === '/api/access/bootstrap') return json({ pvtree: [], groups: [{ id: 'g1', name: '영업팀', members: [] }], members: [], teams: [], knowledge: KNOWLEDGE, workspaces: WORKSPACES });
    if (p === '/api/flows' && req.method() === 'PUT') { const body = JSON.parse(req.postData()); puts.push(body); return json({ flows: body.flows }); }
    if (p === '/api/flows') return json(FLOWS);
    if (p === '/api/flows/groups/g1/resources') return json(PALETTE);
    if (p.startsWith('/api/')) return json({ detail: 'stub' }, 404);
    return route.abort();
  });
  await page.goto(ORIGIN + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => typeof window.ai365ApplyLang === 'function' && !!document.getElementById('navPerm')
    && (window.AI365_ORG_GROUPS || []).some(g => g.id === 'g1') && (window.AI365_KNOWLEDGE || []).some(n => n.node === 'n_hr'));
  if (opts.en) await page.evaluate(() => { localStorage.setItem('ai365_lang', 'en'); ai365ApplyLang('en'); });
  await page.evaluate(() => { document.getElementById('navPerm').click(); document.querySelector('[data-hubcard="flows"]').click(); });
  await page.waitForSelector('#flGroupSel');
  await page.selectOption('#flGroupSel', 'g1');
  await page.waitForSelector('[data-flres="0:3"]');
  // 페이지 [저장] → 보낸 1단계 작업들의 resources / page [Save] → the resources of the stage-1 tasks it sent
  const saved = async () => {
    const n = puts.length;
    await page.click('#flSaveBtn');
    for (let i = 0; i < 200 && puts.length <= n; i++) await page.waitForTimeout(25);
    assert.equal(puts.length, n + 1, 'PUT /api/flows');
    return puts[puts.length - 1].flows[0].stages[0].nodes.map(x => x.resources.slice().sort());
  };
  return { page, errors, saved };
}
const txt = (page, sel) => page.$eval(sel, e => e.textContent.trim());
// 줄 = [LV 배지, 이름, aria-checked, 오른쪽 숫자, 'N 선택', 켜짐] / a row = [LV badge, name, aria-checked, count, 'N selected', on]
const rows = page => page.$$eval('#flRmOv .flrm-row', es => es.map(e => {
  const q = s => { const x = e.querySelector(s); return x ? x.textContent.trim() : ''; };
  return [q('.flrm-lv'), q('.flrm-lb'), e.querySelector('.flrm-ck').getAttribute('aria-checked'), q('.flrm-cnt'), q('.flrm-selcnt'), e.classList.contains('on')];
}));
const open = async (page, key) => { await page.click('[data-flres="' + key + '"]'); await page.waitForSelector('#flRmOv .flrm'); };
const closed = async page => page.waitForFunction(() => !document.getElementById('flRmOv'));
const focusedRes = page => page.evaluate(() => document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.flres : null);

test('knowledge: the dialog matches the mockup, keeps a draft that Cancel discards, and Done writes file names that Save sends', async t => {
  const { page, errors, saved } = await app(t);
  assert.equal(await txt(page, '[data-flres="0:0"]'), '리소스 2개');
  await open(page, '0:0');
  assert.equal(await txt(page, '#flRmOv .flrm-tt'), '리소스 선택');
  assert.equal(await txt(page, '#flRmOv .flrm-sub'), 'AI가 참고할 폴더·파일을 선택하세요');
  assert.equal(await txt(page, '#flRmOv .flrm-dtt'), '지식 관리');
  assert.equal(await page.getAttribute('#flRmOv [data-flrm-all]', 'aria-checked'), 'mixed');
  assert.equal(await page.getAttribute('#flRmOv [data-flrm-ck="kd:n_hr"]', 'aria-label'), '인사 업무 영역');   // 체크마다 이름 / every check is named
  // 고른 파일의 조상이 펼쳐져 있다, 허용 파일 없는 폴더(급여 · 재무)는 없다, 트리 밖 허용 파일은 '기타'
  // the picked file's ancestors are open; folders without allowed files (payroll, finance) are gone; allowed files outside the tree sit in 'Other'
  assert.deepEqual(await rows(page), [
    ['LV.1', '인사 업무 영역', 'mixed', '6', '1 선택', false],
    ['LV.2', '채용', 'mixed', '5', '', false],
    ['LV.3', '채용 공고 문서', 'false', '2', '', false],
    ['LV.3', '온보딩 자료', 'false', '1', '', false],
    ['', '면접_평가_가이드.docx', 'true', '', '', true],
    ['', '직무기술서_PM_v3.docx', 'false', '', '', false],
    ['', '취업규칙.pdf', 'false', '', '', false],
    ['LV.1', '경영 업무 영역', 'false', '2', '', false],
    ['LV.1', '특수 "따옴표" 폴더', 'false', '1', '', false],
    ['', '기타', 'false', '1', '', false]]);
  assert.match(await txt(page, '#flRmOv [data-flrm-extra="삭제된_문서.pdf"]'), /삭제된_문서\.pdf \(권한 밖\) ✕/);
  // 폴더 체크 = 그 아래 파일 전부(초안만), [취소] = 버림 / a folder check takes every file below it (draft only); Cancel discards
  await page.click('#flRmOv [data-flrm-ck="kd:n_hr"]');
  assert.deepEqual((await rows(page))[0], ['LV.1', '인사 업무 영역', 'true', '6', '6 선택', true]);
  assert.equal(await txt(page, '[data-flres="0:0"]'), '리소스 2개');
  await page.click('#flRmOv [data-flrm-cancel]');
  await closed(page);
  assert.equal(await txt(page, '[data-flres="0:0"]'), '리소스 2개');
  assert.equal(await focusedRes(page), '0:0');
  // 손대지 않은 권한 밖 값은 [선택 완료]에도 남는다 / an untouched out-of-permission value survives Done
  await open(page, '0:0');
  await page.click('#flRmOv [data-flrm-ok]');
  await closed(page);
  assert.deepEqual((await saved())[0], ['면접_평가_가이드.docx', '삭제된_문서.pdf']);
  // 다시 열면 저장된 값에서 시작 / reopening starts from the stored value
  await open(page, '0:0');
  assert.deepEqual((await rows(page))[0], ['LV.1', '인사 업무 영역', 'mixed', '6', '1 선택', false]);
  await page.click('#flRmOv [data-flrm-tog="kd:__left"]');                   // '기타' 펼치기 / expand 'Other'
  await page.click('#flRmOv .flrm-row:has-text("외부_자료.pdf")');            // 항목 줄 = 체크 / an item row checks
  await page.click('#flRmOv [data-flrm-extra="삭제된_문서.pdf"]');              // 권한 밖 값 빼기 / drop the out-of-permission value
  assert.equal(await page.$('#flRmOv [data-flrm-extra]'), null);
  await page.click('#flRmOv [data-flrm-ck="kd:n_hr"]');
  await page.click('#flRmOv [data-flrm-ok]');
  await closed(page);
  assert.equal(await txt(page, '[data-flres="0:0"]'), '리소스 7개');            // 인사 6 + 외부_자료 1 / HR 6 + the outside file
  assert.equal(await focusedRes(page), '0:0');                                // 포커스는 버튼으로 / focus returns to the button
  // 저장 값 = 파일 이름(트리 id 가 아니다) / saved values are file names, never tree ids
  assert.deepEqual((await saved())[0], ['면접_평가_가이드.docx', '온보딩_체크리스트.xlsx', '외부_자료.pdf', '직무기술서_PM_v3.docx', '채용공고_2025.pdf', '채용공고_2026.pdf', '취업규칙.pdf']);
  assert.deepEqual(errors, []);
});

test('knowledge: keyboard and closing — Tab wraps both ways, Space and Enter toggle, odd ids keep focus, every close returns focus', async t => {
  const { page, errors } = await app(t);
  await open(page, '0:0');
  assert.equal(await page.evaluate(() => document.activeElement.classList.contains('flrm')), true);
  await page.keyboard.press('Shift+Tab');                                     // 창에서 뒤로 = 마지막([선택 완료]) / back from the dialog = the last control
  assert.equal(await page.evaluate(() => document.activeElement.hasAttribute('data-flrm-ok')), true);
  await page.keyboard.press('Tab');                                           // 마지막에서 앞으로 = 처음(✕) / forward from the last = the first (✕)
  assert.equal(await page.evaluate(() => document.activeElement.hasAttribute('data-flrm-x')), true);
  for (let i = 0; i < 40; i++) await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => !!document.activeElement.closest('#flRmOv')), true);
  await page.focus('#flRmOv [data-flrm-ck="kd:n_mgmt"]');
  await page.keyboard.press('Space');
  assert.equal(await page.getAttribute('#flRmOv [data-flrm-ck="kd:n_mgmt"]', 'aria-checked'), 'true');
  assert.equal(await page.evaluate(() => document.activeElement.getAttribute('data-flrm-ck')), 'kd:n_mgmt');
  // 따옴표가 든 id 도 다시 그린 뒤 같은 체크로 포커스가 돌아온다(CSS.escape) / an id with quotes gets focus back after the re-render too
  const qid = 'kd:' + QID;
  await page.evaluate(id => [...document.querySelectorAll('#flRmOv [data-flrm-ck]')].find(e => e.getAttribute('data-flrm-ck') === id).focus(), qid);
  await page.keyboard.press('Enter');
  assert.deepEqual(await page.evaluate(id => { const a = document.activeElement; return [a.getAttribute('data-flrm-ck') === id, a.getAttribute('aria-checked')]; }, qid), [true, 'true']);
  // 같은 파일이 두 폴더에 있으면 함께 켜지고 꺼진다(경영 폴더 체크로 켜진 상태) / a file in two folders turns on and off in both (on via the management check)
  await page.click('#flRmOv [data-flrm-tog="kd:n_mgmt"]');
  const both = () => page.$$eval('#flRmOv .flrm-row', es => es.filter(e => e.querySelector('.flrm-lb').textContent === '취업규칙.pdf').map(e => e.classList.contains('on')));
  assert.deepEqual(await both(), [true, true]);
  await page.click('#flRmOv .flrm-row:has-text("취업규칙.pdf")');
  assert.deepEqual(await both(), [false, false]);
  // 닫는 길마다 버린다 + 포커스는 [리소스 선택] 버튼으로 / every way out discards and returns focus to the button
  await page.keyboard.press('Escape');
  await closed(page);
  assert.equal(await txt(page, '[data-flres="0:0"]'), '리소스 2개');
  assert.equal(await focusedRes(page), '0:0');
  await open(page, '0:0');
  await page.click('#flRmOv [data-flrm-x]');
  await closed(page);
  assert.equal(await focusedRes(page), '0:0');
  await open(page, '0:0');
  await page.click('#flRmOv [data-flrm-fold]');                               // 카드 접기 / fold the card
  assert.equal(await page.$('#flRmOv .flrm-tree'), null);
  assert.equal(await page.getAttribute('#flRmOv [data-flrm-fold]', 'aria-expanded'), 'false');
  await page.click('#flRmOv [data-flrm-fold]');
  assert.ok(await page.$('#flRmOv .flrm-tree'));
  // 창 안에서 누르고 바깥에서 떼면 닫지 않는다 / pressing inside and releasing outside does not close
  const sub = await page.$eval('#flRmOv .flrm-sub', e => { const r = e.getBoundingClientRect(); return { x: r.left + 4, y: r.top + r.height / 2 }; });
  await page.mouse.move(sub.x, sub.y); await page.mouse.down(); await page.mouse.move(8, 8); await page.mouse.up();
  assert.ok(await page.$('#flRmOv .flrm'));
  await page.mouse.click(8, 8);                                               // 바깥 클릭 / backdrop click
  await closed(page);
  assert.equal(await focusedRes(page), '0:0');
  assert.equal(await txt(page, '[data-flres="0:0"]'), '리소스 2개');
  assert.deepEqual(errors, []);
});

test('data: workspace (LV.1) → DB/CSV/BI (LV.2) → slots with type pills; repeated or denied tables stay out; Save sends table names', async t => {
  const { page, errors, saved } = await app(t);
  assert.equal(await txt(page, '[data-flres="0:1"]'), '리소스 선택');
  await open(page, '0:1');
  assert.equal(await txt(page, '#flRmOv .flrm-dtt'), '데이터 분석');
  assert.deepEqual(await rows(page), [['LV.1', '재무 그룹', 'false', '4', '', false], ['', '기타', 'false', '1', '', false]]);
  await page.click('#flRmOv [data-flrm-tog="dw:ws_fin"]');
  await page.click('#flRmOv [data-flrm-tog="dc:ws_fin:sql"]');
  assert.deepEqual(await rows(page), [
    ['LV.1', '재무 그룹', 'false', '4', '', false],
    ['LV.2', 'DB', 'false', '2', '', false],
    ['', '매출_월별_집계', 'false', '', '', false],
    ['', '계정별_잔액_조회', 'false', '', '', false],
    ['LV.2', 'CSV', 'false', '1', '', false],
    ['LV.2', 'BI', 'false', '1', '', false],
    ['', '기타', 'false', '1', '', false]]);
  assert.deepEqual(await page.$$eval('#flRmOv .flrm-row .flrm-type', es => es.map(e => e.textContent)), ['DB', 'DB']);
  await page.click('#flRmOv [data-flrm-ck="dc:ws_fin:sql"]');
  assert.deepEqual((await rows(page)).slice(0, 2), [['LV.1', '재무 그룹', 'mixed', '4', '2 선택', false], ['LV.2', 'DB', 'true', '2', '', true]]);
  await page.click('#flRmOv [data-flrm-tog="dw:__left"]');
  await page.click('#flRmOv .flrm-row:has-text("스테이징")');                    // 워크스페이스 밖 허용 테이블 / an allowed table outside any workspace
  await page.click('#flRmOv [data-flrm-ok]');
  await closed(page);
  assert.equal(await txt(page, '[data-flres="0:1"]'), '리소스 3개');
  assert.deepEqual((await saved())[1], ['acct_balance', 'sales_monthly', 'staging_tmp']);   // 물리 테이블 이름 / physical table names
  assert.deepEqual(errors, []);
});

test('groupware: sections with "N 선택", read/run tags, select-all from the card head, Escape discards, red chips survive Done', async t => {
  const { page, errors, saved } = await app(t);
  assert.equal(await txt(page, '[data-flres="0:2"]'), '작업 2개');
  await open(page, '0:2');
  assert.equal(await txt(page, '#flRmOv .flrm-dtt'), '그룹웨어');
  assert.deepEqual(await rows(page), [
    ['', 'Outlook 메일', 'mixed', '', '1 선택', false],
    ['', '안 읽은 메일', 'true', '', '', true],
    ['', '발신자별 메일', 'false', '', '', false],
    ['', '새 메일 작성', 'false', '', '', false],
    ['', 'Outlook 일정', 'false', '', '', false],
    ['', 'Microsoft To Do', 'false', '', '', false],
    ['', 'SharePoint', 'false', '', '', false],
    ['', '위젯', 'false', '', '', false]]);
  assert.deepEqual(await page.$$eval('#flRmOv .flrm-tag', es => es.map(e => e.textContent + (e.classList.contains('a') ? '*' : ''))), ['조회', '조회', '실행*']);
  assert.ok(await page.$('#flRmOv [data-flrm-extra="mail.info.retired"]'));
  await page.click('#flRmOv [data-flrm-all]');
  assert.equal(await page.getAttribute('#flRmOv [data-flrm-all]', 'aria-checked'), 'true');
  assert.deepEqual((await rows(page))[0], ['', 'Outlook 메일', 'true', '', '3 선택', true]);
  await page.click('#flRmOv [data-flrm-all]');
  assert.equal(await page.getAttribute('#flRmOv [data-flrm-all]', 'aria-checked'), 'false');
  assert.ok(await page.$('#flRmOv [data-flrm-extra="mail.info.retired"]'));   // 전체 해제도 권한 밖 값은 건드리지 않는다 / clear-all leaves it alone
  await page.keyboard.press('Escape');
  await closed(page);
  assert.equal(await txt(page, '[data-flres="0:2"]'), '작업 2개');
  await open(page, '0:2');
  await page.click('#flRmOv .flrm-row:has-text("발신자별 메일")');
  await page.click('#flRmOv [data-flrm-ok]');
  await closed(page);
  assert.equal(await txt(page, '[data-flres="0:2"]'), '작업 3개');
  assert.deepEqual((await saved())[2], ['mail.info.retired', 'mail.info.sender', 'mail.info.unread']);   // 작업 키 + 권한 밖 키 / task keys + the out-of-permission key
  assert.deepEqual(errors, []);
});

test('automation: one agent only — another agent clears the picks but not red chips, a registered tool is exclusive, the head check only clears', async t => {
  const { page, errors, saved } = await app(t);
  await open(page, '0:3');
  assert.equal(await txt(page, '#flRmOv .flrm-dtt'), '업무 자동화');
  assert.equal(await txt(page, '#flRmOv .flrm-dnote'), '에이전트 1개만');
  assert.equal(await page.getAttribute('#flRmOv [data-flrm-all]', 'aria-label'), '모두 해제');
  const secSel = () => page.$$eval('#flRmOv .flrm-row', es => es.filter(e => e.querySelector('.flrm-selcnt')).map(e => e.querySelector('.flrm-lb').textContent + ':' + e.querySelector('.flrm-selcnt').textContent));
  assert.deepEqual(await secSel(), ['이메일 업무 에이전트:1 선택']);
  assert.equal(await txt(page, '#flRmOv [data-flrm-row="sw:agent_ab12cd34"] .flrm-lb'), '사내 ERP · API');
  await page.click('#flRmOv [data-flrm-ck="sn:edu"]');                         // 다른 에이전트 = 앞 선택 해제 / another agent clears the earlier picks
  assert.deepEqual(await secSel(), ['교육 에이전트:1 선택']);
  assert.ok(await page.$('#flRmOv [data-flrm-extra="email.info.retired"]'));   // 빨간 칩은 칩으로만 뺀다 / a red chip leaves only through its chip
  await page.click('#flRmOv [data-flrm-ck="sw:agent_ab12cd34"]');              // 등록 에이전트 섹션 체크 = 펼치기만 / the registered-agent check only expands
  assert.deepEqual(await secSel(), ['교육 에이전트:1 선택']);
  assert.match(await txt(page, '#flRmOv .flrm-hint'), /등록 에이전트 도구는 하나만 고를 수 있습니다/);
  assert.deepEqual(await page.$$eval('#flRmOv .flrm-desc', es => es.map(e => e.textContent)), ['기간별 매출 요약', '주문 승인']);
  await page.click('#flRmOv .flrm-desc:has-text("기간별 매출 요약")');          // 설명 줄을 눌러도 고른다 / clicking the description picks too
  assert.deepEqual(await secSel(), ['사내 ERP · API:1 선택']);
  assert.equal(await page.$('#flRmOv [data-flrm-extra]'), null);              // wa 는 배타 / a wa pick is exclusive
  await page.click('#flRmOv [data-flrm-ck="si:wa:agent_ab12cd34:ApproveOrder"]');
  assert.deepEqual(await page.$$eval('#flRmOv .flrm-row.on .flrm-lb', es => es.map(e => e.textContent)), ['ApproveOrder']);
  await page.click('#flRmOv [data-flrm-all]');                                  // 머리 체크 = 해제 / the head check clears
  assert.deepEqual(await secSel(), []);
  assert.equal(await page.$('#flRmOv [data-flrm-all]'), null);                 // 고른 것이 없으면 꺼진 체크 / disabled while nothing is picked
  assert.equal(await page.getAttribute('#flRmOv .flrm-chd .flrm-ck', 'aria-disabled'), 'true');
  assert.equal(await page.evaluate(() => document.activeElement.hasAttribute('data-flrm-fold')), true);   // 포커스는 접기 버튼으로 / focus moves to the fold button
  await page.click('#flRmOv .flrm-row:has-text("GetSalesSummary")');
  await page.click('#flRmOv [data-flrm-ok]');
  await closed(page);
  assert.equal(await txt(page, '[data-flres="0:3"] .fl-resbtn-tx'), '사내 ERP · GetSalesSummary');
  assert.ok(await page.$('[data-flschema="0:3:in"]'));                         // 입력값 표 / the input table
  assert.deepEqual((await saved())[3], ['wa:agent_ab12cd34:GetSalesSummary']);
  assert.deepEqual(errors, []);
});

test('external tools keep the in-place panel; on small screens the dialog fits, scrolls only its body and keeps the scroll on clicks', async t => {
  const { page, errors } = await app(t, { viewport: { width: 760, height: 620 } });
  await page.click('[data-flres="1:0"]');
  // 이 폭에선 편집기 칸 자체가 눌려 패널 폭이 0 이다(종전 배치 그대로) — 팝업이 아니라 그 자리 패널이 생겼는지만 본다
  // at this width the editor column itself is squeezed to zero (existing layout), so only check the in-place panel exists instead of a dialog
  await page.waitForSelector('.fl-res.api', { state: 'attached' });
  assert.equal(await page.$('#flRmOv'), null);
  await open(page, '0:0');
  await page.click('#flRmOv [data-flrm-tog="kd:__left"]');
  await page.click('#flRmOv [data-flrm-tog="kd:n_mgmt"]');
  const box = await page.evaluate(() => {
    const d = document.querySelector('#flRmOv .flrm').getBoundingClientRect(), f = document.querySelector('#flRmOv .flrm-ft').getBoundingClientRect();
    const b = document.querySelector('#flRmOv .flrm-body');
    return { left: d.left, right: d.right, top: d.top, bottom: d.bottom, ftBottom: f.bottom, vw: innerWidth, vh: innerHeight,
      scrollX: b.scrollWidth - b.clientWidth, scrolls: b.scrollHeight > b.clientHeight };
  });
  assert.ok(box.left >= 23 && box.right <= box.vw - 23, JSON.stringify(box));
  assert.ok(box.top >= 23 && box.bottom <= box.vh - 23 && box.ftBottom <= box.vh, JSON.stringify(box));
  assert.ok(box.scrollX <= 0, JSON.stringify(box));
  assert.equal(box.scrolls, true);                                             // 본문만 스크롤 / only the body scrolls
  // 맨 아래로 내린 채 줄을 눌러도 스크롤 위치는 그대로 / clicking a row at the bottom keeps the scroll position
  const top0 = await page.$eval('#flRmOv .flrm-body', b => { b.scrollTop = b.scrollHeight; return b.scrollTop; });
  assert.ok(top0 > 0);
  await page.click('#flRmOv .flrm-row:has-text("외부_자료.pdf")');
  assert.equal(await page.getAttribute('#flRmOv .flrm-row:has-text("외부_자료.pdf") .flrm-ck', 'aria-checked'), 'true');
  const top1 = await page.$eval('#flRmOv .flrm-body', b => b.scrollTop);
  assert.ok(Math.abs(top1 - top0) <= 2, top0 + ' → ' + top1);
  await page.click('#flRmOv [data-flrm-ck="kd:__left"]');                     // 체크(포커스 복원)도 스크롤을 옮기지 않는다 / a check (with focus restore) does not scroll either
  const top2 = await page.$eval('#flRmOv .flrm-body', b => b.scrollTop);
  assert.ok(Math.abs(top2 - top0) <= 2, top0 + ' → ' + top2);
  assert.deepEqual(errors, []);
});

test('the dialog is 960 wide on desktop and speaks English when the UI is English', async t => {
  const { page, errors } = await app(t, { en: true });
  await open(page, '0:0');
  const w = await page.$eval('#flRmOv .flrm', e => Math.round(e.getBoundingClientRect().width));
  assert.equal(w, 960);
  assert.equal(await txt(page, '#flRmOv .flrm-tt'), 'Choose a resource');
  assert.equal(await txt(page, '#flRmOv .flrm-sub'), 'Choose the folders and files the AI should use');
  assert.equal(await txt(page, '#flRmOv .flrm-dtt'), 'Knowledge');
  assert.equal(await txt(page, '#flRmOv [data-flrm-cancel]'), 'Cancel');
  assert.equal(await txt(page, '#flRmOv [data-flrm-ok]'), 'Done');
  assert.equal((await rows(page))[0][4], '1 selected');
  assert.equal(await page.getAttribute('#flRmOv [data-flrm-ck="kd:__left"]', 'aria-label'), 'Other');
  assert.equal(await page.getAttribute('#flRmOv [data-flrm-tog="kd:__left"]', 'aria-label'), 'Expand section');
  assert.match(await txt(page, '#flRmOv [data-flrm-extra]'), /\(No access\) ✕/);
  await page.click('#flRmOv [data-flrm-cancel]');
  await closed(page);
  await open(page, '0:3');
  assert.equal(await txt(page, '#flRmOv .flrm-dtt'), 'Automation');
  assert.equal(await txt(page, '#flRmOv .flrm-dnote'), '1 agent only');
  assert.equal(await page.getAttribute('#flRmOv [data-flrm-all]', 'aria-label'), 'Clear all');
  assert.deepEqual(await page.$$eval('#flRmOv .flrm-tag', es => es.map(e => e.textContent)), ['Read', 'Read', 'Action']);
  assert.deepEqual(errors, []);
});
