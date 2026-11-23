"""@멘션 도구 능력 카탈로그 — 네임스페이스 × {조회(info)|실행(action)} × 동사의 단일 출처.

키는 `<namespace>.<kind>.<verb>` 3세그먼트다. 구형 키(mail.new 등)는 2세그먼트라
세그먼트 수만으로 마이그레이션 판별이 되므로 별도 버전 컬럼이 필요 없다.

핵심 불변식: **kind == "action" ⟺ exec is not None**. 딥링크로 실제 실행이 되는 것만
Action이고, 실행 수단이 없는 능력은 전부 Info(조회)로 내린다. 모듈 로드 시 assert로 강제해
"실행 가능한 것만 Action"이 주석이 아니라 코드로 남게 한다.

app/catalog.py가 리소스 트리의 단일 출처인 것과 같은 역할 — smart_actions.py는 저장만,
여기서 ACTION_KEYS·DEFAULTS를 파생한다. 폼 파라미터 스키마(라벨·placeholder·타이프어헤드
힌트)는 순수 렌더 관심사라 adapter.js에 남는다.
"""
# @-mention tool capability catalog — single source of truth for namespace x {info|action} x verb.
#
# Keys are 3-segment `<namespace>.<kind>.<verb>`. Legacy keys (mail.new, ...) are 2-segment, so
# migration can be detected by segment count alone — no version column needed.
#
# Core invariant: **kind == "action" <=> exec is not None**. Only capabilities that a deep link can
# actually execute are Actions; everything without an execution path becomes Info (read-only).
# Enforced by assert at import so "only what really executes is an Action" lives in code, not a comment.
#
# Same role app/catalog.py plays for the resource tree: smart_actions.py only persists, while
# ACTION_KEYS/DEFAULTS are derived here. Form param schemas (labels, placeholders, typeahead hints)
# stay in adapter.js — they are pure rendering concerns.

# 네임스페이스 — 사용자가 입력하는 @토큰과 1:1. limits는 조회 전용 도구가 "왜 실행이 없는지"를
# 설명하는 고정 문구다(LLM이 즉흥 작문하면 데모에서 틀린 말을 한다).
# Namespaces — 1:1 with the @token users type. `limits` is the fixed sentence explaining why a
# read-only tool has no actions (letting an LLM improvise this produces wrong claims in the demo).
NAMESPACES = {
    "mail": {
        "label": "Outlook 메일",
        "app_url": "https://outlook.office.com/mail/",
        "limits": None,
    },
    "calendar": {
        "label": "Outlook 일정",
        "app_url": "https://outlook.office.com/calendar/",
        "limits": "기존 일정의 수정·취소·참석자 변경은 조회만 지원합니다 — 변경은 Microsoft Graph 연동이 필요합니다",
    },
    "todo": {
        "label": "Microsoft To Do",
        "app_url": "https://to-do.office.com/tasks/",
        "limits": "조회·생성·완료 처리를 지원합니다 — 세부 편집(기한 변경·목록 이동)은 조회만 지원합니다",
    },
    "sharepoint": {
        "label": "SharePoint",
        "app_url": "https://www.office.com/launch/sharepoint",
        "limits": "조회만 지원합니다 — 폴더 생성·업로드·다운로드는 Microsoft Graph 연동이 필요합니다",
    },
}

# 표시 순서(멘션 목록·관리 센터 공통) / display order shared by the mention list and admin center
# Teams는 제거(2026-08-28 사용자 지시 — Microsoft Graph의 Teams API가 MFA를 요구해 실연동 불가).
# Teams removed (user decision 2026-08-28 — the Graph Teams API requires MFA, so real integration is impossible).
NS_ORDER = ("mail", "calendar", "todo", "sharepoint")

