"""접근 통제(관리 센터) 영속화 + 실효 권한 엔진 — SQLite.

목업(frontend/ai365-mockup.html)의 관리 센터/리소스 센터가 in-memory로만 들고 있던
조직도 구성원·권한 그룹·데이터 분석 워크스페이스를 DB에 저장해 새로고침 후에도 유지한다.

단일 소스(source of truth): 목업의 window.AI365_ORG_MEMBERS / AI365_ORG_GROUPS /
AI365_WORKSPACES 와 동일한 시드를 Python으로 그대로 포팅해 최초 1회 시드한다.
이후 프론트의 생성/수정/삭제는 이 모듈의 API를 통해 영속화되고, 부팅 시 다시 하이드레이션된다.

실효 권한 엔진(effective)은 목업 '실효 권한 미리보기'의 JS 로직을 그대로 옮긴 것:
합집합만(가산) · 폴더 캐스케이드 · 그룹 한정 예외 · 열람(1)/관리(2) 2단 · 메뉴 게이트.
"""
# Access control (Admin Center) persistence + effective-permission engine — SQLite.
#
# Org-chart members, permission groups, and data-analysis workspaces — which the mockup
# (frontend/ai365-mockup.html) Admin Center / Resource Center kept in-memory only — are stored
# in the DB so they persist across page refreshes.
#
# Source of truth: the same seed as the mockup's window.AI365_ORG_MEMBERS / AI365_ORG_GROUPS /
# AI365_WORKSPACES is ported verbatim to Python and seeded once on first run.
# Afterward the front-end's create/update/delete is persisted through this module's API,
# and re-hydrated again on boot.
#
# The effective-permission engine (effective) is a verbatim port of the mockup's
# 'effective-permission preview' JS logic:
# union only (additive) · folder cascade · group-scoped exceptions · view(1)/manage(2) two tiers · menu gate.

import json
import logging
import sqlite3
import threading

from app import catalog
from app.db import DB_PATH

logger = logging.getLogger("ai365.access")

# ─────────────────────────────────────────────────────────────────────────────
# 시드 데이터 — 목업 IIFE(약 7576~7664행)의 JS 생성 로직을 결정적으로 포팅
# Seed data — deterministic port of the mockup IIFE's (~lines 7576-7664) JS generation logic
# ─────────────────────────────────────────────────────────────────────────────

ORG_NPOOL = [
    {"ko": "홍서연", "en": "seoyeon.hong"}, {"ko": "김민준", "en": "minjun.kim"},
    {"ko": "이서윤", "en": "seoyoon.lee"}, {"ko": "박도윤", "en": "doyoon.park"},
    {"ko": "최지우", "en": "jiwoo.choi"}, {"ko": "정하준", "en": "hajun.jung"},
    {"ko": "강수아", "en": "sua.kang"}, {"ko": "조예준", "en": "yejun.cho"},
    {"ko": "윤지호", "en": "jiho.yoon"}, {"ko": "임채원", "en": "chaewon.lim"},
    {"ko": "한지안", "en": "jian.han"}, {"ko": "오은우", "en": "eunwoo.oh"},
    {"ko": "서지민", "en": "jimin.seo"}, {"ko": "신예린", "en": "yerin.shin"},
    {"ko": "권민서", "en": "minseo.kwon"}, {"ko": "황시우", "en": "siwoo.hwang"},
    {"ko": "안하은", "en": "haeun.ahn"}, {"ko": "송지율", "en": "jiyul.song"},
    {"ko": "전유나", "en": "yuna.jeon"}, {"ko": "홍준우", "en": "junwoo.hong"},
    {"ko": "고서진", "en": "seojin.ko"}, {"ko": "문가은", "en": "gaeun.moon"},
    {"ko": "양도현", "en": "dohyun.yang"}, {"ko": "배수빈", "en": "subin.bae"},
    {"ko": "백지윤", "en": "jiyoon.baek"}, {"ko": "허준서", "en": "junseo.heo"},
    {"ko": "유다은", "en": "daeun.yoo"}, {"ko": "남시연", "en": "siyeon.nam"},
    {"ko": "심우진", "en": "woojin.shim"}, {"ko": "노하린", "en": "harin.no"},
    {"ko": "하지환", "en": "jihwan.ha"}, {"ko": "곽서아", "en": "seoa.kwak"},
]
ORG_GRADES = ["선임", "책임", "수석", "대리", "과장", "차장", "부장", "사원"]
ORG_PREV = ["재무회계파트", "영업관리파트", "PMO파트", "기술운영파트", "AI 파트", "인사총무"]
ORG_DEF = [
    {"id": "ceo", "name": "대표이사", "cnt": 1, "leaf": True},
    {"id": "mgmt", "name": "경영지원본부", "children": [
        {"id": "fin", "name": "재무회계파트", "cnt": 3},
        {"id": "sales", "name": "영업관리파트", "cnt": 1},
        {"id": "hr", "name": "인사총무", "cnt": 3},
    ]},
    {"id": "pmo", "name": "PMO", "children": [
        {"id": "pmo1", "name": "PMO파트", "cnt": 11},
        {"id": "tech", "name": "기술운영파트", "cnt": 3},
    ]},
    {"id": "dev", "name": "AI365 개발본부", "children": [
        {"id": "ai", "name": "AI 파트", "cnt": 10},
        {"id": "aiagent", "name": "AI Agent 파트", "cnt": 8},
        {"id": "fe", "name": "Front-End 파트", "cnt": 2},
    ]},
]
TEAMS = ["대표이사", "재무회계파트", "영업관리파트", "인사총무", "PMO파트",
         "기술운영파트", "AI 파트", "AI Agent 파트", "Front-End 파트"]


def _pad(n: int) -> str:
    return str(n).zfill(2)


def seed_members() -> list[dict]:
    """목업과 동일한 42명을 결정적으로 생성(no===gi, 1-based)."""
    # Deterministically generate the same 42 members as the mockup (no===gi, 1-based).
    members: list[dict] = []
    gi = 0

    def mk(dept_name: str, div_name: str, is_head: bool) -> None:
        nonlocal gi
        gi += 1
        no = gi
        p = ORG_NPOOL[(gi - 1) % len(ORG_NPOOL)]
        cyc = (gi - 1) // len(ORG_NPOOL)
        is_ceo = dept_name == "대표이사"
        grade = "대표" if is_ceo else ORG_GRADES[(gi - 1) % len(ORG_GRADES)]
        role = "대표이사" if is_ceo else ("파트장" if is_head else "팀원")
        en = p["en"] + (str(cyc + 1) if cyc > 0 else "")
        yr = 2010 + ((gi * 3) % 14)
        mo = 1 + ((gi * 5) % 12)
        dy = 1 + ((gi * 7) % 27)
        join = f"{yr}-{_pad(mo)}-{_pad(dy)}"
        empno = f"{yr}{_pad(mo)}{_pad(dy)}{_pad((gi % 50) + 1)}"
        phone = f"010-{_pad((gi * 13) % 100)}{_pad((gi * 29) % 100)}-{_pad((gi * 7) % 100)}{_pad((gi * 3) % 100)}"
        tel = f"02-{100 + (gi % 900)}-{_pad((gi * 11) % 100)}{_pad((gi * 5) % 100)}"
        hist: list[dict] = []
        if (gi % 3 == 0) and yr <= 2018:
            p_yr = yr + 3 + (gi % 4)
            hist.append({"tag": "본부서", "dept": dept_name, "role": role, "date": f"{p_yr}-01-01 현재", "cur": True})
            hist.append({"tag": "본부서 종료", "dept": ORG_PREV[gi % len(ORG_PREV)], "role": "팀원",
                         "date": f"{join} ~ {p_yr}-01-01"})
        else:
            hist.append({"tag": "본부서", "dept": dept_name, "role": role, "date": f"{join} 현재", "cur": True})
        members.append({
            "no": no, "name": p["ko"], "dept": dept_name, "div": div_name, "grade": grade, "role": role,
            "email": en + "@internal.example", "phone": phone, "tel": tel, "empno": empno, "join": join, "hist": hist,
        })

    for top in ORG_DEF:
        if top.get("leaf"):
            for i in range(top["cnt"]):
                mk(top["name"], top["name"], i == 0)
        else:
            for ch in top["children"]:
                for i in range(ch["cnt"]):
                    mk(ch["name"], top["name"], i == 0)
    return members


