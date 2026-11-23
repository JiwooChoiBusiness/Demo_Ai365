// 로컬 지식 에이전트 화면(2026-09-29) — 관리 센터 › 로컬 설정(목록 · 등록/수정 페이지, 등록은 여기에만), 리소스 센터 지식 관리 [Public | Local] 탭
// (열람 · 문서만), 권한 편집기 지식 관리 카드 Local 탭. 순수 함수(권한 파생 · 번역 · 요청 토큰)는 node:vm 에서, 화면 흐름은 목업 전체 + 어댑터를 가짜
// 원점에 올린 격리 브라우저에서 돌린다. 네트워크는 전부 스텁이다.
// Local knowledge agent screens (2026-09-29) — Admin Center › Local settings (list and create/edit page; registration lives only there), the
// Resource Center knowledge [Public | Local] tabs (browsing and documents only) and the permission editor's knowledge-card Local tab. Pure
// functions (permission derivation, translation, request tokens) run in node:vm; screen flows run the whole mockup + adapter on a fake origin
// in an isolated browser. Every network call is stubbed.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { chromium } = require('playwright');
const mockup = fs.readFileSync(path.join(__dirname, '../frontend/ai365-mockup.html'), 'utf8').replace(/\r\n/g, '\n');
const adapter = fs.readFileSync(path.join(__dirname, '../static/adapter.js'), 'utf8').replace(/\r\n/g, '\n');
function fn(name) {   // 목업 IIFE 안의 2칸 들여쓰기 함수 / a two-space indented function inside the mockup IIFE
  const start = mockup.indexOf('  function ' + name + '(');
  assert.ok(start >= 0, name);
  const end = mockup.indexOf('\n', start);
  return /}\s*$/.test(mockup.slice(start, end)) ? mockup.slice(start, end) : mockup.slice(start, mockup.indexOf('\n  }', start) + 4);
}
function plain(v) { return JSON.parse(JSON.stringify(v)); }   // vm 영역 값을 이 영역 값으로 / plain values out of the vm realm
function line(rx) { const m = mockup.match(rx); assert.ok(m, String(rx)); return m[0]; }
function block(from, to) { const i = mockup.indexOf(from); assert.ok(i >= 0, from); const j = mockup.indexOf(to, i); assert.ok(j > i, to); return mockup.slice(i, j); }
function dict() {   // 어댑터 EN 사전 + 목업이 런타임에 보태는 표(DOC_KO2EN, 2026-10-28) / the adapter EN dictionary plus the table the mockup adds at runtime
  const a = adapter.indexOf('const AI365_KO2EN = {'), b = adapter.indexOf('\n};', a);
  const base = vm.runInNewContext('(' + adapter.slice(a + 'const AI365_KO2EN = '.length, b + 2) + ')');
  const c = mockup.indexOf('var DOC_KO2EN='), d = mockup.indexOf('};', c);
  const extra = c >= 0 ? vm.runInNewContext('(' + mockup.slice(c + 'var DOC_KO2EN='.length, d + 1) + ')') : {};
  return Object.assign({}, extra, base);
}
function rng(seed) {   // 결정적 난수(mulberry32) / deterministic PRNG
  return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}

/* ── 권한 편집기 순수 함수(PG_FLAT 두 장: 지식 관리 + 가짜 카드 knlocal) / permission-editor pure functions (knowledge + the knlocal pseudo-card) ── */
function permContext(agents) {
  const ctx = { window: { AI365_LOCAL_AGENTS: agents } };
  vm.createContext(ctx);
  vm.runInContext([
    "var PG_FLAT=[{key:'knowledge', rows:[{lv:1, name:'인사', node:'f_hr', level:0}]}, {key:'knlocal', rows:[], desc:''}];",
    'var PG_INIT=PG_FLAT.map(function(c){ return []; });',
    line(/^ {2}const esc = .*$/m).replace(/^ {2}const /, 'var '),
    line(/^ {2}const PG_FILE_IC = .*$/m).replace(/^ {2}const /, 'var '),
    line(/^ {2}const isKlNode = .*$/m).replace(/^ {2}const /, 'var '),
    ['levelsFor', 'tgtBadge', 'rebuildLocalCard', 'klChainLevel', 'loadLocalPerms', 'deriveLocalPerms', 'pgCardSig'].map(fn).join('\n'),
    'function setLevels(ls){ PG_FLAT[1].rows.forEach(function(r, i){ r.level=ls[i]; }); }',
  ].join('\n'), ctx);
  ctx.rebuildLocalCard();
  return ctx;
}
const TWO = [{ id: 'kl_demo_hq', label: '본사 <b>지식</b>' }, { id: 'kl_ab12cd34', label: '연구소' }];
const IDS = TWO.map(a => a.id);
/* access.group_map 의 JS 판(m_res › p_know › f_hr, m_res › p_klocal › 에이전트) / a JS port of access.group_map over a small universe */
const KIDS = { m_res: ['p_know', 'p_klocal'], p_know: ['f_hr'], p_klocal: IDS.slice() };
function descendants(n) { return [n].concat(...(KIDS[n] || []).map(descendants)); }
function groupMap(g) {
  const m = {};
  (g.grants || []).forEach(gr => { const l = gr.action === 'manage' ? 2 : 1; descendants(gr.node).forEach(n => { if ((m[n] || 0) < l) m[n] = l; }); });
  (g.exceptions || []).forEach(ex => {
    if (ex.type === 'exclude') descendants(ex.node).forEach(n => { m[n] = 0; });
    else if (ex.type === 'manage') m[ex.node] = 2;
    else if ((m[ex.node] || 0) < 1) m[ex.node] = 1;
  });
  return m;
}
function randomGroup(r) {
  const nodes = ['m_res', 'p_klocal', 'p_know', 'f_hr'].concat(IDS), pick = a => a[Math.floor(r() * a.length)];
  const grants = [], exceptions = [];
  for (let i = Math.floor(r() * 4); i > 0; i--) grants.push({ node: pick(nodes), action: pick(['view', 'manage']) });
  for (let i = Math.floor(r() * 4); i > 0; i--) exceptions.push({ node: pick(nodes), type: pick(['exclude', 'manage', 'view']) });
  return { grants, exceptions };
}

test('the Local card offers block/view/manage per agent with unbadged level-0 rows, escaped names, its own PG_INIT slot and the Admin Center empty notice', () => {
  const c = permContext(TWO), lc = c.PG_FLAT[1];
  assert.deepEqual(Array.from(c.levelsFor(lc, lc.rows[0])), ['차단', '열람', '관리']);
  assert.deepEqual(Array.from(c.levelsFor(c.PG_FLAT[0], c.PG_FLAT[0].rows[0])), ['차단', '열람', '업로드', '관리']);   // Public 4단 무변경 / Public keeps four levels
  assert.deepEqual(plain(lc.rows.map(r => [r.lv, r.node, r.name, r.level])), [[0, 'kl_demo_hq', '본사 &lt;b&gt;지식&lt;/b&gt;', 0], [0, 'kl_ab12cd34', '연구소', 0]]);
  assert.equal(c.tgtBadge(lc.rows[0]), '');                           // 0단계 = 'LV.0' 표시 없음(2026-10-08) / level 0 = no 'LV.0' label
  assert.equal(c.tgtBadge(c.PG_FLAT[0].rows[0]), '<span class="pg-lv l1">LV.1</span>');   // Public 행은 그대로 / Public rows unchanged
  assert.equal(c.PG_INIT[1].length, 2);                                 // resetData 가 읽는 칸 / the slot resetData reads
  assert.equal(lc.desc, '에이전트 단위 차단 / 열람 / 관리');
  const empty = permContext([]);
  assert.equal(empty.PG_FLAT[1].desc, '등록된 로컬 지식 에이전트가 없습니다 (관리 센터 › 로컬 LLM & DB 설정)');
  assert.ok(mockup.includes("desc:'등록된 로컬 지식 에이전트가 없습니다 (관리 센터 › 로컬 LLM & DB 설정)'"));   // 수화 전 기본값도 같다 / same default before hydration
  assert.equal(empty.PG_INIT[1].length, 0);
  assert.ok(c.isKlNode('p_klocal') && c.isKlNode('kl_x') && !c.isKlNode('p_know') && !c.isKlNode('f_hr'));
});

test('loading replays access.group_map on [m_res, p_klocal, agent]: grants, then exceptions in list order including view-type ones', () => {
  const c = permContext(TWO), rows = c.PG_FLAT[1].rows, lv = () => plain(rows.map(r => r.level));
  c.loadLocalPerms({ grants: [{ node: 'p_klocal', action: 'view' }, { node: 'kl_demo_hq', action: 'manage' }], exceptions: [] });
  assert.deepEqual(lv(), [2, 1]);
  c.loadLocalPerms({ grants: [{ node: 'm_res', action: 'manage' }], exceptions: [{ node: 'kl_ab12cd34', type: 'exclude' }] });
  assert.deepEqual(lv(), [2, 0]);
  c.loadLocalPerms({ grants: [{ node: 'p_klocal', action: 'manage' }], exceptions: [{ node: 'p_klocal', type: 'exclude' }] });
  assert.deepEqual(lv(), [0, 0]);
  c.loadLocalPerms({ grants: [], exceptions: [{ node: 'kl_demo_hq', type: 'manage' }] });
  assert.deepEqual(lv(), [2, 0]);
  // 순서가 결과를 바꾼다: exclude 뒤 view = 열람, view 뒤 exclude = 차단 / order matters: exclude then view = view, view then exclude = blocked
  c.loadLocalPerms({ grants: [{ node: 'm_res', action: 'manage' }], exceptions: [{ node: 'kl_demo_hq', type: 'exclude' }, { node: 'kl_demo_hq', type: 'view' }] });
  assert.deepEqual(lv(), [1, 2]);
  c.loadLocalPerms({ grants: [{ node: 'm_res', action: 'manage' }], exceptions: [{ node: 'kl_demo_hq', type: 'view' }, { node: 'kl_demo_hq', type: 'exclude' }] });
  assert.deepEqual(lv(), [0, 2]);
  // manage 예외는 자기 노드만(p_klocal manage 예외는 에이전트를 올리지 않는다) / a manage exception lifts only its own node
  c.loadLocalPerms({ grants: [], exceptions: [{ node: 'p_klocal', type: 'manage' }] });
  assert.deepEqual(lv(), [0, 0]);
  // 무작위 그룹 500개가 group_map 과 같다 / 500 random groups match group_map
  const r = rng(20260929);
  for (let i = 0; i < 500; i++) {
    const g = randomGroup(r), m = groupMap(g);
    c.loadLocalPerms(g);
    assert.deepEqual(lv(), IDS.map(id => m[id] || 0), JSON.stringify(g));
  }
});

