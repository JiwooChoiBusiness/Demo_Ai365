// 실행: Playwright 가 NODE_PATH 에 있을 때 node --test tests/test_conn_page_ui.cjs
// 관리 센터 › API · MCP 연결 두 칸 화면(2026-10-08 사용자 시안). [API | MCP] 탭마다 왼쪽 목록 카드(항목 · 쓰는 워크플로우 수 · [+ 추가])와
// 오른쪽 편집 카드(API = 요청 설정 · 응답 설정 · 테스트 탭의 섹션 카드, MCP = 번호 섹션 4장, 바닥 [취소][저장]). 고른 것이 없으면 첫 항목이 열리고,
// 저장하지 않은 고침이 있으면 다른 항목 · 탭 · [+ 추가]로 옮기기 전에 묻는다. 폭은 좌우로 넓다. 실제 목업 + 어댑터, 네트워크는 전부 스텁(상태 유지).
// Run with Playwright on NODE_PATH: node --test tests/test_conn_page_ui.cjs
// Admin Center › API and MCP connections two-pane screen (user mockups 2026-10-08). Each [API | MCP] tab has a list card on the left (items, how
// many workflows use each, [+ Add]) and an editor card on the right (API = section cards under Request / Response / Test tabs, MCP = four numbered
// sections, footer [Cancel][Save]). With no pick the first item opens; unsaved edits ask before moving to another item, tab or [+ Add]. Full width.
// The real mockup and adapter run; every network call is stubbed (stateful).
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const mockup = fs.readFileSync(path.join(__dirname, '../frontend/ai365-mockup.html'), 'utf8').replace(/\r\n/g, '\n');
const adapter = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8').replace(/\r\n/g, '\n');
const kst = fs.readFileSync(path.join(__dirname, '../static/kst.js'), 'utf8');
const ORIGIN = 'http://conn.test';
const HTML = mockup.replace('<head>', '<head><script src="/static/kst.js"></script>').replace('</body>', '<script src="/static/adapter.js"></script></body>');

const apiRec = (id, name, extra) => Object.assign({ id, name, description: name + ' 설명', category: 'erp', kind: 'read', enabled: true, source: 'api',
  api: { name, method: 'GET', url: 'https://erp.example.invalid/sales?month={{input.month}}', timeout: 30, auth: { type: 'none', key: '', in: 'header', name: 'Authorization' },
    headers: [{ name: 'Accept', value: 'application/json' }], params: [], body: { content_type: 'none', payload: '' },
    response: { format: 'auto', path: '', outputs: [{ name: 'total_sales', path: '$.total_sales' }], ok_status: '2xx', on_error: 'continue', retries: 0, retry_wait: 2, preview_chars: 1200, include_in_answer: true },
    input_docs: [{ name: 'month', description: '조회 월', example: '2026-09', default: '', type: 'string', required: true }], test: null } }, extra || {});
const toolRec = (id, server, tool) => ({ id, name: tool, description: tool + ' 설명', category: 'other', kind: 'read', enabled: true, source: 'mcp',
  api: { mcp: { server_id: server, tool, title: tool }, input_docs: [] } });
function seed() {
  return {
    connectors: [apiRec('cn_erp', 'ERP 매출 조회'), apiRec('cn_ems', 'EMS 설비 상태', { enabled: false, category: 'ems' }), toolRec('mcp_srv1_read_sensor', 'srv1', 'read_sensor')],
    servers: [{ id: 'srv1', name: '설비 MCP', description: '설비 센서 도구', category: 'other', url: 'https://mcp.example.invalid/mcp', auth_type: 'none', timeout: 30, enabled: true,
      fetched_at: '2026-10-08T09:00:00', server_info: { name: 'demo', version: '1.0' }, skill_count: 0, tools: [{ name: 'read_sensor' }] }],
  };
}
// 쓰는 워크플로우: cn_erp = 2개(fl_a · fl_b), 설비 MCP = 1개(fl_a 의 도구) / workflows: cn_erp in two, the MCP server's tool in one
const FLOWS = { flows: [
  { id: 'fl_a', name: '월간 보고', group: 'g1', stages: [{ nodes: [{ agent: 'api', resources: ['cn_erp'] }, { agent: 'api', resources: ['mcp_srv1_read_sensor'] }] }] },
  { id: 'fl_b', name: '주간 점검', group: 'g1', stages: [{ nodes: [{ agent: 'api', resources: ['cn_erp'] }, { agent: 'knowledge', resources: ['cn_ems'] }] }] }] };
