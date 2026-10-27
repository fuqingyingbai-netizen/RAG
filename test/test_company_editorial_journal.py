import json
import threading
from copy import deepcopy

from report_agents.company_checkpoint import checkpoint_editorial_batch,read_generation_checkpoint,read_editorial_journal
from report_agents.company_editorial import build_editorial_package
from report_agents.company_editorial import editorial_batches,native_propositions
from test_company_checkpoint import project,store
from test_company_editorial import record,invoke_for,OUTLINE


def rows():
    return [record(f'I-{i:02d}',text='远帆设备有限公司披露本期已交付产品，扩建计划尚未实施。',entity='远帆设备有限公司') for i in range(20)]


def test_partial_run_resumes_only_genuinely_checked_batches_and_reaudits_other_information(tmp_path):
    p=project();p.company_generation_checkpoint_store=store(tmp_path);native=rows();base=invoke_for(native)
    def interrupted(role,prompt,trace):
        if role.endswith('格式修复'):return 'not-json'
        if role=='公司交付正文编写':
            data=json.loads(prompt.split('材料：\n',1)[1].split('\n上一稿',1)[0])
            if data[0]['information_id']=='I-16':return 'not-json'
        return base(role,prompt,trace)
    journal=lambda batch:checkpoint_editorial_batch(p,batch,lambda *a,**k:None)
    first=build_editorial_package({'records':native},OUTLINE,p.target_name,interrupted,workers=1,receipt_callback=journal)
    assert first['diagnostic']['failed_batches']==1 and len(first['diagnostic']['pending_information_ids'])==4
    candidates=read_generation_checkpoint(p,store=p.company_generation_checkpoint_store)['company_editorial_cache']
    assert len(candidates['batches'])==1
    calls=[]
    resumed=build_editorial_package({'records':native},OUTLINE,p.target_name,invoke_for(native,calls),
        previous=candidates,workers=1,receipt_callback=journal)
    assert calls==['公司交付正文编写','公司交付正文独立审稿']
    assert resumed['batches'][0]['reused'] and not resumed['diagnostic']['pending_information_ids']
    assert len(read_editorial_journal(p,store=p.company_generation_checkpoint_store))==2
    changed=deepcopy(native);changed[0]['context']['period']='不同期间'
    calls=[]
    build_editorial_package({'records':changed},OUTLINE,p.target_name,invoke_for(changed,calls),previous=candidates,workers=1)
    assert calls.count('公司交付正文编写')==2


def test_completed_batch_is_saved_without_waiting_for_an_earlier_job_and_final_order_is_stable(tmp_path):
    p=project();p.company_generation_checkpoint_store=store(tmp_path);native=rows();base=invoke_for(native)
    released=threading.Event();completed=[]
    def invoke(role,prompt,trace):
        if role=='公司交付正文编写':
            data=json.loads(prompt.split('材料：\n',1)[1])
            if data[0]['information_id']=='I-00':assert released.wait(3)
        return base(role,prompt,trace)
    def callback(batch):
        completed.append(batch['information_ids'][0])
        checkpoint_editorial_batch(p,batch,lambda *a,**k:None)
        if batch['information_ids'][0]=='I-16':released.set()
    result=build_editorial_package({'records':native},OUTLINE,p.target_name,invoke,workers=2,receipt_callback=callback)
    assert completed==['I-16','I-00']
    assert [b['information_ids'][0] for b in result['batches']]==['I-00','I-16']
    assert not result['diagnostic']['pending_information_ids']


def test_corrupt_batch_or_changed_original_cannot_become_an_accepted_cache_hit(tmp_path):
    p=project();storage=store(tmp_path);p.company_generation_checkpoint_store=storage;native=rows()[:1]
    result=build_editorial_package({'records':native},OUTLINE,p.target_name,invoke_for(native),workers=1)
    checkpoint_editorial_batch(p,result['batches'][0],lambda *a,**k:None)
    assert len(read_editorial_journal(p,store=storage))==1
    changed=deepcopy(p);changed.sources[0].source_metadata['entity_validation']='rejected'
    assert read_editorial_journal(changed,store=storage)==[]
    payload=next(tmp_path.rglob('editorial/*.json'));payload.write_text('{}',encoding='utf-8')
    assert read_editorial_journal(p,store=storage)==[]


def test_batch_workload_budget_never_drops_records_or_slices_a_large_native_statement():
    native=[record(f'I-{i:02d}',text=''.join(f'原文第{j}项保留独立的交付条件。' for j in range(12))) for i in range(5)]
    jobs=editorial_batches(native,max_propositions=25)
    assert [r['information_id'] for _,group in jobs for r in group]==[r['information_id'] for r in native]
    assert all(sum(len(native_propositions(r)) for r in group)<=25 for _,group in jobs)
    oversized=record('I-large',text=''.join(f'原文第{j}项保留独立的适用条件。' for j in range(60)))
    jobs=editorial_batches([oversized],max_propositions=25)
    assert jobs[0][1][0]['text']==oversized['text'] and len(native_propositions(jobs[0][1][0]))==60
