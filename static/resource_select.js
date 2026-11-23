/* 리소스 선택 대화 상자(2026-10-28, Dev 원본 정렬 명세 1.1 · 작업자 R). 입력 카드의 "리소스 센터" 칩([data-agentpill]: 채팅 #agentPill ·
   홈 #homeAgentPill · 컬렉션 #cdAgentPill · 예약 #ai365SdAgent · 예약 창 #cdSchedAgentPill)을 누르면 작은 분야 메뉴(#agentMenu)를 거치지 않고
   곧바로 Dev 의 "리소스 선택" 대화 상자가 열린다(Unified_Dev_Frontend: chat/components/ChatResource.tsx · input/ChatResourceButton.tsx ·
   shared/layout/PopUpLayout.tsx · templates/ResourceContent.tsx · ui/Accordion.tsx · ui/ResourceFolderTree.tsx ·
   resource/DataAnalysisResource.tsx · resource/GroupwareResource.tsx).
   - 틀: 폭 960 · 모서리 16 · 접는 구획 5개(지식 관리 Public · 지식 관리 Local · 데이터 분석 · 그룹웨어 · 업무 자동화, 기본 접힘) · [취소][선택 완료].
   - 상태: 목업 컴포저의 공유 상태(window.AI365_SMF_HOOKS)를 그대로 쓴다. 대화 상자 안에서는 임시 선택만 바꾸고 [선택 완료] 때만 반영한다
     ([취소] · X · 바깥 · Esc 는 그대로 둔다). 라우팅(AI365_COMPOSER_AGENTS) · scope_files(resolveScope) · 칩 라벨(computeLabel) 계약은 그대로다.
     트리 체크는 adapter 3분할 패널과 같은 어휘(켜기 = 자신 + 하위 전부, 끄기 = 자신 + 하위 + 조상)이고, BI 는 지금 정책대로 여러 개를 고를 수 있다.
   - Local 구획 = 관리 센터 › 로컬 설정에 등록한 로컬 지식 에이전트(선택 단위 = 에이전트, 펼치면 그 에이전트의 폴더 트리를 보여 준다).
     하나라도 고르면 나머지 구획은 잠기고(opacity .4 · grayscale · inert) 그 선택은 지워진다. 반영 = 분야 knowledge + 이 모듈의 로컬 선택 →
     전송 때 scope_files.local_agents 로 나간다(ai365SelectionSnapshot 감싸기, 서버는 app/agents/knowledge.py 의 로컬 전용 분기).
     예약 화면에서는 예약이 local_agents 를 저장하지 않으므로 Local 구획을 잠근다.
   - 칩 모양(글 700 · 왼쪽 리소스 센터 아이콘 21 · 셰브런 숨김 · 활성 #F2F6FF/#CCDAFF/#4450CE)과 홈 코치 툴팁도 이 모듈이 그린다.
   Resource picker (2026-10-28, Dev-original alignment spec 1.1, worker R). Clicking a "Resource Center" chip ([data-agentpill]: chat
   #agentPill, home #homeAgentPill, collection #cdAgentPill, schedules #ai365SdAgent, schedule dialog #cdSchedAgentPill) opens the Dev
   "Select Resources" dialog at once, without the small domain menu (#agentMenu).
   - Frame: 960 wide, radius 16, five collapsible sections (Knowledge Public, Knowledge Local, Data Analysis, Groupware, Work
     Automation, collapsed by default), [Cancel][Done].
   - State: the mockup composer's shared state (window.AI365_SMF_HOOKS) as is. The dialog edits a temporary selection that is applied
     on [Done] only ([Cancel], X, outside clicks and Esc leave everything as it was). The routing, scope_files and chip-label contracts
     are unchanged. Tree checks use the vocabulary of the adapter's three-pane panel (on = self + descendants, off = self +
     descendants + ancestors); BI stays multi-select as the current policy says.
   - The Local section lists the local knowledge agents registered in Admin Center › Local settings (one agent = one choice; expanding
     shows its folder tree). Choosing any locks the other sections (opacity .4, grayscale, inert) and clears their choices. Applying =
     the knowledge domain + this module's local choice, sent as scope_files.local_agents (the ai365SelectionSnapshot wrapper; the
     server side is the local-only branch of app/agents/knowledge.py). Schedules do not store local_agents, so the Local section is
     locked on the schedule screens.
   - This module also draws the chip (700 text, the Resource Center icon at 21, no chevron, active #F2F6FF/#CCDAFF/#4450CE) and the
     home coach tooltip. */
