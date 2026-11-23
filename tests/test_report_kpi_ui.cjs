// 실행: Playwright 가 NODE_PATH 에 있을 때 node --test tests/test_report_kpi_ui.cjs
// 리포트 에이전트 KPI 카드(2026-10-12) — 첫 화면에 카드가 없고, 제목 줄의 [+ KPI 카드] 버튼이 여는 대화 상자와 대화로 추가 · 편집(데이터에서 계산 | 직접 입력) ·
// 삭제 · 추천 채우기를 실제 패널(덮개 호스트)에서 마우스 · 키보드로 한다. /api/reports/dash* 는 fetch 스텁(norm_kpi · put_kpi · auto_kpis 의 규칙을 흉내 낸
// 작은 서버), Chart.js 는 저장소의 vendored 파일. 앱 서버 · DB · LLM 없음.
// Run with Playwright on NODE_PATH: node --test tests/test_report_kpi_ui.cjs
// Report-agent KPI cards (2026-10-12): no cards on the first screen; the title row's [+ KPI card] button opens a dialog, and the dialog
// and the conversation add, edit (computed | typed), remove and fill suggestions, driven in the real panel (overlay host) with mouse
// and keyboard. /api/reports/dash* is a fetch stub (a tiny server imitating the norm_kpi, put_kpi and auto_kpis rules) and Chart.js
// is the vendored file. No app server, DB or LLM.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const ROOT = path.join(__dirname, '..');
const STYLE = { palette: 'indigo', labels: false, smooth: false, fill: false, legend: 'none', rounded: true, grid: true };
const COLS = ['지점', '월', '매출', '달성률'];
const ROWS = [['강남점', '1월', 100, 80], ['광주점', '1월', 50, 70], ['강남점', '2월', 120, 90], ['광주점', '2월', 40, 60], ['강남점', '3월', 90, 85], ['광주점', '3월', 60, 75]];
const SOURCE = { id: 's1', name: 'Source 1', label: '', columns: COLS, rows: ROWS, types: { 지점: 'text', 월: 'text', 매출: 'number', 달성률: 'number' },
  periods: { 월: 'month' }, sql: 'SELECT 1', tables: ['sales'], fetched_at: '2026-10-12T10:00:00', origin: { kind: 'chat', note: '', chat_id: '', clone_of: '' } };
function chart(over) {
  return Object.assign({ type: 'bar', group: null, sort: { by: 'none', dir: 'desc' }, limit: null, stack: false, ref_lines: [], unit: '', filters: [], style: STYLE, size: 'half', insight: '' }, over);
}
const CHARTS = [
  chart({ id: 'c1', source: 's1', title: '월별 매출', x: '월', filters: [{ id: 'f1', col: '지점', label: '지점', selected: ['강남점'] }], y: [{ col: '매출', agg: 'sum', name: '매출', type: 'bar', axis: 0 }] }),
  chart({ id: 'c2', source: 's1', title: '지점별 매출', type: 'pie', x: '지점', y: [{ col: '매출', agg: 'sum', name: '매출', type: 'bar', axis: 0 }] }),
];
// 값 컬럼이 없는 데이터(번호 컬럼뿐) — 추천할 것이 없다 / data without a value column (only an order number): nothing to suggest
const ID_SOURCE = Object.assign({}, SOURCE, { columns: ['지점', '월', 'order_no'], rows: ROWS.map((r, i) => [r[0], r[1], i + 1]), types: { 지점: 'text', 월: 'text', order_no: 'number' } });
const ID_CHARTS = [chart({ id: 'c1', source: 's1', title: '지점별 주문', x: '지점', y: [{ col: 'order_no', agg: 'count', name: '주문', type: 'bar', axis: 0 }] })];
const manual = (id, label, value) => ({ id, source: '', col: '', agg: '', label, unit: '', link: '', delta: '', value, note: '' });

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

