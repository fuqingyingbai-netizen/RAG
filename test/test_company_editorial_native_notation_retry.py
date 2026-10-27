import json

import pytest

from report_agents.company_editorial import build_editorial_package
from test_company_editorial import record, audit, OUTLINE


@pytest.mark.parametrize('native,invented', [
    ('公司披露：1、不得从事竞争业务；2、公司拥有商业机会优先权。',
     '公司披露第1项不得从事竞争业务，第2项公司拥有商业机会优先权。'),
    ('公司披露次数栏原值为0，相关情况栏为不适用。',
     '公司披露次数为0次，相关情况栏为不适用。'),
])
def test_retry_corrects_added_units_without_weakening_native_quantity_guards(native, invented):
    row = record(text=native)
    writes = []
    def invoke(role, prompt, trace):
        if role == '公司交付正文独立审稿':
            data = json.loads(prompt.split('资料：\n', 1)[1])
            return json.dumps(audit([row], data['findings']))
        writes.append(prompt)
        text = invented if len(writes) == 1 else native
        return json.dumps({'findings': [{'finding_id': 'p1', 'text': text,
                                         'information_ids': ['I-a']}]})
    result = build_editorial_package({'records': [row]}, OUTLINE, '青禾食品公司', invoke, workers=1)
    assert len(writes) == 2
    assert any('new_or_changed_number_unit' in e for e in result['batches'][0]['attempts'][0]['errors'])
    assert result['diagnostic']['pending_information_ids'] == []
    assert result['findings'][0]['text'] == native