(function () {
  'use strict';
  if (window.AI365_RS) return;   // 한 번만 / once
  var H = window.AI365_SMF_HOOKS;
  if (!H || typeof H.sections !== 'function' || typeof H.setAgents !== 'function' || typeof H.setFiles !== 'function') return;

  /* ── 상수 · 문구 / constants and strings ── */
  var ORDER = ['knowledge', 'data', 'groupware', 'work'];
  var SECS = ['kpub', 'klocal', 'data', 'groupware', 'work'];
  var LOCAL_KEY = 'local:';   // 공유 상태 files() 에 싣는 가짜 키(스태시 · 복원 왕복용) / pseudo key in files() so stash and restore round-trip it
  var COACH_KEY = 'ai365_rs_coach_done';
  var FONT = '"Pretendard",-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR","Segoe UI",sans-serif';
  var FOCUS = '0 0 0 2px rgba(68,80,206,.4)';   // 공용 화면 포커스(계약 결정 4) / the shared-screen focus ring (contract decision 4)
  var EN = {
    '리소스 선택': 'Select Resources',
    'AI가 참고할 폴더·파일을 선택하세요': 'Select the folders/files for AI to reference',
    '취소': 'Cancel', '선택 완료': 'Done', '닫기': 'Close',
    '지식 관리': 'Knowledge Management', '데이터 분석': 'Data Analysis', '그룹웨어': 'Groupware', '업무 자동화': 'Work Automation',
    '전체 선택': 'Select all', '펼치기/접기': 'Expand or collapse',
    '선택할 수 있는 리소스가 없습니다': 'No resources available',
    '등록된 로컬 지식 에이전트가 없습니다': 'No local knowledge agents registered',
    '불러오는 중…': 'Loading…',
    '목록을 불러오지 못했습니다': 'Could not load the list',
    '폴더를 불러오지 못했습니다': 'Could not load the folders',
    '폴더가 없습니다': 'No folders',
    '예약 작업에서는 로컬 지식 에이전트를 쓸 수 없습니다': 'Local knowledge agents are not available for schedules',
    '리소스를 세부적으로 선택해보세요': 'Select resources in detail'
  };
  var SEC_NAME = { kpub: '지식 관리', klocal: '지식 관리', data: '데이터 분석', groupware: '그룹웨어', work: '업무 자동화' };
  // 칩 라벨(ChatResourceButton.generateTitle · Dev 사전 menu.2 · menu.2.x · chat_nav.automation). 규칙은 목업 computeLabel 그대로(2개 + " +n")
  // The chip label (Dev menu.2, menu.2.x, chat_nav.automation); the rule is the mockup's computeLabel (two names + " +n")
  var CHIP = { ko: { none: '리소스 센터', knowledge: '지식 관리', data: '데이터 분석', groupware: '그룹웨어', work: '업무 자동화' },
    en: { none: 'Resource Center', knowledge: 'Knowledge Management', data: 'Data Analysis', groupware: 'Groupware', work: 'Work Automation' } };

  function isEn() { return typeof ai365CurrentLang === 'function' && ai365CurrentLang() === 'en'; }
  function T(ko) { return isEn() ? (EN[ko] || ko) : ko; }
  function TD(s) { return (typeof ai365T === 'function') ? ai365T(s) : s; }   // 데이터 이름은 adapter 사전으로(정확히 같을 때만) / data names via the adapter dictionary (exact match only)
  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function cssq(s) { return (window.CSS && CSS.escape) ? CSS.escape(String(s)) : String(s).replace(/["\\]/g, '\\$&'); }
  function acting() {
    if (typeof ai365ActingId === 'function') return ai365ActingId();
    return window.AI365_ACTING_USER ? String(window.AI365_ACTING_USER.no) : '';
  }
  function uniq(arr) {
    var out = [];
    (arr || []).forEach(function (x) { if (typeof x === 'string' && x && out.indexOf(x) < 0) out.push(x); });
    return out;
  }

  /* ── 아이콘(Dev 원본 SVG) / icons (Dev original SVGs) ── */
  var RC_OFF = 'M13.0883 6.41228C13.016 6.31886 12.9377 6.2298 12.8539 6.14569C12.5417 5.83255 12.1606 5.59666 11.741 5.45683L10.3632 5.00939C10.257 4.97196 10.165 4.90253 10.1 4.81068C10.0349 4.71883 10 4.60908 10 4.49656C10 4.38404 10.0349 4.27429 10.1 4.18244C10.165 4.09058 10.257 4.02116 10.3632 3.98372L11.741 3.53628C12.1547 3.39352 12.5299 3.15705 12.837 2.84537C13.1357 2.54224 13.3623 2.17595 13.5 1.77372L13.5114 1.73963L13.9592 0.362894C13.9967 0.256782 14.0662 0.164895 14.1581 0.0998993C14.25 0.0349035 14.3598 0 14.4724 0C14.5851 0 14.6949 0.0349035 14.7868 0.0998993C14.8787 0.164895 14.9482 0.256782 14.9857 0.362894L15.4335 1.73963C15.5727 2.15819 15.8077 2.53853 16.1198 2.85041C16.432 3.1623 16.8126 3.39715 17.2315 3.53628L18.6093 3.98372L18.6368 3.99061C18.743 4.02804 18.835 4.09747 18.9 4.18932C18.9651 4.28117 19 4.39092 19 4.50344C19 4.61596 18.9651 4.72571 18.9 4.81756C18.835 4.90942 18.743 4.97884 18.6368 5.01628L17.259 5.46372C16.8402 5.60285 16.4595 5.8377 16.1474 6.14959C15.8353 6.46147 15.6003 6.84181 15.461 7.26037L15.0132 8.63711C15.0092 8.64855 15.0048 8.65983 15 8.67093C14.9605 8.76273 14.8964 8.84212 14.8144 8.9001C14.7224 8.9651 14.6126 9 14.5 9C14.3874 9 14.2776 8.9651 14.1856 8.9001C14.0937 8.8351 14.0242 8.74322 13.9868 8.63711L13.539 7.26037C13.4378 6.95331 13.2851 6.66664 13.0883 6.41228ZM20.7829 10.2132L20.0175 9.9646C19.7848 9.8873 19.5733 9.75683 19.3999 9.58356C19.2265 9.41029 19.0959 9.199 19.0186 8.96646L18.7698 8.20161C18.749 8.14266 18.7104 8.09161 18.6593 8.0555C18.6083 8.01939 18.5473 8 18.4847 8C18.4221 8 18.3611 8.01939 18.31 8.0555C18.259 8.09161 18.2204 8.14266 18.1996 8.20161L17.9508 8.96646C17.875 9.19736 17.7467 9.40761 17.5761 9.58076C17.4055 9.75392 17.1971 9.88529 16.9672 9.9646L16.2018 10.2132C16.1428 10.234 16.0917 10.2725 16.0555 10.3236C16.0194 10.3746 16 10.4356 16 10.4981C16 10.5606 16.0194 10.6216 16.0555 10.6726C16.0917 10.7236 16.1428 10.7622 16.2018 10.783L16.9672 11.0316C17.2003 11.1093 17.412 11.2403 17.5855 11.4143C17.7589 11.5882 17.8893 11.8003 17.9661 12.0335L18.2149 12.7984C18.2357 12.8573 18.2743 12.9084 18.3254 12.9445C18.3764 12.9806 18.4374 13 18.5 13C18.5626 13 18.6236 12.9806 18.6746 12.9445C18.7257 12.9084 18.7643 12.8573 18.7851 12.7984L19.0339 12.0335C19.1113 11.801 19.2418 11.5897 19.4152 11.4164C19.5886 11.2432 19.8001 11.1127 20.0328 11.0354L20.7982 10.7868C20.8572 10.766 20.9083 10.7275 20.9445 10.6764C20.9806 10.6254 21 10.5644 21 10.5019C21 10.4394 20.9806 10.3784 20.9445 10.3274C20.9083 10.2764 20.8572 10.2378 20.7982 10.217L20.7829 10.2132ZM7.25 3.00195C8.2165 3.00195 9 3.78545 9 4.75195V9.25195C9 10.2185 8.2165 11.002 7.25 11.002H1.75C0.783502 11.002 0 10.2185 0 9.25195V4.75195C0 3.78545 0.783502 3.00195 1.75 3.00195H7.25ZM7.5 9.25195V4.75195C7.5 4.61388 7.38807 4.50195 7.25 4.50195H1.75C1.61193 4.50195 1.5 4.61388 1.5 4.75195V9.25195C1.5 9.39002 1.61193 9.50195 1.75 9.50195H7.25C7.38807 9.50195 7.5 9.39002 7.5 9.25195ZM4.23759 12.9838C5.20408 12.9838 5.98759 13.7673 5.98759 14.7338V19.2482C5.98759 20.2147 5.20408 20.9982 4.23759 20.9982H1.75C0.783502 20.9982 0 20.2147 0 19.2482V14.7338C0 13.7673 0.783502 12.9838 1.75 12.9838H4.23759ZM4.48759 19.2482V14.7338C4.48759 14.5957 4.37566 14.4838 4.23759 14.4838H1.75C1.61193 14.4838 1.5 14.5957 1.5 14.7338V19.2482C1.5 19.3862 1.61193 19.4982 1.75 19.4982H4.23759C4.37566 19.4982 4.48759 19.3862 4.48759 19.2482ZM16.2517 12.9982C17.2182 12.9982 18.0017 13.7817 18.0017 14.7482V19.2482C18.0017 20.2147 17.2182 20.9982 16.2517 20.9982H9.75169C8.78519 20.9982 8.00169 20.2147 8.00169 19.2482V14.7482L8.00749 14.6046C8.08049 13.7053 8.83351 12.9982 9.75169 12.9982H16.2517ZM16.5017 19.2482V14.7482C16.5017 14.6101 16.3898 14.4982 16.2517 14.4982H9.75169C9.63334 14.4982 9.5342 14.5804 9.50829 14.6908L9.50169 14.7482V19.2482C9.50169 19.3862 9.61362 19.4982 9.75169 19.4982H16.2517C16.3898 19.4982 16.5017 19.3862 16.5017 19.2482Z';
  var RC_ON = 'M13.0873 6.41228C13.015 6.31886 12.9367 6.2298 12.8529 6.14569C12.5407 5.83255 12.1596 5.59666 11.74 5.45683L10.3622 5.00939C10.256 4.97196 10.164 4.90253 10.099 4.81068C10.034 4.71883 9.99902 4.60908 9.99902 4.49656C9.99902 4.38404 10.034 4.27429 10.099 4.18244C10.164 4.09058 10.256 4.02116 10.3622 3.98372L11.74 3.53628C12.1538 3.39352 12.5289 3.15705 12.836 2.84537C13.1347 2.54224 13.3613 2.17595 13.499 1.77372L13.5105 1.73963L13.9582 0.362894C13.9957 0.256782 14.0652 0.164895 14.1571 0.0998993C14.249 0.0349035 14.3589 0 14.4715 0C14.5841 0 14.6939 0.0349035 14.7858 0.0998993C14.8778 0.164895 14.9472 0.256782 14.9847 0.362894L15.4325 1.73963C15.5717 2.15819 15.8067 2.53853 16.1189 2.85041C16.431 3.1623 16.8116 3.39715 17.2305 3.53628L18.6083 3.98372L18.6359 3.99061C18.742 4.02804 18.834 4.09747 18.899 4.18932C18.9641 4.28117 18.999 4.39092 18.999 4.50344C18.999 4.61596 18.9641 4.72571 18.899 4.81756C18.834 4.90942 18.742 4.97884 18.6359 5.01628L17.2581 5.46372C16.8392 5.60285 16.4586 5.8377 16.1464 6.14959C15.8343 6.46147 15.5993 6.84181 15.46 7.26037L15.0123 8.63711C15.0082 8.64855 15.0038 8.65983 14.999 8.67093C14.9595 8.76273 14.8954 8.84212 14.8134 8.9001C14.7215 8.9651 14.6116 9 14.499 9C14.3864 9 14.2766 8.9651 14.1847 8.9001C14.0927 8.8351 14.0233 8.74322 13.9858 8.63711L13.538 7.26037C13.4368 6.95331 13.2842 6.66664 13.0873 6.41228ZM20.782 10.2132L20.0165 9.9646C19.7838 9.8873 19.5723 9.75683 19.3989 9.58356C19.2255 9.41029 19.095 9.199 19.0176 8.96646L18.7688 8.20161C18.748 8.14266 18.7094 8.09161 18.6584 8.0555C18.6073 8.01939 18.5463 8 18.4837 8C18.4212 8 18.3601 8.01939 18.3091 8.0555C18.258 8.09161 18.2194 8.14266 18.1986 8.20161L17.9498 8.96646C17.874 9.19736 17.7458 9.40761 17.5751 9.58076C17.4045 9.75392 17.1961 9.88529 16.9662 9.9646L16.2008 10.2132C16.1418 10.234 16.0907 10.2725 16.0546 10.3236C16.0184 10.3746 15.999 10.4356 15.999 10.4981C15.999 10.5606 16.0184 10.6216 16.0546 10.6726C16.0907 10.7236 16.1418 10.7622 16.2008 10.783L16.9662 11.0316C17.1993 11.1093 17.4111 11.2403 17.5845 11.4143C17.7579 11.5882 17.8883 11.8003 17.9651 12.0335L18.2139 12.7984C18.2347 12.8573 18.2733 12.9084 18.3244 12.9445C18.3754 12.9806 18.4365 13 18.499 13C18.5616 13 18.6226 12.9806 18.6737 12.9445C18.7247 12.9084 18.7633 12.8573 18.7841 12.7984L19.0329 12.0335C19.1103 11.801 19.2408 11.5897 19.4142 11.4164C19.5877 11.2432 19.7991 11.1127 20.0318 11.0354L20.7973 10.7868C20.8563 10.766 20.9073 10.7275 20.9435 10.6764C20.9796 10.6254 20.999 10.5644 20.999 10.5019C20.999 10.4394 20.9796 10.3784 20.9435 10.3274C20.9073 10.2764 20.8563 10.2378 20.7973 10.217L20.782 10.2132ZM7.25 3.00275C8.2165 3.00275 9 3.78625 9 4.75275V9.25275C9 10.2192 8.2165 11.0027 7.25 11.0027H1.75C0.783502 11.0027 0 10.2192 0 9.25275V4.75275C0 3.78625 0.783502 3.00275 1.75 3.00275H7.25ZM4.23759 12.9845C5.20408 12.9845 5.98759 13.7681 5.98759 14.7345V19.249C5.98759 20.2155 5.20408 20.999 4.23759 20.999H1.75C0.783502 20.999 0 20.2155 0 19.249V14.7345C0 13.7681 0.783502 12.9845 1.75 12.9845H4.23759ZM16.2517 12.999C17.2182 12.999 18.0017 13.7825 18.0017 14.749V19.249C18.0017 20.2155 17.2182 20.999 16.2517 20.999H9.75169C8.78519 20.999 8.00169 20.2155 8.00169 19.249V14.749L8.00749 14.6054C8.08049 13.7061 8.83351 12.999 9.75169 12.999H16.2517Z';
  var KN_OFF = 'M6.54159 6.60759L7.64196 4.37799C7.89069 3.874 8.60937 3.874 8.8581 4.37799L9.95847 6.60759L12.419 6.96512C12.9752 7.04594 13.1972 7.72944 12.7948 8.12174L11.0143 9.85724L11.4347 12.3078C11.5297 12.8617 10.9482 13.2842 10.4508 13.0226L8.25003 11.8656L6.04929 13.0226C5.55182 13.2842 4.9704 12.8617 5.06541 12.3078L5.48571 9.85724L3.70527 8.12174C3.30281 7.72944 3.5249 7.04594 4.08108 6.96512L6.54159 6.60759ZM7.59996 7.52747C7.50119 7.72761 7.31026 7.86633 7.0894 7.89842L5.6358 8.10964L6.68763 9.13493C6.84745 9.29071 6.92038 9.51516 6.88265 9.73513L6.63434 11.1829L7.93448 10.4993C8.13203 10.3955 8.36803 10.3955 8.56558 10.4993L9.86572 11.1829L9.61741 9.73513C9.57968 9.51516 9.65261 9.29071 9.81243 9.13493L10.8643 8.10964L9.41066 7.89842C9.1898 7.86633 8.99887 7.72761 8.9001 7.52747L8.25003 6.21029L7.59996 7.52747ZM2.5 0C1.11929 0 0 1.11929 0 2.5V17.5C0 18.8807 1.11929 20 2.5 20H15.75C16.1642 20 16.5 19.6642 16.5 19.25C16.5 18.8358 16.1642 18.5 15.75 18.5H2.5C1.94772 18.5 1.5 18.0523 1.5 17.5H15.75C16.1642 17.5 16.5 17.1642 16.5 16.75V2.5C16.5 1.11929 15.3807 0 14 0H2.5ZM15 16H1.5V2.5C1.5 1.94772 1.94772 1.5 2.5 1.5H14C14.5523 1.5 15 1.94772 15 2.5V16Z';
  var KN_ON = 'M2.5 0C1.11929 0 0 1.11929 0 2.5V17.5C0 18.8807 1.11929 20 2.5 20H15.75C16.1642 20 16.5 19.6642 16.5 19.25C16.5 18.8358 16.1642 18.5 15.75 18.5H2.5C1.94772 18.5 1.5 18.0523 1.5 17.5H15.75C16.1642 17.5 16.5 17.1642 16.5 16.75V2.5C16.5 1.11929 15.3807 0 14 0H2.5ZM6.54159 6.60759L7.64196 4.37799C7.89069 3.874 8.60937 3.874 8.8581 4.37799L9.95847 6.60759L12.419 6.96512C12.9752 7.04594 13.1972 7.72944 12.7948 8.12174L11.0143 9.85724L11.4347 12.3078C11.5297 12.8617 10.9482 13.2842 10.4508 13.0226L8.25003 11.8656L6.04929 13.0226C5.55182 13.2842 4.9704 12.8617 5.06541 12.3078L5.48571 9.85724L3.70527 8.12174C3.30281 7.72944 3.5249 7.04594 4.08108 6.96512L6.54159 6.60759Z';
  var CH_OFF = 'M12.7276 2.2155C12.8731 2.07426 13.0696 1.99796 13.2723 2.00399C18.0267 2.1455 21.8545 5.97326 21.996 10.7276C22.002 10.9303 21.9257 11.1268 21.7844 11.2723C21.6432 11.4178 21.4491 11.4999 21.2463 11.4999H13.25C12.8358 11.4999 12.5 11.1642 12.5 10.7499V2.75366C12.5 2.55088 12.5821 2.35674 12.7276 2.2155ZM14 3.566V9.99995H20.434C19.9888 6.65788 17.3421 4.01119 14 3.566ZM11 4.76465C11 4.55403 10.9114 4.35312 10.756 4.21103C10.6005 4.06894 10.3925 3.99877 10.1827 4.01768C5.59476 4.43112 2 8.28584 2 12.981C2 17.9516 6.02944 21.981 11 21.981C15.6881 21.981 19.5383 18.3971 19.9615 13.819C19.9809 13.609 19.9109 13.4005 19.7688 13.2447C19.6267 13.0888 19.4256 13 19.2146 13H13.25C12.0074 13 11 11.9926 11 10.75V4.76465ZM3.5 12.981C3.5 9.35271 6.07693 6.32555 9.5 5.63092V10.75C9.5 12.8211 11.1789 14.5 13.25 14.5H18.3462C17.6443 17.9136 14.6216 20.481 11 20.481C6.85786 20.481 3.5 17.1232 3.5 12.981Z';
  var CH_ON = 'M13.2723 2.00424C13.0696 1.99821 12.8731 2.07451 12.7276 2.21575C12.5821 2.35699 12.5 2.55113 12.5 2.75391V10.7502C12.5 11.1644 12.8336 11.5002 13.25 11.5002H21.2463C21.4491 11.5002 21.6432 11.4181 21.7844 11.2726C21.9257 11.1271 22.002 10.9306 21.996 10.7279C21.8545 5.9735 18.0267 2.14214 13.2723 2.00424ZM10.756 4.21128C10.9114 4.35337 11 4.55428 11 4.7649V10.7502C11 11.9929 12.0074 13.0002 13.25 13.0002H19.2146C19.4256 13.0002 19.6267 13.0891 19.7688 13.2449C19.9109 13.4008 19.9809 13.6093 19.9615 13.8193C19.5383 18.3973 15.6681 21.9813 11 21.9813C6.02944 21.9813 2 17.9518 2 12.9813C2 8.28609 5.59476 4.43136 10.1127 4.01792C10.3925 3.99902 10.6005 4.06919 10.756 4.21128Z';
  var GW_OFF = 'M5.75 10C6.99264 10 8 11.0074 8 12.25V15.75C8 16.9926 6.99264 18 5.75 18H2.25C1.00736 18 0 16.9926 0 15.75V12.25C0 11.0074 1.00736 10 2.25 10H5.75ZM15.75 10C16.9926 10 18 11.0074 18 12.25V15.75C18 16.9926 16.9926 18 15.75 18H12.25C11.0074 18 10 16.9926 10 15.75V12.25C10 11.0074 11.0074 10 12.25 10H15.75ZM5.75 11.5H2.25C1.83579 11.5 1.5 11.8358 1.5 12.25V15.75C1.5 16.1642 1.83579 16.5 2.25 16.5H5.75C6.16421 16.5 6.5 16.1642 6.5 15.75V12.25C6.5 11.8358 6.16421 11.5 5.75 11.5ZM15.75 11.5H12.25C11.8358 11.5 11.5 11.8358 11.5 12.25V15.75C11.5 16.1642 11.8358 16.5 12.25 16.5H15.75C16.1642 16.5 16.5 16.1642 16.5 15.75V12.25C16.5 11.8358 16.1642 11.5 15.75 11.5ZM5.75 0C6.99264 0 8 1.00736 8 2.25V5.75C8 6.99264 6.99264 8 5.75 8H2.25C1.00736 8 0 6.99264 0 5.75V2.25C0 1.00736 1.00736 0 2.25 0H5.75ZM15.75 0C16.9926 0 18 1.00736 18 2.25V5.75C18 6.99264 16.9926 8 15.75 8H12.25C11.0074 8 10 6.99264 10 5.75V2.25C10 1.00736 11.0074 0 12.25 0H15.75ZM5.75 1.5H2.25C1.83579 1.5 1.5 1.83579 1.5 2.25V5.75C1.5 6.16421 1.83579 6.5 2.25 6.5H5.75C6.16421 6.5 6.5 6.16421 6.5 5.75V2.25C6.5 1.83579 6.16421 1.5 5.75 1.5ZM15.75 1.5H12.25C11.8358 1.5 11.5 1.83579 11.5 2.25V5.75C11.5 6.16421 11.8358 6.5 12.25 6.5H15.75C16.1642 6.5 16.5 6.16421 16.5 5.75V2.25C16.5 1.83579 16.1642 1.5 15.75 1.5Z';
  var BOT_OFF = 'M17.7534 13.9999C18.9961 13.9999 20.0034 15.0073 20.0034 16.2499V17.155C20.0034 18.2487 19.526 19.2879 18.6961 20.0003C17.1307 21.3442 14.8904 22.0011 12.0004 22.0011C9.11087 22.0011 6.87205 21.3445 5.30918 20.0008C4.48056 19.2884 4.00391 18.25 4.00391 17.1572V16.2499C4.00391 15.0073 5.01127 13.9999 6.25391 13.9999H17.7534ZM17.7534 15.4999H6.25391C5.83969 15.4999 5.50391 15.8357 5.50391 16.2499V17.1572C5.50391 17.8129 5.7899 18.4359 6.28707 18.8634C7.54516 19.945 9.44117 20.5011 12.0004 20.5011C14.5603 20.5011 16.4582 19.9447 17.7191 18.8622C18.2169 18.4347 18.5034 17.8112 18.5034 17.155V16.2499C18.5034 15.8357 18.1676 15.4999 17.7534 15.4999ZM11.8989 2.00733L12.0007 2.00049C12.3804 2.00049 12.6942 2.28264 12.7438 2.64872L12.7507 2.75049L12.7499 3.49949L16.2504 3.49999C17.493 3.49999 18.5004 4.50735 18.5004 5.74999V10.2546C18.5004 11.4972 17.493 12.5046 16.2504 12.5046H7.75036C6.50772 12.5046 5.50036 11.4972 5.50036 10.2546V5.74999C5.50036 4.50735 6.50772 3.49999 7.75036 3.49999L11.2499 3.49949L11.2507 2.75049C11.2507 2.37079 11.5328 2.057 11.8989 2.00733L12.0007 2.00049L11.8989 2.00733ZM16.2504 4.99999H7.75036C7.33615 4.99999 7.00036 5.33578 7.00036 5.74999V10.2546C7.00036 10.6688 7.33615 11.0046 7.75036 11.0046H16.2504C16.6646 11.0046 17.0004 10.6688 17.0004 10.2546V5.74999C17.0004 5.33578 16.6646 4.99999 16.2504 4.99999ZM9.74965 6.49999C10.4396 6.49999 10.9989 7.05932 10.9989 7.74928C10.9989 8.43925 10.4396 8.99857 9.74965 8.99857C9.05969 8.99857 8.50036 8.43925 8.50036 7.74928C8.50036 7.05932 9.05969 6.49999 9.74965 6.49999ZM14.2424 6.49999C14.9324 6.49999 15.4917 7.05932 15.4917 7.74928C15.4917 8.43925 14.9324 8.99857 14.2424 8.99857C13.5524 8.99857 12.9931 8.43925 12.9931 7.74928C12.9931 7.05932 13.5524 6.49999 14.2424 6.49999Z';
  var BOT_ON_1 = 'M11.25 2.75C11.25 2.336 11.586 2 12 2C12.414 2 12.75 2.336 12.75 2.75V3.5H16.25C17.493 3.5 18.5 4.507 18.5 5.75V10.25C18.5 11.493 17.493 12.5 16.25 12.5H7.75C6.507 12.5 5.5 11.493 5.5 10.25V5.75C5.5 4.507 6.507 3.5 7.75 3.5H11.25V2.75ZM9.75 6.5C9.06 6.5 8.5 7.06 8.5 7.75C8.5 8.44 9.06 9 9.75 9C10.44 9 11 8.44 11 7.75C11 7.06 10.44 6.5 9.75 6.5ZM14.24 6.5C13.55 6.5 12.99 7.06 12.99 7.75C12.99 8.44 13.55 9 14.24 9C14.93 9 15.49 8.44 15.49 7.75C15.49 7.06 14.93 6.5 14.24 6.5Z';
  var BOT_ON_2 = 'M17.7534 14C18.9961 14 20.0034 15.0074 20.0034 16.25V17.155C20.0034 18.2487 19.526 19.2879 18.6961 20.0003C17.1307 21.3442 14.8904 22.0011 12.0004 22.0011C9.11087 22.0011 6.87205 21.3445 5.30918 20.0008C4.48056 19.2884 4.00391 18.25 4.00391 17.1572V16.25C4.00391 15.0074 5.01127 14 6.25391 14H17.7534Z';
  function icKnow(on) {
    return '<svg class="ai365-rs-ic" width="17" height="20" viewBox="0 0 17 20" fill="none" aria-hidden="true"><path d="' + (on ? KN_ON : KN_OFF) + '" fill="' + (on ? '#4450CE' : '#3E424B') + '"/></svg>';
  }
  function icChart(on) {
    return '<svg class="ai365-rs-ic" width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="' + (on ? CH_ON : CH_OFF) + '" fill="' + (on ? '#4450CE' : '#3E424B') + '"/></svg>';
  }
  function icGw(on) {
    var body = on ? '<g fill="#4450CE"><rect x="0" y="0" width="8" height="8" rx="2.25"/><rect x="10" y="0" width="8" height="8" rx="2.25"/><rect x="0" y="10" width="8" height="8" rx="2.25"/><rect x="10" y="10" width="8" height="8" rx="2.25"/></g>'
      : '<path d="' + GW_OFF + '" fill="#3E424B"/>';
    return '<span class="ai365-rs-gwbox' + (on ? ' on' : '') + '"><svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">' + body + '</svg></span>';
  }
  function icBot(on) {
    var body = on ? '<g fill="#4450CE"><path fill-rule="evenodd" clip-rule="evenodd" d="' + BOT_ON_1 + '"/><path d="' + BOT_ON_2 + '"/></g>'
      : '<path d="' + BOT_OFF + '" fill="#3E424B"/>';
    return '<svg class="ai365-rs-ic" width="16" height="20" viewBox="4 2 16 20" fill="none" aria-hidden="true">' + body + '</svg>';
  }
  // lucide ChevronDown · ChevronRight · X(선 굵기는 Dev 와 같게) / lucide chevrons and X (stroke widths as in Dev)
  function svgChev(dir, size, sw) {
    var d = dir === 'down' ? 'm6 9 6 6 6-6' : 'm9 18 6-6-6-6';
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="' + sw + '" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + d + '"/></svg>';
  }
  var SVG_X = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
  function chipIcon(on) {
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="21" height="21" viewBox="0 0 21 21" fill="none"><path d="' + (on ? RC_ON : RC_OFF) + '" fill="' + (on ? '#4450CE' : '#21242C') + '"/></svg>';
    return 'url("data:image/svg+xml,' + encodeURIComponent(svg) + '")';
  }

  /* ── 스타일 / styles ── */
  (function css() {
    if (document.getElementById('ai365RsCss')) return;
    // 특이도를 (0,4,2) 이상으로 둔다: adapter 가 body 끝에 붙이는 .pill-btn(0,1,0) · .pill-btn:hover:not(.agp-active)(0,3,0) · 목업
    // .pill-btn.agp-active(0,2,0) 와 화면별 클래스 3개 규칙보다 늘 이기게(이 스타일은 head 에 있어 순서로는 지기 때문)
    // Specificity (0,4,2) and up: always beats the adapter's body-end .pill-btn (0,1,0) and .pill-btn:hover:not(.agp-active) (0,3,0),
    // the mockup's .pill-btn.agp-active (0,2,0) and three-class screen rules (this sheet sits in head, so order alone would lose)
    var C = '[data-agentpill][data-agentpill][data-agentpill][data-agentpill]';
    var st = document.createElement('style');
    st.id = 'ai365RsCss';
    st.textContent = [
      // 칩(ChatResourceButton.tsx:91-106): 글 700 · 리소스 센터 아이콘 21(24 칸) · 셰브런 없음 · 활성 = #F2F6FF/#CCDAFF/#4450CE, hover #E4EDFF.
      // 공통 hover(#EDF1FA · #C3C7D2)와 그라데이션 걷기는 adapter(작업자 B1) 몫이다. 칩 라벨은 목업 syncUI 가 첫 글자 노드만 바꾸므로 아이콘은 ::before 로 둔다.
      // The chip: 700 text, the Resource Center icon at 21 in a 24 box, no chevron, active #F2F6FF/#CCDAFF/#4450CE with #E4EDFF on hover.
      // The common hover and removing the gradient belong to the adapter (worker B1). The mockup's syncUI rewrites only the first text
      // node, so the icon is a ::before.
      'html body ' + C + '{font-weight:700;gap:6px;}',
      'html body ' + C + '::before{content:"";display:inline-block;flex:none;width:24px;height:24px;vertical-align:middle;background:' + chipIcon(false) + ' center/21px 21px no-repeat;}',
      'html body ' + C + ' > svg{display:none;}',
      'html body ' + C + '.agp-active{background:#F2F6FF;border-color:#CCDAFF;color:#4450CE;}',
      'html body ' + C + '.agp-active:hover,html body ' + C + '.agp-active:active{background:#E4EDFF;border-color:#CCDAFF;color:#4450CE;}',
      'html body ' + C + '.agp-active::before{background-image:' + chipIcon(true) + ';}',
      // 틀(PopUpLayout resourceLayout): 덮개 rgba(0,0,0,.5) · 바깥 24 · 최대 폭 960 · 최대 높이 100dvh-48 · r16 · shadow-lg / the frame
      '#ai365RsOv{position:fixed;inset:0;z-index:1350;display:flex;align-items:center;justify-content:center;padding:24px;background:rgba(0,0,0,.5);font-family:' + FONT + ';-webkit-font-smoothing:antialiased;}',
      '#ai365RsOv[hidden]{display:none;}',
      '#ai365RsOv,#ai365RsOv *{box-sizing:border-box;}',
      '.ai365-rs-card{display:flex;flex-direction:column;width:100%;max-width:960px;max-height:calc(100vh - 48px);max-height:calc(100dvh - 48px);overflow:hidden;border-radius:16px;background:#fff;box-shadow:0 10px 15px -3px rgba(0,0,0,.1),0 4px 6px -4px rgba(0,0,0,.1);outline:none;color:#21242C;}',
      '.ai365-rs-head{display:flex;flex-shrink:0;align-items:flex-start;justify-content:space-between;gap:8px;padding:24px 24px 20px;}',
      '.ai365-rs-headtx{display:flex;min-width:0;flex-direction:column;}',
      // 제목 700(2026-10-28 조정자 확인): Dev PopUpLayout 의 h1 은 font-semibold(레이어 안 유틸리티)지만 Dev index.css 19행의 전역
      // h1{font-weight:bold} 가 레이어 밖이라 이겨 화면에서는 700 이다. 구획 이름(ResourceContent, h1 아님)은 600 그대로.
      // Title at 700 (2026-10-28, confirmed by the coordinator): Dev PopUpLayout's h1 has font-semibold (a layered utility), but Dev
      // index.css line 19 sets h1{font-weight:bold} outside any layer, which wins, so it renders at 700. Section names (ResourceContent,
      // not h1) stay 600.
      '.ai365-rs-title{margin:0;font-size:20px;line-height:28px;font-weight:700;color:#21242C;letter-spacing:0;}',
      '.ai365-rs-desc{margin:8px 0 0;font-size:14px;line-height:20px;font-weight:400;color:#6C707A;}',
      '.ai365-rs-x{display:flex;width:32px;height:32px;flex-shrink:0;align-items:center;justify-content:center;border:0;border-radius:8px;background:transparent;padding:0;color:#5D616A;cursor:pointer;transition:background-color .15s;}',
      '.ai365-rs-x:hover{background:#EDF1FA;}.ai365-rs-x:active{background:#DCE0EB;}',
      '.ai365-rs-content{display:flex;min-height:0;flex:1;flex-direction:column;overflow:hidden;background:#fff;}',
      '.ai365-rs-hr{flex-shrink:0;height:0;margin:0;border:0;border-top:1px solid #CDD1DC;}',
      '.ai365-rs-body{display:flex;min-height:0;flex:1;flex-direction:column;gap:16px;overflow-y:auto;padding:20px 16px 16px 24px;}',
      '.ai365-rs-foot{display:flex;flex-shrink:0;align-items:center;justify-content:space-between;gap:20px;padding:20px 24px 24px;background:#fff;}',
      '.ai365-rs-cancel{display:inline-flex;height:32px;min-width:96px;flex-shrink:0;align-items:center;justify-content:center;border:1px solid #CDD1DC;border-radius:9999px;background:#fff;padding:0 12px;font:400 14px/20px ' + FONT + ';color:#3E424B;cursor:pointer;transition:background-color .15s;}',
      '.ai365-rs-cancel:hover{background:#EDF1FA;}.ai365-rs-cancel:active{background:#DCE0EB;}',
      '.ai365-rs-done{display:inline-flex;height:32px;min-width:96px;flex-shrink:0;align-items:center;justify-content:center;gap:4px;border:0;border-radius:9999px;background:#4450CE;padding:0 12px;font:600 14px/20px ' + FONT + ';color:#fff;cursor:pointer;transition:background-color .15s;}',
      '.ai365-rs-done:hover{background:#3940BD;}.ai365-rs-done:active{background:#1D008B;}',
      '.ai365-rs-done:disabled{cursor:not-allowed;background:#ECF0FB;color:#B9BDC8;}',
      '#ai365RsOv button:focus-visible,#ai365RsOv input:focus-visible{outline:none;box-shadow:' + FOCUS + ';}',
      // 구획 = 접는 카드(ResourceContent · Accordion): 1px #CDD1DC · r16 · 안쪽 12, 머리 = [체크 · 왼쪽 8 · 오른쪽 4][제목 · 안쪽 12][셰브런 24 · 선 1]
      // A section = a collapsible card: 1px #CDD1DC, r16, padding 12; header = [checkbox ml 8 mr 4][title px 12][chevron 24, stroke 1]
      '.ai365-rs-secwrap{flex-shrink:0;}',
      '.ai365-rs-secwrap.locked{pointer-events:none;user-select:none;opacity:.4;filter:grayscale(1);}',
      '.ai365-rs-sec{width:100%;border:1px solid #CDD1DC;border-radius:16px;background:#fff;padding:12px;}',
      '.ai365-rs-sechead{display:flex;align-items:center;border-radius:6px;}',
      '.ai365-rs-sechead.sel{background:#E7EBF6;}',
      '.ai365-rs-chk{width:16px;height:16px;flex-shrink:0;margin:0;accent-color:#4450CE;cursor:pointer;}',
      '.ai365-rs-chk:disabled{cursor:not-allowed;}',
      '.ai365-rs-sechead > .ai365-rs-chk{margin:0 4px 0 8px;}',
      '.ai365-rs-trigger{display:flex;flex:1;min-width:0;align-items:center;border:0;border-radius:6px;background:transparent;padding:0;color:#21242C;font:inherit;text-align:left;cursor:pointer;}',
      '.ai365-rs-tt{display:flex;min-height:32px;min-width:0;align-items:center;padding:0 12px;}',
      '.ai365-rs-ttin{display:flex;min-width:0;align-items:center;gap:4px;font-size:14px;line-height:20px;font-weight:600;color:#21242C;}',
      '.ai365-rs-ttin .on{color:#4450CE;}',
      '.ai365-rs-ic{flex-shrink:0;}',
      '.ai365-rs-gwbox{display:flex;width:24px;height:24px;flex-shrink:0;align-items:center;justify-content:center;border-radius:6px;transition:background-color .15s;}',
      '.ai365-rs-gwbox.on{background:#E4EDFF;}',
      '.ai365-rs-badge{border-radius:9999px;padding:0 6px;font-size:12px;line-height:20px;font-weight:600;}',
      '.ai365-rs-badge.pub{background:#E4EDFF;color:#4450CE;}.ai365-rs-badge.loc{background:#F2FAFC;color:#008AA9;}',
      '.ai365-rs-chev{display:flex;flex-shrink:0;margin-left:auto;color:#21242C;transition:transform .15s;}',
      '.ai365-rs-sec.open .ai365-rs-chev{transform:rotate(180deg);}',
      '.ai365-rs-secbody[hidden]{display:none;}',
      '.ai365-rs-sechr{height:0;margin:8px 0 10px;border:0;border-top:1px solid #CDD1DC;}',
      '.ai365-rs-list{max-height:280px;overflow-y:auto;font-size:14px;line-height:20px;color:#3E424B;}',
      '.ai365-rs-empty{display:flex;min-height:32px;align-items:center;padding:0 8px;font-size:14px;line-height:20px;color:#9FA3AD;}',
      // 지식 트리(ResourceFolderTree): 행 32 · r6 · 오른쪽 8 · 단계마다 24, [셰브런 12(선 1.5) · 칸 6/10][체크 16][LV 배지 16 · 10px 700][이름 14/20] … [파일 수 10px 600 #4450CE]
      // The knowledge tree: rows 32, r6, right 8, 24 per level; [chevron 12 (stroke 1.5) in a 6/10 box][checkbox][LV badge][name] ... [file count]
      '.ai365-rs-tree{display:flex;flex-direction:column;gap:2px;overflow-x:hidden;}',
      '.ai365-rs-fnode{display:flex;flex-direction:column;}',
      '.ai365-rs-frow{display:flex;min-height:32px;align-items:center;flex-wrap:nowrap;border-radius:6px;padding-right:8px;font-size:12px;transition:background-color .15s;}',
      '.ai365-rs-frow:hover{background:#F6F8FD;}.ai365-rs-frow.on{background:#E7EBF6;}',
      '.ai365-rs-frow.ro:hover{background:transparent;}',
      '.ai365-rs-carbox{display:flex;flex-shrink:0;align-items:flex-start;padding:10px 6px;}',
      '.ai365-rs-caret{display:flex;width:12px;height:12px;flex-shrink:0;align-items:center;justify-content:center;border:0;border-radius:2px;background:transparent;padding:0;color:#3E424B;cursor:pointer;}',
      '.ai365-rs-caret svg{transition:transform .15s;}',
      '.ai365-rs-caret.open svg{transform:rotate(90deg);}',
      '.ai365-rs-carsp{width:12px;height:12px;flex-shrink:0;}',
      '.ai365-rs-fmain{display:flex;flex:1;min-width:0;align-items:center;gap:4px;margin-right:8px;cursor:pointer;}',
      '.ai365-rs-frow.ro .ai365-rs-fmain{cursor:default;}',
      '.ai365-rs-lv{display:flex;height:16px;flex-shrink:0;align-items:center;justify-content:center;border-radius:9999px;padding:0 6px;font-size:10px;line-height:16px;font-weight:700;color:#fff;}',
      '.ai365-rs-lv.l1{background:#1C1F27;}.ai365-rs-lv.l2{background:#767A84;}.ai365-rs-lv.l3{background:#AFB3BE;}',
      '.ai365-rs-fname{flex:1;min-width:0;overflow:hidden;padding:0 2px;font-size:14px;line-height:20px;color:#3E424B;text-overflow:ellipsis;white-space:nowrap;}',
      '.ai365-rs-frow.on .ai365-rs-fname,.ai365-rs-file.on .ai365-rs-fname{color:#4450CE;font-weight:600;}',
      '.ai365-rs-fcnt{display:flex;height:16px;min-width:16px;flex-shrink:0;align-items:center;justify-content:flex-end;margin-left:auto;padding:0 2px;font-size:10px;font-weight:600;color:#4450CE;}',
      '.ai365-rs-files{display:flex;flex-direction:column;gap:2px;padding:2px 0;}',
      '.ai365-rs-file{display:flex;min-height:32px;align-items:center;gap:4px;border-radius:6px;padding-right:8px;cursor:pointer;transition:background-color .15s;}',
      '.ai365-rs-file:hover{background:#F6F8FD;}.ai365-rs-file.on{background:#E7EBF6;}',
      '.ai365-rs-file .ai365-rs-fname{padding:6px 2px;}',
      // 데이터 트리(DataAnalysisResource): 워크스페이스 LV.1 → DB/BI/CSV LV.2(왼쪽 32) → 항목(왼쪽 68, 종류 배지 29×16 r12 12px 700)
      // The data tree: workspace LV.1 → DB/BI/CSV LV.2 (left 32) → items (left 68, type badge 29×16, r12, 12px 700)
      '.ai365-rs-drow{display:flex;align-items:center;overflow:hidden;border-radius:6px;padding-right:8px;cursor:pointer;transition:background-color .15s;}',
      '.ai365-rs-drow:hover{background:#F6F8FD;}.ai365-rs-drow.leaf.on{background:#E7EBF6;}',
      '.ai365-rs-dcar{display:flex;width:24px;flex-shrink:0;align-items:center;padding-left:4px;}',
      '.ai365-rs-dcar .ai365-rs-caret{width:16px;height:16px;}',
      '.ai365-rs-dmain{display:flex;flex:1;min-width:0;align-items:center;gap:8px;padding:6px 0;font-size:14px;cursor:pointer;}',
      '.ai365-rs-dlv{flex-shrink:0;border-radius:9999px;padding:0 8px;font-size:12px;line-height:20px;color:#fff;}',
      '.ai365-rs-dname{display:flex;min-width:0;align-items:center;gap:8px;padding-right:8px;font-size:14px;line-height:20px;}',
      '.ai365-rs-drow.leaf.on .ai365-rs-dname{color:#4450CE;font-weight:600;}',
      '.ai365-rs-type{display:inline-flex;width:29px;height:16px;flex-shrink:0;align-items:center;justify-content:center;border-radius:12px;font-size:12px;line-height:16px;font-weight:700;}',
      '.ai365-rs-type.t-bi{color:#FFA83D;background:#FFFAF5;}.ai365-rs-type.t-db{color:#6174F5;background:#F2F6FF;}.ai365-rs-type.t-csv{color:#359B35;background:#F1FAF1;}',
      // 그룹웨어 · 업무 자동화 줄(GroupwareResource · ChatResource 업무 자동화): 32 · r6 · 좌우 8 · 간격 8, 켜짐 #E7EBF6 + #4450CE 600
      // Groupware and work-automation rows: 32, r6, sides 8, gap 8; on = #E7EBF6 + #4450CE 600
      '.ai365-rs-alist{display:flex;flex-direction:column;gap:2px;}',
      '.ai365-rs-arow{display:flex;min-height:32px;align-items:center;gap:8px;border-radius:6px;padding:0 8px;font-size:14px;line-height:20px;color:#3E424B;cursor:pointer;transition:background-color .15s;}',
      '.ai365-rs-arow:hover{background:#F6F8FD;}.ai365-rs-arow.on{background:#E7EBF6;font-weight:600;color:#4450CE;}',
      // Local 트리(ChatResource LocalKnowledgeTree): 뿌리 줄 [셰브런 24×32][체크][Local n 배지 #008AA9][이름], 폴더는 단계마다 24 / the Local tree
      '.ai365-rs-lnode{display:flex;flex-direction:column;gap:2px;}',
      '.ai365-rs-lroot{display:flex;min-height:32px;align-items:center;gap:4px;padding-right:8px;}',
      '.ai365-rs-lcar{display:flex;width:24px;height:32px;flex-shrink:0;align-items:center;justify-content:center;border:0;border-radius:4px;background:transparent;padding:0;color:#3E424B;cursor:pointer;}',
      '.ai365-rs-lmain{display:flex;min-width:0;align-items:center;gap:4px;cursor:pointer;}',
      '.ai365-rs-lbadge{display:inline-flex;height:16px;flex-shrink:0;align-items:center;justify-content:center;border-radius:9999px;background:#008AA9;padding:0 6px;font-size:10px;line-height:16px;font-weight:700;color:#fff;}',
      '.ai365-rs-lname{min-width:0;overflow:hidden;padding:0 2px;font-size:14px;line-height:20px;color:#3E424B;text-overflow:ellipsis;white-space:nowrap;}',
      // 코치 툴팁(ContentWithToolTip 규칙: #262931 · 흰 12px · r4 · 4/8 · shadow-md) + 위쪽 꼬리 / the coach tooltip with an upward tail
      '.ai365-rs-coach{position:fixed;z-index:60;display:none;transform:translateX(-50%);padding:4px 8px;border-radius:4px;background:#262931;color:#fff;font:400 12px/16px ' + FONT + ';white-space:nowrap;pointer-events:none;box-shadow:0 4px 6px -1px rgba(0,0,0,.1),0 2px 4px -2px rgba(0,0,0,.1);}',
      '.ai365-rs-coach.show{display:block;}',
      '.ai365-rs-coach::before{content:"";position:absolute;bottom:100%;left:50%;margin-left:-5px;border:5px solid transparent;border-bottom-color:#262931;}'
    ].join('\n');
    document.head.appendChild(st);
  })();

  /* ── 원본 훅과 로컬 선택 / the original hooks and the local selection ── */
  var O = {
    agents: H.agents, files: H.files, setAgents: H.setAgents, setFiles: H.setFiles,
    openMenu: H.openMenu, closeMenu: H.closeMenu
  };
  var local = [];   // 확정된 로컬 지식 에이전트 id / the applied local knowledge agent ids
  function onlyKnowledge(keys) {
    var k = uniq(keys).filter(function (x) { return ORDER.indexOf(x) >= 0; });
    return k.length === 1 && k[0] === 'knowledge';
  }
  // 로컬 선택이 지금 유효한가 = 공유 상태가 "지식 관리만 · 파일 없음"일 때만(다른 화면이 상태를 바꾸면 저절로 꺼진다)
  // The local choice is live only while the shared state is "knowledge only, no files" (any other change turns it off by itself)
  function liveLocal() {
    if (!local.length) return [];
    var a = [];
    try { a = O.agents() || []; } catch (e) { return []; }
    if (!onlyKnowledge(a)) return [];
    try { if ((O.files() || []).length) return []; } catch (e) { return []; }
    return local.slice();
  }
  function isLocalKey(k) { return typeof k === 'string' && k.indexOf(LOCAL_KEY) === 0 && k.length > LOCAL_KEY.length; }
  // files() 에 로컬 가짜 키를 덧붙이고, setFiles() 는 그 키를 로컬 선택으로 되살린다. 예약 창 · 예약 페이지의 스태시/복원이 로컬 선택도 왕복시킨다.
  // Public 키가 함께 오면 Public 이 이긴다(로컬 배타). setAgents 가 "지식 관리만"이 아니면 로컬 선택을 지운다.
  // files() appends local pseudo keys and setFiles() turns them back into the local choice, so the stash/restore of the schedule
  // dialog and page round-trips the local choice too. Public keys win when both come (local is exclusive). setAgents to anything
  // but "knowledge only" clears the local choice.
  H.files = function () {
    var f = O.files.apply(this, arguments) || [];
    var l = liveLocal();
    return l.length ? f.concat(l.map(function (id) { return LOCAL_KEY + id; })) : f;
  };
  H.setFiles = function (arr) {
    var loc = [], rest = [];
    (Array.isArray(arr) ? arr : []).forEach(function (k) { if (isLocalKey(k)) loc.push(k.slice(LOCAL_KEY.length)); else rest.push(k); });
    local = rest.length ? [] : uniq(loc);
    var r = O.setFiles.call(this, rest);
    coachSync();
    return r;
  };
  H.setAgents = function (keys) {
    if (!onlyKnowledge(keys)) local = [];
    var r = O.setAgents.apply(this, arguments);
    coachSync();
    return r;
  };
  // 예약 페이지(#ai365SdAgent)는 훅으로 연다 → 같은 대화 상자 / the schedules page opens through the hook → the same dialog
  H.openMenu = function (anchor) { openModal(anchor || null); };
  H.closeMenu = function () {
    if (S.open) closeModal();
    return typeof O.closeMenu === 'function' ? O.closeMenu.apply(this, arguments) : undefined;
  };

  /* ── 전송: scope_files.local_agents / sending ── */
  // adapter 의 ai365SelectionSnapshot(전역 function 선언)은 H.scope() 를 읽은 뒤 알려진 키만 남기므로 local_agents 를 여기서 덧붙인다.
  // ① opts.scopeFiles 가 넘어오면(새 채팅의 두 번째 스냅숏 등) 그 local_agents 를 그대로 잇고 ② 아니면 사내 · 지식 관리 선택일 때 지금 로컬 선택을 싣는다.
  // H.scope() 는 감싸지 않는다: 예약 저장(/api/schedules)은 scope_files 의 모르는 키를 422 로 거절한다.
  // The adapter's ai365SelectionSnapshot (a global function declaration) reads H.scope() and keeps only known keys, so local_agents is
  // added here: (1) forwarded from opts.scopeFiles when given (e.g. the second snapshot of a new chat), (2) otherwise the current local
  // choice for an Internal, knowledge selection. H.scope() is not wrapped: saving a schedule (/api/schedules) rejects unknown
  // scope_files keys with 422.
  // 분야를 명시로 넘기면(opts.agents, 2026-10-28 검토 반영) 그 분야는 호출한 쪽이 정한 것이라 컴포저의 로컬 선택을 잇지 않는다(그룹웨어 홈 미니
  // 입력 ai365HomeAskStart 의 분야 프리셋에 남아 있던 로컬 선택이 실리던 문제). 단 컬렉션 컴포저(cdSubmit)처럼 컴포저 선택을
  // AI365_COMPOSER_AGENTS_RAW() 그대로 넘긴 배열은 컴포저 선택이므로 잇는다: 그 함수가 돌려준 배열을 WeakSet 으로 기억해 가른다.
  // An explicit opts.agents (2026-10-28 review) is the caller's own choice, so the composer's local choice is not carried over (the
  // groupware home mini composer's ai365HomeAskStart preset used to pick up a stale local choice). An array passed straight from
  // AI365_COMPOSER_AGENTS_RAW(), as the collection composer (cdSubmit) does, is the composer's selection and keeps it: the arrays
  // that function returns are remembered in a WeakSet to tell them apart.
  var fromComposer = (typeof WeakSet === 'function') ? new WeakSet() : null;
  var origRaw = window.AI365_COMPOSER_AGENTS_RAW;
  if (fromComposer && typeof origRaw === 'function' && !origRaw.ai365Rs) {
    var rawWrapped = function () {
      var r = origRaw.apply(this, arguments);
      try { if (r && typeof r === 'object') fromComposer.add(r); } catch (e) { /* 기억 실패 = 명시로 본다 / unremembered = explicit */ }
      return r;
    };
    rawWrapped.ai365Rs = true;
    window.AI365_COMPOSER_AGENTS_RAW = rawWrapped;
  }
  function composerAgents(a) {
    try { return !!(fromComposer && a && typeof a === 'object' && fromComposer.has(a)); } catch (e) { return false; }
  }
  var origSnap = window.ai365SelectionSnapshot;
  if (typeof origSnap === 'function' && !origSnap.ai365Rs) {
    var wrapped = function (opts) {
      var out = origSnap.apply(this, arguments);
      try {
        if (out && out.scopeFiles && typeof out.scopeFiles === 'object') {
          var sf = opts && opts.scopeFiles, ids = [];
          if (sf && typeof sf === 'object') ids = Array.isArray(sf.local_agents) ? uniq(sf.local_agents) : [];
          else if (opts && opts.agents != null && !composerAgents(opts.agents)) ids = [];   // 명시한 분야 / explicit domains
          else if (out.scope === '사내' && (out.agents || []).indexOf('knowledge') >= 0) ids = liveLocal();
          if (ids.length) out.scopeFiles.local_agents = ids;
        }
      } catch (e) { /* 스냅숏은 그대로 / the snapshot stays as it is */ }
      return out;
    };
    wrapped.ai365Rs = true;
    window.ai365SelectionSnapshot = wrapped;
  }

  /* ── 대화 상자 상태 / dialog state ── */
  var S = {
    open: false, anchor: null, schedule: false,
    nodes: { knowledge: [], data: [], groupware: [], work: [] }, knowAllowed: false,
    index: {},          // 키 → {sec, node, path(조상)} / key → {sec, node, path (ancestors)}
    temp: null,         // 임시 선택(Public 지식 · 데이터 · 그룹웨어 · 업무 키) / the temporary selection
    tempLocal: [],      // 임시 로컬 선택 / the temporary local choice
    secOpen: {}, nodeOpen: {},
    agents: {},         // 사용자별 로컬 에이전트 목록 캐시 {list, loading, error} / per-user local agent list cache
    folders: {},        // 사용자|에이전트 → {list, loading, error} / per-user, per-agent folders
    downOnOv: false
  };
  function secOf(domain) { return { knowledge: 'kpub', data: 'data', groupware: 'groupware', work: 'work' }[domain]; }
  function domainOf(k) {
    if (/^knf?:/.test(k)) return 'knowledge';
    if (/^wsi?:/.test(k)) return 'data';
    if (k === 'gw:agent') return 'groupware';
    if (/^work:/.test(k)) return 'work';
    return null;
  }
  function kids(n) { return (n && n.children) || []; }
  function subtreeKeys(n) { var out = [n.key]; kids(n).forEach(function (c) { out = out.concat(subtreeKeys(c)); }); return out; }
  function leafKeys(n) { var c = kids(n); if (!c.length) return [n.key]; var out = []; c.forEach(function (x) { out = out.concat(leafKeys(x)); }); return out; }
  function isOn(n) {
    if (S.temp.has(n.key)) return true;
    if (!kids(n).length) return false;
    var lv = leafKeys(n);
    return lv.length > 0 && lv.every(function (k) { return S.temp.has(k); });
  }
  function secNodes(sk) {
    return sk === 'kpub' ? S.nodes.knowledge : sk === 'data' ? S.nodes.data : sk === 'groupware' ? S.nodes.groupware : sk === 'work' ? S.nodes.work : [];
  }
  function localList() {
    var c = S.agents[acting()];
    return (c && c.list) || [];
  }

  // 네 분야 트리를 한 번에 읽는다: 공유 상태를 잠깐 "네 분야 전부"로 두고 sections() 를 읽은 뒤 그 자리에서 되돌린다(권한 없는 분야는 setAgents 가 뺀다).
  // Read the four domain trees at once: the shared state briefly holds all four domains, sections() is read, and the state is put
  // back on the spot (setAgents already drops unreadable domains).
  function readSections() {
    var a = [], f = [];
    try { a = (O.agents() || []).slice(); f = (O.files() || []).slice(); } catch (e) { /* 빈 상태로 / empty */ }
    var out = { knowledge: [], data: [], groupware: [], work: [] }, seen = {};
    try {
      O.setAgents(ORDER.slice());
      (H.sections() || []).forEach(function (s) { if (s && out[s.key]) { out[s.key] = s.nodes || []; seen[s.key] = true; } });
    } catch (e) {
      console.warn('[AI365 resource select] 리소스 트리를 읽지 못했습니다 / could not read the resource trees', e);
    } finally {
      try { O.setFiles(f); O.setAgents(a); } catch (e) { /* 복원 실패는 다음 동기화가 고친다 / the next sync repairs it */ }
    }
    S.nodes = out;
    S.knowAllowed = !!seen.knowledge;
    S.index = {};
    Object.keys(out).forEach(function (d) {
      (function walk(nodes, path) {
        (nodes || []).forEach(function (n) {
          if (!n || !n.key) return;
          S.index[n.key] = { sec: secOf(d), node: n, path: path };
          walk(kids(n), path.concat([n]));
        });
      })(out[d], []);
    });
  }

  /* ── 열기 · 닫기 · 반영 / open, close, apply ── */
  function isScheduleCtx(anchor) {
    return !!(anchor && anchor.closest && anchor.closest('#cdSchedOv, .ai365-sd-composer, #ai365SdAgent, #cdSchedAgentPill'));
  }
  function openModal(anchor) {
    if (S.open) return;
    try { if (typeof O.closeMenu === 'function') O.closeMenu(); } catch (e) { /* noop */ }
    readSections();
    S.anchor = anchor || null;
    S.schedule = isScheduleCtx(anchor);
    // 지금 선택을 3분할 패널과 같은 어휘(폴더 키 = 하위 전부)로 펼쳐 둔다(resolveScope 결과는 그대로다).
    // Expand the current choice into the three-pane vocabulary (a folder key = all its descendants); resolveScope gives the same result.
    S.temp = new Set();
    (O.files() || []).forEach(function (k) {
      var it = S.index[k];
      if (it) subtreeKeys(it.node).forEach(function (x) { S.temp.add(x); });
    });
    S.tempLocal = S.schedule ? [] : liveLocal();
    // 열 때 확정 선택이 있었는가(분야만 고른 상태 포함). 있으면 모두 풀고 [선택 완료]로 해제할 수 있다(Dev 는 0개면 늘 비활성이라 해제할 길이 없다).
    // Whether a choice was applied when the dialog opened (a domain-only choice included); if so, clearing everything can be applied
    // with [Done] (Dev always disables it at zero, which leaves no way to clear).
    var had = [];
    try { had = O.agents() || []; } catch (e) { /* 없음 / none */ }
    S.had = S.temp.size > 0 || S.tempLocal.length > 0 || had.length > 0;
    S.secOpen = {};
    S.nodeOpen = {};
    S.folders = {};   // 폴더는 열 때마다 새로(펼칠 때 받는다) / folders are fetched afresh per opening (on expand)
    S.open = true;
    var ov = ensureDom();
    S.prevFocus = document.activeElement;
    paint();
    ov.hidden = false;
    var card = ov.querySelector('.ai365-rs-card');
    if (card) { try { card.focus({ preventScroll: true }); } catch (e) { card.focus(); } }
    coachSync();
    loadAgents(false);
  }
  function closeModal() {
    if (!S.open) return;
    S.open = false;
    var ov = document.getElementById('ai365RsOv');
    if (ov) ov.hidden = true;
    var back = S.anchor && S.anchor.isConnected ? S.anchor : (S.prevFocus && S.prevFocus.isConnected ? S.prevFocus : null);
    S.anchor = null; S.prevFocus = null;
    if (back && typeof back.focus === 'function') { try { back.focus({ preventScroll: true }); } catch (e) { /* noop */ } }
    coachSync();
  }
  function apply() {
    var files = Array.from(S.temp), loc = S.tempLocal.slice();
    if (!files.length && !loc.length && !S.had) return;   // 빈 반영은 해제할 선택이 있을 때만 / an empty apply only clears an existing choice
    var domains = ORDER.filter(function (d) { return files.some(function (k) { return domainOf(k) === d; }); });
    try {
      O.setAgents(ORDER.slice());
      O.setFiles(loc.length ? [] : files);
      O.setAgents(loc.length ? ['knowledge'] : domains);
    } catch (e) {
      console.warn('[AI365 resource select] 선택을 반영하지 못했습니다 / could not apply the selection', e);
    }
    local = loc;
    closeModal();
  }

  /* ── 로컬 에이전트 · 폴더 / local agents and folders ── */
  function fetchJson(url) {
    return fetch(url, { headers: { Accept: 'application/json' } }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, status: r.status, j: j }; }, function () { return { ok: r.ok, status: r.status, j: null }; });
    });
  }
  // 목록 = GET /api/knowledge-agents(이 사용자에게 보이는 것, 사용 중인 것만). 서버가 없으면 부트스트랩의 AI365_LOCAL_AGENTS 로.
  // The list = GET /api/knowledge-agents (what this user sees, enabled ones only); without the server, the bootstrap's AI365_LOCAL_AGENTS.
  function fallbackAgents() {
    var ags = Array.isArray(window.AI365_LOCAL_AGENTS) ? window.AI365_LOCAL_AGENTS : [];
    return ags.filter(function (a) { return a && a.id && (!window.AI365_canRead || window.AI365_canRead(a.id)); })
      .map(function (a) { return { id: String(a.id), name: String(a.label || a.name || a.id) }; });
  }
  function loadAgents(force) {
    if (!S.knowAllowed) return;
    var who = acting(), c = S.agents[who];
    if (c && c.loading && !force) return;
    var seq = (c && c.seq || 0) + 1;
    S.agents[who] = { list: c ? c.list : null, loading: true, error: '', seq: seq };
    if (S.open) paint();
    fetchJson('/api/knowledge-agents?acting_user_id=' + encodeURIComponent(who)).then(function (res) {
      var cur = S.agents[who];
      if (!cur || cur.seq !== seq) return;
      if (res.ok && res.j && Array.isArray(res.j.agents)) {
        cur.list = res.j.agents.filter(function (a) { return a && a.id && a.enabled !== false; })
          .map(function (a) { return { id: String(a.id), name: String(a.name || a.id) }; });
      } else if (!cur.list) {
        var fb = fallbackAgents();
        if (fb.length) cur.list = fb; else cur.error = '목록을 불러오지 못했습니다';
      }
      cur.loading = false;
      settled();
    }).catch(function () {
      var cur = S.agents[who];
      if (!cur || cur.seq !== seq) return;
      cur.loading = false;
      if (!cur.list) { var fb = fallbackAgents(); if (fb.length) cur.list = fb; else cur.error = '목록을 불러오지 못했습니다'; }
      settled();
    });
    function settled() {
      if (!S.open) return;
      var ids = localList().map(function (a) { return a.id; });
      S.tempLocal = S.tempLocal.filter(function (id) { return ids.indexOf(id) >= 0; });
      paint();
    }
  }
  function loadFolders(aid) {
    var key = acting() + '|' + aid;
    if (S.folders[key]) return;
    S.folders[key] = { loading: true };
    fetchJson('/api/knowledge-agents/' + encodeURIComponent(aid) + '/folders?acting_user_id=' + encodeURIComponent(acting())).then(function (res) {
      S.folders[key] = (res.ok && res.j && Array.isArray(res.j.folders)) ? { list: res.j.folders } : { error: true };
      if (S.open) paint();
    }).catch(function () {
      S.folders[key] = { error: true };
      if (S.open) paint();
    });
  }

  /* ── 그리기 / rendering ── */
  function ensureDom() {
    var ov = document.getElementById('ai365RsOv');
    if (ov) return ov;
    ov = document.createElement('div');
    ov.id = 'ai365RsOv';
    ov.hidden = true;
    ov.setAttribute('data-i18n-skip', '');
    ov.innerHTML = '<div class="ai365-rs-card" role="dialog" aria-modal="true" aria-labelledby="ai365RsTitle" aria-describedby="ai365RsDesc" tabindex="-1">'
      + '<div class="ai365-rs-head"><div class="ai365-rs-headtx"><h1 class="ai365-rs-title" id="ai365RsTitle"></h1><p class="ai365-rs-desc" id="ai365RsDesc"></p></div>'
      + '<button type="button" class="ai365-rs-x" data-rs-close>' + SVG_X + '</button></div>'
      + '<div class="ai365-rs-content"><hr class="ai365-rs-hr"><div class="ai365-rs-body" id="ai365RsBody"></div><hr class="ai365-rs-hr">'
      + '<div class="ai365-rs-foot"><button type="button" class="ai365-rs-cancel" data-rs-cancel></button><button type="button" class="ai365-rs-done" data-rs-done></button></div></div></div>';
    document.body.appendChild(ov);
    ov.addEventListener('mousedown', function (e) { S.downOnOv = (e.target === ov); });
    ov.addEventListener('click', onClick);
    ov.addEventListener('change', onChange);
    return ov;
  }
  function chkHtml(attr, val, on, label, disabled) {
    return '<input type="checkbox" class="ai365-rs-chk" ' + attr + '="' + esc(val) + '" data-rs-focus="' + esc(attr + ':' + val) + '"'
      + (on ? ' checked' : '') + (disabled ? ' disabled' : '') + (label ? ' aria-label="' + esc(label) + '"' : '') + '>';
  }
  function caretHtml(key, open, size, sw, cls) {
    return '<button type="button" class="' + (cls || 'ai365-rs-caret') + (open ? ' open' : '') + '" data-rs-caret="' + esc(key) + '" data-rs-focus="' + esc('caret:' + key) + '"'
      + ' aria-expanded="' + (open ? 'true' : 'false') + '" aria-label="' + esc(T('펼치기/접기')) + '">' + svgChev('right', size, sw) + '</button>';
  }
  function emptyHtml(msg) { return '<div class="ai365-rs-empty">' + esc(T(msg)) + '</div>'; }
  function name(n) { return TD(n.name || ''); }

  // 지식(Public) 폴더 · 파일(ResourceFolderTree): 폴더 아래 파일이 먼저, 하위 폴더가 뒤 / files first, then subfolders
  function kFolderHtml(n) {
    var c = kids(n), files = c.filter(function (x) { return x.file; }), folders = c.filter(function (x) { return !x.file; });
    var open = !!S.nodeOpen[n.key], on = isOn(n), lv = Math.max(1, n.lv || 1), nm = name(n);
    var h = '<div class="ai365-rs-fnode"><div class="ai365-rs-frow' + (on ? ' on' : '') + '" data-rs-row="' + esc(n.key) + '" style="padding-left:' + ((lv - 1) * 24) + 'px">'
      + '<span class="ai365-rs-carbox">' + (c.length ? caretHtml(n.key, open, 12, 1.5) : '<span class="ai365-rs-carsp"></span>') + '</span>'
      + '<label class="ai365-rs-fmain">' + chkHtml('data-rs-check', n.key, on, nm)
      + '<span class="ai365-rs-lv l' + Math.min(lv, 3) + '">LV.' + lv + '</span><span class="ai365-rs-fname" title="' + esc(nm) + '">' + esc(nm) + '</span></label>'
      + '<span class="ai365-rs-fcnt">' + (n.count == null ? 0 : n.count) + '</span></div>';
    if (c.length && open) {
      if (files.length) {
        h += '<div class="ai365-rs-files">' + files.map(function (f) {
          var fo = S.temp.has(f.key), fn = name(f);
          return '<label class="ai365-rs-file' + (fo ? ' on' : '') + '" data-rs-row="' + esc(f.key) + '" style="padding-left:' + (32 + (lv - 1) * 24) + 'px">'
            + chkHtml('data-rs-check', f.key, fo, fn) + '<span class="ai365-rs-fname" title="' + esc(fn) + '">' + esc(fn) + '</span></label>';
        }).join('') + '</div>';
      }
      h += folders.map(kFolderHtml).join('');
    }
    return h + '</div>';
  }
  // 데이터(DataAnalysisResource): LV.1 워크스페이스 · LV.2 DB/BI/CSV · LV.3 항목(종류 배지) / workspaces, buckets, items
  function dNodeHtml(n) {
    var c = kids(n), lv = n.lv || 1, open = !!S.nodeOpen[n.key], on = isOn(n), nm = name(n);
    var leaf = lv >= 3 || !c.length;
    var pad = lv === 1 ? (c.length ? 0 : 16) : lv === 2 ? 32 : 68;
    var label = lv >= 3
      ? '<span class="ai365-rs-dname">' + (n.item ? '<span class="ai365-rs-type t-' + esc(String(n.item).toLowerCase()) + '">' + esc(n.item) + '</span>' : '') + '<span>' + esc(nm) + '</span></span>'
      : '<span class="ai365-rs-dlv" style="background:' + (lv === 1 ? '#1C1F27' : '#767A84') + '">LV.' + lv + '</span><span class="ai365-rs-dname">' + esc(nm) + '</span>';
    var h = '<div class="ai365-rs-drow' + (leaf ? ' leaf' : '') + (on ? ' on' : '') + '" data-rs-row="' + esc(n.key) + '" style="padding-left:' + pad + 'px">'
      + (lv < 3 && c.length ? '<span class="ai365-rs-dcar">' + caretHtml(n.key, open, 16, 2) + '</span>' : '')
      + '<label class="ai365-rs-dmain">' + chkHtml('data-rs-check', n.key, on, nm) + label + '</label></div>';
    if (c.length && open) h += c.map(dNodeHtml).join('');
    return h;
  }
  function aRowsHtml(nodes) {
    return '<div class="ai365-rs-alist">' + nodes.map(function (n) {
      var on = S.temp.has(n.key), nm = name(n);
      return '<label class="ai365-rs-arow' + (on ? ' on' : '') + '" data-rs-row="' + esc(n.key) + '">' + chkHtml('data-rs-check', n.key, on, nm) + '<span>' + esc(nm) + '</span></label>';
    }).join('') + '</div>';
  }
  // Local: 에이전트 = 뿌리 줄(체크 = 선택 단위), 펼치면 그 에이전트의 폴더(보기만, 단계마다 24) / agents as root rows, folders view-only
  function lFolderHtml(aid, f, lv) {
    var key = 'lf:' + aid + '/' + f.id, c = Array.isArray(f.children) ? f.children : [], open = !!S.nodeOpen[key], nm = String(f.name || f.id || '');
    var h = '<div class="ai365-rs-frow ro" style="padding-left:' + (24 * lv) + 'px"><span class="ai365-rs-carbox">'
      + (c.length ? caretHtml(key, open, 12, 1.5) : '<span class="ai365-rs-carsp"></span>') + '</span>'
      + '<span class="ai365-rs-fmain"><span class="ai365-rs-lv l' + Math.min(lv, 3) + '">LV.' + lv + '</span><span class="ai365-rs-fname" title="' + esc(nm) + '">' + esc(nm) + '</span></span></div>';
    if (c.length && open) h += c.map(function (x) { return lFolderHtml(aid, x, lv + 1); }).join('');
    return h;
  }
  function localHtml() {
    if (!S.knowAllowed) return emptyHtml('선택할 수 있는 리소스가 없습니다');
    var c = S.agents[acting()];
    if (!c || (!c.list && c.loading)) return emptyHtml('불러오는 중…');
    if (!c.list) return emptyHtml(c.error || '목록을 불러오지 못했습니다');
    if (!c.list.length) return emptyHtml('등록된 로컬 지식 에이전트가 없습니다');
    return '<div class="ai365-rs-tree">' + c.list.map(function (a, i) {
      var on = S.tempLocal.indexOf(a.id) >= 0, k = 'la:' + a.id, open = S.nodeOpen[k] !== false;   // Dev 처럼 뿌리는 기본 펼침 / roots open by default as in Dev
      var h = '<div class="ai365-rs-lnode"><div class="ai365-rs-lroot" data-rs-row="' + esc(LOCAL_KEY + a.id) + '">'
        + '<button type="button" class="ai365-rs-lcar" data-rs-caret="' + esc(k) + '" data-rs-focus="' + esc('caret:' + k) + '" aria-expanded="' + (open ? 'true' : 'false') + '" aria-label="' + esc(T('펼치기/접기')) + '">'
        + svgChev(open ? 'down' : 'right', 12, 2) + '</button>'
        + '<label class="ai365-rs-lmain">' + chkHtml('data-rs-local', a.id, on, a.name)
        + '<span class="ai365-rs-lbadge">Local ' + (i + 1) + '</span><span class="ai365-rs-lname" title="' + esc(a.name) + '">' + esc(a.name) + '</span></label></div>';
      if (open) {
        var fk = acting() + '|' + a.id, fo = S.folders[fk];
        if (!fo) { loadFolders(a.id); fo = S.folders[fk]; }
        if (fo.loading) h += '<div class="ai365-rs-empty" style="padding-left:32px">' + esc(T('불러오는 중…')) + '</div>';
        else if (fo.error) h += '<div class="ai365-rs-empty" style="padding-left:32px">' + esc(T('폴더를 불러오지 못했습니다')) + '</div>';
        else if (!fo.list.length) h += '<div class="ai365-rs-empty" style="padding-left:32px">' + esc(T('폴더가 없습니다')) + '</div>';
        else h += fo.list.map(function (f) { return lFolderHtml(a.id, f, 1); }).join('');
      }
      return h + '</div>';
    }).join('') + '</div>';
  }
  function listHtml(sk) {
    if (sk === 'klocal') return localHtml();
    var nodes = secNodes(sk);
    if (!nodes.length) return emptyHtml('선택할 수 있는 리소스가 없습니다');
    if (sk === 'kpub') return '<div class="ai365-rs-tree">' + nodes.map(kFolderHtml).join('') + '</div>';
    if (sk === 'data') return '<div class="ai365-rs-tree">' + nodes.map(dNodeHtml).join('') + '</div>';
    return aRowsHtml(nodes);
  }
  function secState(sk) {
    if (sk === 'klocal') {
      var ids = localList().map(function (a) { return a.id; });
      return { selectable: S.knowAllowed && !S.schedule && ids.length > 0,
        all: ids.length > 0 && ids.every(function (id) { return S.tempLocal.indexOf(id) >= 0; }) };
    }
    var leaves = [];
    secNodes(sk).forEach(function (n) { leaves = leaves.concat(leafKeys(n)); });
    return { selectable: leaves.length > 0, all: leaves.length > 0 && leaves.every(function (k) { return S.temp.has(k); }) };
  }
  function titleHtml(sk, all) {
    var nm = '<span' + (all ? ' class="on"' : '') + '>' + esc(T(SEC_NAME[sk])) + '</span>';
    if (sk === 'kpub') return icKnow(all) + nm + '<span class="ai365-rs-badge pub">Public</span>';
    if (sk === 'klocal') return icKnow(all) + nm + '<span class="ai365-rs-badge loc">Local</span>';
    if (sk === 'data') return icChart(all) + nm;
    if (sk === 'groupware') return icGw(all) + nm;
    return icBot(all) + nm;
  }
  function locked(sk) { return sk === 'klocal' ? S.schedule : S.tempLocal.length > 0; }
  function secHtml(sk) {
    var st = secState(sk), open = !!S.secOpen[sk], lock = locked(sk);
    var note = (sk === 'klocal' && S.schedule) ? ' title="' + esc(T('예약 작업에서는 로컬 지식 에이전트를 쓸 수 없습니다')) + '"' : '';
    return '<div class="ai365-rs-secwrap' + (lock ? ' locked' : '') + '" data-rs-sec="' + sk + '"' + (lock ? ' inert aria-disabled="true"' : '') + note + '>'
      + '<div class="ai365-rs-sec' + (open ? ' open' : '') + '"><div class="ai365-rs-sechead' + (st.all ? ' sel' : '') + '">'
      + chkHtml('data-rs-secall', sk, st.all, T('전체 선택'), !st.selectable)
      + '<button type="button" class="ai365-rs-trigger" data-rs-toggle="' + sk + '" data-rs-focus="' + esc('toggle:' + sk) + '" aria-expanded="' + (open ? 'true' : 'false') + '">'
      + '<span class="ai365-rs-tt"><span class="ai365-rs-ttin">' + titleHtml(sk, st.all) + '</span></span>'
      + '<span class="ai365-rs-chev">' + svgChev('down', 24, 1) + '</span></button></div>'
      + '<div class="ai365-rs-secbody"' + (open ? '' : ' hidden') + '><hr class="ai365-rs-sechr"><div class="ai365-rs-list" data-rs-list="' + sk + '">'
      + (open ? listHtml(sk) : '') + '</div></div></div></div>';
  }
  function paint() {
    var ov = ensureDom(), body = document.getElementById('ai365RsBody');
    if (!body) return;
    var keep = { top: body.scrollTop, lists: {} };
    body.querySelectorAll('[data-rs-list]').forEach(function (el) { keep.lists[el.getAttribute('data-rs-list')] = el.scrollTop; });
    var act = document.activeElement, focusKey = (act && ov.contains(act) && act.getAttribute) ? act.getAttribute('data-rs-focus') : null;
    ov.querySelector('#ai365RsTitle').textContent = T('리소스 선택');
    ov.querySelector('#ai365RsDesc').textContent = T('AI가 참고할 폴더·파일을 선택하세요');
    var x = ov.querySelector('[data-rs-close]');
    x.setAttribute('aria-label', T('닫기'));
    ov.querySelector('[data-rs-cancel]').textContent = T('취소');
    var done = ov.querySelector('[data-rs-done]');
    done.textContent = T('선택 완료');
    done.disabled = !(S.temp && S.temp.size) && !S.tempLocal.length && !S.had;
    body.innerHTML = SECS.map(secHtml).join('');
    body.scrollTop = keep.top;
    body.querySelectorAll('[data-rs-list]').forEach(function (el) { var v = keep.lists[el.getAttribute('data-rs-list')]; if (v) el.scrollTop = v; });
    if (focusKey) {
      var f = ov.querySelector('[data-rs-focus="' + cssq(focusKey) + '"]');
      if (f) { try { f.focus({ preventScroll: true }); } catch (e) { f.focus(); } }
    }
  }

  /* ── 동작 / interactions ── */
  function toggleKey(key) {
    var it = S.index[key];
    if (!it) return;
    if (isOn(it.node)) {
      subtreeKeys(it.node).forEach(function (k) { S.temp.delete(k); });
      it.path.forEach(function (a) { S.temp.delete(a.key); });   // 조상 키가 남으면 하위가 범위에 남는다 / a surviving ancestor keeps the subtree in scope
    } else {
      subtreeKeys(it.node).forEach(function (k) { S.temp.add(k); });
    }
  }
  function toggleSection(sk) {
    if (sk === 'klocal') {
      var ids = localList().map(function (a) { return a.id; });
      var all = ids.length > 0 && ids.every(function (id) { return S.tempLocal.indexOf(id) >= 0; });
      setLocal(all ? [] : ids);
      return;
    }
    var keys = [];
    secNodes(sk).forEach(function (n) { keys = keys.concat(subtreeKeys(n)); });
    if (secState(sk).all) keys.forEach(function (k) { S.temp.delete(k); });
    else keys.forEach(function (k) { S.temp.add(k); });
  }
  // 로컬을 고르면 나머지 구획의 선택을 지운다(Dev: isLocalSelected 효과) / choosing local clears the other sections (Dev's isLocalSelected effect)
  function setLocal(ids) {
    var order = localList().map(function (a) { return a.id; });
    S.tempLocal = order.filter(function (id) { return ids.indexOf(id) >= 0; });
    if (S.tempLocal.length) S.temp.clear();
  }
  function toggleLocal(id) {
    var cur = S.tempLocal.slice(), i = cur.indexOf(id);
    if (i >= 0) cur.splice(i, 1); else cur.push(id);
    setLocal(cur);
  }
  function onChange(e) {
    var t = e.target;
    if (!t || !t.getAttribute || !S.open) return;
    var v;
    if ((v = t.getAttribute('data-rs-check')) !== null) { if (!S.tempLocal.length) toggleKey(v); }
    else if ((v = t.getAttribute('data-rs-secall')) !== null) {
      if (v === 'klocal' ? (S.schedule || !S.knowAllowed) : S.tempLocal.length) { paint(); return; }
      toggleSection(v);
    }
    else if ((v = t.getAttribute('data-rs-local')) !== null) { if (!S.schedule) toggleLocal(v); }
    else return;
    paint();
  }
  function onClick(e) {
    var ov = document.getElementById('ai365RsOv');
    if (e.target === ov) { if (S.downOnOv) closeModal(); S.downOnOv = false; return; }
    S.downOnOv = false;
    var t = e.target && e.target.closest ? e.target : null;
    if (!t) return;
    var el;
    if ((el = t.closest('[data-rs-close]')) || (el = t.closest('[data-rs-cancel]'))) { closeModal(); return; }
    if ((el = t.closest('[data-rs-done]'))) { if (!el.disabled) apply(); return; }
    if ((el = t.closest('[data-rs-toggle]'))) {
      var sk = el.getAttribute('data-rs-toggle');
      S.secOpen[sk] = !S.secOpen[sk];
      if (S.secOpen[sk] && sk === 'klocal') loadAgents(false);
      paint();
      return;
    }
    if ((el = t.closest('[data-rs-caret]'))) {
      e.preventDefault();   // 라벨 안에 있지 않지만 혹시 모를 체크 전환을 막는다 / never toggles a checkbox
      var k = el.getAttribute('data-rs-caret');
      if (k.indexOf('la:') === 0) S.nodeOpen[k] = (S.nodeOpen[k] === false);   // 뿌리 = 기본 펼침 / roots default open
      else S.nodeOpen[k] = !S.nodeOpen[k];
      paint();
    }
  }

  // 칩 클릭은 캡처 단계에서 가로챈다(목업의 #agentMenu · 홈 칩 메뉴 · 예약 페이지 위임을 모두 건너뛴다)
  // Chip clicks are taken in the capture phase (skipping the mockup's #agentMenu, the home chip menu and the schedules-page delegation)
  window.addEventListener('click', function (e) {
    var pill = e.target && e.target.closest ? e.target.closest('[data-agentpill]') : null;
    if (!pill) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    closeOtherPopovers();
    dismissCoach();
    openModal(pill);
  }, true);
  // 위에서 클릭을 멈추면 문서 수준 "바깥 클릭" 닫기(+ 첨부 메뉴 #cmpAttMenu · 모델 · 프로필 메뉴 등)도 돌지 않아, 열린 팝오버가 대화 상자 뒤에
  // 남았다(2026-10-28 검토 반영). 대화 상자를 열기 직전에 body 대상 합성 click 을 한 번 보내 그 닫기들만 태운다. 문서 click 리스너는 모두
  // 대상 요소(closest)로 동작하거나 바깥 클릭을 닫기라, body 대상 click 은 실제 칩 클릭이 일으켰을 바깥 닫기만 일으킨다(칩 고유 동작은 없다).
  // Stopping the click above also skipped the document-level "outside click" closers (the + attach menu #cmpAttMenu, the model and
  // profile menus, ...), leaving an open popover behind the dialog (2026-10-28 review). Right before the dialog opens one synthetic
  // click on body runs just those closers: every document click listener acts on its own target (closest) or closes on outside
  // clicks, so a body-targeted click causes only the outside-closing the real chip click would have (no chip-specific action).
  var closingPopovers = false;
  function closeOtherPopovers() {
    if (closingPopovers || !document.body) return;
    closingPopovers = true;
    try { document.body.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window })); }
    catch (e) { /* 닫지 못한 팝오버는 그대로 / a popover that did not close stays */ }
    finally { closingPopovers = false; }
  }
  // 포커스 가두기(2026-10-28 검토 반영, aria-modal): Tab · Shift+Tab 이 대화 상자 안에서 돈다. 잠긴 구획(inert) · 비활성 · 숨은 요소는 건너뛴다.
  // A focus trap (2026-10-28 review, aria-modal): Tab and Shift+Tab cycle inside the dialog, skipping locked (inert), disabled and hidden elements.
  var FOCUSABLE = 'button, input, select, textarea, a[href], [tabindex]:not([tabindex="-1"])';
  function focusables(root) {
    return Array.prototype.filter.call(root.querySelectorAll(FOCUSABLE), function (el) {
      if (el.disabled || el.tabIndex < 0 || (el.closest && el.closest('[inert],[hidden]'))) return false;
      return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    });
  }
  function trapTab(e) {
    var ov = document.getElementById('ai365RsOv'), card = ov && ov.querySelector('.ai365-rs-card');
    if (!card) return;
    var items = focusables(card), act = document.activeElement;
    if (!items.length) { e.preventDefault(); try { card.focus({ preventScroll: true }); } catch (x) { card.focus(); } return; }
    var first = items[0], last = items[items.length - 1], inside = card.contains(act) && act !== card;
    var to = e.shiftKey ? ((!inside || act === first) ? last : null) : ((!inside || act === last) ? first : null);
    if (!to) return;   // 가운데는 브라우저 순서 그대로 / in between, the browser's order
    e.preventDefault();
    try { to.focus({ preventScroll: false }); } catch (x) { to.focus(); }
  }
  window.addEventListener('keydown', function (e) {
    if (!S.open) return;
    if (e.key === 'Tab' && !e.altKey && !e.ctrlKey && !e.metaKey) { trapTab(e); return; }
    if (e.key !== 'Escape') return;
    e.preventDefault();
    e.stopImmediatePropagation();   // 뒤의 예약 창 · 다른 Esc 처리가 같이 닫히지 않게 / keep the schedule dialog and other Esc handlers from closing too
    closeModal();
  }, true);
  // 언어 전환 = 열린 대화 상자 · 코치 툴팁 다시 그리기 / a language switch repaints the open dialog and the coach tooltip
  document.addEventListener('click', function (e) {
    var path = (e && typeof e.composedPath === 'function') ? e.composedPath() : [];
    var hit = path.some(function (n) { return n && n.id === 'ai365-lang-toggle'; }) || !!(e.target && e.target.closest && e.target.closest('#ai365-lang-toggle'));
    if (!hit) return;
    setTimeout(function () { if (S.open) paint(); coachSync(); }, 0);
  });

  /* ── 홈 코치 툴팁(계약 결정 2) / the home coach tooltip (contract decision 2) ── */
  // 홈 입력 카드 · 사내 · 선택 0개일 때 칩 아래 가운데. 칩을 한 번 누르면 숨기고 기억한다(localStorage, 막혀도 이 탭에서는 기억).
  // Under the home chip, centred, while the home composer is Internal with nothing chosen. One chip click hides it for good
  // (localStorage; remembered in this tab even when storage is blocked).
  var coachMem = false, coachRaf = 0;
  function coachDone() {
    if (coachMem) return true;
    try { return localStorage.getItem(COACH_KEY) === '1'; } catch (e) { return false; }
  }
  function dismissCoach() {
    if (!coachMem) {
      coachMem = true;
      try { localStorage.setItem(COACH_KEY, '1'); } catch (e) { /* 저장 막힘 = 이 탭에서만 / storage blocked: this tab only */ }
    }
    coachSync();
  }
  function coachEl() {
    var el = document.getElementById('ai365RsCoach');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'ai365RsCoach';
    el.className = 'ai365-rs-coach';
    el.setAttribute('role', 'tooltip');
    el.setAttribute('data-i18n-skip', '');
    document.body.appendChild(el);
    return el;
  }
  function coachTarget() {
    if (S.open || coachDone()) return null;
    var home = document.getElementById('viewHome');
    if (!home || !home.classList.contains('active')) return null;
    var pill = document.getElementById('homeAgentPill');
    if (!pill || pill.style.display === 'none' || !pill.offsetParent) return null;
    try { if ((O.agents() || []).length || (O.files() || []).length || liveLocal().length) return null; } catch (e) { return null; }
    return pill;
  }
  function coachPaint() {
    coachRaf = 0;
    var pill = coachTarget(), el = coachEl();
    if (!pill) {
      el.classList.remove('show');
      var hp = document.getElementById('homeAgentPill');
      if (hp && hp.getAttribute('aria-describedby') === 'ai365RsCoach') hp.removeAttribute('aria-describedby');
      return;
    }
    var r = pill.getBoundingClientRect();
    el.textContent = T('리소스를 세부적으로 선택해보세요');
    el.style.left = Math.round(r.left + r.width / 2) + 'px';
    el.style.top = Math.round(r.bottom + 11) + 'px';   // 꼬리 5 + 간격 6 / tail 5 + offset 6
    el.classList.add('show');
    pill.setAttribute('aria-describedby', 'ai365RsCoach');
  }
  function coachSync() {
    if (coachRaf) return;
    coachRaf = (window.requestAnimationFrame || function (f) { return setTimeout(f, 16); })(coachPaint);
  }
  (function coachWatch() {
    if (!window.MutationObserver) return;
    var hp = document.getElementById('homeAgentPill'), vh = document.getElementById('viewHome');
    if (hp) new MutationObserver(coachSync).observe(hp, { attributes: true, attributeFilter: ['style', 'class', 'data-agents'] });
    if (vh) new MutationObserver(coachSync).observe(vh, { attributes: true, attributeFilter: ['class'] });
    window.addEventListener('resize', coachSync);
    window.addEventListener('scroll', coachSync, true);
    coachSync();
  })();

  /* ── 칩 라벨 언어(2026-10-28) / the chip label language ── */
  // [data-agentpill] 은 adapter 번역 워커가 건너뛰고(목업 syncUI 가 첫 글자 노드를 다시 쓰므로) 목업 라벨은 한국어뿐이라, 영어 화면에서도 칩이
  // "리소스 센터"로 남았다. syncUI 뒤(data-agents 변화) · 칩이 새로 생길 때 · 언어 전환 때 지금 언어 라벨로 칠한다(한국어는 computeLabel 과 같은 글).
  // [data-agentpill] is skipped by the adapter's translation walker (the mockup's syncUI rewrites the first text node) and the mockup's
  // labels are Korean only, so the chip stayed "리소스 센터" on English screens. After syncUI (data-agents changes), when a chip
  // appears and on a language switch, the chip is painted in the current language (Korean = the same text as computeLabel).
  var chipRaf = 0;
  function chipLabel() {
    var t = CHIP[isEn() ? 'en' : 'ko'], a = [];
    try { a = O.agents() || []; } catch (e) { a = []; }
    var names = ORDER.filter(function (k) { return a.indexOf(k) >= 0; }).map(function (k) { return t[k]; });
    if (!names.length) return t.none;
    return names.slice(0, 2).join(', ') + (names.length > 2 ? ' +' + (names.length - 2) : '');
  }
  function chipPaint() {
    chipRaf = 0;
    var want = chipLabel() + ' ';
    document.querySelectorAll('[data-agentpill]').forEach(function (p) {
      var n = p.firstChild;
      if (n && n.nodeType === 3 && n.textContent !== want) n.textContent = want;
    });
  }
  function chipSync() {
    if (chipRaf) return;
    chipRaf = (window.requestAnimationFrame || function (f) { return setTimeout(f, 16); })(chipPaint);
  }
  // 새 칩 찾기(2026-10-28 검토 반영, 성능): 스트리밍 중에는 답변 노드가 계속 붙어 노드마다 querySelector 를 부르던 비용이 컸다. 관찰자는
  // 붙은 요소만 모으고, 다음 프레임에 한 번 그때도 문서에 붙어 있는 것만 검사한다(같은 프레임에 붙었다 떨어진 노드는 건너뛴다). 한 프레임에
  // CHIP_PEND_MAX 개를 넘으면 모으기를 멈추고 칩 칠하기를 한 번 한다(숨은 탭에서 떨어진 노드를 오래 붙잡지 않게). 칠하는 결과는 종전과 같다.
  // Finding new chips (2026-10-28 review, performance): while streaming, answer nodes keep arriving and the per-node querySelector
  // was costly. The observer only collects added elements; on the next frame, those still attached are checked once (nodes added
  // and removed within the frame are skipped). Past CHIP_PEND_MAX in a frame, collecting stops and the chips are painted once
  // (so a hidden tab never holds detached nodes for long). The painted result is the same as before.
  var CHIP_PEND_MAX = 200, chipPend = [], chipOver = false, chipScanRaf = 0;
  function chipScan() {
    chipScanRaf = 0;
    var list = chipPend, over = chipOver;
    chipPend = []; chipOver = false;
    if (over) { chipPaint(); return; }
    for (var i = 0; i < list.length; i++) {
      var n = list[i];
      if (n.isConnected && (n.hasAttribute('data-agentpill') || (n.querySelector && n.querySelector('[data-agentpill]')))) { chipPaint(); return; }
    }
  }
  (function chipWatch() {
    if (window.MutationObserver && document.body) {
      new MutationObserver(function (recs) {
        for (var i = 0; i < recs.length; i++) {
          var r = recs[i];
          if (r.type === 'attributes') { chipSync(); chipPend = []; chipOver = false; return; }   // 칠하기가 곧 온다 / a paint is coming
          if (chipOver) continue;
          for (var j = 0; j < r.addedNodes.length; j++) {
            var n = r.addedNodes[j];
            if (n.nodeType !== 1) continue;
            if (chipPend.length >= CHIP_PEND_MAX) { chipOver = true; chipPend = []; break; }
            chipPend.push(n);
          }
        }
        if ((chipPend.length || chipOver) && !chipScanRaf) chipScanRaf = (window.requestAnimationFrame || function (f) { return setTimeout(f, 16); })(chipScan);
      }).observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['data-agents'] });
    }
    document.addEventListener('click', function (e) {
      var path = (e && typeof e.composedPath === 'function') ? e.composedPath() : [];
      if (path.some(function (n) { return n && n.id === 'ai365-lang-toggle'; })) setTimeout(chipSync, 0);
    });
    chipSync();
  })();

  /* ── 바깥 노출(테스트 · 점검용) / exposed for tests and inspection ── */
  window.AI365_RS = {
    open: function (anchor) { openModal(anchor || null); },
    close: closeModal,
    isOpen: function () { return S.open; },
    local: function () { return liveLocal(); },
    coach: coachSync
  };
})();
