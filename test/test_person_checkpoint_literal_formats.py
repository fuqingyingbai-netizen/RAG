import pytest
from person_replay_state import checkpoint_literal_plan


def test_material_and_coverage_requests_bind_the_same_literal_state():
    material={'source_display_quotes':[{'shown_evidence_id':'E-PFORMATONE','quote':'真实逐字原文。'}]}
    coverage={'tables':[{'table_index':0,'text':'普通资料表行','evidence_ids':['E-POTHER']},
        {'table_index':1,'representation':'literal_source_excerpt','text':'真实逐字原文。','evidence_ids':['E-PFORMATONE']}]}
    assert checkpoint_literal_plan(material)==checkpoint_literal_plan(coverage)==[{'evidence_id':'E-PFORMATONE','quote':'真实逐字原文。'}]


def test_conflicting_literal_contexts_cannot_be_cherry_picked():
    packet={'source_display_quotes':[{'shown_evidence_id':'E-PFORMATONE','quote':'第一段'}],
        'tables':[{'representation':'literal_source_excerpt','text':'另一段','evidence_ids':['E-PFORMATONE']}]}
    with pytest.raises(ValueError,match='checkpoint_literal_context_conflict'):checkpoint_literal_plan(packet)


def test_a_normal_table_with_multiple_sources_cannot_masquerade_as_one_literal():
    with pytest.raises(ValueError,match='checkpoint_literal_context_invalid'):
        checkpoint_literal_plan({'tables':[{'representation':'literal_source_excerpt','text':'混合表格内容',
            'evidence_ids':['E-PFORMATONE','E-PFORMATTWO']}]})
