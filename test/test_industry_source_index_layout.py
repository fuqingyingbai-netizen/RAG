"""Source-index layout holdouts from the screenshot, including repaired old Markdown."""
import io
from copy import deepcopy
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from docx_exporter import markdown_to_docx_bytes
from industry_grounding import display_source_title, source_markdown_link
from industry_research import append_evidence_index
from report_agents.industry_report_agent import IndustryReportAgent
from test_industry_fact_contracts import card

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
HEADERS = '| 证据编号及支持章节 | 原始来源与发布日期 | 定位识别 |\n| --- | --- | --- |\n'
URL = 'https://research.example/reports/post_10166373.html?download=1&lang=cn'


def export(markdown):
    with ZipFile(io.BytesIO(markdown_to_docx_bytes(markdown, document_kind='industry_report'))) as archive:
        return ET.fromstring(archive.read('word/document.xml')), ET.fromstring(archive.read('word/_rels/document.xml.rels'))


@pytest.mark.parametrize('markup', ['<br/>', '&lt;br/&gt;', '<br />', '&#10;'])
def test_old_title_markup_does_not_break_the_link_or_expose_markdown(markup):
    source = '[深圳市人民代表大会公告'+markup+'机器人产业促进条例]('+URL+')<br>发布：日期待核验'
    document, relationships = export('## 15. 来源\n'+HEADERS+'| E-ABCDEF123456<br>第1、3章 | '+source+' | 原文位置：155–230<br>指纹前缀：<br>c694ca3d6349 |')
    visible = ''.join(t.text or '' for t in document.iter(W+'t'))
    assert '](https' not in visible and URL not in visible
    assert '深圳市人民代表大会公告 机器人产业促进条例' in visible
    assert URL in {r.get('Target') for r in relationships}
    parents = {child:parent for parent in document.iter() for child in parent}
    assert list(document.iter(W+'br'))
    assert all(parents[br].tag == W+'r' for br in document.iter(W+'br'))
    source_cell = document.find('.//'+W+'tbl').findall(W+'tr')[1].findall(W+'tc')[1]
    paragraph = source_cell.find(W+'p')
    assert paragraph.find(W+'hyperlink') is not None
    assert len(paragraph.findall('.//'+W+'br')) == 1


def test_title_cleanup_changes_only_the_display_not_source_metadata():
    fact = card('机器人服务提供者应当保护个人信息。',source_title='深圳市公告<br/> 机器人条例 &amp; 配套说明')
    original = deepcopy(fact)
    label = display_source_title(fact['source_title'])
    assert label == '深圳市公告机器人条例 & 配套说明'
    assert '<br' not in source_markdown_link(fact['source_title'], URL)
    assert fact == original


def test_fixed_source_index_grid_cell_widths_and_indents_fit_page_body():
    document, _ = export('## 15. 来源\n'+HEADERS+'| E-ABCDEF123456<br>第1、4、14章 | [机器人产业研究]('+URL+')<br>发布：2026-10-21 | 原文位置：984–1032<br>指纹前缀：<br>a5b2bb72d063 |')
    table = document.find('.//'+W+'tbl')
    widths = [int(n.get(W+'w')) for n in table.find(W+'tblGrid')]
    section = document.find('.//'+W+'sectPr')
    margins = section.find(W+'pgMar')
    body_width = int(section.find(W+'pgSz').get(W+'w')) - int(margins.get(W+'left')) - int(margins.get(W+'right'))
    assert sum(widths) == int(table.find(W+'tblPr/'+W+'tblW').get(W+'w')) == body_width
    assert widths[0] >= 2300 and widths[2] >= 2700
    assert table.find(W+'tblPr/'+W+'tblInd').get(W+'w') == '0'
    assert table.find(W+'tblPr/'+W+'tblLayout').get(W+'type') == 'fixed'
    # CT_TblPr properties must stay in schema order across Word readers.
    property_order = [x.tag for x in table.find(W+'tblPr')]
    assert property_order == [W+tag for tag in ['tblW','tblInd','tblBorders','tblLayout','tblCellMar']]
    for row in table.findall(W+'tr'):
        assert [int(c.find(W+'tcPr/'+W+'tcW').get(W+'w')) for c in row.findall(W+'tc')] == widths
    assert table.find('.//'+W+'tblHeader') is not None
    assert table.find('.//'+W+'trHeight') is None and table.find('.//'+W+'noWrap') is None
    first_cell = table.findall(W+'tr')[1].find(W+'tc')
    eid_run = next(run for run in first_cell.iter(W+'r') if any(t.text=='E-ABCDEF123456' for t in run.iter(W+'t')))
    assert eid_run.find(W+'rPr/'+W+'rFonts').get(W+'ascii') == 'Consolas'
    assert eid_run.find(W+'rPr/'+W+'sz').get(W+'val') == '20'
    assert first_cell.find('.//'+W+'br') is not None


def test_facts_sharing_a_source_each_keep_their_own_matching_locator_row():
    ids = ['E-ABCDEF123456','E-ABCDEF654321']
    facts = [card('2024年中国机器人市场规模达到120亿元。', evidence_id=eid,
                  source_url=URL,source_title='机器人行业研究<br/> 数据附表') for eid in ids]
    for i,fact in enumerate(facts):
        fact['provenance']['locator'].update(start=100+i*100,end=150+i*100,body_sha256='a'*64)
    original = deepcopy(facts)
    report = '## 1. 摘要\n'+','.join(ids)+'\n## 15. 信息来源\n旧索引\n## 16. 核验任务\n'
    packages = {i:{'facts':facts if i==1 else []} for i in range(1,17)}
    markdown, _ = append_evidence_index(report,{'facts':facts,'fact_contract_version':'test'},IndustryReportAgent.outline,packages)
    document, relationships = export(markdown)
    table = document.find('.//'+W+'tbl')
    rows = table.findall(W+'tr')[1:]
    assert len(rows) == 2
    for i,row in enumerate(rows):
        cells = [''.join(t.text or '' for t in cell.iter(W+'t')) for cell in row.findall(W+'tc')]
        assert cells[0] == ids[i]+'第1章'
        assert '原文位置：'+str(100+i*100)+'–'+str(150+i*100) in cells[2]
        assert not any(eid in cells[2] for eid in ids)
    assert sum(r.get('Target')==URL for r in relationships) == 1
    assert facts == original


def test_plain_and_linked_multiline_text_use_valid_run_breaks_without_losing_lines():
    document, _ = export('甲<br>乙 [点击原文]('+URL+')<br>丙')
    paragraph = next(p for p in document.iter(W+'p') if '甲' in ''.join(p.itertext()))
    assert ''.join(t.text or '' for t in paragraph.iter(W+'t')) == '甲乙 点击原文丙'
    assert len(paragraph.findall('.//'+W+'br')) == 2
    assert paragraph.find(W+'br') is None
