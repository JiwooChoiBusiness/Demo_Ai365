// 위젯 에이전트(2026-11-16, static/widget_agent.js · docs/widget-agent.md 9 · 13 · 14절). 2026-11-20 부터 머리줄 알약이 아니라 그룹웨어 에이전트
// 머리줄의 아이콘(#waBtn, 톱니 왼쪽) · 만든 위젯 머리의 아이콘으로 여는 오른쪽 패널(#waView, body.wa-open)이다. 홈은 그대로 보이고, 따로 된 미리보기 ·
// [저장]이 없다: 턴 · 되돌리기 · 기록 · 이름 · 크기 · 새로 가져오기가 바뀔 때마다 바로 저장해 홈에 반영하고(새 위젯은 빈 첫 자리에 놓는다),
// 찾는 동안의 초안 · 지난 모습 · 반영 전 작업본은 홈 격자의 그 위젯 자리에(아직 없는 위젯은 빈 첫 자리의 점선 카드로) 그린다. 패널 = 머리(이름 ·
// 내 위젯 · 새 위젯 · 되돌리기 · 닫기) · 탭(대화 · 정보 · 기록) + 홈에 반영된 상태 · 알림 줄(홈에 없음 · 지난 모습) · 대화 + 입력 카드. 같은 날 독립 검토 반영:
// 그 사이 지워진 위젯(PUT 404 · 배치 편집 서랍)은 다시 만들지 않고, 사람이 바뀌면(뷰애즈) 새 사람에게 아무것도 저장하지 않으며, 다시 시도는 답이 온 뒤에만 바꾼다.
// 진짜 홈 파일 + static/report_dash.js · home_dash.js · widget_agent.js · home-live.js 를 가짜 원점에서 띄우고, /api/home/* 는 상태를 들고 있는 작은
// 가짜 서버가 받는다(만든 · 고친 · 지운 위젯과 마지막 배치가 다음 읽기에 돌아온다, 위젯 에이전트 턴은 정해 둔 답을 차례로). 순수 함수는 그대로 부른다.
// The widget agent (2026-11-16; docs/widget-agent.md sections 9, 13 and 14). Since 2026-11-20 it is a right-hand panel (#waView, body.wa-open)
// opened from an icon in the groupware header (#waBtn, left of the gear) or the icon on a made widget, no longer a header pill. Home stays in
// view and there is no separate preview and no [Save]: every change (a turn, undo, history, rename, size, refresh) is saved and shown on Home at
// once (a new widget lands on the first free spot), while a running turn's draft, an earlier state or an unapplied working copy is drawn in the
// widget's own home cell (a widget not made yet is a dashed card at the first free spot). The panel = a head (name, my widgets, new, undo,
// close), tabs (chat, info, history) with the applied state, notice rows (not on Home, earlier state) and the chat with its input card.
// Same-day review fixes: a widget deleted meanwhile (PUT 404, the layout-editing drawer) is never re-created, a changed person (view-as) never
// gets anything saved, and a retry changes things only once its answer arrives.
// The real home file and the four scripts run on a fake origin; /api/home/* is a small stateful fake server (widgets made, updated or deleted
// and the last layout come back on the next read; agent turns return scripted answers in order). Pure functions are called as is.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test, before, after } = require('node:test');
const { chromium } = require('playwright');

const ROOT = path.join(__dirname, '..');
const HOME = path.join(ROOT, 'frontend', 'ai365-home.html');
const PURE = require(path.join(ROOT, 'static', 'widget_agent.js'));
const ORIGIN = 'http://ai365.test';
const MIME = { '.js': 'application/javascript', '.css': 'text/css', '.woff2': 'font/woff2' };
const INJECT = '<script src="/static/report_dash.js"></script><script src="/static/home_dash.js"></script><script src="/static/widget_agent.js"></script>' +
  '<script src="/static/home-live.js"></script></body>';
const BUILTIN = [['wx', '오늘의 날씨', true], ['cal', '일정'], ['tok', '토큰 사용량'], ['ask', 'AI 질문'], ['sc', '바로가기'], ['coll', '컬렉션'], ['att', '근태관리'], ['org', '조직도'],
  ['gwb', '그룹웨어 게시판']].map(b => ({ key: b[0], kind: 'builtin', name: b[1], locked: !!b[2] }));
// 홈 격자 배치(4단계 — app/home_widgets.DEFAULT_ITEMS): 빈 첫 자리 = 왼쪽 열 다섯째 줄(x 0 · y 4) / the home grid layout (the server's default items); first free spot = x 0, y 4
const ROWS = ['wx 0 0 1 1', 'cal 0 1 1 2', 'tok 0 3 1 1', 'ask 1 0 1 1', 'sc 1 1 1 1', 'coll 1 2 1 1', 'att 1 3 1 1', 'org 2 0 1 2', 'gwb 2 2 1 2'];
const layoutOf = rows => ({ layout_type: '1:1:1', items: rows.map(r => { const p = r.split(' '); return { widget_key: p[0], x: +p[1], y: +p[2], w: +p[3], h: +p[4] }; }) });
const rowsOf = items => items.map(i => (i.key || i.widget_key) + ' ' + i.x + ' ' + i.y + ' ' + i.w + ' ' + i.h);
// 넓은 창: 패널(460)을 열어도 홈 격자가 3열로 남는다 / a wide window: the home grid keeps three columns with the panel (460) open
const WIDE = 1800;

// 서버가 돌려줄 작업본 · 모델 / drafts and models the server returns
const PENDING = { id: 'k1', source: '', col: '', agg: '', label: 'KPI 1', unit: '', link: '', delta: '', value: null, note: '', pending: true };
const DRAFT1 = { v: 2, title: '새 위젯', source: null, chart: null, kpis: [PENDING], theme: null, insight: '' };
const MODEL1 = { v: 2, title: '새 위젯', kpis: [{ id: 'k1', label: 'KPI 1', unit: '', note: '', pending: true, text: '', manual: false, delta: null, period: '' }], chart: null, theme: null,
  insight: '', insight_wait: false, needs_data: true, empty: false };
const FIXED = { id: 'k1', source: '', col: '', agg: '', label: 'KPI 1', unit: '건', link: '', delta: '', value: 1200, note: '' };
const DRAFT2 = { v: 2, title: '새 위젯', source: null, chart: null, kpis: [FIXED], theme: null, insight: '' };
const MODEL2 = { v: 2, title: '새 위젯', kpis: [{ id: 'k1', label: 'KPI 1', unit: '건', note: '', pending: false, text: '1,200건', manual: true, delta: null, period: '' }], chart: null,
  theme: null, insight: '', insight_wait: false, needs_data: false, empty: false };
const ASK = { kind: 'data', question: '어떤 데이터를 연결할까요?', cards: ['KPI 1'], need: 'KPI 카드',
  hint: '무엇의 숫자인지 말씀해 주시면 사내 데이터 · 사내 문서 · 웹에서 찾아 넣습니다. 숫자를 직접 알려 주셔도 됩니다.' };
const TRACE1 = [{ agent: 'Visualize Agent', group: 'KPI 카드', tool: 'add_kpi', label: 'KPI 카드 추가', ok: true, detail: 'KPI 카드 k1 추가', say: "'KPI 1' KPI 카드를 만들었습니다." }];
const TURN1 = { widget: DRAFT1, model: MODEL1, reply: "'KPI 1' KPI 카드를 만들었습니다.", trace: TRACE1, ask: ASK };
const TURN2 = { widget: DRAFT2, model: MODEL2, reply: 'KPI 카드를 1,200건으로 바꿨습니다.', ask: null,
  trace: [{ agent: 'Visualize Agent', group: 'KPI 카드', tool: 'add_kpi', label: 'KPI 카드 추가', ok: true, detail: '', say: '', round: 1 },
    { agent: 'Visualize Agent', group: '정리', tool: 'set_insight', label: '인사이트 작성', ok: false, detail: '숫자는 직접 쓰지 말고 변수로 써 주세요', say: '', round: 2 }] };
const CHART_MODEL = { v: 2, title: '지점별 매출', kpis: [], theme: null, insight: '강남점이 가장 높습니다', insight_wait: false, needs_data: false, empty: false,
  chart: { type: 'bar', empty: false, filters: [], data: { kind: 'bar', x: ['강남점', '광주점'], series: [{ name: '매출', type: 'bar', axis: 0, values: [1200, 800] }], refs: [], rows: 2 },
    config: { id: 'c1', source: 's1', type: 'bar', title: '지점별 매출', subtitle: '', x: '지점', y: [{ col: '매출', agg: 'sum', name: '매출', type: 'bar', axis: 0 }], group: null,
      sort: { by: 'none', dir: 'desc' }, limit: null, stack: false, xLabel: '', yLabel: '', unit: '만원', ref_lines: [], filters: [],
      style: { palette: 'indigo', labels: false, smooth: true, fill: false, legend: 'bottom', rounded: true, grid: true }, insight: '', size: 'full' } } };
const SAVED = { key: 'cw_55555555', kind: 'custom', name: '지점별 매출', created_at: '2026-11-16T09:00:00', updated_at: '2026-11-16T09:30:00',
  spec: { v: 2, title: '지점별 매출', source: { tool: 'inline', columns: ['지점', '매출'], rows: [['강남점', 1200], ['광주점', 800]] }, chart: CHART_MODEL.chart.config, kpis: [], theme: null, insight: '{최고}가 가장 높습니다' },
  model: CHART_MODEL };
// 3단계: 웹에서 가져온 환율(고정 숫자 카드 + 뉴스 목록 + 출처) / phase 3: a rate fetched from the web (a fixed card, a news list, the origin)
const WEBREF = { kind: 'web', label: 'news.example', url: 'https://news.example/fx', page: null };
const NEWS = [{ title: '환율 1,350원 돌파', sub: '11/16 · news.example', url: 'https://news.example/fx' }];
const FX_DRAFT = { v: 2, title: '오늘 환율', kpis: [], chart: null, theme: null, insight: '', insight_wait: false, blocks: [], refs: [], origins: [], refresh: false,
  needs_data: false, empty: false, skeleton: { view: 'kpi', labels: ['원달러'], sources: ['사내 데이터'] } };
const FX_WIDGET = { v: 2, title: '오늘 환율', source: null, chart: null, theme: null, insight: '',
  kpis: [{ id: 'k1', source: '', col: '', agg: '', label: '원달러', unit: '원', link: '', delta: '', value: 1350.5, note: '11/16' }],
  blocks: [{ type: 'list', items: NEWS }],
  origins: [{ part: 'cards', kind: 'web', query: '오늘 원달러 환율', view: 'kpi', sql: '', sig: '', tables: [], refs: [WEBREF], fetched_at: '2026-11-16T10:00:00',
    cards: [{ id: 'k1', key: '1달러' }] }] };
const FX_MODEL = { v: 2, title: '오늘 환율', chart: null, theme: null, insight: '', insight_wait: false, needs_data: false, empty: false,
  kpis: [{ id: 'k1', label: '원달러', unit: '원', note: '11/16', pending: false, text: '1,350.5원', manual: true, delta: null, period: '' }],
  blocks: [{ type: 'list', items: NEWS }], refs: [WEBREF], origins: [{ kind: 'web', label: '웹 검색', fetched_at: '2026-11-16T10:00:00' }], refresh: true };
const FX_TRACE = { agent: 'Data Agent', group: '데이터', tool: 'fetch_data', label: '데이터 가져오기', ok: true, detail: '웹 검색에서 가져와 KPI 카드(으)로 넣음',
  say: '웹 검색에서 가져와 KPI 카드(으)로 넣었습니다.', round: 1 };
const FX_TURN = { widget: FX_WIDGET, model: FX_MODEL, reply: '오늘 환율을 넣었습니다.', ask: null, trace: [FX_TRACE] };
// 홈에 놓인 또 하나의 만든 위젯(웹 환율) / another made widget on Home (the web rate)
const FXW = { key: 'cw_66666666', kind: 'custom', name: '오늘 환율', created_at: '2026-11-16T09:00:00', updated_at: '2026-11-16T10:00:00', spec: FX_WIDGET, model: FX_MODEL };
// 스트림 진행(2026-11-19): 찾을 곳 → 라운드 → 사내 데이터(못 찾음) → 웹(실시간) → 쓴 갈래 → 도구 결과 / the progress stream of a turn
const FX_EVENTS = [['plan', { sources: ['data'], view: 'kpi', forced: false }], ['round', { no: 1, tools: [{ tool: 'fetch_data', label: '데이터 가져오기' }] }],
  ['stage', { source: 'data', label: '사내 데이터' }], ['draft', { model: FX_DRAFT }], ['branch', { source: 'data', label: '사내 데이터', ok: false, why: '사내 데이터에서 찾지 못했습니다' }],
  ['stage', { source: 'web', label: '웹 검색', fallback: true }],
  ['branch', { source: 'web', label: '웹 검색', ok: true, kind: 'numbers', count: 1, refs: [WEBREF], live: true }], ['picked', { source: 'web' }], ['tool', FX_TRACE]];
const sse = (kind, d) => 'event: ' + kind + '\ndata: ' + JSON.stringify(d) + '\n\n';
const TOOLS = [{ agent: 'Visualize Agent', groups: [{ group: '리포트', tools: [{ name: 'update_chart', label: '차트 수정', description: 'x' }] },
  { group: '기준선', tools: [{ name: 'add_reference_line', label: '기준선 추가', description: 'x' }] }] },
  { agent: 'Data Agent', groups: [{ group: '데이터', tools: [{ name: 'ask_data', label: '데이터 질문', description: 'x' }] }] }];
// 저장된 대화(예전 요청 한 번 + 그 전 모습 h1 = 1,200건 카드) / a saved conversation (one earlier request, plus h1 = the 1,200 card before it)
const OLD = { v: 1, label: 'turn:예전 요청', at: '2026-11-18T10:00:00',
  msgs: [{ role: 'user', text: '예전 요청' }, { role: 'agent', text: '예전 답', trace: [], changes: [{ k: 'title', v: '지점별 매출' }], beforeId: 'h1', q: '예전 요청',
    frame: { plan: null, cards: {}, order: [], picked: '', rounds: [{ no: 1, tools: [{ tool: 'rename_widget', label: '위젯 제목 변경' }] }],
      tools: [{ tool: 'rename_widget', label: '위젯 제목 변경', ok: true, detail: '', say: '바꿨어요', round: 1 }] } }],
  hist: [{ id: 'h1', label: 'new:', at: '2026-11-18T09:00:00', widget: DRAFT2 }] };

/* ── 순수 함수 / pure functions ── */
test('작업본 · 변경 여부 · 대화 기록 / drafts, dirtiness and history', () => {
  assert.deepEqual(PURE.waBlank(), { v: 2, title: '새 위젯', source: null, chart: null, kpis: [], theme: null, insight: '', blocks: [], origins: [] });
  assert.equal(PURE.waHasContent(PURE.waBlank()), false);
  assert.equal(PURE.waHasContent(DRAFT1), true);
  assert.equal(PURE.waHasContent(Object.assign(PURE.waBlank(), { blocks: [{ type: 'text', text: '연차 15일' }] })), true);   // 글/목록만으로도 / text or a list alone
  assert.equal(PURE.waDirty(PURE.waBlank(), null), false);                       // 빈 새 작업본은 저장할 것이 없다 / an empty new draft has nothing to save
  assert.equal(PURE.waDirty(Object.assign(PURE.waBlank(), { title: '이름만' }), null), true);
  assert.equal(PURE.waDirty(DRAFT1, null), true);
  assert.equal(PURE.waDirty(DRAFT1, JSON.stringify(DRAFT1)), false);
  assert.equal(PURE.waDirty(DRAFT2, JSON.stringify(DRAFT1)), true);
  const msgs = [{ role: 'user', text: 'a' }, { role: 'agent', text: 'b', trace: TRACE1, ask: ASK }, { role: 'agent', error: true, text: '오류' }, { role: 'agent', text: '  ' },
    { role: 'agent', stopped: true, text: '', q: 'x' }].concat(Array.from({ length: 12 }, (_, i) => ({ role: 'user', text: 'm' + i })));
  const h = PURE.waHistory(msgs);
  assert.equal(h.length, 10);
  assert.deepEqual(h[0], { role: 'user', text: 'm2', trace: [] });
  // 에이전트가 물었으면 그 질문도 기록에(빈 답이어도), 오류 · 멈춘 줄은 빼고 / the agent's question joins the history; error and stopped lines stay out
  assert.deepEqual(PURE.waHistory(msgs.slice(0, 5)), [{ role: 'user', text: 'a', trace: [] },
    { role: 'agent', text: 'b [질문] 어떤 데이터를 연결할까요? (KPI 1)', trace: [{ tool: 'add_kpi', ok: true }] }]);
  assert.deepEqual(PURE.waHistory([{ role: 'agent', text: '', trace: [], ask: { question: '어떤 매출 데이터를 쓸까요?', cards: [] } }]),
    [{ role: 'agent', text: '[질문] 어떤 매출 데이터를 쓸까요?', trace: [] }]);
  assert.equal(PURE.waEsc('<a href="x">\'</a>'), '&lt;a href=&quot;x&quot;&gt;&#39;&lt;/a&gt;');
  for (const k of ['update_chart', 'add_kpi', 'rename_widget', 'set_insight', 'fetch_data', 'ask_data']) assert.ok(PURE.EXAMPLES[k], k);
  assert.deepEqual(PURE.STARTERS, ['KPI 카드 위젯을 만들어줘', '오늘 원달러 환율 위젯을 만들어줘', '지점별 매출 차트 위젯을 만들어줘', '연차 규정 요약 위젯을 만들어줘']);
});

test('이벤트 스트림 읽기 / reading the event stream', () => {
  assert.deepEqual(PURE.waSseEvent('event: stage\ndata: {"label":"웹 검색"}'), { event: 'stage', data: { label: '웹 검색' } });
  assert.deepEqual(PURE.waSseEvent('data: {"a":1}'), { event: 'message', data: { a: 1 } });
  assert.deepEqual(PURE.waSseEvent('event: done\r\ndata: {"a":\r\ndata: 2}'), { event: 'done', data: { a: 2 } });   // 여러 줄 data · CRLF / multi-line data, CRLF
  for (const bad of ['', 'event: x', 'event: x\ndata: {oops', ': keep-alive']) assert.equal(PURE.waSseEvent(bad), null, bad);
  // 조각 경계: 끝나지 않은 이벤트는 다음 조각과 이어 붙인다 / chunk boundaries: an unfinished event waits for the next piece
  const one = PURE.waSseSplit(sse('stage', { label: '사내 데이터' }) + 'event: draft\ndata: {"mo');
  assert.deepEqual(one.events, [{ event: 'stage', data: { label: '사내 데이터' } }]);
  const two = PURE.waSseSplit(one.rest + 'del":1}\n\n');
  assert.deepEqual([two.events, two.rest], [[{ event: 'draft', data: { model: 1 } }], '']);
});

test('생각 과정 틀: 진행 이벤트 · trace 로 채우기 / the thinking frame from progress events and from a trace', () => {
  let f = PURE.waFrameEmpty();
  for (const [event, data] of FX_EVENTS) f = PURE.waFrame(f, { event, data });
  assert.deepEqual(f.plan, { sources: ['data'], view: 'kpi', forced: false });
  assert.deepEqual(f.order, ['data', 'web']);
  assert.deepEqual([f.cards.data.status, f.cards.web.status, !!f.cards.web.fallback, f.picks], ['fail', 'ok', true, ['web']]);
  assert.deepEqual(f.rounds, [{ no: 1, tools: [{ tool: 'fetch_data', label: '데이터 가져오기' }] }]);
  assert.deepEqual(f.tools.map(t => [t.tool, t.ok, t.round]), [['fetch_data', true, 1]]);
  // 모르는 곳 · 틀린 이벤트는 버린다, 이전 틀은 그대로 / unknown places and broken events are ignored; the previous frame is untouched
  const g = PURE.waFrame(f, { event: 'stage', data: { source: 'mail' } });
  assert.deepEqual(g, f);
  assert.notEqual(g, f);
  assert.deepEqual(PURE.waFrame(null, { event: 'picked', data: { source: null } }).picks, ['none']);
  // 한 턴에 두 번 가져오면 쓴 곳도 둘(독립 검토) / two fetches in a turn record two places (independent review)
  assert.deepEqual(PURE.waFrame(PURE.waFrame(null, { event: 'picked', data: { source: 'docs' } }), { event: 'picked', data: { source: 'web' } }).picks, ['docs', 'web']);
  assert.deepEqual(PURE.waFrame(null, { event: 'plan', data: null }), PURE.waFrameEmpty());
  // 진행 알림 없이 끝난 턴: trace 로 단계 · 도구를 채운다(round 없으면 1단계) / a turn without notices: stages and tools from the trace
  const t = PURE.waFrameFromTrace(null, TURN2.trace.concat([{ tool: 'rename_widget', label: '위젯 제목 변경', ok: true }]));
  assert.deepEqual(t.rounds.map(r => [r.no, r.tools.map(x => x.tool)]), [[1, ['add_kpi', 'rename_widget']], [2, ['set_insight']]]);
  assert.deepEqual(t.tools.map(x => [x.tool, x.ok]), [['add_kpi', true], ['set_insight', false], ['rename_widget', true]]);
  assert.equal(PURE.waFrameFromTrace(f, [{ tool: 'x' }]).tools.length, 1);   // 알림이 있었으면 그대로 / notices win
});

test('저장된 대화 다시 짓기: 모르는 곳 · 틀린 모양 · 위험한 주소는 버린다(저장된 XSS), 바뀌었는지(changed)는 남긴다 / rebuilding saved messages drops unknown places, bad shapes and unsafe links and keeps whether the widget changed', () => {
  const evil = 'web"><img src=x onerror=alert(1)>';
  const m = PURE.waCleanMsg({ role: 'agent', text: '답', src: 'mail', frame: { order: [evil, 'docs', 'docs', 'web'], picks: ['docs', evil],
    cards: { [evil]: { status: 'ok' }, docs: { status: 'ok', note: { refs: [{ label: 'a.pdf', url: 'javascript:alert(1)', page: '3' }, 'x', { label: 'b', url: 'https://x.test', page: 2.6 }] } }, web: 'bad' },
    rounds: 'x', tools: [null, { tool: 'rename_widget', ok: 1, round: '2' }] }, changes: [{ k: 'view', v: null }, { k: 'evil', v: 1 }, { k: 'title', v: { a: 1 } }],
    ask: { question: 7, cards: [1, 'KPI 1'] }, refs: 'x', trace: [{ tool: 'a', ok: true, round: 1 }, 5] });
  assert.deepEqual(m.frame.order, ['docs']);
  assert.deepEqual(m.frame.picks, ['docs']);
  assert.deepEqual(m.frame.cards.docs.note.refs, [{ kind: 'doc', label: 'a.pdf', page: null, url: '' }, { kind: 'doc', label: 'b', page: 3, url: 'https://x.test' }]);
  assert.deepEqual([m.frame.rounds, m.frame.tools.map(t => [t.tool, t.ok, t.round])], [[], [['rename_widget', true, 0]]]);
  assert.deepEqual(m.changes, [{ k: 'view', v: { chart: '', kpis: 0, text: false, list: 0 } }, { k: 'title', v: '' }]);
  assert.deepEqual([m.src, m.refs, m.ask.question, m.ask.cards, m.trace.length], ['auto', [], '', ['KPI 1'], 1]);
  assert.equal(PURE.waCleanMsg({ role: 'system', text: 'x' }), null);
  assert.equal(PURE.waCleanMsg('x'), null);
  assert.deepEqual(PURE.waCleanMsg({ role: 'user', text: 5 }), { role: 'user', text: '', at: '' });
  // changed(2026-11-20): '결과를 반영해 위젯을 고쳤습니다' 줄을 정한다. 예전 저장본은 beforeId 만 있었다 / changed drives the 'updated the widget' line; older saves only had beforeId
  assert.equal(m.changed, false);
  assert.deepEqual([{ changed: true }, { changed: false }, { beforeId: 'h1' }, { changed: false, beforeId: '' }].map(x => PURE.waCleanMsg(Object.assign({ role: 'agent', text: 'x' }, x)).changed),
    [true, false, true, false]);
  // 다시 시도에 쓰는 base(그 턴이 돈 기록) · blank(빈 위젯에서 돈 턴)도 남긴다(2026-11-20 검토) / base (the history entry a turn ran on) and blank (a turn on an empty widget) stay for retries
  assert.deepEqual([m.base, m.blank], ['', false]);
  const kept = PURE.waCleanMsg({ role: 'agent', text: 'x', error: true, q: 'y', base: 'h1', blank: 1 });
  assert.deepEqual([kept.base, kept.blank, kept.error, kept.q], ['h1', true, true, 'y']);
  assert.deepEqual([PURE.waCleanMsg({ role: 'agent', text: 'x', base: { evil: 1 } }).base, PURE.waCleanMsg({ role: 'agent', text: 'x', base: 'h'.repeat(90) }).base.length], ['', 40]);
});

