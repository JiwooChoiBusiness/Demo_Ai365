// M코스메틱 이메일 에이전트 배선(2026-09-28) — 리소스 센터 업무 자동화 카드·showEmailAgent(view)·업무 자동화 탭의 MCP 연결 배선
// (2026-09-29, 종전 열람 전용 API 레지스트리 대체, 목업), 스마트 파일 트리 이름 덮어쓰기·EN 사전(adapter). 실제 목업·어댑터 코드를
// 격리 브라우저에서 돌리고 네트워크는 전부 막는다.
// M Cosmetic Email Agent wiring (2026-09-28) — Resource Center automation cards, showEmailAgent(view) and the automation tab's
// MCP connection wiring (2026-09-29, replacing the read-only API registry; mockup); the smart-file tree name override and the
// EN dictionary (adapter). Real code in an isolated browser, no network.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const mockup = fs.readFileSync(path.join(__dirname, '../frontend/ai365-mockup.html'), 'utf8').replace(/\r\n/g, '\n');
const adapter = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8').replace(/\r\n/g, '\n');
function fn(name) {   // 목업 IIFE 안의 2칸 들여쓰기 함수 / a two-space indented function inside the mockup IIFE
  const start = mockup.indexOf('  function ' + name + '(');
  assert.ok(start >= 0, name);
  const end = mockup.indexOf('\n', start);
  return /}\s*$/.test(mockup.slice(start, end)) ? mockup.slice(start, end) : mockup.slice(start, mockup.indexOf('\n  }', start) + 4);
}
function slice(src, from, to) {
  const i = src.indexOf(from);
  assert.ok(i >= 0, from);
  const j = src.indexOf(to, i);
  assert.ok(j > i, to);
  return src.slice(i, j + to.length);
}
const EMAIL_LABEL = 'M코스메틱 이메일 에이전트';
let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });
async function page(t, html, script) {
  const p = await browser.newPage();
  t.after(() => p.close());
  await p.route('**/*', route => route.abort());
  await p.setContent(html, { waitUntil: 'domcontentloaded' });
  await p.addScriptTag({ content: script });
  return p;
}

// 2026-09-29: 업무 메뉴 카드 4장(견적요청·주문등록·출하일정·인보이스 발행요청) 삭제 — 업무 자동화 카드는 이메일·교육 2장뿐이다.
// showEmailAgent(view)의 #view= 경로는 함수에 그대로 남아 아래에서 직접 검증한다.
// 2026-09-29: the four work-menu cards are removed, leaving the email and edu cards; showEmailAgent(view) keeps its #view= path.
test('resource center shows only the email and edu agent cards; showEmailAgent opens /email#view= and rebuilds only on change', async t => {
  const cards = slice(mockup, "$('#rcAutomationGrid').innerHTML = `", '</button>`;');
  const p = await page(t, '<div id="viewResource"><div class="sub-header"></div><div class="rc-scroll"><div id="rcAutomationGrid"></div></div>'
    + '<div id="rcManageScroll"></div><div id="emailAgentScroll" style="display:none"><div class="ea-body">'
    + '<iframe class="ea-embed" title="t" src="/email"></iframe></div></div></div>',
    'const $ = s => document.querySelector(s);\n' + cards + '\n' + fn('showEmailAgent') + '\nwindow.showEmailAgent = showEmailAgent;');
  const grid = await p.$$eval('#rcAutomationGrid .rc-card', els => els.map(e => ({
    title: e.querySelector('.rc-card-title').textContent, desc: e.querySelector('.rc-card-desc').textContent,
    agent: e.getAttribute('data-emailagent'), view: e.getAttribute('data-emailview'), rc: e.getAttribute('data-rc') })));
  assert.deepEqual(grid.map(c => c.title), [EMAIL_LABEL, '교육 에이전트']);
  assert.deepEqual(grid.map(c => c.view), [null, null]);
  assert.deepEqual(grid.map(c => c.agent), ['1', null]);
  assert.ok(!mockup.includes('RC_EMAIL_VIEW_CARDS'));                            // 삭제된 카드 정의 없음 / the removed card list is gone
  assert.ok(grid.every(c => c.rc === null));                                     // 자리 표시 카드 없음 / no placeholder cards
  assert.ok(grid.every(c => !/—/.test(c.title + c.desc)));                        // 화면 문구 em dash 금지 / no em dash
  // 카드 위임은 data-emailview 를 첫 메뉴로 넘긴다 / the delegation passes data-emailview as the first menu
  assert.ok(mockup.includes("const emc=e.target.closest('[data-emailagent]'); if(emc){ showEmailAgent(emc.dataset.emailview||''); return; }"));
  const r = await p.evaluate(() => {
    const src = () => document.querySelector('#emailAgentScroll iframe.ea-embed').getAttribute('src');
    const el = () => document.querySelector('#emailAgentScroll iframe.ea-embed');
    const first = el();
    showEmailAgent('');
    const same0 = el() === first;
    showEmailAgent('quote');
    const quote = { src: src(), rebuilt: el() !== first, count: document.querySelectorAll('iframe.ea-embed').length,
      shown: document.getElementById('emailAgentScroll').style.display, grid: document.querySelector('.rc-scroll').style.display };
    const q = el();
    showEmailAgent('quote');
    const kept = el() === q;
    showEmailAgent('invoice');
    const invoice = src();
    showEmailAgent();
    return { same0, quote, kept, invoice, back: src(), title: el().getAttribute('title') };
  });
  assert.equal(r.same0, true);                                                    // 같은 주소면 그대로 / same address keeps it
  assert.deepEqual(r.quote, { src: '/email#view=quote', rebuilt: true, count: 1, shown: '', grid: 'none' });
  assert.equal(r.kept, true);
  assert.equal(r.invoice, '/email#view=invoice');
  assert.equal(r.back, '/email');
  assert.equal(r.title, 't');                                                     // 속성은 복제로 유지 / attributes carried over
});

