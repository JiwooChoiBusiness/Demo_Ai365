"""Actual Office round-trips and template chat contracts, without external services."""
import io
import zipfile
import httpx
from unittest.mock import patch, AsyncMock

from fastapi import HTTPException
from test_boards_api import BoardsBase, eff_for
from app import boards, boards_api, template_files, docgen, db


def office(fmt):
    buf = io.BytesIO()
    if fmt == "docx":
        from docx import Document
        doc = Document()
        p = doc.add_paragraph()
        p.add_run("회사 양식 {{보고").bold = True
        p.add_run("기간}} / {{분석}} 끝")
        doc.sections[0].header.paragraphs[0].text = "회사 로고 영역"
        table = doc.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "품목"
        table.cell(0, 1).text = "매출"
        table.cell(1, 0).text = "{{실적.품목}}"
        table.cell(1, 1).text = "{{실적.매출}}"
        doc.save(buf)
    elif fmt == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import PatternFill
        book = Workbook(); sheet = book.active
        sheet['A1'] = '회사 양식'; sheet.merge_cells('A1:C1')
        sheet['A2'] = '{{보고기간}}'; sheet['B2'] = '{{매출}}'; sheet['C2'] = '=B2*2'
        sheet['A2'].fill = PatternFill('solid', fgColor='123456')
        sheet['A3'] = '{{분석}}'
        book.save(buf); book.close()
    else:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        deck = Presentation(); slide = deck.slides.add_slide(deck.slide_layouts[6])
        shape = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(6), Inches(2))
        p = shape.text_frame.paragraphs[0]
        p.add_run().text = '회사 {{보고'; p.runs[0].font.size = Pt(24)
        p.add_run().text = '기간}} / {{분석}}'
        deck.save(buf)
    return buf.getvalue()