test('바뀐 점 · 다음에 해 볼 것 · 위젯 정보 · 크기 · 기록 이름 · 저장본 · 폼 요청 / changes, suggestions, info, size, labels, payload, form requests', () => {
  assert.deepEqual(PURE.waChanges(PURE.waBlank(), FX_WIDGET), [{ k: 'title', v: '오늘 환율' }, { k: 'view', v: { chart: '', kpis: 1, text: false, list: 1 } },
    { k: 'origin', v: [{ kind: 'web', refs: 1, first: 'news.example' }] }]);
  assert.deepEqual(PURE.waChanges(DRAFT1, DRAFT2), [{ k: 'kpis', v: 1 }]);
  assert.deepEqual(PURE.waChanges(SAVED.spec, Object.assign({}, SAVED.spec, { insight: '', theme: { brand: '#112233' } })),
    [{ k: 'insight', v: 'cleared' }, { k: 'theme', v: '#112233' }]);
  assert.deepEqual(PURE.waChanges(FX_WIDGET, FX_WIDGET), []);
  // 다음에 해 볼 것: 데이터 질문이 먼저, 차트면 종류 · 기준선 · 강조, 글이면 카드 · 목록, 인사이트 없으면 인사이트 / suggestions per state
  assert.deepEqual(PURE.waNext(DRAFT1), []);
  assert.deepEqual(PURE.waNext(SAVED.spec).map(p => p[0]), ['선 차트로 바꿔줘', '평균선을 넣어줘', '가장 높은 곳을 강조해줘']);
  assert.deepEqual(PURE.waNext({ blocks: [{ type: 'text', text: 'x' }] }).map(p => p[1]), ['Pull the key numbers into KPI cards', 'Show it as a list too']);
  assert.deepEqual(PURE.waNext(FX_WIDGET).map(p => p[0]), ['글로도 요약해줘', '인사이트를 한 줄 써줘']);
  // 위젯 정보: 부분별 출처 · 가장 늦은 시각 · 새로 가져오는 종류 / widget info
  const info = PURE.waInfo(FX_WIDGET);
  assert.deepEqual(info, { rows: [{ part: 'cards', kind: 'web', refs: [{ label: 'news.example', page: null }], at: '2026-11-16T10:00:00', refresh: true }],
    latest: '2026-11-16T10:00:00', kinds: ['web'] });
  assert.deepEqual(PURE.waInfo({ chart: {}, origins: [{ part: 'source', kind: 'data', query: 'q', sql: '', refs: [], fetched_at: 'x' }] }).kinds, []);   // 서명 SQL 없는 데이터 / no SQL
  // 크기: 고른 크기 → 놓인 크기 → 처음 크기 / size: picked, placed, first
  assert.deepEqual(PURE.waSizeOf(SAVED.spec, null), { w: 1, h: 2, picked: false });
  assert.deepEqual(PURE.waSizeOf(DRAFT2, { x: 1, y: 0, w: 2, h: 1 }), { w: 2, h: 1, picked: false, placed: true });
  assert.deepEqual(PURE.waSizeOf(Object.assign({}, DRAFT2, { size: { w: 9, h: 0.4 } }), { w: 2, h: 1 }), { w: 3, h: 1, picked: true });
  assert.equal(PURE.waLabel('turn', '가'.repeat(100)).length, 80);
  // 저장본: fold 는 빼고, 넘치면 오래된 기록 → 대화 순으로 버린다 / the payload drops fold and trims history, then messages
  const big = { v: 2, title: 'x', blocks: [{ type: 'text', text: '가'.repeat(PURE.CHAT_BUDGET) }] };
  const pay = PURE.waChatPayload([{ role: 'user', text: 'a', fold: true }, { role: 'agent', text: 'b', fold: true }], [{ id: 'h1', label: 'turn:a', at: 't', widget: big, model: {} }], 'turn:b', 't2');
  assert.deepEqual(pay, { v: 1, msgs: [{ role: 'user', text: 'a' }, { role: 'agent', text: 'b' }], hist: [], label: 'turn:b', at: 't2' });
  assert.equal(PURE.waChatPayload(Array.from({ length: 70 }, (_, i) => ({ n: i })), [], '', '').msgs[0].n, 10);
  // 폼 요청: 적은 글이 먼저, 없으면 고른 곳 + 카드 이름 / the form request
  assert.equal(PURE.waAskMessage(ASK, 'web', '  이번 달 매출 ', false), '이번 달 매출');
  assert.equal(PURE.waAskMessage(ASK, 'docs', '', false), "사내 문서에서 'KPI 1' 카드에 맞는 데이터를 찾아 연결해줘");
  assert.equal(PURE.waAskMessage({ cards: ['A', 'B'] }, 'data', '', true), "Find data for the 'A', 'B' cards in company data and connect it");
  assert.equal(PURE.waAskMessage({ cards: [] }, 'web', '', false), '');
  assert.equal(PURE.waAskMessage(ASK, '', '', false), '');
  // 입력 카드의 [자동 ▾](자동 · 사내 · 외부) + 리소스 센터 → source / the input card's scope plus the resource center → source
  assert.deepEqual([PURE.waSourceOf('auto', ['docs']), PURE.waSourceOf('web', []), PURE.waSourceOf('internal', []), PURE.waSourceOf('internal', ['docs']),
    PURE.waSourceOf('internal', ['data', 'docs']), PURE.waSourceOf('internal', ['x'])], ['auto', 'web', 'internal', 'docs', 'internal', 'internal']);
});

/* ── 화면 / screen ── */
let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

// 가짜 서버가 위젯 정의로 그리는 모델: 아는 정의(정해 둔 값 · 턴 답 · 내 위젯)와 내용이 같으면 그 모델, 모르면 MODEL2. 제목 · 고른 크기는 정의를 따른다
// the model the fake server draws for a definition: the model of a known one with the same content (fixed values, turn answers, my widgets),
// else MODEL2; the title and a picked size follow the definition
const KNOWN = [[DRAFT1, MODEL1], [DRAFT2, MODEL2], [FX_WIDGET, FX_MODEL], [SAVED.spec, CHART_MODEL]];
const bare = s => JSON.stringify(Object.assign({}, s, { title: '', size: null }));
function modelFor(db, spec) {
  const hit = db.known.filter(p => bare(p[0]) === bare(spec))[0];
  const m = Object.assign({}, hit ? hit[1] : MODEL2, { title: spec.title });
  if (spec.size) m.size = spec.size;
  return m;
}
// 홈이 받는 만든 위젯 = 서버(app/home_widgets)처럼 정의 없이 모델 · 크기(고른 크기 → 차트면 1 × 2 → 1 × 1, 1 ~ 3 칸)
// a made widget as the home receives it, like the server: no definition, the model and a size (picked, else 1 × 2 with a chart, else 1 × 1; 1 to 3 cells)
function homeRow(w) {
  const p = w.model && w.model.size, fit = n => Math.min(3, Math.max(1, n)), chart = !!(w.model && w.model.chart && w.model.chart.type !== 'kpi');
  const size = p && Number.isInteger(p.w) && Number.isInteger(p.h) ? { w: fit(p.w), h: fit(p.h) } : { w: 1, h: chart ? 2 : 1 };
  return { key: w.key, kind: 'custom', name: w.name, model: w.model, size: Object.assign(size, { min_w: 1, max_w: 3, min_h: 1, max_h: 3 }),
    created_at: w.created_at, updated_at: w.updated_at };
}

// 가짜 서버 + 홈. opts: turns(차례로 돌려줄 턴 답, {status, body} · body · {events, done}), mine(내 위젯), chats(키 → 대화 저장본), layout(배치 줄),
// lang, width(창 너비), holdTurn(턴 답을 붙잡아 둔다), holdChat(대화 복원 답), refresh(지금 새로 가져오기 답), failSave(위젯 저장이 실패한다 —
// db.failSave 로 도중에 바꾼다), failDash(배치 저장이 실패한다 — db.failDash), holdSave(위젯 저장 답을 db.heldSaves 에 붙잡아 둔다), holdDash(배치 저장
// 답을 db.heldDash 에). 서버는 상태를 들고 있다: 만든(POST) · 고친(PUT) · 지운(DELETE) 위젯과 마지막으로 저장한 배치가 다음 읽기에 돌아온다. 만든 위젯
// 키는 성공한 만들기 차례대로 cw_99990001, cw_99990002 …, 고친 시각은 11:15, 11:16 …(PUT 차례)
// fake server + the home. opts: turns, mine, chats, layout rows, lang, width, holdTurn, holdChat, refresh (the refresh-now answer), failSave
// (widget saves fail; db.failSave toggles it later), failDash (layout saves fail; db.failDash), holdSave (widget save answers wait in db.heldSaves),
// holdDash (layout save answers wait in db.heldDash). The server is stateful: widgets made, updated or deleted and the last saved layout come back
// on the next read. New keys follow successful creations (cw_99990001, …) and updates are stamped 11:15, 11:16, … in PUT order
async function fixture(t, opts) {
  opts = opts || {};
  const db = { turns: (opts.turns || []).slice(), turnBodies: [], posts: [], puts: [], deletes: [], gets: 0, mineGets: 0, made: 0, known: KNOWN.slice(),
    mine: JSON.parse(JSON.stringify(opts.mine || [])), layout: layoutOf(opts.layout || ROWS), held: [], hold: !!opts.holdTurn,
    chats: Object.assign({}, opts.chats || {}), chatGets: [], chatPuts: [], models: [], refreshes: [], dashPuts: [], holdChat: !!opts.holdChat, heldChat: [],
    failSave: !!opts.failSave, failDash: !!opts.failDash, holdSave: !!opts.holdSave, heldSaves: [], holdDash: !!opts.holdDash, heldDash: [] };
  db.mine.forEach(w => db.known.push([w.spec, w.model]));
  if (opts.refresh && opts.refresh.widget) db.known.push([opts.refresh.widget, opts.refresh.model]);
  const page = await browser.newPage({ viewport: { width: opts.width || 1500, height: 900 }, reducedMotion: 'reduce' });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  t.after(async () => { await page.close(); assert.deepEqual(errors, []); });
  await page.route('**/*', route => {
    const req = route.request(), u = new URL(req.url());
    const json = (d, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(d) });
    if (u.origin !== ORIGIN) return json({});
    if (u.pathname === '/home') {
      const html = fs.readFileSync(HOME, 'utf8').replace(/<head>/, '<head><script src="/static/kst.js"></script>').replace('</body>', INJECT);
      return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: html });
    }
    if (u.pathname.startsWith('/static/')) {
      const f = path.join(ROOT, u.pathname);
      return fs.existsSync(f) ? route.fulfill({ status: 200, contentType: MIME[path.extname(f)] || 'application/octet-stream', body: fs.readFileSync(f) }) : route.fulfill({ status: 404, body: '' });
    }
    if (u.pathname === '/api/home/dashboard' && req.method() === 'PUT') {
      const body = JSON.parse(req.postData());
      db.dashPuts.push(body);
      const answer = () => {
        if (db.failDash) return json({ detail: '배치를 저장하지 못했습니다' }, 503);
        db.layout = { layout_type: body.layout_type, items: body.items };
        return json(Object.assign({ saved: true }, JSON.parse(JSON.stringify(db.layout))));
      };
      if (db.holdDash) { db.heldDash.push(answer); return undefined; }
      return answer();
    }
    if (u.pathname === '/api/home/dashboard') {
      db.gets++;
      return json({ layout_options: [], config: Object.assign({ saved: true }, JSON.parse(JSON.stringify(db.layout))), widgets: BUILTIN.concat(db.mine.map(homeRow)) });
    }
    if (u.pathname === '/api/home/agent/turn/stream') {
      // = 서버의 스트림 턴: 본문이 틀리면 422 JSON, 그 밖의 실패는 error 이벤트, 성공은 (진행 이벤트 …) + done
      // = the server's stream turn: a wrong body is a 422 JSON, other failures an error event, success (progress events …) plus done
      db.turnBodies.push(JSON.parse(req.postData()));
      const next = db.turns.shift() || { status: 503, body: { detail: '위젯 에이전트가 지금 응답하지 않습니다. 잠시 뒤 다시 시도해 주세요' } };
      const done = next.status || next.done === null ? null : (next.done || next);
      if (done && done.widget && done.model) db.known.push([done.widget, done.model]);   // 서버가 그 정의의 모델을 안다 / the server knows that definition's model
      const stream = body => route.fulfill({ status: 200, contentType: 'text/event-stream', body: body });
      const send = () => (next.status === 422 ? json(next.body, 422)
        : next.status ? stream(sse('error', { status: next.status, detail: next.body.detail }))
          : stream((next.events || []).map(e => sse(e[0], e[1])).join('') + (done ? sse('done', done) : '')));
      if (db.hold) { db.held.push(send); return undefined; }
      return send();
    }
    if (u.pathname === '/api/home/agent/tools') return json({ tree: TOOLS });
    const chat = u.pathname.match(/^\/api\/home\/agent\/chat\/([^/]+)$/);
    if (chat && req.method() === 'GET') {
      db.chatGets.push(chat[1]);
      const answer = () => (db.chatFail ? json({ detail: '오류' }, 500) : json({ key: chat[1], chat: db.chats[chat[1]] || null, updated_at: '' }));
      if (db.holdChat) { db.heldChat.push(answer); return undefined; }
      return answer();
    }
    if (chat && req.method() === 'PUT') { const body = JSON.parse(req.postData()); db.chatPuts.push({ key: chat[1], body: body }); db.chats[chat[1]] = body.chat; return json({ key: chat[1], updated_at: '2026-11-19T10:00:00' }); }
    if (u.pathname === '/api/home/agent/model') {
      const body = JSON.parse(req.postData());
      db.models.push(body);
      return json({ widget: body.widget, model: modelFor(db, body.widget) });
    }
    if (u.pathname === '/api/home/agent/refresh') { const body = JSON.parse(req.postData()); db.refreshes.push(body); return json(opts.refresh || { changed: false }); }
    if (u.pathname === '/api/home/widgets' && req.method() === 'GET') { db.mineGets++; return json({ widgets: db.mine }); }
    if (u.pathname === '/api/home/widgets' && req.method() === 'POST') {
      const body = JSON.parse(req.postData());
      db.posts.push(body);
      const answer = () => {
        if (db.failSave) return json({}, 500);
        const w = { key: 'cw_9999000' + (++db.made), kind: 'custom', name: body.spec.title, spec: body.spec, model: modelFor(db, body.spec),
          created_at: '2026-11-16T10:00:00', updated_at: '2026-11-16T10:00:00' };
        db.mine.push(w);
        return json(w);
      };
      if (db.holdSave) { db.heldSaves.push(answer); return undefined; }
      return answer();
    }
    const one = u.pathname.match(/^\/api\/home\/widgets\/([^/]+)$/);
    if (one && req.method() === 'PUT') {
      const body = JSON.parse(req.postData());
      db.puts.push({ key: one[1], body: body });
      const at = '2026-11-16T11:' + (14 + db.puts.length) + ':00';
      const answer = () => {
        if (db.failSave) return json({}, 500);
        const w = db.mine.filter(x => x.key === one[1])[0];
        if (!w) return json({ detail: '존재하지 않는 위젯입니다' }, 404);
        Object.assign(w, { name: body.spec.title, spec: body.spec, model: modelFor(db, body.spec), updated_at: at });
        return json(w);
      };
      if (db.holdSave) { db.heldSaves.push(answer); return undefined; }
      return answer();
    }
    if (one && req.method() === 'DELETE') {
      // = 서버: 위젯 · 그 대화를 지우고 저장된 배치에서도 뺀다, 이미 없으면 404 / the server drops the widget, its conversation and its spot; 404 when already gone
      db.deletes.push({ key: one[1], who: u.searchParams.get('acting_user_id') });
      const had = db.mine.some(x => x.key === one[1]);
      db.mine = db.mine.filter(x => x.key !== one[1]);
      db.layout.items = db.layout.items.filter(i => i.widget_key !== one[1]);
      delete db.chats[one[1]];
      return had ? json({ ok: true }) : json({ detail: '존재하지 않는 위젯입니다' }, 404);
    }
    if (u.pathname === '/api/collections') return json({ collections: [] });
    return json({});
  });
  await page.addInitScript(l => { try { localStorage.setItem('ai365_lang', l); } catch (e) {} }, opts.lang || 'ko');
  await page.goto(ORIGIN + '/home?entry=tab');
  await page.waitForFunction(() => window.AI365_homeDash && window.AI365_homeDash.state() && window.AI365_widgetAgent);
  return { page, db };
}
// 그룹웨어 머리줄의 아이콘(톱니 왼쪽)으로 패널을 연다 / opens the panel from the groupware header icon (left of the gear)
async function openAgent(page) { await page.click('#waBtn'); await page.waitForSelector('#waView'); }
const state = page => page.evaluate(() => window.AI365_widgetAgent.state());
// 하던 일(턴 · 저장 · 홈에 놓기)이 다 끝날 때까지 / until the work (turn, save, placing on Home) is over
const idle = page => page.waitForFunction(() => !window.AI365_widgetAgent.state().busy);
// 홈 격자의 그 위젯 칸 / the widget's cell on the home grid
const cell = (page, key) => page.locator('#dash > .wg[data-wg="' + key + '"]');
const spot = loc => loc.evaluate(el => [el.style.gridColumn, el.style.gridRow]);
const tab = (page, name) => page.click('[data-wa-tab="' + name + '"]');
const acts = loc => loc.evaluateAll(b => b.map(x => x.dataset.waAct));
// 가짜 서버 쪽 기록이 맞을 때까지 기다린다(최대 3초) / waits until the fake server's record matches (3 s at most)
async function until(fn) {
  for (let i = 0; i < 60; i++) { if (fn()) return; await new Promise(r => setTimeout(r, 50)); }
  assert.fail('기다린 조건이 오지 않았습니다 / the awaited condition never came');
}
async function send(page, text) {
  await page.fill('#waIn', text);
  await page.press('#waIn', 'Enter');
  await idle(page);
}
// 조각조각 오는 스트림: 이 쪽의 fetch 가 테스트가 쥔 ReadableStream 을 돌려준다(가로채기는 한 번에 보내므로). 멈추기(signal)도 따른다
// a stream arriving in pieces: the page's fetch hands back a ReadableStream the test controls (route interception sends a body at once); it honours stop (signal)
async function liveStream(page) {
  await page.evaluate(() => {
    const orig = window.fetch;
    window.__sse = { ctrl: null, bodies: [], aborted: 0 };
    window.fetch = function (url, init) {
      if (String(url).indexOf('/api/home/agent/turn/stream') < 0) return orig.apply(this, arguments);
      window.__sse.bodies.push(JSON.parse(init.body));
      const body = new ReadableStream({ start(c) { window.__sse.ctrl = c; } });
      if (init.signal) init.signal.addEventListener('abort', () => { window.__sse.aborted++; try { window.__sse.ctrl.error(new DOMException('Aborted', 'AbortError')); } catch (e) {} });
      return Promise.resolve(new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }));
    };
  });
  const push = s => page.evaluate(s => window.__sse.ctrl.enqueue(new TextEncoder().encode(s)), s);
  return {
    push: push,
    // 이벤트 경계를 일부러 조각 사이에 걸친다 / event boundaries deliberately straddle the pieces
    write: async s => { const cut = Math.floor(s.length / 2); await push(s.slice(0, cut)); await push(s.slice(cut)); },
    end: async s => { if (s) await push(s); await page.evaluate(() => window.__sse.ctrl.close()); },
  };
}

