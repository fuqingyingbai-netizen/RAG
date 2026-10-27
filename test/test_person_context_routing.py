"""Behavioral regressions for context propagation, disambiguation and paid routing."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from company_platform import CompanyPlatformAudit
from person_identity import affiliations, build_anchor
from person_platforms import BASE, collect, detail_tools, validated_records, xiniu_plan
from person_retrieval import DIMENSIONS, SearchSession, coverage
from research_api import _identity_skeleton, _locked_run_intake, _save_project_intake, _project_intake, _merge_upload_identity_into_intake
from research_schemas import ResearchRunRequest
from research_workflow import ResearchWorkflow
from research_strategies.person import PersonResearchStrategy


def intake(name='林知远'):
    value = {'target_type': 'person', 'target_name': name, 'affiliation': '恒川软件有限公司 / 前CTO',
             'person_context': '2018至2022年负责研发；教育：远山大学', 'identity_anchors': '远山大学',
             'person_aliases': ['Evan Lin'], 'focus_questions': ['核对历史任职'], 'focus_modules': ['经营胜任力', '核心管理团队背景']}
    value['person_anchor'] = build_anchor(value)
    return value


def source(text, url='https://official.invalid/profile', **metadata):
    return SimpleNamespace(id=1, title='人物介绍', content=text, summary='', url=url,
                           source_type='official', source_metadata={'identity_confidence': 'high', **metadata})


@pytest.mark.parametrize('value, expected', [
    ('恒川软件有限公司 CTO / 前合伙人 / 远山大学 / 2018-2022', ['恒川软件有限公司']),
    ('甲机构 / 乙机构 / 创始人', ['甲机构', '乙机构']),
    ('原任恒川科技CEO', ['恒川科技']),
    ('前海资本 / 董事长', ['前海资本']),
    ('远山大学教授 / 学历：博士 / 所在地：南京', []),
])
def test_context_segments_do_not_become_bogus_company_queries(value, expected):
    assert affiliations(value) == expected


def test_every_person_query_keeps_context_but_broad_identity_discovery_remains():
    value = intake()
    rows = PersonResearchStrategy().expand_search_queries({'modules': []}, value)
    assert any(r['module'] == '身份消歧' and '恒川' not in r['query'] for r in rows)
    for row in rows:
        assert row['identity_context']['raw_context'] == value['affiliation']
        if row['module'] != '身份消歧':
            assert '恒川软件有限公司' in row['query']
    assert any('核对历史任职' in r['query'] for r in rows)


def test_supplementary_context_changes_source_cache_fingerprint_and_writer_anchor():
    wf = ResearchWorkflow.__new__(ResearchWorkflow)
    a = intake()
    b = {**a, 'person_context': '任职机构：另一家公司；任职时间：2023年'}
    b['person_anchor'] = build_anchor(b)
    assert wf._intake_evidence_fingerprint(a) != wf._intake_evidence_fingerprint(b)
    assert b['person_anchor']['provenance'] == 'user_supplied_clues_not_verified_facts'


def test_same_name_and_generic_role_do_not_confirm_identity():
    wf = ResearchWorkflow.__new__(ResearchWorkflow)
    value = intake()
    assert wf._person_source_identity_confidence('林知远', '林知远是另一机构的CTO。', value)['confidence'] == 'low'
    distant = '林知远参与科研。' + '无关新闻内容。' * 120 + '远山大学公布信息。'
    assert wf._person_source_identity_confidence('林知远', distant, value)['confidence'] == 'low'
    assert wf._person_source_identity_confidence('林知远', '林知远毕业于远山大学。', value)['confidence'] == 'medium'


def test_upload_school_extraction_is_generic_and_person_is_never_company_name():
    result = _identity_skeleton('姓名：林知远\n公司：恒川软件有限公司\n学校：远山大学\n职位：CTO', 'person')
    assert 'company_name' not in result
    assert '远山大学' in result['identity_anchors']


def test_explicit_person_fields_survive_schema_and_search_toggle():
    req = ResearchRunRequest(target_type='person', affiliation='恒川软件 / CTO', person_context='任职时间：2020年',
                             identity_anchors='远山大学', ai_search_enabled=False)
    value = _locked_run_intake(req)
    assert value['person_context'] == '任职时间：2020年'
    assert value['identity_anchors'] == '远山大学'
    assert value['ai_search_enabled'] is False
    # An abbreviated resume must not erase saved optional fields or disabled search.
    abbreviated = _locked_run_intake(ResearchRunRequest(), 'person')
    assert 'affiliation' not in abbreviated and 'person_context' not in abbreviated
    assert 'ai_search_enabled' not in abbreviated


def test_three_engines_are_sequential_bounded_and_all_chapters_are_assessed(monkeypatch):
    monkeypatch.setenv('PERSON_SEARCH_CALL_BUDGET', '25')
    value = intake()
    rows = PersonResearchStrategy().expand_search_queries({'modules': []}, value)
    session = SearchSession(value, ['bocha', 'exa', 'tavily'])
    first = session.choose(rows, 1, [])
    assert {c for r in first for c in r['person_chapters']} >= set(DIMENSIONS)
    assert all(len(r['preferred_providers']) == 1 for r in first)
    session.record([(r, []) for r in first])
    second = session.choose(rows, 2, [])
    assert second and all(r['retrieval_reason'] == 'independent_engine_probe' for r in second)
    for row in second:
        chapter = row['person_chapters'][0]
        first_engine = next(r['provider'] for r in session.rows if chapter in r['chapters'])
        assert row['preferred_providers'] != [first_engine]
    session.choose(rows, 3, [])
    audit = session.audit([])
    assert len(audit['attempts']) <= 25
    assert len(audit['coverage']['chapters']) == 15
    # The generic rounds stop before spending the reserved reputation/peer pass.
    assert not audit['budget_exhausted']
    assert len(audit['attempts']) + audit['chapter_7_8_reserved_calls'] == 25


def test_duplicate_queries_cannot_spend_twice_on_same_engine():
    session = SearchSession(intake(), ['bocha'])
    rows = [{'query': '林知远 恒川软件 任职', 'person_chapters': [2]}] * 4
    first = session.choose(rows, 1, [])
    assert sum(r['query'] == rows[0]['query'] for r in first) == 1
    assert sum(r.get('retrieval_reason') == 'primary_identity_source_reserve' for r in first) <= 1
    assert not session.choose(rows, 1, [])


def test_failed_account_is_not_queried_in_later_rounds():
    session = SearchSession(intake(), ['bocha', 'exa', 'tavily'])
    first = session.choose([{'query': '林知远 恒川软件 履历', 'person_chapters': [2]}], 1, [])
    first[0].update(person_search_status='failed', person_search_error_reason='quota_exceeded')
    session.record([(first[0], [])])
    later = session.choose([], 2, [])
    assert later and all(r['preferred_providers'] != ['bocha'] for r in later)
    assert session.audit([])['unavailable_providers']['bocha'] == 'quota_exceeded'


def test_primary_identity_has_a_slot_before_broad_chapter_queries():
    value = intake()
    rows = PersonResearchStrategy().expand_search_queries({'modules':[]},value)
    session = SearchSession(value,['bocha','tavily','exa'])
    first = session.choose(rows,1,[])
    assert first[0]['retrieval_reason'] == 'primary_identity_source_reserve'
    assert value['target_name'] in first[0]['query']
    assert value['person_anchor']['known_affiliations'][0] in first[0]['query']
    listed = source('恒川软件是上市公司，披露股票代码，本段仅为媒体介绍。'*6)
    listed.source_type = 'news'
    later = session.choose(rows,2,[listed])
    assert later[0].get('include_domains')
    assert later[0]['retrieval_reason'] == 'independent_engine_probe'


def test_snippets_namesakes_and_reprints_do_not_close_gaps():
    text = '林知远于2021年毕业于远山大学并开始职业生涯，后加入恒川软件有限公司担任技术负责人。' * 4
    evidence = [source(text), source(text, 'https://reprint.invalid/article'),
                source(text, 'https://namesake.invalid/bio', identity_confidence='low')]
    chapter = coverage(evidence, intake())['chapters'][1]
    education = chapter['requirements'][0]
    assert len(education['candidates']) == 2
    assert any('独立' in gap for gap in education['gaps'])
    assert education['state'] == 'partial'
    assert not coverage([source('林知远 毕业')], intake())['chapters'][1]['requirements'][0]['candidates']


def test_company_sources_never_satisfy_personal_responsibility():
    text = '恒川软件有限公司披露2021年融资及经营战略相关事项，公司董事会讨论下一阶段计划和产品布局。' * 4
    row = coverage([source(text, person_affiliation={'person_name': '林知远'})], intake())['chapters'][3]
    assert any('个人职责' in g for r in row['requirements'] for g in r['gaps'])


def test_personnel_record_cannot_fill_credit_chapter_from_a_company_name_keyword():
    from person_evidence import build_packages
    from report_agents.person_report_agent import PERSON_REPORT_OUTLINE
    facts = [{'fact': '林知远的人员关联记录：企业名称为恒川信用技术有限公司，角色为董事。',
              'evidence_quote': '林知远的人员关联记录：企业名称为恒川信用技术有限公司，角色为董事。',
              'source_url': 'structured://qcc_executive/positions', 'source_title': '信用与人格评价检索结果',
              'identity_confidence': 'high', 'identity_match': 'confirmed', 'claim_type': 'person_platform_record',
              'person_chapters': [2, 6, 9]}]
    package = build_packages({'facts': facts}, '林知远', PERSON_REPORT_OUTLINE)
    assert package['chapters'][9]['facts']
    assert not package['chapters'][7]['facts']


def envelope(person='林知远', company='恒川软件有限公司', records=None):
    return {'result': {'content': [{'type': 'text', 'text': json.dumps({'人员名称': person, '企业名称': company,
        '摘要': '没有风险，仅为平台文案', '记录': records if records is not None else [{'企业名称': company, '角色': ['CTO'], '成立日期': '2001-01-01'}]}, ensure_ascii=False)}]}}


def test_qcc_checks_returned_person_and_company_and_ignores_summary_innocence():
    assert not validated_records(envelope(person='陈雨安'), '林知远', '恒川软件有限公司', BASE[0])[0]
    assert not validated_records(envelope(company='另一家公司'), '林知远', '恒川软件有限公司', BASE[0])[0]
    matched, quotes = validated_records(envelope(records=[]), '林知远', '恒川软件有限公司', BASE[0])
    assert matched and not quotes
    matched, quotes = validated_records(envelope(), '林知远', '恒川软件有限公司', BASE[2])
    assert matched and '历史记录' in quotes[0]
    assert '没有风险' not in quotes[0]
    assert not detail_tools('失信：0条\n处罚：0条')
    assert detail_tools('失信：2条') == ['get_executive_dishonest']


def test_xiniu_routes_questions_to_specific_tools_instead_of_all_21():
    assert not xiniu_plan({'focus_questions': ['核对学历']}, '恒川软件有限公司')
    plan = xiniu_plan({'focus_questions': ['核对投资机构融资和最近一年事件'], 'as_of_date': '2026-10-20'}, '恒川资本')
    assert [r[0] for r in plan] == ['get_entity_profile', 'get_company_info', 'get_project_events']
    assert plan[-1][1]['end_date'] == '2026-10-20'
    assert len(plan) <= 3


def test_main_person_collector_calls_person_history_and_stops_xiniu_on_quota(monkeypatch):
    monkeypatch.setenv('QCC_API_KEY', 'fake-qcc')
    monkeypatch.setenv('XINIU_API_KEY', 'fake-xiniu')
    monkeypatch.delenv('PERSON_TYC_FALLBACK_ENABLED', raising=False)
    calls = []
    project = SimpleNamespace(target_name='林知远', target_type='person', title='合成人物测试', description='', industry='', person_platform_attempts=[])
    wf = ResearchWorkflow.__new__(ResearchWorkflow)
    wf._mcp_initialize = Mock(return_value=(object(), True, ''))
    def query(url, headers, tool, args, **kwargs):
        calls.append((tool, args))
        return ({'error': {'message': '余额不足，配额已用完'}} if 'xiniudata' in url else envelope(), object())
    wf._mcp_call_tool = query
    wf._save_structured_source = Mock(return_value=True)
    wf._collect_tyc_sources = Mock(side_effect=AssertionError('TYC must be opt-in'))
    collect(wf, None, project, '恒川软件有限公司', intake())
    assert all({'searchKey', 'personName'} == set(args) for tool, args in calls if tool.startswith('get_executive'))
    assert any('historical_positions' in tool for tool, _ in calls)
    assert sum(tool == 'get_company_info' for tool, _ in calls) == 1
    assert any(r['reason'] == 'quota_exceeded' for r in project.person_platform_attempts)
    assert any(r['status'] == 'not_queried' and r['provider'] == 'xiniu' for r in project.person_platform_attempts)
    # One-hop same-run collection cannot spend again on matching successful QCC queries.
    previous = len(calls)
    collect(wf, None, project, '恒川软件有限公司', intake())
    assert len(calls) == previous


def test_known_subject_upload_does_not_import_an_unrelated_person(monkeypatch):
    project = SimpleNamespace(target_name='林知远', target_type='person')
    assert _merge_upload_identity_into_intake(None, project, '姓名：陈雨安\n学校：远山大学') == {}


def test_changed_identity_context_rechecks_existing_sources_instead_of_reusing_namesake_match():
    wf = ResearchWorkflow.__new__(ResearchWorkflow)
    value = intake()
    old = source('林知远在另外一家研究院担任CTO。', person_intake_fingerprint='old-context')
    record = source('', url='structured://qcc/old-company', person_intake_fingerprint='old-context',
                    person_affiliation={'person_name': '林知远', 'affiliation_name': '另一家公司'})
    correct = source('林知远在恒川软件有限公司担任CTO，2021年加入。')
    project = SimpleNamespace(sources=[old, record, correct])
    wf._refresh_person_source_identities(project, value)
    assert old.source_metadata['identity_confidence'] == 'low'
    assert record.source_metadata['identity_status'] == 'quarantined'
    assert correct.source_metadata['identity_confidence'] == 'high'
    assert correct.source_metadata['person_intake_fingerprint'] == wf._intake_evidence_fingerprint(value)


def test_offline_person_run_never_calls_paid_professional_platforms():
    workflow = Mock()
    project = SimpleNamespace(target_name='林知远')
    assert collect(workflow, None, project, '恒川软件有限公司', {**intake(), 'ai_search_enabled': False}) == 0
    workflow._mcp_initialize.assert_not_called()
    assert project.person_platform_attempts[0]['reason'] == 'online_search_disabled'


def test_fast_person_tools_do_not_overwrite_each_others_original_objects(monkeypatch):
    import research_workflow as module
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    workflow._structured_entity_matches_request = Mock(return_value=(True, 'test_matched_subject'))
    workflow._is_empty_structured_text = Mock(return_value=False)
    workflow._save_professional_visual_evidence = Mock(return_value=[])
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = None
    writes = {}
    def put(key, body, *args):
        assert key not in writes, 'an earlier source was overwritten'
        writes[key] = body
        return key
    monkeypatch.setattr(module.research_store, 'put_text', put)
    monkeypatch.setattr(module, '_now_key', lambda: '20261020120000')
    monkeypatch.setattr(module.time, 'time_ns', lambda: 1792476237651063900)
    project = SimpleNamespace(id=1)
    for tool in ('get_executive_positions', 'get_executive_historical_positions'):
        assert workflow._save_structured_source(db, project, 'qcc_executive', '人物核查', tool,
            '林知远在恒川软件有限公司的人员任职原始记录。',
            {'tool': tool, 'person_subject_verified': True, 'company_qcc_raw_response': {'tool': tool}}, intake=intake())
    assert len(writes) == 4


def test_abbreviated_api_resume_preserves_saved_context_and_explicit_clear_works(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import research_api
    from models import Base, ResearchProject, User
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    monkeypatch.setattr(research_api.research_store, 'mode', 'local')
    monkeypatch.setattr(research_api.research_store, 'local_root', tmp_path)
    with Session(engine) as db:
        user = User(username='context-resume-test', password_hash='not-a-real-login')
        db.add(user)
        db.flush()
        p = ResearchProject(title='身份上下文保存测试', target_name='林知远', target_type='person',
                            industry='', description='', created_by_id=user.id)
        db.add(p)
        db.flush()
        _save_project_intake(db, p, {'affiliation': '恒川软件 / CTO', 'person_context': '2018年入职',
                                   'identity_anchors': '远山大学', 'ai_search_enabled': False,
                                   'focus_questions': ['核对历史任职']})
        abbreviated = _locked_run_intake(ResearchRunRequest(), 'person')
        _save_project_intake(db, p, abbreviated)
        assert abbreviated['person_context'] == '2018年入职'
        assert abbreviated['ai_search_enabled'] is False
        db.expire(p, ['artifacts'])
        assert _project_intake(p)['identity_anchors'] == '远山大学'
        clear = _locked_run_intake(ResearchRunRequest(target_type='person', person_context=''), 'person')
        _save_project_intake(db, p, clear)
        assert clear['person_context'] == '' and clear['affiliation'] == '恒川软件 / CTO'


@pytest.mark.parametrize('provider', ['bocha', 'tavily', 'exa'])
def test_person_recall_is_one_request_without_upfront_full_content_or_images(monkeypatch, provider):
    from web_search import WebSearchProvider
    import web_search
    monkeypatch.setenv(provider.upper() + '_API_KEY', 'fake-key')
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {'code': 200, 'data': {'webPages': {'value': []}}, 'results': []}
    post = Mock(return_value=response)
    monkeypatch.setattr(web_search.requests, 'post', post)
    search = WebSearchProvider()
    monkeypatch.setattr(search, '_wait_for_exa_slot', lambda: None)
    search.search_single(provider, '林知远 恒川软件', limit=3)
    post.assert_called_once()
    body = post.call_args.kwargs['json']
    if provider == 'tavily':
        assert body['search_depth'] == 'basic'
        assert body['include_raw_content'] is False and body['include_images'] is False
    if provider == 'exa':
        assert 'contents' not in body


def test_actual_web_pipeline_retains_context_budget_and_all_15_diagnostics(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import research_workflow as module
    import report_knowledge
    from models import Base, ResearchProject, User
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    for key in ('QCC_API_KEY', 'XINIU_API_KEY', 'TYC_API_KEY', 'TENCENT_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('BOCHA_API_KEY', 'fake-key')
    monkeypatch.setenv('WEB_SEARCH_PROVIDER', 'bocha')
    monkeypatch.setenv('PERSON_SEARCH_CALL_BUDGET', '5')
    monkeypatch.setenv('PERSON_WEB_FETCH_BUDGET', '5')
    monkeypatch.setenv('AUTHORITY_COVERAGE_REQUIRED', 'false')
    monkeypatch.setenv('CLEANING_LLM_ENABLED', 'false')
    monkeypatch.setenv('RESEARCH_LEGACY_RAG_ENABLED', 'false')
    monkeypatch.setattr(module, 'FIXED_GENERATE_PROPOSAL', False)
    monkeypatch.setattr(module.research_store, 'mode', 'local')
    monkeypatch.setattr(module.research_store, 'local_root', tmp_path)
    monkeypatch.setattr(report_knowledge, 'sync_report_safely', lambda *a, **kw: None)
    queries, packs = [], []
    def search(provider, query, **kw):
        queries.append((provider, query, kw['limit']))
        rows = [{'title': '林知远在恒川软件有限公司的公开履历', 'url': f'https://fixture.invalid/record/{len(queries)}/{i}',
                 'summary': '林知远在恒川软件有限公司任职。', 'content': '',
                 'metadata': {'provider': provider}, 'credibility_score': 90} for i in range(4)]
        return rows + [rows[0]]
    monkeypatch.setattr(module.web_search_provider, 'search_single', search)
    w = ResearchWorkflow()
    monkeypatch.setattr(w, 'resolve_business_entity', lambda p, value, **kw: value)
    original = ('林知远于2021年在恒川软件有限公司担任技术负责人，负责产品战略、团队管理、研发创新及董事会沟通。'
                '林知远于2010年毕业于远山大学，公开履历中的任职时间和职责仍需查验。') * 8
    monkeypatch.setattr(w, '_fetch_web_url_with_timeout', lambda *a, **kw: {'status': 'done', 'content': original})
    def write(role, prompt, **kw):
        pack = json.loads(prompt[prompt.index('{"chapter":'):])
        if '材料采用诊断' in role:
            from person_model_fixture import material_response
            return material_response(pack)
        packs.append(pack)
        return json.dumps({'claims': [{'statement': f['fact'], 'evidence_ids': [f['evidence_id']], 'analysis': ''}
                                     for f in pack['facts']]}, ensure_ascii=False)
    monkeypatch.setattr(w, '_invoke_person_report_section', write)
    monkeypatch.setattr(w, '_append_professional_evidence_assets', lambda p, report, cleaned, **kw: report)
    monkeypatch.setattr(w, '_render_docx_quality', lambda data: ({'docx_render_status': 'not_run_in_offline_test'}, b''))
    monkeypatch.setattr(w, '_finalize_source_records', lambda *a, **kw: None)
    with Session(engine) as db:
        user = User(username='context-pipeline-test', password_hash='not-a-real-login')
        db.add(user)
        db.flush()
        p = ResearchProject(title='林知远人物背景调查', target_name='林知远', target_type='person',
                            industry='', description='', created_by_id=user.id)
        db.add(p)
        db.commit()
        artifacts, _ = w.run_project(db, p, [], [], intake={**intake(), 'company_name': '林知远'})
        assert len(queries) == 5 and all(limit <= 6 for _, _, limit in queries)
        assert packs and all(pack['identity_clues_not_facts']['supplementary_context'] == intake()['person_context'] for pack in packs)
        audit = json.loads(w._latest_artifact(p, 'person_retrieval_audit').content)
        assert audit['calls_planned'] == 5 and audit['page_fetch_attempts'] <= 5
        assert audit['budget_exhausted']
        assert len(audit['coverage']['chapters']) == 15
        assert audit['candidate_flow_summary']['returned_candidate_rows'] == 25
        assert audit['candidate_flow_summary']['unique_returned_urls'] == 20
        assert audit['candidate_flow_summary']['dispositions'] == {'retained':20,'duplicate_url':5}
        assert not audit['candidate_flow_summary']['unresolved_candidate_rows']
        assert sum(r['fetch_disposition']=='explicit_budget_exhausted' for r in audit['candidate_flow']) == 15
        report = next(a for a in artifacts if a.artifact_type == 'desktop_report')
        assert '人物检索已达到本轮请求预算' in report.content
        assert report.artifact_metadata['requires_human_review']
        monkeypatch.setenv('WORKFLOW_RESUME_ENABLED','true')
        # A writing-code upgrade must not invalidate an otherwise matching
        # retained search stage or spend the search allowance a second time.
        report.artifact_metadata = {**report.artifact_metadata,'report_pipeline_version':'older-writer-fixture'}
        db.commit()
        queries.clear()
        rerun,_ = w.run_project(db,p,[],[],intake={**intake(),'company_name':'林知远'})
        assert not queries
        assert any(a.artifact_type=='desktop_report' for a in rerun)
