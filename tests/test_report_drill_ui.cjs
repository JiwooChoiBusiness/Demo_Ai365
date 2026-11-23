// 실행: Playwright 가 NODE_PATH 에 있을 때 node --test tests/test_report_drill_ui.cjs
// 리포트 에이전트 드릴다운 화면(2026-09-30) — 게시판 읽기 전용 뷰어(패널과 같은 렌더·클릭 코드)에 대시보드를 올리고 실제 마우스로 막대·점을 누른다.
// Chart.js 는 저장소의 vendored 파일, /api/reports/drill 은 fetch 스텁이다. 앱 서버 · DB · LLM 없음.
// Run with Playwright on NODE_PATH: node --test tests/test_report_drill_ui.cjs
// Report-agent drill-down UI (2026-09-30): a dashboard mounted in the board's read-only viewer (the same rendering and click
// code as the panel), clicked with a real mouse. Chart.js is the repository's vendored file and /api/reports/drill is a fetch
// stub. No app server, no DB, no LLM.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const ROOT = path.join(__dirname, '..');
const STYLE = { palette: 'indigo', labels: false, smooth: false, fill: false, legend: 'none', rounded: true, grid: true };
function chart(over) {
  return Object.assign({ type: 'bar', group: null, sort: { by: 'none', dir: 'desc' }, limit: null, stack: false, ref_lines: [], unit: '',
    filters: [], style: STYLE, size: 'full' }, over);
}
function source(id, columns, rows, over) {
  const types = {};
  columns.forEach((c, i) => { types[c] = typeof rows[0][i] === 'number' ? 'number' : 'text'; });
  return Object.assign({ id, name: 'Source ' + id.slice(1), label: '', columns, rows, types, periods: {}, sql: '', tables: ['t'],
    fetched_at: '2026-09-30T10:00:00', origin: { kind: 'chat', note: '', chat_id: '', clone_of: '' } }, over || {});
}
const REFUSED = '이 조회는 모양이 복잡해 더 내려갈 수 없습니다';   // = app/report_drill.MSG_SHAPE
const DATA = {
  title: '드릴다운', kpis: [],
  sources: [
    source('s1', ['branch', 'total_sales'], [['서울중앙', 300], ['울산', 200], ['대구', 100]], { sql: 'SELECT branch, SUM(v) AS total_sales FROM sales GROUP BY branch' }),
    source('s2', ['dept', 'cnt'], [['인사', 3], ['영업', 5]]),   // 조회 SQL 이 없는 옛 저장분 / a legacy save without SQL
    source('s3', ['dept', 'cnt'], [['인사', 3], ['영업', 5]], { sql: 'SELECT dept, COUNT(*) AS cnt FROM hr_employees GROUP BY dept' }),
    source('s4', ['m', 'v'], [['2025-01', 1], ['2025-02', 2]], { sql: 'WITH q AS (SELECT 1) SELECT * FROM q', periods: { m: 'month' } }),
    source('s5', ['m', 'v'], [['2025-01', 10], ['2025-02', 30], ['2025-03', 20]], { sql: 'SELECT m, SUM(v) AS v FROM t_refuse GROUP BY m', periods: { m: 'month' } }),
    source('s6', ['m', 'v'], [['2025-01', 1], ['2025-02', 2]], { sql: 'SELECT m, v FROM t_rows ORDER BY m', periods: { m: 'month' } }),
    // 조회 SQL 없는 행 데이터: a~e 가 단계마다 둘로 나뉜다(32행) / rows without SQL where a..e each split in two at every level
    source('s9', ['a', 'b', 'c', 'd', 'e', 'v'], Array.from({ length: 32 }, (_, i) => ['a', 'b', 'c', 'd', 'e'].map((k, j) => k + (((i >> (4 - j)) & 1) + 1)).concat([1]))),
  ],
  charts: [
    chart({ id: 'c1', source: 's1', title: '지점별 매출', x: 'branch', insight: '맨 위 단계 설명', y: [{ col: 'total_sales', agg: 'sum', name: '총 매출', type: 'bar', axis: 0 }] }),
    chart({ id: 'c2', source: 's2', title: '옛 부서', x: 'dept', y: [{ col: 'cnt', agg: 'sum', name: '인원', type: 'bar', axis: 0 }] }),
    chart({ id: 'c3', source: 's3', title: '부서', x: 'dept', y: [{ col: 'cnt', agg: 'sum', name: '인원', type: 'bar', axis: 0 }] }),
    chart({ id: 'c4', source: 's4', title: '월', x: 'm', type: 'line', y: [{ col: 'v', agg: 'sum', name: '값', type: 'line', axis: 0 }] }),
    chart({ id: 'c5', source: 's5', title: '월 추이', x: 'm', type: 'line', y: [{ col: 'v', agg: 'sum', name: '값', type: 'line', axis: 0 }] }),
    chart({ id: 'c6', source: 's6', title: '월별 행', x: 'm', type: 'line', y: [{ col: 'v', agg: 'sum', name: '값', type: 'line', axis: 0 }] }),
    // 값 컬럼 범위 필터(총 매출 150 이상) — 지점 합계에 맞춘 조건 / a measure range filter meant for branch totals
    chart({ id: 'c7', source: 's1', title: '큰 지점', x: 'branch', filters: [{ id: 'f1', col: 'total_sales', label: 'total_sales', selected: [], range: { min: 150, max: null } }],
      y: [{ col: 'total_sales', agg: 'sum', name: '총 매출', type: 'bar', axis: 0 }] }),
    chart({ id: 'c8', source: 's1', title: '고른 지점', x: 'branch', filters: [{ id: 'f1', col: 'branch', label: 'branch', selected: ['서울중앙', '울산'] }],
      y: [{ col: 'total_sales', agg: 'sum', name: '총 매출', type: 'bar', axis: 0 }] }),
    chart({ id: 'c9', source: 's9', title: '깊은 행', x: 'a', y: [{ col: 'v', agg: 'sum', name: '값', type: 'bar', axis: 0 }] }),
    chart({ id: 'c10', source: 's9', title: '정해 둔 순서', x: 'a', drill: ['b'], y: [{ col: 'v', agg: 'sum', name: '값', type: 'bar', axis: 0 }] }),
    // 에이전트가 정한 순서의 month 는 받아 둔 데이터(지점별 합계)에 없다 — 서버가 그 단계를 가져온다(2026-10-01)
    // The agent's path names month, which the fetched branch totals lack: the server fetches that level (2026-10-01)
    chart({ id: 'c11', source: 's1', title: '정한 순서 · 서버', x: 'branch', drill: ['month'], y: [{ col: 'total_sales', agg: 'sum', name: '총 매출', type: 'bar', axis: 0 }] }),
    chart({ id: 'c12', source: 's9', title: '도넛', type: 'donut', x: 'a', drill: ['b'], y: [{ col: 'v', agg: 'sum', name: '값', type: 'bar', axis: 0 }] }),
  ],
};
// 행 조회를 서버로 한 단계 내리면 원래 컬럼 + 지점이 온다 — 이 안에서는 권역이 지점을 나눈다(로컬로 한 단계 더)
// A row query one server level down brings its columns plus branch; inside it region splits a branch (one more local level)
const ROWS = source('s6', ['branch', 'm', 'region', 'v'], [['울산', '2025-02', '동', 1], ['울산', '2025-02', '서', 2], ['대구', '2025-02', '남', 5]],
  { sql: 'SELECT "t_rows"."branch" AS "branch", m, v FROM t_rows WHERE CAST(m AS TEXT) = \'2025-02\' ORDER BY "t_rows"."branch", m', periods: { m: 'month' } });