class TemplateFilesTests(BoardsBase):
    async def test_native_word_preserves_runs_headers_and_repeats_rows(self):
        from docx import Document
        info = template_files.save(office('docx'), '기안서.docx', '', [])
        self.assertEqual(info['fields'], ['보고기간', '분석', '실적.품목', '실적.매출'])
        output = docgen.GENERATED_DIR / 'filled.docx'
        template_files.fill(info['id'], {'보고기간':'2월','분석':'계획 설명', '실적':[
            {'품목':'A','매출':10}, {'품목':'B','매출':20}]}, output)
        doc = Document(output)
        self.assertEqual(doc.paragraphs[0].text, '회사 양식 2월 / 계획 설명 끝')
        self.assertTrue(doc.paragraphs[0].runs[0].bold)
        self.assertEqual(doc.sections[0].header.paragraphs[0].text, '회사 로고 영역')
        self.assertEqual(len(doc.tables[0].rows), 3)
        self.assertEqual(doc.tables[0].cell(2, 1).text, '20')

    async def test_excel_preserves_formulas_formats_and_never_injects_formula(self):
        from openpyxl import load_workbook
        info = template_files.save(office('xlsx'), '실적.xlsx', '', [])
        output = docgen.GENERATED_DIR / 'filled.xlsx'
        template_files.fill(info['id'], {'보고기간':'3월','매출':'123','분석':'=HYPERLINK("evil")'}, output)
        book = load_workbook(output); s = book.active
        self.assertEqual((s['B2'].value, s['C2'].value), (123, '=B2*2'))
        self.assertEqual(s['A3'].data_type, 's')
        self.assertEqual(s['A2'].fill.fgColor.rgb, '00123456')
        self.assertIn('A1:C1', str(s.merged_cells)); book.close()

    async def test_ppt_preserves_slide_geometry_and_text_style(self):
        from pptx import Presentation
        from pptx.util import Inches, Pt
        info = template_files.save(office('pptx'), '영업.pptx', '', [])
        output = docgen.GENERATED_DIR / 'filled.pptx'
        template_files.fill(info['id'], {'보고기간':'4월','분석':'매출 분석'}, output)
        deck = Presentation(output); shape = deck.slides[0].shapes[0]
        self.assertEqual(shape.text, '회사 4월 / 매출 분석')
        self.assertEqual((shape.left,shape.top,shape.width), (Inches(1),Inches(2),Inches(6)))
        self.assertEqual(shape.text_frame.paragraphs[0].runs[0].font.size, Pt(24))

    async def test_upload_validation_and_asset_access(self):
        for content, fmt in ((b'bad', 'docx'), (office('docx'), 'xlsx'), (b'x'*(template_files.MAX_BYTES+1),'docx')):
            with self.assertRaises(ValueError): template_files.inspect(content, fmt)
        malicious = io.BytesIO()
        with zipfile.ZipFile(malicious, 'w') as z:
            z.writestr('word/document.xml', '<x/>'); z.writestr('word/vbaProject.bin', b'bad')
        with self.assertRaises(ValueError): template_files.inspect(malicious.getvalue(), 'docx')
        self.effs['7'] = eff_for({'bd_g_og9':2})
        self.effs['12'] = eff_for({'bd_g_og3':2})
        info = template_files.save(office('docx'), 'x.docx', '7', ['og9'])
        raw = {'name':'양식','format':'docx','mode':'fill','groups':['og9'],'file_id':info['id']}
        created = boards_api.create_template(boards_api.TemplateIn(acting_user_id='',template=raw))['template']   # 관리는 슈퍼만(2026-09-22) / super only
        with self.assertRaises(HTTPException):
            boards_api.create_template(boards_api.TemplateIn(acting_user_id='7',template={**raw,'groups':[]}))
        with self.assertRaises(HTTPException):
            boards_api.create_template(boards_api.TemplateIn(acting_user_id='12',template={**raw,'groups':['og3']}))
        with self.assertRaises(HTTPException):
            boards_api.template_file_sample(info['id'],boards_api.UseIn(acting_user_id='12'))
        for bad_groups in (['missing'], 'og9'):
            with self.assertRaises(HTTPException): boards_api._validate_template({**raw,'groups':bad_groups})
        sample = boards_api.template_file_sample(info['id'],boards_api.UseIn(acting_user_id=''))
        self.assertTrue(sample.body.startswith(b'PK'))
        self.assertEqual(created['file']['id'],info['id'])
        self.effs['7'] = eff_for({})
        with self.assertRaises(HTTPException):
            boards_api.template_file_sample(info['id'],boards_api.UseIn(acting_user_id='7'))

    async def test_multipart_upload_checks_registration_scope(self):
        self.effs['7'] = eff_for({'bd_g_og9':2})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://test') as client:
            denied = await client.post('/api/boards/template-files',data={'acting_user_id':'7','groups':'[]'},files={'file':('a.pptx',office('pptx'))})
            self.assertEqual(denied.status_code,403)
            ok = await client.post('/api/boards/template-files',data={'acting_user_id':'','groups':'["og9"]'},files={'file':('a.pptx',office('pptx'))})
            self.assertEqual(ok.status_code,200,ok.text)
            self.assertEqual(ok.json()['file']['format'],'pptx')
            bad = await client.post('/api/boards/template-files',data={'acting_user_id':'','groups':'["unknown"]'},files={'file':('a.pptx',office('pptx'))})
            self.assertEqual(bad.status_code,422)

    async def test_common_and_group_listing_and_version_revalidation(self):
        self.effs['7'] = eff_for({'bd_g_og9':2})
        base = {'name':'양식','format':'docx','sections':['내용']}
        common = boards_api.create_template(boards_api.TemplateIn(template=base))['template']
        mine = boards_api.create_template(boards_api.TemplateIn(acting_user_id='',template={**base,'groups':['og9']}))['template']
        other = boards.add_template({**base,'groups':['other']})
        ids = {t['id'] for t in boards_api.list_templates('7')['templates']}
        self.assertEqual(ids, {common['id'], mine['id']})
        boards.update_template(mine['id'],mine)
        with self.assertRaises(HTTPException) as ctx: boards_api.prepare_template_run(mine['id'],'7',{},1)
        self.assertEqual(ctx.exception.status_code,409)
        with patch('app.boards_api._groups_of',return_value=[]):
            with self.assertRaises(HTTPException): boards_api.prepare_template_run(mine['id'],'7',{})

    async def test_required_input_card_is_persisted_and_resumed_with_original_request(self):
        t = boards.add_template({'name':'영업','format':'docx','groups':[],'sections':[], 'inputs':[
            {'name':'보고기간','required':True}], 'length':2, 'source':'context'})
        chat = db.create_chat('template','사내')
        body = boards_api.TemplateChatIn(chat_id=chat['id'],message='영업 실적 보고서 만들어줘',acting_user_id='7',version=1)
        with patch('app.llm.generate',return_value={'inputs':{}}):
            question = boards_api.prepare_template_chat(t['id'],body)
        self.assertEqual(question['missing'][0]['name'],'보고기간')
        self.assertEqual(len(db.list_messages(chat['id'])),2)
        prepared = boards_api.prepare_template_chat(t['id'],boards_api.TemplateChatIn(
            chat_id=chat['id'],message='변조된 요청',acting_user_id='7',version=1,
            question_id=question['question_id'],inputs={'보고기간':'2월'}))
        self.assertEqual(prepared['message'],'영업 실적 보고서 만들어줘')
        self.assertFalse(prepared['save_user'])
        self.assertEqual(prepared['template']['inputs'],{'보고기간':'2월'})
        with self.assertRaises(HTTPException): boards_api.prepare_template_chat(t['id'],boards_api.TemplateChatIn(
            chat_id=chat['id'],message='요청',acting_user_id='12',question_id=question['question_id']))

    async def test_generation_fills_real_office_files_for_three_formats(self):
        docgen.init_docgen()
        async def smooth(text): yield text
        for fmt in ('docx','xlsx','pptx'):
            with self.subTest(fmt=fmt):
                info = template_files.save(office(fmt),'source.'+fmt,'',[])
                t = boards_api.create_template(boards_api.TemplateIn(template={'name':'보고서','format':fmt,'mode':'fill',
                    'file_id':info['id'],'groups':[],'inputs':[{'name':'보고기간','required':True}], 'source':'general'}))['template']
                prep = boards_api.prepare_template_run(t['id'],'7',{'보고기간':'2월'})
                chat = db.create_chat('filled','사내')
                generated = {'values':{'분석':'제공된 실적 분석','매출':10,'실적':[{'품목':'A','매출':10}], '보고기간':'잘못된 값'}}
                with patch.object(docgen,'_llm_json',new=AsyncMock(return_value=generated)), \
                     patch.object(docgen,'collection_material',return_value=''),patch.object(docgen,'_smooth',smooth):
                    d = prep['docgen']
                    events = [e async for e in docgen.run_docgen(chat,'2월 매출은 10입니다. 양식을 채워줘.',fmt,d['topic'],d['style'],d['length'],
                        'general','7',d['instruction'],template=prep['template'])]
                self.assertEqual(events[-1]['type'],'done',events[-1])
                meta = next(e for e in events if e['type']=='doc_meta')
                output = docgen.build_file(meta['doc_id'])
                self.assertTrue(output.is_file())
                self.assertEqual(docgen.get_doc(meta['doc_id'])['template']['file_id'],info['id'])
                self.assertEqual(docgen.list_pages(meta['doc_id'])[0]['data']['template_values']['보고기간'],'2월')


