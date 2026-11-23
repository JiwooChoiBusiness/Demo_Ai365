"""위젯 에이전트(2026-11-16, 계약 = docs/widget-agent.md 8절) — 홈 위젯 하나를 대화로 만들고 고치는 도구 호출 루프.

리포트 에이전트의 그룹웨어 버전이다. 위젯 하나를 리포트 에이전트의 작은 대시보드(데이터 0~1 · 차트 0~1 · KPI 카드 0~4)로 보고,
리포트 에이전트의 Visualize Agent 도구 중 차트를 바꾸는 도구와 KPI 카드 도구를 그대로 불러 쓴다(report_agent.run_tool — 검사와
계산이 같다). 2026-11-16 사용자 결정:
- 붙이는 것: 차트 수정 · 디자인 변경 · 테마 설정 · 기준선 추가/삭제 · 계산 값 추가 · 강조 추가/삭제 · 추세선·예측 · 필터 추가/삭제
  (위젯에는 고정 조건) · KPI 카드 추가/삭제/순서 + 위젯 도구(위젯 제목 변경 · 인사이트 작성 · 데이터 질문).
- 붙이지 않는 것: 리포트 에이전트의 데이터 조회(데이터는 3단계 fetch_data 가 위젯 전용 파이프라인으로) · 드릴다운 · 차트 추가/삭제 ·
  배치 변경 · 대시보드 제목 변경.
- KPI 카드는 데이터를 정하지 않고도 만든다('데이터 연결 전' 카드) — 그러면 "어떤 데이터를 연결할까요?"라고 되묻는다(ask).
- 인사이트는 틀({변수})로 두어 위젯 데이터가 바뀌면 같이 바뀐다(home_widgets.render_insight).
서버는 작업본을 저장하지 않는다: 화면이 작업본 · 대화를 들고 한 턴씩 보내고, 저장은 /api/home/widgets 가 한다.

The widget agent (2026-11-16; contract = docs/widget-agent.md section 8): a tool-calling loop that builds and edits one
home widget by conversation — the groupware version of the report agent. A widget is treated as a small report-agent
dashboard (0..1 data, 0..1 chart, 0..4 KPI cards), and the report agent's chart-changing and KPI tools are called as they
are (report_agent.run_tool: the same checks and math). User decisions of 2026-11-16: attach the chart, design, theme,
reference-line, calculation, highlight, trend, filter (a fixed condition on a widget) and KPI-card tools plus the widget's
own tools (rename, insight, data question); leave out the report agent's data query (phase 3's fetch_data uses the
widget-only pipeline), drill-down, adding or
removing charts, arranging and renaming a dashboard. A KPI card can be made before its data is chosen (a 'not connected
yet' card), and the agent then asks which data to connect (ask). Insights are templates ({variables}) that follow the
widget data (home_widgets.render_insight). The server keeps no working copy: the screen holds the draft and the
conversation and sends one turn at a time; saving goes through /api/home/widgets.
"""
from __future__ import annotations

import copy
import json
import logging

import re

from app import home_widgets as hw, llm, report_agent as ra, report_dash as rd, settings, widget_data as wd

logger = logging.getLogger("ai365.widget_agent")

MAX_ROUNDS = 4
MAX_CALLS = 8              # 한 라운드에 실행하는 도구 수 / tool calls run per round
HISTORY_TURNS = 10
MAX_MESSAGE = 2000         # 요청 한 번의 글자 수 / characters per request
MAX_HISTORY_TEXT = 400

DATA_AGENT, VIZ_AGENT = ra.DATA_AGENT, ra.VIZ_AGENT

CHART_TOOLS = ("update_chart", "set_style", "set_theme", "add_reference_line", "remove_reference_line", "add_calculation",
               "add_highlight", "remove_highlight", "set_trend", "add_filter", "remove_filter")
KPI_TOOLS = ("add_kpi", "remove_kpi", "arrange_kpis")
OWN_TOOLS = ("fetch_data", "rename_widget", "set_insight", "ask_data")
TOOL_NAMES = CHART_TOOLS + KPI_TOOLS + OWN_TOOLS

NO_CHART = "이 위젯에는 아직 차트가 없습니다. 먼저 보여 줄 데이터를 가져오면 차트가 생깁니다"
NO_DATA = "이 위젯에는 아직 데이터가 없습니다. 먼저 데이터를 가져오거나 숫자를 알려 주세요"
ASK_TEXT = "어떤 데이터를 연결할까요?"
ASK_HINT_KPI = "무엇의 숫자인지 말씀해 주시면 사내 데이터 · 사내 문서 · 웹에서 찾아 넣습니다. 숫자를 직접 알려 주셔도 됩니다."
ASK_HINT_DATA = "말씀해 주시면 사내 데이터 · 사내 문서 · 웹에서 찾아 넣습니다."
_AUTO_LABEL = re.compile(r"KPI \d+")   # 이름을 말하지 않아 붙은 카드 이름 / a card name given because nobody named it
TOOL_BROKE = "도구를 실행하지 못했습니다. 요청을 조금 바꿔 다시 시도해 주세요"

