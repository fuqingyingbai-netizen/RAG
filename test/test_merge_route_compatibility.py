"""Shared exporter must retain each report route's evidence contract after merge."""
import io
import zipfile
from xml.etree import ElementTree as ET

from docx_exporter import markdown_to_docx_bytes
from research_workflow import ResearchWorkflow

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def document(markdown):
    with zipfile.ZipFile(io.BytesIO(markdown_to_docx_bytes(markdown))) as archive:
        return ET.fromstring(archive.read('word/document.xml'))


def test_person_literal_source_and_industry_damaged_text_policy_do_not_cross():
    quote = '林知远原始记录中含有一个缺字�，此处保留原件字样，尚须核实。'
    table = '| 信息点 | 说明 |\n| --- | --- |\n| ' + quote + ' | 来源原文待核验 |\n'
    person = document('## 2. 履历\n' + table + '\n## 14. 信息来源（正文实际引用索引）\n原件定位。')
    assert quote in ''.join(node.text or '' for node in person.iter(W + 't'))
    assert any(node.get(W + 'val') == 'PersonTable' for node in person.iter(W + 'pStyle'))
    industry = document('## 2. 行业证据\n' + table + '\n## 15. 信息来源\n原件定位。')
    text = ''.join(node.text or '' for node in industry.iter(W + 't'))
    assert quote not in text and '请核对原始来源' in text
    assert any(node.get(W + 'val') == 'TableText' for node in industry.iter(W + 'pStyle'))
    assert person.find('.//' + W + 'tblHeader') is not None
    assert industry.find('.//' + W + 'tblHeader') is not None


def test_person_followup_keeps_original_while_company_and_industry_keep_own_plans():
    workflow = ResearchWorkflow()
    person = '## 7. 商业操守\n> 原文称“未履约”，其事实与处理结果待核验。\n\n## 15. 后续研究点\n核对原始契约与履行记录。'
    assert workflow._consolidate_report_verification_gaps(person, target_type='person') == person
    industry = workflow._consolidate_report_verification_gaps('## 2. 行业规模\n缺少同期间收入统计及原始口径，仍待核验。', target_type='industry')
    assert '集中式待核验清单' in industry
    company = workflow._consolidate_report_verification_gaps('## 2. 工商股权\n缺少完整登记原件，历史变更时间仍待核验。', target_type='company')
    assert '14. 后续研究建议' in company
    assert '集中式待核验清单' not in company
