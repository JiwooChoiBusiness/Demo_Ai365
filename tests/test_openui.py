"""OpenUI 답변 서버 쪽(2026-10-27, 1단계) — app/openui.py 도구 · 번호 출처 · 형식 스위치 · 경로 배선(지식 고속경로 · 취합 · 웹 · 직접 답
text 모드 · 발송/문서 생성/탐색/데이터는 마크다운) · 저장 meta · 이력 평문 · HTTP ui_format 끄기 · 각주 건너뛰기 · 기본(off) 불변.
임시 DB, 가짜 llm.stream · llm.generate_grounded_meta, 생성 프롬프트는 임시 파일(openui.PROMPT_PATH 패치). 실 DB · 실 포트 · 네트워크 없음.

OpenUI answers, server side (2026-10-27, phase 1): app/openui.py helpers, numbered sources, the format switch, path wiring
(knowledge fast path, aggregation, web, direct answers in text mode; send/document/explore/data stay markdown), saved meta,
plain-text history, the HTTP ui_format opt-out, skipped footnote enrichment and the unchanged default (off). Temp DB, fake
llm.stream / llm.generate_grounded_meta, the generated prompt is a temp file (openui.PROMPT_PATH patched). No real DB, port or
network.

2단계(계약 9절): 대상 판정(ui_eligible) · 데이터 문장(d{n} · d{n}top · d{n}sum · gw{m}) 모양 · 상한 · 계산 · 이스케이프 · 번호 출처 순서
(지식 → 로컬 → 데이터 → 그룹웨어 → 웹) · finalize 의 서버 문장 재정의 제거 · 숫자 리터럴 점검 · 범례 · 데이터 프로그램 평문 · 취합 끝단
(데이터만 · 그룹웨어만 · 섞임) · 자동 모드 웹 보완 번호 · 그룹웨어 에이전트 gw_rows. catalog.data_locate 와 그룹웨어 노드 실행은 대역이다
(app/groupware.py 는 실 DB 경로를 가져다 쓰므로 실제로 부르지 않는다).
Phase 2 (contract 9): eligibility, data statements (shapes, caps, stats, escaping), numbered-source order, finalize dropping
server-name redefinitions, the literal check, the legend, plain text of data-bound programs, end-to-end aggregation (data only,
groupware only, mixed), the auto mode's web-supplement numbering and the groupware agent's gw_rows. catalog.data_locate and the
groupware node run are stand-ins (app/groupware.py binds the real DB path, so it is never called for real)."""
import asyncio
import copy
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import quote, unquote

from db_fixture import isolate_db

from app import answers, chats_api, cite, db, execution_store as store, openui, pipeline, run_context, runs
from app import conversation_execution as conversation
from app.agents import AGENT_REGISTRY
from app.agents import knowledge as knowledge_agent
from app.intent import ANSWER_SYSTEM, DIRECT_SYSTEM, _INTERRUPT_NOTE

PROMPT = "## OpenUI 생성 프롬프트(시험용)\nCard(children, sources?): 시험용 서명"
KN_PATH = {"path": ["지식 관리", "인사", "규정"], "folder": "f_hr"}
DOC = "인사 규정.pdf"
QUESTION = "연차는 며칠이야?"
CTX = [{"role": "user", "content": "안녕"}, {"role": "assistant", "content": "안녕하세요"}, {"role": "user", "content": QUESTION}]
MODEL = ['root = Card([intro, fu], [src1])\n',
         'intro = TextContent("연차는 입사 1년 뒤 15일이 생깁니다 [1].")\n',
         'fu = FollowUpBlock([FollowUpItem("반차도 되나요?"), FollowUpItem("신청 방법은?")])']
MODEL_PLAIN = "연차는 입사 1년 뒤 15일이 생깁니다 [1]."


def decision(steps=None, **kw):
    return {"version": 3, "query": QUESTION, "steps": steps or [], "send_query": "", "clarify": None,
            "document": None, "use_previous": False, "web": False, **kw}


def step(key, agent="knowledge"):
    return {"id": key, "agent": agent, "task": key, "depends_on": [], "inputs": {}}


def kn_result(doc=DOC, page=3, text="연차는 15일입니다.", excerpt="제12조 연차는 1년 근속 시 15일을 부여한다."):
    return {"agent": "knowledge", "task_id": "knowledge", "label": "지식관리", "status": "answer", "text": text,
            "extras": {"references": [{"doc": doc, "page": page}],
                       "excerpts": [{"doc": doc, "page": page, "text": excerpt}]}}


def local_result(aid="kl_demo_hq", name="본사 로컬 에이전트"):
    return {"agent": "local", "label": f"로컬 지식 에이전트 · {name}", "status": "answer", "text": "비밀번호는 90일마다 바꾼다.",
            "extras": {"local": {"agent_id": aid, "name": name, "model": "Qwen 3.5-4B", "question": "비밀번호 주기",
                                 "sources": [{"doc_id": "hq-doc-001", "title": "보안 정책", "page": 2,
                                              "snippet": "비밀번호 변경 주기는 90일이다."}]}}}


# ── 2단계 고정 자료(데이터 · 그룹웨어) / phase-2 fixtures (data, groupware) ──
SQL = "SELECT month AS 월, sales AS 매출액 FROM pos_sales"
MONTHS12 = [[f"{m}월", 100 + m * 5] for m in range(1, 13)]   # 105 … 160, 합 1590 / sum 1590
LOCS = {"pos_sales": {"ws": "ws_sales", "wsName": "영업", "kind": "DB", "label": "월별 매출", "node": "sl_ws_sales_sql_pos_sales"},
        "dept_budget": {"ws": "ws_fin", "wsName": "재무", "kind": "CSV", "label": "부서 예산", "node": "sl_ws_fin_csv_dept_budget"},
        "분기 판매.pbix": {"ws": "ws_sales", "wsName": "영업", "kind": "BI", "label": "분기 판매 대시보드", "node": "sl_bi"}}


def data_locate(table=None, bi_file=None):
    """catalog.data_locate 대역(모르는 표는 None) / a catalog.data_locate stand-in (None for unknown tables)"""
    return LOCS.get(table if table is not None else bi_file)


def data_result(rows=None, columns=("월", "매출액"), sql=SQL, tables=("pos_sales",), extra=None, text="1분기 매출은 꾸준히 늘었다.",
                status="analysis"):
    rows = rows if rows is not None else [["1월", 120], ["2월", 135], ["3월", 150]]
    ex = {"columns": list(columns), "rows": [r if isinstance(r, dict) else list(r) for r in rows], "sql": sql, "tables": list(tables)}
    if extra:
        ex["extra_results"] = extra
    return {"agent": "data", "task_id": "s1", "label": "데이터분석", "status": status, "text": text, "extras": ex}


GW_NEWS = {"title": "오늘의 뉴스", "path": ["그룹웨어", "위젯"], "kind": "gw", "key": "news", "ns": "widget"}
GW_MAIL = {"title": "안 읽은 메일", "path": ["그룹웨어", "Outlook 메일"], "kind": "gw", "key": "mail.info.unread", "ns": "mail"}
GW_ROWS = [("반도체 수출 3개월 연속 증가", "경제"), ("AI 도입률 60% 돌파", "IT")]
# 스마트 실행 시드 행 모양(smart_seed._mail_row · _event_row · _task_row · _file_row · calendar_free) / the seed row shapes
MAILS = [{"subject": "3분기 예산안 검토 요청", "from": {"name": "김지민", "email": "jm@example.test"}, "when": "오늘 10:12", "isRead": False},
         {"subject": "주간 보고", "from": {"name": "박서준", "email": "sj@example.test"}, "when": "어제", "isRead": True},
         {"subject": "", "from": {"name": "제목 없음"}, "when": "어제", "isRead": True}]        # 제목 없는 행 / a row without a title
EVENTS = [{"subject": "주간 회의", "when": "오늘 10:00", "timeRange": "10:00~11:00", "location": "3층 회의실"},
          {"subject": "고객 미팅", "when": "오늘 14:00", "timeRange": "14:00~15:00", "location": ""}]
FREE = [{"start": "2026-10-27T15:30:00+09:00", "end": "2026-10-27T17:00:00+09:00", "when": "오늘 15:30",
         "timeRange": "15:30~17:00", "minutes": 90}]
TASKS = [{"title": "보고서 제출", "due": "오늘", "isOverdue": True}, {"title": "회의록 정리", "due": "기한 없음", "isOverdue": False}]
FILES = [{"name": "예산안.xlsx", "path": "/재무/2026", "when": "어제"}]
MAIL_LIST = {"key": "mail.info.unread", "title": "Outlook 메일 · 안 읽은 메일", "left": "제목", "right": "보낸 사람 · 시각 · 안 읽음 표시",
             "rows": [{"t": "3분기 예산안 검토 요청", "s": "김지민 · 오늘 10:12 · 안 읽음"}, {"t": "주간 보고", "s": "박서준 · 어제"}]}


def gw_result(rows=GW_ROWS, items=(GW_NEWS,), status="answer", lists=None, **extras):
    """그룹웨어 에이전트 읽기 결과 대역. gw_rows 는 에이전트와 같은 모양(조회한 키마다 목록 하나: {key, title, left, right, rows})이고,
    lists 를 주면 그대로(옛 평평한 [{t, s}] 모양도) 싣는다 / a stand-in for a groupware read result; gw_rows has the agent's shape"""
    ex = {"gw": [dict(i) for i in items], "gw_keys": [i["key"] for i in items]}
    if lists is not None:
        ex["gw_rows"] = lists
    elif rows:
        first = items[0] if items else {}
        ex["gw_rows"] = [{"key": first.get("key", ""), "title": first.get("title", ""), "left": "항목", "right": "내용",
                          "rows": [{"t": t, "s": s} for t, s in rows]}]
    ex.update(extras)
    lines = "\n".join(f"- {t} — {s}" for t, s in (rows or []))
    return {"agent": "groupware", "task_id": "groupware", "label": "그룹웨어", "status": status,
            "text": "[오늘의 뉴스]\n오늘의 주요 뉴스입니다.\n" + lines, "extras": ex}


async def collect(stream):
    return [e async for e in stream]


async def _one(text):
    yield text


REAL_SMOOTH = answers._smooth   # 패치 전 원본(실제로 잘게 흘리는지 보는 시험용) / the unpatched original, for the smoothing check


class FakeStream:
    """llm.stream 대역 — 호출마다 (messages, system) 을 기록하고 토큰 목록 하나를 흘린다(예외 객체는 그 자리에서 던진다)
    llm.stream stand-in: records (messages, system) per call and streams one token list (exception objects are raised in place)."""

    def __init__(self, *outputs):
        self.outputs = [list(o) for o in outputs]
        self.calls: list[dict] = []

    def __call__(self, messages, system=None, tier="main"):
        self.calls.append({"messages": copy.deepcopy(messages), "system": system})
        tokens = self.outputs.pop(0) if self.outputs else []

        def gen():
            for t in tokens:
                if isinstance(t, BaseException):
                    raise t
                yield t
        return gen()


def oui_env(stack, mode="on", prompt=True) -> Path:
    """OPENUI_MODE · 생성 프롬프트(임시 파일)를 맞춘다 / set OPENUI_MODE and a temp generated prompt"""
    tmp = stack.enter_context(tempfile.TemporaryDirectory())
    path = Path(tmp) / "openui_system_prompt.txt"
    if prompt:
        path.write_text(PROMPT, encoding="utf-8")
    stack.enter_context(patch.object(openui, "PROMPT_PATH", path))
    env = dict(os.environ)
    env.pop("OPENUI_MODE", None)
    if mode is not None:
        env["OPENUI_MODE"] = mode
    stack.enter_context(patch.dict(os.environ, env, clear=True))
    return path


# ── 도구 단위 / helper units ─────────────────────────────────────────────────────────────