// 패널을 덮개로 연다 — opts.init: 처음부터 들어 있는 카드, opts.src/charts: 다른 데이터 / open the panel as an overlay; init = cards present from the start
async function fixture(t, opts) {
  opts = opts || {};
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  t.after(async () => { await page.close(); assert.deepEqual(errors, []); });
  await page.setContent('<div id="v"></div>');
  await page.addScriptTag({ path: path.join(ROOT, 'static', 'vendor', 'chart.umd.min.js') });
  await page.evaluate(({ src, charts, init }) => {
    window.toasts = []; window.toast = m => window.toasts.push(String(m)); window.calls = []; window.__delay = 0;
    window.AI365_KO2EN = {}; window.AI365_EN2KO = {}; window.__lang = 'ko';
    window.ai365CurrentLang = () => window.__lang;
    window.ai365T = ko => (window.__lang === 'en' && window.AI365_KO2EN[ko]) || ko;
    const AGG = { sum: '합계', avg: '평균', count: '건수', min: '최솟값', max: '최댓값', first: '첫 값' };
    // = app/report_dash 의 RATE_ONLY · _RATE_COL · _PERIOD_COL · _ID_COL / the server's column rules
    const RATE_ONLY = /(률|율|비중)\s*(\(?%\)?)?$|%|(^|[_\s])(rate|ratio|share|pct|percent)([_\s]|$)/i, RATE_COL = /률|율|비중|평균|단가|점수|percent|rate|ratio|avg|pct|%/i;
    const PERIOD_RE = /date|month|year|week|quarter|일자|날짜|연도|년도|월|분기|기간|주차/i, ID_RE = /(^|_)(id|no|code|seq)$|번호|코드|사번/i;
    const db = { state: { v: 2, title: '매출 대시보드', sources: [src], charts, kpis: init.slice() }, undo: 0, messages: [] };
    const nextId = () => { let n = 1; while (db.state.kpis.some(k => k.id === 'k' + n)) n++; return 'k' + n; };   // 서버처럼 빈 번호를 다시 쓴다 / like the server, the smallest free number
    const session = () => ({ id: 'd1', post_id: null, saved: false, kind: 'chat', origin: {}, state: JSON.parse(JSON.stringify(db.state)), messages: db.messages.slice(), updated: '',
      can_undo: db.undo > 0, dirty: db.undo > 0, saved_at: '', pending_auto: false });
    const json = (d, status) => new Response(JSON.stringify(d), { status: status || 200, headers: { 'content-type': 'application/json' } });
    // 서버 흉내 — norm_kpi · put_kpi · auto_kpis 의 규칙 중 화면이 기대는 것 / the norm_kpi, put_kpi and auto_kpis rules the screen relies on
    function norm(k, id) {
      const label = String(k.label || '').trim();
      if (k.value !== undefined && k.value !== null && k.value !== '') {
        const v = Number(String(k.value).replace(/,/g, ''));
        if (!isFinite(v)) throw new Error('KPI 카드에 보여 줄 숫자를 적어 주세요');
        if (!label) throw new Error('KPI 카드 이름을 적어 주세요');
        return { id, source: '', col: '', agg: '', label, unit: k.unit || '', link: '', delta: '', value: v, note: k.note || '' };
      }
      const s = db.state.sources.find(x => x.id === k.source);
      if (!s) throw new Error('KPI 카드가 가리키는 Source 가 없습니다');
      const col = k.col, numeric = col !== '*' && s.types[col] === 'number';
      let agg = ['sum', 'avg', 'count', 'min', 'max', 'first'].includes(k.agg) ? k.agg : ((RATE_COL.test(col) || RATE_ONLY.test(col)) ? 'avg' : 'sum');
      if (col === '*' || !numeric) agg = 'count';
      if (agg === 'sum' && col !== '*' && RATE_ONLY.test(col)) throw new Error("'" + col + "'는 비율이라 더하면 틀립니다. avg 로 요약하세요");
      return { id, source: k.source, col, agg, label: label || (col === '*' ? '건수' : col + ' ' + AGG[agg]), unit: k.unit || '', link: k.link || '', delta: k.delta === 'prev' ? 'prev' : '', note: k.note || '' };
    }
    function put(k, id) {
      const out = norm(k, id || nextId());
      if (db.state.kpis.some(x => x.id !== out.id && x.label === out.label)) throw new Error('같은 이름의 KPI 카드가 이미 있습니다: ' + out.label);
      return out;
    }
    function autoPicks() {   // = app/report_dash.auto_kpis + ops kpi_auto 의 중복 제외 / the server's suggestion rule, already-present columns skipped
      const s = db.state.sources[0], have = db.state.kpis.map(k => k.source + ':' + k.col);
      return s.columns.filter(c => s.types[c] === 'number' && !(s.periods || {})[c] && !PERIOD_RE.test(c) && !ID_RE.test(c)).slice(0, 3)
        .map((c, i) => ({ source: s.id, col: c, link: 'c1', delta: i === 0 ? 'prev' : '' })).filter(p => !have.includes(p.source + ':' + p.col));
    }
    window.fetch = async (url, init2) => {
      const body = init2 && init2.body ? JSON.parse(init2.body) : {};
      window.calls.push({ url, body });
      if (window.__delay) await new Promise(r => setTimeout(r, window.__delay));
      if (url === '/api/reports/dash') return json({ session: session() });
      if (/\/ops$/.test(url)) {
        try {
          for (const op of body.ops) {
            const kpis = db.state.kpis;
            if (op.op === 'kpi_add') { if (kpis.length >= 8) throw new Error('KPI 카드는 8개까지입니다'); kpis.push(put(op.kpi)); }
            else if (op.op === 'kpi_set') { const i = kpis.findIndex(k => k.id === op.id); if (!op.id || i < 0) throw new Error('해당 KPI 카드가 없습니다'); kpis[i] = put(op.kpi, op.id); }
            else if (op.op === 'kpi_remove') { if (!kpis.some(k => k.id === op.id)) throw new Error('해당 KPI 카드가 없습니다'); db.state.kpis = kpis.filter(k => k.id !== op.id); }
            else if (op.op === 'kpi_auto') { let n = 0; for (const p of autoPicks()) { try { kpis.push(put(p)); n++; } catch (e) { /* 건너뛴다 / skipped */ } } if (!n) throw new Error('추천할 값 컬럼이 없습니다'); }
            else throw new Error('알 수 없는 조작입니다');
          }
          db.undo += 1;
          return json({ session: session() });
        } catch (e) { return json({ detail: e.message }, 422); }
      }
      if (/\/turn$/.test(url)) {   // 대화 흉내 — 문장에 따라 카드를 넣고 · 이름을 바꾸고 · 지운다 / a conversation imitation: add, rename or remove by the sentence
        const m = body.message, kpis = db.state.kpis;
        let trace = [];
        if (/지워/.test(m)) db.state.kpis = [];
        else if (/이름/.test(m)) { if (kpis[0]) kpis[0] = Object.assign({}, kpis[0], { label: '매출 합계' }); }
        else if (/목표/.test(m)) kpis.push(put({ label: '연간 목표', value: 1500, unit: '원' }));
        else {
          kpis.push(put({ source: 's1', col: '매출', agg: 'sum', label: '총 매출', link: 'c1', delta: 'prev' }));
          trace = [{ agent: 'Visualize Agent', group: '요약 숫자', tool: 'add_kpi', label: '요약 숫자 추가', ok: true, detail: '', say: '' }];   // 2026-10-12 전 턴에 저장된 도구 이름 / a tool name stored by an older turn
        }
        db.undo += 1;
        db.messages.push({ role: 'user', text: m, focus: body.focus, ts: '' }, { role: 'agent', text: 'KPI 카드를 반영했습니다.', trace, ts: '' });
        return json({ session: session(), reply: 'KPI 카드를 반영했습니다.', trace });
      }
      return json({ detail: 'no ' + url }, 404);
    };
  }, { src: opts.src || SOURCE, charts: opts.charts || CHARTS, init: opts.init || [] });
  await page.addScriptTag({ path: path.join(ROOT, 'static', 'report_dash.js') });
  await page.evaluate(() => window.AI365_reportDash.open({ sources: [], host: 'overlay' }));
  await page.waitForSelector('#ai365RdRoot .ai365-rd-grid');
  const n = (opts.charts || CHARTS).length;
  await page.waitForFunction(n => [...document.querySelectorAll('canvas[data-rd-canvas]')].filter(c => window.Chart.getChart(c)).length === n, n);
  return page;
}
const tiles = page => page.$$eval('#ai365RdRoot [data-rd-kpis] .ai365-rd-kt', els => els.map(e => ({
  id: e.dataset.rdKpi, label: e.querySelector('.l').textContent, value: e.querySelector('.v').textContent,
  meta: e.querySelector('.m').textContent.replace(/\s+/g, ' ').trim(), note: (e.querySelector('.n') || { textContent: '' }).textContent, editing: e.classList.contains('edit') })));