class TemplateReviewFixTests(BoardsBase):
    """2026-09-15 점검 수정: 슬롯 공백 무시, 선택 슬롯 빈칸 허용, 요청은 재료로 / review fixes: slot spaces, optional slots, request as material"""

    async def test_slot_names_ignore_spaces_inside_the_braces(self):
        from docx import Document
        buf = io.BytesIO()
        doc = Document()
        doc.add_paragraph('기간: {{ 보고기간 }} / {{ 분석 }} 끝')
        doc.save(buf)
        info = template_files.save(buf.getvalue(), '공백.docx', '', [])
        self.assertEqual(info['fields'], ['보고기간', '분석'])
        output = docgen.GENERATED_DIR / 'spaces.docx'
        template_files.fill(info['id'], {'보고기간': '2월', '분석': '계획'}, output)
        self.assertEqual(Document(output).paragraphs[0].text, '기간: 2월 / 계획 끝')

    async def test_optional_slots_stay_blank_and_are_listed_but_an_empty_model_result_fails(self):
        docgen.init_docgen()

        async def smooth(text):
            yield text
        info = template_files.save(office('docx'), 'source.docx', '', [])
        t = boards_api.create_template(boards_api.TemplateIn(template={'name': '보고서', 'format': 'docx', 'mode': 'fill',
            'file_id': info['id'], 'groups': [], 'inputs': [{'name': '보고기간', 'required': True}], 'source': 'general'}))['template']
        prep = boards_api.prepare_template_run(t['id'], '7', {'보고기간': '2월'})
        self.assertEqual(prep['template']['required'], ['보고기간'])
        d = prep['docgen']
        chat = db.create_chat('blank', '사내')
        # 분석만 채우고 반복 표(실적)는 못 채움 → 빈 목록으로 두고 안내 / only 분석 filled: the repeat list stays empty and is listed
        with patch.object(docgen, '_llm_json', new=AsyncMock(return_value={'values': {'분석': '내용'}})), \
             patch.object(docgen, 'collection_material', return_value=''), patch.object(docgen, '_smooth', smooth):
            events = [e async for e in docgen.run_docgen(chat, '양식을 채워줘', 'docx', d['topic'], d['style'], d['length'],
                                                          'general', '7', d['instruction'], template=prep['template'])]
        self.assertEqual(events[-1]['type'], 'done', events[-1])
        meta = next(e for e in events if e['type'] == 'doc_meta')
        values = docgen.list_pages(meta['doc_id'])[0]['data']['template_values']
        self.assertEqual((values['보고기간'], values['분석'], values['실적']), ('2월', '내용', []))
        text = ''.join(e['text'] for e in events if e['type'] == 'token')
        self.assertIn('비워 둔 항목: 실적', text)
        self.assertTrue(docgen.build_file(meta['doc_id']).is_file())
        # 모델이 아무 값도 못 만들면 빈 양식 대신 실패 / nothing generated at all → failure instead of an empty form
        with patch.object(docgen, '_llm_json', new=AsyncMock(return_value={'values': {}})), \
             patch.object(docgen, 'collection_material', return_value=''), patch.object(docgen, '_smooth', smooth):
            events = [e async for e in docgen.run_docgen(chat, '양식을 채워줘', 'docx', d['topic'], d['style'], d['length'],
                                                          'general', '7', d['instruction'], template=prep['template'])]
        self.assertEqual(events[-1]['type'], 'error')
        self.assertIn('만들지 못했습니다', events[-1]['detail'])

    async def test_chat_request_reaches_the_prompts_outside_the_hint_cap(self):
        docgen.init_docgen()

        async def smooth(text):
            yield text
        t = boards.add_template(boards_api._validate_template({'name': '보고', 'format': 'docx', 'sections': ['핵심'], 'length': 2}))
        prep = boards_api.prepare_template_run(t['id'], '7', {})
        prep['template']['request'] = '2월 영업 실적으로 작성해줘'
        chat = db.create_chat('request', '사내')
        seen = []

        async def capture(state, user, system, tier='main'):
            seen.append(user)
            return None
        with patch.object(docgen, '_llm_json', new=capture), patch.object(docgen, 'collection_material', return_value=''), \
             patch.object(docgen, 'build_file'), patch.object(docgen, '_smooth', smooth):
            d = prep['docgen']
            events = [e async for e in docgen.run_docgen(chat, '2월 영업 실적으로 작성해줘', 'docx', d['topic'], d['style'], d['length'],
                                                          'general', '7', d['instruction'], template=prep['template'])]
        self.assertEqual(events[-1]['type'], 'done')
        self.assertTrue(seen and all('[이번 작성 요청] 2월 영업 실적으로 작성해줘' in u for u in seen))
        self.assertNotIn('request', docgen.get_doc(next(e for e in events if e['type'] == 'doc_meta')['doc_id'])['template'])

