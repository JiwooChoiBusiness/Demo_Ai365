// 리포트 에이전트 대시보드(2026-09-18) — 프런트 집계(ai365RdCompute)가 서버 compute 와 같은 값을 내는지, 차트 구성이 설정을 반영하는지.
// 실행: node --test tests/*.cjs  (static/report_dash.js 는 document 가 없으면 순수 함수만 내보낸다)
// Report-agent dashboards (2026-09-18) — the front-end aggregation must match the server's compute, and the Chart.js
// config must reflect the spec. Run: node --test tests/*.cjs (without a document the file exports only its pure functions)
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const rd = require(path.join(__dirname, '..', 'static', 'report_dash.js'));

const COLS = ['제품', '연도', '불량률', '검사수'];
const ROWS = [['FG-CREAM-01', 2025, 0.52, 100], ['FG-CREAM-01', 2026, 0.0, 140],
  ['FG-MASK-03', 2025, 0.23, 80], ['FG-MASK-03', 2026, 0.26, 90],
  ['BULK-TONER-01', 2025, 0.0, 60], ['BULK-TONER-01', 2026, 0.0, 70]];
const SRC = { id: 's1', name: 'Source 1', columns: COLS, rows: ROWS, types: { 제품: 'text', 연도: 'number', 불량률: 'number', 검사수: 'number' } };
function chart(over) {
  return Object.assign({ id: 'c1', source: 's1', type: 'bar', x: '제품', group: null, sort: { by: 'none', dir: 'desc' }, limit: null, stack: false,
    y: [{ col: '검사수', agg: 'sum', name: '검사수', type: 'bar', axis: 0 }], ref_lines: [], unit: '',
    style: { palette: 'indigo', labels: false, smooth: true, fill: false, legend: 'bottom', rounded: true, grid: true } }, over || {});
}

test('the same fixtures give the same numbers as tests/test_report_dash.py (sum, sort by value, limit)', () => {
  const c = rd.rdCompute(chart({ sort: { by: 'y', dir: 'desc' }, limit: 2 }), SRC, []);
  assert.deepEqual(c.x, ['FG-CREAM-01', 'FG-MASK-03']);
  assert.deepEqual(c.series[0].values, [240, 170]);
});

test('a group column splits series and the filters of the chart apply before aggregation', () => {
  const filters = [{ id: 'f1', col: '제품', label: '제품', selected: ['FG-MASK-03', 'BULK-TONER-01'] }];
  const c = rd.rdCompute(chart({ group: '연도', filters, y: [{ col: '불량률', agg: 'avg', name: '불량률', type: 'bar', axis: 0 }] }), SRC);
  assert.deepEqual(c.x, ['FG-MASK-03', 'BULK-TONER-01']);
  assert.deepEqual(c.series.map(s => [s.name, s.values]), [['2025', [0.23, 0]], ['2026', [0.26, 0]]]);
  assert.equal(c.rows, 4);
  // 필터는 차트(BI)마다 따로다 — 필터 없는 옆 차트는 전체를 본다 / filters are per chart: a chart without filters sees everything
  assert.equal(rd.rdCompute(chart(), SRC).x.length, 3);
  // 없는 컬럼의 필터와 빈 선택은 아무것도 거르지 않는다 / a filter on a missing column or with no selection filters nothing
  assert.equal(rd.rdFilteredRows(SRC, [{ col: '없음', selected: ['x'] }, { col: '제품', selected: [] }]).length, ROWS.length);
});

test('reference lines: fixed value and a statistic that follows the filtered values', () => {
  const spec = chart({ ref_lines: [{ id: 'r1', label: '목표', value: 200, stat: null }, { id: 'r2', label: '평균', value: null, stat: 'avg' }] });
  assert.deepEqual(rd.rdCompute(spec, SRC).refs.map(r => [r.label, r.value]), [['목표', 200], ['평균', 180]]);
  spec.filters = [{ id: 'f1', col: '제품', label: '제품', selected: ['FG-MASK-03'] }];
  assert.equal(rd.rdCompute(spec, SRC).refs[1].value, 170);
  assert.equal(rd.rdCompute(spec, SRC, []).refs[1].value, 180);             // 세 번째 인자로 필터를 바꿔 계산할 수 있다 / the third argument overrides the filters
});

test('pie folds the tail into 기타, a KPI is one number, keys follow String(v)', () => {
  const rows = Array.from({ length: 12 }, (_, i) => ['P' + i, 1, 20 - i, 1]);
  const src = Object.assign({}, SRC, { rows });
  const pie = rd.rdCompute(chart({ type: 'pie', y: [{ col: '불량률', agg: 'sum', name: '불량률', type: 'bar', axis: 0 }] }), src, []);
  assert.equal(pie.x.length, 8);
  assert.equal(pie.x[7], '기타');
  assert.equal(pie.series[0].values[7], [7, 8, 9, 10, 11].reduce((a, i) => a + (20 - i), 0));
  const kpi = rd.rdCompute(chart({ type: 'kpi', x: null, y: [{ col: '불량률', agg: 'max', name: '최대 불량률', type: 'bar', axis: 0 }] }), src, []);
  assert.deepEqual(kpi.series[0].values, [20]);
  assert.deepEqual([2025, 0.5, true, null, 'A'].map(rd.rdKey), ['2025', '0.5', 'true', '', 'A']);
  assert.deepEqual(['1,200', '12.5%', '', 'x', true].map(rd.rdNum), [1200, 12.5, null, null, null]);
});

