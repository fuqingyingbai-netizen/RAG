import json
from person_material_accounting import diagnose_material
from person_content_acceptance import accept_content


def packet():
    f={'evidence_id':'E-PTEST00000001','fact':'来源介绍了公司的成立背景和行业口号，没有新增具体管理行为。',
       'source_url':'https://fixture.invalid/background','subject':'甲公司','subject_scope':'affiliated_company','analysis_allowed':False}
    p={'chapter':5,'title':'管理','task':'核对具体管理行为和正式授权','facts':[f],
       'require_material_dispositions':True,'required_source_displays':[{'evidence_id':f['evidence_id'],'quote':f['fact'],'reason':'旧自动展示计划'}]}
    return f,p


def test_transport_retry_keeps_identical_sources_and_does_not_expand_format_packet():
    f,p=packet();calls=[]
    def invoke(role,prompt,*args):
        calls.append((role,prompt))
        if len(calls)==1:raise TimeoutError('Request timed out')
        return json.dumps({'material_reviews':[{'evidence_id':f['evidence_id'],'disposition':'appendix',
            'reason':'原文仅为公司成立背景和行业口号，没有本章所核对的具体管理行为或授权。'}]},ensure_ascii=False)
    result=diagnose_material(p,[],invoke,None)
    assert result['status']=='passed' and result['requests']==2
    assert calls[0]==calls[1] and 'source_segments' not in calls[1][1]
    assert f['fact'] in json.loads(calls[1][1].splitlines()[-1])['facts'][0]['original']


def test_reviewed_background_literal_can_be_removed_without_promoting_or_losing_source():
    f,p=packet();calls=[]
    def invoke(role,prompt,*args):
        data=json.loads(prompt.splitlines()[-1]);calls.append(data)
        return json.dumps({'material_reviews':[{'evidence_id':f['evidence_id'],'disposition':'appendix',
            'reason':'原文仅是公司成立背景及行业口号，不提供本章所问的具体管理行为或授权；完整来源留附录供查。'}]},ensure_ascii=False)
    result,errors,audit=accept_content(p,[],[],{'facts':[f]},invoke,None,lambda *a:([],[]))
    assert not errors and audit['status'].startswith('passed') and result==[]
    assert not p['required_source_displays'] and not f['analysis_allowed']
    assert len(calls)==2 and calls[0].get('source_display_quotes') and not calls[1].get('source_display_quotes')
    assert audit['material_diagnosis']['counts']=={'appendix':1}
    assert p['facts'][0]['fact']==f['fact']


def test_new_review_can_restore_a_literal_that_was_the_only_carrier_of_important_conditions():
    f,p=packet();f['fact']='甲公司董事会批准对林知远授权，限额为100万元，期限为2025年。';p['required_source_displays'][0]['quote']=f['fact'];calls=[]
    def invoke(role,prompt,*args):
        data=json.loads(prompt.splitlines()[-1]);calls.append(data)
        if len(calls)==1:row={'evidence_id':f['evidence_id'],'disposition':'appendix','reason':'原文是公司授权安排，暂作为背景留附录供核对。'}
        else:row={'evidence_id':f['evidence_id'],'disposition':'source_display','reason':'实际授权额度与期限直接回答本章正式授权问题，当前未在正文保留。','required_quote':f['fact']}
        return json.dumps({'material_reviews':[row]},ensure_ascii=False)
    _,errors,audit=accept_content(p,[],[],{'facts':[f]},invoke,None,lambda *a:([],[]))
    assert not errors and audit['status'].startswith('passed')
    assert p['required_source_displays'][0]['quote']==f['fact'] and not f['analysis_allowed']
    assert audit['material_diagnosis']['counts']=={'source_display':1}


