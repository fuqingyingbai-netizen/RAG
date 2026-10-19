import json
from types import SimpleNamespace

import pytest

from industry_research import active_risk_dimensions, delivery_review_reasons
from research_workflow import ResearchWorkflow


SCOPE = {'capital_market': 'none', 'named_companies': []}


def assessed_risk(scope=None):
    return {'dimensions': [{'name': name, 'score': 35, 'level': 'low',
            'evidence_ids': ['E-0123456789AB'], 'reason': '已引用适用行业事实。'}
            for name in active_risk_dimensions(scope or SCOPE)]}


def setup_case(degradations=None, risk=None, scope=None):
    w = ResearchWorkflow.__new__(ResearchWorkflow)
    p = SimpleNamespace(title='行业状态测试', target_name='人工智能', target_type='industry',
        industry_scope=scope or SCOPE, industry_report_degradations=degradations or [],
        industry_delivery_diagnostic={'referenced_sources': 4}, industry_quality_issues=[])
    w._validate_delivery_report = lambda *a: None
    r = assessed_risk(scope) if risk is None else risk
    return w, p, json.dumps(r, ensure_ascii=False)


def test_candidate_requires_completed_writing_and_all_enabled_risks():
    w, p, risk = setup_case()
    report, meta = w._prepare_industry_delivery(p, '## 1. 摘要\n正文', risk)
    assert meta['delivery_status'] == 'final_candidate'
    assert meta['delivery_review_reasons'] == [] and 'quality_warning' not in meta
    assert '待人工复核稿' not in report


@pytest.mark.parametrize('chapter', [1, 4, 7, 14])
def test_citation_pass_cannot_hide_degraded_analysis_chapter(chapter):
    w, p, risk = setup_case([{'chapter':chapter, 'message':f'第{chapter}章改用事实摘录。'}])
    report, meta = w._prepare_industry_delivery(p, '## 1. 摘要\n正文', risk)
    assert meta['quality_issues'] == []  # Citation integrity passed independently.
    assert meta['delivery_status'] == 'review_draft'
    assert meta['delivery_review_reasons'][0]['chapter'] == chapter
    assert report.startswith('> **待人工复核稿**')


def test_only_missing_enabled_risk_is_listed_and_unknown_reason_survives():
    risk = assessed_risk()
    risk['dimensions'][2].update(score=None, level='unknown', evidence_ids=[],
        reason='模型未提供评分证据编号，暂不评分。', unknown_cause='missing_model_citations')
    w, p, payload = setup_case(risk=risk)
    _, meta = w._prepare_industry_delivery(p, '## 1. 摘要\n正文', payload)
    reasons = meta['delivery_review_reasons']
    assert len(reasons) == 1 and reasons[0]['dimension'] == '竞争格局与集中度风险'
    assert reasons[0]['unknown_cause'] == 'missing_model_citations'
    assert '模型未提供' in reasons[0]['message']


@pytest.mark.parametrize('risk', [{}, {'dimensions':None}, {'dimensions':[]}])
def test_missing_assessment_never_becomes_final_candidate(risk):
    w, p, payload = setup_case(risk=risk)
    _, meta = w._prepare_industry_delivery(p, '## 1. 摘要\n正文', payload)
    assert meta['delivery_status'] == 'review_draft'
    assert len(meta['delivery_review_reasons']) == 6


def test_disabled_modules_and_appendix_degradation_do_not_create_false_review():
    notes = [{'chapter':i, 'message':f'第{i}章旧降级'} for i in (8, 9, 12, 15, 16)]
    assert delivery_review_reasons(SCOPE, assessed_risk(), notes) == []


def test_enabled_capital_and_company_chapters_are_reviewed():
    scope = {'capital_market':'summary', 'named_companies':['样本企业']}
    reasons = delivery_review_reasons(scope, assessed_risk(scope),
        [{'chapter':i, 'message':f'第{i}章事实摘录'} for i in (8, 9, 12)])
    assert {r['chapter'] for r in reasons} == {8, 9, 12}


