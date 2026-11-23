"""리포트 에이전트(2026-09-18) — 대시보드 하나를 대화로 고치는 도구 호출 루프.

구조: 리포트 에이전트(오케스트레이터)가 요청을 받아 붙어 있는 도구를 부른다.
- Data Agent 도구: query_data(권한 범위 안에서 새로 조회해 Source 로 추가)
- Visualize Agent 도구: create_chart·update_chart·remove_chart·add_reference_line·remove_reference_line·set_style·
  add_filter·remove_filter·set_insight·arrange·rename_dashboard
  + 2026-09-21: add_calculation(계산 값 — 증감률·누계·구성비 등, 숫자는 코드가 계산)·add_highlight·remove_highlight(조건부 강조)·
  set_drill(드릴다운 순서)·add_kpi·remove_kpi·arrange_kpis(대시보드 맨 위 KPI 카드 = 요약 숫자 줄 — 대화로 만들고 고친다, 2026-10-12)·set_trend(추세선·간단한 예측)·set_theme(대시보드 테마).
  add_filter 는 컬럼 종류에 따라 값 목록 / 기간 범위(last_n·from·to) / 숫자 범위(min·max). 메모(주석)와 차트 복제는 도구가 아니라 화면 버튼이다(사용자 지시).
LLM 은 "무엇을 어떻게 그릴지"(설정)만 정하고 숫자는 report_dash.compute 가 계산한다. 도구 결과(계산된 값)를 다음 라운드에
돌려줘 인사이트를 실제 수치로 쓰게 한다. 맥락은 이 대시보드의 상태와 대화뿐이다 — 일반 채팅 기록은 넘기지 않는다.
"""
# Report agent (2026-09-18) — a tool-calling loop that edits one dashboard by conversation.
# The report agent (orchestrator) calls the tools attached to it: the Data Agent's query_data (a permission-gated
# query added as a source) and the Visualize Agent's chart/reference-line/style/filter/insight/layout tools. The LLM
# decides only the spec; report_dash.compute does the math, and the computed values are fed back so insights quote
# real numbers. The only context is this dashboard's state and conversation — chat history is never passed in.

import json
import logging
import re

from app import analytics, catalog, llm, report_dash as rd, report_drill, settings

logger = logging.getLogger("ai365.report_agent")

MAX_ROUNDS = 4
HISTORY_TURNS = 10
SAMPLE_ROWS = 5
RESULT_X_ITEMS = 20

DATA_AGENT = "Data Agent"
VIZ_AGENT = "Visualize Agent"

_CALC_DESC = ("계산 값(숫자는 시스템이 계산한다): share 구성비(%) · cum_share 누적 비중(%) · cumsum 누계 · pct_prev 직전 기간 대비 증감률(%) · "
              "diff_prev 직전 기간 대비 증감 · moving_avg 이동 평균(window) · yoy 전년 같은 기간 대비(%) · rank 순위 · "
              "ratio 두 값의 비율(column ÷ by_column) · ratio_pct 그 비율(%) · diff 두 값의 차이(column − by_column). "
              "pct_prev·diff_prev·moving_avg·yoy 는 x 가 [기간] 컬럼일 때만 쓴다.")

_Y_ITEM = {"type": "OBJECT", "properties": {
    "column": {"type": "STRING", "description": "값 컬럼 이름. 행 수를 세려면 '*'"},
    "agg": {"type": "STRING", "enum": list(rd.AGGS), "description": "집계 방법. 수량·금액·건수는 sum, 비율·평균·단가처럼 더하면 안 되는 값은 avg. 생략하면 컬럼 이름으로 고른다."},
    "name": {"type": "STRING", "description": "범례에 보일 이름(생략하면 컬럼 이름)"},
    "type": {"type": "STRING", "enum": ["bar", "line"], "description": "막대와 선을 섞을 때 이 계열의 모양"},
    "axis": {"type": "INTEGER", "description": "0=왼쪽 축, 1=오른쪽 축(단위가 크게 다른 계열)"},
    "calc": {"type": "STRING", "enum": list(rd.CALCS), "description": _CALC_DESC},
    "window": {"type": "INTEGER", "description": "moving_avg 의 구간 수(2~12, 기본 3)"},
    "by_column": {"type": "STRING", "description": "ratio·ratio_pct·diff 의 둘째 값 컬럼"},
    "by_agg": {"type": "STRING", "enum": list(rd.AGGS)},
    "unit": {"type": "STRING", "description": "이 계열만의 단위(생략하면 차트 단위)"}},
    "required": ["column"]}

_CHART_PROPS = {
    "type": {"type": "STRING", "enum": list(rd.CHART_TYPES),
             "description": "bar 세로 막대, hbar 가로 막대, line 선, area 영역, pie 원, donut 도넛, kpi 숫자 카드"},
    "title": {"type": "STRING", "description": "차트 제목"},
    "subtitle": {"type": "STRING", "description": "제목 아래 한 줄 설명"},
    "x": {"type": "STRING", "description": "x 축(범주) 컬럼 이름. kpi 는 생략"},
    "y": {"type": "ARRAY", "description": "값 계열 목록", "items": _Y_ITEM},
    "group": {"type": "STRING", "description": "이 컬럼의 값마다 계열을 나눈다(있으면 y 는 1개만)"},
    "sort_by": {"type": "STRING", "enum": list(rd.SORT_BY), "description": "none 데이터 순서, x 축 값 순, y 첫 계열 값 순"},
    "sort_dir": {"type": "STRING", "enum": ["asc", "desc"]},
    "limit": {"type": "INTEGER", "description": "정렬 뒤 앞에서 N개만(상위 N)"},
    "stack": {"type": "BOOLEAN", "description": "누적(막대·영역)"},
    "x_label": {"type": "STRING"}, "y_label": {"type": "STRING"},
    "unit": {"type": "STRING", "description": "값 뒤에 붙는 단위(예: %, 원, 건)"},
    "size": {"type": "STRING", "enum": list(rd.SIZES), "description": "half 반 폭, full 전체 폭"},
}

