// 실행: Playwright 가 NODE_PATH 에 있을 때 node --test --test-concurrency=1 tests/test_agentic_phase2_ui.cjs
// Agentic 모드 셸 2차 · 3차(static/agentic.js, 2026-10-19, 내부 계약 2 의 H 절 + 프런트 적대 검토 반영): 슬래시 팝업(거르기 · 키보드 · ARIA ·
// /plan · /clear 와 옛 세션 seen) · 실행 중 스티어링(mode steer · 전달 대기 말풍선 · user steer 태그 · 합쳐진 새 턴 · 전달되지 않음) · 플랜 카드 ·
// 서브에이전트 task 카드 중첩(자식 · 프리셋 · 거절된 중첩 task · 병렬 서브에이전트 연결 · 서랍 행) · 훅 줄 · 압축 칩(서브에이전트 안 포함) · 완료 알림 줄 ·
// 체크포인트 ⟲(살아 있는 것만 · 정리된 것 404) · Connectors(사용할 수 없음 보존) · Changes(diff · 체크포인트 · 커밋 제안) · Outputs(내려받기 · 실패 토스트) ·
// 세션 메뉴 완료 알림 · 사이드바 미확인 점과 seen · 상태가 바뀌어도 제자리 · 서버 글의 마크업 이스케이프 · EN 라벨 · state() 요약.
// 목업 + adapter + agentic.js 를 가짜 원점에 올리고 /api/agentic/* 는 page.route 메모리 스텁(계약 2 의 F · B · E9 모양, 세션은 2차 모양)이다.
// /stream 은 새 이벤트가 생길 때까지 잠깐 기다렸다가 답하고 끝난다(EventSource 가 다시 붙고 after 로 중복이 없다). 앱 서버 · DB · LLM 없음.
// Run with Playwright on NODE_PATH: node --test --test-concurrency=1 tests/test_agentic_phase2_ui.cjs
// The Agentic shell, phases 2 and 3 (static/agentic.js, 2026-10-19, section H of the internal contract 2 plus the front-end adversarial
// review): the slash popup (filter, keyboard, ARIA, /plan, /clear and the old session's seen report), steering while running (mode
// steer, the pending bubble, the user steer tag, a merged new turn, undelivered texts), the plan card, nested subagent task cards
// (children, preset, a refused nested task, linking parallel subagents, drawer rows), hook lines, compact chips (inside subagents too),
// the completion-notice line, checkpoint restore (live ones only, a cleaned-up one answers 404), Connectors (unavailable ids kept),
// Changes (diff, checkpoint, commit suggestion), Outputs (download and failure toast), the notify menu item, the sidebar's unseen dot
// with seen reports, staying in place across status changes, escaping markup in server strings, English labels and state().
// The mockup, adapter and agentic.js run on a fake origin; /api/agentic/* is an in-memory page.route stub shaped like contract 2
// (sections F, B and E9, phase-2 sessions). /stream waits briefly for new events, answers and ends (EventSource reconnects and `after`
// keeps it free of duplicates). No app server, DB or LLM.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const read = rel => fs.readFileSync(path.join(__dirname, '..', rel), 'utf8').replace(/\r\n/g, '\n');
const mockup = read('frontend/ai365-mockup.html');
const adapter = read('static/adapter.js');
const agentic = read('static/agentic.js');
const ORIGIN = 'http://ag2.test';
const HTML = mockup.replace('</body>', '<script src="/static/adapter.js"></script><script src="/static/agentic.js"></script></body>');
const SHOTS = process.env.AI365_SHOTS || '';

