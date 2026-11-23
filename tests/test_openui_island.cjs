// 실행: Playwright 가 NODE_PATH 에 있을 때
//   NODE_PATH="<npm root -g>" node --test --test-concurrency=1 tests/test_openui_island.cjs
// OpenUI 섬 번들(static/openui, frontend/openui 에서 빌드)을 격리 브라우저에서 돌린다: 감싼 글 · 사내 출처(ai365://) 칩 ·
// 인용 번호 칩(2026-10-29, 예전 채팅 각주 모양 · 누르면 바로 열기) · http 출처(window.open noopener) · 후속 질문 · 폼 값 ·
// 스트리밍 중 잘린 프로그램 · 마크다운 대체 · 표 · 차트 ·
// Mermaid 지연 청크 · 화면 글자 한/영 · 렌더 오류 보고 · 목업 위임 셀렉터 · 실제 목업에서 CSS 격리. 검증 도구(validate.mjs)와
// 생성 프롬프트 · 번들 버전도 확인한다. 서버 · DB · LLM 없음(가짜 원점 + page.route). 캡처는 AI365_SHOTS 폴더(있을 때만).
// 2단계(계약 9절): 서버 데이터 문장(d1 · d1top · d1sum · gw1) 참조로 그리는 표 · 차트 · Stat · 글 · 내장 함수 · 그룹웨어 목록과 질문 단추,
// 표 "number" 열, 데이터 · 그룹웨어 출처 아이콘, 서버 규칙이 피해야 할 한계, 프롬프트 Example 10 · 11.
// Phase 2 (contract section 9): tables, charts, stats, text and built-ins bound to the server's data statements (d1, d1top,
// d1sum, gw1), groupware lists and question buttons, Table "number" columns, data and groupware source icons, the limits
// the server rules must avoid, and the prompt's Examples 10 and 11.
// Run with Playwright on NODE_PATH (see above). Runs the OpenUI island bundle (static/openui, built from frontend/openui)
// in an isolated browser: wrapped text, internal (ai365://) source chips, citation number chips (2026-10-29, the old chat
// footnote look; a click opens the source), http sources (window.open with noopener), follow-ups, form values, a program
// cut mid-statement while streaming, the markdown
// fallback, tables, charts, the lazy Mermaid chunk, Korean/English labels, render error reporting, the mockup's
// delegated selectors, and CSS isolation on the real mockup. Also checks the validator (validate.mjs), the generated
// prompt and the bundle version. No server, DB or LLM (a fake origin + page.route). Screenshots go to AI365_SHOTS when set.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { chromium } = require('playwright');

const ROOT = path.join(__dirname, '..');
const STATIC = path.join(ROOT, 'static');
const ISLAND_SRC = path.join(ROOT, 'frontend/openui');
const ORIGIN = 'http://oui.test';
const SHOTS = process.env.AI365_SHOTS || '';

// 목업 #chatInner 의 위임 클릭 처리기가 반응하는 셀렉터(섬 DOM 에 있으면 안 된다)
// Selectors the mockup's delegated #chatInner click handlers react to (the island DOM must have none)
const DELEGATED = ['.option-row', '[data-group]', '[data-followup]', '.foot-btn', '[data-copy]', '.chart-tab', '.lnk',
  '.task-toggle', '[data-open-artifact]', '[data-detail]'];

const KN1 = 'ai365://kn/%EC%B6%9C%EC%9E%A5%20%EC%97%AC%EB%B9%84%20%EA%B7%9C%EC%A0%95.pdf?page=3';
const KN2 = 'ai365://kn/%EA%B2%BD%EB%B9%84%20%EC%A7%80%EC%B9%A8.pdf?page=1';

// 서버가 출처 문장을 먼저 흘리는 사내 문서 답(계약 8절) / an internal-document answer, sources first (contract section 8)
const INTERNAL = [
  `src1 = {title: "출장 여비 규정 p.3", sourceName: "인사 › 규정", url: ${JSON.stringify(KN1)}}`,
  `src2 = {title: "경비 처리 지침 p.1", sourceName: "재무 › 지침", url: ${JSON.stringify(KN2)}}`,
  'root = Card([header, summary, steps, limits, note, followUps], [src1, src2])',
  'header = CardHeader("국내 출장비 정산 절차", "인사 › 규정 기준")',
  'summary = TextContent("국내 출장비는 출장을 마친 날부터 **7일 안에** 정산합니다 [1]. 숙박비는 실비로 지급합니다 [2]. 자세한 건 [규정 원문](ai365://kn/rule.pdf?page=2) 을 보세요.")',
  'steps = Steps([st1, st2])',
  'st1 = StepsItem("증빙 모으기", "영수증과 카드 전표를 모읍니다.")',
  'st2 = StepsItem("정산서 작성", "전자결재에서 정산서를 올립니다.")',
  'limits = EntityList([{left: "숙박비", right: "1박 8만 원"}, {left: "식비", right: "1일 3만 원"}])',
  'note = Callout("info", "확인하세요", "법인카드로 낸 비용은 개인 정산에서 뺍니다.")',
  'followUps = FollowUpBlock([fu1, fu2])',
  'fu1 = FollowUpItem("해외 출장비 규정도 알려줘")',
  'fu2 = FollowUpItem("정산서 양식은 어디 있어?")',
].join('\n');

const FORM = [
  'root = Card([form])',
  'form = Form("trip", Buttons([Button("계획 세워 줘", @ToAssistant("출장 계획을 세워 줘"), "primary")]), [fc1, fc2])',
  'fc1 = FormControl("목적지", Input("destination", "예: 부산", "text", {required: true}))',
  'fc2 = FormControl("인원", Select("people", [SelectItem("1", "1명"), SelectItem("2", "2명")], "선택"))',
].join('\n');

const DATA = [
  'root = Card([tbl, chart, pie])',
  'tbl = Table([Col("부서", ["영업", "개발", "인사"]), Col("인원", [12, 30, 5], "number"), Col("상태", [Tag("증가", null, "sm", "success"), Tag("유지", null, "sm", "neutral"), Tag("감소", null, "sm", "danger")])])',
  'chart = BarChart(["1분기", "2분기", "3분기"], [Series("매출", [120, 150, 170]), Series("비용", [80, 90, 95])], "grouped")',
  'pie = PieChart(["A", "B"], [60, 40], "donut")',
].join('\n');

// ── 2단계(계약 9절): 서버가 프로그램 앞에 흘리는 데이터 · 그룹웨어 · 출처 문장. 모델은 이름으로 참조만 한다.
// ── Phase 2 (contract section 9): the data, groupware and source statements the server streams ahead of the program;
//    the model only refers to them by name.

/** openui-lang 값 표기(서버 문장과 같이: 키는 이름 그대로, 값은 JSON) / An openui-lang value, written like the server's statements. */
function oui(value) {
  if (Array.isArray(value)) return '[' + value.map(oui).join(', ') + ']';
  if (value !== null && typeof value === 'object') return '{' + Object.entries(value).map(([k, v]) => k + ': ' + oui(v)).join(', ') + '}';
  return JSON.stringify(value);
}

// 월 · 매출액(억 원) · 주문 건수(2월은 빈 값) · 매출액(원) / month, sales (100M won), orders (February empty), sales (won)
const D_ROWS = [
  ['1월', 42.5, 96, 4250000000], ['2월', 38.1, null, 3810000000], ['3월', 51.2, 104, 5120000000], ['4월', 47, 99, 4700000000],
  ['5월', 55.25, 110, 5525000000], ['6월', 60, 120, 6000000000], ['7월', 58.4, 118, 5840000000], ['8월', 61.9, 121, 6190000000],
  ['9월', 64, 130, 6400000000], ['10월', 70.1, 140, 7010000000], ['11월', 72.3, 150, 7230000000], ['12월', 80, 160, 8000000000],
].map(([c1, c2, c3, c4]) => ({ c1, c2, c3, c4 }));
// 서버 코드가 계산하는 요약(빈 값은 뺀다). chg = 부호 붙은 변화율 글자(change 가 null 이면 "")
// the summary the server code computes (empty cells left out); chg = the signed change as text ("" when change is null)
const D_SUM = {
  c2: { sum: 700.75, avg: 58.4, min: 38.1, max: 80, first: 42.5, last: 80, change: 88.2, chg: '+88.2%' },
  c3: { sum: 1348, avg: 122.55, min: 96, max: 160, first: 96, last: 160, change: 66.7, chg: '+66.7%' },
  c4: { sum: 70075000000, avg: 5839583333.33, min: 3810000000, max: 8000000000, first: 4250000000, last: 8000000000, change: 88.2, chg: '+88.2%' },
};
// 따옴표 · 역슬래시가 든 한국어 제목 / Korean titles with quotes and backslashes
const GW_ROWS = [
  { left: '3분기 예산안 검토 요청', right: '김지민 · 10:12' },
  { left: '"신제품" 출시 일정 공유', right: '박서준 · 09:40' },
  { left: '경로 C:\\공유\\보고서 확인', right: '이하늘 · 어제' },
];
const DATA_URL = 'ai365://data/sales_monthly?ws=sales';
const BI_URL = 'ai365://data/bi/sales.pbix?ws=sales';
const DATA_SRC = { title: '월별 매출', sourceName: '데이터 분석 › 영업 › DB', url: DATA_URL };
const GW_SRC = { title: '받은편지함', sourceName: '그룹웨어 › 메일' };   // 그룹웨어 출처는 url 이 없다 / groupware sources have no url
const PREFIX = [
  `d1 = ${oui(D_ROWS)}`,
  `d1top = ${oui(D_ROWS.slice(0, 10))}`,
  `d1sum = ${oui(D_SUM)}`,
  `gw1 = ${oui(GW_ROWS)}`,
  `src1 = ${oui(DATA_SRC)}`,
  `src2 = ${oui(GW_SRC)}`,
].join('\n');

// 데이터 분석 답: 모든 숫자가 데이터 문장 참조 · 내장 함수 / a data answer: every number is a data statement reference or a built-in
const DATA_ANSWER = [
  'root = Card([header, summary, stats, chart, line, table, note, fu], [src1])',
  'header = CardHeader("월별 매출 추이", "영업 실적 데이터 기준")',
  'summary = TextContent("12개월 매출 합계는 **" + @FormatNumber(d1sum.c2.sum) + "억 원**이고 최고는 " + d1sum.c2.max + "억 원입니다 [1]. 1월은 " + d1[0].c2 + "억 원입니다.")',
  'stats = StatStrip([s1, s2, s3, s4])',
  's1 = Stat(@FormatNumber(d1sum.c2.sum) + "억", "매출 합계", @FormatNumber(d1sum.c2.change, 1) + "%")',
  's2 = Stat(@FormatNumber(@Sum(d1.c2)) + "억", "합계(@Sum)")',
  's3 = Stat("" + @Round(@Avg(d1.c2), 1), "월평균(@Round · @Avg)")',
  's4 = Stat((d1sum.c3.change >= 0 ? "+" : "") + @FormatNumber(d1sum.c3.change, 1) + "%", "주문 변화", null, null, "📦")',
  'chart = BarChart(d1.c1, [Series("매출액", d1.c2)])',
  'line = LineChart(d1.c1, [Series("매출액", d1.c2), Series("주문 건수", d1.c3)], "natural", null, "억 원 · 건")',
  'table = Table([Col("월", d1top.c1), Col("매출액(억 원)", d1top.c2, "number"), Col("주문 건수", d1top.c3, "number"), Col("매출액(원)", d1top.c4, "number")])',
  'note = Callout("info", "변동 폭", "최저 " + @FormatNumber(d1sum.c2.min) + "억 원, 최고 " + @FormatNumber(d1sum.c2.max) + "억 원")',
  'fu = FollowUpBlock([FollowUpItem("분기별로 보여줘")])',
].join('\n');

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

/** static/ 아래 파일을 그대로 / a file under static/, as is */
function staticFile(route, pathname) {
  const file = path.join(STATIC, pathname.replace(/^\/static\//, ''));
  if (!file.startsWith(STATIC) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) return route.fulfill({ status: 404, body: '' });
  const type = file.endsWith('.css') ? 'text/css; charset=utf-8' : file.endsWith('.js') ? 'text/javascript; charset=utf-8' : 'text/plain; charset=utf-8';
  return route.fulfill({ status: 200, contentType: type, body: fs.readFileSync(file) });
}

// 섬 진입점 = adapter 처럼 쿼리(?v=)를 붙인 주소 / the island entry, with a query (?v=) like the adapter's
const ENTRY = '/static/openui/openui.js?v=test';

// 구글 파비콘 대역: 32px 그림(16px 이하면 OpenUI 가 실패로 본다) / a Google favicon stand-in: 32px (16px or less counts as a miss)
const FAVICON_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" rx="6" fill="#1a73e8"/></svg>';

// 섬만 있는 빈 화면: 모듈을 불러오고 window.open 을 기록용으로 바꾼다(favicons: 구글 파비콘 요청에 그림으로 답한다)
// A page with the island only: loads the module and records window.open (favicons: Google favicon requests get an image)
async function islandPage(t, opts) {
  opts = opts || {};
  const page = await browser.newPage({ viewport: { width: 1100, height: 900 } });
  const state = { errors: [], external: [], navigations: 0, requests: [], consoleErrors: [] };
  page.on('pageerror', e => state.errors.push(e.message));
  page.on('framenavigated', f => { if (f === page.mainFrame()) state.navigations++; });
  // 같은 원점 요청(경로 + 쿼리) · 콘솔 오류를 기록한다(라우팅 중엔 HTTP 캐시가 꺼져 모든 내려받기가 보인다)
  // record same-origin requests (path + query) and console errors (routing disables the HTTP cache, so every fetch shows)
  page.on('request', r => { const u = new URL(r.url()); if (u.origin === ORIGIN) state.requests.push(u.pathname + u.search); });
  page.on('console', m => { if (m.type() === 'error') state.consoleErrors.push(m.text()); });
  t.after(async () => { await page.close(); assert.deepEqual(state.errors, []); });
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== ORIGIN) {
      state.external.push(url.href);
      if (opts.favicons && url.host === 'www.google.com' && url.pathname === '/s2/favicons') {
        return route.fulfill({ status: 200, contentType: 'image/svg+xml', body: FAVICON_SVG });
      }
      return route.fulfill({ status: 404, body: '' });
    }
    if (url.pathname === '/') {
      return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body:
        '<!doctype html><html lang="ko"><head><meta charset="utf-8"><link rel="stylesheet" href="/static/openui/openui.css"></head>' +
        '<body style="margin:0;padding:24px;font-family:Pretendard,sans-serif"><div id="host" style="width:760px"></div></body></html>' });
    }
    if (url.pathname.startsWith('/static/')) return staticFile(route, url.pathname);
    return route.fulfill({ status: 404, body: '' });
  });
  await page.goto(ORIGIN + '/');
  // adapter 와 같이 쿼리를 붙여 불러온다(?v=버전) / loaded with a query, as the adapter does (?v=version)
  await page.evaluate((entry) => import(entry), ENTRY);
  await page.evaluate(() => {
    window.__events = [];
    window.__opened = [];
    window.open = (...args) => { window.__opened.push(args); return null; };
    // 칩 자리가 보이는 글: 인용 번호 칩 = "^n", <br> = 줄바꿈, 나머지는 글 그대로 / text that shows where the chips sit: a
    // citation number chip = "^n", <br> = a line break, everything else as text
    window.__inline = node => [...node.childNodes].map(n => n.nodeType === 3 ? n.nodeValue : n.nodeType !== 1 ? ''
      : n.classList.contains('ai365-oui-cite') ? '^' + n.textContent : n.tagName === 'BR' ? '\n' : window.__inline(n)).join('');
  });
  state.navigations = 0;
  return { page, state };
}