TOOL_SPECS = [
    {"name": "query_data",
     "description": "지금 Source 들에 없는 데이터(다른 테이블·기간·지표)가 필요할 때 사내 데이터에서 새로 조회해 Source 로 추가한다. 있는 Source 로 되는 일에는 부르지 않는다.",
     "parameters": {"type": "OBJECT", "properties": {
         "request": {"type": "STRING", "description": "조회할 내용(한국어 한 문장, 필요한 컬럼·기간·집계 단위를 분명히)"},
         "label": {"type": "STRING", "description": "이 데이터의 짧은 이름"}}, "required": ["request"]}},
    {"name": "create_chart", "description": "Source 하나로 새 차트를 만들어 대시보드에 추가한다.",
     "parameters": {"type": "OBJECT", "properties": {"source_id": {"type": "STRING", "description": "예: s1"}, **_CHART_PROPS},
                    "required": ["source_id", "type", "title"]}},
    {"name": "update_chart",
     "description": "있는 차트를 고친다 — 준 항목만 바뀐다. 계열 추가는 add_y, 계열 빼기는 remove_y(이름), 전부 바꾸려면 y.",
     "parameters": {"type": "OBJECT", "properties": {
         "chart_id": {"type": "STRING", "description": "예: c1"}, "source_id": {"type": "STRING"}, **_CHART_PROPS,
         "add_y": {"type": "ARRAY", "items": _Y_ITEM}, "remove_y": {"type": "ARRAY", "items": {"type": "STRING"}}},
         "required": ["chart_id"]}},
    {"name": "remove_chart", "description": "차트를 대시보드에서 지운다.",
     "parameters": {"type": "OBJECT", "properties": {"chart_id": {"type": "STRING"}}, "required": ["chart_id"]}},
    {"name": "add_reference_line",
     "description": "차트에 기준선(가로 점선)을 넣는다. 고정 값이면 value, 데이터에서 계산하려면 stat(평균·중앙값·최솟값·최댓값). 원·도넛·숫자 카드에는 넣을 수 없다.",
     "parameters": {"type": "OBJECT", "properties": {
         "chart_id": {"type": "STRING"}, "label": {"type": "STRING", "description": "선 옆에 보일 이름(예: 목표 0.3%)"},
         "value": {"type": "NUMBER"}, "stat": {"type": "STRING", "enum": list(rd.REF_STATS)},
         "series": {"type": "STRING", "description": "stat 을 계산할 계열 이름(생략하면 첫 계열)"},
         "color": {"type": "STRING", "description": "#RRGGBB"}}, "required": ["chart_id", "label"]}},
    {"name": "remove_reference_line", "description": "기준선을 지운다(label 생략 시 그 차트의 기준선 전부).",
     "parameters": {"type": "OBJECT", "properties": {"chart_id": {"type": "STRING"}, "label": {"type": "STRING"}},
                    "required": ["chart_id"]}},
    {"name": "add_calculation",
     "description": "차트에 계산 값 계열을 넣는다 — 직전 기간(전월·전년도) 대비 증감률·증감, 전년 같은 기간 대비, 누계, 구성비(비중), 누적 비중, 이동 평균, 순위, 두 컬럼의 비율·차이. 숫자는 시스템이 계산한다. replace=true 면 바탕 계열을 계산 값으로 바꾸고(\"증감률로 바꿔줘\"), 아니면 옆에 추가한다(\"증감률도 같이 보여줘\").",
     "parameters": {"type": "OBJECT", "properties": {
         "chart_id": {"type": "STRING"}, "calc": {"type": "STRING", "enum": list(rd.CALCS), "description": _CALC_DESC},
         "column": {"type": "STRING", "description": "바탕 값 컬럼(생략하면 차트의 첫 계열)"},
         "agg": {"type": "STRING", "enum": list(rd.AGGS)},
         "by_column": {"type": "STRING", "description": "ratio·ratio_pct·diff 의 둘째 값 컬럼"}, "by_agg": {"type": "STRING", "enum": list(rd.AGGS)},
         "window": {"type": "INTEGER", "description": "moving_avg 의 구간 수(2~12)"},
         "name": {"type": "STRING", "description": "범례에 보일 이름(생략하면 알맞게 붙인다)"},
         "replace": {"type": "BOOLEAN", "description": "true = 바탕 계열을 계산 값으로 바꾼다"}}, "required": ["chart_id", "calc"]}},
    {"name": "add_highlight",
     "description": "조건에 맞는 막대·점만 색을 달리해 강조한다(어느 것이 맞는지는 시스템이 판정한다). kind: value 고정 값과 비교(op·value) · stat 평균·중앙값과 비교(op·stat) · ref 기준선과 비교(op·ref_label — 그 기준선이 없으면 add_reference_line 을 먼저 부른다) · top 상위 n개 · bottom 하위 n개 · items 특정 항목(items). 색: 미달·위험 red, 달성·좋음 green, 주의 amber, 그 밖에 blue·gray·#RRGGBB(생략하면 알맞게 고른다). 원·도넛·숫자 카드에는 쓸 수 없다.",
     "parameters": {"type": "OBJECT", "properties": {
         "chart_id": {"type": "STRING"}, "kind": {"type": "STRING", "enum": list(rd.HL_KINDS)},
         "op": {"type": "STRING", "enum": list(rd.HL_OPS), "description": "lt 미만 · lte 이하 · gt 초과 · gte 이상"},
         "value": {"type": "NUMBER"}, "stat": {"type": "STRING", "enum": list(rd.HL_STATS)},
         "ref_label": {"type": "STRING", "description": "비교할 기준선의 이름"},
         "n": {"type": "INTEGER", "description": "top·bottom 의 개수"},
         "items": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "강조할 x 축 항목 이름"},
         "color": {"type": "STRING"}, "label": {"type": "STRING", "description": "범례에 보일 이름(예: 목표 미달)"},
         "dim": {"type": "BOOLEAN", "description": "조건에 안 맞는 나머지를 흐리게"},
         "series": {"type": "STRING", "description": "계열이 여럿일 때 판정할 계열 이름(생략하면 첫 계열)"}}, "required": ["chart_id", "kind"]}},
    {"name": "remove_highlight", "description": "강조 규칙을 지운다(label 생략 시 그 차트의 강조 전부).",
     "parameters": {"type": "OBJECT", "properties": {"chart_id": {"type": "STRING"}, "label": {"type": "STRING"}},
                    "required": ["chart_id"]}},
    {"name": "set_drill",
     "description": "드릴다운 순서를 정한다 — 사용자가 막대·조각을 누르면 그 값으로 좁혀 x 축이 columns 의 컬럼으로 차례로 내려간다(예: 지점 차트에 ['월','제품']). "
                    "컬럼은 그 차트의 Source 에 있거나, Source 의 조회 SQL 이 쓰는 원본 테이블의 글자·날짜 컬럼이면 된다(누를 때 서버가 그 단계를 조회한다). "
                    "사용자가 '브랜드 > 딜러사 > 전시장'·'눌러서 내려가며'·'계층으로'처럼 순서를 말하면 쓴다. 빈 목록이면 순서를 지운다(그래도 사용자는 누를 때 컬럼을 직접 고를 수 있다).",
     "parameters": {"type": "OBJECT", "properties": {
         "chart_id": {"type": "STRING"}, "columns": {"type": "ARRAY", "items": {"type": "STRING"}}}, "required": ["chart_id", "columns"]}},
    {"name": "set_style",
     "description": "차트 디자인을 바꾼다. chart_id 에 'all' 을 주면 모든 차트.",
     "parameters": {"type": "OBJECT", "properties": {
         "chart_id": {"type": "STRING"},
         "palette": {"type": "STRING", "enum": list(rd.PALETTES),
                     "description": "indigo 기본 남보라, ocean 파랑·청록, sunset 주황·분홍, forest 초록, mono 회색조, pastel 파스텔"},
         "labels": {"type": "BOOLEAN", "description": "값 라벨 표시"},
         "smooth": {"type": "BOOLEAN", "description": "선을 부드럽게"},
         "fill": {"type": "BOOLEAN", "description": "선 아래 채우기"},
         "legend": {"type": "STRING", "enum": list(rd.LEGENDS)},
         "rounded": {"type": "BOOLEAN", "description": "막대 모서리 둥글게"},
         "grid": {"type": "BOOLEAN", "description": "격자선"}}, "required": ["chart_id"]}},
    {"name": "add_filter",
     "description": "차트(BI) 하나에 필터 버튼을 만든다 — 필터는 차트마다 따로이고, 사용자가 그 컬럼의 값을 골라 그 차트만 걸러 본다. 컬럼은 그 차트의 Source 에 있어야 한다. 특정 값만 보이게 하려면 selected 에 값을 넣는다(같은 컬럼에 다시 부르면 선택 값이 바뀐다). 필터 모양은 컬럼 종류를 따른다: 글자 컬럼은 값 목록(selected), [기간] 컬럼은 범위(last_n 또는 from_value·to_value — '최근 3개월만'은 last_n=3), 숫자 컬럼은 min·max. 여러 차트에 각각 만들려면 chart_id 에 'all'.",
     "parameters": {"type": "OBJECT", "properties": {
         "chart_id": {"type": "STRING", "description": "예: c1. 선택된 차트가 있으면 그 차트. 'all' = 그 컬럼을 가진 모든 차트에 각각"},
         "column": {"type": "STRING"}, "label": {"type": "STRING", "description": "버튼 이름(생략하면 컬럼 이름)"},
         "selected": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "미리 골라 둘 값(생략하면 전체)"},
         "last_n": {"type": "INTEGER", "description": "[기간] 컬럼 전용: 최근 N개 기간만(데이터의 마지막 기간 기준). 예: 최근 3개월 = 3"},
         "from_value": {"type": "STRING", "description": "[기간] 컬럼 전용: 이 기간부터(그 컬럼에 있는 라벨 그대로, 예: 2025-03)"},
         "to_value": {"type": "STRING", "description": "[기간] 컬럼 전용: 이 기간까지"},
         "min": {"type": "NUMBER", "description": "숫자 컬럼 전용: 이 값 이상"}, "max": {"type": "NUMBER", "description": "숫자 컬럼 전용: 이 값 이하"}},
         "required": ["chart_id", "column"]}},
    {"name": "remove_filter", "description": "차트의 필터 버튼을 지운다(chart_id 에 'all' 이면 모든 차트에서).",
     "parameters": {"type": "OBJECT", "properties": {"chart_id": {"type": "STRING"}, "column": {"type": "STRING"}},
                    "required": ["chart_id", "column"]}},
    {"name": "set_trend",
     "description": "차트에 추세선과 간단한 예측을 넣거나 뺀다. x 가 [기간] 컬럼인 세로 막대·선·영역 차트에만 쓴다. line=true 면 추세선(지난 값들을 가장 가깝게 지나는 직선), forecast=N 이면 앞으로 N개 기간을 점선으로 이어 그린다(그 차트의 지난 값만으로 시스템이 계산한다 — 점이 6개 이상일 때만, 길이는 점 수의 1/3 까지, 최대 6). method: linear 직선 연장(기본) · seasonal 작년 같은 기간 × 최근 증가율(월·분기 데이터가 2년치 이상일 때). 지우려면 line=false, forecast=0.",
     "parameters": {"type": "OBJECT", "properties": {
         "chart_id": {"type": "STRING"}, "line": {"type": "BOOLEAN"}, "forecast": {"type": "INTEGER", "description": "예측할 기간 수(0 = 없음)"},
         "method": {"type": "STRING", "enum": ["linear", "seasonal"]},
         "series": {"type": "STRING", "description": "계열이 여럿일 때 대상 계열 이름(생략하면 첫 계열)"}}, "required": ["chart_id"]}},
    {"name": "set_theme",
     "description": "대시보드 테마를 정한다 — 회사 대표 색(brand_color, #RRGGBB) 하나에서 계열 색들을 만들어 모든 차트에 한 번에 입히고, 앞으로 만드는 차트도 따른다. 둘째 색(second_color)과 모서리·격자·범례·값 라벨 기본값도 같이 줄 수 있다. 색 이름만 들었으면(예: 청록, 남색) 알맞은 #RRGGBB 로 바꿔 준다. clear=true 면 테마를 지우고 기본 색으로 돌아간다. 차트 하나의 색만 바꾸는 일은 set_style 이다.",
     "parameters": {"type": "OBJECT", "properties": {
         "brand_color": {"type": "STRING", "description": "#RRGGBB"}, "second_color": {"type": "STRING", "description": "#RRGGBB(생략 가능)"},
         "rounded": {"type": "BOOLEAN"}, "grid": {"type": "BOOLEAN"}, "labels": {"type": "BOOLEAN"},
         "legend": {"type": "STRING", "enum": list(rd.LEGENDS)}, "clear": {"type": "BOOLEAN"}}}},
    {"name": "add_kpi",
     "description": "대시보드 맨 위 'KPI 카드(요약 숫자) 줄'에 카드 하나를 넣거나 고친다(최대 8개). 두 종류다 — ① 데이터에서 계산하는 카드: column(+agg, 합계·평균·건수 등)을 주면 숫자는 시스템이 계산한다(네가 숫자를 적지 않는다). ② 고정 숫자 카드: 사용자가 문장에서 말한 숫자(목표치 등)를 value 에 그대로 넣는다 — 사용자가 숫자를 말하지 않았으면 지어내지 말고 물어본다. 고치기: kpi_id(예: k1) 또는 있는 카드와 같은 label 을 주면 그 카드를 제자리에서 적은 항목만 바꾼다(이름·설명·단위·집계·컬럼·연결 차트·직전 기간 대비·숫자) — 적지 않은 항목은 그대로이고, 바뀐 게 없으면 실패한다. 끄기: delta='none', link_chart_id='none', unit·note 는 빈 문자열. 고정 숫자 카드에 column 을 주면 데이터 계산 카드로, 데이터 카드에 value 를 주면 고정 숫자 카드로 바뀐다(둘을 함께 주지 않는다). link_chart_id 를 주면 그 차트의 필터를 따라가고(같은 데이터의 차트만), delta='prev' 면 [기간] 컬럼이 있는 Source 에서 직전 기간 대비 증감률을 같이 보여 준다. 차트의 kpi 타입(카드 하나를 통째로 쓰는 큰 숫자)과는 다르다 — 여러 숫자를 한 줄로 보고 싶다는 요청은 이 도구다.",
     "parameters": {"type": "OBJECT", "properties": {
         "kpi_id": {"type": "STRING", "description": "고칠 카드 id(예: k1) 또는 그 카드의 이름. 새 카드면 생략"},
         "source_id": {"type": "STRING", "description": "예: s1(생략하면 첫 Source)"}, "column": {"type": "STRING", "description": "값 컬럼. 행 수는 '*'. 고정 숫자 카드면 생략"},
         "agg": {"type": "STRING", "enum": list(rd.AGGS)}, "label": {"type": "STRING", "description": "숫자 위에 보일 이름(예: 총 매출)"},
         "value": {"type": "NUMBER", "description": "고정 숫자 카드의 숫자 — 사용자가 말한 값만"},
         "unit": {"type": "STRING", "description": "단위(예: 원·%·건). 빈 문자열이면 지운다"}, "note": {"type": "STRING", "description": "카드 아래 한 줄 설명(예: 2026년 1분기 기준, 생략 가능). 빈 문자열이면 지운다"},
         "link_chart_id": {"type": "STRING", "description": "이 차트의 필터를 따라간다(생략 가능). 'none' 이면 연결을 끊는다"},
         "delta": {"type": "STRING", "enum": ["prev", "none"], "description": "prev = 직전 기간 대비 증감률 표시, none = 끄기"}}}},
    {"name": "remove_kpi", "description": "KPI 카드(요약 숫자)를 지운다 — label 또는 kpi_id 로 하나, 둘 다 생략하면 전부.",
     "parameters": {"type": "OBJECT", "properties": {"label": {"type": "STRING"}, "kpi_id": {"type": "STRING", "description": "예: k1"}}}},
    {"name": "arrange_kpis", "description": "KPI 카드 순서를 바꾼다 — 앞에 둘 순서대로 카드 id(k1) 또는 이름 목록. 적지 않은 카드는 그 뒤에 그대로 남는다.",
     "parameters": {"type": "OBJECT", "properties": {"order": {"type": "ARRAY", "items": {"type": "STRING"}}}, "required": ["order"]}},
    {"name": "set_insight", "description": "차트 아래 Insight 문장을 쓴다 — 도구 결과로 받은 실제 수치를 인용해 1~2문장.",
     "parameters": {"type": "OBJECT", "properties": {"chart_id": {"type": "STRING"}, "text": {"type": "STRING"}},
                    "required": ["chart_id", "text"]}},
    {"name": "arrange", "description": "차트 순서를 바꾼다(앞에 둘 순서대로 chart id 목록).",
     "parameters": {"type": "OBJECT", "properties": {"order": {"type": "ARRAY", "items": {"type": "STRING"}}},
                    "required": ["order"]}},
    {"name": "rename_dashboard", "description": "대시보드 제목을 바꾼다.",
     "parameters": {"type": "OBJECT", "properties": {"title": {"type": "STRING"}}, "required": ["title"]}},
]

