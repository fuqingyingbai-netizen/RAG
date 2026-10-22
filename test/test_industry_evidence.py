import json
import re
import sys
from types import SimpleNamespace

import pytest

from industry_research import (annotate_fact, append_evidence_index, delivery_errors,
                               normalize_risk, select_chapter_evidence, unknown_risk,
                               balanced_risk_facts, trace_snapshot, scope_fingerprint)
from report_agents.industry_report_agent import IndustryReportAgent
from research_strategies.industry import IndustryResearchStrategy
from research_workflow import ResearchWorkflow


def fact(module='政策与监管', scope='industry_level', text='机器人行业政策公布准入要求', url='https://sources.example/report'):
    return annotate_fact({'fact': text, 'source_url': url, 'module': module,
                          'evidence_scope': scope, 'source_grade': 'A', 'quality_score': 90},
                         {'industry_name': '机器人', 'as_of_date': '2026-01-31'})


def test_internal_fenced_facts_are_indexed_individually(monkeypatch):
    documents = []
    monkeypatch.setitem(sys.modules, 'milvus_writer', SimpleNamespace(
        MilvusWriter=lambda: SimpleNamespace(write_documents=lambda rows: documents.extend(rows))))
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = SimpleNamespace(id=1, target_name='机器人', target_type='industry', industry='机器人')
    payload = json.dumps({'facts': [{'fact': '```python\nprint(1)\n```'}, {'fact': 'another fact'}]})
    assert workflow._index_cleaned_facts(project, payload, 1, 'key') == 2
    assert documents[0]['text'] == '```python\nprint(1)\n```'
    with pytest.raises(ValueError, match='JSON'):
        workflow._index_cleaned_facts(project, 'invalid', 1, 'key')


def test_invalid_fact_library_records_index_failure_before_async_queue(monkeypatch):
    from unittest.mock import Mock
    import research_workflow
    monkeypatch.setattr(research_workflow.research_store, 'put_text', lambda *args, **kwargs: 'test-key')
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    database = Mock()
    database.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    project = SimpleNamespace(id=1, title='索引测试', target_name='机器人', target_type='industry', industry='机器人')
    artifact = workflow.save_artifact(database, project, 'cleaned_facts', '事实', 'invalid JSON')
    assert artifact.artifact_metadata['vector_index_status'] == 'error'
    assert artifact.artifact_metadata['vector_indexed'] is False
    assert 'JSON' in artifact.artifact_metadata['vector_index_error']


def test_capital_toggle_and_neutral_queries():
    intake = {'target_type': 'industry', 'target_name': '生物医药', 'industry': '生物医药',
              'industry_scope': {'capital_market': 'none', 'geography': '中国大陆', 'named_companies': []}}
    rows = IndustryResearchStrategy().expand_search_queries({'modules': []}, intake)
    assert not any(row['module'] == '投融资与资本市场' for row in rows)
    assert not any(row['module'] == '核心企业尽调' for row in rows)
    assert all(not any(word in row['query'] for word in ('美团', '阿里', 'CNNIC', '本地生活')) for row in rows)
    assert any('nmpa.gov.cn' in row.get('include_domains', []) for row in rows)
    intake['industry_scope']['capital_market'] = 'summary'
    enabled = IndustryResearchStrategy().expand_search_queries({'modules': []}, intake)
    assert all(row['evidence_scope'] == 'capital_market' for row in enabled if row['module'] == '投融资与资本市场')


def test_explicit_companies_are_the_only_due_diligence_queries():
    intake = {'target_name': '机器人', 'industry_scope': {'named_companies': ['甲公司'], 'capital_market': 'none'}}
    rows = IndustryResearchStrategy().expand_search_queries({'modules': []}, intake)
    requested = [row for row in rows if row['module'] == '核心企业尽调']
    assert len(requested) == 3
    assert all(row['company_name'] == '甲公司' and row['company_role'] == 'requested_due_diligence' for row in requested)