test('re-clicking the same card re-sets the loaded page hash so its hashchange reopens that menu', async t => {
  // 같은 출처의 가짜 /email 페이지 — 부팅 때와 hashchange 때 읽은 view 를 기록한다(실제 네트워크 없음, route 로만 응답)
  // A fake same-origin /email page that records the view read at boot and on hashchange (no real network; routed only)
  const p = await browser.newPage();
  t.after(() => p.close());
  const fake = '<!doctype html><meta charset="utf-8"><script>window.views=[];'
    + 'const rv=()=>new URLSearchParams(String(location.hash).replace(/^#/, "")).get("view");'
    + 'views.push("boot:"+rv());addEventListener("hashchange",()=>views.push("hash:"+rv()));</script>';
  const host = '<!doctype html><meta charset="utf-8"><div id="viewResource"><div class="sub-header"></div><div class="rc-scroll"></div>'
    + '<div id="rcManageScroll"></div><div id="emailAgentScroll" style="display:none"><div class="ea-body">'
    + '<iframe class="ea-embed" title="t" src="/email"></iframe></div></div></div><script>' + fn('showEmailAgent')
    + '\nwindow.showEmailAgent = showEmailAgent;</script>';
  await p.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname !== 'ai365.test') return route.abort();
    return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: u.pathname === '/email' ? fake : host });
  });
  await p.goto('http://ai365.test/rc');
  const views = () => p.evaluate(() => document.querySelector('#emailAgentScroll iframe.ea-embed').contentWindow.views || []);
  const until = want => p.waitForFunction(w => {
    const f = document.querySelector('#emailAgentScroll iframe.ea-embed');
    const v = f && f.contentWindow && f.contentWindow.views;
    return !!v && JSON.stringify(v) === w;
  }, JSON.stringify(want));
  await until(['boot:null']);
  await p.evaluate(() => showEmailAgent('quote'));                // 주소가 바뀜 → 새 iframe / new address: rebuilt
  await until(['boot:quote']);
  const before = await p.evaluate(() => { window.keep = document.querySelector('iframe.ea-embed'); return window.keep.getAttribute('src'); });
  assert.equal(before, '/email#view=quote');
  await p.evaluate(() => showEmailAgent('quote'));                // 같은 카드 재클릭 / the same card again
  await until(['boot:quote', 'hash:quote']);
  assert.equal(await p.evaluate(() => document.querySelector('iframe.ea-embed') === window.keep), true);   // 다시 만들지 않음 / not rebuilt
  assert.equal(await p.evaluate(() => document.querySelector('iframe.ea-embed').contentWindow.location.hash), '#view=quote');
  await p.evaluate(() => showEmailAgent(''));                     // 메인 카드 → 다른 주소 / the main card: another address
  await until(['boot:null']);
  const n = (await views()).length;
  await p.evaluate(() => showEmailAgent(''));                     // 메인 카드 재클릭은 상태 유지 / re-clicking main keeps state
  await p.waitForTimeout(150);
  assert.equal((await views()).length, n);
});

