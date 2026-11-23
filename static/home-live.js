/* /home(Groupware Agent 홈) 라이브 스크립트 — GET /home 응답 시점에만 주입(원본·스냅숏 무수정 관례,
   edu-sync.js·email-live.js 선례). 역할 두 가지:
   ① EN 번역 — 부모 앱의 KO/EN 토글(localStorage 'ai365_lang', 동일 출처라 iframe과 공유)을 읽어
      위젯 문자열을 사전 기반으로 번역. storage 이벤트로 부모 토글에 실시간 반응, MutationObserver로
      동적 재렌더에도 재적용(무변경 대입은 건너뛰어 피드백 루프 방지 — adapter.js 워커와 동일 규칙).
   ② Teams 액션 제거(2026-08-28) — Graph Teams API가 MFA를 요구해 실연동 불가. @teams 액션 버튼을
      제거한다(Teams '회의'는 캘린더 일정+딥링크라 유지). */
/* Live script for /home (Groupware Agent) — injected only at response time (originals untouched;
   same convention as edu-sync.js / email-live.js). Two jobs:
   ① EN translation — reads the parent app's KO/EN toggle (localStorage 'ai365_lang', shared with the
      iframe via same-origin) and translates widget strings via a dictionary. Reacts live to the parent
      toggle through storage events, and re-applies on dynamic re-renders via a MutationObserver
      (no-op assignments are skipped to avoid feedback loops — same rule as the adapter walker).
   ② Teams action removal (2026-08-28) — the Graph Teams API requires MFA, so real integration is
      impossible. The @teams action button is removed (Teams *meetings* stay: calendar + deeplink). */