def test_chapter_9_accepts_capital_evidence_and_fact_reuse_does_not_starve_later_chapters():
    policy = fact()
    market = fact('市场规模与增长', text='机器人行业市场规模和增长需求')
    capital = fact('投融资与资本市场', 'capital_market', '机器人板块二级市场换手率变化')
    payload = {'facts': [policy, market, capital]}
    assert select_chapter_evidence(payload, '二级市场情绪', ['换手率'])['facts'] == [capital]
    assert select_chapter_evidence(payload, '摘要', [])['facts']
    assert select_chapter_evidence(payload, '市场规模与增长预测', [])['facts'] == [market]
    assert select_chapter_evidence(payload, '政策环境分析与近期政策摘录', [])['facts'] == [policy]
    assert policy['evidence_id'] != market['evidence_id']


def test_unknown_future_and_incomplete_numeric_facts_cannot_score():
    unknown = annotate_fact({'fact': '完全无关的食品行业信息', 'evidence_scope': 'industry_level'}, {'industry_name': '机器人'})
    assert unknown['scope_match'] == 'uncertain' and unknown['eligible_for_report'] is False
    future = annotate_fact({'fact': '机器人行业政策', 'date': '2026-02-01'}, {'industry_name': '机器人', 'as_of_date': '2026-01-31'})
    assert future['scope_match'] == 'out_of_scope'
    numeric = fact('市场规模与增长', text='机器人行业规模为100亿元')
    assert numeric['numeric_validation']['passed'] is False
    assert numeric['eligible_for_risk_scoring'] is False


def test_complete_numeric_context_still_requires_matching_region_and_time():
    raw = {'fact': '机器人规模100亿元', 'source_url': 'https://stats.gov.cn/sample',
           'evidence_scope': 'industry_level', 'numeric_context': {'metric': '规模', 'value': 100, 'unit': '亿元',
           'geography': '中国', 'period': '2025', 'definition': '工业机器人销售额', 'is_forecast': False}}
    correct = annotate_fact(raw, {'industry_name': '机器人', 'geography': '中国大陆', 'as_of_date': '2026-01-31'})
    assert correct['numeric_validation']['passed']
    foreign = annotate_fact(raw, {'industry_name': '机器人', 'geography': '欧洲', 'as_of_date': '2026-01-31'})
    assert 'geography_scope_match' in foreign['numeric_validation']['missing_fields']
    future = annotate_fact(raw, {'industry_name': '机器人', 'geography': '中国', 'as_of_date': '2024-01-31'})
    assert 'period_after_cutoff' in future['numeric_validation']['missing_fields']


def test_risk_requires_valid_dimension_evidence_and_never_scores_a_company_as_industry():
    policy = fact()
    supplied = {'dimensions': [{'name': '政策与监管风险', 'score': 10, 'evidence_ids': ['E-FAKEFAKEFAKE', policy['evidence_id']]},
                               {'name': '市场增长与需求风险', 'score': 10, 'evidence_ids': [policy['evidence_id']]}]}
    result = normalize_risk(supplied, [policy])
    assert result['dimensions'][0]['score'] == 10
    assert result['dimensions'][0]['evidence_ids'] == [policy['evidence_id']]
    assert result['dimensions'][1]['score'] is None
    assert result['overall_score'] is None
    company = fact(scope='representative_company')
    supplied['dimensions'][0]['evidence_ids'] = [company['evidence_id']]
    assert normalize_risk(supplied, [company])['dimensions'][0]['score'] is None
    assert len(unknown_risk()['dimensions']) == 7


def test_template_has_16_chapters_and_disabled_modules_skip_model_calls():
    agent = IndustryReportAgent()
    assert len(agent.outline) == 16
    assert agent.outline[6][0] == '技术路线对比'
    assert agent.outline[11][0] == '行业核心公司主体全面尽调'
    project = SimpleNamespace(title='机器人行业研究', target_name='机器人', target_type='industry', industry='机器人',
                              description='', industry_scope={'capital_market': 'none', 'named_companies': []})
    calls = []
    def invoke(role, prompt, emit):
        calls.append(role)
        if '总编' in role:
            return ''
        title = role.split(' - ')[-1]
        index = next(index for index, (heading, _) in enumerate(agent.outline, 1) if heading == title)
        ids = re.findall(r'E-[A-F0-9]{12}', prompt)
        return f'## {index}. {title}\n\n已核验事实 {ids[0] if ids else "待核验"}'
    body = agent.generate(project, json.dumps({'facts': [fact()]}, ensure_ascii=False), '{}', invoke,
                          lambda value, limit: value[:limit], lambda *a, **kw: None)
    headings = re.findall(r'^## (\d+)\.', body, flags=re.M)
    assert headings == [str(n) for n in range(1, 17)]
    assert not any(title in role for role in calls for title in ('行业投融资全景', '二级市场情绪', '行业核心公司主体全面尽调'))
    assert any(role.endswith(' - 摘要') for role in calls)
    assert not any('总编' in role for role in calls)
    assert '未指定核心企业' in body


