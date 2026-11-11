import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('conversation_check',
    Path(__file__).resolve().parents[1] / 'scripts/manual/check_company_conversation.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


@pytest.mark.parametrize('answer,expected', [
    ('丙公司2025年净利润：本轮资料中未找到依据，资料仅注明“未披露净利润”[id_3]，不做推算。', True),
    ('丙公司未披露净利润，不进行推算。', True),
    ('未披露净利润，但估算为120万元[id_3]。', False),
    ('丙公司净利润为120万元[id_3]。', False),
    ('丙公司未披露净利润[3]，不进行推算。', False),
])
def test_refusal_distinguishes_citation_ids_invented_values_and_invalid_citations(answer, expected):
    assert bool(check.grounded_refusal(answer)) == expected