const lastOps = page => page.evaluate(() => window.calls.filter(c => /\/ops$/.test(c.url)).slice(-1)[0].body.ops);
// 대화 상자 상태 — preview 는 미리보기 타일의 숫자 / the dialog's state; preview is the preview tile's number
const form = page => page.evaluate(() => {
  const f = document.querySelector('[data-rd-kpif]');
  if (!f) return null;
  const val = k => { const el = f.querySelector('[data-rdk="' + k + '"]'); return el ? (el.type === 'checkbox' ? el.checked : el.value) : undefined; };
  const pv = f.querySelector('[data-rd-kpipv] .ai365-rd-kt');
  return { head: f.querySelector('.hd > b').textContent, preview: pv ? pv.querySelector('.v').textContent : '', previewLabel: pv ? pv.querySelector('.l').textContent : '',
    previewMeta: pv ? pv.querySelector('.m').textContent.replace(/\s+/g, ' ').trim() : '', err: f.querySelector('[data-rd-kpierr]').textContent,
    mode: (f.querySelector('[data-rdk-mode][aria-pressed="true"]') || { dataset: {} }).dataset.rdkMode, placeholder: f.querySelector('[data-rdk="label"]').placeholder,
    label: val('label'), source: val('source'), col: val('col'), agg: val('agg'), value: val('value'), unit: val('unit'), link: val('link'), delta: val('delta'), note: val('note'),
    deltaDisabled: !!(f.querySelector('[data-rdk="delta"]') || {}).disabled, hasDelete: !!f.querySelector('[data-rd-kpirm]'), suggest: !!f.querySelector('[data-rd-kpiauto]'),
    applyDisabled: !!f.querySelector('[data-rd-kpiok]').disabled };
});
const has = (page, sel) => page.evaluate(sel => !!document.querySelector(sel), sel);
// 2026-10-13 디자인: [KPI 카드 추가]는 제목 줄 ⋯ 메뉴의 항목이다 — 메뉴를 열어 읽고, 다시 눌러 닫는다 / the add item lives in the title row's more menu: open it to read, click again to close
const addBtn = async page => {
  await page.click('.ai365-rd-top [data-rd="more"]');
  const b = await page.evaluate(() => { const b = document.querySelector('.ai365-rd-top [data-rd-smenu] [data-rd-kpiadd]'); return b ? { disabled: b.disabled, text: b.querySelector('span').textContent } : null; });
  await page.click('.ai365-rd-top [data-rd="more"]');
  return b;
};
const clickAdd = async page => { await page.click('.ai365-rd-top [data-rd="more"]'); await page.click('.ai365-rd-top [data-rd-smenu] [data-rd-kpiadd]'); };
const ask = async (page, text) => { await page.fill('#ai365RdInput', text); await page.press('#ai365RdInput', 'Enter'); };