def test_baseline_and_current_analysis_citations_protect_their_literal_support():
    f,p=packet();f.update(fact='来源记载林知远曾任董事，具体任期未披露。',subject='林知远',subject_scope='person',analysis_allowed=True)
    p['required_source_displays'][0]['quote']=f['fact'];p['chapter']=3
    claim={'analysis':f['fact'],'evidence_ids':[f['evidence_id']]};material_calls=[]
    def invoke(role,prompt,*args):
        if '材料采用诊断' in role:
            material_calls.append(prompt)
            return json.dumps({'material_reviews':[{'evidence_id':f['evidence_id'],'disposition':'appendix','reason':'原文为历史职务背景，不单独推断人格，完整资料仍作背景保留。'}]},ensure_ascii=False)
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[0],'matched_table_indices':[],'gaps':[],'reason':'当前逐字保留该条历史职务及资料局限。'}]},ensure_ascii=False)
    _,errors,audit=accept_content(p,[claim],[claim],{'facts':[f]},invoke,None,lambda *a:([],[]))
    assert not errors and audit['status'].startswith('passed')
    assert p['required_source_displays'][0]['quote']==f['fact'] and len(material_calls)==1


def test_quote_only_carrier_of_a_replaced_valid_fact_survives_final_material_review():
    from person_evidence import validate_model_claims
    facts=[{'evidence_id':f'E-PKEEP{i:08d}','fact':text,'source_url':f'https://fixture.invalid/{i}',
            'subject':'林知远','subject_scope':'person','analysis_allowed':True} for i,text in enumerate([
        '林知远于2018年任董事。','林知远于2019年任总裁。',
        '补充文献背景资料，仅作完整原文上下文。'*20+'林知远于2020年决定设立研究中心。'])]
    claims=[{'analysis':'来源记载'+f['fact'],'evidence_ids':[f['evidence_id']]} for f in facts[:2]]
    p={'chapter':5,'title':'管理','task':'核对具体管理行为','facts':facts,'research_facts':facts,
       'writing_contract':'evidence_selection_v2','require_material_dispositions':True,
       'required_source_displays':[{'evidence_id':facts[1]['evidence_id'],'quote':facts[1]['fact'],'reason':'旧自动展示'}]}
    def invoke(role,prompt,*args):
        if '材料采用诊断' in role:
            data=json.loads(prompt.splitlines()[-1]);new=any('2020' in c['analysis'] for c in data['draft']);reviews=[]
            for f in data['facts']:
                eid=f['evidence_id']
                if eid==facts[1]['evidence_id']:
                    row={'evidence_id':eid,'disposition':'appendix','reason':'原文是总裁任职履历背景，本章只核对具体管理行为；不据此推断能力。'}
                elif eid==facts[2]['evidence_id'] and not new:
                    row={'evidence_id':eid,'disposition':'missing','matched_claim_indices':[1],'reason':'2020年设立研究中心的具体决策尚未保留。'}
                else:row={'evidence_id':eid,'disposition':'analysis','matched_claim_indices':[1 if eid==facts[2]['evidence_id'] else 0],'reason':'对应正文已经保留该条具体事项。'}
                reviews.append(row)
            return json.dumps({'material_reviews':reviews},ensure_ascii=False)
        data=json.loads(prompt.splitlines()[-1])
        if '事项定向补写' in role:
            return json.dumps({'claims':[{'analysis':'来源记载林知远于2020年决定设立研究中心。','evidence_ids':[facts[2]['evidence_id']]}]},ensure_ascii=False)
        if '语义复核' in role:
            return json.dumps({'reviews':[{'claim_index':i,'verdict':'supported','supporting_evidence_ids':r['evidence_ids']} for i,r in enumerate(data['claims'])]})
        if '事项覆盖验收' in role:
            if '2019' in data['prior'][0]['analysis']:
                return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[],
                    'matched_table_indices':[0],'gaps':[],'reason':'2019年的总裁任职由正文逐字来源展示完整保留。'}]},ensure_ascii=False)
            return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[0],
                'matched_table_indices':[],'gaps':[],'reason':'董事历史任职仍由当前第一项完整保留。'}]},ensure_ascii=False)
        raise AssertionError(role)
    final,errors,audit=accept_content(p,claims,claims[:1],{'facts':facts},invoke,None,validate_model_claims)
    assert not errors and audit['status'].startswith('passed')
    assert any('2020' in r['analysis'] for r in final)
    assert not any('2019' in r['analysis'] for r in final)
    assert any(r['quote']==facts[1]['fact'] for r in p['required_source_displays'])