const DESK = 'C:\\Users\\demo\\Desktop', DOCS = 'C:\\Users\\demo\\Documents';
const PA = DESK + '\\proj-a', NOTES = DOCS + '\\notes', PX = DESK + '\\proj-x';
const MODELS = [
  { id: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash' },
  { id: 'gemini-3.7-flash', label: 'Gemini 3.7 Flash' },
  { id: 'gemini-3.5-flash-lite', label: 'Gemini 3.5 Flash-Lite' },
];
const B = (name, description, args) => ({ name, description, source: 'builtin', args: args || '' });
const COMMANDS = [   // 계약 2 F: 이름순, 내장 먼저 / contract 2 F: by name, built-ins first
  B('help', '명령 · 스킬 목록'), B('compact', '컨텍스트를 요약으로 접습니다'), B('plan', '플랜 모드로 바꿉니다'), B('auto', 'Auto 모드로 바꿉니다'), B('ask', '묻기 모드로 바꿉니다'),
  B('model', '모델을 바꿉니다', '<id>'), B('clear', '같은 설정으로 새 세션'), B('checkpoint', '체크포인트를 만듭니다', '[label]'), B('undo', '마지막 체크포인트로 되돌립니다'),
  B('commit', '변경 사항을 커밋합니다', '<message>'), B('cost', '스텝 · 시간 · 토큰'), B('init', 'AGENTS.md 를 만듭니다'), B('notify', '완료 알림', 'on|off'),
  B('skills', '스킬 목록'), B('hooks', '훅 목록'), B('connectors', '연결 도구 목록'),
  { name: 'deploy', description: '배포 절차를 따라 합니다', source: 'folder', args: '<env>' },
  { name: 'standup', description: '오늘 한 일을 정리합니다', source: 'global', args: '' },
  { name: 'pdf', description: 'PDF 를 다루는 방법', source: 'skill', args: '' },
];
const CONNS = [
  { id: 'mcp_a', name: '사내 위키 검색', description: '위키 문서를 찾습니다', kind: 'read', server_name: '위키 MCP', tool: 'search', inputs: [{ name: 'query', type: 'string', required: true, description: '검색어' }] },
  { id: 'mcp_b', name: '메일 보내기', description: '메일을 보냅니다', kind: 'action', server_name: '메일 MCP', tool: 'send', inputs: [] },
];
const DIFF_APP = '--- a/src/app.js\n+++ b/src/app.js\n@@ -1,2 +1,3 @@\n-console.log(1);\n+console.log(2);\n+export default 2;\n';
// 마크업이 든 서버 글(이스케이프 확인용) / server strings carrying markup (for the escaping checks)
const X = n => '<img src=x onerror="window.__xss=' + n + '">';

function sess(o) {
  return Object.assign({ owner: '', title: '', folder: '', extra_folders: [], model: 'gemini-3.8-flash', effort: 'auto', perm_mode: 'auto', status: 'idle',
    context_pct: 0, rules: [], steps: 0, last_seq: 0, created: '2026-10-19T09:00:00', updated: '2026-10-19T09:00:00',
    connectors: [], notify: false, seen_seq: 0, prev_perm: '', hooks_trust: '', compact_seq: 0 }, o);
}
// 계약 2 A: light 에 notify · seen_seq · last_seq / contract 2 A: light carries notify, seen_seq and last_seq
const light = s => ({ id: s.id, title: s.title, folder: s.folder, model: s.model, perm_mode: s.perm_mode, status: s.status, updated: s.updated, created: s.created,
  steps: s.steps, notify: s.notify, seen_seq: s.seen_seq, last_seq: s.last_seq });
const file = (p, content) => ({ kind: 'file', path: p, content, truncated: false, size: Buffer.byteLength(content) });
const cpRow = (id, seq, label) => ({ id, seq, ref: 'refs/ai365/checkpoints/' + id, commit: 'c0ffee' + id.length, label, files: 12, ts: '2026-10-19T14:40:00' });

function makeDb() {
  let clock = 0;
  const db = {
    host: 'DEMO-PC', n: 0, calls: [], queued: [], steered: [], suggest: 'README 정리 / Tidy the README', dlFail: '',
    now: () => { clock += 1; return '2026-10-19T15:' + String(10 + Math.floor(clock / 60)).padStart(2, '0') + ':' + String(clock % 60).padStart(2, '0'); },
    settings: { allowed_folders: [DESK, DOCS], default_perm: 'auto', default_model: 'gemini-3.8-flash', deny_commands: [],
      budgets: { max_steps: 200, max_minutes: 120, max_sessions: 3, bash_timeout_sec: 120, max_output_chars: 20000, compact_pct: 80, max_subagents: 3, subagent_max_steps: 60 },
      notify_default: false, commands: [], skills: [], hooks: [] },
    commands: COMMANDS.slice(), conns: CONNS.slice(),
    sessions: [
      sess({ id: 'ag_p1', title: '플랫폼 리팩터', folder: PA, connectors: ['mcp_a', 'mcp_gone'], context_pct: 1, steps: 6, updated: '2026-10-19T14:50:00' }),
      sess({ id: 'ag_p2', title: '배포 계획', folder: PA, perm_mode: 'plan', prev_perm: 'ask', updated: '2026-10-19T12:00:00' }),
      sess({ id: 'ag_p3', title: '메모 정리', folder: NOTES, updated: '2026-10-18T09:00:00' }),
      sess({ id: 'ag_x', title: '<b>마크업</b> 세션' + X(30), folder: PX, updated: '2026-10-17T09:00:00' }),
    ],
    events: { ag_p1: [], ag_p2: [], ag_p3: [], ag_x: [] },
    git: { ag_p1: { repo: true, branch: 'main' }, ag_p2: { repo: true, branch: 'main' }, ag_p3: { repo: false }, ag_x: { repo: true, branch: 'x' } },
    cps: { ag_p1: [cpRow('cp_1', 1, '턴 시작 · 코드 구조를 조사하고 리뷰해 줘')], ag_p2: [], ag_p3: [], ag_x: [cpRow('cp_x', 1, X(23) + '라벨')] },   // 살아 있는 체크포인트 / live checkpoints
    changes: {
      ag_p1: { repo: true, branch: 'main', added: 12, removed: 2, count: 3, truncated: false, last_checkpoint: null, files: [
        { path: 'src/app.js', status: 'M', added: 10, removed: 2, binary: false },
        { path: 'docs/new.md', status: '?', added: 2, removed: 0, binary: false },
        { path: 'logo.png', status: 'M', added: 0, removed: 0, binary: true },
      ] },
      ag_p2: { repo: true, branch: 'main', added: 0, removed: 0, count: 0, truncated: false, last_checkpoint: null, files: [] },
      ag_p3: { repo: false, branch: null, added: 0, removed: 0, count: 0, truncated: false, last_checkpoint: null, files: [] },
      ag_x: { repo: true, branch: X(24), added: 1, removed: 0, count: 1, truncated: false, last_checkpoint: { id: 'cp_x', label: X(25), ts: '2026-10-17T09:00:00' },
        files: [{ path: X(26) + '.js', status: 'M', added: 1, removed: 0, binary: false }] },
    },
    diffs: {
      'src/app.js': { path: 'src/app.js', status: 'M', unified: DIFF_APP, binary: false, truncated: false },
      'logo.png': { path: 'logo.png', status: 'M', unified: '', binary: true, truncated: false },
    },
    outputs: {
      ag_p1: [
        { path: PA + '\\docs\\report.md', rel: 'docs/report.md', kind: 'created', bytes: 2048, ts: '2026-10-19T14:49:00', exists: true },
        { path: PA + '\\README.md', rel: 'README.md', kind: 'modified', bytes: 1200, ts: '2026-10-19T14:48:00', exists: true },
        { path: PA + '\\tmp.txt', rel: 'tmp.txt', kind: 'created', bytes: 10, ts: '2026-10-19T14:47:00', exists: false },
      ],
      ag_x: [{ path: PX + '\\out.md', rel: X(27) + '.md', kind: 'created', bytes: 5, ts: '2026-10-17T09:00:00', exists: true }],
    },
    tasks: {
      ag_p1: [
        { id: 'sa1', kind: 'subagent', label: '코드 조사', status: 'done', started: '2026-10-19T14:40:05', ended: '2026-10-19T14:40:10', exit_code: null },
        { id: 'sa2', kind: 'subagent', label: '변경 검토', status: 'done', started: '2026-10-19T14:40:06', ended: '2026-10-19T14:40:11', exit_code: null },
        { id: 't1', kind: 'bash', label: 'npm run dev', status: 'running', started: '2026-10-19T14:30:00', ended: null, exit_code: null },
      ],
      ag_x: [{ id: 'sx', kind: 'subagent', label: X(28), status: 'done', started: '2026-10-17T09:00:00', ended: '2026-10-17T09:00:01', exit_code: null }],
    },
    files: {
      [PA]: { kind: 'dir', path: PA, entries: [{ name: 'README.md', type: 'file', size: 1200 }, { name: 'src', type: 'dir', size: 0 }] },
      [NOTES]: { kind: 'dir', path: NOTES, entries: [{ name: 'todo.md', type: 'file', size: 12 }] },
      [PX]: { kind: 'dir', path: PX, entries: [{ name: X(29) + '.txt', type: 'file', size: 3 }] },
      [PA + '\\README.md']: file(PA + '\\README.md', '# 프로젝트 A\n\nthe quick brown fox\n'),
      [PA + '\\docs\\report.md']: file(PA + '\\docs\\report.md', '# 보고서\n\n조사 결과\n'),
    },
  };
  db.push = (sid, kind, payload, ts) => {
    const evs = db.events[sid];
    evs.push({ seq: evs.length + 1, ts: ts || db.now(), kind, payload });
    const s = db.sessions.find(x => x.id === sid);
    if (s) s.last_seq = evs.length;
    return evs.length;
  };
  db.snap = sid => JSON.parse(JSON.stringify(db.sessions.find(x => x.id === sid)));
  db.sess = sid => db.sessions.find(x => x.id === sid);

  // ag_p1: 지난 턴 = 병렬 서브에이전트 둘(task 호출에 subagent.task_id, 자식 이벤트가 섞여 오고 sa2 의 자식이 먼저) · 서브에이전트 안에서 거절된
  // 중첩 task · 서브에이전트 안 압축 · 훅 · 턴 안 압축 · 완료 알림, 그 뒤 /compact 명령(정리된 체크포인트 cp_old 가 붙은 말풍선)
  // ag_p1: the previous turn = two parallel subagents (subagent.task_id on the task calls, interleaved children, sa2's first), a nested task
  // refused inside a subagent, a compaction inside a subagent, hooks, an in-turn compaction and a notice; then /compact (whose bubble has
  // the cleaned-up checkpoint cp_old)
  const at = n => '2026-10-19T14:40:' + String(n).padStart(2, '0');
  const P = (kind, payload) => db.push('ag_p1', kind, payload, at(db.events.ag_p1.length + 1));
  P('user', { text: '코드 구조를 조사하고 리뷰해 줘' });
  P('checkpoint', { id: 'cp_1', ref: 'refs/ai365/checkpoints/ag_p1/1', commit: 'abc1234def0', label: '턴 시작 · 코드 구조를 조사하고 리뷰해 줘', files: 12, action: 'create', seq: 1 });
  P('status', { state: 'running', note: '요청을 살펴보는 중', step: 0 });
  P('hook', { event: 'session_start', source: 'global', matcher: '', command: 'python hooks/start.py', exit_code: 0, output: '환경 확인 완료', duration_ms: 120, decision: 'allow', reason: '', timed_out: false });
  P('hook', { event: 'user_prompt', source: 'folder', matcher: '', command: 'node check-prompt.js', exit_code: 0, output: '', duration_ms: 40, decision: 'allow', reason: '', timed_out: false });
  P('tool_call', { call_id: 'tc1', tool: 'task', args: { description: '코드 조사', prompt: 'src 폴더 구조를 조사해 요약하라', preset: 'explorer' }, label: '서브에이전트: 코드 조사', group: 'agent', subagent: { task_id: 'sa1', preset: 'explorer' } });
  P('tool_call', { call_id: 'tc2', tool: 'task', args: { description: '변경 검토', prompt: '최근 변경을 검토하라', preset: 'reviewer' }, label: '서브에이전트: 변경 검토', group: 'agent', subagent: { task_id: 'sa2', preset: 'reviewer' } });
  P('tool_call', { call_id: 'k1', tool: 'list_dir', args: { path: 'src' }, label: 'src 목록', group: 'read', task_id: 'sa2' });
  P('tool_call', { call_id: 'k2', tool: 'read_file', args: { path: 'README.md' }, label: 'README.md 읽기', group: 'read', task_id: 'sa1' });
  P('tool_result', { call_id: 'k2', tool: 'read_file', ok: true, summary: '3줄', detail: '1\t# 프로젝트 A', duration_ms: 20, truncated: false, task_id: 'sa1' });
  P('tool_result', { call_id: 'k1', tool: 'list_dir', ok: true, summary: '2개', detail: 'app.js\nutil/', duration_ms: 10, truncated: false, task_id: 'sa2' });
  P('tool_call', { call_id: 'k3', tool: 'grep', args: { pattern: 'TODO', path: 'src' }, label: 'TODO 찾기', group: 'search', task_id: 'sa1' });
  P('tool_result', { call_id: 'k3', tool: 'grep', ok: true, summary: '1곳', detail: 'src/app.js:3:// TODO', duration_ms: 15, truncated: false, task_id: 'sa1' });
  P('assistant', { text: '구조를 정리하는 중입니다.', task_id: 'sa1' });
  P('tool_call', { call_id: 'k4', tool: 'bash', args: { command: 'git log --oneline -3' }, label: 'git log 실행', group: 'run', task_id: 'sa1' });
  P('tool_result', { call_id: 'k4', tool: 'bash', ok: true, summary: '3줄', output: 'abc1234 fix\ndef5678 feat\n0a1b2c3 init', exit_code: 0, duration_ms: 90, truncated: false, task_id: 'sa1' });
  P('hook', { event: 'pre_tool', source: 'folder', matcher: 'bash', command: 'python guard.py', exit_code: 2, output: 'rm 은 막습니다', duration_ms: 30, decision: 'block', reason: '위험한 명령', timed_out: false, call_id: 'k5', task_id: 'sa2' });
  P('tool_call', { call_id: 'kx', tool: 'task', args: { description: '중첩 조사', prompt: '더 깊이 조사하라', preset: 'explorer' }, label: '서브에이전트: 중첩 조사', group: 'agent', task_id: 'sa1' });
  P('tool_result', { call_id: 'kx', tool: 'task', ok: false, summary: '서브에이전트 안에서는 쓸 수 없음', detail: '서브에이전트는 task 를 부를 수 없습니다', duration_ms: 0, truncated: false, task_id: 'sa1' });
  P('compact', { scope: 'turn', text: '서브에이전트 앞부분 요약', upto_seq: 17, chars_before: 9000, chars_after: 1200, task_id: 'sa2' });
  P('tool_result', { call_id: 'tc1', tool: 'task', ok: true, summary: '조사 완료', detail: '## 조사 결과\n- src 에는 app.js 하나뿐입니다.', duration_ms: 5200, truncated: false, subagent: { task_id: 'sa1', preset: 'explorer', steps: 4, duration_ms: 5100 } });
  P('tool_result', { call_id: 'tc2', tool: 'task', ok: true, summary: '검토 완료', detail: '문제 없음', duration_ms: 6100, truncated: false, subagent: { task_id: 'sa2', preset: 'reviewer', steps: 1, duration_ms: 6000 } });
  P('compact', { scope: 'turn', text: '앞부분 요약: 조사와 검토를 마쳤다.', upto_seq: 22, chars_before: 123000, chars_after: 21000 });
  P('assistant', { text: '조사와 검토를 마쳤습니다.' });
  P('hook', { event: 'stop', source: 'global', matcher: '', command: 'python hooks/stop.py', exit_code: 0, output: '', duration_ms: 60000, decision: 'allow', reason: '', timed_out: true });
  P('summary', { text: '조사 · 검토', steps: 6, duration_ms: 12000, tokens_est: 5000 });
  P('context', { pct: 23 });
  P('notify', { ok: true, to: ['me@example.com'], backend: 'outlook', error: '' });
  P('status', { state: 'idle' });
  const cmdSeq = P('user', { text: '/compact', command: 'compact' });
  P('checkpoint', { id: 'cp_old', ref: 'refs/ai365/checkpoints/ag_p1/0', commit: '0ld0ld0', label: '오래된 체크포인트', files: 3, action: 'create', seq: cmdSeq });   // 서버가 50개 초과로 정리함 / trimmed by the server past 50
  P('compact', { scope: 'history', text: '이전 대화 요약: 구조 조사와 리뷰를 마쳤다.', upto_seq: 29, chars_before: 48000, chars_after: 3200 });
  P('context', { pct: 1 });
  P('assistant', { text: '컨텍스트를 압축했습니다(48,000자 → 3,200자).', command: true });
  db.sess('ag_p1').seen_seq = db.sess('ag_p1').last_seq;   // 다 본 세션 / fully seen

  // ag_p2: 플랜 모드의 답(계획) + 실패한 완료 알림 / ag_p2: a plan-mode answer and a failed notice
  const Q = (kind, payload) => db.push('ag_p2', kind, payload, '2026-10-19T11:59:' + String(db.events.ag_p2.length + 1).padStart(2, '0'));
  Q('user', { text: '배포 절차를 정리해 줘' });
  Q('status', { state: 'running', step: 0 });
  Q('tool_call', { call_id: 'p1', tool: 'read_file', args: { path: 'deploy.sh' }, label: 'deploy.sh 읽기', group: 'read' });
  Q('tool_result', { call_id: 'p1', tool: 'read_file', ok: true, summary: '20줄', detail: '…', duration_ms: 12, truncated: false });
  Q('assistant', { text: '## 계획\n1. `deploy.sh` 의 경로를 고친다\n2. 테스트로 확인한다', plan: true });
  Q('summary', { text: '계획', steps: 1, duration_ms: 3000, tokens_est: 900 });
  Q('context', { pct: 2 });
  Q('notify', { ok: false, to: [], backend: '', error: '메일 서버에 연결하지 못했습니다' });
  Q('status', { state: 'idle' });
  db.sess('ag_p2').seen_seq = db.sess('ag_p2').last_seq;

  // ag_p3: 다른 데서 이어진 활동(미확인) / ag_p3: activity elsewhere, not seen yet
  db.push('ag_p3', 'user', { text: '메모를 정리해 줘' }, '2026-10-18T08:59:00');
  db.push('ag_p3', 'status', { state: 'running' }, '2026-10-18T08:59:01');
  db.push('ag_p3', 'assistant', { text: '메모를 정리했습니다.' }, '2026-10-18T08:59:30');
  db.push('ag_p3', 'status', { state: 'idle' }, '2026-10-18T08:59:31');
  db.sess('ag_p3').seen_seq = 1;

  // ag_x: 모든 서버 글에 마크업(이스케이프 확인) / ag_x: markup in every server string (escaping checks)
  const XP = (kind, payload) => db.push('ag_x', kind, payload, '2026-10-17T08:59:' + String(db.events.ag_x.length + 1).padStart(2, '0'));
  XP('user', { text: X(1) + '사용자 글', command: '', expanded: X(2) });
  XP('checkpoint', { id: 'cp_x', ref: 'r', commit: 'x1x2x3x', label: X(23) + '라벨', files: 1, action: 'create', seq: 1 });
  XP('status', { state: 'running', note: X(3), step: 1 });
  XP('tool_call', { call_id: 'x1', tool: 'bash', args: { command: 'echo "<script>window.__xss=4</script>"' }, label: X(5) + '명령', group: 'run' });
  XP('tool_result', { call_id: 'x1', tool: 'bash', ok: true, summary: '<b>요약</b>', output: X(6) + '출력', exit_code: 0, duration_ms: 5, truncated: false });
  XP('tool_call', { call_id: 'x2', tool: 'read_file', args: { path: X(7) + '.md' }, label: '읽기 <svg onload="window.__xss=8">', group: 'read' });
  XP('tool_result', { call_id: 'x2', tool: 'read_file', ok: false, summary: '실패', detail: '<script>window.__xss=9</script>세부', duration_ms: 1, truncated: false });
  XP('hook', { event: 'pre_tool', source: 'folder', matcher: X(10), command: X(11), exit_code: 2, output: X(12) + '훅 출력', duration_ms: 3, decision: 'block', reason: '<i>' + X(13) + '</i>', timed_out: false });
  XP('compact', { scope: 'turn', text: X(14) + '요약', upto_seq: 7, chars_before: 20000, chars_after: 3000 });
  XP('tool_call', { call_id: 'x3', tool: 'task', args: { description: X(15), prompt: '<script>window.__xss=16</script>', preset: '"><img src=x onerror="window.__xss=17">' }, label: '서브에이전트: ' + X(18), group: 'agent', subagent: { task_id: 'sx', preset: '"><img src=x>' } });
  XP('tool_result', { call_id: 'x3', tool: 'task', ok: true, summary: X(19), detail: X(20) + '결과', duration_ms: 2, truncated: false, subagent: { task_id: 'sx', preset: 'reviewer', steps: 0, duration_ms: 1 } });
  XP('assistant', { text: '답 ' + X(21) + ' 끝' });
  XP('notify', { ok: false, to: [], backend: '', error: X(22) });
  XP('approval', { approval_id: 'ax', call_id: 'x1', tool: 'bash', args: { command: X(31) }, label: X(32), reason: 'ask_mode', decision: 'allow', decided_at: '2026-10-17T08:59:59' });
  XP('summary', { text: X(33), steps: 1, duration_ms: 10, tokens_est: 10 });
  XP('status', { state: 'idle' });
  db.sess('ag_x').seen_seq = db.sess('ag_x').last_seq;
  return db;
}

async function stream(route, db, sid, afterSeq) {
  const t0 = Date.now();
  while (Date.now() - t0 < 2500 && !(db.events[sid] || []).some(e => e.seq > afterSeq)) await new Promise(r => setTimeout(r, 40));
  const evs = (db.events[sid] || []).filter(e => e.seq > afterSeq);
  const body = evs.length ? evs.map(e => 'id: ' + e.seq + '\ndata: ' + JSON.stringify(e) + '\n\n').join('') : ': ping\n\n';
  try {
    await route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream; charset=utf-8', 'cache-control': 'no-cache' }, body });
  } catch (e) { /* 페이지 · 요청이 먼저 닫힘 / the page or the request closed first */ }
}

// 턴 끝 이벤트(계약 2 B 순서의 줄인 모양) / turn-end events (a shortened contract 2 B order)
function finishTurn(db, sid, text) {
  const s = db.sess(sid);
  db.push(sid, 'assistant', { text });
  db.push(sid, 'summary', { text: '끝', steps: 1, duration_ms: 2000, tokens_est: 800 });
  db.push(sid, 'context', { pct: 3 });
  db.push(sid, 'status', { state: 'idle' });
  s.status = 'idle'; s.updated = db.now();
}
// 턴 시작(저장소면 턴 체크포인트 먼저) / a turn start (a turn checkpoint first in a repository)
function beginTurn(db, sid, userPayload, note) {
  const s = db.sess(sid), us = db.push(sid, 'user', userPayload);
  if ((db.git[sid] || {}).repo) {
    const cp = cpRow('cp_t' + us, us, '턴 시작 · ' + String(userPayload.text).slice(0, 40));
    db.cps[sid].push(cp);
    db.push(sid, 'checkpoint', { id: cp.id, ref: cp.ref, commit: cp.commit, label: cp.label, files: cp.files, action: 'create', seq: us });
  }
  s.status = 'running'; s.updated = db.now();
  db.push(sid, 'status', { state: 'running', note: note || '작업 중', step: 1 });
  return us;
}

async function agenticRoute(route, db, url, p) {
  const req = route.request(), method = req.method(), q = Object.fromEntries(url.searchParams);
  let body = null;
  try { body = req.postData() ? JSON.parse(req.postData()) : null; } catch (e) { body = null; }
  db.calls.push({ method, path: p, q, body });
  const json = (obj, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(obj) });
  const rest = p.slice('/api/agentic'.length);
  if (rest === '/models') return json({ models: MODELS });
  if (rest === '/settings') return json({ settings: db.settings, host: db.host });
  if (rest === '/connectors') return json({ connectors: db.conns });
  if (rest === '/sessions' && method === 'GET') return json({ sessions: db.sessions.slice().sort((a, b) => b.updated.localeCompare(a.updated)).map(light) });
  const m = /^\/sessions\/([^/]+)(\/.*)?$/.exec(rest);
  if (!m) return json({ detail: 'no route' }, 404);
  const sid = decodeURIComponent(m[1]), tail = m[2] || '', s = db.sess(sid);
  if (!s) return json({ detail: '세션이 없습니다' }, 404);
  const evs = db.events[sid] || (db.events[sid] = []);
  const busy = s.status === 'running' || s.status === 'waiting';
  if (!tail && method === 'GET') return json({ session: s, git: db.git[sid] || { repo: false } });
  if (!tail && method === 'PATCH') {
    if ('perm_mode' in body && body.perm_mode !== s.perm_mode) {   // 계약 2 E5: plan 으로 들어갈 때 이전 모드를 둔다 / entering plan keeps the previous mode
      s.prev_perm = body.perm_mode === 'plan' ? s.perm_mode : '';
      s.perm_mode = body.perm_mode;
    }
    ['title', 'model', 'extra_folders', 'connectors', 'notify'].forEach(k => { if (k in body) s[k] = body[k]; });
    s.updated = db.now();
    return json({ session: s });
  }
  if (tail === '/events') {
    const from = Number(q.after || 0), lim = Number(q.limit || 500);
    return json({ events: evs.filter(e => e.seq > from).slice(0, lim), last_seq: evs.length });
  }
  if (tail === '/stream') return stream(route, db, sid, Number(q.after || 0));
  if (tail === '/files') { const f = db.files[q.path || s.folder]; return f ? json(f) : json({ detail: '허용 폴더 밖의 경로입니다' }, 403); }
  if (tail === '/tasks') return json({ tasks: db.tasks[sid] || [] });
  if (tail === '/commands') return json({ commands: db.commands });
  if (tail === '/seen' && method === 'POST') { s.seen_seq = Math.max(s.seen_seq, Math.min(Number(body.seq) || 0, s.last_seq)); return json({ session: s }); }
  if (tail === '/changes') return json(db.changes[sid] || { repo: false, branch: null, files: [], added: 0, removed: 0, count: 0, truncated: false, last_checkpoint: null });
  if (tail === '/changes/diff') { const d = db.diffs[q.path]; return d ? json(d) : json({ detail: '변경이 없습니다' }, 404); }
  if (tail === '/commit/suggest') return json({ message: db.suggest, files: (db.changes[sid] || { files: [] }).files.length });
  if (tail === '/commit' && method === 'POST') {
    const ch = db.changes[sid];
    if (busy) return json({ detail: '실행 중입니다' }, 409);
    if (!String(body.message || '').trim()) return json({ detail: '커밋 메시지가 비어 있습니다' }, 422);
    const n = ch.files.length;
    ch.files = []; ch.added = 0; ch.removed = 0; ch.count = 0;
    return json({ ok: true, commit: '1a2b3c4', files: n, message: body.message });
  }
  if (tail === '/outputs') return json({ outputs: db.outputs[sid] || [] });
  if (tail === '/outputs/download') {   // 서버 변경 4: 산출물 목록에 있는(있는 파일) 경로만 200 / server change 4: only listed, existing paths answer 200
    const o = (db.outputs[sid] || []).find(x => x.path === q.path && x.exists);
    if (!o || db.dlFail === q.path) return json({ detail: '산출물이 아닙니다' }, 404);
    return route.fulfill({ status: 200, headers: { 'content-type': 'text/markdown; charset=utf-8', 'content-disposition': 'attachment; filename="' + o.rel.split('/').pop() + '"' }, body: '# 보고서\n' });
  }
  if (tail === '/checkpoints' && method === 'GET') return json({ checkpoints: (db.cps[sid] || []).slice().reverse() });
  if (tail === '/checkpoints' && method === 'POST') {
    if (busy) return json({ detail: '실행 중입니다' }, 409);
    const cp = cpRow('cp_m' + (++db.n), null, '수동 체크포인트');
    db.cps[sid].push(cp);
    db.changes[sid].last_checkpoint = cp;
    db.push(sid, 'checkpoint', { id: cp.id, ref: cp.ref, commit: cp.commit, label: cp.label, files: cp.files, action: 'create' });
    return json({ checkpoint: cp });
  }
  const rm = /^\/checkpoints\/([^/]+)\/restore$/.exec(tail);
  if (rm && method === 'POST') {
    if (busy) return json({ detail: '실행 중에는 되돌릴 수 없습니다' }, 409);
    const cid = decodeURIComponent(rm[1]), cp = (db.cps[sid] || []).find(c => c.id === cid);
    if (!cp) return json({ detail: '체크포인트를 찾을 수 없습니다' }, 404);   // 정리됨 / cleaned up
    // 서버는 되돌리기 전 지금 상태를 먼저 저장한다(seq 없음) / the server first saves the current state (no seq)
    const safe = cpRow('cp_s' + (++db.n), null, '되돌리기 전 자동 저장');
    db.cps[sid].push(safe);
    db.push(sid, 'checkpoint', { id: safe.id, ref: safe.ref, commit: safe.commit, label: safe.label, files: safe.files, action: 'create' });
    db.push(sid, 'checkpoint', { id: cp.id, ref: cp.ref, commit: cp.commit, label: cp.label, files: cp.files, action: 'restore' });
    s.updated = db.now();
    return json({ checkpoint: cp, session: s });
  }
  if (tail === '/messages') {
    const text = String(body.text || '').trim();
    // 계약 2 E9: 내장 · 등록된 이름만 명령, 그 밖의 "/단어" 는 일반 글 / contract 2 E9: only built-in and registered names are commands, any other "/word" is plain text
    const sm = /^\s*\/([a-z0-9_-]+)(?:\s+([\s\S]*))?$/i.exec(text), cmd = sm ? db.commands.find(c => c.name === sm[1].toLowerCase()) : null;
    if (cmd) {
      if (busy) return json({ detail: '실행 중에는 명령을 쓸 수 없습니다' }, 409);
      const name = cmd.name, args = (sm[2] || '').trim();
      if (cmd.source !== 'builtin') {   // 사용자 명령 · 스킬 = 프롬프트 확장 뒤 일반 턴 / user commands and skills expand into a normal turn
        const key = cmd.source === 'skill' ? 'skill' : 'command';
        beginTurn(db, sid, { text, [key]: name, expanded: '[' + name + '] ' + (args || '위 지시를 적용해 작업하라') });
        const snap = db.snap(sid);
        finishTurn(db, sid, name + ' 를 마쳤습니다.');
        return json({ command: name, queued: false, steered: false, session: snap });
      }
      db.push(sid, 'user', { text, command: name });
      if (name === 'plan' || name === 'auto' || name === 'ask') {
        s.prev_perm = name === 'plan' ? s.perm_mode : '';
        s.perm_mode = name;
        db.push(sid, 'assistant', { text: name === 'plan' ? '플랜 모드로 바꿨습니다. 읽기 · 조사만 합니다.' : name + ' 모드로 바꿨습니다.', command: true });
      } else if (name === 'clear') {
        const now = db.now();
        const ns = sess({ id: 'ag_new' + (++db.n), title: s.title + ' (새)', folder: s.folder, model: s.model, perm_mode: s.perm_mode, created: now, updated: now });
        db.sessions.push(ns); db.events[ns.id] = []; db.git[ns.id] = db.git[sid]; db.changes[ns.id] = db.changes[sid]; db.cps[ns.id] = [];
        db.push(sid, 'assistant', { text: '새 세션 「' + ns.title + '」을 만들었습니다.', command: true });
        s.updated = db.now();
        return json({ command: 'clear', queued: false, steered: false, session: ns });
      } else db.push(sid, 'assistant', { text: '`/' + name + '` 명령을 처리했습니다.', command: true });
      s.updated = db.now();
      return json({ command: name, queued: false, steered: false, session: s });
    }
    if (busy) {   // 계약 2 E2: steer · auto = 끼워 넣기, queue = 대기열 / contract 2 E2: steer and auto steer, queue queues
      if (body.mode === 'queue') { db.queued.push(text); return json({ queued: true, steered: false, session: s }); }
      db.steered.push(text);
      return json({ queued: false, steered: true, session: s });
    }
    beginTurn(db, sid, { text }, /오래/.test(text) ? '테스트 실행 중' : '작업 중');
    const snap = db.snap(sid);
    if (/오래/.test(text)) db.push(sid, 'tool_call', { call_id: 'c9', tool: 'bash', args: { command: 'npm test -- --watch' }, label: 'npm test 실행', group: 'run' });
    else finishTurn(db, sid, '요청대로 진행했습니다.');
    return json({ queued: false, steered: false, session: snap });
  }
  if (tail === '/stop') {   // 계약 2 E1: 대기 승인은 전부 거부로 닫는다 / contract 2 E1: every pending approval closes as denied
    const pend = {};
    evs.filter(e => e.kind === 'approval').forEach(e => { pend[e.payload.approval_id] = e.payload; });
    Object.values(pend).filter(a => a.decision === 'pending').forEach(a => db.push(sid, 'approval', Object.assign({}, a, { decision: 'deny', decided_at: db.now() })));
    db.push(sid, 'status', { state: 'stopped', note: '사용자가 중단했습니다' });
    s.status = 'stopped'; s.updated = db.now();
    return json({ session: s });
  }
  return json({ detail: 'no route' }, 404);
}