test('deriveLocalPerms keeps the anchor, handles m_res levels with exclude + view exceptions, drops the anchor when every row is blocked', () => {
  const c = permContext(TWO);
  const run = (grants, levels, exceptions) => { c.setLevels(levels); return plain(c.deriveLocalPerms(grants, exceptions)); };
  // 앵커 보존 · 앵커 아래 차단 = exclude / anchor kept, blocked under the anchor = exclude
  assert.deepEqual(run([{ node: 'p_klocal', action: 'view' }], [1, 0]),
    { grants: [{ node: 'p_klocal', action: 'view' }], exceptions: [{ node: 'kl_ab12cd34', type: 'exclude' }] });
  // 앵커보다 높은 행 = grant / a row above the anchor gets a grant
  assert.deepEqual(run([{ node: 'p_klocal', action: 'view' }], [2, 1]),
    { grants: [{ node: 'p_klocal', action: 'view' }, { node: 'kl_demo_hq', action: 'manage' }], exceptions: [] });
  // 관리 앵커 아래 열람 행 = 앵커를 열람으로 / a view row lowers a manage anchor to view
  assert.deepEqual(run([{ node: 'p_klocal', action: 'manage' }], [2, 1]),
    { grants: [{ node: 'p_klocal', action: 'view' }, { node: 'kl_demo_hq', action: 'manage' }], exceptions: [] });
  assert.deepEqual(run([{ node: 'p_klocal', action: 'manage' }], [2, 2]), { grants: [{ node: 'p_klocal', action: 'manage' }], exceptions: [] });
  // 전부 차단 = 앵커를 걷는다(예외도 필요 없다) / every row blocked drops the anchor (and needs no exception)
  assert.deepEqual(run([{ node: 'p_klocal', action: 'manage' }], [0, 0]), { grants: [], exceptions: [] });
  // 새 그룹(앵커 없음) / new group (no anchor)
  assert.deepEqual(run(null, [1, 2]), { grants: [{ node: 'kl_demo_hq', action: 'view' }, { node: 'kl_ab12cd34', action: 'manage' }], exceptions: [] });
  assert.deepEqual(run([], [0, 0]), { grants: [], exceptions: [] });
  // m_res 열람 위에서만 grant, 차단은 exclude / above an inherited m_res view only, blocked = exclude
  assert.deepEqual(run([{ node: 'm_res', action: 'view' }], [0, 2]),
    { grants: [{ node: 'kl_ab12cd34', action: 'manage' }], exceptions: [{ node: 'kl_demo_hq', type: 'exclude' }] });
  // m_res 관리 아래 열람 = exclude 뒤 view 예외, 차단 = exclude / under m_res manage: view = exclude then view, blocked = exclude
  assert.deepEqual(run([{ node: 'm_res', action: 'manage' }], [1, 0]),
    { grants: [], exceptions: [{ node: 'kl_demo_hq', type: 'exclude' }, { node: 'kl_demo_hq', type: 'view' }, { node: 'kl_ab12cd34', type: 'exclude' }] });
  // m_res 차단 예외 아래에서는 grant 로 안 오르므로 예외로 올린다 / under an m_res exclude only exceptions lift a row
  assert.deepEqual(run([{ node: 'p_klocal', action: 'view' }], [2, 1], [{ node: 'm_res', type: 'exclude' }]),
    { grants: [{ node: 'p_klocal', action: 'view' }], exceptions: [{ node: 'kl_demo_hq', type: 'manage' }, { node: 'kl_ab12cd34', type: 'view' }] });
});

test('a derived Local save round-trips through group_map for random groups and targets (the save filter keeps non-Local items first)', () => {
  const c = permContext(TWO), r = rng(7);
  const isKl = n => n === 'p_klocal' || String(n).indexOf('kl_') === 0;
  for (let i = 0; i < 1500; i++) {
    const g = randomGroup(r), want = IDS.map(() => Math.floor(r() * 3));
    c.setLevels(want);
    const d = plain(c.deriveLocalPerms(g.grants, g.exceptions));
    const saved = { grants: g.grants.filter(x => !isKl(x.node)).concat(d.grants), exceptions: g.exceptions.filter(x => !isKl(x.node)).concat(d.exceptions) };
    const m = groupMap(saved);
    assert.deepEqual(IDS.map(id => m[id] || 0), want, JSON.stringify({ g, want, d }));
    c.loadLocalPerms(saved);   // 다시 불러와도 같은 레벨 / reloading shows the same levels
    assert.deepEqual(plain(c.PG_FLAT[1].rows.map(x => x.level)), want);
    assert.ok(d.grants.concat(d.exceptions).every(x => isKl(x.node)), 'only Local nodes are emitted');
  }
});

test('the deployment settings label map covers every contract enum id and the default and lab profiles are valid', () => {
  const src = block('  var KL_OPTS={', '  var KL_AUTH=');
  const ctx = vm.createContext({});
  vm.runInContext(src, ctx);
  const ids = list => list.map(o => o[0]);
  const O = plain(ctx.KL_OPTS);
  assert.deepEqual(ids(O.storage), ['on_prem', 'azure_blob', 'aws_s3']);
  assert.deepEqual(ids(O.vector_db), ['milvus', 'azure_ai_search', 'chroma']);
  assert.deepEqual(ids(O.type), ['local', 'public']);
  assert.deepEqual(ids(O.embedding.local), ['bge-m3', 'multilingual-e5-large']);
  assert.deepEqual(ids(O.embedding.public), ['text-embedding-3-large', 'text-embedding-3-small']);
  assert.deepEqual(ids(O.llm.local), ['qwen-3.5-4b', 'deepseek-v4-pro', 'llama-4']);
  assert.deepEqual(ids(O.llm.public), ['azure-openai-gpt', 'claude', 'gemini']);
  assert.deepEqual(ids(O.parser), ['default', 'layout', 'ocr']);
  assert.deepEqual(ids(O.reranker), ['none', 'bge-reranker', 'cross-encoder']);
  assert.deepEqual(ids(O.network), ['private', 'vpn', 'allowlist']);
  const labels = [O.storage, O.vector_db, O.type, O.embedding.local, O.embedding.public, O.llm.local, O.llm.public, O.parser, O.reranker, O.network].flat().map(o => o[1]);
  assert.deepEqual(labels, ['온프레미스 저장소', 'Azure Blob Storage', 'AWS S3', 'Milvus', 'Azure AI Search', 'Chroma', 'Local', 'Public', 'BGE-M3', 'Multilingual E5 Large',
    'Azure OpenAI text-embedding-3-large', 'Azure OpenAI text-embedding-3-small', 'Qwen 3.5-4B', 'DeepSeek V4 Pro', 'Llama 4', 'Azure OpenAI GPT', 'Claude', 'Gemini',
    '기본 파서', '레이아웃 인식', 'OCR 포함', '사용 안 함', 'BGE Reranker', 'Cross-encoder', '사내망 전용', 'VPN 경유', 'IP 허용 목록']);
  assert.deepEqual(plain(ctx.KL_SETTINGS_DEFAULT), { storage: 'on_prem', vector_db: 'milvus', embedding: { type: 'local', model: 'bge-m3' }, llm: { type: 'local', model: 'qwen-3.5-4b' },
    processing: { chunk_size: 800, chunk_overlap: 100, parser: 'layout' }, retrieval: { top_k: 5, threshold: 0.35, reranker: 'bge-reranker' }, security: { network: 'private' } });
  assert.deepEqual(plain(ctx.KL_LAB.settings), { storage: 'on_prem', vector_db: 'chroma', embedding: { type: 'local', model: 'multilingual-e5-large' }, llm: { type: 'local', model: 'qwen-3.5-4b' },
    processing: { chunk_size: 600, chunk_overlap: 80, parser: 'ocr' }, retrieval: { top_k: 8, threshold: 0.3, reranker: 'none' }, security: { network: 'vpn' } });
  assert.deepEqual([ctx.KL_LAB.name, ctx.KL_LAB.mcp_url, ctx.KL_LAB.api_url, ctx.KL_LAB.auth.type, ctx.KL_LAB.auth.header],
    ['연구소 로컬 에이전트', '{{base_url}}/mock/kagent/lab/mcp', '{{base_url}}/mock/kagent/lab/api/v1', 'api_key', 'X-API-Key']);
  const en = dict();   // 한국어 표시 이름은 EN 사전에 있다 / Korean display names have EN entries
  labels.filter(l => /[가-힣]/.test(l)).forEach(l => assert.ok(l in en, 'EN key for ' + l));
  // 한글 없는 선택지는 번역에서 뺀다(KO 역변환이 Claude 를 클로드로 바꾸던 문제) / options without Hangul skip translation (KO turned Claude into 클로드)
  const sel = vm.runInNewContext(line(/^ {2}const esc = .*$/m).replace(/^ {2}const /, 'var ') + '\n' + fn('klSelect') + '; klSelect', {});
  assert.equal(sel('x', [['claude', 'Claude'], ['a', '기본 파서']], 'claude'), '<select class="mcf-in" data-klf="x"><option value="claude" selected data-i18n-skip>Claude</option><option value="a">기본 파서</option></select>');
});

test('server reasons translate whole, around ": ", and by template; preview kinds are decided before any request', () => {
  const en = dict();
  let LANG = 'en';
  const ctx = vm.createContext({ ai365CurrentLang: () => LANG, ai365T: s => (LANG === 'en' ? (en[s] || s) : s) });
  vm.runInContext(['klEn', 'klT', 'klTd', 'klPreviewKind'].map(fn).join('\n'), ctx);
  assert.equal(ctx.klTd('에이전트에 연결하지 못했습니다: 리다이렉트는 따르지 않습니다(HTTP 302)'), 'Could not connect to the agent: Redirects are not followed (HTTP 302)');
  assert.equal(ctx.klTd('에이전트에 연결하지 못했습니다: 인증에 실패했습니다(HTTP 401): bad key'), 'Could not connect to the agent: Authentication failed (HTTP 401): bad key');
  assert.equal(ctx.klTd('주소가 바뀌면 인증 정보를 다시 입력해야 합니다'), 'Re-enter the credentials when an address changes');
  assert.equal(ctx.klTd('인증 방식이 바뀌면 인증 정보를 다시 입력해야 합니다'), 'Re-enter the credentials when the authentication type changes');
  assert.equal(ctx.klTd('로컬 지식 에이전트를 등록할 권한이 없습니다'), 'You do not have permission to register local knowledge agents');
  assert.equal(ctx.klTd('MCP 서버 URL에는 쿼리(?)나 조각(#)을 넣을 수 없습니다'), 'The MCP server URL cannot contain a query (?) or fragment (#)');
  assert.equal(ctx.klTd('API Base URL에는 쿼리(?)나 조각(#)을 넣을 수 없습니다'), 'The API base URL cannot contain a query (?) or fragment (#)');
  assert.equal(ctx.klTd('같은 이름의 지식 에이전트가 이미 있습니다: 연구소'), 'A knowledge agent with the same name already exists: 연구소');
  assert.equal(ctx.klTd('문서를 찾을 수 없습니다'), 'Document not found');
  assert.equal(ctx.klTd('존재하지 않는 에이전트입니다'), 'This agent does not exist');
  LANG = 'ko';
  assert.equal(ctx.klTd('에이전트에 연결하지 못했습니다: 리다이렉트는 따르지 않습니다(HTTP 302)'), '에이전트에 연결하지 못했습니다: 리다이렉트는 따르지 않습니다(HTTP 302)');
  const k = d => ctx.klPreviewKind(d);
  assert.deepEqual([k({ name: 'a.pdf' }), k({ name: 'x', mime: 'application/pdf' }), k({ name: 'a.TXT' }), k({ name: 'b.md' }), k({ name: 'c', mime: 'text/csv' }),
    k({ name: 'd.docx', mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }), k({ name: 'e.hwp' }), k({ name: 'f.xlsx' })],
  ['pdf', 'pdf', 'text', 'text', 'text', '', '', '']);
  assert.ok(fn('klPdfFrame').includes("url+'#navpanes=0'"));   // 두 PDF 경로 모두 klPdfFrame / both PDF paths use klPdfFrame
  assert.equal(block('  function klOpenView(', '  /* 업로드(rmUploadOv').split('klPdfFrame(url)').length - 1, 2);
});