# 리포트 에이전트 도구를 위젯에 맞춰 고친 것: 차트는 하나뿐이라 chart_id 는 생략해도 되고, 제목 · 크기 · 데이터 바꾸기는 뺀다
# The report agent's tools adjusted to a widget: with one chart chart_id may be left out, and title, size and data changes are dropped
_DROP_PROPS = {"update_chart": ("title", "subtitle", "size", "source_id"), "add_kpi": ("source_id",)}
_DESC = {
    "add_kpi": "위젯에 KPI 카드(숫자 카드)를 넣거나 고친다(최대 4개). ① 사용자가 숫자를 말했으면 value 에 그 숫자를 그대로 넣는다(고정 숫자 카드). "
               "② [위젯 상태]에 데이터가 있고 사용자가 값 컬럼을 말했으면 column(+agg) — 숫자는 시스템이 계산한다. "
               "③ 둘 다 아니면 숫자 없이 카드를 만든다(데이터 연결 전 카드) — label 은 사용자가 이름을 말했을 때만 준다. 그러면 시스템이 사용자에게 "
               "어떤 데이터를 연결할지 묻는다. 숫자를 지어내지 않는다. 고치기: kpi_id(예: k1) 또는 같은 이름을 주면 그 카드에서 적은 항목만 바뀐다"
               "(이름 · 단위 · 설명 · 숫자 · 컬럼). 끄기: delta='none', link_chart_id='none', unit · note 는 빈 문자열.",
    "add_filter": "위젯 차트에 필터 조건을 건다 — 위젯에는 누르는 필터 버튼이 없고 이 조건이 고정으로 걸린다. 컬럼은 [위젯 상태]의 데이터에 있어야 한다. "
                  "글자 컬럼은 selected(보일 값), [기간] 컬럼은 last_n 또는 from_value · to_value('최근 6개월만' = last_n 6), 숫자 컬럼은 min · max. "
                  "같은 컬럼에 다시 부르면 조건이 바뀐다.",
    "remove_filter": "위젯 차트의 필터 조건을 지운다.",
    "set_theme": "위젯 차트의 대표 색(brand_color, #RRGGBB)을 정해 그 색에서 계열 색을 만든다. 색 이름만 들었으면 알맞은 #RRGGBB 로 바꿔 준다. "
                 "clear=true 면 기본 색으로 돌아간다. 색 묶음(palette)만 고르는 일은 set_style 이다.",
}
_OWN_SPECS = [
    {"name": "fetch_data",
     "description": "위젯에 보여 줄 내용을 가져온다. 시스템이 요청에 맞춰 사내 데이터(DB) · 사내 문서 · 웹 검색 중 알맞은 곳을 골라(권한 안에서) 찾아 위젯에 넣는다: "
                    "표 → 차트(view 가 kpi 면 데이터 KPI 카드), 숫자 → KPI 카드(데이터 연결 전 카드가 있으면 그 카드부터 채운다), 목록 → 목록, 설명 → 글. "
                    "위젯은 숫자가 아니어도 된다(뉴스 목록 · 규정 요약 등). 무엇을 보여 줄지 정해졌으면 바로 부르고, 결과를 보고 필요하면 차트 · 디자인 도구로 다듬는다. "
                    "새로 가져오면 같은 종류의 이전 내용은 바뀐다.",
     "parameters": {"type": "OBJECT", "properties": {
         "request": {"type": "STRING", "description": "무엇을 가져올지 한 문장(기간 · 대상 · 지표를 분명히. 예: 2026년 지점별 월 매출, 오늘 원달러 환율, 연차 규정 요약)"},
         "view": {"type": "STRING", "enum": list(wd.VIEWS), "description": "보여 줄 모양(생략하면 시스템이 정한다): kpi 숫자 카드 · chart 차트 · list 목록 · text 글"}},
         "required": ["request"]}},
    {"name": "rename_widget", "description": "위젯 제목을 바꾼다(홈 위젯 머리줄에 보이는 이름, 40자까지).",
     "parameters": {"type": "OBJECT", "properties": {"title": {"type": "STRING"}}, "required": ["title"]}},
    {"name": "set_insight",
     "description": "위젯 아래 인사이트(1~2문장, 300자까지)를 쓴다. 위젯 데이터가 바뀌면 같이 바뀌도록 숫자와 항목 이름은 직접 쓰지 않고 "
                    "[인사이트 변수]의 {변수}로 쓴다(예: '{최고}가 {최고값}으로 가장 높고, 평균은 {평균}입니다.'). 조사(이/가 · 은/는 · 을/를 · "
                    "와/과 · 으로/로)는 시스템이 값에 맞게 고친다. 빈 문자열이면 인사이트를 지운다.",
     "parameters": {"type": "OBJECT", "properties": {"text": {"type": "STRING"}}, "required": ["text"]}},
    {"name": "ask_data",
     "description": "무엇을 보여 줄지 정해지지 않았을 때만(예: 'KPI 카드 위젯 만들어줘', '차트 위젯 하나'처럼 대상이 없는 요청) 사용자에게 어떤 데이터를 "
                    "연결할지 묻는다. 대상이 있으면 묻지 말고 fetch_data 를 부른다. 이 도구를 부르면 이번 턴은 끝난다.",
     "parameters": {"type": "OBJECT", "properties": {
         "question": {"type": "STRING", "description": "사용자에게 할 질문 한 문장(생략하면 '어떤 데이터를 연결할까요?')"},
         "need": {"type": "STRING", "description": "무엇을 만들려는지 짧게(예: 월별 매출 차트)"}}}},
]
_OWN_META = {"fetch_data": (DATA_AGENT, "데이터 가져오기", "데이터"), "rename_widget": (VIZ_AGENT, "위젯 제목 변경", "정리"),
             "set_insight": (VIZ_AGENT, "인사이트 작성", "정리"), "ask_data": (DATA_AGENT, "데이터 질문", "데이터")}


def _reuse(name: str) -> dict:
    """리포트 에이전트의 도구 선언을 복사해 위젯에 맞춘다 / copy a report-agent tool declaration and fit it to a widget"""
    spec = copy.deepcopy(next(s for s in ra.TOOL_SPECS if s["name"] == name))
    params = spec["parameters"]
    props = params.get("properties") or {}
    for p in _DROP_PROPS.get(name, ()):
        props.pop(p, None)
    if "chart_id" in props:
        props["chart_id"] = {"type": "STRING", "description": "위젯의 차트는 c1 하나뿐이다(생략 가능)"}
        params["required"] = [r for r in params.get("required") or [] if r != "chart_id"]
    if name in _DESC:
        spec["description"] = _DESC[name]
    return spec


TOOL_SPECS = [_reuse(n) for n in CHART_TOOLS + KPI_TOOLS] + copy.deepcopy(_OWN_SPECS)
_NEEDS_FOLLOWUP = {"update_chart", "add_calculation", "fetch_data"}
# 입력 카드에서 고른 가져올 곳(2026-11-19 — 메인 채팅과 같은 [자동 ▾] 사내 · 외부 + 리소스 센터): internal = 사내 데이터 + 사내 문서
# where to fetch, picked in the input card (the main chat's [Auto ▾] internal / external plus the resource center): internal = data + documents
SCOPE_SOURCES = {"internal": ("data", "docs"), "data": ("data",), "docs": ("docs",), "web": ("web",)}
SCOPE_LABEL = {"internal": "사내(사내 데이터 · 사내 문서)", **wd.SOURCE_LABEL}   # 바뀐 값을 보고 한 번 더 생각할 도구 / tools whose new values deserve another round


def tool_meta(name: str) -> tuple[str, str, str]:
    """도구 → (소속 에이전트, 화면 이름, 묶음) / tool → (agent, label, group)"""
    if name in _OWN_META:
        return _OWN_META[name]
    agent, label = ra.TOOL_META.get(name, (VIZ_AGENT, name))
    return agent, label, ra.TOOL_GROUP.get(name, "기타")


def tool_tree() -> list[dict]:
    """위젯 에이전트에 붙은 도구를 트리로(에이전트 › 묶음 › 도구) — 리포트 에이전트의 tool_tree 와 같은 모양.
    The widget agent's tools as a tree (agent › group › tool), shaped like the report agent's tool_tree."""
    agents: list[dict] = []
    for spec in TOOL_SPECS:
        agent, label, group = tool_meta(spec["name"])
        a = next((x for x in agents if x["agent"] == agent), None)
        if a is None:
            a = {"agent": agent, "groups": []}
            agents.append(a)
        g = next((x for x in a["groups"] if x["group"] == group), None)
        if g is None:
            g = {"group": group, "tools": []}
            a["groups"].append(g)
        g["tools"].append({"name": spec["name"], "label": label, "description": spec["description"]})
    return agents


