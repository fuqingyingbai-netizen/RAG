import asyncio
import hashlib
import io
import json
import zipfile
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest

from report_agents.company_delivery_contract import assess_delivery,finalize_export
from report_agents.company_editorial import record_payload,fingerprint
from report_agents.company_presentation import (build_presentation,presentation_scope,render_annex,
    delivery_bundle,checkpoint_batch,read_journal)
from report_agents.company_checkpoint import read_generation_checkpoint
from report_agents.company_main_focus import build_main_focus, source_units, CRITERIA
from report_agents.company_editorial import build_editorial_package, retention_propositions, REVIEW_CRITERIA
from report_agents.company_presentation import main_usage
from test_company_checkpoint import project as checkpoint_project,store
from test_company_editorial import good_contract_project,record,invoke_for,OUTLINE


def answer_for(rows):
    return {'records':[{'information_id':r['information_id'],'surface':'evidence' if r['information_id']=='I-extra' else 'main',
        'source_excerpt':r['text'],'reason':'与核心判断直接相关，应在正文保留。' if r['information_id']!='I-extra' else '常规程序条文的具体写法，完整放在附件供查阅。'} for r in rows]}


def project_with_annex():
    project,text=good_contract_project();project.company_reading_mode='analysis_with_annex'
    usage=project.company_information_usage_package
    usage['records'].append(record('I-extra',text='公司章程规定会议记录应由出席人员签字。',chapter=4))
    rows=usage['records']
    project.company_presentation_package=build_presentation(usage,project.target_name,presentation_scope(project),
        lambda *a:json.dumps(answer_for(rows)),workers=1)
    main=main_usage(usage,project.company_presentation_package)['records']
    project.company_main_focus_package=build_main_focus(usage,project.company_presentation_package,
        project.target_name,presentation_scope(project),lambda *a:json.dumps({'records':[
            {'information_id':r['information_id'],'main_proposition_ids':[u['proposition_id'] for u in source_units(r)],
             'reason':'保留该记录所有实质事实及对应状态限定。','criteria':dict.fromkeys(CRITERIA,True)} for r in main]}),workers=1)
    focused=main_usage(usage,project.company_presentation_package,project.company_main_focus_package)['records']
    def editorial_invoke(role,prompt,trace):
        delimiter='资料：\n' if '独立审稿' in role else '材料：\n'
        data=json.loads(prompt.split(delimiter,1)[1].split('\n上一稿',1)[0])
        native={r['information_id']:r for r in focused}
        if '独立审稿' in role:
            return json.dumps({'criteria':dict.fromkeys(REVIEW_CRITERIA,True),
                'findings':[{'finding_id':f['finding_id'],'status':'supported','reason':'原文支持全部事实和范围。'} for f in data['findings']],
                'information':[{'information_id':r['information_id'],'status':'retained','reason':'全部要求事实均在正文。',
                    'spans':[{'proposition_id':u['proposition_id'],
                              'finding_id':next(f['finding_id'] for f in data['findings'] if r['information_id'] in f['information_ids']),
                              'output_excerpt':r['text']}
                             for u in retention_propositions(native[r['information_id']])]} for r in data['records']],'issues':[]})
        return json.dumps({'findings':[{'finding_id':'p'+str(n),'text':r['text'],'information_ids':[r['information_id']]}
                                      for n,r in enumerate(data)]})
    project.company_editorial_package=build_editorial_package({'records':focused},OUTLINE,project.target_name,editorial_invoke,workers=1)
    project.company_evidence_annex_html=render_annex(usage,project.company_presentation_package,project.target_name)
    project.company_evidence_annex_manifest={
        'sha256':hashlib.sha256(project.company_evidence_annex_html.encode()).hexdigest(),
        'native_input_sha256':fingerprint([record_payload(r) for r in rows]),'information_records':len(rows)}
    return project,text


def test_main_and_annex_contract_requires_both_existing_semantic_receipts_and_lossless_attachment():
    project,text=project_with_annex()
    assert assess_delivery(project,text)['status']=='passed'
    project.company_evidence_annex_html=project.company_evidence_annex_html.replace('签字','表决')
    project.company_evidence_annex_manifest['sha256']=hashlib.sha256(project.company_evidence_annex_html.encode()).hexdigest()
    assert '原文缺失' in '；'.join(assess_delivery(project,text)['errors'])