test('the first screen has no KPI cards and no slot taken; the title-row button opens a dialog whose preview follows the linked chart', async (t) => {
  const page = await fixture(t);
  assert.deepEqual([await tiles(page), await addBtn(page), await has(page, '[data-rd-kpiauto]'), await has(page, '[data-rd-kpif]'), await has(page, '[data-rd-kpis] .ai365-rd-kt')],
    [[], { disabled: false, text: 'KPI 카드 추가' }, false, false, false]);
  await clickAdd(page);
  let f = await form(page);
  // 기본값: 첫 숫자 컬럼 · 합계 · 같은 데이터의 첫 차트에 연결 · 미리보기 타일은 그 차트의 필터(강남점)를 따르고 이름은 비우면 "매출 합계"
  // Defaults: first numeric column, sum, linked to the first chart; the preview tile follows its filter and an empty name reads "매출 합계"
  assert.deepEqual([f.head, f.mode, f.source, f.col, f.agg, f.link, f.delta, f.deltaDisabled, f.preview, f.previewLabel, f.placeholder, f.hasDelete, f.suggest],
    ['KPI 카드 추가', 'data', undefined, '매출', 'sum', 'c1', false, false, '310', '매출 합계', '매출 합계', false, true]);
  assert.equal(await page.evaluate(() => document.activeElement.dataset.rdk), 'label');
  await page.fill('[data-rdk="label"]', '총 매출');
  await page.fill('[data-rdk="unit"]', '원');
  assert.deepEqual([(await form(page)).preview, (await form(page)).previewLabel], ['310원', '총 매출']);
  await page.check('[data-rdk="delta"]');                                                      // 3월 90 vs 2월 120 (강남점) / March vs February
  f = await form(page);
  assert.deepEqual([f.preview, f.label, f.delta], ['310원', '총 매출', true]);
  assert.match(f.previewMeta, /▼ 25%.*3월 · 직전 기간 대비.*필터 적용 중/);
  await page.fill('[data-rdk="note"]', '강남점 기준');
  await page.click('[data-rd-kpiok]');
  await page.waitForSelector('[data-rd-kpis] .ai365-rd-kt[data-rd-kpi="k1"]');
  assert.deepEqual(await lastOps(page), [{ op: 'kpi_add', kpi: { label: '총 매출', source: 's1', col: '매출', agg: 'sum', unit: '원', link: 'c1', delta: 'prev', note: '강남점 기준' } }]);
  const [k1] = await tiles(page);
  assert.deepEqual([k1.id, k1.label, k1.value, k1.note, k1.editing], ['k1', '총 매출', '310원', '강남점 기준', false]);
  assert.match(k1.meta, /▼ 25%.*3월 · 직전 기간 대비.*필터 적용 중/);
  assert.deepEqual([await has(page, '[data-rd-kpif]'), (await tiles(page)).length, await addBtn(page)], [false, 1, { disabled: false, text: 'KPI 카드 추가' }]);   // 격자에는 카드만 / only cards in the grid
  assert.deepEqual(await page.evaluate(() => window.toasts), []);
});

