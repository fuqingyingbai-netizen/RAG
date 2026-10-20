import json
from types import SimpleNamespace
from unittest.mock import Mock

from person_evidence import normalize_facts, validate_model_claims, render_section
from person_records import observation, chapter_relevant
from person_platforms import collect, collect_group, coverage_rows, CRITICAL, IDENTITY, validated_records, response_state
from research_workflow import ResearchWorkflow


def claims(texts, analysis):
    rows, _ = normalize_facts({'facts': [
        {'fact': text, 'source_url': f'https://official.invalid/{i}',
         'identity_match': 'confirmed', 'identity_confidence': 'high'} for i, text in enumerate(texts)]}, '林知远')
    output = json.dumps({'claims': [{'evidence_ids': [r['evidence_id'] for r in rows], 'analysis': analysis}]})
    return rows, validate_model_claims(output, {'writing_contract': 'evidence_selection_v2', 'facts': rows})


def test_uncertain_comparison_stays_visible_with_specific_review_reason_and_exact_sources():
    rows, (accepted, errors) = claims(['林知远曾任恒川软件董事，负责产品。', '林知远曾任远山科技董事，负责研发。'],
                                      '两段职责存在差异，需要结合授权文件进一步核对。')
    claim = accepted[0]
    assert not claim['analysis'] and claim['analysis_status'] == 'pending_review'
    assert claim['review_analysis'] and 'comparison_basis_insufficient' in errors
    assert claim['source_support'][0]['quote'] == rows[0]['fact']
    text = render_section({'chapter': 6, 'title': '团队', 'task': '', 'facts': rows, 'information_gaps': []}, accepted)
    assert '【待复核】' in text and '比较依据尚不完整' in text
    assert '不作为已确认发现' in text


def test_known_wrong_units_and_personality_findings_do_not_survive_as_review_text():
    _, (accepted, _) = claims(['林知远持股10%。', '林知远持有20万股。'], '10%与20万股存在矛盾。')
    assert not accepted[0]['analysis'] and not accepted[0]['review_analysis']
    _, (accepted, _) = claims(['林知远发表公开演讲。', '林知远担任董事。'], '这证明其诚信优秀。')
    assert not accepted[0]['analysis'] and not accepted[0]['review_analysis']


def envelope(company, person='林知远', rows=None, summary_only=False):
    data = {'人员名称': person, '企业名称': company, '摘要': '平台摘要不构成无风险结论'}
    if not summary_only:
        data['记录'] = rows if rows is not None else [{'企业名称': company, '角色': ['董事']}]
    return {'result': {'content': [{'type': 'text', 'text': json.dumps(data, ensure_ascii=False)}]}}


def setup(monkeypatch, budget=18):
    monkeypatch.setenv('QCC_API_KEY', 'synthetic-key')
    monkeypatch.delenv('XINIU_API_KEY', raising=False)
    monkeypatch.setenv('PERSON_PLATFORM_CALL_BUDGET', str(budget))
    project = SimpleNamespace(target_name='林知远', target_type='person', title='测试', description='', industry='')
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    workflow._mcp_initialize = Mock(return_value=(None, True, ''))
    workflow._save_structured_source = Mock(return_value=True)
    calls = []
    def call(url, headers, tool, arguments, **kwargs):
        calls.append((tool, arguments['searchKey']))
        return envelope(arguments['searchKey'], rows=[] if tool in CRITICAL else None), None
    workflow._mcp_call_tool = call
    return workflow, project, calls


def test_group_preserves_core_budget_before_company_history_and_background(monkeypatch):
    workflow, project, calls = setup(monkeypatch, 12)
    intake = {'target_type': 'person', 'target_name': '林知远'}
    collect_group(workflow, None, project, [('恒川软件有限公司', intake), ('远山科技有限公司', intake)])
    assert len(calls) == 12
    assert all((tool, company) in calls for tool in CRITICAL for company in ('恒川软件有限公司', '远山科技有限公司'))
    assert not any('historical' in tool for tool, _ in calls)
    assert all(tool in IDENTITY for tool, _ in calls[:4])
    assert all(r['status'] == 'empty_result' for r in coverage_rows(project.person_platform_attempts) if r['tool'] in CRITICAL)


def test_initial_company_cannot_exhaust_affiliation_reserve(monkeypatch):
    workflow, project, calls = setup(monkeypatch)
    intake = {'target_type': 'person', 'target_name': '林知远'}
    collect(workflow, None, project, '恒川软件有限公司', intake)
    assert len(calls) <= 10
    collect_group(workflow, None, project, [('远山科技有限公司', intake)])
    assert all((tool, '远山科技有限公司') in calls for tool in CRITICAL)
    assert len(calls) <= 18


def test_wrong_person_blocks_legal_and_company_expansion(monkeypatch):
    workflow, project, calls = setup(monkeypatch)
    def mismatch(url, headers, tool, arguments, **kwargs):
        calls.append((tool, arguments['searchKey']))
        return envelope(arguments['searchKey'], person='另一个人'), None
    workflow._mcp_call_tool = mismatch
    collect(workflow, None, project, '恒川软件有限公司', {'target_name': '林知远'})
    assert all(tool in IDENTITY for tool, _ in calls)
    assert any(r['reason'] == 'identity_not_verified' for r in project.person_platform_attempts)
    assert not workflow._save_structured_source.called