def test_forged_placement_or_changed_main_prose_cannot_pass_as_an_annex_delivery():
    project,text=project_with_annex()
    project.company_presentation_package['main_information_ids']=[]
    assert assess_delivery(project,text)['status']=='needs_repair'
    project,text=project_with_annex()
    project.company_editorial_package['findings'][0]['text']='偷偷改写已经通过审稿的正文。'
    assert '丢失或被改写' in '；'.join(assess_delivery(project,text)['errors'])


def test_export_requires_exact_word_and_annex_package_in_addition_to_render_gates():
    project,text=project_with_annex();contract=assess_delivery(project,text)
    metadata={'docx_integrity_status':'passed','docx_layout_status':'passed'}
    assert not finalize_export(metadata,contract,{'docx_render_status':'passed'})['company_delivery_contract']['delivery_ready']
    from docx_exporter import markdown_to_docx_bytes
    word=markdown_to_docx_bytes(text,title='分析主报告')
    payload,bundle_metadata=delivery_bundle(word,project.company_evidence_annex_html)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.namelist()==['分析主报告.docx','完整证据附件.html']
        assert archive.read('分析主报告.docx')==word
        assert archive.read('完整证据附件.html').decode()==project.company_evidence_annex_html
    assert finalize_export({**metadata,**bundle_metadata},contract,{'docx_render_status':'passed'})['company_delivery_contract']['delivery_ready']


def test_placement_journal_restores_only_native_source_bound_candidates(tmp_path):
    project=checkpoint_project();storage=store(tmp_path);project.company_generation_checkpoint_store=storage
    rows=[record()];usage={'records':rows}
    package=build_presentation(usage,project.target_name,presentation_scope(project),
        lambda *a:json.dumps(answer_for(rows)),workers=1,
        receipt_callback=lambda batch:checkpoint_batch(project,batch,lambda *a,**k:None))
    assert len(read_journal(project,storage))==1
    cache=read_generation_checkpoint(project,store=storage)['company_presentation_cache']
    reused=build_presentation(usage,project.target_name,presentation_scope(project),
        lambda *a:pytest.fail('a checked unchanged placement should be reused'),previous=cache,workers=1)
    assert not reused['diagnostic']['pending_information_ids']
    project.sources[0].content+='原文已变化。'
    assert read_journal(project,storage)==[]


def test_corrupted_placement_journal_never_restores_a_green_flag(tmp_path):
    project=checkpoint_project();storage=store(tmp_path);project.company_generation_checkpoint_store=storage
    rows=[record()]
    package=build_presentation({'records':rows},project.target_name,presentation_scope(project),
        lambda *a:json.dumps(answer_for(rows)),workers=1)
    checkpoint_batch(project,package['batches'][0],lambda *a,**k:None)
    folder=f'projects/{project.id}/company_generation_checkpoint'
    index=json.loads(storage.get_text(folder+'/presentation-current.json'))
    digest=next(iter(index['entries'].values()))
    storage.put_text(folder+'/presentation/'+digest+'.json','{"accepted":true}')
    assert read_journal(project,storage)==[]


@pytest.mark.parametrize('missing',[False,True])
def test_download_returns_complete_bundle_or_explicit_error_without_silently_losing_annex(monkeypatch,missing):
    import research_api
    artifact=NS(id=7,project_id=1,artifact_type='desktop_report',title='公司报告',version=1,created_by='workflow',
        artifact_metadata={'default_download_format':'zip','delivery_bundle_object_key':'bundle.zip','docx_object_key':'main.docx'})
    class Query:
        def options(self,*a):return self
        def filter(self,*a):return self
        def first(self):return artifact
    db=NS(query=lambda *a:Query())
    monkeypatch.setattr(research_api,'_get_project',lambda *a:NS())
    def read(key):
        assert key=='bundle.zip'
        if missing:raise FileNotFoundError(key)
        return b'complete-bundle-bytes'
    monkeypatch.setattr(research_api.research_store,'get_bytes',read)
    if missing:
        with pytest.raises(research_api.HTTPException) as exc:research_api.download_artifact(7,db,NS())
        assert exc.value.status_code==503
    else:
        response=research_api.download_artifact(7,db,NS())
        assert response.body==b'complete-bundle-bytes' and response.media_type=='application/zip'