class HelperTests(unittest.TestCase):
    def test_quote_str_is_a_json_string(self):
        for s in ['a "b" \\ c', "줄\n바꿈\t탭", "제어\x01문자", "😀 이모지   구분", ""]:
            q = openui.quote_str(s)
            self.assertTrue(q.startswith('"') and q.endswith('"'))
            self.assertEqual(json.loads(q), s)
            self.assertNotIn("\n", q)
        self.assertEqual(openui.quote_str("한글"), '"한글"')    # ensure_ascii=False

    def test_wrap_text_follows_the_contract_template(self):
        self.assertEqual(openui.wrap_text("안녕하세요"), 'root = Card([body])\nbody = TextContent("안녕하세요")')
        src = [{"title": "a.pdf p.1", "sourceName": "지식 관리 › 인사", "url": "ai365://kn/a.pdf?page=1"},
               {"title": "b.com", "sourceName": "b.com", "url": "https://b.com"}]
        self.assertEqual(openui.wrap_text('본문 "인용" [1]', sources=src, followups=["더 알려줘", " ", "요약해줘"]), "\n".join([
            "root = Card([body, fu], [src1, src2])",
            'body = TextContent("본문 \\"인용\\" [1]")',
            "fu = FollowUpBlock([fu1, fu2])",
            'fu1 = FollowUpItem("더 알려줘")',
            'fu2 = FollowUpItem("요약해줘")',
            'src1 = {title: "a.pdf p.1", sourceName: "지식 관리 › 인사", url: "ai365://kn/a.pdf?page=1"}',
            'src2 = {title: "b.com", sourceName: "b.com", url: "https://b.com"}']))
        self.assertEqual(openui.wrap_text("x", followups=["y"]).split("\n")[0], "root = Card([body, fu])")
        self.assertEqual(openui.wrap_text("x", sources=src[:1]).split("\n")[0], "root = Card([body], [src1])")

    def test_source_statements(self):
        self.assertEqual(openui.source_statements([]), "")
        self.assertEqual(openui.source_statements([{"title": "t", "sourceName": "s", "url": ""}, {"title": 'q"', "sourceName": "s2", "url": "u"}]),
                         'src1 = {title: "t", sourceName: "s"}\nsrc2 = {title: "q\\"", sourceName: "s2", url: "u"}')

    def test_fences_report_and_is_program(self):
        raw = "```openui\nroot = Card([b])\nb = TextContent(\"x\")\n```"
        self.assertEqual(openui.strip_fences(raw), 'root = Card([b])\nb = TextContent("x")')
        self.assertEqual(openui.program_report(raw), {"has_root": True, "fenced": True})
        self.assertEqual(openui.program_report("b = TextContent(\"x\")"), {"has_root": False, "fenced": False})
        self.assertTrue(openui.is_program("intro = TextContent(\"x\")"))
        self.assertTrue(openui.is_program("$count = 0"))
        self.assertFalse(openui.is_program("그냥 글입니다.\n- 목록"))

    def test_plain_text_round_trips_wrap_and_skips_followups_and_sources(self):
        md = '첫 줄 "따옴표" \\ 역슬래시\n\t탭 😀   [1] 끝'
        src = [{"title": "a.pdf p.1", "sourceName": "지식 관리", "url": "ai365://kn/a.pdf"}]
        self.assertEqual(openui.plain_text(openui.wrap_text(md)), md)
        self.assertEqual(openui.plain_text(openui.wrap_text(md, sources=src, followups=["후속 질문"])), md)

    def test_plain_text_leaves_out_non_prose_strings(self):
        program = "\n".join([
            "root = Card([h, t, c, tb, e, b, tags, fu], [{title: \"인라인 출처\", sourceName: \"s\", url: \"https://x\"}])",
            "h = CardHeader('연차 안내', \"부제\")",
            "t = TextContent(\"본문 [1]\", \"large\")   # 주석 \"따옴표\" 무시",
            "c = Callout(\"info\", \"주의\", \"신청은 3일 전\")",
            "tb = Table([Col(\"항목\", [\"연차\", \"반차\"]), Col(\"일수\", [15, 0.5])])",
            "e = EntityList([{left: \"연차\", right: \"15일\"}])",
            "b = Buttons([Button(\"규정 열기\", Action([@OpenUrl(\"ai365://kn/a.pdf\")]), \"primary\")])",
            "tags = TagBlock([\"인사\", \"인사\"])",
            "ic = Icon(\"circle-check\")",
            "$state = \"초기값\"",
            "fu = FollowUpBlock([FollowUpItem(\"후속\")])",
            "src1 = {title: \"출처 제목\", sourceName: \"출처명\", url: \"ai365://kn/b.pdf\"}",
        ])
        # 표 숫자 · 항목 목록은 읽기 좋은 줄로(2026-10-27 검토 반영), 화면에 붙지 않은 문장(ic)은 뺀다
        # Table numbers and entity rows become readable lines (review fix); a statement not on the screen (ic) is left out
        self.assertEqual(openui.plain_text(program).split("\n"),
                         ["연차 안내", "부제", "본문 [1]", "주의", "신청은 3일 전", "항목 | 일수", "연차 | 15", "반차 | 0.5",
                          "연차: 15일", "규정 열기", "인사, 인사"])

    def test_plain_text_survives_prose_and_multiline_statements(self):
        program = "Here's the answer:\nroot = Card([\n  body\n])\nbody = TextContent(\"여러\n줄\")\n끝인사 'quote"
        self.assertEqual(openui.plain_text(program), "여러\n줄")
        # 주소로 시작하는 글은 남고, 주소만인 문자열은 빠진다 / prose starting with a URL stays, a bare URL goes
        self.assertEqual(openui.plain_text('root = Card([a, b])\na = TextContent("https://x.com 에서 확인하세요")\nb = Image("사진", "https://x.com/a.png")'),
                         "https://x.com 에서 확인하세요\n사진")

    def test_finalize_program_mode(self):
        numbered = [{"title": "a.pdf p.1", "sourceName": "지식 관리", "url": "ai365://kn/a.pdf?page=1"}]
        raw = "\n".join(["Here's your answer:", "```openui", "root = Card([body, fu], [src1])",
                         "src1 = {", '  title: "모델이 지어낸 출처",', '  sourceName: "x"', "}",
                         'body = TextContent("연차는 15일 [1]")', "src2 = {title: \"또\", sourceName: \"y\"}",
                         'fu = FollowUpBlock([FollowUpItem("더")])', "```", "감사합니다"])
        program, report = openui.finalize(raw, "program", numbered)
        self.assertEqual(program, "\n".join([openui.source_statements(numbered), "root = Card([body, fu], [src1])",
                                             'body = TextContent("연차는 15일 [1]")', 'fu = FollowUpBlock([FollowUpItem("더")])']))
        self.assertEqual(report, {"has_root": True, "fenced": True, "fallback": False})
        self.assertNotIn("모델이 지어낸", program)
        self.assertEqual(openui.plain_text(program), "연차는 15일 [1]")

    def test_finalize_fallback_and_text_mode(self):
        numbered = [{"title": "a.pdf", "sourceName": "지식 관리", "url": "ai365://kn/a.pdf"}]
        prose = "연차는 15일입니다 [1].\n\n```python\nprint('code')\n```"
        program, report = openui.finalize(prose, "program", numbered)
        self.assertEqual(program, openui.wrap_text(prose, sources=numbered))   # 마크다운 코드 펜스는 그대로 / markdown fences kept
        self.assertEqual(report, {"has_root": False, "fenced": True, "fallback": True})
        program, report = openui.finalize("  안녕하세요  ", "text", [])
        self.assertEqual((program, report), (openui.wrap_text("안녕하세요"), {"has_root": True, "fenced": False, "fallback": False}))
        # 모델이 src 문장만 썼으면 그 줄은 빼고 나머지 글을 감싼다 / only src statements: their lines are dropped, the rest wrapped
        program, report = openui.finalize('src1 = {title: "가짜", sourceName: "x"}\n죄송합니다, 답을 찾지 못했습니다.', "program", numbered)
        self.assertEqual(program, openui.wrap_text("죄송합니다, 답을 찾지 못했습니다.", sources=numbered))
        self.assertEqual(report, {"has_root": False, "fenced": False, "fallback": True})
        # 문장은 있으나 root 가 없으면 감싸지 않는다(계약: 문장 줄도 없을 때만 fallback) / statements without root are kept
        program, report = openui.finalize('card = Card([b])\nb = TextContent("x")', "program", [])
        self.assertEqual((program, report["fallback"], report["has_root"]), ('card = Card([b])\nb = TextContent("x")', False, False))

    def test_insert_markers(self):
        text = "서울은 맑다. 내일은 비가 온다."
        sup = [{"end": 7, "ns": [1]}, {"end": len(text), "ns": [3, 2]}, {"end": 7, "ns": [1]},
               {"end": 999, "ns": [0, True, "x"]}, {"end": "bad", "ns": [1]}, "junk"]
        self.assertEqual(openui.insert_markers(text, sup), "서울은 맑다.[1] 내일은 비가 온다.[2][3]")
        self.assertEqual(openui.insert_markers(text, sup, {1: 1, 2: 2, 3: 1}), "서울은 맑다.[1] 내일은 비가 온다.[1][2]")
        self.assertEqual(openui.insert_markers(text, []), text)

    def test_evidence_and_compose_messages(self):
        numbered = [{"n": 1, "title": "a.pdf p.1", "sourceName": "지식 관리 › 인사", "url": "ai365://kn/a.pdf?page=1",
                     "kind": "knowledge", "excerpt": "제1조 발췌"}]
        msgs = openui.compose_messages(CTX, numbered, ["[지식 에이전트 답변]\n연차는 15일"])
        self.assertEqual(msgs[:2], CTX[:2])
        last = msgs[-1]
        self.assertEqual(last["role"], "user")
        body = last["content"]
        for part in ("## 번호 출처", "src1 는 시스템이 이미 정의했다", "[src1]", "[1] a.pdf p.1", "출처명: 지식 관리 › 인사",
                     "url: ai365://kn/a.pdf?page=1", "발췌: 제1조 발췌", "[지식 에이전트 답변]\n연차는 15일",
                     "## 사용자 질문\n" + QUESTION, openui.ANSWER_TAIL):
            self.assertIn(part, body)
        self.assertLess(body.index("[지식 에이전트 답변]"), body.index("## 사용자 질문"))
        self.assertTrue(body.endswith(openui.ANSWER_TAIL))
        none = openui.compose_messages([{"role": "user", "content": "q"}], [], [])
        self.assertEqual(len(none), 1)
        self.assertIn("(없음: 루트 Card 의 출처 인자와 [n] 인용을 쓰지 않는다.)", none[0]["content"])
        explicit = openui.compose_messages(CTX, [], [], question=QUESTION)
        self.assertEqual(len(explicit), 3)   # 같은 마지막 질문은 한 번만 / the same last question appears once

    def test_plain_row(self):
        # 대상 판정(1단계 knowledge_only → 2단계 ui_eligible)은 EligibilityTests 에서 / eligibility moved to EligibilityTests
        row = {"role": "assistant", "content": "root = Card([b])", "meta": {"format": "openui", "plain": "평문"}}
        self.assertEqual(openui.plain_row(row)["content"], "평문")
        self.assertEqual(row["content"], "root = Card([b])")   # 원본 불변 / the original is untouched
        for keep in ({"role": "assistant", "content": "md", "meta": {"source": "사내"}},
                     {"role": "assistant", "content": "p", "meta": {"format": "openui", "plain": "  "}},
                     {"role": "user", "content": "u", "meta": {"format": "openui", "plain": "x"}},
                     {"role": "assistant", "content": "n", "meta": None}):
            self.assertIs(openui.plain_row(keep), keep)
        self.assertFalse(hasattr(openui, "knowledge_only"))

    def test_excerpts_are_capped_and_never_reach_prompts_or_meta(self):
        hits = [{"doc": DOC, "page": 1, "text": "가" * 900}, {"doc": DOC, "page": 1, "text": "가" * 900}, {"doc": DOC, "page": 2, "text": " "}]
        ex = knowledge_agent._excerpts(hits)
        self.assertEqual(len(ex), 1)
        self.assertEqual(len(ex[0]["text"]), knowledge_agent.EXCERPT_CHARS)
        self.assertNotIn("excerpts", answers._slim_extras(kn_result()["extras"]))
        stripped = answers._without_excerpts({"knowledge": kn_result(), "data": {"agent": "data", "extras": {"rows": []}}})
        self.assertNotIn("excerpts", stripped["knowledge"]["extras"])
        self.assertEqual(stripped["knowledge"]["extras"]["references"], [{"doc": DOC, "page": 3}])
        self.assertIn("excerpts", kn_result()["extras"])


class PlainTextTests(unittest.TestCase):
    """평문의 구조 컴포넌트 · 참조 · 뽑기 · 이어 붙이기 · 진입점 · fail soft(2026-10-27 검토 반영)
    Plain text for structured components, references, plucks, concatenation, the entry point and fail-soft (review round)."""

    @staticmethod
    def plain(*lines) -> list[str]:
        return openui.plain_text("\n".join(lines)).split("\n")

    def test_table_zips_columns_with_numbers_booleans_and_progress_cells(self):
        self.assertEqual(self.plain('root = Card([tb])',
                                    'tb = Table([Col("부서", ["영업", "개발", "인사"]), Col("인원", [12, 30.5, -3]), '
                                    'Col("목표", [ProgressBar(12, 20, "60%"), ProgressBar(30, 30), true])])'),
                         ["부서 | 인원 | 목표", "영업 | 12 | 60%", "개발 | 30.5 | 30/30", "인사 | -3 | true"])
        self.assertEqual(self.plain('root = Card([tb])', 'tb = Table([Col("값", [1, 2.5]), Col("비고", ["a"])])'),
                         ["값 | 비고", "1 | a", "2.5 |"])
        self.assertEqual(self.plain('root = Card([h, tb])', 'h = CardHeader("부서별 인원")',
                                    'tb = Table([Col("부서", ["영업", "개발"]), Col("인원", [12, 30])])'),
                         ["부서별 인원", "부서 | 인원", "영업 | 12", "개발 | 30"])   # 검토자 예 / the reviewer's example

    def test_entity_list_rows_header_and_footer(self):
        self.assertEqual(self.plain('root = Card([e])',
                                    'e = EntityList([{left: "연차", right: "15일"}, {left: "반차", right: 0.5, rightVariant: "number"}], '
                                    '"default", {left: "항목", right: "값"}, {left: "합계", right: "15.5일"})'),
                         ["항목: 값", "연차: 15일", "반차: 0.5", "합계: 15.5일"])

    def test_stats(self):
        self.assertEqual(self.plain('root = Card([s])',
                                    's = StatStrip([Stat("12명", "영업", "+2"), Stat("30명", "개발", null, "neutral", "x", "증가"), '
                                    'Stat("5", "인사")])'),
                         ["영업: 12명 (+2)", "개발: 30명 · 증가", "인사: 5"])

    def test_charts(self):
        for chart in ("BarChart", "LineChart", "AreaChart", "HorizontalBarChart"):
            self.assertEqual(self.plain('root = Card([c])',
                                        f'c = {chart}(["1월", "2월"], [Series("매출", [120, 135.5]), Series("비용", [80, 90])], "grouped")'),
                             ["매출: 1월 120, 2월 135.5", "비용: 1월 80, 2월 90"], chart)
        self.assertEqual(self.plain('root = Card([p])', 'p = PieChart(["A", "B"], [60, 40], "donut")'), ["A 60, B 40"])
        self.assertEqual(self.plain('root = Card([p])', 'p = PieChart([Slice("A", 60), Slice("B", 40)])'), ["A 60, B 40"])
        self.assertEqual(self.plain('root = Card([c])', 'c = BarChart(["1월", "2월"], series)'), ["1월, 2월"])   # 계열 모름 / unknown series

    def test_progress_bar_and_readout_keep_their_numbers(self):
        self.assertEqual(self.plain('root = Card([a, b, c, d])', 'a = ProgressBar(299, 300, "$299M")', 'b = ProgressBar(40)',
                                    'c = Readout(42, "계산 결과")', 'd = Readout($display, "계산기")'),
                         ["$299M (299/300)", "40", "계산 결과: 42", "계산기"])

    def test_references_and_plucks_over_server_data_rows(self):
        self.assertEqual(self.plain(
            'rows = [{month: "1월", sales: 120, note: "개장"}, {month: "2월", sales: 135}]',
            'root = Card([title, ch, tb, p])',
            'title = CardHeader("월별 매출")',
            'ch = BarChart(rows.month, [Series("매출", rows.sales)])',
            'tb = Table([Col("월", rows.month), Col("매출", rows.sales), Col("비고", rows.note)])',
            'data = {categories: ["온라인", "매장"], values: [70, 30]}',
            'p = PieChart(data.categories, data.values)'),
            ["월별 매출", "매출: 1월 120, 2월 135", "월 | 매출 | 비고", "1월 | 120 | 개장", "2월 | 135 |", "온라인 70, 매장 30"])
        self.assertEqual(self.plain('root = Card([t])', 'names = ["가", "나"]', 't = TextContent(names[1])'), ["나"])

    def test_concatenation_is_one_line(self):
        self.assertEqual(self.plain('root = Card([a, b, c, d])', 'n = 15', 'unit = "일"',
                                    'a = TextContent("연차는 " + "15일" + " 입니다")',
                                    'b = TextContent("연차는 " + n + unit + "입니다")',
                                    'c = TextContent("합계: " + $total)',
                                    'd = TextContent(1 + 2 + "개")'),
                         ["연차는 15일 입니다", "연차는 15일입니다", "합계:", "3개"])

    def test_ternary_shows_both_branches(self):
        self.assertEqual(self.plain('root = Card([t])', '$d = "0"', 't = TextContent($d == "0"', '  ? "영"', '  : "비영")'), ["영 / 비영"])

    def test_steps_lists_forms_and_layout(self):
        self.assertEqual(self.plain('root = Card([s, l, tags, cols, f])',
                                    's = Steps([StepsItem("신청", "인사 시스템에서 신청"), StepsItem("승인", "팀장 승인")])',
                                    'l = ListBlock([ListItem("연차", "15일"), ListItem("반차")])',
                                    'tags = TagBlock(["인사", "규정"])',
                                    'cols = Columns([Panel("요약", [TextContent("본문")], "부제")])',
                                    'f = Form("leave", Buttons([Button("제출", Action([@ToAssistant("제출")]))]), '
                                    '[FormControl("부서", Select("dept", [SelectItem("sales", "영업"), SelectItem("dev", "개발")]), "하나 고르세요"), '
                                    'FormControl("메모", Input("memo", "적어 주세요"))])'),
                         ["1. 신청: 인사 시스템에서 신청", "2. 승인: 팀장 승인", "- 연차: 15일", "- 반차", "인사, 규정", "요약", "부제",
                          "본문", "부서", "하나 고르세요", "영업", "개발", "메모", "제출"])

    def test_entry_point_orphans_and_cycles(self):
        self.assertEqual(self.plain('root = Card([a])', 'a = TextContent("보임")', 'b = TextContent("안 보임")'), ["보임"])
        self.assertEqual(self.plain('a = TextContent("A")', 'main = Card([a])', 'z = TextContent("고아")'), ["A"])
        self.assertEqual(self.plain('a = TextContent("A")', 'b = Callout("info", "주의", "B")', 'c = [a]'), ["주의", "B", "A"])
        self.assertEqual(self.plain('root = Card([a])', 'a = Card([b, TextContent("x")])', 'b = Card([a])'), ["x"])
        self.assertEqual(self.plain('root = Card([t])', 't = TextContent("text")'), ["text"])   # 본문 자리는 열거형 검사 없음 / text slot

    def test_unknown_components_and_fail_soft(self):
        # 모르는 컴포넌트: 종전처럼 글만(열거형 · 주소 · 숫자 빼고) / unknown components: strings only, as before
        self.assertEqual(self.plain('root = Card([g])', 'g = Gizmo("info", "글", 42, {left: "x", url: "https://y"})'), ["글", "x"])
        # 평가기가 실패하면 종전 문자열 모음 / when the evaluator fails, the former string collection
        with patch.object(openui, "_plain_eval", side_effect=RuntimeError("boom")), \
                self.assertLogs("ai365.openui", level="WARNING"):
            self.assertEqual(openui.plain_text('root = Card([t])\nt = TextContent("글")\ntb = Table([Col("n", [1])])'), "글\nn")
        # 망가진 프로그램도 예외 없이 / a broken program never raises
        self.assertEqual(openui.plain_text('root = Card([a, b\nb = TextContent("부분'), "부분")
        self.assertEqual(openui.plain_text("root = Card([)]}{ , : ? + - ! .\n= = ="), "")


class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)

    def test_enabled_matrix(self):
        oui_env(self.stack, mode="on")
        for fmt in ("auto", "openui", None, "", "anything"):
            self.assertTrue(openui.enabled(fmt), fmt)
        self.assertFalse(openui.enabled("markdown"))
        self.assertFalse(openui.enabled(" Markdown "))
        self.assertFalse(openui.enabled("auto", lane="explore"))
        self.assertEqual((openui.resolve("auto"), openui.resolve("markdown")), ("openui", None))
        self.assertEqual((openui.fmt_kw("openui"), openui.fmt_kw(None)), ({"fmt": "openui"}, {}))

    def test_default_mode_is_on(self):
        # 기본값 on(2026-10-27 전환): OPENUI_MODE 가 없으면 켜지고 "markdown" 요청 · 탐색만 빠진다
        # Default on (switched 2026-10-27): unset OPENUI_MODE turns it on; only "markdown" requests and explore stay out
        self.assertEqual(openui.DEFAULT_MODE, "on")
        oui_env(self.stack, mode=None)   # OPENUI_MODE 없음 / unset
        self.assertTrue(openui.enabled("auto"))
        self.assertTrue(openui.enabled("openui"))
        self.assertFalse(openui.enabled("markdown"))
        self.assertFalse(openui.enabled("auto", lane="explore"))

    def test_off_and_missing_prompt(self):
        oui_env(self.stack, mode="off")
        self.assertFalse(openui.enabled("auto"))
        stack2 = ExitStack()
        self.addCleanup(stack2.close)
        oui_env(stack2, mode="on", prompt=False)
        self.assertFalse(openui.prompt_available())
        self.assertFalse(openui.enabled("auto"))

    def test_system_prompt_parts_and_cache(self):
        path = oui_env(self.stack)
        out = openui.system_prompt("[경로 규칙]", "\n\n[LANGUAGE] English")
        self.assertTrue(out.startswith(PROMPT))
        self.assertIn("## 채팅 규칙\n\n" + openui.DEMO_RULES, out)
        self.assertLess(out.index(openui.DEMO_RULES), out.index("[경로 규칙]"))
        self.assertTrue(out.endswith("[경로 규칙]\n\n[LANGUAGE] English"))
        path.write_text(PROMPT + "\n바뀐 프롬프트 줄", encoding="utf-8")
        self.assertIn("바뀐 프롬프트 줄", openui.system_prompt())
        path.unlink()
        self.assertTrue(openui.system_prompt().startswith("## 채팅 규칙"))

    def test_demo_rules_cover_the_contract(self):
        for part in ("root = Card([...])", "펜스", "TextContent", "src1", "[src1, src2, …, srcN]", "[1][2]", "PlaceCard",
                     "ItineraryStop", "지어내지 않는다", "ai365://", "FollowUpBlock", "2~3개", "한국어", "[LANGUAGE]", "Form answers:"):
            self.assertIn(part, openui.DEMO_RULES)
        self.assertNotIn("—", openui.DEMO_RULES)   # em dash 금지 / no em dash


class NumberedSourcesTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("app.catalog.kn_locate", return_value=KN_PATH))

    def test_knowledge_local_and_web_in_order(self):
        doc = "보안 규정 & 지침?#.pdf"
        kn = kn_result(doc=doc, page=2)
        kn["extras"]["references"].append({"doc": doc, "page": 2})          # 중복 / duplicate
        kn["extras"]["references"].append({"doc": "목차.pdf", "page": None})
        kn["extras"]["web_sources"] = [{"title": "w1.com", "url": "https://w1.com/a"}]
        results = {"knowledge": kn, "local:kl_demo_hq": local_result(),
                   "k2": {"agent": "knowledge", "extras": {"references": [{"doc": "", "page": 1}]}}}
        web = [{"title": "w2.com", "url": "https://w2.com/b"}, {"title": "w1.com", "url": "https://w1.com/a"}]
        out = openui.numbered_sources(results, web)
        self.assertEqual([s["n"] for s in out], [1, 2, 3, 4, 5])
        self.assertEqual([s["kind"] for s in out], ["knowledge", "knowledge", "local", "web", "web"])
        k = out[0]
        self.assertEqual((k["title"], k["sourceName"]), (f"{doc} p.2", "지식 관리 › 인사 › 규정"))
        self.assertEqual(k["url"], f"ai365://kn/{quote(doc, safe='')}?page=2")
        self.assertEqual(unquote(k["url"][len("ai365://kn/"):].split("?")[0]), doc)
        self.assertEqual(k["excerpt"], "제12조 연차는 1년 근속 시 15일을 부여한다.")
        self.assertEqual((out[1]["title"], out[1]["url"]), ("목차.pdf", f"ai365://kn/{quote('목차.pdf', safe='')}"))
        self.assertNotIn("excerpt", out[1])
        loc = out[2]
        self.assertEqual((loc["title"], loc["sourceName"]), ("보안 정책 p.2", "로컬 · 본사 로컬 에이전트"))
        self.assertEqual(loc["url"], f"ai365://local/kl_demo_hq/hq-doc-001?page=2&title={quote('보안 정책', safe='')}")
        self.assertEqual(loc["excerpt"], "비밀번호 변경 주기는 90일이다.")
        self.assertEqual([(s["title"], s["url"]) for s in out[3:]], [("w1.com", "https://w1.com/a"), ("w2.com", "https://w2.com/b")])
        self.assertEqual(openui.web_index_map(out, web), {1: 5, 2: 4})

    def test_no_sources(self):
        self.assertEqual(openui.numbered_sources({}, None), [])
        self.assertEqual(openui.numbered_sources({"data": {"agent": "data", "extras": {"rows": [[1]]}}}, []), [])


# ── 경로 배선 / wired paths ─────────────────────────────────────────────────────────────

class _Wired(unittest.IsolatedAsyncioTestCase):
    MODE = "on"

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        oui_env(self.stack, mode=self.MODE)
        self.chat = db.create_chat("openui", "사내")
        self.stack.enter_context(patch("app.catalog.kn_locate", return_value=KN_PATH))
        self.stack.enter_context(patch("app.catalog.data_locate", side_effect=data_locate))
        self.stack.enter_context(patch("app.answers._smooth", side_effect=_one))
        self.stack.enter_context(patch("app.llm.generate", side_effect=AssertionError("unexpected llm.generate")))
        self.stack.enter_context(patch("app.llm.generate_grounded_meta", side_effect=AssertionError("unexpected grounding")))
        self.stack.enter_context(patch("app.llm.stream", side_effect=AssertionError("unexpected llm.stream")))

    def use_stream(self, *outputs) -> FakeStream:
        fake = FakeStream(*outputs)
        self.stack.enter_context(patch("app.llm.stream", side_effect=fake))
        return fake

    def saved(self) -> dict:
        return [m for m in db.list_messages(self.chat["id"]) if m["role"] == "assistant"][-1]

    def make_run(self, d, scope="사내", ui_format="auto", lane="chat", context=None):
        run = conversation.create(self.chat, d, QUESTION, context or CTX, scope, None, {}, "", "", ui_format=ui_format)
        run["snapshot"]["lane"] = lane
        store.save(run)
        return run


