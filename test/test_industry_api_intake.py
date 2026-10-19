from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import research_api
from research_schemas import ResearchRunRequest


def test_industry_request_respects_disabled_search_and_bounded_rounds():
    intake = research_api._locked_run_intake(ResearchRunRequest(
        target_type='industry', ai_search_enabled=False, max_search_rounds=1))
    assert intake['ai_search_enabled'] is False
    assert intake['max_search_rounds'] == 1
    assert 'industry_focus' not in intake


def test_industry_run_can_inherit_project_type_without_enabling_search():
    intake = research_api._locked_run_intake(ResearchRunRequest(ai_search_enabled=False), target_type='industry')
    assert intake['target_type'] == 'industry' and intake['ai_search_enabled'] is False


def test_save_and_resume_preserve_scope_and_allow_clearing_companies(monkeypatch):
    saved = {'industry_focus': '协作机器人', 'focus_modules': ['技术路线对比'], 'focus_entities': '甲公司',
             'include_capital_markets': False, 'as_of_date': '2026-01-31', 'region': '欧洲',
             'special_requirements': '重点研究成本', 'target_type': 'industry'}
    artifact = SimpleNamespace(artifact_type='project_intake', artifact_metadata=saved, content='')
    project = SimpleNamespace(id=1, title='测试项目', target_name='机器人行业', target_type='industry',
                              industry='机器人行业', description='', artifacts=[artifact])
    database = Mock()
    database.query.return_value.filter.return_value.first.return_value = artifact
    monkeypatch.setattr(research_api.research_store, 'put_text', lambda *args, **kwargs: 'test-key')
    requested = {'target_type': 'industry', 'focus_entities': ''}
    research_api._save_project_intake(database, project, requested)
    assert requested['focus_modules'] == ['技术路线对比']
    assert requested['industry_scope']['segments'] == ['协作机器人']
    assert requested['industry_scope']['named_companies'] == []
    assert requested['as_of_date'] == '2026-01-31'
    assert artifact.artifact_metadata['region'] == '欧洲'
    assert artifact.artifact_metadata['special_requirements'] == '重点研究成本'
    assert database.commit.called


def test_saved_scope_date_is_validated():
    with pytest.raises(ValueError):
        ResearchRunRequest(target_type='industry', industry_scope={'as_of_date': '2026-02-30'})
