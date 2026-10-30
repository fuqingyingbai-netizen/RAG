"""Frozen failure examples, positive controls and bounded-input regressions."""
import io
import json
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pytest

from docx_exporter import markdown_to_docx_bytes
from industry_analysis import complete_plan, observed_business
from industry_delivery import verification_tasks
from industry_fact_contracts import attach_contract, chapter_coverage, render_plan
from industry_grounding import metric_period_region
from industry_research import normalize_risk
from industry_risk_input import risk_input, attach_selection
from test_industry_fact_contracts import card, SCOPE
from text_integrity import text_issues, decode_http_text


@pytest.mark.parametrize('encoding', ['utf-8', 'gb18030'])
def test_http_bytes_are_decoded_without_inheriting_requests_latin1_default(encoding):
    from types import SimpleNamespace
    text = '<html><meta charset="'+encoding+'"><p>中国机器人企业采用按量计费。</p></html>'
    raw = text.encode(encoding)
    response = SimpleNamespace(content=raw, encoding='ISO-8859-1', headers={'Content-Type': 'text/html'},
                               apparent_encoding=encoding, text=raw.decode('latin1'))
    assert decode_http_text(response) == text
    assert not text_issues(decode_http_text(response))


@pytest.mark.parametrize('text', [
    '机器人在场景应用中采用按量计费。'.encode('utf-8').decode('latin1'),
    '机器人在场景应用中采用按量计费。'.encode('utf-8').decode('cp1252', errors='replace'),
    '机器人技术路\ufffd线需要复核。',
    '浜哄伐鏅鸿兘正在发展。',
    '全球视角 美国在技术上拥有全球领',
    '新工具旨在简化企业机器学习模型的',
    '竞争性风险需要进一步核查。 ## 事件经过 播报',
])
def test_corrupt_or_truncated_text_is_not_body_or_index_evidence(text):
    from industry_assertions import reader_evidence_excerpt
    f = attach_contract(card(text), SCOPE)
    assert not f['fact_contract']['report_admitted']
    assert '暂不' in reader_evidence_excerpt({**card(text), 'eligible_for_report': True}) or '不转述' in reader_evidence_excerpt({**card(text), 'eligible_for_report': True})


def test_valid_multilingual_names_symbols_and_complete_chinese_are_preserved():
    assert not text_issues('机器人研究者 François、Søren 与 Åsa 比较 café 场景；带宽为10 GB/s，延迟为5 ms。')
    text = '机器人软件采用按量计费，用户按实际调用量支付费用。'
    assert attach_contract(card(text), SCOPE)['fact_contract']['report_admitted']


def test_declared_gbk_is_respected_when_its_bytes_also_form_valid_utf8():
    from types import SimpleNamespace
    raw = '<meta charset="gb18030">漏'.encode('gb18030')
    assert raw.decode('utf-8').endswith('©')
    response = SimpleNamespace(content=raw, encoding='ISO-8859-1', headers={}, apparent_encoding='utf-8')
    assert decode_http_text(response).endswith('漏')


def test_legacy_index_export_holds_damaged_cell_but_keeps_citation_and_url():
    broken = '在场景采用新技术。'.encode('utf-8').decode('latin1')
    markdown = ('## 15. 来源\n| 证据编号与原始来源 | 支持章节 | 信息点 | 获取工具与信源等级 |\n'
                '| --- | --- | --- | --- |\n| E-123456789ABC https://research.example/original | 第1章 | '+broken+' | tavily / C |')
    data = markdown_to_docx_bytes(markdown, document_kind='industry_report')
    with ZipFile(io.BytesIO(data)) as z:
        document = z.read('word/document.xml').decode('utf-8')
        assert broken not in document and '暂不转述' in document and 'E-123456789ABC' in document
        assert 'https://research.example/original' in z.read('word/_rels/document.xml.rels').decode('utf-8')


def checked(quote, module, i, **kwargs):
    return attach_contract(card(quote, module=module, evidence_id=f'E-{i:012X}', **kwargs), SCOPE)