class WiredPathTests(_Wired):
    async def test_knowledge_fast_path_writes_one_program(self):
        fake = self.use_stream(MODEL)
        ev = await collect(answers._aggregate_answer(self.chat["id"], "사내", CTX, {"knowledge": kn_result()}, fmt="openui"))
        self.assertEqual(ev[0], {"type": "answer_head", "source": "사내", "format": "openui", "ui_mode": "program"})
        numbered = openui.numbered_sources({"knowledge": kn_result()})
        tokens = [e["text"] for e in ev if e["type"] == "token"]
        self.assertEqual(tokens[0], openui.source_statements(numbered) + "\n")   # 첫 token = 출처 문장 / first token = sources
        self.assertTrue(tokens[0].startswith('src1 = {title: "인사 규정.pdf p.3", sourceName: "지식 관리 › 인사 › 규정", url: "ai365://kn/'))
        done = ev[-1]
        self.assertEqual(set(done), {"type", "format", "program", "plain", "ui_report", "references", "sources", "message_id"})
        self.assertEqual(done["program"], "".join(tokens))
        self.assertEqual((done["plain"], done["ui_report"]), (MODEL_PLAIN, {"has_root": True, "fenced": False, "fallback": False}))
        self.assertEqual(done["references"], [{"doc": DOC, "page": 3}])
        self.assertEqual(done["sources"]["knowledge"]["items"][0]["path"], KN_PATH["path"])
        # 작성 호출 1회: 생성 프롬프트 + 채팅 규칙 + 지식 규칙, 마지막 메시지 = 번호 출처(발췌) + 지식 답 + 질문
        # One compose call: generated prompt + chat rules + knowledge rules; last message = numbered sources + answer + question
        self.assertEqual(len(fake.calls), 1)
        system, last = fake.calls[0]["system"], fake.calls[0]["messages"][-1]["content"]
        for part in (PROMPT, openui.DEMO_RULES, openui.KNOWLEDGE_RULES):
            self.assertIn(part, system)
        for part in ("발췌: 제12조 연차는 1년 근속 시 15일을 부여한다.", "[지식 에이전트 답변]\n연차는 15일입니다.", "## 사용자 질문\n" + QUESTION):
            self.assertIn(part, last)
        self.assertEqual(fake.calls[0]["messages"][:2], CTX[:2])
        row = self.saved()
        self.assertEqual(row["content"], done["program"])
        self.assertEqual(row["meta"]["format"], "openui")
        self.assertEqual(row["meta"]["ui_mode"], "program")
        self.assertEqual(row["meta"]["plain"], MODEL_PLAIN)
        self.assertEqual(row["id"], done["message_id"])
        dumped = json.dumps(row["meta"], ensure_ascii=False)
        self.assertNotIn("excerpt", dumped)
        self.assertNotIn("제12조", dumped)

    async def test_aggregate_with_local_results_writes_a_program(self):
        fake = self.use_stream(MODEL)
        results = {"knowledge": kn_result(), "local:kl_demo_hq": local_result()}
        ev = await collect(answers._aggregate_answer(self.chat["id"], "사내", CTX, results, fmt="openui", local_done=True))
        done = ev[-1]
        self.assertEqual(done["format"], "openui")
        numbered = openui.numbered_sources(results)
        self.assertEqual([s["kind"] for s in numbered], ["knowledge", "local"])
        self.assertTrue(done["program"].startswith(openui.source_statements(numbered) + "\nroot = Card("))
        self.assertIn("src2 = {title: \"보안 정책 p.2\", sourceName: \"로컬 · 본사 로컬 에이전트\"", done["program"])
        system, last = fake.calls[0]["system"], fake.calls[0]["messages"][-1]["content"]
        self.assertIn(openui.AGGREGATE_RULES, system)
        self.assertIn("로컬 지식 에이전트 · 이름", system)       # 로컬 규칙 / the local rule
        self.assertIn("[에이전트 실행 결과]", last)
        evidence_json = last[last.index("[에이전트 실행 결과]"):last.index("## 사용자 질문")]
        self.assertNotIn('"excerpts"', evidence_json)               # 취합 블록엔 발췌 없음 / no excerpts in the results block
        self.assertIn("발췌: 비밀번호 변경 주기는 90일이다.", last)
        meta = self.saved()["meta"]
        self.assertEqual([s["id"] for s in meta["steps"]], ["knowledge", "local:kl_demo_hq"])
        self.assertEqual(meta["sources"]["local"]["items"][0]["doc_id"], "hq-doc-001")

    async def test_work_connector_and_pending_actions_stay_markdown(self):
        # 2단계(계약 9.1절): 데이터 · 그룹웨어 조회는 OpenUI 지만 업무 자동화 · 커넥터 · 실행 대기(action_draft · await_recipient)가 섞이면
        # 종전 마크다운 / phase 2: data and groupware reads are OpenUI, but work, connector and pending actions keep markdown
        draft = {"kind": "mail.action.compose", "payload": {"to": "self"}, "summary": "메일"}
        cases = {
            "work": {"w1": {"agent": "work", "status": "answer", "text": "업무 결과", "extras": {"auto_label": "교육 에이전트"}}},
            "connector": {"connector:c1": {"agent": "connector", "label": "가상 API", "status": "answer", "text": "API 결과", "extras": {}}},
            "action_draft": {"groupware": {"agent": "groupware", "status": "answer", "text": "메일 초안", "extras": {"action_draft": draft}}},
            "await_recipient": {"groupware": {"agent": "groupware", "status": "answer", "text": "누구에게 보낼까요?",
                                              "extras": {"await_recipient": True}}},
        }
        for label, extra in cases.items():
            fake = self.use_stream(["매출 요약입니다."])
            results = {"knowledge": kn_result(), "s1": data_result(), **extra}
            ev = await collect(answers._aggregate_answer(self.chat["id"], "사내", CTX, results, fmt="openui", local_done=True))
            self.assertEqual(ev[0], {"type": "answer_head", "source": "사내"}, label)
            self.assertNotIn("format", ev[-1], label)
            self.assertTrue(fake.calls[0]["system"].startswith(ANSWER_SYSTEM), label)
            self.assertNotIn(PROMPT, fake.calls[0]["system"], label)
            self.assertEqual(self.saved()["content"], "매출 요약입니다.", label)
            self.assertNotIn("format", self.saved()["meta"], label)

    async def test_external_inserts_grounding_markers_and_numbers_sources(self):
        text = "서울은 맑다. 내일은 비가 온다."
        gmeta = {"text": text, "sources": [{"title": "a.com", "url": "https://a.com/x"}, {"title": "b.com", "url": "https://b.com/y"},
                                           {"title": "a.com", "url": "https://a.com/x"}],
                 "supports": [{"end": 7, "ns": [1]}, {"end": len(text), "ns": [2, 3]}]}
        fake = self.use_stream(MODEL)
        with patch("app.llm.generate_grounded_meta", return_value=gmeta):
            ev = await collect(answers._run_external(self.chat["id"], CTX, "", fmt="openui"))
        self.assertEqual([e["type"] for e in ev][:2], ["thinking", "answer_head"])
        self.assertEqual(ev[1]["format"], "openui")
        last = fake.calls[0]["messages"][-1]["content"]
        self.assertIn("[웹 검색 답변]\n서울은 맑다.[1] 내일은 비가 온다.[1][2]", last)
        self.assertIn(openui.EXTERNAL_RULES, fake.calls[0]["system"])
        done = ev[-1]
        self.assertTrue(done["_grounded"])
        self.assertEqual(done["sources"], {"external": [{"n": 1, "title": "a.com", "url": "https://a.com/x"},
                                                       {"n": 2, "title": "b.com", "url": "https://b.com/y"},
                                                       {"n": 3, "title": "a.com", "url": "https://a.com/x"}]})
        self.assertTrue(done["program"].startswith('src1 = {title: "a.com", sourceName: "a.com", url: "https://a.com/x"}\n'
                                                   'src2 = {title: "b.com", sourceName: "b.com", url: "https://b.com/y"}\n'))
        self.assertEqual(self.saved()["meta"]["source"], "외부")

    async def test_external_without_grounding_writes_a_program_without_sources(self):
        from app import llm
        fake = self.use_stream(['root = Card([b])\nb = TextContent("일반 지식 답")'])
        with patch("app.llm.generate_grounded_meta", side_effect=llm.GroundingUnavailableError("off")):
            ev = await collect(answers._run_external(self.chat["id"], CTX, "", fmt="openui"))
        done = ev[-1]
        self.assertFalse(done["_grounded"])
        self.assertNotIn("sources", done)
        self.assertEqual(done["program"], 'root = Card([b])\nb = TextContent("일반 지식 답")')
        self.assertIn(openui.EXTERNAL_FALLBACK_RULES, fake.calls[0]["system"])
        self.assertIn("(없음:", fake.calls[0]["messages"][-1]["content"])

    async def test_auto_supplement_markers_follow_the_internal_sources(self):
        text = "오늘 환율은 1,340원이다."
        gmeta = {"text": text, "sources": [{"title": "fx.com", "url": "https://fx.com"}], "supports": [{"end": len(text), "ns": [1]}]}
        fake = self.use_stream(MODEL)
        results = {"k1": kn_result(), "k2": {"agent": "knowledge", "status": "not_found", "text": "", "extras": {},
                                             "fail_reason": "사내 문서에서 관련 근거를 찾지 못했습니다."}}
        with patch("app.llm.generate_grounded_meta", return_value=gmeta), \
                patch.object(answers, "_judge_gap", return_value={"complete": False, "missing": "환율"}):
            ev = await collect(answers._auto_answer(self.chat["id"], "사내", CTX, QUESTION, results, fmt="openui"))
        last = fake.calls[0]["messages"][-1]["content"]
        self.assertIn("[웹 보완 정보]", last)
        self.assertIn("1,340원이다.[2]", last)                      # 사내 출처 1개 뒤 = [2] / after one internal source
        self.assertIn("[2] fx.com", last)
        self.assertIn(openui.BLEND_RULES.strip(), fake.calls[0]["system"])
        done = ev[-1]
        self.assertEqual((done["format"], done.get("_web_resolved")), ("openui", True))
        self.assertEqual(self.saved()["meta"]["source"], "사내|웹 보완")

    async def test_mixed_results_get_no_openui_markers_in_the_markdown_blend(self):
        # 취합이 마크다운이면(ui_eligible 이 False) 웹 보완 글에 OpenUI [n] 표식을 넣지 않는다(검토 반영). 2단계부터 데이터는 OpenUI 대상이고,
        # 그룹웨어 · 업무 · 커넥터는 웹 보완 앞에서 빠지므로 판정 함수를 False 로 바꿔 같은 조건을 본다.
        # When the aggregation is markdown (ui_eligible False) the web supplement gets no OpenUI [n] markers (review fix). Since
        # phase 2 data is OpenUI-eligible and groupware / work / connector skip the web supplement, the check is forced False.
        text = "오늘 환율은 1,340원이다."
        gmeta = {"text": text, "sources": [{"title": "fx.com", "url": "https://fx.com"}], "supports": [{"end": len(text), "ns": [1]}]}
        fake = self.use_stream(["마크다운 답"])
        results = {"k1": kn_result(), "k2": {"agent": "knowledge", "status": "not_found", "text": "", "extras": {},
                                             "fail_reason": "사내 문서에서 관련 근거를 찾지 못했습니다."},
                   "d1": {"agent": "data", "status": "analysis", "text": "분석", "extras": {"rows": [[1]], "columns": ["n"], "sql": "SELECT 1"}}}
        with patch("app.llm.generate_grounded_meta", return_value=gmeta), \
                patch.object(answers, "_judge_gap", return_value={"complete": False, "missing": "환율"}), \
                patch.object(openui, "ui_eligible", return_value=False):
            ev = await collect(answers._auto_answer(self.chat["id"], "사내", CTX, QUESTION, results, fmt="openui"))
        self.assertNotIn("format", next(e for e in ev if e["type"] == "answer_head"))
        last = fake.calls[0]["messages"][-1]["content"]
        self.assertIn("[웹 보완 정보]", last)
        self.assertIn(text + "\n\n위 결과를 바탕으로", last)    # 표식 없이 바로 끝맺음 지시 / no marker before the closing instruction
        self.assertNotIn("1,340원이다.[", last)
        self.assertTrue(fake.calls[0]["system"].startswith(answers.ANSWER_SYSTEM_BLEND))

    async def test_auto_all_not_found_goes_to_the_openui_web_answer(self):
        seen = []

        async def external(chat_id, context, lang_note="", **kw):
            seen.append(kw)
            yield {"type": "done", "_grounded": True}
        with patch.object(answers, "_run_external", external):
            await collect(answers._auto_answer(self.chat["id"], "사내", CTX, QUESTION,
                                               {"k": {"agent": "knowledge", "status": "not_found", "extras": {}}}, fmt="openui"))
        self.assertEqual(seen, [{"fmt": "openui"}])

    async def test_direct_answer_uses_text_mode(self):
        fake = self.use_stream(["안녕하세요. ", "무엇을 도와드릴까요?"])
        run = self.make_run(decision())
        ev = await collect(conversation.drive(run, self.chat, [], None))
        head = next(e for e in ev if e["type"] == "answer_head")
        self.assertEqual(head, {"type": "answer_head", "source": "사내", "format": "openui", "ui_mode": "text"})
        self.assertEqual([e["text"] for e in ev if e["type"] == "token"], ["안녕하세요. ", "무엇을 도와드릴까요?"])
        done = next(e for e in ev if e["type"] == "done")
        md = "안녕하세요. 무엇을 도와드릴까요?"
        self.assertEqual((done["program"], done["plain"]), (openui.wrap_text(md), md))
        self.assertEqual(fake.calls[0]["system"], DIRECT_SYSTEM)              # 긴 OpenUI 프롬프트 없음 / no OpenUI prompt
        self.assertEqual(fake.calls[0]["messages"], CTX)
        saved = store.get(run["id"])
        self.assertEqual((saved["state"], saved["snapshot"]["report"], saved["snapshot"]["ui_format"]), ("completed", md, "auto"))
        self.assertEqual(self.saved()["meta"]["ui_mode"], "text")

    async def test_drive_markdown_opt_out_and_explore_lane(self):
        for ui_format, lane in (("markdown", "chat"), ("auto", "explore")):
            fake = self.use_stream(["평문 답"])
            run = self.make_run(decision(), ui_format=ui_format, lane=lane)
            ev = await collect(conversation.drive(run, self.chat, [], None))
            head = next(e for e in ev if e["type"] == "answer_head")
            self.assertEqual(head, {"type": "answer_head", "source": "사내"}, (ui_format, lane))
            self.assertNotIn("format", next(e for e in ev if e["type"] == "done"))
            self.assertEqual(fake.calls[0]["system"], DIRECT_SYSTEM)

    async def test_auto_scope_passes_fmt_and_resume_keeps_the_snapshot_value(self):
        calls = []

        async def recorder(*args, **kwargs):
            calls.append(kwargs)
            yield {"type": "token", "text": "답"}
            yield {"type": "done", "format": "openui", "plain": "답"}
        with patch.dict(AGENT_REGISTRY["knowledge"], {"run": AsyncMock(return_value=kn_result())}), \
                patch.object(answers, "_auto_answer", recorder):
            run = self.make_run(decision([step("knowledge")]), scope="자동")
            await collect(conversation.drive(run, self.chat, [], None))
            self.assertEqual(calls[-1], {"fmt": "openui"})
            off = self.make_run(decision([step("knowledge")]), scope="자동", ui_format="markdown")
            await collect(conversation.drive(off, self.chat, [], None))
            self.assertEqual(calls[-1], {})
        self.assertEqual(store.get(run["id"])["snapshot"]["report"], "답")

    async def test_send_and_document_runs_stay_markdown(self):
        calls = []

        async def recorder(*args, **kwargs):
            calls.append(kwargs)
            yield {"type": "answer_head", "source": "사내"}
            yield {"type": "done"}
        probe = {"status": "answer", "extras": {"action_draft": {"kind": "mail.action.compose", "payload": {"to": "self"}, "summary": "메일"}}}
        with patch.dict(AGENT_REGISTRY["knowledge"], {"run": AsyncMock(return_value=kn_result())}), \
                patch.object(answers, "_aggregate_answer", recorder), \
                patch.object(answers, "_auto_answer", recorder), \
                patch("app.agents.groupware.run", AsyncMock(return_value=probe)):
            send = self.make_run(decision([step("knowledge")], send_query="결과를 나에게 메일로 보내줘"), scope="자동")
            await collect(conversation.drive(send, self.chat, [], None))
            doc = self.make_run(decision([step("knowledge")], document={"format": "pdf", "topic": "연차"}), scope="자동")
            doc["snapshot"]["doc_cfg"] = {"format": "pdf", "topic": "연차", "style": "report", "length": 2, "source": "context"}
            store.save(doc)
            await collect(conversation.drive(doc, self.chat, [], None))
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("fmt" not in c for c in calls))

    # ── 작성 호출 실패 / compose-call failures ──
    # 지식 고속경로 · 그라운딩 웹 답은 완성된 근거 답으로 대신하고(1 · 2), 일반 취합 · 직접 답은 종전처럼 다시 던지거나 중단 안내(3),
    # 근거 답 대체는 done 하나 · drive 에서 답 완료 · 보고서 = 평문(4)
    # The knowledge fast path and the grounded web answer fall back to the finished evidence (1, 2); the general aggregation and
    # direct answers keep re-raising / the interruption note (3); a fallback sends one done and drive counts it as answered (4).

    @staticmethod
    def two_results() -> dict:
        return {"k1": kn_result(), "k2": kn_result(doc="복무 규정.pdf", page=5, text="반차는 4시간입니다.")}

    async def test_fast_path_compose_failure_before_the_first_token_streams_the_wrapped_draft(self):   # 1
        self.use_stream([RuntimeError("504 DEADLINE_EXCEEDED")])
        self.stack.enter_context(patch("app.answers._smooth", new=REAL_SMOOTH))   # 실제로 잘게 흘리는지 / real smoothing
        numbered = openui.numbered_sources({"knowledge": kn_result()})
        with self.assertLogs("ai365.openui", level="WARNING") as logs:
            ev = await collect(answers._aggregate_answer(self.chat["id"], "사내", CTX, {"knowledge": kn_result()}, fmt="openui"))
        program = openui.wrap_text("연차는 15일입니다.", sources=numbered)
        self.assertEqual(ev[0], {"type": "answer_head", "source": "사내", "format": "openui", "ui_mode": "program"})
        tokens = [e["text"] for e in ev if e["type"] == "token"]
        self.assertGreater(len(tokens), 1)
        self.assertEqual("".join(tokens), program)
        dones = [e for e in ev if e["type"] == "done"]
        self.assertEqual(len(dones), 1)
        self.assertEqual((dones[0]["program"], dones[0]["plain"]), (program, "연차는 15일입니다."))
        self.assertEqual(dones[0]["ui_report"], {"has_root": False, "fenced": False, "fallback": True})
        self.assertEqual(dones[0]["references"], [{"doc": DOC, "page": 3}])
        self.assertIn("첫 토큰 전", "\n".join(logs.output))
        row = self.saved()
        self.assertEqual((row["content"], row["meta"]["plain"], row["meta"]["format"]), (program, "연차는 15일입니다.", "openui"))

    async def test_fast_path_mid_stream_failure_uses_the_complete_draft(self):   # 1
        self.use_stream([MODEL[0], RuntimeError("503 UNAVAILABLE")])
        numbered = openui.numbered_sources({"knowledge": kn_result()})
        with self.assertLogs("ai365.openui", level="WARNING"):
            ev = await collect(answers._aggregate_answer(self.chat["id"], "사내", CTX, {"knowledge": kn_result()}, fmt="openui"))
        tokens = [e["text"] for e in ev if e["type"] == "token"]
        self.assertEqual(tokens, [openui.source_statements(numbered) + "\n", MODEL[0]])   # 흘린 것은 부분뿐 / only the partial went out
        self.assertEqual(sum(e["type"] == "done" for e in ev), 1)
        done = ev[-1]
        self.assertEqual(done["program"], openui.wrap_text("연차는 15일입니다.", sources=numbered))
        self.assertEqual(done["plain"], "연차는 15일입니다.")
        self.assertEqual(done["ui_report"], {"has_root": True, "fenced": False, "fallback": True})
        self.assertNotIn(_INTERRUPT_NOTE, done["program"] + done["plain"])
        self.assertEqual(self.saved()["content"], done["program"])

    async def test_fast_path_empty_reply_uses_the_draft(self):   # 1 (빈 답 / an empty reply)
        self.use_stream([])
        numbered = openui.numbered_sources({"knowledge": kn_result()})
        with self.assertLogs("ai365.openui", level="WARNING"):
            ev = await collect(answers._aggregate_answer(self.chat["id"], "사내", CTX, {"knowledge": kn_result()}, fmt="openui"))
        program = openui.wrap_text("연차는 15일입니다.", sources=numbered)
        self.assertEqual([e["text"] for e in ev if e["type"] == "token"], [program])
        self.assertEqual((ev[-1]["program"], ev[-1]["ui_report"]["fallback"]), (program, True))

    async def test_external_compose_failure_falls_back_to_the_grounded_text(self):   # 2
        text = "서울은 맑다. 내일은 비가 온다."
        gmeta = {"text": text, "sources": [{"title": "a.com", "url": "https://a.com/x"}, {"title": "b.com", "url": "https://b.com/y"},
                                           {"title": "a.com", "url": "https://a.com/x"}],
                 "supports": [{"end": 7, "ns": [1]}, {"end": len(text), "ns": [2, 3]}]}
        marked = "서울은 맑다.[1] 내일은 비가 온다.[1][2]"
        numbered = openui.numbered_sources({}, gmeta["sources"])
        for label, outputs, has_root in (("before", [RuntimeError("504 DEADLINE_EXCEEDED")], False),
                                         ("mid", [MODEL[0], RuntimeError("503 UNAVAILABLE")], True)):
            self.use_stream(outputs)
            with patch("app.llm.generate_grounded_meta", return_value=copy.deepcopy(gmeta)), \
                    self.assertLogs("ai365.openui", level="WARNING"):
                ev = await collect(answers._run_external(self.chat["id"], CTX, "", fmt="openui"))
            dones = [e for e in ev if e["type"] == "done"]
            self.assertEqual(len(dones), 1, label)
            done = dones[0]
            self.assertEqual(done["program"], openui.wrap_text(marked, sources=numbered), label)
            self.assertEqual(done["plain"], marked, label)
            self.assertEqual(done["ui_report"], {"has_root": has_root, "fenced": False, "fallback": True}, label)
            self.assertTrue(done["_grounded"], label)
            self.assertEqual(len(done["sources"]["external"]), 3, label)
            self.assertEqual(self.saved()["content"], done["program"], label)

    async def test_external_without_grounding_has_no_evidence_and_reraises(self):   # 2 · 3
        from app import llm
        self.use_stream([RuntimeError("504 DEADLINE_EXCEEDED")])
        with patch("app.llm.generate_grounded_meta", side_effect=llm.GroundingUnavailableError("off")), \
                self.assertRaises(RuntimeError):
            await collect(answers._run_external(self.chat["id"], CTX, "", fmt="openui"))
        self.assertEqual([m for m in db.list_messages(self.chat["id"]) if m["role"] == "assistant"], [])

    async def test_aggregation_interrupted_after_a_partial_answer(self):   # 3
        self.use_stream(['root = Card([body])\n', 'body = TextContent("연차는 15일', RuntimeError("429 RESOURCE_EXHAUSTED")])
        results = self.two_results()
        numbered = openui.numbered_sources(results)
        with self.assertLogs("ai365.openui", level="WARNING"):
            ev = await collect(answers._aggregate_answer(self.chat["id"], "사내", CTX, results, fmt="openui"))
        done = ev[-1]
        text = "연차는 15일\n\n" + _INTERRUPT_NOTE
        self.assertEqual(sum(e["type"] == "done" for e in ev), 1)
        self.assertEqual(done["program"], openui.wrap_text(text, sources=numbered))
        self.assertEqual(done["plain"], text)
        self.assertEqual(done["ui_report"], {"has_root": True, "fenced": False, "fallback": True})
        self.assertEqual(self.saved()["content"], done["program"])

    async def test_aggregation_failure_before_any_token_reraises_without_saving(self):   # 3
        self.use_stream([RuntimeError("429 RESOURCE_EXHAUSTED")])
        events = []
        with self.assertRaises(RuntimeError):
            async for e in answers._aggregate_answer(self.chat["id"], "사내", CTX, self.two_results(), fmt="openui"):
                events.append(e)
        self.assertEqual([e["type"] for e in events], ["answer_head"])   # 출처 문장도 아직 안 보냄 / no source token yet
        self.assertEqual([m for m in db.list_messages(self.chat["id"]) if m["role"] == "assistant"], [])

    async def test_text_mode_ignores_fallback_text_and_keeps_the_error_path(self):   # 3
        self.use_stream([RuntimeError("504 DEADLINE_EXCEEDED")])
        with self.assertRaises(RuntimeError):
            await collect(openui.stream_program(self.chat["id"], "사내", CTX, DIRECT_SYSTEM, mode="text", fallback_text="무시됨"))
        # drive 의 직접 답: 첫 토큰 전 실패는 종전(마크다운)처럼 error · interrupted / a direct answer's early failure: error + interrupted
        self.use_stream([RuntimeError("504 DEADLINE_EXCEEDED")])
        run = self.make_run(decision())
        ev = await collect(conversation.drive(run, self.chat, [], None))
        self.assertEqual(ev[-1]["type"], "error")
        self.assertFalse(any(e["type"] == "done" for e in ev))
        self.assertEqual(store.get(run["id"])["state"], "interrupted")

    async def test_drive_treats_evidence_fallbacks_as_answered(self):   # 4
        # (a) 지식 고속경로 · 첫 토큰 전 실패 / knowledge fast path, failure before the first token
        self.use_stream([RuntimeError("504 DEADLINE_EXCEEDED")])
        with patch.dict(AGENT_REGISTRY["knowledge"], {"run": AsyncMock(return_value=kn_result())}), \
                self.assertLogs("ai365.openui", level="WARNING"):
            run = self.make_run(decision([step("knowledge")]))
            ev = await collect(conversation.drive(run, self.chat, [], None))
        self.assertEqual(sum(e["type"] == "done" for e in ev), 1)
        self.assertFalse(any(e["type"] == "error" for e in ev))
        saved = store.get(run["id"])
        self.assertEqual((saved["state"], saved["snapshot"]["report"], saved["snapshot"]["answer_done"]),
                         ("completed", "연차는 15일입니다.", True))
        # (b) 자동 · 사내 못 찾음 → 웹 답 · 도중 실패 / auto: nothing internal → web answer, mid-stream failure
        web_text = "웹 답입니다."
        gmeta = {"text": web_text, "sources": [{"title": "a.com", "url": "https://a.com"}], "supports": [{"end": len(web_text), "ns": [1]}]}
        miss = {"status": "not_found", "text": "", "extras": {}, "fail_reason": "사내 문서에서 관련 근거를 찾지 못했습니다."}
        self.use_stream([MODEL[0], RuntimeError("503 UNAVAILABLE")])
        with patch.dict(AGENT_REGISTRY["knowledge"], {"run": AsyncMock(return_value=miss)}), \
                patch("app.llm.generate_grounded_meta", return_value=gmeta), self.assertLogs("ai365.openui", level="WARNING"):
            run = self.make_run(decision([step("knowledge")]), scope="자동")
            ev = await collect(conversation.drive(run, self.chat, [], None))
        dones = [e for e in ev if e["type"] == "done"]
        self.assertEqual(len(dones), 1)
        self.assertTrue(dones[0].get("_web_resolved"))
        self.assertFalse(any(e["type"] == "error" for e in ev))
        saved = store.get(run["id"])
        self.assertEqual((saved["state"], saved["snapshot"]["report"]), ("completed", "웹 답입니다.[1]"))

    async def test_text_mode_interruption_and_drive_marks_the_run_interrupted(self):
        self.use_stream(["안녕하세요", RuntimeError("503 UNAVAILABLE")])
        run = self.make_run(decision())
        with self.assertLogs("ai365.openui", level="WARNING"):
            ev = await collect(conversation.drive(run, self.chat, [], None))
        tokens = [e["text"] for e in ev if e["type"] == "token"]
        self.assertEqual(tokens, ["안녕하세요", "\n\n" + _INTERRUPT_NOTE])
        done = next(e for e in ev if e["type"] == "done")
        self.assertEqual(done["program"], openui.wrap_text("안녕하세요\n\n" + _INTERRUPT_NOTE))
        self.assertEqual(done["ui_report"]["fallback"], False)
        self.assertEqual(ev[-1]["type"], "error")                          # 종전처럼 후속 보류 / follow-ups held, as before
        self.assertEqual(store.get(run["id"])["state"], "interrupted")


class HistoryTests(_Wired):
    async def test_history_and_context_read_the_plain_text(self):
        cid = self.chat["id"]
        db.add_message(cid, "user", "연차 알려줘")
        program = openui.wrap_text("연차는 15일입니다 [1].", sources=[{"title": "a", "sourceName": "b", "url": "c"}])
        db.add_message(cid, "assistant", program, {"source": "사내", "format": "openui", "ui_mode": "program",
                                                    "plain": "연차는 15일입니다 [1]."})
        db.add_message(cid, "assistant", "마크다운 답", {"source": "사내"})
        self.assertEqual([m["content"] for m in run_context.history(cid)], ["연차 알려줘", "연차는 15일입니다 [1].", "마크다운 답"])
        self.assertEqual([m["content"] for m in run_context.history(cid, "explore")][1], "연차는 15일입니다 [1].")
        ctx = pipeline._build_context(cid, "다음 질문")
        self.assertEqual([m["content"] for m in ctx], ["연차 알려줘", "연차는 15일입니다 [1].", "마크다운 답", "다음 질문"])
        self.assertEqual([m["content"] for m in db.list_messages(cid)][1], program)   # DB 행은 프로그램 그대로 / rows unchanged
        from app import docgen
        self.assertIn("연차는 15일입니다 [1].", str(docgen._context_messages(cid, "현재")))
        self.assertNotIn("TextContent", str(docgen._context_messages(cid, "현재")))