test('x sort is numeric when every label is numeric, otherwise by code point', () => {
  const c = rd.rdCompute(chart({ x: '연도', sort: { by: 'x', dir: 'desc' } }), SRC, []);
  assert.deepEqual(c.x, ['2026', '2025']);
  assert.deepEqual(c.series[0].values, [300, 240]);
});

test('chart config: mixed bar and line with a right axis, reference lines widen the axis, labels and palette', () => {
  const spec = chart({ y: [{ col: '검사수', agg: 'sum', name: '검사수', type: 'bar', axis: 0 }, { col: '불량률', agg: 'avg', name: '불량률', type: 'line', axis: 1 }],
    ref_lines: [{ id: 'r1', label: '목표', value: 500, stat: null }], unit: '건',
    style: { palette: 'ocean', labels: true, smooth: false, fill: false, legend: 'top', rounded: false, grid: true } });
  const cfg = rd.rdChartConfig(spec, rd.rdCompute(spec, SRC, []));
  assert.equal(cfg.type, 'bar');
  assert.deepEqual(cfg.data.datasets.map(d => [d.type, d.yAxisID]), [['bar', 'y'], ['line', 'y1']]);
  assert.equal(cfg.data.datasets[1].borderColor, rd.PALETTES.ocean[1]);
  assert.equal(cfg.data.datasets[1].tension, 0);
  assert.equal(cfg.data.datasets[0].borderRadius, 0);
  assert.ok(cfg.options.scales.y1 && cfg.options.scales.y1.position === 'right');
  assert.ok(cfg.options.scales.y.suggestedMax >= 500);                       // 기준선이 축 안에 들어온다 / the line stays inside the axis
  assert.deepEqual(cfg.options.plugins.rdRefLines.lines.map(l => [l.label, l.value, l.text]), [['목표', 500, '500건']]);
  assert.deepEqual([cfg.options.plugins.rdValueLabels.on, cfg.options.plugins.legend.position], [true, 'top']);
});

test('chart config: pure lines use the line type, donut and horizontal bars map to Chart.js shapes', () => {
  const line = chart({ type: 'line', y: [{ col: '검사수', agg: 'sum', name: '검사수', type: 'line', axis: 0 }] });
  assert.equal(rd.rdChartConfig(line, rd.rdCompute(line, SRC, [])).type, 'line');
  const donut = chart({ type: 'donut' });
  const dc = rd.rdChartConfig(donut, rd.rdCompute(donut, SRC, []));
  assert.deepEqual([dc.type, dc.options.cutout, Object.keys(dc.options.scales).length, dc.options.plugins.legend.display], ['doughnut', '62%', 0, true]);
  assert.equal(dc.data.datasets[0].backgroundColor.length, dc.data.labels.length);
  const hbar = chart({ type: 'hbar' });
  const hc = rd.rdChartConfig(hbar, rd.rdCompute(hbar, SRC, []));
  assert.equal(hc.options.indexAxis, 'y');
  assert.ok(hc.options.scales.x.beginAtZero && !hc.options.scales.y.beginAtZero);   // 값 축은 x, 범주 축은 y / values on x, categories on y
  const stacked = chart({ type: 'area', stack: true, y: [{ col: '검사수', agg: 'sum', name: 'a', type: 'line', axis: 0 }, { col: '불량률', agg: 'sum', name: 'b', type: 'line', axis: 0 }] });
  const sc = rd.rdChartConfig(stacked, rd.rdCompute(stacked, SRC, []));
  assert.deepEqual(sc.data.datasets.map(d => d.fill), ['origin', '-1']);
  assert.ok(sc.options.scales.y.stacked);
});

test('number formatting keeps small decimals and abbreviates 억', () => {
  assert.equal(rd.rdFmt(0.5208, '%'), '0.52%');
  assert.equal(rd.rdFmt(12345.6), '12,346');
  assert.equal(rd.rdFmt(250000000, '원'), '2.5억원');
});

/* ── Visualize Agent 확장(2026-09-21): tests/test_report_dash_viz.py 와 같은 자료·같은 기대값 — 서버와 화면의 숫자가 같아야 한다 ──
   Visualize Agent extensions: the same fixtures and expectations as tests/test_report_dash_viz.py, so server and screen agree */
const VCOLS = ['지점', '월', '매출', '불량수', '검사수'];
const VROWS = [['강남점', '10월', 150, 3, 100], ['광주점', '10월', 30, 4, 40], ['강남점', '1월', 100, 1, 100], ['광주점', '1월', 50, 2, 50],
  ['강남점', '2월', 120, 2, 100], ['광주점', '2월', 40, 1, 50], ['강남점', '3월', 90, 0, 100], ['광주점', '3월', 60, 3, 60]];
const VSRC = { id: 's1', name: 'Source 1', columns: VCOLS, rows: VROWS, periods: { 월: 'month' },
  types: { 지점: 'text', 월: 'text', 매출: 'number', 불량수: 'number', 검사수: 'number' } };