test('톱니 왼쪽 아이콘 = 오른쪽 패널(알약은 셋): 홈은 그대로 보이고, 머리 아이콘 · 탭 · 첫 화면 · 입력 카드 · 정보 · 기록, 아이콘 · [닫기]로 여닫는다 / the icon left of the gear opens a right panel (three pills remain): Home stays in view; head icons, tabs, first screen, input card, info and history; the icon and [Close] toggle it', async t => {
  const { page } = await fixture(t);
  // 위젯 에이전트는 알약이 아니다(2026-11-20) / the widget agent is no longer a pill
  assert.deepEqual(await page.locator('#agentSeg .seg-btn').allInnerTexts(), ['그룹웨어 에이전트', '전자결재', '보안 에이전트']);
  assert.deepEqual(await page.evaluate(() => [].map.call(document.querySelectorAll('#agentSeg .seg-btn'), b => b.dataset.seg)), ['gw', 'eapp', 'sec']);
  assert.equal(await page.evaluate(() => document.getElementById('waBtn').nextElementSibling.id), 'editBtn');   // 톱니 바로 왼쪽 / right before the gear
  assert.deepEqual([await page.getAttribute('#waBtn', 'title'), await page.getAttribute('#waBtn', 'aria-pressed'), await page.locator('#waBtn.on').count()], ['위젯 에이전트', 'false', 0]);
  assert.equal(await page.locator('#waView').count(), 0);                 // 처음 열 때 만든다 / built on the first open
  await openAgent(page);
  assert.deepEqual([await page.locator('body.wa-open').count(), await page.locator('#waBtn.on').count(), await page.getAttribute('#waBtn', 'aria-pressed'), (await state(page)).shown],
    [1, 1, 'true', true]);
  // 홈은 그대로(제목 · 격자 · 톱니), 패널 너비만큼 좁아진다 / Home stays (title, grid, gear) and narrows by the panel width
  assert.equal(await page.locator('#homeTitle').innerText(), '그룹웨어 에이전트');
  for (const sel of ['#dash', '#editBtn', '#dash > .wg[data-wg="wx"]']) assert.equal(await page.locator(sel).isVisible(), true, sel);
  // 위 막대 바로 아래부터 바닥까지 오른쪽에 붙는다 / docked on the right from right under the top bar to the bottom
  const geo = await page.evaluate(() => { const r = document.getElementById('waView').getBoundingClientRect(), h = document.querySelector('.hero'), d = document.getElementById('dash').getBoundingClientRect(),
    bar = document.querySelector('#viewHome .topbar').getBoundingClientRect();
    return [Math.round(r.left), Math.round(r.right), Math.round(r.top) === Math.round(bar.bottom), Math.round(r.bottom), getComputedStyle(h).marginRight, d.right <= r.left]; });
  assert.deepEqual(geo, [1040, 1500, true, 900, '460px', true]);
  assert.equal(await page.evaluate(() => document.scrollingElement.scrollHeight <= window.innerHeight), true);   // 쪽은 스크롤되지 않는다 / no page scroll
  // 머리: 이름(연필) · 내 위젯 · 새 위젯 · 되돌리기 · 닫기 = 아이콘만, 이름은 title 로만(사전이 바꾼다 — aria-label 은 없다)
  // the head: name (pen), my widgets, new, undo, close; icons only, named by title alone (the dictionary translates it; no aria-label)
  assert.deepEqual(await page.locator('.wa-hd button').evaluateAll(b => b.map(x => [x.dataset.wa, x.title, x.textContent.trim(), x.disabled, x.hasAttribute('aria-label')])),
    [['rename', '이름 바꾸기', '', false, false], ['mine', '내 위젯', '', false, false], ['new', '새 위젯', '', false, false], ['undo', '되돌리기', '', true, false],
      ['close', '닫기', '', false, false]]);
  assert.equal(await page.locator('.wa-nmtx').innerText(), '새 위젯');
  await page.click('[data-wa="rename"]');
  assert.deepEqual(await page.locator('#waNmIn').evaluate(i => [i.title, i.hasAttribute('aria-label'), i.value, document.activeElement === i]), ['이름 바꾸기', false, '새 위젯', true]);
  await page.press('#waNmIn', 'Escape');
  assert.deepEqual([await page.locator('#waNmIn').count(), await page.locator('.wa-nmtx').innerText()], [0, '새 위젯']);
  assert.equal(await page.locator('[data-wa="save"]').count(), 0);        // [저장]은 없다(자동 저장) / no [Save] (auto-save)
  for (const gone of ['#waStage', '#waCard', '#waFrame', '#waHint', '.wa-blank', '.wa-bar']) assert.equal(await page.locator(gone).count(), 0, gone);
  // 탭(대화가 먼저) · 상태 알약(반영할 것이 없으면 숨김) · 알림 줄 / tabs (chat first), the status pill (hidden with nothing to apply), notice rows
  assert.deepEqual(await page.locator('[data-wa-tab]').evaluateAll(b => b.map(x => [x.dataset.waTab, x.textContent, x.classList.contains('on'), x.getAttribute('aria-selected')])),
    [['chat', '대화', true, 'true'], ['info', '정보', false, 'false'], ['hist', '기록', false, 'false']]);
  for (const sel of ['#waSt', '#waNote', '#waPeek', '#waPaneInfo', '#waPaneHist']) assert.equal(await page.locator(sel).isHidden(), true, sel);
  assert.equal(await page.locator('#waChat').isVisible(), true);
  // 첫 화면 / the first screen
  assert.equal(await page.locator('.wa-hello .t').innerText(), '무엇을 만들까요?');
  assert.equal(await page.locator('.wa-hello .s').innerText(), '대화로 위젯을 만들고 고치면 홈에 바로 반영됩니다. 예를 눌러 시작해 보세요.');
  assert.deepEqual(await page.locator('.wa-ex .q').allInnerTexts(), PURE.STARTERS);
  assert.deepEqual(await page.locator('.wa-ex .c').allInnerTexts(), ['KPI 카드 · 연결할 데이터를 되물어요', '웹 검색 · 실시간 환율', '사내 데이터 · 막대 차트', '사내 문서 · 요약 글']);
  // 입력 카드 = 메인 채팅 입력창(2026-11-19 사용자 "이 채팅창이랑 다를게 없어야"): [+] · [자동 ▾] · 마이크 · 보내기(종이비행기)
  // the input card = the main chat composer (user, 2026-11-19): [+], [Auto ▾], the mic and send (a paper plane)
  assert.equal(await page.locator('.wa-cmp #waIn').count(), 1);
  assert.deepEqual(await page.locator('.wa-cmp-row button:visible').evaluateAll(b => b.map(x => x.dataset.wa)), ['plus', 'scope', 'mic', 'send']);
  assert.deepEqual(await page.locator('.wa-cmp-row button:visible').allInnerTexts(), ['', '자동', '', '']);
  assert.deepEqual([await page.getAttribute('[data-wa="plus"]', 'title'), await page.getAttribute('[data-wa="mic"]', 'title'), await page.getAttribute('[data-wa="send"]', 'title')],
    ['도구', '음성 입력', '보내기']);
  assert.equal(await page.locator('[data-wa="send"] svg path').getAttribute('d'), 'M3.4 20.6 21.6 12 3.4 3.4l2.8 7.2 9.3 1.4-9.3 1.4z');
  const look = await page.evaluate(() => [...document.querySelectorAll('.wa-cmp,[data-wa="plus"],[data-wa="scope"],[data-wa="mic"],[data-wa="send"]')].map(el => {
    const c = getComputedStyle(el), r = el.getBoundingClientRect(); return [Math.round(r.height), c.borderRadius]; }));
  assert.deepEqual(look.slice(1), [[40, '9999px'], [40, '9999px'], [40, '9999px'], [40, '50%']]);
  assert.equal(look[0][1], '24px');
  // 보내기는 늘 파란 원(빈 글이면 보내지 않을 뿐) / send stays a blue circle; an empty box simply sends nothing
  assert.equal(await page.locator('[data-wa="send"]').isDisabled(), false);
  await page.click('[data-wa="send"]');
  assert.equal(await page.locator('.wa-hello').count(), 1);
  // 정보 탭: 홈에서의 크기(처음 1 × 1, 홈에 처음 놓일 크기) · 위젯 정보, 지우기는 만든 위젯에만 / the info tab: size on Home (1 × 1, the first size) and widget info; delete only for a made widget
  await tab(page, 'info');
  assert.deepEqual([await page.locator('#waChat').isHidden(), await page.locator('#waPaneInfo').isVisible(), (await state(page)).tab], [true, true, 'info']);
  assert.deepEqual(await page.locator('#waPaneInfo .wa-pnl-t > span').allInnerTexts(), ['홈에서의 크기', '위젯 정보']);
  assert.deepEqual(await page.locator('#waSize > span:not(.g)').allInnerTexts(), ['가로', '세로']);
  assert.deepEqual(await page.locator('#waSize .g button.on').allInnerTexts(), ['1', '1']);
  assert.equal(await page.locator('.wa-size-h').innerText(), '홈에 처음 놓일 크기입니다');
  assert.deepEqual(await page.locator('#waInfo .wa-pnl-r > span:last-child').allInnerTexts(), ['아직 가져온 내용이 없습니다', '—', '새로 가져오지 않음', '내용 없음', '가로 1 × 세로 1']);
  assert.equal(await page.locator('#waInfo [data-wa-act="refresh"], [data-wa-act="delete"]').count(), 0);   // 가져온 것 · 만든 위젯이 없다 / nothing fetched, nothing made
  assert.equal(await page.locator('#waPaneHist').innerHTML(), '');        // 다른 탭은 고를 때만 채운다 / other tabs fill only when picked
  // 기록 탭: 지금 모습 한 줄 / the history tab: just the current state
  await tab(page, 'hist');
  assert.equal(await page.locator('#waPaneInfo').innerHTML(), '');
  assert.deepEqual(await page.locator('#waHist .wa-hs .l').allInnerTexts(), ['새 위젯']);
  assert.equal(await page.locator('#waHist .wa-hs .now').innerText(), '지금');
  assert.equal(await page.locator('#waHist .sub').innerText(), '아직 바뀐 것이 없습니다');
  // 내용이 없으면 홈에 아무것도 그리지 않는다 / with no content nothing is drawn on Home
  assert.equal(await page.locator('#dash .hd-ghost, #dash .hd-wa-on').count(), 0);
  // [닫기] · 아이콘으로 여닫는다 / [Close] and the icon open and close it
  await page.click('[data-wa="close"]');
  assert.deepEqual([await page.locator('body.wa-open').count(), await page.locator('#waView').isHidden(), await page.getAttribute('#waBtn', 'aria-pressed'), await page.locator('#waBtn.on').count(),
    (await state(page)).shown], [0, true, 'false', 0, false]);
  assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('.hero')).marginRight), '0px');
  await page.click('#waBtn');
  assert.deepEqual([(await state(page)).shown, await page.locator('#waView').isVisible()], [true, true]);
  await page.click('#waBtn');
  assert.deepEqual([(await state(page)).shown, await page.locator('#waView').isHidden(), await page.locator('#dash').isVisible()], [false, true, true]);
});

test('KPI 카드를 만들면 되묻는 폼 카드, 숫자를 말하면 고정 숫자 카드: 생각 과정 · 바뀐 점 · 발치 · 홈의 그 칸 · 기록 · 되돌리기 / a KPI card asks with a form card, then a fixed number: thinking, changes, footer, the home cell, history, undo', async t => {
  const { page, db } = await fixture(t, { turns: [TURN1, TURN2], holdTurn: true });
  await openAgent(page);
  await page.click('.wa-ex button >> nth=0');                                  // 예시는 채우기만 한다 / an example only fills the input
  assert.equal(await page.inputValue('#waIn'), 'KPI 카드 위젯을 만들어줘');
  assert.equal(db.turnBodies.length, 0);
  await page.press('#waIn', 'Enter');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().busy);
  // 메인 채팅처럼 '생각 중입니다', 보내기는 ■ 멈추기, 입력은 열려 있다(대기열) / 'Thinking…' as in the main chat; send turns into stop; the input stays open (queue)
  assert.equal(await page.locator('.wa-a.live .wa-think').innerText(), '생각 중입니다');
  assert.equal(await page.locator('#waIn').isDisabled(), false);
  assert.equal(await page.getAttribute('#waIn', 'placeholder'), '답을 기다리는 동안 다음 요청을 추가하세요');
  assert.deepEqual([await page.locator('[data-wa="send"].stop').count(), await page.getAttribute('[data-wa="send"]', 'title'), await page.locator('[data-wa="send"]').isDisabled()], [1, '멈추기', false]);
  assert.equal(await page.locator('[data-wa="send"] svg rect').count(), 1);   // 메인 채팅의 흰 사각 / the main chat's white square
  // 일하는 동안 머리의 아이콘은 [닫기]만 눌린다, 상태 알약은 숨는다 / while working only [Close] works in the head; the status pill hides
  assert.deepEqual(await page.locator('.wa-hd button').evaluateAll(b => b.map(x => x.disabled)), [true, true, true, true, false]);
  assert.equal(await page.locator('#waSt').isHidden(), true);
  assert.deepEqual(db.turnBodies[0], { acting_user_id: '', widget: PURE.waBlank(), messages: [], message: 'KPI 카드 위젯을 만들어줘' });   // 자동이면 source 없음 / no source on auto
  db.hold = false; db.held.splice(0).forEach(f => f());
  await idle(page);
  assert.equal(await page.locator('.wa-m.wa-u .wa-bub').innerText(), 'KPI 카드 위젯을 만들어줘');
  assert.equal(await page.locator('.wa-a .wa-tx').innerText(), "'KPI 1' KPI 카드를 만들었습니다.");
  // 생각 과정(진행 알림이 없던 턴 = trace 로): 위젯 편집 카드 · 공통 줄 · 단계 트리 / the thinking (no notices, so from the trace)
  assert.equal(await page.locator('.wa-fr').getAttribute('class'), 'wa-fr');   // 마지막 답은 펼쳐 둔다 / the last reply stays open
  assert.equal(await page.locator('.wa-fr-tg .n').innerText(), '도구 1');
  assert.equal(await page.locator('.wa-a .wa-res').count(), 0);                // 출처 카드가 없으면 리소스 링크도 없다 / no source card, no resources link
  assert.equal(await page.locator('.wa-kc.edit .wa-kc-tx b').innerText(), '위젯 편집');
  assert.equal(await page.locator('.wa-kc.edit .wa-ln.ok .lb').innerText(), 'KPI 카드 추가');
  assert.equal(await page.locator('.wa-kc.edit .wa-ln.ok code').innerText(), 'add_kpi');
  assert.equal(await page.locator('.wa-cl').innerText(), '결과를 반영해 위젯을 고쳤습니다');
  assert.deepEqual(await page.locator('.wa-tk-gh').allInnerTexts(), ['1단계 · 1개 작업 실행 완료']);
  assert.deepEqual(await page.locator('.wa-tk-l').allInnerTexts(), ['KPI 카드 추가']);
  assert.deepEqual(await page.locator('.wa-chg-r').allInnerTexts(), ['보기\nKPI 카드 1개']);
  // 추가 확인 폼 카드 / the details form card
  assert.equal(await page.locator('.wa-af-t').innerText(), '추가 확인이 필요합니다');
  assert.equal(await page.locator('.wa-af-q span:last-child').innerText(), '어떤 데이터를 연결할까요?');
  assert.deepEqual(await page.locator('.wa-af-cs .c').allInnerTexts(), ['KPI 1']);
  assert.deepEqual(await page.locator('.wa-af-o').allInnerTexts(), ['사내 데이터에서 찾기', '사내 문서에서 찾기', '웹에서 찾기']);
  assert.equal(await page.locator('.wa-af-h').innerText(), ASK.hint);
  assert.equal(await page.getAttribute('#waIn', 'placeholder'), '연결할 데이터나 숫자를 알려 주세요.');
  assert.equal(await page.locator('.wa-nx').count(), 0);                        // 질문이 있으면 다음 제안은 없다 / no suggestions under a question
  // 만든 턴은 되돌릴 곳이 없다(빈 처음은 기록에 남기지 않는다, 2026-11-20): 발치 = 복사 · 다시 시도 / the creating turn has nothing to undo to: copy and retry
  assert.deepEqual(await acts(page.locator('.wa-ft button')), ['copy', 'retry']);
  assert.deepEqual(await page.evaluate(() => { const m = window.AI365_widgetAgent.state().msgs[1]; return [m.beforeId, m.changed]; }), ['', true]);
  assert.deepEqual([(await state(page)).undo, await page.locator('[data-wa="undo"]').isDisabled()], [0, true]);
  // 그 턴이 바로 저장되어 홈의 그 칸에 홈의 그리기로(데이터 연결 전 카드), 상태 = 홈에 반영됨 / the turn is saved at once and drawn in its home cell; status = applied
  assert.equal((await state(page)).key, 'cw_99990001');
  assert.equal(await cell(page, 'cw_99990001').locator('.hw-kt.pend .l').innerText(), 'KPI 1');
  assert.equal(await page.locator('#waSt').textContent(), '홈에 반영됨 11-16 10:00');
  // 기록(빈 '새 위젯' 줄은 없다) · 정보(홈에 놓임) / history (no blank 'new widget' row) and info (on Home)
  await tab(page, 'hist');
  assert.deepEqual(await page.locator('#waHist .wa-hs .l').allInnerTexts(), ['KPI 카드 위젯을 만들어줘']);
  await tab(page, 'info');
  assert.deepEqual(await page.locator('#waInfo .wa-pnl-r > span:last-child').allInnerTexts(), ['직접 넣은 내용', '—', '새로 가져오지 않음', 'KPI 카드 1개', '가로 1 × 세로 1 · 홈에 놓임']);
  await tab(page, 'chat');
  // 둘째 턴: 대화 기록(오류 없이 글 · 도구)과 지금 작업본 / the second turn sends the history and the current draft
  await send(page, '목표 1,200건으로 해줘');
  assert.deepEqual(db.turnBodies[1].widget, DRAFT1);
  assert.deepEqual(db.turnBodies[1].messages, [{ role: 'user', text: 'KPI 카드 위젯을 만들어줘', trace: [] },
    { role: 'agent', text: "'KPI 1' KPI 카드를 만들었습니다. [질문] 어떤 데이터를 연결할까요? (KPI 1)", trace: [{ tool: 'add_kpi', ok: true }] }]);
  assert.equal(await cell(page, 'cw_99990001').locator('.hw-kt .v').innerText(), '1,200건');
  assert.deepEqual(await page.locator('.wa-fr').evaluateAll(f => f.map(x => x.classList.contains('fold'))), [true, false]);   // 지난 생각 과정은 접힌다 / earlier thinking folds
  assert.equal(await page.locator('.wa-ask').count(), 1);                       // 지난 질문은 그냥 상자로 / an earlier question is a plain box
  assert.deepEqual(await page.locator('.wa-fr >> nth=-1').locator('.wa-tk-gh').allInnerTexts(), ['1단계 · 1개 작업 실행 완료', '2단계 · 1개 작업 실행 완료']);
  assert.equal(await page.locator('.wa-kc.edit >> nth=-1').locator('.wa-ln.fail').innerText(), '인사이트 작성 — 숫자는 직접 쓰지 말고 변수로 써 주세요set_insight');   // 실패는 까닭을 / a failure shows why
  assert.deepEqual(await page.locator('.wa-nx button').allInnerTexts(), ['인사이트를 한 줄 써줘']);
  assert.equal(await page.getAttribute('#waIn', 'placeholder'), '위젯에 바라는 점을 적어 주세요. / 를 누르면 도구 트리가 열립니다.');
  assert.deepEqual(await acts(page.locator('.wa-a >> nth=-1').locator('.wa-ft button')), ['copy', 'undo-turn', 'retry']);   // 둘째 턴은 되돌릴 곳이 있다 / the second turn can be undone
  // 접힌 생각 과정은 눌러 펼친다 / a folded thinking opens on click
  await page.click('.wa-fr-tg >> nth=0');
  assert.deepEqual(await page.locator('.wa-fr').evaluateAll(f => f.map(x => x.classList.contains('fold'))), [false, false]);
  // 되돌리기 = 바로 전 작업본, 바로 홈에 반영된다. 그 앞(빈 처음)으로는 가지 않는다 / undo = the draft before, applied at once; never back to the blank start
  await page.click('[data-wa="undo"]');
  await idle(page);
  assert.deepEqual((await state(page)).widget, DRAFT1);
  assert.equal(await page.locator('#toast').innerText(), '되돌렸습니다');
  assert.deepEqual(db.puts.map(p => [p.key, p.body.spec]), [['cw_99990001', DRAFT2], ['cw_99990001', DRAFT1]]);
  assert.equal(await cell(page, 'cw_99990001').locator('.hw-kt.pend .l').innerText(), 'KPI 1');
  assert.deepEqual([(await state(page)).undo, await page.locator('[data-wa="undo"]').isDisabled()], [0, true]);
  assert.equal(await page.locator('.wa-ft [data-wa-act="undo-turn"]').count(), 0);   // 되돌린 턴에는 '이 턴 되돌리기'가 없다 / gone once undone
  assert.equal(db.posts.length, 1);
});

test('추가 확인 폼 카드: 빈 제출은 알리고, 고른 곳 · 적은 글로 보낸다 / the details form: an empty submit errs; the pick and text are sent', async t => {
  const { page, db } = await fixture(t, { turns: [TURN1, TURN1, FX_TURN] });
  await openAgent(page);
  await send(page, 'KPI 카드 위젯을 만들어줘');
  await page.click('[data-wa-act="ask-go"]');
  assert.equal(await page.locator('.wa-af-er').innerText(), '연결할 데이터를 적거나 찾을 곳을 골라 주세요');
  assert.equal(db.turnBodies.length, 1);
  await page.click('[data-wa-opt="docs"]');
  assert.deepEqual(await page.locator('.wa-af-o.on').allInnerTexts(), ['사내 문서에서 찾기']);
  assert.equal(await page.locator('.wa-af-er').count(), 0);
  await page.click('[data-wa-act="ask-go"]');
  await idle(page);
  // 고른 곳만 있으면 카드 이름으로 요청을 만들고 그곳에서만 찾는다 / a pick alone builds the request from the card names and searches there only
  assert.deepEqual([db.turnBodies[1].message, db.turnBodies[1].source], ["사내 문서에서 'KPI 1' 카드에 맞는 데이터를 찾아 연결해줘", 'docs']);
  // 적은 글이 먼저(Enter 로도 제출) / typed text wins (Enter submits too)
  await page.click('[data-wa-opt="web"]');
  await page.fill('#waAfIn', '오늘 원달러 환율');
  await page.press('#waAfIn', 'Enter');
  await idle(page);
  assert.deepEqual([db.turnBodies[2].message, db.turnBodies[2].source], ['오늘 원달러 환율', 'web']);
  assert.equal((await state(page)).source, 'auto');                             // 입력 카드의 고른 곳은 그대로 / the input card's pick is unchanged
  assert.equal(await page.locator('.wa-m.wa-u .wa-bub >> nth=-1').innerText(), '오늘 원달러 환율');
  // 만든 턴 = 만들기, 바뀌지 않은 턴 = 저장 없음, 바뀐 턴 = 고치기 / the creating turn creates, an unchanged one saves nothing, a changing one updates
  assert.deepEqual([db.posts.map(p => p.spec), db.puts.map(p => p.body.spec)], [[DRAFT1], [FX_WIDGET]]);
});

test('턴이 위젯을 바꾸면 바로 홈에 반영: 처음은 만들어 빈 첫 자리에 놓고 대화도 저장, 다음은 고치고, 바뀐 것이 없는 턴은 대화만 / a turn that changes the widget lands on Home at once: the first makes it at the first free spot and saves the conversation, the next updates it, an unchanged turn saves the conversation only', async t => {
  const SAME = { widget: DRAFT2, model: MODEL2, reply: '그대로예요.', ask: null,
    trace: [{ agent: 'Visualize Agent', group: '정리', tool: 'set_insight', label: '인사이트 작성', ok: false, detail: '숫자는 직접 쓰지 말고 변수로 써 주세요', say: '', round: 1 }] };
  const { page, db } = await fixture(t, { turns: [TURN1, TURN2, SAME], width: WIDE });
  await openAgent(page);
  await send(page, 'KPI 카드 위젯을 만들어줘');
  // 만들기(POST) → 배치를 읽어 빈 첫 자리에 처음 크기로 놓아 저장(PUT) → 다시 읽기 / create (POST), then read the layout, place it at the first free spot at its first size (PUT) and read again
  assert.deepEqual(db.posts, [{ acting_user_id: '', spec: DRAFT1 }]);
  assert.equal(db.puts.length, 0);
  assert.equal(db.dashPuts.length, 1);
  assert.deepEqual(rowsOf(db.dashPuts[0].items), ['wx 0 0 1 1', 'ask 1 0 1 1', 'org 2 0 1 2', 'cal 0 1 1 2', 'sc 1 1 1 1', 'coll 1 2 1 1', 'gwb 2 2 1 2', 'tok 0 3 1 1', 'att 1 3 1 1',
    'cw_99990001 0 4 1 1']);
  let s = await state(page);
  assert.deepEqual([s.key, s.dirty, s.busy, s.undo, s.shown], ['cw_99990001', false, false, 0, true]);
  assert.equal(await page.locator('#toast').innerText(), '새 위젯을 홈에 놓았습니다');
  const made = cell(page, 'cw_99990001');
  assert.deepEqual(await spot(made), ['1 / span 1', '5 / span 1']);
  assert.equal(await made.evaluate(el => el.classList.contains('hd-wa-on')), true);   // 패널이 고치는 위젯 = 파란 테두리 / the widget the panel edits gets the blue ring
  assert.equal(await made.locator('.hd-nm').innerText(), '새 위젯');
  assert.equal(await page.locator('#dash .hd-ghost').count(), 0);
  assert.equal(await page.evaluate(() => window.AI365_homeDash.previewOf('cw_99990001')), null);   // 저장된 모습 그대로 / the stored drawing
  assert.deepEqual(await page.locator('#waSt').evaluate(b => [b.hidden, b.disabled, b.classList.contains('dirty'), b.textContent]), [false, true, false, '홈에 반영됨 11-16 10:00']);
  // 예전 [저장] 시절의 문구는 어디에도 없다 / none of the former [Save]-era labels remain anywhere
  const panelText = await page.locator('#waView').innerText();
  for (const old of ['저장됨', '저장 안 됨', '저장하지 않은 변경', '홈에서 보이는 모습', '아직 위젯 내용이 없습니다', '저장했습니다']) assert.equal(panelText.indexOf(old), -1, old);
  // 대화 저장본 = 대화 + 변경 기록 + 지금 이름(fold 는 빼고), 빈 처음은 기록에 없다 / the saved conversation (no fold); no blank first state in the history
  await until(() => db.chatPuts.length === 1);
  const saved = db.chatPuts[0];
  assert.equal(saved.key, 'cw_99990001');
  assert.deepEqual(saved.body.chat.msgs.map(m => [m.role, m.text, 'fold' in m]), [['user', 'KPI 카드 위젯을 만들어줘', false], ['agent', "'KPI 1' KPI 카드를 만들었습니다.", false]]);
  assert.deepEqual([saved.body.chat.msgs[1].changed, saved.body.chat.hist, saved.body.chat.label], [true, [], 'turn:KPI 카드 위젯을 만들어줘']);
  // 다음 턴 = 고치기(PUT), 배치는 다시 읽기만 / the next turn updates (PUT); the layout is only read again
  const gets = db.gets;
  await send(page, '목표 1,200건으로 해줘');
  assert.deepEqual(db.puts, [{ key: 'cw_99990001', body: { acting_user_id: '', spec: DRAFT2 } }]);
  assert.deepEqual([db.posts.length, db.dashPuts.length], [1, 1]);
  assert.ok(db.gets > gets);
  assert.equal(await made.locator('.hw-kt .v').innerText(), '1,200건');
  assert.equal(await page.locator('#waSt').textContent(), '홈에 반영됨 11-16 11:15');
  await until(() => db.chatPuts.length === 2);
  assert.deepEqual(db.chatPuts[1].body.chat.hist.map(h => [h.label, h.widget.title, h.widget.kpis[0].pending]), [['turn:KPI 카드 위젯을 만들어줘', '새 위젯', true]]);
  // 바뀐 것이 없는 턴: 위젯은 저장하지 않고 대화만, 공통 줄은 '바뀌지 않았습니다' / an unchanged turn saves the conversation only and its common line says so
  await send(page, '그대로 둬');
  assert.equal(db.puts.length, 1);
  await until(() => db.chatPuts.length === 3);
  const last = db.chatPuts[2].body.chat.msgs.slice(-1)[0];
  assert.deepEqual([last.text, last.changed, last.beforeId], ['그대로예요.', false, '']);
  assert.equal(await page.locator('.wa-a >> nth=-1').locator('.wa-cl').innerText(), '위젯은 바뀌지 않았습니다');
  assert.deepEqual(await acts(page.locator('.wa-a >> nth=-1').locator('.wa-ft button')), ['copy', 'retry']);
  s = await state(page);
  assert.deepEqual([s.dirty, s.undo], [false, 1]);
});

