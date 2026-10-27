"""Native heading labels are optional prose; business values stay mandatory."""
from copy import deepcopy
import re

import pytest

from report_agents.company_editorial import numeric_tokens, semantic_source_text
from test_company_editorial import record


def test_flattened_industry_heading_pair_masks_only_its_labels():
    text = ('4）海外市场 公司收入为17.7亿元。 2、行业的基本特点 行业规模4万家，利润增长7.6%。 '
            '3、主要技术门槛 仍有2项条件和0项已确认成果。')
    row = record(text=text); before = deepcopy(row)
    projected = semantic_source_text(row)
    assert len(projected) == len(text) and row == before
    assert '2、' not in projected and '3、' not in projected
    assert {'17.7亿元', '4万', '7.6%', '2项', '0项'} <= numeric_tokens(projected)
    assert '行业的基本特点' in projected and '主要技术门槛' in projected


def test_bullet_hierarchy_includes_a_final_single_subheading():
    text = ('一、经营分析 1. 业绩修复 ◦ 收入351.4百万元，增长6.0%。 '
            '2. 风险与挑战 ◦ 海外收入占比7%，目标15%尚未实现。 '
            '二、后续建议 1. 短期核验 ◦ 原文没有执行结果，0项成果已确认。')
    row = record(text=text); before = deepcopy(row)
    projected = semantic_source_text(row)
    assert len(projected) == len(text) and row == before
    assert not re.search(r'(?<!\S)[12]\.[ \t]', projected)
    assert {'351.4百万元', '6.0%', '7%', '15%', '0项'} <= numeric_tokens(projected)
    assert '目标15%尚未实现' in projected and '原文没有执行结果' in projected


@pytest.mark.parametrize('text', [
    '2、行业的基本特点 公司收入为2元。',
    '2、行业的基本特点 公司收入为2元。 4、主要技术门槛 仍有3项条件。',
    '1. 经营结果 ◦ 收入为1元。 2. 核验范围 ◦ 尚未核验。',
    '一、经营分析 1. 经营结果 ◦ 收入为1元。',
    '一、经营分析 1. 经营结果 ◦ 收入为1元。 3. 核验范围 ◦ 尚未核验。',
    '一、经营分析 1. 万元 ◦ 原值。 2. 人民币 ◦ 原币种。',
    '一、经营分析 1.5 经营结果 ◦ 原值。 2.5 核验范围 ◦ 原值。',
    '2、行业的基本特点 收入为2元。\n\n3、主要技术门槛 仍有3项条件。',
])
def test_incomplete_or_quantity_like_patterns_remain_native(text):
    # Prefixing keeps this about inline recognition, independently of the
    # existing separate rule for labels at a physical line start.
    text = '原文正文 ' + text.replace('\n\n', '\n\n原文正文 ')
    assert semantic_source_text(record(text=text)) == text


@pytest.mark.parametrize('field', ['登记编号', '经营范围'])
def test_explicit_fields_never_become_heading_only(field):
    text = '2、行业的基本特点 公司收入2元。 3、主要技术门槛 有3项条件。'
    assert semantic_source_text(record(text=text, field=field)) == text


HEADER = '发起人名称 认购股份数\n（股） 持股比例（%） 出资方式 出资时间\n'


def test_actual_legal_table_continuation_folio_remains_in_original():
    text = '--- PDF page 6 ---\n4\n' + HEADER + 'Kong) Limited 30 日\n合计 360,000,000 100.00 - -'
    row = record(text=text); row['provenance'][0]['source_title'] = '某公司章程'
    before = deepcopy(row); projected = semantic_source_text(row)
    assert row == before and len(projected) == len(text)
    assert '4' not in numeric_tokens(projected)
    assert {'30', '360000000', '100.00'} <= numeric_tokens(projected)
    assert HEADER in projected


@pytest.mark.parametrize('text,title,field', [
    ('4\n' + HEADER + '合计 360,000,000', '公司章程', None),
    ('--- PDF page 6 ---\n7\n' + HEADER, '公司章程', None),
    ('--- PDF page 6 ---\n4\n' + HEADER, '经营数据', None),
    ('--- PDF page 6 ---\n0\n' + HEADER, '公司章程', None),
    ('--- PDF page 6 ---\n4\n发起人名称 认购股份数\n4万元', '公司章程', None),
    ('--- PDF page 6 ---\n' + HEADER + '4\n合计 360,000,000', '公司章程', None),
    ('--- PDF page 6 ---\n4\n' + HEADER, '公司章程', '认购股份数'),
])
def test_unbound_or_actual_values_are_not_legal_table_folios(text, title, field):
    row = record(text=text, **({'field': field} if field else {}))
    row['provenance'][0]['source_title'] = title
    projected = semantic_source_text(row)
    expected = '7' if '\n7\n' in text else '0' if '\n0\n' in text else '4'
    assert any(t == expected or t.startswith(expected + '万') for t in numeric_tokens(projected))