# 도구 → (소속 에이전트, 화면에 보일 이름) / tool → (owning agent, label shown in the conversation)
TOOL_META = {
    "query_data": (DATA_AGENT, "데이터 조회"),
    "create_chart": (VIZ_AGENT, "차트 추가"), "update_chart": (VIZ_AGENT, "차트 수정"),
    "remove_chart": (VIZ_AGENT, "차트 삭제"), "add_reference_line": (VIZ_AGENT, "기준선 추가"),
    "remove_reference_line": (VIZ_AGENT, "기준선 삭제"), "set_style": (VIZ_AGENT, "디자인 변경"),
    "add_filter": (VIZ_AGENT, "필터 추가"), "remove_filter": (VIZ_AGENT, "필터 삭제"),
    "set_insight": (VIZ_AGENT, "인사이트 작성"), "arrange": (VIZ_AGENT, "배치 변경"),
    "rename_dashboard": (VIZ_AGENT, "제목 변경"),
    "add_calculation": (VIZ_AGENT, "계산 값 추가"), "add_highlight": (VIZ_AGENT, "강조 추가"),
    "remove_highlight": (VIZ_AGENT, "강조 삭제"), "set_drill": (VIZ_AGENT, "드릴다운 설정"),
    "add_kpi": (VIZ_AGENT, "KPI 카드 추가"), "remove_kpi": (VIZ_AGENT, "KPI 카드 삭제"), "arrange_kpis": (VIZ_AGENT, "KPI 카드 순서"),
    "set_trend": (VIZ_AGENT, "추세선·예측"), "set_theme": (VIZ_AGENT, "테마 설정"),
}
# 도구 → 화면 트리의 묶음(에이전트 › 묶음 › 도구) / tool → its group in the on-screen tree (agent › group › tool)
TOOL_GROUP = {
    "query_data": "데이터",
    "create_chart": "리포트", "update_chart": "리포트", "remove_chart": "리포트",
    "add_reference_line": "기준선", "remove_reference_line": "기준선",
    "add_calculation": "계산 값", "add_highlight": "강조", "remove_highlight": "강조", "set_drill": "드릴다운",
    "add_filter": "필터", "remove_filter": "필터",
    "set_style": "디자인", "set_theme": "디자인", "set_trend": "추세·예측", "add_kpi": "KPI 카드", "remove_kpi": "KPI 카드", "arrange_kpis": "KPI 카드",
    "set_insight": "정리", "arrange": "정리", "rename_dashboard": "정리",
}


def tool_tree() -> list[dict]:
    """리포트 에이전트에 붙은 도구를 트리로 — 화면의 도구 트리(무엇을 시킬 수 있나)와 실행 내역 트리가 같은 구조를 쓴다.
    도구를 더 붙이면(TOOL_SPECS·TOOL_META·TOOL_GROUP) 화면에도 그대로 나온다."""
    # The tools attached to the report agent as a tree; the on-screen tool tree and the activity tree share this structure,
    # so a tool added to TOOL_SPECS / TOOL_META / TOOL_GROUP shows up on screen as is.
    agents: list[dict] = []
    for spec in TOOL_SPECS:
        name = spec["name"]
        agent, label = TOOL_META.get(name, (VIZ_AGENT, name))
        a = next((x for x in agents if x["agent"] == agent), None)
        if a is None:
            a = {"agent": agent, "groups": []}
            agents.append(a)
        gname = TOOL_GROUP.get(name, "기타")
        g = next((x for x in a["groups"] if x["group"] == gname), None)
        if g is None:
            g = {"group": gname, "tools": []}
            a["groups"].append(g)
        g["tools"].append({"name": name, "label": label, "description": spec["description"]})
    return agents


# 결과 값을 본 뒤 한 번 더 생각해야 하는 도구(인사이트·다음 단계) / tools whose results need another round
_NEEDS_FOLLOWUP = {"query_data", "create_chart", "update_chart", "add_calculation"}

SYSTEM = """너는 사내 '리포트 에이전트'다. 사용자의 대시보드 하나를 대화로 만들고 고친다. 너에게는 Data Agent 도구(query_data)와 Visualize Agent 도구(차트·기준선·계산 값·강조·드릴다운·디자인·필터·인사이트·배치)가 붙어 있고, 대시보드는 도구를 불러서만 바뀐다.

규칙:
- [대시보드 상태]에 있는 Source id, 차트 id, 컬럼 이름만 쓴다. 없는 컬럼을 지어내지 않는다.
- 리포트(차트) 하나가 Source 하나다. 이미 차트가 있는 Source 로 create_chart 를 부르면 시스템이 그 데이터를 새 Source(다음 번호)로 복제해 거기에 차트를 만든다 — 너는 쓰고 싶은 데이터의 source_id 만 주면 된다. "~ 와 같은 데이터"라고 적힌 Source 는 그 Source 의 복제본이다.
- 차트의 숫자는 시스템이 계산한다. 너는 어느 Source 의 어느 컬럼을 어떻게 집계해 어떤 모양으로 그릴지만 정한다.
- 지금 Source 로 되는 요청이면 바로 차트 도구를 쓴다. Source 에 없는 데이터가 필요할 때만 query_data 를 먼저 부르고, 결과로 새 Source 가 생기면 다음 차례에 그 Source 로 차트를 만든다.
- "차트 하나 더", "추가로 보여줘"는 create_chart, "이 차트에 ~도 넣어줘", "막대를 선으로"는 update_chart, "기준선·목표선·평균선"은 add_reference_line, "색·디자인·라벨·범례"는 set_style, "필터·골라서 보게·~별로 볼 수 있게"는 add_filter 다.
- 필터는 차트(BI)마다 따로다. [선택된 차트]가 있으면 그 차트에, 없고 어느 차트인지 말하지 않았으면 그 컬럼을 가진 차트 전부에 각각 만든다(chart_id='all'). "2026년만 보여줘"처럼 값을 말하면 selected 에 넣는다.
- [선택된 차트]가 있으면 '이 차트', '여기' 같은 말은 그 차트를 가리킨다.
- [현재 화면]이 Source 탭이면 사용자는 그 Source 의 리포트를 보고 있다 — '이 차트', '이 데이터', '여기'는 그 Source 와 그 차트이고, "하나 더 만들어줘"는 그 Source 의 데이터로 create_chart 를 부른다(새 Source 탭이 생긴다). 바뀐 내용은 전체 대시보드에도 그대로 보인다(같은 차트다).
- 집계(agg): 수량·금액·건수처럼 더해도 되는 값은 sum, 비율·평균·단가·점수처럼 더하면 안 되는 값(률·율·%·평균)은 avg 를 쓴다. 비율은 Source 에 분자·분모 컬럼(예: 실적·목표)이 있으면 add_calculation 의 ratio_pct(분자 합 ÷ 분모 합)로 만든다 — 드릴다운·필터로 단계마다 다시 계산돼도 맞는 값이다. 비율 컬럼을 sum 으로 더하거나 원·도넛의 값으로 쓰지 않는다(도구가 거절한다).
- "전월 대비·전년 대비·증감률·누계·비중(구성비)·이동 평균·순위·두 값의 비율"은 add_calculation 이다 — 네가 숫자를 계산하지 말고 calc 만 고른다. "~도 같이·함께·추가로 보여줘"면 replace 를 주지 않고(바탕 값 옆에 추가된다), "~로 바꿔줘·~로 보여줘"일 때만 replace=true 를 준다. 새 차트를 처음부터 계산 값으로 만들 때는 create_chart 의 y 항목에 calc 를 준다. pct_prev·diff_prev·moving_avg·yoy 는 x 가 [기간] 표시가 있는 컬럼일 때만 쓴다(아니면 x 를 기간 컬럼으로 바꾸거나 안 된다고 답한다).
- "~는 빨간색으로·강조해줘·눈에 띄게·상위 N개만 색"은 add_highlight 다. 기준선도 함께 말했으면("목표 300 못 넘은 곳은 빨갛게") 같은 차례에 add_reference_line 을 먼저, add_highlight(kind=ref, ref_label=그 이름)를 다음에 부른다.
- "추세선·추이선·앞으로 어떻게 될지·예측·전망"은 set_trend 다(x 가 [기간] 컬럼인 차트에만). 예측은 시스템이 그 차트의 지난 값으로 계산한 참고용 값이다 — 네가 미래 숫자를 지어내지 않는다.
- "최근 N개월만·~부터 ~까지·~ 이상만"은 add_filter 의 last_n · from_value·to_value · min·max 다.
- "우리 회사 색으로·전체 색을 ~로·브랜드 색·테마"는 set_theme 이다(모든 차트 + 앞으로 만들 차트). "이 차트만 파랗게"는 set_style 이다.
- KPI 카드는 대화로 만들고 고친다. "맨 위에 숫자로·요약 숫자·KPI 카드·KPI 를 한 줄로·한눈에 합계"는 add_kpi 다(카드 하나에 한 번씩, 여러 개면 여러 번 부른다). 차트를 하나 더 만들지 않는다. [대시보드 상태]에 있는 카드의 이름·설명·단위·집계·컬럼·연결 차트·직전 기간 대비·숫자를 바꾸는 요청은 add_kpi 에 그 카드의 kpi_id(또는 이름)와 바꿀 항목만 준다. "목표 1,200 카드"처럼 사용자가 숫자를 말한 고정 숫자 카드는 value 에 그 숫자를 그대로 넣고, 숫자를 말하지 않았으면 지어내지 말고 물어본다. "직전 기간 대비 빼줘·연결 끊어줘·단위 지워줘"는 delta='none'·link_chart_id='none'·unit='' 이다. 순서는 arrange_kpis, 삭제는 remove_kpi(이름·id, 둘 다 없으면 전부)다. 카드가 처음부터 있지는 않다(요청해야 생긴다).
- 메모(주석)와 차트 복제는 사용자가 화면의 버튼으로 직접 한다 — 부탁받으면 카드의 메모·복제 버튼을 쓰라고 안내한다. [대시보드 상태]의 메모는 인사이트를 쓸 때 참고한다.
- "누르면 ~별로 보이게·드릴다운·안쪽을 보고 싶다", "브랜드 > 딜러사 > 전시장"처럼 내려갈 순서를 말하면 set_drill 이다(Source 에 없는 컬럼도 원본 테이블에 있으면 된다). [현재 화면]에 드릴다운 중이라고 적혀 있으면 사용자는 그 차트를 그 값으로 좁혀 보는 중이다 — "이걸 따로 차트로 만들어줘"는 보고 있는 컬럼을 x 로 create_chart 를 부르고 add_filter 로 그 값을 골라 둔다.
- 차트를 만들거나 데이터가 바뀌게 고쳤으면, 도구 결과로 받은 실제 값을 보고 set_insight 로 1~2문장 인사이트를 쓴다(수치 인용).
- 한 요청에 필요한 도구는 한 번에 여러 개 불러도 된다. 요청과 무관한 변경은 하지 않는다.
- 더 부를 도구가 없으면 도구 없이 사용자에게 한두 문장으로 무엇을 했는지 답한다. 사용자가 쓴 언어로 답한다(기본 한국어).
- 이 대화의 맥락은 이 대시보드뿐이다. 다른 채팅 내용은 모른다고 생각한다."""