test('clicking a card opens the dialog prefilled; the segmented switch to a typed number keeps the name, Enter saves kpi_set, and the pencil works from the keyboard', async (t) => {
  const page = await fixture(t);
  await clickAdd(page);
  await page.fill('[data-rdk="label"]', '총 매출');
  await page.click('[data-rd-kpiok]');
  await page.waitForSelector('[data-rd-kpis] .ai365-rd-kt[data-rd-kpi="k1"]');
  await page.click('[data-rd-kpis] .ai365-rd-kt[data-rd-kpi="k1"] .v');
  let f = await form(page);
  assert.deepEqual([f.head, f.label, f.mode, f.col, f.agg, f.link, f.hasDelete, f.suggest, (await tiles(page))[0].editing], ['KPI 카드 편집', '총 매출', 'data', '매출', 'sum', 'c1', true, false, true]);
  await page.fill('[data-rdk="note"]', '초안');
  await page.click('[data-rdk-mode="manual"]');
  f = await form(page);
  assert.deepEqual([f.mode, f.link, f.value, f.label, f.note, f.preview, await page.evaluate(() => document.activeElement.dataset.rdk)], ['manual', undefined, '', '총 매출', '초안', '–', 'value']);
  await page.fill('[data-rdk="value"]', '1,200');
  await page.fill('[data-rdk="unit"]', '원');
  await page.fill('[data-rdk="label"]', '목표 매출');
  assert.deepEqual([(await form(page)).preview, (await form(page)).previewMeta], ['1,200원', '직접 입력']);
  await page.press('[data-rdk="label"]', 'Enter');
  await page.waitForFunction(() => !document.querySelector('[data-rd-kpif]'));
  assert.deepEqual(await lastOps(page), [{ op: 'kpi_set', id: 'k1', kpi: { label: '목표 매출', value: '1,200', unit: '원', note: '초안' } }]);
  assert.deepEqual(await tiles(page), [{ id: 'k1', label: '목표 매출', value: '1,200원', meta: '직접 입력', note: '초안', editing: false }]);
  // 키보드: 연필 버튼에 포커스 → Enter / keyboard: focus the pencil, then Enter
  await page.focus('[data-rd-kpied="k1"]');
  await page.keyboard.press('Enter');
  assert.deepEqual([(await form(page)).head, (await form(page)).mode, (await form(page)).value], ['KPI 카드 편집', 'manual', '1200']);
});

