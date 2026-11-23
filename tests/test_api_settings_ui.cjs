// Real editor functions in an isolated browser; all network requests are stubbed.
// 목업의 실제 편집기 함수를 격리 브라우저에서 실행한다. 네트워크는 전부 막거나 스텁으로 바꾼다.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const source = fs.readFileSync(path.join(__dirname, '../frontend/ai365-mockup.html'), 'utf8').replace(/\r\n/g, '\n');
const boardAdmin = fs.readFileSync(path.join(__dirname, '../static/board_admin.js'), 'utf8').replace(/\r\n/g, '\n');
function fn(name) {
  const start = source.indexOf('  function ' + name + '(');
  assert.ok(start >= 0, name);
  const end = source.indexOf('\n', start);
  return /}\s*$/.test(source.slice(start, end)) ? source.slice(start, end) : source.slice(start, source.indexOf('\n  }', start) + 4);
}
function line(rx) { const m = source.match(rx); assert.ok(m, String(rx)); return m[0]; }
let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });
// 실제 화면처럼 어댑터의 DS 토큰 블록(ai365DsTokens, --ds-*)을 목업 CSS 앞에 둔다(2026-10-28 부터 데모 전용 화면 · MCP 편집의 목업 CSS 가 --ds-* 를 쓴다).
// Like the real page, the adapter's DS token block (ai365DsTokens, --ds-*) goes before the mockup CSS (since 2026-10-28 the mockup CSS of the demo-only screens and the MCP editor uses --ds-*).
const adapterSrc = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8').replace(/\r\n/g, '\n');
const dsTokens = (() => {
  const a = adapterSrc.indexOf('(function ai365DsTokens()');
  assert.ok(a >= 0, 'ai365DsTokens block');
  const b = adapterSrc.indexOf('const css = `', a) + 'const css = `'.length, c = adapterSrc.indexOf('`;', b);
  return adapterSrc.slice(b, c);
})();
const styles = () => dsTokens + '\n' + [...source.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map(m => m[1]).join('\n');
// API 편집(2026-10-08 두 칸 화면): API · MCP 연결의 오른쪽 편집 카드(#pgConnScroll › .conn-layout › .conn-ed › #flApiPage)에 그린다.
// showPermSection 은 호출 기록 스텁, connRender 는 호출 횟수 스텁.
// The API editor (2026-10-08 two-pane screen) is drawn into the right editor card of API and MCP connections (#pgConnScroll › .conn-layout › .conn-ed ›
// #flApiPage); showPermSection is a recording stub and connRender counts its calls.
async function fixture(t) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 980 } });
  t.after(() => page.close());
  await page.route('**/*', route => route.abort());
  await page.setContent('<style>' + styles() + '</style><div class="pg-list-scroll" id="pgConnScroll"><div class="pg-list-inner conn-page"><div class="conn-layout">'
    + '<section class="conn-list"><div class="conn-list-body" id="connListBody"></div></section>'
    + '<section class="conn-ed" id="connEd"><div class="conn-host" id="flApiPage"></div><div class="conn-host" id="mcpPage" hidden></div><div class="conn-ed-empty" id="connEdEmpty" hidden></div></section>'
    + '</div></div></div>', {waitUntil:'domcontentloaded'});
  // 서버가 <head> 에 넣는 한국 시간 도우미(static/kst.js) — flApiTest 의 검증 시각이 쓴다 / the KST helpers the server injects; flApiTest's stamp uses them
  await page.addScriptTag({ path: path.join(__dirname, '../static/kst.js') });
  const names = [...source.matchAll(/^  function (flApi\w+)\(/gm)].map(m => m[1]);
  await page.addScriptTag({ content: `
    var FL={gres:{old:{}}}, CONN={meta:{auto_inputs:['question','user_name','user_no','date','time','month']}, tab:'api', sel:{api:null, mcp:null}, list:[]};
    var flApiOv=null, FLAPI_AUTO_INPUTS=[], FLAPI_TEST_NEUTRAL=['name','response.preview_chars','response.include_in_answer'];
    var MCF_BACK_IC='', MCF_DOC_IC='';
    ${line(/^  var FLAPI_VAR_RX=.*$/m)}
    function esc(v){const d=document.createElement('span');d.textContent=String(v??'');return d.innerHTML.replace(/"/g,'&quot;');}
    function toast(){} function connLoad(){window.loaded=true;} function rebuildConnectorsCard(){window.rebuilt=true;}
    function showPermSection(s){ (window.sections=window.sections||[]).push(s); }
    function connRender(){ window.rendered=(window.rendered||0)+1; }
    ${fn('flT')}
    ${names.map(fn).join('\n')}
    ${fn('connRefresh')}
    FL.api={draft:flApiDefault(),conn:{kind:'read',id:'cn_test'},desc:'입력값 테스트',vars:{},tab:'req',result:null,testing:false};
    Object.assign(FL.api.draft,{name:'ERP 재고 조회',url:'https://example.invalid/{{input.sku}}?qty={{input.qty}}',
      input_docs:[{name:'sku',description:'품목 코드',type:'string',required:true},{name:'qty',description:'요청 수량',type:'integer',required:false}]});
    flApiEl(); flApiRender();
  ` });
  return page;
}
// 워크플로우 편집기 노드 렌더(2026-09-26): 그룹 팔레트를 FL.gres 에 넣고 실제 flResData·flNodeHtml·flBindTableHtml 와 리소스 선택 팝업(flRm*, 2026-10-08)을 돌린다.
// Workflow editor node rendering (2026-09-26): the group palette sits in FL.gres and the real flResData/flNodeHtml/flBindTableHtml and the resource picker dialog (flRm*, 2026-10-08) run.
const PALETTE = {readable:{knowledge:true, data:true, groupware:true, auto:true}, resources:{
  knowledge_files:['규정.pdf'], tables:[], bi:[], gw_catalog:[],
  connectors:[{id:'cn_1', name:'ERP 조회', description:'매출 조회', kind:'read', source:'api', outputs:['total'],
    inputs:[{name:'period', description:'조회 월', example:'2026-08', default:''}],
    input_schema:{type:'object', properties:{period:{type:'string'}}}, output_schema:null}],
  auto_catalog:[
    {ns:'email', label:'M코스메틱 이메일 에이전트', items:[{key:'email.info.inbox', label:'확인 필요 메일', kind:'info'}]},
    {ns:'wa', agent_id:'agent_ab12cd34', label:'사내 ERP', method:'api', items:[
      {key:'wa:agent_ab12cd34:GetSalesSummary', label:'GetSalesSummary', kind:'read', description:'기간별 매출 요약',
        inputs:[{name:'period', description:'조회 월', example:'2026-08', default:'', required:true}],
        input_schema:{type:'object', properties:{period:{type:'string'}}, required:['period']}, output_schema:{type:'object', properties:{total:{type:'number'}}}},
      {key:'wa:agent_ab12cd34:ApproveOrder', label:'ApproveOrder', kind:'action', description:'주문 승인', inputs:[], input_schema:{type:'object', properties:{}}, output_schema:null}]},
    {ns:'wa', agent_id:'agent_mcp01', label:'설비 MCP', method:'mcp', items:[
      {key:'wa:agent_mcp01:read_sensor', label:'read_sensor', kind:'read', description:'센서 값 조회', inputs:[], input_schema:{type:'object'}, output_schema:null}]}]}};