class ScheduleTests(unittest.IsolatedAsyncioTestCase):
    """예약 실행(헤드리스): 알림 메일 미리보기는 OpenUI 답의 평문, 각주 귀속은 건너뜀 / schedule runs: the mail preview is the plain text"""

    def setUp(self):
        from app import collections_store, schedules
        self.schedules = schedules
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        collections_store.init_collections()
        schedules.init_schedules()
        self.stack.enter_context(patch.object(schedules, "_owner_names", return_value={}))
        self.stack.enter_context(patch.object(pipeline, "_resolve_eff", return_value=None))

    async def test_notify_preview_uses_the_plain_text(self):
        plain = "연차는 15일입니다 [1]."
        program = openui.wrap_text(plain, sources=[{"title": "a.pdf p.1", "sourceName": "지식 관리", "url": "ai365://kn/a.pdf?page=1"}])

        async def fake_pipeline(chat, message, scope, *args, **kwargs):
            mid = db.add_message(chat["id"], "assistant", program,
                                 {"source": "사내", "format": "openui", "ui_mode": "program", "plain": plain})
            yield {"type": "answer_head", "source": "사내", "format": "openui", "ui_mode": "program"}
            yield {"type": "token", "text": program}
            yield {"type": "done", "format": "openui", "program": program, "plain": plain, "message_id": mid,
                   "references": [{"doc": "a.pdf", "page": 1}], "sources": {"knowledge": {"folders": 1, "files": 1, "items": []}}}
        s = self.schedules.create(None, "", "test", "연차 정리해줘", "사내", "daily", "09:00", [], True, False)
        self.assertTrue(self.schedules.claim(s["id"], force=True))
        with patch.object(pipeline, "run_pipeline", fake_pipeline), patch.object(cite, "enrich_sources") as enrich:
            result, chat_id, preview = await self.schedules._fire_inner(s["id"], {})
        self.assertEqual((result, preview), ("ok", plain))
        enrich.assert_not_called()
        self.assertEqual(next(m["content"] for m in reversed(run_context.history(chat_id)) if m["role"] == "assistant"), plain)


# ── HTTP 끝점 · 기본(off) 불변 / HTTP endpoint and the unchanged default (off) ───────────────

class HttpTests(_Wired):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(pipeline, "_judge_intent", return_value=decision()))
        self.enrich = self.stack.enter_context(patch.object(cite, "enrich_sources", wraps=cite.enrich_sources))
        self.addCleanup(runs.RUNS.pop, self.chat["id"], None)

    def post(self, body: dict) -> list[dict]:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(chats_api.router)
        with TestClient(app) as client:
            r = client.post(f"/api/chats/{self.chat['id']}/stream", json=body)
            self.assertEqual(r.status_code, 200)
        return [json.loads(line[5:].strip()) for line in r.text.splitlines() if line.startswith("data:")]

    async def test_markdown_opt_out_and_enrichment_skip(self):
        self.assertEqual(chats_api.StreamBody(message="x").ui_format, "auto")
        self.use_stream(["마크다운 답"], ["UI 답"])
        ev = await asyncio.to_thread(self.post, {"message": "인사 규정 알려줘", "scope": "사내", "ui_format": "markdown"})
        head = next(e for e in ev if e["type"] == "answer_head")
        self.assertNotIn("format", head)
        self.assertNotIn("format", next(e for e in ev if e["type"] == "done"))
        self.assertEqual(self.enrich.call_count, 1)
        self.assertNotIn("format", self.saved()["meta"])
        ev = await asyncio.to_thread(self.post, {"message": "인사 규정 알려줘", "scope": "사내"})
        head = next(e for e in ev if e["type"] == "answer_head")
        self.assertEqual((head["format"], head["ui_mode"]), ("openui", "text"))
        done = next(e for e in ev if e["type"] == "done")
        self.assertEqual(done["program"], openui.wrap_text("UI 답"))
        self.assertEqual(self.enrich.call_count, 1)                        # OpenUI 답은 각주 귀속 건너뜀 / skipped for OpenUI
        self.assertEqual(self.saved()["meta"]["format"], "openui")
        self.assertIn("trace", self.saved()["meta"])


class DefaultOffTests(_Wired):
    """OPENUI_MODE=off — 모든 경로가 종전 그대로(기본값은 2026-10-27 부터 on) / OPENUI_MODE=off: every path as before (default is on)"""
    MODE = "off"

    async def test_fast_path_streams_the_agent_text_without_an_llm_call(self):
        ev = await collect(answers._aggregate_answer(self.chat["id"], "사내", CTX, {"knowledge": kn_result()}))
        self.assertEqual(ev[0], {"type": "answer_head", "source": "사내"})
        self.assertEqual([e["text"] for e in ev if e["type"] == "token"], ["연차는 15일입니다."])
        self.assertNotIn("format", ev[-1])
        self.assertEqual(self.saved()["content"], "연차는 15일입니다.")

    async def test_drive_and_external_and_http_stay_markdown(self):
        self.use_stream(["평문 답"], ["또 다른 답"])
        run = self.make_run(decision())
        ev = await collect(conversation.drive(run, self.chat, [], None))
        self.assertEqual(next(e for e in ev if e["type"] == "answer_head"), {"type": "answer_head", "source": "사내"})
        gmeta = {"text": "웹 답", "sources": [{"title": "a.com", "url": "https://a"}], "supports": [{"end": 3, "ns": [1]}]}
        with patch("app.llm.generate_grounded_meta", return_value=gmeta), \
                patch.object(pipeline, "_build_context", side_effect=lambda cid, msg, lane="chat": [{"role": "user", "content": msg}]):
            ev = await collect(pipeline.run_pipeline(self.chat, "최신 뉴스 알려줘", "외부"))
        done = ev[-1]
        self.assertEqual(done["sources"], {"external": [{"n": 1, "title": "a.com", "url": "https://a"}], "supports": [{"end": 3, "ns": [1]}]})
        self.assertEqual([e["text"] for e in ev if e["type"] == "token"], ["웹 답"])
        self.assertNotIn("format", done)
        with patch.object(pipeline, "_judge_intent", return_value=decision()):
            enrich = self.stack.enter_context(patch.object(cite, "enrich_sources", wraps=cite.enrich_sources))
            self.addCleanup(runs.RUNS.pop, self.chat["id"], None)
            ev = await asyncio.to_thread(HttpTests.post, self, {"message": "인사 규정 알려줘", "scope": "사내"})
        self.assertNotIn("format", next(e for e in ev if e["type"] == "answer_head"))
        self.assertEqual(enrich.call_count, 1)


# ── 2단계: 데이터 분석 · 그룹웨어 조회(계약 9절) / phase 2: data analysis and groupware reads (contract 9) ─────────────

class EligibilityTests(unittest.TestCase):
    """openui.ui_eligible 판정표(계약 9.1절) / the ui_eligible matrix (contract 9.1)"""

    def test_matrix(self):
        draft = {"kind": "mail.action.compose", "payload": {}, "summary": "메일"}
        bi = {"agent": "data", "status": "dashboard", "extras": {"thumb_url": "/x.png", "file": "a.pbix"}}
        yes = {
            "nothing": {},
            "knowledge + local": {"knowledge": kn_result(), "local:kl": local_result()},
            "data only": {"s1": data_result()},
            "BI dashboard": {"s1": bi},
            "groupware read": {"groupware": gw_result()},
            "groupware not found": {"groupware": {"agent": "groupware", "status": "not_found", "extras": {}}},
            "mixed internal": {"knowledge": kn_result(), "s1": data_result(), "groupware": gw_result(), "local:kl": local_result()},
            "agent from the key": {"knowledge:2": {}, "data": {"extras": {"rows": []}}, "groupware": {}},
        }
        no = {
            "work": {"knowledge": kn_result(), "w1": {"agent": "work", "status": "answer", "extras": {}}},
            "connector agent": {"s1": data_result(), "c": {"agent": "connector", "status": "answer"}},
            "connector key": {"connector:abc": {"status": "answer"}},
            "unknown agent": {"r1": {"agent": "report", "status": "answer"}},
            "groupware action_draft": {"groupware": {"agent": "groupware", "status": "answer", "extras": {"action_draft": draft}}},
            "groupware await_recipient": {"groupware": {"agent": "groupware", "status": "answer", "extras": {"await_recipient": True}}},
            "mixed with an action": {"s1": data_result(), "groupware": gw_result(action_draft=draft)},
        }
        for label, results in yes.items():
            self.assertTrue(openui.ui_eligible(results), label)
        for label, results in no.items():
            self.assertFalse(openui.ui_eligible(results), label)
        self.assertEqual(openui.UI_AGENTS, {"knowledge", "local", "data", "groupware"})


class DataStatementTests(unittest.TestCase):
    """서버 데이터 문장(계약 9.2절 + 섬 렌더 점검 조정): 모양 · 상한 · 계산 · 값 표기 / server data statements"""

    @staticmethod
    def block(results, numbered=None):
        return openui.data_statements(results, numbered or [])

    def test_small_table_shapes(self):
        b = self.block({"s1": data_result(rows=[["1월", 120, "개장"], ["2월", 135.5, None], ["3월", None, "보수"]],
                                          columns=["월", "매출액", "비고"])})
        self.assertEqual(b["text"].split("\n"), [
            'd1 = [{c1: "1월", c2: 120, c3: "개장"}, {c1: "2월", c2: 135.5, c3: null}, {c1: "3월", c2: null, c3: "보수"}]',
            "d1top = d1",                                         # 10행 이하면 별칭(늘 있다) / an alias up to 10 rows (always defined)
            'd1sum = {c2: {sum: 255.5, avg: 127.75, min: 120, max: 135.5, first: 120, last: null, change: null, chg: ""}}'])
        self.assertEqual((b["names"], b["data"], b["lists"], b["groupware"]), (["d1", "d1top", "d1sum"], 1, 0, False))
        self.assertIn("전체 3행, d1top = d1(전체가 10행 이하)", b["legend"])
        self.assertIn("c2 = 매출액(숫자, 빈 값 1개), c3 = 비고(문자, 빈 값 1개)", b["legend"])
        self.assertEqual(openui.data_statements({}, []),
                         {"text": "", "names": [], "legend": "", "data": 0, "lists": 0, "groupware": False})
        self.assertEqual(openui.data_statements({"knowledge": kn_result()})["text"], "")

    def test_caps_and_the_top_rows(self):
        rows = [[f"r{i}", i] for i in range(1, 61)]
        b = self.block({"s1": data_result(rows=rows, columns=["행", "값"])})
        lines = b["text"].split("\n")
        self.assertEqual([line.split(" = ", 1)[0] for line in lines], ["d1", "d1top", "d1sum"])
        self.assertEqual(lines[0].count("{c1:"), openui.DATA_ROWS)                        # 50
        self.assertTrue(lines[0].endswith('{c1: "r50", c2: 50}]'))
        self.assertNotIn('"r51"', lines[0])
        self.assertEqual(lines[1].count("{c1:"), openui.TOP_ROWS)                         # 10
        self.assertTrue(lines[1].endswith('{c1: "r10", c2: 10}]'))
        # 합계는 잘리지 않은 전체 60행 기준 / the stats cover all 60 rows, not the 50 sent
        self.assertEqual(lines[2], 'd1sum = {c2: {sum: 1830, avg: 30.5, min: 1, max: 60, first: 1, last: 60, change: 5900, '
                                   'chg: "+5900.0%"}}')
        self.assertIn("d1 는 전체 60행 중 앞 50행, d1top = 앞 10행, 합계 · 평균은 d1sum(전체 기준)", b["legend"])
        self.assertIn('{c1: "r20", c2: 20}', b["legend"])                                # 미리보기 20행 / a 20-row preview
        self.assertNotIn('{c1: "r21", c2: 21}', b["legend"])
        b11 = self.block({"s1": data_result(rows=rows[:11], columns=["행", "값"])})
        self.assertTrue(b11["text"].split("\n")[1].startswith('d1top = [{c1: "r1", c2: 1}'))
        self.assertIn("전체 11행, d1 = 11행 전부, d1top = 앞 10행", b11["legend"])
        wide = self.block({"s1": data_result(rows=[list(range(25))], columns=[f"col{i}" for i in range(25)])})
        self.assertIn("c20: 19}", wide["text"])                                          # 열 상한 20 / the column cap
        self.assertNotIn("c21", wide["text"])
        g = self.block({"groupware": gw_result(rows=[(f"항목 {i}", f"내용 {i}") for i in range(1, 36)])})
        self.assertEqual(g["text"].count("{left:"), openui.GW_ROWS)                       # 30
        self.assertNotIn("항목 31", g["text"])
        self.assertIn("전체 35행 중 gw1 = 앞 30행", g["legend"])

    def test_column_stats(self):
        columns = ["항목", "a", "b", "c", "d", "e", "f", "g"]
        rows = [["x", 100, 0, -50, "글", True, 0.1, 1.005],
                ["y", 112.34, 10, -25, 3, False, 0.2, None]]
        b = self.block({"s1": data_result(rows=rows, columns=columns)})
        self.assertEqual(b["text"].split("\n")[2], "d1sum = {"
                         'c2: {sum: 212.34, avg: 106.17, min: 100, max: 112.34, first: 100, last: 112.34, change: 12.3, chg: "+12.3%"}, '
                         'c3: {sum: 10, avg: 5, min: 0, max: 10, first: 0, last: 10, change: null, chg: ""}, '          # 첫 값 0 / first 0
                         'c4: {sum: -75, avg: -37.5, min: -50, max: -25, first: -50, last: -25, change: 50, chg: "+50.0%"}, '  # |first|
                         'c7: {sum: 0.3, avg: 0.15, min: 0.1, max: 0.2, first: 0.1, last: 0.2, change: 100, chg: "+100.0%"}, '  # 0.1+0.2
                         'c8: {sum: 1.005, avg: 1.01, min: 1.005, max: 1.005, first: 1.005, last: null, change: null, chg: ""}}')  # 사사오입
        for part in ("c2 = a(숫자)", "c5 = d(섞임)", "c6 = e(참거짓)", "c8 = g(숫자, 빈 값 1개)"):
            self.assertIn(part, b["legend"])
        self.assertEqual([openui._chg(v) for v in (21.6, -3.2, 0.0, -0.0, None, 7)], ["+21.6%", "-3.2%", "0.0%", "0.0%", "", "+7.0%"])

    def test_values_escaping_and_numeric_text(self):
        tricky = '따옴표 "인용" \\ 역슬래시\n줄 😀'
        columns = ["글", "n", "참", "nan", "긴 글", "실수", "큰 수", "코드", "금액", "정수 글자"]
        rows = [[tricky, None, True, float("nan"), "가" * 250, 120.0, 1e20, "00123", "1234.50", "1234"],
                ["둘째", 7, False, float("inf"), "짧음", 3.5, 2.5e-7, "00456", "99.90", "-5"]]
        b = self.block({"s1": data_result(rows=rows, columns=columns)})
        d1, _top, s = b["text"].split("\n")
        for part in ("c1: " + json.dumps(tricky, ensure_ascii=False), "c2: null", "c3: true", "c3: false", "c4: null",
                     'c5: "' + "가" * (openui.CELL_MAX - 1) + '…"',   # 긴 글 칸 자르기 / long text cells are cut
                     "c6: 120,",                                          # 정수인 실수는 정수로 / an integral float as an int
                     "c7: 1e+20,", "c7: 2.5e-07,",                        # JSON 표기(openui-lang 이 지수를 읽는다) / JSON notation
                     'c8: "00123"',                                       # 앞자리 0 코드는 글자 그대로 / codes stay text
                     "c9: 1234.5,", "c9: 99.9,", "c10: 1234}", "c10: -5}"):   # 숫자 글자 열 → 숫자 / numeric text → numbers
            self.assertIn(part, d1)
        for bad in ("NaN", "Infinity"):
            self.assertNotIn(bad, b["text"])
        self.assertIn('c2: {sum: 7, avg: 7, min: 7, max: 7, first: null, last: 7, change: null, chg: ""}', s)
        self.assertIn("c9: {sum: 1334.4, avg: 667.2,", s)
        self.assertIn("c10: {sum: 1229, avg: 614.5,", s)
        for key in ("c1:", "c3:", "c4:", "c5:", "c8:"):
            self.assertNotIn(key, s)
        # 서버 문장의 글은 평가기(JSON 문자열 규칙)로 원래 값이 된다 / the evaluator reads the strings back exactly
        self.assertEqual(openui.plain_text(b["text"] + "\nroot = Card([t])\nt = TextContent(d1[0].c1)"), tricky)

    def test_dict_rows_missing_cells_and_extra_columns(self):
        b = self.block({"s1": data_result(rows=[{"월": "1월", "매출": 10}, {"월": "2월"}], columns=["월", "매출"])})
        self.assertTrue(b["text"].startswith('d1 = [{c1: "1월", c2: 10}, {c1: "2월", c2: null}]'))
        b = self.block({"s1": data_result(rows=[["a", 1, "덤"], ["b"]], columns=["x", "y"])})
        self.assertTrue(b["text"].startswith('d1 = [{c1: "a", c2: 1, c3: "덤"}, {c1: "b", c2: null, c3: null}]'))
        self.assertIn("c3 = c3(문자, 빈 값 1개)", b["legend"])

    def test_datasets_follow_the_table_cards(self):
        r1 = data_result(rows=[["1월", 1]], tables=("pos_sales", "dept_budget"),
                         extra=[{"columns": ["부서", "예산"], "rows": [["영업", 10], ["개발", 20]],
                                 "sql": "SELECT dept AS 부서, budget AS 예산 FROM dept_budget"},
                                {"columns": ["x"], "rows": None, "sql": "SELECT 1"}])
        r2 = data_result(rows=[["a", 2]], columns=("이름", "수"))
        results = {"s1": r1, "s2": r2}
        b = self.block(results)
        self.assertEqual(b["names"], ["d1", "d1top", "d1sum", "d2", "d2top", "d2sum", "d3", "d3top", "d3sum"])
        self.assertEqual(openui.dataset_names(results), {"s1": [(None, "d1"), (0, "d2")], "s2": [(None, "d3")]})
        self.assertEqual([len(c["rows"]) for c in answers._collect_cards(results)], [1, 2, 1])   # d{n} = n 번째 표 카드
        self.assertIn('d2 = [{c1: "영업", c2: 10}, {c1: "개발", c2: 20}]', b["text"])
        self.assertEqual(b["data"], 3)

    def test_empty_result(self):
        b = self.block({"s1": data_result(rows=[])})
        self.assertEqual(b["text"], "d1 = []\nd1top = d1\nd1sum = {}")
        self.assertIn("결과 0행(d1 · d1top 은 빈 목록)", b["legend"])
        self.assertIn("d1sum = {} (숫자 열 없음)", b["legend"])
        self.assertNotIn("미리보기", b["legend"])

    def test_groupware_lists(self):
        b = self.block({"groupware": gw_result()})
        self.assertEqual(b["text"], 'gw1 = [{left: "반도체 수출 3개월 연속 증가", right: "경제"}, {left: "AI 도입률 60% 돌파", right: "IT"}]')
        self.assertEqual((b["names"], b["data"], b["lists"], b["groupware"]), (["gw1"], 0, 1, True))
        self.assertEqual(openui.data_rules(b), openui.GW_RULES + openui.ASK_RULE)
        # left · right 는 늘 글자(없음 → "", 숫자 → 글자) / left and right are always strings
        nb = self.block({"groupware": gw_result(rows=[(3, None), ("회의", 0), ("x", 2.5), ("y", float("nan"))])})
        self.assertEqual(nb["text"], 'gw1 = [{left: "3", right: ""}, {left: "회의", right: "0"}, {left: "x", right: "2.5"}, '
                                     '{left: "y", right: ""}]')
        # 못 찾은 결과 · 행 없는 결과(능력 조회) · 제목 없는 행은 문장이 없고, 범례가 gw1 이 없다고 분명히 적는다(없는 gw1 참조 = 빈 목록)
        # No statement for these, and the legend says plainly that there is no gw1 (a reference to a missing gw1 = an empty list)
        for res in (gw_result(status="not_found"), gw_result(rows=()), gw_result(rows=[("", "내용만"), (None, "x")])):
            nb = self.block({"groupware": res})
            self.assertEqual((nb["text"], nb["names"], nb["groupware"]), ("", [], True))
            self.assertEqual(openui.data_rules(nb), openui.GW_RULES + openui.ASK_RULE)
            self.assertTrue(nb["legend"].startswith("## 데이터 문장\n이번 답에는 시스템이 정의한 데이터 문장(d1 · gw1 …)이 없다."))
            self.assertIn("gw1 을 참조하지 말고", nb["legend"])
            self.assertNotIn("—", nb["legend"])
        mixed = self.block({"s1": data_result(), "groupware": gw_result(rows=())})
        self.assertEqual(mixed["names"], ["d1", "d1top", "d1sum"])
        self.assertIn("d1: 데이터 분석 결과", mixed["legend"])
        self.assertTrue(mixed["legend"].endswith("EntityList · ListBlock 으로 옮겨 정리한다."))
        both_legend = self.block({"s1": data_result(), "groupware": gw_result()})["legend"]
        self.assertIn("gw1: ", both_legend)
        self.assertNotIn("gw1 을 참조하지 말고", both_legend)

    def test_one_gw_list_per_read_key_and_the_older_flat_shape(self):
        news = {"key": "news", "title": "오늘의 뉴스", "left": "항목", "right": "내용", "rows": [{"t": "뉴스", "s": "IT"}]}
        results = {"groupware": gw_result(items=(GW_MAIL, GW_NEWS), lists=[MAIL_LIST, news])}
        b = openui.data_statements(results, openui.numbered_sources(results))
        self.assertEqual(b["text"].split("\n"), [
            'gw1 = [{left: "3분기 예산안 검토 요청", right: "김지민 · 오늘 10:12 · 안 읽음"}, {left: "주간 보고", right: "박서준 · 어제"}]',
            'gw2 = [{left: "뉴스", right: "IT"}]'])
        self.assertEqual((b["names"], b["lists"]), (["gw1", "gw2"], 2))
        # 목록마다 자기 키의 출처 번호와 이름 · 칸 설명 / each list names itself with its own key's source number and cells
        self.assertIn("gw1: [1] Outlook 메일 · 안 읽은 메일 · 2행, left = 제목, right = 보낸 사람 · 시각 · 안 읽음 표시", b["legend"])
        self.assertIn("gw2: [2] 오늘의 뉴스 · 1행, left = 항목, right = 내용", b["legend"])
        # 옛 평평한 모양([{t, s}], 실행 스냅숏에 남을 수 있다)은 목록 하나 · 제목과 출처는 위젯 항목 / the older flat shape: one list
        flat = {"groupware": gw_result(lists=[{"t": "a", "s": "b"}, {"t": "", "s": "빈 제목"}])}
        fb = openui.data_statements(flat, [{"n": 1, "kind": "groupware", "key": "news", "title": "오늘의 뉴스"}])
        self.assertEqual(fb["text"], 'gw1 = [{left: "a", right: "b"}]')
        self.assertIn("gw1: [1] 오늘의 뉴스 · 1행, left = 항목, right = 내용", fb["legend"])
        both = self.block({"s1": data_result(), "groupware": gw_result()})
        self.assertEqual(both["names"], ["d1", "d1top", "d1sum", "gw1"])
        self.assertEqual(openui.data_rules(both), openui.DATA_RULES + openui.GW_RULES + openui.ASK_RULE)
        self.assertEqual(openui.data_rules(self.block({"s1": data_result()})), openui.DATA_RULES + openui.ASK_RULE)
        self.assertEqual(openui.data_rules(self.block({"knowledge": kn_result()})), "")
        self.assertEqual(openui.data_rules(None), "")


