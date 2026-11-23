"""요구사항/대상 선택/계획 계약과 기존 카드 재개. 외부 LLM·API 호출 없음."""
import copy
import json
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch
from db_fixture import isolate_db
from app import capability_catalog as catalog, request_planning as rp, requirements, decisions, intent
from app.execution import PlanError


def req(rid='r1', kind='retrieve', **kw):
    return {'id': rid, 'kind': kind, 'request': '구매 데이터 조회', 'source_hint': '',
            'constraints': ['2026년 2월'], 'depends_on': [], **kw}


def spec(*items):
    return {'version': 1, 'query': '자료를 취합해줘', 'items': list(items or [req()])}


def conn(cid, name, **kw):
    return {'id': cid, 'name': name, 'description': 'ERP 구매 데이터 조회', 'kind': 'read',
            'api': {'url': 'https://example.invalid/purchases', 'auth': {'type': 'bearer', 'key': 'NEVER_INCLUDE_SECRET'}}, **kw}


CONNECTORS = [conn('cn_one', 'ERP1 구매'), conn('cn_two', 'ERP2 구매')]


def routing(**targets):
    return {rid: {'candidates': ids, 'selected': ids[0] if len(ids) == 1 else None, 'reason': '업무 범위 일치'}
            for rid, ids in targets.items()}


def raw_plan(agent='connector', **step_kw):
    step = {'id': 's1', 'agent': agent, 'task': '조회', 'depends_on': [], 'inputs': {}, **step_kw}
    return {'version': 3, 'query': '조회', 'steps': [step], 'send_query': '', 'document': None,
            'clarify': None, 'web': False, 'use_previous': False, 'coverage': {'r1': ['s1']}}


def attached(raw=None, request=None, routes=None):
    return {**(raw or raw_plan(connector_id='cn_one')), 'request_spec': request or spec(),
            'routing': routes or routing(r1=['connector:cn_one']), 'planning_pending': False}


