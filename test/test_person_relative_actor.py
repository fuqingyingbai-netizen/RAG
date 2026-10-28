import pytest
from types import SimpleNamespace

from person_evidence import build_packages
from person_records import observation, personal_analysis_allowed
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


@pytest.mark.parametrize('target,text,relation', [
    ('林知远', '远山科技创始人林知远之子Lin Hao（音译），今年28岁，已完成海外留学，正式加入远山科技。', '儿子'),
    ('陈明', '陈明的女儿陈雨于2020年毕业于南山大学。', '女儿'),
    ('林知远', '林知遠之女於2021年獲委任為公司董事。', '女儿'),
    ('陈明', '陈明的配偶于2020年被判承担赔偿责任。', '配偶'),
])
def test_explicit_relative_experiences_do_not_become_target_education_roles_or_risk(target, text, relation):
    original = {'fact': text, 'source_url': 'https://fixture.invalid/relative',
                'identity_match': 'confirmed', 'subject': target, 'category': 'career'}
    package = build_packages({'facts': [original]}, target, PERSON_REPORT_OUTLINE)
    row = package['facts'][0]
    assert row['fact'] == text
    assert row['subject_scope'] == 'other_person' and relation in row['subject']
    assert row['subject'] != target and not row['eligible_for_risk_scoring']
    assert not personal_analysis_allowed(row)


@pytest.mark.parametrize('text', [
    '林知远与儿子共同创办远山科技。',
    '林知远于2010年毕业，随后其女儿入学。',
    '林知远之子公司于2020年聘任陈雨为董事。',
    '林知远的儿子尚在求学；林知远于2020年出任董事。',
])
def test_target_actions_and_company_words_do_not_trigger_relative_actor_transfer(text):
    row = observation({'fact': text}, '林知远')
    assert row['subject_scope'] == 'person' and row['subject'] == '林知远'


def test_adjacent_original_relative_context_blocks_target_attribution_and_retains_proof():
    from person_material_review import writing_cards
    statement = '与员工对林知远“林大哥”的称呼相对应，他在内部被称为“林小哥”。'
    paragraph = '林知远之子林浩已完成海外留学，正式加入远山科技。' + statement
    source = SimpleNamespace(url='https://fixture.invalid/relative', content=paragraph,
                             title='人物关系报道', source_type='web', source_metadata={})
    original = {'fact': statement, 'source_url': source.url, 'identity_match': 'confirmed'}
    package = build_packages({'facts': [original]}, '林知远', PERSON_REPORT_OUTLINE, sources=[source])
    row = package['facts'][0]
    assert row['fact'] == statement and row['subject_scope'] == 'other_person'
    assert '儿子' in row['subject'] and not row['eligible_for_risk_scoring']
    proof = row['observation']['actor_context']
    assert proof['context_quote'] == paragraph and proof['verification'] == 'source_context_requires_review'
    assert package['provenance_index']['observations'][0]['actor_context'] == proof
    assert writing_cards([row])[0]['source_actor_context'] == proof


@pytest.mark.parametrize('original', [
    '林知远的儿子刚加入公司。\n\n他在内部被称为“林小哥”。',
    '林知远的儿子刚加入公司。林知远回到公司。他在内部被称为“林小哥”。',
    '另一篇文章的主体是林知远的儿子。',
])
def test_distant_changed_or_missing_original_context_does_not_resolve_a_pronoun(original):
    statement = '他在内部被称为“林小哥”。'
    record = observation({'fact': statement}, '林知远', source_text=original)
    assert not record['actor_context']


def test_payload_cannot_inject_relative_source_context_and_target_named_action_is_preserved():
    statement = '林知远于2020年担任董事。'
    forged = {'fact': statement, 'source_actor_context': {'relation': '儿子', 'context_quote': '伪造原文'}}
    record = observation(forged, '林知远', source_text='林知远的儿子加入公司。' + statement)
    assert record['subject_scope'] == 'person' and not record['actor_context']