// 섬을 그린다(opts 의 콜백은 기록용) / renders the island (the opts callbacks record what they get)
function render(page, program, opts) {
  return page.evaluate(([program, opts]) => {
    const el = document.getElementById('host');
    window.AI365_OpenUI.render(el, program, Object.assign({}, opts, {
      onAction: e => window.__events.push(['action', e]),
      onLink: (url, target) => window.__events.push(['link', url, target === el]),
      onError: errors => window.__events.push(['error', errors.map(e => e.code + ':' + (e.component || ''))]),
    }));
  }, [program, opts || {}]);
}

// 섬 도구(frontend/openui/node_modules)가 있어야 하는 검사: 없으면 건너뛴다(npm install 안내)
// Checks that need the island toolchain (frontend/openui/node_modules); skipped without it (run npm install there)
const TOOLCHAIN = fs.existsSync(path.join(ISLAND_SRC, 'node_modules/@openuidev/lang-core'));
const NEEDS_TOOLCHAIN = TOOLCHAIN ? {} : { skip: 'frontend/openui/node_modules missing: run "npm install" in frontend/openui' };

/**
 * build/cssScope.ts 가 덜어 내는 클래스(쓰지 않는 컴포넌트 CSS 파일에만 나오는 클래스)를 같은 규칙으로 다시 센다.
 * Recomputes the classes build/cssScope.ts prunes (classes found only in the unused components' CSS files).
 */
function prunedOnlyClasses() {
  const postcss = require(path.join(ISLAND_SRC, 'node_modules/postcss'));
  const source = fs.readFileSync(path.join(ISLAND_SRC, 'build/cssScope.ts'), 'utf8');
  const list = source.slice(source.indexOf('UNUSED_STYLE_FILES = ['), source.indexOf('];', source.indexOf('UNUSED_STYLE_FILES = [')));
  const unusedFiles = new Set([...list.matchAll(/"([A-Za-z]+)"/g)].map(m => m[1] + '.css'));
  const dir = path.join(ISLAND_SRC, 'node_modules/@openuidev/react-ui/dist/styles');
  const unused = new Set(), kept = new Set();
  for (const name of fs.readdirSync(dir)) {
    if (!name.endsWith('.css') || name === 'index.css' || name === 'openui-defaults.css') continue;
    const target = unusedFiles.has(name) ? unused : kept;
    postcss.parse(fs.readFileSync(path.join(dir, name), 'utf8')).walkRules(rule => {
      for (const sel of rule.selectors) for (const m of sel.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)) target.add(m[1]);
    });
  }
  assert.equal(unusedFiles.size, 19);
  return [...unused].filter(c => !kept.has(c));
}

const events = page => page.evaluate(() => window.__events);
const opened = page => page.evaluate(() => window.__opened);
const shot = async (page, name) => { if (SHOTS) { fs.mkdirSync(SHOTS, { recursive: true }); await page.screenshot({ path: path.join(SHOTS, name), fullPage: true }); } };

test('API: version matches version.txt and the validator schema; toProgram, isProgram and wrapText', async (t) => {
  const { page } = await islandPage(t);
  const version = fs.readFileSync(path.join(STATIC, 'openui/version.txt'), 'utf8').trim();
  const schema = JSON.parse(fs.readFileSync(path.join(ISLAND_SRC, 'dist-node/library.schema.json'), 'utf8'));
  const out = await page.evaluate(() => {
    const api = window.AI365_OpenUI;
    return {
      keys: Object.keys(api).sort(),
      version: api.version,
      fenced: api.toProgram('```openui\nroot = Card([b])\nb = TextContent("x")\n```'),
      isProg: [api.isProgram('root = Card([b])'), api.isProgram('$x = 1'), api.isProgram('# 제목\n본문입니다.'), api.isProgram('')],
      wrapped: api.wrapText('글', [{ title: 'T', sourceName: '인사 › 규정', url: 'ai365://kn/a.pdf?page=1' }], ['다음 질문']),
      plain: api.wrapText('a"b\\c\n한글 ' + String.fromCharCode(0x2028) + ' 😀'),
      noFollow: api.wrapText('본문', [{ title: 'T', sourceName: 'S', url: 'https://x.test/' }, { title: 'U', sourceName: 'S2' }], ['  ', '']),
      trimmed: api.wrapText('본문', null, ['  다음  ', null, '']),
    };
  });
  assert.deepEqual(out.keys, ['isProgram', 'render', 'toProgram', 'unmount', 'version', 'wrapText']);
  assert.equal(out.version, version);
  assert.equal(schema.version, version);                          // gen:prompt 와 build 가 같은 입력 / same inputs
  assert.equal(out.fenced, 'root = Card([b])\nb = TextContent("x")');
  assert.deepEqual(out.isProg, [true, true, false, false]);
  assert.equal(out.wrapped, [
    'root = Card([body, fu], [src1])',
    'body = TextContent("글")',
    'fu = FollowUpBlock([fu1])',
    'fu1 = FollowUpItem("다음 질문")',
    'src1 = {title: "T", sourceName: "인사 › 규정", url: "ai365://kn/a.pdf?page=1"}',
  ].join('\n'));
  assert.equal(out.plain, 'root = Card([body])\nbody = TextContent(' + JSON.stringify('a"b\\c\n한글 ' + String.fromCharCode(0x2028) + ' 😀') + ')');
  // 서버 wrap_text 와 같게: 빈 후속 질문은 빼고(앞뒤 공백 정리), url 이 없는 출처는 url 칸이 없다
  // like the server's wrap_text: blank follow-ups are dropped (trimmed), a source without a url has no url field
  assert.equal(out.noFollow, [
    'root = Card([body], [src1, src2])',
    'body = TextContent("본문")',
    'src1 = {title: "T", sourceName: "S", url: "https://x.test/"}',
    'src2 = {title: "U", sourceName: "S2"}',
  ].join('\n'));
  assert.equal(out.trimmed, 'root = Card([body, fu])\nbody = TextContent("본문")\nfu = FollowUpBlock([fu1])\nfu1 = FollowUpItem("다음")');
});

// adapter 는 openui.js?v=<버전> 으로 부른다. 지연 청크가 쿼리 없는 진입점을 가져오면 번들이 두 번 평가된다(2026-10-27 버그).
// 진입점은 chunks/main-<해시>.js 를 다시 내보내기만 하고, 지연 청크도 그 main 을 가져와 섬은 언제나 한 벌이다.
// The adapter loads openui.js?v=<version>. Lazy chunks importing the plain entry made the bundle run twice (bug of
// 2026-10-27). The entry only re-exports chunks/main-<hash>.js and the lazy chunks import that main too, so there is
// always one island.
test('one island instance: the ?v= entry re-exports chunks/main-<hash>.js, which Mermaid and the icon set share', async (t) => {
  const entrySource = fs.readFileSync(path.join(STATIC, 'openui/openui.js'), 'utf8');
  const main = /from"\.\/chunks\/(main-[\w-]+\.js)"/.exec(entrySource);
  assert.ok(main && entrySource.length < 1024, entrySource.slice(0, 200));
  const chunkDir = path.join(STATIC, 'openui/chunks');
  assert.deepEqual(fs.readdirSync(chunkDir).filter(f => fs.readFileSync(path.join(chunkDir, f), 'utf8').includes('openui.js')), []);

  const { page, state } = await islandPage(t);
  await page.evaluate(() => { window.__api = window.AI365_OpenUI; });
  await render(page, [
    `src1 = {title: "보안규정.pdf p.3", sourceName: "지식 관리 › 보안", url: ${JSON.stringify(KN1)}}`,
    'root = Card([body, d, btns], [src1])',
    'body = TextContent("흐름은 아래와 같습니다 [1].")',
    'd = MermaidDiagram("flowchart TD\\n  A[신청] --> B[승인]", "흐름")',
    'btns = Buttons([IconButton("문서 보기", Icon("rocket", "travel"), @OpenUrl("ai365://kn/flow.pdf?page=2"), "secondary")])',
  ].join('\n'));
  await page.waitForSelector('#host .mermaid-svg svg', { timeout: 30000 });       // 지연 청크: mermaid / lazy chunk: mermaid
  await page.waitForSelector('#host svg.lucide-rocket');                          // 지연 청크: 이름으로 고른 아이콘 / lazy chunk: a named icon
  await page.click('#host svg.lucide-rocket');                                    // 지연 청크가 그린 아이콘 안을 누른다 / click inside it
  await page.click('#host .openui-listed-source-item');
  assert.deepEqual(await events(page), [['link', 'ai365://kn/flow.pdf?page=2', true], ['link', KN1, true]]);
  const out = await page.evaluate(() => ({ same: window.AI365_OpenUI === window.__api, loads: globalThis[Symbol.for('ai365.openui.loads')] }));
  assert.deepEqual(out, { same: true, loads: 1 });                                // 본체 평가 한 번 / the core ran once
  assert.deepEqual(state.requests.filter(p => p.startsWith('/static/openui/openui.js')), [ENTRY]);   // 진입점 한 번 / the entry once
  assert.deepEqual(state.requests.filter(p => /^\/static\/openui\/chunks\/main-/.test(p)), ['/static/openui/chunks/' + main[1]]);
  assert.equal(state.requests.filter(p => /^\/static\/openui\/chunks\/(mermaid\.core|lucideSet)-/.test(p)).length, 2);
  assert.deepEqual(state.consoleErrors, []);                                      // "Invalid hook call" 등 없음 / no invalid hook call
});

test('wrapText output renders its markdown, follow-ups and source strip', async (t) => {
  const { page } = await islandPage(t);
  const program = await page.evaluate(() => window.AI365_OpenUI.wrapText('**안녕하세요** 첫 문단입니다.\n\n두 번째 문단입니다 [1].', [{ title: '안내서', sourceName: '총무 › 안내', url: 'ai365://kn/guide.pdf?page=1' }], ['더 알려줘']));
  await render(page, program);
  const out = await page.evaluate(() => {
    const el = document.getElementById('host');
    return { root: el.classList.contains('ai365-oui'), strong: el.querySelector('.openui-text-content strong')?.textContent,
      paragraphs: el.querySelectorAll('.openui-text-content p').length, text: el.querySelector('.openui-text-content').innerText,
      follow: [...el.querySelectorAll('.openui-follow-up-item')].map(b => b.innerText.trim()), source: el.querySelector('.openui-listed-sources')?.innerText };
  });
  assert.equal(out.root, true);
  assert.equal(out.strong, '안녕하세요');
  assert.equal(out.paragraphs, 2);
  assert.match(out.text, /두 번째 문단입니다/);
  assert.deepEqual(out.follow, ['더 알려줘']);
  assert.match(out.source, /총무 › 안내/);
});

test('Korean internal answer: the source strip, a citation number chip and a markdown link call onLink and never navigate', async (t) => {
  const { page, state } = await islandPage(t);
  await render(page, INTERNAL, { lang: 'ko' });
  const strip = await page.evaluate(() => {
    const s = document.querySelector('#host .openui-listed-sources');
    return s ? { title: s.querySelector('.openui-listed-sources-header__title').textContent, items: [...s.querySelectorAll('.openui-listed-source-item')].map(i => i.innerText.replace(/\s+/g, ' ').trim()) } : null;
  });
  assert.deepEqual(strip, { title: '출처', items: ['인사 › 규정 출장 여비 규정 p.3', '재무 › 지침 경비 처리 지침 p.1'] });
  await shot(page, 'oui_1_internal.png');

  await page.click('#host .openui-listed-source-item >> nth=1');                // 출처 칩 / a source chip
  // 인용 [1] · [2] = 번호 칩(title = 출처 제목). 누르면 말풍선 없이 바로 onLink
  // citations [1] and [2] = number chips (title = the source title); a click goes straight to onLink, with no popover
  assert.deepEqual(await page.$$eval('#host .ai365-oui-cite', cs => cs.map(c => [c.textContent, c.getAttribute('title')])),
    [['1', '출장 여비 규정 p.3'], ['2', '경비 처리 지침 p.1']]);
  await page.click('#host .ai365-oui-cite >> nth=0');
  assert.equal(await page.$('.openui-citation-tooltip, .openui-citation'), null);
  await page.click('#host .openui-text-content a');                             // 마크다운 링크 / markdown link
  const href = await page.$eval('#host .openui-text-content a', a => a.getAttribute('href'));
  assert.equal(href, 'ai365://kn/rule.pdf?page=2');

  assert.deepEqual(await events(page), [['link', KN2, true], ['link', KN1, true], ['link', 'ai365://kn/rule.pdf?page=2', true]]);
  assert.deepEqual(await opened(page), []);
  assert.equal(page.url(), ORIGIN + '/');
  assert.equal(state.navigations, 0);
  assert.deepEqual(state.external, []);                                          // 사내 출처는 파비콘 요청도 없다 / no favicon request
});

test('http sources and links open a new tab with noopener; other schemes are ignored', async (t) => {
  const { page, state } = await islandPage(t);
  await render(page, [
    'src1 = {title: "Example 기사", sourceName: "example.com", url: "https://example.com/a?x=1"}',
    'root = Card([body, btns], [src1])',
    'body = TextContent("웹 결과입니다 [1]. [원문](https://example.com/b) · [메일](mailto:a@b.test) · [스크립트](javascript:alert(1))")',
    'btns = Buttons([Button("열기", @OpenUrl("https://example.com/c"), "secondary"), Button("사내", @OpenUrl("ai365://kn/z.pdf?page=4"), "secondary")])',
  ].join('\n'));
  await page.click('#host .openui-listed-source-item');
  const links = await page.$$('#host .openui-text-content a');
  assert.equal(links.length, 3);
  for (const a of links) await a.click();
  await page.click('#host button >> text=열기');
  await page.click('#host button >> text=사내');
  assert.deepEqual(await opened(page), [
    ['https://example.com/a?x=1', '_blank', 'noopener'],
    ['https://example.com/b', '_blank', 'noopener'],
    ['https://example.com/c', '_blank', 'noopener'],
  ]);
  assert.deepEqual(await events(page), [['link', 'ai365://kn/z.pdf?page=4', true]]);
  assert.equal(state.navigations, 0);
  // http 출처만 구글 파비콘을 묻는다 / only the http source asks Google for a favicon
  assert.deepEqual(state.external, ['https://www.google.com/s2/favicons?sz=128&domain=example.com']);
});

