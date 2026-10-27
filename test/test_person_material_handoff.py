"""Offline orchestration regressions; no live model verdicts are supplied."""
import json
import pytest
from person_content_acceptance import accept_content
from person_evidence import validate_model_claims


@pytest.mark.parametrize('changed_task,stable_literal_mode',[(False,True),(True,True),(False,False)])
def test_literal_only_followup_reuses_unchanged_decisions_but_changed_task_rechecks_all(changed_task,stable_literal_mode):
    base={'subject':'陈安','subject_scope':'person','analysis_allowed':True}
    facts=[{**base,'evidence_id':'E-PHANDOFF001','fact':'陈安于2018年任董事。','source_url':'https://fixture.invalid/role'},
           {**base,'evidence_id':'E-PHANDOFF002','fact':'陈安于2019年主持项目会议。','source_url':'https://fixture.invalid/meeting'},
           {**base,'evidence_id':'E-PHANDOFF003','fact':'公司创立早期的场景背景，未记载陈安在该事项中的具体行为。','source_url':'https://fixture.invalid/background'}]
    p={'chapter':5,'title':'治理','task':'核对具体治理行为。','facts':facts,'research_facts':facts,
       'writing_contract':'evidence_selection_v2','require_material_dispositions':True,'literal_material_display_proposed':stable_literal_mode}
    claims=[{'analysis':facts[0]['fact'],'evidence_ids':[facts[0]['evidence_id']]}]
    calls=[]
    def invoke(role,prompt,*args):
        assert '材料采用诊断' in role
        packet=json.loads(prompt.splitlines()[-1]);calls.append(packet)
        reviews=[]
        for f in packet['facts']:
            eid=f['evidence_id']
            if eid==facts[0]['evidence_id']:
                reviews.append({'evidence_id':eid,'disposition':'analysis','matched_claim_indices':[0],'reason':'正文保留任职日期与职务，并引用该记录。'})
            elif eid==facts[1]['evidence_id']:
                displayed=eid in packet['source_display_evidence_ids']
                reviews.append({'evidence_id':eid,'disposition':'source_display' if displayed else 'missing',
                    'matched_claim_indices':[],'required_quote':facts[1]['fact'],'reason':'项目会议的日期和主持行为须作为来源记载保留。'})
            else:
                reviews.append({'evidence_id':eid,'disposition':'appendix','reason':'只载公司创立的场景背景，没有人物的具体治理行为。'})
        if len(calls)==1 and changed_task:p['task']='核对另一项完整委托范围。'
        return json.dumps({'material_reviews':reviews})
    final,errors,audit=accept_content(p,claims,[],{'chapter':5,'facts':facts},invoke,None,validate_model_claims)
    assert not errors, [(e.get('exception_type'),e.get('format_errors')) for e in audit.get('material_diagnosis',{}).get('events',[])]
    assert audit['status'].startswith('passed') and final==claims
    assert len(calls)==2 and len(calls[0]['facts'])==3
    assert [f['evidence_id'] for f in calls[1]['facts']]==([f['evidence_id'] for f in facts] if changed_task or not stable_literal_mode else [facts[1]['evidence_id']])
    assert len(audit['material_diagnosis']['rows'])==3
    assert len(p['facts'])==3 and p['required_source_displays'][0]['quote']==facts[1]['fact']