test('내 위젯 열기 = 저장된 대화가 접힌 채로 이어지고 홈의 그 칸이 강조된다, 지난 모습은 그 칸에 미리 보고, 이름을 바꾸면 바로 반영, 다 반영됐으면 묻지 않는다 / opening restores the folded conversation and marks the home cell; an earlier state previews in that cell; renaming applies at once; nothing is asked when all is applied', async t => {
  const { page, db } = await fixture(t, { turns: [TURN1], mine: [SAVED], chats: { cw_55555555: OLD }, layout: ROWS.concat(['cw_55555555 0 4 1 2']) });
  await openAgent(page);
  await page.click('[data-wa="mine"]');
  await page.waitForSelector('[data-wa-open="cw_55555555"]');
  assert.equal(await page.locator('.wa-mn-it .t').innerText(), '지점별 매출');
  assert.equal(await page.locator('.wa-mn-it .s').innerText(), '2026-11-16 09:30');   // 홈에 놓여 있다('홈에 없음' 없음) / placed, so no 'Not on Home'
  await page.click('[data-wa-open="cw_55555555"]');                               // 반영하지 못한 것이 없으면 바로 연다 / opens at once with nothing unapplied
  await page.waitForFunction(() => window.AI365_widgetAgent.state().msgs.length === 2 && !window.AI365_widgetAgent.state().busy);
  assert.deepEqual(db.chatGets, ['cw_55555555']);
  assert.equal(await page.locator('.wa-nmtx').innerText(), '지점별 매출');
  const home = cell(page, 'cw_55555555');
  assert.equal(await home.evaluate(el => el.classList.contains('hd-wa-on')), true);   // 고치는 위젯 강조 / the widget being edited is marked
  await page.waitForFunction(() => { const c = document.querySelector('#dash > .wg[data-wg="cw_55555555"] canvas[data-hw-canvas]'); return !!(c && c._hw && c.width > 0); });   // 차트는 홈의 것 / the home's own chart
  assert.equal(await home.locator('.hw-ins span').innerText(), '강남점이 가장 높습니다');
  assert.equal(await page.locator('#waSt').textContent(), '홈에 반영됨 11-16 09:30');
  // 저장된 대화: 생각 과정은 접혀 있고, 변경 기록은 저장본에서 / the saved conversation: thinking folded, history from the save
  assert.deepEqual(await page.locator('.wa-fr').evaluateAll(f => f.map(x => x.classList.contains('fold'))), [true]);
  assert.equal(await page.locator('.wa-a .wa-tx').innerText(), '예전 답');
  await tab(page, 'hist');
  assert.deepEqual(await page.locator('#waHist .wa-hs .l').allInnerTexts(), ['예전 요청', '새 위젯']);
  assert.equal((await state(page)).undo, 1);
  // 모델이 없는 지난 모습은 서버가 그려 주고, 홈의 그 칸에 미리 보인다 / an earlier state without a model is drawn by the server and previewed in the home cell
  await page.click('#waHist [data-wa-hist="h1"]');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().peek === 'h1' && !window.AI365_widgetAgent.state().busy);
  assert.equal(db.models.length, 1);
  assert.deepEqual(db.models[0].widget, DRAFT2);
  assert.equal(await page.locator('#waPeek > span').innerText(), '지난 모습 미리보기 — 새 위젯');
  assert.deepEqual(await acts(page.locator('#waPeek button')), ['restore', 'peek-close']);
  assert.deepEqual([await home.locator('.hd-nm').innerText(), await home.locator('.hw-kt .v').innerText(), await home.locator('canvas').count()], ['새 위젯', '1,200건', 0]);
  assert.equal(await page.evaluate(() => window.AI365_homeDash.previewOf('cw_55555555').kpis[0].text), '1,200건');
  assert.equal(await page.locator('#waHist [data-wa-hist="h1"].on').count(), 1);
  await tab(page, 'info');
  assert.equal(await page.locator('#waSize .g button:disabled').count(), 6);      // 미리보기 중에는 크기를 바꾸지 않는다 / no resizing while previewing
  await page.click('[data-wa-act="peek-close"]');
  assert.equal(await page.locator('#waPeek').isHidden(), true);
  assert.equal(await page.evaluate(() => window.AI365_homeDash.previewOf('cw_55555555')), null);   // 저장된 모습으로 / back to the stored drawing
  assert.deepEqual([await home.locator('.hd-nm').innerText(), await home.locator('.hw-kt').count()], ['지점별 매출', 0]);
  await page.waitForFunction(() => { const c = document.querySelector('#dash > .wg[data-wg="cw_55555555"] canvas[data-hw-canvas]'); return !!(c && c._hw && c.width > 0); });
  assert.equal(db.puts.length, 0);                                                   // 미리보기는 저장하지 않는다 / previewing saves nothing
  // 이름 바로 바꾸기: Esc 는 그대로, Enter 는 바꾸고 바로 저장(홈의 그 칸도) · 기록에 남긴다 / rename in place: Esc keeps it; Enter changes, saves (the home cell too) and records it
  await page.click('[data-wa="rename"]');
  await page.fill('#waNmIn', '버려질 이름');
  await page.press('#waNmIn', 'Escape');
  assert.equal(await page.locator('.wa-nmtx').innerText(), '지점별 매출');
  assert.equal(db.puts.length, 0);
  await page.click('[data-wa="rename"]');
  await page.fill('#waNmIn', '  지점 매출 비교 ');
  await page.press('#waNmIn', 'Enter');
  await idle(page);
  assert.equal(await page.locator('.wa-nmtx').innerText(), '지점 매출 비교');
  assert.deepEqual(db.puts, [{ key: 'cw_55555555', body: { acting_user_id: '', spec: Object.assign({}, SAVED.spec, { title: '지점 매출 비교' }) } }]);
  assert.equal(await home.locator('.hd-nm').innerText(), '지점 매출 비교');
  assert.equal(await page.locator('#waSt').textContent(), '홈에 반영됨 11-16 11:15');
  await until(() => db.chatPuts.length === 1);
  assert.deepEqual([db.chatPuts[0].body.chat.label, db.chatPuts[0].body.chat.hist.map(h => h.label)], ['rename:지점 매출 비교', ['new:', 'turn:예전 요청']]);
  await tab(page, 'hist');
  assert.deepEqual(await page.locator('#waHist .wa-hs .l').allInnerTexts(), ['이름 바꾸기 · 지점 매출 비교', '예전 요청', '새 위젯']);
  // 다 반영됐으면 새 위젯 · 다른 위젯 열기는 묻지 않는다 / with everything applied, a new or another widget asks nothing
  await page.click('[data-wa="new"]');
  assert.equal(await page.locator('#waOv').count(), 0);
  const s = await state(page);
  assert.deepEqual([s.key, s.widget, s.msgs, s.dirty, s.busy, s.undo, s.queue, s.label, s.peek, s.tab], ['', PURE.waBlank(), [], false, false, 0, [], 'new:', '', 'chat']);
  assert.equal(await page.locator('.wa-hello .t').innerText(), '무엇을 만들까요?');
  assert.equal(await home.evaluate(el => el.classList.contains('hd-wa-on')), false);   // 강조가 풀린다 / the mark goes
  assert.equal(await page.locator('#waSt').isHidden(), true);
  await page.click('[data-wa="mine"]');
  await page.click('[data-wa-open="cw_55555555"]');
  assert.equal(await page.locator('#waOv').count(), 0);
  await page.waitForFunction(() => window.AI365_widgetAgent.state().msgs.length === 2 && !window.AI365_widgetAgent.state().busy);
  assert.deepEqual([await page.locator('.wa-nmtx').innerText(), (await state(page)).undo, (await state(page)).label], ['지점 매출 비교', 2, 'rename:지점 매출 비교']);   // 저장된 기록 그대로 / the saved history
  assert.equal(db.posts.length, 0);
});

test('열어 둔 위젯이 그 사이 지워졌으면(PUT 404) 다시 만들지 않는다: 알리고 작업본만 남기며 자동 저장도 멈추고(다음 턴도), [다시 저장]을 눌러야 새 위젯으로 / a widget deleted meanwhile (PUT 404) is not re-created: a notice, only the working copy stays and auto-save pauses (later turns too) until [save again] makes a new widget', async t => {
  const { page, db } = await fixture(t, { turns: [TURN2], mine: [SAVED], width: WIDE });
  await openAgent(page);
  await page.click('[data-wa="mine"]');
  await page.click('[data-wa-open="cw_55555555"]');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === 'cw_55555555' && !window.AI365_widgetAgent.state().busy);
  db.mine = [];                                                                       // 다른 창에서 지웠다 / deleted in another window
  await page.click('[data-wa="rename"]');
  await page.fill('#waNmIn', '지점 매출 비교');
  await page.press('#waNmIn', 'Enter');
  await idle(page);
  assert.deepEqual([db.puts.map(p => p.key), db.posts.length, db.dashPuts.length], [['cw_55555555'], 0, 0]);   // 고치기만 했고 만들지 않았다 / only the update; nothing created
  assert.equal(await page.locator('#toast').innerText(), '이 위젯은 지워졌습니다. 고친 내용은 홈에 반영하지 않았습니다 — [다시 저장]을 누르면 새 위젯으로 만듭니다');
  let s = await state(page);
  assert.deepEqual([s.key, s.dirty, s.widget.title], ['', true, '지점 매출 비교']);
  assert.deepEqual(await page.locator('#waSt').evaluate(b => [b.hidden, b.disabled, b.classList.contains('dirty'), b.textContent]), [false, false, true, '반영 안 됨 · 다시 저장']);
  assert.equal(await page.locator('#dash .hd-ghost').count(), 0);                    // 지워진 위젯의 작업본은 홈에 그리지 않는다 / a deleted widget's copy is not drawn on Home
  // 다음 턴도 저장하지 않는다(멈춘 채) / a later turn saves nothing either (still paused)
  await send(page, '목표 1,200건으로 해줘');
  s = await state(page);
  assert.deepEqual([db.puts.length, db.posts.length, s.key, s.widget, s.dirty], [1, 0, '', DRAFT2, true]);
  assert.equal(await page.locator('#dash .hd-ghost').count(), 0);
  assert.equal(await page.locator('#waSt').textContent(), '반영 안 됨 · 다시 저장');
  // [다시 저장] = 그때 새 위젯으로 만들어 빈 첫 자리에 / [save again] only then makes it a new widget at the first free spot
  await page.click('#waSt');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === 'cw_99990001' && !window.AI365_widgetAgent.state().busy);
  assert.deepEqual(db.posts.map(p => p.spec), [DRAFT2]);
  assert.equal(await page.locator('#toast').innerText(), '새 위젯을 홈에 놓았습니다');
  assert.deepEqual([(await state(page)).dirty, await page.locator('#waSt').textContent()], [false, '홈에 반영됨 11-16 10:00']);
  assert.deepEqual([await spot(cell(page, 'cw_99990001')), await page.locator('#dash .hd-ghost').count()], [['1 / span 1', '5 / span 1'], 0]);
  await until(() => db.chatPuts.length === 1);
  assert.equal(db.chatPuts[0].key, 'cw_99990001');                                    // 대화는 새 위젯에 / the conversation goes with the new widget
});

test('[+] 도구 메뉴 · [자동 ▾] 사내 · 외부 · 리소스 센터(메인 채팅과 같다). 한글 조합 중 Enter 는 보내지 않는다 / the [+] tool menu, [Auto ▾] internal, external and the resource center (as the main chat); Enter while composing never sends', async t => {
  const { page, db } = await fixture(t, { turns: [TURN1, TURN1, TURN1, TURN1] });
  await openAgent(page);
  await page.click('#waIn');
  await page.keyboard.press('/');
  await page.waitForSelector('.wa-pop.am [data-wa-grp]');
  assert.equal(await page.inputValue('#waIn'), '');                                // / 는 글자로 들어가지 않는다 / the slash is not typed
  // [+] 메뉴 = 메인 채팅의 + 메뉴: 묶음(데이터 먼저) › 도구 / the [+] menu = the main chat's: groups (data first) › tools
  assert.deepEqual(await page.locator('.wa-pop.am [data-wa-grp]').allInnerTexts(), ['데이터', '리포트', '기준선']);
  const box = await page.evaluate(() => { const m = document.querySelector('.wa-pop.am'), b = document.querySelector('[data-wa="plus"]').getBoundingClientRect(), r = m.getBoundingClientRect();
    return [getComputedStyle(m).position, Math.round(b.top - r.bottom), Math.round(r.left - b.left)]; });
  assert.deepEqual(box, ['fixed', 8, 0]);                                            // [+] 바로 위 8px · 왼쪽 맞춤 / 8px above the [+], left-aligned
  assert.equal(await page.locator('[data-wa="plus"].on').count(), 1);
  await page.click('.wa-pop.am [data-wa-grp="기준선"]');                             // 묶음을 누르면 그 도구들(메뉴는 열린 채) / a group shows its tools (the menu stays)
  assert.deepEqual(await page.locator('.wa-pop.am .wa-mi').allInnerTexts(), ['기준선', '기준선 추가\nadd_reference_line']);
  await page.click('.wa-pop.am .wa-mi.back');
  assert.equal(await page.locator('.wa-pop.am [data-wa-grp="리포트"]').count(), 1);
  await page.click('.wa-pop.am [data-wa-grp="기준선"]');
  await page.click('[data-wa-tool="add_reference_line"]');
  assert.equal(await page.inputValue('#waIn'), '평균선을 넣어줘');
  assert.equal(await page.locator('.wa-pop').count(), 0);
  await page.click('[data-wa="plus"]');
  await page.waitForSelector('.wa-pop.am');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.wa-pop').count(), 0);
  await page.click('[data-wa="plus"]');
  await page.click('#homeTitle');                                                    // 바깥(홈)을 누르면 닫힌다 / a click outside (on Home) closes it
  assert.equal(await page.locator('.wa-pop').count(), 0);
  // [자동 ▾]: 누를 때마다 자동 → 사내 → 외부, 사내면 [리소스 센터] / [Auto ▾] cycles auto → internal → external; internal shows [Resource Center]
  const label = () => page.locator('[data-wa="scope"] .wa-pb-tx').innerText();
  assert.equal(await label(), '자동');
  assert.equal(await page.locator('[data-wa="res"]').isHidden(), true);
  await page.click('[data-wa="scope"]');
  assert.equal(await label(), '사내');
  assert.equal(await page.locator('[data-wa="res"]').innerText(), '리소스 센터');
  await send(page, '연차 규정 요약');
  assert.equal(db.turnBodies[0].source, 'internal');                                // 사내 = 사내 데이터 · 사내 문서(웹 없이) / internal = data and documents, no web
  // 리소스 선택 창: 지식 관리 · 데이터 분석(하나만 고르면 그곳만, 둘 다 · 안 고름 = 사내 전체) / the resource dialog
  await page.click('[data-wa="res"]');
  assert.equal(await page.locator('#waRsOv .wa-rs-hd .t').innerText(), '리소스 선택');
  assert.deepEqual(await page.locator('#waRsOv .wa-rs-r .n').allInnerTexts(), ['지식 관리', '데이터 분석']);
  await page.check('#waRsOv [data-wa-rsk="docs"]');
  await page.click('#waRsOv [data-wa-rs="ok"]');
  assert.equal(await page.locator('#waRsOv').count(), 0);
  assert.deepEqual([await page.locator('[data-wa="res"]').innerText(), await page.locator('[data-wa="res"].on').count()], ['지식 관리', 1]);
  await send(page, '다시');
  assert.equal(db.turnBodies[1].source, 'docs');
  await page.click('[data-wa="res"]');
  assert.equal(await page.locator('#waRsOv [data-wa-rsk="docs"]').isChecked(), true);
  await page.check('#waRsOv [data-wa-rsk="data"]');
  await page.click('#waRsOv [data-wa-rs="ok"]');
  assert.deepEqual([await page.locator('[data-wa="res"]').innerText(), await page.locator('[data-wa="res"].on').count()], ['리소스 센터', 0]);
  await page.click('[data-wa="res"]');
  await page.keyboard.press('Escape');                                              // Esc = 취소 / Esc cancels
  assert.equal(await page.locator('#waRsOv').count(), 0);
  await page.click('[data-wa="scope"]');
  assert.deepEqual([await label(), await page.locator('[data-wa="res"]').isHidden()], ['외부', true]);
  await send(page, '환율');
  assert.equal(db.turnBodies[2].source, 'web');
  await page.click('[data-wa="scope"]');
  assert.equal(await label(), '자동');
  await send(page, '자동으로');
  assert.equal('source' in db.turnBodies[3], false);
  await page.click('[data-wa="mic"]');                                              // 마이크는 메인 채팅처럼 모양만 / the mic is shape only, as in the main chat
  assert.equal(db.turnBodies.length, 4);
  // 한글 조합 중의 Enter / Enter during Korean composition
  await page.evaluate(() => { const i = document.getElementById('waIn'); i.value = '한글'; i.dispatchEvent(new Event('input', { bubbles: true }));
    i.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true, cancelable: true })); });
  await page.waitForTimeout(150);
  assert.equal(db.turnBodies.length, 4);
});

test('턴이 실패하면 대화에 알리고 작업본은 그대로, 영어에서는 패널의 머리 · 탭 · 정보 · 상태 · 알림이 영어 / a failed turn says so and keeps the draft; in English the panel head, tabs, info, status and toasts are English', async t => {
  const { page, db } = await fixture(t, { lang: 'en', turns: [{ status: 503, body: { detail: '위젯 에이전트가 지금 응답하지 않습니다. 잠시 뒤 다시 시도해 주세요' } }, TURN1] });
  await page.waitForFunction(() => document.getElementById('waBtn').title === 'Widget Agent');
  await openAgent(page);
  await page.waitForFunction(() => document.querySelector('[data-wa="close"]').title === 'Close');
  assert.deepEqual(await page.locator('.wa-hd button').evaluateAll(b => b.map(x => x.title)), ['Rename', 'My widgets', 'New widget', 'Undo', 'Close']);
  assert.equal(await page.locator('.wa-nmtx').innerText(), '새 위젯');               // 위젯 이름은 데이터라 그대로 / the widget name is data
  await page.click('[data-wa="rename"]');
  assert.equal(await page.getAttribute('#waNmIn', 'title'), 'Rename');
  await page.press('#waNmIn', 'Escape');
  assert.deepEqual(await page.locator('[data-wa-tab]').allInnerTexts(), ['Chat', 'Info', 'History']);
  assert.deepEqual(await page.locator('.wa-ex .c').allInnerTexts(), ['KPI cards · asks which data to connect', 'Web search · live exchange rate', 'Company data · bar chart', 'Company documents · summary text']);
  assert.equal(await page.locator('[data-wa="scope"] .wa-pb-tx').innerText(), 'Auto');
  assert.deepEqual([await page.getAttribute('[data-wa="plus"]', 'title'), await page.getAttribute('[data-wa="mic"]', 'title')], ['Tools', 'Voice input']);
  await page.click('[data-wa="plus"]');
  await page.waitForSelector('.wa-pop.am [data-wa-grp]');
  assert.deepEqual(await page.locator('.wa-pop.am [data-wa-grp]').allInnerTexts(), ['Data', 'Report', 'Reference lines']);
  await page.keyboard.press('Escape');
  await page.click('[data-wa="scope"]');
  assert.equal(await page.locator('[data-wa="res"]').innerText(), 'Resource Center');
  await page.click('[data-wa="scope"]');
  assert.equal(await page.locator('[data-wa="scope"] .wa-pb-tx').innerText(), 'External');
  await page.click('[data-wa="scope"]');
  assert.equal(await page.locator('.wa-hello .t').innerText(), 'What shall we build?');
  assert.equal(await page.locator('.wa-hello .s').innerText(), 'Build and refine widgets by conversation; Home updates at once. Pick an example to start.');
  assert.equal(await page.getAttribute('#waIn', 'placeholder'), 'Tell the agent what the widget should show. Type / for the tool tree.');
  // 정보 탭 / the info tab
  await tab(page, 'info');
  assert.deepEqual(await page.locator('#waPaneInfo .wa-pnl-t > span').allInnerTexts(), ['Size on Home', 'Widget info']);
  assert.deepEqual(await page.locator('#waSize > span:not(.g)').allInnerTexts(), ['Wide', 'Tall']);
  assert.equal(await page.locator('.wa-size-h').innerText(), 'The size it first takes on Home');
  assert.deepEqual(await page.locator('#waInfo .wa-pnl-r > span:first-child').allInnerTexts(), ['Sources', 'Fetched', 'Refresh', 'Contents', 'Size']);
  await tab(page, 'chat');
  await send(page, '저장');                                                         // 사용자의 글은 번역하지 않는다 / the user's text is never translated
  assert.equal(await page.locator('.wa-m.err .wa-tx').innerText(), '위젯 에이전트가 지금 응답하지 않습니다. 잠시 뒤 다시 시도해 주세요');   // 서버의 문장은 그대로 / the server's sentence as is
  assert.equal(await page.locator('.wa-m.wa-u .wa-bub').innerText(), '저장');
  assert.deepEqual((await state(page)).widget, PURE.waBlank());
  assert.deepEqual(await acts(page.locator('.wa-m.err .wa-ft button')), ['retry']);   // 실패한 턴은 다시 시도만 / a failed turn offers retry
  assert.deepEqual([db.posts.length, await page.locator('#waSt').isHidden()], [0, true]);   // 실패한 턴은 저장할 것이 없다 / a failed turn saves nothing
  await send(page, 'make a KPI card');
  assert.deepEqual(db.turnBodies[1].messages, [{ role: 'user', text: '저장', trace: [] }]);   // 오류 줄은 기록에 넣지 않는다 / error lines stay out of the history
  await page.waitForTimeout(250);
  assert.equal(await page.locator('.wa-af-t').innerText(), 'More details needed');
  assert.equal(await page.locator('.wa-af-q span:last-child').innerText(), 'Which data should I connect?');
  assert.deepEqual(await page.locator('.wa-af-o').allInnerTexts(), ['Find it in company data', 'Find it in company documents', 'Find it on the web']);
  assert.equal(await page.locator('.wa-af-cs .c').innerText(), 'KPI 1');
  assert.equal(await page.locator('.wa-kc.edit .lb').innerText(), 'Add KPI card');                // 도구 이름은 사전이 / the dictionary names the tool
  assert.equal(await page.locator('.wa-kc.edit .wa-kc-tx b').innerText(), 'Widget edits');
  assert.equal(await page.locator('.wa-fr-tg .n').innerText(), 'Tools 1');
  assert.deepEqual(await page.locator('.wa-tk-gh').allInnerTexts(), ['Stage 1 · 1 task done']);
  // 홈의 새 칸 · 알림 · 상태 / the new home cell, the toast and the status
  await page.waitForFunction(() => { const g = document.querySelector('#dash > .wg[data-wg="cw_99990001"] .hw-kt.pend .tag'); return g && g.textContent === 'Not connected'; });
  await page.waitForFunction(() => document.querySelector('#dash > .wg[data-wg="cw_99990001"] [data-hd-wa]').title === 'Edit with the Widget Agent');
  assert.equal(await page.locator('#toast').innerText(), 'The new widget is on Home');
  assert.equal(await page.locator('#waSt').textContent(), 'On Home · 11-16 10:00');
  await tab(page, 'hist');
  assert.deepEqual(await page.locator('#waHist .wa-hs .l').allInnerTexts(), ['make a KPI card']);
  assert.equal(await page.locator('#waHist .sub').innerText(), 'No changes yet');
  await tab(page, 'info');
  assert.equal(await page.locator('.wa-size-h').innerText(), 'A pick resizes it on Home at once');
  assert.equal(await page.locator('#waInfo .wa-pnl-r >> nth=4').locator('span:last-child').innerText(), '1 wide × 1 tall · on Home');
  assert.equal(await page.locator('[data-wa-act="delete"]').innerText(), 'Delete widget');
  await tab(page, 'chat');
  // 우리 오류 문구는 영어로(서버가 문장을 주지 않은 실패) / our own error sentence turns English (a failure without a server sentence)
  await page.route('**/api/home/agent/turn/stream', route => route.abort());
  await send(page, 'again');
  assert.equal(await page.locator('.wa-m.err .wa-tx >> nth=-1').innerText(), 'The widget agent is not answering. Please try again shortly');
  assert.equal(await page.locator('.wa-a:not(.err) .wa-tx').innerText(), "'KPI 1' KPI 카드를 만들었습니다.");   // 서버의 답은 그대로 / the server's reply as is
});