const CATALOG = { systems: [{ id: 'erp', label: 'ERP' }], items: [{ id: 'erp_sales', system: 'erp', label: 'ERP 매출', description: '매출 조회', kind: 'read',
  sample: { name: '', method: 'GET', url: '{{base_url}}/mock/erp/sales' }, test_vars: {} }],
  mcp: { label: '데모 MCP', description: '데모 서버', category: 'other', url: 'https://mcp.example.invalid/mock' } };

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

async function app(t, opts) {
  opts = opts || {};
  const db = opts.empty ? { connectors: [], servers: [] } : seed();
  const page = await browser.newPage({ viewport: opts.viewport || { width: 1440, height: 1000 } });
  t.after(() => page.close());
  const errors = [], calls = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), p = url.pathname, method = req.method();
    const json = (obj, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(obj) });
    if (url.origin !== ORIGIN) return route.abort();
    if (p === '/') return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: HTML });
    if (p === '/static/adapter.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: adapter });
    if (p === '/static/kst.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: kst });
    if (p.startsWith('/api/connectors') || p.startsWith('/api/mcp')) calls.push(method + ' ' + p);
    if (p === '/api/access/bootstrap') return json({ pvtree: [], groups: [], members: [], teams: [] });
    if (p === '/api/flows') return json(FLOWS);
    if (p === '/mock/catalog') return json(CATALOG);
    if (p === '/api/connectors' && method === 'GET' && db.failList) return json({ detail: 'down' }, 500);
    if (p === '/api/connectors/test' && method === 'POST') return json({ ok: true, status: 200, elapsed_ms: 5, result_text: 'ok', outputs: {}, url: 'https://erp.example.invalid/sales', request: { method: 'GET', headers: {} } });
    if (p === '/api/connectors' && method === 'GET') return json({ connectors: db.connectors, mcp_servers: db.servers, categories: [], kinds: [], max: 30, auto_inputs: ['question', 'user_name', 'user_no', 'date', 'time', 'month'] });
    if (p === '/api/connectors' && method === 'POST') { const b = JSON.parse(req.postData()); const rec = Object.assign({ id: 'cn_new', source: 'api' }, b); delete rec.acting_user_id; db.connectors.push(rec); calls.push('BODY ' + JSON.stringify(b)); return json(rec); }
    let m = /^\/api\/connectors\/([^/]+)\/usage$/.exec(p);
    if (m) return json({ workflows: m[1] === 'cn_erp' ? [{ id: 'fl_a', name: '월간 보고', stage: 1, task: 1 }, { id: 'fl_b', name: '주간 점검', stage: 1, task: 1 }] : [] });
    m = /^\/api\/connectors\/([^/]+)$/.exec(p);
    if (m && method === 'PUT' && db.hold) await new Promise(res => { db.release = res; });   // 저장을 붙잡아 둔다 / hold the save
    if (m && method === 'PUT') { const b = JSON.parse(req.postData()); const i = db.connectors.findIndex(c => c.id === m[1]); db.connectors[i] = Object.assign({}, db.connectors[i], b); return json(db.connectors[i]); }
    if (m && method === 'DELETE') { db.connectors = db.connectors.filter(c => c.id !== m[1]); return json({ ok: true }); }
    m = /^\/api\/mcp\/servers\/([^/]+)\/usage$/.exec(p);
    if (m) return json({ workflows: [{ id: 'fl_a', name: '월간 보고', stage: 1, task: 2, tool: 'read_sensor' }] });
    m = /^\/api\/mcp\/servers\/([^/]+)$/.exec(p);
    if (m && method === 'GET' && db.failDetail) return json({ detail: 'down' }, 500);
    if (m && method === 'PUT') { const b = JSON.parse(req.postData()); calls.push('MCPBODY ' + JSON.stringify(b)); const i = db.servers.findIndex(x => x.id === m[1]); db.servers[i] = Object.assign({}, db.servers[i], { name: b.name, description: b.description }); return json(Object.assign({ id: m[1], tools: [{ name: 'read_sensor' }] }, db.servers[i])); }
    if (m && method === 'DELETE') { db.servers = db.servers.filter(x => x.id !== m[1]); db.connectors = db.connectors.filter(c => !((c.api || {}).mcp && c.api.mcp.server_id === m[1])); return json({ ok: true }); }
    if (m && method === 'GET') { const s = db.servers.find(x => x.id === m[1]); return s ? json(Object.assign({}, s, { auth: { type: 'none', key: '', name: 'Authorization' },
      tools: [{ name: 'read_sensor', title: '센서 값 조회', description: '센서 값을 읽습니다', kind: 'read', enabled: true, input_schema: { type: 'object' }, output_schema: null }], skills: [] })) : json({ detail: 'no' }, 404); }
    if (p.startsWith('/api/')) return json({ detail: 'stub' }, 404);
    return route.abort();
  });
  await page.goto(ORIGIN + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => typeof window.ai365ApplyLang === 'function' && !!document.getElementById('navPerm'));
  if (opts.en) await page.evaluate(() => { localStorage.setItem('ai365_lang', 'en'); ai365ApplyLang('en'); });
  await page.evaluate(() => { document.getElementById('navPerm').click(); document.querySelector('[data-hubcard="connectors"]').click(); });
  await page.waitForSelector(opts.empty ? '#connListBody .conn-list-empty' : '#connListBody .conn-row');
  return { page, errors, calls, db };
}
const txt = (page, sel) => page.$eval(sel, e => e.textContent.trim());
// 목록 줄 = 이름|꼬리표|숫자 / a list row = name|tag|count
const listRows = page => page.$$eval('#connListBody .conn-row', es => es.map(e => [e.querySelector('b').textContent, (e.querySelector('.conn-row-off') || {}).textContent || '',
  (e.querySelector('.conn-row-cnt') || {}).textContent || ''].filter(Boolean).join('|') + (e.classList.contains('sel') ? '*' : '')));
