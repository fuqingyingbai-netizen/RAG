import re
from pathlib import Path
from types import SimpleNamespace

from person_identity import build_anchor
from person_material_review import writing_input_for
from person_provenance import build_provenance_index
from person_requirements import bind_query_requirements, query_rows, requirements
from research_strategies.person import PersonResearchStrategy


def intake(company='甲软件', name='陈明'):
    result = {'target_type': 'person', 'target_name': name, 'company_name': company,
              'affiliation': company, 'focus_modules': ['司法负面与诉讼核查', '教育与履历']}
    result['person_anchor'] = build_anchor(result)
    return result


def test_every_actual_frontend_option_has_a_question_tool_evidence_and_chapter_route():
    text = (Path(__file__).resolve().parents[1] / 'frontend/script.js').read_text(encoding='utf-8')
    options = re.search(r"person: \[(.*?)\]\.map", text, re.S)[1]
    labels = re.findall(r"'([^']+)'", options)
    assert len(labels) >= 11
    rows = requirements({**intake(), 'focus_modules': labels})
    assert {label for row in rows for label in row['selected_labels']} == set(labels)
    assert all(row['chapters'] and row['tool_capabilities'] and row['expected_evidence'] for row in rows)
    assert all(row['state'] == 'planned_not_verified' for row in rows)


def test_same_name_different_organization_queries_keep_target_and_clue_separate():
    first, other = query_rows(intake()), query_rows(intake(company='乙制造'))
    assert all('"陈明"' in r['query'] and '"甲软件"' in r['query'] for r in first)
    assert all('"乙制造"' in r['query'] for r in other)
    assert all(r['identity_context']['target_person'] == '陈明' for r in first + other)
    assert all('甲软件' not in r['query'] for r in other)
    assert first[0]['requirement_ids'] == other[0]['requirement_ids']


def test_normalized_person_query_rows_preserve_lineage_to_existing_production_source_fields():
    rows = PersonResearchStrategy().expand_search_queries({'modules': []}, intake())
    selected = [r for r in rows if r.get('retrieval_reason') == 'frontend_requirement_question']
    assert {r['requirement_ids'][0] for r in selected} == {'R-P-BIOGRAPHY', 'R-P-JUDICIAL'}
    source = SimpleNamespace(url='https://issuer.invalid/original', content='原文',
        source_metadata={'person_requirement_ids': selected[0]['requirement_ids']})
    ledger = build_provenance_index('陈明', intake(), [source], [], [], {})
    assert ledger['documents'][0]['requirement_ids'] == selected[0]['requirement_ids']


def test_commission_id_is_preserved_when_a_frontend_requirement_is_also_applicable():
    rows = bind_query_requirements([{'module': '司法负面与诉讼核查', 'person_chapters': [12],
                                   'requirement_ids': ['C-EXISTING']}], intake())
    assert rows[0]['requirement_ids'] == ['C-EXISTING', 'R-P-JUDICIAL']


def test_unknown_option_is_explicitly_pending_and_company_industry_do_not_get_person_rules():
    row = requirements({**intake(), 'focus_modules': ['未来新增勾选项']})[0]
    assert row['state'] == 'mapping_requires_review' and row['chapters'] == []
    assert requirements({**intake(), 'target_type': 'company'}) == []
    assert requirements({**intake(), 'target_type': 'industry'}) == []


def test_research_writer_receives_actual_selected_question_and_expected_evidence():
    req = requirements(intake())[0]
    packet = writing_input_for({'chapter': 2, 'title': '履历', 'user_requirements': [req]}, [])
    assert packet['user_requirements'][0] == {k:req[k] for k in ('requirement_id','question','expected_evidence')}
    assert not packet['facts']
