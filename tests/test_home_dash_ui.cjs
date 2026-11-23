// 실행: Playwright 가 NODE_PATH 에 있을 때 node --test tests/test_home_dash_ui.cjs
// 홈 대시보드 = 3열 격자 · 배치 편집 · 만든 위젯(2026-11-13 1단계, 2026-11-17 4단계 — docs/widget-agent.md 12절). 순수 함수는 그대로 부르고, 화면은 실제
// 홈 파일(frontend/ai365-home.html) + static/home_dash.js + static/home-live.js 를 가짜 원점에서 띄워 마우스로 다룬다. /api/home/* 는 작은 가짜 서버(격자 배치
// 저장 · 위젯 삭제 · 저장본 유무 · 옛 세 열 저장을 격자로), 바깥 요청(Open-Meteo)은 빈 답. 앱 서버 · DB · LLM 없음. 2026-11-20 위젯 에이전트 패널과 함께
// 쓰는 것(만든 위젯 머리의 아이콘 · preview · ghost · place · focus · editing, 머리줄 알약 셋 + 톱니 왼쪽 아이콘)도 여기서 본다.
// Run with Playwright on NODE_PATH: node --test tests/test_home_dash_ui.cjs
// Also covered: what the widget agent panel uses since 2026-11-20 (the icon on made widgets, preview, ghost, place, focus, editing, the three
// header pills plus the icon left of the gear).
// Home dashboard = the 3-column grid, layout editing and made widgets (phase 1 2026-11-13, phase 4 2026-11-17 — docs/widget-agent.md
// section 12). Pure functions are called as is; the screen is the real home file plus static/home_dash.js and static/home-live.js on a
// fake origin, driven with the mouse. /api/home/* is a tiny fake server (grid saves, widget delete, saved or not, the older column
// shape turned into a grid) and outside requests (Open-Meteo) get an empty answer. No app server, DB or LLM.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const ROOT = path.join(__dirname, '..');
const HOME = process.env.AI365_HOME_HTML || path.join(ROOT, 'frontend', 'ai365-home.html');
const PURE = require(path.join(ROOT, 'static', 'home_dash.js'));
const ORIGIN = 'http://ai365.test';
const MIME = { '.js': 'application/javascript', '.css': 'text/css', '.woff2': 'font/woff2' };

// 위젯 크기(칸) = 서버(app/home_widgets.SIZES · size_of)와 같은 값: [처음 가로, 처음 세로, 최소 가로, 최대 가로, 최소 세로, 최대 세로]
// widget sizes in cells, the same values as the server (app/home_widgets.SIZES, size_of): [w, h, min_w, max_w, min_h, max_h]
const sz = a => ({ w: a[0], h: a[1], min_w: a[2], max_w: a[3], min_h: a[4], max_h: a[5] });
const SIZE = { wx: sz([1, 1, 1, 2, 1, 1]), cal: sz([1, 2, 1, 2, 2, 3]), tok: sz([1, 1, 1, 2, 1, 1]), ask: sz([1, 1, 1, 3, 1, 1]), sc: sz([1, 1, 1, 3, 1, 2]),
  coll: sz([1, 1, 1, 2, 1, 3]), att: sz([1, 1, 1, 2, 1, 1]), org: sz([1, 2, 1, 3, 2, 3]), gwb: sz([1, 2, 1, 3, 1, 3]) };
const CHART_SIZE = sz([1, 2, 1, 3, 1, 3]), CARD_SIZE = sz([1, 1, 1, 3, 1, 3]);   // 만든 위젯: 차트가 있으면 1 × 2, 아니면 1 × 1 / made widgets
const BUILTIN = [['wx', '오늘의 날씨', true], ['cal', '일정'], ['tok', '토큰 사용량'], ['ask', 'AI 질문'], ['sc', '바로가기'], ['coll', '컬렉션'], ['att', '근태관리'], ['org', '조직도'],
  ['gwb', '그룹웨어 게시판']].map(b => ({ key: b[0], kind: 'builtin', name: b[1], locked: !!b[2], size: SIZE[b[0]] }));
// 만든 위젯의 표시 모델 = 서버(app/home_widgets.resolve)가 만든 v2 모델 그대로 / made-widget display models exactly as the server (app/home_widgets.resolve) makes them
const SALES = { key: 'cw_11111111', kind: 'custom', name: '지점별 매출', spec: {}, size: CHART_SIZE,
  model: {"v":2,"title":"지점별 매출","kpis":[],"chart":{"type":"bar","config":{"id":"c1","source":"s1","type":"bar","title":"지점별 매출","subtitle":"","x":"지점","y":[{"col":"매출","agg":"sum","name":"매출","type":"bar","axis":0}],"group":null,"sort":{"by":"none","dir":"desc"},"limit":null,"stack":false,"xLabel":"","yLabel":"","unit":"만원","ref_lines":[],"filters":[],"style":{"palette":"indigo","labels":false,"smooth":true,"fill":false,"legend":"bottom","rounded":true,"grid":true},"insight":"","size":"full"},"data":{"kind":"bar","x":["강남점","광주점"],"series":[{"name":"매출","type":"bar","axis":0,"values":[1200,800]}],"refs":[],"rows":2},"empty":false,"filters":[]},"theme":null,"insight":"","insight_wait":false,"needs_data":false,"empty":false} };
const APPROVAL = { key: 'cw_22222222', kind: 'custom', name: '결재 현황', spec: {}, size: CARD_SIZE,
  model: {"v":2,"title":"결재 현황","kpis":[{"id":"k1","label":"대기 문서","unit":"건","note":"","pending":false,"text":"12건","manual":true,"delta":null,"period":""},{"id":"k2","label":"끝난 문서","unit":"건","note":"","pending":false,"text":"31건","manual":true,"delta":null,"period":""}],"chart":null,"theme":null,"insight":"","insight_wait":false,"needs_data":false,"empty":false} };
// 3단계: 웹에서 가져온 내용(숫자 카드 + 뉴스 목록 + 출처 줄, 새로 가져오기 대상) / phase 3: fetched web content (a card, news, the origin line; refreshed)
const FX = { key: 'cw_44444444', kind: 'custom', name: '오늘 환율', spec: {}, size: CARD_SIZE,
  model: { v: 2, title: '오늘 환율', chart: null, theme: null, insight: '', insight_wait: false, needs_data: false, empty: false,
    kpis: [{ id: 'k1', label: '원달러', unit: '원', note: '11/16', pending: false, text: '1,350.5원', manual: true, delta: null, period: '' }],
    blocks: [{ type: 'list', items: [{ title: '환율 1,350원 돌파', sub: '11/16 · news.example', url: 'https://news.example/fx' }] }],
    refs: [{ kind: 'web', label: 'news.example', url: 'https://news.example/fx', page: null }], origins: [{ kind: 'web', label: '웹 검색', fetched_at: '2026-11-16T09:00:00' }],
    refresh: true } };
const RD = require(path.join(ROOT, 'static', 'report_dash.js'));
const INJECT = '<script src="/static/report_dash.js"></script><script src="/static/home_dash.js"></script><script src="/static/widget_agent.js"></script>' +
  '<script src="/static/home-live.js"></script></body>';   // = app/main.py 의 /home 주입 순서 / the injection order of /home in app/main.py