def seed_groups(members: list[dict]) -> list[dict]:
    """목업의 캐노니컬 11개 권한 그룹(팀 표준 9 + 팀장 + 데이터 분석가)."""
    # The mockup's canonical 11 permission groups (9 team standards + Team Lead + Data Analyst).
    by_team: dict[str, list[int]] = {}
    for m in members:
        by_team.setdefault(m["dept"], []).append(m["no"])
    unassigned = members[-1]["no"] if members else -1  # deny-by-default 데모: 미배정 1명
    # deny-by-default demo: 1 unassigned member
    leads = [m["no"] for m in members if m["role"] == "파트장"]
    analysts = ([m["no"] for m in members if m["dept"] == "재무회계파트"][:1]
                + [m["no"] for m in members if m["dept"] == "AI 파트"][:2])  # 재무 1 + AI 2
    # Finance 1 + AI 2
    tg = {
        "대표이사": {"menus": ["m_home", "m_chat", "m_coll", "m_res", "m_admin"],
                  "grants": [{"node": "m_res", "action": "manage"}, {"node": "m_admin", "action": "view"}], "exceptions": []},
        "재무회계파트": {"menus": ["m_home", "m_chat", "m_coll", "m_res"],
                   "grants": [{"node": "p_data", "action": "view"}], "exceptions": [{"node": "tbl_hr", "type": "exclude"}]},
        "영업관리파트": {"menus": ["m_home", "m_chat", "m_coll", "m_res"],
                   "grants": [{"node": "p_data", "action": "view"}], "exceptions": [{"node": "tbl_hr", "type": "exclude"}]},
        "인사총무": {"menus": ["m_home", "m_chat", "m_res"],
                  "grants": [{"node": "f_hr", "action": "view"}, {"node": "tbl_hr", "action": "view"}], "exceptions": []},
        "PMO파트": {"menus": ["m_home", "m_chat", "m_coll", "m_res"],
                  "grants": [{"node": "p_know", "action": "view"}], "exceptions": []},
        "기술운영파트": {"menus": ["m_home", "m_chat", "m_res"],
                   "grants": [{"node": "p_auto", "action": "view"}], "exceptions": []},
        "AI 파트": {"menus": ["m_home", "m_chat", "m_coll", "m_res"],
                  "grants": [{"node": "p_data", "action": "view"}, {"node": "p_know", "action": "view"}],
                  "exceptions": [{"node": "tbl_hr", "type": "exclude"}]},
        "AI Agent 파트": {"menus": ["m_home", "m_chat", "m_coll", "m_res"],
                        "grants": [{"node": "p_auto", "action": "view"}, {"node": "p_data", "action": "view"}],
                        "exceptions": [{"node": "tbl_hr", "type": "exclude"}]},
        "Front-End 파트": {"menus": ["m_home", "m_chat", "m_coll", "m_res"],
                         "grants": [{"node": "p_know", "action": "view"}], "exceptions": []},
    }
    groups: list[dict] = []
    gi = 0
    for t in TEAMS:
        conf = tg.get(t, {"menus": ["m_home", "m_chat"], "grants": [], "exceptions": []})
        mem = [no for no in by_team.get(t, []) if no != unassigned]
        groups.append({"id": "og" + str(gi), "name": t + " 표준", "desc": t + " 기본 접근 권한",
                       "memberIds": mem, "menus": conf["menus"], "grants": conf["grants"], "exceptions": conf["exceptions"]})
        gi += 1
    # 팀장 = 4축 앵커 기본 권한(2026-09-26 사용자 결정): 지식·데이터·업무 자동화 관리 + API·MCP 도구 전체 열람.
    # 앵커 grant 는 group_map 캐스케이드로 뒤에 등록되는 API·MCP 도구·업무 자동화 에이전트까지 자동 포함한다.
    # 지식 관리 · Local(p_klocal, 2026-09-29) 관리 앵커도 같은 이유로 둔다(새 로컬 지식 에이전트 자동 포함).
    # Team lead = axis-anchor defaults (user decision 2026-09-26): manage knowledge, data and automation, view every API
    # and MCP tool. Anchor grants cascade through group_map, so later-registered tools and agents are covered automatically.
    # The Knowledge · Local anchor (p_klocal, 2026-09-29) is managed for the same reason (new local agents are included).
    groups.append({"id": "og" + str(gi), "name": "팀장", "desc": "전 팀 파트장 — 전 축 기본 권한(횡단)",
                   "memberIds": leads, "menus": ["m_home", "m_chat", "m_coll", "m_res"],
                   "grants": [{"node": "p_know", "action": "manage"}, {"node": "p_data", "action": "manage"},
                              {"node": "p_auto", "action": "manage"}, {"node": "p_conn", "action": "view"},
                              {"node": "p_klocal", "action": "manage"}],
                   "exceptions": []})
    gi += 1
    groups.append({"id": "og" + str(gi), "name": "데이터 분석가", "desc": "데이터 분석 심화 — BI 관리(횡단)",
                   "memberIds": analysts, "menus": ["m_home", "m_chat", "m_res"],
                   "grants": [{"node": "bi", "action": "manage"}, {"node": "p_data", "action": "view"}],
                   "exceptions": [{"node": "tbl_hr", "type": "exclude"}]})
    return groups


def seed_workspaces() -> list[dict]:
    """데이터 분석 워크스페이스 4개 — 카탈로그(실제 CSV/테이블/BI 매핑)에서 생성."""
    # 4 data-analysis workspaces — built from the catalog (real CSV/table/BI mapping).
    return catalog.seed_workspaces_data()