test('영어: 반영하지 못한 상태 · 묻는 창 · 점선 카드 · 홈에 놓기 · 지우기 문구 / English: the not-applied pill, the guard dialog, the dashed card, putting on Home and deleting', async t => {
  const { page, db } = await fixture(t, { lang: 'en', turns: [TURN1], mine: [SAVED], failSave: true });
  await page.waitForFunction(() => document.getElementById('waBtn').title === 'Widget Agent');
  await openAgent(page);
  await send(page, 'make a KPI card');
  await page.waitForFunction(() => document.getElementById('toast').textContent === 'Could not save the widget');
  assert.equal(await page.locator('#waSt').textContent(), 'Not applied · save again');
  await page.waitForFunction(() => { const n = document.querySelector('#dash .hd-ghost .hd-new'); return n && n.textContent === 'New widget'; });
  await page.click('[data-wa="new"]');
  await page.waitForFunction(() => { const x = document.querySelector('#waOv .wa-dlg-tt'); return x && x.textContent === 'Some changes could not be applied to Home.'; });
  assert.deepEqual([await page.locator('#waOv .wa-dlg-bd').innerText(), await page.locator('#waOv [data-wa-dlg="no"]').innerText(), await page.locator('#waOv [data-wa-dlg="ok"]').innerText()],
    ['Start a new widget without applying them?', 'Cancel', 'Start new']);
  assert.equal(await page.evaluate(() => document.activeElement.dataset.waDlg), 'ok');   // 묻는 창은 확인 단추에 초점 / the guard dialog focuses its confirm button
  await page.click('#waOv [data-wa-dlg="no"]');
  await page.click('[data-wa="mine"]');
  await page.click('[data-wa-open="cw_55555555"]');
  await page.waitForFunction(() => { const x = document.querySelector('#waOv .wa-dlg-bd'); return x && x.textContent === 'Open another widget without applying them?'; });
  assert.equal(await page.locator('#waOv [data-wa-dlg="ok"]').innerText(), 'Open');
  await page.click('#waOv [data-wa-dlg="no"]');
  // 저장은 되지만 홈에 놓지 못하면 알림 줄 / saved but not placed: the notice row
  db.failSave = false; db.failDash = true;
  await page.click('#waSt');
  await idle(page);
  assert.equal(await page.locator('#toast').innerText(), 'Widget made. It could not be placed now, so it is under Add widget in Edit layout');
  assert.deepEqual([await page.locator('#waNote > span').innerText(), await page.locator('#waNote button').innerText()], ['This widget is not on Home', 'Put on Home']);
  await page.click('[data-wa="mine"]');
  await page.waitForSelector('[data-wa-open="cw_99990001"]');
  assert.equal(await page.locator('[data-wa-open="cw_99990001"] .off').innerText(), 'Not on Home');
  await page.click('[data-wa="mine"]');
  db.failDash = false;
  await page.click('#waNote [data-wa-act="put-home"]');
  await idle(page);
  assert.equal(await page.locator('#toast').innerText(), 'It is on Home now');
  assert.equal(await page.locator('#waSt').textContent(), 'On Home · 11-16 10:00');
  await tab(page, 'info');
  assert.equal(await page.locator('.wa-size-h').innerText(), 'A pick resizes it on Home at once');
  await page.click('[data-wa-act="delete"]');
  await page.waitForFunction(() => { const x = document.querySelector('#waOv [data-wa-dlg="no"]'); return x && x.textContent === 'Cancel'; });
  assert.deepEqual([await page.locator('#waOv .wa-dlg-tt').innerText(), await page.locator('#waOv .wa-dlg-bd').innerText(), await page.locator('#waOv [data-wa-dlg="ok"]').innerText()],
    ['Delete this widget?', 'It leaves Home and My widgets together with its conversation. This cannot be undone.', 'Delete']);
  assert.equal(await page.evaluate(() => document.activeElement.dataset.waDlg), 'no');   // 지우기 창은 [취소]에 초점 / the delete dialog focuses [Cancel]
  await page.click('#waOv [data-wa-dlg="ok"]');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === '' && !window.AI365_widgetAgent.state().busy);
  assert.equal(await page.locator('#toast').innerText(), 'Widget deleted');
});

// 뷰애즈(사람 바꾸기) 흉내 · 토스트 지우기 / view-as (switching the person) and clearing the toast
const asUser = (page, no) => page.evaluate(n => { window.AI365_ACTING_USER = n == null ? null : { no: n, name: '#' + n, dept: '' }; }, no);
const clearToast = page => page.evaluate(() => { document.getElementById('toast').textContent = ''; });
const MOVED = '사용자가 바뀌어 위젯 에이전트를 처음 상태로 돌렸습니다';

test('사람이 바뀌면(뷰애즈) 처음 상태로 돌리고 새 사람에게는 아무것도 저장하지 않는다: 진입 알림 · 패널 안 클릭(그 클릭은 하지 않는다) · 보내기(보내지 않는다) / a changed person (view-as) resets the panel and nothing is saved for the new person: on the entry notice, on a click inside the panel (which does nothing else) and on a send (which is not sent)', async t => {
  const { page, db } = await fixture(t, { turns: [TURN1], mine: [SAVED], chats: { cw_55555555: OLD } });
  const entry = async () => { const g = db.gets; await page.evaluate(() => window.postMessage({ type: 'ai365-home-entry', entry: 'tab' }, location.origin)); await until(() => db.gets > g); };
  const openSaved = async () => {
    await page.click('[data-wa="mine"]');
    await page.click('[data-wa-open="cw_55555555"]');
    await page.waitForFunction(() => window.AI365_widgetAgent.state().key === 'cw_55555555' && window.AI365_widgetAgent.state().msgs.length === 2 && !window.AI365_widgetAgent.state().busy);
  };
  await openAgent(page);
  await openSaved();
  // 부모 앱이 알려 주면(진입 메시지) 처음 상태로 / told by the parent app (the entry message), the panel resets
  await asUser(page, 12);
  await entry();
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === '');
  assert.deepEqual([await page.locator('.wa-nmtx').innerText(), await page.locator('#toast').innerText()], ['새 위젯', MOVED]);
  // 알림 없이 바뀌면: 패널 안을 누르는 순간 처음 상태로, 그 클릭(이름 바꾸기)은 하지 않는다 / a silent switch: the first click inside the panel resets it and does nothing else
  await asUser(page, null);
  await entry();
  await openSaved();
  await asUser(page, 12);
  await clearToast(page);
  await page.click('[data-wa="rename"]');
  assert.deepEqual([(await state(page)).key, (await state(page)).msgs, await page.locator('#waNmIn').count(), await page.locator('#toast').innerText()], ['', [], 0, MOVED]);
  // 알림 없이 바뀐 채 보내면: 보내지 않고 처음 상태로 / a send after a silent switch is not sent; the panel resets
  await asUser(page, null);
  await entry();
  await openSaved();
  await asUser(page, 12);
  await clearToast(page);
  await page.fill('#waIn', '그대로 둬');
  await page.press('#waIn', 'Enter');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === '');
  assert.deepEqual([(await state(page)).msgs, db.turnBodies.length, await page.locator('#toast').innerText()], [[], 0, MOVED]);
  await page.waitForTimeout(200);
  assert.deepEqual([db.posts.length, db.puts.length, db.chatPuts.length, db.dashPuts.length], [0, 0, 0, 0]);   // 새 사람에게 아무것도 저장하지 않았다 / nothing saved for the new person
});

test('턴이 도는 사이 · 이름을 바꾸는 사이 사람이 바뀌면(뷰애즈) 결과를 버리고 처음 상태로, 위젯 · 대화 · 배치 어느 것도 저장하지 않는다 / a person change during a held turn or an open rename drops the result and resets; no widget, conversation or layout save', async t => {
  const { page, db } = await fixture(t, { turns: [TURN2], holdTurn: true, mine: [SAVED], chats: { cw_55555555: OLD }, layout: ROWS.concat(['cw_55555555 0 4 1 2']) });
  await page.click('#dash > .wg[data-wg="cw_55555555"] [data-hd-wa]');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().msgs.length === 2 && !window.AI365_widgetAgent.state().busy);
  await page.fill('#waIn', '카드로 바꿔줘');
  await page.press('#waIn', 'Enter');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().busy);
  assert.equal(db.turnBodies[0].acting_user_id, '');
  // 턴이 도는 사이 바뀌었다: 끝난 답은 버리고 처음 상태로 / switched during the turn: the finished answer is dropped and the panel resets
  await asUser(page, 12);
  db.hold = false; db.held.splice(0).forEach(f => f());
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === '' && !window.AI365_widgetAgent.state().busy);
  assert.equal(await page.locator('#toast').innerText(), MOVED);
  assert.deepEqual([(await state(page)).msgs, (await state(page)).widget], [[], PURE.waBlank()]);
  await page.waitForTimeout(300);
  assert.deepEqual([db.posts.length, db.puts.length, db.chatPuts.length, db.dashPuts.length], [0, 0, 0, 0]);
  assert.equal(await page.evaluate(() => window.AI365_homeDash.previewOf('cw_55555555')), null);   // 홈의 그 칸은 저장된 모습 그대로 / the home cell keeps its stored drawing
  assert.equal(await cell(page, 'cw_55555555').locator('.hd-nm').innerText(), '지점별 매출');
  // 이름을 바꾸는 사이 바뀌었다: Enter 를 눌러도 저장하지 않고 처음 상태로 / switched while renaming: Enter saves nothing and resets
  await asUser(page, null);
  await page.click('#dash > .wg[data-wg="cw_55555555"] [data-hd-wa]');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === 'cw_55555555' && !window.AI365_widgetAgent.state().busy);
  await page.click('[data-wa="rename"]');
  await page.fill('#waNmIn', '바꾼 이름');
  await asUser(page, 12);
  await clearToast(page);
  await page.press('#waNmIn', 'Enter');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === '');
  assert.equal(await page.locator('#toast').innerText(), MOVED);
  await page.waitForTimeout(300);
  assert.deepEqual([db.posts.length, db.puts.length, db.chatPuts.length, db.dashPuts.length], [0, 0, 0, 0]);
  assert.equal(await cell(page, 'cw_55555555').locator('.hd-nm').innerText(), '지점별 매출');
});

test('스트림: 생각 과정이 진행 이벤트를 따라 그려지고, 아직 없는 위젯의 초안은 홈의 빈 첫 자리 점선 카드로, 끝나면 진짜 위젯이 그 자리에 / the stream: thinking follows progress events, a draft of a widget not made yet is a dashed card at the first free spot, and the real widget lands there', async t => {
  const { page, db } = await fixture(t, { width: WIDE });
  const sse2 = await liveStream(page);
  await asUser(page, 7);                                                              // 패널을 열기 전의 신원 / the identity before the panel opens
  await openAgent(page);
  await page.fill('#waIn', '오늘 원달러 환율 위젯을 만들어줘');
  await page.press('#waIn', 'Enter');
  await page.waitForFunction(() => window.__sse.ctrl);
  const sent = await page.evaluate(() => window.__sse.bodies[0]);
  assert.deepEqual([sent.acting_user_id, sent.message], ['7', '오늘 원달러 환율 위젯을 만들어줘']);   // 권한은 지금 신원의 것 / the current identity's permissions
  assert.equal(await page.locator('.wa-a.live .wa-think').innerText(), '생각 중입니다');
  for (const e of FX_EVENTS.slice(0, 3)) await sse2.write(sse(e[0], e[1]));          // 찾을 곳 · 라운드 · 사내 데이터 시작 / plan, round, data starts
  await page.waitForSelector('.wa-a.live .wa-kc.data');
  assert.equal(await page.locator('.wa-a.live .wa-ln >> nth=0').innerText(), '의도 판단 — 사내 데이터에서 찾아 KPI 카드(으)로 보여 주기');
  assert.equal(await page.locator('.wa-a.live .wa-scnt').innerText(), '사내 리소스 1개');
  assert.equal(await page.locator('.wa-a.live .wa-kc.data .wa-kc-tx i').innerText(), '찾는 중');
  assert.equal(await page.locator('.wa-a.live .wa-kc.data .wa-ln.run').innerText(), '허용된 데이터에서 조회하는 중…');
  assert.deepEqual(await page.locator('.wa-a.live .wa-tk-gh').allInnerTexts(), ['1단계 · 1개 작업 실행 중']);
  assert.equal(await page.locator('.wa-a.live .wa-think.sm').innerText(), '사내 데이터에서 찾는 중');
  assert.equal(await page.locator('.wa-a.live .wa-res').count(), 1);
  assert.equal(await page.locator('#dash .hd-ghost').count(), 0);                    // 초안 전에는 그릴 것이 없다 / nothing to draw before the draft
  // 의도 판단이 끝나면 미리 그린 위젯 = 홈의 빈 첫 자리 점선 카드(새 위젯 표시) / the early draft = a dashed card at the first free spot, chipped 'new widget'
  await sse2.write(sse('draft', { model: FX_DRAFT }));
  await page.waitForSelector('#dash .hd-ghost .hw-wait');
  const ghost = page.locator('#dash > .wg.hd-ghost');
  assert.deepEqual([await ghost.locator('.hd-nm').innerText(), await ghost.locator('.hd-new').innerText()], ['오늘 환율', '새 위젯']);
  assert.deepEqual(await ghost.locator('.hw-kt.sk .l').allInnerTexts(), ['원달러']);
  const at = await spot(ghost);
  assert.deepEqual(at, ['1 / span 1', '5 / span 1']);                                // 빈 첫 자리 / the first free spot
  // 실제 크기 = 홈 격자 한 칸(열 너비 × 240) / real size = one home grid cell (a column wide, 240 high)
  const gb = await ghost.boundingBox(), col = await page.evaluate(() => window.AI365_homeDash.geometry(document.getElementById('dash').clientWidth).tracks.w[0]);
  assert.deepEqual([Math.abs(gb.width - col) <= 1, Math.round(gb.height)], [true, 240]);
  assert.deepEqual(await page.evaluate(() => window.AI365_homeDash.ghostOf()), FX_DRAFT);
  assert.equal(await page.locator('.wa-nmtx').innerText(), '새 위젯');               // 작업본은 아직 그대로 / the working copy is unchanged so far
  assert.equal(db.posts.length, 0);
  // 사내에서 못 찾으면 웹으로 / nothing in the company: the web
  for (const e of FX_EVENTS.slice(4, 6)) await sse2.write(sse(e[0], e[1]));
  await page.waitForSelector('.wa-a.live .wa-kc.web');
  assert.equal(await page.locator('.wa-a.live .wa-kc.data .wa-ln.fail').innerText(), '찾지 못했습니다 — 사내 데이터에서 찾지 못했습니다');
  assert.equal(await page.locator('.wa-a.live .wa-kc.web .wa-ln.run').innerText(), '사내에서 찾지 못해 웹에서 찾는 중…');
  assert.deepEqual(await page.locator('.wa-a.live .wa-scnt').allInnerTexts(), ['사내 리소스 1개', '외부 리소스 1개']);
  for (const e of FX_EVENTS.slice(6)) await sse2.write(sse(e[0], e[1]));
  await page.waitForFunction(() => document.querySelectorAll('.wa-a.live .wa-kc.edit').length === 1);
  assert.equal(await page.locator('.wa-a.live .wa-think.sm').innerText(), '답을 정리하는 중');
  await sse2.end(sse('done', FX_TURN));
  await idle(page);
  assert.deepEqual((await state(page)).widget, FX_WIDGET);
  // 끝나면 바로 만들어 그 자리에 놓는다(점선 카드는 진짜 위젯으로) / once done it is made and placed on that spot (the dashed card becomes the real widget)
  assert.deepEqual(db.posts, [{ acting_user_id: '7', spec: FX_WIDGET }]);
  assert.deepEqual(db.dashPuts.map(p => [p.acting_user_id, rowsOf(p.items).filter(r => r.indexOf('cw_') === 0)]), [['7', ['cw_99990001 0 4 1 1']]]);
  assert.deepEqual([await page.locator('#dash .hd-ghost').count(), await page.evaluate(() => window.AI365_homeDash.ghostOf())], [0, null]);
  const home = cell(page, 'cw_99990001');
  assert.deepEqual(await spot(home), at);
  assert.equal(await home.locator('.hw-kt .v').innerText(), '1,350.5원');
  assert.equal(await home.locator('.hw-wait').count(), 0);
  assert.deepEqual(await home.locator('.hw-src > span').allInnerTexts(), ['웹 검색', 'news.example', '11/16 10:00']);
  assert.equal(await page.locator('#toast').innerText(), '새 위젯을 홈에 놓았습니다');
  // 끝난 생각 과정 = 받은 그대로(+ 쓴 갈래) / the finished thinking as received (plus the branch used)
  assert.deepEqual(await page.locator('.wa-kc.web .wa-ln').allInnerTexts(), ['news.example에서 실시간 값을 받았습니다', '이 결과를 위젯에 넣었습니다']);
  assert.equal(await page.locator('.wa-kc.web .wa-kc-tx i').innerText(), '외부 출처 1개');
  assert.equal(await page.locator('.wa-kc.data .wa-kc-tx i').innerText(), '찾지 못함');
  assert.deepEqual(await page.locator('.wa-tk-l').allInnerTexts(), ['데이터 가져오기 · 웹 검색']);
  assert.equal(await page.locator('.wa-fr-tg .n').innerText(), '리소스 2 · 도구 1');
  // 자세히 = 근거 목록(주소는 새 창) / Details lists the references (links open a new tab)
  await page.click('.wa-kc.web .wa-kc-more');
  assert.deepEqual(await page.evaluate(() => { const a = document.querySelector('.wa-kc.web .wa-kc-dt a'); return [a.textContent, a.getAttribute('href'), a.target, a.rel]; }),
    ['news.example', 'https://news.example/fx', '_blank', 'noopener noreferrer']);
  assert.equal(await page.locator('.wa-kc.web .wa-kc-more').getAttribute('aria-expanded'), 'true');
  // 답 · 바뀐 점 · 다음에 해 볼 것 · 출처 / reply, changes, suggestions, sources
  assert.equal(await page.locator('.wa-a .wa-tx').innerText(), '오늘 환율을 넣었습니다.');
  assert.deepEqual(await page.locator('.wa-chg-r').allInnerTexts(), ['제목\n오늘 환율', '보기\nKPI 카드 1개 + 목록 1건', '출처\n웹 검색 · news.example']);
  assert.deepEqual(await page.locator('.wa-nx button').allInnerTexts(), ['글로도 요약해줘', '인사이트를 한 줄 써줘']);
  assert.deepEqual(await page.evaluate(() => [].map.call(document.querySelectorAll('.wa-src a'), a => [a.textContent, a.getAttribute('href')])), [['news.example', 'https://news.example/fx']]);
  // 리소스 › = 정보 탭(출처 · 가져온 시각 · 새로 가져오는 간격 · 구성 · 크기 + [지금 새로 가져오기]) / Resources › switches to the info tab
  await page.click('.wa-a .wa-res');
  assert.equal((await state(page)).tab, 'info');
  assert.equal(await page.locator('#waInfo.flash').count(), 1);
  assert.deepEqual(await page.locator('#waInfo .wa-pnl-r > span:last-child').allInnerTexts(),
    ['카드 · 웹 검색 · news.example', '11/16 10:00', '웹 30분마다', 'KPI 카드 1개 + 목록 1건', '가로 1 × 세로 1 · 홈에 놓임']);
  assert.equal(await page.locator('#waInfo [data-wa-act="refresh"]').innerText(), '지금 새로 가져오기');
  assert.equal(db.turnBodies.length, 0);                                           // 가짜 서버까지 가지 않았다 / the fake server was never asked
});

test('멈추기: 스트림을 끊고 받은 데까지 남기며(저장하지 않는다), 대기 요청은 멈춘 뒤 보내지 않는다 / stop drops the stream, keeps what came (saving nothing), and the queue waits', async t => {
  const { page, db } = await fixture(t);
  const sse2 = await liveStream(page);
  await openAgent(page);
  await page.fill('#waIn', '지점별 매출 차트 위젯을 만들어줘');
  await page.press('#waIn', 'Enter');
  await page.waitForFunction(() => window.__sse.ctrl);
  for (const e of FX_EVENTS.slice(0, 4)) await sse2.write(sse(e[0], e[1]));          // 초안까지 / up to the draft
  await page.waitForSelector('.wa-a.live .wa-kc.data');
  await page.waitForSelector('#dash .hd-ghost');
  // 기다리는 동안 쓴 요청 = Queue(고친 · 지운 · 남은 것) / requests written meanwhile go to the Queue
  for (const q of ['첫째 요청', '둘째 요청', '셋째 요청']) { await page.fill('#waIn', q); await page.press('#waIn', 'Enter'); }
  assert.equal(await page.inputValue('#waIn'), '');
  assert.equal(await page.locator('.wa-q-hd').innerText(), 'Queue · 3');
  assert.deepEqual(await page.locator('.wa-q-tx').allInnerTexts(), ['첫째 요청', '둘째 요청', '셋째 요청']);
  await page.click('[data-wa-qdel="1"]');
  await page.click('[data-wa-qedit="1"]');
  assert.equal(await page.inputValue('#waIn'), '셋째 요청');
  assert.deepEqual((await state(page)).queue, [{ text: '첫째 요청', source: 'auto' }]);
  await page.fill('#waIn', '');
  await page.click('[data-wa="send"]');                                             // ■ 멈추기 / stop
  await idle(page);
  assert.equal(await page.evaluate(() => window.__sse.aborted), 1);
  const last = (await state(page)).msgs.slice(-1)[0];
  assert.deepEqual([last.stopped, last.q], [true, '지점별 매출 차트 위젯을 만들어줘']);
  assert.equal(await page.locator('.wa-a .wa-tx.muted').innerText(), '멈췄습니다. 위젯은 바뀌지 않았습니다.');
  assert.equal(await page.locator('.wa-kc.data .wa-ln.fail').innerText(), '멈춰서 끝까지 찾지 않았습니다');   // 찾던 곳은 '멈춤' / the running place reads stopped
  assert.equal(await page.locator('.wa-kc.data .wa-kc-tx i').innerText(), '멈춤');
  assert.deepEqual(await page.locator('.wa-tk-gh').allInnerTexts(), ['1단계 · 1개 작업 실행 멈춤']);
  assert.deepEqual((await state(page)).widget, PURE.waBlank());
  assert.equal(await page.locator('#dash .hd-ghost').count(), 0);                    // 멈추면 초안 카드도 치운다 / stopping clears the draft card
  await page.waitForTimeout(500);
  assert.equal(await page.evaluate(() => window.__sse.bodies.length), 1);           // 멈춘 뒤 대기 요청은 가지 않는다 / no queued send after a stop
  assert.deepEqual([db.posts.length, db.chatPuts.length], [0, 0]);                  // 저장할 것이 없다 / nothing to save
  assert.equal(await page.locator('.wa-q-hd').innerText(), 'Queue · 1');
  assert.deepEqual(await acts(page.locator('.wa-a .wa-ft button')), ['retry']);
  // 다시 시도 = 같은 요청을 다시(멈춘 짝은 지운다) / try again resends the request (the stopped pair is removed)
  await page.click('.wa-a .wa-ft [data-wa-act="retry"]');
  await page.waitForFunction(() => window.__sse.bodies.length === 2);
  assert.equal(await page.evaluate(() => window.__sse.bodies[1].message), '지점별 매출 차트 위젯을 만들어줘');
  assert.equal((await state(page)).msgs.filter(m => m.stopped).length, 0);
  // 직접 보낸 턴이 끝나면(저장 · 홈에 놓기까지) 대기 요청이 이어서 간다 / once a turn sent by hand ends (saved and placed), the queue goes on
  await sse2.end(sse('done', FX_TURN));
  await page.waitForFunction(() => window.__sse.bodies.length === 3, null, { timeout: 5000 });
  assert.equal(await page.evaluate(() => window.__sse.bodies[2].message), '첫째 요청');
  assert.equal(db.posts.length, 1);
  assert.equal(await page.locator('#waQ').isHidden(), true);
});

