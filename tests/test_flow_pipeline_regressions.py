"""Workflow input propagation and checkpoint recovery; isolated DB, no external calls."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

import test_flow_stage_gate as gates
from app import artifact_execution, flows, execution_store as store
from app.agents import AGENT_REGISTRY


class WorkflowRecoveryTests(unittest.IsolatedAsyncioTestCase):
    setUp = gates.StageGateTests.setUp
    stub_flow = gates.StageGateTests.stub_flow
    stub_docgen = gates.StageGateTests.stub_docgen
    make_run = gates.StageGateTests.make_run
    recording_worker = staticmethod(gates.StageGateTests.recording_worker)

    async def test_review_answer_reaches_rerun_query_and_context(self):
        flow = gates.two_stage_flow()
        flow['stages'] = flow['stages'][:1]
        calls = []
        self.stub_flow(self.recording_worker(calls), review=gates.LLM_QUESTIONS)
        run = self.make_run(flow)
        await gates.collect(artifact_execution.workflow_run(flow, self.chat, 'q', '', run))
        run = store.get(run['id'])
        artifact_execution.resume_workflow(run, {'kind': 'flow_question', 'answers': {'q1': 'REVIEW_SENTINEL'}})
        run = store.get(run['id'])
        await gates.collect(artifact_execution.workflow_run(run['snapshot']['flow'], self.chat, 'q', '', run))
        self.assertEqual(len(calls), 2)
        self.assertIn('REVIEW_SENTINEL', calls[-1]['message'])
        self.assertIn('REVIEW_SENTINEL', json.dumps(calls[-1]['context']))
        self.assertEqual(store.get(run['id'])['state'], 'completed')

    async def test_interrupted_stage_file_is_retried_before_next_stage_gate(self):
        flow = gates.two_stage_flow()
        flow['stages'][0]['docgen'] = {'format': 'docx', 'instruction': ''}
        calls = []
        self.stub_flow(self.recording_worker(calls))

        async def interrupt(*args, **kwargs):
            raise asyncio.CancelledError()
            yield {}

        run = self.make_run(flow)
        with patch.object(artifact_execution, 'document_events', interrupt), self.assertRaises(asyncio.CancelledError):
            await gates.collect(artifact_execution.workflow_run(flow, self.chat, 'q', '', run))
        saved = store.get(run['id'])
        self.assertEqual(saved['state'], 'interrupted')
        self.assertEqual(saved['snapshot']['cursor'], 0)
        doc_calls = self.stub_docgen()
        events = await gates.collect(artifact_execution.workflow_run(saved['snapshot']['flow'], self.chat, 'q', '', saved))
        self.assertEqual(len(doc_calls), 1)
        self.assertEqual(len(calls), 1)  # no repeated task and no next-stage execution
        self.assertEqual(len(self.astream), 1)  # reuse the persisted answer
        self.assertIn('flow_gate', [ev['type'] for ev in events])
        saved = store.get(run['id'])
        self.assertEqual(saved['state'], 'needs_input')
        self.assertEqual(saved['snapshot']['cursor'], 1)
        artifact_execution.resume_workflow(saved, {'kind': 'flow_gate', 'action': 'run'})
        saved = store.get(run['id'])
        await gates.collect(artifact_execution.workflow_run(saved['snapshot']['flow'], self.chat, 'q', '', saved))
        self.assertEqual(len(calls), 2)
        self.assertEqual(store.get(run['id'])['state'], 'completed')

    async def test_nameless_answer_is_reextracted_and_missing_value_asked_again(self):
        flow = gates.two_stage_flow()
        flow['stages'] = [{'nodes': [{'agent': 'knowledge', 'resources': [],
                                     'instruction': '계약 확인', 'extract_prompt': '고객사와 계약 연도'}]}]
        # Keep the real task runner; stub only its agent and external dependencies.
        actual_runner = flows._run_step_node
        self.stub_flow(actual_runner)
        agent = AsyncMock(return_value={'status': 'answer', 'text': '결과', 'extras': {}})
        self.stack.enter_context(patch.dict(AGENT_REGISTRY['knowledge'], {'run': agent}))
        self.generate.side_effect = [RuntimeError('offline'), {'values': {'고객사': 'A사', '계약 연도': None}}]
        run = self.make_run(flow)
        await gates.collect(artifact_execution.workflow_run(flow, self.chat, 'q', '', run))
        saved = store.get(run['id'])
        unknown = 'in_1_' + flows._EXTRACT_UNKNOWN
        artifact_execution.resume_workflow(saved, {'kind': 'flow_question', 'answers': {unknown: 'A사'}})
        saved = store.get(run['id'])
        events = await gates.collect(artifact_execution.workflow_run(saved['snapshot']['flow'], self.chat, 'q', '', saved))
        agent.assert_not_awaited()
        self.assertIn('A사', self.generate.call_args.args[0])
        self.assertEqual(store.get(run['id'])['state'], 'needs_input')
        card = next(ev['card'] for ev in events if ev['type'] == 'flow_question')
        self.assertEqual(card['items'][0]['id'], 'in_1_계약 연도')
        saved = store.get(run['id'])
        artifact_execution.resume_workflow(saved, {'kind': 'flow_question', 'answers': {'in_1_계약 연도': '2026'}})
        saved = store.get(run['id'])
        self.generate.side_effect = AssertionError('known fields must not be re-extracted')
        await gates.collect(artifact_execution.workflow_run(saved['snapshot']['flow'], self.chat, 'q', '', saved))
        agent.assert_awaited_once()
        self.assertIn('계약 연도: 2026', agent.await_args.args[0])
        self.assertEqual(store.get(run['id'])['state'], 'completed')

    async def test_nameless_answer_is_used_as_is_when_reextraction_fails(self):
        # 경량 모델이 계속 실패해도 이름 없는 질문 카드는 한 번뿐 — 답을 그대로 값으로 쓰고 진행한다(2026-09-29 리뷰, 종전 동작)
        # With the lite model failing throughout, the nameless card appears once; the answer is used as the value (review)
        flow = gates.two_stage_flow()
        flow['stages'] = [{'nodes': [{'agent': 'knowledge', 'resources': [],
                                     'instruction': '계약 확인', 'extract_prompt': '고객사와 계약 연도'}]}]
        self.stub_flow(flows._run_step_node)
        agent = AsyncMock(return_value={'status': 'answer', 'text': '결과', 'extras': {}})
        self.stack.enter_context(patch.dict(AGENT_REGISTRY['knowledge'], {'run': agent}))
        self.generate.side_effect = RuntimeError('lite model down')
        run = self.make_run(flow)
        await gates.collect(artifact_execution.workflow_run(flow, self.chat, 'q', '', run))
        saved = store.get(run['id'])
        unknown = 'in_1_' + flows._EXTRACT_UNKNOWN
        artifact_execution.resume_workflow(saved, {'kind': 'flow_question', 'answers': {unknown: 'A사, 2026'}})
        saved = store.get(run['id'])
        events = await gates.collect(artifact_execution.workflow_run(saved['snapshot']['flow'], self.chat, 'q', '', saved))
        self.assertNotIn('flow_question', [ev['type'] for ev in events])   # 같은 카드가 되풀이되지 않는다 / no repeated card
        agent.assert_awaited_once()
        self.assertIn(flows._EXTRACT_UNKNOWN + ': A사, 2026', agent.await_args.args[0])
        self.assertEqual(store.get(run['id'])['state'], 'completed')

    async def test_external_tool_gets_the_original_request_not_notes_or_answers(self):
        # 실행 카드 추가 지시·검수 답변은 입력값 추출과 작업 질의에만 쓰고, 도구의 {{input.question}} 에는 원래 요청만 간다(2026-09-29 리뷰)
        # The run-card note and review answers feed extraction and task queries only; {{input.question}} stays the request
        conn = {'id': 'cn_order', 'name': '주문 API', 'kind': 'read', 'enabled': True, 'description': '주문 조회',
                'api': {'url': 'https://erp.invalid/order?qty={{input.qty}}&note={{input.question}}',
                        'input_docs': [{'name': 'qty', 'description': '수량', 'example': '1'}]}}
        flow = gates.two_stage_flow()
        flow['stages'][1]['nodes'] = [{'agent': 'api', 'resources': ['cn_order'], 'instruction': '', 'prompt': ''}]
        real = flows._run_step_node

        async def worker(node, message, context, eff, prior, actor=''):
            if node['agent'] == 'api':
                return await real(node, message, context, eff, prior, actor)
            return {'status': 'done', 'label': '1단계 작업', 'text': '1단계 결과'}
        self.stub_flow(worker)
        extract_prompts = []

        def fake_generate(prompt, **kw):
            if '입력값 추출기' in (kw.get('system') or ''):
                extract_prompts.append(prompt)
                return {'inputs': {}}
            return {'questions': []}
        self.generate.side_effect = fake_generate
        call = AsyncMock(return_value={'ok': True, 'result_text': '주문 10건', 'outputs': {}, 'status': 200})
        self.stack.enter_context(patch.object(flows, '_api_candidates', return_value=([conn], None)))
        self.stack.enter_context(patch.object(flows, 'call_connector', call))
        self.stack.enter_context(patch('app.connectors.get_connector', return_value=conn))
        run = self.make_run(flow)
        await gates.collect(artifact_execution.workflow_run(flow, self.chat, 'q', '', run))
        artifact_execution.resume_workflow(store.get(run['id']), {'kind': 'flow_gate', 'action': 'run', 'note': '서울만'})
        run = store.get(run['id'])
        events = await gates.collect(artifact_execution.workflow_run(run['snapshot']['flow'], self.chat, 'q', '', run))
        card = next(ev['card'] for ev in events if ev['type'] == 'flow_question')      # qty 를 묻는다 / asks for qty
        self.assertEqual([i['id'] for i in card['items']], ['in_1_qty'])
        self.assertIn('(추가 지시: 서울만)', extract_prompts[-1])                        # 추출에는 지시가 간다 / extraction sees the note
        artifact_execution.resume_workflow(store.get(run['id']), {'kind': 'flow_question', 'answers': {'in_1_qty': '10'}})
        run = store.get(run['id'])
        await gates.collect(artifact_execution.workflow_run(run['snapshot']['flow'], self.chat, 'q', '', run))
        call.assert_awaited_once()
        self.assertEqual(call.await_args.args[1], 'q')                                 # 원래 요청만 / the original request only
        self.assertEqual(call.await_args.args[3], {'qty': '10'})
        self.assertEqual(store.get(run['id'])['state'], 'completed')

    async def test_review_answers_reach_only_the_tasks_their_question_names(self):
        # 한 단계에 작업이 둘이고 질문도 작업마다 하나 — 답은 그 질문이 가리킨 작업의 재실행 질의·맥락에만 실린다(2026-09-29 리뷰)
        # Two tasks, one question each: an answer rides only in the query and context of the task its question names (review)
        flow = gates.two_stage_flow()
        flow['stages'] = [{'nodes': [{'agent': 'data', 'resources': [], 'instruction': '매출'},
                                     {'agent': 'data', 'resources': [], 'instruction': '재고'}], 'answer_prompt': ''}]
        review = {'questions': [
            {'id': 'q1', 'label': '기간', 'question': '매출 기간?', 'kind': 'text', 'task_ids': ['stage1_1']},
            {'id': 'q2', 'label': '창고', 'question': '재고 창고?', 'kind': 'text', 'task_ids': ['stage1_2']}]}
        calls = []
        self.stub_flow(self.recording_worker(calls), review=review)
        run = self.make_run(flow)
        await gates.collect(artifact_execution.workflow_run(flow, self.chat, 'q', '', run))
        artifact_execution.resume_workflow(store.get(run['id']),
                                           {'kind': 'flow_question', 'answers': {'q1': 'SALES_ANS', 'q2': 'STOCK_ANS'}})
        calls.clear()
        run = store.get(run['id'])
        await gates.collect(artifact_execution.workflow_run(run['snapshot']['flow'], self.chat, 'q', '', run))
        by_key = {c['key']: c for c in calls}
        self.assertEqual(set(by_key), {'매출', '재고'})
        self.assertIn('SALES_ANS', by_key['매출']['message'])
        self.assertNotIn('STOCK_ANS', by_key['매출']['message'])
        self.assertIn('STOCK_ANS', by_key['재고']['message'])
        self.assertNotIn('SALES_ANS', json.dumps(by_key['재고']['context'], ensure_ascii=False))
        self.assertEqual(store.get(run['id'])['state'], 'completed')


class WorkflowInputTests(unittest.IsolatedAsyncioTestCase):
    async def test_web_receives_previous_stage_even_on_grounding_fallback(self):
        context = [{'role': 'assistant', 'content': 'PRIOR_PRODUCT_719'}]
        node = {'agent': 'web', 'instruction': '앞 단계 상품을 검색'}
        with patch.object(flows.llm, 'generate_grounded_meta', return_value={'text': 'result'}) as ground:
            await flows._run_step_node(node, '검색', context, None, [])
            self.assertIn('PRIOR_PRODUCT_719', str(ground.call_args.args[0]))
        with patch.object(flows.llm, 'generate_grounded_meta', side_effect=flows.llm.GroundingUnavailableError()), \
                patch.object(flows.llm, 'generate', return_value='result') as plain:
            await flows._run_step_node(node, '검색', context, None, [])
            self.assertIn('PRIOR_PRODUCT_719', str(plain.call_args.args[0]))

    def test_extraction_includes_fixed_task_values_and_requires_known_missing_names(self):
        node = {'agent': 'data', 'instruction': '2026년 A사의 계약을 조회', 'extract_prompt': '고객사, 계약 연도'}
        with patch.object(flows.llm, 'generate', return_value={'values': {'고객사': 'A사', '계약 연도': '2026'}}) as model:
            found, pending = flows._extract_required(node, '실행', [])
        self.assertIn('[작업 지침]\n2026년 A사의 계약을 조회', model.call_args.args[0])
        self.assertIsNone(pending)
        with patch.object(flows.llm, 'generate', side_effect=AssertionError):
            _, pending = flows._extract_required({**node, '_required_inputs': ['고객사', '계약 연도']},
                                                '실행', [], {'고객사': 'A사'})
        self.assertEqual(pending['extras']['missing_inputs'], ['계약 연도'])

    async def test_groupware_maps_extracted_search_and_date_to_actual_dispatch(self):
        from app import smart_actions_api as saa
        node = {'agent': 'groupware', 'resources': ['mail.info.search', 'calendar.info.range'],
                'instruction': '메일과 일정 조회', 'extract_prompt': '검색어와 조회 날짜'}
        mail, calendar = Mock(return_value=[]), Mock(return_value=[])
        with patch.object(flows.llm, 'generate', side_effect=[
                {'values': {'검색어': '계약719', '조회 날짜': '내일'}},
                {'args': {'mail.info.search': {'q': '계약719'}, 'calendar.info.range': {'day': 1}}}]), \
                patch('app.groupware.get_widgets', return_value={}), \
                patch('app.smart_actions.get_config', return_value={}), \
                patch.dict(saa.INFO_DISPATCH, {'mail.info.search': mail, 'calendar.info.range': calendar}):
            result = await flows._run_step_node(node, '조회', [], None, [])
        self.assertEqual(result['status'], 'done')
        mail.assert_called_once_with({'q': '계약719'})
        calendar.assert_called_once_with({'day': 1})
        self.assertNotIn('args', node)

    async def test_groupware_does_not_broaden_query_when_mapping_fails(self):
        # 검색어를 매핑하지 못하면 전체 조회로 넓히지 않고 질문 카드로 묻는다(2026-09-29 리뷰: 실패 대신 needs_input)
        # An unmapped search term is never broadened into a full listing; it is asked through the question card (review)
        node = {'agent': 'groupware', 'resources': ['mail.info.search'], 'extract_prompt': '검색어'}
        with patch.object(flows.llm, 'generate', side_effect=[{'values': {'검색어': '계약719'}}, {'args': {}}]), \
                patch.object(flows, '_run_groupware_node') as run:
            result = await flows._run_step_node(node, '조회', [], None, [])
        self.assertEqual(result['status'], 'needs_input')
        self.assertEqual(result['extras']['missing_inputs'], ['메일 검색어'])
        self.assertEqual(result['extras']['inputs'], {'검색어': '계약719'})
        run.assert_not_called()

    async def test_groupware_date_and_duration_fall_back_to_defaults(self):
        # 날짜·시간은 기본값이 있다(INFO_DISPATCH 와 같음) — 못 찾아도, 매핑 LLM 이 실패해도 작업을 실패시키지 않는다(2026-09-29 리뷰)
        # Date and duration have defaults (as in INFO_DISPATCH): neither a missing value nor a failed mapping fails the task
        from app import smart_actions_api as saa
        node = {'agent': 'groupware', 'resources': ['calendar.info.range', 'calendar.info.free'],
                'instruction': '일정 확인', 'extract_prompt': '고객사 이름'}
        for mapping in ({'args': {'calendar.info.range': {'day': None}, 'calendar.info.free': {'day': 1, 'minutes': None}}},
                        RuntimeError('lite model down')):
            with self.subTest(mapping=type(mapping).__name__):
                rng, free = Mock(return_value=[]), Mock(return_value=[])
                with patch.object(flows.llm, 'generate', side_effect=[{'values': {'고객사': 'A사'}}, mapping]), \
                        patch('app.groupware.get_widgets', return_value={}), \
                        patch('app.smart_actions.get_config', return_value={}), \
                        patch.dict(saa.INFO_DISPATCH, {'calendar.info.range': rng, 'calendar.info.free': free}):
                    result = await flows._run_step_node(node, '조회', [], None, [])
                self.assertEqual(result['status'], 'done')
                rng.assert_called_once_with({'day': 0})
                free.assert_called_once_with({'day': 1 if isinstance(mapping, dict) else 0, 'minutes': 60})

    def test_groupware_answer_under_the_description_needs_no_mapping(self):
        # 질문 카드 답변은 인자 설명 이름('메일 검색어')으로 돌아온다 — 재실행 때 LLM 없이 그 인자에 들어간다
        # A question-card answer comes back under the argument description and binds without the LLM on the re-run
        node = {'agent': 'groupware', 'resources': ['mail.info.search']}
        with patch.object(flows.llm, 'generate') as model:
            bound, pending = flows._groupware_inputs(node, '조회', {'메일 검색어': '계약719', '고객사': 'A사'}, [])
        model.assert_not_called()
        self.assertIsNone(pending)
        self.assertEqual(bound['args'], {'mail.info.search': {'q': '계약719'}})
        self.assertNotIn('args', node)   # 원래 노드는 그대로 / the original node is untouched


if __name__ == '__main__':
    unittest.main()