test('document lists keep only the latest reply per selection (request tokens) and drop replies for another acting user', async () => {
  const pend = [];
  const ctx = vm.createContext({ encodeURIComponent, Date, pend, rendered: [], polled: [],
    fetch: () => new Promise(res => pend.push(res)) });
  vm.runInContext([
    "var KL={actor:'', docs:{}, docTok:{}, tokSeq:0, polling:{}, list:[{id:'kl_a', enabled:true}]};",
    "function klAgent(id){ return KL.list.filter(function(a){ return a.id===id; })[0]||null; }",
    "function klQ(){ return 'acting_user_id='; }",
    "function klPollProcessing(k, n){ polled.push(k); }",
    "function klRenderKey(k){ rendered.push(k); }",
    ['klDocsKey', 'klJson', 'klDetail', 'klDocsLoad'].map(fn).join('\n'),
  ].join('\n'), ctx);
  const reply = (i, docs) => pend[i]({ ok: true, status: 200, json: () => Promise.resolve({ documents: docs }) });
  const tick = () => new Promise(r => setTimeout(r, 5));
  const sel = { agent: 'kl_a', folder: null };
  ctx.klDocsLoad(sel, false, 0);
  ctx.klDocsLoad(sel, false, 0);   // 같은 선택의 진행 중 요청은 다시 보내지 않는다 / an in-flight load is not repeated
  assert.equal(pend.length, 1);
  ctx.klDocsLoad(sel, true, 0);    // 강제 새로 받기 = 두 번째 요청 / a forced refresh sends a second request
  assert.equal(pend.length, 2);
  reply(1, [{ id: 'new' }]); await tick();
  reply(0, [{ id: 'old' }]); await tick();   // 늦게 온 옛 응답은 버린다 / the late old reply is dropped
  assert.deepEqual(plain(ctx.KL.docs['kl_a|'].list), [{ id: 'new' }]);
  assert.deepEqual(plain(ctx.rendered), ['kl_a|']);
  ctx.klDocsLoad(sel, true, 0);
  vm.runInContext("KL.actor='7';", ctx);   // 사용자 전환 / acting user changed
  reply(2, [{ id: 'other' }]); await tick();
  assert.deepEqual(plain(ctx.KL.docs['kl_a|'].list), [{ id: 'new' }]);   // 이전 목록을 들고 기다리던 상태 그대로 / still the refresh placeholder with the previous list
  // 사용 중지 에이전트는 요청 없이 409 안내 / a disabled agent gets the 409 notice without a request
  vm.runInContext("KL.list.push({id:'kl_off', enabled:false});", ctx);
  ctx.klDocsLoad({ agent: 'kl_off', folder: null }, false, 0);
  assert.equal(pend.length, 3);
  assert.deepEqual([ctx.KL.docs['kl_off|'].status, ctx.KL.docs['kl_off|'].error], [409, '사용 중지된 에이전트입니다']);
});

test('registration lives in Admin Center › Local LLM & DB setting, the Resource Center has no register entry, and the EN dictionary follows', () => {
  ['data-hubcard="llm"', 'id="pgLlmScroll"', 'id="pgLlmEditScroll"', 'function showLlm', 'function llmRender', 'function klToggle', "s==='llmedit'", "k==='llm'",
    '.llm-switch', '.kl-table', '.kl-chip', 'id="llmCrumbList"', 'id="llmAddMcp"']
    .forEach(s => assert.ok(mockup.includes(s), s));
  assert.equal(mockup.split('id="klPage"').length - 1, 1);
  assert.ok(mockup.indexOf('id="klPage"') > mockup.indexOf('id="pgLlmEditScroll"'));   // 수정 페이지는 관리 센터 안 / the edit page sits in the Admin Center
  ['klRegScroll', 'docKlReg', 'rmKlReg', 'data-klreg', 'data-klmore', "act==='klset'", 'klApplyRegBtn'].forEach(s => assert.ok(!mockup.includes(s), s));
  const en = dict();
  // 옛 Local LLM 데모 키만 정리 / only the old Local LLM demo keys are pruned
  ['데모: KMS Agent 채우기', 'Local LLM 설정', '켜짐', '로컬 LLM', '모델 목록 가져오기', '에이전트 등록',
    '고객 환경에 배포한 지식 관리 에이전트를 MCP와 API로 연결합니다. 등록한 이름은 Local 탭에 LV.0으로 표시됩니다.', '등록된 로컬 지식 에이전트가 없습니다 (리소스 센터 › 지식 관리 › Local)']
    .forEach(k => assert.ok(!(k in en), 'pruned ' + k));
  const want = {
    '로컬 LLM & DB 설정': 'Local LLM & DB setting', '+ 로컬 에이전트 등록': '+ Register local agent', '관리 센터에서 수정': 'Edit in Admin Center',
    '사용 여부를 저장했습니다.': 'Saved the enabled setting.', '등록된 로컬 지식 에이전트가 없습니다 (관리 센터 › 로컬 LLM & DB 설정)': 'No local knowledge agents registered (Admin Center › Local LLM & DB setting)',
    '고객 환경에 배포한 로컬 에이전트의 MCP · API 연결': 'MCP and API connections of local agents deployed in customer environments',
    '이 파일을 삭제하시겠습니까?': 'Delete this file?', '주소가 바뀌면 인증 정보를 다시 입력해야 합니다': 'Re-enter the credentials when an address changes',
    '인증 방식이 바뀌면 인증 정보를 다시 입력해야 합니다': 'Re-enter the credentials when the authentication type changes',
    '로컬 지식 에이전트를 등록할 권한이 없습니다': 'You do not have permission to register local knowledge agents',
  };
  Object.keys(want).forEach(k => assert.equal(en[k], want[k], k));
  // 두 블록(관리 센터 로컬 설정 · 리소스 센터 Local)의 한국어 화면 문구는 모두 EN 키가 있다 / every Korean UI string of both blocks has an EN key
  const kl = block('  /* ── 로컬 설정(2026-09-29 개편, 관리 센터 카드)', '  /* ── 청구 현황(2026-09-15') + block('  /* ── 리소스 센터 [Public | Local] 탭(2026-09-29)', '  /* ── AI Batch Log');
  const literals = [...kl.matchAll(/'([^'\\\n]*(?:\\.[^'\\\n]*)*)'/g)].map(m => m[1]);
  assert.ok(literals.length > 200);
  literals.forEach(s => assert.ok(!s.includes('—'), s));   // 화면 문구에 em dash 없음 / no em dash in UI strings
  const skip = new Set(['개 파일을 올렸습니다.', '연구소 로컬 에이전트', '연구소 연구 과제와 실험 문서를 검색하고 답변하는 로컬 에이전트']);
  const texts = new Set();
  literals.forEach(s => s.split(/<[^>]*>/).forEach(p => { p = p.trim().replace(/&lt;/g, '<').replace(/&gt;/g, '>'); if (/[가-힣]/.test(p) && !/=|["<>]/.test(p.replace(/<토큰>/, ''))) texts.add(p); }));
  [...texts].filter(t => !skip.has(t)).forEach(t => assert.ok(t in en, 'EN key for ' + t));
  ['이 로컬 에이전트 연결을 삭제할까요?', '목록에서 빠지며, 이미 저장된 파일은 [저장]을 누를 때 삭제됩니다.', '접근 권한의 지식 관리 Local 항목에서 제거됩니다',
    '등록한 주소·인증 정보와 Skills 파일이 삭제됩니다', '에이전트 저장소의 문서는 삭제되지 않습니다', '에이전트 저장소에서 삭제되며 복구할 수 없습니다.']
    .forEach(k => assert.ok(k in en, 'EN key for ' + k));
});

/* ── 화면 흐름: 목업 전체 + 어댑터, 가짜 원점(모든 요청 스텁) / screen flows: whole mockup + adapter on a fake origin (every request stubbed) ── */
const ORIGIN = 'http://kl.test';
const HTML = mockup.replace('</body>', '<script src="/static/adapter.js"></script></body>');
const SETTINGS = { storage: 'on_prem', vector_db: 'milvus', embedding: { type: 'local', model: 'bge-m3' }, llm: { type: 'local', model: 'deepseek-v4-pro' },
  processing: { chunk_size: 800, chunk_overlap: 100, parser: 'layout' }, retrieval: { top_k: 5, threshold: 0.35, reranker: 'bge-reranker' }, security: { network: 'private' } };
const AGENT = { id: 'kl_demo_hq', name: '본사 지식 에이전트', description: '', enabled: true, pos: 0, level: 2, editable: true, settings: SETTINGS, skills: [],
  mcp: { url: '{{base_url}}/mock/kagent/hq/mcp', timeout: 30, tools: [] }, api: { base_url: '{{base_url}}/mock/kagent/hq/api/v1', timeout: 30 }, auth: { type: 'none' },
  status: { state: 'ok', checked_at: '2026-09-29T10:00:00', mcp_ok: true, api_ok: true, doc_count: 2, error: '', checks: [] } };
const LAB = Object.assign({}, AGENT, { id: 'kl_ab12cd34', name: '연구소 지식 에이전트', pos: 1 });
const DOCS = [{ id: 'd1', name: '규정.pdf', folder_id: 'f1', size: 2048, mime: 'application/pdf', status: 'done', updated_at: '' }];
function pvtree(agents) {
  return [{ id: 'm_res', label: '리소스 센터', kind: 'menu', children: [{ id: 'p_know', label: '지식 관리', kind: 'page', children: [] },
    { id: 'p_klocal', label: '지식 관리 · Local', kind: 'page', children: agents.map(a => ({ id: a.id, label: a.name, kind: 'file' })) }] },
    { id: 'm_admin', label: '관리 센터', kind: 'menu', children: [] }];
}
/* 구성원 목록 = 공개 레코드(주소 · 인증 · 도구 · Skills 없음) + editable / member lists carry public records (no URLs, auth, tools or skills) + editable */
function pub(a) { return { id: a.id, name: a.name, description: a.description, enabled: a.enabled, level: a.level, pos: a.pos, settings: a.settings, status: a.status, editable: !!a.editable }; }
let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });
async function app(t, opts) {
  const o = Object.assign({ agents: [AGENT], groups: [], members: [], teams: [], bootstrap: null, super: true, canRegister: true, docs: null, status: null,
    effective: {}, hold: null }, opts || {});
  const srv = { agents: plain(o.agents), skillSeq: 0 };
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  t.after(() => page.close());
  const errors = [], puts = [], calls = [], reqs = [], downloads = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => d.accept());
  page.on('download', d => downloads.push(new URL(d.url()).pathname));   // <a download> 는 route 를 지나지 않는다 / anchor downloads bypass page.route
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), method = req.method(), p = url.pathname;
    const json = (obj, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(obj) });
    if (url.origin !== ORIGIN) return route.abort();
    if (p === '/') return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: HTML });
    if (p === '/static/adapter.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: adapter });
    if (p.startsWith('/api/')) reqs.push(method + ' ' + p + url.search);
    const body = /json/.test(req.headers()['content-type'] || '') ? JSON.parse(req.postData()) : null;
    if (p.indexOf('/api/knowledge-agents') === 0 && method !== 'GET') calls.push({ method: method, path: p + url.search, body: body });
    if (o.hold) { const h = o.hold(method, p); if (h) await h; }
    if (p === '/api/access/bootstrap') return json(o.bootstrap || { pvtree: pvtree(srv.agents), groups: o.groups, members: o.members, teams: o.teams });
    if (p === '/api/access/groups' && method === 'PUT') { puts.push(JSON.parse(req.postData())); return json({ ok: true }); }
    const eff = /^\/api\/access\/effective\/(\d+)$/.exec(p);
    if (eff) return json(o.effective[eff[1]] || { super: false, menus: {}, nodes: {}, mgmt: {}, read: {} });
    if (p === '/api/knowledge-agents' && method === 'GET') return json({ agents: o.super ? srv.agents.map(a => Object.assign({}, a, { editable: true })) : srv.agents.map(pub), super: o.super, can_register: o.canRegister });
    if (p === '/api/knowledge-agents' && method === 'POST') { const a = Object.assign({}, AGENT, { id: 'kl_new00001', name: body.name, pos: 9 }); srv.agents.push(a); return json({ agent: a }, 201); }
    if (p === '/api/knowledge-agents/check') return json({ ok: true, checked_at: '2026-09-29T12:00:00', mcp: { ok: true, tools: [] }, api: { ok: true }, checks: [] });
    if (p === '/api/knowledge-agents/skills' && method === 'POST') { const k = ++srv.skillSeq; return json({ file: { id: 'sk_' + k, name: 'guide' + k + '.md', size: 12, uploaded_at: '2026-09-29T12:00:00' } }, 201); }
    const one = /^\/api\/knowledge-agents\/(kl_[^/]+)$/.exec(p);
    if (one) {
      const a = srv.agents.find(x => x.id === one[1]);
      if (!a) return json({ detail: '존재하지 않는 에이전트입니다' }, 404);
      if (method === 'GET') { const { editable, ...rec } = a; return json({ agent: rec }); }   // 편집 레코드에는 editable 이 없다 / editor records carry no editable
      if (method === 'DELETE') { srv.agents = srv.agents.filter(x => x.id !== one[1]); return json({ ok: true }); }
      Object.assign(a, { name: body.name, enabled: body.enabled });
      const { editable, ...rec } = a; return json({ agent: rec });
    }
    const doc = /^\/api\/knowledge-agents\/(kl_[^/]+)\/documents\/([^/]+)\/(status|download|preview)$/.exec(p);
    if (doc) {
      if (doc[3] === 'status') { const s = o.status ? o.status(doc[2]) : null; return s ? json(s.body, s.code) : json({ id: doc[2], status: 'done' }); }
      if (doc[3] === 'download') return route.fulfill({ status: 200, headers: { 'content-type': 'application/octet-stream', 'content-disposition': 'attachment; filename="x.bin"' }, body: 'bytes' });
      return route.fulfill({ status: 200, contentType: 'text/plain; charset=utf-8', body: '미리보기 본문' });
    }
    if (/\/folders$/.test(p)) return json({ folders: [{ id: 'f1', name: '경영 규정', children: [{ id: 'f1a', name: '보안 정책', children: [] }] }] });
    const docs = /^\/api\/knowledge-agents\/(kl_[^/]+)\/documents$/.exec(p);
    if (docs && method === 'GET') return json({ documents: o.docs ? o.docs(docs[1], url.searchParams.get('folder_id')) : DOCS });
    if (docs && method === 'POST') return json({ document: { id: 'up1' } }, 201);
    if (p.startsWith('/api/')) return json({ detail: 'stub' }, 404);
    return route.abort();
  });
  await page.goto(ORIGIN + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => Array.isArray(window.AI365_LOCAL_AGENTS), null, { timeout: 10000 });
  return { page, errors, puts, calls, reqs, srv, downloads };
}
async function until(fn) { for (let i = 0; i < 400 && !(await fn()); i++) await new Promise(r => setTimeout(r, 50)); assert.ok(await fn()); }
const shown = (page, sel) => page.$eval(sel, el => !!el && getComputedStyle(el).display !== 'none' && !!el.offsetParent).catch(() => false);
async function localList(page) {   // 관리 센터 › 로컬 설정 목록 / Admin Center › Local settings list
  await page.evaluate(() => { document.getElementById('navPerm').click(); document.querySelector('[data-hubcard="llm"]').click(); });
  await page.waitForFunction(() => { const b = document.getElementById('llmBody'); return !!b && !!b.querySelector('table, .llm-empty b'); });
}
async function docLocal(page) {   // 문서 관리 → Local / Document management → Local
  await page.evaluate(() => { openResourceCenter(); window.openDocMgr(); });
  await page.click('#docMgrScroll [data-kltab="local"]');
  await page.waitForSelector('#docTree [data-kltree="agent"]');
}
async function rmLocal(page, add) {   // 리소스 관리(선택: [리소스 추가]) → Local / Resource management (optionally add mode) → Local
  await page.evaluate(() => { openResourceCenter(); document.getElementById('rcManageBtn').click(); });
  if (add) await page.click('#rmAddResBtn');
  await page.click('#rmPaneKnow [data-kltab="local"]');
  await page.waitForSelector('#rmTree [data-kltree="agent"]');
  await page.waitForFunction(() => { const b = document.getElementById('rmFilesBody'); return !!b && !!b.querySelector('table, .rm-empty-ic'); });
}

