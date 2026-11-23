// 업무 자동화 에이전트 등록 화면(2026-09-22) — 목업의 rmWa* 함수를 격리 브라우저에서 실행. 네트워크는 전부 차단.
// Work-agent registration screen (2026-09-22) — the mockup's rmWa* functions in an isolated browser; all network stubbed.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const source = fs.readFileSync(path.join(__dirname, '../frontend/ai365-mockup.html'), 'utf8').replace(/\r\n/g, '\n');
function fn(name) {
  const start = source.indexOf('  function ' + name + '(');
  assert.ok(start >= 0, name);
  const end = source.indexOf('\n', start);
  return /}\s*$/.test(source.slice(start, end)) ? source.slice(start, end) : source.slice(start, source.indexOf('\n  }', start) + 4);
}
let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });
async function fixture(t, mode) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 980 } });
  t.after(() => page.close());
  const styles = [...source.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map(m => m[1]).join('\n');
  await page.route('**/*', route => route.abort());
  await page.setContent('<style>' + styles + '</style><div id="rmAutoAgList"></div><div class="rm-panel" id="rmAutoSettings"></div>', { waitUntil: 'domcontentloaded' });
  // 서버가 <head> 에 넣는 한국 시간 도우미(static/kst.js) — rmWaTest 의 검증 시각이 쓴다 / the KST helpers the server injects; rmWaTest's stamp uses them
  await page.addScriptTag({ path: path.join(__dirname, '../static/kst.js') });
  const names = [...source.matchAll(/^  function (rmWa\w+)\(/gm)].map(m => m[1]);
  const consts = ['RM_WA=', 'RM_WA_METHODS=', 'RM_WA_AUTH_API=', 'RM_WA_AUTH_MCP=', 'RM_WA_HTTP='].map(k => {
    const i = source.indexOf('  const ' + k); assert.ok(i >= 0, k);
    const end = k === 'RM_WA_METHODS=' ? source.indexOf('\n  ];\n', i) + 6 : source.indexOf('\n', i) + 1;   // 방식 카드 배열만 여러 줄 / only the method array spans lines
    return source.slice(i, end);
  }).join('') + (() => {   // 교육 에이전트 레지스트리(여러 줄) — 기본 제공 수정 폼이 쓴다(2026-10-06) / the education registry, used by the built-in edit form
    const i = source.indexOf('  const RM_EDU_API={'); assert.ok(i >= 0, 'RM_EDU_API');
    return source.slice(i, source.indexOf('\n  };\n', i) + 5);
  })();
  await page.addScriptTag({ content: `
    var rmMode=${JSON.stringify(mode || 'add')};
    function esc(v){const d=document.createElement('span');d.textContent=String(v??'');return d.innerHTML.replace(/"/g,'&quot;');}
    function toast(){} function rmActingId(){ return ''; }
    function rmRoField(label, value, req, full){ return '<div class="rm-field'+(full?' full':'')+'"><span class="rm-flabel">'+esc(label)+(req?' <span class="rm-req">*</span>':'')+'</span><div class="rm-ro">'+esc(value||'-')+'</div></div>'; }
    function rmDaTip(t){ return '<span class="rm-tip">'+esc(t)+'</span>'; }
    function rmEmailCode(src){ return '<div class="rm-code">'+String(src).split('\\n').map(function(l,i){ return '<div class="rm-code-row"><span class="rm-code-ln">'+(i+1)+'</span><span class="rm-code-tx">'+esc(l)+'</span></div>'; }).join('')+'</div>'; }
    function renderRmEduSettings(){}
    ${consts}
    let rmAutoSel=null, rmAutoForm=null;
    var MCF_DOC_IC='', MCF_UP_IC='', MCF_UPBTN_IC='', MCF_TRASH_IC='', MCF_EYE_IC='', MCF_EYE_OFF_IC='', MCF_BACK_IC='', MCF_EXTS=['.yaml','.yml','.json','.md','.txt'], MCF_MAX_BYTES=10485760, MCF_MAX_FILES=20;   // 공통 도우미 상수(2026-09-23) / shared helper constants
    ${['mcfSec','mcfRow','mcfSize','mcfTime','mcfSchemaBtn','mcfSkillsHtml','mcfPickFiles'].map(fn).join('\n')}
    ${fn('rmAutoTip')}
    ${names.map(fn).join('\n')}
    ${fn('rmAutoUpdateSave')}
    ${fn('renderRmAuto')}
    ${fn('renderRmAutoSettings')}
    ${fn('rmWaField')}
    window.setForm=function(f, sel){ rmAutoForm=f; rmAutoSel=sel||{kind:'new'}; renderRmAutoSettings(); };
    window.setList=function(list, sel){ RM_WA.list=list; RM_WA.loaded=true; rmAutoSel=sel; rmAutoForm=null; renderRmAuto(); };
    window.formOf=function(a){ return rmWaFormFrom(a); };
    window.schemaOf=rmWaSchema; window.missingOf=rmWaMissing; window.bodyOf=rmWaBody;
  ` });
  return page;
}
const SAVED = {
  id: 'agent_ab12cd34', name: '사내 ERP', description: '매출 조회', method: 'api', enabled: true,
  config: { base_url: 'https://erp.example.invalid/api', version: 'v1', timeout: 30, auth: { type: 'bearer', key: '••••••', name: 'Authorization' },
    endpoints: [
      { name: 'GetSalesSummary', method: 'GET', path: '/sales/summary', description: '매출 요약', kind: 'read', tested_at: '2026-09-22T09:00:00', sample: '{"total": 5}',
        params: [{ name: 'period', type: 'string', required: true, description: '조회 월', example: '2026-08' }],
        input_schema: { type: 'object', properties: { period: { type: 'string', description: '조회 월', examples: ['2026-08'] } }, required: ['period'] } },
      { name: 'ApproveOrder', method: 'POST', path: '/orders/{order_id}/approve', description: '', kind: 'action', tested_at: '', sample: '',
        params: [{ name: 'order_id', type: 'string', required: true, description: '', example: '' }] }] } };

test('parameter table becomes the same JSON Schema as the server and path variables are required', async t => {
  const page = await fixture(t);
  const schema = await page.evaluate(() => schemaOf({ method: 'GET', path: '/orders/{id}/items', params: [
    { name: 'period', type: 'string', required: false, description: '조회 월', example: '2026-08' }, { name: 'qty', type: 'integer', required: true, description: '', example: '' }] }));
  assert.deepEqual(schema, { type: 'object', properties: { period: { type: 'string', description: '조회 월', examples: ['2026-08'] }, qty: { type: 'integer' }, id: { type: 'string' } }, required: ['qty', 'id'] });
  const missing = await page.evaluate(() => {
    const out = [];
    const f = { name: '', method: 'api', description: '', enabled: true, api: { base_url: '', auth: { type: 'none', key: '' }, endpoints: [] }, mcp: { url: '', auth: { type: 'none', key: '' }, tools: [] } };
    out.push(missingOf(f)); f.name = 'ERP'; out.push(missingOf(f)); f.api.base_url = 'https://x.invalid'; out.push(missingOf(f));
    f.api.endpoints.push({ name: 'bad name', path: '/a', params: [] }); out.push(missingOf(f)); f.api.endpoints[0].name = 'GetA'; f.api.endpoints[0].path = 'a'; out.push(missingOf(f));
    f.api.endpoints[0].path = '/a'; out.push(missingOf(f));
    f.method = 'mcp'; out.push(missingOf(f)); f.mcp.url = 'https://m.invalid/mcp'; out.push(missingOf(f)); f.mcp.tools.push({ name: 't' }); out.push(missingOf(f));
    return out;
  });
  assert.deepEqual(missing, ['에이전트 이름을 입력하세요', 'Base URL 을 입력하세요', '엔드포인트를 1개 이상 추가하세요',
    "'bad name' 은(는) 영문으로 시작하고 영문·숫자·밑줄만 쓸 수 있습니다", "'GetA' 의 경로는 / 로 시작해야 합니다", '',
    'MCP 서버 주소를 입력하세요', '[도구 가져오기]로 도구 목록을 받아 오세요', '']);
});

test('view mode shows the read-only registry with masked auth, status badges and the detail section', async t => {
  const page = await fixture(t, 'view');
  await page.evaluate(a => setList([a], { kind: 'agent', agentId: a.id }), SAVED);
  const rows = await page.$$eval('#rmAutoAgList .rm-da-agent', els => els.map(e => e.textContent.trim() + (e.classList.contains('sel') ? '*' : '')));
  assert.deepEqual(rows, ['MCPM코스메틱 이메일 에이전트', 'AI교육 에이전트', 'API사내 ERP*']);   // 2026-09-29 이메일 = MCP 연결 / email is an MCP connection
  assert.equal(await page.$$eval('[data-rmautomore]', els => els.length), 0);   // 조회 모드에는 ⋯ 없음 / no ⋯ in view mode
  const cards = await page.$$eval('#rmAutoSettings .rm-fcard-t', els => els.map(e => e.textContent.trim()));
  assert.equal(cards[0], '1. 에이전트 정보 Active');
  assert.match(cards[1], /^2\. API 엔드포인트 2개/);
  assert.ok((await page.textContent('#rmAutoSettings')).includes('Bearer 토큰 · ••••••'));
  assert.deepEqual(await page.$$eval('[data-rmwarow] .rm-api-status', els => els.map(e => e.textContent)), ['검증됨', '미검증']);
  assert.equal(await page.$$eval('#rmAutoSettings input, #rmAutoSettings select', els => els.length), 0);   // 편집 컨트롤 없음 / no edit controls
  await page.evaluate(() => { RM_WA.view['agent_ab12cd34'] = 0; renderRmAutoSettings(); });
  const detail = await page.$$eval('#rmAutoSettings .rm-fcard-t', els => els.map(e => e.textContent.trim()));
  assert.deepEqual(detail, ['3. 엔드포인트 상세', 'Parameters (JSON Schema)', 'Sample Response']);
  const text = await page.textContent('#rmAutoSettings');
  assert.ok(text.includes('"period"') && text.includes('"total": 5') && text.includes('← 목록으로'));
});

// 기본 제공 M코스메틱 이메일 에이전트(2026-09-29) — 서버 목록 builtin 의 MCP 연결을 등록 에이전트와 같은 열람 화면으로(조회 모드). 2026-10-06부터 리소스 추가 모드는 수정 폼(아래 테스트).
// The built-in M Cosmetic Email Agent (2026-09-29): the server list's builtin MCP connection in the registered agents' read-only view (view mode); since 2026-10-06 add mode opens an edit form (next test).
const BUILTIN = {
  id: 'agent_email', label: 'M코스메틱 이메일 에이전트', method: 'mcp', description: '고객 메일 분류',
  config: { url: '{{base_url}}/mock/mcosmetic/mcp', timeout: 30, auth: { type: 'bearer', key: '••••••', name: 'Authorization' },
    server_info: { name: 'M코스메틱 이메일 에이전트 MCP 서버', version: '1.0.0', protocol: '2025-06-18' },
    tools: [
      { name: 'get_mail', title: '메일 상세 조회', description: '메일 1건 조회', kind: 'read', enabled: true, unsupported: [],
        input_schema: { type: 'object', properties: { email_id: { type: 'string', description: '메일 ID' } }, required: ['email_id'] } },
      { name: 'send_reply', title: '답변 발송', description: '답변 발송', kind: 'action', enabled: true, unsupported: [],
        input_schema: { type: 'object', properties: { email_id: { type: 'string' }, draft: { type: 'string' } }, required: ['email_id'] } }] } };

test('the built-in M Cosmetic row opens its MCP connection from the server list, read-only in view mode', async t => {
  const page = await fixture(t, 'view');
  const panel = () => page.textContent('#rmAutoSettings');
  await page.evaluate(() => { RM_WA.loaded = true; rmAutoSel = { kind: 'email' }; renderRmAutoSettings(); });   // 목록 도착 전 / before the list
  assert.ok((await panel()).includes('연결 정보를 불러오는 중…'));
  await page.evaluate(b => { RM_WA.meta = { builtin: [b, { id: 'agent_edu', label: '교육 에이전트' }] }; RM_WA.list = []; rmAutoSel = { kind: 'email' }; renderRmAuto(); }, BUILTIN);
  const rows = await page.$$eval('#rmAutoAgList .rm-da-agent', els => els.map(e => e.textContent.trim() + (e.classList.contains('sel') ? '*' : '')));
  assert.deepEqual(rows, ['MCPM코스메틱 이메일 에이전트*', 'AI교육 에이전트']);
  assert.equal(await page.$$eval('[data-rmautomore]', els => els.length), 0);   // 기본 제공은 ⋯ 없음 / no ⋯ on built-in rows
  assert.deepEqual(await page.evaluate(() => rmWaBuiltin('agent_edu')), { id: 'agent_edu', name: '교육 에이전트', description: '', builtin: true, edited: false, updated_at: '' });   // 연결 설정 없이 설명만 / description only, no connection
  const cards = await page.$$eval('#rmAutoSettings .rm-fcard-t', els => els.map(e => e.textContent.trim()));
  assert.equal(cards[0], '1. 에이전트 정보 Active');
  assert.match(cards[1], /^2\. 도구 2개/);
  const text = await panel();
  for (const s of ['MCP', 'M코스메틱 이메일 에이전트', '{{base_url}}/mock/mcosmetic/mcp', 'Bearer 토큰 · ••••••', 'Timeout (초)30', '고객 메일 분류']) assert.ok(text.includes(s), s);
  // 인증 칸의 방식 이름은 따로 된 텍스트 노드라 EN 사전이 옮길 수 있다 / the auth type label is its own text node, so the EN dictionary can translate it
  assert.deepEqual(await page.$$eval('#rmAutoSettings .rm-ro > span', els => els.map(e => e.textContent)), ['Bearer 토큰']);
  assert.deepEqual(await page.$$eval('[data-rmwarow] .rm-api-method', els => els.map(e => e.textContent)), ['조회', '실행']);
  assert.equal(await page.$$eval('#rmAutoSettings input, #rmAutoSettings select, #rmAutoSaveBtn', els => els.length), 0);   // 편집 폼이 아니다 / not a form
  const detail = await page.evaluate(() => { const k = rmWaViewKey(); RM_WA.view[k] = 1; renderRmAutoSettings(); return k; });
  assert.equal(detail, 'agent_email');
  assert.deepEqual(await page.$$eval('#rmAutoSettings .rm-fcard-t', els => els.map(e => e.textContent.trim())), ['3. 도구 상세', 'Parameters (JSON Schema)']);
  const d = await panel();
  assert.ok(d.includes('send_reply') && d.includes('"draft"') && d.includes('← 목록으로'));
  await page.evaluate(() => { RM_WA.meta = null; RM_WA.err = '목록을 불러오지 못했습니다'; renderRmAutoSettings(); });   // 목록 실패 / list failed
  assert.ok((await panel()).includes('연결 정보를 불러오지 못했습니다'));
});

test('edit form builds the save body from the loaded agent and keeps the masked key', async t => {
  const page = await fixture(t, 'add');
  await page.evaluate(a => { setList([a], null); setForm(formOf(a), { kind: 'agent', agentId: a.id }); }, SAVED);   // 목록에 있는 에이전트를 추가 모드에서 연다 / open a listed agent in add mode
  assert.equal(await page.$$eval('[data-rmwamethod]', els => els.length), 0);   // 기존 에이전트는 방식 카드 없음 / no method cards when editing
  assert.equal(await page.inputValue('[data-wa="api.auth.key"]'), '••••••');
  assert.deepEqual(await page.$$eval('[data-rmwaep] td.k', els => els.map(e => e.textContent)), ['GetSalesSummary', 'ApproveOrder']);
  assert.equal(await page.$eval('#rmAutoSaveBtn', b => b.disabled), false);
  await page.evaluate(() => { rmAutoForm.ep = 1; renderRmAutoSettings(); });   // 행 클릭 위임은 페이지 스크립트에 있어 상태로 연다 / row-click delegation lives in the page script, so open via state
  const req = await page.$eval('[data-wa="api.endpoints.1.params.0.required"]', c => c.checked + '|' + c.disabled);
  assert.equal(req, 'true|true');   // 경로 변수는 항상 필수(잠김) / path variables stay required (locked)
  const body = await page.evaluate(() => bodyOf(rmAutoForm));
  assert.equal(body.method, 'api');
  assert.equal(body.config.auth.key, '••••••');
  assert.deepEqual(body.config.endpoints.map(e => e.name), ['GetSalesSummary', 'ApproveOrder']);
  assert.equal(body.config.endpoints[0].sample, '{"total": 5}');
  assert.equal(body.acting_user_id, '');
  // MCP 신규 폼: 방식 카드 2개, 도구 없으면 저장 불가 안내 / new MCP form: two method cards, cannot save without tools
  await page.evaluate(() => { const f = rmWaNewForm(); f.method = 'mcp'; f.name = '설비'; f.mcp.url = 'https://m.invalid/mcp'; setForm(f); });
  assert.deepEqual(await page.$$eval('[data-rmwamethod]', els => els.map(e => e.dataset.rmwamethod + ':' + e.classList.contains('sel'))), ['api:false', 'mcp:true']);
  assert.equal(await page.textContent('#rmWaMissing'), '[도구 가져오기]로 도구 목록을 받아 오세요');
  assert.equal(await page.$eval('#rmAutoSaveBtn', b => b.disabled), true);
  assert.ok((await page.textContent('#rmAutoSettings')).includes('도구 가져오기'));
});

// 기본 제공 에이전트 수정(2026-10-06) — 리소스 추가 모드에서 이메일은 MCP 수정 폼(이름 · 활성 고정, 도구 종류 잠금, Skills 없음), 교육은 설명 폼.
// 저장 = PUT /api/work-agents/builtin/<id>, 되돌리기 = DELETE(확인 창). / Editing built-in agents (2026-10-06) in add mode.
test('built-in agents open edit forms in add mode with a fixed name, locked tool kinds, and save or reset through /builtin', async t => {
  const page = await fixture(t, 'add');
  await page.evaluate(b => {
    RM_WA.meta = { builtin: [Object.assign({ edited: false, updated_at: '' }, b),
      { id: 'agent_edu', label: '교육 에이전트', description: '교육 콘텐츠 수집', edited: true, updated_at: '2026-10-06T10:00:00' }] };
    RM_WA.list = []; RM_WA.loaded = true; rmAutoSel = { kind: 'email' }; renderRmAuto();
  }, BUILTIN);
  assert.equal(await page.$eval('#rmAutoSettings input[aria-label="에이전트 이름"]', e => e.disabled + '|' + e.value), 'true|M코스메틱 이메일 에이전트');
  assert.ok((await page.textContent('#rmAutoSettings .rm-da-set-head')).includes('기본 제공'));
  assert.equal(await page.$('[data-rmwademo]'), null);    // 데모 채우기 없음 / no demo fill
  assert.equal(await page.$('[data-rmwareset]'), null);   // 고친 값이 없으면 되돌리기도 없다 / no reset without edits
  assert.equal(await page.$('[data-wa="enabled"]'), null);   // 활성은 고정 / always on
  assert.equal(await page.$('[data-wa-upbtn]'), null);       // Skills 없음 / no skill files
  assert.deepEqual(await page.$$eval('[data-wa$=".kind"]', els => els.map(e => e.disabled + ':' + e.value)), ['true:read', 'true:action']);
  assert.equal(await page.$eval('#rmAutoSaveBtn', b => b.disabled + '|' + b.textContent), 'false|저장');
  const body = await page.evaluate(() => { rmAutoForm.description = '사내 메일'; rmAutoForm.mcp.tools[1].enabled = false; return bodyOf(rmAutoForm); });
  assert.deepEqual(Object.keys(body).sort(), ['acting_user_id', 'config', 'description']);   // 이름 · 활성 · Skills 는 보내지 않는다 / no name, state or skills
  assert.equal(body.config.auth.key, '••••••');
  assert.equal(body.config.tools[1].enabled, false);
  const saved = await page.evaluate(async b => {
    const seen = [];
    window.fetch = (url, opt) => {
      seen.push([url, opt.method, JSON.parse(opt.body || 'null')]);
      return Promise.resolve({ ok: true, json: () => Promise.resolve(Object.assign({}, b, { description: '사내 메일', edited: true, updated_at: '2026-10-06T11:00:00' })) });
    };
    rmWaSave(); await new Promise(r => setTimeout(r, 30));
    return seen;
  }, BUILTIN);
  assert.deepEqual(saved.map(x => x[0] + ' ' + x[1]), ['/api/work-agents/builtin/agent_email PUT']);
  assert.equal(saved[0][2].description, '사내 메일');
  assert.ok(await page.$('[data-rmwareset]'));   // 저장 뒤 = 고친 값 있음 / edited after the save
  assert.equal(await page.inputValue('#rmWaDesc'), '사내 메일');
  const reset = await page.evaluate(async b => {
    const seen = []; window.confirm = () => true;
    window.fetch = (url, opt) => { seen.push(url + ' ' + opt.method); return Promise.resolve({ ok: true, json: () => Promise.resolve(Object.assign({}, b, { edited: false, updated_at: '' })) }); };
    rmWaReset(); await new Promise(r => setTimeout(r, 30));
    return seen;
  }, BUILTIN);
  assert.deepEqual(reset, ['/api/work-agents/builtin/agent_email?acting_user_id= DELETE']);
  assert.equal(await page.$('[data-rmwareset]'), null);
  // 교육 에이전트: 설명만 / the education agent: description only
  await page.evaluate(() => { rmAutoSel = { kind: 'edu' }; rmAutoForm = null; renderRmAutoSettings(); });
  assert.deepEqual(await page.$$eval('#rmAutoSettings [data-wa]', els => els.map(e => e.dataset.wa)), ['description']);
  assert.equal(await page.inputValue('#rmWaDesc'), '교육 콘텐츠 수집');
  assert.ok(await page.$('[data-rmwareset]'));
  assert.deepEqual(await page.evaluate(() => bodyOf(rmAutoForm)), { description: '교육 콘텐츠 수집', acting_user_id: '' });
  assert.equal(await page.$eval('#rmAutoSaveBtn', b => b.disabled), false);
  // 조회 모드는 종전처럼 열람만 / view mode still only reads
  await page.evaluate(() => { rmMode = 'view'; rmAutoSel = { kind: 'email' }; rmAutoForm = null; renderRmAutoSettings(); });
  assert.equal(await page.$$eval('#rmAutoSettings input, #rmAutoSettings select, #rmAutoSaveBtn', els => els.length), 0);
});