# 능력 항목 — key/ns/kind/verb는 키에서 파생 가능하지만 조회 편의를 위해 펼쳐 둔다.
#   exec   : 실행 수단 식별자(action 전용). None이면 Action이 될 수 없다.
#   view   : 결과 렌더러 종류(info 전용) — adapter.js의 카드 렌더러와 1:1.
#   match  : 규칙 우선 분류기의 키워드. 앞쪽 항목일수록 먼저 검사된다.
#   prompt : 관리 센터 기본 프롬프트. Action은 폼 작성 지침, Info는 결과 서술·필터 방침.
# Capability entries — key/ns/kind/verb are derivable from the key but kept expanded for lookup ease.
#   exec: execution-mechanism id (actions only); None means it cannot be an Action.
#   view: result renderer kind (info only) — 1:1 with adapter.js card renderers.
#   match: keywords for the rule-first classifier; earlier entries are tested first.
#   prompt: admin-center default — form guidance for actions, narration/filter policy for infos.
CATALOG = (
    # ── Outlook 메일 ──────────────────────────────────────────────────────────
    {
        "key": "mail.info.unread", "view": "mailList",
        "label": "안 읽은 메일", "desc": "아직 읽지 않은 메일만 모아 보여줍니다",
        "match": ("안 읽은", "안읽은", "안 읽", "unread", "새 메일", "새로운 메일"),
        "examples": ("@mail 안 읽은 메일 있어?",),
        "prompt": "안 읽은 메일을 최신순으로 정리한다. 보낸 사람과 제목을 앞세우고, 답장이 필요해 보이는 건을 먼저 언급한다.",
    },
    {
        "key": "mail.info.from", "view": "mailList",
        "label": "발신자별 메일", "desc": "특정 사람이 보낸 메일만 골라 보여줍니다",
        "match": ("보낸 메일", "에게서", "한테서", "님이 보낸", "이 보낸", "가 보낸", "from"),
        "examples": ("@mail 김민준 님이 보낸 메일 보여줘",),
        "prompt": "지정한 발신자의 메일만 최신순으로 정리한다. 발신자를 찾지 못하면 조직도에 없는 이름임을 알린다.",
    },
    {
        "key": "mail.info.detail", "view": "mailDetail",
        "label": "메일 본문·첨부", "desc": "메일 한 건의 본문과 첨부파일을 펼쳐 봅니다",
        "match": ("본문", "내용 보여", "열어", "첨부", "detail", "전문"),
        "examples": ("@mail 예산안 검토 요청 메일 본문 보여줘",),
        "prompt": "메일 본문을 그대로 보여주되, 요청 사항이 있으면 마지막에 한 줄로 짚어 준다.",
    },
    {
        "key": "mail.info.search", "view": "mailList",
        "label": "메일 검색", "desc": "키워드·기간으로 메일을 찾습니다",
        "match": ("검색", "찾아", "관련 메일", "search"),
        "examples": ("@mail 계약 관련 메일 찾아줘",),
        "prompt": "키워드와 기간 조건에 맞는 메일을 최신순으로 정리한다. 결과가 없으면 조건을 넓혀 볼 것을 제안한다.",
    },
    {
        "key": "mail.info.digest", "view": "mailList", "narrate": True,
        "label": "메일함 브리핑", "desc": "받은 메일을 요약해 지금 처리할 것을 짚어 줍니다",
        "match": ("브리핑", "요약", "정리해", "digest", "뭐 왔"),
        "examples": ("@mail 오늘 온 메일 브리핑해줘",),
        "prompt": "받은 메일을 3줄 이내로 요약한다. 답장이 필요한 건, 기한이 임박한 건 순으로 짚고 나머지는 묶어서 언급한다.",
    },
    {
        "key": "mail.info.inbox", "view": "mailList",
        "label": "받은 메일", "desc": "받은 편지함을 최신순으로 보여줍니다",
        # '받은'만 두면 '주고받은'·'전달받은' 같은 낱말 안에도 걸려 이 항목이 자석이 된다
        # A bare '받은' also matches inside words like '주고받은', turning this entry into a magnet
        "match": ("받은 메일", "받은메일", "받은 편지함", "메일함", "inbox", "메일 목록"),
        "examples": ("@mail 받은 메일 보여줘",),
        "prompt": "받은 편지함을 최신순으로 정리한다. 안 읽은 메일을 먼저 눈에 띄게 표시한다.",
    },
    {
        "key": "mail.action.compose", "exec": "outlook_mail",
        "label": "새 메일 작성", "desc": "받는 사람·제목·본문을 채운 Outlook 작성 창을 엽니다",
        "match": ("메일 써", "메일 보내", "메일 작성", "이메일 보내", "발송", "compose"),
        "examples": ("@mail 김민준 님께 실적 자료 요청 메일 써줘",),
        "prompt": "대화 내용을 바탕으로 받는 사람·제목·본문을 구성한다. 회사 표준 톤(정중·간결)을 따르고 본문은 인사-요지-마무리 구조로 쓴다.",
    },

    # ── Outlook 일정 ──────────────────────────────────────────────────────────
    {
        "key": "calendar.info.today", "view": "eventList",
        "label": "오늘 일정", "desc": "오늘 하루 일정을 시간순으로 보여줍니다",
        "match": ("오늘", "today", "하루"),
        "examples": ("@calendar 오늘 일정 알려줘",),
        "prompt": "오늘 일정을 시간순으로 정리한다. 다음 일정이 임박했으면 남은 시간을 함께 알린다.",
    },
    {
        "key": "calendar.info.week", "view": "eventList",
        "label": "이번 주 일정", "desc": "이번 주 일정을 날짜별로 보여줍니다",
        "match": ("이번 주", "이번주", "주간", "week"),
        "examples": ("@calendar 이번 주 일정 보여줘",),
        "prompt": "이번 주 일정을 날짜별로 묶어 정리한다. 회의가 몰린 날이 있으면 짚어 준다.",
    },
    {
        "key": "calendar.info.next", "view": "eventList",
        "label": "다음 일정", "desc": "바로 다음에 있을 일정 하나를 알려줍니다",
        "match": ("다음 일정", "다음 회의", "곧", "next"),
        "examples": ("@calendar 다음 일정 뭐야?",),
        "prompt": "다음 일정 하나만 알려준다. 시작까지 남은 시간과 장소·참석자를 함께 전한다.",
    },
    {
        "key": "calendar.info.free", "view": "slotList",
        "label": "빈 시간 찾기", "desc": "일정이 비어 있는 시간대를 찾아 줍니다",
        "match": ("빈 시간", "빈시간", "가능한 시간", "언제 비", "free"),
        "examples": ("@calendar 내일 빈 시간 찾아줘",),
        "prompt": "업무시간(09:00~18:00) 안에서 비어 있는 구간을 길이순으로 제안한다. 점심시간은 제외한다.",
    },
    {
        "key": "calendar.info.range", "view": "eventList",
        "label": "기간 조회", "desc": "특정 날짜나 기간의 일정을 보여줍니다",
        "match": ("일정", "스케줄", "calendar", "schedule"),
        "examples": ("@calendar 다음 주 화요일 일정 보여줘",),
        "prompt": "요청한 날짜·기간의 일정을 시간순으로 정리한다. 기간이 모호하면 가장 가까운 해석을 택하고 그 기준을 밝힌다.",
    },
    {
        "key": "calendar.action.event", "exec": "outlook_calendar",
        "label": "새 일정 만들기", "desc": "제목·일시를 채운 Outlook 일정 작성 창을 엽니다",
        "match": ("일정 잡", "일정 만들", "일정 생성", "일정 등록", "예약"),
        "examples": ("@calendar 내일 오후 2시에 실적 리뷰 일정 잡아줘",),
        "prompt": "대화에서 일정 제목과 날짜·시간을 추출해 일정을 구성한다. 시간이 모호하면 가장 가까운 업무시간대를 제안한다.",
    },
    {
        "key": "calendar.action.meeting", "exec": "teams_meeting",
        "label": "Teams 회의 만들기", "desc": "제목·참석자를 채운 Teams 회의 생성 화면을 엽니다",
        "match": ("회의 잡", "회의 만들", "미팅 잡", "teams 회의", "온라인 회의"),
        "examples": ("@calendar 김민준·이서윤 님과 내일 3시 회의 잡아줘",),
        "prompt": "대화에서 회의 제목·일시·참석자를 추출해 Teams 회의로 구성한다. 참석자는 조직도 구성원 이름으로 정리한다.",
    },

    # ── Microsoft To Do (조회 + 완료·생성) ────────────────────────────────────
    {
        "key": "todo.info.overdue", "view": "taskList",
        "label": "기한 지난 할 일", "desc": "기한을 넘긴 할 일을 모아 보여줍니다",
        "match": ("기한 지", "지연", "밀린", "overdue", "늦은"),
        "examples": ("@todo 기한 지난 거 있어?",),
        "prompt": "기한이 지난 할 일을 오래된 순으로 정리한다. 며칠 지났는지 함께 알린다.",
    },
    {
        "key": "todo.info.today", "view": "taskList",
        "label": "오늘 할 일", "desc": "오늘 기한인 할 일을 보여줍니다",
        "match": ("오늘", "today", "오늘까지"),
        "examples": ("@todo 오늘 할 일 알려줘",),
        "prompt": "오늘 기한인 할 일을 중요도순으로 정리한다.",
    },
    {
        "key": "todo.info.assigned", "view": "taskList",
        "label": "내게 배정된 할 일", "desc": "나에게 배정된 항목만 보여줍니다",
        "match": ("내게", "나한테", "배정", "assigned", "내 할 일"),
        "examples": ("@todo 나한테 배정된 거 뭐 있어?",),
        "prompt": "나에게 배정된 미완료 할 일을 기한순으로 정리한다.",
    },
    {
        "key": "todo.info.completed", "view": "taskList",
        "label": "완료 이력", "desc": "최근 완료한 할 일을 보여줍니다",
        "match": ("완료", "끝낸", "done", "completed"),
        "examples": ("@todo 최근 완료한 거 보여줘",),
        "prompt": "최근 완료한 할 일을 완료일 최신순으로 정리한다.",
    },
    {
        "key": "todo.info.list", "view": "taskList",
        "label": "할 일 목록", "desc": "미완료 할 일 전체를 보여줍니다",
        "match": ("할 일", "할일", "태스크", "task", "todo", "목록"),
        "examples": ("@todo 할 일 목록 보여줘",),
        "prompt": "미완료 할 일을 기한순으로 정리한다. 기한이 없는 항목은 뒤로 보낸다.",
    },
    {
        "key": "todo.action.complete", "exec": "todo_complete",
        "label": "할 일 완료 처리", "desc": "지정한 할 일을 완료 상태로 바꿉니다",
        "match": ("완료 처리", "완료해", "끝냈", "체크"),
        "examples": ("@todo 하반기 교육 수요조사 완료 처리해줘",),
        "prompt": "대화에서 완료할 할 일의 제목을 특정한다. 제목이 모호하면 가장 가까운 미완료 항목을 제안한다.",
    },
    {
        "key": "todo.action.create", "exec": "todo_create",
        "label": "새 할 일 추가", "desc": "제목·기한을 채운 새 할 일을 등록합니다",
        "match": ("할 일 추가", "할일 추가", "태스크 추가", "투두 추가", "할 일 만들"),
        "examples": ("@todo 3분기 보고서 초안 작성 할 일 추가해줘",),
        "prompt": "대화에서 새 할 일의 제목과 (있으면) 기한을 추출해 등록 항목을 구성한다.",
    },

    # ── SharePoint (조회 전용) ────────────────────────────────────────────────
    {
        "key": "sharepoint.info.search", "view": "fileList",
        "label": "파일 검색", "desc": "이름·확장자로 문서를 찾습니다",
        "match": ("검색", "찾아", "search", "어디 있"),
        "examples": ("@sharepoint 실적 보고서 찾아줘",),
        "prompt": "검색어에 맞는 파일을 관련도순으로 정리한다. 경로와 최종 수정자를 함께 보여준다.",
    },
    {
        "key": "sharepoint.info.shared", "view": "fileList",
        "label": "공유받은 문서", "desc": "다른 사람이 나에게 공유한 문서를 보여줍니다",
        "match": ("공유받", "공유 받", "shared", "받은 문서"),
        "examples": ("@sharepoint 공유받은 문서 보여줘",),
        "prompt": "나에게 공유된 문서를 공유일 최신순으로 정리한다. 공유한 사람을 함께 표시한다.",
    },
    {
        "key": "sharepoint.info.browse", "view": "fileList",
        "label": "폴더 탐색", "desc": "폴더 안의 파일 목록을 보여줍니다",
        "match": ("폴더", "디렉터리", "folder", "안에"),
        "examples": ("@sharepoint 보고서 폴더 안에 뭐 있어?",),
        "prompt": "지정한 폴더의 하위 폴더와 파일을 폴더 먼저, 그다음 파일 순으로 정리한다.",
    },
    {
        "key": "sharepoint.info.recent", "view": "fileList",
        "label": "최근 문서", "desc": "최근에 열었거나 수정된 문서를 보여줍니다",
        "match": ("최근", "recent", "문서", "파일"),
        "examples": ("@sharepoint 최근 문서 보여줘",),
        "prompt": "최근 수정된 문서를 최신순으로 정리한다. 파일 형식과 수정자를 함께 보여준다.",
    },
)