SYSTEM = """너는 사내 그룹웨어 홈의 '위젯 에이전트'다. 사용자의 홈 위젯 하나를 대화로 만들고 고친다. 너에게는 Data Agent 도구(데이터 가져오기 · 데이터 질문)와 리포트 에이전트와 같은 Visualize Agent 도구(차트 수정 · 디자인 · 테마 · 기준선 · 계산 값 · 강조 · 추세 · 필터 · KPI 카드), 위젯 도구(위젯 제목 변경 · 인사이트)가 붙어 있고, 위젯은 도구를 불러서만 바뀐다.

규칙:
- 위젯에 보여 줄 내용이 필요하면 fetch_data 를 부른다. 시스템이 요청에 맞춰 사내 데이터 · 사내 문서 · 웹 검색 중 알맞은 곳에서(권한 안에서) 찾아 넣는다. 위젯은 숫자가 아니어도 된다(뉴스 목록 · 규정 요약처럼 요청에 맞는 내용). 숫자를 지어내지 않는다.
- 대상이 정해진 요청(예: "지점별 매출 차트 위젯", "오늘 환율 위젯", "연차 규정 요약 위젯")은 묻지 말고 바로 fetch_data 를 부른다. 대상이 없는 요청(예: "KPI 카드 위젯을 만들어줘", "차트 위젯 하나")만 묻는다.
- 위젯에는 차트가 하나뿐이다(chart_id 는 c1, 생략해도 된다). 차트를 새로 만들거나 지우는 도구는 없다. 차트는 표를 가져오면 생긴다.
- "KPI 카드(위젯) 만들어줘"처럼 대상 없이 카드를 원하면 add_kpi 로 숫자 없는 카드를 만든다(데이터 연결 전 카드 — 시스템이 사용자에게 어떤 데이터를 연결할지 묻는다). 카드 이름은 사용자가 말했을 때만 label 로 준다. 사용자가 숫자를 말했으면 add_kpi 의 value 에 그 숫자를 넣는다.
- 카드 · 차트 · 목록을 '무엇의' 내용인지와 함께 말하면(예: "오늘 원달러 환율 카드", "이 위젯에 이번 달 매출 카드도 넣어줘", "경쟁사 뉴스 목록도") add_kpi 로 빈 카드를 만들지 말고 fetch_data(request=그 대상, 카드면 view="kpi")를 부른다. 이미 내용이 있는 위젯에 더하는 요청도 같다(있던 차트 · 카드 · 글은 그대로 남는다). 숫자 없는 카드는 대상이 전혀 없을 때만 만든다.
- 사용자가 데이터 연결 전 카드에 쓸 대상을 말하면(예: 이번 달 매출, 오늘 환율) fetch_data(request=그 대상, view="kpi")로 가져온다. 시스템이 그 카드부터 채운다.
- 위젯 제목은 rename_widget 이다(홈 위젯 머리줄의 이름 = 차트 제목). fetch_data 가 처음 내용을 넣을 때 '새 위젯'이면 알맞은 제목이 붙는다.
- 인사이트(set_insight)는 위젯 아래 한두 문장이다. 위젯 데이터가 바뀌면 같이 바뀌도록 숫자와 항목 이름은 직접 쓰지 않고 [인사이트 변수]의 {변수}로 쓴다. [인사이트 변수]에 없는 변수는 쓰지 않는다. 변수 자리에는 지금 값이 그대로 들어가므로 앞뒤 말과 이어지게 쓴다(예: {증감} = 증가 → "{직전대비} {증감}했습니다"). 조사는 시스템이 값에 맞게 고친다. 인사이트는 사용자가 요청할 때 쓰고, 차트를 바꿔서 지금 인사이트가 숨겨졌으면([위젯 상태]의 '값을 기다리는 중') 다시 쓴다.
- 집계(agg): 수량 · 금액 · 건수는 sum, 비율 · 평균 · 단가 · 점수는 avg. 비율 컬럼을 sum 으로 더하거나 원 · 도넛의 값으로 쓰지 않는다(도구가 거절한다).
- "막대를 선으로 · 가로 막대 · 도넛으로 · 상위 5개만 · 큰 순서로 · 누적으로 · 단위"는 update_chart, "색 · 값 라벨 · 범례 · 격자 · 둥글게"는 set_style, "회사 색 · 대표 색"은 set_theme, "목표선 · 평균선"은 add_reference_line, "전월 대비 · 증감률 · 누계 · 비중 · 이동 평균 · 순위"는 add_calculation(숫자는 시스템이 계산, ~도 같이면 replace 없이 · ~로 바꿔줘면 replace=true), "빨갛게 · 강조 · 상위 N개만 색"은 add_highlight(기준선과 같이 말했으면 add_reference_line 을 먼저), "추세선 · 예측"은 set_trend(x 가 [기간] 컬럼일 때만), "최근 N개월만 · ~부터 ~까지 · ~ 이상만 · ~만 보여줘"는 add_filter 다.
- 필터는 위젯에 고정 조건으로 걸린다(홈 위젯에는 누르는 필터 버튼이 없다).
- 한 요청에 여러 가지를 말하면(예: 강조하고 추세선도) 필요한 도구를 한 번에 모두 부른다. 요청과 무관한 변경은 하지 않는다.
- 위젯은 도구를 불러야만 바뀐다. 도구를 부르지 않은 변경은 했다고 말하지 않는다.
- 더 부를 도구가 없으면 도구 없이 사용자에게 한두 문장으로 무엇을 했는지 답한다. 답에는 {변수}를 쓰지 않는다(변수는 인사이트에만 쓴다). 사용자가 쓴 언어로 답한다(기본 한국어).
- 이 대화의 맥락은 이 위젯뿐이다. 다른 채팅 내용은 모른다고 생각한다."""


# ────────────────────────────────────────────────────────
# 프롬프트 재료 / prompt material
# ────────────────────────────────────────────────────────

def _chart_line(c: dict) -> str:
    ys = ", ".join(ra._y_text(y) for y in c["y"])  # noqa: SLF001  리포트 에이전트와 같은 표기 / the report agent's notation
    refs = ", ".join(f"{r['label']}={r['stat'] or r['value']}" for r in c["ref_lines"])
    flts = ", ".join(f"{f['col']}={ra._filter_text(f)}" for f in c["filters"])  # noqa: SLF001
    hls = ", ".join(h["label"] for h in c.get("highlights") or [])
    tr = c.get("trend") or {}
    return (f"c1 [{c['type']}] x={c['x']} y=[{ys}]" + (f" group={c['group']}" if c["group"] else "")
            + (f" sort={c['sort']['by']}/{c['sort']['dir']}" if c["sort"]["by"] != "none" else "")
            + (f" limit={c['limit']}" if c["limit"] else "") + (" stack" if c["stack"] else "")
            + (f" unit={c['unit']}" if c.get("unit") else "")
            + (f" 기준선=[{refs}]" if refs else "") + (f" 강조=[{hls}]" if hls else "") + (f" 필터=[{flts}]" if flts else "")
            + (f" 추세={'선' if tr.get('line') else ''}{'+예측' + str(tr['forecast']) if tr.get('forecast') else ''}" if tr else "")
            + f" palette={c['style']['palette']}{' labels' if c['style']['labels'] else ''}")