AUTO_INSTRUCTION = ("각 Source 를 가장 잘 보여주는 차트를 Source 마다 하나씩 만들어 줘. 제목과 부제를 붙이고, 대시보드 제목도 "
                    "데이터에 맞게 정해 줘.")
REGEN_INSTRUCTION = "선택된 차트를 이 데이터를 더 잘 보여주는 모양으로 다시 만들어 줘(같은 차트를 update_chart 로 고친다)."


class AgentError(RuntimeError):
    """사용자에게 그대로 보여 줄 수 있는 실패 / a failure that is safe to show to the user"""


# ────────────────────────────────────────────────────────
# 프롬프트 재료 / prompt material
# ────────────────────────────────────────────────────────

def _col_profile(src: dict, col: str) -> str:
    ci = src["columns"].index(col)
    vals = [r[ci] for r in src["rows"] if r[ci] is not None and r[ci] != ""]
    pkind = (src.get("periods") or {}).get(col)
    if pkind:   # 기간 컬럼은 [기간] 표시 + 처음~끝 / a period column: a [period] mark plus first~last
        labels = sorted({rd.key(v) for v in vals}, key=lambda k: rd.period_key(k, pkind) or (0, 0))
        span = f"{labels[0]}~{labels[-1]}" if labels else ""
        return f"{col}([기간] {pkind} {len(labels)}개: {span})"
    if src["types"].get(col) == "number":
        nums = [n for n in (rd.num(v) for v in vals) if n is not None]
        return f"{col}(숫자 {rd.fmt(min(nums))}~{rd.fmt(max(nums))})" if nums else f"{col}(숫자)"
    distinct: list[str] = []
    for v in vals:
        k = rd.key(v)
        if k not in distinct:
            distinct.append(k)
    head = ", ".join(distinct[:8]) + (" …" if len(distinct) > 8 else "")
    return f"{col}(글자 {len(distinct)}종: {head})"


def _filter_text(f: dict) -> str:
    r = f.get("range") or {}
    if r.get("last"):
        return f"최근 {r['last']}개"
    if "from" in r:
        return f"{r.get('from') or '처음'}~{r.get('to') or '끝'}"
    if "min" in r:
        return f"{'' if r.get('min') is None else r['min']}~{'' if r.get('max') is None else r['max']}"
    return "|".join(f["selected"]) if f["selected"] else "전체"


def _y_text(y: dict) -> str:
    inner = f"{y['agg']}({y['col']})"
    if y.get("by"):
        inner += f", {y['by']['agg']}({y['by']['col']})"
    if y.get("calc"):
        inner = f"{y['calc']}[{inner}{', window=' + str(y['window']) if y.get('window') else ''}]"
    return f"{y['name']}={inner}/{y['type']}{'/우축' if y['axis'] else ''}"


def describe_state(state: dict, focus: str = "", view: str = "", drill: dict | None = None) -> str:
    lines = [f"제목: {state['title']}", "", "Sources:"]
    if not state["sources"]:
        lines.append("  (없음 — 데이터가 필요하면 query_data 로 조회한다)")
    for s in state["sources"]:
        if s["origin"].get("clone_of"):   # 복제본은 한 줄만(같은 컬럼·행을 되풀이하지 않는다) / a clone gets one line
            lines.append(f"  {s['id']} \"{s['name']}{' · ' + s['label'] if s['label'] else ''}\" = {s['origin']['clone_of']} 와 같은 데이터(컬럼·행 동일)")
            continue
        origin = {"chat": "채팅 답변의 조회 결과", "agent": "에이전트가 조회", "legacy": "예전에 저장한 값"}[s["origin"]["kind"]]
        lines.append(f"  {s['id']} \"{s['name']}{' · ' + s['label'] if s['label'] else ''}\" 행 {len(s['rows'])}개 · {origin}"
                     + (f" · 원본 테이블 {', '.join(s['tables'])}" if s["tables"] else ""))
        lines.append("    컬럼: " + "; ".join(_col_profile(s, c) for c in s["columns"]))
        for r in s["rows"][:SAMPLE_ROWS]:
            lines.append("    샘플: " + ", ".join(f"{c}={rd.key(v)[:30]}" for c, v in zip(s["columns"], r)))
    lines += ["", "차트:"]
    if not state["charts"]:
        lines.append("  (없음)")
    for c in state["charts"]:
        ys = ", ".join(_y_text(y) for y in c["y"])
        refs = ", ".join(f"{r['label']}={r['stat'] or r['value']}" for r in c["ref_lines"])
        flts = ", ".join(f"{f['col']}={_filter_text(f)}" for f in c["filters"])
        hls = ", ".join(h["label"] for h in c.get("highlights") or [])
        style = c["style"]
        lines.append(f"  {c['id']} [{c['type']}] \"{c['title']}\" source={c['source']} x={c['x']} y=[{ys}]"
                     + (f" group={c['group']}" if c["group"] else "")
                     + (f" sort={c['sort']['by']}/{c['sort']['dir']}" if c["sort"]["by"] != "none" else "")
                     + (f" limit={c['limit']}" if c["limit"] else "") + (" stack" if c["stack"] else "")
                     + (f" 기준선=[{refs}]" if refs else "") + (f" 강조=[{hls}]" if hls else "")
                     + (f" 드릴다운=[{' > '.join(c['drill'])}]" if c.get("drill") else "") + (f" 필터=[{flts}]" if flts else "")
                     + (" 메모=[" + ", ".join(f"{n['x']}:{n['text']}" for n in c["notes"]) + "]" if c.get("notes") else "")
                     + (f" 비교묶음={c['compare']}" if c.get("compare") else "")
                     + (f" 추세={'선' if c['trend']['line'] else ''}{'+예측' + str(c['trend']['forecast']) if c['trend']['forecast'] else ''}" if c.get("trend") else "")
                     + f" palette={style['palette']}{' labels' if style['labels'] else ''} size={c['size']}")
    if state.get("theme"):
        th = state["theme"]
        lines += ["", f"테마: 대표 색 {th['brand']}" + (f", 둘째 색 {th['second']}" if th.get("second") else "") + " (색 묶음 theme)"]
    if state.get("kpis"):
        lines += ["", "KPI 카드(대시보드 맨 위 요약 숫자 줄):"]
        for k in state["kpis"]:
            lines.append(f"  {k['id']} \"{k['label']}\" = "
                         + (f"직접 적은 숫자 {k.get('value')}" if not k.get("source") else f"{k['agg']}({k['col']}) source={k['source']}")
                         + (f" 연결 차트={k['link']}" if k.get("link") else "") + (" 직전 기간 대비" if k.get("delta") else "")
                         + (f" 단위={k['unit']}" if k.get("unit") else "") + (f" 설명=\"{k['note']}\"" if k.get("note") else ""))
    src = next((s for s in state["sources"] if s["id"] == view), None)
    if src is not None:
        own = [c["id"] for c in state["charts"] if c["source"] == src["id"]]
        lines += ["", f"[현재 화면] {src['name']}({src['id']}) 탭 — 이 Source 의 리포트 화면. 이 Source 의 차트: {', '.join(own) or '없음'}"]
    else:
        lines += ["", "[현재 화면] 전체 대시보드(모든 차트)"]
    # 드릴다운 중이면 무엇으로 좁혀 어느 컬럼을 보고 있는지 알려 준다(화면 상태일 뿐 저장되지 않는다)
    # While drilled down, say what the chart is narrowed by and which column is on the axis (a view state, never stored)
    dchart = next((c for c in state["charts"] if isinstance(drill, dict) and c["id"] == drill.get("chart")), None)
    path = [p for p in ((drill or {}).get("path") or []) if isinstance(p, dict) and p.get("col")][:rd.MAX_DRILL] if dchart else []
    if path:
        narrowed = ", ".join(f"{rd._s(p.get('col'), 80)}={rd._s(p.get('value'), 80)}" for p in path)
        lines.append(f"  드릴다운 중: 차트 {dchart['id']} 을(를) {narrowed} (으)로 좁혀 {rd._s(drill.get('level'), 80) or '다음 단계'}별로 보고 있다")
    picked = next((c for c in state["charts"] if c["id"] == focus), None) if focus else None
    if picked is not None:   # 대화 기록의 다른 차트에 끌려가지 않게 제목까지 적는다 / name it so the history's other charts do not win
        lines += ["", f"[선택된 차트] {focus} \"{picked['title']}\" — 요청의 '이 차트'·'여기'는 이 차트다"]
    return "\n".join(lines)


def _history(messages: list[dict]) -> str:
    out = []
    for m in (messages or [])[-HISTORY_TURNS:]:
        if m.get("silent") or not m.get("text"):
            continue
        tools = ", ".join(t.get("tool", "") for t in (m.get("trace") or []) if t.get("ok"))
        out.append(("사용자: " if m.get("role") == "user" else "에이전트: ") + str(m["text"])[:400]
                   + (f" (실행한 도구: {tools})" if tools else ""))
    return "\n".join(out) or "(없음)"


# ────────────────────────────────────────────────────────
# 데이터 조회(권한 게이트) / permission-gated data query
# ────────────────────────────────────────────────────────

SQL_SYSTEM = """너는 DuckDB SQL 생성기다. [스키마]의 테이블만 사용해 [조회 요청]을 만족하는 SELECT 단일문을 JSON으로만 출력한다.
출력 형식: {"sql": "SELECT ..."}
규칙: SELECT 단일문만(INSERT/UPDATE/DELETE/DDL 금지). 집계·정렬을 적절히 쓰고 컬럼·테이블명은 스키마 그대로 쓴다.
차트와 필터에 쓰기 좋게 범주 컬럼(기간·부서·제품 등)을 결과에 남긴다.
비율(달성률·전환율 등)은 AVG(비율 컬럼) 대신 SUM(분자)/SUM(분모)로 계산하고 분자·분모 합계도 컬럼으로 남긴다(드릴다운·필터로 단계마다 다시 계산할 수 있게).
상위 N개로 자르는 LIMIT 은 요청이 개수를 말할 때만 쓴다."""