const MONTHS = source('s1', ['month', 'total_sales'], [['2025-01', 50], ['2025-02', 70], ['2025-03', 80]],
  { sql: 'SELECT month, SUM(v) AS total_sales FROM sales WHERE CAST(branch AS TEXT) = \'울산\' GROUP BY month', periods: { month: 'month' } });
const TITLES = source('s3', ['title', 'cnt'], [['대리', 2], ['과장', 1]], { sql: 'SELECT title, COUNT(*) AS cnt FROM hr_employees GROUP BY title' });

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

async function fixture(t) {
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  t.after(async () => { await page.close(); assert.deepEqual(errors, []); });
  await page.setContent('<div id="v" style="width:1100px"></div>');
  await page.addScriptTag({ path: path.join(ROOT, 'static', 'vendor', 'chart.umd.min.js') });
  await page.evaluate(({ months, titles, rows, refused }) => {
    window.toasts = [];
    window.toast = m => window.toasts.push(String(m));
    window.calls = [];
    // 스텁 서버 — 사전 확인은 맨 위 단계만 "누를 값 있음"(WITH 조회는 없음). s1 은 월로 바로, s3 은 컬럼을 고르게, s5 는 거절
    // The stub server: the probe says "drillable" on the top level only (never for WITH). s1 goes to months, s3 asks for a column, s5 declines
    window.fetch = async (url, init) => {
      const body = JSON.parse(init.body);
      window.calls.push(Object.assign({ url }, body));
      const reply = d => new Response(JSON.stringify(d), { status: 200, headers: { 'content-type': 'application/json' } });
      if (body.probe) return reply({ status: 'probe', drillable: body.path.length === 0 && !/^WITH/.test(body.sql) });
      if (/t_refuse/.test(body.sql)) return reply({ status: 'none', reason: refused, scope: 'chart' });
      if (/t_rows/.test(body.sql)) return reply({ status: 'ok', next: 'branch', source: rows, candidates: [] });
      if (/hr_employees/.test(body.sql) && !body.next) return reply({ status: 'choose', candidates: [{ column: 'title', period: false, count: 2 }, { column: 'status', period: false, count: 2 }] });
      if (/hr_employees/.test(body.sql)) return reply({ status: 'ok', next: body.next, source: titles, candidates: [] });
      return reply({ status: 'ok', next: 'month', source: months, candidates: [] });
    };
  }, { months: MONTHS, titles: TITLES, rows: ROWS, refused: REFUSED });
  await page.addScriptTag({ path: path.join(ROOT, 'static', 'report_dash.js') });
  await page.evaluate(data => { window.AI365_reportDash.viewer.mount(document.getElementById('v'), data); }, DATA);
  await page.waitForFunction(() => [...document.querySelectorAll('canvas[data-rd-canvas]')].filter(c => window.Chart.getChart(c)).length === 12);
  await page.waitForTimeout(800);   // 그리기 애니메이션 · 사전 확인 응답 / the draw animation and the probe answers
  return page;
}
const drills = page => page.evaluate(() => window.calls.filter(c => !c.probe));
// 막대 가운데 · 점의 좌표(화면 기준) / the viewport coordinates of a bar's middle or a point
async function mark(page, cid, i, dy) {
  await page.evaluate(cid => document.querySelector('[data-rd-card="' + cid + '"]').scrollIntoView({ block: 'center' }), cid);
  return page.evaluate(({ cid, i, dy }) => {
    const cv = document.querySelector('canvas[data-rd-canvas="' + cid + '"]'), ch = window.Chart.getChart(cv), r = cv.getBoundingClientRect();
    const p = ch.getDatasetMeta(0).data[i].getProps(['x', 'y', 'base'], true);
    return { x: r.left + p.x, y: r.top + (ch.config.type === 'bar' ? (p.y + p.base) / 2 : p.y) + (dy || 0) };
  }, { cid, i, dy });
}
async function cursorAt(page, cid, i) {
  const m = await mark(page, cid, i);
  await page.mouse.move(m.x - 30, m.y - 30);
  await page.mouse.move(m.x, m.y);
  await page.waitForTimeout(150);
  return page.evaluate(cid => document.querySelector('canvas[data-rd-canvas="' + cid + '"]').style.cursor, cid);
}
async function clickMark(page, cid, i, dy) {
  const m = await mark(page, cid, i, dy);
  await page.mouse.click(m.x, m.y);
}
async function view(page, cid) {
  return page.evaluate(cid => {
    const cv = document.querySelector('canvas[data-rd-canvas="' + cid + '"]'), ch = cv && window.Chart.getChart(cv);
    const ins = document.querySelector('[data-rd-ins="' + cid + '"]');
    return { crumbs: [...document.querySelectorAll('[data-rd-crumbs="' + cid + '"] .ai365-rd-crumb, [data-rd-crumbs="' + cid + '"] .lv')].map(b => b.textContent.replace(/\s+/g, ' ').trim()),
      type: ch ? ch.config.type : null, labels: ch ? ch.data.labels.slice() : null, insightHidden: ins ? ins.hidden : null,
      menu: [...document.querySelectorAll('[data-rd-dpick]')].map(b => b.dataset.rdDpick), veil: !!document.querySelector('[data-rd-dveil]') };
  }, cid);
}
const drilledTo = (page, cid, col) => page.waitForFunction(({ cid, col }) => {
  const lv = document.querySelector('[data-rd-crumbs="' + cid + '"] .lv'), cv = document.querySelector('canvas[data-rd-canvas="' + cid + '"]');
  return lv && lv.textContent === col && cv && window.Chart.getChart(cv);
}, { cid, col });