def describe(state: dict, insight: str, values: dict, waiting: bool, extra: dict | None = None) -> str:
    """[위젯 상태] — 제목 · 출처 · 데이터 · 차트 · KPI 카드 · 글/목록 · 테마 · 인사이트 · 인사이트 변수 / the widget state for the prompt"""
    extra = extra or {}
    lines = [f"제목: {state['title']}"]
    part_name = {"source": "표", "cards": "카드", "text": "글", "list": "목록"}
    for o in extra.get("origins") or []:
        what = part_name.get(o["part"], o["part"]) + (" " + ",".join(c["id"] for c in o["cards"]) if o["part"] == "cards" else "")
        lines.append(f"출처({what}): {wd.SOURCE_LABEL.get(o['kind'], o['kind'])} · \"{o['query']}\" · 가져온 시각 {o['fetched_at'][:16]}")
    lines.append("")
    if state["sources"]:
        s = state["sources"][0]
        lines.append(f"데이터: 행 {len(s['rows'])}개 · 컬럼: " + "; ".join(ra._col_profile(s, c) for c in s["columns"]))  # noqa: SLF001
        for r in s["rows"][:ra.SAMPLE_ROWS]:
            lines.append("  샘플: " + ", ".join(f"{c}={rd.key(v)[:30]}" for c, v in zip(s["columns"], r)))
    else:
        lines.append("데이터: 없음(fetch_data 로 가져온다)")
    lines.append("차트: " + (_chart_line(state["charts"][0]) if state["charts"] else "없음(표를 가져오면 생긴다)"))
    kpis = state.get("kpis") or []
    if kpis:
        lines.append("KPI 카드:")
        for k in kpis:
            if k.get("pending"):
                body = "데이터 연결 전(숫자 없음)"
            elif not k.get("source"):
                body = f"직접 적은 숫자 {rd.fmt(k['value'], k.get('unit') or '')}"
            else:
                body = f"{k['agg']}({k['col']})" + (" 직전 기간 대비" if k.get("delta") else "")
            lines.append(f"  {k['id']} \"{k['label']}\" = {body}" + (f" 단위={k['unit']}" if k.get("unit") else "")
                         + (f" 설명=\"{k['note']}\"" if k.get("note") else ""))
    else:
        lines.append("KPI 카드: 없음")
    for b in extra.get("blocks") or []:
        if b["type"] == "text":
            lines.append(f"글: \"{b['text'][:200]}\"")
        else:
            lines.append(f"목록: {len(b['items'])}건 — " + " / ".join(it["title"][:40] for it in b["items"][:4]))
    if state.get("theme"):
        lines.append(f"테마: 대표 색 {state['theme']['brand']}")
    lines.append("인사이트: " + (f"\"{insight}\"" + (" (값을 기다리는 중이라 지금은 숨겨져 있다)" if waiting else "") if insight else "없음"))
    lines += ["", "[인사이트 변수] (지금 값)"]
    lines += [f"  {{{k}}} = {v}" for k, v in values.items()] or ["  (없음 — 차트나 숫자가 있는 KPI 카드가 있어야 쓸 수 있다)"]
    return "\n".join(lines)


def _history(messages) -> list[dict]:
    """화면이 보낸 대화 기록을 정리한다(마지막 10개, 글 400자, 도구는 이름과 성공 여부만) / clean the screen's history"""
    out = []
    for m in (messages if isinstance(messages, list) else [])[-HISTORY_TURNS:]:
        if not isinstance(m, dict) or not isinstance(m.get("text"), str) or not m["text"].strip():
            continue
        trace = [{"tool": str(t.get("tool") or "")[:40], "ok": t.get("ok") is True}
                 for t in (m.get("trace") if isinstance(m.get("trace"), list) else [])[:12] if isinstance(t, dict)]
        out.append({"role": "user" if m.get("role") == "user" else "agent", "text": m["text"][:MAX_HISTORY_TEXT], "trace": trace})
    return out


# ────────────────────────────────────────────────────────
# 도구 실행 / tool execution
# ────────────────────────────────────────────────────────

def _txt(value, n: int) -> str:
    return value.strip()[:n] if isinstance(value, str) else ""


def _comp(state: dict) -> dict | None:
    return rd.compute(state["charts"][0], state["sources"][0]) if state["charts"] else None


def _card_id(state: dict, value) -> str:
    """카드를 가리키는 말 → id. 이름이 정확히 같은 카드가 먼저이고, 없으면 리포트 에이전트의 느슨한 id('k1' · 'KPI 1' · '카드 2')로 읽는다.
    리포트 에이전트는 'KPI 1'을 k1 로 먼저 읽어, 이름이 'KPI 1'인 다른 카드 대신 k1 을 지우거나 고쳤다(2026-11-16 검토).
    Words naming a card → its id: an exact name wins, otherwise the report agent's loose id ('k1', 'KPI 1', '카드 2'). The report
    agent read 'KPI 1' as k1 first and so removed or edited k1 instead of the card named 'KPI 1' (review of 2026-11-16)."""
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    exact = next((k["id"] for k in state.get("kpis") or [] if k["label"] == text), "")
    return exact or ra._kpi_id(state, text)  # noqa: SLF001


def _free_label(have: list[dict]) -> str:
    """이름을 말하지 않은 새 카드의 이름 'KPI N'(겹치지 않는 가장 작은 N) / the name 'KPI N' for a new card nobody named (the smallest free N)"""
    names = {k["label"] for k in have}
    n = 1
    while f"KPI {n}" in names:
        n += 1
    return f"KPI {n}"


def _pending_card(state: dict, ctx: dict, cur: dict | None, args: dict, label: str) -> tuple[str, str]:
    """데이터 연결 전 카드를 만들거나(cur 없음) 이름 · 단위 · 설명만 고친다 / create a not-connected card or change its name, unit or note"""
    have = state.get("kpis") or []
    names = {k["label"] for k in have if k is not cur}
    if label in names:
        raise ValueError(f"같은 이름의 KPI 카드가 이미 있습니다: {label}")
    if cur is None:
        label = label or _free_label(have)
        kid = rd._next_id("k", {k["id"] for k in have})  # noqa: SLF001
        card = {"id": kid, "source": "", "col": "", "agg": "", "label": label, "unit": _txt(args.get("unit"), 8),
                "link": "", "delta": "", "value": None, "note": _txt(args.get("note"), rd.MAX_KPI_NOTE), "pending": True}
        state["kpis"] = have + [card]
        ctx["created"].add(kid)
        return f"KPI 카드 {kid} \"{label}\" 추가 — 데이터 연결 전(숫자 없음)", f"'{label}' KPI 카드를 만들었습니다."
    new = dict(cur)
    if label:
        new["label"] = label
    if args.get("unit") is not None:
        new["unit"] = _txt(args.get("unit"), 8)
    if args.get("note") is not None:
        new["note"] = _txt(args.get("note"), rd.MAX_KPI_NOTE)
    if new == cur:
        raise ValueError("바뀐 항목이 없습니다. 이름 · 단위 · 설명이나 사용자가 말한 숫자(value)를 적어 주세요")
    state["kpis"] = [new if k is cur else k for k in have]
    return f"KPI 카드 {cur['id']} \"{new['label']}\" 수정(아직 데이터 연결 전)", f"KPI 카드 '{new['label']}'을 고쳤습니다."