@pytest.mark.parametrize('mode',['analysis_with_annex','detailed'])
def test_report_agent_keeps_annex_information_out_of_main_writing_only_in_requested_mode(monkeypatch,mode):
    from report_agents.company_report_agent import CompanyReportAgent
    rows=[record('I-id',text='公司登记状态为存续。',chapter=2),record(),
          record('I-extra',text='公司章程规定会议记录应由出席人员签字。',chapter=4)]
    for row in rows:row['uses'][0]['aspect']=row['decision']['aspect']
    usage={'records':deepcopy(rows),'diagnostic':{}}
    monkeypatch.setattr('report_agents.company_information_usage.build_information_usage',lambda *a,**k:deepcopy(usage))
    monkeypatch.setattr('report_agents.company_report_agent.build_corpus_review_with_recovery',
        lambda *a,**k:{'version':'unit-native-corpus','facts':[],'diagnostic':{}})
    project=NS(target_name='青禾食品公司',target_type='company',industry='食品',description='',title='公司报告',sources=[],
               company_research_intake={'reading_format':mode})
    agent=CompanyReportAgent();monkeypatch.setattr(agent,'_write_summary',lambda *a,**k:'## 1. 摘要\n摘要内容。')
    main_rows=rows if mode=='detailed' else rows[:2];base=invoke_for(main_rows);roles=[]
    def invoke(role,prompt,trace):
        roles.append(role)
        if role.startswith('公司交付正文取舍'):return json.dumps(answer_for(rows))
        if role.startswith('公司主报告事实选择'):
            data=json.loads(prompt.split('完整资料：\n',1)[1])
            return json.dumps({'records':[{'information_id':item['record']['information_id'],
                'main_proposition_ids':[u['proposition_id'] for u in item['native_propositions']],
                'reason':'保留全部实际状态和与该状态有关的限定。','criteria':dict.fromkeys(CRITERIA,True)} for item in data]})
        if mode=='analysis_with_annex' and role=='公司交付正文独立审稿':
            data=json.loads(prompt.split('资料：\n',1)[1])
            return json.dumps({'criteria':dict.fromkeys(REVIEW_CRITERIA,True),
                'findings':[{'finding_id':f['finding_id'],'status':'supported','reason':'原文支持所有事实和范围。'} for f in data['findings']],
                'information':[{'information_id':r['information_id'],'status':'retained','reason':'全部具体事实已经保留。',
                    'spans':[{'proposition_id':u['proposition_id'],
                        'finding_id':next(f['finding_id'] for f in data['findings'] if r['information_id'] in f['information_ids']),
                        'output_excerpt':next(f['text'] for f in data['findings'] if r['information_id'] in f['information_ids'])}
                        for u in r['propositions']]} for r in data['records']],'issues':[]})
        return base(role,prompt,trace)
    text=agent.generate(project,'{"facts":[]}','{}',invoke,lambda s,n:s[:n],lambda *a,**k:None)
    assert rows[0]['text'] in text and rows[1]['text'] in text
    if mode=='analysis_with_annex':
        assert rows[2]['text'] not in text and rows[2]['text'] in project.company_evidence_annex_html
        assert not project.company_presentation_package['diagnostic']['pending_information_ids']
        assert not project.company_main_focus_package['diagnostic']['pending_information_ids']
        assert not project.company_editorial_package['diagnostic']['pending_information_ids']
    else:
        assert rows[2]['text'] in text and not project.company_evidence_annex_html
        assert not any(role.startswith('公司交付正文取舍') for role in roles)
        assert not any(role.startswith('公司主报告事实选择') for role in roles)


def test_export_exception_clears_an_inherited_ready_flag(monkeypatch):
    import research_workflow
    workflow=research_workflow.ResearchWorkflow.__new__(research_workflow.ResearchWorkflow)
    class Query:
        def filter(self,*a):return self
        def order_by(self,*a):return self
        def first(self):return None
    db=NS(query=lambda *a:Query(),add=lambda *a:None,commit=lambda:None,refresh=lambda *a:None)
    project=NS(id=1,target_type='company',target_name='青禾食品公司')
    calls=[]
    def fail(*a,**k):calls.append(True);raise RuntimeError('export diagnostic')
    monkeypatch.setattr(research_workflow,'markdown_to_docx_bytes',fail)
    monkeypatch.setattr(workflow,'_select_report_outline',lambda *a:OUTLINE)
    monkeypatch.setattr(research_workflow.research_store,'put_text',lambda *a:'report.md')
    monkeypatch.setattr('report_knowledge.sync_report_safely',lambda *a:None)
    artifact=workflow.save_artifact(db,project,'desktop_report','报告','正文',
        {'company_delivery_contract':{'delivery_ready':True,'status':'passed','errors':[]}})
    assert calls and artifact.artifact_metadata['delivery_status']=='export_failed'
    assert artifact.artifact_metadata['company_delivery_contract']['delivery_ready'] is False
