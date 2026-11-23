"""양식 자동 추출(Word · Excel · PowerPoint, 2026-09-21) — 실제 파일을 만들어 분석 계획 검증·표시 넣기·확장된 채우기 엔진·API 를 확인한다. LLM 은 고정 계획으로 대체.
Automatic form extraction (Word, Excel, PowerPoint): real file round-trips for plan validation, marking, the extended fill engine and the API; the LLM is a fixed plan."""
import io
from unittest.mock import AsyncMock, patch

import httpx
from docx import Document
from docx.oxml.ns import qn
from docx.shared import RGBColor
from fastapi import HTTPException

from test_boards_api import BoardsBase, eff_for
from app import boards_api, db, docgen, template_analyze, template_files

GREY = RGBColor(0xA6, 0xA6, 0xA6)


def meeting_form() -> bytes:
    """회의록 양식 — 정보 표(예시·빈칸), 1.1/1.2 반복 절, 빈 글머리표, 번호만 있는 표 행, 간격용 빈 문단, 마지막 빈 문단
    A minutes form: info table, repeated 1.1/1.2 sections, empty bullets, numbered empty rows, a spacing paragraph, a trailing paragraph."""
    doc = Document()
    doc.add_paragraph("회  의  록")                                   # p0
    info = doc.add_table(rows=2, cols=4)                              # t0
    info.cell(0, 0).text = "회의명"
    info.cell(0, 1).paragraphs[0].add_run("예) 주간 회의").font.color.rgb = GREY
    info.cell(0, 2).text = "일시"
    info.cell(0, 3).paragraphs[0].add_run("YYYY. MM. DD.").font.color.rgb = GREY
    info.cell(1, 0).text = "장소"
    info.cell(1, 2).text = "참석자"
    doc.add_paragraph("1. 공유 사항", style="Heading 1")               # p1
    for n in (1, 2):                                                  # p2~p4, p5~p7
        h = doc.add_paragraph(style="Heading 2")
        h.add_run(f"1.{n} ")
        h.add_run("파트명 (담당자)").font.color.rgb = GREY
        doc.add_paragraph(style="List Bullet").add_run("진행 내용 / 완료 사항").font.color.rgb = GREY
        doc.add_paragraph(style="List Bullet").add_run("요청 사항: ").font.color.rgb = GREY
    doc.add_paragraph("")                                             # p8 간격용 빈 문단(Normal) / a spacing paragraph
    doc.add_paragraph("2. 논의 및 결정 사항", style="Heading 1")       # p9
    doc.add_paragraph(style="List Bullet").add_run("안건: 논의 내용 → 결정 사항 (담당)").font.color.rgb = GREY   # p10
    doc.add_paragraph("", style="List Bullet")                        # p11
    doc.add_paragraph("", style="List Bullet")                        # p12
    doc.add_paragraph("3. Action Items", style="Heading 1")           # p13
    act = doc.add_table(rows=4, cols=3)                               # t1
    for i, head in enumerate(("No.", "항목", "담당")):
        act.cell(0, i).text = head
    for r in (1, 2, 3):
        act.cell(r, 0).text = str(r)
    doc.add_paragraph("위와 같이 회의 내용을 기록합니다.")              # p14 고정 문구 / fixed text
    doc.add_paragraph("")                                             # p15 마지막 문단 / the last paragraph
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


PLAN = {
    "doc_type": "회의록", "name": "주간 회의록", "description": "주간 회의 기록 양식", "instruction": "개조식으로 쓴다.",
    "blocks": [
        {"id": "t0.r0.c1", "action": "replace", "text": "{{회의명}}"},
        {"id": "t0.r0.c3", "action": "replace", "text": "{{일시}}"},
        {"id": "t0.r1.c1", "action": "replace", "text": "{{장소}}"},
        {"id": "t0.r1.c3", "action": "replace", "text": "{{참석자}}"},
        {"id": "p2", "action": "replace", "text": "1.{{파트.#}} {{파트.파트명}} ({{파트.담당자}})"},
        {"id": "p3", "action": "replace", "text": "{{파트.진행 내용/완료 사항}}"},          # 허용 밖 글자 → 정리 / cleaned name
        {"id": "p4", "action": "replace", "text": "요청 사항: {{파트.요청 사항}}"},
        {"id": "p5", "action": "delete"}, {"id": "p6", "action": "delete"}, {"id": "p7", "action": "delete"},
        {"id": "p10", "action": "replace", "text": "{{논의 및 결정 사항}}"},
        {"id": "p11", "action": "delete"}, {"id": "p12", "action": "delete"},
        {"id": "t1.r1.c0", "action": "replace", "text": "{{액션.#}}"},
        {"id": "t1.r1.c1", "action": "replace", "text": "{{액션.항목}}"},
        {"id": "t1.r1.c2", "action": "replace", "text": "{{액션.담당}}"},
        {"id": "t1.r2", "action": "delete"}, {"id": "t1.r3", "action": "delete"},
        # ── 코드가 거절해야 하는 것 / entries the code must refuse ──
        {"id": "p0", "action": "replace", "text": "회의록(수정)"},        # 표시 없는 바꾸기 / a rewrite without a marker
        {"id": "p1", "action": "delete"},                               # 고정 제목 지우기 / deleting a fixed heading
        {"id": "p8", "action": "delete"},                               # 간격용 빈 문단 / a spacing paragraph
        {"id": "p14", "action": "delete"},                              # 고정 문구 / fixed text
        {"id": "p15", "action": "delete"},                              # 마지막 문단 / the last paragraph
        {"id": "t0.r1.c0", "action": "delete"},                         # 칸은 못 지운다 / cells cannot be deleted
        {"id": "p99", "action": "delete"},                              # 없는 블록 / unknown block
    ],
    "slots": [
        {"name": "회의명", "type": "text", "hint": "회의 이름", "example": "주간 회의", "required": True},
        {"name": "일시", "type": "text", "hint": "회의 일시", "example": "YYYY. MM. DD.", "required": True},
        {"name": "파트.진행 내용/완료 사항", "type": "list", "hint": "진행 현황"},
        {"name": "파트.요청 사항", "type": "list", "hint": "요청"},                       # 라벨과 같이 있는 자리는 목록이 될 수 없다 / not a whole-paragraph slot
        {"name": "파트.담당자", "type": "text", "required": True},                      # 묶음 항목은 필수 입력이 아니다 / group fields are never required inputs
        {"name": "논의 및 결정 사항", "type": "list", "hint": "안건별 결정", "example": "안건: 논의 내용 → 결정 사항 (담당)"},
    ],
    "groups": [{"name": "파트", "hint": "파트별 공유 사항"}, {"name": "액션", "hint": "실행 과제"}],
}