// 2026-09-29: 업무 자동화 탭의 이메일 행은 MCP 연결(/mock/mcosmetic/mcp) — 종전 열람 전용 API 레지스트리(RM_EMAIL_API, 28개)는 걷어냈다.
// 화면 렌더는 tests/test_work_agent_ui.cjs, 서버 쪽 연결 설정은 tests/test_mcmail_mcp.py 가 본다. 여기서는 배선과 교육 레지스트리만.
// 2026-09-29: the automation tab's email row is an MCP connection; the read-only API registry (RM_EMAIL_API, 28 rows) is gone.
// The rendering is covered by tests/test_work_agent_ui.cjs and the server side by tests/test_mcmail_mcp.py; here only the wiring and the edu registry.
test('the email row is an MCP connection now; the edu registry keeps its API view without a kind column', async t => {
  for (const gone of ['RM_EMAIL_API', 'renderRmEmailSettings', 'data-rmemailep', 'rmEmailApiBack', 'rmEmSchema'])
    assert.ok(!mockup.includes(gone), gone);
  assert.ok(fn('renderRmAuto').includes('data-rmemailagent role="button" tabindex="0"><span class="rm-ag-type">MCP</span><span class="rm-da-aname">' + EMAIL_LABEL));
  assert.ok(fn('renderRmAutoSettings').includes("const a=rmWaBuiltin('agent_email');"));
  // 이메일 행을 누르면 도구 목록부터(상세 선택 초기화) / clicking the email row starts at the tool list
  assert.ok(mockup.includes("if(e.target.closest('[data-rmemailagent]')){ rmAutoSel={kind:'email'}; rmAutoForm=null; delete RM_WA.view.agent_email; renderRmAuto(); return; }"));
  const edu = slice(mockup, '  const RM_EDU_API={', '\n  };\n');
  const p = await page(t, '<div id="edu"></div>', `
    function esc(v){ const d=document.createElement('span'); d.textContent=String(v??''); return d.innerHTML.replace(/"/g,'&quot;'); }
    function rmRoField(label, value){ return '<div class="rm-field"><span class="rm-flabel">'+esc(label)+'</span><div class="rm-ro">'+esc(value)+'</div></div>'; }
    function rmDaTip(t){ return '<span class="rm-tip">'+esc(t)+'</span>'; }
    function rmEmailCode(src){ return '<pre class="rm-code">'+esc(src)+'</pre>'; }
    ${edu}
    ${fn('renderRmAgentApi')}
    window.render = () => renderRmAgentApi(document.getElementById('edu'), RM_EDU_API, {label:'교육 에이전트', backId:'b', epAttr:'data-ep'});
  `);
  const r = await p.evaluate(() => {
    render();
    const heads = [...document.querySelectorAll('#edu th')].map(e => e.textContent);
    const rows = document.querySelectorAll('#edu tr.rm-api-row').length;
    RM_EDU_API.sel = 0;
    render();
    return { heads, rows, detail: [...document.querySelectorAll('#edu .rm-flabel')].map(e => e.textContent) };
  });
  assert.deepEqual(r.heads, ['API Name', 'Method', 'Endpoint', 'Description', 'Status']);
  assert.equal(r.rows, 12);
  assert.deepEqual(r.detail, ['API Name', 'Method', 'Endpoint', 'Description']);
});

