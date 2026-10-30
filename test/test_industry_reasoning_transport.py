"""Reasoning gateways need enough total tokens and a completed streamed answer."""
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessageChunk

import industry_model_output as output


@pytest.mark.parametrize('value,expected', [('16384', 16384), ('0', None),
    ('invalid', 4000), ('-1', 4000), ('999999', 131072)])
def test_stage_completion_budget_is_configurable_and_bounded(monkeypatch, value, expected):
    monkeypatch.setenv('INDUSTRY_RISK_MAX_OUTPUT_TOKENS', value)
    assert output.stage_output_options('risk', 4000) == ({'max_tokens': expected} if expected else {})


def test_stream_aggregates_final_text_usage_and_finish_without_exposing_reasoning(monkeypatch):
    monkeypatch.setenv('INDUSTRY_MODEL_STREAMING_ENABLED', 'true')
    closed, options = [], []
    def stream(messages, **kwargs):
        options.append(kwargs)
        try:
            yield AIMessageChunk(content='', additional_kwargs={'reasoning_content': 'PRIVATE_REASONING'})
            yield AIMessageChunk(content='{"facts":')
            yield AIMessageChunk(content='[]}', response_metadata={'finish_reason': 'stop'},
                usage_metadata={'input_tokens': 10, 'output_tokens': 50, 'total_tokens': 60,
                                'output_token_details': {'reasoning': 40}})
        finally:
            closed.append(True)
    result = output.invoke_model(SimpleNamespace(stream=stream), [], timeout=15)
    text, diagnostic = output.response_text(result)
    assert text == '{"facts":[]}' and closed == [True]
    assert diagnostic['token_usage']['reasoning_tokens'] == 40
    assert options == [{'stream_usage': True, 'timeout': 15}]


@pytest.mark.parametrize('finish,code', [('', 'incomplete_model_stream'), ('length', 'truncated_model_output')])
def test_stream_never_accepts_partial_json_as_completed_output(monkeypatch, finish, code):
    monkeypatch.setenv('INDUSTRY_MODEL_STREAMING_ENABLED', 'true')
    chunk = AIMessageChunk(content='{"facts":[]}', response_metadata={'finish_reason': finish})
    with pytest.raises(output.IndustryModelOutputError, match=code):
        output.response_text(output.invoke_model(SimpleNamespace(stream=lambda *a, **k: iter([chunk])), []))


def test_stream_reasoning_counts_against_wall_budget_and_closes_connection(monkeypatch):
    monkeypatch.setenv('INDUSTRY_MODEL_STREAMING_ENABLED', 'true')
    clock, closed = [0.0], []
    monkeypatch.setattr(output.time, 'monotonic', lambda: clock[0])
    def stream(*args, **kwargs):
        try:
            yield AIMessageChunk(content='', additional_kwargs={'reasoning_content': 'thinking'})
            clock[0] = 2.0
            yield AIMessageChunk(content='{"facts":[]}', response_metadata={'finish_reason': 'stop'})
        finally:
            closed.append(True)
    with pytest.raises(TimeoutError, match='model_request_timeout'):
        output.invoke_model(SimpleNamespace(stream=stream), [], timeout=1)
    assert closed == [True]


@pytest.mark.parametrize('stage,repair,limit', [('cleaning', False, 8192), ('risk', False, 16384), ('risk', True, 8192)])
def test_cleaning_and_risk_use_tested_completion_budgets(monkeypatch, stage, repair, limit):
    import research_workflow
    monkeypatch.setenv('ARK_API_KEY', 'synthetic')
    monkeypatch.setenv('MODEL', 'qwen3.8-max')
    monkeypatch.setenv('INDUSTRY_MODEL_STREAMING_ENABLED', 'true')
    monkeypatch.setenv('INDUSTRY_' + ('RISK_REPAIR' if repair else stage.upper()) + '_MAX_OUTPUT_TOKENS', str(limit))
    settings = []
    def create(**kwargs):
        settings.append(kwargs)
        return SimpleNamespace(request_timeout=240, stream=lambda *a, **k: iter([
            AIMessageChunk(content='{}', response_metadata={'finish_reason': 'stop'})]))
    monkeypatch.setattr(research_workflow, 'init_chat_model', create)
    workflow = research_workflow.ResearchWorkflow.__new__(research_workflow.ResearchWorkflow)
    result = getattr(workflow, '_invoke_industry_' + stage)('role', 'prompt', **({'repair': repair} if stage == 'risk' else {}))
    assert result == '{}'
    assert settings[0]['max_tokens'] == limit and settings[0]['max_retries'] == 0


@pytest.mark.parametrize('role,setting', [('行业问题规划 Agent', 'PLANNER'), ('行业证据筛选 Agent - 1', 'SELECTOR'),
                                       ('行业报告质量编辑 - 1', 'SECTION')])
def test_structured_roles_allow_completion_budget_for_reasoning(monkeypatch, role, setting):
    import research_workflow
    monkeypatch.setenv('ARK_API_KEY', 'synthetic')
    monkeypatch.setenv('MODEL', 'qwen3.8-max')
    monkeypatch.setenv('INDUSTRY_' + setting + '_MAX_OUTPUT_TOKENS', '16384')
    settings = []
    monkeypatch.setattr(research_workflow, 'init_chat_model', lambda **kwargs:
        settings.append(kwargs) or SimpleNamespace(invoke=lambda *a, **k: SimpleNamespace(content='{}')))
    workflow = research_workflow.ResearchWorkflow.__new__(research_workflow.ResearchWorkflow)
    assert workflow._invoke_industry_report(role, 'prompt') == '{}'
    assert settings[0]['max_tokens'] == 16384