// 사내(kn) · 로컬(local) · 웹 출처가 하나씩 / one internal (kn), one local and one web source
const LOCAL1 = 'ai365://local/hq-agent/doc-7?page=1&title=%EC%A0%95%EB%B3%B4';
const KINDS = [
  `src1 = {title: "보안규정.pdf p.3", sourceName: "지식 관리 › 보안", url: ${JSON.stringify(KN1)}}`,
  `src2 = {title: "정보보안 기본 규정.pdf p.1", sourceName: "본사 지식 에이전트", url: ${JSON.stringify(LOCAL1)}}`,
  'src3 = {title: "Password guidance", sourceName: "example.com", url: "https://example.com/pw"}',
  'root = Card([header, body], [src1, src2, src3])',
  'header = CardHeader("비밀번호 변경 주기", "지식 관리 › 보안 기준")',
  'body = TextContent("비밀번호는 90일마다 바꿉니다 [1]. 본사 시스템도 같은 규칙을 씁니다 [2]. 외부 권고는 다를 수 있습니다 [3].")',
].join('\n');
const FAVICON_URL = 'https://www.google.com/s2/favicons?sz=128&domain=example.com';

// 출처 종류 아이콘은 답 아래 출처 띠 카드에 그대로 있고, 본문 인용은 아이콘 없는 번호 칩이다(2026-10-29)
// The source-kind icons stay on the Sources strip cards under the answer; inline citations are number chips without icons (2026-10-29)
test('source icons: kn and local strip cards get document icons and the web card keeps its favicon; citations are number chips that open their source', async (t) => {
  const { page, state } = await islandPage(t, { favicons: true });
  await render(page, KINDS, { lang: 'ko' });
  // 번호 칩 셋 · 띠 카드의 파비콘이 다 그려질 때까지 / until the three number chips and the strip favicon are drawn
  await page.waitForFunction(() => {
    const img = document.querySelector('#host .openui-listed-source-item img.openui-source-favicon-image');
    return document.querySelectorAll('#host .ai365-oui-cite').length === 3 && !!img && img.complete && img.naturalWidth > 16;
  });
  const KIND_OF = `(node) => {
    const doc = node.querySelector('[data-source-kind]');
    if (doc) return doc.getAttribute('data-source-kind');
    const img = node.querySelector('img.openui-source-favicon-image');
    if (img) return 'favicon:' + img.getAttribute('src');
    return node.querySelector('svg.lucide-globe') ? 'globe' : '?';
  }`;
  const out = await page.evaluate((kindOf) => {
    const kind = eval(kindOf);
    const el = document.getElementById('host');
    return {
      // 칩 = 숫자만(아이콘 · 그림 없음) / a chip is its number only (no icon or image)
      chips: [...el.querySelectorAll('.ai365-oui-cite')].map(c => [c.textContent, c.getAttribute('title'), c.getAttribute('aria-label'), c.getAttribute('role'),
        !c.querySelector('svg, img, [data-source-kind]')]),
      cards: [...el.querySelectorAll('.openui-listed-source-item')].map(c => {
        const logo = c.querySelector('.openui-listed-source-item__logo');
        return [kind(logo), c.getAttribute('title'), getComputedStyle(logo).borderTopColor];
      }),
      tiles: [...el.querySelectorAll('.ai365-oui-doc')].map(d => [d.getAttribute('data-source-kind'), getComputedStyle(d).backgroundColor, d.getAttribute('aria-label'),
        d.querySelector('path').getAttribute('fill'), Math.round(d.getBoundingClientRect().width)]),
    };
  }, KIND_OF);
  assert.deepEqual(out.chips, [
    ['1', '보안규정.pdf p.3', '출처 1: 보안규정.pdf p.3', 'button', true],
    ['2', '정보보안 기본 규정.pdf p.1', '출처 2: 정보보안 기본 규정.pdf p.1', 'button', true],
    ['3', 'Password guidance', '출처 3: Password guidance', 'button', true],
  ]);
  // 로컬 = DS 경고 틴트(2026-10-28 Figma DS: 바탕 #FFF9F5 · 테두리 #FDCFB4 · 아이콘 #BC4B09, adapter 의 '로컬' 배지와 같다)
  // local = the DS warning tint (2026-10-28 Figma DS: ground #FFF9F5, border #FDCFB4, icon #BC4B09, as the adapter's '로컬' badge)
  assert.deepEqual(out.cards, [
    ['kn', '보안규정.pdf p.3', 'rgb(220, 224, 235)'],
    ['local', '정보보안 기본 규정.pdf p.1', 'rgb(253, 207, 180)'],                 // 로컬 배지 테두리(Warning border 1) / the local badge border (Warning border 1)
    ['favicon:' + FAVICON_URL, 'Password guidance', 'rgb(220, 224, 235)'],
  ]);
  assert.deepEqual(out.tiles, [                                                     // 띠 카드 칸을 채운다(20px 칸, 테두리 1px) / fills the 20px slot
    ['kn', 'rgb(242, 246, 255)', '사내 문서', '#4450CE', 18],
    ['local', 'rgb(255, 249, 245)', '로컬 문서', '#BC4B09', 18],
  ]);
  await shot(page, 'oui_4_source_icons.png');

  // 마우스를 올려도 말풍선은 없다(예전 말풍선이 열리던 시간보다 오래 기다린다) / hovering opens no popover (waits longer than the
  // old popover's open delay)
  await page.hover('#host .ai365-oui-cite >> nth=1');
  await page.waitForTimeout(400);
  assert.equal(await page.$('.openui-citation-tooltip, .openui-citation, .ai365-oui-portal'), null);
  // 누르면 그 출처를 바로 연다: 사내 · 로컬 = onLink, 웹 = 새 창(noopener) / a click opens the source directly: internal and
  // local = onLink, web = a new tab (noopener)
  for (let i = 0; i < 3; i++) await page.click(`#host .ai365-oui-cite >> nth=${i}`);
  assert.deepEqual(await events(page), [['link', KN1, true], ['link', LOCAL1, true]]);
  assert.deepEqual(await opened(page), [['https://example.com/pw', '_blank', 'noopener']]);
  assert.equal(state.navigations, 0);

  // 파비콘은 웹 출처(띠 카드)만, 사내 · 로컬 출처는 요청 없음 / favicons for the web source (its strip card) only, none for internal or local ones
  assert.deepEqual([...new Set(state.external)], [FAVICON_URL]);
});

// 2단계 출처(계약 9.3절): 데이터 표 · BI 는 ai365://data/…(누르면 onLink → adapter 가 리소스 센터로), 그룹웨어는 url 이 없다(누를 곳 없음).
// 띠 카드 아이콘은 adapter 의 AI365_RES_ICONS.data(보라 원그래프) · .groupware(파랑 네 칸)와 같은 색 · 모양. 본문 인용은 번호 칩이고,
// 그룹웨어 칩은 열 곳이 없어 단추가 아니다(기본 커서 · 탭 순서 밖).
// Phase 2 sources (contract section 9.3): data tables and BI are ai365://data/… (a click goes to onLink, which the adapter
// routes to the Resource Center); groupware has no url (nothing to open). The strip card icons take the colour and shape of
// the adapter's AI365_RES_ICONS.data (a purple pie) and .groupware (a blue four-square grid). Inline citations are number
// chips; the groupware chip has nothing to open, so it is not a button (default cursor, outside the tab order).
test('source icons: data sources get the purple pie, url-less groupware sources the blue grid; data opens onLink, groupware never navigates or fetches', async (t) => {
  const { page, state } = await islandPage(t);
  const program = [
    `src1 = ${oui(DATA_SRC)}`,
    `src2 = ${oui({ title: '매출 대시보드.pbix', sourceName: '데이터 분석 › 영업 › BI', url: BI_URL })}`,
    `src3 = ${oui({ title: '오늘 일정', sourceName: '그룹웨어 › 캘린더' })}`,
    'root = Card([body], [src1, src2, src3])',
    'body = TextContent("12월 매출이 가장 큽니다 [1]. 대시보드도 같습니다 [2]. 오늘 회의가 있습니다 [3].")',
  ].join('\n');
  await render(page, program, { lang: 'ko' });
  await page.waitForFunction(() => document.querySelectorAll('#host .ai365-oui-cite').length === 3);
  const out = await page.evaluate(() => {
    const el = document.getElementById('host');
    const kind = n => n.querySelector('[data-source-kind]')?.getAttribute('data-source-kind') || (n.querySelector('svg.lucide-globe') ? 'globe' : '?');
    return {
      chips: [...el.querySelectorAll('.ai365-oui-cite')].map(c => [c.textContent, c.getAttribute('title'), c.getAttribute('role'), c.tabIndex, getComputedStyle(c).cursor]),
      cards: [...el.querySelectorAll('.openui-listed-source-item')].map(c => [kind(c), c.getAttribute('title'), c.classList.contains('openui-listed-source-item--has-url')]),
      tiles: [...el.querySelectorAll('.ai365-oui-doc')].map(d => {
        const g = d.querySelector('g');
        return [d.getAttribute('data-source-kind'), getComputedStyle(d).backgroundColor, d.getAttribute('aria-label'), g.getAttribute('fill'), g.getAttribute('stroke')];
      }),
    };
  });
  assert.deepEqual(out.chips, [
    ['1', '월별 매출', 'button', 0, 'pointer'],
    ['2', '매출 대시보드.pbix', 'button', 0, 'pointer'],
    ['3', '오늘 일정', 'img', -1, 'default'],                                      // 그룹웨어: 열 곳이 없다 / groupware: nothing to open
  ]);
  assert.deepEqual(out.cards, [['data', '월별 매출', true], ['data', '매출 대시보드.pbix', true], ['gw', '오늘 일정', false]]);
  assert.deepEqual(out.tiles, [
    ['data', 'rgb(242, 233, 254)', '데이터 분석', '#8B43E6', null],
    ['data', 'rgb(242, 233, 254)', '데이터 분석', '#8B43E6', null],
    ['gw', 'rgb(230, 240, 255)', '그룹웨어', 'none', '#3B6FE0'],
  ]);
  await shot(page, 'oui_6_source_icons_data_gw.png');

  // 번호 칩: 데이터 · BI 는 onLink, 그룹웨어 칩은 아무 일도 없다 / number chips: data and BI call onLink, the groupware chip does nothing
  for (let i = 0; i < 3; i++) await page.click(`#host .ai365-oui-cite >> nth=${i}`);
  // 출처 띠 카드: 데이터 · BI 는 onLink, 그룹웨어는 그대로 / strip cards: data and BI call onLink, groupware stays put
  for (let i = 0; i < 3; i++) await page.click(`#host .openui-listed-source-item >> nth=${i}`);
  assert.deepEqual(await events(page), [['link', DATA_URL, true], ['link', BI_URL, true], ['link', DATA_URL, true], ['link', BI_URL, true]]);
  assert.deepEqual(await opened(page), []);
  assert.equal(state.navigations, 0);
  assert.deepEqual(state.external, []);                                          // 파비콘 요청 없음 / no favicon request

  // 영어 화면: 타일 이름 · 칩 이름 / English: the tiles' and the chips' names
  await render(page, program, { lang: 'en' });
  assert.deepEqual(await page.$$eval('#host .ai365-oui-doc', ds => ds.map(d => d.getAttribute('aria-label'))), ['Data analysis', 'Data analysis', 'Groupware']);
  assert.deepEqual(await page.$$eval('#host .ai365-oui-cite', cs => cs.map(c => c.getAttribute('aria-label'))),
    ['Source 1: 월별 매출', 'Source 2: 매출 대시보드.pbix', 'Source 3: 오늘 일정']);
});

// 한중일 친화 강조(src/vendor/cjkEmphasis.ts): CommonMark 은 닫는 ** 앞이 문장 부호 · 뒤가 글자(조사)면 닫지 못해 별표가 남는다.
// 모든 마크다운 자리(TextContent · MarkDownRenderer · Callout · TextCallout · 단계 설명 · 목록 부제 · EntityList · InlineHeader ·
// 장소 설명 · 마크다운 대체)에서 굵게 그린다. _ 강조와 코드는 CommonMark 그대로.
// CJK-friendly emphasis (src/vendor/cjkEmphasis.ts): CommonMark cannot close a ** preceded by punctuation and followed by
// a letter (a particle), leaving the asterisks. Every markdown surface draws it bold; _ emphasis and code stay CommonMark.
test('Korean bold on every markdown surface: **55%**로, **(주)엠클라우드**는, **3분기**에, **"따옴표"**를; __x__ and code spans unchanged', async (t) => {
  const { page } = await islandPage(t);
  const body = '이익률이 **55%**로 올랐고 목표 **105%**를 넘었습니다. **(주)엠클라우드**는 고객사**(주)엠클라우드**와 **3분기**에 **"따옴표"**를 썼습니다. ' +
    '__x__ 는 그대로, a__b__c 도, `**55%**로` 코드도.';
  await render(page, [
    'root = Card([t, md, co, tco, st, lb, el, ih, pl])',
    `t = TextContent(${JSON.stringify(body)})`,
    'md = MarkDownRenderer("마크다운 **55%**로 증가")',
    'co = Callout("warning", "참고", "예산이 **105%**를 넘었습니다.")',
    'tco = TextCallout("info", "안내", "목표는 **55%**로 잡았습니다.")',
    'st = Steps([StepsItem("검토", "**(주)엠클라우드**는 먼저 검토합니다.")])',
    'lb = ListBlock([ListItem("일정", "**3분기**에 끝납니다.")])',
    'el = EntityList([{left: "증가율", right: "**55%**로"}])',
    'ih = InlineHeader("머리", "설명 **\\"따옴표\\"**를 씁니다")',
    'pl = PlaceList([PlaceCard("본사", "매출 **105%**를 넘은 곳")])',
  ].join('\n'), { lang: 'ko' });
  const out = await page.evaluate(() => {
    const el = document.getElementById('host');
    const pick = sel => { const n = el.querySelector(sel); return { strong: [...n.querySelectorAll('strong')].map(s => s.textContent), stars: n.innerText.includes('**') }; };
    const text = el.querySelector('.openui-text-content');
    return {
      text: { strong: [...text.querySelectorAll('strong')].map(s => s.textContent), code: [...text.querySelectorAll('code')].map(c => c.textContent),
        plain: text.innerText.replace(/\s+/g, ' ') },
      md: pick('.openui-markdown-renderer:not(.openui-text-content-markdown)'),
      callout: pick('.openui-callout-description'),
      textCallout: pick('.openui-text-callout-content-description'),
      step: pick('.openui-step-details'),
      subtitle: pick('.openui-list-item-subtitle'),
      entity: pick('.openui-entity-list'),
      inlineHeader: pick('.openui-inline-header'),
      place: pick('.place-card'),
    };
  });
  assert.deepEqual(out.text.strong, ['55%', '105%', '(주)엠클라우드', '(주)엠클라우드', '3분기', '"따옴표"', 'x']);
  assert.deepEqual(out.text.code, ['**55%**로']);                                 // 코드 안은 그대로 / code untouched
  assert.match(out.text.plain, / a__b__c 도/);                                     // 단어 안 _ 는 강조가 아니다 / intraword _ stays text
  assert.doesNotMatch(out.text.plain.replace('**55%**로', ''), /\*\*/);
  assert.deepEqual(out.md, { strong: ['55%'], stars: false });
  assert.deepEqual(out.callout, { strong: ['105%'], stars: false });
  assert.deepEqual(out.textCallout, { strong: ['55%'], stars: false });           // 맨 글자였다 → 인라인 마크다운 / was plain text
  assert.deepEqual(out.step, { strong: ['(주)엠클라우드'], stars: false });
  assert.deepEqual(out.subtitle, { strong: ['3분기'], stars: false });
  assert.deepEqual(out.entity, { strong: ['55%'], stars: false });
  assert.deepEqual(out.inlineHeader, { strong: ['"따옴표"'], stars: false });
  assert.deepEqual(out.place, { strong: ['105%'], stars: false });
  // 프로그램이 아닌 글(마크다운 대체)도 / non-program text (the markdown fallback) too
  await render(page, '목표 **105%**를 넘었고 **(주)엠클라우드**는 만족했습니다.', { streaming: false });
  assert.deepEqual(await page.$$eval('#host .ai365-oui-md strong', ns => ns.map(n => n.textContent)), ['105%', '(주)엠클라우드']);
  assert.deepEqual(await events(page), []);
});