test('an aggregated bar goes one level down through the server, and the leaf level drops the zoom cursor', async t => {
  const page = await fixture(t);
  // SQL 이 있는 차트만 미리 확인한다(c2 는 옛 저장분) / only charts with SQL are probed (c2 is a legacy save)
  const probes = await page.evaluate(() => window.calls.filter(c => c.probe).map(c => c.x + ':' + c.path.length + ':' + c.url));
  assert.deepEqual(probes.sort(), ['branch:0:/api/reports/drill', 'branch:0:/api/reports/drill', 'branch:0:/api/reports/drill', 'dept:0:/api/reports/drill',
    'm:0:/api/reports/drill', 'm:0:/api/reports/drill', 'm:0:/api/reports/drill']);
  assert.equal(await cursorAt(page, 'c1', 1), 'zoom-in');
  await clickMark(page, 'c1', 1);
  await drilledTo(page, 'c1', 'month');
  const calls = await drills(page);
  assert.deepEqual(calls.map(c => [c.path, c.next, c.sql]), [[[{ col: 'branch', value: '울산' }], '', DATA.sources[0].sql]]);
  await page.waitForTimeout(400);   // 이 단계의 사전 확인 / this level's probe
  const v = await view(page, 'c1');
  assert.deepEqual(v, { crumbs: ['branch 전체', '울산', 'month'], type: 'line', labels: ['2025-01', '2025-02', '2025-03'], insightHidden: true, menu: [], veil: false });
  assert.equal(await cursorAt(page, 'c1', 0), '');   // 이 단계엔 누를 값이 없다(사전 확인) / nothing to click on this level (the probe said so)
  await clickMark(page, 'c1', 0);
  await page.waitForTimeout(300);
  assert.equal((await drills(page)).length, 1);      // 다시 묻지 않는다 / no further request
});