function vchart(over) {
  return Object.assign({ id: 'c1', source: 's1', type: 'bar', x: '월', group: null, sort: { by: 'x', dir: 'asc' }, limit: null, stack: false, filters: [],
    y: [{ col: '매출', agg: 'sum', name: '매출', type: 'bar', axis: 0 }], ref_lines: [], unit: '',
    style: { palette: 'indigo', labels: false, smooth: true, fill: false, legend: 'bottom', rounded: true, grid: true } }, over || {});
}
const GANGNAM = [{ id: 'f1', col: '지점', label: '지점', selected: ['강남점'] }];
const yCalc = (calc, more) => [Object.assign({ col: '매출', agg: 'sum', name: '매출', type: 'line', axis: 0, calc }, more || {})];

test('period labels parse like the server: by shape, and bare digits only by the column hint', () => {
  const p = rd.rdParsePeriod;
  assert.deepEqual(['2026-03-15', '2026.3.5 00:00:00', '2026년 3월 15일'].map(v => p(v)), [['date', 2026, 315], ['date', 2026, 305], ['date', 2026, 315]]);
  assert.deepEqual(['2026-03', '2026/3', '2026년 3월', '3월', '12 월'].map(v => p(v)), [['month', 2026, 3], ['month', 2026, 3], ['month', 2026, 3], ['month', 0, 3], ['month', 0, 12]]);
  assert.deepEqual(['2026 Q1', '2026-Q4', '1분기', '2026년 2분기', '3Q'].map(v => p(v)), [['quarter', 2026, 1], ['quarter', 2026, 4], ['quarter', 0, 1], ['quarter', 2026, 2], ['quarter', 0, 3]]);
  assert.deepEqual(['12주차', 'W05', '2026-W12', '2026년'].map(v => p(v)), [['week', 0, 12], ['week', 0, 5], ['week', 2026, 12], ['year', 2026, 0]]);
  assert.deepEqual(['13월', '강남점', '', '2026', 2026, '202603', 3].map(v => p(v)), [null, null, null, null, null, null, null]);
  assert.deepEqual([p(2026, 'year'), p('202603', 'month'), p(3, 'month'), p('2', 'quarter'), p('20260315', 'date')],
    [['year', 2026, 0], ['month', 2026, 3], ['month', 0, 3], ['quarter', 0, 2], ['date', 2026, 315]]);
});

test('a period axis sorts by period, and order-dependent calcs run after sorting and before the limit', () => {
  assert.deepEqual(rd.rdCompute(vchart(), VSRC).x, ['1월', '2월', '3월', '10월']);
  assert.deepEqual(rd.rdCompute(vchart({ sort: { by: 'x', dir: 'desc' } }), VSRC).x, ['10월', '3월', '2월', '1월']);
  const run = (calc, more, over) => rd.rdCompute(vchart(Object.assign({ filters: GANGNAM, y: yCalc(calc, more) }, over || {})), VSRC).series[0];
  assert.deepEqual(run('pct_prev', { unit: '%' }).values, [null, 20, -25, 66.666667]);
  assert.deepEqual([run('pct_prev', { unit: '%' }).unit, run('pct_prev').calc], ['%', 'pct_prev']);
  assert.deepEqual(run('diff_prev').values, [null, 20, -30, 60]);
  assert.deepEqual(run('cumsum').values, [100, 220, 310, 460]);
  assert.deepEqual(run('moving_avg', { window: 2 }).values, [null, 110, 105, 120]);
  assert.deepEqual(run('cumsum', {}, { limit: 2 }).values, [100, 220]);
});

test('share, rank and pair calcs run before sorting so a chart can sort by them; year over year pairs the same period', () => {
  const ratio = rd.rdCompute(vchart({ x: '지점', sort: { by: 'y', dir: 'desc' },
    y: [{ col: '불량수', agg: 'sum', name: '불량수 ÷ 검사수', type: 'bar', axis: 0, calc: 'ratio_pct', by: { col: '검사수', agg: 'sum' }, unit: '%' }] }), VSRC);
  assert.deepEqual([ratio.x, ratio.series[0].values], [['광주점', '강남점'], [5, 1.5]]);
  assert.deepEqual(rd.rdCompute(vchart({ x: '지점', sort: { by: 'none' }, y: yCalc('share') }), VSRC).series[0].values, [71.875, 28.125]);
  assert.deepEqual(rd.rdCompute(vchart({ y: yCalc('rank') }), VSRC).series[0].values, [3, 2, 3, 1]);
  const pareto = rd.rdCompute(vchart({ x: '지점', sort: { by: 'y', dir: 'desc' }, y: [vchart().y[0]].concat(yCalc('cum_share')) }), VSRC);
  assert.deepEqual([pareto.x, pareto.series[1].values], [['강남점', '광주점'], [71.875, 100]]);
  const src = { id: 's1', name: 'Source 1', columns: ['월', '매출'], rows: [['2025-01', 100], ['2025-02', 200], ['2026-01', 150], ['2026-02', 100]],
    types: { 월: 'text', 매출: 'number' }, periods: { 월: 'month' } };
  assert.deepEqual(rd.rdCompute(vchart({ y: yCalc('yoy') }), src).series[0].values, [null, null, 50, -50]);
});

