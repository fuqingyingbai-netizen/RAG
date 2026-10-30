"""Editorial roles must inherit request deadlines and structured responses."""
import time
from types import SimpleNamespace

import pytest

from industry_model_output import IndustryModelOutputError, request_deadline


@pytest.mark.parametrize('role', ['行业报告质量编辑 - 风险核查 - 1', '行业报告局部修订写作者 - 风险核查 - 1'])
def test_editorial_transport_uses_remaining_deadline_and_json_mode(monkeypatch, role):
    import research_workflow
    monkeypatch.setenv('ARK_API_KEY', 'synthetic-editorial-test')
    monkeypatch.setenv('MODEL', 'synthetic-model')
    configured, invoked = [], []

    def create(**options):
        configured.append(options)

        def invoke(messages, **kwargs):
            invoked.append(kwargs)
            return SimpleNamespace(content='{"reviews":[]}', response_metadata={'finish_reason': 'stop'})

        return SimpleNamespace(invoke=invoke)

    monkeypatch.setattr(research_workflow, 'init_chat_model', create)
    workflow = research_workflow.ResearchWorkflow.__new__(research_workflow.ResearchWorkflow)
    with request_deadline(time.monotonic() + 15):
        assert workflow._invoke_industry_report(role, 'Synthetic editorial request') == '{"reviews":[]}'
    assert 0 < invoked[0]['timeout'] <= 15
    assert configured[0]['model_kwargs']['response_format'] == {'type': 'json_object'}
    assert configured[0]['max_retries'] == 0


@pytest.mark.parametrize('role', ['行业报告质量编辑 - 风险核查 - 1', '行业报告局部修订写作者 - 风险核查 - 1'])
def test_editorial_transport_does_not_invoke_after_deadline(monkeypatch, role):
    import research_workflow
    monkeypatch.setenv('ARK_API_KEY', 'synthetic-editorial-test')
    monkeypatch.setenv('MODEL', 'synthetic-model')
    monkeypatch.setattr(research_workflow, 'init_chat_model', lambda **kwargs: SimpleNamespace(
        invoke=lambda *args, **kwargs: pytest.fail('Expired editorial work must not invoke a model')))
    workflow = research_workflow.ResearchWorkflow.__new__(research_workflow.ResearchWorkflow)
    with request_deadline(time.monotonic() - 1):
        with pytest.raises(IndustryModelOutputError, match='chapter_generation_budget_exhausted'):
            workflow._invoke_industry_report(role, 'Expired synthetic editorial request')
