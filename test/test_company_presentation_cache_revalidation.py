from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace as NS

import pytest

from report_agents.company_checkpoint import save_generation_checkpoint,read_generation_checkpoint,prefix,encode
from report_agents.company_presentation import (VERSION,build_presentation,presentation_scope,checkpoint_batch,
    read_journal,package_errors,journal_binding)
from test_company_checkpoint import store
from test_company_editorial import record
from test_company_presentation import placements


def seeded(tmp_path):
    storage=store(tmp_path)
    project=NS(id=31,target_name='青禾食品公司',industry='食品',
        company_research_intake={'as_of_date':'2026-10-24','reading_format':'analysis_with_annex'},
        sources=[NS(id=1,title='原始文件',url='https://issuer.test/a',content='公司披露本期生产进展。',source_metadata={})],
        company_generation_checkpoint_store=storage)
    rows=[record(text='公司章程规定会议记录须由出席者签字。')]
    package=build_presentation({'records':rows},project.target_name,presentation_scope(project),
        lambda *a:json.dumps(placements(rows)),workers=1,
        receipt_callback=lambda batch:checkpoint_batch(project,batch,lambda *a,**k:None))
    return project,storage,rows,package


def run(project,storage,rows):
    calls=[]
    def invoke(role,*args):calls.append(role);return json.dumps(placements(rows))
    prior={'version':VERSION,'target_name':project.target_name,'scope':presentation_scope(project),
           'batches':read_journal(project,storage)}
    package=build_presentation({'records':rows},project.target_name,presentation_scope(project),invoke,previous=prior,workers=1)
    assert not package_errors(package,{'records':rows},project.target_name,presentation_scope(project))
    return package,calls


def test_unrelated_source_revision_reuses_only_exact_inputs_and_does_not_approve_a_report(tmp_path):
    project,storage,rows,first=seeded(tmp_path)
    project.sources[0].content+='另一个段落新增一句说明。'
    current,calls=run(project,storage,rows)
    assert calls==[] and current['batches'][0]['reused'] is True
    assert current['placements']==first['placements']
    assert not hasattr(project,'company_delivery_contract') and not hasattr(project,'company_document_review')


@pytest.mark.parametrize('change',['text','context','provenance','evidence_ids','decision'])
def test_changed_record_reopens_both_current_reviews_even_when_the_index_is_a_candidate(tmp_path,change):
    project,storage,rows,_=seeded(tmp_path);rows=deepcopy(rows)
    project.sources[0].content+='来源修订。'
    if change=='text':rows[0]['text']+='签字须在会后完成。'
    elif change=='context':rows[0]['context']['period']='2025年度'
    elif change=='provenance':rows[0]['provenance'][0]['source_url']='https://different.test/original'
    elif change=='evidence_ids':rows[0]['evidence_ids']=['E-999999999999']
    else:rows[0]['decision']['voice']='第三方记载，非公司自述'
    assert len(read_journal(project,storage))==1
    current,calls=run(project,storage,rows)
    assert len(calls)==2 and not current['batches'][0].get('reused')


@pytest.mark.parametrize('change',['project','target','date','question','version','missing_source_binding'])
def test_project_scope_version_and_native_provenance_are_never_inferred(tmp_path,change):
    project,storage,rows,_=seeded(tmp_path)
    if change=='project':project.id+=1
    elif change=='target':project.target_name='另一公司'
    elif change=='date':project.company_research_intake['as_of_date']='2026-09-30'
    elif change=='question':project.company_research_intake['focus_questions']=['股东控制边界']
    else:
        key=prefix(project)+'/presentation-current.json';index=json.loads(storage.get_text(key))
        if change=='version':index['version']='unsupported-placement-version'
        else:index.pop('source_fingerprint')
        storage.put_text(key,encode(index))
    assert read_journal(project,storage)==[]


@pytest.mark.parametrize('damage',['review','native_witness'])
def test_rehashed_but_invalid_independent_witnesses_are_rechecked_not_trusted(tmp_path,damage):
    project,storage,rows,_=seeded(tmp_path);folder=prefix(project)
    index=json.loads(storage.get_text(folder+'/presentation-current.json'))
    key,digest=next(iter(index['entries'].items()))
    batch=json.loads(storage.get_text(folder+'/presentation/'+digest+'.json'))
    if damage=='review':batch['review']['records'][0]['source_excerpt']='原文并不存在的句子。'
    else:next(a for a in batch['attempts'] if a['stage']=='review')['response']['records'][0]['surface']='main'
    text=encode(batch);digest=hashlib.sha256(text.encode()).hexdigest()
    storage.put_text(folder+'/presentation/'+digest+'.json',text);index['entries'][key]=digest
    storage.put_text(folder+'/presentation-current.json',encode(index))
    project.sources[0].content+='别处修订。'
    current,calls=run(project,storage,rows)
    assert len(calls)==2 and not current['batches'][0].get('reused')


def test_new_receipt_keeps_prior_candidates_while_every_batch_is_validated_again(tmp_path):
    project,storage,rows,_=seeded(tmp_path)
    project.sources[0].content+='另外一项修订。';project._company_presentation_journal_index=None
    extra=record('I-b',text='公司披露另一项日常例会程序。')
    new=build_presentation({'records':[extra]},project.target_name,presentation_scope(project),
        lambda *a:json.dumps(placements([extra])),workers=1)
    checkpoint_batch(project,new['batches'][0],lambda *a,**k:None)
    index=json.loads(storage.get_text(prefix(project)+'/presentation-current.json'))
    assert len(index['entries'])==2 and index['source_fingerprint']==journal_binding(project)['source_fingerprint']
    current,calls=run(project,storage,rows+[extra])
    assert calls==[] and len(current['placements'])==2


def test_changed_whole_source_still_rejects_the_whole_stage_cache(tmp_path):
    project,storage,rows,package=seeded(tmp_path)
    project.company_presentation_package=package
    project.company_source_review_package={'version':'native-source-review','facts':[]}
    save_generation_checkpoint(project,store=storage)
    project.sources[0].content+='新的来源正文。'
    assert read_generation_checkpoint(project,store=storage)=={}
    # Only the explicit candidate reader can offer the old receipt; its exact
    # rows and both reviews still have to pass before it can be reused.
    assert len(read_journal(project,storage))==1