@pytest.mark.parametrize('quote', [
    '人工智能 | 全产业链梳理: 甲、乙、丙、丁、戊、己，产业进入下游场景验证收入的阶段。',
    '> 注：以上为粗略估算，实际成本受吞吐量、并发数影响。',
    '“新架构标志着机器人技术路线分化突破的出现',
    '全球前3大生产商占有大约 %的市场份额。',
])
def test_orphans_titles_unclosed_quotes_and_missing_quantities_are_held(quote):
    f = attach_contract(card(quote), SCOPE)
    assert not f['fact_contract']['report_admitted']


def test_complete_quotation_and_real_qualification_remain_usable():
    f = checked('研究者指出：“机器人上游提供控制器，中游完成集成，下游服务制造。”', '细分赛道与产业链', 1)
    assert f['fact_contract']['report_admitted']
    assert checked('机器人产业链上游提供控制器，中游完成整机集成，下游服务制造场景。', '细分赛道与产业链', 2)['fact_contract']['report_admitted']
    from industry_passages import atomic_passages
    quote = '研究者指出：“机器人上游提供控制器，中游完成集成。下游服务制造场景。”'
    assert list(atomic_passages(quote)) == [quote]
    assert attach_contract(card(quote), SCOPE)['fact_contract']['statement'].endswith('场景。”')


def test_forecast_base_and_target_are_distinct_without_mutating_source():
    quote = '中国机器人市场规模预计从2022年的940亿元增长至2030年的9930亿元。'
    base = card(quote, '市场规模', '940', '亿元')
    base['numeric_context'].update(period='2022', is_forecast=True)
    target = card(quote, '市场规模', '9930', '亿元')
    target['numeric_context'].update(period='2030', is_forecast=True)
    b, t = attach_contract(base, SCOPE), attach_contract(target, SCOPE)
    assert b['fact_contract']['report_admitted'] and t['fact_contract']['report_admitted']
    assert not b['numeric_context']['is_forecast'] and t['numeric_context']['is_forecast']
    assert '历史基期值' in b['fact_contract']['statement']
    assert '2030' in t['fact_contract']['statement']
    assert base['numeric_context']['is_forecast']  # saved audit input is unchanged
    assert metric_period_region(quote, '市场规模', '9930', '亿元')[0] == '2030'


def test_estimate_has_its_own_label_and_is_not_certified_observation():
    f = card('中国机器人市场规模估计在2024年达到19.73亿美元。', '市场规模', '19.73', '亿美元')
    f['numeric_context']['is_forecast'] = True
    c = attach_contract(f, SCOPE)
    assert '来源估计值' in c['fact_contract']['statement']
    assert not c['numeric_context']['is_forecast']


def test_saved_source_extraction_preserves_separate_base_and_target_cards():
    from types import SimpleNamespace
    from industry_research import extract_industry_source_facts, annotate_fact
    quote = '中国机器人市场规模预计从2022年的940亿元增长至2030年的9930亿元。'
    source = SimpleNamespace(url='https://research.example/robot', title='机器人市场报告', content=quote,
        source_type='web_search', source_metadata={'module': '市场规模与增长'}, credibility_score=80, object_key='saved.txt')
    rows = [annotate_fact(f, SCOPE) for f in extract_industry_source_facts([source], SCOPE)]
    by_value = {str(f['numeric_context']['value']): f for f in rows if f.get('numeric_context')}
    assert set(by_value) == {'940', '9930'}
    assert by_value['940']['numeric_context']['is_forecast'] is False
    assert by_value['9930']['numeric_context']['is_forecast'] is True
    assert by_value['940']['evidence_id'] != by_value['9930']['evidence_id']