test('the table view shows the fetched level with its SQL, and the crumb goes back to the top', async t => {
  const page = await fixture(t);
  await clickMark(page, 'c1', 1);
  await drilledTo(page, 'c1', 'month');
  await page.click('[data-rd-view="c1:table"]');
  await page.click('[data-rd-sql="c1"]');
  const table = await page.evaluate(() => {
    const body = document.querySelector('[data-rd-body="c1"]');
    return { heads: [...body.querySelectorAll('.ai365-rd-tbl:not(.vals) th')].map(th => th.textContent), rows: body.querySelectorAll('.ai365-rd-tbl:not(.vals) tbody tr').length,
      sql: (body.querySelector('.ai365-rd-sqlpre') || {}).textContent };
  });
  assert.deepEqual(table, { heads: ['month', 'total_sales'], rows: 3, sql: MONTHS.sql });
  await page.click('[data-rd-view="c1:chart"]');
  await page.click('[data-rd-drillto="c1:0"]');
  await page.waitForFunction(() => { const cv = document.querySelector('canvas[data-rd-canvas="c1"]'); return cv && window.Chart.getChart(cv); });
  const v = await view(page, 'c1');
  assert.deepEqual([v.crumbs, v.type, v.labels, v.insightHidden], [[], 'bar', ['서울중앙', '울산', '대구'], false]);
  // 같은 막대를 다시 누르면 받아 둔 단계를 쓰지 않고 새로 가져온다(경로를 벗어난 단계는 버린다) / the same bar again fetches afresh
  await clickMark(page, 'c1', 1);
  await drilledTo(page, 'c1', 'month');
  assert.equal((await drills(page)).length, 2);
});

test('several candidate columns open a menu and the pick fetches that level', async t => {
  const page = await fixture(t);
  await clickMark(page, 'c3', 0);
  await page.waitForSelector('[data-rd-dpick]');
  assert.deepEqual((await view(page, 'c3')).menu, ['title', 'status']);
  await page.click('[data-rd-dpick="title"]');
  await drilledTo(page, 'c3', 'title');
  const calls = await drills(page);
  assert.deepEqual(calls.map(c => [c.path.map(p => p.col + '=' + p.value).join('/'), c.next]), [['dept=인사', ''], ['dept=인사', 'title']]);
  const v = await view(page, 'c3');
  assert.deepEqual([v.crumbs, v.type, v.labels, v.menu], [['dept 전체', '인사', 'title'], 'bar', ['대리', '과장'], []]);
});