test('발치 · 정보 · 기록: 이 턴 되돌리기 · 크기 칸(홈에서 바로) · 지난 모습으로 되돌리기, 하나하나 바로 저장해 홈에 / the footer, info and history: undo a turn, size cells (on Home at once) and restoring an earlier state, each saved to Home at once', async t => {
  const { page, db } = await fixture(t, { turns: [FX_TURN, TURN2], width: WIDE });
  await openAgent(page);
  await send(page, '오늘 환율 위젯');
  await send(page, '카드 숫자를 1,200건으로');
  assert.deepEqual((await state(page)).widget, DRAFT2);
  const home = cell(page, 'cw_99990001');
  assert.equal(await home.locator('.hw-kt .v').innerText(), '1,200건');
  // 만든 턴은 되돌릴 곳이 없고, 둘째 턴의 '이 턴 되돌리기' = 그 턴 전 모습(지금 모습은 기록에 남는다)
  // the creating turn has nothing to undo to; the second turn's 'undo this turn' goes back to before it (the current state stays in the history)
  assert.equal(await page.locator('.wa-a >> nth=0').locator('[data-wa-act="undo-turn"]').count(), 0);
  await page.click('.wa-a >> nth=1 >> [data-wa-act="undo-turn"]');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().label.indexOf('restore:') === 0 && !window.AI365_widgetAgent.state().busy);
  let s = await state(page);
  assert.deepEqual([s.widget, s.label, s.undo], [FX_WIDGET, 'restore:turn:오늘 환율 위젯', 2]);
  assert.deepEqual(db.puts.map(p => p.body.spec), [DRAFT2, FX_WIDGET]);
  assert.equal(await home.locator('.hw-kt .v').innerText(), '1,350.5원');
  assert.equal(await page.locator('#toast').innerText(), '되돌렸습니다');
  await tab(page, 'hist');
  assert.deepEqual(await page.locator('#waHist .wa-hs .l').allInnerTexts(), ['되돌림 · 오늘 환율 위젯', '카드 숫자를 1,200건으로', '오늘 환율 위젯']);
  await page.click('[data-wa="undo"]');                                              // 되돌린 것도 되돌린다 / a restore can be undone
  await idle(page);
  assert.deepEqual((await state(page)).widget, DRAFT2);
  assert.deepEqual(db.puts.map(p => p.body.spec), [DRAFT2, FX_WIDGET, DRAFT2]);
  assert.equal(await home.locator('.hw-kt .v').innerText(), '1,200건');
  // 크기 칸(정보 탭): 이어서 고르면 기록 한 칸, 고를 때마다 저장하고 홈에 놓인 칸도 바로 그 크기로(배치 저장) / size cells: consecutive picks share one step; each pick saves and resizes the placed cell
  await tab(page, 'info');
  assert.equal(await page.locator('.wa-size-h').innerText(), '고르면 홈에서 바로 바뀝니다');
  const undo0 = (await state(page)).undo, dash0 = db.dashPuts.length;
  await page.click('[data-wa-size="w:2"]');
  await idle(page);
  await page.click('[data-wa-size="h:3"]');
  await idle(page);
  s = await state(page);
  assert.deepEqual([s.widget.size, s.undo - undo0, s.label], [{ w: 2, h: 3 }, 1, 'size:2x3']);
  assert.deepEqual(db.puts.slice(-2).map(p => p.body.spec.size), [{ w: 2, h: 1 }, { w: 2, h: 3 }]);
  assert.deepEqual(db.dashPuts.slice(dash0).map(p => rowsOf(p.items).filter(r => r.indexOf('cw_99990001 ') === 0)[0]), ['cw_99990001 0 4 2 1', 'cw_99990001 0 4 2 3']);
  assert.deepEqual(await spot(home), ['1 / span 2', '5 / span 3']);
  assert.deepEqual(await page.locator('#waSize .g button.on').allInnerTexts(), ['2', '3']);
  assert.equal(await page.locator('#waInfo .wa-pnl-r >> nth=4').locator('span:last-child').innerText(), '가로 2 × 세로 3 · 홈에 놓임');
  // 지금 크기를 다시 누르면 아무 일도 없다(기록 · 저장 없음) / clicking the size already shown does nothing (no history step, no save)
  const was = [db.puts.length, db.dashPuts.length, (await state(page)).undo, (await state(page)).label];
  await page.click('[data-wa-size="h:3"]');
  await page.click('[data-wa-size="w:2"]');
  await page.waitForTimeout(200);
  assert.deepEqual([db.puts.length, db.dashPuts.length, (await state(page)).undo, (await state(page)).label], was);
  // 기록: 미리보기(홈의 그 칸) → 되돌리기 / history: a preview (in the home cell), then restore
  await tab(page, 'hist');
  assert.deepEqual(await page.locator('#waHist .wa-hs .l').allInnerTexts(), ['크기 가로 2 × 세로 3', '카드 숫자를 1,200건으로', '오늘 환율 위젯']);
  await page.click('#waHist .wa-hs button >> nth=2');
  await page.waitForFunction(() => !!window.AI365_widgetAgent.state().peek);
  assert.equal(await page.locator('#waHist .wa-hs button.on').count(), 1);
  assert.equal(await page.locator('#waPeek > span').innerText(), '지난 모습 미리보기 — 오늘 환율 위젯');
  assert.equal(await home.locator('.hw-kt .v').innerText(), '1,350.5원');            // 지난 모습은 홈의 그 칸에 / the earlier state shows in the home cell
  const puts0 = db.puts.length;
  await page.click('#waPeek [data-wa-act="restore"]');
  await page.waitForFunction(() => !window.AI365_widgetAgent.state().peek && window.AI365_widgetAgent.state().label.indexOf('restore:') === 0 && !window.AI365_widgetAgent.state().busy);
  s = await state(page);
  assert.deepEqual([s.widget, s.label], [FX_WIDGET, 'restore:turn:오늘 환율 위젯']);
  assert.deepEqual(db.puts.slice(puts0).map(p => p.body.spec), [FX_WIDGET]);
  assert.equal(await page.evaluate(() => window.AI365_homeDash.previewOf('cw_99990001')), null);
  assert.equal(await home.locator('.hw-kt .v').innerText(), '1,350.5원');
  assert.equal(db.models.length, 0);                                                 // 모델이 있는 기록은 서버에 묻지 않는다 / states with a model need no server
  await until(() => db.chatPuts.length === db.posts.length + db.puts.length);          // 저장마다 대화도 / the conversation after every save
});

test('크기 칸 · [지금 새로 가져오기]: 놓인 위젯은 놓인 크기로, 고르면 바로 저장해 홈에(연 뒤 첫 고르기는 기록 한 칸 — 지난번 마지막이 크기였어도), 크기 되돌리기는 놓였던 칸으로(배치 저장), 새로 가져오면 바로 저장 / size cells and refresh now: a placed widget shows its placed size; a pick saves to Home at once (the first pick after opening gets its own history step, even after a saved size label); undoing a resize returns to the placed cell (layout saved); refreshing saves at once', async t => {
  const PLACED = Object.assign({}, SAVED, { spec: Object.assign({}, SAVED.spec, { origins: FX_WIDGET.origins }) });
  const FRESH = Object.assign({}, PLACED.spec, { title: '새로 가져온 매출', size: { w: 1, h: 2 } });
  const SIZED = { v: 1, label: 'size:1x2', at: '2026-11-18T10:00:00', msgs: [], hist: [] };   // 지난번 마지막 일 = 크기 고르기 / last time's last change was a size pick
  const { page, db } = await fixture(t, { mine: [PLACED], chats: { cw_55555555: SIZED }, layout: ROWS.concat(['cw_55555555 1 4 1 2']), width: WIDE,
    refresh: { changed: true, widget: FRESH, model: Object.assign({}, CHART_MODEL, { title: '새로 가져온 매출', size: { w: 1, h: 2 } }), fetched_at: '2026-11-19T10:00:00' } });
  // 만든 위젯 머리의 아이콘으로 연다 / opened from the icon on the made widget
  await page.click('#dash > .wg[data-wg="cw_55555555"] [data-hd-wa]');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === 'cw_55555555' && !window.AI365_widgetAgent.state().busy);
  assert.deepEqual([(await state(page)).label, (await state(page)).undo], ['size:1x2', 0]);
  // 놓인 위젯은 놓인 크기로 보인다 / a placed widget shows at its placed size
  await tab(page, 'info');
  assert.deepEqual(await page.locator('#waSize .g button.on').allInnerTexts(), ['1', '2']);
  assert.equal(await page.locator('.wa-size-h').innerText(), '고르면 홈에서 바로 바뀝니다');
  assert.equal(await page.locator('#waInfo .wa-pnl-r >> nth=4').locator('span:last-child').innerText(), '가로 1 × 세로 2 · 홈에 놓임');
  // 지금 크기를 누르면 아무 일도 없다 / the size already shown does nothing
  await page.click('[data-wa-size="h:2"]');
  await page.waitForTimeout(200);
  assert.deepEqual([db.puts.length, db.dashPuts.length, (await state(page)).undo], [0, 0, 0]);
  // 고르면 저장하고 홈에 놓인 위젯도 그 크기로(배치 저장). 연 뒤 첫 고르기는 기록 한 칸, 이어 고른 것은 같은 칸
  // a pick saves and the placed widget takes it (layout saved); the first pick after opening gets its own step, the next one joins it
  await page.click('[data-wa-size="w:2"]');
  await idle(page);
  await page.click('[data-wa-size="h:3"]');
  await idle(page);
  let s = await state(page);
  assert.deepEqual([s.undo, s.label, s.widget.size], [1, 'size:2x3', { w: 2, h: 3 }]);
  assert.deepEqual(db.puts.map(p => p.body.spec.size), [{ w: 2, h: 2 }, { w: 2, h: 3 }]);
  assert.deepEqual(db.dashPuts.map(p => rowsOf(p.items).filter(r => r.indexOf('cw_55555555 ') === 0)[0]), ['cw_55555555 1 4 2 2', 'cw_55555555 1 4 2 3']);
  assert.deepEqual(await spot(cell(page, 'cw_55555555')), ['2 / span 2', '5 / span 3']);
  // 되돌리기 = 고르기 전에 놓여 있던 칸(1 × 2)으로, 배치도 저장한다 / undo goes back to the cell as placed before the picks (1 × 2) and saves the layout too
  await page.click('[data-wa="undo"]');
  await idle(page);
  s = await state(page);
  assert.deepEqual([s.undo, s.label, s.widget.size], [0, 'size:1x2', { w: 1, h: 2 }]);
  assert.deepEqual(db.puts.slice(-1)[0].body.spec.size, { w: 1, h: 2 });
  assert.deepEqual(rowsOf(db.dashPuts.slice(-1)[0].items).filter(r => r.indexOf('cw_55555555 ') === 0), ['cw_55555555 1 4 1 2']);
  assert.deepEqual(await spot(cell(page, 'cw_55555555')), ['2 / span 1', '5 / span 2']);
  assert.deepEqual(await page.locator('#waSize .g button.on').allInnerTexts(), ['1', '2']);
  // 지금 새로 가져오기 → 바로 저장(배치는 그대로) / refresh now → saved at once (the layout untouched)
  const dash0 = db.dashPuts.length, puts0 = db.puts.length;
  await page.click('#waInfo [data-wa-act="refresh"]');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().label === 'refresh:' && !window.AI365_widgetAgent.state().busy);
  assert.equal(db.refreshes.length, 1);
  assert.deepEqual(db.refreshes[0].widget, Object.assign({}, PLACED.spec, { size: { w: 1, h: 2 } }));
  assert.equal(await page.locator('.wa-nmtx').innerText(), '새로 가져온 매출');
  assert.equal(await page.locator('#toast').innerText(), '새로 가져왔습니다');
  assert.deepEqual(db.puts.slice(puts0), [{ key: 'cw_55555555', body: { acting_user_id: '', spec: FRESH } }]);
  assert.deepEqual([db.dashPuts.length, (await state(page)).dirty], [dash0, false]);
  assert.equal(await cell(page, 'cw_55555555').locator('.hd-nm').innerText(), '새로 가져온 매출');
});

test('대화 복원은 기다림: 받기 전에 보낸 요청은 Queue 에서 기다리고(보내면 대화 탭으로), 받지 못하면 대화를 저장하지 않는다(독립 검토) / restoring waits (a queued send returns to the chat tab); failures never overwrite the saved conversation', async t => {
  const OLD2 = { v: 1, label: 'turn:예전', at: '2026-11-18T10:00:00', msgs: [{ role: 'user', text: '예전 요청' }, { role: 'agent', text: '예전 답', q: '예전 요청' }],
    hist: [{ id: 'h1', label: 'new:', at: '2026-11-18T09:00:00', widget: DRAFT2 }] };
  const SAME = { widget: SAVED.spec, model: CHART_MODEL, reply: '그대로예요.', trace: [], ask: null };
  const { page, db } = await fixture(t, { turns: [SAME, SAME], mine: [SAVED], chats: { cw_55555555: OLD2 }, holdChat: true });
  await openAgent(page);
  await page.click('[data-wa="mine"]');
  await page.click('[data-wa-open="cw_55555555"]');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().busy);           // 받는 동안은 기다림 / waiting while it arrives
  await page.fill('#waIn', '그대로 둬');
  await page.press('#waIn', 'Enter');
  assert.deepEqual([(await state(page)).queue.length, db.turnBodies.length], [1, 0]);   // 받기 전 요청은 Queue 로 / queued until restored
  await tab(page, 'info');
  assert.equal(await page.locator('[data-wa-size="w:2"]').isDisabled(), true);       // 편집도 기다린다 / edits wait too
  assert.equal(await page.locator('[data-wa-act="delete"]').isDisabled(), true);
  db.heldChat.splice(0).forEach(f => f());
  await page.waitForFunction(() => window.AI365_widgetAgent.state().msgs.length === 4, null, { timeout: 5000 });
  assert.equal((await state(page)).tab, 'chat');                                      // 요청을 보내면 대화 탭으로 / a send switches to the chat tab
  const s = await state(page);
  assert.deepEqual(s.msgs.map(m => m.text), ['예전 요청', '예전 답', '그대로 둬', '그대로예요.']);   // 복원 뒤에 이어서 / after the restore
  await until(() => db.chatPuts.length === 1);
  assert.deepEqual(db.chatPuts[0].body.chat.msgs.length, 4);                          // 저장본을 잃지 않는다 / nothing lost
  assert.equal(db.chatPuts[0].body.chat.hist.length, 1);
  assert.equal(db.puts.length, 0);                                                    // 바뀐 것이 없으면 위젯은 저장하지 않는다 / no change, no widget save
  // 받지 못하면 알리고, 이번 대화는 저장하지 않는다 / a failed load is reported and this session's conversation is not saved
  db.chatFail = true;
  db.holdChat = false;
  await page.click('[data-wa="mine"]');
  await page.click('[data-wa-open="cw_55555555"]');
  await idle(page);
  assert.equal(await page.locator('#toast').innerText(), '대화 기록을 불러오지 못해 이번 대화는 저장하지 않습니다');
  await send(page, '그대로 둬');
  await page.waitForTimeout(300);
  assert.equal(db.chatPuts.length, 1);
});

test('저장된 대화에 위험한 값이 있어도 스크립트가 돌지 않고 화면도 멈추지 않는다(독립 검토) / a hostile saved conversation runs no script and never locks the screen', async t => {
  const evil = 'web"><img src=x onerror="window.__xss=1">';
  const BAD = { v: 1, label: 'turn:x', at: '', hist: [], msgs: [{ role: 'user', text: '<b>요청</b>' },
    { role: 'agent', text: '<img src=x onerror="window.__xss=2">', frame: { order: [evil, 'docs'], cards: { [evil]: { status: 'ok' }, docs: { status: 'ok', note: { refs: [{ label: '<i>a</i>', url: 'javascript:window.__xss=3' }] } } },
      picks: ['docs'], rounds: [{ no: 1, tools: 'x' }], tools: [{ tool: '<b>t</b>', label: '<b>l</b>', ok: true, round: 1 }] }, changes: [{ k: 'view', v: null }], refs: [{ label: 'r', url: 'javascript:x' }] },
    { role: 'agent', frame: { order: 'web', cards: null }, changes: 'x', text: 3 }] };
  const { page, db } = await fixture(t, { turns: [TURN1], mine: [SAVED], chats: { cw_55555555: BAD } });
  await openAgent(page);
  await page.click('[data-wa="mine"]');
  await page.click('[data-wa-open="cw_55555555"]');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().msgs.length === 3 && !window.AI365_widgetAgent.state().busy);
  await page.click('.wa-fr-tg >> nth=0');                                            // 펼쳐서 다 그린다 / unfold so everything draws
  await page.waitForTimeout(200);
  assert.equal(await page.evaluate(() => window.__xss), undefined);
  assert.equal(await page.locator('#waMsgs img').count(), 0);
  assert.deepEqual(await page.locator('.wa-kc:not(.edit)').evaluateAll(k => k.map(x => x.className)), ['wa-kc docs']);
  assert.equal(await page.locator('.wa-a .wa-tx >> nth=0').innerText(), '<img src=x onerror="window.__xss=2">');   // 글로만 / as text only
  assert.equal(await page.locator('.wa-src a').count(), 0);                              // javascript: 주소는 링크가 아니다 / no javascript: links
  // 화면은 멈추지 않는다: 다음 요청이 그대로 가고 바로 저장된다 / the screen keeps working: the next request goes and is saved at once
  await send(page, 'KPI 카드 위젯을 만들어줘');
  assert.equal(await page.locator('.wa-af').count(), 1);
  assert.deepEqual(db.puts.map(p => [p.key, p.body.spec]), [['cw_55555555', DRAFT1]]);
});

/* ── 2026-11-20 패널 / the panel ── */
test('만든 위젯 머리의 아이콘 = 그 위젯과 대화를 패널에 연다(기본 위젯에는 없다), 잇달아 누르면 마지막 것만, 같은 위젯은 다시 읽지 않고, 일하는 동안은 다른 위젯을 열지 않는다 / the icon on a made widget opens it with its conversation (built-ins have none); quick clicks open only the last one, the same widget is not read again, and nothing else opens while working', async t => {
  const { page, db } = await fixture(t, { turns: [TURN2], holdTurn: true, mine: [SAVED, FXW], chats: { cw_55555555: OLD },
    layout: ROWS.concat(['cw_55555555 0 4 1 2', 'cw_66666666 1 4 1 1']) });
  // 아이콘은 놓인 만든 위젯에만 / the icon sits on placed made widgets only
  assert.deepEqual(await page.locator('#dash [data-hd-wa]').evaluateAll(b => b.map(x => [x.dataset.hdWa, x.title, x.closest('.wg').dataset.wg])),
    [['cw_55555555', '위젯 에이전트로 고치기', 'cw_55555555'], ['cw_66666666', '위젯 에이전트로 고치기', 'cw_66666666']]);
  assert.equal(await page.locator('#dash > .wg:not(.hd-cw) [data-hd-wa]').count(), 0);
  assert.deepEqual(await cell(page, 'cw_55555555').locator('.wg-head > *').evaluateAll(e => e.map(x => x.className)), ['hd-nm', 'sp', 'hd-btn hd-wa']);
  assert.equal(await cell(page, 'cw_55555555').locator('.wg-head .hd-nm').innerText(), '지점별 매출');
  assert.equal(await page.locator('#waView').count(), 0);
  // 두 위젯의 아이콘을 잇달아 누르면 마지막 것만 연다(내 위젯 읽기는 둘, 대화는 마지막 것만) / two quick icon clicks open only the last widget
  await page.evaluate(() => { document.querySelector('#dash [data-hd-wa="cw_66666666"]').click(); document.querySelector('#dash [data-hd-wa="cw_55555555"]').click(); });
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === 'cw_55555555' && window.AI365_widgetAgent.state().msgs.length === 2 && !window.AI365_widgetAgent.state().busy);
  await page.waitForTimeout(200);
  assert.deepEqual([await page.locator('body.wa-open').count(), await page.getAttribute('#waBtn', 'aria-pressed')], [1, 'true']);
  assert.deepEqual([db.mineGets, db.chatGets], [2, ['cw_55555555']]);                 // 앞의 위젯은 열지 않았다 / the first widget never opened
  assert.equal(await page.locator('.wa-nmtx').innerText(), '지점별 매출');
  assert.deepEqual(await page.locator('#dash > .wg.hd-wa-on').evaluateAll(e => e.map(x => x.dataset.wg)), ['cw_55555555']);
  // 같은 위젯의 아이콘은 다시 읽지 않는다 / the same widget's icon reads nothing again
  await page.click('#dash > .wg[data-wg="cw_55555555"] [data-hd-wa]');
  await page.waitForTimeout(200);
  assert.deepEqual([db.mineGets, db.chatGets.length], [2, 1]);
  // 패널을 닫으면 강조가 풀리고, 아이콘으로 그대로 다시 연다 / closing drops the mark; the icon reopens it as it was
  await page.click('[data-wa="close"]');
  assert.equal(await page.locator('#dash > .wg.hd-wa-on').count(), 0);
  await page.click('#dash > .wg[data-wg="cw_55555555"] [data-hd-wa]');
  assert.deepEqual([await page.locator('body.wa-open').count(), (await state(page)).key, (await state(page)).msgs.length, db.chatGets.length], [1, 'cw_55555555', 2, 1]);
  assert.equal(await page.locator('#dash > .wg[data-wg="cw_55555555"].hd-wa-on').count(), 1);
  // 다른 위젯의 아이콘 = 그 위젯과 그 대화(저장된 대화가 없으면 빈 대화) / another widget's icon opens it with its own conversation (empty without one)
  await page.click('#dash > .wg[data-wg="cw_66666666"] [data-hd-wa]');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === 'cw_66666666' && !window.AI365_widgetAgent.state().busy);
  assert.deepEqual([(await state(page)).msgs, db.chatGets, db.mineGets], [[], ['cw_55555555', 'cw_66666666'], 3]);
  assert.deepEqual(await page.locator('#dash > .wg.hd-wa-on').evaluateAll(e => e.map(x => x.dataset.wg)), ['cw_66666666']);
  assert.equal(await page.locator('.wa-nmtx').innerText(), '오늘 환율');
  assert.equal(await page.locator('.wa-hello').count(), 1);
  // 턴이 도는 동안 다른 위젯의 아이콘 = 알리기만 / while a turn runs another widget's icon only says so
  await page.fill('#waIn', '카드 숫자를 1,200건으로');
  await page.press('#waIn', 'Enter');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().busy);
  await page.click('#dash > .wg[data-wg="cw_55555555"] [data-hd-wa]');
  await page.waitForFunction(() => document.getElementById('toast').textContent === '지금 하는 일이 끝난 뒤에 열 수 있습니다');
  assert.deepEqual([(await state(page)).key, db.chatGets.length], ['cw_66666666', 2]);
  db.hold = false; db.held.splice(0).forEach(f => f());
  await idle(page);
  assert.deepEqual(db.puts.map(p => [p.key, p.body.spec]), [['cw_66666666', DRAFT2]]);
  assert.equal(await cell(page, 'cw_66666666').locator('.hw-kt .v').innerText(), '1,200건');
});

