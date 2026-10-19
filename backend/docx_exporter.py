import base64
import html
import mimetypes
import os
import re
from datetime import datetime
from io import BytesIO
from typing import Callable
from zipfile import ZIP_DEFLATED, ZipFile

try:
    from .research_store import research_store
except ImportError:
    try:
        from research_store import research_store
    except Exception:
        research_store = None


CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""

ROOT_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""

WORD_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>
"""

STYLES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:pPr><w:spacing w:after="120" w:line="300" w:lineRule="auto"/></w:pPr><w:rPr><w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/><w:sz w:val="21"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="CompanyTable"><w:name w:val="Company Table"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="60" w:line="240" w:lineRule="auto"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:pPr><w:jc w:val="center"/><w:spacing w:before="240" w:after="240"/></w:pPr><w:rPr><w:b/><w:color w:val="111827"/><w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/><w:sz w:val="34"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:pPr><w:jc w:val="center"/><w:spacing w:after="240"/></w:pPr><w:rPr><w:color w:val="64748B"/><w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/><w:sz w:val="20"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="ReportTitle"><w:name w:val="Report Title"/><w:basedOn w:val="Normal"/><w:pPr><w:jc w:val="center"/><w:spacing w:before="240" w:after="240"/></w:pPr><w:rPr><w:b/><w:color w:val="111827"/><w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/><w:sz w:val="34"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="ReportSubtitle"><w:name w:val="Report Subtitle"/><w:basedOn w:val="Normal"/><w:pPr><w:jc w:val="center"/><w:spacing w:after="240"/></w:pPr><w:rPr><w:color w:val="64748B"/><w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/><w:sz w:val="20"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="ToCTitle"><w:name w:val="TOC Title"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="420" w:after="180"/><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="6" w:color="D1D5DB"/></w:pBdr></w:pPr><w:rPr><w:b/><w:color w:val="111827"/><w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/><w:sz w:val="28"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="420" w:after="180"/><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="6" w:color="D1D5DB"/></w:pBdr></w:pPr><w:rPr><w:b/><w:color w:val="111827"/><w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/><w:sz w:val="28"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="260" w:after="120"/></w:pPr><w:rPr><w:b/><w:color w:val="1F2937"/><w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/><w:sz w:val="24"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="180" w:after="80"/></w:pPr><w:rPr><w:b/><w:color w:val="374151"/><w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/><w:sz w:val="21"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="SectionHeading"><w:name w:val="section heading"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="260" w:after="120"/></w:pPr><w:rPr><w:b/><w:color w:val="1F2937"/><w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/><w:sz w:val="24"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="SubsectionHeading"><w:name w:val="subsection heading"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="180" w:after="80"/></w:pPr><w:rPr><w:b/><w:color w:val="374151"/><w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/><w:sz w:val="21"/></w:rPr></w:style>
</w:styles>
"""

CORE_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:creator>RAG Research Workflow</dc:creator>
  <cp:lastModifiedBy>RAG Research Workflow</cp:lastModifiedBy>
</cp:coreProperties>
"""

APP_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>RAG Research Workflow</Application></Properties>
"""


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


# URLs in Chinese prose are often immediately followed by a full-width colon
# or explanatory text.  A generic non-whitespace match made that explanation
# part of the Word hyperlink.
_URL_RE = re.compile(r"https?://[A-Za-z0-9][A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]*", flags=re.I)
_EVIDENCE_ID_RE = re.compile(r"\bE-[A-Z0-9-]{6,}\b", flags=re.I)


def _normalize_url(url: str) -> str:
    """Keep Markdown/Chinese sentence punctuation out of a Word hyperlink."""
    return str(url or "").strip().rstrip(".,;:。；，、!?！？)）]】}》>”’\"")


