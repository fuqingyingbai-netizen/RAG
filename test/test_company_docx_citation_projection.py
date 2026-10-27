"""Actual DOCX bytes must keep prose on both sides of native citations."""
import io
import zipfile
from xml.etree import ElementTree as ET

import pytest

from docx_exporter import markdown_to_docx_bytes
from report_agents.company_delivery_contract import validate_docx
from report_agents.company_report_agent import COMPANY_REPORT_OUTLINE as OUTLINE


def report_with(body):
    return '\n\n'.join(
        f'## {n}. {title}' + ('（自动生成审计索引）' if n == 13 else '') + '\n\n' + (
            body if n == 6 else
            '| 证据编号 | 原件 |\n| --- | --- |\n| E-123456ABCDEF | 原始披露 |' if n == 13 else
            '具体正文内容必须完整保留以便阅读和核对。'
        ) for n, (title, _) in enumerate(OUTLINE, 1)
    )


@pytest.mark.parametrize('body', [
    '- 公司披露营业收入为人民币351.4百万元。[E-123456ABCDEF]（物理页30）',
    '公司新增产线计划尚未完成。[E-123456ABCDEF]该计划仍须股东会批准。',
    '收入本期为人民币0元。[E-123456ABCDEF]上年同期为人民币12.50万元。',
    'Remote-Northstar retained API_V2 unchanged.[E-123456ABCDEF]Subject to approval.',
    '| 项目 | 原值和条件 |\n| --- | --- |\n| 收入 | 351.4百万元[E-123456ABCDEF]（物理页30） |',
])
def test_exact_prose_after_native_citation_survives_export(body):
    report = report_with(body)
    payload = markdown_to_docx_bytes(report, outline=OUTLINE)
    result = validate_docx(payload, report, OUTLINE)
    assert result['docx_integrity_status'] == 'passed', result


@pytest.mark.parametrize('before,after', [
    ('351.4百万元', '351.4万元'),
    ('（物理页30）', ''),
    ('仍须股东会批准', '已经获得股东会批准'),
    ('API_V2', 'APIV2'),
    ('Remote-Northstar', 'RemoteNorthstar'),
])
def test_projection_does_not_excuse_real_content_changes(before, after):
    report = report_with(
        'Remote-Northstar的API_V2收入为351.4百万元[E-123456ABCDEF]（物理页30）；'
        '新增产线仍须股东会批准。'
    )
    payload = markdown_to_docx_bytes(report, outline=OUTLINE)
    with zipfile.ZipFile(io.BytesIO(payload)) as original:
        root = ET.fromstring(original.read('word/document.xml'))
        changed = False
        for node in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'):
            if before in (node.text or ''):
                node.text = node.text.replace(before, after)
                changed = True
        assert changed
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as edited:
            for name in original.namelist():
                edited.writestr(name, ET.tostring(root) if name == 'word/document.xml' else original.read(name))
    result = validate_docx(output.getvalue(), report, OUTLINE)
    assert result['docx_integrity_status'] == 'failed'
    assert 'docx_missing_prose:6' in result['docx_integrity_errors']
