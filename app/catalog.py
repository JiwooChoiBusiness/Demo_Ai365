"""리소스 카탈로그 — 권한 노드 ↔ 실제 리소스(파일/테이블/BI) 단일 매핑.

목적: '보이는 리소스 트리 = 실제 인덱싱된 파일/적재된 테이블 = 권한 노드'를 한 곳에서 정의한다.
- 지식 관리: data/knowledge/ 의 실제 PDF를 LV.1~3 중첩 폴더로 묶고 각 파일에 노드 id 부여.
- 데이터 분석: DuckDB 테이블(시드 2 + CSV 뷰) + BI 4종에 노드 id 부여(게이팅 유니버스).
  · 프론트 표시용 워크스페이스(재무/영업/경영/연구·AI)는 access.seed_workspaces 가 이 매핑으로 생성.
- access.py 의 PV_TREE(권한 유니버스)는 이 카탈로그에서 생성된다(build_pv_tree).
- 챗봇 게이팅(Phase 3)은 effective(no).nodes 와 NODE_FILE/NODE_TABLE 역참조로 허용 집합을 만든다.

설계 메모: grants 호환을 위해 앵커 노드 id(p_know·p_data·p_auto·f_hr·tbl_hr·bi·m_*)는 유지한다.
"""
# Resource catalog — single mapping of permission nodes ↔ real resources (files/tables/BI). See Korean docstring above.

import re

# ─────────────────────────────────────────────────────────────────────────────
# 지식 관리 — LV.1~3 중첩 폴더 → 실제 PDF (folders[]/files[] 재귀 구조)
# Knowledge — LV.1~3 nested folders → real PDFs (recursive folders[]/files[] structure)
# 폴더: {"id","label","folders":[...], "files":[(file_node_id, pdf_filename), ...]}
# ─────────────────────────────────────────────────────────────────────────────
KNOWLEDGE_TREE: list[dict] = [
    {"id": "f_hr", "label": "인사·총무", "folders": [
        {"id": "f_hr_rule", "label": "규정", "files": [
            ("kf_hr_rule", "상세_가상_IT회사_인사규정_2022.pdf"),
            ("kf_company_rule", "A사 사내규정.pdf"),
            ("kf_attendance", "근태_취업규칙.pdf"),
            ("kf_travel", "출장경비_처리규정.pdf"),
        ]},
        {"id": "f_hr_recruit", "label": "채용", "files": [
            ("kf_recruit_notice", "2026_상반기_채용공고.pdf"),
            ("kf_interview", "면접_평가_가이드.pdf"),
        ], "folders": [
            {"id": "f_hr_onboard", "label": "온보딩", "files": [
                ("kf_onboard", "신입_온보딩_체크리스트.pdf"),
            ]},
        ]},
    ]},
    {"id": "f_welfare", "label": "복리후생", "files": [
        ("kf_welfare", "임직원_복리후생_안내.pdf"),
        ("kf_club", "사내_동호회_지원_안내.pdf"),
    ]},
    {"id": "f_security", "label": "정보보안·컴플라이언스", "files": [
        ("kf_infosec", "정보보안_정책_v1.pdf"),
        ("kf_privacy", "개인정보_처리방침_컴플라이언스.pdf"),
        ("kf_incident", "정보보안_사고대응_절차.pdf"),
    ]},
    {"id": "f_mgmt_kpi", "label": "경영지표", "files": [
        ("kf_kpi_a", "A사 경영지표.pdf"),
        ("kf_kpi_b", "경쟁사 B사 경영지표.pdf"),
    ]},
    {"id": "f_product", "label": "제품 자료", "folders": [
        {"id": "f_prod_boiler", "label": "보일러", "files": [
            ("kf_cat_boiler1", "가스보일러_종합_카탈로그_58p_20260327.pdf"),
            ("kf_cat_boiler2", "카탈로그_가스보일러 종합_221213-i.pdf"),
            ("kf_cat_ncb314", "카탈로그_NCB314_8p_240307.pdf"),
            ("kf_cat_smarttok", "카타로그_나비엔 콘덴싱 스마트 톡_161001.pdf"),
            ("kf_cat_heater", "중대형, 진공 온수히터 합본_12p_230706.pdf"),
        ]},
        {"id": "f_prod_vent", "label": "환기·청정", "files": [
            ("kf_cat_vent1", "8. 카세트형 환기청정기 카탈로그_20p_250120.pdf"),
            ("kf_cat_vent2", "각실 환기청정기 키친플러스 카탈로그_B2C_28p_240202.pdf"),
        ]},
        {"id": "f_prod_policy", "label": "정책", "files": [
            ("kf_warranty", "제품보증_AS정책.pdf"),
            ("kf_install", "제품_설치_가이드.pdf"),
        ]},
    ]},
    {"id": "f_it_policy", "label": "IT·정책", "folders": [
        {"id": "f_it_tech", "label": "기술", "files": [
            ("kf_api", "API_Usage_Guide_EN.pdf"),
            ("kf_sla", "Cloud_Service_SLA_EN.pdf"),
            ("kf_platform", "[MCloudBridge] Why Ai 365 Orchestration Platform_v22.pdf"),
        ]},
        {"id": "f_it_pol", "label": "정책", "files": [
            ("kf_remote", "Remote_Work_Policy_EN.pdf"),
            ("kf_conduct", "Business_Code_of_Conduct_EN.pdf"),
        ]},
    ]},
]