// TextContent 밖의 [n]: Callout · TextCallout 설명, StepsItem 설명, ListItem 부제도 TextContent 와 같은 인용 번호 칩(루트 Card 의
// 출처 · 누르면 onLink). 누르면 질문을 보내는 목록 줄은 칩을 둘 수 없어(칩을 누르면 줄 동작까지 불린다) [n] 을 지운다.
// [n] outside TextContent: Callout and TextCallout descriptions, StepsItem details and ListItem subtitles get the same
// citation number chips as TextContent (the root Card's sources; a click calls onLink). A list row that sends a question
// cannot host a chip (clicking it would fire the row's action too), so its [n] is dropped.
test('[n] citations become chips in Callout and TextCallout descriptions, StepsItem details and ListItem subtitles; a clickable list row drops them', async (t) => {
  const { page } = await islandPage(t);
  await render(page, [
    `src1 = {title: "보안규정.pdf p.3", sourceName: "지식 관리 › 보안", url: ${JSON.stringify(KN1)}}`,
    `src2 = ${oui(DATA_SRC)}`,
    'root = Card([co, tco, st, lb, act], [src1, src2])',
    'co = Callout("warning", "참고사항", "재검토가 필요합니다 [1].")',
    'tco = TextCallout("info", "안내", "목표치를 잡았습니다 [2].")',
    'st = Steps([StepsItem("검토", "먼저 검토합니다 [1]."), StepsItem("승인", "팀장이 승인합니다 [2][1]")])',
    'lb = ListBlock([ListItem("일정", "부제에 인용이 있습니다 [2].")])',
    'act = ListBlock([ListItem("누르는 줄", "부제의 인용은 지웁니다 [1].", null, @ToAssistant("누르는 줄 자세히"))])',
  ].join('\n'), { lang: 'ko' });
  const out = await page.evaluate(() => {
    const el = document.getElementById('host');
    // 글 = 칩 자리를 "^n" 으로 보인 글(구두점 뒤 · 앞 공백 없음), 칩 = 묶음마다 번호 / the text shows the chips as "^n" (after the
    // punctuation, no space before); the chips are listed per group by number
    const at = n => ({ text: window.__inline(n).replace(/\s+/g, ' ').trim(),
      chips: [...n.querySelectorAll('.ai365-oui-cites')].map(g => [...g.children].map(c => c.textContent)) });
    const subtitles = [...el.querySelectorAll('.openui-list-item-subtitle')];
    return {
      callout: at(el.querySelector('.openui-callout-description')),
      textCallout: at(el.querySelector('.openui-text-callout-content-description')),
      steps: [...el.querySelectorAll('.openui-step-details')].map(at),
      subtitle: at(subtitles[0]),
      clickable: at(subtitles[1]),
    };
  });
  assert.deepEqual(out.callout, { text: '재검토가 필요합니다.^1', chips: [['1']] });
  assert.deepEqual(out.textCallout, { text: '목표치를 잡았습니다.^2', chips: [['2']] });
  assert.deepEqual(out.steps, [{ text: '먼저 검토합니다.^1', chips: [['1']] }, { text: '팀장이 승인합니다^2^1', chips: [['2', '1']] }]);   // [2][1] = 칩 둘 / two chips
  assert.deepEqual(out.subtitle, { text: '부제에 인용이 있습니다.^2', chips: [['2']] });
  assert.deepEqual(out.clickable, { text: '부제의 인용은 지웁니다.', chips: [] });  // 누르는 줄: [n] 없이 / clickable row: no [n]
  await shot(page, 'oui_10_citations_outside_text.png');

  // 칩 → 그 출처로 바로 onLink(말풍선 없음), 단계의 [2][1] 은 칩마다 자기 출처 / a chip → onLink of its source directly (no
  // popover); each chip of the step's [2][1] opens its own source
  await page.click('#host .openui-callout-description .ai365-oui-cite');
  assert.equal(await page.$('.openui-citation-tooltip, .openui-citation'), null);
  await page.locator('#host .openui-step-details').nth(1).locator('.ai365-oui-cite').nth(0).click();
  await page.locator('#host .openui-step-details').nth(1).locator('.ai365-oui-cite').nth(1).click();
  // 누르는 줄은 질문만 보낸다 / the clickable row only sends its question
  await page.click('#host .openui-list-item-clickable');
  assert.deepEqual(await events(page), [['link', KN1, true], ['link', DATA_URL, true], ['link', KN1, true],
    ['action', { type: 'continue_conversation', text: '누르는 줄 자세히' }]]);
});

// 본문 인용 [n] = 번호 칩(2026-10-29, OpenUI 이전 채팅 각주 static/adapter.js .ai365-fn 과 같은 모양 · 동작). 번호는 모델이 쓴 [n]
// 그대로 = 루트 Card 출처 목록의 n 번째 = 출처 띠의 n 번째 카드(나온 순서가 아니다). 붙은 인용은 칩을 나란히, 한 묶음 안의 같은
// 번호는 한 번, 목록에 없는 번호는 그리지 않는다. title = 출처 제목(url 의 쪽은 제목에 없을 때만 " p.N"), 제목 없는 웹 출처는 도메인.
// 마우스를 올려도 말풍선은 없고, 누르면(Enter · Space 도) 그 출처를 바로 연다. url 이 없는 그룹웨어 칩은 단추가 아니라 탭 순서에서
// 빠진다. 띠 카드는 종류 아이콘 그대로.
// Inline [n] = number chips (2026-10-29, the look and behaviour of the pre-OpenUI chat footnotes, .ai365-fn in static/adapter.js).
// The number is the model's [n] as written = the nth source of the root Card = the nth card of the Sources strip (not the order
// of appearance). Adjacent citations sit side by side, a number repeated in one group shows once, and a number without a source
// draws nothing. The title is the source title (the url's page as " p.N" only when the title lacks it); a web source without a
// title shows its domain. Hovering opens no popover; a click (Enter and Space too) opens the source directly. The url-less
// groupware chip is not a button and is left out of the tab order. Strip cards keep their kind icons.
const CITES = [
  `src1 = {title: "보안규정.pdf", sourceName: "지식 관리 › 보안", url: ${JSON.stringify(KN1)}}`,     // 제목에 쪽이 없다 / no page in the title
  `src2 = {title: "경비 처리 지침 p.1", sourceName: "재무 › 지침", url: ${JSON.stringify(KN2)}}`,
  'src3 = {title: "", sourceName: "example.com", url: "https://www.example.com/a"}',              // 제목 없는 웹 / a titleless web source
  `src4 = ${oui(GW_SRC)}`,
  'root = Card([body, co], [src1, src2, src3, src4])',
  'body = TextContent("먼저 둘째 문서 [2], 다음 첫째 [1][2]. 같은 번호 [3][3], 없는 번호 [9], 그룹웨어 [4].")',
  'co = Callout("info", "참고", "콜아웃 인용 [1].")',
].join('\n');

test('citation number chips: the written [n] (source list position = strip order), adjacent chips, titles, the .ai365-fn look, click and keyboard open the source, no popover, groupware is not a button', async (t) => {
  const { page, state } = await islandPage(t);
  await render(page, CITES, { lang: 'ko' });
  // 웹 띠 카드: 파비콘 요청이 404 라 지구 아이콘이 될 때까지 / the web strip card: until the 404 favicon turns into the globe
  await page.waitForSelector('#host .openui-listed-source-item svg.lucide-globe');
  const out = await page.evaluate(() => {
    const el = document.getElementById('host');
    const body = el.querySelector('.openui-text-content');
    return {
      groups: [...body.querySelectorAll('.ai365-oui-cites')].map(g => [...g.children].map(c => c.tagName + ':' + c.textContent)),
      chips: [...body.querySelectorAll('.ai365-oui-cite')].map(c => [c.textContent, c.getAttribute('title'), c.getAttribute('aria-label'), c.getAttribute('role'), c.tabIndex]),
      text: window.__inline(body).replace(/\s+/g, ' ').trim(),
      strip: [...el.querySelectorAll('.openui-listed-source-item')].map(c => c.querySelector('[data-source-kind]')?.getAttribute('data-source-kind') || (c.querySelector('svg.lucide-globe') ? 'globe' : '?')),
    };
  });
  assert.deepEqual(out.groups, [['SUP:2'], ['SUP:1', 'SUP:2'], ['SUP:3'], ['SUP:4']]);       // [9] 는 칩이 없다 / [9] gets none
  assert.deepEqual(out.chips, [
    ['2', '경비 처리 지침 p.1', '출처 2: 경비 처리 지침 p.1', 'button', 0],
    ['1', '보안규정.pdf p.3', '출처 1: 보안규정.pdf p.3', 'button', 0],             // url 의 쪽을 붙인다 / the url's page is added
    ['2', '경비 처리 지침 p.1', '출처 2: 경비 처리 지침 p.1', 'button', 0],           // 이미 있으면 그대로 / kept as is when present
    ['3', 'www.example.com', '출처 3: www.example.com', 'button', 0],                // 제목 없는 웹 = 도메인 / titleless web = domain
    ['4', '받은편지함', '출처 4: 받은편지함', 'img', -1],                               // 그룹웨어: 단추 아님 / groupware: not a button
  ]);
  // 칩은 구두점 뒤에 바로, [9] 는 글자도 칩도 없다 / chips right after the punctuation; [9] leaves neither text nor a chip
  assert.equal(out.text, '먼저 둘째 문서,^2 다음 첫째.^1^2 같은 번호,^3 없는 번호, 그룹웨어.^4');
  assert.deepEqual(out.strip, ['kn', 'kn', 'globe', 'gw']);                          // 띠 카드 아이콘은 그대로 / strip icons unchanged
  await shot(page, 'oui_11_citation_numbers.png');

  // 모양 = .ai365-fn 값(10px · 700 · #4450CE · #F2F6FF · 모서리 4 · 좌우 4 · 왼쪽 2 · 위첨자 · 줄 1.4), hover #E4EDFF; 그룹웨어는 기본 커서 · hover 없음
  // the look = the .ai365-fn values, hover #E4EDFF; the groupware chip keeps the default cursor and no hover
  const look = sel => page.$eval(sel, c => {
    const s = getComputedStyle(c);
    return [s.fontSize, s.fontWeight, s.color, s.backgroundColor, s.borderTopLeftRadius, s.paddingTop, s.paddingLeft, s.paddingRight, s.marginLeft,
      s.verticalAlign, s.lineHeight, s.cursor];
  });
  const ONE = '#host .openui-text-content .ai365-oui-cite[data-citation="1"]';
  const GW = '#host .ai365-oui-cite[data-citation="4"]';
  assert.deepEqual(await look(ONE), ['10px', '700', 'rgb(68, 80, 206)', 'rgb(242, 246, 255)', '4px', '0px', '4px', '4px', '2px', 'super', '14px', 'pointer']);
  await page.hover(ONE);
  await page.waitForTimeout(400);                                                  // 예전 말풍선이 열리던 시간보다 길게 / longer than the old popover delay
  assert.equal((await look(ONE))[3], 'rgb(228, 237, 255)');
  assert.equal(await page.$('.openui-citation-tooltip, .openui-citation, .ai365-oui-portal'), null);   // 말풍선 없음 / no popover
  await page.hover(GW);
  assert.deepEqual((await look(GW)).filter((_, i) => i === 3 || i === 11), ['rgb(242, 246, 255)', 'default']);

  // 누르면 바로 연다: 사내 = onLink, 웹 = 새 창(noopener), 그룹웨어 = 아무 일 없음 / a click opens directly: internal = onLink,
  // web = a new tab (noopener), groupware = nothing
  const group = page.locator('#host .openui-text-content .ai365-oui-cites');
  await group.nth(1).locator('.ai365-oui-cite').nth(1).click();                     // "1 2" 의 2 / the 2 of "1 2"
  await group.nth(1).locator('.ai365-oui-cite').nth(0).click();                     // "1 2" 의 1 / the 1 of "1 2"
  await page.click('#host .ai365-oui-cite[data-citation="3"]');
  await page.click(GW);
  // 키보드: Tab 으로 닿고(그룹웨어 칩은 건너뛴다) Enter · Space 로 연다 / keyboard: reached with Tab (skipping the groupware chip),
  // opened with Enter and Space
  await page.focus('#host .ai365-oui-cite[data-citation="3"]');
  await page.keyboard.press('Tab');
  assert.deepEqual(await page.evaluate(() => { const a = document.activeElement; return [a.className, a.textContent, !!a.closest('.openui-callout')]; }),
    ['ai365-oui-cite', '1', true]);
  await page.keyboard.press('Enter');
  await page.focus('#host .openui-text-content .ai365-oui-cite >> nth=0');
  await page.keyboard.press('Space');
  assert.deepEqual(await events(page), [['link', KN2, true], ['link', KN1, true], ['link', KN1, true], ['link', KN2, true]]);
  assert.deepEqual(await opened(page), [['https://www.example.com/a', '_blank', 'noopener']]);
  assert.equal(state.navigations, 0);

  // 영어 화면: 칩 이름 "Source n: 제목"(title 은 같은 출처 제목) / English: chip names "Source n: title" (the same titles)
  await render(page, CITES, { lang: 'en' });
  assert.deepEqual(await page.$$eval('#host .openui-text-content .ai365-oui-cite', cs => cs.map(c => [c.getAttribute('aria-label'), c.getAttribute('title')])), [
    ['Source 2: 경비 처리 지침 p.1', '경비 처리 지침 p.1'],
    ['Source 1: 보안규정.pdf p.3', '보안규정.pdf p.3'],
    ['Source 2: 경비 처리 지침 p.1', '경비 처리 지침 p.1'],
    ['Source 3: www.example.com', 'www.example.com'],
    ['Source 4: 받은편지함', '받은편지함'],
  ]);
});