let browser;
before(async () => { browser = await chromium.launch({ channel: 'msedge', headless: true }); });
after(async () => { if (browser) await browser.close(); });

async function app(t, last, tweak) {
  const db = makeDb();
  if (tweak) tweak(db);
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => d.dismiss());
  t.after(async () => { await page.close(); assert.deepEqual(errors, []); });
  const handle = async route => {
    const url = new URL(route.request().url()), p = decodeURIComponent(url.pathname);
    const json = (obj, status) => route.fulfill({ status: status || 200, contentType: 'application/json', body: JSON.stringify(obj) });
    if (url.origin !== ORIGIN) return route.abort();
    if (p === '/') return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: HTML });
    if (p === '/static/adapter.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: adapter });
    if (p === '/static/agentic.js') return route.fulfill({ status: 200, contentType: 'application/javascript; charset=utf-8', body: agentic });
    if (p.startsWith('/api/agentic/')) return agenticRoute(route, db, url, p);
    if (p === '/api/access/bootstrap') return json({ pvtree: [], groups: [], members: [], teams: [] });
    if (p === '/api/boards/notifications') return json({ unread: 0, notifications: [] });
    return p.startsWith('/api/') ? json({ detail: 'stub' }, 404) : route.abort();
  };
  await page.route('**/*', route => handle(route).catch(() => {}));
  await page.goto(ORIGIN + '/');
  await page.waitForSelector('#viewHome.active .ai365-ca');
  if (last) await page.evaluate(id => localStorage.setItem('ai365_ag_last', id), last);
  return { page, db };
}
async function enter(page, sid) {
  await page.click('#viewHome [data-ca="agentic"]');
  await page.waitForSelector('.ai365-ag-sess[data-id="' + sid + '"].on');
  await page.waitForSelector('.ai365-ag-tx .ai365-ag-status', { state: 'attached' });   // 세션 본문이 그려진 뒤 / once the session body is drawn
}
async function waitFor(fn, ms) {
  const t0 = Date.now();
  while (Date.now() - t0 < (ms || 8000)) { if (await fn()) return; await new Promise(r => setTimeout(r, 30)); }
  throw new Error('timed out waiting');
}
const callsTo = (db, method, tail) => db.calls.filter(c => c.method === method && c.path.endsWith(tail));
// 목업의 #agentFeature 가 문서를 화면보다 길게 만들어 Playwright 클릭이 html 을 스크롤한다 → 캡처 전에 되돌린다
// The mockup's #agentFeature makes the document taller than the window, so Playwright clicks scroll html; reset it before a capture
const shot = async (page, name) => {
  if (!SHOTS) return;
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.evaluate(() => { document.scrollingElement.scrollTop = 0; });
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SHOTS, name) });
};
const texts = (page, sel) => page.$$eval(sel, els => els.map(e => e.textContent.trim()));
const toastIs = (page, text) => page.waitForFunction(t => (document.getElementById('toast') || {}).textContent === t, text);