test('만든 위젯을 고치는 동안 그 자리에 그리기: 찾는 동안의 초안 · 지난 모습 미리보기는 홈의 그 칸에, 끝나거나 패널을 닫으면 저장된 모습으로 / drawing in place: a running turn\'s draft and an earlier state show in the widget\'s own home cell, and the stored drawing returns afterwards or on closing', async t => {
  const RENAMED = { widget: Object.assign({}, SAVED.spec, { title: '지점 매출 추이' }), model: Object.assign({}, CHART_MODEL, { title: '지점 매출 추이' }),
    reply: "제목을 '지점 매출 추이'로 바꿨습니다.", ask: null, trace: [{ agent: 'Visualize Agent', group: '정리', tool: 'rename_widget', label: '위젯 제목 변경', ok: true, detail: '', say: '', round: 1 }] };
  const DRAFT_CHART = { v: 2, title: '지점 매출 추이', kpis: [], chart: null, theme: null, insight: '', insight_wait: false, blocks: [], refs: [], origins: [], refresh: false,
    needs_data: false, empty: false, skeleton: { view: 'chart', labels: [], sources: ['사내 데이터'] } };
  const { page, db } = await fixture(t, { mine: [SAVED], chats: { cw_55555555: OLD }, layout: ROWS.concat(['cw_55555555 0 4 1 2']) });
  const sse2 = await liveStream(page);
  await page.click('#dash > .wg[data-wg="cw_55555555"] [data-hd-wa]');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().msgs.length === 2 && !window.AI365_widgetAgent.state().busy);
  const home = cell(page, 'cw_55555555');
  await page.waitForFunction(() => { const c = document.querySelector('#dash > .wg[data-wg="cw_55555555"] canvas[data-hw-canvas]'); return !!(c && c._hw && c.width > 0); });
  await page.fill('#waIn', '제목을 지점 매출 추이로 바꿔줘');
  await page.press('#waIn', 'Enter');
  await page.waitForFunction(() => window.__sse.ctrl);
  await sse2.write(sse('draft', { model: DRAFT_CHART }));
  // 초안 = 그 칸에(이름도), 점선 카드는 없다 / the draft goes into that cell (name too); no dashed card
  await page.waitForSelector('#dash > .wg[data-wg="cw_55555555"] .hw-wait');
  assert.deepEqual([await home.locator('.hd-nm').innerText(), await home.locator('.hw-sk-cv').count(), await home.locator('canvas').count()], ['지점 매출 추이', 1, 0]);
  assert.deepEqual(await page.evaluate(() => window.AI365_homeDash.previewOf('cw_55555555')), DRAFT_CHART);
  assert.equal(await page.locator('#dash .hd-ghost').count(), 0);
  assert.equal(await home.evaluate(el => el.classList.contains('hd-wa-on')), true);
  assert.equal(await page.locator('.wa-nmtx').innerText(), '지점별 매출');            // 작업본은 아직 그대로 / the working copy is unchanged
  assert.equal(db.puts.length, 0);
  await sse2.end(sse('done', RENAMED));
  await idle(page);
  // 끝나면 저장되고 그 칸은 저장된 모습(새 이름 · 차트) / once done it is saved and the cell shows the stored drawing (new name, chart)
  assert.deepEqual(db.puts.map(p => p.body.spec.title), ['지점 매출 추이']);
  assert.equal(await page.evaluate(() => window.AI365_homeDash.previewOf('cw_55555555')), null);
  assert.deepEqual([await home.locator('.hd-nm').innerText(), await home.locator('.hw-wait').count()], ['지점 매출 추이', 0]);
  await page.waitForFunction(() => { const c = document.querySelector('#dash > .wg[data-wg="cw_55555555"] canvas[data-hw-canvas]'); return !!(c && c._hw && c.width > 0); });
  // 지난 모습 미리보기 = 그 칸, 패널을 닫으면 미리보기도 닫히고 강조도 풀린다 / an earlier state previews in the cell; closing the panel ends the preview and the mark
  await tab(page, 'hist');
  await page.click('#waHist [data-wa-hist="h1"]');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().peek === 'h1' && !window.AI365_widgetAgent.state().busy);
  assert.deepEqual([await home.locator('.hd-nm').innerText(), await home.locator('.hw-kt .v').innerText()], ['새 위젯', '1,200건']);
  await page.click('#waBtn');
  assert.deepEqual([(await state(page)).shown, (await state(page)).peek], [false, '']);
  assert.equal(await page.evaluate(() => window.AI365_homeDash.previewOf('cw_55555555')), null);
  assert.deepEqual([await home.locator('.hd-nm').innerText(), await home.locator('.hw-kt').count()], ['지점 매출 추이', 0]);
  assert.equal(await home.evaluate(el => el.classList.contains('hd-wa-on')), false);
  assert.equal(db.puts.length, 1);                                                    // 미리보기는 저장하지 않는다 / previews save nothing
});

test('저장 중에는 기다리고(보낸 요청은 Queue), 점선 카드는 끝난 모습을 그리며 진짜 위젯이 홈에 놓일 때까지 남는다 / while saving the panel waits (requests queue); the dashed card shows the finished state and stays until the real widget is placed', async t => {
  const { page, db } = await fixture(t, { turns: [TURN1, TURN2], holdSave: true, holdDash: true, width: WIDE });
  await openAgent(page);
  await page.fill('#waIn', 'KPI 카드 위젯을 만들어줘');
  await page.press('#waIn', 'Enter');
  while (!db.heldSaves.length) await page.waitForTimeout(20);
  // 턴은 끝났고 저장이 남았다: 기다림 · 점선 카드 = 끝난 모습 · 상태 알약 숨김 / the turn is over, the save is pending
  const s = await state(page);
  assert.deepEqual([s.busy, s.key, s.widget], [true, '', DRAFT1]);
  assert.deepEqual(await page.evaluate(() => window.AI365_homeDash.ghostOf()), MODEL1);
  assert.equal(await page.locator('#dash .hd-ghost .hw-kt.pend .l').innerText(), 'KPI 1');
  assert.equal(await page.locator('#waSt').isHidden(), true);
  assert.deepEqual(await page.locator('.wa-hd button').evaluateAll(b => b.map(x => x.disabled)), [true, true, true, true, false]);
  await page.fill('#waIn', '목표 1,200건으로 해줘');
  await page.press('#waIn', 'Enter');
  assert.deepEqual([(await state(page)).queue.length, db.turnBodies.length], [1, 1]);   // 저장이 끝난 뒤에 간다 / it goes once the save is done
  db.holdSave = false;
  db.heldSaves.splice(0).forEach(f => f());
  // 만들어졌고 홈에 놓기(배치 저장)를 기다리는 동안에도 점선 카드가 남는다 / made, and while placing (the layout save) waits the dashed card stays
  while (!db.heldDash.length) await page.waitForTimeout(20);
  assert.deepEqual([(await state(page)).key, (await state(page)).busy, db.turnBodies.length], ['cw_99990001', true, 1]);
  assert.equal(await page.locator('#dash .hd-ghost .hw-kt.pend .l').innerText(), 'KPI 1');
  assert.equal(await cell(page, 'cw_99990001').count(), 0);
  db.holdDash = false;
  db.heldDash.splice(0).forEach(f => f());
  await page.waitForFunction(() => window.AI365_widgetAgent.state().msgs.length === 4 && !window.AI365_widgetAgent.state().busy, null, { timeout: 5000 });
  assert.deepEqual([db.posts.length, db.puts.map(p => p.body.spec)], [1, [DRAFT2]]);
  assert.equal(db.turnBodies[1].widget.kpis[0].pending, true);                         // 저장된 정의 위에서 이어 간다 / it builds on the saved definition
  assert.equal(await cell(page, 'cw_99990001').locator('.hw-kt .v').innerText(), '1,200건');
  assert.equal(await page.locator('#dash .hd-ghost').count(), 0);
});

test('저장에 실패하면 알리고 상태 알약이 [반영 안 됨 · 다시 저장], 새 위젯 · 다른 위젯 전에 묻고, 알약을 누르면 다시 저장 / a failed save: a toast and a [Not applied · save again] pill, a question before a new or another widget, and the pill retries', async t => {
  const { page, db } = await fixture(t, { turns: [TURN1], mine: [SAVED], failSave: true, width: WIDE });
  await openAgent(page);
  await send(page, 'KPI 카드 위젯을 만들어줘');
  assert.equal(db.posts.length, 1);
  assert.equal(await page.locator('#toast').innerText(), '위젯을 저장하지 못했습니다');
  let s = await state(page);
  assert.deepEqual([s.key, s.dirty, s.busy], ['', true, false]);
  assert.deepEqual(await page.locator('#waSt').evaluate(b => [b.hidden, b.disabled, b.classList.contains('dirty'), b.textContent]), [false, false, true, '반영 안 됨 · 다시 저장']);
  // 홈에는 아직 없다: 빈 첫 자리의 점선 카드로만, 대화도 저장하지 않는다 / not on Home yet: only a dashed card at the first free spot; no conversation saved
  assert.deepEqual([await page.locator('#dash .hd-ghost .hw-kt.pend .l').innerText(), await page.locator('#dash .hd-ghost .hd-new').innerText()], ['KPI 1', '새 위젯']);
  assert.deepEqual(await spot(page.locator('#dash > .wg.hd-ghost')), ['1 / span 1', '5 / span 1']);
  assert.deepEqual([db.dashPuts.length, db.chatPuts.length], [0, 0]);
  // 반영하지 못한 내용이 있으면 새 위젯 · 다른 위젯 전에 묻는다 / with unapplied content, a new or another widget asks first
  await page.click('[data-wa="new"]');
  assert.deepEqual([await page.locator('#waOv .wa-dlg-tt').innerText(), await page.locator('#waOv .wa-dlg-bd').innerText(), await page.locator('#waOv [data-wa-dlg="ok"]').innerText()],
    ['홈에 반영하지 못한 변경이 있습니다.', '반영하지 않고 새 위젯을 시작할까요?', '새로 시작']);
  await page.click('#waOv [data-wa-dlg="no"]');
  assert.equal((await state(page)).widget.kpis.length, 1);
  await page.click('[data-wa="mine"]');
  await page.click('[data-wa-open="cw_55555555"]');
  assert.deepEqual([await page.locator('#waOv .wa-dlg-bd').innerText(), await page.locator('#waOv [data-wa-dlg="ok"]').innerText()], ['반영하지 않고 다른 위젯을 열까요?', '열기']);
  await page.click('#waOv [data-wa-dlg="no"]');
  assert.deepEqual([(await state(page)).key, db.chatGets.length], ['', 0]);
  // 알약 = 다시 저장 → 만들어 그 자리에 / the pill saves again → made and placed on that spot
  db.failSave = false;
  await page.click('#waSt');
  await idle(page);
  s = await state(page);
  assert.deepEqual([s.key, s.dirty, db.posts.length], ['cw_99990001', false, 2]);
  assert.equal(await page.locator('#toast').innerText(), '새 위젯을 홈에 놓았습니다');
  assert.deepEqual(await page.locator('#waSt').evaluate(b => [b.disabled, b.classList.contains('dirty'), b.textContent]), [true, false, '홈에 반영됨 11-16 10:00']);
  assert.equal(await page.locator('#dash .hd-ghost').count(), 0);
  assert.deepEqual(await spot(cell(page, 'cw_99990001')), ['1 / span 1', '5 / span 1']);
  await until(() => db.chatPuts.length === 1);
  // 있는 위젯의 저장 실패: 고친 모습은 홈의 그 칸에 그려 두고, 다시 저장하면 저장된 모습 / a failed update keeps the working copy drawn in the home cell until saved
  db.failSave = true;
  await page.click('[data-wa="rename"]');
  await page.fill('#waNmIn', '목표 카드');
  await page.press('#waNmIn', 'Enter');
  await idle(page);
  const home = cell(page, 'cw_99990001');
  assert.equal(await page.locator('#waSt').textContent(), '반영 안 됨 · 다시 저장');
  assert.equal(await home.locator('.hd-nm').innerText(), '목표 카드');
  assert.equal(await page.evaluate(() => window.AI365_homeDash.previewOf('cw_99990001').title), '목표 카드');
  assert.equal(db.chatPuts.length, 1);                                                 // 반영하지 못하면 대화도 저장하지 않는다 / nothing applied, no conversation saved
  db.failSave = false;
  await page.click('#waSt');
  await idle(page);
  assert.deepEqual(db.puts.map(p => p.body.spec.title), ['목표 카드', '목표 카드']);
  assert.equal(await page.locator('#waSt').textContent(), '홈에 반영됨 11-16 11:16');
  assert.equal(await page.evaluate(() => window.AI365_homeDash.previewOf('cw_99990001')), null);
  assert.equal(await home.locator('.hd-nm').innerText(), '목표 카드');
  await until(() => db.chatPuts.length === 2);
});

test('홈에 놓지 못한 새 위젯 · 홈에서 빠진 위젯: 알림 줄 [홈에 놓기] → 빈 첫 자리에 / a new widget that could not be placed, or one off Home: a [Put on Home] notice that places it at the first free spot', async t => {
  const { page, db } = await fixture(t, { turns: [TURN1], failDash: true, width: WIDE });
  await openAgent(page);
  await send(page, 'KPI 카드 위젯을 만들어줘');
  assert.deepEqual([db.posts.length, db.dashPuts.length], [1, 1]);                    // 만들었고 놓으려 했지만 실패 / made, placing failed
  assert.equal(await page.locator('#toast').innerText(), '위젯을 만들었습니다. 지금은 홈에 놓지 못해 배치 편집의 위젯 추가에 넣었습니다');
  assert.equal((await state(page)).key, 'cw_99990001');
  assert.deepEqual([await cell(page, 'cw_99990001').count(), await page.locator('#dash .hd-ghost').count()], [0, 0]);
  assert.equal(await page.evaluate(() => window.AI365_homeDash.state().unused.indexOf('cw_99990001') >= 0), true);   // 배치 편집의 위젯 추가에 / in the Add widget drawer
  assert.equal(await page.locator('#waSt').textContent(), '홈에 반영됨 11-16 10:00');   // 저장은 됐다 / it is saved
  assert.deepEqual([await page.locator('#waNote').isVisible(), await page.locator('#waNote > span').innerText(), await page.locator('#waNote [data-wa-act="put-home"]').innerText()],
    [true, '이 위젯은 홈에 놓여 있지 않습니다', '홈에 놓기']);
  await page.click('[data-wa="mine"]');
  await page.waitForSelector('[data-wa-open="cw_99990001"]');
  assert.equal(await page.locator('.wa-mn-it .off').innerText(), '홈에 없음');
  await page.click('[data-wa="mine"]');
  await tab(page, 'info');
  assert.equal(await page.locator('.wa-size-h').innerText(), '홈에 처음 놓일 크기입니다');
  assert.equal(await page.locator('#waInfo .wa-pnl-r >> nth=4').locator('span:last-child').innerText(), '가로 1 × 세로 1');
  // 놓지 못하면 다시 알린다 / a failed attempt says so
  await page.click('#waNote [data-wa-act="put-home"]');
  await idle(page);
  assert.equal(await page.locator('#toast').innerText(), '지금은 홈에 놓을 수 없습니다');
  assert.equal(await page.locator('#waNote').isVisible(), true);
  db.failDash = false;
  await page.click('#waNote [data-wa-act="put-home"]');
  await idle(page);
  assert.equal(await page.locator('#toast').innerText(), '홈에 놓았습니다');
  assert.equal(await page.locator('#waNote').isHidden(), true);
  const home = cell(page, 'cw_99990001');
  assert.deepEqual([...await spot(home), await home.evaluate(el => el.classList.contains('hd-wa-on'))], ['1 / span 1', '5 / span 1', true]);
  assert.equal(await page.locator('.wa-size-h').innerText(), '고르면 홈에서 바로 바뀝니다');
  // 다른 곳에서 홈에서 빼면(다시 읽을 때) 알림이 돌아온다 / taken off Home elsewhere, the notice returns on the next read
  db.layout.items = db.layout.items.filter(i => i.widget_key !== 'cw_99990001');
  await page.evaluate(() => window.AI365_homeDash.reload());
  await page.waitForSelector('#waNote:not([hidden])');
  assert.equal(await page.locator('.wa-size-h').innerText(), '홈에 처음 놓일 크기입니다');
});

test('정보 탭 [위젯 지우기]: 확인 창 → 홈 · 내 위젯 · 대화에서 지우고 패널은 새 위젯으로, 이미 없는 위젯도 지운 것으로 / [Delete widget] on the info tab: a confirmation, then it leaves Home, My widgets and its conversation and the panel starts anew; an already-gone one counts as deleted', async t => {
  const { page, db } = await fixture(t, { mine: [SAVED, FXW], chats: { cw_55555555: OLD }, layout: ROWS.concat(['cw_55555555 0 4 1 2', 'cw_66666666 1 4 1 1']) });
  await page.click('#dash > .wg[data-wg="cw_55555555"] [data-hd-wa]');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().msgs.length === 2 && !window.AI365_widgetAgent.state().busy);
  await tab(page, 'info');
  assert.equal(await page.locator('[data-wa-act="delete"]').innerText(), '위젯 지우기');
  await page.click('[data-wa-act="delete"]');
  assert.deepEqual([await page.locator('#waOv .wa-dlg-tt').innerText(), await page.locator('#waOv .wa-dlg-bd').innerText(),
    await page.locator('#waOv [data-wa-dlg="no"]').innerText(), await page.locator('#waOv [data-wa-dlg="ok"]').innerText()],
    ['이 위젯을 지울까요?', '홈과 내 위젯에서 사라지고 대화 기록도 함께 지워집니다. 되돌릴 수 없습니다.', '취소', '지우기']);
  assert.equal(await page.evaluate(() => document.activeElement.dataset.waDlg), 'no');   // 지우기는 [취소]에 초점(Enter 로 지워지지 않게) / focus on [Cancel], so Enter never deletes
  await page.click('#waOv [data-wa-dlg="no"]');                                         // 취소 = 그대로 / cancel keeps it
  assert.deepEqual([db.deletes.length, (await state(page)).key], [0, 'cw_55555555']);
  await page.click('[data-wa-act="delete"]');
  await page.click('#waOv [data-wa-dlg="ok"]');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === '' && !window.AI365_widgetAgent.state().busy);
  assert.deepEqual(db.deletes, [{ key: 'cw_55555555', who: '' }]);
  assert.equal(await page.locator('#toast').innerText(), '위젯을 지웠습니다');
  const s = await state(page);
  assert.deepEqual([s.widget, s.msgs, s.undo, s.tab, s.shown], [PURE.waBlank(), [], 0, 'chat', true]);
  await page.waitForFunction(() => !document.querySelector('#dash > .wg[data-wg="cw_55555555"]'));
  assert.deepEqual([await page.locator('#dash .hd-wa-on').count(), await page.locator('.wa-hello').count(), db.chats.cw_55555555], [0, 1, undefined]);
  await page.click('[data-wa="mine"]');
  await page.waitForSelector('[data-wa-open="cw_66666666"]');
  assert.deepEqual(await page.locator('.wa-mn-it .t').allInnerTexts(), ['오늘 환율']);
  await page.click('[data-wa="mine"]');
  // 이미 없는 위젯(404)도 지운 것으로 / an already-gone widget (404) counts as deleted
  await page.click('#dash > .wg[data-wg="cw_66666666"] [data-hd-wa]');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === 'cw_66666666' && !window.AI365_widgetAgent.state().busy);
  db.mine = [];
  await tab(page, 'info');
  await page.click('[data-wa-act="delete"]');
  await page.click('#waOv [data-wa-dlg="ok"]');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === '' && !window.AI365_widgetAgent.state().busy);
  assert.deepEqual(db.deletes.map(d => d.key), ['cw_55555555', 'cw_66666666']);
  assert.equal(await page.locator('#toast').innerText(), '위젯을 지웠습니다');
  await page.waitForFunction(() => !document.querySelector('#dash > .wg[data-wg="cw_66666666"]'));
});

test('전자결재 · 보안 · 배치 편집(톱니)을 고르면 패널이 닫히고, 패널을 닫은 채 끝난 턴도 홈에 반영된다(그동안 아이콘에 점) / e-Approval, security or the gear close the panel, and a turn that ends with the panel closed still lands on Home (a dot on the icon meanwhile)', async t => {
  const { page, db } = await fixture(t, { turns: [TURN1], holdTurn: true });
  await openAgent(page);
  await page.click('#agentSeg [data-seg="eapp"]');
  assert.deepEqual([await page.locator('body.wa-open').count(), (await state(page)).shown, await page.locator('#waView').isHidden(), await page.locator('#waBtn').isHidden()],
    [0, false, true, true]);                                                           // 전자결재 화면에는 아이콘도 없다 / no icon on the e-Approval screen
  await page.click('#agentSeg [data-seg="gw"]');
  assert.deepEqual([await page.locator('#waBtn').isVisible(), (await state(page)).shown], [true, false]);   // 돌아와도 닫힌 채 / still closed on return
  await openAgent(page);
  await page.click('#agentSeg [data-seg="sec"]');
  assert.deepEqual([(await state(page)).shown, await page.locator('#waBtn').isHidden()], [false, true]);
  await page.click('#agentSeg [data-seg="gw"]');
  await openAgent(page);
  await page.click('#editBtn');                                                       // 한 번에 하나: 배치 편집이 열리면 패널은 닫힌다 / one at a time
  await page.waitForSelector('body.hd-edit #hdEbar');
  assert.deepEqual([await page.locator('body.wa-open').count(), (await state(page)).shown, await page.locator('#waBtn').isVisible(), await page.evaluate(() => window.AI365_homeDash.editing())],
    [0, false, false, true]);
  await page.click('[data-hd-act="cancel"]');
  assert.deepEqual([await page.evaluate(() => window.AI365_homeDash.editing()), await page.locator('#waBtn').isVisible()], [false, true]);
  // 닫은 채 일하기 / working with the panel closed
  await openAgent(page);
  await page.fill('#waIn', 'KPI 카드 위젯을 만들어줘');
  await page.press('#waIn', 'Enter');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().busy);
  assert.equal(await page.locator('#waBtn.busy').count(), 0);                         // 열려 있으면 점이 없다 / no dot while open
  await page.click('#waBtn');
  assert.deepEqual([await page.locator('#waBtn.busy').count(), await page.getAttribute('#waBtn', 'aria-pressed'), await page.locator('body.wa-open').count()], [1, 'false', 0]);
  db.hold = false; db.held.splice(0).forEach(f => f());
  await idle(page);
  assert.equal(await page.locator('#waBtn.busy').count(), 0);
  assert.equal(await cell(page, 'cw_99990001').locator('.hw-kt.pend .l').innerText(), 'KPI 1');
  assert.equal(await page.locator('#toast').innerText(), '새 위젯을 홈에 놓았습니다');
  assert.deepEqual([await page.locator('#dash .hd-wa-on').count(), (await state(page)).shown], [0, false]);   // 닫혀 있으면 강조하지 않는다 / no mark while closed
  await page.click('#waBtn');                                                         // 다시 열면 끝난 대화 그대로 / reopening shows the finished conversation
  assert.equal(await page.locator('.wa-a .wa-tx').innerText(), "'KPI 1' KPI 카드를 만들었습니다.");
  assert.equal(await page.locator('#dash > .wg[data-wg="cw_99990001"].hd-wa-on').count(), 1);
});