test("a rate column defaults to average, the server's refusal keeps the dialog open with a toast, Escape and the backdrop close it, and the ✕ removes a card", async (t) => {
  const page = await fixture(t);
  await clickAdd(page);
  await page.selectOption('[data-rdk="col"]', '달성률');
  assert.deepEqual([(await form(page)).col, (await form(page)).agg, (await form(page)).preview, (await form(page)).placeholder], ['달성률', 'avg', '85', '달성률 평균']);   // 비율은 평균 / rates average
  await page.selectOption('[data-rdk="agg"]', 'sum');
  assert.equal((await form(page)).preview, '255');                                             // 강남점 80+90+85
  await page.click('[data-rd-kpiok]');
  await page.waitForFunction(() => window.toasts.length === 1);
  assert.match((await page.evaluate(() => window.toasts))[0], /비율/);
  assert.deepEqual([await has(page, '[data-rd-kpif]'), (await form(page)).applyDisabled], [true, false]);   // 대화 상자는 열린 채, 다시 누를 수 있다 / the dialog stays open and usable
  await page.selectOption('[data-rdk="agg"]', 'avg');
  await page.click('[data-rd-kpiok]');
  await page.waitForSelector('[data-rd-kpis] .ai365-rd-kt[data-rd-kpi="k1"]');
  assert.deepEqual((await tiles(page)).map(k => [k.label, k.value]), [['달성률 평균', '85']]);
  // 직접 입력에서 숫자가 아니면 대화 상자 안에서 막는다(서버 호출 없음) / a non-number typed value is stopped in the dialog, no server call
  await clickAdd(page);
  await page.click('[data-rdk-mode="manual"]');
  await page.fill('[data-rdk="label"]', '목표');
  await page.fill('[data-rdk="value"]', 'abc');
  const calls = await page.evaluate(() => window.calls.length);
  await page.click('[data-rd-kpiok]');
  assert.deepEqual([(await form(page)).err, await page.evaluate(() => window.calls.length), await page.evaluate(() => document.activeElement.dataset.rdk)], ['보여 줄 숫자를 적어 주세요.', calls, 'value']);
  await page.keyboard.press('Escape');
  assert.equal(await has(page, '[data-rd-kpif]'), false);
  await clickAdd(page);
  await page.mouse.click(40, 450);                                                             // 덮개 클릭 = 닫기 / a backdrop click closes
  assert.equal(await has(page, '[data-rd-kpif]'), false);
  await page.hover('[data-rd-kpis] .ai365-rd-kt[data-rd-kpi="k1"]');
  await page.click('[data-rd-kpirm="k1"]');
  await page.waitForFunction(() => !document.querySelector('[data-rd-kpis] .ai365-rd-kt'));
  assert.deepEqual([await lastOps(page), await addBtn(page)], [[{ op: 'kpi_remove', id: 'k1' }], { disabled: false, text: 'KPI 카드 추가' }]);
});

test('Fill suggestions in the dialog adds rule-based cards and closes it, the cap disables the button, and the read-only viewer shows cards without controls', async (t) => {
  const page = await fixture(t);
  await clickAdd(page);
  await page.click('[data-rd-kpiauto]');
  await page.waitForSelector('[data-rd-kpis] .ai365-rd-kt[data-rd-kpi="k2"]');
  assert.deepEqual([await lastOps(page), (await tiles(page)).map(k => [k.label, k.value]), await has(page, '[data-rd-kpif]')], [[{ op: 'kpi_auto' }], [['매출 합계', '310'], ['달성률 평균', '85']], false]);
  assert.match((await tiles(page))[0].meta, /▼ 25%/);
  await clickAdd(page);
  assert.equal((await form(page)).suggest, false);                                            // 추천할 컬럼이 더 없다 / nothing left to suggest
  await page.keyboard.press('Escape');
  // 상한(8장): 버튼이 잠긴다 / at the cap of 8 the button is disabled
  const full = await fixture(t, { init: Array.from({ length: 8 }, (_, i) => manual('k' + (i + 1), '카드 ' + (i + 1), i)) });
  assert.deepEqual([(await tiles(full)).length, await addBtn(full)], [8, { disabled: true, text: 'KPI 카드 추가' }]);
  // 읽기 전용 뷰어 / the read-only viewer
  await full.evaluate(({ src, charts }) => {
    const el = document.createElement('div'); el.id = 'viewer'; document.body.appendChild(el);
    window.AI365_reportDash.viewer.mount(el, { title: '보기', sources: [src], charts, kpis: [
      { id: 'k1', source: 's1', col: '매출', agg: 'sum', label: '총 매출', unit: '원', link: 'c1', delta: 'prev', note: '강남점' },
      { id: 'k2', source: '', col: '', agg: '', label: '목표', unit: '원', link: '', delta: '', value: 1200, note: '' }] });
  }, { src: SOURCE, charts: CHARTS });
  const view = await full.$$eval('#viewer .ai365-rd-kt', els => els.map(e => [e.querySelector('.l').textContent, e.querySelector('.v').textContent, !!e.querySelector('.acts'), e.classList.contains('can')]));
  assert.deepEqual(view, [['총 매출', '310원', false, false], ['목표', '1,200원', false, false]]);
  assert.equal(await full.evaluate(() => document.querySelectorAll('#viewer [data-rd-kpiadd], #viewer [data-rd-kdlg]').length), 0);
});

