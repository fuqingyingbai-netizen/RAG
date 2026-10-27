from person_material_review import presentation_facts
from person_content_acceptance import same_source_bound_draft


def fixture(size):
    text='原始的公司披露陈述。'*size
    fs=[{'evidence_id':f'E-PREQ{i}','fact':text,'source_url':f'https://fixture.invalid/{i}'} for i in range(2)]
    return {'facts':fs,'research_facts':fs,'required_source_displays':[{'evidence_id':f['evidence_id'],'quote':text} for f in fs]}


def test_mandatory_identical_words_keep_both_source_identifiers_within_real_budget():
    p=fixture(12);shown=presentation_facts(p,[])
    assert {f['evidence_id'] for f in shown}=={f['evidence_id'] for f in p['facts']}
    assert all(f['fact']==p['facts'][0]['fact'] for f in shown)
    assert p['quotation_budget']['displayed_chars']==sum(len(f['fact']) for f in shown)<=1600
    assert not p['quotation_budget']['required_undisplayed_evidence_ids']


def test_actual_mandatory_overflow_is_still_blocked_even_when_words_are_identical():
    p=fixture(90);shown=presentation_facts(p,[])
    assert sum(len(f['fact']) for f in p['facts'])>1600
    assert len(shown)==1 and p['quotation_budget']['required_undisplayed_evidence_ids']==['E-PREQ1']
    assert p['quotation_budget']['displayed_chars']<=1600


def test_optional_identical_illustrations_still_deduplicate():
    p=fixture(12);p.pop('required_source_displays');shown=presentation_facts(p,[])
    assert len(shown)==1 and p['quotation_budget']['required_undisplayed_evidence_ids']==[]


def test_rendered_candidate_binding_allows_reference_order_without_changing_text():
    assert same_source_bound_draft([{'analysis':'来源载2018年任职。','evidence_ids':['E-PONE','E-PTWO']}],
        [{'analysis':'来源载2018年任职。','evidence_ids':['E-PTWO','E-PONE']}])


def test_rendered_candidate_binding_rejects_different_period_or_source():
    old=[{'analysis':'来源载2018年任职。','evidence_ids':['E-PONE']}]
    assert not same_source_bound_draft(old,[{'analysis':'来源载2019年任职。','evidence_ids':['E-PONE']}])
    assert not same_source_bound_draft(old,[{'analysis':'来源载2018年任职。','evidence_ids':['E-PTWO']}])


def test_rendered_candidate_binding_rejects_missing_or_malformed_prose():
    old=[{'analysis':'来源载2018年任职。','evidence_ids':['E-PONE']}]
    assert not same_source_bound_draft(old,[])
    assert not same_source_bound_draft(None,None)
    assert not same_source_bound_draft(old,[{'analysis':'来源载2018年任职。','evidence_ids':None}])


def test_passed_coverage_audit_persists_the_actual_returned_candidate_for_resuming():
    import json
    from person_content_acceptance import accept_content,draft_rows
    from person_evidence import validate_model_claims
    f={'evidence_id':'E-PRETURNCANDIDATE','fact':'林知远于2018年任董事。','source_url':'https://fixture.invalid/role',
       'subject':'林知远','subject_scope':'person','analysis_allowed':True}
    p={'chapter':5,'title':'治理','facts':[f],'research_facts':[f],'writing_contract':'evidence_selection_v2'}
    raw=[{'analysis':f['fact'],'evidence_ids':[f['evidence_id']]}]
    current,errors=validate_model_claims(json.dumps({'claims':raw}),p);assert not errors
    def model(role,prompt,emit):
        assert '事项覆盖验收' in role
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[0],
            'matched_table_indices':[],'gaps':[],'reason':'任职日期及职务逐字保留。'}]})
    result,errors,audit=accept_content(p,current,raw,{'chapter':5,'facts':[f]},model,None,validate_model_claims)
    assert not errors and audit['status'].startswith('passed')
    assert audit['last_validated_candidate']==draft_rows(result)==raw


def test_completed_source_plan_restores_actual_literals_without_promoting_permission():
    from person_content_acceptance import restore_literal_plan_from_checkpoint
    fact={'evidence_id':'E-PRESTORELITERAL','fact':'公司制度载明授权条件，仅作为来源陈述。','analysis_allowed':False}
    p={'facts':[fact],'research_facts':[fact],'required_source_displays':[]}
    old={'required_source_displays':[{'evidence_id':fact['evidence_id'],'quote':fact['fact'],'reason':'实际旧方案。'}]}
    result=restore_literal_plan_from_checkpoint(p,old)
    assert result=={'records':1,'chars':len(fact['fact'])}
    assert p['required_source_displays']==old['required_source_displays'] and not fact['analysis_allowed']
    p['required_source_displays'][0]['reason']='运行期记录。'
    assert old['required_source_displays'][0]['reason']=='实际旧方案。'


def test_source_plan_restoration_rejects_unknown_record_or_changed_original():
    import pytest
    from person_content_acceptance import restore_literal_plan_from_checkpoint
    p={'facts':[{'evidence_id':'E-PRESTORELITERAL','fact':'公司实际授权条件。'}]}
    for row in [{'evidence_id':'E-POTHER','quote':'公司实际授权条件。'},
                {'evidence_id':'E-PRESTORELITERAL','quote':'新增不在原文中的条件。'}]:
        with pytest.raises(ValueError,match='source_display_mismatch'):
            restore_literal_plan_from_checkpoint(p,{'required_source_displays':[row]})


def test_absent_source_plan_cannot_silently_erase_the_current_candidate_plan():
    import pytest
    from person_content_acceptance import restore_literal_plan_from_checkpoint
    p={'facts':[],'required_source_displays':[{'evidence_id':'E-POLD','quote':'现有实际片段。'}]}
    with pytest.raises(ValueError):restore_literal_plan_from_checkpoint(p,{})
    assert p['required_source_displays']==[{'evidence_id':'E-POLD','quote':'现有实际片段。'}]
