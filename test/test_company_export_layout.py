import io
import zipfile
from xml.etree import ElementTree as ET

from docx_exporter import markdown_to_docx_bytes

W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
URL='https://issuer.test/2026/0929/long_original_announcement.pdf?download=1&lang=cn'
INDEX=('## 13. 信息来源（自动生成审计索引）\n\n'
       '| 证据编号 | 支持章节 | 来源与关键摘要 | 台账定位 |\n'
       '| --- | --- | --- | --- |\n'
       '| E-ABC123DEF456 | 第 7 章 | 任命公告 | 原始链接 → '+URL+' |')


def exported(text):
    data=markdown_to_docx_bytes(text,title='公司报告排版核对')
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return ET.fromstring(z.read('word/document.xml')),ET.fromstring(z.read('word/_rels/document.xml.rels'))


def test_company_index_short_link_keeps_exact_original_relationship_and_eid_jump():
    doc,rels=exported('## 7. 团队\n公司聘任披露。[E-ABC123DEF456]\n\n'+INDEX)
    labels=''.join(x.text or '' for x in doc.iter(W+'t'))
    assert '打开原件' in labels and URL not in labels
    assert URL in {r.get('Target') for r in rels}
    assert any(r.get(W+'anchor')=='evidence_E_ABC123DEF456' for r in doc.iter(W+'hyperlink'))
    assert any(r.get(W+'name')=='evidence_E_ABC123DEF456' for r in doc.iter(W+'bookmarkStart'))


def test_company_table_repeats_header_and_keeps_short_rows_together():
    table='| 人员 | 职务 |\n| --- | --- |\n| 王甲 | 董事 |\n| 乙 | '+'长文本'*200+' |\n'
    doc,_=exported('## 7. 团队\n'+table+'\n'+INDEX)
    rows=doc.find('.//'+W+'tbl').findall(W+'tr')
    assert rows[0].find('.//'+W+'tblHeader') is not None
    assert rows[1].find('.//'+W+'cantSplit') is not None
    assert rows[2].find('.//'+W+'cantSplit') is None


def test_person_or_industry_export_does_not_use_company_table_profile():
    doc,_=exported('## 14. 信息来源\n| 来源 | URL |\n| --- | --- |\n| 原件 | '+URL+' |')
    assert URL in ''.join(x.text or '' for x in doc.iter(W+'t'))
    assert doc.find('.//'+W+'tblHeader') is None


def test_company_body_urls_are_not_hidden_by_source_index_compaction():
    doc,_=exported('## 7. 团队\n正文URL：'+URL+'\n\n'+INDEX)
    assert URL in ''.join(x.text or '' for x in doc.iter(W+'t'))


def test_company_roster_allocates_width_to_biography_and_stays_within_page_body():
    table='| 姓名 | 职务／披露时点 | 履历要点（公司自述） | 出处 |\n| --- | --- | --- | --- |\n| 王甲 | 董事 | 既往经历 | 原件 |\n'
    doc,_=exported('## 7. 团队\n'+table+'\n'+INDEX)
    t=doc.find('.//'+W+'tbl');widths=[int(x.get(W+'w')) for x in t.find(W+'tblGrid')]
    assert sum(widths)==11906-1440-1440
    assert widths[2]>2*widths[0] and widths[2]>widths[1]
    assert all(x.get(W+'val')=='top' for x in t.iter(W+'vAlign'))
    assert any(x.get(W+'val')=='CompanyTable' for x in t.iter(W+'pStyle'))


def test_company_heading_stays_with_following_content():
    doc,_=exported('## 7. 团队\n### 任职\n具体任职披露。\n\n'+INDEX)
    headings=[p for p in doc.iter(W+'p') if any(s.get(W+'val') in {'Heading1','Heading2','SectionHeading'} for s in p.iter(W+'pStyle'))]
    assert headings and all(p.find('.//'+W+'keepNext') is not None for p in headings)


def test_company_source_chapter_ranges_and_platform_locator_are_readable():
    index=INDEX.replace('第 7 章','第 1 章、第 2 章、第 3 章、第 5 章').replace('原始链接 → '+URL,'结构化记录 → qcc_company / 企查查-get_key_personnel-目标公司')
    doc,_=exported(index)
    text=''.join(x.text or '' for x in doc.iter(W+'t'))
    assert '第1—3、5章' in text and '企查查记录；按本行证据编号查项目台账' in text