def _add_kpi(state: dict, ctx: dict, args: dict) -> tuple[str, str]:
    have = state.get("kpis") or []
    kid = _card_id(state, args.get("kpi_id"))
    label = rd._s(args.get("label"), hw.MAX_KPI_LABEL)  # noqa: SLF001
    if not kid and label:
        kid = next((k["id"] for k in have if k["label"] == label), "")
    cur = next((k for k in have if k["id"] == kid), None)
    has_value = args.get("value") not in (None, "")
    has_col = bool(str(args.get("column") or "").strip())
    if has_col and not state["sources"]:
        raise ValueError(NO_DATA)
    if cur is None and len(have) >= hw.MAX_KPIS:
        raise ValueError(f"위젯에는 KPI 카드를 {hw.MAX_KPIS}개까지 넣을 수 있습니다")
    if not has_value and not has_col and (cur is None or cur.get("pending")):
        return _pending_card(state, ctx, cur, args, label)
    out = {k: v for k, v in args.items() if k != "source_id"}
    if kid:
        out["kpi_id"] = kid
    elif has_value and not label:   # 이름 없이 말한 숫자도 카드가 된다(리포트 에이전트는 이름을 요구한다) / a number given without a name still makes a card
        out["label"] = _free_label(have)
    result = ra.run_tool(state, "add_kpi", out, None, {"focus": hw.CHART_ID if state["charts"] else ""})
    if cur is not None and (has_value or has_col):
        _release_card(ctx, cur["id"])   # 사용자가 정한 숫자 · 열 / the user's own number or column
    return result


def _release_card(ctx: dict, cid: str) -> None:
    """카드를 가져온 출처에서 뺀다: 지운 카드(같은 id 가 새 카드에 다시 붙는다)나 사용자가 숫자 · 열을 정한 카드는 다시 가져오기가 덮어쓰면
    안 된다(3단계 검토). A card leaves its origin when removed (the id may be reused) or when the user set its number or column, so a
    refresh never overwrites it (phase-3 review)."""
    out = []
    for o in ctx["extra"]["origins"]:
        if o["part"] == "cards":
            o = {**o, "cards": [c for c in o["cards"] if c["id"] != cid]}
            if not o["cards"]:
                continue
        out.append(o)
    ctx["extra"]["origins"] = out


def _remove_kpi(state: dict, ctx: dict, args: dict) -> tuple[str, str]:
    """카드 지우기(이름이 정확히 같은 카드가 먼저). 지운 카드의 변수({k1} …)를 쓰던 인사이트는 함께 지운다: 같은 id 가 새 카드에 다시
    붙으면 그 카드의 숫자로 엉뚱한 문장이 되살아나기 때문이다.
    Removes a card (an exact name first). An insight using a removed card's variable ({k1} …) is removed too: the id may be reused by
    a new card, which would revive the sentence with that card's number."""
    named = args.get("kpi_id") or args.get("label")
    out = {"kpi_id": _card_id(state, named) or str(named)} if named else {}
    before = {k["id"] for k in state.get("kpis") or []}
    detail, say = ra.run_tool(state, "remove_kpi", out, None, {})
    gone = before - {k["id"] for k in state.get("kpis") or []}
    for g in gone:
        _release_card(ctx, g)
    if ctx["insight"] and any("{" + g + "}" in ctx["insight"] for g in gone):
        ctx["insight"] = ""
        detail += " (이 카드를 쓰던 인사이트도 삭제)"
        say = (say + " 이 카드를 쓰던 인사이트도 지웠습니다.").strip()
    return detail, say


def _draft(state: dict, ctx: dict, plan: dict) -> None:
    """의도 판단이 끝나면 미리 그릴 수 있는 부분(제목 · 칸 모양)을 초안으로 보낸다 — 화면은 데이터가 오기 전에 위젯 모양을 먼저 그린다.
    Once the intent is known, sends what can be drawn early (title, slots) as a draft, so the screen shows the widget's shape
    before the data arrives."""
    if ctx.get("emit") is None:
        return
    try:
        spec = hw.from_state(state, ctx["clean"], ctx["insight"], ctx["extra"])
        model = hw.model_of(spec)
    except Exception:  # noqa: BLE001 — 초안은 덤이다 / the draft is a bonus
        return
    if model["title"] == hw.NEW_TITLE and plan.get("title"):
        model["title"] = plan["title"]
    model["skeleton"] = {"view": plan["view"], "labels": plan["labels"], "sources": [wd.SOURCE_LABEL[s] for s in plan["sources"]]}
    model["empty"] = False
    ctx["emit"]("draft", {"model": model})


def _put_label(state: dict, label: str, skip_id: str = "") -> str:
    """다른 카드와 겹치지 않는 이름(겹치면 뒤에 번호) / a name no other card has (a number is added on a clash)"""
    names = {k["label"] for k in state.get("kpis") or [] if k["id"] != skip_id}
    base, out, n = label[:36], label, 2
    while out in names:
        out = f"{base} {n}"
        n += 1
    return out


def _apply_table(state: dict, ctx: dict, table: dict, plan: dict) -> tuple[str, list[str]]:
    """가져온 표를 위젯 데이터로: 예전 표에 묶인 데이터 카드는 새 표에 그 열이 없으면 빼고, view 가 kpi 면 숫자 열로 데이터 KPI 카드, 아니면
    차트(예전 차트가 있으면 그 종류 · 디자인을 잇는다). 카드와 열은 **이름으로** 짝짓는다(3단계 검토: 순서로 붙여 '매출' 카드에 연도가 들어갔다):
    이름 있는 데이터 연결 전 카드 → 같은 · 품는 이름의 열, 'KPI N' 카드 → 남은 열 차례로, 계획한 카드 이름 → 이름이 맞는 열. 연도 · 월 · id 같은
    열은 숫자로 쓰지 않는다. 차트를 없애면 카드의 차트 연결도 지운다.
    A fetched table becomes the widget data. Cards and columns pair **by name** (phase-3 review: positional pairing put the year
    into a '매출' card): named not-connected cards take same-named columns, 'KPI N' cards take the remaining ones in order, planned
    names take matching columns; period or id columns are never used as values. Removing the chart also clears card links."""
    ctx["extra"]["source"] = table
    src = rd.norm_source({"id": hw.SOURCE_ID, "columns": table["columns"], "rows": table["rows"],
                          "origin": {"kind": "agent", "note": plan["query"]}}, set())
    old = state["charts"][0] if state["charts"] else None
    state["sources"] = [src]
    state["kpis"] = [k for k in state.get("kpis") or [] if not k.get("source") or k.get("col") == "*" or k.get("col") in src["columns"]]
    nums = wd.number_columns(src["columns"], src["types"])
    if plan["view"] == "kpi" and nums:
        state["charts"] = []
        for k in state["kpis"]:
            if k.get("link") == hw.CHART_ID:
                k["link"] = ""   # 없어진 차트를 가리키지 않게 / never point at the removed chart
        pending = [k for k in state["kpis"] if k.get("pending")]
        named = [k for k in pending if not _AUTO_LABEL.fullmatch(k["label"])]
        pairs: list[tuple[dict | None, str, str]] = []   # (카드, 열, 이름) / (card, column, label)
        used: set[str] = set()
        for i, col in wd.match_columns([k["label"] for k in named], nums).items():
            pairs.append((named[i], col, named[i]["label"]))
            used.add(col)
        for card in (k for k in pending if _AUTO_LABEL.fullmatch(k["label"])):
            col = next((c for c in nums if c not in used), None)
            if col is None:
                break
            pairs.append((card, col, ""))
            used.add(col)
        if not pairs:   # 채울 카드가 없으면 새 카드: 계획한 이름이 맞는 열, 없으면 첫 열 하나 / new cards when nothing was filled
            labels = list(plan.get("labels") or [])
            for i, col in wd.match_columns(labels, nums).items():
                pairs.append((None, col, labels[i]))
            if not pairs:
                pairs.append((None, nums[0], labels[0] if len(labels) == 1 else ""))
        cards = []
        for card, col, label in pairs:
            if card is None and len(state["kpis"]) >= hw.MAX_KPIS:
                break
            raw = {"source": hw.SOURCE_ID, "col": col}
            if card is not None:
                raw.update({"unit": card.get("unit") or "", "note": card.get("note") or ""})
            if label:
                raw["label"] = label if card is not None else _put_label(state, label)
            kpi = rd.put_kpi(state, raw, card["id"] if card is not None else "")
            cards.append(kpi["id"])
        return "KPI 카드", cards
    spec = rd.auto_chart_spec(src)
    if old is not None and old["type"] != "kpi":   # 사용자가 고른 모양 · 디자인을 잇는다 / keep the user's chosen type and design
        spec["type"], spec["style"] = old["type"], old["style"]
    state["charts"] = [rd.norm_chart({**spec, "id": hw.CHART_ID, "source": hw.SOURCE_ID, "title": state["title"], "size": "full"},
                                     {hw.SOURCE_ID: src}, set())]
    return "차트", []


