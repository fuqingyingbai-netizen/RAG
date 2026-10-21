from types import SimpleNamespace

from person_colleague_material import explicit_colleague_roles
from person_material_tables import role_literals, team_table
from person_evidence import build_packages
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


INTAKE = {'target_name': '林知远', 'person_anchor': {'known_affiliations': ['恒川软件'], 'aliases': ['林知远']}}


def source(text):
    return SimpleNamespace(url='https://fixture.invalid/article', title='原始报道', content=text,
        source_metadata={'identity_confidence': 'high', 'fetch_status': 'done'})


def test_explicit_company_role_and_name_are_retained_as_colleague_context():
    original = '恒川软件首席运营官陈雨安在公开采访中介绍经营安排，林知远参与此次会议，原文未说明当前任职期限。'
    records = explicit_colleague_roles([source(original)], INTAKE)
    assert [r['team_member_name'] for r in records] == ['陈雨安']
    assert records[0]['fact'] == original
    assert records[0]['team_role_literal'] == '恒川软件首席运营官陈雨安'
    contract = build_packages({'facts': []}, '林知远', PERSON_REPORT_OUTLINE, INTAKE, [source(original)])
    record = contract['chapters'][6]['research_facts'][0]
    assert record['subject_scope'] == 'other_person' and not record['analysis_allowed']
    assert not any(f.get('team_member_name') for f in contract['chapters'][9]['research_facts'])


def test_replacement_object_is_not_the_new_office_holder():
    text = '恒川软件发表公告，林知远接替陈雨安出任公司CEO，即日生效，本文没有披露陈雨安的新职位。'
    assert not explicit_colleague_roles([source(text)], INTAKE)


def test_partner_executive_is_not_a_member_of_target_company():
    text = '林知远与恒川软件合作伙伴远山科技CEO陈雨安在会场会谈，双方介绍不同公司的战略，不涉及恒川软件任职。'
    assert not explicit_colleague_roles([source(text)], INTAKE)


def test_plural_previous_ceos_have_distinct_ids_even_with_same_quote():
    text = '林知远介绍，恒川软件前两任CEO陈雨安与李清均来自一线岗位，具体任期在本段没有披露，不认定二人仍然在任。'
    contract = build_packages({'facts': []}, '林知远', PERSON_REPORT_OUTLINE, INTAKE, [source(text)])
    records = contract['chapters'][6]['research_facts']
    assert {f['team_member_name'] for f in records} == {'陈雨安', '李清'}
    assert len({f['evidence_id'] for f in records}) == 2
    assert all(f['fact'] == text for f in records)


def test_pdf_role_wrap_does_not_truncate_title_or_adopt_prohibition():
    fact = {'fact': '陈雨安女士，现任本公司高级副\n总裁、技术委员会主任。不存在不得担任董事、高级管理人员的情形。'}
    roles = role_literals(fact)
    assert roles == ['现任本公司高级副总裁']


def test_colleague_joining_event_is_not_current_role_start_date():
    fact = {'fact': '陈雨安于1996年加入恒川软件，现任本公司副总裁。', 'subject_scope': 'other_person',
        'team_member_name': '陈雨安', 'team_affiliation_name': '恒川软件', 'evidence_id': 'E-PTEAM',
        'observation': {'source_events': [{'kind': 'appointment', 'date_literal': '1996年', 'source_quote': '1996年加入恒川软件'}]}}
    rendered = '\n'.join(team_table({'facts': [fact], 'research_facts': [fact]}))
    assert '原文事件日期（非现职任期）' in rendered and '1996年加入恒川软件' in rendered
