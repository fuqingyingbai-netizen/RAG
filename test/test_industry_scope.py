from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from industry_research import normalize_scope, scope_fingerprint, source_in_current_run
from research_schemas import ResearchProjectCreate, ResearchRunRequest


def project():
    return SimpleNamespace(target_name='工业机器人', industry='工业机器人')


def test_explicit_scope_survives_resume_and_manufacturing_is_not_excluded():
    raw = {'industry_focus': '焊接机器人、协作机器人', 'region': '欧洲',
           'as_of_date': '2026-01-31', 'research_purpose': '战略研究', 'include_capital_markets': False}
    scope = normalize_scope(project(), {'target_name': '工业机器人', **raw}, raw)
    assert scope['segments'] == ['焊接机器人', '协作机器人']
    assert scope['geography'] == '欧洲'
    assert scope['capital_market'] == 'none'
    assert scope['excluded_segments'] == []
    resumed = normalize_scope(project(), {'target_name': '工业机器人'}, {'industry_scope': scope})
    for key in ('segments', 'as_of_date', 'geography', 'capital_market', 'purpose'):
        assert resumed[key] == scope[key]


@pytest.mark.parametrize('key,value', [('segments', ['协作机器人']), ('geography', '欧洲'),
    ('as_of_date', '2025-01-31'), ('purpose', '投资判断'), ('capital_market', 'summary'),
    ('named_companies', ['样本企业']), ('excluded_segments', ['军工'])])
def test_every_boundary_change_invalidates_fingerprint(key, value):
    intake = {'target_name': '机器人', 'industry_scope': {'geography': '中国大陆', 'as_of_date': '2026-01-31'}}
    changed = deepcopy(intake)
    changed['industry_scope'][key] = value
    assert scope_fingerprint(intake) != scope_fingerprint(changed)


def test_scope_fingerprint_ignores_list_order_and_assumption_wording():
    left = {'target_name': 'robotics', 'industry_scope': {'segments': ['a', 'b'], 'assumptions': ['old']}}
    right = {'target_name': 'robotics', 'industry_scope': {'segments': ['b', 'a'], 'assumptions': ['new']}}
    assert scope_fingerprint(left) == scope_fingerprint(right)


def test_source_versions_quarantine_old_runs_without_dropping_uploads():
    old = SimpleNamespace(source_type='news', source_metadata={'industry_scope_fingerprint': 'old'})
    current = SimpleNamespace(source_type='news', source_metadata={'industry_scope_fingerprint': 'current'})
    upload = SimpleNamespace(source_type='upload', source_metadata={})
    assert not source_in_current_run(old, 'current')
    assert source_in_current_run(current, 'current')
    assert source_in_current_run(upload, 'current')


@pytest.mark.parametrize('value', ['2026-02-30', '2026-1-1', '2026-10', 'tomorrow'])
def test_request_rejects_invalid_dates(value):
    with pytest.raises(ValidationError):
        ResearchRunRequest(target_type='industry', as_of_date=value)


def test_string_false_cannot_enable_capital_market():
    with pytest.raises(ValidationError):
        ResearchRunRequest(target_type='industry', include_capital_markets='false')
    assert ResearchRunRequest(include_capital_markets=False).include_capital_markets is False


def test_invalid_project_metadata_is_rejected_before_project_creation():
    with pytest.raises(ValidationError):
        ResearchProjectCreate(title='行业研究', target_type='industry', metadata={'as_of_date': '2026-02-30'})


def test_source_scope_does_not_change_when_second_stage_questions_change():
    first = {'target_name': '机器人', 'industry_scope': {'geography': '中国'}, 'focus_questions': ['市场规模']}
    second = {**first, 'focus_questions': ['基于访谈更新事实'], 'special_requirements': '二阶段'}
    assert scope_fingerprint(first, source_only=True) == scope_fingerprint(second, source_only=True)
    assert scope_fingerprint(first) != scope_fingerprint(second)


def test_default_assumptions_remain_visible_after_scope_is_saved():
    first = normalize_scope(project(), {'target_name': '工业机器人'}, {})
    resumed = normalize_scope(project(), {'target_name': '工业机器人', 'region': first['geography']},
                              {'industry_scope': first, 'as_of_date': first['as_of_date']})
    assert any('未指定地域' in note for note in resumed['assumptions'])