def _apply_numbers(state: dict, numbers: list[dict]) -> list[dict]:
    """뽑은 숫자 → 고정 숫자 KPI 카드. **이름으로** 짝짓는다(3단계 검토: 순서로 채워 '엔화' 카드에 달러 값이 들어갔다): 이름 있는 데이터
    연결 전 카드 → 같은 · 품는 이름이나 별칭이 맞는 숫자, 'KPI N' 카드 → 남은 숫자 차례로, 그래도 남으면 새 카드(위젯당 4개까지). 맞는 숫자가
    없는 이름 있는 카드는 그대로 둔다. 반환 = [{id, key}](key = 가져온 이름 — 다시 가져올 때 이 이름으로 찾는다).
    Numbers → fixed KPI cards, paired **by name** (phase-3 review: positional filling put the dollar rate into a '엔화' card): named
    not-connected cards take numbers whose name or alias matches, 'KPI N' cards take the rest in order, leftovers become new cards
    (four per widget); a named card without a match stays as it is. Returns [{id, key}], key = the fetched name used by refreshes."""
    pending = [k for k in state.get("kpis") or [] if k.get("pending")]
    named = [k for k in pending if not _AUTO_LABEL.fullmatch(k["label"])]
    pairs = wd.match_numbers([k["label"] for k in named], numbers)
    plan = [(named[i], numbers[j]) for i, j in sorted(pairs.items())]
    rest = [n for j, n in enumerate(numbers) if j not in set(pairs.values())]
    for card in (k for k in pending if _AUTO_LABEL.fullmatch(k["label"])):
        if not rest:
            break
        plan.append((card, rest.pop(0)))
    plan += [(None, n) for n in rest]
    out = []
    for card, n in plan:
        if card is None and len(state.get("kpis") or []) >= hw.MAX_KPIS:
            break
        label = card["label"] if card is not None and not _AUTO_LABEL.fullmatch(card["label"]) else n["label"]
        kpi = rd.put_kpi(state, {"label": _put_label(state, label, card["id"] if card else ""), "value": n["value"],
                                 "unit": n["unit"] or (card or {}).get("unit") or "", "note": n["note"] or (card or {}).get("note") or ""},
                         card["id"] if card else "")
        out.append({"id": kpi["id"], "key": n["label"]})
    if not out:
        raise ValueError(f"위젯에는 KPI 카드를 {hw.MAX_KPIS}개까지 넣을 수 있습니다")
    return out


def _fetch(state: dict, ctx: dict, args: dict) -> tuple[str, str]:
    """fetch_data: 위젯 전용 데이터 파이프라인(app/widget_data.py)으로 가져와 위젯에 넣는다 / fetch through the widget pipeline and fill the widget"""
    request = rd._s(args.get("request"), 300)  # noqa: SLF001
    if not request:
        raise ValueError("가져올 내용을 한 문장으로 적어 주세요")

    def emit(kind, data):
        if kind == "plan":
            _draft(state, ctx, data)
            if ctx.get("emit") is not None:   # 화면에는 찾을 곳 · 모양 · 고른 곳인지만 / the screen gets places, view and whether they were chosen
                ctx["emit"]("plan", {"sources": list(data.get("sources") or []), "view": data.get("view") or "", "forced": bool(data.get("forced"))})
        elif kind in ("stage", "branch", "picked") and ctx.get("emit") is not None:
            ctx["emit"](kind, data)

    chosen = list(SCOPE_SOURCES.get(ctx["source"], (ctx["source"],))) if ctx.get("source") else None
    out = wd.fetch(request, ctx.get("eff"), view=args.get("view") if args.get("view") in wd.VIEWS else None, emit=emit,
                   sources=chosen, cancel=ctx.get("cancel"))
    plan, res, origin = out["plan"], out["result"], out["origin"]
    if res is None:
        why = ", ".join(f"{wd.SOURCE_LABEL[s]}: {w}" for s, w in out["tried"].items() if w)
        raise ValueError("요청한 내용을 찾지 못했습니다" + (f"({why})" if why else ""))
    if state["title"] == hw.NEW_TITLE and plan.get("title"):
        state["title"] = plan["title"][:hw.MAX_TITLE]
    kind = res["kind"]
    part = wd.PART_OF[kind]
    entry = {"part": part, "kind": origin, "query": plan["query"], "view": plan["view"], "sql": "", "sig": "", "tables": [],
             "refs": res.get("refs", []), "fetched_at": out["fetched_at"], "cards": []}
    if kind == "table":
        table = res["table"] if res["table"].get("tool") == "inline" else wd.table_source(res["table"]["columns"], res["table"]["rows"])
        if table is None:
            raise ValueError("가져온 표가 비어 있습니다")
        shown, _cards = _apply_table(state, ctx, table, plan)
        note = f"표 {len(table['rows'])}행 · 컬럼 {', '.join(table['columns'])}"
        if origin == "data" and res.get("sql"):   # 서버가 만든 SQL 에만 서명 / only server-made SQL is signed
            entry.update(sql=res["sql"], sig=hw.sign_sql(ctx.get("owner") or "", res["sql"]), tables=res.get("tables", []))
    elif kind == "numbers":
        entry["cards"] = _apply_numbers(state, res["numbers"])
        shown = "KPI 카드"
        note = ", ".join(f"{n['label']}={n['value']}{n['unit']}" for n in res["numbers"])
    else:
        block = {"type": "list", "items": res["items"]} if kind == "items" else {"type": "text", "text": res["text"]}
        ctx["extra"]["blocks"] = [b for b in ctx["extra"]["blocks"] if b["type"] != block["type"]] + [block]
        shown = "목록" if kind == "items" else "글"
        note = f"목록 {len(res['items'])}건" if kind == "items" else f"글 {len(res['text'])}자"
    # 부분마다 출처 하나(카드는 가져온 요청마다): 같은 부분의 예전 출처를 바꾸고, 다른 부분의 출처는 그대로 둔다(3단계 검토)
    # one origin per part (per fetch for cards): the same part's old origin is replaced and other parts keep theirs (phase-3 review)
    if part == "cards":
        for c in entry["cards"]:
            _release_card(ctx, c["id"])
        kept = ctx["extra"]["origins"]
    else:
        kept = [o for o in ctx["extra"]["origins"] if o["part"] != part]
    ctx["extra"]["origins"] = (kept + [entry])[-hw.MAX_ORIGINS:]
    label = wd.SOURCE_LABEL[origin]
    extra_note = f" {res['note']}" if res.get("note") else ""   # 예: 다른 기간으로 조회했다 / e.g. a different period was used
    return (f"{label}에서 가져와 {shown}(으)로 넣음 — {note}{extra_note}",
            f"{label}에서 가져와 {shown}(으)로 넣었습니다.{extra_note}")