test('the slash popup is an ARIA combobox list that filters, moves and fills; /plan runs, a plain "/word" is a normal turn, /clear opens the new session and reports the old one as seen', async (t) => {
  const { page, db } = await app(t);
  await enter(page, 'ag_p1');
  const aria = () => page.evaluate(() => {
    const i = document.getElementById('ai365AgInput'), l = document.getElementById('ai365AgSlash'), on = l.querySelector('.ai365-ag-scmd.on');
    return { role: i.getAttribute('role'), controls: i.getAttribute('aria-controls'), expanded: i.getAttribute('aria-expanded'), active: i.getAttribute('aria-activedescendant'),
      list: l.getAttribute('role'), label: l.getAttribute('aria-label'), onId: on ? on.id : null, onRole: on ? on.getAttribute('role') : null, onSel: on ? on.getAttribute('aria-selected') : null };
  });
  assert.deepEqual(await aria(), { role: 'combobox', controls: 'ai365AgSlash', expanded: 'false', active: null, list: 'listbox', label: '슬래시 명령', onId: null, onRole: null, onSel: null });
  await page.click('#ai365AgInput');
  await page.keyboard.type('/');
  await page.waitForSelector('.ai365-ag-slash:not([hidden]) [data-ag-cmd]');
  const all = await page.evaluate(() => ({
    names: [...document.querySelectorAll('.ai365-ag-slash [data-ag-cmd]')].map(e => e.dataset.agCmd),
    on: document.querySelector('.ai365-ag-scmd.on').dataset.agCmd,
    model: document.querySelector('[data-ag-cmd="model"]').textContent,
    badges: ['help', 'deploy', 'standup', 'pdf'].map(n => document.querySelector('[data-ag-cmd="' + n + '"] .ai365-ag-sb').textContent),
  }));
  assert.deepEqual(all.names, COMMANDS.map(c => c.name));
  assert.deepEqual([all.on, all.model, all.badges], ['help', '/model<id>모델을 바꿉니다내장', ['내장', '폴더', '전역', '스킬']]);
  assert.deepEqual(await aria(), { role: 'combobox', controls: 'ai365AgSlash', expanded: 'true', active: 'ai365AgCmd0', list: 'listbox', label: '슬래시 명령', onId: 'ai365AgCmd0', onRole: 'option', onSel: 'true' });
  assert.equal(callsTo(db, 'GET', '/ag_p1/commands').length, 1);
  await shot(page, 'ag2_1_slash.png');

  // 거르기: 이름이 'pl' 로 시작하는 것 먼저, 그다음 이름 안에 든 것 / filtering: names starting with 'pl' first, then names containing it
  await page.keyboard.type('pl');
  await page.waitForFunction(() => document.querySelectorAll('.ai365-ag-slash [data-ag-cmd]').length === 2);
  assert.deepEqual(await page.$$eval('.ai365-ag-slash [data-ag-cmd]', els => els.map(e => e.dataset.agCmd)), ['plan', 'deploy']);
  const sel = () => page.$eval('.ai365-ag-scmd.on', e => e.dataset.agCmd);
  assert.equal(await sel(), 'plan');
  await page.keyboard.press('ArrowDown');
  assert.equal(await sel(), 'deploy');
  assert.deepEqual([(await aria()).active, (await aria()).onId], ['ai365AgCmd1', 'ai365AgCmd1']);
  await page.keyboard.press('ArrowDown');   // 끝에서 처음으로 / wraps to the top
  assert.equal(await sel(), 'plan');
  await page.keyboard.press('ArrowUp');
  assert.equal(await sel(), 'deploy');
  await page.keyboard.press('ArrowUp');
  await page.keyboard.press('Tab');
  assert.deepEqual(await page.evaluate(() => [document.getElementById('ai365AgInput').value, document.querySelector('.ai365-ag-slash').hidden, document.activeElement.id]),
    ['/plan ', true, 'ai365AgInput']);
  assert.deepEqual([(await aria()).expanded, (await aria()).active], ['false', null]);
  await page.keyboard.press('Enter');
  await page.waitForSelector('.ai365-ag-msg.agent.cmd >> text=플랜 모드로 바꿨습니다');
  assert.deepEqual(callsTo(db, 'POST', '/ag_p1/messages').map(c => c.body), [{ acting_user_id: '', text: '/plan' }]);   // 실행 중이 아니면 mode 없음 / no mode when idle
  await page.waitForFunction(() => document.querySelector('[data-ag-perm]').value === 'plan');
  const after1 = await page.evaluate(() => {
    const users = [...document.querySelectorAll('.ai365-ag-msg.user')];
    return { last: users[users.length - 1].textContent, cn: users[users.length - 1].querySelector('.cn').textContent, cmdCls: users[users.length - 1].classList.contains('cmd'),
      perm: [...document.querySelectorAll('[data-ag-perm] option')].map(o => o.textContent), planCls: document.querySelector('[data-ag-perm]').classList.contains('plan'),
      pend: document.querySelectorAll('.ai365-ag-msg.pend').length };
  });
  assert.deepEqual(after1, { last: '/plan', cn: '/plan', cmdCls: true, perm: ['Auto', '묻기', '플랜'], planCls: true, pend: 0 });

  // 맞는 것이 없으면 안내 줄, Esc 로 닫는다(입력은 그대로). 등록되지 않은 "/단어" 는 일반 턴 / no match shows a note and Esc closes it; an unregistered "/word" is a normal turn
  await page.fill('#ai365AgInput', '');
  await page.click('#ai365AgInput');
  await page.keyboard.type('/zz');
  await page.waitForSelector('.ai365-ag-slash:not([hidden]) .ai365-ag-snote');
  assert.equal(await page.textContent('.ai365-ag-slash .ai365-ag-snote'), '일치하는 명령이 없습니다');
  assert.equal((await aria()).active, null);
  await page.keyboard.press('Escape');
  assert.deepEqual(await page.evaluate(() => [document.querySelector('.ai365-ag-slash').hidden, document.getElementById('ai365AgInput').value]), [true, '/zz']);
  assert.equal(callsTo(db, 'GET', '/ag_p1/commands').length, 2);   // 열 때마다 새로 읽는다 / re-read on every open
  await page.keyboard.type(' 경로를 찾아 줘');
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => [...document.querySelectorAll('.ai365-ag-msg.user')].some(e => e.textContent === '/zz 경로를 찾아 줘') && !document.querySelector('.ai365-ag-msg.pend'));
  assert.equal(await page.evaluate(() => [...document.querySelectorAll('.ai365-ag-msg.user')].pop().querySelector('.cn')), null);
  await page.waitForFunction(() => document.querySelector('.ai365-ag-status').hidden);

  // 마우스로 고르기 → 채움, 꼭 맞는 이름에서 Enter = 보내기 / a click fills; Enter on an exact name sends
  await page.fill('#ai365AgInput', '');
  await page.click('#ai365AgInput');
  await page.keyboard.type('/cl');
  await page.waitForFunction(() => document.querySelectorAll('.ai365-ag-slash [data-ag-cmd]').length === 1);
  await page.click('[data-ag-cmd="clear"]');
  assert.equal(await page.inputValue('#ai365AgInput'), '/clear ');
  await page.keyboard.press('Backspace');   // '/clear' 꼭 맞음 → 팝업이 다시 열린다 / an exact '/clear' reopens the popup
  await page.waitForSelector('.ai365-ag-slash:not([hidden]) [data-ag-cmd="clear"].on');
  await page.keyboard.press('Enter');
  await page.waitForSelector('.ai365-ag-sess[data-id="ag_new1"].on');
  assert.deepEqual(callsTo(db, 'POST', '/ag_p1/messages').map(c => c.body.text), ['/plan', '/zz 경로를 찾아 줘', '/clear']);
  await page.waitForFunction(() => document.querySelector('.ai365-ag-title .t').textContent === '플랫폼 리팩터 (새)' && !!document.querySelector('.ai365-ag-tx .ai365-ag-hint'));
  assert.equal(await page.evaluate(() => window.AI365_agentic.state().session), 'ag_new1');
  // 옛 세션은 /clear 이벤트까지 본 것으로 보고하고, 목록을 다시 읽어도 '새 활동' 점이 없다(적대 검토 L12)
  // The old session is reported as seen through its /clear events, and the re-read list shows no 'new activity' dot (review L12)
  let seenIdx = -1;
  await waitFor(() => { seenIdx = db.calls.findIndex(c => c.method === 'POST' && c.path.endsWith('/ag_p1/seen') && c.body.seq === db.sess('ag_p1').last_seq); return seenIdx >= 0; }, 9000);
  await waitFor(() => db.calls.some((c, i) => i > seenIdx && c.method === 'GET' && c.path === '/api/agentic/sessions'), 9000);   // 그 뒤 목록을 다시 읽는다 / then the list is re-read
  await page.waitForTimeout(200);
  assert.equal(await page.locator('.ai365-ag-sess[data-id="ag_p1"] .dot.unseen').count(), 0);
  assert.equal(db.sess('ag_p1').seen_seq, db.sess('ag_p1').last_seq);
});

test('while running a message is steered; merged leftover steers and undelivered texts clear the pending bubbles; commands answer 409', async (t) => {
  const { page, db } = await app(t);
  await enter(page, 'ag_p1');
  await page.fill('#ai365AgInput', '오래 걸리는 작업을 해 줘');
  await page.press('#ai365AgInput', 'Enter');
  await page.waitForSelector('[data-ag="stop"]:not([hidden])');
  await page.waitForSelector('.ai365-ag-tool[data-call="c9"]');
  assert.deepEqual(await page.evaluate(() => [document.getElementById('ai365AgInput').placeholder, document.querySelector('.ai365-ag').classList.contains('busy')]),
    ['실행 중에도 보낼 수 있습니다. 다음 단계 사이에 끼워 넣습니다', true]);
  const steer = async text => { await page.fill('#ai365AgInput', text); await page.press('#ai365AgInput', 'Enter'); await waitFor(() => db.steered.includes(text)); };
  await steer('테스트는 건너뛰어 줘');
  await page.waitForSelector('.ai365-ag-msg.pend.steer');
  assert.deepEqual(callsTo(db, 'POST', '/ag_p1/messages').map(c => c.body), [
    { acting_user_id: '', text: '오래 걸리는 작업을 해 줘' },
    { acting_user_id: '', text: '테스트는 건너뛰어 줘', mode: 'steer' },
  ]);
  const mid = await page.evaluate(() => ({
    pend: [...document.querySelectorAll('.ai365-ag-msg.pend')].map(e => [e.className, e.textContent]), queueHidden: document.querySelector('.ai365-ag-queue').hidden,
    steer: window.AI365_agentic.state().steer, input: document.getElementById('ai365AgInput').value,
  }));
  assert.deepEqual(mid, { pend: [['ai365-ag-msg pend steer', '전달 대기테스트는 건너뛰어 줘']], queueHidden: true, steer: 1, input: '' });
  assert.deepEqual(db.queued, []);
  // 서버가 다음 LLM 호출 앞에서 user steer 이벤트를 쓴다 / the server writes the user steer event before its next LLM call
  db.push('ag_p1', 'user', { text: '테스트는 건너뛰어 줘', steer: true });
  await page.waitForSelector('.ai365-ag-msg.user.steer');
  const done = await page.evaluate(() => {
    const el = document.querySelector('.ai365-ag-msg.user.steer');
    return { tag: el.querySelector('.tg').textContent, text: el.textContent, pend: document.querySelectorAll('.ai365-ag-msg.pend').length, steer: window.AI365_agentic.state().steer };
  });
  assert.deepEqual(done, { tag: '끼워 넣음', text: '끼워 넣음테스트는 건너뛰어 줘', pend: 0, steer: 0 });
  await shot(page, 'ag2_2_steer.png');

  // 승인 여러 개가 동시에 대기(도는 호출 + 서브에이전트) / several approvals pending at once (the running call and a subagent's)
  db.push('ag_p1', 'approval', { approval_id: 'a7', call_id: 'c9', tool: 'bash', args: { command: 'npm test -- --watch' }, label: 'npm test 실행', reason: 'auto_cmd', decision: 'pending', decided_at: '' });
  db.push('ag_p1', 'approval', { approval_id: 'a8', call_id: 'x1', tool: 'edit_file', args: { path: 'README.md' }, label: '[서브에이전트] README.md 편집', reason: 'ask_mode', decision: 'pending', decided_at: '', task_id: 'sa9' });
  db.push('ag_p1', 'status', { state: 'waiting', note: 'npm test 실행', step: 2 });
  db.sess('ag_p1').status = 'waiting';
  await page.waitForSelector('.ai365-ag-approval[data-aid="a8"]');
  await page.waitForFunction(() => window.AI365_agentic.state().pendingApprovals === 2);
  assert.deepEqual(await page.$$eval('.ai365-ag-approval', els => els.map(a => [a.dataset.aid, a.querySelector('.hd b').textContent, a.querySelectorAll('[data-ag-dec]').length])),
    [['a7', 'npm test 실행', 3], ['a8', '[서브에이전트] README.md 편집', 3]]);

  // 실행 중 슬래시 명령 = 409, 입력은 되돌아온다 / a slash command while running gets 409 and the text comes back
  await page.click('#ai365AgInput');
  await page.keyboard.type('/compact');
  await page.waitForSelector('.ai365-ag-slash:not([hidden]) [data-ag-cmd="compact"].on');
  await page.keyboard.press('Enter');
  await toastIs(page, '실행 중에는 명령을 쓸 수 없습니다');
  assert.deepEqual(await page.evaluate(() => [document.getElementById('ai365AgInput').value, document.querySelector('.ai365-ag-slash').hidden]), ['/compact', true]);
  assert.deepEqual(callsTo(db, 'POST', '/ag_p1/messages').pop().body, { acting_user_id: '', text: '/compact', mode: 'steer' });
  await page.fill('#ai365AgInput', '');

  // 남은 끼워 넣기 둘이 "\n\n" 으로 합쳐진 새 턴 → 대기 말풍선 둘 다 지운다(적대 검토 L11)
  // Two leftover steers merged with "\n\n" into a new turn → both pending bubbles go (review L11)
  await steer('A 도 해 줘');
  await steer('B 도 해 줘');
  await page.waitForFunction(() => window.AI365_agentic.state().steer === 2 && document.querySelectorAll('.ai365-ag-msg.pend.steer').length === 2);
  db.push('ag_p1', 'user', { text: 'A 도 해 줘\n\nB 도 해 줘' });
  await page.waitForFunction(() => [...document.querySelectorAll('.ai365-ag-msg.user')].some(e => e.textContent === 'A 도 해 줘\n\nB 도 해 줘'));
  assert.deepEqual(await page.evaluate(() => [window.AI365_agentic.state().steer, document.querySelectorAll('.ai365-ag-msg.pend').length]), [0, 0]);
  // 턴이 오류 · 예산으로 끝나 전달되지 않은 글 = 흐린 말풍선 + '전달되지 않음'(서버 변경 1) / a text never delivered (error or budget end) = a faded bubble tagged 'Not delivered' (server change 1)
  await steer('C 도 해 줘');
  await page.waitForFunction(() => window.AI365_agentic.state().steer === 1);
  db.push('ag_p1', 'user', { text: 'C 도 해 줘', steer: true, dropped: true });
  await page.waitForSelector('.ai365-ag-msg.user.dropped');
  assert.deepEqual(await page.evaluate(() => {
    const el = document.querySelector('.ai365-ag-msg.user.dropped');
    return [el.className, el.querySelector('.tg').textContent, el.textContent, window.AI365_agentic.state().steer, document.querySelectorAll('.ai365-ag-msg.pend').length];
  }), ['ai365-ag-msg user steer dropped', '전달되지 않음', '전달되지 않음C 도 해 줘', 0, 0]);
  await page.waitForFunction(() => getComputedStyle(document.querySelector('.ai365-ag-msg.user.dropped')).opacity === '0.62');   // 등장 애니메이션 뒤 흐림 / faded once the entry animation ends
  await shot(page, 'ag2_2b_dropped.png');

  // EN: 스티어링 안내 · 태그 / English placeholder and tags
  await page.click('#ai365-lang-toggle');
  await page.waitForFunction(() => document.querySelector('.ai365-ag-msg.user.steer:not(.dropped) .tg').textContent === 'Steered');
  assert.deepEqual(await page.evaluate(() => [document.getElementById('ai365AgInput').placeholder, document.querySelector('.ai365-ag-msg.user.dropped .tg').textContent]),
    ['You can send while it runs. It goes in before the next step', 'Not delivered']);
  await page.click('#ai365-lang-toggle');
  await page.waitForFunction(() => document.querySelector('.ai365-ag-msg.user.steer:not(.dropped) .tg').textContent === '끼워 넣음');

  await page.click('[data-ag="stop"]');
  await page.waitForSelector('.ai365-ag-mark.stopped');
  await page.waitForFunction(() => window.AI365_agentic.state().pendingApprovals === 0 && !document.querySelector('.ai365-ag').classList.contains('busy'));
  assert.equal(await page.$eval('#ai365AgInput', e => e.placeholder), '에이전트에게 맡길 작업을 적어 주세요');
});

