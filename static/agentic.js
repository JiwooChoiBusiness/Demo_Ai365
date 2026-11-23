/* =====================================================================
   Agentic 모드 셸(2026-10-19, 1차 프런트) - Claude Code 데스크톱 화면을 우리 밝은 테마로 옮긴 작업 환경.
   adapter.js 의 ai365ChatAgentic 블록이 모드를 바꿀 때 보내는 'ai365:agentic' 신호({on})로 마운트 · 해제한다.
   on: body.ai365-ag-on + 사이드바 첫 자식 .ai365-ag-side(목업 사이드바 자식은 CSS 로만 숨긴다, 노드는 옮기지 않는다)
       + #viewWork .ai365-ca-blank 안 3단 레이아웃(.ai365-ag: 트랜스크립트 · 입력줄 | 환경 패널) + 머리줄(← → · 세션 제목 ˅ · 오른쪽 아이콘).
   off: 끼운 것을 모두 걷고 EventSource · 타이머를 닫는다. 트랜스크립트의 원본은 서버 이벤트(seq)이고, 처음엔 /events 로 그리고
   그 뒤엔 /stream?after=last_seq(SSE)로 이어 받는다(끊기면 3초 뒤 재접속). API 모양은 내부 계약 F, 셀렉터는 계약 G 그대로다.
   Agentic mode shell (2026-10-19, phase-1 front end): the Claude Code desktop screen moved onto our light theme.
   Mounted and unmounted on the 'ai365:agentic' signal ({on}) that the adapter's ai365ChatAgentic block sends on a mode change.
   on: body.ai365-ag-on, a .ai365-ag-side first child in the sidebar (the mockup's sidebar children are hidden by CSS only, never
       moved), a three-pane layout inside #viewWork .ai365-ca-blank (.ai365-ag: transcript and composer | environment panel) and the
       sub-header pieces (back/forward, session title menu, icons on the right).
   off: everything inserted is removed and the EventSource and timers are closed. The transcript's source is the server's event list
   (seq): drawn from /events first, then followed over /stream?after=last_seq (SSE, reconnect after 3 s). API shapes follow the
   internal contract F and the selectors follow contract G as written.

   2차 · 3차(2026-10-19, 내부 계약 2 의 H 절): 입력줄 슬래시 팝업 · 실행 중 스티어링(mode steer) · 플랜 모드와 [계획대로 실행] ·
   서브에이전트 task 카드 중첩(자식 = 같은 task_id 의 이벤트) · 훅 줄 · 압축 칩 · 체크포인트 ⟲ 되돌리기 · 완료 알림 줄 ·
   환경 패널 Connectors · Changes(diff · 체크포인트 · 커밋) · Outputs · 서브에이전트 서랍 행 · 머리줄 산출물 아이콘 · 세션 메뉴 완료 알림 ·
   사이드바 미확인 점과 seen 보고. 2차 UI 는 서버가 2차 모양(세션의 notify · seen_seq · connectors, 설정의 notify_default 등)을 줄 때만
   보인다(v2()): 1차 서버(와 1차 테스트 스텁)에는 1차 화면을 그대로 보여 준다.
   Phases 2 and 3 (2026-10-19, section H of the internal contract 2): the composer's slash popup, steering while running (mode
   steer), plan mode with [Run the plan], nested subagent task cards (children = events with the same task_id), hook lines, the
   compact chip, checkpoint restore, the completion-notice line, the environment panel's Connectors, Changes (diff, checkpoint,
   commit) and Outputs, subagent rows in the drawer, the outputs icon, the notify menu item, and the sidebar's unseen dot with seen
   reports. The phase-2 UI shows only when the server sends phase-2 shapes (notify, seen_seq, connectors on a session, notify_default
   and the like in the settings; v2()): a phase-1 server (and the phase-1 test stub) keeps the phase-1 screen as it was.

   폴더 고르기(2026-10-19): 새 세션 대화 상자의 [찾아보기…](POST /pick-folder = 서버 PC 의 폴더 선택 창, 503 · 네트워크 실패면
   앱 안 탐색기 [data-ag-ov="browse"] = GET /browse) · "서버 폴더에서 고르기" · 세션 메뉴 "추가 폴더…"(extra_folders PATCH).
   서버가 설정 응답에 folder_picker 를 알릴 때만 보인다(그 전 서버 · 테스트 스텁은 화면 그대로). 승인 카드의 [이 세션에서 항상 허용]은
   서버가 실어 준 payload.rule 의 범위를 붙인다(예: (python …)).
   Folder picking (2026-10-19): [Browse…] in the new-session dialog (POST /pick-folder = the server PC's folder window; 503 or a
   network failure opens the in-app explorer [data-ag-ov="browse"] over GET /browse), "Pick from server folders" and the session menu's
   "Extra folders…" (an extra_folders PATCH). They show only when the server's settings answer carries folder_picker (older servers and
   test stubs keep their screen). The approval card's [Always allow in this session] names the scope of payload.rule, e.g. (python …).

   내 컴퓨터 폴더(2026-10-20, docs/agentic-browser-folder-contract.md F 절): 브라우저의 File System Access API(showDirectoryPicker)로
   사용자 PC 의 폴더를 열어 세션(kind 'browser', folder = 폴더 이름)을 만들고, 서버 루프가 보내는 파일 도구 요청(SSE 'tool_request' ·
   GET …/tool-requests)을 이 화면이 그 폴더에서 대신 실행해 POST …/tool-results 로 답한다(list · read · write · walk · grep, 문서는
   POST /extract 로 본문). 핸들은 IndexedDB(ai365_agentic_fs / handles)에 세션별로 두고, 권한이 없으면 트랜스크립트 위 안내 줄
   (.ai365-ag-fsbar)의 [허용] · [폴더 열기] · [다시 시도]가 사용자 제스처 안에서 다시 묻는다. 서버 설정과 무관하게
   window.showDirectoryPicker 가 있을 때만 켠다. 명령 실행 · 훅 · git 은 없다(Changes · Terminal 숨김).
   Folders on my computer (2026-10-20, section F of docs/agentic-browser-folder-contract.md): the browser's File System Access API
   (showDirectoryPicker) opens a folder on the user's PC and creates a session (kind 'browser', folder = the folder name); the file
   tool requests the server loop sends (SSE 'tool_request', GET …/tool-requests) run here against that folder and are answered with
   POST …/tool-results (list, read, write, walk, grep; documents go through POST /extract). Handles live per session in IndexedDB
   (ai365_agentic_fs / handles); without permission the bar above the transcript (.ai365-ag-fsbar) asks again inside a user
   gesture ([Allow], [Open folder], [Retry]). On only when window.showDirectoryPicker exists, whatever the server settings say.
   No commands, hooks or git there (Changes and Terminal are hidden).
===================================================================== */
(function () {
  'use strict';
  if (typeof window === 'undefined' || typeof document === 'undefined') return;
  if (window.AI365_agentic) return;   // 두 번 실리면 처음 것만 / when loaded twice, the first copy wins

  const BASE = '/api/agentic';
  const LAST_KEY = 'ai365_ag_last';
  const RETRY_MS = 3000, RETRY_SLOW_MS = 15000, TASK_POLL_MS = 5000, LIST_POLL_MS = 10000, EVENT_PAGE = 500;
  const SEEN_MS = 1000, SEEN_MAX_MS = 5000, TASKS_KICK_MS = 250, SUB_ROWS = 20, LIST_CAP = 200;
  const BUSY = { running: true, waiting: true };
  const FALLBACK_MODELS = [
    { id: 'gemini-3.7-flash', label: 'Gemini 3.7 Flash' },
    { id: 'gemini-3.5-flash', label: 'Gemini 3.5 Flash' },
    { id: 'gemini-3.5-flash-lite', label: 'Gemini 3.5 Flash-Lite' },
  ];
  // 도구 이름 → 묶음(이벤트에 group 이 없을 때) / tool name → group, used when an event carries no group
  const GROUP_OF = { read_file: 'read', list_dir: 'read', glob: 'search', grep: 'search', write_file: 'write', edit_file: 'write',
    bash: 'run', task_output: 'run', web_search: 'web', fetch_page: 'web', task: 'agent', skill: 'read', mcp_tool: 'mcp' };
  const REASON = { deny_cmd: '차단 목록에 있는 명령입니다', outside: '허용 폴더 밖의 경로입니다', ask_mode: '묻기 모드라 승인이 필요합니다',
    auto_cmd: 'Auto 모드에서는 안전 목록 밖의 명령이라 승인이 필요합니다', budget: '스텝 또는 시간 예산을 다 썼습니다',   // auto_cmd: 2026-10-19 적대 검토 반영(안전 목록 밖 명령은 Auto 에서도 승인) / commands outside the safe list ask even in Auto
    mcp_action: 'Auto 모드에서도 바깥으로 보내는 MCP 도구는 승인이 필요합니다', hooks: '이 폴더의 훅(.ai365/hooks.json)을 이 세션에서 실행해도 될지 확인합니다' };   // 2차 계약 C / contract 2, section C
  const TOOL_STATE = { ok: '성공', fail: '실행 실패', run: '실행 중…', wait: '승인을 기다리는 중', stop: '중단됨' };
  const SESS_STATE = { running: '실행 중', waiting: '승인 대기', error: '오류' };
  const PERM_HINT = { auto: 'Auto: 읽기 · 검색 · 편집과 안전 목록의 명령은 바로 하고, 그 밖의 명령 · 삭제 · 폴더 밖 경로는 묻습니다', ask: '묻기: 편집과 명령을 모두 먼저 묻습니다',
    plan: '플랜: 읽기 · 조사만 하고 파일은 고치지 않습니다. 끝에 단계별 계획을 냅니다' };
  const PERM_LABEL = { ask: '묻기', plan: '플랜' };   // auto 는 두 언어 모두 'Auto' / 'Auto' in both languages
  const SECTIONS = [   // 환경 패널 섹션(제목은 두 언어 모두 영어, v2 = 2차 서버에서만) / environment panel sections (English titles in both languages, v2 = phase-2 servers only)
    { key: 'env', title: 'Environment', cls: 'ai365-ag-info' },
    { key: 'ctx', title: 'Context', cls: 'ai365-ag-ctxs' },
    { key: 'connectors', title: 'Connectors', cls: 'ai365-ag-conns', v2: true },
    { key: 'files', title: 'Files', cls: 'ai365-ag-files' },
    { key: 'changes', title: 'Changes', cls: 'ai365-ag-changes', v2: true },
    { key: 'outputs', title: 'Outputs', cls: 'ai365-ag-outputs', v2: true },
    { key: 'term', title: 'Terminal', cls: 'ai365-ag-term' },
    { key: 'tasks', title: 'Background tasks', cls: 'ai365-ag-tasks' },
  ];
  const HOOK_EVENT = { session_start: '세션 시작', user_prompt: '요청 받음', pre_tool: '도구 실행 전', post_tool: '도구 실행 뒤', stop: '턴 끝' };
  const TASK_ST = { running: 'run', done: 'ok', error: 'fail', stopped: 'stop' };   // 작업 행 상태 → 상태 점 / task-row status → state dot
  const CHANGE_CLS = { M: 'm', A: 'a', D: 'd', R: 'r', '?': 'u', '!': 'i' };   // git 상태 글자 → 클래스 / git status letter → class
  // 명령 출처 배지([한국어, 영어]; 전역 사전의 '스킬'은 복수형 Skills 라 짝으로 둔다. 훅 줄의 '훅'도 같은 이유로 Hook 짝을 쓴다(전역 '훅' = 관리 센터 탭 Hooks))
  // Command source badges ([KO, EN]; the global '스킬' maps to plural Skills, so pairs live here; the hook line's '훅' uses a Hook pair for the same reason, the global '훅' being the Admin Center tab 'Hooks')
  const SRC_LABEL = { builtin: ['내장', 'Built-in'], folder: ['폴더', 'Folder'], global: ['전역', 'Global'], skill: ['스킬', 'Skill'] };
  // 내 컴퓨터 폴더(계약 B2 · F): 상한은 서버 agentic_exec 와 같은 값 / folders on my computer (contract B2, F): caps match the server's agentic_exec
  const FS_DB = 'ai365_agentic_fs', FS_STORE = 'handles';
  const FS_MAX_BYTES = 10 * 1024 * 1024, FS_LIST_MAX = 500, FS_SCAN_MAX = 50000, FS_GREP_FILE = 5 * 1024 * 1024, FS_GREP_LINE = 300;
  const FS_GREP_DEFAULT = 200, FS_GREP_MAX = 1000, FS_GREP_MS = 30000, FS_VIEW_BYTES = 512 * 1024, FS_VIEW_CHARS = 100000, FS_PAR = 16;
  const FS_DOC = { pdf: true, docx: true, pptx: true, xlsx: true };   // 브라우저가 /extract 로 본문을 뽑는 문서 / documents the browser extracts through /extract

  /* ── 도우미 / helpers ── */
  const esc = (typeof ai365Esc === 'function') ? ai365Esc : function (s) {
    return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; });
  };
  function E(s) { return esc(s === null || s === undefined ? '' : s); }
  function T(ko) { return (typeof ai365T === 'function') ? ai365T(ko) : ko; }
  function isEn() { return typeof ai365CurrentLang === 'function' && ai365CurrentLang() === 'en'; }
  function acting() { return (typeof ai365ActingId === 'function') ? ai365ActingId() : ''; }
  function say(msg) { if (msg && typeof toast === 'function') toast(msg); }
  function noop() { /* 일부러 비움 / intentionally empty */ }
  // 이 클릭이 언어 토글에서 왔는지(전달 시점 경로 우선) / whether this click came from the language toggle (dispatch-time path first)
  function fromLangToggle(e) {
    const path = (e && typeof e.composedPath === 'function') ? e.composedPath() : [];
    for (let i = 0; i < path.length; i++) if (path[i] && path[i].id === 'ai365-lang-toggle') return true;
    const t = e && e.target;
    return !!(t && t.closest && t.closest('#ai365-lang-toggle'));
  }
  function cssq(s) { return (window.CSS && CSS.escape) ? CSS.escape(String(s)) : String(s).replace(/["\\]/g, '\\$&'); }

  function qs(params) {
    const parts = ['acting_user_id=' + encodeURIComponent(acting())];
    Object.keys(params || {}).forEach(function (k) { parts.push(k + '=' + encodeURIComponent(params[k] === null || params[k] === undefined ? '' : String(params[k]))); });
    return '?' + parts.join('&');
  }
  function sessUrl(id, tail) { return BASE + '/sessions/' + encodeURIComponent(id) + (tail || ''); }
  function withActing(extra) { return Object.assign({ acting_user_id: acting() }, extra || {}); }
  function detailOf(d) {
    if (!d) return '';
    if (typeof d.detail === 'string') return d.detail;
    if (Array.isArray(d.detail) && d.detail[0] && d.detail[0].msg) return String(d.detail[0].msg);   // FastAPI 검증 오류 / FastAPI validation errors
    return '';
  }
  function api(url, method, body) {
    return fetch(url, { method: method || 'GET', headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (d) {
        if (!res.ok) { const err = new Error(detailOf(d) || ('HTTP ' + res.status)); err.status = res.status; throw err; }
        return d;
      });
    });
  }

  // 서버 시각은 오프셋 없는 KST 벽시계 문자열이다(kst.js 가 있으면 그것을 쓴다) / server times are naive KST strings (kst.js when present)
  function parseTs(s) {
    if (!s) return null;
    if (typeof window.ai365KstParse === 'function') return window.ai365KstParse(s);
    const t = String(s), m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/.exec(t);
    if (m && !/(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(t)) return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0)) - 9 * 3600 * 1000);
    const d = new Date(t);
    return isNaN(d.getTime()) ? null : d;
  }
  function ago(s) {
    const d = parseTs(s);
    if (!d) return '';
    const en = isEn(), sec = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
    if (sec < 60) return en ? 'now' : '방금';
    const min = Math.floor(sec / 60);
    if (min < 60) return en ? min + 'm' : min + '분';
    const h = Math.floor(min / 60);
    if (h < 24) return en ? h + 'h' : h + '시간';
    const day = Math.floor(h / 24);
    if (day < 7) return en ? day + 'd' : day + '일';
    return String(s).slice(5, 10);   // MM-DD(KST 문자열 그대로) / MM-DD straight from the KST string
  }
  function hm(s) { const m = /[T ](\d{2}:\d{2})/.exec(String(s || '')); return m ? m[1] : ''; }
  function fmtDur(ms) {
    ms = Number(ms);
    if (!isFinite(ms) || ms < 0) return '';
    const en = isEn();
    if (ms < 1000) return Math.round(ms) + 'ms';
    const s = ms / 1000;
    if (s < 10) return (Math.round(s * 10) / 10) + (en ? 's' : '초');
    if (s < 60) return Math.round(s) + (en ? 's' : '초');
    const m = Math.floor(s / 60), r = Math.round(s % 60);
    return en ? m + 'm ' + r + 's' : m + '분 ' + r + '초';
  }
  function fmtTokens(n) { n = Number(n); if (!isFinite(n) || n <= 0) return ''; return n >= 1000 ? (Math.round(n / 100) / 10) + 'k' : String(Math.round(n)); }
  function fmtSize(n) {
    n = Number(n);
    if (!isFinite(n) || n < 0) return '';
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (Math.round(n / 102.4) / 10) + ' KB';
    return (Math.round(n / 104857.6) / 10) + ' MB';
  }
  function baseName(p) { const s = String(p || '').replace(/[\\/]+$/, ''); const i = Math.max(s.lastIndexOf('\\'), s.lastIndexOf('/')); return i >= 0 ? s.slice(i + 1) : s; }
  function joinPath(dir, name) {
    const d = String(dir || ''), sep = (d.indexOf('\\') >= 0 || /^[A-Za-z]:/.test(d)) ? '\\' : '/';
    return d.replace(/[\\/]+$/, '') + sep + name;
  }
  function folderKey(f) { return String(f || '').replace(/[\\/]+$/, '').toLowerCase(); }
  // 긴 경로는 구분자 뒤에서만 줄을 바꾼다 / long paths wrap only after a separator
  function pathHtml(p) { return E(p).replace(/([\\/])/g, '$1<wbr>'); }
  function initial(t) { const ch = Array.from(String(t || '').trim())[0]; return ch ? ch.toUpperCase() : '?'; }
  function titleOf(s) { return (s && (s.title || baseName(s.folder) || s.id)) || ''; }

  /* ── EN 사전(정확히 일치하는 고정 문구만) / EN dictionary (fixed strings, exact match) ──
     정방향(KO→EN)만 넣는다: 이 셸은 언어 토글 때 스스로 다시 그리므로 역방향이 필요 없고, 흔한 영어 낱말(Model · Branch 등)을
     역방향에 넣으면 다른 화면의 영어 라벨이 한국어로 뒤집힐 수 있다. 이미 있는 키는 건드리지 않는다.
     Forward entries (KO→EN) only: the shell re-renders itself on a language toggle, so no reverse entry is needed, and putting
     common English words (Model, Branch, ...) into the reverse map could flip English labels on other screens. Existing keys stay. */
  const DICT = {
    '새 세션': 'New session', '세션 검색': 'Search sessions', '세션이 없습니다': 'No sessions yet', '검색 결과가 없습니다': 'No matching sessions',
    '승인 대기': 'Waiting for approval', '이전 세션': 'Previous session', '다음 세션': 'Next session', '세션 메뉴': 'Session menu',
    '폴더 보기': 'Show folder', '트랜스크립트': 'Transcript', '터미널': 'Terminal', '패널 접기': 'Hide panel', '패널 펴기': 'Show panel',
    '작업 폴더를 골라 새 세션을 시작하세요': 'Pick a working folder to start a new session',
    '에이전트가 작업 폴더 안에서 파일을 읽고 고치고 명령을 실행합니다.': 'The agent reads and edits files and runs commands inside the working folder.',
    '아직 대화가 없습니다. 아래 입력창에 맡길 작업을 적어 보세요.': 'No messages yet. Describe a task in the box below.',
    '세션 목록을 불러오지 못했습니다': 'Could not load the sessions', '세션을 불러오지 못했습니다': 'Could not load the session',
    '에이전트에게 맡길 작업을 적어 주세요': 'Describe a task for the agent',
    '실행 중에도 보낼 수 있습니다. 지금 작업이 끝나면 이어서 처리합니다': 'You can send while it runs. It is handled after the current task',
    '권한 모드': 'Permission mode', '모델': 'Model', '대기 중': 'Queued',
    '대기열에 넣었습니다. 지금 작업이 끝나면 이어서 처리합니다.': 'Queued. It runs after the current task.',
    '실행 중…': 'Running…', '승인을 기다리는 중': 'Waiting for approval', '계속할지 기다리는 중': 'Waiting for you to continue',
    '실행 실패': 'Failed', '작업 중…': 'Working…', '실행을 중단했습니다': 'Run stopped', '오류로 멈췄습니다': 'Stopped by an error',
    '출력이 길어 가운데를 줄였습니다': 'The output was long, so the middle was trimmed', '내용이 길어 앞부분만 보여 줍니다': 'Long content, showing the beginning only',
    '백그라운드 작업': 'Background task', '출력 없음': 'No output',
    '거부': 'Deny', '이 세션에서 항상 허용': 'Always allow in this session', '계속': 'Continue', '멈추기': 'Stop here', '계속할까요?': 'Continue?',
    '허용함': 'Allowed', '거부함': 'Denied', '이 세션에서 항상 허용함': 'Always allowed in this session', '계속함': 'Continued', '멈춤': 'Stopped',
    '차단 목록에 있는 명령입니다': 'This command is on the deny list', '허용 폴더 밖의 경로입니다': 'This path is outside the allowed folders',
    '묻기 모드라 승인이 필요합니다': 'Ask mode needs your approval', '스텝 또는 시간 예산을 다 썼습니다': 'The step or time budget is used up',
    'Auto 모드에서는 안전 목록 밖의 명령이라 승인이 필요합니다': 'Auto mode asks for commands outside the safe list',
    '승인이 필요합니다': 'Approval needed',
    '작업 폴더': 'Working folder', '추가 폴더': 'Extra folders', '브랜치': 'Branch', 'git 저장소 아님': 'Not a git repository',
    '컨텍스트 사용률': 'Context used', '세션을 고르면 여기에 표시됩니다': 'Shown here once a session is open',
    '폴더를 불러오지 못했습니다': 'Could not load the folder', '빈 폴더': 'Empty folder', '폴더가 아닙니다': 'Not a folder',
    '이 세션에서 실행한 명령이 없습니다': 'No commands run in this session yet', '실행 중인 작업이 없습니다': 'No running tasks',
    '트랜스크립트로': 'Back to transcript', '이진 파일이라 미리 볼 수 없습니다': 'Binary file, no preview', '파일을 불러오지 못했습니다': 'Could not load the file',
    '허용 폴더 안의 경로만 쓸 수 있습니다': 'Only paths inside the allowed folders can be used', '제목 (선택)': 'Title (optional)',
    '비우면 폴더 이름을 씁니다': 'Leave blank to use the folder name', '작업 폴더를 적어 주세요': 'Enter a working folder',
    'Auto: 읽기 · 검색 · 편집과 안전 목록의 명령은 바로 하고, 그 밖의 명령 · 삭제 · 폴더 밖 경로는 묻습니다': 'Auto: reads, searches, edits and safe-list commands run at once; other commands, deletions and outside paths ask first',
    '묻기: 편집과 명령을 모두 먼저 묻습니다': 'Ask: every edit and command asks first',
    '세션 이름 바꾸기': 'Rename session', '이름을 적어 주세요': 'Enter a name', '세션 삭제': 'Delete session',
    '이 세션을 삭제할까요? 트랜스크립트도 함께 지워집니다.': 'Delete this session? Its transcript is deleted too.',
    '실행 중이면 먼저 중단합니다.': 'A running session is stopped first.', '세션을 삭제했습니다.': 'Session deleted.',
    // 2차 · 3차(계약 2 H 절) / phases 2 and 3 (contract 2, section H)
    '실행 중에도 보낼 수 있습니다. 다음 단계 사이에 끼워 넣습니다': 'You can send while it runs. It goes in before the next step',
    '일치하는 명령이 없습니다': 'No matching commands', '명령을 불러오지 못했습니다': 'Could not load the commands',
    '끼워 넣음': 'Steered', '전달 대기': 'Pending', '플랜': 'Plan',
    '플랜: 읽기 · 조사만 하고 파일은 고치지 않습니다. 끝에 단계별 계획을 냅니다': 'Plan: reads and researches only, never edits files; ends with a step-by-step plan',
    'Auto 모드에서도 바깥으로 보내는 MCP 도구는 승인이 필요합니다': 'Outward MCP tools ask even in Auto mode',
    '이 폴더의 훅(.ai365/hooks.json)을 이 세션에서 실행해도 될지 확인합니다': "Confirm running this folder's hooks (.ai365/hooks.json) in this session",
    '이 시점으로 되돌리기': 'Restore to this point', '이 시점으로 되돌릴까요?': 'Restore to this point?', '되돌리기': 'Restore',
    '이 메시지를 보내기 전 상태로 작업 폴더의 파일을 되돌립니다. 그 뒤에 바뀐 내용은 사라집니다(무시된 파일은 그대로 둡니다).': 'The working folder goes back to how it was before this message. Changes made after it are lost (ignored files stay as they are).',
    '체크포인트로 되돌렸습니다': 'Restored to the checkpoint',
    '플랜 모드': 'Plan mode', '계획대로 실행': 'Run the plan', '플랜 모드 유지': 'Stay in plan mode', '위 계획대로 진행해줘': 'Go ahead with the plan above',
    '지시 내용': 'Prompt', '서브에이전트 결과': 'Subagent result', '아직 도구를 쓰지 않았습니다': 'No tool calls yet',
    '세션 시작': 'Session start', '요청 받음': 'Prompt received', '도구 실행 전': 'Before a tool', '도구 실행 뒤': 'After a tool', '턴 끝': 'Turn end',
    '차단함': 'Blocked', '시간 초과': 'Timed out', '이유': 'Reason',
    '컨텍스트 압축': 'Context compacted', '대화 기록': 'History', '이번 작업': 'This task',
    '완료 알림을 보냈습니다': 'Completion notice sent', '완료 알림을 보내지 못했습니다': 'Could not send the completion notice',
    '관리 센터 › API · MCP 연결에 등록된 MCP 도구가 없습니다': 'No MCP tools are registered in Admin Center › API · MCP connections',
    '연결 도구를 불러오지 못했습니다': 'Could not load the connectors', '읽기 전용': 'Read only', '외부 실행': 'Action',
    '고른 도구만 이 세션의 에이전트가 씁니다': 'The agent in this session uses only the checked tools',
    'git 저장소가 아닙니다': 'Not a git repository', '변경 사항이 없습니다': 'No changes', '변경 사항을 불러오지 못했습니다': 'Could not load the changes',
    '체크포인트 만들기': 'Create checkpoint', '커밋': 'Commit', '마지막 체크포인트': 'Last checkpoint', '이진': 'Binary',
    '체크포인트를 만들었습니다': 'Checkpoint created', '실행 중에는 쓸 수 없습니다': 'Not available while running',
    '변경 사항 커밋': 'Commit changes', '작업 폴더의 변경 사항을 모두 스테이징해 커밋합니다.': 'Stages every change in the working folder and commits it.',
    '커밋 메시지': 'Commit message', '커밋 메시지(한국어 / English)': 'Commit message (Korean / English)', '메시지 제안': 'Suggest a message',
    '커밋 메시지를 적어 주세요': 'Enter a commit message', '커밋했습니다': 'Committed', '제안을 받지 못했습니다': 'Could not get a suggestion',
    '이진 파일이라 비교할 수 없습니다': 'Binary file, no diff', '변경 내용이 길어 앞부분만 보여 줍니다': 'Long diff, showing the beginning only',
    '표시할 변경이 없습니다': 'No changes to show', '변경을 불러오지 못했습니다': 'Could not load the diff',
    '이 세션이 만든 파일이 없습니다': 'No files from this session yet', '새로 만듦': 'Created', '수정됨': 'Modified', '지워짐': 'Deleted',
    '내려받기': 'Download', '산출물을 불러오지 못했습니다': 'Could not load the outputs', '산출물': 'Outputs',
    '완료 알림 켜기': 'Turn on completion notices', '완료 알림 끄기': 'Turn off completion notices',
    '완료 알림을 켰습니다': 'Completion notices on', '완료 알림을 껐습니다': 'Completion notices off', '새 활동': 'New activity',
    // 적대 검토 반영(2026-10-19) / adversarial review fixes (2026-10-19)
    '이미 정리된 체크포인트입니다': 'This checkpoint has already been cleaned up', '전달되지 않음': 'Not delivered',
    '사용할 수 없음': 'Unavailable', '관리 센터에서 지웠거나 끈 도구입니다. 이 세션 설정에는 그대로 남겨 둡니다': 'Removed or turned off in the Admin Center; kept in this session as is',
    '내려받지 못했습니다': 'Could not download', '슬래시 명령': 'Slash commands',
    // 폴더 고르기 · 규칙 범위(2026-10-19) / folder picking and rule scopes (2026-10-19)
    '찾아보기…': 'Browse…', '서버 폴더에서 고르기': 'Pick from server folders',
    '폴더 선택 창을 열었습니다. 창이 보이지 않으면 작업 표시줄을 확인하세요': 'The folder window is open. If you cannot see it, check the taskbar',
    '허용 폴더 밖입니다. 관리 센터 › Agentic 설정에서 추가하세요': 'Outside the allowed folders. Add it in Admin Center › Agentic settings',
    '이미 폴더 선택 창이 열려 있습니다': 'A folder window is already open',
    '폴더 고르기': 'Choose a folder', '이 폴더 선택': 'Select this folder', '위로': 'Up', '처음으로': 'Top', '드라이브': 'Drives',
    '하위 폴더가 없습니다': 'No subfolders', '폴더가 많아 500개까지만 보여 줍니다': 'Showing the first 500 folders',
    '작업 폴더 선택': 'Choose a working folder', '추가 폴더 선택': 'Choose an extra folder', '추가 폴더…': 'Extra folders…',
    '에이전트가 작업 폴더 밖에서도 읽고 고칠 수 있는 폴더입니다. 허용 폴더 안에서만 고를 수 있습니다.': 'Folders the agent may also read and edit outside the working folder. Only folders inside the allowed folders can be chosen.',
    '추가 폴더가 없습니다': 'No extra folders', '이미 목록에 있는 폴더입니다': 'This folder is already in the list',
    // 내 컴퓨터 폴더(2026-10-20, 계약 F4). {name} · {n} 은 그리는 때 채운다 / folders on my computer (contract F4); {name} and {n} are filled when drawn
    '내 컴퓨터 폴더 열기…': 'Open a folder on my computer…', '내 컴퓨터 폴더 열기': 'Open a folder on my computer',
    '브라우저로 내 컴퓨터의 폴더를 고릅니다. 에이전트가 그 폴더 안의 파일을 읽고 고칩니다(명령 실행 없음).': 'Pick a folder on your computer in the browser. The agent reads and edits the files in it (no commands).',
    '또는 서버 폴더': 'Or a server folder', '서버 폴더로 새 세션': 'New session on a server folder',
    // 원인은 대개 비보안 http 원점이다(적대 검토 2026-10-20) / usually an insecure http origin (review 2026-10-20)
    '이 브라우저 · 주소에서는 내 컴퓨터 폴더 열기를 쓸 수 없습니다(Edge · Chrome 의 https 또는 localhost 에서만)': 'Folders on your computer cannot be opened in this browser or at this address (Edge or Chrome over https or localhost only)',
    '이 서버에서는 내 컴퓨터 폴더 세션을 쓸 수 없습니다': 'This server does not allow sessions on a folder on your computer',
    '내 컴퓨터': 'My computer', '내 컴퓨터(브라우저)': 'My computer (browser)', '연결됨': 'Connected', '연결 안 됨': 'Not connected', '허용 필요': 'Permission needed',
    '폴더 다시 연결…': 'Reconnect folder…',
    "세션 폴더 '{folder}' 과 이름이 다른 폴더입니다: {name}. 이 폴더를 연결할까요?": "This folder's name differs from the session folder '{folder}': {name}. Connect this folder?",
    "이 세션의 폴더 '{name}' 을(를) 이 브라우저에서 다시 열어 주세요": "Open this session's folder '{name}' again in this browser",
    "폴더 '{name}' 접근을 허용해 주세요": "Allow access to the folder '{name}'", '폴더 접근이 거부되었습니다': 'Folder access was denied',
    '에이전트가 폴더를 기다리고 있습니다({n})': 'The agent is waiting for the folder ({n})', '폴더 열기': 'Open folder',
    '미리 볼 수 없습니다': 'No preview', '폴더 선택 창을 열지 못했습니다': 'Could not open the folder window',
  };
  if (typeof AI365_KO2EN !== 'undefined') {
    Object.keys(DICT).forEach(function (k) { if (!(k in AI365_KO2EN)) AI365_KO2EN[k] = DICT[k]; });
  }

  /* ── 아이콘 / icons ── */
  function svg(w, body, sw) {
    return '<svg width="' + w + '" height="' + w + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="' + (sw || 1.9)
      + '" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + body + '</svg>';
  }
  const IC = {
    plus: svg(13, '<path d="M12 5v14M5 12h14"/>', 2.4),
    search: svg(14, '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>'),
    sidebar: svg(17, '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9.5 4v16"/>', 2),
    agentic: svg(18, '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m7.5 9.5 3 2.5-3 2.5"/><path d="M12.5 15h4"/>'),
    left: svg(17, '<path d="m15 18-6-6 6-6"/>', 2.1),
    right: svg(17, '<path d="m9 18 6-6-6-6"/>', 2.1),
    chev: svg(14, '<path d="m6 9 6 6 6-6"/>', 2.1),
    chevR: svg(13, '<path d="m9 6 6 6-6 6"/>', 2.2),
    transcript: svg(17, '<path d="M4 5h16v11H9l-5 4z"/><path d="M8 9h8M8 12.5h5"/>'),
    terminal: svg(17, '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="m7 9 3 3-3 3"/><path d="M12.5 15H17"/>'),
    files: svg(17, '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'),
    panel: svg(17, '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M15 4v16"/>'),
    folder: svg(14, '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'),
    file: svg(14, '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>'),
    read: svg(15, '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/>'),
    write: svg(15, '<path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z"/>'),
    run: svg(15, '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="m7 9 3 3-3 3"/><path d="M12.5 15H17"/>'),
    find: svg(15, '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>'),
    web: svg(15, '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18z"/>'),
    mcp: svg(15, '<path d="M9 7V3M15 7V3"/><path d="M6 7h12v4a6 6 0 0 1-12 0z"/><path d="M12 17v4"/>'),
    tool: svg(15, '<path d="M14.7 6.3a4.5 4.5 0 0 0-6 5.6L3 17.6V21h3.4l5.7-5.7a4.5 4.5 0 0 0 5.6-6L14.5 12l-2.5-2.5 2.7-3.2z"/>'),
    shield: svg(16, '<path d="M12 3 5 6v5c0 4.5 3 8.3 7 10 4-1.7 7-5.5 7-10V6z"/><path d="M12 8v4.5"/><path d="M12 15.5h.01"/>', 2),
    clock: svg(16, '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', 2),
    check: svg(12, '<path d="m5 12.5 4.5 4.5L19 7.5"/>', 2.6),
    x: svg(14, '<path d="M6 6l12 12M18 6 6 18"/>', 2.2),
    alert: svg(15, '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5"/><path d="M12 16h.01"/>', 2),
    send: svg(16, '<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>', 2.4),
    stop: '<svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="3" fill="currentColor"/></svg>',
    edit: svg(15, '<path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z"/>'),
    trash: svg(15, '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'),
    branch: svg(13, '<circle cx="6" cy="5" r="2.2"/><circle cx="6" cy="19" r="2.2"/><circle cx="18" cy="8" r="2.2"/><path d="M6 7.2v9.6"/><path d="M18 10.2c0 4-6 3.5-11.2 7"/>'),
    // 2차 / phase 2
    agent: svg(15, '<rect x="4.5" y="8" width="15" height="11" rx="3"/><path d="M12 8V4.6"/><circle cx="12" cy="3.6" r="1"/><path d="M9.5 13.2h.01M14.5 13.2h.01"/><path d="M2.5 12.5v2.5M21.5 12.5v2.5"/>'),
    hook: svg(14, '<path d="M7 4v8.5a5 5 0 0 0 10 0V9"/><path d="m14 12 3-3 3 3"/>'),
    compact: svg(14, '<path d="M4 12h16"/><path d="m9 4 3 3 3-3"/><path d="m9 20 3-3 3 3"/>'),
    restore: svg(15, '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1"/><path d="M3.5 4.5v4.2h4.2"/>', 2),
    bell: svg(15, '<path d="M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 21h4"/>'),
    outputs: svg(17, '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M12 11v6"/><path d="m9.5 14.5 2.5 2.5 2.5-2.5"/>'),
    download: svg(14, '<path d="M12 4v11"/><path d="m7 11 5 5 5-5"/><path d="M5 20h14"/>', 2.1),
    commit: svg(14, '<circle cx="12" cy="12" r="3.2"/><path d="M3 12h5.8M15.2 12H21"/>', 2.1),
    plan: svg(15, '<path d="M10 6h10M10 12h10M10 18h10"/><path d="m3.5 6 1.3 1.3L7.5 4.6M3.5 12l1.3 1.3 2.7-2.7M3.5 18l1.3 1.3 2.7-2.7"/>'),
    flag: svg(14, '<path d="M5 21V4"/><path d="M5 4h11l-2 4 2 4H5"/>', 2),
    // 폴더 고르기(2026-10-19) / folder picking
    up: svg(14, '<path d="M12 19V6"/><path d="m6 11.5 6-6 6 6"/>', 2.2),
    home: svg(14, '<path d="M4 11.5 12 5l8 6.5"/><path d="M6.5 10v9.5h11V10"/>', 2),
    drive: svg(14, '<rect x="3" y="13" width="18" height="7" rx="2"/><path d="M5.2 13 7.6 5h8.8l2.4 8"/><path d="M16.5 16.5h.01"/>', 2),
    // 내 컴퓨터 폴더(2026-10-20): 노트북 / folders on my computer: a laptop
    laptop: svg(15, '<rect x="4" y="5" width="16" height="10.5" rx="1.6"/><path d="M2.5 19h19"/>'),
  };
  const GROUP_ICON = { read: IC.read, write: IC.write, run: IC.run, search: IC.find, web: IC.web, mcp: IC.mcp, agent: IC.agent };

  /* ── 스타일 / styles ── */
  (function style() {
    const MONO = 'ui-monospace,Consolas,"Cascadia Mono","Courier New",monospace';
    // Figma DS 적용(2026-10-28, docs/figma-design-system-spec.md 6 · 7절, 사용자 지시 "모두 디자인 시스템대로"): 버튼 = DS 코어 직사각 r8(Secondary ·
    // Primary · Subtle 아이콘 · 위험 채움, hover · pressed · selected · disabled 단계), 세션 목록 = DS Nav(40 · r4 · 선택 막대 4×16 · hover 글자 브랜드),
    // 메뉴 · 슬래시 팝업 = DS Menu(r12 · 안쪽 4 · Shadow 16, 항목 32 · r6), 대화 상자 = DS Dialog(600 · r16 · 안쪽 24 · Shadow 64 · 제목 Subtitle 1 ·
    // CTA 36 알약), 입력칸 = DS Outline 입력(32 · r8, 포커스 = 아래 2px 브랜드), 입력줄 = 제품 시트 입력 카드(r24 · Stroke 2 · Shadow 12, 모델 ·
    // 권한 = 알약 40, 보내기 = 원 40), 승인 · 오류 · 폴더 안내 = DS 메시지 바(경고 · 오류), 배지 = DS Badge r4 틴트, 상태 색 = DS 램프,
    // 글자 = DS 글자 단계(500 → 400, 800 → 700). 모든 DS 토큰에 adapter.js ai365DsTokens 와 같은 값을 기본값으로 함께 적는다.
    // Figma DS applied (2026-10-28, sections 6 and 7 of docs/figma-design-system-spec.md; the user's "apply the design system everywhere"):
    // DS core r8 buttons (Secondary, Primary, Subtle icon, danger fill; hover, pressed, selected and disabled steps), the session list as
    // DS Nav (40, r4, a 4x16 selection bar, brand text on hover), menus and the slash popup as DS Menu (r12, 4 padding, Shadow 16; 32px r6
    // items), dialogs as DS Dialog (600, r16, 24 padding, Shadow 64, Subtitle 1 title, 36px pill CTAs), DS Outline inputs (32, r8; focus = a
    // 2px brand bottom bar), the input row as the product-sheet composer (r24, Stroke 2, Shadow 12; model and permission pills 40, a 40px
    // round send), approval, error and folder notices as DS message bars (warning, error), DS r4 tint badges, the DS status ramps and the
    // DS type ramp (500 → 400, 800 → 700). Every DS token carries the adapter.js ai365DsTokens value as its fallback.
    const D = function (name, value) { return 'var(--ds-' + name + ',' + value + ')'; };
    const FONT = '"Pretendard",-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR","Segoe UI",sans-serif';
    const TY = function (role, w, size) { return D('type-' + role, w + ' ' + size + ' ' + FONT); };
    const FG1 = D('fg-1', '#21242C'), FG2 = D('fg-2', '#3E424B'), FG3 = D('fg-3', '#5D616A'), FG4 = D('fg-4', '#6C707A'), FG_DIS = D('fg-disabled', '#B9BDC8');
    const FG_ON = D('fg-on-brand', '#FFFFFF'), FG_BRAND = D('fg-brand-1', '#4450CE'), FG_LINK = D('fg-link', '#3940BD'), FGB2 = D('fg-brand-2', '#3940BD');
    const FG2_H = D('fg-2-hover', '#21242C'), FG2_BH = D('fg-2-brand-hover', '#4450CE'), FG2_BP = D('fg-2-brand-pressed', '#3940BD'), FG2_BS = D('fg-2-brand-selected', '#4450CE');
    const BG1 = D('bg-1', '#FFFFFF'), BG1_H = D('bg-1-hover', '#F6F8FD'), BG1_P = D('bg-1-pressed', '#DCE0EB'), BG1_S = D('bg-1-selected', '#E7EBF6');
    const BG2 = D('bg-2', '#FAFCFF'), BG3 = D('bg-3', '#F6F8FD'), BG3_H = D('bg-3-hover', '#E7EBF6'), BG3_P = D('bg-3-pressed', '#D2D6E1'), BG4 = D('bg-4', '#EFF2FA');
    const BG4_H = D('bg-4-hover', '#FAFCFF'), BG5 = D('bg-5', '#E7EBF6'), BG_DIS = D('bg-disabled', '#EFF2FA');
    const SUB_H = D('subtle-bg-hover', '#F6F8FD'), SUB_P = D('subtle-bg-pressed', '#DCE0EB'), SUB_S = D('subtle-bg-selected', '#E7EBF6');
    const BRAND = D('brand-bg', '#4450CE'), BRAND_H = D('brand-bg-hover', '#3940BD'), BRAND_P = D('brand-bg-pressed', '#1D008B');
    const BRAND2 = D('brand-bg-2', '#E4EDFF'), BRAND2_H = D('brand-bg-2-hover', '#CCDAFF'), CB = D('compound-brand', '#4450CE');
    const B110 = D('brand-110', '#7186FF'), B170 = D('brand-170', '#F2F6FF'), BSTROKE2 = D('brand-stroke-2', '#B4C6FF');
    const ST1 = D('stroke-1', '#CDD1DC'), ST1_H = D('stroke-1-hover', '#C3C7D2'), ST1_P = D('stroke-1-pressed', '#AFB3BE'), ST2 = D('stroke-2', '#DCE0EB');
    const ACC = D('stroke-accessible', '#5D616A'), ACC_H = D('stroke-accessible-hover', '#535760'), ST_DIS = D('stroke-disabled', '#DCE0EB');
    const OK = D('success-fg-1', '#0E700E'), OK_BG = D('success-bg-1', '#F1FAF1'), OK_FILL = D('success-bg-3', '#359B35'), OK_BD = D('success-border-1', '#9FD89F');
    const WARN_IC = D('warning-fg-1', '#BC4B09'), WARN_FG = D('warning-fg-2', '#8A3707'), WARN_BG = D('warning-bg-1', '#FFF9F5'), WARN_FILL = D('warning-bg-3', '#F87528');
    const WARN_BD = D('warning-border-1', '#FDCFB4');
    const BAD = D('danger-fg-1', '#C50F1F'), BAD_BG = D('danger-bg-1', '#FDF3F4'), BAD_FILL = D('danger-bg-3', '#CC2635'), BAD_BD = D('danger-border-1', '#EEACB2');
    const BAD_SHADE = D('cranberry-shade-20', '#960B18');
    const SH12 = D('shadow-12', '0 0 2px #15135208, 0 8px 16px #15135214'), SH16 = D('shadow-16', '0 0 2px #1513520F, 0 8px 16px #15135224');
    const SH64 = D('shadow-64', '0 0 8px #1513521F, 0 32px 64px #1513523D'), RING = D('focus-ring', '0 0 0 1px #FFFFFF, 0 0 0 3px #000000');
    const R_BTN = D('radius-button', '8px'), R_IN = D('radius-input', '8px'), R_CARD = D('radius-card', '8px'), R_TAG = D('radius-tag', '8px'), R_NAV = D('radius-nav-item', '4px');
    const R_MENU = D('radius-menu', '12px'), R_ITEM = D('radius-menu-item', '6px'), R_BADGE = D('radius-badge', '4px'), R_DLG = D('radius-dialog', '16px'), R_MB = D('radius-message-bar', '8px');
    const R_CHK = D('radius-checkbox', '2px'), R_COMP = D('radius-composer', '24px'), R2 = D('radius-2', '2px'), R4 = D('radius-4', '4px'), R8 = D('radius-8', '8px');
    const R12 = D('radius-12', '12px'), R_FULL = D('radius-full', '9999px');
    const CAP2 = TY('caption-2', 400, '10px/14px'), CAP2S = TY('caption-2-strong', 600, '10px/14px'), CAP1 = TY('caption-1', 400, '12px/16px'), CAP1S = TY('caption-1-strong', 600, '12px/16px');
    const B1 = TY('body-1', 400, '14px/20px'), B1S = TY('body-1-strong', 600, '14px/20px'), B2 = TY('body-2', 400, '16px/22px'), SUB2 = TY('subtitle-2', 600, '16px/22px');
    const SUB1 = TY('subtitle-1', 600, '20px/28px');
    // 셀렉트 화살표(색 = NeutralForeground3 #5D616A) / the select arrow (colour = NeutralForeground3)
    const CHEV = 'url("data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 width=%2712%27 height=%2712%27 viewBox=%270 0 24 24%27 fill=%27none%27 stroke=%27%235D616A%27 stroke-width=%272.4%27 stroke-linecap=%27round%27 stroke-linejoin=%27round%27%3E%3Cpath d=%27m6 9 6 6 6-6%27/%3E%3C/svg%3E")';
    // 체크 표시(흰색) · 오류 아이콘(Danger foreground 1) / the check mark (white) and the error icon (Danger foreground 1)
    const CHECK = 'url("data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 12 12%27 fill=%27none%27 stroke=%27white%27 stroke-width=%271.6%27 stroke-linecap=%27round%27 stroke-linejoin=%27round%27%3E%3Cpath d=%27m2.5 6.2 2.3 2.3 4.7-4.9%27/%3E%3C/svg%3E")';
    const ERR_IC = 'url("data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 20 20%27%3E%3Ccircle cx=%2710%27 cy=%2710%27 r=%278%27 fill=%27%23C50F1F%27/%3E%3Cpath d=%27m7.2 7.2 5.6 5.6M12.8 7.2l-5.6 5.6%27 stroke=%27white%27 stroke-width=%271.6%27 stroke-linecap=%27round%27/%3E%3C/svg%3E")';
    // DS 체크박스(16 · r2 · 1px Stroke accessible, 켜짐 = 브랜드 채움 + 흰 체크) / the DS checkbox (16, r2; on = brand fill and a white check)
    const CHK = 'appearance:none;-webkit-appearance:none;flex:none;width:16px;height:16px;border:1px solid ' + ACC + ';border-radius:' + R_CHK + ';background:' + BG1 + ' center/12px no-repeat;';
    const CHK_ON = 'background-color:' + CB + ';background-image:' + CHECK + ';border-color:' + CB + ';';
    const s = document.createElement('style');
    s.id = 'ai365AgStyle';
    s.textContent = [
      /* 셸 켜짐: 목업 사이드바 자식은 숨기기만 한다 / shell on: the mockup's sidebar children are only hidden */
      'body.ai365-ag-on aside.sidebar > :not(.ai365-ag-side){display:none !important;}',
      '.ai365-ag [hidden],.ai365-ag-side [hidden],.ai365-ag-ov [hidden],.ai365-ag-hl [hidden],.ai365-ag-hr [hidden]{display:none !important;}',
      '.ai365-ag button,.ai365-ag-side button,.ai365-ag-ov button,.ai365-ag-hl button,.ai365-ag-hr button,.ai365-ag-menu button{font-family:inherit;cursor:pointer;}',
      // 포커스 = DS(Fluent) 링(입력칸은 아래 2px 브랜드 막대) / focus = the DS (Fluent) ring (inputs use the 2px brand bottom bar)
      ':is(.ai365-ag,.ai365-ag-side,.ai365-ag-ov,.ai365-ag-hl,.ai365-ag-hr,.ai365-ag-menu) :is(button,[tabindex]):focus-visible{outline:none;box-shadow:' + RING + ';}',
      '@keyframes ai365AgSpin{to{transform:rotate(360deg);}}',
      '@keyframes ai365AgPulse{0%,100%{opacity:1;transform:scale(1);}50%{opacity:.35;transform:scale(.78);}}',
      '@keyframes ai365AgFlash{0%{background:' + BRAND2 + ';}100%{background:transparent;}}',
      '@keyframes ai365AgIn{from{opacity:0;transform:translateY(4px);}to{opacity:1;transform:none;}}',
      /* 사이드바 = DS Nav(제품 시트): 위 48px · 항목 40 · r4 · 간격 8, hover = 글자 브랜드, 선택 = Foreground 1 semibold + 왼쪽 4×16 막대 /
         sidebar = DS Nav (product sheet): a 48px top, 40px r4 rows with an 8 gap; hover = brand text; selected = Foreground 1 semibold and a 4x16 bar */
      '.ai365-ag-side{display:flex;flex-direction:column;flex:1;min-height:0;}',
      '.ai365-ag-stop{flex:none;display:flex;align-items:center;gap:8px;height:48px;padding:8px 4px 0 16px;}',
      '.ai365-ag-stop .lg{display:flex;color:' + CB + ';}',
      '.ai365-ag-stop .nm{font:' + SUB2 + ';color:' + FG1 + ';}',
      '.ai365-ag-stop .sp{flex:1;}',
      '.sidebar.collapsed .ai365-ag-stop{justify-content:center;padding:8px 0 0;}',
      '.ai365-ag-sbody{flex:1;min-height:0;display:flex;flex-direction:column;padding:4px 10px 0;}',
      '.sidebar.collapsed .ai365-ag-sbody{padding:4px 10px 0;}',
      // 세션 검색 = DS SearchBox(Filled darker = Background 4 · r8 · 32, 앞 검색 아이콘, 포커스 = 아래 2px 브랜드) / session search = a DS SearchBox
      '.ai365-ag-ssearch{position:relative;display:flex;align-items:center;margin:6px 0 4px;color:' + FG3 + ';}',
      '.ai365-ag-ssearch svg{position:absolute;left:10px;pointer-events:none;}',
      '.ai365-ag-ssearch input{width:100%;height:32px;border:0;border-radius:' + R_IN + ';background:' + BG4 + ';padding:0 10px 0 32px;font:' + B1 + ';color:' + FG1 + ';outline:0;transition:background .12s,box-shadow .12s;}',
      '.ai365-ag-ssearch input:hover{background:' + BG4_H + ';}',
      '.ai365-ag-ssearch input::placeholder{color:' + FG4 + ';}',
      '.ai365-ag-ssearch input:focus{background:' + BG4 + ';box-shadow:inset 0 -2px 0 ' + CB + ';}',
      '.ai365-ag-slist{flex:1;min-height:0;overflow-y:auto;margin:0 -4px;padding:2px 4px 16px;}',
      '.ai365-ag-slist::-webkit-scrollbar{width:6px;}',
      '.ai365-ag-slist::-webkit-scrollbar-thumb{background:' + D('grey-90', '#E2E6F1') + ';border-radius:' + R_FULL + ';}',
      '.ai365-ag-sgrp{margin-top:10px;}',
      '.sidebar.collapsed .ai365-ag-sgrp{margin-top:6px;}',
      '.ai365-ag-sgh{display:flex;align-items:center;gap:6px;height:32px;padding:0 10px;font:' + CAP1S + ';color:' + FG3 + ';min-width:0;}',
      '.ai365-ag-sgh span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-ag-sess{width:100%;height:40px;display:flex;align-items:center;gap:8px;padding:0 10px;border-radius:' + R_NAV + ';font:' + B1 + ';color:' + FG2 + ';text-align:left;position:relative;transition:color .12s,background .12s;}',
      '.ai365-ag-sess:hover{color:' + FG2_BH + ';}',
      '.ai365-ag-sess:active{color:' + FG2_BP + ';}',
      '.ai365-ag-sess.on{background:none;color:' + FG1 + ';font-weight:600;}',
      '.ai365-ag-sess.on::before{content:"";position:absolute;left:0;top:12px;width:4px;height:16px;border-radius:' + R2 + ';background:' + CB + ';}',
      '.ai365-ag-sess .tt{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
      '.ai365-ag-sess .tm{flex:none;font:' + CAP1 + ';color:' + FG4 + ';}',
      '.ai365-ag-sess .dot{flex:none;width:8px;height:8px;border-radius:50%;background:transparent;}',
      '.ai365-ag-sess .av{display:none;position:relative;width:32px;height:32px;border-radius:' + R_BTN + ';background:' + BG5 + ';color:' + FG2 + ';font:' + CAP1S + ';align-items:center;justify-content:center;}',
      '.ai365-ag-sess.on .av{background:' + BRAND2 + ';color:' + CB + ';}',
      '.ai365-ag-sess .av .dot{position:absolute;top:-2px;right:-2px;border:2px solid ' + BG3 + ';width:10px;height:10px;}',
      '.sidebar.collapsed .ai365-ag-sess{justify-content:center;padding:0;}',
      '.sidebar.collapsed .ai365-ag-sess.on::before{display:none;}',
      '.sidebar.collapsed .ai365-ag-sess.on{background:transparent;}',
      '.sidebar.collapsed .ai365-ag-sess .av{display:flex;}',
      // 상태 점 = DS 상태 채움 색(성공 · 위험 · 경고 Background 3, 실행 = 브랜드) / state dots = the DS status fills (success, danger, warning Background 3; running = brand)
      '.dot.running{background:' + CB + ' !important;animation:ai365AgPulse 1.1s ease-in-out infinite;}',
      '.dot.waiting{background:' + WARN_FILL + ' !important;}',
      '.dot.error{background:' + BAD_FILL + ' !important;}',
      '.ai365-ag-snone{padding:12px 10px;font:' + CAP1 + ';color:' + FG3 + ';}',
      /* 머리줄(아이콘 버튼 = DS Subtle 아이콘 버튼 M 32 · r8, 오른쪽 120px = 우상단 고정 묶음 #hdrFixed 자리) / sub-header (DS Subtle icon buttons M; the right 120px belongs to #hdrFixed) */
      // 셸이 켜진 동안 #viewWork 머리줄은 가로 한 줄(flex)로 두고 오른쪽 여백은 .ai365-ag-hr 의 120px 하나로 센다(목업 머리줄의 오른쪽 padding 과 겹쳐 세지 않게,
      // 다른 머리줄처럼 화면 오른쪽 끝에서 120px)
      // While the shell is on, #viewWork's sub-header stays one flex row and the right gap is .ai365-ag-hr's 120px alone (not added on top of
      // the mockup header's right padding; 120px from the right edge like the other headers)
      'body.ai365-ag-on #viewWork > .sub-header{display:flex;align-items:center;padding-right:0;}',
      '.ai365-ag-hl{display:flex;align-items:center;gap:2px;min-width:0;max-width:calc(50% - 128px);}',
      '.ai365-ag-hr{margin-left:auto;margin-right:120px;display:flex;align-items:center;gap:2px;}',
      '.ai365-ag-nav{width:32px;height:32px;border-radius:' + R_BTN + ';display:flex;align-items:center;justify-content:center;color:' + FG2 + ';flex:none;transition:background .12s,color .12s;}',
      '.ai365-ag-nav:hover{background:' + SUB_H + ';color:' + FG2_BH + ';}',
      '.ai365-ag-nav:active{background:' + SUB_P + ';color:' + FG2_BP + ';}',
      '.ai365-ag-nav:disabled{color:' + FG_DIS + ';background:none;cursor:default;}',
      // 세션 제목 = 제품 시트 머리줄 제목(Subtitle 2 · Foreground 1), 누르면 메뉴(DS Subtle 버튼 단계) / the session title = the product-sheet header title (Subtitle 2); a Subtle button opening the menu
      '.ai365-ag-title{display:flex;align-items:center;gap:6px;min-width:0;height:32px;margin-left:4px;padding:0 8px 0 10px;border-radius:' + R_BTN + ';font:' + SUB2 + ';color:' + FG1 + ';transition:background .12s;}',
      '.ai365-ag-title:hover{background:' + SUB_H + ';}',
      '.ai365-ag-title:active{background:' + SUB_P + ';}',
      '.ai365-ag-title[aria-expanded="true"]{background:' + SUB_S + ';}',
      '.ai365-ag-title .t{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-ag-title svg{color:' + FG3 + ';}',
      '.ai365-ag-hb{width:32px;height:32px;border-radius:' + R_BTN + ';display:flex;align-items:center;justify-content:center;color:' + FG2 + ';transition:background .12s,color .12s;}',
      '.ai365-ag-hb:hover{background:' + SUB_H + ';color:' + FG2_BH + ';}',
      '.ai365-ag-hb:active{background:' + SUB_P + ';color:' + FG2_BP + ';}',
      '.ai365-ag-hb.on{color:' + FG2_BS + ';background:' + SUB_S + ';}',
      /* 세션 메뉴 = DS Menu(r12 · 안쪽 4 · Shadow 16, 항목 32 · r6 · Body 1 Foreground 2 → hover Foreground 1, 구분선 전폭) / the session menu is a DS Menu */
      '.ai365-ag-menu{position:absolute;top:46px;z-index:60;background:' + BG1 + ';border:0;border-radius:' + R_MENU + ';box-shadow:' + SH16 + ';padding:4px;min-width:200px;display:flex;flex-direction:column;gap:2px;}',
      '.ai365-ag-mi{width:100%;min-height:32px;display:flex;align-items:center;gap:8px;padding:6px;border-radius:' + R_ITEM + ';font:' + B1 + ';color:' + FG2 + ';text-align:left;}',
      '.ai365-ag-mi:hover{background:' + SUB_H + ';color:' + FG2_H + ';}',
      '.ai365-ag-mi:active{background:' + SUB_P + ';}',
      '.ai365-ag-mi.danger{color:' + BAD + ';}',
      '.ai365-ag-mi.danger:hover{background:' + BAD_BG + ';color:' + BAD + ';}',
      '.ai365-ag-menu .sep{height:1px;background:' + ST2 + ';margin:2px -4px;}',
      /* 3단 레이아웃 / three-pane layout */
      'body.ai365-ag-on #viewWork .ai365-ca-blank{display:flex;flex-direction:column;min-height:0;}',
      '.ai365-ag{flex:1;min-height:0;display:grid;grid-template-columns:minmax(0,1fr) 300px;border-top:1px solid ' + ST2 + ';color:' + FG1 + ';font:' + B1 + ';}',
      '.ai365-ag.noenv{grid-template-columns:minmax(0,1fr);}',
      '.ai365-ag.noenv > .ai365-ag-env{display:none;}',
      '@media (max-width:1100px){.ai365-ag{grid-template-columns:minmax(0,1fr) 260px;}}',
      '.ai365-ag-main{position:relative;display:flex;flex-direction:column;min-width:0;min-height:0;}',
      '.ai365-ag-scroll{flex:1;min-height:0;overflow-y:auto;}',
      '.ai365-ag-tx{max-width:820px;margin:0 auto;padding:24px 28px 16px;display:flex;flex-direction:column;gap:8px;}',
      '.ai365-ag-tx > *{animation:ai365AgIn .16s ease;}',
      /* 사용자 말풍선(Background 3 · r12 · Body 2 · 80%) · 에이전트 글(Body 2 · Foreground 2) / user bubbles (Background 3, r12, Body 2, 80%) and agent text (Body 2, Foreground 2) */
      '.ai365-ag-msg.user,.ai365-ag-msg.pend{align-self:flex-end;max-width:80%;margin:10px 0 4px;background:' + BG3 + ';border-radius:' + R12 + ';padding:12px;white-space:pre-wrap;word-break:break-word;font:' + B2 + ';color:' + FG2 + ';}',
      '.ai365-ag-msg.pend{opacity:.55;}',
      '.ai365-ag-msg.agent{margin:4px 0;font:' + B2 + ';color:' + FG2 + ';word-break:break-word;}',
      '.ai365-ag-msg.agent p{margin:8px 0;}',
      '.ai365-ag-msg.agent > :first-child{margin-top:0;}',
      '.ai365-ag-hint{margin:40px auto;max-width:420px;text-align:center;font:' + B1 + ';color:' + FG3 + ';}',
      /* 도구 카드(r8 · 1px Stroke 2 · 흰 바탕, 줄 hover = Subtle) / tool cards (r8, a 1px Stroke 2, white; rows hover Subtle) */
      '.ai365-ag-tool{border:1px solid ' + ST2 + ';border-radius:' + R_CARD + ';background:' + BG1 + ';overflow:hidden;}',
      '.ai365-ag-trow{width:100%;min-height:32px;display:flex;align-items:center;gap:8px;padding:6px 12px;font:' + B1 + ';color:' + FG2 + ';text-align:left;transition:background .12s;}',
      '.ai365-ag-trow:hover{background:' + SUB_H + ';}',
      '.ai365-ag-trow:active{background:' + SUB_P + ';}',
      '.ai365-ag-tool .ic{display:flex;color:' + FG3 + ';flex:none;}',
      '.ai365-ag-tool .lb{flex:0 1 auto;min-width:0;font-weight:600;color:' + FG1 + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
      '.ai365-ag-tool .sm{flex:1 1 auto;min-width:0;color:' + FG3 + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
      '.ai365-ag-tool .ds{flex:none;font:' + CAP1 + ';font-variant-numeric:tabular-nums;}',
      '.ai365-ag-tool .ds .a{color:' + OK + ';font-weight:700;}',
      '.ai365-ag-tool .ds .d{color:' + BAD + ';font-weight:700;}',
      '.ai365-ag-tool .du,.ai365-ag-tih .du{flex:none;font:' + CAP1 + ';color:' + FG3 + ';font-variant-numeric:tabular-nums;}',
      '.ai365-ag-tool .cv{flex:none;display:flex;color:' + FG3 + ';transition:transform .15s;}',
      '.ai365-ag-tool.open .cv{transform:rotate(90deg);}',
      /* 상태 점(DS 상태 채움: 성공 · 위험 · 경고 Background 3, 멈춤 = 회색, 실행 = 브랜드) / state dots (DS status fills; stopped = grey; running = brand) */
      '.st{flex:none;width:8px;height:8px;border-radius:50%;background:' + ST1 + ';}',
      '.st.ok{background:' + OK_FILL + ';}',
      '.st.fail{background:' + BAD_FILL + ';}',
      '.st.wait{background:' + WARN_FILL + ';}',
      '.st.stop{background:' + D('grey-66', '#A4A8B2') + ';}',
      '.st.run{background:' + CB + ';animation:ai365AgPulse 1.1s ease-in-out infinite;}',
      '.ai365-ag-tbody{border-top:1px solid ' + ST2 + ';padding:10px 12px 12px;background:' + BG2 + ';display:flex;flex-direction:column;gap:8px;}',
      '.ai365-ag-fp{display:flex;align-items:center;gap:6px;font:' + CAP1 + ';color:' + FG2 + ';word-break:break-all;}',
      '.ai365-ag-fp svg{color:' + FG3 + ';}',
      '.ai365-ag-note{font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-ag-meta{display:flex;flex-wrap:wrap;align-items:center;gap:8px;font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-ag-meta code{font-family:' + MONO + ';font-size:12px;}',
      // 종료 코드 = DS Badge M 20 · r4 틴트 / exit codes = DS Badges M 20, r4, tint
      '.ex{flex:none;display:inline-flex;align-items:center;height:20px;font:' + CAP2S + ';border-radius:' + R_BADGE + ';padding:0 6px;}',
      '.ex.ok{color:' + OK + ';background:' + OK_BG + ';box-shadow:inset 0 0 0 1px ' + OK_BD + ';}',
      '.ex.bad{color:' + BAD + ';background:' + BAD_BG + ';box-shadow:inset 0 0 0 1px ' + BAD_BD + ';}',
      '.ai365-ag-out{margin:0;font-family:' + MONO + ';font-size:12px;line-height:1.55;white-space:pre-wrap;word-break:break-word;color:' + FG1 + ';background:' + BG1 + ';border:1px solid ' + ST2 + ';border-radius:' + R8 + ';padding:10px 12px;max-height:360px;overflow:auto;}',
      '.ai365-ag-out .pr{color:' + FG_BRAND + ';font-weight:600;}',
      '.ai365-ag-out.bad{color:' + BAD + ';}',
      '.ai365-ag-diff{font-family:' + MONO + ';font-size:12px;line-height:1.55;border:1px solid ' + ST2 + ';border-radius:' + R8 + ';background:' + BG1 + ';overflow:auto;max-height:440px;}',
      '.ai365-ag-diff .in{display:inline-block;min-width:100%;padding:4px 0;}',
      '.ai365-ag-diff .l{display:flex;white-space:pre;color:' + FG1 + ';}',
      '.ai365-ag-diff .l i{flex:none;width:44px;padding-right:10px;text-align:right;font-style:normal;color:' + FG4 + ';user-select:none;}',
      '.ai365-ag-diff .l span{padding-right:14px;}',
      // 더한 줄 = 성공 연한 바탕 + Success foreground 1, 지운 줄 = 위험 연한 바탕 + Danger foreground 1 / added lines = the light success ground, removed = the light danger ground
      '.ai365-ag-diff .l.a{background:' + OK_BG + ';color:' + OK + ';}',
      '.ai365-ag-diff .l.d{background:' + BAD_BG + ';color:' + BAD + ';}',
      '.ai365-ag-diff .l.a i{color:' + OK + ';opacity:.75;}',
      '.ai365-ag-diff .l.d i{color:' + BAD + ';opacity:.75;}',
      '.ai365-ag-diff .l.k{background:' + B170 + ';color:' + FG_BRAND + ';}',
      '.ai365-ag-diff .l.h{color:' + FG3 + ';font-weight:600;}',
      /* 승인 카드 = DS 메시지 바(경고: Warning background 1 · 1px Warning border 1 · r8, 아이콘 Warning foreground 1) · 상태 줄 · 요약 칩 · 오류 줄 /
         the approval card = a DS message bar (warning), the status line, the summary chip and the error line */
      '.ai365-ag-approval{border:1px solid ' + WARN_BD + ';background:' + WARN_BG + ';border-radius:' + R_MB + ';padding:12px;display:flex;flex-direction:column;gap:8px;}',
      '.ai365-ag-approval .hd{display:flex;align-items:center;gap:8px;font:' + B1 + ';color:' + FG1 + ';min-width:0;}',
      '.ai365-ag-approval .hd .ic{display:flex;color:' + WARN_IC + ';flex:none;}',
      '.ai365-ag-approval .hd b{font-weight:600;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-ag-approval .rs{font:' + CAP1 + ';color:' + WARN_FG + ';}',
      '.ai365-ag-approval .ar{font-family:' + MONO + ';font-size:12px;line-height:1.5;color:' + FG1 + ';background:' + BG1 + ';border:1px solid ' + WARN_BD + ';border-radius:' + R8 + ';padding:6px 10px;white-space:pre-wrap;word-break:break-all;max-height:160px;overflow:auto;}',
      '.ai365-ag-approval .acts{display:flex;flex-wrap:wrap;gap:8px;}',
      '.ai365-ag-approval.done{border-color:' + ST2 + ';background:' + BG2 + ';}',
      '.ai365-ag-approval.done .hd .ic{color:' + FG3 + ';}',
      '.ai365-ag-approval.done .rs{color:' + FG3 + ';}',
      '.ai365-ag-approval .res{display:flex;align-items:center;gap:6px;font:' + CAP1S + ';}',
      '.ai365-ag-approval .res.allow,.ai365-ag-approval .res.always{color:' + OK + ';}',
      '.ai365-ag-approval .res.deny{color:' + BAD + ';}',
      '.ai365-ag-approval .res .at{font-weight:400;color:' + FG3 + ';}',
      /* 버튼 = DS 코어 버튼 M(r8 · 32 · Body 1 Strong): 기본 Secondary, .pri = Primary, .danger = 위험 채움(Danger background 3) / buttons = DS core buttons M: Secondary, .pri Primary, .danger the danger fill */
      '.ai365-ag-btn{height:32px;padding:0 12px;display:inline-flex;align-items:center;justify-content:center;gap:6px;border:1px solid ' + ST1 + ';border-radius:' + R_BTN + ';background:' + BG1 + ';font:' + B1S + ';color:' + FG1 + ';white-space:nowrap;transition:background .12s,border-color .12s,color .12s;}',
      '.ai365-ag-btn:hover:not(:disabled){background:' + BG1_H + ';border-color:' + ST1_H + ';}',
      '.ai365-ag-btn:active:not(:disabled){background:' + BG1_P + ';border-color:' + ST1_P + ';}',
      '.ai365-ag-btn.pri{min-width:96px;background:' + BRAND + ';border-color:transparent;color:' + FG_ON + ';}',
      '.ai365-ag-btn.pri:hover:not(:disabled){background:' + BRAND_H + ';border-color:transparent;}',
      '.ai365-ag-btn.pri:active:not(:disabled){background:' + BRAND_P + ';border-color:transparent;}',
      '.ai365-ag-btn.danger{min-width:96px;background:' + BAD_FILL + ';border-color:transparent;color:' + FG_ON + ';}',
      '.ai365-ag-btn.danger:hover:not(:disabled){background:' + BAD + ';border-color:transparent;}',
      '.ai365-ag-btn.danger:active:not(:disabled){background:' + BAD_SHADE + ';border-color:transparent;}',
      '.ai365-ag-btn:disabled{cursor:default;background:' + BG_DIS + ';border-color:' + ST_DIS + ';color:' + FG_DIS + ';}',
      '.ai365-ag-btn.pri:disabled,.ai365-ag-btn.danger:disabled{background:' + BG_DIS + ';border-color:transparent;color:' + FG_DIS + ';}',
      // 스피너 = 브랜드 머리 + Brand stroke 2 트랙 / the spinner = a brand head on a Brand stroke 2 track
      '.ai365-ag-spin{flex:none;width:14px;height:14px;border:2px solid ' + BSTROKE2 + ';border-top-color:' + CB + ';border-radius:50%;animation:ai365AgSpin .8s linear infinite;}',
      '.ai365-ag-spin.sm{width:12px;height:12px;}',
      '.ai365-ag-btn.pri .ai365-ag-spin{border-color:rgba(255,255,255,.45);border-top-color:' + FG_ON + ';}',
      '.ai365-ag-btn.pri:disabled .ai365-ag-spin{border-color:' + BSTROKE2 + ';border-top-color:' + CB + ';}',
      '.ai365-ag-status{display:flex;align-items:center;gap:8px;padding:6px 2px;font:' + B1 + ';color:' + FG2 + ';}',
      '.ai365-ag-status .stp{color:' + FG3 + ';font:' + CAP1 + ';}',
      '.ai365-ag-status.waiting .ai365-ag-spin{border-color:' + WARN_BD + ';border-top-color:' + WARN_FILL + ';}',
      '.ai365-ag-status.waiting{color:' + WARN_FG + ';}',
      // 요약 칩 = DS Tag Filled S(24 · r8) / the summary chip = a DS Tag Filled S
      '.ai365-ag-sum{align-self:flex-start;display:inline-flex;align-items:center;gap:6px;max-width:100%;min-height:24px;margin:2px 0 6px;font:' + CAP1 + ';color:' + FG3 + ';background:' + BG3 + ';border-radius:' + R_TAG + ';padding:4px 8px;}',
      '.ai365-ag-sum svg{color:' + OK + ';}',
      '.ai365-ag-sum .sep{color:' + FG4 + ';}',
      // 오류 줄 = DS 메시지 바(오류: Danger background 1 · 1px Danger border 1 · r8, 아이콘 Danger foreground 1) / the error line = a DS message bar (error)
      '.ai365-ag-err{display:flex;align-items:flex-start;gap:8px;color:' + FG1 + ';background:' + BAD_BG + ';border:1px solid ' + BAD_BD + ';border-radius:' + R_MB + ';padding:8px 12px;font:' + B1 + ';}',
      '.ai365-ag-err svg{margin-top:2px;color:' + BAD + ';flex:none;}',
      '.ai365-ag-mark{display:flex;align-items:center;gap:10px;margin:4px 0;font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-ag-mark .ln{flex:1;height:1px;background:' + ST2 + ';}',
      '.ai365-ag-mark.error{color:' + BAD + ';}',
      /* 입력줄 = 제품 시트 입력 카드(r24 · 1px Stroke 2 · Shadow 12 · 안쪽 16, 글자 Body 2, placeholder Foreground 4) / the composer = the product-sheet input card */
      '.ai365-ag-foot{padding:6px 24px 16px;}',
      '.ai365-ag-foot-in{max-width:820px;margin:0 auto;}',
      '.ai365-ag-queue{display:flex;flex-direction:column;gap:4px;margin:0 6px 8px;}',
      '.ai365-ag-qi{display:flex;align-items:center;gap:8px;font:' + B1 + ';color:' + FG2 + ';background:' + BG3 + ';border:1px dashed ' + ST1 + ';border-radius:' + R8 + ';padding:6px 12px;}',
      '.ai365-ag-qi .b{flex:none;display:inline-flex;align-items:center;height:20px;font:' + CAP2S + ';color:' + FGB2 + ';background:' + BRAND2 + ';box-shadow:inset 0 0 0 1px ' + BSTROKE2 + ';border-radius:' + R_BADGE + ';padding:0 6px;}',
      '.ai365-ag-qi .t{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-ag-comp{border:1px solid ' + ST2 + ';border-radius:' + R_COMP + ';background:' + BG1 + ';box-shadow:' + SH12 + ';padding:16px;transition:border-color .12s;}',
      '.ai365-ag-comp:focus-within{border-color:' + ST1 + ';}',
      '#ai365AgInput{display:block;width:100%;min-height:32px;max-height:200px;border:0;outline:0;resize:none;background:transparent;font:' + B2 + ';color:' + FG1 + ';padding:2px 2px 6px;overflow-y:auto;}',
      '#ai365AgInput::placeholder{color:' + FG4 + ';}',
      '.ai365-ag-crow{display:flex;align-items:center;gap:8px;padding-top:4px;}',
      '.ai365-ag-crow .sp{flex:1;}',
      // 권한 모드 · 모델 = 제품 시트 모델 알약(40 · 알약 · 1px Stroke 1 · Subtitle 2 + 셰브런 Foreground 3) / permission mode and model = the product-sheet model pill (40, pill, a 1px Stroke 1, Subtitle 2, a Foreground 3 chevron)
      '.ai365-ag-sel{appearance:none;-webkit-appearance:none;field-sizing:content;height:40px;max-width:240px;border:1px solid ' + ST1 + ';border-radius:' + R_FULL + ';padding:0 32px 0 16px;font:' + SUB2 + ';color:' + FG1 + ';background-color:' + BG1 + ';background-image:' + CHEV + ';background-repeat:no-repeat;background-position:right 14px center;cursor:pointer;transition:background-color .12s,border-color .12s;}',
      '.ai365-ag-sel:hover{background-color:' + BG1_H + ';border-color:' + ST1_H + ';}',
      '.ai365-ag-sel:active{background-color:' + BG1_P + ';border-color:' + ST1_P + ';}',
      '.ai365-ag-sel:focus{outline:0;}',
      '.ai365-ag-sel:focus-visible{box-shadow:' + RING + ';}',
      '.ai365-ag-sel:disabled{cursor:default;background-color:' + BG_DIS + ';border-color:' + ST_DIS + ';color:' + FG_DIS + ';}',
      // 보내기 · 멈춤 = 제품 시트 보내기(40 원 · 브랜드) / send and stop = the product-sheet send (a 40px brand circle)
      '.ai365-ag-send,.ai365-ag-stopb{flex:none;width:40px;height:40px;margin-left:4px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:' + FG_ON + ';background:' + BRAND + ';transition:background .12s;}',
      '.ai365-ag-send:hover:not(:disabled),.ai365-ag-stopb:hover:not(:disabled){background:' + BRAND_H + ';}',
      '.ai365-ag-send:active:not(:disabled),.ai365-ag-stopb:active:not(:disabled){background:' + BRAND_P + ';}',
      '.ai365-ag-send:disabled{background:' + BG_DIS + ';color:' + FG_DIS + ';cursor:default;}',
      '.ai365-ag-stopb:disabled{background:' + BG_DIS + ';color:' + FG_DIS + ';cursor:default;}',
      /* 빈 화면 · 오류 / empty and error states */
      '.ai365-ag-empty{margin:72px auto 0;max-width:460px;text-align:center;display:flex;flex-direction:column;align-items:center;gap:10px;}',
      '.ai365-ag-empty .ic{width:48px;height:48px;border-radius:' + R12 + ';background:' + BRAND2 + ';color:' + CB + ';display:flex;align-items:center;justify-content:center;margin-bottom:6px;}',
      '.ai365-ag-empty h2{font:' + SUB1 + ';color:' + FG1 + ';}',
      '.ai365-ag-empty p{font:' + B1 + ';color:' + FG3 + ';}',
      '.ai365-ag-empty .ai365-ag-btn{margin-top:8px;}',
      '.ai365-ag-empty.bad h2{color:' + BAD + ';}',
      /* 파일 보기 / file viewer */
      '.ai365-ag-viewer{flex:1;min-height:0;display:flex;flex-direction:column;}',
      '.ai365-ag-vh{display:flex;align-items:center;gap:8px;padding:8px 10px 8px 8px;border-bottom:1px solid ' + ST2 + ';font:' + B1 + ';min-width:0;}',
      '.ai365-ag-vh > svg{color:' + FG3 + ';}',
      '.ai365-ag-vh b{font-weight:600;color:' + FG1 + ';white-space:nowrap;}',
      '.ai365-ag-vh .p{flex:1;min-width:0;font:' + CAP1 + ';color:' + FG3 + ';overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-ag-vh .sz{font:' + CAP1 + ';color:' + FG3 + ';white-space:nowrap;}',
      '.ai365-ag-x{width:32px;height:32px;border-radius:' + R_BTN + ';display:flex;align-items:center;justify-content:center;color:' + FG2 + ';flex:none;}',
      '.ai365-ag-x:hover{background:' + SUB_H + ';color:' + FG2_BH + ';}',
      '.ai365-ag-x:active{background:' + SUB_P + ';color:' + FG2_BP + ';}',
      '.ai365-ag-vb{flex:1;min-height:0;overflow:auto;}',
      '.ai365-ag-vnote{padding:12px 16px;font:' + B1 + ';color:' + FG3 + ';}',
      '.ai365-ag-vnote.bad{color:' + BAD + ';}',
      '.ai365-ag-code{display:inline-block;min-width:100%;padding:10px 0 24px;font-family:' + MONO + ';font-size:12px;line-height:1.65;color:' + FG1 + ';}',
      '.ai365-ag-code .r{display:flex;white-space:pre;}',
      '.ai365-ag-code .r i{flex:none;width:52px;padding-right:14px;text-align:right;font-style:normal;color:' + FG4 + ';user-select:none;}',
      '.ai365-ag-code .r span{padding-right:18px;}',
      /* 환경 패널(바탕 Background 3, 줄 hover = 더 밝은 Background 2(DS Nav 서랍 방식), 선택 = Subtle selected, 개수 = DS Badge 브랜드 틴트) /
         environment panel (Background 3; row hover = the lighter Background 2, as in the DS Nav drawer; selected = Subtle selected; counts = brand tint badges) */
      '.ai365-ag-env{min-height:0;overflow-y:auto;border-left:1px solid ' + ST2 + ';background:' + BG3 + ';}',
      '.ai365-ag-sec{border-bottom:1px solid ' + ST2 + ';}',
      '.ai365-ag-sec.flash{animation:ai365AgFlash 1s ease;}',
      '.ai365-ag-sech{width:100%;display:flex;align-items:center;gap:8px;padding:12px 12px 10px 16px;font:' + B1S + ';color:' + FG1 + ';text-align:left;transition:background .12s;}',
      '.ai365-ag-sech:hover{background:' + BG2 + ';}',
      '.ai365-ag-sech:active{background:' + BG3_P + ';}',
      '.ai365-ag-sech .cnt{display:inline-flex;align-items:center;height:20px;font:' + CAP2S + ';color:' + FGB2 + ';background:' + BRAND2 + ';box-shadow:inset 0 0 0 1px ' + BSTROKE2 + ';border-radius:' + R_BADGE + ';padding:0 6px;}',
      '.ai365-ag-sech .cv{margin-left:auto;display:flex;color:' + FG3 + ';transition:transform .15s;}',
      '.ai365-ag-sec.shut .ai365-ag-sech .cv{transform:rotate(-90deg);}',
      '.ai365-ag-sec.shut .ai365-ag-secb{display:none;}',
      '.ai365-ag-secb{padding:0 12px 12px 16px;font:' + CAP1 + ';color:' + FG2 + ';}',
      '.ai365-ag-kv{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:8px 16px;margin:0;}',
      '.ai365-ag-kv dt{color:' + FG3 + ';font-weight:400;}',
      '.ai365-ag-kv dd{margin:0;min-width:0;color:' + FG1 + ';overflow-wrap:anywhere;}',
      '.ai365-ag-kv dd .ln{display:block;}',
      '.ai365-ag-kv .mu,.ai365-ag-mu{color:' + FG3 + ';}',
      '.ai365-ag-kv .br{display:inline-flex;align-items:center;gap:4px;font-weight:600;}',
      '.ai365-ag-kv .br svg{color:' + FG3 + ';}',
      '.ai365-ag-ctx{display:flex;align-items:center;gap:10px;}',
      '.ai365-ag-ctx .bar{flex:1;height:6px;border-radius:' + R_FULL + ';background:' + BG5 + ';overflow:hidden;}',
      '.ai365-ag-ctx .bar i{display:block;height:100%;border-radius:' + R_FULL + ';background:' + CB + ';transition:width .3s;}',
      '.ai365-ag-ctx.mid .bar i{background:' + WARN_FILL + ';}',
      '.ai365-ag-ctx.hi .bar i{background:' + BAD_FILL + ';}',
      '.ai365-ag-ctx .v{min-width:36px;text-align:right;font:' + CAP1S + ';color:' + FG1 + ';font-variant-numeric:tabular-nums;}',
      '.ai365-ag-mu{margin-top:6px;font:' + CAP1 + ';}',
      '.ai365-ag-none{padding:2px 0;font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-ag-ftree{max-height:340px;overflow:auto;margin:0 -6px;padding:0 6px;}',
      '.ai365-ag-froot{display:flex;align-items:center;gap:6px;padding:2px 2px 6px;font:' + CAP1 + ';color:' + FG1 + ';min-width:0;}',
      '.ai365-ag-froot svg{color:' + FG3 + ';flex:none;}',
      '.ai365-ag-froot b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      // 파일 나무 줄 = DS Nav 항목 S 모양(24 · r4) / file-tree rows shaped like DS Nav items S (24, r4)
      '.ai365-ag-fnode{width:100%;height:24px;display:flex;align-items:center;gap:4px;padding-right:6px;border-radius:' + R_NAV + ';font:' + CAP1 + ';color:' + FG2 + ';text-align:left;white-space:nowrap;transition:background .1s;}',
      '.ai365-ag-fnode:hover{background:' + BG2 + ';color:' + FG2_H + ';}',
      '.ai365-ag-fnode:active{background:' + BG3_P + ';}',
      '.ai365-ag-fnode.on{background:' + SUB_S + ';color:' + FG1 + ';font-weight:600;}',
      '.ai365-ag-fnode .cv{flex:none;width:13px;display:flex;color:' + FG3 + ';transition:transform .12s;}',
      '.ai365-ag-fnode.open .cv{transform:rotate(90deg);}',
      '.ai365-ag-fnode > svg{flex:none;color:' + FG3 + ';}',
      '.ai365-ag-fnode .nm{min-width:0;overflow:hidden;text-overflow:ellipsis;}',
      '.ai365-ag-fnode .sz{margin-left:auto;padding-left:8px;font:' + CAP2 + ';color:' + FG4 + ';}',
      '.ai365-ag-fnote{height:24px;display:flex;align-items:center;font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-ag-fnote.bad{color:' + BAD + ';}',
      '.ai365-ag-tlist{display:flex;flex-direction:column;gap:6px;max-height:300px;overflow:auto;}',
      '.ai365-ag-titem{flex:none;border:1px solid ' + ST2 + ';border-radius:' + R8 + ';background:' + BG1 + ';overflow:hidden;}',
      '.ai365-ag-tih{width:100%;display:flex;align-items:center;gap:6px;padding:6px 8px;font:' + CAP1 + ';text-align:left;}',
      '.ai365-ag-tih:hover{background:' + BG1_H + ';}',
      '.ai365-ag-tih .cmd{flex:1;min-width:0;font-family:' + MONO + ';color:' + FG1 + ';overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-ag-titem .ai365-ag-out{border:0;border-top:1px solid ' + ST2 + ';border-radius:0;max-height:220px;font-size:12px;}',
      '.ai365-ag-task{display:flex;align-items:center;gap:8px;padding:4px 0;font:' + CAP1 + ';}',
      '.ai365-ag-task .lb{flex:1;min-width:0;color:' + FG1 + ';overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-ag-task .du{font:' + CAP1 + ';color:' + FG3 + ';}',
      /* 대화 상자 = DS Dialog(600 · r16 · 안쪽 24 · Shadow 64, 제목 Subtitle 1, 제목 → 본문 16, 본문 → 버튼 20, CTA 36 알약), 입력칸 = DS Outline 입력 /
         dialogs = DS Dialog (600, r16, 24 padding, Shadow 64; Subtitle 1 title; 16 title-to-body, 20 body-to-buttons; 36px pill CTAs); fields = DS Outline inputs */
      '.ai365-ag-ov{position:fixed;inset:0;z-index:150;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;padding:20px;}',
      '.ai365-ag-dlg{width:600px;max-width:100%;max-height:calc(100vh - 40px);overflow:auto;background:' + BG1 + ';border-radius:' + R_DLG + ';box-shadow:' + SH64 + ';padding:24px;display:flex;flex-direction:column;gap:16px;color:' + FG1 + ';}',
      '.ai365-ag-dlg h3{font:' + SUB1 + ';}',
      '.ai365-ag-dlg .ds{margin-top:0;font:' + B1 + ';color:' + FG1 + ';}',
      // 필드 = DS Field(라벨 Body 1 · Foreground 1, 라벨 → 칸 2px, 칸 → 안내 4px) / fields = DS Field (Body 1 Foreground 1 labels, 2px label-to-control, 4px control-to-message)
      '.ai365-ag-fld{display:flex;flex-direction:column;gap:2px;min-width:0;font:' + B1 + ';color:' + FG1 + ';}',
      '.ai365-ag-fld > .ai365-ag-fsub{margin-top:2px;}',
      '.ai365-ag-in{width:100%;height:32px;' + 'border:1px solid ' + ST1 + ';border-bottom-color:' + ACC + ';border-radius:' + R_IN + ';padding:0 10px;font:' + B1 + ';color:' + FG1 + ';background-color:' + BG1 + ';outline:0;transition:border-color .12s,box-shadow .12s;}',
      '.ai365-ag-in::placeholder{color:' + FG4 + ';}',
      '.ai365-ag-in:hover{border-color:' + ST1_H + ';border-bottom-color:' + ACC_H + ';}',
      '.ai365-ag-in:focus{border-bottom-color:' + CB + ';box-shadow:inset 0 -1px 0 ' + CB + ';}',
      '.ai365-ag-in[readonly]{background-color:transparent;}',
      '.ai365-ag-in:disabled{background-color:transparent;border-color:' + ST_DIS + ';color:' + FG_DIS + ';cursor:not-allowed;}',
      'select.ai365-ag-in{appearance:none;-webkit-appearance:none;padding-right:32px;background-image:' + CHEV + ';background-repeat:no-repeat;background-position:right 12px center;cursor:pointer;}',
      '.ai365-ag-row2{display:grid;grid-template-columns:1fr 1fr;gap:12px;}',
      '.ai365-ag-chips{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-top:-8px;}',
      '.ai365-ag-chips .lb{margin-right:2px;font:' + CAP1 + ';color:' + FG3 + ';}',
      // 추천 폴더 칩 = DS Interaction tag Brand S(24 · r8) / suggestion chips = DS Interaction tags Brand S (24, r8)
      '.ai365-ag-chip{height:24px;display:inline-flex;align-items:center;gap:4px;max-width:220px;padding:0 8px;border:0;border-radius:' + R_TAG + ';background:' + BRAND2 + ';font:' + CAP1 + ';color:' + FGB2 + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
      '.ai365-ag-chip:hover{color:' + D('fg-brand-2-hover', '#2E2FAC') + ';background:' + BRAND2_H + ';}',
      '.ai365-ag-hint2{margin-top:-12px;font:' + CAP1 + ';color:' + FG3 + ';}',
      // 대화 상자 오류 = DS 메시지 바(오류, 아이콘 포함) / dialog errors = a DS message bar (error, with its icon)
      '.ai365-ag-derr{font:' + CAP1 + ';color:' + FG1 + ';background:' + BAD_BG + ' ' + ERR_IC + ' no-repeat 12px 10px/16px;border:1px solid ' + BAD_BD + ';border-radius:' + R_MB + ';padding:10px 12px 10px 36px;}',
      '.ai365-ag-dlg .acts{display:flex;justify-content:flex-end;gap:8px;margin-top:4px;}',
      '.ai365-ag-dlg .acts .ai365-ag-btn{height:36px;border-radius:' + R_FULL + ';padding:0 16px;font:' + SUB2 + ';}',
      '.ai365-ag-dname{font:' + B1S + ';background:' + BG3 + ';border-radius:' + R8 + ';padding:8px 12px;word-break:break-all;}',
      /* ── 2차 · 3차 / phases 2 and 3 ── */
      '@keyframes ai365AgRing{0%{box-shadow:0 0 0 3px ' + B110 + ';}100%{box-shadow:0 0 0 0 transparent;}}',
      '.ai365-ag-ring{animation:ai365AgRing 1.4s ease;}',
      '.dot.unseen{background:transparent !important;border:2px solid ' + CB + ';}',
      '.ai365-ag-sess > .dot.unseen{width:8px;height:8px;}',
      '.ai365-ag-sess .av .dot.unseen{background:' + BG1 + ' !important;border-color:' + CB + ';}',
      /* 슬래시 팝업 = DS Menu(r12 · 안쪽 4 · Shadow 16, 항목 32 · r6, 고른 항목 = Subtle selected) / slash popup = a DS Menu */
      '.ai365-ag-comp{position:relative;}',
      '.ai365-ag-slash{position:absolute;left:0;right:0;bottom:calc(100% + 8px);z-index:40;max-height:300px;overflow-y:auto;background:' + BG1 + ';border:0;border-radius:' + R_MENU + ';box-shadow:' + SH16 + ';padding:4px;}',
      '.ai365-ag-scmd{display:flex;align-items:center;gap:8px;min-width:0;min-height:32px;padding:6px;border-radius:' + R_ITEM + ';font:' + B1 + ';color:' + FG2 + ';cursor:pointer;}',
      '.ai365-ag-scmd:hover{background:' + SUB_H + ';color:' + FG2_H + ';}',
      '.ai365-ag-scmd.on{background:' + SUB_S + ';color:' + FG1 + ';}',
      '.ai365-ag-scmd .nm{flex:none;font-family:' + MONO + ';font-size:13px;font-weight:600;color:' + FG1 + ';}',
      '.ai365-ag-scmd.on .nm{color:' + FG_BRAND + ';}',
      '.ai365-ag-scmd .ar{flex:none;font-family:' + MONO + ';font-size:12px;color:' + FG3 + ';}',
      '.ai365-ag-scmd .ds{flex:1;min-width:0;font:' + CAP1 + ';color:' + FG3 + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
      // 범위 배지 = DS Badge M 20 · r4 틴트(기본 = informative, 폴더 = success, 전역 = brand, 스킬 = warning) / scope badges = DS Badges M 20, r4, tint
      '.ai365-ag-sb{flex:none;display:inline-flex;align-items:center;height:20px;font:' + CAP2S + ';border-radius:' + R_BADGE + ';padding:0 6px;background:' + BG4 + ';color:' + FG3 + ';box-shadow:inset 0 0 0 1px ' + ST2 + ';}',
      '.ai365-ag-sb.folder{background:' + OK_BG + ';color:' + OK + ';box-shadow:inset 0 0 0 1px ' + OK_BD + ';}',
      '.ai365-ag-sb.global{background:' + BRAND2 + ';color:' + FGB2 + ';box-shadow:inset 0 0 0 1px ' + BSTROKE2 + ';}',
      '.ai365-ag-sb.skill{background:' + WARN_BG + ';color:' + WARN_FG + ';box-shadow:inset 0 0 0 1px ' + WARN_BD + ';}',
      '.ai365-ag-snote{padding:8px;font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-ag-sel.plan{color:' + FG_BRAND + ';}',
      /* 사용자 말풍선: 스티어링 태그 · 명령 · ⟲ 되돌리기 / user bubbles: steer tag, commands, restore */
      '.ai365-ag-msg.user,.ai365-ag-msg.pend{position:relative;}',
      '.ai365-ag-msg .tg{display:block;width:max-content;margin:0 0 4px;font:' + CAP2S + ';color:' + FGB2 + ';background:' + BRAND2 + ';box-shadow:inset 0 0 0 1px ' + BSTROKE2 + ';border-radius:' + R_BADGE + ';padding:3px 6px;}',
      '.ai365-ag-msg.user.steer,.ai365-ag-msg.pend.steer{background:' + B170 + ';border:1px dashed ' + B110 + ';}',
      '.ai365-ag-msg.user .cn{font-family:' + MONO + ';font-weight:600;color:' + FG_BRAND + ';}',
      '.ai365-ag-msg.user.dropped{opacity:.62;background:' + BG3 + ';border:1px dashed ' + ST1 + ';}',
      '.ai365-ag-msg.user.dropped .tg{color:' + FG3 + ';background:' + BG4 + ';box-shadow:inset 0 0 0 1px ' + ST2 + ';}',
      '.ai365-ag-msg.user.has-cp::before{content:"";position:absolute;right:100%;top:0;bottom:0;width:46px;}',
      // ⟲ = DS Secondary 아이콘 버튼 M(32 · r8) / restore = a DS Secondary icon button M (32, r8)
      '.ai365-ag-rst{position:absolute;right:calc(100% + 8px);top:50%;transform:translateY(-50%);width:32px;height:32px;border-radius:' + R_BTN + ';display:flex;align-items:center;justify-content:center;color:' + FG2 + ';background:' + BG1 + ';border:1px solid ' + ST1 + ';opacity:0;transition:opacity .12s,color .12s,background .12s;}',
      '.ai365-ag-msg.user:hover .ai365-ag-rst,.ai365-ag-rst:focus-visible{opacity:1;}',
      '.ai365-ag-rst:hover{color:' + FG2_BH + ';background:' + BG1_H + ';border-color:' + ST1_H + ';}',
      '.ai365-ag.busy .ai365-ag-rst{display:none;}',
      /* 플랜 = 브랜드 옅은 카드(Brand 170 · 1px Brand stroke 2 · r8) · 명령 결과 카드(Background 2 · Stroke 2) / the plan = a light brand card; command results = a Background 2 card */
      '.ai365-ag-msg.agent.plan{border:1px solid ' + BSTROKE2 + ';background:' + B170 + ';border-radius:' + R_CARD + ';padding:12px 16px;}',
      '.ai365-ag-msg.agent.plan .ph{display:flex;align-items:center;gap:6px;margin-bottom:6px;font:' + B1S + ';color:' + FG_BRAND + ';}',
      '.ai365-ag-msg.agent.plan .pa{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px;padding-top:10px;border-top:1px solid ' + BRAND2 + ';}',
      '.ai365-ag-msg.agent.cmd{border:1px solid ' + ST2 + ';background:' + BG2 + ';border-radius:' + R_CARD + ';padding:10px 14px;font:' + B1 + ';}',
      /* 서브에이전트 카드(프로필 배지 = DS Badge 틴트: explorer = brand · worker = success · reviewer = warning) / subagent cards (profile badges = DS tint badges) */
      '.ai365-ag-tool.task > .ai365-ag-trow .ic{color:' + CB + ';}',
      '.ai365-ag-pr{flex:none;display:inline-flex;align-items:center;height:20px;font:' + CAP2S + ';border-radius:' + R_BADGE + ';padding:0 6px;background:' + BG4 + ';color:' + FG3 + ';box-shadow:inset 0 0 0 1px ' + ST2 + ';}',
      '.ai365-ag-pr.explorer{background:' + BRAND2 + ';color:' + FGB2 + ';box-shadow:inset 0 0 0 1px ' + BSTROKE2 + ';}',
      '.ai365-ag-pr.worker{background:' + OK_BG + ';color:' + OK + ';box-shadow:inset 0 0 0 1px ' + OK_BD + ';}',
      '.ai365-ag-pr.reviewer{background:' + WARN_BG + ';color:' + WARN_FG + ';box-shadow:inset 0 0 0 1px ' + WARN_BD + ';}',
      '.ai365-ag-tool .tn{flex:none;font:' + CAP1 + ';color:' + FG3 + ';white-space:nowrap;}',
      '.ai365-ag-tlb{font:' + CAP1S + ';color:' + FG3 + ';}',
      '.ai365-ag-tprompt{max-height:150px;}',
      '.ai365-ag-sub{display:flex;flex-direction:column;gap:6px;padding-left:10px;border-left:2px solid ' + ST2 + ';}',
      '.ai365-ag-sub > .ai365-ag-note{padding:2px 0;}',
      '.ai365-ag-stext{font:' + B1 + ';color:' + FG2 + ';word-break:break-word;}',
      '.ai365-ag-stext p{margin:2px 0;}',
      '.ai365-ag-tres{font:' + B1 + ';color:' + FG1 + ';background:' + BG1 + ';border:1px solid ' + ST2 + ';border-radius:' + R8 + ';padding:8px 12px;word-break:break-word;max-height:360px;overflow:auto;}',
      '.ai365-ag-tres.bad{color:' + BAD + ';}',
      /* 훅 줄 / hook lines */
      '.ai365-ag-hook{border:1px dashed ' + ST1 + ';border-radius:' + R8 + ';background:' + BG2 + ';}',
      '.ai365-ag-hook[data-decision="block"]{border-color:' + BAD_BD + ';background:' + BAD_BG + ';}',
      '.ai365-ag-hrow{width:100%;display:flex;align-items:center;gap:8px;min-height:32px;padding:4px 10px;font:' + CAP1 + ';color:' + FG2 + ';text-align:left;}',
      '.ai365-ag-hrow .ic{display:flex;color:' + FG3 + ';flex:none;}',
      '.ai365-ag-hrow .ev{flex:none;font-weight:600;color:' + FG2 + ';}',
      '.ai365-ag-hrow .cm{flex:1;min-width:0;font-family:' + MONO + ';font-size:12px;color:' + FG3 + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
      '.ai365-ag-hrow .du{flex:none;font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-ag-hrow .cv{flex:none;display:flex;color:' + FG3 + ';transition:transform .15s;}',
      '.ai365-ag-hook.open .ai365-ag-hrow .cv{transform:rotate(90deg);}',
      '.ex.block{color:' + BAD + ';background:' + BAD_BG + ';box-shadow:inset 0 0 0 1px ' + BAD_BD + ';}',
      '.ex.to{color:' + WARN_FG + ';background:' + WARN_BG + ';box-shadow:inset 0 0 0 1px ' + WARN_BD + ';}',
      '.ai365-ag-hbody{padding:0 10px 10px;display:flex;flex-direction:column;gap:6px;}',
      /* 압축 칩 = DS Interaction tag Filled S(24 · r8) / the compact chip = a DS Interaction tag Filled S */
      '.ai365-ag-compact{display:flex;flex-direction:column;align-items:center;gap:6px;margin:4px 0;}',
      '.ai365-ag-cphd{display:inline-flex;align-items:center;gap:6px;max-width:100%;min-height:24px;font:' + CAP1 + ';color:' + FG2 + ';background:' + BG3 + ';border:0;border-radius:' + R_TAG + ';padding:4px 8px;}',
      '.ai365-ag-cphd:hover{background:' + BG3_H + ';color:' + FG2_H + ';}',
      '.ai365-ag-cphd .ic{display:flex;color:' + CB + ';}',
      '.ai365-ag-cphd .sc{display:inline-flex;align-items:center;height:16px;font:' + CAP2S + ';color:' + FGB2 + ';background:' + BRAND2 + ';border-radius:' + R_BADGE + ';padding:0 4px;}',
      '.ai365-ag-cbody{align-self:stretch;font:' + B1 + ';color:' + FG2 + ';background:' + BG2 + ';border:1px solid ' + ST2 + ';border-radius:' + R8 + ';padding:10px 14px;word-break:break-word;}',
      '.ai365-ag-mark.checkpoint{color:' + FG_BRAND + ';}',
      '.ai365-ag-mark.checkpoint svg{flex:none;}',
      /* 완료 알림 줄 / completion-notice line */
      '.ai365-ag-notify{display:flex;align-items:center;gap:6px;padding:2px;font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-ag-notify svg{flex:none;color:' + OK + ';}',
      '.ai365-ag-notify.bad{color:' + BAD + ';}',
      '.ai365-ag-notify.bad svg{color:' + BAD + ';}',
      /* 환경 패널: Connectors · Changes · Outputs · 서브에이전트 행 / environment panel: connectors, changes, outputs, subagent rows */
      '.ai365-ag-clist{display:flex;flex-direction:column;gap:2px;}',
      '.ai365-ag-conn{display:flex;align-items:flex-start;gap:8px;padding:4px 2px;border-radius:' + R_NAV + ';font:' + CAP1 + ';color:' + FG2 + ';cursor:pointer;}',
      '.ai365-ag-conn:hover{background:' + BG2 + ';}',
      // 체크박스 = DS 체크박스 / checkboxes = the DS checkbox
      '.ai365-ag-conn input{' + CHK + 'margin:0;cursor:pointer;}',
      '.ai365-ag-conn input:hover{border-color:' + ACC_H + ';}',
      '.ai365-ag-conn input:checked{' + CHK_ON + '}',
      '.ai365-ag-conn input:disabled{border-color:' + ST_DIS + ';background-color:' + BG_DIS + ';}',
      '.ai365-ag-conn .tx{min-width:0;display:flex;flex-wrap:wrap;align-items:center;gap:4px 6px;}',
      '.ai365-ag-conn .nm{font-weight:600;color:' + FG1 + ';overflow-wrap:anywhere;}',
      '.ai365-ag-conn .sv{flex-basis:100%;font:' + CAP1 + ';color:' + FG3 + ';overflow-wrap:anywhere;}',
      // 종류 배지 = DS Badge S 16 · r4 틴트 / kind badges = DS Badges S 16, r4, tint
      '.ai365-ag-kd{flex:none;display:inline-flex;align-items:center;height:16px;font:' + CAP2S + ';border-radius:' + R_BADGE + ';padding:0 4px;background:' + BRAND2 + ';color:' + FGB2 + ';}',
      '.ai365-ag-kd.action{background:' + WARN_BG + ';color:' + WARN_FG + ';box-shadow:inset 0 0 0 1px ' + WARN_BD + ';}',
      '.ai365-ag-kd.gone{background:' + BG4 + ';color:' + FG3 + ';}',
      '.ai365-ag-conn.gone{cursor:default;opacity:.75;}',
      '.ai365-ag-conn.gone:hover{background:none;}',
      '.ai365-ag-conn.gone input{cursor:default;}',
      '.ai365-ag-chs{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-bottom:6px;font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-ag-chs .br{display:inline-flex;align-items:center;gap:4px;font-weight:600;color:' + FG2 + ';}',
      '.ai365-ag-chs .a,.ai365-ag-chf .a{color:' + OK + ';font-weight:700;}',
      '.ai365-ag-chs .d,.ai365-ag-chf .d{color:' + BAD + ';font-weight:700;}',
      '.ai365-ag-chl{max-height:260px;overflow:auto;margin:0 -6px;padding:0 6px;}',
      '.ai365-ag-chf{width:100%;height:24px;display:flex;align-items:center;gap:6px;padding:0 6px;border-radius:' + R_NAV + ';font:' + CAP1 + ';color:' + FG2 + ';text-align:left;white-space:nowrap;}',
      '.ai365-ag-chf:hover{background:' + BG2 + ';color:' + FG2_H + ';}',
      '.ai365-ag-chf.on{background:' + SUB_S + ';color:' + FG1 + ';font-weight:600;}',
      '.ai365-ag-chf .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;}',
      '.ai365-ag-chf .ds,.ai365-ag-chf .bn{flex:none;font:' + CAP1 + ';font-variant-numeric:tabular-nums;}',
      '.ai365-ag-chf .bn{color:' + FG3 + ';}',
      // git 상태 글자: 더함 · 새것 = 성공, 지움 = 위험, 이름 바꿈 = 브랜드, 고침 = 경고 / git letters: added and untracked = success, deleted = danger, renamed = brand, modified = warning
      '.ai365-ag-cs{flex:none;width:16px;text-align:center;font-family:' + MONO + ';font-size:12px;font-weight:700;color:' + FG3 + ';}',
      '.ai365-ag-cs.m{color:' + WARN_IC + ';}',
      '.ai365-ag-cs.a,.ai365-ag-cs.u{color:' + OK + ';}',
      '.ai365-ag-cs.d{color:' + BAD + ';}',
      '.ai365-ag-cs.r{color:' + FG_BRAND + ';}',
      '.ai365-ag-acts2{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;}',
      // 작은 버튼 = DS 버튼 S(24 · Caption 1) / small buttons = DS buttons S (24, Caption 1)
      '.ai365-ag-btn.sm{height:24px;padding:0 8px;font:' + CAP1 + ';gap:4px;}',
      '.ai365-ag-olist{display:flex;flex-direction:column;gap:2px;max-height:260px;overflow:auto;margin:0 -6px;padding:0 6px;}',
      '.ai365-ag-orow{display:flex;align-items:center;gap:2px;}',
      '.ai365-ag-ofile{flex:1;min-width:0;height:24px;display:flex;align-items:center;gap:6px;padding:0 6px;border-radius:' + R_NAV + ';font:' + CAP1 + ';color:' + FG2 + ';text-align:left;white-space:nowrap;}',
      '.ai365-ag-ofile:hover{background:' + BG2 + ';color:' + FG2_H + ';}',
      '.ai365-ag-ofile:disabled{color:' + FG_DIS + ';cursor:default;background:none;}',
      '.ai365-ag-ofile > svg{flex:none;color:' + FG3 + ';}',
      '.ai365-ag-ofile .nm{min-width:0;overflow:hidden;text-overflow:ellipsis;}',
      '.ai365-ag-ofile .sz,.ai365-ag-ofile .tm{flex:none;font:' + CAP2 + ';color:' + FG4 + ';}',
      '.ai365-ag-ofile .sz{margin-left:auto;}',
      '.ai365-ag-kb{flex:none;display:inline-flex;align-items:center;height:16px;font:' + CAP2S + ';border-radius:' + R_BADGE + ';padding:0 4px;background:' + OK_BG + ';color:' + OK + ';box-shadow:inset 0 0 0 1px ' + OK_BD + ';}',
      '.ai365-ag-kb.modified{background:' + WARN_BG + ';color:' + WARN_FG + ';box-shadow:inset 0 0 0 1px ' + WARN_BD + ';}',
      '.ai365-ag-kb.gone{background:' + BG4 + ';color:' + FG3 + ';box-shadow:inset 0 0 0 1px ' + ST2 + ';}',
      // 내려받기 = DS Subtle 아이콘 버튼 S(24 · r8, 패널 위 hover = Background 2) / download = a DS Subtle icon button S (24, r8; Background 2 hover on the panel)
      '.ai365-ag-dl{flex:none;width:24px;height:24px;display:flex;align-items:center;justify-content:center;border-radius:' + R_BTN + ';color:' + FG2 + ';}',
      '.ai365-ag-dl:hover{background:' + BG2 + ';color:' + FG2_BH + ';}',
      '.ai365-ag-dl:active{background:' + BG3_P + ';color:' + FG2_BP + ';}',
      'button.ai365-ag-task{width:100%;border-radius:' + R_NAV + ';text-align:left;padding:4px;color:' + FG2 + ';}',
      'button.ai365-ag-task:hover{background:' + BG2 + ';}',
      '.ai365-ag-task .ic{display:flex;color:' + CB + ';flex:none;}',
      /* 뷰어의 diff · 대화 상자 textarea / the viewer diff and the dialog textarea */
      '.ai365-ag-vb > .ai365-ag-diff{max-height:none;border:0;border-radius:0;}',
      '.ai365-ag-vh .ai365-ag-cs{width:auto;padding:0 6px;border-radius:' + R_BADGE + ';background:' + BG5 + ';}',
      // 여러 줄 입력 = DS Textarea(입력과 같은 토큰, 위 6 · 좌우 12) / the multi-line field = a DS Textarea (the input tokens; 6 top, 12 sides)
      'textarea.ai365-ag-in{height:auto;min-height:84px;padding:6px 12px;resize:vertical;}',
      '.ai365-ag-fldh{display:flex;align-items:center;justify-content:space-between;gap:8px;}',
      /* ── 폴더 고르기(2026-10-19): [찾아보기…] · 앱 안 탐색기 · 추가 폴더 대화 상자 · 규칙 범위 / folder picking: Browse, the in-app explorer, extra folders, rule scopes ── */
      '.ai365-ag-frow{display:flex;align-items:center;gap:8px;min-width:0;}',
      '.ai365-ag-frow .ai365-ag-in{flex:1;min-width:0;}',
      '.ai365-ag-frow > .ai365-ag-btn{flex:none;height:32px;}',
      '.ai365-ag-fsub{display:flex;align-items:flex-start;gap:10px;min-width:0;}',
      '.ai365-ag-fsub.mid{align-items:center;}',
      '.ai365-ag-pickhint{flex:1;min-width:0;font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-ag-pickhint.bad{color:' + WARN_FG + ';}',
      // 글자 링크 = DS 링크(Brand foreground link) / text links = the DS link colour
      '.ai365-ag-link{flex:none;margin-left:auto;padding:0;border:0;background:none;font:' + CAP1S + ';color:' + FG_LINK + ';}',
      '.ai365-ag-link:hover{text-decoration:underline;}',
      '.ai365-ag-link:disabled{color:' + FG_DIS + ';cursor:default;text-decoration:none;}',
      '.ai365-ag-ov.ai365-ag-ov2{z-index:151;background:rgba(0,0,0,.2);}',
      '.ai365-ag-bdlg{width:600px;}',   // 아래 새 세션 대화 상자(600px)를 가로로 덮는다 / covers the 600px dialog below it
      '.ai365-ag-bcrumbs{display:flex;flex-wrap:wrap;align-items:center;gap:2px;min-width:0;margin-top:-8px;font:' + CAP1 + ';}',
      // 경로 조각 = DS Subtle 버튼 S(24 · r8), 지금 위치 = Foreground 1 semibold / crumbs = DS Subtle buttons S; the current one in Foreground 1 semibold
      '.ai365-ag-bc{max-width:200px;height:24px;display:inline-flex;align-items:center;padding:0 8px;border-radius:' + R_BTN + ';color:' + FG2 + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
      '.ai365-ag-bc:hover{background:' + SUB_H + ';color:' + FG2_H + ';}',
      '.ai365-ag-bc.on{color:' + FG1 + ';font-weight:600;}',
      '.ai365-ag-bsep{display:flex;color:' + FG4 + ';}',
      '.ai365-ag-blist{height:300px;overflow-y:auto;border:1px solid ' + ST2 + ';border-radius:' + R8 + ';padding:4px;}',
      '.ai365-ag-bgrp{padding:6px 8px 2px;font:' + CAP1S + ';color:' + FG3 + ';}',
      '.ai365-ag-brow{width:100%;height:32px;display:flex;align-items:center;gap:8px;padding:0 8px;border-radius:' + R_ITEM + ';font:' + B1 + ';color:' + FG2 + ';text-align:left;}',
      '.ai365-ag-brow:hover{background:' + SUB_H + ';color:' + FG2_H + ';outline:0;}',
      '.ai365-ag-brow:active{background:' + SUB_P + ';}',
      '.ai365-ag-brow > svg{flex:none;color:' + FG3 + ';}',
      '.ai365-ag-brow .nm{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-ag-bnote{padding:12px 8px;font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-ag-bnote.bad{color:' + BAD + ';}',
      '.ai365-ag-bdlg .acts .sp{flex:1;}',
      '.ai365-ag-xlist{display:flex;flex-direction:column;gap:6px;max-height:240px;overflow-y:auto;}',
      '.ai365-ag-xrow{display:flex;align-items:center;gap:8px;min-width:0;}',
      '.ai365-ag-xrow code{flex:1;min-width:0;font-family:' + MONO + ';font-size:12px;color:' + FG2 + ';background:' + BG3 + ';border-radius:' + R8 + ';padding:8px 12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-ag-xnone{padding:2px 0;font:' + CAP1 + ';color:' + FG3 + ';}',
      '.ai365-ag-approval .ai365-ag-btn .sc{display:inline-block;max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;vertical-align:bottom;}',
      '.ai365-ag-approval .ai365-ag-btn .sc.code{font-family:' + MONO + ';font-size:12px;}',
      /* ── 내 컴퓨터 폴더(2026-10-20): 사이드바 태그 · 안내 줄(DS 메시지 바: 경고, 거부 = 오류) · 대화 상자 블록 · 연결 상태 · 빈 화면 버튼 둘 ──
         folders on my computer: the sidebar tag, the bar (a DS message bar: warning; denied = error), the dialog block, the state badge, two empty-state buttons */
      '.ai365-ag-sgh .tag{flex:none;display:inline-flex;align-items:center;height:16px;font:' + CAP2S + ';border-radius:' + R_BADGE + ';padding:0 4px;background:' + BRAND2 + ';color:' + FGB2 + ';}',
      '.ai365-ag-fsbar{flex:none;display:flex;align-items:center;gap:10px;box-sizing:border-box;width:calc(100% - 56px);max-width:764px;margin:12px auto 0;padding:6px 8px 6px 12px;min-height:36px;border:1px solid ' + WARN_BD + ';background:' + WARN_BG + ';border-radius:' + R_MB + ';font:' + CAP1 + ';color:' + FG1 + ';}',
      '.ai365-ag-fsbar .ic{display:flex;flex:none;color:' + WARN_IC + ';}',
      '.ai365-ag-fsbar .tx{flex:1;min-width:0;overflow-wrap:anywhere;}',
      '.ai365-ag-fsbar .ai365-ag-btn{flex:none;}',
      '.ai365-ag-fsbar[data-state="denied"]{border-color:' + BAD_BD + ';background:' + BAD_BG + ';color:' + FG1 + ';}',
      '.ai365-ag-fsbar[data-state="denied"] .ic{color:' + BAD + ';}',
      '.ai365-ag-fsnew{display:flex;flex-direction:column;align-items:flex-start;gap:6px;}',
      '.ai365-ag-fsnew .ai365-ag-hint2{margin-top:0;}',
      '.ai365-ag-or{display:flex;align-items:center;gap:10px;margin:2px 0 -2px;font:' + CAP1S + ';color:' + FG3 + ';}',
      '.ai365-ag-or::before,.ai365-ag-or::after{content:"";flex:1;height:1px;background:' + ST2 + ';}',
      '.ai365-ag-dlg .ai365-ag-or + .ds{margin-top:0;}',   // 구분선 아래 = 서버 폴더 설명 / below the divider it describes server folders
      '.ai365-ag-fsst{display:inline-flex;align-items:center;height:16px;margin-left:6px;font:' + CAP2S + ';border-radius:' + R_BADGE + ';padding:0 4px;vertical-align:1px;white-space:nowrap;}',
      '.ai365-ag-fsst.ok{background:' + OK_BG + ';color:' + OK + ';}',
      '.ai365-ag-fsst.no{background:' + BG4 + ';color:' + FG3 + ';}',
      '.ai365-ag-fsst.ask{background:' + WARN_BG + ';color:' + WARN_FG + ';}',
      '.ai365-ag-empty .acts{display:flex;flex-wrap:wrap;justify-content:center;gap:8px;margin-top:8px;}',
      '.ai365-ag-empty .acts .ai365-ag-btn{margin-top:0;}',
    ].join('\n');
    document.head.appendChild(s);
  })();

  /* ── 상태 / state ── */
  const S = {
    on: false, mountTok: 0, openTok: 0,
    settings: null, host: '', models: FALLBACK_MODELS.slice(), sessions: [], listLoading: false, listErr: '',
    cur: null, git: null, sessLoading: false, sessErr: '',
    events: [], lastSeq: 0, items: [], calls: {}, approvals: {}, lastStatus: null,
    open: {}, termOpen: {}, deciding: {},
    es: null, reTimer: null, reFails: 0, taskTimer: null, listTimer: null,
    tasks: [], tree: null, viewer: null,
    pend: '', queue: [], sending: false, stopping: false,
    hist: [], hpos: -1,
    env: true, shut: {}, search: '', menu: false, dlg: null,
    actor: undefined,   // 불러온 때의 acting_user_id / the acting_user_id at load time
    // 2차 트랜스크립트 모델(resetTranscript 가 비운다) / the phase-2 transcript model (cleared by resetTranscript)
    steer: [],                      // 끼워 넣기로 보냈고 아직 user 이벤트로 안 온 글 / steered texts not yet echoed as user events
    cps: {}, userIt: {},            // user seq → 체크포인트(create) · 말풍선 항목 / user seq → its checkpoint (create) and bubble item
    lastUserSeq: 0, lastPlanSeq: 0, planDone: {}, planIt: {},
    sub: {}, tids: [], taskCalls: [], bash: [],   // task_id → {items, tools} · 처음 본 순서 · task 카드 call id · bash call id / subagent children, first-seen order, task cards, bash calls
    fixed: {}, linkT: {}, linkC: {}, orph: {},    // 결과로 확정된 연결 · 지금 연결(tid→call, call→tid) · 부모 없는 tid / links fixed by a result, current links, parentless tids
    hookOpen: {}, compOpen: {},
    // 2차 패널 데이터 / phase-2 panel data
    conns: null, connBusy: false, cpBusy: false, changes: null, outputs: null, chSeq: 0, outSeq: 0,
    cmdCache: null, slash: null,
    seenTimer: null, seenFirst: 0, seenPosted: 0, tasksKick: null,
    cpLive: null, cpKick: null, cpSeq: 0,   // 서버에 살아 있는 체크포인트 id(null = 아직 모름) / checkpoint ids alive on the server (null = unknown yet)
    // 폴더 고르기(2026-10-19): 서버가 설정 응답에 folder_picker 를 알릴 때만 · 폴더 선택 창 대기 중 · 앱 안 탐색기(두 번째 오버레이)
    // Folder picking: only when the server's settings answer carries folder_picker; a folder window in progress; the in-app explorer (a second overlay)
    picker: false, picking: false, browse: null,
    // 내 컴퓨터 폴더(계약 F1): 기능 유무 · 세션 id → {handle, name, perm} · 선택 창 · 권한 창 진행 중 · request_id → 요청 · 지금 안내 줄 상태
    // ('' | 'nohandle' | 'prompt' | 'denied') · 답했거나 끝난 request_id · 핸들을 찾는 중인 세션 · 셸이 마운트된 뒤 만들 세션(+ 메뉴) ·
    // 첫 불러오기가 끝났는가 · 그 세션을 만드는 중
    // Folders on my computer (contract F1): support, session id → {handle, name, perm}, a picker or permission prompt in progress,
    // request_id → request, the bar state ('' | 'nohandle' | 'prompt' | 'denied'), answered or finished request ids, the session whose
    // handle is being looked up, the session to create once the shell is mounted (the + menu), whether the first load finished,
    // and that session being created
    fsOk: typeof window.showDirectoryPicker === 'function', fs: {}, fsBusy: false, fsReq: {}, fsBar: '', fsSeen: {}, fsChk: '',
    fsPend: null, ready: false, fsMaking: false, fsDb: null,
    // 보내지 못한 답(request_id → {q, body, tries, timer, busy}) · 서버가 내 컴퓨터 폴더를 명시적으로 껐나(browser_folders === false) ·
    // 원격 클라이언트인가(설정 응답 remote: 서버 폴더 UI 를 숨긴다, 2026-10-20 서버 결정)
    // Answers not delivered yet (request_id → {q, body, tries, timer, busy}), whether the server explicitly turned browser folders
    // off (browser_folders === false), and whether this is a remote client (settings remote: hide the server-folder UI; server decision 2026-10-20)
    fsOut: {}, bfOff: false, remote: false,
  };
  const R = {};   // 끼운 DOM 참조 / references to the inserted DOM

  // 2차 서버인가: 세션(light · 전체)이나 설정에 2차 키가 있으면(계약 2 A 절). 아니면 1차 화면 그대로(1차 서버 · 1차 테스트 스텁)
  // A phase-2 server: phase-2 keys on the session (light or full) or in the settings (contract 2, section A); otherwise the phase-1 screen
  function v2() {
    const c = S.cur, st = S.settings;
    if (c && ('notify' in c || 'seen_seq' in c || 'connectors' in c)) return true;
    return !!(st && ('notify_default' in st || 'hooks' in st || 'commands' in st));
  }
  function isBusy() { return !!(S.cur && BUSY[S.cur.status]); }
  // 내 컴퓨터 폴더 세션인가(세션 행의 kind, 계약 A) / a browser-folder session (the row's kind, contract A)
  function isBrowser(s) { s = s === undefined ? S.cur : s; return !!(s && s.kind === 'browser'); }
  // 내 컴퓨터 폴더를 열 수 있나: 브라우저가 지원하고 서버가 끄지 않았다 / can a folder on this computer be opened: the browser supports it and the server did not turn it off
  function fsAvail() { return S.fsOk && !S.bfOff; }
  const FS_NO = '이 브라우저 · 주소에서는 내 컴퓨터 폴더 열기를 쓸 수 없습니다(Edge · Chrome 의 https 또는 localhost 에서만)';
  const FS_OFF = '이 서버에서는 내 컴퓨터 폴더 세션을 쓸 수 없습니다';
  function idxSess(id) { for (let i = 0; i < S.sessions.length; i++) if (S.sessions[i].id === id) return i; return -1; }
  function sortSessions() { S.sessions.sort(function (a, b) { return String(b.updated || '').localeCompare(String(a.updated || '')); }); }
  function lastId() { try { return localStorage.getItem(LAST_KEY) || ''; } catch (e) { return ''; } }
  function saveLast(id) { try { if (id) localStorage.setItem(LAST_KEY, id); else localStorage.removeItem(LAST_KEY); } catch (e) { /* 저장소 없음 / no storage */ } }
  function resetTranscript() {
    S.events = []; S.lastSeq = 0; S.items = []; S.calls = {}; S.approvals = {}; S.lastStatus = null;
    S.open = {}; S.termOpen = {}; S.deciding = {}; S.pend = ''; S.queue = [];
    S.steer = []; S.cps = {}; S.userIt = {}; S.lastUserSeq = 0; S.lastPlanSeq = 0; S.planDone = {}; S.planIt = {};
    S.sub = {}; S.tids = []; S.taskCalls = []; S.bash = []; S.fixed = {}; S.linkT = {}; S.linkC = {}; S.orph = {};
    S.hookOpen = {}; S.compOpen = {}; S.cpLive = null;
  }

  /* ── 마운트 · 해제 / mount and unmount ── */
  function mount() {
    if (S.on) return;
    const work = document.getElementById('viewWork');
    const blank = work && work.querySelector('.ai365-ca-blank');
    const head = work && work.querySelector('.sub-header');
    const side = document.getElementById('sidebar') || document.querySelector('aside.sidebar');
    if (!blank || !head || !side) return;
    S.on = true;
    S.mountTok += 1;
    document.body.classList.add('ai365-ag-on');
    R.sidebar = side;
    R.side = document.createElement('div');
    R.side.className = 'ai365-ag-side';
    side.insertBefore(R.side, side.firstChild);
    R.side.addEventListener('click', onSideClick);
    R.side.addEventListener('input', onSideInput);
    R.head = head;
    R.hl = document.createElement('div'); R.hl.className = 'ai365-ag-hl';
    R.hr = document.createElement('div'); R.hr.className = 'ai365-ag-hr';
    head.insertBefore(R.hl, head.firstChild);
    head.appendChild(R.hr);
    R.hl.addEventListener('click', onHeadClick);
    R.hr.addEventListener('click', onHeadClick);
    R.blank = blank;
    blank.innerHTML = shellHtml();
    R.shell = blank.querySelector('.ai365-ag');
    R.scroll = R.shell.querySelector('.ai365-ag-scroll');
    R.tx = R.shell.querySelector('.ai365-ag-tx');
    R.viewer = R.shell.querySelector('.ai365-ag-viewer');
    R.foot = R.shell.querySelector('.ai365-ag-foot');
    R.queue = R.shell.querySelector('.ai365-ag-queue');
    R.input = R.shell.querySelector('#ai365AgInput');
    R.send = R.shell.querySelector('[data-ag="send"]');
    R.stop = R.shell.querySelector('[data-ag="stop"]');
    R.perm = R.shell.querySelector('[data-ag-perm]');
    R.model = R.shell.querySelector('[data-ag-model]');
    R.env = R.shell.querySelector('.ai365-ag-env');
    R.slash = R.shell.querySelector('.ai365-ag-slash');
    R.fsbar = R.shell.querySelector('.ai365-ag-fsbar');
    S.fsOk = typeof window.showDirectoryPicker === 'function';   // 늦게 실린 폴리필도 / a polyfill loaded late too
    S.ready = false; S.fsBar = ''; S.fsChk = '';
    R.shell.addEventListener('click', onShellClick);
    R.shell.addEventListener('change', onShellChange);
    R.shell.addEventListener('mousedown', onShellDown);
    R.input.addEventListener('keydown', onInputKey);
    R.input.addEventListener('input', onInputInput);
    R.input.addEventListener('blur', closeSlash);
    S.cur = null; S.git = null; S.sessErr = ''; S.viewer = null; S.tree = null; S.tasks = []; S.menu = false;
    S.changes = null; S.outputs = null; S.slash = null; S.seenPosted = 0;
    resetTranscript();
    renderAll();
    load();
  }

  function unmount() {
    if (!S.on) return;
    flushSeen();   // 본 데까지 알리고 나간다 / report what was seen before leaving
    S.on = false;
    S.mountTok += 1; S.openTok += 1;
    closeStream();
    stopTaskPoll();
    if (S.listTimer) { clearInterval(S.listTimer); S.listTimer = null; }
    clearTimeout(S.tasksKick); S.tasksKick = null;
    clearTimeout(S.cpKick); S.cpKick = null;
    S.slash = null;
    closeDialog();
    S.menu = false;
    const m = R.head && R.head.querySelector('.ai365-ag-menu');
    if (m) m.remove();
    if (R.side) R.side.remove();
    if (R.hl) R.hl.remove();
    if (R.hr) R.hr.remove();
    if (R.blank) R.blank.innerHTML = '';
    document.body.classList.remove('ai365-ag-on');
    Object.keys(R).forEach(function (k) { delete R[k]; });
    S.cur = null; S.git = null; S.viewer = null; S.tree = null; S.tasks = []; S.sending = false; S.stopping = false;
    S.changes = null; S.outputs = null; S.connBusy = false;
    // 아직 만들지 못한 + 메뉴 세션은 취소로 끝낸다. 대기 요청은 서버가 시간 초과로 정리한다(답하던 것은 끝까지 보낸다)
    // A + menu session not created yet ends as cancelled; waiting requests are left to the server's timeout (ones in flight still answer)
    S.ready = false; S.fsBar = ''; S.fsChk = ''; S.fsMaking = false;
    if (S.fsPend) { const p = S.fsPend; S.fsPend = null; p.resolve(null); }
    Object.keys(S.fsReq).forEach(function (k) { if (!S.fsReq[k].running) delete S.fsReq[k]; });
    resetTranscript();
  }

  function shellHtml() {
    return '<div class="ai365-ag' + (S.env ? '' : ' noenv') + '">'
      + '<section class="ai365-ag-main">'
      + '<div class="ai365-ag-fsbar" role="status" aria-live="polite" hidden></div>'   // 내 컴퓨터 폴더 안내 줄(계약 F4) / the browser-folder bar (contract F4)
      + '<div class="ai365-ag-scroll"><div class="ai365-ag-tx"></div></div>'
      + '<div class="ai365-ag-viewer" hidden></div>'
      + '<div class="ai365-ag-foot" hidden><div class="ai365-ag-foot-in">'
      + '<div class="ai365-ag-queue" hidden></div>'
      + '<div class="ai365-ag-comp">'
      + '<div class="ai365-ag-slash" id="ai365AgSlash" role="listbox" hidden></div>'
      // 슬래시 팝업과 묶인 콤보박스(적대 검토 L10) / a combobox tied to the slash popup (review L10)
      + '<textarea id="ai365AgInput" rows="1" role="combobox" aria-autocomplete="list" aria-haspopup="listbox" aria-controls="ai365AgSlash" aria-expanded="false" data-i18n-skip></textarea>'
      + '<div class="ai365-ag-crow">'
      + '<select class="ai365-ag-sel" data-ag-perm data-i18n-skip></select>'
      + '<span class="sp"></span>'
      + '<select class="ai365-ag-sel" data-ag-model data-i18n-skip></select>'
      + '<button type="button" class="ai365-ag-send" data-ag="send" disabled>' + IC.send + '</button>'
      + '<button type="button" class="ai365-ag-stopb" data-ag="stop" hidden>' + IC.stop + '</button>'
      + '</div></div></div></div>'
      + '</section>'
      + '<aside class="ai365-ag-env"></aside>'
      + '</div>';
  }

  /* ── 불러오기 / loading ── */
  function load() {
    if (!S.on) return;
    const tok = ++S.mountTok;   // 겹친 불러오기는 마지막 것만 / overlapping loads: only the latest applies
    const openAt = S.openTok;   // 불러오는 동안 사용자가 세션을 열었는지 / whether the user opens a session while this load runs
    S.actor = acting();
    S.listLoading = true; S.listErr = '';
    renderSideList(); paintTranscript();
    Promise.all([
      api(BASE + '/settings' + qs()).catch(function () { return null; }),
      api(BASE + '/models' + qs()).catch(function () { return null; }),
      api(BASE + '/sessions' + qs()),
    ]).then(function (res) {
      if (tok !== S.mountTok || !S.on) return;
      const st = res[0], md = res[1], ss = res[2];
      if (st) {
        S.settings = st.settings || {}; S.host = st.host || ''; S.picker = !!st.folder_picker;
        // browser_folders 는 명시적으로 false 일 때만 끈다(값이 없는 서버 · 스텁은 켠 채), remote 면 서버 폴더 UI 를 숨긴다
        // browser_folders turns the feature off only when explicitly false (servers and stubs without it keep it on); remote hides the server-folder UI
        S.bfOff = st.browser_folders === false; S.remote = !!st.remote;
        window.AI365_agenticOpenFolder.off = S.bfOff;   // 컴포저 + 항목도 숨긴다(adapter G) / hides the composer + item too (adapter G)
      }
      if (md && Array.isArray(md.models) && md.models.length) S.models = md.models;
      S.sessions = (ss && ss.sessions) || [];
      // 목록이 늦게 오는 동안 사용자가 세션을 열었으면(대화 상자로 막 만든 세션 등) 그것을 지킨다: 목록에 없으면 넣고 다시 열지 않는다
      // (느린 첫 응답 뒤 마지막 세션을 다시 열어 막 만든 세션을 버리던 경합, 2026-10-20 실서버 점검)
      // Keep a session the user opened while the list was slow (one just made in the dialog, say): add it when missing and do not
      // reopen another (a race where a slow first answer reopened the last session over the new one; real-server check, 2026-10-20)
      const mine = S.openTok !== openAt && S.cur ? S.cur : null;
      if (mine && idxSess(mine.id) < 0) S.sessions.push(Object.assign({}, mine));
      sortSessions();
      S.listLoading = false; S.ready = true;
      if (v2() || S.sessions.some(function (s) { return 'notify' in s || 'seen_seq' in s; })) loadConns();   // 2차 서버만 / phase-2 servers only
      // + 메뉴에서 고른 내 컴퓨터 폴더가 기다리면 마지막 세션 대신 그 세션을 만든다(계약 F2) / a folder picked from the + menu: create that session instead of reopening the last one
      if (fsRunPend()) { ensureListPoll(); return; }
      if (mine) { renderAll(); ensureListPoll(); return; }
      let id = lastId();
      if (idxSess(id) < 0) id = S.sessions[0] ? S.sessions[0].id : '';
      if (id) openSession(id); else renderAll();
      ensureListPoll();
    }).catch(function (err) {
      if (tok !== S.mountTok || !S.on) return;
      S.listLoading = false; S.ready = true; S.listErr = err.message || T('세션 목록을 불러오지 못했습니다');
      if (fsRunPend()) return;   // 목록만 실패했을 수 있다 → 만들기는 해 본다 / only the list may have failed, so creation is still tried
      renderAll();
    });
  }

  function refreshList() {
    if (!S.on) return;
    const tok = S.mountTok;
    api(BASE + '/sessions' + qs()).then(function (d) {
      if (tok !== S.mountTok || !S.on) return;
      const cur = S.cur;
      S.sessions = ((d && d.sessions) || []).map(function (s) { return (cur && s.id === cur.id) ? Object.assign({}, s, { status: cur.status }) : s; });
      sortSessions();
      renderSideList(); renderHead(); ensureListPoll();
    }).catch(noop);   // 다음 주기에 다시 / retried on the next round
  }
  // 다른 세션이 실행 중일 때만 목록을 주기적으로 다시 읽는다(지금 세션은 스트림이 알려 준다)
  // Re-read the list periodically only while another session runs (the open session is followed by its stream)
  function ensureListPoll() {
    const need = S.on && S.sessions.some(function (s) { return BUSY[s.status] && !(S.cur && s.id === S.cur.id); });
    if (need && !S.listTimer) S.listTimer = setInterval(refreshList, LIST_POLL_MS);
    else if (!need && S.listTimer) { clearInterval(S.listTimer); S.listTimer = null; }
  }

  function openSession(id, opts) {
    opts = opts || {};
    if (!S.on || !id) return;
    flushSeen();   // 떠나는 세션의 본 데까지 먼저 / report the leaving session first
    closeStream();
    stopTaskPoll();
    const tok = ++S.openTok;
    const brief = S.sessions[idxSess(id)];
    S.cur = Object.assign({ id: id, title: '', folder: '', status: 'idle', extra_folders: [] }, brief || {});
    S.git = null; S.sessErr = ''; S.sessLoading = true; S.viewer = null; S.tasks = []; S.menu = false;
    S.tree = null; S.changes = null; S.outputs = null; S.slash = null; S.seenPosted = 0;
    clearTimeout(S.tasksKick); S.tasksKick = null;
    clearTimeout(S.cpKick); S.cpKick = null;
    resetTranscript();
    // 내 컴퓨터 폴더: 안내 줄 · 다른 세션의 대기 요청은 새로(답하던 것은 끝까지 보낸다) / browser folders: a fresh bar; other sessions' waiting requests dropped (ones in flight still answer)
    S.fsBar = ''; S.fsChk = ''; S.fsSeen = {};
    Object.keys(S.fsReq).forEach(function (k) { if (!S.fsReq[k].running) delete S.fsReq[k]; });
    if (!opts.hist) pushHist(id);
    saveLast(id);
    renderAll();
    let row = null;
    api(sessUrl(id) + qs()).then(function (d) {
      if (tok !== S.openTok) return false;
      S.cur = Object.assign({}, S.cur, d.session || {});
      S.git = d.git || null;
      row = { status: S.cur.status, ctx: S.cur.context_pct, seq: typeof S.cur.last_seq === 'number' ? S.cur.last_seq : -1 };
      const i = idxSess(id);
      if (i >= 0) S.sessions[i] = Object.assign({}, S.sessions[i], d.session || {});
      return loadEvents(id, tok);
    }).then(function (ok) {
      if (ok === false || tok !== S.openTok) return;
      S.sessLoading = false;
      // 다시 읽은 이벤트가 세션 행보다 새것이 아니면 상태 · 컨텍스트는 행이 원본이다 / unless the replayed events are newer, the row owns status and context
      if (row && row.seq >= S.lastSeq) { S.cur.status = row.status; if (row.ctx !== undefined) S.cur.context_pct = row.ctx; }
      // 내 컴퓨터 폴더 세션의 파일 트리는 폴더 기준 상대 경로('' = 폴더 자체)로 핸들에서 읽는다(계약 F4)
      // A browser-folder session's tree uses folder-relative paths ('' = the folder itself) read from the handle (contract F4)
      const br = isBrowser();
      S.tree = br ? { root: '', nodes: {}, open: {}, browser: true } : { root: S.cur.folder, nodes: {}, open: {} };
      S.seenPosted = Number(S.cur.seen_seq) || 0;
      if (br) S.fsChk = id;   // 핸들을 찾는 동안 안내 줄을 띄우지 않는다 / no bar while the handle is looked up
      renderAll();
      scrollBottom();
      connect();
      loadTasks();
      if (br) { loadDir(''); fsAttach(); fsSync(); }   // 핸들 · 권한 → 대기 요청(새로고침 · 다른 탭 보완, 계약 F3) / handle and permission, then the waiting requests (contract F3)
      else if (S.cur.folder) loadDir(S.cur.folder);
      ensureTaskPoll();
      if (v2()) {   // 2차 패널 · 미확인 점 · 살아 있는 체크포인트 / phase-2 panels, the unseen dot and the live checkpoints
        if (!br) { loadChanges(); loadCheckpoints(); }   // 내 컴퓨터 폴더엔 git 이 없다 / no git for browser folders
        loadOutputs();
        if (!S.conns) loadConns();
        scheduleSeen();
      }
      const ae = document.activeElement;   // 다른 입력칸에 있지 않으면 입력줄로 / focus the composer unless another field has focus
      if (R.input && !R.input.disabled && (!ae || ae === document.body)) { try { R.input.focus(); } catch (e) { /* 무시 / ignore */ } }
    }).catch(function (err) {
      if (tok !== S.openTok) return;
      S.sessLoading = false; S.sessErr = err.message || T('세션을 불러오지 못했습니다');
      renderAll();
    });
  }

  // 이벤트를 처음부터 쪽 단위로 읽는다(limit 500) / read the events from the start, page by page (limit 500)
  function loadEvents(id, tok) {
    let pages = 0;
    function step() {
      return api(sessUrl(id, '/events') + qs({ after: S.lastSeq, limit: EVENT_PAGE })).then(function (d) {
        if (tok !== S.openTok) return false;
        const evs = (d && d.events) || [];
        evs.forEach(function (ev) { ingest(ev); });
        const last = (d && typeof d.last_seq === 'number') ? d.last_seq : S.lastSeq;
        if (evs.length >= EVENT_PAGE && S.lastSeq < last && ++pages < 40) return step();
        if (!evs.length && last > S.lastSeq) S.lastSeq = last;
        return true;
      });
    }
    return step();
  }

  /* ── 이벤트 → 모델 / events → model ── */
  function pushItem(it) { S.items.push(it); return it; }
  // 이벤트 하나를 모델에 넣고, 화면에 무엇을 고칠지 돌려준다(이미 본 seq 는 null) / fold one event in and report what to repaint (null for a seen seq)
  function ingest(ev) {
    if (!ev || typeof ev.seq !== 'number' || ev.seq <= S.lastSeq) return null;
    S.lastSeq = ev.seq;
    S.events.push(ev);
    const p = ev.payload || {}, r = {};
    const tid = p.task_id ? String(p.task_id) : '';
    switch (ev.kind) {
      case 'user': {
        // 끼워 넣은 글 → 대기열 글 → 보내는 중인 글 순으로 짝을 찾는다. 턴 끝에 남은 끼워 넣기 여러 개는 "\n\n" 으로 합쳐 새 턴이 되므로
        // 조각도 맞춰 본다(적대 검토 L11) / match steered texts, then queued ones, then the one being sent; leftover steers merged with
        // "\n\n" into a new turn are matched piece by piece too (review L11)
        const t = String(p.text || '').trim(), parts = pieces(t), cand = parts.length > 1 ? [t].concat(parts) : [t];
        let hitS = false, hitQ = false;
        cand.forEach(function (x) {
          const si = S.steer.indexOf(x), qi = S.queue.indexOf(x);
          if (si >= 0) { S.steer.splice(si, 1); hitS = true; }
          if (qi >= 0) { S.queue.splice(qi, 1); hitQ = true; }
        });
        if (hitS) r.pend = true;
        if (hitQ) r.queue = true;
        if (!hitS && !hitQ && S.pend && !p.steer && !p.dropped) { S.pend = ''; r.pend = true; }
        const it = pushItem({ k: 'user', ev: ev });
        if (p.dropped) { r.add = it; break; }   // 턴이 오류 · 예산으로 끝나 전달되지 않은 글(서버 변경 1) / a text never delivered because the turn ended in an error or budget stop
        S.userIt[ev.seq] = it;
        if (S.lastPlanSeq && S.lastPlanSeq > S.lastUserSeq) r.plan = S.lastPlanSeq;   // 뒤에 글이 왔으니 계획 버튼을 거둔다 / a later message retires the plan buttons
        S.lastUserSeq = ev.seq;
        r.add = it;
        break;
      }
      case 'assistant': {
        if (tid) { addChild(r, tid, { k: 'stext', ev: ev }); break; }   // 서브에이전트의 글 / a subagent's text
        const it = pushItem({ k: 'agent', ev: ev });
        if (p.plan) { if (S.lastPlanSeq && S.lastPlanSeq > S.lastUserSeq) r.plan = S.lastPlanSeq; S.lastPlanSeq = ev.seq; S.planIt[ev.seq] = it; }
        if (p.command && !isBusy()) r.changes = true;   // /commit · /checkpoint 같은 내장 명령은 턴 끝이 없다 / built-in commands such as /commit have no turn end
        r.add = it;
        break;
      }
      case 'tool_call': case 'tool_result': {
        const id = String(p.call_id || ('s' + ev.seq)), isCall = ev.kind === 'tool_call';
        // 서브에이전트 카드인가는 처음 본 때 정해 둔다(적대 검토 L5: 서브에이전트 안에서 거절된 task 호출은 그 카드의 자식)
        // Whether this is a subagent card is fixed when first seen (review L5: a task call refused inside a subagent is that card's child)
        const own = S.calls[id] ? !!S.calls[id].own : ownTask(p, tid, id);
        const child = own ? '' : tid;
        if (S.calls[id]) { if (isCall) S.calls[id].call = p; else S.calls[id].result = p; r.tool = id; }
        else {
          S.calls[id] = { call: isCall ? p : { call_id: id, tool: p.tool, label: p.tool, args: {} }, result: isCall ? null : p, task: child, own: own };
          if ((S.calls[id].call.tool || p.tool) === 'bash') S.bash.push(id);
          if (child) addChild(r, child, { k: 'tool', id: id });
          else { r.add = pushItem({ k: 'tool', id: id }); if (own) S.taskCalls.push(id); }
        }
        const c = S.calls[id];
        if (c.call.tool === 'bash' || p.tool === 'bash') r.term = true;
        if (c.task && S.linkT[c.task]) r.prow = S.linkT[c.task];
        if (own) {   // 호출 · 결과의 subagent.task_id(또는 task_id)가 오면 확정 연결 / subagent.task_id (or task_id) on the call or the result fixes the link
          const st = (p.subagent && p.subagent.task_id) ? String(p.subagent.task_id) : tid;
          if (st && S.fixed[id] !== st) { S.fixed[id] = st; r.relink = true; }
          if (!isCall) r.tasks = true;   // 서랍의 서브에이전트 행 / the drawer's subagent row
        }
        break;
      }
      case 'approval': {
        const aid = String(p.approval_id || ('s' + ev.seq)), had = S.approvals[aid];
        S.approvals[aid] = Object.assign({}, had || {}, p);   // 같은 approval_id 의 새 이벤트 = 결정 / a newer event with the same id = the decision
        if ((S.approvals[aid].decision || 'pending') !== 'pending') delete S.deciding[aid];
        if (had) r.appr = aid; else r.add = pushItem({ k: 'appr', id: aid });   // 서브에이전트의 승인도 본문에 / subagent approvals stay in the body
        if (p.call_id && S.calls[p.call_id]) {
          r.tool = String(p.call_id);
          const ct = S.calls[p.call_id].task;
          if (ct && S.linkT[ct]) r.prow = S.linkT[ct];
        }
        break;
      }
      case 'status': {
        const st = p.state || 'idle';
        S.lastStatus = p;
        if (S.cur) S.cur.status = st;
        if (st === 'stopped' || st === 'error') r.add = pushItem({ k: 'mark', ev: ev });
        if (!BUSY[st] && S.queue.length) { S.queue = []; r.queue = true; }
        if (!BUSY[st] && S.steer.length) { S.steer = []; r.pend = true; }   // 남은 끼워 넣기는 서버가 새 턴으로 잇는다 / leftover steers become the server's next turn
        r.status = st;
        break;
      }
      case 'summary': r.add = pushItem({ k: 'sum', ev: ev }); break;
      case 'context': if (S.cur && typeof p.pct === 'number') S.cur.context_pct = p.pct; r.ctx = true; break;
      case 'error': r.add = pushItem({ k: 'err', ev: ev }); break;
      case 'hook':
        if (tid) addChild(r, tid, { k: 'hook', ev: ev }); else r.add = pushItem({ k: 'hook', ev: ev });
        break;
      case 'compact':   // 서브에이전트 턴 안 압축은 그 카드 안에(적대 검토 L6) / a compaction inside a subagent's turn goes into its card (review L6)
        if (tid) addChild(r, tid, { k: 'compact', ev: ev }); else r.add = pushItem({ k: 'compact', ev: ev });
        break;
      case 'checkpoint':
        if (p.action === 'restore') { r.add = pushItem({ k: 'cpmark', ev: ev }); r.git = true; }   // 파일이 바뀌었다(/undo 포함) / the files changed (/undo too)
        else {
          if (p.id && S.cpLive) S.cpLive[String(p.id)] = true;   // 막 만든 것은 살아 있다(정리 여부는 아래 다시 읽기로) / a fresh one is alive; trimming shows on the re-read below
          if (p.seq !== undefined && p.seq !== null && p.id) { S.cps[p.seq] = p; r.user = p.seq; }   // ⟲ 는 그 user 말풍선에 / the restore button goes on that user bubble
          if (!isBusy()) r.changes = true;   // 턴 밖(명령 · 버튼)의 체크포인트 / a checkpoint outside a turn (command or button)
        }
        r.cps = true;   // 서버가 50개 넘는 것을 정리했을 수 있다 → GET …/checkpoints(적대 검토 M2) / the server may have trimmed past 50 → GET …/checkpoints (review M2)
        break;
      case 'notify': r.add = pushItem({ k: 'notify', ev: ev }); break;
      default: break;   // 모르는 종류는 건너뛴다 / unknown kinds are skipped
    }
    if (r.relink) r.relink = fixLinks();   // 바뀐 부모 카드 목록 / the parent cards whose children changed
    return r;
  }

  /* ── 서브에이전트 자식 ↔ task 카드 연결 / linking subagent children to task cards ──
     자식 이벤트에는 task_id 만 있고 부모 task 호출에는 없을 수 있다. 연결 순서: 결과의 subagent.task_id(확정) →
     /tasks 행의 label(= description) 일치 → 결과가 아직 없는 가장 이른 task 카드(잠정). 잠정 연결은 /tasks 를 읽을 때마다 다시 맞춘다.
     부모 카드를 못 찾으면 그 자식은 일반 카드로 본문에 그린다.
     Child events carry a task_id the parent task call may lack. Linking order: the result's subagent.task_id (fixed), then a /tasks
     row whose label (= description) matches, then the earliest task card still without a result (tentative). Tentative links are
     rematched on every /tasks read. A child without any parent card is drawn as an ordinary card in the body. */
  // 서브에이전트 카드가 될 task 호출인가: subagent.task_id 가 있거나 task_id 가 없거나(맨 위), task_id 가 아직 다른 카드에 묶이지 않았을 때.
  // 이미 다른 카드에 묶인 task_id 를 단 task 호출 = 그 서브에이전트 안에서 거절된 호출(깊이 1) → 일반 자식 카드(적대 검토 L5)
  // Is this task call a subagent card: it carries subagent.task_id, or no task_id (top level), or a task_id not bound to another card yet.
  // A task call whose task_id is already bound to another card was refused inside that subagent (depth one) → an ordinary child card (review L5)
  function ownTask(p, tid, id) {
    if (p.tool !== 'task') return false;
    if (p.subagent && p.subagent.task_id) return true;
    if (!tid) return true;
    const bound = S.linkT[tid];
    return !(bound && bound !== id);
  }
  // "\n\n" 으로 이어 붙인 글의 조각 / the pieces of a text joined with "\n\n"
  function pieces(t) { return String(t || '').split(/\n\s*\n/).map(function (x) { return x.trim(); }).filter(Boolean); }
  function descOf(cid) { const c = S.calls[cid]; return c ? String((c.call.args || {}).description || '') : ''; }
  function taskRow(tid) { for (let i = 0; i < S.tasks.length; i++) if (String(S.tasks[i].id) === tid) return S.tasks[i]; return null; }
  function freeCalls(taken) { return S.taskCalls.filter(function (c) { return !taken[c]; }); }
  function guessParent(tid) {
    const free = freeCalls(S.linkC), row = taskRow(tid);
    if (row && row.label) { const m = free.filter(function (c) { return descOf(c) === String(row.label); })[0]; if (m) return m; }
    return free.filter(function (c) { return !S.calls[c].result; })[0] || '';
  }
  function addChild(r, tid, it) {
    it.task = tid;
    if (S.tids.indexOf(tid) < 0) S.tids.push(tid);
    let pc = S.linkT[tid];
    if (!pc && !S.orph[tid]) {
      pc = guessParent(tid);
      if (pc) { S.linkT[tid] = pc; S.linkC[pc] = tid; } else S.orph[tid] = true;
      r.tasks = true;   // /tasks 로 맞춰 본다 / confirm against /tasks
    }
    if (S.orph[tid]) { r.add = pushItem(it); return; }
    const sub = S.sub[tid] || (S.sub[tid] = { items: [], tools: 0 });
    sub.items.push(it);
    if (it.k === 'tool') sub.tools += 1;
    r.sub = { parent: pc, it: it };
  }
  // 확정 연결은 두고 나머지를 /tasks label → 지금 연결 → 순서로 다시 맞춘다 → 자식이 바뀐 부모 카드 call id 목록
  // Keep the fixed links, rematch the rest by /tasks label, then the current link, then order → call ids of parents whose children changed
  function fixLinks() {
    const before = Object.assign({}, S.linkC), nextT = {}, nextC = {};
    Object.keys(S.fixed).forEach(function (c) { const t = S.fixed[c]; if (!nextT[t] && !nextC[c]) { nextT[t] = c; nextC[c] = t; } });
    const pending = S.tids.filter(function (t) { return !nextT[t] && !S.orph[t]; });
    pending.forEach(function (t) {
      const row = taskRow(t);
      if (!row || !row.label) return;
      const c = freeCalls(nextC).filter(function (x) { return descOf(x) === String(row.label); })[0];
      if (c) { nextT[t] = c; nextC[c] = t; }
    });
    pending.forEach(function (t) {
      if (nextT[t]) return;
      const old = S.linkT[t];
      const c = (old && !nextC[old]) ? old : freeCalls(nextC).filter(function (x) { return !S.calls[x].result; })[0];
      if (c) { nextT[t] = c; nextC[c] = t; }
      else {   // 둘 곳이 없다 → 본문의 일반 카드로 / nowhere to go → ordinary cards in the body
        S.orph[t] = true;
        const sub = S.sub[t];
        if (sub) { sub.items.forEach(function (it) { pushItem(it); if (S.on && R.tx) appendItem(it); }); delete S.sub[t]; }
      }
    });
    S.linkT = nextT; S.linkC = nextC;
    const changed = {};
    Object.keys(before).forEach(function (c) { if (before[c] !== nextC[c]) changed[c] = true; });
    Object.keys(nextC).forEach(function (c) { if (before[c] !== nextC[c]) changed[c] = true; });
    return Object.keys(changed);
  }
  function repaintParents(list) { (list || []).forEach(function (c) { repaintTool(c); }); }
  // 처음 보는 task_id 는 /tasks 를 곧 다시 읽어 label 로 맞춘다(묶어서 한 번) / an unseen task_id re-reads /tasks soon to match labels (batched)
  function kickTasks() {
    if (S.tasksKick || !S.on || !S.cur) return;
    S.tasksKick = setTimeout(function () { S.tasksKick = null; loadTasks(); }, TASKS_KICK_MS);
  }

  /* ── 살아 있는 체크포인트(적대 검토 M2) / live checkpoints (review M2) ──
     ⟲ 는 이벤트 재생만으로 붙이지 않는다: 서버가 50개를 넘겨 정리한 체크포인트는 GET …/checkpoints 에 없으니 그 id 에만 붙인다.
     세션을 열 때와 checkpoint 이벤트 뒤에 다시 읽는다. The restore button is not attached from the replay alone: checkpoints the
     server trimmed past 50 are missing from GET …/checkpoints, so only listed ids get one. Re-read on open and after checkpoint events. */
  function cpShown(cp) { return !!(cp && cp.id && S.cpLive && S.cpLive[String(cp.id)]); }
  function repaintCp(cid) { Object.keys(S.cps).forEach(function (seq) { if (S.cps[seq] && String(S.cps[seq].id) === String(cid)) repaintUser(Number(seq)); }); }
  function loadCheckpoints() {
    if (!S.on || !S.cur || !v2() || isBrowser()) return;   // 내 컴퓨터 폴더엔 체크포인트가 없다 / no checkpoints for browser folders
    const tok = S.openTok, sid = S.cur.id, my = (S.cpSeq = (S.cpSeq || 0) + 1);
    api(sessUrl(sid, '/checkpoints') + qs()).then(function (d) {
      if (tok !== S.openTok || my !== S.cpSeq) return;
      const live = {}, old = S.cpLive || {};
      ((d && d.checkpoints) || []).forEach(function (c) { if (c && c.id) live[String(c.id)] = true; });
      S.cpLive = live;
      Object.keys(S.cps).forEach(function (seq) { const id = String(S.cps[seq].id); if (!!old[id] !== !!live[id]) repaintUser(Number(seq)); });
    }).catch(noop);   // 못 읽으면 지금 표시를 둔다 / keep the current marks when the read fails
  }
  function kickCheckpoints() {
    if (S.cpKick || !S.on || !S.cur) return;
    S.cpKick = setTimeout(function () { S.cpKick = null; loadCheckpoints(); }, TASKS_KICK_MS);
  }

  // 스트림으로 온 이벤트 하나 → 필요한 곳만 다시 그림 / one streamed event → repaint only what changed
  function onLive(ev) {
    const r = ingest(ev);
    if (!r || !S.on || !R.tx) return;
    const near = nearBottom();
    if (r.pend) paintPend();
    if (r.add) appendItem(r.add);
    if (r.sub) appendSub(r.sub.parent, r.sub.it);
    if (r.relink && r.relink.length) repaintParents(r.relink);
    if (r.tool) repaintTool(r.tool);
    if (r.prow) repaintTaskRow(r.prow);
    if (r.appr) repaintAppr(r.appr);
    if (r.user !== undefined) repaintUser(r.user);
    if (r.plan) repaintPlan(r.plan);
    if (r.status) onStatusChange(r.status, ev.ts);
    if (r.ctx) paintSec('ctx');
    if (r.term) paintSec('term');
    if (r.queue) paintQueue();
    if (r.tasks) kickTasks();
    if (r.cps) kickCheckpoints();
    if (r.git) afterGit(); else if (r.changes) loadChanges();
    if (near) scrollBottom();
    scheduleSeen();
  }

  function onStatusChange(st, ts) {
    if (!S.cur) return;
    const i = idxSess(S.cur.id);
    if (i >= 0) { S.sessions[i] = Object.assign({}, S.sessions[i], { status: st }, ts ? { updated: ts } : {}); sortSessions(); }
    renderSideList(); paintStatus(); syncComposer(); repaintPendingTools();
    ensureTaskPoll();
    // 상태로 바뀌는 것(버튼 disabled)만 제자리에서 토글한다: 다시 그리면 패널 스크롤이 처음으로 가고 펼친 카드가 깜빡인다(적대 검토 L7)
    // Toggle only the state-driven bits (disabled buttons) in place: a repaint resets panel scroll and flickers open cards (review L7)
    syncPlanBtns(); syncChangesBtns();
    if (!BUSY[st]) {
      loadTasks(); refreshMeta(); refreshTree(); refreshViewer();
      if (v2()) { loadChanges(); loadOutputs(); }   // 턴 끝 / the end of a turn
      fsDropWaiting();   // 턴이 끝나면 서버가 남은 브라우저 요청을 정리했다 / the server dropped any browser request left at the end of the turn
    }
    ensureListPoll();
  }

  // 서버 응답의 세션으로 갱신 - last_seq 가 스트림보다 오래됐으면 상태 · 컨텍스트는 스트림 쪽을 믿는다
  // Update from a session in an API reply; when its last_seq is older than the stream, status and context keep the stream's values
  function upsert(s) {
    if (!s || !s.id) return;
    const isCur = !!(S.cur && S.cur.id === s.id);
    let changed = '';
    if (isCur) {
      const fresh = typeof s.last_seq !== 'number' || s.last_seq >= S.lastSeq;
      const next = Object.assign({}, S.cur, s);
      if (!fresh) { next.status = S.cur.status; next.context_pct = S.cur.context_pct; }
      if (next.status !== S.cur.status) changed = next.status;
      S.cur = next;
    }
    const i = idxSess(s.id);
    const entry = Object.assign({}, i >= 0 ? S.sessions[i] : {}, s, isCur ? { status: S.cur.status } : {});
    if (i >= 0) S.sessions[i] = entry; else S.sessions.push(entry);
    sortSessions();
    renderSideList(); renderHead(); syncComposer();
    if (isCur) {
      paintSec('env'); paintSec('ctx'); paintSec('connectors');
      syncPlanBtns();
      if (changed) onStatusChange(changed);
    }
    ensureListPoll();
  }

  function refreshMeta() {
    if (!S.cur) return;
    const tok = S.openTok, sid = S.cur.id;
    api(sessUrl(sid) + qs()).then(function (d) {
      if (tok !== S.openTok || !S.cur) return;
      if (d && d.git) S.git = d.git;
      if (d && d.session) upsert(d.session); else paintSec('env');
    }).catch(noop);
  }

  /* ── 스트림(SSE) / the stream (SSE) ── */
  function connect() {
    closeStream();
    if (!S.on || !S.cur || typeof window.EventSource !== 'function') return;
    const sid = S.cur.id, tok = S.openTok;
    let es;
    try { es = new EventSource(sessUrl(sid, '/stream') + qs({ after: S.lastSeq })); } catch (e) { S.reFails += 1; retry(sid, tok); return; }
    S.es = es;
    es.onopen = function () {
      if (S.es !== es) return;
      S.reFails = 0;
      if (isBrowser()) fsSync();   // 다시 붙을 때마다 대기 요청을 맞춰 본다(계약 F3) / re-sync the waiting requests on every (re)connect (contract F3)
    };
    es.onmessage = function (m) {
      if (S.es !== es || tok !== S.openTok) return;
      let ev = null;
      try { ev = JSON.parse(m.data); } catch (err) { return; }
      onLive(ev);
    };
    // 내 컴퓨터 폴더의 도구 요청(seq 없는 transient, 계약 E) / browser-folder tool requests (transient, no seq; contract E)
    es.addEventListener('tool_request', function (m) {
      if (S.es !== es || tok !== S.openTok) return;
      let p = null;
      try { p = JSON.parse(m.data); } catch (err) { return; }
      onToolRequest(p);
    });
    es.onerror = function () {   // 끊김(서버 재시작 · 응답 끝) → 닫고 3초 뒤 after 를 새로 해서 다시 / dropped → close, reconnect in 3 s with a fresh after
      if (S.es !== es) return;
      es.close();
      S.es = null;
      S.reFails += 1;
      retry(sid, tok);
    };
  }
  function retry(sid, tok) {
    clearTimeout(S.reTimer);
    S.reTimer = setTimeout(function () {
      S.reTimer = null;
      if (S.on && S.cur && S.cur.id === sid && tok === S.openTok) connect();
    }, S.reFails > 5 ? RETRY_SLOW_MS : RETRY_MS);
  }
  function closeStream() {
    clearTimeout(S.reTimer); S.reTimer = null;
    if (S.es) { try { S.es.close(); } catch (e) { /* 이미 닫힘 / already closed */ } S.es = null; }
  }
  // 보내기 · 승인 · 중단 뒤 스트림이 쉬고 있으면 기다리지 않고 바로 다시 붙는다 / after send, approve or stop, reattach at once when the stream is idle
  function kick() { if (S.on && S.cur && !S.es) connect(); }

  /* ── 백그라운드 작업 / background tasks ── */
  function loadTasks() {
    if (!S.on || !S.cur) return;
    const tok = S.openTok, sid = S.cur.id;
    api(sessUrl(sid, '/tasks') + qs()).then(function (d) {
      if (tok !== S.openTok) return;
      S.tasks = (d && d.tasks) || [];
      if (S.tids.length) repaintParents(fixLinks());   // label 로 서브에이전트 연결을 다시 맞춘다 / rematch subagent links by label
      paintSec('tasks');
      ensureTaskPoll();
    }).catch(noop);
  }
  // 세션이 실행 중이거나 백그라운드 작업이 돌고 있는 동안 5초마다 / every 5 s while the session runs or a background task is running
  function ensureTaskPoll() {
    const need = S.on && !!S.cur && !S.sessLoading && (isBusy() || S.tasks.some(function (t) { return t.status === 'running'; }));
    if (need && !S.taskTimer) S.taskTimer = setInterval(loadTasks, TASK_POLL_MS);
    else if (!need) stopTaskPoll();
  }
  function stopTaskPoll() { if (S.taskTimer) { clearInterval(S.taskTimer); S.taskTimer = null; } }

  /* ── 2차 패널 데이터 · 미확인 보고 / phase-2 panel data and seen reports ── */
  // MCP 도구 커넥터(전역 목록, 마운트마다 한 번) / MCP tool connectors (a global list, once per mount)
  function loadConns() {
    if (!S.on) return;
    const tok = S.mountTok;
    S.conns = { loading: true, list: (S.conns && S.conns.list) || null, err: '' };
    paintSec('connectors');
    api(BASE + '/connectors' + qs()).then(function (d) {
      if (tok !== S.mountTok || !S.on) return;
      S.conns = { loading: false, list: (d && Array.isArray(d.connectors)) ? d.connectors : [], err: '' };
      paintSec('connectors');
      // 목록이 승인 카드보다 늦게 오면 커넥터 규칙 범위(id)를 이름으로 다시 그린다 / when the list arrives after the cards, connector scopes switch from ids to names
      Object.keys(S.approvals).forEach(function (aid) {
        const a = S.approvals[aid];
        if ((a.decision || 'pending') === 'pending' && a.rule && a.rule.tool === 'mcp_tool') repaintAppr(aid);
      });
    }).catch(function (err) {
      if (tok !== S.mountTok || !S.on) return;
      S.conns = { loading: false, list: null, err: err.message || T('연결 도구를 불러오지 못했습니다') };
      paintSec('connectors');
    });
  }
  // 세션 열 때 · 턴 끝 · 복원 · 커밋 뒤(계약 2 H). 다시 읽는 동안 지금 목록을 둔다 / on open, turn end, restore and commit (contract 2 H); the current list stays while re-reading
  // 겹친 요청은 마지막 것만 적용한다(늦게 온 옛 응답이 새 목록을 덮지 않게) / overlapping reads: only the latest applies, so a late old reply never overwrites a newer list
  function loadChanges() {
    if (!S.on || !S.cur || !v2() || isBrowser()) return;   // 내 컴퓨터 폴더엔 git 이 없다(서버 409) / no git for browser folders (the server answers 409)
    const tok = S.openTok, sid = S.cur.id, old = S.changes, my = (S.chSeq = (S.chSeq || 0) + 1);
    S.changes = { loading: true, data: old && old.data, err: '' };
    if (!old || !old.data) paintSec('changes');
    api(sessUrl(sid, '/changes') + qs()).then(function (d) {
      if (tok !== S.openTok || my !== S.chSeq) return;
      S.changes = { loading: false, data: d || { repo: false, files: [] }, err: '' };
      paintSec('changes');
    }).catch(function (err) {
      if (tok !== S.openTok || my !== S.chSeq) return;
      S.changes = { loading: false, data: old && old.data, err: (old && old.data) ? '' : (err.message || T('변경 사항을 불러오지 못했습니다')) };
      paintSec('changes');
    });
  }
  function loadOutputs() {
    if (!S.on || !S.cur || !v2()) return;
    const tok = S.openTok, sid = S.cur.id, old = S.outputs, my = (S.outSeq = (S.outSeq || 0) + 1);
    S.outputs = { loading: true, list: old && old.list, err: '' };
    if (!old || !old.list) paintSec('outputs');
    api(sessUrl(sid, '/outputs') + qs()).then(function (d) {
      if (tok !== S.openTok || my !== S.outSeq) return;
      S.outputs = { loading: false, list: (d && Array.isArray(d.outputs)) ? d.outputs : [], err: '' };
      paintSec('outputs');
    }).catch(function (err) {
      if (tok !== S.openTok || my !== S.outSeq) return;
      S.outputs = { loading: false, list: old && old.list, err: (old && old.list) ? '' : (err.message || T('산출물을 불러오지 못했습니다')) };
      paintSec('outputs');
    });
  }
  // 열린 세션의 이벤트를 받으면 1초 디바운스(최대 5초)로 POST /seen(문서가 보일 때만) / on events in the open session, POST /seen after a 1 s debounce (5 s at most), only while the page is visible
  function visible() { return document.visibilityState === 'visible'; }
  function scheduleSeen() {
    if (!S.on || !S.cur || !v2() || !visible() || S.sessLoading) return;
    if (S.lastSeq <= Math.max(S.seenPosted, Number(S.cur.seen_seq) || 0)) return;
    const now = Date.now();
    if (!S.seenTimer) S.seenFirst = now;
    clearTimeout(S.seenTimer);
    S.seenTimer = setTimeout(postSeen, Math.max(0, Math.min(SEEN_MS, S.seenFirst + SEEN_MAX_MS - now)));
  }
  function flushSeen() { if (S.seenTimer) { clearTimeout(S.seenTimer); postSeen(); } }
  function postSeen() {
    clearTimeout(S.seenTimer); S.seenTimer = null;
    if (!S.on || !S.cur || !v2() || !visible()) return;
    const sid = S.cur.id, seq = S.lastSeq;
    if (!seq || seq <= Math.max(S.seenPosted, Number(S.cur.seen_seq) || 0)) return;
    S.seenPosted = seq;
    const mark = function (s, v) { if (s && (Number(s.seen_seq) || 0) < v) s.seen_seq = v; };
    mark(S.cur, seq);
    const i = idxSess(sid);
    if (i >= 0) { S.sessions[i] = Object.assign({}, S.sessions[i]); mark(S.sessions[i], seq); if (typeof S.sessions[i].last_seq !== 'number' || S.sessions[i].last_seq < seq) S.sessions[i].last_seq = seq; }
    api(sessUrl(sid, '/seen'), 'POST', withActing({ seq: seq })).then(function (d) {
      const s = d && d.session;
      if (!s || typeof s.seen_seq !== 'number') return;
      const j = idxSess(sid);
      if (j >= 0) mark(S.sessions[j], s.seen_seq);
      if (S.cur && S.cur.id === sid) mark(S.cur, s.seen_seq);
    }).catch(noop);
  }

  /* ── 그리기 / rendering ── */
  function renderAll() {
    if (!S.on) return;
    renderSide(); renderHead(); paintTranscript(); paintViewer(); syncComposer(); renderEnv(); paintSlash(); paintFsBar();
  }

  function renderSide() {
    if (!R.side) return;
    R.side.innerHTML = '<div class="ai365-ag-stop"><span class="lg">' + IC.agentic + '</span>'
      + '<span class="nm hide-on-collapse" data-i18n-skip>Agentic</span><span class="sp hide-on-collapse"></span>'
      + '<button type="button" class="icon-btn hide-on-collapse" data-ag="collapse" title="' + E(T('사이드바 접기')) + '" aria-label="' + E(T('사이드바 접기')) + '">' + IC.sidebar + '</button></div>'
      + '<div class="ai365-ag-sbody">'
      + '<button type="button" class="nav-item new-chat ai365-ag-snew" data-ag="new" title="' + E(T('새 세션')) + '"><span class="nav-icon-circle">' + IC.plus + '</span><span class="hide-on-collapse">' + E(T('새 세션')) + '</span></button>'
      + '<label class="ai365-ag-ssearch hide-on-collapse">' + IC.search + '<input type="search" data-ag="search" placeholder="' + E(T('세션 검색')) + '" aria-label="' + E(T('세션 검색')) + '" value="' + E(S.search) + '" autocomplete="off" data-i18n-skip></label>'
      + '<div class="ai365-ag-slist" role="list"></div></div>';
    R.slist = R.side.querySelector('.ai365-ag-slist');
    renderSideList();
  }

  function renderSideList() {
    if (!R.slist) return;
    if (S.listLoading && !S.sessions.length) { R.slist.innerHTML = '<div class="ai365-ag-snone hide-on-collapse">' + E(T('불러오는 중…')) + '</div>'; return; }
    if (S.listErr && !S.sessions.length) { R.slist.innerHTML = '<div class="ai365-ag-snone hide-on-collapse" data-i18n-skip>' + E(S.listErr) + '</div>'; return; }
    const q = S.search.trim().toLowerCase();
    const list = S.sessions.filter(function (s) { return !q || String(s.title || '').toLowerCase().indexOf(q) >= 0 || String(s.folder || '').toLowerCase().indexOf(q) >= 0; });
    if (!list.length) { R.slist.innerHTML = '<div class="ai365-ag-snone hide-on-collapse">' + E(T(S.sessions.length ? '검색 결과가 없습니다' : '세션이 없습니다')) + '</div>'; return; }
    const groups = [], by = {};
    list.forEach(function (s) {   // 작업 폴더별 묶음, 묶음 순서 = 가장 최근 활동 순 / grouped by working folder, groups ordered by latest activity
      // 내 컴퓨터 폴더(이름만)는 서버 폴더와 따로 묶는다 / browser folders (names only) group apart from server folders
      const br = isBrowser(s), k = (br ? 'b|' : '') + folderKey(s.folder);
      if (!by[k]) { by[k] = { folder: s.folder, browser: br, items: [] }; groups.push(by[k]); }
      by[k].items.push(s);
    });
    R.slist.innerHTML = groups.map(function (g) {
      return '<div class="ai365-ag-sgrp" role="group"' + (g.browser ? ' data-kind="browser"' : '') + '><div class="ai365-ag-sgh hide-on-collapse" title="' + E(g.folder) + '">' + IC.folder
        + '<span data-i18n-skip>' + E(g.browser ? g.folder : (baseName(g.folder) || g.folder)) + '</span>'
        + (g.browser ? '<span class="tag" data-i18n-skip>' + E(T('내 컴퓨터')) + '</span>' : '') + '</div>' + g.items.map(sessHtml).join('') + '</div>';
    }).join('');
  }

  function sessHtml(s) {
    const on = !!(S.cur && S.cur.id === s.id), st = s.status || 'idle', title = titleOf(s);
    // 미확인 = 실행 중이 아니고 last_seq > seen_seq(열려 있는 세션은 보고 있으니 빼고, 실행 · 오류 점이 먼저)
    // Unseen = not running and last_seq > seen_seq (never the open session; the running and error dots win)
    const unseen = !on && typeof s.last_seq === 'number' && typeof s.seen_seq === 'number' && s.last_seq > s.seen_seq;
    const dot = SESS_STATE[st] ? st : (unseen ? 'unseen' : '');
    const dotTip = dot ? ' title="' + E(T(dot === 'unseen' ? '새 활동' : SESS_STATE[dot])) + '"' : '';
    return '<button type="button" class="ai365-ag-sess' + (on ? ' on' : '') + '" data-id="' + E(s.id) + '" role="listitem" title="' + E(title) + '"' + (on ? ' aria-current="true"' : '') + '>'
      + '<span class="av" aria-hidden="true" data-i18n-skip>' + E(initial(title)) + (dot ? '<i class="dot ' + dot + '"></i>' : '') + '</span>'
      + '<span class="dot ' + dot + ' hide-on-collapse"' + dotTip + '></span>'
      + '<span class="tt hide-on-collapse" data-i18n-skip>' + E(title) + '</span>'
      + '<span class="tm hide-on-collapse" data-i18n-skip>' + E(ago(s.updated)) + '</span></button>';
  }

  function renderHead() {
    if (!R.hl) return;
    const cur = S.cur, viewer = !!S.viewer;
    R.hl.innerHTML = '<button type="button" class="ai365-ag-nav tip" data-ag="back" data-tip="' + E(T('이전 세션')) + '" aria-label="' + E(T('이전 세션')) + '"' + (canHist(-1) ? '' : ' disabled') + '>' + IC.left + '</button>'
      + '<button type="button" class="ai365-ag-nav tip" data-ag="fwd" data-tip="' + E(T('다음 세션')) + '" aria-label="' + E(T('다음 세션')) + '"' + (canHist(1) ? '' : ' disabled') + '>' + IC.right + '</button>'
      + (cur ? '<button type="button" class="ai365-ag-title" data-ag="title" aria-haspopup="menu" aria-expanded="' + (S.menu ? 'true' : 'false') + '" aria-label="' + E(T('세션 메뉴')) + '" title="' + E(cur.folder || '') + '">'
        + '<span class="t" data-i18n-skip>' + E(titleOf(cur)) + '</span>' + IC.chev + '</button>' : '');
    R.hr.innerHTML = hb('transcript', IC.transcript, '트랜스크립트', !viewer)
      + (isBrowser(cur) ? '' : hb('terminal', IC.terminal, '터미널', false))   // 내 컴퓨터 폴더엔 명령이 없다 / no commands for browser folders
      + (v2() ? hb('outputs', IC.outputs, '산출물', false) : '')   // 2차: 산출물(설계 1절 순서) / phase 2: outputs, in the design's order
      + hb('files', IC.files, '파일', viewer)
      + hb('panel', IC.panel, S.env ? '패널 접기' : '패널 펴기', S.env);
    paintMenu();
  }
  function hb(name, icon, label, on) {
    return '<button type="button" class="ai365-ag-hb tip' + (on ? ' on' : '') + '" data-ag-view="' + name + '" data-tip="' + E(T(label)) + '" aria-label="' + E(T(label)) + '"'
      + (name === 'panel' ? ' aria-pressed="' + (on ? 'true' : 'false') + '"' : '') + '>' + icon + '</button>';
  }
  function paintMenu() {
    if (!R.head) return;
    let m = R.head.querySelector('.ai365-ag-menu');
    const btn = R.hl && R.hl.querySelector('[data-ag="title"]');
    if (!S.menu || !S.cur || !btn) { if (m) m.remove(); if (btn) btn.setAttribute('aria-expanded', 'false'); return; }
    if (!m) { m = document.createElement('div'); m.className = 'ai365-ag-menu'; m.setAttribute('role', 'menu'); R.head.appendChild(m); m.addEventListener('click', onHeadClick); }
    m.style.left = Math.max(8, btn.offsetLeft) + 'px';
    m.innerHTML = menuItem('rename', IC.edit, '이름 바꾸기') + menuItem('folder', IC.folder, '폴더 보기')
      // 폴더 고르기(2026-10-19): 추가 폴더 대화 상자. 내 컴퓨터 폴더 세션은 그 대신 '폴더 다시 연결…'(계약 F4)
      // Folder picking: the extra folders dialog; a browser-folder session gets 'Reconnect folder…' instead (contract F4)
      + (isBrowser() ? (fsAvail() ? menuItem('fsrelink', IC.laptop, '폴더 다시 연결…') : '') : (S.picker ? menuItem('folders', IC.plus, '추가 폴더…') : ''))
      + (v2() ? menuItem('notify', IC.bell, S.cur.notify ? '완료 알림 끄기' : '완료 알림 켜기') : '')   // 2차: 완료 알림 / phase 2: completion notices
      + '<div class="sep"></div>' + menuItem('delete', IC.trash, '삭제', 'danger');
    btn.setAttribute('aria-expanded', 'true');
  }
  function menuItem(act, icon, label, cls) {
    return '<button type="button" class="ai365-ag-mi' + (cls ? ' ' + cls : '') + '" role="menuitem" data-ag-menu="' + act + '">' + icon + '<span>' + E(T(label)) + '</span></button>';
  }
  function setMenu(on) { S.menu = !!on; paintMenu(); }

  function paintTranscript() {
    if (!R.tx) return;
    R.status = null;
    if (!S.cur) {
      if (S.listLoading || S.fsMaking) R.tx.innerHTML = '<div class="ai365-ag-hint">' + E(T('불러오는 중…')) + '</div>';
      else if (S.listErr) R.tx.innerHTML = stateHtml(T('세션 목록을 불러오지 못했습니다'), S.listErr, 'retry', '다시 시도', true);
      else if (fsAvail() || S.remote) R.tx.innerHTML = emptyFsHtml();   // 내 컴퓨터 폴더 + 서버 폴더(계약 F2, 원격은 내 컴퓨터만) / my-computer and server folders (contract F2; remote: my computer only)
      else R.tx.innerHTML = stateHtml(T('작업 폴더를 골라 새 세션을 시작하세요'), T('에이전트가 작업 폴더 안에서 파일을 읽고 고치고 명령을 실행합니다.'), 'newc', '새 세션', false);
      return;
    }
    if (S.sessLoading) { R.tx.innerHTML = '<div class="ai365-ag-hint">' + E(T('불러오는 중…')) + '</div>'; return; }
    if (S.sessErr) { R.tx.innerHTML = stateHtml(T('세션을 불러오지 못했습니다'), S.sessErr, '', '', true); return; }
    R.tx.innerHTML = (S.items.length ? S.items.map(itemHtml).join('') : '<div class="ai365-ag-hint">' + E(T('아직 대화가 없습니다. 아래 입력창에 맡길 작업을 적어 보세요.')) + '</div>')
      + pendHtml() + '<div class="ai365-ag-status" role="status" aria-live="polite" hidden></div>';
    R.status = R.tx.querySelector('.ai365-ag-status');
    paintStatus();
  }
  function stateHtml(title, text, act, label, bad) {
    return '<div class="ai365-ag-empty' + (bad ? ' bad' : '') + '"><div class="ic">' + (bad ? IC.alert : IC.agentic) + '</div><h2>' + E(title) + '</h2>'
      + (text ? '<p' + (bad ? ' data-i18n-skip' : '') + '>' + E(text) + '</p>' : '')
      + (act ? '<button type="button" class="ai365-ag-btn' + (bad ? '' : ' pri') + '" data-ag="' + act + '">' + (bad ? '' : IC.plus) + E(T(label)) + '</button>' : '') + '</div>';
  }
  // 세션이 없을 때(브라우저가 폴더 열기를 지원하면): [내 컴퓨터 폴더 열기](선택 창 → 설정 기본값으로 생성) + [서버 폴더로 새 세션](종전
  // 대화 상자, 원격 클라이언트는 없음). 원격인데 폴더를 열 수 없으면 버튼 없이 안내만
  // No sessions yet, on a browser that can open folders: [Open a folder on my computer] (picker → created with the default settings)
  // plus [New session on a server folder] (the existing dialog; not for remote clients). Remote without folder access: the note only
  function emptyFsHtml() {
    const ok = fsAvail();
    return '<div class="ai365-ag-empty"><div class="ic">' + IC.agentic + '</div><h2>' + E(T('작업 폴더를 골라 새 세션을 시작하세요')) + '</h2>'
      + '<p>' + E(T(ok ? '브라우저로 내 컴퓨터의 폴더를 고릅니다. 에이전트가 그 폴더 안의 파일을 읽고 고칩니다(명령 실행 없음).' : (S.fsOk ? FS_OFF : FS_NO))) + '</p>'
      + (ok || !S.remote ? '<div class="acts">'
        + (ok ? '<button type="button" class="ai365-ag-btn pri" data-ag="fsopen"' + (S.fsBusy ? ' disabled' : '') + '>' + IC.laptop + E(T('내 컴퓨터 폴더 열기')) + '</button>' : '')
        + (S.remote ? '' : '<button type="button" class="ai365-ag-btn" data-ag="newc">' + IC.plus + E(T('서버 폴더로 새 세션')) + '</button>') + '</div>' : '')
      + '</div>';
  }
  // 보내는 중인 글 + 끼워 넣기로 보내 아직 user 이벤트가 안 온 글(흐린 말풍선) / the text being sent plus steered texts not yet echoed (faded bubbles)
  function pendHtml() {
    return S.steer.map(function (t) {
      return '<div class="ai365-ag-msg pend steer" data-i18n-skip><span class="tg">' + E(T('전달 대기')) + '</span>' + E(t) + '</div>';
    }).join('') + (S.pend ? '<div class="ai365-ag-msg pend" data-i18n-skip>' + E(S.pend) + '</div>' : '');
  }
  function paintPend() {
    if (!R.tx) return;
    R.tx.querySelectorAll('.ai365-ag-msg.pend').forEach(function (el) { el.remove(); });
    if ((S.pend || S.steer.length) && R.status) R.status.insertAdjacentHTML('beforebegin', pendHtml());
  }
  function appendItem(it) {
    if (!R.tx || !R.status) return;
    const hint = R.tx.querySelector('.ai365-ag-hint');
    if (hint) hint.remove();
    const pend = R.tx.querySelector('.ai365-ag-msg.pend');
    (pend || R.status).insertAdjacentHTML('beforebegin', itemHtml(it));
  }
  function repaintTool(id) {
    const el = R.tx && R.tx.querySelector('.ai365-ag-tool[data-call="' + cssq(id) + '"]');
    if (el && S.calls[id]) el.outerHTML = toolHtml(id);
  }
  function repaintAppr(aid) {
    const el = R.tx && R.tx.querySelector('.ai365-ag-approval[data-aid="' + cssq(aid) + '"]');
    if (el && S.approvals[aid]) el.outerHTML = apprHtml(aid);
  }
  // 결과가 없는 호출(자식 포함)만 상태를 제자리에서 바꾼다(펼친 본문 · 스크롤을 지킨다, 적대 검토 L7)
  // Only calls without a result (children included) get their state updated in place, keeping open bodies and scroll (review L7)
  function repaintPendingTools() {
    const rows = {};
    Object.keys(S.calls).forEach(function (id) {
      const c = S.calls[id];
      if (c.result) return;
      if (c.call.tool === 'task' && !c.task) rows[id] = true; else refreshToolState(id);
      if (c.call.tool === 'bash') refreshTermState(id);
      if (c.task && S.linkT[c.task]) rows[S.linkT[c.task]] = true;
    });
    Object.keys(rows).forEach(repaintTaskRow);
  }
  function refreshToolState(id) {
    const c = S.calls[id], el = c && R.tx && R.tx.querySelector('.ai365-ag-tool[data-call="' + cssq(id) + '"]');
    if (!el) return;
    const st = toolState(c);
    if (el.getAttribute('data-state') === st) return;
    el.setAttribute('data-state', st);
    const dot = el.querySelector(':scope > .ai365-ag-trow > .st');
    if (dot) { dot.className = 'st ' + st; dot.title = T(TOOL_STATE[st]); }
    const note = el.querySelector(':scope > .ai365-ag-tbody > [data-ag-stnote]');
    if (note) note.textContent = T(TOOL_STATE[st]);
  }
  function refreshTermState(id) {
    const c = S.calls[id], el = c && R.env && R.env.querySelector('[data-ag-term="' + cssq(id) + '"]');
    if (!el) return;
    const st = toolState(c), dot = el.querySelector('.ai365-ag-tih > .st'), note = el.querySelector('[data-ag-stnote]');
    if (dot) dot.className = 'st ' + st;
    if (note) note.textContent = T(TOOL_STATE[st]);
  }
  // 계획 버튼 · Changes 버튼의 사용 가능 여부만 / only whether the plan buttons and the Changes buttons are usable
  function syncPlanBtns() {
    const el = S.lastPlanSeq ? bySeq('ai365-ag-msg.agent.plan', S.lastPlanSeq) : null, b = el && el.querySelector('[data-ag="plan-run"]');
    if (b) b.disabled = isBusy() || S.sending;
  }
  function syncChangesBtns() {
    const sec = R.env && R.env.querySelector('[data-sec="changes"]');
    if (!sec) return;
    const busy = isBusy(), d = S.changes && S.changes.data, files = d && Array.isArray(d.files) ? d.files : [], tip = busy ? T('실행 중에는 쓸 수 없습니다') : '';
    const cp = sec.querySelector('[data-ag="checkpoint"]'), cm = sec.querySelector('[data-ag="commit"]');
    if (cp) { cp.disabled = busy || S.cpBusy; cp.title = tip; }
    if (cm) { cm.disabled = busy || !files.length; cm.title = tip; }
  }
  function bySeq(cls, seq) { return R.tx ? R.tx.querySelector('.' + cls + '[data-seq="' + cssq(seq) + '"]') : null; }
  function repaintUser(seq) { const it = S.userIt[seq], el = bySeq('ai365-ag-msg.user', seq); if (it && el) el.outerHTML = itemHtml(it); }
  function repaintPlan(seq) { const it = S.planIt[seq], el = bySeq('ai365-ag-msg.agent.plan', seq); if (it && el) el.outerHTML = itemHtml(it); }
  function repaintSeqItem(cls, seq) {   // 훅 줄 · 압축 칩(본문이나 task 카드 안) / a hook line or compact chip (body or inside a task card)
    const el = bySeq(cls, seq), it = findSeqItem(seq);
    if (el && it) el.outerHTML = it.task && !S.orph[it.task] ? subItemHtml(it) : itemHtml(it);
  }
  function findSeqItem(seq) {
    let hit = null;
    S.items.forEach(function (x) { if (x.ev && x.ev.seq === seq) hit = x; });
    if (!hit) Object.keys(S.sub).forEach(function (t) { S.sub[t].items.forEach(function (x) { if (x.ev && x.ev.seq === seq) hit = x; }); });
    return hit;
  }
  // 서브에이전트 자식 하나를 부모 카드에 붙인다(펼쳐 있을 때만 DOM) + 부모 줄 갱신 / append one subagent child to its parent card (DOM only while open) and refresh the parent row
  function appendSub(parent, it) {
    const el = R.tx && R.tx.querySelector('.ai365-ag-tool[data-call="' + cssq(parent) + '"]');
    if (!el) return;
    const box = S.open[parent] && el.querySelector(':scope > .ai365-ag-tbody > .ai365-ag-sub');
    if (box) {
      const empty = box.querySelector(':scope > .ai365-ag-note');
      if (empty) empty.remove();
      box.insertAdjacentHTML('beforeend', subItemHtml(it));
    }
    repaintTaskRow(parent);
  }
  function repaintTaskRow(cid) {
    const el = R.tx && R.tx.querySelector('.ai365-ag-tool[data-call="' + cssq(cid) + '"]'), c = S.calls[cid];
    if (!el || !c || c.call.tool !== 'task') return;
    const row = el.querySelector(':scope > .ai365-ag-trow'), st = taskState(cid), tid = S.linkC[cid];
    if (row) row.outerHTML = taskRowHtml(cid, st);
    el.setAttribute('data-state', st);
    if (tid) el.setAttribute('data-tid', tid); else el.removeAttribute('data-tid');   // 처음 묶인 카드도 / a card linked just now too
  }

  function itemHtml(it) {
    const p = (it.ev && it.ev.payload) || {};
    switch (it.k) {
      case 'user': return userHtml(it.ev, p);
      case 'agent':
        if (p.plan) return planHtml(it.ev, p);
        return '<div class="ai365-ag-msg agent' + (p.command ? ' cmd' : '') + '" data-seq="' + E(it.ev.seq) + '" data-i18n-skip>' + md(p.text || '') + '</div>';
      case 'tool': return toolHtml(it.id);
      case 'appr': return apprHtml(it.id);
      case 'sum': return sumHtml(p);
      case 'err': return '<div class="ai365-ag-err" role="alert">' + IC.alert + '<span data-i18n-skip>' + E(p.message || T('오류')) + '</span></div>';
      case 'mark': return '<div class="ai365-ag-mark ' + E(p.state || '') + '"><span class="ln"></span><span>' + E(T(p.state === 'error' ? '오류로 멈췄습니다' : '실행을 중단했습니다'))
        + (p.note ? ' · </span><span data-i18n-skip>' + E(p.note) : '') + '</span><span class="ln"></span></div>';
      case 'stext': case 'hook': return subItemHtml(it);   // 부모 카드가 없는 서브에이전트 자식 · 본문의 훅 / a parentless subagent child, or a hook in the body
      case 'compact': return compactHtml(it.ev, p);
      case 'cpmark': return '<div class="ai365-ag-mark checkpoint" data-seq="' + E(it.ev.seq) + '"><span class="ln"></span>' + IC.restore + '<span>' + E(T('체크포인트로 되돌렸습니다'))
        + (p.label ? ' · </span><span data-i18n-skip>' + E(p.label) : '') + '</span><span class="ln"></span></div>';
      case 'notify': return notifyHtml(p);
      default: return '';
    }
  }
  // 사용자 말풍선: 끼워 넣기 태그 · 전달되지 않은 글(dropped) · 슬래시 명령(이름 강조, expanded 는 title) · 체크포인트 ⟲(서버에 살아 있는 것만,
  // 실행 중엔 CSS 로 숨김) / A user bubble: the steer tag, an undelivered text (dropped), a slash command (name highlighted, expanded in the
  // title), the checkpoint restore button (only for checkpoints alive on the server; hidden by CSS while running)
  function userHtml(ev, p) {
    const cp = cpShown(S.cps[ev.seq]) ? S.cps[ev.seq] : null, text = String(p.text || '');
    let body = E(text);
    if (p.command || p.skill) {
      const raw = /^\s*\//.test(text) ? text : '/' + (p.command || p.skill) + (text ? ' ' + text : '');
      const m = /^(\s*\/\S+)([\s\S]*)$/.exec(raw);
      body = m ? '<span class="cn">' + E(m[1]) + '</span>' + E(m[2]) : E(raw);
    }
    const tip = p.expanded ? ' title="' + E(p.expanded) + '"' : '';
    return '<div class="ai365-ag-msg user' + (p.steer ? ' steer' : '') + (p.dropped ? ' dropped' : '') + (p.command || p.skill ? ' cmd' : '') + (cp ? ' has-cp' : '') + '" data-seq="' + E(ev.seq) + '" data-i18n-skip' + tip + '>'
      + (p.dropped ? '<span class="tg">' + E(T('전달되지 않음')) + '</span>' : (p.steer ? '<span class="tg">' + E(T('끼워 넣음')) + '</span>' : '')) + body
      + (cp ? '<button type="button" class="ai365-ag-rst" data-ag-restore="' + E(cp.id) + '" title="' + E(T('이 시점으로 되돌리기')) + '" aria-label="' + E(T('이 시점으로 되돌리기')) + '">' + IC.restore + '</button>' : '')
      + '</div>';
  }
  // 플랜 모드의 최종 답: [계획대로 실행] · [플랜 모드 유지]는 가장 최근 계획이고 뒤에 글이 없고 닫지 않았을 때만
  // The plan-mode answer: [Run the plan] and [Stay in plan mode] only on the latest plan with nothing after it, until dismissed
  function planHtml(ev, p) {
    const seq = ev.seq, live = seq === S.lastPlanSeq && seq > S.lastUserSeq && !S.planDone[seq], off = isBusy() || S.sending ? ' disabled' : '';
    // 머리표 = '플랜 모드'(본문에는 모델이 쓴 '계획' 제목이 따로 있다) / the header says 'Plan mode' (the model writes its own '계획' heading in the body)
    return '<div class="ai365-ag-msg agent plan" data-seq="' + E(seq) + '"><div class="ph">' + IC.plan + '<span>' + E(T('플랜 모드')) + '</span></div>'
      + '<div class="pb" data-i18n-skip>' + md(p.text || '') + '</div>'
      + (live ? '<div class="pa"><button type="button" class="ai365-ag-btn pri" data-ag="plan-run" data-seq="' + E(seq) + '"' + off + '>' + E(T('계획대로 실행')) + '</button>'
        + '<button type="button" class="ai365-ag-btn" data-ag="plan-stay" data-seq="' + E(seq) + '">' + E(T('플랜 모드 유지')) + '</button></div>' : '')
      + '</div>';
  }
  function fmtChars(n) {
    n = Number(n);
    if (!isFinite(n) || n < 0) return '?';
    if (isEn()) return n >= 1000 ? (Math.round(n / 100) / 10) + 'k' : String(Math.round(n));
    return n >= 10000 ? (Math.round(n / 1000) / 10) + '만' : String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }
  // 압축 칩("컨텍스트 압축 · 12.3만 → 2.1만 자" + 범위), 누르면 요약 글 / the compact chip ("Context compacted · 123k → 21k chars" and the scope); a click shows the summary
  function compactHtml(ev, p) {
    const open = !!S.compOpen[ev.seq], scope = p.scope === 'turn' ? 'turn' : 'history';
    return '<div class="ai365-ag-compact' + (open ? ' open' : '') + '" data-seq="' + E(ev.seq) + '" data-scope="' + scope + '"' + (p.task_id ? ' data-task="' + E(p.task_id) + '"' : '') + '>'
      + '<button type="button" class="ai365-ag-cphd" data-ag-compact="' + E(ev.seq) + '" aria-expanded="' + (open ? 'true' : 'false') + '"><span class="ic">' + IC.compact + '</span>'
      + '<span class="tx">' + E(T('컨텍스트 압축')) + ' · <span data-i18n-skip>' + E(fmtChars(p.chars_before) + ' → ' + fmtChars(p.chars_after) + (isEn() ? ' chars' : ' 자')) + '</span></span>'
      + '<span class="sc">' + E(T(scope === 'turn' ? '이번 작업' : '대화 기록')) + '</span></button>'
      + (open ? '<div class="ai365-ag-cbody" data-i18n-skip>' + md(p.text || '') + '</div>' : '') + '</div>';
  }
  function notifyHtml(p) {
    const ok = p.ok !== false;
    const tail = ok ? [p.backend, (Array.isArray(p.to) ? p.to.join(', ') : '')].filter(Boolean).join(' · ') : String(p.error || '');
    return '<div class="ai365-ag-notify' + (ok ? '' : ' bad') + '" role="status">' + (ok ? IC.bell : IC.alert) + '<span>' + E(T(ok ? '완료 알림을 보냈습니다' : '완료 알림을 보내지 못했습니다'))
      + (tail ? '<span data-i18n-skip>' + E((ok ? ' · ' : ': ') + tail) + '</span>' : '') + '</span></div>';
  }
  // 훅 줄: 이벤트 · 명령 · exit · 결정, 누르면 출력 / a hook line: event, command, exit code and decision; a click shows the output
  function hookHtml(ev, p) {
    const seq = ev.seq, open = !!S.hookOpen[seq], dec = p.decision || '';
    const exit = p.exit_code !== undefined && p.exit_code !== null ? '<span class="ex ' + (Number(p.exit_code) === 0 ? 'ok' : 'bad') + '" data-i18n-skip>exit ' + E(p.exit_code) + '</span>' : '';
    let body = '';
    if (open) {
      body = '<div class="ai365-ag-hbody">'
        + (p.reason ? '<div class="ai365-ag-note"><b>' + E(T('이유')) + '</b> · <span data-i18n-skip>' + E(p.reason) + '</span></div>' : '')
        + '<pre class="ai365-ag-out" data-i18n-skip><span class="pr">$ ' + E(p.command || '') + '</span>' + (p.output ? '\n' + E(p.output) : '') + '</pre>'
        + (!p.output ? '<div class="ai365-ag-note">' + E(T('출력 없음')) + '</div>' : '') + '</div>';
    }
    return '<div class="ai365-ag-hook' + (open ? ' open' : '') + '" data-seq="' + E(seq) + '" data-hook-event="' + E(p.event || '') + '" data-decision="' + E(dec) + '"' + (ev.payload && ev.payload.task_id ? ' data-task="' + E(ev.payload.task_id) + '"' : '') + '>'
      + '<button type="button" class="ai365-ag-hrow" data-ag-hook="' + E(seq) + '" aria-expanded="' + (open ? 'true' : 'false') + '"'
      + ' title="' + E([p.source ? srcLabel(p.source) : '', p.matcher ? 'matcher: ' + p.matcher : ''].filter(Boolean).join(' · ')) + '"><span class="ic">' + IC.hook + '</span>'
      + '<span class="ev">' + E(isEn() ? 'Hook' : '훅') + ' · ' + E(T(HOOK_EVENT[p.event] || String(p.event || ''))) + '</span>'
      + '<code class="cm" data-i18n-skip title="' + E(p.command || '') + '">' + E(p.command || '') + '</code>' + exit
      + (dec === 'block' ? '<span class="ex block">' + E(T('차단함')) + '</span>' : '')
      + (p.timed_out ? '<span class="ex to">' + E(T('시간 초과')) + '</span>' : '')
      + (p.duration_ms !== undefined && p.duration_ms !== null ? '<span class="du" data-i18n-skip>' + E(fmtDur(p.duration_ms)) + '</span>' : '')
      + '<span class="cv">' + IC.chevR + '</span></button>' + body + '</div>';
  }
  // 서브에이전트 카드 안의 자식(또는 부모 없는 자식) / a child inside a subagent card (or a parentless one)
  function subItemHtml(it) {
    if (it.k === 'tool') return toolHtml(it.id);
    if (it.k === 'hook') return hookHtml(it.ev, it.ev.payload || {});
    if (it.k === 'compact') return compactHtml(it.ev, it.ev.payload || {});
    if (it.k === 'stext') return '<div class="ai365-ag-stext" data-seq="' + E(it.ev.seq) + '" data-task="' + E(it.task || '') + '" data-i18n-skip>' + md((it.ev.payload || {}).text || '') + '</div>';
    return '';
  }

  // 마크다운: adapter 의 ai365MnMd 가 있으면 그것, 없으면 최소 렌더러 / markdown: the adapter's ai365MnMd when present, else a minimal renderer
  function md(text) {
    if (typeof ai365MnMd === 'function') { try { return ai365MnMd(text); } catch (e) { /* 아래 최소 렌더러로 / fall through to the minimal one */ } }
    const out = [];
    let code = null;
    const inline = function (s) { return E(s).replace(/`([^`\n]+)`/g, '<code class="ai365-md-c">$1</code>').replace(/\*\*(.+?)\*\*/g, '<b>$1</b>'); };
    String(text || '').split('\n').forEach(function (line) {
      if (/^\s*```/.test(line)) {
        if (code === null) code = []; else { out.push('<pre class="ai365-md-pre"><code>' + E(code.join('\n')) + '</code></pre>'); code = null; }
        return;
      }
      if (code !== null) { code.push(line); return; }
      if (!line.trim()) return;
      const li = /^\s*[-*]\s+(.*)$/.exec(line);
      out.push(li ? '<p>• ' + inline(li[1]) + '</p>' : '<p>' + inline(line.trim()) + '</p>');
    });
    if (code !== null) out.push('<pre class="ai365-md-pre"><code>' + E(code.join('\n')) + '</code></pre>');
    return out.join('');
  }

  function toolName(id) { const c = S.calls[id]; return c ? (c.call.tool || (c.result && c.result.tool) || '') : ''; }
  function pendingApprovalFor(callId) {
    return Object.keys(S.approvals).some(function (k) { const a = S.approvals[k]; return a.call_id === callId && (a.decision || 'pending') === 'pending'; });
  }
  function toolState(c) {
    if (c.result) return c.result.ok === false ? 'fail' : 'ok';
    if (pendingApprovalFor(c.call.call_id)) return 'wait';
    return isBusy() ? 'run' : 'stop';
  }
  function argsSummary(args) {
    args = args || {};
    if (args.command) return '$ ' + args.command;
    if (args.path && args.pattern) return args.pattern + '   ' + args.path;
    if (args.path) return String(args.path);
    if (args.pattern) return String(args.pattern);
    if (args.query) return String(args.query);
    if (args.url) return String(args.url);
    if (args.task_id) return String(args.task_id);
    if (args.name) return String(args.name);   // skill / the skill tool
    if (Array.isArray(args.hooks)) {   // 폴더 훅 신뢰 승인 / the folder-hook trust approval
      return args.hooks.map(function (h) { return T(HOOK_EVENT[h && h.event] || String((h && h.event) || '')) + ' · ' + String((h && h.command) || ''); }).join('\n');
    }
    try { const s = JSON.stringify(args); return s === '{}' ? '' : s.slice(0, 300); } catch (e) { return ''; }
  }

  function diffStat(u) {
    if (!u) return null;
    const lines = String(u).replace(/\r\n/g, '\n').split('\n'), hasHunk = lines.some(function (l) { return l.indexOf('@@') === 0; });
    let a = 0, d = 0, hunk = !hasHunk;
    lines.forEach(function (l) {
      if (l.indexOf('@@') === 0) { hunk = true; return; }
      if (!hunk) return;
      if (!hasHunk && (l.indexOf('+++') === 0 || l.indexOf('---') === 0)) return;
      if (l[0] === '+') a += 1; else if (l[0] === '-') d += 1;
    });
    return (a || d) ? { a: a, d: d } : null;
  }
  // unified diff → 줄마다 색 · 줄 번호(추가 · 문맥 = 새 번호, 삭제 = 옛 번호) / per-line colours and numbers (added and context = new, deleted = old)
  function diffHtml(u) {
    const lines = String(u).replace(/\r\n/g, '\n').split('\n');
    if (lines.length && lines[lines.length - 1] === '') lines.pop();
    const hasHunk = lines.some(function (l) { return l.indexOf('@@') === 0; });
    let hunk = !hasHunk, on = 0, nn = 0;
    return '<div class="ai365-ag-diff" data-i18n-skip><div class="in">' + lines.map(function (l) {
      let c = '', num = '';
      const m = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(l);
      if (l.indexOf('@@') === 0) { hunk = true; c = 'k'; if (m) { on = +m[1]; nn = +m[2]; } }
      else if (!hunk) c = 'h';
      else if (!hasHunk && (l.indexOf('+++') === 0 || l.indexOf('---') === 0)) c = 'h';
      else if (l[0] === '+') { c = 'a'; num = nn ? nn++ : ''; }
      else if (l[0] === '-') { c = 'd'; num = on ? on++ : ''; }
      else if (l[0] === '\\') c = 'h';
      else { num = nn ? nn : ''; if (nn) nn += 1; if (on) on += 1; }
      return '<div class="l' + (c ? ' ' + c : '') + '"><i>' + E(num) + '</i><span>' + (E(l) || ' ') + '</span></div>';
    }).join('') + '</div></div>';
  }

  function toolHtml(id) {
    const c = S.calls[id];
    if (!c) return '';
    const call = c.call || {};
    if (call.tool === 'task' && !c.task) return taskHtml(id);   // 서브에이전트 카드 / a subagent card
    const r = c.result, st = toolState(c), open = !!S.open[id];
    const grp = call.group || GROUP_OF[call.tool] || '';
    const ds = r && r.diff && r.diff.unified ? diffStat(r.diff.unified) : null;
    return '<div class="ai365-ag-tool' + (open ? ' open' : '') + '" data-call="' + E(id) + '" data-state="' + st + '" data-tool="' + E(call.tool || '') + '"'
      + (c.task ? ' data-task="' + E(c.task) + '"' : '') + '>'
      + '<button type="button" class="ai365-ag-trow" data-ag-tool="' + E(id) + '" aria-expanded="' + (open ? 'true' : 'false') + '">'
      + '<span class="ic">' + (GROUP_ICON[grp] || IC.tool) + '</span>'
      + '<span class="lb" data-i18n-skip>' + E(call.label || call.tool || '') + '</span>'
      + '<span class="sm" data-i18n-skip>' + E((r && r.summary) || '') + '</span>'
      + (ds ? '<span class="ds" data-i18n-skip><b class="a">+' + ds.a + '</b> <b class="d">-' + ds.d + '</b></span>' : '')
      + '<span class="st ' + st + '" title="' + E(T(TOOL_STATE[st])) + '"></span>'
      + (r && r.duration_ms !== undefined && r.duration_ms !== null ? '<span class="du" data-i18n-skip>' + E(fmtDur(r.duration_ms)) + '</span>' : '')
      + '<span class="cv">' + IC.chevR + '</span></button>'
      + (open ? '<div class="ai365-ag-tbody">' + toolBody(c, st) + '</div>' : '')
      + '</div>';
  }
  // 결과의 task_id: 1차 = 백그라운드 명령 작업, 2차 = 서브에이전트 안의 호출(카드의 c.task 와 같다). 서브에이전트 안의 백그라운드 명령은
  // 서버가 제 작업 id 를 bg_task_id 로 옮긴다 → bg_task_id 먼저, 아니면 task_id 가 카드의 서브에이전트와 다를 때만 백그라운드
  // A result's task_id means a background command (phase 1) or a call inside a subagent (phase 2, equal to the card's c.task); inside a
  // subagent the server moves a background command's own id to bg_task_id → bg_task_id first, else task_id only when it differs
  function bgTask(c) {
    const r = c.result;
    if (!r) return '';
    if (r.bg_task_id) return String(r.bg_task_id);
    return r.task_id && String(r.task_id) !== String(c.task || '') ? String(r.task_id) : '';
  }
  function toolBody(c, st) {
    const call = c.call || {}, r = c.result, a = call.args || {}, bg = bgTask(c);
    let h = '';
    if (call.tool === 'bash') {
      const out = r ? (r.output || (r.ok === false ? r.detail : '') || '') : '';
      h += '<pre class="ai365-ag-out" data-i18n-skip><span class="pr">$ ' + E(a.command || '') + '</span>' + (out ? '\n' + E(out) : '') + '</pre>';
      const meta = [];
      if (r && r.exit_code !== undefined && r.exit_code !== null) meta.push('<span class="ex ' + (r.exit_code === 0 ? 'ok' : 'bad') + '" data-i18n-skip>exit ' + E(r.exit_code) + '</span>');
      if (bg) meta.push('<span>' + E(T('백그라운드 작업')) + ' <code data-i18n-skip>' + E(bg) + '</code></span>');
      if (r && r.truncated) meta.push('<span>' + E(T('출력이 길어 가운데를 줄였습니다')) + '</span>');
      if (r && r.ok !== false && !out && !bg) meta.push('<span>' + E(T('출력 없음')) + '</span>');
      if (meta.length) h += '<div class="ai365-ag-meta">' + meta.join('') + '</div>';
    } else if (r && r.diff && r.diff.unified) {
      h += '<div class="ai365-ag-fp" data-i18n-skip>' + IC.file + E(r.diff.path || a.path || '') + '</div>' + diffHtml(r.diff.unified);
      if (r.ok === false && r.detail) h += '<pre class="ai365-ag-out bad" data-i18n-skip>' + E(r.detail) + '</pre>';
    } else {
      const target = argsSummary(a);
      if (target) h += '<div class="ai365-ag-fp" data-i18n-skip>' + E(target) + '</div>';
      const body = r ? (r.detail || r.output || '') : '';
      if (body) h += '<pre class="ai365-ag-out' + (r.ok === false ? ' bad' : '') + '" data-i18n-skip>' + E(body) + '</pre>';
      if (r && r.truncated) h += '<div class="ai365-ag-note">' + E(T('내용이 길어 앞부분만 보여 줍니다')) + '</div>';
    }
    if (!r) h += '<div class="ai365-ag-note" data-ag-stnote>' + E(T(TOOL_STATE[st])) + '</div>';   // 상태가 바뀌면 제자리에서 / updated in place on a state change
    return h;
  }

  /* ── 서브에이전트(task) 카드 / subagent (task) cards ──
     접힌 줄 = 아이콘 · label · 프리셋 배지 · 결과 요약 · 자식 도구 수 · 상태 점 · 소요 시간, 펼치면 지시 내용 · 자식(.ai365-ag-sub) · 최종 글.
     The collapsed row: icon, label, preset badge, result summary, child tool count, state dot, duration; open: the prompt, the children (.ai365-ag-sub) and the final text. */
  function taskSub(cid) { const t = S.linkC[cid]; return t ? S.sub[t] : null; }
  function taskState(cid) {
    const c = S.calls[cid], sub = taskSub(cid);
    if (c.result) return c.result.ok === false ? 'fail' : 'ok';
    const waiting = sub && sub.items.some(function (it) { return it.k === 'tool' && S.calls[it.id] && !S.calls[it.id].result && pendingApprovalFor(it.id); });
    if (waiting) return 'wait';
    return isBusy() ? 'run' : 'stop';
  }
  function presetOf(cid) {
    const c = S.calls[cid], r = c.result, a = c.call.args || {}, cs = c.call.subagent || {};
    return String((r && r.subagent && r.subagent.preset) || cs.preset || a.preset || '');
  }
  function taskRowHtml(cid, st) {
    const c = S.calls[cid], call = c.call || {}, r = c.result, open = !!S.open[cid], sub = taskSub(cid);
    const n = sub ? sub.tools : ((r && r.subagent && r.subagent.steps) || 0), pr = presetOf(cid), en = isEn();
    const dur = r && r.subagent && r.subagent.duration_ms !== undefined && r.subagent.duration_ms !== null ? r.subagent.duration_ms : (r ? r.duration_ms : null);
    return '<button type="button" class="ai365-ag-trow" data-ag-tool="' + E(cid) + '" aria-expanded="' + (open ? 'true' : 'false') + '">'
      + '<span class="ic">' + IC.agent + '</span>'
      + '<span class="lb" data-i18n-skip>' + E(call.label || call.tool || '') + '</span>'
      + (pr ? '<span class="ai365-ag-pr ' + (/^(explorer|worker|reviewer)$/.test(pr) ? pr : '') + '" data-i18n-skip>' + E(pr) + '</span>' : '')
      + '<span class="sm" data-i18n-skip>' + E((r && r.summary) || '') + '</span>'
      + '<span class="tn" data-i18n-skip>' + E(en ? n + (n === 1 ? ' tool' : ' tools') : '도구 ' + n + '개') + '</span>'
      + '<span class="st ' + st + '" title="' + E(T(TOOL_STATE[st])) + '"></span>'
      + (dur !== undefined && dur !== null ? '<span class="du" data-i18n-skip>' + E(fmtDur(dur)) + '</span>' : '')
      + '<span class="cv">' + IC.chevR + '</span></button>';
  }
  function taskHtml(cid) {
    const c = S.calls[cid], r = c.result, a = c.call.args || {}, open = !!S.open[cid], st = taskState(cid), tid = S.linkC[cid] || '', sub = taskSub(cid);
    let body = '';
    if (open) {
      const kids = sub ? sub.items.map(subItemHtml).join('') : '';
      body = '<div class="ai365-ag-tbody">'
        + (a.prompt ? '<div class="ai365-ag-tlb">' + E(T('지시 내용')) + '</div><pre class="ai365-ag-out ai365-ag-tprompt" data-i18n-skip>' + E(a.prompt) + '</pre>' : '')
        + '<div class="ai365-ag-sub" data-sub="' + E(cid) + '">' + (kids || (r ? '' : '<div class="ai365-ag-note">' + E(T('아직 도구를 쓰지 않았습니다')) + '</div>')) + '</div>'
        + (r ? '<div class="ai365-ag-tlb">' + E(T('서브에이전트 결과')) + '</div><div class="ai365-ag-tres' + (r.ok === false ? ' bad' : '') + '" data-i18n-skip>' + md(r.detail || r.summary || '') + '</div>' : '')
        + '</div>';
    }
    return '<div class="ai365-ag-tool task' + (open ? ' open' : '') + '" data-call="' + E(cid) + '" data-state="' + st + '" data-tool="task"' + (tid ? ' data-tid="' + E(tid) + '"' : '') + '>'
      + taskRowHtml(cid, st) + body + '</div>';
  }
  // 서랍 행 → 그 task 카드로 스크롤하고 펼친다 / a drawer row → scroll to its task card and open it
  function openTaskCard(tid) {
    const cid = S.linkT[tid];
    if (!cid || !R.tx) return;
    if (S.viewer) closeViewer();
    if (!S.open[cid]) { S.open[cid] = true; repaintTool(cid); }
    const el = R.tx.querySelector('.ai365-ag-tool[data-call="' + cssq(cid) + '"]');
    if (!el || !R.scroll) return;
    R.scroll.scrollTop += el.getBoundingClientRect().top - R.scroll.getBoundingClientRect().top - 16;
    el.classList.remove('ai365-ag-ring'); void el.offsetWidth; el.classList.add('ai365-ag-ring');
  }

  function apprHtml(aid) {
    const a = S.approvals[aid] || {}, dec = a.decision || 'pending', pend = dec === 'pending';
    const budget = a.reason === 'budget' || a.tool === 'continue', busyDec = S.deciding[aid] || '';
    const title = budget ? T('계속할까요?') : (a.label || a.tool || T('승인이 필요합니다'));
    let h = '<div class="ai365-ag-approval' + (pend ? '' : ' done') + '" data-aid="' + E(aid) + '" data-dec="' + E(dec) + '" data-reason="' + E(a.reason || '') + '">'
      + '<div class="hd"><span class="ic">' + (budget ? IC.clock : IC.shield) + '</span><b' + (budget ? '' : ' data-i18n-skip') + ' title="' + E(title) + '">' + E(title) + '</b></div>'
      + '<div class="rs">' + E(T(REASON[a.reason] || '승인이 필요합니다')) + '</div>';
    const sum = budget ? '' : argsSummary(a.args);
    if (sum) h += '<div class="ar" data-i18n-skip>' + E(sum) + '</div>';
    if (pend) {
      // 범위가 있으면 라벨 전체를 한 span 으로(버튼의 flex 간격이 괄호 사이에 끼지 않게), 명령 · 도구 이름만 고정폭 글꼴
      // With a scope the whole label is one span (so the button's flex gap stays out of the parentheses); only commands and tool names are monospace
      const b = function (d, label, cls, scope, code) {
        return '<button type="button" class="ai365-ag-btn' + (cls ? ' ' + cls : '') + '" data-ag-dec="' + d + '"' + (busyDec ? ' disabled' : '') + '>'
          + (busyDec === d ? '<span class="ai365-ag-spin sm"></span>' : '')
          + (scope ? '<span>' + E(T(label)) + ' (<span class="sc' + (code ? ' code' : '') + '" data-i18n-skip title="' + E(scope) + '">' + E(scope) + '</span>)</span>' : E(T(label)))
          + '</button>';
      };
      // '항상 허용'은 규칙이 실제로 건너뛸 수 있는 묻기 모드 승인에만 둔다(폴더 밖 · 차단 명령은 규칙이 있어도 늘 묻는다, 계약 C)
      // 'Always allow' only on ask-mode approvals, the only ones a rule can skip (outside paths and denied commands always ask, contract C)
      // 2차: mcp_action 도 커넥터 규칙으로 건너뛴다(계약 2 C) / phase 2: mcp_action is skipped by a connector rule too (contract 2 C)
      // 2026-10-19: 서버가 실어 준 규칙(payload.rule)의 범위를 버튼에 붙인다(예: 이 세션에서 항상 허용 (python …))
      // 2026-10-19: the button names the scope of the rule the server sent (payload.rule), e.g. Always allow in this session (python …)
      const always = a.reason === 'ask_mode' || a.reason === 'auto_cmd' || a.reason === 'mcp_action';   // auto_cmd 도 규칙으로 건너뛸 수 있다 / auto_cmd can be skipped by a rule too
      h += '<div class="acts">' + b('allow', budget ? '계속' : '허용', 'pri') + b('deny', budget ? '멈추기' : '거부')
        + (always ? b('always', '이 세션에서 항상 허용', '', ruleScope(a.rule), !!(a.rule && a.rule.tool !== 'mcp_tool')) : '') + '</div>';
    } else {
      const label = budget ? (dec === 'deny' ? '멈춤' : '계속함') : ({ allow: '허용함', deny: '거부함', always: '이 세션에서 항상 허용함' }[dec] || dec);
      h += '<div class="res ' + E(dec) + '">' + (dec === 'deny' ? IC.x : IC.check) + '<span>' + E(T(label)) + '</span>'
        + (a.decided_at ? '<span class="at" data-i18n-skip>' + E(hm(a.decided_at)) + '</span>' : '') + '</div>';
    }
    return h + '</div>';
  }
  // 규칙의 범위 글: bash = prefix + ' …', mcp_tool = 커넥터 이름(모르면 id), 그 밖 = 도구 이름. 규칙이 없거나 비면 ''
  // The rule's scope text: bash = its prefix plus ' …', mcp_tool = the connector name (its id when unknown), others = the tool name; '' without a rule
  function ruleScope(r) {
    if (!r || typeof r !== 'object' || !r.tool) return '';
    if (r.tool === 'bash') return r.prefix ? String(r.prefix) + ' …' : '';
    if (r.tool === 'mcp_tool') {
      const id = String(r.connector || '');
      if (!id) return '';
      const c = ((S.conns && S.conns.list) || []).filter(function (x) { return String(x.id) === id; })[0];
      return (c && c.name) ? String(c.name) : id;
    }
    return String(r.tool);
  }

  function sumHtml(p) {
    const en = isEn(), parts = [];
    if (p.steps !== undefined && p.steps !== null) parts.push(en ? p.steps + (Number(p.steps) === 1 ? ' step' : ' steps') : p.steps + '스텝');
    if (p.duration_ms !== undefined && p.duration_ms !== null) parts.push(fmtDur(p.duration_ms));
    const tk = fmtTokens(p.tokens_est);
    if (tk) parts.push(en ? '~' + tk + ' tokens' : '토큰 약 ' + tk);
    return '<div class="ai365-ag-sum" data-i18n-skip' + (p.text ? ' title="' + E(p.text) + '"' : '') + '>' + IC.check + '<span>' + E(T('완료')) + '</span>'
      + parts.map(function (x) { return '<span class="sep">·</span><span>' + E(x) + '</span>'; }).join('') + '</div>';
  }

  function paintStatus() {
    if (!R.status) return;
    const st = S.cur && S.cur.status;
    if (!BUSY[st]) { R.status.hidden = true; R.status.className = 'ai365-ag-status'; R.status.innerHTML = ''; return; }
    const p = S.lastStatus || {}, waiting = st === 'waiting';
    const budget = waiting && Object.keys(S.approvals).some(function (k) { const a = S.approvals[k]; return (a.decision || 'pending') === 'pending' && (a.reason === 'budget' || a.tool === 'continue'); });
    const note = !waiting && p.state === 'running' && p.note ? String(p.note) : '';
    const text = waiting ? T(budget ? '계속할지 기다리는 중' : '승인을 기다리는 중') : (note || T('작업 중…'));
    const step = !waiting && p.state === 'running' && p.step ? (isEn() ? 'Step ' : '스텝 ') + p.step : '';
    R.status.hidden = false;
    R.status.className = 'ai365-ag-status ' + st;
    R.status.innerHTML = '<span class="ai365-ag-spin" aria-hidden="true"></span><span class="tx"' + (note ? ' data-i18n-skip' : '') + '>' + E(text) + '</span>'
      + (step ? '<span class="stp" data-i18n-skip>' + E(step) + '</span>' : '');
  }

  function syncComposer() {
    if (!R.input) return;
    const cur = S.cur, busy = isBusy(), off = !cur || S.sessLoading || !!S.sessErr;
    R.foot.hidden = !cur;
    R.send.hidden = busy;
    R.stop.hidden = !busy;
    R.send.disabled = off || S.sending || !R.input.value.trim();
    R.stop.disabled = S.stopping;
    R.send.title = T('보내기'); R.send.setAttribute('aria-label', T('보내기'));
    R.stop.title = T('중단'); R.stop.setAttribute('aria-label', T('중단'));
    // 2차 서버는 실행 중 글을 다음 단계 사이에 끼워 넣는다(mode steer), 1차는 대기열 / a phase-2 server steers a message sent while running, phase 1 queues it
    R.input.placeholder = T(busy ? (v2() ? '실행 중에도 보낼 수 있습니다. 다음 단계 사이에 끼워 넣습니다' : '실행 중에도 보낼 수 있습니다. 지금 작업이 끝나면 이어서 처리합니다') : '에이전트에게 맡길 작업을 적어 주세요');
    R.input.disabled = off;
    R.shell.classList.toggle('busy', busy);   // 실행 중엔 ⟲ 되돌리기를 숨긴다 / hides the restore buttons while running
    setOptions(R.perm, permOpts((cur && cur.perm_mode) || 'auto'));
    R.perm.value = (cur && cur.perm_mode) || 'auto';
    R.perm.classList.toggle('plan', R.perm.value === 'plan');
    R.perm.title = T('권한 모드'); R.perm.setAttribute('aria-label', T('권한 모드'));
    setOptions(R.model, modelOpts(cur && cur.model));
    R.model.value = (cur && cur.model) || (S.models[0] && S.models[0].id) || '';
    R.model.title = T('모델'); R.model.setAttribute('aria-label', T('모델'));
    R.perm.disabled = R.model.disabled = off;
    paintQueue();
  }
  // 바뀐 때만 옵션을 다시 쓴다(열린 목록이 닫히지 않게) / rewrite options only when they change, so an open list stays open
  function setOptions(sel, html) { if (sel && sel.__agOpts !== html) { sel.innerHTML = html; sel.__agOpts = html; } }
  // 플랜(2차)은 2차 서버에서만(또는 이미 plan 일 때) / plan (phase 2) only on a phase-2 server, or when the mode already is plan
  function permOpts(cur) {
    const modes = (v2() || cur === 'plan') ? ['auto', 'ask', 'plan'] : ['auto', 'ask'];
    return modes.map(function (v) { return '<option value="' + v + '"' + (v === cur ? ' selected' : '') + '>' + (v === 'auto' ? 'Auto' : E(T(PERM_LABEL[v]))) + '</option>'; }).join('');
  }
  function modelOpts(cur) {
    const list = S.models.slice();
    if (cur && !list.some(function (m) { return m.id === cur; })) list.push({ id: cur, label: cur });
    return list.map(function (m) { return '<option value="' + E(m.id) + '"' + (m.id === cur ? ' selected' : '') + '>' + E(m.label || m.id) + '</option>'; }).join('');
  }
  function paintQueue() {
    if (!R.queue) return;
    R.queue.hidden = !S.queue.length;
    R.queue.innerHTML = S.queue.map(function (t) { return '<div class="ai365-ag-qi"><span class="b">' + E(T('대기 중')) + '</span><span class="t" data-i18n-skip title="' + E(t) + '">' + E(t) + '</span></div>'; }).join('');
  }

  /* ── 환경 패널 / environment panel ── */
  // 내 컴퓨터 폴더 세션은 Changes(git) · Terminal(명령)을 숨긴다(계약 F4) / browser-folder sessions hide Changes (git) and Terminal (commands), contract F4
  const FS_HIDE = { changes: true, term: true };
  function shownSections() { const two = v2(), br = isBrowser(); return SECTIONS.filter(function (x) { return (!x.v2 || two) && !(br && FS_HIDE[x.key]); }); }
  function renderEnv() {
    if (!R.env) return;
    R.shell.classList.toggle('noenv', !S.env);
    R.env.innerHTML = shownSections().map(secHtml).join('');
  }
  // 머리줄 숫자: 서랍 = 실행 중 작업 수, Connectors = 고른 수, Changes = 바뀐 파일 수, Outputs = 파일 수 / header counts: running tasks, checked connectors, changed files, outputs
  function secCount(key) {
    if (key === 'tasks') return S.tasks.filter(function (t) { return t.status === 'running'; }).length;
    if (key === 'connectors') { const sh = connShown(); return connSel().filter(function (id) { return sh[id]; }).length; }   // 보이는 목록 ∩ 세션(적대 검토 L9) / visible list ∩ session (review L9)
    if (key === 'changes') { const d = S.changes && S.changes.data; return d && d.repo ? (Number(d.count) || (d.files || []).length) : 0; }
    if (key === 'outputs') return (S.outputs && S.outputs.list) ? S.outputs.list.length : 0;
    return 0;
  }
  function secHtml(sec) {
    const shut = !!S.shut[sec.key], n = secCount(sec.key);
    return '<section class="ai365-ag-sec ' + sec.cls + (shut ? ' shut' : '') + '" data-sec="' + sec.key + '">'
      + '<button type="button" class="ai365-ag-sech" data-ag-sec="' + sec.key + '" aria-expanded="' + (shut ? 'false' : 'true') + '"><span data-i18n-skip>' + sec.title + '</span>'
      + (n ? '<span class="cnt" data-i18n-skip>' + n + '</span>' : '') + '<span class="cv">' + IC.chev + '</span></button>'
      + '<div class="ai365-ag-secb">' + secBody(sec.key) + '</div></section>';
  }
  // 섹션을 다시 그려도 안쪽 목록의 스크롤은 지킨다(적대 검토 L7) / a section repaint keeps its inner lists' scroll (review L7)
  const SCROLLERS = '.ai365-ag-ftree,.ai365-ag-chl,.ai365-ag-olist,.ai365-ag-tlist,.ai365-ag-clist,.ai365-ag-out';
  function paintSec(key) {
    if (!R.env) return;
    const el = R.env.querySelector('[data-sec="' + key + '"]'), sec = SECTIONS.filter(function (x) { return x.key === key; })[0];
    if (!el || !sec) return;
    const marks = [];
    el.querySelectorAll(SCROLLERS).forEach(function (x, i) { if (x.scrollTop) marks.push([i, x.scrollTop]); });
    el.outerHTML = secHtml(sec);
    if (!marks.length) return;
    const now = R.env.querySelector('[data-sec="' + key + '"]'), list = now ? now.querySelectorAll(SCROLLERS) : [];
    marks.forEach(function (m) { if (list[m[0]]) list[m[0]].scrollTop = m[1]; });
  }
  function none(ko) { return '<div class="ai365-ag-none">' + E(T(ko)) + '</div>'; }
  function secBody(key) {
    const c = S.cur;
    if (!c) return none('세션을 고르면 여기에 표시됩니다');
    if (key === 'env') {
      const extra = c.extra_folders || [], g = S.git;
      const kv = function (k, v) { return '<dt>' + E(T(k)) + '</dt><dd>' + v + '</dd>'; };
      if (isBrowser(c)) {   // 호스트 = 내 컴퓨터(브라우저), 작업 폴더 = 이름 + 연결 상태, 추가 폴더 · 브랜치 없음(계약 F4) / host, folder name with its state; no extra folders or branch
        const st = fsStateLabel();
        return '<dl class="ai365-ag-kv">'
          + kv('호스트', '<span>' + E(T('내 컴퓨터(브라우저)')) + '</span>')
          + kv('작업 폴더', '<span data-i18n-skip title="' + E(c.folder || '') + '">' + E(c.folder || '-') + '</span>'
            + (st ? '<span class="ai365-ag-fsst ' + st[0] + '" data-ag-fsst="' + st[0] + '">' + E(T(st[1])) + '</span>' : ''))
          + '</dl>';
      }
      return '<dl class="ai365-ag-kv">'
        + kv('호스트', '<span data-i18n-skip>' + E(S.host || '-') + '</span>')
        + kv('작업 폴더', '<span data-i18n-skip title="' + E(c.folder || '') + '">' + pathHtml(c.folder || '-') + '</span>')
        + kv('추가 폴더', extra.length ? extra.map(function (f) { return '<span class="ln" data-i18n-skip>' + pathHtml(f) + '</span>'; }).join('') : '<span class="mu">' + E(T('없음')) + '</span>')
        + kv('브랜치', !g ? '<span class="mu" data-i18n-skip>-</span>' : (g.repo ? '<span class="br" data-i18n-skip>' + IC.branch + E(g.branch || 'HEAD') + '</span>' : '<span class="mu">' + E(T('git 저장소 아님')) + '</span>'))
        + '</dl>';
    }
    if (key === 'ctx') {
      const pct = Math.max(0, Math.min(100, Math.round(Number(c.context_pct) || 0)));
      return '<div class="ai365-ag-ctx' + (pct >= 80 ? ' hi' : (pct >= 60 ? ' mid' : '')) + '"><div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + pct + '" aria-label="' + E(T('컨텍스트 사용률')) + '"><i style="width:' + pct + '%"></i></div>'
        + '<span class="v" data-ag-ctx="' + pct + '" data-i18n-skip>' + (pct === 0 && S.lastSeq > 0 ? '<1%' : pct + '%') + '</span></div><div class="ai365-ag-mu">' + E(T('컨텍스트 사용률')) + '</div>';
    }
    if (key === 'files') {
      if (!S.tree) return none(S.sessLoading ? '불러오는 중…' : '세션을 고르면 여기에 표시됩니다');
      if (S.tree.browser && !fsReady()) {   // 핸들 · 권한이 없으면 연결 상태만 / without a handle or permission, only the state
        const st = fsStateLabel();
        return '<div class="ai365-ag-ftree" role="tree">' + dirHtml(S.tree.root, 0, true, true)
          + '<div class="ai365-ag-fnote" style="padding-left:6px">' + E(T(st ? st[1] : '불러오는 중…')) + '</div></div>';
      }
      return '<div class="ai365-ag-ftree" role="tree">' + dirHtml(S.tree.root, 0, true) + '</div>';
    }
    if (key === 'term') {   // 서브에이전트 안의 명령도 포함 / commands inside subagents included
      const ids = S.bash.filter(function (id) { return !!S.calls[id]; });
      if (!ids.length) return none('이 세션에서 실행한 명령이 없습니다');
      return '<div class="ai365-ag-tlist">' + ids.slice(-30).map(termRow).join('') + '</div>';
    }
    if (key === 'tasks') {
      // 백그라운드 명령은 실행 중만(1차), 서브에이전트는 상태와 함께 최근 20개(2차) / background commands while running (phase 1), subagents with their status, latest 20 (phase 2)
      const run = S.tasks.filter(function (t) { return t.status === 'running' && t.kind !== 'subagent'; });
      const subs = S.tasks.filter(function (t) { return t.kind === 'subagent'; }).sort(function (a, b) {
        if ((a.status === 'running') !== (b.status === 'running')) return a.status === 'running' ? -1 : 1;
        return String(b.started || '').localeCompare(String(a.started || ''));
      }).slice(0, SUB_ROWS);
      if (!run.length && !subs.length) return none('실행 중인 작업이 없습니다');
      return run.map(function (t) {
        return '<div class="ai365-ag-task" data-ag-task="' + E(t.id) + '"><span class="st run"></span><span class="lb" data-i18n-skip title="' + E(t.label || '') + '">' + E(t.label || t.kind || t.id)
          + '</span><span class="du" data-i18n-skip>' + E(ago(t.started)) + '</span></div>';
      }).join('') + subs.map(function (t) {
        const st = TASK_ST[t.status] || 'stop';
        return '<button type="button" class="ai365-ag-task sub" data-ag-task="' + E(t.id) + '" data-kind="subagent" title="' + E(t.label || '') + '"><span class="st ' + st + '"></span>'
          + '<span class="ic">' + IC.agent + '</span><span class="lb" data-i18n-skip>' + E(t.label || t.id) + '</span><span class="du" data-i18n-skip>' + E(ago(t.ended || t.started)) + '</span></button>';
      }).join('');
    }
    if (key === 'connectors') return connBody();
    if (key === 'changes') return changesBody();
    if (key === 'outputs') return outputsBody();
    return '';
  }
  // Connectors: 관리 센터 MCP 도구 중 이 세션이 쓸 것. 세션에 있는데 목록에 없는 id(지웠거나 끈 도구)는 '사용할 수 없음' 줄로 보이고
  // 다른 체크를 바꿔도 PATCH 에서 빠지지 않는다(적대 검토 L9) / the Admin Center MCP tools this session may use; session ids missing from the
  // list (removed or turned off) show as 'Unavailable' rows and stay in the PATCH when other boxes change (review L9)
  function connSel() { return ((S.cur && Array.isArray(S.cur.connectors)) ? S.cur.connectors : []).map(String); }
  function connShown() { const sh = {}; ((S.conns && S.conns.list) || []).forEach(function (c) { sh[String(c.id)] = true; }); return sh; }
  function connBody() {
    const cs = S.conns;
    if (!cs || (cs.loading && !cs.list)) return none('불러오는 중…');
    if (!cs.list) return '<div class="ai365-ag-none" data-i18n-skip>' + E(cs.err || T('연결 도구를 불러오지 못했습니다')) + '</div>';
    const on = {}, sh = connShown(), missing = connSel().filter(function (id) { return !sh[id]; });
    connSel().forEach(function (id) { on[id] = true; });
    const rows = cs.list.map(function (c) {
      const id = String(c.id), act = c.kind === 'action';
      return '<label class="ai365-ag-conn" title="' + E(c.description || '') + '"><input type="checkbox" data-ag-conn="' + E(id) + '"' + (on[id] ? ' checked' : '') + (S.connBusy ? ' disabled' : '') + '>'
        + '<span class="tx"><span class="nm" data-i18n-skip>' + E(c.name || id) + '</span><span class="ai365-ag-kd' + (act ? ' action' : '') + '">' + E(T(act ? '외부 실행' : '읽기 전용')) + '</span>'
        + (c.server_name || c.tool ? '<span class="sv" data-i18n-skip>' + E([c.server_name, c.tool].filter(Boolean).join(' · ')) + '</span>' : '') + '</span></label>';
    }).concat(missing.map(function (id) {
      return '<div class="ai365-ag-conn gone" data-ag-conn-missing="' + E(id) + '" title="' + E(T('관리 센터에서 지웠거나 끈 도구입니다. 이 세션 설정에는 그대로 남겨 둡니다')) + '">'
        + '<input type="checkbox" checked disabled aria-hidden="true"><span class="tx"><span class="nm" data-i18n-skip>' + E(id) + '</span>'
        + '<span class="ai365-ag-kd gone">' + E(T('사용할 수 없음')) + '</span></span></div>';
    })).join('');
    return (cs.list.length ? '' : none('관리 센터 › API · MCP 연결에 등록된 MCP 도구가 없습니다'))
      + (rows ? '<div class="ai365-ag-clist">' + rows + '</div>' : '')
      + (cs.list.length ? '<div class="ai365-ag-mu">' + E(T('고른 도구만 이 세션의 에이전트가 씁니다')) + '</div>' : '');
  }
  function plusMinus(a, d) { return '<b class="a">+' + E(Number(a) || 0) + '</b> <b class="d">−' + E(Number(d) || 0) + '</b>'; }
  // Changes: HEAD 대비 바뀐 파일 · diff 보기 · 체크포인트 · 커밋(실행 중엔 버튼 비활성) / files changed since HEAD, diff view, checkpoint and commit (buttons disabled while running)
  function changesBody() {
    const ch = S.changes;
    if (!ch || (ch.loading && !ch.data)) return none('불러오는 중…');
    if (!ch.data) return '<div class="ai365-ag-none" data-i18n-skip>' + E(ch.err || T('변경 사항을 불러오지 못했습니다')) + '</div>';
    const d = ch.data;
    if (!d.repo) return none('git 저장소가 아닙니다');
    const files = Array.isArray(d.files) ? d.files : [], en = isEn(), busy = isBusy();
    const cnt = Number(d.count) || files.length;
    let h = '<div class="ai365-ag-chs"><span class="br" data-i18n-skip>' + IC.branch + E(d.branch || 'HEAD') + '</span>'
      + (files.length ? '<span data-i18n-skip>· ' + E(en ? cnt + (cnt === 1 ? ' file' : ' files') : '파일 ' + cnt + '개') + ' · </span><span data-i18n-skip>' + plusMinus(d.added, d.removed) + '</span>' : '') + '</div>';
    if (!files.length) h += none('변경 사항이 없습니다');
    else {
      const sel = S.viewer && S.viewer.kind === 'diff' ? S.viewer.path : null;
      h += '<div class="ai365-ag-chl">' + files.slice(0, LIST_CAP).map(function (f) {
        const st = String(f.status || 'M'), p = String(f.path || '');
        return '<button type="button" class="ai365-ag-chf' + (sel === p ? ' on' : '') + '" data-ag-change="' + E(p) + '" title="' + E(p) + '">'
          + '<span class="ai365-ag-cs ' + (CHANGE_CLS[st] || '') + '" data-i18n-skip>' + E(st) + '</span><span class="nm" data-i18n-skip>' + E(p) + '</span>'
          + (f.binary ? '<span class="bn">' + E(T('이진')) + '</span>' : '<span class="ds" data-i18n-skip>' + plusMinus(f.added, f.removed) + '</span>') + '</button>';
      }).join('') + (files.length > LIST_CAP ? '<div class="ai365-ag-fnote" data-i18n-skip>+' + (files.length - LIST_CAP) + '</div>' : '') + '</div>';
      if (d.truncated) h += '<div class="ai365-ag-mu">' + E(T('내용이 길어 앞부분만 보여 줍니다')) + '</div>';   // 서버가 목록을 줄였다 / the server cut the list
    }
    const lc = d.last_checkpoint;
    if (lc) h += '<div class="ai365-ag-mu">' + E(T('마지막 체크포인트')) + ' · <span data-i18n-skip>' + E([lc.label, ago(lc.ts)].filter(Boolean).join(' · ')) + '</span></div>';
    const tip = busy ? ' title="' + E(T('실행 중에는 쓸 수 없습니다')) + '"' : '';
    h += '<div class="ai365-ag-acts2"><button type="button" class="ai365-ag-btn sm" data-ag="checkpoint"' + (busy || S.cpBusy ? ' disabled' : '') + tip + '>' + IC.flag + E(T('체크포인트 만들기')) + '</button>'
      + '<button type="button" class="ai365-ag-btn sm" data-ag="commit"' + (busy || !files.length ? ' disabled' : '') + tip + '>' + IC.commit + E(T('커밋')) + '</button></div>';
    return h;
  }
  // Outputs: 이 세션이 만들거나 고친 파일 · 미리보기 · 내려받기 / files this session created or modified: preview and download
  function outputsBody() {
    const o = S.outputs;
    if (!o || (o.loading && !o.list)) return none('불러오는 중…');
    if (!o.list) return '<div class="ai365-ag-none" data-i18n-skip>' + E(o.err || T('산출물을 불러오지 못했습니다')) + '</div>';
    if (!o.list.length) return none('이 세션이 만든 파일이 없습니다');
    const sid = S.cur ? S.cur.id : '', br = isBrowser();   // 내 컴퓨터 폴더는 목록만(파일은 그 컴퓨터에 있다, 계약 F4) / browser folders list only (the files are on that computer)
    return '<div class="ai365-ag-olist">' + o.list.slice(0, LIST_CAP).map(function (f) {
      const p = String(f.path || ''), gone = f.exists === false, kind = f.kind === 'modified' ? 'modified' : 'created';
      const href = sessUrl(sid, '/outputs/download') + qs({ path: p });
      return '<div class="ai365-ag-orow' + (gone ? ' gone' : '') + '">'
        + '<button type="button" class="ai365-ag-ofile" data-ag-output="' + E(p) + '" title="' + E(p) + '"' + (gone ? ' disabled' : '') + '>' + IC.file
        + '<span class="nm" data-i18n-skip>' + E(baseName(f.rel || p) || p) + '</span>'
        + '<span class="ai365-ag-kb ' + (gone ? 'gone' : kind) + '">' + E(T(gone ? '지워짐' : (kind === 'modified' ? '수정됨' : '새로 만듦'))) + '</span>'
        + (f.bytes !== undefined && f.bytes !== null ? '<span class="sz" data-i18n-skip>' + E(fmtSize(f.bytes)) + '</span>' : '')
        + '<span class="tm" data-i18n-skip>' + E(ago(f.ts)) + '</span></button>'
        + (gone || br ? '' : '<a class="ai365-ag-dl" data-ag-dl="' + E(p) + '" href="' + E(href) + '" target="_blank" rel="noopener" title="' + E(T('내려받기')) + '" aria-label="' + E(T('내려받기')) + '">' + IC.download + '</a>')
        + '</div>';
    }).join('') + '</div>';
  }
  function termRow(id) {
    const c = S.calls[id], a = c.call.args || {}, r = c.result, st = toolState(c), open = !!S.termOpen[id], bg = bgTask(c);
    const out = r ? (bg && !r.output ? T('백그라운드 작업') + ' ' + bg : (r.output || (r.ok === false ? r.detail : '') || '')) : '';
    return '<div class="ai365-ag-titem' + (open ? ' open' : '') + '" data-ag-term="' + E(id) + '">'
      + '<button type="button" class="ai365-ag-tih" data-ag-termt="' + E(id) + '" aria-expanded="' + (open ? 'true' : 'false') + '"><span class="st ' + st + '"></span>'
      + '<span class="cmd" data-i18n-skip title="' + E(a.command || '') + '">$ ' + E(a.command || c.call.label || '') + '</span>'
      + (r && r.exit_code !== undefined && r.exit_code !== null ? '<span class="ex ' + (r.exit_code === 0 ? 'ok' : 'bad') + '" data-i18n-skip>exit ' + E(r.exit_code) + '</span>' : '')
      + (r && r.duration_ms !== undefined && r.duration_ms !== null ? '<span class="du" data-i18n-skip>' + E(fmtDur(r.duration_ms)) + '</span>' : '') + '</button>'
      + (open ? '<pre class="ai365-ag-out" data-i18n-skip' + (!r && !out ? ' data-ag-stnote' : '') + '>' + E(out || T(r ? '출력 없음' : TOOL_STATE[st])) + '</pre>' : '') + '</div>';
  }

  /* ── 파일 트리(지연 로딩) · 파일 보기 / file tree (lazy) and file viewer ── */
  function sortEntries(list) {
    return (list || []).slice().sort(function (a, b) {
      if ((a.type === 'dir') !== (b.type === 'dir')) return a.type === 'dir' ? -1 : 1;
      return String(a.name).localeCompare(String(b.name), undefined, { sensitivity: 'base' });
    });
  }
  // 내 컴퓨터 폴더 트리는 폴더 기준 상대 경로('/' 구분), 뿌리 라벨 = 폴더 이름(계약 F4) / a browser-folder tree uses folder-relative '/' paths; the root label is the folder name
  function treePath(dir, name) { return S.tree && S.tree.browser ? (dir ? dir + '/' + name : name) : joinPath(dir, name); }
  function dirHtml(path, depth, isRoot, labelOnly) {
    const n = S.tree.nodes[path] || {}, open = isRoot || !!S.tree.open[path];
    const rootName = S.tree.browser ? ((S.cur && S.cur.folder) || '') : (baseName(path) || path);
    let h = isRoot ? '<div class="ai365-ag-froot" title="' + E(S.tree.browser ? rootName : path) + '">' + (S.tree.browser ? IC.laptop : IC.folder) + '<b data-i18n-skip>' + E(rootName) + '</b></div>' : '';
    if (!open || labelOnly) return h;
    const pad = 'padding-left:' + (6 + depth * 14) + 'px';
    if (n.err && !n.entries) return h + '<div class="ai365-ag-fnote bad" style="' + pad + '" data-i18n-skip>' + E(n.err) + '</div>';
    if (!n.entries) return h + '<div class="ai365-ag-fnote" style="' + pad + '">' + E(T('불러오는 중…')) + '</div>';
    if (!n.entries.length) return h + '<div class="ai365-ag-fnote" style="' + pad + '">' + E(T('빈 폴더')) + '</div>';
    n.entries.forEach(function (en) {
      const p = treePath(path, en.name);
      if (en.type === 'dir') {
        const o = !!S.tree.open[p];
        h += '<button type="button" class="ai365-ag-fnode dir' + (o ? ' open' : '') + '" data-ag-dir="' + E(p) + '" style="' + pad + '" role="treeitem" aria-expanded="' + (o ? 'true' : 'false') + '" title="' + E(p) + '">'
          + '<span class="cv">' + IC.chevR + '</span>' + IC.folder + '<span class="nm" data-i18n-skip>' + E(en.name) + '</span></button>';
        if (o) h += dirHtml(p, depth + 1, false);
      } else {
        h += '<button type="button" class="ai365-ag-fnode file' + (S.viewer && S.viewer.kind !== 'diff' && S.viewer.path === p ? ' on' : '') + '" data-ag-file="' + E(p) + '" style="' + pad + '" role="treeitem" title="' + E(p) + '">'
          + '<span class="cv"></span>' + IC.file + '<span class="nm" data-i18n-skip>' + E(en.name) + '</span>'
          + (en.size !== undefined && en.size !== null ? '<span class="sz" data-i18n-skip>' + E(fmtSize(en.size)) + '</span>' : '') + '</button>';
      }
    });
    return h;
  }
  // refresh = 지금 목록을 둔 채 조용히 다시 읽기(턴이 끝난 뒤) / refresh = re-read quietly, keeping the current entries (after a turn)
  function loadDir(path, refresh) {
    if (!S.tree || !S.cur) return;
    const n = S.tree.nodes[path] || (S.tree.nodes[path] = { entries: null, err: '', loading: false });
    if (n.loading || (n.entries && !refresh)) return;
    if (S.tree.browser) { fsLoadDir(path, n); return; }   // 내 컴퓨터 폴더 = 핸들에서(서버 /files 는 409) / browser folders read the handle (the server's /files answers 409)
    n.loading = true;
    if (!n.entries) paintSec('files');
    const tok = S.openTok, sid = S.cur.id;
    api(sessUrl(sid, '/files') + qs({ path: path })).then(function (d) {
      if (tok !== S.openTok || !S.tree) return;
      n.loading = false;
      if (d && d.kind === 'dir') { n.entries = sortEntries(d.entries); n.err = ''; } else { n.entries = n.entries || []; n.err = T('폴더가 아닙니다'); }
      paintSec('files');
    }).catch(function (err) {
      if (tok !== S.openTok || !S.tree) return;
      n.loading = false;
      if (!n.entries) n.err = err.message || T('폴더를 불러오지 못했습니다');
      paintSec('files');
    });
  }
  function refreshTree() {
    if (!S.tree) return;
    Object.keys(S.tree.nodes).forEach(function (p) { if (p === S.tree.root || S.tree.open[p]) loadDir(p, true); else delete S.tree.nodes[p]; });
  }
  function openFile(path, quiet) {
    if (!S.cur) return;
    if (isBrowser()) { fsOpenFile(path, quiet); return; }   // 내 컴퓨터 폴더 = 핸들에서 / browser folders read the handle
    const tok = S.openTok, sid = S.cur.id;
    if (!quiet) { S.viewer = { path: path, loading: true, data: null, err: '' }; paintViewer(); renderHead(); paintSec('files'); }
    api(sessUrl(sid, '/files') + qs({ path: path })).then(function (d) {
      if (tok !== S.openTok || !S.viewer || S.viewer.path !== path) return;
      if (d && d.kind === 'dir') { S.viewer = null; S.tree.open[path] = true; loadDir(path); paintViewer(); renderHead(); paintSec('files'); return; }
      S.viewer.loading = false; S.viewer.err = ''; S.viewer.data = d || {};
      paintViewer();
    }).catch(function (err) {
      if (tok !== S.openTok || !S.viewer || S.viewer.path !== path) return;
      if (quiet && S.viewer.data) return;
      S.viewer.loading = false; S.viewer.err = err.message || T('파일을 불러오지 못했습니다');
      paintViewer();
    });
  }
  function refreshViewer() { if (S.viewer && !S.viewer.loading) { if (S.viewer.kind === 'diff') openDiff(S.viewer.path, true); else openFile(S.viewer.path, true); } }
  // Changes 의 파일 → 가운데 뷰어에 diff(1차 diffHtml 재사용) / a Changes file → its diff in the centre viewer (phase-1 diffHtml reused)
  function openDiff(path, quiet) {
    if (!S.cur) return;
    const tok = S.openTok, sid = S.cur.id;
    if (!quiet) { S.viewer = { kind: 'diff', path: path, loading: true, data: null, err: '' }; paintViewer(); renderHead(); paintSec('files'); paintSec('changes'); }
    api(sessUrl(sid, '/changes/diff') + qs({ path: path })).then(function (d) {
      if (tok !== S.openTok || !S.viewer || S.viewer.kind !== 'diff' || S.viewer.path !== path) return;
      S.viewer.loading = false; S.viewer.err = ''; S.viewer.data = d || {};
      paintViewer();
    }).catch(function (err) {
      if (tok !== S.openTok || !S.viewer || S.viewer.kind !== 'diff' || S.viewer.path !== path) return;
      if (quiet && S.viewer.data) return;
      S.viewer.loading = false; S.viewer.err = err.message || T('변경을 불러오지 못했습니다');
      paintViewer();
    });
  }
  function closeViewer() {
    if (!S.viewer) return;
    const wasDiff = S.viewer.kind === 'diff';
    S.viewer = null;
    paintViewer(); renderHead(); paintSec('files');
    if (wasDiff) paintSec('changes');
  }
  function paintViewer() {
    if (!R.viewer) return;
    const v = S.viewer;
    R.viewer.hidden = !v;
    R.scroll.hidden = !!v;
    if (!v) { R.viewer.innerHTML = ''; R.viewer.removeAttribute('data-path'); R.viewer.removeAttribute('data-kind'); return; }
    const d = v.data || {};
    let body;
    if (v.loading) body = '<div class="ai365-ag-vnote">' + E(T('불러오는 중…')) + '</div>';
    else if (v.err) body = '<div class="ai365-ag-vnote bad" data-i18n-skip>' + E(v.err) + '</div>';
    else if (v.kind === 'diff') {
      if (d.binary) body = '<div class="ai365-ag-vnote">' + E(T('이진 파일이라 비교할 수 없습니다')) + '</div>';
      else if (!d.unified) body = '<div class="ai365-ag-vnote">' + E(T('표시할 변경이 없습니다')) + '</div>';
      else body = (d.truncated ? '<div class="ai365-ag-vnote">' + E(T('변경 내용이 길어 앞부분만 보여 줍니다')) + '</div>' : '') + diffHtml(d.unified);
    }
    else if (d.nopreview) body = '<div class="ai365-ag-vnote">' + E(T('미리 볼 수 없습니다')) + '</div>';   // 내 컴퓨터 폴더의 문서(pdf · docx 등) / a document in a browser folder
    else if (d.binary) body = '<div class="ai365-ag-vnote">' + E(T('이진 파일이라 미리 볼 수 없습니다')) + '</div>';
    else {
      const lines = String(d.content || '').replace(/\r\n/g, '\n').split('\n');
      if (lines.length > 1 && lines[lines.length - 1] === '') lines.pop();
      body = (d.truncated ? '<div class="ai365-ag-vnote">' + E(T('내용이 길어 앞부분만 보여 줍니다')) + '</div>' : '')
        + '<div class="ai365-ag-code" data-i18n-skip>' + lines.map(function (l, i) { return '<div class="r"><i>' + (i + 1) + '</i><span>' + (E(l) || ' ') + '</span></div>'; }).join('') + '</div>';
    }
    // 같은 파일을 다시 그릴 때(턴 뒤 새로 읽기)는 스크롤 위치를 지킨다 / keep the scroll position when the same file is redrawn (re-read after a turn)
    const kind = v.kind === 'diff' ? 'diff' : 'file';
    const oldVb = R.viewer.querySelector('.ai365-ag-vb'), keep = R.viewer.getAttribute('data-path') === v.path && R.viewer.getAttribute('data-kind') === kind && oldVb ? oldVb.scrollTop : 0;
    R.viewer.setAttribute('data-path', v.path);
    R.viewer.setAttribute('data-kind', kind);
    const stl = kind === 'diff' && d.status ? String(d.status) : '';
    R.viewer.innerHTML = '<div class="ai365-ag-vh"><button type="button" class="ai365-ag-nav" data-ag="vclose" title="' + E(T('트랜스크립트로')) + '" aria-label="' + E(T('트랜스크립트로')) + '">' + IC.left + '</button>'
      + (kind === 'diff' ? IC.commit : IC.file) + '<b data-i18n-skip>' + E(baseName(v.path)) + '</b><span class="p" data-i18n-skip title="' + E(v.path) + '">' + E(v.path) + '</span>'
      + (stl ? '<span class="ai365-ag-cs ' + (CHANGE_CLS[stl] || '') + '" data-i18n-skip>' + E(stl) + '</span>' : '')
      + (kind === 'diff' && d.unified ? (function () { const s = diffStat(d.unified); return s ? '<span class="sz" data-i18n-skip>' + plusMinus(s.a, s.d) + '</span>' : ''; })() : '')
      + (d.size !== undefined && d.size !== null ? '<span class="sz" data-i18n-skip>' + E(fmtSize(d.size)) + '</span>' : '')
      + '<button type="button" class="ai365-ag-x" data-ag="vclose" title="' + E(T('닫기')) + '" aria-label="' + E(T('닫기')) + '">' + IC.x + '</button></div>'
      + '<div class="ai365-ag-vb">' + body + '</div>';
    if (keep) R.viewer.querySelector('.ai365-ag-vb').scrollTop = keep;
  }

  /* ── 동작 / actions ── */
  function nearBottom() { const s = R.scroll; return !s || s.scrollHeight - s.scrollTop - s.clientHeight < 80; }
  function scrollBottom() { const s = R.scroll; if (s) s.scrollTop = s.scrollHeight; }
  function autosize() { const t = R.input; if (!t) return; t.style.height = 'auto'; t.style.height = Math.min(200, t.scrollHeight) + 'px'; }

  function send() {
    if (!S.cur || !R.input || S.sending) return;
    const text = R.input.value.replace(/^\s+|\s+$/g, '');
    if (!text) return;
    closeSlash();
    R.input.value = '';
    autosize();
    post(text, true).catch(noop);   // 오류 안내는 post 가 한다 / post already reported the error
  }
  // 이 seq 뒤에 같은 글의 user 이벤트가 이미 왔는가(스트림이 응답보다 빠를 때) / has a user event with this text arrived after this seq (the stream beat the reply)
  function userSince(text, seq) {
    for (let i = S.events.length - 1; i >= 0 && S.events[i].seq > seq; i--) {
      const ev = S.events[i];
      if (ev.kind !== 'user') continue;
      const t = String((ev.payload || {}).text || '').trim();
      if (t === text || pieces(t).indexOf(text) >= 0) return true;   // 합쳐진 새 턴의 조각도 / a piece of a merged new turn too
    }
    return false;
  }
  // 세션 하나를 끝까지 본 것으로(지금 last_seq 를 읽어 seen 으로, /clear 뒤 옛 세션용, 적대 검토 L12)
  // Mark a session as seen to its end (read its last_seq, report it; for the old session after /clear, review L12)
  function seenAll(sid) {
    if (!S.on || !v2()) return Promise.resolve(null);
    return api(sessUrl(sid) + qs()).then(function (d) {
      const s = d && d.session, seq = s && typeof s.last_seq === 'number' ? s.last_seq : 0;
      if (!seq) return null;
      return api(sessUrl(sid, '/seen'), 'POST', withActing({ seq: seq })).then(function (res) {
        const ss = (res && res.session) || s, i = idxSess(sid);
        if (i >= 0) S.sessions[i] = Object.assign({}, S.sessions[i], { last_seq: ss.last_seq, seen_seq: Math.max(Number(ss.seen_seq) || 0, seq) });
        return ss;
      });
    }).catch(noop);
  }
  // 메시지 보내기(입력줄 · [계획대로 실행] 공용). 실행 중이면 mode steer(계약 2 F · E2), 슬래시 명령은 서버가 가른다(E9)
  // Send a message (the composer and [Run the plan]). While running it goes as mode steer (contract 2 F, E2); the server splits out slash commands (E9)
  function post(text, fromInput) {
    if (!S.cur || S.sending) return Promise.resolve(null);
    const sid = S.cur.id, wasBusy = isBusy(), seqAt = S.lastSeq;
    S.sending = true;
    if (!wasBusy) { S.pend = text; paintPend(); scrollBottom(); }
    syncComposer();
    const body = { text: text };
    if (wasBusy) body.mode = 'steer';
    return api(sessUrl(sid, '/messages'), 'POST', withActing(body)).then(function (d) {
      S.sending = false;
      if (!S.cur || S.cur.id !== sid) return d;
      if (d && d.command === 'clear' && d.session && d.session.id && d.session.id !== sid) {   // /clear = 같은 설정의 새 세션 / /clear opens a new session with the same settings
        if (S.pend === text) S.pend = '';
        fsCarry(sid, d.session);   // 내 컴퓨터 폴더: 같은 세션의 폴더 핸들을 새 세션으로 / browser folders: carry the same session's handle over
        upsert(d.session);
        openSession(d.session.id);
        // 옛 세션의 /clear 이벤트까지 본 것으로 알린 뒤 목록을 다시 읽는다('새 활동' 점이 생기지 않게)
        // Report the old session as seen through its /clear events, then re-read the list (so no 'new activity' dot appears)
        seenAll(sid).then(refreshList, refreshList);
        return d;
      }
      if (d && d.steered) {   // 다음 단계 사이에 끼워 넣음 → 스트림의 user steer 이벤트가 말풍선이 된다 / steered → the stream's user steer event becomes the bubble
        if (S.pend === text) S.pend = '';
        if (!userSince(text, seqAt)) S.steer.push(text);
        paintPend(); scrollBottom();   // 방금 보낸 글이 보이게 / keep the text just sent in view
      } else if (d && d.queued) {   // 실행 중이라 대기열로 / queued behind the running turn
        if (S.pend === text) { S.pend = ''; paintPend(); }
        S.queue.push(text);
        say(T('대기열에 넣었습니다. 지금 작업이 끝나면 이어서 처리합니다.'));
      }
      if (d && d.session) upsert(d.session); else syncComposer();
      kick();
      return d;
    }).catch(function (err) {
      S.sending = false;
      if (S.cur && S.cur.id === sid) {
        if (S.pend === text) { S.pend = ''; paintPend(); }
        if (fromInput && R.input && !R.input.value) { R.input.value = text; autosize(); }
        syncComposer();
      }
      say(err.message);
      throw err;
    });
  }

  function stop() {
    if (!S.cur || S.stopping) return;
    const sid = S.cur.id;
    S.stopping = true; syncComposer();
    api(sessUrl(sid, '/stop'), 'POST', withActing()).then(function (d) {
      S.stopping = false;
      if (d && d.session) upsert(d.session); else syncComposer();
      kick();
    }).catch(function (err) { S.stopping = false; syncComposer(); say(err.message); });
  }

  function decide(aid, dec) {
    if (!S.cur || S.deciding[aid] || ['allow', 'deny', 'always'].indexOf(dec) < 0) return;
    const a = S.approvals[aid];
    if (!a || (a.decision || 'pending') !== 'pending') return;
    const sid = S.cur.id;
    S.deciding[aid] = dec; repaintAppr(aid);
    api(sessUrl(sid, '/approvals/' + encodeURIComponent(aid)), 'POST', withActing({ decision: dec })).then(function (d) {
      if (d && d.session) upsert(d.session);
      kick();
    }).catch(function (err) {
      if (S.deciding[aid] === dec) { delete S.deciding[aid]; repaintAppr(aid); }
      say(err.message);
      kick();
    });
  }

  function patch(fields, quiet) {
    if (!S.cur) return Promise.resolve(null);
    const sid = S.cur.id;
    return api(sessUrl(sid), 'PATCH', withActing(fields)).then(function (d) {
      if (d && d.session) upsert(d.session);
      return d;
    }).catch(function (err) {
      if (!quiet) say(err.message);
      if (S.cur && S.cur.id === sid) syncComposer();   // 고른 값을 되돌린다 / revert the picked value
      throw err;
    });
  }

  /* ── 2차 동작 / phase-2 actions ── */
  // [계획대로 실행]: 아직 플랜 모드면 들어오기 전 모드(prev_perm, 없으면 auto)로 바꾸고 "위 계획대로 진행해줘" 를 보낸다
  // [Run the plan]: when still in plan mode, switch back to the mode before it (prev_perm, else auto), then send the follow-up
  function planRun(seq) {
    if (!S.cur || isBusy() || S.sending || S.planDone[seq]) return;
    S.planDone[seq] = true; repaintPlan(seq);
    const undo = function () { delete S.planDone[seq]; repaintPlan(seq); };
    const go = function () { return post(T('위 계획대로 진행해줘'), false).catch(undo); };
    if (S.cur.perm_mode === 'plan') {
      const prev = S.cur.prev_perm === 'ask' ? 'ask' : 'auto';
      patch({ perm_mode: prev }).then(go, undo);
    } else go();
  }
  function planStay(seq) { S.planDone[seq] = true; repaintPlan(seq); }

  function cpOf(cid) {
    let hit = null;
    Object.keys(S.cps).forEach(function (k) { if (S.cps[k] && S.cps[k].id === cid) hit = S.cps[k]; });
    return hit;
  }
  // 이전 내용 다시 읽기(복원 · 커밋 뒤) / re-read what a restore or commit changed
  function afterGit() { loadChanges(); loadOutputs(); refreshTree(); refreshViewer(); refreshMeta(); }
  function openRestoreDialog(cid) {
    const c = S.cur, cp = cpOf(cid);
    if (!c || !cp || isBusy()) return;
    const en = isEn(), files = Number(cp.files);
    const meta = [cp.commit ? String(cp.commit).slice(0, 7) : '', isFinite(files) && cp.files !== undefined && cp.files !== null ? (en ? files + ' files' : '파일 ' + files + '개') : ''].filter(Boolean).join(' · ');
    openDialog('restore', '<h3 id="ai365AgDlgT">' + E(T('이 시점으로 되돌릴까요?')) + '</h3>'
      + '<p class="ds">' + E(T('이 메시지를 보내기 전 상태로 작업 폴더의 파일을 되돌립니다. 그 뒤에 바뀐 내용은 사라집니다(무시된 파일은 그대로 둡니다).')) + '</p>'
      + '<div class="ai365-ag-dname" data-i18n-skip>' + E(cp.label || cid) + (meta ? '<div class="ai365-ag-mu">' + E(meta) + '</div>' : '') + '</div>'
      + '<div class="ai365-ag-derr" role="alert" hidden></div>' + actsHtml('되돌리기', 'danger'), function (d) {
      const sid = c.id;
      dlgErr(d, ''); dlgBusy(d, true);
      api(sessUrl(sid, '/checkpoints/' + encodeURIComponent(cid) + '/restore'), 'POST', withActing()).then(function (r) {
        if (S.dlg === d) closeDialog();
        if (!S.cur || S.cur.id !== sid) return;
        say(T('체크포인트로 되돌렸습니다'));
        if (r && r.session) upsert(r.session);
        afterGit();
        kick();
      }).catch(function (err) {
        if (S.dlg !== d) return;
        if (err.status === 404) {   // 그새 서버가 정리했다 → ⟲ 를 걷고 안내(적대 검토 M2) / the server trimmed it meanwhile → drop the button and say so (review M2)
          closeDialog();
          if (S.cpLive) delete S.cpLive[String(cid)];
          repaintCp(cid);
          say(T('이미 정리된 체크포인트입니다'));
          kickCheckpoints();
          return;
        }
        dlgBusy(d, false); dlgErr(d, err.message);
      });
    });
  }
  function createCheckpoint() {
    if (!S.cur || isBusy() || S.cpBusy) return;
    const sid = S.cur.id;
    S.cpBusy = true; paintSec('changes');
    api(sessUrl(sid, '/checkpoints'), 'POST', withActing()).then(function () {
      S.cpBusy = false;
      if (!S.cur || S.cur.id !== sid) return;
      say(T('체크포인트를 만들었습니다'));
      loadChanges();
      kick();
    }).catch(function (err) { S.cpBusy = false; paintSec('changes'); say(err.message); });
  }
  function openCommitDialog() {
    const c = S.cur, data = S.changes && S.changes.data;
    if (!c || isBusy() || !data || !data.repo) return;
    const en = isEn(), n = Number(data.count) || (data.files || []).length;
    openDialog('commit', '<h3 id="ai365AgDlgT">' + E(T('변경 사항 커밋')) + '</h3>'
      + '<p class="ds">' + E(T('작업 폴더의 변경 사항을 모두 스테이징해 커밋합니다.')) + ' <span data-i18n-skip>' + E((data.branch || 'HEAD') + ' · ' + (en ? n + (n === 1 ? ' file' : ' files') : '파일 ' + n + '개')) + '</span></p>'
      + '<div class="ai365-ag-fld"><div class="ai365-ag-fldh"><span>' + E(T('커밋 메시지')) + '</span>'
      + '<button type="button" class="ai365-ag-btn sm" data-ag="suggest">' + E(T('메시지 제안')) + '</button></div>'
      + '<textarea class="ai365-ag-in" data-ag-f="message" rows="3" placeholder="' + E(T('커밋 메시지(한국어 / English)')) + '" spellcheck="false" data-i18n-skip></textarea></div>'
      + '<div class="ai365-ag-derr" role="alert" hidden></div>' + actsHtml('커밋'), function (d) {
      const ta = d.el.querySelector('[data-ag-f="message"]'), message = ta ? ta.value.trim() : '', sid = c.id;
      if (!message) { dlgErr(d, T('커밋 메시지를 적어 주세요')); return; }
      dlgErr(d, ''); dlgBusy(d, true);
      api(sessUrl(sid, '/commit'), 'POST', withActing({ message: message })).then(function (r) {
        if (S.dlg === d) closeDialog();
        if (!S.cur || S.cur.id !== sid) return;
        const k = Number(r && r.files);
        say([T('커밋했습니다'), r && r.commit ? String(r.commit) : '', isFinite(k) && r && r.files !== undefined ? (isEn() ? k + (k === 1 ? ' file' : ' files') : '파일 ' + k + '개') : ''].filter(Boolean).join(' · '));
        afterGit();
      }).catch(function (err) { if (S.dlg === d) { dlgBusy(d, false); dlgErr(d, err.message); } });
    }, function (e, d) {   // [메시지 제안] / [Suggest a message]
      const b = e.target.closest('[data-ag="suggest"]');
      if (!b || d.busy || b.disabled) return;
      b.disabled = true;
      b.insertAdjacentHTML('afterbegin', '<span class="ai365-ag-spin sm"></span>');
      dlgErr(d, '');
      api(sessUrl(c.id, '/commit/suggest') + qs()).then(function (r) {
        if (S.dlg !== d) return;
        const ta = d.el.querySelector('[data-ag-f="message"]'), msg = r && r.message ? String(r.message).trim() : '';
        if (!msg) { dlgErr(d, T('제안을 받지 못했습니다')); return; }   // 빈 제안(적대 검토 L8) / an empty suggestion (review L8)
        if (ta) { ta.value = msg; try { ta.focus(); } catch (err) { /* 무시 / ignore */ } }
      }).catch(function (err) {
        if (S.dlg === d) dlgErr(d, err.message || T('제안을 받지 못했습니다'));
      }).then(function () {
        if (S.dlg !== d) return;
        b.disabled = false;
        const sp = b.querySelector('.ai365-ag-spin');
        if (sp) sp.remove();
      });
    });
  }
  // Connectors 체크 → 고른 목록 전체를 PATCH(그동안 체크박스 잠금) / a Connectors checkbox → PATCH the whole checked list (checkboxes locked meanwhile)
  function toggleConn() {
    if (!S.cur || !R.env || S.connBusy) return;
    const ids = [], sid = S.cur.id, prev = (S.cur.connectors || []).slice(), sh = connShown();
    R.env.querySelectorAll('[data-ag-conn]').forEach(function (el) { if (el.checked) ids.push(el.getAttribute('data-ag-conn')); });
    connSel().forEach(function (id) { if (!sh[id]) ids.push(id); });   // 목록에 없는 세션 id 는 그대로 / session ids missing from the list are kept (review L9)
    S.cur.connectors = ids;   // 고른 대로 먼저 보여 주고 실패하면 되돌린다 / show the choice at once, revert on failure
    S.connBusy = true; paintSec('connectors');
    const done = function () { S.connBusy = false; paintSec('connectors'); };
    patch({ connectors: ids }).then(done, function () { if (S.cur && S.cur.id === sid) S.cur.connectors = prev; done(); });
  }
  // 산출물 내려받기: 서버는 산출물 목록에 있는 경로만 200, 그 밖은 404 → 받아 본 뒤 파일로 저장, 실패는 토스트(서버 변경 4)
  // Download an output: the server answers 200 only for paths in the outputs list, else 404 → fetch first, save as a file, toast on failure (server change 4)
  function fileNameOf(cd) {
    const star = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(cd || '');
    if (star) { try { return decodeURIComponent(star[1].trim().replace(/^"|"$/g, '')); } catch (e) { /* 아래 / below */ } }
    const plain = /filename\s*=\s*"?([^";]+)"?/.exec(cd || '');
    return plain ? plain[1].trim() : '';
  }
  function downloadOutput(path, href) {
    if (!href) return;
    fetch(href).then(function (res) {
      if (!res.ok) return res.json().catch(function () { return {}; }).then(function (d) { throw new Error(detailOf(d) || T('내려받지 못했습니다')); });
      const name = fileNameOf(res.headers.get('content-disposition')) || baseName(path) || 'download';
      return res.blob().then(function (b) { return { blob: b, name: name }; });
    }).then(function (x) {
      const url = URL.createObjectURL(x.blob), a = document.createElement('a');
      a.href = url; a.download = x.name; a.style.display = 'none';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
    }).catch(function (err) { say(err instanceof TypeError || !(err && err.message) ? T('내려받지 못했습니다') : err.message); });   // 네트워크 오류는 우리 문구로 / network errors use our wording
  }
  function toggleNotify() {
    if (!S.cur) return;
    const next = !S.cur.notify;
    patch({ notify: next }).then(function () { say(T(next ? '완료 알림을 켰습니다' : '완료 알림을 껐습니다')); }, noop);
  }

  /* ── 슬래시 명령 팝업 / the slash-command popup ──
     입력 전체가 "/이름앞부분" 일 때만 연다(열 때마다 GET …/commands 를 새로 읽는다). ↑↓ 이동 · Tab/Enter 채우기 · Esc 닫기,
     이미 꼭 맞는 이름에서 Enter 면 닫고 보낸다. Opens only while the whole input is "/name-prefix" (each open re-reads GET …/commands).
     Arrows move, Tab or Enter fills, Esc closes; Enter on an exact name closes and sends. */
  function slashQuery() {
    if (!R.input || !S.cur || !v2() || S.sessLoading || S.sessErr) return null;
    const m = /^\/([^\s/]*)$/.exec(R.input.value);
    return m ? m[1].toLowerCase() : null;
  }
  function updateSlash() {
    const q = slashQuery();
    if (q === null) { closeSlash(); return; }
    if (!S.slash) {
      S.slash = { q: q, sel: 0, items: (S.cmdCache && S.cmdCache.sid === S.cur.id) ? S.cmdCache.items : null, err: '' };
      fetchCmds(S.slash);
    } else if (S.slash.q !== q) { S.slash.q = q; S.slash.sel = 0; }
    paintSlash();
  }
  function fetchCmds(sl) {
    const sid = S.cur.id, tok = S.openTok;
    api(sessUrl(sid, '/commands') + qs()).then(function (d) {
      const items = (d && Array.isArray(d.commands)) ? d.commands.filter(function (c) { return c && c.name; }) : [];
      S.cmdCache = { sid: sid, items: items };
      if (tok !== S.openTok || S.slash !== sl) return;
      const keep = slashList()[sl.sel];
      sl.items = items; sl.err = '';
      const list = slashList(), at = keep ? list.map(function (c) { return c.name; }).indexOf(keep.name) : -1;
      sl.sel = at >= 0 ? at : 0;
      paintSlash();
    }).catch(function (err) {
      if (tok !== S.openTok || S.slash !== sl) return;
      if (!sl.items) { sl.err = err.message || T('명령을 불러오지 못했습니다'); paintSlash(); }
    });
  }
  // 이름이 입력으로 시작하는 것 먼저, 그다음 이름 안에 들어 있는 것(서버 순서 = 내장 먼저 · 이름순) / prefix matches first, then substring matches (server order: built-ins first, by name)
  function slashList() {
    const sl = S.slash;
    if (!sl || !sl.items) return [];
    const a = [], b = [];
    sl.items.forEach(function (c) {
      const n = String(c.name).toLowerCase();
      if (!sl.q || n.indexOf(sl.q) === 0) a.push(c); else if (n.indexOf(sl.q) > 0) b.push(c);
    });
    return a.concat(b);
  }
  function srcLabel(src) { const p = SRC_LABEL[src]; return p ? p[isEn() ? 1 : 0] : String(src || ''); }
  // 콤보박스 ARIA: textarea 의 aria-expanded · aria-activedescendant 가 목록(listbox)과 고른 항목(option id)을 가리킨다(적대 검토 L10)
  // Combobox ARIA: the textarea's aria-expanded and aria-activedescendant point at the listbox and the selected option id (review L10)
  function paintSlash() {
    if (!R.slash) return;
    const sl = S.slash;
    R.slash.setAttribute('aria-label', T('슬래시 명령'));
    if (!sl) {
      R.slash.hidden = true; R.slash.innerHTML = '';
      if (R.input) { R.input.setAttribute('aria-expanded', 'false'); R.input.removeAttribute('aria-activedescendant'); }
      return;
    }
    const list = slashList();
    if (sl.sel >= list.length) sl.sel = Math.max(0, list.length - 1);
    let h;
    if (!sl.items) h = '<div class="ai365-ag-snote"' + (sl.err ? ' data-i18n-skip' : '') + '>' + E(sl.err || T('불러오는 중…')) + '</div>';
    else if (!list.length) h = '<div class="ai365-ag-snote">' + E(T('일치하는 명령이 없습니다')) + '</div>';
    else h = list.map(function (c, i) {
      const src = String(c.source || 'builtin');
      return '<div class="ai365-ag-scmd' + (i === sl.sel ? ' on' : '') + '" id="ai365AgCmd' + i + '" role="option" aria-selected="' + (i === sl.sel ? 'true' : 'false') + '" data-ag-cmd="' + E(c.name) + '">'
        + '<span class="nm" data-i18n-skip>/' + E(c.name) + '</span>' + (c.args ? '<span class="ar" data-i18n-skip>' + E(c.args) + '</span>' : '')
        + '<span class="ds" data-i18n-skip title="' + E(c.description || '') + '">' + E(c.description || '') + '</span>'
        + '<span class="ai365-ag-sb ' + E(src) + '">' + E(srcLabel(src)) + '</span></div>';
    }).join('');
    R.slash.innerHTML = h;
    R.slash.hidden = false;
    if (R.input) {
      R.input.setAttribute('aria-expanded', 'true');
      if (list.length) R.input.setAttribute('aria-activedescendant', 'ai365AgCmd' + sl.sel); else R.input.removeAttribute('aria-activedescendant');
    }
    const on = R.slash.querySelector('.ai365-ag-scmd.on');   // 고른 항목이 보이게 / keep the selection in view
    if (on) {
      const top = on.offsetTop, bot = top + on.offsetHeight;
      if (top < R.slash.scrollTop) R.slash.scrollTop = top - 6;
      else if (bot > R.slash.scrollTop + R.slash.clientHeight) R.slash.scrollTop = bot - R.slash.clientHeight + 6;
    }
  }
  function closeSlash() { if (!S.slash) return; S.slash = null; paintSlash(); }
  function fillCmd(c) {
    if (!c || !R.input) return;
    R.input.value = '/' + c.name + ' ';
    closeSlash();
    autosize();
    onInputInput();
    try { const n = R.input.value.length; R.input.focus(); R.input.setSelectionRange(n, n); } catch (e) { /* 무시 / ignore */ }
  }
  // 팝업이 키를 썼으면 true / true when the popup consumed the key
  function slashKey(e) {
    const sl = S.slash;
    if (!sl) return false;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeSlash(); return true; }
    const list = slashList();
    if (!list.length) return false;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      sl.sel = (sl.sel + (e.key === 'ArrowDown' ? 1 : -1) + list.length) % list.length;
      paintSlash();
      return true;
    }
    if (e.key === 'Tab' && !e.shiftKey) { e.preventDefault(); fillCmd(list[sl.sel]); return true; }
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
      e.preventDefault();
      const c = list[sl.sel];
      if (R.input.value.trim().toLowerCase() === '/' + String(c.name).toLowerCase()) { closeSlash(); send(); }
      else fillCmd(c);
      return true;
    }
    return false;
  }

  function pushHist(id) {
    if (S.hist[S.hpos] === id) return;
    S.hist = S.hist.slice(0, S.hpos + 1);
    S.hist.push(id);
    S.hpos = S.hist.length - 1;
  }
  function histTarget(dir) {
    let p = S.hpos + dir;
    while (p >= 0 && p < S.hist.length && idxSess(S.hist[p]) < 0) p += dir;
    return (p >= 0 && p < S.hist.length) ? p : -1;
  }
  function canHist(dir) { return histTarget(dir) >= 0; }
  function goHist(dir) { const p = histTarget(dir); if (p < 0) return; S.hpos = p; openSession(S.hist[p], { hist: true }); }

  function showSec(key) {
    if (!R.env) return;
    if (!S.env) { S.env = true; R.shell.classList.remove('noenv'); renderHead(); }
    if (S.shut[key]) { delete S.shut[key]; paintSec(key); }
    const el = R.env.querySelector('[data-sec="' + key + '"]');
    if (el) {
      R.env.scrollTop = Math.max(0, el.offsetTop - 4);
      el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
    }
  }

  /* ── 대화 상자 / dialogs ── */
  // onClick(e, d) = 그 밖의 버튼(커밋 대화 상자의 [메시지 제안] 등) / onClick(e, d) handles other buttons (such as [Suggest a message] in the commit dialog)
  function openDialog(kind, html, onOk, onClick) {
    closeDialog();
    const ov = document.createElement('div');
    ov.className = 'ai365-ag-ov';
    ov.setAttribute('data-ag-ov', kind);
    ov.innerHTML = '<div class="ai365-ag-dlg" role="dialog" aria-modal="true" aria-labelledby="ai365AgDlgT">' + html + '</div>';
    document.body.appendChild(ov);
    const d = { kind: kind, el: ov, ok: onOk, busy: false };
    S.dlg = d;
    ov.addEventListener('mousedown', function (e) { if (e.target === ov) closeDialog(); });   // 바깥을 누르면 닫는다 / a press outside closes
    ov.addEventListener('click', function (e) {
      const b = e.target.closest('[data-ag-dlg]');
      if (b) { if (b.dataset.agDlg === 'cancel') closeDialog(); else submitDialog(); return; }
      const pk = e.target.closest('[data-ag-pick]');
      if (pk) { const inp = ov.querySelector('[data-ag-f="folder"]'); if (inp) { inp.value = pk.dataset.agPick; inp.focus(); } clearBadHint(ov); return; }
      if (onClick) onClick(e, d);
    });
    ov.addEventListener('change', function (e) {
      if (e.target.matches('[data-ag-f="perm"]')) { const h = ov.querySelector('[data-ag-permhint]'); if (h) h.textContent = T(PERM_HINT[e.target.value] || ''); }
    });
    // 폴더 칸을 고치면 '허용 폴더 밖' 안내를 걷는다 / editing the folder field drops the 'outside the allowed folders' note
    ov.addEventListener('input', function (e) { if (e.target.matches('[data-ag-f="folder"]')) clearBadHint(ov); });
    ov.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' || e.isComposing || e.keyCode === 229) return;
      // 입력칸의 Enter, textarea 는 Ctrl/⌘+Enter 가 확인 / Enter in an input, or Ctrl/Cmd+Enter in a textarea, confirms
      if (e.target.matches('input') || (e.target.matches('textarea') && (e.ctrlKey || e.metaKey))) { e.preventDefault(); submitDialog(); }
    });
    // 입력칸(textarea 포함)이 먼저, 없으면 첫 버튼(적대 검토 L8: 커밋 대화 상자는 [메시지 제안]보다 메시지 칸)
    // A field (textarea included) first, else the first button (review L8: the commit dialog focuses the message, not [Suggest])
    const first = ov.querySelector('input, select, textarea') || ov.querySelector('button');
    if (first) { try { first.focus(); if (first.select && first.value) first.select(); } catch (e) { /* 포커스 실패 무시 / ignore focus errors */ } }
    return d;
  }
  function closeDialog() { closeBrowse(true); if (S.dlg) { S.dlg.el.remove(); S.dlg = null; } }   // 탐색기는 대화 상자에 딸린다 / the explorer belongs to the dialog
  function submitDialog() { const d = S.dlg; if (d && !d.busy && d.ok) d.ok(d); }
  function dlgErr(d, msg) { const el = d.el.querySelector('.ai365-ag-derr'); if (el) { el.hidden = !msg; el.textContent = msg || ''; } }
  function dlgBusy(d, on) {
    d.busy = on;
    d.el.querySelectorAll('[data-ag-dlg], input, select, textarea, [data-ag]').forEach(function (el) { el.disabled = on; });
  }
  function actsHtml(okLabel, okCls) {
    return '<div class="acts"><button type="button" class="ai365-ag-btn" data-ag-dlg="cancel">' + E(T('취소')) + '</button>'
      + '<button type="button" class="ai365-ag-btn ' + (okCls || 'pri') + '" data-ag-dlg="ok">' + E(T(okLabel)) + '</button></div>';
  }

  function openNewDialog() {
    if (!S.on) return;
    const st = S.settings || {}, allowed = Array.isArray(st.allowed_folders) ? st.allowed_folders : [];
    const folder = (S.sessions[0] && S.sessions[0].folder) || allowed[0] || '';   // 가장 최근 세션의 폴더부터 / start from the latest session's folder
    const model = st.default_model || (S.models[0] && S.models[0].id) || '';
    const perm = st.default_perm === 'ask' || (st.default_perm === 'plan' && v2()) ? st.default_perm : 'auto';
    // 폴더 칸 옆 [찾아보기…] = 서버 PC 의 폴더 선택 창, 그 아래 "서버 폴더에서 고르기" = 앱 안 탐색기(서버가 folder_picker 를 알릴 때만)
    // [Browse…] next to the folder field opens the server PC's folder window; "Pick from server folders" opens the in-app explorer (only with folder_picker)
    const pk = S.picker;
    // 내 컴퓨터 폴더(계약 F2): 쓸 수 있으면 맨 위에 [내 컴퓨터 폴더 열기…] + 설명 + "또는 서버 폴더" 구분선(종전 설명 줄은 그 아래로
    // 옮겨 서버 폴더 설명이 된다). 브라우저 · 주소가 지원하지 않으면 안내 한 줄, 서버가 껐으면(browser_folders false) 아무것도 없다.
    // 원격 클라이언트(remote)는 서버 폴더 구역(설명 · 칸 · 찾아보기 · 칩 · 안내 · 구분선 · [만들기])이 없고, Enter 도 선택 창을 연다.
    // 서버 폴더 칸 · 버튼 · 칩 · 제목 · 모델 · 권한 모드 · [만들기]의 셀렉터는 종전 그대로
    // Folders on my computer (contract F2): when available, [Open a folder on my computer…] with a note and an "Or a server folder"
    // divider at the very top (the old description line moves below it and describes server folders). A browser or address without
    // support gets one note line; a server that turned it off (browser_folders false) gets nothing. Remote clients get no
    // server-folder section (description, field, Browse, chips, note, divider, [Create]) and Enter opens the picker too. The
    // selectors of the server-folder field, buttons, chips, title, model, mode and [Create] stay as they were
    const avail = fsAvail(), remote = S.remote;
    const fsBlock = avail
      ? '<div class="ai365-ag-fsnew"><button type="button" class="ai365-ag-btn pri" data-ag="fsopen">' + IC.laptop + E(T('내 컴퓨터 폴더 열기…')) + '</button>'
        + '<div class="ai365-ag-hint2">' + E(T('브라우저로 내 컴퓨터의 폴더를 고릅니다. 에이전트가 그 폴더 안의 파일을 읽고 고칩니다(명령 실행 없음).')) + '</div></div>'
        + (remote ? '' : '<div class="ai365-ag-or" role="separator"><span>' + E(T('또는 서버 폴더')) + '</span></div>')
      : (!S.fsOk ? '<div class="ai365-ag-hint2" data-ag-fsno>' + E(T(FS_NO)) + '</div>' : (remote ? '<div class="ai365-ag-hint2" data-ag-fsno>' + E(T(FS_OFF)) + '</div>' : ''));
    const server = remote ? '' : '<p class="ds">' + E(T('에이전트가 작업 폴더 안에서 파일을 읽고 고치고 명령을 실행합니다.')) + '</p>'
      + '<div class="ai365-ag-fld"><label for="ai365AgFolder">' + E(T('작업 폴더')) + '</label>'
      + '<div class="ai365-ag-frow"><input class="ai365-ag-in" id="ai365AgFolder" data-ag-f="folder" list="ai365AgFolders" value="' + E(folder) + '" spellcheck="false" autocomplete="off" data-i18n-skip>'
      + (pk ? '<button type="button" class="ai365-ag-btn" data-ag="pick">' + E(T('찾아보기…')) + '</button>' : '') + '</div>'
      + (pk ? '<div class="ai365-ag-fsub"><span class="ai365-ag-pickhint" data-ag-pickhint role="status" hidden></span>'
        + '<button type="button" class="ai365-ag-link" data-ag="browse">' + E(T('서버 폴더에서 고르기')) + '</button></div>' : '')
      + '</div>'
      + '<datalist id="ai365AgFolders">' + allowed.map(function (f) { return '<option value="' + E(f) + '"></option>'; }).join('') + '</datalist>'
      + (allowed.length ? '<div class="ai365-ag-chips"><span class="lb">' + E(T('허용 폴더')) + '</span>' + allowed.map(function (f) {
        return '<button type="button" class="ai365-ag-chip" data-ag-pick="' + E(f) + '" title="' + E(f) + '" data-i18n-skip>' + IC.folder + E(baseName(f) || f) + '</button>';
      }).join('') + '</div>' : '')
      + '<div class="ai365-ag-hint2">' + E(T('허용 폴더 안의 경로만 쓸 수 있습니다')) + '</div>';
    const html = '<h3 id="ai365AgDlgT">' + E(T('새 세션')) + '</h3>' + fsBlock + server
      + '<label class="ai365-ag-fld"><span>' + E(T('제목 (선택)')) + '</span><input class="ai365-ag-in" data-ag-f="title" placeholder="' + E(T('비우면 폴더 이름을 씁니다')) + '" autocomplete="off"></label>'
      + '<div class="ai365-ag-row2"><label class="ai365-ag-fld"><span>' + E(T('모델')) + '</span><select class="ai365-ag-in" data-ag-f="model" data-i18n-skip>' + modelOpts(model) + '</select></label>'
      + '<label class="ai365-ag-fld"><span>' + E(T('권한 모드')) + '</span><select class="ai365-ag-in" data-ag-f="perm" data-i18n-skip>' + permOpts(perm) + '</select></label></div>'
      + '<div class="ai365-ag-hint2" data-ag-permhint>' + E(T(PERM_HINT[perm])) + '</div>'
      + '<div class="ai365-ag-derr" role="alert" hidden></div>'
      + (remote ? '<div class="acts"><button type="button" class="ai365-ag-btn" data-ag-dlg="cancel">' + E(T('취소')) + '</button></div>' : actsHtml('만들기'));
    // 원격의 확인(Enter) = 선택 창(키 입력도 사용자 제스처다) / for remote clients, confirming (Enter) opens the picker (a key press is a user gesture too)
    const onOk = !remote ? submitNew : function (d) { const b = d.el.querySelector('[data-ag="fsopen"]'); if (b && !b.disabled && !d.busy) fsDialogOpen(d, b); };
    openDialog('new', html, onOk, function (e, d) {
      const fo = e.target.closest('[data-ag="fsopen"]');   // 선택 창은 이 클릭(제스처) 안에서 바로 연다 / the picker opens right inside this click (gesture)
      if (fo) { if (!d.busy && !fo.disabled) fsDialogOpen(d, fo); return; }
      const t = e.target.closest('[data-ag="pick"], [data-ag="browse"]');
      if (!t || d.busy || t.disabled) return;
      const inp = d.el.querySelector('[data-ag-f="folder"]'), hint = d.el.querySelector('[data-ag-pickhint]');
      // 고른 폴더를 칸에 채운다. 허용 폴더 밖이면 안내(만들기는 서버가 422 로 막는다) / fill the field; outside the allowed folders shows a note (the server refuses creation with 422)
      const fill = function (p, ok) {
        if (S.dlg !== d || !inp) return;
        inp.value = p;
        setHint(hint, ok ? '' : '허용 폴더 밖입니다. 관리 센터 › Agentic 설정에서 추가하세요', true);
        dlgErr(d, '');
        try { inp.focus(); } catch (err) { /* 무시 / ignore */ }
      };
      const browse = function () { openBrowse(inp ? inp.value.trim() : '', fill, t); };
      if (t.getAttribute('data-ag') === 'browse') browse();
      else pickFolder(d, t, hint, inp ? inp.value.trim() : '', T('작업 폴더 선택'), fill, browse);
    });
  }
  function submitNew(d) {
    const val = function (f) { const el = d.el.querySelector('[data-ag-f="' + f + '"]'); return el ? el.value.trim() : ''; };
    const folder = val('folder'), title = val('title');
    if (!folder) { dlgErr(d, T('작업 폴더를 적어 주세요')); return; }
    const payload = withActing({ folder: folder, model: val('model'), perm_mode: val('perm') || 'auto' });
    if (title) payload.title = title;
    dlgErr(d, ''); dlgBusy(d, true);
    api(BASE + '/sessions', 'POST', payload).then(function (r) {
      if (S.dlg !== d) return;
      closeDialog();
      const s = r && r.session;
      if (!s || !S.on) return;
      upsert(s);
      openSession(s.id);
    }).catch(function (err) {
      if (S.dlg !== d) return;
      dlgBusy(d, false); dlgErr(d, err.message);
    });
  }

  /* ── 폴더 고르기(2026-10-19) / folder picking ──
     [찾아보기…] = POST /pick-folder: 서버 PC 에 운영체제 폴더 선택 창을 띄우고 고를 때까지 기다린다. 409(이미 열림) = 토스트,
     503 · 네트워크 실패 = 앱 안 탐색기(GET /browse 로 하위 폴더만 걷는 두 번째 오버레이 [data-ag-ov="browse"]).
     [Browse…] = POST /pick-folder shows the operating system's folder window on the server PC and waits for the choice. 409 (already
     open) = a toast; 503 or a network failure = the in-app explorer (a second overlay [data-ag-ov="browse"] walking subfolders through GET /browse). */
  // 안내 줄: 글이 비면 숨긴다, bad = 경고색 / the note line: hidden when empty, bad = warning colour
  function setHint(el, ko, bad) {
    if (!el) return;
    el.textContent = ko ? T(ko) : '';
    el.hidden = !ko;
    el.classList.toggle('bad', !!(ko && bad));
  }
  function clearBadHint(root) { const h = root && root.querySelector('[data-ag-pickhint].bad'); if (h) setHint(h, ''); }
  // 대화 상자 d 의 [찾아보기…](btn): 기다리는 동안 스피너와 안내, path 가 오면 onPath(path, allowed), 503 · 네트워크 실패면 onBrowse()
  // [Browse…] (btn) in dialog d: a spinner and a note while waiting; a path calls onPath(path, allowed); 503 or a network failure calls onBrowse()
  function pickFolder(d, btn, hint, start, title, onPath, onBrowse) {
    if (S.picking || !S.on) return;
    S.picking = true;
    if (btn) { btn.disabled = true; btn.insertAdjacentHTML('afterbegin', '<span class="ai365-ag-spin sm"></span>'); }
    setHint(hint, '폴더 선택 창을 열었습니다. 창이 보이지 않으면 작업 표시줄을 확인하세요');
    api(BASE + '/pick-folder', 'POST', withActing({ start: start || '', title: title || '' })).then(function (r) {
      if (S.dlg !== d) return;
      setHint(hint, '');
      if (r && !r.cancelled && r.path) onPath(String(r.path), r.allowed !== false);   // cancelled = 아무것도 안 함 / a cancel does nothing
    }).catch(function (err) {
      if (S.dlg !== d) return;
      setHint(hint, '');
      if (err.status === 409) say(T(err.message));
      else if (err.status === 503 || !err.status) onBrowse();   // 창을 띄울 수 없음 · 네트워크 실패 → 앱 안 탐색기 / no window or no network → the in-app explorer
      else say(err.message);
    }).then(function () {
      S.picking = false;
      if (!btn) return;
      const sp = btn.querySelector('.ai365-ag-spin');
      if (sp) sp.remove();
      btn.disabled = !!(S.dlg && S.dlg.busy);
    });
  }

  // 앱 안 탐색기: 열린 대화 상자 위에 겹치는 두 번째 오버레이. 줄을 누르면 들어가고 [이 폴더 선택]이 onPick(path, allowed).
  // ret = 닫을 때 초점을 돌려줄 버튼 / The in-app explorer: a second overlay above the open dialog. A row click enters it;
  // [Select this folder] calls onPick(path, allowed); ret = the button that gets the focus back on close
  function openBrowse(start, onPick, ret) {
    if (!S.on) return;
    closeBrowse(true);
    const ov = document.createElement('div');
    ov.className = 'ai365-ag-ov ai365-ag-ov2';
    ov.setAttribute('data-ag-ov', 'browse');
    ov.innerHTML = '<div class="ai365-ag-dlg ai365-ag-bdlg" role="dialog" aria-modal="true" aria-labelledby="ai365AgBrT">'
      + '<h3 id="ai365AgBrT">' + E(T('폴더 고르기')) + '</h3>'
      + '<nav class="ai365-ag-bcrumbs" data-ag-bcrumbs aria-label="' + E(T('폴더 고르기')) + '"></nav>'
      + '<div class="ai365-ag-blist" data-ag-blist></div>'
      + '<div class="acts"><button type="button" class="ai365-ag-btn" data-ag="browse-up">' + IC.up + E(T('위로')) + '</button><span class="sp"></span>'
      + '<button type="button" class="ai365-ag-btn" data-ag="browse-cancel">' + E(T('취소')) + '</button>'
      + '<button type="button" class="ai365-ag-btn pri" data-ag="browse-ok">' + E(T('이 폴더 선택')) + '</button></div></div>';
    document.body.appendChild(ov);
    const b = { el: ov, onPick: onPick, data: null, loading: false, err: '', tok: 0, ret: ret || document.activeElement };
    S.browse = b;
    ov.addEventListener('mousedown', function (e) { if (e.target === ov) closeBrowse(); });   // 바깥 = 탐색기만 닫는다 / outside closes the explorer only
    ov.addEventListener('click', onBrowseClick);
    loadBrowse(start || '', true);
  }
  function closeBrowse(quiet) {
    const b = S.browse;
    if (!b) return;
    S.browse = null;
    b.el.remove();
    if (!quiet && b.ret && b.ret.isConnected) { try { b.ret.focus(); } catch (e) { /* 무시 / ignore */ } }
  }
  // fallback = 시작 경로를 못 열면(밖 · 없음) 처음 목록으로 / fallback: when the start path fails (outside, missing), go to the top list
  function loadBrowse(path, fallback) {
    const b = S.browse;
    if (!b) return;
    const my = ++b.tok;
    b.loading = true; b.err = '';
    paintBrowse();
    api(BASE + '/browse' + qs({ path: path || '' })).then(function (d) {
      if (S.browse !== b || my !== b.tok) return;
      b.loading = false; b.data = d || { path: '', entries: [] };
      paintBrowse(); focusBrowse(b);
    }).catch(function (err) {
      if (S.browse !== b || my !== b.tok) return;
      if (fallback && path) { loadBrowse('', false); return; }
      b.loading = false; b.err = err.message || T('폴더를 불러오지 못했습니다');
      paintBrowse(); focusBrowse(b);
    });
  }
  // 초점이 탐색기 밖이거나(처음 열 때) 다시 그린 줄과 함께 사라졌으면 첫 줄(없으면 [이 폴더 선택] · [취소])로: 키보드로도 이어서 고른다
  // When the focus is outside the explorer (first open) or went with the repainted rows, move it to the first row (else Select or
  // Cancel) so the keyboard can keep going
  function focusBrowse(b) {
    const a = document.activeElement;
    if (a && a.isConnected && b.el.contains(a)) return;
    const f = b.el.querySelector('.ai365-ag-brow') || b.el.querySelector('[data-ag="browse-ok"]:not(:disabled)') || b.el.querySelector('[data-ag="browse-cancel"]');
    try { f.focus(); } catch (e) { /* 무시 / ignore */ }
  }
  function browseRow(x, icon) {
    return '<button type="button" class="ai365-ag-brow" data-ag-bdir="' + E(x.path) + '" title="' + E(x.path) + '" data-i18n-skip>' + icon + '<span class="nm">' + E(x.name || x.path) + '</span></button>';
  }
  function paintBrowse() {
    const b = S.browse;
    if (!b) return;
    const d = b.data, path = (d && d.path) || '', top = !path;
    const crumbs = b.el.querySelector('[data-ag-bcrumbs]'), list = b.el.querySelector('[data-ag-blist]');
    crumbs.innerHTML = '<button type="button" class="ai365-ag-bc' + (top ? ' on' : '') + '" data-ag-bcrumb="" title="' + E(T('처음으로')) + '" aria-label="' + E(T('처음으로')) + '">' + IC.home + '</button>'
      + ((d && d.crumbs) || []).map(function (c, i, all) {
        return '<span class="ai365-ag-bsep" aria-hidden="true">' + IC.chevR + '</span><button type="button" class="ai365-ag-bc' + (i === all.length - 1 ? ' on' : '') + '" data-ag-bcrumb="' + E(c.path) + '" title="' + E(c.path) + '" data-i18n-skip>' + E(c.name || c.path) + '</button>';
      }).join('');
    let body = '';
    if (b.err) body = '<div class="ai365-ag-bnote bad" data-i18n-skip>' + E(b.err) + '</div>';
    else if (!d) body = '<div class="ai365-ag-bnote">' + E(T('불러오는 중…')) + '</div>';
    else if (top) {
      const entries = d.entries || [], drives = d.drives || [];
      body = (entries.length ? '<div class="ai365-ag-bgrp">' + E(T('허용 폴더')) + '</div>' + entries.map(function (x) { return browseRow(x, IC.folder); }).join('') : '')
        + (drives.length ? '<div class="ai365-ag-bgrp">' + E(T('드라이브')) + '</div>' + drives.map(function (x) { return browseRow(x, IC.drive); }).join('') : '');
      if (!body) body = '<div class="ai365-ag-bnote">' + E(T('허용 폴더가 없으면 세션을 만들 수 없습니다.')) + '</div>';   // 허용 폴더도 드라이브도 없음 / neither allowed folders nor drives
    } else {
      const entries = d.entries || [];
      body = entries.length ? entries.map(function (x) { return browseRow(x, IC.folder); }).join('') : '<div class="ai365-ag-bnote">' + E(T('하위 폴더가 없습니다')) + '</div>';
      if (d.truncated) body += '<div class="ai365-ag-bnote">' + E(T('폴더가 많아 500개까지만 보여 줍니다')) + '</div>';
    }
    list.innerHTML = body;
    list.scrollTop = 0;
    list.setAttribute('aria-busy', b.loading ? 'true' : 'false');
    const up = b.el.querySelector('[data-ag="browse-up"]'), ok = b.el.querySelector('[data-ag="browse-ok"]');
    up.disabled = top;
    ok.disabled = top || b.loading || !!b.err;
  }
  function onBrowseClick(e) {
    const b = S.browse;
    if (!b) return;
    let t;
    if ((t = e.target.closest('[data-ag-bdir]'))) { loadBrowse(t.getAttribute('data-ag-bdir')); return; }
    if ((t = e.target.closest('[data-ag-bcrumb]'))) { loadBrowse(t.getAttribute('data-ag-bcrumb')); return; }
    if (!(t = e.target.closest('[data-ag]')) || t.disabled) return;
    const ag = t.getAttribute('data-ag');
    if (ag === 'browse-up') { if (b.data && b.data.path) loadBrowse(b.data.parent || ''); }
    else if (ag === 'browse-cancel') closeBrowse();
    else if (ag === 'browse-ok') {
      const p = b.data && b.data.path;
      if (!p) return;
      const fn = b.onPick, ok = b.data.allowed !== false;
      closeBrowse();
      if (fn) fn(String(p), ok);
    }
  }

  // 세션 메뉴 "추가 폴더…": 지금 extra_folders 를 고치는 대화 상자([찾아보기…] · 서버 폴더에서 고르기 · [삭제] → [저장] = PATCH)
  // The session menu's "Extra folders…": a dialog editing extra_folders ([Browse…], pick from server folders, [Delete] → [Save] = PATCH)
  function openFoldersDialog() {
    const c = S.cur;
    if (!c || !S.picker || S.sessLoading || S.sessErr) return;   // 전체 세션을 읽기 전(목록의 가벼운 모양)에는 열지 않는다 / not before the full session is loaded
    const draft = (c.extra_folders || []).slice(), sid = c.id;
    const rows = function () {
      return draft.length ? draft.map(function (f, i) {
        return '<div class="ai365-ag-xrow" data-ag-xf="' + i + '"><code title="' + E(f) + '" data-i18n-skip>' + E(f) + '</code>'
          + '<button type="button" class="ai365-ag-btn sm" data-ag-xfrm="' + i + '">' + E(T('삭제')) + '</button></div>';
      }).join('') : '<div class="ai365-ag-xnone">' + E(T('추가 폴더가 없습니다')) + '</div>';
    };
    const d = openDialog('folders', '<h3 id="ai365AgDlgT">' + E(T('추가 폴더')) + '</h3>'
      + '<p class="ds">' + E(T('에이전트가 작업 폴더 밖에서도 읽고 고칠 수 있는 폴더입니다. 허용 폴더 안에서만 고를 수 있습니다.')) + '</p>'
      + '<div class="ai365-ag-xlist" data-ag-xlist>' + rows() + '</div>'
      + '<div class="ai365-ag-fsub mid"><button type="button" class="ai365-ag-btn sm" data-ag="pick">' + IC.plus + E(T('찾아보기…')) + '</button>'
      + '<button type="button" class="ai365-ag-link" data-ag="browse">' + E(T('서버 폴더에서 고르기')) + '</button></div>'
      + '<div class="ai365-ag-pickhint" data-ag-pickhint role="status" hidden></div>'
      + '<div class="ai365-ag-derr" role="alert" hidden></div>' + actsHtml('저장'), function (dd) {
      if (!S.cur || S.cur.id !== sid) { closeDialog(); return; }
      dlgErr(dd, ''); dlgBusy(dd, true);
      patch({ extra_folders: draft.slice() }, true).then(function () { if (S.dlg === dd) closeDialog(); })
        .catch(function (err) { if (S.dlg === dd) { dlgBusy(dd, false); dlgErr(dd, err.message); } });
    }, function (e, dd) {
      if (dd.busy) return;
      const hint = dd.el.querySelector('[data-ag-pickhint]'), list = dd.el.querySelector('[data-ag-xlist]');
      let t;
      if ((t = e.target.closest('[data-ag-xfrm]'))) {
        draft.splice(Number(t.getAttribute('data-ag-xfrm')), 1);
        list.innerHTML = rows(); setHint(hint, '');
        return;
      }
      if (!(t = e.target.closest('[data-ag="pick"], [data-ag="browse"]')) || t.disabled) return;
      // 허용 폴더 밖 · 이미 있는 폴더는 넣지 않고 안내한다(밖은 저장 때 서버도 422) / outside or duplicate folders are refused with a note (the server answers 422 for outside ones too)
      const add = function (p, ok) {
        if (S.dlg !== dd) return;
        if (!ok) { setHint(hint, '허용 폴더 밖입니다. 관리 센터 › Agentic 설정에서 추가하세요', true); return; }
        if (draft.some(function (f) { return folderKey(f) === folderKey(p); })) { setHint(hint, '이미 목록에 있는 폴더입니다', true); return; }
        draft.push(p);
        list.innerHTML = rows(); setHint(hint, ''); dlgErr(dd, '');
      };
      const browse = function () { openBrowse(c.folder || '', add, t); };
      if (t.getAttribute('data-ag') === 'browse') browse();
      else pickFolder(dd, t, hint, c.folder || '', T('추가 폴더 선택'), add, browse);
    });
    const pb = d.el.querySelector('[data-ag="pick"]');   // 입력칸이 없으니 [찾아보기…]에 초점 / no field here, so focus [Browse…]
    if (pb) { try { pb.focus(); } catch (e) { /* 무시 / ignore */ } }
  }

  function openRenameDialog() {
    const c = S.cur;
    if (!c) return;
    openDialog('rename', '<h3 id="ai365AgDlgT">' + E(T('세션 이름 바꾸기')) + '</h3>'
      + '<label class="ai365-ag-fld"><span>' + E(T('제목')) + '</span><input class="ai365-ag-in" data-ag-f="title" value="' + E(c.title || titleOf(c)) + '" autocomplete="off" data-i18n-skip></label>'
      + '<div class="ai365-ag-derr" role="alert" hidden></div>' + actsHtml('저장'), function (d) {
      const inp = d.el.querySelector('[data-ag-f="title"]'), title = inp ? inp.value.trim() : '';
      if (!title) { dlgErr(d, T('이름을 적어 주세요')); return; }
      dlgErr(d, ''); dlgBusy(d, true);
      patch({ title: title }, true).then(function () { if (S.dlg === d) closeDialog(); })
        .catch(function (err) { if (S.dlg === d) { dlgBusy(d, false); dlgErr(d, err.message); } });
    });
  }

  function openDeleteDialog() {
    const c = S.cur;
    if (!c) return;
    openDialog('delete', '<h3 id="ai365AgDlgT">' + E(T('세션 삭제')) + '</h3>'
      + '<p class="ds">' + E(T('이 세션을 삭제할까요? 트랜스크립트도 함께 지워집니다.')) + (isBusy() ? ' ' + E(T('실행 중이면 먼저 중단합니다.')) : '') + '</p>'
      + '<div class="ai365-ag-dname" data-i18n-skip>' + E(titleOf(c)) + '</div>'
      + '<div class="ai365-ag-derr" role="alert" hidden></div>' + actsHtml('삭제', 'danger'), function (d) {
      const sid = c.id;
      dlgErr(d, ''); dlgBusy(d, true);
      api(sessUrl(sid) + qs(), 'DELETE').then(function () {
        if (S.dlg === d) closeDialog();
        if (!S.on) return;
        S.sessions = S.sessions.filter(function (s) { return s.id !== sid; });
        if (isBrowser(c)) { delete S.fs[sid]; idbDel(sid); }   // 그 세션의 폴더 핸들도 지운다 / drop that session's folder handle too
        S.hist = S.hist.filter(function (h) { return h !== sid; });
        S.hpos = S.hist.length - 1;
        if (lastId() === sid) saveLast('');
        say(T('세션을 삭제했습니다.'));
        if (S.cur && S.cur.id === sid) {
          if (S.sessions[0]) openSession(S.sessions[0].id);
          else { closeStream(); stopTaskPoll(); S.cur = null; S.git = null; S.tree = null; S.viewer = null; S.tasks = []; resetTranscript(); renderAll(); }
        } else { renderSideList(); renderHead(); }
        ensureListPoll();
      }).catch(function (err) { if (S.dlg === d) { dlgBusy(d, false); dlgErr(d, err.message); } });
    });
  }

  /* ── 내 컴퓨터 폴더(브라우저) 세션(2026-10-20, 계약 F) / browser-folder sessions (2026-10-20, contract F) ──
     핸들 저장(IndexedDB) · 권한 · 선택 창 · 세션 만들기 · 서버의 도구 요청 실행(원시 op, 계약 B2) · 안내 줄 · 파일 트리와 뷰어.
     선택 창(showDirectoryPicker)과 권한 창(requestPermission)은 사용자 제스처 안에서만 열리므로 클릭 처리기에서 await 없이 바로 부른다.
     Handle storage (IndexedDB), permissions, the picker, session creation, running the server's tool requests (primitive ops,
     contract B2), the bar, and the file tree and viewer. The picker (showDirectoryPicker) and the permission prompt
     (requestPermission) open only inside a user gesture, so click handlers call them at once, before any await. */

  // IndexedDB ai365_agentic_fs / handles(key = 세션 id, value = {name, handle, ts}). 실패(저장소 없음 · 복제할 수 없는 가짜 핸들)는 조용히 null
  // IndexedDB ai365_agentic_fs / handles (key = session id, value = {name, handle, ts}); failures (no storage, uncloneable fake handles) quietly give null
  function idb() {
    if (!S.fsDb) {
      S.fsDb = new Promise(function (resolve) {
        let req;
        try { req = window.indexedDB.open(FS_DB, 1); } catch (e) { resolve(null); return; }
        req.onupgradeneeded = function () { try { req.result.createObjectStore(FS_STORE); } catch (e) { /* 이미 있음 / already there */ } };
        req.onsuccess = function () { resolve(req.result); };
        req.onerror = req.onblocked = function () { resolve(null); };
      });
    }
    return S.fsDb;
  }
  function idbRun(mode, fn) {
    return idb().then(function (db) {
      if (!db) return null;
      return new Promise(function (resolve) {
        let tx, req;
        try { tx = db.transaction(FS_STORE, mode); req = fn(tx.objectStore(FS_STORE)); } catch (e) { resolve(null); return; }
        tx.oncomplete = function () { resolve(req ? req.result : null); };
        tx.onerror = tx.onabort = function () { resolve(null); };
      });
    }).catch(function () { return null; });
  }
  function idbDel(sid) { return idbRun('readwrite', function (st) { return st.delete(sid); }); }
  function fsHandleOk(h) { return !!(h && h.kind === 'directory' && typeof h.getDirectoryHandle === 'function' && typeof h.getFileHandle === 'function'); }
  function fsSave(sid, name, h) {
    if (sid && fsHandleOk(h)) idbRun('readwrite', function (st) { return st.put({ name: String(name || h.name || ''), handle: h, ts: Date.now() }, sid); });
  }
  // 세션의 핸들: 그 세션 id 의 것만(메모리 → IndexedDB). 이름이 같은 다른 세션의 핸들은 빌리지 않는다: 이름이 같은 다른 폴더를 조용히
  // 연결하던 문제(적대 검토 2026-10-20 HIGH). 없으면 안내 줄 nohandle + [폴더 열기]. /clear 의 새 세션은 fsCarry 가 명시적으로 옮긴다
  // A session's handle: only that session id's (memory, then IndexedDB). Another session's handle is never borrowed by name, which
  // silently connected a different folder with the same name (review 2026-10-20, HIGH); without one the bar shows nohandle and
  // [Open folder]. fsCarry moves the handle explicitly to the new session made by /clear
  function fsFind(s) {
    const mem = S.fs[s.id];
    if (mem && fsHandleOk(mem.handle)) return Promise.resolve(mem.handle);
    return idbRun('readonly', function (st) { return st.get(s.id); }).then(function (rec) { return rec && fsHandleOk(rec.handle) ? rec.handle : null; });
  }
  // /clear 응답을 받은 탭: 옛 세션의 핸들(같은 세션의 폴더)을 새 세션으로 옮겨 저장한다. 옛 세션의 핸들은 그대로 둔다
  // The tab that got the /clear answer carries the old session's handle (the same session's folder) to the new one and stores it;
  // the old session keeps its handle
  function fsCarry(oldId, s) {
    const f = S.fs[oldId];
    if (!s || !s.id || !isBrowser(s) || !f || !fsHandleOk(f.handle)) return;
    S.fs[s.id] = { handle: f.handle, name: f.name, perm: f.perm };
    fsSave(s.id, f.name, f.handle);
  }
  // 읽기 · 쓰기 권한: 'granted' | 'prompt' | 'denied'. ask = requestPermission(제스처 안). 메서드가 없는 브라우저는 허용으로 본다
  // Read-write permission: 'granted' | 'prompt' | 'denied'; ask = requestPermission (inside a gesture). Browsers without the method count as granted
  function fsPerm(h, ask) {
    const fn = h && (ask ? h.requestPermission : h.queryPermission);
    if (typeof fn !== 'function') return Promise.resolve('granted');
    let p;
    try { p = fn.call(h, { mode: 'readwrite' }); } catch (e) { return Promise.resolve('prompt'); }
    return Promise.resolve(p).then(function (st) { return st === 'granted' || st === 'denied' ? st : 'prompt'; }, function () { return 'prompt'; });
  }
  function fsEnt() { return S.cur ? S.fs[S.cur.id] || null : null; }
  function fsReady() { const f = fsEnt(); return !!(f && f.handle && f.perm === 'granted'); }
  // 안내 줄 상태: '' = 숨김(준비됨 · 서버 폴더 · 핸들 찾는 중) | 'nohandle' | 'prompt' | 'denied'
  // The bar state: '' hides it (ready, a server folder, or the handle still being looked up) | 'nohandle' | 'prompt' | 'denied'
  function fsBarState() {
    const c = S.cur;
    if (!c || !isBrowser(c) || S.sessLoading || S.sessErr || S.fsChk === c.id) return '';
    const f = S.fs[c.id];
    if (!f || !f.handle) return 'nohandle';
    if (f.perm === 'granted') return '';
    return f.perm === 'denied' ? 'denied' : 'prompt';
  }
  // 환경 패널 · 트리의 연결 상태 [클래스, 글](찾는 중이면 null) / the connection state for the panel and the tree [class, text] (null while looking up)
  function fsStateLabel() {
    const c = S.cur;
    if (!c || !isBrowser(c) || S.fsChk === c.id) return null;
    const f = S.fs[c.id];
    if (!f || !f.handle) return ['no', '연결 안 됨'];
    return f.perm === 'granted' ? ['ok', '연결됨'] : ['ask', '허용 필요'];
  }
  function fsWaiting() {
    const sid = S.cur ? S.cur.id : '';
    return Object.keys(S.fsReq).filter(function (k) { const q = S.fsReq[k]; return q.sid === sid && !q.running; }).length;
  }
  // 사전 문구의 {name} · {n} 등을 한 번에 채운다(넣은 값 안의 {…}는 다시 바꾸지 않는다) / fill {name}, {n} and the like in one pass (inserted values are not rescanned)
  function fmtT(ko, vars) {
    vars = vars || {};
    return T(ko).replace(/\{(\w+)\}/g, function (m, k) { return Object.prototype.hasOwnProperty.call(vars, k) ? String(vars[k]) : m; });
  }
  // 안내 줄(계약 F4). 같은 상태면 글 · 버튼만 제자리에서 바꾼다(눌린 버튼을 떼지 않게). 지원하지 않는 브라우저는 버튼 없이 안내만
  // The bar (contract F4); the same state updates the text and button in place (never detaching a pressed button). Unsupported browsers get the note only
  function paintFsBar() {
    const st = fsBarState(), bar = R.fsbar;
    S.fsBar = st;
    if (!bar) return;
    if (!st) { bar.hidden = true; bar.removeAttribute('data-state'); bar.innerHTML = ''; return; }
    const name = (S.cur && S.cur.folder) || '', n = fsWaiting(), can = fsAvail();
    const spec = !can ? [S.fsOk ? FS_OFF : FS_NO, '', '']
      : (st === 'nohandle' ? ["이 세션의 폴더 '{name}' 을(를) 이 브라우저에서 다시 열어 주세요", '폴더 열기', 'fsrelink']
        : (st === 'prompt' ? ["폴더 '{name}' 접근을 허용해 주세요", '허용', 'fsgrant'] : ['폴더 접근이 거부되었습니다', '다시 시도', 'fsgrant']));
    const key = st + (can ? '' : '!');
    if (bar.getAttribute('data-state') !== st || bar.getAttribute('data-key') !== key || !bar.querySelector('.tx')) {
      bar.setAttribute('data-state', st);
      bar.setAttribute('data-key', key);
      bar.innerHTML = '<span class="ic">' + IC.laptop + '</span><span class="tx" data-i18n-skip></span>'
        + (spec[2] ? '<button type="button" class="ai365-ag-btn sm pri" data-ag="' + spec[2] + '"></button>' : '');
    }
    bar.querySelector('.tx').textContent = fmtT(spec[0], { name: name }) + (n ? ' · ' + fmtT('에이전트가 폴더를 기다리고 있습니다({n})', { n: n }) : '');
    const b = bar.querySelector('button');
    if (b) { b.textContent = T(spec[1]); b.disabled = S.fsBusy; }
    bar.hidden = false;
  }

  // 세션을 열 때: 핸들을 찾고 권한을 (창 없이) 물어 안내 줄 · 환경 패널 · 트리를 맞춘다 / on open: find the handle, query the permission without a prompt, then sync the bar, panel and tree
  function fsAttach() {
    const c = S.cur;
    if (!c || !isBrowser(c)) return;
    const sid = c.id, tok = S.openTok;
    S.fsChk = sid;
    fsFind(c).then(function (h) {
      if (tok !== S.openTok) return null;
      if (!h) { delete S.fs[sid]; return null; }
      const old = S.fs[sid];
      S.fs[sid] = { handle: h, name: String(h.name || ''), perm: old && old.handle === h ? old.perm : '' };   // name = 실제 폴더 이름 / the real folder name
      return fsPerm(h, false).then(function (perm) { const f = S.fs[sid]; if (f && f.handle === h) f.perm = perm; });
    }).catch(noop).then(function () {
      if (tok !== S.openTok) return;
      if (S.fsChk === sid) S.fsChk = '';
      fsChanged(true);
    });
  }
  // 핸들 · 권한이 바뀐 뒤: 안내 줄 · 환경 패널 · 트리 · 뷰어 · 대기 요청(reset = 트리를 새 핸들에서 다시) / after a handle or permission change (reset = reload the tree from the new handle)
  function fsChanged(reset) {
    if (!S.on || !S.cur || !isBrowser()) return;
    paintFsBar(); paintSec('env');
    if (fsReady()) {
      if (S.tree && S.tree.browser) {
        if (reset || !S.tree.nodes[''] || !S.tree.nodes[''].entries) {
          S.tree.nodes = {};
          loadDir('');
          Object.keys(S.tree.open).forEach(function (p) { if (S.tree.open[p]) loadDir(p); });
        } else refreshTree();
      }
      refreshViewer();
      fsPump(); fsSync();
    }
    paintSec('files');
  }
  // 권한 오류(denied) 뒤 다시 물어 본다(창 없이) / re-query after a denied answer (no prompt)
  function fsRecheck(sid) {
    const f = S.fs[sid];
    if (!f || !f.handle) return;
    fsPerm(f.handle, false).then(function (perm) {
      const g = S.fs[sid];
      if (!g || g.handle !== f.handle || g.perm === perm) return;
      g.perm = perm;
      if (S.cur && S.cur.id === sid) fsChanged(false);
    });
  }

  // 선택 창: 제스처 안에서 바로 부른다. mode 를 모르는 브라우저(TypeError)는 인자 없이 다시. 취소(AbortError) = null
  // The picker, called at once inside the gesture; a browser that rejects the options (TypeError) is retried without them; a cancel (AbortError) gives null
  function fsPick() {
    let p;
    try { p = window.showDirectoryPicker({ id: 'ai365-agentic', mode: 'readwrite', startIn: 'desktop' }); } catch (e) { p = Promise.reject(e); }
    return Promise.resolve(p).catch(function (err) {
      if (err && (err.name === 'TypeError' || err instanceof TypeError)) return window.showDirectoryPicker();
      throw err;
    }).then(function (h) { return fsHandleOk(h) ? h : null; }, function (err) {
      if (err && err.name === 'AbortError') return null;
      throw err;
    });
  }
  function fsPickErr() { say(T('폴더 선택 창을 열지 못했습니다')); }
  function fsDefaults() {
    const st = S.settings || {};
    return { model: st.default_model || (S.models[0] && S.models[0].id) || '',
      perm_mode: st.default_perm === 'ask' || (st.default_perm === 'plan' && v2()) ? st.default_perm : 'auto' };
  }
  // POST /sessions {kind:'browser', folder: 핸들 이름, …}(계약 E) → 핸들을 메모리 · IndexedDB 에 / … then keep the handle in memory and IndexedDB
  function fsCreate(h, fields) {
    return api(BASE + '/sessions', 'POST', withActing(Object.assign({ kind: 'browser', folder: h.name }, fields || {}))).then(function (r) {
      const s = r && r.session;
      if (!s || !s.id) throw new Error(T('세션을 불러오지 못했습니다'));
      S.fs[s.id] = { handle: h, name: String(h.name || ''), perm: '' };
      fsSave(s.id, h.name, h);
      return s;
    });
  }
  function fsOpenNew(s) { if (!s || !S.on) return; upsert(s); openSession(s.id); }
  // 새 세션 대화 상자의 [내 컴퓨터 폴더 열기…]: 고른 폴더 + 대화 상자의 제목 · 모델 · 권한 모드로 만든다(계약 F2)
  // [Open a folder on my computer…] in the new-session dialog: create with the picked folder and the dialog's title, model and mode (contract F2)
  function fsDialogOpen(d, btn) {
    if (S.fsBusy) return;
    S.fsBusy = true;
    const picked = fsPick();   // 제스처 안 / inside the gesture
    btn.disabled = true;
    picked.then(function (h) {
      S.fsBusy = false;
      if (S.dlg !== d) return null;
      btn.disabled = false;
      if (!h) return null;   // 취소 = 아무것도 안 함 / a cancel does nothing
      const val = function (f) { const el = d.el.querySelector('[data-ag-f="' + f + '"]'); return el ? el.value.trim() : ''; };
      const fields = { model: val('model'), perm_mode: val('perm') || 'auto' }, title = val('title');
      if (title) fields.title = title;
      dlgErr(d, ''); dlgBusy(d, true);
      return fsCreate(h, fields).then(function (s) {
        if (S.dlg !== d) { if (S.on) upsert(s); return; }
        closeDialog();
        fsOpenNew(s);
      }, function (err) {
        if (S.dlg !== d) return;
        dlgBusy(d, false); dlgErr(d, err.message);
      });
    }, function () {
      S.fsBusy = false;
      if (S.dlg === d) btn.disabled = false;
      fsPickErr();
    });
  }
  // 빈 화면의 [내 컴퓨터 폴더 열기]: 선택 창 → 설정 기본 모델 · 권한으로 만든다 / the empty state's button: picker, then create with the default model and mode
  function fsQuickOpen() {
    if (S.fsBusy || !S.on) return;
    S.fsBusy = true;
    const picked = fsPick();   // 제스처 안 / inside the gesture
    const b = R.tx && R.tx.querySelector('[data-ag="fsopen"]');
    if (b) b.disabled = true;   // 제자리에서(눌린 버튼을 떼지 않게) / in place, never detaching the pressed button
    picked.then(function (h) {
      S.fsBusy = false;
      if (!h || !S.on) { if (S.on && !S.cur) paintTranscript(); return null; }
      S.fsMaking = true;
      if (!S.cur) paintTranscript();
      return fsCreate(h, fsDefaults()).then(function (s) { S.fsMaking = false; fsOpenNew(s); }, function (err) {
        S.fsMaking = false;
        if (S.on && !S.cur) paintTranscript();
        say(err.message);
      });
    }, function () { S.fsBusy = false; if (S.on && !S.cur) paintTranscript(); fsPickErr(); });
  }
  // 채팅 컴포저 + 메뉴(adapter G 절): 제스처 안에서 선택 창 → showView('work') 로 셸 마운트 → 첫 불러오기가 끝나면 만들어 연다
  // The chat composer's + menu (adapter, section G): picker inside the gesture, showView('work') mounts the shell, then create and open once loaded
  function fsOpenFromComposer() {
    if (typeof window.showDirectoryPicker !== 'function' || S.fsBusy) return Promise.resolve(null);
    S.fsOk = true;
    S.fsBusy = true;
    return fsPick().then(function (h) {
      S.fsBusy = false;
      if (!h) return null;
      return new Promise(function (resolve) {
        if (S.fsPend) S.fsPend.resolve(null);   // 앞서 기다리던 것은 새것으로 바꾼다 / an older pending pick is replaced
        S.fsPend = { handle: h, resolve: resolve };
        if (!S.on && typeof window.showView === 'function') window.showView('work');   // 마운트 → load() 끝에서 fsRunPend / mount; load() ends with fsRunPend
        if (!S.on) { S.fsPend = null; resolve(null); return; }   // 메뉴 권한이 없어 셸이 열리지 않았다 / the shell did not open (no menu permission)
        if (S.ready) fsRunPend();
      });
    }, function () { S.fsBusy = false; fsPickErr(); return null; });
  }
  // 셸이 마운트되고 첫 불러오기(설정 · 세션 목록)가 끝나면 기다리던 + 메뉴 세션을 만든다 → 기다리던 것이 있었으면 true
  // Once mounted and loaded (settings and the session list), create the waiting + menu session → true when one was waiting
  function fsRunPend() {
    const p = S.fsPend;
    if (!p || !S.on) return false;
    S.fsPend = null;
    if (S.bfOff) { say(T(FS_OFF)); p.resolve(null); return false; }   // 서버가 껐다 → 만들지 않고 셸만 / turned off by the server: no session, just the shell
    S.fsMaking = true;
    renderAll();
    fsCreate(p.handle, fsDefaults()).then(function (s) { S.fsMaking = false; fsOpenNew(s); p.resolve(s); }, function (err) {
      S.fsMaking = false;
      if (S.on) renderAll();
      say(err.message);
      p.resolve(null);
    });
    return true;
  }
  // 메뉴 '폴더 다시 연결…' · 안내 줄 [폴더 열기]: 선택 창 → 세션 폴더와 이름이 다르면 window.confirm 으로 확인받은 뒤에만 연결하고(적대 검토
  // 2026-10-20, 종전 계약 F4 의 토스트 대신), 저장 이름은 실제 폴더 이름(세션 제목 · 폴더 이름은 그대로)
  // The menu's 'Reconnect folder…' and the bar's [Open folder]: picker; a folder named unlike the session folder connects only after
  // a window.confirm (review 2026-10-20, replacing contract F4's toast), stored under its real name (the session title and folder stay)
  function fsRelink() {
    const c = S.cur;
    if (!c || !isBrowser(c) || !fsAvail() || S.fsBusy) return;
    const sid = c.id;
    S.fsBusy = true;
    const picked = fsPick();   // 제스처 안 / inside the gesture
    paintFsBar();
    picked.then(function (h) {
      S.fsBusy = false;
      if (!h) { paintFsBar(); return null; }   // 취소 / cancelled
      if (h.name !== c.folder && !window.confirm(fmtT("세션 폴더 '{folder}' 과 이름이 다른 폴더입니다: {name}. 이 폴더를 연결할까요?", { folder: c.folder, name: h.name }))) {
        paintFsBar();
        return null;
      }
      S.fs[sid] = { handle: h, name: String(h.name || ''), perm: '' };
      fsSave(sid, h.name, h);
      return fsPerm(h, false).then(function (perm) {
        const f = S.fs[sid];
        if (f && f.handle === h) f.perm = perm;
        if (S.cur && S.cur.id === sid) fsChanged(true); else paintFsBar();
      });
    }, function () { S.fsBusy = false; paintFsBar(); fsPickErr(); });
  }
  // 안내 줄 [허용] · [다시 시도]: 제스처 안에서 requestPermission / the bar's [Allow] and [Retry]: requestPermission inside the gesture
  function fsGrant() {
    const c = S.cur, f = c && S.fs[c.id];
    if (!f || !f.handle || S.fsBusy) return;
    const sid = c.id, h = f.handle;
    S.fsBusy = true;
    const asked = fsPerm(h, true);   // 제스처 안 / inside the gesture
    paintFsBar();
    asked.then(function (perm) {
      S.fsBusy = false;
      const g = S.fs[sid];
      if (g && g.handle === h) g.perm = perm;
      if (S.cur && S.cur.id === sid) fsChanged(false); else paintFsBar();
    });
  }

  /* 도구 요청(계약 F3): 스트림의 tool_request · GET …/tool-requests 로 받아 핸들이 준비되면 실행하고 POST …/tool-results 로 답한다.
     409(다른 탭이 먼저 답함) · 404(이미 끝남)는 무시한다. Tool requests (contract F3): received from the stream's tool_request and
     GET …/tool-requests, run once the handle is ready and answered with POST …/tool-results; 409 (another tab answered first)
     and 404 (already finished) are ignored. */
  function fsAdd(sid, r) {
    const id = String(r.request_id);
    if (S.fsReq[id] || S.fsSeen[id]) return false;
    S.fsReq[id] = { id: id, sid: sid, op: String(r.op || ''), args: (r.args && typeof r.args === 'object') ? r.args : {}, at: Date.now(), running: false };
    return true;
  }
  function onToolRequest(p) {
    if (!p || !p.request_id || !S.cur) return;
    const id = String(p.request_id);
    if (p.done) {   // 누군가 답했거나 시간 초과 · 중단 · 삭제로 끝났다 / answered by someone, or ended by a timeout, stop or delete
      S.fsSeen[id] = true;
      if (S.fsOut[id]) fsSettle(id);   // 아직 보내던 답은 그만 보낸다 / stop retrying an undelivered answer
      else if (S.fsReq[id] && !S.fsReq[id].running) delete S.fsReq[id];
      paintFsBar();
      return;
    }
    if (!isBrowser() || (p.session_id && String(p.session_id) !== S.cur.id)) return;
    if (fsAdd(S.cur.id, p)) { paintFsBar(); fsPump(); }
  }
  // 대기 요청을 서버 목록과 맞춘다: 새것은 넣고, 이 GET 보다 먼저 받았는데 목록에 없는 것은 끝난 것이라 뺀다
  // Sync with the server's list: add new ones; ones received before this GET but missing from the list are finished and dropped
  function fsSync() {
    const c = S.cur;
    if (!S.on || !c || !isBrowser(c)) return;
    const sid = c.id, tok = S.openTok, t0 = Date.now();
    fsResend(sid);   // 보관한 답 먼저 / the stored answers first
    api(sessUrl(sid, '/tool-requests') + qs()).then(function (d) {
      if (tok !== S.openTok) return;
      const live = {};
      ((d && Array.isArray(d.requests)) ? d.requests : []).forEach(function (r) { if (r && r.request_id) { live[String(r.request_id)] = true; fsAdd(sid, r); } });
      Object.keys(S.fsReq).forEach(function (k) { const q = S.fsReq[k]; if (q.sid === sid && !q.running && q.at < t0 && !live[k]) delete S.fsReq[k]; });
      paintFsBar(); fsPump();
    }).catch(noop);   // 다음 접속 때 다시 / retried on the next connect
  }
  function fsPump() {
    if (!S.cur || !fsReady()) { paintFsBar(); return; }
    const sid = S.cur.id;
    Object.keys(S.fsReq).forEach(function (k) { const q = S.fsReq[k]; if (q.sid === sid && !q.running) fsRun(q); });
  }
  function fsRun(q) {
    const f = S.fs[q.sid];
    if (!f || !f.handle) return;
    q.running = true;
    fsExec(f.handle, q.op, q.args).then(function (result) { return { ok: true, result: result, error: '', code: '' }; }, function (err) {
      const e = fsMap(err, 'exec', (q.args || {}).path);
      return { ok: false, result: null, error: e.message, code: e.fsCode };
    }).then(function (ans) {
      if (ans.code === 'denied') fsRecheck(q.sid);
      fsSend(q, withActing(Object.assign({ request_id: q.id }, ans)));
    });
  }
  /* 답 보내기(적대 검토 2026-10-20 MEDIUM): 2xx · 404(모름) · 409(이미 끝남) · 그 밖 4xx 면 끝, HTTP 상태가 없는 실패(네트워크 ·
     서버 재시작)와 5xx 는 답을 보관하고 1 · 2 · 4 · 4초 뒤 다시(모두 5번). 그래도 못 보내면 보관해 두고 재접속(fsSync) 때 먼저 다시 보낸다.
     Sending an answer (review 2026-10-20, MEDIUM): 2xx, 404 (unknown), 409 (finished) and other 4xx settle it; a failure without
     an HTTP status (network, server restart) and 5xx keep the answer and retry after 1, 2, 4 and 4 s (five tries in all). Still
     undelivered, it stays stored and goes out first on the next reconnect (fsSync). */
  const FS_SEND_TRIES = 5, FS_SEND_WAIT = [1000, 2000, 4000, 4000];
  function fsSend(q, body) {
    const o = S.fsOut[q.id] || (S.fsOut[q.id] = { q: q, body: body, tries: 0, timer: null, busy: false });
    if (o.busy) return;
    clearTimeout(o.timer); o.timer = null;
    o.busy = true; o.tries += 1;
    api(sessUrl(q.sid, '/tool-results'), 'POST', o.body).then(function () { fsSettle(q.id); }, function (err) {
      o.busy = false;
      if (S.fsOut[q.id] !== o) return;   // 그사이 done 으로 끝났다 / finished meanwhile by a done notice
      if (err && err.status && err.status < 500) { fsSettle(q.id); return; }
      if (o.tries < FS_SEND_TRIES) o.timer = setTimeout(function () { fsSend(q, o.body); }, FS_SEND_WAIT[Math.min(o.tries, FS_SEND_WAIT.length) - 1]);
    });
  }
  // 끝난 요청: 보관한 답 · 대기 줄을 걷고 다시 받지 않는다 / a finished request: drop the stored answer and the entry, never take it again
  function fsSettle(id) {
    const o = S.fsOut[id];
    if (o) { clearTimeout(o.timer); delete S.fsOut[id]; }
    delete S.fsReq[id];
    S.fsSeen[id] = true;
    paintFsBar();
  }
  // 재접속 때 보관한 답을 먼저 보낸다(시도 횟수는 새로) / on a reconnect, send the stored answers first (tries start over)
  function fsResend(sid) {
    Object.keys(S.fsOut).forEach(function (k) { const o = S.fsOut[k]; if (o.q.sid === sid && !o.busy) { o.tries = 0; fsSend(o.q, o.body); } });
  }
  // 턴이 끝나면(서버가 남은 요청을 정리했다) 기다리던 것을 걷는다 / at the end of a turn (the server dropped what was left) clear the waiting ones
  function fsDropWaiting() {
    const sid = S.cur ? S.cur.id : '';
    let n = 0;
    Object.keys(S.fsReq).forEach(function (k) { const q = S.fsReq[k]; if (q.sid === sid && !q.running) { delete S.fsReq[k]; n += 1; } });
    if (n) paintFsBar();
  }

  /* 원시 op(계약 B2): 경로는 폴더 기준 상대('/' 구분, '' = 폴더). 오류 = fsErr(code): outside · notfound · isdir · notdir · toolarge ·
     denied · exec. 결과 모양 · 상한은 서버 LocalExecutor 와 같게 맞춘다(목록 500 · 훑기 50,000 · 검색 파일당 5MB · 줄 300자).
     Primitive ops (contract B2): folder-relative paths ('/'-separated, '' = the folder); errors carry a contract code; result shapes
     and caps follow the server's LocalExecutor (500 entries, 50,000 files scanned, 5 MB per searched file, 300-character lines). */
  function fsErr(code, msg) { const e = new Error(msg || code); e.fsCode = code; return e; }
  // DOMException → 계약 오류 코드. kind: dir(대상이 폴더) · file(대상이 파일) · path(중간 조각: 다른 종류 = 없음) · mkdir(만들며 내려감)
  // DOMException → a contract code; kind: dir (the target is a folder), file (a file), path (a middle segment: wrong type = missing), mkdir (creating on the way)
  function fsMap(e, kind, path) {
    if (e && e.fsCode) return e;
    const n = e && e.name, p = String(path === null || path === undefined ? '' : path);
    if (n === 'NotAllowedError' || n === 'SecurityError') return fsErr('denied', '브라우저가 폴더 접근을 거부했습니다');
    if (n === 'NotFoundError') return fsErr('notfound', (kind === 'dir' ? '폴더가 없습니다: ' : '파일이 없습니다: ') + p);
    if (n === 'TypeMismatchError') {
      if (kind === 'file') return fsErr('isdir', '폴더입니다: ' + p);
      if (kind === 'path') return fsErr('notfound', '파일이 없습니다: ' + p);
      return fsErr('notdir', '폴더가 아닙니다: ' + p);
    }
    return fsErr('exec', (e && e.message) ? String(e.message) : String(e || '실행하지 못했습니다'));
  }
  // 경로 규칙(계약 F3): '\'→'/', 앞 './' 제거, 빈 값 = 폴더, 절대 경로('/', 'X:') · '..' = outside. 폴더 이름 접두는 벗기지 않는다:
  // 서버가 보내는 도구 요청 경로는 이미 정규화 · 접두 제거가 끝난 값이라(계약 변경 기록 2026-10-20) 한 번 더 벗기면 같은 이름의
  // 하위 폴더('경동/경동/a.txt')에서 다른 파일을 연다. 화면의 "<이름>/<rel>"(산출물)은 fsOutRel 이 벗긴다
  // Path rules (contract F3): '\' becomes '/', a leading './' goes, empty = the folder, absolute ('/', 'X:') or '..' = outside. The
  // folder-name prefix is not stripped: tool-request paths arrive normalized with it already removed (contract change log,
  // 2026-10-20), and stripping again would open another file under a same-named subfolder; fsOutRel strips the screen's "<name>/<rel>"
  function fsParts(path) {
    let p = String(path === null || path === undefined ? '' : path).replace(/\\/g, '/');
    if (p.charAt(0) === '/' || /^[A-Za-z]:/.test(p)) throw fsErr('outside', '폴더 밖 경로는 쓸 수 없습니다: ' + path);
    while (p.indexOf('./') === 0) p = p.slice(2);
    const parts = p.split('/').filter(function (x) { return x !== '' && x !== '.'; });
    if (parts.indexOf('..') >= 0) throw fsErr('outside', '폴더 밖 경로는 쓸 수 없습니다: ' + path);
    return parts;
  }
  async function fsDir(root, parts, create, kind, path) {
    let d = root;
    for (let i = 0; i < parts.length; i++) {
      try { d = await d.getDirectoryHandle(parts[i], create ? { create: true } : undefined); } catch (e) { throw fsMap(e, kind, path); }
    }
    return d;
  }
  async function fsFileAt(root, parts, path) {
    const dir = await fsDir(root, parts.slice(0, -1), false, 'path', path);
    try { return await dir.getFileHandle(parts[parts.length - 1]); } catch (e) { throw fsMap(e, 'file', path); }
  }
  // 폴더 항목을 하나씩(fn 이 false 면 멈춤) / each folder entry in turn (stops when fn returns false)
  async function fsEach(dir, fn) {
    if (typeof dir.entries === 'function') {
      for await (const pair of dir.entries()) { if (fn(pair[0], pair[1]) === false) return; }
    } else if (typeof dir.values === 'function') {
      for await (const h of dir.values()) { if (fn(h.name, h) === false) return; }
    }
  }
  // 순서를 지키며 동시에 FS_PAR 개씩 / FS_PAR at a time, order kept
  async function fsPool(items, fn) {
    const out = new Array(items.length);
    let i = 0;
    const worker = async function () { while (i < items.length) { const k = i++; out[k] = await fn(items[k]); } };
    const ws = [];
    for (let w = 0; w < Math.min(FS_PAR, items.length); w++) ws.push(worker());
    await Promise.all(ws);
    return out;
  }
  function fsDenied(e) { return !!(e && (e.name === 'NotAllowedError' || e.name === 'SecurityError' || e.fsCode === 'denied')); }
  function fsClamp(v, lo, hi, def) { const n = Math.trunc(Number(v)); return Math.max(lo, Math.min(hi, isFinite(n) ? n : def)); }
  function fsSkip(list) { const o = {}; (Array.isArray(list) ? list : []).forEach(function (x) { o[String(x)] = true; }); return o; }
  function extOf(name) { const m = /\.([^./\\]+)$/.exec(String(name || '')); return m ? m[1].toLowerCase() : ''; }
  // 수정 시각 = File.lastModified(밀리초 숫자, 모르면 null). 서버가 숫자를 받아 바꾼다(시간대 없는 ISO 글의 함정을 피한다, 적대 검토 2026-10-20)
  // mtime = File.lastModified (milliseconds, null when unknown); the server converts the number (avoiding the naive-ISO time-zone trap; review 2026-10-20)
  function fsMtime(f) { const n = Number(f && f.lastModified); return isFinite(n) && n > 0 ? n : null; }
  // 바이트 → {text, enc} 또는 null(이진). 서버 _decode_text 와 같은 순서: BOM → 앞 8KB 의 NUL → UTF-8 → cp949 → 대체 문자.
  // partial = 앞부분만 읽음(잘린 마지막 UTF-8 글자를 뺀다) / Bytes → {text, enc} or null (binary), in the server's order; partial drops a cut last UTF-8 character
  function fsDecode(buf, partial) {
    const dec = function (label, fatal, b) { try { return new TextDecoder(label, { fatal: !!fatal }).decode(b || buf); } catch (e) { return null; } };
    if (buf.length >= 3 && buf[0] === 0xEF && buf[1] === 0xBB && buf[2] === 0xBF) return { text: dec('utf-8', false) || '', enc: 'utf-8-sig' };
    if (buf.length >= 2 && ((buf[0] === 0xFF && buf[1] === 0xFE) || (buf[0] === 0xFE && buf[1] === 0xFF))) {
      const le = buf[0] === 0xFF, u = dec(le ? 'utf-16le' : 'utf-16be', true);
      if (u !== null) return { text: u, enc: 'utf-16', le: le };   // le = 바이트 순서(쓸 때 그대로) / the byte order, kept on write
    }
    if (buf.subarray(0, 8192).indexOf(0) >= 0) return null;
    if (partial) {
      for (let k = 0; k < 4 && k < buf.length; k++) { const c = dec('utf-8', true, buf.subarray(0, buf.length - k)); if (c !== null) return { text: c, enc: 'utf-8' }; }
    }
    let t = dec('utf-8', true);
    if (t !== null) return { text: t, enc: 'utf-8' };
    t = dec('euc-kr', true);
    if (t !== null) return { text: t, enc: 'cp949' };
    return { text: dec('utf-8', false) || '', enc: 'utf-8' };
  }
  // glob → 정규식(서버 agentic_exec._glob_body 와 같은 규칙: ** · * · ? · [...] · {a,b}, 대소문자 무시)
  // glob → regex (the server's agentic_exec._glob_body rules: **, *, ?, [...], {a,b}; case-insensitive)
  function fsGlobBody(pat) {
    let out = '', i = 0;
    while (i < pat.length) {
      const c = pat.charAt(i);
      if (c === '*') {
        if (pat.substr(i, 2) === '**') {
          if (pat.charAt(i + 2) === '/') { out += '(?:.*/)?'; i += 3; continue; }
          out += '.*'; i += 2; continue;
        }
        out += '[^/]*';
      } else if (c === '?') out += '[^/]';
      else if (c === '[') {
        const j = pat.indexOf(']', i + 1);
        if (j < 0) out += '\\[';
        else {
          let cls = pat.slice(i + 1, j);
          if (cls.charAt(0) === '!') cls = '^' + cls.slice(1);
          out += '[' + cls.replace(/\\/g, '\\\\') + ']';
          i = j + 1;
          continue;
        }
      } else if (c === '{') {
        const j = pat.indexOf('}', i + 1);
        if (j < 0) out += '\\{';
        else { out += '(?:' + pat.slice(i + 1, j).split(',').map(fsGlobBody).join('|') + ')'; i = j + 1; continue; }
      } else out += c.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&');
      i += 1;
    }
    return out;
  }
  function fsGlobRx(g) {
    try { return new RegExp('^' + fsGlobBody(g) + '$', 'i'); } catch (e) { throw fsErr('exec', 'glob 이 올바르지 않습니다: ' + (e && e.message ? e.message : e)); }
  }
  // 문서(pdf · docx · pptx · xlsx) 본문: POST /api/agentic/extract(multipart file + acting_user_id) → {text, truncated}
  // Document text: POST /api/agentic/extract (multipart file plus acting_user_id) → {text, truncated}
  function fsExtract(file, fname) {
    const fd = new FormData();
    fd.append('file', file, fname);
    fd.append('acting_user_id', acting());
    return fetch(BASE + '/extract' + qs(), { method: 'POST', body: fd }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (d) {
        if (res.status === 413) throw fsErr('toolarge', detailOf(d) || '파일이 너무 큽니다');
        if (!res.ok) throw fsErr('exec', detailOf(d) || ('문서 본문을 읽지 못했습니다(HTTP ' + res.status + ')'));
        return { text: String((d && d.text) || ''), truncated: !!(d && d.truncated) };
      });
    }, function () { throw fsErr('exec', '문서 본문을 읽지 못했습니다(네트워크 오류)'); });
  }
  function fsExec(root, op, args) {
    const fn = { list: fsList, read: fsRead, write: fsWrite, walk: fsWalk, grep: fsGrep }[op];
    if (!fn) return Promise.reject(fsErr('exec', '알 수 없는 요청입니다: ' + op));
    return Promise.resolve().then(function () { return fn(root, args && typeof args === 'object' ? args : {}); });
  }
  // list {path} → {entries:[{name, type, size, mtime}], truncated, total}: 폴더 먼저 · 이름순 500개(정렬은 서버도 한다)
  // list → the first 500 entries, folders first then by name (the server sorts too)
  async function fsList(root, args) {
    const path = String(args.path || ''), dir = await fsDir(root, fsParts(args.path), false, 'dir', path), all = [];
    try { await fsEach(dir, function (n, h) { all.push({ name: n, h: h, d: h.kind === 'directory' }); }); } catch (e) { throw fsMap(e, 'dir', path); }
    all.sort(function (a, b) {
      if (a.d !== b.d) return a.d ? -1 : 1;
      const x = a.name.toLowerCase(), y = b.name.toLowerCase();
      return x < y ? -1 : (x > y ? 1 : 0);
    });
    const entries = await fsPool(all.slice(0, FS_LIST_MAX), async function (x) {
      if (x.d) return { name: x.name, type: 'dir', size: 0, mtime: null };
      try { const f = await x.h.getFile(); return { name: x.name, type: 'file', size: f.size, mtime: fsMtime(f) }; }
      catch (e) { if (fsDenied(e)) throw fsMap(e); return { name: x.name, type: 'file', size: 0, mtime: null }; }
    });
    return { entries: entries, truncated: all.length > FS_LIST_MAX, total: all.length };
  }
  // read {path, max_bytes} → {text, size, binary, extracted, truncated, encoding}: 문서는 /extract, 이진(앞 8KB 의 NUL)은 빈 글
  // read → documents through /extract, binaries (a NUL in the first 8 KB) with empty text
  async function fsRead(root, args) {
    const path = String(args.path || ''), parts = fsParts(args.path);
    if (!parts.length) throw fsErr('isdir', '폴더입니다: ' + path);
    const fh = await fsFileAt(root, parts, path);
    let file, buf;
    try { file = await fh.getFile(); } catch (e) { throw fsMap(e, 'file', path); }
    const max = Number(args.max_bytes) > 0 ? Number(args.max_bytes) : FS_MAX_BYTES, leaf = parts[parts.length - 1];
    if (file.size > max) throw fsErr('toolarge', '파일이 너무 큽니다(10MB 초과)');
    if (FS_DOC[extOf(leaf)]) {
      const x = await fsExtract(file, leaf);
      return { text: x.text, size: file.size, binary: false, extracted: true, truncated: x.truncated };
    }
    try { buf = new Uint8Array(await file.arrayBuffer()); } catch (e) { throw fsMap(e, 'file', path); }
    const d = fsDecode(buf, false);
    if (!d) return { text: '', size: file.size, binary: true, extracted: false, truncated: false };
    return { text: d.text, size: file.size, binary: false, extracted: false, truncated: false, encoding: d.enc };
  }
  // UTF-8 BOM · UTF-16(바이트 순서 그대로) 바이트. null = BOM 없는 UTF-8(문자열을 그대로 쓴다). TextEncoder 는 UTF-8 만이라 UTF-16 은
  // 손으로 만든다(JS 문자열 = UTF-16 코드 단위) / bytes for UTF-8 with a BOM or UTF-16 (byte order kept); null = UTF-8 without a BOM
  // (the string is written as is). TextEncoder is UTF-8 only, so UTF-16 is built by hand (JS strings are UTF-16 code units)
  function fsEncode(text, enc) {
    if (enc === 'utf-8-sig') {
      const b = new TextEncoder().encode(text), out = new Uint8Array(b.length + 3);
      out.set([0xEF, 0xBB, 0xBF]); out.set(b, 3);
      return out;
    }
    if (enc === 'utf-16le' || enc === 'utf-16be') {
      const le = enc === 'utf-16le', out = new Uint8Array(2 + text.length * 2);
      out[0] = le ? 0xFF : 0xFE; out[1] = le ? 0xFE : 0xFF;
      for (let i = 0; i < text.length; i++) {
        const c = text.charCodeAt(i), j = 2 + i * 2;
        out[le ? j : j + 1] = c & 0xFF;
        out[le ? j + 1 : j] = c >> 8;
      }
      return out;
    }
    return null;
  }
  // write {path, text} → {created, bytes, old_text}: 빠진 상위 폴더는 만든다. old_text = 있던 글 파일(10MB 이하)의 이전 본문,
  // 새 파일 · 이진이면 null(서버 LocalExecutor 처럼 diff 없음). 있던 글 파일의 인코딩은 지킨다(서버 폴더의 LocalExecutor.edit 처럼,
  // 적대 검토 2026-10-20): UTF-8 BOM · UTF-16 LE/BE 는 BOM 째로, cp949 는 브라우저가 인코딩할 수 없어 쓰지 않고 exec 오류. 새 파일 ·
  // 이진 덮어쓰기는 UTF-8. bytes = 실제로 쓴 바이트 수(BOM 포함)
  // write → missing parent folders are created; old_text is the previous text of an existing text file (10 MB or less), null for a
  // new or binary file (no diff, as in the server's LocalExecutor). An existing text file keeps its encoding (like LocalExecutor.edit
  // for server folders; review 2026-10-20): UTF-8 with a BOM and UTF-16 LE/BE keep their BOM, cp949 cannot be encoded by a browser
  // and is refused with an exec error; new files and binary overwrites are UTF-8. bytes = the bytes actually written (BOM included)
  async function fsWrite(root, args) {
    const path = String(args.path || ''), parts = fsParts(args.path);
    if (!parts.length) throw fsErr('isdir', '폴더입니다: ' + path);
    const text = args.text === null || args.text === undefined ? '' : String(args.text), utf8 = new TextEncoder().encode(text).length;
    if (utf8 > FS_MAX_BYTES) throw fsErr('toolarge', '내용이 너무 큽니다(10MB 초과)');
    const dir = await fsDir(root, parts.slice(0, -1), true, 'mkdir', path), leaf = parts[parts.length - 1];
    let fh = null, created = false, old = null, enc = 'utf-8', w = null;
    try { fh = await dir.getFileHandle(leaf); } catch (e) {
      if (!e || e.name !== 'NotFoundError') throw fsMap(e, 'file', path);
      created = true;
    }
    if (fh) {
      try {
        const f = await fh.getFile();
        if (f.size <= FS_MAX_BYTES) {
          const d = fsDecode(new Uint8Array(await f.arrayBuffer()), false);
          if (d) { old = d.text; enc = d.enc === 'utf-16' ? (d.le ? 'utf-16le' : 'utf-16be') : d.enc; }
        }
      } catch (e) { if (fsDenied(e)) throw fsMap(e); old = null; }
    }
    if (enc === 'cp949') throw fsErr('exec', 'cp949 파일은 브라우저 세션에서 다시 쓸 수 없습니다. UTF-8 로 바꿔 두세요');
    const data = fsEncode(text, enc), bytes = data ? data.length : utf8;
    if (bytes > FS_MAX_BYTES) throw fsErr('toolarge', '내용이 너무 큽니다(10MB 초과)');
    if (!fh) { try { fh = await dir.getFileHandle(leaf, { create: true }); } catch (e) { throw fsMap(e, 'file', path); } }
    try {
      w = await fh.createWritable();
      await w.write(data || text);
      await w.close();
    } catch (e) {
      if (w && typeof w.abort === 'function') { try { await w.abort(); } catch (x) { /* 이미 닫힘 / already closed */ } }
      throw fsMap(e, 'file', path);
    }
    return { created: created, bytes: bytes, old_text: old };
  }
  // 폴더 아래 파일을 깊이 우선으로 모은다(skip 이름의 폴더는 들어가지 않는다, max 개 넘으면 capped). 읽지 못한 하위 폴더는 건너뛴다
  // Collect the files under a folder depth first (folders named in skip are not entered; capped past max); unreadable subfolders are skipped
  async function fsCollect(dir, prefix, skip, max, out, st) {
    const subs = [];
    try {
      await fsEach(dir, function (n, h) {
        if (h.kind === 'directory') { if (!skip[n]) subs.push([n, h]); return true; }
        if (out.length >= max) { st.capped = true; return false; }
        out.push({ rel: prefix + n, h: h });
        return true;
      });
    } catch (e) { if (fsDenied(e)) throw fsMap(e); return; }
    for (let i = 0; i < subs.length && !st.capped; i++) await fsCollect(subs[i][1], prefix + subs[i][0] + '/', skip, max, out, st);
  }
  // walk {path, skip, max} → {files:[{rel, size, mtime}], capped}. rel = path 기준 상대(서버 LocalExecutor._walk 와 같다)
  // walk → rel is relative to `path` (as the server's LocalExecutor._walk yields it)
  async function fsWalk(root, args) {
    const path = String(args.path || ''), dir = await fsDir(root, fsParts(args.path), false, 'dir', path);
    const files = [], st = { capped: false };
    await fsCollect(dir, '', fsSkip(args.skip), fsClamp(args.max, 1, FS_SCAN_MAX, FS_SCAN_MAX), files, st);
    const out = await fsPool(files, async function (x) {
      try { const f = await x.h.getFile(); return { rel: x.rel, size: f.size, mtime: fsMtime(f) }; }
      catch (e) { if (fsDenied(e)) throw fsMap(e); return { rel: x.rel, size: 0, mtime: null }; }
    });
    return { files: out, capped: st.capped };
  }
  // grep {path, pattern, flags, glob, glob_re, by_path, max_results, skip} → {matches:["rel:line:text"], count, files, truncated}.
  // rel = 세션 폴더 기준, glob = 이름(by_path 면 path 기준 경로) 글롭, 파일당 5MB · 50,000개 · 30초 · 줄 300자. flags = 서버가 패턴 앞의
  // (?i) 같은 묶음을 옮긴 것(i · m · s), glob_re = 서버가 만든 글롭 정규식(있으면 그것, 없으면 glob 을 스스로 바꾼다). 둘 다 u 플래그 없이
  // (glob_re 에 파이썬 re.escape 의 \- 같은 이스케이프가 있다, 계약 변경 기록 2026-10-20)
  // grep → rel is session-relative; glob matches the name (the path relative to `path` with by_path); 5 MB per file, 50,000 files,
  // 30 s, 300-character lines. flags carries a leading inline-flag group the server moved (i, m, s); glob_re is the server's glob regex
  // (used when present, else glob is converted here). Both are built without the u flag (glob_re holds Python re.escape escapes such
  // as \-; contract change log, 2026-10-20)
  async function fsGrep(root, args) {
    const pat = String(args.pattern === null || args.pattern === undefined ? '' : args.pattern);
    if (!pat) throw fsErr('exec', 'pattern 이 비어 있습니다');
    const flags = String(args.flags || '').replace(/[^ims]/g, '').split('').filter(function (c, i, a) { return a.indexOf(c) === i; }).join('');
    let rx, grx = null;
    try { rx = new RegExp(pat, flags); } catch (e) { throw fsErr('exec', '정규식 오류: ' + (e && e.message ? e.message : e)); }
    const path = String(args.path || ''), parts = fsParts(args.path), skip = fsSkip(args.skip);
    const mx = fsClamp(args.max_results, 1, FS_GREP_MAX, FS_GREP_DEFAULT);
    const g = String(args.glob || '').trim().replace(/\\/g, '/');
    const byPath = args.by_path === undefined || args.by_path === null ? g.indexOf('/') >= 0 : !!args.by_path;
    if (args.glob_re) {
      try { grx = new RegExp(String(args.glob_re), 'i'); } catch (e) { throw fsErr('exec', 'glob 이 올바르지 않습니다: ' + (e && e.message ? e.message : e)); }
    } else if (g) grx = fsGlobRx(g);
    const files = [], st = { capped: false };
    let prefix = '';
    if (!parts.length) await fsCollect(root, '', skip, FS_SCAN_MAX, files, st);
    else {
      const parent = await fsDir(root, parts.slice(0, -1), false, 'path', path), leaf = parts[parts.length - 1];
      let dir = null;
      try { dir = await parent.getDirectoryHandle(leaf); } catch (e) {
        if (!e || e.name !== 'TypeMismatchError') throw fsMap(e, 'path', path);
        let fh;
        try { fh = await parent.getFileHandle(leaf); } catch (x) { throw fsMap(x, 'file', path); }
        files.push({ rel: leaf, h: fh, shown: parts.join('/') });   // 파일 하나(서버 _walk 처럼 이름으로 맞춘다) / a single file, matched by its name like the server's _walk
      }
      if (dir) { prefix = parts.join('/') + '/'; await fsCollect(dir, '', skip, FS_SCAN_MAX, files, st); }
    }
    const matches = [], deadline = Date.now() + FS_GREP_MS;
    let hitFiles = 0, truncated = st.capped;
    for (let i = 0; i < files.length && matches.length < mx; i++) {
      if (Date.now() > deadline) { truncated = true; break; }
      const f = files[i];
      if (grx && !grx.test(byPath ? f.rel : f.rel.slice(f.rel.lastIndexOf('/') + 1))) continue;
      let d = null;
      try {
        const file = await f.h.getFile();
        if (file.size > FS_GREP_FILE) continue;
        d = fsDecode(new Uint8Array(await file.arrayBuffer()), false);
      } catch (e) { if (fsDenied(e)) throw fsMap(e); continue; }
      if (!d) continue;   // 이진 / binary
      const lines = d.text.split(/\r\n|\r|\n/), shown = f.shown || prefix + f.rel;
      if (lines.length && lines[lines.length - 1] === '') lines.pop();   // 파이썬 splitlines 처럼 끝 빈 줄 없음 / no trailing empty line, like Python's splitlines
      let hit = false;
      for (let j = 0; j < lines.length; j++) {
        if (!rx.test(lines[j])) continue;
        matches.push(shown + ':' + (j + 1) + ':' + lines[j].slice(0, FS_GREP_LINE));
        hit = true;
        if (matches.length >= mx) { truncated = true; break; }
      }
      if (hit) hitFiles += 1;
    }
    return { matches: matches, count: matches.length, files: hitFiles, truncated: truncated };
  }

  /* 파일 트리 · 뷰어(계약 F4): 서버 /files 대신 핸들에서 읽는다. 문서 · 이진은 미리 보지 않는다.
     The file tree and viewer (contract F4) read the handle instead of the server's /files; documents and binaries get no preview. */
  function fsLoadDir(path, n) {
    const f = fsEnt();
    if (!fsReady()) { n.loading = false; paintSec('files'); return; }   // 준비되면 fsChanged 가 다시 읽는다 / fsChanged re-reads once ready
    n.loading = true;
    if (!n.entries) paintSec('files');
    const tok = S.openTok;
    fsList(f.handle, { path: path }).then(function (d) {
      if (tok !== S.openTok || !S.tree) return;
      n.loading = false; n.entries = sortEntries(d.entries); n.err = '';
      paintSec('files');
    }, function (err) {
      if (tok !== S.openTok || !S.tree) return;
      const e = fsMap(err, 'dir', path);
      n.loading = false;
      if (!n.entries) n.err = T(e.fsCode === 'notdir' ? '폴더가 아닙니다' : '폴더를 불러오지 못했습니다');
      if (e.fsCode === 'denied' && S.cur) fsRecheck(S.cur.id);
      paintSec('files');
    });
  }
  // 산출물 경로("<이름>/<rel>")를 폴더 기준으로 / an output path ("<name>/<rel>") made folder-relative
  function fsOutRel(p) {
    const s = String(p || '').replace(/\\/g, '/'), pre = ((S.cur && S.cur.folder) || '') + '/';
    return pre.length > 1 && s.indexOf(pre) === 0 ? s.slice(pre.length) : s;
  }
  async function fsPreview(rel) {
    const f = fsEnt();
    if (!fsReady()) throw fsErr('denied', '');
    const parts = rel ? rel.split('/') : [];
    if (!parts.length) return { dir: true };
    const parent = await fsDir(f.handle, parts.slice(0, -1), false, 'path', rel), leaf = parts[parts.length - 1];
    let fh, file;
    try { fh = await parent.getFileHandle(leaf); } catch (e) { if (e && e.name === 'TypeMismatchError') return { dir: true }; throw fsMap(e, 'file', rel); }
    try { file = await fh.getFile(); } catch (e) { throw fsMap(e, 'file', rel); }
    if (FS_DOC[extOf(leaf)]) return { nopreview: true, size: file.size };
    const partial = file.size > FS_VIEW_BYTES;
    const d = fsDecode(new Uint8Array(await (partial ? file.slice(0, FS_VIEW_BYTES) : file).arrayBuffer()), partial);
    if (!d) return { binary: true, size: file.size };
    const text = d.text.replace(/\r\n/g, '\n');
    return { content: text.slice(0, FS_VIEW_CHARS), truncated: partial || text.length > FS_VIEW_CHARS, size: file.size };
  }
  function fsOpenFile(path, quiet) {
    let rel = null;
    try { rel = fsParts(path).join('/'); } catch (e) { rel = null; }
    const shown = rel === null ? String(path || '') : rel, tok = S.openTok;
    if (!quiet) { S.viewer = { path: shown, loading: true, data: null, err: '' }; paintViewer(); renderHead(); paintSec('files'); }
    const mine = function () { return tok === S.openTok && S.viewer && S.viewer.kind !== 'diff' && S.viewer.path === shown; };
    (rel === null ? Promise.reject(fsErr('outside', '')) : fsPreview(rel)).then(function (d) {
      if (!mine()) return;
      if (d.dir) { S.viewer = null; if (S.tree) { S.tree.open[rel] = true; loadDir(rel); } paintViewer(); renderHead(); paintSec('files'); return; }
      S.viewer.loading = false; S.viewer.err = ''; S.viewer.data = d;
      paintViewer();
    }, function () {
      if (!mine() || (quiet && S.viewer.data)) return;
      const st = fsStateLabel();
      S.viewer.loading = false; S.viewer.err = T(!fsReady() && st ? st[1] : '파일을 불러오지 못했습니다');
      paintViewer();
    });
  }

  /* ── 이벤트 연결 / event wiring ── */
  function onSideClick(e) {
    const sb = R.sidebar, collapsed = !!(sb && sb.classList.contains('collapsed'));
    const t = e.target.closest('[data-ag], .ai365-ag-sess');
    if (!t || !R.side || !R.side.contains(t)) return;   // 빈 곳은 목업 핸들러가 접힌 사이드바를 편다 / empty spots: the mockup handler expands a collapsed sidebar
    const ag = t.getAttribute('data-ag');
    if (ag === 'collapse') { e.stopPropagation(); sb.classList.add('collapsed'); return; }
    if (ag === 'search') return;
    // 접힌 상태의 아이콘도 바로 동작한다(펼치지 않는다) / icons work in the collapsed rail too, without expanding it
    if (ag === 'new') { if (collapsed) e.stopPropagation(); openNewDialog(); return; }
    if (t.classList.contains('ai365-ag-sess')) { if (collapsed) e.stopPropagation(); if (!S.cur || S.cur.id !== t.dataset.id) openSession(t.dataset.id); }
  }
  function onSideInput(e) {
    if (e.target && e.target.matches('[data-ag="search"]')) { S.search = e.target.value; renderSideList(); }
  }
  function onHeadClick(e) {
    const t = e.target.closest('[data-ag], [data-ag-view], [data-ag-menu]');
    if (!t) return;
    const menu = t.getAttribute('data-ag-menu'), view = t.getAttribute('data-ag-view');
    if (menu) {
      setMenu(false);
      if (menu === 'rename') openRenameDialog();
      else if (menu === 'folder') showSec('files');
      else if (menu === 'folders') openFoldersDialog();
      else if (menu === 'fsrelink') fsRelink();   // 선택 창은 이 클릭 안에서 / the picker opens inside this click
      else if (menu === 'notify') toggleNotify();
      else if (menu === 'delete') openDeleteDialog();
      return;
    }
    if (view) {
      if (view === 'panel') { S.env = !S.env; if (R.shell) R.shell.classList.toggle('noenv', !S.env); renderHead(); }
      else if (view === 'transcript') { if (S.viewer) closeViewer(); else scrollBottom(); }
      else if (view === 'terminal') showSec('term');
      else if (view === 'outputs') showSec('outputs');
      else if (view === 'files') showSec('files');
      return;
    }
    const ag = t.getAttribute('data-ag');
    if (ag === 'back') goHist(-1);
    else if (ag === 'fwd') goHist(1);
    else if (ag === 'title') setMenu(!S.menu);
  }
  function onShellClick(e) {
    let t;
    if ((t = e.target.closest('[data-ag-tool]'))) { const id = t.getAttribute('data-ag-tool'); S.open[id] = !S.open[id]; repaintTool(id); return; }
    if ((t = e.target.closest('[data-ag-dec]'))) { const card = t.closest('[data-aid]'); if (card) decide(card.getAttribute('data-aid'), t.getAttribute('data-ag-dec')); return; }
    if ((t = e.target.closest('[data-ag-sec]'))) { const k = t.getAttribute('data-ag-sec'); S.shut[k] = !S.shut[k]; paintSec(k); return; }
    if ((t = e.target.closest('[data-ag-dir]'))) {
      const p = t.getAttribute('data-ag-dir');
      if (!S.tree) return;
      S.tree.open[p] = !S.tree.open[p];
      if (S.tree.open[p]) loadDir(p);
      paintSec('files');
      return;
    }
    if ((t = e.target.closest('[data-ag-file]'))) { openFile(t.getAttribute('data-ag-file')); return; }
    if ((t = e.target.closest('[data-ag-termt]'))) { const id = t.getAttribute('data-ag-termt'); S.termOpen[id] = !S.termOpen[id]; paintSec('term'); return; }
    // 2차 / phase 2
    if ((t = e.target.closest('[data-ag-dl]'))) {   // 보조 키 클릭은 브라우저 그대로(새 탭) / modifier clicks stay native (new tab)
      if (e.button === 0 && !e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey) { e.preventDefault(); downloadOutput(t.getAttribute('data-ag-dl'), t.getAttribute('href')); }
      return;
    }
    if ((t = e.target.closest('[data-ag-cmd]'))) { const c = slashList().filter(function (x) { return x.name === t.getAttribute('data-ag-cmd'); })[0]; if (c) fillCmd(c); return; }
    if ((t = e.target.closest('[data-ag-restore]'))) { openRestoreDialog(t.getAttribute('data-ag-restore')); return; }
    if ((t = e.target.closest('[data-ag-hook]'))) { const s = Number(t.getAttribute('data-ag-hook')); S.hookOpen[s] = !S.hookOpen[s]; repaintSeqItem('ai365-ag-hook', s); return; }
    if ((t = e.target.closest('[data-ag-compact]'))) { const s = Number(t.getAttribute('data-ag-compact')); S.compOpen[s] = !S.compOpen[s]; repaintSeqItem('ai365-ag-compact', s); return; }
    if ((t = e.target.closest('[data-ag-task]'))) { openTaskCard(t.getAttribute('data-ag-task')); return; }
    if ((t = e.target.closest('[data-ag-change]'))) { openDiff(t.getAttribute('data-ag-change')); return; }
    if ((t = e.target.closest('[data-ag-output]'))) {   // 내 컴퓨터 폴더 산출물 경로 = "<이름>/<rel>" / a browser folder's output path is "<name>/<rel>"
      if (!t.disabled) { const op = t.getAttribute('data-ag-output'); openFile(isBrowser() ? fsOutRel(op) : op); }
      return;
    }
    if ((t = e.target.closest('[data-ag]'))) {
      const ag = t.getAttribute('data-ag');
      if (ag === 'send') send();
      else if (ag === 'stop') stop();
      else if (ag === 'vclose') closeViewer();
      else if (ag === 'newc') openNewDialog();
      else if (ag === 'fsopen') { if (!t.disabled) fsQuickOpen(); }   // 빈 화면의 [내 컴퓨터 폴더 열기] / the empty state's button
      else if (ag === 'fsgrant') { if (!t.disabled) fsGrant(); }      // 안내 줄 [허용] · [다시 시도] / the bar's [Allow] and [Retry]
      else if (ag === 'fsrelink') { if (!t.disabled) fsRelink(); }    // 안내 줄 [폴더 열기] / the bar's [Open folder]
      else if (ag === 'retry') load();
      else if (ag === 'plan-run') planRun(Number(t.getAttribute('data-seq')));
      else if (ag === 'plan-stay') planStay(Number(t.getAttribute('data-seq')));
      else if (ag === 'checkpoint') createCheckpoint();
      else if (ag === 'commit') openCommitDialog();
    }
  }
  // 슬래시 팝업을 눌러도 입력줄이 포커스를 잃지 않게 / keep the composer focused while the slash popup is clicked
  function onShellDown(e) { if (e.target.closest && e.target.closest('.ai365-ag-slash')) e.preventDefault(); }
  function onShellChange(e) {
    if (e.target.matches('[data-ag-perm]')) patch({ perm_mode: e.target.value }).catch(noop);
    else if (e.target.matches('[data-ag-model]')) patch({ model: e.target.value }).catch(noop);
    else if (e.target.matches('[data-ag-conn]')) toggleConn();
  }
  function onInputKey(e) {
    if (slashKey(e)) return;   // 슬래시 팝업이 먼저 / the slash popup first
    // Enter = 보내기, Shift+Enter = 줄바꿈, 한글 조합 중 Enter 는 무시 / Enter sends, Shift+Enter breaks the line, Enter while composing Hangul is ignored
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); send(); }
  }
  function onInputInput() {
    autosize();
    if (R.send) R.send.disabled = !S.cur || S.sessLoading || !!S.sessErr || S.sending || !R.input.value.trim();
    updateSlash();
  }

  document.addEventListener('ai365:agentic', function (e) { if (e && e.detail && e.detail.on) mount(); else unmount(); });
  document.addEventListener('keydown', function (e) {
    if (!S.on || e.key !== 'Escape') return;
    if (S.browse) { e.preventDefault(); closeBrowse(); return; }   // 위에 겹친 탐색기부터 / the explorer on top first
    if (S.dlg) { e.preventDefault(); closeDialog(); return; }
    if (S.slash) { closeSlash(); return; }
    if (S.menu) { setMenu(false); return; }
    if (S.viewer) closeViewer();
  });
  // 다시 보이면 그동안 받은 이벤트를 본 것으로 / once visible again, the events received meanwhile count as seen
  document.addEventListener('visibilitychange', function () { if (S.on && visible()) scheduleSeen(); });
  document.addEventListener('click', function (e) {
    if (!S.on) return;
    const t = e.target;
    if (S.menu && !(t.closest && t.closest('.ai365-ag-menu, [data-ag="title"]'))) setMenu(false);
    // 언어 토글: 사전 왕복 대신 다시 그린다(T 가 그 시점 언어를 고른다). 토글은 눌린 순간 안쪽 글("KO ˅")을 다시 그려 e.target 이
    // 문서에서 떨어질 수 있으므로 전달 시점의 경로(composedPath)로 찾는다(2026-10-20 DEV 정렬의 새 토글 모양)
    // Language toggle: re-render instead of a dictionary round trip. The toggle repaints its inner label ("KO ˅") during the click,
    // which can detach e.target, so it is looked up in the dispatch-time path (composedPath; the 2026-10-20 DEV-aligned toggle)
    if (fromLangToggle(e)) setTimeout(function () { if (S.on) renderAll(); }, 80);
    // 뷰애즈로 사용자가 바뀌면(세션은 소유자 것만 보인다) 목록부터 다시 / a view-as user switch reloads from the list (sessions are per owner)
    setTimeout(function () {
      if (!S.on || S.actor === undefined || S.actor === acting()) return;
      S.hist = []; S.hpos = -1; S.openTok += 1;
      closeStream(); stopTaskPoll();
      clearTimeout(S.seenTimer); S.seenTimer = null; clearTimeout(S.tasksKick); S.tasksKick = null;
      S.cur = null; S.git = null; S.tree = null; S.viewer = null; S.tasks = []; S.sessions = [];
      S.changes = null; S.outputs = null; S.conns = null; S.slash = null; S.cmdCache = null;
      resetTranscript();
      load();
    }, 150);
  });

  window.AI365_agentic = {
    mount: mount,
    unmount: unmount,
    isOn: function () { return S.on; },
    open: function (id) { openSession(id); },
    reload: function () { load(); },
    state: function () {   // 점검용 요약(테스트 · 콘솔) / a summary for checks (tests and the console)
      return { on: S.on, session: S.cur ? S.cur.id : '', status: S.cur ? S.cur.status : '', lastSeq: S.lastSeq, events: S.events.length,
        streaming: !!S.es, reconnecting: !!S.reTimer, taskPolling: !!S.taskTimer, listPolling: !!S.listTimer, queue: S.queue.slice(), env: S.env,
        // 2차: 끼워 넣기 대기 수 · 대기 중 승인 수 · 열린(접히지 않은) 환경 패널 섹션 / phase 2: pending steers, pending approvals, open (not collapsed) panel sections
        steer: S.steer.length,
        pendingApprovals: Object.keys(S.approvals).filter(function (k) { return (S.approvals[k].decision || 'pending') === 'pending'; }).length,
        sections: R.env ? shownSections().filter(function (x) { return !S.shut[x.key]; }).map(function (x) { return x.key; }) : [],
        // 내 컴퓨터 폴더: 지원 · 안내 줄 · 핸들 · 그 실제 폴더 이름 · 권한 · 기다리는 요청 수 · 처리 중 요청 수 · 아직 못 보낸 답 수 · 원격 · 서버가 껐나
        // Browser folders: support, bar, handle, its real folder name, permission, waiting and running requests, undelivered answers, remote, turned off
        fs: (function () {
          const f = S.cur ? S.fs[S.cur.id] : null, ids = Object.keys(S.fsReq);
          return { ok: S.fsOk, bar: S.fsBar, handle: !!(f && f.handle), name: (f && f.name) || '', perm: (f && f.perm) || '', waiting: fsWaiting(),
            running: ids.filter(function (k) { return S.fsReq[k].running; }).length, unsent: Object.keys(S.fsOut).length, remote: S.remote, off: S.bfOff };
        })() };
    },
  };
  // 채팅 컴포저 + 메뉴의 [내 컴퓨터 폴더 열기](adapter G 절)가 부른다: 제스처 안에서 선택 창 → Agentic 화면 → 세션 생성 · 열기(계약 F2)
  // Called by [Open a folder on my computer] in the chat composer's + menu (adapter, section G): picker in the gesture → the Agentic
  // view → create and open the session (contract F2). Resolves with the session, or null when cancelled or refused.
  window.AI365_agenticOpenFolder = function () { return fsOpenFromComposer(); };

  // 이미 Agentic 화면이 열려 있으면 바로 마운트(늦게 실린 경우) / mount at once when the Agentic view is already open (late load)
  const work = document.getElementById('viewWork');
  if (work && work.classList.contains('active')) mount();
})();