def test_rhetorical_business_opinion_is_not_actual_payment_or_summary_evidence():
    f = checked('如果说传统经济依靠销售，那么机器人经济则是以生产力为核心、按量计费的全新模式。', '商业模式与盈利逻辑', 1)
    assert f['fact_contract']['source_role'] == 'opinion'
    assert not f['fact_contract']['risk_admitted'] and not observed_business(f)
    coverage = chapter_coverage({'facts': [f]}, 10, [f['evidence_id']])
    assert coverage[0]['status'] == 'background_only' and not coverage[0]['evidence_ids']
    report = render_plan({'facts': [f]}, 10, '商业化', [f['evidence_id']])
    assert '实际经营指标仍缺证' in report and '未形成行业实际付费' in report
    actual = checked('机器人软件采用按量计费，用户按实际调用量支付费用。', '商业模式与盈利逻辑', 2)
    assert observed_business(actual)
    assert chapter_coverage({'facts': [actual]}, 10, [actual['evidence_id']])[0]['evidence_ids'] == [actual['evidence_id']]


def risk_cards():
    texts = [
        ('第三条 机器人服务提供者应当建立安全管理制度，保障使用者合法权益。', '政策与监管'),
        ('机器人市场需求增长仍需结合实际采购及新增订单核对。', '市场规模与增长'),
        ('机器人供应商迁移成本形成进入壁垒，限制替代竞争。', '竞争格局与代表企业'),
        ('机器人软件采用按量计费，用户按实际调用量支付费用。', '商业模式与盈利逻辑'),
        ('机器人采用统一硬件开展测试，测试条件限定为相同模型和量化精度。', '技术路线对比'),
    ]
    return [checked(text, module, i + 1, **({'source_title': '机器人服务管理办法',
                 'source_url': 'https://www.cac.gov.cn/robot'} if module == '政策与监管' else {}))
            for i, (text, module) in enumerate(texts)]


def test_scoring_budget_keeps_applicable_dimensions_and_exact_authorized_ids():
    fs = risk_cards()
    # Hundreds of long cards and private diagnostic fields cannot displace a dimension.
    noise = [{**fs[1], 'evidence_id': f'E-{n:012X}', 'original_model_fact': '未经授权999亿元',
              'validation_diagnostic': {'reason': '旧失败理由'}, 'source_title': '长标题' * 200} for n in range(100, 250)]
    p = risk_input(noise + fs, SCOPE, 9000)
    assert len(json.dumps(p, ensure_ascii=False)) <= 9000
    for name, row in p['input_selection'].items():
        assert row['available_applicable_count'] and row['retained_applicable_count']
        assert p['dimension_evidence_ids'][name]
    assert '资本热度与估值风险' not in p['dimension_evidence_ids']
    assert '未经授权999' not in json.dumps(p, ensure_ascii=False)
    allowed = {f['evidence_id'] for f in p['facts']}
    assert all(set(ids) <= allowed for ids in p['dimension_evidence_ids'].values())


def test_budget_loss_is_not_a_purchase_task_or_an_automatic_score():
    f = risk_cards()[0]
    raw = normalize_risk({}, [], SCOPE)
    selection = {'政策与监管风险': {'available_applicable_count': 5, 'retained_applicable_count': 0, 'selection_status': 'budget_excluded'}}
    result = attach_selection(raw, selection)
    row = next(d for d in result['dimensions'] if d['name'] == '政策与监管风险')
    assert row['score'] is None and row['unknown_cause'] == 'evidence_budget_excluded'
    tasks = verification_tasks({'facts': [f]}, result, [], SCOPE)
    task = next(t for t in tasks if t['topic'] == '政策与监管风险')
    assert task['task_type'] == 'input_selection_review' and '重新分配证据预算' in task['action']
    assert result['overall_score'] is None


def test_evidence_operations_add_market_comparison_boundary_without_new_growth():
    fs=[]
    for i, year in enumerate(('2023', '2024')):
        f = card(f'{year}年中国机器人市场规模超过{100+i*50}亿元。', '市场规模', str(100+i*50), '亿元', evidence_id=f'E-{i+1:012X}')
        f['numeric_context'].update(period=year, definition='中国机器人市场规模')
        fs.append(attach_contract(f, SCOPE))
    body = render_plan({'facts': fs}, 4, '市场', [f['evidence_id'] for f in fs])
    assert '材料整理与口径说明' in body and '不能用下限变化代替实际增长率' in body
    assert '50%' not in body