test('a plan answer shows Run the plan and Stay in plan mode; Run PATCHes the previous mode, then sends the follow-up', async (t) => {
  const { page, db } = await app(t, 'ag_p2');
  await enter(page, 'ag_p2');
  await page.waitForSelector('.ai365-ag-msg.agent.plan [data-ag="plan-run"]');
  const card = await page.evaluate(() => {
    const p = document.querySelector('.ai365-ag-msg.agent.plan');
    return { head: p.querySelector('.ph').textContent, items: [...p.querySelectorAll('.pb li')].map(li => li.textContent), btns: [...p.querySelectorAll('[data-ag]')].map(b => [b.dataset.ag, b.textContent, b.disabled]),
      perm: document.querySelector('[data-ag-perm]').value, notify: document.querySelector('.ai365-ag-notify').className + '|' + document.querySelector('.ai365-ag-notify').textContent };
  });
  assert.deepEqual(card, { head: '플랜 모드', items: ['deploy.sh 의 경로를 고친다', '테스트로 확인한다'], btns: [['plan-run', '계획대로 실행', false], ['plan-stay', '플랜 모드 유지', false]],
    perm: 'plan', notify: 'ai365-ag-notify bad|완료 알림을 보내지 못했습니다: 메일 서버에 연결하지 못했습니다' });
  await shot(page, 'ag2_3_plan.png');
  await page.click('[data-ag="plan-run"]');
  await waitFor(() => callsTo(db, 'POST', '/ag_p2/messages').length === 1);
  const order = db.calls.filter(c => (c.method === 'PATCH' && c.path.endsWith('/ag_p2')) || (c.method === 'POST' && c.path.endsWith('/ag_p2/messages'))).map(c => [c.method, c.body]);
  assert.deepEqual(order, [['PATCH', { acting_user_id: '', perm_mode: 'ask' }], ['POST', { acting_user_id: '', text: '위 계획대로 진행해줘' }]]);
  await page.waitForFunction(() => [...document.querySelectorAll('.ai365-ag-msg.user')].some(e => e.textContent === '위 계획대로 진행해줘') && document.querySelectorAll('.ai365-ag-sum').length === 2);
  assert.deepEqual(await page.evaluate(() => [document.querySelector('[data-ag-perm]').value, document.querySelectorAll('.ai365-ag-msg.agent.plan .pa').length]), ['ask', 0]);

  // 다음 계획 → [플랜 모드 유지] = 버튼만 닫는다(요청 없음) / the next plan → [Stay in plan mode] just closes the buttons (no request)
  db.push('ag_p2', 'user', { text: '다시 계획해 줘' });
  db.push('ag_p2', 'assistant', { text: '## 계획\n1. 롤백 절차를 더한다', plan: true });
  await page.waitForFunction(() => document.querySelectorAll('.ai365-ag-msg.agent.plan').length === 2 && document.querySelectorAll('.ai365-ag-msg.agent.plan .pa').length === 1);
  const before2 = db.calls.length;
  await page.click('[data-ag="plan-stay"]');
  await page.waitForFunction(() => document.querySelectorAll('.ai365-ag-msg.agent.plan .pa').length === 0);
  await page.waitForTimeout(200);
  assert.equal(db.calls.filter((c, i) => i >= before2 && (c.method === 'PATCH' || c.path.endsWith('/messages'))).length, 0);
});

test('task cards nest their subagent calls (a refused nested task stays a child), link parallel subagents, and the drawer opens a card', async (t) => {
  const { page, db } = await app(t);
  await enter(page, 'ag_p1');
  await page.waitForSelector('.ai365-ag-tool[data-tool="task"][data-call="tc2"]');
  const rows = await page.evaluate(() => [...document.querySelectorAll('.ai365-ag-tx > .ai365-ag-tool[data-tool="task"]')].map(e => ({
    call: e.dataset.call, tid: e.dataset.tid, state: e.dataset.state, lb: e.querySelector('.lb').textContent, pr: e.querySelector('.ai365-ag-pr').textContent,
    prCls: e.querySelector('.ai365-ag-pr').className, sm: e.querySelector('.sm').textContent, tn: e.querySelector('.tn').textContent, du: e.querySelector('.du').textContent })));
  assert.deepEqual(rows, [
    { call: 'tc1', tid: 'sa1', state: 'ok', lb: '서브에이전트: 코드 조사', pr: 'explorer', prCls: 'ai365-ag-pr explorer', sm: '조사 완료', tn: '도구 4개', du: '5.1초' },
    { call: 'tc2', tid: 'sa2', state: 'ok', lb: '서브에이전트: 변경 검토', pr: 'reviewer', prCls: 'ai365-ag-pr reviewer', sm: '검토 완료', tn: '도구 1개', du: '6초' },
  ]);
  // 자식은 본문에 따로 그리지 않는다(거절된 중첩 task 포함, 적대 검토 L5) / children are not drawn in the body (the refused nested task included, review L5)
  assert.deepEqual(await page.evaluate(() => [document.querySelectorAll('.ai365-ag-tx > [data-task]').length, !!document.querySelector('.ai365-ag-tx > [data-call="kx"]')]), [0, false]);
  await page.click('[data-call="tc1"] > .ai365-ag-trow');
  await page.waitForSelector('[data-call="tc1"].open .ai365-ag-sub');
  const kids = await page.evaluate(() => {
    const box = document.querySelector('[data-call="tc1"] .ai365-ag-sub');
    return { tools: [...box.querySelectorAll(':scope > .ai365-ag-tool[data-task="sa1"]')].map(e => [e.dataset.call, e.dataset.tool, e.querySelector('.lb').textContent, e.dataset.state, e.classList.contains('task')]),
      text: box.querySelector('.ai365-ag-stext').textContent, prompt: document.querySelector('[data-call="tc1"] .ai365-ag-tprompt').textContent,
      result: document.querySelector('[data-call="tc1"] .ai365-ag-tres li').textContent };
  });
  assert.deepEqual(kids, { tools: [['k2', 'read_file', 'README.md 읽기', 'ok', false], ['k3', 'grep', 'TODO 찾기', 'ok', false], ['k4', 'bash', 'git log 실행', 'ok', false],
    ['kx', 'task', '서브에이전트: 중첩 조사', 'fail', false]], text: '구조를 정리하는 중입니다.', prompt: 'src 폴더 구조를 조사해 요약하라', result: 'src 에는 app.js 하나뿐입니다.' });
  await page.click('[data-call="k4"] .ai365-ag-trow');   // 자식 카드도 1차 카드처럼 펼친다 / a child card opens like a phase-1 card
  assert.equal(await page.textContent('[data-call="k4"] .ai365-ag-out'), '$ git log --oneline -3\nabc1234 fix\ndef5678 feat\n0a1b2c3 init');
  assert.equal(await page.textContent('[data-call="k4"] .ai365-ag-meta'), 'exit 0');   // 서브에이전트 task_id 는 백그라운드 작업이 아니다 / a subagent task_id is not a background task
  assert.deepEqual(await texts(page, '.ai365-ag-term .cmd'), ['$ git log --oneline -3']);   // 서브에이전트의 명령도 Terminal 에 / subagent commands show in Terminal too
  await shot(page, 'ag2_4_task.png');

  // 서랍: 서브에이전트 행(완료) + 실행 중 명령, 행을 누르면 그 카드로 / the drawer: subagent rows (done) and the running command; a row jumps to its card
  await page.click('[data-call="tc1"] > .ai365-ag-trow');   // 접기 / collapse
  await page.waitForSelector('[data-call="tc1"]:not(.open)');
  assert.deepEqual(await page.$$eval('.ai365-ag-tasks .ai365-ag-task', els => els.map(e => [e.dataset.agTask, e.querySelector('.st').className, e.querySelector('.lb').textContent])),
    [['t1', 'st run', 'npm run dev'], ['sa2', 'st ok', '변경 검토'], ['sa1', 'st ok', '코드 조사']]);
  await page.click('.ai365-ag-tasks [data-ag-task="sa2"]');
  await page.waitForSelector('[data-call="tc2"].open .ai365-ag-sub .ai365-ag-tool[data-task="sa2"]');
  assert.equal(await page.evaluate(() => { const r = document.querySelector('[data-call="tc2"]').getBoundingClientRect(), s = document.querySelector('.ai365-ag-scroll').getBoundingClientRect(); return r.top >= s.top - 1 && r.top < s.bottom; }), true);

  // 실시간 병렬 서브에이전트(호출에 subagent 가 없는 대체 경로): sa4 의 자식이 먼저 와서 잠정으로 tc3 에 붙었다가 /tasks label 로 tc4 로 옮겨진다
  // Live parallel subagents (the fallback with no subagent on the calls): sa4's child lands tentatively on tc3, then moves to tc4 once /tasks gives labels
  db.tasks.ag_p1.push({ id: 'sa3', kind: 'subagent', label: '문서 정리', status: 'running', started: '2026-10-19T15:00:00', ended: null, exit_code: null },
    { id: 'sa4', kind: 'subagent', label: '테스트 작성', status: 'running', started: '2026-10-19T15:00:00', ended: null, exit_code: null });
  db.sess('ag_p1').status = 'running';
  db.push('ag_p1', 'user', { text: '문서와 테스트를 나눠서 해 줘' });
  db.push('ag_p1', 'status', { state: 'running', note: '서브에이전트 실행 중: 문서 정리, 테스트 작성', step: 1 });
  db.push('ag_p1', 'tool_call', { call_id: 'tc3', tool: 'task', args: { description: '문서 정리', prompt: 'docs 를 정리하라', preset: 'worker' }, label: '서브에이전트: 문서 정리', group: 'agent' });
  db.push('ag_p1', 'tool_call', { call_id: 'tc4', tool: 'task', args: { description: '테스트 작성', prompt: '테스트를 쓴다', preset: 'explorer' }, label: '서브에이전트: 테스트 작성', group: 'agent' });
  db.push('ag_p1', 'tool_call', { call_id: 'k6', tool: 'glob', args: { pattern: 'tests/**' }, label: 'tests 찾기', group: 'search', task_id: 'sa4' });
  await page.waitForSelector('.ai365-ag-tool[data-call="tc4"]');
  await page.waitForFunction(() => document.querySelector('[data-call="tc4"]').dataset.tid === 'sa4' && !document.querySelector('[data-call="tc3"]').dataset.tid);
  assert.ok(callsTo(db, 'GET', '/ag_p1/tasks').length >= 2);
  db.push('ag_p1', 'tool_call', { call_id: 'k7', tool: 'read_file', args: { path: 'docs/a.md' }, label: 'docs/a.md 읽기', group: 'read', task_id: 'sa3' });
  await page.waitForFunction(() => document.querySelector('[data-call="tc3"]').dataset.tid === 'sa3');
  const live = await page.evaluate(() => ['tc3', 'tc4'].map(c => { const e = document.querySelector('[data-call="' + c + '"]'); return [e.dataset.state, e.querySelector('.ai365-ag-pr').textContent, e.querySelector('.tn').textContent]; }));
  assert.deepEqual(live, [['run', 'worker', '도구 1개'], ['run', 'explorer', '도구 1개']]);
  assert.equal(await page.textContent('.ai365-ag-status .tx'), '서브에이전트 실행 중: 문서 정리, 테스트 작성');
  await page.click('[data-call="tc4"] > .ai365-ag-trow');
  assert.deepEqual(await page.$$eval('[data-call="tc4"] .ai365-ag-sub > .ai365-ag-tool', els => els.map(e => [e.dataset.call, e.dataset.task, e.dataset.state])), [['k6', 'sa4', 'run']]);
  // 펼친 카드에는 새 자식이 바로 붙는다 / a new child is appended to an open card at once
  db.push('ag_p1', 'tool_result', { call_id: 'k6', tool: 'glob', ok: true, summary: '4개', detail: 'tests/a.py', duration_ms: 8, truncated: false, task_id: 'sa4' });
  db.push('ag_p1', 'tool_call', { call_id: 'k8', tool: 'write_file', args: { path: 'tests/test_b.py' }, label: 'tests/test_b.py 쓰기', group: 'write', task_id: 'sa4' });
  await page.waitForFunction(() => document.querySelectorAll('[data-call="tc4"] .ai365-ag-sub > .ai365-ag-tool').length === 2 && document.querySelector('[data-call="k6"]').dataset.state === 'ok');
  assert.equal(await page.textContent('[data-call="tc4"] > .ai365-ag-trow .tn'), '도구 2개');

  // task 호출 자체에 subagent.task_id 가 오면(백엔드 모양) /tasks 없이도 바로 그 카드로 / a task call carrying subagent.task_id (the backend's shape) links at once, no /tasks needed
  db.push('ag_p1', 'tool_call', { call_id: 'tc6', tool: 'task', args: { description: '정리 2', prompt: '…', preset: 'worker' }, label: '서브에이전트: 정리 2', group: 'agent' });
  db.push('ag_p1', 'tool_call', { call_id: 'tc5', tool: 'task', args: { description: '검토 2', prompt: '…', preset: 'reviewer' }, label: '서브에이전트: 검토 2', group: 'agent', subagent: { task_id: 'sa5', preset: 'reviewer' } });
  db.push('ag_p1', 'tool_call', { call_id: 'k9', tool: 'bash', args: { command: 'npm run lint' }, label: 'npm run lint 실행', group: 'run', task_id: 'sa5' });
  db.push('ag_p1', 'tool_result', { call_id: 'k9', tool: 'bash', ok: true, summary: '통과', output: '', exit_code: 0, duration_ms: 50, truncated: false, task_id: 'sa5', bg_task_id: 'bg7' });
  await page.waitForFunction(() => document.querySelector('[data-call="tc5"]') && document.querySelector('[data-call="tc5"]').dataset.tid === 'sa5');
  assert.deepEqual(await page.evaluate(() => [document.querySelector('[data-call="tc6"]').dataset.tid || '', document.querySelector('[data-call="tc5"] .tn').textContent]), ['', '도구 1개']);
  await page.click('[data-call="tc5"] > .ai365-ag-trow');
  await page.click('[data-call="k9"] .ai365-ag-trow');
  assert.equal(await page.textContent('[data-call="k9"] .ai365-ag-meta'), 'exit 0백그라운드 작업 bg7');   // 서브에이전트 안의 백그라운드 명령 = bg_task_id / a background command inside a subagent uses bg_task_id
});

