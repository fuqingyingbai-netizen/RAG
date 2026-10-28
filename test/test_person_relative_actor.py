import pytest

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