test('highlight rules give the same hits as the server, and the colours follow them', () => {
  const rule = (over) => Object.assign({ id: 'h1', kind: 'top', op: null, value: null, stat: null, ref: '', n: null, items: [], color: '', label: 'x', dim: false, series: '' }, over);
  const spec = vchart({ ref_lines: [{ id: 'r1', label: '목표', value: 160, stat: null }],
    highlights: [rule({ id: 'h1', kind: 'ref', op: 'lt', ref: 'r1', color: '#E03131', label: '목표 미달' }), rule({ id: 'h2', kind: 'top', n: 3, label: '상위 3', dim: true })] });
  const comp = rd.rdCompute(spec, VSRC);                                       // 매출: 1월 150, 2월 160, 3월 150, 10월 180
  assert.deepEqual(comp.marks.map(m => [m.label, m.hits]), [['목표 미달', [0, 2]], ['상위 3', [1, 3]]]);
  assert.deepEqual(rd.rdMarkColors(comp, 0, '#5B5BD6'), [['#E03131', false], ['#5B5BD6', false], ['#E03131', false], ['#5B5BD6', false]]);
  spec.ref_lines[0].value = 100;
  assert.deepEqual(rd.rdCompute(spec, VSRC).marks[0].hits, []);
  const more = rd.rdCompute(vchart({ highlights: [rule({ id: 'h1', kind: 'value', op: 'gte', value: 170, label: 'a' }),
    rule({ id: 'h2', kind: 'items', items: ['1월', '없는달'], label: 'b', dim: true }), rule({ id: 'h3', kind: 'bottom', n: 2, label: 'c', dim: true })] }), VSRC);
  assert.deepEqual(more.marks.map(m => m.hits), [[3], [0], [2]]);
  assert.deepEqual(rd.rdMarkColors(more, 0, '#111111')[1], ['#111111', true]);   // 어느 규칙에도 안 걸린 막대는 흐리게 / a bar no rule hits is dimmed
  assert.deepEqual(rd.rdCompute(vchart({ highlights: [rule({ kind: 'stat', stat: 'avg', op: 'gte' })] }), VSRC).marks[0].hits, [1, 3]);
  assert.equal(rd.rdCompute(vchart({ type: 'pie', highlights: [rule({ n: 1 })] }), VSRC).marks, undefined);
  assert.equal(rd.rdMarkColors(rd.rdCompute(vchart(), VSRC), 0, '#111111'), null);
});

test('chart config: a percent series reads its own unit on the right axis, marks colour bars per index, picks are reported only when asked', () => {
  const spec = vchart({ unit: '원', y: [vchart().y[0], { col: '매출', agg: 'sum', name: '매출 증감률', type: 'line', axis: 1, calc: 'pct_prev', unit: '%' }],
    highlights: [{ id: 'h1', kind: 'top', n: 1, color: '', label: '상위 1', dim: true, series: '' }] });
  const cfg = rd.rdChartConfig(spec, rd.rdCompute(spec, VSRC));
  assert.deepEqual(cfg.data.datasets.map(d => [d.type, d.yAxisID, d.rdUnit]), [['bar', 'y', '원'], ['line', 'y1', '%']]);
  assert.equal(cfg.options.scales.y.ticks.callback(1000), '1,000원');
  assert.equal(cfg.options.scales.y1.ticks.callback(12.5), '12.5%');
  assert.equal(typeof cfg.data.datasets[0].backgroundColor, 'function');
  assert.deepEqual(cfg.data.datasets[1].data, [null, 6.666667, -6.25, 20]);      // 빈 칸은 null 그대로(선이 끊긴다) / gaps stay null
  // 클릭은 화면 쪽 처리기가 받는다(Chart.js onClick 은 한 프레임 늦다) — 설정은 누를 수 있는 곳의 커서만 바꾼다
  // The DOM handler takes the click (Chart.js calls onClick a frame late); the config only marks pickable marks with a cursor
  assert.deepEqual([cfg.options.onClick, cfg.options.onHover], [undefined, undefined]);
  const hover = rd.rdChartConfig(spec, rd.rdCompute(spec, VSRC), { pickable: true }).options.onHover;
  const canvas = { style: {} };
  hover({}, [], { canvas, getElementsAtEventForMode: () => [{ index: 2 }] });
  assert.equal(canvas.style.cursor, 'zoom-in');
  hover({}, [], { canvas, getElementsAtEventForMode: () => [] });
  assert.equal(canvas.style.cursor, '');
});