test('hook lines, compact chips (a subagent compaction inside its card), the notify line and command bubbles render from the events; clicks expand them', async (t) => {
  const { page } = await app(t);
  await enter(page, 'ag_p1');
  await page.waitForSelector('.ai365-ag-hook[data-hook-event="stop"]');
  const hooks = await page.$$eval('.ai365-ag-tx > .ai365-ag-hook', els => els.map(e => [e.dataset.hookEvent, e.dataset.decision, e.querySelector('.ai365-ag-hrow').textContent, e.querySelector('.ai365-ag-hrow').title]));
  assert.deepEqual(hooks, [
    ['session_start', 'allow', '훅 · 세션 시작python hooks/start.pyexit 0120ms', '전역'],
    ['user_prompt', 'allow', '훅 · 요청 받음node check-prompt.jsexit 040ms', '폴더'],
    ['stop', 'allow', '훅 · 턴 끝python hooks/stop.pyexit 0시간 초과1분 0초', '전역'],
  ]);
  await page.click('.ai365-ag-hook[data-hook-event="session_start"] .ai365-ag-hrow');
  await page.waitForSelector('.ai365-ag-hook[data-hook-event="session_start"].open');
  assert.equal(await page.textContent('.ai365-ag-hook[data-hook-event="session_start"] .ai365-ag-out'), '$ python hooks/start.py\n환경 확인 완료');
  // 서브에이전트 안의 훅 · 압축은 그 카드 안에(적대 검토 L6) / hooks and compactions inside a subagent live in its card (review L6)
  assert.deepEqual(await page.evaluate(() => [document.querySelectorAll('.ai365-ag-tx > .ai365-ag-hook[data-hook-event="pre_tool"]').length,
    [...document.querySelectorAll('.ai365-ag-tx > .ai365-ag-compact')].map(e => e.dataset.scope)]), [0, ['turn', 'history']]);
  await page.click('[data-call="tc2"] > .ai365-ag-trow');
  await page.click('[data-call="tc2"] .ai365-ag-hook[data-hook-event="pre_tool"][data-decision="block"] .ai365-ag-hrow');
  await page.waitForSelector('[data-call="tc2"] .ai365-ag-hook.open');
  assert.deepEqual(await page.evaluate(() => { const h = document.querySelector('[data-call="tc2"] .ai365-ag-hook'); return [h.querySelector('.ex.bad').textContent, h.querySelector('.ex.block').textContent, h.querySelector('.ai365-ag-note').textContent, h.dataset.task]; }),
    ['exit 2', '차단함', '이유 · 위험한 명령', 'sa2']);
  const subChip = '[data-call="tc2"] .ai365-ag-sub > .ai365-ag-compact';
  assert.deepEqual(await page.$eval(subChip, e => [e.dataset.scope, e.dataset.task, e.querySelector('.ai365-ag-cphd').textContent]), ['turn', 'sa2', '컨텍스트 압축 · 9,000 → 1,200 자이번 작업']);
  await page.click(subChip + ' .ai365-ag-cphd');
  await page.waitForSelector(subChip + ' .ai365-ag-cbody');
  assert.equal(await page.textContent(subChip + ' .ai365-ag-cbody'), '서브에이전트 앞부분 요약');

  const chips = await page.$$eval('.ai365-ag-tx > .ai365-ag-compact', els => els.map(e => [e.dataset.scope, e.querySelector('.ai365-ag-cphd').textContent]));
  assert.deepEqual(chips, [['turn', '컨텍스트 압축 · 12.3만 → 2.1만 자이번 작업'], ['history', '컨텍스트 압축 · 4.8만 → 3,200 자대화 기록']]);
  await page.click('.ai365-ag-tx > .ai365-ag-compact[data-scope="history"] .ai365-ag-cphd');
  await page.waitForSelector('.ai365-ag-tx > .ai365-ag-compact[data-scope="history"] .ai365-ag-cbody');
  assert.equal(await page.textContent('.ai365-ag-tx > .ai365-ag-compact[data-scope="history"] .ai365-ag-cbody'), '이전 대화 요약: 구조 조사와 리뷰를 마쳤다.');
  await page.waitForSelector('.ai365-ag-msg.user[data-seq="1"] [data-ag-restore="cp_1"]');   // 살아 있는 체크포인트를 읽은 뒤 / once the live checkpoints are read
  const rest = await page.evaluate(() => ({
    notify: document.querySelector('.ai365-ag-notify').className + '|' + document.querySelector('.ai365-ag-notify').textContent,
    cmd: document.querySelector('.ai365-ag-msg.agent.cmd').textContent, cmdUser: document.querySelector('.ai365-ag-msg.user.cmd').textContent,
    users: [...document.querySelectorAll('.ai365-ag-msg.user')].map(e => e.textContent), cp: document.querySelector('.ai365-ag-msg.user[data-seq="1"]').classList.contains('has-cp'),
    oldCp: [document.querySelector('.ai365-ag-msg.user.cmd').classList.contains('has-cp'), !!document.querySelector('[data-ag-restore="cp_old"]')],
    cpLines: document.querySelectorAll('.ai365-ag-mark.checkpoint').length,
  }));
  assert.deepEqual(rest, { notify: 'ai365-ag-notify|완료 알림을 보냈습니다 · outlook · me@example.com', cmd: '컨텍스트를 압축했습니다(48,000자 → 3,200자).', cmdUser: '/compact',
    users: ['코드 구조를 조사하고 리뷰해 줘', '/compact'], cp: true, oldCp: [false, false], cpLines: 0 });
  await shot(page, 'ag2_5_hooks.png');
});

test('the restore button shows only for live checkpoints, asks first, POSTs the restore; a cleaned-up one answers 404 and loses its button; hidden while running', async (t) => {
  const { page, db } = await app(t);
  await enter(page, 'ag_p1');
  await page.waitForSelector('.ai365-ag-changes .ai365-ag-chf');
  const bubble = '.ai365-ag-msg.user[data-seq="1"]';
  await page.waitForSelector(bubble + ' [data-ag-restore="cp_1"]');
  // 정리된 cp_old 에는 ⟲ 가 없다(적대 검토 M2) / the cleaned-up cp_old gets no button (review M2)
  assert.deepEqual(await page.evaluate(() => [!!document.querySelector('[data-ag-restore="cp_old"]'), document.querySelectorAll('.ai365-ag-rst').length]), [false, 1]);
  const cpGets = () => callsTo(db, 'GET', '/ag_p1/checkpoints').length;
  assert.equal(cpGets(), 1);
  const changesGets = () => callsTo(db, 'GET', '/ag_p1/changes').length;
  const g0 = changesGets();
  assert.equal(await page.$eval(bubble + ' .ai365-ag-rst', b => getComputedStyle(b).opacity), '0');
  await page.hover(bubble);
  await page.waitForFunction(sel => getComputedStyle(document.querySelector(sel + ' .ai365-ag-rst')).opacity === '1', bubble);
  assert.equal(await page.$eval(bubble + ' .ai365-ag-rst', b => b.getAttribute('aria-label')), '이 시점으로 되돌리기');
  await page.click(bubble + ' [data-ag-restore="cp_1"]');
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="restore"]');
  assert.deepEqual(await page.evaluate(() => { const ov = document.querySelector('.ai365-ag-ov'); return [ov.querySelector('h3').textContent, ov.querySelector('.ai365-ag-dname').textContent, ov.querySelector('[data-ag-dlg="ok"]').textContent, document.activeElement.dataset.agDlg]; }),
    ['이 시점으로 되돌릴까요?', '턴 시작 · 코드 구조를 조사하고 리뷰해 줘abc1234 · 파일 12개', '되돌리기', 'cancel']);
  await shot(page, 'ag2_6_restore.png');
  await page.click('[data-ag-ov="restore"] [data-ag-dlg="ok"]');
  await page.waitForSelector('.ai365-ag-mark.checkpoint');
  assert.deepEqual(callsTo(db, 'POST', '/ag_p1/checkpoints/cp_1/restore').map(c => c.body), [{ acting_user_id: '' }]);
  assert.equal(await page.textContent('.ai365-ag-mark.checkpoint'), '체크포인트로 되돌렸습니다 · 턴 시작 · 코드 구조를 조사하고 리뷰해 줘');
  await toastIs(page, '체크포인트로 되돌렸습니다');
  await waitFor(() => changesGets() >= g0 + 1 && cpGets() >= 2);   // 복원 뒤 Changes · 체크포인트 목록을 다시 읽는다 / Changes and the checkpoint list are re-read
  assert.equal(await page.locator('.ai365-ag-ov').count(), 0);
  assert.equal(db.events.ag_p1.filter(e => e.kind === 'checkpoint' && e.payload.label === '되돌리기 전 자동 저장').length, 1);   // 서버가 먼저 쓴 자동 저장(seq 없음) / the server's safety save (no seq)
  assert.deepEqual(await page.$$eval('.ai365-ag-rst', bs => bs.map(b => b.dataset.agRestore)), ['cp_1']);   // seq 없는 체크포인트는 말풍선이 없다 / a checkpoint without seq has no bubble

  // 그새 서버가 cp_1 을 정리했다 → 404 → ⟲ 를 걷고 안내(적대 검토 M2) / the server trimmed cp_1 meanwhile → 404 → the button goes, with a note (review M2)
  db.cps.ag_p1 = db.cps.ag_p1.filter(c => c.id !== 'cp_1');
  await page.hover(bubble);
  await page.click(bubble + ' [data-ag-restore="cp_1"]');
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="restore"]');
  await page.click('[data-ag-ov="restore"] [data-ag-dlg="ok"]');
  await toastIs(page, '이미 정리된 체크포인트입니다');
  assert.deepEqual(await page.evaluate(sel => [document.querySelectorAll('.ai365-ag-ov').length, !!document.querySelector(sel + ' .ai365-ag-rst'), document.querySelector(sel).classList.contains('has-cp')], bubble), [0, false, false]);
  assert.equal(callsTo(db, 'POST', '/ag_p1/checkpoints/cp_1/restore').length, 2);

  // 실행 중: 새 턴의 말풍선에도 ⟲ 가 생기지만 숨는다 / while running the new turn's bubble gets one too, but hidden
  await page.fill('#ai365AgInput', '오래 걸리는 작업을 해 줘');
  await page.press('#ai365AgInput', 'Enter');
  await page.waitForSelector('[data-ag="stop"]:not([hidden])');
  const newSeq = db.events.ag_p1.find(e => e.kind === 'user' && e.payload.text === '오래 걸리는 작업을 해 줘').seq;
  await page.waitForSelector('.ai365-ag-msg.user[data-seq="' + newSeq + '"] [data-ag-restore="cp_t' + newSeq + '"]', { state: 'attached' });
  assert.deepEqual(await page.$$eval('.ai365-ag-rst', bs => bs.map(b => [b.dataset.agRestore, getComputedStyle(b).display])), [['cp_t' + newSeq, 'none']]);
  await page.click('[data-ag="stop"]');
  await page.waitForFunction(() => !document.querySelector('.ai365-ag').classList.contains('busy'));
  assert.deepEqual(await page.$$eval('.ai365-ag-rst', bs => bs.map(b => getComputedStyle(b).display)), ['flex']);
});

