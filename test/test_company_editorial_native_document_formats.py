"""Native document notation, source ownership and full quantity gates."""
from copy import deepcopy
import pytest
from report_agents.company_editorial import (
    parse_proposal, semantic_source_text, numeric_tokens, validate_audit,
)
from test_company_editorial import record, audit, OUTLINE


def parse(row, text):
    return parse_proposal({'findings': [{'finding_id': 'p', 'text': text,
        'information_ids': [row['information_id']]}]}, [row], 6, OUTLINE[5][1][0])


@pytest.mark.parametrize('name', ['青禾食品', '远帆物流', '华舟软件'])
@pytest.mark.parametrize('verb', ['刊载', '转载', '发布', '收录', '转引', '提供', '披露'])
def test_publisher_reference_preserves_only_the_own_document_identity(name, verb):
    row = record(text='公司联系地址为文沙路16号，邮政编码528000。')
    row['provenance'][0]['source_title'] = '公开平台-' + name + '股份有限公司 第六届监事会第三次会议决议公告'
    before = deepcopy(row)
    text = '公开平台' + verb + '的公司第六届监事会第三次会议决议公告载明，公司联系地址为文沙路16号，邮政编码528000。'
    assert not parse(row, text)[1]
    assert row == before


@pytest.mark.parametrize('text', [
    '公开平台刊载的公司第六届监事会第四次会议决议公告载明，公司完成产品交付。',
    '公开平台刊载的公司第六届监事会第三次会议决议公告载明，公司交付6个产品。',
    '公司于2022年完成产品交付。',
    '公开平台刊载的公司2022年年度报告载明，公司2022年完成产品交付。',
])
def test_reference_does_not_license_unknown_titles_periods_or_business_counts(text):
    row = record(text='公司完成产品交付。')
    row['provenance'][0]['source_title'] = '公司第六届监事会第三次会议决议公告；公司2022年年度报告'
    assert parse(row, text)[1]


def test_uncited_source_title_cannot_supply_document_numbers():
    row = record(text='公司完成产品交付。')
    assert parse(row, '公开平台刊载的公司第六届监事会第三次会议决议公告载明，公司完成产品交付。')[1]


NATIVE = '股东说明 1、甲公司持有0股；2、乙公司持有25%股权；3、公司未知其他股东是否存在一致行动关系。'
PROSE = '甲公司持有0股；乙公司持有25%股权；公司未知其他股东是否存在一致行动关系。'


def test_inline_labels_do_not_demand_business_numbers_and_originals_stay_exact():
    row = record(text=NATIVE); before = deepcopy(row)
    findings, errors = parse(row, PROSE)
    assert not errors
    review = audit([row], findings)
    assert not validate_audit([row], findings, review)
    assert numeric_tokens(semantic_source_text(row)) == {'0股', '25%'}
    assert row == before
    assert len(semantic_source_text(row)) == len(row['text'])


@pytest.mark.parametrize('text', [
    PROSE.replace('0股', '1股'),
    PROSE.replace('25%', '24%'),
    PROSE.replace('25%', '25'),
])
def test_inline_layout_projection_cannot_hide_lost_or_changed_real_quantities(text):
    row = record(text=NATIVE)
    findings = [{'finding_id': 'p', 'text': text, 'information_ids': [row['information_id']]}]
    assert validate_audit([row], findings, audit([row], findings))


@pytest.mark.parametrize('text', [
    '股东说明 1、甲公司持有0股。',
    '股东说明 1、甲公司持有0股；3、乙公司持有25%股权。',
    '股东说明 1、甲公司持有0股；3、乙公司持有25%股权；2、公司披露关系。',
    '金额原值 1、万元；2、人民币。',
    '股东说明 1、甲公司持有0股；\n\n2、乙公司持有25%股权。',
    '股东说明 1、甲公司持有0股。\n2、乙公司持有25%股权。',
])
def test_unpaired_skipped_quantity_leading_or_multiline_guesses_keep_first_number(text):
    row = record(text=text)
    assert '1' in numeric_tokens(semantic_source_text(row))


def test_explicit_field_numbers_and_unknowns_remain_whole():
    row = record(text=NATIVE, field='股东关系原字段')
    assert semantic_source_text(row) == NATIVE
    assert {'1', '2', '3', '0股', '25%'} <= numeric_tokens(semantic_source_text(row))


def test_omitting_zero_or_changing_share_units_is_still_rejected():
    row = record(text=NATIVE)
    assert parse(row, PROSE.replace('0股', '0元'))[1]
    text = PROSE.replace('甲公司持有0股；', '')
    findings = [{'finding_id': 'p', 'text': text, 'information_ids': [row['information_id']]}]
    assert 'lost_numeric_information:I-a' in validate_audit([row], findings, audit([row], findings))


def test_explicit_semicolon_sequence_survives_physical_pdf_line_wrapping():
    row = record(text='股东说明 1、甲公司持有\n0股；2、\n乙公司持有25%股权；\n3、公司未知其他股东是否存在一致行动关系。')
    before = deepcopy(row)
    findings, errors = parse(row, PROSE)
    assert not errors
    assert not validate_audit([row], findings, audit([row], findings))
    assert numeric_tokens(semantic_source_text(row)) == {'0股', '25%'}
    assert row == before