// 격자 배치(서버 모양) — 항목마다 '키 x y 가로 세로' / a grid layout in the server's shape, one 'key x y w h' per entry
const grid = (layout, ...rows) => ({ layout_type: layout, items: rows.map(r => { const p = r.split(' '); return { widget_key: p[0], x: +p[1], y: +p[2], w: +p[3], h: +p[4] }; }) });
// = app/home_widgets.DEFAULT_ITEMS / the server's default items
const DEFAULT = () => grid('1:1:1', 'wx 0 0 1 1', 'cal 0 1 1 2', 'tok 0 3 1 1', 'ask 1 0 1 1', 'sc 1 1 1 1', 'coll 1 2 1 1', 'att 1 3 1 1', 'org 2 0 1 2', 'gwb 2 2 1 2');
// 지금 홈과 같은 기본 배치를 격자 차례(y · x)로 / the default layout in grid order (y, x)
const DEFAULT_ROWS = ['wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'cal 0 1 1 2', 'sc 1 1 1 1', 'coll 1 2 1 1', 'gwb 2 2 1 2', 'tok 0 3 1 1', 'att 1 3 1 1'];
const rowsOf = items => items.map(i => (i.key || i.widget_key) + ' ' + i.x + ' ' + i.y + ' ' + i.w + ' ' + i.h);
// 옛 세 열 모양(옛 브라우저 저장본을 옮길 때 화면이 보낸다) / the older three-column shape (sent when an old browser layout moves over)
const cols = (layout, a, b, c) => ({ layout_type: layout, columns: [a, b, c].map((list, i) => ({ column_index: i, widgets: list.map((k, j) => ({ widget_key: k, sort_order: j })) })) });
const W = BUILTIN.concat([SALES, APPROVAL]);
const overlapFree = items => items.every((a, i) => items.every((b, j) => i === j || !(a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h)));

/* ── 순수 함수 / pure functions ── */
test('배치 → 화면 상태: 모르는 키 · 두 번째 키는 버리고, 크기 · 자리는 위젯의 최소 · 최대와 격자에 맞추고, 겹침은 밀고 당기며, 날씨는 늘 놓는다 / layout → state: unknown and repeated keys drop, sizes and spots fit the limits and grid, overlaps resolve, weather always stays', () => {
  const st = PURE.hdState({ layout_type: '2:3:3', items: [
    { widget_key: 'cal', x: 0, y: 0, w: 5, h: 1 },            // 가로 → 최대 2, 세로 → 최소 2 / w → max 2, h → min 2
    { widget_key: 'ghost', x: 1, y: 0, w: 1, h: 1 },          // 모르는 키 / unknown
    { widget_key: 'org', x: 9, y: -3, w: 1, h: 9 },           // x → 2, y → 0, 세로 → 최대 3 / x → 2, y → 0, h → max 3
    { widget_key: 'cal', x: 2, y: 5, w: 1, h: 2 },            // 두 번째 / repeated
    { widget_key: 'cw_11111111', x: 1, y: 0, w: 1, h: 2 }] }, W);
  // 날씨(잠금)가 맨 위에 들어가 일정을 밀고, 일정이 지점별 매출을 민다 / weather goes on top and pushes the schedule, which pushes the sales widget
  assert.deepEqual(rowsOf(st.items), ['wx 0 0 1 1', 'org 2 0 1 3', 'cal 0 1 2 2', 'cw_11111111 1 3 1 2']);
  assert.deepEqual(st.unused, ['tok', 'ask', 'sc', 'coll', 'att', 'gwb', 'cw_22222222']);   // 위젯 목록 순서 / widget-list order
  assert.equal(st.layout, '2:3:3');
  const bad = PURE.hdState({ layout_type: '9:9:9', items: 'x' }, W);
  assert.equal(bad.layout, '1:1:1');
  assert.deepEqual(rowsOf(bad.items), ['wx 0 0 1 1']);
  // 격자 차례로 정리되어 왕복하고, 다시 읽어도 같다 / round-trips in grid order and is stable when read again
  const def = PURE.hdState(DEFAULT(), W);
  assert.deepEqual(rowsOf(PURE.hdConfig(def).items), DEFAULT_ROWS);
  assert.deepEqual(PURE.hdState(PURE.hdConfig(def), W), def);
  assert.equal(PURE.hdSame(def, PURE.hdClone(def)), true);
  // 서버처럼 키 · 비율의 앞뒤 공백을 뺀다(4단계 검토) / keys and the ratio are stripped like the server
  const sp = PURE.hdState({ layout_type: ' 1:2:1 ', items: [{ widget_key: ' cal ', x: 0, y: 0, w: 1, h: 2 }] }, W);
  assert.deepEqual([sp.layout, rowsOf(sp.items)], ['1:2:1', ['wx 0 0 1 1', 'cal 0 1 1 2']]);
  assert.equal(PURE.hdGrid('2:3:3'), '2fr 3fr 3fr');
  assert.equal(PURE.hdGrid('nope'), '1fr 1fr 1fr');
  assert.deepEqual(PURE.hdSizes([{ key: 'x' }, { key: 'y', size: { h: 2, max_h: 2 } }]),
    { x: PURE.DEF_SIZE, y: Object.assign({}, PURE.DEF_SIZE, { h: 2, max_h: 2 }) });   // 크기가 없으면 1 × 1 · 가로 3 · 세로 3 까지 / no size = 1 × 1 up to 3 × 3
});

test('겹침 풀기: 앞에 놓인 위젯과 겹치면 아래로 밀고, 다 놓은 뒤 위가 빈 위젯은 당긴다 · 고정한 위젯은 자리를 지킨다 · 다시 해도 같다 / settle: push down on overlap, then pull gaps up; a fixed widget keeps its spot; idempotent', () => {
  const items = [{ key: 'a', x: 0, y: 0, w: 1, h: 1 }, { key: 'b', x: 0, y: 0, w: 1, h: 2 }, { key: 'c', x: 1, y: 5, w: 1, h: 1 }];
  const one = PURE.hdSettle(items);
  assert.deepEqual(rowsOf(one), ['a 0 0 1 1', 'c 1 0 1 1', 'b 0 1 1 2']);
  assert.deepEqual(PURE.hdSettle(one), one);
  assert.deepEqual(rowsOf(PURE.hdSettle(items, 'b')), ['b 0 0 1 2', 'c 1 0 1 1', 'a 0 2 1 1']);
  assert.deepEqual(items[1], { key: 'b', x: 0, y: 0, w: 1, h: 2 });   // 원본은 그대로 / the input is untouched
  assert.equal(overlapFree(PURE.hdSettle([1, 2, 3, 4, 5].map(i => ({ key: 'k' + i, x: i % 2, y: 0, w: 2, h: i })))), true);
});

test('옮기기 · 크기 · 넣기 · 빼기: 그 위젯은 자리를 지키고 나머지가 비킨다, 크기는 최소 · 최대 안에서 / move, resize, add, remove: that widget keeps its spot and the rest make room, sizes within the limits', () => {
  const st = PURE.hdState(DEFAULT(), W);
  // 바로가기를 오른쪽 열 맨 위로: 조직도 · 게시판이 밀리고, 가운데 열은 위로 당겨진다 / shortcuts to the top right: org and board move down, the middle column closes up
  assert.deepEqual(rowsOf(PURE.hdPlace(st, 'sc', 2, 0, 1, 1, SIZE.sc).items),
    ['wx 0 0 1 1', 'ask 1 0 1 1', 'sc 2 0 1 1', 'cal 0 1 1 2', 'coll 1 1 1 1', 'org 2 1 1 2', 'att 1 2 1 1', 'tok 0 3 1 1', 'gwb 2 3 1 2']);
  // AI 질문을 가로 2칸으로: 오른쪽의 조직도 · 게시판이 한 칸씩 내려간다 / AI ask two wide: org and board on the right move down a row
  assert.deepEqual(rowsOf(PURE.hdPlace(st, 'ask', 1, 0, 2, 1, SIZE.ask).items),
    ['wx 0 0 1 1', 'ask 1 0 2 1', 'cal 0 1 1 2', 'sc 1 1 1 1', 'org 2 1 1 2', 'coll 1 2 1 1', 'tok 0 3 1 1', 'att 1 3 1 1', 'gwb 2 3 1 2']);
  // 바로 아래 위젯 위에 놓으면 둘이 자리를 바꾼다 — 나머지를 먼저 정리한 뒤 놓는다(4단계 검토) / dropping onto the widget right below swaps them (phase-4 review)
  const pick = (s, re) => rowsOf(s.items).filter(r => re.test(r));
  assert.deepEqual(pick(PURE.hdPlace(st, 'org', 2, 2, 1, 2, SIZE.org), /^(org|gwb) /), ['gwb 2 0 1 2', 'org 2 2 1 2']);
  assert.deepEqual(pick(PURE.hdPlace(st, 'org', 2, 3, 1, 2, SIZE.org), /^(org|gwb) /), ['gwb 2 0 1 2', 'org 2 2 1 2']);
  assert.deepEqual(pick(PURE.hdPlace(st, 'ask', 1, 1, 1, 1, SIZE.ask), /^(ask|sc) /), ['sc 1 0 1 1', 'ask 1 1 1 1']);
  assert.deepEqual(pick(PURE.hdPlace(st, 'wx', 0, 2, 1, 1, SIZE.wx), /^(wx|cal|tok) /), ['cal 0 0 1 2', 'wx 0 2 1 1', 'tok 0 3 1 1']);
  // 크기는 위젯의 최소 · 최대로(날씨: 가로 2 · 세로 1 까지), 겹침은 없다 / sizes clamp to the widget's limits (weather: up to 2 × 1), never overlapping
  const big = PURE.hdPlace(st, 'wx', 0, 0, 3, 3, SIZE.wx);
  assert.deepEqual(big.items.filter(i => i.key === 'wx')[0], { key: 'wx', x: 0, y: 0, w: 2, h: 1 });
  assert.equal(overlapFree(big.items), true);
  assert.equal(PURE.hdPlace(st, 'ghost', 0, 0, 1, 1, SIZE.wx), st);
  // 빼기 → 서랍, 아래가 당겨진다(잠근 날씨는 빠지지 않는다) / remove → drawer, the column below closes up (locked weather stays)
  const out = PURE.hdRemove(st, 'sc', false);
  assert.deepEqual(rowsOf(out.items), ['wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'cal 0 1 1 2', 'coll 1 1 1 1', 'att 1 2 1 1', 'gwb 2 2 1 2', 'tok 0 3 1 1']);
  assert.deepEqual(out.unused, ['cw_11111111', 'cw_22222222', 'sc']);       // 뺀 위젯은 서랍 끝에 / the removed widget joins the drawer's end
  assert.equal(PURE.hdRemove(st, 'wx', true), st);
  assert.equal(PURE.hdRemove(out, 'sc', false), out);
  // 넣기: 자리를 안 주면 빈 첫 자리, 주면 그 자리(나머지가 비킨다), 처음 크기로 / add: the first free spot, or the given one (the rest make room), at the default size
  assert.deepEqual(rowsOf(PURE.hdAdd(out, 'sc', SIZE.sc).items).slice(-1), ['sc 1 3 1 1']);
  assert.deepEqual(rowsOf(PURE.hdAdd(out, 'sc', SIZE.sc, 1, 0).items),
    ['wx 0 0 1 1', 'sc 1 0 1 1', 'org 2 0 1 2', 'cal 0 1 1 2', 'ask 1 1 1 1', 'coll 1 2 1 1', 'gwb 2 2 1 2', 'tok 0 3 1 1', 'att 1 3 1 1']);
  assert.deepEqual(PURE.hdAdd(out, 'sc', SIZE.sc).unused, ['cw_11111111', 'cw_22222222']);
  assert.equal(PURE.hdAdd(out, 'cal', SIZE.cal), out);                     // 서랍에 없는 위젯 / not in the drawer
  assert.deepEqual(PURE.hdFree([{ x: 0, y: 0, w: 2, h: 1 }], 1, 1, 2), { x: 0, y: 1 });   // 열 수를 준다 / with a column count
  assert.deepEqual(rowsOf(st.items), DEFAULT_ROWS);                         // 원본은 그대로 / the input is untouched
});

test('끌기 계산: 열 너비(기본 비율) · 가장 가까운 칸 · 크기(최소 · 최대, 안내용 원래 칸 수) · 좁은 화면의 차례 채우기 / drag maths: column widths, the nearest cell, sizes with limits and the unclamped counts, narrow flows', () => {
  const t = PURE.hdTracks('1:1:1', 916, 16);
  assert.deepEqual(t.l.map(Math.round), [0, 311, 621]);
  assert.equal(Math.round(PURE.hdSpanW(t, 0, 2)), 605);
  const w = PURE.hdTracks('1:2:1', 1016, 16);
  assert.deepEqual(w.w, [246, 492, 246]);
  assert.deepEqual(w.l, [0, 262, 770]);
  assert.deepEqual(PURE.hdSnapMove(300, 270, 1, t), { x: 1, y: 1 });
  assert.deepEqual(PURE.hdSnapMove(700, -50, 2, t), { x: 1, y: 0 });        // 가로 2칸은 x = 1 까지 / two wide stops at x = 1
  assert.deepEqual(PURE.hdSnapSize(0, 600, 500, SIZE.cal, t), { w: 2, h: 2, wantW: 2, wantH: 2 });
  assert.deepEqual(PURE.hdSnapSize(0, 900, 300, SIZE.cal, t), { w: 2, h: 2, wantW: 3, wantH: 1 });   // 최대 가로 2 · 최소 세로 2 / max 2 wide, min 2 tall
  assert.deepEqual(PURE.hdSnapSize(2, 900, 240, SIZE.sc, t), { w: 1, h: 1, wantW: 1, wantH: 1 });   // 오른쪽 끝 열 / the last column
  // 좁은 화면: 격자 차례대로 빈 첫 자리 — 2열 · 1열 / narrow screens fill in grid order — two columns and one
  const st = PURE.hdState(DEFAULT(), W);
  const two = PURE.hdFlow(st.items, 2);
  assert.deepEqual(rowsOf(two), ['wx 0 0 1 1', 'ask 1 0 1 1', 'org 0 1 1 2', 'cal 1 1 1 2', 'sc 0 3 1 1', 'coll 1 3 1 1', 'gwb 0 4 1 2', 'tok 1 4 1 1', 'att 1 5 1 1']);
  assert.deepEqual(rowsOf(PURE.hdFlow(st.items, 1)), ['wx 0 0 1 1', 'ask 0 1 1 1', 'org 0 2 1 2', 'cal 0 4 1 2', 'sc 0 6 1 1', 'coll 0 7 1 1', 'gwb 0 8 1 2', 'tok 0 10 1 1', 'att 0 11 1 1']);
  assert.deepEqual(rowsOf(PURE.hdFlow([{ key: 'a', x: 0, y: 0, w: 3, h: 1 }], 2)), ['a 0 0 2 1']);   // 넓은 위젯은 열 수까지 / wide widgets shrink to the column count
});

test('옛 브라우저 저장본 → 세 열: 숨긴 위젯은 서랍, 저장본에 없던 위젯은 기본 열 / the old browser layout → three columns: hidden widgets go to the drawer and unknown-to-it widgets join their default column', () => {
  const keys = BUILTIN.map(b => b.key);
  const base = PURE.hdColumnsOf(PURE.hdState(DEFAULT(), BUILTIN));
  assert.deepEqual(base.cols, [['wx', 'cal', 'tok'], ['ask', 'sc', 'coll', 'att'], ['org', 'gwb']]);   // 격자 → 옛 세 열 / the grid as columns
  const st = PURE.hdLegacy({ cols: { l: ['tok', 'wx'], m: ['org', 'ask', 'nope'], r: ['cal'] }, hidden: ['ask', 'gwb'] }, keys, base);
  assert.deepEqual(st.cols, [['tok', 'wx'], ['org', 'sc', 'coll', 'att'], ['cal']]);
  assert.deepEqual(st.unused, ['ask', 'gwb']);
  // 한 열을 전부 숨긴 저장본: 그 열의 기본 위젯 하나를 되돌려 놓고 나머지 숨김은 지킨다 / a whole hidden column gets one of its defaults back
  const hid = PURE.hdLegacy({ cols: { l: ['wx', 'cal', 'tok'], m: ['ask', 'sc', 'coll', 'att'], r: ['org', 'gwb'] }, hidden: ['org', 'gwb', 'cal'] }, keys, base);
  assert.deepEqual(hid.cols, [['wx', 'tok'], ['ask', 'sc', 'coll', 'att'], ['org']]);
  assert.deepEqual(hid.unused, ['cal', 'gwb']);
  assert.equal(PURE.hdLegacy(null, keys, base), null);
  assert.equal(PURE.hdLegacy({ hidden: [] }, keys, base), null);
});

test('표시 모델 → 본문: KPI 카드 줄 · 차트 자리 · 필터 조건 · 인사이트, 글자는 이스케이프한다 / model → body: KPI row, chart slot, conditions and insight, all escaped', () => {
  const m = { v: 2, title: '<b>제목</b>', empty: false, needs_data: true, insight: '<i>서울</i>이 가장 높습니다', theme: null,
    kpis: [{ id: 'k1', label: '<img src=x onerror=1>', text: '1,200건', unit: '건', note: '이번 달', pending: false, manual: true, delta: 8.86, period: '2026-08' },
      { id: 'k2', label: '새 카드', text: '', unit: '', note: '', pending: true, manual: false, delta: null, period: '' },
      { id: 'k3', label: '감소', text: '5', unit: '', note: '', pending: false, manual: false, delta: -3.04, period: '2026-08' }],
    chart: Object.assign({}, SALES.model.chart, { filters: ['월: 최근 3개', '지점: <서울>'] }) };
  const html = PURE.hdWidgetHtml(m);
  assert.ok(!html.includes('<img') && html.includes('&lt;img src=x onerror=1&gt;') && html.includes('&lt;i&gt;서울&lt;/i&gt;') && html.includes('지점: &lt;서울&gt;'));
  assert.equal((html.match(/class="hw-kt/g) || []).length, 3);
  assert.ok(html.includes('grid-template-columns:repeat(3,minmax(0,1fr))'));                 // 3개 = 3열 / three cards, three columns
  assert.ok(html.includes('<span class="d up" data-i18n-skip>▲ 8.9%</span>') && html.includes('<span class="d down" data-i18n-skip>▼ 3%</span>'));
  assert.ok(html.includes('<div class="hw-kt pend">') && html.includes('<span class="tag">데이터 연결 전</span>'));   // 데이터 연결 전 카드 / a not-connected card
  assert.ok(html.includes('<canvas data-hw-canvas') && html.includes('aria-label="&lt;b&gt;제목&lt;/b&gt;"'));
  assert.equal((html.match(/class="hw-tag"/g) || []).length, 2);
  assert.equal((html.match(/data-i18n-skip/g) || []).length >= 8, true);                       // 사용자의 데이터는 번역하지 않는다 / user data is never translated
  const one = PURE.hdKpiHtml([{ label: '목표', text: '1,200', pending: false }]);
  assert.ok(one.includes('hw-kpis one') && one.includes('repeat(1,'));
  assert.ok(PURE.hdKpiHtml([1, 2, 3, 4].map(i => ({ label: 'k' + i, text: String(i) }))).includes('repeat(2,'));
  const big = PURE.hdWidgetHtml({ v: 2, empty: false, kpis: [], chart: { type: 'kpi', text: '540', label: '매출', filters: [] } });
  assert.ok(big.includes('<div class="hw-big"><b data-i18n-skip>540</b><span data-i18n-skip>매출</span></div>') && !big.includes('canvas'));
  const empty = PURE.hdWidgetHtml({ v: 2, empty: false, kpis: [], chart: Object.assign({}, SALES.model.chart, { empty: true }) });
  assert.ok(empty.includes('표시할 데이터가 없습니다') && !empty.includes('canvas'));
  // 1단계 모델 · 빈 모델 · 모델 아님은 '표시할 데이터가 없습니다' / phase 1 models, empty models and non-models read 'No data to show'
  for (const x of [null, { type: 'chart', empty: false }, { v: 2, empty: true }, { v: 3, empty: false }]) assert.ok(PURE.hdWidgetHtml(x).includes('표시할 데이터가 없습니다'));
});

test('3단계 본문: 글 · 목록(http(s) 만 링크) · 출처 줄(근거 둘 + 나머지 수 · 시각) · 미리 그리기 / phase 3 bodies: text, lists (http(s) links only), the origin line, the early draft', () => {
  const html = PURE.hdWidgetHtml(Object.assign({}, FX.model, { kpis: [], blocks: [{ type: 'text', text: '연차는 <b>15일</b>' },
    { type: 'list', items: [{ title: '<i>뉴스</i>', sub: '한 줄', url: 'https://a.example/1?x=1&y=2' }, { title: '스크립트', url: 'javascript:alert(1)' }, { title: '' }] }],
  refs: [{ kind: 'doc', label: '취업규칙.pdf', url: '', page: 3 }, { kind: 'web', label: 'a.example', url: 'https://a.example/1' }, { kind: 'web', label: 'b' }],
  origins: [{ kind: 'docs', label: '사내 문서', fetched_at: '2026-11-16T09:05:00' }] }));
  assert.ok(html.includes('<p class="hw-tx" data-i18n-skip>연차는 &lt;b&gt;15일&lt;/b&gt;</p>'));
  assert.ok(html.includes('<a class="t" href="https://a.example/1?x=1&amp;y=2" target="_blank" rel="noopener noreferrer">&lt;i&gt;뉴스&lt;/i&gt;</a><span class="s">한 줄</span>'));
  assert.ok(html.includes('<span class="t">스크립트</span>') && !html.includes('javascript:'));   // http(s) 가 아니면 링크가 아니다 / no link unless http(s)
  assert.equal((html.match(/<li>/g) || []).length, 2);
  assert.ok(html.includes('<span class="k">사내 문서</span>') && html.includes('<span>취업규칙.pdf p.3</span>') && html.includes('>a.example</a>') &&
    html.includes('<span>+1</span>') && html.includes('<span class="at" data-i18n-skip>11/16 09:05</span>'));
  assert.equal(PURE.hdOriginHtml({ origins: [{ kind: 'mail' }] }), '');
  assert.equal(PURE.hdOriginHtml({ origins: [] }), '');
  assert.equal(PURE.hdOriginHtml({ origin: { kind: 'web' } }), '');   // 옛 꼴(origin 하나)은 그리지 않는다 / the old single shape is not drawn
  // 부분마다 출처가 다르면 종류마다 이름이 서고, 시각은 가장 늦은 것 / several kinds each show, with the latest time
  const two = PURE.hdOriginHtml({ origins: [{ kind: 'data', fetched_at: '2026-11-16T10:00:00' }, { kind: 'web', fetched_at: '2026-11-16T10:05:00' }],
    refs: [{ kind: 'data', label: '지점별_월매출' }] });
  assert.ok(two.includes('<span class="k">사내 데이터</span>') && two.includes('<span class="k">웹 검색</span>') && two.includes('11/16 10:05'));
  assert.equal(PURE.hdFetchedAt({ origins: [{ fetched_at: '2026-11-16T10:00:00' }, { fetched_at: '2026-11-16T09:00:00' }] }), '2026-11-16T10:00:00');
  assert.equal(PURE.hdFetchedAt(null), '');
  assert.deepEqual(PURE.SRC_LABEL, { data: '사내 데이터', docs: '사내 문서', web: '웹 검색' });
  // 미리 그리기: 아직 없는 칸만 자리, 출처 줄 대신 찾는 곳 / the early draft: placeholders for what is missing, the places instead of the origin line
  const sk = v => PURE.hdWidgetHtml({ v: 2, title: 't', kpis: [], chart: null, blocks: [], empty: false, origins: [], skeleton: { view: v, labels: ['원달러', '엔화'], sources: ['웹 검색', '사내 문서'] } });
  assert.equal((sk('kpi').match(/class="hw-kt sk"/g) || []).length, 2);
  assert.ok(sk('kpi').includes('<span class="l" data-i18n-skip>엔화</span>') && sk('kpi').includes('repeat(2,'));
  assert.ok(sk('chart').includes('hw-sk-cv') && sk('list').includes('hw-sk-ls') && sk('text').includes('hw-sk-tx'));
  assert.ok(sk('kpi').includes('<div class="hw-wait"><span class="dot" aria-hidden="true"></span><span>찾는 중</span><span class="c">웹 검색</span><span class="c">사내 문서</span></div>'));
  const filled = PURE.hdWidgetHtml(Object.assign({}, FX.model, { skeleton: { view: 'kpi', labels: [], sources: ['웹 검색'] } }));
  assert.ok(!filled.includes('hw-kt sk') && filled.includes('hw-wait') && !filled.includes('hw-src'));   // 이미 있는 칸은 그대로 / existing parts stay
  assert.ok(PURE.hdWidgetHtml({ v: 2, title: 't', kpis: [], chart: null, blocks: [{ type: 'text', text: '글만' }], empty: false }).includes('글만'));
});

test('차트 = 리포트 에이전트의 그리기(rdChartConfig) 그대로, 영어면 추세 범례만 바꾼다 / charts use the report agent\'s rdChartConfig as is; English swaps the trend legend only', () => {
  const cfg = PURE.hdChartConfig(SALES.model, RD.rdChartConfig, { still: true });
  assert.deepEqual(cfg.data.labels, ['강남점', '광주점']);
  assert.deepEqual(cfg.data.datasets[0].data, [1200, 800]);
  assert.equal(cfg.options.animation, false);
  assert.deepEqual(JSON.stringify(cfg.data), JSON.stringify(RD.rdChartConfig(SALES.model.chart.config, SALES.model.chart.data, { theme: null, still: true }).data));
  const trend = { kind: 'line', x: ['2026-01', '2026-02', '2026-03'], series: [{ name: '매출', type: 'line', axis: 0, values: [1, 2, 3] }], refs: [], rows: 3,
    trend: { series: 0, values: [1, 2, 3], slope: 1, points: 3 } };
  const m = { v: 2, theme: null, chart: { config: Object.assign({}, SALES.model.chart.config, { type: 'line', x: '월' }), data: trend } };
  const labels = c => c.data.datasets.map(d => d.label);
  assert.deepEqual(labels(PURE.hdChartConfig(m, RD.rdChartConfig, {})), ['매출', '추세선']);
  assert.deepEqual(labels(PURE.hdChartConfig(m, RD.rdChartConfig, { en: true })), ['매출', 'Trend line']);
});

/* ── 화면 / screen ── */
let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

// 서버(app/home_widgets._from_columns + normalize_config)처럼 옛 세 열 저장을 격자로: 열 i 를 x = i 에 쌓고(가로 최소 · 세로 처음), 날씨를 넣고 정리
// like the server, turn an older column save into a grid: column i stacks at x = i (minimum width, default height), weather added, settled
function fromColumns(columns) {
  const items = [];
  columns.forEach(c => {
    let y = 0;
    c.widgets.slice().sort((a, b) => a.sort_order - b.sort_order).forEach(w => {
      const s = SIZE[w.widget_key] || CARD_SIZE;
      items.push({ key: w.widget_key, x: c.column_index, y: y, w: s.min_w, h: s.h });
      y += s.h;
    });
  });
  if (!items.some(i => i.key === 'wx')) items.unshift({ key: 'wx', x: 0, y: 0, w: 1, h: 1 });
  return PURE.hdSettle(items).map(i => ({ widget_key: i.key, x: i.x, y: i.y, w: i.w, h: i.h }));
}

// 가짜 서버 + 홈 열기. opts: config(저장된 배치) · saved · custom(만든 위젯) · lang · legacy(옛 브라우저 저장본) · html(홈 파일 고쳐 쓰기) · failPut
// fake server + open the home. opts: config (saved layout), saved, custom (made widgets), lang, legacy (old browser layout), html (rewrite the home file), failPut,
// slowGet (ms before the layout answers), failGets (the first N layout reads fail), badGet (a 200 with an empty body), abortPut (the save never reaches the
// server), delete404, others ({id: {saved, config, custom}} = other identities' stores), motion (allow animations), oldCache (a phase-3 cache to clear),
// width / height, holdPut, holdData. db.hold = true holds layout answers until db.held[i]() sends them; db.holdPut does the same for saves (db.heldPuts)
// and db.holdData for fresh content (/data, db.heldData)
async function fixture(t, opts) {
  opts = opts || {};
  const db = { saved: opts.saved !== false, config: opts.config || DEFAULT(), custom: (opts.custom || []).slice(), puts: [], deletes: [], deletedAs: [], gets: 0, asked: [],
    others: opts.others || {}, hold: false, held: [], dataAsks: [], fresh: opts.fresh || {}, holdPut: !!opts.holdPut, heldPuts: [], holdData: !!opts.holdData, heldData: [] };
  const who = id => ((id && db.others[id]) ? db.others[id] : db);   // 신원별 저장소(기본 사용자 = db) / per-identity store (the default user is db)
  const page = await browser.newPage({ viewport: { width: opts.width || 1500, height: opts.height || 1500 }, reducedMotion: opts.motion ? 'no-preference' : 'reduce' });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  t.after(async () => { await page.close(); assert.deepEqual(errors, []); });
  await page.route('**/*', route => {
    const req = route.request(), u = new URL(req.url());
    const json = (d, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(d) });
    if (u.origin !== ORIGIN) return json({});
    if (u.pathname === '/home') {
      let html = fs.readFileSync(HOME, 'utf8');
      if (opts.html) html = opts.html(html);
      html = html.replace(/<head>/, '<head><script src="/static/kst.js"></script>')   // = app/main.py 의 /home 주입 순서 / the injection order of /home in app/main.py
        .replace('</body>', INJECT);
      return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: html });
    }
    if (u.pathname.startsWith('/static/')) {
      const f = path.join(ROOT, u.pathname);
      return fs.existsSync(f) ? route.fulfill({ status: 200, contentType: MIME[path.extname(f)] || 'application/octet-stream', body: fs.readFileSync(f) }) : route.fulfill({ status: 404, body: '' });
    }
    if (u.pathname === '/api/home/dashboard' && req.method() === 'GET') {
      db.gets++;
      const id = u.searchParams.get('acting_user_id') || '', me = who(id);
      db.asked.push(id);
      // 답의 내용은 읽은 시점의 것(붙잡아 두었다 늦게 보내도 그때 내용이다) / the answer holds what was read at that moment, even when it is sent late
      const body = opts.badGet ? {} : { layout_options: [], config: Object.assign({ saved: me.saved }, JSON.parse(JSON.stringify(me.config))), widgets: BUILTIN.concat(me.custom) };
      const answer = () => ((opts.failGets && db.gets <= opts.failGets) ? json({ detail: 'down' }, 500) : json(body));
      if (db.hold) { db.held.push(answer); return undefined; }
      return opts.slowGet ? setTimeout(answer, opts.slowGet) : answer();
    }
    if (u.pathname === '/api/home/dashboard' && req.method() === 'PUT') {
      const body = JSON.parse(req.postData()), me = who(body.acting_user_id);
      db.puts.push(body);
      if (opts.abortPut) return route.abort();
      if (opts.failPut) return json({ detail: '저장소가 응답하지 않습니다' }, 422);
      const answer = () => {
        me.saved = true;
        me.config = { layout_type: body.layout_type, items: body.items ? body.items : fromColumns(body.columns) };
        return json(Object.assign({ saved: true }, me.config));
      };
      if (db.holdPut) { db.heldPuts.push(answer); return undefined; }   // db.heldPuts[i]() 가 보낸다 / sent by db.heldPuts[i]()
      return answer();
    }
    // 새로 가져오기(3단계): db.fresh[키] 가 있으면 그 모델 / fresh content (phase 3): the model in db.fresh[key], if any
    const data = u.pathname.match(/^\/api\/home\/widgets\/([^/]+)\/data$/);
    if (data) {
      db.dataAsks.push({ key: data[1], who: u.searchParams.get('acting_user_id') || '' });
      const m = db.fresh[data[1]];
      const answer = () => (m ? json({ key: data[1], model: m, fetched_at: '2026-11-16T10:00:00' }) : json({ detail: '존재하지 않는 위젯입니다' }, 404));
      if (db.holdData) { db.heldData.push(answer); return undefined; }   // db.heldData[i]() 가 보낸다 / sent by db.heldData[i]()
      return answer();
    }
    const one = u.pathname.match(/^\/api\/home\/widgets\/([^/]+)$/);
    if (one && req.method() === 'DELETE') {
      const id = u.searchParams.get('acting_user_id') || '', me = who(id);
      db.deletes.push(one[1]); db.deletedAs.push(id);
      if (opts.delete404) return json({ detail: '존재하지 않는 위젯입니다' }, 404);
      me.custom = me.custom.filter(w => w.key !== one[1]);
      // 서버처럼 저장된 배치에서도 빼고 다시 정리한다 / like the server, strip it from the saved layout and settle again
      me.config.items = PURE.hdSettle(me.config.items.filter(i => i.widget_key !== one[1]).map(i => ({ key: i.widget_key, x: i.x, y: i.y, w: i.w, h: i.h })))
        .map(i => ({ widget_key: i.key, x: i.x, y: i.y, w: i.w, h: i.h }));
      return json({ ok: true, config: Object.assign({ saved: me.saved }, me.config) });
    }
    if (u.pathname === '/api/collections') return json({ collections: [] });
    return json({});
  });
  await page.addInitScript(o => {
    try {
      localStorage.setItem('ai365_lang', o.lang);
      if (o.legacy && !sessionStorage.getItem('seeded')) { localStorage.setItem('ai365_home_widgets_v2', JSON.stringify(o.legacy)); sessionStorage.setItem('seeded', '1'); }
      if (o.oldCache && !sessionStorage.getItem('seededCache')) { localStorage.setItem('ai365_home_dash_v4', '{"owner":""}'); sessionStorage.setItem('seededCache', '1'); }
    } catch (e) {}
    // 용량 초과 흉내: window.__quota 가 켜지면 배치 캐시 쓰기가 실패한다 / quota simulation: with window.__quota on, writing the layout cache fails
    const set = Storage.prototype.setItem;
    Storage.prototype.setItem = function (k, v) {
      if (k === 'ai365_home_dash_v5' && window.__quota) throw new DOMException('quota', 'QuotaExceededError');
      return set.call(this, k, v);
    };
  }, { lang: opts.lang || 'ko', legacy: opts.legacy || null, oldCache: !!opts.oldCache });
  await page.goto(ORIGIN + '/home?entry=tab');
  if (!opts.inert) await page.waitForFunction(() => window.AI365_homeDash && window.AI365_homeDash.state());
  return { page, db };
}
// 홈에 놓인 위젯 = 격자 자리('키 x y 가로 세로', 화면 차례), 위젯 에이전트의 새 위젯 자리(점선 카드)는 빼고
// placed widgets as 'key x y w h' in DOM order, read from their grid areas; the widget agent's new-widget spot (the dashed card) is left out
const placed = page => page.evaluate(() => [].map.call(document.querySelectorAll('#dash > .wg:not(.hd-ghost)'), el => {
  const c = /^(\d+)\s*\/\s*span (\d+)$/.exec(el.style.gridColumn), r = /^(\d+)\s*\/\s*span (\d+)$/.exec(el.style.gridRow);
  return el.dataset.wg + ' ' + (c[1] - 1) + ' ' + (r[1] - 1) + ' ' + c[2] + ' ' + r[2];
}));
// 스크립트가 격자를 깔기 전의 홈 파일 열 칸 / the home file's own columns before the script lays out its grid
const fileCols = page => page.evaluate(() => [].map.call(document.querySelectorAll('#dash .col'), c => [].map.call(c.querySelectorAll(':scope > .wg'), w => w.dataset.wg)));
const draftRows = async page => rowsOf((await page.evaluate(() => window.AI365_homeDash.draft())).items);
const stateRows = async page => rowsOf((await page.evaluate(() => window.AI365_homeDash.state())).items);
async function openEdit(page) { await page.click('#editBtn'); await page.waitForSelector('body.hd-edit #hdEbar'); }
async function confirm(page) { await page.click('#hdOv [data-hd-dlg="ok"]'); }
const cellLabel = page => page.evaluate(() => { const c = document.querySelector('#dash > .hd-cell'); return c ? { col: c.style.gridColumn, row: c.style.gridRow, text: c.textContent } : null; });
// 격자 칸 (x, y) 의 왼쪽 위(페이지 px) / the top-left of grid cell (x, y) in page px
function cellAt(page, x, y) {
  return page.evaluate(([cx, cy]) => {
    const d = document.getElementById('dash'), r = d.getBoundingClientRect(), tr = getComputedStyle(d).gridTemplateColumns.split(' ').map(parseFloat);
    let left = r.left;
    for (let i = 0; i < cx; i++) left += tr[i] + 16;
    return { x: left, y: r.top + cy * 256 };
  }, [x, y]);
}
// 위젯을 잡는다: 'move' = 덮개 가운데, 'size' = 오른쪽 아래 손잡이. 4px 넘게 움직여 끌기를 시작해 둔다
// grab a widget: 'move' = the cover's middle, 'size' = the bottom-right handle; moved past 4px so the drag has started
async function grab(page, key, kind) {
  const b = await page.locator('#dash > .wg[data-wg="' + key + '"]').boundingBox();
  const x = kind === 'size' ? b.x + b.width - 6 : b.x + b.width / 2, y = kind === 'size' ? b.y + b.height - 6 : b.y + b.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 6, y + 6, { steps: 2 });
  return { x: x, y: y, b: b, by: (dx, dy) => page.mouse.move(x + dx, y + dy, { steps: 8 }), drop: () => page.mouse.up() };
}
// 위젯의 왼쪽 위가 칸 (x, y) 에 오도록 끈다(놓지는 않는다) / drag so the widget's top-left sits on cell (x, y), without dropping
async function moveTo(page, key, x, y) {
  const g = await grab(page, key, 'move'), c = await cellAt(page, x, y);
  await page.mouse.move(g.x + (c.x - g.b.x), g.y + (c.y - g.b.y), { steps: 8 });
  return g;
}

test('홈은 서버 격자대로 위젯을 놓는다: 칸 = 240px · 간격 16, 열 너비 = 기본 비율, 만든 위젯은 모델로 그리고 배치에 없는 기본 위젯은 숨긴다 / the home follows the server grid: 240px rows, 16 gaps, ratio columns; made widgets drawn, unplaced built-ins hidden', async t => {
  const { page } = await fixture(t, { config: grid('1:2:1', 'wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'tok 0 1 1 1', 'cw_11111111 1 1 1 2', 'sc 0 3 3 1'), custom: [SALES, APPROVAL] });
  assert.deepEqual(await placed(page), ['wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'tok 0 1 1 1', 'cw_11111111 1 1 1 2', 'sc 0 3 3 1']);
  assert.equal(await page.locator('#dash > .col').count(), 0);                       // 홈 파일의 열 칸은 걷었다 / the file's column wrappers are gone
  assert.equal(await page.evaluate(() => getComputedStyle(document.getElementById('dash')).getPropertyValue('--hd-cols').trim()), 'minmax(0,1fr) minmax(0,2fr) minmax(0,1fr)');
  const box = k => page.locator('#dash > .wg[data-wg="' + k + '"]').boundingBox();
  const [wx, ask, org, cw, sc] = await Promise.all(['wx', 'ask', 'org', 'cw_11111111', 'sc'].map(box));
  assert.ok(Math.abs(ask.width - wx.width * 2) <= 2, JSON.stringify([wx.width, ask.width]));   // 가운데가 두 배 / the middle is twice as wide
  assert.equal(Math.round(wx.height), 240);
  assert.equal(Math.round(org.height), 496);                                         // 세로 2칸 = 240 × 2 + 16 / two rows
  assert.equal(Math.round(cw.y - ask.y), 256);
  assert.equal(Math.round(sc.width), Math.round(org.x + org.width - wx.x));           // 가로 3칸 = 격자 전체 / three wide = the whole grid
  assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('#dash > .wg[data-wg="org"]')).overflowY), 'auto');   // 칸보다 길면 안에서 스크롤 / scrolls inside
  assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('#dash > .wg[data-wg="org"] > .wg-head')).position), 'sticky');
  const made = page.locator('#dash > .wg[data-wg="cw_11111111"]');
  assert.equal(await made.locator('.wg-head').innerText(), '지점별 매출');
  await page.waitForFunction(() => { const c = document.querySelector('#dash .wg[data-wg="cw_11111111"] canvas[data-hw-canvas]'); return !!(c && c._hw && c.width > 0); });
  assert.deepEqual(await page.evaluate(() => document.querySelector('#dash .wg[data-wg="cw_11111111"] canvas')._hw.data.datasets[0].data), [1200, 800]);   // 리포트 에이전트의 그리기 / the report agent's drawing
  const cv = await made.locator('.hw-cv').boundingBox();
  assert.ok(cv.height > 300, String(cv.height));                                      // 차트가 남는 높이를 채운다 / the chart fills the height left
  assert.equal(await page.locator('#dash .wg[data-wg="cw_22222222"]').count(), 0);   // 서랍의 만든 위젯은 홈에 없다 / a made widget in the drawer is not on the home
  for (const k of ['cal', 'coll', 'att', 'gwb']) assert.equal(await page.locator('.wg[data-wg="' + k + '"]').isVisible(), false, k);
  assert.equal(await page.locator('#hdPool .wg[data-wg="cal"] #calGrid').count(), 1);       // 숨겨도 마크업은 남는다(미리보기 · 다시 놓기용) / hidden, not removed
  assert.equal(await page.locator('#editBtnTx').innerText(), '배치 편집');
  assert.equal(await page.locator('#editBtn').getAttribute('title'), '배치 편집');
});

test('배치 편집: 톱니를 누르면 홈이 그 자리에서 편집 상태가 된다 — 막대 · 덮개(칸 수 · ✕ · 손잡이) · 내용은 눌리지 않음 / edit mode: the gear turns the home into edit mode — the bar, covers (cells, ✕, handle) and inert content', async t => {
  const { page } = await fixture(t, { custom: [SALES] });
  await openEdit(page);
  const bar = page.locator('#hdEbar');
  assert.equal(await bar.locator('.tx b').innerText(), '배치 편집');
  assert.equal(await bar.locator('.tx span').innerText(), '위젯을 끌어 옮기고, 오른쪽 아래 모서리로 크기를 바꾸세요.');
  assert.equal(await bar.locator('.hd-rl').innerText(), '기본 비율');
  assert.deepEqual(await bar.locator('.hd-rseg button').allInnerTexts(), ['1:1:1', '왼쪽 좁게', '가운데 넓게']);
  assert.deepEqual(await page.evaluate(() => [].map.call(document.querySelectorAll('#hdEbar .hd-rseg button'), b => b.getAttribute('aria-checked'))), ['true', 'false', 'false']);
  assert.equal(await bar.locator('[data-hd-act="add"] > span:not(.n)').innerText(), '위젯 추가');
  assert.equal(await bar.locator('[data-hd-act="add"] .n').innerText(), '1');           // 서랍의 위젯 수 / the drawer count
  assert.deepEqual(await bar.locator('[data-hd-act="cancel"], [data-hd-act="save"]').allInnerTexts(), ['취소', '저장']);
  // 톱니 · 에이전트 탭은 숨는다 / the gear and agent tabs hide
  assert.equal(await page.locator('#editBtn').isVisible(), false);
  assert.equal(await page.locator('#agentSeg').isVisible(), false);
  // 놓인 위젯마다 덮개: 칸 수 · 크기 손잡이, ✕ 는 날씨에만 없다 / a cover per placed widget: cells and a handle; ✕ on all but weather
  assert.deepEqual(await page.evaluate(() => [].map.call(document.querySelectorAll('#dash > .wg > .hd-cover .sz'), s => s.textContent)), ['1×1', '1×1', '1×2', '1×2', '1×1', '1×1', '1×2', '1×1', '1×1']);
  assert.equal(await page.locator('#dash .hd-cover .rz').count(), 9);
  assert.equal(await page.locator('#dash [data-hd-rm]').count(), 8);
  assert.equal(await page.locator('#dash [data-hd-rm="wx"]').count(), 0);
  // 위젯 안은 눌리지도 초점이 가지도 않는다 / widget contents are inert
  assert.equal(await page.evaluate(() => !!document.getElementById('calGrid').closest('[inert]')), true);
  assert.equal(await page.evaluate(() => !!document.getElementById('collNewBtn').closest('[inert]')), true);
  // [취소]: 바뀐 것이 없으면 확인 없이 닫고, 내용은 다시 눌린다 / [Cancel] with no change closes at once and contents work again
  await page.click('[data-hd-act="cancel"]');
  assert.equal(await page.locator('#hdOv').count(), 0);
  assert.equal(await page.locator('body.hd-edit').count(), 0);
  assert.equal(await page.locator('#hdEbar').isVisible(), false);
  assert.equal(await page.locator('#dash .hd-cover, [data-hd-inert], #dash [inert]').count(), 0);
  assert.equal(await page.locator('#editBtn').isVisible(), true);
});

test('끌어 옮기기: 손을 따라오고 점선이 놓을 자리를 보이며, 놓으면 그 칸에 붙고 겹친 위젯은 밀리고 빈 곳은 당겨진다 / moving: the widget follows the hand, a dashed box shows the spot, and on release it snaps while overlaps move down and gaps close', async t => {
  const { page, db } = await fixture(t, {});
  await openEdit(page);
  const g = await moveTo(page, 'sc', 2, 0);
  assert.equal(await page.locator('#dash > .wg[data-wg="sc"].hd-moving').count(), 1);
  assert.notEqual(await page.evaluate(() => document.querySelector('#dash > .wg[data-wg="sc"]').style.transform), '');   // 손을 따라온다 / follows the hand
  assert.deepEqual(await cellLabel(page), { col: '3 / span 1', row: '1 / span 1', text: '여기에 놓기' });
  assert.deepEqual(await draftRows(page), DEFAULT_ROWS);                              // 놓기 전에는 그대로 / nothing changes before the drop
  await g.drop();
  assert.equal(await page.locator('#dash > .hd-cell').count(), 0);
  const moved = ['wx 0 0 1 1', 'ask 1 0 1 1', 'sc 2 0 1 1', 'cal 0 1 1 2', 'coll 1 1 1 1', 'org 2 1 1 2', 'att 1 2 1 1', 'tok 0 3 1 1', 'gwb 2 3 1 2'];
  assert.deepEqual(await draftRows(page), moved);
  assert.deepEqual(await placed(page), moved);                                       // 화면 차례도 격자 차례 / the DOM follows grid order
  assert.equal(await page.evaluate(() => document.querySelector('#dash > .wg[data-wg="sc"]').style.transform), '');
  // 점선은 놓으면 실제로 갈 자리: 빈 곳 아래로 끌면 위로 당겨진 자리를 보인다 / the dashed box is the real landing spot: dragged below a gap it shows the pulled-up place
  const g2 = await moveTo(page, 'tok', 0, 4);
  assert.deepEqual(await cellLabel(page), { col: '1 / span 1', row: '4 / span 1', text: '여기에 놓기' });
  // Esc = 끌기를 버리고 제자리 / Esc abandons the drag and the widget stays
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#dash > .hd-cell, #dash > .wg.hd-moving').count(), 0);
  await g2.drop();
  assert.deepEqual(await draftRows(page), moved);
  assert.equal(await page.locator('body.hd-edit').count(), 1);                       // Esc 는 끌기만 버렸다 / Esc only dropped the drag
  assert.equal(db.puts.length, 0);
});

test('크기 조절: 오른쪽 아래 손잡이를 끌면 손을 따라 커지고 점선이 "놓으면 가로 × 세로"를 보이며, 최소 · 최대에 걸리면 알린다 / resizing: the corner handle follows the hand, the dashed box shows the cells, and limits are announced', async t => {
  const { page } = await fixture(t, {});
  await openEdit(page);
  const ask = await grab(page, 'ask', 'size');
  await ask.by(ask.b.width * 0.8, 30);
  assert.equal(await page.locator('#dash > .wg[data-wg="ask"].hd-sizing').count(), 1);
  assert.deepEqual(await cellLabel(page), { col: '2 / span 2', row: '1 / span 1', text: '놓으면 가로 2 × 세로 1' });
  await ask.drop();
  assert.deepEqual(await draftRows(page), ['wx 0 0 1 1', 'ask 1 0 2 1', 'cal 0 1 1 2', 'sc 1 1 1 1', 'org 2 1 1 2', 'coll 1 2 1 1', 'tok 0 3 1 1', 'att 1 3 1 1', 'gwb 2 3 1 2']);
  assert.equal(await page.evaluate(() => document.querySelector('#dash > .wg[data-wg="ask"] .hd-cover .sz').textContent), '2×1');
  assert.equal(await page.evaluate(() => document.querySelector('#dash > .wg[data-wg="ask"]').style.width), '');   // 놓으면 칸에 붙는다 / snaps on release
  // 최대: 날씨는 세로 1칸까지 — 아래로 크게 끌어도 1칸, 위젯은 조금(40px)만 더 따라오고 멈춘다 / weather is at most 1 tall; the widget stops 40px past it
  const wx = await grab(page, 'wx', 'size');
  await wx.by(0, 400);
  assert.equal((await cellLabel(page)).text, '놓으면 가로 1 × 세로 1 · 최대 세로 1칸');
  assert.equal(Math.round(await page.evaluate(() => document.querySelector('#dash > .wg[data-wg="wx"]').getBoundingClientRect().height)), 280);
  await wx.by(wx.b.width * 2.2, 0);
  assert.equal((await cellLabel(page)).text, '놓으면 가로 2 × 세로 1 · 최대 가로 2칸');
  await wx.drop();
  // 최소: 일정은 세로 2칸부터 / the schedule is at least 2 tall
  const cal = await grab(page, 'cal', 'size');
  await cal.by(0, -300);
  assert.equal((await cellLabel(page)).text, '놓으면 가로 1 × 세로 2 · 최소 세로 2칸');
  await cal.drop();
  const after = await draftRows(page);
  assert.ok(after.indexOf('wx 0 0 2 1') >= 0 && after.indexOf('cal 0 1 1 2') >= 0, JSON.stringify(after));
  assert.equal(overlapFree((await page.evaluate(() => window.AI365_homeDash.draft())).items), true);
});

test('✕ = 서랍으로, [위젯 추가] = 서랍(이름 · 처음 크기 · 미리보기 · [넣기] · 끌어 넣기 · 만든 위젯만 휴지통) / ✕ goes to the drawer; [Add widget] opens it with names, default sizes, previews, [Place], drag-in and trash for made widgets', async t => {
  const { page } = await fixture(t, { custom: [SALES, APPROVAL] });
  await openEdit(page);
  await page.click('#dash [data-hd-rm="sc"]');
  assert.deepEqual(await draftRows(page), ['wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'cal 0 1 1 2', 'coll 1 1 1 1', 'att 1 2 1 1', 'gwb 2 2 1 2', 'tok 0 3 1 1']);
  assert.equal(await page.locator('#dash .wg[data-wg="sc"]').count(), 0);
  assert.equal(await page.locator('[data-hd-act="add"] .n').innerText(), '3');
  await page.click('[data-hd-act="add"]');
  assert.equal(await page.locator('#hdDrawer').isVisible(), true);
  assert.equal(await page.getAttribute('[data-hd-act="add"]', 'aria-expanded'), 'true');
  // 위젯 목록 차례 · 이름 · 처음 크기 · 미리보기, 휴지통은 만든 위젯에만 / widget-list order, names, default sizes, previews; trash on made widgets only
  assert.deepEqual(await page.evaluate(() => [].map.call(document.querySelectorAll('#hdDrawer .hd-dcard'), c => c.dataset.hdAdd)), ['sc', 'cw_11111111', 'cw_22222222']);
  assert.deepEqual(await page.locator('#hdDrawer .hd-dhd .nm').allInnerTexts(), ['바로가기', '지점별 매출', '결재 현황']);
  assert.deepEqual(await page.locator('#hdDrawer .hd-dhd .sz').allInnerTexts(), ['1×1', '1×2', '1×1']);
  assert.deepEqual(await page.evaluate(() => [].map.call(document.querySelectorAll('#hdDrawer [data-hd-del]'), b => b.dataset.hdDel)), ['cw_11111111', 'cw_22222222']);
  assert.ok((await page.locator('#hdDrawer [data-hd-pv="sc"]').innerText()).includes('Outlook'));   // 기본 위젯 = 지금 화면의 위젯 그대로 / a built-in previews the live widget
  assert.equal(await page.locator('#hdDrawer [data-hd-pv="sc"] .hd-cover').count(), 0);           // 편집 중에 뺀 위젯도 덮개 없이 / no cover even when removed mid-edit
  await page.waitForFunction(() => { const c = document.querySelector('#hdDrawer [data-hd-pv="cw_11111111"] canvas'); return !!(c && c._hw && c.width > 0); });
  assert.equal(await page.evaluate(() => document.querySelector('#hdDrawer [data-hd-pv="cw_11111111"] canvas')._hw.options.animation), false);
  assert.deepEqual(await page.locator('#hdDrawer [data-hd-pv="cw_22222222"] .hw-kt .v').allInnerTexts(), ['12건', '31건']);
  assert.equal(await page.evaluate(() => [].every.call(document.querySelectorAll('#hdDrawer .hd-pv .wg'), w => w.hasAttribute('inert') && !w.querySelector('[id]'))), true);
  assert.deepEqual(await page.evaluate(() => { const seen = {}, dup = []; document.querySelectorAll('[id]').forEach(n => { if (seen[n.id]) dup.push(n.id); seen[n.id] = 1; }); return dup; }), []);
  // [넣기] = 빈 첫 자리에 처음 크기로, 서랍은 열린 채 / [Place] = the first free spot at the default size; the drawer stays open
  await page.click('#hdDrawer [data-hd-put="sc"]');
  assert.deepEqual((await draftRows(page)).slice(-1), ['sc 1 3 1 1']);
  assert.equal(await page.locator('#hdDrawer').isVisible(), true);
  // 끌어 넣기: 카드를 칸에 놓으면 그 자리(나머지가 비킨다) / drag in: dropping a card on a cell places it there and the rest make room
  const card = await page.locator('#hdDrawer [data-hd-add="cw_11111111"] .hd-pv').boundingBox(), c0 = await cellAt(page, 0, 0);
  await page.mouse.move(card.x + 40, card.y + 40);
  await page.mouse.down();
  await page.mouse.move(card.x + 30, card.y + 50, { steps: 2 });
  await page.mouse.move(c0.x + 40, c0.y + 40, { steps: 10 });
  assert.equal(await page.locator('.hd-float').innerText(), '지점별 매출');
  assert.deepEqual(await cellLabel(page), { col: '1 / span 1', row: '1 / span 2', text: '여기에 놓기' });
  await page.mouse.up();
  assert.deepEqual((await draftRows(page)).slice(0, 2), ['cw_11111111 0 0 1 2', 'ask 1 0 1 1']);
  assert.equal(overlapFree((await page.evaluate(() => window.AI365_homeDash.draft())).items), true);
  assert.equal(await page.locator('.hd-float').count(), 0);
  // 바깥을 누르면 서랍이 닫히고, 다 놓으면 안내 / an outside click closes the drawer; with everything placed it says so
  await page.click('[data-hd-act="add"]');
  if (!(await page.locator('#hdDrawer').isVisible())) await page.click('[data-hd-act="add"]');
  await page.click('#hdDrawer [data-hd-put="cw_22222222"]');
  assert.equal(await page.locator('#hdDrawer .hd-dnone').innerText(), '모든 위젯이 홈에 있습니다');
  assert.equal(await page.locator('[data-hd-act="add"] .n').isVisible(), false);
  await page.mouse.click(20, 20);
  assert.equal(await page.locator('#hdDrawer').isVisible(), false);
});

test('기본 비율을 바꾸고 저장하면 격자 모양으로 보내고, 홈이 바뀌고, 다시 열어도 같다 / changing the base ratio and saving sends the grid shape, the home follows and it survives a reload', async t => {
  const { page, db } = await fixture(t, { custom: [SALES] });
  await openEdit(page);
  await page.click('[data-hd-lay="2:3:3"]');
  assert.equal(await page.evaluate(() => document.getElementById('dash').style.getPropertyValue('--hd-cols')), 'minmax(0,2fr) minmax(0,3fr) minmax(0,3fr)');   // 바로 보인다 / live
  assert.deepEqual(await page.evaluate(() => [].map.call(document.querySelectorAll('#hdEbar .hd-rseg button'), b => b.getAttribute('aria-checked'))), ['false', 'true', 'false']);
  await page.click('#dash [data-hd-rm="att"]');
  await page.click('[data-hd-act="add"]');
  await page.click('#hdDrawer [data-hd-put="cw_11111111"]');
  await page.click('[data-hd-act="save"]');
  assert.equal(await page.locator('#hdOv #hdDlgTt').innerText(), '저장');
  assert.equal(await page.locator('#hdOv .hd-dlg-bd').innerText(), '배치를 저장하시겠습니까?');
  assert.equal(db.puts.length, 0);                                                    // 확인 창을 거친다 / goes through the confirmation
  await confirm(page);
  await page.waitForFunction(() => !document.body.classList.contains('hd-edit'));
  const rows = ['wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'cal 0 1 1 2', 'sc 1 1 1 1', 'coll 1 2 1 1', 'gwb 2 2 1 2', 'tok 0 3 1 1', 'cw_11111111 1 3 1 2'];
  assert.deepEqual(db.puts, [Object.assign({ acting_user_id: '' }, grid('2:3:3', ...rows))]);
  assert.equal(await page.locator('#toast.show').innerText(), '배치를 저장했습니다');
  assert.deepEqual(await placed(page), rows);
  assert.equal(await page.evaluate(() => document.getElementById('dash').style.getPropertyValue('--hd-cols')), 'minmax(0,2fr) minmax(0,3fr) minmax(0,3fr)');
  assert.equal(await page.locator('.wg[data-wg="att"]').isVisible(), false);
  await page.reload();
  await page.waitForFunction(() => window.AI365_homeDash && window.AI365_homeDash.state());
  assert.deepEqual(await placed(page), rows);
});

test('[취소]는 바뀐 것이 있으면 확인 창(Esc 는 창만 닫는다) → 저장 없이 저장본으로 / [Cancel] with changes asks first (Esc closes the dialog only), then returns to the saved layout without saving', async t => {
  const { page, db } = await fixture(t, {});
  await openEdit(page);
  await page.click('#dash [data-hd-rm="cal"]');
  await page.click('[data-hd-act="cancel"]');
  assert.equal(await page.locator('#hdOv #hdDlgTt').innerText(), '취소');
  assert.equal(await page.locator('#hdOv .hd-dlg-bd').innerText(), '배치 편집을 취소하시겠습니까?');
  assert.equal(await page.locator('#hdOv .hd-dlg-warn').innerText(), '저장하지 않으면 변경 사항이 적용되지 않습니다.');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#hdOv').count(), 0);
  assert.equal(await page.locator('body.hd-edit').count(), 1);
  await page.keyboard.press('Escape');                                                // 편집 중 Esc = [취소] / Esc while editing = [Cancel]
  assert.equal(await page.locator('#hdOv .hd-dlg-bd').innerText(), '배치 편집을 취소하시겠습니까?');
  await confirm(page);
  assert.equal(await page.locator('body.hd-edit').count(), 0);
  assert.equal(db.puts.length, 0);
  assert.deepEqual(await placed(page), DEFAULT_ROWS);
  await openEdit(page);                                                               // 다시 열면 저장본에서 시작 / reopening starts from the saved layout
  assert.deepEqual((await page.evaluate(() => window.AI365_homeDash.draft())).unused, []);
});

test('움직임을 줄이지 않았으면 비킨 위젯이 새 자리로 미끄러진다 / unless motion is reduced, widgets that make room slide to their new places', async t => {
  const { page } = await fixture(t, { motion: true });
  await openEdit(page);
  const tr = await page.evaluate(() => { document.querySelector('#dash [data-hd-rm="sc"]').click(); return document.querySelector('#dash > .wg[data-wg="coll"]').style.transition; });
  assert.ok(tr.indexOf('transform') === 0, tr);
});

test('저장에 실패하면 편집에 남고 서버가 준 문장을, 서버에 닿지 못하면 우리 문장을 알린다 / a failed save stays in edit mode with the server\'s sentence; one that never reaches the server uses ours', async t => {
  const { page } = await fixture(t, { failPut: true });
  await openEdit(page);
  await page.click('#dash [data-hd-rm="att"]');
  await page.click('[data-hd-act="save"]');
  await confirm(page);
  await page.waitForSelector('#toast.show');
  assert.equal(await page.locator('#toast').innerText(), '저장소가 응답하지 않습니다');
  assert.equal(await page.locator('body.hd-edit').count(), 1);
  assert.equal(await page.locator('#hdOv').count(), 0);
  assert.deepEqual((await page.evaluate(() => window.AI365_homeDash.draft())).unused, ['att']);   // 고친 내용은 남는다 / the edits survive
  assert.equal(await page.locator('[data-hd-act="save"]').isDisabled(), false);
  const off = await fixture(t, { abortPut: true });
  await openEdit(off.page);
  await off.page.click('[data-hd-act="save"]');
  await confirm(off.page);
  await off.page.waitForSelector('#toast.show');
  assert.equal(await off.page.locator('#toast').innerText(), '배치를 저장하지 못했습니다');   // "Failed to fetch" 가 아니다 / not "Failed to fetch"
  assert.equal(await off.page.locator('body.hd-edit').count(), 1);
});

test('만든 위젯 삭제: 서랍의 휴지통 → 확인 창 → 바로 지워지고(저장 없이도) 홈에서도 빠진다, 이미 없는 위젯도 지운 것으로 / deleting a made widget: drawer trash → confirmation → gone at once, without [Save]; an already-gone one settles as deleted', async t => {
  const { page, db } = await fixture(t, { config: grid('1:1:1', 'wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'cw_11111111 0 1 1 2'), custom: [SALES, APPROVAL] });
  // 지운 위젯은 위젯 에이전트 패널에 알린다(ai365-home-widget-deleted, 2026-11-20) / a deleted widget is announced to the widget agent panel
  const listen = p => p.evaluate(() => { window.__gone = []; document.addEventListener('ai365-home-widget-deleted', e => window.__gone.push(e.detail.key)); });
  await listen(page);
  assert.equal(await page.locator('#dash .wg[data-wg="cw_11111111"]').count(), 1);
  await openEdit(page);
  assert.equal(await page.locator('#dash [data-hd-del]').count(), 0);                // 홈에 놓인 동안에는 휴지통이 없다 / no trash while placed
  await page.click('#dash [data-hd-rm="cw_11111111"]');
  await page.click('[data-hd-act="add"]');
  await page.click('#hdDrawer [data-hd-del="cw_11111111"]');
  assert.equal(await page.locator('#hdOv #hdDlgTt').innerText(), '위젯 삭제');
  assert.equal(await page.locator('#hdOv .hd-dlg-bd b').innerText(), '지점별 매출');
  assert.equal(await page.locator('#hdOv .hd-dlg-bd span').innerText(), '위젯을 삭제하시겠습니까?');
  assert.equal(await page.locator('#hdOv .hd-dlg-warn').innerText(), '삭제한 위젯은 되돌릴 수 없습니다.');
  await page.click('#hdOv [data-hd-dlg="x"]');                                       // ✕ = 그만두기 / ✕ backs out
  assert.deepEqual([db.deletes.length, await page.evaluate(() => window.__gone)], [0, []]);
  assert.equal(await page.locator('#hdDrawer').isVisible(), true);                   // 확인 창을 눌러도 서랍은 열린 채 / the drawer stays open through the dialog
  await page.click('#hdDrawer [data-hd-del="cw_11111111"]');
  await confirm(page);
  await page.waitForFunction(() => !document.querySelector('#hdDrawer [data-hd-add="cw_11111111"]'));
  assert.deepEqual(db.deletes, ['cw_11111111']);
  assert.deepEqual(await page.evaluate(() => window.__gone), ['cw_11111111']);
  assert.equal(await page.locator('#toast').innerText(), '위젯을 삭제했습니다');
  assert.deepEqual(await page.evaluate(() => [].map.call(document.querySelectorAll('#hdDrawer .hd-dcard'), c => c.dataset.hdAdd)), ['cal', 'tok', 'sc', 'coll', 'att', 'gwb', 'cw_22222222']);
  // [저장]을 누르지 않고 나가도 지운 위젯은 홈에 없다(편집본 = 저장본이라 확인 없이 닫힌다) / gone from the home without [Save] (the draft equals the saved layout, so it closes at once)
  await page.click('[data-hd-act="cancel"]');
  assert.equal(await page.locator('body.hd-edit').count(), 0);
  assert.deepEqual(await placed(page), ['wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2']);
  assert.equal(db.puts.length, 0);
  const gone = await fixture(t, { delete404: true, custom: [SALES] });
  await listen(gone.page);
  await openEdit(gone.page);
  await gone.page.click('[data-hd-act="add"]');
  await gone.page.click('#hdDrawer [data-hd-del="cw_11111111"]');
  await confirm(gone.page);
  await gone.page.waitForFunction(() => !document.querySelector('#hdDrawer [data-hd-add="cw_11111111"]'));
  assert.equal(await gone.page.locator('#toast').innerText(), '위젯을 삭제했습니다');
  assert.deepEqual(gone.db.deletes, ['cw_11111111']);
  assert.deepEqual(await gone.page.evaluate(() => window.__gone), ['cw_11111111']);   // 이미 없던 위젯도 알린다 / an already-gone widget is announced too
});

test('옛 브라우저 저장본은 서버에 저장본이 없을 때 한 번 옛 세 열 모양으로 보내고, 서버가 격자로 바꾼 것을 놓는다 / the old browser layout moves once, sent in the older column shape, and the server\'s grid is placed', async t => {
  const legacy = { cols: { l: ['tok', 'wx', 'cal'], m: ['ask', 'coll', 'sc', 'att'], r: ['gwb', 'org'] }, hidden: ['att'] };
  const { page, db } = await fixture(t, { saved: false, legacy });
  await page.waitForFunction(() => localStorage.getItem('ai365_home_widgets_v2') === null);
  assert.deepEqual(db.puts, [Object.assign({ acting_user_id: '' }, cols('1:1:1', ['tok', 'wx', 'cal'], ['ask', 'coll', 'sc'], ['gwb', 'org']))]);
  await page.waitForFunction(() => document.querySelector('#dash > .wg[data-wg="tok"]').style.gridRow === '1 / span 1');
  assert.deepEqual(await placed(page), ['tok 0 0 1 1', 'ask 1 0 1 1', 'gwb 2 0 1 2', 'wx 0 1 1 1', 'coll 1 1 1 1', 'cal 0 2 1 2', 'sc 1 2 1 1', 'org 2 2 1 2']);
  await page.reload();
  await page.waitForFunction(() => window.AI365_homeDash && window.AI365_homeDash.state());
  assert.equal(db.puts.length, 1);
  // 서버에 저장본이 있으면 옛 저장본을 보지 않는다 / with a saved server layout the old one is ignored
  const second = await fixture(t, { saved: true, legacy });
  assert.deepEqual(await placed(second.page), DEFAULT_ROWS);
  assert.equal(second.db.puts.length, 0);
});

test('옛 브라우저 저장본은 기본 사용자에게만 옮기고, 한 열을 전부 숨긴 저장본도 옮겨진다 / the old browser layout moves to the default user only, and one that hid a whole column still moves', async t => {
  const legacy = { cols: { l: ['wx', 'cal', 'tok'], m: ['ask', 'sc', 'coll', 'att'], r: ['org', 'gwb'] }, hidden: ['org', 'gwb', 'tok'] };
  const others = { 12: { saved: false, config: DEFAULT(), custom: [] } };
  const { page, db } = await fixture(t, { saved: false, legacy, others, inert: true, html: h => h.replace('<head>', '<head><script>window.AI365_ACTING_USER = { no: 12 };</script>') });
  await page.waitForFunction(() => window.AI365_homeDash && window.AI365_homeDash.state());
  // 뷰애즈로 보는 사람(12)에게는 옮기지 않는다 / nothing moves to the viewed-as person
  assert.deepEqual(db.asked, ['12']);
  assert.deepEqual(await placed(page), DEFAULT_ROWS);
  assert.equal(db.puts.length, 0);
  assert.notEqual(await page.evaluate(() => localStorage.getItem('ai365_home_widgets_v2')), null);
  // 기본 사용자로 돌아오면 그때 옮긴다: 빈 열에는 그 열의 위젯 하나(조직도)가 돌아온다 / back as the default user it moves; the emptied column gets the org chart back
  await asUser(page, null);
  await reenter(page);
  await page.waitForFunction(() => localStorage.getItem('ai365_home_widgets_v2') === null);
  assert.deepEqual(db.puts, [Object.assign({ acting_user_id: '' }, cols('1:1:1', ['wx', 'cal'], ['ask', 'sc', 'coll', 'att'], ['org']))]);
  await page.waitForFunction(() => !document.querySelector('#dash > .wg[data-wg="tok"]'));
  assert.deepEqual(await placed(page), ['wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'cal 0 1 1 2', 'sc 1 1 1 1', 'coll 1 2 1 1', 'att 1 3 1 1']);
  assert.equal(others[12].saved, false);
});

test('부모 앱이 홈을 다시 열면 편집을 닫고(묻지 않는다) 배치를 새로 읽는다 / when the parent app reopens the home, editing closes without asking and the layout is re-read', async t => {
  const { page, db } = await fixture(t, {});
  await openEdit(page);
  await page.click('#dash [data-hd-rm="cal"]');
  const before = db.gets;
  db.config = grid('1:2:1', 'wx 0 0 1 1', 'ask 1 0 1 1', 'cal 1 1 1 2', 'org 2 0 1 2');
  await reenter(page);
  await page.waitForFunction(() => !document.body.classList.contains('hd-edit'));
  await page.waitForFunction(() => { const c = document.querySelector('#dash > .wg[data-wg="cal"]'); return c && c.style.gridColumn === '2 / span 1'; });
  assert.equal(db.gets, before + 1);
  assert.deepEqual(await placed(page), ['wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'cal 1 1 1 2']);
  assert.equal(await page.locator('#hdOv').count(), 0);
  assert.equal(db.puts.length, 0);
});

test('영어: 막대 · 서랍 · 확인 창은 사전으로, 끄는 동안의 칸 수 안내는 화면이 영어로 짓는다 / English: the bar, drawer and dialogs come from the dictionary and drag notices are composed in English', async t => {
  const { page } = await fixture(t, { lang: 'en', custom: [SALES] });
  await page.waitForFunction(() => document.getElementById('editBtnTx').textContent === 'Edit layout');
  await openEdit(page);
  await page.waitForFunction(() => document.querySelector('#hdEbar .tx b').textContent === 'Edit layout');
  assert.equal(await page.locator('#hdEbar .tx span').innerText(), 'Drag widgets to move them and resize them from the bottom-right corner.');
  assert.equal(await page.locator('#hdEbar .hd-rl').innerText(), 'Base ratio');
  assert.deepEqual(await page.locator('#hdEbar .hd-rseg button').allInnerTexts(), ['1:1:1', 'Narrow Left', 'Wide Center']);
  assert.deepEqual(await page.locator('[data-hd-act="add"] > span:not(.n), [data-hd-act="cancel"] > span, [data-hd-act="save"] > span').allInnerTexts(), ['Add widget', 'Cancel', 'Save']);
  assert.equal(await page.getAttribute('#dash [data-hd-rm="cal"]', 'title'), 'Remove from Home');
  const ask = await grab(page, 'ask', 'size');
  await ask.by(ask.b.width * 0.8, 0);
  assert.equal((await cellLabel(page)).text, 'Drop: 2 wide × 1 tall');
  await ask.by(ask.b.width * 0.8, 300);
  assert.equal((await cellLabel(page)).text, 'Drop: 2 wide × 1 tall · up to 1 tall');
  await ask.drop();
  await page.click('[data-hd-act="add"]');
  await page.waitForFunction(() => document.querySelector('#hdDrawer .hd-put').textContent === 'Place');
  assert.equal(await page.locator('#hdDrawer [data-hd-add="cw_11111111"] .nm').innerText(), '지점별 매출');   // 위젯 이름은 데이터 / a widget name is data
  await page.click('#hdDrawer [data-hd-del="cw_11111111"]');
  await page.waitForFunction(() => { const s = document.querySelector('#hdOv .hd-dlg-bd span'); return s && s.textContent === 'Delete this widget?'; });
  assert.equal(await page.locator('#hdOv #hdDlgTt').innerText(), 'Delete widget');
  assert.equal(await page.locator('#hdOv [data-hd-dlg="ok"]').innerText(), 'Delete');
  await page.click('#hdOv [data-hd-dlg="x"]');
  await page.click('[data-hd-act="cancel"]');
  await page.waitForFunction(() => { const s = document.querySelector('#hdOv .hd-dlg-bd span'); return s && s.textContent === 'Cancel layout editing?'; });
});

test('표식이 없는 옛 홈 파일에는 아무것도 하지 않는다 / an older home file without the marker is left alone', async t => {
  const { page, db } = await fixture(t, { inert: true, html: h => h.replace('id="dash" data-hd="1"', 'id="dash"') });
  await page.waitForLoadState('load');
  assert.equal(await page.evaluate(() => typeof window.AI365_homeDash), 'undefined');
  assert.equal(await page.locator('#hdPool').count(), 0);
  await page.click('#editBtn');
  assert.equal(await page.locator('body.hd-edit, #hdEbar').count(), 0);
  assert.equal(db.gets, 0);
});

test('좁은 화면: 격자 너비 900 밑은 2열, 600 밑은 1열로 차례대로 채우고(겹침 없음), 배치 편집은 넓은 화면에서만 / narrow screens flow into two columns below 900 and one below 600 without overlaps; layout editing needs the wide grid', async t => {
  const { page } = await fixture(t, { config: grid('2:3:3', ...DEFAULT_ROWS) });
  const tracks = () => page.evaluate(() => getComputedStyle(document.getElementById('dash')).gridTemplateColumns.split(' ').length);
  const noOverlap = async () => overlapFree((await placed(page)).map(r => { const p = r.split(' '); return { x: +p[1], y: +p[2], w: +p[3], h: +p[4] }; }));
  assert.equal(await tracks(), 3);
  await page.setViewportSize({ width: 900, height: 1200 });
  await page.waitForFunction(() => getComputedStyle(document.getElementById('dash')).gridTemplateColumns.split(' ').length === 2);
  assert.deepEqual(await placed(page), rowsOf(PURE.hdFlow(PURE.hdState(DEFAULT(), W).items, 2)));
  assert.equal(await noOverlap(), true);
  await page.click('#editBtn');
  await page.waitForSelector('#toast.show');
  assert.equal(await page.locator('#toast').innerText(), '배치 편집은 넓은 화면에서 할 수 있습니다');
  assert.equal(await page.locator('body.hd-edit').count(), 0);
  await page.setViewportSize({ width: 560, height: 1200 });
  await page.waitForFunction(() => getComputedStyle(document.getElementById('dash')).gridTemplateColumns.split(' ').length === 1);
  assert.equal(await noOverlap(), true);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  await page.setViewportSize({ width: 1500, height: 1500 });                         // 넓어지면 저장된 격자로 / wide again = the saved grid
  await page.waitForFunction(() => getComputedStyle(document.getElementById('dash')).gridTemplateColumns.split(' ').length === 3);
  assert.deepEqual(await placed(page), DEFAULT_ROWS);
  assert.equal(await tracks(), 3);
});

test('배치를 아직 읽는 중에 톱니를 누르면 다 읽은 뒤 편집이 열리고, 읽기에 실패하면 알리고 다시 읽는다 / the gear pressed while the layout is still loading opens editing once it arrives; a failed read says so and retries', async t => {
  const slow = await fixture(t, { slowGet: 700, inert: true });
  await slow.page.waitForSelector('#editBtn');
  await slow.page.click('#editBtn');
  await slow.page.click('#editBtn');                                                 // 두 번 눌러도 한 번만 열린다 / two presses still open it once
  assert.equal(await slow.page.locator('body.hd-edit').count(), 0);
  await slow.page.waitForSelector('body.hd-edit #hdEbar');
  assert.equal(await slow.page.locator('#toast.show').count(), 0);
  assert.deepEqual(await draftRows(slow.page), DEFAULT_ROWS);
  assert.equal(slow.db.gets, 1);
  const down = await fixture(t, { failGets: 2, inert: true });
  await down.page.waitForFunction(() => window.AI365_homeDash);
  await down.page.click('#editBtn');
  await down.page.waitForSelector('#toast.show');
  assert.equal(await down.page.locator('#toast').innerText(), '배치를 불러오지 못했습니다');
  assert.equal(await down.page.locator('body.hd-edit').count(), 0);
  assert.deepEqual(await fileCols(down.page), [['wx', 'cal', 'tok'], ['ask', 'sc', 'coll', 'att'], ['org', 'gwb']]);   // 홈 파일의 기본 배치 그대로 / the home file's own layout stays
  await down.page.click('#editBtn');                                                 // 세 번째 읽기는 성공 / the third read succeeds
  await down.page.waitForSelector('body.hd-edit #hdEbar');
});

/* ── 앱 안(목업 + 어댑터 + 홈 iframe) / inside the app (mockup + adapter + the home iframe) ── */
async function appFixture(t) {
  const mockup = fs.readFileSync(path.join(ROOT, 'frontend', 'ai365-mockup.html'), 'utf8').replace(/\r\n/g, '\n');
  const page = await browser.newPage({ viewport: { width: 1500, height: 900 }, reducedMotion: 'reduce' });
  const errors = [], asked = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => d.dismiss());
  t.after(async () => { await page.close(); assert.deepEqual(errors, []); });
  await page.route('**/*', route => {
    const req = route.request(), u = new URL(req.url()), p = decodeURIComponent(u.pathname);
    const json = (d, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(d) });
    if (u.origin !== ORIGIN) return route.abort();
    if (p === '/') return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: mockup.replace('</body>', '<script src="/static/adapter.js"></script></body>') });
    if (p === '/home') {
      const html = fs.readFileSync(HOME, 'utf8').replace(/<head>/, '<head><script src="/static/kst.js"></script>')
        .replace('</body>', INJECT);
      return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: html });
    }
    if (p.startsWith('/static/')) {
      const f = path.join(ROOT, p);
      return fs.existsSync(f) ? route.fulfill({ status: 200, contentType: MIME[path.extname(f)] || 'application/octet-stream', body: fs.readFileSync(f) }) : route.fulfill({ status: 404, body: '' });
    }
    if (p === '/api/home/dashboard') {
      asked.push(u.searchParams.get('acting_user_id') || '');
      return json({ layout_options: [], config: Object.assign({ saved: true }, DEFAULT()), widgets: BUILTIN });
    }
    if (p.startsWith('/api/access/effective/')) return json({ super: true });   // 뷰애즈 전환(권한은 슈퍼처럼) / a view-as switch (permissions as super)
    if (p === '/api/access/bootstrap') return json({ pvtree: [], groups: [], members: [], teams: [] });
    if (p === '/api/boards/notifications') return json({ unread: 0, notifications: [] });
    if (p === '/api/collections') return json({ collections: [] });
    if (p.startsWith('/api/security')) return json({});
    return p.startsWith('/api/') ? json({ detail: 'stub' }, 404) : route.abort();
  });
  await page.goto(ORIGIN + '/');
  await page.waitForFunction(() => typeof window.AI365_openHome === 'function' && !!document.getElementById('hdrFixed'));
  await page.evaluate(() => window.AI365_openHome());
  const frame = await (await page.waitForSelector('#ai365GwFrame')).contentFrame();
  await frame.waitForFunction(() => window.AI365_homeDash && window.AI365_homeDash.state());
  // 부모 앱은 iframe 이 다 뜬 뒤(load) '홈 열림'을 알리고, 홈은 그때 편집을 닫고 배치를 다시 읽는다. 그 알림까지 기다린다 — 먼저 톱니를 누르면 늦게 온 알림이
  // 방금 연 편집을 닫는다(PC 가 느릴 때 이 화면들이 시간 초과로 실패했다, 2026-11-21). 읽기 = 처음 한 번 + 알림 한 번
  // the parent app announces the entry once the iframe has loaded, and the home then closes editing and re-reads; wait for that notice, or a gear click made
  // earlier is undone by the late notice (these cases timed out on a slow PC, 2026-11-21). Reads = the first one plus the one after the notice
  while (asked.length < 2) await page.waitForTimeout(20);
  await frame.waitForFunction(() => window.AI365_homeDash && window.AI365_homeDash.state());
  return { page, frame, asked };
}

test('앱 안에서는 배치 편집 동안 우상단 고정 묶음을 숨겨 막대의 [저장] · [취소]가 가려지지 않는다 / inside the app the fixed top-right bundle hides while editing, so the bar\'s [Save] and [Cancel] are never covered', async t => {
  const { page, frame } = await appFixture(t);
  const bundle = page.locator('#hdrFixed');
  assert.equal(await bundle.isVisible(), true);
  await frame.click('#editBtn');
  await frame.waitForSelector('body.hd-edit #hdEbar');
  await page.waitForFunction(() => document.body.classList.contains('ai365-gwset-on'));
  assert.equal(await bundle.isVisible(), false);
  // [저장] · [취소]는 실제 클릭(가려져 있으면 실패한다) / real clicks on [Save] and [Cancel] (they fail when covered)
  await frame.click('[data-hd-act="save"]', { timeout: 3000 });
  await frame.click('#hdOv [data-hd-dlg="x"]');
  await frame.click('[data-hd-act="cancel"]', { timeout: 3000 });
  await page.waitForFunction(() => !document.body.classList.contains('ai365-gwset-on'));
  assert.equal(await bundle.isVisible(), true);
  // 편집을 연 채 다른 화면으로 가면 묶음이 돌아온다 / leaving for another view while editing brings the bundle back
  await frame.click('#editBtn');
  await page.waitForFunction(() => document.body.classList.contains('ai365-gwset-on'));
  await page.evaluate(() => window.showView('home'));
  assert.equal(await page.evaluate(() => document.body.classList.contains('ai365-gwset-on')), false);
  assert.equal(await bundle.isVisible(), true);
  // 홈 iframe 이 아닌 곳에서 온 같은 메시지는 듣지 않는다 / the same message from anywhere but the home iframe is ignored
  await page.evaluate(() => window.postMessage({ type: 'ai365-home-chrome', hide: true }, location.origin));
  await page.waitForTimeout(150);
  assert.equal(await page.evaluate(() => document.body.classList.contains('ai365-gwset-on')), false);
  assert.equal(await page.evaluate(() => [].map.call(document.querySelectorAll('main.main > .view.active'), v => v.id).join()), 'viewHome');   // 그 메시지가 화면을 옮기지도 않는다 / nor does it navigate
});

test('홈 머리줄 알약 = 그룹웨어 에이전트 → 전자결재 → 보안 에이전트(2026-11-20: 위젯 에이전트는 알약이 아니라 톱니 왼쪽 아이콘 = 오른쪽 패널), 고르면 그 화면 / the home header pill runs Groupware → e-Approval → Security (the widget agent is now an icon left of the gear that opens a right panel), and a pick shows that screen', async t => {
  const { page } = await fixture(t, {});
  assert.deepEqual(await page.locator('#agentSeg .seg-btn').allInnerTexts(), ['그룹웨어 에이전트', '전자결재', '보안 에이전트']);
  assert.deepEqual(await page.evaluate(() => [].map.call(document.querySelectorAll('#agentSeg .seg-btn'), b => b.dataset.seg)), ['gw', 'eapp', 'sec']);
  assert.deepEqual(await page.evaluate(() => { const b = document.getElementById('waBtn'); return [b.nextElementSibling.id, b.title, b.getAttribute('aria-pressed')]; }), ['editBtn', '위젯 에이전트', 'false']);
  // 아이콘 = 오른쪽 패널, 홈(제목 · 격자)은 그대로 / the icon opens the right panel; Home (title, grid) stays
  await page.click('#waBtn');
  await page.waitForFunction(() => document.body.classList.contains('wa-open') && !!document.getElementById('waView'));
  assert.deepEqual([await page.locator('#homeTitle').innerText(), await page.locator('#dash').isVisible(), await page.locator('#waView').isVisible(), await page.getAttribute('#waBtn', 'aria-pressed')],
    ['그룹웨어 에이전트', true, true, 'true']);
  assert.equal(await page.locator('body.wa-on').count(), 0);                          // 예전 알약 화면(wa-on)은 없다 / the former pill screen (wa-on) is gone
  // 다른 화면을 고르면 패널이 닫히고, 그 화면에는 아이콘이 없다 / another screen closes the panel and has no icon
  await page.click('#agentSeg [data-seg="eapp"]');
  await page.waitForFunction(() => document.body.classList.contains('eapp-on') && !document.body.classList.contains('wa-open'));
  assert.deepEqual([await page.locator('#homeTitle').innerText(), await page.locator('#waBtn').isVisible(), await page.locator('#waView').isVisible()], ['전자결재', false, false]);
  await page.click('#agentSeg [data-seg="sec"]');
  assert.deepEqual([await page.locator('#homeTitle').innerText(), await page.locator('#waBtn').isVisible(), await page.locator('#editBtn').isVisible()], ['보안 에이전트', false, false]);
  await page.click('#agentSeg [data-seg="gw"]');
  assert.deepEqual([await page.locator('#homeTitle').innerText(), await page.locator('#waBtn').isVisible(), await page.locator('body.wa-open').count(), await page.getAttribute('#waBtn', 'aria-pressed')],
    ['그룹웨어 에이전트', true, 0, 'false']);
});

/* ── 2026-11-15 적대 검토 반영(4단계 격자로 옮김) / fixes from the adversarial review, moved onto the phase-4 grid ── */
function asUser(page, no) { return page.evaluate(n => { window.AI365_ACTING_USER = n == null ? null : { no: n, name: '#' + n, dept: '' }; }, no); }
function reenter(page) { return page.evaluate(() => window.postMessage({ type: 'ai365-home-entry', entry: 'tab' }, location.origin)); }
// 사전에 있는 낱말(완료 · 서울 · Save · OK)로 채운 만든 위젯 / a made widget filled with dictionary words (완료, 서울, Save, OK)
const NOTE = { key: 'cw_33333333', kind: 'custom', name: '완료', size: CARD_SIZE,
  model: { v: 2, title: '완료', empty: false, needs_data: true, insight: '완료', insight_wait: false, theme: null, chart: null,
    kpis: [{ id: 'k1', label: '완료', text: 'OK', unit: '', note: '서울', pending: false, manual: true, delta: null, period: '' },
      { id: 'k2', label: 'Save', text: '', unit: '', note: '', pending: true, manual: false, delta: null, period: '' }] } };

test('신원이 바뀌면 새 사람의 배치를 다시 읽고, 이전 사람의 것에는 저장 · 삭제를 보내지 않는다 / a changed identity re-reads that person\'s layout and never saves or deletes onto the previous one', async t => {
  const others = { 12: { saved: true, config: grid('1:2:1', 'wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'cal 1 1 1 2'), custom: [APPROVAL] } };
  const { page, db } = await fixture(t, { others, custom: [SALES] });
  assert.deepEqual(db.asked, ['']);
  // 부모 앱이 알려 주면(뷰애즈 전환 → 진입 메시지) 새 신원으로 다시 읽는다 / told by the parent app it re-reads as the new identity
  await asUser(page, 12);
  await reenter(page);
  await page.waitForFunction(() => { const c = document.querySelector('#dash > .wg[data-wg="cal"]'); return c && c.style.gridColumn === '2 / span 1'; });
  assert.deepEqual(db.asked, ['', '12']);
  assert.deepEqual(await placed(page), ['wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'cal 1 1 1 2']);
  // 알림 없이 신원만 바뀐 채 톱니를 누르면: 먼저 다시 읽고 그 사람 것으로 연다 / the gear after a silent identity change reads first
  await asUser(page, null);
  await page.click('#editBtn');
  await page.waitForSelector('body.hd-edit #hdEbar');
  assert.deepEqual(db.asked, ['', '12', '']);
  assert.deepEqual((await page.evaluate(() => window.AI365_homeDash.draft())).unused, ['cw_11111111']);   // 기본 사용자의 만든 위젯 / the default user's made widget
  // 편집하는 사이 신원이 바뀌면 [저장]은 보내지 않고 닫은 뒤 새 사람 것으로 읽는다 / an identity change mid-edit sends no save; editing closes and re-reads
  await page.click('#dash [data-hd-rm="att"]');
  await asUser(page, 12);
  await page.click('[data-hd-act="save"]');
  await confirm(page);
  await page.waitForFunction(() => !document.body.classList.contains('hd-edit'));
  assert.equal(await page.locator('#toast').innerText(), '사용자가 바뀌어 대시보드를 다시 불러왔습니다');
  assert.equal(db.puts.length, 0);
  await page.waitForFunction(() => { const c = document.querySelector('#dash > .wg[data-wg="cal"]'); return c && c.style.gridColumn === '2 / span 1'; });
  assert.deepEqual(db.asked, ['', '12', '', '12']);
  // 삭제도 같다 / the same for a delete
  await openEdit(page);
  assert.deepEqual((await page.evaluate(() => window.AI365_homeDash.draft())).unused, ['tok', 'sc', 'coll', 'att', 'gwb', 'cw_22222222']);
  await asUser(page, null);
  await page.click('[data-hd-act="add"]');
  await page.click('#hdDrawer [data-hd-del="cw_22222222"]');
  await confirm(page);
  await page.waitForFunction(() => !document.body.classList.contains('hd-edit'));
  assert.deepEqual(db.deletes, []);
  assert.equal(others[12].custom.length, 1);
});

// 옛 배치를 읽은 답을 붙잡아 두었다가, 그 사이 일(저장 또는 삭제)이 끝난 뒤에 보낸다 / hold an answer carrying the old layout and send it after the work in between
async function holdRead(page, db) {
  db.hold = true;
  await reenter(page);
  while (!db.held.length) await page.waitForTimeout(20);
  db.hold = false;
}
async function releaseReads(page, db) { db.held.splice(0).forEach(send => send()); await page.waitForTimeout(250); }

test('저장보다 먼저 떠난 읽기의 답이 늦게 와도 저장한 배치를 덮지 못한다 / the answer of a read that left before a save cannot overwrite the saved layout when it arrives late', async t => {
  const { page, db } = await fixture(t, {});
  await holdRead(page, db);
  await openEdit(page);
  await page.click('#dash [data-hd-rm="att"]');
  await page.click('[data-hd-act="save"]');
  await confirm(page);
  await page.waitForFunction(() => !document.body.classList.contains('hd-edit'));
  const saved = DEFAULT_ROWS.filter(r => r.indexOf('att ') !== 0);
  assert.deepEqual(await placed(page), saved);
  await releaseReads(page, db);                                                      // 이제 옛 답(근태관리가 놓여 있다)이 도착한다 / now the old answer arrives
  assert.deepEqual(await placed(page), saved);
  await openEdit(page);
  assert.deepEqual((await page.evaluate(() => window.AI365_homeDash.draft())).unused, ['att']);
});

test('삭제보다 먼저 떠난 읽기의 답이 늦게 와도 지운 위젯을 되살리지 못한다 / the answer of a read that left before a delete cannot bring the deleted widget back when it arrives late', async t => {
  const { page, db } = await fixture(t, { config: grid('1:1:1', 'wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'cw_11111111 0 1 1 2'), custom: [SALES, APPROVAL] });
  await holdRead(page, db);
  await openEdit(page);
  await page.click('#dash [data-hd-rm="cw_11111111"]');
  await page.click('[data-hd-act="add"]');
  await page.click('#hdDrawer [data-hd-del="cw_11111111"]');
  await confirm(page);
  await page.waitForFunction(() => !document.querySelector('#hdDrawer [data-hd-add="cw_11111111"]'));
  await releaseReads(page, db);                                                      // 옛 답에는 지운 위젯이 놓여 있다 / the old answer still has the deleted widget placed
  assert.equal(await page.locator('#hdDrawer [data-hd-add="cw_11111111"], #dash .wg[data-wg="cw_11111111"]').count(), 0);
  await page.click('[data-hd-act="cancel"]');
  assert.deepEqual(await placed(page), ['wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2']);
  await openEdit(page);
  assert.equal((await page.evaluate(() => window.AI365_homeDash.draft())).unused.indexOf('cw_11111111'), -1);
});

test('만든 위젯의 이름과 데이터는 번역 사전이 바꾸지 않는다 / the dictionary never changes a made widget\'s name or data', async t => {
  const { page } = await fixture(t, { lang: 'en', config: grid('1:1:1', 'wx 0 0 1 1', 'cw_33333333 0 1 1 1', 'ask 1 0 1 1', 'org 2 0 1 2'), custom: [NOTE, SALES] });
  await page.waitForFunction(() => document.querySelector('.wg[data-wg="wx"] .wg-head').textContent.indexOf("Today's Weather") === 0);   // 영어로 바뀐 뒤에 본다 / once English is applied
  const cells = () => page.evaluate(() => [].map.call(document.querySelectorAll('#dash .wg[data-wg="cw_33333333"] .hw-kt .l, #dash .wg[data-wg="cw_33333333"] .hw-kt .v, #dash .wg[data-wg="cw_33333333"] .hw-kt .n, #dash .wg[data-wg="cw_33333333"] .hw-ins span'), c => c.textContent));
  const head = () => page.locator('#dash .wg[data-wg="cw_33333333"] .wg-head').innerText();
  assert.deepEqual(await cells(), ['완료', 'OK', '서울', 'Save', '–', '완료']);       // '완료' → Completed, '서울' → Seoul 로 바뀌지 않는다 / not turned into Completed or Seoul
  assert.equal(await page.locator('#dash .wg[data-wg="cw_33333333"] .hw-kt .tag').innerText(), 'Not connected');   // 고정 문구만 영어 / only the fixed tag turns English
  assert.equal(await head(), '완료');
  // 한국어로 돌아와도 'OK' · 'Save' 가 '확인' · '저장'이 되지 않는다 / back in Korean, 'OK' and 'Save' do not become '확인' and '저장'
  await page.evaluate(() => { localStorage.setItem('ai365_lang', 'ko'); window.dispatchEvent(new StorageEvent('storage', { key: 'ai365_lang' })); });
  await page.waitForFunction(() => document.querySelector('.wg[data-wg="wx"] .wg-head').textContent.indexOf('오늘의 날씨') === 0);
  assert.deepEqual(await cells(), ['완료', 'OK', '서울', 'Save', '–', '완료']);
  // 서랍의 이름 · 미리보기 · 삭제 확인 창도 같다 / the same in the drawer: names, previews and the delete dialog
  await page.evaluate(() => { localStorage.setItem('ai365_lang', 'en'); window.dispatchEvent(new StorageEvent('storage', { key: 'ai365_lang' })); });
  await openEdit(page);
  await page.click('#dash [data-hd-rm="cw_33333333"]');
  await page.click('[data-hd-act="add"]');
  assert.equal(await page.locator('#hdDrawer [data-hd-add="cw_33333333"] .nm').innerText(), '완료');
  assert.deepEqual(await page.evaluate(() => [].map.call(document.querySelectorAll('#hdDrawer [data-hd-pv="cw_33333333"] .hw-kt .l'), c => c.textContent)), ['완료', 'Save']);
  await page.click('#hdDrawer [data-hd-del="cw_33333333"]');
  assert.equal(await page.locator('#hdOv .hd-dlg-bd b').innerText(), '완료');
  await page.waitForFunction(() => { const s = document.querySelector('#hdOv .hd-dlg-bd span'); return s && s.textContent === 'Delete this widget?'; });
});

test('영어에서 다시 그린 문구는 기다림 없이 바로 영어다 / in English a redraw is English at once, with no wait', async t => {
  const { page } = await fixture(t, { lang: 'en' });
  await openEdit(page);
  await page.waitForFunction(() => document.querySelector('#hdEbar .tx b').textContent === 'Edit layout');
  // 누른 그 자리에서(같은 작업 안에서) 본다 — 0.12초 뒤에 바뀌는 것이 아니다 / read in the same task as the click, not 0.12 s later
  const seen = await page.evaluate(() => {
    document.querySelector('#dash [data-hd-rm="gwb"]').click();
    document.querySelector('#dash [data-hd-rm="org"]').click();
    document.querySelector('[data-hd-act="add"]').click();
    return { names: [].map.call(document.querySelectorAll('#hdDrawer .hd-dhd .nm'), n => n.textContent), put: document.querySelector('#hdDrawer .hd-put').textContent };
  });
  assert.deepEqual(seen, { names: ['Org Chart', 'Groupware board'], put: 'Place' });
  const dlg = await page.evaluate(() => { document.querySelector('[data-hd-act="cancel"]').click(); return document.querySelector('#hdOv .hd-dlg-bd').textContent; });
  assert.equal(dlg, 'Cancel layout editing?');
});

test('브라우저 캐시(v5)에는 그릴 것만 적고(크기 포함), 못 적으면 옛 캐시를 지우며, 3단계 캐시(v4)는 치운다 / the browser cache (v5) holds only what is drawn, sizes included; a failed write removes it; the phase-3 cache (v4) is cleared', async t => {
  const heavy = Object.assign({}, SALES, { spec: { title: '지점별 매출', source: { tool: 'inline', columns: ['a'], rows: [['x'.repeat(400)]] } }, created_at: 'c', updated_at: 'u' });
  const { page } = await fixture(t, { config: grid('1:1:1', 'wx 0 0 1 1', 'cw_11111111 0 1 1 2', 'ask 1 0 1 1', 'org 2 0 1 2'), custom: [heavy], oldCache: true });
  const cache = () => page.evaluate(() => JSON.parse(localStorage.getItem('ai365_home_dash_v5')));
  const c = await cache();
  assert.deepEqual(c.widgets[9], { key: 'cw_11111111', kind: 'custom', name: '지점별 매출', model: SALES.model, size: CHART_SIZE, updated_at: 'u' });   // 정의(spec)는 없다 / no definition
  assert.deepEqual(c.widgets[0], { key: 'wx', kind: 'builtin', name: '오늘의 날씨', locked: true, size: SIZE.wx });
  assert.deepEqual(c.config, grid('1:1:1', 'wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'cw_11111111 0 1 1 2'));
  assert.equal(c.owner, '');
  assert.equal(await page.evaluate(() => localStorage.getItem('ai365_home_dash_v4')), null);
  await page.evaluate(() => { window.__quota = true; });
  await reenter(page);
  await page.waitForFunction(() => localStorage.getItem('ai365_home_dash_v5') === null);
  assert.deepEqual(await placed(page), ['wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'cw_11111111 0 1 1 2']);   // 화면은 그대로 / the screen is unaffected
});

test('끌던 중 단추를 뗀 것을 놓치면 그만두고, 다른 포인터는 따라가지 않으며, 창이 초점을 잃어도 그만둔다 / a missed release abandons the drag, another pointer is not followed, and losing focus abandons it too', async t => {
  const { page } = await fixture(t, {});
  await openEdit(page);
  const g = await moveTo(page, 'cal', 2, 0);
  assert.equal(await page.locator('#dash > .hd-cell').count(), 1);
  // 다른 포인터(손가락)의 움직임 · 뗌은 무시한다 / another pointer's move and release are ignored
  await page.evaluate(() => {
    document.dispatchEvent(new PointerEvent('pointermove', { pointerId: 77, pointerType: 'touch', buttons: 1, clientX: 5, clientY: 5, bubbles: true }));
    document.dispatchEvent(new PointerEvent('pointerup', { pointerId: 77, pointerType: 'touch', clientX: 5, clientY: 5, bubbles: true }));
  });
  assert.equal(await page.locator('#dash > .hd-cell').count(), 1);
  assert.equal(await page.locator('#dash > .wg.hd-moving').count(), 1);
  // 단추가 떼어진 채 움직임이 들어오면(창 밖에서 뗐다) 끌기를 버린다 / a move with no button down (released outside the window) drops the drag
  await page.evaluate(() => {
    document.dispatchEvent(new PointerEvent('pointermove', { pointerId: 1, pointerType: 'mouse', buttons: 0, clientX: 400, clientY: 300, bubbles: true }));
  });
  assert.equal(await page.locator('#dash > .hd-cell, #dash > .wg.hd-moving').count(), 0);
  await g.drop();
  assert.deepEqual(await draftRows(page), DEFAULT_ROWS);
  await moveTo(page, 'cal', 2, 0);
  await page.evaluate(() => window.dispatchEvent(new Event('blur')));
  assert.equal(await page.locator('#dash > .hd-cell, #dash > .wg.hd-moving').count(), 0);
  await page.mouse.up();
  assert.deepEqual(await draftRows(page), DEFAULT_ROWS);
});

test('모양이 틀린 답(위젯 목록이 없다)은 적용하지 않는다 / a mis-shaped answer (no widget list) is not applied', async t => {
  const { page, db } = await fixture(t, { badGet: true, inert: true });
  await page.waitForFunction(() => window.AI365_homeDash);
  while (!db.gets) await page.waitForTimeout(20);
  await page.waitForTimeout(150);
  assert.deepEqual(await fileCols(page), [['wx', 'cal', 'tok'], ['ask', 'sc', 'coll', 'att'], ['org', 'gwb']]);   // 기본 위젯이 숨지 않는다 / no built-in is hidden
  assert.equal(await page.evaluate(() => localStorage.getItem('ai365_home_dash_v5')), null);
  await page.click('#editBtn');
  await page.waitForSelector('#toast.show');
  assert.equal(await page.locator('#toast').innerText(), '배치를 불러오지 못했습니다');
  assert.equal(await page.locator('body.hd-edit').count(), 0);
});

test('앱 안에서 사용자를 바꾸면 홈이 새 사용자로 다시 읽고 편집을 닫는다 / switching the user inside the app makes the home re-read as that user and close editing', async t => {
  const { page, frame, asked } = await appFixture(t);
  assert.deepEqual([...new Set(asked)], ['']);
  await frame.click('#editBtn');
  await frame.waitForSelector('body.hd-edit #hdEbar');
  await page.evaluate(() => window.AI365_setActingUser(12));                         // 목업의 사용자 전환 훅(프로필 › 사용자 전환과 같다) / the mockup's user-switch hook
  await frame.waitForFunction(() => !document.body.classList.contains('hd-edit'));
  await page.waitForFunction(() => !document.body.classList.contains('ai365-gwset-on'));
  while (asked.indexOf('12') < 0) await page.waitForTimeout(20);
  const n = asked.length;
  await page.evaluate(() => window.AI365_applyEffective());                          // 신원이 그대로인 호출은 다시 읽지 않는다 / a call that keeps the identity re-reads nothing
  await page.waitForTimeout(200);
  assert.equal(asked.length, n);
  await page.evaluate(() => window.AI365_setActingUser(null));
  while (asked[asked.length - 1] !== '') await page.waitForTimeout(20);
});

test('가져온 내용이 있는 놓인 위젯은 서버에 새 내용을 묻고, 바뀌었을 때만 다시 그린다(1분에 한 번까지) / placed widgets with fetched content ask for fresh content and redraw only on change (once a minute at most)', async t => {
  const fresh = Object.assign({}, FX.model, { kpis: [Object.assign({}, FX.model.kpis[0], { text: '1,362원' })], origins: [Object.assign({}, FX.model.origins[0], { fetched_at: '2026-11-16T10:00:00' })] });
  const { page, db } = await fixture(t, { config: grid('1:1:1', 'wx 0 0 1 1', 'cw_44444444 0 1 1 1', 'ask 1 0 1 1', 'cw_11111111 1 1 1 2', 'org 2 0 1 2'), custom: [FX, SALES, APPROVAL], fresh: { cw_44444444: fresh } });
  await page.waitForFunction(() => { const v = document.querySelector('#dash .wg[data-wg="cw_44444444"] .hw-kt .v'); return v && v.textContent === '1,362원'; });
  assert.deepEqual(db.dataAsks.map(a => a.key), ['cw_44444444']);                   // 가져온 내용이 있는 놓인 위젯만 / placed widgets with fetched content only
  const fx = page.locator('#dash .wg[data-wg="cw_44444444"]');
  assert.deepEqual(await fx.locator('.hw-src > span').allInnerTexts(), ['웹 검색', 'news.example', '11/16 10:00']);
  assert.equal(await fx.locator('.hw-ls a.t').innerText(), '환율 1,350원 돌파');
  assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('ai365_home_dash_v5')).widgets.filter(w => w.key === 'cw_44444444')[0].model.kpis[0].text), '1,362원');
  // 1분 안에 홈을 다시 열면 묻지 않는다 / reopening the home within a minute asks nothing
  await reenter(page);
  await page.waitForTimeout(300);
  assert.equal(db.dataAsks.length, 1);
});

test('영어: 출처 이름 · 찾는 중은 사전이 바꾸고, 근거 · 시각 · 목록은 그대로 / English: origin names and "searching" are swapped by the dictionary; references, times and lists stay', async t => {
  const { page } = await fixture(t, { lang: 'en', config: grid('1:1:1', 'wx 0 0 1 1', 'cw_44444444 0 1 1 1', 'ask 1 0 1 1', 'org 2 0 1 2'), custom: [FX] });
  await page.waitForFunction(() => { const k = document.querySelector('#dash .wg[data-wg="cw_44444444"] .hw-src .k'); return k && k.textContent === 'Web search'; });
  assert.deepEqual(await page.locator('#dash .wg[data-wg="cw_44444444"] .hw-src > span').allInnerTexts(), ['Web search', 'news.example', '11/16 09:00']);
  assert.equal(await page.locator('#dash .wg[data-wg="cw_44444444"] .hw-ls a.t').innerText(), '환율 1,350원 돌파');
  await page.evaluate(() => {
    const host = document.createElement('div');
    host.id = 'skHost';
    document.body.appendChild(host);
    window.AI365_homeWidget.render(host, { v: 2, title: 't', kpis: [], chart: null, blocks: [], empty: false, skeleton: { view: 'list', labels: [], sources: ['사내 데이터', '사내 문서', '웹 검색'] } });
    window.AI365_homeLang();
  });
  assert.deepEqual(await page.locator('#skHost .hw-wait > span:not(.dot)').allInnerTexts(), ['Searching', 'Company data', 'Company documents', 'Web search']);
});

test('늦게 온 배치 답은 먼저 새로 가져온 모델을 되돌리지 않는다 / a late layout answer never rolls back a model refreshed before it', async t => {
  // 3단계 검토: /data 가 먼저 오고 그 전에 읽은 /dashboard 가 늦게 오면 옛 숫자로 다시 그렸다 / a late /dashboard repainted the old numbers
  const fresh = Object.assign({}, FX.model, { kpis: [Object.assign({}, FX.model.kpis[0], { text: '1,362원' })], origins: [Object.assign({}, FX.model.origins[0], { fetched_at: '2026-11-16T10:00:00' })] });
  const { page, db } = await fixture(t, { config: grid('1:1:1', 'wx 0 0 1 1', 'cw_44444444 0 1 1 1', 'ask 1 0 1 1', 'org 2 0 1 2'), custom: [FX], fresh: { cw_44444444: fresh } });
  await page.waitForFunction(() => { const v = document.querySelector('#dash .wg[data-wg="cw_44444444"] .hw-kt .v'); return v && v.textContent === '1,362원'; });
  await reenter(page);   // 다시 읽은 배치에는 저장된 옛 모델(09:00)이 온다 / the re-read layout carries the stored older model (09:00)
  await page.waitForTimeout(400);
  assert.ok(db.gets >= 2);
  assert.equal(await page.locator('#dash .wg[data-wg="cw_44444444"] .hw-kt .v').innerText(), '1,362원');
  assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('ai365_home_dash_v5')).widgets.filter(w => w.key === 'cw_44444444')[0].model.kpis[0].text), '1,362원');
});

/* ── 2026-11-17 4단계 독립 검토 반영 / fixes from the phase-4 independent review ── */
test('바로 아래 위젯 위에 놓으면 둘이 자리를 바꾼다(점선도 그 자리) / dropping a widget onto the one right below swaps them, and the dashed box says so', async t => {
  const { page } = await fixture(t, {});
  await openEdit(page);
  const g = await moveTo(page, 'org', 2, 2);
  assert.deepEqual(await cellLabel(page), { col: '3 / span 1', row: '3 / span 2', text: '여기에 놓기' });
  await g.drop();
  let rows = await draftRows(page);
  assert.ok(rows.indexOf('gwb 2 0 1 2') >= 0 && rows.indexOf('org 2 2 1 2') >= 0, JSON.stringify(rows));
  const g2 = await moveTo(page, 'ask', 1, 1);
  await g2.drop();
  rows = await draftRows(page);
  assert.ok(rows.indexOf('sc 1 0 1 1') >= 0 && rows.indexOf('ask 1 1 1 1') >= 0, JSON.stringify(rows));
  assert.equal(overlapFree((await page.evaluate(() => window.AI365_homeDash.draft())).items), true);
});

test('서랍 카드를 끌기 시작하면 서랍이 비켜 주고, 편집 막대 위에서 놓으면 넣지 않는다 / dragging a drawer card moves the drawer aside, and a release over the edit bar adds nothing', async t => {
  const { page } = await fixture(t, { custom: [SALES], height: 800 });
  await openEdit(page);
  await page.evaluate(() => { document.querySelector('.hero').scrollTop = 260; });   // 막대가 위에 붙어 격자를 덮는다 / the sticky bar now covers the grid
  await page.click('[data-hd-act="add"]');
  const card = await page.locator('#hdDrawer [data-hd-add="cw_11111111"] .hd-pv').boundingBox();
  await page.mouse.move(card.x + 40, card.y + 40);
  await page.mouse.down();
  await page.mouse.move(card.x + 30, card.y + 50, { steps: 2 });
  assert.equal(await page.locator('#hdDrawer').isVisible(), false);                  // 서랍이 비켰다 / the drawer stepped aside
  assert.equal(await page.locator('.hd-float').innerText(), '지점별 매출');
  const tx = await page.locator('#hdEbar .tx').boundingBox();
  await page.mouse.move(tx.x + 30, tx.y + tx.height / 2, { steps: 6 });             // 막대 위 / over the bar
  assert.equal(await page.locator('#dash > .hd-cell').count(), 0);
  await page.mouse.up();
  assert.deepEqual((await page.evaluate(() => window.AI365_homeDash.draft())).unused, ['cw_11111111']);
  assert.deepEqual(await draftRows(page), DEFAULT_ROWS);
  assert.equal(await page.locator('.hd-float').count(), 0);
});

test('저장 답이 오기 전에 다른 사람의 배치를 읽었으면, 늦게 온 답은 그 사람의 화면 · 캐시를 바꾸지 않는다 / a save answer arriving after another person\'s layout was read never touches that person\'s screen or cache', async t => {
  const twelve = ['wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'cal 1 1 1 2'];
  const others = { 12: { saved: true, config: grid('1:2:1', ...twelve), custom: [] } };
  const { page, db } = await fixture(t, { others });
  await openEdit(page);
  await page.click('#dash [data-hd-rm="att"]');
  db.holdPut = true;
  await page.click('[data-hd-act="save"]');
  await confirm(page);
  while (!db.heldPuts.length) await page.waitForTimeout(20);
  db.holdPut = false;
  await asUser(page, 12);
  await reenter(page);                                                               // 앱이 다른 사람으로 홈을 다시 열었다 / the app reopened the home as someone else
  await page.waitForFunction(() => { const c = document.querySelector('#dash > .wg[data-wg="cal"]'); return c && c.style.gridColumn === '2 / span 1'; });
  assert.equal(await page.locator('body.hd-edit').count(), 0);
  db.heldPuts.splice(0).forEach(send => send());                                     // 이제 이전 사람(기본 사용자)의 저장 답이 온다 / now the previous person's save answer arrives
  await page.waitForTimeout(300);
  assert.deepEqual(await placed(page), twelve);
  assert.deepEqual(await stateRows(page), twelve);
  const c = await page.evaluate(() => JSON.parse(localStorage.getItem('ai365_home_dash_v5')));
  assert.equal(c.owner, '12');
  assert.deepEqual(rowsOf(c.config.items), twelve);
  assert.deepEqual(db.puts.map(p => p.acting_user_id), ['']);                        // 저장은 이전 사람 것 하나뿐 / one save, the previous person's
  assert.equal(rowsOf(others[12].config.items).join(), twelve.join());
  assert.equal(await page.locator('#hdOv').count(), 0);
});

test('위젯 에이전트가 정의를 바꾸면(updated_at) 먼저 새로 가져온 모델 대신 새 정의의 모델을 그린다 / a definition changed by the widget agent (updated_at) draws its new model, not one refreshed before', async t => {
  const fx = Object.assign({}, FX, { updated_at: '2026-11-16T09:00:00' });
  const fresh = Object.assign({}, FX.model, { kpis: [Object.assign({}, FX.model.kpis[0], { text: '1,362원' })], origins: [Object.assign({}, FX.model.origins[0], { fetched_at: '2026-11-16T10:00:00' })] });
  const { page, db } = await fixture(t, { config: grid('1:1:1', 'wx 0 0 1 1', 'cw_44444444 0 1 1 1', 'ask 1 0 1 1', 'org 2 0 1 2'), custom: [fx], fresh: { cw_44444444: fresh } });
  await page.waitForFunction(() => { const v = document.querySelector('#dash .wg[data-wg="cw_44444444"] .hw-kt .v'); return v && v.textContent === '1,362원'; });
  // 위젯 에이전트가 고정 숫자 카드로 다시 저장했다(가져온 출처 없음) / the widget agent saved it again as a fixed-number card (no fetched origins)
  db.custom = [Object.assign({}, fx, { name: '목표', updated_at: '2026-11-16T10:30:00', model: { v: 2, title: '목표', chart: null, theme: null, insight: '', insight_wait: false,
    needs_data: false, empty: false, kpis: [{ id: 'k1', label: '연간 목표', unit: '건', note: '', pending: false, text: '1,200건', manual: true, delta: null, period: '' }] } })];
  await page.evaluate(() => window.AI365_homeDash.reload());
  await page.waitForFunction(() => document.querySelector('#dash .wg[data-wg="cw_44444444"] .wg-head').textContent === '목표');
  assert.equal(await page.locator('#dash .wg[data-wg="cw_44444444"] .hw-kt .v').innerText(), '1,200건');
  // 내용이 같은 모델로 다시 읽으면 위젯을 다시 만들지 않는다(끄는 중인 위젯이 손에서 떨어지지 않게) / an equal model re-read keeps the element
  await page.evaluate(() => { window.__el = document.querySelector('#dash .wg[data-wg="cw_44444444"]'); });
  await page.evaluate(() => window.AI365_homeDash.reload());
  await page.waitForTimeout(200);
  assert.equal(await page.evaluate(() => window.__el === document.querySelector('#dash .wg[data-wg="cw_44444444"]')), true);
});

test('접근성: 이름은 보이는 글자 · title 에서(영어도), 덮개 = 위젯 이름 묶음, 키보드 초점은 막대 → [위젯 추가] → 서랍 → 톱니로 / accessibility: names come from text and titles (English too), covers are groups named after their widget, and keyboard focus moves sensibly', async t => {
  const { page } = await fixture(t, { lang: 'en', custom: [SALES] });
  await page.waitForFunction(() => document.getElementById('editBtnTx').textContent === 'Edit layout');
  assert.equal(await page.getByRole('button', { name: 'Edit layout' }).count(), 1);
  await page.focus('#editBtn');
  await page.keyboard.press('Enter');
  await page.waitForSelector('body.hd-edit #hdEbar');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'hdEbar');     // 톱니는 숨었다 → 막대로 / the gear hid, so the bar takes focus
  assert.equal(await page.getByRole('region', { name: 'Edit layout' }).count(), 1);
  assert.equal(await page.getByRole('radiogroup', { name: 'Base ratio' }).count(), 1);
  assert.equal(await page.getByRole('group', { name: 'Org Chart' }).getByRole('button', { name: 'Remove from Home' }).count(), 1);
  assert.equal(await page.getByRole('group', { name: "Today's Weather" }).getByRole('button').count(), 0);   // 날씨는 뺄 수 없다 / weather cannot leave
  await page.focus('#dash [data-hd-rm="org"]');
  await page.keyboard.press('Enter');                                                // ✕ → 위젯은 서랍으로, 초점은 [위젯 추가]로 / the widget goes to the drawer, focus to [Add widget]
  assert.equal(await page.evaluate(() => document.activeElement.dataset.hdAct), 'add');
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('#hdDrawer').isVisible(), true);
  assert.equal(await page.getByRole('button', { name: 'Delete widget' }).count(), 1);
  await page.focus('#hdDrawer [data-hd-put="org"]');
  await page.keyboard.press('Enter');                                                // [넣기] → 다시 그린 서랍 안에 초점 / focus stays in the redrawn drawer
  assert.equal(await page.evaluate(() => !!document.activeElement.closest('#hdDrawer')), true);
  await page.keyboard.press('Escape');                                               // 서랍 닫기 / close the drawer
  await page.keyboard.press('Escape');                                               // [취소] = 확인 창(바꾼 것이 있다) / cancel asks (there are changes)
  await page.waitForSelector('#hdOv');
  await page.keyboard.press('Enter');                                                // 확인 창은 확인 단추에 초점 / the dialog focuses its button
  await page.waitForFunction(() => !document.body.classList.contains('hd-edit'));
  assert.equal(await page.evaluate(() => document.activeElement.id), 'editBtn');     // 다시 보이는 톱니로 / back to the gear
});

test('옛 저장본을 옮기는 중에 톱니를 누르면 옮긴 뒤에 열린다(기본 배치로 열어 덮어쓰지 않게) / the gear pressed while the old layout moves opens editing afterwards, from the moved layout', async t => {
  const legacy = { cols: { l: ['tok', 'wx', 'cal'], m: ['ask', 'coll', 'sc', 'att'], r: ['gwb', 'org'] }, hidden: ['att'] };
  const { page, db } = await fixture(t, { saved: false, legacy, holdPut: true });
  while (!db.heldPuts.length) await page.waitForTimeout(20);
  await page.click('#editBtn');
  await page.waitForTimeout(200);
  assert.equal(await page.locator('body.hd-edit').count(), 0);                       // 아직 열리지 않는다 / not yet
  db.holdPut = false;
  db.heldPuts.splice(0).forEach(send => send());
  await page.waitForSelector('body.hd-edit #hdEbar');
  assert.deepEqual(await draftRows(page), ['tok 0 0 1 1', 'ask 1 0 1 1', 'gwb 2 0 1 2', 'wx 0 1 1 1', 'coll 1 1 1 1', 'cal 0 2 1 2', 'sc 1 2 1 1', 'org 2 2 1 2']);
  assert.equal(await page.locator('#toast.show').count(), 0);
});

/* ── 2026-11-20 위젯 에이전트 패널과 함께(docs/widget-agent.md 14절): 만든 위젯 머리의 아이콘 · 그 자리에 그리기(preview) · 새 위젯 자리(ghost) ·
   새 위젯 놓기(place) · 강조(focus) · 편집 중인지(editing). 패널 자체는 tests/test_widget_agent_ui.cjs 가 본다
   working with the widget agent panel (2026-11-20, section 14): the icon on made widgets, drawing in place, the new-widget spot, placing a new
   widget, the mark and whether layout editing is on. The panel itself is covered by tests/test_widget_agent_ui.cjs ── */
const spot = loc => loc.evaluate(el => [el.style.gridColumn, el.style.gridRow]);

test('만든 위젯 머리 = 이름 + [위젯 에이전트로 고치기] 아이콘(기본 위젯에는 없다), 누르면 AI365_widgetAgent.open(키), 배치 편집 중에는 열지 않는다 / a made widget\'s head = the name plus an [Edit with the Widget Agent] icon (none on built-ins); a click calls AI365_widgetAgent.open(key), never while editing', async t => {
  const { page } = await fixture(t, { config: grid('1:1:1', 'wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'cw_11111111 0 1 1 2', 'cw_22222222 1 1 1 1'), custom: [SALES, APPROVAL] });
  const head = page.locator('#dash > .wg[data-wg="cw_11111111"] > .wg-head');
  assert.deepEqual(await head.locator(':scope > *').evaluateAll(e => e.map(x => [x.className, x.hasAttribute('data-i18n-skip')])), [['hd-nm', true], ['sp', false], ['hd-btn hd-wa', false]]);
  assert.deepEqual([await head.innerText(), await head.locator('[data-hd-wa]').getAttribute('title'), await head.locator('[data-hd-wa]').getAttribute('type')],
    ['지점별 매출', '위젯 에이전트로 고치기', 'button']);
  assert.deepEqual(await page.locator('#dash [data-hd-wa]').evaluateAll(b => b.map(x => x.dataset.hdWa)), ['cw_11111111', 'cw_22222222']);
  assert.equal(await page.locator('#dash > .wg:not(.hd-cw) [data-hd-wa]').count(), 0);
  await page.evaluate(() => { window.__opened = []; window.AI365_widgetAgent.open = k => window.__opened.push(k); });
  await page.click('#dash > .wg[data-wg="cw_22222222"] [data-hd-wa]');
  assert.deepEqual(await page.evaluate(() => window.__opened), ['cw_22222222']);
  // 패널이 열려 있는 동안(body.wa-open, 2026-11-21): 만든 위젯 카드 어디를 눌러도 open(키) — 닫혀 있으면 · 지금 고치는 위젯 · 기본 위젯은 아니다
  // while the panel is open (body.wa-open, 2026-11-21) a click anywhere on a made widget card calls open(key); not while closed, nor on the edited widget or a built-in
  await page.click('#dash > .wg[data-wg="cw_11111111"] .hd-nm');
  assert.deepEqual(await page.evaluate(() => window.__opened), ['cw_22222222']);
  await page.evaluate(() => { document.body.classList.add('wa-open'); window.AI365_homeDash.focus('cw_22222222'); });
  await page.click('#dash > .wg[data-wg="cw_11111111"] .hd-nm');
  await page.click('#dash > .wg[data-wg="cw_22222222"] .hd-nm');
  await page.click('#dash > .wg[data-wg="wx"] .wg-head');
  assert.deepEqual(await page.evaluate(() => window.__opened), ['cw_22222222', 'cw_11111111']);
  await page.evaluate(() => { document.body.classList.remove('wa-open'); window.AI365_homeDash.focus(''); });
  // 배치 편집 중: 위젯 안은 눌리지 않고(덮개), 눌린 것으로 쳐도 열지 않는다 / while editing the inside is inert (covers), and even a dispatched click opens nothing
  await openEdit(page);
  assert.equal(await page.evaluate(() => !!document.querySelector('#dash > .wg[data-wg="cw_11111111"] [data-hd-wa]').closest('[inert]')), true);
  await page.evaluate(() => document.querySelector('#dash > .wg[data-wg="cw_11111111"] [data-hd-wa]').dispatchEvent(new MouseEvent('click', { bubbles: true })));
  assert.deepEqual(await page.evaluate(() => window.__opened), ['cw_22222222', 'cw_11111111']);   // 더 열리지 않았다 / nothing more opened
  await page.click('[data-hd-act="cancel"]');
  // 영어: 아이콘 이름 · 머리줄 아이콘은 사전이, 위젯 이름은 그대로 / English: the dictionary names the icons; the widget name stays
  const en = await fixture(t, { lang: 'en', config: grid('1:1:1', 'wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'cw_11111111 0 1 1 2'), custom: [SALES] });
  await en.page.waitForFunction(() => document.querySelector('#dash [data-hd-wa]').title === 'Edit with the Widget Agent' && document.getElementById('waBtn').title === 'Widget Agent');
  assert.equal(await en.page.locator('#dash > .wg[data-wg="cw_11111111"] .hd-nm').innerText(), '지점별 매출');
});

test('그 자리에 그리기(preview · previewOf): 놓인 만든 위젯만, 한 번에 하나, 없애면 저장된 모습으로, 그동안 온 새 내용(/data)은 그 위에 그리지 않는다 / drawing in place: placed made widgets only, one at a time, cleared back to the stored drawing; fresh content arriving meanwhile (/data) is not painted over it', async t => {
  const fresh = Object.assign({}, FX.model, { kpis: [Object.assign({}, FX.model.kpis[0], { text: '1,362원' })], origins: [Object.assign({}, FX.model.origins[0], { fetched_at: '2026-11-16T10:00:00' })] });
  const { page, db } = await fixture(t, { config: grid('1:1:1', 'wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'cw_22222222 0 1 1 1', 'cw_44444444 1 1 1 1'), custom: [APPROVAL, FX, SALES],
    fresh: { cw_44444444: fresh }, holdData: true });
  while (!db.heldData.length) await page.waitForTimeout(20);                          // 환율 위젯의 새 내용 답을 붙잡았다 / the rate widget's fresh-content answer is held
  const DRAFT = { v: 2, title: '초안', empty: false, needs_data: false, insight: '', theme: null, chart: null,
    kpis: [{ id: 'k1', label: '초안 카드', text: '7건', unit: '건', note: '', pending: false, manual: true, delta: null, period: '' }] };
  const ap = page.locator('#dash > .wg[data-wg="cw_22222222"]'), fx = page.locator('#dash > .wg[data-wg="cw_44444444"]');
  const pv = (k, m, n) => page.evaluate(([k, m, n]) => window.AI365_homeDash.preview(k, m, n), [k, m, n]);
  const pvOf = k => page.evaluate(k => window.AI365_homeDash.previewOf(k), k);
  assert.equal(await pvOf('cw_22222222'), null);
  assert.equal(await pv('cw_22222222', DRAFT, '미리 이름'), true);
  assert.deepEqual([await ap.locator('.hd-nm').innerText(), await ap.locator('.hw-kt .v').allInnerTexts(), await pvOf('cw_22222222')], ['미리 이름', ['7건'], DRAFT]);
  assert.equal(await pv('cw_22222222', DRAFT), true);                                 // 이름이 없으면 위젯 이름 / without a name, the widget's own
  assert.equal(await ap.locator('.hd-nm').innerText(), '결재 현황');
  // 한 번에 하나: 다른 위젯을 그리면 앞의 것은 저장된 모습으로 / one at a time: drawing another restores the first
  assert.equal(await pv('cw_44444444', DRAFT, '환율 초안'), true);
  assert.deepEqual([await ap.locator('.hd-nm').innerText(), await ap.locator('.hw-kt .v').allInnerTexts(), await pvOf('cw_22222222')], ['결재 현황', ['12건', '31건'], null]);
  assert.deepEqual([await fx.locator('.hd-nm').innerText(), await fx.locator('.hw-kt .v').allInnerTexts()], ['환율 초안', ['7건']]);
  // 그동안 새 내용이 와도 그 위에 그리지 않는다(모델만 바꿔 둔다) / fresh content meanwhile is kept, not painted over
  db.heldData.splice(0).forEach(send => send());
  await page.waitForFunction(() => JSON.parse(localStorage.getItem('ai365_home_dash_v5')).widgets.filter(w => w.key === 'cw_44444444')[0].model.kpis[0].text === '1,362원');
  assert.deepEqual([await fx.locator('.hd-nm').innerText(), await fx.locator('.hw-kt .v').allInnerTexts(), await pvOf('cw_44444444')], ['환율 초안', ['7건'], DRAFT]);
  // 없애면 저장된(그사이 새로 온) 모습으로 / clearing shows the stored drawing (the fresh one that came meanwhile)
  assert.equal(await pv('cw_44444444', null), true);
  assert.deepEqual([await fx.locator('.hd-nm').innerText(), await fx.locator('.hw-kt .v').allInnerTexts(), await pvOf('cw_44444444')], ['오늘 환율', ['1,362원'], null]);
  // 놓이지 않은 위젯 · 기본 위젯 · 없는 키는 그리지 않는다 / unplaced, built-in or unknown keys draw nothing
  for (const k of ['cw_11111111', 'wx', 'nope', '']) assert.equal(await pv(k, DRAFT, 'x'), false, k);
  assert.equal(await page.locator('#dash .hw-kt .v').filter({ hasText: /^7건$/ }).count(), 0);
});

test('새 위젯 자리(ghost · ghostOf): 빈 첫 자리의 점선 카드(3열 · 2열 · 1열마다 다시), 배치에는 없고, 배치 편집 중에는 숨고, ghost(null) 이면 치운다 / the new-widget spot: a dashed card at the first free spot (re-placed in three, two and one columns), not part of the layout, hidden while editing, removed by ghost(null)', async t => {
  const { page } = await fixture(t, { config: grid('1:1:1', 'wx 0 0 1 1', 'org 2 0 1 2', 'cal 0 1 1 2') });
  const M = { v: 2, title: '새 KPI', empty: false, needs_data: false, insight: '', theme: null, chart: null,
    kpis: [{ id: 'k1', label: '목표', text: '1,200건', unit: '건', note: '', pending: false, manual: true, delta: null, period: '' }] };
  const ghost = page.locator('#dash > .wg.hd-ghost');
  const put = (m, n, s) => page.evaluate(([m, n, s]) => window.AI365_homeDash.ghost(m, n, s), [m, n, s]);
  const cols = n => page.waitForFunction(n => getComputedStyle(document.getElementById('dash')).gridTemplateColumns.split(' ').length === n, n);
  assert.equal(await page.evaluate(() => window.AI365_homeDash.ghostOf()), null);
  assert.equal(await put(M, '새 KPI', { w: 1, h: 1 }), true);
  assert.deepEqual(await spot(ghost), ['2 / span 1', '1 / span 1']);                  // 빈 첫 자리 = 가운데 맨 위 / the first free spot = top middle
  assert.deepEqual([await ghost.locator('.hd-nm').innerText(), await ghost.locator('.hd-new').innerText(), await ghost.locator('.hw-kt .v').innerText()], ['새 KPI', '새 위젯', '1,200건']);
  assert.deepEqual([await ghost.getAttribute('data-wg'), await page.evaluate(() => window.AI365_homeDash.ghostOf())], [null, M]);   // 진짜 위젯이 아니다 / not a real widget
  assert.deepEqual(await placed(page), ['wx 0 0 1 1', 'org 2 0 1 2', 'cal 0 1 1 2']);
  assert.deepEqual(rowsOf((await page.evaluate(() => window.AI365_homeDash.state())).items), ['wx 0 0 1 1', 'org 2 0 1 2', 'cal 0 1 1 2']);   // 배치는 그대로 / the layout is untouched
  // 크기가 바뀌면 그 크기가 들어갈 첫 자리 / a new size takes the first spot it fits
  assert.equal(await put(M, '새 KPI', { w: 2, h: 1 }), true);
  assert.deepEqual(await spot(ghost), ['2 / span 2', '3 / span 1']);
  assert.equal(await page.locator('#dash > .wg.hd-ghost').count(), 1);                 // 카드는 하나 / one card
  // 좁은 화면: 2열 · 1열로 흘린 배치에서의 첫 자리(가로는 열 수까지) / narrow screens: the first spot in the two- and one-column flow (width capped)
  await page.setViewportSize({ width: 900, height: 1500 });
  await cols(2);
  assert.deepEqual(await spot(ghost), ['1 / span 2', '4 / span 1']);
  await put(M, '새 KPI', { w: 1, h: 1 });
  assert.deepEqual(await spot(ghost), ['2 / span 1', '3 / span 1']);
  await page.setViewportSize({ width: 560, height: 1500 });
  await cols(1);
  assert.deepEqual(await spot(ghost), ['1 / span 1', '6 / span 1']);
  await page.setViewportSize({ width: 1500, height: 1500 });
  await cols(3);
  assert.deepEqual(await spot(ghost), ['2 / span 1', '1 / span 1']);
  // 배치 편집 중에는 숨고(덮개도 없다), 닫으면 다시 / hidden while editing (no cover), back afterwards
  await openEdit(page);
  assert.deepEqual([await ghost.isVisible(), await ghost.locator('.hd-cover').count(), await page.locator('#dash .hd-cover').count()], [false, 0, 3]);
  await page.click('[data-hd-act="cancel"]');
  assert.equal(await ghost.isVisible(), true);
  // ghost(null) = 치운다 / ghost(null) removes it
  assert.equal(await put(null), false);
  assert.deepEqual([await page.locator('#dash .hd-ghost').count(), await page.evaluate(() => window.AI365_homeDash.ghostOf())], [0, null]);
});

test('새 위젯 홈에 놓기(place): 다시 읽고 빈 첫 자리에 처음 크기로 놓아 저장 · 다시 읽기, 이미 놓였거나 모르는 위젯 · 배치 편집 중(editing)이면 놓지 않는다 / placing a new widget: re-read, put it at the first free spot at its first size, save and read again; nothing for a placed or unknown widget or while editing', async t => {
  const { page, db } = await fixture(t, { custom: [SALES, APPROVAL] });
  const place = k => page.evaluate(k => window.AI365_homeDash.place(k), k);
  assert.equal(await page.evaluate(() => window.AI365_homeDash.editing()), false);
  const gets = db.gets;
  assert.equal(await place('cw_11111111'), true);
  assert.equal(db.gets, gets + 2);                                                      // 놓기 전 · 후로 읽는다 / read before and after
  assert.equal(db.puts.length, 1);
  assert.deepEqual(rowsOf(db.puts[0].items), DEFAULT_ROWS.concat(['cw_11111111 0 4 1 2']));   // 나머지는 그대로, 빈 첫 자리 · 처음 크기(차트 = 1 × 2) / the rest stay; the first free spot at the first size
  assert.deepEqual((await placed(page)).slice(-1), ['cw_11111111 0 4 1 2']);
  assert.deepEqual([await place('cw_11111111'), await place('nope'), db.puts.length], [false, false, 1]);   // 이미 놓였다 · 모른다 / already placed, unknown
  // 배치 편집 중에는 놓지 않는다(서랍에 남는다) / never while editing (it stays in the drawer)
  await openEdit(page);
  assert.equal(await page.evaluate(() => window.AI365_homeDash.editing()), true);
  assert.equal(await place('cw_22222222'), false);
  assert.equal(db.puts.length, 1);
  assert.deepEqual((await page.evaluate(() => window.AI365_homeDash.draft())).unused, ['cw_22222222']);
  await page.click('[data-hd-act="cancel"]');
  assert.equal(await page.evaluate(() => window.AI365_homeDash.editing()), false);
  assert.equal(await place('cw_22222222'), true);
  assert.deepEqual(rowsOf(db.puts[1].items).slice(-1), ['cw_22222222 1 4 1 1']);
  assert.deepEqual((await placed(page)).slice(-2), ['cw_11111111 0 4 1 2', 'cw_22222222 1 4 1 1']);
});

test('고치는 위젯 강조(focus): 다시 읽어도 · 위젯이 새로 그려져도 남고, 기본 위젯은 강조하지 않으며, 놓이지 않은 위젯은 놓이면 그때, 빈 키면 풀린다 / marking the widget being edited: it survives a re-read and a rebuilt widget, built-ins are never marked, an unplaced one is marked once placed, an empty key clears it', async t => {
  const { page, db } = await fixture(t, { config: grid('1:1:1', 'wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'cw_11111111 0 1 1 2'), custom: [SALES, APPROVAL] });
  const focus = (k, s) => page.evaluate(([k, s]) => window.AI365_homeDash.focus(k, s), [k, s]);
  const marked = () => page.evaluate(() => [].map.call(document.querySelectorAll('#dash > .hd-wa-on'), el => el.dataset.wg));
  assert.deepEqual(await marked(), []);
  assert.equal(await focus('cw_11111111', true), true);
  assert.deepEqual(await marked(), ['cw_11111111']);
  await page.evaluate(() => window.AI365_homeDash.reload());
  assert.deepEqual(await marked(), ['cw_11111111']);
  // 정의가 바뀌어 위젯을 새로 그려도 남는다 / a changed definition rebuilds the widget and the mark stays
  db.custom = [Object.assign({}, SALES, { name: '지점 매출', updated_at: 'u2', model: Object.assign({}, SALES.model, { title: '지점 매출' }) }), APPROVAL];
  await page.evaluate(() => { window.__el = document.querySelector('#dash > .wg[data-wg="cw_11111111"]'); return window.AI365_homeDash.reload(); });
  assert.equal(await page.locator('#dash > .wg[data-wg="cw_11111111"] .hd-nm').innerText(), '지점 매출');
  assert.equal(await page.evaluate(() => window.__el === document.querySelector('#dash > .wg[data-wg="cw_11111111"]')), false);
  assert.deepEqual(await marked(), ['cw_11111111']);
  // 기본 위젯 · 놓이지 않은 위젯은 강조하지 않는다(놓이면 그때) / built-ins and unplaced widgets are not marked (an unplaced one once placed)
  assert.deepEqual([await focus('wx'), await marked()], [false, []]);
  assert.deepEqual([await focus('cw_22222222'), await marked()], [false, []]);
  assert.equal(await page.evaluate(() => window.AI365_homeDash.place('cw_22222222')), true);
  assert.deepEqual(await marked(), ['cw_22222222']);
  assert.deepEqual([await focus(''), await marked()], [false, []]);
});
