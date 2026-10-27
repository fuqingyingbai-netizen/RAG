"""One source correction must not repack unrelated, already audited inputs."""
from copy import deepcopy
from report_agents import company_editorial as editorial
from test_company_editorial import record,invoke_for,OUTLINE


def rows():
    return [record('I-'+str(i),text=f'第{i}组原表列示收入{i+100}.00元，尚未完成的计划保持待完成状态。') for i in range(4)]


def setup(monkeypatch):
    original=editorial.editorial_batches
    monkeypatch.setattr(editorial,'editorial_batches',lambda records:original(records,max_records=2))
    current=rows()
    prior=editorial.build_editorial_package({'records':current},OUTLINE,'远帆设备公司',invoke_for(current),workers=1)
    assert prior['diagnostic']['failed_batches']==0
    return current,prior


def test_inserting_information_keeps_exact_prior_groups_and_writes_only_the_new_record(monkeypatch):
    current,prior=setup(monkeypatch);extra=record('I-new',text='另有原表列示现金流为0元，不能解读为缺少数据。')
    current.insert(1,extra);calls=[]
    result=editorial.build_editorial_package({'records':current},OUTLINE,'远帆设备公司',invoke_for(current,calls),previous=prior,workers=1)
    assert calls==['公司交付正文编写','公司交付正文独立审稿']
    assert sum(b.get('reused') is True for b in result['batches'])==2
    assert sorted(i for b in result['batches'] for i in b['information_ids'])==sorted(r['information_id'] for r in current)
    assert not result['diagnostic']['pending_information_ids']


def test_excluded_or_changed_record_cannot_reserve_its_old_batch(monkeypatch):
    current,prior=setup(monkeypatch);current[1]['decision']['status']='exclude';calls=[]
    result=editorial.build_editorial_package({'records':current},OUTLINE,'远帆设备公司',invoke_for(current,calls),previous=prior,workers=1)
    assert sum(b.get('reused') is True for b in result['batches'])==1
    assert calls==['公司交付正文编写','公司交付正文独立审稿']
    assert 'I-1' not in {i for b in result['batches'] for i in b['information_ids']}
    changed=rows();changed[2]['text']=changed[2]['text'].replace('102.00元','103.00元');calls=[]
    result=editorial.build_editorial_package({'records':changed},OUTLINE,'远帆设备公司',invoke_for(changed,calls),previous=prior,workers=1)
    assert sum(b.get('reused') is True for b in result['batches'])==1 and len(calls)==2


def test_an_accepted_flag_cannot_bypass_current_native_number_or_audit_checks(monkeypatch):
    current,prior=setup(monkeypatch);prior=deepcopy(prior)
    prior['batches'][0]['findings'][0]['text']=prior['batches'][0]['findings'][0]['text'].replace('100.00元','100.00万元')
    calls=[]
    result=editorial.build_editorial_package({'records':current},OUTLINE,'远帆设备公司',invoke_for(current,calls),previous=prior,workers=1)
    assert sum(b.get('reused') is True for b in result['batches'])==1 and len(calls)==2
    assert all('100.00万元' not in f['text'] for f in result['findings'])


def test_overlapping_old_groups_never_cover_information_twice(monkeypatch):
    current,prior=setup(monkeypatch)
    overlap=editorial.build_editorial_package({'records':current[1:3]},OUTLINE,'远帆设备公司',invoke_for(current),workers=1)
    prior['batches'].extend(overlap['batches']);calls=[]
    result=editorial.build_editorial_package({'records':current},OUTLINE,'远帆设备公司',invoke_for(current,calls),previous=prior,workers=1)
    ids=[i for b in result['batches'] for i in b['information_ids']]
    assert len(ids)==len(set(ids))==4 and not calls