(function () {
  var KEY = 'ai365_lang';

  var KO2EN = {
    /* ── 2026-09-03 홈 재구성(캡처 기준) 신규 문자열 / new strings for the 2026-09-03 home rebuild ──
       exact-trim 매치라 텍스트 노드 전체가 키와 같을 때만 치환된다. "N명"처럼 숫자와 붙는 단위는
       사전으로 못 다루므로 페이지 쪽에서 숫자 span을 분리하고 '구성원'·'명' 단독 노드로 두어야 한다.
       Exact-trim matching: a text node is swapped only when its whole trimmed content equals a key.
       Units glued to numbers ("N명") cannot be handled here — the page should split the number
       into its own span so '구성원' / '명' stand alone as text nodes. */
    '그룹웨어 에이전트': 'Groupware Agent', '보안 에이전트': 'Security Agent',
    /* ── 2026-09-18 홈 전자결재 탭(데모 시드) — 문서 제목·양식·이름·부서는 데이터라 번역하지 않는다
       e-Approval tab on the home (demo seed) — titles, forms, names and departments are data and stay untranslated ── */
    '전자결재': 'e-Approval', '전자결재는 결재 요청부터 승인 현황까지 한눈에 관리하세요.': 'Manage approval requests and their status at a glance.',
    '결재 대기': 'Pending approval', '진행 중': 'In progress', '완료 문서': 'Completed documents', '반려 문서': 'Rejected documents',
    '빠른 작성': 'Quick create', '결재 목록': 'Approval list', '새 문서 작성': 'New document', '최근 작성한 양식': 'Recently used forms',
    '반려': 'Rejected', '완료': 'Completed', '문서 제목': 'Document title', '기안자': 'Drafter', '요청일': 'Requested',
    '문서가 없습니다': 'No documents', '전자결재 연동 후 이용할 수 있습니다': 'Available after the e-approval integration',
    /* ── 2026-09-18 홈 위젯 2종(그룹웨어 게시판·근태관리, 데모 시드) — 글 제목·작성자는 데이터라 번역하지 않는다. 공지사항 = Announcements
       (종전 '사내 공지' 위젯과 '오늘의 뉴스' 위젯은 2026-09-21 사용자 지시로 삭제 — 그 사전 항목도 같이 뺐다)
       two home widgets (groupware board, attendance; demo seeds) — post titles and authors are data. 공지사항 = Announcements
       (the former Notices and Today's News widgets were removed on 2026-09-21 by user request, with their dictionary entries) ── */
    '그룹웨어 게시판': 'Groupware board', '공지사항': 'Announcements', '게시글': 'Posts',
    '근태관리': 'Attendance', '연도': 'Year', '연간근태현황 바로가기': 'Open annual attendance',
    '공지사항 바로가기': 'Open announcements', '게시글 바로가기': 'Open posts',
    '발생 연차': 'Granted leave', '전년 이월': 'Carried over', '사용 일수': 'Days used', '잔여 일수': 'Days left',
    '근태관리 연동 후 이용할 수 있습니다': 'Available after the attendance integration',
    '그룹웨어 연동 후 이용할 수 있습니다': 'Available after the groupware integration',
    /* ── 2026-09-07 보안 에이전트 대시보드(상단 Groupware 탭) / Security Agent dashboard (top Groupware tab) ──
       역방향(EN→KO) 사전은 값으로 뒤집으므로 EN 값이 서로 겹치면 안 된다('삭제된 사용자'/'삭제 사용자' 등 구분).
       The EN→KO map is built by inverting values, so EN values must stay unique (e.g. '삭제된 사용자' vs '삭제 사용자'). */
    '조직의 보안 현황과 위험 요소를 한눈에 확인하세요.': "See your organization's security posture and risks at a glance.",
    '종합 상태': 'Overall status', '위험한 사용자/로그인': 'Risky users / sign-ins', '사용자 관리': 'User management',
    '인증 관리': 'Authentication', '운영 관리': 'Operations', '로그 관리': 'Log management',
    '주의': 'Caution', '확인 필요': 'Needs review', '안전': 'Safe',
    '위험한 사용자, 위험한 로그인': 'Risky users and risky sign-ins', '날짜': 'Date', '사용자': 'User', '상태': 'Status', '삭제': 'Delete',
    '새로고침': 'Refresh', '기록이 없습니다': 'No records',
    '점검 항목': 'Check item', '전역 관리자': 'Global admins', '게스트 관리자': 'Guest admins', '역할 변경된 사용자': 'Users with role changes',
    '사용자 액세스': 'User access', '암호가 만료되지 않도록 설정': 'Passwords set to never expire', '위험한 사용자': 'Risky users', '위험한 로그인': 'Risky sign-ins',
    '사용자 현황': 'Users', '그룹 현황': 'Groups', '총 사용자 수': 'Total user count', '총 그룹 수': 'Total group count', '게스트': 'Guests',
    'M365 그룹': 'M365 groups', '배포 그룹': 'Distribution groups', '보안 그룹': 'Security groups', '메일 그룹': 'Mail groups',
    'Microsoft 365 서비스 사용 개요': 'Microsoft 365 service usage', '서비스': 'Service', '활성 사용자': 'Active users', '비활성 사용자': 'Inactive users', '총 사용자': 'Total users',
    'Teams 사용 현황': 'Teams usage', '비공개 팀': 'Private teams', '활성 비공개 팀': 'Active private teams', '공개 팀': 'Public teams', '활성 공개 팀': 'Active public teams',
    'Exchange 사용 현황': 'Exchange usage', '저장소 할당량 상태별 사용자 사서함 수': 'User mailboxes by storage quota status', '사용된 저장소': 'Storage used',
    '정상(제한 미만)': 'Normal (under limit)', '경고 발생': 'Warning issued', '보내기 금지됨': 'Send prohibited', '보내기/받기 금지됨': 'Send/receive prohibited',
    '사용된 저장 용량이 가장 많은 사용자': 'Top users by storage used', '사용자 이름': 'User name', '사용된 저장 용량 (MB)': 'Usage (MB)', '할당량 상태': 'Quota status', '정상': 'Normal',
    '신규/삭제 현황': 'New / deleted', '신규 사용자': 'New users', '삭제된 사용자': 'Deleted users', '신규 그룹': 'New groups', '삭제된 그룹': 'Deleted groups',
    '만든 날짜': 'Created', '계정명': 'Account', '삭제 사용자': 'Deleted accounts', '삭제 날짜': 'Deleted on', '영구 삭제 날짜': 'Permanent deletion', '표시 이름': 'Display name',
    '전역관리자 현황': 'Global administrators',
    '주요 이슈': 'Key issues', '라이선스': 'Licenses', '저장소': 'Storage', '사용자·그룹': 'Users & groups',
    '위험 로그인 사용자 3명이 탐지되었습니다.': '3 users with risky sign-ins were detected.',
    'Microsoft_365_Copilot 은 10/10 으로 전량 할당되었고, Dynamics 365 Partner Sandbox 2종은 70% 이상 사용 중입니다.': 'Microsoft_365_Copilot is fully assigned (10/10) and both Dynamics 365 Partner Sandbox licenses are over 70% used.',
    'OneDrive 3.3TB · SharePoint 2.7TB · Exchange 1.3TB 를 사용 중이며, 사서함 19개가 보내기/받기 금지 상태입니다.': 'OneDrive 3.3TB · SharePoint 2.7TB · Exchange 1.3TB in use; 19 mailboxes are send/receive prohibited.',
    '총 사용자 304명(구성원 217·게스트 87), 그룹 216개이며 최근 신규 사용자 25명이 추가되었습니다.': '304 users in total (217 members · 87 guests) and 216 groups; 25 new users were added recently.',
    '고객사명': 'Customer', '테넌트명': 'Tenant', '엠클라우드브리지': 'MCloudBridge',
    '사용 가능한 라이선스': 'Available licenses', '할당된 라이선스': 'Assigned licenses',
    'OneDrive 사용 현황': 'OneDrive usage', 'SharePoint 사용 현황': 'SharePoint usage',
    '총 계정': 'Total accounts', '활성 계정 수': 'Active accounts', '총 파일 수': 'Total files', '활성 파일 수': 'Active files',
    '사용된 저장소가 제일 많은 OneDrive 사용자': 'Top OneDrive users by storage', '사용된 저장소가 제일 많은 SharePoint 사이트': 'Top SharePoint sites by storage',
    '소유자 계정 이름': 'Owner account', '사용된 저장소(MB)': 'Storage used (MB)', '사이트 이름': 'Site name', '사용된 저장소(GB)': 'Storage used (GB)',
    '위험 로그인 기록이 삭제되었습니다': 'Risky sign-in record deleted', '새로고침되었습니다': 'Refreshed',
    '요약 생성 중…': 'Generating summary…', '삭제에 실패했습니다': 'Delete failed', '새로고침에 실패했습니다': 'Refresh failed',
    '중요한 알림과 업무 현황을 한눈에 확인하세요.': 'Check key alerts and work status at a glance.',
    '대시보드 설정': 'Dashboard settings', '⚙ 대시보드 설정': '⚙ Dashboard settings',
    '일정': 'Schedule', '전체': 'All',
    '토큰 사용 현황': 'Token usage',
    '내가 사용한 토큰': 'Tokens I used', '팀이 사용한 토큰': 'Team tokens used',
    'AI 질문': 'Ask AI', '무엇을 도와드릴까요?': 'How can I help?',
    '바로가기': 'Shortcuts',
    '새 컬렉션 추가': 'New collection', '＋ 새 컬렉션 추가': '＋ New collection',
    '이름, 부서 검색': 'Search name, department',
    '구성원': 'Members', /* '명'은 미등록 — 단독 1글자라 오역 위험, 숫자 span 분리 후 페이지가 처리 / '명' not registered — single char, mistranslation risk; page handles it after splitting the number span */
    '이름': 'Name', '부서': 'Department', '직책': 'Title',
    '일정이 없습니다': 'No events',
    '최고': 'High', '최저': 'Low',
    /* 요일 1글자 키는 등록하지 않는다 — 페이지가 ai365_lang 을 읽어 요일·날짜를 직접 로케일 처리하며, 1글자 키는
       아바타 이니셜 같은 단독 1글자 노드를 오역한다(리뷰 지적). / Weekday single-char keys are NOT registered — the page
       localizes weekdays/dates itself, and 1-char keys would mistranslate standalone initials (review fix). */
    '서울': 'Seoul', '회의실 A': 'Room A', '컬렉션이 없습니다': 'No collections',
    '이전 해': 'Prev year', '이전 달': 'Prev month', '다음 달': 'Next month', '다음 해': 'Next year',
    '분야 선택·첨부': 'Field · attach',
    /* 달력 월 네비 / calendar month nav */
    '2026년 7월': 'July 2026', '2026년 9월': 'September 2026', '2026년 10월': 'October 2026',
    '2026년 11월': 'November 2026', '2026년 12월': 'December 2026', '2027년 1월': 'January 2027',

    /* ── 위젯 프레임 / widget frame ── */
    '오늘의 날씨·일정': "Today's Weather & Schedule",
    '오늘의 날씨': "Today's Weather",
    '2026년 8월': 'August 2026',
    '누르면 이어서 · 입력 후 엔터 → Workspace': 'Click to continue · type + Enter → Workspace',
    '사용 현황': 'Usage',
    'BI 하이라이트': 'BI Highlights',
    '새 소식': "What's New",
    '최근 대화': 'Recent Chats',
    '컬렉션': 'Collections',
    '조직도': 'Org Chart',
    '액션 모드': 'Action Mode',
    '고정': 'Pinned',
    '닫기': 'Close',
    '확인': 'OK',

    /* ── 날씨·일정 / weather & schedule ── */
    '맑음': 'Sunny', '대체로 맑음': 'Mostly sunny', '구름 조금': 'Partly cloudy', '흐림': 'Cloudy',
    '안개': 'Foggy', '이슬비': 'Drizzle', '강한 비': 'Heavy rain', '폭설': 'Heavy snow',
    '소나기': 'Showers', '강한 소나기': 'Heavy showers', '뇌우': 'Thunderstorm',
    '강수 확률': 'Precip.', '습도': 'Humidity', '최고 / 최저': 'High / Low', '위치': 'Location',
    '· 서울': '· Seoul', 'Open-Meteo 실시간': 'Open-Meteo live',
    '예시 데이터': 'Sample data', '예시 데이터 (오프라인)': 'Sample data (offline)',
    '오늘 일정': "Today's schedule", '곧 시작': 'Starting soon',
    '주간 업무 회의': 'Weekly team meeting', '경력 채용 면접': 'Interview (experienced hire)',
    '데이터 리뷰': 'Data review', '일시:': 'When:', '참석자:': 'Attendees:',
    'Teams 회의로 진행합니다.': 'Held as a Teams meeting.',

    /* ── 사용 현황 / usage ── */
    '내가 쓴 크레딧': 'My credits',
    '부서(인사총무)가 쓴 크레딧': 'Dept (HR & GA) credits',
    '한도는 관리 센터 › 토큰 설정 기준 · 예시 데이터': 'Limits per Admin Center › Token Settings · sample data',
    '3건': '3 items',

    /* ── 새 소식 / alerts ── */
    '내 권한 범위 기준': 'Within my access scope',
    '영업 그룹': 'Sales Group', '재무 그룹': 'Finance Group',
    '품질 그룹': 'Quality Group', 'SCM 그룹': 'SCM Group',
    '2시간 전': '2h ago', '어제': 'Yesterday', '1일 전': '1d ago', '3일 전': '3d ago',
    '5일 전': '5d ago', '1주 전': '1w ago',

    /* ── 최근 대화·컴포저 / recent chats & composer ── */
    '스레드 14 · 6시간 전': 'Thread 14 · 6h ago',
    '스레드 1 · 3개월 전': 'Thread 1 · 3mo ago',
    '스레드 2 · 2개월 전': 'Thread 2 · 2mo ago',
    '연차 휴가 일수 확인': 'Check annual-leave balance',
    '월별 POS 매출 분석': 'Monthly POS sales analysis',
    '경영진 보고서 작성': 'Executive report drafting',
    '대화로 이동했습니다.': 'Moved to the chat.',
    '무엇이든 물어보세요 — 엔터를 누르면 Workspace 채팅으로 이어집니다': 'Ask anything — Enter continues in Workspace chat',
    '질문으로 새 채팅이 시작됩니다.': 'A new chat starts with your question.',
    '음성 입력은 예시입니다': 'Voice input is a sample',
    '파일 첨부': 'Attach files',
    '파일 첨부는 예시입니다 — 실서비스에서 연결됩니다': 'Attachments are sample-only — wired in production',
    '자동': 'Auto', '사내': 'Internal', '외부': 'External',
    '사내 자료 우선, 부족하면 웹 보완': 'Internal first, web fills gaps',
    '사내 자료만 사용': 'Internal materials only',
    '웹 검색만 사용': 'Web search only',
    '새 채팅': 'New chat', '잠시만요…': 'One moment…', '불러오는 중…': 'Loading…',
    '✦ AI 요약': '✦ AI Summary',

    /* ── 컬렉션 / collections ── */
    '채팅·지침·파일 묶음': 'Chats · instructions · files',
    '＋ 새 컬렉션 만들기': '＋ New collection', '컬렉션 추가': 'Add collection',
    '뉴스레터': 'Newsletter', '보도 자료': 'Press releases',
    '📁 뉴스레터': '📁 Newsletter', '📁 보도 자료': '📁 Press releases',
    '실서비스에서는 컬렉션 생성 창이 열립니다 (예시)': 'In production this opens the collection creator (sample)',
    '실서비스에서는 해당 채팅이 이어서 열립니다.': 'In production the chat continues from here.',

    /* ── BI / dashboards ── */
    'Power BI 대시보드 · 내가 볼 수 있는 항목': 'Power BI dashboards · visible to me',
    '분기 판매 실적': 'Quarterly sales', '월별 매출 추이': 'Monthly revenue trend',
    '재고·물류 현황': 'Inventory & logistics', '인사·근태 현황': 'HR & attendance',
    '품질 지표 대시보드': 'Quality metrics dashboard', '거래처 판매 TOP 10': 'Top 10 partner sales',
    '표시할 Power BI 선택': 'Choose Power BI to show',
    '표시할 Power BI · 여러 개 선택': 'Power BI to show · multi-select',
    '표시할 Power BI가 없습니다 — 우측 ⚙ 에서 볼 대시보드를 선택하세요.': 'Nothing selected — pick dashboards via ⚙ on the right.',

    /* ── 조직도 / org chart ── */
    '전체 42명 · 조회 전용': 'All 42 · read-only',
    '이름 검색': 'Search names', '검색 결과가 없습니다': 'No results',
    '경영지원본부': 'Mgmt Support Div', 'AI365 개발본부': 'AI365 Dev Div',
    '인사총무': 'HR & GA', '재무회계파트': 'Finance & Accounting', '영업관리파트': 'Sales Ops',
    '기술운영파트': 'Tech Ops', 'PMO파트': 'PMO', 'AI 파트': 'AI', 'AI Agent 파트': 'AI Agent',
    'Front-End 파트': 'Front-End',
    '대표이사': 'CEO', '대표': 'CEO', '부장': 'Director', '차장': 'Deputy Director',
    '과장': 'Manager', '대리': 'Asst. Manager', '사원': 'Staff', '수석': 'Principal',
    '책임': 'Sr. Manager', '선임': 'Senior', '파트장': 'Part Lead',

    /* ── 액션 모드 위젯·모달 / action-mode widget & modal ── */
    '@ 도구 호출 · Microsoft 365': '@ tool calls · Microsoft 365',
    'Outlook 메일': 'Outlook Mail', 'Outlook 일정': 'Outlook Calendar',
    '버튼 → 최근 대화 채팅창에 @ 입력 → 엔터 → Workspace 대화로 실행': 'Button → @ token in the chat box → Enter → runs in Workspace',
    '실행 확인': 'Run confirmation', '실행 결과': 'Result',
    '실행할 액션을 선택하세요': 'Choose an action to run',
    '정말 실행하시겠습니까?': 'Run this action?',
    '실행': 'Run', '실행 완료': 'Executed', '✕ 실행 실패': '✕ Failed',
    '← 이전': '← Back', '← 수정하기': '← Edit',
    '(선택)': '(optional)', '선택하세요': 'Select',
    '신규 이메일 발송': 'Send new email', '받는 사람 이메일': 'Recipient email',
    '받는 사람': 'Recipient', '이메일 주소, 쉼표 구분': 'Email addresses, comma-separated',
    '이메일 주소 형식으로 다시 시도해 주세요': 'Please retry with a valid email address',
    '제목': 'Subject', '내용': 'Body',
    '일정 생성': 'Create event', '일정 제목': 'Event title', '날짜·시간': 'Date & time',
    '예: 8/7(금) 14:00~15:00': 'e.g. Fri 8/7 14:00–15:00',
    'Teams 회의 만들기': 'Create Teams meeting', '회의 제목': 'Meeting title', '참석자': 'Attendees',
    'SharePoint 폴더 만들기': 'Create SharePoint folder', '폴더 이름': 'Folder name',
    '선택 — 기본: 내 문서': 'Optional — default: My Documents',
    '새 할 일 생성': 'Create to-do', '할 일 제목': 'To-do title', '담당자 배정': 'Assign to',
    '할 일 완료 처리': 'Complete a to-do', '대상 할 일': 'Target to-do',
    '메일에서 할 일 생성': 'To-do from email', '대상 메일': 'Target email',
    '이름 입력 — 아래 목록에서 선택, 쉼표로 여러 명': 'Type names — pick from the list, comma-separate several',
    '선택 — 이름 입력 후 목록에서 선택': 'Optional — type a name, pick from the list',
    'Outlook으로 연결되었습니다': 'Connected to Outlook',
    '입력 내용이 채워진 상태로 열립니다 — 확인 후 보내기/저장을 눌러 주세요 (자동 서명은 계정 설정에 따라 포함)': 'Opens prefilled — review, then send/save (auto signature per account settings)',
    '예시 실행입니다 — 실서비스에서는 Microsoft 365로 전송됩니다': 'Sample run — production sends to Microsoft 365',
    '실서비스에서는 Teams 회의가 열립니다 (예시)': 'In production this opens a Teams meeting (sample)',

    /* ── 메일·할 일 시드 / mail & to-do seeds ── */
    '[요청] 3분기 실적 자료 공유': '[Request] Q3 results deck',
    '[파트너] 계약 갱신 일정 문의': '[Partner] Contract renewal scheduling',
    '휴가 신청 승인 요청': 'Leave request approval',
    '월간 경영 보고서 초안 검토 요청': 'Monthly management report draft review',
    '지난 주간회의에서 말씀 주신 3분기 실적 자료 공유 부탁드립니다. 가능하시면 금주 내로 받아볼 수 있을까요?': 'Please share the Q3 results deck mentioned in last weekly meeting — ideally within this week.',
    '8/11(월)~8/13(수) 연차 사용을 신청드립니다. 업무 인수인계는 조예준 님과 완료했습니다. 승인 부탁드립니다.': 'Requesting annual leave 8/11 (Mon)–8/13 (Wed). Handover completed with Yejun Cho. Please approve.',
    '월간 경영 보고서 초안을 공유드립니다. 재무 파트 수치 위주로 검토 의견 주시면 반영하겠습니다.': 'Sharing the monthly management report draft. Comments on the finance figures welcome.',
    '안녕하세요, 파트너코프 박태호입니다. 계약 갱신 관련 미팅 일정을 다음 주 중으로 잡을 수 있을지 문의드립니다.': 'Hello, Taeho Park from PartnerCorp. Could we schedule a contract-renewal meeting next week?',
    '주간보고 초안 작성': 'Draft weekly report', '채용 공고 검토': 'Review job posting',
    '거래처 계약서 회신': 'Reply to partner contract',

    /* ── 2026-10-28 /home Dev 원본 정렬: Dev 문구(resource/language/ko.json groupware · securityAgent, home/eApproval/language/ko.json)로 바뀐 라벨.
       EN 값은 Dev en.json 기준이고 기존 값과 겹치지 않는다(EN→KO 역사전). 아래 "옛 키"는 페이지가 더 쓰지 않으니 이 줄로 바꿔도 된다.
       /home Dev original alignment (2026-10-28): labels now in the Dev wording; EN values follow Dev en.json and stay unique
       (the EN→KO map is inverted). The "old keys" below are no longer used by the page and can be replaced by these lines. ── */
    '토큰 사용량': 'Token Usage', '내 토큰 사용량': 'My Tokens Used', '팀 토큰 사용량': 'Team Tokens Used',
    '전체 일정': 'All Schedules', '이 날의 일정이 없습니다.': 'No schedule for this day.',
    '이름 또는 부서로 검색': 'Search by name or department', '직위': 'Position', '컬렉션이 없습니다.': 'No collections found.',
    '결재할 문서': 'Documents to Approve', '진행중 문서': 'In Progress', '문서명': 'Document Title',
    '결재 문서가 없습니다.': 'There are no approval documents.', '새 문서 작성 버튼을 통해 결재를 시작해 보세요.': 'Click New document to start an approval.',
    '위험 사용자, 위험 로그인': 'Risky Users, Risky Sign-ins', '전체 현황': 'Overall Status', '위험 사용자/로그인': 'Risky Users/Sign-ins',
    '검토 필요': 'Review Needed', '문제 없음': 'No Issue',
    '사용자 개요': 'User Overview', '전체 사용자': 'Total Users', '그룹 개요': 'Group Overview', '전체 그룹': 'Total Groups',
    '신규/삭제 개요': 'New/Deleted Overview', '생성일': 'Created Date', '계정 이름': 'Account Name', '제거된 사용자': 'Removed Users',
    '삭제일': 'Deleted Date', '영구 삭제일': 'Permanent Deletion Date',
    'Microsoft 365 서비스 사용 현황': 'Microsoft 365 Service Usage Overview',
    '저장소 할당량 상태별 사용자 사서함': 'User Mailboxes by Storage Quota Status', '사용 중인 저장소': 'Used Storage',
    '정상 (한도 이내)': 'Normal (Under Limit)', '보내기 금지': 'Send Prohibited', '보내기/받기 금지': 'Send/Receive Prohibited',
    '저장소 사용량 상위 사용자': 'Top Users by Storage Used', '저장소 사용량 (MB)': 'Storage Used (MB)', '저장소 사용량 (GB)': 'Storage Used (GB)',
    '고객 이름': 'Customer Name', '테넌트 이름': 'Tenant Name',
    '전체 계정': 'Total Accounts', '활성 계정': 'Active Accounts', '전체 파일': 'Total Files', '활성 파일': 'Active Files',
    '저장소 사용량 상위 OneDrive 사용자': 'Top OneDrive Users by Storage Used', '저장소 사용량 상위 SharePoint 사이트': 'Top SharePoint Sites by Storage Used',

    /* ── 홈 대시보드(static/home_dash.js): 2026-11-13 만든 위젯 · 2026-11-17 4단계 배치 편집(격자 · 끌어 옮기기 · 크기 · 기본 비율 · 위젯 추가 서랍).
       EN 값은 기존 값과 겹치지 않는다(EN→KO 역사전). 끄는 동안의 칸 수 안내("놓으면 가로 2 × 세로 1")는 home_dash.js 가 직접 짓는다.
       종전 대시보드 설정 화면(세 열 · 미사용 메뉴)의 항목은 4단계에서 뺐고, 옛 편집 모드(▲▼✕ · 숨긴 위젯 트레이)의 항목은 아래에 남겨 둔다
       (바탕화면에 옛 홈 파일이 다시 놓이면 그 화면이 쓴다 — 새 홈 파일은 쓰지 않는다).
       The home dashboard (static/home_dash.js): made widgets (2026-11-13) and phase-4 layout editing (2026-11-17: grid, drag to move,
       resize, base ratio, the Add widget drawer). EN values stay unique (the EN→KO map is inverted); drag notices with cell counts are
       composed by home_dash.js. The former settings page's entries went with phase 4; the older edit mode's entries stay below. ── */
    '배치 편집': 'Edit layout', '위젯을 끌어 옮기고, 오른쪽 아래 모서리로 크기를 바꾸세요.': 'Drag widgets to move them and resize them from the bottom-right corner.',
    '기본 비율': 'Base ratio', '위젯 추가': 'Add widget', '넣기': 'Place', '모든 위젯이 홈에 있습니다': 'Every widget is on Home',
    '홈에서 빼기': 'Remove from Home', '크기 조절': 'Resize',
    '취소': 'Cancel', '저장': 'Save', '왼쪽 좁게': 'Narrow Left', '가운데 넓게': 'Wide Center',
    '배치 편집을 취소하시겠습니까?': 'Cancel layout editing?', '저장하지 않으면 변경 사항이 적용되지 않습니다.': 'Changes will not be applied unless saved.',
    '배치를 저장하시겠습니까?': 'Save this layout?', '배치를 저장했습니다': 'Layout saved', '배치를 저장하지 못했습니다': 'Could not save the layout',
    '배치를 불러오지 못했습니다': 'Could not load the layout', '배치 편집은 넓은 화면에서 할 수 있습니다': 'Layout editing needs a wider screen',
    '위젯 삭제': 'Delete widget', '위젯을 삭제하시겠습니까?': 'Delete this widget?', '삭제한 위젯은 되돌릴 수 없습니다.': 'A deleted widget cannot be restored.',
    '위젯을 삭제했습니다': 'Widget deleted', '위젯을 삭제하지 못했습니다': 'Could not delete the widget', '표시할 데이터가 없습니다': 'No data to show',
    '사용자가 바뀌어 대시보드를 다시 불러왔습니다': 'The user changed, so the dashboard was reloaded',
    /* 옛 편집 모드(표식 없는 옛 홈 파일 전용) / the former edit mode (an older home file without the marker only) */
    '위젯 편집': 'Edit widgets', '편집 완료': 'Done', '숨기기': 'Hide', '숨긴 위젯:': 'Hidden widgets:', '위로': 'Up', '아래로': 'Down',
    '위젯 배치가 저장되었습니다': 'Widget layout saved', '＋ 그룹웨어 게시판': '＋ Groupware board', '＋ 근태관리': '＋ Attendance',

    /* ── 2026-11-16 위젯 에이전트 화면(static/widget_agent.js) · 만든 위젯 v2(static/home_dash.js). EN 값은 기존 값과 겹치지 않는다(EN→KO 역사전).
       일반 낱말(데이터 · 리포트 · 필터 · 도구 · 열기 …)은 넣지 않는다 — 홈의 사용자 데이터까지 바뀌므로 위젯 에이전트 화면 안에서 번역한다.
       The widget agent screen (static/widget_agent.js) and made widgets v2 (static/home_dash.js), 2026-11-16; EN values stay unique (the EN→KO map is
       inverted). Generic words (data, report, filters, tools, open …) stay out, as they would rewrite user data on the home; the screen translates them. ── */
    '위젯 에이전트': 'Widget Agent',
    /* 2026-11-17 대화창 새 구성: 예시 카드 설명 / the rebuilt chat's starter captions */
    'KPI 카드 · 연결할 데이터를 되물어요': 'KPI cards · asks which data to connect', '웹 검색 · 실시간 환율': 'Web search · live exchange rate',
    '사내 데이터 · 막대 차트': 'Company data · bar chart', '사내 문서 · 요약 글': 'Company documents · summary text',
    '내 위젯': 'My widgets',
    '새 위젯': 'New widget',
    '되돌리기': 'Undo',
    '이름 바꾸기': 'Rename',
    '무엇을 만들까요?': 'What shall we build?',
    '대화로 위젯을 만들고 고치면 홈에 바로 반영됩니다. 예를 눌러 시작해 보세요.': 'Build and refine widgets by conversation; Home updates at once. Pick an example to start.',
    /* 2026-11-20 패널: 만든 위젯 머리의 아이콘(static/home_dash.js) / the panel: the icon on a made widget's head */
    '위젯 에이전트로 고치기': 'Edit with the Widget Agent',
    'KPI 카드 위젯을 만들어줘': 'Make a KPI card widget',
    '오늘 원달러 환율 위젯을 만들어줘': 'Make a widget with today\'s won-dollar rate',
    '지점별 매출 차트 위젯을 만들어줘': 'Make a sales-by-branch chart widget',
    '연차 규정 요약 위젯을 만들어줘': 'Make a widget summarizing the annual leave rules',
    '위젯 에이전트가 작업 중…': 'The widget agent is working…',
    '도구 트리': 'Tool tree',
    '위젯 에이전트의 도구': 'The widget agent\'s tools',
    '항목을 누르면 요청 문장이 입력창에 채워집니다.': 'Pick an item to fill a request into the input.',
    '보내기': 'Send',
    '위젯에 바라는 점을 적어 주세요. / 를 누르면 도구 트리가 열립니다.': 'Tell the agent what the widget should show. Type / for the tool tree.',
    '연결할 데이터나 숫자를 알려 주세요.': 'Tell me which data or number to use.',
    '어떤 데이터를 연결할까요?': 'Which data should I connect?',
    '무엇의 숫자인지 말씀해 주시면 사내 데이터 · 사내 문서 · 웹에서 찾아 넣습니다. 숫자를 직접 알려 주셔도 됩니다.': 'Tell me what the number is for and I will find it in company data, company documents or on the web. You can also give the number yourself.',
    '말씀해 주시면 사내 데이터 · 사내 문서 · 웹에서 찾아 넣습니다.': 'Tell me and I will find it in company data, company documents or on the web.',
    /* 3단계: 데이터 가져오기 — 찾는 곳 이름 · 작업 줄 · 출처 줄(static/home_dash.js · static/widget_agent.js) / phase 3: fetching — place names, the busy line, the origin line */
    '데이터 가져오기': 'Fetch data',
    '찾는 중': 'Searching',
    '사내에서 찾지 못해 웹에서 찾는 중…': 'Nothing found in the company, so searching the web…',
    '사내 데이터': 'Company data',
    '사내 문서': 'Company documents',
    '웹 검색': 'Web search',
    '데이터 연결 전': 'Not connected',
    '차트를 불러오지 못했습니다': 'Could not load the chart',
    '아직 만든 위젯이 없습니다': 'No widgets made yet',
    '내 위젯을 불러오지 못했습니다': 'Could not load my widgets',
    '위젯을 저장하지 못했습니다': 'Could not save the widget',
    '되돌렸습니다': 'Undone',
    '위젯 에이전트가 응답하지 않습니다. 잠시 뒤 다시 시도해 주세요': 'The widget agent is not answering. Please try again shortly',
    '홈에 반영하지 못한 변경이 있습니다.': 'Some changes could not be applied to Home.',
    '반영하지 않고 새 위젯을 시작할까요?': 'Start a new widget without applying them?',
    '반영하지 않고 다른 위젯을 열까요?': 'Open another widget without applying them?',
    '새로 시작': 'Start new',
    '사용자가 바뀌어 위젯 에이전트를 처음 상태로 돌렸습니다': 'The user changed, so the widget agent was reset',
    '차트 수정': 'Edit chart',
    '디자인 변경': 'Change design',
    '테마 설정': 'Set theme',
    '기준선 추가': 'Add reference line',
    '기준선 삭제': 'Remove reference line',
    '계산 값 추가': 'Add calculation',
    '강조 추가': 'Add highlight',
    '강조 삭제': 'Remove highlight',
    '추세선·예측': 'Trend line and forecast',
    '필터 추가': 'Add filter',
    '필터 삭제': 'Remove filter',
    'KPI 카드 추가': 'Add KPI card',
    'KPI 카드 삭제': 'Remove KPI card',
    'KPI 카드 순서': 'KPI card order',
    '위젯 제목 변경': 'Rename widget',
    '인사이트 작성': 'Write insight',
    '데이터 질문': 'Ask for data',

    /* ── 좌측 네비 / left nav ── */
    '관리 센터': 'Admin Center', '리소스 센터': 'Resource Center',
    '지식 관리': 'Knowledge', '데이터 분석': 'Data Analysis',
    '업무 자동화': 'Task Automation', '그룹웨어': 'Groupware',
    '사이드바': 'Sidebar', '환경설정': 'Preferences',
  };
  var EN2KO = {};
  Object.keys(KO2EN).forEach(function (k) { EN2KO[KO2EN[k]] = k; });

  function lang() {
    try { return localStorage.getItem(KEY) === 'en' ? 'en' : 'ko'; } catch (e) { return 'ko'; }
  }

  /* 텍스트 노드 + placeholder/title 사전 치환 — 무변경 대입은 건너뛴다(옵저버 피드백 루프 방지).
     [data-i18n-skip] 안은 사용자의 데이터(만든 위젯의 이름 · 칸 값)라 건드리지 않는다: 칸 값 "OK" 가 "확인"으로, "완료"가 "Completed"로 바뀌면 안 된다 */
  /* Dictionary swap over text nodes + placeholder/title — no-op assignments skipped (no observer loops).
     Anything inside [data-i18n-skip] is user data (a made widget's name and cells) and is left alone: a cell reading "OK" must not
     become "확인", nor "완료" become "Completed" */
  function applyLang(l) {
    var map = l === 'en' ? KO2EN : EN2KO;
    var tr = function (s) { var t = (s || '').trim(); return t && map[t] ? s.replace(t, map[t]) : s; };
    var tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) {
        if (!n.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        var el = n.parentElement;
        if (el && (el.tagName === 'SCRIPT' || el.tagName === 'STYLE')) return NodeFilter.FILTER_REJECT;
        if (el && el.closest('[data-i18n-skip]')) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    var nodes = []; var n;
    while ((n = tw.nextNode())) nodes.push(n);
    nodes.forEach(function (node) {
      var rep = tr(node.nodeValue);
      if (rep !== node.nodeValue) node.nodeValue = rep;
    });
    document.querySelectorAll('[placeholder]').forEach(function (el) {
      if (el.closest('[data-i18n-skip]')) return;
      var v = tr(el.placeholder); if (v !== el.placeholder) el.placeholder = v;
    });
    document.querySelectorAll('[title]').forEach(function (el) {
      if (el.closest('[data-i18n-skip]')) return;
      var v = tr(el.getAttribute('title')); if (v !== el.getAttribute('title')) el.title = v;
    });
  }

  /* Teams 액션 버튼 제거 — 액션/조회 전면 삭제(회의는 캘린더 소관이라 유지) */
  /* Remove the Teams action button — actions/reads deleted (meetings stay under calendar) */
  function dropTeams() {
    document.querySelectorAll('.act-btn[data-ns="teams"]').forEach(function (b) { b.remove(); });
  }

  dropTeams();
  if (lang() === 'en') applyLang('en');
  /* 화면을 다시 그린 쪽(static/home_dash.js 의 대시보드 설정 화면)이 바로 부른다 — 아래 옵저버의 0.12초를 기다리면 영어에서 한국어가 잠깐 보인다 */
  /* Called right after a redraw (the dashboard settings page in static/home_dash.js); waiting for the observer's 0.12 s below would flash Korean in English */
  window.AI365_homeLang = function () { if (lang() === 'en') applyLang('en'); };
  /* 지금 언어('ko' | 'en') — 만든 위젯의 차트가 추세 범례 이름을 고를 때 쓴다(static/home_dash.js) / the current language, used by made-widget charts for trend legend names */
  window.AI365_homeLangIs = function () { return lang(); };

  /* 부모 앱의 KO/EN 토글에 실시간 반응(동일 출처 storage 이벤트) */
  /* React live to the parent app's KO/EN toggle (same-origin storage event) */
  window.addEventListener('storage', function (e) {
    if (e.key === KEY) applyLang(lang());
  });

  /* 동적 재렌더(위젯 편집·모달·자동완성) 후 재적용 — 디바운스 */
  /* Re-apply after dynamic re-renders (widget edit / modals / autocomplete) — debounced */
  var t = null;
  new MutationObserver(function () {
    if (t) return;
    t = setTimeout(function () {
      t = null;
      dropTeams();
      if (lang() === 'en') applyLang('en');
    }, 120);
  }).observe(document.body, { childList: true, subtree: true });
})();