def test_event_material_is_deduplicated_without_claiming_a_heat_index():
    fs = [checked('2025年5月1日发布《机器人服务办法》，自2025年8月1日起施行。', '政策与监管', i,
                  source_title='机器人服务办法', source_url='https://www.cac.gov.cn/robot') for i in (1, 2)]
    chosen = complete_plan({'facts': fs}, 5, [f['evidence_id'] for f in fs])
    assert len(chosen) == 1
    amended = checked('2026年6月1日发布《机器人服务办法》，自2026年8月1日起施行。', '政策与监管', 3,
                      source_title='机器人服务办法', source_url='https://www.cac.gov.cn/robot')
    assert len(complete_plan({'facts': fs+[amended]}, 5, [f['evidence_id'] for f in fs]+[amended['evidence_id']])) == 2


def test_explicit_year_estimate_footnote_survives_contract_compilation():
    f = card('中国机器人市场规模2024年达到120亿元。注：2024年数据为预估值。', '市场规模', '120', '亿元')
    compiled = attach_contract(f, SCOPE)
    assert '来源估计值' in compiled['fact_contract']['statement']
    assert not compiled['numeric_context']['is_forecast']


def test_forward_estimate_is_still_forecast_relative_to_the_report_cutoff():
    from industry_research import annotate_fact
    f = card('中国机器人市场规模估计在2030年达到120亿元。', '市场规模', '120', '亿元',
             cleaning_method='llm', evidence_quote_verified=True)
    f['numeric_context']['period'] = '2030'
    scope = {**SCOPE, 'as_of_date': '2026-10-14'}
    checked = annotate_fact(f, scope)
    assert checked['numeric_validation']['passed'] and checked['numeric_context']['is_forecast']
    assert '预测/目标值' in attach_contract(checked, scope)['fact_contract']['statement']


def test_exact_comparison_and_policy_analysis_use_only_their_supporting_cards():
    amounts = []
    for i, year in enumerate(('2023', '2024')):
        f = card(f'{year}年中国机器人市场规模达到{100+i*50}亿元。', '市场规模', str(100+i*50), '亿元', evidence_id=f'E-{i+1:012X}')
        f['numeric_context'].update(period=year, definition='中国机器人市场规模')
        amounts.append(attach_contract(f, SCOPE))
    body = render_plan({'facts': amounts}, 4, '市场', [f['evidence_id'] for f in amounts])
    assert '后期记录的数值较高' in body and '尚不等于经方法核验的行业增长结论' in body
    policy = risk_cards()[0]
    body = render_plan({'facts': [policy]}, 3, '政策', [policy['evidence_id']])
    assert '义务对象及要求' in body and '机器人服务提供者应当建立安全管理制度' in body


def test_source_table_gives_long_prose_space_and_allows_long_rows_to_continue():
    text = '证据说明' * 120
    markdown = ('## 15. 信息来源\n| 证据编号与原始来源 | 支持章节 | 信息点 | 获取工具与信源等级 |\n'
                '| --- | --- | --- | --- |\n| E-123456789ABC | 第1章 | '+text+' | exa / C |\n')
    payload = markdown_to_docx_bytes(markdown, document_kind='industry_report')
    w = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    with ZipFile(io.BytesIO(payload)) as z:
        doc = ET.fromstring(z.read('word/document.xml'))
        styles = ET.fromstring(z.read('word/styles.xml'))
    table = doc.find('.//' + w + 'tbl')
    widths = [int(n.get(w+'w')) for n in table.find(w+'tblGrid')]
    assert sum(widths) == 9026 and widths[2] > 4*widths[1]
    rows = table.findall(w+'tr')
    assert rows[0].find('.//' + w+'tblHeader') is not None
    assert rows[1].find('.//' + w+'cantSplit') is None
    assert all(n.get(w+'val') == 'top' for n in rows[1].iter(w+'vAlign'))
    assert all(n.get(w+'val') == 'TableText' for n in rows[1].iter(w+'pStyle'))
    assert text in ''.join(n.text or '' for n in doc.iter(w+'t'))
    assert styles.find(".//"+w+"style[@"+w+"styleId='TableText']") is not None
