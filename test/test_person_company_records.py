from types import SimpleNamespace

from person_company_records import company_records
from person_evidence import build_packages
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE
from research_workflow import ResearchWorkflow


def test_company_table_rows_keep_full_values_with_company_scope():
    source = SimpleNamespace(content='### 公司基本信息\n| 字段 | 值 |\n| --- | --- |\n'
        '| 公司简介 | ' + '很长的公司背景介绍' * 100 + ' |\n'
        '| 法定代表 | 林知远 |\n| 主营产品 | 工业软件 |\n| 诉讼记录 | 一起合同争议 |',
        url='structured://xiniu/profile', title='公司资料', source_type='business_database',
        source_metadata={'provider': 'xiniu', 'person_affiliation': {'person_name': '林知远', 'affiliation_name': '恒川软件有限公司'}})
    rows = company_records(source)
    assert len(rows) == 4
    assert all(r['evidence_quote'] in source.content for r in rows)
    assert max(len(r['fact']) for r in rows) > 700
    assert any('很长的公司背景介绍' * 100 in r['fact'] for r in rows)
    package = build_packages({'facts': rows}, '林知远', PERSON_REPORT_OUTLINE)
    assert not package['chapters'][2]['facts']
    assert not package['chapters'][3]['facts']
    assert not package['chapters'][7]['facts']
    assert package['chapters'][4]['facts']
    assert not package['chapters'][6]['facts']  # Target's legal-representative row is not a colleague bio.
    assert package['chapters'][9]['facts']
    assert all(not f['analysis_allowed'] for f in package['chapters'][9]['facts'])


def test_personnel_relationship_rows_are_used_even_without_literal_chapter_title():
    fact = {'fact': '林知远；平台人员记录；{"企业名称":"恒川软件有限公司","角色":["董事"]}',
            'source_url': 'structured://qcc/record', 'identity_confidence': 'high',
            'claim_type': 'person_platform_record', 'person_chapters': [2, 6, 9]}
    package = build_packages({'facts': [fact]}, '林知远', PERSON_REPORT_OUTLINE)
    assert package['chapters'][9]['facts']
    assert not package['chapters'][7]['facts']
    assert any('司法事项' in gap for gap in package['chapters'][9]['information_gaps'])


def test_person_quality_diagnostic_lists_model_rejections_and_dimension_gaps():
    project = SimpleNamespace(target_type='person', target_name='林知远', title='林知远背景调查',
        person_delivery_diagnostic={'chapters': [{'chapter': 7, 'gaps': ['缺少授权访谈记录']}],
        'section_diagnostics': {7: {'validation_rejections': ['indirect_or_conflicting_analysis']}}})
    result = ResearchWorkflow.__new__(ResearchWorkflow)._build_report_quality_diagnostic(project, '', '需复核')
    assert '第7章' in result and '缺少授权访谈记录' in result
    assert 'indirect_or_conflicting_analysis' in result
    assert '未发现章节级证据缺口' not in result
    assert '第14章' in result and '第15章' in result