// 인용 칩 자리(2026-10-29, src/vendor/citationPlacement.ts): 예전 각주(adapter ai365CiteMd)처럼 문장 끝 구두점 뒤에 바로 붙는다.
// 앞 공백 · 탭은 지우고(줄바꿈은 아님), 바로 뒤의 . , ! ? 。 는 칩 앞으로 옮긴다. 숫자 · 소수 바로 뒤, 코드 안, 링크 글, 줄 첫머리는
// 그대로이고, 칩 뒤의 띄어쓰기는 남는다(remarkCitations 정규식 빌드 패치). 쉼표(, ， 、)로만 이은 나열 "[1], [2], [3]" 은 같은 패치로
// 한 묶음이라 "문서¹²³에" 가 되고, 뒤에 [n] 이 없는 쉼표("문서 [1], 그리고")는 구두점처럼 칩 앞으로 간다.
// Citation chip placement (2026-10-29, src/vendor/citationPlacement.ts): right after the sentence punctuation, like the old
// footnotes (ai365CiteMd in the adapter). Spaces and tabs before are removed (not line breaks) and a . , ! ? 。 right after
// moves before the chip. Right after a number or decimal, inside code, in link text and at the start of a line nothing
// changes, and the space after a chip stays (the remarkCitations regex build patch). A list joined only by commas (, ， 、),
// "[1], [2], [3]", is one group through the same patch and becomes "문서¹²³에"; a comma with no [n] after it ("문서 [1], 그리고")
// moves in front like other punctuation.
test('citation placement: no space before a chip, the punctuation after it moves in front, comma lists are one group, numbers, code, link text and line starts stay', async (t) => {
  const { page } = await islandPage(t);
  const q = s => JSON.stringify(s);
  await render(page, [
    `src1 = {title: "보안규정.pdf p.3", sourceName: "지식 관리 › 보안", url: ${q(KN1)}}`,
    `src2 = {title: "경비 처리 지침 p.1", sourceName: "재무 › 지침", url: ${q(KN2)}}`,
    `src3 = {title: "정보보안 기본 규정.pdf p.1", sourceName: "본사 지식 에이전트", url: ${q(LOCAL1)}}`,
    'root = Card([a, b, c, d, e, f], [src1, src2, src3])',
    `a = TextContent(${q('비밀번호는 **90일마다** 바꿉니다 [1]. 알림은 메일로 보냅니다 [1][2]. 정말인가요 [2]?! 그리고 [1] 다음 문장, 규정[2]에 따라 **처리** [1].')})`,
    `b = TextContent(${q('값은 3.5 [1] 이고 버전 v2.0[2] 입니다. 합계 700.75 [1].')})`,
    `c = TextContent(${q('코드 `안내 [1].` 는 그대로, [원문 보기 [2]](https://example.com/b) 도 그대로.')})`,
    `d = TextContent(${q('첫 줄입니다\n[1]. 둘째 줄입니다 [2].')})`,
    `e = Callout("info", "참고", ${q('탭 앞\t[1].')})`,
    // 쉼표(, ， 、)로만 이은 나열 = 한 묶음, 뒤에 [n] 이 없는 쉼표는 구두점 / a list joined only by commas = one group; a comma
    // with no [n] after it is punctuation
    `f = TextContent(${q('제공된 사내 문서 [1], [2], [3]에 직접 명시되어 있지 않습니다. 규정입니다 [1],[2]. 문서 [1]、[2] 참고, 자료 [2]，[3]。 문서 [1], 그리고 다음 문서 [1], [2], 그리고 끝.')})`,
  ].join('\n'), { lang: 'ko' });
  const out = await page.evaluate(() => {
    const el = document.getElementById('host');
    const line = n => window.__inline(n).replace(/[ \t]+/g, ' ').replace(/\s*\n\s*/g, '\n').trim();
    const texts = [...el.querySelectorAll('.openui-text-content')].map(line);
    return {
      texts,
      callout: line(el.querySelector('.openui-callout-description')),
      code: el.querySelector('.openui-text-content code')?.textContent,
      linkChip: !!el.querySelector('.openui-text-content a .ai365-oui-cite'),
      listGroups: [...[...el.querySelectorAll('.openui-text-content')][4].querySelectorAll('.ai365-oui-cites')].map(g => [...g.children].map(c => c.textContent)),
    };
  });
  assert.deepEqual(out.texts, [
    // 앞 공백 없음 · 구두점 뒤 · 칩 뒤 띄어쓰기 유지 · 조사는 붙은 그대로 · 굵게 뒤에도 / no space before, after the punctuation,
    // the space after kept, a particle stays attached, after bold too
    '비밀번호는 90일마다 바꿉니다.^1 알림은 메일로 보냅니다.^1^2 정말인가요?!^2 그리고^1 다음 문장, 규정^2에 따라 처리.^1',
    '값은 3.5 ^1 이고 버전 v2.0^2 입니다. 합계 700.75 ^1.',                       // 숫자 · 소수 바로 뒤는 그대로 / numbers stay
    '코드 안내 [1]. 는 그대로, 원문 보기 ^2 도 그대로.',                            // 코드 · 링크 글은 그대로 / code and link text stay
    '첫 줄입니다\n^1. 둘째 줄입니다.^2',                                            // 줄 첫머리는 그대로 / a line start stays
    // 쉼표 나열은 구분 쉼표 없이 칩 나란히, 단일 인용 뒤 쉼표는 칩 앞으로 / comma lists become side-by-side chips without their
    // commas; a comma after a single citation moves in front of it
    '제공된 사내 문서^1^2^3에 직접 명시되어 있지 않습니다. 규정입니다.^1^2 문서^1^2 참고, 자료。^2^3 문서,^1 그리고 다음 문서,^1^2 그리고 끝.',
  ]);
  assert.deepEqual(out.listGroups, [['1', '2', '3'], ['1', '2'], ['1', '2'], ['2', '3'], ['1'], ['1', '2']]);   // 나열마다 한 묶음 / one group per list
  assert.equal(out.callout, '탭 앞.^1');                                          // 탭도 지운다 / a tab goes too
  assert.equal(out.code, '안내 [1].');
  assert.equal(out.linkChip, true);
});

test('a follow-up click sends continue_conversation with its text', async (t) => {
  const { page } = await islandPage(t);
  await render(page, INTERNAL);
  await page.click('#host .openui-follow-up-item >> nth=1');
  assert.deepEqual(await events(page), [['action', { type: 'continue_conversation', text: '정산서 양식은 어디 있어?' }]]);
});

test('a form validates in Korean, its select list is a styled portal, and submit sends the form answers', async (t) => {
  const { page } = await islandPage(t);
  await render(page, FORM, { lang: 'ko' });
  await page.click('#host button >> text=계획 세워 줘');
  assert.equal(await page.$eval('#host .openui-hint-error', n => n.textContent.trim()), '필수 항목입니다');
  assert.deepEqual(await events(page), []);                                      // 검증 실패 = 보내지 않음 / not sent
  await page.fill('#host input[name=destination]', '부산');
  await page.click('#host .openui-select-trigger');
  const list = await page.waitForSelector('.openui-select-content');
  const listInfo = await list.evaluate(n => ({ portal: n.classList.contains('ai365-oui-portal'), inIsland: !!n.closest('#host'), bg: getComputedStyle(n).backgroundColor !== 'rgba(0, 0, 0, 0)', radius: getComputedStyle(n).borderTopLeftRadius }));
  assert.deepEqual(listInfo, { portal: true, inIsland: false, bg: true, radius: '8px' });   // DS 목록 모서리 8(2026-10-28) / the DS listbox radius 8
  await page.click('.openui-select-content [role=option] >> text=2명');
  await page.click('#host button >> text=계획 세워 줘');
  assert.deepEqual(await events(page), [['action', { type: 'continue_conversation', text: '출장 계획을 세워 줘\n\n입력한 내용:\n- destination: 부산\n- people: 2' }]]);
});

test('labels follow opts.lang: English labels and messages with lang "en"', async (t) => {
  const { page } = await islandPage(t);
  await render(page, INTERNAL + '\n', { lang: 'en' });
  const en = await page.evaluate(() => ({ sources: document.querySelector('#host .openui-listed-sources-header__title').textContent,
    related: document.querySelector('#host .openui-follow-up-block__header').textContent, lang: document.querySelector('#host .ai365-oui-root').getAttribute('lang'),
    cites: [...document.querySelectorAll('#host .ai365-oui-cite')].map(c => c.getAttribute('aria-label')) }));
  assert.deepEqual(en, { sources: 'Sources', related: 'Related Queries', lang: 'en', cites: ['Source 1: 출장 여비 규정 p.3', 'Source 2: 경비 처리 지침 p.1'] });
  await render(page, FORM, { lang: 'en' });
  await page.click('#host button >> text=계획 세워 줘');
  assert.equal(await page.$eval('#host .openui-hint-error', n => n.textContent.trim()), 'This field is required');
  await page.fill('#host input[name=destination]', 'Busan');
  await page.click('#host button >> text=계획 세워 줘');
  assert.deepEqual(await events(page), [['action', { type: 'continue_conversation', text: '출장 계획을 세워 줘\n\nForm answers:\n- destination: Busan' }]]);
  await render(page, INTERNAL, { lang: 'ko' });
  const ko = await page.evaluate(() => [document.querySelector('#host .openui-listed-sources-header__title').textContent, document.querySelector('#host .openui-follow-up-block__header').textContent,
    [...document.querySelectorAll('#host .ai365-oui-cite')].map(c => c.getAttribute('aria-label'))]);
  assert.deepEqual(ko, ['출처', '관련 질문', ['출처 1: 출장 여비 규정 p.3', '출처 2: 경비 처리 지침 p.1']]);
});

test('a program cut mid-statement renders while streaming without errors, then completes', async (t) => {
  const { page } = await islandPage(t);
  const cut = INTERNAL.indexOf('7일 안에') + 4;                                   // 문자열 한가운데 / inside a string
  const cuts = [40, INTERNAL.indexOf('root ='), INTERNAL.indexOf('header =') + 20, cut, INTERNAL.indexOf('\\', 0) > 0 ? INTERNAL.indexOf('\\') : cut + 10, INTERNAL.length - 30];
  for (const n of cuts) await render(page, INTERNAL.slice(0, n), { streaming: true });
  const mid = await page.evaluate(() => ({ header: document.querySelector('#host .openui-card')?.innerText.includes('국내 출장비 정산 절차') }));
  assert.deepEqual(mid, { header: true });
  await render(page, INTERNAL.slice(0, cut), { streaming: true });
  const partialText = await page.$eval('#host', n => n.innerText);
  assert.match(partialText, /국내 출장비는 출장을 마친 날부터/);
  await render(page, INTERNAL, { streaming: false });
  const done = await page.$eval('#host', n => n.innerText);
  assert.match(done, /숙박비는 실비로 지급합니다/);
  assert.match(done, /정산서 양식은 어디 있어\?/);
  assert.deepEqual(await events(page), []);                                      // 오류 없음 / no errors
});

test('non-program text renders as markdown', async (t) => {
  const { page } = await islandPage(t);
  await render(page, '## 안내\n\n- 첫째 항목\n- 둘째 항목\n\n**굵게** 끝. [사내 문서](ai365://kn/a.pdf?page=1)', { streaming: false });
  const out = await page.evaluate(() => {
    const el = document.getElementById('host');
    return { md: !!el.querySelector('.ai365-oui-md'), items: [...el.querySelectorAll('li')].map(li => li.textContent.trim()), strong: el.querySelector('strong')?.textContent, heading: el.querySelector('h2')?.textContent };
  });
  assert.deepEqual(out, { md: true, items: ['첫째 항목', '둘째 항목'], strong: '굵게', heading: '안내' });
  await page.click('#host a');
  assert.deepEqual(await events(page), [['link', 'ai365://kn/a.pdf?page=1', true]]);
});

test('Table, BarChart and PieChart render', async (t) => {
  const { page } = await islandPage(t);
  await render(page, DATA);
  await page.waitForSelector('#host [data-openui-chart="bar"] svg');
  const out = await page.evaluate(() => {
    const el = document.getElementById('host');
    const rows = [...el.querySelectorAll('.openui-table tr')].map(tr => [...tr.children].map(td => td.innerText.trim()));
    const bar = el.querySelector('[data-openui-chart="bar"]');
    const pie = el.querySelector('.openui-pie-chart-container');
    return { rows, bars: bar.querySelectorAll('svg .openui-bar-chart-bar').length, legend: el.innerText.includes('매출') && el.innerText.includes('비용'),
      pieShapes: pie ? pie.querySelectorAll('svg path').length : -1, pieLegend: el.innerText.includes('60.0%') && el.innerText.includes('40.0%') };
  });
  assert.deepEqual(out.rows, [['부서', '인원', '상태'], ['영업', '12', '증가'], ['개발', '30', '유지'], ['인사', '5', '감소']]);
  assert.equal(out.bars, 6);                                                      // 2 계열 × 3 분기 / 2 series × 3 quarters
  assert.equal(out.legend, true);
  assert.ok(out.pieShapes >= 2, `pie shapes ${out.pieShapes}`);
  assert.equal(out.pieLegend, true);
  await shot(page, 'oui_2_data.png');
});

