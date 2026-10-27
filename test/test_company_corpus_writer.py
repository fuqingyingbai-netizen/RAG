import copy
import hashlib
import json
from types import SimpleNamespace

from report_agents.company_corpus import VERSION,source_input_fingerprint
from report_agents.company_corpus_writer import (
    corpus_cache_matches,collect_statements,build_compact_digest,condense_groups,
    render_compact_chapters,update_evidence_diagnostics,
)


def test_attributed_platform_numbers_are_not_a_blocked_source_class():
    from report_agents.company_corpus_writer import _prose_errors
    record={'text':'企查查页面载明注册资本1000万元；注册资本不是实缴或融资到账。',
            'context':{'source_kind':'professional_platform_record'},'origin':'literal_original_statement'}
    assert not _prose_errors('企查查所载注册资本为1000万元，该字段不代表融资到账。',[record])
    assert 'nonprimary_numeric_claim_requires_explicit_attribution' in _prose_errors('注册资本为1000万元。',[record])
    assert 'new_or_changed_number_unit' in _prose_errors('企查查所载注册资本为2000万元。',[record])


def test_one_batch_cannot_assert_that_the_whole_corpus_lacks_a_fact():
    from report_agents.company_corpus_writer import _prose_errors
    record={'text':'公司在本页说明技术合作。','context':{},'origin':'literal_original_statement'}
    assert 'batch_cannot_assert_whole_corpus_gap' in _prose_errors('现有材料未提供官方成立日或股权控制文件。',[record])
from report_agents.company_report_agent import COMPANY_REPORT_OUTLINE

TARGET='杭州深度求索人工智能基础技术研究有限公司'
EID='E-111111111111'


def fixture():
    text=TARGET+'在原页披露董事会审计委员会负责审核相关政策及重大事项，此处仅说明已披露职责，不等于实际执行有效。'
    source=dict(id=1,url='https://issuer.example/original',title=TARGET,content=text,source_metadata={'content_kind':'full_text'})
    record=dict(source_id='1',source_url=source['url'],source_title=TARGET,evidence_id=EID,evidence_ids=[EID],
        fact=text,chapter=4,scope='target',source_kind='issuer_disclosure',period='原页时点待核',original_offset=0)
    review=dict(version=VERSION,target_name=TARGET,research_as_of='2026-10-20',facts=[record],
        source_review={'1':{'original_sha256':hashlib.sha256(text.encode()).hexdigest(),
                            'source_input_sha256':source_input_fingerprint(source),'source_kind':'issuer_disclosure'}},
        diagnostic={'all_candidate_windows_reviewed':True})
    p=SimpleNamespace(target_name=TARGET,sources=[source],company_research_intake={'as_of_date':'2026-10-20'})
    return p,review


def test_same_source_bytes_are_insufficient_when_the_research_cutoff_or_completion_differs():
    p,r=fixture();assert corpus_cache_matches(p,r)
    r['facts'][0]['original_offset']=1;assert not corpus_cache_matches(p,r)
    r['facts'][0]['original_offset']=0
    p.company_research_intake['as_of_date']='2026-10-19';assert not corpus_cache_matches(p,r)
    p.company_research_intake['as_of_date']='2026-10-20';r['diagnostic']['all_candidate_windows_reviewed']=False
    assert not corpus_cache_matches(p,r)
    r['diagnostic']['all_candidate_windows_reviewed']=True;p.sources[0]['content']+='修订'
    assert not corpus_cache_matches(p,r)


def test_specialized_platform_fields_retain_platform_attribution_in_synthesis_inputs():
    p,r=fixture();r['source_review']['1']['source_kind']='professional_platform_record'
    p.company_governance_package={'facts':[dict(evidence_id=EID,evidence_ids=[EID],source_url=p.sources[0]['url'],
        kind='registry',field='注册资本',value='1000万元',period='原页时点待核')]}
    statements=collect_statements(p,r)
    assert next(v for v in statements if v['origin']=='specialized_checked_record')['context']['source_kind']=='professional_platform_record'