# ─────────────────────────────────────────────────────────────────────────────
# 데이터 분석 — DuckDB 테이블 노드(게이팅 유니버스) + BI 노드
# Data — DuckDB table nodes (gating universe) + BI nodes
# (table_node_id, label, duckdb_table_name) — tbl_hr 는 grants 예외 호환 위해 id 유지
# ─────────────────────────────────────────────────────────────────────────────
DATA_TABLES: list[tuple[str, str, str]] = [
    ("tbl_hr", "HR_EMPLOYEES (인사)", "hr_employees"),
    ("tbl_budget", "DEPT_BUDGET (부서예산)", "dept_budget"),
    ("tbl_pos", "POS_SALES (월매출)", "pos_sales"),
    ("tbl_finance", "FINANCE_EXPENSES (비용)", "finance_expenses"),
    ("tbl_fin_ledger", "FINANCE_LEDGER_2024 (결산원장)", "finance_ledger_2024"),
    ("tbl_fin_budget", "FINANCE_BUDGET_ACTUAL (예산집행)", "finance_budget_actual"),
    ("tbl_sales", "SALES_BRANCH_MONTHLY (지점매출)", "sales_branch_monthly"),
    ("tbl_sales_pipe", "SALES_PIPELINE (영업파이프라인)", "sales_pipeline"),
    ("tbl_marketing", "MARKETING_CAMPAIGNS (마케팅)", "marketing_campaigns"),
    ("tbl_orders", "LUMICART_ORDERS_RAW (주문)", "lumicart_orders_raw"),
    ("tbl_order_items", "LUMICART_ORDER_ITEMS_RAW (주문상세)", "lumicart_order_items_raw"),
    ("tbl_customers", "LUMICART_CUSTOMERS_RAW (고객)", "lumicart_customers_raw"),
    ("tbl_products", "LUMICART_PRODUCTS_RAW (상품)", "lumicart_products_raw"),
    ("tbl_dict", "LUMICART_DATA_DICTIONARY (데이터사전)", "lumicart_data_dictionary"),
    ("tbl_mgmt", "MANAGEMENT (경영)", "management"),
    ("tbl_kpi", "KPI_MONTHLY (월간KPI)", "kpi_monthly"),
    ("tbl_project", "PROJECT_STATUS (과제현황)", "project_status"),
    ("tbl_support", "SUPPORT_TICKETS (고객지원)", "support_tickets"),
    ("tbl_research", "RESEARCH (연구)", "research"),
    ("tbl_rnd", "RND_EXPERIMENTS (연구실험)", "rnd_experiments"),
    ("tbl_quality", "QUALITY (품질)", "quality"),
    ("tbl_production", "PRODUCTION (생산)", "production"),
    ("tbl_inventory", "INVENTORY_STOCK (재고)", "inventory_stock"),
]

# (bi_node_id, label, bi_filename)
DATA_BI: list[tuple[str, str, str]] = [
    ("bi_mgmt", "경영 대시보드", "경영Dashboard.png"),
    ("bi_prod", "생산 대시보드", "생산Dashboard.png"),
    ("bi_rnd", "연구 대시보드", "연구Dashboard.png"),
    ("bi_qa", "품질 대시보드", "품질Dashboard.png"),
]