test('a chart without SQL, or one the probe ruled out, shows no zoom cursor and sends nothing', async t => {
  const page = await fixture(t);
  assert.equal(await cursorAt(page, 'c2', 0), '');   // 옛 저장분 = 조회 SQL 없음 / a legacy save without SQL
  assert.equal(await cursorAt(page, 'c4', 1), '');   // WITH 조회 = 사전 확인이 아니라고 했다 / a WITH query: the probe said no
  await clickMark(page, 'c2', 0);
  await clickMark(page, 'c4', 1);
  await page.waitForTimeout(300);
  assert.deepEqual(await drills(page), []);
  assert.deepEqual([(await view(page, 'c2')).crumbs, (await view(page, 'c4')).crumbs], [[], []]);
});

test('a line point is picked a few pixels off, and a refusal for the whole chart becomes a notice and drops the cursor', async t => {
  const page = await fixture(t);
  assert.equal(await cursorAt(page, 'c5', 1), 'zoom-in');
  await clickMark(page, 'c5', 1, 40);                 // 점에서 40px 아래 = 빈 곳 / 40px below the point is empty space
  await page.waitForTimeout(200);
  assert.deepEqual(await drills(page), []);
  await clickMark(page, 'c5', 1, 10);                 // 10px 아래 = 그 점 / 10px below still picks the point
  await page.waitForFunction(() => window.toasts.length > 0);
  const calls = await drills(page);
  assert.deepEqual(calls.map(c => c.path), [[{ col: 'm', value: '2025-02' }]]);
  assert.deepEqual(await page.evaluate(() => window.toasts), [REFUSED]);
  assert.deepEqual((await view(page, 'c5')).crumbs, []);
  assert.equal(await cursorAt(page, 'c5', 0), '');   // 이 차트는 더 묻지 않는다 / this chart is not asked again
  await clickMark(page, 'c5', 0);
  await page.waitForTimeout(200);
  assert.equal((await drills(page)).length, 1);
});

test('a local level below a server level narrows the fetched data, not the top source', async t => {
  const page = await fixture(t);
  await clickMark(page, 'c6', 1);                     // 2025-02 → 서버 단계(지점) / a server level (branch)
  await drilledTo(page, 'c6', 'branch');
  let v = await view(page, 'c6');
  assert.deepEqual([v.crumbs, v.type, v.labels], [['m 전체', '2025-02', 'branch'], 'bar', ['대구', '울산']]);
  assert.equal(await cursorAt(page, 'c6', 1), 'zoom-in');   // 받아 온 데이터 안에서 권역이 울산을 나눈다 / region splits 울산 in the fetched rows
  await clickMark(page, 'c6', 1);
  await drilledTo(page, 'c6', 'region');
  assert.equal((await drills(page)).length, 1);      // 로컬 단계 = 요청 없음 / the local level sends nothing
  v = await view(page, 'c6');
  assert.deepEqual([v.crumbs, v.type, v.labels], [['m 전체', '2025-02', '울산', 'region'], 'bar', ['서', '동']]);
  await page.click('[data-rd-drillto="c6:1"]');       // 서버 단계로 돌아가기 / back to the server level
  await drilledTo(page, 'c6', 'branch');
  assert.deepEqual((await view(page, 'c6')).labels, ['대구', '울산']);
  assert.equal((await drills(page)).length, 1);
});

test('a server level does not re-apply chart filters, and a filter change while there goes back above it', async t => {
  const page = await fixture(t);
  // c7: 값 컬럼 필터(총 매출 150 이상)는 지점 합계의 조건 — 월별 값(50~80)에 다시 걸면 다 사라진다 / a branch-total condition, not for months
  assert.deepEqual((await view(page, 'c7')).labels, ['서울중앙', '울산']);
  await clickMark(page, 'c7', 1);
  await drilledTo(page, 'c7', 'month');
  let v = await view(page, 'c7');
  assert.deepEqual([v.crumbs, v.labels], [['branch 전체', '울산', 'month'], ['2025-01', '2025-02', '2025-03']]);
  assert.deepEqual((await drills(page)).map(c => c.filters), [[{ col: 'total_sales', values: ['300', '200'] }]]);
  // c8: 지점 필터로 서버 단계에 내려간 뒤 필터를 바꾸면 그 단계는 예전 필터로 가져온 것 — 맨 위로 / stale after a filter change: back to the top
  await clickMark(page, 'c8', 1);
  await drilledTo(page, 'c8', 'month');
  await page.click('[data-rdf-open="c8:f1"]');
  await page.click('[data-rdf-val="c8:f1"][value="서울중앙"]');
  await page.waitForFunction(() => !document.querySelector('[data-rd-crumbs="c8"] .lv'));
  await page.waitForFunction(() => { const cv = document.querySelector('canvas[data-rd-canvas="c8"]'); return cv && window.Chart.getChart(cv); });
  v = await view(page, 'c8');
  assert.deepEqual([v.crumbs, v.type, v.labels], [[], 'bar', ['울산']]);
});