def run_tool(state: dict, ctx: dict, name: str, args) -> tuple[str, str]:
    """도구 하나를 위젯 상태에 적용하고 (LLM 에 돌려줄 결과 메모, 사용자에게 보일 한 문장)을 돌려준다. 실패는 ValueError/AgentError.
    ctx = {insight: 지금 인사이트 틀, created: 이번 턴에 만든 데이터 연결 전 카드 id, ask: 데이터 질문}.
    Apply one tool to the widget state and return (a note for the LLM, one sentence for the user); failures raise.
    ctx = {insight: the current template, created: not-connected card ids made this turn, ask: a data question}."""
    args = dict(args) if isinstance(args, dict) else {}
    if name not in TOOL_NAMES:
        raise ValueError(f"위젯 에이전트에 없는 도구입니다: {name}")
    if name == "rename_widget":
        title = rd._s(args.get("title"), 200)  # noqa: SLF001
        if not title:
            raise ValueError("제목이 비어 있습니다")
        if len(title) > hw.MAX_TITLE:
            raise ValueError(f"위젯 제목은 {hw.MAX_TITLE}자까지 쓸 수 있습니다")
        state["title"] = title
        if state["charts"]:
            state["charts"][0]["title"] = title
        return f"위젯 제목을 \"{title}\"(으)로 변경", f"위젯 제목을 '{title}'(으)로 바꿨습니다."
    if name == "set_insight":
        text = hw.check_insight(args.get("text"), state, _comp(state))
        ctx["insight"] = text
        if not text:
            return "인사이트 삭제", "인사이트를 지웠습니다."
        shown, _ = hw.render_insight(text, hw.insight_values(state, _comp(state)))
        return f"인사이트 작성 — 지금 보이는 문장: {shown}", "인사이트를 썼습니다. 위젯 데이터가 바뀌면 숫자도 같이 바뀝니다."
    if name == "ask_data":
        question = rd._s(args.get("question"), 200) or ASK_TEXT  # noqa: SLF001
        ctx["ask"] = {"kind": "data", "question": question, "cards": [], "need": rd._s(args.get("need"), 80), "hint": ASK_HINT_DATA}  # noqa: SLF001
        return "사용자에게 연결할 데이터를 물었다", ""
    if name == "fetch_data":
        return _fetch(state, ctx, args)
    if name == "add_kpi":
        return _add_kpi(state, ctx, args)
    if name == "remove_kpi":
        return _remove_kpi(state, ctx, args)
    if name == "arrange_kpis":
        order = args.get("order")
        if isinstance(order, list):   # 이름이 정확히 같은 카드를 먼저 id 로 / exact names become ids first
            args["order"] = [_card_id(state, x) or x for x in order]
        return ra.run_tool(state, name, args, None, {})
    if not state["charts"]:
        raise ValueError(NO_CHART)
    for p in _DROP_PROPS.get(name, ()):
        args.pop(p, None)
    args["chart_id"] = hw.CHART_ID   # 차트는 하나뿐 / the only chart
    return ra.run_tool(state, name, args, None, {"focus": hw.CHART_ID})


def _pick_tools(prompt: str) -> dict:
    """도구 고르기 1회 — 리포트 에이전트와 같은 티어 규칙(기본 경량, 실패하면 다른 티어로 한 번 더) / one tool-picking call, the report agent's tier rule"""
    first = "main" if settings.REPORT_AGENT_TIER == "main" else "lite"
    try:
        return llm.generate_calls(prompt, system=SYSTEM, tools=TOOL_SPECS, tier=first)
    except Exception as e:  # noqa: BLE001
        other = "lite" if first == "main" else "main"
        logger.warning("위젯 에이전트 %s 티어 실패(%s), %s 티어로 재시도", first, type(e).__name__, other)
        return llm.generate_calls(prompt, system=SYSTEM, tools=TOOL_SPECS, tier=other)


def _notify(emit, kind: str, data: dict) -> None:
    """진행 알림(실패해도 턴은 계속) / a progress notice (a failure never stops the turn)"""
    if emit is None:
        return
    try:
        emit(kind, data)
    except Exception:  # noqa: BLE001
        logger.debug("위젯 에이전트 알림 실패 / notice failed", exc_info=True)


def _trace_entry(name: str, ok: bool, detail: str, say: str = "") -> dict:
    agent, label, group = tool_meta(name)
    return {"agent": agent, "group": group, "tool": name, "label": label, "ok": ok, "detail": detail[:300], "say": say[:200]}


def _says(trace: list[dict]) -> str:
    """성공한 도구의 문장을 겹치지 않게 최대 3개 / up to three distinct sentences of the tools that succeeded"""
    says: list[str] = []
    for t in trace:
        if t["ok"] and t.get("say") and t["say"] not in says:
            says.append(t["say"])
    return " ".join(says[:3]) + (f" 그 밖에 {len(says) - 3}건을 더 반영했습니다." if len(says) > 3 else "")


def _ask_for_pending(state: dict, ctx: dict) -> dict | None:
    """이번 턴에 만든 카드가 아직 데이터 연결 전이면 "어떤 데이터를 연결할까요?"라고 묻는다(질문은 고정 문장, 대상 카드는 cards).
    이름만 고친 카드는 다시 묻지 않는다: 사용자가 데이터를 말한 턴의 "아직 연결할 수 없다"는 답이 질문에 가려지지 않게.
    Ask "which data shall I connect?" about cards made this turn that are still unconnected (a fixed sentence; the cards ride in
    cards). A card that was only renamed is not asked about again, so a "cannot connect yet" reply is never buried under a question."""
    names = [k["label"] for k in state.get("kpis") or [] if k.get("pending") and k["id"] in ctx["created"]]
    if not names:
        return None
    return {"kind": "data", "question": ASK_TEXT, "cards": names, "need": "KPI 카드", "hint": ASK_HINT_KPI}


