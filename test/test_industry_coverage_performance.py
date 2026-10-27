"""Coverage classification scales by facts, without mixing requirement identities."""
from copy import deepcopy
import industry_grounding
import industry_evidence as evidence


def requirement(identity,module):
    return {'id':identity,'module':module,'question':'合成指标条件','kind':'qualitative',
            'accepted_scopes':['industry_level'],'metric_pattern':'合成'}


def fact(identity,module,**extra):
    return {'evidence_id':identity,'module':module,'scope_match':'in_scope','evidence_scope':'industry_level',
            'fact':'合成行业事实','provenance':{'locator':{'status':'verified'}},**extra}


def test_coverage_does_not_reclassify_each_source_for_every_requirement(monkeypatch):
    calls=[]
    monkeypatch.setattr(industry_grounding,'sample_boundary',lambda f:calls.append(f['evidence_id']) or '')
    monkeypatch.setattr(evidence,'_metric_present',lambda *a:True)
    facts=[fact(f'E-{i}','module') for i in range(60)]
    requirements=[requirement(f'R-{i}','module') for i in range(35)]
    original=deepcopy(facts)
    result=evidence.fact_coverage(facts,requirements)
    assert len(calls)<=len(facts)*2
    assert facts==original
    assert all(row['status']=='verified' and row['verified_evidence_ids']==[f['evidence_id'] for f in facts] for row in result['requirements'])


def test_coverage_keeps_duplicate_ids_order_samples_candidate_status_and_module_boundaries(monkeypatch):
    monkeypatch.setattr(industry_grounding,'sample_boundary',lambda f:f.get('sample',''))
    monkeypatch.setattr(evidence,'_metric_present',lambda *a:True)
    facts=[fact('E-A','A'),fact('E-A','A'),fact('E-B','B',claim_type='source_excerpt'),
           fact('E-SAMPLE','A',sample='representative sample'),fact('E-OUT','A',scope_match='out_of_scope')]
    requirements=[requirement('duplicate','A'),requirement('duplicate','B'),requirement('missing','C')]
    result=evidence.fact_coverage(facts,requirements)
    a,b,missing=result['requirements']
    assert a['candidate_evidence_ids']==['E-A','E-A'] and a['verified_evidence_ids']==['E-A','E-A']
    assert b['candidate_evidence_ids']==['E-B'] and b['verified_evidence_ids']==[] and b['status']=='candidate'
    assert missing['status']=='missing' and missing['candidate_evidence_ids']==[]
    assert evidence.fact_requirement_ids(facts[0],requirements)==['duplicate']
    assert evidence.fact_requirement_ids(facts[2],requirements,True)==[]