// 2단계 데이터 답(계약 9.2 · 9.4절): 표 · 차트 · Stat · Callout · 글의 숫자가 서버 데이터 문장을 참조한다. 쓰지 않은 문장(gw1 · src2)과
// 빈 칸(null)은 오류가 아니다. "number" 열은 오른쪽 정렬, 1만 이상이 있으면 천 단위 쉼표(연도처럼 네 자리뿐인 열은 그대로).
// Phase 2 data answers (contract sections 9.2 and 9.4): the numbers of tables, charts, stats, callouts and text refer to
// the server's data statements. Unreferenced statements (gw1, src2) and empty cells (null) are no errors. "number"
// columns align right and get thousands separators when they hold 10,000 or more (four-digit columns such as years stay).
test('data answers: Table, charts, StatStrip, Callout and text bind to d1, d1top and d1sum; streaming with the server prefix; number columns', async (t) => {
  const { page } = await islandPage(t);
  const program = PREFIX + '\n' + DATA_ANSWER;
  // 서버 문장만 온 동안은 빈 화면, 식 한가운데서 잘려도 오류 없음 / blank while only the server statements are in; cuts mid-expression are fine
  await render(page, PREFIX, { streaming: true });
  assert.equal(await page.$eval('#host', n => n.innerText.trim()), '');
  for (let n = PREFIX.length + 1; n < program.length; n += 37) await render(page, program.slice(0, n), { streaming: true });
  await render(page, program, { streaming: false, lang: 'ko' });
  await page.waitForSelector('#host [data-openui-chart="bar"] svg');
  await page.waitForSelector('#host [data-openui-chart="line"] svg');
  const out = await page.evaluate(() => {
    const el = document.getElementById('host');
    const flat = s => s.replace(/\s+/g, ' ').trim();
    return {
      summary: flat(window.__inline(el.querySelector('.openui-text-content'))),
      stats: [...el.querySelectorAll('.stat')].map(s => flat(s.innerText)),
      bars: el.querySelectorAll('[data-openui-chart="bar"] svg .openui-bar-chart-bar').length,
      barTicks: [...el.querySelectorAll('[data-openui-chart="bar"] svg text')].map(x => x.textContent).filter(x => /월$/.test(x)).length,
      lineLegend: [...el.querySelectorAll('[data-openui-chart="line"] .openui-chart-legend-item-label')].map(x => x.textContent),
      yLabel: el.querySelector('[data-openui-chart="line"] .openui-cartesian-y-axis-label')?.textContent,
      rows: [...el.querySelectorAll('.openui-table tr')].map(tr => [...tr.children].map(td => td.innerText.trim())),
      heads: [...el.querySelectorAll('.openui-table thead .openui-table-head-content')].map(h => h.classList.contains('openui-table-align-right')),
      cells: [...el.querySelectorAll('.openui-table tbody tr:first-child td')].map(td => getComputedStyle(td).textAlign + ' ' + getComputedStyle(td).fontVariantNumeric),
      callout: flat(el.querySelector('.openui-callout')?.innerText ?? ''),
      source: flat(el.querySelector('.openui-listed-source-item')?.innerText ?? ''),
    };
  });
  assert.equal(out.summary, '12개월 매출 합계는 700.75억 원이고 최고는 80억 원입니다.^1 1월은 42.5억 원입니다.');   // [1] = 마침표 뒤 번호 칩 / the chip right after the period
  assert.deepEqual(out.stats, ['700.75억 매출 합계 88.2%', '700.75억 합계(@Sum)', '58.4 월평균(@Round · @Avg)', '📦 +66.7% 주문 변화']);
  assert.deepEqual([out.bars, out.barTicks], [12, 12]);                           // d1 = 12행 / twelve rows
  assert.deepEqual(out.lineLegend, ['매출액', '주문 건수']);                        // null 이 든 계열도 / the series with a null too
  assert.equal(out.yLabel, '억 원 · 건');
  assert.deepEqual(out.rows, [['월', '매출액(억 원)', '주문 건수', '매출액(원)'],
    ...D_ROWS.slice(0, 10).map(r => [r.c1, String(r.c2), r.c3 === null ? '' : String(r.c3), r.c4.toLocaleString('en-US')])]);
  assert.equal(out.rows[2][3], '3,810,000,000');                                 // 1만 이상 열 = 쉼표 / thousands separators
  assert.deepEqual(out.heads, [false, true, true, true]);                         // "number" 열만 오른쪽 / only "number" columns
  assert.deepEqual(out.cells, ['start normal', 'right tabular-nums', 'right tabular-nums', 'right tabular-nums']);
  assert.equal(out.callout, '변동 폭 최저 38.1억 원, 최고 80억 원');
  assert.match(out.source, /데이터 분석 › 영업 › DB/);
  assert.deepEqual(await events(page), []);                                      // 오류 없음 / no errors
  await shot(page, 'oui_7_data_answer.png');

  // 연도처럼 네 자리뿐인 "number" 열 · 소수 열은 그대로, 큰 수가 하나라도 있으면 열 전체에 쉼표(음수 · 소수 둘째 자리)
  // four-digit "number" columns (years) and small decimals stay; one large number puts separators on the whole column
  await render(page, 'd9 = [{y: 2025, v: 1250000, r: 42.5}, {y: 2024, v: 980500.456, r: null}, {y: 2023, v: -12000, r: 7}, {y: 2022, v: 3, r: 0.125}]\n' +
    'root = Card([t])\nt = Table([Col("연도", d9.y, "number"), Col("금액", d9.v, "number"), Col("비율", d9.r, "number"), Col("금액(글)", d9.v)])');
  const mixed = await page.evaluate(() => [...document.querySelectorAll('#host .openui-table tbody tr')].map(tr => [...tr.children].map(td => td.innerText.trim())));
  assert.deepEqual(mixed, [['2025', '1,250,000', '42.5', '1250000'], ['2024', '980,500.46', '', '980500.456'], ['2023', '-12,000', '7', '-12000'], ['2022', '3', '0.125', '3']]);
});

// 내장 함수(@Count · @Sum · @Max · @First · @Last · @Filter · @Sort · @Each · @Round)를 데이터 문장에 쓰면 렌더러가 계산한다.
// The built-ins (@Count, @Sum, @Max, @First, @Last, @Filter, @Sort, @Each, @Round) compute in the renderer over the
// data statements.
test('data answers: built-in functions compute over the data statements (sort, filter, pluck, @Each cells with Tag and ProgressBar)', async (t) => {
  const { page } = await islandPage(t);
  await render(page, PREFIX + '\n' + [
    'root = Card([e, t])',
    'e = EntityList([{left: "Count", right: "" + @Count(d1)}, {left: "Sum", right: "" + @Sum(d1.c3)}, {left: "Max", right: "" + @Max(d1.c2)}, {left: "First", right: @First(d1.c1)}, ' +
      '{left: "Last", right: "" + @Last(d1.c2)}, {left: "Filter", right: "" + @Count(@Filter(d1, "c2", ">", 60))}, {left: "Top", right: @First(@Sort(d1, "c2", "desc")).c1}, ' +
      '{left: "Round", right: "" + @Round(d1sum.c2.avg * 1.1, 2)}, {left: "Raw", right: "" + @Sum(d1.c2)}])',
    'sorted = @Sort(d1top, "c2", "desc")',
    't = Table([Col("월", sorted.c1), Col("매출액", sorted.c2, "number"), Col("상태", @Each(sorted, "r", Tag(r.c2 >= 60 ? "높음" : "보통", null, "sm", r.c2 >= 60 ? "success" : "neutral"))), ' +
      'Col("막대", @Each(sorted, "r", ProgressBar(r.c2, d1sum.c2.max, @FormatNumber(r.c2) + "억")))])',
  ].join('\n'));
  const out = await page.evaluate(() => ({
    text: document.querySelector('#host').innerText,
    rows: [...document.querySelectorAll('#host .openui-table tbody tr')].map(tr => [...tr.children].map(td => td.innerText.replace(/\s+/g, ' ').trim())),
    tags: [...document.querySelectorAll('#host .openui-table tbody .openui-tag')].map(x => x.className.match(/openui-tag-(success|neutral)/)?.[1]),
    bars: [...document.querySelectorAll('#host .progress-cell-bar')].map(b => b.style.width),
  }));
  for (const [k, v] of [['Count', '12'], ['Sum', '1348'], ['Max', '80'], ['First', '1월'], ['Last', '80'], ['Filter', '5'], ['Top', '12월'], ['Round', '64.24'],
    ['Raw', '700.7499999999999']]) {                                              // 그냥 이어 붙이면 부동소수 오차 → @FormatNumber / raw float noise
    assert.match(out.text, new RegExp(k + '\\s+' + v.replace('.', '\\.') + '(\\s|$)'), k);
  }
  assert.deepEqual(out.rows.map(r => r[0]), ['10월', '9월', '8월', '6월', '7월', '5월', '3월', '4월', '1월', '2월']);
  assert.deepEqual(out.rows[0], ['10월', '70.1', '높음', '70.1억']);
  assert.deepEqual(out.rows[9], ['2월', '38.1', '보통', '38.1억']);
  assert.deepEqual(out.tags.slice(0, 5), ['success', 'success', 'success', 'success', 'neutral']);
  assert.deepEqual([out.bars[0], out.bars[9]], ['87.625%', '47.625%']);           // 최대 = d1sum.c2.max(80) / max = d1sum.c2.max
  assert.deepEqual(await events(page), []);
});

// 2단계 그룹웨어 답(계약 9.4절): gw1 목록을 EntityList · Table · @Each 로, 단추는 @ToAssistant 로 다음 질문만 보낸다(실행은 승인 카드 몫).
// Phase 2 groupware answers (contract section 9.4): the gw1 list as EntityList, Table or @Each; buttons only send the next
// question through @ToAssistant (doing things is the approval card's job).
test('groupware answers: EntityList(gw1), a Table of gw1 and @Each lists render; @ToAssistant buttons send continue_conversation; quotes and backslashes survive', async (t) => {
  const { page } = await islandPage(t);
  await render(page, PREFIX + '\n' + [
    'root = Card([summary, list, tbl, items, actions, each], [src2])',
    'summary = TextContent("안 읽은 메일이 **" + @Count(gw1) + "통** 있습니다 [1]. 맨 위 메일은 ‘" + gw1[0].left + "’입니다.")',
    'list = EntityList(gw1)',
    'tbl = Table([Col("제목", gw1.left), Col("보낸 사람", gw1.right)])',
    'items = ListBlock(@Each(gw1, "g", ListItem(g.left, g.right)))',
    'actions = Buttons([b1, b2])',
    'b1 = Button("답장 초안", @ToAssistant("이 메일에 답장 초안 써줘"), "primary")',
    'b2 = Button("첫 메일", @ToAssistant("‘" + gw1[0].left + "’ 메일에 답장 초안 써줘"), "secondary")',
    'each = Buttons(@Each(gw1, "g", Button(g.left, @ToAssistant(g.left + " 메일 요약해줘"), "tertiary")))',
  ].join('\n'), { lang: 'ko' });
  const out = await page.evaluate(() => {
    const el = document.getElementById('host');
    const flat = s => s.replace(/\s+/g, ' ').trim();
    return {
      summary: flat(window.__inline(el.querySelector('.openui-text-content'))),
      entity: flat(el.querySelector('.openui-entity-list').innerText),
      rows: [...el.querySelectorAll('.openui-table tbody tr')].map(tr => [...tr.children].map(td => td.innerText.trim())),
      items: flat(el.querySelector('.openui-list-block').innerText),
      buttons: [...el.querySelectorAll('button.openui-button-base, .openui-buttons button')].map(b => b.innerText.trim()).filter(Boolean),
      source: el.querySelector('.openui-listed-source-item [data-source-kind]')?.getAttribute('data-source-kind'),
    };
  });
  assert.equal(out.summary, '안 읽은 메일이 3통 있습니다.^1 맨 위 메일은 ‘3분기 예산안 검토 요청’입니다.');   // [1] = 마침표 뒤 번호 칩 / the chip right after the period
  assert.equal(out.entity, GW_ROWS.map(r => r.left + ' ' + r.right).join(' '));
  assert.deepEqual(out.rows, GW_ROWS.map(r => [r.left, r.right]));
  assert.equal(out.items, GW_ROWS.map((r, i) => `${i + 1} ${r.left} ${r.right}`).join(' '));
  assert.deepEqual([...new Set(out.buttons)], ['답장 초안', '첫 메일', ...GW_ROWS.map(r => r.left)]);
  assert.equal(out.source, 'gw');
  for (const label of ['답장 초안', '첫 메일', ...GW_ROWS.map(r => r.left)]) await page.click(`#host button >> text=${JSON.stringify(label)}`);
  assert.deepEqual(await events(page), [
    ['action', { type: 'continue_conversation', text: '이 메일에 답장 초안 써줘' }],
    ['action', { type: 'continue_conversation', text: '‘3분기 예산안 검토 요청’ 메일에 답장 초안 써줘' }],
    ...GW_ROWS.map(r => ['action', { type: 'continue_conversation', text: r.left + ' 메일 요약해줘' }]),
  ]);
});