def allowed_tables(eff: dict | None) -> set[str] | None:
    return None if eff is None else catalog.allowed_tables(eff)


def tables_in(sql: str) -> list[str]:
    low = (sql or "").lower()
    return sorted(t for t in catalog.all_table_names() if re.search(r"\b" + re.escape(t.lower()) + r"\b", low))


def query(request: str, eff: dict | None) -> tuple[list, list, str]:
    """Text2SQL 1회 — 신원의 허용 테이블로 스키마를 좁혀 생성·가드·실행. 실패는 AgentError(사용자에게 보일 문장)."""
    # One Text2SQL pass — schema narrowed to the identity's allowed tables, then guard and run.
    analytics.refresh_csv_views()
    allowed = allowed_tables(eff)
    if eff is not None and (not catalog.domain_readable(eff, "p_data") or not allowed):
        raise AgentError("데이터를 조회할 수 있는 테이블 권한이 없습니다")
    schema = analytics.schema_summary(allowed_tables=allowed)
    try:
        plan = llm.generate(f"[스키마]\n{schema}\n\n[조회 요청]\n{request}", system=SQL_SYSTEM, json_mode=True, tier="lite")
        guarded = analytics.guard_sql((plan or {}).get("sql") or "", allowed)
        columns, rows = analytics.run_select(guarded, allowed)
    except AgentError:
        raise
    except Exception as e:  # noqa: BLE001 — 생성·가드·실행 어느 단계든 한 문장으로 돌려준다 / any stage fails as one sentence
        logger.warning("리포트 에이전트 데이터 조회 실패: %s", e)
        raise AgentError(f"데이터 조회에 실패했습니다: {e}") from e
    if not columns:
        raise AgentError("조회 결과에 컬럼이 없습니다")
    return columns, rows, guarded


def refresh_sources(state: dict, eff: dict | None) -> tuple[dict, list[dict]]:
    """저장된 조회 SQL 을 지금 신원의 권한으로 다시 실행 — SQL 없는 Source(옛 저장분 등)와 권한 밖 조회는 그대로 둔다."""
    # Re-run each stored SQL under the current identity's permissions; sources without SQL and queries outside the
    # permission stay as they are.
    analytics.refresh_csv_views()
    allowed = allowed_tables(eff)
    report = []
    for s in state["sources"]:
        if s["origin"].get("clone_of"):   # 복제본은 원본을 가리키므로 원본만 다시 조회하면 된다 / clones follow their root
            continue
        if not s.get("sql"):
            report.append({"id": s["id"], "ok": False, "reason": "조회 SQL 이 없는 데이터입니다"})
            continue
        try:
            columns, rows = analytics.run_select(s["sql"], allowed)
        except Exception as e:  # noqa: BLE001
            report.append({"id": s["id"], "ok": False, "reason": f"다시 조회하지 못했습니다: {e}"[:200]})
            continue
        if columns != s["columns"]:
            report.append({"id": s["id"], "ok": False, "reason": "조회 결과의 컬럼이 바뀌어 그대로 두었습니다"})
            continue
        s["rows"], s["fetched_at"] = rows, rd._now()
        report.append({"id": s["id"], "ok": True, "rows": len(rows)})
    return rd.normalize_state(state), report


# ────────────────────────────────────────────────────────
# 도구 실행 / tool execution
# ────────────────────────────────────────────────────────

def _loose_id(value, prefix: str, words: str) -> str:
    """LLM 이 'Source 1', '차트 2', '3' 처럼 부른 id 를 's1'·'c2' 꼴로 / turn 'Source 1', 'chart 2' or '3' into 's1' / 'c2'"""
    v = str(value or "").strip()
    m = re.fullmatch(rf"(?i)(?:{words}|{prefix})?\s*[-_#]?\s*(\d{{1,3}})", v)
    return f"{prefix}{int(m.group(1))}" if m else v


def _src_id(state: dict, value) -> str:
    v = _loose_id(value, "s", "source|소스")
    if any(s["id"] == v for s in state["sources"]):
        return v
    low = str(value or "").strip().lower()
    return next((s["id"] for s in state["sources"] if low and low in (s["name"].lower(), (s["label"] or "").lower())), v)


def _kpi_id(state: dict, value) -> str:
    """LLM 이 'k1'·'KPI 1'·'카드 2'·카드 이름으로 부른 KPI 카드 → id, 없으면 '' / a KPI card named by a loose id or its label → its id, else ''"""
    want, text = _loose_id(value, "k", "kpi|카드|card|요약"), str(value or "").strip()
    return next((k["id"] for k in state.get("kpis") or [] if k["id"] == want or (text and k["label"] == text)), "")


def _chart(state: dict, cid) -> dict:
    want = _loose_id(cid, "c", "chart|차트|리포트")
    c = next((c for c in state["charts"] if c["id"] == want), None)
    if c is None:   # 제목으로 부른 경우 / called by its title
        title = str(cid or "").strip().strip("'\"")
        c = next((x for x in state["charts"] if title and x["title"] == title), None)
    if c is None:
        raise ValueError(f"'{cid}' 차트가 없습니다. 있는 차트: " + (", ".join(c["id"] for c in state["charts"]) or "없음"))
    return c


def _sources(state: dict) -> dict[str, dict]:
    return {s["id"]: s for s in state["sources"]}


def _values_note(state: dict, chart: dict) -> str:
    comp = rd.compute(chart, _sources(state)[chart["source"]])
    x = comp["x"][:RESULT_X_ITEMS]
    parts = [f"x={x}"] + [f"{s['name']}={s['values'][:RESULT_X_ITEMS]}" for s in comp["series"]]
    if comp["refs"]:
        parts.append("기준선=" + ", ".join(f"{r['label']}:{r['value']}" for r in comp["refs"]))
    return " ".join(parts) + (f" (전체 {len(comp['x'])}개 중 앞 {RESULT_X_ITEMS}개)" if len(comp["x"]) > RESULT_X_ITEMS else "")


# 더하면 틀리는 비율 — 받은 드릴다운 코드의 RATE_LIKE 낱말(율 · 률 · % · 비중 · rate · ratio · share) + pct · percent. 도구를 거절하는 데 쓰므로
# 더 좁게 본다: 한글은 이름 끝(달성률 · 이자율(%) — 법률자문비는 아니다), 영어는 단어로(conversion_rate · avg_pct — corporate_sales 는 아니다).
# 평균 · 단가 · 점수는 기본 집계만 avg 로 둔다(_RATE_COL).
# Rates that break when added: the reviewed code's RATE_LIKE words plus pct and percent, read narrowly since they refuse a tool
# call: Korean suffixes only at the end of the name, English words only as words.
_RATE_ONLY = rd.RATE_ONLY   # KPI 카드 편집(put_kpi)과 같은 규칙 / the same rule as the KPI card editor (put_kpi)


def _rate_check(chart: dict, before: dict | None = None) -> None:
    """비율 컬럼을 더하거나(sum) 원·도넛으로 나누는 설정을 도구 호출에서 거절한다 — 드릴다운 · 필터로 단계마다 다시 계산하면 비율의 합이 되어
    오류 없이 틀린 수가 나온다. 이 호출이 새로 만들거나 바꾼 계열(또는 원·도넛으로 바꾼 차트)만 본다 — 저장분은 그대로 읽힌다.
    Refuse, on a tool call, a rate column that is summed or sliced into a pie or donut: re-aggregating per drill level or filter
    would add rates up and give wrong numbers silently. Only series this call made or changed (or a chart it turned into a
    pie) are checked, so saved dashboards still load."""
    old = {rd._y_key(y) for y in (before or {}).get("y") or []}
    pie = chart["type"] in ("pie", "donut")
    became_pie = pie and (before is None or before.get("type") not in ("pie", "donut"))
    for y in chart["y"]:
        if y["col"] == "*" or not _RATE_ONLY.search(y["col"]) or (rd._y_key(y) in old and not became_pie):
            continue
        if y["agg"] == "sum":
            raise ValueError(f"'{y['col']}'는 비율이라 더하면 틀립니다(드릴다운·필터로 다시 계산할 때도). avg 를 쓰거나, 분자·분모 컬럼이 있으면 "
                             "add_calculation 의 ratio_pct(분자 합 ÷ 분모 합)로 만드세요")
        if pie and y["agg"] != "count":
            raise ValueError(f"원·도넛은 더할 수 있는 값(건수·금액)으로 나눕니다. '{y['col']}'는 비율이라 조각 크기가 뜻을 잃습니다 — 막대로 그리세요")


def _spec_from_args(args: dict) -> dict:
    spec = {k: args[k] for k in ("type", "title", "subtitle", "x", "y", "group", "limit", "stack", "unit", "size") if k in args}
    if "x_label" in args:
        spec["xLabel"] = args["x_label"]
    if "y_label" in args:
        spec["yLabel"] = args["y_label"]
    if "sort_by" in args or "sort_dir" in args:
        spec["sort"] = {"by": args.get("sort_by") or "none", "dir": args.get("sort_dir")}
    if "y" in spec:
        spec["y"] = [dict(y) if isinstance(y, dict) else {"column": y} for y in (spec["y"] or [])]
    return spec


def _filter_targets(state: dict, chart_id, scope: dict | None) -> list[dict]:
    """필터 도구의 대상 차트 — 'all'(또는 빈 값)이면 선택된 차트 → 현재 Source 탭의 차트 → 모든 차트 순으로 좁힌다."""
    # Target charts of a filter tool: 'all' (or blank) narrows to the focused chart, then the current Source tab's
    # charts, then every chart.
    cid = str(chart_id or "").strip()
    scope = scope or {}
    if cid and cid.lower() != "all":
        return [_chart(state, cid)]
    if not cid and scope.get("focus") and any(c["id"] == scope["focus"] for c in state["charts"]):
        return [_chart(state, scope["focus"])]
    in_view = _view_charts(state, scope.get("view"))
    return in_view if in_view is not None else list(state["charts"])


def _view_charts(state: dict, view) -> list[dict] | None:
    """Source 탭에서 '모든 차트' = 그 데이터(원본과 복제본)로 만든 리포트들. 전체 대시보드면 None."""
    # On a Source tab "every chart" means the reports built from that data (the source and its clones); None on the full dashboard.
    by_id = _sources(state)
    if not view or view not in by_id:
        return None
    root = rd.lineage(by_id[view])
    return [c for c in state["charts"] if rd.lineage(by_id[c["source"]]) == root]


