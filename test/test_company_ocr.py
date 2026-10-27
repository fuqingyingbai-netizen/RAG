from types import SimpleNamespace

import pytest

import company_ocr
import research_workflow
from company_ocr import enrich_pdf_pages, native_text_issue
from research_workflow import ResearchWorkflow
from report_agents.company_delivery import company_overclaims


@pytest.mark.parametrize('text', [
    '这是公司2025年年度报告，营业收入人民币100万元，适用项目已勾选，未适用项目□。',
    'Revenue 100 million. Café and Müller; healthy bilingual text 营业收入，繁體字正常保留。',
    'ภาษาไทย' * 12,
])
def test_healthy_native_scripts_do_not_trigger_recognition(text, monkeypatch):
    assert native_text_issue(text) == ''
    monkeypatch.setattr(company_ocr, '_recognize', lambda _: pytest.fail('healthy pages must not invoke OCR'))
    page = {'page': 15, 'text': text}
    assert enrich_pdf_pages(b'not-even-a-pdf', [page])['status'] == 'not_needed'
    assert page['text'] == text


def test_bad_character_maps_and_low_text_are_different_triggers():
    assert native_text_issue('签字页') == 'low_text'
    assert native_text_issue('(cid:42)' * 12) == 'broken_character_map'
    assert native_text_issue('公司' * 20 + 'ཀකα' * 6) == 'mixed_script_character_map'
    assert native_text_issue('公司□' * 20) == ''


def setup_pdf(monkeypatch, lines):
    import pypdfium2
    monkeypatch.setattr(pypdfium2, 'PdfDocument', lambda _: SimpleNamespace(close=lambda: None))
    calls = []
    def transcribe(pdf, n):
        calls.append(n)
        if isinstance(lines, Exception):
            raise lines
        return lines, {'scale': 2.5, 'image_size': [1488, 2105]}
    monkeypatch.setattr(company_ocr, '_transcribe_page', transcribe)
    return calls


def recognized(text, confidence=.97):
    return [[[[1, 2], [300, 2], [300, 28], [1, 28]], text, confidence]]


def test_scanned_page_keeps_native_physical_number_and_coordinates(monkeypatch):
    calls = setup_pdf(monkeypatch, recognized('本公司截至2025年12月31日的财务报告内部控制在所有重大方面有效。'))
    page = {'page': 81, 'text': '', 'native_text_issue': 'low_text'}
    result = enrich_pdf_pages(b'pdf bytes', [page])
    assert calls == [81] and result['accepted_pages'] == [81] and not result['pending_pages']
    assert page['native_text'] == '' and page['text_origin'] == 'local_ocr'
    assert page['ocr_lines'][0]['box'][0] == [1, 2]
    assert page['requires_numeric_layout_review'] is True


def test_bilingual_corruption_does_not_destroy_readable_english(monkeypatch):
    setup_pdf(monkeypatch, recognized('商誉账面价值为人民币4361657千元，原页仍需核对表格列和单位。'))
    native = 'Goodwill RMB 4,361,657 thousand. ' + 'ཀකα' * 6
    page = {'page': 173, 'text': native, 'native_text_issue': native_text_issue(native)}
    result = enrich_pdf_pages(b'pdf bytes', [page])
    assert page['text'] == native and '商誉' in page['ocr_text']
    assert result['alternative_pages'] == [173] and result['pending_pages'] == [173]
    assert result['status'] == 'partial'


def test_high_confidence_sideways_license_is_not_accepted_as_body(monkeypatch):
    text='这是横放在文档中的营业执照，名称和数字识别置信度很高但阅读顺序未经核对。'
    setup_pdf(monkeypatch, [[[[1, 2], [20, 2], [20, 350], [1, 350]], text, .99]])
    page={'page': 5, 'text': '', 'native_text_issue': 'low_text'}
    r=enrich_pdf_pages(b'pdf', [page])
    assert page['ocr_confidence']==.99 and page['ocr_status']=='orientation_requires_review'
    assert page['text']=='' and r['accepted_pages']==[] and r['pending_pages']==[5]