const cardTitles = page => page.$$eval('#flApiBody .conn-card-tt', es => es.map(e => e.textContent.replace(/\s+/g, ' ').trim()));

test('the API tab opens the first API in the editor: two panes, counts, the request cards, full width', async t => {
  const { page, errors } = await app(t, { viewport: { width: 1920, height: 1080 } });   // 넓은 화면이라야 옛 최대 폭(1180)과 갈린다 / only a wide screen tells it from the old 1180 cap
  assert.deepEqual(await page.$$eval('[data-conntab]', es => es.map(e => e.textContent + (e.classList.contains('active') ? '*' : ''))), ['API*', 'MCP']);
  assert.equal(await txt(page, '#connListTt'), 'API');
  assert.equal(await txt(page, '#connAddBtn'), '+ API 추가');
  await page.waitForFunction(() => document.querySelector('#connListBody .conn-row-cnt'));   // 숫자는 워크플로우를 받은 뒤 / counts arrive with the workflows
  assert.deepEqual(await listRows(page), ['ERP 매출 조회|2*', 'EMS 설비 상태|비활성|0']);
  assert.equal(await txt(page, '#flApiPage .conn-ed-tt'), 'API 수정');
  assert.equal(await page.isVisible('#flApiPage [data-flapi-del]'), true);
  assert.equal(await page.isVisible('#mcpPage'), false);
  await page.waitForFunction(() => document.getElementById('flApiUsage').style.display === '');
  assert.match(await txt(page, '#flApiUsage'), /사용 중인 워크플로우: 월간 보고 \(1단계 1번 작업\), 주간 점검/);
  assert.deepEqual(await page.$$eval('#flApiPage .conn-subtabs button', es => es.map(e => e.textContent + (e.classList.contains('on') ? '*' : ''))), ['요청 설정*', '응답 설정', '테스트']);
  assert.deepEqual(await cardTitles(page), ['기본 정보', '1. 요청', '2. 인증', '3. 헤더', '4. 쿼리 파라미터 (선택)', '5. 요청 본문ⓘ', '6. 입력값 설명']);
  assert.equal(await page.inputValue('#flApiBody [data-fa="name"]'), 'ERP 매출 조회');
  assert.deepEqual(await page.$$eval('#flApiBody .conn-card.flush th', es => es.map(e => e.textContent)), ['헤더 이름', '값', '삭제', '파라미터 이름', '값', '삭제']);
  assert.equal(await page.isChecked('#flApiBody [data-fa-conn="enabled"]'), true);   // 활성 스위치 / the enabled switch
  assert.deepEqual(await page.$$eval('#flApiPage .conn-ed-ft button', es => es.map(e => e.textContent)), ['취소', '저장']);
  // 좌우로 넓다: 안쪽 폭 = 스크롤 칸 폭 - 좌우 여백 / full width: the inner width = the scroll box width minus its side padding
  const w = await page.evaluate(() => { const sc = document.getElementById('pgConnScroll'), inner = sc.querySelector('.pg-list-inner'), cs = getComputedStyle(sc);
    return [Math.round(inner.getBoundingClientRect().width), Math.round(sc.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight))]; });
  assert.equal(w[0], w[1]);
  assert.ok(w[0] > 1180, String(w));
  const panes = await page.evaluate(() => ['.conn-list', '.conn-ed'].map(s => Math.round(document.querySelector('#pgConnScroll ' + s).getBoundingClientRect().width)));
  assert.equal(panes[0], 260);   // 왼쪽 목록 = Dev ApiListPanel.tsx 260(2026-10-28 Dev 원본 정렬, 종전 320) / the list pane is Dev's 260 (was 320)
  assert.ok(panes[1] > 760, String(panes));
  assert.deepEqual(errors, []);
});