# 업무 자동화 — 기본 제공 에이전트(노드 id 유지, p_auto grant 호환). 교육 에이전트 추가(2026-08-19).
# 2026-09-28: agent_email 은 M코스메틱 이메일 에이전트로 대체(id 는 그대로 — 권한·워크플로우 호환, 라벨만 변경).
# Work automation — built-in agents (node ids stable, p_auto-grant compatible). Education agent added 2026-08-19.
# 2026-09-28: agent_email is now the M Cosmetic Email Agent (same id for permission and workflow compatibility; label only).
WORK_AGENTS: list[tuple[str, str]] = [
    ("agent_email", "M코스메틱 이메일 에이전트"),
    ("agent_edu", "교육 에이전트"),
]

# ─────────────────────────────────────────────────────────────────────────────
# 데이터 분석 워크스페이스(프론트 표시 + 권한 트리) — access.seed_workspaces 가 이걸로 생성.
# 각 항목: (원본_label, duckdb_table_or_bi_file)  — csv/sql 은 테이블, bi 는 BI 파일.
# Data-analysis workspaces (frontend display + permission tree) — built by access.seed_workspaces from this.
# Each item: (source_label, duckdb_table_or_bi_file) — csv/sql → table, bi → BI file.
# ─────────────────────────────────────────────────────────────────────────────
DATA_WORKSPACES: list[dict] = [
    {"id": "ws_fin", "name": "재무 그룹", "team": "재무회계파트", "desc": "재무·회계 데이터 분석",
     "bi": [("월간 손익 대시보드", "경영Dashboard.png")],
     "csv": [("2024_결산_원장", "finance_ledger_2024"), ("예산_집행_실적", "finance_budget_actual"),
             ("비용_집행_내역", "finance_expenses")],
     "sql": [("월매출_집계", "pos_sales"), ("부서_예산_집행", "dept_budget"), ("HR_급여", "hr_employees")]},
    {"id": "ws_sales", "name": "영업 그룹", "team": "영업관리파트", "desc": "영업·매출 데이터 분석",
     "bi": [],
     "csv": [("지점별_월매출", "sales_branch_monthly"), ("영업_파이프라인", "sales_pipeline"),
             ("마케팅_캠페인", "marketing_campaigns"), ("주문_내역", "lumicart_orders_raw")],
     "sql": [("고객_마스터", "lumicart_customers_raw"), ("주문_상세", "lumicart_order_items_raw"),
             ("상품_마스터", "lumicart_products_raw")]},
    {"id": "ws_pmo", "name": "경영 그룹", "team": "PMO파트", "desc": "경영지표·KPI 데이터 분석",
     "bi": [("경영 KPI 대시보드", "경영Dashboard.png")],
     "csv": [("과제_관리", "management"), ("월간_KPI", "kpi_monthly"), ("과제_현황", "project_status")],
     "sql": [("고객지원_티켓", "support_tickets"), ("데이터_사전", "lumicart_data_dictionary")]},
    {"id": "ws_ai", "name": "연구·AI 그룹", "team": "AI 파트", "desc": "연구개발·품질 데이터 분석",
     "bi": [("연구 과제 대시보드", "연구Dashboard.png"), ("품질 모니터링", "품질Dashboard.png"),
            ("생산 모니터링", "생산Dashboard.png")],
     "csv": [("연구_과제", "research"), ("연구_실험", "rnd_experiments"), ("품질_검사", "quality")],
     "sql": [("생산_실적", "production"), ("재고_현황", "inventory_stock")]},
]


# ─────────────────────────────────────────────────────────────────────────────
# 파생 매핑(역참조용) — 게이팅에서 사용
# Derived maps (for reverse lookup) — used by gating
# ─────────────────────────────────────────────────────────────────────────────

def _walk_kn(nodes, cb):
    for n in nodes:
        for fid, fname in n.get("files", []):
            cb(fid, fname)
        if n.get("folders"):
            _walk_kn(n["folders"], cb)


# 시드 물리 테이블명(불변) — analytics.register_csv 의 시드 덮어쓰기 방지 가드에 사용.
# Immutable seed table names — used by analytics.register_csv to protect seed tables from overwrite.
SEED_TABLE_NAMES: frozenset = frozenset(tbl for _, _, tbl in DATA_TABLES)