def test_whole_report_template_fallback_requires_review_even_with_valid_risk():
    w, p, risk = setup_case([{'chapter':None,'message':'整篇报告模板降级。'}])
    _, meta = w._prepare_industry_delivery(p, '## 1. 摘要\n正文', risk)
    assert meta['delivery_status']=='review_draft'
    assert meta['delivery_review_reasons'][0]['code']=='report_generation_degraded'


def test_duplicate_degradation_does_not_repeat_review_message():
    note = {'chapter':1, 'message':'摘要采用事实摘录。'}
    assert len(delivery_review_reasons(SCOPE, assessed_risk(), [note,note]))==1


def test_gate_failure_is_combined_with_writing_degradation(monkeypatch):
    monkeypatch.setenv('REPORT_SAVE_REVIEW_DRAFT_ON_GATE_FAIL','true')
    w, p, risk = setup_case([{'chapter':1,'message':'摘要摘录。'}])
    def fail(*a):
        p.industry_quality_issues=[{'chapter':4,'message':'第4章缺少有效规模证据。'}]
        raise RuntimeError('引用闸门失败')
    w._validate_delivery_report=fail
    _, meta=w._prepare_industry_delivery(p,'## 1. 摘要\n正文',risk)
    assert {r['code'] for r in meta['delivery_review_reasons']} == {'chapter_generation_degraded','evidence_gate_failed'}
    assert meta['quality_issues']==p.industry_quality_issues


def test_strict_evidence_gate_still_raises(monkeypatch):
    monkeypatch.setenv('REPORT_SAVE_REVIEW_DRAFT_ON_GATE_FAIL','false')
    w,p,risk=setup_case()
    def fail(*a): raise RuntimeError('证据闸门失败')
    w._validate_delivery_report=fail
    with pytest.raises(RuntimeError,match='证据闸门失败'):
        w._prepare_industry_delivery(p,'## 1. 摘要\n正文',risk)


def test_unknown_risk_is_reviewable_completion_even_when_evidence_gate_strict(monkeypatch):
    monkeypatch.setenv('REPORT_SAVE_REVIEW_DRAFT_ON_GATE_FAIL','false')
    w,p,risk=setup_case(risk={})
    _,meta=w._prepare_industry_delivery(p,'## 1. 摘要\n正文',risk)
    assert meta['delivery_status']=='review_draft'


def test_reexport_refreshes_notice_and_preserves_degradation():
    w,p,risk=setup_case([{'chapter':1,'message':'摘要采用事实摘录。'}])
    report,meta=w._prepare_industry_delivery(p,'## 1. 摘要\n正文',risk)
    old=report.replace('摘要采用事实摘录。','旧的过期原因')
    result,current=w._prepare_industry_delivery(p,old,risk)
    assert result.count('**待人工复核稿**')==1 and '旧的过期原因' not in result
    assert current['delivery_status']=='review_draft'
    assert current['generation_degradations']==meta['generation_degradations']


def test_legacy_fallback_text_without_metadata_stays_review_draft():
    w,p,risk=setup_case()
    _,meta=w._prepare_industry_delivery(p,'## 1. 摘要\n模型摘要未通过校验，综合判断需人工复核。',risk)
    assert meta['delivery_status']=='review_draft'
    assert meta['generation_degradations'][0]['chapter']==1


def test_industry_diagnostic_uses_actual_review_reasons_and_correct_source_chapter():
    w,p,risk=setup_case([{'chapter':1,'message':'摘要修复失败，使用来源事实摘录。'}],risk={})
    report,meta=w._prepare_industry_delivery(p,'## 1. 摘要\n正文',risk)
    diagnostic=w._build_report_quality_diagnostic(p,report,meta['quality_warning'])
    assert '第15章来源索引' in diagnostic and '摘要修复失败' in diagnostic
    assert '竞争格局与集中度风险' in diagnostic
    assert '第13章审计索引' not in diagnostic