test('the drilled view narrows by the picked values, moves x down, and keeps only what still makes sense', () => {
  const top = vchart({ x: '지점', sort: { by: 'y', dir: 'desc' }, limit: 5, ref_lines: [{ id: 'r1', label: '목표', value: 300, stat: null }],
    highlights: [{ id: 'h1', kind: 'top', n: 1, color: '', label: '상위 1', dim: true, series: '' }], filters: [{ id: 'f1', col: '월', label: '월', selected: ['1월', '2월', '10월'] }] });
  assert.equal(rd.rdDrillChart(top, VSRC, []), top);
  const d1 = rd.rdDrillChart(top, VSRC, [{ col: '지점', value: '강남점', next: '월' }]);
  assert.deepEqual([d1.type, d1.x, d1.sort, d1.limit, d1.ref_lines, d1.highlights, d1.y[0].type], ['line', '월', { by: 'x', dir: 'asc' }, null, [], [], 'line']);
  assert.deepEqual(d1.filters.map(f => [f.col, f.selected]), [['월', ['1월', '2월', '10월']], ['지점', ['강남점']]]);
  const c1 = rd.rdCompute(d1, VSRC);
  assert.deepEqual([c1.x, c1.series[0].values], [['1월', '2월', '10월'], [100, 120, 150]]);
  assert.equal(top.x, '지점');                                                               // 원래 설정은 그대로 / the stored spec is untouched
  // 기간 축에서 범주 축으로 내려가면 선 → 막대, 순서가 뜻인 계산은 걷는다 / from a period axis down to categories: line → bar, order-dependent calcs go
  const trend = vchart({ type: 'line', y: yCalc('pct_prev', { unit: '%', name: '매출 증감률' }) });
  const d2 = rd.rdDrillChart(trend, VSRC, [{ col: '월', value: '3월', next: '지점' }]);
  assert.deepEqual([d2.type, d2.sort, d2.y[0].calc, d2.y[0].unit, d2.y[0].name, d2.y[0].type], ['bar', { by: 'y', dir: 'desc' }, undefined, undefined, '매출', 'bar']);
  assert.deepEqual(rd.rdCompute(d2, VSRC).series[0].values, [90, 60]);
  const share = rd.rdDrillChart(vchart({ x: '지점', y: yCalc('share', { unit: '%' }) }), VSRC, [{ col: '지점', value: '강남점', next: '월' }]);
  assert.equal(share.y[0].calc, 'share');                                                    // 순서와 무관한 계산은 남는다 / order-independent calcs stay
});

test('a click picks the bar it hits, a line point within 16px (Chart.js event or DOM click), and nothing on empty space', () => {
  const pick = rd.rdPickIndex, el = { x: 100, y: 50 };
  // 누른 자리에 걸린 것(intersect) / 가장 가까운 점(intersect 아님)을 돌려주는 가짜 차트 / a fake chart returning the hit (intersect) or the nearest point
  const fake = (type, hit, near) => ({ config: { type }, canvas: { getBoundingClientRect: () => ({ left: 20, top: 30 }) },
    getElementsAtEventForMode: (evt, mode, opts) => (opts.intersect ? hit : near) });
  assert.equal(pick(fake('bar', [{ index: 2 }], []), { x: 0, y: 0, native: {} }), 2);
  assert.equal(pick(fake('bar', [], [{ index: 1, element: el }]), { x: 100, y: 50, native: {} }), -1);   // 막대·조각은 그 위를 눌러야 한다 / bars and slices need a hit
  const line = fake('line', [], [{ index: 3, element: el }]);
  assert.equal(pick(line, { x: 110, y: 62, native: {} }), 3);                                 // 15.6px
  assert.equal(pick(line, { x: 100, y: 67, native: {} }), -1);                                // 17px
  assert.equal(pick(line, { clientX: 20 + 109, clientY: 30 + 62 }), 3);                       // DOM 클릭은 캔버스 좌표로 바꿔 잰다 / a DOM click is measured on the canvas
  assert.equal(pick(line, { clientX: 20 + 100, clientY: 30 + 70 }), -1);
  assert.equal(pick(fake('line', [], []), { x: 1, y: 1, native: {} }), -1);
  // 경로 이름표 = (컬럼, 값) 목록 — 값의 모양·다음 컬럼·서버 단계 표시와 무관 / the path signature is (column, value) pairs only
  assert.equal(rd.rdDrillSig([{ col: '지점', value: '강남점', next: '월' }, { col: '월', value: null, remote: true }]), JSON.stringify([['지점', '강남점'], ['월', '']]));
  assert.equal(rd.rdDrillSig([{ col: 'a', value: 1 }]), rd.rdDrillSig([{ col: 'a', value: '1', next: 'x', remote: true }]));
  assert.equal(rd.rdDrillSig(undefined), '[]');
});