// 서버 규칙이 지켜야 하는 렌더러의 한계(고치지 않고 서버가 피한다): 오류 없이 조용히 틀리거나 행이 빠지는 경우를 고정해 둔다.
// Renderer limits the server rules must respect (avoided by the server, not fixed here): the cases that silently go
// wrong or drop rows are pinned down.
test('renderer limits the server rules must respect: EntityList rows need strings, NaN and Infinity are not numbers, an undefined d1top is silent, @Avg and @Min count null as 0', async (t) => {
  const { page } = await islandPage(t);
  const tableRows = () => page.evaluate(() => [...document.querySelectorAll('#host .openui-table tr')].map(tr => [...tr.children].map(td => td.innerText.trim())));
  // 부분마다 기록을 비우고 그린다 / each part starts with an empty record
  const draw = async (program) => { await page.evaluate(() => { window.__events = []; }); await render(page, program); };
  // 1. EntityList: null · 숫자 칸이 있는 행은 빠지고 오류 / rows with a null or number cell are dropped, with errors
  await draw('gw1 = [{left: "일정 A", right: null}, {left: "일정 B", right: "10:00"}, {left: "건수", right: 3}]\nroot = Card([e])\ne = EntityList(gw1)');
  assert.equal(await page.$eval('#host .openui-entity-list', n => n.innerText.replace(/\s+/g, ' ').trim()), '일정 B 10:00');
  assert.deepEqual(await events(page), [['error', ['null-required:EntityList', 'type-mismatch:EntityList']]]);
  // 2. NaN · Infinity 는 JSON 이 아니다(파이썬 json.dumps 기본값은 쓴다): 빈 칸 · 0, 오류도 없다 / not JSON: a blank and a 0, no error
  await draw('d1 = [{c1: "가", c2: NaN}, {c1: "나", c2: Infinity}, {c1: "다", c2: -Infinity}, {c1: "라", c2: 3}]\nroot = Card([t])\nt = Table([Col("이름", d1.c1), Col("값", d1.c2, "number")])');
  assert.deepEqual(await tableRows(), [['이름', '값'], ['가', ''], ['나', ''], ['다', '0'], ['라', '3']]);
  assert.deepEqual(await events(page), []);
  // 3. 정의되지 않은 d1top(10행 이하라 서버가 만들지 않음): 열이 조용히 빈다. 별칭 d1top = d1 이면 그려진다.
  //    an undefined d1top (not made for ten rows or fewer) empties the column silently; the alias d1top = d1 renders
  await draw('d1 = [{c1: "1월"}, {c1: "2월"}]\nroot = Card([t])\nt = Table([Col("월", d1top.c1)])');
  assert.deepEqual(await tableRows(), [['월']]);
  assert.deepEqual(await events(page), []);
  await draw('d1 = [{c1: "1월"}, {c1: "2월"}]\nd1top = d1\nroot = Card([t])\nt = Table([Col("월", d1top.c1)])');
  assert.deepEqual(await tableRows(), [['월'], ['1월'], ['2월']]);
  // 4. @Avg · @Min 은 null 을 0 으로 센다(d1sum 은 빈 값을 뺀다) / @Avg and @Min count null as 0 (d1sum leaves empties out)
  await draw(PREFIX + '\nroot = Card([e])\ne = EntityList([{left: "Avg", right: "" + @Avg(d1.c3)}, {left: "Min", right: "" + @Min(d1.c3)}, {left: "d1sum", right: "" + d1sum.c3.avg}])');
  assert.equal(await page.$eval('#host .openui-entity-list', n => n.innerText.replace(/\s+/g, ' ').trim()), 'Avg 112.33333333333333 Min 0 d1sum 122.55');
  // 5. @FormatNumber 에 열(배열)을 넣으면 실행 오류(스트리밍이 끝난 뒤), Stat 은 단위만 / a whole column in @FormatNumber is a runtime error
  await draw(PREFIX + '\nroot = Card([s])\ns = StatStrip([Stat(@FormatNumber(d1.c2) + "억", "열을 넣음")])');
  assert.equal(await page.$eval('#host .stat-value', n => n.textContent), '억');
  assert.deepEqual(await events(page), [['error', ['runtime-error:Stat']]]);
});

test('MermaidDiagram shows code while streaming, then draws from the lazy mermaid chunk', async (t) => {
  const { page } = await islandPage(t);
  const requests = [];
  page.on('request', r => requests.push(new URL(r.url()).pathname));
  const program = 'root = Card([d])\nd = MermaidDiagram("flowchart TD\\n  A[신청] --> B{승인?}\\n  B -->|예| C[지급]", "정산 흐름")';
  await render(page, program, { streaming: true });
  assert.equal(await page.$eval('#host .mermaid-note', n => n.textContent), '답변이 끝나면 다이어그램을 그립니다…');
  assert.equal(requests.some(p => /\/chunks\/mermaid/.test(p)), false);
  await render(page, program, { streaming: false });
  await page.waitForSelector('#host .mermaid-svg svg', { timeout: 30000 });
  assert.ok(requests.some(p => /^\/static\/openui\/chunks\/mermaid\.core-/.test(p)), requests.join(','));
  assert.match(await page.$eval('#host .mermaid-svg', n => n.textContent), /승인/);
  assert.equal(await page.evaluate(() => document.querySelectorAll('body > [id^="dai365oui-mermaid"]').length), 0);
});

test('render errors reach onError only after streaming ends and show on screen only with debug', async (t) => {
  const { page } = await islandPage(t);
  const bad = 'root = Card([body, img])\nbody = TextContent("본문입니다")\nimg = Image("사진", "https://example.com/p.png")';
  await render(page, bad, { streaming: true });
  assert.deepEqual(await events(page), []);
  await render(page, bad, { streaming: false });
  assert.deepEqual(await events(page), [['error', ['unknown-component:Image']]]);
  assert.equal(await page.$('#host .ai365-oui-errors'), null);
  assert.match(await page.$eval('#host', n => n.innerText), /본문입니다/);         // 나머지는 그린다 / the rest renders
  await render(page, bad, { streaming: false, debug: true });
  assert.match(await page.$eval('#host .ai365-oui-errors summary', n => n.textContent), /^1개 부분을 표시하지 못했습니다$/);
});

test('re-render updates the same root; unmount empties the element; a rich answer uses no mockup selector or pruned CSS class', NEEDS_TOOLCHAIN, async (t) => {
  const { page } = await islandPage(t);
  const rich = [
    INTERNAL.replace('root = Card([header, summary, steps, limits, note, followUps], [src1, src2])', 'root = Card([header, summary, steps, limits, note, tabs, acc, list, code, tags, places, day, stats, cols, tool, form, followUps], [src1, src2])'),
    'tabs = Tabs([TabItem("a", "가", [TextContent("가 탭")]), TabItem("b", "나", [TextContent("나 탭")])])',
    'acc = Accordion([AccordionItem("q1", "질문", [TextContent("답")])])',
    'list = ListBlock([ListItem("하나", "설명", null, @ToAssistant("하나"))])',
    'code = CodeBlock("python", "print(1)")',
    'tags = TagBlock(["태그1", "태그2"])',
    'places = PlaceList([PlaceCard("본사", "강남에 있습니다 [1].", "본사", "info", [{label: "층", value: "12층"}], "https://example.com/hq")])',
    'day = ItineraryDay("1일차: 부산", [ItineraryStop("해운대", "오전 9시", "바다 산책 [2]."), ItineraryStop("자갈치", "오후 2시", "시장 구경.")], "바다와 시장")',
    'stats = StatStrip([Stat("12건", "신청"), Stat("3건", "반려", "-1", "good")])',
    'cols = Columns([Panel("월별", [BarChart(["1월", "2월"], [Series("건수", [1, 2])])]), Panel("단계", [FunnelChart([FunnelStage("신청", 100), FunnelStage("승인", 40)])])])',
    '$n = "2"',
    'tool = ToolField("수량", Input("n", "2", "number", null, $n), "1 이상")',
    'form = Form("f", Buttons([Button("보내기", @ToAssistant("보내기"), "primary")]), [FormControl("날짜", DatePicker("d", "single")), FormControl("유형", RadioGroup("r", [RadioItem("가", "설명", "a")])), FormControl("동의", CheckBoxGroup("c", [CheckBoxItem("예", "설명", "yes")]))])',
  ].join('\n');
  await render(page, rich, { streaming: false });
  // 위임 셀렉터 · 덜어 낸 CSS 의 클래스가 섬 · 포털 어디에도 없어야 한다 / neither delegated selectors nor pruned-CSS classes anywhere
  const pruned = prunedOnlyClasses();
  assert.ok(pruned.length > 100, String(pruned.length));
  const inspect = () => page.evaluate(([selectors, pruned]) => {
    const el = document.getElementById('host');
    const inPortals = [...document.querySelectorAll('.ai365-oui-portal')];
    const nodes = [...el.querySelectorAll('*'), ...inPortals, ...inPortals.flatMap(p => [...p.querySelectorAll('*')])];
    const classes = new Set(nodes.flatMap(n => [...n.classList]));
    return {
      hits: selectors.filter(s => el.querySelector(s) || inPortals.some(p => p.matches(s) || p.querySelector(s))),
      prunedHits: pruned.filter(c => classes.has(c)),
      text: /[가나] 탭/.test(el.innerText) && el.innerText.includes('본사') && el.innerText.includes('해운대') && el.innerText.includes('12건') &&
        el.innerText.includes('날짜 선택'),
      portals: inPortals.length,
    };
  }, [DELEGATED, pruned]);
  // 인용은 번호 칩(말풍선 포털 없음), 장소 · 일정 설명의 [n] 도 칩이다 / citations are number chips (no popover portal), the [n] in
  // place and itinerary descriptions too
  assert.deepEqual(await page.$$eval('#host :is(.place-description, .itinerary-stop-description) .ai365-oui-cite', cs => cs.map(c => c.textContent)), ['1', '2']);
  await page.click('#host .ai365-oui-cite >> nth=0');
  assert.deepEqual(await inspect(), { hits: [], prunedHits: [], text: true, portals: 0 });
  await shot(page, 'oui_3_rich.png');
  await page.click('#host .openui-date-picker-renderer-floating-input-container');                         // 달력 포털 / the calendar portal
  await page.waitForSelector('.openui-date-picker-renderer-floating-content');
  const withCalendar = await inspect();
  assert.deepEqual([withCalendar.hits, withCalendar.prunedHits], [[], []]);
  assert.equal(await page.$eval('.openui-date-picker-renderer-floating-content', n => n.classList.contains('ai365-oui-portal') && !n.closest('#host')), true);
  await render(page, 'root = Card([b])\nb = TextContent("두 번째 답")');
  assert.equal(await page.$eval('#host', n => n.innerText.trim()), '두 번째 답');
  await page.evaluate(() => window.AI365_OpenUI.unmount(document.getElementById('host')));
  assert.equal(await page.$eval('#host', n => n.childElementCount), 0);
  await render(page, 'root = Card([b])\nb = TextContent("다시 그림")');
  assert.equal(await page.$eval('#host', n => n.innerText.trim()), '다시 그림');
});

// 실제 목업(+ adapter) 위에서: 섬 CSS 를 넣고 섬을 그려도 호스트 요소의 계산된 스타일 · @keyframes 가 그대로다
// On the real mockup (+ adapter): adding the island CSS and rendering an island leaves the host elements' computed
// styles and @keyframes as they were
test('CSS isolation: the real mockup keeps its computed styles and keyframes; every island rule is scoped', async (t) => {
  const mockup = fs.readFileSync(path.join(ROOT, 'frontend/ai365-mockup.html'), 'utf8').replace(/\r\n/g, '\n');
  const html = mockup.replace('</body>', '<script src="/static/adapter.js"></script></body>');
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => d.dismiss());
  t.after(async () => { await page.close(); assert.deepEqual(errors, []); });
  await page.route('**/*', async route => {
    const url = new URL(route.request().url()), p = decodeURIComponent(url.pathname);
    const json = (obj, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(obj) });
    if (url.origin !== ORIGIN) return route.abort();
    if (p === '/') return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: html });
    if (p.startsWith('/static/')) return staticFile(route, p);
    if (p === '/api/access/bootstrap') return json({ pvtree: [], groups: [], members: [], teams: [] });
    if (p === '/api/boards/notifications') return json({ unread: 0, notifications: [] });
    return p.startsWith('/api/') ? json({ detail: 'stub' }, 404) : route.abort();
  });
  await page.goto(ORIGIN + '/');
  await page.waitForSelector('#viewHome.active');
  await page.waitForTimeout(300);

  const PROPS = ['font-family', 'font-size', 'font-weight', 'line-height', 'letter-spacing', 'color', 'background-color', 'margin', 'padding',
    'border', 'border-radius', 'box-shadow', 'display', 'text-align', 'animation-name', 'list-style-type', 'cursor'];
  const snapshot = () => page.evaluate((props) => {
    const pick = ['body', '.sidebar', '.nav-item', '#newChatBtn', '.avatar-btn', '.sub-header', '.model-btn', 'h1', 'h2', 'h3', 'p', 'input', 'textarea',
      'select', 'table', 'td', 'ul', 'li', 'a', 'button', 'svg', '.popover', '.tip'];
    const out = {};
    for (const sel of pick) {
      const node = [...document.querySelectorAll(sel)].find(n => !n.closest('.ai365-oui, .ai365-oui-portal'));
      if (!node) continue;
      const cs = getComputedStyle(node);
      out[sel] = Object.fromEntries(props.map(p => [p, cs.getPropertyValue(p)]));
    }
    const frames = {};
    for (const sheet of document.styleSheets) {
      let rules;
      try { rules = sheet.cssRules; } catch { continue; }
      for (const r of rules) if (r.type === CSSRule.KEYFRAMES_RULE) (frames[r.name] = frames[r.name] || []).push(r.cssText);
    }
    return { styles: out, frames };
  }, PROPS);

  // 기준선이 안정됐는지 먼저(어댑터의 비동기 초기화가 끝났는지) / the baseline must be stable first (adapter init done)
  let before = await snapshot();
  for (let i = 0; i < 10; i++) {
    await page.waitForTimeout(300);
    const again = await snapshot();
    if (JSON.stringify(again) === JSON.stringify(before)) break;
    before = again;
  }
  assert.ok(Object.keys(before.styles).length >= 12, Object.keys(before.styles).join(','));
  await page.evaluate(async ([program, entry]) => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/static/openui/openui.css?v=test';
    await new Promise((resolve, reject) => { link.onload = resolve; link.onerror = reject; document.head.appendChild(link); });
    await import(entry);
    // 채팅 답처럼 .ai-body 안에 / inside an .ai-body, like a chat answer
    const box = document.createElement('div');
    box.style.cssText = 'position:fixed;left:-5000px;top:0;width:760px';
    box.innerHTML = '<div class="msg"><div class="ai-body"><div class="ai365-oui" data-i18n-skip id="isl"></div></div></div>';
    document.body.appendChild(box);
    window.AI365_OpenUI.render(document.getElementById('isl'), program, { lang: 'ko' });
  }, [[INTERNAL.replace('root = Card([header, summary, steps, limits, note, followUps], [src1, src2])', 'root = Card([header, summary, steps, limits, note, tbl, chart, followUps], [src1, src2])'),
    ...DATA.split('\n').slice(1, 3)].join('\n'), ENTRY]);
  await page.waitForSelector('#isl .openui-table');
  const afterSnap = await snapshot();
  assert.deepEqual(afterSnap.styles, before.styles);
  for (const name of Object.keys(before.frames)) assert.deepEqual(afterSnap.frames[name], before.frames[name], name);   // 호스트 fadeIn · slideDown 그대로 / host keyframes intact
  assert.ok(before.frames.fadeIn && before.frames.slideDown);
  // 새 이름은 섬 접두사뿐(react-lang 이 head 에 한 번 넣는 불러오기 표시용 openui-spin 은 예외)
  // new names carry the island prefix only (except openui-spin, which react-lang adds to the head once for its loading spinner)
  assert.deepEqual(Object.keys(afterSnap.frames).filter(n => !(n in before.frames) && !n.startsWith('ai365oui-') && n !== 'openui-spin'), []);

  // 섬 CSS 의 모든 스타일 규칙은 섬(.ai365-oui) 또는 포털(.ai365-oui-portal) 안으로만 / every island rule is scoped
  const leaks = await page.evaluate(() => {
    const sheet = [...document.styleSheets].find(s => (s.href || '').includes('/static/openui/openui.css'));
    const bad = [];
    const walk = rules => {
      for (const r of rules) {
        if (r.type === CSSRule.STYLE_RULE) {
          for (const sel of r.selectorText.split(/,(?![^(]*\))/)) if (!/\.ai365-oui/.test(sel)) bad.push(sel.trim());
        } else if (r.type === CSSRule.FONT_FACE_RULE || r.type === CSSRule.IMPORT_RULE) bad.push(r.cssText.slice(0, 60));
        else if (r.cssRules && r.type !== CSSRule.KEYFRAMES_RULE) walk(r.cssRules);
      }
    };
    walk(sheet.cssRules);
    return { bad: bad.slice(0, 10), count: sheet.cssRules.length };
  });
  assert.deepEqual(leaks.bad, []);
  assert.ok(leaks.count > 500, String(leaks.count));

  // 호스트 .ai-body 의 표 규칙(테두리 · 짝수 줄 배경)이 섬 표에 새지 않는다 / the host .ai-body table rules stay out
  const guard = await page.evaluate(() => {
    const cell = document.querySelector('#isl .openui-table tbody tr:nth-child(2) td');
    const cs = getComputedStyle(cell);
    return { borderLeft: cs.borderLeftWidth, cellBg: cs.backgroundColor, family: getComputedStyle(document.querySelector('#isl .openui-text-content p')).fontFamily.split(',')[0].replace(/"/g, '') };
  });
  assert.deepEqual(guard, { borderLeft: '0px', cellBg: 'rgba(0, 0, 0, 0)', family: 'Pretendard' });
});