test('switching items asks about unsaved edits; Cancel reverts; response and test tabs show their cards', async t => {
  const { page, errors } = await app(t);
  await page.fill('#flApiBody [data-fa="name"]', 'ERP 매출 조회(고침)');
  let asked = null;
  page.once('dialog', d => { asked = d.message(); d.dismiss(); });
  await page.click('#connListBody [data-connsel="cn_ems"]');
  assert.equal(asked, '저장하지 않은 변경 사항이 있습니다. 이동할까요?');
  assert.equal(await page.inputValue('#flApiBody [data-fa="name"]'), 'ERP 매출 조회(고침)');   // 머문다 / stays
  assert.deepEqual(await listRows(page), ['ERP 매출 조회|2*', 'EMS 설비 상태|비활성|0']);
  await page.click('#flApiPage [data-flapi-cancel]');                                        // [취소] = 저장된 값으로 / Cancel reverts
  assert.equal(await page.inputValue('#flApiBody [data-fa="name"]'), 'ERP 매출 조회');
  await page.click('#connListBody [data-connsel="cn_ems"]');                                   // 고친 것이 없으면 묻지 않는다 / no edits, no question
  assert.equal(await page.inputValue('#flApiBody [data-fa="name"]'), 'EMS 설비 상태');
  assert.equal(await page.isChecked('#flApiBody [data-fa-conn="enabled"]'), false);
  await page.click('#flApiPage [data-flapi-tab="res"]');
  assert.deepEqual(await cardTitles(page), ['1. 결과 추출ⓘ', '2. 출력 변수', '3. 성공 조건과 실패 처리ⓘ', '4. 결과 전달']);
  assert.equal(await page.inputValue('#flApiBody [data-fa-cell="response.outputs:0:name"]'), 'total_sales');
  assert.equal(await page.isChecked('#flApiBody [data-fa="response.include_in_answer"]'), true);
  await page.click('#flApiPage [data-flapi-tab="test"]');
  assert.deepEqual(await cardTitles(page), ['변수 테스트 값ⓘ']);
  assert.ok(await page.$('#flApiBody .conn-runrow [data-flapi-run]'));
  assert.deepEqual(errors, []);
});

