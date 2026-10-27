import json
from person_content_acceptance import check_coverage,exact_retained_item
from person_evidence import validate_model_claims


def fixture():
    f={'evidence_id':'E-PEXACTONE','fact':'来源称最高日产超过5000万只。','source_url':'https://fixture.invalid/one','analysis_allowed':True,'subject_scope':'person'}
    g={**f,'evidence_id':'E-PEXACTTWO','source_url':'https://fixture.invalid/two'}
    p={'chapter':3,'title':'资料','facts':[f,g],'research_facts':[f,g],'writing_contract':'evidence_selection_v2'}
    old={'analysis':f['fact'],'evidence_ids':[f['evidence_id']]}
    return p,old,g


def test_identical_actual_prose_and_retained_references_need_no_new_review_request():
    p,old,g=fixture()
    def no_request(*args):raise AssertionError('Unchanged prose preservation requires no model request.')
    result=check_coverage(p,[old],[old],no_request,None)
    assert result['status']=='passed' and result['requests']==0
    assert result['items'][0]['validation']=='exact_actual_text_and_retained_source_references'


def test_missing_highest_qualifier_still_requires_and_fails_content_review():
    p,old,g=fixture();calls=[];current={**old,'analysis':old['analysis'].replace('最高','')}
    def model(role,prompt,emit):
        calls.append(prompt)
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'missing','matched_claim_indices':[0],
            'gaps':[{'prior_quote':'最高','evidence_ids':old['evidence_ids']}],'reason':'数量限定缺失。'}]})
    result=check_coverage(p,[current],[old],model,None)
    assert len(calls)==1 and result['status']=='pending_review' and result['items'][0]['status']=='missing'


def test_different_source_or_negated_text_never_uses_exact_retention():
    p,old,g=fixture();admitted={f['evidence_id'] for f in p['facts']}
    assert exact_retained_item(old,[{**old,'evidence_ids':[g['evidence_id']]}],admitted) is None
    assert exact_retained_item(old,[{**old,'analysis':'并非'+old['analysis']}],admitted) is None
    assert exact_retained_item(old,[{**old,'evidence_ids':old['evidence_ids']+['E-PUNKNOWN']}],admitted) is None


def test_adding_qualified_references_does_not_remove_the_old_text_or_original_references():
    p,old,g=fixture();current={**old,'evidence_ids':[g['evidence_id'],*old['evidence_ids']]}
    result=exact_retained_item(old,[current],{f['evidence_id'] for f in p['facts']})
    assert result['status']=='covered' and result['matched_claim_indices']==[0]


def test_literal_preservation_cannot_bypass_source_validation_of_an_unsupported_claim():
    p,old,g=fixture();unsupported={**old,'analysis':'来源称最高日产超过9000万只。'}
    rows,errors=validate_model_claims(json.dumps({'claims':[unsupported]}),p)
    assert errors and not any(r.get('analysis') for r in rows)


def test_changed_wording_still_retries_an_actual_needed_review_with_identical_input():
    p,old,g=fixture();calls=[];current={**old,'analysis':'来源注明：'+old['analysis']}
    def model(role,prompt,emit):
        calls.append((role,prompt))
        if len(calls)==1:raise ConnectionError('offline test only')
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[0],'gaps':[]}]})
    result=check_coverage(p,[current],[old],model,None)
    assert result['status']=='passed' and result['requests']==2
    assert len(calls)==2 and calls[0][1]==calls[1][1]