test('내용이 없는 모습은 홈에 반영하지 않는다: 위젯 · 대화 저장 없이 [반영 안 됨]으로 알리고, 눌러도 알리기만, 되돌리면 저장 없이 원래대로 / an empty state is never applied to Home: no widget or conversation save, a [Not applied] pill that only explains, and undo returns without a save', async t => {
  const EMPTY = { widget: Object.assign(PURE.waBlank(), { title: '지점별 매출' }), model: Object.assign(PURE.waBlankModel(), { title: '지점별 매출' }), reply: '차트를 지웠습니다.', ask: null,
    trace: [{ agent: 'Visualize Agent', group: '리포트', tool: 'update_chart', label: '차트 수정', ok: true, detail: '', say: '', round: 1 }] };
  const { page, db } = await fixture(t, { turns: [EMPTY], mine: [SAVED], layout: ROWS.concat(['cw_55555555 0 4 1 2']) });
  await page.click('#dash > .wg[data-wg="cw_55555555"] [data-hd-wa]');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === 'cw_55555555' && !window.AI365_widgetAgent.state().busy);
  await send(page, '차트를 지워줘');
  await page.waitForTimeout(300);
  assert.deepEqual([db.puts.length, db.posts.length, db.dashPuts.length, db.chatPuts.length], [0, 0, 0, 0]);
  assert.deepEqual([(await state(page)).dirty, (await state(page)).undo], [true, 1]);
  assert.deepEqual(await page.locator('#waSt').evaluate(b => [b.hidden, b.disabled, b.classList.contains('dirty'), b.textContent]), [false, false, true, '반영 안 됨 · 다시 저장']);
  // 홈의 그 칸에는 반영 전 작업본(빈 위젯)을 그려 둔다 / the home cell shows the unapplied working copy (empty)
  assert.equal(await cell(page, 'cw_55555555').locator('.hd-none').innerText(), '표시할 데이터가 없습니다');
  await page.click('#waSt');
  assert.equal(await page.locator('#toast').innerText(), '내용이 없는 모습은 홈에 반영하지 않습니다');
  assert.equal(db.puts.length, 0);
  // 되돌리면 저장된 모습 그대로(저장할 것이 없다) / undo returns to the stored state with nothing to save
  await page.click('[data-wa="undo"]');
  await idle(page);
  assert.deepEqual((await state(page)).widget, SAVED.spec);
  assert.deepEqual([db.puts.length, (await state(page)).dirty, await page.locator('#waSt').textContent()], [0, false, '홈에 반영됨 11-16 09:30']);
  assert.equal(await page.evaluate(() => window.AI365_homeDash.previewOf('cw_55555555')), null);
  await page.waitForFunction(() => { const c = document.querySelector('#dash > .wg[data-wg="cw_55555555"] canvas[data-hw-canvas]'); return !!(c && c._hw && c.width > 0); });
});

/* ── 2026-11-20 독립 검토 반영 / fixes from the independent review ── */
test('배치 편집 서랍에서 패널의 위젯을 지우면: 쉬고 있으면 새 위젯으로, 턴이 도는 중이면 끝난 뒤에 — 바뀌지 않았으면 새 위젯으로, 바뀌었으면 다시 만들지 않고 작업본만([다시 저장]을 기다린다) / deleting the panel\'s widget in the layout-editing drawer: idle → a new widget; during a turn it is handled when the turn ends (unchanged → a new widget; changed → never re-created, the working copy waits for [save again])', async t => {
  const KPIW = { key: 'cw_77777777', kind: 'custom', name: '목표 카드', created_at: '2026-11-16T09:00:00', updated_at: '2026-11-16T09:40:00',
    spec: Object.assign({}, DRAFT2, { title: '목표 카드' }), model: Object.assign({}, MODEL2, { title: '목표 카드' }) };
  const { page, db } = await fixture(t, { turns: [FX_TURN, TURN1], holdTurn: true, mine: [SAVED, FXW, KPIW], chats: { cw_55555555: OLD }, width: WIDE,
    layout: ROWS.concat(['cw_55555555 0 4 1 2', 'cw_66666666 1 4 1 1', 'cw_77777777 2 4 1 1']) });
  // 서랍에서 지우기: 톱니(패널이 닫힌다) → ✕ → [위젯 추가] → 휴지통 → 삭제 → 편집 닫기 / delete in the drawer: gear (the panel closes) → ✕ → Add widget → trash → Delete → close editing
  const drawerDelete = async key => {
    await page.click('#editBtn');
    await page.waitForSelector('body.hd-edit #hdEbar');
    assert.equal((await state(page)).shown, false);
    await page.click('#dash [data-hd-rm="' + key + '"]');
    await page.click('[data-hd-act="add"]');
    await page.click('#hdDrawer [data-hd-del="' + key + '"]');
    await page.click('#hdOv [data-hd-dlg="ok"]');
    await page.waitForFunction(k => !document.querySelector('#hdDrawer [data-hd-add="' + k + '"]'), key);
    await page.click('[data-hd-act="cancel"]');
    await page.waitForFunction(() => !document.body.classList.contains('hd-edit'));
  };
  const openByIcon = async (key, msgs) => {
    await page.click('#dash > .wg[data-wg="' + key + '"] [data-hd-wa]');
    await page.waitForFunction(([k, n]) => window.AI365_widgetAgent.state().key === k && window.AI365_widgetAgent.state().msgs.length === n && !window.AI365_widgetAgent.state().busy, [key, msgs]);
  };
  // 쉬고 있을 때: 바로 새 위젯으로 / while idle: a new widget at once
  await openByIcon('cw_55555555', 2);
  await drawerDelete('cw_55555555');
  let s = await state(page);
  assert.deepEqual([s.key, s.msgs, s.widget], ['', [], PURE.waBlank()]);
  await page.click('#waBtn');
  assert.deepEqual([await page.locator('.wa-hello').count(), await page.locator('#waNote').isHidden(), await page.locator('#waSt').isHidden()], [1, true, true]);
  // 턴이 도는 중 · 바뀌지 않은 답: 끝난 뒤 새 위젯으로 / during a turn whose answer changes nothing: a new widget once it ends
  await openByIcon('cw_66666666', 0);
  await page.fill('#waIn', '그대로 둬');
  await page.press('#waIn', 'Enter');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().busy);
  await drawerDelete('cw_66666666');
  assert.deepEqual([(await state(page)).key, (await state(page)).busy], ['cw_66666666', true]);   // 턴이 끝날 때까지 기다린다 / it waits for the turn
  db.hold = false; db.held.splice(0).forEach(f => f());
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === '' && !window.AI365_widgetAgent.state().busy);
  s = await state(page);
  assert.deepEqual([s.msgs, s.widget], [[], PURE.waBlank()]);
  // 턴이 도는 중 · 바뀐 답: 다시 만들지 않고 작업본만 남겨 알린다, [다시 저장]을 눌러야 새 위젯 / during a turn whose answer changes it: not re-created; the working copy stays with a notice until [save again]
  db.hold = true;
  await page.click('#waBtn');
  await openByIcon('cw_77777777', 0);
  await page.fill('#waIn', '데이터를 연결할 카드로 바꿔줘');
  await page.press('#waIn', 'Enter');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().busy);
  await drawerDelete('cw_77777777');
  db.hold = false; db.held.splice(0).forEach(f => f());
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === '' && !window.AI365_widgetAgent.state().busy);
  await page.waitForTimeout(300);
  s = await state(page);
  assert.deepEqual([s.widget, s.dirty, s.msgs.length], [DRAFT1, true, 2]);
  assert.equal(await page.locator('#toast').innerText(), '이 위젯은 지워졌습니다. 고친 내용은 홈에 반영하지 않았습니다 — [다시 저장]을 누르면 새 위젯으로 만듭니다');
  assert.deepEqual([db.deletes.map(d => d.key), db.posts.length, db.puts.length], [['cw_55555555', 'cw_66666666', 'cw_77777777'], 0, 0]);   // 다시 만들지 않았다 / nothing re-created
  assert.equal(await page.locator('#dash .hd-ghost').count(), 0);
  await page.click('#waBtn');
  assert.equal(await page.locator('#waSt').textContent(), '반영 안 됨 · 다시 저장');
  await page.click('#waSt');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === 'cw_99990001' && !window.AI365_widgetAgent.state().busy);
  assert.deepEqual([db.posts.map(p => p.spec), db.puts.length], [[DRAFT1], 0]);
  assert.equal(await cell(page, 'cw_99990001').locator('.hw-kt.pend .l').innerText(), 'KPI 1');
});

test('다시 시도: 그 턴이 돈 모습 위에서 다시 묻고(답이 오기 전에는 작업본 · 기록 · 홈 그대로), 멈추거나 실패하면 아무것도 바꾸지 않고 저장도 없이 같은 모습에서 또 시도할 수 있으며, 되면 그 턴을 바꿔 넣고(기록 수 그대로) 바로 저장 / retry asks again on the state that turn ran on (working copy, history and Home unchanged until the answer); a stopped or failed retry changes nothing, saves nothing and can be retried on the same state; success replaces that turn (history count unchanged) and is saved at once', async t => {
  const NEW = { widget: Object.assign({}, FX_WIDGET, { title: '환율 카드' }), model: Object.assign({}, FX_MODEL, { title: '환율 카드' }), reply: '제목을 환율 카드로 했습니다.', ask: null, trace: [] };
  const { page, db } = await fixture(t, { width: WIDE });
  const sse2 = await liveStream(page);
  const asked = n => page.waitForFunction(k => window.__sse.bodies.length === k, n);
  const last = async () => (await state(page)).msgs.slice(-1)[0];
  await openAgent(page);
  // 턴 둘: 만들기(환율) → 고치기(1,200건) / two turns: create (the rate), then update (1,200)
  await page.fill('#waIn', '오늘 환율 위젯');
  await page.press('#waIn', 'Enter');
  await asked(1);
  await sse2.end(sse('done', FX_TURN));
  await idle(page);
  await page.fill('#waIn', '카드 숫자를 1,200건으로');
  await page.press('#waIn', 'Enter');
  await asked(2);
  await sse2.end(sse('done', TURN2));
  await idle(page);
  const home = cell(page, 'cw_99990001'), h1 = (await state(page)).msgs[3].beforeId;
  assert.ok(h1);
  assert.deepEqual([(await state(page)).undo, db.puts.map(p => p.body.spec), await home.locator('.hw-kt .v').innerText()], [1, [DRAFT2], '1,200건']);
  // 다시 시도 = 그 턴이 돈 모습(환율)으로 묻는다, 답이 오기 전에는 아무것도 바뀌지 않는다 / retry asks on the state the turn ran on; nothing changes before the answer
  await page.click('.wa-a >> nth=-1 >> [data-wa-act="retry"]');
  await asked(3);
  const b3 = await page.evaluate(() => window.__sse.bodies[2]);
  assert.deepEqual([b3.widget, b3.message, b3.messages.map(m => m.role)], [FX_WIDGET, '카드 숫자를 1,200건으로', ['user', 'agent']]);   // 앞 턴만 기록으로 / only the earlier turn as history
  let s = await state(page);
  assert.deepEqual([s.widget, s.undo, s.busy], [DRAFT2, 1, true]);
  assert.equal(await home.locator('.hw-kt .v').innerText(), '1,200건');
  // 멈추면: 아무것도 바뀌지 않고 저장도 없다, 멈춘 줄은 그 모습(base)을 기억한다 / stopped: nothing changes or is saved; the stopped line remembers the state (base)
  await page.click('[data-wa="send"]');
  await idle(page);
  s = await state(page);
  assert.deepEqual([s.widget, s.undo, db.puts.length, (await last()).stopped, (await last()).base], [DRAFT2, 1, 1, true, h1]);
  assert.equal(await home.locator('.hw-kt .v').innerText(), '1,200건');
  // 멈춘 줄을 다시 시도 → 같은 모습에서, 이번에는 실패 → 그대로 / retrying the stopped line asks on the same state; this time it fails and nothing changes
  await page.click('.wa-a >> nth=-1 >> [data-wa-act="retry"]');
  await asked(4);
  assert.deepEqual((await page.evaluate(() => window.__sse.bodies[3])).widget, FX_WIDGET);
  await sse2.end(sse('error', { status: 503, detail: '위젯 에이전트가 지금 응답하지 않습니다. 잠시 뒤 다시 시도해 주세요' }));
  await idle(page);
  s = await state(page);
  assert.deepEqual([s.widget, s.undo, db.puts.length, (await last()).error, (await last()).base], [DRAFT2, 1, 1, true, h1]);
  assert.equal(await home.locator('.hw-kt .v').innerText(), '1,200건');
  // 또 다시 시도 → 이번에는 답: 그 턴을 바꿔 넣고(기록 수 그대로) 바로 저장 / retry again: the answer replaces that turn (history count unchanged) and is saved at once
  await page.click('.wa-a >> nth=-1 >> [data-wa-act="retry"]');
  await asked(5);
  assert.deepEqual((await page.evaluate(() => window.__sse.bodies[4])).widget, FX_WIDGET);
  await sse2.end(sse('done', NEW));
  await idle(page);
  s = await state(page);
  assert.deepEqual([s.widget, s.undo, s.msgs.length, s.msgs[3].beforeId, s.msgs[3].text], [NEW.widget, 1, 4, h1, '제목을 환율 카드로 했습니다.']);
  assert.deepEqual(db.puts.map(p => p.body.spec), [DRAFT2, NEW.widget]);
  assert.equal(await home.locator('.hd-nm').innerText(), '환율 카드');
});

test('만든 턴을 다시 시도: 빈 작업본에서 다시 묻되 위젯 키는 그대로, 실패하면 아무것도 바뀌지 않고, 되면 그 위젯을 고친다(PUT — 새로 만들지 않는다) / retrying the creating turn asks again from a blank draft while the key stays; a failure changes nothing; success updates that widget (PUT, never a second POST)', async t => {
  const { page, db } = await fixture(t, { turns: [TURN1, { status: 503, body: { detail: '위젯 에이전트가 지금 응답하지 않습니다. 잠시 뒤 다시 시도해 주세요' } }, TURN2], width: WIDE });
  await openAgent(page);
  await send(page, 'KPI 카드 위젯을 만들어줘');
  const home = cell(page, 'cw_99990001');
  assert.deepEqual([(await state(page)).msgs[1].blank, (await state(page)).msgs[1].beforeId], [true, '']);   // 빈 위젯에서 돈 턴 / a turn on an empty widget
  await page.click('.wa-a >> nth=-1 >> [data-wa-act="retry"]');
  await idle(page);
  assert.deepEqual([db.turnBodies[1].widget, db.turnBodies[1].messages, db.turnBodies[1].message], [PURE.waBlank(), [], 'KPI 카드 위젯을 만들어줘']);   // 빈 작업본에서 다시 / from a blank draft
  let s = await state(page);
  const err = s.msgs.slice(-1)[0];
  assert.deepEqual([s.key, s.widget, s.undo, err.error, err.blank], ['cw_99990001', DRAFT1, 0, true, true]);   // 실패: 그대로 / failed: unchanged
  assert.deepEqual([db.posts.length, db.puts.length], [1, 0]);
  assert.equal(await home.locator('.hw-kt.pend .l').innerText(), 'KPI 1');
  await page.click('.wa-a >> nth=-1 >> [data-wa-act="retry"]');
  await idle(page);
  assert.deepEqual(db.turnBodies[2].widget, PURE.waBlank());
  s = await state(page);
  assert.deepEqual([s.key, s.widget, s.undo, s.msgs.length], ['cw_99990001', DRAFT2, 0, 2]);   // 그 턴이 없었던 것처럼(빈 처음은 기록에 없다) / as if the turn never happened (no blank entry)
  assert.deepEqual([db.posts.length, db.puts.map(p => [p.key, p.body.spec])], [1, [['cw_99990001', DRAFT2]]]);
  assert.equal(await home.locator('.hw-kt .v').innerText(), '1,200건');
});

test('이름 바꾸기와 턴이 겹치면: 턴이 도는 중에 끝낸 이름은 버리고(턴의 결과가 이긴다), 이름 칸이 열려 있는 동안 Queue 는 기다린다 / renaming and a turn overlap: a rename finished while a turn runs is discarded (the turn wins), and the Queue waits while the name box is open', async t => {
  const SAME = { widget: DRAFT2, model: MODEL2, reply: '그대로예요.', trace: [], ask: null };
  const { page, db } = await fixture(t, { turns: [TURN1, TURN2, SAME, SAME] });
  await openAgent(page);
  await send(page, 'KPI 카드 위젯을 만들어줘');
  // 이름 칸을 연 채 턴이 시작됐다(보내기를 눌러 초점은 이름 칸에 남는다) → 그 사이 끝낸 이름은 버린다 / a turn starts while the name box is open (focus stays there)
  await page.fill('#waIn', '목표 1,200건으로 해줘');
  await page.click('[data-wa="rename"]');
  await page.fill('#waNmIn', '버려질 이름');
  db.hold = true;
  await page.evaluate(() => document.querySelector('[data-wa="send"]').click());
  await page.waitForFunction(() => window.AI365_widgetAgent.state().busy);
  await page.press('#waNmIn', 'Enter');
  assert.deepEqual([await page.locator('#waNmIn').count(), await page.locator('.wa-nmtx').innerText()], [0, '새 위젯']);
  db.hold = false; db.held.splice(0).forEach(f => f());
  await idle(page);
  assert.deepEqual([(await state(page)).widget, db.puts.map(p => p.body.spec.title)], [DRAFT2, ['새 위젯']]);   // 턴의 결과만 저장 / only the turn's result is saved
  // 대기 요청은 이름 칸이 닫힐 때까지 기다린다 / a queued request waits until the name box closes
  db.hold = true;
  await page.fill('#waIn', '그대로 둬');
  await page.press('#waIn', 'Enter');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().busy);
  await page.fill('#waIn', '다음 요청');
  await page.press('#waIn', 'Enter');
  assert.equal((await state(page)).queue.length, 1);
  db.hold = false;
  // 턴이 끝나는 바로 그때 이름 칸을 연다(대기 요청이 가기 전, 0.3초 안) / open the name box the moment the turn ends (within the queue's 0.3 s)
  const opened = page.evaluate(() => new Promise(r => { const t = setInterval(() => {
    if (!window.AI365_widgetAgent.state().busy) { clearInterval(t); document.querySelector('[data-wa="rename"]').click(); r(!!document.getElementById('waNmIn')); } }, 2); }));
  db.held.splice(0).forEach(f => f());
  assert.equal(await opened, true);
  await page.waitForTimeout(700);
  assert.deepEqual([db.turnBodies.length, (await state(page)).queue.length], [3, 1]);   // 아직 가지 않았다 / not sent yet
  await page.press('#waNmIn', 'Escape');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().queue.length === 0 && !window.AI365_widgetAgent.state().busy, null, { timeout: 5000 });
  assert.deepEqual([db.turnBodies.length, db.turnBodies[3].message], [4, '다음 요청']);   // 닫히자 이어서 갔다 / sent once it closed
});

test('패널이 열려 있으면 홈의 만든 위젯 카드를 눌러 대화 상대를 바꾼다(2026-11-21): 닫혀 있으면 아무 일 없고, 지금 고치는 위젯 · 기본 위젯 · 카드 안의 링크는 바꾸지 않으며, 일하는 동안은 알리기만 / with the panel open a click on a made widget card switches the conversation: nothing while closed; the edited widget, built-ins and links inside a card never switch; while busy it only says so', async t => {
  const { page, db } = await fixture(t, { turns: [TURN2], holdTurn: true, mine: [SAVED, FXW], chats: { cw_55555555: OLD },
    layout: ROWS.concat(['cw_55555555 0 4 1 2', 'cw_66666666 1 4 1 1']) });
  // 패널이 닫혀 있으면 카드를 눌러도 열리지 않는다(머리의 아이콘만 연다) / with the panel closed a card click opens nothing (only the head icon does)
  assert.equal(await cell(page, 'cw_55555555').evaluate(el => getComputedStyle(el).cursor), 'auto');
  await cell(page, 'cw_55555555').locator('.hd-nm').click();
  await page.waitForTimeout(150);
  assert.deepEqual([await page.locator('#waView').count(), db.mineGets], [0, 0]);
  await openAgent(page);
  // 첫 화면에 알림 한 줄, 만든 위젯 카드는 손가락 커서 / a hint on the first screen; made widget cards take a pointer cursor
  assert.equal(await page.locator('.wa-hello .h').innerText(), '홈에 있는 내 위젯을 누르면 그 위젯과 대화합니다');
  assert.deepEqual([await cell(page, 'cw_55555555').evaluate(el => getComputedStyle(el).cursor), await cell(page, 'wx').evaluate(el => getComputedStyle(el).cursor)], ['pointer', 'auto']);
  // 카드 본문을 누르면 그 위젯과 저장된 대화가 열린다 / a click on the card body opens that widget with its saved conversation
  await cell(page, 'cw_55555555').locator('.hd-body').click();
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === 'cw_55555555' && window.AI365_widgetAgent.state().msgs.length === 2 && !window.AI365_widgetAgent.state().busy);
  assert.deepEqual([db.chatGets, await page.locator('.wa-nmtx').innerText()], [['cw_55555555'], '지점별 매출']);
  assert.deepEqual(await page.locator('#dash > .wg.hd-wa-on').evaluateAll(e => e.map(x => x.dataset.wg)), ['cw_55555555']);
  assert.equal(await cell(page, 'cw_55555555').evaluate(el => getComputedStyle(el).cursor), 'auto');   // 지금 고치는 위젯은 고를 것이 아니다 / the edited widget is not a pick
  // 다른 카드를 누르면 그 위젯으로 바뀐다(머리의 이름을 눌러도) / another card switches to it (the name in its head works too)
  await cell(page, 'cw_66666666').locator('.hd-nm').click();
  await page.waitForFunction(() => window.AI365_widgetAgent.state().key === 'cw_66666666' && !window.AI365_widgetAgent.state().busy);
  assert.deepEqual([db.chatGets, await page.locator('.wa-nmtx').innerText(), (await state(page)).msgs], [['cw_55555555', 'cw_66666666'], '오늘 환율', []]);
  assert.deepEqual(await page.locator('#dash > .wg.hd-wa-on').evaluateAll(e => e.map(x => x.dataset.wg)), ['cw_66666666']);
  // 바꾸지 않는 것: 지금 고치는 위젯 · 기본 위젯 · 카드 안의 링크(링크는 제 일을 한다) / no switch for the edited widget, a built-in, or a link inside a card
  const gets = db.mineGets;
  await cell(page, 'cw_66666666').locator('.hd-nm').click();
  await cell(page, 'wx').locator('.wg-head').click();
  await page.evaluate(() => {
    const a = document.createElement('a');
    a.href = '#x'; a.id = 'tLink'; a.textContent = '링크';
    a.addEventListener('click', e => e.preventDefault());
    document.querySelector('#dash > .wg[data-wg="cw_55555555"] .hd-body').appendChild(a);
  });
  await page.click('#tLink');
  await page.waitForTimeout(200);
  assert.deepEqual([db.mineGets, (await state(page)).key, db.chatGets.length], [gets, 'cw_66666666', 2]);
  // 턴이 도는 동안 다른 카드 = 알리기만 / while a turn runs another card only says so
  await page.fill('#waIn', '카드 숫자를 1,200건으로');
  await page.press('#waIn', 'Enter');
  await page.waitForFunction(() => window.AI365_widgetAgent.state().busy);
  await cell(page, 'cw_55555555').locator('.hd-nm').click();
  await page.waitForFunction(() => document.getElementById('toast').textContent === '지금 하는 일이 끝난 뒤에 열 수 있습니다');
  assert.deepEqual([(await state(page)).key, db.chatGets.length], ['cw_66666666', 2]);
  db.hold = false; db.held.splice(0).forEach(f => f());
  await idle(page);
  assert.deepEqual(db.puts.map(p => p.key), ['cw_66666666']);
  // 패널을 닫으면 다시 눌러도 바뀌지 않는다 / once the panel closes a card click switches nothing again
  await page.click('[data-wa="close"]');
  await cell(page, 'cw_55555555').locator('.hd-nm').click();
  await page.waitForTimeout(150);
  assert.deepEqual([await page.locator('body.wa-open').count(), (await state(page)).key], [0, 'cw_66666666']);
});
