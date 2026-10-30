from types import SimpleNamespace
from person_evidence import build_packages
from person_records import personal_analysis_allowed
from person_source_context import signature_only_context, document_issuer
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


def test_other_director_page_does_not_become_targets_salary_from_closing_signature():
    body = ('各新董事有权收取董事袍金每年60万人民币。公司将根据其职责和表现审阅薪酬。'
            '各新董事已确认其与主要股东没有关系，其他事项已按文件载明披露，任期按各自服务合约执行。')
    quote = body + '\n承董事会命\n远山科技有限公司\n主席\n林知远'
    source = SimpleNamespace(url='https://fixture.invalid/filing.pdf', content=quote,
                             title='董事变更公告', source_type='filing', source_metadata={})
    package = build_packages({'facts': [{'fact': quote, 'source_url': source.url,
        'identity_match': 'confirmed'}]}, '林知远', PERSON_REPORT_OUTLINE, sources=[source])
    row = next(f for f in package['facts'] if f['fact'] == quote)
    assert row['personal_attribution_pending'] and row['fact'] == quote
    assert not personal_analysis_allowed(row) and not row['eligible_for_risk_scoring']
    assert not row['observation']['direct_person_link']


def test_target_body_or_honorific_is_not_signature_only_and_spaced_issuer_is_read_literally():
    prefix = '公司公告内容。' * 25
    assert not signature_only_context(prefix+'林知远获委任董事。承董事会命\n林知远', ['林知远'])
    assert not signature_only_context(prefix+'林先生获委任董事。承董事会命\n林知远', ['林知远'])
    assert not signature_only_context('承董事会命\n林知远', ['林知远'])
    source = SimpleNamespace(source_metadata={'document_pages':[{'page':1,'text':'远 山 科 技 有 限 公 司\n公告'}]})
    assert document_issuer(source) == '远 山 科 技 有 限 公 司'