test('local drill-down goes as deep as columns remain, and an agent path that is used up drops the cursor', async t => {
  const page = await fixture(t);
  for (const [level, col] of [[0, 'b'], [1, 'c'], [2, 'd'], [3, 'e']]) {   // 3단계 뒤에도 받아 둔 컬럼이 남으면 내려간다 / past three levels while columns remain
    assert.equal(await cursorAt(page, 'c9', 0), 'zoom-in', 'level ' + level);
    await clickMark(page, 'c9', 0);
    if (col !== 'e') {   // 남은 컬럼이 여럿이면 메뉴 / several columns left: the menu
      await page.waitForSelector('[data-rd-dpick="' + col + '"]');
      await page.click('[data-rd-dpick="' + col + '"]');
    }
    await drilledTo(page, 'c9', col);
  }
  assert.deepEqual((await view(page, 'c9')).crumbs, ['a 전체', 'a1', 'b1', 'c1', 'd1', 'e']);
  assert.equal(await cursorAt(page, 'c9', 0), '');    // 더 나눌 컬럼이 없다 / nothing left to split
  // c10: 에이전트가 정한 순서(b)를 다 쓰면 다른 컬럼이 남아도 돋보기는 없다(누르면 아무 일도 없던 결함) / a used-up agent path shows no zoom
  await clickMark(page, 'c10', 0);
  await drilledTo(page, 'c10', 'b');
  assert.equal(await cursorAt(page, 'c10', 0), '');
  assert.deepEqual(await drills(page), []);
});

test('an agent path that names a column the fetched data lacks fetches that column from the server, and ends there', async t => {
  const page = await fixture(t);
  assert.equal(await cursorAt(page, 'c11', 1), 'zoom-in');
  await clickMark(page, 'c11', 1);
  await drilledTo(page, 'c11', 'month');
  const calls = await drills(page);
  assert.deepEqual(calls.map(c => [c.path.map(p => p.col + '=' + p.value).join('/'), c.next]), [['branch=울산', 'month']]);   // 정한 컬럼을 지정해 묻는다 / asks for the planned column
  await page.waitForTimeout(300);
  assert.deepEqual((await view(page, 'c11')).labels, ['2025-01', '2025-02', '2025-03']);
  assert.equal(await cursorAt(page, 'c11', 0), '');   // 정해 둔 순서를 다 썼다 / the path is used up
  assert.equal(await page.evaluate(() => window.calls.filter(c => c.probe && c.x === 'month').length), 0);   // 정한 순서는 미리 묻지 않는다 / never probed
});

test('a donut drills from a click in its hole, in the direction of the slice', async t => {
  const page = await fixture(t);
  const at = await page.evaluate(() => {
    const cv = document.querySelector('canvas[data-rd-canvas="c12"]');
    cv.scrollIntoView({ block: 'center' });
    const ch = window.Chart.getChart(cv), r = cv.getBoundingClientRect(), a = ch.getDatasetMeta(0).data[0].getProps(['x', 'y', 'outerRadius', 'innerRadius'], true);
    return { x: r.left + a.x + a.outerRadius * 0.35, y: r.top + a.y, hole: a.innerRadius > a.outerRadius * 0.35 };   // 3시 방향 구멍 안 = 첫 조각(a1) / the hole at 3 o'clock: the first slice
  });
  assert.equal(at.hole, true);
  await page.mouse.move(at.x - 5, at.y - 5);
  await page.mouse.move(at.x, at.y);
  await page.waitForTimeout(150);
  assert.equal(await page.evaluate(() => document.querySelector('canvas[data-rd-canvas="c12"]').style.cursor), 'zoom-in');
  await page.mouse.click(at.x, at.y);
  await drilledTo(page, 'c12', 'b');
  assert.deepEqual((await view(page, 'c12')).crumbs, ['a 전체', 'a1', 'b']);
});