def test_role_record_is_not_a_case_record_and_summary_is_not_an_empty_result(monkeypatch):
    assert validated_records(envelope('恒川软件有限公司'), '林知远', '恒川软件有限公司', CRITICAL[0]) == (True, [])
    workflow, project, _ = setup(monkeypatch)
    def query(url, headers, tool, arguments, **kwargs):
        return envelope(arguments['searchKey'], summary_only=tool in CRITICAL), None
    workflow._mcp_call_tool = query
    collect(workflow, None, project, '恒川软件有限公司', {'target_name': '林知远'})
    assert all(r['status'] == 'returned_unresolved' for r in coverage_rows(project.person_platform_attempts) if r['tool'] in CRITICAL)


def test_lifecycle_dedup_keeps_actual_result_not_last_skip():
    rows = [dict(provider='qcc', subject='公司', tool='风险', status=s) for s in ('returned', 'collected', 'reused', 'not_queried')]
    assert coverage_rows(rows)[0]['status'] == 'records_found'


def test_explicit_provider_empty_is_scoped_and_distinct_from_summary_only():
    data = envelope('恒川软件有限公司', summary_only=True)
    doc = {'企业名称': '恒川软件有限公司', '人员名称': '林知远',
           '搜索结果': '已全量扫描该主体董监高-失信被执行人数据库，未发现任何记录。'}
    data['result']['content'][0]['text'] = json.dumps(doc)
    assert response_state(data) == 'explicit_empty_record_list'
    assert not response_state(envelope('恒川软件有限公司', summary_only=True))


def test_region_restriction_stops_only_this_subject_not_the_account(monkeypatch):
    workflow, project, calls = setup(monkeypatch)
    def restricted(url, headers, tool, arguments, **kwargs):
        calls.append((tool, arguments['searchKey']))
        data = {'地域限制': '当前区域不能提供该主体记录'} if arguments['searchKey']=='受限公司' else {
            '企业名称': arguments['searchKey'], '人员名称': '林知远', '记录': [{'企业名称': arguments['searchKey'], '角色': ['董事']}]}
        return {'result': {'content': [{'type': 'text', 'text': json.dumps(data)}]}}, None
    workflow._mcp_call_tool = restricted
    collect(workflow, None, project, '受限公司', {'target_name': '林知远'})
    assert len(calls) == 1
    assert any(r['reason']=='regional_restriction' and r['status']=='failed' for r in project.person_platform_attempts)
    collect(workflow, None, project, '正常公司', {'target_name': '林知远'})
    assert any(company=='正常公司' for _, company in calls)


def test_shared_surname_relative_and_general_marketing_do_not_fill_credit_or_peers():
    text = '林先生现持有10万股，林先生为本公司董事长林知远先生的兄长。'
    record = observation({'fact': text}, '林知远')
    assert record['subject_scope']=='other_person' and '兄长' in record['subject']
    assert not chapter_relevant({'fact': '林知远秉持创新理念，打造具有全球竞争力的产品。'}, 8)
    assert not chapter_relevant({'fact': '董事会授权林知远依证券监管部门规定制定融资方案。'}, 12)
    assert chapter_relevant({'fact': '监管调查发现林知远涉嫌违规。'}, 12)


def test_failed_affiliation_releases_budget_for_next_verified_subject(monkeypatch):
    workflow, project, calls = setup(monkeypatch, 8)
    original = workflow._mcp_call_tool
    def first_restricted(url, headers, tool, arguments, **kwargs):
        if arguments['searchKey']=='受限公司':
            calls.append((tool, '受限公司'))
            return {'result': {'content': [{'text': json.dumps({'地域限制': '限制'})}]}}, None
        return original(url, headers, tool, arguments, **kwargs)
    workflow._mcp_call_tool = first_restricted
    value={'target_name':'林知远','target_type':'person'}
    collect_group(workflow,None,project,[('受限公司',value),('正常公司',value)])
    assert all((tool,'正常公司') in calls for tool in CRITICAL)
    assert len(calls)<=8


def test_xiniu_transient_retry_uses_same_total_budget_and_does_not_loop(monkeypatch):
    workflow, project, calls = setup(monkeypatch, 20)
    monkeypatch.setenv('XINIU_API_KEY','synthetic-xiniu')
    monkeypatch.setenv('PERSON_PLATFORM_AFFILIATION_RESERVE','0')
    original=workflow._mcp_call_tool
    attempts=[]
    def fail_once(url,headers,tool,args,**kwargs):
        if 'xiniudata' in url:
            attempts.append(tool)
            return ({'error':{'message':'temporary request failure'}} if len(attempts)==1 else envelope('恒川软件有限公司')),None
        return original(url,headers,tool,args,**kwargs)
    workflow._mcp_call_tool=fail_once
    collect(workflow,None,project,'恒川软件有限公司',{'target_name':'林知远','focus_questions':['融资']})
    assert len(attempts)==2 and len(project.person_platform_query_keys)<=20
    assert any(r['provider']=='xiniu' and r['status']=='collected' for r in project.person_platform_attempts)


def test_person_postprocessing_preserves_source_wording_and_inline_review_marker():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    report = '## 9. 关联司法\n原文：未履约，涉嫌违反《合同法》第三条。\n【待复核】需要补证。\n## 15. 后续研究点\n核对原件。'
    assert workflow._consolidate_report_verification_gaps(report, target_type='person') == report
