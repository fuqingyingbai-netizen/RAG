import json
import pytest
from types import SimpleNamespace

from report_agents.company_corpus import prepare_corpus, build_corpus_review, _batches, disclosed_aliases
from report_agents.company_source_review import validate_selection

TARGET='杭州深度求索人工智能基础技术研究有限公司'


def source(number=1,body=None,**extra):
    return dict(id=number,url=f'https://www.tianyancha.com/company/{number}',title=TARGET,
        content=body or (TARGET+'在本页面载明注册资本为1000万元，企业登记状态为存续，字段以平台页面所列时点为准。'),
        source_metadata={'content_kind':'full_text'},**extra)


def project(sources):
    return SimpleNamespace(target_name=TARGET,sources=sources,company_research_intake={'as_of_date':'2026-10-20'})


def test_professional_original_is_not_blocked_by_provider_class_or_an_excluded_cleaner_card():
    s=source();p=project([s])
    docs,states,_=prepare_corpus(p,{'facts':[dict(source_url=s['url'],evidence_id='E-111111111111',eligible_for_report=False,exclusion_reason='cleaner_prefix_incomplete')]})
    assert docs[0]['source_kind']=='professional_platform_record'
    assert states['1']['state']=='pending_full_corpus_review'
    assert states['1']['prior_card_exclusions']==['cleaner_prefix_incomplete']
    doc=docs[0]
    fact,error=validate_selection(dict(evidence_id=doc['evidence_id'],window_id='W1',chapter=2,scope='target',relevance='登记字段'),{doc['evidence_id']:doc},TARGET)
    assert not error and fact['eligible_for_risk_scoring'] is False


def test_unknown_publisher_has_attributed_native_evidence_and_is_not_implicitly_authenticated():
    s=source();s['url']='https://independent.example/report'
    docs,_,_=prepare_corpus(project([s]),{'facts':[]})
    assert docs[0]['source_kind']=='attributed_publication'
    assert docs[0]['subject_binding']['issuer_document'] is False


def test_all_distinct_native_windows_are_reviewed_without_the_old_two_claim_limit():
    s=source(body='\n\n'.join(TARGET+f'第{i}次披露注册资本及股东变更事项，具体登记字段和原始时间按各条记录逐项核对，不能由此推断融资到账。' for i in range(25)))
    p=project([s]);prepared=prepare_corpus(p,{'facts':[]})
    assert len(prepared[0][0]['windows'])==25
    def invoke(role,prompt,trace):
        batch=json.loads(prompt.split('资料：\n',1)[1])['originals']
        return json.dumps({'decisions':[dict(evidence_id=d['evidence_id'],disposition='accepted') for d in batch],
            'facts':[dict(evidence_id=d['evidence_id'],window_id=w['window_id'],chapter=2,scope='target',relevance='变更记录') for d in batch for w in d['windows']]})
    result=build_corpus_review(p,{'facts':[]},{},invoke,lambda *a,**k:None,prepared=prepared)
    assert len(result['facts'])==25
    assert result['diagnostic']['all_candidate_windows_reviewed']
    assert result['source_review']['1']['reviewed_windows']==25


def test_exact_originals_corroborate_with_their_own_source_ids_and_urls():
    a=source(1);b=source(2,body=a['content']);p=project([a,b])
    def invoke(role,prompt,trace):
        d=json.loads(prompt.split('资料：\n',1)[1])['originals'][0]
        return json.dumps({'decisions':[dict(evidence_id=d['evidence_id'],disposition='accepted')],
            'facts':[dict(evidence_id=d['evidence_id'],window_id='W1',chapter=2,scope='target',relevance='登记字段')]})
    result=build_corpus_review(p,{'facts':[]},{},invoke,lambda *a,**k:None)
    assert len(result['facts'])==2
    assert {r['source_url'] for r in result['facts']}=={a['url'],b['url']}
    assert result['source_review']['2']['state']=='exact_original_corroboration'


def test_challenge_or_discovery_is_tracked_without_turning_it_into_a_company_fact():
    s=source(body='请完成安全验证');s['source_metadata']['content_kind']='summary_only'
    docs,states,_=prepare_corpus(project([s]),{'facts':[]})
    assert not docs and states['1']['state']=='original_not_available_discovery_only'


def test_industry_only_window_cannot_become_a_target_company_fact():
    s=source(body='全球人工智能行业的市场份额与竞争格局随评测周期变化，需要比较模型性能和不同基准测试结果，不能将行业样本直接推断到具体企业。')
    s.update(title='全球人工智能行业统计',url='https://research.example/review')
    docs,_,_=prepare_corpus(project([s]),{'facts':[]});doc=docs[0]
    row=dict(evidence_id=doc['evidence_id'],window_id='W1',chapter=5,scope='target',relevance='行业比较')
    corrected=validate_selection(row,{doc['evidence_id']:doc},TARGET)[0]
    assert corrected['scope']=='industry_context' and corrected['selection_corrections']
    row['scope']='industry_context'
    assert validate_selection(row,{doc['evidence_id']:doc},TARGET)[0]['scope']=='industry_context'