test('+ Add opens a "새 API" draft; Cancel drops it; Save posts it, keeps it picked and shows it in the list', async t => {
  const { page, errors, calls } = await app(t);
  await page.click('#connAddBtn');
  assert.deepEqual(await listRows(page), ['새 API|0*', 'ERP 매출 조회|2', 'EMS 설비 상태|비활성|0']);
  assert.equal(await txt(page, '#flApiPage .conn-ed-tt'), 'API 추가');
  assert.equal(await page.isVisible('#flApiPage [data-flapi-del]'), false);                    // 새 API 는 삭제 없음 / no delete for a draft
  await page.click('#flApiPage [data-flapi-cancel]');
  assert.deepEqual(await listRows(page), ['ERP 매출 조회|2*', 'EMS 설비 상태|비활성|0']);
  await page.click('#connAddBtn');
  await page.fill('#flApiBody [data-fa="name"]', '재고 조회');
  await page.fill('#flApiBody [data-fa-desc]', '품목별 재고를 조회합니다');
  await page.fill('#flApiBody [data-fa="url"]', 'https://erp.example.invalid/stock');
  await page.click('#flApiPage [data-flapi-save]');
  await page.waitForFunction(() => [...document.querySelectorAll('#connListBody .conn-row.sel b')].some(b => b.textContent === '재고 조회'));
  const body = JSON.parse(calls.find(c => c.startsWith('BODY ')).slice(5));
  assert.deepEqual([body.name, body.description, body.api.url, body.enabled], ['재고 조회', '품목별 재고를 조회합니다', 'https://erp.example.invalid/stock', true]);
  assert.equal(await txt(page, '#flApiPage .conn-ed-tt'), 'API 수정');                      // 저장된 값으로 다시 열림 / reopened from the saved record
  assert.equal(await page.inputValue('#flApiBody [data-fa="name"]'), '재고 조회');
  assert.deepEqual(errors, []);
});

test('Delete confirms, removes the API and the first item opens', async t => {
  const { page, errors, calls } = await app(t);
  await page.click('#connListBody [data-connsel="cn_ems"]');
  let asked = null;
  page.once('dialog', d => { asked = d.message(); d.accept(); });
  await page.click('#flApiPage [data-flapi-del]');
  await page.waitForFunction(() => document.querySelectorAll('#connListBody .conn-row').length === 1);
  assert.equal(asked, "'EMS 설비 상태' API를 삭제할까요?");
  assert.ok(calls.includes('DELETE /api/connectors/cn_ems'));
  assert.deepEqual(await listRows(page), ['ERP 매출 조회|2*']);
  assert.equal(await page.inputValue('#flApiBody [data-fa="name"]'), 'ERP 매출 조회');
  assert.deepEqual(errors, []);
});