# 데이터셋 연결 카드 시드 — 목업 RM_DATASETS(약 9213행) 포팅. 값은 전부 데모용 모의 자격증명.
# Seed dataset-connection cards — port of the mockup's RM_DATASETS (~line 9213). All values are demo mock credentials.
SEED_CONNECTIONS: list[dict] = [
    {"id": "ds_erp", "kind": "DB", "name": "사내 ERP DB (재무)", "dstype": "sql",
     "host": "db.internal.ai365.co", "port": "5432", "database": "erp_finance", "schema": "public",
     "user": "ai365_reader", "password": "erp_demo_pw",
     "tables": [{"key": "BUDGET", "desc": "예산 편성 테이블"}, {"key": "ACTUALS", "desc": "실적 집계 테이블"},
                {"key": "DEPT_PL", "desc": "부서별 손익"}, {"key": "AP_AR", "desc": "수금·지급 원장"},
                {"key": "COST_CENTER", "desc": "코스트센터 마스터"}]},
    {"id": "ds_sales", "kind": "CSV", "name": "판매실적 CSV 데이터셋", "dstype": "csv",
     "storageAccount": "ai365sales", "containerName": "sales-data", "accessKey": "demoKeyAbc123==",
     "tables": [], "files": [{"name": "판매실적_2026Q1.csv"}, {"name": "판매실적_2026Q2.csv"}]},
]


# ─────────────────────────────────────────────────────────────────────────────
# 실효 권한 유니버스(PV_TREE) + 엔진 — 목업 미리보기 IIFE(약 1881~1967행) 포팅
# Effective-permission universe (PV_TREE) + engine — port of the mockup preview IIFE (~lines 1881-1967)
# ─────────────────────────────────────────────────────────────────────────────

# PV_TREE 는 카탈로그(app/catalog.py)에서 생성 — 권한 노드 = 실제 리소스(파일/테이블/BI)
# PV_TREE is generated from the catalog (app/catalog.py) — permission nodes = real resources (files/tables/BI)
PV_TREE = catalog.build_pv_tree()

# 인덱싱: node id → node, node id → parent id
# Indexing: node id → node, node id → parent id
PV_NODES: dict[str, dict] = {}
PV_PARENT: dict[str, str | None] = {}


def _index(nodes: list[dict], parent: str | None) -> None:
    for n in nodes:
        PV_NODES[n["id"]] = n
        PV_PARENT[n["id"]] = parent
        if n.get("children"):
            _index(n["children"], n["id"])


_index(PV_TREE, None)

_universe_lock = threading.Lock()
# 마지막 재구축에서 읽기에 실패한 동적 로더의 노드 접두사(2026-09-29). 그 축의 잎이 빈 목록으로 대체됐으니 _sanitize_groups 는
# 이 접두사의 grant · 예외를 지우지 않는다(지우면 exclude 예외가 사라져 앵커 grant 로 권한이 넓어진다).
# Node prefixes whose dynamic loader failed on the last rebuild (2026-09-29). Their leaves were replaced by an empty list, so
# _sanitize_groups must not prune grants or exceptions with these prefixes (dropping an exclude would widen access via the anchor).
_LOADER_GAPS: set[str] = set()


def rebuild_universe() -> None:
    """DB 스냅샷(지식 트리·워크스페이스·CSV 풀)으로 권한 유니버스를 재구축 — 변이 성공 직후마다 호출.

    catalog 파생맵과 PV_TREE/PV_NODES/PV_PARENT 를 in-place 갱신하므로 기존 참조는 그대로 유효하고,
    effective()/descendants()/_top_menu() 는 순수 함수라 즉시 새 유니버스를 따른다."""
    # Rebuild the permission universe from the DB snapshot (knowledge tree, workspaces, CSV pool) —
    # called right after every successful mutation. Updates catalog derived maps and
    # PV_TREE/PV_NODES/PV_PARENT in place, so existing references stay valid; effective()/descendants()/
    # _top_menu() are pure functions and follow the new universe immediately.
    with _universe_lock:
        gaps: set[str] = set()   # 이번에 읽지 못한 동적 축의 접두사 / prefixes of dynamic axes that failed to load this time
        try:
            knowledge = load_knowledge()
            workspaces = list_workspaces()
            pool = [e.get("table") for e in list_csv_pool() if e.get("table")]
        except sqlite3.OperationalError as e:
            knowledge, workspaces, pool = None, None, []  # 최초 부팅 중(테이블 미생성) — 시드 폴백
            # 표가 없는 게 아니라 읽기 실패(잠김 · 입출력 오류)면 시드 트리로 대신한 것이라, 사용자 폴더 · 파일 · 워크스페이스 · 슬롯의
            # grant · 예외를 부팅 정리가 지우지 않게 한다(2026-09-29, 지운 exclude 는 앵커 grant 로 권한을 넓힌다).
            # A read failure (locked, I/O) rather than a missing table means the seed tree stood in, so boot sanitize must not
            # prune grants/exceptions on user folders, files, workspaces or slots (2026-09-29; a pruned exclude widens access).
            if "no such table" not in str(e):
                logger.warning("지식 트리 · 워크스페이스를 읽지 못했습니다(f_ · kf_ · ws_ · sl_ 정리 보류)", exc_info=True)
                gaps.update(("f_", "kf_", "ws_", "sl_"))
        # 커넥터(2026-09-09) — 권한 축 p_conn 의 leaf. 테이블 미생성(부팅 순서)·오류는 빈 목록 + 정리 보류(cn_).
        # Connectors (2026-09-09) — leaves of the p_conn axis. Missing table (boot order) or errors → empty list, pruning held (cn_).
        try:
            from app import connectors as _connectors   # 지연 임포트(순환 방지) / lazy import (avoids a cycle)
            conns = [{"id": c["id"], "name": c["name"]} for c in _connectors.list_connectors()]
        except Exception:  # noqa: BLE001
            conns = []
            gaps.add("cn_")
        # 업무 자동화 에이전트(2026-09-22) — 리소스 관리에서 등록한 에이전트 = p_auto 의 잎. 테이블 미생성(부팅 순서)·오류는 빈 목록 + 정리 보류(agent_).
        # Work agents (2026-09-22) — agents registered in Resource Management become p_auto leaves. Missing table or errors → empty list, pruning held (agent_).
        try:
            from app import work_agents as _work_agents   # 지연 임포트(순환 방지) / lazy import (avoids a cycle)
            wagents = _work_agents.summaries()
        except Exception:  # noqa: BLE001
            wagents = []
            gaps.add("agent_")
        # 로컬 지식 에이전트(2026-09-29) — 등록한 에이전트 = p_klocal 의 잎. 표가 없으면 summaries() 가 [](정상), 그 밖의 오류는
        # 빈 목록 + 정리 보류(kl_).
        # Local knowledge agents (2026-09-29) — registered agents become p_klocal leaves. A missing table gives [] from summaries()
        # (normal); any other error → empty list, pruning held (kl_).
        try:
            from app import knowledge_agents as _knowledge_agents   # 지연 임포트(순환 방지) / lazy import (avoids a cycle)
            kagents = _knowledge_agents.summaries()
        except Exception:  # noqa: BLE001
            logger.warning("로컬 지식 에이전트 목록을 읽지 못했습니다(kl_* 정리 보류)", exc_info=True)
            kagents = []
            gaps.add("kl_")
        _LOADER_GAPS.clear()
        _LOADER_GAPS.update(gaps)
        catalog.set_dynamic(knowledge, workspaces, conns, wagents, kagents)
        catalog.set_extra_tables(set(pool))
        PV_TREE[:] = catalog.build_pv_tree()
        PV_NODES.clear()
        PV_PARENT.clear()
        _index(PV_TREE, None)