class DataSourceTests(unittest.TestCase):
    """번호 출처 확장(계약 9.3절): 지식 → 로컬 → 데이터 → 그룹웨어 → 웹 / numbered sources in phase 2"""

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("app.catalog.kn_locate", return_value=KN_PATH))
        self.stack.enter_context(patch("app.catalog.data_locate", side_effect=data_locate))

    def test_order_urls_and_names(self):
        cal = {"title": "오늘 일정", "path": ["그룹웨어", "캘린더"], "kind": "gw", "key": "calendar.info.today", "ns": "calendar"}
        bi = {"agent": "data", "status": "dashboard", "text": "대시보드",
              "extras": {"title": "분기 판매", "thumb_url": "/static/bi_thumbs/q.png", "file": "분기 판매.pbix"}}
        results = {"knowledge": kn_result(), "local:kl_demo_hq": local_result(),
                   "s1": data_result(tables=("pos_sales", "dept_budget")),
                   "s2": data_result(tables=("pos_sales", "unknown_t")),          # 같은 표는 한 번 · 위치 없음 / dedupe, no location
                   "bi": bi,
                   "groupware": gw_result(items=(GW_NEWS, cal)),
                   "groupware:2": gw_result(items=({"title": "못 찾음", "path": ["그룹웨어"], "key": "x"},), status="not_found")}
        web = [{"title": "w.com", "url": "https://w.com/a"}]
        out = openui.numbered_sources(results, web)
        self.assertEqual([s["kind"] for s in out],
                         ["knowledge", "local", "data", "data", "data", "data", "groupware", "groupware", "web"])
        self.assertEqual([s["n"] for s in out], list(range(1, 10)))
        self.assertEqual([(s["title"], s["sourceName"], s["url"]) for s in out[2:6]], [
            ("월별 매출", "데이터 분석 › 영업 › DB", "ai365://data/pos_sales?ws=ws_sales"),
            ("부서 예산", "데이터 분석 › 재무 › CSV", "ai365://data/dept_budget?ws=ws_fin"),
            ("unknown_t", "데이터 분석", "ai365://data/unknown_t"),
            ("분기 판매", "데이터 분석 › 영업 › BI", f"ai365://data/bi/{quote('분기 판매.pbix', safe='')}?ws=ws_sales")])
        # 리소스 블록(sources.data.items)과 같은 순서 · 같은 자원 / the same order and resources as the resource block
        items = answers._build_sources(results)["data"]["items"]
        self.assertEqual([i.get("table") or i.get("file") for i in items], ["pos_sales", "dept_budget", "unknown_t", "분기 판매.pbix"])
        self.assertEqual([(s["title"], s["sourceName"], s["url"]) for s in out[6:8]],
                         [("오늘의 뉴스", "그룹웨어 › 위젯", ""), ("오늘 일정", "그룹웨어 › 캘린더", "")])
        stmts = openui.source_statements(out).split("\n")
        self.assertEqual(stmts[2], 'src3 = {title: "월별 매출", sourceName: "데이터 분석 › 영업 › DB", url: "ai365://data/pos_sales?ws=ws_sales"}')
        self.assertEqual(stmts[6], 'src7 = {title: "오늘의 뉴스", sourceName: "그룹웨어 › 위젯"}')   # url 없음 / no url
        self.assertEqual(openui.web_index_map(out, web), {1: 9})                                  # 웹은 사내 뒤 / web last
        self.assertEqual(out[8]["url"], "https://w.com/a")


class FinalizeDataTests(unittest.TestCase):
    """finalize 의 서버 문장 재정의 제거 · 숫자 리터럴 점검(계약 9.2 · 9.4절) / redefinition removal and the literal check"""

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("app.catalog.data_locate", side_effect=data_locate))
        self.results = {"s1": data_result(rows=MONTHS12), "groupware": gw_result()}
        self.numbered = openui.numbered_sources(self.results)
        self.block = openui.data_statements(self.results, self.numbered)

    def test_server_names_are_dropped_and_the_prefix_comes_first(self):
        model = ["root = Card([tb, own, gl], [src1, src2])",
                 'd1 = [{c1: "가짜", c2: 1}]', 'd1top = [{c1: "가짜", c2: 2}]', "d1sum = {c2: {sum: 999}}",
                 'gw1 = [{left: "가짜", right: "x"}]', 'src1 = {title: "가짜 출처", sourceName: "x"}',
                 'd2 = @Sort(d1, "c2", "desc")',          # 서버가 정의하지 않은 이름 = 모델 문장(둔다) / not a server name: kept
                 'tb = Table([Col("월", d1top.c1), Col("매출액", d1top.c2, "number")])',
                 'own = Table([Col("높은 달", d2.c1)])',
                 'gl = EntityList(gw1)']
        raw = "```openui\n" + "\n".join(model) + "\n```"
        with self.assertLogs("ai365.openui", level="INFO") as logs:
            program, report = openui.finalize(raw, "program", self.numbered, self.block)
        self.assertEqual(program, openui.statement_head(self.numbered, self.block) + "\n" + "\n".join([model[0]] + model[6:]))
        self.assertEqual([line.split(" = ", 1)[0] for line in program.split("\n")[:7]],
                         ["d1", "d1top", "d1sum", "gw1", "src1", "src2", "root"])
        self.assertTrue(program.startswith('d1 = [{c1: "1월", c2: 105}'))
        self.assertNotIn("가짜", program)
        self.assertEqual(report, {"has_root": True, "fenced": True, "fallback": False, "literals": 0})
        self.assertIn("d1, d1top, d1sum, gw1, src1", "\n".join(logs.output))     # 지운 이름 / the dropped names
        plain = openui.plain_text(program).split("\n")
        self.assertEqual(plain[:3], ["월 | 매출액", "1월 | 105", "2월 | 110"])
        self.assertIn("10월 | 150", plain)
        self.assertNotIn("11월 | 155", plain)                                       # d1top = 앞 10행 / the first 10 rows
        self.assertEqual(plain[plain.index("높은 달") + 1], "12월")                   # 모델의 d2 = 정렬 / the model's sorted d2
        self.assertIn("반도체 수출 3개월 연속 증가: 경제", plain)

    def test_model_names_survive_without_server_statements(self):
        raw = "\n".join(['root = Card([d1, d2])', 'd1 = ItineraryDay("1일차", [s1])',
                         's1 = ItineraryStop("경복궁", "10:00", "고궁 산책")', 'd2 = ItineraryDay("2일차", [])'])
        program, report = openui.finalize(raw, "program", [])
        self.assertEqual((program, report), (raw, {"has_root": True, "fenced": False, "fallback": False}))
        self.assertEqual(openui.plain_text(program).split("\n"), ["1일차", "10:00 경복궁: 고궁 산책", "2일차"])

    def test_literal_count(self):
        body = "\n".join([
            'root = Card([st, ch, ch2, tb, t, pb, lst])',
            'st = StatStrip([Stat("1,234억", "매출", "+12.5%"), Stat(@FormatNumber(d1sum.c2.sum), "합계", d1sum.c2.chg), Stat(d1[0].c2, "첫 달")])',
            'ch = BarChart(["1월", "2월"], [Series("매출", vals)], "grouped", "월", "억", 320)',
            'ch2 = LineChart(["a"], [Series("x", vals)])',
            'vals = [120, 135]',
            'tb = Table([Col("값", [1.5, "2,000원", "Q1", "2024년"]), Col("반올림", [@Round(d1sum.c2.avg, 1)])])',
            't = TextContent("매출은 1,234억입니다")',
            'pb = Table([Col("진행", [ProgressBar(30, 100, "30%")])])',
            'lst = ListBlock([ListItem("3건", "기타")])'])
        # Stat 2 + vals 2(한 번만) + Col 2 + ProgressBar 2(값 · 이름표, 최댓값 제외) = 8. 차트 높이 · @Round 자릿수 · 첨자 · 날짜 이름표 ·
        # TextContent · ListItem 은 세지 않는다 / chart height, @Round places, indexes, date labels, prose and list items do not count
        self.assertEqual(openui._literal_count(body), 8)
        self.assertEqual(openui._literal_count('root = Card([c])\nc = BarChart(d1.c1, [Series("매출", d1.c2)])'), 0)
        self.assertEqual(openui._literal_count(""), 0)
        with self.assertLogs("ai365.openui", level="INFO") as logs:
            report = openui.finalize(body, "program", [], self.block)[1]
        self.assertEqual(report["literals"], 8)
        self.assertIn("숫자 리터럴 8개", "\n".join(logs.output))
        self.assertNotIn("literals", openui.finalize(body, "program", [])[1])   # 데이터 문장이 없으면 세지 않는다 / no block, no count

    def test_interrupted_partial_resolves_data_references(self):
        raw = 'root = Card([tb])\ntb = Table([Col("월", d1top.c1), Col("매출액", d1top.c2)])\nt = TextContent("부분'
        with self.assertLogs("ai365.openui", level="INFO"):
            program, report, plain = openui._finalize(raw, "program", self.numbered, interrupted=True, block=self.block)
        self.assertTrue(plain.startswith("월 | 매출액\n1월 | 105\n2월 | 110"))
        self.assertTrue(plain.endswith(_INTERRUPT_NOTE))
        self.assertEqual(program, openui.wrap_text(plain, sources=self.numbered))
        self.assertEqual(report, {"has_root": True, "fenced": False, "fallback": True, "literals": 0})