test('adapter renames the work:email smart-file node at runtime and carries the new EN labels', async t => {
  const iife = slice(adapter, '/* 스마트 파일 트리의 work:email 노드 이름(2026-09-28)', '\n})();\n');
  assert.match(adapter, /email: \{ key: 'email', file: 'work:email', node: 'agent_email', label: 'M코스메틱 이메일 에이전트', url: '\/email', api: 'email' \}/);
  const p = await page(t, '<div id="smartFileBody"></div>', `
    window.lang = 'ko';
    const ai365T = s => window.lang === 'en' ? ({'M코스메틱 이메일 에이전트': 'M Cosmetic Email Agent'}[s] || s) : s;
    const AI365_AUTO_REG = { email: { label: 'M코스메틱 이메일 에이전트' } };
    window.AI365_SMF_HOOKS = { sections: () => [{ key: 'work', nodes: [{ key: 'work:email', name: '이메일 업무 에이전트' },
      { key: 'work:edu', name: '교육 에이전트' }] }] };
    ${iife}
  `);
  const names = await p.evaluate(() => window.AI365_SMF_HOOKS.sections()[0].nodes.map(n => n.name));
  assert.deepEqual(names, [EMAIL_LABEL, '교육 에이전트']);
  const draw = () => document.getElementById('smartFileBody').innerHTML =
    '<div data-smf="work:email"><span class="smft-name">이메일 업무 에이전트</span></div>'
    + '<div data-smf="work:edu"><span class="smft-name">교육 에이전트</span></div>';
  await p.evaluate(draw);
  await p.waitForFunction(label => document.querySelector('[data-smf="work:email"] .smft-name').textContent === label, EMAIL_LABEL);
  assert.equal(await p.textContent('[data-smf="work:edu"] .smft-name'), '교육 에이전트');
  await p.evaluate(() => { window.lang = 'en'; });
  await p.evaluate(draw);
  await p.waitForFunction(() => document.querySelector('[data-smf="work:email"] .smft-name').textContent === 'M Cosmetic Email Agent');
  // EN 사전 — 새 라벨·카드·레지스트리·카탈로그 문구가 있고 EN 값이 서로 겹치지 않는다(역방향 사전 오염 방지)
  // EN dictionary: the new labels, cards, registry and catalog strings exist and their EN values are unique (reverse map safety)
  const dict = new Function(slice(adapter, 'const AI365_KO2EN = {', '\n};') + '\nreturn AI365_KO2EN;')();
  const keys = [EMAIL_LABEL,
    '고객 메일을 자동 분류하고 견적·주문·출하·재고·인보이스 업무를 ERP와 연결해 처리하는 이메일 에이전트를 엽니다.',
    'M코스메틱 이메일 에이전트 · 고객 메일 분류와 견적·주문·출하·재고·인보이스 업무, 가상 ERP 연동',
    '확인 필요 메일', '오늘 수신 현황', '견적요청 현황', '주문등록 현황', '출하일정 문의', '재고문의', '인보이스 요청', '업무 Case', '처리오류',
    'ERP 조회·초안', 'ERP 주문등록', '답변 초안', '오류 재처리',
    // 업무 자동화 탭 MCP 연결(2026-09-29) — 안내 문구와 도구 이름 몇 개 / the automation tab's MCP connection: notes and some tool titles
    '연결 정보를 불러오는 중…', '연결 정보를 불러오지 못했습니다', '메일 상세 조회', '답변 발송', '통합 검색'];
  for (const k of keys) {
    assert.ok(dict[k], k);
    assert.equal(Object.values(dict).filter(v => v === dict[k]).length, 1, 'unique EN value: ' + dict[k]);
    assert.equal((adapter.match(new RegExp("'" + k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + "':", 'g')) || []).length, 1, 'single key: ' + k);
  }
  // 삭제된 업무 메뉴 카드(2026-09-29)의 제목 키는 남기지 않는다 / keys of the removed work-menu cards are gone
  for (const k of ['견적요청', '주문등록', '출하일정', '인보이스 발행요청']) assert.equal(dict[k], undefined, k);
});
