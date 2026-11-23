/* =====================================================================
   위젯 에이전트 화면(2026-11-16, docs/widget-agent.md 9절 · 13절 · 14절).
   2026-11-20 패널(사용자 "그룹웨어 에이전트에 아이콘으로 심어서 누르면 나오고 바로 반영되게", 14절): 머리줄 알약이 아니라 그룹웨어 에이전트 머리줄의
   아이콘(#waBtn) · 만든 위젯 머리의 아이콘으로 연다. 홈은 그대로 보이고 오른쪽에 대화 패널(460)이 붙는다. 미리보기는 따로 없다 — 홈 격자의 그 위젯
   자리에 바로 그린다(찾는 동안의 초안도, 아직 없는 새 위젯은 빈 첫 자리의 점선 카드로). [저장]도 없다 — 작업본이 바뀔 때마다(턴 · 되돌리기 · 이름 ·
   크기 · 새로 가져오기) 자동으로 저장해 홈에 반영하고, 새 위젯은 홈의 빈 첫 자리에 놓는다. 마음에 안 들면 [되돌리기] · 기록. 기본 위젯은 대상이 아니다.
   아래 2026-11-16 · 11-19 설명 가운데 "왼쪽 미리보기 · [저장] · 토글"은 이 패널로 바뀌었다(대화 · 생각 과정 · 입력 카드 · 정보 · 기록은 그대로).
   The panel (2026-11-20, user: "plant it in the groupware agent as an icon; a click brings it out and changes land at once", section 14): opened
   from #waBtn in the groupware header or the icon on a made widget, no longer a header pill. The home stays in view with a 460px conversation
   panel on its right. There is no separate preview: drafts are drawn in the widget's own cell of the home grid (a widget not made yet gets a
   dashed card at the first free spot). There is no [Save]: every change (a turn, undo, rename, size, refresh) is saved and shown on Home at once,
   and a new widget lands on the first free spot; [Undo] and the history take things back. Built-in widgets are out of scope.
   In the 2026-11-16 and 11-19 notes below, the left preview, [Save] and the toggle are replaced by this panel; the rest stands.
   대화로 나만의 위젯을 만들고 고친다(리포트 에이전트의 그룹웨어 버전). 왼쪽은 홈에서 보이는 모습 그대로의 미리보기
   (static/home_dash.js 의 window.AI365_homeWidget = 홈과 같은 그리기), 오른쪽은 대화 + 입력 카드.
   작업본과 대화는 이 화면이 들고 있고(서버는 한 턴씩 계산만: POST /api/home/agent/turn/stream), [저장]하면 내 위젯이 되어 배치 편집의
   위젯 추가 서랍에 들어간다(POST · PUT /api/home/widgets). [내 위젯]에서 저장한 위젯을 다시 열어 고친다. [되돌리기]는 바로 전 작업본으로.
   KPI 카드를 무엇의 숫자인지 없이 만들면 "어떤 데이터를 연결할까요?"로 되묻는다.
   2026-11-19 대화 화면 2차(사용자 "우리 채팅창처럼", 13절):
   - 대화 = 메인 채팅과 같은 꼴: '생각 중입니다' → 생각 과정(찾을 곳 판단 · 사내/외부 리소스 카드와 진행 줄 · 위젯 편집 카드 · 단계 트리) →
     답 · 바뀐 점 · 추가 확인 폼 카드 · 다음에 해 볼 것 · 출처 · 발치(복사 · 이 턴 되돌리기 · 다시 시도). 진행은 스트림의 plan · stage · branch ·
     picked · round · tool 이벤트로 바로 그린다. 보내기는 작업 중 ■ 멈추기, 기다리는 동안 쓴 요청은 Queue 에 쌓였다가 차례로 간다.
     입력 카드 = 메인 채팅 입력창과 같은 구성(사용자 "이 채팅창이랑 다를게 없어야"): [+](도구 메뉴 — 묶음 › 도구) · [자동 ▾](누를 때마다 자동 → 사내
     → 외부, 사내면 [리소스 센터] = 지식 관리 · 데이터 분석 고르기) · 마이크(메인 채팅처럼 모양만) · 보내기(종이비행기, 작업 중 ■).
   - 왼쪽 빈 곳: A 실제 크기 미리보기(가로 · 세로 칸 고르기 — 홈 격자와 같은 크기, 저장하면 처음 크기 · 놓인 위젯도) · B 위젯 정보(출처 · 가져온
     시각 · 새로 가져오는 간격 · 구성 + [지금 새로 가져오기]) · C 변경 기록(눌러 미리 보고 되돌리기).
   - 대화는 위젯마다 저장(GET · PUT /api/home/agent/chat/{key}) — 다시 열면 생각 과정은 접힌 채로 이어진다.
   권한은 지금 신원(acting_user_id)의 것이다. 홈 파일의 #dash 에 data-hd="1" 이 있을 때만 움직인다. 고정 문구(TX)는 한국어 텍스트 노드로 두고
   home-live.js 사전이 영어로 바꾸며, 2차의 문구(U)는 화면이 한국어 · 영어를 직접 고른다(바꾸면 다시 그린다).
   The widget agent screen (2026-11-16; docs/widget-agent.md sections 9 and 13): the second [Widget Agent] of the home header toggle.
   It builds and edits your own widgets by conversation. The left shows the widget exactly as Home draws it; the right holds the
   conversation and the input card. The screen keeps the draft and the conversation (the server computes one turn at a time);
   [Save] makes it one of my widgets (the Add widget drawer of layout editing); [My widgets] reopens one; [Undo] steps back.
   Chat round 2 (2026-11-19, user: "like our chat", section 13): the conversation takes the main chat's shape — 'Thinking…', then
   the thinking process (the intent, internal/external resource cards with progress lines, a widget-edit card, the stage tree),
   the reply, what changed, a details form card, suggestions, sources and a footer (copy, undo this turn, try again), drawn live
   from the stream's plan, stage, branch, picked, round and tool events; send turns into ■ stop while busy and requests written
   meanwhile wait in a Queue; [Auto ▾] picks where to fetch. The empty left side gets A a real-size preview (pick cells; saving
   sets the first size and resizes a placed widget), B widget info (sources, fetch time, refresh interval, contents, [Refresh
   now]) and C history (preview and restore). The conversation is saved per widget and reopens with the thinking folded.
   Permissions are those of the current identity. Fixed labels (TX) are Korean text nodes swapped by home-live.js; round-2 text (U)
   is picked per language by the screen, which repaints on a switch.
===================================================================== */
(function () {
  'use strict';

  /* ── 순수 함수(노드 테스트가 그대로 부른다) / pure functions (called as is by the node tests) ── */
  const NEW_TITLE = '새 위젯';
  const ASK_TEXT = '어떤 데이터를 연결할까요?';
  const MAX_UNDO = 10;
  const HISTORY = 10;
  const SOURCES = ['data', 'docs', 'web'];
  const MAX_QUEUE = 5;
  const MAX_SAVED_MSGS = 60;      // 서버의 MAX_CHAT_MSGS / the server's MAX_CHAT_MSGS
  const CHAT_BUDGET = 550000;     // 대화 저장본 글자 수(서버 상한 60만보다 조금 작게) / the saved conversation's size, a little under the server's 600k
  const MAX_LABEL = 80;
  // 도구 트리에서 고르면 입력창에 채우는 요청 문장 / the request a tool-tree pick fills into the input
  const EXAMPLES = {
    update_chart: '막대 차트를 선 차트로 바꿔줘', set_style: '값 라벨을 보여줘', set_theme: '우리 회사 색(#4450CE)으로 바꿔줘',
    add_reference_line: '평균선을 넣어줘', remove_reference_line: '기준선을 지워줘', add_calculation: '전월 대비 증감률도 같이 보여줘',
    add_highlight: '가장 높은 곳을 강조해줘', remove_highlight: '강조를 지워줘', set_trend: '추세선을 넣어줘',
    add_filter: '최근 6개월만 보여줘', remove_filter: '필터를 지워줘', add_kpi: 'KPI 카드를 하나 넣어줘',
    remove_kpi: 'KPI 카드를 지워줘', arrange_kpis: 'KPI 카드 순서를 바꿔줘', rename_widget: "위젯 제목을 '이번 달 실적'으로 바꿔줘",
    set_insight: '인사이트를 한 줄 써줘', fetch_data: '오늘 원달러 환율 KPI 카드를 만들어줘', ask_data: '위젯에 데이터를 연결해줘',
  };
  // 첫 화면 예: 되묻기(KPI 카드) · 웹 · 사내 데이터 · 사내 문서 / the first-screen examples: the data question, the web, company data, documents
  const STARTERS = ['KPI 카드 위젯을 만들어줘', '오늘 원달러 환율 위젯을 만들어줘', '지점별 매출 차트 위젯을 만들어줘', '연차 규정 요약 위젯을 만들어줘'];

  function waBlank() { return { v: 2, title: NEW_TITLE, source: null, chart: null, kpis: [], theme: null, insight: '', blocks: [], origins: [] }; }
  function waBlankModel() {
    return { v: 2, title: NEW_TITLE, kpis: [], chart: null, theme: null, insight: '', insight_wait: false, blocks: [], refs: [], origins: [], refresh: false,
      needs_data: false, empty: true };
  }
  // 보여 줄 것이 있는가: 차트 · KPI 카드 · 글/목록(3단계) / anything to show: a chart, KPI cards, or text and lists (phase 3)
  function waHasContent(w) { return !!(w && (w.chart || (Array.isArray(w.kpis) && w.kpis.length) || (Array.isArray(w.blocks) && w.blocks.length))); }
  // 저장할 것이 있는가: 저장한 적 없으면 내용이나 제목이 생겼을 때, 저장했으면 저장본과 다를 때 / anything to save: once content or a title exists for a new draft, a difference from the saved copy otherwise
  function waDirty(w, saved) {
    if (!w) return false;
    if (saved === null || saved === undefined) return waHasContent(w) || w.title !== NEW_TITLE;
    return JSON.stringify(w) !== saved;
  }
  // 서버에 보낼 대화 기록: 마지막 10개, 글(에이전트가 물었으면 그 질문도) · 도구 이름 · 성공 여부만, 오류 · 멈춘 줄은 뺀다
  // the history sent to the server: the last ten, text (plus the agent's question, if any), tool names and outcomes; error and stopped lines left out
  function waHistory(msgs) {
    const textOf = m => {
      const t = typeof m.text === 'string' ? m.text.trim() : '';
      const q = m.ask && m.ask.question ? '[질문] ' + m.ask.question + (m.ask.cards && m.ask.cards.length ? ' (' + m.ask.cards.join(', ') + ')' : '') : '';
      return [t, q].filter(Boolean).join(' ');
    };
    return (msgs || []).filter(m => m && !m.error && !m.stopped && textOf(m)).slice(-HISTORY).map(m => ({
      role: m.role === 'user' ? 'user' : 'agent', text: textOf(m),
      trace: (m.trace || []).map(t => ({ tool: t.tool, ok: !!t.ok })),
    }));
  }
  function waEsc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  // 이벤트 스트림 한 조각 → {event, data}(data 는 JSON). data 가 없거나 JSON 이 아니면 null / one event-stream chunk → {event, data}; null when malformed
  function waSseEvent(chunk) {
    let event = 'message';
    const data = [];
    String(chunk || '').split(/\r?\n/).forEach(line => {
      if (line.indexOf('event:') === 0) event = line.slice(6).trim();
      else if (line.indexOf('data:') === 0) data.push(line.slice(5).replace(/^ /, ''));
    });
    if (!data.length) return null;
    try { return { event: event, data: JSON.parse(data.join('\n')) }; } catch (e) { return null; }
  }
  // 받은 글자 → 끝난 이벤트들 + 아직 끝나지 않은 나머지(다음 조각과 이어 붙인다) / received text → finished events plus the unfinished rest
  function waSseSplit(buf) {
    const parts = String(buf || '').split(/\r?\n\r?\n/), rest = parts.pop();
    return { events: parts.map(waSseEvent).filter(Boolean), rest: rest };
  }

  /* 생각 과정(2026-11-19): 한 턴의 진행 이벤트를 모은 틀 — 찾을 곳 판단(plan) · 출처 카드(stage → branch, 쓴 갈래 picked) · 단계(round) ·
     도구 결과(tool). 화면은 이것만으로 그린다(저장본에도 들어간다)
     the thinking frame (2026-11-19): one turn's progress events — the intent (plan), source cards (stage → branch, the one used
     = picked), stages (round) and tool results (tool). The screen draws from it alone (it is saved too) */
  function waFrameEmpty() { return { plan: null, cards: {}, order: [], picks: [], rounds: [], tools: [] }; }
  function waFrame(prev, ev) {
    const f = prev ? JSON.parse(JSON.stringify(prev)) : waFrameEmpty();
    const d = ev && ev.data && typeof ev.data === 'object' ? ev.data : null;
    if (!d) return f;
    const card = src => {
      if (!f.cards[src]) { f.cards[src] = { status: 'run' }; f.order.push(src); }
      return f.cards[src];
    };
    if (ev.event === 'plan') {
      f.plan = { sources: (Array.isArray(d.sources) ? d.sources : []).filter(s => SOURCES.indexOf(s) >= 0), view: typeof d.view === 'string' ? d.view : '', forced: !!d.forced };
    } else if (ev.event === 'stage' && SOURCES.indexOf(d.source) >= 0) {
      const c = card(d.source);
      c.status = 'run';   // 같은 곳을 다시 찾으면 다시 진행 중 / searching the same place again runs again
      if (d.fallback) c.fallback = true;
    } else if (ev.event === 'branch' && SOURCES.indexOf(d.source) >= 0) {
      const c = card(d.source);
      c.status = d.ok ? 'ok' : 'fail';
      c.note = d;
    } else if (ev.event === 'picked') {   // 가져오기마다 하나(한 턴에 두 번 가져오면 둘) / one per fetch (two fetches in a turn give two)
      f.picks.push(SOURCES.indexOf(d.source) >= 0 ? d.source : 'none');
    } else if (ev.event === 'round' && typeof d.no === 'number') {
      f.rounds.push({ no: d.no, tools: (Array.isArray(d.tools) ? d.tools : []).filter(t => t && typeof t === 'object')
        .map(t => ({ tool: String(t.tool || ''), label: String(t.label || '') })) });
    } else if (ev.event === 'tool') {
      f.tools.push({ tool: String(d.tool || ''), label: String(d.label || ''), ok: !!d.ok, detail: String(d.detail || ''), say: String(d.say || ''),
        round: typeof d.round === 'number' ? d.round : 0 });
    }
    return f;
  }
  // 끝난 턴의 trace 로 단계 · 도구를 채운다(진행 알림을 받지 못했을 때) / stages and tools from a finished turn's trace (when no notices came)
  function waFrameFromTrace(frame, trace) {
    const f = frame ? JSON.parse(JSON.stringify(frame)) : waFrameEmpty();
    if (f.tools.length || !Array.isArray(trace) || !trace.length) return f;
    trace.forEach(t => {
      if (!t || typeof t !== 'object') return;
      const no = typeof t.round === 'number' ? t.round : 1;
      let g = f.rounds.filter(r => r.no === no)[0];
      if (!g) { g = { no: no, tools: [] }; f.rounds.push(g); }
      if (g.tools.length <= f.tools.filter(x => x.round === no).length) g.tools.push({ tool: String(t.tool || ''), label: String(t.label || '') });
      f.tools.push({ tool: String(t.tool || ''), label: String(t.label || ''), ok: !!t.ok, detail: String(t.detail || ''), say: String(t.say || ''), round: no });
    });
    return f;
  }
  /* 저장된 대화의 모양 다시 짓기(독립 검토 2026-11-19 — 저장본은 화면이 보낸 그대로라 모르는 값 · 틀린 모양이 섞일 수 있다: 출처 이름으로 HTML 이
     끼어들거나(저장된 XSS) 그리기가 멈췄다). 아는 칸만, 정한 모양 · 길이로 / rebuilding a saved conversation (independent review: the store keeps what
     the screen sent, so unknown values or shapes could inject HTML through a source name or break painting); known fields only, typed and capped */
  const STR = (v, n) => (typeof v === 'string' ? v.slice(0, n) : '');
  const NUM = v => (typeof v === 'number' && isFinite(v) ? v : 0);
  const SRC_PARAMS = ['auto', 'internal', 'data', 'docs', 'web'];
  function waCleanRefs(list) {
    return (Array.isArray(list) ? list : []).filter(r => r && typeof r === 'object').slice(0, 12).map(r => {
      const url = STR(r.url, 600);
      return { kind: ['data', 'doc', 'web'].indexOf(r.kind) >= 0 ? r.kind : 'doc', label: STR(r.label, 160),
        page: typeof r.page === 'number' && isFinite(r.page) ? Math.round(r.page) : null, url: /^https?:\/\//i.test(url) ? url : '' };
    }).filter(r => r.label);
  }
  function waCleanNote(n) {
    n = n && typeof n === 'object' ? n : {};
    return { ok: !!n.ok, why: STR(n.why, 240), kind: STR(n.kind, 20), refs: waCleanRefs(n.refs), rows: NUM(n.rows), count: NUM(n.count),
      columns: (Array.isArray(n.columns) ? n.columns : []).filter(c => typeof c === 'string').slice(0, 12).map(c => c.slice(0, 40)),
      sql: STR(n.sql, 4000), note: STR(n.note, 240), live: !!n.live, skipped: !!n.skipped };
  }
  function waCleanFrame(f) {
    f = f && typeof f === 'object' ? f : {};
    const out = waFrameEmpty(), p = f.plan && typeof f.plan === 'object' ? f.plan : null;
    if (p) out.plan = { sources: (Array.isArray(p.sources) ? p.sources : []).filter(x => SOURCES.indexOf(x) >= 0), view: ['kpi', 'chart', 'list', 'text'].indexOf(p.view) >= 0 ? p.view : '', forced: !!p.forced };
    const cards = f.cards && typeof f.cards === 'object' ? f.cards : {};
    (Array.isArray(f.order) ? f.order : []).forEach(x => {
      const c = cards[x];
      if (SOURCES.indexOf(x) < 0 || out.cards[x] || !c || typeof c !== 'object') return;
      out.cards[x] = { status: ['run', 'ok', 'fail'].indexOf(c.status) >= 0 ? c.status : 'fail', fallback: !!c.fallback };
      if (c.note) out.cards[x].note = waCleanNote(c.note);
      out.order.push(x);
    });
    out.picks = (Array.isArray(f.picks) ? f.picks : []).filter(x => x === 'none' || SOURCES.indexOf(x) >= 0).slice(0, 8);
    out.rounds = (Array.isArray(f.rounds) ? f.rounds : []).filter(r => r && typeof r === 'object').slice(0, 8).map(r => ({ no: Math.round(NUM(r.no)),
      tools: (Array.isArray(r.tools) ? r.tools : []).filter(t => t && typeof t === 'object').slice(0, 12).map(t => ({ tool: STR(t.tool, 40), label: STR(t.label, 80) })) }));
    out.tools = (Array.isArray(f.tools) ? f.tools : []).filter(t => t && typeof t === 'object').slice(0, 40).map(t => ({ tool: STR(t.tool, 40), label: STR(t.label, 80),
      ok: !!t.ok, detail: STR(t.detail, 300), say: STR(t.say, 200), round: Math.round(NUM(t.round)) }));
    return out;
  }
  const CHANGE_KEYS = ['title', 'view', 'chart', 'kpis', 'origin', 'insight', 'theme'];
  function waCleanChanges(list) {
    return (Array.isArray(list) ? list : []).filter(c => c && typeof c === 'object' && CHANGE_KEYS.indexOf(c.k) >= 0).slice(0, 5).map(c => {
      if (c.k === 'view') { const v = c.v && typeof c.v === 'object' ? c.v : {}; return { k: 'view', v: { chart: STR(v.chart, 20), kpis: NUM(v.kpis), text: !!v.text, list: NUM(v.list) } }; }
      if (c.k === 'kpis') return { k: 'kpis', v: NUM(c.v) };
      if (c.k === 'origin') {
        return { k: 'origin', v: (Array.isArray(c.v) ? c.v : []).filter(o => o && typeof o === 'object').slice(0, 8)
          .map(o => ({ kind: SOURCES.indexOf(o.kind) >= 0 ? o.kind : 'docs', refs: NUM(o.refs), first: STR(o.first, 160) })) };
      }
      if (c.k === 'insight') return { k: 'insight', v: c.v === 'set' ? 'set' : 'cleared' };
      return { k: c.k, v: STR(c.v, 120) };
    });
  }
  // 저장된 대화 한 줄 → 그릴 수 있는 줄(모르는 역할은 null) / one saved message → a drawable one (null for unknown roles)
  function waCleanMsg(m) {
    if (!m || typeof m !== 'object' || (m.role !== 'user' && m.role !== 'agent')) return null;
    if (m.role === 'user') return { role: 'user', text: STR(m.text, 4000), at: STR(m.at, 40) };
    const a = m.ask && typeof m.ask === 'object' ? m.ask : null;
    return { role: 'agent', text: STR(m.text, 4000), at: STR(m.at, 40), q: STR(m.q, 2000), src: SRC_PARAMS.indexOf(m.src) >= 0 ? m.src : 'auto',
      beforeId: STR(m.beforeId, 40), base: STR(m.base, 40), blank: !!m.blank, changed: !!m.changed || !!m.beforeId, error: !!m.error, fixed: !!m.fixed, stopped: !!m.stopped,
      trace: (Array.isArray(m.trace) ? m.trace : []).filter(t => t && typeof t === 'object').slice(0, 40).map(t => ({ agent: STR(t.agent, 40), group: STR(t.group, 40),
        tool: STR(t.tool, 40), label: STR(t.label, 80), ok: !!t.ok, detail: STR(t.detail, 300), say: STR(t.say, 200), round: Math.round(NUM(t.round)) })),
      ask: a ? { kind: STR(a.kind, 20), question: STR(a.question, 200), cards: (Array.isArray(a.cards) ? a.cards : []).filter(c => typeof c === 'string').slice(0, 4).map(c => c.slice(0, 40)),
        need: STR(a.need, 80), hint: STR(a.hint, 300) } : null,
      frame: m.frame ? waCleanFrame(m.frame) : null, changes: waCleanChanges(m.changes), refs: waCleanRefs(m.refs) };
  }
  // 위젯이 무엇을 보여 주는가 / what a widget shows: chart type, KPI card count, text, list length
  function waViewOf(w) {
    w = w || {};
    const blocks = Array.isArray(w.blocks) ? w.blocks : [];
    const list = blocks.filter(b => b && b.type === 'list')[0];
    return { chart: w.chart && w.chart.type ? String(w.chart.type) : '', kpis: Array.isArray(w.kpis) ? w.kpis.length : 0,
      text: blocks.some(b => b && b.type === 'text'), list: list ? Math.max(1, Array.isArray(list.items) ? list.items.length : 0) : 0 };
  }
  // 한 턴에 바뀐 점(답 아래 줄): 제목 · 보기 · 차트 · KPI 카드 · 새 출처 · 인사이트 · 대표 색 — 최대 5줄, 글은 그릴 때 언어로
  // what a turn changed (rows under the reply): title, view, chart, KPI cards, new sources, insight, brand colour; five at most
  function waChanges(before, after) {
    const a = before || {}, b = after || {}, out = [];
    if ((a.title || '') !== (b.title || '')) out.push({ k: 'title', v: b.title || '' });
    const va = waViewOf(a), vb = waViewOf(b);
    if (JSON.stringify(va) !== JSON.stringify(vb)) out.push({ k: 'view', v: vb });
    else {
      if (JSON.stringify(a.chart || null) !== JSON.stringify(b.chart || null)) out.push({ k: 'chart', v: vb.chart });
      if (JSON.stringify(a.kpis || []) !== JSON.stringify(b.kpis || [])) out.push({ k: 'kpis', v: vb.kpis });
    }
    const seen = {};
    (Array.isArray(a.origins) ? a.origins : []).forEach(o => { if (o) seen[o.part + '|' + o.kind + '|' + o.fetched_at] = 1; });
    const fresh = (Array.isArray(b.origins) ? b.origins : []).filter(o => o && !seen[o.part + '|' + o.kind + '|' + o.fetched_at]);
    if (fresh.length) {
      out.push({ k: 'origin', v: fresh.map(o => ({ kind: String(o.kind || ''), refs: Array.isArray(o.refs) ? o.refs.length : 0,
        first: Array.isArray(o.refs) && o.refs[0] ? String(o.refs[0].label || '') : '' })) });
    }
    if ((a.insight || '') !== (b.insight || '')) out.push({ k: 'insight', v: b.insight ? 'set' : 'cleared' });
    const ta = (a.theme && a.theme.brand) || '', tb = (b.theme && b.theme.brand) || '';
    if (ta !== tb) out.push({ k: 'theme', v: tb });
    return out.slice(0, 5);
  }
  // 다음에 해 볼 것(위젯 상태로 정하는 규칙 — 모델을 부르지 않는다): 최대 3개, [한국어, 영어] / suggestions from the widget state (no model call)
  function waNext(w) {
    w = w || {};
    const out = [], v = waViewOf(w), c = w.chart || {};
    const add = p => { if (out.length < 3 && !out.some(x => x[0] === p[0])) out.push(p); };
    if ((Array.isArray(w.kpis) ? w.kpis : []).some(k => k && k.pending)) return [];   // 데이터 질문이 먼저 / the data question comes first
    if (v.chart && v.chart !== 'kpi') {
      add(['bar', 'hbar'].indexOf(v.chart) >= 0 ? ['선 차트로 바꿔줘', 'Make it a line chart'] : ['막대 차트로 바꿔줘', 'Make it a bar chart']);
      if (['bar', 'hbar', 'line', 'area'].indexOf(v.chart) >= 0 && !(c.ref_lines || []).length) add(['평균선을 넣어줘', 'Add an average line']);
      if (!(c.highlights || []).length) add(['가장 높은 곳을 강조해줘', 'Highlight the highest value']);
    }
    if (v.text) {
      add(['핵심 숫자를 KPI 카드로 뽑아줘', 'Pull the key numbers into KPI cards']);
      add(['항목별 목록도 보여줘', 'Show it as a list too']);
    }
    if (v.list && !v.text) add(['글로도 요약해줘', 'Add a short text summary']);
    if ((v.chart || v.kpis) && !w.insight) add(['인사이트를 한 줄 써줘', 'Write a one-line insight']);
    return out;
  }
  // 다시 가져올 수 있는 출처인가(서버 refreshable 과 같다) / can this origin refresh (the server's refreshable)
  function waRefreshable(o) { return !!(o && SOURCES.indexOf(o.kind) >= 0 && o.query && (o.kind !== 'data' || o.sql)); }
  // 위젯 정보(왼쪽 B): 부분별 출처 · 가장 늦게 가져온 시각 · 새로 가져오는 출처 종류 / widget info (left B): per-part sources, the latest fetch, refreshing kinds
  function waInfo(w) {
    w = w || {};
    const rows = (Array.isArray(w.origins) ? w.origins : []).filter(o => o && typeof o === 'object').map(o => ({
      part: o.part === 'source' ? (w.chart ? 'chart' : 'cards') : String(o.part || ''), kind: String(o.kind || ''),
      refs: (Array.isArray(o.refs) ? o.refs : []).filter(r => r && r.label).map(r => ({ label: String(r.label), page: r.page })),
      at: String(o.fetched_at || ''), refresh: waRefreshable(o) }));
    return { rows: rows, latest: rows.reduce((m, r) => (r.at > m ? r.at : m), ''), kinds: SOURCES.filter(k => rows.some(r => r.refresh && r.kind === k)) };
  }
  // 미리보기 크기(칸): 고른 크기 → 홈에 놓인 크기 → 처음 크기(차트면 1 × 2) / the preview size: picked, else placed, else the first size
  function waSizeOf(w, placed) {
    const fit = (n, d) => (typeof n === 'number' && isFinite(n) ? Math.min(3, Math.max(1, Math.round(n))) : d);
    const s = w && w.size;
    if (s && typeof s === 'object' && typeof s.w === 'number' && typeof s.h === 'number') return { w: fit(s.w, 1), h: fit(s.h, 1), picked: true };
    if (placed) return { w: fit(placed.w, 1), h: fit(placed.h, 1), picked: false, placed: true };
    return { w: 1, h: w && w.chart && w.chart.type !== 'kpi' ? 2 : 1, picked: false };
  }
  // 변경 기록의 이름: '종류:글'(turn = 요청 · new · opened · rename · size · refresh · restore) — 언어는 그릴 때 / history labels, rendered per language
  function waLabel(kind, text) { return (kind + ':' + String(text == null ? '' : text)).slice(0, MAX_LABEL); }
  // 대화 저장본(서버 normalize_chat 이 받는 모양): 그리기 전용 칸(fold)은 빼고, 넘치면 오래된 변경 기록부터, 그다음 오래된 대화부터 버린다
  // the saved conversation: drawing-only fields (fold) left out; over budget, the oldest history goes first, then the oldest messages
  function waChatPayload(msgs, undo, label, at) {
    const keep = m => { const o = {}; Object.keys(m || {}).forEach(k => { if (k !== 'fold') o[k] = m[k]; }); return o; };
    const out = { v: 1, msgs: (msgs || []).slice(-MAX_SAVED_MSGS).map(keep),
      hist: (undo || []).map(u => ({ id: u.id || '', label: u.label || '', at: u.at || '', widget: u.widget })), label: label || '', at: at || '' };
    const size = () => JSON.stringify(out).length;
    while (size() > CHAT_BUDGET && out.hist.length) out.hist.shift();
    while (size() > CHAT_BUDGET && out.msgs.length > 2) out.msgs.shift();
    return out;
  }
  // 입력 카드의 [자동 ▾](자동 · 사내 · 외부)와 리소스 센터(사내에서 고른 곳) → 턴의 source(auto · internal · data · docs · web)
  // the input card's [Auto ▾] (auto, internal, external) and the resource center (places picked under internal) → the turn's source
  function waSourceOf(scope, res) {
    if (scope === 'web') return 'web';
    if (scope !== 'internal') return 'auto';
    const r = (Array.isArray(res) ? res : []).filter(x => x === 'data' || x === 'docs');
    return r.length === 1 ? r[0] : 'internal';
  }
  // 추가 확인 폼 카드의 제출 → 보낼 요청(적은 글이 먼저, 없으면 고른 곳 + 카드 이름). 만들 수 없으면 '' / the details form → the request to send
  const PLACE = { data: ['사내 데이터', 'company data'], docs: ['사내 문서', 'company documents'], web: ['웹', 'the web'] };
  function waAskMessage(ask, opt, detail, en) {
    const t = String(detail || '').trim();
    if (t) return t;
    const cards = ask && Array.isArray(ask.cards) ? ask.cards.filter(c => typeof c === 'string' && c) : [];
    if (!PLACE[opt] || !cards.length) return '';
    const names = cards.map(c => "'" + c + "'").join(', ');
    return en ? 'Find data for the ' + names + ' card' + (cards.length > 1 ? 's' : '') + ' in ' + PLACE[opt][1] + ' and connect it'
      : PLACE[opt][0] + '에서 ' + names + ' 카드에 맞는 데이터를 찾아 연결해줘';
  }

  const PURE = { NEW_TITLE: NEW_TITLE, EXAMPLES: EXAMPLES, STARTERS: STARTERS, waBlank: waBlank, waBlankModel: waBlankModel, waHasContent: waHasContent,
    waDirty: waDirty, waHistory: waHistory, waEsc: waEsc, waSseEvent: waSseEvent, waSseSplit: waSseSplit, waFrameEmpty: waFrameEmpty, waFrame: waFrame,
    waFrameFromTrace: waFrameFromTrace, waViewOf: waViewOf, waChanges: waChanges, waNext: waNext, waInfo: waInfo, waSizeOf: waSizeOf, waLabel: waLabel,
    waChatPayload: waChatPayload, waAskMessage: waAskMessage, waSourceOf: waSourceOf, waCleanMsg: waCleanMsg, waCleanFrame: waCleanFrame, CHAT_BUDGET: CHAT_BUDGET };
  if (typeof module !== 'undefined' && module.exports) module.exports = PURE;
  if (typeof document === 'undefined') return;

  /* ── 화면 / screen ── */
  const dash = document.getElementById('dash'), hero = document.querySelector('.hero');
  if (!dash || dash.dataset.hd !== '1' || !hero) return;   // 옛 홈 파일이면 손대지 않는다 / an older home file is left alone
  const E = waEsc;

  const TX = {
    agent: '위젯 에이전트', mine: '내 위젯', fresh: '새 위젯', undo: '되돌리기', save: '저장', rename: '이름 바꾸기',
    hello: '무엇을 만들까요?', helloSub: '대화로 위젯을 만들고 고치면 홈에 바로 반영됩니다. 예를 눌러 시작해 보세요.',
    tools: '도구', toolTree: '도구 트리', toolsHead: '위젯 에이전트의 도구',
    toolsSub: '항목을 누르면 요청 문장이 입력창에 채워집니다.', send: '보내기',
    placeholder: '위젯에 바라는 점을 적어 주세요. / 를 누르면 도구 트리가 열립니다.', askPlaceholder: '연결할 데이터나 숫자를 알려 주세요.',
    loading: '불러오는 중…', noMine: '아직 만든 위젯이 없습니다', mineFail: '내 위젯을 불러오지 못했습니다',
    saveFail: '위젯을 저장하지 못했습니다', undone: '되돌렸습니다', turnFail: '위젯 에이전트가 응답하지 않습니다. 잠시 뒤 다시 시도해 주세요',
    dirtyAsk: '홈에 반영하지 못한 변경이 있습니다.', dirtyNew: '반영하지 않고 새 위젯을 시작할까요?', dirtyOpen: '반영하지 않고 다른 위젯을 열까요?',
    startNew: '새로 시작', open: '열기', cancel: '취소', close: '닫기', moved: '사용자가 바뀌어 위젯 에이전트를 처음 상태로 돌렸습니다',
  };
  // 2차 문구 [한국어, 영어] — 화면이 언어를 골라 그린다(사전을 거치지 않는다) / round-2 text [ko, en], picked by the screen (no dictionary)
  const UI = {
    think: ['생각 중입니다', 'Thinking…'], thought: ['생각 과정', 'Thinking process'], thoughtSum: ['리소스 {n} · 도구 {t}', 'Resources {n} · tools {t}'],
    thoughtRes: ['리소스 {n}', 'Resources {n}'], thoughtTools: ['도구 {t}', 'Tools {t}'],
    resources: ['리소스', 'Resources'], internalN: ['사내 리소스 {n}개', 'Internal resources {n}'], externalN: ['외부 리소스 {n}개', 'External resources {n}'],
    plan: ['의도 판단 — {places}에서 찾아 {view}(으)로 보여 주기', 'Intent — look in {places} and show it as {view}'],
    planForced: ['고른 곳 — {places}에서만 찾기', 'Chosen place — {places} only'],
    v_kpi: ['KPI 카드', 'KPI cards'], v_chart: ['차트', 'a chart'], v_list: ['목록', 'a list'], v_text: ['글', 'text'],
    src_data: ['사내 데이터', 'Company data'], src_docs: ['사내 문서', 'Company documents'], src_web: ['웹 검색', 'Web search'], srcAuto: ['자동', 'Auto'],
    subRun: ['찾는 중', 'Searching'], subFail: ['찾지 못함', 'Nothing found'], subSkipped: ['기다리지 않음', 'Not awaited'],
    subDocs: ['문서 {d} · 근거 {p}', 'Documents {d} · passages {p}'], subRows: ['{rows}행', '{rows} rows'], subExt: ['외부 출처 {n}개', 'External sources {n}'],
    run_docs: ['검색 범위의 문서에서 관련 문단을 찾는 중', 'Searching the documents in scope'], run_data: ['허용된 데이터에서 조회하는 중', 'Querying the data you can access'],
    run_web: ['웹에서 찾는 중', 'Searching the web'], webFallback: ['사내에서 찾지 못해 웹에서 찾는 중', 'Nothing in the company, so searching the web'],
    docsFound: ['검색 범위의 문서에서 관련 문단을 찾았습니다', 'Found related passages in the documents in scope'],
    docsPages: ['{pages} 문단을 참조했습니다', 'Referred to passages on {pages}'], docsRefs: ['근거 {n}곳 확보 — {first}{more}', '{n} passages — {first}{more}'],
    more: [' 외 {k}건', ' and {k} more'], dataFound: ['{tables}에서 {rows}행을 가져왔습니다', 'Fetched {rows} rows from {tables}'],
    webLive: ['{site}에서 실시간 값을 받았습니다', 'Got live values from {site}'], webFound: ['웹 자료 {n}건에서 내용을 찾았습니다', 'Found it in {n} web sources'],
    failWhy: ['찾지 못했습니다 — {why}', 'Nothing found — {why}'], skipped: ['다른 곳에서 찾아 기다리지 않았습니다', 'Found elsewhere, so not awaited'],
    pickedThis: ['이 결과를 위젯에 넣었습니다', 'This result went into the widget'], pickedOther: ['다른 곳의 결과를 썼습니다', "Another place's result was used"],
    details: ['자세히', 'Details'], sql: ['조회 SQL', 'Query SQL'], columns: ['열', 'Columns'],
    edit: ['위젯 편집', 'Widget edits'], toolsN: ['도구 {n}', 'Tools {n}'],
    commonChanged: ['결과를 반영해 위젯을 고쳤습니다', 'Updated the widget with the results'], commonSame: ['위젯은 바뀌지 않았습니다', 'The widget did not change'],
    treeHead: ['작업을 단계별로 실행', 'Run tasks by stage'], stageN: ['{no}단계 · {n}개 작업 실행 {state}', 'Stage {no} · {n} {tasks} {state}'],
    stDone: ['완료', 'done'], stRun: ['중', 'running'], stStop: ['멈춤', 'stopped'], subStop: ['멈춤', 'Stopped'],
    lineStop: ['멈춰서 끝까지 찾지 않았습니다', 'Stopped before the search finished'],
    actSearch: ['{places}에서 찾는 중', 'Searching {places}'], actEdit: ['위젯을 고치는 중', 'Editing the widget'], actReply: ['답을 정리하는 중', 'Writing the reply'],
    stopped: ['멈췄습니다. 위젯은 바뀌지 않았습니다.', 'Stopped. The widget did not change.'],
    cTitle: ['제목', 'Title'], cView: ['보기', 'View'], cChart: ['차트', 'Chart'], cKpis: ['KPI 카드', 'KPI cards'], cOrigin: ['출처', 'Sources'],
    cInsight: ['인사이트', 'Insight'], cTheme: ['대표 색', 'Brand colour'], cChartChanged: ['설정을 바꿈', 'Settings changed'], cInsSet: ['새로 씀', 'Written'],
    cInsCleared: ['지움', 'Removed'], cThemeDefault: ['기본 색', 'Default'], kpiN: ['KPI 카드 {n}개', '{n} KPI cards'], textPart: ['글', 'Text'],
    listN: ['목록 {n}건', 'List of {n}'], emptyView: ['내용 없음', 'Nothing yet'], nPlaces: ['{n}곳', '({n})'],
    ch_bar: ['막대 차트', 'Bar chart'], ch_hbar: ['가로 막대 차트', 'Horizontal bar chart'], ch_line: ['선 차트', 'Line chart'], ch_area: ['영역 차트', 'Area chart'],
    ch_pie: ['원 차트', 'Pie chart'], ch_donut: ['도넛 차트', 'Donut chart'],
    next: ['다음에 해 볼 것', 'Try next'], copy: ['복사', 'Copy'], copied: ['복사했습니다', 'Copied'], undoTurn: ['이 턴 되돌리기', 'Undo this turn'],
    retry: ['다시 시도', 'Try again'], restored: ['되돌렸습니다', 'Restored'], restoreFail: ['그 모습을 불러오지 못했습니다', 'That state could not be loaded'],
    afTitle: ['추가 확인이 필요합니다', 'More details needed'], opt_data: ['사내 데이터에서 찾기', 'Find it in company data'],
    opt_docs: ['사내 문서에서 찾기', 'Find it in company documents'], opt_web: ['웹에서 찾기', 'Find it on the web'],
    afPh: ['연결할 데이터나 숫자를 적어 주세요 (예: 이번 달 매출)', "Name the data or a number (e.g. this month's sales)"], afGo: ['제출', 'Submit'],
    afErr: ['연결할 데이터를 적거나 찾을 곳을 골라 주세요', 'Name the data or pick where to look'], afErrNoCards: ['무엇을 보여 줄지 적어 주세요', 'Say what the widget should show'],
    stop: ['멈추기', 'Stop'], busyPh: ['답을 기다리는 동안 다음 요청을 추가하세요', 'Add your next request while waiting'], queue: ['Queue · {n}', 'Queue · {n}'],
    qEdit: ['요청 고치기', 'Edit request'], qDel: ['요청 지우기', 'Remove request'], queueFull: ['대기 요청은 {n}개까지입니다', 'The queue holds {n} requests'],
    sc_auto: ['자동', 'Auto'], sc_internal: ['사내', 'Internal'], sc_web: ['외부', 'External'], plusTitle: ['도구', 'Tools'], mic: ['음성 입력', 'Voice input'],
    resCenter: ['리소스 센터', 'Resource Center'], resTitle: ['리소스 선택', 'Select resources'], resSub: ['위젯이 참고할 사내 리소스를 선택하세요', 'Pick the company resources the widget should use'],
    res_docs: ['지식 관리', 'Knowledge'], res_data: ['데이터 분석', 'Data Analysis'], resDesc_docs: ['사내 문서', 'Company documents'], resDesc_data: ['사내 데이터', 'Company data'],
    resOk: ['선택 완료', 'Done'], resCancel: ['취소', 'Cancel'], resHint: ['고르지 않으면 둘 다에서 찾습니다', 'With nothing picked, both are searched'], back: ['뒤로', 'Back'],
    wide: ['가로', 'Wide'], tall: ['세로', 'Tall'], sizeGroup: ['홈에서의 크기', 'Size on Home'],
    sizeNote: ['고르면 홈에서 바로 바뀝니다', 'A pick resizes it on Home at once'], sizeNoteNew: ['홈에 처음 놓일 크기입니다', 'The size it first takes on Home'],
    // 2026-11-20 패널: 탭 · 홈에 반영 상태 · 홈에 놓기 · 지우기 / the panel: tabs, the applied state, putting on Home, deleting
    tab_chat: ['대화', 'Chat'], tab_info: ['정보', 'Info'], tab_hist: ['기록', 'History'],
    stSaved: ['홈에 반영됨 {t}', 'On Home · {t}'], stUnsaved: ['반영 안 됨 · 다시 저장', 'Not applied · save again'],
    emptyKeep: ['내용이 없는 모습은 홈에 반영하지 않습니다', 'An empty state is not applied to Home'],
    placedNew: ['새 위젯을 홈에 놓았습니다', 'The new widget is on Home'],
    placedLater: ['위젯을 만들었습니다. 지금은 홈에 놓지 못해 배치 편집의 위젯 추가에 넣었습니다', 'Widget made. It could not be placed now, so it is under Add widget in Edit layout'],
    offHome: ['이 위젯은 홈에 놓여 있지 않습니다', 'This widget is not on Home'], putHome: ['홈에 놓기', 'Put on Home'],
    putDone: ['홈에 놓았습니다', 'It is on Home now'], putFail: ['지금은 홈에 놓을 수 없습니다', 'It cannot be placed on Home right now'], offTag: ['홈에 없음', 'Not on Home'],
    del: ['위젯 지우기', 'Delete widget'], delAsk: ['이 위젯을 지울까요?', 'Delete this widget?'],
    delBody: ['홈과 내 위젯에서 사라지고 대화 기록도 함께 지워집니다. 되돌릴 수 없습니다.', 'It leaves Home and My widgets together with its conversation. This cannot be undone.'],
    delGo: ['지우기', 'Delete'], deleted: ['위젯을 지웠습니다', 'Widget deleted'], delFail: ['위젯을 지우지 못했습니다', 'The widget could not be deleted'],
    busyOpen: ['지금 하는 일이 끝난 뒤에 열 수 있습니다', 'It can be opened once the current work is done'],
    openFail: ['그 위젯을 열지 못했습니다', 'That widget could not be opened'],
    pickHint: ['홈에 있는 내 위젯을 누르면 그 위젯과 대화합니다', 'Click one of your widgets on Home to talk about that one'],
    goneKeep: ['이 위젯은 지워졌습니다. 고친 내용은 홈에 반영하지 않았습니다 — [다시 저장]을 누르면 새 위젯으로 만듭니다',
      'This widget was deleted. Your changes were not applied; [save again] makes them a new widget'],
    peekAt: ['지난 모습 미리보기 — {label}', 'Preview of an earlier state — {label}'], restore: ['이 모습으로 되돌리기', 'Restore this'], close: ['닫기', 'Close'],
    info: ['위젯 정보', 'Widget info'], iOrigin: ['출처', 'Sources'], iAt: ['가져온 시각', 'Fetched'], iRefresh: ['새로 가져오기', 'Refresh'], iCompose: ['구성', 'Contents'],
    iSize: ['크기', 'Size'], iNone: ['아직 가져온 내용이 없습니다', 'Nothing fetched yet'], iManual: ['직접 넣은 내용', 'Entered by hand'],
    iNoRefresh: ['새로 가져오지 않음', 'Not refreshed'], ttl_data: ['사내 데이터 1분마다', 'company data every minute'],
    ttl_docs: ['사내 문서 6시간마다', 'documents every 6 hours'], ttl_web: ['웹 30분마다', 'web every 30 minutes'], iInsight: ['인사이트 있음', 'with an insight'],
    iSizeVal: ['가로 {w} × 세로 {h}', '{w} wide × {h} tall'], iPlaced: ['홈에 놓임', 'on Home'],
    refreshNow: ['지금 새로 가져오기', 'Refresh now'], refreshing: ['가져오는 중…', 'Refreshing…'], refreshed: ['새로 가져왔습니다', 'Refreshed'],
    noChange: ['새로 가져온 내용이 없습니다', 'Nothing new came back'], refreshFail: ['지금은 새로 가져올 수 없습니다', 'Refreshing is not possible right now'],
    hist: ['변경 기록', 'History'], now: ['지금', 'Now'], histEmpty: ['아직 바뀐 것이 없습니다', 'No changes yet'], histHint: ['눌러서 그때 모습을 미리 봅니다', 'Click to preview that state'],
    hNew: ['새 위젯', 'New widget'], hOpened: ['저장된 모습', 'As saved'], hRename: ['이름 바꾸기 · {t}', 'Renamed · {t}'], hSize: ['크기 가로 {w} × 세로 {h}', 'Size {w} × {h}'],
    hRefresh: ['새로 가져오기', 'Refreshed'], hRestore: ['되돌림 · {l}', 'Restored · {l}'],
    pt_chart: ['차트', 'Chart'], pt_cards: ['카드', 'Cards'], pt_text: ['글', 'Text'], pt_list: ['목록', 'List'], refsN: ['근거 {n}곳', '{n} passages'],
    previewFail: ['그 모습을 미리 보지 못했습니다', 'That state could not be previewed'],
    chatLoadFail: ['대화 기록을 불러오지 못해 이번 대화는 저장하지 않습니다', 'The saved conversation could not be loaded, so this one will not be saved'],
  };
  function U(k, v) {
    const p = UI[k];
    if (!p) return k;
    let s = p[isEn() ? 1 : 0];
    if (v) Object.keys(v).forEach(n => { s = s.split('{' + n + '}').join(String(v[n])); });
    return s;
  }
  const svg = d => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + d + '</svg>';
  const ICON = {
    list: svg('<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>'),
    plus: svg('<path d="M12 5v14M5 12h14"/>'),
    undo: svg('<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>'),
    save: svg('<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7M7 3v4a1 1 0 0 0 1 1h7"/>'),
    pen: svg('<path d="M12 20h9"/><path d="M16.4 3.6a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4z"/>'),
    tree: svg('<path d="M21 12h-8M21 6H8M21 18h-8M3 6v4c0 1.1.9 2 2 2h3M3 10v6c0 1.1.9 2 2 2h3"/>'),
    ask: svg('<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01"/>'),
    eye: svg('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'),
    chev: svg('<path d="m6 9 6 6 6-6"/>'),
    chevR: svg('<path d="m9 6 6 6-6 6"/>'),
    spark: svg('<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>'),
    up: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5"/><polyline points="5 12 12 5 19 12"/></svg>',
    stop: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6.5" y="6.5" width="11" height="11" rx="2.5"/></svg>',
    hash: svg('<path d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18"/>'),
    globe: svg('<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>'),
    chart: svg('<path d="M3 3v18h18"/><path d="M8 17v-6M13 17V7M18 17v-4"/>'),
    doc: svg('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/>'),
    db: svg('<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>'),
    tool: svg('<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>'),
    minus: svg('<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>'),
    pend: svg('<circle cx="12" cy="12" r="9"/>'),
    fail: svg('<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/>'),
    check: svg('<path d="M20 6 9 17l-5-5"/>'),
    branch: svg('<path d="M6 5v11"/><circle cx="6" cy="19" r="2.2"/><circle cx="18" cy="6" r="2.2"/><path d="M18 8.5A9.5 9.5 0 0 1 8.5 18"/>'),
    arrow: svg('<path d="M5 4v7a4 4 0 0 0 4 4h10"/><path d="m15 11 4 4-4 4"/>'),
    copy: svg('<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'),
    retry: svg('<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>'),
    x: svg('<path d="M18 6 6 18M6 6l12 12"/>'),
    refresh: svg('<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/>'),
    hist: svg('<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>'),
    info: svg('<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>'),
    // 메인 채팅 입력창의 아이콘(마이크 · 종이비행기 · STOP) / the main chat composer's icons (mic, paper plane, stop)
    mic: svg('<rect x="9" y="2.5" width="6" height="11.5" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3.5"/>'),
    plane: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M3.4 20.6 21.6 12 3.4 3.4l2.8 7.2 9.3 1.4-9.3 1.4z"/></svg>',
    stopSq: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2.5"/></svg>',
    res: svg('<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/><path d="M17.5 3.5v6M14.5 6.5h6"/>'),
    palette: svg('<path d="M12 2a10 10 0 0 0 0 20c1 0 1.7-.8 1.7-1.7 0-.5-.2-.9-.5-1.2-.3-.3-.4-.7-.4-1.1 0-.9.8-1.7 1.7-1.7H16a5.6 5.6 0 0 0 5.6-5.6C21.6 6 17.3 2 12 2z"/><circle cx="7.5" cy="11.5" r="1"/><circle cx="10" cy="7" r="1"/><circle cx="15" cy="7.5" r="1"/>'),
    rule: svg('<path d="M3 19h18"/><path d="M3 11h3M9 11h3M15 11h3"/>'),
    sigma: svg('<path d="M18 7V4H6l6 8-6 8h12v-3"/>'),
    star: svg('<path d="m12 3 2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.4l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/>'),
    trend: svg('<path d="m22 7-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/>'),
    funnel: svg('<path d="M22 3H2l8 9.5V19l4 2v-8.5z"/>'),
    back: svg('<path d="m15 18-6-6 6-6"/>'),
    grip: svg('<path d="M4 9h16M4 15h16"/>'),
    size: svg('<rect x="3" y="3" width="18" height="18" rx="2.5"/><path d="M3 12h18M12 3v18"/>'),
    trash: svg('<path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M10 11v6M14 11v6"/>'),
  };
  // [+] 메뉴의 묶음 아이콘 / group icons in the [+] menu
  const GROUP_IC = { '데이터': 'db', '리포트': 'chart', '디자인': 'palette', '기준선': 'rule', '계산 값': 'sigma', '강조': 'star', '추세·예측': 'trend', '필터': 'funnel',
    'KPI 카드': 'hash', '정리': 'pen' };
  const SRC_IC = { data: 'db', docs: 'doc', web: 'globe' };
  // 첫 화면 예시 카드(STARTERS 차례): 아이콘 + 무엇을 보여 주는 예인지(찾는 곳). 글은 사전이 영어로 바꾼다
  // the starter cards (STARTERS order): an icon and what each example shows (where it looks); the dictionary translates the text
  const STARTER_UI = [{ ic: 'hash', cap: 'KPI 카드 · 연결할 데이터를 되물어요' }, { ic: 'globe', cap: '웹 검색 · 실시간 환율' },
    { ic: 'chart', cap: '사내 데이터 · 막대 차트' }, { ic: 'doc', cap: '사내 문서 · 요약 글' }];
  const CSS = [
    /* 패널(2026-11-20, 14절): 홈 오른쪽에 붙는 대화 패널 — 위 60 막대 아래부터 바닥까지, 너비 460. 열리면 홈(.hero)이 그만큼 좁아져 격자가
       다시 놓인다(좁으면 2열 · 1열, static/home_dash.js). 800 이하의 좁은 창에서는 홈을 밀지 않고 덮는다
       the panel (2026-11-20, section 14): docked on the right of the home, from under the 60px bar to the bottom, 460 wide. Opening it narrows
       the home (.hero), whose grid re-flows (two columns, then one); on windows up to 800 wide it covers the home instead */
    '.wa{display:none;position:fixed;top:60px;right:0;bottom:0;z-index:45;width:460px;max-width:100vw;flex-direction:column;background:#fff;border-left:1px solid #E1E5F0;border-top:1px solid #E1E5F0;border-top-left-radius:16px;box-shadow:-6px 0 24px rgba(16,24,40,.06);}',
    'body.wa-open .wa{display:flex;}',
    'body.wa-open .hero{margin-right:460px;}',
    'body.wa-open .ph{flex-wrap:wrap;row-gap:12px;}',
    '@media (max-width:800px){body.wa-open .hero{margin-right:0;}.wa{box-shadow:-10px 0 30px rgba(16,24,40,.18);}}',
    '.wa-hd{flex:none;display:flex;align-items:center;gap:4px;min-height:54px;padding:8px 10px 8px 14px;border-bottom:1px solid #EEF0F5;}',
    '.wa-hd > .wa-av{margin-right:6px;}',
    '.wa-nm{flex:1;min-width:0;display:flex;align-items:center;gap:4px;}',
    '.wa-nmtx{min-width:0;font-size:16px;line-height:24px;font-weight:700;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.wa-nmin{width:100%;height:34px;padding:0 10px;border:1px solid var(--primary);border-radius:8px;outline:none;font-size:14.5px;font-weight:600;color:var(--ink);box-shadow:0 0 0 3px rgba(68,80,206,.12);}',
    '.wa-ic,.wa-ib{flex-shrink:0;border-radius:8px;display:flex;align-items:center;justify-content:center;}',
    '.wa-ic{width:28px;height:28px;color:var(--muted);}',
    '.wa-ib{width:32px;height:32px;color:var(--ink-3);}',
    '.wa-ic:hover,.wa-ib:hover{background:var(--soft-3);color:var(--ink-2);}',
    '.wa-ic:disabled,.wa-ib:disabled{opacity:.4;cursor:not-allowed;}',
    '.wa-ic svg{width:15px;height:15px;}',
    '.wa-ib svg{width:17px;height:17px;}',
    '.wa-tabs{flex:none;display:flex;align-items:center;gap:8px;padding:8px 12px;border-bottom:1px solid #EEF0F5;}',
    '.wa-tabs [role="tablist"]{display:flex;gap:4px;}',
    '.wa-tabs .sp{flex:1;}',
    '.wa-tab{height:30px;padding:0 12px;border-radius:9999px;font-size:13px;font-weight:600;color:var(--ink-3);white-space:nowrap;}',
    '.wa-tab:hover{background:var(--soft-3);}',
    '.wa-tab.on,.wa-tab.on:hover{background:var(--primary-soft);color:var(--primary);}',
    '.wa-st{flex-shrink:1;min-width:0;padding:2px 10px;border-radius:9999px;background:var(--table-head);font-size:12px;line-height:18px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-variant-numeric:tabular-nums;}',
    '.wa-st[hidden]{display:none;}',
    '.wa-st:disabled{cursor:default;}',
    '.wa-st.dirty{background:#FFF4DB;color:#8A5A00;font-weight:600;}',
    '.wa-st.dirty:hover{background:#FFE9B8;}',
    '.wa-mine{position:relative;}',
    '.wa-pop{position:absolute;z-index:60;background:#fff;border:1px solid var(--border-2);border-radius:12px;box-shadow:var(--shadow-pop);}',
    '.wa-mine .wa-pop{top:38px;right:-72px;width:300px;max-width:calc(100vw - 24px);max-height:360px;overflow-y:auto;padding:6px;}',
    '.wa-mn-it{width:100%;display:flex;flex-direction:column;align-items:flex-start;gap:1px;padding:8px 10px;border-radius:8px;text-align:left;}',
    '.wa-mn-it:hover{background:var(--sidebar-bg);}',
    '.wa-mn-it.on{background:var(--soft-2);}',
    '.wa-mn-it .t{max-width:100%;font-size:13.5px;font-weight:600;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.wa-mn-it .s{font-size:11.5px;color:var(--muted);font-variant-numeric:tabular-nums;}',
    '.wa-mn-it .off{margin-left:6px;padding:0 6px;border-radius:9999px;background:var(--table-head);color:var(--ink-3);}',
    '.wa-mn-none{padding:14px 10px;text-align:center;font-size:12.5px;color:var(--muted);}',
    /* 알림 줄: 홈에 없는 위젯 [홈에 놓기] · 지난 모습 미리보기 [이 모습으로 되돌리기] / notice rows: a widget off Home, and a history preview */
    '.wa-note,.wa-peek{flex:none;display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:10px 12px 0;padding:8px 10px 8px 14px;border-radius:12px;font-size:12.5px;line-height:18px;}',
    '.wa-note[hidden],.wa-peek[hidden]{display:none;}',
    '.wa-note > span,.wa-peek > span{flex:1;min-width:150px;}',
    '.wa-note{border:1px solid #D9DEF7;background:#F7F8FF;color:var(--ink-2);}',
    '.wa-note button{height:28px;padding:0 12px;border-radius:9999px;background:var(--primary);color:#fff;font-size:12px;font-weight:600;}',
    '.wa-note button:disabled{opacity:.45;cursor:not-allowed;}',
    '.wa-peek{border:1px solid #F6D3A1;background:#FFFBF5;color:#8A5A00;}',
    '.wa-peek button{height:28px;padding:0 12px;border-radius:9999px;font-size:12px;font-weight:600;background:#fff;border:1px solid #F0C98E;color:#8A5A00;}',
    '.wa-peek button.pri{background:#B45309;border-color:#B45309;color:#fff;}',
    /* 정보 · 기록 탭 / the info and history tabs */
    '.wa-pane{flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;gap:12px;padding:14px 12px 20px;}',
    '.wa-pane[hidden]{display:none;}',
    '.wa-pnl{flex:none;padding:12px 14px;border:1px solid #E1E5F0;border-radius:14px;background:#fff;transition:box-shadow .3s;}',
    '.wa-pnl.flash{box-shadow:0 0 0 3px rgba(68,80,206,.25);}',
    '.wa-pnl-t{display:flex;align-items:center;gap:6px;margin-bottom:4px;font-size:13px;line-height:20px;font-weight:700;color:var(--ink);}',
    '.wa-pnl-t svg{width:15px;height:15px;color:var(--ink-3);}',
    '.wa-pnl-t .sub{margin-left:auto;font-size:11.5px;font-weight:400;color:var(--muted);}',
    '.wa-pnl-r{display:flex;gap:12px;padding:7px 0;border-bottom:1px solid #F0F2F6;font-size:12.5px;line-height:18px;}',
    '.wa-pnl-r:last-of-type{border-bottom:0;}',
    '.wa-pnl-r > span:first-child{flex:0 0 84px;color:var(--muted);}',
    '.wa-pnl-r > span:last-child{flex:1;min-width:0;color:var(--ink-2);overflow-wrap:anywhere;}',
    '.wa-pnl-r .o{display:block;}',
    '.wa-pnl-go{display:inline-flex;align-items:center;gap:6px;margin-top:8px;height:32px;padding:0 14px;border:1px solid var(--border);border-radius:9999px;background:#fff;font-size:12.5px;font-weight:600;color:var(--ink-2);}',
    '.wa-pnl-go:hover{background:#F3F5FB;}',
    '.wa-pnl-go:disabled{opacity:.45;cursor:not-allowed;}',
    '.wa-pnl-go svg{width:14px;height:14px;}',
    '.wa-size{display:flex;align-items:center;flex-wrap:wrap;gap:6px;padding-top:4px;font-size:12px;color:var(--muted);}',
    '.wa-size .g{display:inline-flex;padding:2px;border:1px solid #D9DEEA;border-radius:9999px;background:#fff;}',
    '.wa-size .g button{min-width:28px;height:26px;padding:0 6px;border-radius:9999px;font-size:12px;font-weight:600;color:var(--ink-3);font-variant-numeric:tabular-nums;}',
    '.wa-size .g button:hover{background:#F1F3F9;}',
    '.wa-size .g button.on{background:var(--primary);color:#fff;}',
    '.wa-size .g button:disabled{opacity:.45;cursor:not-allowed;}',
    '.wa-size .g + span{margin-left:6px;}',
    '.wa-size-h{margin-top:8px;font-size:12px;line-height:18px;color:var(--muted);}',
    '.wa-del{flex:none;align-self:flex-start;display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 14px;border:1px solid #F3C7CB;border-radius:9999px;background:#fff;font-size:12.5px;font-weight:600;color:var(--danger);}',
    '.wa-del:hover{background:#FFF5F5;}',
    '.wa-del:disabled{opacity:.45;cursor:not-allowed;}',
    '.wa-del svg{width:14px;height:14px;}',
    '.wa-hs{display:flex;flex-direction:column;gap:2px;}',
    '.wa-hs button{display:flex;align-items:center;gap:8px;width:100%;padding:7px 8px;border-radius:8px;text-align:left;font-size:12.5px;line-height:18px;color:var(--ink-2);}',
    '.wa-hs button:hover{background:#F3F5FB;}',
    '.wa-hs button.on{background:var(--primary-soft);color:var(--primary);}',
    '.wa-hs button:disabled{opacity:.5;cursor:not-allowed;}',
    '.wa-hs .l{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.wa-hs .t{flex-shrink:0;font-size:11.5px;color:var(--muted);font-variant-numeric:tabular-nums;}',
    '.wa-hs .now{flex-shrink:0;padding:0 7px;border-radius:9999px;background:var(--primary);font-size:11px;line-height:17px;font-weight:600;color:#fff;}',
    '.wa-hs .dot{flex-shrink:0;width:7px;height:7px;border-radius:50%;background:#C9CFDC;}',
    '.wa-hs button.cur .dot{background:var(--primary);}',
    '.wa-hs-none{padding:6px 8px;font-size:12px;color:var(--muted);}',
    /* 대화(2026-11-17 새 구성, 2026-11-19 메인 채팅 꼴): 에이전트 답은 말풍선 없이 아바타 옆에, 사용자 글은 오른쪽 말풍선
       the conversation (rebuilt 2026-11-17, the main chat's shape 2026-11-19): agent replies beside an avatar, the user's text in a right bubble */
    '.wa-chat{position:relative;flex:1;min-height:0;display:flex;flex-direction:column;}',
    '.wa-chat[hidden]{display:none;}',
    '.wa-msgs{flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;gap:20px;padding:18px 16px 14px;}',
    '.wa-m{display:flex;gap:12px;width:100%;max-width:720px;min-width:0;margin:0 auto;}',
    '.wa-u{justify-content:flex-end;}',
    '.wa-bub{max-width:82%;padding:10px 16px;border-radius:18px 18px 6px 18px;background:#F1F3F9;font-size:14.5px;line-height:22px;color:var(--ink);white-space:pre-wrap;word-break:keep-all;overflow-wrap:anywhere;}',
    '.wa-av{flex-shrink:0;width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:var(--primary-soft);color:var(--primary);}',
    '.wa-av svg{width:16px;height:16px;}',
    '.wa-ab{flex:1;min-width:0;display:flex;flex-direction:column;align-items:flex-start;gap:10px;padding-top:5px;}',
    '.wa-who{align-self:stretch;display:flex;align-items:center;gap:8px;font-size:12.5px;line-height:18px;font-weight:700;color:var(--ink-2);}',
    '.wa-res{margin-left:auto;display:inline-flex;align-items:center;gap:2px;font-size:12px;font-weight:400;color:var(--muted);}',
    '.wa-res:hover{color:var(--primary);}',
    '.wa-res svg{width:13px;height:13px;}',
    '.wa-tx{font-size:14.5px;line-height:23px;color:var(--ink);white-space:pre-wrap;word-break:keep-all;overflow-wrap:anywhere;}',
    '.wa-tx.muted{color:var(--muted);}',
    '.wa-m.err .wa-tx{color:var(--danger);}',
    /* 생각 과정 = 메인 채팅의 실행 틀(사내 리소스 n개 · 에이전트 카드 · ⊖ 진행 줄 · 단계 트리) / the thinking process = the main chat's execution frame */
    '.wa-think{display:flex;align-items:center;gap:11px;min-height:30px;font-size:14.5px;line-height:22px;color:var(--ink);}',
    '.wa-think.sm{min-height:0;gap:8px;padding:2px 0 0 2px;font-size:12.5px;color:var(--ink-3);}',
    '.wa-spin{width:18px;height:18px;border-radius:50%;border:2.5px solid #D9DDF5;border-top-color:var(--primary);animation:waSpin 1s linear infinite;flex-shrink:0;}',
    '.wa-spin.sm{width:12px;height:12px;border-width:2px;}',
    '@keyframes waSpin{to{transform:rotate(360deg);}}',
    '@media (prefers-reduced-motion: reduce){.wa-spin{animation-duration:3s;}}',
    '.wa-fr{align-self:stretch;display:flex;flex-direction:column;gap:8px;}',
    '.wa-fr-tg{align-self:flex-start;display:inline-flex;align-items:center;gap:6px;padding:0;font-size:12.5px;line-height:18px;font-weight:600;color:var(--ink-3);}',
    '.wa-fr-tg .n{font-weight:400;color:var(--muted);}',
    '.wa-fr-tg svg{width:13px;height:13px;transform:rotate(180deg);transition:transform .15s;}',
    '.wa-fr.fold .wa-fr-tg svg{transform:none;}',
    '.wa-fr.fold .wa-fr-bd{display:none;}',
    '.wa-fr-bd{display:flex;flex-direction:column;gap:8px;}',
    '.wa-scnt{font-size:12px;line-height:16px;font-weight:600;color:var(--primary);}',
    '.wa-kc{border-radius:12px;overflow:hidden;background:var(--primary-soft);}',
    '.wa-kc-hd{display:flex;align-items:center;gap:10px;padding:8px 12px;background:var(--soft-2);}',
    '.wa-kc-ic{flex-shrink:0;display:flex;color:var(--primary);}',
    '.wa-kc-ic svg{width:18px;height:18px;}',
    '.wa-kc-tx{flex:1;min-width:0;display:flex;flex-direction:column;}',
    '.wa-kc-tx b{font-size:13.5px;line-height:19px;font-weight:600;color:var(--ink);}',
    '.wa-kc-tx i{font-style:normal;font-size:12px;line-height:17px;color:var(--ink-3);}',
    '.wa-kc-more{flex-shrink:0;display:inline-flex;align-items:center;gap:3px;height:24px;padding:2px 8px;border-radius:12px;background:#fff;font-size:12px;color:var(--ink-2);}',
    '.wa-kc-more svg{width:12px;height:12px;transition:transform .15s;}',
    '.wa-kc-more[aria-expanded="true"] svg{transform:rotate(180deg);}',
    '.wa-kc-bd{padding:8px 12px;}',
    '.wa-kc.edit{background:#F6F7FA;}',
    '.wa-kc.edit .wa-kc-hd{background:#ECEEF3;}',
    '.wa-kc.edit .wa-kc-ic{color:var(--ink-3);}',
    '.wa-ln{display:flex;align-items:flex-start;gap:5px;padding:2px 0;font-size:12px;line-height:18px;color:var(--ink-2);overflow-wrap:anywhere;}',
    '.wa-ln > svg{width:14px;height:14px;flex-shrink:0;margin-top:2px;color:var(--muted);}',
    '.wa-ln.run{color:var(--ink-3);}',
    '.wa-ln.fail,.wa-ln.fail > svg{color:var(--danger);}',
    '.wa-ln.ok > svg{color:var(--success);}',
    '.wa-ln .lb{font-weight:600;}',
    '.wa-ln code{margin-left:6px;padding:0 5px;border-radius:4px;background:#ECEEF3;font:11px/16px ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--muted);}',
    '.wa-kc-dt{margin-top:6px;padding:8px 10px;border-radius:8px;background:#fff;font-size:12px;line-height:18px;color:var(--ink-2);}',
    '.wa-kc-dt ul{list-style:none;margin:0;padding:0;}',
    '.wa-kc-dt li{padding:2px 0;overflow-wrap:anywhere;}',
    '.wa-kc-dt a{color:var(--primary);}',
    '.wa-kc-dt b{display:block;margin-top:4px;font-size:11.5px;color:var(--muted);}',
    '.wa-kc-dt pre{margin:2px 0 0;padding:6px 8px;border-radius:6px;background:#F6F7FA;white-space:pre-wrap;word-break:break-all;font:11.5px/17px ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--ink-2);}',
    '.wa-cl{padding:0 12px;}',
    '.wa-tk{font-size:13px;line-height:19px;color:var(--ink-3);}',
    '.wa-tk-hd{display:inline-flex;align-items:center;gap:8px;padding:3px 0;color:var(--ink-3);}',
    '.wa-tk-hd > svg:first-child{width:13px;height:13px;}',
    '.wa-tk-hd > svg:last-child{width:12px;height:12px;color:var(--muted);transform:rotate(180deg);transition:transform .15s;}',
    '.wa-tk.fold .wa-tk-hd > svg:last-child{transform:none;}',
    '.wa-tk.fold .wa-tk-bd{display:none;}',
    '.wa-tk-g{margin-left:20px;}',
    '.wa-tk-gh,.wa-tk-l{display:flex;align-items:flex-start;gap:8px;padding:3px 0;}',
    '.wa-tk-l{margin-left:20px;color:var(--muted);}',
    '.wa-tk-gh svg,.wa-tk-l svg{width:12px;height:12px;flex-shrink:0;margin-top:4px;}',
    '.wa-tk-l .sf{color:var(--muted);}',
    /* 답 아래: 바뀐 점 · 다음에 해 볼 것 · 출처 · 발치 / under the reply: what changed, suggestions, sources, footer */
    '.wa-chg{align-self:stretch;display:flex;flex-direction:column;}',
    '.wa-chg-r{display:flex;justify-content:space-between;gap:12px;padding:9px 0;border-bottom:1px solid #EEF0F5;font-size:13.5px;line-height:20px;}',
    '.wa-chg-r span{color:var(--ink-3);}',
    '.wa-chg-r b{font-weight:600;color:var(--ink);text-align:right;overflow-wrap:anywhere;}',
    '.wa-sec{align-self:stretch;display:flex;flex-direction:column;}',
    '.wa-sec-t{padding:2px 0 8px;border-bottom:1px solid #EEF0F5;font-size:12px;line-height:16px;font-weight:600;color:var(--ink-3);}',
    '.wa-nx button{display:flex;align-items:center;justify-content:space-between;gap:10px;width:100%;padding:10px 2px;border-bottom:1px solid #EEF0F5;text-align:left;font-size:13.5px;line-height:20px;color:var(--ink);}',
    '.wa-nx button:hover{color:var(--primary);}',
    '.wa-nx button svg{width:14px;height:14px;flex-shrink:0;color:var(--muted);}',
    '.wa-src{display:flex;flex-wrap:wrap;gap:6px;padding-top:10px;}',
    '.wa-src a,.wa-src .s{display:inline-flex;align-items:center;gap:6px;max-width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:10px;background:#fff;font-size:12px;line-height:17px;color:var(--ink-2);text-decoration:none;}',
    '.wa-src a:hover{border-color:#B9C0F2;color:var(--primary);}',
    '.wa-src svg{width:13px;height:13px;flex-shrink:0;color:var(--primary);}',
    '.wa-src span span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
    '.wa-ft{display:flex;gap:2px;margin-left:-6px;}',
    '.wa-ft button{width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:var(--muted);}',
    '.wa-ft button:hover{background:var(--soft-3);color:var(--ink-2);}',
    '.wa-ft svg{width:15px;height:15px;}',
    '.wa-ask{align-self:stretch;display:flex;flex-direction:column;gap:8px;padding:12px 14px;border:1px solid #D9DEF7;border-radius:14px;background:#F7F8FF;}',
    '.wa-ask .q{display:flex;align-items:flex-start;gap:8px;font-size:14px;line-height:21px;font-weight:600;color:var(--ink);}',
    '.wa-ask .q svg{width:18px;height:18px;flex-shrink:0;margin-top:1px;color:var(--primary);}',
    '.wa-ask .cs,.wa-af-cs{display:flex;flex-wrap:wrap;gap:6px;}',
    '.wa-ask .cs{padding-left:26px;}',
    '.wa-ask .c,.wa-af-cs .c{padding:2px 10px;border:1px solid #D5DBF7;border-radius:9999px;background:#fff;font-size:12px;line-height:18px;color:var(--ink-2);}',
    '.wa-ask .h{padding-left:26px;font-size:12px;line-height:18px;color:var(--muted);}',
    /* 추가 확인 폼 카드(메인 채팅의 '추가 확인이 필요합니다') / the details form card (the main chat's clarify card) */
    '.wa-af{align-self:stretch;display:flex;flex-direction:column;gap:10px;padding:14px 16px;border:1px solid var(--border);border-radius:16px;background:#fff;box-shadow:0 1px 3px rgba(16,24,40,.06);}',
    '.wa-af-t{font-size:13px;line-height:18px;font-weight:700;color:var(--primary);}',
    '.wa-af-q{display:flex;gap:6px;font-size:14px;line-height:21px;font-weight:600;color:var(--ink);}',
    '.wa-af-os{display:flex;flex-direction:column;gap:6px;}',
    '.wa-af-o{display:flex;align-items:center;gap:10px;width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:10px;background:#fff;text-align:left;font-size:13.5px;line-height:19px;color:var(--ink);}',
    '.wa-af-o:hover{background:#F8F9FD;}',
    '.wa-af-o .rd{flex-shrink:0;width:16px;height:16px;border-radius:50%;border:1.5px solid #C3C7D2;}',
    '.wa-af-o.on{border-color:var(--primary);background:var(--primary-soft);color:var(--primary);}',
    '.wa-af-o.on .rd{border:5px solid var(--primary);}',
    '.wa-af-in{width:100%;height:40px;padding:0 12px;border:1px solid var(--border);border-radius:10px;font-size:13.5px;color:var(--ink);outline:none;}',
    '.wa-af-in:focus{border-color:var(--primary);box-shadow:0 0 0 3px rgba(68,80,206,.12);}',
    '.wa-af-h{font-size:12px;line-height:18px;color:var(--muted);}',
    '.wa-af-er{font-size:12.5px;line-height:18px;color:var(--danger);}',
    '.wa-af-ft{display:flex;justify-content:flex-end;}',
    '.wa-af-go{height:34px;padding:0 20px;border-radius:9999px;background:var(--primary);color:#fff;font-size:13px;font-weight:600;}',
    '.wa-af-go:hover{background:var(--primary-hover);}',
    /* 첫 화면 = 아이콘 · 인사 · 예시 카드(아이콘 + 요청 + 무엇을 보여 주는지), 누르면 입력 카드에 채우기만 한다
       the first screen: an icon, a greeting and starter cards (icon, request, what it shows); a click only fills the input card */
    '.wa-hello{margin:auto;width:100%;max-width:640px;display:flex;flex-direction:column;align-items:center;gap:6px;padding:16px 4px;text-align:center;}',
    '.wa-hello-ic{width:46px;height:46px;margin-bottom:8px;border-radius:14px;display:flex;align-items:center;justify-content:center;background:var(--primary-soft);color:var(--primary);}',
    '.wa-hello-ic svg{width:22px;height:22px;}',
    '.wa-hello .t{font-size:20px;line-height:28px;font-weight:700;color:var(--ink);}',
    '.wa-hello .s{font-size:13.5px;line-height:20px;color:var(--muted);}',
    '.wa-hello .h{font-size:12.5px;line-height:18px;color:var(--ink-3);}',
    '.wa-ex{width:100%;display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin-top:18px;}',
    '.wa-ex button{display:flex;align-items:flex-start;gap:10px;padding:12px 14px;border:1px solid #E6E8EF;border-radius:14px;background:#fff;text-align:left;transition:border-color .15s,background-color .15s;}',
    '.wa-ex button:hover{border-color:#B9C0F2;background:#FAFBFF;}',
    '.wa-ex button:focus-visible{outline:2px solid var(--primary);outline-offset:2px;}',
    '.wa-ex .ic{flex-shrink:0;width:30px;height:30px;border-radius:9px;display:flex;align-items:center;justify-content:center;background:#F1F3F9;color:var(--ink-3);transition:background-color .15s,color .15s;}',
    '.wa-ex button:hover .ic{background:var(--primary-soft);color:var(--primary);}',
    '.wa-ex .ic svg{width:16px;height:16px;}',
    '.wa-ex .tx{display:flex;flex-direction:column;gap:2px;min-width:0;}',
    '.wa-ex .q{font-size:13.5px;line-height:19px;font-weight:600;color:var(--ink);}',
    '.wa-ex .c{font-size:12px;line-height:17px;color:var(--muted);}',
    /* 대기 요청 = 메인 채팅의 Queue 상자(연한 파랑 · 선 · 모서리 16, 줄 = 손잡이 · 글 · 지나갈 때 ✎ ✕) / queued requests = the main chat's Queue box */
    '.wa-q{flex:none;width:calc(100% - 24px);max-width:800px;box-sizing:border-box;margin:0 auto 10px;padding:5px 7px;border:1px solid var(--border-2);border-radius:16px;background:var(--primary-soft);}',
    '.wa-q[hidden]{display:none;}',
    '.wa-q-hd{display:flex;align-items:center;justify-content:space-between;width:100%;padding:6px 10px;font-size:14px;line-height:20px;font-weight:600;color:var(--ink-2);}',
    '.wa-q-hd svg{width:14px;height:14px;color:var(--muted);transition:transform .15s;}',
    '.wa-q.fold .wa-q-hd svg{transform:rotate(180deg);}',
    '.wa-q.fold .wa-q-r{display:none;}',
    '.wa-q-r{display:flex;align-items:center;gap:8px;padding:7px 10px;border-radius:9px;font-size:14px;line-height:20px;color:var(--ink);}',
    '.wa-q-r:hover{background:var(--soft-2);}',
    '.wa-q-g{flex-shrink:0;display:inline-flex;color:var(--muted);}',
    '.wa-q-g svg{width:13px;height:13px;}',
    '.wa-q-tx{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.wa-q-r .sc{flex-shrink:0;font-size:12px;font-weight:600;color:var(--primary);}',
    '.wa-q-r button{flex-shrink:0;opacity:0;padding:2px;display:inline-flex;align-items:center;color:var(--ink-2);}',
    '.wa-q-r:hover button,.wa-q-r button:focus-visible{opacity:1;}',
    '.wa-q-r button:hover{color:var(--primary);}',
    '.wa-q-r svg{width:13px;height:13px;}',
    /* 입력 카드 = 메인 채팅 입력창(Dev ChatInput · ChatUploadFile · ChatResourceButton · ChatSendButton)과 같은 값: 카드 모서리 24 · 선 #CDD1DC ·
       안쪽 16 · 그림자, 글 칸 16/22, [+] 40 원 · 알약 40 · 16px 600 · 마이크 40(아이콘 24) · 보내기 40(종이비행기 20, 작업 중 흰 사각)
       the input card uses the main chat composer's values: radius 24, an #CDD1DC line, 16 padding and its shadow; 16/22 text; the [+] circle,
       pills, mic and send at 40 */
    '.wa-cmp{position:relative;flex:none;width:calc(100% - 24px);max-width:800px;margin:0 auto 12px;display:flex;flex-direction:column;padding:16px;border:1px solid #CDD1DC;border-radius:24px;background:#fff;box-shadow:0 10px 15px -3px rgba(0,0,0,.1),0 4px 6px -4px rgba(0,0,0,.1);transition:border-color .15s;}',
    '.wa-in{display:block;width:100%;min-height:34px;max-height:166px;resize:none;padding:6px 2px;border:0;outline:0;background:transparent;font:inherit;font-size:16px;line-height:22px;color:var(--ink);}',
    '.wa-in::placeholder{color:var(--muted);}',
    '.wa-cmp-row{display:flex;align-items:center;gap:6px;padding-top:10px;}',
    '.wa-cmp-sp{flex:1;min-width:0;}',
    '.wa-cb{flex-shrink:0;width:40px;height:40px;border:1px solid #CDD1DC;border-radius:9999px;background:#fff;color:var(--ink);display:flex;align-items:center;justify-content:center;transition:background .13s,border-color .13s,transform .13s;}',
    '.wa-cb svg{width:24px;height:24px;stroke-width:1.5;}',
    '.wa-cb:hover,.wa-cb.on{background:#EDF1FA;border-color:#C3C7D2;}',
    '.wa-cb:active{background:var(--border-2);border-color:#AFB3BE;transform:scale(.92);}',
    '.wa-pb{flex-shrink:1;min-width:0;height:40px;display:inline-flex;align-items:center;gap:4px;padding:0 10px;border:1px solid #CDD1DC;border-radius:9999px;background:#fff;color:var(--ink);font-size:14px;line-height:20px;font-weight:600;white-space:nowrap;transition:background .13s,border-color .13s,transform .13s;}',
    '.wa-pb[hidden]{display:none;}',
    '.wa-pb svg{flex-shrink:0;width:16px;height:16px;stroke-width:1;}',
    '.wa-pb-tx{min-width:0;overflow:hidden;text-overflow:ellipsis;}',
    '.wa-pb .ri{width:20px;height:20px;stroke-width:1.6;}',
    '.wa-pb:hover:not(.on){background:#EDF1FA;border-color:#C3C7D2;}',
    '.wa-pb:active:not(.on){background:var(--border-2);border-color:#AFB3BE;transform:scale(.92);}',
    '.wa-pb.on{border-color:var(--primary);background:var(--primary-soft);color:var(--primary);}',
    '.wa-mic{flex-shrink:0;width:40px;height:40px;border-radius:9999px;background:transparent;color:var(--ink-2);display:flex;align-items:center;justify-content:center;}',
    '.wa-mic svg{width:24px;height:24px;stroke-width:1.5;}',
    '.wa-mic:hover{color:var(--primary);}',
    '.wa-send{flex-shrink:0;width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:var(--primary);color:#fff;transition:background .12s,transform .1s;}',
    '.wa-send:hover{background:var(--primary-hover);}',
    '.wa-send:active{background:var(--primary-active);transform:scale(.96);}',
    '.wa-send svg{width:20px;height:20px;}',
    '.wa-send.stop svg{width:32px;height:32px;}',
    /* [+] 메뉴 = 메인 채팅의 + 메뉴(흰 바탕 · 모서리 12 · 그림자 · 안쪽 4, 줄 32 · 14px · 아이콘 · › 하위 메뉴, 뒤로 줄) / the [+] menu = the main chat's + menu */
    '.wa-pop.am{position:fixed;z-index:1200;min-width:208px;max-width:300px;max-height:340px;overflow-y:auto;padding:4px;border:0;border-radius:12px;background:#fff;box-shadow:var(--shadow-pop);}',
    '.wa-mi{width:100%;display:flex;align-items:center;gap:6px;min-height:32px;padding:6px;margin-bottom:2px;border-radius:6px;font-size:14px;line-height:20px;color:var(--ink-2);text-align:left;transition:background .12s,color .12s;}',
    '.wa-mi:hover,.wa-mi:focus-visible{background:var(--sidebar-bg);color:var(--ink);outline:none;}',
    '.wa-mi:active{background:var(--border-2);}',
    '.wa-mi > svg{width:16px;height:16px;flex-shrink:0;color:var(--ink-3);}',
    '.wa-mi > span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
    '.wa-mi .cv{margin-left:auto;display:inline-flex;color:var(--muted);}',
    '.wa-mi .cv svg{width:14px;height:14px;}',
    '.wa-mi .id{margin-left:auto;padding-left:8px;flex-shrink:0;font:10.5px/16px ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--muted);}',
    '.wa-mi.back{color:var(--ink-3);font-weight:600;}',
    '.wa-am-none{padding:10px 8px;font-size:13px;color:var(--muted);}',
    /* 리소스 선택 창(메인 채팅의 '리소스 선택'과 같은 꼴, 고르는 단위 = 지식 관리 · 데이터 분석) / the resource dialog (the main chat's look; picks knowledge or data) */
    '.wa-rs{width:560px;max-width:calc(100vw - 32px);border-radius:16px;background:#fff;box-shadow:var(--shadow-pop);overflow:hidden;}',
    '.wa-rs-hd{display:flex;align-items:flex-start;gap:12px;padding:22px 24px 16px;border-bottom:1px solid #E6E8EF;}',
    '.wa-rs-hd .t{font-size:18px;line-height:26px;font-weight:700;color:var(--ink);}',
    '.wa-rs-hd .s{margin-top:4px;font-size:13px;line-height:19px;color:var(--muted);}',
    '.wa-rs-hd .x{margin-left:auto;width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center;color:var(--ink-2);}',
    '.wa-rs-hd .x:hover{background:var(--soft-3);}',
    '.wa-rs-hd .x svg{width:18px;height:18px;}',
    '.wa-rs-bd{display:flex;flex-direction:column;gap:12px;padding:20px 24px;}',
    '.wa-rs-r{display:flex;align-items:center;gap:12px;min-height:56px;padding:0 18px;border:1px solid #CDD1DC;border-radius:12px;cursor:pointer;}',
    '.wa-rs-r:hover{background:#F8F9FD;}',
    '.wa-rs-r input{width:18px;height:18px;margin:0;accent-color:var(--primary);flex-shrink:0;}',
    '.wa-rs-r .ic{display:flex;color:var(--ink-2);}',
    '.wa-rs-r .ic svg{width:20px;height:20px;stroke-width:1.6;}',
    '.wa-rs-r .n{font-size:15px;font-weight:600;color:var(--ink);}',
    '.wa-rs-r .b{padding:1px 8px;border-radius:9999px;background:var(--primary-soft);font-size:11.5px;line-height:17px;font-weight:600;color:var(--primary);}',
    '.wa-rs-r .d{margin-left:auto;font-size:12.5px;color:var(--muted);}',
    '.wa-rs-h{font-size:12px;color:var(--muted);}',
    '.wa-rs-ft{display:flex;align-items:center;justify-content:space-between;padding:14px 24px 18px;border-top:1px solid #E6E8EF;}',
    '.wa-rs-ft button{height:32px;padding:0 20px;border-radius:9999px;font-size:13px;font-weight:600;}',
    '.wa-rs-ft .no{border:1px solid #CDD1DC;background:#fff;color:var(--ink-2);}',
    '.wa-rs-ft .ok{background:var(--primary);color:#fff;}',
    '.wa-rs-ft .ok:hover{background:var(--primary-hover);}',

    '.wa-ov{position:fixed;inset:0;z-index:250;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.3);}',
    '.wa-dlg{width:340px;max-width:calc(100vw - 32px);padding:20px;border-radius:12px;background:#fff;box-shadow:var(--shadow-pop);}',
    '.wa-dlg-tt{margin-bottom:6px;font-size:14px;line-height:22px;font-weight:700;color:var(--ink);}',
    '.wa-dlg-bd{font-size:12.5px;line-height:18px;color:#52545F;}',
    '.wa-dlg-act{display:flex;justify-content:flex-end;gap:8px;margin-top:16px;}',
    '.wa-dlg-act button{height:34px;padding:0 16px;border-radius:8px;font-size:12.5px;font-weight:600;}',
    '.wa-dlg-act .no{background:var(--table-head);color:var(--ink-2);}',
    '.wa-dlg-act .ok{background:#E35B62;color:#fff;}',
  ].join('\n');

  // 일반 낱말(도구 묶음 · '도구' · '열기')은 홈 전체 사전(home-live.js) 대신 여기서 번역한다: 사전에 넣으면 홈의 사용자 데이터(컬렉션 이름 '데이터' 등)까지 바뀐다.
  // 그린 자리는 data-i18n-skip 이다 / generic words (tool groups, '도구', '열기') are translated here rather than in the home-wide dictionary, which would also
  // rewrite user data on the home (a collection named '데이터'); the spots drawn with them carry data-i18n-skip
  const WORDS_EN = { '리포트': 'Report', '디자인': 'Design', '기준선': 'Reference lines', '계산 값': 'Calculations', '강조': 'Highlights', '추세·예측': 'Trends',
    '필터': 'Filters', 'KPI 카드': 'KPI cards', '정리': 'Organize', '데이터': 'Data', '기타': 'Other', '도구': 'Tools', '열기': 'Open', '새로 시작': 'Start new' };
  function isEn() { try { return typeof window.AI365_homeLangIs === 'function' && window.AI365_homeLangIs() === 'en'; } catch (e) { return false; } }
  function L(ko) { return isEn() && WORDS_EN[ko] ? WORDS_EN[ko] : ko; }

  const W = { built: false, owner: '', key: '', widget: waBlank(), model: waBlankModel(), saved: null, savedAt: '', msgs: [], undo: [],
    busy: false, wait: 0, mine: null, tools: null, menu: '', seq: 0, renaming: false, draft: null, live: null, ctrl: null, stopped: false,
    scope: 'auto', res: [], group: '', queue: [], qfold: false, label: waLabel('new', ''), at: '', peek: null, open: {}, fold: {}, refreshing: false,
    askForm: { mi: -1, opt: '', text: '', err: '' }, nid: 0, chatOk: true, shown: false, tab: 'chat', syncing: false, hold: false, sizeRun: false, want: '', goneKey: '' };
  let root = null;

  function owner() {
    try { const a = window.parent && window.parent.AI365_ACTING_USER; return a && a.no != null ? String(a.no) : ''; } catch (e) { return ''; }
  }
  function busy() { return W.busy || W.wait > 0; }
  function nowIso() {
    try { if (typeof window.ai365KstIso === 'function') return window.ai365KstIso(); } catch (e) {}
    return new Date().toISOString().slice(0, 19);
  }
  function newId() { return 'h' + Date.now().toString(36) + (++W.nid).toString(36); }
  function tr() { try { if (typeof window.AI365_homeLang === 'function') window.AI365_homeLang(); } catch (e) {} }
  function toast(msg) {
    const t = document.getElementById('toast');
    if (!t) return;
    t.textContent = msg; t.classList.add('show');
    clearTimeout(t._tm); t._tm = setTimeout(() => t.classList.remove('show'), 2600);
    tr();
  }
  // 실패는 Error 로: 서버가 준 문장(detail)이 있으면 그 문장, 없거나 네트워크 실패면 빈 메시지 / failures become Errors carrying the server's sentence, or an empty one
  function api(method, path, body) {
    const init = { method: method, headers: {} };
    if (body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
    return fetch(path, init).then(r => r.json().catch(() => null).then(d => {
      if (!r.ok) { const err = new Error(d && typeof d.detail === 'string' ? d.detail : ''); err.status = r.status; throw err; }
      return d;
    }), () => { throw new Error(''); });
  }
  // 이벤트 스트림 POST: 끝난 이벤트마다 onEvent({event, data}). 스트림을 열기 전의 실패(422 등)는 api 와 같은 Error, 도중에 끊기면 빈 메시지의 Error.
  // signal 로 멈춘다(멈추기 — 서버는 끊긴 것을 보고 턴을 멈춘다) / an event-stream POST; signal aborts it (stop — the server sees the drop and halts the turn)
  function stream(path, body, onEvent, signal) {
    const init = { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
    if (signal) init.signal = signal;
    return fetch(path, init).then(r => {
      if (!r.ok) {
        return r.json().catch(() => null).then(d => { const err = new Error(d && typeof d.detail === 'string' ? d.detail : ''); err.status = r.status; throw err; });
      }
      if (!r.body || typeof r.body.getReader !== 'function') return r.text().then(t => { waSseSplit(t + '\n\n').events.forEach(onEvent); });
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = '';
      const pump = () => reader.read().then(res => {
        if (res.value) buf += dec.decode(res.value, { stream: true });
        if (res.done) buf += dec.decode() + '\n\n';
        const cut = waSseSplit(buf);
        buf = cut.rest;
        cut.events.forEach(onEvent);
        return res.done ? null : pump();
      });
      return pump().catch(() => { throw new Error(''); });
    }, () => { throw new Error(''); });
  }
  function when(iso) { return String(iso || '').replace('T', ' ').slice(0, 16); }
  function hm(iso) { return String(iso || '').slice(11, 16); }
  function mdhm(iso) { const s = String(iso || ''); return s.length >= 16 ? s.slice(5, 7) + '/' + s.slice(8, 10) + ' ' + s.slice(11, 16) : ''; }
  function dirty() { return waDirty(W.widget, W.saved); }
  function $(sel) { return root.querySelector(sel); }
  function srcName(s) { return U('src_' + s); }
  function chartName(t) { return UI['ch_' + t] ? U('ch_' + t) : String(t || ''); }
  function viewText(v) {
    const parts = [];
    if (v.chart && v.chart !== 'kpi') parts.push(chartName(v.chart));
    if (v.kpis) parts.push(U('kpiN', { n: v.kpis }));
    if (v.text) parts.push(U('textPart'));
    if (v.list) parts.push(U('listN', { n: v.list }));
    return parts.join(' + ') || U('emptyView');
  }
  function uniq(a) { return a.filter((x, i) => x && a.indexOf(x) === i); }
  function labelText(lbl) {
    const s = String(lbl || ''), i = s.indexOf(':'), kind = i < 0 ? 'turn' : s.slice(0, i), text = i < 0 ? s : s.slice(i + 1);
    if (kind === 'new') return U('hNew');
    if (kind === 'opened') return U('hOpened');
    if (kind === 'rename') return U('hRename', { t: text });
    if (kind === 'size') { const p = text.split('x'); return U('hSize', { w: p[0] || '', h: p[1] || '' }); }
    if (kind === 'refresh') return U('hRefresh');
    if (kind === 'restore') return U('hRestore', { l: labelText(text) });
    return text;
  }

  /* ── 틀 / frame ── */
  function HD() { return window.AI365_homeDash || null; }
  function build() {
    const style = document.createElement('style');
    style.id = 'waCss'; style.textContent = CSS;
    document.head.appendChild(style);
    root = document.createElement('section');
    root.className = 'wa'; root.id = 'waView';
    root.setAttribute('aria-label', TX.agent);
    // 이름은 title 로만: 사전이 title 은 영어로 바꾸지만 aria-label 은 바꾸지 못한다(독립 검토) / named by title only: the dictionary translates title but not aria-label
    const ib = (k, ic, label, more) => '<button type="button" class="wa-ib" data-wa="' + k + '" title="' + label + '"' + (more || '') + '>' + ic + '</button>';
    root.innerHTML =
      // 머리: 위젯 이름(연필 = 이름 바꾸기) · [내 위젯] · [새 위젯] · [되돌리기] · [닫기] / the head: the widget name (pen = rename), [My widgets], [New widget], [Undo], [Close]
      '<div class="wa-hd"><span class="wa-av" aria-hidden="true">' + ICON.spark + '</span><div class="wa-nm" id="waNm"></div>' +
      '<div class="wa-mine">' + ib('mine', ICON.list, TX.mine, ' aria-haspopup="true"') + '</div>' + ib('new', ICON.plus, TX.fresh) + ib('undo', ICON.undo, TX.undo) + ib('close', ICON.x, TX.close) + '</div>' +
      // 탭: 대화 · 정보(홈에서의 크기 · 출처 · 새로 가져오기 · 지우기) · 기록, 오른쪽 = 홈에 반영된 상태(반영하지 못했으면 눌러 다시 저장)
      // tabs: chat, info (size on Home, sources, refresh, delete) and history; on the right the applied state (a button to save again when it failed)
      '<div class="wa-tabs" data-i18n-skip><div role="tablist">' + ['chat', 'info', 'hist'].map(t => '<button type="button" class="wa-tab" role="tab" data-wa-tab="' + t + '"></button>').join('') +
      '</div><span class="sp"></span><button type="button" class="wa-st" id="waSt" data-wa="resave" hidden></button></div>' +
      '<div class="wa-note" id="waNote" hidden data-i18n-skip></div>' +
      '<div class="wa-peek" id="waPeek" hidden data-i18n-skip></div>' +
      '<div class="wa-pane" id="waPaneInfo" hidden data-i18n-skip></div><div class="wa-pane" id="waPaneHist" hidden data-i18n-skip></div>' +
      '<div class="wa-chat" id="waChat"><div class="wa-msgs" id="waMsgs" aria-live="polite"></div>' +
      '<div class="wa-q" id="waQ" hidden data-i18n-skip></div>' +
      // 입력 카드 = 메인 채팅 입력창: 위 = 글 칸(늘어난다), 아래 줄 = [+](도구 메뉴) · [자동 ▾](자동 → 사내 → 외부) · [리소스 센터](사내일 때) · 마이크 · 보내기
      // the input card = the main chat composer: text above; [+] (the tool menu), [Auto ▾] (auto → internal → external), [Resource Center] (internal), mic and send below
      '<div class="wa-cmp"><textarea class="wa-in" id="waIn" rows="1" placeholder="' + TX.placeholder + '"></textarea>' +
      '<div class="wa-cmp-row"><button type="button" class="wa-cb" data-wa="plus" aria-haspopup="true" data-i18n-skip>' + ICON.plus + '</button>' +
      '<button type="button" class="wa-pb" data-wa="scope" data-i18n-skip><span class="wa-pb-tx"></span>' + ICON.chev + '</button>' +
      '<button type="button" class="wa-pb" data-wa="res" hidden data-i18n-skip>' + ICON.res.replace('<svg ', '<svg class="ri" ') + '<span class="wa-pb-tx"></span></button>' +
      '<span class="wa-cmp-sp"></span><button type="button" class="wa-mic" data-wa="mic" data-i18n-skip>' + ICON.mic + '</button>' +
      '<button type="button" class="wa-send" data-wa="send" title="' + TX.send + '">' + ICON.plane + '</button></div></div></div>';
    // 홈 화면(#viewHome) 안에 둔다 — 다른 화면(Workspace)에서는 같이 숨는다 / lives inside the home view, so it hides with it
    (hero.parentNode || document.body).appendChild(root);
    root.addEventListener('click', onClick);
    root.addEventListener('keydown', onKey);
    root.addEventListener('input', onInput);
    // 바깥 클릭이면 메뉴를 닫는다 — 판정은 누른 순간의 경로로(묶음을 누르면 메뉴를 다시 그려 누른 단추가 문서에서 떨어진다, 4단계 서랍과 같은 함정)
    // an outside click closes the menu, judged by the path at click time (a group click redraws the menu and detaches the button, as with the phase-4 drawer)
    document.addEventListener('click', e => {
      if (!W.menu || !root) return;
      const path = typeof e.composedPath === 'function' ? e.composedPath() : [e.target];
      if (!path.some(n => n && n.nodeType === 1 && n.matches('.wa-pop,[data-wa="mine"],[data-wa="plus"]'))) closeMenu();
    });
    window.addEventListener('resize', () => { if (W.menu === 'plus') placePop(); });
    W.built = true;
    W.owner = owner();
  }
  // 글 칸 높이 = 한 줄 34(22 + 위아래 6) ~ 일곱 줄 166. 비어 있으면 안내 글(placeholder)이 다 들어갈 높이 — 영어처럼 긴 안내가 잘리지 않게
  // the text box height: one line (34 = 22 plus 6 above and below) to seven (166); when empty, tall enough for the whole placeholder
  function grow(ta) {
    const empty = !ta.value;
    if (empty) ta.value = ta.placeholder;
    ta.style.height = 'auto';
    const h = Math.min(166, Math.max(34, ta.scrollHeight));
    if (empty) ta.value = '';
    ta.style.height = h + 'px';
  }

  /* ── 그리기 / painting ── */
  // 번역(tr) 뒤에 글 칸 높이를 다시 잰다 — 안내 글이 영어로 바뀌면 길이가 달라진다 / the text box is measured again after translation (an English hint is longer)
  function paint(bottom) { paintBar(); paintSide(); paintChat(bottom); paintHome(); tr(); grow($('#waIn')); }
  function paintBar() {
    const nm = $('#waNm'), d = dirty(), b = busy();
    if (!W.renaming) {
      nm.innerHTML = '<span class="wa-nmtx" data-i18n-skip>' + E(W.widget.title) + '</span><button type="button" class="wa-ic" data-wa="rename" title="' + TX.rename + '">' + ICON.pen + '</button>';
    }
    // 상태 알약(탭 줄 오른쪽): 홈에 반영됨 + 시각. 반영하지 못했으면(저장 실패 · 내용 없음) 누르는 [다시 저장]
    // the status pill (right of the tabs): applied to Home with the time; a [save again] button when it could not be applied
    const st = $('#waSt'), unsaved = !b && d && (!!W.key || waHasContent(W.widget));
    st.hidden = b || (!unsaved && !W.key);
    st.classList.toggle('dirty', unsaved);
    st.disabled = !unsaved;
    st.textContent = unsaved ? U('stUnsaved') : (W.key ? U('stSaved', { t: when(W.savedAt).slice(5) }) : '');
    const input = $('#waIn');
    root.querySelectorAll('[data-wa="mine"],[data-wa="new"],[data-wa="rename"]').forEach(x => { x.disabled = b; });
    $('[data-wa="undo"]').disabled = b || !W.undo.length;
    // 그룹웨어 머리줄의 아이콘: 열려 있으면 켜짐, 닫은 채 일하는 중이면 점 / the header icon: on while open, a dot while working with the panel closed
    const hb = document.getElementById('waBtn');
    if (hb) { hb.classList.toggle('on', W.shown); hb.classList.toggle('busy', !W.shown && busy()); hb.setAttribute('aria-pressed', String(W.shown)); }
    // 보내기 = 메인 채팅처럼 늘 파란 원(빈 글이면 보내지 않을 뿐), 작업 중에는 ■ 멈추기(Enter 는 Queue 에 쌓는다)
    // send stays a blue circle like the main chat (an empty box simply sends nothing); while a turn runs it is ■ stop (Enter queues)
    const send = $('[data-wa="send"]'), stopping = W.busy && !!W.ctrl;
    if (send.classList.contains('stop') !== stopping) {
      send.classList.toggle('stop', stopping);
      send.innerHTML = stopping ? ICON.stopSq : ICON.plane;
    }
    send.title = stopping ? U('stop') : TX.send;
    send.setAttribute('aria-label', send.title);
    // [+] · [자동 ▾] · [리소스 센터] · 마이크 / [+], [Auto ▾], [Resource Center] and the mic
    const plus = $('[data-wa="plus"]');
    plus.title = U('plusTitle'); plus.setAttribute('aria-label', plus.title);
    const sc = $('[data-wa="scope"]');
    sc.querySelector('.wa-pb-tx').textContent = U('sc_' + W.scope);
    const rs = $('[data-wa="res"]'), picked = W.res.filter(k => k === 'data' || k === 'docs');
    rs.hidden = W.scope !== 'internal';
    rs.classList.toggle('on', picked.length === 1);
    rs.querySelector('.wa-pb-tx').textContent = picked.length === 1 ? U('res_' + picked[0]) : U('resCenter');
    const mic = $('[data-wa="mic"]');
    mic.title = U('mic'); mic.setAttribute('aria-label', mic.title);
    input.disabled = false;
    paintQueue();
  }

  // 홈에 놓인 칸(없으면 null) · 크기 칸에 보일 크기: 홈에 놓였고 반영이 끝났으면 놓인 크기, 아니면 고른 크기 → 처음 크기
  // the placed cell (or null) and the size the cells show: the placed size once applied, otherwise the picked size, then the first size
  function placed() {
    try { const g = HD() && HD().geometry; return W.key && g ? g(0, W.key).placed : null; } catch (e) { return null; }
  }
  function curSize() {
    const p = placed(), s = waSizeOf(W.widget, p);
    return p && !dirty() && !W.syncing ? { w: p.w, h: p.h, picked: s.picked, placed: true } : s;
  }
  /* 홈에 그리기(2026-11-20, 14절): 미리보기가 따로 없다 — 홈 격자의 그 위젯 자리에 지금 보여 줄 모습을 그린다. 지난 모습 미리보기 > 찾는 동안의 초안 >
     아직 홈에 반영되지 않은 작업본 차례이고, 다 반영됐으면 홈의 것을 그대로 둔다. 아직 없는 새 위젯은 빈 첫 자리의 점선 카드로.
     drawing on Home (2026-11-20, section 14): no separate preview — the widget's own cell shows a history preview, else the draft of a running
     turn, else a working copy not applied yet; once applied the home's own drawing stays. A widget not made yet is a dashed card at the first free spot */
  function paintHome() {
    const hd = HD();
    if (!hd || !hd.preview) return;
    const peek = W.peek && W.peek.model ? W.peek.model : null, draft = W.busy && W.draft ? W.draft : null;
    const name = peek ? (peek.title || '') : (draft && draft.title ? draft.title : W.widget.title);
    if (W.key) {
      // 방금 만든 위젯이 홈에 놓일 때까지는 점선 카드를 그대로 둔다(그 사이 빈 자리가 번쩍이지 않게, 독립 검토)
      // a just-made widget keeps its dashed card until it is placed (no empty flash in between; independent review)
      if (W.syncing && !placed() && !W.model.empty) hd.ghost(W.model, name, waSizeOf(W.widget, null));
      else hd.ghost(null);
      const m = peek || draft || (dirty() || W.syncing ? W.model : null);
      if (hd.previewOf(W.key) !== m) hd.preview(W.key, m, name);
      hd.focus(W.shown || W.busy ? W.key : '');
    } else {
      hd.preview('', null);
      const m = peek || draft || (waHasContent(W.widget) && !W.hold ? W.model : null);   // 지워진 위젯의 작업본은 그리지 않는다 / a deleted widget's copy is not drawn
      if (m && !m.empty) hd.ghost(m, name, waSizeOf(W.widget, null));
      else hd.ghost(null);
      hd.focus('');
    }
  }
  function sizeHtml() {
    const sz = curSize(), off = busy() || !!W.peek;
    const grp = (dim, cur) => '<span class="g" role="group" aria-label="' + E(U(dim === 'w' ? 'wide' : 'tall')) + '">' + [1, 2, 3].map(n =>
      '<button type="button" data-wa-size="' + dim + ':' + n + '" aria-pressed="' + (cur === n) + '"' + (cur === n ? ' class="on"' : '') + (off ? ' disabled' : '') + '>' + n + '</button>').join('') + '</span>';
    return '<section class="wa-pnl"><div class="wa-pnl-t">' + ICON.size + '<span>' + E(U('sizeGroup')) + '</span></div><div class="wa-size" id="waSize" aria-label="' + E(U('sizeGroup')) + '">' +
      '<span>' + E(U('wide')) + '</span>' + grp('w', sz.w) + '<span>' + E(U('tall')) + '</span>' + grp('h', sz.h) + '</div><p class="wa-size-h">' + E(U(placed() ? 'sizeNote' : 'sizeNoteNew')) + '</p></section>';
  }
  function paintPeek() {
    const box = $('#waPeek');
    if (!W.peek) { box.hidden = true; box.innerHTML = ''; return; }
    box.hidden = false;
    box.innerHTML = '<span>' + E(U('peekAt', { label: labelText(W.peek.label) })) + '</span><button type="button" class="pri" data-wa-act="restore">' + E(U('restore')) +
      '</button><button type="button" data-wa-act="peek-close">' + E(U('close')) + '</button>';
  }
  // 홈에 없는 위젯(배치 편집에서 뺐다 · 놓지 못했다): 알리고 [홈에 놓기] / a widget off Home (removed in layout editing, or not placed): say so and offer [Put on Home]
  function offHome() {
    const hd = HD();
    try { return !!(W.key && hd && hd.state && hd.state() && !placed() && !W.syncing); } catch (e) { return false; }
  }
  function paintNote() {
    const box = $('#waNote'), off = offHome();
    box.hidden = !off;
    box.innerHTML = off ? '<span>' + E(U('offHome')) + '</span><button type="button" data-wa-act="put-home"' + (busy() ? ' disabled' : '') + '>' + E(U('putHome')) + '</button>' : '';
  }
  // 탭 · 알림 줄 · 정보(크기 · 위젯 정보 · 지우기) · 기록 / tabs, notice rows, info (size, widget info, delete) and history
  function paintSide() {
    root.querySelectorAll('[data-wa-tab]').forEach(t => {
      const on = t.dataset.waTab === W.tab;
      t.classList.toggle('on', on); t.setAttribute('aria-selected', String(on));
      t.textContent = U('tab_' + t.dataset.waTab);
    });
    $('#waChat').hidden = W.tab !== 'chat';
    const info = $('#waPaneInfo'), hist = $('#waPaneHist');
    info.hidden = W.tab !== 'info'; hist.hidden = W.tab !== 'hist';
    paintNote(); paintPeek();
    info.innerHTML = W.tab !== 'info' ? '' : sizeHtml() + '<section class="wa-pnl" id="waInfo">' + infoHtml() + '</section>' +
      (W.key ? '<button type="button" class="wa-del" data-wa-act="delete"' + (busy() ? ' disabled' : '') + '>' + ICON.trash + '<span>' + E(U('del')) + '</span></button>' : '');
    hist.innerHTML = W.tab !== 'hist' ? '' : '<section class="wa-pnl" id="waHist">' + histHtml() + '</section>';
  }
  function infoHtml() {
    const w = W.widget, info = waInfo(w), v = waViewOf(w), sz = curSize();
    const row = (k, val) => '<div class="wa-pnl-r"><span>' + E(U(k)) + '</span><span>' + val + '</span></div>';
    const origin = info.rows.length ? info.rows.map(r => {
      const first = r.refs[0] ? r.refs[0].label : '';
      const what = r.kind === 'docs' ? U('refsN', { n: r.refs.length }) : first;
      return '<span class="o">' + E((UI['pt_' + r.part] ? U('pt_' + r.part) : r.part) + ' · ' + srcName(r.kind) + (what ? ' · ' + what : '')) + '</span>';
    }).join('') : E(waHasContent(w) ? U('iManual') : U('iNone'));
    const every = info.kinds.length ? info.kinds.map(k => U('ttl_' + k)).join(' · ') : U('iNoRefresh');
    const compose = viewText(v) + (w.insight ? ' · ' + U('iInsight') : '');
    const size = U('iSizeVal', { w: sz.w, h: sz.h }) + (placed() ? ' · ' + U('iPlaced') : '');
    const go = info.kinds.length ? '<button type="button" class="wa-pnl-go" data-wa-act="refresh"' + (busy() ? ' disabled' : '') + '>' + ICON.refresh + '<span>' +
      E(W.refreshing ? U('refreshing') : U('refreshNow')) + '</span></button>' : '';
    return '<div class="wa-pnl-t" id="waInfoT">' + ICON.info + '<span>' + E(U('info')) + '</span></div>' + row('iOrigin', origin) +
      row('iAt', E(info.latest ? mdhm(info.latest) : '—')) + row('iRefresh', E(every)) + row('iCompose', E(compose)) + row('iSize', E(size)) + go;
  }
  function histHtml() {
    const rows = [{ id: 'now', label: W.label, at: W.at, now: true }].concat(W.undo.slice().reverse());
    const off = busy();
    const list = rows.map(r => {
      const on = W.peek && W.peek.id === r.id, cur = r.now && !W.peek;
      return '<button type="button" data-wa-hist="' + E(r.id) + '"' + (on ? ' class="on"' : (cur ? ' class="cur"' : '')) + (off ? ' disabled' : '') + ' aria-pressed="' + (!!on || cur) + '">' +
        '<span class="dot"></span><span class="l">' + E(labelText(r.label)) + '</span>' + (r.at ? '<span class="t">' + E(hm(r.at)) + '</span>' : '') +
        (r.now ? '<span class="now">' + E(U('now')) + '</span>' : '') + '</button>';
    }).join('');
    return '<div class="wa-pnl-t">' + ICON.hist + '<span>' + E(U('hist')) + '</span><span class="sub">' + E(W.undo.length ? U('histHint') : U('histEmpty')) + '</span></div>' +
      '<div class="wa-hs">' + list + '</div>';
  }

  /* 대화 / the conversation */
  const AV = '<span class="wa-av" aria-hidden="true">' + ICON.spark + '</span>';
  function lineHtml(st, text, skip) {
    const ic = st === 'run' ? ICON.pend : st === 'fail' ? ICON.fail : st === 'ok' ? ICON.check : ICON.minus;
    return '<div class="wa-ln ' + st + '">' + ic + '<span' + (skip ? ' data-i18n-skip' : '') + '>' + E(text) + (st === 'run' ? '…' : '') + '</span></div>';
  }
  function hasDetail(src, nt) { return !!(nt && ((nt.refs && nt.refs.length) || (src === 'data' && nt.sql))); }
  function detailHtml(src, nt) {
    const refs = (nt.refs || []).map(r => {
      const t = r.label + (r.page ? ' · p.' + r.page : '');
      return '<li>' + (/^https?:\/\//i.test(r.url || '') ? '<a href="' + E(r.url) + '" target="_blank" rel="noopener noreferrer">' + E(t) + '</a>' : E(t)) + '</li>';
    }).join('');
    let h = refs ? '<ul>' + refs + '</ul>' : '';
    if (src === 'data' && nt.columns && nt.columns.length) h += '<b>' + E(U('columns')) + '</b><div>' + E(nt.columns.join(', ')) + '</div>';
    if (src === 'data' && nt.sql) h += '<b>' + E(U('sql')) + '</b><pre>' + E(nt.sql) + '</pre>';
    return '<div class="wa-kc-dt">' + h + '</div>';
  }
  function cardHtml(f, src, key, stopped) {
    const c = f.cards[src], nt = c.note || {}, lines = [];
    let sub = '';
    if (c.status === 'run' && stopped) {
      sub = U('subStop');
      lines.push(lineHtml('fail', U('lineStop')));
    } else if (c.status === 'run') {
      sub = U('subRun');
      lines.push(lineHtml('run', U(c.fallback && src === 'web' ? 'webFallback' : 'run_' + src)));
    } else if (c.status === 'fail') {
      sub = U(nt.skipped ? 'subSkipped' : 'subFail');
      lines.push(nt.skipped ? lineHtml('done', U('skipped')) : lineHtml('fail', U('failWhy', { why: nt.why || '' }), true));
    } else {
      const refs = Array.isArray(nt.refs) ? nt.refs : [];
      if (src === 'docs') {
        const docs = uniq(refs.map(r => r.label)), pages = uniq(refs.filter(r => r.page).map(r => 'p.' + r.page));
        sub = U('subDocs', { d: docs.length, p: refs.length });
        lines.push(lineHtml('done', U('docsFound')));
        if (pages.length) lines.push(lineHtml('done', U('docsPages', { pages: pages.slice(0, 5).join(', ') })));
        if (docs.length) lines.push(lineHtml('done', U('docsRefs', { n: refs.length, first: docs[0], more: docs.length > 1 ? U('more', { k: docs.length - 1 }) : '' }), true));
      } else if (src === 'data') {
        const tables = uniq(refs.map(r => r.label));
        sub = U('subRows', { rows: nt.rows || 0 });
        lines.push(lineHtml('done', U('dataFound', { tables: tables.join(', ') || srcName('data'), rows: nt.rows || 0 }), true));
      } else {
        const sites = uniq(refs.map(r => r.label));
        sub = U('subExt', { n: sites.length });
        lines.push(lineHtml('done', nt.live ? U('webLive', { site: sites[0] || srcName('web') }) : U('webFound', { n: sites.length || 1 }), true));
      }
      if (nt.note) lines.push(lineHtml('done', nt.note, true));
      const used = (f.picks || []).filter(x => x !== 'none');
      if (used.length) lines.push(lineHtml('done', U(used.indexOf(src) >= 0 ? 'pickedThis' : 'pickedOther')));
    }
    const k = key + ':' + src, open = !!W.open[k], more = c.status === 'ok' && hasDetail(src, nt);
    return '<div class="wa-kc ' + E(src) + '"><div class="wa-kc-hd"><span class="wa-kc-ic">' + ICON[SRC_IC[src]] + '</span><span class="wa-kc-tx"><b>' + E(srcName(src)) +
      '</b><i>' + E(sub) + '</i></span>' + (more ? '<button type="button" class="wa-kc-more" data-wa-more="' + E(k) + '" aria-expanded="' + open + '">' + E(U('details')) + ICON.chev + '</button>' : '') +
      '</div><div class="wa-kc-bd">' + lines.join('') + (open && more ? detailHtml(src, nt) : '') + '</div></div>';
  }
  function editHtml(f) {
    return '<div class="wa-kc edit"><div class="wa-kc-hd"><span class="wa-kc-ic">' + ICON.tool + '</span><span class="wa-kc-tx"><b>' + E(U('edit')) + '</b><i>' +
      E(U('toolsN', { n: f.tools.length })) + '</i></span></div><div class="wa-kc-bd">' + f.tools.map(t => {
      const note = t.ok ? t.say : t.detail;
      // 도구 이름(서버의 한국어 이름)은 사전이 바꾸도록 따로, 문장 · 도구 id 는 그대로 / the tool label stays a dictionary node; sentences and ids stay as they are
      return '<div class="wa-ln ' + (t.ok ? 'ok' : 'fail') + '">' + (t.ok ? ICON.check : ICON.fail) + '<span><span class="lb">' + E(t.label || t.tool) + '</span>' +
        (note ? '<span data-i18n-skip> — ' + E(note) + '</span>' : '') + '<code data-i18n-skip>' + E(t.tool) + '</code></span></div>';
    }).join('') + '</div></div>';
  }
  function treeHtml(f, key, live, stopped) {
    const k = key + ':tree', fold = !!W.fold[k];
    let nth = 0;   // n 번째 데이터 가져오기 = n 번째로 쓴 곳 / the n-th fetch matches the n-th place used
    return '<div class="wa-tk' + (fold ? ' fold' : '') + '"><button type="button" class="wa-tk-hd" data-wa-tk="' + E(k) + '" aria-expanded="' + !fold + '">' + ICON.branch +
      '<span>' + E(U('treeHead')) + '</span>' + ICON.chev + '</button><div class="wa-tk-bd">' + f.rounds.map(r => {
      const done = f.tools.filter(t => t.round === r.no).length, fin = done >= r.tools.length || (!live && !stopped);
      return '<div class="wa-tk-g"><div class="wa-tk-gh">' + ICON.arrow + '<span>' + E(U('stageN', { no: r.no, n: r.tools.length, tasks: r.tools.length === 1 ? 'task' : 'tasks', state: U(fin ? 'stDone' : stopped ? 'stStop' : 'stRun') })) + '</span></div>' +
        r.tools.map(t => {
          const pk = t.tool === 'fetch_data' ? (f.picks || [])[nth++] : '';
          return '<div class="wa-tk-l">' + ICON.arrow + '<span><span>' + E(t.label || t.tool) + '</span>' +
            (pk && pk !== 'none' ? '<span class="sf"> · ' + E(srcName(pk)) + '</span>' : '') + '</span></div>';
        }).join('') + '</div>';
    }).join('') + '</div></div>';
  }
  function activity(f) {
    const running = f.order.filter(s => f.cards[s] && f.cards[s].status === 'run');
    if (running.length) return U('actSearch', { places: running.map(srcName).join(' · ') });
    const last = f.rounds[f.rounds.length - 1];
    if (last && f.tools.filter(t => t.round === last.no).length < last.tools.length) return U('actEdit');
    return f.rounds.length ? U('actReply') : U('think');
  }
  function frameHas(f) { return !!(f && ((f.order && f.order.length) || (f.tools && f.tools.length) || (f.rounds && f.rounds.length) || f.plan)); }
  // 생각 과정: 찾을 곳 판단 · 사내/외부 리소스 카드 · 위젯 편집 카드 · 공통 줄 · 단계 트리(작업 중이면 맨 아래에 지금 하는 일)
  // the thinking process: the intent, internal/external resource cards, the widget-edit card, the common line, the stage tree (plus the current activity while live)
  function frameHtml(f, o) {
    const cards = f.order.filter(s => SOURCES.indexOf(s) >= 0 && f.cards[s]), internal = cards.filter(s => s !== 'web'), external = cards.filter(s => s === 'web');
    let b = '';
    if (f.plan && f.plan.sources.length) {
      b += lineHtml('done', U(f.plan.forced ? 'planForced' : 'plan', { places: f.plan.sources.map(srcName).join(' · '), view: UI['v_' + f.plan.view] ? U('v_' + f.plan.view) : U('v_text') }));
    }
    if (internal.length) b += '<div class="wa-scnt">' + E(U('internalN', { n: internal.length })) + '</div>' + internal.map(s => cardHtml(f, s, o.key, o.stopped)).join('');
    if (external.length) b += '<div class="wa-scnt">' + E(U('externalN', { n: external.length })) + '</div>' + external.map(s => cardHtml(f, s, o.key, o.stopped)).join('');
    if (f.tools.length) b += editHtml(f);
    if (!o.live && !o.stopped && f.tools.length) b += '<div class="wa-cl">' + lineHtml('done', U(o.changed ? 'commonChanged' : 'commonSame')) + '</div>';
    if (f.rounds.length) b += treeHtml(f, o.key, o.live, o.stopped);
    if (o.live) return '<div class="wa-fr live">' + b + '<div class="wa-think sm"><span class="wa-spin sm" aria-hidden="true"></span><span>' + E(activity(f)) + '</span></div></div>';
    return '<div class="wa-fr' + (o.fold ? ' fold' : '') + '"><button type="button" class="wa-fr-tg" data-wa-fold="' + o.key + '" aria-expanded="' + !o.fold + '"><span>' +
      E(U('thought')) + '</span><span class="n">' + E(U(cards.length && f.tools.length ? 'thoughtSum' : cards.length ? 'thoughtRes' : 'thoughtTools', { n: cards.length, t: f.tools.length })) + '</span>' + ICON.chev + '</button><div class="wa-fr-bd">' + b + '</div></div>';
  }
  function changeText(c) {
    if (c.k === 'title') return [U('cTitle'), c.v];
    if (c.k === 'view') return [U('cView'), viewText(c.v)];
    if (c.k === 'chart') return [U('cChart'), c.v ? chartName(c.v) + ' · ' + U('cChartChanged') : U('cChartChanged')];
    if (c.k === 'kpis') return [U('cKpis'), U('kpiN', { n: c.v })];
    if (c.k === 'origin') return [U('cOrigin'), (c.v || []).map(o => srcName(o.kind) + (o.kind === 'docs' && o.refs ? ' ' + U('nPlaces', { n: o.refs }) : (o.first ? ' · ' + o.first : ''))).join(', ')];
    if (c.k === 'insight') return [U('cInsight'), U(c.v === 'set' ? 'cInsSet' : 'cInsCleared')];
    if (c.k === 'theme') return [U('cTheme'), c.v || U('cThemeDefault')];
    return [c.k, String(c.v || '')];
  }
  function changesHtml(list) {
    return '<div class="wa-chg">' + list.map(c => { const t = changeText(c); return '<div class="wa-chg-r"><span>' + E(t[0]) + '</span><b data-i18n-skip>' + E(t[1]) + '</b></div>'; }).join('') + '</div>';
  }
  function askStaticHtml(a) {
    const fixed = a.question === ASK_TEXT || !a.question;
    return '<div class="wa-ask"><div class="q">' + ICON.ask + '<span' + (fixed ? '' : ' data-i18n-skip') + '>' + E(a.question || ASK_TEXT) + '</span></div>' +
      (Array.isArray(a.cards) && a.cards.length ? '<div class="cs">' + a.cards.map(c => '<span class="c" data-i18n-skip>' + E(c) + '</span>').join('') + '</div>' : '') +
      (a.hint ? '<div class="h">' + E(a.hint) + '</div>' : '') + '</div>';
  }
  // 추가 확인 폼 카드(마지막 답의 질문): 찾을 곳 고르기 · 직접 적기 · 제출 / the details form card for the last reply's question
  function askFormHtml(a, i) {
    if (W.askForm.mi !== i) W.askForm = { mi: i, opt: '', text: '', err: '' };
    const st = W.askForm, fixed = a.question === ASK_TEXT || !a.question;
    return '<div class="wa-af" role="group" aria-labelledby="waAfT"><div class="wa-af-t" id="waAfT">' + E(U('afTitle')) + '</div>' +
      '<div class="wa-af-q"><span>Q.</span><span' + (fixed ? '' : ' data-i18n-skip') + '>' + E(a.question || ASK_TEXT) + '</span></div>' +
      (Array.isArray(a.cards) && a.cards.length ? '<div class="wa-af-cs">' + a.cards.map(c => '<span class="c" data-i18n-skip>' + E(c) + '</span>').join('') + '</div>' : '') +
      '<div class="wa-af-os" role="radiogroup">' + SOURCES.map(s => '<button type="button" class="wa-af-o' + (st.opt === s ? ' on' : '') + '" role="radio" aria-checked="' + (st.opt === s) +
        '" data-wa-opt="' + s + '"><span class="rd"></span><span>' + E(U('opt_' + s)) + '</span></button>').join('') + '</div>' +
      '<input type="text" class="wa-af-in" id="waAfIn" maxlength="300" placeholder="' + E(U('afPh')) + '" value="' + E(st.text) + '" data-i18n-skip>' +
      (a.hint ? '<div class="wa-af-h">' + E(a.hint) + '</div>' : '') + (st.err ? '<div class="wa-af-er" role="alert">' + E(st.err) + '</div>' : '') +
      '<div class="wa-af-ft"><button type="button" class="wa-af-go" data-wa-act="ask-go" data-mi="' + i + '">' + E(U('afGo')) + '</button></div></div>';
  }
  function nextHtml(list) {
    const en = isEn() ? 1 : 0;
    return '<div class="wa-sec"><div class="wa-sec-t">' + E(U('next')) + '</div><div class="wa-nx">' + list.map(p =>
      '<button type="button" data-wa-next="' + E(p[en]) + '"><span>' + E(p[en]) + '</span>' + ICON.chevR + '</button>').join('') + '</div></div>';
  }
  function srcHtml(refs) {
    return '<div class="wa-sec"><div class="wa-sec-t">' + E(U('cOrigin')) + '</div><div class="wa-src">' + refs.slice(0, 6).map(r => {
      const t = r.label + (r.page ? ' · p.' + r.page : ''), ic = ICON[r.kind === 'web' ? 'globe' : r.kind === 'data' ? 'db' : 'doc'];
      return /^https?:\/\//i.test(r.url || '') ? '<a href="' + E(r.url) + '" target="_blank" rel="noopener noreferrer" data-i18n-skip title="' + E(t) + '">' + ic + '<span>' + E(t) + '</span></a>'
        : '<span class="s" data-i18n-skip title="' + E(t) + '">' + ic + '<span>' + E(t) + '</span></span>';
    }).join('') + '</div></div>';
  }
  function footHtml(m, i, isLast) {
    const btn = (act, ic, label) => '<button type="button" data-wa-act="' + act + '" data-mi="' + i + '" title="' + E(label) + '" aria-label="' + E(label) + '">' + ic + '</button>';
    const out = [];
    if (m.text && !m.error && !m.stopped) out.push(btn('copy', ICON.copy, U('copy')));
    if (m.beforeId && W.undo.some(u => u.id === m.beforeId)) out.push(btn('undo-turn', ICON.undo, U('undoTurn')));
    if (isLast && m.q && !busy()) out.push(btn('retry', ICON.retry, U('retry')));
    return out.length ? '<div class="wa-ft">' + out.join('') + '</div>' : '';
  }
  function whoHtml(res) {
    return '<div class="wa-who"><span>' + TX.agent + '</span>' + (res ? '<button type="button" class="wa-res" data-wa-act="res" data-i18n-skip>' + E(U('resources')) + ICON.chevR + '</button>' : '') + '</div>';
  }
  function agentHtml(m, i, isLast) {
    if (m.error) {
      return '<div class="wa-m wa-a err">' + AV + '<div class="wa-ab">' + whoHtml(false) + '<div class="wa-tx"' + (m.fixed ? '' : ' data-i18n-skip') + '>' + E(m.fixed ? TX.turnFail : m.text) + '</div>' +
        footHtml(m, i, isLast) + '</div></div>';
    }
    const has = frameHas(m.frame);
    let h = whoHtml(has && (m.frame.order || []).length > 0);
    if (has) h += frameHtml(m.frame, { key: String(i), fold: !!m.fold, live: false, changed: !!m.changed || !!m.beforeId, stopped: !!m.stopped });
    if (m.stopped) h += '<div class="wa-tx muted" data-i18n-skip>' + E(U('stopped')) + '</div>';
    else if (m.text) h += '<div class="wa-tx" data-i18n-skip>' + E(m.text) + '</div>';
    if (Array.isArray(m.changes) && m.changes.length) h += changesHtml(m.changes);
    if (m.ask) h += isLast && !busy() ? askFormHtml(m.ask, i) : askStaticHtml(m.ask);
    if (isLast && !busy() && !m.ask && !m.stopped) { const nx = waNext(W.widget); if (nx.length) h += nextHtml(nx); }
    if (Array.isArray(m.refs) && m.refs.length) h += srcHtml(m.refs);
    h += footHtml(m, i, isLast);
    return '<div class="wa-m wa-a">' + AV + '<div class="wa-ab">' + h + '</div></div>';
  }
  function paintChat(bottom) {
    const box = $('#waMsgs');
    const stick = bottom || box.scrollHeight - box.scrollTop - box.clientHeight < 60, top = box.scrollTop;
    const last = W.msgs.length - 1;
    let h = W.msgs.map((m, i) => {
      try {
        return m.role === 'user' ? '<div class="wa-m wa-u"><div class="wa-bub" data-i18n-skip>' + E(m.text) + '</div></div>' : agentHtml(m, i, i === last);
      } catch (err) {   // 그리지 못한 줄은 글만 / a message that cannot be drawn shows its text only
        return '<div class="wa-m wa-a">' + AV + '<div class="wa-ab"><div class="wa-tx" data-i18n-skip>' + E(typeof m.text === 'string' ? m.text : '') + '</div></div></div>';
      }
    }).join('');
    if (W.busy && W.live) {
      h += '<div class="wa-m wa-a live">' + AV + '<div class="wa-ab">' + (frameHas(W.live.frame) ? whoHtml(W.live.frame.order.length > 0) + frameHtml(W.live.frame, { key: 'live', live: true })
        : '<div class="wa-think"><span class="wa-spin" aria-hidden="true"></span><span data-i18n-skip>' + E(U('think')) + '</span></div>') + '</div></div>';
    }
    if (!h) {
      h = '<div class="wa-hello"><span class="wa-hello-ic" aria-hidden="true">' + ICON.spark + '</span><p class="t">' + TX.hello + '</p><p class="s">' + TX.helloSub + '</p><p class="h" data-i18n-skip>' + E(U('pickHint')) + '</p><div class="wa-ex">' +
        STARTERS.map((s, i) => { const u = STARTER_UI[i];
          return '<button type="button" data-wa-ex><span class="ic" aria-hidden="true">' + ICON[u ? u.ic : 'spark'] + '</span><span class="tx"><span class="q">' + E(s) + '</span>' +
            (u ? '<span class="c">' + E(u.cap) + '</span>' : '') + '</span></button>'; }).join('') + '</div></div>';
    }
    const focus = document.activeElement && document.activeElement.id === 'waAfIn';
    box.innerHTML = h;
    box.scrollTop = stick ? box.scrollHeight : top;
    if (focus) { const f = $('#waAfIn'); if (f) { f.focus(); f.setSelectionRange(f.value.length, f.value.length); } }
    const lm = W.msgs[last];
    const inp = $('#waIn');
    inp.placeholder = W.busy ? U('busyPh') : (lm && lm.role === 'agent' && lm.ask ? TX.askPlaceholder : TX.placeholder);
    grow(inp);
  }
  function paintQueue() {
    const box = $('#waQ');
    if (!W.queue.length) { box.hidden = true; box.innerHTML = ''; return; }
    box.hidden = false;
    box.classList.toggle('fold', W.qfold);
    box.innerHTML = '<button type="button" class="wa-q-hd" data-wa-act="q-toggle" aria-expanded="' + !W.qfold + '"><span>' + E(U('queue', { n: W.queue.length })) + '</span>' + ICON.chev + '</button>' +
      W.queue.map((q, i) => '<div class="wa-q-r"><span class="wa-q-g" aria-hidden="true">' + ICON.grip + '</span><span class="wa-q-tx" title="' + E(q.text) + '">' + E(q.text) + '</span>' +
        (q.source && q.source !== 'auto' ? '<span class="sc">' + E(q.source === 'internal' ? U('sc_internal') : q.source === 'web' ? U('sc_web') : U('res_' + q.source)) + '</span>' : '') +
        '<button type="button" data-wa-qedit="' + i + '" title="' + E(U('qEdit')) + '" aria-label="' + E(U('qEdit')) + '">' + ICON.pen + '</button>' +
        '<button type="button" data-wa-qdel="' + i + '" title="' + E(U('qDel')) + '" aria-label="' + E(U('qDel')) + '">' + ICON.x + '</button></div>').join('');
  }
  function paintLive() { paintChat(); }

  /* ── 대화 한 턴(이벤트 스트림) / one turn (event stream) ── */
  // 되돌릴 모습을 기록에 쌓는다. 내용이 없는 모습(새 위젯의 빈 처음)은 쌓지 않는다 — 홈에 반영할 수 없어 되돌릴 곳이 못 된다(2026-11-20, 지우려면 [위젯 지우기])
  // push a state to return to; an empty state (a new widget's blank start) is not kept, as it cannot be applied to Home (delete the widget instead)
  function pushUndo(entry) {
    const e = entry || { widget: W.widget, model: W.model, label: W.label, at: W.at };
    W.sizeRun = false;   // 다른 변경이 끼면 크기 고르기 묶음이 끝난다 / any other change ends a run of size picks
    if (!waHasContent(e.widget)) return '';
    const id = newId();
    W.undo.push(Object.assign({ id: id }, e));
    if (W.undo.length > MAX_UNDO) W.undo.shift();
    return id;
  }
  // opts.base = 다시 시도: 그 모습 위에서 턴을 돌린다(되돌릴 기록의 id, 또는 'blank' = 위젯을 처음 만든 턴). 작업본 · 기록은 **답이 온 뒤에만** 바꾼다 —
  // 실패하거나 멈추면 아무것도 바뀌지 않는다(독립 검토 2026-11-20: 먼저 되돌려 두면 실패한 다시 시도 뒤의 자동 저장이 되돌린 모습을 홈에 저장하고 마지막 결과를 잃었다)
  // opts.base = a retry: the turn runs on that state (an undo entry's id, or 'blank' for the turn that created the widget). The working copy and the
  // history change **only once the answer arrives**, so a failed or stopped turn changes nothing (independent review: rolling back first let the
  // auto-save after a failed retry write the rolled-back state to Home and lose the last result)
  function send(text, opts) {
    text = String(text || '').trim();
    if (!text) return;
    opts = opts || {};
    // 그 사이 사람이 바뀌었다(뷰애즈): 이전 사람의 위젯 · 대화를 새 사람으로 저장하지 않게 처음 상태로(독립 검토)
    // the person changed meanwhile (view-as): reset, so the previous person's widget and conversation are never saved as the new person's
    if (owner() !== W.owner) { reset(TX.moved); return; }
    const source = opts.source && (opts.source === 'auto' || opts.source === 'internal' || SOURCES.indexOf(opts.source) >= 0) ? opts.source : waSourceOf(W.scope, W.res);
    if (busy()) { enqueue(text, source); return; }
    closeMenu();
    if (!opts.keepInput) { const input = $('#waIn'); input.value = ''; grow(input); }
    W.peek = null; W.stopped = false; W.tab = 'chat'; W.sizeRun = false;
    const cur = { widget: W.widget, model: W.model, label: W.label, at: W.at };
    const blank = opts.base === 'blank';
    const baseEntry = opts.base && !blank ? (W.undo.filter(u => u.id === opts.base)[0] || null) : null;
    const start = baseEntry ? baseEntry.widget : (blank ? Object.assign(waBlank(), W.widget.size ? { size: W.widget.size } : {}) : W.widget);
    const carry = { src: source, q: text };   // 실패 · 멈춘 줄도 같은 모습에서 다시 시도할 수 있게 / an error or stopped line can be retried on the same state
    if (baseEntry) carry.base = baseEntry.id;
    if (blank) carry.blank = true;
    const history = waHistory(W.msgs), seq = ++W.seq, me = W.owner;
    W.msgs.forEach(m => { if (m.role === 'agent' && m.frame) m.fold = true; });   // 지난 생각 과정은 접는다 / earlier thinking folds
    W.msgs.push({ role: 'user', text: text, at: nowIso() });
    W.busy = true; W.draft = null; W.live = { frame: waFrameEmpty() };
    const ctrl = typeof AbortController === 'function' ? new AbortController() : null;
    W.ctrl = ctrl;
    paint(true);
    let result = null, failed = null;
    const onEvent = ev => {
      if (seq !== W.seq) return;   // 그 사이 새 위젯 · 다른 위젯을 열었다 / a new or other widget was opened meanwhile
      if (ev.event === 'draft') { if (ev.data && ev.data.model) { W.draft = ev.data.model; paintHome(); tr(); } return; }
      if (ev.event === 'done') { result = ev.data; return; }
      if (ev.event === 'error') { failed = ev.data || {}; return; }
      W.live.frame = waFrame(W.live.frame, ev);
      paintLive(); tr();
    };
    const body = { acting_user_id: me, widget: start, messages: history, message: text };
    if (source !== 'auto') body.source = source;
    stream('/api/home/agent/turn/stream', body, onEvent, ctrl ? ctrl.signal : undefined).then(() => {
      if (seq !== W.seq) return;
      if (owner() !== me) { reset(TX.moved); return; }   // 턴이 도는 사이 사람이 바뀌었다: 결과를 버린다 / the person changed during the turn: the result is dropped
      if (failed) { const err = new Error(typeof failed.detail === 'string' ? failed.detail : ''); err.status = failed.status; throw err; }
      const d = result;
      if (!d || !d.widget || !d.model) throw new Error('');
      const frame = waFrameFromTrace(W.live.frame, d.trace);
      // 턴이 돈 모습(before)과 되돌릴 기록: 보통은 지금 모습. 다시 시도면 — 그 턴 뒤로 바뀐 것이 없으면(기록 맨 위) 그 턴이 없던 것처럼,
      // 더 앞의 모습이면 지금 모습을 기록에 남기고, 처음 만든 턴이면 빈 모습에서 다시
      // the state the turn ran on and the history: normally the current one; a retry runs as if the turn never happened (top of the history),
      // from an earlier state with the current one kept in the history, or from a blank state for the creating turn
      const top = W.undo[W.undo.length - 1], onTop = !!(baseEntry && top && top.id === baseEntry.id);
      let before = cur, beforeId = '';
      if (onTop) before = { widget: top.widget, model: top.model, label: top.label, at: top.at };
      else if (baseEntry) { pushUndo(cur); before = { widget: baseEntry.widget, model: baseEntry.model, label: waLabel('restore', baseEntry.label), at: nowIso() }; }
      else if (blank) before = { widget: start, model: waBlankModel(), label: waLabel('new', ''), at: cur.at };
      const changed = JSON.stringify(d.widget) !== JSON.stringify(before.widget);
      if (changed) {
        beforeId = onTop ? top.id : pushUndo(before);
        W.label = waLabel('turn', text.slice(0, 60)); W.at = nowIso();
      } else if (onTop) { W.undo.pop(); W.label = before.label; W.at = before.at; }
      else if (baseEntry) { W.label = before.label; W.at = before.at; }
      const changes = changed ? waChanges(before.widget, d.widget) : [];
      const moved = changed || JSON.stringify(d.widget) !== JSON.stringify(cur.widget);
      W.widget = d.widget; W.model = d.model;
      // 출처 = 이번 턴에 쓴 곳들의 근거(겹치지 않게) / sources = the references of every place used this turn, without repeats
      const refs = [], seen = {};
      (frame.picks || []).filter(x => x !== 'none').forEach(x => {
        const c = frame.cards[x];
        ((c && c.note && c.note.refs) || []).forEach(r => { const k = r.label + '|' + r.page; if (!seen[k]) { seen[k] = 1; refs.push(r); } });
      });
      W.msgs.push({ role: 'agent', text: d.reply || '', trace: Array.isArray(d.trace) ? d.trace : [], ask: d.ask || null, frame: frame, changes: changes,
        refs: refs.slice(0, 12), beforeId: beforeId, changed: moved, blank: !waHasContent(before.widget), src: source, q: text, at: nowIso() });
    }).catch(err => {
      if (seq !== W.seq) return;
      if (ctrl && ctrl.signal.aborted) {   // 멈추기 — 받은 데까지의 생각 과정과 함께 / stopped, with the thinking so far
        W.msgs.push(Object.assign({ role: 'agent', stopped: true, text: '', frame: W.live ? W.live.frame : waFrameEmpty(), at: nowIso() }, carry));
        W.stopped = true;
        return;
      }
      W.msgs.push(Object.assign({ role: 'agent', error: true, text: err.message || TX.turnFail, fixed: !err.message, at: nowIso() }, carry));
    }).then(() => {
      if (seq !== W.seq) return;
      W.busy = false; W.live = null; W.ctrl = null; W.draft = null;
      // 턴이 도는 사이 이 위젯이 배치 편집에서 지워졌다: 다시 만들지 않는다 — 바뀐 것이 없으면 처음 상태로, 있으면 작업본만 남긴다(독립 검토)
      // the widget was deleted in layout editing during the turn: never re-created — reset when nothing changed, else only the working copy stays
      if (W.goneKey && W.goneKey === W.key) {
        if (dirty() && waHasContent(W.widget)) gone(); else { reset(''); return; }
      }
      W.goneKey = '';
      paint(true);
      // 바뀐 것이 있으면 바로 홈에 반영한다(자동 저장 — 대화도 같이, 끝난 뒤 Queue 를 잇는다). 없으면 대화만 저장. 실패 · 멈춘 턴은 작업본을 바꾸지 않으므로
      // 여기서 저장되는 것은 이번 턴의 결과이거나 앞서 실패한 저장뿐이다
      // a change is applied to Home at once (auto-save, the conversation with it; the Queue continues afterwards); otherwise only the conversation is
      // saved. A failed or stopped turn leaves the working copy alone, so what is saved here is this turn's result or an earlier save that failed
      if (dirty() && waHasContent(W.widget)) commit();
      else { if (W.key && !dirty()) saveChat(); drainSoon(); }
      const inp = $('#waIn'); if (inp && W.shown) inp.focus();
    });
  }
  function stop() { if (W.busy && W.ctrl) W.ctrl.abort(); }
  function enqueue(text, source) {
    if (W.queue.length >= MAX_QUEUE) { toast(U('queueFull', { n: MAX_QUEUE })); return; }
    W.queue.push({ text: text, source: source || 'auto' });
    const input = $('#waIn'); input.value = ''; grow(input);
    paintBar();
  }
  // 대기 요청을 차례로: 일이 끝나고 잠깐 뒤, 멈춘 뒤에는 보내지 않는다(다음에 직접 보내면 이어서) / queued requests go one by one; not after a stop
  function drainSoon() {
    setTimeout(() => {
      if (busy() || W.stopped || W.renaming || !W.queue.length || !root) return;   // 이름을 바꾸는 중에는 기다린다 / waits while a rename is open
      const it = W.queue.shift();
      paintQueue();
      send(it.text, { source: it.source, keepInput: true });
    }, 300);
  }
  function modelOf(e) {
    if (e.model) return Promise.resolve(e.model);
    return api('POST', '/api/home/agent/model', { acting_user_id: owner(), widget: e.widget }).then(d => { e.model = d.model; e.widget = d.widget; return d.model; });
  }
  function settle(seq, fn) { return (...a) => { if (seq !== W.seq) return; W.wait = Math.max(0, W.wait - 1); fn(...a); }; }
  function undo() {
    if (busy() || !W.undo.length) return;
    const prev = W.undo[W.undo.length - 1], seq = W.seq;
    W.wait++;
    modelOf(prev).then(settle(seq, model => {
      const resize = sizeMoved(W.widget, prev.widget);
      W.undo.pop(); W.sizeRun = false;
      W.widget = prev.widget; W.model = model; W.label = prev.label; W.at = prev.at; W.peek = null;
      toast(TX.undone); commit({ resize: resize });
    }), settle(seq, err => { paint(); toast(err.message || U('restoreFail')); drainSoon(); }));
  }
  // 지난 모습으로(지금 모습은 기록에 남겨 되돌린 것도 되돌릴 수 있다) / back to an earlier state (the current one stays in the history)
  function restoreTo(id) {
    const e = W.undo.filter(u => u.id === id)[0];
    if (busy() || !e) return;
    const seq = W.seq;
    W.wait++; paint();
    modelOf(e).then(settle(seq, model => {
      const resize = sizeMoved(W.widget, e.widget);
      pushUndo();
      W.widget = e.widget; W.model = model; W.label = waLabel('restore', e.label); W.at = nowIso(); W.peek = null;
      toast(U('restored')); commit({ resize: resize });
    }), settle(seq, err => { paint(); toast(err.message || U('restoreFail')); drainSoon(); }));
  }
  function peekAt(id) {
    if (busy()) return;
    if (id === 'now' || (W.peek && W.peek.id === id)) { W.peek = null; paint(); return; }
    const e = W.undo.filter(u => u.id === id)[0];
    if (!e) return;
    W.peek = { id: id, label: e.label, model: e.model };
    try { const hd = HD(); if (hd && hd.focus && W.key) hd.focus(W.key, true); } catch (x) { /* 홈 격자 없음 / no home grid */ }
    if (!e.model) {
      const seq = W.seq;
      W.wait++;
      modelOf(e).then(settle(seq, m => { if (W.peek && W.peek.id === id) W.peek.model = m; paint(); drainSoon(); }),
        settle(seq, () => { W.peek = null; paint(); toast(U('previewFail')); drainSoon(); }));
    }
    paint();
  }
  // [다시 시도](마지막 답): 같은 요청 · 같은 가져올 곳으로, 그 턴이 돌았던 모습 위에서 다시(send 의 opts.base). 여기서는 작업본을 건드리지 않는다
  // [Try again] (the last reply): the same request and place, run again on the state that turn ran on (send's opts.base); nothing is rolled back here
  function retry(i) {
    const m = W.msgs[i];
    if (busy() || i !== W.msgs.length - 1 || !m || m.role !== 'agent' || !m.q) return;
    const baseId = m.beforeId || m.base || '';
    const e = baseId ? W.undo.filter(u => u.id === baseId)[0] : null;
    const go = base => {
      const u = W.msgs[i - 1];
      W.msgs.splice(u && u.role === 'user' ? i - 1 : i);
      send(m.q, { source: m.src || 'auto', keepInput: true, base: base });
    };
    if (!e) { go(m.blank && W.key ? 'blank' : ''); return; }   // 위젯을 처음 만든 턴은 빈 모습에서 다시 / the creating turn runs again from a blank state
    const seq = W.seq;
    W.wait++;
    modelOf(e).then(settle(seq, () => go(e.id)), settle(seq, err => { paint(); toast(err.message || U('restoreFail')); drainSoon(); }));
  }
  function copy(text) {
    const done = () => toast(U('copied'));
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text, done)); return; }
    } catch (e) { /* 아래로 / fall through */ }
    fallbackCopy(text, done);
  }
  function fallbackCopy(text, done) {
    const ta = document.createElement('textarea');
    ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); done(); } catch (e) { /* 복사 못 함 / nothing copied */ }
    ta.remove();
  }
  // 크기 칸(정보 탭): 고르면 홈에 놓인 그 위젯이 바로 그 크기로(아직 없는 위젯이면 처음 놓일 크기). 이어서 고른 크기는 되돌리기 한 칸
  // the size cells (info tab): a pick resizes the placed widget at once (or sets the first size of one not made yet); consecutive picks share one undo step
  function setSize(dim, n) {
    if (busy() || W.peek) return;
    const cur = curSize(), next = { w: dim === 'w' ? n : cur.w, h: dim === 'h' ? n : cur.h };
    if (cur.w === next.w && cur.h === next.h) return;
    // 되돌릴 모습에는 그때 홈에 놓여 있던 크기를 적어 둔다 — 크기 되돌리기가 배치 편집에서 정한 칸으로 돌아가게(정의의 옛 크기가 아니라, 독립 검토)
    // the state to return to records the cell as placed then, so undoing a resize goes back to the arranged cell (not a stale definition size)
    if (!W.sizeRun) {
      const p = placed();
      pushUndo(p ? { widget: Object.assign({}, W.widget, { size: { w: p.w, h: p.h } }), model: W.model, label: W.label, at: W.at } : undefined);
    }
    W.sizeRun = true;
    W.widget = Object.assign({}, W.widget, { size: next });
    W.model = Object.assign({}, W.model, { size: next });
    W.label = waLabel('size', next.w + 'x' + next.h); W.at = nowIso();
    commit({ resize: true });
  }
  // [지금 새로 가져오기](정보 탭): 출처를 지금 다시 가져오고, 바뀌었으면 홈에 반영한다 / refresh the origins now and apply a change to Home
  function refreshNow() {
    if (busy()) return;
    const seq = W.seq;
    W.wait++; W.refreshing = true; paint();
    api('POST', '/api/home/agent/refresh', { acting_user_id: owner(), widget: W.widget }).then(settle(seq, d => {
      W.refreshing = false;
      if (!d || !d.changed || !d.widget || !d.model) { paint(); toast(U('noChange')); drainSoon(); return; }
      pushUndo();
      W.widget = d.widget; W.model = d.model; W.label = waLabel('refresh', ''); W.at = nowIso();
      toast(U('refreshed')); commit();
    }), settle(seq, err => { W.refreshing = false; paint(); toast(err.message || U('refreshFail')); drainSoon(); }));
  }
  function focusInfo() {
    W.tab = 'info'; paintSide();
    const el = $('#waInfo');
    if (!el) return;
    try { el.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); } catch (e) { el.scrollIntoView(); }
    el.classList.add('flash');
    setTimeout(() => el.classList.remove('flash'), 1200);
  }
  function askGo(i) {
    const m = W.msgs[i];
    if (!m || !m.ask || busy()) return;
    const st = W.askForm, text = waAskMessage(m.ask, st.opt, st.text, isEn());
    if (!text) {
      st.err = U((m.ask.cards || []).length ? 'afErr' : 'afErrNoCards');
      paintChat();
      const f = $('#waAfIn'); if (f) f.focus();
      return;
    }
    const opt = st.opt;
    W.askForm = { mi: -1, opt: '', text: '', err: '' };
    send(text, { source: opt || waSourceOf(W.scope, W.res), keepInput: true });
  }

  /* ── 홈에 반영(자동 저장) · 홈에 놓기 · 지우기 · 대화 저장 · 내 위젯 · 새 위젯
     applying to Home (auto-save), putting on Home, deleting, the saved conversation, my widgets, new widget ── */
  function sizeMoved(a, b) { return JSON.stringify((a && a.size) || null) !== JSON.stringify((b && b.size) || null); }
  // 작업본이 바뀔 때마다 부른다(2026-11-20 — [저장] 단추가 없다): 저장하고(없던 위젯이면 만들어 홈의 빈 첫 자리에 놓고) 홈을 다시 읽는다. 그동안은 기다림이라
  // 보낸 요청은 Queue 에서 기다린다. 내용이 없는 모습은 저장하지 않는다. 실패하면 알리고 상태 알약이 [다시 저장]이 된다. opts.resize = 크기를 바꿨다(홈에 놓인
  // 칸도 그 크기로 — 턴마다 맞추면 배치 편집에서 바꾼 크기를 되돌리게 되므로 크기를 바꾼 때만). 독립 검토(2026-11-20): 열어 둔 위젯이 그 사이 지워졌으면(404)
  // **다시 만들지 않고** 작업본만 남긴 채 자동 저장을 멈춘다([다시 저장]을 누르면 새 위젯으로, gone) · 사람이 바뀌었으면(뷰애즈) 저장하지 않고 처음 상태로
  // called after every change (there is no [Save]): it saves (a widget that did not exist is created and put on the first free spot) and re-reads the
  // home; meanwhile requests wait in the Queue. An empty state is not saved; a failure is reported and the status pill becomes [save again].
  // opts.resize = the size changed (the placed cell follows — only then, or every turn would undo a size set in layout editing). Independent review
  // (2026-11-20): a widget deleted meanwhile (404) is **not re-created** — the working copy stays and auto-save pauses until [save again] (gone);
  // a changed person (view-as) is never saved to: the panel resets instead. opts.user = the user pressed [save again]
  function gone() {
    W.key = ''; W.saved = null; W.savedAt = ''; W.mine = null; W.hold = true; W.chatOk = true;
    toast(U('goneKeep'));
  }
  function commit(opts) {
    opts = opts || {};
    if (!dirty() || !waHasContent(W.widget) || (W.hold && !opts.user)) { W.syncing = false; paint(); drainSoon(); return Promise.resolve(false); }
    const me = owner(), spec = W.widget, seq = W.seq;
    if (me !== W.owner) { reset(TX.moved); return Promise.resolve(false); }
    const fresh = !W.key;
    W.hold = false;
    W.wait++; W.syncing = true; paint();
    const req = fresh ? api('POST', '/api/home/widgets', { acting_user_id: me, spec: spec })
      : api('PUT', '/api/home/widgets/' + encodeURIComponent(W.key), { acting_user_id: me, spec: spec });
    return req.then(w => {
      if (seq !== W.seq) return false;
      W.key = w.key; W.owner = me; W.widget = w.spec; W.model = w.model; W.saved = JSON.stringify(w.spec); W.savedAt = w.updated_at || '';
      W.mine = null;
      if (fresh) W.chatOk = true;   // 새 위젯에는 저장된 대화가 없다 / a new widget has no saved conversation
      saveChat();
      const hd = HD(), sz = w.spec && w.spec.size;
      let sync = null;
      try {
        if (hd && fresh && hd.place) {
          sync = hd.place(w.key).then(ok => { if (seq !== W.seq) return; toast(U(ok ? 'placedNew' : 'placedLater')); if (ok) hd.focus(w.key, true); });
        } else if (hd && opts.resize && sz && hd.resize) sync = hd.resize(w.key, sz.w, sz.h).then(done => (done ? null : hd.reload()));
        else if (hd) sync = hd.reload();
      } catch (e) { /* 홈 격자가 없다 / no home grid */ }
      return Promise.resolve(sync).then(() => true, () => true);
    }, err => {
      if (seq !== W.seq) return false;
      if (err.status === 404 && !fresh) gone();   // 그 사이 지워졌다(배치 편집의 서랍 · 다른 창) / deleted meanwhile (the layout-editing drawer, another window)
      else toast(err.message || TX.saveFail);
      return false;
    }).then(ok => {
      if (seq !== W.seq) return ok;   // 그 사이 화면을 처음 상태로 돌렸다 / the screen was reset meanwhile
      W.wait = Math.max(0, W.wait - 1); W.syncing = false;
      paint(); drainSoon();
      return ok;
    });
  }
  // [홈에 놓기]: 홈에 없는 위젯(배치 편집에서 뺐다 · 놓지 못했다)을 빈 첫 자리에 / put a widget that is off Home on the first free spot
  function putHome() {
    const hd = HD();
    if (busy() || !W.key || !hd || !hd.place) return;
    const seq = W.seq, key = W.key;
    W.wait++; paint();
    hd.place(key).then(ok => !!ok, () => false).then(settle(seq, ok => {
      paint(); toast(U(ok ? 'putDone' : 'putFail'));
      if (ok) hd.focus(key, true);
      drainSoon();
    }));
  }
  // [위젯 지우기](정보 탭): 확인을 거쳐 지운다 — 홈 · 내 위젯 · 그 대화가 함께 사라진다. 이미 없는 위젯(404)도 지운 것으로
  // [Delete widget] (info tab), after a confirmation: it leaves Home and My widgets with its conversation; an already-gone widget (404) counts as deleted
  function askDelete() {
    if (busy() || !W.key) return;
    ask({ title: U('delAsk'), body: U('delBody'), ok: U('delGo'), raw: true, danger: true, run: doDelete });
  }
  function doDelete() {
    if (busy() || !W.key) return;
    const key = W.key, me = W.owner, seq = W.seq;
    W.wait++; paint();
    api('DELETE', '/api/home/widgets/' + encodeURIComponent(key) + '?acting_user_id=' + encodeURIComponent(me)).then(() => true, err => err.status === 404)
      .then(settle(seq, ok => {
        if (!ok) { paint(); toast(U('delFail')); drainSoon(); return; }
        try { const hd = HD(); if (hd) hd.reload(); } catch (e) { /* 홈 격자가 없다 / no home grid */ }
        reset('');
        toast(U('deleted'));
      }));
  }
  // 대화 저장(위젯마다): 실패해도 위젯은 그대로라 알리지 않는다 / saves the conversation per widget; a failure is silent (the widget is fine)
  function saveChat() {
    // 저장된 대화를 아직 못 받았으면(받는 중 · 실패) 덮어쓰지 않는다(독립 검토) / never overwrite a saved conversation not yet received (independent review)
    if (!W.key || owner() !== W.owner || !W.chatOk) return Promise.resolve();
    const chat = waChatPayload(W.msgs, W.undo, W.label, W.at);
    return api('PUT', '/api/home/agent/chat/' + encodeURIComponent(W.key), { acting_user_id: W.owner, chat: chat }).catch(() => {});
  }
  function clearState() {
    if (W.ctrl) { try { W.ctrl.abort(); } catch (e) { /* 이미 끝났다 / already over */ } }
    W.seq++;
    W.msgs = []; W.undo = []; W.busy = false; W.wait = 0; W.renaming = false; W.draft = null; W.live = null; W.ctrl = null; W.stopped = false;
    W.queue = []; W.peek = null; W.open = {}; W.fold = {}; W.refreshing = false; W.askForm = { mi: -1, opt: '', text: '', err: '' }; W.syncing = false;
    W.hold = false; W.sizeRun = false; W.goneKey = ''; W.want = '';
  }
  function reset(note) {
    clearState();
    W.key = ''; W.owner = owner(); W.widget = waBlank(); W.model = waBlankModel(); W.saved = null; W.savedAt = ''; W.mine = null;
    W.label = waLabel('new', ''); W.at = nowIso(); W.chatOk = true; W.tab = 'chat';
    closeMenu(); paint();
    if (note) toast(note);
  }
  function openWidget(w) {
    clearState();
    W.key = w.key; W.owner = owner(); W.widget = w.spec; W.model = w.model; W.saved = JSON.stringify(w.spec); W.savedAt = w.updated_at || '';
    W.label = waLabel('opened', ''); W.at = w.updated_at || nowIso();
    // 그 위젯의 대화를 이어서(생각 과정은 접어서). 받는 동안은 기다림(W.wait): 보낸 요청은 Queue 에서 기다리고 편집도 막혀, 늦게 온 저장본이
    // 그 사이의 대화 · 편집을 덮지 않는다. 받지 못하면 이번 대화는 저장하지 않는다(저장본을 덮어쓰지 않게) — 독립 검토 2026-11-19
    // the widget's conversation continues (thinking folded); receiving it is a wait, so requests queue and edits pause, and a late answer
    // never overwrites them; when it cannot be received this session's conversation is not saved (the stored one is kept)
    W.chatOk = false;
    W.wait++;
    W.tab = 'chat';
    closeMenu(); paint();
    try { const hd = HD(); if (hd && hd.focus) hd.focus(w.key, true); } catch (e) { /* 홈 격자가 없다 / no home grid */ }
    const key = w.key, seq = W.seq, me = W.owner;
    api('GET', '/api/home/agent/chat/' + encodeURIComponent(key) + '?acting_user_id=' + encodeURIComponent(me)).then(d => {
      if (seq !== W.seq || W.key !== key) return;
      W.wait = Math.max(0, W.wait - 1);
      W.chatOk = true;
      const c = d && d.chat && typeof d.chat === 'object' ? d.chat : null;
      if (c) {
        W.msgs = (Array.isArray(c.msgs) ? c.msgs : []).map(waCleanMsg).filter(Boolean).map(m => (m.role === 'agent' ? Object.assign(m, { fold: true }) : m));
        W.undo = (Array.isArray(c.hist) ? c.hist : []).filter(h => h && h.widget && typeof h.widget === 'object').slice(-MAX_UNDO)
          .map(h => ({ id: STR(h.id, 40) || newId(), widget: h.widget, model: null, label: STR(h.label, MAX_LABEL), at: STR(h.at, 40) }));
        if (typeof c.label === 'string' && c.label) W.label = c.label.slice(0, MAX_LABEL);
        if (typeof c.at === 'string' && c.at) W.at = c.at.slice(0, 40);
      }
      paint(true); drainSoon();
    }, () => {
      if (seq !== W.seq || W.key !== key) return;
      W.wait = Math.max(0, W.wait - 1);
      paint(); toast(U('chatLoadFail')); drainSoon();
    });
  }
  // 확인 창(반영하지 못한 변경 · 위젯 지우기). raw = 화면이 언어를 고른 글(사전을 거치지 않는다) / a confirmation; raw = text already in the screen's language
  function ask(o) {
    closeMenu();
    const ov = document.createElement('div'), sk = o.raw ? ' data-i18n-skip' : '';
    ov.className = 'wa-ov'; ov.id = 'waOv';
    ov.innerHTML = '<div class="wa-dlg" role="dialog" aria-modal="true" aria-labelledby="waDlgTt"><p class="wa-dlg-tt" id="waDlgTt"' + sk + '>' + E(o.title) + '</p>' +
      '<p class="wa-dlg-bd"' + sk + '>' + E(o.body) + '</p><div class="wa-dlg-act"><button type="button" class="no" data-wa-dlg="no">' + TX.cancel + '</button>' +
      '<button type="button" class="ok" data-wa-dlg="ok" data-i18n-skip>' + E(o.ok) + '</button></div></div>';
    ov.addEventListener('click', e => {
      const b = e.target.closest('[data-wa-dlg]');
      if (!b && e.target !== ov) return;
      ov.remove();
      if (b && b.dataset.waDlg === 'ok') o.run();
    });
    ov.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); ov.remove(); } });
    document.body.appendChild(ov);
    ov.querySelector(o.danger ? '[data-wa-dlg="no"]' : '[data-wa-dlg="ok"]').focus();   // 지우기는 [취소]에 초점 / a destructive ask focuses [Cancel]
    tr();
  }
  // 다른 위젯을 열거나 새로 시작하기 전: 홈에 반영하지 못한 내용(저장 실패)이 있을 때만 묻는다 / asked only when something could not be applied to Home (a failed save)
  function guard(body, okLabel, run) {
    if (!(dirty() && waHasContent(W.widget))) { run(); return; }
    ask({ title: TX.dirtyAsk, body: body, ok: L(okLabel), run: run });
  }
  // [리소스 센터](사내일 때): 지식 관리(사내 문서) · 데이터 분석(사내 데이터) 고르기 — 고르지 않으면 둘 다 / the resource dialog: knowledge and/or data (none = both)
  function openRes() {
    closeMenu();
    const picked = W.res.slice();
    const ov = document.createElement('div');
    ov.className = 'wa-ov'; ov.id = 'waRsOv';
    const row = k => '<label class="wa-rs-r"><input type="checkbox" data-wa-rsk="' + k + '"' + (picked.indexOf(k) >= 0 ? ' checked' : '') + '><span class="ic">' +
      ICON[k === 'docs' ? 'doc' : 'db'] + '</span><span class="n">' + E(U('res_' + k)) + '</span>' + (k === 'docs' ? '<span class="b">Public</span>' : '') +
      '<span class="d">' + E(U('resDesc_' + k)) + '</span></label>';
    ov.innerHTML = '<div class="wa-rs" role="dialog" aria-modal="true" aria-labelledby="waRsT" data-i18n-skip><div class="wa-rs-hd"><div><p class="t" id="waRsT">' + E(U('resTitle')) +
      '</p><p class="s">' + E(U('resSub')) + '</p></div><button type="button" class="x" data-wa-rs="no" aria-label="' + E(U('close')) + '">' + ICON.x + '</button></div>' +
      '<div class="wa-rs-bd">' + row('docs') + row('data') + '<p class="wa-rs-h">' + E(U('resHint')) + '</p></div>' +
      '<div class="wa-rs-ft"><button type="button" class="no" data-wa-rs="no">' + E(U('resCancel')) + '</button><button type="button" class="ok" data-wa-rs="ok">' + E(U('resOk')) + '</button></div></div>';
    const close = () => { ov.remove(); const b = root && $('[data-wa="res"]'); if (b && document.hasFocus()) b.focus(); };
    ov.addEventListener('click', e => {
      const b = e.target.closest('[data-wa-rs]');
      if (!b && e.target !== ov) return;
      if (b && b.dataset.waRs === 'ok') {
        W.res = [].map.call(ov.querySelectorAll('[data-wa-rsk]:checked'), x => x.dataset.waRsk);
        if (W.res.length === 2) W.res = [];   // 둘 다 = 고르지 않은 것과 같다 / both = none picked
        paintBar();
      }
      close();
    });
    ov.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } });
    document.body.appendChild(ov);
    const first = ov.querySelector('[data-wa-rsk]');
    if (first) first.focus();
  }
  function loadMine() {
    const me = owner();
    return api('GET', '/api/home/widgets?acting_user_id=' + encodeURIComponent(me)).then(d => {
      if (owner() !== me) return;
      W.mine = (d && Array.isArray(d.widgets)) ? d.widgets : [];
    }, () => { W.mine = []; toast(TX.mineFail); });
  }

  /* ── 메뉴(내 위젯 · 도구 트리 · 가져올 곳) / menus (my widgets, tool tree, where to look) ── */
  function closeMenu() {
    W.menu = '';
    if (!root) return;
    root.querySelectorAll('.wa-pop').forEach(p => p.remove());
    W.group = '';
    root.querySelectorAll('[data-wa="plus"]').forEach(b => b.classList.remove('on'));
  }
  function mineHtml() {
    if (!W.mine) return '<div class="wa-mn-none">' + TX.loading + '</div>';
    if (!W.mine.length) return '<div class="wa-mn-none">' + TX.noMine + '</div>';
    // 홈에 놓이지 않은 위젯은 '홈에 없음' / widgets that are not placed say so
    let on = null;
    try { const st = HD() && HD().state && HD().state(); if (st) { on = {}; st.items.forEach(i => { on[i.key] = 1; }); } } catch (e) { on = null; }
    return W.mine.map(w => '<button type="button" class="wa-mn-it' + (w.key === W.key ? ' on' : '') + '" data-wa-open="' + E(w.key) + '"><span class="t" data-i18n-skip>' + E(w.name) +
      '</span><span class="s" data-i18n-skip>' + E(when(w.updated_at)) + (on && !on[w.key] ? '<span class="off">' + E(U('offTag')) + '</span>' : '') + '</span></button>').join('');
  }
  // 도구 묶음(데이터 먼저, 같은 이름은 한 묶음) / tool groups (data first; same names merge)
  function toolGroups() {
    const out = [];
    (W.tools || []).forEach(a => (a.groups || []).forEach(g => {
      let hit = out.filter(x => x.group === g.group)[0];
      if (!hit) { hit = { group: g.group, tools: [] }; out.push(hit); }
      hit.tools = hit.tools.concat(g.tools || []);
    }));
    return out.sort((x, y) => (y.group === '데이터') - (x.group === '데이터'));
  }
  // [+] 메뉴: 처음 = 묶음(아이콘 · 이름 · ›), 묶음을 누르면 그 도구들(‹ 뒤로 · 이름 · 도구 id), 도구를 누르면 요청 문장을 채운다
  // the [+] menu: groups first (icon, name, ›); a group opens its tools (‹ back, name, tool id); a tool fills a request
  function plusHtml() {
    if (!W.tools) return '<div class="wa-am-none">' + TX.loading + '</div>';
    const groups = toolGroups(), g = W.group ? groups.filter(x => x.group === W.group)[0] : null;
    if (!g) {
      return groups.map(x => '<button type="button" class="wa-mi" role="menuitem" data-wa-grp="' + E(x.group) + '">' + ICON[GROUP_IC[x.group] || 'list'] +
        '<span data-i18n-skip>' + E(L(x.group)) + '</span><span class="cv">' + ICON.chevR + '</span></button>').join('') || '<div class="wa-am-none">' + TX.loading + '</div>';
    }
    return '<button type="button" class="wa-mi back" role="menuitem" data-wa-grp="">' + ICON.back + '<span data-i18n-skip>' + E(L(g.group)) + '</span></button>' +
      g.tools.map(t => '<button type="button" class="wa-mi" role="menuitem" data-wa-tool="' + E(t.name) + '"><span>' + E(t.label) + '</span><span class="id" data-i18n-skip>' + E(t.name) + '</span></button>').join('');
  }
  // 메인 채팅처럼 [+] 바로 위 8px(자리가 없으면 아래), 왼쪽은 [+] 에 맞춘다 / like the main chat: 8px above the [+] (below without room), left-aligned to it
  function placePop() {
    const pop = root && root.querySelector('.wa-pop.am'), btn = root && $('[data-wa="plus"]');
    if (!pop || !btn) return;
    const r = btn.getBoundingClientRect(), mh = pop.offsetHeight, mw = pop.offsetWidth;
    let top = r.top - mh - 8; if (top < 8) top = r.bottom + 8;
    let left = r.left; if (left + mw > window.innerWidth - 8) left = window.innerWidth - 8 - mw; if (left < 8) left = 8;
    pop.style.top = top + 'px'; pop.style.left = left + 'px';
  }
  function openMenu(kind) {
    const was = W.menu;
    closeMenu();
    if (was === kind) return;
    W.menu = kind;
    const pop = document.createElement('div');
    pop.className = 'wa-pop' + (kind === 'plus' ? ' am' : ''); pop.setAttribute('role', 'menu');
    const paintPop = () => { if (W.menu !== kind) return; pop.innerHTML = kind === 'mine' ? mineHtml() : plusHtml(); tr(); if (kind === 'plus') placePop(); };
    W.paintPop = paintPop;
    if (kind === 'mine') {
      root.querySelector('.wa-mine').appendChild(pop);
      paintPop();
      loadMine().then(paintPop);
    } else {
      root.querySelector('.wa-cmp').appendChild(pop);
      $('[data-wa="plus"]').classList.add('on');
      paintPop();
      if (!W.tools) api('GET', '/api/home/agent/tools').then(d => { W.tools = (d && Array.isArray(d.tree)) ? d.tree : []; paintPop(); }, () => { W.tools = []; paintPop(); });
    }
  }
  function fill(text) {
    const input = $('#waIn');
    input.value = text; grow(input); input.focus();
    input.setSelectionRange(text.length, text.length);
    paintBar();
  }

  /* ── 이름 바꾸기(대화 없이 바로) / renaming in place (no conversation) ── */
  function startRename() {
    if (busy() || W.renaming) return;
    W.renaming = true;
    const nm = $('#waNm');
    nm.innerHTML = '<input type="text" class="wa-nmin" id="waNmIn" maxlength="40" title="' + TX.rename + '">';
    const inp = nm.querySelector('input');
    inp.value = W.widget.title;
    inp.focus(); inp.select();
    let done = false;
    const finish = keep => {
      if (done) return;
      done = true; W.renaming = false;
      const t = inp.value.trim();
      // 그 사이 턴이 돌고 있으면 바꾸지 않는다(턴의 결과가 덮는다) — Queue 는 이름 바꾸기가 끝날 때까지 기다리므로 보통은 없는 일(독립 검토)
      // not applied while a turn runs (its result would overwrite it); the Queue waits for an open rename, so this is rare
      if (keep && t && t !== W.widget.title && !busy()) {
        pushUndo();
        W.widget = Object.assign({}, W.widget, { title: t });
        W.model = Object.assign({}, W.model, { title: t });
        W.label = waLabel('rename', t); W.at = nowIso();
        commit();
        return;
      }
      paint(); drainSoon();
    };
    inp.addEventListener('keydown', e => {
      if (e.isComposing) return;
      if (e.key === 'Enter') { e.preventDefault(); finish(true); } else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finish(false); }
    });
    inp.addEventListener('blur', () => finish(true));
    tr();
  }

  /* ── 입력 / input ── */
  function onClick(e) {
    const t = e.target;
    // 그 사이 사람이 바뀌었으면(뷰애즈 — 부모 앱은 따로 알리지 않는다) 아무것도 하지 않고 처음 상태로: 이전 사람의 위젯을 새 사람으로 고치거나 지우지 않는다(독립 검토)
    // a changed person (view-as; the parent app sends no notice) resets the panel before anything else, so the previous person's widget is never edited or deleted as the new one
    if (owner() !== W.owner && !W.busy) { reset(dirty() || W.msgs.length ? TX.moved : ''); return; }
    const ex = t.closest('[data-wa-ex]');
    if (ex) { const q = ex.querySelector('.q'); fill((q || ex).textContent); return; }
    const tool = t.closest('[data-wa-tool]');
    if (tool) { closeMenu(); fill(EXAMPLES[tool.dataset.waTool] || tool.textContent); return; }
    const op = t.closest('[data-wa-open]');
    if (op) {
      const w = (W.mine || []).filter(x => x.key === op.dataset.waOpen)[0];
      if (w) guard(TX.dirtyOpen, TX.open, () => openWidget(w));
      return;
    }
    const gp = t.closest('[data-wa-grp]');
    if (gp) { W.group = gp.dataset.waGrp; if (W.paintPop) W.paintPop(); const f = root.querySelector('.wa-pop.am .wa-mi'); if (f) f.focus(); return; }
    const nx = t.closest('[data-wa-next]');
    if (nx) { send(nx.dataset.waNext, { keepInput: true }); return; }
    const opt = t.closest('[data-wa-opt]');
    if (opt) { W.askForm.opt = W.askForm.opt === opt.dataset.waOpt ? '' : opt.dataset.waOpt; W.askForm.err = ''; paintChat(); return; }
    const hs = t.closest('[data-wa-hist]');
    if (hs) { if (!hs.disabled) peekAt(hs.dataset.waHist); return; }
    const sz = t.closest('[data-wa-size]');
    if (sz) { if (!sz.disabled) { const p = sz.dataset.waSize.split(':'); setSize(p[0], +p[1]); } return; }
    const fd = t.closest('[data-wa-fold]');
    if (fd) { const m = W.msgs[+fd.dataset.waFold]; if (m) { m.fold = !m.fold; paintChat(); } return; }
    const mo = t.closest('[data-wa-more]');
    if (mo) { const k = mo.dataset.waMore; W.open[k] = !W.open[k]; paintChat(); return; }
    const tk = t.closest('[data-wa-tk]');
    if (tk) { const k = tk.dataset.waTk; W.fold[k] = !W.fold[k]; paintChat(); return; }
    const qe = t.closest('[data-wa-qedit]');
    if (qe) {
      const it = W.queue.splice(+qe.dataset.waQedit, 1)[0];
      paintQueue();
      if (it) {   // 그 요청의 가져올 곳도 입력 카드로 / the request's place goes back to the input card too
        const v = it.source || 'auto';
        W.scope = v === 'web' ? 'web' : v === 'auto' ? 'auto' : 'internal';
        W.res = v === 'data' || v === 'docs' ? [v] : [];
        paintBar(); fill(it.text);
      }
      return;
    }
    const qd = t.closest('[data-wa-qdel]');
    if (qd) { W.queue.splice(+qd.dataset.waQdel, 1); paintBar(); return; }
    const tb = t.closest('[data-wa-tab]');
    if (tb) { W.tab = tb.dataset.waTab; paintSide(); tr(); return; }
    const act = t.closest('[data-wa-act]');
    if (act) {
      const a = act.dataset.waAct, i = +act.dataset.mi;
      if (a === 'copy') { const m = W.msgs[i]; if (m && m.text) copy(m.text); }
      else if (a === 'undo-turn') { const m = W.msgs[i]; if (m && m.beforeId) restoreTo(m.beforeId); }
      else if (a === 'retry') retry(i);
      else if (a === 'res') focusInfo();
      else if (a === 'ask-go') askGo(i);
      else if (a === 'restore') { if (W.peek) restoreTo(W.peek.id); }
      else if (a === 'peek-close') { W.peek = null; paint(); }
      else if (a === 'refresh') refreshNow();
      else if (a === 'q-toggle') { W.qfold = !W.qfold; paintQueue(); }
      else if (a === 'put-home') putHome();
      else if (a === 'delete') askDelete();
      return;
    }
    const b = t.closest('[data-wa]');
    if (!b || b.disabled) return;
    const k = b.dataset.wa;
    if (k === 'send') { if (W.busy && W.ctrl) stop(); else send($('#waIn').value); }
    else if (k === 'mine') openMenu('mine');
    else if (k === 'plus') openMenu('plus');
    else if (k === 'scope') {   // 메인 채팅처럼 누를 때마다 자동 → 사내 → 외부 / like the main chat: auto → internal → external on each click
      const order = ['auto', 'internal', 'web'];
      W.scope = order[(order.indexOf(W.scope) + 1) % order.length];
      paintBar();
    }
    else if (k === 'res') openRes();
    else if (k === 'mic') { /* 메인 채팅 입력창처럼 모양만(음성 입력 없음) / shape only, as in the main chat composer (no voice input) */ }
    else if (k === 'new') guard(TX.dirtyNew, TX.startNew, () => reset(''));
    else if (k === 'undo') undo();
    else if (k === 'resave') { if (waHasContent(W.widget)) commit({ user: true }); else toast(U('emptyKeep')); }
    else if (k === 'close') closePanel();
    else if (k === 'rename') startRename();
  }
  function onKey(e) {
    if (e.key === 'Escape' && W.menu) { closeMenu(); return; }
    if (e.isComposing) return;   // 한글 조합 중의 Enter 는 글자 확정이다 / Enter while composing Korean confirms the syllable
    if (e.target.id === 'waAfIn' && e.key === 'Enter') { e.preventDefault(); askGo(W.askForm.mi); return; }
    if (e.target.id !== 'waIn') return;
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(e.target.value); return; }
    if (e.key === '/' && !e.target.value) { e.preventDefault(); openMenu('plus'); }
  }
  function onInput(e) {
    if (e.target.id === 'waIn') { grow(e.target); paintBar(); return; }
    if (e.target.id === 'waAfIn') {
      W.askForm.text = e.target.value;
      if (W.askForm.err) { W.askForm.err = ''; const er = root.querySelector('.wa-af-er'); if (er) er.remove(); }
    }
  }

  /* ── 열기 · 닫기(2026-11-20, 14절) / opening and closing ──
     그룹웨어 머리줄의 아이콘(#waBtn)이 패널을 열고 닫는다. 만든 위젯 머리의 아이콘(static/home_dash.js)은 그 위젯과 저장된 대화를 연다.
     패널이 열려 있는 동안에는 홈의 만든 위젯 카드 어디를 눌러도 그 위젯으로 대화 상대가 바뀐다(2026-11-21, static/home_dash.js 가 open(키)를 부른다).
     닫아도 돌던 턴은 계속 돌고(아이콘에 점) 끝나면 홈에 반영된다. 보안 · 전자결재 화면으로 가거나 배치 편집을 열면 닫힌다.
     #waBtn in the groupware header opens and closes the panel; the icon on a made widget (static/home_dash.js) opens that widget with its saved
     conversation. While the panel is open, a click anywhere on a made widget card switches the conversation to it (2026-11-21; home_dash.js calls open(key)).
     A running turn goes on after closing (a dot on the icon) and still lands on Home; leaving for the security or e-Approval
     screen, or opening layout editing, closes the panel. */
  function setShown(on) {
    W.shown = !!on;
    document.body.classList.toggle('wa-open', W.shown);
    if (!W.shown) { closeMenu(); W.peek = null; return; }
    // 위 막대 바로 아래부터(앱 안 = 60, 홈만 따로 연 화면은 머리줄만큼 더 아래) / from right under the top bar (60 inside the app; lower on the standalone page)
    const bar = hero.parentNode ? hero.parentNode.querySelector('.topbar') : null;
    if (bar && root) root.style.top = Math.max(0, Math.round(bar.getBoundingClientRect().bottom)) + 'px';
  }
  function openPanel(key) {
    if (!W.built) { build(); W.at = nowIso(); }
    else if (owner() !== W.owner) reset(dirty() || W.msgs.length ? TX.moved : '');   // 그 사이 사람이 바뀌었다 / the person changed meanwhile
    const was = W.shown;
    setShown(true);
    paint(!was);
    if (!key || key === W.key) {
      try { const hd = HD(); if (hd && hd.focus && W.key) hd.focus(W.key, true); } catch (e) { /* 홈 격자가 없다 / no home grid */ }
      const inp = $('#waIn');
      if (inp && document.hasFocus()) inp.focus({ preventScroll: true });
      return;
    }
    if (busy()) { toast(U('busyOpen')); return; }
    const me = owner();
    W.want = key;   // 이어서 다른 카드를 누르면 마지막 것만 연다 / a later click on another card wins
    loadMine().then(() => {
      if (owner() !== me || !W.shown || W.want !== key) return;
      W.want = '';
      const w = (W.mine || []).filter(x => x.key === key)[0];
      if (!w) { toast(U('openFail')); return; }
      if (busy()) { toast(U('busyOpen')); return; }
      guard(TX.dirtyOpen, TX.open, () => openWidget(w));
    });
  }
  function closePanel() {
    if (!W.built || !W.shown) return;
    const inside = root.contains(document.activeElement);
    setShown(false);
    paint();
    const hb = document.getElementById('waBtn');
    if (inside && hb && document.hasFocus()) hb.focus({ preventScroll: true });
  }
  const headBtn = document.getElementById('waBtn');
  if (headBtn) headBtn.addEventListener('click', () => { if (W.shown) closePanel(); else openPanel(''); });
  document.addEventListener('ai365-home-seg', e => { if (e.detail && e.detail.seg !== 'gw') closePanel(); });
  // 배치 편집의 서랍에서 이 위젯을 지웠다(static/home_dash.js): 쉬고 있으면 처음 상태로, 일하는 중이면 턴이 끝난 뒤에 본다(다시 만들지 않는다 — 독립 검토)
  // this widget was deleted in the layout-editing drawer: reset when idle; while a turn runs it is handled when the turn ends (never re-created)
  document.addEventListener('ai365-home-widget-deleted', e => {
    if (!W.built || !W.key || !e.detail || e.detail.key !== W.key) return;
    if (busy()) { W.goneKey = W.key; return; }
    reset('');
  });
  // 홈 격자가 다시 그려지면(읽기 · 배치 저장 · 너비 변화) 그 자리 그리기 · 강조를 다시 맞추고, 열려 있으면 크기 칸 · '홈에 없음' 알림도
  // when the home grid is redrawn (a read, a layout save, a width change) the in-place drawing and the mark are re-applied, plus the size cells and the off-Home notice while open
  document.addEventListener('ai365-home-dash', () => {
    if (!W.built) return;
    paintHome();
    if (W.shown) { paintSide(); tr(); }
  });
  // 부모 앱이 홈을 다시 열면(신원이 바뀌었을 수 있다) 사람을 다시 본다 / when the parent reopens the home (the identity may have changed) the person is re-checked
  window.addEventListener('message', e => {
    const d = e.data || {};
    if (e.origin !== location.origin || !d || d.type !== 'ai365-home-entry' || !W.built) return;
    if (owner() !== W.owner && !W.busy) reset(dirty() || W.msgs.length ? TX.moved : '');
  });
  window.addEventListener('storage', e => {
    if (e.key !== 'ai365_lang' || !W.built) return;
    paintChat(); paintBar(); paintSide();
    setTimeout(() => { if (root) grow($('#waIn')); }, 0);   // 사전이 안내 글을 바꾼 뒤에 / after the dictionary swaps the hint
    if (W.menu) { const kind = W.menu; closeMenu(); openMenu(kind); }
  });
  window.AI365_widgetAgent = { open: openPanel, close: closePanel, show: () => openPanel(''), state: () => ({ key: W.key, widget: W.widget, model: W.model, msgs: W.msgs.slice(), dirty: dirty(), busy: W.busy || W.wait > 0,
    undo: W.undo.length, queue: W.queue.slice(), source: waSourceOf(W.scope, W.res), scope: W.scope, res: W.res.slice(), label: W.label, peek: W.peek ? W.peek.id : '',
    shown: W.shown, tab: W.tab }) };
})();
