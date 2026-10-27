import json
from person_content_acceptance import accept_content
from person_evidence import validate_model_claims


def facts():
    rows=[{'evidence_id':f'E-PSAFE{i:08d}','fact':text,'source_url':f'https://fixture.invalid/{i}',
        'subject':'林知远','subject_scope':'person','analysis_allowed':True} for i,text in enumerate([
            '林知远于2018年任董事。','林知远于2019年任总裁。',
            '补充文献背景资料，仅作完整原文上下文。'*20+'林知远于2020年决定设立研究中心。'])]
    rows.append({**rows[1],'evidence_id':'E-PALTERNATE0001','source_url':'https://fixture.invalid/alternate',
        'analysis_allowed':False,'opinion_only':True})
    return rows


def test_trimmed_alternate_source_literal_cannot_reuse_a_stale_conservation_pass():
    fs=facts();claims=[{'analysis':'来源记载'+f['fact'],'evidence_ids':[f['evidence_id']]} for f in fs[:2]]
    p={'chapter':5,'title':'管理','task':'核对具体管理行为','facts':fs,'research_facts':fs,
       'writing_contract':'evidence_selection_v2','require_material_dispositions':True,
       'required_source_displays':[{'evidence_id':fs[3]['evidence_id'],'quote':fs[3]['fact'],'reason':'旧自动展示'}]}
    writer_calls=[];observed_missing_after_trim=[]
    def invoke(role,prompt,*args):
        data=json.loads(prompt.splitlines()[-1])
        if '材料采用诊断' in role:
            has_new=any('2020' in c['analysis'] for c in data['draft']);reviews=[]
            for f in data['facts']:
                eid=f['evidence_id']
                if eid==fs[2]['evidence_id'] and not has_new:
                    r={'evidence_id':eid,'disposition':'missing','matched_claim_indices':[1],'reason':'2020年设立研究中心的决策未保留。'}
                elif eid==fs[3]['evidence_id'] and not has_new:
                    r={'evidence_id':eid,'disposition':'source_display','reason':'替代来源逐字记载2019年的总裁任职，尚保留于正文。'}
                elif eid in {fs[1]['evidence_id'],fs[3]['evidence_id']}:
                    r={'evidence_id':eid,'disposition':'appendix','reason':'总裁任职记录只作历史背景，不单独推断管理行为和效果。'}
                else:r={'evidence_id':eid,'disposition':'analysis','matched_claim_indices':[0 if eid==fs[0]['evidence_id'] else 1],'reason':'正文已保留这一具体事项。'}
                reviews.append(r)
            return json.dumps({'material_reviews':reviews},ensure_ascii=False)
        if '事项定向补写' in role:
            writer_calls.append(data)
            if len(writer_calls)==1:
                return json.dumps({'claims':[{'analysis':'来源记载林知远于2020年决定设立研究中心。','evidence_ids':[fs[2]['evidence_id']]}]},ensure_ascii=False)
            return json.dumps({'claims':[{'analysis':'来源记载林知远于2019年任总裁。','evidence_ids':[fs[1]['evidence_id']]}]},ensure_ascii=False)
        if '语义复核' in role:
            return json.dumps({'reviews':[{'claim_index':i,'verdict':'supported','supporting_evidence_ids':c['evidence_ids']} for i,c in enumerate(data['claims'])]})
        if '事项覆盖验收' in role:
            old=data['prior'][0]['analysis'];draft=data['draft'];matches=[i for i,c in enumerate(draft) if ('2019' if '2019' in old else '2020' if '2020' in old else '2018') in c['analysis']]
            if matches:r={'prior_index':0,'verdict':'covered','matched_claim_indices':matches,'matched_table_indices':[],'gaps':[],'reason':'当前实际文字保留了对应历史事项。'}
            elif '2019' in old and data.get('tables'):
                r={'prior_index':0,'verdict':'covered','matched_claim_indices':[],'matched_table_indices':[0],'gaps':[],'reason':'替代来源的正文逐字展示保留相同主体、期间及职务。'}
            else:
                observed_missing_after_trim.append(old)
                r={'prior_index':0,'verdict':'missing','matched_claim_indices':[],'matched_table_indices':[],
                   'gaps':[{'prior_quote':old,'evidence_ids':data['prior'][0]['evidence_ids']}],'reason':'此前承接这一旧事实的逐字展示已从实际正文删除。'}
            return json.dumps({'reviews':[r]},ensure_ascii=False)
        raise AssertionError(role)
    final,errors,audit=accept_content(p,claims,claims[:1],{'facts':fs},invoke,None,validate_model_claims)
    assert not errors and audit['status'].startswith('passed')
    assert observed_missing_after_trim and len(writer_calls)==2
    assert any('2019' in c['analysis'] for c in final)
    assert any('2020' in c['analysis'] for c in final)
    assert not fs[3]['analysis_allowed']


def test_old_fact_without_a_matching_paragraph_reallocates_unusable_sentence_space():
    fs=facts()[:2];sentence='来源记载林知远于2018年任董事。'
    current={'analysis':sentence*(600//len(sentence)),'evidence_ids':[fs[0]['evidence_id']]}
    assert 590<=len(current['analysis'])<=600
    prior={'analysis':'来源记载林知远于2019年任总裁。','evidence_ids':[fs[1]['evidence_id']]}
    p={'chapter':5,'title':'管理','facts':fs,'writing_contract':'evidence_selection_v2'};revisions=[]
    def invoke(role,prompt,*args):
        data=json.loads(prompt.splitlines()[-1])
        if '事项覆盖验收' in role:
            reviews=[]
            for i,old in enumerate(data['prior']):
                if '2019' in old['analysis'] and not any('2019' in c['analysis'] for c in data['draft']):
                    r={'prior_index':i,'verdict':'missing','matched_claim_indices':[],'matched_table_indices':[],
                        'gaps':[{'prior_quote':old['analysis'],'evidence_ids':[fs[1]['evidence_id']]}],'reason':'有效旧事实没有对应新段落或编号。'}
                else:r={'prior_index':i,'verdict':'covered','matched_claim_indices':[0],'matched_table_indices':[],'gaps':[],'reason':'同一事项的重复叙述已合并，具体历史角色及年份均实际保留。'}
                reviews.append(r)
            return json.dumps({'reviews':reviews},ensure_ascii=False)
        if '事项定向补写' in role:
            revisions.append(data)
            assert not data['locked_analyses'] and data['replace_draft']
            return json.dumps({'claims':[{'analysis':'来源记载林知远于2018年任董事，2019年任总裁。','evidence_ids':[f['evidence_id'] for f in fs]}]},ensure_ascii=False)
        if '篇幅压缩' in role:
            # Offline candidate remains too long for the measured spare space;
            # the next round must then unlock shared prose for both facts.
            return json.dumps({'claims':[prior]},ensure_ascii=False)
        if '语义复核' in role:return json.dumps({'reviews':[{'claim_index':0,'verdict':'supported','supporting_evidence_ids':[f['evidence_id'] for f in fs]}]})
        raise AssertionError(role)
    final,errors,audit=accept_content(p,[current],[prior],{'facts':fs},invoke,None,validate_model_claims)
    assert not errors and audit['status'].startswith('passed') and len(revisions)==1
    assert '2018' in final[0]['analysis'] and '2019' in final[0]['analysis']
