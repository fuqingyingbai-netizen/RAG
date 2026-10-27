import hashlib
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest

from report_agents.company_assessment_sources import assessment_source_context


@pytest.mark.parametrize('url,target,usable',[
    ('https://static.cninfo.com.cn/report.pdf','远山制造股份有限公司',True),
    ('https://static.cninfo.com.cn/report.pdf','其他企业股份有限公司',False),
    ('https://manufacturer.test/report.pdf','远山制造股份有限公司',False),
])
def test_nonplatform_admission_uses_original_heading_and_exchange_without_irrelevant_row_decode(monkeypatch,url,target,usable):
    body='远山制造股份有限公司\n2025年年度报告\n| 项目 | 数值 |\n| --- | --- |\n| 营业收入 | 0元 |'
    source=NS(url=url,title='年度报告',content=body,source_metadata={'document_pages':[{'page':1,'text':body}]})
    before=deepcopy(vars(source))
    def forbidden(_):raise AssertionError('non-platform row parsing cannot affect admission')
    monkeypatch.setattr('report_agents.company_assessment_sources.original_field_rows',forbidden)
    result=assessment_source_context(source,target)
    assert result['usable'] is usable and result['subject_bound'] is usable
    assert result['pages']==source.source_metadata['document_pages'] and result['scoped_fields_only'] is False
    assert result['original_sha256']==hashlib.sha256(body.encode()).hexdigest() and vars(source)==before


def test_platform_mixed_company_rows_still_require_native_subject_binding():
    body='| 企业名称 | 指标 | 本期 |\n| --- | --- | --- |\n| 远山制造股份有限公司 | 营业收入 | 0 |\n| 其他企业股份有限公司 | 营业收入 | 999 |'
    source=NS(url='https://www.qcc.com/firm/example.html',title='平台查询',content=body,
              source_metadata={'content_kind':'provider_text','provider_content_complete':True})
    result=assessment_source_context(source,'远山制造股份有限公司')
    assert result['usable'] and result['scoped_fields_only'] and result['pages']==[]
    assert not assessment_source_context(source,'不存在的企业股份有限公司')['usable']