def test_oversized_unbound_table_is_recorded_and_not_silently_clipped():
    s=source(body=TARGET+'\n'+('公司股东 注册资本1234567890 '*200))
    docs,states,_=prepare_corpus(project([s]),{'facts':[]})
    assert not docs and states['1']['oversize_windows']==1


def test_brand_reference_is_not_upgraded_to_single_legal_entity():
    s=source(body='DeepSeek 用户协议\n\nDeepSeek产品及服务由'+TARGET+'及其关联公司共同所有和负责运营。\n\nDeepSeek已开源并发布新的模型架构，产品支持技术服务和软件开发，具体测试结果仍应依原始基准任务及测试版本核对。')
    s.update(url='https://cdn.deepseek.com/policies/terms',title='DeepSeek 用户协议')
    docs,_,_=prepare_corpus(project([s]),{'facts':[]});doc=docs[0]
    w=doc['windows'][-1]
    row=dict(evidence_id=doc['evidence_id'],window_id=w['window_id'],chapter=6,scope='target',relevance='开源产品')
    corrected=validate_selection(row,{doc['evidence_id']:doc},TARGET)[0]
    assert corrected['scope']=='service_joint' and corrected['selection_corrections']
    row['scope']='service_joint'
    assert validate_selection(row,{doc['evidence_id']:doc},TARGET)[0]


def test_generic_pronouns_are_never_learned_as_company_aliases():
    sources=[source(body=TARGET+'（“标的公司”）披露事项。'+TARGET+'（“公\n司”）其他事项。'+TARGET+'（“深度求索”）提供服务。')]
    aliases=disclosed_aliases(TARGET,sources)
    assert '深度求索' in aliases
    assert not {'标的公司','公司','公\n司','本公司本公司','发行人'} & set(aliases)


@pytest.mark.parametrize('legacy_version',['company-corpus-v2-native-guard-and-literal-reuse','company-corpus-v9-complete-registry-field-context'])
def test_completed_native_batches_are_revalidated_without_another_model_call(legacy_version):
    p=project([source()])
    def invoke(role,prompt,trace):
        d=json.loads(prompt.split('资料：\n',1)[1])['originals'][0]
        return json.dumps({'decisions':[dict(evidence_id=d['evidence_id'],disposition='accepted')],
            'facts':[dict(evidence_id=d['evidence_id'],window_id=d['windows'][0]['window_id'],chapter=2,scope='target',relevance='登记字段')]})
    first=build_corpus_review(p,{'facts':[]},{},invoke,lambda *a,**k:None)
    p.company_corpus_analysis_cache=first
    def forbidden(*args):raise AssertionError('same source batch must reuse its real receipt')
    second=build_corpus_review(p,{'facts':[]},{},forbidden,lambda *a,**k:None)
    assert second['facts']==first['facts']
    assert second['diagnostic']['model_requests']==0 and second['diagnostic']['cached_review_batches']==1
    import hashlib
    first['version']=legacy_version
    batch=list(_batches(prepare_corpus(p,{'facts':[]})[0]))[0]
    first['review_receipts'][0]['input_sha256']=hashlib.sha256((first['version']+'\n'+TARGET+'\n2026-10-20\n'+json.dumps(batch,ensure_ascii=False,sort_keys=True)).encode()).hexdigest()
    migrated=build_corpus_review(p,{'facts':[]},{},forbidden,lambda *a,**k:None)
    assert migrated['facts']==first['facts'] and migrated['diagnostic']['cached_review_batches']==1


def test_research_scope_reaches_review_and_invalidates_receipts_when_changed():
    from report_agents.company_corpus_writer import corpus_cache_matches
    p = project([source()])
    p.industry = '海洋工程服务'
    p.company_research_intake.update(focus_questions=['核查工程交付与回款'], special_requirements='保留地区边界')
    prompts = []

    def invoke(role, prompt, trace):
        prompts.append(prompt)
        doc = json.loads(prompt.split('资料：\n', 1)[1])['originals'][0]
        return json.dumps({'decisions': [dict(evidence_id=doc['evidence_id'], disposition='accepted')],
            'facts': [dict(evidence_id=doc['evidence_id'], window_id=doc['windows'][0]['window_id'],
                           chapter=2, scope='target', relevance='登记字段')]})

    first = build_corpus_review(p, {}, {}, invoke, lambda *a, **k: None)
    assert '海洋工程服务' in prompts[0] and '核查工程交付与回款' in prompts[0]
    assert '保留地区边界' in prompts[0]
    assert corpus_cache_matches(p, first)
    p.company_corpus_analysis_cache = first
    same = build_corpus_review(p, {}, {}, invoke, lambda *a, **k: None)
    assert same['diagnostic']['model_requests'] == 0
    p.industry = '办公协同软件'
    assert not corpus_cache_matches(p, first)
    changed = build_corpus_review(p, {}, {}, invoke, lambda *a, **k: None)
    assert changed['diagnostic']['model_requests'] == 1
    assert '办公协同软件' in prompts[-1]
    p.industry = '海洋工程服务'
    p.company_research_intake['focus_questions'] = ['核查海外项目的合同范围']
    assert not corpus_cache_matches(p, first)
    refocused = build_corpus_review(p, {}, {}, invoke, lambda *a, **k: None)
    assert refocused['diagnostic']['model_requests'] == 1
    assert '核查海外项目的合同范围' in prompts[-1]


