/* =====================================================================
   /home 대시보드 = 3열 격자 · 배치 편집 · 만든 위젯(2026-11-13 1단계, 2026-11-16 위젯 에이전트, 2026-11-17 4단계 — docs/widget-agent.md)
   GET /home 응답에만 주입된다(home-live.js 앞). 홈 파일의 #dash 에 data-hd="1" 이 있을 때만 움직인다 — 옛 홈 파일이면 아무것도 하지 않는다.
   ① 배치(4단계, 12절): 가로 3칸(열 너비 = 기본 비율 1:1:1 · 왼쪽 좁게 · 가운데 넓게) × 세로 칸(1칸 240px) 격자. 위젯마다 x · y · 가로 w · 세로 h 칸이고,
      위젯별 처음 크기 · 최소 · 최대(서버가 size 로 준다)를 지킨다. 기본 위젯은 홈 파일의 마크업을 그대로 옮기고(이벤트 유지), 만든 위젯은 서버가 계산한
      표시 모델로 그린다. 칸보다 내용이 길면 위젯 안에서 스크롤된다. 좁으면(격자 너비 900 미만) 2열 · 1열로 차례대로 채운다.
   ② 배치 편집: 톱니를 누르면 홈이 그 자리에서 편집 상태가 된다. 위젯을 끌어 옮기고, 오른쪽 아래 모서리로 크기를 바꾼다 — 끄는 동안 손을 따라오고
      점선이 놓을 자리 · 크기를 보이며(최소 · 최대에 걸리면 알린다) 놓으면 칸에 붙는다. 겹친 위젯은 아래로 밀리고 빈 곳은 위로 당겨진다. ✕ = 서랍(안 쓰는
      위젯)으로, [위젯 추가] = 서랍(미리보기 · 넣기 · 끌어 넣기 · 만든 위젯 휴지통), 기본 비율, [취소] · [저장](확인 창). 화살표 키 크기 조절은 없다(사용자 결정).
   ③ 문구는 한국어 텍스트 노드로 두고 영어는 home-live.js 사전이 바꾼다(그래서 바뀌는 말과 고정 문구를 한 노드에 섞지 않는다). 끄는 동안의 칸 수 안내는 여기서 짓는다.
   ④ 만든 위젯 = 리포트 에이전트의 작은 판(KPI 카드 · 차트 · 필터 표시 · 인사이트 · 글/목록 · 출처 줄). 차트는 리포트 에이전트의 그리기(report_dash.js 의
      rdChartConfig + Chart.js, 처음 필요할 때 불러온다)를 그대로 쓰고, 위젯 에이전트 화면도 window.AI365_homeWidget 으로 같은 그리기를 쓴다. 놓인 위젯 중 가져온
      내용이 있는 것은 GET …/data 로 새로 가져온다(3단계).
   The /home dashboard: a 3-column grid, layout editing and made widgets (phase 1 2026-11-13, the widget agent 2026-11-16, phase 4 2026-11-17).
   2026-11-20 위젯 에이전트 패널(docs/widget-agent.md 14절): 만든 위젯 머리에 [위젯 에이전트로 고치기] 아이콘, 에이전트가 고치는 동안 그 자리에
   작업본을 그리기(preview) · 아직 없는 새 위젯의 자리(ghost) · 새로 만든 위젯을 빈 첫 자리에 놓기(place) · 고치는 위젯 강조(focus).
   The widget agent panel (2026-11-20, section 14): an [Edit with the Widget Agent] icon on made widgets, drawing the agent's draft in place
   (preview), a spot for a widget not made yet (ghost), putting a just-made widget at the first free spot (place) and marking the edited one (focus).
   Injected only into the GET /home response (before home-live.js) and active only when the home file's #dash carries data-hd="1".
   (1) Layout (phase 4, section 12): three columns (widths = the base ratio) by rows of 240px; each widget has x, y, w and h in cells within
       its default, minimum and maximum size (sent by the server as size). Built-ins move their markup (listeners survive); made widgets are
       drawn from their server-computed model; content taller than its cells scrolls inside. Below 900px of grid width it flows into two or
       one column.
   (2) Layout editing: the gear turns the home itself into edit mode. Widgets move by dragging and resize from the bottom-right corner: they
       follow the hand, a dashed box shows where and how big they will land (limits are announced) and they snap on release; overlaps are
       pushed down and gaps pulled up. ✕ sends a widget to the drawer of unused widgets; [Add widget] opens the drawer (previews, add, drag
       in, trash for made widgets); base ratio; [Cancel] and [Save] with confirmations. No arrow-key resizing (user decision).
   (3) Labels stay Korean text nodes and home-live.js's dictionary swaps in English; drag labels with numbers are composed here.
   (4) A made widget is a small report-agent board; charts use the report agent's drawing (rdChartConfig plus Chart.js, loaded when first
       needed), shared with the widget agent screen through window.AI365_homeWidget. Placed widgets with fetched content refresh (phase 3).
===================================================================== */
(function () {
  'use strict';

  /* ── 순수 함수(노드 테스트가 그대로 부른다) / pure functions (called as is by the node tests) ── */
  const LAYOUTS = [
    { value: '1:1:1', ratios: [1, 1, 1], label: '1:1:1' },
    { value: '2:3:3', ratios: [2, 3, 3], label: '왼쪽 좁게' },
    { value: '1:2:1', ratios: [1, 2, 1], label: '가운데 넓게' },
  ];
  const NO_DATA = '표시할 데이터가 없습니다';
  const PENDING_TX = '데이터 연결 전';
  const CHART_FAIL = '차트를 불러오지 못했습니다';
  // 리포트 에이전트의 추세 범례 이름(rdChartConfig 가 한국어로 넣는다) → 영어 / the report agent's trend legend names (Korean from rdChartConfig) → English
  const TREND_EN = { '추세선': 'Trend line', '예측(참고용)': 'Forecast (reference)', '예측 범위': 'Forecast range' };
  const SVG_FUNNEL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 4h18l-7 8.5V19l-4 2v-8.5z"/></svg>';
  // 내용의 출처(3단계 데이터 파이프라인, docs/widget-agent.md 11절): 이름은 번역 사전이 바꾸는 고정 문구 / where the content came from (phase 3); names are dictionary-translated labels
  const SRC_LABEL = { data: '사내 데이터', docs: '사내 문서', web: '웹 검색' };
  const SRC_ICON = {
    data: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></svg>',
    docs: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/></svg>',
    web: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
  };
  const SEARCHING = '찾는 중';
  const SVG_SPARK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></svg>';

  function hdRatios(type) {
    const hit = LAYOUTS.filter(o => o.value === type)[0];
    return (hit || LAYOUTS[0]).ratios;
  }
  function hdGrid(type) { return hdRatios(type).map(r => r + 'fr').join(' '); }


  /* ── 격자(4단계, 2026-11-17 — docs/widget-agent.md 12절): 가로 3칸(열 너비 = 기본 비율) × 세로 칸(1칸 = ROW px, 간격 GAP). 위젯마다
     {key, x, y, w, h}. 서버(app/home_widgets.normalize_config · settle)와 같은 규칙이다.
     the grid (phase 4): three columns (widths = the base ratio) by rows of ROW px with GAP gaps; each widget is {key, x, y, w, h}; the server's rules ── */
  const GRID_COLS = 3, ROW = 240, GAP = 16, MAX_ROW = 300;
  const DEF_SIZE = { w: 1, h: 1, min_w: 1, max_w: 3, min_h: 1, max_h: 3 };

  // 위젯 목록(서버가 준 size 포함) → {키: 크기} / the widget list (with the server's size) → {key: size}
  function hdSizes(widgets) {
    const out = {};
    (widgets || []).forEach(w => {
      if (w && typeof w.key === 'string') out[w.key] = Object.assign({}, DEF_SIZE, (w.size && typeof w.size === 'object') ? w.size : {});
    });
    return out;
  }
  function hdInt(v, fb) { return (typeof v === 'number' && isFinite(v)) ? Math.round(v) : fb; }
  // 크기 · 위치 맞추기: 가로 · 세로는 그 위젯의 최소 · 최대(가로는 3칸까지), x 는 0 ~ 3 − 가로, y 는 0 이상 / fit size and position
  function hdFit(it, size) {
    const s = size || DEF_SIZE;
    const w = Math.min(Math.max(hdInt(it.w, s.w), s.min_w), Math.min(s.max_w, GRID_COLS));
    const h = Math.min(Math.max(hdInt(it.h, s.h), s.min_h), s.max_h);
    return { key: it.key, x: Math.min(Math.max(hdInt(it.x, 0), 0), GRID_COLS - w), y: Math.min(Math.max(hdInt(it.y, 0), 0), MAX_ROW), w: w, h: h };
  }
  function hdOverlap(a, b) { return a !== b && a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h; }
  // 겹침 풀기 + 위로 당기기: 위에서 아래 · 왼쪽에서 오른쪽 차례로 앞에 놓인 위젯과 겹치면 그 아래로 밀고, 다 놓은 뒤 위가 빈 위젯은 위로 당긴다.
  // fixedKey 의 위젯은 먼저 놓아 자리를 지키고 나머지가 비킨다. 이미 정리된 배치는 그대로다(서버 settle 과 같다)
  // resolve overlaps and pull gaps up; the fixedKey widget is placed first and keeps its spot. Idempotent, like the server's settle
  function hdSettle(items, fixedKey) {
    const list = items.map((it, i) => Object.assign({}, it, { _i: i }));
    const fixed = fixedKey == null ? null : (list.filter(i => i.key === fixedKey)[0] || null);
    const placed = fixed ? [fixed] : [];
    list.filter(i => i !== fixed).sort((a, b) => a.y - b.y || a.x - b.x || a._i - b._i).forEach(it => {
      let hit;
      while ((hit = placed.filter(q => hdOverlap(it, q))[0])) it.y = hit.y + hit.h;
      placed.push(it);
    });
    placed.slice().sort((a, b) => a.y - b.y || a.x - b.x).forEach(it => {
      while (it.y > 0) {
        it.y--;
        if (placed.some(o => hdOverlap(it, o))) { it.y++; break; }
      }
    });
    return placed.sort((a, b) => a.y - b.y || a.x - b.x).map(it => ({ key: it.key, x: it.x, y: it.y, w: it.w, h: it.h }));
  }
  // 서버 배치 + 위젯 목록 → 화면 상태 {layout, items, unused}. 모르는 키 · 두 번째로 나온 키는 버리고, 잠근 위젯(날씨)이 없으면 맨 위에 넣는다
  // server layout + the widget list → screen state; unknown and repeated keys are dropped and a missing locked widget goes on top
  function hdState(config, widgets) {
    const sizes = hdSizes(widgets), list = [], seen = {};
    ((config && Array.isArray(config.items)) ? config.items : []).forEach(it => {
      const k = it && typeof it.widget_key === 'string' ? it.widget_key.trim() : '';   // 서버처럼 앞뒤 공백을 뺀다 / stripped like the server
      if (!k || !sizes[k] || seen[k]) return;
      seen[k] = 1;
      list.push(hdFit({ key: k, x: it.x, y: it.y, w: it.w, h: it.h }, sizes[k]));
    });
    (widgets || []).forEach(w => {
      if (w && w.locked && sizes[w.key] && !seen[w.key]) { seen[w.key] = 1; list.unshift(hdFit({ key: w.key }, sizes[w.key])); }
    });
    const type = config && typeof config.layout_type === 'string' ? config.layout_type.trim() : '';
    return { layout: LAYOUTS.some(o => o.value === type) ? type : LAYOUTS[0].value, items: hdSettle(list),
      unused: (widgets || []).map(w => w && w.key).filter(k => typeof k === 'string' && !seen[k]) };
  }
  function hdConfig(st) { return { layout_type: st.layout, items: st.items.map(i => ({ widget_key: i.key, x: i.x, y: i.y, w: i.w, h: i.h })) }; }
  function hdClone(st) { return { layout: st.layout, items: st.items.map(i => Object.assign({}, i)), unused: st.unused.slice() }; }
  function hdSame(a, b) { return JSON.stringify(hdConfig(a)) === JSON.stringify(hdConfig(b)); }
  // 옮기거나 크기를 바꾼 뒤의 상태: 나머지가 먼저 그 위젯 없이 빈 곳을 당겨 정리되고, 그 위젯이 새 자리에 놓이면 겹친 위젯이 아래로 비킨다 —
  // 그래서 바로 아래 위젯 위에 놓으면 둘이 자리를 바꾼다(그 위젯을 고정한 채 한 번에 정리하면 위로 당기기가 그 위젯을 원래 칸으로 되돌렸다, 4단계 검토)
  // the state after a move or resize: the others first close up without it, then it takes its new spot and overlapping widgets move down —
  // so dropping onto the widget right below swaps the two (settling once with it fixed pulled it back into its old cells; phase-4 review)
  function hdPlace(st, key, x, y, w, h, size) {
    if (!st.items.some(i => i.key === key)) return st;
    const f = hdFit({ key: key, x: x, y: y, w: w, h: h }, size), next = hdClone(st);
    next.items = hdSettle(hdSettle(next.items.filter(i => i.key !== key)).concat([f]), key);
    return next;
  }
  // 빈 첫 자리(위에서 아래, 왼쪽에서 오른쪽, cols = 열 수 · 기본 3) / the first free spot, top to bottom and left to right (cols defaults to 3)
  function hdFree(items, w, h, cols) {
    const c = cols || GRID_COLS;
    for (let y = 0; y < MAX_ROW; y++) {
      for (let x = 0; x <= c - w; x++) {
        const box = { x: x, y: y, w: w, h: h };
        if (!items.some(i => hdOverlap(box, i))) return { x: x, y: y };
      }
    }
    return { x: 0, y: 0 };
  }
  // 서랍의 위젯을 홈에 놓기: 자리를 주면 그 자리(나머지가 비킨다), 없으면 빈 첫 자리. 처음 크기로 / put a drawer widget on the home at its default size
  function hdAdd(st, key, size, x, y) {
    const i = st.unused.indexOf(key);
    if (i < 0) return st;
    const next = hdClone(st), s = Object.assign({}, DEF_SIZE, size || {});
    next.unused.splice(i, 1);
    const at = (x == null || y == null) ? hdFree(next.items, Math.min(s.w, GRID_COLS), s.h) : { x: x, y: y };
    next.items.push(hdFit({ key: key, x: at.x, y: at.y, w: s.w, h: s.h }, s));
    next.items = hdSettle(next.items, key);
    return next;
  }
  // 홈에서 빼기(서랍으로) — 잠근 위젯은 뺄 수 없다 / remove to the drawer; a locked widget stays
  function hdRemove(st, key, locked) {
    if (locked) return st;
    const next = hdClone(st), before = next.items.length;
    next.items = next.items.filter(i => i.key !== key);
    if (next.items.length === before) return st;
    next.unused.push(key);
    next.items = hdSettle(next.items);
    return next;
  }
  // 열 너비 · 왼쪽 끝(px) / column widths and left edges (px)
  function hdTracks(layout, width, gap) {
    const r = hdRatios(layout), g = gap == null ? GAP : gap, sum = r[0] + r[1] + r[2], free = Math.max(0, width - g * (GRID_COLS - 1));
    const w = r.map(v => free * v / sum);
    return { w: w, l: [0, w[0] + g, w[0] + w[1] + 2 * g] };
  }
  function hdSpanW(t, x, w) { return t.l[x + w - 1] + t.w[x + w - 1] - t.l[x]; }
  // 끌어 옮길 자리: 위젯 왼쪽 위(격자 기준 px) → 가장 가까운 칸 / the nearest cell for a dragged widget's top-left (px in the grid)
  function hdSnapMove(left, top, w, t, row, gap) {
    let bx = 0, bd = Infinity;
    for (let x = 0; x <= GRID_COLS - w; x++) {
      const d = Math.abs(left - t.l[x]);
      if (d < bd) { bd = d; bx = x; }
    }
    const r = row || ROW, g = gap == null ? GAP : gap;
    return { x: bx, y: Math.max(0, Math.round(top / (r + g))) };
  }
  // 끌어 바꿀 크기: x 에서 시작하는 너비 · 높이(px) → 가장 가까운 칸 수를 위젯의 최소 · 최대로 맞춘다. wantW · wantH = 맞추기 전(안내용)
  // the nearest cell counts for a width and height from x, fitted to the widget's limits; wantW / wantH are before fitting (for the notice)
  function hdSnapSize(x, width, height, size, t, row, gap) {
    const s = size || DEF_SIZE, r = row || ROW, g = gap == null ? GAP : gap;
    let bw = 1, bd = Infinity;
    for (let w = 1; w <= GRID_COLS - x; w++) {
      const d = Math.abs(width - hdSpanW(t, x, w));
      if (d < bd) { bd = d; bw = w; }
    }
    const wantH = Math.max(1, Math.round((height + g) / (r + g)));
    return { w: Math.min(Math.max(bw, s.min_w), Math.min(s.max_w, GRID_COLS)), h: Math.min(Math.max(wantH, s.min_h), s.max_h), wantW: bw, wantH: wantH };
  }
  // 좁은 화면(2열 · 1열): 격자 차례(y · x)대로 빈 첫 자리에 놓는다(가로는 열 수까지, 세로는 그대로) / narrow screens: flow in grid order
  function hdFlow(items, cols) {
    const placed = [];
    items.slice().sort((a, b) => a.y - b.y || a.x - b.x).forEach(it => {
      const w = Math.min(it.w, cols), at = hdFree(placed, w, it.h, cols);
      placed.push({ key: it.key, x: at.x, y: at.y, w: w, h: it.h });
    });
    return placed;
  }
  // 격자 → 옛 세 열(옛 브라우저 저장본 옮기기의 바탕) / the grid as three columns (the base for moving an old browser layout)
  function hdColumnsOf(st) {
    const cols = [[], [], []];
    st.items.slice().sort((a, b) => a.y - b.y || a.x - b.x).forEach(i => { cols[Math.min(Math.max(i.x, 0), 2)].push(i.key); });
    return { layout: st.layout, cols: cols, unused: st.unused.slice() };
  }

  // 옛 브라우저 저장본(ai365_home_widgets_v2 = {cols: {l, m, r}, hidden}) → 옛 세 열 {layout, cols, unused}(서버가 격자로 바꾼다). 저장본에 없던
  // 위젯은 기본 열에, 숨긴 위젯은 서랍(안 쓰는 위젯)으로(한 열을 전부 숨겼으면 하나는 되돌려 놓는다). 읽을 수 없는 저장본은 null
  // the old browser-saved layout → three columns {layout, cols, unused} (the server makes them a grid); widgets it never knew join
  // their default column and hidden ones go to the drawer (one returns when a whole column was hidden); an unreadable one is null
  function hdLegacy(saved, keys, base) {
    if (!saved || typeof saved !== 'object' || !saved.cols || typeof saved.cols !== 'object') return null;
    const known = {}, hidden = {}, seen = {}, cols = [[], [], []];
    keys.forEach(k => { known[k] = 1; });
    (Array.isArray(saved.hidden) ? saved.hidden : []).forEach(k => { hidden[k] = 1; });
    const take = (k, i) => { if (!known[k] || seen[k]) return; seen[k] = 1; if (!hidden[k]) cols[i].push(k); };
    ['l', 'm', 'r'].forEach((name, i) => { (Array.isArray(saved.cols[name]) ? saved.cols[name] : []).forEach(k => take(k, i)); });
    base.cols.forEach((list, i) => list.forEach(k => take(k, i)));
    const placed = {};
    cols.forEach(c => c.forEach(k => { placed[k] = 1; }));
    // 옛 화면은 한 열의 위젯을 전부 숨길 수 있었지만 지금은 빈 열을 저장할 수 없다 → 빈 열에는 숨겼던 위젯 하나(그 열의 기본 위젯 먼저)를 되돌려 놓는다
    // the old screen could hide a whole column, but an empty column can no longer be saved, so one hidden widget (that column's default first) returns to it
    cols.forEach((c, i) => {
      if (c.length) return;
      const back = base.cols[i].concat(keys).filter(k => known[k] && !placed[k])[0];
      if (back) { c.push(back); placed[back] = 1; }
    });
    return { layout: base.layout, cols: cols, unused: keys.filter(k => !placed[k]) };
  }

  function hdEsc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  // 증감률 표기(소수 첫째 자리) / a change rate with one decimal
  function hdPct(x) { return String(Math.round(Math.abs(Number(x)) * 10) / 10) + '%'; }

  // KPI 카드 줄: 1개는 크게, 2 · 4개는 2열, 3개는 3열. 이름 · 숫자 · 설명은 사용자의 데이터라 번역하지 않고, '데이터 연결 전' 표시만 번역한다
  // the KPI card row: one card large, two or four in two columns, three in three. Names, numbers and notes are user data and
  // never translated; only the 'not connected yet' tag is
  function hdKpiHtml(list) {
    const n = list.length, cols = n === 1 ? 1 : (n === 3 ? 3 : 2);
    return '<div class="hw-kpis' + (n === 1 ? ' one' : '') + '" style="grid-template-columns:repeat(' + cols + ',minmax(0,1fr))">' + list.map(k => {
      const pend = !!k.pending, d = (typeof k.delta === 'number' && isFinite(k.delta)) ? k.delta : null;
      const delta = (!pend && d !== null) ? '<span class="d' + (d > 0 ? ' up' : (d < 0 ? ' down' : '')) + '" data-i18n-skip>' + (d > 0 ? '▲ ' : (d < 0 ? '▼ ' : '')) + hdEsc(hdPct(d)) + '</span>' : '';
      return '<div class="hw-kt' + (pend ? ' pend' : '') + '"><span class="l" data-i18n-skip>' + hdEsc(k.label) + '</span>' +
        '<b class="v" data-i18n-skip>' + (pend || !k.text ? '–' : hdEsc(k.text)) + '</b>' + (pend ? '<span class="tag">' + PENDING_TX + '</span>' : delta) +
        (k.note ? '<span class="n" data-i18n-skip>' + hdEsc(k.note) + '</span>' : '') + '</div>';
    }).join('') + '</div>';
  }

  // 위젯 정의 v2 의 표시 모델(docs/widget-agent.md 7절) → 위젯 본문 HTML: KPI 카드 줄 · 차트 자리(캔버스, 숫자 카드면 큰 숫자) · 필터 조건 · 인사이트.
  // 차트는 캔버스만 두고 hdChartConfig 로 그린다. 모델이 아니거나(옛 1단계 모델 포함) 비었으면 '표시할 데이터가 없습니다'
  // the v2 display model (docs/widget-agent.md section 7) → widget body HTML: KPI row, a chart slot (a canvas, or a big number for a number card),
  // fixed conditions and the insight. Charts get a canvas only and are drawn through hdChartConfig. Anything else (phase 1 models included) or an empty model reads 'No data to show'
  function hdWidgetHtml(m) {
    const none = '<div class="hd-none">' + NO_DATA + '</div>';
    if (!m || typeof m !== 'object' || m.v !== 2 || m.empty) return none;
    // 미리 그리기(위젯 에이전트가 데이터를 찾는 동안 보내는 초안): 아직 없는 칸은 자리만 / the early draft while the agent searches: missing parts get placeholders
    const sk = (m.skeleton && typeof m.skeleton === 'object') ? m.skeleton : null;
    const blocks = Array.isArray(m.blocks) ? m.blocks.filter(b => b && typeof b === 'object') : [];
    const has = t => blocks.some(b => b.type === t);
    let h = '';
    if (Array.isArray(m.kpis) && m.kpis.length) h += hdKpiHtml(m.kpis);
    else if (sk && sk.view === 'kpi') h += hdSkKpis(sk.labels);
    const c = m.chart;
    if (c && typeof c === 'object') {
      if (c.type === 'kpi') h += '<div class="hw-big"><b data-i18n-skip>' + hdEsc(c.text || '–') + '</b>' + (c.label ? '<span data-i18n-skip>' + hdEsc(c.label) + '</span>' : '') + '</div>';
      else if (c.empty || !c.config || !c.data) h += none;
      else h += '<div class="hw-cv"><canvas data-hw-canvas role="img" aria-label="' + hdEsc(m.title || '') + '"></canvas></div>';
      if (Array.isArray(c.filters) && c.filters.length) {
        h += '<div class="hw-tags">' + c.filters.map(t => '<span class="hw-tag">' + SVG_FUNNEL + '<span data-i18n-skip>' + hdEsc(t) + '</span></span>').join('') + '</div>';
      }
    } else if (sk && sk.view === 'chart') h += '<div class="hw-sk-cv" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i></div>';
    h += hdBlocksHtml(blocks);
    if (sk && sk.view === 'list' && !has('list')) h += '<div class="hw-sk-ls" aria-hidden="true"><i></i><i></i><i></i></div>';
    if (sk && sk.view === 'text' && !has('text')) h += '<div class="hw-sk-tx" aria-hidden="true"><i></i><i></i><i></i></div>';
    if (m.insight) h += '<div class="hw-ins">' + SVG_SPARK + '<span data-i18n-skip>' + hdEsc(m.insight) + '</span></div>';
    if (sk) {
      h += '<div class="hw-wait"><span class="dot" aria-hidden="true"></span><span>' + SEARCHING + '</span>' +
        (Array.isArray(sk.sources) ? sk.sources : []).map(s => '<span class="c">' + hdEsc(s) + '</span>').join('') + '</div>';
    } else h += hdOriginHtml(m);
    return '<div class="hw" data-hw>' + (h || none) + '</div>';
  }

  // 숫자가 아닌 내용: 글(그대로) · 목록(제목 — 주소가 http(s) 면 새 창 링크 — 과 한 줄 설명). 사용자 데이터라 번역하지 않는다
  // non-numeric content: text as is, and a list (titles, linked in a new tab when the address is http(s), with one line under each); user data, never translated
  function hdBlocksHtml(blocks) {
    const url = u => (typeof u === 'string' && /^https?:\/\//i.test(u)) ? u : '';
    return (blocks || []).map(b => {
      if (b.type === 'text' && b.text) return '<p class="hw-tx" data-i18n-skip>' + hdEsc(b.text) + '</p>';
      if (b.type !== 'list' || !Array.isArray(b.items) || !b.items.length) return '';
      return '<ul class="hw-ls" data-i18n-skip>' + b.items.filter(it => it && it.title).map(it => {
        const u = url(it.url), t = hdEsc(it.title);
        return '<li>' + (u ? '<a class="t" href="' + hdEsc(u) + '" target="_blank" rel="noopener noreferrer">' + t + '</a>' : '<span class="t">' + t + '</span>') +
          (it.sub ? '<span class="s">' + hdEsc(it.sub) + '</span>' : '') + '</li>';
      }).join('') + '</ul>';
    }).join('');
  }

  // 위젯의 출처들(부분마다 하나 — 서버가 종류별로 묶어 준다) 중 가장 늦게 가져온 시각 / the latest fetch time across a model's origins
  function hdFetchedAt(m) {
    return ((m && Array.isArray(m.origins)) ? m.origins : []).reduce((a, o) => (o && typeof o.fetched_at === 'string' && o.fetched_at > a ? o.fetched_at : a), '');
  }
  // 출처 줄: 어디서(종류마다 아이콘 + 고정 이름, 번역) · 근거 두 개까지(웹은 링크, 문서는 쪽) · 가장 늦게 가져온 시각(월/일 시:분)
  // the origin line: where (an icon and a translated label per kind), up to two references (links for the web, pages for documents)
  // and the latest fetch time (month/day hour:minute)
  function hdOriginHtml(m) {
    const kinds = (Array.isArray(m.origins) ? m.origins : []).filter(o => o && typeof o === 'object' && SRC_LABEL[o.kind]);
    if (!kinds.length) return '';
    const refs = Array.isArray(m.refs) ? m.refs.filter(r => r && r.label) : [];
    const one = r => {
      const label = hdEsc(r.label) + (r.page ? ' p.' + hdEsc(r.page) : '');
      return (typeof r.url === 'string' && /^https?:\/\//i.test(r.url)) ? '<a href="' + hdEsc(r.url) + '" target="_blank" rel="noopener noreferrer">' + label + '</a>' : '<span>' + label + '</span>';
    };
    const at = /^\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(hdFetchedAt(m));
    return '<div class="hw-src">' + kinds.map(o => SRC_ICON[o.kind] + '<span class="k">' + SRC_LABEL[o.kind] + '</span>').join('') +
      (refs.length ? '<span class="r" data-i18n-skip>' + refs.slice(0, 2).map(one).join('<i aria-hidden="true">·</i>') + (refs.length > 2 ? '<span>+' + (refs.length - 2) + '</span>' : '') + '</span>' : '') +
      (at ? '<span class="at" data-i18n-skip>' + at[1] + '/' + at[2] + ' ' + at[3] + ':' + at[4] + '</span>' : '') + '</div>';
  }

  // 미리 그리기의 KPI 칸: 의도 판단이 정한 카드 이름이 있으면 그 이름, 숫자 자리는 반짝이는 막대 / draft KPI slots: the planned names, shimmering bars for the numbers
  function hdSkKpis(labels) {
    const list = (Array.isArray(labels) && labels.length ? labels : ['']).slice(0, 4), n = list.length;
    return '<div class="hw-kpis' + (n === 1 ? ' one' : '') + '" style="grid-template-columns:repeat(' + (n === 1 ? 1 : (n === 3 ? 3 : 2)) + ',minmax(0,1fr))">' +
      list.map(l => '<div class="hw-kt sk">' + (l ? '<span class="l" data-i18n-skip>' + hdEsc(l) + '</span>' : '<i class="hw-bar" aria-hidden="true"></i>') +
        '<i class="hw-bar big" aria-hidden="true"></i></div>').join('') + '</div>';
  }

  // 차트 모델 → Chart.js 구성: 리포트 에이전트의 rdChartConfig 를 그대로 부른다(같은 색 · 기준선 · 강조 · 추세선 · 값 라벨). 영어면 추세 범례만 바꾼다
  // chart model → a Chart.js config through the report agent's rdChartConfig (same colours, reference lines, highlights, trend, value labels); English swaps the trend legend only
  function hdChartConfig(m, rdChartConfig, opts) {
    opts = opts || {};
    const cfg = rdChartConfig(m.chart.config, m.chart.data, { theme: m.theme || null, still: !!opts.still });
    if (opts.en) ((cfg.data && cfg.data.datasets) || []).forEach(d => { if (TREND_EN[d.label]) d.label = TREND_EN[d.label]; });
    return cfg;
  }

  const PURE = { LAYOUTS: LAYOUTS, GRID_COLS: GRID_COLS, ROW: ROW, GAP: GAP, DEF_SIZE: DEF_SIZE, hdRatios: hdRatios, hdGrid: hdGrid, hdSizes: hdSizes,
    hdFit: hdFit, hdOverlap: hdOverlap, hdSettle: hdSettle, hdState: hdState, hdConfig: hdConfig, hdClone: hdClone, hdSame: hdSame, hdPlace: hdPlace,
    hdFree: hdFree, hdAdd: hdAdd, hdRemove: hdRemove, hdTracks: hdTracks, hdSpanW: hdSpanW, hdSnapMove: hdSnapMove, hdSnapSize: hdSnapSize,
    hdFlow: hdFlow, hdColumnsOf: hdColumnsOf, hdLegacy: hdLegacy, hdEsc: hdEsc, hdPct: hdPct, hdKpiHtml: hdKpiHtml, hdWidgetHtml: hdWidgetHtml,
    hdBlocksHtml: hdBlocksHtml, hdOriginHtml: hdOriginHtml, hdFetchedAt: hdFetchedAt, hdChartConfig: hdChartConfig, SRC_LABEL: SRC_LABEL };
  if (typeof module !== 'undefined' && module.exports) module.exports = PURE;
  if (typeof document === 'undefined') return;

  /* ── 화면 / screen ── */
  const dash = document.getElementById('dash');
  if (!dash || dash.dataset.hd !== '1') return;   // 옛 홈 파일(자체 편집 모드)이면 손대지 않는다 / an older home file (own edit mode) is left alone
  const gear = document.getElementById('editBtn'), gearTx = document.getElementById('editBtnTx');
  const hero = dash.closest('.hero');

  const LS_OLD = 'ai365_home_widgets_v2', LS_CACHE = 'ai365_home_dash_v5';
  const TX = {
    edit: '배치 편집', hint: '위젯을 끌어 옮기고, 오른쪽 아래 모서리로 크기를 바꾸세요.', ratio: '기본 비율', add: '위젯 추가', put: '넣기',
    allPlaced: '모든 위젯이 홈에 있습니다', remove: '홈에서 빼기', resize: '크기 조절', cancel: '취소', save: '저장', close: '닫기',
    del: '위젯 삭제', cancelAsk: '배치 편집을 취소하시겠습니까?', cancelWarn: '저장하지 않으면 변경 사항이 적용되지 않습니다.',
    saveAsk: '배치를 저장하시겠습니까?', saved: '배치를 저장했습니다', saveFail: '배치를 저장하지 못했습니다',
    delAsk: '위젯을 삭제하시겠습니까?', delWarn: '삭제한 위젯은 되돌릴 수 없습니다.', delBtn: '삭제', deleted: '위젯을 삭제했습니다', delFail: '위젯을 삭제하지 못했습니다',
    agentEdit: '위젯 에이전트로 고치기', fresh: '새 위젯',
    loadFail: '배치를 불러오지 못했습니다', moved: '사용자가 바뀌어 대시보드를 다시 불러왔습니다', narrow: '배치 편집은 넓은 화면에서 할 수 있습니다',
  };
  // 끄는 동안의 안내(칸 수가 들어간다)는 사전 대신 여기서 짓는다 / drag notices with numbers are composed here instead of the dictionary
  const DYN = { drop: ['여기에 놓기', 'Drop here'], size: ['놓으면 가로 {w} × 세로 {h}', 'Drop: {w} wide × {h} tall'],
    maxW: [' · 최대 가로 {n}칸', ' · up to {n} wide'], minW: [' · 최소 가로 {n}칸', ' · at least {n} wide'],
    maxH: [' · 최대 세로 {n}칸', ' · up to {n} tall'], minH: [' · 최소 세로 {n}칸', ' · at least {n} tall'] };
  function Ld(k, vars) {
    let s = DYN[k][isEn() ? 1 : 0];
    Object.keys(vars || {}).forEach(v => { s = s.split('{' + v + '}').join(String(vars[v])); });
    return s;
  }
  const svg = d => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + d + '</svg>';
  const ICON = {
    x: svg('<path d="M18 6 6 18M6 6l12 12"/>'),
    plus: svg('<path d="M12 5v14M5 12h14"/>'),
    save: svg('<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7M7 3v4a1 1 0 0 0 1 1h7"/>'),
    trash: svg('<path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M10 11v6M14 11v6"/>'),
  };

  const CSS = [
    '.hd-pool{display:none !important;}',
    /* 만든 위젯 본문 = 홈의 기본 위젯과 같은 값(목록 12.5 · 표 머리 11 · 숫자 타일 #F8F9FA) / made-widget bodies use the built-ins' values */
    '.hd-body{padding:14px 16px 16px;min-width:0;}',
    '.hd-none{padding:24px 0;text-align:center;font-size:12px;color:#ABADB8;}',
    /* 만든 위젯(v2) = KPI 카드 줄 · 차트(200 높이) · 필터 조건 · 인사이트. KPI 카드는 1단계 숫자 타일과 같은 값(#F8F9FA · 20/26),
       데이터 연결 전 카드는 점선 + 옅은 노랑 표시 / a made widget (v2) = KPI row, chart (200 high), fixed conditions, insight; KPI tiles keep phase 1's values,
       a not-connected card gets a dashed rule and a pale amber tag */
    '.hw{display:flex;flex-direction:column;gap:12px;min-width:0;}',
    '.hw-kpis{display:grid;gap:8px;}',
    '.hw-kt{min-width:0;display:flex;flex-direction:column;align-items:flex-start;gap:2px;background:#F8F9FA;border:1px solid transparent;border-radius:10px;padding:12px 14px;}',
    '.hw-kt .l{max-width:100%;font-size:12px;line-height:16px;color:#6B6D79;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.hw-kt .v{max-width:100%;font-size:20px;line-height:26px;font-weight:700;color:#33343E;font-variant-numeric:tabular-nums;overflow-wrap:anywhere;}',
    '.hw-kpis.one .hw-kt{padding:14px 16px;}',
    '.hw-kpis.one .hw-kt .v{font-size:30px;line-height:38px;color:var(--primary);}',
    '.hw-kt .d{font-size:11.5px;line-height:16px;font-weight:600;color:var(--muted);font-variant-numeric:tabular-nums;}',
    '.hw-kt .d.up{color:#1BA672;}',
    '.hw-kt .d.down{color:#E35B62;}',
    '.hw-kt .n{max-width:100%;font-size:11px;line-height:15px;color:#8A8C99;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.hw-kt.pend{background:#FBFBFD;border:1px dashed #D5D9E4;}',
    '.hw-kt.pend .v{color:#B9BDC8;}',
    '.hw-kt .tag{margin-top:2px;padding:1px 8px;border-radius:9999px;background:#FFF4DB;font-size:10.5px;line-height:16px;font-weight:600;color:#8A5A00;white-space:nowrap;}',
    '.hw-cv{position:relative;height:200px;min-width:0;}',
    '.hw-big{display:flex;flex-direction:column;gap:2px;padding:4px 0 2px;}',
    '.hw-big b{font-size:32px;line-height:40px;font-weight:700;color:var(--primary);font-variant-numeric:tabular-nums;overflow-wrap:anywhere;}',
    '.hw-big span{font-size:13px;line-height:18px;color:var(--muted);}',
    '.hw-tags{display:flex;flex-wrap:wrap;gap:6px;}',
    '.hw-tag{display:inline-flex;align-items:center;gap:4px;max-width:100%;padding:2px 9px;border-radius:9999px;background:var(--table-head);font-size:11px;line-height:17px;color:var(--ink-3);white-space:nowrap;overflow:hidden;}',
    '.hw-tag span{overflow:hidden;text-overflow:ellipsis;}',
    '.hw-tag svg{width:11px;height:11px;}',
    '.hw-ins{display:flex;align-items:flex-start;gap:8px;padding:10px 12px;border-radius:10px;background:var(--primary-soft);font-size:12.5px;line-height:19px;color:var(--ink-2);word-break:keep-all;overflow-wrap:anywhere;}',
    '.hw-ins svg{width:14px;height:14px;margin-top:2px;color:var(--primary);}',
    /* 3단계 = 글 · 목록 · 출처 줄 · 미리 그리기(반짝이는 자리) / phase 3: text, lists, the origin line and the early draft (shimmering slots) */
    '.hw-tx{margin:0;font-size:13px;line-height:20px;color:var(--ink-2);white-space:pre-wrap;word-break:keep-all;overflow-wrap:anywhere;}',
    '.hw-ls{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;min-width:0;}',
    '.hw-ls li{display:flex;flex-direction:column;gap:1px;min-width:0;padding:8px 0;border-top:1px solid #F0F1F5;}',
    '.hw-ls li:first-child{padding-top:0;border-top:0;}',
    '.hw-ls li:last-child{padding-bottom:0;}',
    '.hw-ls .t{font-size:13px;line-height:19px;font-weight:600;color:var(--ink);text-decoration:none;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;word-break:keep-all;overflow-wrap:anywhere;}',
    '.hw-ls a.t:hover{color:var(--primary);text-decoration:underline;text-underline-offset:2px;}',
    '.hw-ls a.t:focus-visible,.hw-src a:focus-visible{outline:2px solid var(--primary);outline-offset:2px;border-radius:2px;}',
    '.hw-ls .s{font-size:11.5px;line-height:16px;color:#8A8C99;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.hw-src{display:flex;align-items:center;gap:6px;min-width:0;padding-top:2px;font-size:11px;line-height:16px;color:#8A8C99;}',
    '.hw-src svg{flex-shrink:0;width:12px;height:12px;}',
    '.hw-src .k{flex-shrink:0;font-weight:600;color:var(--ink-3);}',
    '.hw-src .r{flex:1;min-width:0;display:flex;gap:4px;overflow:hidden;white-space:nowrap;}',
    '.hw-src .r a,.hw-src .r span{min-width:0;overflow:hidden;text-overflow:ellipsis;}',
    '.hw-src .r i{font-style:normal;}',
    '.hw-src a{color:inherit;text-decoration:underline;text-underline-offset:2px;}',
    '.hw-src a:hover{color:var(--primary);}',
    '.hw-src .at{flex-shrink:0;margin-left:auto;font-variant-numeric:tabular-nums;}',
    '.hw-bar,.hw-sk-cv i,.hw-sk-ls i,.hw-sk-tx i{display:block;border-radius:6px;background:linear-gradient(90deg,#ECEEF4 0%,#F7F8FB 50%,#ECEEF4 100%);background-size:200% 100%;animation:hwSk 1.3s ease-in-out infinite;}',
    '.hw-bar{width:42%;height:10px;margin:3px 0;}',
    '.hw-bar.big{width:64%;height:22px;margin-top:6px;}',
    '.hw-kpis.one .hw-bar.big{height:30px;}',
    '.hw-sk-cv{height:200px;display:flex;align-items:flex-end;gap:10px;padding:16px 8px 0;border-bottom:1px solid #ECEEF4;}',
    '.hw-sk-cv i{flex:1;border-radius:4px 4px 0 0;}',
    '.hw-sk-cv i:nth-child(1){height:42%;}.hw-sk-cv i:nth-child(2){height:66%;}.hw-sk-cv i:nth-child(3){height:52%;}',
    '.hw-sk-cv i:nth-child(4){height:84%;}.hw-sk-cv i:nth-child(5){height:60%;}.hw-sk-cv i:nth-child(6){height:74%;}',
    '.hw-sk-ls,.hw-sk-tx{display:flex;flex-direction:column;gap:10px;}',
    '.hw-sk-ls i{height:30px;}',
    '.hw-sk-tx i{height:12px;}',
    '.hw-sk-tx i:last-child{width:62%;}',
    '.hw-wait{display:flex;align-items:center;flex-wrap:wrap;gap:6px;font-size:11.5px;line-height:17px;color:var(--muted);}',
    '.hw-wait .dot{width:6px;height:6px;border-radius:50%;background:var(--primary);animation:hwPulse 1s ease-in-out infinite;}',
    '.hw-wait .c{padding:1px 8px;border-radius:9999px;background:var(--table-head);color:var(--ink-3);}',
    '@keyframes hwSk{0%{background-position:100% 0;}100%{background-position:-100% 0;}}',
    '@keyframes hwPulse{0%,100%{opacity:.35;}50%{opacity:1;}}',
    '@media (prefers-reduced-motion: reduce){.hw-bar,.hw-sk-cv i,.hw-sk-ls i,.hw-sk-tx i,.hw-wait .dot{animation:none;}}',
    /* 4단계 격자(1칸 240 · 간격 16): 위젯은 칸을 꽉 채우고, 내용이 길면 위젯 안에서 스크롤(머리는 붙어 있다). 만든 위젯의 차트는 남는 높이를 채운다
       the phase-4 grid (rows of 240, gaps of 16): widgets fill their cells and scroll inside (the head stays); made widgets' charts fill the space left */
    '#dash.hd-grid{grid-template-columns:var(--hd-cols,1fr 1fr 1fr);grid-auto-rows:240px;align-items:stretch;position:relative;}',
    '#dash.hd-grid > .wg{min-height:0;overflow-y:auto;overscroll-behavior:contain;}',
    '#dash.hd-grid > .wg > .wg-head{position:sticky;top:0;z-index:2;background:#fff;}',
    '#dash.hd-grid > .hd-cw > .hd-body{flex:1 0 auto;display:flex;flex-direction:column;}',
    '#dash.hd-grid > .hd-cw .hw{flex:1 0 auto;}',
    '#dash.hd-grid > .hd-cw .hw-cv{flex:1 1 0;height:auto;min-height:150px;}',
    /* 배치 편집 막대(편집 중에는 톱니 · 에이전트 탭을 숨긴다) / the edit bar (the gear and agent tabs hide while editing) */
    'body.hd-edit #editBtn,body.hd-edit #waBtn,body.hd-edit .ph .seg{display:none !important;}',
    'body.sec-on .hd-ebar,body.eapp-on .hd-ebar{display:none !important;}',
    /* 만든 위젯 머리: 이름(넘치면 …) + [위젯 에이전트로 고치기]. 에이전트가 고치는 위젯은 파란 테두리, 아직 없는 새 위젯의 자리는 점선
       a made widget's head: the name (ellipsis) and [Edit with the Widget Agent]; the widget being edited gets a blue ring, a widget not made yet a dashed spot */
    '.hd-cw > .wg-head .hd-nm{min-width:0;overflow:hidden;text-overflow:ellipsis;}',
    '.hd-cw > .wg-head .hd-wa{flex-shrink:0;margin-right:-6px;}',
    '.hd-cw.hd-wa-on{border-color:var(--primary);box-shadow:0 0 0 3px rgba(68,80,206,.16);}',
    '.hd-cw.hd-wa-on > .wg-head .hd-wa{background:var(--primary-soft);color:var(--primary);}',
    '.hd-cw.hd-ghost{border:1.5px dashed var(--primary);box-shadow:0 0 0 3px rgba(68,80,206,.10);}',
    '.hd-ghost .hd-new{flex-shrink:0;padding:1px 8px;border-radius:9999px;background:var(--primary-soft);font-size:11.5px;line-height:17px;font-weight:600;color:var(--primary);}',
    'body.hd-edit .hd-ghost{display:none !important;}',
    /* 패널이 열려 있는 동안(2026-11-21): 만든 위젯 카드는 누르면 대화 상대가 되는 것 — 손가락 커서 · 올리면 옅은 테두리(지금 고치는 위젯은 빼고)
       while the panel is open (2026-11-21) a made widget card is something to pick: a pointer cursor and a faint ring on hover (not on the one being edited) */
    'body.wa-open #dash > .hd-cw[data-wg]:not(.hd-wa-on){cursor:pointer;}',
    'body.wa-open #dash > .hd-cw[data-wg]:not(.hd-wa-on):hover{border-color:#B9C0F2;box-shadow:0 0 0 3px rgba(68,80,206,.08);}',
    '.hd-ebar{display:none;position:sticky;top:0;z-index:40;align-items:center;gap:8px 10px;flex-wrap:wrap;margin:0 0 14px;padding:10px 10px 10px 16px;background:#FAFCFF;border:1px solid var(--border);border-radius:14px;}',
    'body.hd-edit .hd-ebar{display:flex;}',
    '.hd-ebar:focus{outline:none;}',
    '.hd-ebar:focus-visible{outline:2px solid var(--primary);outline-offset:2px;}',
    '.hd-ebar .tx{display:flex;flex-direction:column;gap:1px;min-width:0;}',
    '.hd-ebar .tx b{font-size:15px;line-height:22px;font-weight:700;color:var(--ink);}',
    '.hd-ebar .tx span{font-size:12px;line-height:17px;color:var(--muted);}',
    '.hd-right{margin-left:auto;display:flex;flex-wrap:wrap;justify-content:flex-end;align-items:center;gap:8px 10px;}',
    '.hd-rgrp,.hd-acts{display:flex;align-items:center;gap:8px;}',
    '.hd-rl{font-size:12.5px;font-weight:600;color:var(--ink-3);white-space:nowrap;}',
    '.hd-rseg{display:inline-flex;gap:2px;padding:3px;border-radius:9999px;background:var(--table-head);}',
    '.hd-rseg button{height:28px;padding:0 12px;border-radius:9999px;font-size:12.5px;font-weight:600;color:var(--ink-3);white-space:nowrap;}',
    '.hd-rseg button.on{background:#fff;color:var(--primary);box-shadow:0 1px 2px rgba(0,0,0,.08);}',
    '.hd-ebtn,.hd-epri{flex-shrink:0;display:inline-flex;align-items:center;gap:6px;height:34px;padding:0 14px;border-radius:9999px;font-size:13px;font-weight:600;white-space:nowrap;}',
    '.hd-ebtn{background:var(--table-head);color:var(--ink-2);}',
    '.hd-ebtn:hover{background:var(--soft-3);}',
    '.hd-epri{padding:0 18px;background:var(--primary);color:#fff;}',
    '.hd-epri:hover{background:var(--primary-hover);}',
    '.hd-ebtn:disabled,.hd-epri:disabled{opacity:.5;cursor:not-allowed;}',
    '.hd-ebtn svg,.hd-epri svg{width:15px;height:15px;}',
    '.hd-ebtn .n{min-width:18px;height:18px;padding:0 5px;border-radius:9999px;background:#fff;font-size:11px;line-height:18px;color:var(--primary);text-align:center;}',
    '.hd-ebtn .n:empty{display:none;}',
    /* 서랍(안 쓰는 위젯): 이름 · 처음 크기 · [넣기] · 휴지통(만든 위젯만) + 미리보기, 카드를 끌어 홈에 넣는다 / the drawer of unused widgets */
    '.hd-addw{position:relative;}',
    '.hd-drawer{position:absolute;top:42px;right:0;z-index:50;width:min(360px,80vw);max-height:min(560px,70vh);overflow-y:auto;display:flex;flex-direction:column;gap:10px;padding:12px;background:#fff;border:1px solid var(--border-2);border-radius:14px;box-shadow:var(--shadow-pop);}',
    '.hd-drawer[hidden]{display:none;}',
    '.hd-dcard{display:flex;flex-direction:column;flex-shrink:0;border:1px solid var(--border);border-radius:12px;background:#fff;cursor:grab;touch-action:none;user-select:none;-webkit-user-select:none;}',
    '.hd-dcard:hover{border-color:var(--primary);}',
    '.hd-dhd{display:flex;align-items:center;gap:6px;min-height:38px;padding:0 6px 0 12px;font-size:13px;font-weight:600;color:var(--ink);}',
    '.hd-dhd .nm{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.hd-dhd .sz{font-size:11px;font-weight:600;color:var(--muted);font-variant-numeric:tabular-nums;}',
    '.hd-put{height:26px;padding:0 10px;border-radius:9999px;background:var(--primary-soft);font-size:12px;font-weight:600;color:var(--primary);}',
    '.hd-put:hover{background:var(--soft-2);}',
    '.hd-dnone{padding:18px 6px;text-align:center;font-size:12.5px;color:var(--muted);}',
    '.hd-ic{flex-shrink:0;display:flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:7px;color:#8A8C99;}',
    '.hd-ic svg{width:14px;height:14px;}',
    '.hd-ic:hover{background:#F3F3F8;color:#52545F;}',
    '.hd-ic.del:hover{background:#FDECEE;color:#E35B62;}',
    '.hd-pv{position:relative;height:150px;margin:0 10px 10px;border:1px solid var(--soft-3);border-radius:8px;background:#F6F8FD;overflow:hidden;pointer-events:none;}',
    '.hd-pv-in{width:142.86%;padding:8px;transform:scale(.7);transform-origin:0 0;}',
    '.hd-pv::after{content:"";position:absolute;left:0;right:0;bottom:0;height:28px;background:linear-gradient(rgba(246,248,253,0),#F6F8FD);}',
    /* 편집 중 위젯 = 덮개(점선 · 끌기 · 칸 수 · ✕ · 크기 손잡이). 안의 버튼은 눌리지 않는다 / while editing each widget wears a cover; its own buttons are inert */
    '#dash.hd-editing{min-width:880px;}',
    '#dash.hd-editing > .wg{overflow:hidden;}',
    '.hd-cover{position:absolute;inset:0;z-index:6;border:1.5px dashed #AEB6D2;border-radius:15px;background:rgba(68,80,206,.03);cursor:grab;touch-action:none;}',
    '.hd-cover:hover{border-color:var(--primary);background:rgba(68,80,206,.06);}',
    '.hd-cover .sz{position:absolute;left:10px;bottom:10px;padding:1px 8px;border-radius:9999px;background:#fff;border:1px solid var(--border);font-size:11px;line-height:17px;font-weight:600;color:var(--ink-3);font-variant-numeric:tabular-nums;}',
    '.hd-cover .rm{position:absolute;top:7px;right:8px;width:28px;height:28px;border-radius:8px;display:flex;align-items:center;justify-content:center;background:#fff;border:1px solid var(--border);color:#6B6D79;}',
    '.hd-cover .rm:hover{color:#E35B62;border-color:#F3B9BD;}',
    '.hd-cover .rm svg{width:14px;height:14px;}',
    '.hd-cover .rz{position:absolute;right:-1px;bottom:-1px;width:26px;height:26px;border-radius:7px 0 14px 0;background:#fff;border:1px solid var(--border);cursor:nwse-resize;display:flex;align-items:center;justify-content:center;}',
    '.hd-cover .rz i{width:8px;height:8px;border-right:2px solid #8A8C99;border-bottom:2px solid #8A8C99;}',
    '.hd-cover .rz:hover i{border-color:var(--primary);}',
    /* 점선 칸은 끄는 위젯 위에 그린다(손 밑에 가려 놓을 자리 · 안내가 안 보이지 않게) / the dashed cell sits above the dragged widget so the spot and notice stay visible */
    '.wg.hd-moving{z-index:30;opacity:.9;box-shadow:var(--shadow-pop);}',
    '.wg.hd-sizing{z-index:30;justify-self:start;align-self:start;box-shadow:var(--shadow-pop);}',
    '.hd-cell{z-index:35;pointer-events:none;border:2px dashed var(--primary);border-radius:16px;background:rgba(68,80,206,.06);display:flex;align-items:flex-end;justify-content:flex-end;padding:10px;}',
    '.hd-cell span{padding:2px 10px;border-radius:9999px;background:var(--primary);font-size:12px;line-height:18px;font-weight:600;color:#fff;white-space:nowrap;}',
    '.hd-float{position:fixed;left:0;top:0;z-index:300;display:flex;align-items:center;gap:8px;height:34px;padding:0 12px;background:#F6F8FD;border:1px solid var(--border);border-radius:10px;box-shadow:var(--shadow-pop);font-size:13px;font-weight:600;color:var(--ink);white-space:nowrap;pointer-events:none;}',
    'body.hd-dragging,body.hd-dragging *{cursor:grabbing !important;user-select:none !important;}',
    'body.hd-dragging.hd-sizing-now,body.hd-dragging.hd-sizing-now *{cursor:nwse-resize !important;}',
    '.hd-ov{position:fixed;inset:0;z-index:250;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.3);}',
    '.hd-dlg{width:320px;max-width:calc(100vw - 32px);padding:20px;background:#fff;border-radius:12px;box-shadow:var(--shadow-pop);}',
    '.hd-dlg-tt{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;font-size:14px;line-height:22px;font-weight:700;color:var(--ink);}',
    '.hd-dlg-bd{margin-bottom:4px;font-size:12.5px;line-height:18px;color:#52545F;overflow-wrap:anywhere;}',
    '.hd-dlg-bd b{margin-right:4px;font-weight:600;color:var(--ink);}',
    '.hd-dlg-warn{font-size:11px;line-height:16px;color:#E35B62;}',
    '.hd-dlg-act{display:flex;justify-content:flex-end;gap:8px;margin-top:16px;}',
    '.hd-dlg-btn{height:34px;padding:0 16px;border-radius:8px;background:var(--primary);font-size:12.5px;font-weight:600;color:#fff;}',
    '.hd-dlg-btn.danger{background:#E35B62;}',
    '.hd-dlg-btn:disabled{opacity:.5;cursor:not-allowed;}',
  ].join('\n');

  const S = { owner: '', widgets: [], byKey: {}, sizes: {}, state: null, draft: null, busy: false, seq: 0, dlg: null, pending: null, opening: false, mode: 0 };
  const E = { on: false };
  // 위젯 에이전트 패널과 함께 쓰는 상태(2026-11-20): 그 자리에 그리는 위젯 · 새 위젯의 자리 · 강조하는 위젯 / state shared with the widget agent panel
  const A = { pv: '', ghost: null, focus: '' };
  const builtinEl = {}, madeEl = {};
  let bar = null, drawer = null, drag = null, cell = null, floatEl = null;

  function owner() {
    try { const a = window.parent && window.parent.AI365_ACTING_USER; return a && a.no != null ? String(a.no) : ''; } catch (e) { return ''; }
  }
  // 영어일 때 방금 그린 한국어 문구를 바로 바꾼다(home-live.js 가 내놓은 함수 — 안 부르면 약 0.1초 한국어가 보였다가 바뀐다)
  // in English, swap the Korean labels just drawn at once (a function home-live.js exposes; without the call Korean shows for about 0.1 s first)
  function tr() {
    try { if (typeof window.AI365_homeLang === 'function') window.AI365_homeLang(); } catch (e) {}
  }
  function toast(msg) {
    const t = document.getElementById('toast');
    if (!t) return;
    t.textContent = msg; t.classList.add('show');
    clearTimeout(t._tm); t._tm = setTimeout(() => t.classList.remove('show'), 2600);
    tr();
  }
  // 실패는 Error 로: 서버가 준 문장(detail)이 있으면 그 문장, 없거나 네트워크 실패면 빈 메시지(부르는 쪽이 우리 문장을 쓴다). status 도 싣는다
  // failures become Errors: the server's sentence (detail) when there is one, otherwise an empty message (the caller supplies ours); the status rides along
  function api(method, path, body) {
    const init = { method: method, headers: {} };
    if (body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
    return fetch(path, init).then(r => r.json().catch(() => null).then(d => {
      if (!r.ok) { const err = new Error(d && typeof d.detail === 'string' ? d.detail : ''); err.status = r.status; throw err; }
      return d;
    }), () => { throw new Error(''); });
  }
  function setWidgets(list) {
    S.widgets = (Array.isArray(list) ? list : []).filter(w => w && typeof w.key === 'string');
    S.byKey = {};
    S.widgets.forEach(w => { S.byKey[w.key] = w; });
  }
  function keys() { return S.widgets.map(w => w.key); }
  function nameOf(key) { const w = S.byKey[key]; return w && w.name ? String(w.name) : key; }
  function isCustom(key) { const w = S.byKey[key]; return !!(w && w.kind === 'custom'); }
  function isLocked(key) { const w = S.byKey[key]; return !!(w && w.locked); }

  /* ── 차트 = 리포트 에이전트의 그리기(report_dash.js 의 rdChartConfig) + Chart.js(처음 필요할 때 한 번 불러온다)
     charts = the report agent's drawing (rdChartConfig of report_dash.js) plus Chart.js (loaded once, when first needed) ── */
  let chartWait = null;
  function chartKit() {
    const rd = window.AI365_reportDash;
    if (!rd || typeof rd.chartConfig !== 'function') return Promise.resolve(false);
    if (typeof window.Chart === 'function') return Promise.resolve(true);
    if (!chartWait) {
      chartWait = new Promise(resolve => {
        const s = document.createElement('script');
        s.src = '/static/vendor/chart.umd.min.js';
        s.onload = () => resolve(typeof window.Chart === 'function');
        s.onerror = () => { chartWait = null; resolve(false); };   // 다음에 다시 시도 / try again next time
        document.head.appendChild(s);
      });
    }
    return chartWait;
  }
  function isEn() { try { return typeof window.AI365_homeLangIs === 'function' && window.AI365_homeLangIs() === 'en'; } catch (e) { return false; } }
  // 모델을 본문에 그리고(차트 자리는 캔버스) 그 모델을 요소에 붙여 둔다 / draw a model into a body (canvas for the chart) and keep the model on the element
  function paintModel(host, m) {
    host.innerHTML = hdWidgetHtml(m);
    const w = host.querySelector('[data-hw]');
    if (w) w._hwModel = m;
  }
  // root 안의 차트 캔버스를 그린다. 문서에 붙은 캔버스만(그 사이 지워진 것은 건너뛴다), 불러오기에 실패하면 안내 문구
  // draw the chart canvases inside root: connected ones only (removed ones are skipped); a failed load shows a notice
  function mountIn(root, opts) {
    const list = root ? [].slice.call(root.querySelectorAll('canvas[data-hw-canvas]')) : [];
    if (!list.length) return Promise.resolve(0);
    return chartKit().then(ok => {
      let n = 0;
      list.forEach(cv => {
        const host = cv.closest('[data-hw]'), m = host && host._hwModel;
        if (!cv.isConnected || !m || !m.chart) return;
        if (cv._hw) { try { cv._hw.destroy(); } catch (e) {} cv._hw = null; }
        if (!ok) { cv.parentNode.innerHTML = '<div class="hd-none">' + CHART_FAIL + '</div>'; tr(); return; }
        cv._hw = new window.Chart(cv, hdChartConfig(m, window.AI365_reportDash.chartConfig, { still: !!(opts && opts.still), en: isEn() }));
        n++;
      });
      return n;
    });
  }
  function unmountIn(root) {
    if (!root) return;
    root.querySelectorAll('canvas[data-hw-canvas]').forEach(cv => { if (cv._hw) { try { cv._hw.destroy(); } catch (e) {} cv._hw = null; } });
  }

  // 만든 위젯 = 기본 위젯과 같은 틀(.wg + .wg-head)에 서버가 준 모델을 그린다(차트는 문서에 붙인 뒤 mountIn) / a made widget: the built-in frame around the server's model (charts mount once attached)
  function customEl(w) {
    const el = document.createElement('div');
    el.className = 'wg hd-cw';
    el.dataset.wg = w.key;
    // 이름과 본문의 데이터는 사용자의 것이라 번역 사전이 건드리지 않는다(data-i18n-skip) / the name and the body's data are the user's, so the dictionary leaves them alone
    // 머리 오른쪽 = [위젯 에이전트로 고치기](2026-11-20): 누르면 오른쪽 패널에 이 위젯과 그 대화가 열린다 / the head's right: opens this widget and its conversation in the panel
    el.innerHTML = '<div class="wg-head"><span class="hd-nm" data-i18n-skip>' + hdEsc(w.name || '') + '</span><span class="sp"></span>' +
      '<button type="button" class="hd-btn hd-wa" data-hd-wa="' + hdEsc(w.key) + '" title="' + TX.agentEdit + '">' + SVG_SPARK + '</button></div><div class="hd-body"></div>';
    paintModel(el.querySelector('.hd-body'), w.model);
    return el;
  }

  function useWidgets(list) { setWidgets(list); S.sizes = hdSizes(S.widgets); }
  function sizeOf(key) { return S.sizes[key] || DEF_SIZE; }
  // 지금 그릴 열 수: 격자 너비 900 이상 = 3열(기본 비율), 600 이상 = 2열, 그 밑 = 1열. 편집 중에는 늘 3열 / columns to draw now (always three while editing)
  function gridMode() { const w = dash.clientWidth; return w >= 900 ? 3 : (w >= 600 ? 2 : 1); }

  // 위젯 요소: 기본 위젯은 홈 파일의 마크업(이벤트 유지), 만든 위젯은 모델로 그린 것(모델 · 이름이 바뀌면 다시 그린다)
  // a widget's element: built-ins keep the home file's markup; made widgets are drawn from their model (redrawn when it changes)
  function elOf(key) {
    if (builtinEl[key]) return builtinEl[key];
    const w = S.byKey[key];
    if (!w || w.kind !== 'custom') return null;
    let el = madeEl[key];
    if (el && (el._model !== w.model || el._name !== w.name)) { unmountIn(el); el.remove(); el = null; }
    if (!el) {
      el = customEl(w);
      el._model = w.model; el._name = w.name; el._mount = true;
      madeEl[key] = el;
    }
    return el;
  }
  function clearPos(el) { el.style.gridColumn = ''; el.style.gridRow = ''; }
  // 배치 적용: 위젯마다 격자 자리(grid-column · grid-row)를 주고 화면 차례도 맞춘다. 놓이지 않은 기본 위젯은 보관 칸으로, 만든 위젯은 지운다
  // apply a layout: each widget gets its grid area and the DOM follows the grid order; unplaced built-ins go to the pool, made ones are removed
  function apply(st) {
    if (!dash.classList.contains('hd-grid')) {   // 처음 한 번: 세 열 칸을 걷어 내고 격자로 / once: drop the column wrappers for the grid
      dash.classList.add('hd-grid');
      Object.keys(builtinEl).forEach(k => pool.appendChild(builtinEl[k]));
      dash.querySelectorAll(':scope > .col').forEach(c => c.remove());
    }
    const mode = E.on ? 3 : gridMode();
    S.mode = mode;
    // 열은 minmax(0, Nfr): 넓은 내용이 열을 밀어 넓히지 못하게(넓으면 위젯 안에서 스크롤) — 끌기 계산(hdTracks)과 같은 너비가 된다
    // columns are minmax(0, Nfr) so wide content never widens a column (it scrolls inside) and widths match the drag maths (hdTracks)
    const fr = mode === 3 ? hdRatios(st.layout) : (mode === 2 ? [1, 1] : [1]);
    dash.style.setProperty('--hd-cols', fr.map(r => 'minmax(0,' + r + 'fr)').join(' '));
    // 화면 차례 = 격자 차례(읽기 · 초점 차례). 이미 제자리인 위젯은 옮기지 않는다(옮기면 안의 초점 · 스크롤이 풀린다)
    // DOM order = grid order (reading and focus order); widgets already in place are not moved (moving drops focus and scroll inside)
    const placed = {};
    let prev = null;
    (mode === 3 ? st.items : hdFlow(st.items, mode)).forEach(p => {
      const el = elOf(p.key);
      if (!el) return;
      el.style.gridColumn = (p.x + 1) + ' / span ' + p.w;
      el.style.gridRow = (p.y + 1) + ' / span ' + p.h;
      const want = prev ? prev.nextElementSibling : dash.firstElementChild;
      if (el !== want) dash.insertBefore(el, want);
      prev = el;
      placed[p.key] = 1;
    });
    Object.keys(builtinEl).forEach(k => {
      if (placed[k]) return;
      clearPos(builtinEl[k]);
      if (builtinEl[k].parentNode !== pool) pool.appendChild(builtinEl[k]);
    });
    Object.keys(madeEl).forEach(k => { if (!placed[k]) { unmountIn(madeEl[k]); madeEl[k].remove(); delete madeEl[k]; } });
    Object.keys(madeEl).forEach(k => { const el = madeEl[k]; if (el._mount) { el._mount = false; mountIn(el); } });
    placeGhost(); markFocus();
    if (E.on) paintCovers(st);
    else refreshPlaced(st);
    // 위젯 에이전트 패널이 듣는다(그 자리 그리기 · 크기 칸을 다시 맞춘다) / the widget agent panel listens (to re-apply its in-place drawing and size cells)
    try { document.dispatchEvent(new CustomEvent('ai365-home-dash')); } catch (e) { /* 옛 브라우저 / an old browser */ }
  }

  // 놓인 만든 위젯 중 가져온 내용이 있는 것(웹 · 사내 문서 · 사내 데이터, model.refresh)은 서버에 새 내용을 부탁한다. 때가 됐는지는 서버가 정하고
  // (웹 30분 · 문서 6시간 · 데이터 1분), 이 화면은 같은 위젯을 1분에 한 번까지만 묻는다. 모델이 바뀌었을 때만 그 위젯을 다시 그린다
  // placed made widgets with fetched content (model.refresh) ask the server for fresh content; the server decides when it is due
  // (web 30 min, documents 6 h, data 1 min) and this page asks at most once a minute per widget. A widget is redrawn only when its model changed
  const asked = {};
  function refreshPlaced(st) {
    const me = S.owner, now = Date.now();
    st.items.forEach(item => {
      const k = item.key, w = S.byKey[k];
      if (!w || w.kind !== 'custom' || !w.model || !w.model.refresh || (asked[k] && now - asked[k] < 60000)) return;
      asked[k] = now;
      api('GET', '/api/home/widgets/' + encodeURIComponent(k) + '/data?acting_user_id=' + encodeURIComponent(me)).then(d => {
        const cur = S.byKey[k];
        if (!d || !d.model || !cur || S.owner !== me || JSON.stringify(d.model) === JSON.stringify(cur.model)) return;
        cur.model = d.model;
        const el = madeEl[k];
        if (el && el._pv) el._model = d.model;   // 위젯 에이전트의 작업본을 그리는 중: 모델만 바꿔 둔다 / the agent's draft is on show: keep the model only
        else if (el) {
          const body = el.querySelector('.hd-body');
          unmountIn(body); paintModel(body, d.model); el._model = d.model; mountIn(body); tr();
        }
        cacheSave();
      }).catch(() => {});
    });
  }

  // 마지막 배치를 브라우저에 적어 두고 다음에 열 때 먼저 그린다(서버 응답을 기다리는 동안 기본 배치가 번쩍이지 않게). 그릴 것만 적고(이름 · 모델 · 크기 · 정의 시각),
  // 못 적으면(용량 초과) 옛 캐시를 지운다 / remember the last layout and draw it first next time; only what is drawn is stored, and a failed write removes the cache
  function cacheSave() {
    const slim = S.widgets.map(w => (w.kind === 'custom' ? { key: w.key, kind: 'custom', name: w.name, model: w.model, size: w.size, updated_at: w.updated_at }
      : { key: w.key, kind: 'builtin', name: w.name, locked: !!w.locked, size: w.size }));
    try { localStorage.setItem(LS_CACHE, JSON.stringify({ owner: S.owner, config: hdConfig(S.state), widgets: slim })); }
    catch (e) { try { localStorage.removeItem(LS_CACHE); } catch (e2) {} }
  }
  function cacheLoad() {
    try {
      const c = JSON.parse(localStorage.getItem(LS_CACHE));
      if (!c || c.owner !== owner() || !Array.isArray(c.widgets) || !c.config) return false;
      useWidgets(c.widgets);
      S.owner = c.owner; S.state = hdState(c.config, S.widgets);
      apply(S.state);
      return true;
    } catch (e) { return false; }
  }
  // 옛 브라우저 저장본은 서버에 저장본이 없을 때 한 번 옮긴다(옛 세 열 모양으로 보내면 서버가 격자로 바꾼다). 읽을 수 없는 저장본은 치우고,
  // 서버가 받지 못하면 남겨 두었다가 다음에 다시 옮긴다. 신원 구분이 없던 저장본이라 기본 사용자에게만 옮긴다
  // the old browser layout moves once, when the server has nothing saved (sent in the old column shape, the server makes it a grid); an
  // unreadable one is discarded and one the server could not take stays for the next try; it moves to the default user only
  function migrateLegacy(base) {
    if (S.owner !== '' || E.on || S.migrating) return;   // 편집 중에는 옮기지 않는다(다음 읽기 때 다시) / not while editing (retried on the next read)
    let raw = null, saved = null;
    try { raw = localStorage.getItem(LS_OLD); saved = JSON.parse(raw); } catch (e) {}
    if (raw === null) return;
    const old = hdLegacy(saved, S.widgets.map(w => w.key), hdColumnsOf(base));
    if (!old || old.cols.some(c => !c.length)) { try { localStorage.removeItem(LS_OLD); } catch (e) {} return; }
    const seq = S.seq;
    // 옮기는 동안 [배치 편집]은 기다린다 — 기본 배치로 편집을 시작해 옮긴 배치를 덮어쓰지 않게(4단계 검토). 그 사이 다시 읽었으면 옮긴 배치를 다시 읽는다
    // layout editing waits while it moves, so editing never starts from the default and overwrites the moved layout (phase-4 review); a read made
    // meanwhile is followed by another one that sees the moved layout
    S.migrating = api('PUT', '/api/home/dashboard', { acting_user_id: S.owner, layout_type: old.layout,
      columns: old.cols.map((list, i) => ({ column_index: i, widgets: list.map((k, j) => ({ widget_key: k, sort_order: j })) })) }).then(d => {
      try { localStorage.removeItem(LS_OLD); } catch (e) {}
      if (!d || !Array.isArray(d.items)) return;
      if (seq !== S.seq) { if (S.owner === '') load(); return; }
      S.state = hdState(d, S.widgets);
      apply(S.state); cacheSave();
    }).catch(() => {}).then(() => { S.migrating = null; });
  }
  // 편집 중에 위젯 목록이 바뀌면(위젯 에이전트가 저장 · 다른 창에서 삭제) 편집본도 맞춘다 / keep the draft in step with a changed widget list
  function syncDraft(dr) {
    const known = {};
    S.widgets.forEach(w => { known[w.key] = 1; });
    const next = hdClone(dr);
    next.items = hdSettle(next.items.filter(i => known[i.key]));
    next.unused = next.unused.filter(k => known[k]);
    S.widgets.forEach(w => { if (!next.items.some(i => i.key === w.key) && next.unused.indexOf(w.key) < 0) next.unused.push(w.key); });
    return next;
  }
  function load() {
    const me = owner(), seq = ++S.seq;
    const run = api('GET', '/api/home/dashboard?acting_user_id=' + encodeURIComponent(me)).then(d => {
      // 그 사이 더 새 읽기 · 저장 · 삭제가 있었으면 이 답은 버린다. 모양이 틀린 답(위젯 목록이 없다)도 버린다 — 적용하면 기본 위젯이 전부 숨는다
      // an answer overtaken by a newer read, save or delete is dropped; so is a mis-shaped one (no widget list), which would hide every built-in
      if (seq !== S.seq || !d || !d.config || !Array.isArray(d.widgets) || !d.widgets.length) return;
      // 새로 가져온 모델(/data)이 이 답보다 먼저 왔으면 더 늦게 가져온 쪽을 쓴다(늦게 온 배치 답이 새 숫자를 되돌리지 않게, 3단계 검토)
      // when a refreshed model (/data) arrived before this answer, the later-fetched one wins (a late layout answer never rolls numbers back)
      // 단 같은 정의(updated_at)일 때만 — 위젯 에이전트가 정의를 바꿨으면 새 모델을 쓴다. 내용이 같은 모델은 예전 객체를 그대로 써서 위젯을 다시
      // 그리지 않는다(끄는 중인 위젯이 손에서 떨어지지 않고, 다시 읽을 때마다 차트를 새로 그리지 않게) — 4단계 검토
      // only for the same definition (updated_at): a definition changed by the widget agent brings its new model. An equal model keeps the old
      // object so the widget is not rebuilt (a widget being dragged stays in hand and charts are not redrawn on every read) — phase-4 review
      const prev = me === S.owner ? S.byKey : {};
      d.widgets.forEach(w => {
        const p = w && w.kind === 'custom' && prev[w.key];
        if (!p || !p.model) return;
        if (p.updated_at === w.updated_at && hdFetchedAt(p.model) > hdFetchedAt(w.model)) w.model = p.model;
        else if (JSON.stringify(p.model) === JSON.stringify(w.model)) w.model = p.model;
      });
      if (E.on && me !== S.owner) closeEdit();
      S.owner = me;
      useWidgets(d.widgets);
      S.state = hdState(d.config, S.widgets);
      if (E.on) { S.draft = syncDraft(S.draft); apply(S.draft); paintBar(); }
      else apply(S.state);
      cacheSave();
      if (d.config.saved === false) migrateLegacy(S.state);
    }).catch(() => {}).then(() => { if (S.pending === run) S.pending = null; });
    S.pending = run;
    return run;
  }

  // 미리보기 = 실제 위젯을 작게, 눌리지 않게. 기본 위젯은 지금 화면의 것을 베끼고(id 는 뗀다), 만든 위젯은 저장된 모델로 그린다(데이터를 다시 가져오지 않는다,
  // 차트는 서랍이 움직임 없이 그린다)
  // preview = the real widget, small and inert: a built-in is cloned from the live one (ids stripped) and a made widget is drawn from its stored model (no refetch;
  // the drawer draws its chart without animation)
  function previewEl(key) {
    let el = null;
    if (builtinEl[key]) {
      el = builtinEl[key].cloneNode(true);
      el.removeAttribute('id');
      el.querySelectorAll('[id]').forEach(n => n.removeAttribute('id'));
      el.querySelectorAll('[for]').forEach(n => n.removeAttribute('for'));
    } else if (isCustom(key)) {
      el = customEl(S.byKey[key]);
    }
    if (!el) return null;
    el.removeAttribute('data-wg');
    el.querySelectorAll('.hd-cover').forEach(c => c.remove());   // 편집 중에 서랍으로 뺀 기본 위젯은 덮개를 달고 있다 / a built-in removed while editing still wears its cover
    el.setAttribute('inert', ''); el.setAttribute('aria-hidden', 'true');
    const box = document.createElement('div');
    box.className = 'hd-pv-in';
    box.appendChild(el);
    return box;
  }

  /* ── 배치 편집 / layout editing ── */
  function buildBar() {
    bar = document.createElement('div');
    bar.className = 'hd-ebar'; bar.id = 'hdEbar';
    // 막대 = 이름 붙은 영역, 편집을 열면 키보드 초점이 여기로 온다(톱니는 숨는다) / the bar is a named region that takes keyboard focus on open (the gear hides)
    bar.setAttribute('role', 'region'); bar.setAttribute('aria-labelledby', 'hdEbarTt'); bar.tabIndex = -1;
    // 오른쪽 묶음(기본 비율 · 단추들)은 좁으면 통째로 다음 줄로 내려가도 오른쪽에 붙는다 / the right group wraps as a whole and stays right-aligned
    bar.innerHTML = '<div class="tx"><b id="hdEbarTt">' + TX.edit + '</b><span>' + TX.hint + '</span></div><div class="hd-right">' +
      '<span class="hd-rgrp"><span class="hd-rl" id="hdRl">' + TX.ratio + '</span><span class="hd-rseg" role="radiogroup" aria-labelledby="hdRl">' +
      LAYOUTS.map(o => '<button type="button" role="radio" data-hd-lay="' + o.value + '">' + o.label + '</button>').join('') + '</span></span>' +
      '<span class="hd-acts"><span class="hd-addw"><button type="button" class="hd-ebtn" data-hd-act="add" aria-haspopup="true" aria-expanded="false">' + ICON.plus +
      '<span>' + TX.add + '</span><span class="n" data-i18n-skip></span></button><div class="hd-drawer" id="hdDrawer" hidden></div></span>' +
      '<button type="button" class="hd-ebtn" data-hd-act="cancel">' + ICON.x + '<span>' + TX.cancel + '</span></button>' +
      '<button type="button" class="hd-epri" data-hd-act="save">' + ICON.save + '<span>' + TX.save + '</span></button></span></div>';
    dash.parentNode.insertBefore(bar, dash);
    drawer = bar.querySelector('#hdDrawer');
    bar.addEventListener('click', onBarClick);
    drawer.addEventListener('pointerdown', onDrawerDown);
  }
  function paintBar() {
    if (!bar || !S.draft) return;
    bar.querySelectorAll('[data-hd-lay]').forEach(b => {
      const on = b.dataset.hdLay === S.draft.layout;
      b.classList.toggle('on', on); b.setAttribute('aria-checked', String(on));
    });
    bar.querySelector('[data-hd-act="add"] .n').textContent = S.draft.unused.length ? String(S.draft.unused.length) : '';
    bar.querySelectorAll('button').forEach(b => { b.disabled = S.busy; });
    if (!drawer.hidden) paintDrawer();
  }
  // 서랍 = 안 쓰는 위젯(위젯 목록 차례): 이름 · 처음 크기 · [넣기] · 휴지통(만든 위젯만) + 미리보기 / the drawer of unused widgets, in widget-list order
  function paintDrawer() {
    const had = drawer.contains(document.activeElement);   // 서랍 안에 있던 키보드 초점은 다시 그린 뒤에도 서랍 안에 / focus inside the drawer stays inside across a redraw
    unmountIn(drawer);
    const rest = S.widgets.map(w => w.key).filter(k => S.draft.unused.indexOf(k) >= 0);
    drawer.innerHTML = rest.length ? rest.map(k => {
      const s = sizeOf(k), del = isCustom(k)
        ? '<button type="button" class="hd-ic del" data-hd-del="' + hdEsc(k) + '" title="' + TX.del + '">' + ICON.trash + '</button>' : '';
      return '<div class="hd-dcard" data-hd-add="' + hdEsc(k) + '"><div class="hd-dhd"><span class="nm"' + (isCustom(k) ? ' data-i18n-skip' : '') + '>' + hdEsc(nameOf(k)) +
        '</span><span class="sz" data-i18n-skip>' + s.w + '×' + s.h + '</span><button type="button" class="hd-put" data-hd-put="' + hdEsc(k) + '">' + TX.put + '</button>' + del +
        '</div><div class="hd-pv" data-hd-pv="' + hdEsc(k) + '"></div></div>';
    }).join('') : '<div class="hd-dnone">' + TX.allPlaced + '</div>';
    drawer.querySelectorAll('[data-hd-pv]').forEach(box => { const pv = previewEl(box.dataset.hdPv); if (pv) box.appendChild(pv); });
    mountIn(drawer, { still: true });
    tr();
    if (had) { const f = drawer.querySelector('.hd-put') || bar.querySelector('[data-hd-act="add"]'); if (f) f.focus({ preventScroll: true }); }
  }
  function toggleDrawer(open) {
    if (!drawer) return;
    const on = open == null ? drawer.hidden : open;
    bar.querySelector('[data-hd-act="add"]').setAttribute('aria-expanded', String(!!on));
    if (!on) { unmountIn(drawer); drawer.hidden = true; return; }
    drawer.hidden = false;
    paintDrawer();
  }
  // 덮개: 점선 · 칸 수 · ✕(잠근 위젯은 없다) · 크기 손잡이. 편집하는 동안 위젯 내용은 눌리지도 초점이 가지도 않는다(inert), 덮개가 맞게 덮이도록 스크롤은 맨 위로
  // covers: dashed frame, cell count, ✕ (none on a locked widget), resize handle; while editing the widget's content is inert and scrolled to the top so the cover fits
  function paintCovers(st) {
    const items = {};
    st.items.forEach(i => { items[i.key] = i; });
    dash.querySelectorAll(':scope > .wg').forEach(el => {
      const it = items[el.dataset.wg];
      let cv = el.querySelector(':scope > .hd-cover');
      if (!it) { if (cv) cv.remove(); return; }
      if (!cv) {
        [].forEach.call(el.children, c => { if (!c.hasAttribute('inert')) { c.setAttribute('inert', ''); c.setAttribute('data-hd-inert', ''); } });
        el.scrollTop = 0;
        cv = document.createElement('div');
        cv.className = 'hd-cover'; cv.dataset.hdKey = it.key;
        // 덮개 = 위젯 이름이 붙은 묶음: 보조 기술이 위젯마다의 ✕ 를 구별한다(내용은 inert 라 머리가 읽히지 않는다, 4단계 검토)
        // the cover is a group named after the widget, so assistive tech tells each ✕ apart (the inert content hides the head; phase-4 review)
        cv.setAttribute('role', 'group'); cv.setAttribute('aria-label', headName(el, it.key));
        cv.innerHTML = '<span class="sz" data-i18n-skip></span>' + (isLocked(it.key) ? '' : '<button type="button" class="rm" data-hd-rm="' + hdEsc(it.key) + '" title="' +
          TX.remove + '">' + ICON.x + '</button>') + '<span class="rz" title="' + TX.resize + '"><i></i></span>';
        el.appendChild(cv);
      }
      cv.querySelector('.sz').textContent = it.w + '×' + it.h;
    });
  }
  // 위젯 머리의 이름 = 지금 언어로 보이는 머리의 첫 글자 마디(없으면 위젯 이름) / the head's first text node as shown now (else the widget name)
  function headName(el, key) {
    const head = el.querySelector(':scope > .wg-head');
    const t = head && [].filter.call(head.childNodes, n => n.nodeType === 3 && n.nodeValue.trim())[0];
    return t ? t.nodeValue.trim() : nameOf(key);
  }
  function clearCovers() {
    document.querySelectorAll('.hd-cover').forEach(c => c.remove());
    document.querySelectorAll('[data-hd-inert]').forEach(n => { n.removeAttribute('inert'); n.removeAttribute('data-hd-inert'); });
  }
  // 편집하는 동안 부모 앱의 우상단 고정 묶음(언어 · 계정)을 숨긴다(adapter.js 가 듣는다) — 편집 막대가 위에 붙었을 때 [저장]을 가리지 않게
  // while editing the parent app hides its fixed top-right bundle (adapter.js listens), so it never covers [Save] when the edit bar sticks to the top
  function chrome(hide) {
    try { if (window.parent && window.parent !== window) window.parent.postMessage({ type: 'ai365-home-chrome', hide: !!hide }, location.origin); } catch (e) {}
  }
  function openEdit() {
    if (S.opening) return;
    // 아직 배치를 못 읽었거나 · 그 사이 신원이 바뀌었거나 · 옛 저장본을 옮기는 중이면: 그 일이 다 끝난 뒤(도중에 시작된 읽기까지) 열고, 끝내 못 읽으면 알린다
    // no layout yet, a changed identity or an old layout still moving: open once that settles (reads started in between included), or say so when nothing arrives
    if (!S.state || owner() !== S.owner || S.migrating) {
      S.opening = true;
      const fresh = !S.state || owner() !== S.owner;
      const settle = () => (S.migrating || S.pending || (fresh ? load() : Promise.resolve())).then(() => (S.migrating || S.pending ? settle() : null));
      settle().then(() => { S.opening = false; if (S.state && owner() === S.owner && !S.migrating) openEdit(); else toast(TX.loadFail); });
      return;
    }
    if (E.on) return;
    // 한 번에 하나: 위젯 에이전트 패널이 열려 있으면 닫고(홈 너비가 돌아온다) 편집을 연다 / one at a time: an open agent panel closes first (the home regains its width)
    try { const a = window.AI365_widgetAgent; if (a && a.close) a.close(); } catch (e) { /* 패널 없음 / no panel */ }
    if (gridMode() < 3) { toast(TX.narrow); return; }
    if (!bar) buildBar();
    S.draft = hdClone(S.state);
    E.on = true;
    document.body.classList.add('hd-edit');
    dash.classList.add('hd-editing');
    apply(S.draft); paintBar();
    chrome(true);
    tr();
    bar.focus({ preventScroll: true });   // 키보드 초점은 편집 막대로(톱니는 숨는다) / keyboard focus moves to the edit bar (the gear hides)
  }
  function closeEdit() {
    const a = document.activeElement;
    const inside = !!(a && (a === document.body || (bar && bar.contains(a)) || dash.contains(a) || (a.closest && a.closest('#hdOv'))));
    const was = E.on;
    endDrag(false); toggleDrawer(false); closeDialog();
    if (E.on) chrome(false);
    E.on = false; S.draft = null;
    document.body.classList.remove('hd-edit');
    dash.classList.remove('hd-editing');
    clearCovers();
    if (S.state) apply(S.state);
    // 초점이 편집 화면 안에 있었으면 다시 보이는 톱니로 — 이 문서가 초점을 가진 때만(부모 앱의 초점을 빼앗지 않게)
    // focus returns to the gear when it was inside the editor, only while this document has focus (never stealing the parent app's)
    if (was && inside && gear && document.hasFocus()) gear.focus({ preventScroll: true });
  }
  function askCancel() {
    if (!S.draft || hdSame(S.draft, S.state)) { closeEdit(); return; }
    dialog({ title: TX.cancel, body: '<span>' + TX.cancelAsk + '</span>', warn: TX.cancelWarn, btn: TX.cancel, danger: true, ok: closeEdit });
  }
  // 편집본 바꾸기: 위젯들이 새 자리로 미끄러지듯 옮겨 간다(움직임 줄이기 설정이면 바로) / change the draft; widgets slide to their new places
  function change(fn, before) {
    const from = before || rects(), next = fn();
    if (next && next !== S.draft) { S.draft = next; apply(S.draft); paintBar(); }
    flip(from);
  }
  function rects() {
    const m = {};
    dash.querySelectorAll(':scope > .wg').forEach(el => { m[el.dataset.wg] = el.getBoundingClientRect(); });
    return m;
  }
  function reduced() { try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; } }
  function flip(before) {
    if (reduced()) return;
    dash.querySelectorAll(':scope > .wg').forEach(el => {
      const a = before[el.dataset.wg];
      if (!a) return;
      const b = el.getBoundingClientRect(), dx = a.left - b.left, dy = a.top - b.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
      el.style.transition = 'none';
      el.style.transform = 'translate(' + dx + 'px,' + dy + 'px)';
      el.getBoundingClientRect();
      el.style.transition = 'transform .18s ease-out';
      el.style.transform = '';
      clearTimeout(el._flipT);
      el._flipT = setTimeout(() => { el.style.transition = ''; }, 240);
    });
  }
  function onBarClick(e) {
    if (!E.on || S.busy) return;
    const lay = e.target.closest('[data-hd-lay]'), act = e.target.closest('[data-hd-act]'), put = e.target.closest('[data-hd-put]'), del = e.target.closest('[data-hd-del]');
    if (lay) { change(() => Object.assign(hdClone(S.draft), { layout: lay.dataset.hdLay })); return; }
    if (put) { change(() => hdAdd(S.draft, put.dataset.hdPut, sizeOf(put.dataset.hdPut))); return; }
    if (del) { askDelete(del.dataset.hdDel); return; }
    if (!act) return;
    if (act.dataset.hdAct === 'add') toggleDrawer();
    else if (act.dataset.hdAct === 'cancel') askCancel();
    else if (act.dataset.hdAct === 'save') dialog({ title: TX.save, body: '<span>' + TX.saveAsk + '</span>', btn: TX.save, ok: doSave });
  }
  // 편집하는 사이 신원이 바뀌었으면(뷰애즈 전환) 저장 · 삭제를 보내지 않는다: 이전 사람의 배치와 위젯에 적용되기 때문이다. 편집을 닫고 새로 읽는다
  // when the identity changed while editing nothing is saved or deleted (it would land on the previous person's layout); editing closes and the layout is read again
  function identityMoved() {
    if (owner() === S.owner) return false;
    closeEdit(); load(); toast(TX.moved);
    return true;
  }
  function doSave() {
    if (S.busy || !S.draft || identityMoved()) return;
    setBusy(true);
    const who = S.owner;
    api('PUT', '/api/home/dashboard', Object.assign({ acting_user_id: who }, hdConfig(S.draft))).then(d => {
      // 답이 오기 전에 다른 사람의 배치를 읽었으면 이 답(이전 사람의 배치)은 화면 · 캐시에 쓰지 않는다(4단계 검토)
      // when another person's layout was read before this answer, the answer (the previous person's layout) touches neither screen nor cache (phase-4 review)
      if (S.owner !== who) { setBusy(false); closeDialog(); return; }
      S.seq++;   // 저장보다 먼저 떠난 읽기의 답이 늦게 와도 이 배치를 덮지 못한다 / a read that left before this save can no longer overwrite it
      S.state = hdState(d && Array.isArray(d.items) ? d : hdConfig(S.draft), S.widgets);
      setBusy(false); closeEdit(); cacheSave();
      toast(TX.saved);
      if (owner() !== S.owner) load();   // 저장하는 사이 신원이 바뀌었다 / the identity changed while saving
    }).catch(err => { setBusy(false); closeDialog(); toast(err.message || TX.saveFail); });
  }
  function askDelete(key) {
    if (!isCustom(key) || !S.draft || S.draft.unused.indexOf(key) < 0) return;
    dialog({ title: TX.del, body: '<b data-i18n-skip>' + hdEsc(nameOf(key)) + '</b><span>' + TX.delAsk + '</span>', warn: TX.delWarn, btn: TX.delBtn, danger: true, ok: () => doDelete(key) });
  }
  // 삭제는 [저장]을 기다리지 않고 바로 지운다(확인 창을 거친다). 서버가 저장된 배치에서도 그 위젯을 빼 준다. 이미 없는 위젯(404)도 지운 것으로 맞춘다
  // deleting does not wait for [Save] (it has its own confirmation); the server strips the widget from the saved layout; an already-gone widget (404) settles as deleted
  function doDelete(key) {
    if (S.busy || identityMoved()) return;
    setBusy(true);
    const who = S.owner;
    const gone = d => {
      if (S.owner !== who) { setBusy(false); closeDialog(); return; }   // 그 사이 다른 사람의 배치를 읽었다(4단계 검토) / another person's layout was read meanwhile (phase-4 review)
      S.seq++;   // 삭제보다 먼저 떠난 읽기가 지운 위젯을 되살리지 못하게 / a read that left before this delete cannot bring the widget back
      useWidgets(S.widgets.filter(w => w.key !== key));
      S.state = hdState(d && d.config ? d.config : hdConfig(S.state), S.widgets);
      if (S.draft) {
        const dr = hdClone(S.draft);
        dr.items = hdSettle(dr.items.filter(i => i.key !== key)); dr.unused = dr.unused.filter(k => k !== key);
        S.draft = dr;
      }
      apply(S.draft || S.state); cacheSave();
      setBusy(false); closeDialog();
      if (S.draft) paintBar();
      toast(TX.deleted);
      // 위젯 에이전트 패널이 듣는다: 열어 둔 위젯이면 처음 상태로(다시 만들지 않는다) / the widget agent panel listens: an open widget resets (never re-created)
      try { document.dispatchEvent(new CustomEvent('ai365-home-widget-deleted', { detail: { key: key } })); } catch (e) { /* 옛 브라우저 / an old browser */ }
      if (owner() !== S.owner) { closeEdit(); load(); }   // 지우는 사이 신원이 바뀌었다 / the identity changed while deleting
    };
    api('DELETE', '/api/home/widgets/' + encodeURIComponent(key) + '?acting_user_id=' + encodeURIComponent(who)).then(gone, err => {
      if (err.status === 404) { gone(null); return; }
      setBusy(false); closeDialog(); toast(err.message || TX.delFail);
    });
  }
  function setBusy(on) {
    S.busy = on;
    if (bar) bar.querySelectorAll('button').forEach(b => { b.disabled = on; });
    const ok = document.querySelector('#hdOv [data-hd-dlg="ok"]');
    if (ok) ok.disabled = on;
  }

  /* ── 확인 창(실제 제품의 취소 · 저장 창 모양) / confirmation dialog (the real product's cancel and save dialogs) ── */
  function dialog(opts) {
    closeDialog();
    const ov = document.createElement('div');
    ov.className = 'hd-ov'; ov.id = 'hdOv';
    ov.innerHTML = '<div class="hd-dlg" role="dialog" aria-modal="true" aria-labelledby="hdDlgTt"><div class="hd-dlg-tt"><span id="hdDlgTt">' + hdEsc(opts.title) + '</span>' +
      '<button type="button" class="hd-ic" data-hd-dlg="x" title="' + TX.close + '">' + ICON.x + '</button></div><div class="hd-dlg-bd">' + opts.body + '</div>' +
      (opts.warn ? '<div class="hd-dlg-warn">' + hdEsc(opts.warn) + '</div>' : '') + '<div class="hd-dlg-act"><button type="button" class="hd-dlg-btn' + (opts.danger ? ' danger' : '') +
      '" data-hd-dlg="ok">' + hdEsc(opts.btn) + '</button></div></div>';
    ov.addEventListener('click', e => {
      const b = e.target.closest('[data-hd-dlg]');
      if (!b || S.busy) return;
      if (b.dataset.hdDlg === 'ok') opts.ok(); else closeDialog();
    });
    ov.addEventListener('keydown', e => {   // Tab 은 창 안의 두 버튼만 돈다 / Tab cycles the dialog's two buttons only
      if (e.key !== 'Tab') return;
      const f = [].slice.call(ov.querySelectorAll('button:not(:disabled)'));
      if (!f.length) return;
      const i = f.indexOf(document.activeElement), j = e.shiftKey ? (i <= 0 ? f.length - 1 : i - 1) : (i === f.length - 1 ? 0 : i + 1);
      e.preventDefault(); f[j].focus();
    });
    document.body.appendChild(ov);
    S.dlg = { back: document.activeElement };
    ov.querySelector('[data-hd-dlg="ok"]').focus();
    tr();
  }
  function closeDialog() {
    const ov = document.getElementById('hdOv');
    if (!ov) return;
    ov.remove();
    const back = S.dlg && S.dlg.back;
    S.dlg = null;
    if (back && document.contains(back) && typeof back.focus === 'function') back.focus();
  }

  /* ── 끌기(포인터 이벤트): 옮기기 = 덮개를 끈다(4px 넘게 움직이면 시작), 크기 = 오른쪽 아래 손잡이, 넣기 = 서랍 카드를 홈으로.
     끄는 동안 위젯은 손을 따라오고 점선 칸이 놓을 자리 · 크기를 보이며, 놓으면 그 칸에 붙고 나머지가 비킨다. 화살표 키는 없다(사용자 결정)
     dragging (pointer events): move = drag a cover (starts past 4px), size = the bottom-right handle, add = a drawer card onto the home. The widget
     follows the hand while a dashed cell shows where and how big it lands; on release it snaps and the rest make room. No arrow keys (user decision) ── */
  function onDown(e) {
    if (!E.on || drag || S.busy || (e.pointerType === 'mouse' && e.button !== 0)) return;
    const cv = e.target.closest('.hd-cover');
    if (!cv || e.target.closest('.rm')) return;
    const key = cv.dataset.hdKey, it = S.draft.items.filter(i => i.key === key)[0];
    if (!it) return;
    e.preventDefault();
    beginDrag({ kind: e.target.closest('.rz') ? 'size' : 'move', key: key, it: Object.assign({}, it), el: cv.parentNode }, e);
  }
  function onDrawerDown(e) {
    if (!E.on || drag || S.busy || (e.pointerType === 'mouse' && e.button !== 0) || e.target.closest('button')) return;
    const card = e.target.closest('[data-hd-add]');
    if (!card) return;
    e.preventDefault();
    beginDrag({ kind: 'add', key: card.dataset.hdAdd, el: null }, e);
  }
  function beginDrag(d, e) {
    // 미끄러지던 중(FLIP)이면 먼저 멈추고 잰다 — 중간 위치를 재면 위젯이 손에서 튀었다(4단계 검토) / stop a running slide before measuring (phase-4 review)
    if (d.el) { clearTimeout(d.el._flipT); d.el.style.transition = 'none'; d.el.style.transform = ''; }
    const g = dash.getBoundingClientRect(), r = d.el ? d.el.getBoundingClientRect() : null;
    drag = Object.assign(d, { pid: e.pointerId, mouse: e.pointerType === 'mouse', x0: e.clientX, y0: e.clientY, cx: e.clientX, cy: e.clientY,
      sy: hero ? hero.scrollTop : 0, on: false, r: r, ox: r ? r.left - g.left : 0, oy: r ? r.top - g.top : 0, target: null, raf: 0 });
    if (d.kind === 'size') startDrag();
  }
  function startDrag() {
    const d = drag;
    d.on = true;
    document.body.classList.add('hd-dragging');
    if (d.el) { clearTimeout(d.el._flipT); d.el.style.transition = ''; }   // 미끄러지던 중이면 멈추고 손을 바로 따라오게 / stop a slide so the widget follows the hand at once
    if (d.kind === 'size') {
      document.body.classList.add('hd-sizing-now');
      d.el.classList.add('hd-sizing');
      d.el.style.width = d.r.width + 'px'; d.el.style.height = d.r.height + 'px';
    } else if (d.kind === 'move') {
      d.el.classList.add('hd-moving');
    } else {
      toggleDrawer(false);   // 서랍은 비켜 준다(서랍 아래 칸에도 놓을 수 있게, 서랍 위에서 놓아도 넣지 않게 — 4단계 검토) / the drawer steps aside (phase-4 review)
      floatEl = document.createElement('div');
      floatEl.className = 'hd-float';
      floatEl.innerHTML = '<span' + (isCustom(d.key) ? ' data-i18n-skip' : '') + '>' + hdEsc(nameOf(d.key)) + '</span>';
      document.body.appendChild(floatEl);
      tr();
    }
    d.raf = requestAnimationFrame(autoScroll);
  }
  function onMove(e) {
    const d = drag;
    if (!d || e.pointerId !== d.pid) return;   // 시작한 포인터만 따라간다(손가락 둘) / follow the pointer that started it only (two fingers)
    // 단추를 뗀 것을 놓쳤으면(창 밖에서 뗐다) 위젯이 따라다니지 않게 그만둔다 / a missed release (outside the window) abandons the drag
    if (d.mouse && e.buttons === 0) { endDrag(false); return; }
    d.cx = e.clientX; d.cy = e.clientY;
    if (!d.on) {
      if (Math.abs(d.cx - d.x0) + Math.abs(d.cy - d.y0) < 4) return;
      startDrag();
    }
    e.preventDefault();
    track();
  }
  function limitNote(s, size) {
    return (s.wantW > size.max_w ? Ld('maxW', { n: size.max_w }) : s.wantW < size.min_w ? Ld('minW', { n: size.min_w }) : '') +
      (s.wantH > size.max_h ? Ld('maxH', { n: size.max_h }) : s.wantH < size.min_h ? Ld('minH', { n: size.min_h }) : '');
  }
  // 손 위치 → 위젯이 따라오고 점선 칸이 놓을 자리 · 크기를 보인다 / the hand → the widget follows and the dashed cell shows where it lands
  function track() {
    const d = drag, scroll = (hero ? hero.scrollTop : 0) - d.sy, dx = d.cx - d.x0, dy = d.cy - d.y0 + scroll;
    const t = hdTracks(S.draft.layout, dash.clientWidth, GAP), size = sizeOf(d.key);
    let want, label;
    if (d.kind === 'size') {
      // 손을 따라 커지고 줄되, 최소 · 최대 크기에서 조금(40px)만 더 가고 멈춘다 — 더 갈 수 없다는 것이 손에 느껴지게(점선 안내도 같이 뜬다)
      // grow and shrink with the hand, but only 40px past the minimum and maximum, so the limit is felt (the dashed notice says it too)
      const slack = 40, x = d.it.x, wMax = Math.min(size.max_w, GRID_COLS - x), hMax = size.max_h;
      const minW = hdSpanW(t, x, Math.min(size.min_w, wMax)) - slack, maxW = hdSpanW(t, x, wMax) + slack;
      const minH = size.min_h * ROW + (size.min_h - 1) * GAP - slack, maxH = hMax * ROW + (hMax - 1) * GAP + slack;
      const rw = Math.min(Math.max(d.r.width + dx, Math.max(120, minW)), maxW), rh = Math.min(Math.max(d.r.height + dy, Math.max(120, minH)), maxH);
      d.el.style.width = rw + 'px'; d.el.style.height = rh + 'px';
      const s = hdSnapSize(x, Math.max(1, d.r.width + dx), Math.max(1, d.r.height + dy), size, t, ROW, GAP);   // 칸 · 안내는 손 위치로 / cells and notice follow the hand
      want = { x: d.it.x, y: d.it.y, w: s.w, h: s.h };
      label = Ld('size', { w: s.w, h: s.h }) + limitNote(s, size);
    } else if (d.kind === 'move') {
      d.el.style.transform = 'translate(' + dx + 'px,' + dy + 'px)';
      const p = hdSnapMove(d.ox + dx, d.oy + dy, d.it.w, t, ROW, GAP);
      want = { x: p.x, y: p.y, w: d.it.w, h: d.it.h };
      label = Ld('drop');
    } else {
      floatEl.style.transform = 'translate(' + (d.cx + 12) + 'px,' + (d.cy + 10) + 'px)';
      const g = dash.getBoundingClientRect(), hit = document.elementFromPoint(d.cx, d.cy);
      // 격자 밖이나 편집 막대 위(막대는 위에 붙어 격자를 덮을 수 있다)는 놓을 곳이 아니다 / outside the grid or over the edit bar (it can stick over the grid) is no drop spot
      if (d.cx < g.left || d.cx > g.right || d.cy < g.top || d.cy > g.bottom + ROW || (hit && hit.closest && hit.closest('#hdEbar'))) { d.target = null; hideCell(); return; }
      const w = Math.min(size.w, GRID_COLS), p = hdSnapMove(d.cx - g.left - 24, d.cy - g.top - 20, w, t, ROW, GAP);
      want = { x: p.x, y: p.y, w: w, h: size.h };
      label = Ld('drop');
    }
    d.target = want;
    // 점선 = 놓으면 실제로 갈 자리(겹친 위젯을 밀고 빈 곳을 당긴 뒤 — 놓을 때와 같은 계산) / the dashed box = where it really lands (after the same push and pull as the drop)
    const next = d.kind === 'add' ? hdAdd(S.draft, d.key, size, want.x, want.y) : hdPlace(S.draft, d.key, want.x, want.y, want.w, want.h, size);
    showCell(next.items.filter(i => i.key === d.key)[0] || want, label);
  }
  function showCell(b, label) {
    if (!cell) { cell = document.createElement('div'); cell.className = 'hd-cell'; cell.innerHTML = '<span data-i18n-skip></span>'; }
    if (cell.parentNode !== dash) dash.appendChild(cell);
    cell.style.gridColumn = (Math.min(b.x, GRID_COLS - 1) + 1) + ' / span ' + Math.max(1, Math.min(b.w, GRID_COLS - b.x));
    cell.style.gridRow = (b.y + 1) + ' / span ' + b.h;
    cell.firstChild.textContent = label;
  }
  function hideCell() { if (cell && cell.parentNode) cell.remove(); }
  function autoScroll() {
    const d = drag;
    if (!d || !d.on || !hero) return;
    const r = hero.getBoundingClientRect(), edge = 56;
    let v = 0;
    if (d.cy < r.top + edge) v = -Math.ceil((r.top + edge - d.cy) / 6);
    else if (d.cy > r.bottom - edge) v = Math.ceil((d.cy - (r.bottom - edge)) / 6);
    if (v) { const before = hero.scrollTop; hero.scrollTop = before + v; if (hero.scrollTop !== before) track(); }
    d.raf = requestAnimationFrame(autoScroll);
  }
  // 놓기: 점선 칸에 붙인다(그 위젯은 그 자리, 나머지가 비킨다). 그만두면 제자리로 미끄러져 돌아간다 / drop onto the dashed cell; an abandoned drag slides back
  function endDrag(commit) {
    const d = drag;
    if (!d) return;
    drag = null;
    if (d.raf) cancelAnimationFrame(d.raf);
    const before = rects();
    hideCell();
    if (floatEl) { floatEl.remove(); floatEl = null; }
    document.body.classList.remove('hd-dragging', 'hd-sizing-now');
    if (d.el) {
      d.el.classList.remove('hd-moving', 'hd-sizing');
      d.el.style.transform = ''; d.el.style.width = ''; d.el.style.height = ''; d.el.style.transition = '';
    }
    if (!d.on) return;
    if (!commit || !d.target || !S.draft) { flip(before); return; }
    const t = d.target, size = sizeOf(d.key);
    change(() => (d.kind === 'add' ? hdAdd(S.draft, d.key, size, t.x, t.y) : hdPlace(S.draft, d.key, t.x, t.y, t.w, t.h, size)), before);
  }

  /* ── 시작 / boot ── */
  const style = document.createElement('style');
  style.id = 'hdCss'; style.textContent = CSS;
  document.head.appendChild(style);
  const pool = document.createElement('div');
  pool.className = 'hd-pool'; pool.id = 'hdPool';
  dash.parentNode.insertBefore(pool, dash.nextSibling);
  dash.querySelectorAll('.wg[data-wg]').forEach(el => { builtinEl[el.dataset.wg] = el; });

  if (gear) {
    gear.title = TX.edit;   // 이름은 보이는 글자 · title 로(사전이 영어로 바꾼다 — aria-label 은 바꾸지 못한다) / named by its text and title, which the dictionary translates
    if (gearTx) gearTx.textContent = TX.edit;
    gear.addEventListener('click', openEdit);
  }
  dash.addEventListener('pointerdown', onDown);
  dash.addEventListener('click', e => {
    const wa = !E.on && e.target.closest('[data-hd-wa]');
    if (wa) { try { const a = window.AI365_widgetAgent; if (a && a.open) a.open(wa.dataset.hdWa); } catch (x) { /* 패널 없음 / no panel */ } return; }
    // 위젯 에이전트 패널이 열려 있으면(2026-11-21 사용자 "위젯을 화면에서 클릭해서 대화할 상대를 전환") 만든 위젯 카드 어디를 눌러도 그 위젯으로 바꾼다.
    // 빼는 것: 지금 고치는 위젯 · 기본 위젯 · 점선 카드(data-wg 없음) · 카드 안의 링크 · 단추 같은 누르는 것 · 글자를 끌어 고른 때
    // with the widget agent panel open (user, 2026-11-21) a click anywhere on a made widget card switches the conversation to it — except the widget
    // being edited, built-ins, the dashed card (no data-wg), links and other controls inside the card, and a click that ends a text selection
    if (!E.on && document.body.classList.contains('wa-open')) {
      const card = e.target.closest('#dash > .hd-cw[data-wg]');
      if (card && !card.classList.contains('hd-wa-on') && !e.target.closest('a,button,input,select,textarea,label,[role="button"]')) {
        let picked = '';
        try { picked = String(window.getSelection() || ''); } catch (x) { /* 고른 글 없음 / no selection */ }
        if (!picked) {
          try { const a = window.AI365_widgetAgent; if (a && a.open) a.open(card.dataset.wg); } catch (x) { /* 패널 없음 / no panel */ }
          return;
        }
      }
    }
    const rm = E.on && !S.busy && !drag && e.target.closest('[data-hd-rm]');
    if (!rm) return;
    change(() => hdRemove(S.draft, rm.dataset.hdRm, isLocked(rm.dataset.hdRm)));
    // 누른 ✕ 는 위젯과 함께 사라진다: 초점은 그 위젯이 간 [위젯 추가]로 / the pressed ✕ leaves with its widget, so focus moves to [Add widget] where it went
    const a = document.activeElement;
    if (bar && document.hasFocus() && (!a || a === document.body || !a.isConnected || pool.contains(a))) bar.querySelector('[data-hd-act="add"]').focus({ preventScroll: true });
  });
  document.addEventListener('pointermove', onMove, { passive: false });
  document.addEventListener('pointerup', e => { if (drag && e.pointerId === drag.pid) endDrag(true); });
  document.addEventListener('pointercancel', e => { if (drag && e.pointerId === drag.pid) endDrag(false); });
  window.addEventListener('blur', () => endDrag(false));   // 끄는 중에 다른 창으로 가면 그만둔다 / leaving for another window abandons the drag
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (drag && drag.on) { endDrag(false); return; }
    if (document.getElementById('hdOv')) { if (!S.busy) closeDialog(); return; }
    if (drawer && !drawer.hidden) { toggleDrawer(false); return; }
    if (E.on && !S.busy) askCancel();
  });
  // 서랍 밖을 누르면 닫는다. 누른 순간의 경로로 본다([넣기]가 서랍을 다시 그려 누른 단추가 문서에서 떨어져도 서랍 안으로 친다), 확인 창 안도 서랍 안으로 친다
  // a click outside closes the drawer; judged on the event path at dispatch ([Add] redraws the drawer and detaches the button), and the dialog counts as inside
  document.addEventListener('click', e => {
    if (!drawer || drawer.hidden) return;
    const path = typeof e.composedPath === 'function' ? e.composedPath() : [e.target];
    if (path.some(n => n && n.nodeType === 1 && (n.classList.contains('hd-addw') || n.id === 'hdOv'))) return;
    toggleDrawer(false);
  });
  // 부모 앱이 홈을 다시 열면(사이드바 HOME · 리소스 센터 카드) 편집을 닫고 배치를 새로 읽는다(신원이 바뀌었을 수 있다)
  // when the parent app reopens the home (sidebar HOME, a Resource Center card) editing closes and the layout is re-read (the identity may have changed)
  window.addEventListener('message', e => {
    const d = e.data || {};
    if (e.origin !== location.origin || !d || d.type !== 'ai365-home-entry') return;
    if (E.on && !S.busy) closeEdit();
    load();
  });
  // 너비가 바뀌어 열 수(3 · 2 · 1)가 달라지면 다시 놓는다 / re-place when the width changes the column count
  if (typeof window.ResizeObserver === 'function') {
    new window.ResizeObserver(() => {
      if (!dash.classList.contains('hd-grid') || E.on || drag || !S.state) return;
      if (gridMode() !== S.mode) apply(S.state);
    }).observe(dash);
  }

  try { localStorage.removeItem('ai365_home_dash_v4'); } catch (e) {}   // 3단계까지의 세 열 캐시 / the column-shaped cache up to phase 3
  cacheLoad();
  load();
  // 위젯 에이전트의 실제 크기 미리보기(2026-11-19, docs/widget-agent.md 13절): 이 너비일 때 홈 격자의 열 너비 · 왼쪽 끝(기본 비율) · 줄 높이 ·
  // 간격과, 그 위젯이 홈에 놓여 있으면 그 칸 / the widget agent's real-size preview: the home grid's tracks at this width, row height and gap, and the placed cell
  function geometry(width, key) {
    const st = S.state, it = st && key ? st.items.filter(i => i.key === key)[0] : null;
    return { tracks: hdTracks(st ? st.layout : LAYOUTS[0].value, Math.max(0, width || 0), GAP), row: ROW, gap: GAP,
      placed: it ? { x: it.x, y: it.y, w: it.w, h: it.h } : null };
  }
  // 위젯 에이전트에서 고른 크기를 홈에 놓인 그 위젯에도(저장할 때): 다른 위젯은 비키고(배치 편집과 같은 hdPlace), 배치를 저장한 뒤 다시 읽는다.
  // 편집 중 · 저장 중이거나 놓이지 않았거나 크기가 같으면 아무것도 하지 않는다(false) / applies the size picked in the widget agent to the placed
  // widget on save: others make way (hdPlace, as in layout editing), the layout is saved and read again; false when editing, busy, unplaced or unchanged
  function resizePlaced(key, w, h) {
    if (!S.state || E.on || S.busy) return Promise.resolve(false);
    const it = S.state.items.filter(i => i.key === key)[0];
    if (!it || (it.w === w && it.h === h)) return Promise.resolve(false);
    const next = hdPlace(S.state, key, it.x, it.y, w, h, sizeOf(key)), who = S.owner;
    if (hdSame(next, S.state)) return Promise.resolve(false);
    return api('PUT', '/api/home/dashboard', Object.assign({ acting_user_id: who }, hdConfig(next)))
      .then(() => (S.owner === who ? load().then(() => true) : false), () => false);
  }
  /* ── 위젯 에이전트 패널과 함께(2026-11-20, docs/widget-agent.md 14절) / working with the widget agent panel ── */
  function scrollTo(el) {
    try { el.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: reduced() ? 'auto' : 'smooth' }); } catch (e) { el.scrollIntoView(); }
  }
  // 그 자리에 그리기: 놓인 만든 위젯의 본문 · 이름을 작업본 모델로 잠깐 바꿔 그린다(저장된 모델은 그대로), model 이 없으면 저장된 모습으로. 한 번에 한 위젯만.
  // 놓여 있지 않으면 false / drawing in place: a placed made widget shows the draft model for a while (the stored model stays); no model restores it;
  // one widget at a time; false when it is not placed
  function restorePv(key) {
    const el = madeEl[key], w = S.byKey[key];
    if (!el || !el._pv) return;
    el._pv = null;
    if (!w) return;
    const body = el.querySelector('.hd-body'), nm = el.querySelector('.hd-nm');
    unmountIn(body); paintModel(body, w.model); el._model = w.model; mountIn(body);
    if (nm) nm.textContent = w.name || '';
    tr();
  }
  function previewIn(key, model, name) {
    if (A.pv && A.pv !== key) { restorePv(A.pv); A.pv = ''; }
    const el = key ? madeEl[key] : null;
    if (!el) return false;
    if (!model) { restorePv(key); A.pv = ''; return true; }
    const body = el.querySelector('.hd-body'), nm = el.querySelector('.hd-nm');
    unmountIn(body); paintModel(body, model); mountIn(body);
    if (nm) nm.textContent = name || nameOf(key);
    el._pv = model; A.pv = key;
    tr();
    return true;
  }
  // 아직 없는 새 위젯의 자리: 빈 첫 자리에 점선 카드로 작업본을 그린다(저장하면 진짜 위젯이 그 자리에 놓인다). model 이 없으면 치운다
  // a spot for a widget not made yet: the draft drawn as a dashed card at the first free spot (saving puts the real widget there); no model removes it
  function placeGhost() {
    if (!A.ghost) return;
    const el = A.ghost.el;
    if (E.on || !S.state || !dash.classList.contains('hd-grid')) { el.style.display = 'none'; return; }
    el.style.display = '';
    const mode = S.mode || 3, items = mode === 3 ? S.state.items : hdFlow(S.state.items, mode);
    const w = Math.min(A.ghost.size.w, mode), h = A.ghost.size.h, at = hdFree(items, w, h, mode);
    el.style.gridColumn = (at.x + 1) + ' / span ' + w;
    el.style.gridRow = (at.y + 1) + ' / span ' + h;
    if (el.parentNode !== dash) dash.appendChild(el);
  }
  function ghostSet(model, name, size) {
    if (!model) {
      if (A.ghost) { unmountIn(A.ghost.el); A.ghost.el.remove(); A.ghost = null; }
      return false;
    }
    const first = !A.ghost;
    if (first) {
      const el = document.createElement('div');
      el.className = 'wg hd-cw hd-ghost';
      el.innerHTML = '<div class="wg-head"><span class="hd-nm" data-i18n-skip></span><span class="sp"></span><span class="hd-new">' + TX.fresh + '</span></div><div class="hd-body"></div>';
      A.ghost = { el: el, model: null, size: { w: 1, h: 1 } };
    }
    const fit = (n, d) => (typeof n === 'number' && isFinite(n) ? Math.min(GRID_COLS, Math.max(1, Math.round(n))) : d);
    A.ghost.size = { w: fit(size && size.w, 1), h: fit(size && size.h, 1) };
    A.ghost.el.querySelector('.hd-nm').textContent = name || '';
    placeGhost();
    if (A.ghost.model !== model) {
      const body = A.ghost.el.querySelector('.hd-body');
      unmountIn(body); paintModel(body, model); mountIn(body);
      A.ghost.model = model;
    }
    tr();
    if (first && A.ghost.el.isConnected) scrollTo(A.ghost.el);
    return true;
  }
  // 새로 만든 위젯을 홈의 빈 첫 자리에(처음 크기): 배치를 새로 읽고 → 안 놓인 위젯이면 놓아 저장 → 다시 읽는다. 편집 중이면 놓지 않는다(서랍에 들어간다)
  // put a just-made widget at the first free spot (its first size): re-read, place it if unplaced, save and read again; never while editing (it joins the drawer)
  function placeNew(key) {
    const who = owner();
    // 그 사이 더 새 읽기가 시작됐으면(이 읽기의 답은 버려진다) 그 읽기까지 기다린다 / a newer read started meanwhile (this one's answer is dropped), so wait for it too
    return load().then(() => S.pending || null).then(() => {
      if (!S.state || S.owner !== who || E.on || S.busy || S.state.unused.indexOf(key) < 0) return false;
      const next = hdAdd(S.state, key, sizeOf(key));
      if (hdSame(next, S.state)) return false;
      return api('PUT', '/api/home/dashboard', Object.assign({ acting_user_id: who }, hdConfig(next)))
        .then(() => (S.owner === who ? load().then(() => S.state.items.some(i => i.key === key)) : false), () => false);
    });
  }
  // 고치는 위젯 강조(다시 그려도 유지), scroll 이면 보이는 곳으로 / mark the widget being edited (kept across redraws); scroll brings it into view
  function markFocus() {
    const el = A.focus ? madeEl[A.focus] : null;
    dash.querySelectorAll(':scope > .hd-wa-on').forEach(n => { if (n !== el) n.classList.remove('hd-wa-on'); });
    if (el) el.classList.add('hd-wa-on');
  }
  function focusOn(key, scroll) {
    A.focus = key || '';
    markFocus();
    const el = A.focus ? madeEl[A.focus] : null;
    if (el && scroll) scrollTo(el);
    return !!el;
  }
  window.AI365_homeDash = { reload: load, open: openEdit, close: closeEdit, state: () => (S.state ? hdClone(S.state) : null),
    draft: () => (S.draft ? hdClone(S.draft) : null), geometry: geometry, resize: resizePlaced, editing: () => E.on,
    preview: previewIn, previewOf: key => ((madeEl[key] && madeEl[key]._pv) || null), ghost: ghostSet, ghostOf: () => (A.ghost ? A.ghost.model : null),
    place: placeNew, focus: focusOn };
  // 위젯 에이전트 화면(static/widget_agent.js)의 미리보기 = 홈과 같은 그리기 / the widget agent screen's preview = the home's drawing
  window.AI365_homeWidget = {
    html: hdWidgetHtml,
    render: function (host, model, opts) { unmountIn(host); paintModel(host, model); return mountIn(host, opts); },
    clear: unmountIn,
  };
})();