test('Connectors keep unavailable ids, Changes open diffs and commit with a suggestion, Outputs preview and download (a refused path toasts); non-repo sessions say so', async (t) => {
  const { page, db } = await app(t);
  await enter(page, 'ag_p1');
  await page.waitForSelector('.ai365-ag-outputs .ai365-ag-ofile');
  await page.waitForSelector('.ai365-ag-conns [data-ag-conn]');
  const env = await page.evaluate(() => ({
    titles: [...document.querySelectorAll('.ai365-ag-env .ai365-ag-sech > span:first-child')].map(e => e.textContent),
    icons: [...document.querySelectorAll('#viewWork .ai365-ag-hr [data-ag-view]')].map(b => b.dataset.agView),
    conns: [...document.querySelectorAll('label.ai365-ag-conn')].map(l => [l.querySelector('input').dataset.agConn, l.querySelector('input').checked, l.querySelector('.nm').textContent, l.querySelector('.ai365-ag-kd').textContent, l.querySelector('.sv').textContent]),
    missing: [...document.querySelectorAll('.ai365-ag-conn.gone')].map(r => [r.dataset.agConnMissing, r.querySelector('.nm').textContent, r.querySelector('.ai365-ag-kd').textContent, r.querySelector('input').checked, r.querySelector('input').disabled]),
    cnt: document.querySelector('.ai365-ag-conns .cnt').textContent, chCnt: document.querySelector('.ai365-ag-changes .cnt').textContent, outCnt: document.querySelector('.ai365-ag-outputs .cnt').textContent,
    sum: document.querySelector('.ai365-ag-chs').textContent,
    changes: [...document.querySelectorAll('.ai365-ag-chf')].map(b => [b.dataset.agChange, b.querySelector('.ai365-ag-cs').textContent, b.querySelector('.ai365-ag-cs').className, (b.querySelector('.ds') || b.querySelector('.bn')).textContent]),
    btns: [...document.querySelectorAll('.ai365-ag-changes .ai365-ag-acts2 [data-ag]')].map(b => [b.dataset.ag, b.textContent, b.disabled]),
    outs: [...document.querySelectorAll('.ai365-ag-orow')].map(r => [r.querySelector('.nm').textContent, r.querySelector('.ai365-ag-kb').textContent, r.querySelector('.sz').textContent, r.querySelector('.ai365-ag-ofile').disabled, !!r.querySelector('[data-ag-dl]')]),
    dl: (() => { const a = document.querySelector('.ai365-ag-orow [data-ag-dl]'); return [a.getAttribute('href'), a.getAttribute('target'), a.getAttribute('rel')]; })(),
    sections: window.AI365_agentic.state().sections,
  }));
  assert.deepEqual(env.titles, ['Environment', 'Context', 'Connectors', 'Files', 'Changes', 'Outputs', 'Terminal', 'Background tasks']);
  assert.deepEqual(env.icons, ['transcript', 'terminal', 'outputs', 'files', 'panel']);
  assert.deepEqual(env.conns, [['mcp_a', true, '사내 위키 검색', '읽기 전용', '위키 MCP · search'], ['mcp_b', false, '메일 보내기', '외부 실행', '메일 MCP · send']]);
  assert.deepEqual(env.missing, [['mcp_gone', 'mcp_gone', '사용할 수 없음', true, true]]);   // 적대 검토 L9 / review L9
  assert.deepEqual([env.cnt, env.chCnt, env.outCnt], ['1', '3', '3']);   // 배지 = 보이는 목록 ∩ 세션 / badge = visible list ∩ session
  assert.equal(env.sum, 'main· 파일 3개 · +12 \u22122');
  assert.deepEqual(env.changes, [['src/app.js', 'M', 'ai365-ag-cs m', '+10 \u22122'], ['docs/new.md', '?', 'ai365-ag-cs u', '+2 \u22120'], ['logo.png', 'M', 'ai365-ag-cs m', '이진']]);
  assert.deepEqual(env.btns, [['checkpoint', '체크포인트 만들기', false], ['commit', '커밋', false]]);
  assert.deepEqual(env.outs, [['report.md', '새로 만듦', '2 KB', false, true], ['README.md', '수정됨', '1.2 KB', false, true], ['tmp.txt', '지워짐', '10 B', true, false]]);
  assert.deepEqual(env.dl, ['/api/agentic/sessions/ag_p1/outputs/download?acting_user_id=&path=' + encodeURIComponent(PA + '\\docs\\report.md'), '_blank', 'noopener']);
  assert.deepEqual(env.sections, ['env', 'ctx', 'connectors', 'files', 'changes', 'outputs', 'term', 'tasks']);
  await shot(page, 'ag2_7_panels.png');

  // Connectors: 체크 → 고른 목록 + 목록에 없는 세션 id 를 PATCH / a checkbox PATCHes the checked list plus the session ids missing from the list
  await page.click('[data-ag-conn="mcp_b"]');
  await waitFor(() => callsTo(db, 'PATCH', '/sessions/ag_p1').length === 1);
  assert.deepEqual(callsTo(db, 'PATCH', '/sessions/ag_p1')[0].body, { acting_user_id: '', connectors: ['mcp_a', 'mcp_b', 'mcp_gone'] });
  await page.waitForFunction(() => document.querySelector('.ai365-ag-conns .cnt').textContent === '2' && !document.querySelector('[data-ag-conn="mcp_b"]').disabled);
  await page.click('[data-ag-conn="mcp_a"]');   // 끄기도 사용할 수 없음 id 를 지우지 않는다 / unchecking keeps the unavailable id too
  await waitFor(() => callsTo(db, 'PATCH', '/sessions/ag_p1').length === 2);
  assert.deepEqual(callsTo(db, 'PATCH', '/sessions/ag_p1')[1].body, { acting_user_id: '', connectors: ['mcp_b', 'mcp_gone'] });
  await page.waitForFunction(() => document.querySelector('.ai365-ag-conns .cnt').textContent === '1' && !!document.querySelector('[data-ag-conn-missing="mcp_gone"]'));

  // Changes: 파일 → 가운데 diff 뷰어 / a file opens its diff in the centre viewer
  await page.click('[data-ag-change="src/app.js"]');
  await page.waitForSelector('.ai365-ag-viewer:not([hidden]) .ai365-ag-diff');
  const view = await page.evaluate(() => ({
    kind: document.querySelector('.ai365-ag-viewer').dataset.kind, name: document.querySelector('.ai365-ag-vh b').textContent, p: document.querySelector('.ai365-ag-vh .p').textContent,
    st: document.querySelector('.ai365-ag-vh .ai365-ag-cs').textContent, lines: [...document.querySelectorAll('.ai365-ag-vb .ai365-ag-diff .l')].map(l => [l.className.replace('l', '').trim(), l.querySelector('span').textContent]),
    on: document.querySelector('.ai365-ag-chf.on').dataset.agChange,
  }));
  assert.deepEqual(view, { kind: 'diff', name: 'app.js', p: 'src/app.js', st: 'M', on: 'src/app.js',
    lines: [['h', '--- a/src/app.js'], ['h', '+++ b/src/app.js'], ['k', '@@ -1,2 +1,3 @@'], ['d', '-console.log(1);'], ['a', '+console.log(2);'], ['a', '+export default 2;']] });
  assert.deepEqual(callsTo(db, 'GET', '/ag_p1/changes/diff').map(c => c.q.path), ['src/app.js']);
  await page.click('[data-ag-change="logo.png"]');
  await page.waitForFunction(() => document.querySelector('.ai365-ag-vb .ai365-ag-vnote') && document.querySelector('.ai365-ag-vb .ai365-ag-vnote').textContent === '이진 파일이라 비교할 수 없습니다');
  await page.click('.ai365-ag-vh [data-ag="vclose"]');
  await page.waitForSelector('.ai365-ag-viewer[hidden]', { state: 'attached' });

  // 체크포인트 만들기 → POST → 마지막 체크포인트 줄 / create a checkpoint → POST → the last-checkpoint line
  await page.click('[data-ag="checkpoint"]');
  await toastIs(page, '체크포인트를 만들었습니다');
  assert.deepEqual(callsTo(db, 'POST', '/ag_p1/checkpoints').map(c => c.body), [{ acting_user_id: '' }]);
  await page.waitForFunction(() => [...document.querySelectorAll('.ai365-ag-changes .ai365-ag-mu')].some(e => /^마지막 체크포인트 · 수동 체크포인트/.test(e.textContent)));

  // 커밋: 첫 초점 = 메시지 칸(적대 검토 L8), 빈 메시지 = 안내, 빈 제안 = '제안을 받지 못했습니다', 제안 = 채움, 확인 = POST commit → 다시 읽기
  // Commit: the message field has the first focus (review L8); empty = a note; an empty suggestion = a note; a suggestion fills; OK POSTs and re-reads
  await page.click('[data-ag="commit"]');
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="commit"]');
  assert.deepEqual(await page.evaluate(() => [document.querySelector('[data-ag-ov="commit"] .ds').textContent, document.activeElement.dataset.agF]),
    ['작업 폴더의 변경 사항을 모두 스테이징해 커밋합니다. main · 파일 3개', 'message']);
  await page.click('[data-ag-ov="commit"] [data-ag-dlg="ok"]');
  await page.waitForSelector('[data-ag-ov="commit"] .ai365-ag-derr:not([hidden])');
  assert.equal(await page.textContent('[data-ag-ov="commit"] .ai365-ag-derr'), '커밋 메시지를 적어 주세요');
  db.suggest = '';
  await page.click('[data-ag-ov="commit"] [data-ag="suggest"]');
  await page.waitForFunction(() => document.querySelector('[data-ag-ov="commit"] .ai365-ag-derr').textContent === '제안을 받지 못했습니다' && !document.querySelector('[data-ag="suggest"]').disabled);
  assert.equal(await page.inputValue('[data-ag-f="message"]'), '');
  db.suggest = 'README 정리 / Tidy the README';
  await page.click('[data-ag-ov="commit"] [data-ag="suggest"]');
  await page.waitForFunction(() => document.querySelector('[data-ag-f="message"]').value === 'README 정리 / Tidy the README');
  assert.equal(callsTo(db, 'GET', '/ag_p1/commit/suggest').length, 2);
  await page.click('[data-ag-ov="commit"] [data-ag-dlg="ok"]');
  await toastIs(page, '커밋했습니다 · 1a2b3c4 · 파일 3개');
  assert.deepEqual(callsTo(db, 'POST', '/ag_p1/commit').map(c => c.body), [{ acting_user_id: '', message: 'README 정리 / Tidy the README' }]);
  await page.waitForFunction(() => [...document.querySelectorAll('.ai365-ag-changes .ai365-ag-none')].some(e => e.textContent === '변경 사항이 없습니다') && document.querySelector('[data-ag="commit"]').disabled);
  assert.equal(await page.locator('.ai365-ag-ov').count(), 0);

  // Outputs: 파일 → 파일 뷰어, 내려받기 = 받아 본 뒤 파일 저장, 거절(404) = 토스트(서버 변경 4)
  // Outputs: a file opens the viewer; download = fetch then save; a refused path (404) = a toast (server change 4)
  await page.click('[data-ag-output="' + PA.replace(/\\/g, '\\\\') + '\\\\README.md"]');
  await page.waitForSelector('.ai365-ag-viewer:not([hidden]) .ai365-ag-code');
  assert.deepEqual(await page.evaluate(() => [document.querySelector('.ai365-ag-viewer').dataset.kind, [...document.querySelectorAll('.ai365-ag-code .r span')].map(s => s.textContent)]),
    ['file', ['# 프로젝트 A', ' ', 'the quick brown fox']]);
  const [dl] = await Promise.all([page.waitForEvent('download'), page.click('.ai365-ag-orow [data-ag-dl]')]);
  assert.equal(dl.suggestedFilename(), 'report.md');
  assert.deepEqual(callsTo(db, 'GET', '/ag_p1/outputs/download').map(c => c.q.path), [PA + '\\docs\\report.md']);
  db.dlFail = PA + '\\README.md';
  await page.click('.ai365-ag-orow:nth-child(2) [data-ag-dl]');
  await toastIs(page, '산출물이 아닙니다');
  await page.click('[data-ag-sec="outputs"]');   // 접고 / collapse it
  assert.equal(await page.evaluate(() => document.querySelector('.ai365-ag-outputs').classList.contains('shut')), true);
  assert.deepEqual(await page.evaluate(() => window.AI365_agentic.state().sections), ['env', 'ctx', 'connectors', 'files', 'changes', 'term', 'tasks']);
  await page.click('[data-ag-view="outputs"]');
  assert.equal(await page.evaluate(() => document.querySelector('.ai365-ag-outputs').classList.contains('shut')), false);

  // 저장소가 아닌 세션 / a session outside git
  await page.click('.ai365-ag-sess[data-id="ag_p3"]');
  await page.waitForFunction(() => [...document.querySelectorAll('.ai365-ag-changes .ai365-ag-none')].some(e => e.textContent === 'git 저장소가 아닙니다'));
  assert.deepEqual(await page.evaluate(() => [document.querySelectorAll('.ai365-ag-changes [data-ag]').length, [...document.querySelectorAll('.ai365-ag-outputs .ai365-ag-none')].map(e => e.textContent)]),
    [0, ['이 세션이 만든 파일이 없습니다']]);
});