def _plain_runs(
    text: str,
    bold_xml: str,
    evidence_bookmarks: dict[str, tuple[int, str]] | None = None,
    suppress_evidence_links: bool = False,
) -> str:
    """Render text runs and link company E-IDs to chapter 13 bookmarks."""
    body: list[str] = []
    cursor = 0
    for match in _EVIDENCE_ID_RE.finditer(text or ""):
        if match.start() > cursor:
            body.append(f'<w:r><w:rPr>{bold_xml}<w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/></w:rPr><w:t xml:space="preserve">{_esc(text[cursor:match.start()])}</w:t></w:r>')
        evidence_id = match.group(0).upper()
        bookmark = (evidence_bookmarks or {}).get(evidence_id)
        run = (
            f'<w:r><w:rPr>{bold_xml}<w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/>'
            + ('<w:color w:val="0563C1"/><w:u w:val="single"/>' if bookmark and not suppress_evidence_links else '')
            + f'</w:rPr><w:t xml:space="preserve">{_esc(match.group(0))}</w:t></w:r>'
        )
        if bookmark and not suppress_evidence_links:
            run = f'<w:hyperlink w:anchor="{bookmark[1]}" w:history="1">{run}</w:hyperlink>'
        body.append(run)
        cursor = match.end()
    if cursor < len(text or ""):
        body.append(f'<w:r><w:rPr>{bold_xml}<w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/></w:rPr><w:t xml:space="preserve">{_esc((text or "")[cursor:])}</w:t></w:r>')
    return "".join(body)


def _run(
    text: str,
    bold: bool = False,
    hyperlink_id: Callable[[str], str] | None = None,
    evidence_bookmarks: dict[str, tuple[int, str]] | None = None,
    suppress_evidence_links: bool = False,
    compact_url_labels: bool = False,
) -> str:
    bold_xml = "<w:b/>" if bold else ""
    body = []
    for index, part in enumerate(str(text or "").split("\n")):
        if index:
            body.append("<w:br/>")
        cursor = 0
        for match in _URL_RE.finditer(part):
            url = _normalize_url(match.group(0))
            if match.start() > cursor:
                body.append(_plain_runs(part[cursor:match.start()], bold_xml, evidence_bookmarks, suppress_evidence_links))
            if url:
                if hyperlink_id:
                    rid = hyperlink_id(url)
                    body.append(
                        f'<w:hyperlink r:id="{rid}"><w:r><w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/>'
                        f'<w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/></w:rPr>'
                        f'<w:t xml:space="preserve">{_esc("打开原件" if compact_url_labels else url)}</w:t></w:r></w:hyperlink>'
                    )
                else:
                    body.append(f'<w:r><w:rPr>{bold_xml}<w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/></w:rPr><w:t xml:space="preserve">{_esc(url)}</w:t></w:r>')
            cursor = match.start() + len(url)
        if cursor < len(part):
            body.append(_plain_runs(part[cursor:], bold_xml, evidence_bookmarks, suppress_evidence_links))
    return "".join(body) or f'<w:r><w:rPr>{bold_xml}</w:rPr><w:t/></w:r>'


def _page_break() -> str:
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


def _normalize_inline_breaks(text: str) -> str:
    text = html.unescape(str(text or ""))
    return re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.I)