test('without a value column the dialog offers no suggestions but still works', async (t) => {
  const page = await fixture(t, { src: ID_SOURCE, charts: ID_CHARTS });
  assert.deepEqual([await addBtn(page), await has(page, '[data-rd-kpiauto]')], [{ disabled: false, text: 'KPI 카드 추가' }, false]);
  await clickAdd(page);
  assert.deepEqual([(await form(page)).mode, (await form(page)).link, (await form(page)).suggest], ['data', 'c1', false]);
});

test('a second Apply while the request runs is ignored, and Tab stays inside the dialog', async (t) => {
  const page = await fixture(t, { init: [manual('k1', '카드 1', 1), manual('k2', '카드 2', 2)] });
  await page.evaluate(() => { window.__delay = 350; });
  await clickAdd(page);
  await page.fill('[data-rdk="label"]', '총 매출');
  await page.press('[data-rdk="label"]', 'Enter');                                             // Enter 두 번 = 이중 제출 시도 / Enter twice: a double-submit attempt
  await page.press('[data-rdk="label"]', 'Enter');
  assert.equal((await form(page)).applyDisabled, true);                                        // 요청 중엔 잠긴다 / locked while the request runs
  await page.waitForSelector('[data-rd-kpis] .ai365-rd-kt[data-rd-kpi="k3"]');
  await page.waitForTimeout(450);
  assert.deepEqual([await page.evaluate(() => window.calls.filter(c => /\/ops$/.test(c.url)).length), (await tiles(page)).map(k => k.label), await has(page, '[data-rd-kpif]')], [1, ['카드 1', '카드 2', '총 매출'], false]);
  await page.evaluate(() => { window.__delay = 0; });
  await page.click('[data-rd-kpis] .ai365-rd-kt[data-rd-kpi="k1"] .v');
  for (let i = 0; i < 14; i++) await page.keyboard.press('Tab');                              // 포커스는 대화 상자 안에서만 돈다 / focus cycles inside the dialog
  assert.equal(await page.evaluate(() => !!document.activeElement.closest('[data-rd-kpif]')), true);
  await page.keyboard.press('Shift+Tab');
  assert.equal(await page.evaluate(() => !!document.activeElement.closest('[data-rd-kpif]')), true);
});

