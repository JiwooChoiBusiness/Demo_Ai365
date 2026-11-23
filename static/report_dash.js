/* =====================================================================
   리포트 에이전트 대시보드(2026-09-18) — 채팅 옆 패널(실제 제품 구조: 머리줄·차트 카드·Chart|Table·맨 아래 입력창)에
   대시보드 개념을 얹는다: 모든 차트 카드가 한 화면(Source 탭 분기는 2026-09-22 사용자 지시로 폐지 — 대상은 카드를 눌러 지정하고, 원본
   테이블·조회 시각·조회 SQL 은 카드의 Table 보기에 둔다), 필터는 차트(BI)마다 카드 안에, 이 대시보드 전용 대화(도구 호출 표시·되돌리기), 내 보관소에서 다시 열기.
   데이터(Source)와 차트 설정이 분리돼 있어 숫자는 여기서 계산한다(ai365RdCompute = app/report_dash.py compute 와 같은 규칙) —
   필터는 LLM 없이 바로 반응한다. 차트는 Chart.js(static/vendor, 처음 열 때만 불러온다). 기준선·값 라벨은 작은 인라인 플러그인.
   게시판 상세는 viewer.mount 로 같은 카드를 읽기 전용으로 그린다.
   Report-agent dashboards (2026-09-18) — the chat-side panel keeps the real product's structure (header, chart cards,
   Chart|Table, input at the bottom) and gains the dashboard concepts: every chart card on one screen (the Source-tab branching
   was retired on 2026-09-22 at the user's request — a target is chosen by clicking its card, and the source table, fetch time and
   query SQL live under the card's Table view), per-chart filters inside the cards, a dashboard-only conversation (tool calls,
   undo), and reopening from my library.
   Data (sources) and chart specs are separate, so numbers are computed here (ai365RdCompute mirrors compute in
   app/report_dash.py) and filters react without the LLM. Charts use Chart.js (static/vendor, loaded on first open);
   reference lines and value labels are small inline plugins. The board detail mounts the same cards read-only.
===================================================================== */
(function () {
  'use strict';

  /* ── 순수 함수(노드 테스트가 그대로 부른다) / pure functions (called as is by the node tests) ── */
  const MAX_X_ITEMS = 40, MAX_PIE_SLICES = 8, MAX_GROUP_SERIES = 8, OTHERS = '기타';
  const PALETTES = {
    indigo: ['#5B5BD6', '#22B8CF', '#F59F00', '#12B886', '#E64980', '#868E96'],
    ocean: ['#1C7ED6', '#15AABF', '#4DABF7', '#0B7285', '#74C0FC', '#3BC9DB'],
    sunset: ['#F76707', '#E64980', '#FAB005', '#D6336C', '#FF922B', '#F783AC'],
    forest: ['#2F9E44', '#66A80F', '#099268', '#94D82D', '#37B24D', '#20C997'],
    mono: ['#343A40', '#868E96', '#ADB5BD', '#495057', '#CED4DA', '#212529'],
    pastel: ['#91A7FF', '#66D9E8', '#FFD43B', '#8CE99A', '#FAA2C1', '#B197FC'],
  };

  function rdNum(v) {
    if (v === null || v === undefined || typeof v === 'boolean') return null;
    if (typeof v === 'number') return isFinite(v) ? v : null;
    if (typeof v !== 'string') return null;
    let s = v.replace(/,/g, '').trim();
    if (s.slice(-1) === '%') s = s.slice(0, -1).trim();
    if (!s) return null;
    const f = Number(s);
    return isFinite(f) ? f : null;
  }
  function rdKey(v) { return (v === null || v === undefined) ? '' : String(v); }
  function rdRound(v) { return Math.round(v * 1e6) / 1e6; }

  /* 범위 필터 → 값 하나를 통과시킬지 정하는 함수(거를 것이 없으면 null) — 서버 _range_test 와 같은 규칙. 기간 컬럼은 부터~까지 또는
     최근 N개 기간(오늘이 아니라 데이터의 마지막 기간 기준), 숫자 컬럼은 이상·이하 / a range filter → a predicate, same rules as the server */
  function rdRangeTest(source, col, rng) {
    const ci = source.columns.indexOf(col), pkind = (source.periods || {})[col];
    const cmp = function (a, b) { return (a[0] - b[0]) || (a[1] - b[1]); };
    if (pkind) {
      let lo = null, hi = null;
      if (rng.last) {
        const seen = {}, keys = [];
        source.rows.forEach(function (r) { const k = rdPeriodKey(r[ci], pkind); if (k && !seen[k[0] + ':' + k[1]]) { seen[k[0] + ':' + k[1]] = 1; keys.push(k); } });
        if (!keys.length) return null;
        keys.sort(cmp);
        lo = keys[keys.length - Math.min(rng.last, keys.length)];
      } else {
        lo = rdPeriodKey(rng.from, pkind); hi = rdPeriodKey(rng.to, pkind);
        if (!lo && !hi) return null;
      }
      return function (v) { const k = rdPeriodKey(v, pkind); return !!k && (!lo || cmp(k, lo) >= 0) && (!hi || cmp(k, hi) <= 0); };
    }
    const lo = (rng.min === null || rng.min === undefined) ? null : rng.min, hi = (rng.max === null || rng.max === undefined) ? null : rng.max;
    if (lo === null && hi === null) return null;
    return function (v) { const n = rdNum(v); return n !== null && (lo === null || n >= lo) && (hi === null || n <= hi); };
  }

  function rdFilteredRows(source, filters) {
    const active = [];
    (filters || []).forEach(function (f) {
      const ci = source.columns.indexOf(f.col);
      if (ci < 0) return;
      if (f.range) { const test = rdRangeTest(source, f.col, f.range); if (test) active.push([ci, test]); }
      else if ((f.selected || []).length) active.push([ci, function (v) { return f.selected.indexOf(rdKey(v)) >= 0; }]);
    });
    if (!active.length) return source.rows;
    return source.rows.filter(function (r) { return active.every(function (a) { return a[1](r[a[0]]); }); });
  }

  function rdAgg(rows, ci, how) {
    if (how === 'count') return ci === null ? rows.length : rows.filter(function (r) { return r[ci] !== null && r[ci] !== undefined && r[ci] !== ''; }).length;
    const vals = ci === null ? [] : rows.map(function (r) { return rdNum(r[ci]); }).filter(function (v) { return v !== null; });
    if (!vals.length) return 0;
    if (how === 'avg') return rdRound(vals.reduce(function (a, b) { return a + b; }, 0) / vals.length);
    if (how === 'min') return rdRound(Math.min.apply(null, vals));
    if (how === 'max') return rdRound(Math.max.apply(null, vals));
    if (how === 'first') return rdRound(vals[0]);
    return rdRound(vals.reduce(function (a, b) { return a + b; }, 0));
  }

  function rdStat(stat, vals) {
    if (stat === 'min') return Math.min.apply(null, vals);
    if (stat === 'max') return Math.max.apply(null, vals);
    if (stat === 'median') {
      const s = vals.slice().sort(function (a, b) { return a - b; }), m = Math.floor(s.length / 2);
      return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
    }
    return vals.reduce(function (a, b) { return a + b; }, 0) / vals.length;
  }

  /* 기간 라벨 읽기(2026-09-21) — app/report_dash.py parse_period 와 같은 규칙. 숫자뿐인 값은 컬럼 종류(hint)로만 읽는다.
     반환 [종류, 연, 순번] 또는 null / period labels, same rules as parse_period on the server: [kind, year, ordinal] or null */
  const P_DATE = /^(\d{4})[-./](\d{1,2})[-./](\d{1,2})(?:[T ].*)?$/i, P_DATE_KO = /^(\d{4})[ \t]*년[ \t]*(\d{1,2})[ \t]*월[ \t]*(\d{1,2})[ \t]*일$/,
    P_YM = /^(\d{4})[-./](\d{1,2})$/, P_YM_KO = /^(\d{4})[ \t]*년[ \t]*(\d{1,2})[ \t]*월$/,
    P_Q = /^(?:(\d{4})[ \t]*년?[ \t]*[-/]?[ \t]*)?(?:Q([1-4])|([1-4])[ \t]*분기|([1-4])Q)$/i,
    P_W = /^(?:(\d{4})[ \t]*년?[ \t]*[-/]?[ \t]*)?(?:W(\d{1,2})|(\d{1,2})[ \t]*주차?)$/i,
    P_M = /^(\d{1,2})[ \t]*월$/, P_Y = /^(\d{4})[ \t]*년$/, P_DIGITS = /^\d+$/;
  function rdParsePeriod(label, hint) {
    const s = rdKey(label).trim();
    if (!s) return null;
    let m = P_DATE.exec(s) || P_DATE_KO.exec(s);
    if (m) { const mo = +m[2], d = +m[3]; return (mo >= 1 && mo <= 12 && d >= 1 && d <= 31) ? ['date', +m[1], mo * 100 + d] : null; }
    m = P_YM.exec(s) || P_YM_KO.exec(s);
    if (m) return (+m[2] >= 1 && +m[2] <= 12) ? ['month', +m[1], +m[2]] : null;
    m = P_Q.exec(s);
    if (m) return ['quarter', +(m[1] || 0), +(m[2] || m[3] || m[4])];
    m = P_W.exec(s);
    if (m) { const w = +(m[2] || m[3]); return (w >= 1 && w <= 53) ? ['week', +(m[1] || 0), w] : null; }
    m = P_M.exec(s);
    if (m) return (+m[1] >= 1 && +m[1] <= 12) ? ['month', 0, +m[1]] : null;
    m = P_Y.exec(s);
    if (m) return ['year', +m[1], 0];
    if (P_DIGITS.test(s) && s.length <= 8) {
      const n = parseInt(s, 10);
      if (hint === 'year' && s.length === 4 && n >= 1900 && n <= 2100) return ['year', n, 0];
      if (hint === 'month' && s.length <= 2 && n >= 1 && n <= 12) return ['month', 0, n];
      if (hint === 'month' && s.length === 6 && n % 100 >= 1 && n % 100 <= 12) return ['month', Math.floor(n / 100), n % 100];
      if (hint === 'quarter' && s.length === 1 && n >= 1 && n <= 4) return ['quarter', 0, n];
      if (hint === 'week' && s.length <= 2 && n >= 1 && n <= 53) return ['week', 0, n];
      if (hint === 'date' && s.length === 8 && Math.floor(n / 100) % 100 >= 1 && Math.floor(n / 100) % 100 <= 12 && n % 100 >= 1 && n % 100 <= 31) return ['date', Math.floor(n / 10000), n % 10000];
    }
    return null;
  }
  function rdPeriodKey(label, kind) {
    const p = rdParsePeriod(label, kind);
    return p && p[0] === kind ? [p[1], p[2]] : null;
  }

  /* 계산 값(2026-09-21) — 서버 _calc_point · _calc_seq 와 같은 규칙. 순서와 무관한 계산은 정렬 전에, 순서가 뜻인 계산은 정렬 뒤·자르기 전에.
     Calculated values, same rules as the server: order-independent calcs before sorting, order-dependent ones after sorting and before the limit. */
  const ORDER_CALCS = ['pct_prev', 'diff_prev', 'moving_avg', 'yoy', 'cumsum', 'cum_share'], PCT_CALCS = ['share', 'cum_share', 'pct_prev', 'yoy', 'ratio_pct'];
  function rdSum(a) { return a.reduce(function (x, y) { return x + y; }, 0); }
  function rdCalcPoint(y, a, b) {
    const calc = y.calc;
    if (calc === 'share') { const total = rdSum(a); return a.map(function (v) { return total ? rdRound(v / total * 100) : null; }); }
    if (calc === 'rank') return a.map(function (v) { return 1 + a.filter(function (o) { return o > v; }).length; });
    if ((calc === 'ratio' || calc === 'ratio_pct') && b) return a.map(function (v, i) { return b[i] ? rdRound(v / b[i] * (calc === 'ratio_pct' ? 100 : 1)) : null; });
    if (calc === 'diff' && b) return a.map(function (v, i) { return rdRound(v - b[i]); });
    return a;
  }
  function rdCalcSeq(y, vals, labels, pkind) {
    const calc = y.calc, isNull = function (v) { return v === null || v === undefined; };
    if (calc === 'cumsum' || calc === 'cum_share') {
      const total = rdSum(vals.map(function (v) { return v || 0; }));
      let run = 0;
      return vals.map(function (v) { run += v || 0; return calc === 'cumsum' ? rdRound(run) : (total ? rdRound(run / total * 100) : null); });
    }
    if (calc === 'pct_prev' || calc === 'diff_prev') {
      return vals.map(function (v, i) {
        const prev = i ? vals[i - 1] : null;
        if (!i || isNull(prev) || isNull(v) || (calc === 'pct_prev' && !prev)) return null;
        return calc === 'diff_prev' ? rdRound(v - prev) : rdRound((v - prev) / Math.abs(prev) * 100);
      });
    }
    if (calc === 'moving_avg') {
      const w = y.window || 3;
      return vals.map(function (_, i) {
        const win = vals.slice(i - w + 1, i + 1);
        return (i >= w - 1 && win.every(function (v) { return !isNull(v); })) ? rdRound(rdSum(win) / w) : null;
      });
    }
    if (calc === 'yoy') {
      const keys = labels.map(function (lb) { return pkind ? rdPeriodKey(lb, pkind) : null; }), at = {};
      keys.forEach(function (k, i) { if (k) at[k[0] + ':' + k[1]] = vals[i]; });
      return vals.map(function (v, i) {
        const k = keys[i], prev = (k && k[0] > 0) ? at[(k[0] - 1) + ':' + k[1]] : null;
        return (prev && !isNull(v)) ? rdRound((v - prev) / Math.abs(prev) * 100) : null;
      });
    }
    return vals;
  }

  /* 조건부 강조(2026-09-21) — 서버 _marks 와 같은 규칙: 규칙마다 맞는 x 위치, 여러 규칙에 걸리면 앞 규칙이 이긴다 / highlight rules → hit positions; the first matching rule wins */
  function rdMarks(chart, series, refs, labels) {
    const out = [], taken = {};
    (chart.highlights || []).forEach(function (h) {
      let si = 0;
      for (let i = 0; i < series.length; i++) { if (series[i].name === h.series) { si = i; break; } }
      const vals = series.length ? series[si].values : [], idx = [];
      vals.forEach(function (v, i) { if (v !== null && v !== undefined) idx.push(i); });
      let hits = [];
      if (h.kind === 'value' || h.kind === 'stat' || h.kind === 'ref') {
        let th = h.value;
        if (h.kind === 'stat' && idx.length) th = rdRound(rdStat(h.stat === 'median' ? 'median' : 'avg', idx.map(function (i) { return vals[i]; })));
        else if (h.kind === 'ref') { const r = (refs || []).filter(function (x) { return x.id === h.ref; })[0]; th = r ? r.value : null; }
        if (th !== null && th !== undefined) {
          const op = h.op || 'lt';
          hits = idx.filter(function (i) { const v = vals[i]; return op === 'lt' ? v < th : op === 'lte' ? v <= th : op === 'gt' ? v > th : v >= th; });
        }
      } else if (h.kind === 'top') hits = idx.slice().sort(function (a, b) { return (vals[b] - vals[a]) || (a - b); }).slice(0, h.n || 3).sort(function (a, b) { return a - b; });
      else if (h.kind === 'bottom') hits = idx.slice().sort(function (a, b) { return (vals[a] - vals[b]) || (a - b); }).slice(0, h.n || 3).sort(function (a, b) { return a - b; });
      else if (h.kind === 'items') labels.forEach(function (lb, i) { if ((h.items || []).indexOf(lb) >= 0) hits.push(i); });
      hits = hits.filter(function (i) { return !taken[i]; });
      hits.forEach(function (i) { taken[i] = 1; });
      out.push({ id: h.id, label: h.label, color: h.color || '', dim: !!h.dim, series: si, hits: hits });
    });
    return out;
  }

  /* 드릴다운 화면(2026-09-21) — 막대를 눌러 내려간 자리의 차트 설정. path = [{col, value, next}]: col=value 로 좁히고 x 는 마지막 next.
     화면 상태일 뿐 저장하지 않는다. 기준선·강조는 맨 위 단계의 것이라 걷고, 순서가 뜻인 계산은 다음 축이 기간일 때만 남긴다.
     The drilled view: the chart narrowed by col=value pairs with x moved to the last `next`. A view state, never stored; reference
     lines and highlights belong to the top level, and order-dependent calcs stay only when the next axis is a period. */
  function rdDrillChart(chart, source, path) {
    if (!path || !path.length) return chart;
    const next = path[path.length - 1].next, pk = (source.periods || {})[next];
    const filters = (chart.filters || []).filter(function (f) { return !path.some(function (p) { return p.col === f.col; }); })
      .concat(path.map(function (p, i) { return { id: 'd' + i, col: p.col, label: p.col, selected: [p.value] }; }));
    let type = chart.type;
    if (pk && ['bar', 'hbar', 'pie', 'donut'].indexOf(type) >= 0) type = 'line';
    else if (!pk && (type === 'line' || type === 'area')) type = 'bar';
    const ys = chart.y.map(function (y) {
      const o = Object.assign({}, y);
      if (o.calc && ORDER_CALCS.indexOf(o.calc) >= 0 && !pk) {
        if (PCT_CALCS.indexOf(o.calc) >= 0) delete o.unit;
        delete o.calc; delete o.window; o.name = o.col === '*' ? '건수' : o.col;
      }
      if (type !== chart.type) { o.type = type === 'line' ? 'line' : 'bar'; if (type === 'hbar') o.axis = 0; }
      return o;
    });
    return Object.assign({}, chart, { x: next, y: ys, type: type, filters: filters, limit: null, ref_lines: [], highlights: [], notes: [],
      group: (chart.group && chart.group !== next && !path.some(function (p) { return p.col === chart.group; })) ? chart.group : null,
      sort: pk ? { by: 'x', dir: 'asc' } : { by: 'y', dir: 'desc' } });
  }

  /* 차트 설정 + Source(+필터) → 그릴 값 — app/report_dash.py compute 와 같은 규칙 / chart spec + source (+ filters) → values; same rules as the server */
  function rdCompute(chart, source, filters) {
    // 필터는 차트의 것(chart.filters) — 세 번째 인자를 주면 그것으로 바꿔 계산한다 / the chart's own filters apply unless overridden
    const rows = rdFilteredRows(source, filters === undefined ? chart.filters : filters), cols = source.columns, ys = chart.y, ctype = chart.type;
    const ciOf = function (col) { return col === '*' ? null : cols.indexOf(col); };
    if (ctype === 'kpi' || !chart.x) {
      const y0 = ys[0];
      return { kind: ctype, x: [y0.name], rows: rows.length, refs: [],
        series: [{ name: y0.name, type: 'bar', axis: 0, values: [rdAgg(rows, ciOf(y0.col), y0.agg)] }] };
    }
    const xi = cols.indexOf(chart.x), labels = [], buckets = {};
    rows.forEach(function (r) {
      const k = rdKey(r[xi]);
      if (!Object.prototype.hasOwnProperty.call(buckets, k)) { buckets[k] = []; labels.push(k); }
      buckets[k].push(r);
    });
    // 계열 하나 — 버킷마다 집계하고(짝 계산이면 둘째 값도), 순서와 무관한 계산까지 끝낸다 / one series: aggregate per bucket, then the order-independent calc
    const one = function (y, name, pick) {
      const a = labels.map(function (k) { return rdAgg(pick(buckets[k]), ciOf(y.col), y.agg); });
      const b = y.by ? labels.map(function (k) { return rdAgg(pick(buckets[k]), ciOf(y.by.col), y.by.agg); }) : null;
      const s = { name: name, type: y.type, axis: y.axis, values: rdCalcPoint(y, a, b) };
      if (y.unit) s.unit = y.unit;
      if (y.calc) s.calc = y.calc;
      return s;
    };
    let series = [], specs = [];
    if (chart.group) {
      const gi = cols.indexOf(chart.group), y = ys[0], groups = [];
      rows.forEach(function (r) { const g = rdKey(r[gi]); if (groups.indexOf(g) < 0) groups.push(g); });
      groups.slice(0, MAX_GROUP_SERIES).forEach(function (g) {
        series.push(one(y, g || '(빈 값)', function (rs) { return rs.filter(function (r) { return rdKey(r[gi]) === g; }); }));
        specs.push(y);
      });
    } else {
      series = ys.map(function (y) { return one(y, y.name, function (rs) { return rs; }); });
      specs = ys.slice();
    }
    const pkind = (source.periods || {})[chart.x];
    let items = labels.map(function (label, i) { return [label, series.map(function (s) { return s.values[i]; })]; });
    const sort = chart.sort || {}, first = function (it) { const v = it[1].length ? it[1][0] : 0; return (v === null || v === undefined) ? -Infinity : v; };
    if (sort.by === 'x') {
      const asPeriod = !!pkind && items.length > 0 && items.every(function (it) { return rdPeriodKey(it[0], pkind) !== null; });
      const numeric = items.length > 0 && items.every(function (it) { return rdNum(it[0]) !== null; });
      const cmp = asPeriod ? function (a, b) { const p = rdPeriodKey(a[0], pkind), q = rdPeriodKey(b[0], pkind); return (p[0] - q[0]) || (p[1] - q[1]); }
        : numeric ? function (a, b) { return rdNum(a[0]) - rdNum(b[0]); }
        : function (a, b) { return a[0] < b[0] ? -1 : (a[0] > b[0] ? 1 : 0); };
      items.sort(sort.dir === 'desc' ? function (a, b) { return cmp(b, a); } : cmp);
    } else if (sort.by === 'y') {
      const byVal = function (a, b) { const p = first(a), q = first(b); return p === q ? 0 : (p < q ? -1 : 1); };   // -Infinity 끼리 빼면 NaN 이라 비교로 / compare, never subtract infinities
      items.sort(sort.dir === 'asc' ? byVal : function (a, b) { return byVal(b, a); });
    }
    if (specs.some(function (y) { return ORDER_CALCS.indexOf(y.calc) >= 0; })) {   // 순서가 뜻인 계산은 정렬 뒤, 자르기 전에 / after sorting, before the limit
      const lbs = items.map(function (it) { return it[0]; });
      const colsOut = specs.map(function (y, si) { return rdCalcSeq(y, items.map(function (it) { return it[1][si]; }), lbs, pkind); });
      items = items.map(function (it, i) { return [it[0], colsOut.map(function (c) { return c[i]; })]; });
    }
    if (ctype === 'pie' || ctype === 'donut') {
      if (sort.by !== 'x') items.sort(function (a, b) { return first(b) - first(a); });
      const cap = Math.min(chart.limit || MAX_PIE_SLICES, MAX_PIE_SLICES);
      if (items.length > cap) {
        const rest = rdRound(items.slice(cap - 1).reduce(function (a, it) { return a + first(it); }, 0));
        items = items.slice(0, cap - 1).concat([[OTHERS, [rest]]]);
      }
    } else {
      items = items.slice(0, Math.min(chart.limit || MAX_X_ITEMS, MAX_X_ITEMS));
    }
    series.forEach(function (s, si) { s.values = items.map(function (it) { return it[1][si]; }); });
    const refs = [];
    (chart.ref_lines || []).forEach(function (ref) {
      let value = ref.value;
      if (ref.stat) {
        const target = series.filter(function (s) { return s.name === ref.series; })[0] || series[0];
        const vals = target ? target.values.filter(function (v) { return v !== null && v !== undefined; }) : [];   // 계산 값의 빈 칸은 뺀다 / skip the gaps of calculated values
        if (!vals.length) return;
        value = rdRound(rdStat(ref.stat, vals));
      }
      if (value !== null && value !== undefined) refs.push({ id: ref.id, label: ref.label, value: value, color: ref.color || '' });
    });
    const out = { kind: ctype, x: items.map(function (it) { return it[0]; }), series: series, refs: refs, rows: rows.length };
    const marks = (ctype === 'pie' || ctype === 'donut') ? [] : rdMarks(chart, series, refs, out.x);
    if (marks.length) out.marks = marks;
    const trend = rdTrend(chart, source, out.x, series);
    if (trend) out.trend = trend;
    return out;
  }

  /* 기간 축의 다음 라벨들 — 마지막 라벨의 모양(구분자·자릿수)을 그대로 잇는다. 서버 next_period_labels 와 같은 규칙 */
  /* The next labels of a period axis, continuing the last label's shape; same rules as next_period_labels on the server */
  function rdOrdinal(y, md) {
    const mo = Math.floor(md / 100), d = md % 100, dt = new Date(Date.UTC(y, mo - 1, d));
    return (dt.getUTCFullYear() === y && dt.getUTCMonth() === mo - 1 && dt.getUTCDate() === d) ? Math.round(dt.getTime() / 86400000) : null;
  }
  function rdNextPeriodLabels(labels, kind, count) {
    const parsed = labels.map(function (lb) { return [lb, rdParsePeriod(lb, kind)]; }).filter(function (p) { return p[1] && p[1][0] === kind; });
    if (!parsed.length || count < 1) return [];
    const last = parsed[parsed.length - 1][0];
    let y = parsed[parsed.length - 1][1][1], n = parsed[parsed.length - 1][1][2];
    const groups = last.match(/\d+/g) || [], found = parsed.map(function (p) { return p[0].match(/\d+/g) || []; }), plain = !/[가-힣]/.test(last);
    const padded = groups.map(function (_, i) {
      const at = found.filter(function (f) { return f.length > i; }).map(function (f) { return f[i]; });
      return at.some(function (g) { return g.length > 1 && g.charAt(0) === '0'; }) || (plain && at.every(function (g) { return g.length === 2; }));
    });
    let gap = 1;
    if (kind === 'date') {
      const days = parsed.map(function (p) { return rdOrdinal(p[1][1], p[1][2]); }).filter(function (d) { return d !== null; });
      const diffs = [];
      for (let i = 1; i < days.length; i++) if (days[i] > days[i - 1]) diffs.push(days[i] - days[i - 1]);
      diffs.sort(function (a, b) { return a - b; });
      gap = diffs.length ? diffs[Math.floor(diffs.length / 2)] : 1;
    }
    const out = [];
    for (let c = 0; c < count; c++) {
      let nums;
      if (kind === 'year') { y += 1; nums = [y]; }
      else if (kind === 'month' || kind === 'quarter' || kind === 'week') {
        const cycle = { month: 12, quarter: 4, week: 52 }[kind];
        n += 1;
        if (n > cycle) { n = 1; y = y ? y + 1 : 0; }
        nums = (kind === 'month' && groups.length === 1 && groups[0].length === 6) ? [y * 100 + n] : (groups.length >= 2 ? [y, n] : [n]);
      } else {
        const day = rdOrdinal(y, n);
        if (day === null) break;
        const d = new Date((day + gap) * 86400000);
        y = d.getUTCFullYear(); n = (d.getUTCMonth() + 1) * 100 + d.getUTCDate();
        nums = groups[0].length === 8 ? [y * 10000 + n] : [y, Math.floor(n / 100), n % 100];
      }
      let i = 0;
      out.push(last.replace(/\d+/g, function (m) {
        if (i >= nums.length) return m;
        const v = String(nums[i]), pad = padded[i];
        i += 1;
        return pad ? ('0000000' + v).slice(-Math.max(m.length, v.length)) : v;
      }));
    }
    return out;
  }

  /* 추세선(최소제곱 직선)과 간단한 예측 — 서버 _trend 와 같은 규칙: 보이는 값만으로 계산, 예측은 점 6개 이상·길이는 점 수의 1/3(최대 6),
     범위는 ±2σ 가 멀수록 넓어진다 / a least-squares trend line and a simple forecast, same rules as _trend on the server */
  const MIN_FORECAST_POINTS = 6, MAX_FORECAST = 6;
  function rdTrend(chart, source, labels, series) {
    const tr = chart.trend, pkind = (source.periods || {})[chart.x];
    if (!tr || !pkind || !series.length) return null;
    let si = 0;
    for (let i = 0; i < series.length; i++) { if (series[i].name === tr.series) { si = i; break; } }
    const vals = series[si].values, pts = [];
    vals.forEach(function (v, i) { if (v !== null && v !== undefined) pts.push([i, v]); });
    const n = pts.length;
    if (n < 3) return null;
    const xb = rdSum(pts.map(function (p) { return p[0]; })) / n, yb = rdSum(pts.map(function (p) { return p[1]; })) / n;
    const sxx = rdSum(pts.map(function (p) { return (p[0] - xb) * (p[0] - xb); }));
    const b = rdSum(pts.map(function (p) { return (p[0] - xb) * (p[1] - yb); })) / sxx, a = yb - b * xb;
    const out = { series: si, slope: rdRound(b), points: n };
    if (tr.line) out.values = vals.map(function (_, i) { return rdRound(a + b * i); });
    const want = tr.forecast || 0;
    if (want && n >= MIN_FORECAST_POINTS) {
      const h = Math.min(want, Math.max(1, Math.floor(n / 3)), MAX_FORECAST), size = vals.length;
      const sd = Math.sqrt(rdSum(pts.map(function (p) { const e = p[1] - (a + b * p[0]); return e * e; })) / (n - 2));
      const cycle = { month: 12, quarter: 4 }[pkind];
      const prevSum = cycle ? rdSum(vals.slice(size - 2 * cycle, size - cycle).map(function (v) { return v || 0; })) : 0;
      const seasonal = tr.method === 'seasonal' && !!cycle && n === size && size >= 2 * cycle && !!prevSum;
      let fvals = [];
      if (seasonal) {
        const g = rdSum(vals.slice(size - cycle)) / prevSum;
        for (let k = 0; k < h; k++) fvals.push(vals[size - cycle + (k % cycle)] * Math.pow(g, 1 + Math.floor(k / cycle)));
      } else for (let k = 0; k < h; k++) fvals.push(a + b * (size + k));
      const fresh = rdNextPeriodLabels(labels, pkind, h);
      fvals = fvals.slice(0, fresh.length);
      if (fresh.length) {
        out.forecast = { labels: fresh, values: fvals.map(rdRound), method: seasonal ? 'seasonal' : 'linear',
          low: fvals.map(function (v, k) { return rdRound(v - 2 * sd * Math.sqrt(k + 1)); }), high: fvals.map(function (v, k) { return rdRound(v + 2 * sd * Math.sqrt(k + 1)); }) };
      }
    }
    return out;
  }

  /* 테마 색 — 대표 색(과 둘째 색)에서 계열 색 6개를 만든다. 너무 밝거나 어두운 색은 흰 바탕에서 읽히는 밝기로 맞춘다 */
  /* Theme colours: six series colours from the brand (and second) colour, clamped to a lightness that reads on white */
  function rdHexToHsl(hex) {
    let h = String(hex || '').replace('#', '');
    if (h.length === 3) h = h.split('').map(function (c) { return c + c; }).join('');
    const r = parseInt(h.slice(0, 2), 16) / 255, g = parseInt(h.slice(2, 4), 16) / 255, b = parseInt(h.slice(4, 6), 16) / 255;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2;
    let hue = 0, s = 0;
    if (mx !== mn) {
      const d = mx - mn;
      s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
      hue = mx === r ? (g - b) / d + (g < b ? 6 : 0) : (mx === g ? (b - r) / d + 2 : (r - g) / d + 4);
      hue *= 60;
    }
    return [hue, s * 100, l * 100];
  }
  function rdHslToHex(h, s, l) {
    s /= 100; l /= 100;
    const k = function (n) { return (n + h / 30) % 12; }, a = s * Math.min(l, 1 - l);
    const f = function (n) { return l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1))); };
    return '#' + [f(0), f(8), f(4)].map(function (v) { return ('0' + Math.round(v * 255).toString(16)).slice(-2); }).join('').toUpperCase();
  }
  function rdThemePalette(theme) {
    if (!theme || !/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(theme.brand || '')) return null;
    const a = rdHexToHsl(theme.brand), sat = Math.max(38, Math.min(a[1], 78)), light = Math.max(34, Math.min(a[2], 56));
    const b = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(theme.second || '') ? rdHexToHsl(theme.second) : [(a[0] + 38) % 360, sat, light];
    const s2 = Math.max(38, Math.min(b[1], 78)), l2 = Math.max(34, Math.min(b[2], 56));
    return [rdHslToHex(a[0], sat, light), rdHslToHex(b[0], s2, l2), rdHslToHex(a[0], Math.max(30, sat - 12), Math.min(74, light + 20)),
      rdHslToHex((a[0] + 322) % 360, sat, light), rdHslToHex(b[0], Math.max(30, s2 - 12), Math.min(74, l2 + 20)), '#868E96'];
  }

  /* 복제본은 원본 데이터를 가리키기만 한다(2026-09-21) — 서버는 복제본의 행을 비워 보내고, 여기서 원본의 컬럼·행을 다시 잇는다(복사 없음).
     A clone only points at its root's data: the server sends clones without rows and this links the root's columns and rows back (no copy). */
  function rdLinkClones(state) {
    (state.sources || []).forEach(function (s) {
      const rootId = s.origin && s.origin.clone_of, root = rootId && state.sources.filter(function (r) { return r.id === rootId; })[0];
      if (!root || root === s || (root.origin && root.origin.clone_of)) return;
      ['columns', 'rows', 'types', 'periods', 'sql', 'tables', 'fetched_at'].forEach(function (k) { s[k] = root[k]; });
    });
    return state;
  }

  /* 요약 숫자의 값 — app/report_dash.py kpi_value 와 같은 규칙: 연결한 차트의 필터를 따르고, delta=prev 면 마지막 기간과 그 앞 기간을 비교한다.
     The value of a summary number, same rules as kpi_value on the server: the linked chart's filters apply; delta=prev compares the last two periods. */
  function rdKpi(kpi, state) {
    if (!kpi.source) return { value: (kpi.value === undefined || kpi.value === null) ? null : Number(kpi.value), rows: 0, manual: true };   // 직접 적은 숫자(2026-10-12) / a typed number
    const src = state.sources.filter(function (s) { return s.id === kpi.source; })[0];
    if (!src) return { value: null, rows: 0 };
    const chart = kpi.link ? state.charts.filter(function (c) { return c.id === kpi.link; })[0] : null;
    const rows = chart ? rdFilteredRows(src, chart.filters) : src.rows, ci = kpi.col === '*' ? null : src.columns.indexOf(kpi.col);
    const out = { value: rdAgg(rows, ci, kpi.agg), rows: rows.length }, periods = src.periods || {}, pcols = Object.keys(periods);
    if (kpi.delta === 'prev' && pcols.length) {
      const pcol = (chart && chart.x && periods[chart.x]) ? chart.x : pcols[0], pi = src.columns.indexOf(pcol), kind = periods[pcol], buckets = {}, order = [];
      rows.forEach(function (r) {
        const k = rdPeriodKey(r[pi], kind);
        if (!k) return;
        const id = k[0] + ':' + k[1];
        if (!buckets[id]) { buckets[id] = { key: k, label: rdKey(r[pi]), rows: [] }; order.push(buckets[id]); }
        buckets[id].rows.push(r);
      });
      order.sort(function (a, b) { return (a.key[0] - b.key[0]) || (a.key[1] - b.key[1]); });
      if (order.length >= 2) {
        const L = order[order.length - 1], P = order[order.length - 2], last = rdAgg(L.rows, ci, kpi.agg), prev = rdAgg(P.rows, ci, kpi.agg);
        out.period = L.label; out.prev_period = P.label; out.last = last;
        out.delta = prev ? rdRound((last - prev) / Math.abs(prev) * 100) : null;
      }
    }
    return out;
  }

  /* 비교 묶음의 값 범위 — 같은 묶음의 차트가 값 축 눈금을 같이 쓰게 한다(누적이면 누적 합 기준) / the value range of a compare group, so its charts share one scale */
  function rdCompareRange(pairs) {
    let min = 0, max = 0;
    pairs.forEach(function (p) {
      const chart = p[0], comp = p[1], main = comp.series.filter(function (s) { return s.axis !== 1; });
      comp.x.forEach(function (_, i) {
        const vals = main.map(function (s) { return s.values[i]; }).filter(function (v) { return v !== null && v !== undefined; });
        if (!vals.length) return;
        if (chart.stack) { max = Math.max(max, rdSum(vals.filter(function (v) { return v > 0; }))); min = Math.min(min, rdSum(vals.filter(function (v) { return v < 0; }))); }
        else { max = Math.max(max, Math.max.apply(null, vals)); min = Math.min(min, Math.min.apply(null, vals)); }
      });
    });
    return { min: min, max: max };
  }

  /* 강조 규칙 → 그 계열의 점마다 [색, 흐리게] (규칙이 없으면 null) / highlight marks → a [colour, dimmed] pair per point of that series, or null */
  function rdMarkColors(comp, si, base) {
    const marks = (comp.marks || []).filter(function (m) { return m.series === si; });
    if (!marks.length) return null;
    const dimRest = marks.some(function (m) { return m.dim; });
    const out = comp.x.map(function () { return [base, dimRest]; });
    marks.forEach(function (m) { m.hits.forEach(function (i) { out[i] = [m.color || base, false]; }); });
    return out;
  }

  function rdFmt(v, unit) {
    if (v === null || v === undefined || !isFinite(v)) return '';
    const a = Math.abs(v);
    let text;
    if (a >= 1e8) text = (v / 1e8).toLocaleString('ko-KR', { maximumFractionDigits: 1 }) + '억';
    else if (a >= 1e4 || Number.isInteger(v)) text = Math.round(v).toLocaleString('ko-KR');
    else text = v.toLocaleString('ko-KR', { maximumFractionDigits: 2 });
    return text + (unit || '');
  }

  function rdAlpha(hex, a) {
    const h = String(hex || '#5B5BD6').replace('#', '');
    const f = h.length === 3 ? h.split('').map(function (c) { return c + c; }).join('') : h.slice(0, 6);
    return 'rgba(' + parseInt(f.slice(0, 2), 16) + ',' + parseInt(f.slice(2, 4), 16) + ',' + parseInt(f.slice(4, 6), 16) + ',' + a + ')';
  }

  /* 세로 그라데이션 채움 — 차트 영역이 아직 없으면(첫 레이아웃 전) 단색 / vertical gradient fill; a flat colour before the first layout */
  function rdGradient(color, top, bottom, horizontal) {
    return function (ctx) {
      const area = ctx.chart.chartArea;
      if (!area) return rdAlpha(color, top);
      const g = horizontal ? ctx.chart.ctx.createLinearGradient(area.right, 0, area.left, 0)
        : ctx.chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
      g.addColorStop(0, rdAlpha(color, top));
      g.addColorStop(1, rdAlpha(color, bottom));
      return g;
    };
  }

  /* 기준선 플러그인 — 값 축에 점선 + 끝에 이름표 / reference lines: a dashed line on the value axis with a tag at the end */
  const RD_REF_PLUGIN = {
    id: 'rdRefLines',
    afterDatasetsDraw: function (chart, args, opts) {
      const lines = (opts && opts.lines) || [];
      if (!lines.length || !chart.chartArea) return;
      const horizontal = chart.options.indexAxis === 'y';
      const scale = chart.scales[horizontal ? 'x' : 'y'];
      if (!scale) return;
      const ctx = chart.ctx, area = chart.chartArea;
      lines.forEach(function (ln) {
        const p = scale.getPixelForValue(ln.value);
        if (!isFinite(p)) return;
        ctx.save();
        ctx.strokeStyle = ln.color; ctx.lineWidth = 1.5; ctx.setLineDash([6, 4]);
        ctx.beginPath();
        if (horizontal) { ctx.moveTo(p, area.top); ctx.lineTo(p, area.bottom); } else { ctx.moveTo(area.left, p); ctx.lineTo(area.right, p); }
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.font = '600 10.5px Pretendard, system-ui, sans-serif';
        const text = ln.label + ' ' + ln.text, w = ctx.measureText(text).width + 12, h = 18;
        const bx = horizontal ? Math.min(Math.max(p - w / 2, area.left), area.right - w) : area.right - w;
        const by = horizontal ? area.top : Math.max(p - h - 3, area.top);
        ctx.fillStyle = ln.color;
        if (ctx.roundRect) { ctx.beginPath(); ctx.roundRect(bx, by, w, h, 5); ctx.fill(); } else ctx.fillRect(bx, by, w, h);
        ctx.fillStyle = '#fff'; ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
        ctx.fillText(text, bx + 6, by + h / 2 + 0.5);
        ctx.restore();
      });
    },
  };

  /* 값 라벨 플러그인 — 막대·선은 값, 원·도넛은 비율 / value labels: values on bars and lines, shares on pies */
  const RD_LABEL_PLUGIN = {
    id: 'rdValueLabels',
    afterDatasetsDraw: function (chart, args, opts) {
      if (!opts || !opts.on) return;
      const ctx = chart.ctx, pie = chart.config.type === 'pie' || chart.config.type === 'doughnut';
      const horizontal = chart.options.indexAxis === 'y';
      ctx.save();
      ctx.font = '600 10.5px Pretendard, system-ui, sans-serif';
      chart.data.datasets.forEach(function (ds, di) {
        const meta = chart.getDatasetMeta(di);
        if (meta.hidden || ds.rdAux) return;
        const total = pie ? ds.data.reduce(function (a, b) { return a + (b || 0); }, 0) : 0;
        meta.data.forEach(function (el, i) {
          const v = ds.data[i];
          if (v === null || v === undefined) return;
          if (pie) {
            if (!total || v / total < 0.06) return;
            const pos = el.tooltipPosition();
            ctx.fillStyle = '#fff'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
            ctx.fillText(Math.round((v / total) * 100) + '%', pos.x, pos.y);
            return;
          }
          if (chart.options.scales && chart.options.scales.x && chart.options.scales.x.stacked && chart.data.datasets.length > 1) return;
          ctx.fillStyle = '#4A5163';
          const u = ds.rdUnit === undefined ? opts.unit : ds.rdUnit;
          if (horizontal) { ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(rdFmt(v, u), el.x + 5, el.y); }
          else { ctx.textAlign = 'center'; ctx.textBaseline = 'bottom'; ctx.fillText(rdFmt(v, u), el.x, el.y - 5); }
        });
      });
      ctx.restore();
    },
  };

  /* 메모(주석) 플러그인 — x 값에 붙은 이름표: 점 + 가는 선 + 글 상자. 캔버스에 그리므로 PNG 저장·공유 화면에도 그대로 나온다.
     Notes: a tag anchored to an x value (dot, leader line, text box); drawn on the canvas, so it shows in PNGs and shared views too. */
  const RD_NOTE_PLUGIN = {
    id: 'rdNotes',
    afterDatasetsDraw: function (chart, args, opts) {
      const notes = (opts && opts.notes) || [];
      if (!notes.length || !chart.chartArea) return;
      const horizontal = chart.options.indexAxis === 'y', ctx = chart.ctx, area = chart.chartArea;
      const cat = chart.scales[horizontal ? 'y' : 'x'], val = chart.scales[horizontal ? 'x' : 'y'];
      if (!cat || !val) return;
      ctx.save();
      ctx.font = '600 10.5px Pretendard, system-ui, sans-serif';
      notes.forEach(function (n) {
        const c = cat.getPixelForValue(n.index), v = val.getPixelForValue(n.value);
        if (!isFinite(c) || !isFinite(v)) return;
        const w = ctx.measureText(n.text).width + 14, h = 19;
        const px = horizontal ? v : c, py = horizontal ? c : v;
        const bx = horizontal ? Math.min(px + 12, area.right - w) : Math.min(Math.max(px - w / 2, area.left), area.right - w);
        const by = horizontal ? py - h / 2 : Math.max(py - 34, area.top - 20);
        ctx.strokeStyle = '#B7791F'; ctx.lineWidth = 1;
        ctx.beginPath();
        if (horizontal) { ctx.moveTo(px + 4, py); ctx.lineTo(bx, py); } else { ctx.moveTo(px, py - 5); ctx.lineTo(px, by + h); }
        ctx.stroke();
        ctx.fillStyle = '#FFF4DB'; ctx.strokeStyle = '#F2D48A';
        if (ctx.roundRect) { ctx.beginPath(); ctx.roundRect(bx, by, w, h, 5); ctx.fill(); ctx.stroke(); } else { ctx.fillRect(bx, by, w, h); ctx.strokeRect(bx, by, w, h); }
        ctx.fillStyle = '#8A5A00'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
        ctx.fillText(n.text, bx + 7, by + h / 2 + 0.5);
        ctx.beginPath(); ctx.arc(px, py, 4, 0, Math.PI * 2); ctx.fillStyle = '#B7791F'; ctx.fill();
        ctx.lineWidth = 1.5; ctx.strokeStyle = '#fff'; ctx.stroke();
      });
      ctx.restore();
    },
  };

  /* 내려받은 PNG 가 투명하지 않게 흰 바탕 / a white ground so downloaded PNGs are not transparent */
  const RD_BG_PLUGIN = {
    id: 'rdWhiteBg',
    beforeDraw: function (chart) {
      const ctx = chart.ctx;
      ctx.save(); ctx.globalCompositeOperation = 'destination-over'; ctx.fillStyle = '#fff';
      ctx.fillRect(0, 0, chart.width, chart.height); ctx.restore();
    },
  };

  /* 차트 설정 + 계산 값 → Chart.js 구성. Chart 전역을 쓰지 않아 노드에서도 검사할 수 있다 / spec + computed → a Chart.js config (no Chart global needed) */
  const T_TREND = ['추세선', '예측(참고용)', '예측 범위'];   // 범례 이름 — 화면 쪽이 언어에 맞게 바꿔 끼운다 / legend names; the UI swaps them per language
  function rdChartConfig(chart, comp, env) {
    env = env || {};
    const style = chart.style || {}, unit = chart.unit || '';
    const colors = (style.palette === 'theme' && rdThemePalette(env.theme)) || PALETTES[style.palette] || PALETTES.indigo;
    const kind = chart.type, pie = kind === 'pie' || kind === 'donut', horizontal = kind === 'hbar';
    const font = { family: 'Pretendard, system-ui, -apple-system, sans-serif', size: 11 };
    const many = comp.x.length > 24;
    const unitOf = function (s) { return (s && s.unit) || unit; };   // 계열 단위(계산 값의 % 등) — 없으면 차트 단위 / a per-series unit, else the chart's
    const datasets = comp.series.map(function (s, i) {
      const color = colors[i % colors.length], mc = rdMarkColors(comp, i, color);   // mc: 강조 규칙이 있으면 점마다 [색, 흐리게] / per-point [colour, dimmed]
      if (pie) {
        return { label: s.name, data: s.values, backgroundColor: comp.x.map(function (_, k) { return colors[k % colors.length]; }),
          borderColor: '#fff', borderWidth: 2, hoverOffset: 6, rdUnit: unitOf(s) };
      }
      const line = !horizontal && (s.type === 'line' || kind === 'area');
      if (line) {
        const fill = kind === 'area' || !!style.fill;
        const hit = function (k) { return mc && mc[k] && !mc[k][1] && (comp.marks || []).some(function (m) { return m.series === i && m.hits.indexOf(k) >= 0; }); };
        return { type: 'line', label: s.name, data: s.values, yAxisID: s.axis === 1 ? 'y1' : 'y', borderColor: color, borderWidth: 2.5,
          tension: style.smooth === false ? 0 : 0.35, pointHoverRadius: 5, pointBorderWidth: 2, pointHitRadius: 12, spanGaps: false,
          pointRadius: mc ? comp.x.map(function (_, k) { return hit(k) ? 5.5 : (many ? 0 : 3); }) : (many ? 0 : 3),
          pointBackgroundColor: mc ? comp.x.map(function (_, k) { return hit(k) ? mc[k][0] : '#fff'; }) : '#fff',
          pointBorderColor: mc ? comp.x.map(function (_, k) { return hit(k) ? mc[k][0] : color; }) : color,
          fill: fill ? (chart.stack && i > 0 ? '-1' : 'origin') : false,
          backgroundColor: fill ? rdGradient(color, 0.28, 0.02, false) : color, order: 1, rdUnit: unitOf(s) };
      }
      const radius = style.rounded === false ? 0 : 6;
      return { type: 'bar', label: s.name, data: s.values, yAxisID: (!horizontal && s.axis === 1) ? 'y1' : (horizontal ? undefined : 'y'),
        // 강조 규칙이 있으면 막대마다 색을 고른다(맞는 막대 = 규칙 색, 나머지 = 그대로 또는 흐리게) / with highlight rules each bar picks its colour
        backgroundColor: mc ? function (ctx) { const m = mc[ctx.dataIndex] || [color, false]; return rdGradient(m[0], m[1] ? 0.3 : 0.95, m[1] ? 0.16 : 0.62, horizontal)(ctx); }
          : rdGradient(color, 0.95, 0.62, horizontal),
        hoverBackgroundColor: mc ? function (ctx) { const m = mc[ctx.dataIndex] || [color, false]; return rdAlpha(m[0], m[1] ? 0.5 : 1); } : color,
        borderRadius: radius, borderSkipped: false, maxBarThickness: 46, categoryPercentage: 0.72, barPercentage: 0.86, order: 2, rdUnit: unitOf(s) };
    });
    // 추세선(긴 점선)과 예측(짧은 점선 + 빈 점 + 옅은 범위 띠): 예측은 x 축을 그만큼 늘리고 다른 계열은 빈 칸으로 채운다
    // The trend line (long dashes) and the forecast (short dashes, hollow points, a faint band): the forecast extends the x axis
    const tr = pie || horizontal ? null : comp.trend, fc = tr && tr.forecast, labels = fc ? comp.x.concat(fc.labels) : comp.x;
    if (tr) {
      const base = comp.series[tr.series] || comp.series[0], tcolor = colors[tr.series % colors.length], axisId = base && base.axis === 1 ? 'y1' : 'y';
      const gap = function (k) { const a = []; for (let i = 0; i < k; i++) a.push(null); return a; };
      if (fc) datasets.forEach(function (d) { d.data = d.data.concat(gap(fc.labels.length)); });
      if (tr.values) {
        datasets.push({ type: 'line', label: T_TREND[0], data: tr.values.concat(fc ? gap(fc.labels.length) : []), yAxisID: axisId, borderColor: '#5F6675', borderWidth: 1.5,
          borderDash: [7, 5], pointRadius: 0, pointHoverRadius: 0, tension: 0, fill: false, order: 0, rdUnit: unitOf(base), rdAux: true });
      }
      if (fc) {
        const n = comp.x.length, lastVal = base.values[n - 1], head = gap(n - 1);
        const join = function (arr) { return head.concat([lastVal]).concat(arr); };   // 마지막 실제 값에서 이어 그린다 / continue from the last actual value
        datasets.push({ type: 'line', label: T_TREND[1], data: join(fc.values), yAxisID: axisId, borderColor: tcolor, borderWidth: 2, borderDash: [3, 4],
          pointRadius: join(fc.values).map(function (_, i) { return i >= n ? 4 : 0; }), pointHoverRadius: 5, pointBackgroundColor: '#fff', pointBorderColor: tcolor, pointBorderWidth: 2,
          tension: 0, fill: false, order: 0, rdUnit: unitOf(base), rdAux: true });
        datasets.push({ type: 'line', label: T_TREND[2], data: join(fc.high), yAxisID: axisId, borderWidth: 0, pointRadius: 0, pointHoverRadius: 0, tension: 0,
          fill: '+1', backgroundColor: rdAlpha(tcolor, 0.13), order: 3, rdUnit: unitOf(base), rdAux: true, rdBand: true });
        datasets.push({ type: 'line', label: T_TREND[2], data: join(fc.low), yAxisID: axisId, borderWidth: 0, pointRadius: 0, pointHoverRadius: 0, tension: 0,
          fill: false, order: 3, rdUnit: unitOf(base), rdAux: true, rdBand: true });
      }
    }
    const axisUnit = function (axis) { return unitOf(comp.series.filter(function (s) { return (s.axis === 1 ? 1 : 0) === axis; })[0]); };
    const unit0 = horizontal ? unitOf(comp.series[0]) : axisUnit(0);
    const tick = function (v) { return rdFmt(v, unit0); };
    const label = function (v) { const s = String(this.getLabelForValue(v)); return s.length > 14 ? s.slice(0, 13) + '…' : s; };
    const grid = { color: '#EEF0F5', drawTicks: false, display: style.grid !== false };
    const border = { display: false };
    const refValues = (comp.refs || []).map(function (r) { return r.value; });
    const valueAxis = { beginAtZero: true, grid: grid, border: border, stacked: !!chart.stack,
      ticks: { color: '#8A90A0', font: font, padding: 8, callback: tick, maxTicksLimit: 6 },
      title: { display: !!chart.yLabel, text: chart.yLabel || '', color: '#8A90A0', font: font } };
    if (refValues.length) {   // 기준선이 축 밖으로 나가지 않게 / keep reference lines inside the axis
      valueAxis.suggestedMax = Math.max.apply(null, refValues) * 1.08;
      valueAxis.suggestedMin = Math.min(0, Math.min.apply(null, refValues));
    }
    if (env.lock) {   // 비교 묶음: 같은 묶음의 차트와 값 축 눈금을 맞춘다 / a compare group shares one value-axis scale
      valueAxis.suggestedMax = Math.max(valueAxis.suggestedMax || 0, env.lock.max);
      valueAxis.suggestedMin = Math.min(valueAxis.suggestedMin || 0, env.lock.min);
    }
    // 메모: x 값이 지금 보이는 항목에 있을 때만, 그 자리의 가장 큰 값(누적이면 합) 위에 붙인다 / notes sit on the tallest value of their x, when that x is in view
    const main = comp.series.filter(function (s) { return horizontal || s.axis !== 1; });
    const notes = pie ? [] : (chart.notes || []).map(function (n) {
      const i = comp.x.indexOf(n.x);
      if (i < 0) return null;
      const vals = main.map(function (s) { return s.values[i]; }).filter(function (v) { return v !== null && v !== undefined; });
      const top = !vals.length ? 0 : (chart.stack ? vals.filter(function (v) { return v > 0; }).reduce(function (a, b) { return a + b; }, 0) : Math.max.apply(null, vals));
      return { index: i, value: top, text: n.text };
    }).filter(Boolean);
    const catAxis = { grid: { display: false }, border: { display: true, color: '#E3E6EE' }, stacked: !!chart.stack,
      ticks: { color: '#6B7180', font: font, padding: 6, maxRotation: 40, autoSkip: true, callback: label },
      title: { display: !!chart.xLabel, text: chart.xLabel || '', color: '#8A90A0', font: font } };
    let scales;
    if (pie) scales = {};
    else if (horizontal) scales = { x: valueAxis, y: catAxis };
    else {
      scales = { x: catAxis, y: valueAxis };
      if (comp.series.some(function (s) { return s.axis === 1; })) {
        const unit1 = axisUnit(1);
        scales.y1 = { position: 'right', beginAtZero: true, grid: { drawOnChartArea: false, drawTicks: false }, border: border,
          ticks: { color: '#8A90A0', font: font, padding: 8, callback: function (v) { return rdFmt(v, unit1); }, maxTicksLimit: 6 } };
      }
    }
    const legendOn = style.legend !== 'none' && (pie || datasets.length > 1);
    const legendFilter = function (item, data) { return !data.datasets[item.datasetIndex] || !data.datasets[item.datasetIndex].rdBand; };   // 범위 띠는 범례에서 뺀다 / the band stays out of the legend
    // 막대·조각·점을 눌렀을 때만 알린다(드릴다운) — 빈 곳을 누르면 카드의 대상 선택이 된다. 선의 점은 16px 안이면 잡는다(rdPickIndex)
    // report only hits on a mark (drill-down); empty space selects the card. Line points count within 16px (rdPickIndex)
    const pickAt = function (evt, ch) { return rdPickIndex(ch, evt); };
    return {
      type: pie ? (kind === 'donut' ? 'doughnut' : 'pie') : (datasets.length && datasets.every(function (d) { return d.type === 'line'; }) ? 'line' : 'bar'),
      data: { labels: labels, datasets: datasets },
      options: {
        responsive: true, maintainAspectRatio: false, indexAxis: horizontal ? 'y' : 'x', cutout: kind === 'donut' ? '62%' : undefined,
        animation: env.still ? false : { duration: 520, easing: 'easeOutQuart' },
        // 누를 수 있는 막대 위에서는 커서를 바꾼다. 클릭 자체는 화면 쪽 클릭 처리기가 받는다 — Chart.js 의 onClick 은 다음 프레임에 불려서
        // 카드의 대상 선택보다 늦다 / the cursor marks pickable marks; the click itself is handled by the DOM handler, since Chart.js
        // calls onClick a frame later, after the card's own click handling
        // '기타' 조각은 한 값이 아니라 내려갈 곳이 없다 — 돋보기도 없다 / the 'others' slice is not one value: no zoom there
        onHover: env.pickable ? function (evt, els, ch) { const i = pickAt(evt, ch); ch.canvas.style.cursor = i >= 0 && !(pie && labels[i] === OTHERS) ? 'zoom-in' : ''; } : undefined,
        interaction: pie ? { mode: 'nearest', intersect: true } : { mode: 'index', intersect: false, axis: horizontal ? 'y' : 'x' },
        layout: { padding: { top: (notes.length && !horizontal) ? 38 : (refValues.length || style.labels ? 22 : 8), right: horizontal && (style.labels || notes.length) ? 44 : 8, bottom: 2, left: 2 } },
        scales: scales,
        plugins: {
          legend: { display: legendOn, position: style.legend && style.legend !== 'none' ? style.legend : (pie ? 'right' : 'bottom'),
            labels: { usePointStyle: true, pointStyle: 'circle', boxWidth: 7, boxHeight: 7, padding: 14, color: '#5F6675', font: { family: font.family, size: 11.5 }, filter: pie ? undefined : legendFilter } },
          tooltip: { filter: function (item) { return !item.dataset.rdBand; }, backgroundColor: '#1B2033', padding: 10, cornerRadius: 8, titleFont: { family: font.family, size: 12, weight: '700' },
            bodyFont: { family: font.family, size: 12 }, boxPadding: 4, usePointStyle: true,
            callbacks: { label: function (c) {
              const v = pie ? c.parsed : (horizontal ? c.parsed.x : c.parsed.y);
              const total = pie ? c.dataset.data.reduce(function (a, b) { return a + (b || 0); }, 0) : 0;
              return ' ' + (pie ? c.label : c.dataset.label) + ': ' + rdFmt(v, c.dataset.rdUnit === undefined ? unit : c.dataset.rdUnit) + (pie && total ? ' (' + Math.round((v / total) * 100) + '%)' : '');
            } } },
          rdRefLines: { lines: (comp.refs || []).map(function (r, i) {
            return { value: r.value, label: r.label, text: rdFmt(r.value, unit0), color: r.color || ['#E8590C', '#0CA678', '#7048E8', '#D6336C'][i % 4] };
          }) },
          rdValueLabels: { on: !!style.labels, unit: unit },
          rdNotes: { notes: notes },
        },
      },
      plugins: [RD_BG_PLUGIN, RD_REF_PLUGIN, RD_LABEL_PLUGIN, RD_NOTE_PLUGIN],
    };
  }

  /* 누른 자리의 막대·조각·점 번호(없으면 -1) — 막대와 조각은 그 위를 눌러야 하고, 선 차트의 점은 작아서 16px 안이면 그 점으로 본다(2026-09-30).
     evt = Chart.js 이벤트(x·y 가 캔버스 좌표) 또는 DOM 클릭(clientX·clientY).
     The index of the clicked bar, slice or point (-1 when none): bars and slices need a hit, while a line point, being tiny,
     counts within 16px (2026-09-30). evt is a Chart.js event (x, y on the canvas) or a DOM click (clientX, clientY). */
  function rdPickIndex(ch, evt) {
    const hit = ch.getElementsAtEventForMode(evt, 'nearest', { intersect: true }, true)[0];
    if (hit) return hit.index;
    const type = ch.config && ch.config.type;
    if (type === 'pie' || type === 'doughnut') return rdSliceAt(ch, evt);
    if (type !== 'line') return -1;
    const near = ch.getElementsAtEventForMode(evt, 'nearest', { intersect: false, axis: 'xy' }, true)[0];
    const at = near && near.element ? rdCanvasXY(ch, evt) : null;
    return (at && Math.hypot(near.element.x - at.x, near.element.y - at.y) <= 16) ? near.index : -1;
  }
  /* 캔버스 좌표 — Chart.js 이벤트는 x·y 그대로, DOM 클릭은 clientX·clientY 에서 캔버스 위치를 뺀다 / canvas coordinates of an event */
  function rdCanvasXY(ch, evt) {
    let x = evt.x, y = evt.y;
    if (evt.native === undefined && typeof evt.clientX === 'number' && ch.canvas) {
      const r = ch.canvas.getBoundingClientRect();
      x = evt.clientX - r.left; y = evt.clientY - r.top;
    }
    return (typeof x === 'number' && typeof y === 'number') ? { x: x, y: y } : null;
  }
  /* 원·도넛(2026-10-01): 조각 위가 아니어도 그림 안이면 중심에서의 방향으로 조각을 고른다 — 가운데 구멍이나 조각 바로 바깥을 눌러도 그 방향의
     조각이다. 반지름의 0.15배 안(방향이 뜻을 잃음) · 1.4배 밖 · 그림 영역 밖(범례)은 고르지 않는다. 각도는 Chart.js 조각의 실제 값을 쓴다.
     Pie and donut (2026-10-01): off a slice but inside the plot, pick the slice in that direction from the centre, so the hole
     or just outside a slice works too. Within 0.15 of the radius (no direction), beyond 1.4 of it, or outside the chart area
     (the legend) picks nothing. The angles are Chart.js's own slice geometry. */
  function rdSliceAt(ch, evt) {
    const at = rdCanvasXY(ch, evt), area = ch.chartArea, arcs = ((ch.getDatasetMeta && ch.getDatasetMeta(0)) || {}).data || [];
    if (!at || !arcs.length || (area && (at.x < area.left || at.x > area.right || at.y < area.top || at.y > area.bottom))) return -1;
    const c = arcs[0].getProps(['x', 'y', 'outerRadius'], true), away = Math.hypot(at.x - c.x, at.y - c.y);
    if (!(c.outerRadius > 0) || away > c.outerRadius * 1.4 || away < c.outerRadius * 0.15) return -1;
    const turn = Math.PI * 2, angle = Math.atan2(at.y - c.y, at.x - c.x);
    for (let i = 0; i < arcs.length; i++) {
      const a = arcs[i].getProps(['startAngle', 'endAngle'], true);
      if (!(a.endAngle > a.startAngle)) continue;   // 범례로 끈 조각 / a slice hidden from the legend
      if ((((angle - a.startAngle) % turn) + turn) % turn < a.endAngle - a.startAngle) return i;
    }
    return -1;
  }
  /* 드릴다운 경로의 이름표(누른 값들) — 서버에서 받은 단계를 경로별로 기억한다 / the signature of a drill path (the clicked values) */
  function rdDrillSig(path) { return JSON.stringify((path || []).map(function (p) { return [p.col, rdKey(p.value)]; })); }

  /* 실행 내역을 에이전트별 가지로 — 순서를 지키며 이어진 같은 에이전트끼리 묶는다 / group consecutive trace entries by agent, keeping order */
  function rdTraceTree(trace) {
    const out = [];
    (trace || []).forEach(function (t) {
      const last = out[out.length - 1];
      if (last && last.agent === t.agent) last.tools.push(t); else out.push({ agent: t.agent, tools: [t] });
    });
    return out;
  }

  const PURE = { rdTraceTree: rdTraceTree, rdNum: rdNum, rdKey: rdKey, rdFilteredRows: rdFilteredRows, rdCompute: rdCompute, rdFmt: rdFmt, rdChartConfig: rdChartConfig, PALETTES: PALETTES,
    rdParsePeriod: rdParsePeriod, rdPeriodKey: rdPeriodKey, rdMarkColors: rdMarkColors, rdDrillChart: rdDrillChart,
    rdLinkClones: rdLinkClones, rdKpi: rdKpi, rdCompareRange: rdCompareRange, rdRangeTest: rdRangeTest, rdNextPeriodLabels: rdNextPeriodLabels,
    rdTrend: rdTrend, rdThemePalette: rdThemePalette, rdPickIndex: rdPickIndex, rdDrillSig: rdDrillSig, OTHERS: OTHERS };
  if (typeof module !== 'undefined' && module.exports) module.exports = PURE;
  if (typeof document === 'undefined' || typeof window === 'undefined') return;

  /* ── 화면 / UI ── */
  const E = (typeof ai365Esc === 'function') ? ai365Esc : function (s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  function T(ko) { return (typeof ai365T === 'function') ? ai365T(ko) : ko; }
  function isEn() { return typeof ai365CurrentLang === 'function' && ai365CurrentLang() === 'en'; }
  function acting() { return (typeof ai365ActingId === 'function') ? ai365ActingId() : ''; }
  function say(msg) { if (typeof toast === 'function') toast(msg); }
  function when(iso) { return String(iso || '').replace('T', ' ').slice(0, 16); }

  const DICT = {
    '리포트 에이전트': 'Report agent', '내 보관소': 'My library', '대시보드': 'Dashboard', '닫기': 'Close',
    '저장됨': 'Saved', '저장 안 됨': 'Not saved yet', '저장하지 않은 변경': 'Unsaved changes',
    '저장하고 닫기': 'Save and close', '저장하지 않고 닫기': 'Close without saving', '계속 편집': 'Keep editing',
    '저장하고 열기': 'Save and open', '저장하지 않고 열기': 'Open without saving', '저장하지 않은 변경 사항이 있습니다.': 'You have unsaved changes.',
    '저장하지 않으면 마지막으로 저장한 내용만 남습니다.': 'Without saving, only the last saved copy remains.',
    '저장하지 않으면 이 대시보드는 보관함에 남지 않습니다.': 'Without saving, this dashboard will not be kept in your library.',
    '내 보관소에 저장했습니다.': 'Saved to my library.', '저장했습니다.': 'Saved.',   // 2026-10-06 이름 통일(게시판 개편) / naming aligned with the board redesign
    '리포트 에이전트가 작업 중입니다. 끝난 뒤 저장해 주세요.': 'The report agent is still working. Save when it finishes.',
    '차트가 없는 대시보드는 저장할 수 없습니다.': 'A dashboard without charts cannot be saved.', '이름 변경': 'Rename',
    '데이터 새로고침': 'Refresh data', '대시보드 공유': 'Share dashboard', '필터': 'Filters', '전체': 'All',
    '전체 선택': 'Select all', '선택 해제': 'Clear', '값 검색': 'Search values', '필터 삭제': 'Remove filter',
    '크기 전환': 'Toggle size', '다시 생성': 'Regenerate', '내려받기': 'Download', '공유': 'Share this chart', '내 보관소에 저장': 'Save to my library',
    '차트 삭제': 'Delete chart', '참조': 'uses', '차트를 만드는 중…': 'Building charts…', '다시 만드는 중…': 'Regenerating…',
    '이 데이터를 쓰는 차트': 'Charts using this data', '아직 이 데이터를 쓰는 차트가 없습니다.': 'No chart uses this data yet.',
    '원본 테이블': 'Source tables', '조회 시각': 'Fetched at', '행': 'rows', '열': 'columns', '조회 SQL': 'Query SQL',
    '필터 적용 중': 'Filtered',
    '대화 기록': 'Conversation', '대화 기록 접기': 'Hide conversation', '대상': 'Target', '리포트 에이전트가 작업 중…': 'The report agent is working…',
    '리포트 데이터를 바탕으로 궁금한 내용을 입력하세요.': 'Ask anything about the report data.', '보내기': 'Send',
    '아직 차트가 없습니다': 'No charts yet', '아래 입력창에 보고 싶은 내용을 요청해 보세요. 예: 지난달 부서별 매출을 막대 차트로 보여줘':
      'Ask for what you want to see in the box below, e.g. show last month\'s sales by department as a bar chart',
    '대시보드로': 'Back to dashboard', '새 대시보드': 'New dashboard', '열기': 'Open', '삭제': 'Delete', '리포트': 'Report',
    '저장한 리포트와 대시보드가 없습니다': 'No saved reports or dashboards', '대시보드 머리줄의 [저장]을 누르면 여기에 보관됩니다.': 'Press [Save] in the dashboard header to keep it here.',
    '불러오는 중…': 'Loading…', '차트': 'charts', '예전 저장분': 'Legacy', '데이터 출처': 'Data sources', '쓰는 차트': 'Used by',
    '리포트 에이전트에서 열기': 'Open in the report agent',
    '메일로 공유': 'Share by email', '게시판으로 공유': 'Share to board', '게시판에 공유': 'Share to board', '메일 공유 기능을 불러오지 못했습니다.': 'Could not load email sharing.',
    '전체 대시보드': 'Full dashboard', '전체 보기': 'Show all', '필터할 컬럼': 'Column to filter', '수정 중…': 'Updating…',
    '필터에 맞는 데이터가 없습니다': 'No data matches the filters', '원본 데이터': 'Source data',
    '이 데이터로 차트 만들기': 'Build a chart from this data', '아직 이 데이터로 만든 차트가 없습니다': 'No chart has been built from this data yet',
    '도구 트리': 'Tool tree', '리포트 에이전트의 도구': 'Tools of the report agent', '도구를 고르는 중…': 'Choosing tools…',
    '항목을 누르면 요청 문장이 입력창에 채워집니다. 빈 입력창에서 / 를 눌러도 열립니다.': 'Pick an item to fill the request into the input. A slash in an empty input opens this tree too.',
    '데이터': 'Data', '기준선': 'Reference lines', '디자인': 'Design', '정리': 'Organize', '기타': 'Other',
    '계열 추가': 'Add a series', '정렬·상위 N': 'Sort and top N', '리포트 삭제': 'Delete report', '평균선 넣기': 'Add an average line',
    '목표선 넣기': 'Add a target line', '기준선 지우기': 'Remove reference lines', '필터 지우기': 'Remove filters',
    '인사이트 다시 쓰기': 'Rewrite the insight', '순서 바꾸기': 'Reorder charts', '대시보드 제목 바꾸기': 'Rename the dashboard',
    '리포트 추가': 'Add report',
    '되돌리기': 'Undo', '직전 변경 되돌리기': 'Undo the last change', '도구': 'tools',
    '기준선 넣기': 'Add a reference line', '차트 종류 바꾸기': 'Change chart type', '값 라벨 표시': 'Show value labels', '상위 5개만': 'Top 5 only',
    '비중 보기': 'Show shares', '색 바꾸기': 'Change colors', '데이터 더 조회': 'Query more data', '제목 바꾸기': 'Rename dashboard',
    '차트를 지웠습니다. 되돌리기로 살릴 수 있습니다.': 'Chart deleted. Undo brings it back.',
    '데이터 조회': 'Query data', '차트 추가': 'Add chart', '차트 수정': 'Edit chart', '기준선 추가': 'Add reference line',
    '기준선 삭제': 'Remove reference line', '디자인 변경': 'Change design', '필터 추가': 'Add filter', '인사이트 작성': 'Write insight',
    '배치 변경': 'Rearrange', '제목 변경': 'Rename title', '대시보드 이름': 'Dashboard name',
    '계산': 'calc', '차트 값': 'Chart values', '계산 값은 조회한 데이터로 시스템이 계산한 값입니다': 'Calculated values are computed by the system from the queried data',
    '안쪽 보기': 'drill down by', '이 데이터에는 더 내려갈 컬럼이 없습니다.': 'This data has no further column to drill into.', '강조 삭제': 'Remove highlight',
    '이 조회는 모양이 복잡해 더 내려갈 수 없습니다': 'This query is too complex to drill into.',
    '이 값 안에서는 더 나눠 볼 컬럼이 없습니다': 'There is no column to break this value down by.',
    '이 데이터의 원본 테이블을 열람할 권한이 없습니다': 'You cannot read the source table of this data.',
    '드릴다운은 3단계까지입니다': 'Drill-down goes up to three levels.', '하위 데이터를 조회하지 못했습니다': 'Could not fetch the next level.', '(빈 값)': '(blank)',
    '계산 값 추가': 'Add calculation', '강조 추가': 'Add highlight', '드릴다운 설정': 'Set drill-down', '계산 값': 'Calculations', '강조': 'Highlights', '드릴다운': 'Drill-down',
    '직전 기간 대비 증감률': 'Change from the previous period', '누계 보기': 'Running total', '구성비 보기': 'Shares', '목표 미달 강조': 'Highlight below target',
    '상위 3개 강조': 'Highlight the top 3', '강조 지우기': 'Remove highlights', '드릴다운 순서 정하기': 'Set the drill-down path',
    '복제': 'Duplicate', '메모 달기': 'Add note', '메모를 달 항목': 'Item to annotate', '메모 내용 (예: 신제품 출시)': 'Note text (e.g. product launch)',
    '메모 내용을 먼저 적어 주세요.': 'Write the note first.', '메모는 차트마다 6개까지 달 수 있습니다.': 'A chart holds up to six notes.', '메모 삭제': 'Remove note',
    '비교 묶음': 'Compare group', '눈금 맞춤': 'shared scale', '비교 묶음에서 빼기': 'Leave the compare group', 'KPI 카드 삭제': 'Remove KPI card',
    '직전 기간 대비': 'vs the previous period', 'KPI 카드': 'KPI card', 'KPI 카드 추가': 'Add KPI card', 'KPI 카드 편집': 'Edit KPI card', 'KPI 카드 넣기': 'Add KPI cards',
    'KPI 카드 지우기': 'Remove KPI cards', '추천 채우기': 'Fill suggestions', 'KPI 카드 순서': 'KPI card order', 'KPI 카드 순서 바꾸기': 'Reorder the KPI cards',
    '요약 숫자': 'Summary numbers', '요약 숫자 추가': 'Add summary number', '요약 숫자 삭제': 'Remove summary number',   // 2026-10-12 전 대화 기록의 도구 이름 / tool names in older traces
    '고정 숫자 카드 넣기': 'Add a fixed-number card', 'KPI 카드 고치기': 'Change a KPI card', '차트를 복제했습니다. 원본과 눈금을 맞춰 나란히 놓았습니다.': 'Chart duplicated and placed beside the original with a shared scale.',
    '리포트 에이전트가 작업 중입니다. 끝난 뒤에 다시 해 주세요.': 'The report agent is working. Try again when it is done.',
    '처음': 'Start', '끝': 'End', '이상': 'Min', '이하': 'Max', '최근 N개는 오늘이 아니라 데이터의 마지막 기간 기준입니다': 'The last N periods count back from the last period in the data, not from today',
    '추세선': 'Trend line', '예측(참고용)': 'Forecast (reference)', '예측 범위': 'Forecast range', '추세·예측': 'Trend and forecast', '추세선·예측': 'Trend and forecast',
    '추세선·예측 지우기': 'Remove the trend line and forecast', '예측은 점이 6개 이상일 때만 그립니다': 'A forecast needs at least six points',
    '추세선 넣기': 'Add a trend line', '앞으로 3개 기간 예측': 'Forecast the next 3 periods', '최근 기간만 보기': 'Show recent periods only',
    '테마': 'Theme', '테마 설정': 'Set theme', '테마 지우기': 'Remove the theme', '회사 색으로 바꾸기': 'Use the company colour',
    '대표 색을 고르면 모든 차트에 한 번에 입힙니다': 'Pick a brand colour to apply it to every chart at once',
    '차트 라이브러리를 불러오지 못했습니다.': 'Could not load the chart library.', '게시판 기능을 불러오지 못했습니다.': 'Could not load the boards feature.',
    '내 보관소에 리포트로 저장했습니다.': 'Saved to my library as a report.', '이 차트를 대시보드에서 지울까요?': 'Delete this chart from the dashboard?',
    '내 보관소에서 삭제할까요? 대화 기록도 함께 지워집니다.': 'Delete from my library? Its conversation is deleted too.',
    '이 메시지의 데이터가 만료되었습니다. 다시 질문해 주세요.': 'The data of this message has expired. Please ask again.',
    // 2026-10-13 디자인 개편: 머리줄 ← · 카드 ⋮ 메뉴 · 펼치기 · 대화 서랍 · 버전 미리보기 / the 2026-10-13 design: back arrow, card menu, expand, conversation drawer, version preview
    '카드 펼치기': 'Expand card', '카드 접기': 'Collapse card', '카드 메뉴': 'Card menu', '그 밖의 작업': 'More actions', '테마 색': 'Theme colour',
    '다시 실행': 'Run again', '다운로드': 'Download', '저장': 'Save', '대화 열기': 'Show conversation', '대화 접기': 'Hide conversation',
    '이 버전으로 이어가기': 'Continue from this version', '미리보기 닫기': 'Close preview', '대시보드 생성': 'Dashboard created', '변경': 'Changed',
    '미리보기 중에는 바꿀 수 없습니다. 이 버전으로 이어가거나 미리보기를 닫아 주세요.': 'Nothing can be changed while previewing. Continue from this version or close the preview.',
    '미리보기 중입니다. 이어가려면 [이 버전으로 이어가기]를 누르세요.': 'Previewing. Press [Continue from this version] to keep editing.',
  };
  if (typeof AI365_KO2EN !== 'undefined' && typeof AI365_EN2KO !== 'undefined') {
    Object.keys(DICT).forEach(function (k) {   // 있는 키와 값은 건드리지 않는다(역방향 사전 보호) / never override existing keys or values
      if (!(k in AI365_KO2EN)) AI365_KO2EN[k] = DICT[k];
      if (!(AI365_KO2EN[k] in AI365_EN2KO)) AI365_EN2KO[AI365_KO2EN[k]] = k;
    });
  }
  function translate(el) {
    if (el && typeof ai365TranslateRoot === 'function' && typeof ai365CurrentLang === 'function') { try { ai365TranslateRoot(el, ai365CurrentLang()); } catch (e) { /* noop */ } }
  }

  const IC = {
    mail: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>',
    board: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9h10M7 13h10M7 17h6"/></svg>',
    folder: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
    x: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
    size: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/></svg>',
    regen: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/></svg>',
    down: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>',
    share: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7"/><path d="m16 6-4-4-4 4"/><path d="M12 2v13"/></svg>',
    save: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M5 3h11l4 4v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M8 3v5h7"/><path d="M8 21v-7h8v7"/></svg>',
    trash: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/></svg>',
    chart: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-7"/><path d="M22 20H2"/></svg>',
    table: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M3 15h18M9 4v16"/></svg>',
    filter: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5h16l-6 8v6l-4-2v-4z"/></svg>',
    caret: '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>',
    tool: '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/></svg>',
    send: '<svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor"><path d="M3.4 20.6 21.6 12 3.4 3.4l2.8 7.2 9.3 1.4-9.3 1.4z"/></svg>',
    pen: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4L19 9l-4-4L4 16z"/></svg>',
    db: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></svg>',
    plus: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
    back: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 6-6 6 6 6"/></svg>',
    check: '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>',
    tree: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="10" width="7" height="5" rx="1.5"/><rect x="14" y="17" width="7" height="4" rx="1.5"/><path d="M6.5 8v10.5a1 1 0 0 0 1 1H14M6.5 12.5H14"/></svg>',
    copy: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg>',
    note: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M5 4h14v11l-5 5H5z"/><path d="M14 20v-5h5"/><path d="M9 9h6M9 13h3"/></svg>',
    scale: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M4 8h13l-3-3"/><path d="M20 16H7l3 3"/></svg>',
    trend: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/></svg>',
    undo: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M9 14 4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/></svg>',
    spark: '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l2.2 6.3L20.5 10l-6.3 2.2L12 18.5l-2.2-6.3L3.5 10l6.3-1.7z"/></svg>',
    // 2026-10-13 디자인: ← · 보관소 · ⋮ · 펼치기/접기 · 버전 · 서랍 손잡이 / the 2026-10-13 design: back, archive, kebab, expand/collapse, version, drawer handle
    arrow: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5"/><path d="m12 19-7-7 7-7"/></svg>',
    archive: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="5" rx="1.5"/><path d="M5 9v9a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9"/><path d="M10 13h4"/></svg>',
    dots: '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="12" cy="19" r="1.8"/></svg>',
    expand: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M9 21H3v-6"/><path d="M21 3l-7 7"/><path d="M3 21l7-7"/></svg>',
    collapse: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 14h6v6"/><path d="M20 10h-6V4"/><path d="M14 10l7-7"/><path d="M3 21l7-7"/></svg>',
    history: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/><path d="M12 7v5l3 2"/></svg>',
    chev: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>',
  };

  (function style() {
    // Figma DS 적용(2026-10-28, docs/figma-design-system-spec.md 6 · 7절, 사용자 지시 "모두 디자인 시스템대로"): 버튼 = DS 코어 직사각 r8
    // (Secondary · Primary · Subtle 아이콘, hover · pressed · selected · disabled 단계), 카드 = DS Card(r8 · 흰 바탕 · Shadow 04 → hover Shadow 08,
    // 선택 = Background 1 selected + Stroke 1 selected), 메뉴 = DS Menu(r12 · 안쪽 4 · Shadow 16, 항목 32 · r6), 대화 상자 = DS Dialog(r16 · 안쪽 24 ·
    // Shadow 64 · 제목 Subtitle 1 · CTA 36 알약), 입력칸 = DS Outline 입력(흰 바탕 · Stroke 1 · 아래 Stroke accessible · r8, 포커스 = 아래 2px 브랜드),
    // 알약 토글 = DS Subtle circular 탭, 표 = DS DataGrid(머리 채움 없음 · 구분선 · 바깥 선 없음), 인사이트 = DS 메시지 바(정보), 상태 색 = DS 램프,
    // 대화 입력줄 = 제품 시트 입력 카드(r24 · Stroke 2 · Shadow 12, 도구 알약 · 보내기 원 40), 글자 = DS 글자 단계(500 → 400, 800 → 700).
    // 차트 색상 팔레트 · 캔버스 그리기 색 · KPI 증감 · 추세선/메모/범례 같은 데이터 색은 그대로. 이 파일은 단독 페이지(테스트)에서도 돌므로
    // 모든 DS 토큰에 adapter.js ai365DsTokens 와 같은 값을 기본값으로 함께 적는다.
    // Figma DS applied (2026-10-28, sections 6 and 7 of docs/figma-design-system-spec.md; the user's "apply the design system everywhere"):
    // DS core r8 buttons (Secondary, Primary, Subtle icon; hover, pressed, selected and disabled steps), DS Cards (r8, white, Shadow 04 →
    // hover Shadow 08; selected = Background 1 selected + Stroke 1 selected), DS Menus (r12, 4 padding, Shadow 16; 32px r6 items), DS Dialogs
    // (r16, 24 padding, Shadow 64, Subtitle 1 title, 36px pill CTAs), DS Outline inputs (white, Stroke 1, a Stroke accessible bottom, r8;
    // focus = a 2px brand bottom line), DS Subtle circular tabs for pill toggles, DS DataGrid tables (no header fill, rules only, no outer
    // stroke), the insight as a DS message bar (info), DS status ramps, the chat input row as the product-sheet composer (r24, Stroke 2,
    // Shadow 12; a tools pill and a 40px round send) and the DS type ramp (500 → 400, 800 → 700). Data colours (chart palettes, canvas drawing
    // colours, KPI deltas, trend/note/legend markers) stay. This file also runs on standalone pages (tests), so every DS token carries the
    // adapter.js ai365DsTokens value as its fallback.
    const D = function (name, value) { return 'var(--ds-' + name + ',' + value + ')'; };
    const FONT = '"Pretendard",-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR","Segoe UI",sans-serif';
    const TY = function (role, w, size) { return D('type-' + role, w + ' ' + size + ' ' + FONT); };
    const FG1 = D('fg-1', '#21242C'), FG2 = D('fg-2', '#3E424B'), FG3 = D('fg-3', '#5D616A'), FG4 = D('fg-4', '#6C707A'), FG_DIS = D('fg-disabled', '#B9BDC8');
    const FG_ON = D('fg-on-brand', '#FFFFFF'), FG_BRAND = D('fg-brand-1', '#4450CE'), FG_LINK = D('fg-link', '#3940BD');
    const FGB2 = D('fg-brand-2', '#3940BD'), FGB2_H = D('fg-brand-2-hover', '#2E2FAC'), FGB2_P = D('fg-brand-2-pressed', '#160076');
    const FG2_H = D('fg-2-hover', '#21242C'), FG2_BH = D('fg-2-brand-hover', '#4450CE'), FG2_BP = D('fg-2-brand-pressed', '#3940BD'), FG2_BS = D('fg-2-brand-selected', '#4450CE');
    const BG1 = D('bg-1', '#FFFFFF'), BG1_H = D('bg-1-hover', '#F6F8FD'), BG1_P = D('bg-1-pressed', '#DCE0EB'), BG1_S = D('bg-1-selected', '#E7EBF6');
    const BG2 = D('bg-2', '#FAFCFF'), BG2_H = D('bg-2-hover', '#EFF2FA'), BG3 = D('bg-3', '#F6F8FD'), BG3_H = D('bg-3-hover', '#E7EBF6'), BG4 = D('bg-4', '#EFF2FA');
    const BG4_H = D('bg-4-hover', '#FAFCFF'), BG_DIS = D('bg-disabled', '#EFF2FA');
    const SUB_H = D('subtle-bg-hover', '#F6F8FD'), SUB_P = D('subtle-bg-pressed', '#DCE0EB'), SUB_S = D('subtle-bg-selected', '#E7EBF6');
    const BRAND = D('brand-bg', '#4450CE'), BRAND_H = D('brand-bg-hover', '#3940BD'), BRAND_P = D('brand-bg-pressed', '#1D008B');
    const BRAND2 = D('brand-bg-2', '#E4EDFF'), BRAND2_H = D('brand-bg-2-hover', '#CCDAFF'), BRAND2_P = D('brand-bg-2-pressed', '#9CB1FF');
    const CB = D('compound-brand', '#4450CE'), CB_H = D('compound-brand-hover', '#3940BD'), CB_P = D('compound-brand-pressed', '#2E2FAC');
    const B110 = D('brand-110', '#7186FF'), B170 = D('brand-170', '#F2F6FF'), BSTROKE2 = D('brand-stroke-2', '#B4C6FF');
    const ST1 = D('stroke-1', '#CDD1DC'), ST1_H = D('stroke-1-hover', '#C3C7D2'), ST1_P = D('stroke-1-pressed', '#AFB3BE'), ST1_S = D('stroke-1-selected', '#B9BDC8');
    const ST2 = D('stroke-2', '#DCE0EB'), ACC = D('stroke-accessible', '#5D616A'), ACC_H = D('stroke-accessible-hover', '#535760'), ACC_P = D('stroke-accessible-pressed', '#494D56');
    const ST_DIS = D('stroke-disabled', '#DCE0EB');
    const OK = D('success-fg-1', '#0E700E'), OK_BG = D('success-bg-1', '#F1FAF1'), OK_FILL = D('success-bg-3', '#359B35'), OK_BD = D('success-border-1', '#9FD89F');
    const WARN_FG = D('warning-fg-2', '#8A3707'), WARN_FILL = D('warning-bg-3', '#F87528');
    const BAD = D('danger-fg-1', '#C50F1F'), BAD_BG = D('danger-bg-1', '#FDF3F4'), BAD_BG2 = D('danger-bg-2', '#EEACB2'), BAD_BD = D('danger-border-1', '#EEACB2');
    const INFO_BG = D('info-bg', '#F6F8FD'), INFO_BD = D('info-border', '#CDD1DC');
    const SH4 = D('shadow-4', '0 0 2px #1513520F, 0 2px 4px #15135224'), SH8 = D('shadow-8', '0 0 2px #1513520F, 0 4px 8px #15135224');
    const SH12 = D('shadow-12', '0 0 2px #15135208, 0 8px 16px #15135214'), SH16 = D('shadow-16', '0 0 2px #1513520F, 0 8px 16px #15135224');
    const SH64 = D('shadow-64', '0 0 8px #1513521F, 0 32px 64px #1513523D'), RING = D('focus-ring', '0 0 0 1px #FFFFFF, 0 0 0 3px #000000');
    const R_BTN = D('radius-button', '8px'), R_IN = D('radius-input', '8px'), R_CARD = D('radius-card', '8px'), R_TAG = D('radius-tag', '8px'), R_LIST = D('radius-listbox', '8px');
    const R_MENU = D('radius-menu', '12px'), R_ITEM = D('radius-menu-item', '6px'), R_BADGE = D('radius-badge', '4px'), R_DLG = D('radius-dialog', '16px'), R_MB = D('radius-message-bar', '8px');
    const R_TOAST = D('radius-toast', '8px'), R_CHK = D('radius-checkbox', '2px'), R_COMP = D('radius-composer', '24px'), R4 = D('radius-4', '4px'), R8 = D('radius-8', '8px');
    const R12 = D('radius-12', '12px'), R_FULL = D('radius-full', '9999px');
    const CAP2S = TY('caption-2-strong', 600, '10px/14px'), CAP1 = TY('caption-1', 400, '12px/16px'), CAP1S = TY('caption-1-strong', 600, '12px/16px');
    const B1 = TY('body-1', 400, '14px/20px'), B1S = TY('body-1-strong', 600, '14px/20px'), B2 = TY('body-2', 400, '16px/22px'), SUB2 = TY('subtitle-2', 600, '16px/22px');
    const SUB1 = TY('subtitle-1', 600, '20px/28px'), LT = TY('large-title', 600, '40px/56px');
    // 셀렉트 화살표(색 = NeutralForeground3 #5D616A) / the select arrow (colour = NeutralForeground3)
    const CHEV = 'url("data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 width=%2712%27 height=%2712%27 viewBox=%270 0 24 24%27 fill=%27none%27 stroke=%27%235D616A%27 stroke-width=%272.4%27 stroke-linecap=%27round%27 stroke-linejoin=%27round%27%3E%3Cpath d=%27m6 9 6 6 6-6%27/%3E%3C/svg%3E")';
    // 체크 표시(흰색) / the check mark (white)
    const CHECK = 'url("data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 12 12%27 fill=%27none%27 stroke=%27white%27 stroke-width=%271.6%27 stroke-linecap=%27round%27 stroke-linejoin=%27round%27%3E%3Cpath d=%27m2.5 6.2 2.3 2.3 4.7-4.9%27/%3E%3C/svg%3E")';
    // DS Outline 입력칸(32 · r8 · 흰 바탕 · 옆선 Stroke 1 · 아래선 Stroke accessible), 포커스 = 아래 2px 브랜드 막대 / the DS Outline input; focus = a 2px brand bottom bar
    const FILL = 'border:1px solid ' + ST1 + ';border-bottom-color:' + ACC + ';border-radius:' + R_IN + ';background-color:' + BG1 + ';outline:none;';
    const FOCUS = 'border-bottom-color:' + CB + ';box-shadow:inset 0 -1px 0 ' + CB + ';';
    // DS 체크박스(16 · r2 · 1px Stroke accessible, 켜짐 = 브랜드 채움 + 흰 체크) / the DS checkbox (16, r2, a 1px Stroke accessible; on = brand fill and a white check)
    const CHK = 'appearance:none;-webkit-appearance:none;flex:none;width:16px;height:16px;margin:0;border:1px solid ' + ACC + ';border-radius:' + R_CHK + ';background:' + BG1 + ' center/12px no-repeat;cursor:pointer;';
    const CHK_ON = 'background-color:' + CB + ';background-image:' + CHECK + ';border-color:' + CB + ';';
    const s = document.createElement('style');
    s.textContent = [
      '.artifact-panel.open.ai365-rd-mode{width:100%;}',   /* 2026-10-13 디자인: 작업 공간이 채팅 영역 전체를 쓴다(← 로 돌아간다) / the workspace takes the whole chat area; ← goes back */
      '.artifact-panel.ai365-rd-mode .artifact-head{display:none;}',
      '.artifact-panel.ai365-rd-mode .artifact-body{padding:0;overflow:hidden;display:flex;flex-direction:column;min-width:0;}',
      // 답변의 [대시보드 열기] = 제품 시트 답변 카드 동작(알약 32 · 브랜드 · Body 1 Strong) / the answer's open button = the product sheet's answer-card action (a 32px brand pill)
      '.ai365-rd-go{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:32px;min-width:96px;margin:4px 0 12px;padding:6px 12px;font:' + B1S + ';color:' + FG_ON + ';background:' + BRAND + ';border:0;border-radius:' + R_FULL + ';cursor:pointer;transition:background .12s;}',
      '.ai365-rd-go:hover{background:' + BRAND_H + ';}',
      '.ai365-rd-go:active{background:' + BRAND_P + ';}',
      '.toast{z-index:1400 !important;}',
      '#ai365RdOv{position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.5);display:none;padding:22px;}',
      '#ai365RdOv.show{display:flex;}',
      '#ai365RdOv .ai365-rd-ovbox{flex:1;min-width:0;background:' + BG1 + ';border-radius:' + R_DLG + ';overflow:hidden;display:flex;flex-direction:column;box-shadow:' + SH64 + ';}',
      '.ai365-rd{position:relative;flex:1;min-height:0;display:flex;flex-direction:column;background:' + BG1 + ';color:' + FG1 + ';font:' + B1 + ';}',
      '.ai365-rd button{font-family:inherit;}',
      // 포커스 = DS(Fluent) 링(입력칸은 아래 2px 브랜드 막대가 포커스 표시) / focus = the DS (Fluent) ring (inputs show focus with the 2px brand bottom bar)
      '.ai365-rd :is(button,[tabindex]):focus-visible{outline:none;box-shadow:' + RING + ';}',
      // 머리줄(제품 시트 Header: 제목 Subtitle 2) / the header (product-sheet Header: a Subtitle 2 title)
      '.ai365-rd-hd{display:flex;align-items:center;gap:8px;padding:10px 16px 10px 12px;background:' + BG1 + ';border-bottom:1px solid ' + ST2 + ';}',
      '.ai365-rd-back{width:32px;height:32px;border-radius:' + R_BTN + ';border:0;background:none;color:' + FG2 + ';display:inline-flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;transition:background .12s,color .12s;}',
      '.ai365-rd-back:hover{background:' + SUB_H + ';color:' + FG2_BH + ';}',
      '.ai365-rd-back:active{background:' + SUB_P + ';color:' + FG2_BP + ';}',
      '.ai365-rd-hd .t{font:' + SUB2 + ';color:' + FG1 + ';}',
      '.ai365-rd-hd .sp{flex:1;}',
      // 머리줄 버튼 = DS Secondary 버튼 M(r8), .on = 선택, .pri = Primary / header buttons = DS Secondary buttons M (r8); .on = selected, .pri = Primary
      '.ai365-rd-hbtn{display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 12px;font:' + B1S + ';color:' + FG1 + ';background:' + BG1 + ';border:1px solid ' + ST1 + ';border-radius:' + R_BTN + ';cursor:pointer;transition:background .12s,border-color .12s,color .12s;}',
      '.ai365-rd-hbtn:hover:not(:disabled){background:' + BG1_H + ';border-color:' + ST1_H + ';}',
      '.ai365-rd-hbtn:active:not(:disabled){background:' + BG1_P + ';border-color:' + ST1_P + ';}',
      '.ai365-rd-hbtn.on{background:' + BG1_S + ';border-color:' + ST1_S + ';color:' + FG1 + ';}',
      /* 저장 상태·[저장]·닫기 확인(2026-09-22 명시 저장) / save state, [Save] and the close confirmation (explicit save) */
      '.ai365-rd-hbtn.pri{min-width:96px;background:' + BRAND + ';border-color:transparent;color:' + FG_ON + ';}',
      '.ai365-rd-hbtn.pri:hover:not(:disabled){background:' + BRAND_H + ';border-color:transparent;color:' + FG_ON + ';}',
      '.ai365-rd-hbtn.pri:active:not(:disabled){background:' + BRAND_P + ';border-color:transparent;}',
      '.ai365-rd-hbtn:disabled{cursor:default;background:' + BG_DIS + ';border-color:' + ST_DIS + ';color:' + FG_DIS + ';}',
      '.ai365-rd-hbtn.pri:disabled{background:' + BG_DIS + ';border-color:transparent;color:' + FG_DIS + ';}',
      '.ai365-rd-sst{display:inline-flex;align-items:center;gap:6px;font:' + CAP1 + ';color:' + FG3 + ';white-space:nowrap;}',
      '.ai365-rd-sst::before{content:"";width:8px;height:8px;border-radius:50%;background:' + ST1 + ';flex:none;}',
      '.ai365-rd-sst.ok::before{background:' + OK_FILL + ';}',
      '.ai365-rd-sst.dirty{color:' + WARN_FG + ';font-weight:600;}',
      '.ai365-rd-sst.dirty::before{background:' + WARN_FILL + ';}',
      // 닫기 확인 = DS Dialog(600 · r16 · 안쪽 24 · Shadow 64, 제목 Subtitle 1, 본문 Body 1, CTA 36 알약) / the close confirmation is a DS Dialog
      '.ai365-rd-ask{position:absolute;inset:0;z-index:6;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;padding:20px;}',
      '.ai365-rd-askbox{background:' + BG1 + ';border-radius:' + R_DLG + ';padding:24px;max-width:600px;width:100%;box-shadow:' + SH64 + ';display:flex;flex-direction:column;gap:8px;}',
      '.ai365-rd-askbox b{font:' + SUB1 + ';color:' + FG1 + ';margin-bottom:8px;}',
      '.ai365-rd-askbox span{font:' + B1 + ';color:' + FG1 + ';}',
      '.ai365-rd-askbox .r{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;margin-top:12px;}',
      '.ai365-rd-askbox .r .ai365-rd-btn,.ai365-rd-kdlg .ft .ai365-rd-btn{height:36px;border-radius:' + R_FULL + ';padding:0 16px;font:' + SUB2 + ';}',
      // 닫기 X = DS Subtle 아이콘 버튼 M(32 · r8) / the close X = a DS Subtle icon button M (32, r8)
      '.ai365-rd-x{width:32px;height:32px;border-radius:' + R_BTN + ';border:0;background:none;color:' + FG2 + ';display:flex;align-items:center;justify-content:center;cursor:pointer;}',
      '.ai365-rd-x:hover{background:' + SUB_H + ';color:' + FG2_BH + ';}',
      '.ai365-rd-x:active{background:' + SUB_P + ';color:' + FG2_BP + ';}',
      '@keyframes ai365RdPop{0%{background:' + B170 + ';}100%{background:transparent;}}',
      '.ai365-rd-scroll{flex:1;min-height:0;overflow:auto;padding:16px 20px 20px;container-type:inline-size;background:' + BG3 + ';}',
      /* 2026-10-13 디자인: 대시보드 영역 + 대화 서랍(손잡이로 여닫음) + 버전 미리보기 막대 / dashboard area, conversation drawer (handle) and version preview bar */
      '.ai365-rd-main{flex:1;min-height:0;display:flex;flex-direction:column;position:relative;}',
      '.ai365-rd-dash{flex:1;min-height:0;display:flex;flex-direction:column;position:relative;}',
      '.ai365-rd-main.chat-open .ai365-rd-dash{flex:0 0 46%;}',
      '.ai365-rd-handle{position:relative;height:0;z-index:3;}',
      '.ai365-rd-handle[hidden]{display:none;}',
      '.ai365-rd-handle .pill{position:absolute;left:50%;top:-12px;transform:translateX(-50%);width:40px;height:24px;border-radius:' + R_FULL + ';border:1px solid ' + ST1 + ';background:' + BG1 + ';color:' + FG2 + ';display:inline-flex;align-items:center;justify-content:center;cursor:pointer;padding:0;box-shadow:' + SH4 + ';}',
      '.ai365-rd-handle .pill:hover{color:' + FG2_BH + ';border-color:' + ST1_H + ';background:' + BG1_H + ';}',
      '.ai365-rd-handle .pill:active{color:' + FG2_BP + ';border-color:' + ST1_P + ';background:' + BG1_P + ';}',
      '.ai365-rd-handle .pill svg{transform:rotate(180deg);transition:transform .14s;}',
      '.ai365-rd-main.chat-open .ai365-rd-handle .pill svg{transform:none;}',
      '.ai365-rd-chat{flex:1;min-height:0;overflow:auto;background:' + BG1 + ';border-top:1px solid ' + ST2 + ';padding:20px 20px 12px;display:flex;flex-direction:column;gap:12px;}',
      '.ai365-rd-chat[hidden]{display:none;}',
      // 버전 칩 = 누르는 작은 카드(Background 2 · 1px Stroke 2 · r8 → hover Background 2 hover, 보는 중 = 선택 단계) / the version chip is a small clickable card
      '.ai365-rd-ver{display:flex;align-items:center;gap:10px;width:100%;margin-top:10px;border:1px solid ' + ST2 + ';border-radius:' + R_CARD + ';padding:8px 12px;background:' + BG2 + ';font:' + CAP1 + ';color:' + FG2 + ';cursor:pointer;text-align:left;box-sizing:border-box;transition:border-color .12s,background .12s;}',
      '.ai365-rd-ver:hover{border-color:' + ST1_H + ';background:' + BG2_H + ';}',
      '.ai365-rd-ver:active{background:' + BG1_P + ';}',
      '.ai365-rd-ver.on{border-color:' + ST1_S + ';background:' + BG1_S + ';}',
      '.ai365-rd-ver svg{color:' + FG3 + ';flex:none;}',
      '.ai365-rd-ver .vn{font-weight:600;color:' + FG1 + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
      '.ai365-rd-ver .sep{width:1px;height:14px;background:' + ST2 + ';flex:none;}',
      '.ai365-rd-ver .at{color:' + FG3 + ';white-space:nowrap;font-variant-numeric:tabular-nums;}',
      // 미리보기 막대 = 떠 있는 DS 토스트 모양(흰 바탕 · r8 · Shadow 16) + Primary 버튼 M · Subtle 아이콘 버튼 / the preview bar floats like a DS toast
      '.ai365-rd-pvbar{position:absolute;left:50%;bottom:16px;transform:translateX(-50%);z-index:4;display:flex;align-items:center;gap:10px;max-width:calc(100% - 40px);box-sizing:border-box;background:' + BG1 + ';border:0;border-radius:' + R_TOAST + ';box-shadow:' + SH16 + ';padding:6px 6px 6px 12px;font:' + B1 + ';color:' + FG1 + ';}',
      '.ai365-rd-pvbar>svg{color:' + FG3 + ';flex:none;}',
      '.ai365-rd-pvbar .lb{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-rd-pvbar .go{height:32px;padding:0 12px;border:0;border-radius:' + R_BTN + ';background:' + BRAND + ';color:' + FG_ON + ';font:' + B1S + ';cursor:pointer;white-space:nowrap;}',
      '.ai365-rd-pvbar .go:hover:not(:disabled){background:' + BRAND_H + ';}',
      '.ai365-rd-pvbar .go:active:not(:disabled){background:' + BRAND_P + ';}',
      '.ai365-rd-pvbar .go:disabled{background:' + BG_DIS + ';color:' + FG_DIS + ';cursor:default;}',
      '.ai365-rd-pvbar .x{width:32px;height:32px;border:0;background:none;border-radius:' + R_BTN + ';color:' + FG2 + ';display:inline-flex;align-items:center;justify-content:center;cursor:pointer;padding:0;}',
      '.ai365-rd-pvbar .x:hover{background:' + SUB_H + ';color:' + FG2_BH + ';}',
      '.ai365-rd-pvbar .x:active{background:' + SUB_P + ';color:' + FG2_BP + ';}',
      '.ai365-rd-top{display:flex;align-items:center;gap:4px;margin-bottom:16px;min-height:32px;}',
      '.ai365-rd-top h2{font:' + SUB2 + ';color:' + FG1 + ';margin:0;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-rd-top .st{font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-rd-top .sp{flex:1;}',
      // 아이콘 버튼 = DS Subtle 아이콘 버튼 M(32 · r8, hover · pressed = 아이콘 브랜드, 비활성 = Foreground disabled) / icon buttons = DS Subtle icon buttons M
      '.ai365-rd-ib{width:32px;height:32px;border-radius:' + R_BTN + ';border:0;background:none;color:' + FG2 + ';display:inline-flex;align-items:center;justify-content:center;cursor:pointer;transition:background .12s,color .12s;flex-shrink:0;}',
      '.ai365-rd-ib.dirty{position:relative;}',   /* 저장하지 않은 변경 = 저장 아이콘의 경고 점(설명은 title) / unsaved changes = a warning dot on the save icon (the title tells) */
      '.ai365-rd-ib.dirty::after{content:"";position:absolute;top:5px;right:5px;width:8px;height:8px;border-radius:50%;background:' + WARN_FILL + ';box-shadow:0 0 0 2px ' + BG1 + ';}',
      '.ai365-rd-ib:hover:not(:disabled){background:' + SUB_H + ';color:' + FG2_BH + ';}',
      '.ai365-rd-ib:active:not(:disabled){background:' + SUB_P + ';color:' + FG2_BP + ';}',
      '.ai365-rd-ib:disabled{color:' + FG_DIS + ';cursor:default;}',
      '.ai365-rd-ib.danger:hover:not(:disabled){background:' + BAD_BG + ';color:' + BAD + ';}',
      '.ai365-rd-cf{display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding:8px 12px 0;}',
      '.ai365-rd-cf[hidden]{display:none;}',
      '.ai365-rd-cf>.lb{display:inline-flex;color:' + FG3 + ';}',
      '.ai365-rd-cf .ai365-rd-fp{height:24px;font:' + CAP1 + ';padding:0 4px 0 8px;}',
      // [+ 필터] = DS Transparent 버튼 S(글자 → hover 브랜드) / [+ Filter] = a DS Transparent button S (text turns brand on hover)
      '.ai365-rd-fadd{display:inline-flex;align-items:center;gap:4px;height:24px;font:' + CAP1 + ';color:' + FG2 + ';background:none;border:0;border-radius:' + R_BTN + ';padding:0 8px;cursor:pointer;}',
      '.ai365-rd-fadd:hover{color:' + FG2_BH + ';background:' + SUB_H + ';}',
      '.ai365-rd-fadd.open{color:' + FG2_BS + ';background:' + SUB_S + ';}',
      '.ai365-rd-fadd svg{width:12px;height:12px;}',
      '.ai365-rd-colmenu .cap{font:' + CAP1S + ';color:' + FG3 + ';padding:6px 6px 4px;}',
      '.ai365-rd-colmenu .vals button{display:block;width:100%;min-height:32px;text-align:left;font:' + B1 + ';color:' + FG2 + ';background:none;border:0;border-radius:' + R_ITEM + ';padding:6px;cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-rd-colmenu .vals button:hover{background:' + SUB_H + ';color:' + FG2_H + ';}',
      '.ai365-rd-colmenu .vals button:active{background:' + SUB_P + ';}',
      // 대상 표시 = DS Badge M 20 · r4 브랜드 채움 / the target mark = a DS Badge M 20, r4, brand filled
      '.ai365-rd-tgt{display:none;font:' + CAP2S + ';color:' + FG_ON + ';background:' + BRAND + ';border-radius:' + R_BADGE + ';padding:3px 6px;flex-shrink:0;margin-right:2px;}',
      '.ai365-rd-card.focus .ai365-rd-tgt{display:inline-block;}',
      '.ai365-rd-nodata{height:180px;display:flex;align-items:center;justify-content:center;font:' + CAP1 + ';color:' + FG3 + ';border:1px dashed ' + ST1 + ';border-radius:' + R8 + ';}',
      '.ai365-rd-btn.sm{height:24px;padding:0 8px;font:' + CAP1 + ';flex-shrink:0;}',
      '.ai365-rd-sqlpre{background:' + BG3 + ';border:1px solid ' + ST2 + ';border-radius:' + R8 + ';padding:10px 12px;margin:8px 0 10px;font:' + CAP1 + ';white-space:pre-wrap;word-break:break-all;color:' + FG2 + ';}',
      'span.ai365-rd-ref{cursor:default;}',
      '.ai365-rd-btn.on{border-color:' + ST1_S + ';color:' + FG1 + ';background:' + BG1_S + ';}',
      '.ai365-rd-btn:disabled{cursor:default;background:' + BG_DIS + ';border-color:' + ST_DIS + ';color:' + FG_DIS + ';}',
      '.ai365-rd-f{position:relative;}',
      // 필터 알약 = DS Subtle circular 탭 M 32(비선택 투명 → hover 중립 바탕 + 선, 걸린 필터 = Brand background 2 + 1px 브랜드 + Brand foreground 2)
      // filter pills = DS Subtle circular tabs M 32 (unselected transparent → hover neutral ground and stroke; an applied filter = Brand background 2, a 1px brand stroke, Brand foreground 2)
      '.ai365-rd-fp{display:inline-flex;align-items:center;gap:6px;height:32px;font:' + B1 + ';color:' + FG2 + ';background:transparent;border:1px solid transparent;border-radius:' + R_FULL + ';padding:0 6px 0 12px;cursor:pointer;transition:border-color .12s,background .12s;}',
      '.ai365-rd-fp:hover,.ai365-rd-fp.open{background:' + BG1_H + ';border-color:' + ST1_H + ';color:' + FG2_H + ';}',
      '.ai365-rd-fp.act{background:' + BRAND2 + ';border-color:' + CB + ';color:' + FGB2 + ';font-weight:600;}',
      '.ai365-rd-fp.act:hover,.ai365-rd-fp.act.open{background:' + BRAND2_H + ';border-color:' + CB_H + ';color:' + FGB2_H + ';}',
      '.ai365-rd-fp .v{font-weight:600;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      // 필터 지우기 = 태그 닫기 아이콘(hover 브랜드) / the clear button = a tag dismiss icon (brand on hover)
      '.ai365-rd-fp .rm{width:16px;height:16px;border-radius:' + R4 + ';display:inline-flex;align-items:center;justify-content:center;color:' + FG3 + ';}',
      '.ai365-rd-fp .rm:hover{background:' + BRAND2_H + ';color:' + CB + ';}',
      '.ai365-rd-fp .rm svg{width:10px;height:10px;}',
      /* 메뉴(공유 · 더보기 · 카드 ⋮) = DS Menu(r12 · 안쪽 4 · Shadow 16, 항목 32 · r6 · Body 1 Foreground 2 → hover Foreground 1, 구분선 전폭) / menus = DS Menu */
      '.ai365-rd-chd .tools,.ai365-rd-top{position:relative;}',
      '.ai365-rd-smenu{position:absolute;top:calc(100% + 4px);right:0;z-index:31;min-width:180px;background:' + BG1 + ';border:0;border-radius:' + R_MENU + ';box-shadow:' + SH16 + ';padding:4px;display:flex;flex-direction:column;gap:2px;opacity:1;}',
      '.ai365-rd-smenu button{display:flex;align-items:center;gap:8px;width:100%;min-height:32px;padding:6px;border:0;background:none;border-radius:' + R_ITEM + ';font:' + B1 + ';color:' + FG2 + ';cursor:pointer;text-align:left;white-space:nowrap;}',
      '.ai365-rd-smenu button:disabled{color:' + FG_DIS + ';cursor:default;}',
      '.ai365-rd-smenu button:disabled:hover{background:none;color:' + FG_DIS + ';}',
      '.ai365-rd-smenu button:disabled:hover svg,.ai365-rd-smenu button:disabled svg{color:' + FG_DIS + ';}',
      '.ai365-rd-smenu button.danger:hover{background:' + BAD_BG + ';color:' + BAD + ';}',
      '.ai365-rd-smenu button.danger:hover svg{color:' + BAD + ';}',
      '.ai365-rd-smenu .hr{height:1px;background:' + ST2 + ';margin:2px -4px;}',
      '.ai365-rd-cmenu{min-width:180px;}',
      '.ai365-rd-smenu button svg{flex:none;color:' + FG2 + ';}',
      '.ai365-rd-smenu button:hover{background:' + SUB_H + ';color:' + FG2_H + ';}',
      '.ai365-rd-smenu button:active{background:' + SUB_P + ';}',
      '.ai365-rd-smenu button:hover svg{color:' + FG2_H + ';}',
      // 필터 값 목록 = DS Dropdown 목록(r8 · 안쪽 4 · Shadow 16), 검색 = DS SearchBox(Background 4), 체크 = DS 체크박스 / the filter value list = a DS Dropdown listbox
      '.ai365-rd-fmenu{position:absolute;top:calc(100% + 4px);left:0;z-index:30;min-width:220px;max-width:300px;background:' + BG1 + ';border:0;border-radius:' + R_LIST + ';box-shadow:' + SH16 + ';padding:4px;}',
      '.ai365-rd-fmenu input[type=search]{width:100%;box-sizing:border-box;height:32px;border:0;border-radius:' + R_IN + ';background-color:' + BG4 + ';outline:none;padding:0 10px;font:' + B1 + ';color:' + FG1 + ';margin-bottom:4px;}',
      '.ai365-rd-fmenu input[type=search]:hover{background-color:' + BG4_H + ';}',
      '.ai365-rd-fmenu input[type=search]:focus{box-shadow:inset 0 -2px 0 ' + CB + ';}',
      '.ai365-rd-fmenu input[type=search]::placeholder{color:' + FG4 + ';}',
      '.ai365-rd-fmenu input[type=checkbox]{' + CHK + '}',
      '.ai365-rd-fmenu input[type=checkbox]:hover{border-color:' + ACC_H + ';}',
      '.ai365-rd-fmenu input[type=checkbox]:checked{' + CHK_ON + '}',
      '.ai365-rd-fmenu .ops{display:flex;gap:4px;margin-bottom:4px;}',
      '.ai365-rd-fmenu .ops button{height:24px;font:' + CAP1S + ';color:' + CB + ';background:none;border:0;padding:0 8px;border-radius:' + R_BTN + ';cursor:pointer;}',
      '.ai365-rd-fmenu .ops button:hover{background:' + SUB_H + ';color:' + CB_H + ';}',
      '.ai365-rd-fmenu .ops button:active{background:' + SUB_P + ';color:' + CB_P + ';}',
      '.ai365-rd-fmenu .vals{max-height:230px;overflow:auto;display:flex;flex-direction:column;gap:2px;}',
      '.ai365-rd-fmenu label{display:flex;align-items:center;gap:8px;min-height:32px;font:' + B1 + ';padding:6px 8px;border-radius:' + R_ITEM + ';cursor:pointer;color:' + FG1 + ';}',
      '.ai365-rd-fmenu label:hover{background:' + SUB_H + ';}',
      '.ai365-rd-fmenu label span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-rd-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:16px;}',   /* 넓으면 3열(디자인), 좁아지면 2열 · 1열 / three columns when wide, then two, then one */
      '@container (max-width:780px){.ai365-rd-grid{grid-template-columns:minmax(0,1fr);}}',
      // 카드 = DS Card(r8 · 흰 바탕 · Shadow 04 → hover Shadow 08), 고른 카드 = DS 선택 단계(Background 1 selected + 1px Stroke 1 selected) / cards = DS Cards; the focused card = the DS selected step
      '.ai365-rd-card{background:' + BG1 + ';border:1px solid transparent;border-radius:' + R_CARD + ';box-shadow:' + SH4 + ';display:flex;flex-direction:column;min-width:0;transition:box-shadow .16s,border-color .16s,background .16s;position:relative;}',
      '.ai365-rd-card.full,.ai365-rd-card.expanded,.ai365-rd-grid>.ai365-rd-card:only-child{grid-column:1/-1;}',
      '.ai365-rd-card:hover{box-shadow:' + SH8 + ';}',
      '.ai365-rd-card.focus{background:' + BG1_S + ';border-color:' + ST1_S + ';box-shadow:' + SH8 + ';}',
      '.ai365-rd-card.flash{animation:ai365RdFlash 1.4s ease;}',
      '@keyframes ai365RdFlash{0%,40%{box-shadow:0 0 0 3px ' + B110 + ';}100%{box-shadow:0 0 0 0 transparent;}}',
      '.ai365-rd-chd{display:flex;align-items:center;gap:4px;padding:12px 8px 0 12px;}',
      '.ai365-rd-chd b{flex:1;min-width:0;font:' + B1S + ';color:' + FG1 + ';overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-rd-chd .tools{display:flex;gap:2px;flex-shrink:0;}',
      '.ai365-rd-card:hover .tools,.ai365-rd-card.focus .tools{opacity:1;}',
      '.ai365-rd-sub{font:' + CAP1 + ';color:' + FG3 + ';padding:2px 12px 0;}',
      '.ai365-rd-cbody{padding:12px 12px 0;cursor:pointer;}',
      '.ai365-rd-canvas{position:relative;height:220px;}',
      '.ai365-rd-card.full .ai365-rd-canvas,.ai365-rd-card.expanded .ai365-rd-canvas,.ai365-rd-grid>.ai365-rd-card:only-child .ai365-rd-canvas{height:340px;}',
      '.ai365-rd-kpi{height:180px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;}',
      '.ai365-rd-kpi .v{font:' + LT + ';color:' + FG_BRAND + ';font-variant-numeric:tabular-nums;}',
      '.ai365-rd-kpi .l{font:' + B1S + ';color:' + FG2 + ';}',
      '.ai365-rd-kpi .s{font:' + CAP1 + ';color:' + FG3 + ';}',
      // 인사이트 = DS 메시지 바(정보: Background 3 · 1px info 선 · r8) / the insight = a DS message bar (info)
      '.ai365-rd-ins{margin:12px 0 0;font:' + B1 + ';color:' + FG1 + ';background:' + INFO_BG + ';border:1px solid ' + INFO_BD + ';border-radius:' + R_MB + ';padding:8px 12px;}',
      '.ai365-rd-ins b{display:block;font:' + CAP1S + ';color:' + FG1 + ';margin:0 0 2px;}',
      /* 발치 [차트 종류 | Table] = DS Subtle circular 탭 M 32 / the footer [type | Table] = DS Subtle circular tabs M 32 */
      '.ai365-rd-cft{display:inline-flex;align-self:flex-start;align-items:center;gap:4px;margin:12px 12px 12px;padding:0;border:0;border-radius:0;background:transparent;}',
      '.ai365-rd-cft:empty{display:none;}',
      '.ai365-rd-vt{display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 12px;font:' + B1 + ';color:' + FG2 + ';background:transparent;border:1px solid transparent;border-radius:' + R_FULL + ';cursor:pointer;transition:background .12s,color .12s,border-color .12s;}',
      '.ai365-rd-vt:hover{background:' + BG1_H + ';border-color:' + ST1_H + ';color:' + FG2_H + ';}',
      '.ai365-rd-vt:active{background:' + BG1_P + ';border-color:' + ST1_P + ';}',
      '.ai365-rd-vt.on{color:' + FGB2 + ';background:' + BRAND2 + ';border-color:' + CB + ';font-weight:600;}',
      '.ai365-rd-vt.on:hover{color:' + FGB2_H + ';background:' + BRAND2_H + ';border-color:' + CB_H + ';}',
      // 기준 = DS Interaction tag Filled S(24 · r8) / the reference chip = a DS Interaction tag Filled S
      '.ai365-rd-ref{margin-left:auto;display:inline-flex;align-items:center;gap:4px;height:24px;font:' + CAP1 + ';color:' + FG2 + ';background:' + BG3 + ';border:0;border-radius:' + R_TAG + ';padding:0 8px;cursor:pointer;}',
      '.ai365-rd-ref:hover{background:' + BG3_H + ';color:' + FG2_H + ';}',
      '.ai365-rd-tblnote{display:flex;align-items:center;gap:6px;flex-wrap:wrap;font:' + CAP1 + ';color:' + FG3 + ';margin:2px 2px 8px;}',
      '.ai365-rd-tblnote b{color:' + FG2 + ';font-weight:600;}',
      // 표 = DS DataGrid(머리 채움 없음 · 붙는 머리는 표면색 흰 바탕 · 구분선 Stroke 2 · 셀 좌우 8 · 행 S 33 · 바깥 선 없음) / tables = DS DataGrid
      '.ai365-rd-tbl{max-height:282px;overflow:auto;border:0;border-radius:0;}',
      '.ai365-rd-card.full .ai365-rd-tbl,.ai365-rd-card.expanded .ai365-rd-tbl{max-height:342px;}',
      '.ai365-rd-tbl table{width:100%;border-collapse:collapse;font:' + B1 + ';font-variant-numeric:tabular-nums;}',
      '.ai365-rd-tbl th{position:sticky;top:0;height:33px;background:' + BG1 + ';text-align:left;font:' + B1 + ';color:' + FG1 + ';padding:0 8px;border-bottom:1px solid ' + ST2 + ';white-space:nowrap;}',
      '.ai365-rd-card.focus .ai365-rd-tbl th{background:' + BG1_S + ';}',
      '.ai365-rd-tbl th.used{color:' + FG_BRAND + ';font-weight:600;}',
      '.ai365-rd-tbl td{padding:6px 8px;border-bottom:1px solid ' + ST2 + ';white-space:nowrap;color:' + FG1 + ';}',
      '.ai365-rd-tbl td.num{text-align:right;}',
      '.ai365-rd-tbl tr:last-child td{border-bottom:0;}',
      // 드릴 경로 = DS Interaction tag Brand S(r8), 지금 단계 = Selected(브랜드 채움) / drill crumbs = DS Interaction tags Brand S; the current one is Selected
      '.ai365-rd-crumbs{display:flex;align-items:center;gap:4px;flex-wrap:wrap;margin:0 2px 6px;font:' + CAP1 + ';}',
      '.ai365-rd-crumbs:empty{display:none;}',
      '.ai365-rd-crumb{display:inline-flex;align-items:center;gap:4px;height:24px;font:' + CAP1 + ';color:' + FGB2 + ';background:' + BRAND2 + ';border:0;border-radius:' + R_TAG + ';padding:0 8px;cursor:pointer;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-rd-crumb:hover{background:' + BRAND2_H + ';color:' + FGB2_H + ';}',
      '.ai365-rd-crumb.cur{background:' + BRAND + ';color:' + FG_ON + ';}',
      '.ai365-rd-crumb svg{width:10px;height:10px;flex-shrink:0;}',
      '.ai365-rd-crumbs .sep{color:' + FG3 + ';}',
      '.ai365-rd-crumbs .lv{font:' + CAP1S + ';color:' + FG2 + ';background:' + BG3 + ';border-radius:' + R_TAG + ';padding:4px 8px;}',
      // 표시 칩 = DS Interaction tag Filled S(24 · r8) / marker chips = DS Interaction tags Filled S
      '.ai365-rd-mks{display:flex;flex-wrap:wrap;gap:6px;margin:8px 2px 0;}',
      '.ai365-rd-mks:empty{display:none;}',
      '.ai365-rd-mk{display:inline-flex;align-items:center;gap:6px;max-width:100%;min-width:0;height:24px;font:' + CAP1 + ';color:' + FG2 + ';background:' + BG3 + ';border:1px solid transparent;border-radius:' + R_TAG + ';padding:0 4px 0 8px;cursor:default;box-sizing:border-box;}',
      '.ai365-rd-mk i{width:9px;height:9px;border-radius:3px;flex-shrink:0;}',
      '.ai365-rd-mk b{font-weight:600;white-space:nowrap;}',
      '.ai365-rd-mk em{font-style:normal;font:' + CAP2S + ';color:' + FG3 + ';background:' + BG4 + ';border-radius:' + R_BADGE + ';padding:1px 4px;}',
      '.ai365-rd-mk .nm{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:' + FG3 + ';}',
      '.ai365-rd-mk button{width:16px;height:16px;border:0;background:none;color:' + FG3 + ';border-radius:' + R4 + ';display:inline-flex;align-items:center;justify-content:center;cursor:pointer;padding:0;flex-shrink:0;}',
      '.ai365-rd-mk button:hover{background:' + SUB_P + ';color:' + CB + ';}',
      '.ai365-rd-mk button svg{width:9px;height:9px;}',
      '.ai365-rd-dmenu{min-width:180px;max-width:220px;cursor:default;}',
      '.ai365-rd-ib.on,.ai365-rd-ib.on:hover:not(:disabled){background:' + SUB_S + ';color:' + FG2_BS + ';}',
      // 추세선 · 메모 표시는 차트 위 그리기 색과 짝이라 그대로 / the trend and note markers pair with the canvas drawing colours, so they stay
      '.ai365-rd-mk.trend{background:#EEF6FF;border-color:#C9E0FB;color:#1C5FA8;}',
      '.ai365-rd-mk.trend>svg{flex-shrink:0;}',
      '.ai365-rd-mk.trend .nm{color:#1C5FA8;}',
      '.ai365-rd-rmenu{min-width:250px;}',
      '.ai365-rd-rmenu .presets{display:flex;gap:4px;flex-wrap:wrap;margin:2px 0 8px;}',
      // 기간 프리셋 = DS Subtle circular 탭 S 24 / range presets = DS Subtle circular tabs S 24
      '.ai365-rd-rmenu .presets button{height:24px;font:' + CAP1 + ';color:' + FG2 + ';background:transparent;border:1px solid ' + ST2 + ';border-radius:' + R_FULL + ';padding:0 8px;cursor:pointer;}',
      '.ai365-rd-rmenu .presets button:hover{background:' + BG1_H + ';border-color:' + ST1_H + ';color:' + FG2_H + ';}',
      '.ai365-rd-rmenu .presets button.on{background:' + BRAND2 + ';border-color:' + CB + ';color:' + FGB2 + ';font-weight:600;}',
      '.ai365-rd-rmenu .rng{display:flex;align-items:center;gap:6px;font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-rd-rmenu .rng select,.ai365-rd-rmenu .rng input{flex:1;min-width:0;height:32px;box-sizing:border-box;' + FILL + 'padding:0 8px;font:' + B1 + ';color:' + FG1 + ';}',
      '.ai365-rd-rmenu .rng select:focus,.ai365-rd-rmenu .rng input:focus{' + FOCUS + '}',
      '.ai365-rd-rmenu .hint{margin-top:8px;font:' + CAP1 + ';color:' + FG3 + ';}',
      // 테마 = DS Secondary 버튼 M(r8), 메뉴 안에서는 메뉴 항목 / the theme control = a DS Secondary button M (r8); a menu item inside menus
      '.ai365-rd-theme{display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 12px;border:1px solid ' + ST1 + ';border-radius:' + R_BTN + ';background:' + BG1 + ';font:' + B1S + ';color:' + FG1 + ';cursor:pointer;position:relative;}',
      '.ai365-rd-smenu .ai365-rd-theme{border:0;border-radius:' + R_ITEM + ';height:auto;min-height:32px;padding:6px;font:' + B1 + ';color:' + FG2 + ';gap:8px;width:100%;box-sizing:border-box;}',
      '.ai365-rd-smenu .ai365-rd-theme:hover{background:' + SUB_H + ';color:' + FG2_H + ';}',
      '.ai365-rd-smenu .ai365-rd-theme i{width:13px;height:13px;}',
      '.ai365-rd-theme:hover,.ai365-rd-theme.on{border-color:' + ST1_H + ';background:' + BG1_H + ';color:' + FG1 + ';}',
      '.ai365-rd-theme i{width:12px;height:12px;border-radius:' + R4 + ';flex-shrink:0;box-shadow:inset 0 0 0 1px rgba(0,0,0,.12);}',   /* 고른 색 견본(데이터) / the picked colour swatch (data) */
      '.ai365-rd-theme input{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer;padding:0;border:0;}',
      '.ai365-rd-mk.cmp{color:' + FGB2 + ';background:' + BRAND2 + ';border-color:transparent;}',
      '.ai365-rd-mk.cmp>svg,.ai365-rd-mk.note>svg{flex-shrink:0;}',
      '.ai365-rd-mk.note{background:#FFF9EA;border-color:#F2D48A;color:#8A5A00;}',
      '.ai365-rd-mk.note>svg{width:12px;height:12px;}',
      '.ai365-rd-mk.note .nm{color:#8A5A00;}',
      '.ai365-rd-notef{display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding:8px 12px 0;}',
      '.ai365-rd-notef:empty{display:none;}',
      '.ai365-rd-notef>.lb{display:inline-flex;color:#B7791F;}',   /* 메모 표시 색과 짝(데이터) / pairs with the note marker colour (data) */
      '.ai365-rd-notef select,.ai365-rd-notef input{height:32px;box-sizing:border-box;' + FILL + 'padding:0 10px;font:' + B1 + ';color:' + FG1 + ';}',
      '.ai365-rd-notef select{max-width:150px;}',
      '.ai365-rd-notef input{flex:1;min-width:140px;}',
      '.ai365-rd-notef input::placeholder{color:' + FG4 + ';}',
      '.ai365-rd-notef input:focus,.ai365-rd-notef select:focus{' + FOCUS + '}',
      '.ai365-rd-notef .err{font:' + CAP1 + ';color:' + BAD + ';}',
      /* KPI 카드 줄 + 편집 폼(2026-10-12), 카드 = DS Card, 숫자 · 증감의 데이터 색은 그대로 / the KPI card row and its editor (2026-10-12); tiles are DS Cards; the numbers' and deltas' data colours stay */
      '.ai365-rd-khost{margin-bottom:16px;}',
      '.ai365-rd-khost:empty{display:none;margin:0;}',
      '.ai365-rd-kpis{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;}',   /* 카드가 하나여도 전체 폭으로 늘어나지 않게(auto-fill) / a single card does not stretch across the row */
      '.ai365-rd-kpis:empty{display:none;}',
      '.ai365-rd-kt{position:relative;min-width:0;background:' + BG1 + ';border:1px solid transparent;border-radius:' + R_CARD + ';box-shadow:' + SH4 + ';padding:12px;display:flex;flex-direction:column;gap:2px;text-align:left;font-family:inherit;box-sizing:border-box;}',
      '.ai365-rd-kt.can{cursor:pointer;transition:box-shadow .12s,background .12s,border-color .12s;}',
      '.ai365-rd-kt.can:hover{background:' + BG1_H + ';box-shadow:' + SH8 + ';}',
      '.ai365-rd-kt.can:active{background:' + BG1_P + ';}',
      '.ai365-rd-kt.can:focus-visible{outline:none;box-shadow:' + RING + ';}',
      '.ai365-rd-kt.edit{background:' + BG1_S + ';border-color:' + ST1_S + ';}',
      '.ai365-rd-kt .l{font:' + CAP1S + ';color:' + FG3 + ';overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding-right:52px;}',
      '.ai365-rd-kt .v{font:' + SUB1 + ';color:' + FG1 + ';font-variant-numeric:tabular-nums;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-rd-kt .m{display:flex;align-items:center;gap:6px;flex-wrap:wrap;min-height:16px;font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-rd-kt .n{font:' + CAP1 + ';color:' + FG3 + ';overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-rd-kt .d{font-weight:700;color:' + FG2 + ';}',
      '.ai365-rd-kt .d.up{color:#0B7A5E;}',
      '.ai365-rd-kt .d.down{color:#B3261E;}',
      '.ai365-rd-kt .f{color:' + FG_BRAND + ';font-weight:600;}',
      '.ai365-rd-kt .acts{position:absolute;top:4px;right:4px;display:inline-flex;gap:2px;opacity:0;pointer-events:none;transition:opacity .12s;}',   /* keyboard: Tab reaches them (opacity, not display) */
      '.ai365-rd-kt:hover .acts,.ai365-rd-kt:focus-within .acts,.ai365-rd-kt.edit .acts{opacity:1;pointer-events:auto;}',
      '.ai365-rd-kt .acts button{width:24px;height:24px;border:0;background:none;color:' + FG2 + ';border-radius:' + R_BTN + ';display:inline-flex;align-items:center;justify-content:center;cursor:pointer;padding:0;}',
      '.ai365-rd-kt .acts button:hover{background:' + SUB_P + ';color:' + FG2_BH + ';}',
      '.ai365-rd-kt .acts button.rm:hover{background:' + BAD_BG + ';color:' + BAD + ';}',
      '.ai365-rd-kt .acts button svg{width:12px;height:12px;}',
      /* 제목 줄의 [+ KPI 카드] = DS Secondary 버튼 M(r8), 편집 = DS Dialog(600 · r16 · 안쪽 24 · Shadow 64) / the title-row [+ KPI card] = a DS Secondary button M; the editor = a DS Dialog */
      '.ai365-rd-kbtn{display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 12px;border:1px solid ' + ST1 + ';border-radius:' + R_BTN + ';background:' + BG1 + ';font:' + B1S + ';color:' + FG1 + ';cursor:pointer;white-space:nowrap;}',
      '.ai365-rd-kbtn:hover:not(:disabled){background:' + BG1_H + ';border-color:' + ST1_H + ';}',
      '.ai365-rd-kbtn:active:not(:disabled){background:' + BG1_P + ';border-color:' + ST1_P + ';}',
      '.ai365-rd-kbtn:focus-visible{outline:none;box-shadow:' + RING + ';}',
      '.ai365-rd-kbtn:disabled{cursor:default;background:' + BG_DIS + ';border-color:' + ST_DIS + ';color:' + FG_DIS + ';}',
      '.ai365-rd-kbtn svg{width:12px;height:12px;}',
      '.ai365-rd-kov{position:absolute;inset:0;z-index:6;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;padding:20px;}',
      '.ai365-rd-kdlg{background:' + BG1 + ';border-radius:' + R_DLG + ';width:100%;max-width:600px;max-height:100%;overflow:auto;box-sizing:border-box;padding:24px;box-shadow:' + SH64 + ';display:flex;flex-direction:column;gap:16px;}',
      '.ai365-rd-kdlg .hd{display:flex;align-items:center;gap:8px;}',
      '.ai365-rd-kdlg .hd b{font:' + SUB1 + ';color:' + FG1 + ';}',
      '.ai365-rd-kdlg .hd .x{margin-left:auto;width:32px;height:32px;border:0;background:none;border-radius:' + R_BTN + ';color:' + FG2 + ';display:inline-flex;align-items:center;justify-content:center;cursor:pointer;padding:0;}',
      '.ai365-rd-kdlg .hd .x:hover{background:' + SUB_H + ';color:' + FG2_BH + ';}',
      '.ai365-rd-kdlg .hd .x svg{width:14px;height:14px;}',
      '.ai365-rd-kdlg .pv{display:flex;flex-direction:column;gap:6px;}',
      '.ai365-rd-kdlg .pv .cap{font:' + CAP1S + ';color:' + FG3 + ';}',
      '.ai365-rd-kdlg .pv .ai365-rd-kt{max-width:260px;background:' + BG3 + ';box-shadow:none;}',
      '.ai365-rd-kdlg .f{display:flex;flex-direction:column;gap:10px;}',
      '.ai365-rd-kdlg .row{display:grid;grid-template-columns:76px minmax(0,1fr);align-items:center;gap:10px;}',
      // 필드 라벨 = DS Field 라벨 M(Body 1 · Foreground 1) / field labels = DS Field labels M (Body 1, Foreground 1)
      '.ai365-rd-kdlg .row>span:first-child{font:' + B1 + ';color:' + FG1 + ';}',
      '.ai365-rd-kdlg .fx{display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-width:0;}',
      '.ai365-rd-kdlg input[type=text],.ai365-rd-kdlg select{height:32px;box-sizing:border-box;' + FILL + 'padding:0 10px;font:' + B1 + ';color:' + FG1 + ';min-width:0;}',
      '.ai365-rd-kdlg input[type=text]::placeholder{color:' + FG4 + ';}',
      '.ai365-rd-kdlg input[type=text]:hover,.ai365-rd-kdlg select:hover{border-color:' + ST1_H + ';border-bottom-color:' + ACC_H + ';}',
      '.ai365-rd-kdlg input[type=text]:focus,.ai365-rd-kdlg select:focus{' + FOCUS + '}',
      '.ai365-rd-kdlg input[type=text]:disabled,.ai365-rd-kdlg select:disabled{background-color:transparent;border-color:' + ST_DIS + ';color:' + FG_DIS + ';}',
      '.ai365-rd-kdlg input.grow{flex:1;min-width:140px;}',
      '.ai365-rd-kdlg input.s{width:84px;}',
      '.ai365-rd-kdlg select{flex:1;max-width:190px;}',
      // 네이티브 셀렉트 = 같은 Outline 입력 + 셰브런(Foreground 3) / native selects get the same Outline input plus a chevron (Foreground 3)
      '.ai365-rd-kdlg select,.ai365-rd-notef select,.ai365-rd-rmenu .rng select{appearance:none;-webkit-appearance:none;padding-right:28px;background-image:' + CHEV + ';background-repeat:no-repeat;background-position:right 9px center;cursor:pointer;}',
      // 선택지 묶음 = DS Subtle circular 탭 M 32 / option groups = DS Subtle circular tabs M 32
      '.ai365-rd-kdlg .seg{display:inline-flex;gap:4px;padding:0;border:0;border-radius:0;background:transparent;}',
      '.ai365-rd-kdlg .seg button{height:32px;padding:0 12px;border:1px solid transparent;border-radius:' + R_FULL + ';background:none;font:' + B1 + ';color:' + FG2 + ';cursor:pointer;}',
      '.ai365-rd-kdlg .seg button:hover:not(:disabled){background:' + BG1_H + ';border-color:' + ST1_H + ';color:' + FG2_H + ';}',
      '.ai365-rd-kdlg .seg button[aria-pressed=true]{background:' + BRAND2 + ';color:' + FGB2 + ';border-color:' + CB + ';font-weight:600;}',
      '.ai365-rd-kdlg .seg button[aria-pressed=true]:hover:not(:disabled){background:' + BRAND2_H + ';color:' + FGB2_H + ';border-color:' + CB_H + ';}',
      '.ai365-rd-kdlg .seg button:disabled{color:' + FG_DIS + ';cursor:default;}',
      '.ai365-rd-kdlg .seg button:focus-visible{outline:none;box-shadow:' + RING + ';}',
      // 체크박스 = DS 체크박스(라벨: 꺼짐 Foreground 3 → 켜짐 Foreground 1) / checkboxes = the DS checkbox (label: off Foreground 3 → on Foreground 1)
      '.ai365-rd-kdlg label.ck{display:inline-flex;align-items:center;gap:8px;font:' + B1 + ';color:' + FG3 + ';cursor:pointer;white-space:nowrap;}',
      '.ai365-rd-kdlg label.ck:has(input:checked){color:' + FG1 + ';}',
      '.ai365-rd-kdlg label.ck input{' + CHK + '}',
      '.ai365-rd-kdlg label.ck input:hover{border-color:' + ACC_H + ';}',
      '.ai365-rd-kdlg label.ck input:checked{' + CHK_ON + '}',
      '.ai365-rd-kdlg .hint{font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-rd-kdlg .ft{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding-top:4px;}',
      '.ai365-rd-kdlg .ft .sp{flex:1;}',
      '.ai365-rd-kdlg .err{font:' + CAP1 + ';color:' + BAD + ';}',
      '.ai365-rd-kdlg .err:empty{display:none;}',
      '.ai365-rd-calc{font-style:normal;display:inline-flex;align-items:center;height:16px;font:' + CAP2S + ';color:' + FGB2 + ';background:' + BRAND2 + ';border:0;border-radius:' + R_BADGE + ';padding:0 4px;margin-left:4px;vertical-align:1px;}',
      '.ai365-rd-tbl.vals{max-height:200px;margin-bottom:10px;}',
      '.ai365-rd-skel{height:220px;border-radius:' + R8 + ';background:linear-gradient(100deg,' + BG4 + ' 30%,' + BG2 + ' 50%,' + BG4 + ' 70%);background-size:300% 100%;animation:ai365RdSkel 1.3s linear infinite;}',
      '@keyframes ai365RdSkel{0%{background-position:100% 0;}100%{background-position:-100% 0;}}',
      '.ai365-rd-veil{position:absolute;inset:0;border-radius:' + R_CARD + ';background:rgba(255,255,255,.78);display:flex;align-items:center;justify-content:center;gap:8px;font:' + CAP1S + ';color:' + FG2 + ';z-index:5;}',
      '.ai365-rd-empty{display:flex;flex-direction:column;align-items:center;gap:6px;text-align:center;padding:44px 20px;border:1px dashed ' + ST1 + ';border-radius:' + R_CARD + ';color:' + FG3 + ';font:' + CAP1 + ';background:' + BG1 + ';}',
      '.ai365-rd-empty b{font:' + B1S + ';color:' + FG1 + ';}',
      // 출처 카드 = DS Card / the provenance card = a DS Card
      '.ai365-rd-prov{background:' + BG1 + ';border:0;border-radius:' + R_CARD + ';box-shadow:' + SH4 + ';padding:12px 16px;margin-bottom:12px;}',
      '.ai365-rd-prov h3{font:' + SUB2 + ';margin:0 0 10px;display:flex;align-items:center;gap:8px;}',
      '.ai365-rd-prov h3 em{font-style:normal;font:' + CAP1S + ';color:' + FG3 + ';}',
      '.ai365-rd-kv{display:grid;grid-template-columns:96px minmax(0,1fr);gap:8px 12px;font:' + CAP1 + ';}',
      '.ai365-rd-kv dt{color:' + FG3 + ';font-weight:400;}',
      '.ai365-rd-kv dd{margin:0;color:' + FG1 + ';min-width:0;word-break:break-word;}',
      // 칩 = DS Tag Brand S(r8) / chips = DS Tags Brand S (r8)
      '.ai365-rd-tag{display:inline-flex;align-items:center;gap:4px;height:24px;font:' + CAP1 + ';background:' + BRAND2 + ';border-radius:' + R_TAG + ';padding:0 8px;margin:0 4px 4px 0;color:' + FGB2 + ';}',
      '.ai365-rd-prov details{margin-top:10px;font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-rd-prov summary{cursor:pointer;font-weight:600;user-select:none;}',
      '.ai365-rd-prov pre{background:' + BG3 + ';border:1px solid ' + ST2 + ';border-radius:' + R8 + ';padding:10px 12px;margin:8px 0 0;font:' + CAP1 + ';white-space:pre-wrap;word-break:break-all;color:' + FG2 + ';}',
      '.ai365-rd-uses{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:12px;padding-top:12px;border-top:1px solid ' + ST2 + ';font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-rd-use{display:inline-flex;align-items:center;gap:4px;height:24px;font:' + CAP1 + ';color:' + FGB2 + ';background:' + BRAND2 + ';border:0;border-radius:' + R_TAG + ';padding:0 8px;cursor:pointer;}',
      '.ai365-rd-use:hover{background:' + BRAND2_H + ';color:' + FGB2_H + ';}',
      '.ai365-rd-use:active{background:' + BRAND2_P + ';color:' + FGB2_P + ';}',
      '.ai365-rd-dock{background:' + BG1 + ';border-top:1px solid ' + ST2 + ';padding:12px 20px 16px;}',
      // 대화: 사용자 말풍선 = Background 3 · r12, 오류 = DS 메시지 바(오류) / the conversation: user bubbles on Background 3 (r12); errors are a DS message bar (error)
      '.ai365-rd-msg{max-width:72%;font:' + B1 + ';border-radius:' + R12 + ';padding:8px 12px;white-space:pre-wrap;word-break:break-word;}',
      '.ai365-rd-msg.user{align-self:flex-end;background:' + BG3 + ';color:' + FG2 + ';}',
      '.ai365-rd-msg.agent{align-self:stretch;max-width:100%;background:none;padding:0 2px;color:' + FG2 + ';font:' + B1 + ';}',
      '.ai365-rd-msg.agent .tx{display:block;}',
      '.ai365-rd-msg.err{align-self:flex-start;background:' + BAD_BG + ';border:1px solid ' + BAD_BD + ';border-radius:' + R_MB + ';color:' + BAD + ';}',
      '.ai365-rd-tree{font:' + CAP1 + ';color:' + FG2 + ';margin:0 0 8px 2px;}',
      '.ai365-rd-msg .ai365-rd-tree{margin:6px 0 0;}',
      '.ai365-rd-msg.agent .ai365-rd-tree{max-height:180px;overflow:auto;}',
      '.ai365-rd-tree ul{list-style:none;margin:0;padding:0;}',
      '.ai365-rd-tree ul ul{padding-left:20px;}',
      '.ai365-rd-tree li{position:relative;}',
      '.ai365-rd-tree ul ul>li::before{content:"";position:absolute;left:-11px;top:0;width:9px;height:12px;border-left:1.5px solid ' + ST1 + ';border-bottom:1.5px solid ' + ST1 + ';border-bottom-left-radius:6px;}',
      '.ai365-rd-tree ul ul>li:not(:last-child)::after{content:"";position:absolute;left:-11px;top:0;bottom:0;border-left:1.5px solid ' + ST1 + ';}',
      '.ai365-rd-tree .tn{display:flex;align-items:center;gap:6px;min-width:0;width:100%;box-sizing:border-box;padding:2px 0;background:none;border:0;font:inherit;color:inherit;text-align:left;}',
      '.ai365-rd-tree .tn.root b{font-weight:600;color:' + FG1 + ';}',
      '.ai365-rd-tree .tn.root .mk{width:16px;height:16px;border-radius:50%;background:' + BRAND2 + ';color:' + CB + ';display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;}',
      '.ai365-rd-tree .tn.root .mk svg{width:9px;height:9px;}',
      '.ai365-rd-tree .tn.root[role=button]{cursor:pointer;width:auto;}',
      '.ai365-rd-tree .tn>svg:last-child{color:' + FG3 + ';transition:transform .14s;flex-shrink:0;}',
      '.ai365-rd-tree.shut .tn.root>svg:last-child,.ai365-rd-tree .tn.shut>svg:last-child{transform:rotate(-90deg);}',
      '.ai365-rd-tree .cnt{font:' + CAP2S + ';color:' + FG3 + ';background:' + BG4 + ';border-radius:' + R_BADGE + ';padding:1px 4px;white-space:nowrap;}',
      '.ai365-rd-tree .tn.ag b{font-weight:600;}',
      // 에이전트 종류 점은 차트 팔레트(indigo)와 같은 데이터 색이라 그대로 / the agent-kind dots share the chart palette (indigo), so they stay
      '.ai365-rd-tree .tn.ag i{width:7px;height:7px;border-radius:50%;background:#5B5BD6;flex-shrink:0;}',
      '.ai365-rd-tree .tn.ag i.data{background:#12B886;}',
      '.ai365-rd-tree .tn.leaf .st{width:14px;height:14px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;background:' + OK_BG + ';color:' + OK + ';box-shadow:inset 0 0 0 1px ' + OK_BD + ';flex-shrink:0;}',
      '.ai365-rd-tree .tn.leaf.bad .st{background:' + BAD_BG + ';color:' + BAD + ';box-shadow:inset 0 0 0 1px ' + BAD_BD + ';}',
      '.ai365-rd-tree .tn.leaf .st svg{width:9px;height:9px;}',
      '.ai365-rd-tree .tn.leaf.wait .ai365-rd-spin{width:11px;height:11px;}',
      '.ai365-rd-tree .lb{font-weight:600;white-space:nowrap;}',
      '.ai365-rd-tree code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:10px;line-height:14px;color:' + FG3 + ';background:' + BG3 + ';border-radius:' + R4 + ';padding:1px 4px;white-space:nowrap;}',
      '.ai365-rd-tree .nt{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:' + FG3 + ';}',
      '.ai365-rd-tree .tn.bad .nt{color:' + BAD + ';}',
      '.ai365-rd-inrow{position:relative;}',
      // 도구 버튼 = 제품 시트 입력 카드 알약(40 · Stroke 1), 도구 트리 = DS 팝오버(r12 · Shadow 16) / the tools button = the product composer pill (40, Stroke 1); the tool tree = a DS popover
      '.ai365-rd-tbtn{display:inline-flex;align-items:center;gap:6px;height:40px;padding:0 16px;border:1px solid ' + ST1 + ';border-radius:' + R_FULL + ';background:' + BG1 + ';font:' + B1S + ';color:' + FG1 + ';cursor:pointer;flex-shrink:0;transition:.12s;}',
      '.ai365-rd-tbtn:hover:not(:disabled){background:' + BG1_H + ';border-color:' + ST1_H + ';}',
      '.ai365-rd-tbtn:active:not(:disabled){background:' + BG1_P + ';border-color:' + ST1_P + ';}',
      '.ai365-rd-tbtn.on{border-color:' + ST1_S + ';color:' + FG1 + ';background:' + BG1_S + ';}',
      '.ai365-rd-tbtn:disabled{cursor:default;background:' + BG_DIS + ';border-color:' + ST_DIS + ';color:' + FG_DIS + ';}',
      '.ai365-rd-tmenu{position:absolute;left:0;bottom:calc(100% + 8px);width:390px;max-width:100%;max-height:min(62vh,460px);overflow:auto;box-sizing:border-box;background:' + BG1 + ';border:0;border-radius:' + R_MENU + ';box-shadow:' + SH16 + ';padding:12px;z-index:40;}',
      '.ai365-rd-tmenu .hd{display:flex;align-items:center;gap:8px;margin-bottom:8px;font:' + CAP1 + ';}',
      '.ai365-rd-tmenu .hd .wh{margin-left:auto;min-width:0;max-width:55%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-rd-tmenu .ft{margin-top:8px;padding-top:8px;border-top:1px solid ' + ST2 + ';font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-rd-tree.pick{margin:0;font:' + CAP1 + ';}',
      '.ai365-rd-tree.pick ul ul>li::before{height:16px;}',
      '.ai365-rd-tree.pick .tn{min-height:32px;padding:6px 8px;border-radius:' + R_ITEM + ';}',
      '.ai365-rd-tree.pick button.tn{cursor:pointer;}',
      '.ai365-rd-tree.pick button.tn:hover{background:' + SUB_H + ';color:' + FG2_H + ';}',
      '.ai365-rd-tree.pick button.tn:active{background:' + SUB_P + ';}',
      '.ai365-rd-tree.pick button.tn.leaf:hover{background:' + SUB_H + ';color:' + FG2_BH + ';}',
      '.ai365-rd-tree.pick .tn.leaf .lb{font-weight:400;}',
      '.ai365-rd-tree.pick .tn code{margin-left:auto;}',
      '.ai365-rd-tree.pick .tn.grp .cnt{margin-left:2px;}',
      '.ai365-rd-scope{display:flex;margin-bottom:8px;}',
      '.ai365-rd-scope .ai365-rd-focus{margin-bottom:0;}',
      '.ai365-rd-dock{position:relative;}',
      '.ai365-rd-prog{position:absolute;left:0;right:0;top:-1px;height:2px;background:linear-gradient(90deg,transparent,' + CB + ',transparent);background-size:40% 100%;background-repeat:no-repeat;animation:ai365RdProg 1.1s linear infinite;}',
      '@keyframes ai365RdProg{0%{background-position:-40% 0;}100%{background-position:140% 0;}}',
      '.ai365-rd-busy{display:inline-flex;align-items:center;gap:8px;font:' + CAP1S + ';color:' + FG_BRAND + ';}',
      // 스피너 = 브랜드 머리 + Brand stroke 2 트랙 / the spinner = a brand head on a Brand stroke 2 track
      '.ai365-rd-spin{width:13px;height:13px;border-radius:50%;border:2px solid ' + BSTROKE2 + ';border-top-color:' + CB + ';animation:ai365RdSpin .8s linear infinite;}',
      '@keyframes ai365RdSpin{to{transform:rotate(360deg);}}',
      // 차트 대상 칩 = DS Interaction tag Brand S(24 · r8) / the chart-target chip = a DS Interaction tag Brand S
      '.ai365-rd-focus{display:inline-flex;align-items:center;gap:4px;height:24px;font:' + CAP1 + ';color:' + FGB2 + ';background:' + BRAND2 + ';border-radius:' + R_TAG + ';padding:0 4px 0 8px;margin-bottom:8px;max-width:100%;}',
      '.ai365-rd-focus span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-rd-focus button{width:16px;height:16px;border:0;background:none;color:' + FGB2 + ';cursor:pointer;display:inline-flex;align-items:center;justify-content:center;border-radius:' + R4 + ';padding:0;}',
      '.ai365-rd-focus button:hover{background:' + BRAND2_H + ';color:' + CB + ';}',
      '.ai365-rd-focus button svg{width:10px;height:10px;}',
      // 대화 입력줄 = 제품 시트 입력 카드(흰 바탕 · r24 · 1px Stroke 2 · Shadow 12, 글자 Body 2, placeholder Foreground 4) /
      // the chat input row = the product-sheet composer (white, r24, a 1px Stroke 2, Shadow 12; Body 2 text, Foreground 4 placeholder)
      '.ai365-rd-inrow{display:flex;gap:8px;align-items:flex-end;border:1px solid ' + ST2 + ';border-radius:' + R_COMP + ';background:' + BG1 + ';box-shadow:' + SH12 + ';padding:8px;transition:border-color .12s;}',
      '.ai365-rd-inrow:focus-within{border-color:' + ST1 + ';}',
      '.ai365-rd-inrow textarea{flex:1;min-width:0;border:0;border-radius:' + R8 + ';padding:9px 8px;font:' + B2 + ';color:' + FG1 + ';outline:none;resize:none;max-height:110px;background:transparent;}',
      '.ai365-rd-inrow textarea::placeholder{color:' + FG4 + ';}',
      '.ai365-rd-inrow textarea:focus{outline:none;box-shadow:none;}',
      '.ai365-rd-inrow textarea:disabled{color:' + FG_DIS + ';}',
      // 보내기 = 제품 시트 보내기(40 원 · 브랜드) / send = the product-sheet send (a 40px brand circle)
      '.ai365-rd-send{width:40px;height:40px;border-radius:50%;background:' + BRAND + ';color:' + FG_ON + ';border:0;display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;transition:.12s;}',
      '.ai365-rd-send:hover:not(:disabled){background:' + BRAND_H + ';}',
      '.ai365-rd-send:active:not(:disabled){background:' + BRAND_P + ';}',
      '.ai365-rd-send:disabled{background:' + BG_DIS + ';color:' + FG_DIS + ';cursor:default;}',
      '.ai365-rd-libhd{display:flex;align-items:center;gap:8px;margin-bottom:16px;}',
      '.ai365-rd-libhd h2{font:' + SUB2 + ';margin:0;}',
      '.ai365-rd-libhd .sp{flex:1;}',
      // 버튼 = DS 코어 버튼 M(r8 · 32 · Body 1 Strong): 기본 Secondary, .pri = Primary / buttons = DS core buttons M (r8, 32, Body 1 Strong): Secondary by default, .pri = Primary
      '.ai365-rd-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;height:32px;padding:0 12px;font:' + B1S + ';color:' + FG1 + ';background:' + BG1 + ';border:1px solid ' + ST1 + ';border-radius:' + R_BTN + ';cursor:pointer;transition:.12s;white-space:nowrap;}',
      '.ai365-rd-btn:hover:not(:disabled){background:' + BG1_H + ';border-color:' + ST1_H + ';}',
      '.ai365-rd-btn:active:not(:disabled){background:' + BG1_P + ';border-color:' + ST1_P + ';}',
      '.ai365-rd-btn.pri{background:' + BRAND + ';border-color:transparent;color:' + FG_ON + ';}',
      '.ai365-rd-btn.pri:not(.sm){min-width:96px;}',
      '.ai365-rd-btn.pri:hover:not(:disabled){background:' + BRAND_H + ';border-color:transparent;color:' + FG_ON + ';}',
      '.ai365-rd-btn.pri:active:not(:disabled){background:' + BRAND_P + ';border-color:transparent;}',
      '.ai365-rd-btn.pri:disabled{background:' + BG_DIS + ';border-color:transparent;color:' + FG_DIS + ';}',
      '.ai365-rd-lib{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:16px;}',
      // 보관소 카드 = DS Card(r8 · Shadow 04 → hover Background 1 hover + Shadow 08, 지금 것 = 선택 단계) / library cards = DS Cards (the current one = selected)
      '.ai365-rd-lc{background:' + BG1 + ';border:1px solid transparent;border-radius:' + R_CARD + ';box-shadow:' + SH4 + ';overflow:hidden;display:flex;flex-direction:column;cursor:pointer;transition:box-shadow .14s,background .14s;text-align:left;padding:0;}',
      '.ai365-rd-lc:hover{background:' + BG1_H + ';box-shadow:' + SH8 + ';}',
      '.ai365-rd-lc:active{background:' + BG1_P + ';}',
      '.ai365-rd-lc.cur{background:' + BG1_S + ';border-color:' + ST1_S + ';}',
      '.ai365-rd-lth{height:132px;background:' + BG3 + ';border-bottom:1px solid ' + ST2 + ';display:grid;gap:4px;padding:8px;overflow:hidden;}',
      '.ai365-rd-lth.n2,.ai365-rd-lth.n3,.ai365-rd-lth.n4{grid-template-columns:1fr 1fr;}',
      '.ai365-rd-lth>span{min-width:0;min-height:0;overflow:hidden;background:' + BG1 + ';border-radius:' + R8 + ';display:block;}',
      '.ai365-rd-lth svg{width:100% !important;height:100% !important;display:block;}',
      '.ai365-rd-lb{padding:12px;display:flex;flex-direction:column;gap:4px;}',
      '.ai365-rd-lb .r{display:flex;align-items:center;gap:6px;}',
      // 종류 = DS Badge M 20 · r4 틴트(대시보드 = brand · 리포트 = success · 옛 형식 = informative) / kinds = DS Badges M 20, r4, tint
      '.ai365-rd-kind{display:inline-flex;align-items:center;height:20px;font:' + CAP2S + ';border-radius:' + R_BADGE + ';padding:0 6px;background:' + BRAND2 + ';color:' + FGB2 + ';box-shadow:inset 0 0 0 1px ' + BSTROKE2 + ';}',
      '.ai365-rd-kind.report{background:' + OK_BG + ';color:' + OK + ';box-shadow:inset 0 0 0 1px ' + OK_BD + ';}',
      '.ai365-rd-kind.old{background:' + BG4 + ';color:' + FG3 + ';box-shadow:inset 0 0 0 1px ' + ST2 + ';}',
      '.ai365-rd-lb b{font:' + B1S + ';overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-rd-lb .m{font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-rd-lb .del{margin-left:auto;}',
      '.ai365-rdv{display:flex;flex-direction:column;gap:12px;container-type:inline-size;}',
      '.ai365-rdv .ai365-rd-cbody{cursor:default;}',
      '.ai365-rdv-src{background:' + BG3 + ';border:0;border-radius:' + R_CARD + ';padding:12px;font:' + CAP1 + ';}',
      '.ai365-rdv-src h4{font:' + B1S + ';margin:0 0 8px;color:' + FG1 + ';}',
      '.ai365-rdv-src .row{display:flex;gap:10px;flex-wrap:wrap;align-items:baseline;padding:6px 0;border-top:1px solid ' + ST2 + ';color:' + FG3 + ';}',
      '.ai365-rdv-src .row:first-of-type{border-top:0;}',
      '.ai365-rdv-src .row b{color:' + FG2 + ';}',
    ].join('\n');
    document.head.appendChild(s);
  })();

  /* ── Chart.js 지연 로드 / lazy load ── */
  let chartJsReady = null;
  function loadChartJs() {
    if (window.Chart) return Promise.resolve();
    if (chartJsReady) return chartJsReady;
    chartJsReady = new Promise(function (resolve, reject) {
      const s = document.createElement('script');
      s.src = '/static/vendor/chart.umd.min.js';
      s.onload = function () { resolve(); };
      s.onerror = function () { chartJsReady = null; reject(new Error('Chart.js')); };
      document.head.appendChild(s);
    });
    return chartJsReady;
  }

  function api(path, method, body) {
    return fetch(path, { method: method || 'GET', headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (d) {
        if (!res.ok) throw new Error((d && typeof d.detail === 'string' && d.detail) || ('HTTP ' + res.status));
        return d;
      });
    });
  }

  /* ── 공용 렌더(패널과 읽기 전용 뷰어가 함께 쓴다) / shared rendering (panel and read-only viewer) ──
     ctx = { state, tableOf:{cid:bool}, fopen:'cid:fid', fq:검색어, addf:cid(컬럼 고르는 중), focus, readonly, charts:Map, root:Element, regen:cid }
     필터는 차트(BI)마다 따로다(2026-09-19) — 카드 안에 필터 줄이 있고 그 차트의 값·표에만 적용된다.
     Filters belong to a chart (2026-09-19): the filter row lives inside the card and applies to that chart only. */
  function srcOf(state, id) { return state.sources.filter(function (s) { return s.id === id; })[0]; }
  function chartOf(state, id) { return state.charts.filter(function (c) { return c.id === id; })[0]; }
  function usedCols(chart) {
    return [chart.x, chart.group].concat(chart.y.map(function (y) { return y.col; }), chart.y.map(function (y) { return y.by && y.by.col; }))
      .filter(function (c) { return c && c !== '*'; });
  }
  function filterOf(chart, fid) { return (chart.filters || []).filter(function (f) { return f.id === fid; })[0]; }

  function filterValues(src, f) {
    const ci = src.columns.indexOf(f.col), seen = {}, out = [];
    if (ci < 0) return out;
    src.rows.forEach(function (r) { const k = rdKey(r[ci]); if (!seen[k]) { seen[k] = 1; out.push(k); } });
    const pk = (src.periods || {})[f.col];
    if (pk && out.every(function (v) { return v === '' || rdPeriodKey(v, pk); })) {
      return out.filter(function (v) { return v !== ''; }).sort(function (a, b) { const p = rdPeriodKey(a, pk), q = rdPeriodKey(b, pk); return (p[0] - q[0]) || (p[1] - q[1]); }).slice(0, 300);
    }
    const numeric = out.length > 0 && out.every(function (v) { return rdNum(v) !== null; });
    return out.sort(numeric ? function (a, b) { return rdNum(a) - rdNum(b); } : undefined).slice(0, 300);
  }
  /* 필터 모양은 컬럼 종류를 따른다(2026-09-21): 글자 = 값 목록, 기간 = 범위(부터~까지 · 최근 N개), 숫자 = 이상·이하 */
  /* The filter's shape follows the column kind: text = a value list, period = a range (from~to or the last N), number = min and max */
  function filterKind(src, f) { return (src.periods || {})[f.col] ? 'period' : ((src.types || {})[f.col] === 'number' ? 'number' : 'list'); }
  const PERIOD_UNIT = { year: ['년', 'years', [2, 3, 5]], quarter: ['분기', 'quarters', [2, 4, 8]], month: ['개월', 'months', [3, 6, 12]], week: ['주', 'weeks', [4, 8, 12]], date: ['일', 'days', [7, 14, 30]] };
  function lastText(kind, n) { const u = PERIOD_UNIT[kind] || PERIOD_UNIT.month; return isEn() ? 'Last ' + n + ' ' + u[1] : '최근 ' + n + u[0]; }
  function filterSummary(f, src) {
    const sel = f.selected || [], r = f.range;
    if (r && r.last) return lastText(src ? (src.periods || {})[f.col] : 'month', r.last);
    if (r && ('from' in r || 'to' in r)) return (r.from || T('처음')) + ' ~ ' + (r.to || T('끝'));
    if (r) {
      const lo = (r.min === null || r.min === undefined) ? '' : rdFmt(r.min), hi = (r.max === null || r.max === undefined) ? '' : rdFmt(r.max);
      return lo && hi ? lo + ' ~ ' + hi : (lo ? '≥ ' + lo : '≤ ' + hi);
    }
    return !sel.length ? T('전체') : (sel.length === 1 ? sel[0] : sel[0] + ' +' + (sel.length - 1));
  }
  function rangeMenuHtml(key, src, f) {
    const kind = filterKind(src, f), r = f.range || {};
    const head = '<div class="ops"><button type="button" data-rdf-none="' + E(key) + '">' + T('전체 보기') + '</button></div>';
    if (kind === 'period') {
      const pk = src.periods[f.col], vals = filterValues(src, f), unit = PERIOD_UNIT[pk] || PERIOD_UNIT.month;
      const opts = function (cur, blank) {
        return '<option value="">' + T(blank) + '</option>' + vals.map(function (v) { return '<option value="' + E(v) + '"' + (v === cur ? ' selected' : '') + '>' + E(v) + '</option>'; }).join('');
      };
      return '<div class="ai365-rd-fmenu ai365-rd-rmenu" data-rdf-menu="' + E(key) + '">' + head
        + '<div class="presets">' + unit[2].map(function (n) { return '<button type="button" class="' + (r.last === n ? 'on' : '') + '" data-rdf-last="' + E(key) + '" data-n="' + n + '">' + E(lastText(pk, n)) + '</button>'; }).join('') + '</div>'
        + '<div class="rng" data-i18n-skip><select data-rdf-from="' + E(key) + '" aria-label="' + E(T('처음')) + '">' + opts(r.from || '', '처음') + '</select><span>~</span>'
        + '<select data-rdf-to="' + E(key) + '" aria-label="' + E(T('끝')) + '">' + opts(r.to || '', '끝') + '</select></div>'
        + '<div class="hint">' + T('최근 N개는 오늘이 아니라 데이터의 마지막 기간 기준입니다') + '</div></div>';
    }
    const ci = src.columns.indexOf(f.col), nums = src.rows.map(function (row) { return rdNum(row[ci]); }).filter(function (v) { return v !== null; });
    const lo = nums.length ? Math.min.apply(null, nums) : 0, hi = nums.length ? Math.max.apply(null, nums) : 0;
    const val = function (v) { return (v === null || v === undefined) ? '' : String(v); };
    return '<div class="ai365-rd-fmenu ai365-rd-rmenu" data-rdf-menu="' + E(key) + '">' + head
      + '<div class="rng"><input type="number" data-rdf-min="' + E(key) + '" value="' + E(val(r.min)) + '" placeholder="' + E(rdFmt(lo)) + '" aria-label="' + E(T('이상')) + '"><span>~</span>'
      + '<input type="number" data-rdf-max="' + E(key) + '" value="' + E(val(r.max)) + '" placeholder="' + E(rdFmt(hi)) + '" aria-label="' + E(T('이하')) + '"></div>'
      + '<div class="hint"><span>' + T('이상') + '</span> ~ <span>' + T('이하') + '</span></div></div>';
  }

  function chartFiltersHtml(ctx, chart) {
    const src = srcOf(ctx.state, chart.source), fl = chart.filters || [], adding = !ctx.readonly && ctx.addf === chart.id;
    if (!fl.length && !adding) return '';
    const pills = fl.map(function (f) {
      const key = chart.id + ':' + f.id, sel = f.selected || [], open = ctx.fopen === key;
      let menu = '';
      if (open && filterKind(src, f) !== 'list') menu = rangeMenuHtml(key, src, f);
      else if (open) {
        const q = (ctx.fq || '').toLowerCase();
        const vals = filterValues(src, f).filter(function (v) { return !q || v.toLowerCase().indexOf(q) >= 0; });
        menu = '<div class="ai365-rd-fmenu" data-rdf-menu="' + E(key) + '">'
          + '<input type="search" data-rdf-q placeholder="' + E(T('값 검색')) + '" value="' + E(ctx.fq || '') + '">'
          + '<div class="ops"><button type="button" data-rdf-none="' + E(key) + '">' + T('전체 보기') + '</button></div>'
          + '<div class="vals" data-i18n-skip>' + vals.map(function (v) {
            return '<label><input type="checkbox" data-rdf-val="' + E(key) + '" value="' + E(v) + '"' + (sel.indexOf(v) >= 0 ? ' checked' : '') + '><span>' + E(v === '' ? '(빈 값)' : v) + '</span></label>';
          }).join('') + '</div></div>';
      }
      const on = sel.length > 0 || !!f.range;
      return '<div class="ai365-rd-f"><button type="button" class="ai365-rd-fp' + (on ? ' act' : '') + (open ? ' open' : '') + '" data-rdf-open="' + E(key) + '">'
        + '<span data-i18n-skip>' + E(f.label) + '</span><span class="v"' + (on ? ' data-i18n-skip' : '') + '>' + E(filterSummary(f, src)) + '</span>' + IC.caret
        + (ctx.readonly ? '' : '<span class="rm" data-rdf-rm="' + E(key) + '" title="' + E(T('필터 삭제')) + '">' + IC.x + '</span>') + '</button>' + menu + '</div>';
    }).join('');
    let add = '';
    if (!ctx.readonly && fl.length < 4) {
      const taken = fl.map(function (f) { return f.col; });
      const cols = src.columns.filter(function (c) { return taken.indexOf(c) < 0; });
      add = '<div class="ai365-rd-f"><button type="button" class="ai365-rd-fadd' + (adding ? ' open' : '') + '" data-rdf-add="' + E(chart.id) + '">' + IC.plus + '<span>' + T('필터') + '</span></button>'
        + (adding ? '<div class="ai365-rd-fmenu ai365-rd-colmenu" data-rdf-menu="add"><div class="cap">' + T('필터할 컬럼') + '</div><div class="vals" data-i18n-skip>'
          + cols.map(function (c) { return '<button type="button" data-rdf-colpick="' + E(chart.id) + '" data-col="' + E(c) + '">' + E(c) + '</button>'; }).join('') + '</div></div>' : '') + '</div>';
    }
    return '<span class="lb">' + IC.filter + '</span>' + pills + add;
  }

  /* 지금 보이는 데이터 — 경로에서 가장 깊은 서버 단계(remote)의 데이터, 없으면 차트의 Source(2026-09-30). 서버 단계 아래의
     로컬 단계는 그 서버 데이터 안에서 좁힌다(맨 위 Source 로 돌아가면 서버 단계의 값이 빠진다).
     The data in view: the deepest server (remote) level on the path, else the chart's source (2026-09-30). Local levels below a
     server level narrow that fetched data (falling back to the top source would drop the server level's value). */
  function viewSrc(ctx, chart) {
    const path = (ctx.drill && ctx.drill[chart.id]) || [];
    for (let i = path.length - 1; i >= 0; i--) {
      if (!path[i].remote) continue;
      const hit = ((ctx.dsrc || {})[chart.id] || {})[rdDrillSig(path.slice(0, i + 1))];
      if (hit) return hit.src;
      break;
    }
    return srcOf(ctx.state, chart.source);
  }
  /* 지금 보이는 차트 설정 — 드릴다운 중이면 내려간 자리의 설정. 서버에서 받은 단계에는 묶음 컬럼이 없으니 나누지 않는다
     The chart as shown: the drilled spec while drilled down. A fetched level has no group column, so the series is not split */
  function viewChart(ctx, chart) {
    const path = ctx.drill && ctx.drill[chart.id];
    if (!path || !path.length) return chart;
    const src = viewSrc(ctx, chart), vc = rdDrillChart(chart, src, path);
    const out = (vc.group && src.columns.indexOf(vc.group) < 0) ? Object.assign({}, vc, { group: null }) : vc;
    if (!path.some(function (p) { return p.remote; })) return out;
    // 서버 단계의 데이터에는 차트 필터가 이미 들어가 있다(값 컬럼 필터는 뜻이 달라져 서버가 일부러 뺐다) — 경로의 값만 다시 건다
    // A server level already reflects the chart's filters (measure filters are left out on purpose, their meaning changes); only the path applies
    const cols = path.map(function (p) { return p.col; });
    return Object.assign({}, out, { filters: out.filters.filter(function (f) { return cols.indexOf(f.col) >= 0; }) });
  }

  /* 계산 값이 있는 차트는 표 탭 맨 위에 "차트 값"(그려진 숫자)을 먼저 보여 준다 — 계산 열에는 '계산' 표시.
     A chart with calculated values shows the drawn numbers first on the Table tab; calculated columns carry a badge. */
  function valuesTableHtml(chart, comp) {
    if (!comp.series.some(function (s) { return s.calc; }) || !comp.x.length) return '';
    const head = '<th data-i18n-skip>' + E(chart.x || '') + '</th>' + comp.series.map(function (s) {
      return '<th' + (s.calc ? ' class="used"' : '') + '><span data-i18n-skip>' + E(s.name) + '</span>' + (s.calc ? '<em class="ai365-rd-calc">' + T('계산') + '</em>' : '') + '</th>';
    }).join('');
    const body = comp.x.map(function (label, i) {
      return '<tr><td data-i18n-skip>' + E(label) + '</td>' + comp.series.map(function (s) {
        return '<td class="num" data-i18n-skip>' + E(rdFmt(s.values[i], s.unit || chart.unit)) + '</td>';
      }).join('') + '</tr>';
    }).join('');
    return '<div class="ai365-rd-tblnote"><b>' + T('차트 값') + '</b><span>' + T('계산 값은 조회한 데이터로 시스템이 계산한 값입니다') + '</span></div>'
      + '<div class="ai365-rd-tbl vals"><table><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table></div>';
  }

  function tableHtml(ctx, chart) {
    const vc = viewChart(ctx, chart);
    const src = viewSrc(ctx, chart), rows = rdFilteredRows(src, vc.filters), used = usedCols(vc);   // 서버에서 가져온 단계면 그 데이터와 SQL / a fetched level shows its own data and SQL
    // Source 탭이 없어진 뒤(2026-09-22) 원본 테이블·조회 시각·[조회 SQL]은 여기서 본다 / with the Source tabs gone, the source table, fetch time and [query SQL] live here
    const sqlOpen = !!((ctx.sqlOpen || {})[chart.id]);
    const note = '<div class="ai365-rd-tblnote"><b data-i18n-skip>' + E(srcLabel(src)) + '</b>'
      + (src.fetched_at ? '<span data-i18n-skip>' + E(when(src.fetched_at)) + '</span>' : '')
      + '<span data-i18n-skip>' + rows.length.toLocaleString('ko-KR') + (rows.length !== src.rows.length ? ' / ' + src.rows.length.toLocaleString('ko-KR') : '') + '</span><span>' + T('행') + '</span>'
      + (rows.length !== src.rows.length ? '<span>' + T('필터 적용 중') + '</span>' : '')
      + (src.sql ? '<button type="button" class="ai365-rd-btn sm' + (sqlOpen ? ' on' : '') + '" data-rd-sql="' + E(chart.id) + '">' + T('조회 SQL') + '</button>' : '') + '</div>'
      + (sqlOpen && src.sql ? '<pre class="ai365-rd-sqlpre" data-i18n-skip>' + E(src.sql) + '</pre>' : '');
    return valuesTableHtml(vc, rdCompute(vc, src)) + note + dataTableHtml(src, rows, used);
  }
  function cellText(v, col) {
    if (typeof v !== 'number') return rdKey(v);
    if (Number.isInteger(v) && v >= 1000 && v <= 2999 && /연도|년도|년$|year|yr/i.test(col)) return String(v);   // 연도에는 천 단위 쉼표를 넣지 않는다 / no thousands separator for years
    return v.toLocaleString('ko-KR', { maximumFractionDigits: 4 });
  }
  function dataTableHtml(src, rows, used) {
    const head = src.columns.map(function (c) { return '<th' + (used && used.indexOf(c) >= 0 ? ' class="used"' : '') + '>' + E(c) + '</th>'; }).join('');
    const body = rows.slice(0, 200).map(function (r) {
      return '<tr>' + r.map(function (v, i) {
        const n = (src.types || {})[src.columns[i]] === 'number';
        return '<td' + (n ? ' class="num"' : '') + '>' + E(cellText(v, src.columns[i])) + '</td>';
      }).join('') + '</tr>';
    }).join('');
    return '<div class="ai365-rd-tbl" data-i18n-skip><table><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table></div>';
  }

  function cardBodyHtml(ctx, chart) {
    if (ctx.tableOf[chart.id]) return tableHtml(ctx, chart);
    const vc = viewChart(ctx, chart), comp = rdCompute(vc, viewSrc(ctx, chart));
    if (chart.type === 'kpi') {
      return '<div class="ai365-rd-kpi" data-i18n-skip><span class="v">' + E(rdFmt(comp.series[0].values[0], chart.unit)) + '</span><span class="l">' + E(comp.series[0].name) + '</span></div>';
    }
    if (!comp.x.length) return '<div class="ai365-rd-nodata"><span>' + T('필터에 맞는 데이터가 없습니다') + '</span></div>';
    return '<div class="ai365-rd-canvas"><canvas data-rd-canvas="' + E(chart.id) + '"></canvas>' + drillMenuHtml(ctx, chart.id) + '</div>';
  }

  /* ── 드릴다운(2026-09-21) — 막대·조각·점을 누르면 그 값으로 좁혀 다음 컬럼으로 내려간다. 화면 상태(ctx.drill)일 뿐 저장하지 않고,
     이미 받아 둔 Source 로 계산하므로 새 조회가 없다. 다음 컬럼 = 에이전트가 정해 둔 순서(chart.drill), 없으면 Source 에 남은 글자·기간 컬럼에서 고른다.
     Drill-down (2026-09-21): clicking a mark narrows the chart by that value and moves x to the next column. A view state
     (ctx.drill), never stored, computed from the source already in hand. The next column comes from the path the agent set
     (chart.drill), else it is picked from the source's remaining text and period columns. ── */
  /* 에이전트가 정해 둔 순서(chart.drill)의 다음 컬럼 — 아직 쓰지 않은 첫 컬럼, 다 썼으면 '' (2026-10-01: 받아 둔 데이터에 없는 컬럼이면 서버가 그 단계를 가져온다)
     The next column of the agent's path (chart.drill): the first one not used yet, '' when used up (2026-10-01: a column the
     fetched data lacks is fetched from the server) */
  function plannedNext(ctx, chart) {
    const path = (ctx.drill && ctx.drill[chart.id]) || [], vc = viewChart(ctx, chart);
    const used = [chart.x, chart.group, vc.x].concat(path.map(function (p) { return p.col; }));
    return (chart.drill || []).filter(function (c) { return used.indexOf(c) < 0; })[0] || '';
  }
  function drillNext(ctx, chart, vc, value) {
    const src = viewSrc(ctx, chart), path = (ctx.drill && ctx.drill[chart.id]) || [];
    const used = [chart.x, chart.group, vc.x].concat(path.map(function (p) { return p.col; }));
    if ((chart.drill || []).length) {   // 정해 둔 순서: 받아 둔 데이터에 있으면 여기서, 없으면 서버에서(pickOnCanvas) / planned: here when fetched, else the server
      const nx = plannedNext(ctx, chart);
      return nx && src.columns.indexOf(nx) >= 0 ? [nx] : [];
    }
    const rows = rdFilteredRows(src, vc.filters.concat([{ col: vc.x, selected: [value] }]));
    return src.columns.filter(function (c) {
      if (used.indexOf(c) >= 0 || !((src.types || {})[c] === 'text' || (src.periods || {})[c])) return false;
      const ci = src.columns.indexOf(c), seen = {};
      let n = 0;
      for (let i = 0; i < rows.length && n <= 40; i++) { const k = rdKey(rows[i][ci]); if (!seen[k]) { seen[k] = 1; n++; } }
      return n >= 2 && n <= 40;   // 값이 하나뿐이거나 너무 많은 컬럼은 내려가도 볼 것이 없다 / one value or too many values is not worth a level
    });
  }
  function drillInto(ctx, cid, col, value, next) {
    ctx.drill[cid] = ((ctx.drill[cid]) || []).concat([{ col: col, value: value, next: next }]);
    ctx.dmenu = null;
    refreshChart(ctx, cid, true);
  }

  /* ── 서버 드릴다운(2026-09-30) — 받아 둔 데이터에 더 내려갈 컬럼이 없으면(채팅 답변의 집계 결과 대부분) 그 Source 의 조회 SQL 을 서버가
     코드로 고쳐 한 단계를 가져온다(POST /api/reports/drill, LLM 없음, 지금 사용자의 권한). 가져온 단계는 경로(ctx.drill 의 remote 단계)마다
     ctx.dsrc 에 두고 화면에서만 쓴다(저장하지 않음). 서버가 "이 조회로는 안 된다"고 한 차트·단계는 ctx.dnone 에 적어 다시 묻지 않는다.
     ── Server drill-down (2026-09-30): when the fetched data has no deeper column (most aggregated chat answers), the server
     rewrites the source's query SQL by code and returns one level (POST /api/reports/drill, no LLM, the current user's
     permissions). Fetched levels are kept per path in ctx.dsrc and used on screen only (never stored). A chart and level the
     server declined is noted in ctx.dnone and not asked again. ── */
  const RD_MAX_DRILL = 3;   // = 서버 report_dash.MAX_DRILL / the server's MAX_DRILL
  function drillBase(src) { return (src.sql || '') + '|' + (src.fetched_at || ''); }
  /* 받아 둔 데이터만으로 내려갈 수 있는가 — 정해 둔 순서(chart.drill)가 남았거나, 어떤 축 값 안에서 2~40개로 나뉘는 글자·기간 컬럼이 있을 때
     (drillNext 와 같은 규칙) / whether the fetched data alone can go down: a planned column left, or a text/period column that splits
     some axis value into 2 to 40 values (the drillNext rule) */
  function localDrillable(ctx, chart) {
    const path = (ctx.drill && ctx.drill[chart.id]) || [], src = viewSrc(ctx, chart), vc = viewChart(ctx, chart);
    const used = [chart.x, chart.group, vc.x].concat(path.map(function (p) { return p.col; }));
    // 정해 둔 순서가 있으면 drillNext 처럼 그 순서만 본다(다 쓴 뒤 받아 둔 컬럼으로 돋보기를 켜면 눌러도 아무 일이 없다)
    // With a planned path only that path counts, as in drillNext (a zoom from other columns once it is used up would do nothing)
    if ((chart.drill || []).length) { const nx = plannedNext(ctx, chart); return !!nx && src.columns.indexOf(nx) >= 0; }
    const xi = src.columns.indexOf(vc.x);
    if (xi < 0) return false;
    const rows = rdFilteredRows(src, vc.filters);
    return src.columns.some(function (c, ci) {
      if (used.indexOf(c) >= 0 || !((src.types || {})[c] === 'text' || (src.periods || {})[c])) return false;
      const per = {};
      for (let i = 0; i < rows.length; i++) { const k = rdKey(rows[i][xi]); (per[k] = per[k] || {})[rdKey(rows[i][ci])] = 1; }
      return Object.keys(per).some(function (k) { const n = Object.keys(per[k]).length; return n >= 2 && n <= 40; });
    });
  }
  function probeKey(ctx, chart) {   // 필터가 바뀌면 답도 달라질 수 있다 / a filter change can change the answer
    return chart.id + '|' + drillBase(srcOf(ctx.state, chart.source)) + '|' + rdDrillSig((ctx.drill && ctx.drill[chart.id]) || [])
      + '|' + JSON.stringify(drillFilters(ctx, chart));
  }
  /* 막대를 눌러 더 내려갈 수 있는가 — 받아 둔 데이터로 되거나, 조회 SQL 이 있어 서버에서 한 단계를 더 가져올 수 있을 때(서버의 사전 확인이
     아니라고 했거나 한 번 거절한 단계는 제외). 커서의 돋보기와 클릭이 같은 판단을 쓴다.
     Whether a click can go one level down: with the fetched data, or from the server when the source has SQL (unless the server's
     probe said no or it declined this level once). The zoom cursor and the click share it. */
  function canDrill(ctx, chart) {
    if (!chart || chart.type === 'kpi') return false;
    const path = (ctx.drill && ctx.drill[chart.id]) || [];
    if (localDrillable(ctx, chart)) return true;       // 받아 둔 데이터로는 컬럼이 남는 만큼 / locally, as deep as columns remain
    if (path.length >= RD_MAX_DRILL) return false;     // 서버 단계는 3단계까지 / server levels stop at three
    const root = srcOf(ctx.state, chart.source), no = (ctx.dnone || {})[chart.id];
    if (!root || !root.sql || (no && no.base === drillBase(root) && no.levels[path.length])) return false;
    // 정해 둔 순서는 그 컬럼으로 서버에서(사전 확인 없이, 다 쓰면 끝), 아니면 사전 확인이 아니라고 하지 않은 동안
    // a planned path goes to the server with its column (no probe, done when used up); otherwise while the probe has not said no
    if ((chart.drill || []).length) return !!plannedNext(ctx, chart);
    return (ctx.dprobe || {})[probeKey(ctx, chart)] !== false;
  }
  /* 서버에서만 내려갈 수 있는 자리면 그 단계에 누를 값이 있는지 한 번 묻는다(결과가 오기 전에는 돋보기를 보인다). 없으면 커서를 바로 끈다.
     Where only the server can go further, ask once whether the level has anything to click (the zoom shows until the answer);
     a no turns the cursor off right away. */
  function ensureProbe(ctx, chart) {
    if (!ctx.dprobe || !chart || chart.type === 'kpi' || !ctx.root) return;
    const path = (ctx.drill && ctx.drill[chart.id]) || [], root = srcOf(ctx.state, chart.source);
    if (path.length >= RD_MAX_DRILL || !root || !root.sql || (chart.drill || []).length || localDrillable(ctx, chart)) return;   // 정해 둔 순서는 묻지 않는다 / a planned path needs no probe
    const key = probeKey(ctx, chart);
    if (key in ctx.dprobe) return;
    ctx.dprobe[key] = 'wait';
    api('/api/reports/drill', 'POST', { acting_user_id: acting(), sql: root.sql, probe: true, x: viewChart(ctx, chart).x,
      path: path.map(function (p) { return { col: p.col, value: p.value }; }), filters: drillFilters(ctx, chart) })
      .then(function (d) { return !!(d && d.status === 'probe' && d.drillable); }, function () { return true; })   // 확인 실패는 눌러 보게 둔다 / a failed probe leaves the click to try
      .then(function (ok) {
        ctx.dprobe[key] = ok;
        if (!ok && ctx.root && chartOf(ctx.state, chart.id) && probeKey(ctx, chart) === key && ctx.charts.get(chart.id)) refreshChart(ctx, chart.id);
      });
  }
  /* 차트 필터를 서버가 쓸 값 목록으로 — 범위·최근 N 도 받아 둔 데이터에서 통과한 값으로 바꾼다(값 컬럼 필터는 서버가 건너뛴다)
     The chart's filters as value lists for the server; ranges and "last N" become the values that pass (measure filters are skipped there) */
  function drillFilters(ctx, chart) {
    const root = srcOf(ctx.state, chart.source);
    return (chart.filters || []).filter(function (f) { return root.columns.indexOf(f.col) >= 0 && (f.range || (f.selected || []).length); }).map(function (f) {
      const ci = root.columns.indexOf(f.col), seen = {}, values = [];
      rdFilteredRows(root, [f]).forEach(function (r) { const k = rdKey(r[ci]); if (!seen[k]) { seen[k] = 1; values.push(k); } });
      return { col: f.col, values: values };
    }).filter(function (f) { return f.values.length && f.values.length < 200; });
  }
  function drillVeil(ctx, cid, on) {
    const card = ctx.root && ctx.root.querySelector('[data-rd-card="' + cid + '"]');
    if (!card) return;
    const old = card.querySelector('[data-rd-dveil]');
    if (old) old.remove();
    if (on) card.insertAdjacentHTML('afterbegin', '<div class="ai365-rd-veil" data-rd-dveil><span class="ai365-rd-spin"></span><span>' + T('불러오는 중…') + '</span></div>');
  }
  function drillRemote(ctx, cid, col, value, next, pos) {
    const chart = chartOf(ctx.state, cid), root = chart && srcOf(ctx.state, chart.source);
    if (!root || !root.sql || ctx.dbusy) return;
    const before = (ctx.drill[cid] || []).slice(), sig = rdDrillSig(before), base = drillBase(root);
    const path = before.map(function (p) { return { col: p.col, value: p.value }; }).concat([{ col: col, value: value }]);
    const filters = drillFilters(ctx, chart), filt = JSON.stringify(filters);
    ctx.dbusy = cid; ctx.dmenu = null; paintDrillMenu(ctx); drillVeil(ctx, cid, true);
    // 답이 오지 않으면 30초 뒤 기다림을 푼다(기다리는 동안에는 다른 막대를 눌러도 삼켜진다) / give up after 30 seconds (clicks are swallowed while waiting)
    const late = new Promise(function (_, reject) { setTimeout(function () { reject(new Error(T('하위 데이터를 조회하지 못했습니다'))); }, 30000); });
    Promise.race([api('/api/reports/drill', 'POST', { acting_user_id: acting(), sql: root.sql, path: path, next: next || '', filters: filters }), late])
      .then(function (d) {
        if (ctx.dbusy === cid) ctx.dbusy = '';
        drillVeil(ctx, cid, false);
        const now = chartOf(ctx.state, cid), nroot = now && srcOf(ctx.state, now.source);
        // 기다리는 사이 화면이 바뀌었으면(다른 단계 · 새 데이터 · 바뀐 필터 · 지운 차트 · 닫은 화면) 답을 버린다 / drop the answer when the view moved on
        if (!ctx.root || !now || !nroot || drillBase(nroot) !== base || rdDrillSig(ctx.drill[cid] || []) !== sig
          || JSON.stringify(drillFilters(ctx, now)) !== filt) return;
        if (d.status === 'ok' && d.source) {
          const np = before.concat([{ col: col, value: value, next: d.next, remote: true }]);
          (ctx.dsrc[cid] = ctx.dsrc[cid] || {})[rdDrillSig(np)] = { src: d.source, base: base, filt: filt };
          ctx.drill[cid] = np;
          refreshChart(ctx, cid, true);
        } else if (d.status === 'choose' && (d.candidates || []).length) {
          ctx.dmenu = Object.assign({ cid: cid, col: col, value: value, remote: true,
            cols: d.candidates.map(function (c) { return c.column; }) }, pos || { left: 8, top: 8 });
          paintDrillMenu(ctx);
        } else {
          if (d.scope === 'chart') {   // 이 조회로는 어느 값도 안 된다 — 이 단계의 돋보기를 끈다 / no value works with this query: drop the zoom cursor at this level
            const no = (ctx.dnone[cid] && ctx.dnone[cid].base === base) ? ctx.dnone[cid] : (ctx.dnone[cid] = { base: base, levels: {} });
            no.levels[before.length] = true;
            refreshChart(ctx, cid);
          }
          say(T(d.reason || '이 데이터에는 더 내려갈 컬럼이 없습니다.'));
        }
      })
      .catch(function (err) {
        if (ctx.dbusy === cid) ctx.dbusy = '';
        drillVeil(ctx, cid, false);
        if (ctx.root) say(err.message || T('하위 데이터를 조회하지 못했습니다'));   // 닫은 화면에는 알리지 않는다 / not for a closed view
      });
  }
  /* 새 데이터·바뀐 차트 뒤에도 드릴다운 경로가 맞는가 — 받아 둔 단계는 컬럼이, 서버에서 가져온 단계는 같은 조회의 같은 데이터가 있어야 한다
     Whether a drill path still holds after new data or a changed chart: fetched-data levels need their columns, server levels the same query */
  function drillValid(ctx, cid) {
    const c = chartOf(ctx.state, cid), root = c && srcOf(ctx.state, c.source), path = (ctx.drill || {})[cid] || [];
    if (!c || !root || !path.length || path[0].col !== c.x) return false;
    let src = root;
    for (let i = 0; i < path.length; i++) {
      const p = path[i];
      if (src.columns.indexOf(p.col) < 0) return false;
      if (p.remote) {
        const hit = ((ctx.dsrc || {})[cid] || {})[rdDrillSig(path.slice(0, i + 1))];
        if (!hit || hit.base !== drillBase(root)) return false;
        src = hit.src;
      } else if (src.columns.indexOf(p.next) < 0) return false;
    }
    return true;
  }
  /* 필터가 바뀌면 서버에서 가져온 단계는 낡는다(예전 필터로 조회했다) — 처음 낡은 서버 단계 바로 앞까지 돌아간다
     A filter change makes server levels stale (fetched under the old filters): go back to just before the first stale one */
  function drillFresh(ctx, cid) {
    const path = (ctx.drill || {})[cid] || [], chart = chartOf(ctx.state, cid);
    if (!chart || !path.some(function (p) { return p.remote; })) return;
    const want = JSON.stringify(drillFilters(ctx, chart)), cache = (ctx.dsrc || {})[cid] || {};
    for (let i = 0; i < path.length; i++) {
      if (!path[i].remote) continue;
      const hit = cache[rdDrillSig(path.slice(0, i + 1))];
      if (hit && hit.filt === want) continue;
      ctx.drill[cid] = path.slice(0, i);
      delete ctx.dsrc[cid];
      if (ctx.dmenu && ctx.dmenu.cid === cid) ctx.dmenu = null;
      return;
    }
  }
  /* 캔버스 클릭이 막대·조각·점 위였으면 드릴다운하고 true — 빈 곳이거나 내려갈 곳이 없으면 false(카드의 대상 선택으로 넘어간다) */
  /* A canvas click on a mark drills down and returns true; empty space or nowhere to go returns false so the card's own click handling goes on */
  function pickOnCanvas(ctx, cv, e) {
    const cid = cv.dataset.rdCanvas, chart = chartOf(ctx.state, cid), inst = ctx.charts.get(cid);
    if (!chart || !inst || !canDrill(ctx, chart)) return false;
    const idx = rdPickIndex(inst, e);
    if (idx < 0) return false;
    if (ctx.dbusy) return true;   // 한 단계를 가져오는 중 — 거듭 누르지 않는다 / a level is being fetched
    const vc = viewChart(ctx, chart), value = rdCompute(vc, viewSrc(ctx, chart)).x[idx];
    if (value === undefined || ((vc.type === 'pie' || vc.type === 'donut') && value === OTHERS)) return true;
    const box = cv.getBoundingClientRect();
    const pos = { left: Math.max(4, Math.min(e.clientX - box.left, box.width - 196)), top: Math.max(4, Math.min(e.clientY - box.top, box.height - 40)) };
    const cols = drillNext(ctx, chart, vc, value);
    if (cols.length === 1) { drillInto(ctx, cid, vc.x, value, cols[0]); return true; }
    if (cols.length) { ctx.dmenu = Object.assign({ cid: cid, col: vc.x, value: value, cols: cols }, pos); paintDrillMenu(ctx); return true; }
    const root = srcOf(ctx.state, chart.source);   // 받아 둔 데이터로는 더 없다 — 서버에서 한 단계 / nothing further locally: one level from the server
    if (!root || !root.sql) return false;
    drillRemote(ctx, cid, vc.x, value, plannedNext(ctx, chart), pos);   // 정해 둔 순서면 그 컬럼, 아니면 서버가 후보를 찾는다 / the planned column, else the server's candidates
    return true;
  }
  function drillMenuHtml(ctx, cid) {
    const m = ctx.dmenu;
    if (!m || m.cid !== cid) return '';
    return '<div class="ai365-rd-fmenu ai365-rd-colmenu ai365-rd-dmenu" data-rd-dmenu style="left:' + m.left + 'px;top:' + m.top + 'px"><div class="cap"><span data-i18n-skip>' + E(m.value) + '</span> <span>' + T('안쪽 보기') + '</span></div>'
      + '<div class="vals" data-i18n-skip>' + m.cols.map(function (c) { return '<button type="button" data-rd-dpick="' + E(c) + '">' + E(c) + '</button>'; }).join('') + '</div></div>';
  }
  function paintDrillMenu(ctx) {
    ctx.root.querySelectorAll('[data-rd-dmenu]').forEach(function (el) { el.remove(); });
    const m = ctx.dmenu, host = m && ctx.root.querySelector('[data-rd-body="' + m.cid + '"] .ai365-rd-canvas');
    if (host) host.insertAdjacentHTML('beforeend', drillMenuHtml(ctx, m.cid));
  }
  function crumbsHtml(ctx, chart) {
    const path = (ctx.drill && ctx.drill[chart.id]) || [];
    if (!path.length) return '';
    return '<button type="button" class="ai365-rd-crumb" data-rd-drillto="' + E(chart.id) + ':0">' + IC.back + '<span data-i18n-skip>' + E(chart.x) + '</span> <span>' + T('전체') + '</span></button>'
      + path.map(function (p, i) {
        return '<span class="sep">›</span><button type="button" class="ai365-rd-crumb' + (i === path.length - 1 ? ' cur' : '') + '" data-rd-drillto="' + E(chart.id) + ':' + (i + 1) + '" data-i18n-skip>' + E(p.value === '' ? T('(빈 값)') : p.value) + '</button>';
      }).join('') + '<span class="sep">›</span><span class="lv" data-i18n-skip>' + E(path[path.length - 1].next) + '</span>';
  }
  /* 강조 범례 — 색만으로 구분하지 않게 규칙 이름·개수·해당 항목을 글로 같이 보여 준다 / the highlight legend spells out the rule, the count and the items */
  function notable(chart) { return ['pie', 'donut', 'kpi'].indexOf(chart.type) < 0; }
  /* 메모 달기(2026-09-21 사용자 지시: AI 없이 붙인다) — 카드의 [메모] 버튼이 여는 한 줄: 어느 항목에 + 무슨 글을 */
  /* Adding a note (2026-09-21, user decision: no AI involved): the one-line form behind the card's [note] button */
  function noteFormHtml(ctx, chart) {
    if (ctx.readonly || ctx.noteOpen !== chart.id || !notable(chart)) return '';
    const labels = rdCompute(chart, srcOf(ctx.state, chart.source)).x, taken = (chart.notes || []).map(function (n) { return n.x; });
    return '<span class="lb">' + IC.note + '</span><select data-rd-notex data-i18n-skip aria-label="' + E(T('메모를 달 항목')) + '">'
      + labels.map(function (v) { return '<option value="' + E(v) + '">' + E(v === '' ? '(빈 값)' : v) + (taken.indexOf(v) >= 0 ? ' *' : '') + '</option>'; }).join('') + '</select>'
      + '<input type="text" data-rd-notetext maxlength="30" placeholder="' + E(T('메모 내용 (예: 신제품 출시)')) + '">'
      + '<button type="button" class="ai365-rd-btn sm pri" data-rd-noteadd="' + E(chart.id) + '">' + T('메모 달기') + '</button><span class="err" data-rd-noteerr></span>';
  }
  function paintNoteForm(ctx, cid) {
    const host = ctx.root.querySelector('[data-rd-notef="' + cid + '"]'), chart = chartOf(ctx.state, cid);
    if (host && chart) host.innerHTML = noteFormHtml(ctx, chart);
    const btn = ctx.root.querySelector('[data-rd-note="' + cid + '"]');
    if (btn) btn.classList.toggle('on', ctx.noteOpen === cid);
  }
  /* 비교 묶음의 값 범위(같은 묶음의 차트가 값 축 눈금을 같이 쓴다) — 묶음이 아니면 null / the shared value range of a compare group, else null */
  function lockOf(ctx, chart) {
    if (!chart.compare || (ctx.drill[chart.id] || []).length) return null;
    const group = ctx.state.charts.filter(function (c) { return c.compare === chart.compare && !(ctx.drill[c.id] || []).length; });
    if (group.length < 2) return null;
    return rdCompareRange(group.map(function (c) { return [c, rdCompute(c, srcOf(ctx.state, c.source))]; }));
  }
  function marksHtml(ctx, chart) {
    const path = (ctx.drill && ctx.drill[chart.id]) || [];
    if (path.length || ctx.tableOf[chart.id]) return '';
    const rm = function (attr, title) { return ctx.readonly ? '' : '<button type="button" ' + attr + ' title="' + E(T(title)) + '">' + IC.x + '</button>'; };
    const group = chart.compare ? ctx.state.charts.filter(function (c) { return c.compare === chart.compare; }) : [];
    const cmp = group.length > 1 ? '<span class="ai365-rd-mk cmp" title="' + E(group.map(function (c) { return c.title; }).join(' · ')) + '">' + IC.scale + '<b>' + T('비교 묶음') + '</b><span class="nm">' + T('눈금 맞춤') + '</span>'
      + rm('data-rd-cmprm="' + E(chart.id) + '"', '비교 묶음에서 빼기') + '</span>' : '';
    const notes = (chart.notes || []).map(function (n) {
      return '<span class="ai365-rd-mk note">' + IC.note + '<b data-i18n-skip>' + E(n.x === '' ? '(빈 값)' : n.x) + '</b><span class="nm" data-i18n-skip title="' + E(n.text) + '">' + E(n.text) + '</span>'
        + rm('data-rd-noterm="' + E(chart.id) + ':' + E(n.id) + '"', '메모 삭제') + '</span>';
    }).join('');
    const comp = rdCompute(chart, srcOf(ctx.state, chart.source)), base = (PALETTES[(chart.style || {}).palette] || PALETTES.indigo);
    let trend = '';
    if (chart.trend) {   // 추세·예측 칩 — 기울기와 예측 길이를 글로도 보여 준다 / the trend chip spells out the slope and the forecast length
      const tr = comp.trend, unit = (chart.y[0] && chart.y[0].unit) || chart.unit || '';
      const parts = [];
      if (tr && chart.trend.line) parts.push((isEn() ? 'per period ' : '한 기간에 ') + (tr.slope > 0 ? '+' : '') + rdFmt(tr.slope, unit));
      if (tr && tr.forecast) parts.push(isEn() ? tr.forecast.labels.length + ' periods ahead (reference)' : '앞으로 ' + tr.forecast.labels.length + '개 기간(참고용)');
      else if (chart.trend.forecast) parts.push(T('예측은 점이 6개 이상일 때만 그립니다'));
      trend = '<span class="ai365-rd-mk trend">' + IC.trend + '<b>' + T(chart.trend.forecast ? '추세·예측' : '추세선') + '</b><span class="nm"' + (parts.length ? ' data-i18n-skip' : '') + '>' + E(parts.join(' · ')) + '</span>'
        + rm('data-rd-trendrm="' + E(chart.id) + '"', '추세선·예측 지우기') + '</span>';
    }
    return cmp + trend + notes + (comp.marks || []).map(function (m) {
      const names = m.hits.map(function (i) { return comp.x[i]; });
      return '<span class="ai365-rd-mk"><i style="background:' + E(m.color || base[m.series % base.length]) + '"></i><b data-i18n-skip>' + E(m.label) + '</b><em data-i18n-skip>' + names.length + '</em>'
        + (names.length ? '<span class="nm" data-i18n-skip title="' + E(names.join(', ')) + '">' + E(names.slice(0, 4).join(', ') + (names.length > 4 ? ' …' : '')) + '</span>' : '')
        + (ctx.readonly ? '' : '<button type="button" data-rd-hlrm="' + E(chart.id) + ':' + E(m.id) + '" title="' + E(T('강조 삭제')) + '">' + IC.x + '</button>') + '</span>';
    }).join('');
  }

  /* 발치 첫 탭의 이름 = 차트 종류(2026-10-13 디자인: [Bar | Table]) / the chart type names the first footer tab */
  function typeLabel(chart) { return { bar: 'Bar', hbar: 'Bar', line: 'Line', area: 'Area', pie: 'Pie', donut: 'Donut', kpi: 'KPI' }[chart.type] || 'Chart'; }
  /* 카드 ⋮ 메뉴(2026-10-13 디자인): 필터 · 메모 달기 · 복제 · 다시 실행 · 다운로드 · 게시판으로 공유 · 메일로 공유 · 저장 · 삭제.
     버전 미리보기 중에는 바꾸는 항목이 잠긴다(다운로드만 된다). 항목의 data 속성은 종전 버튼과 같아 처리기는 그대로다.
     The card's kebab menu. While a version is previewed every changing item is disabled (only download works). The items keep
     the old buttons' data attributes, so the handlers are unchanged. */
  function cardMenuHtml(ctx, chart) {
    const src = srcOf(ctx.state, chart.source), fl = chart.filters || [], pv = !!ctx.preview, busy = !!ctx.busy;
    const canFilter = !pv && fl.length < 4 && !!src && src.columns.some(function (c) { return !fl.some(function (f) { return f.col === c; }); });
    const item = function (attr, icon, label, off, cls) {
      return '<button type="button" ' + attr + (off ? ' disabled' : '') + (cls ? ' class="' + cls + '"' : '') + '>' + icon + '<span>' + T(label) + '</span></button>';
    };
    return '<div class="ai365-rd-smenu ai365-rd-cmenu" data-rd-smenu>'
      + item('data-rdf-add="' + E(chart.id) + '"', IC.filter, '필터', !canFilter)
      + (notable(chart) ? item('data-rd-note="' + E(chart.id) + '"', IC.note, '메모 달기', pv) : '')
      + item('data-rd-dup="' + E(chart.id) + '"', IC.copy, '복제', pv || busy)
      + item('data-rd-regen="' + E(chart.id) + '"', IC.regen, '다시 실행', pv || busy)
      + item('data-rd-down="' + E(chart.id) + '"', IC.down, '다운로드', false)
      + item('data-rd-sm="board" data-cid="' + E(chart.id) + '"', IC.board, '게시판으로 공유', pv)
      + item('data-rd-sm="mail" data-cid="' + E(chart.id) + '"', IC.mail, '메일로 공유', pv)
      + item('data-rd-save="' + E(chart.id) + '"', IC.save, '저장', pv)
      + item('data-rd-del="' + E(chart.id) + '"', IC.trash, '삭제', pv || busy, 'danger') + '</div>';
  }
  function cardHtml(ctx, chart) {
    const tbl = !!ctx.tableOf[chart.id], filters = chartFiltersHtml(ctx, chart), ex = ctx.expanded === chart.id;
    // 머리 도구 = [펼치기][⋮] (2026-10-13 디자인) — 나머지 작업은 ⋮ 메뉴 / header tools: expand and the kebab; everything else lives in the menu
    const tools = (ctx.readonly && !ctx.preview) ? '' : '<span class="tools">'
      + '<button type="button" class="ai365-rd-ib" data-rd-expand="' + E(chart.id) + '" title="' + E(T(ex ? '카드 접기' : '카드 펼치기')) + '">' + (ex ? IC.collapse : IC.expand) + '</button>'
      + '<button type="button" class="ai365-rd-ib" data-rd-cmenu="' + E(chart.id) + '" title="' + E(T('카드 메뉴')) + '" aria-haspopup="true">' + IC.dots + '</button></span>';
    return '<section class="ai365-rd-card' + (chart.size === 'full' ? ' full' : '') + (ex ? ' expanded' : '') + (ctx.focus === chart.id ? ' focus' : '') + '" data-rd-card="' + E(chart.id) + '">'
      + (ctx.regen === chart.id ? '<div class="ai365-rd-veil"><span class="ai365-rd-spin"></span><span>' + T('다시 만드는 중…') + '</span></div>' : '')
      + '<div class="ai365-rd-chd"><b data-i18n-skip title="' + E(chart.title) + '">' + E(chart.title) + '</b>'
      + (ctx.readonly ? '' : '<span class="ai365-rd-tgt">' + T('대상') + '</span>') + tools + '</div>'
      + (chart.subtitle ? '<div class="ai365-rd-sub" data-i18n-skip>' + E(chart.subtitle) + '</div>' : '')
      + '<div class="ai365-rd-cf" data-rd-cf="' + E(chart.id) + '"' + (filters ? '' : ' hidden') + '>' + filters + '</div>'
      + '<div class="ai365-rd-notef" data-rd-notef="' + E(chart.id) + '">' + noteFormHtml(ctx, chart) + '</div>'
      + '<div class="ai365-rd-cbody" data-rd-focus="' + E(chart.id) + '"><div class="ai365-rd-crumbs" data-rd-crumbs="' + E(chart.id) + '">' + crumbsHtml(ctx, chart) + '</div>'
      + '<div data-rd-body="' + E(chart.id) + '">' + cardBodyHtml(ctx, chart) + '</div>'
      + '<div class="ai365-rd-mks" data-rd-marks="' + E(chart.id) + '">' + marksHtml(ctx, chart) + '</div>'
      // 인사이트는 맨 위 단계의 설명이라 드릴다운 중에는 숨긴다(강조·메모와 같다) / the insight describes the top level, hidden while drilled like highlights and notes
      + (chart.insight ? '<div class="ai365-rd-ins" data-rd-ins="' + E(chart.id) + '"' + (((ctx.drill || {})[chart.id] || []).length ? ' hidden' : '') + '><b data-i18n-skip>Insight</b><span data-i18n-skip>' + E(chart.insight) + '</span></div>' : '') + '</div>'
      // 발치 = [차트 종류 | Table] (2026-10-13 디자인; 원본 테이블 · 조회 SQL 은 Table 보기 머리에) / footer tabs; the source table and SQL live in the Table view
      + '<div class="ai365-rd-cft"><button type="button" class="ai365-rd-vt' + (tbl ? '' : ' on') + '" data-rd-view="' + E(chart.id) + ':chart">' + IC.chart + '<span data-i18n-skip>' + typeLabel(chart) + '</span></button>'
      + '<button type="button" class="ai365-rd-vt' + (tbl ? ' on' : '') + '" data-rd-view="' + E(chart.id) + ':table">' + IC.table + '<span data-i18n-skip>Table</span></button></div></section>';
  }

  /* ── KPI 카드(요약 숫자) 줄 — 2026-10-12 사용자 결정: 첫 화면에 자동으로 놓지 않는다. [+ KPI 카드] · [추천 채우기] · 대화로 요청해야 생기고,
     카드를 누르면 줄 아래에 편집 폼이 열려 이름 · 값(데이터에서 계산 = Source · 컬럼 · 집계 | 직접 적은 숫자) · 단위 · 연결 차트(그 필터를 따라감) ·
     직전 기간 대비 · 설명 한 줄을 바꾼다(LLM 없음, ops kpi_add / kpi_set, 되돌리기 대상). 데이터 카드의 숫자는 rdKpi 가 계산한다(서버 kpi_value 와 같은 규칙).
     폼 라벨의 영어는 전역 사전 대신 KPI_EN 에 둔다('데이터' · '합계' 같은 낱말이 앱 전체 사전에 섞이지 않게).
     The KPI card row (summary numbers), user decision 2026-10-12: nothing is placed on the first screen; cards come from
     [+ KPI card], [Fill suggestions] or the conversation. Clicking a card opens the editor under the row: name, value (computed
     from data = source · column · aggregation, or a typed number), unit, linked chart (follows its filters), previous-period
     change and a one-line note (no LLM, ops kpi_add / kpi_set, undoable). rdKpi computes a data card's number (same rules as
     the server's kpi_value). The form's English labels live in KPI_EN, not the app-wide dictionary (generic words stay out of it). ── */
  const MAX_KPIS = 8;   // = app/report_dash.MAX_KPIS
  const KPI_AGG = { sum: '합계', avg: '평균', count: '건수', min: '최솟값', max: '최댓값', first: '첫 값' };
  const KPI_EN = { '이름': 'Name', '값': 'Value', '숫자': 'Number', '데이터': 'Data', '컬럼': 'Column', '집계': 'Aggregation', '행 수': 'Row count', '단위': 'Unit',
    '연결 차트': 'Linked chart', '설명': 'Note', '합계': 'Sum', '평균': 'Average', '건수': 'Count', '최솟값': 'Minimum', '최댓값': 'Maximum', '첫 값': 'First value',
    '없음': 'None', '직접 입력': 'Typed number', '데이터에서 계산': 'Computed from data', '미리보기': 'Preview', '적용': 'Apply', '취소': 'Cancel', '삭제': 'Delete',
    '예: 총 매출': 'e.g. Total sales', '예: 1200': 'e.g. 1200', '원 · % · 건': 'e.g. $, %, pcs', '카드 아래 한 줄 (선택)': 'One line under the card (optional)',
    '연결한 차트의 필터를 따라갑니다': "Follows the linked chart's filters", '마지막 기간과 그 앞 기간을 비교합니다': 'Compares the last period with the one before',
    '기간 컬럼이 있는 데이터에서만 됩니다': 'Needs data with a period column', '누르면 이 카드를 편집합니다': 'Click to edit this card',
    '값 컬럼으로 카드를 골라 넣습니다': 'Picks value columns as cards', '카드 이름을 적어 주세요.': 'Give the card a name.',
    'KPI 카드는 8장까지입니다': 'Up to 8 KPI cards', '이름 없음': 'Untitled', '예: 연간 목표': 'e.g. Yearly target', '비우면 컬럼 · 집계 이름이 붙습니다': 'Leave empty for the column and aggregation name',
    '보여 줄 숫자를 적어 주세요.': 'Type the number to show.', '데이터와 컬럼을 골라 주세요.': 'Pick the data and a column.' };
  function TK(ko) { return isEn() ? (KPI_EN[ko] || T(ko)) : ko; }
  function kpiRoots(state) { return state.sources.filter(function (s) { return !(s.origin && s.origin.clone_of) && (s.rows || []).length; }); }   // 복제본은 같은 데이터 / clones share their rows
  function kpiLineage(state, sid) { const s = srcOf(state, sid); return (s && s.origin && s.origin.clone_of) || sid; }
  function kpiFirstCol(src) {   // 기본 컬럼 = 기간이 아닌 첫 숫자 컬럼, 없으면 행 수 / the first non-period numeric column, else the row count
    return src ? (src.columns.filter(function (c) { return src.types[c] === 'number' && !(src.periods || {})[c]; })[0] || '*') : '*';
  }
  function kpiNumeric(src, col) { return !!src && col !== '*' && src.types[col] === 'number'; }
  // = app/report_dash._RATE_COL ∪ RATE_ONLY · _PERIOD_COL · _ID_COL / the server's rate, period and id column rules
  const KPI_RATE_RE = /률|율|비중|평균|단가|점수|percent|rate|ratio|avg|pct|%|share/i, KPI_PERIOD_RE = /date|month|year|week|quarter|일자|날짜|연도|년도|월|분기|기간|주차/i, KPI_ID_RE = /(^|_)(id|no|code|seq)$|번호|코드|사번/i;
  function kpiDefaultAgg(src, col) { return !kpiNumeric(src, col) ? 'count' : (KPI_RATE_RE.test(col) ? 'avg' : 'sum'); }   // 비율은 평균 / rates average
  function kpiSuggestible(state) {   // [추천 채우기]가 넣을 게 있는가 — 서버 auto_kpis 와 같은 규칙(첫 원본 Source 의 값 컬럼 3개 중 아직 없는 것) / whether [Fill suggestions] has anything, the server's rule
    const src = kpiRoots(state)[0];
    if (!src) return false;
    const have = (state.kpis || []).map(function (k) { return k.source + ':' + k.col; });
    return src.columns.filter(function (c) { return src.types[c] === 'number' && !(src.periods || {})[c] && !KPI_PERIOD_RE.test(c) && !KPI_ID_RE.test(c); }).slice(0, 3)
      .some(function (c) { return have.indexOf(src.id + ':' + c) < 0; });
  }
  function kpiFirstChart(state, sid) { const c = state.charts.filter(function (c) { return kpiLineage(state, c.source) === kpiLineage(state, sid); })[0]; return c ? c.id : ''; }
  function kpiSpec(d) {   // 폼 초안 → 서버에 보내는 카드 설정 / the draft → the spec sent to the server
    if (d.mode === 'manual') return { label: d.label, value: d.value, unit: d.unit, note: d.note };
    return { label: d.label, source: d.source, col: d.col, agg: d.agg, unit: d.unit, link: d.link, delta: d.delta ? 'prev' : '', note: d.note };
  }
  function kpiArrow(v) { return v.delta > 0 ? '▲ ' : (v.delta < 0 ? '▼ ' : ''); }
  function kpiTileHtml(ctx, k, opts) {   // opts.preview: 대화 상자의 미리보기(버튼 없음) / the dialog's preview (no buttons)
    const v = rdKpi(k, ctx.state), chart = k.link ? chartOf(ctx.state, k.link) : null, can = !ctx.readonly && !(opts && opts.preview);
    const filtered = chart && (chart.filters || []).some(function (f) { return (f.selected || []).length || f.range; });
    const editing = can && ctx.kpiEdit && ctx.kpiEdit.id === k.id, title = can ? TK('누르면 이 카드를 편집합니다') : (chart ? chart.title : '');
    let delta = '';
    if (v.delta !== null && v.delta !== undefined) {
      delta = '<span class="d ' + (v.delta > 0 ? 'up' : (v.delta < 0 ? 'down' : '')) + '" data-i18n-skip>' + kpiArrow(v) + E(rdFmt(Math.abs(v.delta), '%')) + '</span>'
        + '<span class="p"><span data-i18n-skip>' + E(v.period) + '</span> · <span>' + T('직전 기간 대비') + '</span></span>';
    }
    return '<div class="ai365-rd-kt' + (can ? ' can' : '') + (editing ? ' edit' : '') + '" data-rd-kpi="' + E(k.id) + '"'
      + (title ? ' title="' + E(title) + '"' : '') + '><span class="l" data-i18n-skip>' + E(k.label) + '</span><b class="v" data-i18n-skip>' + (E(rdFmt(v.value, k.unit)) || '–') + '</b>'
      + '<span class="m">' + delta + (filtered ? '<span class="f">' + T('필터 적용 중') + '</span>' : '') + (v.manual ? '<span>' + TK('직접 입력') + '</span>' : '') + '</span>'
      + (k.note ? '<span class="n" data-i18n-skip title="' + E(k.note) + '">' + E(k.note) + '</span>' : '')
      + (can ? '<span class="acts"><button type="button" data-rd-kpied="' + E(k.id) + '" title="' + E(T('KPI 카드 편집')) + '">' + IC.pen + '</button>'
        + '<button type="button" class="rm" data-rd-kpirm="' + E(k.id) + '" title="' + E(T('KPI 카드 삭제')) + '">' + IC.x + '</button></span>' : '') + '</div>';
  }
  function kpisHtml(ctx) {   // 타일만 — 추가는 제목 줄의 [+ KPI 카드] 버튼, 편집은 대화 상자(2026-10-12 사용자 피드백: 추가 타일이 격자 한 칸을 차지했다)
    // Tiles only: adding lives in the title row's [+ KPI card] button and editing in a dialog (user feedback 2026-10-12: the add tile took a grid slot)
    const list = ctx.state.kpis || [];
    if (!list.length || (ctx.session && ctx.session.pending_auto)) return '';
    return '<div class="ai365-rd-kpis">' + list.map(function (k) { return kpiTileHtml(ctx, k); }).join('') + '</div>';
  }
  function kpiAutoLabel(d) { return d.col === '*' ? '건수' : (d.col ? d.col + ' ' + (KPI_AGG[d.agg] || '') : ''); }   // = 서버가 이름을 비우면 붙이는 이름 / the server's default name
  function kpiDraftKpi(d) {   // 폼 초안 → 미리보기 타일에 그릴 카드 / the draft as a card for the preview tile
    const label = d.label.trim() || (d.mode === 'manual' ? TK('이름 없음') : kpiAutoLabel(d));
    if (d.mode === 'manual') { const n = rdNum(d.value); return { id: '', source: '', col: '', agg: '', label: label, unit: d.unit, link: '', delta: '', value: n === null ? null : n, note: d.note }; }
    return { id: '', source: d.source, col: d.col, agg: d.agg, label: label, unit: d.unit, link: d.link, delta: d.delta ? 'prev' : '', note: d.note };
  }
  function kpiFormHtml(ctx) {   // 편집 대화 상자 — 미리보기 타일 · 이름 · 값 방식(데이터에서 계산 | 직접 입력) · 컬럼 · 집계 · 단위 · 연결 차트 · 직전 기간 대비 · 설명
    // The editor dialog: preview tile, name, value kind (computed | typed), column, aggregation, unit, linked chart, previous-period change, note
    const d = ctx.kpiEdit;
    if (!d || ctx.readonly) return '';
    const roots = kpiRoots(ctx.state), src = srcOf(ctx.state, d.source), manual = d.mode === 'manual';
    const opt = function (v, t, sel) { return '<option value="' + E(v) + '"' + (sel ? ' selected' : '') + '>' + E(t) + '</option>'; };
    const row = function (label, inner) { return '<div class="row"><span>' + label + '</span><div class="fx">' + inner + '</div></div>'; };
    let f = row(TK('이름'), '<input type="text" class="grow" data-rdk="label" maxlength="40" value="' + E(d.label) + '" placeholder="' + E(manual ? TK('예: 연간 목표') : (kpiAutoLabel(d) || TK('예: 총 매출'))) + '">'
      + (manual ? '' : '<span class="hint">' + TK('비우면 컬럼 · 집계 이름이 붙습니다') + '</span>'));
    f += row(TK('값'), '<div class="seg" role="group" aria-label="' + E(TK('값')) + '"><button type="button" data-rdk-mode="data" aria-pressed="' + (!manual) + '"' + (roots.length ? '' : ' disabled') + '>' + TK('데이터에서 계산') + '</button>'
      + '<button type="button" data-rdk-mode="manual" aria-pressed="' + manual + '">' + TK('직접 입력') + '</button></div>');
    const unit = '<input type="text" class="s" data-rdk="unit" maxlength="8" value="' + E(d.unit) + '" placeholder="' + E(TK('단위')) + '" aria-label="' + E(TK('단위')) + '" title="' + E(TK('원 · % · 건')) + '">';
    if (manual) {
      f += row(TK('숫자'), '<input type="text" class="grow" inputmode="decimal" data-rdk="value" value="' + E(d.value) + '" placeholder="' + E(TK('예: 1200')) + '">' + unit);
    } else {
      const srcs = roots.slice();
      if (src && srcs.indexOf(src) < 0) srcs.push(src);
      if (srcs.length > 1) f += row(TK('데이터'), '<select data-rdk="source" data-i18n-skip>' + srcs.map(function (x) { return opt(x.id, srcLabel(x) || x.name, x.id === d.source); }).join('') + '</select>');
      const numeric = kpiNumeric(src, d.col);
      f += row(TK('컬럼'), '<select data-rdk="col" data-i18n-skip aria-label="' + E(TK('컬럼')) + '">' + opt('*', TK('행 수'), d.col === '*') + (src ? src.columns : []).map(function (c) { return opt(c, c, c === d.col); }).join('') + '</select>'
        + '<select data-rdk="agg" data-i18n-skip aria-label="' + E(TK('집계')) + '" title="' + E(TK('집계')) + '">' + Object.keys(KPI_AGG).filter(function (x) { return numeric || x === 'count'; }).map(function (x) { return opt(x, TK(KPI_AGG[x]), x === d.agg); }).join('') + '</select>' + unit);
      const lin = kpiLineage(ctx.state, d.source), charts = ctx.state.charts.filter(function (c) { return kpiLineage(ctx.state, c.source) === lin; });
      const periods = src ? Object.keys(src.periods || {}).length : 0;
      f += row(TK('연결 차트'), '<select data-rdk="link" data-i18n-skip title="' + E(TK('연결한 차트의 필터를 따라갑니다')) + '">' + opt('', TK('없음'), !d.link) + charts.map(function (c) { return opt(c.id, c.title, c.id === d.link); }).join('') + '</select>'
        + '<label class="ck" title="' + E(TK(periods ? '마지막 기간과 그 앞 기간을 비교합니다' : '기간 컬럼이 있는 데이터에서만 됩니다')) + '"><input type="checkbox" data-rdk="delta"' + (d.delta ? ' checked' : '') + (periods ? '' : ' disabled') + '><span>' + T('직전 기간 대비') + '</span></label>');
    }
    f += row(TK('설명'), '<input type="text" class="grow" data-rdk="note" maxlength="40" value="' + E(d.note) + '" placeholder="' + E(TK('카드 아래 한 줄 (선택)')) + '">');
    const suggest = !d.id && kpiSuggestible(ctx.state), title = T(d.id ? 'KPI 카드 편집' : 'KPI 카드 추가');
    return '<div class="ai365-rd-kov" data-rd-kdlg><div class="ai365-rd-kdlg" data-rd-kpif role="dialog" aria-modal="true" aria-label="' + E(title) + '">'
      + '<div class="hd"><b>' + title + '</b><button type="button" class="x" data-rd-kpicancel title="' + E(T('닫기')) + '">' + IC.x + '</button></div>'
      + '<div class="pv"><span class="cap">' + TK('미리보기') + '</span><div data-rd-kpipv>' + kpiTileHtml(ctx, kpiDraftKpi(d), { preview: true }) + '</div></div>'
      + '<div class="f">' + f + '</div>'
      + '<div class="ft">' + (d.id ? '<button type="button" class="ai365-rd-btn sm" data-rd-kpirm="' + E(d.id) + '">' + TK('삭제') + '</button>' : '')
      + (suggest ? '<button type="button" class="ai365-rd-btn sm" data-rd-kpiauto' + (ctx.kpiBusy ? ' disabled' : '') + ' title="' + E(TK('값 컬럼으로 카드를 골라 넣습니다')) + '">' + IC.spark + '<span>' + T('추천 채우기') + '</span></button>' : '')
      + '<span class="sp"></span><span class="err" data-rd-kpierr></span><button type="button" class="ai365-rd-btn sm" data-rd-kpicancel>' + TK('취소') + '</button>'
      + '<button type="button" class="ai365-rd-btn sm pri" data-rd-kpiok' + (ctx.kpiBusy ? ' disabled' : '') + '>' + TK('적용') + '</button></div></div></div>';
  }
  function paintKpis(ctx) {
    if (!ctx.root) return;
    const host = ctx.root.querySelector('[data-rd-kpis]');
    if (host) host.innerHTML = kpisHtml(ctx);
    paintKpiDialog(ctx);
  }
  function paintKpiDialog(ctx) {   // 대화 상자는 패널 뿌리에 붙는다(저장 확인 상자와 같은 방식) · 다시 그려도 입력 중인 칸의 포커스 · 캐럿은 그대로(초안은 ctx.kpiEdit 에)
    // The dialog hangs off the panel root (like the save prompt); a repaint keeps the field being typed in and its caret (the draft lives in ctx.kpiEdit)
    const old = ctx.root.querySelector('[data-rd-kdlg]'), a = document.activeElement;
    const keep = (a && old && old.contains(a) && a.matches('[data-rdk]')) ? { key: a.dataset.rdk, text: a.tagName === 'INPUT' && a.type === 'text', s: 0, e: 0 } : null;
    if (keep && keep.text) { try { keep.s = a.selectionStart; keep.e = a.selectionEnd; } catch (e) { keep.text = false; } }
    if (old) old.remove();
    if (!ctx.kpiEdit || ctx.readonly) return;
    const ask = ctx.root.querySelector('[data-rd-ask]');   // 저장 확인 상자보다 아래에 / below the save prompt
    if (ask) ask.insertAdjacentHTML('beforebegin', kpiFormHtml(ctx)); else ctx.root.insertAdjacentHTML('beforeend', kpiFormHtml(ctx));
    if (keep) {
      const el = ctx.root.querySelector('[data-rd-kpif] [data-rdk="' + keep.key + '"]');
      if (el) { el.focus({ preventScroll: true }); if (keep.text && keep.s !== null) { try { el.setSelectionRange(keep.s, keep.e); } catch (e) { /* noop */ } } }
    }
  }
  function openKpiForm(id) {
    if (id && R.kpiEdit && R.kpiEdit.id === id) {   // 이미 고치는 중이면 초안을 지키고 포커스만 / already editing this card: keep the draft, just focus
      const el = R.root.querySelector('[data-rd-kpif] [data-rdk="label"]');
      if (el) el.focus();
      return;
    }
    const k = id ? (R.state.kpis || []).filter(function (x) { return x.id === id; })[0] : null;
    if (id && !k) return;
    const roots = kpiRoots(R.state), first = roots[0], fsrc = first ? first.id : '';
    if (k) {
      // 복제본을 가리키는 옛 카드는 같은 데이터의 원본으로 보여 준다 / a card pointing at a clone is shown on its root (the same data)
      const lin = k.source ? kpiLineage(R.state, k.source) : '', sid = k.source ? (roots.some(function (s) { return s.id === lin; }) ? lin : k.source) : fsrc;
      const src = srcOf(R.state, sid) || first, col = k.source ? k.col : kpiFirstCol(src);
      R.kpiEdit = { id: k.id, orig: JSON.stringify(k), mode: k.source ? 'data' : 'manual', label: k.label || '', source: sid, col: col,
        agg: k.source ? k.agg : kpiDefaultAgg(src, col), value: (k.value === undefined || k.value === null) ? '' : String(k.value),
        unit: k.unit || '', link: k.source ? (k.link || '') : kpiFirstChart(R.state, fsrc), delta: k.delta === 'prev', note: k.note || '' };
    } else {
      const col = kpiFirstCol(first);
      R.kpiEdit = { id: '', orig: '', mode: first ? 'data' : 'manual', label: '', source: fsrc, col: col, agg: kpiDefaultAgg(first, col), value: '', unit: '',
        link: kpiFirstChart(R.state, fsrc), delta: false, note: '' };
    }
    paintKpis(R);
    kpiFocus('label');
  }
  function kpiFormInput(el) {   // 글자 칸: 초안과 미리보기만 갱신(다시 그리지 않는다) / text fields: update the draft and the preview only
    const d = R.kpiEdit;
    if (!d) return;
    d[el.dataset.rdk] = el.value;
    const pv = R.root.querySelector('[data-rd-kpipv]'), err = R.root.querySelector('[data-rd-kpierr]');
    if (pv) pv.innerHTML = kpiTileHtml(R, kpiDraftKpi(d), { preview: true });
    if (err) err.textContent = '';
  }
  function kpiFormChange(el) {   // 고르기 칸: 따라 바뀌는 칸이 있어 폼을 다시 그린다 / select fields: dependent fields change, so the form re-renders
    const d = R.kpiEdit, key = el.dataset.rdk;
    if (!d) return;
    if (el.type === 'checkbox') d[key] = el.checked;
    else if (el.tagName === 'SELECT') {
      d[key] = el.value;
      if (key === 'source') {
        const src = srcOf(R.state, d.source);
        d.col = kpiFirstCol(src); d.agg = kpiDefaultAgg(src, d.col); d.delta = false; d.link = kpiFirstChart(R.state, d.source);
      }
      if (key === 'col') {   // 합계 · 평균 · 건수는 새 컬럼에 맞게 다시 고른다(최솟값 등 고른 것은 지킨다) / sum, avg and count follow the new column; min, max, first stay
        const src = srcOf(R.state, d.source);
        if (!kpiNumeric(src, d.col) || ['sum', 'avg', 'count'].indexOf(d.agg) >= 0) d.agg = kpiDefaultAgg(src, d.col);
      }
    } else return;
    paintKpis(R);
  }
  function kpiSetMode(mode) {   // 값 방식 전환(데이터에서 계산 | 직접 입력) — 그 방식의 첫 칸으로 포커스 / switch the value kind and focus its first field
    const d = R.kpiEdit;
    if (!d || d.mode === mode || (mode === 'data' && !kpiRoots(R.state).length)) return;
    d.mode = mode;
    paintKpis(R);
    kpiFocus(mode === 'manual' ? 'value' : 'col');
  }
  function kpiFocus(key) { const el = R.root && R.root.querySelector('[data-rd-kpif] [data-rdk="' + key + '"]'); if (el) el.focus(); }
  function kpiTrapTab(e) {   // Tab 은 대화 상자 안에서 돈다 / Tab cycles inside the dialog
    const box = e.target.closest('[data-rd-kpif]'), els = box ? Array.prototype.slice.call(box.querySelectorAll('button:not([disabled]),input:not([disabled]),select:not([disabled])')) : [];
    if (!els.length) return;
    const first = els[0], last = els[els.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); } else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
  function applyKpiForm() {
    const d = R.kpiEdit;
    if (!d || blocked()) return;
    const err = R.root.querySelector('[data-rd-kpierr]');
    const stop = function (msg, key) { if (err) err.textContent = msg; const el = R.root.querySelector('[data-rd-kpif] [data-rdk="' + key + '"]'); if (el) el.focus(); };
    if (d.mode === 'manual') {
      if (!d.label.trim()) return stop(TK('카드 이름을 적어 주세요.'), 'label');
      if (rdNum(d.value) === null) return stop(TK('보여 줄 숫자를 적어 주세요.'), 'value');
    } else if (!d.source || !d.col) return stop(TK('데이터와 컬럼을 골라 주세요.'), 'col');
    if (R.kpiBusy) return;   // 요청이 도는 동안 [적용]을 다시 눌러도 한 번만 / a second click while the request runs is ignored
    const spec = kpiSpec(d);
    kpiLock(true);
    ops([d.id ? { op: 'kpi_set', id: d.id, kpi: spec } : { op: 'kpi_add', kpi: spec }], true).then(function (r) {
      kpiLock(false);
      if (!r) return;
      R.state.kpis = r.session.state.kpis || [];
      if (R.kpiEdit === d) R.kpiEdit = null;   // 그 사이 다른 카드를 열었으면 그 폼은 둔다 / a form opened meanwhile for another card stays
      paintKpis(R); paintDock();
    });
  }
  function kpiLock(on) {   // [적용] · [추천 채우기] 잠금(다시 그려도 kpiBusy 로 유지) / lock apply and fill while a request runs (kept across repaints via kpiBusy)
    R.kpiBusy = on;
    if (R.root) R.root.querySelectorAll('[data-rd-kpiok],[data-rd-kpiauto]').forEach(function (b) { b.disabled = on; });
  }

  function destroyCharts(ctx) { ctx.charts.forEach(function (c) { try { c.destroy(); } catch (e) { /* noop */ } }); ctx.charts.clear(); }
  // pickable = 눌러서 더 내려갈 수 있을 때만 돋보기 커서(2026-09-30, 종전에는 모든 막대에 떠서 눌러도 아무 일이 없었다)
  // pickable: the zoom cursor only where a click can go further (2026-09-30; it used to show on every mark, even with nowhere to go)
  function chartEnv(ctx, chart) { return { pickable: canDrill(ctx, chart), lock: lockOf(ctx, chart), theme: ctx.state.theme }; }
  /* 차트 구성 + 보조 계열(추세선·예측) 이름을 지금 언어로 / the chart config, with the auxiliary series named in the current language */
  function configOf(ctx, chart, vc, comp) {
    const cfg = rdChartConfig(vc, comp, chartEnv(ctx, chart));
    cfg.data.datasets.forEach(function (d) { if (d.rdAux) d.label = T(d.label); });
    return cfg;
  }
  function mountOne(ctx, cv) {
    const chart = chartOf(ctx.state, cv.dataset.rdCanvas);
    if (!chart || !cv.isConnected) return;
    const vc = viewChart(ctx, chart);
    const inst = new window.Chart(cv, configOf(ctx, chart, vc, rdCompute(vc, viewSrc(ctx, chart))));
    ctx.charts.set(chart.id, inst);
    ensureProbe(ctx, chart);   // 서버에서만 내려갈 수 있는 자리면 누를 값이 있는지 미리 묻는다 / ask ahead where only the server can go further
    setTimeout(function () { if (ctx.charts.get(chart.id) === inst) settleChart(inst); }, 160);
  }
  /* 카드 폭이 바뀐 직후(비교 묶음 편입·해제 등) 만든 막대 차트는 최종 좌표가 바닥(y=base)에 납작하게 남아 클릭 판정(드릴다운·툴팁)이 빗나갔다
     (2026-09-22 확인). 값이 있는데 막대가 전부 납작하면 한 번 다시 계산한다. / A bar chart built right after a card-width change kept flat final
     coordinates (y = base), so hit-testing (drill-down, tooltips) missed (seen 2026-09-22). If every bar is flat while the data is not, recompute once. */
  function settleChart(inst) {
    try {
      const ds = (inst.data && inst.data.datasets && inst.data.datasets[0]) || {}, meta = inst.getDatasetMeta(0);
      const vals = (ds.data || []).filter(function (v) { return typeof v === 'number' && v !== 0; });
      if (!vals.length || !meta || !meta.data.length) return;
      const k = (inst.options && inst.options.indexAxis === 'y') ? 'x' : 'y';
      const flat = meta.data.every(function (p) { const f = p.getProps([k, 'base'], true); return typeof f.base === 'number' && Math.abs(f[k] - f.base) < 0.5; });
      if (flat) inst.update();
    } catch (e) { /* noop */ }
  }
  function mountCharts(ctx) {
    destroyCharts(ctx);
    const canvases = ctx.root ? ctx.root.querySelectorAll('canvas[data-rd-canvas]') : [];
    if (!canvases.length) return;
    loadChartJs().then(function () { canvases.forEach(function (cv) { mountOne(ctx, cv); }); })
      .catch(function () { say(T('차트 라이브러리를 불러오지 못했습니다.')); });
  }

  /* 필터 값만 바뀐 경우 — 그 차트만, 다시 그리지 않고 데이터만 갈아 끼운다(부드러운 전환) / a filter change swaps that chart's data in place */
  function refreshChart(ctx, cid, hard, alone) {
    const chart = chartOf(ctx.state, cid), inst = ctx.charts.get(cid);
    if (!chart) return;
    const deep = ((ctx.drill || {})[cid] || []).length;
    drillFresh(ctx, cid);   // 필터가 바뀌었으면 낡은 서버 단계를 걷는다(차트 모양이 바뀔 수 있어 다시 만든다) / drop stale server levels (rebuild, the type may change)
    if (((ctx.drill || {})[cid] || []).length !== deep) hard = true;
    if (!alone) {   // 값이 바뀌면 같은 비교 묶음의 눈금과, 이 차트의 필터를 따라가는 요약 숫자도 바뀐다 / siblings of the compare group and linked summary numbers follow
      if (chart.compare) ctx.state.charts.forEach(function (c) { if (c.id !== cid && c.compare === chart.compare) refreshChart(ctx, c.id, false, true); });
      paintKpis(ctx);
    }
    const vc = viewChart(ctx, chart), comp = rdCompute(vc, viewSrc(ctx, chart));
    const crumbs = ctx.root.querySelector('[data-rd-crumbs="' + cid + '"]'), marks = ctx.root.querySelector('[data-rd-marks="' + cid + '"]');
    if (crumbs) crumbs.innerHTML = crumbsHtml(ctx, chart);
    if (marks) marks.innerHTML = marksHtml(ctx, chart);
    const ins = ctx.root.querySelector('[data-rd-ins="' + cid + '"]');
    if (ins) ins.hidden = !!((ctx.drill || {})[cid] || []).length;
    // hard: 드릴다운처럼 차트 모양(막대↔선)까지 바뀔 수 있으면 다시 만든다 / rebuild when the chart type itself may change (drill-down)
    if (inst && !hard && !ctx.tableOf[cid] && chart.type !== 'kpi' && comp.x.length) {
      const cfg = configOf(ctx, chart, vc, comp);
      inst.data = cfg.data; inst.options = cfg.options; inst.update();
      // 사전 확인·거절로 더는 못 내려가게 됐으면 막대 위에 남은 돋보기를 지운다 / drop a zoom cursor left over a mark once the chart can no longer drill
      if (!cfg.options.onHover && inst.canvas) inst.canvas.style.cursor = '';
      ensureProbe(ctx, chart);   // 필터가 바뀌면 사전 확인도 새로 한다(필터마다 따로 기억) / a new filter gets its own probe
      return;
    }
    if (inst) { try { inst.destroy(); } catch (e) { /* noop */ } ctx.charts.delete(cid); }
    const body = ctx.root.querySelector('[data-rd-body="' + cid + '"]');
    if (!body) return;
    body.innerHTML = cardBodyHtml(ctx, chart);
    const cv = body.querySelector('canvas[data-rd-canvas]');
    if (cv) loadChartJs().then(function () { mountOne(ctx, cv); });
  }

  function paintChartFilters(ctx, cid) {
    const host = ctx.root.querySelector('[data-rd-cf="' + cid + '"]'), chart = chartOf(ctx.state, cid);
    if (!host || !chart) return;
    const q = host.querySelector('[data-rdf-q]'), hadFocus = q && document.activeElement === q, pos = q ? q.selectionStart : 0;
    const html = chartFiltersHtml(ctx, chart);
    host.innerHTML = html; host.hidden = !html;
    if (hadFocus) { const nq = host.querySelector('[data-rdf-q]'); if (nq) { nq.focus(); try { nq.setSelectionRange(pos, pos); } catch (e) { /* noop */ } } }
  }
  function closeMenus(ctx) {
    const open = ctx.fopen ? ctx.fopen.split(':')[0] : '', add = ctx.addf;
    ctx.fopen = ''; ctx.addf = ''; ctx.fq = '';
    if (open) paintChartFilters(ctx, open);
    if (add && add !== open) paintChartFilters(ctx, add);
  }

  /* 패널·뷰어 공통 클릭 — 처리했으면 true / clicks shared by panel and viewer; true when handled */
  function commonClick(ctx, e, onFilterChange) {
    let t;
    if ((t = e.target.closest('[data-rd-dpick]'))) {   // 서버 후보(remote)면 고른 컬럼으로 한 단계를 가져온다 / a server candidate fetches that level
      const m = ctx.dmenu;
      if (m && m.remote) drillRemote(ctx, m.cid, m.col, m.value, t.dataset.rdDpick, { left: m.left, top: m.top });
      else if (m) drillInto(ctx, m.cid, m.col, m.value, t.dataset.rdDpick);
      return true;
    }
    if (e.target.closest('[data-rd-dmenu]')) return true;
    if (ctx.dmenu) { ctx.dmenu = null; paintDrillMenu(ctx); }
    // 막대·조각·점을 눌렀으면 드릴다운(여기서 끝), 차트의 빈 곳이면 아래로 내려가 카드의 대상 선택이 된다 / a mark drills down; empty chart space falls through
    if ((t = e.target.closest('canvas[data-rd-canvas]')) && pickOnCanvas(ctx, t, e)) { if (ctx.fopen || ctx.addf) closeMenus(ctx); return true; }
    if ((t = e.target.closest('[data-rd-drillto]'))) {   // 경로를 누르면 그 단계로 돌아간다 / a crumb goes back to that level
      const p = t.dataset.rdDrillto.split(':');
      ctx.drill[p[0]] = (ctx.drill[p[0]] || []).slice(0, +p[1]);
      refreshChart(ctx, p[0], true);
      return true;
    }
    if (e.target.closest('[data-rdf-rm],[data-rdf-colpick]')) return false;   // 삭제·컬럼 고르기는 패널 전용 / panel only
    if ((t = e.target.closest('[data-rdf-open]'))) {
      const key = t.dataset.rdfOpen, was = ctx.fopen === key;
      closeMenus(ctx);
      if (!was) { ctx.fopen = key; paintChartFilters(ctx, key.split(':')[0]); }
      return true;
    }
    if ((t = e.target.closest('[data-rdf-add]'))) {
      const cid = t.dataset.rdfAdd, was = ctx.addf === cid;
      closeMenus(ctx);
      if (!was) { ctx.addf = cid; paintChartFilters(ctx, cid); }
      return true;
    }
    if ((t = e.target.closest('[data-rdf-none]'))) {
      const p = t.dataset.rdfNone.split(':'), chart = chartOf(ctx.state, p[0]), f = chart && filterOf(chart, p[1]);
      if (f) { f.selected = []; delete f.range; paintChartFilters(ctx, p[0]); refreshChart(ctx, p[0]); onFilterChange(chart, f); }
      return true;
    }
    if ((t = e.target.closest('[data-rdf-last]'))) {   // 최근 N개 기간 / the last N periods
      const p = t.dataset.rdfLast.split(':'), chart = chartOf(ctx.state, p[0]), f = chart && filterOf(chart, p[1]);
      if (f) { f.selected = []; f.range = { last: +t.dataset.n }; paintChartFilters(ctx, p[0]); refreshChart(ctx, p[0]); onFilterChange(chart, f); }
      return true;
    }
    if (e.target.closest('[data-rdf-menu]')) return true;
    if (ctx.fopen || ctx.addf) closeMenus(ctx);
    if ((t = e.target.closest('[data-rd-sql]'))) {   // Table 보기의 [조회 SQL] 펴기/접기 / toggle the query SQL under the Table view
      const cid = t.dataset.rdSql, ch = chartOf(ctx.state, cid);
      ctx.sqlOpen = ctx.sqlOpen || {}; ctx.sqlOpen[cid] = !ctx.sqlOpen[cid];
      const body = ctx.root && ctx.root.querySelector('[data-rd-body="' + cid + '"]');
      if (body && ch) body.innerHTML = cardBodyHtml(ctx, ch);
      return true;
    }
    if ((t = e.target.closest('[data-rd-view]'))) {
      const p = t.dataset.rdView.split(':');
      ctx.tableOf[p[0]] = p[1] === 'table';
      const card = ctx.root.querySelector('[data-rd-card="' + p[0] + '"]');
      if (card) card.querySelectorAll('[data-rd-view]').forEach(function (b) { b.classList.toggle('on', b.dataset.rdView === t.dataset.rdView); });
      refreshChart(ctx, p[0]);
      return true;
    }
    return false;
  }
  function commonChange(ctx, e, onFilterChange) {
    const rt = e.target.closest('[data-rdf-from],[data-rdf-to],[data-rdf-min],[data-rdf-max]');
    if (rt) {   // 범위: 부터~까지(기간) · 이상~이하(숫자). 거꾸로 고르면 두 값을 바꿔 끼운다 / a range; reversed bounds are swapped
      const d = rt.dataset, key = d.rdfFrom || d.rdfTo || d.rdfMin || d.rdfMax, p = key.split(':'), chart = chartOf(ctx.state, p[0]), f = chart && filterOf(chart, p[1]);
      if (!f) return true;
      const menu = rt.closest('[data-rdf-menu]'), src = srcOf(ctx.state, chart.source), pk = (src.periods || {})[f.col];
      if (pk) {
        let from = menu.querySelector('[data-rdf-from]').value, to = menu.querySelector('[data-rdf-to]').value;
        const a = rdPeriodKey(from, pk), b = rdPeriodKey(to, pk);
        if (a && b && ((a[0] - b[0]) || (a[1] - b[1])) > 0) { const s = from; from = to; to = s; }
        if (from || to) f.range = { from: from, to: to }; else delete f.range;
      } else {
        let lo = rdNum(menu.querySelector('[data-rdf-min]').value), hi = rdNum(menu.querySelector('[data-rdf-max]').value);
        if (lo !== null && hi !== null && lo > hi) { const s = lo; lo = hi; hi = s; }
        if (lo !== null || hi !== null) f.range = { min: lo, max: hi }; else delete f.range;
      }
      f.selected = [];
      paintChartFilters(ctx, p[0]); refreshChart(ctx, p[0]); onFilterChange(chart, f);
      return true;
    }
    const t = e.target.closest('[data-rdf-val]');
    if (!t) return false;
    const p = t.dataset.rdfVal.split(':'), chart = chartOf(ctx.state, p[0]), f = chart && filterOf(chart, p[1]);
    if (!f) return true;
    const i = f.selected.indexOf(t.value);
    if (t.checked && i < 0) f.selected.push(t.value);
    if (!t.checked && i >= 0) f.selected.splice(i, 1);
    const pill = t.closest('.ai365-rd-f').querySelector('.ai365-rd-fp'), v = pill.querySelector('.v');
    pill.classList.toggle('act', f.selected.length > 0);
    v.textContent = filterSummary(f, srcOf(ctx.state, chart.source));
    refreshChart(ctx, p[0]); onFilterChange(chart, f);
    return true;
  }

  /* ── 패널 상태 / panel state ──
     tab: 'dash' = 전체 대시보드(모든 차트) | 's1' = 그 Source 의 개별 대시보드(그 Source 를 쓰는 차트 + 출처 + 원본 데이터).
     어느 탭에서 고치든 차트는 같은 객체라 다른 탭에도 그대로 보인다. 대화는 보고 있는 탭을 에이전트에게 알려 준다(view).
     tab: 'dash' = the full dashboard | 's1' = that source's own dashboard (its charts, provenance and data). Charts are the
     same objects everywhere, so an edit shows on every tab; the conversation tells the agent which tab is in view. */
  const R = { host: '', session: null, tab: 'dash', view: 'dash', focus: '', busy: false, pending: '', err: '', lib: null,
    chatOpen: false, expanded: '', preview: null, pvStash: null,   // 2026-10-13 디자인: 대화 서랍 열림 · 펼친 카드 · 버전 미리보기(그 버전의 상태) · 미리보기 전 화면 상태 / drawer open, expanded card, version preview and the stashed view state
    noteOpen: '', kpiEdit: null, kpiBusy: false, drill: {}, dmenu: null,   // noteOpen: 메모 입력 줄을 연 차트 · kpiEdit: 편집 중인 KPI 카드 초안(2026-10-12) · 드릴다운: {차트 id: [{col, value, next}]} — 화면 상태, 저장하지 않는다 / drill-down paths, a view state
    dsrc: {}, dnone: {}, dbusy: '', dprobe: {},   // 서버 드릴다운(2026-09-30): 가져온 단계 · 안 되는 차트 · 가져오는 중 · 사전 확인 / server drill-down state
    tableOf: {}, fopen: '', fq: '', addf: '', charts: new Map(), root: null, regen: '', flash: '', readonly: false, loading: false,
    onClose: null, sqlOpen: {}, dataOpen: {}, toolsOpen: true, tmenu: false, tshut: {}, tacts: [], histTree: {} };
  // 그리는 상태 = 버전 미리보기 중이면 그 버전, 아니면 세션의 작업본 / the state drawn: the previewed version, else the session's working copy
  Object.defineProperty(R, 'state', { get: function () { return R.preview ? R.preview.state : (R.session ? R.session.state : { title: '', sources: [], charts: [] }); } });

  function sid() { return R.session ? R.session.id : ''; }
  function path(tail) { return '/api/reports/dash/' + encodeURIComponent(sid()) + (tail || ''); }
  /* Source 탭·탭 줄은 2026-09-22 폐지 — 대상은 카드를 눌러 지정한다 / the Source tabs and tab bar are gone (2026-09-22); targets are chosen by clicking a card */
  function srcLabel(src) { return (src.tables && src.tables.length) ? src.tables.join(', ') : (src.label || src.name || ''); }

  /* 펼친 카드(2026-10-13 디자인)는 맨 위에 전체 폭으로 올라오고 나머지가 그 아래로 흐른다 — 화면 상태일 뿐 저장하지 않는다
     The expanded card rises to the top at full width and the rest flow below; a view state, never stored */
  function gridHtml(charts) {
    const ex = R.expanded ? charts.filter(function (c) { return c.id === R.expanded; }) : [];
    const rest = ex.length ? charts.filter(function (c) { return c.id !== R.expanded; }) : charts;
    return '<div class="ai365-rd-grid">' + ex.concat(rest).map(function (c) { return cardHtml(R, c); }).join('') + '</div>';
  }
  function canUndo() { return !!(R.session && R.session.can_undo) && !R.busy && !R.preview; }
  /* 제목 줄의 [저장] 아이콘 — 저장하지 않은 변경은 주황 점, 상태 설명은 title(2026-10-13 디자인: 글자 없는 아이콘 세 개)
     The title row's save icon: unsaved changes show as an amber dot and the status lives in the title (the design has three plain icons) */
  function saveBtnHtml() {
    const sn = R.session;
    if (!sn || R.loading) return '';
    const dirty = !!sn.dirty, saved = !!sn.saved;
    const label = dirty ? T('저장하지 않은 변경') : (saved ? T('저장됨') + (sn.saved_at ? ' ' + when(sn.saved_at).slice(11) : '') : T('저장 안 됨'));
    const can = (dirty || !saved) && !R.busy && !R.preview && R.state.charts.length;
    return '<button type="button" class="ai365-rd-ib' + (dirty ? ' dirty' : '') + '" data-rd="save" data-rd-sst="' + (dirty ? 'dirty' : (saved ? 'ok' : 'none')) + '" title="' + E(T('내 보관소에 저장') + ' · ' + label) + '"' + (can ? '' : ' disabled') + '>' + IC.save + '</button>';
  }
  /* 제목 줄 ⋯ 메뉴: KPI 카드 추가 · 테마 색 · 데이터 새로고침(디자인의 세 아이콘 밖의 일) / the more menu: KPI card, theme colour, refresh */
  function moreMenuHtml() {
    const st = R.state, full = (st.kpis || []).length >= MAX_KPIS, brand = (st.theme && st.theme.brand) || '#5B5BD6';
    return '<div class="ai365-rd-smenu ai365-rd-mmenu" data-rd-smenu>'
      + '<button type="button" data-rd-kpiadd' + (full ? ' disabled' : '') + ' title="' + E(full ? TK('KPI 카드는 8장까지입니다') : '') + '">' + IC.plus + '<span>' + T('KPI 카드 추가') + '</span></button>'
      + '<label class="ai365-rd-theme' + (st.theme ? ' on' : '') + '" title="' + E(T('대표 색을 고르면 모든 차트에 한 번에 입힙니다')) + '"><input type="color" data-rd-brand value="' + E(brand) + '"><i style="background:' + E(brand) + '"></i><span>' + T('테마 색') + '</span></label>'
      + (st.theme ? '<button type="button" data-rd-themerm>' + IC.x + '<span>' + T('테마 지우기') + '</span></button>' : '')
      + '<div class="hr"></div>'
      + '<button type="button" data-rd="refresh"' + (st.sources.some(function (x) { return x.sql; }) ? '' : ' disabled') + '>' + IC.regen + '<span>' + T('데이터 새로고침') + '</span></button></div>';
  }
  function dashHtml() {
    const st = R.state, sn = R.session, pv = !!R.preview;
    // 제목 줄(2026-10-13 디자인): 제목 ✎ ……… [공유][되돌리기][저장][⋯] / the title row: title, pencil, then share, undo, save and more
    const top = '<div class="ai365-rd-top"><h2 data-i18n-skip title="' + E(st.title) + '">' + E(st.title) + '</h2>'
      + (pv ? '' : '<button type="button" class="ai365-rd-ib" data-rd="rename" title="' + E(T('이름 변경')) + '">' + IC.pen + '</button>')
      + '<span class="sp"></span>'
      + '<button type="button" class="ai365-rd-ib" data-rd="sharedash" title="' + E(T('대시보드 공유')) + '"' + (st.charts.length && !pv ? '' : ' disabled') + '>' + IC.share + '</button>'
      + '<button type="button" class="ai365-rd-ib" data-rd="undo" title="' + E(T('직전 변경 되돌리기')) + '"' + (canUndo() ? '' : ' disabled') + '>' + IC.undo + '</button>'
      + saveBtnHtml()
      + '<button type="button" class="ai365-rd-ib" data-rd="more" title="' + E(T('그 밖의 작업')) + '" aria-haspopup="true"' + (pv ? ' disabled' : '') + '>' + IC.dots + '</button></div>';
    let body;
    if (sn && sn.pending_auto && !pv) {
      body = '<div class="ai365-rd-grid">' + st.sources.map(function () {
        return '<section class="ai365-rd-card"><div class="ai365-rd-chd"><b>' + T('차트를 만드는 중…') + '</b></div><div class="ai365-rd-cbody"><div class="ai365-rd-skel"></div></div><div class="ai365-rd-cft"></div></section>';
      }).join('') + '</div>';
    } else if (!st.charts.length) {
      body = '<div class="ai365-rd-empty"><b>' + T('아직 차트가 없습니다') + '</b><span>' + T('아래 입력창에 보고 싶은 내용을 요청해 보세요. 예: 지난달 부서별 매출을 막대 차트로 보여줘') + '</span></div>';
    } else body = gridHtml(st.charts);
    return top + '<div class="ai365-rd-khost" data-rd-kpis>' + kpisHtml(R) + '</div>' + body;
  }
  /* 머리줄(2026-10-13 디자인): ← 리포트 에이전트 ……… [내 보관소]. ← 는 닫기(보관소 화면에서는 대시보드로) / the header: back arrow, title, library */
  function headHtml() {
    const back = R.view === 'library' && R.session;
    return '<div class="ai365-rd-hd"><button type="button" class="ai365-rd-back" data-rd="back" title="' + E(T(back ? '대시보드로' : '닫기')) + '">' + IC.arrow + '</button>'
      + '<span class="t">' + T('리포트 에이전트') + '</span><span class="sp"></span>'
      + '<button type="button" class="ai365-rd-hbtn' + (R.view === 'library' ? ' on' : '') + '" data-rd="library">' + IC.archive + '<span>' + T('내 보관소') + '</span></button></div>';
  }

  /* ── 대화 서랍(2026-10-13 디자인): 대시보드 아래, 손잡이로 여닫는다. 답변 = 글 + 도구 트리(2026-09-19 사용자 지시로 유지) + 버전 칩.
     버전 칩 "V1 · 대시보드 생성 | 2026.09.28 09:45" 을 누르면 그 버전을 미리보기하고, [이 버전으로 이어가기]로 작업본을 그 버전으로 되돌린다.
     The conversation drawer under the dashboard, toggled by the handle. An answer = text + the tool tree (kept at the user's
     request) + a version chip; clicking the chip previews that version and [Continue from this version] makes it the working copy. ── */
  function fmtTs(iso) { const t = String(iso || ''); return t.length >= 16 ? t.slice(0, 10).replace(/-/g, '.') + ' ' + t.slice(11, 16) : t; }
  function mdLite(text) { return E(text).replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>'); }   // 답변의 **굵게**만 / only the answer's bold marks
  function verOf(n) { return ((R.session && R.session.versions) || []).filter(function (v) { return v.n === n; })[0]; }
  function verLabel(v) {   // 서버의 한국어 이름 → 지금 언어 / the server's Korean label in the current language
    const m = /^V(\d+)에서 이어가기$/.exec(v.label || '');
    if (m) return isEn() ? 'Continued from V' + m[1] : v.label;
    return T(v.label || '');
  }
  function verChipHtml(m) {
    const v = m.ver ? verOf(m.ver) : null;
    if (!v) return '';
    const on = R.preview && R.preview.n === v.n;
    return '<button type="button" class="ai365-rd-ver' + (on ? ' on' : '') + '" data-rd-ver="' + v.n + '" title="' + E(isEn() ? 'Preview the dashboard at V' + v.n : 'V' + v.n + ' 시점의 대시보드 미리보기') + '">' + IC.history
      + '<span class="vn" data-i18n-skip>V' + v.n + ' · ' + E(verLabel(v)) + '</span><span class="sep"></span><span class="at" data-i18n-skip>' + E(fmtTs(m.ts || v.at)) + '</span></button>';
  }
  function chatHtml() {
    const sn = R.session, msgs = (sn && sn.messages) || [];
    let lastAgent = -1;
    msgs.forEach(function (m, i) { if (m.role === 'agent') lastAgent = i; });
    let h = msgs.map(function (m, i) {
      if (m.role === 'user') return '<div class="ai365-rd-msg user" data-i18n-skip>' + E(m.text) + '</div>';
      const last = i === lastAgent;   // 마지막 답변의 도구 트리만 기본으로 펼친다 / only the last answer's tool tree starts open
      return '<div class="ai365-rd-msg agent"><span class="tx" data-i18n-skip>' + mdLite(m.text) + '</span>'
        + traceTreeHtml(m.trace, { toggle: last ? 'last' : 'h' + i, collapsed: last ? !R.toolsOpen : !R.histTree[i] }) + verChipHtml(m) + '</div>';
    }).join('');
    if (R.pending) h += '<div class="ai365-rd-msg user" data-i18n-skip>' + E(R.pending) + '</div>';
    if (R.busy) h += '<div class="ai365-rd-msg agent">' + busyTreeHtml() + '</div>';
    if (R.err) h += '<div class="ai365-rd-msg err" data-i18n-skip>' + E(R.err) + '</div>';
    return h;
  }
  function handleHtml() {
    const sn = R.session, has = !!(sn && (((sn.messages || []).length) || R.busy || R.pending));
    return '<div class="ai365-rd-handle"' + (has ? '' : ' hidden') + '><button type="button" class="pill" data-rd="chat" title="' + E(T(R.chatOpen ? '대화 접기' : '대화 열기')) + '" aria-expanded="' + (R.chatOpen ? 'true' : 'false') + '">' + IC.chev + '</button></div>';
  }
  function paintChat(keep) {
    const main = R.root && R.root.querySelector('.ai365-rd-main');
    if (!main) return;
    main.classList.toggle('chat-open', !!R.chatOpen);
    const hd = main.querySelector('.ai365-rd-handle');
    if (hd) hd.outerHTML = handleHtml();
    const chat = document.getElementById('ai365RdChat');
    if (!chat) return;
    const top = chat.scrollTop;
    chat.hidden = !R.chatOpen;
    chat.innerHTML = chatHtml();
    chat.scrollTop = keep ? top : chat.scrollHeight;
  }
  function previewBarHtml() {
    const p = R.preview;
    if (!p) return '';
    const lb = isEn() ? 'Previewing "' + p.label + '"' : '"' + p.label + '" 미리보기';
    return '<div class="ai365-rd-pvbar" data-rd-pvbar>' + IC.history + '<span class="lb" data-i18n-skip title="' + E(lb) + '">' + E(lb) + '</span>'
      + '<button type="button" class="go" data-rd="pvgo"' + (R.busy ? ' disabled' : '') + '>' + T('이 버전으로 이어가기') + '</button>'
      + '<button type="button" class="x" data-rd="pvx" title="' + E(T('미리보기 닫기')) + '">' + IC.x + '</button></div>';
  }
  /* 버전 미리보기 — 서버가 그 버전의 차트 설정에 지금 데이터를 붙여 준다. 화면만 바뀌고(readonly) 작업본은 그대로; 드릴다운 · 표 보기 같은 화면 상태는 치워 뒀다 되돌린다.
     Version preview: the server joins that version's chart specs with the current data. Only the screen changes (read-only); the
     working copy is untouched; view states such as drill paths and table views are stashed and restored. */
  function openPreview(n) {
    if (R.busy || !R.session) return;
    const v = verOf(n), id = sid();
    if (!v) return;
    api(path('/versions/' + n + '?acting_user_id=' + encodeURIComponent(acting()))).then(function (d) {
      if (sid() !== id || !d || !d.state || !R.root) return;
      const st = rdLinkClones(d.state);
      (st.charts || []).forEach(function (c) { c.filters = c.filters || []; });
      st.kpis = st.kpis || [];
      if (!R.preview) R.pvStash = { drill: R.drill, dsrc: R.dsrc, dnone: R.dnone, dprobe: R.dprobe, tableOf: R.tableOf, expanded: R.expanded };
      R.preview = { n: n, label: verLabel(v), state: st };
      R.readonly = true;
      Object.assign(R, { drill: {}, dsrc: {}, dnone: {}, dprobe: {}, tableOf: {}, focus: '', expanded: '', dmenu: null, noteOpen: '', kpiEdit: null, fopen: '', addf: '', fq: '', tmenu: false, chatOpen: true });
      render();
    }).catch(function (err) { say(err.message); });
  }
  function closePreview(quiet) {
    if (!R.preview) return;
    R.preview = null; R.readonly = false;
    const st = R.pvStash || {};
    Object.assign(R, { drill: st.drill || {}, dsrc: st.dsrc || {}, dnone: st.dnone || {}, dprobe: st.dprobe || {}, tableOf: st.tableOf || {}, focus: '', expanded: st.expanded || '', dmenu: null, fopen: '', addf: '', fq: '' });
    R.pvStash = null;
    if (!quiet) render();
  }
  function restoreVersion() {
    const p = R.preview;
    if (!p || R.busy) return;
    const id = sid(), n = p.n;
    R.busy = true; paintDock();
    api(path('/versions/' + n + '/restore'), 'POST', { acting_user_id: acting() }).then(function (d) {
      if (sid() !== id) return;
      R.busy = false; closePreview(true); adopt(d); R.chatOpen = true; render();
      say(isEn() ? 'Continuing from V' + n + '.' : 'V' + n + ' 시점의 대시보드로 이어갑니다.');
    }).catch(function (err) { if (sid() !== id) return; R.busy = false; say(err.message); paintDock(); });
  }

  function thumbsHtml(it) {
    const th = (it.thumbs || []).slice(0, 4);
    if (!th.length || typeof ai365RepChartSvg !== 'function') return '<div class="ai365-rd-lth"></div>';
    return '<div class="ai365-rd-lth n' + th.length + '" data-i18n-skip>' + th.map(function (c) {
      return '<span>' + ai365RepChartSvg(c, { w: th.length > 1 ? 260 : 420, h: th.length > 1 ? 130 : 200, legend: false }) + '</span>';
    }).join('') + '</div>';
  }
  function libraryHtml() {
    const head = '<div class="ai365-rd-libhd"><h2>' + T('내 보관소') + '</h2><span class="sp"></span><button type="button" class="ai365-rd-btn pri" data-rd="blank">' + IC.plus + '<span>' + T('새 대시보드') + '</span></button></div>';
    if (R.lib === null) return head + '<div class="ai365-rd-empty"><span>' + T('불러오는 중…') + '</span></div>';
    if (!R.lib.length) return head + '<div class="ai365-rd-empty"><b>' + T('저장한 리포트와 대시보드가 없습니다') + '</b><span>' + T('대시보드 머리줄의 [저장]을 누르면 여기에 보관됩니다.') + '</span></div>';
    return head + '<div class="ai365-rd-lib">' + R.lib.map(function (it) {
      const cur = R.session && R.session.post_id === it.id;
      return '<div class="ai365-rd-lc' + (cur ? ' cur' : '') + '" data-rd-open="' + E(it.id) + '" role="button" tabindex="0">' + thumbsHtml(it)
        + '<div class="ai365-rd-lb"><div class="r"><span class="ai365-rd-kind ' + E(it.kind) + '">' + T(it.kind === 'dashboard' ? '대시보드' : '리포트') + '</span>'
        + (it.v2 ? '' : '<span class="ai365-rd-kind old">' + T('예전 저장분') + '</span>')
        + '<button type="button" class="ai365-rd-ib danger del" data-rd-libdel="' + E(it.id) + '" title="' + E(T('삭제')) + '">' + IC.trash + '</button></div>'
        + '<b data-i18n-skip title="' + E(it.title) + '">' + E(it.title) + '</b>'
        + '<span class="m"><span data-i18n-skip>' + E(when(it.updated)) + ' · ' + it.charts + '</span> <span>' + T('차트') + '</span></span></div></div>';
    }).join('') + '</div>';
  }

  /* ── 도구 트리(2026-09-19 사용자 지시: 버튼 말고 트리 구조) ──
     ① 실행 내역 트리: 리포트 에이전트 › Data Agent / Visualize Agent › 부른 도구(성공·실패 + 한 문장). 답변 아래와 대화 기록에 쓴다.
     ② 도구 고르기 트리: 입력창 왼쪽 [도구 트리] 또는 빈 입력창에서 '/' → 리포트 에이전트 › 에이전트 › 묶음 › 할 수 있는 일.
        누르면 요청 문장을 입력창에 채울 뿐 보내지 않는다. 붙어 있는 도구 목록은 서버(GET /api/reports/dash/tools)가 주므로
        도구가 늘면 트리에도 그대로 나온다 — 여기서는 도구마다 요청 문장만 붙인다(모르는 도구는 이름만으로 한 줄).
     Tool trees (2026-09-19, user direction: a tree instead of buttons) — (1) the activity tree: report agent › Data Agent /
     Visualize Agent › the tools it called (status + one sentence), under the answer and in the history; (2) the picker tree:
     the [Tool tree] button or '/' in an empty input opens report agent › agent › group › what can be asked. Picking fills the
     input and never sends. The attached tools come from the server, so new tools appear as is; this file only adds the
     request sentences (an unknown tool gets one generic line). */
  function treeLeafHtml(t) {
    const note = t.ok ? (t.say || '') : (t.detail || '');
    return '<li><div class="tn leaf' + (t.ok ? '' : ' bad') + '"><span class="st">' + (t.ok ? IC.check : IC.x) + '</span><span class="lb">' + E(T(t.label)) + '</span><code data-i18n-skip>' + E(t.tool) + '</code>'
      + (note ? '<span class="nt" data-i18n-skip title="' + E(note) + '">' + E(note) + '</span>' : '') + '</div></li>';
  }
  function agentNodeHtml(agent, tail) {
    return '<i class="' + (agent === 'Data Agent' ? 'data' : 'viz') + '"></i><b data-i18n-skip>' + E(agent) + '</b>' + (tail || '');
  }
  function traceTreeHtml(trace, opts) {
    opts = opts || {};
    const groups = rdTraceTree(trace), n = (trace || []).length;
    if (!n) return '';
    const root = '<div class="tn root"' + (opts.toggle ? ' data-rd-ttoggle="' + E(opts.toggle) + '" role="button" tabindex="0"' : '') + '><span class="mk">' + IC.spark + '</span><b>' + T('리포트 에이전트') + '</b>'
      + '<span class="cnt"><span>' + T('도구') + '</span> <span data-i18n-skip>' + n + '</span></span>' + (opts.toggle ? IC.caret : '') + '</div>';
    if (opts.collapsed) return '<div class="ai365-rd-tree shut"><ul><li>' + root + '</li></ul></div>';
    return '<div class="ai365-rd-tree"><ul><li>' + root + '<ul>' + groups.map(function (g) {
      return '<li><div class="tn ag">' + agentNodeHtml(g.agent) + '</div><ul>' + g.tools.map(treeLeafHtml).join('') + '</ul></li>';
    }).join('') + '</ul></li></ul></div>';
  }
  function busyTreeHtml() {
    return '<div class="ai365-rd-tree"><ul><li><div class="tn root"><span class="mk">' + IC.spark + '</span><b>' + T('리포트 에이전트') + '</b></div>'
      + '<ul><li><div class="tn leaf wait"><span class="ai365-rd-spin"></span><span class="lb">' + T('도구를 고르는 중…') + '</span></div></li></ul></li></ul></div>';
  }

  let TOOLS = null;
  const TOOLS_FALLBACK = [   // 서버 목록을 못 받았을 때 / when the server list cannot be fetched
    { agent: 'Data Agent', groups: [{ group: '데이터', tools: [{ name: 'query_data', label: '데이터 조회' }] }] },
    { agent: 'Visualize Agent', groups: [
      { group: '리포트', tools: [{ name: 'create_chart', label: '차트 추가' }, { name: 'update_chart', label: '차트 수정' }, { name: 'remove_chart', label: '차트 삭제' }] },
      { group: '기준선', tools: [{ name: 'add_reference_line', label: '기준선 추가' }, { name: 'remove_reference_line', label: '기준선 삭제' }] },
      { group: '계산 값', tools: [{ name: 'add_calculation', label: '계산 값 추가' }] },
      { group: '강조', tools: [{ name: 'add_highlight', label: '강조 추가' }, { name: 'remove_highlight', label: '강조 삭제' }] },
      { group: '드릴다운', tools: [{ name: 'set_drill', label: '드릴다운 설정' }] },
      { group: '디자인', tools: [{ name: 'set_style', label: '디자인 변경' }, { name: 'set_theme', label: '테마 설정' }] },
      { group: '필터', tools: [{ name: 'add_filter', label: '필터 추가' }, { name: 'remove_filter', label: '필터 삭제' }] },
      { group: '추세·예측', tools: [{ name: 'set_trend', label: '추세선·예측' }] },
      { group: 'KPI 카드', tools: [{ name: 'add_kpi', label: 'KPI 카드 추가' }, { name: 'remove_kpi', label: 'KPI 카드 삭제' }, { name: 'arrange_kpis', label: 'KPI 카드 순서' }] },
      { group: '정리', tools: [{ name: 'set_insight', label: '인사이트 작성' }, { name: 'arrange', label: '배치 변경' }, { name: 'rename_dashboard', label: '제목 변경' }] }] },
  ];
  function loadTools() {
    if (TOOLS) return;
    api('/api/reports/dash/tools').then(function (d) { TOOLS = (d && d.agents) || TOOLS_FALLBACK; if (R.tmenu) paintToolsMenu(); })
      .catch(function () { TOOLS = TOOLS_FALLBACK; });
  }
  /* 도구를 고를 때의 대상 — 눌러 둔 차트, 없으면 지금 화면에 하나뿐인 차트(자동 대상) / the target: the focused chart, else the only chart in view */
  function toolCtx() {
    const en = isEn(), src = null, inView = R.state.charts;   // Source 탭 폐지(2026-09-22): 대상은 카드로만 / no tab context since 2026-09-22
    const focus = R.focus && chartOf(R.state, R.focus), target = focus || (inView.length === 1 ? inView[0] : null);
    const tsrc = target && srcOf(R.state, target.source);
    const col = tsrc ? ((tsrc.columns.filter(function (c) { return (tsrc.types || {})[c] === 'text' && c !== target.x; })[0]) || target.x || tsrc.columns[0]) : (en ? 'a column' : '항목');
    return { en: en, src: src, target: target, auto: focus ? null : target, col: col,
      C: target ? (en ? 'this chart' : '이 차트') : (en ? 'the ○○ chart' : '○○ 차트') };
  }
  /* 도구 하나 → 할 수 있는 일들: [이름, 입력창에 채울 문장, 차트 대상이 필요한가] / one tool → its actions: [label, sentence, needs a chart] */
  function toolActions(tool, x) {
    const en = x.en, C = x.C, all = en ? 'every chart' : '모든 차트', S = x.target ? C : all;
    const A = {
      query_data: [[T('데이터 조회'), en ? 'Query this data and turn it into a report: ' : '다음 데이터를 새로 조회해서 리포트로 보여줘: ']],
      create_chart: [[T('리포트 추가'), x.src ? (en ? 'Add another report from the ' + x.src.name + ' data: ' : x.src.name + ' 데이터로 리포트를 하나 더 만들어줘: ') : (en ? 'Add another report: ' : '리포트를 하나 더 만들어줘: ')]],
      update_chart: [
        [T('차트 종류 바꾸기'), en ? 'Turn ' + C + ' into a horizontal bar chart' : C + '를 가로 막대 차트로 바꿔줘', true],
        [T('계열 추가'), en ? 'Also show this value in ' + C + ': ' : C + '에 다음 값도 같이 보여줘: ', true],
        [T('정렬·상위 N'), en ? 'Sort ' + C + ' by value and keep the top 5' : C + '를 값이 큰 순서로 상위 5개만 보여줘', true]],
      remove_chart: [[T('리포트 삭제'), en ? 'Delete ' + C : C + '를 지워줘', true]],
      add_reference_line: [
        [T('평균선 넣기'), en ? 'Add an average reference line to ' + C : C + '에 평균 기준선을 넣어줘', true],
        [T('목표선 넣기'), en ? 'Add a target line to ' + C + ' at: ' : C + '에 목표 기준선을 넣어줘. 목표 값: ', true]],
      remove_reference_line: [[T('기준선 지우기'), en ? 'Remove the reference lines of ' + C : C + '의 기준선을 지워줘', true]],
      add_calculation: [
        [T('직전 기간 대비 증감률'), en ? 'Also show the change from the previous period in ' + C : C + '에 직전 기간 대비 증감률도 같이 보여줘', true],
        [T('누계 보기'), en ? 'Show ' + C + ' as a running total' : C + '를 누계로 바꿔줘', true],
        [T('구성비 보기'), en ? 'Show ' + C + ' as shares (%)' : C + '를 구성비(%)로 바꿔줘', true]],
      add_highlight: [
        [T('목표 미달 강조'), en ? 'In ' + C + ', colour the items below the target red. Target: ' : C + '에서 목표에 못 미친 항목을 빨간색으로 강조해줘. 목표 값: ', true],
        [T('상위 3개 강조'), en ? 'Highlight only the top 3 in ' + C : C + '에서 상위 3개만 강조해줘', true]],
      remove_highlight: [[T('강조 지우기'), en ? 'Remove the highlights of ' + C : C + '의 강조를 지워줘', true]],
      set_drill: [[T('드릴다운 순서 정하기'), en ? 'When a bar of ' + C + ' is clicked, drill down in this order: ' : C + '의 막대를 누르면 다음 순서로 내려가게 해줘: ', true]],
      add_filter: [[T('필터 추가'), en ? 'Add a filter on ' + x.col + ' to ' + C : C + '를 ' + x.col + '별로 골라 볼 수 있게 필터를 만들어줘', true],
        [T('최근 기간만 보기'), en ? 'Show only the last 3 periods in ' + C : C + '를 최근 3개 기간만 보이게 해줘', true]],
      set_trend: [
        [T('추세선 넣기'), en ? 'Add a trend line to ' + C : C + '에 추세선을 넣어줘', true],
        [T('앞으로 3개 기간 예측'), en ? 'Add a trend line to ' + C + ' and forecast the next 3 periods' : C + '에 추세선을 넣고 앞으로 3개 기간을 예측해줘', true],
        [T('추세선·예측 지우기'), en ? 'Remove the trend line and forecast of ' + C : C + '의 추세선과 예측을 지워줘', true]],
      set_theme: [
        [T('회사 색으로 바꾸기'), en ? 'Use our company colour on every chart. Brand colour: ' : '모든 차트를 우리 회사 색으로 바꿔줘. 대표 색: '],
        [T('테마 지우기'), en ? 'Remove the theme and go back to the default colours' : '테마를 지우고 기본 색으로 돌려줘']],
      remove_filter: [[T('필터 지우기'), en ? 'Remove the filters of ' + C : C + '의 필터를 지워줘', true]],
      set_style: [
        [T('색 바꾸기'), en ? 'Use a blue palette for ' + S : S + ' 색을 파란 계열로 바꿔줘'],
        [T('값 라벨 표시'), en ? 'Show value labels on ' + S : S + '에 값 라벨을 보여줘']],
      add_kpi: [[T('KPI 카드 넣기'), en ? 'Add KPI cards on top for: ' : '맨 위 KPI 카드로 다음 숫자를 보여줘: '],
        [T('고정 숫자 카드 넣기'), en ? 'Add a KPI card with a fixed number. Name and number: ' : '고정 숫자 KPI 카드를 넣어줘. 이름과 숫자: '],
        [T('KPI 카드 고치기'), en ? 'Change a KPI card (its name, then what to change): ' : 'KPI 카드를 고쳐줘(카드 이름과 바꿀 내용): ']],
      remove_kpi: [[T('KPI 카드 지우기'), en ? 'Remove the KPI cards' : 'KPI 카드를 지워줘']],
      arrange_kpis: [[T('KPI 카드 순서 바꾸기'), en ? 'Reorder the KPI cards like this: ' : 'KPI 카드 순서를 다음처럼 바꿔줘: ']],
      set_insight: [[T('인사이트 다시 쓰기'), en ? 'Rewrite the insight of ' + C : C + '의 인사이트를 다시 써줘', true]],
      arrange: [[T('순서 바꾸기'), en ? 'Reorder the charts like this: ' : '차트 순서를 다음처럼 바꿔줘: ']],
      rename_dashboard: [[T('대시보드 제목 바꾸기'), en ? 'Rename the dashboard to: ' : '대시보드 제목을 다음으로 바꿔줘: ']],
    };
    return A[tool.name] || [[T(tool.label), T(tool.label) + ': ']];
  }
  function toolsMenuHtml() {
    const x = toolCtx(), agents = TOOLS || TOOLS_FALLBACK;
    const where = x.target ? "'" + x.target.title + "'" : (x.src ? x.src.name : '');
    R.tacts = [];
    return '<div class="ai365-rd-tmenu" id="ai365RdTools"><div class="hd"><b>' + T('리포트 에이전트의 도구') + '</b>'
      + '<span class="wh"><span>' + T('대상') + '</span> ' + (where ? '<span data-i18n-skip>' + E(where) + '</span>' : '<span>' + T('전체 대시보드') + '</span>') + '</span></div>'
      + '<div class="ai365-rd-tree pick"><ul><li><div class="tn root"><span class="mk">' + IC.spark + '</span><b>' + T('리포트 에이전트') + '</b></div><ul>'
      + agents.map(function (a) {
        const akey = 'a:' + a.agent, shutA = !!R.tshut[akey];
        return '<li><button type="button" class="tn ag' + (shutA ? ' shut' : '') + '" data-rd-tnode="' + E(akey) + '">' + agentNodeHtml(a.agent, IC.caret) + '</button>'
          + (shutA ? '' : '<ul>' + a.groups.map(function (g) {
            const gkey = 'g:' + a.agent + ':' + g.group, shutG = !!R.tshut[gkey], leaves = [];
            g.tools.forEach(function (tool) { toolActions(tool, x).forEach(function (act) { leaves.push([tool, act]); }); });
            return '<li><button type="button" class="tn grp' + (shutG ? ' shut' : '') + '" data-rd-tnode="' + E(gkey) + '"><span class="lb">' + E(T(g.group)) + '</span><span class="cnt" data-i18n-skip>' + leaves.length + '</span>' + IC.caret + '</button>'
              + (shutG ? '' : '<ul>' + leaves.map(function (l) {
                const i = R.tacts.push(l[1]) - 1;
                return '<li><button type="button" class="tn leaf" data-rd-tact="' + i + '"><span class="lb">' + E(l[1][0]) + '</span><code data-i18n-skip>' + E(l[0].name) + '</code></button></li>';
              }).join('') + '</ul>') + '</li>';
          }).join('') + '</ul>') + '</li>';
      }).join('') + '</ul></li></ul></div><div class="ft">' + T('항목을 누르면 요청 문장이 입력창에 채워집니다. 빈 입력창에서 / 를 눌러도 열립니다.') + '</div></div>';
  }
  function paintToolsMenu() {
    const old = document.getElementById('ai365RdTools'), row = R.root && R.root.querySelector('.ai365-rd-inrow');
    if (old) old.remove();
    const btn = R.root && R.root.querySelector('[data-rd="toolsmenu"]');
    if (btn) btn.classList.toggle('on', !!R.tmenu);
    if (R.tmenu && row) row.insertAdjacentHTML('afterbegin', toolsMenuHtml());
  }
  function openToolsMenu(on) { R.tmenu = on; if (on) loadTools(); paintToolsMenu(); }
  function pickToolAction(act) {
    const x = toolCtx();
    openToolsMenu(false);
    if (act[2] && x.auto) setFocus(x.auto.id);   // 화면에 하나뿐인 차트는 자동으로 대상이 된다 / the only chart in view becomes the target
    const input = document.getElementById('ai365RdInput');
    if (!input) return;
    input.value = act[1];
    input.focus();
    const hole = act[1].indexOf('○○');
    if (hole >= 0) input.setSelectionRange(hole, hole + 2); else input.setSelectionRange(input.value.length, input.value.length);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function placeholderText() {
    const en = isEn(), focus = R.focus && chartOf(R.state, R.focus);
    if (R.preview) return T('미리보기 중입니다. 이어가려면 [이 버전으로 이어가기]를 누르세요.');
    if (focus) return en ? 'Ask about "' + focus.title + '", e.g. add an average line' : "'" + focus.title + "' 차트에 요청하세요. 예: 평균 기준선 넣어줘";
    return T('리포트 데이터를 바탕으로 궁금한 내용을 입력하세요.');
  }

  /* 발치(2026-10-13 디자인) = 대상 배지 + [도구 트리] 입력창 [보내기]. 답변 · 대화 기록은 위의 대화 서랍으로 옮겼다.
     The dock: the target badge and the tool-tree button, input and send. Answers and history moved up into the drawer. */
  function dockHtml() {
    const sn = R.session, off = R.busy || !sn || !!R.preview;
    let h = R.busy ? '<div class="ai365-rd-prog"></div>' : '';
    const focus = R.focus && chartOf(R.state, R.focus);   // 입력창 위에는 고른 차트(대상)만 표시한다(2026-09-21 사용자 지시) / only the picked chart is shown above the input
    if (focus) h += '<div class="ai365-rd-scope"><div class="ai365-rd-focus"><span>' + T('대상') + '</span><span data-i18n-skip>' + E(focus.title) + '</span><button type="button" data-rd="unfocus" title="' + E(T('닫기')) + '">' + IC.x + '</button></div></div>';
    h += '<div class="ai365-rd-inrow">' + (R.tmenu && sn && !R.busy ? toolsMenuHtml() : '')
      + '<button type="button" class="ai365-rd-tbtn' + (R.tmenu ? ' on' : '') + '" data-rd="toolsmenu" title="' + E(T('리포트 에이전트의 도구')) + ' ( / )"' + (off ? ' disabled' : '') + '>' + IC.tree + '<span>' + T('도구 트리') + '</span></button>'
      + '<textarea id="ai365RdInput" rows="1" placeholder="' + E(placeholderText()) + '"' + (off ? ' disabled' : '') + '></textarea>'
      + '<button type="button" class="ai365-rd-send" data-rd="send" title="' + E(T('보내기')) + '"' + (off ? ' disabled' : '') + '>' + IC.send + '</button></div>';
    return h;
  }

  function render() {
    if (!R.root) return;
    const keep = (document.getElementById('ai365RdInput') || {}).value || '';
    const sc = R.root.querySelector('#ai365RdScroll'), top = sc ? sc.scrollTop : 0;
    let main;
    if (R.view === 'library') main = libraryHtml();
    else if (R.loading) main = '<div class="ai365-rd-empty"><span class="ai365-rd-spin"></span><span>' + T('불러오는 중…') + '</span></div>';
    else { R.tab = 'dash'; main = dashHtml(); }
    const lib = R.view === 'library';
    // 머리줄 › 본문(대시보드 영역 + 미리보기 막대 · 손잡이 · 대화 서랍) › 발치 입력 줄 › 대화 상자들 / header, main (dashboard, preview bar, handle, drawer), dock, dialogs
    R.root.innerHTML = headHtml()
      + '<div class="ai365-rd-main' + (R.chatOpen && !lib ? ' chat-open' : '') + '"><div class="ai365-rd-dash"><div class="ai365-rd-scroll" id="ai365RdScroll">' + main + '</div>' + (lib ? '' : previewBarHtml()) + '</div>'
      + (lib ? '' : handleHtml() + '<div class="ai365-rd-chat" id="ai365RdChat"' + (R.chatOpen ? '' : ' hidden') + '>' + chatHtml() + '</div>') + '</div>'
      + (lib ? '' : '<div class="ai365-rd-dock" id="ai365RdDock">' + dockHtml() + '</div>') + kpiFormHtml(R) + askHtml();
    const input = document.getElementById('ai365RdInput');
    if (input && keep) input.value = keep;
    const nsc = R.root.querySelector('#ai365RdScroll');
    if (nsc) nsc.scrollTop = top;
    mountCharts(R);
    if (R.flash) {
      const card = R.root.querySelector('[data-rd-card="' + R.flash + '"]');
      if (card) { card.classList.add('flash'); card.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
      R.flash = '';
    }
    const chat = document.getElementById('ai365RdChat');
    if (chat) chat.scrollTop = chat.scrollHeight;
  }
  function paintDock(focusInput) {
    const dock = document.getElementById('ai365RdDock');
    if (!dock) return render();
    const keep = (document.getElementById('ai365RdInput') || {}).value || '';
    dock.innerHTML = dockHtml();
    const input = document.getElementById('ai365RdInput');
    if (input) { input.value = keep; if (focusInput && !R.busy) input.focus(); }
    paintSave();
    paintChat(true);
  }
  /* ── 명시 저장(2026-09-22 사용자 결정: 자동 저장 대신 저장 버튼) ──
     보관함 글은 [저장]을 눌렀을 때만 만들어지고 갱신된다(POST …/save). 대화·직접 조작·필터·새로고침은 세션의 작업본만 바꾸고
     머리줄에 '저장하지 않은 변경'으로 표시된다. 변경이 있는 채 닫거나 같은 화면에서 다른 대시보드를 열면 저장하고 / 저장하지 않고 / 취소를
     묻는다 — 저장하지 않으면 글이 있는 대시보드는 마지막 저장본으로 돌아가고(POST …/discard) 한 번도 저장하지 않은 초안은 세션째 사라진다.
     Explicit save (user decision 2026-09-22: a save button instead of autosave). The library post is created and updated only
     by [Save] (POST …/save). Turns, direct edits, filters and refresh change only the session's working copy and the header
     shows "Unsaved changes". Closing, or opening another dashboard in the same host, with unsaved changes asks save / don't
     save / cancel; without saving, a dashboard with a post goes back to its last saved copy (POST …/discard) and a never-saved
     draft is dropped with its session. */
  function paintSave() {
    const btn = R.root && R.root.querySelector('.ai365-rd-top [data-rd="save"]');
    if (btn) btn.outerHTML = saveBtnHtml();
    const u = R.root && R.root.querySelector('.ai365-rd-top [data-rd="undo"]');
    if (u) u.disabled = !canUndo();
  }
  function askHtml() {
    if (!R.ask) return '';
    const closing = R.ask.kind === 'close', saved = !!(R.session && R.session.saved);
    return '<div class="ai365-rd-ask" data-rd-ask><div class="ai365-rd-askbox"><b>' + T('저장하지 않은 변경 사항이 있습니다.') + '</b>'
      + '<span>' + T(saved ? '저장하지 않으면 마지막으로 저장한 내용만 남습니다.' : '저장하지 않으면 이 대시보드는 보관함에 남지 않습니다.') + '</span>'
      + '<div class="r"><button type="button" class="ai365-rd-btn pri" data-rd="asksave"' + (R.busy ? ' disabled' : '') + '>' + T(closing ? '저장하고 닫기' : '저장하고 열기') + '</button>'
      + '<button type="button" class="ai365-rd-btn" data-rd="askdrop">' + T(closing ? '저장하지 않고 닫기' : '저장하지 않고 열기') + '</button>'
      + '<button type="button" class="ai365-rd-btn" data-rd="askcancel">' + T(closing ? '계속 편집' : '취소') + '</button></div></div></div>';
  }
  function paintAsk() {
    if (!R.root) return;
    const old = R.root.querySelector('[data-rd-ask]');
    if (old) old.remove();
    if (R.ask) R.root.insertAdjacentHTML('beforeend', askHtml());
  }
  function guard(kind, run) {
    if (!R.session || !R.session.dirty || !R.root) return run();
    R.ask = { kind: kind, run: run };
    paintAsk();
  }
  function saveDash(then) {
    if (!R.session) return;
    if (R.busy) return say(T('리포트 에이전트가 작업 중입니다. 끝난 뒤 저장해 주세요.'));
    if (!R.state.charts.length) return say(T('차트가 없는 대시보드는 저장할 수 없습니다.'));
    const id = sid(), btn = R.root && R.root.querySelector('[data-rd="save"]');
    if (btn) btn.disabled = true;
    api(path('/save'), 'POST', { acting_user_id: acting() }).then(function (d) {
      if (sid() !== id) return;
      adopt(d); paintSave();
      say(T(d.created ? '내 보관소에 저장했습니다.' : '저장했습니다.'));
      if (typeof then === 'function') then();
    }).catch(function (err) { if (sid() !== id) return; paintSave(); say(err.message); });
  }
  function discardThen(run) {
    const id = sid();
    api(path('/discard'), 'POST', { acting_user_id: acting() }).then(function (d) {
      if (sid() !== id) return;
      if (d && d.session) adopt(d); else R.session = null;   // 저장한 적 없는 초안은 세션째 사라진다 / a never-saved draft is gone with its session
      run();
    }).catch(function (err) { if (sid() !== id) return; say(err.message); run(); });
  }
  function setFocus(cid) {
    R.focus = cid || '';
    if (R.root) R.root.querySelectorAll('[data-rd-card]').forEach(function (c) { c.classList.toggle('focus', c.dataset.rdCard === R.focus); });
    paintDock(!!cid);
  }

  /* ── 호스트: 채팅 옆 패널 / 전체 화면 덮개 / hosts: the chat-side panel or a full-screen overlay ── */
  function mount(host) {
    unmount();
    R.host = host;
    const root = document.createElement('div');
    root.className = 'ai365-rd'; root.id = 'ai365RdRoot';
    if (host === 'panel' && typeof artifactPanel !== 'undefined') {
      const body = document.getElementById('artifactBody');
      body.innerHTML = ''; body.appendChild(root);
      artifactPanel.classList.remove('ai365-res-narrow');
      artifactPanel.classList.add('ai365-rd-mode', 'open');
      if (typeof updateScrollBtn === 'function') updateScrollBtn();
    } else {
      let ov = document.getElementById('ai365RdOv');
      if (!ov) { ov = document.createElement('div'); ov.id = 'ai365RdOv'; ov.innerHTML = '<div class="ai365-rd-ovbox"></div>'; document.body.appendChild(ov); }
      ov.firstChild.innerHTML = ''; ov.firstChild.appendChild(root);
      ov.classList.add('show');
      R.host = 'overlay';
    }
    R.root = root;
    root.addEventListener('click', onClick);
    root.addEventListener('mousedown', function (e) { R.kovDown = !!(e.target.matches && e.target.matches('[data-rd-kdlg]')); });   // 덮개에서 시작한 클릭만 닫는다 / only a click that started on the backdrop closes
    root.addEventListener('change', function (e) {
      if (e.target.matches('[data-rd-brand]')) { if (!blocked()) ops([{ op: 'theme_set', brand: e.target.value }]); return; }   // 대표 색 고르기(LLM 없음) / pick the brand colour, no LLM
      if (e.target.matches('[data-rdk]')) { kpiFormChange(e.target); return; }   // KPI 카드 폼의 고르기 칸 / a select or checkbox in the KPI card form
      commonChange(R, e, saveFilter);
    });
    root.addEventListener('input', function (e) {
      if (e.target.matches('[data-rdf-q]')) { R.fq = e.target.value; if (R.fopen) paintChartFilters(R, R.fopen.split(':')[0]); }
      if (e.target.matches('[data-rd-notetext]')) { const er = e.target.parentNode.querySelector('[data-rd-noteerr]'); if (er) er.textContent = ''; }
      if (e.target.matches('[data-rdk]')) kpiFormInput(e.target);   // KPI 카드 폼의 글자 칸 / a text field in the KPI card form
      if (e.target.id === 'ai365RdInput') { e.target.style.height = 'auto'; e.target.style.height = Math.min(110, e.target.scrollHeight) + 'px'; }
    });
    root.addEventListener('keydown', function (e) {
      if (e.target.id === 'ai365RdInput' && e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
      if (e.target.matches('[data-rd-notetext]') && e.key === 'Enter' && !e.isComposing) { e.preventDefault(); addNote(e.target.closest('[data-rd-notef]').dataset.rdNotef); }
      // 빈 입력창에서 '/' = 도구 트리 열기 / a slash in an empty input opens the tool tree
      if (e.target.id === 'ai365RdInput' && e.key === '/' && !e.target.value && !e.isComposing) { e.preventDefault(); openToolsMenu(true); }
      if (e.key === 'Enter' && e.target.matches('[data-rd-open]')) open({ post_id: e.target.dataset.rdOpen, host: R.host });
      if (e.key === 'Enter' && !e.isComposing && e.target.matches('[data-rd-kpif] input[type="text"]')) { e.preventDefault(); applyKpiForm(); }   // 대화 상자에서 Enter = 적용 / Enter applies the KPI dialog
      if (e.key === 'Tab' && R.kpiEdit && e.target.closest && e.target.closest('[data-rd-kpif]')) kpiTrapTab(e);
    });
  }
  function unmount() {
    destroyCharts(R);
    if (R.root && R.root.parentNode) R.root.parentNode.removeChild(R.root);
    R.root = null;
    const ov = document.getElementById('ai365RdOv');
    if (ov) ov.classList.remove('show');
    if (typeof artifactPanel !== 'undefined') artifactPanel.classList.remove('ai365-rd-mode');
  }
  function close() {
    const host = R.host, cb = R.onClose;
    unmount();
    R.session = null; R.onClose = null; R.host = ''; R.ask = null;
    if (host === 'panel' && typeof closeArtifact === 'function') closeArtifact();
    if (typeof cb === 'function') { try { cb(); } catch (e) { /* noop */ } }
  }
  // 다른 아티팩트가 패널 본문을 바꾸면(문서·리소스 등) 리포트 모드를 걷는다 / another artifact taking the panel body ends report mode
  (function () {
    const body = document.getElementById('artifactBody');
    if (!body || !window.MutationObserver) return;
    new MutationObserver(function () {
      if (R.host === 'panel' && R.root && !body.contains(R.root)) { destroyCharts(R); R.root = null; R.session = null; R.host = ''; artifactPanel.classList.remove('ai365-rd-mode'); }
    }).observe(body, { childList: true });
  })();

  function reset() {
    Object.assign(R, { session: null, tab: 'dash', view: 'dash', focus: '', busy: false, pending: '', err: '', lib: null,
      tableOf: {}, fopen: '', fq: '', addf: '', regen: '', flash: '', loading: true, sqlOpen: {}, dataOpen: {}, toolsOpen: true,
      tmenu: false, histTree: {}, drill: {}, dmenu: null, noteOpen: '', kpiEdit: null, kpiBusy: false, ask: null,
      chatOpen: false, expanded: '', preview: null, pvStash: null, readonly: false,
      dsrc: {}, dnone: {}, dbusy: '', dprobe: {} });   // 서버에서 가져온 드릴다운 단계 · 안 되는 차트 · 가져오는 중 · 사전 확인(2026-09-30) / fetched drill levels, declined charts, in flight, probes
  }
  function adopt(d) {
    R.session = d.session; R.loading = false;
    rdLinkClones(R.session.state);   // 복제본은 원본의 행을 가리킨다(서버는 복제본의 행을 보내지 않는다) / clones point at their root's rows
    R.session.state.charts.forEach(function (c) { c.filters = c.filters || []; });
    // 차트가 바뀌었으면(x 가 달라졌거나 컬럼이 없어졌거나 데이터를 새로 받았으면) 그 차트의 드릴다운은 맨 위로(drillValid)
    // A changed chart (new x, a missing column, refreshed data) drops its drill path (drillValid)
    Object.keys(R.drill).forEach(function (cid) { if (!drillValid(R, cid)) { delete R.drill[cid]; delete R.dsrc[cid]; } else drillFresh(R, cid); });
    Object.keys(R.dnone).forEach(function (cid) {
      const c = chartOf(R.state, cid), src = c && srcOf(R.state, c.source);
      if (!src || R.dnone[cid].base !== drillBase(src)) delete R.dnone[cid];
    });
    R.dbusy = '';
    R.dmenu = null;
    if (R.focus && !chartOf(R.state, R.focus)) R.focus = '';
    if (R.expanded && !chartOf(R.state, R.expanded)) R.expanded = '';   // 펼친 카드가 없어졌으면 접는다 / an expanded card that is gone collapses
    if (R.kpiEdit && R.kpiEdit.id) {   // 고치던 카드가 없어졌거나 다른 카드가 됐으면(id 재사용) 폼을 닫는다 / drop the editor when its card is gone or replaced (ids are reused)
      const k = (R.state.kpis || []).filter(function (x) { return x.id === R.kpiEdit.id; })[0];
      if (!k || JSON.stringify(k) !== R.kpiEdit.orig) R.kpiEdit = null;
    }
  }
  function runAuto() {
    if (!R.session || !R.session.pending_auto) return;
    const id = sid();
    api(path('/auto'), 'POST', { acting_user_id: acting() }).then(function (d) { if (sid() === id) { adopt(d); render(); } })
      .catch(function (err) { if (sid() === id) { R.session.pending_auto = false; R.err = err.message; render(); } });
  }

  /* 열기 — opts: {sources, chat_id, chat_title} | {post_id} | {blank:true}; host: 'panel'(기본) | 'overlay' */
  function open(opts) {
    opts = opts || {};
    // 같은 화면에서 저장 안 된 대시보드를 다른 것으로 바꿀 때만 묻는다(다른 곳에서 열면 작업본은 그 세션에 남는다)
    // Ask only when replacing an unsaved dashboard within the same host; opened elsewhere, the working copy just stays in its session
    if (!opts.force && R.session && R.session.dirty && R.root && (opts.host === 'overlay' ? 'overlay' : 'panel') === R.host) {
      return guard('open', function () { open(Object.assign({}, opts, { force: true })); });
    }
    const onClose = opts.onClose || (opts.host === R.host ? R.onClose : null);
    mount(opts.host === 'overlay' ? 'overlay' : 'panel');
    reset();
    R.onClose = onClose;
    render();
    const req = opts.post_id ? api('/api/reports/dash/open', 'POST', { acting_user_id: acting(), post_id: opts.post_id })
      : api('/api/reports/dash', 'POST', { acting_user_id: acting(), sources: opts.sources || [], chat_id: opts.chat_id || '', chat_title: opts.chat_title || '', blank: !!opts.blank });
    req.then(function (d) { adopt(d); render(); runAuto(); })
      .catch(function (err) { R.loading = false; R.err = err.message; say(err.message); render(); });
  }

  /* ── 동작 / actions ── */
  function veil(cid, on) {
    const card = cid && R.root && R.root.querySelector('[data-rd-card="' + cid + '"]');
    if (!card) return;
    const old = card.querySelector('.ai365-rd-veil');
    if (old) old.remove();
    if (on) card.insertAdjacentHTML('afterbegin', '<div class="ai365-rd-veil"><span class="ai365-rd-spin"></span><span>' + T('수정 중…') + '</span></div>');
  }
  function send(text) {
    const input = document.getElementById('ai365RdInput');
    const msg = (text || (input && input.value) || '').trim();
    if (!msg || R.busy || !R.session || R.preview) return;
    if (input) { input.value = ''; input.style.height = 'auto'; }
    const before = R.state.charts.map(function (c) { return c.id; }), id = sid(), target = R.focus;
    R.busy = true; R.pending = msg; R.err = ''; R.toolsOpen = true; R.tmenu = false; R.chatOpen = true;   // 보내면 대화 서랍이 열린다 / sending opens the drawer
    closeMenus(R); closeShareMenu(); paintDock(); veil(target, true);
    // 드릴다운 중인 차트가 대상이면(또는 하나뿐이면) 에이전트에게 무엇으로 좁혀 보고 있는지 알려 준다 / tell the agent about the drilled view in question
    const drilled = Object.keys(R.drill).filter(function (cid) { return (R.drill[cid] || []).length; });
    const dcid = (R.focus && drilled.indexOf(R.focus) >= 0) ? R.focus : (!R.focus && drilled.length === 1 ? drilled[0] : '');
    const dpath = dcid ? R.drill[dcid] : null;
    api(path('/turn'), 'POST', { acting_user_id: acting(), message: msg, focus: R.focus, view: '',
      drill: dpath ? { chart: dcid, path: dpath.map(function (p) { return { col: p.col, value: p.value }; }), level: dpath[dpath.length - 1].next } : {} }).then(function (d) {
      if (sid() !== id) return;
      R.busy = false; R.pending = ''; adopt(d);
      const made = R.state.charts.filter(function (c) { return before.indexOf(c.id) < 0; })[0];
      R.flash = made ? made.id : (target || ''); R.view = 'dash';   // 새 리포트는 깜빡여 알린다 / a new report is flashed
      render();
    }).catch(function (err) { if (sid() !== id) return; R.busy = false; R.pending = ''; R.err = err.message; veil(target, false); paintDock(true); });
  }
  function ops(list, quiet) {
    const id = sid();
    return api(path('/ops'), 'POST', { acting_user_id: acting(), ops: list }).then(function (d) {
      if (sid() !== id) return null;
      if (quiet) { ['saved', 'post_id', 'updated', 'can_undo', 'dirty', 'saved_at'].forEach(function (k) { R.session[k] = d.session[k]; }); paintSave(); } else { adopt(d); render(); }
      return d;
    }).catch(function (err) { say(err.message); return null; });
  }
  function addNote(cid) {
    const host = R.root.querySelector('[data-rd-notef="' + cid + '"]'), chart = chartOf(R.state, cid);
    if (!host || !chart) return;
    const sel = host.querySelector('[data-rd-notex]'), input = host.querySelector('[data-rd-notetext]'), err = host.querySelector('[data-rd-noteerr]');
    const text = (input.value || '').trim();
    if (!text) { err.textContent = T('메모 내용을 먼저 적어 주세요.'); input.focus(); return; }
    if ((chart.notes || []).length >= 6 && !(chart.notes || []).some(function (n) { return n.x === sel.value; })) { err.textContent = T('메모는 차트마다 6개까지 달 수 있습니다.'); return; }
    ops([{ op: 'note_add', chart: cid, x: sel.value, text: text }], true).then(function (d) {
      if (!d) return;
      const fresh = chartOf(d.session.state, cid);
      chart.notes = (fresh && fresh.notes) || [];
      R.noteOpen = ''; paintNoteForm(R, cid); refreshChart(R, cid);
    });
  }
  const filterTimers = {};
  function saveFilter(chart, f) {
    clearTimeout(filterTimers[chart.id + f.id]);
    filterTimers[chart.id + f.id] = setTimeout(function () { if (R.session && !R.preview) ops([{ op: 'filter_select', chart: chart.id, id: f.id, selected: f.selected, range: f.range || null }], true); }, 450);   // 미리보기의 필터는 화면에서만 / preview filters stay on screen
  }
  function download(cid) {
    const chart = chartOf(R.state, cid);
    if (!chart) return;
    const a = document.createElement('a'), inst = R.charts.get(cid), name = (chart.title || 'chart').replace(/[\\/:*?"<>|]+/g, '_');
    if (inst && !R.tableOf[cid]) { a.href = inst.toBase64Image('image/png', 1); a.download = name + '.png'; }
    else {   // 표·숫자 카드는 지금 보이는 행을 CSV 로 / the table and KPI views download the visible rows as CSV
      const src = viewSrc(R, chart), rows = rdFilteredRows(src, viewChart(R, chart).filters);   // 서버 단계면 그 단계의 행 / a server level's own rows
      const cell = function (v) { const s = rdKey(v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
      const csv = '﻿' + [src.columns].concat(rows).map(function (r) { return r.map(cell).join(','); }).join('\r\n');
      a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' })); a.download = name + '.csv';
    }
    document.body.appendChild(a); a.click(); a.remove();
  }
  function shareSnapshot(cid) {
    api(path('/snapshot?acting_user_id=' + encodeURIComponent(acting()) + (cid ? '&chart=' + encodeURIComponent(cid) : ''))).then(function (d) {
      if (typeof window.AI365_boardShare !== 'function') { say(T('게시판 기능을 불러오지 못했습니다.')); return; }
      const origin = (R.session && R.session.origin) || {};
      window.AI365_boardShare({ kind: d.kind, title: d.title, summary: d.summary, data: d.data, source: origin.chat_id ? { chat_id: origin.chat_id } : {} },
        { skipMe: true });   // 내 보관함은 대상이 아니다(2026-09-22) — [저장]이 맡는다 / my library is not a target; [Save] covers it
    }).catch(function (err) { say(err.message); });
  }
  /* 공유 메뉴(2026-09-22 사용자 지시): 게시판으로 공유 / 메일로 공유 — 머리줄(대시보드 전체)과 카드(차트 하나 = 리포트) 둘 다.
     이메일은 채팅 답변의 공유하기 모달(초대·메일 발송, adapter 의 AI365_mailShare)을 대시보드 미리보기로 열고, [메일 발송]이 POST …/mail 을 부른다
     (가상 메일함 기록 + 받는 사람·제목·본문이 채워진 Outlook 웹 작성 창).
     Share menu (user direction 2026-09-22): share to a board / share by email, on the header (whole dashboard) and on a card
     (one chart = a report). Email reuses the chat answer's share modal (invite + send, the adapter's AI365_mailShare) with a
     dashboard preview; [Send] calls POST …/mail (virtual mailbox row + an Outlook-web compose window with recipients, subject and body). */
  function closeShareMenu() { if (R.root) R.root.querySelectorAll('[data-rd-smenu]').forEach(function (el) { el.remove(); }); }   // 공유 · 카드 ⋮ · ⋯ 메뉴 전부 / every dropdown
  function openMenu(btn, html) {
    const open = btn.parentElement && btn.parentElement.querySelector('[data-rd-smenu]');
    closeShareMenu();
    if (open) return;   // 다시 누르면 닫힌다 / a second click closes it
    btn.insertAdjacentHTML('afterend', html);
  }
  function shareMenuHtml(cid) {
    return '<div class="ai365-rd-smenu" data-rd-smenu>'
      + '<button type="button" data-rd-sm="board" data-cid="' + E(cid || '') + '">' + IC.board + '<span>' + T('게시판으로 공유') + '</span></button>'
      + '<button type="button" data-rd-sm="mail" data-cid="' + E(cid || '') + '">' + IC.mail + '<span>' + T('메일로 공유') + '</span></button></div>';
  }
  function mailShare(cid) {
    api(path('/snapshot?acting_user_id=' + encodeURIComponent(acting()) + (cid ? '&chart=' + encodeURIComponent(cid) : ''))).then(function (d) {
      if (typeof window.AI365_mailShare !== 'function') { say(T('메일 공유 기능을 불러오지 못했습니다.')); return; }
      window.AI365_mailShare({ kind: d.kind, title: d.title, summary: d.summary }, {
        onSend: function (r) { return api(path('/mail'), 'POST', { acting_user_id: acting(), chart: cid || '', people: r.people, teams: r.teams }); },
      });
    }).catch(function (err) { say(err.message); });
  }
  function openLibrary() {
    R.view = 'library'; R.lib = null; render();
    api('/api/reports/dash/library?acting_user_id=' + encodeURIComponent(acting())).then(function (d) { R.lib = d.items || []; if (R.view === 'library') render(); })
      .catch(function (err) { R.lib = []; say(err.message); render(); });
  }

  /* 에이전트가 작업 중일 때 화면에서 직접 고치면 턴 결과가 그 변경을 덮어쓴다 — 끝날 때까지 직접 조작은 막는다 */
  /* A direct edit made while the agent works would be overwritten by the turn result, so direct edits wait until it ends */
  function blocked() {
    if (R.preview) { say(T('미리보기 중에는 바꿀 수 없습니다. 이 버전으로 이어가거나 미리보기를 닫아 주세요.')); return true; }
    if (!R.busy) return false;
    say(T('리포트 에이전트가 작업 중입니다. 끝난 뒤에 다시 해 주세요.'));
    return true;
  }
  const DIRECT = '[data-rd-trendrm],[data-rd-themerm],[data-rdf-rm],[data-rdf-colpick],[data-rd-note],[data-rd-noteadd],[data-rd-noterm],[data-rd-cmprm],[data-rd-kpirm],[data-rd-kpiadd],[data-rd-kpiauto],[data-rd-kpied],[data-rd-kpiok],[data-rd-kpi],[data-rd-dup],[data-rd-hlrm],[data-rd-del]';
  function onClick(e) {
    let t;
    if (e.target.closest(DIRECT) && blocked()) return;
    // 메뉴(공유 · 카드 ⋮ · 그 밖의 작업, 2026-10-13): 여는 버튼이 아니면 닫는다 — 항목을 눌렀을 때도 닫은 뒤 그 동작을 이어 간다(테마 색 줄은 색 창이 돌아올 때까지 둔다)
    // Menus (share, card kebab, more actions): any click that is not an opener closes them; an item click closes first, then runs (the theme row stays until the colour dialog returns)
    const opener = e.target.closest('[data-rd-cmenu],[data-rd="more"],[data-rd="sharedash"]');
    if (!opener && !e.target.closest('[data-rd-smenu] .ai365-rd-theme')) closeShareMenu();
    if (opener) {
      if (opener.dataset.rdCmenu) { const ch = chartOf(R.state, opener.dataset.rdCmenu); if (ch) openMenu(opener, cardMenuHtml(R, ch)); return; }
      if (opener.dataset.rd === 'more') { if (!R.preview) openMenu(opener, moreMenuHtml()); return; }
      return openMenu(opener, shareMenuHtml(''));
    }
    if ((t = e.target.closest('[data-rd-ver]'))) {   // 버전 칩: 미리보기 열기 · 같은 칩을 다시 누르면 닫기 / a version chip opens the preview; the same chip closes it
      const n = +t.dataset.rdVer;
      if (R.preview && R.preview.n === n) return closePreview();
      return openPreview(n);
    }
    if ((t = e.target.closest('[data-rd-expand]'))) {   // 펼치기 = 맨 위 전체 폭(화면 상태), 그 카드가 대상이 된다 / expand lifts the card to the top at full width and targets it
      const cid = t.dataset.rdExpand;
      R.expanded = R.expanded === cid ? '' : cid;
      if (R.expanded && !R.readonly) R.focus = cid;
      render();
      if (R.expanded) { const card = R.root.querySelector('[data-rd-card="' + cid + '"]'); if (card) card.scrollIntoView({ block: 'start', behavior: 'smooth' }); }
      return;
    }
    if ((t = e.target.closest('[data-rd-sm]'))) {
      const kind = t.dataset.rdSm, cid = t.dataset.cid || '';
      closeShareMenu();
      if (kind === 'mail') mailShare(cid); else shareSnapshot(cid);
      return;
    }
    if ((t = e.target.closest('[data-rdf-rm]'))) {
      e.stopPropagation();
      const p = t.dataset.rdfRm.split(':'), chart = chartOf(R.state, p[0]);
      if (chart) { chart.filters = chart.filters.filter(function (f) { return f.id !== p[1]; }); R.fopen = ''; paintChartFilters(R, p[0]); refreshChart(R, p[0]); ops([{ op: 'filter_remove', chart: p[0], id: p[1] }], true); }
      return;
    }
    if ((t = e.target.closest('[data-rdf-colpick]'))) {
      const cid = t.dataset.rdfColpick, col = t.dataset.col, had = (chartOf(R.state, cid).filters || []).map(function (f) { return f.id; });
      R.addf = '';
      ops([{ op: 'filter_add', chart: cid, col: col }], true).then(function (d) {
        if (!d) return paintChartFilters(R, cid);
        const fresh = chartOf(d.session.state, cid), mine = chartOf(R.state, cid);
        mine.filters = fresh.filters;
        const made = fresh.filters.filter(function (f) { return had.indexOf(f.id) < 0; })[0];
        R.fopen = made ? cid + ':' + made.id : '';   // 만든 필터의 값 목록을 바로 연다 / open the new filter's values right away
        paintChartFilters(R, cid);
      });
      return;
    }
    if ((t = e.target.closest('[data-rd-note]'))) {   // 카드의 [메모] — 입력 줄 여닫기 / the card's [note] button toggles the form row
      const cid = t.dataset.rdNote, was = R.noteOpen;
      R.noteOpen = was === cid ? '' : cid;
      if (was && was !== cid) paintNoteForm(R, was);
      paintNoteForm(R, cid);
      const input = R.root.querySelector('[data-rd-notef="' + cid + '"] [data-rd-notetext]');
      if (input) input.focus();
      return;
    }
    if ((t = e.target.closest('[data-rd-noteadd]'))) return addNote(t.dataset.rdNoteadd);
    if (e.target.closest('[data-rd-notef]')) return;   // 입력 줄 안의 클릭은 카드의 대상 선택으로 번지지 않게 / clicks inside the form stay there
    if ((t = e.target.closest('[data-rd-noterm]'))) {
      const p = t.dataset.rdNoterm.split(':'), chart = chartOf(R.state, p[0]);
      if (chart) { chart.notes = (chart.notes || []).filter(function (n) { return n.id !== p[1]; }); refreshChart(R, p[0]); ops([{ op: 'note_remove', chart: p[0], id: p[1] }], true); }
      return;
    }
    if ((t = e.target.closest('[data-rd-cmprm]'))) return void ops([{ op: 'compare_clear', id: t.dataset.rdCmprm }]);
    if ((t = e.target.closest('[data-rd-trendrm]'))) return void ops([{ op: 'trend_clear', id: t.dataset.rdTrendrm }]);
    if ((t = e.target.closest('[data-rd-themerm]'))) return void ops([{ op: 'theme_clear' }]);
    // KPI 카드(2026-10-12): 추가 · 추천 채우기 · 편집 · 적용 · 취소 · 삭제 · 카드 클릭 — 전부 LLM 없이 ops 로 / KPI cards: add, fill, edit, apply, cancel, remove, card click, all through ops
    if (e.target.closest('[data-rd-kpiadd]')) return openKpiForm('');
    if (e.target.closest('[data-rd-kpiauto]')) {
      if (R.kpiBusy) return;
      kpiLock(true);
      ops([{ op: 'kpi_auto' }], true).then(function (r) { kpiLock(false); if (!r) return; R.state.kpis = r.session.state.kpis || []; R.kpiEdit = null; paintKpis(R); paintDock(); });
      return;
    }
    if ((t = e.target.closest('[data-rd-kpied]'))) return openKpiForm(t.dataset.rdKpied);
    if (e.target.closest('[data-rd-kpiok]')) return applyKpiForm();
    if (e.target.closest('[data-rd-kpicancel]')) { R.kpiEdit = null; paintKpis(R); return; }
    if ((t = e.target.closest('[data-rd-kpirm]'))) {
      const kid = t.dataset.rdKpirm;
      R.state.kpis = (R.state.kpis || []).filter(function (k) { return k.id !== kid; });
      if (R.kpiEdit && R.kpiEdit.id === kid) R.kpiEdit = null;
      paintKpis(R); ops([{ op: 'kpi_remove', id: kid }], true).then(function (r) { if (r) paintDock(); });
      return;
    }
    if ((t = e.target.closest('[data-rdk-mode]'))) return kpiSetMode(t.dataset.rdkMode);
    if (e.target.matches && e.target.matches('[data-rd-kdlg]')) {   // 덮개 클릭 = 닫기(누른 채 끌고 나온 경우는 제외) / a click on the backdrop closes (not a drag that ends there)
      if (R.kovDown && e.detail <= 1) { R.kpiEdit = null; paintKpis(R); }
      return;
    }
    if (e.target.closest('[data-rd-kpif]')) return;   // 대화 상자 안의 클릭은 거기에 머문다 / clicks inside the dialog stay there
    if ((t = e.target.closest('[data-rd-kpi]'))) { if (e.detail > 1) return; return openKpiForm(t.dataset.rdKpi); }   // 더블클릭의 둘째 클릭은 무시(✕ 뒤 옆 카드가 열리지 않게) / the second click of a double-click is ignored
    if ((t = e.target.closest('[data-rd-dup]'))) {   // [복제](버튼, LLM 없음): 새 리포트 탭 + 원본과 비교 묶음 → 전체 대시보드에서 나란히 본다
      // [duplicate] (a button, no LLM): a new report tab in one compare group with the original, shown side by side on the full dashboard
      const before = R.state.charts.map(function (c) { return c.id; });
      ops([{ op: 'chart_duplicate', id: t.dataset.rdDup }], true).then(function (d) {
        if (!d) return;
        adopt(d);
        const made = R.state.charts.filter(function (c) { return before.indexOf(c.id) < 0; })[0];
        R.focus = ''; R.flash = made ? made.id : '';
        render();
        say(T('차트를 복제했습니다. 원본과 눈금을 맞춰 나란히 놓았습니다.'));
      });
      return;
    }
    if ((t = e.target.closest('[data-rd-hlrm]'))) {   // 강조 범례의 ✕ — 바로 지우고 서버에 알린다(LLM 없음) / the ✕ on a highlight chip, no LLM
      const p = t.dataset.rdHlrm.split(':'), chart = chartOf(R.state, p[0]);
      if (chart) { chart.highlights = (chart.highlights || []).filter(function (h) { return h.id !== p[1]; }); refreshChart(R, p[0]); ops([{ op: 'hl_remove', chart: p[0], id: p[1] }], true); }
      return;
    }
    // 도구 트리: 가지 접기·항목 고르기, 바깥을 누르면 닫는다 / tool tree: fold a branch, pick an item, close on an outside click
    if ((t = e.target.closest('[data-rd-tnode]'))) { R.tshut[t.dataset.rdTnode] = !R.tshut[t.dataset.rdTnode]; return paintToolsMenu(); }
    if ((t = e.target.closest('[data-rd-tact]'))) return pickToolAction(R.tacts[+t.dataset.rdTact]);
    if (R.tmenu && !e.target.closest('#ai365RdTools') && !e.target.closest('[data-rd="toolsmenu"]')) openToolsMenu(false);
    if ((t = e.target.closest('[data-rd-ttoggle]'))) {
      const k = t.dataset.rdTtoggle;
      if (k === 'last') R.toolsOpen = !R.toolsOpen; else R.histTree[k.slice(1)] = !R.histTree[k.slice(1)];
      return paintChat(true);
    }
    // 카드 안 어디를 눌러도(제목·차트·빈 곳) 그 카드가 대상이 된다. 버튼·입력·메뉴·표는 제외. 다시 눌러도 유지되고 해제는 ✕·Esc·카드 밖 클릭
    // (2026-09-22 사용자 제보: 제목을 누르면 반응이 없고 차트를 다시 누르면 지정이 풀리던 것을 고침)
    // Clicking anywhere on a card (title, chart, empty space) targets it; controls, menus and the table are excluded. A second click keeps
    // it; ✕, Esc or a click outside clears (user report 2026-09-22: the title did nothing and a second chart click cleared the target)
    if ((t = e.target.closest('[data-rd-card]')) && !e.target.closest('button,input,select,textarea,a,label,.ai365-rd-tbl,.ai365-rd-fmenu') && R.focus !== t.dataset.rdCard) setFocus(t.dataset.rdCard);
    if (commonClick(R, e, saveFilter)) return;
    if ((t = e.target.closest('[data-rd]'))) {
      const a = t.dataset.rd;
      if (a === 'close' || a === 'back') {   // ← : 보관소 화면이면 대시보드로, 아니면 닫기(저장 안 된 변경은 묻는다) / back: to the dashboard from the library, else close (asks about unsaved changes)
        if (R.view === 'library' && R.session) { R.view = 'dash'; return render(); }
        return guard('close', close);
      }
      if (a === 'chat') { R.chatOpen = !R.chatOpen; return paintChat(); }
      if (a === 'pvgo') return restoreVersion();
      if (a === 'pvx') return closePreview();
      if (a === 'save') return saveDash();
      if (a === 'asksave') { const ask = R.ask; if (!ask) return; return saveDash(function () { R.ask = null; paintAsk(); ask.run(); }); }
      if (a === 'askdrop') { const ask = R.ask; if (!ask) return; R.ask = null; paintAsk(); return discardThen(ask.run); }
      if (a === 'askcancel') { R.ask = null; return paintAsk(); }
      if (a === 'library') {
        if (R.view === 'library' && R.session) { R.view = 'dash'; return render(); }
        return openLibrary();
      }
      if (a === 'blank') return open({ blank: true, host: R.host });
      if (a === 'send') return send();
      if (a === 'toolsmenu') return openToolsMenu(!R.tmenu);
      if (a === 'unfocus') return setFocus('');
      if (a === 'undo') {
        if (R.busy) return;
        const id = sid();
        R.busy = true; paintDock();
        api(path('/undo'), 'POST', { acting_user_id: acting() }).then(function (d) { if (sid() !== id) return; R.busy = false; R.err = ''; adopt(d); render(); })
          .catch(function (err) { if (sid() !== id) return; R.busy = false; say(err.message); paintDock(); });
        return;
      }
      if (a === 'rename') {
        const name = (window.prompt(T('대시보드 이름'), R.state.title) || '').trim();
        if (name && name !== R.state.title) ops([{ op: 'title', title: name }]);
        return;
      }
      if (a === 'refresh') {
        t.disabled = true;
        api(path('/refresh'), 'POST', { acting_user_id: acting() }).then(function (d) {
          adopt(d); render();
          const ok = (d.refreshed || []).filter(function (r) { return r.ok; }).length, bad = (d.refreshed || []).filter(function (r) { return !r.ok; });
          say(isEn() ? ('Refreshed ' + ok + ' source(s)' + (bad.length ? ', ' + bad.length + ' kept as is' : '')) : ('데이터 ' + ok + '건을 다시 조회했습니다' + (bad.length ? ' (' + bad.length + '개는 그대로: ' + bad[0].reason + ')' : '')));
        }).catch(function (err) { say(err.message); render(); });
        return;
      }
      return;
    }
    if ((t = e.target.closest('[data-rd-regen]'))) {
      if (R.busy) return;
      const cid = t.dataset.rdRegen, id = sid();
      R.busy = true; R.regen = cid; R.err = ''; render();
      api(path('/charts/' + encodeURIComponent(cid) + '/regen'), 'POST', { acting_user_id: acting() }).then(function (d) {
        if (sid() !== id) return; R.busy = false; R.regen = ''; adopt(d); R.flash = cid; render();
      }).catch(function (err) { if (sid() !== id) return; R.busy = false; R.regen = ''; R.err = err.message; say(err.message); render(); });
      return;
    }
    if ((t = e.target.closest('[data-rd-down]'))) return download(t.dataset.rdDown);
    if ((t = e.target.closest('[data-rd-save]'))) {
      api(path('/charts/' + encodeURIComponent(t.dataset.rdSave) + '/save'), 'POST', { acting_user_id: acting() })
        .then(function () { say(T('내 보관소에 리포트로 저장했습니다.')); }).catch(function (err) { say(err.message); });
      return;
    }
    if ((t = e.target.closest('[data-rd-del]'))) {
      // 확인 창 없이 지우고 되돌리기로 살린다 / delete without a confirm; undo brings it back
      const cid = t.dataset.rdDel;
      ops([{ op: 'chart_remove', id: cid }]).then(function (d) { if (d) say(T('차트를 지웠습니다. 되돌리기로 살릴 수 있습니다.')); });
      return;
    }
    if ((t = e.target.closest('[data-rd-libdel]'))) {
      e.stopPropagation();
      if (!window.confirm(T('내 보관소에서 삭제할까요? 대화 기록도 함께 지워집니다.'))) return;
      const pid = t.dataset.rdLibdel;
      api('/api/reports/personal/' + encodeURIComponent(pid) + '?acting_user_id=' + encodeURIComponent(acting()), 'DELETE').then(function () {
        if (R.session && R.session.post_id === pid) { R.session = null; destroyCharts(R); }
        openLibrary();
      }).catch(function (err) { say(err.message); });
      return;
    }
    if ((t = e.target.closest('[data-rd-open]'))) return open({ post_id: t.dataset.rdOpen, host: R.host });
    // 빈 곳을 누르면 대상 해제 / clicking empty canvas clears the target
    if (R.focus && e.target.closest('#ai365RdScroll') && !e.target.closest('.ai365-rd-card')) setFocus('');
  }
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || !R.root) return;
    const bs = document.getElementById('ai365BsOv');
    if (bs && bs.classList.contains('show')) return;
    if (R.ask) { R.ask = null; return paintAsk(); }
    if (R.root.querySelector('[data-rd-smenu]')) return closeShareMenu();
    if (R.tmenu) return openToolsMenu(false);
    if (R.dmenu) { R.dmenu = null; return paintDrillMenu(R); }
    if (R.noteOpen) { const was = R.noteOpen; R.noteOpen = ''; return paintNoteForm(R, was); }
    if (R.kpiEdit) { R.kpiEdit = null; return paintKpis(R); }
    if (R.fopen || R.addf) return closeMenus(R);
    if (R.expanded) { R.expanded = ''; return render(); }
    if (R.preview) return closePreview();
    if (R.focus) return setFocus('');
    if (R.host === 'overlay') guard('close', close);
  });
  // 언어 토글 — 패널은 사전 왕복 대신 다시 그린다(T 가 그 시점 언어를 고른다) / on a language toggle the panel re-renders instead of a dictionary round trip
  // 토글은 눌린 순간 안쪽 글("KO ˅")을 다시 그려 e.target 이 문서에서 떨어질 수 있어 전달 시점 경로(composedPath)를 먼저 본다(2026-10-20 새 토글 모양)
  // The toggle repaints its inner label ("KO ˅") during the click, which can detach e.target, so the dispatch-time path (composedPath) is checked first
  document.addEventListener('click', function (e) {
    const path = typeof e.composedPath === 'function' ? e.composedPath() : [];
    const hit = path.some(function (n) { return n && n.id === 'ai365-lang-toggle'; }) || !!(e.target.closest && e.target.closest('#ai365-lang-toggle'));
    if (hit) setTimeout(function () { if (R.root) render(); }, 80);
  });

  /* ── 읽기 전용 뷰어(게시판 상세) — 필터는 이 화면에서만 바뀌고 저장되지 않는다 / read-only viewer (board detail); filter choices stay local ── */
  function viewerMount(el, data) {
    const state = rdLinkClones(JSON.parse(JSON.stringify({ title: data.title || '', sources: data.sources || [], charts: data.charts || [], kpis: data.kpis || [],
      theme: (data.theme && data.theme.brand) ? data.theme : null })));
    state.charts.forEach(function (c) { c.filters = c.filters || []; });
    const ctx = { state: state, tableOf: {}, fopen: '', fq: '', addf: '', focus: '', readonly: true, charts: new Map(), root: el, regen: '',
      noteOpen: '', drill: {}, dmenu: null, dsrc: {}, dnone: {}, dbusy: '', dprobe: {} };   // 읽기 전용 화면에서도 드릴다운은 된다(이 화면에서만, 서버 단계 포함) / drill-down works read-only too, server levels included
    el.classList.add('ai365-rdv');
    el.innerHTML = '<div class="ai365-rd-khost" data-rd-kpis>' + kpisHtml(ctx) + '</div>'
      + '<div class="ai365-rd-grid">' + state.charts.map(function (c) { return cardHtml(ctx, c); }).join('') + '</div>'
      + '<div class="ai365-rdv-src" data-rdv-src><h4>' + T('데이터 출처') + '</h4>' + state.sources.map(function (s) {
        const users = state.charts.filter(function (c) { return c.source === s.id; }).map(function (c) { return c.title; });
        return '<div class="row" data-rdv-row="' + E(s.id) + '"><b data-i18n-skip>' + E(srcLabel(s)) + '</b>'
          + '<span data-i18n-skip>' + E(when(s.fetched_at)) + ' · ' + s.rows.length + '</span><span>' + T('행') + '</span>'
          + (users.length ? '<span>' + T('쓰는 차트') + '</span><span data-i18n-skip>' + E(users.join(', ')) + '</span>' : '') + '</div>';
      }).join('') + '</div>';
    translate(el);
    const noop = function () {};
    el.addEventListener('click', function (e) {
      commonClick(ctx, e, noop);
    });
    el.addEventListener('change', function (e) { commonChange(ctx, e, noop); });
    el.addEventListener('input', function (e) { if (e.target.matches('[data-rdf-q]')) { ctx.fq = e.target.value; if (ctx.fopen) paintChartFilters(ctx, ctx.fopen.split(':')[0]); } });
    mountCharts(ctx);
    return { destroy: function () { destroyCharts(ctx); ctx.root = null; } };   // 늦게 온 드릴다운 답은 버린다 / late drill answers are dropped
  }

  window.AI365_reportDash = {
    open: open, close: close,
    openPost: function (postId, opts) { open(Object.assign({ post_id: postId, host: 'overlay' }, opts || {})); },
    isV2: function (d) { return !!(d && d.v === 2 && Array.isArray(d.charts) && Array.isArray(d.sources)); },
    viewer: { mount: viewerMount },
    compute: rdCompute, chartConfig: rdChartConfig,
  };
})();