def _clean_inline_markdown(text: str) -> str:
    text = _normalize_inline_breaks(text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\s*>\s*", "", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    return text.strip()


def _is_report_chapter_heading(text: str) -> bool:
    return bool(
        re.match(
            r"^\s*\d{1,2}\s*(?:\.(?!\d)|[、。．）):：\-])\s*\S",
            _clean_inline_markdown(text),
        )
    )


def _company_source_cell(text: str, column: int) -> str:
    """Short Word labels; the Markdown index retains full audit locators."""
    if column==1:
        numbers=sorted(set(map(int,re.findall(r'第\s*(\d+)\s*章',text))))
        if numbers:
            groups=[];start=end=numbers[0]
            for number in numbers[1:]:
                if number==end+1:end=number
                else:
                    groups.append(str(start) if start==end else f'{start}—{end}');start=end=number
            groups.append(str(start) if start==end else f'{start}—{end}')
            return '第'+'、'.join(groups)+'章'
    if column==3 and text.startswith('结构化记录 → '):
        provider=text.removeprefix('结构化记录 → ').split('/',1)[0].strip()
        label='企查查' if provider.startswith('qcc') else '天眼查' if provider=='tyc' else '稀牛' if provider=='xiniu' else provider
        return label+'记录；按本行证据编号查项目台账'
    return text


def _table(
    rows: list[list[str]],
    hyperlink_id: Callable[[str], str] | None = None,
    evidence_bookmarks: dict[str, tuple[int, str]] | None = None,
    company: bool = False,
) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    table_width = 9026 if company else 9360
    col_width = max(900, table_width // max(1, min(width, 8)))
    compact_source=company and rows[0]==['证据编号','支持章节','来源与关键摘要','台账定位']
    widths=[col_width]*width
    if company:
        if compact_source:weights=[22,10,53,15]
        elif rows[0]==['姓名','职务／披露时点','履历要点（公司自述）','出处']:weights=[10,18,50,22]
        elif rows[0]==['字段','登记记录','来源']:weights=[22,53,25]
        else:
            # Give long evidence prose space without devoting the same width
            # to a two-character name or a short numeric column. Use typical
            # cells, not the longest outlier, and retain the normal font size.
            weights=[]
            for cidx in range(width):
                sizes=sorted(len(_clean_inline_markdown(str(row[cidx] if cidx<len(row) else ''))) for row in rows)
                typical=sizes[min(len(sizes)-1,int(len(sizes)*.75))]
                weights.append(max(6,min(26,typical/4)))
        widths=[int(table_width*w/sum(weights)) for w in weights]
        widths[-1]+=table_width-sum(widths)
    grid = "".join(f'<w:gridCol w:w="{value}"/>' for value in widths)
    xml = [
        f'<w:tbl><w:tblPr><w:tblW w:w="{table_width}" w:type="dxa"/>'
        '<w:tblLayout w:type="fixed"/>'
        '<w:tblCellMar><w:top w:w="90" w:type="dxa"/><w:left w:w="120" w:type="dxa"/><w:bottom w:w="90" w:type="dxa"/><w:right w:w="120" w:type="dxa"/></w:tblCellMar>'
        '<w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/></w:tblBorders></w:tblPr>'
        f'<w:tblGrid>{grid}</w:tblGrid>',
    ]
    for ridx, row in enumerate(rows):
        row_props=''
        if company:
            if ridx==0:row_props+='<w:tblHeader/>'
            if max((len(_clean_inline_markdown(str(cell))) for cell in row),default=0)<=160:row_props+='<w:cantSplit/>'
        xml.append('<w:tr>'+('<w:trPr>'+row_props+'</w:trPr>' if row_props else ''))
        padded = row + [""] * (width - len(row))
        for cidx, cell in enumerate(padded):
            if compact_source and ridx>0:cell=_company_source_cell(cell,cidx)
            shade = '<w:shd w:fill="EAF1F8"/>' if ridx == 0 else ""
            v_align = '<w:vAlign w:val="top"/>' if company else '<w:vAlign w:val="center"/>'
            evidence_id = str(cell or "").strip().upper()
            bookmark = (evidence_bookmarks or {}).get(evidence_id) if ridx > 0 and cidx == 0 else None
            xml.append(
                f"<w:tc><w:tcPr><w:tcW w:w=\"{widths[cidx]}\" w:type=\"dxa\"/>{shade}{v_align}</w:tcPr>"
                f"{_paragraph(cell, style='CompanyTable' if company else None, hyperlink_id=hyperlink_id, evidence_bookmarks=evidence_bookmarks, bookmark=bookmark, suppress_evidence_links=bool(bookmark), compact_url_labels=bool(compact_source and ridx>0 and cidx==3))}</w:tc>"
            )
        xml.append("</w:tr>")
    xml.append("</w:tbl>")
    return "".join(xml)


def _paragraph(
    text: str,
    style: str | None = None,
    bullet: bool = False,
    hyperlink_id: Callable[[str], str] | None = None,
    evidence_bookmarks: dict[str, tuple[int, str]] | None = None,
    bookmark: tuple[int, str] | None = None,
    suppress_evidence_links: bool = False,
    compact_url_labels: bool = False,
    keep_next: bool = False,
    keep_lines: bool = False,
) -> str:
    style_xml = f'<w:pStyle w:val="{style}"/>' if style else ""
    indent_xml = '<w:ind w:left="420" w:hanging="220"/>' if bullet else ""
    prefix = "- " if bullet else ""
    bookmark_start = f'<w:bookmarkStart w:id="{bookmark[0]}" w:name="{bookmark[1]}"/>' if bookmark else ""
    bookmark_end = f'<w:bookmarkEnd w:id="{bookmark[0]}"/>' if bookmark else ""
    runs = _run(
        prefix + _clean_inline_markdown(re.sub(r'^原始链接\s*→\s*','',text) if compact_url_labels else text),
        hyperlink_id=hyperlink_id,
        evidence_bookmarks=evidence_bookmarks,
        suppress_evidence_links=suppress_evidence_links,
        compact_url_labels=compact_url_labels,
    )
    after='60' if style=='CompanyTable' else '120'
    keep_xml=('<w:keepNext/>' if keep_next else '')+('<w:keepLines/>' if keep_next or keep_lines else '')
    return f"<w:p><w:pPr>{style_xml}{indent_xml}{keep_xml}<w:spacing w:after=\"{after}\"/></w:pPr>{bookmark_start}{runs}{bookmark_end}</w:p>"


def _is_separator_row(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def _parse_table(
    lines: list[str],
    start: int,
    hyperlink_id: Callable[[str], str] | None = None,
    evidence_bookmarks: dict[str, tuple[int, str]] | None = None,
    company: bool = False,
) -> tuple[str, int]:
    rows: list[list[str]] = []
    i = start
    while i < len(lines) and "|" in lines[i]:
        if not _is_separator_row(lines[i]):
            rows.append([cell.strip() for cell in lines[i].strip().strip("|").split("|")])
        i += 1
    return _table(rows, hyperlink_id=hyperlink_id, evidence_bookmarks=evidence_bookmarks, company=company), i


def _image_payload(target: str) -> tuple[bytes, str] | None:
    target = html.unescape(str(target or "").strip().strip("<>"))
    if not target:
        return None
    data_match = re.match(r"^data:(image/[A-Za-z0-9.+-]+);base64,(.+)$", target, flags=re.S)
    if data_match:
        try:
            return base64.b64decode(re.sub(r"\s+", "", data_match.group(2))), data_match.group(1)
        except Exception:
            return None
    if re.match(r"^https?://", target, flags=re.I):
        return None
    for candidate in [target, target.replace("/", os.sep)]:
        if os.path.isfile(candidate):
            mime = mimetypes.guess_type(candidate)[0] or "image/png"
            return open(candidate, "rb").read(), mime
    if research_store is not None:
        try:
            payload = research_store.get_bytes(target)
            mime = mimetypes.guess_type(target)[0] or "image/png"
            return payload, mime
        except Exception:
            return None
    return None


def _image_drawing(rid: str, alt: str, width_inches: float = 5.8) -> str:
    cx = int(width_inches * 914400)
    cy = int(width_inches * 0.68 * 914400)
    doc_id = int(re.sub(r"\D", "", rid) or "1")
    alt = _esc(alt or "image")
    return f"""
<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:before="120" w:after="120"/></w:pPr><w:r><w:drawing>
<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" distT="0" distB="0" distL="0" distR="0">
  <wp:extent cx="{cx}" cy="{cy}"/>
  <wp:docPr id="{doc_id}" name="{alt}" descr="{alt}"/>
  <a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
    <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
      <pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
        <pic:nvPicPr><pic:cNvPr id="0" name="{alt}"/><pic:cNvPicPr/></pic:nvPicPr>
        <pic:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
        <pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
      </pic:pic>
    </a:graphicData>
  </a:graphic>
</wp:inline>
</w:drawing></w:r></w:p>
"""


def _strip_subheading_number(text: str) -> str:
    return re.sub(r"^\s*\d{1,2}\.\d{1,2}\s+", "", _clean_inline_markdown(text or "")).strip()


def _outline_subheading_map(outline: list[tuple[str, list[str]]] | None) -> dict[int, dict[str, str]]:
    mapping: dict[int, dict[str, str]] = {}
    for index, (_title, subheadings) in enumerate(outline or [], 1):
        chapter_map: dict[str, str] = {}
        for item in subheadings or []:
            canonical = _clean_inline_markdown(str(item or "").strip())
            if not canonical:
                continue
            chapter_map[canonical] = canonical
            chapter_map[_strip_subheading_number(canonical)] = canonical
        mapping[index] = chapter_map
    return mapping


def _outline_subheading(
    outline_map: dict[int, dict[str, str]],
    chapter_index: int | None,
    text: str,
) -> str | None:
    if not outline_map or not chapter_index:
        return None
    cleaned = _clean_inline_markdown(text or "")
    chapter_map = outline_map.get(chapter_index) or {}
    return chapter_map.get(cleaned) or chapter_map.get(_strip_subheading_number(cleaned))


def _collect_headings(lines: list[str], outline: list[tuple[str, list[str]]] | None = None) -> list[tuple[int, str]]:
    headings: list[tuple[int, str]] = []
    outline_map = _outline_subheading_map(outline)
    current_chapter: int | None = None
    for raw in lines:
        match = re.match(r"^\s*(#{1,6})\s*(.+?)\s*$", raw)
        if not match:
            continue
        markdown_level = len(match.group(1))
        text = _clean_inline_markdown(match.group(2))
        if not text:
            continue
        if markdown_level == 2 and _is_report_chapter_heading(text):
            headings.append((2, text))
            chapter_match = re.match(r"^\s*(\d{1,2})\s*(?:\.(?!\d)|[、。．）):：\-])", text)
            current_chapter = int(chapter_match.group(1)) if chapter_match else current_chapter
        elif not outline_map:
            headings.append((3, text))
        else:
            canonical = _outline_subheading(outline_map, current_chapter, text)
            if canonical:
                headings.append((3, canonical))
    return headings


def _cover(title: str, headings: list[tuple[int, str]], review_draft: bool = True) -> str:
    subtitle = "背景调查与桌面研究报告"
    date_text = datetime.now().strftime("%Y-%m-%d")
    first_chapter = next((text for level, text in headings if level == 2), "")
    return (
        '<w:p><w:pPr><w:spacing w:before="1800" w:after="360"/></w:pPr></w:p>'
        + _paragraph(title, style="ReportTitle")
        + _paragraph(subtitle, style="ReportSubtitle")
        + '<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:before="360" w:after="120"/></w:pPr>'
        + _run(f"报告日期：{date_text}") + "</w:p>"
        + '<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:after="120"/></w:pPr>'
        + _run(
            "保密级别：Confidential | 自动生成待复核稿，正式交付前需人工复核"
            if review_draft
            else "保密级别：Confidential | 证据可追溯桌面研究交付版"
        ) + "</w:p>"
        + (_paragraph(f"核心起始章节：{first_chapter}", style="ReportSubtitle") if first_chapter else "")
        + _page_break()
    )


def _toc(headings: list[tuple[int, str]], chapter_bookmarks: dict[str, tuple[int, str]] | None = None) -> str:
    # Keep the generated front-matter directory readable while preserving the
    # same chapter/subtitle hierarchy that Word shows in its navigation pane.
    items = ([(level,text) for level,text in headings if level==2] if chapter_bookmarks is not None
             else [(level,text) for level,text in headings if level<=3][:80])
    if not items:
        return ""
    xml = [_paragraph("目录", style="ToCTitle")]
    for level, text in items:
        left = 240 + (level - 1) * 360
        runs=_run(text)
        if chapter_bookmarks and text in chapter_bookmarks:
            runs=f'<w:hyperlink w:anchor="{chapter_bookmarks[text][1]}" w:history="1">{runs}</w:hyperlink>'
        xml.append(
            f'<w:p><w:pPr><w:ind w:left="{left}"/><w:spacing w:after="80"/></w:pPr>'
            f'{runs}</w:p>'
        )
    xml.append(_page_break())
    return "".join(xml)


FOOTER_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:p>
    <w:pPr><w:jc w:val="center"/><w:pBdr><w:top w:val="single" w:sz="4" w:space="4" w:color="E5E7EB"/></w:pBdr></w:pPr>
    <w:r><w:rPr><w:color w:val="6B7280"/><w:sz w:val="18"/><w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/></w:rPr><w:t>Confidential | 自动生成初稿，需人工复核 | Page </w:t></w:r>
    <w:r><w:rPr><w:color w:val="6B7280"/><w:sz w:val="18"/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r>
    <w:r><w:rPr><w:color w:val="6B7280"/><w:sz w:val="18"/></w:rPr><w:instrText> PAGE </w:instrText></w:r>
    <w:r><w:rPr><w:color w:val="6B7280"/><w:sz w:val="18"/></w:rPr><w:fldChar w:fldCharType="end"/></w:r>
  </w:p>
</w:ftr>
"""


def _footer_xml(review_draft: bool) -> str:
    if review_draft:
        return FOOTER_XML
    return FOOTER_XML.replace("自动生成初稿，需人工复核", "证据可追溯桌面研究交付版")


def markdown_to_docx_bytes(
    markdown: str,
    title: str = "桌面研究交付物",
    review_draft: bool = True,
    outline: list[tuple[str, list[str]]] | None = None,
) -> bytes:
    lines = (markdown or "").replace("\r\n", "\n").split("\n")
    company_claim_index = bool(re.search(r"(?m)^##\s*13[.、．]\s*信息来源（自动生成审计索引）", markdown or ""))
    indexed_evidence_ids = sorted(set(
        match.group(1).upper()
        for line in lines
        for match in [re.match(r"^\|\s*(E-[A-Z0-9-]{6,})\s*\|", line.strip(), flags=re.I)]
        if match
    )) if company_claim_index else []
    evidence_bookmarks = {
        evidence_id: (1000 + index, "evidence_" + re.sub(r"[^A-Za-z0-9_]", "_", evidence_id))
        for index, evidence_id in enumerate(indexed_evidence_ids)
    }
    outline_map = _outline_subheading_map(outline)
    headings = _collect_headings(lines, outline=outline)
    chapter_bookmarks = {text:(index+1,f'company_chapter_{index+1}')
                         for index,text in enumerate(dict.fromkeys(text for level,text in headings if level==2))} if company_claim_index else None
    visible_title = title
    if headings and headings[0][0] == 1:
        visible_title = headings[0][1]
    body: list[str] = []
    media: list[tuple[str, bytes, str]] = []
    relationships = [
        '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>',
        '  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>',
    ]
    hyperlink_ids: dict[str, str] = {}

    def hyperlink_id(url: str) -> str:
        url = _normalize_url(url)
        if url in hyperlink_ids:
            return hyperlink_ids[url]
        rid = f"rId{len(relationships) + 1}"
        hyperlink_ids[url] = rid
        relationships.append(
            f'  <Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
            f'Target="{html.escape(url, quote=True)}" TargetMode="External"/>'
        )
        return rid
    content_type_defaults = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "svg": "image/svg+xml",
    }
    in_code = False
    current_chapter: int | None = None
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if line.startswith("```"):
            in_code = not in_code
            i += 1
            continue
        if in_code:
            if line:
                body.append(_paragraph(raw, evidence_bookmarks=evidence_bookmarks))
            i += 1
            continue
        if not line:
            i += 1
            continue
        if re.fullmatch(r"[-*_]{3,}", line):
            i += 1
            continue
        image = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", line)
        if image:
            alt = image.group(1).strip() or "图片证据"
            payload = _image_payload(image.group(2))
            if payload:
                data, mime = payload
                ext = (mimetypes.guess_extension(mime) or ".png").lstrip(".").replace("jpe", "jpg")
                rid = f"rId{len(relationships) + 1}"
                media_name = f"image{len(media) + 1}.{ext}"
                media.append((media_name, data, mime))
                relationships.append(f'  <Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{media_name}"/>')
                content_type_defaults[ext] = mime
                previous=next((value.strip() for value in reversed(lines[:i]) if value.strip()),'')
                has_caption=company_claim_index and bool(re.match(r'^#{2,6}\s+',previous)) and _clean_inline_markdown(re.sub(r'^#{2,6}\s+','',previous))==alt
                if not has_caption:
                    body.append(_paragraph(alt, style="SectionHeading", evidence_bookmarks=evidence_bookmarks, keep_next=company_claim_index))
                body.append(_image_drawing(rid, alt))
            else:
                body.append(_paragraph(f"{alt}：{image.group(2)}", evidence_bookmarks=evidence_bookmarks))
            i += 1
            continue
        if "|" in line and i + 1 < len(lines) and _is_separator_row(lines[i + 1]):
            table_xml, i = _parse_table(lines, i, hyperlink_id=hyperlink_id, evidence_bookmarks=evidence_bookmarks, company=company_claim_index)
            body.append(table_xml)
            continue
        heading = re.match(r"^(#{1,6})\s*(.*)$", line)
        if heading:
            level = len(heading.group(1))
            text = _clean_inline_markdown(heading.group(2).strip())
            if level == 1:
                style = "ReportTitle"
            elif level == 2 and _is_report_chapter_heading(text):
                style = "Heading1"
                chapter_match = re.match(r"^\s*(\d{1,2})\s*(?:\.(?!\d)|[、。．）):：\-])", text)
                current_chapter = int(chapter_match.group(1)) if chapter_match else current_chapter
            else:
                if not outline_map:
                    style = "Heading2"
                else:
                    canonical = _outline_subheading(outline_map, current_chapter, text)
                    if canonical:
                        text = canonical
                        style = "Heading2"
                    else:
                        style = "SectionHeading"
            body.append(_paragraph(text, style=style, hyperlink_id=hyperlink_id, evidence_bookmarks=evidence_bookmarks,
                                   bookmark=chapter_bookmarks.get(text) if chapter_bookmarks and level==2 else None,
                                   keep_next=company_claim_index))
            i += 1
            continue
        quote = re.match(r"^>\s*(.*)$", line)
        if quote:
            body.append(_paragraph(quote.group(1), hyperlink_id=hyperlink_id, evidence_bookmarks=evidence_bookmarks, keep_lines=company_claim_index))
            i += 1
            continue
        bullet = re.match(r"^[-*]\s+(.*)$", line)
        if bullet:
            body.append(_paragraph(bullet.group(1), bullet=True, hyperlink_id=hyperlink_id, evidence_bookmarks=evidence_bookmarks, keep_lines=company_claim_index))
            i += 1
            continue
        numbered = re.match(r"^\d+[.)、]\s*(.*)$", line)
        if numbered:
            body.append(_paragraph(line, bullet=True, hyperlink_id=hyperlink_id, evidence_bookmarks=evidence_bookmarks, keep_lines=company_claim_index))
            i += 1
            continue
        following=next((value.strip() for value in lines[i+1:] if value.strip()),'')
        preface=company_claim_index and (following.startswith('|') or (len(line)<=120 and line.endswith(('：',':')) and following.startswith(('- ','* '))))
        body.append(_paragraph(line, hyperlink_id=hyperlink_id, evidence_bookmarks=evidence_bookmarks,
                               keep_lines=company_claim_index,keep_next=preface))
        i += 1

    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    {_cover(visible_title, headings, review_draft=review_draft)}
    {_toc(headings, chapter_bookmarks)}
    {''.join(body) or _paragraph(visible_title, style="ReportTitle")}
    <w:sectPr><w:footerReference w:type="default" r:id="rId2" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:footer="720"/></w:sectPr>
  </w:body>
</w:document>
"""
    payload = BytesIO()
    content_types = CONTENT_TYPES_XML.replace(
        "</Types>",
        "".join(
            f'\n  <Default Extension="{ext}" ContentType="{ctype}"/>'
            for ext, ctype in sorted(content_type_defaults.items())
        )
        + "\n</Types>",
    )
    word_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        + "\n".join(relationships)
        + "\n</Relationships>\n"
    )
    with ZipFile(payload, "w", ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", ROOT_RELS_XML)
        docx.writestr("word/_rels/document.xml.rels", word_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/styles.xml", STYLES_XML)
        docx.writestr("word/footer1.xml", _footer_xml(review_draft))
        docx.writestr("docProps/core.xml", CORE_XML)
        docx.writestr("docProps/app.xml", APP_XML)
        for media_name, data, _mime in media:
            docx.writestr(f"word/media/{media_name}", data)
    return payload.getvalue()
