import copy
import json

from person_material_routing import review_unassigned,apply_routing,routing_complete
from person_prose_budget import resource_only_omission_reason


def fixture(count=300):
    facts=[{'evidence_id':f'E-GLOBAL{i:04d}','fact':f'1994年首家门店事项{i}。',
        'subject':'林知远','subject_scope':'person','source_url':f'https://fixture.invalid/{i}'} for i in range(count)]
    return {'target_name':'林知远','facts':facts,'chapters':{n:{'chapter':n,'title':str(n),
        'task':'按时间梳理经历','facts':[],'research_facts':[]} for n in range(2,13)}}


def test_all_three_hundred_keyword_leftovers_are_routed_without_mutating_sources():
    contract=fixture();original=copy.deepcopy(contract['facts']);seen=[]
    def invoke(role,prompt,*args):
        packet=json.loads(prompt.splitlines()[-1]);seen.extend(packet['review_evidence_ids'])
        return json.dumps({'routings':[{'evidence_id':f['evidence_id'],'action':'chapter','chapter':2,
            'reason':'首家门店开业是职业创业经历的重要事件。'} for f in packet['facts']]})
    audit=review_unassigned(contract,'林知远',invoke)
    assert len(seen)==len(set(seen))==300 and audit['status']=='passed'
    apply_routing(contract,audit)
    assert routing_complete(contract) and len(contract['chapters'][2]['research_facts'])==300
    assert all(f['analysis_allowed'] for f in contract['chapters'][2]['research_facts'])
    assert contract['facts']==original


def test_semantic_routes_preserve_original_scope_opinion_and_conflict_permissions():
    contract=fixture(5);facts=contract['facts']
    facts[1]['subject_scope']='company_context';facts[2]['opinion_only']=True
    facts[3]['source_text_issue']='garbled';contract['conflicts']=[{'evidence_ids':[facts[4]['evidence_id']]}]
    def invoke(role,prompt,*args):
        packet=json.loads(prompt.splitlines()[-1])
        return json.dumps({'routings':[{'evidence_id':f['evidence_id'],'action':'chapter','chapter':5,
            'reason':'具体岗位和用人事件应进入本章进一步核验。'} for f in packet['facts']]})
    audit=review_unassigned(contract,'林知远',invoke);apply_routing(contract,audit)
    assert [f['analysis_allowed'] for f in contract['chapters'][5]['research_facts']]==[True,False,False,False,False]


def test_cached_decisions_require_unchanged_sources_questions_and_valid_scope():
    contract=fixture(1)
    def invoke(role,prompt,*args):
        return json.dumps({'routings':[{'evidence_id':'E-GLOBAL0000','action':'chapter','chapter':2,
            'reason':'首家门店开业是职业创业经历的重要事件。'}]})
    old=review_unassigned(contract,'林知远',invoke)
    def forbidden(*args):raise AssertionError('model called')
    assert review_unassigned(contract,'林知远',forbidden,previous=old,allow_model=False)['status']=='passed'
    broken=copy.deepcopy(old);broken['rows'][0]['chapter']=99
    assert review_unassigned(contract,'林知远',forbidden,previous=broken,allow_model=False)['status']=='pending'
    contract['chapters'][2]['task']='只核对学历'
    assert review_unassigned(contract,'林知远',forbidden,previous=old,allow_model=False)['status']=='pending'
    apply_routing(contract,old)
    assert not routing_complete(contract)


def test_source_equivalence_requires_issuer_and_period_and_source_to_match():
    contract=fixture(2);a,b=contract['facts'];b.update({**a,'evidence_id':b['evidence_id']})
    contract['chapters'][2]['research_facts']=[a]
    audit=review_unassigned(contract,'林知远',None,allow_model=False);apply_routing(contract,audit)
    assert routing_complete(contract)
    contract['facts'][1]['source_document_issuer']='另一家公司'
    audit=review_unassigned(contract,'林知远',None,allow_model=False);apply_routing(contract,audit)
    assert not routing_complete(contract)


def test_substantive_appendix_reasons_are_not_rejected_for_negating_length_limits():
    reasons=['原文仅为两个木匠的儿子访谈场景及成长背景介绍，没有实际任期、授权或人员冲突事件，作为成长经历背景补充细节留附录，不占正文分析篇幅。',
        '原文是公司对岗位变动所作服务于战略发展的概括说明，没有新的日期、职责或权限信息，实际人事变动已保留；属于解释性背景细节，并非因为字数、条数或已有来源而舍弃。']
    assert all(not resource_only_omission_reason(r) for r in reasons)
    assert all(resource_only_omission_reason(r) for r in ['字数太多所以留附录','来源已经足够，保留附录。','并非因字数限制而舍弃，留附录。'])