class PlanningTests(unittest.TestCase):
    def test_requirements_reject_duplicate_and_cyclic_dependencies(self):
        for value in (spec(req(), req()), spec(req(depends_on=['r2']), req('r2', depends_on=['r1'])),
                      spec(req(depends_on=['missing']))):
            with self.assertRaises(PlanError):
                requirements.validate(value)

    def test_catalog_exposes_name_and_schema_but_not_credentials(self):
        rows = catalog.build(CONNECTORS)
        self.assertIn('ERP1 구매', json.dumps(rows, ensure_ascii=False))
        self.assertNotIn('NEVER_INCLUDE_SECRET', json.dumps(rows))
        self.assertNotIn('https://example.invalid', json.dumps(rows))
        self.assertIn('input_schema', rows[-1])

    def test_catalog_filters_scope_permissions_and_disabled_tools(self):
        rows = catalog.build([conn('cn_off', 'off', enabled=False)], ['work'],
                             {'nodes': {'agent_edu': 1}, 'read': {'p_data': False, 'p_know': False}})
        self.assertEqual({r['id'] for r in rows}, {'agent:work:edu', 'delivery:groupware'})

    def test_catalog_includes_only_authorized_selected_resources(self):
        with patch('app.catalog.allowed_tables', return_value={'payroll'}):
            rows = catalog.build(eff={'read': {'p_data': True, 'p_know': False}, 'nodes': {}},
                                 scope_files={'data_tables': ['payroll', 'secret_table']})
        data = next(r for r in rows if r['id'] == 'agent:data')
        self.assertEqual(data['selected_resources'], {'data_tables': ['payroll']})
        with patch('app.catalog.allowed_tables', return_value=set()):
            rows = catalog.build(eff={'read': {'p_data': True, 'p_know': False}, 'nodes': {}},
                                 scope_files={'data_tables': ['secret_table']})
        self.assertNotIn('agent:data', {r['id'] for r in rows})

    def test_routes_preserve_ambiguous_systems_and_respect_explicit_source(self):
        raw = {'routes': [{'requirement_id': 'r1', 'candidates': ['connector:cn_one', 'connector:cn_two']}]}
        routes = rp._routes(raw, spec(), catalog.build(CONNECTORS))
        self.assertIsNone(routes['r1']['selected'])
        routes = rp._routes(raw, spec(req(source_hint='ERP2')), catalog.build(CONNECTORS))
        self.assertEqual(routes['r1']['selected'], 'connector:cn_two')

    def test_routing_rejects_invented_target_and_wrong_operation(self):
        for target in ('connector:unknown', 'agent:work:edu'):
            raw = {'routes': [{'requirement_id': 'r1', 'candidates': [target]}]}
            with self.assertRaises(PlanError):
                rp._routes(raw, spec(req(kind='action')), catalog.build(CONNECTORS))

    def test_coverage_rejects_omission_wrong_system_and_unrequested_tasks(self):
        a = attached(); a['coverage'] = {}
        b = attached(); b['steps'][0]['connector_id'] = 'cn_two'
        c = attached(); c['steps'].append({**c['steps'][0], 'id': 'extra'})
        d = attached(); d['send_query'] = '나에게 보내줘'
        for value in (a, b, c, d):
            with self.assertRaises(PlanError):
                decisions.validate(value, connector_ids={'cn_one', 'cn_two'})

    def test_plan_repair_cannot_rewrite_requirements_or_selection(self):
        request = spec()
        bad = raw_plan(connector_id='cn_two')
        good = raw_plan(connector_id='cn_one')
        good['request_spec'] = spec(req(request='바뀐 요구사항'))
        with patch.object(rp.llm, 'generate', side_effect=[bad, good]) as model:
            result = rp.plan(request, routing(r1=['connector:cn_one']), [], catalog.build(CONNECTORS))
        self.assertEqual(model.call_count, 2)
        self.assertEqual(result['request_spec'], request)
        self.assertEqual(result['steps'][0]['connector_id'], 'cn_one')

    def test_multisource_report_pdf_delivery_keeps_all_requirements_and_join(self):
        request = spec(req(), req('r2', request='연봉 규정'), req('r3', kind='analyze', depends_on=['r1', 'r2']),
                       req('r4', kind='answer', depends_on=['r3']), req('r5', kind='document', format='pdf', depends_on=['r4']),
                       req('r6', kind='delivery', depends_on=['r5']))
        raw = raw_plan('data')
        raw['steps'] += [{'id': 's2', 'agent': 'knowledge', 'task': '규정', 'depends_on': [], 'inputs': {}},
                         {'id': 's3', 'agent': 'data', 'task': '분석', 'depends_on': ['s1', 's2'], 'inputs': {}}]
        raw.update(document={'format': 'pdf', 'topic': '보고서'}, send_query='내 메일로 보내줘',
                   coverage={'r1': ['s1'], 'r2': ['s2'], 'r3': ['s3'], 'r4': ['$answer'], 'r5': ['$document'], 'r6': ['$delivery']})
        routes = routing(r1=['agent:data'], r2=['agent:knowledge'], r3=['agent:data'], r6=['delivery:groupware'])
        value = attached(raw, request, routes)
        self.assertEqual(len(decisions.validate(value)['coverage']), 6)
        bad = copy.deepcopy(value); bad['steps'][2]['depends_on'] = ['s1']
        with self.assertRaises(PlanError): decisions.validate(bad)
        bad = copy.deepcopy(value); bad['document']['format'] = 'pptx'
        with self.assertRaises(PlanError): decisions.validate(bad)

    def test_email_business_work_cannot_be_replaced_with_personal_mail(self):
        value = attached(raw_plan('groupware'), spec(req(kind='action', request='고객 메일 ERP 처리')),
                         routing(r1=['agent:work:email']))
        with self.assertRaises(PlanError): decisions.validate(value)
        value['steps'][0].update(agent='work', worker='email')
        self.assertEqual(decisions.validate(value)['steps'][0]['worker'], 'email')

    def test_ambiguity_waits_before_plan_and_resumes_without_reextracting(self):
        request = spec(req(), req('r2', kind='answer'))
        route_response = {'routes': [{'requirement_id': 'r1', 'candidates': ['connector:cn_one', 'connector:cn_two']}]}
        with patch.object(rp.llm, 'generate', side_effect=[request, route_response]) as model:
            pending = intent._judge_intent([{'role': 'user', 'content': '구매 조회 후 정리'}], CONNECTORS)
        self.assertEqual(model.call_count, 2)
        self.assertTrue(pending['planning_pending'])
        self.assertEqual(pending['steps'], [])
        with patch.object(rp.llm, 'generate', side_effect=AssertionError('no generation')):
            with self.assertRaises(PlanError):
                rp.resume_selection(pending, '알 수 없는 ERP', [], CONNECTORS)
        raw = raw_plan(connector_id='cn_two'); raw['coverage']['r2'] = ['$answer']
        with patch.object(rp.llm, 'generate', return_value=raw) as model:
            done = rp.resume_selection(pending, 'ERP2 구매', [], CONNECTORS)
        self.assertEqual(model.call_count, 1)
        self.assertEqual(done['request_spec'], request)
        self.assertEqual(done['routing']['r1']['selected'], 'connector:cn_two')
        self.assertFalse(pending['routing']['r1']['selected'])  # input remains untouched

    def test_removed_candidate_and_permission_change_stop_resume(self):
        pending = rp.plan(spec(), routing(r1=['connector:cn_one', 'connector:cn_two']), [], catalog.build(CONNECTORS))
        with patch.object(rp.llm, 'generate', side_effect=AssertionError('no planning')):
            with self.assertRaises(PlanError):
                rp.resume_selection(pending, 'ERP2 구매', [], CONNECTORS[:1])
        value = attached(raw_plan('work', worker='edu'), routes=routing(r1=['agent:work:edu']))
        with self.assertRaises(PlanError):
            rp.validate_available(value, catalog.build(eff={'nodes': {}, 'read': {'p_data': False, 'p_know': False}}))

    def test_multiple_source_questions_preserve_prior_selection_without_generation(self):
        request = spec(req(), req('r2'))
        routes = routing(r1=['connector:cn_one', 'connector:cn_two'], r2=['agent:data', 'agent:knowledge'])
        pending = rp.plan(request, routes, [], catalog.build(CONNECTORS))
        with patch.object(rp.llm, 'generate', side_effect=AssertionError('still waiting')):
            next_question = rp.resume_selection(pending, 'ERP1 구매', [], CONNECTORS)
        self.assertTrue(next_question['planning_pending'])
        self.assertEqual(next_question['routing']['r1']['selected'], 'connector:cn_one')
        self.assertEqual(next_question['request_spec'], request)
        self.assertEqual(next_question['clarify']['slots'][0]['key'], 'r2')

    def test_all_three_stages_and_legacy_compatibility(self):
        raw = raw_plan('knowledge')
        route = {'routes': [{'requirement_id': 'r1', 'candidates': ['agent:knowledge']}]}
        with patch.object(rp.llm, 'generate', side_effect=[spec(), route, raw]) as model:
            decision = intent._judge_intent([{'role': 'user', 'content': '규정'}])
        self.assertEqual(model.call_count, 3)
        self.assertEqual(decision['coverage'], {'r1': ['s1']})
        legacy = {k: v for k, v in raw.items() if k != 'coverage'}
        self.assertEqual(decisions.validate(legacy), legacy)


class ExecutionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        isolate_db(self.stack)
        self.stack.enter_context(patch('app.llm.generate', side_effect=AssertionError('unexpected LLM')))
        self.stack.enter_context(patch('app.llm.stream', side_effect=AssertionError('unexpected stream')))
        self.stack.enter_context(patch('app.flow_api_call.call', side_effect=AssertionError('unexpected API')))

    async def test_existing_card_pauses_and_selected_tool_executes_with_original_conditions(self):
        from app import db, conversation_execution as ce, execution_store as store, answers
        chat = db.create_chat('routing', '사내')
        pending = rp.plan(spec(), routing(r1=['connector:cn_one', 'connector:cn_two']), [], catalog.build(CONNECTORS))
        run = ce.create(chat, pending, '구매 조회', [], '사내', None, None, '', '')
        async def tokens(*args, **kwargs):
            yield {'type': 'token', 'text': 'result'}
        worker = AsyncMock(return_value={'status': 'answer', 'text': '구매 719', 'extras': {}})
        with patch('app.task_runner.run_connector', worker), patch.object(answers, '_aggregate_answer', tokens):
            events = [ev async for ev in ce.drive(run, chat, CONNECTORS, None)]
            worker.assert_not_awaited()
            card = next(ev['card'] for ev in events if ev['type'] == 'clarify')
            self.assertEqual(card['options'][1]['value'], 'connector:cn_two')
            saved = store.get(run['id'])
            with patch.object(rp.llm, 'generate', return_value=raw_plan(connector_id='cn_two')):
                ce.fill_reply(saved, 'ERP2 구매', explicit=True, connectors=CONNECTORS)
            saved = store.get(run['id'])
            await self._drain(ce.drive(saved, chat, CONNECTORS, None))
            worker.assert_awaited_once()
            self.assertEqual(worker.await_args.args[0]['id'], 'cn_two')
            self.assertIn('2026년 2월', worker.await_args.args[1])
            self.assertEqual(store.get(run['id'])['state'], 'completed')

    async def test_source_question_does_not_truncate_more_than_four_candidates(self):
        from app import db, conversation_execution as ce
        tools = [conn(f'cn_{i}', f'ERP{i} 구매') for i in range(6)]
        pending = rp.plan(spec(), routing(r1=[f'connector:cn_{i}' for i in range(6)]), [], catalog.build(tools))
        run = ce.create(db.create_chat('many', '사내'), pending, '구매', [], '사내', None, None, '', '')
        card = ce.question_event(run)['card']
        self.assertEqual(len(card['options']), 6)

    async def test_unrelated_message_does_not_fill_pending_source_selection(self):
        from app import db, conversation_execution as ce
        pending = rp.plan(spec(), routing(r1=['connector:cn_one', 'connector:cn_two']), [], catalog.build(CONNECTORS))
        run = ce.create(db.create_chat('new', '사내'), pending, '구매', [], '사내', None, None, '', '')
        self.assertFalse(ce.fill_reply(run, '다른 질문 할게', connectors=CONNECTORS))
        self.assertEqual(run['snapshot']['decision'], pending)

    @staticmethod
    async def _drain(stream):
        return [ev async for ev in stream]


if __name__ == '__main__':
    unittest.main()