def body_lines(path_or_bytes) -> list[str]:
    doc = Document(io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, bytes) else str(path_or_bytes))
    return [p.text for p in doc.paragraphs]


class AnalyzeTests(BoardsBase):
    def analyzed(self, owner="", groups=()):
        with patch("app.llm.generate", return_value=PLAN):
            return template_analyze.analyze_and_save(meeting_form(), "회의록.docx", owner, list(groups))

    async def test_plan_is_validated_by_code_before_it_touches_the_file(self):
        out = self.analyzed()
        info, a = out["file"], out["analysis"]
        self.assertTrue(info["auto"])
        self.assertEqual(info["fields"], ["회의명", "일시", "장소", "참석자", "파트.파트명", "파트.담당자", "파트.진행 내용 완료 사항",
                                          "파트.요청 사항", "논의 및 결정 사항", "액션.항목", "액션.담당"])
        self.assertEqual(info["types"], {"파트.진행 내용 완료 사항": "list", "논의 및 결정 사항": "list"})
        by = {s["name"]: s for s in a["slots"]}
        self.assertEqual((by["회의명"]["required"], by["파트.담당자"]["required"], by["파트.요청 사항"]["type"]), (True, False, "text"))
        self.assertEqual(by["회의명"]["original"], "예) 주간 회의")
        self.assertEqual([g["name"] for g in a["groups"]], ["파트", "액션"])
        self.assertEqual((a["name"], a["instruction"], a["stats"]["removed"]), ("주간 회의록", "개조식으로 쓴다.", 7))
        _, _, marked = template_files.get(info["id"])
        lines = body_lines(marked)
        # 거절: 제목 고쳐 쓰기·고정 제목/문구·간격 문단·마지막 문단은 그대로 / refused edits leave the original alone
        self.assertEqual(lines[0], "회  의  록")
        self.assertIn("1. 공유 사항", lines)
        self.assertIn("위와 같이 회의 내용을 기록합니다.", lines)
        self.assertEqual(lines[-1], "")
        self.assertEqual(lines.count("1.{{파트.#}} {{파트.파트명}} ({{파트.담당자}})"), 1)
        self.assertNotIn("1.2 파트명 (담당자)", lines)
        self.assertEqual(len(Document(io.BytesIO(marked)).tables[1].rows), 2)
        # 원본은 그대로 보관된다 / the untouched original is kept
        meta, _, source = template_files.get(info["source_id"])
        self.assertEqual(meta["kind"], "source")
        self.assertIn("1.2 파트명 (담당자)", body_lines(source))

    async def test_marking_drops_guide_grey_and_keeps_the_heading_with_a_growing_table(self):
        info = self.analyzed()["file"]
        _, _, marked = template_files.get(info["id"])
        doc = Document(io.BytesIO(marked))
        run = doc.tables[0].cell(0, 1).paragraphs[0].runs[0]
        self.assertEqual((run.text, run.font.color.rgb), ("{{회의명}}", None))   # 회색 안내색은 물려받지 않는다 / guide grey is not inherited
        heading = next(p for p in doc.paragraphs if p.text == "3. Action Items")
        self.assertIsNotNone(heading._p.pPr.find(qn("w:keepNext")))

    async def test_fill_repeats_paragraph_groups_lists_rows_and_keeps_blank_lines(self):
        info = self.analyzed()["file"]
        out = docgen.GENERATED_DIR / "minutes.docx"
        template_files.fill(info["id"], {
            "회의명": "주간 회의", "일시": "9/21", "장소": "7층", "참석자": "김, 이",
            "파트": [{"파트명": "백엔드", "담당자": "박준호", "진행 내용 완료 사항": ["배포 완료", "개편 반영"], "요청 사항": "메모리 증설"},
                     {"파트명": "프런트", "담당자": "최유나", "진행 내용 완료 사항": ["버튼 추가"]}],
            "논의 및 결정 사항": [], "액션": [{"항목": "시제품", "담당": "박준호"}, {"항목": "문서", "담당": "이서윤"}]}, out)
        doc = Document(str(out))
        lines = [p.text for p in doc.paragraphs]
        i = lines.index("1.1 백엔드 (박준호)")
        self.assertEqual(lines[i:i + 7], ["1.1 백엔드 (박준호)", "배포 완료", "개편 반영", "요청 사항: 메모리 증설",
                                          "1.2 프런트 (최유나)", "버튼 추가", "요청 사항: "])   # 값 없는 줄은 라벨만 남긴다 / a line without a value keeps its label
        styles = [p.style.name for p in doc.paragraphs[i:i + 7]]
        self.assertEqual(styles, ["Heading 2", "List Bullet", "List Bullet", "List Bullet", "Heading 2", "List Bullet", "List Bullet"])
        j = lines.index("2. 논의 및 결정 사항")
        self.assertEqual((lines[j + 1], doc.paragraphs[j + 1].style.name), ("", "List Bullet"))   # 빈 목록 = 빈 줄 하나 / an empty list keeps one blank bullet
        rows = [[c.text for c in r.cells] for r in doc.tables[1].rows]
        self.assertEqual(rows, [["No.", "항목", "담당"], ["1", "시제품", "박준호"], ["2", "문서", "이서윤"]])
        self.assertFalse(any("{{" in p.text for p in doc.paragraphs))

    async def test_turning_slots_off_restores_the_original_and_renaming_changes_the_fields(self):
        info = self.analyzed()["file"]
        off = [n for n in info["fields"] if n.startswith("파트.")]
        again = template_analyze.remark(info["id"], "", off, {"회의명": "회의 이름", "액션.항목": "할 일", "없는 항목": "x"})
        f2 = again["file"]
        self.assertNotEqual(f2["id"], info["id"])
        self.assertEqual(f2["fields"], ["회의 이름", "일시", "장소", "참석자", "논의 및 결정 사항", "액션.할 일", "액션.담당"])
        self.assertEqual(f2["types"], {"논의 및 결정 사항": "list"})
        lines = body_lines(template_files.get(f2["id"])[2])
        self.assertIn("1.1 파트명 (담당자)", lines)   # 끈 자리는 원본 글 그대로 / a turned-off place keeps the original text
        self.assertIn("1.2 파트명 (담당자)", lines)   # 그 묶음에 기대던 지우기도 되돌린다 / deletes that leaned on it are undone
        state = {s["key"]: (s["name"], s["off"]) for s in again["analysis"]["slots"]}
        self.assertEqual((state["회의명"], state["파트.파트명"]), (("회의 이름", False), ("파트.파트명", True)))
        with self.assertRaises(ValueError):
            template_analyze.remark(info["id"], "", list(info["fields"]), {})
        with self.assertRaises(ValueError):
            template_analyze.remark(info["id"], "", [], {"일시": "장소"})   # 이름 겹침 / a clashing name
        hand = template_files.save(_hand_marked(), "손표시.docx", "", [])
        with self.assertRaises(ValueError):
            template_analyze.remark(hand["id"], "", [], {})

    async def test_plans_stored_by_the_first_stage_still_re_mark_correctly(self):
        """1단계(2026-09-21 오전) 계획에는 fmt·row 가 없다 — 실 DB 에 그런 원본 행이 남아 있으므로 그대로 다시 적용돼야 한다.
        First-stage plans carry no fmt/row; such source rows exist in the real DB and must keep re-marking correctly."""
        import json
        info = self.analyzed()["file"]
        with db._conn() as conn:
            meta = json.loads(conn.execute("SELECT metadata FROM template_files WHERE id=?", (info["source_id"],)).fetchone()["metadata"])
            meta["plan"].pop("fmt")
            for rep in meta["plan"]["replaces"].values():
                rep.pop("row", None)
            conn.execute("UPDATE template_files SET metadata=? WHERE id=?", (json.dumps(meta, ensure_ascii=False), info["source_id"]))
        again = template_analyze.remark(info["id"], "", ["장소"], {})["file"]
        doc = Document(io.BytesIO(template_files.get(again["id"])[2]))
        self.assertEqual((len(doc.tables[1].rows), "장소" in again["fields"]), (2, False))      # 표 행 지우기가 여전히 적용된다 / row deletions still apply
        every = template_analyze.remark(info["id"], "", ["액션.항목", "액션.담당"], {})["file"]
        self.assertEqual(len(Document(io.BytesIO(template_files.get(every["id"])[2])).tables[1].rows), 4)   # 묶음을 끄면 원본 행이 돌아온다 / rows come back with the group off

    async def test_upload_api_analyzes_marker_less_word_and_guards_other_cases(self):
        self.effs["7"] = eff_for({"bd_g_og9": 2})
        self.effs["12"] = eff_for({"bd_g_og3": 2})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
            with patch("app.llm.generate", return_value=PLAN):
                ok = await client.post("/api/boards/template-files", data={"acting_user_id": "", "groups": '["og9"]'},
                                       files={"file": ("회의록.docx", meeting_form())})
            self.assertEqual(ok.status_code, 200, ok.text)
            body = ok.json()
            self.assertEqual((body["file"]["auto"], body["analysis"]["stats"]["slots"]), (True, 11))
            with patch("app.llm.generate", side_effect=RuntimeError("busy")):
                busy = await client.post("/api/boards/template-files", data={"acting_user_id": "", "groups": '["og9"]'},
                                         files={"file": ("회의록.docx", meeting_form())})
            self.assertEqual(busy.status_code, 503)
            with patch("app.llm.generate", return_value={"blocks": []}):
                none = await client.post("/api/boards/template-files", data={"acting_user_id": "", "groups": '["og9"]'},
                                         files={"file": ("회의록.docx", meeting_form())})
            self.assertEqual(none.status_code, 422)
            # 2단계: 표시 없는 Excel·PowerPoint 도 같은 업로드로 자동 인식된다 / stage 2: marker-less Excel and PowerPoint go through the same upload
            with patch("app.llm.generate", return_value=PLAN_XLSX):
                xl = await client.post("/api/boards/template-files", data={"acting_user_id": "", "groups": '["og9"]'},
                                       files={"file": ("정산서.xlsx", expense_form())})
            self.assertEqual(xl.status_code, 200, xl.text)
            self.assertEqual((xl.json()["file"]["format"], xl.json()["file"]["auto"]), ("xlsx", True))
            with patch("app.llm.generate", return_value=PLAN_PPTX):
                pp = await client.post("/api/boards/template-files", data={"acting_user_id": "", "groups": '["og9"]'},
                                       files={"file": ("현황.pptx", status_deck())})
            self.assertEqual(pp.status_code, 200, pp.text)
            pdf = await client.post("/api/boards/template-files", data={"acting_user_id": "", "groups": '["og9"]'},
                                    files={"file": ("양식.pdf", b"%PDF-1.4")})
            self.assertEqual(pdf.status_code, 422)
            fid = body["file"]["id"]
            denied = await client.post(f"/api/boards/template-files/{fid}/remark", json={"acting_user_id": "12", "off": ["장소"]})
            self.assertEqual(denied.status_code, 403)
            re = await client.post(f"/api/boards/template-files/{fid}/remark", json={"acting_user_id": "", "off": ["장소"]})
            self.assertEqual(re.status_code, 200, re.text)
            self.assertNotIn("장소", re.json()["file"]["fields"])
        # 보관용 원본 행은 양식으로 쓸 수 없다 / the kept original is not a usable form
        with self.assertRaises(HTTPException):
            boards_api.create_template(boards_api.TemplateIn(acting_user_id="", template={
                "name": "x", "format": "docx", "mode": "fill", "groups": ["og9"], "file_id": body["file"]["source_id"]}))

    async def test_generation_tells_the_model_which_slots_are_lists_and_fills_the_auto_form(self):
        docgen.init_docgen()

        async def smooth(text):
            yield text
        info = self.analyzed()["file"]
        t = boards_api.create_template(boards_api.TemplateIn(template={"name": "회의록", "format": "docx", "mode": "fill",
            "file_id": info["id"], "groups": [], "inputs": [{"name": "회의명", "required": True}], "source": "general"}))["template"]
        prep = boards_api.prepare_template_run(t["id"], "7", {"회의명": "주간 회의"})
        chat = db.create_chat("auto", "사내")
        seen = []

        async def capture(state, user, system, tier="main"):
            seen.append((user, system))
            return {"values": {"일시": "9/21", "장소": "7층", "참석자": "김", "파트": [{"파트명": "백엔드", "담당자": "박", "진행 내용 완료 사항": ["가", "나"]}],
                               "액션": [{"항목": "시제품", "담당": "박"}]}}
        with patch.object(docgen, "_llm_json", new=capture), patch.object(docgen, "collection_material", return_value=""), \
             patch.object(docgen, "_smooth", smooth):
            d = prep["docgen"]
            events = [e async for e in docgen.run_docgen(chat, "회의록 만들어줘", "docx", d["topic"], d["style"], d["length"],
                                                          "general", "7", d["instruction"], template=prep["template"])]
        self.assertEqual(events[-1]["type"], "done", events[-1])
        user, system = seen[0]
        self.assertIn('"형식": "목록"', user)
        self.assertIn("원본 예시", user)
        self.assertIn("문자열 배열", system)
        meta = next(e for e in events if e["type"] == "doc_meta")
        values = docgen.list_pages(meta["doc_id"])[0]["data"]["template_values"]
        self.assertEqual(values["논의 및 결정 사항"], [])   # 못 채운 목록은 빈 목록 / an unfilled list stays an empty list
        lines = body_lines(docgen.build_file(meta["doc_id"]))
        self.assertIn("1.1 백엔드 (박)", lines)
        self.assertNotIn("게시판에 공유", "".join(e["text"] for e in events if e["type"] == "token"))