def run_tool(state: dict, name: str, args: dict, eff: dict | None, scope: dict | None = None) -> tuple[str, str]:
    """도구 하나를 상태에 적용하고 (LLM 에 돌려줄 결과 메모, 사용자에게 보일 한 문장)을 돌려준다.
    실패는 ValueError/AgentError(문장은 LLM 과 화면에 그대로 간다)."""
    # Apply one tool to the state and return (a result note for the LLM, one sentence for the user); failures raise with
    # a sentence that goes to the LLM and the UI as is.
    args = args if isinstance(args, dict) else {}
    sources = _sources(state)

    if name == "query_data":
        if len(state["sources"]) >= rd.MAX_SOURCES:
            raise ValueError(f"Source 는 {rd.MAX_SOURCES}개까지입니다")
        request = str(args.get("request") or "").strip()
        if not request:
            raise ValueError("조회할 내용이 비어 있습니다")
        columns, rows, sql = query(request, eff)
        src = rd.norm_source({"columns": columns, "rows": rows, "sql": sql, "tables": tables_in(sql),
                              "label": args.get("label") or request[:40],
                              "origin": {"kind": "agent", "note": request}}, set(sources))
        state["sources"].append(src)
        return (f"{src['id']}({src['name']}) 추가 — 행 {len(rows)}개, 컬럼: "
                + "; ".join(_col_profile(src, c) for c in src["columns"]),
                f"새 데이터를 조회해 {src['name']}(으)로 추가했습니다.")

    if name == "create_chart":
        if len(state["charts"]) >= rd.MAX_CHARTS:
            raise ValueError(f"차트는 {rd.MAX_CHARTS}개까지입니다")
        spec = _spec_from_args(args)
        # 리포트 하나 = Source 하나: 그 Source 에 이미 차트가 있으면 데이터를 새 Source 로 복제해 새 탭을 만든다
        # One report = one source: a source that already has a chart is cloned into a new source (a new tab)
        spec["source"], cloned = rd.source_for_new_chart(state, _src_id(state, args.get("source_id") or (scope or {}).get("view") or ""))
        if state.get("theme"):   # 테마가 있으면 새 차트도 테마를 따른다 / with a theme, new charts follow it
            spec["style"] = rd.theme_style(state["theme"])
        elif state["charts"]:   # 새 차트는 직전 차트의 색·라벨 설정을 잇는다(대시보드 톤 유지) / a new chart inherits the last chart's palette and labels
            last = state["charts"][-1]["style"]
            spec["style"] = {"palette": last["palette"], "labels": last["labels"]}
        try:
            chart = rd.norm_chart(spec, _sources(state), {c["id"] for c in state["charts"]}, strict=True)
            _rate_check(chart)
        except ValueError:
            if cloned:
                state["sources"].pop()   # 차트를 못 만들었으면 복제한 Source 도 물린다 / roll the clone back when the chart failed
            raise
        src = _sources(state)[chart["source"]]
        if cloned or not src["label"]:
            src["label"] = chart["title"][:80]
        state["charts"].append(chart)
        return (f"차트 {chart['id']} \"{chart['title']}\" 추가(데이터 {src['id']}). 값: {_values_note(state, chart)}",
                f"'{chart['title']}' 리포트를 추가했습니다.")

    if name == "update_chart":
        cur = _chart(state, args.get("chart_id"))
        merged = {**cur, **_spec_from_args(args)}
        if args.get("source_id") and _src_id(state, args["source_id"]) != cur["source"]:
            rest = {**state, "charts": [c for c in state["charts"] if c is not cur]}
            merged["source"], _ = rd.source_for_new_chart(rest, _src_id(state, args["source_id"]))   # 다른 차트가 쓰는 Source 면 복제 / clone when taken
            state["sources"] = rest["sources"]
            sources = _sources(state)
        ys = [dict(y) for y in (merged.get("y") or [])]
        if args.get("type") and args["type"] != cur["type"] and "y" not in args:
            for y in ys:   # 모양을 바꾸면 기존 계열도 새 모양을 따른다(막대 → 선) / existing series follow the new type
                y.pop("type", None)
        drop = {str(n).strip() for n in (args.get("remove_y") or [])}
        if drop:
            ys = [y for y in ys if y.get("name") not in drop and y.get("col") not in drop and y.get("column") not in drop]
        ys += [dict(y) if isinstance(y, dict) else {"column": y} for y in (args.get("add_y") or [])]
        merged["y"] = ys
        if "type" in args and "style" in cur:   # 영역으로 바꾸면 채우기를 켠다 / switching to an area turns the fill on
            merged["style"] = {**cur["style"], "fill": args["type"] == "area" or (cur["style"]["fill"] and args["type"] == "line")}
        others = {c["id"] for c in state["charts"] if c["id"] != cur["id"]}
        chart = rd.norm_chart(merged, sources, others, strict=True)
        _rate_check(chart, cur)
        state["charts"][state["charts"].index(cur)] = chart
        return (f"차트 {chart['id']} \"{chart['title']}\" 수정. 값: {_values_note(state, chart)}",
                f"'{chart['title']}' 차트를 수정했습니다.")

    if name == "add_calculation":
        cur = _chart(state, args.get("chart_id"))
        calc = args.get("calc")
        if calc not in rd.CALCS:
            raise ValueError("calc 는 다음 중 하나여야 합니다: " + ", ".join(rd.CALCS))
        src = sources[cur["source"]]
        want = rd.resolve_col(args.get("column"), src["columns"]) if args.get("column") else None
        plain = [y for y in cur["y"] if not y.get("calc")]
        base = next((y for y in plain if y["col"] == want), None) if want else (plain[0] if plain else cur["y"][0])
        item = {"column": want or (base or cur["y"][0])["col"], "agg": args.get("agg") or (base or {}).get("agg"),
                "calc": calc, "window": args.get("window"), "by_column": args.get("by_column"), "by_agg": args.get("by_agg"),
                "name": args.get("name")}
        if not item["name"] and base is not None and calc not in rd.PAIR_CALCS:
            item["name"] = f"{base['name']} {rd.CALC_LABEL[calc]}"   # 화면에 보이던 이름을 잇는다("실적 합계 증감률") / keep the displayed name
        # 계열을 하나만 그리는 차트(그룹·가로 막대)는 옆에 둘 자리가 없어 바꾼다 / single-series charts have no room beside: replace
        replace = bool(args.get("replace")) or bool(cur["group"]) or cur["type"] == "hbar"
        ys = [dict(y) for y in cur["y"]]
        if replace and base is not None:
            ys[cur["y"].index(base)] = {**item, "type": base["type"], "axis": base["axis"]}
        else:   # 옆에 두는 계산 값은 선으로 — 바탕 값과 눈금이 같은 것(이동 평균·차이)만 같은 축, 나머지는 오른쪽 축
            # a calc beside its base is a line; only same-scale ones (moving average, difference) share the axis
            replace = False
            ys.append({**item, "type": "line", "axis": 0 if calc in ("moving_avg", "diff") else 1})
        others = {c["id"] for c in state["charts"] if c["id"] != cur["id"]}
        chart = rd.norm_chart({**cur, "y": ys}, sources, others, strict=True)
        _rate_check(chart, cur)
        made = next((y for y in chart["y"] if y.get("calc") == calc), None)
        if made is None:
            raise ValueError("계산 값을 넣지 못했습니다(이미 같은 계산이 있거나 계열 수가 가득 찼습니다)")
        state["charts"][state["charts"].index(cur)] = chart
        return (f"차트 {chart['id']} \"{chart['title']}\"에 계산 값 \"{made['name']}\"({calc}) {'적용' if replace else '추가'}. 값: {_values_note(state, chart)}",
                f"'{chart['title']}'에 '{made['name']}' 값을 {'적용' if replace else '추가'}했습니다.")

    if name == "add_highlight":
        cur = _chart(state, args.get("chart_id"))
        if cur["type"] in ("pie", "donut", "kpi"):
            raise ValueError("원·도넛·숫자 카드에는 강조를 쓸 수 없습니다")
        have = cur.get("highlights") or []
        rule = rd.norm_highlight(args, cur["ref_lines"], {h["id"] for h in have})
        if rule is None:
            raise ValueError("강조 조건이 부족합니다 — value 는 op·value, stat 은 op·stat, ref 는 있는 기준선 이름(ref_label), "
                             "top·bottom 은 n, items 는 항목 이름이 필요합니다. 이 차트의 기준선: "
                             + (", ".join(r["label"] for r in cur["ref_lines"]) or "없음"))
        keep = [h for h in have if h["label"] != rule["label"]]
        if len(keep) >= rd.MAX_HIGHLIGHTS:
            raise ValueError(f"강조는 차트마다 {rd.MAX_HIGHLIGHTS}개까지입니다")
        cur["highlights"] = keep + [rule]
        comp = rd.compute(cur, sources[cur["source"]])
        mark = next((m for m in comp.get("marks") or [] if m["id"] == rule["id"]), {"hits": []})
        names = [comp["x"][i] for i in mark["hits"]]
        return (f"\"{cur['title']}\"에 강조 \"{rule['label']}\" 추가 — 해당 {len(names)}개: {names[:RESULT_X_ITEMS]}",
                f"'{cur['title']}'에서 '{rule['label']}' {len(names)}곳을 강조했습니다." if names
                else f"'{cur['title']}'에 '{rule['label']}' 강조를 넣었지만 지금은 해당하는 항목이 없습니다.")

    if name == "remove_highlight":
        cur = _chart(state, args.get("chart_id"))
        label = str(args.get("label") or "").strip()
        have = cur.get("highlights") or []
        keep = [h for h in have if label and label not in (h["label"], h["id"])]
        if len(keep) == len(have):
            raise ValueError("지울 강조가 없습니다")
        cur["highlights"] = keep
        return f"\"{cur['title']}\"의 강조 {len(have) - len(keep)}개 삭제", f"'{cur['title']}'의 강조를 지웠습니다."

    if name == "set_drill":
        cur = _chart(state, args.get("chart_id"))
        if cur["type"] == "kpi":
            raise ValueError("숫자 카드에는 드릴다운을 쓸 수 없습니다")
        src = sources[cur["source"]]
        path, remote = [], None   # remote: 서버가 내려갈 수 있는 원본 테이블 컬럼(필요할 때 한 번만 찾는다) / base columns the server can drill into, looked up once
        for raw_col in (args.get("columns") or []):
            col = rd.resolve_col(raw_col, src["columns"])
            if col is None and src.get("sql"):   # 받아 둔 데이터에 없으면 원본 테이블에서 — 누를 때 서버가 그 단계를 조회한다 / else from the base tables
                if remote is None:
                    remote = report_drill.dimensions_of(src["sql"], eff)
                col = rd.resolve_col(raw_col, remote)
            if col is None:
                usable = list(dict.fromkeys(src["columns"] + (remote or [])))
                where = f"{src['name']} 에도 원본 테이블에도" if src.get("sql") else f"{src['name']} 에"
                raise ValueError(f"'{raw_col}' 컬럼이 {where} 없습니다. 쓸 수 있는 컬럼: " + ", ".join(usable))
            if col not in (cur["x"], cur["group"]) and col not in path:
                path.append(col)
        cur["drill"] = path[:rd.MAX_DRILL]
        if not path:
            return f"\"{cur['title']}\"의 드릴다운 순서 삭제", f"'{cur['title']}'의 드릴다운 순서를 지웠습니다."
        return (f"\"{cur['title']}\" 드릴다운: {cur['x']} > {' > '.join(cur['drill'])}",
                f"'{cur['title']}'의 막대를 누르면 {' → '.join(cur['drill'])} 순서로 내려가도록 했습니다.")

    if name == "remove_chart":
        cur = _chart(state, args.get("chart_id"))
        state["charts"].remove(cur)
        return f"차트 \"{cur['title']}\" 삭제", f"'{cur['title']}' 차트를 지웠습니다."

    if name == "add_reference_line":
        cur = _chart(state, args.get("chart_id"))
        if cur["type"] in ("pie", "donut", "kpi"):
            raise ValueError("원·도넛·숫자 카드에는 기준선을 넣을 수 없습니다")
        if len(cur["ref_lines"]) >= rd.MAX_REF_LINES:
            raise ValueError(f"기준선은 차트마다 {rd.MAX_REF_LINES}개까지입니다")
        ref = rd.norm_ref(args, {r["id"] for r in cur["ref_lines"]})
        if ref is None:
            raise ValueError("기준선에는 value(고정 값)나 stat(avg·median·min·max) 중 하나가 필요합니다")
        cur["ref_lines"] = [r for r in cur["ref_lines"] if r["label"] != ref["label"]] + [ref]
        comp = rd.compute(cur, sources[cur["source"]])
        value = next((r["value"] for r in comp["refs"] if r["id"] == ref["id"]), ref["value"])
        return (f"\"{cur['title']}\"에 기준선 \"{ref['label']}\"({value}) 추가",
                f"'{cur['title']}'에 기준선 '{ref['label']}'({rd.fmt(value, cur.get('unit') or '')})을 넣었습니다.")

    if name == "remove_reference_line":
        cur = _chart(state, args.get("chart_id"))
        label = str(args.get("label") or "").strip()
        before = len(cur["ref_lines"])
        cur["ref_lines"] = [r for r in cur["ref_lines"] if label and r["label"] != label]
        if before == len(cur["ref_lines"]):
            raise ValueError("지울 기준선이 없습니다")
        return f"\"{cur['title']}\"의 기준선 {before - len(cur['ref_lines'])}개 삭제", f"'{cur['title']}'의 기준선을 지웠습니다."

    if name == "set_style":
        target = str(args.get("chart_id") or "").strip()
        in_view = _view_charts(state, (scope or {}).get("view"))
        charts = (in_view or state["charts"]) if target.lower() == "all" else [_chart(state, target)]
        if not charts:
            raise ValueError("디자인을 바꿀 차트가 없습니다")
        for c in charts:
            c["style"] = rd.norm_style(args, c["type"], c["style"])
        changed = ", ".join(f"{k}={args[k]}" for k in ("palette", "labels", "smooth", "fill", "legend", "rounded", "grid") if k in args)
        return (f"차트 {len(charts)}개의 디자인 변경({changed or '변경 없음'})",
                "모든 차트의 디자인을 바꿨습니다." if len(charts) > 1 else f"'{charts[0]['title']}'의 디자인을 바꿨습니다.")

    if name == "add_filter":
        raw = {"col": args.get("column"), "label": args.get("label"), "selected": args.get("selected") or [],
               **{k: args[k] for k in ("last_n", "from_value", "to_value", "min", "max") if args.get(k) is not None}}
        ranged = any(k in raw for k in ("last_n", "from_value", "to_value", "min", "max"))
        done, last_err = [], ""
        for c in _filter_targets(state, args.get("chart_id"), scope):
            try:
                flt = rd.norm_filter(raw, sources[c["source"]], {f["id"] for f in c["filters"]})
            except ValueError as e:
                last_err = str(e)
                continue
            same = next((f for f in c["filters"] if f["col"] == flt["col"]), None)
            if same is None and len(c["filters"]) >= rd.MAX_FILTERS:
                last_err = f"필터는 차트마다 {rd.MAX_FILTERS}개까지입니다"
                continue
            if ranged and not flt.get("range"):
                last_err = (f"'{flt['col']}' 컬럼에는 범위를 걸 수 없습니다 — 기간 범위(last_n·from_value·to_value)는 [기간] 컬럼에, "
                            "min·max 는 숫자 컬럼에 씁니다")
                continue
            if same is not None:   # 같은 컬럼에 다시 부르면 선택 값(과 이름)만 바꾼다 / calling again on the same column updates it
                same["selected"], same["label"] = flt["selected"], (rd._s(args.get("label"), 40) or same["label"])
                same.pop("range", None)
                if flt.get("range"):
                    same["range"] = flt["range"]
                flt = same
            else:
                c["filters"].append(flt)
            done.append((c, flt))
        if not done:
            raise ValueError(last_err or "필터를 걸 차트가 없습니다")
        flt = done[0][1]
        names = ", ".join(f"{c['id']} \"{c['title']}\"" for c, _ in done)
        where = f"'{done[0][0]['title']}' 차트" if len(done) == 1 else f"차트 {len(done)}개"
        if flt.get("range"):
            return (f"필터 \"{flt['label']}\" 적용: {names}, 범위: {_filter_text(flt)}",
                    f"{where}에 '{flt['label']}' 필터를 걸고 {_filter_text(flt)}만 보이게 했습니다.")
        return (f"필터 \"{flt['label']}\" 적용: {names}" + (f", 선택: {flt['selected']}" if flt["selected"] else ""),
                f"{where}에 '{flt['label']}' 필터를 " + (f"걸고 {', '.join(flt['selected'][:3])}만 보이게 했습니다." if flt["selected"]
                                                      else "추가했습니다. 차트의 필터 버튼에서 값을 골라 보세요."))

    if name == "remove_filter":
        col = str(args.get("column") or "").strip()
        hit = 0
        for c in _filter_targets(state, args.get("chart_id"), scope):
            keep = [f for f in c["filters"] if col not in (f["col"], f["label"], f["id"])]
            hit += len(c["filters"]) - len(keep)
            c["filters"] = keep
        if not hit:
            raise ValueError(f"'{col}' 필터가 없습니다")
        return f"필터 \"{col}\" {hit}개 삭제", f"'{col}' 필터를 지웠습니다."

    if name == "set_trend":
        cur = _chart(state, args.get("chart_id"))
        have = cur.get("trend") or {}
        want = {"line": args["line"] if isinstance(args.get("line"), bool) else bool(have.get("line")),
                "forecast": args["forecast"] if args.get("forecast") is not None else have.get("forecast", 0),
                "method": args.get("method") or have.get("method"), "series": args.get("series") or have.get("series")}
        others = {c["id"] for c in state["charts"] if c["id"] != cur["id"]}
        chart = rd.norm_chart({**cur, "trend": want}, sources, others, strict=True)
        state["charts"][state["charts"].index(cur)] = chart
        if not chart.get("trend"):
            return f"\"{chart['title']}\"의 추세선·예측 삭제", f"'{chart['title']}'의 추세선과 예측을 지웠습니다."
        tr = rd.compute(chart, sources[chart["source"]]).get("trend") or {}
        unit = chart["y"][tr.get("series", 0)].get("unit") or chart.get("unit") or ""
        fc = tr.get("forecast")
        note = f"\"{chart['title']}\" 추세: 한 기간에 {tr.get('slope')} 변화(점 {tr.get('points')}개)"
        say = f"'{chart['title']}'에 추세선을 넣었습니다(한 기간에 약 {rd.fmt(tr.get('slope') or 0, unit)})." if chart["trend"]["line"] else ""
        if fc:
            pairs = ", ".join(f"{lb} {rd.fmt(v, unit)}" for lb, v in zip(fc["labels"], fc["values"]))
            note += f", 예측({fc['method']}): {pairs}"
            say += f" 앞으로 {len(fc['labels'])}개 기간을 예측으로 이어 그렸습니다({pairs}, 참고용)."
        elif chart["trend"]["forecast"]:
            say += f" 예측은 점이 {rd.MIN_FORECAST_POINTS}개 이상일 때만 그립니다(지금 {tr.get('points', 0)}개)."
        return note, say.strip()

    if name == "set_theme":
        if args.get("clear"):
            state.pop("theme", None)
            for c in state["charts"]:
                if c["style"]["palette"] == "theme":
                    c["style"] = {**c["style"], "palette": "indigo"}
            return "테마 삭제(기본 색으로)", "테마를 지우고 기본 색으로 돌렸습니다."
        theme = rd.norm_theme({**(state.get("theme") or {}), **{k: v for k, v in args.items() if v is not None}})
        if theme is None:
            raise ValueError("테마에는 대표 색 brand_color(#RRGGBB)가 필요합니다")
        state["theme"] = theme
        for c in state["charts"]:
            c["style"] = rd.norm_style(rd.theme_style(theme), c["type"], c["style"])
        return (f"테마 적용: 대표 색 {theme['brand']}, 차트 {len(state['charts'])}개",
                f"대표 색 {theme['brand']}(으)로 테마를 정해 모든 차트에 입혔습니다. 앞으로 만드는 차트도 이 색을 따릅니다.")

    if name == "add_kpi":
        # 대화로 카드 넣기·고치기(2026-10-12 사용자 지시 "채팅으로 생성하고 조정") — kpi_id(또는 이름)나 같은 label 의 카드가 있으면 제자리에서
        # 적은 항목만 바뀌고, 없으면 새 카드. value 는 사용자가 말한 고정 숫자(고정 숫자 카드), column 은 데이터에서 계산하는 카드. Source 를 안 적으면 첫 Source.
        # Create or adjust a card from the conversation (user decision 2026-10-12): an existing card (by kpi_id, name or the same label)
        # changes only the given fields, otherwise a new card is added. value is a number the user stated (a fixed-number card), a column
        # makes a computed card. Without a source the first root source is used.
        have = state.get("kpis") or []
        kid = _kpi_id(state, args.get("kpi_id")) if args.get("kpi_id") else ""
        label = rd._s(args.get("label"), 40)
        if not kid and label:
            kid = next((k["id"] for k in have if k["label"] == label), "")
        cur = next((k for k in have if k["id"] == kid), None)
        # 적은 인자만 넘긴다(안 적은 항목은 그대로, 빈 문자열은 지우기) / only the given arguments (others stay; an empty string clears)
        raw: dict = {}
        if args.get("source_id") or (not kid and (scope or {}).get("view")):
            raw["source"] = _src_id(state, args.get("source_id") or (scope or {}).get("view"))
        for key, arg in (("col", "column"), ("agg", "agg"), ("label", "label"), ("unit", "unit"), ("note", "note"), ("value", "value")):
            if args.get(arg) is not None:
                raw[key] = args[arg]
        if args.get("delta") is not None:   # 'prev' | 'none'(끄기) / 'prev' or 'none' (off)
            raw["delta"] = "" if str(args["delta"]).strip().lower() in ("", "none", "off", "false", "no") else args["delta"]
        if args.get("link_chart_id") is not None:   # 차트 id | 'none'(연결 끊기) / a chart id or 'none' (unlink)
            v = str(args["link_chart_id"]).strip()
            raw["link"] = "" if v.lower() in ("", "none", "없음", "no") else _loose_id(v, "c", "chart|차트|리포트")
        col = str(raw.get("col") or "").strip()
        if not kid and raw.get("value") in (None, "") and not col:
            raise ValueError("값 컬럼(column)이나 사용자가 말한 숫자(value) 중 하나가 필요합니다. 사용자가 숫자를 말하지 않았으면 지어내지 말고 물어보세요")
        if col and not raw.get("source") and not (cur and cur.get("source")):   # 새 카드 · 고정 숫자 카드만 첫 원본 Source / only a new or fixed-number card defaults to the first root source
            raw["source"] = next((s["id"] for s in state["sources"] if not s["origin"].get("clone_of") and s["rows"]), "")
        kpi = rd.put_kpi(state, raw, kid, merge=bool(kid))
        if cur is not None and kpi == cur:
            raise ValueError("바뀐 항목이 없습니다 — 고칠 항목(이름·설명·단위·집계·컬럼·연결 차트·직전 기간 대비·숫자)을 적어 주세요")
        val = rd.kpi_value(kpi, state)
        shown = rd.fmt(val["value"], kpi["unit"])
        return (f"KPI 카드 \"{kpi['label']}\" = {val['value']}" + (f" (직전 기간 대비 {val['delta']}%)" if val.get("delta") is not None else ""),
                (f"KPI 카드 '{kpi['label']}'({shown})을 고쳤습니다." if kid else f"맨 위 KPI 카드에 '{kpi['label']}'({shown})을 넣었습니다."))

    if name == "remove_kpi":
        have = state.get("kpis") or []
        named = args.get("kpi_id") or args.get("label")
        want = _kpi_id(state, named) if named else ""
        if named and not want:
            raise ValueError("지울 KPI 카드를 찾지 못했습니다. 카드: " + (", ".join(f"{k['id']} {k['label']}" for k in have) or "없음"))
        keep = [k for k in have if want and k["id"] != want]
        if len(keep) == len(have):
            raise ValueError("지울 KPI 카드가 없습니다")
        state["kpis"] = keep
        return f"KPI 카드 {len(have) - len(keep)}개 삭제", "KPI 카드를 지웠습니다."

    if name == "arrange_kpis":   # 대화로 순서 바꾸기 — 적은 카드를 앞에, 나머지는 그 뒤에 / reorder from the conversation: named cards first, the rest after
        have = state.get("kpis") or []
        if not have:
            raise ValueError("KPI 카드가 없습니다")
        ids: list[str] = []
        for x in (args.get("order") or []):
            kid = _kpi_id(state, x)
            if kid and kid not in ids:
                ids.append(kid)
        if not ids:
            raise ValueError("순서에 적은 카드를 찾지 못했습니다. 카드: " + ", ".join(f"{k['id']} {k['label']}" for k in have))
        by = {k["id"]: k for k in have}
        state["kpis"] = [by[i] for i in ids] + [k for k in have if k["id"] not in ids]
        return "KPI 카드 순서: " + " > ".join(by[i]["label"] for i in ids), "KPI 카드 순서를 바꿨습니다."

    if name == "set_insight":
        cur = _chart(state, args.get("chart_id"))
        cur["insight"] = rd._s(args.get("text"), 600)
        return f"\"{cur['title']}\" 인사이트 작성", ""

    if name == "arrange":
        order = [str(i) for i in (args.get("order") or [])]
        by_id = {c["id"]: c for c in state["charts"]}
        head = [by_id[i] for i in order if i in by_id]
        if not head:
            raise ValueError("순서에 있는 차트 id 가 없습니다")
        state["charts"] = head + [c for c in state["charts"] if c not in head]
        return "차트 순서 변경", "차트 순서를 바꿨습니다."

    if name == "rename_dashboard":
        title = rd._s(args.get("title"), rd.MAX_TITLE)
        if not title:
            raise ValueError("제목이 비어 있습니다")
        state["title"] = title
        return f"대시보드 제목을 \"{title}\"(으)로 변경", f"대시보드 제목을 '{title}'(으)로 바꿨습니다."

    raise ValueError(f"알 수 없는 도구입니다: {name}")