class LegendAndRulesTests(unittest.TestCase):
    """근거 블록의 "## 데이터 문장" 범례와 DATA_RULES · GW_RULES · ASK_RULE(계약 9.4절) / the legend and the rules"""

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("app.catalog.kn_locate", return_value=KN_PATH))
        self.stack.enter_context(patch("app.catalog.data_locate", side_effect=data_locate))

    def test_legend_content(self):
        rows = [[f"{i}일", i * 10] for i in range(1, 26)]
        results = {"knowledge": kn_result(), "s1": data_result(rows=rows, columns=("일자", "매출액")), "groupware": gw_result()}
        legend = openui.data_statements(results, openui.numbered_sources(results))["legend"]
        self.assertEqual(legend.split("\n")[0], "## 데이터 문장(시스템이 이미 정의함, 다시 정의 금지)")
        for part in ("여기 적힌 이름 · 열 키 · d{n}sum 키만 참조한다",
                     "d1: [2] 월별 매출 · 전체 25행, d1 = 25행 전부, d1top = 앞 10행",
                     "SQL: " + SQL,
                     "열: c1 = 일자(문자), c2 = 매출액(숫자)",
                     'd1sum = {c2: {sum: 3250, avg: 130, min: 10, max: 250, first: 10, last: 250, change: 2400, chg: "+2400.0%"}} '
                     "(전체 25행 기준, 빈 값 제외)",
                     "미리보기(앞 20행):", '{c1: "20일", c2: 200}',
                     "gw1: [3] 오늘의 뉴스 · 2행, left = 항목, right = 내용",
                     '{left: "AI 도입률 60% 돌파", right: "IT"}',
                     "d{n}top 은 늘 있다(앞 10행)", "chg(change 의 부호 붙은 글자", "@Avg · @Min · @Max 는 빈 값을 0 으로 센다",
                     "gw{m} 은 조회한 목록마다 하나다", "행은 {left, right} 객체이고 둘 다 글자다"):
            self.assertIn(part, legend)
        self.assertNotIn('{c1: "21일", c2: 210}', legend)
        self.assertNotIn("—", legend)

    def test_evidence_order_and_compose(self):
        legend = "## 데이터 문장(시스템이 이미 정의함, 다시 정의 금지)\nd1: …"
        numbered = [{"n": 1, "title": "월별 매출", "sourceName": "데이터 분석 › 영업 › DB",
                     "url": "ai365://data/pos_sales?ws=ws_sales", "kind": "data", "table": "pos_sales"}]
        body = openui.compose_messages(CTX, numbered, ["[에이전트 실행 결과]\n[]"], legend=legend)[-1]["content"]
        self.assertLess(body.index("## 번호 출처"), body.index("## 데이터 문장"))
        self.assertLess(body.index("## 데이터 문장"), body.index("[에이전트 실행 결과]"))
        self.assertLess(body.index("[에이전트 실행 결과]"), body.index("## 사용자 질문"))
        self.assertIn("url: ai365://data/pos_sales?ws=ws_sales", body)
        self.assertNotIn("## 데이터 문장", openui.evidence_block(numbered, ["x"]))

    def test_rules_carry_the_contract_examples(self):
        for part in ('BarChart(d1.c1, [Series("매출액", d1.c2)])', 'Stat(@FormatNumber(d1sum.c2.sum) + "억", "1분기 매출")',
                     "d{n}top 은 늘 있다", "차트에 앞 10행만 그릴 때 쓴다", "d{n}sum", "d1sum.c2.chg",
                     "@Sum · @Avg · @Min · @Max 는 빈 값(null)을 0 으로", "@FormatNumber(값) 이나 @Round(값, 자릿수)", "700.7499999999999",
                     "범례에 적힌 이름 · 열 키", "@First(@Sort(d1, \"c2\", \"desc\")).c1", "직접 옮겨 적지 않는다",
                     # 데이터 답은 Table 을 쓰지 않는다(아래 표 카드와 겹친다, 2026-10-27 화면 검토) / no Table (the table card below has it)
                     "전체 표는 답 아래 표 카드(리포트 에이전트 진입점)에 이미 있다. Table 을 쓰지 않는다. 요약 TextContent · StatStrip · "
                     "차트로 답하고, 꼭 짚을 행은 글이나 Callout 으로 말한다."):
            self.assertIn(part, openui.DATA_RULES)
        for gone in ("Col(", "Table 은", "ProgressBar"):            # 표를 권하는 말은 없다 / nothing suggests a table
            self.assertNotIn(gone, openui.DATA_RULES)
        # 질문 글이 대상을 담는다(섬은 @ToAssistant 의 두 번째 인자를 버린다) / the question text carries its target
        for part in ("EntityList(gw1)", 'Table([Col("제목", gw1.left), Col("내용", gw1.right)])',
                     '@Each(gw1, "g", ListItem(g.left, g.right))', "gw1[0].left",
                     '@ToAssistant("‘" + gw1[0].left + "’ 메일에 답장 초안 써줘")', "gw1 이 없으면 질문 글에 메일 제목",
                     "FollowUpBlock", "승인 카드", "발송하지 않고"):
            self.assertIn(part, openui.GW_RULES)
        self.assertIn("두 번째 인자는 전달되지 않는다", openui.ASK_RULE)
        self.assertNotIn("gw1", openui.ASK_RULE)    # 데이터만 있는 답에도 붙으므로 gw 이름을 쓰지 않는다 / also added to data-only answers
        for rules in (openui.DATA_RULES, openui.GW_RULES, openui.ASK_RULE):
            self.assertNotIn("—", rules)


class PlainDataTests(unittest.TestCase):
    """데이터 문장을 참조하는 프로그램의 평문(내장 함수 · 연산 포함) / plain text of data-bound programs"""
    D1 = 'd1 = [{c1: "1월", c2: 120}, {c1: "2월", c2: 135}, {c1: "3월", c2: null}, {c1: "4월", c2: 150.5}]'
    D1SUM = 'd1sum = {c2: {sum: 405.5, avg: 135.17, min: 120, max: 150.5, first: 120, last: 150.5, change: 25.4, chg: "+25.4%"}}'
    D2 = 'd2 = [{c1: "가", c2: 3}, {c1: "나", c2: 10}, {c1: "다", c2: 1}]'
    GW1 = 'gw1 = [{left: "주간 회의", right: "10:00 · 3층"}, {left: "고객 미팅", right: "14:00"}]'

    def plain(self, *lines) -> list[str]:
        return openui.plain_text("\n".join([self.D1, "d1top = d1", self.D1SUM, self.D2, self.GW1, *lines])).split("\n")

    def test_tables_charts_and_stats_over_data_statements(self):
        self.assertEqual(self.plain('root = Card([tb, ch, st, s2])',
                                    'tb = Table([Col("월", d1top.c1), Col("매출", d1top.c2, "number")])',
                                    'ch = BarChart(d1.c1, [Series("매출액", d1.c2)])',
                                    'st = StatStrip([Stat(@FormatNumber(d1sum.c2.sum) + "억", "1분기 매출", d1sum.c2.chg)])',
                                    's2 = TextContent("합계는 **" + @FormatNumber(d1sum.c2.sum) + "억 원**이고 변화율은 "'
                                    ' + @FormatNumber(d1sum.c2.change, 1) + "%입니다 [1].")'),
                         ["월 | 매출", "1월 | 120", "2월 | 135", "3월 |", "4월 | 150.5",
                          "매출액: 1월 120, 2월 135, 3월, 4월 150.5", "1분기 매출: 405.5억 (+25.4%)",
                          "합계는 **405.5억 원**이고 변화율은 25.4%입니다 [1]."])

    def test_builtin_functions(self):
        self.assertEqual(self.plain(
            'root = Card([a, b, c, d, e, f, g, h])',
            # @Sum · @Avg · @Min · @Max 는 빈 값을 뺀다(조정자 지시) / empty values are left out (coordinator instruction)
            'a = TextContent("합 " + @Sum(d1.c2) + " · 평균 " + @Round(@Avg(d1.c2), 1) + " · 개수 " + @Count(d1))',
            'b = TextContent("처음 " + @First(d1).c1 + " · 끝 " + @Last(d1.c1) + " · 최대 " + @Max(d1.c2) + " · 최소 " + @Min(d1.c2))',
            'c = TextContent(@Abs(-3) + "/" + @Floor(2.7) + "/" + @Ceil(2.1) + "/" + @Round(2.5) + "/" + @Round(-2.5))',
            'd = TextContent(@ToNumber("1,200") + 1 + " · " + @Clamp(150, 0, 100) + " · " + @Length("가나다") + " · " + '
            '@Substring("abcdef", 1, -1))',
            'e = Table([Col("이름", @Sort(d2, "c2", "desc").c1), Col("수", @Sort(d2, "c2", "desc").c2)])',
            'f = TextContent("가나다순 첫 " + @First(@Sort(d2, "c1")).c1 + " · 2 초과 " + @Count(@Filter(d2, "c2", ">", 2)) + '
            '" · 다 " + @Count(@Filter(d2, "c1", "==", "다")))',
            'g = TextContent("10시 " + @Count(@Filter(gw1, "right", "contains", "10:00")) + " · 최고 " + '
            '@First(@Sort(d2, "c2", "desc")).c1 + " · 첨자 " + @Sort(d2, "c2")[0].c1)',
            'h = TextContent("첫 회의 " + gw1[0].left + " · 건수 " + @Count(gw1))'),
            ["합 405.5 · 평균 135.2 · 개수 4",
             "처음 1월 · 끝 4월 · 최대 150.5 · 최소 120",
             "3/2/3/3/-2",
             "1201 · 100 · 3 · bcde",
             "이름 | 수", "나 | 10", "가 | 3", "다 | 1",
             "가나다순 첫 가 · 2 초과 2 · 다 1",
             "10시 1 · 최고 나 · 첨자 다",
             "첫 회의 주간 회의 · 건수 2"])

    def test_format_number_and_arithmetic(self):
        self.assertEqual(self.plain(
            'root = Card([a, b, c, d, e])',
            'a = TextContent(@FormatNumber(1234567.891) + " | " + @FormatNumber(1234.5, 2) + " | " + @FormatNumber(1234.5, 0) + '
            '" | " + @FormatNumber(1.005) + " | " + @FormatNumber(-0.125))',      # JS toLocaleString("en-US") 과 같다 / as JS
            'b = TextContent("값: " + @FormatNumber("12"))',                        # 숫자가 아니면 null(뺀다) / null for a non-number
            'c = TextContent(@Round(d1sum.c2.sum / 100, 1) + "백 · " + (d1sum.c2.max - d1sum.c2.min) + " · " + d1sum.c2.sum * 2 + '
            '" · " + 7 % 3)',
            'd = TextContent("나눔 " + 1 / 0)',                                    # 0 으로 나눔은 뺀다 / division by zero is dropped
            'e = TextContent("계산 " + @Calc("1+2"))'),                            # @Calc 는 계산하지 않는다 / not evaluated
            ["1,234,567.89 | 1,234.50 | 1,235 | 1.01 | -0.13", "값:", "4.1백 · 30.5 · 811 · 1", "나눔", "계산"])

    def test_each_scope_entities_and_orphans(self):
        self.assertEqual(self.plain('root = Card([l, e, t, x])',
                                    'label = "회의: "',
                                    'l = ListBlock(@Each(gw1, "g", ListItem(g.left, g.right)))',
                                    'e = EntityList(gw1)',
                                    't = Buttons(@Each(gw1, "g", Button(label + g.left, @ToAssistant("자세히: " + g.left))))',
                                    'x = TextContent("밖 " + g)'),       # 반복 변수는 틀 밖에서 보이지 않는다 / the loop variable never leaks
                         ["- 주간 회의: 10:00 · 3층", "- 고객 미팅: 14:00", "주간 회의: 10:00 · 3층", "고객 미팅: 14:00",
                          "회의: 주간 회의", "회의: 고객 미팅", "밖"])
        # root 가 없으면 화면에 붙지 않은 서버 데이터 문장은 쏟지 않는다(모델의 d9 컴포넌트는 그대로)
        # With no root, unattached server data is not dumped (the model's own d9 component still is)
        self.assertEqual(openui.plain_text(self.D1 + "\n" + self.GW1 + '\nt = TextContent("본문")\nd9 = TextContent("모델 문장")'),
                         "본문\n모델 문장")


class WiredDataTests(_Wired):
    """취합 끝단(2단계): 데이터만 · 그룹웨어만 · 섞임 · 자동 모드 웹 보완 번호 / end-to-end aggregation in phase 2"""

    # 규칙대로 쓴 데이터 답(Table 없음: 요약 · StatStrip · 차트 · 꼭 짚을 행은 Callout) / a data answer written by the rules
    DATA_MODEL = ['root = Card([h, st, ch, note, t, fu], [src1])\n',
                  'h = CardHeader("1분기 월별 매출")\n',
                  'st = StatStrip([Stat(@FormatNumber(d1sum.c2.sum) + "억", "누적 매출", d1sum.c2.chg)])\n',
                  'ch = LineChart(d1.c1, [Series("매출액", d1.c2)])\n',
                  'note = Callout("info", "가장 높은 달", @First(@Sort(d1, "c2", "desc")).c1 + " · " + @FormatNumber(d1sum.c2.max) + "억")\n',
                  't = TextContent("12월 매출이 가장 높았습니다 [1].")\n',
                  'fu = FollowUpBlock([FollowUpItem("지점별로 보여줘"), FollowUpItem("작년과 비교해줘")])']

    @staticmethod
    def compose(fake) -> tuple[str, str]:
        return fake.calls[0]["system"], fake.calls[0]["messages"][-1]["content"]

    @staticmethod
    def results_json(last: str) -> str:
        return last[last.index("[에이전트 실행 결과]"):last.index("## 사용자 질문")]

    async def test_data_only_answer_streams_data_statements_first(self):
        fake = self.use_stream(self.DATA_MODEL)
        results = {"s1": data_result(rows=MONTHS12)}
        ev = await collect(answers._aggregate_answer(self.chat["id"], "사내", CTX, results, fmt="openui"))
        self.assertEqual(ev[0], {"type": "answer_head", "source": "사내", "format": "openui", "ui_mode": "program"})
        numbered = openui.numbered_sources(results)
        tokens = [e["text"] for e in ev if e["type"] == "token"]
        self.assertEqual(tokens[0], openui.statement_head(numbered, openui.data_statements(results, numbered)) + "\n")
        head = tokens[0].split("\n")
        self.assertEqual([line.split(" = ", 1)[0] for line in head[:4]], ["d1", "d1top", "d1sum", "src1"])
        self.assertTrue(head[0].startswith('d1 = [{c1: "1월", c2: 105}, {c1: "2월", c2: 110}'))
        self.assertEqual(head[2], 'd1sum = {c2: {sum: 1590, avg: 132.5, min: 105, max: 160, first: 105, last: 160, change: 52.4, '
                                  'chg: "+52.4%"}}')
        self.assertEqual(head[3], 'src1 = {title: "월별 매출", sourceName: "데이터 분석 › 영업 › DB", url: "ai365://data/pos_sales?ws=ws_sales"}')
        done = ev[-1]
        program = done["program"]
        self.assertEqual(program, "".join(tokens))
        self.assertLess(program.index("d1sum = "), program.index("src1 = "))
        self.assertLess(program.index("src1 = "), program.index("root = "))
        self.assertEqual(done["ui_report"], {"has_root": True, "fenced": False, "fallback": False, "literals": 0})
        plain = done["plain"].split("\n")
        self.assertEqual(plain[:2], ["1분기 월별 매출", "누적 매출: 1,590억 (+52.4%)"])
        self.assertTrue(plain[2].startswith("매출액: 1월 105, 2월 110, 3월 115"))
        self.assertEqual(plain[3:], ["가장 높은 달", "12월 · 160억", "12월 매출이 가장 높았습니다 [1]."])
        self.assertNotIn("Table(", program)                                      # 표는 아래 표 카드만 / the table card alone
        self.assertEqual(done["cards"][0]["rows"], MONTHS12)                    # 표 카드는 종전대로 전체 행 / the table card keeps all rows
        self.assertEqual(done["sources"]["data"]["items"][0]["table"], "pos_sales")
        # 작성 호출: 데이터 규칙 · 범례, 취합 블록의 행 목록은 데이터 문장 안내로 / rules, legend, row lists as pointers
        system, last = self.compose(fake)
        self.assertIn(openui.DATA_RULES, system)
        self.assertIn(openui.ASK_RULE.strip(), system)
        self.assertNotIn(openui.GW_RULES, system)
        self.assertIn("## 데이터 문장(시스템이 이미 정의함, 다시 정의 금지)", last)
        self.assertIn("d1: [1] 월별 매출 · 전체 12행, d1 = 12행 전부, d1top = 앞 10행", last)
        rj = self.results_json(last)
        self.assertIn("데이터 문장 d1 참조(12행, [데이터 문장] 범례에 열 · 미리보기)", rj)
        self.assertNotIn('"12월"', rj)
        self.assertNotIn("total_rows", rj)
        # 저장: content = 프로그램(데이터 문장 포함), meta 에는 데이터 문장 · 그룹웨어 행이 없고 행은 표 카드에만(종전)
        # Saved: content = the program (statements included); meta has no statements or gw rows, rows only in the cards (as before)
        row = self.saved()
        self.assertEqual(row["content"], program)
        meta = row["meta"]
        self.assertEqual(set(meta), {"source", "format", "ui_mode", "plain", "steps", "cards", "sources"})
        rest = json.dumps({k: v for k, v in meta.items() if k != "cards"}, ensure_ascii=False)
        self.assertNotIn('"rows"', rest)
        self.assertNotIn("d1 = ", rest)
        self.assertNotIn("gw_rows", json.dumps(meta, ensure_ascii=False))

    async def test_groupware_only_answer(self):
        model = ['root = Card([h, gl, b, fu], [src1])\n', 'h = CardHeader("오늘의 뉴스")\n', 'gl = EntityList(gw1)\n',
                 'b = Buttons([Button("첫 기사 요약", @ToAssistant("‘" + gw1[0].left + "’ 기사를 요약해줘"))])\n',
                 'fu = FollowUpBlock([FollowUpItem("IT 소식만 보여줘")])']
        fake = self.use_stream(model)
        ev = await collect(answers._aggregate_answer(self.chat["id"], "사내", CTX, {"groupware": gw_result()}, fmt="openui"))
        tokens = [e["text"] for e in ev if e["type"] == "token"]
        self.assertEqual(tokens[0], "\n".join([
            'gw1 = [{left: "반도체 수출 3개월 연속 증가", right: "경제"}, {left: "AI 도입률 60% 돌파", right: "IT"}]',
            'src1 = {title: "오늘의 뉴스", sourceName: "그룹웨어 › 위젯"}']) + "\n")
        done = ev[-1]
        self.assertEqual(done["format"], "openui")
        self.assertEqual(done["ui_report"], {"has_root": True, "fenced": False, "fallback": False, "literals": 0})
        self.assertEqual(done["plain"].split("\n"),
                         ["오늘의 뉴스", "반도체 수출 3개월 연속 증가: 경제", "AI 도입률 60% 돌파: IT", "첫 기사 요약"])
        self.assertEqual(done["sources"]["groupware"]["items"], [GW_NEWS])
        system, last = self.compose(fake)
        self.assertIn(openui.GW_RULES, system)
        self.assertIn(openui.ASK_RULE.strip(), system)
        self.assertNotIn(openui.DATA_RULES, system)
        self.assertIn("gw1: [1] 오늘의 뉴스 · 2행", last)
        rj = self.results_json(last)
        self.assertNotIn("gw_rows", rj)                                          # 같은 항목은 text 줄로만 / only as text lines
        self.assertIn("- 반도체 수출 3개월 연속 증가 — 경제", rj)
        meta = self.saved()["meta"]
        dumped = json.dumps(meta, ensure_ascii=False)
        self.assertNotIn("gw_rows", dumped)
        self.assertNotIn('"rows"', dumped)
        self.assertNotIn("cards", meta)

    async def test_mixed_internal_results(self):
        model = ['root = Card([t, st, gl, fu], [src1, src2, src3])\n', 't = TextContent("연차는 15일입니다 [1].")\n',
                 'st = StatStrip([Stat(@FormatNumber(d1sum.c2.sum), "누적 매출")])\n', 'gl = EntityList(gw1)\n',
                 'fu = FollowUpBlock([FollowUpItem("더 알려줘")])']
        fake = self.use_stream(model)
        results = {"knowledge": kn_result(), "s1": data_result(rows=MONTHS12), "groupware": gw_result()}
        ev = await collect(answers._aggregate_answer(self.chat["id"], "사내", CTX, results, fmt="openui"))
        done = ev[-1]
        self.assertEqual([line.split(" = ", 1)[0] for line in done["program"].split("\n")[:8]],
                         ["d1", "d1top", "d1sum", "gw1", "src1", "src2", "src3", "root"])
        self.assertEqual([s["kind"] for s in openui.numbered_sources(results)], ["knowledge", "data", "groupware"])
        self.assertEqual(done["plain"].split("\n"),
                         ["연차는 15일입니다 [1].", "누적 매출: 1,590", "반도체 수출 3개월 연속 증가: 경제", "AI 도입률 60% 돌파: IT"])
        system, last = self.compose(fake)
        self.assertIn(openui.AGGREGATE_RULES, system)
        self.assertIn(openui.DATA_RULES + openui.GW_RULES + openui.ASK_RULE, system)
        for part in ("발췌: 제12조 연차는 1년 근속 시 15일을 부여한다.", "d1: [2] 월별 매출", "gw1: [3] 오늘의 뉴스"):
            self.assertIn(part, last)
        self.assertEqual(done["references"], [{"doc": DOC, "page": 3}])
        self.assertEqual(set(done["sources"]), {"knowledge", "data", "groupware"})

    async def test_unread_mail_question_streams_gw1_first(self):
        # "안 읽은 메일 보여줘": 실제 그룹웨어 에이전트 읽기 경로(툴 콜 · 설정 읽기 · 능력 조회만 대역) → 취합 → done.program 이 gw1 로 시작
        # "안 읽은 메일 보여줘": the real groupware read path (only the tool call, config reads and the lookup are stand-ins) →
        # aggregation → done.program starts with gw1
        from app import smart_actions_api as saa
        from app.agents import groupware as groupware_agent
        calls = {"calls": [{"name": "read_groupware", "args": {"targets": ["mail"]}}]}
        with patch("app.llm.generate_calls", return_value=calls), patch("app.groupware._classify", return_value=None), \
                patch("app.groupware.get_widgets", return_value={}), patch("app.smart_actions.get_config", return_value={}), \
                patch.dict(saa.INFO_DISPATCH, {"mail.info.unread": lambda a: copy.deepcopy(MAILS)}):
            res = groupware_agent._run_sync("안 읽은 메일 보여줘", [])
        model = ['root = Card([h, t, gl, b, fu], [src1])\n', 'h = CardHeader("안 읽은 메일")\n',
                 't = TextContent("안 읽은 메일이 " + @Count(gw1) + "통 있습니다 [1].")\n', 'gl = EntityList(gw1)\n',
                 'b = Buttons([Button("답장 초안", @ToAssistant("‘" + gw1[0].left + "’ 메일에 답장 초안 써줘"))])\n',
                 'fu = FollowUpBlock([FollowUpItem("오늘 일정도 보여줘")])']
        fake = self.use_stream(model)
        results = {"groupware": {**res, "agent": "groupware", "task_id": "groupware", "label": "그룹웨어"}}
        ev = await collect(answers._aggregate_answer(self.chat["id"], "사내", CTX, results, fmt="openui"))
        done = ev[-1]
        lines = done["program"].split("\n")
        self.assertEqual(lines[:3], [
            'gw1 = [{left: "3분기 예산안 검토 요청", right: "김지민 · 오늘 10:12 · 안 읽음"}, {left: "주간 보고", right: "박서준 · 어제"}]',
            'src1 = {title: "안 읽은 메일", sourceName: "그룹웨어 › Outlook 메일"}',
            "root = Card([h, t, gl, b, fu], [src1])"])
        self.assertEqual(done["ui_report"], {"has_root": True, "fenced": False, "fallback": False, "literals": 0})
        self.assertEqual(done["plain"].split("\n"), ["안 읽은 메일", "안 읽은 메일이 2통 있습니다 [1].",
                                                     "3분기 예산안 검토 요청: 김지민 · 오늘 10:12 · 안 읽음", "주간 보고: 박서준 · 어제",
                                                     "답장 초안"])
        self.assertEqual(done["sources"]["groupware"]["items"], [GW_MAIL])
        system, last = self.compose(fake)
        self.assertIn(openui.GW_RULES, system)
        self.assertIn("gw1: [1] Outlook 메일 · 안 읽은 메일 · 2행, left = 제목, right = 보낸 사람 · 시각 · 안 읽음 표시", last)
        self.assertNotIn("gw1 을 참조하지 말고", last)
        self.assertNotIn("gw_rows", self.results_json(last))
        self.assertNotIn("gw_rows", json.dumps(self.saved()["meta"], ensure_ascii=False))

    async def test_auto_supplement_markers_follow_the_data_sources(self):
        text = "오늘 환율은 1,340원이다."
        gmeta = {"text": text, "sources": [{"title": "fx.com", "url": "https://fx.com"}], "supports": [{"end": len(text), "ns": [1]}]}
        fake = self.use_stream(self.DATA_MODEL)
        results = {"k1": kn_result(), "k2": {"agent": "knowledge", "status": "not_found", "text": "", "extras": {},
                                             "fail_reason": "사내 문서에서 관련 근거를 찾지 못했습니다."},
                   "d1": data_result(rows=MONTHS12)}
        with patch("app.llm.generate_grounded_meta", return_value=gmeta), \
                patch.object(answers, "_judge_gap", return_value={"complete": False, "missing": "환율"}):
            ev = await collect(answers._auto_answer(self.chat["id"], "사내", CTX, QUESTION, results, fmt="openui"))
        system, last = self.compose(fake)
        self.assertIn("1,340원이다.[3]", last)          # 지식 [1] · 데이터 [2] 뒤의 웹 = [3] / web after knowledge [1] and data [2]
        self.assertIn("[2] 월별 매출", last)
        self.assertIn("[3] fx.com", last)
        self.assertIn("## 데이터 문장", last)
        self.assertIn(openui.BLEND_RULES.strip(), system)
        self.assertIn(openui.DATA_RULES, system)
        done = ev[-1]
        self.assertEqual((done["format"], done.get("_web_resolved")), ("openui", True))
        self.assertTrue(done["program"].startswith("d1 = ["))
        self.assertIn('src3 = {title: "fx.com", sourceName: "fx.com", url: "https://fx.com"}', done["program"])
        self.assertEqual(self.saved()["meta"]["source"], "사내|웹 보완")


