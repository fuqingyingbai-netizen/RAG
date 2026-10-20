from io import BytesIO
from types import SimpleNamespace

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from person_pdf import extract_person_pdf
from web_search import WebSearchProvider


def fixture_pdf():
    writer = PdfWriter()
    for number in range(55):
        page = writer.add_blank_page(612, 792)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        text = 'Amelia Hart is director of Harbor Capital, appointed in 2021.' if number == 54 else 'Financial disclosure page; no person identity on this introduction.'
        stream = DecodedStreamObject()
        stream.set_data(f'BT /F1 12 Tf 40 700 Td ({text}) Tj ET'.encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO(); writer.write(output)
    return output.getvalue()


def test_person_pdf_retains_late_biography_and_reports_real_page_coverage(monkeypatch):
    payload = fixture_pdf()
    result = extract_person_pdf(payload)
    assert result['pages'] == 55 and result['document_extraction']['complete']
    assert 'Amelia Hart' in result['content'] and 'PDF page 55' in result['content']
    monkeypatch.setenv('PERSON_PDF_MAX_PAGES', '40')
    result = extract_person_pdf(payload)
    assert not result['document_extraction']['complete']
    assert result['document_extraction']['omitted_page_numbers'] == list(range(41, 56))
    assert 'Amelia Hart' not in result['content']


def test_person_network_profile_does_not_apply_generic_body_clip(monkeypatch):
    payload = fixture_pdf()
    response = SimpleNamespace(content=payload, headers={'Content-Type': 'application/pdf'}, url='https://filing.invalid/report.pdf', raise_for_status=lambda: None)
    monkeypatch.setattr('web_search.requests.get', lambda *a, **kw: response)
    result = WebSearchProvider()._fetch_url_once(response.url, 12, 1000, 'test', 'desktop', document_profile='person')
    assert len(result['content']) > 1000 and 'Amelia Hart' in result['content']
