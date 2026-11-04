from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from report_agents.company_information_usage import information_records, routing_fingerprint, VERSION
from test_company_information_usage import statement, decision, OUTLINE

spec = importlib.util.spec_from_file_location('routing_journal_prototype', Path(__file__).with_name('company_information_journal.py'))
journal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journal)


class Store:
    def __init__(self): self.data = {}; self.fail = ''
    def put_text(self, key, text, mime):
        if self.fail and self.fail in key: raise OSError('private detail must not appear')
        self.data[key] = text
    def get_text(self, key):
        if key not in self.data: raise FileNotFoundError(key)
        return self.data[key]


def setup():
    store = Store()
    project = SimpleNamespace(id=1, target_name='测试公司', industry='设备',
        company_research_intake={'as_of_date':'2026-10-24'}, company_generation_checkpoint_store=store)
    rows = information_records([statement(), statement('T-2', '平台披露研发团队有24人，按所载口径观察。')])
    return project, store, rows


def receipt(project, rows):
    scope = journal.binding(project, OUTLINE)['review_scope']
    return {'routing_version':VERSION, 'target_name':project.target_name, 'review_scope':scope,
        'routing_record_hashes':{r['information_id']:routing_fingerprint(r, project.target_name, scope, OUTLINE) for r in rows},
        'information_ids':[r['information_id'] for r in rows],
        'decisions':{r['information_id']:decision(r) for r in rows}, 'errors':[], 'attempts':[{'attempt':1,'errors':[]}]}


def test_completed_batch_survives_without_whole_stage_or_delivery_approval():
    project, store, rows = setup()
    assert journal.checkpoint_batch(project, receipt(project, rows[:1]), OUTLINE)
    fresh = deepcopy(project); fresh.company_generation_checkpoint_store = store
    assert set(journal.read_decisions(fresh, rows, OUTLINE)) == {rows[0]['information_id']}
    assert not hasattr(fresh, 'company_delivery_contract')
    assert not any(key.endswith('/current.json') for key in store.data)


def test_simultaneous_batches_merge_all_ids():
    project, store, rows = setup()
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda row:journal.checkpoint_batch(project, receipt(project, [row]), OUTLINE), rows))
    assert all(results)
    assert len(journal.read_decisions(project, rows, OUTLINE)) == 2


@pytest.mark.parametrize('change', ['text','context','provenance','evidence_ids','target','date','outline'])
def test_current_input_scope_and_template_are_revalidated(change):
    project, store, rows = setup()
    journal.checkpoint_batch(project, receipt(project, rows), OUTLINE)
    outline = deepcopy(OUTLINE)
    if change == 'target': project.target_name = '另一公司'
    elif change == 'date': project.company_research_intake['as_of_date'] = '2026-10-25'
    elif change == 'outline': outline[7] = ('另一个章节问题', outline[7][1])
    elif change == 'text': rows[0]['text'] += '新增条件。'
    elif change == 'context': rows[0]['context']['new_field'] = 0
    elif change == 'provenance': rows[0]['provenance'][0]['source_url'] = 'https://different.test'
    else: rows[0]['evidence_ids'] = ['E-DIFFERENT']
    recovered = journal.read_decisions(project, rows, outline)
    assert rows[0]['information_id'] not in recovered
    assert len(recovered) == (0 if change in {'target','date','outline'} else 1)


@pytest.mark.parametrize('damage',['corrupt','missing','invalid_decision','exclude'])
def test_corrupt_missing_or_invalid_receipts_never_recover(damage):
    project, store, rows = setup(); batch = receipt(project, rows)
    if damage == 'invalid_decision':
        for item in batch['decisions'].values(): item['voice'] = ''
    if damage == 'exclude':
        for item in batch['decisions'].values(): item.update(status='exclude', exclude_code='generic_definition', reason='一般定义，无企业特定内容')
    journal.checkpoint_batch(project, batch, OUTLINE)
    for key in list(store.data):
        if '/information-routing/' in key:
            if damage == 'missing': del store.data[key]
            elif damage == 'corrupt': store.data[key] += 'broken'
    assert journal.read_decisions(project, rows, OUTLINE) == {}


def test_failed_entry_write_never_publishes_pointer_and_redacts_exception():
    project, store, rows = setup(); events = []
    store.fail = '/information-routing/'
    assert not journal.checkpoint_batch(project, receipt(project, rows), OUTLINE,
        emit=lambda *a,**k:events.append(a))
    assert store.data == {} and 'OSError' in str(events)
    assert 'private detail' not in str(events)


def test_failed_pointer_keeps_previous_durable_state():
    project, store, rows = setup()
    journal.checkpoint_batch(project, receipt(project, rows[:1]), OUTLINE)
    store.fail = 'information-routing-current.json'
    assert not journal.checkpoint_batch(project, receipt(project, rows[1:]), OUTLINE)
    assert set(journal.read_decisions(project, rows, OUTLINE)) == {rows[0]['information_id']}


def usage_builder():
    spec = importlib.util.spec_from_file_location('report_agents._usage_prototype',
        Path(__file__).with_name('company_information_usage.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.build_information_usage


def test_real_builder_resumes_completed_batch_after_phase_interrupt_without_recalling_it():
    project, store, _ = setup(); calls = []
    statements = [statement('T-'+str(i), '平台载明岗位编号'+str(i)+'，不等于在岗人数。') for i in range(19)]
    builder = usage_builder()
    def invoke(role, prompt, trace):
        rows = json.loads(prompt.rsplit('\n信息：\n',1)[1]); calls.append([r['information_id'] for r in rows])
        if len(calls) == 2: raise SystemExit('simulated process interruption')
        return json.dumps({'records':[decision(r) for r in rows]}, ensure_ascii=False)
    options = dict(workers=1, review_scope=journal.binding(project, OUTLINE)['review_scope'],
        receipt_callback=lambda batch:journal.checkpoint_batch(project,batch,OUTLINE),
        journal_loader=lambda rows:journal.read_decisions(project,rows,OUTLINE))
    with pytest.raises(SystemExit): builder({'statements':statements},{},OUTLINE,project.target_name,invoke,**options)
    assert len(journal.read_decisions(project,information_records(statements),OUTLINE)) == 18
    first_ids = set(calls[0]); calls.clear()
    result = builder({'statements':statements},{},OUTLINE,project.target_name,invoke,**options)
    assert len(calls) == 1 and first_ids.isdisjoint(calls[0])
    assert result['diagnostic']['cached_journal_records'] == 18
    assert result['diagnostic']['cached_information_records'] == 18
    assert result['diagnostic']['pending_information_ids'] == []
    assert len(result['records']) == 19
    assert not hasattr(project,'company_delivery_contract')


def test_loader_failure_rechecks_all_input_and_does_not_leak_details():
    project, store, rows = setup(); events = []; calls = []
    def invoke(role, prompt, trace):
        records = json.loads(prompt.rsplit('\n信息：\n',1)[1]); calls.extend(records)
        return json.dumps({'records':[decision(r) for r in records]})
    def failed(records): raise OSError('private credential should never be printed')
    result = usage_builder()({'statements':[statement()]},{},OUTLINE,project.target_name,invoke,
        journal_loader=failed,emit=lambda *a,**k:events.append(a))
    assert len(calls) == 1 and result['diagnostic']['cached_journal_records'] == 0
    assert 'OSError' in str(events) and 'private credential' not in str(events)
