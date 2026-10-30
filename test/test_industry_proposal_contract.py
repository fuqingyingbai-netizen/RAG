"""Template content is required; business approval and research remain separate."""
from copy import deepcopy
from hashlib import sha256
import io
import re
from types import SimpleNamespace
from unittest.mock import Mock
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pytest

from report_agents.industry_proposal import build_industry_proposal
from report_agents.industry_proposal_contract import VERSION, render_tables, validate_proposal
from research_workflow import ResearchWorkflow


def project(**scope):
    return SimpleNamespace(id=1, title='行业研究', target_name='机器人', target_type='industry',
        industry_scope={'industry_name': '机器人', 'capital_market': 'none', 'named_companies': [],
                        'purpose': '了解产品与商业化', 'geography': '中国大陆', **scope},
        industry_verification_tasks=[], industry_report_dependency={
            'report_artifact_id': 100, 'report_version': 31, 'report_sha256': 'a' * 64,
            'run_id': 'current-run', 'cleaned_artifact_id': 98, 'risk_artifact_id': 99})


def diagnose(body, p):
    return validate_proposal(body, p.industry_scope, p.industry_verification_tasks)


def test_complete_content_does_not_claim_research_or_business_confirmation():
    p = project()
    body = build_industry_proposal(p)
    d = diagnose(body, p)
    assert d['passed'] and d['covered_count'] == d['requirement_count'] > 30
    assert d['scope_verified'] and d['task_binding_verified']
    assert d['confirmation_status'] == 'pending' and d['pending_confirmations']
    assert d['research_completion_status'] == 'not_evaluated'
    assert all(row['completion_status'] != 'completed' for row in d['requirements'])
    assert re.findall(r'^## (\d+)\.', body, re.M) == list(map(str, range(1, 8)))
    for content in ('渗透率', 'ToB/ToC', '收入结构', '用户粘性', '模型策略', '部署形态',
                    '质量评测', '定价', '付费率', 'ARPU', '留存率', '从业经验及擅长领域',
                    '海外渠道', '行业专家库', '预计工作日及起止日期', '付款安排'):
        assert content in body
    assert '| 企业专项结果 |' not in body and '| 资本专项结果 |' not in body
    assert 'current-run' in body and 'a' * 64 in body and '产物 100' in body
    assert ResearchWorkflow.__new__(ResearchWorkflow)._proposal_quality_warning(body, 'industry', p) == ''


@pytest.mark.parametrize('mutation', ['remove_table', 'appendix_only', 'wrong_chapter', 'remove_metric',
                                    'blank_field', 'invent_fee', 'wrong_columns', 'duplicate_row', 'duplicate_table'])
def test_seven_headings_alone_cannot_hide_missing_or_changed_requirements(mutation):
    p = project()
    body = build_industry_proposal(p)
    tables = render_tables(p.industry_scope, [])
    if mutation in {'remove_table', 'appendix_only', 'wrong_chapter'}:
        body = body.replace(tables['research'], '')
        if mutation == 'appendix_only':
            body += '\n' + tables['research']
        elif mutation == 'wrong_chapter':
            body = body.replace('## 6. 项目团队安排', '## 6. 项目团队安排\n\n' + tables['research'])
    elif mutation == 'remove_metric':
        body = body.replace('ARPU（每用户平均收入）及留存率', '其他指标')
    elif mutation == 'blank_field':
        body = body.replace('| 项目负责人 | 待确认 | 待确认 |', '| 项目负责人 | 待确认 |  |')
    elif mutation == 'invent_fee':
        body = body.replace('| 数据采购 | 待确认 | 待确认 | 待确认 |', '| 数据采购 | 一项 | 10000元 | 已批准 |')
    elif mutation == 'wrong_columns':
        body = body.replace('| 数据采购 | 待确认 | 待确认 | 待确认 |', '| 数据采购 | 待确认 |')
    elif mutation == 'duplicate_row':
        row = '| 数据采购 | 待确认 | 待确认 | 待确认 |'
        body = body.replace(row, row + '\n' + row)
    else:
        body = body.replace(tables['fees'], tables['fees'] + '\n\n' + tables['fees'])
    d = diagnose(body, p)
    assert not d['passed'] and d['errors']
    assert re.findall(r'^## (\d+)\.', body, re.M) == list(map(str, range(1, 8)))
    assert ResearchWorkflow.__new__(ResearchWorkflow)._proposal_quality_warning(body, 'industry', p)
    if mutation == 'remove_metric':
        assert [r['requirement'] for r in d['requirements'] if r['content_status'] != 'present'] == ['商业化指标']


def test_free_analysis_expression_does_not_need_to_match_the_template():
    p = project()
    body = build_industry_proposal(p).replace('## 2. 项目调研分析',
        '## 2. 项目调研分析\n\n结合实际材料讨论收入结构与客户差异，具体推理待人工复核。')
    assert diagnose(body, p)['passed']


