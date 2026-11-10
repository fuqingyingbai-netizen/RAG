import pytest
from company_quality import coverage, retrieval_metrics, validate_case, summary


def test_metrics_count_required_evidence_and_unanswerable_is_not_free_recall():
    gold=[{'document_id':'a','quote':'利润 120 万元'},{'document_id':'b','quote':'收入80万元'}]
    passages=[{'document_id':'a','text':'净利润120万元。'}]
    assert coverage(gold,passages)==.5
    assert coverage([],passages) is None
    assert coverage(gold,[{'document_id':'wrong','text':'利润120万元'}])==0


def test_metric_reports_dropped_evidence_and_invalid_citations_separately():
    case={'evidence':[{'document_id':'a','quote':'原文依据'}],'answer':'结论[id_999]'}
    metrics=retrieval_metrics(case,[{'document_id':'a','text':'原文依据'}],[{'id':'1','document_id':'b','text':'其他文字'}])
    assert metrics['candidate_recall']==1 and metrics['context_recall']==0
    assert metrics['invalid_citation_ids']==['999']


def test_gold_must_match_original_and_version():
    corpus={'a':{'sha256':'v1','parts':[{'text':'真实证据'}]}}
    case={'id':'q','question':'问题','expected_answer':'答案','split':'holdout',
        'evidence':[{'document_id':'a','quote':'真实证据','source_sha256':'v1'}]}
    validate_case(case,corpus)
    case['evidence'][0]['source_sha256']='v2'
    with pytest.raises(ValueError):validate_case(case,corpus)


def test_summary_keeps_errors_visible():
    report=summary([{'error':None,'metrics':{'context_recall':1},'judgment':{'answer_correct':True}}, {'error':'TimeoutError'}])
    assert report['cases']==2 and report['errors']==1
    assert report['answer_correct']==.5


def test_first_question_can_request_a_table_without_being_mistaken_for_a_followup():
    import asyncio
    import company_knowledge
    from company_memory import retrieval_question
    context={'recent':[],'summary':''}
    question='请把2025年各项目收入整理成表格，每行带引用。'
    assert asyncio.run(retrieval_question({},question,context))==question
    assert asyncio.run(retrieval_question({},'请把刚才的问题整理成表格',context)) is None