test('a pie or donut picks the slice in the direction of the click from the centre, never the legend, the middle or far away', () => {
  // 중심 (100,100) · 반지름 50, Chart.js 조각은 12시(-π/2)에서 시계 방향: 0 = 0~180°, 1 = 180~288°, 2 = 288~360°
  // Centre (100,100), radius 50; Chart.js slices run clockwise from 12 o'clock: 0 = 0-180°, 1 = 180-288°, 2 = 288-360°
  const q = Math.PI / 2, arcs = [[-q, q], [q, q + Math.PI * 0.6], [q + Math.PI * 0.6, 3 * q]]
    .map(([s, e]) => ({ getProps: () => ({ x: 100, y: 100, outerRadius: 50, startAngle: s, endAngle: e }) }));
  const pie = (over) => Object.assign({ config: { type: 'doughnut' }, chartArea: { left: 0, top: 0, right: 200, bottom: 200 },
    canvas: { getBoundingClientRect: () => ({ left: 10, top: 20 }) }, getElementsAtEventForMode: () => [], getDatasetMeta: () => ({ data: arcs }) }, over);
  const at = (deg, away) => { const r = (deg - 90) * Math.PI / 180; return { x: 100 + Math.cos(r) * away, y: 100 + Math.sin(r) * away, native: {} }; };
  const pick = (deg, away, over) => rd.rdPickIndex(pie(over), at(deg, away));
  assert.deepEqual([pick(90, 20), pick(200, 60), pick(300, 40), pick(359, 30), pick(181, 30)], [0, 1, 2, 2, 1]);   // 구멍 · 고리 바깥도 그 방향 / the hole and just outside count
  assert.deepEqual([pick(10, 5), pick(90, 75)], [-1, -1]);                        // 한가운데(0.15r 안) · 너무 먼 곳(1.4r 밖) / the very middle and too far
  assert.equal(pick(90, 30, { chartArea: { left: 0, top: 0, right: 120, bottom: 200 } }), -1);   // 그림 영역 밖 = 범례 / outside the chart area: the legend
  assert.equal(rd.rdPickIndex(pie(), { clientX: 10 + 130, clientY: 20 + 100 }), 0); // DOM 클릭은 캔버스 좌표로 / a DOM click, in canvas coordinates
  assert.equal(pick(300, 40, { getElementsAtEventForMode: (e, m, o) => (o.intersect ? [{ index: 1 }] : []) }), 1);   // 조각 위면 그 조각 / on a slice, that slice
  assert.equal(pick(90, 20, { config: { type: 'bar' } }), -1);                    // 막대는 여전히 그 위만 / bars still need a hit
});

test('the zoom cursor skips the pie\'s "others" slice, which folds several values and cannot drill', () => {
  const src = { id: 's1', name: 'Source 1', columns: ['m', 'v'], rows: Array.from({ length: 10 }, (_, i) => ['k' + i, 10 - i]), types: { m: 'text', v: 'number' } };
  const spec = chart({ type: 'pie', x: 'm', y: [{ col: 'v', agg: 'sum', name: 'v', type: 'bar', axis: 0 }] });
  const comp = rd.rdCompute(spec, src);
  assert.equal(comp.x[7], rd.OTHERS);
  const hover = rd.rdChartConfig(spec, comp, { pickable: true }).options.onHover, canvas = { style: {} };
  const over = (i) => { hover({}, [], { canvas, config: { type: 'pie' }, getElementsAtEventForMode: () => [{ index: i }] }); return canvas.style.cursor; };
  assert.deepEqual([over(0), over(7), over(6)], ['zoom-in', '', 'zoom-in']);
});

test('each drill level is that level\'s own total, and a ratio is Σnumerator ÷ Σdenominator on every level, not an average of ratios', () => {
  // 받은 드릴다운 코드의 K01 · K02 와 같은 자료 / the same data as the reviewed drill-down code's K01 and K02
  const cols = ['브랜드', '딜러사', '전시장', '건수', 'IN', '전체'];
  const rows = [['LEXUS', '렉서스 강남', '강남1', 30, 3, 10], ['LEXUS', '렉서스 강남', '강남2', 20, 1, 10], ['LEXUS', '렉서스 분당', '분당1', 15, 9, 10],
    ['TOYOTA', '토요타 용산', '용산1', 40, 2, 20], ['TOYOTA', '토요타 서초', '서초1', 5, 5, 5]];
  const src = { id: 's1', name: 'Source 1', columns: cols, rows, types: { 브랜드: 'text', 딜러사: 'text', 전시장: 'text', 건수: 'number', IN: 'number', 전체: 'number' } };
  const base = chart({ x: '브랜드', sort: { by: 'y', dir: 'desc' }, y: [{ col: '건수', agg: 'sum', name: '건수', type: 'bar', axis: 0 },
    { col: 'IN', agg: 'sum', name: '방어율', type: 'bar', axis: 0, calc: 'ratio_pct', by: { col: '전체', agg: 'sum' }, unit: '%' }] });
  const level = (path) => { const c = rd.rdCompute(rd.rdDrillChart(base, src, path), src); return Object.fromEntries(c.x.map((k, i) => [k, c.series.map(s => s.values[i])])); };
  const lexus = { col: '브랜드', value: 'LEXUS', next: '딜러사' };
  assert.deepEqual(level([]), { LEXUS: [65, 43.333333], TOYOTA: [45, 28] });   // TOYOTA 는 비율 평균이면 55% / 55% if ratios were averaged
  assert.deepEqual(level([lexus]), { '렉서스 강남': [50, 20], '렉서스 분당': [15, 90] });
  assert.deepEqual(level([lexus, { col: '딜러사', value: '렉서스 강남', next: '전시장' }]), { 강남1: [30, 30], 강남2: [20, 10] });
});

