import pytest
import random

from company_citations import CitationFormatter


@pytest.mark.parametrize('text,expected', [
    ('丙公司未披露净利润[3]，不做推算。', '丙公司未披露净利润[id_3]，不做推算。'),
    ('来源：[3]。\n甲公司的价格[1]，乙公司的价格[2]。', '来源：[id_3]。\n甲公司的价格[id_1]，乙公司的价格[id_2]。'),
    ('价格39元/月[id_1]。', '价格39元/月[id_1]。'),
    ('数值为[3]。编号 [1]，第[2]项。', '数值为[3]。编号 [1]，第[2]项。'),
    ('数组[3]，array[1]，示例：[2]。', '数组[3]，array[1]，示例：[2]。'),
    ('矩阵[1][3]。\n| 数值 | 内容 |\n| --- | --- |\n| 客户数 | [3] |', '矩阵[1][3]。\n| 数值 | 内容 |\n| --- | --- |\n| 客户数 | [3] |'),
    ('`claim[3]`，依据[3]。', '`claim[3]`，依据[id_3]。'),
    ('``claim ` [3]``，依据[3]。', '``claim ` [3]``，依据[id_3]。'),
    ('`跨行\n净利润[3]`，依据[3]。', '`跨行\n净利润[3]`，依据[id_3]。'),
    ('```python\n净利润[3]\n```\n依据[3]。', '```python\n净利润[3]\n```\n依据[id_3]。'),
    ('~~~\n净利润[3]\n~~~\n依据[3]。', '~~~\n净利润[3]\n~~~\n依据[id_3]。'),
    ('$$\n矩阵[3]\n$$\n依据[3]。', '$$\n矩阵[3]\n$$\n依据[id_3]。'),
    (r'公式 $x[3]$，公式 \(矩阵[3]\)，依据[3]。', r'公式 $x[3]$，公式 \(矩阵[3]\)，依据[id_3]。'),
    ('[3](https://example.com) ![3](x.png) [3][ref]\n[3]: /source', '[3](https://example.com) ![3](x.png) [3][ref]\n[3]: /source'),
    ('转义\\[3]，引用“[3]”，列表 [1,2,3]，3元。', '转义\\[3]，引用“[3]”，列表 [1,2,3]，3元。'),
])
@pytest.mark.parametrize('chunk_size', [1, 5, 10000])
def test_source_markers_are_normalized_across_chunks_without_rewriting_literals(text, expected, chunk_size):
    formatter = CitationFormatter(['1', '2', '3'])
    output = ''.join(formatter.feed(text[index:index+chunk_size]) for index in range(0, len(text), chunk_size))
    output += formatter.feed('', final=True)
    assert output == expected
    assert not formatter.unknown


def test_numeric_unknown_source_is_not_given_an_existing_document_mapping():
    formatter = CitationFormatter(['1'])
    assert formatter.feed('结论[999]。', final=True) == '结论[999]。'
    assert formatter.unknown == {'999'} and not formatter.changed


def test_lines_remain_streamed_before_completion():
    formatter = CitationFormatter(['3'])
    assert formatter.feed('第一段依据[3]。\n第二段') == '第一段依据[id_3]。\n第二段'
    assert formatter.feed('', final=True) == ''


def test_prose_is_visible_before_a_newline_and_split_marker_is_held():
    formatter = CitationFormatter(['3'])
    assert formatter.feed('批准预算为317万元') == '批准预算为317万元'
    assert formatter.feed('[3') == ''
    assert formatter.feed(']') == ''
    assert formatter.feed('。后续内容') == ''
    assert formatter.feed('', final=True) == '[id_3]。后续内容'


def test_chunk_boundaries_preserve_markdown_even_when_model_syntax_is_incomplete():
    rng = random.Random(112)
    parts = ['结论', '来源：', '[3]', '[999]', '[id_3]', '[a]', '(url)', '[ref]', '\n', '\r',
             '`', '``', '```', '~~~', '$', '$$', r'\(', r'\)', r'\[', '    ', '!', '，', '。', 'a', ' ']
    for _ in range(500):
        text = ''.join(rng.choices(parts, k=rng.randrange(2, 30)))
        whole = CitationFormatter(['3'])
        expected = whole.feed(text, final=True)
        for size in (1, 2, 3, 7, 19):
            chunked = CitationFormatter(['3'])
            actual = ''.join(chunked.feed(text[i:i+size]) for i in range(0, len(text), size))
            actual += chunked.feed('', final=True)
            assert actual == expected and chunked.unknown == whole.unknown