test('the MCP tab lists servers with tool usage, opens the server editor, and + Add / Cancel work there too', async t => {
  const { page, errors } = await app(t);
  await page.click('[data-conntab="mcp"]');
  await page.waitForSelector('#mcpPage [data-mcpf="name"]');
  assert.deepEqual(await page.$$eval('[data-conntab]', es => es.map(e => e.textContent + (e.classList.contains('active') ? '*' : ''))), ['API', 'MCP*']);
  assert.equal(await txt(page, '#connListTt'), 'MCP');
  assert.equal(await txt(page, '#connAddBtn'), '+ MCP 서버 추가');
  assert.equal(await txt(page, '#connSub'), 'MCP(Model Context Protocol) 서버에 연결하고, 워크플로우의 외부 도구 작업이 쓸 도구와 Skills 파일을 정합니다.');
  assert.deepEqual(await listRows(page), ['설비 MCP|1*']);
  assert.equal(await txt(page, '#mcpPage .conn-ed-tt'), 'MCP 서버 수정');
  assert.equal(await page.isVisible('#flApiPage'), false);
  assert.deepEqual(await page.$$eval('#mcpPage .mcf-sec-tt', es => es.map(e => e.textContent)), ['기본 정보', '인증', '도구', 'Skills 파일']);
  assert.equal(await page.inputValue('#mcpPage [data-mcpf="name"]'), '설비 MCP');
  assert.deepEqual(await page.$$eval('#mcpPage .conn-ed-ft button', es => es.map(e => e.textContent)), ['취소', '저장']);
  await page.click('#connAddBtn');
  assert.deepEqual(await listRows(page), ['새 MCP 서버|0*', '설비 MCP|1']);
  assert.equal(await txt(page, '#mcpPage .conn-ed-tt'), 'MCP 서버 추가');
  assert.ok(await page.$('#mcpPage [data-mcp-demo]'));
  await page.fill('#mcpPage [data-mcpf="name"]', '새 서버');
  let asked = null;
  page.once('dialog', d => { asked = d.message(); d.accept(); });
  await page.click('[data-conntab="api"]');                                                  // 고친 새 서버 → 탭 이동도 묻는다 / an edited draft asks on a tab switch too
  assert.equal(asked, '저장하지 않은 변경 사항이 있습니다. 이동할까요?');
  assert.equal(await txt(page, '#flApiPage .conn-ed-tt'), 'API 수정');
  await page.click('[data-conntab="mcp"]');                                                  // 돌아오면 버린 초안 대신 첫 서버 / back again: the first server, not the dropped draft
  await page.waitForSelector('#mcpPage [data-mcpf="name"]');
  assert.equal(await txt(page, '#mcpPage .conn-ed-tt'), 'MCP 서버 수정');
  assert.deepEqual(errors, []);
});

test('empty lists show the mockup messages on both tabs', async t => {
  const { page, errors } = await app(t, { empty: true });
  assert.equal(await txt(page, '#connListBody .conn-list-empty'), 'API가 없습니다');
  assert.equal(await page.isVisible('#flApiPage'), false);
  assert.equal(await txt(page, '#connEdEmpty'), '등록된 API가 없습니다. [+ 추가] 로 API를 등록하세요.');
  await page.click('[data-conntab="mcp"]');
  assert.equal(await txt(page, '#connListBody .conn-list-empty'), 'MCP 서버가 없습니다');
  assert.equal(await txt(page, '#connEdEmpty'), '등록된 MCP 서버가 없습니다. [+ 추가] 로 MCP 서버를 등록하세요.');
  await page.click('#connAddBtn');
  await page.waitForSelector('#mcpPage [data-mcpf="name"]');
  assert.equal(await page.isVisible('#connEdEmpty'), false);
  assert.deepEqual(errors, []);
});

test('English labels the tabs, the list, the editor and the empty states', async t => {
  const { page, errors } = await app(t, { en: true });
  assert.equal(await txt(page, '#connAddBtn'), '+ Add API');
  assert.equal(await txt(page, '#connSub'), 'Register external APIs so workflows can call the functions they need. Descriptions and input details feed the run check and AI input generation.');
  assert.equal(await txt(page, '#flApiPage .conn-ed-tt'), 'Edit API');
  assert.deepEqual((await cardTitles(page)).slice(0, 3), ['Basic Info', '1. Request', '2. Authentication']);
  assert.equal(await txt(page, '#flApiBody .conn-card:last-child .conn-card-tt'), '6. Input descriptions');
  assert.deepEqual(await page.$$eval('#flApiPage .conn-ed-ft button', es => es.map(e => e.textContent)), ['Cancel', 'Save']);
  assert.equal(await page.getAttribute('#flApiBody .conn-tip', 'title'), 'Keep "None" for GET requests or when there is no body.');
  assert.equal(await page.$eval('#connListBody .conn-row-off', e => e.textContent), 'Disabled');
  await page.click('#connAddBtn');
  assert.equal(await txt(page, '#connListBody .conn-row.sel b'), 'New API');
  assert.equal(await txt(page, '#flApiPage .conn-ed-tt'), 'Add API');
  assert.deepEqual(errors, []);
});