def test_unverified_summary_cannot_turn_an_input_source_into_a_body_citation():
    p,r=fixture()
    def invoke(role,prompt,trace):
        if role=='公司多来源归纳 Agent':
            records=json.loads(prompt.split('记录：\n',1)[1])
            return json.dumps({'groups':[dict(group_id='x',aspect='决策机制',summary='董事会审计委员会负责审核相关政策及重大事项，这一披露仅说明职责安排，实际执行仍需结合相应会议与审核记录核对。',statement_ids=[records[0]['statement_id']])],'appendix':[]})
        if role=='公司归纳独立核对 Agent':
            groups=json.loads(prompt.split('资料：\n',1)[1])
            return json.dumps({'groups':[dict(group_id=g['group_id'],status='unsupported',reason='unsupported example') for g in groups]})
        return json.dumps({'groups':[]})
    result=build_compact_digest(p,r,COMPANY_REPORT_OUTLINE,invoke,lambda *a,**k:None)
    assert not result['groups'] and result['diagnostic']['body_sources']==0
    assert result['appendix_statements'][0]['evidence_ids']==[EID]
    assert result['diagnostic']['unaccounted_statement_ids']==[]


def test_invented_number_is_rejected_before_prose_can_be_approved():
    p,r=fixture();calls=[]
    def invoke(role,prompt,trace):
        calls.append(role);records=json.loads(prompt.split('记录：\n',1)[1])
        return json.dumps({'groups':[dict(aspect='决策机制',summary='委员会已召开999次会议并保证所有决策有效。',statement_ids=[records[0]['statement_id']])],'appendix':[]})
    result=build_compact_digest(p,r,COMPANY_REPORT_OUTLINE,invoke,lambda *a,**k:None)
    assert not result['groups'] and calls==['公司多来源归纳 Agent']


def test_compaction_keeps_all_parent_sources_or_retains_the_original_checked_groups():
    groups=[dict(group_id=f'G{i}',chapter=4,aspect='决策机制',summary=('委员会披露的职责与运行安排需要按原页时点分别核对，不能合并为全公司已执行有效的结论。'*5),statement_ids=[f'T{i}'],evidence_ids=[f'E-{i:012X}']) for i in range(3)]
    def invoke(role,prompt,trace):return json.dumps({'paragraphs':[dict(summary='材料反映委员会的职责安排，执行效果仍需逐项核对。',group_ids=['G0','G1'])]})
    new,receipts=condense_groups(groups,invoke)
    assert new==groups and receipts[0]['accepted'] is False


def test_native_financial_values_and_complete_risk_dictionary_survive_compact_layout():
    p,r=fixture();financial=[dict(entity=TARGET,period='2026年半年度报告',metric='营业收入',value='1,234.56',previous_value='2,345.67',unit='元',evidence_ids=[EID])]
    p.company_assessment_package={'financial_observations':financial,'dimensions':[{'id':'revenue','score':None}]}
    p.company_risk_register_package={'checklist':[dict(id=f'ORG-{i:02}',label='测试事项',state='requires_event_evidence') for i in range(75)]}
    before=copy.deepcopy(p.company_assessment_package)
    groups=[dict(group_id='business',chapter=6,aspect='关键经营事实与风险研判',summary='原表经营指标按原期间及原单位保留。',evidence_ids=[EID]),
        dict(group_id='risk',chapter=11,aspect='75项核查目录及扩展事项',summary='核查目录用于识别核验问题，不代表已发生负面事件。',evidence_ids=[EID])]
    sections=render_compact_chapters(p,{'groups':groups},COMPANY_REPORT_OUTLINE,{6:'old',11:'old',12:'unchanged score chapter'})
    assert all(v in sections[6] for v in ['1,234.56','2,345.67','元','2026年半年度报告'])
    assert all(f'ORG-{i:02}' in sections[11] for i in range(75))
    assert p.company_assessment_package==before and sections[12]=='unchanged score chapter'


def test_new_evidence_resolves_only_the_specific_missing_record_error():
    p,r=fixture();p.company_operations_diagnostic={'errors':['第四章没有可核对的治理及运行记录','第四章存在未知证据编号'],'degraded':True}
    p.company_assessment_diagnostic={'errors':['尚无可按原件和锚点评价的公司分项，需人工复核'],'degraded':True}
    update_evidence_diagnostics(p,{'groups':[dict(group_id='G1',chapter=4,evidence_ids=[EID])]}, {4:'原文核对 ['+EID+']'})
    assert p.company_operations_diagnostic['errors']==['第四章存在未知证据编号']
    assert p.company_operations_diagnostic['degraded'] is True
    assert p.company_assessment_diagnostic['degraded'] is True