def test_source_index_uses_actual_packages_and_gate_rejects_fabricated_ids():
    facts = [fact(module, text='机器人' + module) for module in
             ('政策与监管', '市场规模与增长', '竞争格局与代表企业', '技术路线对比')]
    report = '## 研究边界与口径\n\n' + '\n\n'.join(
        f'## {index}. {title}\n\n' + (f'事实 {facts[[3, 4, 6, 7].index(index)]["evidence_id"]}' if index in {3, 4, 6, 7} else '待核验')
        for index, (title, _) in enumerate(IndustryReportAgent.outline, 1))
    indexed, diagnostic = append_evidence_index(report, {'facts': facts}, IndustryReportAgent.outline)
    assert '## 15. 信息来源' in indexed
    assert all(f['evidence_id'] in indexed for f in facts)
    scope = {'capital_market': 'none', 'named_companies': []}
    assert delivery_errors(indexed, diagnostic, scope) == []
    broken = indexed.replace('## 2.', 'E-FAKEFAKEFAKE\n## 2.', 1)
    assert any('不属于本章' in issue for issue in delivery_errors(broken, diagnostic, scope))


def test_numeric_delivery_claim_needs_complete_context_and_matching_source():
    numeric = fact('市场规模与增长', text='机器人行业规模100亿元')
    report = '\n\n'.join(f'## {i}. {title}\n\n' +
                        (f'规模100亿元 {numeric["evidence_id"]}' if i == 4 else '待核验')
                        for i, (title, _) in enumerate(IndustryReportAgent.outline, 1))
    indexed, diagnostic = append_evidence_index(report, {'facts': [numeric]}, IndustryReportAgent.outline)
    assert any('数值 100亿元' in issue for issue in delivery_errors(indexed, diagnostic, {}))


def test_risk_workload_is_balanced_and_trace_retains_each_failure():
    policies = [fact(text='机器人行业政策' + str(i)) for i in range(100)]
    market = fact('市场规模与增长', text='机器人需求持续变化')
    selected = balanced_risk_facts([*policies, market], limit=10)
    assert market in selected and len(selected) == 10
    events = [{'timestamp': f'{i:04}', 'label': 'same step', 'status': 'fallback'} for i in range(8)]
    events.append({'timestamp': '9999', 'heartbeat': True, 'status': 'running'})
    kept, summary = trace_snapshot(events, limit=5)
    assert summary['event_status_counts']['fallback'] == 8
    assert summary['last_backend_event_timestamp'] == '0007'
    assert len(kept) == 5 and summary['history_truncated'] is True


def test_workflow_scope_filters_old_sources_and_canonicalizes_modules():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = SimpleNamespace(title='机器人研究', target_name='机器人', target_type='industry', industry='机器人',
                              description='', sources=[], artifacts=[])
    intake = workflow._normalize_intake(project, {'target_type': 'industry', 'focus_modules': ['行业定义', '供应商调研', '投融资全景'],
                                        'include_capital_markets': False, 'as_of_date': '2026-01-31'}, [], [])
    project.industry_scope = intake['industry_scope']
    project.industry_scope_fingerprint = scope_fingerprint(intake, source_only=True)
    def source(key):
        return SimpleNamespace(source_type='news', source_metadata={'industry_scope_fingerprint': key})
    old, current = source('old'), source(project.industry_scope_fingerprint)
    project.sources = [old, current]
    assert workflow._active_industry_sources(project) == [current]
    assert workflow._project_sources_match_intake(project, intake)
    plan = workflow.plan_research(project, intake)
    assert [m['name'] for m in plan['modules']] == ['行业定义与边界', '细分赛道与产业链']
    assert project.sources == [old, current]