# 구형 2세그먼트 키 → 신규 3세그먼트 키. None은 폐지(실행 수단이 없어 Action이 될 수 없는 것).
# 사용자가 편집한 프롬프트·enabled를 보존하기 위한 매핑이다.
# Legacy 2-segment keys -> new 3-segment keys. None means retired (no execution path, so it cannot
# be an Action). This mapping exists to preserve user-edited prompts and enabled flags.
LEGACY_RENAME = (
    ("mail.new", "mail.action.compose"),
    ("cal.event", "calendar.action.event"),
    ("cal.meet", "calendar.action.meeting"),
    ("teams.msg", None),
    ("teams.group", None),
    ("sp.folder", None),
    ("todo.new", None),
    ("todo.done", None),
    ("todo.mail", None),
)

# 구형 키가 속한 도구 — 능력 단위 저장분을 도구 단위로 접을 때 쓴다.
# The tool a legacy key belonged to — used when folding per-capability storage into per-tool storage.
LEGACY_NS = {"mail": "mail", "cal": "calendar", "sp": "sharepoint", "todo": "todo"}


def ns_of_stored(key: str) -> str | None:
    """저장된 구형 키(2·3세그먼트) → 도구 이름."""
    # A stored legacy key (2- or 3-segment) -> tool name.
    head = str(key).split(".")[0]
    return LEGACY_NS.get(head)