# ── 동적 유니버스 상태 (P1) ──
# 런타임 소스는 DB(access_knowledge/access_workspaces)이고 위 상수들은 "시드 정의"다.
# access.rebuild_universe() 가 set_dynamic() 으로 DB 스냅샷을 주입하면 아래 파생맵을 in-place 재빌드한다
# (소비처들은 모듈 dict '객체'를 참조하므로 재할당 없이 내용만 갱신 — 기존 코드 무수정 호환).
# ── Dynamic universe state (P1) ──
# The runtime source is the DB; the constants above are seed definitions. access.rebuild_universe()
# injects a DB snapshot via set_dynamic(), which rebuilds the derived maps below in place
# (consumers hold references to the module dict objects, so contents change without reassignment).
_dyn: dict = {"knowledge": None, "workspaces": None, "connectors": None, "work_agents": None, "knowledge_agents": None}   # work_agents(2026-09-22): 등록된 업무 자동화 에이전트 [{id, name}] — p_auto 의 동적 잎 / dynamic p_auto leaves   # connectors(2026-09-09): [{id, name}] — 권한 축 p_conn 의 leaf / leaves of the p_conn axis
# knowledge_agents(2026-09-29): 로컬 지식 에이전트 [{id, name}] — p_klocal 의 잎 / local knowledge agents, the p_klocal leaves
_extra_tables: set = set()  # 유니버스 밖 실테이블(CSV 풀 스테이징 등) — SQL 가드 유니버스 포함용

NODE_FILE: dict[str, str] = {}    # 파일 노드 → PDF 파일명
FILE_NODE: dict[str, str] = {}    # 역맵
NODE_TABLE: dict[str, str] = {}   # 슬롯 노드 → DuckDB 테이블명(같은 테이블이 여러 슬롯일 수 있음 — 다:1)
TABLE_NODE: dict[str, str] = {}   # 역맵(대표 1개) — 시드 보호 판정은 SEED_TABLE_NAMES 를 쓸 것
NODE_BI: dict[str, str] = {}      # 슬롯 노드 → BI 파일명
BI_NODE: dict[str, str] = {}      # 역맵(대표 1개)


def _active_knowledge() -> list[dict]:
    return _dyn["knowledge"] if _dyn["knowledge"] is not None else KNOWLEDGE_TREE


def _active_workspaces() -> list[dict]:
    if _dyn["workspaces"] is not None:
        return _dyn["workspaces"]
    ws = seed_workspaces_data()
    assign_slot_nodes(ws)
    return ws


