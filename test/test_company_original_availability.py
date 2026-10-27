from types import SimpleNamespace

import pytest

from report_agents.company_evidence import source_body, document_pages
from research_workflow import ResearchWorkflow


def source(body, **meta):
    return SimpleNamespace(id=1, url='https://records.example.org/original',
        title='青禾网络有限公司原始资料', content=body, summary='检索线索：青禾网络有限公司',
        source_type='web', credibility_score=60, created_at='2026-10-20',
        source_metadata=meta)


@pytest.mark.parametrize('body', [
    '{"_waf_123abc45":"challenge-value"}\n' + 'X0ab1/' * 6000,
    '# Access Denied\nVerify you are human',
    '## 请开启浏览器的Javascript功能\n请启用后重试。',
], ids=['waf-payload', 'access-denied', 'javascript-only'])
def test_challenge_body_never_authenticates_a_company_source_even_with_done_status(body):
    original = source(body, fetch_status='done', content_kind='full_text')
    assert source_body(original)[1] == 'discovery_summary'
    assert document_pages(original) == []
    project = SimpleNamespace(target_type='company', target_name='青禾网络有限公司', sources=[original])
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    retained_card = dict(evidence_id='E-123456789ABC', source_url=original.url,
        source_title=original.title, fact='青禾网络有限公司资料。', company_name=project.target_name,
        evidence_scope='target_direct', eligible_for_report=True, eligible_for_risk_scoring=True)
    result = workflow._annotate_evidence_facts(project, [retained_card])[0]
    assert result['eligible_for_report'] is False
    assert result['eligible_for_risk_scoring'] is False
    assert result['source_content_status'] == 'discovery_only'
    assert retained_card['eligible_for_report'] is True


def test_javascript_banner_does_not_discard_the_actual_original_table_below_it():
    body = ('## 请开启浏览器的Javascript功能\n\n'
        '| 字段 | 原始记录 |\n| --- | --- |\n| 企业名称 | 青禾网络有限公司 |\n'
        + '\n'.join(f'| 商标申请编号 | {10000+i} |' for i in range(60)))
    original = source(body, fetch_status='done', content_kind='full_text')
    assert source_body(original) == (body, 'retrieved_content')


def test_failed_refetch_does_not_discard_retained_provider_original_or_completed_ocr():
    original = source('青禾网络有限公司2025年年度报告。这里是取得的完整原文。',
                      fetch_status='fetch_timeout', content_origin='provider_raw_content')
    assert source_body(original)[1] == 'retrieved_content'
    original.content = 'Access Denied'
    original.source_metadata.update(ocr_text='--- PDF page 2 ---\n青禾网络有限公司原页字段', ocr_status='done')
    assert source_body(original)[1] == 'completed_ocr'
    assert document_pages(original) == [{'page': 2, 'text': '青禾网络有限公司原页字段'}]


def test_article_mentioning_captcha_is_still_retrieved_content():
    body = '青禾网络有限公司公告：公司推出captcha验证码服务，并说明部署范围和使用规则。'
    assert source_body(source(body))[1] == 'retrieved_content'
