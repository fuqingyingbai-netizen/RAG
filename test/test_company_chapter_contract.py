"""Exercise the chapter contract at API, planner, collector and writer boundaries."""
import json
import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from company_chapters import (VERSION, chapters, chapter, outline, public_config,
                              prompt_contract, selected_chapters)
from company_requirements import chapter_queries, build_requirements, selected_platform_tools
from research_workflow import ResearchWorkflow
from report_agents.company_chapter_agent import create_chapter_agents
from report_agents.company_report_agent import CompanyReportAgent


def project():
    return SimpleNamespace(id=1, title='示例制造研究', target_name='示例制造股份有限公司',
        industry='制造业', target_type='company', description='', sources=[], artifacts=[])


def intake(selected=('company.ch02', 'company.ch09')):
    return dict(target_type='company', target_name='示例制造股份有限公司',
                company_template_version=VERSION, focus_modules=list(selected), industry='制造业')


def test_ui_has_exactly_one_option_per_body_chapter_and_fourteen_unique_agents():
    config=public_config()
    assert [c['chapter'] for c in config['chapters']]==list(range(1,13))
    assert [c['title'] for c in config['chapters']]==[t for t,_ in outline()[:12]]
    assert config['defaults']==[chapter(n)['id'] for n in range(2,12)]
    assert {c['chapter'] for c in config['chapters'] if not c['selectable']}=={1,12}
    assert len({c['id'] for c in chapters()})==len({c['agent_id'] for c in chapters()})==14
    config['chapters'][0]['title']='mutation'
    assert public_config()['chapters'][0]['title']=='摘要'


def test_template_examples_are_chapter_local_and_mismatched_example_is_quarantined():
    assert chapter(11)['source_cells']['description']==['B23','B24']
    for n in (2,3,9):
        assert chapter(n)['few_shot']['text'] in prompt_contract(n)
    assert chapter(7)['few_shot']['status']=='quarantined'
    assert chapter(7)['few_shot']['text']
    for n in range(1,15):
        prompt=prompt_contract(n,'本次示例企业')
        assert chapter(7)['few_shot']['text'] not in prompt
        assert '{target}' not in prompt
        assert '模板表达示例不是目标公司的证据' in prompt
        for other in (2,3,9):
            if n!=other:assert chapter(other)['few_shot']['text'] not in prompt


def test_api_rejects_stale_unknown_options_and_normalizes_all_company_requests():
    from research_api import _locked_run_intake, company_chapter_config
    from research_schemas import ResearchRunRequest
    assert company_chapter_config()==public_config()
    saved=_locked_run_intake(ResearchRunRequest(**intake()))
    assert saved['company_template_version']==VERSION
    assert saved['focus_modules']==intake()['focus_modules']
    for values,status in [(dict(company_template_version='stale'),409),
                          (dict(focus_modules=['company.ch02','不存在的章节']),422)]:
        with pytest.raises(HTTPException) as exc:
            _locked_run_intake(ResearchRunRequest(**{**intake(),**values}))
        assert exc.value.status_code==status
    old=_locked_run_intake(ResearchRunRequest(target_type='company',focus_modules=['收入情况']))
    assert old['focus_modules']==['company.ch06'] and old['company_template_version']==VERSION


@pytest.mark.parametrize('selected',[[],['company.ch02'],['company.ch05','company.ch09']])
def test_normalization_plan_and_queries_keep_only_selected_chapter_ownership(selected):
    workflow=ResearchWorkflow();p=project();config=intake(selected)
    normalized=workflow._normalize_intake(p,config,[],[])
    assert normalized['focus_modules']==selected
    assert normalized['company_template_version']==VERSION
    plan=workflow.plan_research(p,normalized)
    assert len(plan['chapter_research_tasks'])==14
    assert [m['name'] for m in plan['modules']]==selected
    assert [r['chapters'] for r in plan['company_requirements']]==[[chapter(s)['chapter']] for s in selected]
    assert {t['chapter_id'] for t in plan['chapter_research_tasks'] if t['focus']}==set(selected)
    rows=workflow._expand_search_queries(plan,normalized)
    assert {r['module'] for r in rows}==set(selected)
    for r in rows:
        assert r['company_chapter_id']==r['module']
        assert r['company_requirement_ids']
        assert r['company_chapter']==chapter(r['module'])['chapter']
    if selected:
        assert {r['search_tier'] for r in rows}=={'authority_first','open_web'}
    gaps=[s+'：缺少原件' for s in selected]+['company.ch08：缺少原件']
    assert {r['module'] for r in workflow._gap_queries(plan,normalized,gaps)}<=set(selected)
    if 'company.ch09' in selected:
        req=next(r for r in plan['company_requirements'] if r['chapter']==9)
        assert 'wenshu.court.gov.cn' in req['authority_domains']


