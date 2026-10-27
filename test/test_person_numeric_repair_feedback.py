import json

from person_claim_repair import repair_once,numeric_rejection_context
from person_evidence import validate_model_claims


def test_a_rejected_clock_conversion_gets_exact_numeric_and_original_clock_feedback():
    fact={'evidence_id':'E-PNUMERIC0001','fact':'报道记载林知远要求当天下午4点前处理投诉。',
        'source_url':'https://fixture.invalid/clock','subject_scope':'person','analysis_allowed':True}
    package={'chapter':5,'title':'管理','facts':[fact],'writing_contract':'evidence_selection_v2'}
    bad={'analysis':'来源记载林知远要求当日16时前处理投诉。','evidence_ids':[fact['evidence_id']]}
    raw=json.dumps({'claims':[bad]});current,reasons=validate_model_claims(raw,package)
    assert 'unsupported_analysis' in reasons
    corrections=[]
    def invoke(role,prompt,*args):
        data=json.loads(prompt[prompt.index('{"material":'):]);detail=data['corrections'][0];corrections.append(detail)
        assert detail['unmatched_numeric_literals']==['16']
        assert detail['source_clock_literals']==['下午4点']
        assert detail['rejected_analysis']==bad['analysis']
        assert any('12/24' in issue for issue in detail['issues'])
        return json.dumps({'claims':[{'analysis':'来源记载林知远要求当天下午4点前处理投诉。','evidence_ids':[fact['evidence_id']]}]})
    final,errors,audit=repair_once(raw,package,{'chapter':5,'facts':[fact]},current,reasons,invoke,None,validate_model_claims)
    assert not errors and len(corrections)==1
    assert '下午4点' in final[0]['analysis'] and '16' not in final[0]['analysis']
    assert audit['diagnosed_corrections']==corrections


def test_numeric_diagnostics_do_not_confuse_a_proven_cover_year_with_an_event_number():
    row={'analysis':'2024年报载支付99万元。','evidence_ids':['E-PNUMERIC0001']}
    facts=[{'evidence_id':'E-PNUMERIC0001','fact':'公司披露支付9万元。','source_reporting_period_literal':'2024'}]
    detail=numeric_rejection_context(row,facts)
    assert detail['unmatched_numeric_literals']==['99']


def test_the_next_content_cycle_receives_the_rejected_postvalidation_clause_and_number():
    from person_content_acceptance import accept_content
    facts=[{'evidence_id':'E-PNUMERIC0001','fact':'林知远于2018年任董事。',
        'analysis_allowed':True,'subject_scope':'person','source_url':'https://fixture.invalid/role'},
        {'evidence_id':'E-PNUMERIC0002','fact':'林知远于2019年要求当天下午4点前处理投诉。',
        'analysis_allowed':True,'subject_scope':'person','source_url':'https://fixture.invalid/event'}]
    current=[{'analysis':'来源记载林知远于2018年任董事。','evidence_ids':[facts[0]['evidence_id']]}]
    prior=[{'analysis':'来源记载林知远于2019年要求当天下午4点前处理投诉。','evidence_ids':[facts[1]['evidence_id']]}]
    bad={'analysis':'来源记载林知远于2019年要求当日16时前处理投诉。','evidence_ids':[facts[1]['evidence_id']]}
    writes=[]
    def invoke(role,prompt,*args):
        if '核验修订' in role:return json.dumps({'claims':[bad]})
        data=json.loads(prompt.splitlines()[-1])
        if '事项覆盖验收' in role:
            covered=any('2019' in c['analysis'] for c in data['draft'])
            return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered' if covered else 'missing',
                'matched_claim_indices':[1] if covered else [],'matched_table_indices':[],
                'gaps':[] if covered else [{'prior_quote':prior[0]['analysis'],'evidence_ids':prior[0]['evidence_ids']}],
                'reason':'对应事项已实际保留。' if covered else '旧稿中的投诉处理时间及要求未保留。'}]})
        if '事项定向补写' in role:
            writes.append(data)
            if len(writes)==1:return json.dumps({'claims':[bad]})
            history=data['previous_repair_diagnostics']
            detail=history[-1]['source_repair']['diagnosed_corrections'][0]
            assert detail['rejected_analysis']==bad['analysis'] and detail['unmatched_numeric_literals']==['16']
            assert 'source_support' not in json.dumps(history)
            return json.dumps({'claims':prior})
        if '语义复核' in role:
            return json.dumps({'reviews':[{'claim_index':0,'verdict':'supported','supporting_evidence_ids':prior[0]['evidence_ids']}]})
        raise AssertionError(role)
    package={'chapter':5,'title':'管理','facts':facts,'writing_contract':'evidence_selection_v2'}
    result,errors,audit=accept_content(package,current,prior,{'chapter':5,'facts':facts},invoke,None,validate_model_claims)
    assert not errors and audit['status'].startswith('passed') and len(writes)==2
    assert any('2018' in c['analysis'] for c in result) and any('下午4点' in c['analysis'] for c in result)
