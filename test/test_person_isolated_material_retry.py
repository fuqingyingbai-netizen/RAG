import json
from person_material_accounting import diagnose_material


def package(count=4):
    facts=[{'evidence_id':f'E-PISOLATE{i:03d}','fact':f'远山科技第{i}个项目的历史背景。'+'技术背景材料。'*20,
        'source_url':f'https://fixture.invalid/{i}','subject':'远山科技','subject_scope':'affiliated_company','analysis_allowed':False} for i in range(count)]
    return {'chapter':5,'title':'治理','task':'核对林知远的具体治理行为。','facts':facts,'research_facts':facts}


def reply(data):
    return json.dumps({'material_reviews':[{'evidence_id':f['evidence_id'],'disposition':'appendix',
        'reason':'本条只记载远山科技项目技术背景，没有记载目标人在本章治理事项中的具体行为。'} for f in data['facts']]})


def test_unfinished_bound_records_retry_individually_with_complete_originals():
    p=package();originals={f['evidence_id']:f['fact'] for f in p['facts']};calls=[]
    def model(role,prompt,emit):
        data=json.loads(prompt.splitlines()[-1]);calls.append(data)
        assert all(f['original']==originals[f['evidence_id']] for f in data['facts'])
        if len(data['facts'])>1:raise TimeoutError('offline test only')
        return reply(data)
    first=diagnose_material(p,[],model,None)
    assert first['status']=='pending' and first['counts']=={'pending':4} and len(calls)==2
    final=diagnose_material(p,[],model,None,first)
    assert final['status']=='passed' and final['counts']=={'appendix':4}
    assert final['isolated_retry_record_ids']==sorted(originals)
    assert final['request_batch_sizes']==[1]*4 and len(calls)==6
    assert {r['evidence_id'] for r in final['rows']}==set(originals)


def test_changed_task_does_not_use_old_unfinished_checkpoint_for_retry_selection():
    p=package()
    def unavailable(*args):raise TimeoutError('offline test only')
    first=diagnose_material(p,[],unavailable,None);p['task']='核对另一项完整委托范围。';sizes=[]
    def model(role,prompt,emit):
        data=json.loads(prompt.splitlines()[-1]);sizes.append(len(data['facts']));return reply(data)
    final=diagnose_material(p,[],model,None,first)
    assert final['status']=='passed' and sizes==[4] and not final['isolated_retry_record_ids']


def test_large_service_outage_keeps_bounded_batches_without_record_loss():
    p=package(9)
    def unavailable(*args):raise TimeoutError('offline test only')
    first=diagnose_material(p,[],unavailable,None)
    assert first['counts']=={'pending':9}
    sizes=[]
    def model(role,prompt,emit):
        data=json.loads(prompt.splitlines()[-1]);sizes.append(len(data['facts']));return reply(data)
    final=diagnose_material(p,[],model,None,first)
    assert final['status']=='passed' and sizes==[8,1]
    assert len(final['rows'])==9 and not final['isolated_retry_record_ids']