test('a save locks the editor until it lands; a test run alone is not an unsaved edit; the head shows the status', async t => {
  const { page, errors, db } = await app(t);
  assert.equal(await txt(page, '#flApiStatus'), '미검증');
  const asked = [];
  page.on('dialog', d => { asked.push(d.message()); d.dismiss(); });
  // 테스트만 돌리고 옮기면 묻지 않는다, 머리는 검증됨 / running a test and moving on never asks; the head says verified
  await page.click('#flApiPage [data-flapi-tab="test"]');
  await page.click('#flApiBody [data-flapi-run]');
  await page.waitForFunction(() => document.querySelector('#flApiStatus').textContent === '검증됨');
  await page.click('#connListBody [data-connsel="cn_ems"]');
  assert.deepEqual(asked, []);
  assert.equal(await page.inputValue('#flApiBody [data-fa="name"]'), 'EMS 설비 상태');
  assert.equal(await txt(page, '#flApiStatus'), '비활성');
  // 저장 중 = [저장] 잠김 '저장 중…', 다른 항목 · [취소]로 옮기지 않는다 / while saving: [Save] locked, no move to another item or by [Cancel]
  await page.fill('#flApiBody [data-fa="name"]', 'EMS 설비 상태 v2');
  db.hold = true;
  await page.click('#flApiPage [data-flapi-save]');
  await page.waitForFunction(() => document.querySelector('#flApiPage [data-flapi-save]').disabled);
  assert.equal(await txt(page, '#flApiPage [data-flapi-save]'), '저장 중…');
  await page.click('#connListBody [data-connsel="cn_erp"]');
  await page.click('#flApiPage [data-flapi-cancel]');
  assert.equal(await page.inputValue('#flApiBody [data-fa="name"]'), 'EMS 설비 상태 v2');
  assert.deepEqual(asked, []);
  db.hold = false; db.release();
  await page.waitForFunction(() => [...document.querySelectorAll('#connListBody .conn-row.sel b')].some(b => b.textContent === 'EMS 설비 상태 v2'));
  assert.equal(await page.inputValue('#flApiBody [data-fa="name"]'), 'EMS 설비 상태 v2');   // 저장된 값으로 다시 열림 / reopened with the saved value
  assert.equal(await txt(page, '#flApiPage [data-flapi-save]'), '저장');
  assert.equal(await page.isDisabled('#flApiPage [data-flapi-save]'), false);
  assert.deepEqual(errors, []);
});