def descendants(node_id: str) -> list[str]:
    out: list[str] = []

    def walk(n: dict | None) -> None:
        if not n:
            return
        out.append(n["id"])
        for c in n.get("children", []):
            walk(c)

    walk(PV_NODES.get(node_id))
    return out


def _top_menu(node_id: str) -> str:
    cur = node_id
    while PV_PARENT.get(cur):
        cur = PV_PARENT[cur]
    return cur


def group_map(group: dict) -> dict[str, int]:
    """한 그룹의 부여 맵(node→0/1/2): 캐스케이드 후 그 그룹 한정 예외 적용."""
    # A single group's grant map (node→0/1/2): apply group-scoped exceptions after cascade.
    m: dict[str, int] = {}
    for gr in group.get("grants", []):
        lvl = 2 if gr.get("action") == "manage" else 1
        for nid in descendants(gr["node"]):
            if m.get(nid, 0) < lvl:
                m[nid] = lvl
    for ex in group.get("exceptions", []):
        t = ex.get("type")
        if t == "exclude":
            for nid in descendants(ex["node"]):
                m[nid] = 0
        elif t == "manage":
            m[ex["node"]] = 2
        else:
            if m.get(ex["node"], 0) < 1:
                m[ex["node"]] = 1
    return m


def menu_visible(groups: list[dict]) -> dict[str, bool]:
    s: dict[str, bool] = {}
    for g in groups:
        for mid in g.get("menus", []):
            s[mid] = True
    return s


def effective_full(member_no: int, groups: list[dict] | None = None) -> dict:
    """한 사용자의 실효 권한 + 부여 출처(그룹명) — 합집합(max) 엔진의 원본 계산.

    반환: {no, menus:{id:True}, nodes:{id:{lvl,src:[그룹명]}}, mgmt, read}
    effective() 는 이 결과에서 lvl 만 남긴 축약본이다(단일 엔진 — 미리보기=인가 일치).
    groups 를 넘기면 재조회를 생략한다(미리보기처럼 전 구성원을 한 번에 계산할 때).
    """
    # A single user's effective permissions + grant sources (group names) — the original union(max) computation.
    # Returns: {no, menus:{id:True}, nodes:{id:{lvl,src:[group names]}}, mgmt, read}
    # effective() is the lvl-only reduction of this result (one engine — preview = authorization).
    # Pass `groups` to skip the re-query (e.g. when the preview computes every member at once).
    all_groups = list_groups() if groups is None else groups
    # 그룹 멤버십 = 개인(memberIds) ∪ 부서 전체(teams) — 저장이 아니라 파생이라서
    # 부서 이동·신규 입사가 별도 마이그레이션 없이 자동 반영된다. 판정은 member_groups(단일 술어)로.
    # Group membership = individuals (memberIds) ∪ whole-team (teams) — derived, not stored,
    # so dept moves and new hires follow automatically without any migration. Resolved via member_groups.
    return {"no": member_no, **_effective_union(member_groups(member_no, all_groups))}


def effective_for_team(team: str, groups: list[dict] | None = None) -> dict:
    """팀 단위 실효 권한 — 이 팀이 '부서 전체'로 등록된 그룹들의 합집합(개인 등록 제외).

    미리보기의 팀 검색이 소비한다. 이 팀 소속 구성원은 최소 이 권한을 가지며,
    개인 등록이 있으면 그 위에 합쳐진다(합집합 엔진은 effective_full 과 동일)."""
    # Team-unit effective permissions — the union over groups where this team is registered as
    # '부서 전체' (individual registrations excluded). Consumed by the preview's team search.
    # Every member of the team holds at least this; personal registrations union on top
    # (same union engine as effective_full).
    all_groups = list_groups() if groups is None else groups
    my_groups = [g for g in all_groups if team in (g.get("teams") or [])]
    return {"team": team, **_effective_union(my_groups)}


def _effective_union(my_groups: list[dict]) -> dict:
    """매칭된 그룹들의 합집합(max) + 메뉴 게이트 — effective_full/effective_for_team 공용 코어."""
    # Union(max) over the matched groups + the menu gate — shared core of effective_full/effective_for_team.
    res: dict[str, dict] = {}
    for g in my_groups:
        gm = group_map(g)
        gname = g.get("name") or g.get("id") or ""
        for nid, lvl in gm.items():
            if not lvl:
                continue
            cur = res.get(nid)
            if cur is None or cur["lvl"] < lvl:
                res[nid] = {"lvl": lvl, "src": [gname]}
            elif cur["lvl"] == lvl and gname not in cur["src"]:
                cur["src"].append(gname)
    mv = menu_visible(my_groups)
    # 리소스 센터(m_res)는 항상 visible — 파생 모델 전환으로 '메뉴 접근' 토글이 제거됐다.
    # 리소스 센터 접근은 grant(열람)에서, 리소스 관리 콘솔은 관리(2)에서 파생된다. 따라서 m_res 는
    # 더 이상 킬 스위치가 아니다(예전엔 menus 에 m_res 없으면 아래 게이트가 리소스 노드를 전부 삭제했다).
    # m_admin 등 다른 메뉴 게이트는 그대로 유지된다.
    # Resource Center (m_res) is always visible — the '메뉴 접근' toggle was removed for the derived model.
    # Resource Center access derives from view grants and the RM console from manage(2), so m_res is no longer
    # a kill switch (previously, a missing m_res deleted every resource node in the gate below). Other menu
    # gates (m_admin, etc.) are unchanged.
    mv["m_res"] = True
    # 메뉴 게이트(축 A): 상위 메뉴가 숨김이면 그 하위 리소스는 도달 불가 → 차단
    # Menu gate (axis A): if the parent menu is hidden, its child resources are unreachable → block
    for nid in list(res.keys()):
        if not mv.get(_top_menu(nid)):
            del res[nid]
    # p_klocal(2026-09-29): 지식 관리 · Local 축 — p_know 와 별도로 판정한다(Local 만 가진 사용자의 read.p_know 는 그대로 False)
    # p_klocal (2026-09-29): the Knowledge · Local axis, judged apart from p_know (a Local-only user keeps read.p_know False)
    mgmt = {dom: any((res[nid]["lvl"] == 2) for nid in descendants(dom) if nid in res)
            for dom in ("p_know", "p_data", "p_auto", "p_klocal")}
    # read: 도메인 하위에 열람(>=1) 노드가 하나라도 있으면 True — 도메인 섹션 노출 판단(부분 grant도 포함)
    # read: True if any descendant node under the domain is readable (>=1) — used to show the domain section (covers partial grants)
    read = {dom: any((res[nid]["lvl"] >= 1) for nid in descendants(dom) if nid in res)
            for dom in ("p_know", "p_data", "p_auto", "p_conn", "p_klocal")}   # p_conn(2026-09-09): 커넥터 축 / connector axis
    return {"menus": {k: True for k in mv}, "nodes": res, "mgmt": mgmt, "read": read}


def allowed_connectors(acting_user_id: str) -> set[str] | None:
    """뷰애즈 사용자가 쓸 수 있는 커넥터 id 집합(2026-09-09). ''(슈퍼)=None(전체). 숫자 = 실효 권한에서 cn_* 노드 lvl≥1.
    p_conn 앵커 grant 는 group_map 캐스케이드로 전 커넥터에 퍼진다."""
    # Connector ids the view-as user may use (2026-09-09). '' (super) = None (all). Numeric = cn_* nodes with lvl>=1
    # in the effective permissions; a p_conn anchor grant cascades to every connector via group_map.
    aid = (acting_user_id or "").strip()
    if not aid.isdigit():
        return None
    eff = effective(int(aid))
    return {nid for nid, lvl in (eff.get("nodes") or {}).items() if str(nid).startswith("cn_") and lvl >= 1}