def test_outgoing_strategic_subscription_is_routed_as_investment_not_fundraising():
    from report_agents.company_corpus_writer import narrative_inputs
    record={'statement_id':'T-outgoing','chapter':10,'text':'第三方核查报告称目标公司流动资金足以覆盖其与发行人签署的战略配售认购协议所约定金额。',
            'evidence_ids':['E-111111111111'],'context':{'source_kind':'third_party_filing','scope':'third_party_about_target'},
            'origin':'literal_original_statement','source_url':'https://disclosure.test/placement'}
    inputs,_=narrative_inputs([record],COMPANY_REPORT_OUTLINE)
    assert inputs[0]['context']['aspect']=='战略布局'


def test_checked_synthesis_is_reused_only_when_native_proofs_are_identical():
    p,r=fixture()
    def invoke(role,prompt,trace):
        if role=='公司多来源归纳 Agent':
            records=json.loads(prompt.split('记录：\n',1)[1])
            return json.dumps({'groups':[dict(aspect='决策机制',summary='原页披露董事会审计委员会负责审核相关政策及重大事项；该记录说明职责安排，实际执行效果仍应结合会议与审核原件核对。',statement_ids=[records[0]['statement_id']])],'appendix':[]})
        groups=json.loads(prompt.split('资料：\n',1)[1])
        return json.dumps({'groups':[dict(group_id=g['group_id'],status='supported',reason='原文支持职责和边界') for g in groups]})
    first=build_compact_digest(p,r,COMPANY_REPORT_OUTLINE,invoke,lambda *a,**k:None)
    assert first['groups']
    first['synthesis_receipts'][0]['errors']=['another_unaccepted_proposal_in_prior_batch']
    p.company_corpus_digest_cache=first
    def forbidden(*args):raise AssertionError('validated unchanged synthesis must not be rewritten by the model')
    second=build_compact_digest(p,r,COMPANY_REPORT_OUTLINE,forbidden,lambda *a,**k:None)
    assert second['groups']==first['groups'] and second['diagnostic']['reused_checked_groups']==1
    p.company_research_intake['as_of_date']='2026-10-19'
    earlier=build_compact_digest(p,r,COMPANY_REPORT_OUTLINE,forbidden,lambda *a,**k:None)
    assert not earlier['groups'] and earlier['diagnostic']['reused_checked_synthesis_batches']==0
    p.company_research_intake['as_of_date']='2026-10-20'
    changed=copy.deepcopy(r);changed['facts'][0]['fact']+='实际职责以变更后的原件为准。'
    third=build_compact_digest(p,changed,COMPANY_REPORT_OUTLINE,forbidden,lambda *a,**k:None)
    assert not third['groups'] and third['diagnostic']['reused_checked_synthesis_batches']==0


def test_hierarchical_compaction_bounds_each_request_and_retains_all_support():
    groups=[dict(group_id=f'G{i}',chapter=4,aspect='决策机制',summary='原页披露委员会负责政策审核和重大事项审议，职责安排须与实际会议执行情况分别核对。'*5,
        statement_ids=[f'T{i}'],evidence_ids=[f'E-{i:012X}']) for i in range(25)]
    sizes=[]
    def invoke(role,prompt,trace):
        if role=='公司正文压缩归并 Agent':
            rows=json.loads(prompt.split('已核对材料：\n',1)[1]);sizes.append(len(rows))
            return json.dumps({'paragraphs':[dict(summary='原页披露委员会的政策审核及重大事项审议职责，实际会议执行情况仍应按相应原件核对。',group_ids=[r['group_id'] for r in rows])]})
        rows=json.loads(prompt.split('材料：\n',1)[1])
        return json.dumps({'groups':[dict(group_id=r['group_id'],status='supported',reason='保留原文职责边界') for r in rows]})
    new,receipts=condense_groups(groups,invoke)
    assert max(sizes)<=8 and len(new)<len(groups) and receipts[0]['hierarchical']
    assert {e for g in new for e in g['evidence_ids']}=={e for g in groups for e in g['evidence_ids']}
    assert {i for g in new for i in g['statement_ids']}=={i for g in groups for i in g['statement_ids']}


