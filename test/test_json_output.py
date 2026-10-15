import json

import pytest

from json_utils import parse_json_output


@pytest.mark.parametrize('value', [
    {'facts': [{'fact': '```python\nprint(1)\n```'}]},
    {'facts': [{'fact': '```json\n{"nested": true}\n```'}, {'fact': 'second'}]},
    {'facts': [{'fact': 'quote " and newline\n'}]},
    [], 0, False,
])
def test_internal_code_and_scalar_json_are_preserved(value):
    text = json.dumps(value, ensure_ascii=False)
    assert parse_json_output(text) == value
    assert parse_json_output(f'```json\n{text}\n```') == value


@pytest.mark.parametrize('text', ['', 'broken', 'prefix ```json\n{"facts": []}\n```',
                                    '{"facts": [}'])
def test_invalid_outputs_are_not_silently_extracted(text):
    assert parse_json_output(text) is None
