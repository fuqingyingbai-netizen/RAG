"""Small regressions from round six; no database, model or search needed."""
import importlib.util
import json
from pathlib import Path

import pytest

from industry_research import (claim_semantic_issues, source_document_key, normalize_risk,
    delivery_errors, risk_repair_package, append_evidence_index)


SCOPE = {'industry_name':'机器人', 'capital_market':'none'}


def fact(eid='E-0123456789AB', url='https://research.example/market', forecast=True):
    return {'evidence_id':eid, 'source_url':url, 'fact':'预计2026年机器人开发服务市场规模达到6240亿元。',
        'module':'商业模式与盈利逻辑', 'scope_match':'in_scope', 'evidence_scope':'industry_level',
        'numeric_context':{'metric':'市场规模','value':6240,'unit':'亿元','period':'2026',
            'geography':'中国大陆','definition':'机器人开发服务市场','is_forecast':forecast},
        'numeric_validation':{'passed':True}}


@pytest.mark.parametrize('variant', ['http://research.example/market#chart',
    'https://www.research.example/market/?utm_source=feed', 'https://research.example/market?spm=1'])
def test_same_document_transport_and_tracking_variants_collapse(variant):
    assert source_document_key(variant)==source_document_key(fact()['source_url'])


def test_document_query_ids_remain_distinct_and_malformed_urls_fail_closed():
    assert source_document_key('https://research.example/?id=1')!=source_document_key('https://research.example/?id=2')
    assert source_document_key('https://research.example:bad/path')==''
    assert source_document_key('structured://same/document')==''


@pytest.mark.parametrize('text', ['市场规模6240亿元，变现路径清晰。',
    '市场规模6240亿元；下一年预计保持增长。', '2026年规模6240亿元（E-0123456789AB）。'])
def test_round6_forecast_without_local_label_is_rejected(text):
    assert claim_semantic_issues(text,[fact()])[0]['code']=='forecast_presented_as_actual'


@pytest.mark.parametrize('text', ['预计2026年规模6240亿元。', '市场规模6240亿元（预测值）。',
    '预测市场规模6240亿元，有望继续增长。'])
def test_forecast_labels_and_observed_values_are_supported(text):
    assert claim_semantic_issues(text,[fact()])==[]
    assert claim_semantic_issues('市场规模6240亿元。',[fact(forecast=False)])==[]


def test_unrelated_observed_card_cannot_remove_cited_forecast_label_requirement():
    f=fact(); observed=fact('E-ABCDEF012345',forecast=False)
    assert claim_semantic_issues('市场规模6240亿元 [E-0123456789AB]',[f,observed])
    assert not claim_semantic_issues('市场规模6240亿元 [E-ABCDEF012345]',[f,observed])


def test_qualitative_claim_does_not_require_forecast_label():
    assert not claim_semantic_issues('行业采用按需调用模式。',[fact()])


@pytest.mark.parametrize('url', ['http://research.example/market#chart', 'https://news.research.example/other-report'])
def test_same_publisher_multiple_cards_cannot_claim_multi_source_agreement(url):
    rows=[fact(),fact('E-ABCDEF012345',url)]
    issues=claim_semantic_issues('多源预测一致指向扩张。',rows)
    assert issues[0]['code']=='source_corroboration_overstated' and issues[0]['publisher_count']==1


def test_distinct_publishers_pass_cardinality_but_uncited_publisher_does_not_count():
    rows=[fact(),fact('E-ABCDEF012345','https://stats.example/research')]
    assert not claim_semantic_issues('多源预测一致。',rows)
    assert claim_semantic_issues('多源预测一致 [E-0123456789AB]',rows)


@pytest.mark.parametrize('text', ['尚无多源预测一致的证据。','不能声称多源一致。','多源一致性待核验。'])
def test_negated_or_pending_corroboration_is_not_a_positive_claim(text):
    assert not claim_semantic_issues(text,[fact()])


@pytest.mark.parametrize('reason,cause', [('2026年市场规模6240亿元，变现路径清晰。','forecast_presented_as_actual'),
    ('多源预测一致，需求增加。','source_corroboration_overstated')])
def test_risk_semantic_failures_are_auditable_and_eligible_for_one_repair(reason,cause):
    f=fact();row={'name':'商业化与盈利模式风险','score':40,'reason':reason,'evidence_ids':[f['evidence_id']]}
    checked=normalize_risk({'dimensions':[row]},[f],SCOPE)
    failed=next(x for x in checked['dimensions'] if x['name']==row['name'])
    assert failed['score'] is None and failed['unknown_cause']==cause
    assert failed['validation_diagnostic']['original_reason']==reason
    package=risk_repair_package({'facts':[f], 'dimension_evidence_ids':{row['name']:[f['evidence_id']]}},checked)
    assert len(package['dimensions_to_repair'])==1
    assert package['dimensions_to_repair'][0]['semantic_issues']


def test_honest_competition_abstention_is_not_repaired_or_assigned_a_score():
    f=fact(); f.update(module='竞争格局与代表企业',fact='举行企业公平竞争座谈会。')
    row={'name':'竞争格局与集中度风险','score':None,'level':'unknown','reason':'缺少市场份额及集中度数据。','evidence_ids':[f['evidence_id']]}
    checked=normalize_risk({'dimensions':[row]},[f],SCOPE)
    assert next(x for x in checked['dimensions'] if x['name']==row['name'])['unknown_cause']=='model_abstained'
    assert not risk_repair_package({'facts':[f],'dimension_evidence_ids':{row['name']:[f['evidence_id']]}},checked)['dimensions_to_repair']