test('English labels come from the panel dictionary, and older traces keep their stored tool names translated', async (t) => {
  const page = await fixture(t);
  // 목업의 언어 토글처럼 — 덮개가 화면을 덮고 있어 스크립트로 누른다 / like the mockup's language toggle; the overlay covers the page, so it is clicked by script
  await page.evaluate(() => { window.__lang = 'en'; document.body.insertAdjacentHTML('beforeend', '<button id="ai365-lang-toggle"></button>'); document.getElementById('ai365-lang-toggle').click(); });
  await page.waitForFunction(() => (document.querySelector('.ai365-rd-hd .ai365-rd-hbtn span') || {}).textContent === 'My library');
  await clickAdd(page);
  assert.deepEqual(await page.$$eval('[data-rd-kpif] .row > span:first-child', els => els.map(e => e.textContent)), ['Name', 'Value', 'Column', 'Linked chart', 'Note']);
  assert.deepEqual(await page.$$eval('[data-rdk-mode]', els => els.map(e => e.textContent)), ['Computed from data', 'Typed number']);
  assert.deepEqual(await page.$$eval('[data-rdk="agg"] option', els => els.map(e => e.textContent)), ['Sum', 'Average', 'Count', 'Minimum', 'Maximum', 'First value']);
  assert.deepEqual([(await form(page)).head, await page.$eval('[data-rd-kpif] .pv .cap', e => e.textContent), await page.$eval('[data-rd-kpiok]', e => e.textContent), await page.$eval('[data-rd-kpiauto] span', e => e.textContent)],
    ['Add KPI card', 'Preview', 'Apply', 'Fill suggestions']);
  await page.fill('[data-rdk="label"]', 'Total sales');
  await page.click('[data-rd-kpiok]');
  await page.waitForSelector('[data-rd-kpis] .ai365-rd-kt[data-rd-kpi="k1"]');
  assert.match((await tiles(page))[0].meta, /Filtered/);
  await page.click('[data-rd-kpis] .ai365-rd-kt[data-rd-kpi="k1"] .v');
  assert.deepEqual([(await form(page)).head, await page.$eval('[data-rd-kpif] [data-rd-kpirm]', e => e.textContent)], ['Edit KPI card', 'Delete']);
  await page.keyboard.press('Escape');
  await ask(page, 'Show total sales as a KPI card');                                            // 옛 이름('요약 숫자 추가')으로 저장된 실행 내역 / a trace stored under the old name
  await page.waitForSelector('[data-rd-kpis] .ai365-rd-kt[data-rd-kpi="k2"]');
  assert.match(await page.$eval('#ai365RdChat', e => e.textContent), /Add summary number/);
});

test('the conversation creates, renames and removes cards, and the row repaints from the turn result', async (t) => {
  // 2026-10-12 사용자 지시 "KPI 카드는 채팅으로 생성하고 조정" — 패널의 입력창으로 보낸 턴이 카드 줄을 바꾼다 / a turn sent from the panel's input changes the card row
  const page = await fixture(t);
  await ask(page, 'KPI 카드로 총 매출 보여줘');
  await page.waitForSelector('[data-rd-kpis] .ai365-rd-kt[data-rd-kpi="k1"]');
  assert.deepEqual((await tiles(page)).map(k => [k.label, k.value]), [['총 매출', '310']]);
  assert.match((await tiles(page))[0].meta, /▼ 25%.*필터 적용 중/);
  assert.equal(await page.$eval('#ai365RdChat .ai365-rd-msg.agent:last-of-type .tx', e => e.textContent), 'KPI 카드를 반영했습니다.');
  assert.equal(await page.$eval('.ai365-rd-main', e => e.classList.contains('chat-open')), true);   // 보내면 대화 서랍이 열린다 / sending opens the drawer
  const turn = await page.evaluate(() => window.calls.filter(c => /\/turn$/.test(c.url)).slice(-1)[0].body);
  assert.deepEqual([turn.message, turn.focus, turn.view], ['KPI 카드로 총 매출 보여줘', '', '']);
  await ask(page, '연간 목표 1,500원 카드 넣어줘');
  await page.waitForSelector('[data-rd-kpis] .ai365-rd-kt[data-rd-kpi="k2"]');
  await ask(page, '첫 번째 카드 이름을 매출 합계로 바꿔줘');
  await page.waitForFunction(() => (document.querySelector('[data-rd-kpis] .ai365-rd-kt[data-rd-kpi="k1"] .l') || {}).textContent === '매출 합계');
  const after = await tiles(page);
  assert.deepEqual(after.map(k => [k.id, k.label, k.value]), [['k1', '매출 합계', '310'], ['k2', '연간 목표', '1,500원']]);
  assert.match(after[0].meta, /▼ 25%.*3월 · 직전 기간 대비.*필터 적용 중/);
  assert.equal(after[1].meta, '직접 입력');
  assert.deepEqual(await addBtn(page), { disabled: false, text: 'KPI 카드 추가' });                 // 버튼도 그대로 쓸 수 있다 / the button stays available too
  await ask(page, 'KPI 카드 전부 지워줘');
  await page.waitForFunction(() => !document.querySelector('[data-rd-kpis] .ai365-rd-kt'));
  assert.deepEqual([await has(page, '[data-rd-kpif]'), await addBtn(page), await has(page, '[data-rd-kpis] *')], [false, { disabled: false, text: 'KPI 카드 추가' }, false]);
  assert.deepEqual(await page.evaluate(() => window.toasts), []);
});