def _hand_marked() -> bytes:
    """손으로 표시한 양식 — 본문 문단 묶음, 두 줄짜리 표 묶음, 순번 / a hand-marked form: paragraph group, two-row table group, index"""
    doc = Document()
    doc.add_paragraph("{{건.#}}) {{건.제목}}", style="Heading 2")
    doc.add_paragraph("{{건.내용}}")
    doc.add_paragraph("끝")
    t = doc.add_table(rows=3, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "이름", "부서"
    t.cell(1, 0).text, t.cell(1, 1).text = "{{인원.이름}}", "{{인원.부서}}"
    t.cell(2, 0).text, t.cell(2, 1).text = "비고", "{{인원.비고}}"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class EngineExtensionTests(BoardsBase):
    async def test_hand_marked_paragraph_groups_two_row_records_and_index(self):
        info = template_files.save(_hand_marked(), "손표시.docx", "", [])
        self.assertEqual(info["fields"], ["건.제목", "건.내용", "인원.이름", "인원.부서", "인원.비고"])   # 순번(#)은 항목이 아니다 / the index is not a field
        out = docgen.GENERATED_DIR / "hand.docx"
        template_files.fill(info["id"], {"건": [{"제목": "가", "내용": "가 내용"}, {"제목": "나"}],
                                         "인원": [{"이름": "김", "부서": "A", "비고": "x"}, {"이름": "이", "부서": "B"}]}, out)
        doc = Document(str(out))
        self.assertEqual([p.text for p in doc.paragraphs][:5], ["1) 가", "가 내용", "2) 나", "", "끝"])
        rows = [[c.text for c in r.cells] for r in doc.tables[0].rows]
        self.assertEqual(rows, [["이름", "부서"], ["김", "A"], ["비고", "x"], ["이", "B"], ["비고", ""]])   # 한 건 = 두 행이 같이 늘어난다 / a record's two rows repeat together
        sample = template_files.sample_values(info)
        self.assertEqual((len(sample["건"]), sample["인원"][1]["이름"]), (2, "예시 이름 2"))

    async def test_repeating_markers_outside_the_word_body_are_still_rejected(self):
        doc = Document()
        doc.add_paragraph("본문 {{제목}}")
        doc.sections[0].header.paragraphs[0].text = "{{머리.항목}}"
        buf = io.BytesIO()
        doc.save(buf)
        with self.assertRaises(ValueError):
            template_files.inspect(buf.getvalue(), "docx")
        with self.assertRaises(template_files.NoSlots):
            template_files.inspect(meeting_form(), "docx")


# ───────────────────────── 2단계: Excel · PowerPoint / stage 2 ─────────────────────────
def expense_form() -> bytes:
    """출장 경비 정산서 — 라벨·빈 입력 칸(테두리), 회색 예시, 번호만 있는 4행 표, 합계 수식, 병합된 메모 칸
    An expense form: labels, bordered empty input cells, a grey example, four numbered rows, a SUM formula, a merged note cell."""
    from openpyxl import Workbook
    from openpyxl.styles import Border, Font, Side
    wb = Workbook()
    ws = wb.active
    ws.title = "정산서"
    box = Border(*(Side(style="thin"),) * 4)
    ws.merge_cells("A1:D1")
    ws["A1"] = "출 장 경 비 정 산 서"
    for ref, text in (("A3", "신청자"), ("C3", "부서"), ("A4", "출장 기간"), ("C4", "출장지")):
        ws[ref] = text
    for ref in ("B3", "D3", "B4", "D4"):
        ws[ref].border = box
    ws["B4"] = "YYYY.MM.DD ~ MM.DD"
    ws["B4"].font = Font(color="FFA6A6A6")
    for col, head in zip("ABCD", ("No.", "항목", "금액", "내역")):
        ws[f"{col}6"] = head
    for i, r in enumerate(range(7, 11), 1):
        ws[f"A{r}"] = i
        for col in "BCD":
            ws[f"{col}{r}"].border = box
    ws["A11"] = "합계"
    ws["C11"] = "=SUM(C7:C10)"
    ws["A13"] = "특이 사항"
    ws.merge_cells("B13:D13")
    ws["B13"].border = box
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


PLAN_XLSX = {
    "doc_type": "정산서", "name": "출장 경비 정산서", "description": "출장 경비 정산", "instruction": "금액은 숫자만 쓴다.",
    "blocks": [
        {"id": "S1!B3", "action": "replace", "text": "{{신청자}}"}, {"id": "S1!D3", "action": "replace", "text": "{{부서}}"},
        {"id": "S1!B4", "action": "replace", "text": "{{출장 기간}}"}, {"id": "S1!D4", "action": "replace", "text": "{{출장지}}"},
        {"id": "S1!B7", "action": "replace", "text": "{{지출.항목}}"}, {"id": "S1!C7", "action": "replace", "text": "{{지출.금액}}"},
        {"id": "S1!D7", "action": "replace", "text": "{{지출.내역}}"},
        {"id": "S1!r10", "action": "repeat"}, {"id": "S1!r8", "action": "repeat"}, {"id": "S1!r9", "action": "repeat"},   # 순서가 뒤섞여도 위에서부터 잇는다 / chained top-down
        {"id": "S1!B13", "action": "replace", "text": "{{특이 사항}}"},
        # ── 코드가 거절해야 하는 것 / entries the code must refuse ──
        {"id": "S1!C11", "action": "replace", "text": "{{합계}}"},         # 수식 칸 / a formula cell
        {"id": "S1!A7", "action": "replace", "text": "{{지출.#}}"},        # 찍혀 있는 순번 / printed row numbers stay
        {"id": "S1!r11", "action": "repeat"},                              # 합계 행은 같은 모양이 아니다 / the total row is not a twin
        {"id": "S1!r13", "action": "delete"},                              # Excel 은 아무것도 지우지 않는다 / nothing is ever deleted in Excel
    ],
    "slots": [{"name": "신청자", "required": True, "hint": "신청자 이름"}, {"name": "지출.금액", "hint": "숫자만"},
              {"name": "특이 사항", "type": "list"}],   # Excel 칸은 목록이 될 수 없다 / a cell never becomes a list
    "groups": [{"name": "지출", "hint": "지출 내역 행"}],
}


def status_deck() -> bytes:
    """현황 보고 슬라이드 3장 — 제목·부제목 개체 틀, 예시 글머리표 3줄(마지막은 빈 줄), 머리말 + 빈 3행 표
    A three-slide status deck: title/subtitle placeholders, three example bullets (the last one empty), a table with a header and three empty rows."""
    from pptx import Presentation
    from pptx.util import Inches
    deck = Presentation()
    s1 = deck.slides.add_slide(deck.slide_layouts[0])
    s1.shapes.title.text = "프로젝트명을 입력하세요"
    s1.placeholders[1].text = "YYYY.MM.DD | 보고자"
    s2 = deck.slides.add_slide(deck.slide_layouts[1])
    s2.shapes.title.text = "1. 진행 현황"
    tf = s2.placeholders[1].text_frame
    tf.text = "현황 요약 첫째 줄"
    tf.add_paragraph().text = "현황 요약 둘째 줄"
    tf.add_paragraph().text = ""
    s3 = deck.slides.add_slide(deck.slide_layouts[5])
    s3.shapes.title.text = "2. 주요 이슈"
    table = s3.shapes.add_table(4, 3, Inches(0.8), Inches(1.6), Inches(8.4), Inches(2.4)).table
    for i, head in enumerate(("구분", "내용", "담당")):
        table.cell(0, i).text = head
    buf = io.BytesIO()
    deck.save(buf)
    return buf.getvalue()


PLAN_PPTX = {
    "doc_type": "현황 보고", "name": "프로젝트 현황 보고", "description": "현황 보고 슬라이드", "instruction": "슬라이드 문구라 짧게 쓴다.",
    "blocks": [
        {"id": "s1.p0", "action": "replace", "text": "{{프로젝트명}}"},
        {"id": "s1.p1", "action": "replace", "text": "{{보고일}} | {{보고자}}"},
        {"id": "s2.p1", "action": "replace", "text": "{{진행 현황}}"},
        {"id": "s2.p2", "action": "delete"}, {"id": "s2.p3", "action": "delete"},
        {"id": "s3.t0.r1.c0", "action": "replace", "text": "{{이슈.구분}}"}, {"id": "s3.t0.r1.c1", "action": "replace", "text": "{{이슈.내용}}"},
        {"id": "s3.t0.r1.c2", "action": "replace", "text": "{{이슈.담당}}"},
        {"id": "s3.t0.r2", "action": "repeat"}, {"id": "s3.t0.r3", "action": "repeat"},
        # ── 코드가 거절해야 하는 것 / entries the code must refuse ──
        {"id": "s2.p0", "action": "delete"},                                   # 고정 슬라이드 제목 / a fixed slide title
        {"id": "s3.t0.r0", "action": "repeat"},                                # 머리말 행 / the header row
        {"id": "s3.p0", "action": "replace", "text": "{{이슈.제목}}"},         # 표 밖의 묶음 / a group outside a table
        {"id": "s3.t0.r1", "action": "delete"},                                # 슬라이드 표의 행은 지우지 않는다 / slide table rows are never deleted
    ],
    "slots": [{"name": "프로젝트명", "required": True}, {"name": "진행 현황", "type": "list", "hint": "3줄 이내"}],
    "groups": [{"name": "이슈", "hint": "주요 이슈 행"}],
}


class SpreadsheetAndSlidesTests(BoardsBase):
    async def test_excel_marks_input_cells_copies_twin_rows_and_fills_within_the_original_rows(self):
        from openpyxl import load_workbook
        with patch("app.llm.generate", return_value=PLAN_XLSX):
            out = template_analyze.analyze_and_save(expense_form(), "정산서.xlsx", "", [])
        info, a = out["file"], out["analysis"]
        self.assertEqual(info["fields"], ["신청자", "부서", "출장 기간", "출장지", "지출.항목", "지출.금액", "지출.내역", "특이 사항"])
        self.assertEqual((info["types"], a["groups"], a["stats"]["removed"]), ({}, [{"name": "지출", "hint": "지출 내역 행", "capacity": 4}], 0))
        ws = load_workbook(io.BytesIO(template_files.get(info["id"])[2])).active
        self.assertEqual([ws[f"B{r}"].value for r in (7, 8, 9, 10)], ["{{지출.항목}}"] * 4)        # 같은 표시가 쌍둥이 행에 복사된다 / markers copied into twin rows
        self.assertEqual(([ws[f"A{r}"].value for r in (7, 10)], ws["C11"].value, ws["A11"].value), ([1, 4], "=SUM(C7:C10)", "합계"))
        self.assertIsNone(getattr(ws["B4"].font.color, "rgb", None) if ws["B4"].font.color is not None else None)   # 회색 안내색 제거 / guide grey dropped
        self.assertIn("B13:D13", str(ws.merged_cells))
        output = docgen.GENERATED_DIR / "expense.xlsx"
        template_files.fill(info["id"], {"신청자": "홍길동", "부서": "AI 파트", "출장 기간": "9/16 ~ 9/17", "출장지": "부산", "특이 사항": "없음",
                                         "지출": [{"항목": "교통비", "금액": "52000", "내역": "KTX"}, {"항목": "숙박비", "금액": 80000}]}, output)
        ws = load_workbook(output).active
        self.assertEqual([[ws[f"{c}{r}"].value for c in "ABCD"] for r in (7, 8, 9)],
                         [[1, "교통비", 52000, "KTX"], [2, "숙박비", 80000, None], [3, None, None, None]])   # 모자란 행은 빈칸, 번호는 그대로 / spare rows blank, numbers stay
        self.assertEqual(ws["C11"].value, "=SUM(C7:C10)")
        many = [{"항목": f"항목{i}", "금액": i} for i in range(1, 8)]
        template_files.fill(info["id"], {"신청자": "a", "부서": "b", "출장 기간": "c", "출장지": "d", "특이 사항": "", "지출": many}, output)
        ws = load_workbook(output).active
        self.assertEqual(([ws[f"B{r}"].value for r in (7, 10)], ws["A11"].value), (["항목1", "항목4"], "합계"))   # 행 수를 넘는 값은 넣지 않는다 / extra records are dropped
        off = template_analyze.remark(info["id"], "", ["지출.항목", "지출.금액", "지출.내역"], {})["file"]
        ws = load_workbook(io.BytesIO(template_files.get(off["id"])[2])).active
        self.assertEqual((off["fields"], ws["B8"].value), (["신청자", "부서", "출장 기간", "출장지", "특이 사항"], None))     # 끄면 복사한 표시도 사라진다 / copies vanish with the group

    async def test_slides_mark_placeholders_bullets_and_fixed_table_rows(self):
        from pptx import Presentation
        with patch("app.llm.generate", return_value=PLAN_PPTX):
            out = template_analyze.analyze_and_save(status_deck(), "현황.pptx", "", [])
        info, a = out["file"], out["analysis"]
        self.assertEqual(info["fields"], ["프로젝트명", "보고일", "보고자", "진행 현황", "이슈.구분", "이슈.내용", "이슈.담당"])
        self.assertEqual((info["types"], a["groups"][0]["capacity"], a["stats"]["removed"]), ({"진행 현황": "list"}, 3, 2))
        self.assertEqual(next(s for s in a["slots"] if s["name"] == "진행 현황")["lines"], 3)
        deck = Presentation(io.BytesIO(template_files.get(info["id"])[2]))
        self.assertEqual(deck.slides[1].shapes.title.text, "1. 진행 현황")                       # 고정 제목은 그대로 / the fixed title stays
        self.assertEqual([p.text for p in deck.slides[1].placeholders[1].text_frame.paragraphs], ["{{진행 현황}}"])
        self.assertEqual(deck.slides[2].shapes.title.text, "2. 주요 이슈")
        table = next(s for s in deck.slides[2].shapes if s.has_table).table
        self.assertEqual([table.cell(r, 1).text for r in range(4)], ["내용", "{{이슈.내용}}", "{{이슈.내용}}", "{{이슈.내용}}"])
        output = docgen.GENERATED_DIR / "status.pptx"
        before = (deck.slides[0].shapes.title.left, deck.slides[0].shapes.title.width)
        template_files.fill(info["id"], {"프로젝트명": "Ai365 3.0", "보고일": "9/21", "보고자": "박준호", "진행 현황": ["배포 완료", "개편 반영"],
                                         "이슈": [{"구분": "일정", "내용": "QA 지연", "담당": "김"}, {"구분": "품질", "내용": "503"}]}, output)
        deck = Presentation(str(output))
        self.assertEqual((deck.slides[0].shapes.title.text, deck.slides[0].placeholders[1].text), ("Ai365 3.0", "9/21 | 박준호"))
        self.assertEqual((deck.slides[0].shapes.title.left, deck.slides[0].shapes.title.width), before)
        self.assertEqual([p.text for p in deck.slides[1].placeholders[1].text_frame.paragraphs], ["배포 완료", "개편 반영"])
        table = next(s for s in deck.slides[2].shapes if s.has_table).table
        self.assertEqual([[table.cell(r, c).text for c in range(3)] for r in range(1, 4)],
                         [["일정", "QA 지연", "김"], ["품질", "503", ""], ["", "", ""]])          # 표는 원본 행 수 그대로 / the table keeps its rows
        sample = boards_api.template_file_sample(info["id"], boards_api.UseIn())
        self.assertTrue(sample.body.startswith(b"PK"))

    async def test_hand_marked_excel_and_slide_groups_fill_fixed_rows(self):
        from openpyxl import Workbook, load_workbook
        wb, buf = Workbook(), io.BytesIO()
        ws = wb.active
        ws["A1"], ws["A2"], ws["B2"], ws["A3"], ws["B3"] = "{{제목}}", "{{인원.이름}}", "{{인원.#}}번", "{{인원.이름}}", "{{인원.#}}번"
        wb.save(buf)
        info = template_files.save(buf.getvalue(), "손표시.xlsx", "", [])
        self.assertEqual(info["fields"], ["제목", "인원.이름"])
        output = docgen.GENERATED_DIR / "hand.xlsx"
        template_files.fill(info["id"], {"제목": "명단", "인원": [{"이름": "김"}]}, output)
        ws = load_workbook(output).active
        self.assertEqual([ws["A2"].value, ws["B2"].value, ws["A3"].value, ws["B3"].value], ["김", "1번", None, "번"])


# ───────────────────────── 자료 출처 개편(2026-09-21) / material-source rework ─────────────────────────
class MaterialSourceTests(BoardsBase):
    """요청과 대화는 항상 재료, 사내 자료 새 조회는 템플릿 체크(source=internal) 또는 요청 문장이 부를 때만, 못 찾아도 실패하지 않는다.
    The request and the conversation are always material; a fresh internal lookup runs only for source=internal or when the request asks; an empty lookup never fails."""

    async def test_request_wording_decides_a_fresh_lookup(self):
        yes = ["사내 자료에서 찾아서 채워줘", "9월 매출 데이터 조회해서 월간 보고서 만들어줘", "인사 규정 찾아서 반영해줘", "회사 문서 기준으로 작성"]
        no = ["오늘 주간 회의 회의록 만들어줘", "위 대화 내용으로 채워줘", "방금 조회한 실적으로 보고서 채워줘", "회의록 문서 만들어줘"]
        self.assertEqual(([boards_api.wants_lookup(m) for m in yes], [boards_api.wants_lookup(m) for m in no]), ([True] * 4, [False] * 4))

    async def test_fill_templates_keep_only_the_always_lookup_flag(self):
        info = template_files.save(_hand_marked(), "손표시.docx", "", [])
        base = {"name": "양식", "format": "docx", "mode": "fill", "groups": [], "file_id": info["id"]}
        self.assertEqual([boards_api._validate_template({**base, "source": s})["source"] for s in ("general", "context", "internal", "x")],
                         ["context", "context", "internal", "context"])
        outline = {"name": "공지", "format": "pdf", "sections": ["개요"], "source": "general"}
        self.assertEqual(boards_api._validate_template(outline)["source"], "general")   # 파일 없는 옛 템플릿은 종전 그대로 / older file-less templates unchanged

    async def _run(self, source, lookup, found):
        docgen.init_docgen()

        async def smooth(text):
            yield text
        info = template_files.save(_hand_marked(), "손표시.docx", "", [])
        t = boards_api.create_template(boards_api.TemplateIn(template={"name": "보고", "format": "docx", "mode": "fill", "file_id": info["id"],
                                                                        "groups": [], "source": source}))["template"]
        prep = boards_api.prepare_template_run(t["id"], "7", {})
        prep["template"]["lookup"] = lookup
        chat = db.create_chat("src", "사내")
        research = AsyncMock(return_value=found)
        seen = []

        async def capture(state, user, system, tier="main"):
            seen.append(user)
            return {"values": {"건": [{"제목": "가", "내용": "나"}], "인원": [{"이름": "김", "부서": "A", "비고": ""}]}}
        with patch.object(docgen, "_research_internal", new=research), patch.object(docgen, "_llm_json", new=capture), \
             patch.object(docgen, "collection_material", return_value=""), patch.object(docgen, "_smooth", smooth):
            d = prep["docgen"]
            events = [e async for e in docgen.run_docgen(chat, "보고서 채워줘", "docx", d["topic"], d["style"], d["length"],
                                                          d["source"], "7", d["instruction"], template=prep["template"])]
        return events, research, seen

    async def test_lookup_runs_only_when_asked_and_an_empty_lookup_does_not_fail(self):
        events, research, _ = await self._run("context", False, [])
        self.assertEqual((events[-1]["type"], research.await_count), ("done", 0))                # 대화만 / conversation only
        events, research, _ = await self._run("context", True, [])
        text = "".join(e["text"] for e in events if e["type"] == "token")
        self.assertEqual((events[-1]["type"], research.await_count), ("done", 1))                # 요청이 불렀다 → 조회, 못 찾아도 완료 / asked → looked up, still done
        self.assertIn("사내 자료에서 관련 근거를 찾지 못해", text)
        found = [{"agent": "data", "text": "9월 매출 1,200", "sources": None}]
        events, research, seen = await self._run("internal", False, found)
        self.assertEqual((events[-1]["type"], research.await_count), ("done", 1))                # 템플릿이 항상 조회 / the template always looks up
        self.assertIn("9월 매출 1,200", seen[0])
        self.assertEqual(next(e for e in events if e["type"] == "doc_meta")["source"], "internal")


# ───────────────────────── 3단계: PDF / stage 3 ─────────────────────────
def pdf_form(markers: bool = False) -> bytes:
    """선으로 그린 표(라벨 음영) + 제목 + 글머리표가 있는 PDF 양식 / a PDF form: a ruled table with shaded labels, a title and bullets"""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((230, 80), "출 장 보 고 서", fontname="korea", fontsize=20)
    xs, ys = [60, 160, 300, 400, 535], [110, 140, 170]
    for r in range(2):
        for c in (0, 2):
            page.draw_rect(fitz.Rect(xs[c], ys[r], xs[c + 1], ys[r + 1]), color=None, fill=(0.86, 0.9, 0.95))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y), color=(0, 0, 0), width=0.7)
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]), color=(0, 0, 0), width=0.7)
    for (r, c, text) in ((0, 0, "출장자"), (0, 2, "부서"), (1, 0, "출장 기간"), (1, 2, "출장지")):
        page.insert_text((xs[c] + 8, ys[r] + 20), text, fontname="korea", fontsize=10.5)
    if markers:
        page.insert_text((xs[1] + 8, ys[0] + 20), "{{출장자}}", fontname="korea", fontsize=10.5)
    else:
        page.insert_text((xs[1] + 8, ys[1] + 20), "YYYY.MM.DD", fontname="korea", fontsize=10.5, color=(0.65, 0.65, 0.65))
    page.insert_text((60, 215), "1. 출장 결과", fontname="korea", fontsize=13)
    page.insert_text((72, 240), "- 주요 결과를 한 줄씩 적습니다", fontname="korea", fontsize=10.5, color=(0.65, 0.65, 0.65))
    page.insert_text((72, 260), "- ", fontname="korea", fontsize=10.5)
    out = doc.tobytes()
    doc.close()
    return out


