import json
from types import SimpleNamespace
from copy import deepcopy
import pytest
from industry_chapter_research import run_chapter_research, prepare_chapter_packages
from test_industry_chapter_batches import rich_package


def test_whole_library_reselection_does_not_require_search():
    payload = rich_package()
    packages = {2: json.dumps({**payload, 'facts': []})}
    p = SimpleNamespace()
    prepare_chapter_packages(payload, packages, p)
    assert json.loads(packages[2])['facts']
    assert p.industry_chapter_research_plan['chapters']['2']['reused_evidence_ids']
    assert not p.industry_chapter_research_plan['synthesis_started']


class Workflow:
    def __init__(self, fail=False):
        self.events = []
        self.fail = fail
    def generate_report(self, p, cleaned, risk, **kwargs):
        if p.industry_chapter_phase:
            self.events.append('chapter_analysis')
            p.industry_chapter_research_plan = {'chapters': {}, 'synthesis_started': False}
            p.industry_generated_sections = {2: 'chapter'}
            p.industry_section_packages = {2: '{}'}
            p.industry_statement_plans = {2: {'analysis_claims': []}}
            return 'chapters only'
        assert p.industry_recovery_plan['chapters'] == []
        assert p.industry_recovery_seed['industry_generated_sections'] == {2: 'repaired'}
        self.events.append('synthesis_and_summary')
        return 'complete report'
    def save_artifact(self, *args, **kwargs):
        return SimpleNamespace(content=args[4])
    def _recover_industry_conclusions(self, db, p, report, cleaned, risk, ca, ra, *args):
        assert p.industry_chapter_phase
        self.events.append('supplement_and_review')
        if self.fail:
            raise RuntimeError('search failure')
        p.industry_generated_sections = {2: 'repaired'}
        return report, 'new facts', 'new risk', ca, ra


def test_recovery_finishes_before_first_synthesis_and_returns_updated_dependencies():
    p = SimpleNamespace(title='test', industry_run_id='fresh')
    w = Workflow()
    result = run_chapter_research(w, SimpleNamespace(commit=lambda: None), p,
        'facts', 'risk', 'ca', 'ra', {}, {}, None, None, lambda stage: None)
    assert w.events == ['chapter_analysis', 'supplement_and_review', 'synthesis_and_summary']
    assert result == ('complete report', 'new facts', 'new risk', 'ca', 'ra')
    assert p.industry_chapter_research_done
    assert not p.industry_chapter_phase
    assert not hasattr(p, 'industry_recovery_seed')


def test_failed_chapter_phase_clears_execution_flag_and_never_synthesizes():
    p = SimpleNamespace(title='test')
    w = Workflow(fail=True)
    with pytest.raises(RuntimeError):
        run_chapter_research(w, SimpleNamespace(commit=lambda: None), p,
            'facts', 'risk', 'ca', 'ra', {}, {}, None, None, lambda stage: None)
    assert not p.industry_chapter_phase
    assert not p.industry_chapter_research_done
    assert 'synthesis_and_summary' not in w.events


def test_real_report_agent_stops_before_summary_and_synthesis(monkeypatch):
    from report_agents.industry_report_agent import IndustryReportAgent
    from industry_research import unknown_risk
    agent = IndustryReportAgent()
    payload = rich_package()
    payload['fact_contract_version'] = 'test'
    p = SimpleNamespace(title='test', target_name='行业', target_type='industry',
        industry='行业', description='', industry_scope={'capital_market': 'none'},
        industry_chapter_phase=True)
    calls = []
    def section(project, cleaned, risk, index, title, *args, **kwargs):
        calls.append(index)
        return f'## {index}. {title}\n章节分析'
    monkeypatch.setattr(agent, '_write_section', section)
    monkeypatch.setattr(agent, '_write_synthesis', lambda *a: pytest.fail('premature synthesis'))
    monkeypatch.setattr(agent, '_review_statement_claims', lambda *a: calls.append('review'))
    monkeypatch.setattr('industry_research_stages.plan_questions', lambda *a: ({}, {}))
    result = agent.generate(p, json.dumps(payload), json.dumps(unknown_risk()),
        lambda *a: pytest.fail('unexpected model'), lambda s,n:s[:n], lambda *a,**k:None)
    assert 1 not in calls and 14 not in calls
    assert calls[-1] == 'review'
    assert '## 1. 摘要' not in result
    assert '## 14.' not in result
    assert p.industry_generated_sections
    assert p.industry_chapter_research_plan['chapters']