def effective(member_no: int) -> dict:
    """한 사용자의 실효 권한 — 소속 그룹 합집합(max) + 메뉴 게이트.

    반환: {no, menus:{id:True}, nodes:{id:lvl}, mgmt:{p_know,p_data,p_auto:bool}, read:{...}}
    계산은 effective_full 위임(엔진 단일화) — nodes 를 {id:lvl} 로 축약해 기존 계약을 유지한다.
    """
    # A single user's effective permissions — union (max) of their groups + menu gate.
    # Delegates to effective_full (single engine) and reduces nodes to {id:lvl} to keep the existing contract.
    full = effective_full(member_no)
    return {**full, "nodes": {nid: info["lvl"] for nid, info in full["nodes"].items()}}


# ─────────────────────────────────────────────────────────────────────────────
# 그룹 단위 helper — 워크플로우 그룹 종속(2026-08-18)이 소비. 멤버십 술어는 여기 한 곳이 원본이다.
# Group-unit helpers — consumed by group-scoped workflows (2026-08-18). The membership predicate
# lives here as the single source of truth.
# ─────────────────────────────────────────────────────────────────────────────

def is_member(group: dict, member_no: int, dept: str | None) -> bool:
    """멤버십 술어 — 개인 등록(memberIds) ∪ 부서 전체(teams). effective_full·preview·flows 공용."""
    # Membership predicate — individual (memberIds) ∪ whole-team (teams). Shared by effective_full/preview/flows.
    return member_no in (group.get("memberIds") or []) \
        or bool(dept and dept in (group.get("teams") or []))


def member_groups(member_no: int, groups: list[dict] | None = None) -> list[dict]:
    """사용자가 속한 권한 그룹 목록 — dept는 여기서 1회 조회한다."""
    # The permission groups a member belongs to — dept is looked up once here.
    all_groups = list_groups() if groups is None else groups
    me = next((m for m in list_members() if m.get("no") == member_no), None)
    dept = (me or {}).get("dept")
    return [g for g in all_groups if is_member(g, member_no, dept)]


def group_effective(group_id: str) -> dict | None:
    """그룹 1개의 실효 권한 — 워크플로우 편집기 팔레트·검증용. 미존재 그룹이면 None.

    nodes는 {id: lvl}로 축약해 반환한다 — catalog.allowed_*가 정수 비교를 하므로
    effective_full의 {id:{lvl,src}} 형태를 그대로 넣으면 안 된다.
    """
    # A single group's effective permissions — for the workflow editor palette and validation.
    # None for a missing group. nodes are reduced to {id: lvl} because catalog.allowed_* compares
    # integers — effective_full's {id:{lvl,src}} shape must not be passed through.
    g = next((x for x in list_groups() if x.get("id") == group_id), None)
    if g is None:
        return None
    eff = _effective_union([g])
    return {**eff, "nodes": {nid: info["lvl"] for nid, info in eff["nodes"].items()}}


def resolve_eff(acting_user_id: str) -> dict | None:
    """''/비숫자=슈퍼(None), 숫자=서버 재계산, 실패=전부 차단 — API 공용 규약의 원본.

    flows 등이 위임한다. pipeline.py의 사본은 무수정 원칙에 따라 잔존한다(동일 규약).
    """
    # ''/non-digit = super (None); digits = recomputed server-side; failure = all blocked.
    # The canonical copy of the shared API contract — flows delegates here. pipeline.py's copy
    # remains untouched per the no-edit rule (same contract).
    aid = (acting_user_id or "").strip()
    if not aid or not aid.isdigit():
        return None
    try:
        return effective(int(aid))
    except Exception:
        logger.warning("effective 조회 실패(no=%s) — 전부 차단", aid, exc_info=True)
        return {"no": None, "menus": {}, "nodes": {}, "mgmt": {},
                "read": {"p_know": False, "p_data": False, "p_auto": False}}


