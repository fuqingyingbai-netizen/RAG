"""An excerpt-only output must not advertise a completed chapter conclusion."""
import io
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from docx_exporter import markdown_to_docx_bytes
from industry_fact_contracts import render_plan
from test_industry_reasoning import chain, review_claim, EID

NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def test_no_analysis_is_labelled_as_excerpt_instead_of_pending_completed_analysis():
    fact=chain()
    text=render_plan({'facts':[fact]},2,'行业定义',[EID],[])
    assert '尚未形成有效综合结论' in text
    assert '材料整理与口径说明' in text
    assert '本章列示已准入陈述及材料支持的比较和边界分析' not in text
    assert fact['fact_contract']['statement'] in text


def test_real_analysis_remains_visible_and_is_not_replaced_by_failure_notice():
    fact=chain(); claim=review_claim(fact)
    text=render_plan({'facts':[fact]},2,'行业定义',[EID],[claim])
    assert claim['text'] in text and '本章初步判断及其依据如下' in text
    assert '以下仅为来源摘录' not in text


def test_limitations_only_are_not_called_substantive_conclusions():
    fact=chain(); claim=review_claim(fact,claim_kind='limitation')
    text=render_plan({'facts':[fact]},2,'行业定义',[EID],[claim])
    assert '尚未形成实质综合结论' in text
    assert claim['text'] in text


def test_industry_toc_retains_chapter_navigation_without_uncomputed_page_fields():
    for kind,count in [('industry_report',16),('industry_proposal',7)]:
        body='\n\n'.join(f'## {i}. 章节{i}\n\n本章正文。' for i in range(1,count+1))
        with ZipFile(io.BytesIO(markdown_to_docx_bytes(body,document_kind=kind))) as z:
            root=ET.fromstring(z.read('word/document.xml'))
            assert len(root.findall('.//w:bookmarkStart',NS)) == count
            assert len(root.findall('.//w:hyperlink',NS)) == count
            assert not root.findall('.//w:fldSimple',NS)
            bookmarks={b.get('{'+NS['w']+'}name') for b in root.findall('.//w:bookmarkStart',NS)}
            anchors={a.get('{'+NS['w']+'}anchor') for a in root.findall('.//w:hyperlink',NS)}
            assert bookmarks == anchors