test('clones are linked to their root rows, and a summary number follows the linked chart and compares periods like the server', () => {
  const state = { sources: [Object.assign({}, VSRC, { origin: { clone_of: '' } }),
    { id: 's2', name: 'Source 2', columns: VCOLS, rows: [], types: {}, periods: {}, origin: { clone_of: 's1' } }],
    charts: [vchart({ filters: GANGNAM }), vchart({ id: 'c2', source: 's2', x: '지점' })] };
  rd.rdLinkClones(state);
  assert.equal(state.sources[1].rows, state.sources[0].rows);                               // 복사가 아니라 같은 배열 / the same array, not a copy
  assert.deepEqual([state.sources[1].periods, rd.rdCompute(state.charts[1], state.sources[1]).x], [{ 월: 'month' }, ['강남점', '광주점']]);
  const k = { id: 'k1', source: 's1', col: '매출', agg: 'sum', label: '매출 합계', unit: '', link: 'c1', delta: 'prev' };
  const v = rd.rdKpi(k, state);                                                              // 강남점: 1월 100 … 3월 90, 10월 150
  assert.deepEqual([v.value, v.period, v.prev_period, v.delta], [460, '10월', '3월', 66.666667]);
  state.charts[0].filters = [];
  assert.equal(rd.rdKpi(k, state).value, 640);
  assert.deepEqual(rd.rdKpi({ source: 's1', col: '*', agg: 'count', link: '', delta: '' }, state), { value: 8, rows: 8 });
  // 직접 적은 숫자 카드(2026-10-12)는 데이터 없이 그 값 / a typed-number card shows its value without data
  assert.deepEqual(rd.rdKpi({ id: 'k2', source: '', col: '', agg: '', label: '목표', unit: '원', link: '', delta: '', value: 1200, note: '' }, state), { value: 1200, rows: 0, manual: true });
});

test('a compare group shares one value range, and notes sit on the tallest value of their x while it is in view', () => {
  const a = vchart({ filters: GANGNAM }), b = vchart({ filters: [{ id: 'f1', col: '지점', label: '지점', selected: ['광주점'] }] });
  const range = rd.rdCompareRange([[a, rd.rdCompute(a, VSRC)], [b, rd.rdCompute(b, VSRC)]]);
  assert.deepEqual(range, { min: 0, max: 150 });
  const small = rd.rdChartConfig(b, rd.rdCompute(b, VSRC), { lock: range });
  assert.equal(small.options.scales.y.suggestedMax, 150);                                    // 작은 쪽도 큰 쪽의 눈금을 쓴다 / the small chart takes the big one's scale
  assert.equal(rd.rdChartConfig(b, rd.rdCompute(b, VSRC)).options.scales.y.suggestedMax, undefined);
  const stacked = vchart({ stack: true, y: [vchart().y[0], { col: '검사수', agg: 'sum', name: '검사수', type: 'bar', axis: 0 }] });
  assert.equal(rd.rdCompareRange([[stacked, rd.rdCompute(stacked, VSRC)]]).max, 320);       // 누적이면 합 기준(10월 180 + 140) / stacked sums
  const noted = vchart({ notes: [{ id: 'n1', x: '3월', text: '신제품 출시' }, { id: 'n2', x: '없는달', text: 'x' }] });
  const cfg = rd.rdChartConfig(noted, rd.rdCompute(noted, VSRC));
  assert.deepEqual(cfg.options.plugins.rdNotes.notes, [{ index: 2, value: 150, text: '신제품 출시' }]);
  assert.equal(cfg.options.layout.padding.top, 38);
  assert.deepEqual(rd.rdDrillChart(noted, VSRC, [{ col: '월', value: '3월', next: '지점' }]).notes, []);
});

test('range filters follow the column kind like the server: the last N periods of the data, from~to, and min~max', () => {
  const rowsOf = (filters) => rd.rdFilteredRows(VSRC, filters);
  assert.deepEqual([...new Set(rowsOf([{ col: '월', selected: [], range: { last: 2 } }]).map(r => r[1]))].sort(), ['10월', '3월']);
  assert.deepEqual(rowsOf([{ col: '매출', selected: [], range: { min: 50, max: 120 } }]).map(r => r[2]), [100, 50, 120, 90, 60]);
  assert.deepEqual(rowsOf([{ col: '월', range: { last: 2 } }, { col: '매출', range: { min: 50, max: 120 } }, { col: '지점', selected: ['강남점'] }]).map(r => r[2]), [90]);
  assert.deepEqual([...new Set(rowsOf([{ col: '월', range: { from: '2월', to: '' } }]).map(r => r[1]))].sort(), ['10월', '2월', '3월']);
  assert.equal(rowsOf([{ col: '월', range: { from: '', to: '' }, selected: [] }]).length, VROWS.length);
  assert.equal(rd.rdRangeTest(VSRC, '지점', { min: null, max: null }), null);
});

test('next period labels continue the shape of the last label, exactly like the server', () => {
  const nx = rd.rdNextPeriodLabels;
  assert.deepEqual(nx(['2025-11', '2025-12'], 'month', 2), ['2026-01', '2026-02']);
  assert.deepEqual(nx(['2025.9'], 'month', 2), ['2025.10', '2025.11']);
  assert.deepEqual(nx(['2025년 12월'], 'month', 1), ['2026년 1월']);
  assert.deepEqual(nx(['11월', '12월'], 'month', 2), ['1월', '2월']);
  assert.deepEqual(nx(['202511', '202512'], 'month', 1), ['202601']);
  assert.deepEqual(nx(['2025 Q3', '2025 Q4'], 'quarter', 2), ['2026 Q1', '2026 Q2']);
  assert.deepEqual(nx(['3분기'], 'quarter', 2), ['4분기', '1분기']);
  assert.deepEqual(nx(['2025', '2026'], 'year', 2), ['2027', '2028']);
  assert.deepEqual(nx(['2026년'], 'year', 1), ['2027년']);
  assert.deepEqual(nx(['W08', 'W09'], 'week', 2), ['W10', 'W11']);
  assert.deepEqual(nx(['2026-02-14', '2026-02-21', '2026-02-28'], 'date', 2), ['2026-03-07', '2026-03-14']);
  assert.deepEqual(nx(['20261230', '20261231'], 'date', 1), ['20270101']);
  assert.deepEqual(nx(['강남점'], 'month', 2), []);
});