def test_industry_target_is_never_replaced_by_project_title():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = SimpleNamespace(title='测试项目1', target_name='生物医药行业', target_type='industry', industry='', description='')
    intake = workflow._normalize_intake(project, {'target_type': 'industry', 'as_of_date': '2026-01-31'}, [], [])
    resolved = workflow.resolve_business_entity(project, intake)
    assert resolved['target_name'] == '生物医药行业'
    assert resolved['industry'] == '生物医药行业'
    assert project.target_name == '生物医药行业'


def test_fabricated_source_is_quarantined_and_uploaded_source_gets_internal_reference():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    source = SimpleNamespace(id=7, url='', title='行业访谈.txt', source_type='upload', source_metadata={},
                             content='机器人行业访谈', summary='', credibility_score=50)
    project = SimpleNamespace(id=1, target_type='industry', target_name='机器人', sources=[source], industry_scope={'industry_name': '机器人'})
    rows = workflow._annotate_evidence_facts(project, [
        {'fact': '机器人行业需求', 'source_title': source.title, 'evidence_scope': 'industry_level'},
        {'fact': '机器人行业需求', 'source_url': 'https://invented.example/source', 'evidence_scope': 'industry_level'},
    ])
    assert rows[0]['source_url'] == 'structured://projects/1/sources/7'
    assert rows[0]['source_provenance_verified']
    assert rows[1]['eligible_for_report'] is False


def test_partial_risk_score_stays_unknown_through_workflow():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    policy = fact()
    workflow._invoke_industry_risk = lambda *a, **kw: json.dumps({'dimensions': [
        {'name': '政策与监管风险', 'score': 10, 'evidence_ids': [policy['evidence_id']]}]})
    project = SimpleNamespace(title='机器人研究', target_name='机器人', target_type='industry', industry='机器人')
    assessed = json.loads(workflow.assess_risk(project, json.dumps({'facts': [policy]})))
    assert assessed['overall_score'] is None and assessed['risk_level'] == 'unknown'


def test_evidence_is_not_hidden_after_large_metadata_in_model_context():
    payload = {'evidence_ledger': ['large metadata' * 1000], 'facts': [fact()]}
    focused = select_chapter_evidence(payload, '政策环境分析与近期政策摘录', [])
    assert 'evidence_ledger' not in focused
    assert next(iter(focused)) == 'facts'