def test_optional_work_is_generated_and_checked_against_current_scope():
    p = project(capital_market='summary', named_companies=['甲公司'])
    body = build_industry_proposal(p)
    assert diagnose(body, p)['passed']
    for label in ('指定企业经营', '指定企业管理层', '资本市场专项', '企业专项渠道', '企业专项结果', '资本专项结果'):
        assert '| ' + label + ' |' in body
    closed = diagnose(body, project())
    assert any(e['code'] == 'disabled_scope_included' for e in closed['errors'])
    absent = diagnose(build_industry_proposal(project()), p)
    assert not absent['passed']
    assert validate_proposal(body)['passed']  # standalone content check only
    assert not validate_proposal(body)['scope_verified']


def test_disabled_capital_unknown_is_not_presented_as_a_gap_even_without_tasks():
    p = project()
    body = build_industry_proposal(p, risk_json={'dimensions': [
        {'name': '资本风险', 'score': None}, {'name': '竞争风险', 'score': None}]})
    main = body.split('## 2. 项目调研分析')[1].split('## 3.')[0]
    assert '竞争风险' in main and '资本风险' not in main


def test_work_packages_bind_all_current_tasks_once_and_keep_full_appendix():
    p = project()
    p.industry_verification_tasks = [dict(task_id=f'TASK-{i:02d}', topic=f'核验问题{i}',
        chapters=[str(2 + i % 6)], action=f'核对资料动作{i}', materials='本轮原始数据',
        reason='口径需确认', completion=f'验收条件{i}', priority='高') for i in range(21)]
    body = build_industry_proposal(p)
    schedule = body.split('### 分项工作与排期确认')[1].split('### 交付内容与适用条件')[0]
    appendix = body.split('## 附录A')[1]
    for task in p.industry_verification_tasks:
        assert schedule.count(task['task_id']) == 1
        assert task['action'] in appendix and task['completion'] in appendix
    assert diagnose(body, p)['passed']
    changed = deepcopy(p)
    changed.industry_verification_tasks[-1]['task_id'] = 'NEW-TASK'
    assert not diagnose(body, changed)['passed']


def test_intake_is_table_data_not_new_rows_or_headings():
    p = project(purpose='市场|商业化\n## 9. 伪造章节')
    body = build_industry_proposal(p)
    assert diagnose(body, p)['passed']
    assert re.findall(r'^## (\d+)\.', body, re.M) == list(map(str, range(1, 8)))
    assert '市场／商业化 ## 9. 伪造章节' in body


def test_export_rechecks_actual_body_not_supplied_cached_diagnostic(monkeypatch):
    import research_workflow as module
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    p = project()
    body = build_industry_proposal(p)
    old = diagnose(body, p)
    body = body.replace('ARPU（每用户平均收入）及留存率', '其他指标')
    monkeypatch.setattr(module.research_store, 'put_text', lambda *a, **kw: 'private-text')
    monkeypatch.setattr(module.research_store, 'put_bytes', lambda *a, **kw: 'private-docx')
    monkeypatch.setattr(workflow, '_render_docx_quality', lambda *a: ({'docx_render_status': 'unavailable'}, b''))
    database = Mock()
    database.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    metadata = {'proposal_content_diagnostic': old, 'proposal_initial_quality_warning': '旧候选缺项'}
    artifact = workflow.save_artifact(database, p, 'proposal', '建议书', body, metadata)
    current = artifact.artifact_metadata
    assert current['proposal_template_version'] == VERSION
    assert not current['proposal_content_diagnostic']['passed']
    assert current['proposal_content_diagnostic']['proposal_sha256'] == sha256(body.encode()).hexdigest()
    assert current['proposal_content_summary']['covered_count'] < current['proposal_content_summary']['requirement_count']
    assert '商业化指标' in current['quality_warning']
    assert current['proposal_initial_quality_warning'] == '旧候选缺项'
    assert current['proposal_confirmation_status'] == 'pending'
    # Rebuild uses current tasks without paid model calls. Saving the fixed
    # body clears current failures but retains the initial candidate history.
    fixed = workflow._fallback_proposal(p, '')
    assert workflow._proposal_quality_warning(fixed, 'industry', p) == ''
    renewed = workflow.save_artifact(database, p, 'proposal', '建议书', fixed, current).artifact_metadata
    assert renewed['proposal_content_diagnostic']['passed']
    assert '商业化指标' not in renewed['quality_warning']
    assert renewed['proposal_initial_quality_warning'] == '旧候选缺项'


def test_confirmation_tables_export_with_consistent_columns_and_seven_navigation_targets():
    from docx_exporter import markdown_to_docx_bytes
    from industry_research import validate_docx_package
    payload = markdown_to_docx_bytes(build_industry_proposal(project()), title='建议书', document_kind='industry_proposal')
    assert validate_docx_package(payload)['docx_integrity_status'] == 'passed'
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    with ZipFile(io.BytesIO(payload)) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
        assert len(root.findall('.//w:bookmarkStart', ns)) == 7
        tables = root.findall('.//w:tbl', ns)
        assert len(tables) >= 9
        for table in tables:
            widths = {len(row.findall('w:tc', ns)) for row in table.findall('w:tr', ns)}
            assert len(widths) == 1 and max(widths) <= 4