def _split(key: str) -> tuple[str, str, str]:
    ns, kind, verb = key.split(".")
    return ns, kind, verb


# 파생 인덱스 — key로 항목을 찾고, ns/kind로 묶는다.
# Derived indexes — look up an entry by key, group by ns/kind.
KEY_INDEX: dict[str, dict] = {}
for _e in CATALOG:
    _ns, _kind, _verb = _split(_e["key"])
    KEY_INDEX[_e["key"]] = {
        **_e,
        "ns": _ns,
        "kind": _kind,
        "verb": _verb,
        "exec": _e.get("exec"),
        "view": _e.get("view"),
        "narrate": _e.get("narrate", False),
    }

ACTION_KEYS = tuple(e["key"] for e in CATALOG)

# 저장 스키마는 **도구(@) 단위 사용 여부**뿐이다(5개). 세부 능력은 켜고 끄지 않는다 —
# 관리자가 판단할 단위는 "이 도구를 쓸지"이지 "받은메일 조회만 끌지"가 아니다.
# 프롬프트도 저장하지 않는다: 응답 형식·필드명·렌더러와 함께 움직이는 구현 세부라 코드가 소유한다.
# The stored schema is **per-tool (@) availability** only — five entries. Individual capabilities are not
# toggled: what an admin decides is whether a tool is in play, not whether to disable "inbox reads" alone.
# Prompts are not stored either; they move with the response format, field names, and renderer, so code owns them.
CONFIG_KEYS = NS_ORDER
DEFAULTS = {ns: {"enabled": True} for ns in NS_ORDER}


