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


def test_native_fallback_preserves_physical_pages_and_both_decoder_outputs(monkeypatch):
    from person_pdf import repair_native_pages
    healthy = 'Amelia Hart was appointed director of Harbor Capital in 2021.'
    broken = '\ufffd' * 30
    pages = [{'page': 4, 'text': broken, 'native_text_issue': 'broken_character_map', 'text_origin': 'embedded_pdf_text'},
             {'page': 5, 'text': healthy, 'native_text_issue': '', 'text_origin': 'embedded_pdf_text'}]
    seen = []
    monkeypatch.setattr('person_pdf._pdfminer_pages', lambda payload, numbers: seen.append(numbers) or {4: healthy, 999: 'not a real requested page'})
    receipt = repair_native_pages(b'immutable original', pages)
    assert seen == [[4]] and receipt['replaced_pages'] == [4]
    assert [p['page'] for p in pages] == [4, 5]
    assert pages[0]['text'] == healthy and pages[0]['text_origin'] == 'embedded_pdf_text_pdfminer'
    assert pages[0]['native_extraction_alternatives'][0]['text'] == broken
    assert 'native_extraction_alternatives' not in pages[1]


def test_pdfminer_subset_uses_physical_numbers_instead_of_renumbered_layout_ids():
    from person_pdf import _pdfminer_pages
    selected = _pdfminer_pages(fixture_pdf(), [2, 55])
    assert list(selected) == [2, 55]
    assert 'Amelia Hart' not in selected[2] and 'Amelia Hart' in selected[55]


def test_failed_or_bounded_native_fallback_keeps_damaged_pages_pending(monkeypatch):
    from person_pdf import repair_native_pages
    pages = [{'page': n, 'text': '\ufffd' * 30, 'native_text_issue': 'broken_character_map'} for n in (2, 3)]
    monkeypatch.setenv('PERSON_PDF_NATIVE_FALLBACK_MAX_PAGES', '1')
    monkeypatch.setattr('person_pdf._pdfminer_pages', lambda *args: {2: 'too little text'})
    receipt = repair_native_pages(b'original', pages)
    assert receipt['attempted_pages'] == [2] and receipt['pending_pages'] == [2, 3]
    assert not receipt['replaced_pages'] and all(p['native_text_issue'] for p in pages)
    def unavailable(*args):
        raise ImportError('optional decoder unavailable')
    monkeypatch.setattr('person_pdf._pdfminer_pages', unavailable)
    receipt = repair_native_pages(b'original', pages)
    assert receipt['status'] == 'unavailable' and receipt['pending_pages'] == [2, 3]