def _slot_slug(phys: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", str(phys or "")).strip("_").lower()


def assign_slot_nodes(workspaces: list[dict]) -> bool:
    """워크스페이스 슬롯 항목에 권한 노드 id가 없으면 결정적으로 부여(sl_{ws}_{kind}_{slug}). 변경 여부 반환.

    슬롯 노드 = 권한이 걸리는 큐레이션 항목(물리 자원 아님). 같은 물리 테이블/BI가 워크스페이스마다
    별도 노드를 갖는다(부서별 차등 허용의 기반)."""
    # Assign deterministic permission-node ids (sl_{ws}_{kind}_{slug}) to slot items lacking one. Returns whether changed.
    # A slot node is the permission-bearing curated item (not the physical resource); the same table/BI gets
    # a distinct node per workspace (the basis for per-department differentiation).
    used = {it.get("node") for w in workspaces for k in ("bi", "csv", "sql")
            for it in (w.get(k) or []) if it.get("node")}
    changed = False
    for w in workspaces:
        wid = str(w.get("id") or "ws")
        for kind in ("bi", "csv", "sql"):
            for i, it in enumerate(w.get(kind) or []):
                if it.get("node"):
                    continue
                phys = it.get("file") if kind == "bi" else it.get("table")
                base = f"sl_{wid}_{kind}_{_slot_slug(phys) or i}"
                nid, n = base, 1
                while nid in used:
                    n += 1
                    nid = f"{base}-{n}"
                used.add(nid)
                it["node"] = nid
                changed = True
    return changed


def set_dynamic(knowledge: list[dict] | None, workspaces: list[dict] | None,
                connectors: list[dict] | None = None, work_agents: list[dict] | None = None,
                knowledge_agents: list[dict] | None = None) -> None:
    """DB 스냅샷 주입 → 파생맵 in-place 재빌드. access.rebuild_universe() 가 호출한다.
    connectors(2026-09-09) = 등록된 커넥터 [{id, name}] — 권한 유니버스의 p_conn 하위 노드가 된다.
    knowledge_agents(2026-09-29) = 로컬 지식 에이전트 [{id, name}] — p_klocal 하위 노드(기본값 None: 인자 2개 호출 호환)."""
    # Inject a DB snapshot → rebuild the derived maps in place. Called by access.rebuild_universe().
    # connectors (2026-09-09) = registered connectors [{id, name}] — become the p_conn children of the universe.
    # knowledge_agents (2026-09-29) = local knowledge agents [{id, name}] — the p_klocal children (default None keeps two-arg calls working).
    _dyn["knowledge"] = knowledge
    _dyn["workspaces"] = workspaces
    _dyn["connectors"] = connectors
    _dyn["work_agents"] = work_agents   # 업무 자동화 에이전트(2026-09-22): 등록분 [{id, name}] → p_auto 의 잎(기본 제공 뒤) / registered work agents → p_auto leaves after the built-ins
    _dyn["knowledge_agents"] = knowledge_agents
    kt, ws = _active_knowledge(), _active_workspaces()
    NODE_FILE.clear()
    _walk_kn(kt, lambda fid, fname: NODE_FILE.__setitem__(fid, fname))
    FILE_NODE.clear()
    FILE_NODE.update({v: k for k, v in NODE_FILE.items()})
    NODE_TABLE.clear()
    NODE_BI.clear()
    for w in ws:
        for it in (w.get("sql") or []) + (w.get("csv") or []):
            if it.get("node") and it.get("table"):
                NODE_TABLE[it["node"]] = it["table"]
        for it in (w.get("bi") or []):
            if it.get("node") and it.get("file"):
                NODE_BI[it["node"]] = it["file"]
    TABLE_NODE.clear()
    TABLE_NODE.update({tbl: nid for nid, tbl in NODE_TABLE.items()})
    BI_NODE.clear()
    BI_NODE.update({fname: nid for nid, fname in NODE_BI.items()})


def set_extra_tables(names: set) -> None:
    """유니버스 밖 실테이블(CSV 풀 스테이징 등) 등록 — all_table_names() 의 SQL 가드 유니버스에 포함."""
    # Register real tables outside the universe (e.g. CSV-pool staging) — included in all_table_names() for the SQL guard.
    _extra_tables.clear()
    _extra_tables.update(names)


def all_work_agents() -> list[tuple[str, str]]:
    """업무 자동화 축의 에이전트 전부 = 기본 제공(WORK_AGENTS) + 리소스 관리에서 등록한 것(2026-09-22, id 는 agent_*).
    권한 트리·도메인 열람 판정이 이 목록을 쓴다."""
    # Every agent on the automation axis = built-ins (WORK_AGENTS) + those registered in Resource Management
    # (2026-09-22, ids agent_*). The permission tree and domain readability use this list.
    seen = {aid for aid, _ in WORK_AGENTS}
    out = list(WORK_AGENTS)
    for a in (_dyn.get("work_agents") or []):
        aid = str(a.get("id") or "")
        if aid and aid not in seen:
            seen.add(aid)
            out.append((aid, str(a.get("name") or aid)))
    return out


def _kn_pv(nodes: list[dict]) -> list[dict]:
    """지식 폴더 → PV_TREE 노드(재귀)."""
    out = []
    for n in nodes:
        children = []
        if n.get("folders"):
            children.extend(_kn_pv(n["folders"]))
        for fid, fname in n.get("files", []):
            children.append({"id": fid, "label": fname, "kind": "file"})
        out.append({"id": n["id"], "label": n["label"], "kind": "folder", "children": children})
    return out


def build_pv_tree() -> list[dict]:
    """카탈로그 → 권한 유니버스(PV_TREE). access.py 가 소비한다.

    데이터 서브트리는 P1 노드화로 `p_data → 워크스페이스(ws_*) → 슬롯 leaf` 구조다
    (기존 ds_db/bi 폴더 노드는 폐지 — 시드 grant 는 access._migrate_data_nodes_v1 이 재키잉)."""
    # The data subtree is `p_data → workspace (ws_*) → slot leaves` after the P1 node-ization
    # (the old ds_db/bi folder nodes are retired — seed grants are re-keyed by access._migrate_data_nodes_v1).
    data_children = []
    for w in _active_workspaces():
        children = []
        for kind, tag in (("bi", "BI"), ("sql", "DB"), ("csv", "CSV")):
            for it in (w.get(kind) or []):
                if not it.get("node"):
                    continue
                children.append({"id": it["node"], "label": f"{it.get('name', '')} ({tag})", "kind": "file"})
        data_children.append({"id": str(w.get("id")), "label": w.get("name", ""), "kind": "folder",
                              "children": children})
    return [
        {"id": "m_home", "label": "홈", "kind": "menu"},
        {"id": "m_chat", "label": "채팅", "kind": "menu"},
        {"id": "m_coll", "label": "컬렉션", "kind": "menu"},
        {"id": "m_res", "label": "리소스 센터", "kind": "menu", "children": [
            {"id": "p_know", "label": "지식 관리", "kind": "page", "children": _kn_pv(_active_knowledge())},
            # 지식 관리 · Local(2026-09-29): 로컬 지식 에이전트 1개 = 잎 1개(id 는 에이전트 id kl_*). 에이전트가 없어도 노드는 항상 둔다
            # (앵커 grant 가 부팅 sanitize 에 지워지지 않게). p_know 와 별도 축이라 채팅 · 컴포저의 지식 판정은 그대로다.
            # Knowledge · Local (2026-09-29): one leaf per local knowledge agent (node id = agent id kl_*). The node is always present,
            # even with no agents, so anchor grants survive the boot-time sanitize. A separate axis from p_know: chat and composer
            # knowledge gating are unchanged.
            {"id": "p_klocal", "label": "지식 관리 · Local", "kind": "page",
             "children": [{"id": str(a.get("id")), "label": str(a.get("name") or a.get("id")), "kind": "file"}
                          for a in (_dyn.get("knowledge_agents") or []) if a.get("id")]},
            {"id": "p_data", "label": "데이터 분석", "kind": "page", "children": data_children},
            {"id": "p_auto", "label": "업무 자동화", "kind": "page",
             "children": [{"id": aid, "label": label, "kind": "file"} for aid, label in all_work_agents()]},   # 등록 에이전트 포함(2026-09-22) / includes registered agents
            # 커넥터 축(2026-09-09): 등록된 커넥터 1개 = leaf 1개(id 는 커넥터 id cn_*). 앵커 p_conn grant 는 전체에 캐스케이드.
            # Connector axis (2026-09-09): one leaf per registered connector (node id = connector id cn_*); a p_conn grant cascades to all.
            {"id": "p_conn", "label": "API", "kind": "page",
             "children": [{"id": str(c.get("id")), "label": str(c.get("name") or c.get("id")), "kind": "file"}
                          for c in (_dyn.get("connectors") or []) if c.get("id")]},
            # 게시판 축(p_board › bd_all·bd_g_<id>, 2026-09-14~2026-09-22)은 폐지 — 게시판 접근은 boards_api 의 고정 규칙(슈퍼 전부 /
            # 전체 게시판은 읽기만 / 그룹 게시판은 소속 구성원)이 정하고, 남아 있던 bd_* grant 는 부팅 때 _sanitize_groups 가 걷어 낸다.
            # The board axis (p_board › bd_all/bd_g_<id>, 2026-09-14 to 2026-09-22) is retired — board access is the fixed rule in
            # boards_api (super everywhere / all-hands read-only / group boards for members); leftover bd_* grants are pruned at boot.
        ]},
        {"id": "m_admin", "label": "관리 센터", "kind": "menu"},
        # Agentic 모드(2026-10-19): 홈의 Chat | Agentic 알약과 Agentic 셸. 기본은 끔(슈퍼는 항상) / the home pill and the Agentic shell; off by default, super always
        {"id": "m_agentic", "label": "Agentic", "kind": "menu"},
    ]


def kn_locate(fname: str) -> dict:
    """PDF 파일명 → {"path": ['지식 관리', …폴더 라벨], "folder": 폴더 id|None}.

    채팅 리소스 참조 블록의 브레드크럼·내비게이션용(미매칭 시 path=['지식 관리'])."""
    # PDF filename → {"path": ['지식 관리', …folder labels], "folder": folder id|None}.
    # For the chat resource-reference breadcrumbs & navigation (unmatched → path=['지식 관리']).
    found: dict | None = None

    def walk(nodes: list[dict], trail: list[str]) -> None:
        nonlocal found
        for n in nodes:
            if found:
                return
            t2 = trail + [str(n.get("label") or "")]
            if any(f == fname for _, f in n.get("files", [])):
                found = {"path": ["지식 관리"] + t2, "folder": n.get("id")}
                return
            if n.get("folders"):
                walk(n["folders"], t2)

    walk(_active_knowledge(), [])
    return found or {"path": ["지식 관리"], "folder": None}


def data_locate(table: str | None = None, bi_file: str | None = None) -> dict | None:
    """물리 테이블/BI 파일 → {"ws","wsName","kind"('DB'|'CSV'|'BI'),"label","node"} — 첫 매칭 워크스페이스.

    채팅 리소스 참조 블록의 그룹(워크스페이스) 집계·브레드크럼용."""
    # Physical table / BI file → {"ws","wsName","kind","label","node"} — first matching workspace.
    # For group (workspace) aggregation & breadcrumbs in the chat resource-reference block.
    for w in _active_workspaces():
        for kind, disp in (("sql", "DB"), ("csv", "CSV"), ("bi", "BI")):
            for it in (w.get(kind) or []):
                hit = (table is not None and it.get("table") == table) or \
                      (bi_file is not None and it.get("file") == bi_file)
                if hit:
                    return {"ws": str(w.get("id")), "wsName": str(w.get("name") or ""), "kind": disp,
                            "label": str(it.get("name") or table or bi_file or ""), "node": it.get("node")}
    return None


def _kn_front(nodes: list[dict], lv: int) -> list[dict]:
    """지식 폴더 → 프론트 RM_KN 유사 트리(재귀, lv 부여)."""
    out = []
    for n in nodes:
        out.append({
            "id": n["id"], "lv": lv, "name": n["label"], "node": n["id"],
            "files": [{"name": fname, "node": fid} for fid, fname in n.get("files", [])],
            "children": _kn_front(n.get("folders", []), lv + 1),
        })
    return out


def knowledge_tree() -> list[dict]:
    """프론트 리소스 센터(문서 관리) 하이드레이션용 — LV.1~3 중첩. 동적 트리(DB) 우선."""
    return _kn_front(_active_knowledge(), 1)


def datasets() -> dict:
    """프론트 데이터 분석 하이드레이션용 — 슬롯 단위 행(같은 테이블/BI가 여러 슬롯이면 행도 여러 개)."""
    # Slot-level rows for frontend hydration (a table/BI appearing in multiple slots yields multiple rows).
    tables, bi = [], []
    for w in _active_workspaces():
        wid = w.get("id")
        for it in (w.get("sql") or []) + (w.get("csv") or []):
            if it.get("node") and it.get("table"):
                tables.append({"node": it["node"], "label": it.get("name", ""), "table": it["table"], "ws": wid})
        for it in (w.get("bi") or []):
            if it.get("node") and it.get("file"):
                bi.append({"node": it["node"], "label": it.get("name", ""), "file": it["file"], "ws": wid})
    return {"tables": tables, "bi": bi}


def seed_workspaces_data() -> list[dict]:
    """access.seed_workspaces 용 — 워크스페이스(프론트 표시). 원본에 실제 table/file 매핑 포함."""
    # For access.seed_workspaces — workspaces (frontend display). Each source carries the real table/file mapping.
    out = []
    for w in DATA_WORKSPACES:
        out.append({
            "id": w["id"], "name": w["name"], "team": w["team"], "desc": w["desc"],
            "bi": [{"name": nm, "src": "Power BI · " + f, "upd": "매일 06:00", "file": f} for nm, f in w["bi"]],
            "csv": [{"name": nm, "src": "CSV · " + t, "upd": "주 1회", "table": t} for nm, t in w["csv"]],
            "sql": [{"name": nm, "src": "SQL · " + t, "upd": "매일", "table": t} for nm, t in w["sql"]],
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — 챗봇 게이팅 헬퍼: effective(no) → 열람(>=1) 가능한 실제 리소스 집합.
# eff=None 은 슈퍼관리자(나) — 게이팅을 우회하므로 이 헬퍼들을 호출하지 않는다(전체 허용).
# Phase 3 — chatbot gating helpers: effective(no) → set of real resources readable (>=1).
# eff=None means super admin (나) — gating is bypassed, so these helpers are not called (all allowed).
# ─────────────────────────────────────────────────────────────────────────────

def _eff_nodes(eff: dict | None) -> dict:
    return (eff or {}).get("nodes", {}) or {}


def allowed_knowledge_files(eff: dict | None) -> set[str]:
    """열람 가능(레벨>=1) 지식 PDF 파일명 집합. kb.search 히트의 doc(파일명) 필터에 사용."""
    # Set of knowledge PDF filenames readable (level>=1). Used to filter kb.search hits by doc (filename).
    nodes = _eff_nodes(eff)
    return {fname for fid, fname in NODE_FILE.items() if nodes.get(fid, 0) >= 1}


def allowed_tables(eff: dict | None) -> set[str]:
    """열람 가능(레벨>=1) DuckDB 테이블명 집합. Text2SQL 스키마/SQL 가드에 사용."""
    # Set of DuckDB table names readable (level>=1). Used for the Text2SQL schema and SQL guard.
    nodes = _eff_nodes(eff)
    return {tbl for tid, tbl in NODE_TABLE.items() if nodes.get(tid, 0) >= 1}


def allowed_bi_files(eff: dict | None) -> set[str]:
    """열람 가능(레벨>=1) BI 대시보드 파일명 집합."""
    # Set of BI dashboard filenames readable (level>=1).
    nodes = _eff_nodes(eff)
    return {fname for bid, fname in NODE_BI.items() if nodes.get(bid, 0) >= 1}


def all_table_names() -> set[str]:
    """SQL 가드 유니버스의 전체 DuckDB 테이블명 = 시드 ∪ 슬롯 ∪ 풀(유니버스 밖 실테이블).

    허용 집합에 없는 이 목록의 테이블을 SQL이 참조하면 차단된다 — 풀 스테이징 CSV가
    큐레이션 전에 멤버 질의로 새는 것을 막는 방어망."""
    # Full table-name universe for the SQL guard = seed ∪ slots ∪ pool (real tables outside the node universe).
    # References to any of these outside the allowed set are blocked — prevents staged pool CSVs from
    # leaking to member queries before curation.
    return set(SEED_TABLE_NAMES) | set(NODE_TABLE.values()) | set(_extra_tables)


def domain_readable(eff: dict | None, domain: str) -> bool:
    """도메인(p_know/p_data/p_auto)에 열람 가능한 하위 리소스가 하나라도 있는지.

    eff=None(슈퍼)은 항상 True. effective(no).read 를 우선 신뢰하고, 없으면 허용 집합으로 폴백.
    """
    # Whether the domain (p_know/p_data/p_auto) has any readable child resource.
    # eff=None (super) is always True. Prefer effective(no).read; fall back to the allowed sets.
    if eff is None:
        return True
    read = eff.get("read")
    if isinstance(read, dict) and domain in read:
        return bool(read[domain])
    if domain == "p_know":
        return bool(allowed_knowledge_files(eff))
    if domain == "p_data":
        return bool(allowed_tables(eff) or allowed_bi_files(eff))
    if domain == "p_auto":
        # 어느 업무 자동화 에이전트든 하나라도 열람 가능하면 도메인 열림(agent_email 하드코딩을
        # WORK_AGENTS 순회로 일반화 — agent_edu 단독 grant 사용자가 잠기지 않도록).
        # The domain opens if any work-automation agent is readable (generalizes the old agent_email
        # hardcoding over WORK_AGENTS so an agent_edu-only grant doesn't lock the whole surface).
        nodes = _eff_nodes(eff)
        return any(nodes.get(aid, 0) >= 1 for aid, _ in all_work_agents())
    return False


# 모듈 로드 시 초기 파생맵 구성(시드 기준) — 부팅 후 access.rebuild_universe() 가 DB 스냅샷으로 대체한다.
# Build the initial derived maps from seeds at import time — replaced with the DB snapshot by
# access.rebuild_universe() after boot.
set_dynamic(None, None)