def test_complete_native_sentence_retains_page_boundary_and_exact_offsets():
    from report_agents.company_corpus import _complete_sentence_spans
    raw='上一句。\n根据'+TARGET+'提供的2025年度审\n\n--- PDF page 12 ---\n12\n计报告及2026年6月末财务报表等文件并经核查，其流动资金足以覆盖特定战略配售认购协议约定金额。\n其他内容。'
    start,quote=next((i,q) for i,q in _complete_sentence_spans(raw) if '流动资金' in q)
    assert raw[start:start+len(quote)]==quote and '--- PDF page 12 ---' in quote
    s=source(body=raw);docs,_,_=prepare_corpus(project([s]),{},sentence_recovery=True)
    doc=next(d for d in docs if any(w['quote']==quote for w in d['windows']))
    w=next(w for w in doc['windows'] if w['quote']==quote)
    fact,error=validate_selection(dict(evidence_id=doc['evidence_id'],window_id=w['window_id'],chapter=10,
        scope='third_party_about_target',relevance='仅为特定认购金额资金核查'),{doc['evidence_id']:doc},TARGET)
    assert not error and fact['fact']==quote and fact['eligible_for_risk_scoring'] is False


def test_profile_table_offsets_account_for_leading_blank_lines_and_indentation():
    from report_agents.company_corpus import _profile_table_spans
    raw='主体信息\n\n  | 字段 | 值 |\n  | --- | --- |\n  | 企业名称 | '+TARGET+' |\n  | 注册资本 | 1000万元 |\n'
    spans=list(_profile_table_spans(raw))
    assert spans
    assert all(raw[start:start+len(quote)]==quote for start,quote in spans)


def test_retained_provider_text_keeps_receipt_boundary_and_summary_stays_a_lead():
    s=source(body=TARGET+'披露董事会负责审核重大事项并安排内部审计流程，具体执行效果仍应结合会议及整改记录核对。')
    s['source_metadata']['retained_provider_receipt']={'line':10,'path':'retained-results.jsonl'}
    docs,_,_=prepare_corpus(project([s]),{});doc=docs[0];w=doc['windows'][0]
    fact,error=validate_selection(dict(evidence_id=doc['evidence_id'],window_id=w['window_id'],chapter=4,scope='target',relevance='留存职责描述'),{doc['evidence_id']:doc},TARGET)
    assert not error and '本轮未独立回取原页' in fact['boundary'] and not doc['document_date_proof']
    s['source_metadata']['content_kind']='search_summary'
    docs,states,_=prepare_corpus(project([s]),{})
    assert not docs and states['1']['state']=='original_not_available_discovery_only'


def test_duplicate_provider_body_keeps_its_own_receipt_and_period_boundary():
    from report_agents.company_corpus_writer import corpus_cache_matches
    first=source(body=TARGET+'披露董事会负责政策审核及重大事项审议，执行效果应以会议和审核原件为依据。')
    second={**first,'id':2,'url':'https://mirror.test/annual','source_metadata':{'content_kind':'full_text',
        'retained_provider_receipt':{'line':20,'path':'existing-receipts.jsonl'}}}
    p=project([first,second])
    def invoke(role,prompt,trace):
        doc=json.loads(prompt.split('资料：\n',1)[1])['originals'][0]
        return json.dumps({'decisions':[{'evidence_id':doc['evidence_id'],'disposition':'accepted'}],
            'facts':[{'evidence_id':doc['evidence_id'],'window_id':doc['windows'][0]['window_id'],'chapter':4,'scope':'target','relevance':'职责披露'}]})
    package=build_corpus_review(p,{}, {},invoke,lambda *a,**k:None)
    duplicate=next(r for r in package['facts'] if r['source_id']=='2')
    assert duplicate['subject_binding']['retained_provider_receipt']==second['source_metadata']['retained_provider_receipt']
    assert '未独立回取原页' in duplicate['boundary'] and duplicate['period'].startswith('既有检索服务')
    assert corpus_cache_matches(p,package)
    duplicate['subject_binding'].pop('retained_provider_receipt')
    assert not corpus_cache_matches(p,package)