def test_transaction_check_can_explain_assessment_boundary_without_creating_scores():
    p,r=fixture();p.company_assessment_package={'financial_observations':[],'dimensions':[{'id':'profit','score':None}]}
    original=copy.deepcopy(p.company_assessment_package)
    context={'statement_id':'T-boundary','chapter':10,'text':'第三方经核查财务报表等文件，称其流动资金足以覆盖特定证券认购金额。',
        'context':{'source_kind':'third_party_filing','scope':'third_party_about_target'},'evidence_ids':[EID]}
    sections=render_compact_chapters(p,{'groups':[],'statements':[context]},COMPANY_REPORT_OUTLINE,{12:'## 12. 综合评价\n尚未取得评分所需原件，不赋分。'})
    assert EID in sections[12] and '不作为营收、盈利能力或公司综合评分的依据' in sections[12]
    assert p.company_assessment_package['dimensions']==original['dimensions']
    assert p.company_assessment_package['financial_observations']==original['financial_observations']
    assert p.company_assessment_context_references==[context]
    facts=p.company_assessment_package['facts']
    assert len(facts)==1 and facts[0]['kind']=='non_scoring_transaction_context'
    assert facts[0]['evidence_ids']==[EID]


def test_retained_provider_records_all_enter_writing_without_source_budget():
    from report_agents.company_corpus_writer import narrative_inputs
    rows=[{'statement_id':f'T-{i}','chapter':i,'text':f'留存原文中与主题相关的具体陈述{i}。','evidence_ids':[EID],
        'context':{'retrieval_mode':'retained_provider_text','source_kind':'attributed_publication'},
        'origin':'literal_original_statement','source_url':'https://retained.test/annual'} for i in range(2,12)]
    inputs,details=narrative_inputs(rows,COMPANY_REPORT_OUTLINE)
    assert len(inputs)==10 and not details
    assert {r['statement_id'] for r in inputs+details}=={r['statement_id'] for r in rows}
    for row in rows:row['origin']='specialized_checked_record'
    inputs,details=narrative_inputs(rows,COMPANY_REPORT_OUTLINE)
    assert len(inputs)==10 and not details


def test_same_source_topic_can_have_many_independent_facts():
    from report_agents.company_corpus_writer import narrative_inputs
    rows=[{'statement_id':f'T-{i}','chapter':6,'text':f'平台所载产品{i}在原期间完成交付。',
        'evidence_ids':[EID],'context':{'aspect':'关键经营事实与风险研判'},
        'origin':'literal_original_statement','source_url':'https://platform.test/company'} for i in range(30)]
    inputs,details=narrative_inputs(rows,COMPANY_REPORT_OUTLINE)
    assert {r['statement_id'] for r in inputs}=={r['statement_id'] for r in rows}
    assert not details


def test_short_platform_unknown_and_zero_fields_survive_sentence_review():
    p,r=fixture()
    p.sources=[{'id':9,'url':'structured://xiniu/company','title':'平台原表','content':
        '| 字段 | 值 |\n| --- | --- |\n| 企业名称 | '+TARGET+' |\n| 公司盈利情况 | 待查 |\n| 参保人数 | 0 |',
        'source_metadata':{'provider':'xiniu','content_kind':'structured_data'}}]
    rows=collect_statements(p,{'facts':[],'source_review':{'9':{'source_kind':'professional_platform_record'}}})
    unknown=next(row for row in rows if row['context'].get('field')=='公司盈利情况')
    zero=next(row for row in rows if row['context'].get('field')=='参保人数')
    assert unknown['text']=='公司盈利情况：待查' and unknown['chapter']==12
    assert zero['text']=='参保人数：0' and zero['chapter']==8
    for row in (unknown,zero):
        quote=row['raw_record']['evidence_quote'];offset=row['raw_record']['original_offset']
        assert p.sources[0]['content'][offset:offset+len(quote)]==quote


def test_native_json_field_value_records_are_not_lost_as_short_unknown_values():
    p,r=fixture()
    p.sources=[{'id':9,'url':'structured://xiniu/company','title':'平台原表',
        'content':json.dumps({'company_name':TARGET,'fields':[{'field':'公司盈利情况','value':'待查'}]},ensure_ascii=False),
        'source_metadata':{'provider':'xiniu','content_kind':'structured_data'}}]
    rows=collect_statements(p,{'facts':[],'source_review':{'9':{'source_kind':'professional_platform_record'}}})
    row=next(r for r in rows if r['context'].get('field')=='公司盈利情况')
    assert row['text']=='公司盈利情况：待查'
    assert row['raw_record']['evidence_quote'] in p.sources[0]['content']
