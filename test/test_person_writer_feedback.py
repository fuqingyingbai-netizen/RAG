import copy
from person_content_acceptance import writer_repair_feedback


def test_writer_feedback_keeps_every_failed_semantic_finding_without_changing_full_audit():
    failed={'verdict':'unsupported','reason':'单位改变','support_quotes':[{'quote':'原文完整保留'}]}
    supported={'verdict':'supported','reason':'已核对','support_quotes':[{'quote':'较长的成功核对原文'}]}
    history=[{'status':'pending_repair_semantics','repair_semantic_review':{
        'claims':[supported,failed],'effective_claims':[supported,failed]}}]
    original=copy.deepcopy(history)
    feedback=writer_repair_feedback(history)
    assert history==original
    assert feedback[0]['repair_semantic_review']['claims']==[failed]
    assert 'effective_claims' not in feedback[0]['repair_semantic_review']


def test_writer_feedback_keeps_missing_and_pending_items_and_all_actual_candidates():
    missing={'status':'missing','gaps':[{'prior_quote':'最高日产','evidence_ids':['E-ONE']}]}
    pending={'status':'pending_review','reason':'核对未完成'}
    history=[{'status':'pending_final_coverage','issues':['missing'],
        'raw_revision':[{'analysis':'完整候选','evidence_ids':['E-ONE']}],
        'final_review':{'status':'pending_review','items':[{'status':'covered','reason':'完整保留'},missing,pending]}}]
    feedback=writer_repair_feedback(history)[0]
    assert feedback['final_review']['items']==[missing,pending]
    assert feedback['raw_revision']==history[0]['raw_revision']
    assert feedback['issues']==history[0]['issues']


def test_writer_feedback_preserves_latest_measured_budget_and_nested_failed_review():
    failed={'verdict':'needs_review','reason':'日期未获支持'}
    row={'status':'pending_repair_validation','validation_rejections':['analysis_length_budget_exceeded'],
         'initial_revision_compression':{'compression':{'max_analysis_chars':69,'draft_chars':85}},
         'repair_semantic_review':{'initial':{'claims':[failed]},'followup':{'claims':[{'verdict':'supported'}]}}}
    result=writer_repair_feedback([row])[0]
    assert result['status']==row['status']
    assert result['validation_rejections']==row['validation_rejections']
    assert result['initial_revision_compression']==row['initial_revision_compression']
    assert result['repair_semantic_review']['initial']['claims']==[failed]
    assert result['repair_semantic_review']['followup']['claims']==[]
