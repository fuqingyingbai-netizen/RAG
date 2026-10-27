"""Offline citation-edit tasks do not manufacture source support."""
import copy,json
import pytest
from person_semantic_review import review_analyses,citation_edit_plans,repair_semantic_findings


def fixture():
    facts=[{'evidence_id':'E-PCHAIR','fact':'林知远担任董事长。','source_url':'https://fixture.invalid/chair','analysis_allowed':True},
           {'evidence_id':'E-POTHER','fact':'另一人物负责技术工作。','source_url':'https://fixture.invalid/other','analysis_allowed':True}]
    original=[{'analysis':'来源称林知远担任董事长。','evidence_ids':['E-PCHAIR','E-POTHER']}]
    reply={'reviews':[{'claim_index':0,'verdict':'supported','supporting_evidence_ids':['E-PCHAIR'],
        'reason':'第一份支持董事长；另一份仅记另一人物技术工作，不能支持本句。'}]}
    reviewed,reasons,audit=review_analyses(5,'管理',facts,original,lambda *a:json.dumps(reply),as_of_date='2026-10-20')
    return facts,original,reviewed,reasons,audit


def test_two_actual_partial_receipts_define_edit_scope_and_stay_pending():
    facts,original,reviewed,reasons,audit=fixture();before=copy.deepcopy(audit)
    plans=citation_edit_plans(audit,original,facts)
    assert reasons==['semantic_review_incomplete'] and reviewed[0]['analysis']==''
    assert plans[0]['citation_edit_scope']['missing_evidence_ids']==['E-POTHER']
    assert plans[0]['citation_edit_scope']['planning_only_not_accepted_support']
    assert audit==before and audit['effective_claims'][0]['verdict']=='supported'
    assert audit['effective_claims'][0]['validation_reason']=='semantic_review_incomplete'


@pytest.mark.parametrize('change',['no_followup','failed_followup','empty_selection','unknown_selection','wrong_quote','unsupported'])
def test_unavailable_or_invalid_receipts_do_not_become_citation_edit_tasks(change):
    facts,original,reviewed,reasons,audit=fixture()
    if change=='no_followup':audit.pop('targeted_followup')
    elif change=='failed_followup':audit['targeted_followup']['status']='request_failed'
    else:
        row=audit['effective_claims'][0]
        if change=='empty_selection':row['support_quotes']=[]
        elif change=='unknown_selection':row['invalid_citation_selection']=True
        elif change=='wrong_quote':row['support_quotes'][0]['quote']='不是原文'
        elif change=='unsupported':row['verdict']='unsupported'
    assert citation_edit_plans(audit,original,facts)==[]


@pytest.mark.parametrize('repair_succeeds',[False,True])
def test_writer_must_repair_then_get_a_new_complete_semantic_receipt(repair_succeeds):
    facts,original,reviewed,reasons,audit=fixture();calls=[]
    def invoke(role,prompt,*args):
        calls.append(role)
        if role.endswith('核验修订'):
            assert 'E-POTHER' in prompt and '回执未完整' in prompt
            return json.dumps({'claims':[{'analysis':original[0]['analysis'],
                'evidence_ids':['E-PCHAIR'] if repair_succeeds else original[0]['evidence_ids']}]})
        packet=json.loads(prompt.splitlines()[-1]);assert packet['claims'][0]['evidence_ids']==(['E-PCHAIR'] if repair_succeeds else original[0]['evidence_ids'])
        return json.dumps({'reviews':[{'claim_index':0,'verdict':'supported','reason':'逐条核验新句全部引用',
            'supporting_evidence_ids':['E-PCHAIR']}]})
    validate=lambda answer,p:([{**r,'analysis_status':'source_text_valid'} for r in json.loads(answer)['claims']],[])
    locked=[{'analysis':'已核验且保留的文字'*40,'evidence_ids':['E-PCHAIR']}]
    result,errors,final=repair_semantic_findings(5,'管理',facts,original,reviewed,reasons,audit,
        {'chapter':5,'title':'管理','facts':facts},{'facts':facts},invoke,None,validate,as_of_date='2026-10-20',max_rounds=1,reserved_analyses=locked)
    assert final['repair_rounds'][0]['citation_edit_plans']
    assert final['initial_review']['effective_claims'][0]['validation_reason']=='semantic_review_incomplete'
    assert final['repair']['revision_available_chars']==600-len(locked[0]['analysis'])
    if repair_succeeds:
        assert not errors and result[0]['evidence_ids']==['E-PCHAIR'] and len(calls)==2
        assert final['final_review']['effective_claims'][0]['validation_reason']==''
    else:
        assert errors==['semantic_review_incomplete'] and result[0]['analysis']==''
        assert result[0]['evidence_ids']==original[0]['evidence_ids']