@pytest.mark.parametrize('lines', [[], recognized('公司营业收入及净利润数值需要进一步核对，不能根据低置信度识别替换原文。', .65), RuntimeError('failed')])
def test_empty_low_confidence_and_failure_remain_pending(monkeypatch, lines):
    setup_pdf(monkeypatch, lines)
    page = {'page': 4, 'text': '', 'native_text_issue': 'low_text'}
    result = enrich_pdf_pages(b'pdf bytes', [page])
    assert result['pending_pages'] == [4] and result['accepted_pages'] == []
    assert page['text'] == '' and result['status'] == 'partial'


def test_page_budget_is_explicit_and_never_reported_complete(monkeypatch):
    calls = setup_pdf(monkeypatch, recognized('原始公司财务报告扫描页，数值及表格仍然需要原页逐项校对。'))
    monkeypatch.setenv('COMPANY_PDF_OCR_MAX_PAGES', '1')
    pages = [{'page': n, 'text': '', 'native_text_issue': 'low_text'} for n in (1, 9)]
    result = enrich_pdf_pages(b'pdf bytes', pages)
    assert calls == [1] and result['pending_pages'] == [9] and pages[1]['ocr_status'] == 'budget_pending'


def test_disabled_ocr_does_not_claim_transcription(monkeypatch):
    monkeypatch.setenv('COMPANY_PDF_OCR_ENABLED', 'false')
    assert enrich_pdf_pages(b'pdf', [{'page': 2, 'text': '', 'native_text_issue': 'low_text'}])['status'] == 'disabled'


def test_busy_engine_retains_pending_page_without_opening_pdf(monkeypatch):
    monkeypatch.setattr(company_ocr, '_pdfium_lock', SimpleNamespace(acquire=lambda **kw:False))
    r=enrich_pdf_pages(b'pdf', [{'page': 2, 'text': '', 'native_text_issue': 'low_text'}])
    assert r['status']=='busy' and r['pending_pages']==[2] and r['attempted_pages']==[]


def test_company_wrapper_allows_extraction_budget_without_changing_other_routes(monkeypatch):
    waits=[]
    original=research_workflow.queue.Queue.get
    def get(self, *args, **kwargs):
        waits.append(kwargs.get('timeout'))
        return original(self, *args, **kwargs)
    monkeypatch.setattr(research_workflow.queue.Queue, 'get', get)
    monkeypatch.setattr(research_workflow.web_search_provider, 'fetch_url', lambda *a, **kw:{'content':'original'})
    monkeypatch.setenv('WEB_FETCH_TOTAL_TIMEOUT_SECONDS','45')
    monkeypatch.setenv('COMPANY_PDF_OCR_MAX_SECONDS','60')
    monkeypatch.delenv('COMPANY_PDF_FETCH_TOTAL_TIMEOUT_SECONDS', raising=False)
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    w._fetch_web_url_with_timeout('https://issuer.test/a.pdf',False,document_profile='company')
    w._fetch_web_url_with_timeout('https://issuer.test/a.pdf',False)
    assert waits==[180,45]


def test_pending_notice_never_claims_ocr_was_skipped_after_actual_attempt():
    from report_agents.company_evidence import pending_ocr_notice
    sources=[{'source_metadata':{'document_extraction':{'ocr':{'attempted_pages':[1]}}}}]
    assert '未执行OCR' not in pending_ocr_notice(sources,'未执行OCR')
    assert '已尝试OCR' in pending_ocr_notice(sources,'未执行OCR')
    assert pending_ocr_notice([], '未执行OCR')=='未执行OCR'