test('the Admin Center hub keeps the Local LLM & DB setting card in Work and AI settings and it opens the agent list', async t => {
  const { page, errors } = await app(t, { agents: [AGENT, LAB] });
  await page.evaluate(() => document.getElementById('navPerm').click());
  await page.waitForSelector('#pgHubScroll .hub-card');
  const sec = await page.$$eval('#pgHubScroll .hub-sec', els => els.map(s => [s.querySelector('.hub-sec-tt').textContent, [...s.querySelectorAll('[data-hubcard]')].map(c => c.dataset.hubcard)]));
  // 순서 = Dev AdminCenter.tsx(로컬 LLM & DB → 워크플로우 → API · MCP) 다음 데모 전용 시스템 구성 · Agentic(2026-10-28)
  // order = Dev AdminCenter.tsx (Local LLM & DB, Workflow, API and MCP), then the demo-only System configuration and Agentic
  assert.deepEqual(sec.find(s => s[0] === '업무 및 AI 설정'), ['업무 및 AI 설정', ['llm', 'flows', 'connectors', 'sysconfig', 'agentic']]);
  assert.deepEqual(await page.$eval('[data-hubcard="llm"]', c => [c.querySelector('.hub-card-tt').textContent, c.querySelector('.hub-card-ds').textContent]),
    ['로컬 LLM & DB 설정', '고객 환경에 배포한 로컬 에이전트의 MCP · API 연결']);
  await page.click('[data-hubcard="llm"]');
  await page.waitForSelector('#llmBody tbody tr');
  assert.equal(await page.textContent('#pgLlmScroll .pg-pagetitle'), '로컬 LLM & DB 설정');
  assert.equal(await page.textContent('#pgLlmScroll .pg-pagesub'), '고객 환경에 배포한 로컬 에이전트를 MCP와 API로 연결합니다. 등록한 이름은 리소스 센터 문서 관리의 Local 탭에 표시됩니다.');
  assert.deepEqual(await page.$$eval('#pgLlmScroll .bl-card-tt > span', els => els.map(e => e.textContent)), ['로컬 에이전트', '2개']);
  assert.deepEqual(await page.$$eval('#llmBody thead th', els => els.map(e => e.textContent)), ['에이전트 이름', '연결', 'LLM', '문서', '상태', '사용', '']);
  assert.equal(await page.textContent('#llmAddMcp'), '+ 로컬 에이전트 등록');
  assert.deepEqual(await page.$$eval('#llmBody [data-kledit]', els => els.map(e => e.dataset.kledit)), ['kl_demo_hq', 'kl_ab12cd34']);
  assert.deepEqual(errors, []);
});

test('register and edit follow can_register and editable; the Resource Center Local tabs offer no registration and the summary link is super only', async t => {
  // 구성원(등록 권한 없음, 본사만 관리): 등록 버튼 없음, 본사 행만 스위치 · [수정] / member without register rights, managing HQ only
  const member = { super: false, menus: { m_home: true, m_chat: true, m_res: true }, nodes: { p_klocal: 1, kl_demo_hq: 2, kl_ab12cd34: 1 }, mgmt: { p_klocal: true }, read: { p_klocal: true } };
  const m = await app(t, { super: false, canRegister: false, agents: [AGENT, Object.assign({}, LAB, { editable: false, level: 1 })], effective: { 7: member },
    members: [{ no: 7, name: '강수아', dept: '인사총무', grade: '사원', empno: 7, email: '' }] });
  await localList(m.page);
  assert.equal(await shown(m.page, '#llmAddMcp'), false);
  assert.deepEqual(await m.page.$$eval('#llmBody [data-kledit]', els => els.map(e => e.dataset.kledit)), ['kl_demo_hq']);
  assert.deepEqual(await m.page.$$eval('#llmBody [data-klon]', els => els.map(e => [e.dataset.klon, e.disabled])), [['kl_demo_hq', false], ['kl_ab12cd34', true]]);
  assert.deepEqual(await m.page.$$eval('#llmBody .llm-empty', els => els.length), 0);
  // 리소스 센터: 두 Local 탭 모두 등록 버튼 · ⋯ 없음, 요약 줄 링크 없음(슈퍼 아님) / Resource Center: no register button or ⋯ in either Local tab, no summary link (not super)
  await m.page.evaluate(() => window.AI365_setActingUser(7));
  await m.page.waitForFunction(() => window.AI365_ACTING_USER && window.AI365_ACTING_USER.no === 7);
  await docLocal(m.page);
  assert.equal(await m.page.$('#docMgrScroll [data-klreg], #docMgrScroll #docKlReg'), null);
  await rmLocal(m.page, true);
  assert.equal(await m.page.$('#rmPaneKnow [data-klreg], #rmTree [data-klmore], #rmTree .rm-node-acts'), null);
  assert.equal(await shown(m.page, '#rmNewFolder'), false);   // Local 은 새 폴더도 없다 / Local has no New folder either
  await m.page.waitForSelector('#rmFilesBody .kl-sum');
  assert.equal(await m.page.$('#rmFilesBody [data-klopen]'), null);
  assert.deepEqual(m.errors, []);
  // 구성원(등록 권한 있음) / member with register rights
  const r = await app(t, { super: false, canRegister: true });
  await localList(r.page);
  assert.ok(await shown(r.page, '#llmAddMcp'));
  // 슈퍼: 요약 줄 [관리 센터에서 수정] → 관리 센터 수정 페이지 / super: the summary [Edit in Admin Center] opens the Admin Center edit page
  const s = await app(t, { agents: [AGENT, LAB] });
  await rmLocal(s.page, false);
  await s.page.waitForSelector('#rmFilesBody .kl-sum');
  assert.equal(await s.page.textContent('#rmFilesBody [data-klopen]'), '관리 센터에서 수정');
  await s.page.click('#rmFilesBody [data-klopen]');
  await s.page.waitForSelector('#klPage [data-klf="name"]');
  assert.ok(await shown(s.page, '#pgLlmEditScroll'));
  assert.ok(await s.page.$eval('#viewPermission', v => v.classList.contains('active')));
  assert.ok(await s.page.$eval('#navPerm', n => n.classList.contains('selected')));
  assert.equal(await s.page.inputValue('#klPage [data-klf="name"]'), '본사 지식 에이전트');
  assert.deepEqual(await s.page.$$eval('#pgLlmEditScroll .pg-breadcrumb span', els => els.map(e => e.textContent)), ['관리 센터', '로컬 LLM & DB 설정', '수정']);
  assert.deepEqual([r.errors, s.errors], [[], []]);
});

