import json

from research_workflow import _plain_json


def test_fact_library_keeps_code_fences_inside_quoted_source_text():
    library = {'facts': [
        {'fact': '公司提供技术服务', 'evidence_quote': '示例：```python\nprint(1)\n```'},
        {'fact': '公司有公开业务资料', 'evidence_quote': '表格和中文资料'},
    ]}
    payload = json.dumps(library, ensure_ascii=False)
    assert _plain_json(payload) == library
    assert _plain_json('```json\n' + payload + '\n```') == library


def test_model_response_accepts_a_json_block_after_introductory_text():
    assert _plain_json('分析结果如下：\n```json\n{"score": 3}\n```') == {'score': 3}
    assert _plain_json('没有可解析的 JSON') is None