def run_turn(widget, messages, message: str, eff: dict | None = None, emit=None, owner: str = "", source: str | None = None,
             cancel=None) -> dict:
    """한 턴 — LLM 이 도구를 고르고 결과를 돌려주며 최대 MAX_ROUNDS 라운드. 반환: {widget, model, reply, trace, ask}.
    2026-11-19(대화 화면 2차): emit 이 round(라운드마다 고른 도구) · tool(도구 결과마다, trace 항목 + round) · plan · branch · picked 도
    알린다(화면의 생각 과정 = 출처 카드 · 위젯 편집 카드 · 단계 트리). source = 입력 카드에서 고른 가져올 곳(data · docs · web, 없으면 에이전트가
    고른다). cancel() 이 참이면(화면이 멈췄다) 라운드 · 도구 사이에서 wd.Cancelled 로 끝난다. trace 항목마다 round(1부터).
    2026-11-19 (chat round 2): emit also sends round (the tools picked per round), tool (each result: the trace entry plus its
    round), plan, branch and picked — the screen's thinking process. source = the place picked in the input card (data, docs,
    web; None lets the agent decide). When cancel() is true (the screen stopped) the turn ends with wd.Cancelled between rounds
    and tools. Every trace entry carries its round (from 1).
    widget 이 None 이면 새 작업본. 정의가 틀리면 SpecError, LLM 호출 실패는 그대로 올린다(작업본은 화면에 그대로 남는다).
    eff = 신원의 권한(None = 슈퍼, 데이터 가져오기의 사내 데이터 · 문서 범위), emit(kind, data) = 진행 알림(stage · draft, 스트림 응답용),
    owner = 신원(가져온 SQL 의 서명). 도구마다 결과가 정의로 맞는지 바로 확인해, 맞지 않으면 그 도구만 실패로 되돌린다(턴을 잃지 않게).
    One turn: the LLM picks tools and sees their results, up to MAX_ROUNDS rounds. Returns {widget, model, reply, trace, ask}.
    widget None starts a new draft. A wrong definition raises SpecError and an LLM failure propagates (the screen keeps its draft).
    eff = the identity's permissions (None = super; it scopes fetched company data and documents); emit(kind, data) reports progress
    (stage and draft, for the streamed answer); owner = the identity (signs fetched SQL). Every tool's result is checked against
    the definition rules at once, and a misfit rolls back as that tool's failure, so the turn is never lost."""
    clean = hw.normalize_spec(widget if widget is not None else {"v": hw.SPEC_VERSION}, draft=True)
    state = hw.to_state(clean)
    stopped = cancel if callable(cancel) else (lambda: False)
    source = source if source in SCOPE_LABEL else None
    ctx = {"insight": clean["insight"], "created": set(), "ask": None, "eff": eff, "emit": emit, "clean": clean, "owner": owner,
           "source": source, "cancel": stopped,
           "extra": {"source": clean["source"], "blocks": [dict(b) for b in clean["blocks"]], "origins": json.loads(json.dumps(clean["origins"]))}}
    note = (f"\n\n[가져올 곳] 사용자가 '{SCOPE_LABEL[source]}'에서만 가져오도록 정했다. fetch_data 는 그곳에서만 찾는다." if source else "")
    history = _history(messages)
    trace: list[dict] = []
    results: list[str] = []
    reply = ""
    for rnd in range(1, MAX_ROUNDS + 1):
        if stopped():
            raise wd.Cancelled()
        comp = _comp(state)
        values = hw.insight_values(state, comp)
        waiting = bool(ctx["insight"]) and hw.render_insight(ctx["insight"], values)[1]
        prompt = (f"[위젯 상태]\n{describe(state, ctx['insight'], values, waiting, ctx['extra'])}\n\n[대화 기록]\n{ra._history(history)}\n\n"  # noqa: SLF001
                  f"[요청]\n{message}{note}"
                  + ("\n\n[이번 턴 도구 실행 결과]\n" + "\n".join(results)
                     + "\n\n남은 일이 있으면 도구를 부르고, 없으면 도구 없이 사용자에게 답한다." if results else ""))
        res = _pick_tools(prompt)
        calls = res.get("calls") or []
        if res.get("text"):
            reply = res["text"]
        if not calls:
            break
        if stopped():
            raise wd.Cancelled()
        _notify(emit, "round", {"no": rnd, "tools": [{"tool": str(c.get("name") or "")[:40], "label": tool_meta(str(c.get("name") or ""))[1]}
                                                      for c in calls[:MAX_CALLS]]})
        followup = False
        for call in calls[:MAX_CALLS]:
            if stopped():
                raise wd.Cancelled()
            name = call.get("name") or ""
            # 실패한 도구는 아무것도 바꾸지 않는다: 일부를 고친 뒤 실패해도 그 앞으로 되돌린다(같은 턴의 다른 도구 결과는 지킨다)
            # a failed tool changes nothing: one that failed half-way is rolled back (the turn's other results stay)
            snap, insight, created = json.loads(json.dumps(state)), ctx["insight"], set(ctx["created"])
            extra = json.loads(json.dumps(ctx["extra"]))
            try:
                detail, say = run_tool(state, ctx, name, call.get("args") or {})
                hw.from_state(state, clean, ctx["insight"], ctx["extra"])   # 정의로 맞는가(크기 · 연결 · 형식) / does it fit a definition
                ok = True
            except wd.Cancelled:
                raise   # 멈춤은 도구 실패가 아니다 / a stop is not a tool failure
            except (ValueError, ra.AgentError) as e:
                detail, say, ok = str(e), "", False
            except Exception as e:  # noqa: BLE001 — 재사용한 도구의 뜻밖의 오류도 턴 전체를 잃지 않게 / an unexpected error in a reused tool never loses the turn
                logger.warning("위젯 에이전트 도구 %s 실패: %s", name, type(e).__name__)
                detail, say, ok = TOOL_BROKE, "", False
            if not ok:
                state.clear()
                state.update(snap)
                ctx["insight"], ctx["created"], ctx["extra"] = insight, created, extra
            trace.append({**_trace_entry(name, ok, detail, say), "round": rnd})
            _notify(emit, "tool", trace[-1])
            results.append(f"{len(results) + 1}. {name} → {'성공' if ok else '실패'}: {detail}")
            if ctx["ask"] is not None:
                break
            if name in _NEEDS_FOLLOWUP or not ok:
                followup = True
        if ctx["ask"] is not None or not followup:
            break   # 질문했거나 결과를 다시 볼 필요가 없으면 끝 / done after a question or when nothing needs another look
    ask = ctx["ask"] or _ask_for_pending(state, ctx)
    # 모델이 답에 인사이트 변수를 그대로 쓴 경우 지금 값으로 / a reply that leaked insight variables gets their current values
    reply = hw.fill_values(reply, hw.insight_values(state, _comp(state)))
    new = hw.from_state(state, clean, ctx["insight"], ctx["extra"])
    if ask is not None:   # 질문은 질문 칸이 보인다 — 답에는 한 일만 / the question shows in its own box; the reply holds what was done
        reply = _says(trace)
    elif not reply:
        reply = _says(trace) or ra._fallback_reply(trace)  # noqa: SLF001
    return {"widget": new, "model": hw.model_of(new), "reply": reply, "trace": trace, "ask": ask}
