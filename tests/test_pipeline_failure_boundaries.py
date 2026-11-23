"""Failure propagation and artifact readiness. Isolated DB, stubbed LLM/network/builders."""
import tempfile
import unittest
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch, AsyncMock

from db_fixture import isolate_db
from app import flows, docgen, artifact_execution, smart_actions_api
from app.agents import AGENT_REGISTRY


async def collect(stream):
    return [event async for event in stream]


class FailureBoundaries(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        self.stack.enter_context(patch('app.llm.generate', side_effect=AssertionError('unexpected LLM')))

    async def test_data_failure_and_denial_stay_failed(self):
        for status in ('failed', 'blocked', 'not_found'):
            with self.subTest(status=status), patch.dict(AGENT_REGISTRY['data'], {
                'run': AsyncMock(return_value={'status': status, 'text': '', 'fail_reason': 'reason', 'extras': {}})
            }):
                result = await flows._run_step_node({'agent': 'data', 'resources': []}, 'q', [], None, [])
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['text'], 'reason')

    def test_groupware_partial_failure_preserves_per_resource_status(self):
        with patch.object(flows.groupware, 'get_widgets', return_value={}), patch('app.smart_actions.get_config', return_value={}), \
             patch.dict(smart_actions_api.INFO_DISPATCH, {'mail.info.inbox': lambda a: [],
                 'mail.info.unread': lambda a: (_ for _ in ()).throw(RuntimeError('lookup failed'))}):
            result = flows._run_groupware_node({'resources': ['mail.info.inbox', 'mail.info.unread']}, 'q', 'mail')
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['extras']['partial'])
        self.assertEqual([r['status'] for r in result['extras']['resource_results']], ['done', 'failed'])
        self.assertIn('조회에 실패', result['text'])

    def test_automation_denied_resource_is_partial_failure(self):
        items = {'a': {'node': 'allowed', 'kind': 'info', 'ns': 'email', 'sec_label': 'mail', 'label': 'a'},
                 'b': {'node': 'denied', 'kind': 'info', 'ns': 'email', 'sec_label': 'mail', 'label': 'b'}}
        # 이메일 조회는 M코스메틱 이메일 에이전트 스토어(2026-09-28) / email reads go through the M Cosmetic Email Agent store
        with patch.dict(flows.AUTO_ITEM_INDEX, items), patch('app.mcmail.lookup', return_value=({}, 'ok', '')), \
             patch('app.mcmail.fallback_answer', return_value='ok'):
            result = flows._run_auto_node({'resources': ['a', 'b']}, 'q', 'auto', {'nodes': {'allowed': 1}})
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['extras']['partial'])
        self.assertIn('권한이 없어', result['text'])

    async def test_failed_workflow_blocks_file_and_delivery_but_keeps_partial_text(self):
        for mode in ('data', 'groupware'):
            with self.subTest(mode=mode):
                flow = {'id': 'f', 'name': 'f', 'docgen': {'format': 'pdf'}, 'stages': [{'nodes': [
                    {'agent': mode, 'resources': []}, {'agent': 'groupware', 'resources': ['mail.action.compose']}]}]}
                async def node(n, *a):
                    if n['resources']:
                        return {'status': 'done', 'text': 'send', 'sends': [{'query': 'send'}]}
                    return {'status': 'failed', 'text': 'partial content: one lookup failed',
                            'extras': {'partial': True}}
                captured = []
                async def tokens(messages, **kw):
                    captured.append(str(messages))
                    yield 'partial report'
                async def smooth(text):
                    yield text
                with patch.object(flows, '_resolve_eff', return_value=None), \
                     patch.object(flows.db, 'add_message', return_value='audit_message'), \
                     patch.object(flows, '_build_context', return_value=[{'role': 'user', 'content': 'q'}]), \
                     patch.object(flows, '_run_step_node', side_effect=node), patch.object(flows, '_flow_stages', return_value=[]), \
                     patch.object(flows, '_flow_sources', return_value=None), patch.object(flows, '_astream', tokens), \
                     patch.object(flows, '_smooth', smooth), patch.object(flows, '_flow_send_confirm', AsyncMock()) as send:
                    events = await collect(flows.run_flow(flow, {'id': 'audit'}, 'q'))
                send.assert_not_called()
                self.assertFalse(any(e.get('docgen') or e['type'] == 'confirm' for e in events))
                self.assertIn('partial content', str(captured))

    async def test_file_build_failure_never_registers_artifact_including_mp4(self):
        for fmt in ('xlsx', 'mp4'):
            with self.subTest(fmt=fmt), ExitStack() as st:
                st.enter_context(patch.object(docgen, '_create_doc', return_value='doc_audit'))
                status = st.enter_context(patch.object(docgen, '_set_status'))
                st.enter_context(patch.object(docgen, '_add_page'))
                st.enter_context(patch.object(docgen, '_record_template_use'))
                st.enter_context(patch.object(docgen, 'collection_material', return_value=''))
                st.enter_context(patch.object(docgen, '_gen_sheet', AsyncMock(return_value={'sheet_name': 'audit', 'columns': [], 'rows': []})))
                st.enter_context(patch.object(docgen, '_gen_outline', AsyncMock(return_value={'doc_title': 'audit', 'pages': [{'layout': 'title'}]})))
                st.enter_context(patch.object(docgen, '_gen_page', AsyncMock(return_value={'title': 'audit', 'html': '', 'fields': {}})))
                build = st.enter_context(patch.object(docgen, 'build_file', side_effect=RuntimeError('build failed')))
                st.enter_context(patch.object(docgen.db, 'add_message', return_value='audit'))
                st.enter_context(patch.object(artifact_execution.store, 'save'))
                run = {'id': 'audit', 'snapshot': {}}
                cfg = {'message': 'q', 'format': fmt, 'topic': 'audit', 'style': 'blue', 'length': 5, 'source': 'general', 'save_user': False}
                events = await collect(artifact_execution.document_events({'id': 'audit'}, cfg, run))
                build.assert_called_once()
                self.assertEqual(status.call_args.args[1], 'failed')
                self.assertNotIn('artifact', run['snapshot'])
                self.assertTrue(any(e['type'] == 'error' for e in events))
                self.assertFalse(any(e['type'] == 'done' for e in events))

    async def test_cached_document_build_failure_clears_old_artifact(self):
        run = {'id': 'audit', 'snapshot': {'artifact': {'id': 'doc_audit'}}}
        with patch.object(docgen, 'get_doc', return_value={'status': 'done'}), \
             patch.object(docgen, 'build_file', side_effect=RuntimeError('build failed')), \
             patch.object(artifact_execution.store, 'save'):
            events = await collect(artifact_execution.document_events({'id': 'audit'}, {'source': 'context'}, run))
        self.assertNotIn('artifact', run['snapshot'])
        self.assertEqual(events[-1]['type'], 'error')

    def test_partial_file_is_not_cached_after_builder_failure(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(docgen, 'GENERATED_DIR', Path(directory)), \
             patch.object(docgen, 'get_doc', return_value={'filename': 'audit.pdf', 'format': 'pdf'}), \
             patch.object(docgen, 'list_pages', return_value=[{}]):
            def broken(doc, pages, out):
                out.write_bytes(b'partial')
                raise RuntimeError('encoder failed')
            with patch.object(docgen, '_build_pdf', side_effect=broken):
                with self.assertRaises(RuntimeError):
                    docgen.build_file('doc_audit')
            self.assertFalse((Path(directory) / 'doc_audit' / 'audit.pdf').exists())
            with patch.object(docgen, '_build_pdf', side_effect=lambda d, p, out: out.write_bytes(b'complete')) as build:
                result = docgen.build_file('doc_audit')
            build.assert_called_once()
            self.assertEqual(result.read_bytes(), b'complete')

    def test_atomic_xlsx_build_produces_a_readable_workbook(self):
        from openpyxl import load_workbook
        doc = {'filename': 'audit.xlsx', 'format': 'xlsx', 'style': 'blue'}
        pages = [{'data': {'sheet': {'sheet_name': '검증', 'columns': ['수량'], 'rows': [[10]]}}}]
        with tempfile.TemporaryDirectory() as directory, patch.object(docgen, 'GENERATED_DIR', Path(directory)), \
             patch.object(docgen, 'get_doc', return_value=doc), patch.object(docgen, 'list_pages', return_value=pages):
            result = docgen.build_file('doc_audit')
            workbook = load_workbook(result)
            try:
                self.assertEqual(workbook.active['A2'].value, 10)
            finally:
                workbook.close()
            self.assertEqual([p.name for p in result.parent.iterdir()], ['audit.xlsx'])


if __name__ == '__main__':
    unittest.main()
