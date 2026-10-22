"""Keep budget selection deterministic while bounding repeated eligibility work."""
from collections import Counter
from copy import deepcopy
import json

import industry_evidence
import industry_research
from industry_risk_input import risk_input


def test_budget_trials_classify_each_fact_dimension_once_and_never_cache_across_calls(monkeypatch):
    names=['政策与监管风险','市场增长与需求风险']
    monkeypatch.setattr(industry_research,'active_risk_dimensions',lambda scope:names)
    calls=Counter()
    def eligible(fact,name):
        calls[fact['evidence_id'],name]+=1
        return fact.get('eligible',True)
    monkeypatch.setattr(industry_research,'risk_fact_applicable',eligible)
    monkeypatch.setattr(industry_research,'risk_fact_text',lambda f:f['fact'])
    monkeypatch.setattr(industry_evidence,'fact_requirement_ids',lambda *a:[])
    facts=[{'evidence_id':f'E-{i:012X}','module':'政策与监管',
        'fact':('合成行业适用条件与核验规则。'*40)+str(i),'source_url':f'https://source-{i}.example/notice'} for i in range(45)]
    original=deepcopy(facts)
    packet=risk_input(facts,{'capital_market':'none'},limit=4000)
    assert facts==original
    assert len(json.dumps(packet,ensure_ascii=False))<=4000
    assert 0<len(packet['facts'])<len(facts)
    assert len(calls)==len(facts)*len(names) and max(calls.values())==1
    retained={row['evidence_id'] for row in packet['facts']}
    assert all(set(ids)==retained for ids in packet['dimension_evidence_ids'].values())
    for fact in facts:fact['eligible']=False
    calls.clear()
    second=risk_input(facts,{'capital_market':'none'},limit=4000)
    assert not second['facts'] and max(calls.values())==1
    assert all(row['selection_status']=='no_applicable_evidence' for row in second['input_selection'].values())


def test_duplicate_evidence_ids_keep_the_last_fact_and_competition_filter_stays_independent_of_enabled_dimensions(monkeypatch):
    name='数据口径与证据可靠性风险'
    monkeypatch.setattr(industry_research,'active_risk_dimensions',lambda scope:[name])
    monkeypatch.setattr(industry_research,'risk_fact_applicable',lambda fact,dimension:fact.get('allowed',True))
    monkeypatch.setattr(industry_research,'risk_fact_text',lambda fact:fact['fact'])
    monkeypatch.setattr(industry_evidence,'fact_requirement_ids',lambda *a:[])
    facts=[{'evidence_id':'E-1','fact':'old'},
           {'evidence_id':'E-1','fact':'new','allowed':True,'module':'竞争格局与代表企业'},
           {'evidence_id':'E-2','fact':'sample','allowed':False,'module':'竞争格局与代表企业'}]
    packet=risk_input(facts,{})
    assert [row['fact'] for row in packet['facts']]==['new']
    assert packet['dimension_evidence_ids'][name]==['E-1']
