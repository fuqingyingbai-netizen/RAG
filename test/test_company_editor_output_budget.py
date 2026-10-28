"""The optional company editor output cap leaves other model factories alone."""
from types import SimpleNamespace
import pytest
from research_workflow import ResearchWorkflow


@pytest.mark.parametrize('limit',[None,'32768'])
def test_only_explicit_company_editor_budget_is_forwarded(monkeypatch,limit):
    for key,value in {'ARK_API_KEY':'test-not-a-credential','MODEL':'qwen-test','BASE_URL':'https://example.invalid/v1'}.items():
        monkeypatch.setenv(key,value)
    if limit is None:monkeypatch.delenv('COMPANY_REPORT_EDITOR_MAX_COMPLETION_TOKENS',raising=False)
    else:monkeypatch.setenv('COMPANY_REPORT_EDITOR_MAX_COMPLETION_TOKENS',limit)
    seen=[]
    def factory(**settings):seen.append(settings);return SimpleNamespace()
    monkeypatch.setattr('research_workflow.init_chat_model',factory)
    w=ResearchWorkflow();w._get_company_report_editor_model();w._get_model();w._get_person_report_editor_model()
    assert seen[0].get('max_tokens')==(int(limit) if limit else None)
    assert all('max_tokens' not in row for row in seen[1:])
    assert all('reasoning_effort' not in row and 'extra_body' not in row for row in seen)