test('status changes keep open task cards, panel lists and their scroll in place; only the state bits toggle', async (t) => {
  const many = Array.from({ length: 30 }, (_, i) => ({ path: PA + '\\gen\\f' + i + '.md', rel: 'gen/f' + i + '.md', kind: 'created', bytes: 100 + i, ts: '2026-10-19T14:30:00', exists: true }));
  const { page, db } = await app(t, null, d => { d.outputs.ag_p1 = d.outputs.ag_p1.concat(many); });
  await enter(page, 'ag_p1');
  await page.waitForFunction(() => document.querySelectorAll('.ai365-ag-orow').length === 33);
  await page.click('[data-call="tc1"] > .ai365-ag-trow');
  await page.waitForSelector('[data-call="tc1"].open .ai365-ag-sub');
  await page.evaluate(() => {
    window.__card = document.querySelector('[data-call="tc1"]');
    window.__chl = document.querySelector('.ai365-ag-chl');
    window.__btn = document.querySelector('[data-ag="checkpoint"]');
    document.querySelector('.ai365-ag-olist').scrollTop = 300;
  });
  const outs0 = callsTo(db, 'GET', '/ag_p1/outputs').length;
  // 실행 중 → 버튼만 비활성(같은 노드), 카드 · 목록은 그대로 / running → only the buttons disable (same nodes); the card and lists stay
  db.sess('ag_p1').status = 'running';
  db.push('ag_p1', 'status', { state: 'running', note: '작업 중', step: 1 });
  await page.waitForFunction(() => document.querySelector('.ai365-ag').classList.contains('busy'));
  assert.deepEqual(await page.evaluate(() => [window.__card.isConnected, window.__chl.isConnected, window.__btn.isConnected, window.__btn.disabled, window.__btn.title,
    document.querySelector('.ai365-ag-olist').scrollTop]), [true, true, true, true, '실행 중에는 쓸 수 없습니다', 300]);
  // 턴 끝 → 목록을 다시 읽어 다시 그려도 스크롤은 그대로, 펼친 카드도 그대로 / the turn ends → the lists are re-read and repainted, yet scroll and the open card stay
  db.sess('ag_p1').status = 'idle';
  db.push('ag_p1', 'status', { state: 'idle' });
  await waitFor(() => callsTo(db, 'GET', '/ag_p1/outputs').length > outs0, 9000);
  await page.waitForFunction(() => !document.querySelector('.ai365-ag').classList.contains('busy') && !document.querySelector('[data-ag="checkpoint"]').disabled);
  await page.waitForTimeout(150);
  assert.deepEqual(await page.evaluate(() => [window.__card.isConnected, window.__card.classList.contains('open'), document.querySelector('.ai365-ag-olist').scrollTop,
    document.querySelector('[data-ag="checkpoint"]').title]), [true, true, 300, '']);
});

test('markup in server strings stays text everywhere (labels, details, outputs, hooks, compact, connectors, dialogs, slash popup); nothing runs', async (t) => {
  const { page, db } = await app(t, 'ag_x', d => {
    d.conns.push({ id: 'mcp_x', name: X(40) + '위키', description: X(41), kind: 'read', server_name: X(42), tool: X(43), inputs: [] });
    d.sess('ag_x').connectors = ['mcp_x', X(44)];
    d.commands.push({ name: 'xss', description: X(45), source: 'global', args: X(46) });
  });
  let imgHits = 0;   // 진짜 img 가 생기면 src=x 를 요청한다 / a real img would request src=x
  page.on('request', r => { try { if (new URL(r.url()).pathname === '/x') imgHits += 1; } catch (e) { /* 무시 / ignore */ } });
  await enter(page, 'ag_x');
  await page.waitForSelector('.ai365-ag-tool[data-call="x3"]');
  await page.waitForSelector('.ai365-ag-conns [data-ag-conn]');
  await page.waitForSelector('[data-ag-restore="cp_x"]', { state: 'attached' });
  for (const sel of ['[data-call="x1"] > .ai365-ag-trow', '[data-call="x2"] > .ai365-ag-trow', '[data-call="x3"] > .ai365-ag-trow', '.ai365-ag-hook .ai365-ag-hrow', '.ai365-ag-compact .ai365-ag-cphd', '.ai365-ag-term .ai365-ag-tih']) {
    await page.click(sel);
  }
  await page.waitForSelector('.ai365-ag-compact .ai365-ag-cbody');
  await page.click('[data-ag-change="' + X(26).replace(/"/g, '\\"') + '.js"]');
  await page.waitForSelector('.ai365-ag-viewer:not([hidden])');
  await page.click('.ai365-ag-vh [data-ag="vclose"]');
  const bad = () => page.evaluate(() => ({ el: document.querySelectorAll('.ai365-ag img, .ai365-ag-side img, .ai365-ag-ov img, .ai365-ag [onerror], .ai365-ag [onload], .ai365-ag-ov [onerror], .ai365-ag script').length, xss: window.__xss === undefined ? null : window.__xss }));
  assert.deepEqual(await bad(), { el: 0, xss: null });
  const shown = await page.evaluate(() => ({
    user: document.querySelector('.ai365-ag-msg.user').textContent, x1: document.querySelector('[data-call="x1"] .lb').textContent, out: document.querySelector('[data-call="x1"] .ai365-ag-out').textContent,
    x2: document.querySelector('[data-call="x2"] .ai365-ag-out').textContent, hook: document.querySelector('.ai365-ag-hook .ai365-ag-out').textContent,
    compact: document.querySelector('.ai365-ag-compact .ai365-ag-cbody').textContent, task: document.querySelector('[data-call="x3"] .lb').textContent,
    pr: document.querySelector('[data-call="x3"] .ai365-ag-pr').className, conn: document.querySelector('[data-ag-conn="mcp_x"]').closest('label').querySelector('.nm').textContent,
    gone: document.querySelector('.ai365-ag-conn.gone .nm').textContent,
    title: document.querySelector('.ai365-ag-sess[data-id="ag_x"] .tt').textContent, notify: document.querySelector('.ai365-ag-notify').textContent,
  }));
  assert.deepEqual(shown, { user: X(1) + '사용자 글', x1: X(5) + '명령', out: '$ echo "<script>window.__xss=4</script>"\n' + X(6) + '출력', x2: '<script>window.__xss=9</script>세부',
    hook: '$ ' + X(11) + '\n' + X(12) + '훅 출력', compact: X(14) + '요약', task: '서브에이전트: ' + X(18), pr: 'ai365-ag-pr reviewer', conn: X(40) + '위키', gone: X(44),
    title: '<b>마크업</b> 세션' + X(30), notify: '완료 알림을 보내지 못했습니다: ' + X(22) });
  // 대화 상자 · 슬래시 팝업 / dialogs and the slash popup
  await page.hover('.ai365-ag-msg.user');
  await page.click('[data-ag-restore="cp_x"]');
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="restore"]');
  assert.equal(await page.textContent('.ai365-ag-ov .ai365-ag-dname'), X(23) + '라벨x1x2x3x · 파일 1개');
  assert.deepEqual(await bad(), { el: 0, xss: null });
  await page.keyboard.press('Escape');
  await page.click('[data-ag="commit"]');
  await page.waitForSelector('.ai365-ag-ov[data-ag-ov="commit"]');
  assert.equal(await page.textContent('[data-ag-ov="commit"] .ds'), '작업 폴더의 변경 사항을 모두 스테이징해 커밋합니다. ' + X(24) + ' · 파일 1개');
  assert.deepEqual(await bad(), { el: 0, xss: null });
  await page.keyboard.press('Escape');
  await page.click('#ai365AgInput');
  await page.keyboard.type('/xs');
  await page.waitForSelector('.ai365-ag-slash:not([hidden]) [data-ag-cmd="xss"]');
  assert.equal(await page.textContent('[data-ag-cmd="xss"]'), '/xss' + X(46) + X(45) + '전역');
  assert.deepEqual(await bad(), { el: 0, xss: null });
  assert.equal(imgHits, 0);   // img 요청이 한 번도 없었다 / no img request ever went out
  assert.ok(db.calls.length > 0);
});

test('the notify menu item PATCHes, the unseen dot and seen reports follow the events, English labels and the state summary', async (t) => {
  const { page, db } = await app(t);
  await enter(page, 'ag_p1');
  await page.waitForSelector('.ai365-ag-conns [data-ag-conn]');
  const dots = () => page.evaluate(() => ['ag_p1', 'ag_p2', 'ag_p3'].map(id => [id, [...document.querySelectorAll('.ai365-ag-sess[data-id="' + id + '"] .dot')].map(d => d.className.replace('hide-on-collapse', '').trim())]));
  assert.deepEqual(await dots(), [['ag_p1', ['dot']], ['ag_p2', ['dot']], ['ag_p3', ['dot unseen', 'dot unseen']]]);   // 점이 있으면 접힌 아이콘에도 하나 / a dot also goes on the collapsed avatar
  assert.equal(await page.$eval('.ai365-ag-sess[data-id="ag_p3"] > .dot', d => d.title), '새 활동');
  assert.equal(callsTo(db, 'POST', '/ag_p1/seen').length, 0);   // 이미 다 본 세션 / already fully seen
  // 열린 세션에 이벤트가 오면 1초 디바운스로 seen / a live event in the open session reports seen after a 1 s debounce
  const last = db.push('ag_p1', 'context', { pct: 2 });
  await waitFor(() => callsTo(db, 'POST', '/ag_p1/seen').length === 1, 9000);
  assert.deepEqual(callsTo(db, 'POST', '/ag_p1/seen')[0].body, { acting_user_id: '', seq: last });
  // 미확인 세션을 열면 seen, 다른 데로 가도 점이 없다 / opening the unseen session reports seen; leaving it keeps the dot away
  await page.click('.ai365-ag-sess[data-id="ag_p3"]');
  await waitFor(() => callsTo(db, 'POST', '/ag_p3/seen').length === 1, 9000);
  assert.deepEqual(callsTo(db, 'POST', '/ag_p3/seen')[0].body, { acting_user_id: '', seq: 4 });
  await page.click('.ai365-ag-sess[data-id="ag_p1"]');
  await page.waitForSelector('.ai365-ag-sess[data-id="ag_p1"].on');
  await page.waitForSelector('.ai365-ag-conns [data-ag-conn]');
  assert.deepEqual((await dots())[2], ['ag_p3', ['dot']]);

  // 세션 메뉴 › 완료 알림 켜기 → PATCH notify → 라벨이 끄기로 / session menu › turn on notices → PATCH notify → the label flips
  await page.click('[data-ag="title"]');
  assert.deepEqual(await texts(page, '.ai365-ag-menu .ai365-ag-mi'), ['이름 바꾸기', '폴더 보기', '완료 알림 켜기', '삭제']);
  await page.click('[data-ag-menu="notify"]');
  await toastIs(page, '완료 알림을 켰습니다');
  assert.deepEqual(callsTo(db, 'PATCH', '/sessions/ag_p1').map(c => c.body), [{ acting_user_id: '', notify: true }]);
  await page.click('[data-ag="title"]');
  assert.equal(await page.textContent('[data-ag-menu="notify"]'), '완료 알림 끄기');
  await page.keyboard.press('Escape');

  // state(): 접은 섹션은 빠진다 / state(): a collapsed section drops out
  await page.click('[data-ag-sec="files"]');
  const st = await page.evaluate(() => window.AI365_agentic.state());
  assert.deepEqual([st.sections, st.steer, st.pendingApprovals, st.session], [['env', 'ctx', 'connectors', 'changes', 'outputs', 'term', 'tasks'], 0, 0, 'ag_p1']);

  // EN
  await page.click('#ai365-lang-toggle');
  await page.waitForFunction(() => document.querySelector('[data-ag="new"]').textContent === 'New session' && document.querySelector('[data-ag="commit"]').textContent === 'Commit');
  const en = await page.evaluate(() => ({
    titles: [...document.querySelectorAll('.ai365-ag-env .ai365-ag-sech > span:first-child')].map(e => e.textContent),
    perm: [...document.querySelectorAll('[data-ag-perm] option')].map(o => o.textContent),
    tips: [...document.querySelectorAll('.ai365-ag-hr [data-ag-view]')].map(b => b.dataset.tip),
    kinds: [...document.querySelectorAll('.ai365-ag-kd')].map(e => e.textContent), outs: [...document.querySelectorAll('.ai365-ag-kb')].map(e => e.textContent),
    btns: [...document.querySelectorAll('.ai365-ag-changes .ai365-ag-acts2 [data-ag]')].map(b => b.textContent),
    hook: document.querySelector('.ai365-ag-hook .ev').textContent, chip: document.querySelector('.ai365-ag-tx > .ai365-ag-compact .ai365-ag-cphd').textContent,
    notify: document.querySelector('.ai365-ag-notify span').textContent, tn: document.querySelector('[data-call="tc1"] .tn').textContent,
    restore: document.querySelector('[data-ag-restore]').getAttribute('aria-label'), unseen: document.querySelector('.ai365-ag-sess[data-id="ag_p2"] .dot').title,
    slash: document.getElementById('ai365AgSlash').getAttribute('aria-label'),
  }));
  assert.deepEqual(en, {
    titles: ['Environment', 'Context', 'Connectors', 'Files', 'Changes', 'Outputs', 'Terminal', 'Background tasks'], perm: ['Auto', 'Ask', 'Plan'],
    tips: ['Transcript', 'Terminal', 'Outputs', 'Files', 'Hide panel'], kinds: ['Read only', 'Action', 'Unavailable'], outs: ['Created', 'Modified', 'Deleted'],
    btns: ['Create checkpoint', 'Commit'], hook: 'Hook · Session start', chip: 'Context compacted · 123k → 21k charsThis task',
    notify: 'Completion notice sent · outlook · me@example.com', tn: '4 tools', restore: 'Restore to this point', unseen: '', slash: 'Slash commands',
  });
  await page.click('[data-ag="title"]');
  assert.equal(await page.textContent('[data-ag-menu="notify"]'), 'Turn off completion notices');
  await page.keyboard.press('Escape');
  await page.click('#ai365AgInput');
  await page.keyboard.type('/hel');
  await page.waitForSelector('.ai365-ag-slash:not([hidden]) [data-ag-cmd="help"]');
  assert.deepEqual(await page.$$eval('.ai365-ag-slash [data-ag-cmd] .ai365-ag-sb', els => els.map(e => e.textContent)), ['Built-in']);
  await page.keyboard.press('Escape');
  await shot(page, 'ag2_8_en.png');
  await page.click('#ai365-lang-toggle');
  await page.waitForFunction(() => document.querySelector('[data-ag="commit"]').textContent === '커밋');
  assert.equal(await page.textContent('.ai365-ag-hook .ev'), '훅 · 세션 시작');
});