test('validate.mjs: good, no-root and unknown-component programs, batch mode and usage errors', NEEDS_TOOLCHAIN, () => {
  const script = path.join(ISLAND_SRC, 'scripts/validate.mjs');
  const run = (args, input) => spawnSync(process.execPath, [script, ...args], { input, encoding: 'utf8', cwd: ISLAND_SRC });
  const good = run([], INTERNAL);
  assert.equal(good.status, 0, good.stderr);
  const g = JSON.parse(good.stdout);
  assert.deepEqual({ ok: g.ok, hasRoot: g.hasRoot, statements: g.statements, errors: g.errors, unknown: g.unknownComponents }, { ok: true, hasRoot: true, statements: 13, errors: [], unknown: [] });
  const text = run([], '그냥 마크다운 글입니다.\n- 항목');
  assert.equal(text.status, 1);
  const tx = JSON.parse(text.stdout);
  assert.deepEqual([tx.ok, tx.hasRoot, tx.errors[0].code], [false, false, 'parse-failed']);
  const unknown = run([], 'root = Card([b, m])\nb = TextContent("x")\nm = Map("Seoul", [])');
  const u = JSON.parse(unknown.stdout);
  assert.deepEqual([unknown.status, u.ok, u.hasRoot, u.unknownComponents], [1, false, true, ['Map']]);
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'oui-validate-'));
  try {
    const file = path.join(tmp, 'answers.jsonl');
    fs.writeFileSync(file, [JSON.stringify({ id: 'a', program: 'root = Card([b])\nb = TextContent("가")' }), '', JSON.stringify({ id: 'b', program: 'root = Card([p])\np = PhotoMosaic(["https://x/y.jpg"])' }), 'not json'].join('\n'));
    const batch = run(['--batch', file]);
    assert.equal(batch.status, 0, batch.stderr);
    const rows = batch.stdout.trim().split('\n').map(l => JSON.parse(l));
    assert.deepEqual(rows.map(r => [r.id, r.ok, r.unknownComponents]), [['a', true, []], ['b', false, ['PhotoMosaic']], [null, false, []]]);
    const prog = path.join(tmp, 'p.txt');
    fs.writeFileSync(prog, '```openui\nroot = Card([b])\nb = TextContent("펜스")\n```\n');
    const fenced = run([prog]);
    assert.equal(fenced.status, 0, fenced.stdout);
  } finally { fs.rmSync(tmp, { recursive: true, force: true }); }
  assert.equal(run(['--batch']).status, 2);
  assert.equal(run(['a', 'b']).status, 2);
});

test('generated prompt and icon set: size, no images or maps, Korean examples; icon names match the lazy set', () => {
  const prompt = fs.readFileSync(path.join(ROOT, 'app/prompts/openui_system_prompt.txt'), 'utf8');
  assert.ok(prompt.length <= 45000, String(prompt.length));
  assert.equal(prompt.includes('\r'), false);
  assert.equal(prompt.includes(String.fromCharCode(0x2014)), false);                                 // em dash 없음 / no em dash
  for (const word of ['Image(', 'ImageBlock', 'PhotoMosaic', 'MapMarker', 'Map(', 'picsum', 'Tavily', 'Carousel', 'EditableTable', 'ScatterChart'])
    assert.equal(prompt.includes(word), false, word);
  for (const word of ['src1, src2 는 시스템이 이미 정의', 'ai365://kn/', 'Table([Col("항목"', 'FollowUpItem("이번 주', 'root = Card('])
    assert.ok(prompt.includes(word), word);
  const lazy = fs.readFileSync(path.join(ISLAND_SRC, 'src/vendor/lucideIcons.ts'), 'utf8');
  const set = fs.readFileSync(path.join(ISLAND_SRC, 'src/vendor/lucideSet.ts'), 'utf8');
  const names = [...lazy.slice(lazy.indexOf('LAZY_ICON_NAMES = ['), lazy.indexOf('];', lazy.indexOf('LAZY_ICON_NAMES'))).matchAll(/"([a-z0-9-]+)"/g)].map(m => m[1]);
  const keys = [...set.slice(set.indexOf('export const ICONS')).matchAll(/"([a-z0-9-]+)":/g)].map(m => m[1]);
  assert.equal(names.length, 200);
  assert.deepEqual([...names].sort(), [...keys].sort());
});

// 생성 프롬프트의 2단계 예시(Example 10 데이터 분석 · Example 11 그룹웨어 목록): 데이터 문장은 시스템 몫이라 예시 프로그램에 없다.
// 서버처럼 문장을 앞에 붙이면 검증기를 통과하고(미해결 참조 없음) 섬이 오류 없이 그린다.
// The prompt's phase 2 examples (Example 10, a data analysis; Example 11, a groupware list): the data statements are the
// system's, so the example programs do not have them. With the statements prepended as the server does, both pass the
// validator (no unresolved reference) and the island draws them without errors.
test('prompt Examples 10 and 11 (data and groupware answers) validate with the server statements prepended and render without errors', NEEDS_TOOLCHAIN, async (t) => {
  const prompt = fs.readFileSync(path.join(ROOT, 'app/prompts/openui_system_prompt.txt'), 'utf8');
  const example = n => {
    const head = prompt.indexOf(`Example ${n}:`);
    assert.ok(head > 0, `Example ${n}`);
    const start = prompt.indexOf('\n\n', head) + 2;
    return { intro: prompt.slice(head, start).trim(), program: prompt.slice(start, prompt.indexOf('\n\n', start)).trim() };
  };
  const ex10 = example(10);
  const ex11 = example(11);
  for (const ex of [ex10, ex11]) {
    assert.match(ex.intro, /시스템이 이미 정의했다/);
    assert.match(ex.intro, /다시 정의하지 말고/);
    assert.doesNotMatch(ex.program, /^(d\d+(top|sum)?|gw\d+|src\d+)\s*=/m);       // 정의하지 않고 참조만 / references only
  }
  assert.match(ex10.intro, /^Example 10: 데이터 분석 답 \(d1 · d1top · d1sum · src1 /);
  assert.match(ex11.intro, /^Example 11: 그룹웨어 목록 답 \(gw1 · src1 /);
  // chg(서버가 만든 부호 붙은 변화율 글자)와 50행 상한 규칙 / chg (the server's signed change text) and the 50-row cap rule
  assert.ok(ex10.intro.includes('d1sum = {c2: {sum, avg, min, max, first, last, change, chg}, c3: {...}} (chg 는 부호 붙은 변화율 글자'), ex10.intro);
  assert.match(ex10.intro, /행이 50개를 넘어 d1 이 잘렸으면 합계 · 평균 · 최소 · 최대는 d1sum 에서만 가져온다/);
  // 전체 표는 답 아래 표 카드에 있다: 예시에 Table · 그 머리가 없다 / the full table is the card under the answer: no Table in the example
  assert.ok(ex10.intro.includes('전체 표는 답 아래 표 카드에 있으니 Table 을 쓰지 않는다(요약 · StatStrip · 차트로 답한다)'), ex10.intro);
  assert.doesNotMatch(ex10.program, /Table\(|Col\(|InlineHeader\(/);
  for (const part of ['root = Card([header, summary, stats, chart, note, followUps], [src1])', 'LineChart(d1.c1, [Series("매출액", d1.c2)]',
    'Stat(@FormatNumber(d1sum.c2.sum)', 'Stat(@FormatNumber(d1sum.c2.last) + "억 원", "마지막 달 매출", d1sum.c2.chg)', 'Callout(', 'FollowUpBlock('])
    assert.ok(ex10.program.includes(part), part);
  for (const part of ['EntityList(gw1)', 'Button("답장 초안 쓰기", @ToAssistant(', 'FollowUpBlock(', '[src1])']) assert.ok(ex11.program.includes(part), part);
  assert.match(prompt, /When the system has defined data statements \(d1, d1top, d1sum, gw1\), follow Examples 10 and 11/);
  // 인용 칩이 되는 자리(TextContent 밖 넷 포함) / where [n] becomes a chip (the four surfaces outside TextContent included)
  assert.ok(prompt.includes('Write [n] citations only inside TextContent, Callout and TextCallout descriptions, StepsItem details, ListItem subtitles and the descriptions of PlaceCard and ItineraryStop.'));

  const program10 = [`d1 = ${oui(D_ROWS)}`, `d1top = ${oui(D_ROWS.slice(0, 10))}`, `d1sum = ${oui(D_SUM)}`, `src1 = ${oui(DATA_SRC)}`, ex10.program].join('\n');
  const program11 = [`gw1 = ${oui(GW_ROWS)}`, `src1 = ${oui(GW_SRC)}`, ex11.program].join('\n');
  const script = path.join(ISLAND_SRC, 'scripts/validate.mjs');
  for (const program of [program10, program11]) {
    const run = spawnSync(process.execPath, [script], { input: program, encoding: 'utf8', cwd: ISLAND_SRC });
    assert.equal(run.status, 0, run.stdout + run.stderr);
    const r = JSON.parse(run.stdout);
    assert.deepEqual([r.ok, r.errors, r.unresolved], [true, [], []]);
  }

  const { page } = await islandPage(t);
  const read = () => page.evaluate(() => {
    const el = document.getElementById('host');
    const flat = s => s.replace(/\s+/g, ' ').trim();
    return {
      summary: flat(window.__inline(el.querySelector('.openui-text-content'))),
      stats: [...el.querySelectorAll('.stat')].map(s => flat(s.innerText)),
      changes: [...el.querySelectorAll('.stat')].map(s => s.querySelector('.stat-change')?.className ?? null),
      rows: [...el.querySelectorAll('.openui-table tr')].map(tr => [...tr.children].map(td => td.innerText.trim())),
      callout: flat(el.querySelector('.openui-callout')?.innerText ?? ''),
      entity: flat(el.querySelector('.openui-entity-list')?.innerText ?? ''),
      buttons: [...el.querySelectorAll('.openui-buttons button')].map(b => b.innerText.trim()),
      follow: [...el.querySelectorAll('.openui-follow-up-item')].map(b => b.innerText.trim()),
      source: el.querySelector('.openui-listed-source-item [data-source-kind]')?.getAttribute('data-source-kind'),
    };
  });

  await render(page, program10, { lang: 'ko' });
  await page.waitForSelector('#host [data-openui-chart="line"] svg');
  const out10 = await read();
  assert.equal(out10.summary, '12개월 매출 합계는 700.75억 원이고, 첫 달 대비 마지막 달 변화율은 88.2%입니다.^1');   // [1] = 마침표 뒤 번호 칩 / the chip right after the period
  assert.deepEqual(out10.stats, ['700.75억 원 매출 합계', '58.4억 원 월평균 매출', '80억 원 마지막 달 매출 +88.2%']);
  assert.deepEqual(out10.changes, [null, null, 'stat-change good']);             // "+" = 좋은 소식(초록) / a rise reads as good news
  assert.deepEqual(out10.rows, []);                                               // 표 없음(표 카드가 따로 있다) / no table (the table card has it)
  assert.equal(out10.callout, '변동 폭 월 매출은 최저 38.1억 원에서 최고 80억 원 사이입니다.');
  assert.deepEqual(out10.follow, ['분기별로 묶어서 보여줘', '주문 건수가 가장 많은 달은?']);
  assert.equal(out10.source, 'data');
  assert.deepEqual(await events(page), []);
  await shot(page, 'oui_8_example10.png');

  // 변화율을 낼 수 없으면(첫 값 0 → change null) 서버는 chg = "" 를 준다: 변화 줄 없이 그린다
  // when no change can be computed (first value 0 → change null) the server sends chg = "": drawn without a change line
  const noChange = { ...D_SUM, c2: { ...D_SUM.c2, change: null, chg: '' } };
  await page.evaluate(() => { window.__events = []; });
  await render(page, program10.replace(`d1sum = ${oui(D_SUM)}`, `d1sum = ${oui(noChange)}`), { lang: 'ko' });
  const flat10 = await read();
  assert.deepEqual([flat10.stats[2], flat10.changes[2]], ['80억 원 마지막 달 매출', null]);
  assert.deepEqual(await events(page), []);
  const toneDown = { ...D_SUM, c2: { ...D_SUM.c2, change: -3.2, chg: '-3.2%' } };
  await render(page, program10.replace(`d1sum = ${oui(D_SUM)}`, `d1sum = ${oui(toneDown)}`), { lang: 'ko' });
  const down10 = await read();
  assert.deepEqual([down10.stats[2], down10.changes[2]], ['80억 원 마지막 달 매출 -3.2%', 'stat-change bad']);

  await render(page, program11, { lang: 'ko' });
  const out11 = await read();
  assert.equal(out11.summary, '안 읽은 메일이 3통 있습니다.^1 맨 위 메일은 ‘3분기 예산안 검토 요청’입니다.');   // [1] = 마침표 뒤 번호 칩 / the chip right after the period
  assert.equal(out11.entity, GW_ROWS.map(r => r.left + ' ' + r.right).join(' '));
  assert.deepEqual(out11.buttons, ['답장 초안 쓰기', '급한 메일 고르기']);
  assert.deepEqual(out11.follow, ['오늘 일정도 보여줘', '김지민 님 메일만 모아줘']);
  assert.equal(out11.source, 'gw');
  await page.click('#host button >> text=답장 초안 쓰기');
  assert.deepEqual(await events(page), [['action', { type: 'continue_conversation', text: '‘3분기 예산안 검토 요청’ 메일에 답장 초안 써줘' }]]);
  await shot(page, 'oui_9_example11.png');
});