@pytest.mark.parametrize('good_repair', [True,False])
def test_risk_forecast_semantic_repair_is_once_and_still_checked(good_repair):
    from research_workflow import ResearchWorkflow
    f=fact();name='商业化与盈利模式风险';bad={'name':name,'score':40,'reason':'市场规模6240亿元。','evidence_ids':[f['evidence_id']]}
    normalized=normalize_risk({'dimensions':[bad]},[f],SCOPE);w=ResearchWorkflow.__new__(ResearchWorkflow);calls=[]
    def invoke(role,prompt,**kwargs):
        calls.append(kwargs)
        assert 'forecast_presented_as_actual' in prompt and kwargs['repair'] is True
        return json.dumps({'dimensions':[{**bad,'reason':'预计规模6240亿元。' if good_repair else bad['reason']}]})
    w._invoke_industry_risk=invoke
    result=w._repair_industry_risk(normalized,{'facts':[f],'dimension_evidence_ids':{name:[f['evidence_id']]}},[f],SCOPE)
    row=next(x for x in result['dimensions'] if x['name']==name)
    assert len(calls)==1 and (row['score']==40 if good_repair else row['score'] is None)
    assert result['validation_diagnostics']['repair']['attempts']==1


def test_report_gate_checks_qualitative_corroboration_and_forecast_after_number_markers():
    f=fact(); report='研究边界与口径\n'+'\n'.join(f'## {i}. 章节\n定性事实 [{f["evidence_id"]}]' for i in range(1,17))
    report=report.replace('## 4. 章节\n定性事实', '## 4. 章节\n多源预测一致，市场规模6240亿元（待核验）')
    indexed,diagnostic=append_evidence_index(report,{'facts':[f]},[('章节',[])]*16,
        {i:{'facts':[f]} for i in range(1,17)})
    diagnostic['chapter_evidence_ids']={i:[f['evidence_id']] for i in range(1,17)}
    issues=delivery_errors(indexed,diagnostic,SCOPE)
    assert any('预测值6240亿元' in x for x in issues)
    assert any('多源印证' in x for x in issues)
    assert diagnostic['numeric_evidence'][f['evidence_id']]['source_url']==f['source_url']


def test_section_semantic_repair_is_once_and_revalidated():
    from report_agents.industry_report_agent import IndustryReportAgent
    agent=IndustryReportAgent();f=fact();calls=[];degraded=[]
    def invoke(*args):
        calls.append(args)
        return '## 4. 市场规模\n预计2026年市场规模6240亿元。 [E-0123456789AB]'
    result=agent._validate_section('## 4. 市场规模\n市场规模6240亿元。 [E-0123456789AB]',
        {'facts':[f]},4,'市场规模',invoke,lambda *a,**k:None,None,degraded)
    assert len(calls)==1 and '预计' in result and not degraded
    assert not claim_semantic_issues(result,[f])


def test_bad_semantic_repair_falls_back_once_and_records_reason():
    from report_agents.industry_report_agent import IndustryReportAgent
    agent=IndustryReportAgent();f=fact();calls=[];degraded=[]
    bad='## 4. 市场规模\n市场规模6240亿元。 [E-0123456789AB]'
    def invoke(*args):calls.append(args);return bad
    result=agent._validate_section(bad,{'facts':[f]},4,'市场规模',invoke,lambda *a,**k:None,None,degraded)
    assert len(calls)==1 and 'forecast_presented_as_actual' in degraded[0]['repair_validation_reasons']
    assert not claim_semantic_issues(result,[f])


def load_auditor():
    spec=importlib.util.spec_from_file_location('industry_auditor',Path(__file__).resolve().parents[1]/'scripts/check_industry.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_saved_run_audit_rejects_round6_reason_without_mutating_inputs(tmp_path):
    from industry_research import summary_length
    f=fact();report='研究边界与口径\n'+'\n'.join(f'## {i}. 章节\n预计规模6240亿元。 [{f["evidence_id"]}]' for i in range(1,17))
    report,diagnostic=append_evidence_index(report,{'facts':[f]},[('章节',[])]*16,
        {i:{'facts':[f]} for i in range(1,17)})
    risk={'dimensions':[{'name':'商业化与盈利模式风险','score':40,'reason':'市场规模6240亿元。','evidence_ids':[f['evidence_id']]}]}
    files={'cleaned_facts.json':json.dumps({'facts':[f],'industry_scope':SCOPE}),
        'risk_assessment.json':json.dumps(risk),'desktop_report.md':report,
        'proposal.md':'\n'.join(f'## {i}. 章\n正文' for i in range(1,8)),
        'monitor-evidence-summary.json':json.dumps({'desktop_report':{'metadata':{
            'delivery_status':'review_draft','industry_evidence_diagnostic':diagnostic}}})}
    for name,content in files.items():(tmp_path/name).write_text(content,encoding='utf-8')
    before={name:(tmp_path/name).read_bytes() for name in files}
    result=load_auditor().audit_saved_run(tmp_path)
    assert result['has_new_findings'] and result['newly_rejected_risks'][0]['cause']=='forecast_presented_as_actual'
    assert result['model_calls']==result['search_calls']==result['database_writes']==0
    assert result['summary_visible_chars']==summary_length('## 1. 摘要\n预计规模6240亿元。 [E-0123456789AB]')
    assert before=={name:(tmp_path/name).read_bytes() for name in files}


def test_audit_cli_refuses_overwriting_saved_artifacts(tmp_path):
    with pytest.raises(SystemExit) as exc:
        load_auditor().main(['--replay-only','--replay',str(tmp_path),'--output',str(tmp_path/'risk_assessment.json')])
    assert exc.value.code==2 and not list(tmp_path.iterdir())
