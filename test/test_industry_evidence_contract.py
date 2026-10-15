import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from industry_evidence import (VERSION,evidence_requirements,source_coverage,attach_provenance,
    fact_coverage,diverse_evidence,claim_ledger,source_fingerprint)


def source(body='2025年我国机器人市场规模为100亿元。',module='市场规模与增长',url='https://stats.example/r',scope='industry_level'):
    return SimpleNamespace(id=1,url=url,title='机器人研究',content=body,summary='',source_type='government',
        source_metadata={'module':module,'evidence_scope':scope},credibility_score=90)


def fact(text='2025年我国机器人市场规模为100亿元。',eid='E-1234567890AB',module='市场规模与增长',url='https://stats.example/r'):
    return {'evidence_id':eid,'fact':text,'evidence_quote':text,'source_url':url,'module':module,
        'scope_match':'in_scope','evidence_scope':'industry_level','claim_type':'industry_metric','cleaning_method':'industry_rule',
        'numeric_context':{'metric':'市场规模','value':100,'unit':'亿元','geography':'中国大陆','period':'2025',
            'definition':'机器人市场','is_forecast':False},'numeric_validation':{'passed':True}}


CASES=json.loads((Path(__file__).parent/'fixtures/industry_evidence_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case',CASES,ids=[x['name'] for x in CASES])
def test_retrieval_benchmark_candidates_never_confuse_summary_or_samples(case):
    s=source(case['body'],case['module'],scope=case.get('scope','industry_level'));s.summary=case.get('summary','')
    requirements=evidence_requirements([case['module']])
    result=source_coverage([s],requirements)
    assert {r['requirement_id'] for r in result['requirements'] if r['status']=='candidate'}==set(case['expected_candidate'])
    assert all(not r['verified_evidence_ids'] for r in result['requirements'])


def test_requirement_scope_respects_selected_modules_and_capital_switch():
    req=evidence_requirements([{'name':'竞争格局与代表企业'},{'name':'投融资与资本市场'}],{'capital_market':'none'})
    assert {r['id'] for r in req}=={'concentration','market_share'}
    assert evidence_requirements(['不存在的模块'])==[]


def test_candidate_documents_deduplicate_url_variants():
    req=evidence_requirements(['市场规模与增长'])
    result=source_coverage([source(),source(url='http://www.stats.example/r?utm_source=x#table')],req)
    assert result['requirements'][0]['candidate_document_count']==1


def test_source_snapshot_invalidates_body_or_scope_changes_but_not_duplicate_rows():
    a=source();b=source();b.id=99;b.summary='不同的搜索摘要'
    original=source_fingerprint([a])
    assert source_fingerprint([b,a])==original
    b.content+='新增产业统计。'
    assert source_fingerprint([a,b])!=original
    b.content=a.content;b.source_metadata['evidence_scope']='representative_company'
    assert source_fingerprint([a,b])!=original


def test_new_industry_index_does_not_embed_quarantined_facts(monkeypatch):
    from research_workflow import ResearchWorkflow
    import sys
    captured=[]
    monkeypatch.setitem(sys.modules,'milvus_writer',SimpleNamespace(
        MilvusWriter=lambda:SimpleNamespace(write_documents=lambda docs:captured.extend(docs))))
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    good=fact();bad={**fact(eid='E-AAAAAAAAAAAA'),'fact':'不应进入索引的虚构事实','eligible_for_report':False}
    count=w._index_cleaned_facts(SimpleNamespace(id=1,target_type='industry',target_name='机器人',industry='机器人'),
        json.dumps({'facts':[good,bad]}),1,'facts-key')
    assert count==1 and len(captured)==1 and '虚构' not in captured[0]['text']


def test_original_body_locators_and_hash_are_reproducible():
    s=source(body='原文开始\n2025年我国机器人市场规模为100亿元。\n原文结束')
    f=attach_provenance([fact()],[s])[0];loc=f['provenance']['locator']
    assert loc['status']=='verified' and loc['source_id']==1
    assert s.content[loc['start']:loc['end']]==loc['quote']==f['evidence_quote']
    assert loc['body_sha256']==hashlib.sha256(s.content.encode()).hexdigest()
    assert 'provenance' not in fact()  # no mutation of caller input


def test_whitespace_normalized_quotes_still_use_raw_body_offsets():
    s=source(body='前言\n2025年 我国机器人市场规模为\n100亿元。')
    f=fact(text='2025年 我国机器人市场规模为 100亿元。')
    loc=attach_provenance([f],[s])[0]['provenance']['locator']
    assert loc['status']=='verified' and s.content[loc['start']:loc['end']]==loc['quote']


def test_search_summary_and_invented_quote_cannot_get_verified_locator():
    s=source(body='正文没有该数字');s.summary=fact()['fact']
    f=attach_provenance([fact()],[s])[0]
    assert f['provenance']['locator']['status']=='unlocated'
    coverage=fact_coverage([f],evidence_requirements(['市场规模与增长']))
    assert coverage['requirements'][0]['status']=='candidate'


def test_body_field_marked_as_search_summary_is_not_primary_evidence():
    s=source();s.source_metadata['content_kind']='summary_only'
    coverage=source_coverage([s],evidence_requirements(['市场规模与增长']))
    assert coverage['requirements'][0]['status']=='missing'
    assert attach_provenance([fact()],[s])[0]['provenance']['locator']['status']=='unlocated'


def test_pdf_spacing_and_case_normalization_preserve_raw_locator():
    s=source(body='2025年我 国机器人AI市场规模为100亿元。')
    loc=attach_provenance([fact(text='2025年我国机器人ai市场规模为100亿元。')],[s])[0]['provenance']['locator']
    assert loc['status']=='verified' and loc['match_mode']=='whitespace_case_normalized'
    assert s.content[loc['start']:loc['end']]==loc['quote']


def test_industry_fast_excerpt_uses_body_and_never_synthetic_summary():
    from research_workflow import ResearchWorkflow
    w=ResearchWorkflow.__new__(ResearchWorkflow);w._extract_image_urls=lambda *a:[]
    w._is_structured_professional_source=lambda *a:False
    s=source(body='2025年我国机器人市场规模为100亿元。'+'这是原文段落。'*70)
    s.summary='模型摘要：机器人市场规模9999亿元，无法在正文找到。'
    result=w._fast_clean_sources([s],SimpleNamespace(target_type='industry',target_name='机器人'))
    assert len(result['facts'])==1
    f=result['facts'][0]
    assert '9999' not in f['fact'] and '[truncated]' not in f['evidence_quote']
    assert attach_provenance([f],[s])[0]['provenance']['locator']['status']=='verified'
    s.content=''
    assert w._fast_clean_sources([s],SimpleNamespace(target_type='industry',target_name='机器人'))['facts']==[]


def test_unlocated_facts_are_retained_for_audit_but_quarantined_from_scoring_and_writing():
    from research_workflow import ResearchWorkflow
    w=ResearchWorkflow.__new__(ResearchWorkflow);w._active_industry_sources=lambda p:[source('没有该数字')]
    p=SimpleNamespace(target_type='industry')
    payload=json.loads(w._prepare_industry_evidence(p,json.dumps({'facts':[fact()]}),
        {'evidence_requirements':evidence_requirements(['市场规模与增长'])}))
    f=payload['facts'][0]
    assert f['eligible_for_report'] is False and f['eligible_for_risk_scoring'] is False
    assert f['provenance']['quarantine_reason']=='unlocated_source_quote'
    assert payload['evidence_coverage']['requirements'][0]['status']=='missing'


def test_structured_platform_snapshots_can_be_located_without_becoming_industry_evidence():
    s=source(url='structured://platform/company/1',scope='representative_company')
    f=fact(url=s.url);f['evidence_scope']='representative_company'
    located=attach_provenance([f],[s])[0]
    assert located['provenance']['locator']['status']=='verified'
    assert fact_coverage([located],evidence_requirements(['市场规模与增长']))['requirements'][0]['status']=='missing'


def test_cleaned_metric_gaps_prevent_source_count_shortcut_but_stale_scope_is_ignored():
    from research_workflow import ResearchWorkflow
    w=ResearchWorkflow.__new__(ResearchWorkflow);w._active_industry_sources=lambda p:[source('2025年机器人市场规模100亿元，同比增长20%。')]
    scope={'geography':'中国大陆'};p=SimpleNamespace(industry_scope=scope)
    previous={'industry_scope':scope,'evidence_coverage':{'version':VERSION,
        'information_gaps':['市场规模与增长：增长率缺证 [需求:growth]']}}
    w._latest_artifact=lambda *a:SimpleNamespace(content=json.dumps(previous))
    plan={'evidence_requirements':evidence_requirements(['市场规模与增长'])}
    assert any('[需求:growth]' in g for g in w._industry_retrieval_gaps(p,plan))
    previous['industry_scope']={'geography':'欧洲'}
    assert not w._industry_retrieval_gaps(p,plan)


@pytest.mark.parametrize('change',[{'claim_type':'source_excerpt'}, {'numeric_validation':{'passed':False}},
    {'evidence_scope':'representative_company'}])
def test_quote_location_alone_never_proves_metric_or_industry_scope(change):
    f=attach_provenance([{**fact(),**change}],[source()])[0]
    row=fact_coverage([f],evidence_requirements(['市场规模与增长']))['requirements'][0]
    assert row['status']!='verified'


def test_complete_metric_with_original_locator_can_fulfill_requirement():
    f=attach_provenance([fact()],[source()])[0]
    row=fact_coverage([f],evidence_requirements(['市场规模与增长']))['requirements'][0]
    assert row['status']=='verified' and row['verified_evidence_ids']==[f['evidence_id']]


def test_page_number_cooccurrence_does_not_validate_wrong_metric_context():
    f=attach_provenance([fact()],[source()])[0];f['numeric_context']['metric']='企业营业收入'
    row=fact_coverage([f],evidence_requirements(['市场规模与增长']))['requirements'][0]
    assert row['status']=='candidate'


def test_selection_keeps_distinct_documents_instead_of_filling_from_one_source():
    a=fact();b=fact(eid='E-1234567890AC');c=fact(eid='E-1234567890AD',url='https://other.example/r')
    selected=diverse_evidence([a,b,c],[],2)
    assert [f['evidence_id'] for f in selected]==[a['evidence_id'],c['evidence_id']]


def test_selection_reserves_space_for_uncovered_verified_metric():
    a=attach_provenance([fact()],[source()])[0]
    b={**a,'evidence_id':'E-1234567890AC'}
    c=fact(text='2025年机器人市场同比增长20%。',eid='E-1234567890AD')
    c['numeric_context'].update(metric='同比增速',value=20,unit='%')
    c=attach_provenance([c],[source(c['fact'])])[0]
    assert diverse_evidence([a,b,c],evidence_requirements(['市场规模与增长']),2)==[a,c]


def test_gap_query_targets_missing_metric_without_regenerating_whole_module():
    from research_workflow import ResearchWorkflow
    w=ResearchWorkflow.__new__(ResearchWorkflow);w._expand_search_queries=lambda *a:[]
    plan={'modules':[{'name':'竞争格局与代表企业'}],'evidence_requirements':evidence_requirements(['竞争格局与代表企业'])}
    queries=w._gap_queries(plan,{'target_type':'industry','target_name':'机器人','industry_scope':{'geography':'中国大陆'}},
        ['竞争格局与代表企业：没有集中度原文 [需求:concentration]'])
    assert len(queries)==1 and queries[0]['requirement_id']=='concentration' and 'CR3' in queries[0]['query']
    assert queries[0]['evidence_scope']=='industry_level'


def test_competition_statistics_and_annual_reports_have_separate_search_scopes():
    from research_strategies.industry import IndustryResearchStrategy
    rows=IndustryResearchStrategy().expand_search_queries({'modules':[{'name':'竞争格局与代表企业'}]},
        {'target_name':'机器人','industry':'机器人','industry_scope':{'geography':'中国大陆','capital_market':'none'}})
    assert any('CR3' in r['query'] and r['evidence_scope']=='industry_level' for r in rows)
    assert all(r['evidence_scope']=='representative_company' for r in rows if '年报' in r['query'])


@pytest.mark.parametrize('change,issue', [({},None),({'provenance':{}},'unlocated_source_quote'),
    ({'numeric_validation':{'passed':False}},'unverified_number')])
def test_claim_lineage_records_dependencies_and_never_claims_entailment(change,issue):
    f={**attach_provenance([fact()],[source()])[0],**change}
    report='## 4. 市场\n2025年我国机器人市场规模100亿元。 [E-1234567890AB]'
    diagnostic={'chapter_evidence_ids':{4:[f['evidence_id']]},'evidence_ids':[f['evidence_id']]}
    deps={'cleaned_artifact_id':10,'risk_artifact_id':11,'report_artifact_id':12}
    result=claim_ledger(report,[f],diagnostic,{},deps);row=result['claims'][0]
    assert result['dependencies']==deps and row['entailment_status']=='not_evaluated'
    assert row['claim_id'].startswith('C-') and row['line_number']==2
    assert (issue in row['issues']) if issue else row['reference_status']=='references_verified'


def test_claim_with_foreign_id_is_never_approved():
    f=fact();r=claim_ledger('## 4. 市场\n事实 [E-AAAAAAAAAAAA]',[f],{'chapter_evidence_ids':{4:[f['evidence_id']]}},{},{})
    assert 'invalid_citation' in r['claims'][0]['issues']


def test_demo_trace_requires_explicit_opt_in_and_is_marked(monkeypatch):
    from research_api import get_report_trace_summary,_is_report_trace_demo_question
    from fastapi import HTTPException
    monkeypatch.delenv('RESEARCH_DEMO_ENABLED',raising=False)
    with pytest.raises(HTTPException) as exc:asyncio.run(get_report_trace_summary('马云报告来源'))
    assert exc.value.status_code==404 and not _is_report_trace_demo_question('马云报告来源')
    monkeypatch.setenv('RESEARCH_DEMO_ENABLED','true')
    response=asyncio.run(get_report_trace_summary('马云报告来源'))
    assert response['is_demo'] is True and response['data_origin']=='static_demo'