@pytest.mark.parametrize('label', [
    '<公司法>', '<青禾食品未来三年（2025-2027年）股东回报规划>',
    '<华舟软件2024年-2028年员工持股计划（草案）>',
    '<2026年限制性股票激励计划（草案）>',
    '< 2025 年限制性股票激励计划实施考核管理办法>',
])
def test_exact_native_chinese_angle_titles_are_plain_prose_and_survive_word_export(label):
    from docx_exporter import markdown_to_docx_bytes
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile
    from io import BytesIO
    row = record(text='公司拟审议《关于' + label + '的议案》，尚未通过。')
    before = deepcopy(row)
    text = row['text']
    findings, errors = parse(row, text)
    assert not errors and not validate_audit([row], findings, audit([row], findings))
    blob = markdown_to_docx_bytes('## 7. 团队\n\n' + text, title='原文书名核对')
    with ZipFile(BytesIO(blob)) as archive:
        doc = ET.fromstring(archive.read('word/document.xml'))
    assert text in ''.join(t.text or '' for t in doc.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
    assert row == before


@pytest.mark.parametrize('markup', [
    '<b>', '</b>', '<script>', '<a href="https://issuer.test">',
    '<公司法 src=external>', '<!--注释-->', '<!DOCTYPE html>', '<?xml version="1.0"?>',
])
def test_actual_markup_still_fails_even_when_literal_in_the_source(markup):
    row = record(text='公司原文载' + markup + '，尚未完成审议。')
    assert any('model_written_structure_or_citation' in e for e in parse(row, row['text'])[1])


@pytest.mark.parametrize('support_location', ['none', 'context', 'provenance', 'uncited_row'])
def test_unbound_angle_title_is_not_licensed_by_metadata_or_another_source(support_location):
    row = record(text='公司完成产品交付。')
    if support_location == 'context': row['context']['context_quote'] = '<公司法>'
    if support_location == 'provenance': row['provenance'][0]['source_title'] = '<公司法>'
    text = '公司根据<公司法>完成产品交付。'
    if support_location == 'uncited_row':
        other = record('I-other', text='原文载<公司法>。')
        answer = {'findings': [
            {'finding_id': 'p', 'text': text, 'information_ids': [row['information_id']]},
            {'finding_id': 'q', 'text': other['text'], 'information_ids': [other['information_id']]},
        ]}
        errors = parse_proposal(answer, [row, other], 6, OUTLINE[5][1][0])[1]
    else:
        errors = parse(row, text)[1]
    assert any('model_written_structure_or_citation' in e for e in errors)


def test_native_angle_title_keeps_year_checks_active():
    row = record(text='公司拟审议《关于<公司2024年-2028年员工持股计划（草案）>的议案》，尚未通过。')
    assert parse(row, row['text'].replace('2028', '2029'))[1]
    findings = [{'finding_id': 'p', 'text': '公司拟审议相关员工持股计划，尚未通过。', 'information_ids': [row['information_id']]}]
    assert validate_audit([row], findings, audit([row], findings))


@pytest.mark.parametrize('native,model', [
    ('< 2026 年限制性股票\n激励计划（草案） >', '<2026年限制性股票激励计划（草案）>'),
    ('<青禾 食品公司章程>', '<青禾食品公司章程>'),
    ('<公司\u20092024年持股计划>', '<公司2024年持股计划>'),
])
def test_own_source_title_layout_whitespace_can_fold_without_changing_glyphs(native,model):
    row = record(text='原文记载《关于' + native + '的议案》，尚未通过。')
    before = deepcopy(row)
    text = '原文记载《关于' + model + '的议案》，尚未通过。'
    findings, errors = parse(row, text)
    assert not errors
    assert not validate_audit([row], findings, audit([row], findings))
    assert row == before


@pytest.mark.parametrize('label', [
    '<2025年限制性股票激励计划（草案）>',
    '<2024年限制性股票激励计划(草案)>',
    '<2024年激励限制性股票计划（草案）>',
    '<2024>', '<script>', '<2024 onclick=external公司法>',
])
def test_layout_matching_cannot_change_years_punctuation_order_or_license_markup(label):
    row = record(text='公司披露《关于<2024年限制性股票激励计划（草案）>的议案》，2025年另行披露业务事项。')
    text = '公司披露《关于' + label + '的议案》，2025年另行披露业务事项。'
    assert any('model_written_structure_or_citation' in e for e in parse(row, text)[1])


def test_angle_title_layout_matching_does_not_normalize_semantic_audit_spans():
    row = record(text='公司拟审议《关于<公司 2024年持股计划>的议案》，尚未通过。')
    findings, errors = parse(row, row['text'].replace('公司 2024', '公司2024'))
    assert not errors
    review = audit([row], findings)
    assert not validate_audit([row], findings, review)
    review['information'][0]['spans'][0]['source_excerpt'] = row['text'].replace('公司 2024', '公司2024')
    assert 'unbound_semantic_span:I-a' in validate_audit([row], findings, review)