test('trend line and forecast match the server, and the config draws them as auxiliary series on a longer axis', () => {
  const rows = [755, 779, 802, 826, 858, 887, 920, 966].map((v, i) => ['2025-0' + (i + 1), v]);
  const src = { id: 's1', name: 'Source 1', columns: ['월', '매출'], rows, types: { 월: 'text', 매출: 'number' }, periods: { 월: 'month' } };
  const spec = vchart({ type: 'line', y: [{ col: '매출', agg: 'sum', name: '매출', type: 'line', axis: 0 }], trend: { line: true, forecast: 3, method: 'linear', series: '' } });
  const comp = rd.rdCompute(spec, src), tr = comp.trend;
  assert.deepEqual([tr.slope, tr.points, tr.values[0], tr.values[7]], [29.392857, 8, 746.25, 952]);
  assert.deepEqual([tr.forecast.labels, tr.forecast.values, tr.forecast.method], [['2025-09', '2025-10'], [981.392857, 1010.785714], 'linear']);
  assert.ok(Math.abs(tr.forecast.high[0] - tr.forecast.values[0] - 17.192884) < 1e-4);
  assert.equal(rd.rdCompute(Object.assign({}, spec, { trend: { line: true, forecast: 3 } }), Object.assign({}, src, { rows: rows.slice(0, 5) })).trend.forecast, undefined);
  const cfg = rd.rdChartConfig(spec, comp);
  assert.deepEqual(cfg.data.labels.slice(-3), ['2025-08', '2025-09', '2025-10']);
  assert.deepEqual(cfg.data.datasets.map(d => [d.label, d.data.length, !!d.rdAux]), [['매출', 10, false], ['추세선', 10, true], ['예측(참고용)', 10, true], ['예측 범위', 10, true], ['예측 범위', 10, true]]);
  assert.deepEqual(cfg.data.datasets[2].data.slice(6), [null, 966, 981.392857, 1010.785714]);   // 마지막 실제 값에서 이어진다 / continues from the last actual value
  assert.deepEqual(cfg.data.datasets[0].data.slice(-2), [null, null]);
  const year2 = [];
  for (const y of [2024, 2025]) for (let m = 1; m <= 12; m++) year2.push([y + '-' + String(m).padStart(2, '0'), (100 + m * 10) * (y === 2024 ? 1 : 1.5)]);
  const seasonal = rd.rdCompute(Object.assign({}, spec, { trend: { forecast: 2, method: 'seasonal' } }), Object.assign({}, src, { rows: year2 })).trend.forecast;
  assert.deepEqual([seasonal.method, seasonal.labels, seasonal.values], ['seasonal', ['2026-01', '2026-02'], [247.5, 270]]);
});

test('a theme makes six readable series colours from the brand colour and only charts on the theme palette use them', () => {
  const pal = rd.rdThemePalette({ brand: '#0F6E56', second: '' });
  assert.equal(pal.length, 6);
  assert.ok(pal.every(c => /^#[0-9A-F]{6}$/.test(c)) && new Set(pal).size === 6);
  assert.equal(rd.rdThemePalette({ brand: 'teal' }), null);
  const themed = vchart({ style: Object.assign({}, vchart().style, { palette: 'theme' }) });
  const comp = rd.rdCompute(themed, VSRC);
  const line = Object.assign({}, themed, { type: 'line', y: [Object.assign({}, themed.y[0], { type: 'line' })] });
  assert.equal(rd.rdChartConfig(line, rd.rdCompute(line, VSRC), { theme: { brand: '#0F6E56' } }).data.datasets[0].borderColor, pal[0]);
  assert.equal(rd.rdChartConfig(line, rd.rdCompute(line, VSRC)).data.datasets[0].borderColor, rd.PALETTES.indigo[0]);   // 테마가 없으면 기본 색 / default without a theme
  assert.ok(comp.x.length > 0);
});

test('the activity tree groups consecutive tool calls under their agent, keeping the order', () => {
  const trace = [{ agent: 'Data Agent', tool: 'query_data' }, { agent: 'Visualize Agent', tool: 'create_chart' },
    { agent: 'Visualize Agent', tool: 'set_insight' }, { agent: 'Data Agent', tool: 'query_data' }];
  assert.deepEqual(rd.rdTraceTree(trace).map(g => [g.agent, g.tools.map(t => t.tool)]),
    [['Data Agent', ['query_data']], ['Visualize Agent', ['create_chart', 'set_insight']], ['Data Agent', ['query_data']]]);
  assert.deepEqual(rd.rdTraceTree(null), []);
});