def prompt_of(key: str) -> str:
    """능력별 AI 동작 지침 — 코드에서만 온다."""
    # A capability's AI behavior guidance — sourced from code only.
    meta = KEY_INDEX.get(key)
    return meta["prompt"] if meta else ""


def keys_of(ns: str, kind: str | None = None) -> tuple[str, ...]:
    """네임스페이스(+선택적 kind)에 속한 키를 카탈로그 순서로 반환."""
    # Keys belonging to a namespace (optionally filtered by kind), in catalog order.
    return tuple(
        k for k, v in KEY_INDEX.items()
        if v["ns"] == ns and (kind is None or v["kind"] == kind)
    )


# ── 불변식 (import 시 강제) ────────────────────────────────────────────────────
# ── Invariants (enforced at import) ───────────────────────────────────────────
assert len(ACTION_KEYS) == len(set(ACTION_KEYS)), "카탈로그에 중복 키가 있습니다"
for _k, _v in KEY_INDEX.items():
    assert _v["ns"] in NAMESPACES, f"{_k}: 알 수 없는 네임스페이스"
    assert _v["kind"] in ("info", "action"), f"{_k}: kind는 info|action 이어야 합니다"
    # 실행 수단이 있는 것만 Action이다 — 이 프로젝트의 핵심 규칙
    # Only capabilities with an execution path are Actions — this project's core rule
    assert (_v["kind"] == "action") == (_v["exec"] is not None), \
        f"{_k}: kind=action 과 exec 유무가 일치해야 합니다"
    assert (_v["kind"] == "info") == (_v["view"] is not None), \
        f"{_k}: kind=info 항목에만 view가 있어야 합니다"
    assert _v["prompt"].strip(), f"{_k}: 기본 프롬프트가 비어 있습니다"
for _ns in NAMESPACES:
    assert _ns in NS_ORDER, f"{_ns}: NS_ORDER에 빠져 있습니다"
    assert keys_of(_ns, "info"), f"{_ns}: 조회 능력이 최소 1개 필요합니다"
    # Action이 없는 네임스페이스는 그 이유를 limits로 반드시 밝힌다
    # A namespace with no actions must state why via limits
    assert keys_of(_ns, "action") or NAMESPACES[_ns]["limits"], \
        f"{_ns}: Action이 없으면 limits 문구가 필요합니다"