def test_old_company_pdf_refetches_once_and_other_routes_do_not(monkeypatch):
    w = ResearchWorkflow.__new__(ResearchWorkflow)
    source = SimpleNamespace(url='https://issuer.test/a.pdf', content='original', source_metadata={'content_kind':'summary_only','fetch_status':'empty_pdf','document_extraction': {'needs_ocr_pages': [30]}})
    p = SimpleNamespace(target_type='company', sources=[source])
    calls = []
    result = {'content': '原文加扫描转录', 'document_pages': [{'page': 30, 'text': '扫描转录'}],
              'document_extraction': {'needs_ocr_pages': [], 'ocr': {'version': company_ocr.VERSION, 'status': 'transcribed', 'accepted_pages': [30]}}}
    monkeypatch.setattr(w, '_fetch_web_url_with_timeout', lambda *a, **kw: calls.append(kw) or result)
    db = SimpleNamespace(commit=lambda: None)
    assert w.enrich_ocr_sources(db, p) == 1
    assert source.content == '原文加扫描转录' and source.source_metadata['ocr_status'] == 'transcribed'
    from report_agents.company_evidence import source_body
    assert source_body(source)[1]=='retrieved_content'
    assert w.enrich_ocr_sources(db, p) == 0 and len(calls) == 1
    p.target_type = 'industry'
    assert w.enrich_ocr_sources(db, p) == 0 and len(calls) == 1


def test_failed_refetch_keeps_original_and_pending_pages(monkeypatch):
    w = ResearchWorkflow.__new__(ResearchWorkflow)
    source = SimpleNamespace(url='https://issuer.test/a.pdf', content='original', source_metadata={'document_extraction': {'needs_ocr_pages': [30]}})
    monkeypatch.setattr(w, '_fetch_web_url_with_timeout', lambda *a, **kw: {'status': 'http_403', 'error': 'forbidden'})
    assert w.enrich_ocr_sources(SimpleNamespace(commit=lambda: None), SimpleNamespace(target_type='company', sources=[source])) == 0
    assert source.content == 'original' and source.source_metadata['document_extraction']['needs_ocr_pages'] == [30]
    assert source.source_metadata['ocr_retry']['status'] == 'http_403'


def test_sparse_company_pdf_keeps_ocr_gaps_without_mobile_or_reader_replacement(monkeypatch):
    import web_search
    provider=web_search.WebSearchProvider()
    result={'status':'empty_pdf','content':'','pages':3,'document_pages':[{'page':1,'text':''}],
            'document_extraction':{'complete':False,'needs_ocr_pages':[1,2,3]}}
    calls=[]
    monkeypatch.setattr(provider,'_fetch_url_once',lambda *a,**kw:calls.append(kw) or result)
    monkeypatch.setattr(provider,'_fetch_with_reader_proxy',lambda *a:pytest.fail('reader would discard acquired PDF provenance'))
    assert provider.fetch_url('https://issuer.test/a.pdf',False,document_profile='company')==result
    assert len(calls)==1


def test_failed_pdf_body_does_not_promote_search_summary_to_original():
    from report_agents.company_evidence import source_body
    source={'content':'搜索摘要声称公司没有任何诉讼。','summary':'搜索摘要声称公司没有任何诉讼。',
            'source_metadata':{'fetch_status':'empty_pdf','document_extraction':{'needs_ocr_pages':[1]}}}
    assert source_body(source)[1]=='discovery_summary'


@pytest.mark.parametrize('line', [
    '数据库默认查询不能证明全历史无处罚、无失信或无重大风险。',
    '平台未命中不代表无行政处罚。',
    '不得表述为无历史行政处罚。',
    '该接口本次未检出，不能等同于无诉讼、无处罚的确定结论。',
    '栏目链接不能作为存在或不存在诉讼的证据。',
    '现阶段不能据此认定存在或不存在行政处罚。',
])
def test_delivery_allows_explicit_evidence_boundaries(line):
    assert company_overclaims(line) == []


@pytest.mark.parametrize('line', [
    '公司无行政处罚。', '公司不存在任何诉讼。', '| 法律合规风险 | 法律合规风险：0 |',
    '不能证明无失信，但公司无行政处罚。',
    '不能证明没有风险。该公司无失信。',
    '待核验：企业无行政处罚。',
    '不能等同于无诉讼；公司无行政处罚。',
    '链接不能作为存在或不存在诉讼的证据，但公司不存在诉讼。',
    '链接不能作为存在或不存在诉讼的证据，公司不存在诉讼。',
    '不能等同于零风险，公司无行政处罚。',
])
def test_delivery_still_rejects_unbacked_clean_conclusions(line):
    assert company_overclaims(line)