def _pick_tools(prompt: str) -> dict:
    """도구 고르기 1회 — 기본은 경량 티어(대화로 고치는 화면이라 한 라운드 1~2초가 중요하고, 닫힌 도구 목록에서 고르는 일이라
    경량 모델로 충분하다). 그 티어가 실패하면 다른 티어로 한 번 더 — 한쪽 모델이 혼잡해도 턴이 죽지 않는다."""
    # One tool-picking call. The lite tier by default: an interactive editor needs 1-2 s rounds and picking from a closed
    # tool list suits a lite model. When that tier fails, the other tier is tried once so a busy model never kills the turn.
    first = "main" if settings.REPORT_AGENT_TIER == "main" else "lite"
    try:
        return llm.generate_calls(prompt, system=SYSTEM, tools=TOOL_SPECS, tier=first)
    except Exception as e:  # noqa: BLE001
        other = "lite" if first == "main" else "main"
        logger.warning("리포트 에이전트 %s 티어 실패(%s), %s 티어로 재시도", first, type(e).__name__, other)
        return llm.generate_calls(prompt, system=SYSTEM, tools=TOOL_SPECS, tier=other)


def _trace_entry(name: str, ok: bool, detail: str, say: str = "") -> dict:
    agent, label = TOOL_META.get(name, (VIZ_AGENT, name))
    return {"agent": agent, "group": TOOL_GROUP.get(name, "기타"), "tool": name, "label": label, "ok": ok,
            "detail": detail[:300], "say": say[:200]}


