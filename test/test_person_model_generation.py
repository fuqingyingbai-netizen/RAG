import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from person_model_transport import EmptyPersonModelResponse,section_model_context,section_model_options
from research_workflow import ResearchWorkflow


def test_deepseek_section_uses_explicit_final_answer_mode_without_trimming_input(monkeypatch):
    monkeypatch.setenv('MODEL','qwen3.8-max')
    monkeypatch.setenv('PERSON_REPORT_SECTION_MODEL','deepseek-v4-pro')
    monkeypatch.setenv('ARK_API_KEY','test-person-model-key')
    monkeypatch.setenv('BASE_URL','https://fixture.invalid/v1')
    monkeypatch.delenv('PERSON_REPORT_SECTION_THINKING',raising=False)
    monkeypatch.delenv('PERSON_REPORT_SECTION_MAX_OUTPUT_TOKENS',raising=False)
    captured={};seen=[]
    model=SimpleNamespace(invoke=lambda messages:seen.append(messages) or SimpleNamespace(
        content='{"claims":[]}',usage_metadata={},response_metadata={'finish_reason':'stop'}))
    def init(**kwargs):captured.update(kwargs);return model
    monkeypatch.setattr('research_workflow.init_chat_model',init)
    workflow=ResearchWorkflow.__new__(ResearchWorkflow);workflow._person_report_section_model=None
    prompt='完整原始记录，不按来源条数删减。'*3000
    assert workflow._invoke_person_report_section('章节校验',prompt)=='{"claims":[]}'
    assert captured['model']=='deepseek-v4-pro' and section_model_context()['model']=='deepseek-v4-pro'
    assert captured['extra_body']=={'thinking':{'type':'disabled'}} and captured['max_tokens']==8192
    assert seen[0][-1]['content']==prompt


def test_empty_final_content_is_failure_and_records_the_finish_reason():
    workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    workflow._person_report_section_model=SimpleNamespace(invoke=lambda messages:SimpleNamespace(
        content='',usage_metadata={'input_tokens':10000,'output_tokens':8192,'total_tokens':18192},
        response_metadata={'finish_reason':'length'}))
    events=[]
    with pytest.raises(EmptyPersonModelResponse,match='empty_model_final_content:length'):
        workflow._invoke_person_report_section('完整材料补写','原文未被删减',events.append)
    assert not any(e.get('status')=='done' for e in events)
    assert any(e.get('finish_reason')=='length' and e.get('output_tokens')==8192 for e in events)


def test_generation_settings_change_invalidates_same_model_raw_response_cache(monkeypatch,tmp_path):
    spec=importlib.util.spec_from_file_location('person_iteration_model_options',Path(__file__).resolve().parents[1]/'scripts/person_iteration.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.delenv('PERSON_REPORT_SECTION_MODEL',raising=False)
    monkeypatch.setenv('MODEL','deepseek-v4-pro');monkeypatch.setenv('BASE_URL','https://fixture.invalid/v1')
    monkeypatch.setenv('PERSON_REPORT_SECTION_THINKING','disabled')
    monkeypatch.setenv('PERSON_REPORT_SECTION_MAX_OUTPUT_TOKENS','8192')
    first=tmp_path/'first';second=tmp_path/'second';first.mkdir();second.mkdir();calls=[]
    def invoke(*args):calls.append(args);return '{"claims":[]}'
    module.ChapterInvoker(invoke,first,model_context=section_model_context())('writer','same complete sources')
    monkeypatch.setenv('PERSON_REPORT_SECTION_THINKING','enabled')
    monkeypatch.setenv('PERSON_REPORT_SECTION_REASONING_EFFORT','low')
    new=module.ChapterInvoker(invoke,second,reuse=first,model_context=section_model_context())
    new('writer','same complete sources')
    assert len(calls)==2 and all(e['status']!='exact_input_reused' for e in new.events)


def test_vendor_specific_thinking_parameter_is_not_sent_to_other_models(monkeypatch):
    monkeypatch.setenv('PERSON_REPORT_SECTION_THINKING','disabled')
    options=section_model_options('qwen3.8-max')
    assert options['max_tokens']==8192 and 'extra_body' not in options and 'reasoning_effort' not in options


@pytest.mark.parametrize('value',['bad','0','999999'])
def test_invalid_output_budget_is_not_silently_treated_as_an_input_record_limit(monkeypatch,value):
    monkeypatch.setenv('PERSON_REPORT_SECTION_MAX_OUTPUT_TOKENS',value)
    with pytest.raises(ValueError,match='invalid_person_section_output_token_budget'):
        section_model_options('deepseek-v4-pro')