PLAN_PDF = {
    "doc_type": "출장 보고서", "name": "출장 보고서", "description": "출장 결과 보고", "instruction": "개조식으로 쓴다.",
    "blocks": [{"id": "t0.r0.c1", "action": "replace", "text": "{{출장자}}"}, {"id": "t0.r0.c3", "action": "replace", "text": "{{부서}}"},
               {"id": "t0.r1.c1", "action": "replace", "text": "{{출장 기간}}"}, {"id": "t0.r1.c3", "action": "replace", "text": "{{출장지}}"},
               {"id": "p3", "action": "replace", "text": "{{출장 결과}}"}, {"id": "p4", "action": "delete"}],
    "slots": [{"name": "출장자", "required": True}, {"name": "출장 결과", "type": "list"}],
}


class PdfFormTests(BoardsBase):
    async def test_pdf_is_rebuilt_as_a_word_form_with_the_same_structure(self):
        from app import template_pdf
        doc = Document(io.BytesIO(template_pdf.to_docx(pdf_form())))
        table = doc.tables[0]
        self.assertEqual([[c.text for c in r.cells] for r in table.rows], [["출장자", "", "부서", ""], ["출장 기간", "YYYY.MM.DD", "출장지", ""]])
        shade = table.cell(0, 0)._tc.tcPr.find(qn("w:shd"))
        self.assertEqual((shade is not None, table.cell(0, 1)._tc.tcPr is None or table.cell(0, 1)._tc.tcPr.find(qn("w:shd")) is None), (True, True))   # 라벨 칸만 음영 / only label cells are shaded
        self.assertEqual(str(table.cell(1, 1).paragraphs[0].runs[0].font.color.rgb), "A6A6A6")   # 회색 예시는 회색 그대로(표시 넣을 때 빠진다) / grey stays grey until marking
        texts = [(p.style.name, p.text) for p in doc.paragraphs if p.text or p.style.name == "List Bullet"]
        self.assertEqual(texts, [("Heading 1", "출 장 보 고 서"), ("Heading 1", "1. 출장 결과"), ("List Bullet", "주요 결과를 한 줄씩 적습니다"), ("List Bullet", "")])
        self.assertEqual(round(doc.sections[0].page_width.pt), 595)
        for bad in (b"not a pdf", b"%PDF-1.4"):
            with self.assertRaises(ValueError):
                template_pdf.to_docx(bad)
        import fitz
        blank = fitz.open()
        blank.new_page()
        with self.assertRaises(ValueError):
            template_pdf.to_docx(blank.tobytes())   # 글자 층이 없는 스캔본 / a scan without a text layer

    async def test_pdf_upload_goes_through_the_word_flow_and_says_so(self):
        self.effs["7"] = eff_for({"bd_g_og9": 2})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
            with patch("app.llm.generate", return_value=PLAN_PDF):
                ok = await client.post("/api/boards/template-files", data={"acting_user_id": "", "groups": '["og9"]'},
                                       files={"file": ("출장보고서.pdf", pdf_form())})
            self.assertEqual(ok.status_code, 200, ok.text)
            f = ok.json()["file"]
            self.assertEqual((f["format"], f["filename"], f["converted_from"], f["auto"]), ("docx", "출장보고서.docx", "pdf", True))
            self.assertEqual((f["fields"], f["types"]), (["출장자", "부서", "출장 기간", "출장지", "출장 결과"], {"출장 결과": "list"}))
            again = await client.post(f"/api/boards/template-files/{f['id']}/remark", json={"acting_user_id": "", "off": ["부서"]})
            self.assertEqual((again.status_code, again.json()["file"]["converted_from"]), (200, "pdf"))   # 다시 표시해도 안내가 따라간다 / the notice survives re-marking
            marked = await client.post("/api/boards/template-files", data={"acting_user_id": "", "groups": '["og9"]'},
                                       files={"file": ("표시있음.pdf", pdf_form(markers=True))})   # 표시가 든 PDF 는 AI 없이 읽는다(LLM 은 AssertionError 로 막혀 있다) / read without the AI
            self.assertEqual((marked.status_code, marked.json()["file"]["fields"], marked.json()["file"].get("auto")), (200, ["출장자"], None))
            scan = await client.post("/api/boards/template-files", data={"acting_user_id": "", "groups": '["og9"]'},
                                     files={"file": ("스캔.pdf", b"%PDF-1.4")})
            self.assertEqual(scan.status_code, 422)
        out = docgen.GENERATED_DIR / "trip.docx"
        template_files.fill(f["id"], {"출장자": "홍길동", "부서": "AI 파트", "출장 기간": "9/16 ~ 9/17", "출장지": "부산", "출장 결과": ["계약 협의", "일정 확정"]}, out)
        lines = [p.text for p in Document(str(out)).paragraphs]
        self.assertEqual(lines[lines.index("1. 출장 결과") + 1:][:2], ["계약 협의", "일정 확정"])