def _fallback_reply(trace: list[dict]) -> str:
    """LLM 이 마무리 말을 안 했을 때의 답 — 성공한 도구의 문장을 겹치지 않게 최대 3개 잇는다 / the reply when the LLM said nothing"""
    says: list[str] = []
    for t in trace:
        if t["ok"] and t.get("say") and t["say"] not in says:
            says.append(t["say"])
    if not says:
        failed = next((t for t in trace if not t["ok"]), None)
        return f"요청을 반영하지 못했습니다. {failed['detail']}" if failed else "바꿀 내용을 찾지 못했습니다. 조금 더 구체적으로 말씀해 주세요."
    return " ".join(says[:3]) + (f" 그 밖에 {len(says) - 3}건을 더 반영했습니다." if len(says) > 3 else "")


def default_title(state: dict) -> None:
    """제목을 아무도 정하지 않았으면 첫 차트 제목으로 / when nobody named the dashboard, name it after its first chart"""
    if state["title"] == "새 대시보드" and state["charts"]:
        state["title"] = (state["charts"][0]["title"] + (" 외" if len(state["charts"]) > 1 else ""))[:rd.MAX_TITLE]


def fill_insights(state: dict, before_ids: set[str]) -> None:
    """새로 생긴 차트에 인사이트가 비어 있으면 결정적 한 줄로 채운다 / fill a deterministic one-liner for new charts without an insight"""
    sources = _sources(state)
    for c in state["charts"]:
        if c["id"] not in before_ids and not c.get("insight"):
            c["insight"] = rd.auto_insight(c, rd.compute(c, sources[c["source"]]))


def run_turn(state: dict, messages: list[dict], message: str, eff: dict | None, focus: str = "", view: str = "",
             drill: dict | None = None) -> dict:
    """한 턴 — LLM 이 도구를 고르고, 실행 결과를 돌려주며 최대 MAX_ROUNDS 라운드. 반환: {state, reply, trace}.
    LLM 호출 자체가 실패하면 예외를 그대로 올린다(상태는 바뀌지 않는다 — 호출부가 저장하지 않는다)."""
    # One turn: the LLM picks tools, results are fed back, up to MAX_ROUNDS rounds. An LLM failure propagates and the
    # caller saves nothing.
    state = rd.normalize_state(json.loads(json.dumps(rd.pack_state(state))))   # 작업용 사본(복제본의 행은 다시 이어진다) / a working copy; clone rows are re-linked
    before = {c["id"] for c in state["charts"]}
    if not focus and view:   # Source 탭(리포트 하나짜리 화면)에서 고른 차트가 없으면 그 탭의 리포트가 '이 차트'다 / on a Source tab its one report is "this chart"
        own = [c["id"] for c in state["charts"] if c["source"] == view]
        focus = own[0] if len(own) == 1 else ""
    trace: list[dict] = []
    results: list[str] = []
    reply = ""
    for round_no in range(MAX_ROUNDS):
        prompt = (f"[대시보드 상태]\n{describe_state(state, focus, view, drill)}\n\n[대화 기록]\n{_history(messages)}\n\n[요청]\n{message}"
                  + ("\n\n[이번 턴 도구 실행 결과]\n" + "\n".join(results)
                     + "\n\n남은 일이 있으면 도구를 부르고(차트를 만들었거나 값이 바뀌었으면 set_insight), 없으면 도구 없이 사용자에게 답한다."
                     if results else ""))
        res = _pick_tools(prompt)
        calls = res.get("calls") or []
        if res.get("text"):
            reply = res["text"]
        if not calls:
            break
        followup = False
        for call in calls[:12]:
            name = call.get("name") or ""
            try:
                detail, say = run_tool(state, name, call.get("args") or {}, eff, {"focus": focus, "view": view})
                ok = True
            except (ValueError, AgentError) as e:
                detail, say, ok = str(e), "", False
            trace.append(_trace_entry(name, ok, detail, say))
            results.append(f"{len(results) + 1}. {name} → {'성공' if ok else '실패'}: {detail}")
            if name in _NEEDS_FOLLOWUP or not ok:
                followup = True
        if not followup:
            break   # 디자인·기준선·필터처럼 결과를 다시 볼 필요가 없는 변경은 한 번에 끝낸다 / style, lines and filters finish in one round
    fill_insights(state, before)
    default_title(state)
    return {"state": rd.normalize_state(state), "reply": reply or _fallback_reply(trace), "trace": trace}


def auto_charts(state: dict, eff: dict | None) -> dict:
    """첫 차트 — LLM 에게 Source 마다 하나씩 맡기고, 실패하거나 하나도 못 만들면 규칙으로 만든다."""
    # First charts: ask the LLM for one per source; fall back to rule-based charts when it fails or makes none.
    try:
        out = run_turn(state, [], AUTO_INSTRUCTION, eff)
    except Exception as e:  # noqa: BLE001 — 첫 화면은 LLM 없이도 떠야 한다 / the first screen must come up without the LLM
        logger.warning("첫 차트 자동 생성 실패, 규칙 기반으로 대체: %s", e)
        out = {"state": rd.normalize_state(state), "reply": "", "trace": []}
    st = out["state"]
    charted = {c["source"] for c in st["charts"]}
    by_id = _sources(st)
    for s in st["sources"]:
        if s["id"] in charted or len(st["charts"]) >= rd.MAX_CHARTS:
            continue
        try:
            st["charts"].append(rd.norm_chart(rd.auto_chart_spec(s), by_id, {c["id"] for c in st["charts"]}))
            out["trace"].append(_trace_entry("create_chart", True, f"\"{st['charts'][-1]['title']}\" 추가(규칙 기반)"))
        except ValueError:
            continue
    fill_insights(st, set())
    default_title(st)
    # KPI 카드는 첫 화면에 놓지 않는다(2026-10-12 사용자 결정) — [+ KPI 카드] · [추천 채우기] · 대화로 요청해야 생긴다
    # No KPI cards on the first screen (user decision 2026-10-12): they come from [+ KPI card], [Fill suggestions] or the conversation
    out["state"] = rd.normalize_state(st)
    return out
