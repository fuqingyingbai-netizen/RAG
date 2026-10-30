"""Company analysis/summary budgets are explicit and preserve other routes."""
from types import SimpleNamespace

import pytest

from research_workflow import ResearchWorkflow
from test_company_editor_transport import workflow_with_transport


def configure_analysis(monkeypatch):
    monkeypatch.setenv('COMPANY_ANALYSIS_MAX_COMPLETION_TOKENS','65536')
    monkeypatch.setenv('COMPANY_ANALYSIS_REASONING_EFFORT','low')
    monkeypatch.delenv('COMPANY_ANALYSIS_THINKING_BUDGET',raising=False)


def test_actual_sdk_analysis_wire_has_own_budget_and_preserves_generic_factory(monkeypatch):
    configure_analysis(monkeypatch)
    workflow,requests,client=workflow_with_transport(monkeypatch)
    workflow._model=None
    try:
        assert workflow._invoke('公司全量原文分析 Agent','完整原文',company_analysis=True)=='{"status":"通过"}'
        assert requests[0]['max_completion_tokens']==65536
        assert requests[0]['reasoning_effort']=='low' and requests[0]['stream'] is True
        assert workflow._invoke('普通任务','其他链路',stream=True)=='{"status":"通过"}'
        assert 'max_completion_tokens' not in requests[1] and 'reasoning_effort' not in requests[1]
        assert workflow._get_company_report_editor_model(profile='analysis') is not workflow._get_model()
        assert workflow._get_company_report_editor_model(profile='analysis') is not workflow._get_company_report_editor_model()
    finally:client.close()


@pytest.mark.parametrize('finish,broken',[(None,False),('length',False),('stop',True)])
def test_analysis_cannot_admit_nonterminal_or_broken_valid_json(monkeypatch,finish,broken):
    configure_analysis(monkeypatch)
    workflow,requests,client=workflow_with_transport(monkeypatch,finish=finish,broken=broken)
    try:assert workflow._invoke('公司材料独立复核','完整原文',company_analysis=True)==''
    finally:client.close()


@pytest.mark.parametrize('configured',[False,True])
def test_report_company_analysis_is_opt_in_after_target_routing(monkeypatch,configured):
    if configured:configure_analysis(monkeypatch)
    else:
        for suffix in ['MAX_COMPLETION_TOKENS','REASONING_EFFORT','THINKING_BUDGET']:
            monkeypatch.delenv('COMPANY_ANALYSIS_'+suffix,raising=False)
    workflow=ResearchWorkflow();calls=[]
    def generate(project,cleaned,risk,*,invoke,**kwargs):
        invoke('公司全量原文分析 Agent','原文')
        return '仅验证实际调度，不是验收报告。'
    workflow._report_agents['company']=SimpleNamespace(generate=generate)
    monkeypatch.setattr(workflow,'_invoke',lambda role,*a,**kw:calls.append(kw) or '{}')
    project=SimpleNamespace(id=0,target_name='青禾公司',target_type='company',industry='',sources=[],artifacts=[])
    workflow.generate_report(project,'{}','{}',intake={'target_type':'company'})
    assert calls[0].get('company_analysis',False) is configured


@pytest.mark.parametrize('target_type,configured',[('company',False),('company',True),('person',True)])
def test_real_cleaning_dispatch_only_company_can_opt_in(monkeypatch,target_type,configured):
    if configured:configure_analysis(monkeypatch)
    else:
        for suffix in ['MAX_COMPLETION_TOKENS','REASONING_EFFORT','THINKING_BUDGET']:
            monkeypatch.delenv('COMPANY_ANALYSIS_'+suffix,raising=False)
    workflow=ResearchWorkflow();calls=[]
    monkeypatch.setattr(workflow,'_cleaning_brief',lambda *a:'按原文核验')
    monkeypatch.setattr(workflow,'_invoke',lambda role,*a,**kw:calls.append((role,kw)) or '{"facts":[]}')
    result=workflow._clean_batches_with_llm(SimpleNamespace(target_type=target_type),{}, {},['完整材料'])
    assert result['facts']==[] and len(calls)==1
    assert calls[0][1].get('company_analysis',False) is (target_type=='company' and configured)


@pytest.mark.parametrize('finish,expected',[('stop','{"status":"通过"}'),('length',''),(None,'')])
def test_summary_optional_budget_reaches_sdk_and_requires_stop_without_sdk_retry(monkeypatch,finish,expected):
    workflow,requests,client=workflow_with_transport(monkeypatch,streaming=False,finish=finish)
    monkeypatch.setenv('COMPANY_SUMMARY_MAX_COMPLETION_TOKENS','32768')
    monkeypatch.setenv('COMPANY_SUMMARY_REASONING_EFFORT','low')
    try:
        assert workflow._invoke_company_summary('公司摘要 Agent','完整事实卡')==expected
        assert len(requests)==1 and requests[0]['max_completion_tokens']==32768
        assert requests[0]['reasoning_effort']=='low'
    finally:client.close()


def test_summary_unconfigured_keeps_existing_2400_budget(monkeypatch):
    workflow,requests,client=workflow_with_transport(monkeypatch,streaming=False)
    for suffix in ['MAX_COMPLETION_TOKENS','REASONING_EFFORT']:
        monkeypatch.delenv('COMPANY_SUMMARY_'+suffix,raising=False)
    try:
        assert workflow._invoke_company_summary('公司摘要 Agent','事实卡')=='{"status":"通过"}'
        assert requests[0]['max_completion_tokens']==2400 and 'reasoning_effort' not in requests[0]
    finally:client.close()