class _GroupwareSeed(unittest.TestCase):
    """그룹웨어 노드 실행 공통 준비: 위젯 · 스마트 실행 설정 읽기와 능력 조회(INFO_DISPATCH)를 대역으로 둔다. app/groupware.py ·
    app/smart_actions.py 는 실 DB 경로를 가져다 쓰므로 실제로 부르지 않는다(테스트 메서드 없음).
    Shared setup for groupware node runs: widget / smart-action config reads and capability lookups (INFO_DISPATCH) are
    stand-ins; app/groupware.py and app/smart_actions.py bind the real DB path, so they are never called (no test methods)."""

    def setUp(self):
        from app import flows, smart_actions_api
        self.flows, self.saa = flows, smart_actions_api
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("app.groupware.get_widgets", return_value={}))
        self.stack.enter_context(patch("app.smart_actions.get_config", return_value={}))
        self.stack.enter_context(patch.dict(smart_actions_api.INFO_DISPATCH, {
            "mail.info.unread": lambda a: copy.deepcopy(MAILS), "calendar.info.today": lambda a: copy.deepcopy(EVENTS),
            "calendar.info.free": lambda a: copy.deepcopy(FREE), "todo.info.overdue": lambda a: copy.deepcopy(TASKS),
            "sharepoint.info.recent": lambda a: copy.deepcopy(FILES)}))

    def run_node(self, keys, **kw):
        return self.flows._run_groupware_node({"resources": list(keys), "args": {}}, "조회", "그룹웨어", **kw)


class GroupwareListRowsTests(_GroupwareSeed):
    """flows._run_groupware_node(want_rows=True) 의 목록 행(조정자 지시 2026-10-27): 능력 조회 · 위젯 키마다 목록 하나, 행은 글자 ·
    최대 30행, 워크플로우 경로(기본 꺼짐)는 그대로 / list rows of _run_groupware_node(want_rows=True); the workflow path unchanged"""

    def test_mail_only(self):
        out = self.run_node(["mail.info.unread"], want_rows=True)
        self.assertEqual(out["row_lists"], [MAIL_LIST])                          # 제목 없는 행은 뺀다 / the untitled row is left out
        self.assertIn("[Outlook 메일 · 안 읽은 메일]\n- 3분기 예산안 검토 요청 — 김지민 · 오늘 10:12 · 안 읽음", out["text"])

    def test_calendar_only(self):
        out = self.run_node(["calendar.info.today"], want_rows=True)
        self.assertEqual(out["row_lists"], [{"key": "calendar.info.today", "title": "Outlook 일정 · 오늘 일정", "left": "제목",
                                             "right": "시각 · 장소", "rows": [{"t": "주간 회의", "s": "오늘 10:00 · 3층 회의실"},
                                                                         {"t": "고객 미팅", "s": "오늘 14:00"}]}])

    def test_free_slots_tasks_and_documents(self):
        out = self.run_node(["calendar.info.free", "todo.info.overdue", "sharepoint.info.recent"], want_rows=True)
        self.assertEqual([(lst["key"], lst["title"], lst["left"], lst["right"], lst["rows"]) for lst in out["row_lists"]], [
            ("calendar.info.free", "Outlook 일정 · 빈 시간 찾기", "빈 시간", "날짜 · 시각 · 길이",
             [{"t": "빈 시간 15:30~17:00", "s": "오늘 15:30 · 90분"}]),
            ("todo.info.overdue", "Microsoft To Do · 기한 지난 할 일", "할 일", "마감 · 기한 지남 표시",
             [{"t": "보고서 제출", "s": "마감 오늘 · 기한 지남"}, {"t": "회의록 정리", "s": "마감 기한 없음"}]),
            ("sharepoint.info.recent", "SharePoint · 최근 문서", "문서", "경로 · 수정 시각", [{"t": "예산안.xlsx", "s": "/재무/2026 · 어제"}])])

    def test_mixed_widget_and_capability(self):
        from app import groupware
        out = self.run_node(["news", "mail.info.unread"], want_rows=True)
        self.assertEqual([(lst["key"], lst["title"], lst["left"], lst["right"], len(lst["rows"])) for lst in out["row_lists"]],
                         [("news", "오늘의 뉴스", "항목", "내용", len(groupware._NEWS)),
                          ("mail.info.unread", MAIL_LIST["title"], "제목", MAIL_LIST["right"], 2)])
        self.assertEqual(out["row_lists"][0]["rows"][0], {"t": groupware._NEWS[0]["title"], "s": groupware._NEWS[0]["tag"]})
        self.assertEqual(len(out["items"]), len(groupware._NEWS))                # 위젯 items 는 종전대로 / widget items as before

    def test_rows_are_capped_at_30(self):
        many = [{"subject": f"메일 {i}", "from": {"name": "가"}, "when": "오늘", "isRead": False} for i in range(40)]
        with patch.dict(self.saa.INFO_DISPATCH, {"mail.info.unread": lambda a: copy.deepcopy(many)}):
            out = self.run_node(["mail.info.unread"], want_rows=True)
        rows = out["row_lists"][0]["rows"]
        self.assertEqual((len(rows), rows[-1]["t"]), (30, "메일 29"))
        self.assertIn("- … 외 35건", out["text"])                               # 글은 종전대로 5줄 + 외 N건 / the text as before
        res = gw_result(items=(GW_MAIL,), lists=out["row_lists"])
        self.assertEqual(openui.data_statements({"groupware": res})["text"].count("{left:"), 30)

    def test_failed_and_disabled_reads_add_no_list(self):
        def boom(_args):
            raise RuntimeError("조회 실패")
        with patch.dict(self.saa.INFO_DISPATCH, {"mail.info.unread": boom}), \
                patch("app.smart_actions.get_config", return_value={"calendar": {"enabled": False}}):
            out = self.run_node(["mail.info.unread", "calendar.info.today", "todo.info.overdue"], want_rows=True)
        self.assertEqual([lst["key"] for lst in out["row_lists"]], ["todo.info.overdue"])
        self.assertIn("[Outlook 메일 · 안 읽은 메일] 조회에 실패했습니다.", out["text"])
        self.assertIn("[Outlook 일정 · 오늘 일정] 도구가 꺼져 있어 실행하지 않았습니다.", out["text"])

    def test_workflow_path_is_unchanged(self):
        # 워크플로우는 위치 인자 3개로 부른다(want_rows 없음): 결과에 키를 더하지 않고, 글 · items · sends · extras 가 켠 실행과 같다
        # Workflows call with three positional arguments (no want_rows): no key is added and text / items / sends / extras equal
        # those of the opted-in run
        keys = ["news", "mail.info.unread", "calendar.info.today", "mail.action.compose"]
        default = self.flows._run_groupware_node({"resources": list(keys), "args": {}}, "조회", "그룹웨어")
        on = self.run_node(keys, want_rows=True)
        self.assertEqual(set(default), {"label", "status", "text", "items", "sends", "extras"})
        self.assertEqual({k: v for k, v in on.items() if k != "row_lists"}, default)
        self.assertEqual(self.run_node(keys, want_rows=False), default)
        self.assertEqual(default["text"].split("\n\n")[1], "\n".join([                  # 종전 _cap_item_lines 형식 / the former format
            "[Outlook 메일 · 안 읽은 메일]", "- 3분기 예산안 검토 요청 — 김지민 · 오늘 10:12 · 안 읽음", "- 주간 보고 — 박서준 · 어제",
            "-  — 제목 없음 · 어제"]))
        self.assertEqual(default["sends"], [{"key": "mail.action.compose", "query": "조회"}])
        self.assertEqual([lst["key"] for lst in on["row_lists"]], ["news", "mail.info.unread", "calendar.info.today"])  # 실행 키 없음


class GroupwareAgentRowsTests(_GroupwareSeed):
    """채팅 그룹웨어 에이전트 읽기 경로: 실제 _run_groupware_node(want_rows) → extras.gw_rows(키마다 목록 하나), 취합 프롬프트 · meta
    에서 빼기 / the chat agent's read path: the real node run → extras.gw_rows (one list per key), kept out of prompts and meta"""

    def read(self, query, targets):
        from app.agents import groupware as groupware_agent
        calls = {"calls": [{"name": "read_groupware", "args": {"targets": targets}}]}
        with patch("app.llm.generate_calls", return_value=calls), patch("app.groupware._classify", return_value=None):
            return groupware_agent._run_sync(query, [])

    def test_mail_read_carries_its_list(self):
        res = self.read("안 읽은 메일 보여줘", ["mail"])
        self.assertEqual(res["status"], "answer")
        ex = res["extras"]
        self.assertEqual((ex["gw_keys"], ex["gw"], ex["gw_rows"]), (["mail.info.unread"], [GW_MAIL], [MAIL_LIST]))
        self.assertIn("- 3분기 예산안 검토 요청 — 김지민 · 오늘 10:12 · 안 읽음", res["text"])   # text 줄은 종전대로 / as before

    def test_mail_and_news_give_one_gw_list_each(self):
        res = {**self.read("안 읽은 메일이랑 뉴스 보여줘", ["mail", "news"]), "agent": "groupware"}
        self.assertEqual([g["key"] for g in res["extras"]["gw_rows"]], ["mail.info.unread", "news"])
        results = {"groupware": res}
        block = openui.data_statements(results, openui.numbered_sources(results))
        self.assertEqual(block["names"], ["gw1", "gw2"])
        self.assertIn("gw1: [1] Outlook 메일 · 안 읽은 메일 · 2행, left = 제목, right = 보낸 사람 · 시각 · 안 읽음 표시", block["legend"])
        self.assertIn("gw2: [2] 오늘의 뉴스 · 3행, left = 항목, right = 내용", block["legend"])

    def test_gw_rows_stay_out_of_the_prompt_and_meta(self):
        ex = gw_result()["extras"]
        self.assertNotIn("gw_rows", answers._slim_extras(ex))
        self.assertIn("gw_rows", ex)                                             # 원본 불변 / the original is untouched
        meta = answers._without_excerpts({"groupware": gw_result(), "knowledge": kn_result()})
        self.assertNotIn("gw_rows", meta["groupware"]["extras"])
        self.assertNotIn("excerpts", meta["knowledge"]["extras"])
        self.assertEqual(meta["groupware"]["extras"]["gw"], [GW_NEWS])


if __name__ == "__main__":
    unittest.main()