async function editorFixture(t) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 980 } });
  t.after(() => page.close());
  await page.route('**/*', route => route.abort());
  await page.setContent('<style>' + styles() + '</style>', {waitUntil:'domcontentloaded'});
  await page.addScriptTag({ content: `
    var FL={resOpen:{}, rm:null, group:'g1', gres:{g1:${JSON.stringify(PALETTE)}}, meta:{agents:[], agent_labels:{}}};
    var FL_RES_IC='', MCF_DOC_IC='';
    function esc(v){const d=document.createElement('span');d.textContent=String(v??'');return d.innerHTML.replace(/"/g,'&quot;');}
    function flAgentOpts(a){ return '<option selected>'+a+'</option>'; }
    function flFlow(){ return window.FLOW||null; }
    function renderFl(){ window.RENDERS=(window.RENDERS||0)+1; }
    ${line(/^  var FL_INPUT_VARS=.*$/m)}
    ${line(/^  var FL_EXTRACT_AGENTS=.*$/m)}
    ${[...source.matchAll(/^  var FL_RM_\w+=.*$/gm)].map(m => m[0]).join('\n')}
    ${['flGres','flResData','flEn','flT','flIsWaKey','flWaItem','flWaOf','flToolOf','flAutoWaBad','flExtractHtml','flExtractSet',
       'flVarList','flVarLabel','mcfSchemaBtn','flBindTableHtml','flNodeHtml',
       'flRmIsDomain','flRmModel','flRmUnion','flRmVals','flRmState','flRmIndex','flRmSecOf','flRmToggle','flRmAll','flRmCkHtml','flRmRowsHtml',
       'flRmHtml','flRmNode','flRmOpen','flRmFocusSel','flRmRender','flRmFocusBtn','flRmClose','flRmApply','flRmBind'].map(fn).join('\n')}
  ` });
  return page;
}
test('type and required controls persist; docs fit across the page', async t => {
  const page = await fixture(t);
  await page.locator('[data-fa-doc="qty:type"]').selectOption('number');
  await page.locator('[data-fa-doc="sku:required"]').selectOption('0');   // 필수/선택 select(2026-09-18) / required/optional select
  const docs = await page.evaluate(() => flApiTestPayload(FL.api.draft).input_docs);
  assert.equal(docs[0].required, false);
  assert.equal(docs[1].type, 'number');
  assert.equal(docs[1].required, false);
  const size = await page.locator('#flApiDocs').evaluate(el => ({width:el.clientWidth, scroll:el.scrollWidth}));
  assert.ok(size.width > 700, JSON.stringify(size));
  assert.ok(size.scroll <= size.width + 1, JSON.stringify(size));
  if (process.env.API_UI_SCREENSHOT) await page.screenshot({ path: process.env.API_UI_SCREENSHOT });
});
// 오버레이 패널 CSS 가드(2026-09-26 회귀): API 등록이 페이지로 바뀐 뒤에도 전역 .flapi-ov/.flapi-panel 규칙은 남아야 한다. 게시판 관리 › 템플릿 등록·수정
// 패널(static/board_admin.js bdTplEl)이 이 규칙을 그대로 쓰기 때문이다. 지우면 패널이 body 끝의 일반 블록이 되어 [저장]이 화면 밖(y≈1800)으로 밀린다.
// 반대로 패널 전용 규칙(.flapi-tt 제목 크기, .flapi-body 스크롤)은 .flapi-panel 안으로 한정돼 API 페이지로 새지 않아야 한다.
// Overlay drawer CSS guard (2026-09-26 regression): the global .flapi-ov/.flapi-panel rules must survive the API page move, because Board management ›
// template register/edit (static/board_admin.js bdTplEl) uses them as is; without them the panel becomes a plain block at the end of body and [Save]
// falls off-screen (y≈1800). Conversely the drawer-only rules (.flapi-tt title size, .flapi-body scroll) stay scoped to .flapi-panel, off the API page.
test('overlay drawer rules stay for the board template panel and do not leak onto the API page', async t => {
  const css = styles();
  assert.match(css, /\.flapi-ov\{[^}]*position:fixed[^}]*\}/, '.flapi-ov{position:fixed…} rule is missing (board_admin.js template panel)');
  assert.match(css, /\.flapi-ov\.open\{[^}]*display:block[^}]*\}/, '.flapi-ov.open{display:block} rule is missing');
  assert.match(css, /\.flapi-panel\{[^}]*position:absolute[^}]*\}/, '.flapi-panel{position:absolute…} rule is missing');
  assert.match(css, /\.flapi-panel \.flapi-body\{[^}]*overflow-y:auto[^}]*\}/, '.flapi-panel .flapi-body{overflow-y:auto} rule is missing');
  assert.match(css, /\.flapi-foot\{[^}]*\}/, '.flapi-foot rule is missing');
  // 실제 게시판 관리 패널을 목업 CSS 로 연다(test_template_chat_ui.cjs 와 같은 소스 구간·스텁). API 페이지 틀도 같은 화면에 있다.
  // Open the real board-admin panel with the mockup CSS (same source slice and stubs as test_template_chat_ui.cjs); the API page frame is on the same screen.
  const page = await fixture(t);
  const a = boardAdmin.indexOf('  function bdTplDefault()'), b = boardAdmin.indexOf('  function bdTplPut(', a);
  assert.ok(a >= 0 && b > a, 'board_admin template editor slice');
  await page.evaluate(code => {
    window.BD_IC = ''; window.BD = {groups:null, canAll:true, tpl:null}; window.BD_FMT_LABEL = {docx:'Word', xlsx:'Excel', pptx:'PPT', pdf:'PDF'}; window.BD_STYLES = {docx:[['formal', '격식']]};
    window.AI365_ORG_GROUPS = []; window.bdActing = () => ''; window.bdLoad = () => {}; window.bdTranslate = () => {}; window.say = () => {}; window.bdFetch = async () => ({});
    window.eval(code); bdTplOpen(null);
  }, boardAdmin.slice(a, b));
  const lay = await page.evaluate(() => {
    const ov = document.getElementById('bdTplOv'), panel = ov.querySelector('.flapi-panel'), save = ov.querySelector('[data-bt-save]');
    const r = panel.getBoundingClientRect(), s = save.getBoundingClientRect(), de = document.documentElement;
    return { ovPos: getComputedStyle(ov).position, ovDisplay: getComputedStyle(ov).display, panelPos: getComputedStyle(panel).position,
      right: Math.round(r.right), width: Math.round(r.width), vw: de.clientWidth, vh: de.clientHeight, saveTop: Math.round(s.top), saveBottom: Math.round(s.bottom),
      bodyOverflow: getComputedStyle(ov.querySelector('.flapi-body')).overflowY, panelTitle: getComputedStyle(ov.querySelector('.flapi-tt')).fontSize,
      pageTitle: getComputedStyle(document.querySelector('#flApiPage .conn-ed-tt')).fontSize,
      pageBodyOverflow: getComputedStyle(document.getElementById('flApiBody')).overflowY,
      pageUsesDrawer: !!document.querySelector('#pgConnScroll .flapi-ov, #pgConnScroll .flapi-panel') };
  });
  assert.equal(lay.ovPos, 'fixed', JSON.stringify(lay));
  assert.equal(lay.ovDisplay, 'block');
  assert.equal(lay.panelPos, 'absolute');
  assert.equal(lay.right, lay.vw);                                        // 오른쪽에 붙은 패널 / docked on the right
  assert.equal(lay.width, 860);
  assert.ok(lay.saveTop >= 0 && lay.saveBottom <= lay.vh, JSON.stringify(lay));   // [저장]이 화면 안 / [Save] is on screen
  assert.equal(lay.bodyOverflow, 'auto');                                 // 패널 본문만 스크롤 / only the panel body scrolls
  assert.equal(lay.panelTitle, '20px');                                   // 서랍 제목 = Dev 대화 상자 제목 20(PopUpLayout.tsx, 2026-10-28) / drawer title: the Dev dialog title 20
  assert.equal(lay.pageTitle, '16px');                                    // 편집 카드 제목 = 글자 단계 16(시안 2026-10-08, 2026-10-28 단계 맞춤), 패널 제목 규칙이 새지 않는다 / the editor card title on the 16 step; the drawer title rule does not leak
  assert.equal(lay.pageBodyOverflow, 'visible');                          // 페이지 본문은 스크롤 상자가 아니다 / the page body is not a scroll box
  assert.equal(lay.pageUsesDrawer, false);                                // API 페이지는 패널 틀을 쓰지 않는다 / the API page does not use the drawer
});
test('API test does not certify settings edited while request is pending', async t => {
  const page = await fixture(t);
  await page.evaluate(() => {
    window.fetch = () => new Promise(resolve => { window.finish = () => resolve({ok:true,json:async()=>({ok:true,status:200})}); });
    flApiTest(); FL.api.conn.kind='action'; flApiTouch(); window.finish();
  });
  await page.waitForFunction(() => !FL.api.testing);
  assert.equal(await page.evaluate(() => FL.api.draft.test), null);
  assert.equal(await page.evaluate(() => FL.api.result), null);
});
test('test response for a closed editor cannot overwrite another API', async t => {
  const page = await fixture(t);
  await page.evaluate(() => {
    window.fetch = () => new Promise(resolve => { window.finish = () => resolve({ok:true,json:async()=>({ok:true,status:200})}); });
    flApiTest();
    FL.api={draft:flApiDefault(),conn:{kind:'read'},vars:{},tab:'req',testing:false,result:null};
    window.finish();
  });
  await page.evaluate(() => new Promise(resolve => setTimeout(resolve, 20)));
  assert.equal(await page.evaluate(() => FL.api.draft.test), null);
});
test('registry mutation invalidates workflow resources and refreshes permission nodes', async t => {
  const page = await fixture(t);
  await page.evaluate(() => {
    window.fetch = async () => ({ok:true,json:async()=>({pvtree:[{id:'p_conn',children:[{id:'cn_new',label:'새 API'}]}]})});
    connRefresh();
  });
  await page.waitForFunction(() => window.rebuilt);
  assert.deepEqual(await page.evaluate(() => FL.gres), {});
  assert.equal(await page.evaluate(() => window.AI365_CONNECTOR_NODES[0].id), 'cn_new');
});
test('tool schema line and value fields replace the per-row pick menu; stored variables still show as chips', async t => {
  const page = await fixture(t);
  // 2026-09-26: 행마다 있던 [가져오기] 목록 폐지 → 표 맨 위 도구 단위 명세 줄(입력 명세·출력 명세 [명세 보기], 없으면 '없음')
  // 2026-09-26: the per-row [Pick from] list is gone → a per-tool schema line tops the table ([View schema], or '없음' when absent)
  await page.addScriptTag({content:`
    function flFlow(){return {stages:[{nodes:[{agent:'api',resources:['cn_test']},{agent:'api',resources:['cn_test']}]}]};}
    function flResData(){return [{v:'cn_test',outputs:['id'],tool:'재고 조회'}]};
    ${line(/^  var FL_INPUT_VARS=.*$/m)}
    ${['flEn','flIsWaKey','flWaItem','flWaOf','flToolOf','flVarList','flVarLabel','mcfSchemaBtn','flBindTableHtml'].map(fn).join('\n')}
  `});
  const IN = {type:'object', properties:{sku:{type:'string'}}};
  const markup = await page.evaluate(IN => ({
    optional:flBindTableHtml('1:0',1,{inputs:[{name:'qty',required:false}], input_schema:IN, output_schema:null},{}),
    required:flBindTableHtml('1:0',1,{inputs:[{name:'sku',required:true}], input_schema:IN, output_schema:{type:'object'}},{}),
    fixed:flBindTableHtml('1:0',1,{inputs:[{name:'sku'}], input_schema:IN},{input_bindings:{sku:{mode:'value',value:'{{step1.task2.id}}'}}}),
    asked:flBindTableHtml('1:0',1,{inputs:[{name:'qty',required:false}], input_schema:IN},{input_bindings:{qty:{mode:'ask'}}}),
    typed:flBindTableHtml('1:0',1,{inputs:[{name:'sku'}], input_schema:IN},{input_bindings:{sku:{mode:'value',value:'SKU-1'}}}),
    none:flBindTableHtml('1:0',1,{inputs:[], input_schema:IN, output_schema:{type:'object'}},{})
  }), IN);
  for (const k of Object.keys(markup)) {
    assert.doesNotMatch(markup[k], /data-flbvar|flapi-varmenu|가져오기/, k);   // 행마다의 [가져오기] 없음 / no per-row pick menu
    assert.match(markup[k], /^<div class="fl-node-binds"><div class="fl-node-schemas">/, k);   // 명세 줄이 표 맨 위 / schema line on top
    assert.match(markup[k], /data-flschema="1:0:in"/, k);
  }
  assert.match(markup.required, /data-flschema="1:0:out"/);
  assert.equal((markup.required.match(/명세 보기/g) || []).length, 2);
  assert.doesNotMatch(markup.optional, /data-flschema="1:0:out"/);   // 출력 명세가 없으면 버튼 대신 '없음' / no output schema → '없음'
  assert.match(markup.optional, /<span class="mcf-none">없음<\/span>/);
  assert.match(markup.optional, /선택값/);
  assert.match(markup.optional, /값 없이 실행합니다/);
  assert.match(markup.optional, /data-flbval="1:0:qty"/);
  assert.match(markup.required, /필수값/);
  assert.match(markup.required, /실행 중에 묻습니다/);
  assert.match(markup.required, /비우면 실행 시 요청과 앞 단계 결과에서 찾습니다/);   // 새 바닥 힌트 / new footer hint
  assert.match(markup.fixed, /fl-inchip/);
  assert.match(markup.fixed, /1단계 · 재고 조회 · id/);           // 칩 라벨은 도구 제목 + 출력 변수 / chip label = tool title + output
  assert.match(markup.fixed, /data-flbclear="1:0:sku"/);
  assert.doesNotMatch(markup.fixed, /\{\{step1\.task2\.id\}\}<\/span>/);   // 괄호 문법은 화면에 없음 / no brace syntax on screen
  assert.match(markup.asked, /항상 실행 중에 질문/);
  assert.match(markup.typed, /data-flbval="1:0:sku" value="SKU-1"/);   // 적은 값은 값 칸에 그대로 / a typed value stays in the field
  assert.match(markup.none, /필요 입력값 없음/);                   // 입력값이 없어도 명세 줄은 보인다 / schema line even without inputs
  assert.match(markup.none, /data-flschema="1:0:out"/);
});
test('knowledge, data and groupware tasks carry the optional extraction prompt; other kinds do not', async t => {
  const page = await editorFixture(t);
  const r = await page.evaluate(() => {
    const html = {};
    html.knowledge = flNodeHtml(0, 0, {agent:'knowledge', resources:[], instruction:'', extract_prompt:'기간은 꼭 찾기'});
    ['data', 'groupware', 'web', 'auto', 'api'].forEach(a => { html[a] = flNodeHtml(0, 1, {agent:a, resources:[], instruction:''}); });
    html.apiPicked = flNodeHtml(0, 2, {agent:'api', resources:['cn_1'], instruction:''});
    const n = {agent:'data'}; flExtractSet(n, ' 월과 지점 '); const kept = n.extract_prompt;
    flExtractSet(n, '   '); const dropped = !('extract_prompt' in n);
    return {html, kept, dropped};
  });
  assert.match(r.html.knowledge, /<label>필수값 추출 프롬프트 \(선택\)<\/label><input type="text" maxlength="500" data-flextract="0:0"/);
  assert.match(r.html.knowledge, /value="기간은 꼭 찾기"/);
  assert.match(r.html.knowledge, /placeholder="예: 조회 기간\(월\)과 사업장 코드는 요청에서 꼭 찾아 쓰고, 없으면 실행 전에 물어봅니다"/);
  assert.match(r.html.data, /data-flextract="0:1" [^>]*value=""/);
  assert.match(r.html.groupware, /data-flextract="0:1"/);
  for (const k of ['web', 'auto', 'api', 'apiPicked']) assert.doesNotMatch(r.html[k], /data-flextract/, k);
  assert.match(r.html.apiPicked, /data-flschema="0:2:in"/);            // 외부 도구 = 명세 줄 + 입력값 표 / external tool = schema line + inputs
  assert.match(r.html.apiPicked, /<span class="mcf-none">없음<\/span>/);  // 이 API 는 출력 명세 없음 / this API has no output schema
  assert.equal(r.kept, ' 월과 지점 ');
  assert.equal(r.dropped, true);                                        // 빈 값 = 키 삭제 / blank = key removed
});
test('automation picker dialog lists registered-agent sections; a tool pick is exclusive and Done brings the input table', async t => {
  // 리소스 선택 팝업(2026-10-08): 고른 것은 초안(FL.rm.draft)에만 있고 [선택 완료](flRmApply) 때 작업에 들어간다. 화면 흐름은 test_flow_resource_picker_ui.cjs
  // Resource picker dialog (2026-10-08): picks stay in the draft (FL.rm.draft) until [Done] (flRmApply); the screen flow lives in test_flow_resource_picker_ui.cjs
  const page = await editorFixture(t);
  const r = await page.evaluate(() => {
    const n = {agent:'auto', resources:['email.info.inbox'], instruction:'취합 지침'};
    window.FLOW = {stages:[{nodes:[n]}]};
    const snap = () => JSON.parse(JSON.stringify(n));
    const pick = key => { const st = FL.rm; flRmToggle(st, flRmIndex(st.roots, {})[key]); return st.draft.slice(); };
    flRmOpen('0:0');
    FL.rm.open['sw:agent_ab12cd34'] = true; flRmRender();   // 사내 ERP 섹션도 펼침(설비 MCP 는 접힘) / open the ERP section too (the MCP one stays folded)
    const before = document.getElementById('flRmOv').innerHTML;
    const picked = pick('si:wa:agent_ab12cd34:GetSalesSummary');
    const switched = pick('si:wa:agent_ab12cd34:ApproveOrder');
    const builtin = pick('si:email.info.inbox');               // 다른 에이전트(내장) = 앞 선택 해제 / another (built-in) agent clears the earlier pick
    const replaced = pick('si:wa:agent_mcp01:read_sensor');
    const cleared = pick('si:wa:agent_mcp01:read_sensor');     // 같은 도구 재클릭 = 해제 / re-clicking the tool clears it
    const untouched = snap();                                  // 초안만 바뀐다 / only the draft changed
    pick('si:wa:agent_ab12cd34:GetSalesSummary'); flRmApply(); const applied = snap(), gone = !document.getElementById('flRmOv');
    n.input_bindings = {period:{mode:'value', value:'2026-08'}};
    const pickedHtml = flNodeHtml(0, 0, n);
    const tool = flToolOf(n) && flToolOf(n).tool;
    flRmOpen('0:0'); flRmApply(); const kept = snap();                                                  // 같은 도구 = 바인딩 유지 / same tool keeps the bindings
    flRmOpen('0:0'); pick('si:wa:agent_ab12cd34:ApproveOrder'); flRmApply(); const reset = snap();      // 다른 도구 = 초기화 / another tool resets them
    flRmOpen('0:0'); pick('si:email.info.inbox'); flRmClose(); const cancelled = snap();               // 닫기 = 버림 / closing discards
    const bad = [['wa:x:a', 'email.info.inbox'], ['wa:x:a', 'wa:x:b'], ['wa:x:a'], ['email.info.inbox', 'edu.info.audit']]
      .map(res => flAutoWaBad({agent:'auto', resources:res}));
    // 내장 항목과 섞인 옛 상태: 버튼은 '작업 N개', 같은 도구 줄 = 그 도구만 남기고 바인딩 유지 / legacy mix: count label; the same tool keeps only it and its bindings
    const mixed = {agent:'auto', resources:['wa:agent_ab12cd34:GetSalesSummary', 'email.info.inbox'], instruction:'', input_bindings:{period:{mode:'value', value:'2026-07'}}};
    window.FLOW = {stages:[{nodes:[mixed]}]};
    const mixedHtml = flNodeHtml(0, 0, mixed);
    flRmOpen('0:0'); pick('si:wa:agent_ab12cd34:GetSalesSummary'); flRmApply(); const mixedFixed = JSON.parse(JSON.stringify(mixed));
    window.FLOW = {stages:[{nodes:[{agent:'auto', resources:['wa:agent_ab12cd34:GetSalesSummary']}]}, {nodes:[{agent:'api', resources:['cn_1']}]}]};
    const label = flVarLabel('step1.task1.result', 1);
    return {before, picked, switched, builtin, replaced, cleared, untouched, applied, gone, renders: window.RENDERS, pickedHtml, tool, kept, reset, cancelled, bad, label, mixedHtml, mixedFixed};
  });
  // 섹션 제목 '<에이전트 이름> · API|MCP', 펼친 등록 에이전트 섹션은 도구마다 설명 한 줄 + 도구 1개 안내 / section titles; an open registered-agent section shows one description line per tool and the one-tool hint
  assert.match(r.before, /<span class="flrm-lb">사내 ERP<span class="flrm-via"> · API<\/span><\/span>/);
  assert.match(r.before, /<span class="flrm-lb">설비 MCP<span class="flrm-via"> · MCP<\/span><\/span>/);
  assert.match(r.before, /data-flrm-ck="si:wa:agent_ab12cd34:GetSalesSummary"/);
  assert.match(r.before, /<span class="flrm-desc">기간별 매출 요약<\/span>/);   // 설명은 줄 상자 안 둘째 줄 / the description is a second line inside the row
  assert.match(r.before, /등록 에이전트 도구는 하나만 고를 수 있습니다/);
  assert.match(r.before, /<span class="flrm-dnote">에이전트 1개만<\/span>/);
  assert.match(r.before, /<span class="flrm-selcnt">1 선택<\/span>/);
  assert.doesNotMatch(r.before, /read_sensor/);          // 접힌 섹션의 항목은 그리지 않는다 / folded section items are not drawn
  assert.deepEqual(r.picked, ['wa:agent_ab12cd34:GetSalesSummary']);
  assert.deepEqual(r.switched, ['wa:agent_ab12cd34:ApproveOrder']);
  assert.deepEqual(r.builtin, ['email.info.inbox']);
  assert.deepEqual(r.replaced, ['wa:agent_mcp01:read_sensor']);
  assert.deepEqual(r.cleared, []);
  assert.deepEqual(r.untouched.resources, ['email.info.inbox']);
  assert.deepEqual(r.applied, {agent:'auto', resources:['wa:agent_ab12cd34:GetSalesSummary'], instruction:'취합 지침'});
  assert.equal(r.gone, true);
  assert.ok(r.renders >= 1);
  assert.match(r.pickedHtml, /<span class="fl-resbtn-tx">사내 ERP · GetSalesSummary<\/span>/);
  assert.match(r.pickedHtml, /data-flschema="0:0:in"/);
  assert.match(r.pickedHtml, /data-flschema="0:0:out"/);
  assert.match(r.pickedHtml, /data-flbval="0:0:period" value="2026-08"/);
  assert.match(r.pickedHtml, /data-flinstr="0:0" placeholder="작업 내용을 입력하세요" value="취합 지침"/);   // 자유 입력(취합 지침) 유지 / free text kept
  assert.doesNotMatch(r.pickedHtml, /data-flextract/);
  assert.doesNotMatch(r.pickedHtml, /class="fl-res[ "]|flrm-/);   // 업무 자동화는 작업 안에 트리를 그리지 않는다(팝업) / no inline tree for automation (dialog)
  assert.equal(r.tool, 'GetSalesSummary');
  assert.deepEqual(r.kept.input_bindings, {period:{mode:'value', value:'2026-08'}});
  assert.deepEqual(r.reset, {agent:'auto', resources:['wa:agent_ab12cd34:ApproveOrder'], instruction:'취합 지침'});
  assert.deepEqual(r.cancelled.resources, ['wa:agent_ab12cd34:ApproveOrder']);
  assert.deepEqual(r.bad, [true, true, false, false]);
  assert.equal(r.label, '1단계 · GetSalesSummary 결과');   // 앞 단계 등록 에이전트 도구 = 도구 이름 라벨 / tool-name label for earlier wa tasks
  assert.match(r.mixedHtml, /작업 2개/);
  assert.doesNotMatch(r.mixedHtml, /fl-resbtn-tx">사내 ERP · GetSalesSummary/);
  assert.deepEqual(r.mixedFixed.resources, ['wa:agent_ab12cd34:GetSalesSummary']);
  assert.deepEqual(r.mixedFixed.input_bindings, {period:{mode:'value', value:'2026-07'}});
});
test('the API editor lives in the right pane: opening keeps the section, the head has title, usage and delete, Cancel goes through connRender', async t => {
  // 2026-10-08 두 칸 화면: 등록 페이지 · 브레드크럼 · 뒤로 버튼은 없고, 편집 카드 머리(제목 · 사용 현황 · [샘플][삭제]) + 바닥 [취소][저장]
  // 2026-10-08 two-pane screen: no registration page, crumb or back button; the editor card head (title, usage, [sample][delete]) + footer [Cancel][Save]
  const page = await fixture(t);
  await page.addScriptTag({ content: [fn('flEn'), fn('connActor'), fn('connApiOpen')].join('\n') });
  await page.evaluate(() => {
    window.sections = []; window.rendered = 0;
    window.fetch = async u => ({ok:true, json: async () => (String(u).includes('/usage') ? {workflows:[{name:'월간 보고', stage:2, task:1}]} : null)});
    connApiOpen({id:'cn_x', name:'ERP', description:'설명', kind:'read', category:'erp', enabled:true, api:{name:'ERP', method:'GET', url:'https://x.invalid'}});
  });
  await page.waitForFunction(() => document.getElementById('flApiUsage').style.display === '');
  const opened = await page.evaluate(() => ({
    sections: window.sections.slice(),
    title: document.querySelector('#flApiPage .conn-ed-hd .flapi-tt').textContent,
    usage: document.getElementById('flApiUsage').innerHTML,
    overlay: !!document.querySelector('.flapi-ov, #flApiOv, .flapi-foot, [data-flapi-close], #flApiPage .mcf-back, #apiCrumbList'),
    acts: [...document.querySelectorAll('#flApiPage .conn-ed-acts > *')].map(e => e.className + (e.hidden ? ':hidden' : '')),
    foot: [...document.querySelectorAll('#flApiPage .conn-ed-ft button')].map(b => b.textContent),
    tabs: [...document.querySelectorAll('#flApiPage .conn-subtabs button')].map(b => b.textContent),
    base: FL.api.base === flApiSnap(),
  }));
  assert.deepEqual(opened.sections, []);                  // 같은 화면의 오른쪽 칸 / the right pane of the same screen
  assert.equal(opened.title, 'API 수정');
  assert.equal(opened.usage, '<span>사용 중인 워크플로우</span>: 월간 보고 (2단계 1번 작업). <span>API 변경 사항은 다음 호출부터 적용됩니다.</span>');
  assert.equal(opened.overlay, false);                    // 오버레이 · 뒤로 버튼 · 브레드크럼 없음 / no overlay, back button or crumb
  assert.deepEqual(opened.acts, ['flapi-sample', 'conn-delbtn']);
  assert.deepEqual(opened.foot, ['취소', '저장']);
  assert.deepEqual(opened.tabs, ['요청 설정', '응답 설정', '테스트']);
  assert.equal(opened.base, true);                        // 열 때 바뀜 판정 기준을 둔다 / the dirty baseline is taken on open
  await page.click('#flApiPage .conn-ed-ft [data-flapi-cancel]');
  assert.deepEqual(await page.evaluate(() => [FL.api, CONN.sel.api, window.rendered]), [null, 'cn_x', 1]);   // 저장된 API 는 connRender 가 다시 연다 / connRender reopens a saved API
  // 새 API = '추가' 제목 · 삭제와 사용 현황 숨김, [취소] = 초안 버리기 / a new API: 'add' title, delete and usage hidden; Cancel drops the draft
  await page.evaluate(() => { connApiOpen(null); });
  assert.equal(await page.textContent('#flApiPage .flapi-tt'), 'API 추가');
  assert.equal(await page.evaluate(() => document.querySelector('#flApiPage [data-flapi-del]').hidden), true);
  assert.equal(await page.evaluate(() => document.getElementById('flApiUsage').style.display), 'none');
  await page.click('#flApiPage [data-flapi-cancel]');
  assert.deepEqual(await page.evaluate(() => [FL.api, CONN.sel.api, window.rendered]), [null, null, 2]);
});