def test_discovery_and_platform_routes_do_not_reenable_unselected_chapters():
    config=intake(['company.ch09']);requirements=build_requirements(config['focus_modules'],config)
    rows=chapter_queries([{'module':'诉讼/制裁','query':'司法缺口'},
        {'module':'融资情报','query':'不应启动'}, {'module':'用户指定','query':'明确委托'}], requirements)
    assert [r['module'] for r in rows]==['company.ch09','用户指定']
    assert selected_platform_tools(config,'qcc')=={'get_company_risk_scan','get_administrative_penalty'}
    assert selected_platform_tools(config,'tyc')==set()
    assert 'get_recruitment_info' in selected_platform_tools(intake(['company.ch08']),'qcc')
    assert selected_platform_tools(intake([]),'xiniu')==set()
    assert selected_platform_tools({'target_type':'person','focus_modules':['company.ch09']},'qcc') is None


def test_actual_platform_collectors_respect_selected_tools(monkeypatch):
    workflow=ResearchWorkflow();p=project();config=intake(['company.ch07'])
    p.company_research_requirements=build_requirements(config['focus_modules'],config)
    for key in ('QCC_API_KEY','TYC_API_KEY','XINIU_API_KEY'):monkeypatch.setenv(key,'test-only')
    monkeypatch.setattr(workflow,'_mcp_initialize',lambda *a,**kw:(None,True,''))
    calls=[]
    def call(url,headers,tool,args,**kw):
        calls.append((tool,dict(args)))
        return {'content':[{'type':'text','text':'示例制造股份有限公司 张某 董事'}]},None
    monkeypatch.setattr(workflow,'_mcp_call_tool',call)
    monkeypatch.setattr(workflow,'_save_structured_source',lambda *a,**kw:True)
    monkeypatch.setattr(workflow,'_extract_tyc_company_anchor',lambda text,target:{'company_name':target})
    for name in ('_collect_qcc_sources','_collect_tyc_sources','_collect_xiniu_sources'):
        getattr(workflow,name)(None,p,p.target_name,config)
    assert {t for t,a in calls}=={'get_key_personnel','search_companies','get_company_people','get_company_info'}
    assert [a['aspect'] for t,a in calls if t=='get_company_info']==['团队人物及招聘分析']
    calls.clear()
    for name in ('_collect_qcc_sources','_collect_tyc_sources','_collect_xiniu_sources'):
        assert getattr(workflow,name)(None,p,p.target_name,intake([]))==0
    assert not calls


def test_agents_enforce_ownership_and_actual_model_prompt_binding():
    p=project();events=[]
    agents=create_chapter_agents(p,lambda *a,**kw:events.append((a,kw)))
    calls=[]
    agents[6].invoke(lambda *a:calls.append(a) or 'ok','正文编写','仅本章材料')
    role,prompt,_=calls[0]
    assert role.endswith('company_chapter_06_agent')
    assert chapter(6)['description'] in prompt
    assert chapter(7)['few_shot']['text'] not in prompt
    assert '示例制造股份有限公司' in prompt
    assert agents[6].metadata()['model_calls']==1
    with pytest.raises(ValueError):agents[6].execute(lambda:'## 7. 越章写作')
    assert agents[6].execute(lambda:'## 6. 本章\n资料').startswith('## 6.')


def test_generate_runs_all_fourteen_chapter_agents_with_exact_template_headings(monkeypatch):
    p=project();p.company_research_intake=intake([]);events=[]
    monkeypatch.setenv('COMPANY_REPORT_EDITOR_ENABLED','false')
    agent=CompanyReportAgent()
    original_outline=list(agent.outline)
    report=agent.generate(p,'{"facts":[]}','{}',lambda *a:'',
        lambda text,n:text[:n],lambda *a,**kw:events.append((a,kw)))
    headings=re.findall(r'(?m)^## (\d+)\. ([^\n]+)',report)
    assert headings==[(str(n),c['title']) for n,c in enumerate(chapters(),1)]
    assert len(p.company_chapter_agents_metadata)==14
    finalized={kw['chapter'] for a,kw in events if kw.get('phase')=='finalize' and kw.get('status')=='done'}
    assert finalized==set(range(1,15))
    assert p.company_template_version==VERSION
    assert agent.outline==original_outline
    assert ResearchWorkflow()._select_report_outline(p)==outline()


def test_delivery_followup_keeps_template_heading():
    from report_agents.company_delivery_contract import followup_chapter,delivery_requirements
    assert followup_chapter(project(),outline()).startswith('## 14. 后续研究点\n')
    assert delivery_requirements(intake(['company.ch09']))['required_chapters']==[2,6,9]
    assert delivery_requirements(intake([]))['required_chapters']==[2,6]