def test_industry_workflow_runs_from_collection_to_word_without_external_calls(monkeypatch):
    from datetime import datetime
    from unittest.mock import Mock
    from docx_exporter import markdown_to_docx_bytes
    from report_agents import CompanyReportAgent, PersonReportAgent
    import io
    import zipfile
    monkeypatch.setattr('research_workflow.object_session', lambda project: None)
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    workflow._report_agents = {'industry': IndustryReportAgent(), 'company': CompanyReportAgent(), 'person': PersonReportAgent()}
    project = SimpleNamespace(id=123, title='行业集成测试', target_name='机器人行业', target_type='industry',
                              industry='机器人行业', description='', sources=[], artifacts=[])
    database = Mock()
    exports = []
    def collect(*args, **kwargs):
        for i, module in enumerate(('政策与监管', '市场规模与增长', '竞争格局与代表企业', '技术路线对比'), 1):
            project.sources.append(SimpleNamespace(id=i, title='机器人行业' + module,
                url=f'https://stats.gov.cn/industry-test/{i}', source_type='government',
                content=('机器人行业' + module + '公开资料明确说明研究边界与应用要求。') * 8, summary='',
                object_key='', credibility_score=90, source_metadata={'module': module, 'evidence_scope': 'industry_level',
                'industry_scope_fingerprint': project.industry_scope_fingerprint, 'quality': {'score': 90}}))
        return 4
    workflow.collect_web_sources = collect
    workflow.enrich_ocr_sources = lambda *a, **kw: 0
    workflow._append_professional_evidence_assets = lambda project, report, *a, **kw: report
    def invoke(role, prompt, emit=None):
        if '风险研判' in role:
            return json.dumps(unknown_risk())
        if '总编' in role:
            return ''
        if '章节 Agent - ' in role:
            title = role.split(' - ')[-1]
            index = next(i for i, (heading, _) in enumerate(IndustryReportAgent.outline, 1) if heading == title)
            ids = re.findall(r'E-[A-F0-9]{12}', prompt)
            return f'## {index}. {title}\n\n' + ('已核验公开事实 ' + ids[0] if ids else '待核验')
        return '{"facts": [], "information_gaps": []}'
    workflow._invoke = invoke
    workflow._invoke_industry_risk = invoke
    workflow._invoke_industry_report = invoke
    def save(db, project, kind, title, content, metadata=None, **kwargs):
        artifact = SimpleNamespace(id=len(project.artifacts) + 1, artifact_type=kind, title=title,
            version=1, content=content, artifact_metadata=metadata or {}, created_at=datetime.now(), object_key='test-key')
        project.artifacts.append(artifact)
        if kind == 'desktop_report':
            exports.append(markdown_to_docx_bytes(content, title=title, outline=IndustryReportAgent.outline))
        return artifact
    workflow.save_artifact = save
    artifacts, added = workflow.run_project(database, project, [], [], intake={
        'target_type': 'industry', 'include_capital_markets': False, 'as_of_date': '2026-01-31'})
    assert added == 4 and project.status == 'completed'
    run_record = next(a for a in artifacts if a.artifact_type == 'industry_run')
    first_run = json.loads(run_record.content)
    assert first_run['status'] == 'completed' and len(first_run['stages']) == 8
    assert first_run['stages'][4]['outputs'][0]['usage'] == 'created'
    risk_artifact = next(a for a in artifacts if a.artifact_type == 'risk_assessment')
    assert risk_artifact.artifact_metadata['risk_transparency']['calibration_status'] == 'not_calibrated'
    report = next(a for a in artifacts if a.artifact_type == 'desktop_report')
    assert report.artifact_metadata['delivery_status'] == 'review_draft'
    assert report.artifact_metadata['risk_transparency'] == risk_artifact.artifact_metadata['risk_transparency']
    assert any(r['code'] == 'risk_assessment_incomplete' for r in report.artifact_metadata['delivery_review_reasons'])
    assert any(a.artifact_type == 'report_quality_diagnostic' for a in artifacts)
    assert '## 16. 后续研究点' in report.content
    with zipfile.ZipFile(io.BytesIO(exports[0])) as archive:
        assert archive.testzip() is None and 'word/document.xml' in archive.namelist()
    assert any(a.artifact_type == 'proposal' for a in artifacts)
    from industry_delivery import verification_task_table
    proposal = next(a for a in artifacts if a.artifact_type == 'proposal')
    task_table = verification_task_table(report.artifact_metadata['verification_tasks'])
    assert task_table in report.content
    assert verification_task_table(report.artifact_metadata['verification_tasks'], include_reference_index=False,
                                   reference_location='附录B候选来源索引') in proposal.content
    assert verification_task_table(report.artifact_metadata['verification_tasks'], reference_index_only=True) in proposal.content
    ledger_artifact=next(a for a in artifacts if a.artifact_type=='industry_claim_ledger')
    ledger=json.loads(ledger_artifact.content)
    assert ledger['dependencies']['report_artifact_id']==report.id
    assert report.artifact_metadata['claim_ledger_artifact_id']==ledger_artifact.id
    assert all(c['entailment_status']=='not_evaluated' for c in ledger['claims'])
    cleaned_contract=json.loads(next(a.content for a in artifacts if a.artifact_type=='cleaned_facts'))
    from industry_evidence import VERSION as evidence_contract_version
    assert cleaned_contract['evidence_coverage']['version']==evidence_contract_version

    # A newer review draft must survive resume even if an older candidate exists.
    older = SimpleNamespace(id=999, artifact_type='desktop_report', title='旧候选稿', version=1,
        content=report.content, artifact_metadata={'report_pipeline_version':report.artifact_metadata['report_pipeline_version'],
        'delivery_status':'final_candidate'}, created_at=datetime(2020,1,1))
    project.artifacts.append(older)
    def no_new_report(*args, **kwargs):
        raise AssertionError('Resume should reuse the latest body without another model call')
    original_generate_report=workflow.generate_report
    workflow.generate_report=no_new_report
    monkeypatch.setenv('WORKFLOW_RESUME_ENABLED','true')
    resumed,_=workflow.run_project(database,project,[],[],intake={
        'target_type':'industry','include_capital_markets':False,'as_of_date':'2026-01-31'})
    reexported=next(a for a in resumed if a.artifact_type=='desktop_report')
    resumed_run=json.loads(next(a.content for a in resumed if a.artifact_type=='industry_run'))
    assert resumed_run['parent_run_id']==first_run['run_id']
    assert resumed_run['stages'][4]['outputs'][0]['usage']=='reused'
    assert json.loads(run_record.content)==first_run
    assert reexported.artifact_metadata['reexported_from_artifact_id']==report.id
    assert reexported.artifact_metadata['delivery_status']=='review_draft'
    assert reexported.artifact_metadata['delivery_review_reasons']==report.artifact_metadata['delivery_review_reasons']
    assert reexported.content.count('**待人工复核稿**')==1
    assert any(a.artifact_type=='report_quality_diagnostic' for a in resumed)
    reexported_ledger=next(a for a in resumed if a.artifact_type=='industry_claim_ledger')
    assert json.loads(reexported_ledger.content)['dependencies']['report_artifact_id']==reexported.id
    assert reexported_ledger.id!=ledger_artifact.id

    # A changed risk pipeline invalidates only risk/report even with reusable facts.
    prior_risk=next(a for a in artifacts if a.artifact_type=='risk_assessment')
    prior_risk.artifact_metadata['risk_pipeline_version']='legacy'
    workflow.generate_report=original_generate_report
    risk_calls=[]
    def assess_again(*a,**kw):
        risk_calls.append(a)
        return json.dumps(unknown_risk(scope=project.industry_scope))
    workflow.assess_risk=assess_again
    refreshed,_=workflow.run_project(database,project,[],[],intake={
        'target_type':'industry','include_capital_markets':False,'as_of_date':'2026-01-31'})
    new_risk=next(a for a in refreshed if a.artifact_type=='risk_assessment')
    new_report=next(a for a in refreshed if a.artifact_type=='desktop_report')
    assert len(risk_calls)==1 and new_risk.id!=prior_risk.id
    from industry_research import INDUSTRY_RISK_VERSION
    assert new_risk.artifact_metadata['risk_pipeline_version']==INDUSTRY_RISK_VERSION
    assert 'reexported_from_artifact_id' not in new_report.artifact_metadata

    # Same source set and pipeline version do not authorize a stale downstream
    # score after the saved fact payload has been revised.
    reused_cleaned=next(a for a in refreshed if a.artifact_type=='cleaned_facts')
    revised_payload=json.loads(reused_cleaned.content)
    revised_payload['information_gaps'].append('新增已审阅的证据缺口。')
    reused_cleaned.content=json.dumps(revised_payload,ensure_ascii=False)
    revised,_=workflow.run_project(database,project,[],[],intake={
        'target_type':'industry','include_capital_markets':False,'as_of_date':'2026-01-31'})
    latest_risk=next(a for a in revised if a.artifact_type=='risk_assessment')
    assert len(risk_calls)==2 and latest_risk.id!=new_risk.id
    assert latest_risk.artifact_metadata['cleaned_sha256']!=new_risk.artifact_metadata['cleaned_sha256']


def test_proposal_follows_seven_sections_and_industry_scope():
    from report_agents.industry_proposal import build_industry_proposal
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = SimpleNamespace(title='机器人研究', target_name='机器人', target_type='industry', industry='机器人',
                              industry_scope={'segments': ['协作机器人'], 'geography': '欧洲',
                                              'as_of_date': '2026-01-31', 'capital_market': 'none', 'named_companies': []})
    proposal = build_industry_proposal(project)
    assert re.findall(r'^## (\d+)\.', proposal, flags=re.M) == [str(i) for i in range(1, 8)]
    assert '欧洲' in proposal and '协作机器人' in proposal
    assert '履历、商业关系' not in proposal
    assert workflow._proposal_quality_warning(proposal, target_type='industry') == ''