// 단계별 답변 프롬프트·파일 생성(2026-09-29 사용자 지시): 마지막 단계에도 나오고 '최종 답변 프롬프트'·'파일 생성 결정' 카드는 없다.
// 안내 문장은 마지막 단계(= 최종 답변)·중간 단계(앞 단계 기록 참고)·단일 단계에 따라 다르고, 문장마다 한 요소라 EN 사전이 번역한다.
// Per-stage answer prompt and file output (user request 2026-09-29): the last stage shows them too and the 'final answer prompt' and
// 'file-output decision' cards are gone. Hints differ for the last stage (= final answer), middle stages and a single stage.
test('every stage, the last one included, has its answer prompt and file output; the final cards are gone', async t => {
  const page = await editorFixture(t);
  await page.addScriptTag({ content: `
    var FL_TRASH_IC='';
    ${line(/^  var FL_DOC_FMTS=.*$/m)}
    function flGroupBarHtml(){ return ''; }
    function flGroupFlows(){ return window.FLOW ? [window.FLOW] : []; }
    function flLoadGres(){}
    function flNodeHtml(){ return '<div class="fl-node"></div>'; }
    ${fn('flStageApHint')}
    ${fn('flFlowsHtml')}
  ` });
  const r = await page.evaluate(() => {
    const stage = (ap, dg) => ({nodes:[{agent:'data', resources:[], instruction:''}], answer_prompt:ap, docgen:dg});
    const out = {};
    window.FLOW = {id:'fl_t', name:'테스트', group:'g1', description:'', stages:[stage('1단계 지침', null), stage('', {format:'pdf', instruction:'표 중심'}), stage('최종 지침', null)]};
    FL.sel = 'fl_t';
    document.body.innerHTML = '<div id="flBody">' + flFlowsHtml() + '</div>';
    out.prompts = [...document.querySelectorAll('[data-flstageprompt]')].map(x => [x.dataset.flstageprompt, x.value]);
    out.placeholders = [...document.querySelectorAll('[data-flstageprompt]')].map(x => x.placeholder);
    out.docs = [...document.querySelectorAll('[data-flstagedoc]')].map(x => [x.dataset.flstagedoc, x.value]);
    out.docInstr = [...document.querySelectorAll('[data-flstagedocinstr]')].map(x => [x.dataset.flstagedocinstr, x.value]);
    out.hints = [...document.querySelectorAll('.fl-stage-ap .fl-dochint')].map(x => x.textContent);
    out.labels = [...document.querySelectorAll('.fl-stage-ap-lb')].map(x => x.textContent);
    out.cards = [...document.querySelectorAll('.fl-card-tt')].map(x => x.textContent);
    out.retired = ['#flAgg', '#flDocFmt', '#flDocInstr'].map(q => !!document.querySelector(q));
    window.FLOW = {id:'fl_t', name:'한 단계', group:'g1', description:'', stages:[stage('', null)]};
    document.body.innerHTML = '<div id="flBody">' + flFlowsHtml() + '</div>';
    out.single = [...document.querySelectorAll('.fl-stage-ap .fl-dochint')].map(x => x.textContent);
    return out;
  });
  assert.deepEqual(r.prompts, [['0', '1단계 지침'], ['1', ''], ['2', '최종 지침']]);   // 마지막(3단계)에도 / the last stage too
  assert.deepEqual(r.docs, [['0', ''], ['1', 'pdf'], ['2', '']]);
  assert.deepEqual(r.docInstr, [['1', '표 중심']]);
  assert.deepEqual(r.labels, ['1단계 답변 프롬프트 (선택)', '1단계 파일 생성 (선택)', '2단계 답변 프롬프트 (선택)', '2단계 파일 생성 (선택)',
                              '3단계 답변 프롬프트 (선택)', '3단계 파일 생성 (선택)']);
  assert.deepEqual(r.hints, [
    '이 단계가 끝났을 때 단계 결과를 보고하는 지침입니다. 비우면 기본 보고 형식으로 정리합니다.',
    '이 단계 보고가 끝나면 그 보고로 파일을 만들고 나서 다음 단계 실행을 묻습니다. 지침은 파일을 생성할 때만 적용됩니다.',
    '이 단계가 끝났을 때 단계 결과를 보고하는 지침입니다. 앞 단계의 결과와 답변도 함께 참고합니다. 비우면 기본 보고 형식으로 정리합니다.',
    '이 단계 보고가 끝나면 그 보고로 파일을 만들고 나서 다음 단계 실행을 묻습니다. 지침은 파일을 생성할 때만 적용됩니다.',
    '마지막 단계의 답변이 최종 답변이 됩니다. 앞 단계의 결과와 답변을 모두 참고합니다. 비우면 기본 형식으로 정리합니다.',
    '이 단계 답변이 끝나면 그 답변으로 파일을 만듭니다. 지침은 파일을 생성할 때만 적용됩니다.']);
  assert.deepEqual(r.cards, ['기본 정보', '실행 흐름 ⓘ']);                  // 최종 카드 2장 없음 / no final cards
  assert.deepEqual(r.retired, [false, false, false]);
  assert.equal(r.single[0], '이 단계의 답변이 최종 답변이 됩니다. 비우면 기본 형식으로 정리합니다.');
  // 마지막 단계 입력칸은 최종 답변 문구(리뷰 2026-09-29) / the last stage's box reads as the final answer
  const reportPh = '이 단계 결과를 보고할 때의 형식과 기준을 지시하세요. 예: 확인한 규정을 체크리스트로 요약, 출처 문서 표시';
  const finalPh = '최종 답변의 형식과 구성을 지시하세요. 예: 경영진 보고 형식으로 핵심 요약, 세부, 후속 액션 순, 숫자는 표로';
  assert.deepEqual(r.placeholders, [reportPh, reportPh, finalPh]);
  const src = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8');
  for (const h of new Set([...r.hints, ...r.single, reportPh, finalPh])) assert.ok(src.includes(`'${h}': '`), h);   // EN 사전 / EN dictionary entries
});