test('MCP: save and delete work in the editor; a failed detail load offers a retry instead of a blank form', async t => {
  const { page, errors, calls, db } = await app(t);
  await page.click('[data-conntab="mcp"]');
  await page.waitForSelector('#mcpPage [data-mcpf="name"]');
  await page.fill('#mcpPage [data-mcpf="name"]', '설비 MCP 2');
  await page.click('#mcpPage [data-mcp-save]');
  await page.waitForFunction(() => [...document.querySelectorAll('#connListBody .conn-row.sel b')].some(b => b.textContent === '설비 MCP 2'));
  assert.equal(JSON.parse(calls.find(c => c.startsWith('MCPBODY ')).slice(8)).name, '설비 MCP 2');
  await page.waitForSelector('#mcpPage [data-mcpf="name"]');
  assert.equal(await page.inputValue('#mcpPage [data-mcpf="name"]'), '설비 MCP 2');
  // 상세를 못 받으면 빈 양식 대신 안내 + 다시 시도, 저장 잠김 / a failed detail shows a note and a retry, and saving is locked
  db.failDetail = true;
  await page.click('#mcpPage [data-mcp-cancel]');                                           // 다시 열기 = 상세 다시 받기 / reopening fetches the detail again
  await page.waitForSelector('#mcpPage [data-mcp-retry]');
  assert.match(await txt(page, '#mcpPage .mcf-empty'), /MCP 서버 정보를 불러오지 못했습니다\./);
  assert.equal(await page.$('#mcpPage [data-mcpf="name"]'), null);
  assert.equal(await page.isDisabled('#mcpPage [data-mcp-save]'), true);
  db.failDetail = false;
  await page.click('#mcpPage [data-mcp-retry]');
  await page.waitForSelector('#mcpPage [data-mcpf="name"]');
  // 삭제 = 확인 뒤 DELETE, 마지막 서버였으면 빈 상태 / delete = confirm then DELETE; the last server leaves the empty state
  let asked = null;
  page.once('dialog', d => { asked = d.message(); d.accept(); });
  await page.click('#mcpPage [data-mcp-del]');
  await page.waitForSelector('#connListBody .conn-list-empty');
  assert.match(asked, /^'설비 MCP 2' MCP 서버와 도구 1개의 연결을 삭제할까요\?\n이 서버의 도구를 쓰는 워크플로우 작업 1개는 도구 없는 상태가 됩니다\.$/);
  assert.ok(calls.includes('DELETE /api/mcp/servers/srv1'));
  assert.equal(await txt(page, '#connEdEmpty'), '등록된 MCP 서버가 없습니다. [+ 추가] 로 MCP 서버를 등록하세요.');
  assert.deepEqual(errors, []);
});

test('a failed list reload keeps the edited editor; keyboard picks keep focus; names are never translated', async t => {
  const { page, errors, db } = await app(t);
  await page.click('#connListBody [data-connsel="cn_ems"]');
  await page.fill('#flApiBody [data-fa="name"]', 'EMS 고침');
  await page.click('#pgConnScroll .pg-crumb-sys');                                           // 허브로 나갔다가 / out to the hub
  db.failList = true;
  await page.evaluate(() => document.querySelector('[data-hubcard="connectors"]').click());  // 목록 받기 실패 / the list load fails
  await page.waitForFunction(() => document.getElementById('pgConnScroll').style.display !== 'none');
  await page.waitForTimeout(200);
  assert.deepEqual(await listRows(page), ['ERP 매출 조회|2', 'EMS 설비 상태|비활성|0*']);    // 종전 목록 그대로 / the previous list stays
  assert.equal(await page.inputValue('#flApiBody [data-fa="name"]'), 'EMS 고침');
  db.failList = false;
  await page.click('#pgConnScroll .pg-crumb-sys');
  await page.evaluate(() => document.querySelector('[data-hubcard="connectors"]').click());
  await page.waitForTimeout(300);
  assert.equal(await page.inputValue('#flApiBody [data-fa="name"]'), 'EMS 고침');           // 다음 성공에도 고친 것 유지 / still kept after the next success
  // 키보드로 고르면 포커스는 고른 행 / a keyboard pick keeps focus on the picked row
  page.once('dialog', d => d.accept());
  await page.focus('#connListBody [data-connsel="cn_erp"]');
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => document.querySelector('#flApiBody [data-fa="name"]').value === 'ERP 매출 조회');
  assert.equal(await page.evaluate(() => document.activeElement.getAttribute('data-connsel')), 'cn_erp');
  // 이름이 사전 낱말과 같아도 번역하지 않는다 / a name equal to a dictionary word is not translated
  assert.equal(await page.$eval('#connListBody [data-connsel="cn_erp"] b', b => b.hasAttribute('data-i18n-skip')), true);
  assert.deepEqual(errors, []);
});