test('the Admin Center page: register, cancel, save and delete return to the Local LLM & DB setting list', async t => {
  const { page, errors, calls } = await app(t, { agents: [AGENT, LAB] });
  await localList(page);
  // 등록 → 취소 / register → cancel
  await page.click('#llmAddMcp');
  await page.waitForSelector('#klPage [data-klf="name"]');
  assert.ok(await shown(page, '#pgLlmEditScroll'));
  assert.deepEqual(await page.$$eval('#pgLlmEditScroll .pg-breadcrumb span', els => els.map(e => e.textContent)), ['관리 센터', '로컬 LLM & DB 설정', '등록']);
  assert.equal(await page.textContent('#klPage .mcf-title'), '로컬 에이전트 등록');
  assert.equal(await page.textContent('#klPage .mcf-sub'), '고객 환경에 배포한 로컬 에이전트의 MCP 서버와 API 서버에 연결하고, 배포 구성과 Skills 파일을 정합니다.');
  assert.deepEqual(await page.$$eval('#klPage .mcf-head-acts button', els => els.map(e => e.textContent)), ['데모: 연구소 에이전트 채우기', '취소', '저장']);
  assert.deepEqual(await page.$$eval('#klPage .mcf-sec-tt', els => els.map(e => e.textContent)), ['기본 정보', '연결 주소', '인증', '연결 확인', '배포 구성', 'Skills 파일']);
  await page.click('#klPage .mcf-head-acts [data-kl-cancel]');
  assert.ok(await shown(page, '#pgLlmScroll'));
  assert.equal(await shown(page, '#pgLlmEditScroll'), false);
  // 크럼(로컬 설정)도 목록으로 / the crumb also returns to the list
  await page.click('#llmAddMcp');
  await page.click('#llmCrumbList');
  assert.ok(await shown(page, '#pgLlmScroll'));
  // 등록 · 데모 채우기 · 저장 → POST → POST /check {id} → 목록 / register, demo fill, save → back to the list
  await page.click('#llmAddMcp');
  await page.click('#klPage [data-kl-demo]');
  const n = calls.length;
  await page.click('#klPage [data-kl-save]');
  await until(() => calls.slice(n).some(c => /\/check$/.test(c.path)));
  const post = calls.slice(n);
  assert.deepEqual(post.map(c => c.method + ' ' + c.path), ['POST /api/knowledge-agents', 'POST /api/knowledge-agents/check']);
  assert.deepEqual([post[0].body.name, post[0].body.mcp.url, post[0].body.api.base_url, post[0].body.auth], ['연구소 로컬 에이전트', '{{base_url}}/mock/kagent/lab/mcp',
    '{{base_url}}/mock/kagent/lab/api/v1', { type: 'api_key', header: 'X-API-Key', key: 'demo-kagent-key-2026' }]);
  assert.deepEqual(post[1].body, { id: 'kl_new00001', acting_user_id: '' });
  await page.waitForSelector('#llmBody [data-klrow="kl_new00001"]');
  assert.ok(await shown(page, '#pgLlmScroll'));
  // 수정 → 저장 = PUT → check → 목록 / edit → save = PUT → check → list
  await page.click('#llmBody [data-kledit="kl_demo_hq"]');
  await page.waitForSelector('#klPage [data-klf="name"]');
  assert.deepEqual(await page.$$eval('#klPage .mcf-head-acts button', els => els.map(e => e.textContent)), ['이 연결 삭제', '취소', '저장']);
  const m = calls.length;
  await page.click('#klPage [data-kl-save]');
  await until(() => calls.slice(m).some(c => /\/check$/.test(c.path)));
  assert.deepEqual(calls.slice(m).map(c => c.method + ' ' + c.path), ['PUT /api/knowledge-agents/kl_demo_hq', 'POST /api/knowledge-agents/check']);
  await until(() => shown(page, '#pgLlmScroll'));
  // 삭제 → 확인 창(문구 · 이름 · 영향 따로) → DELETE → 목록 / delete → confirm (message, name and impact apart) → DELETE → list
  await page.click('#llmBody [data-kledit="kl_ab12cd34"]');
  await page.waitForSelector('#klPage [data-kl-del]:not([disabled])');
  await page.click('#klPage [data-kl-del]');
  await page.waitForSelector('#klConfirmOv.open');
  assert.deepEqual(await page.$$eval('#klConfirmBody > *', els => els.map(e => [e.className, e.tagName === 'UL' ? [...e.children].map(li => li.textContent) : e.textContent])),
    [['kl-del-q', '이 로컬 에이전트 연결을 삭제할까요?'], ['kl-del-name', '연구소 지식 에이전트'],
      ['kl-del-list', ['접근 권한의 지식 관리 Local 항목에서 제거됩니다', '등록한 주소·인증 정보와 Skills 파일이 삭제됩니다', '에이전트 저장소의 문서는 삭제되지 않습니다']]]);
  const d = calls.length;
  await page.click('#klConfirmOk');
  await until(() => calls.slice(d).some(c => c.method === 'DELETE'));
  assert.deepEqual(calls.slice(d).map(c => c.method + ' ' + c.path), ['DELETE /api/knowledge-agents/kl_ab12cd34?acting_user_id=']);
  await until(async () => (await shown(page, '#pgLlmScroll')) && !(await page.$('#llmBody [data-klrow="kl_ab12cd34"]')));
  assert.deepEqual(errors, []);
});

test('the enabled switch PUTs the full record for super and loads the editor record first for a member who manages the agent', async t => {
  const secret = Object.assign({}, AGENT, { auth: { type: 'bearer', key: '••••••' }, skills: [{ id: 'sk_1', name: 'guide.md', size: 10, uploaded_at: '' }] });
  const s = await app(t, { agents: [secret] });
  await localList(s.page);
  await s.page.click('#llmBody .llm-switch span');
  await until(() => s.calls.some(c => c.method === 'PUT'));
  const put = s.calls.find(c => c.method === 'PUT');
  assert.equal(put.path, '/api/knowledge-agents/kl_demo_hq');
  assert.deepEqual([put.body.enabled, put.body.auth, put.body.acting_user_id, 'skill_ids' in put.body], [false, { type: 'bearer', key: '••••••' }, '', false]);
  await s.page.waitForFunction(() => document.getElementById('toast').textContent === '사용 여부를 저장했습니다.');
  // 구성원: 사용 중지 에이전트를 다시 켠다 — GET /{id} 로 편집 레코드를 받은 뒤 PUT / member: switch a disabled agent back on — GET /{id}, then PUT
  const off = Object.assign({}, LAB, { id: 'kl_off00001', name: '중지된 에이전트', enabled: false });
  const m = await app(t, { super: false, canRegister: false, agents: [AGENT, off] });
  await localList(m.page);
  assert.ok(await m.page.$eval('#llmBody [data-klrow="kl_off00001"]', r => r.classList.contains('kl-off')));
  await m.page.click('#llmBody [data-klrow="kl_off00001"] .llm-switch span');
  await until(() => m.calls.some(c => c.method === 'PUT'));
  const seq = m.reqs.filter(r => r.indexOf('/kl_off00001') >= 0);
  assert.deepEqual(seq, ['GET /api/knowledge-agents/kl_off00001?acting_user_id=', 'PUT /api/knowledge-agents/kl_off00001']);
  const mput = m.calls.find(c => c.method === 'PUT');
  assert.deepEqual([mput.body.enabled, mput.body.mcp.url, mput.body.api.base_url], [true, LAB.mcp.url, LAB.api.base_url]);
  await m.page.waitForFunction(() => !document.querySelector('#llmBody [data-klrow="kl_off00001"]').classList.contains('kl-off'));
  assert.equal(await m.page.$eval('#llmBody [data-klrow="kl_off00001"] [data-kledit]', b => !!b), true);   // 다시 켜도 수정 가능 / still editable after the switch
  assert.deepEqual([s.errors, m.errors], [[], []]);
});

test('switching the auth type blanks masked secrets so they are re-entered', async t => {
  const bearer = Object.assign({}, AGENT, { auth: { type: 'bearer', header: '', key: '••••••', token_url: '', client_id: '', client_secret: '' } });
  const oauth = Object.assign({}, LAB, { auth: { type: 'oauth2', header: '', key: '', token_url: 'https://kagent.example.com/oauth/token', client_id: 'ai365', client_secret: '••••••' } });
  const { page, errors } = await app(t, { agents: [bearer, oauth] });
  await page.evaluate(() => window.AI365_openLocalAgent('kl_demo_hq'));
  await page.waitForSelector('#klPage [data-klf="auth.key"]');
  assert.equal(await page.inputValue('#klPage [data-klf="auth.key"]'), '••••••');
  await page.selectOption('#klPage select[data-klf="auth.type"]', 'api_key');
  assert.equal(await page.inputValue('#klPage [data-klf="auth.key"]'), '');
  await page.selectOption('#klPage select[data-klf="auth.type"]', 'bearer');
  assert.equal(await page.inputValue('#klPage [data-klf="auth.key"]'), '');   // 되돌려도 가린 값은 돌아오지 않는다 / switching back does not restore the mask
  await page.evaluate(() => window.AI365_openLocalAgent('kl_ab12cd34'));
  await page.waitForSelector('#klPage [data-klf="auth.client_secret"]');
  assert.equal(await page.inputValue('#klPage [data-klf="auth.client_secret"]'), '••••••');
  await page.selectOption('#klPage select[data-klf="auth.type"]', 'bearer');
  await page.selectOption('#klPage select[data-klf="auth.type"]', 'oauth2');
  assert.equal(await page.inputValue('#klPage [data-klf="auth.client_secret"]'), '');
  assert.equal(await page.inputValue('#klPage [data-klf="auth.client_id"]'), 'ai365');   // 비밀이 아닌 값은 그대로 / non-secret values stay
  assert.deepEqual(errors, []);
});

test('skill files: the delete confirm keeps the message and the name apart, and pending files are deleted at once and on cancel', async t => {
  const { page, errors, calls } = await app(t);
  await localList(page);
  await page.click('#llmAddMcp');
  await page.waitForSelector('#klPage [data-kl-file]', { state: 'attached' });
  await page.setInputFiles('#klPage [data-kl-file]', [{ name: 'a.md', mimeType: 'text/markdown', buffer: Buffer.from('# a') }, { name: 'b.md', mimeType: 'text/markdown', buffer: Buffer.from('# b') }]);
  await page.waitForSelector('#klPage [data-kl-skilldel="1"]');
  const names = () => page.$$eval('#klPage .mcf-files .mcf-fname span', els => els.map(e => e.textContent));
  assert.deepEqual(await names(), ['guide1.md', 'guide2.md']);
  await page.click('#klPage [data-kl-skilldel="0"]');
  await page.waitForSelector('#klConfirmOv.open');
  assert.deepEqual(await page.$$eval('#klConfirmBody > *', els => els.map(e => [e.className, e.textContent])),
    [['kl-del-q', '이 파일을 삭제하시겠습니까?'], ['kl-del-name', 'guide1.md'], ['kl-del-list', '목록에서 빠지며, 이미 저장된 파일은 [저장]을 누를 때 삭제됩니다.']]);
  await page.click('#klConfirmOk');
  await until(() => calls.some(c => c.method === 'DELETE' && c.path === '/api/knowledge-agents/skills/sk_1?acting_user_id='));
  assert.deepEqual(await names(), ['guide2.md']);
  assert.equal(await page.$eval('#klConfirmOv', o => o.classList.contains('open')), false);
  await page.click('#klPage .mcf-head-acts [data-kl-cancel]');   // 취소 = 남은 미저장 파일도 지운다 / cancel deletes the remaining pending file
  await until(() => calls.some(c => c.method === 'DELETE' && c.path === '/api/knowledge-agents/skills/sk_2?acting_user_id='));
  assert.ok(await shown(page, '#pgLlmScroll'));
  assert.deepEqual(errors, []);
});