def test_material_diagnosis_keeps_issuer_and_period_in_target_and_shown_context():
    from person_material_accounting import diagnose_material
    fact={'evidence_id':'E-GLOBAL0000','fact':'本公司董事长。','subject_scope':'person','analysis_allowed':True,
        'subject':'林知远','source_document_issuer':'甲公司','source_reporting_period_literal':'2023年度','published_at':'2024-03-01'}
    other={**fact,'evidence_id':'E-GLOBAL0001','source_document_issuer':'乙公司','source_reporting_period_literal':'2024年度'}
    p={'chapter':5,'title':'管理','facts':[fact,other],'required_source_displays':[{'evidence_id':other['evidence_id'],'quote':other['fact']}]}
    def invoke(role,prompt,*args):
        packet=json.loads(prompt.splitlines()[-1])
        assert packet['facts'][0]['source_document_issuer']=='甲公司'
        shown=packet['source_display_quotes'][0]
        assert shown['source_document_issuer']=='乙公司' and shown['source_reporting_period_literal']=='2024年度'
        assert 'evidence_id' not in shown and shown['shown_evidence_id']==other['evidence_id']
        return json.dumps({'material_reviews':[{'evidence_id':f['evidence_id'],'disposition':'appendix',
            'reason':'原文只有职务名称及不同机构归属，未提供具体任职事件时间，作为职责定位的补充线索，留附录不占分析篇幅。'} for f in packet['facts']]})
    assert diagnose_material(p,[],invoke,None)['status']=='passed'


def test_batch_budget_counts_actual_review_fields_without_dropping_originals():
    from person_material_accounting import diagnose_material
    facts=[{'evidence_id':f'E-GLOBAL{i:04d}','fact':f'林知远补充经历{i}。','subject_scope':'person',
        'analysis_allowed':True,'internal_duplicate_proof':'同一段内部检索数据'*2000,
        'source_document_issuer':'甲公司'} for i in range(16)]
    p={'chapter':2,'title':'背景','facts':facts};packets=[]
    def invoke(role,prompt,*args):
        packet=json.loads(prompt.splitlines()[-1]);packets.append(packet)
        assert all('internal_duplicate_proof' not in f for f in packet['facts'])
        return json.dumps({'material_reviews':[{'evidence_id':f['evidence_id'],'disposition':'appendix',
            'reason':'仅为未给出细节的补充经历线索，没有实际任职时间或具体事件，留附录待核。'} for f in packet['facts']]})
    d=diagnose_material(p,[],invoke,None)
    assert d['status']=='passed' and len(packets)==2
    assert [f['original'] for packet in packets for f in packet['facts']]==[f['fact'] for f in facts]


def test_missing_condition_from_same_source_is_actually_added_despite_existing_id():
    from person_material_accounting import diagnose_material
    f={'evidence_id':'E-GLOBAL0000','fact':'董事会批准授权限额为100万元，授权期限为2025年1月至12月。',
        'subject_scope':'company','analysis_allowed':False}
    p={'chapter':5,'title':'管理','facts':[f],'required_source_displays':[{'evidence_id':f['evidence_id'],
        'quote':'董事会批准授权限额为100万元，'}]}
    def invoke(*args):return json.dumps({'material_reviews':[{'evidence_id':f['evidence_id'],
        'disposition':'missing','reason':'已有金额摘录仍遗漏授权期限这一关键限定条件。',
        'required_quote':'授权期限为2025年1月至12月。'}]})
    d=diagnose_material(p,[],invoke,None)
    assert d['status']=='passed' and len(p['required_source_displays'])==2
    assert any('授权期限' in r['quote'] for r in p['required_source_displays'])


def test_literal_allocator_only_selects_reviewed_requested_spans_not_unrelated_long_originals():
    from person_material_accounting import allocate_literal_displays
    important='董事会批准授权限额为100万元，授权期限为2025年1月至12月。'
    f={'evidence_id':'E-GLOBAL0000','fact':'其他无关原始背景。'*1000+important}
    p={'chapter':5,'title':'管理','facts':[f],'required_source_displays':[{'evidence_id':f['evidence_id'],'quote':important}]}
    def invoke(role,prompt,*args):
        data=json.loads(prompt.splitlines()[-1]);card=data['sources'][0]
        assert 'original' not in card and card['source_requested_originals']==[important]
        assert all(s['quote'] in important for s in card['segments'])
        return json.dumps({'displays':[{'evidence_id':f['evidence_id'],'segment_ids':[0]}]})
    assert allocate_literal_displays(p,[],invoke,None)['status']=='selected_for_material_review'
