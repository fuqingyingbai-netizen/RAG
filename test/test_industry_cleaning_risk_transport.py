"""Empty and truncated model responses must remain failures, with safe usage evidence."""
import json
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('stage', ['cleaning', 'risk'])
@pytest.mark.parametrize('content,finish,code', [
    ('', 'stop', 'empty_model_output'),
    ('{"facts":[]}', 'length', 'truncated_model_output'),
    ([{'type': 'reasoning', 'reasoning': 'PRIVATE_REASONING'}], 'stop', 'empty_model_output'),
])
def test_invalid_visible_output_is_never_reported_as_success(monkeypatch, stage, content, finish, code):
    import research_workflow
    monkeypatch.setenv('ARK_API_KEY', 'synthetic')
    monkeypatch.setenv('MODEL', 'qwen3.8-max')
    message = SimpleNamespace(content=content, response_metadata={'finish_reason': finish},
        usage_metadata={'input_tokens': 100, 'output_tokens': 2000,
                        'output_token_details': {'reasoning': 2000, 'private': 'PRIVATE_USAGE'}})
    calls = []
    def invoke(messages):
        calls.append(messages)
        return message
    monkeypatch.setattr(research_workflow, 'init_chat_model', lambda **kwargs: SimpleNamespace(invoke=invoke))
    workflow = research_workflow.ResearchWorkflow.__new__(research_workflow.ResearchWorkflow)
    events = []
    result = getattr(workflow, '_invoke_industry_' + stage)('synthetic role', 'PRIVATE_PROMPT', emit=events.append)
    assert result == '' and len(calls) == 1
    assert not any(event.get('status') == 'done' for event in events)
    failure = events[-1]
    assert failure['status'] == 'fallback' and failure['failure_code'] == code
    assert failure['output_diagnostic']['token_usage']['reasoning_tokens'] == 2000
    assert 'PRIVATE' not in json.dumps(events)


@pytest.mark.parametrize('stage', ['cleaning', 'risk'])
def test_visible_text_blocks_are_read_without_serializing_reasoning(monkeypatch, stage):
    import research_workflow
    monkeypatch.setenv('ARK_API_KEY', 'synthetic')
    monkeypatch.setenv('MODEL', 'qwen3.8-max')
    message = SimpleNamespace(content=[{'type': 'reasoning', 'reasoning': 'PRIVATE_REASONING'},
        {'type': 'text', 'text': '{"facts":[]}'}], response_metadata={'finish_reason': 'stop'},
        usage_metadata={'input_tokens': 10, 'output_tokens': 20})
    monkeypatch.setattr(research_workflow, 'init_chat_model', lambda **kwargs:
        SimpleNamespace(invoke=lambda messages: message))
    workflow = research_workflow.ResearchWorkflow.__new__(research_workflow.ResearchWorkflow)
    events = []
    assert getattr(workflow, '_invoke_industry_' + stage)('role', 'prompt', emit=events.append) == '{"facts":[]}'
    assert events[-1]['status'] == 'done'
    assert events[-1]['output_diagnostic']['output_chars'] == 12
    assert 'PRIVATE' not in json.dumps(events)


@pytest.mark.parametrize('stage', ['cleaning', 'risk'])
def test_timeout_diagnostics_do_not_log_raw_provider_errors(monkeypatch, stage):
    import research_workflow
    monkeypatch.setenv('ARK_API_KEY', 'synthetic')
    monkeypatch.setenv('MODEL', 'qwen3.8-max')
    def invoke(messages):
        raise TimeoutError('PRIVATE_PROVIDER_KEY_AND_RESPONSE')
    monkeypatch.setattr(research_workflow, 'init_chat_model', lambda **kwargs: SimpleNamespace(invoke=invoke))
    workflow = research_workflow.ResearchWorkflow.__new__(research_workflow.ResearchWorkflow)
    events = []
    assert getattr(workflow, '_invoke_industry_' + stage)('role', 'prompt', emit=events.append) == ''
    assert events[-1]['failure_code'] == 'model_request_timeout'
    assert 'PRIVATE' not in json.dumps(events)