test('downloads ask the status first and previews decide the kind before any request', async t => {
  const docs = [{ id: 'd1', name: '규정.pdf', folder_id: 'f1', size: 2048, mime: 'application/pdf', status: 'done' },
    { id: 'd2', name: '계획.docx', folder_id: 'f1', size: 4096, mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', status: 'done' },
    { id: 'd3', name: '메모.md', folder_id: 'f1', size: 64, mime: '', status: 'done' }];
  let deny = true;
  const { page, errors, reqs, downloads } = await app(t, { docs: () => docs, status: () => (deny ? { code: 403, body: { detail: '이 에이전트를 볼 권한이 없습니다' } } : null) });
  await docLocal(page);
  await page.click('#docTree [data-kltree="agent"] .rm-node-name');
  await page.waitForSelector('#docFilesBody [data-kldl="d1"]');
  const count = rx => reqs.filter(r => rx.test(r)).length;
  // 거부 = 사유 토스트, 다운로드 없음 / denied = reason toast, no download
  await page.click('#docFilesBody [data-kldl="d1"]');
  await until(() => count(/documents\/d1\/status/) === 1);
  await page.waitForFunction(() => document.getElementById('toast').textContent === '이 에이전트를 볼 권한이 없습니다');
  await page.waitForTimeout(300);
  assert.deepEqual(downloads, []);
  // 허용 = 상태 확인 뒤 원본 / allowed = the original after the status check
  deny = false;
  await page.click('#docFilesBody [data-kldl="d1"]');
  await until(() => downloads.length === 1);
  assert.deepEqual(downloads, ['/api/knowledge-agents/kl_demo_hq/documents/d1/download']);
  assert.equal(count(/documents\/d1\/status/), 2);
  // 미리보기: docx 는 요청 없이 안내 / preview: docx gets the notice without a request
  await page.click('#docFilesBody [data-kldoc="d2"] .rm-fname');
  await page.waitForSelector('#docViewOv.open .kl-pv-msg');
  assert.equal(await page.textContent('#docvPreview .kl-pv-msg span'), '미리보기를 지원하지 않는 형식입니다');
  assert.ok(await page.$('#docvPreview [data-kldlnow]'));
  assert.equal(count(/documents\/d2\/preview/), 0);
  // md = 텍스트 미리보기 / md = text preview
  await page.click('#docvClose');
  await page.click('#docFilesBody [data-kldoc="d3"] .rm-fname');
  await page.waitForSelector('#docvPreview pre.kl-pv-text');
  assert.equal(await page.textContent('#docvPreview pre'), '미리보기 본문');
  // pdf = 탐색 창 없는 iframe / pdf = iframe without the navigation pane
  await page.click('#docvClose');
  await page.click('#docFilesBody [data-kldoc="d1"] .rm-fname');
  await page.waitForSelector('#docvPreview iframe.kl-pv-frame');
  assert.match(await page.getAttribute('#docvPreview iframe', 'src'), /\/documents\/d1\/preview\?acting_user_id=#navpanes=0$/);
  assert.deepEqual(errors, []);
});

test('polling stops while the Local view is hidden and restarts from the cached list on return', async t => {
  const { page, errors, reqs } = await app(t, { docs: () => [{ id: 'p1', name: '처리중.pdf', size: 10, mime: 'application/pdf', status: 'processing' }] });
  const lists = () => reqs.filter(r => /^GET \/api\/knowledge-agents\/kl_demo_hq\/documents\?/.test(r)).length;
  await docLocal(page);
  await page.click('#docTree [data-kltree="agent"] .rm-node-name');
  await page.waitForSelector('#docFilesBody .rm-idx.ing');
  assert.equal(lists(), 1);
  await page.evaluate(() => openResourceCenter());   // 화면을 떠난다 / leave the view
  await page.waitForTimeout(3600);                   // 폴링 시각이 지나도 / past the poll time
  assert.equal(lists(), 1);
  await docLocal(page);
  await page.click('#docTree [data-kltree="agent"] .rm-node-name');
  await until(() => lists() === 2);                  // 캐시에 처리 중이 남아 있어 다시 받는다 / the cached list still processing → refetch
  await page.waitForTimeout(3600);
  assert.equal(lists(), 3);                          // 보이는 동안 폴링 재개 / polling resumed while visible
  await page.evaluate(() => showView('home'));        // 다른 뷰 = 멈춤 / another view stops it
  await page.waitForTimeout(3600);
  assert.equal(lists(), 3);
  assert.deepEqual(errors, []);
});

test('cancel is ignored while saving and the post-save steps still run after the session changed', async t => {
  let release;
  const gate = new Promise(r => { release = r; });
  const { page, errors, calls, reqs } = await app(t, { agents: [AGENT, LAB], hold: (method, p) => (method === 'PUT' && p === '/api/knowledge-agents/kl_demo_hq' ? gate : null) });
  await page.evaluate(() => window.AI365_openLocalAgent('kl_demo_hq'));
  await page.waitForSelector('#klPage [data-klf="name"]');
  await page.click('#klPage [data-kl-save]');
  await page.waitForSelector('#klPage [data-kl-save][disabled]');
  assert.equal(await page.textContent('#klPage [data-kl-save]'), '저장 중…');
  assert.ok(await page.$eval('#klPage .mcf-head-acts [data-kl-cancel]', b => b.disabled));
  await page.click('#llmCrumbList');                         // 저장 중 취소 = 무시 / cancel while saving = ignored
  assert.ok(await shown(page, '#pgLlmEditScroll'));
  await page.evaluate(() => window.AI365_openLocalAgent('kl_ab12cd34'));   // 저장 중 다른 에이전트 폼 / another form while saving
  await page.waitForFunction(() => { const i = document.querySelector('#klPage [data-klf="name"]'); return i && i.value === '연구소 지식 에이전트'; });
  const lists = reqs.length;
  release();
  await until(() => calls.some(c => /\/check$/.test(c.path)));
  assert.deepEqual(calls.find(c => /\/check$/.test(c.path)).body, { id: 'kl_demo_hq', acting_user_id: '' });
  await until(() => reqs.slice(lists).includes('GET /api/knowledge-agents?acting_user_id=') && reqs.slice(lists).includes('GET /api/access/bootstrap'));
  await page.waitForFunction(() => document.getElementById('toast').textContent === '저장했습니다.');
  assert.ok(await shown(page, '#pgLlmEditScroll'));             // 지금 폼은 그대로 / the current form stays
  assert.equal(await page.inputValue('#klPage [data-klf="name"]'), '연구소 지식 에이전트');
  assert.deepEqual(errors, []);
});

test('managers see their disabled agents in the Resource Center: a badge and a notice without proxy calls', async t => {
  const off = Object.assign({}, LAB, { id: 'kl_off00001', name: '중지된 에이전트', enabled: false, status: { state: 'unchecked', doc_count: null } });
  const { page, errors, reqs } = await app(t, { super: false, canRegister: false, agents: [AGENT, off] });
  await docLocal(page);
  const row = '#docTree [data-kltree="agent"][data-klagent="kl_off00001"]';
  assert.ok(await page.$eval(row, e => e.classList.contains('kl-off')));
  assert.equal(await page.textContent(row + ' .kl-tag'), '사용 안 함');
  await page.click(row + ' .rm-node-name');
  await page.waitForFunction(() => /사용 중지된 에이전트입니다/.test(document.getElementById('docFilesBody').textContent));
  assert.equal(await page.$('#docFilesBody [data-klretry]'), null);
  assert.equal(reqs.filter(r => r.indexOf('/kl_off00001/') >= 0).length, 0);   // 문서 · 폴더 프록시를 부르지 않는다 / no document or folder proxy calls
  assert.ok(await page.$eval('#docUploadBtn', b => b.classList.contains('rm-locked')));
  // 관리 센터에서는 수정 페이지를 열어 다시 켤 수 있다 / the Admin Center edit page opens so it can be switched back on
  await localList(page);
  await page.click('#llmBody [data-kledit="kl_off00001"]');
  await page.waitForSelector('#klPage [data-klf="enabled"]');
  assert.equal(await page.isChecked('#klPage [data-klf="enabled"]'), false);
  assert.deepEqual(errors, []);
});

test('the AI Batch Log card needs Public knowledge, and a user switch closes a form opened as someone else', async t => {
  const localOnly = { super: false, menus: { m_home: true, m_chat: true, m_res: true }, nodes: { p_klocal: 2, kl_demo_hq: 2 }, mgmt: { p_klocal: true }, read: { p_klocal: true } };
  const { page, errors } = await app(t, { effective: { 7: localOnly }, members: [{ no: 7, name: '강수아', dept: '인사총무', grade: '사원', empno: 7, email: '' }] });
  await localList(page);
  await page.click('#llmAddMcp');
  await page.waitForSelector('#klPage [data-klf="name"]');
  await page.evaluate(() => window.AI365_setActingUser(7));
  await until(async () => !(await shown(page, '#pgLlmEditScroll')) && (await shown(page, '#pgLlmScroll')));
  await page.evaluate(() => openResourceCenter());
  assert.ok(await shown(page, '#rc-knowledge'));
  assert.ok(await shown(page, '#rc-knowledge [data-rc="문서 관리"]'));
  assert.equal(await shown(page, '#rc-knowledge [data-rc="AI Batch Log"]'), false);
  await page.evaluate(() => window.AI365_setActingUser(null));
  await until(() => shown(page, '#rc-knowledge [data-rc="AI Batch Log"]'));
  assert.deepEqual(errors, []);
});

test('hydration publishes AI365_LOCAL_AGENTS from pvtree m_res › p_klocal, and [] when there are none', async t => {
  const one = await app(t);
  assert.deepEqual(await one.page.evaluate(() => window.AI365_LOCAL_AGENTS), [{ id: 'kl_demo_hq', label: '본사 지식 에이전트' }]);
  const none = await app(t, { agents: [] });
  assert.deepEqual(await none.page.evaluate(() => window.AI365_LOCAL_AGENTS), []);
  const noTree = await app(t, { bootstrap: { groups: [], members: [], teams: [] } });   // pvtree 없음 = [] / no pvtree = []
  assert.deepEqual(await noTree.page.evaluate(() => window.AI365_LOCAL_AGENTS), []);
  // 수화가 applyResourceSync 보다 먼저 / hydration sets the global before applyResourceSync
  const hyd = block('  (function ai365HydrateAccess(){', '  })();');
  assert.ok(hyd.indexOf('window.AI365_LOCAL_AGENTS=klAgentsFromTree(d.pvtree);') < hyd.indexOf('applyResourceSync(d);'));
  assert.deepEqual([one.errors, none.errors, noTree.errors], [[], [], []]);
});

test('both resource pages carry a [Public | Local] strip that opens on Public; Local lists agents without an LV badge, auto-opens once and keeps the caret', async t => {
  for (const [id, tree] of [['docMgrScroll', 'docTree'], ['rmPaneKnow', 'rmTree']]) {   // 마크업 / markup
    const start = mockup.indexOf('id="' + id + '"'), seg = mockup.indexOf('kl-segbar', start);
    const strip = mockup.slice(start, mockup.indexOf('</div></div>', seg) + 12);
    assert.match(strip, /data-kltab="public" role="tab" aria-selected="true">Public<\/button><button type="button" class="kl-seg-btn" data-kltab="local" role="tab" aria-selected="false">Local<\/button>/, id);
    // 카테고리 칸 안, 제목 줄 아래 · 트리 위(2026-10-06) / inside the category panel, under the title row and above the tree
    assert.ok(mockup.indexOf('class="rm-panel-head"', start) < seg && seg < mockup.indexOf('id="' + tree + '"', start), id);
  }
  const { page, errors } = await app(t);
  await page.evaluate(() => window.openDocMgr());
  assert.deepEqual(await page.$eval('#docMgrScroll .kl-segbar', e => {
    const seg = e.querySelector('.kl-seg'), on = e.querySelector('.kl-seg-btn.on'), probe = document.createElement('i');
    probe.style.background = 'var(--primary)'; document.body.appendChild(probe);
    const primary = getComputedStyle(probe).backgroundColor; probe.remove();
    return [e.parentElement.classList.contains('rm-panel'), e.nextElementSibling.id, getComputedStyle(seg).borderTopLeftRadius,
      Math.abs(seg.getBoundingClientRect().width - (e.clientWidth - 24)) < 1, getComputedStyle(on).color, getComputedStyle(on).backgroundColor === primary];
  }), [true, 'docTree', '9999px', true, 'rgb(255, 255, 255)', true]);
  // 꽉 찬 알약(좌우 12 안쪽) · 켠 쪽은 주 색 + 흰 글자(Dev KnowledgeFolder.tsx, 2026-10-28 Dev 원본 정렬)
  // a full-width pill strip (12 side padding); the active side is the primary colour with white text (Dev KnowledgeFolder.tsx)
  const tabs = () => page.$$eval('#docMgrScroll [data-kltab]', els => els.map(e => e.textContent + (e.classList.contains('on') ? '*' : '')));
  assert.deepEqual(await tabs(), ['Public*', 'Local']);
  await page.click('#docMgrScroll [data-kltab="local"]');
  await page.waitForSelector('#docTree [data-kltree="agent"]');
  assert.equal(await page.textContent('#docTreeTitle'), '에이전트');
  // 에이전트 줄 = 0단계지만 'LV.0' 배지는 없다(2026-10-08) / agent rows are level 0 but carry no 'LV.0' badge
  assert.deepEqual(await page.$$eval('#docTree [data-kltree="agent"]', els => els.map(e => [e.querySelector('.rm-lv'), e.querySelector('.rm-node-name').textContent, e.querySelector('.kl-dot').className, e.querySelector('.rm-node-cnt').textContent])),
    [[null, '본사 지식 에이전트', 'kl-dot ok', '2']]);
  // 처음 고르면 펼친다 → 캐럿으로 접으면 다시 골라도 접힌 채 / the first pick expands; after the caret folds it, picking keeps it folded
  await page.click('#docTree [data-kltree="agent"] .rm-node-name');
  await page.waitForSelector('#docTree [data-kltree="folder"]');
  assert.deepEqual(await page.$$eval('#docTree [data-kltree="folder"] .rm-lv', els => els.map(e => e.textContent)), ['LV.1', 'LV.2']);
  await page.click('#docTree [data-kltree="agent"] .rm-node-caret');
  assert.equal(await page.$('#docTree [data-kltree="folder"]'), null);
  await page.click('#docTree [data-kltree="agent"] .rm-node-name');
  assert.equal(await page.$('#docTree [data-kltree="folder"]'), null);
  await page.click('#docTree [data-kltree="agent"] .rm-node-caret');
  await page.waitForSelector('#docTree [data-kltree="folder"]');
  await page.waitForSelector('#docFilesBody tbody tr');
  // 맨 앞 = 선택 열(머리는 전체 선택 체크, 2026-10-28 Dev KnowledgeFile.tsx) / the first column picks files (its head is select-all; Dev)
  assert.deepEqual(await page.$$eval('#docFilesBody thead th', els => els.map(e => e.textContent)), ['', '번호', '파일명', '크기', '처리 상태', '다운로드']);
  assert.equal(await page.getAttribute('#docFilesBody thead th:first-child [data-docckall]', 'aria-checked'), 'false');
  assert.equal(await page.getAttribute('#docFilesBody [data-kldl="d1"]', 'aria-label'), '다운로드');
  // 다시 열면 Public / reopening lands on Public
  await page.evaluate(() => window.openDocMgr());
  assert.deepEqual(await tabs(), ['Public*', 'Local']);
  assert.equal(await page.textContent('#docTreeTitle'), '카테고리');
  // 리소스 관리 Local: 요약 줄 · 삭제 열, 삭제 확인은 문구와 이름을 따로 / RM Local: summary, Delete column; the delete confirm keeps message and name apart
  await rmLocal(page, false);
  await page.waitForSelector('#rmFilesBody .kl-sum');
  assert.deepEqual(await page.$$eval('#rmFilesBody .kl-sum-k', els => els.map(e => e.textContent)), ['MCP', 'API', 'LLM', '마지막 확인']);
  await page.waitForSelector('#rmFilesBody tbody tr');
  assert.deepEqual(await page.$$eval('#rmFilesBody thead th', els => els.map(e => e.textContent)), ['번호', '파일명', '크기', '처리 상태', '다운로드', '삭제']);
  await page.click('#rmFilesBody [data-kldel="d1"]');
  await page.waitForSelector('#rmDeleteOv.open');
  assert.deepEqual(await page.$$eval('#rmDeleteMsg > span', els => els.map(e => [e.className, e.textContent])), [['kl-del-q', '이 파일을 삭제하시겠습니까?'], ['kl-del-name', '규정.pdf']]);
  assert.deepEqual(await page.$$eval('#rmDeleteImpact li', els => els.map(e => e.textContent)), ['에이전트 저장소에서 삭제되며 복구할 수 없습니다.']);
  assert.deepEqual(errors, []);
});

// 문서 관리 = Dev KnowledeDetail.tsx · KnowledgeFile.tsx(2026-10-28): 머리 [파일 업로드] 주 알약(권한 없으면 숨김), 첫 폴더 자동 선택, 선택 열 + 전체 선택,
// 검색은 3글자부터, Public 만 "연결된 SharePoint (0)" 줄, 고르면 검색 대신 "n개 선택됨" + [다운로드](일괄 동작은 다운로드만)
// Document management follows Dev: the page-head [Upload files] pill (hidden without rights), the first folder picked on open, a pick column with
// select-all, search from three letters, the Public-only "Connected SharePoint (0)" line, and "n selected" + [Download] once files are picked
test('document management follows the Dev layout: page-head upload pill, pick column, three-letter search, SharePoint line and bulk download', async t => {
  const { page, errors } = await app(t);
  await page.evaluate(() => { openResourceCenter(); window.openDocMgr(); });
  await page.waitForSelector('#docFilesBody .doc-empty, #docFilesBody table');
  assert.deepEqual(await page.evaluate(() => {
    const up = document.getElementById('docUploadBtn');
    return [!!up.closest('.pg-pagehead'), !!up.closest('.rm-panel-head'), up.textContent, getComputedStyle(up).borderTopLeftRadius, getComputedStyle(up).fontSize,
      document.querySelector('#docMgrScroll .pg-pagesub').textContent, (document.querySelector('#docTree .rm-node.sel .rm-node-name') || {}).textContent === document.getElementById('docFilesTitle').textContent];
  }), [true, false, '파일 업로드', '9999px', '16px', '조직의 문서 자산을 한곳에서 등록하고 관리합니다', true]);
  await page.click('#docTree [data-docnode="k_notice"] .rm-node-name');
  await page.waitForSelector('#docFilesBody tbody tr');
  assert.deepEqual(await page.$$eval('#docFilesBody thead th', els => els.map(e => e.textContent)), ['', '번호', '파일명', '크기', '인덱싱', '다운로드']);
  assert.deepEqual(await page.evaluate(() => [getComputedStyle(document.querySelector('#docFilesBody thead th')).backgroundColor,
    Math.round(document.querySelector('#docFilesBody tbody tr').getBoundingClientRect().height), document.getElementById('docSpRow').textContent.replace(/\s+/g, ' ').trim(),
    !document.getElementById('docSpRow').hidden, Math.round(document.getElementById('docSearch').getBoundingClientRect().width)]),
    ['rgb(239, 242, 250)', 49, '연결된 SharePoint (0)', true, 197]);
  const idx = await page.$$eval('#docFilesBody .rm-idx', els => els.map(e => e.textContent));
  assert.ok(idx.includes('진행 중') && idx.includes('대기 중') && idx.includes('완료'), JSON.stringify(idx));   // Dev 인덱싱 표시 / Dev indexing labels
  const head = () => page.evaluate(() => [document.getElementById('docSearch').hidden, document.getElementById('docBulk').hidden, document.getElementById('docSelN').textContent,
    document.querySelectorAll('#docFilesBody tr.doc-picked').length]);
  await page.click('#docFilesBody tbody tr:nth-child(1) [data-docck]');
  await page.click('#docFilesBody tbody tr:nth-child(2) [data-docck]');
  assert.deepEqual(await head(), [true, false, '2', 2]);
  assert.equal(await page.$eval('#docViewOv', ov => ov.classList.contains('open')), false);   // 체크는 열람 창을 열지 않는다 / a check does not open the viewer
  await page.click('#docFilesBody thead [data-docckall]');
  assert.deepEqual(await head(), [true, false, '10', 10]);
  await page.click('#docFilesBody thead [data-docckall]');
  assert.deepEqual(await head(), [false, true, '0', 0]);
  await page.click('#docFilesBody tbody tr:nth-child(1) [data-docck]');
  await page.click('#docBulkDl');
  await page.waitForFunction(() => document.getElementById('toast').textContent === '파일을 다운로드합니다.');
  await page.click('#docFilesBody tbody tr:nth-child(1) [data-docck]');
  await page.fill('#docSearchIn', '면접');   // 두 글자 = 거르지 않는다 / two letters do not filter
  await page.waitForTimeout(400);
  assert.equal(await page.$$eval('#docFilesBody tbody tr', trs => trs.length), 10);
  await page.fill('#docSearchIn', '면접관');
  await page.waitForFunction(() => document.querySelectorAll('#docFilesBody tbody tr').length === 1);
  assert.equal(await page.textContent('#docFilesBody tbody .rm-fname'), '면접관_교육자료_v2.pdf');
  await page.fill('#docSearchIn', '없는파일');
  await page.waitForFunction(() => !!document.querySelector('#docFilesBody .doc-empty'));
  assert.equal(await page.$eval('#docFilesBody .rm-empty', e => e.textContent), '!업로드된 파일이 없습니다.');
  // Local 탭: SharePoint 줄 없음 / the Local tab has no SharePoint line
  await page.click('#docMgrScroll [data-kltab="local"]');
  await page.waitForSelector('#docTree [data-kltree="agent"]');
  assert.equal(await page.$eval('#docSpRow', e => e.hidden), true);
  // 영어 화면: 새 Dev 문구도 번역된다(목업 DOC_KO2EN 표) / the English screen translates the new Dev strings too (the mockup's DOC_KO2EN table)
  await page.evaluate(() => { localStorage.setItem('ai365_lang', 'en'); ai365ApplyLang('en'); });
  await page.waitForFunction(() => document.querySelector('#docMgrScroll .pg-pagesub').textContent.startsWith('Register'));   // 번역은 비동기로 한 번 더 돌 수 있다 / translation may run once more asynchronously
  assert.deepEqual(await page.evaluate(() => [document.querySelector('#docMgrScroll .pg-pagesub').textContent, document.getElementById('docSpRow').textContent.replace(/\s+/g, ' ').trim(),
    document.querySelector('#docUploadBtn').textContent, document.getElementById('docSearchIn').placeholder]),
    ["Register and manage your organization's document assets in one place", 'Connected SharePoint (0)', 'Upload File', 'Search']);
  // 어댑터의 #viewResource 관찰자는 EN 일 때 40ms 뒤 'en' 으로 다시 번역한다(타이머 안에서 언어를 다시 보지 않음). 사람의 전환처럼 그 뒤에 KO 로
  // the adapter's #viewResource observer re-translates to 'en' 40 ms later without re-checking the language, so switch back after it, as a person would
  await page.waitForTimeout(150);
  await page.evaluate(() => { localStorage.setItem('ai365_lang', 'ko'); ai365ApplyLang('ko'); });
  await page.waitForFunction(() => document.querySelector('#docMgrScroll .pg-pagesub').textContent === '조직의 문서 자산을 한곳에서 등록하고 관리합니다', null, { timeout: 5000 });
  // 볼 수 있는 폴더가 없는 사용자 = 업로드 권한 없음 → 버튼 숨김(rm-locked) / a user with no folders has no upload right: the button hides
  await page.evaluate(() => window.AI365_setActingUser(7));
  await page.waitForFunction(() => window.AI365_ACTING_USER && window.AI365_ACTING_USER.no === 7);
  await page.evaluate(() => { openResourceCenter(); window.openDocMgr(); });
  await page.waitForFunction(() => document.getElementById('docUploadBtn').classList.contains('rm-locked'));
  assert.equal(await page.$eval('#docUploadBtn', b => getComputedStyle(b).display), 'none');
  assert.deepEqual(errors, []);
});

test('English labels the list, the edit page and the delete confirms; Korean keeps product names such as Claude', async t => {
  const { page, errors } = await app(t, { agents: [AGENT, LAB] });
  await page.evaluate(() => { localStorage.setItem('ai365_lang', 'en'); ai365ApplyLang('en'); });
  await localList(page);
  await page.waitForFunction(() => document.getElementById('llmAddMcp').textContent === '+ Register local agent');
  assert.equal(await page.textContent('#pgLlmScroll .pg-pagetitle'), 'Local LLM & DB setting');
  await page.click('#llmAddMcp');
  await page.waitForSelector('#klPage [data-klf="name"]');
  assert.equal(await page.textContent('#klPage .mcf-title'), 'Register local agent');
  assert.equal(await page.textContent('#klPage .mcf-sub'), 'Connect to the MCP server and API server of a local agent deployed in a customer environment, and set its deployment settings and skill files.');
  assert.equal(await page.textContent('#klPage [data-kl-demo]'), 'Demo: fill the lab agent');
  await page.click('#klPage .mcf-back');
  await page.click('#llmBody [data-kledit="kl_ab12cd34"]');
  await page.waitForSelector('#klPage [data-kl-del]:not([disabled])');
  await page.click('#klPage [data-kl-del]');
  await page.waitForSelector('#klConfirmOv.open');
  assert.deepEqual(await page.$$eval('#klConfirmOv .pg-confirm-title, #klConfirmBody .kl-del-q, #klConfirmBody .kl-del-name, #klConfirmOk', els => els.map(e => e.textContent)),
    ['Delete', 'Delete this local agent connection?', '연구소 지식 에이전트', 'Delete']);
  await page.click('#klConfirmOv [data-klc-close]');
  await page.click('#klPage .mcf-back');
  await rmLocal(page, false);
  await page.waitForSelector('#rmFilesBody [data-kldel="d1"]');
  await page.click('#rmFilesBody [data-kldel="d1"]');
  await page.waitForFunction(() => document.querySelector('#rmDeleteMsg .kl-del-q').textContent === 'Delete this file?');
  assert.equal(await page.textContent('#rmDeleteMsg .kl-del-name'), '규정.pdf');
  await page.click('#rmDeleteX');
  // 한국어로 돌아와도 Claude 는 Claude / back in Korean, Claude stays Claude
  await page.evaluate(() => { localStorage.setItem('ai365_lang', 'ko'); ai365ApplyLang('ko'); });
  await page.evaluate(() => window.AI365_openLocalAgent('kl_demo_hq'));
  await page.waitForSelector('#klPage [data-klf="settings.llm.type"]');
  await page.selectOption('#klPage select[data-klf="settings.llm.type"]', 'public');
  await page.waitForSelector('#klPage select[data-klf="settings.llm.model"] option[value="claude"]', { state: 'attached' });
  await page.evaluate(() => ai365ApplyLang('ko'));
  assert.equal(await page.textContent('#klPage select[data-klf="settings.llm.model"] option[value="claude"]'), 'Claude');
  assert.equal(await page.textContent('#klPage .mcf-title'), '로컬 에이전트 수정');
  assert.deepEqual(errors, []);
});

test('saving a group re-derives Local only when the Local tab changed; an m_res manage group gets exclude + view for a view row', async t => {
  const agents = [AGENT, LAB];
  const group = { id: 'og5', name: '검증 그룹', desc: '검증', memberIds: [7], teams: [], menus: ['m_home', 'm_chat', 'm_res'],   // 3단계 완료에는 구성원 1명 이상 / step 3 needs a member
    grants: [{ node: 'p_know', action: 'view' }, { node: 'p_klocal', action: 'view' }, { node: 'kl_demo_hq', action: 'manage' }], exceptions: [{ node: 'kl_ab12cd34', type: 'exclude' }] };
  const ceo = { id: 'og6', name: '대표 그룹', desc: '검증', memberIds: [7], teams: [], menus: ['m_home', 'm_chat', 'm_res'], grants: [{ node: 'm_res', action: 'manage' }], exceptions: [] };
  const { page, errors, puts } = await app(t, { agents: agents, groups: [group, ceo],
    members: [{ no: 7, name: '강수아', dept: '인사총무', grade: '사원', empno: 7, email: '' }], teams: ['인사총무'] });
  const openEdit = async gid => {
    await page.evaluate(() => { document.getElementById('navPerm').click(); document.querySelector('[data-hubcard="access"]').click(); });
    await page.click('#pgGroupList [data-gid="' + gid + '"]');
    await page.click('#pgEditBtn');
    await page.click('#pgNext');   // 2단계 / step 2
    await page.click('#pgStep2 .pg-acc:has([data-kntab]) [data-acc-head]');   // 지식 관리 카드 펼치기 / open the knowledge card
  };
  const save = async () => {   // 3단계 → 완료, 그룹 PUT 이 올 때까지 / step 3 → done, until the group PUT arrives
    const n = puts.length;
    await page.click('#pgNext'); await page.click('#pgNext');
    for (let i = 0; i < 400 && puts.length <= n; i++) await page.waitForTimeout(50);   // 병렬 실행 부하에도 넉넉히 / generous under parallel runs
    assert.equal(puts.length, n + 1);
  };
  const levels = () => page.$$eval('#pgStep2 [data-knpane="local"] .pg-lvopt.is-on', els => els.map(e => e.textContent));
  const localOf = x => ({ grants: x.grants.filter(e => /^kl_|^p_klocal$/.test(e.node)), exceptions: x.exceptions.filter(e => /^kl_|^p_klocal$/.test(e.node)) });
  // 1) 불러온 Local 레벨 = 본사 관리 · 연구소 차단 / loaded Local levels: HQ manage, lab blocked
  await openEdit('og5');
  await page.click('#pgStep2 [data-kntab="local"]');
  assert.deepEqual(await levels(), ['관리', '차단']);
  // 2) Public 만 바꿔 저장 → Local grant · 예외 그대로 / Public-only edit keeps every Local grant and exception
  await page.click('#pgStep2 [data-kntab="public"]');
  await page.click('#pgStep2 [data-knpane="public"] tbody tr:first-child [data-lvl="0"]');
  await save();
  let g = puts[puts.length - 1].groups.find(x => x.id === 'og5');
  assert.deepEqual(localOf(g), { grants: [{ node: 'p_klocal', action: 'view' }, { node: 'kl_demo_hq', action: 'manage' }], exceptions: [{ node: 'kl_ab12cd34', type: 'exclude' }] });
  // 3) Local 만 바꿔 저장(연구소 = 열람) → p_know 앵커 유지, Local 재파생 / Local-only edit keeps p_know and re-derives Local
  await page.evaluate(() => { const gg = window.AI365_ORG_GROUPS.find(x => x.id === 'og5'); gg.grants = [{ node: 'p_know', action: 'view' }, { node: 'p_klocal', action: 'view' }, { node: 'kl_demo_hq', action: 'manage' }]; gg.exceptions = [{ node: 'kl_ab12cd34', type: 'exclude' }]; });
  await openEdit('og5');
  await page.click('#pgStep2 [data-kntab="local"]');
  await page.click('#pgStep2 [data-knpane="local"] tbody tr:nth-child(2) [data-lvl="1"]');
  assert.deepEqual(await levels(), ['관리', '열람']);
  await save();
  g = puts[puts.length - 1].groups.find(x => x.id === 'og5');
  assert.deepEqual(g.grants.filter(e => e.node === 'p_know'), [{ node: 'p_know', action: 'view' }]);
  assert.deepEqual(localOf(g), { grants: [{ node: 'p_klocal', action: 'view' }, { node: 'kl_demo_hq', action: 'manage' }], exceptions: [] });
  // 4) m_res 관리 그룹: 둘 다 관리로 보이고, 연구소를 열람으로 → exclude 뒤 view / m_res manage: both load as manage; lab to view → exclude then view
  await openEdit('og6');
  await page.click('#pgStep2 [data-kntab="local"]');
  assert.deepEqual(await levels(), ['관리', '관리']);
  await page.click('#pgStep2 [data-knpane="local"] tbody tr:nth-child(2) [data-lvl="1"]');
  await save();
  g = puts[puts.length - 1].groups.find(x => x.id === 'og6');
  assert.deepEqual(g.grants, [{ node: 'm_res', action: 'manage' }]);
  assert.deepEqual(g.exceptions, [{ node: 'kl_ab12cd34', type: 'exclude' }, { node: 'kl_ab12cd34', type: 'view' }]);
  await openEdit('og6');   // 다시 열면 관리 · 열람 / reopening shows manage and view
  await page.click('#pgStep2 [data-kntab="local"]');
  assert.deepEqual(await levels(), ['관리', '열람']);
  assert.deepEqual(errors, []);
});
