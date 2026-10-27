import json

from person_content_acceptance import _accept_once,accept_content
from person_evidence import validate_model_claims


def facts():
    return [{'evidence_id':f'E-PBODY{i:08d}','fact':text,'source_url':f'https://fixture.invalid/{i}',
        'subject_scope':'person','subject':'林知远','analysis_allowed':True} for i,text in enumerate([
            '林知远于2018年任董事。','林知远于2019年任总裁。',
            '研究中心设立背景资料。'*40+'林知远于2020年决定设立研究中心。'])]


def test_a_writer_can_use_actual_body_quotes_to_preserve_old_facts_without_personal_promotion():
    fs=facts();alternate={**fs[1],'evidence_id':'E-PBODYALTERNATE','analysis_allowed':False}
    fs.append(alternate)
    current=[{'analysis':'来源记载林知远于2018年任董事。','evidence_ids':[fs[0]['evidence_id']]}]
    old=[{'analysis':'来源记载林知远于2019年任总裁。','evidence_ids':[fs[1]['evidence_id']]}]
    p={'chapter':5,'title':'管理','facts':fs,'research_facts':fs,'writing_contract':'evidence_selection_v2',
        'required_source_displays':[{'evidence_id':alternate['evidence_id'],'quote':alternate['fact']}]}
    def invoke(role,prompt,*args):
        data=json.loads(prompt.splitlines()[-1])
        if '事项定向补写' in role:
            quote=data['existing_body_representations']['literal_source_excerpts'][0]
            assert quote['quote']==alternate['fact'] and not quote['personal_analysis_allowed']
            assert alternate['evidence_id'] not in {f['evidence_id'] for f in data['facts']}
            return json.dumps({'claims':[current[0],{'analysis':'来源记载林知远于2020年决定设立研究中心。','evidence_ids':[fs[2]['evidence_id']]}]})
        if '语义复核' in role:
            return json.dumps({'reviews':[{'claim_index':i,'verdict':'supported','supporting_evidence_ids':c['evidence_ids']} for i,c in enumerate(data['claims'])]})
        if '事项覆盖验收' in role:
            is_literal='2019' in data['prior'][0]['analysis']
            return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[] if is_literal else [0],
                'matched_table_indices':[0] if is_literal else [],'gaps':[],'reason':'相同事项由实际逐字展示或当前分析完整保留。'}]})
        raise AssertionError(role)
    result,errors,audit=_accept_once(p,current,old,{'chapter':5,'facts':fs},invoke,None,validate_model_claims,
        material_missing=[{'material_evidence_ids':[fs[2]['evidence_id']],'source_question':'补充研究中心设立事项。','matched_claim_indices':[0]}])
    assert not errors and audit['status']=='passed_after_targeted_repair'
    assert not any('2019' in c['analysis'] for c in result)
    assert p['required_source_displays'][0]['quote']==alternate['fact']


def test_known_conservation_gaps_are_repaired_before_repeating_full_material_diagnosis():
    fs=[facts()[0],facts()[2]]
    current=[{'analysis':'来源记载林知远于2018年任董事。','evidence_ids':[fs[0]['evidence_id']]}]
    p={'chapter':5,'title':'管理','facts':fs,'research_facts':fs,
        'writing_contract':'evidence_selection_v2','require_material_dispositions':True}
    material_drafts=[];writes=[]
    def invoke(role,prompt,*args):
        data=json.loads(prompt.splitlines()[-1])
        if '材料采用诊断' in role:
            draft=data['draft'];material_drafts.append([c['analysis'] for c in draft]);rows=[]
            for f in data['facts']:
                year='2018' if f['evidence_id']==fs[0]['evidence_id'] else '2020'
                matches=[i for i,c in enumerate(draft) if year in c['analysis']]
                rows.append({'evidence_id':f['evidence_id'],'disposition':'analysis' if matches else 'missing',
                    'matched_claim_indices':matches or [0],'reason':'具体事项已保留。' if matches else '2020年设立研究中心的事项尚未出现。'})
            return json.dumps({'material_reviews':rows})
        if '事项覆盖验收' in role:
            old=data['prior'][0]['analysis'];year='2018' if '2018' in old else '2020'
            matches=[i for i,c in enumerate(data['draft']) if year in c['analysis']]
            return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered' if matches else 'missing',
                'matched_claim_indices':matches,'matched_table_indices':[],
                'gaps':[] if matches else [{'prior_quote':old,'evidence_ids':data['prior'][0]['evidence_ids']}],
                'reason':'对应事项已保留。' if matches else '有效旧事项被上一轮修订丢掉。'}]})
        if '事项定向补写' in role:
            writes.append(data)
            # First candidate loses an old valid fact. The next operation must
            # fix that known gap before paying to diagnose every card again.
            claims=[{'analysis':'来源记载林知远于2020年决定设立研究中心。','evidence_ids':[fs[1]['evidence_id']]}] if len(writes)==1 else current
            return json.dumps({'claims':claims})
        if '语义复核' in role:
            return json.dumps({'reviews':[{'claim_index':i,'verdict':'supported','supporting_evidence_ids':c['evidence_ids']} for i,c in enumerate(data['claims'])]})
        raise AssertionError(role)
    final,errors,audit=accept_content(p,current,current,{'chapter':5,'facts':fs},invoke,None,validate_model_claims)
    assert not errors and audit['status'].startswith('passed') and len(writes)==2
    assert len(material_drafts)==2
    assert '2018' in material_drafts[0][0]
    assert all(any(year in c for c in material_drafts[-1]) for year in ['2018','2020'])
    assert audit['material_diagnosis']['status']=='passed'