# ─────────────────────────────────────────────────────────────────────────────
# DB — data/ai365.db 공유. 엔티티별 1행 + JSON payload.
# DB — shares data/ai365.db. 1 row per entity + JSON payload.
# ─────────────────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_access() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS access_members(
              no INTEGER PRIMARY KEY,
              data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS access_groups(
              id TEXT PRIMARY KEY,
              ord INTEGER NOT NULL,
              data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS access_workspaces(
              id TEXT PRIMARY KEY,
              ord INTEGER NOT NULL,
              data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS access_knowledge(
              id INTEGER PRIMARY KEY CHECK(id = 1),
              data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS access_connections(
              id TEXT PRIMARY KEY,
              ord INTEGER NOT NULL,
              data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS access_csv_pool(
              tbl TEXT PRIMARY KEY,
              data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS access_meta(k TEXT PRIMARY KEY, v TEXT);
            """
        )
        # 최초 1회 시드 — 테이블별 독립(각자 비어 있을 때만 시드, 사용자 변경분은 보존)
        # Seed once on first run — independent per table (seed only when each is empty, preserve user changes)
        if conn.execute("SELECT COUNT(*) c FROM access_members").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT OR IGNORE INTO access_members(no, data) VALUES(?, ?)",
                [(m["no"], json.dumps(m, ensure_ascii=False)) for m in seed_members()],
            )
        if conn.execute("SELECT COUNT(*) c FROM access_groups").fetchone()["c"] == 0:
            # 그룹은 구성원에서 파생 — 같은 트랜잭션의 현재 구성원으로 생성(방금 시드됐든 기존이든)
            # Groups are derived from members — built from the current members in the same transaction (whether just seeded or existing)
            mrows = conn.execute("SELECT data FROM access_members ORDER BY no ASC").fetchall()
            groups = seed_groups([json.loads(r["data"]) for r in mrows])
            conn.executemany(
                "INSERT OR IGNORE INTO access_groups(id, ord, data) VALUES(?, ?, ?)",
                [(g["id"], i, json.dumps(g, ensure_ascii=False)) for i, g in enumerate(groups)],
            )
        if conn.execute("SELECT COUNT(*) c FROM access_workspaces").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT OR IGNORE INTO access_workspaces(id, ord, data) VALUES(?, ?, ?)",
                [(w["id"], i, json.dumps(w, ensure_ascii=False)) for i, w in enumerate(seed_workspaces())],
            )
        # 지식 트리(동적 유니버스 런타임 소스) — 시드는 카탈로그 상수 1회 복사(JSON 직렬화로 튜플→리스트)
        # Knowledge tree (runtime source of the dynamic universe) — seeded once from the catalog constant
        if conn.execute("SELECT COUNT(*) c FROM access_knowledge").fetchone()["c"] == 0:
            conn.execute("INSERT INTO access_knowledge(id, data) VALUES(1, ?)",
                         (json.dumps(catalog.KNOWLEDGE_TREE, ensure_ascii=False),))
        if conn.execute("SELECT COUNT(*) c FROM access_connections").fetchone()["c"] == 0:
            conn.executemany(
                "INSERT OR IGNORE INTO access_connections(id, ord, data) VALUES(?, ?, ?)",
                [(c["id"], i, json.dumps(c, ensure_ascii=False)) for i, c in enumerate(SEED_CONNECTIONS)],
            )
    # 시드 워크스페이스를 최신 카탈로그(워크스페이스별 실 CSV/테이블) 구조로 갱신. 멱등.
    # Refresh seed workspaces to the latest catalog (per-workspace real CSV/table) structure. Idempotent.
    _sync_seed_workspaces()
    # P1 데이터 노드화 마이그레이션(슬롯 노드 부여 + 시드 grant 재키잉) — 반드시 _sanitize_groups 보다 먼저.
    # 새 유니버스에는 tbl_*/ds_db/bi 노드가 없어, 먼저 sanitize 하면 tbl_hr exclude 등이 고아로
    # 삭제되어 HR 데이터가 노출된다(순서 치명적).
    # P1 data node-ization migration (assign slot nodes + re-key seed grant anchors) — MUST run before
    # _sanitize_groups: the new universe has no tbl_*/ds_db/bi nodes, so sanitizing first would drop
    # the tbl_hr excludes as orphans and expose HR data (order is critical).
    _migrate_data_nodes_v1()
    # 동적 유니버스 확정 — DB 스냅샷(지식·워크스페이스·풀) → catalog 파생맵 + PV 인덱스 재빌드
    # Finalize the dynamic universe — DB snapshot → catalog derived maps + PV index rebuild
    rebuild_universe()
    # 노드 유니버스 변경 반영 — 영속 그룹의 고아 grant/exception 정리(구 p_sec 등). 멱등.
    # (마이그레이션·리빌드 이후에만 안전)
    # Clean orphan grants/exceptions in persisted groups. Idempotent. (Safe only after migration+rebuild.)
    _sanitize_groups()
    # 팀장(og9) 지식 관리 · Local 관리 앵커 1회 이관(2026-09-29, access_meta 플래그) — sanitize 뒤에 둔다(p_klocal 은 항상 유니버스에 있다).
    # One-time Knowledge · Local manage anchor for the team lead (og9), flagged in access_meta; runs after sanitize (p_klocal is always in the universe).
    _migrate_klocal_og9_v1()
    # 데모: 홍서연 제한 권한을 정확히 1회 적용(access_meta 플래그) — 이후 관리 센터 편집은 보존.
    # Demo: apply 홍서연's limited permissions exactly once (access_meta flag) — admin-center edits afterward are preserved.
    with _conn() as conn:
        done = conn.execute("SELECT 1 FROM access_meta WHERE k = 'demo_limit_ceo_v1'").fetchone()
    if not done:
        _demo_limit_ceo()
        with _conn() as conn:
            conn.execute("INSERT OR REPLACE INTO access_meta(k, v) VALUES('demo_limit_ceo_v1', '1')")
    # 데모: 폐쇄 부서 '신사업TF' 퇴직자 2명을 정확히 1회 시드 — 조직도 관리의
    # '폐쇄된 부서 및 퇴직자' 토글 시연용. 신규 부서명이라 어떤 그룹 teams에도 없어 권한 영향 없음.
    # Demo: seed 2 retirees in the closed dept '신사업TF' exactly once — for the org-admin
    # 'closed departments & former employees' toggle. The new dept name is in no group's teams,
    # so effective permissions are unaffected.
    _seed_retired_members_v1()


def _migrate_klocal_og9_v1() -> None:
    """기존 DB 1회 이관(2026-09-29): 팀장(og9)에 {"node":"p_klocal","action":"manage"} 추가 — og9 가 p_know 관리 grant 를
    가졌고 p_klocal grant 가 아직 없을 때만(관리자가 og9 를 이미 고쳐 p_know 관리를 뺐다면 손대지 않는다). 새 DB 는 seed_groups 가 넣는다.
    One-time migration for existing DBs: add p_klocal manage to the team lead (og9) only when og9 still holds a p_know manage
    grant and has no p_klocal grant yet (an admin-edited og9 without p_know manage is left alone). New DBs get it from seed_groups."""
    with _conn() as conn:
        if conn.execute("SELECT 1 FROM access_meta WHERE k = 'klocal_og9_v1'").fetchone():
            return
    groups = list_groups()
    changed = False
    for g in groups:
        if g.get("id") != "og9":
            continue
        grants = [x for x in (g.get("grants") or []) if isinstance(x, dict)]
        has_know = any(x.get("node") == "p_know" and x.get("action") == "manage" for x in grants)
        has_klocal = any(x.get("node") == "p_klocal" for x in grants)
        if has_know and not has_klocal:
            g["grants"] = list(g.get("grants") or []) + [{"node": "p_klocal", "action": "manage"}]
            changed = True
    if changed:
        replace_groups(groups)
    with _conn() as conn:
        conn.execute("INSERT OR REPLACE INTO access_meta(k, v) VALUES('klocal_og9_v1', '1')")


def _seed_retired_members_v1() -> None:
    with _conn() as conn:
        if conn.execute("SELECT 1 FROM access_meta WHERE k = 'retired_members_v1'").fetchone():
            return
    for m in [
        {"name": "박승우", "dept": "신사업TF", "div": "경영지원본부", "grade": "책임", "role": "파트장",
         "status": "퇴직", "email": "demo-0f40e7f18b@workspace.example", "phone": "010-4021-7783",
         "tel": "02-410-2210", "empno": "2019030412", "join": "2019-03-04", "leave": "2025-12-31",
         "hist": [{"tag": "본부서 종료", "dept": "신사업TF", "role": "파트장", "date": "2019-03-04 ~ 2025-12-31"}]},
        {"name": "정예린", "dept": "신사업TF", "div": "경영지원본부", "grade": "선임", "role": "팀원",
         "status": "퇴직", "email": "demo-9af7446899@workspace.example", "phone": "010-8834-2159",
         "tel": "02-512-4432", "empno": "2021061428", "join": "2021-06-14", "leave": "2025-12-31",
         "hist": [{"tag": "본부서 종료", "dept": "신사업TF", "role": "팀원", "date": "2021-06-14 ~ 2025-12-31"}]},
    ]:
        upsert_member(m)
    with _conn() as conn:
        conn.execute("INSERT OR REPLACE INTO access_meta(k, v) VALUES('retired_members_v1', '1')")


def list_members() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT data FROM access_members ORDER BY no ASC").fetchall()
    return [json.loads(r["data"]) for r in rows]


def upsert_member(member: dict) -> dict:
    """조직도 구성원 추가. no가 없거나 이미 존재하면 max+1로 재할당(기존 구성원 덮어쓰기 방지)."""
    # Add an org-chart member. If no is missing or already exists, reassign to max+1 (prevents overwriting existing members).
    with _conn() as conn:
        no = member.get("no")
        exists = no is not None and conn.execute(
            "SELECT 1 FROM access_members WHERE no = ?", (no,)
        ).fetchone() is not None
        if no is None or exists:
            row = conn.execute("SELECT MAX(no) m FROM access_members").fetchone()
            no = (row["m"] or 0) + 1
            member["no"] = no
        # no가 비어 있음을 보장했으므로 REPLACE 불필요 — 절대 덮어쓰지 않는다
        # Since we ensured no is unused, REPLACE is unnecessary — never overwrite
        conn.execute(
            "INSERT INTO access_members(no, data) VALUES(?, ?)",
            (no, json.dumps(member, ensure_ascii=False)),
        )
    return member


def update_member(no: int, fields: dict) -> dict | None:
    """기존 구성원 부분 수정(no 불변) — 부서 이동 등이 서버 effective(팀 파생 멤버십)에 즉시 반영되도록 영속화한다."""
    # Partial update of an existing member (no immutable) — persists dept moves etc. so the server-side
    # effective engine (team-derived membership) reflects them immediately.
    with _conn() as conn:
        row = conn.execute("SELECT data FROM access_members WHERE no = ?", (no,)).fetchone()
        if not row:
            return None
        m = json.loads(row["data"])
        m.update({k: v for k, v in fields.items() if k != "no"})
        m["no"] = no
        conn.execute("UPDATE access_members SET data = ? WHERE no = ?",
                     (json.dumps(m, ensure_ascii=False), no))
    return m


def list_groups() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT data FROM access_groups ORDER BY ord ASC").fetchall()
    return [json.loads(r["data"]) for r in rows]


def replace_groups(groups: list[dict]) -> None:
    """권한 그룹 전체 교체(프론트가 변경 후 현재 배열을 통째로 PUT)."""
    # Replace all permission groups (the front-end PUTs the whole current array after changes).
    with _conn() as conn:
        conn.execute("DELETE FROM access_groups")
        conn.executemany(
            "INSERT INTO access_groups(id, ord, data) VALUES(?, ?, ?)",
            [(g.get("id", "g" + str(i)), i, json.dumps(g, ensure_ascii=False)) for i, g in enumerate(groups)],
        )


def _sanitize_groups() -> int:
    """영속 그룹에서 현재 노드 유니버스(PV_NODES)에 없는 grant/exception 제거(고아 정리, 예: 구 p_sec 보안).
    마지막 재구축에서 읽지 못한 동적 축(_LOADER_GAPS 접두사)의 항목은 남긴다(2026-09-29)."""
    # Strip grants/exceptions referencing nodes not in the current universe (PV_NODES) from persisted groups (orphan cleanup, e.g. old p_sec security).
    # Items of a dynamic axis that failed to load on the last rebuild (_LOADER_GAPS prefixes) are kept (2026-09-29).
    gaps = tuple(_LOADER_GAPS)

    def keep(x: dict) -> bool:
        node = str(x.get("node") or "")
        return node in PV_NODES or bool(gaps and node.startswith(gaps))

    groups = list_groups()
    n = 0
    for g in groups:
        gr = [x for x in g.get("grants", []) if keep(x)]
        ex = [x for x in g.get("exceptions", []) if keep(x)]
        if len(gr) != len(g.get("grants", [])) or len(ex) != len(g.get("exceptions", [])):
            g["grants"], g["exceptions"] = gr, ex
            n += 1
    if n:
        replace_groups(groups)
    return n


def _sync_seed_workspaces() -> int:
    """시드 워크스페이스(ws_fin/sales/pmo/ai)가 구버전 구조(원본에 table 매핑 없음)면 최신 카탈로그로 갱신.
    사용자가 추가한 워크스페이스(시드 외 id)는 보존. 멱등(이미 최신이면 무변경)."""
    # If seed workspaces are old-structured (sources lack the table mapping), refresh them to the latest catalog.
    # Preserve user-added workspaces (non-seed ids). Idempotent (no-op if already current).
    seed = {w["id"]: w for w in seed_workspaces()}
    cur = list_workspaces()
    out, changed, seen = [], False, set()
    for w in cur:
        wid = w.get("id")
        seen.add(wid)
        csv_items = w.get("csv") or []
        # 시드 워크스페이스인데 csv 원본이 있고 그중 table 매핑이 빠진 게 있으면 구버전 → 갱신.
        # (빈 csv는 사용자가 비운 것일 수 있어 구버전으로 보지 않음 — 매 부팅 리셋 방지)
        # Old-structured = a seed workspace with csv sources where some lack a table mapping.
        # (Empty csv may be user-cleared → not treated as old, to avoid resetting it every boot.)
        is_old = wid in seed and bool(csv_items) and not all(c.get("table") for c in csv_items)
        if is_old:
            out.append(seed[wid])
            changed = True
        else:
            out.append(w)
    for wid, w in seed.items():
        if wid not in seen:
            out.append(w)
            changed = True
    if changed:
        replace_workspaces(out)
    return 1 if changed else 0


def _migrate_data_nodes_v1() -> None:
    """P1 데이터 노드화 마이그레이션 — 슬롯 노드 부여 + 시드 grant 앵커 재키잉. access_meta 멱등.

    새 유니버스는 p_data → ws_* → 슬롯 leaf 이고 구 앵커(tbl_*/ds_db/bi/bi_*)는 노드가 아니므로,
    기존 그룹의 해당 grant/exception 을 같은 물리 자원을 참조하는 슬롯 노드들로 옮긴다.
    p_know/p_data 등 도메인·폴더·파일(kf_*) grant 는 무수정(캐스케이드 자연 전파)."""
    # P1 data node-ization migration — assign slot nodes + re-key seed grant anchors. Idempotent via access_meta.
    # The new universe is p_data → ws_* → slot leaves; old anchors (tbl_*/ds_db/bi/bi_*) are no longer nodes,
    # so matching grants/exceptions are moved onto the slot nodes referencing the same physical resource.
    # Domain/folder/file (kf_*) grants are untouched (cascade propagates naturally).
    with _conn() as conn:
        done = conn.execute("SELECT 1 FROM access_meta WHERE k = 'data_nodes_v1'").fetchone()
    if done:
        return
    ws = list_workspaces()
    if catalog.assign_slot_nodes(ws):
        replace_workspaces(ws)
        ws = list_workspaces()
    # 물리 자원 → 그것을 참조하는 슬롯 노드들 / physical resource → slot nodes referencing it
    table_nodes: dict[str, list[str]] = {}
    bi_nodes: dict[str, list[str]] = {}
    for w in ws:
        for it in (w.get("sql") or []) + (w.get("csv") or []):
            if it.get("node") and it.get("table"):
                table_nodes.setdefault(it["table"], []).append(it["node"])
        for it in (w.get("bi") or []):
            if it.get("node") and it.get("file"):
                bi_nodes.setdefault(it["file"], []).append(it["node"])
    seed_tbl = {tid: tbl for tid, _, tbl in catalog.DATA_TABLES}   # 예: tbl_hr → hr_employees
    seed_bi = {bid: f for bid, _, f in catalog.DATA_BI}
    all_table_slots = sorted({n for ns in table_nodes.values() for n in ns})
    all_bi_slots = sorted({n for ns in bi_nodes.values() for n in ns})

    def _rekey(items: list[dict] | None) -> tuple[list[dict], bool]:
        out: list[dict] = []
        seen: set[tuple] = set()
        changed = False

        def push(d: dict) -> None:
            key = (d.get("node"), d.get("action"), d.get("type"))
            if key in seen:
                return
            seen.add(key)
            out.append(d)

        for item in items or []:
            nid = item.get("node")
            if nid == "ds_db":
                for slot in all_table_slots:
                    push({**item, "node": slot})
                changed = True
            elif nid == "bi":
                # 'bi' 폴더 앵커(예: 데이터 분석가 manage) → 현존 BI 슬롯 전부. 이후 추가되는 BI 슬롯엔
                # 자동 승계되지 않음 — 데모 한계(필요 시 ws 단위 manage 로 대체 부여).
                # The 'bi' folder anchor maps to all current BI slots; NOT auto-inherited by future BI slots
                # — a demo limitation (grant ws-level manage instead if needed).
                for slot in all_bi_slots:
                    push({**item, "node": slot})
                changed = True
            elif nid in seed_tbl:
                for slot in table_nodes.get(seed_tbl[nid], []):
                    push({**item, "node": slot})
                changed = True  # 매핑 불가(참조 슬롯 없음)면 제거 / dropped if no slot references it
            elif nid in seed_bi:
                for slot in bi_nodes.get(seed_bi[nid], []):
                    push({**item, "node": slot})
                changed = True
            else:
                push(item)
        return out, changed

    groups = list_groups()
    any_changed = False
    for g in groups:
        gr, c1 = _rekey(g.get("grants"))
        ex, c2 = _rekey(g.get("exceptions"))
        if c1 or c2:
            g["grants"], g["exceptions"] = gr, ex
            any_changed = True
    if any_changed:
        replace_groups(groups)
    with _conn() as conn:
        conn.execute("INSERT OR REPLACE INTO access_meta(k, v) VALUES('data_nodes_v1', '1')")


def _demo_limit_ceo() -> None:
    """데모: 홍서연(대표이사 표준 그룹의 유일 멤버)에 제한 권한 부여 — 사용자 전환 시 마스킹 시연용.
    홈·채팅·리소스 센터 + 지식 관리 열람만(컬렉션·관리 센터·데이터 분석·업무 자동화 제외)."""
    # Demo: grant 홍서연 (sole member of the 대표이사 표준 group) limited permissions to showcase masking on user switch.
    # Home·Chat·Resource Center + Knowledge view only (excludes Collections·Admin Center·Data Analysis·Work Automation).
    groups = list_groups()
    for g in groups:
        if g.get("name") == "대표이사 표준":
            g["menus"] = ["m_home", "m_chat", "m_res"]
            g["grants"] = [{"node": "p_know", "action": "view"}]
            g["exceptions"] = []
    replace_groups(groups)


def list_workspaces() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT data FROM access_workspaces ORDER BY ord ASC").fetchall()
    return [json.loads(r["data"]) for r in rows]


def replace_workspaces(workspaces: list[dict]) -> None:
    # 슬롯 항목에 권한 노드가 없으면 자동 부여(구버전 프론트 PUT 로도 노드 유실 없게) 후 저장 → 유니버스 리빌드
    # Auto-assign permission nodes to slot items lacking one (so legacy frontend PUTs never lose nodes),
    # save, then rebuild the universe.
    catalog.assign_slot_nodes(workspaces)
    with _conn() as conn:
        conn.execute("DELETE FROM access_workspaces")
        conn.executemany(
            "INSERT INTO access_workspaces(id, ord, data) VALUES(?, ?, ?)",
            [(w.get("id", "ws" + str(i)), i, json.dumps(w, ensure_ascii=False)) for i, w in enumerate(workspaces)],
        )
    rebuild_universe()


def load_knowledge() -> list[dict]:
    """지식 트리(동적 유니버스 런타임 소스) 로드 — 미시드 시 카탈로그 상수 폴백(JSON 복사본)."""
    # Load the knowledge tree (runtime source of the dynamic universe) — falls back to a JSON copy of the seed constant.
    with _conn() as conn:
        row = conn.execute("SELECT data FROM access_knowledge WHERE id = 1").fetchone()
    return json.loads(row["data"]) if row else json.loads(json.dumps(catalog.KNOWLEDGE_TREE, ensure_ascii=False))


def save_knowledge(tree: list[dict]) -> None:
    with _conn() as conn:
        conn.execute("INSERT OR REPLACE INTO access_knowledge(id, data) VALUES(1, ?)",
                     (json.dumps(tree, ensure_ascii=False),))
    rebuild_universe()


def list_connections() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT data FROM access_connections ORDER BY ord ASC").fetchall()
    return [json.loads(r["data"]) for r in rows]


def replace_connections(conns: list[dict]) -> None:
    """데이터셋 연결 카드 전체 교체(슈퍼 전용 — 강제는 API 계층에서)."""
    # Replace all dataset-connection cards (super-only — enforced at the API layer).
    with _conn() as conn:
        conn.execute("DELETE FROM access_connections")
        conn.executemany(
            "INSERT INTO access_connections(id, ord, data) VALUES(?, ?, ?)",
            [(c.get("id", "conn" + str(i)), i, json.dumps(c, ensure_ascii=False)) for i, c in enumerate(conns)],
        )


def list_csv_pool() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT data FROM access_csv_pool").fetchall()
    return [json.loads(r["data"]) for r in rows]


def add_csv_pool(entry: dict) -> None:
    """CSV 풀(스테이징) 항목 기록 — 노드 없음(큐레이션 전 미노출), SQL 가드 유니버스에는 포함."""
    # Record a CSV-pool (staging) entry — no node (invisible until curated) but included in the SQL-guard universe.
    with _conn() as conn:
        conn.execute("INSERT OR REPLACE INTO access_csv_pool(tbl, data) VALUES(?, ?)",
                     (entry.get("table"), json.dumps(entry, ensure_ascii=False)))
    rebuild_universe()


def org_tree() -> list[dict]:
    """ORG_DEF 구조에 멤버 수(부서별)를 반영해 반환(추가된 구성원까지 정합)."""
    # Return the ORG_DEF structure with member counts (per department) applied (consistent even with added members).
    counts: dict[str, int] = {}
    for m in list_members():
        counts[m["dept"]] = counts.get(m["dept"], 0) + 1
    tree = []
    for top in ORG_DEF:
        if top.get("leaf"):
            tree.append({**top, "cnt": counts.get(top["name"], 0)})
        else:
            tree.append({**top, "children": [
                {**ch, "cnt": counts.get(ch["name"], 0)} for ch in top["children"]
            ]})
    return tree


def bootstrap() -> dict:
    return {
        "members": list_members(),
        "teams": TEAMS,
        "tree": org_tree(),
        "groups": list_groups(),
        "workspaces": list_workspaces(),
        # 실제 리소스 카탈로그(권한 노드 = 실파일/테이블) — 프론트 리소스 트리·권한 트리 하이드레이션용
        # Real resource catalog (permission nodes = real files/tables) — for frontend resource/permission tree hydration
        "knowledge": catalog.knowledge_tree(),
        "datasets": catalog.datasets(),
        # P3: 연결 카드(슈퍼 전용 UI)·CSV 풀(스테이징)·물리 테이블 카탈로그(DB 슬롯 폼의 any-table 선택지)
        # P3: connection cards (super-only UI), CSV pool (staging), physical-table catalog (any-table choices for the DB slot form)
        "connections": list_connections(),
        "csv_pool": list_csv_pool(),
        "tables_catalog": sorted(catalog.all_table_names()),
        "pvtree": PV_TREE,
    }
