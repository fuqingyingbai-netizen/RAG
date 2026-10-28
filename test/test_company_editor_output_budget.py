"""The optional company editor output cap leaves other model factories alone."""
from types import SimpleNamespace
import pytest
from research_workflow import ResearchWorkflow


@pytest.mark.parametrize('limit,effort',[(None,None),('32768',None),('32768','medium')])
def test_only_explicit_company_editor_budget_is_forwarded(monkeypatch,limit,effort):
    for key,value in {'ARK_API_KEY':'test-not-a-credential','MODEL':'qwen-test','BASE_URL':'https://example.invalid/v1'}.items():
        monkeypatch.setenv(key,value)
    if limit is None:monkeypatch.delenv('COMPANY_REPORT_EDITOR_MAX_COMPLETION_TOKENS',raising=False)
    else:monkeypatch.setenv('COMPANY_REPORT_EDITOR_MAX_COMPLETION_TOKENS',limit)
    if effort is None:monkeypatch.delenv('COMPANY_REPORT_EDITOR_REASONING_EFFORT',raising=False)
    else:monkeypatch.setenv('COMPANY_REPORT_EDITOR_REASONING_EFFORT',effort)
    seen=[]
    def factory(**settings):seen.append(settings);return SimpleNamespace()
    monkeypatch.setattr('research_workflow.init_chat_model',factory)
    w=ResearchWorkflow();w._get_company_report_editor_model();w._get_model();w._get_person_report_editor_model()
    assert seen[0].get('max_tokens')==(int(limit) if limit else None)
    assert seen[0].get('reasoning_effort')==effort
    assert all('max_tokens' not in row and 'reasoning_effort' not in row for row in seen[1:])
    assert all('extra_body' not in row for row in seen)


def test_focus_profile_has_its_own_cached_budget_and_leaves_other_factories_alone(monkeypatch):
    for key,value in {'ARK_API_KEY':'test-not-a-credential','MODEL':'qwen-test',
            'BASE_URL':'https://example.invalid/v1','COMPANY_REPORT_EDITOR_MAX_COMPLETION_TOKENS':'16384',
            'COMPANY_REPORT_EDITOR_REASONING_EFFORT':'medium','COMPANY_MAIN_FOCUS_MAX_COMPLETION_TOKENS':'32768',
            'COMPANY_MAIN_FOCUS_REASONING_EFFORT':'low'}.items():monkeypatch.setenv(key,value)
    seen=[]
    def factory(**settings):
        model=SimpleNamespace(settings=settings);seen.append(model);return model
    monkeypatch.setattr('research_workflow.init_chat_model',factory)
    w=ResearchWorkflow();editor=w._get_company_report_editor_model()
    focus=w._get_company_report_editor_model(profile='main_focus')
    assert w._get_company_report_editor_model() is editor
    assert w._get_company_report_editor_model(profile='main_focus') is focus
    assert editor.settings['max_tokens']==16384 and editor.settings['reasoning_effort']=='medium'
    assert focus.settings['max_tokens']==32768 and focus.settings['reasoning_effort']=='low'
    w._get_model();w._get_person_report_editor_model()
    assert all('max_tokens' not in row.settings and 'reasoning_effort' not in row.settings for row in seen[2:])


@pytest.mark.parametrize('finish_reason',['length',None,'content_filter'])
def test_focus_role_rejects_incomplete_responses_even_if_the_body_is_valid_json(monkeypatch,finish_reason):
    class Model:
        def invoke(self,messages):return SimpleNamespace(content='{"records":[]}',response_metadata={'finish_reason':finish_reason})
    requested=[];w=ResearchWorkflow()
    def factory(**kwargs):requested.append(kwargs);return Model()
    monkeypatch.setattr(w,'_get_company_report_editor_model',factory)
    assert w._invoke_company_report_editor('公司主报告事实选择独立审稿','完整原文')==''
    assert requested==[{'profile':'main_focus'}]


@pytest.mark.parametrize('configured',[False,True])
def test_report_workflow_routes_only_explicit_focus_roles_to_the_focus_profile(monkeypatch,configured):
    if configured:monkeypatch.setenv('COMPANY_MAIN_FOCUS_REASONING_EFFORT','low')
    else:monkeypatch.delenv('COMPANY_MAIN_FOCUS_REASONING_EFFORT',raising=False)
    monkeypatch.delenv('COMPANY_MAIN_FOCUS_MAX_COMPLETION_TOKENS',raising=False)
    calls=[];w=ResearchWorkflow()
    roles=['公司主报告事实选择','公司主报告事实选择独立审稿','公司监管原件提取']
    def generate(project,cleaned,risk,*,invoke,**kwargs):
        for role in roles:invoke(role,'原文完整传递')
        return '仅用于路由校验，不是验收报告。'
    w._report_agents['company']=SimpleNamespace(generate=generate)
    monkeypatch.setattr(w,'_invoke',lambda role,*a,**kw:calls.append(('normal',role)) or '{}')
    monkeypatch.setattr(w,'_invoke_company_report_editor',lambda role,*a,**kw:calls.append(('scoped',role)) or '{}')
    project=SimpleNamespace(id=0,target_name='青禾公司',target_type='company',industry='',sources=[],artifacts=[])
    w.generate_report(project,'{}','{}',intake={'target_type':'company'})
    assert calls==[(('scoped' if configured else 'normal'),role) for role in roles[:2]]+[('normal',roles[2])]
