import json
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace as NS

import pytest

from company_chapters import VERSION as TEMPLATE_VERSION, outline
from company_flow_state import FlowJournal, CompanyFlowLimit
from company_reading import ReadingIndex, assess_questions
from company_chapter_flow import ChapterFlow
from research_store import ResearchObjectStore
from research_workflow import ResearchWorkflow, WorkflowPaused
from search_results import SearchResults

TARGET='示例制造股份有限公司'
FINANCE=TARGET+'披露2025年度营业收入12.34亿元，经营活动现金流量净额为2.10亿元，数据为本期合并报表口径。'
TEAM=TARGET+'披露张某于2025年5月1日正式担任总经理，曾任某企业技术负责人，董事会已于同日通过聘任决议。'


def source(number=1,text=None):
    return NS(id=number,url=f'https://original.test/report/{number}',title=TARGET+'2025年度报告',
        source_type='filing',content=text or '\n\n'.join([
            '--- PDF page 30 ---\n第六节 财务报告','截至2025年12月31日止年度：',FINANCE,
            '--- PDF page 80 ---\n第七节 董事及高级管理人员',TEAM]),summary='',
        object_key='',credibility_score=90,source_metadata={'content_kind':'full_text','fetch_status':'done',
            'entity_validation':'verified','target':TARGET})


def project(sources=()):
    return NS(id=42,title='测试公司报告',target_name=TARGET,target_type='company',industry='制造业',
        description='',sources=list(sources),artifacts=[],status='draft')


def config(selected=('company.ch06','company.ch07')):
    return {'target_name':TARGET,'company_name':TARGET,'target_type':'company','industry':'制造业',
        'company_template_version':TEMPLATE_VERSION,'focus_modules':list(selected),'as_of_date':'2026-11-03',
        'ai_search_enabled':True,'search_queries':[],'focus_questions':[],'special_requirements':''}


def local_store(tmp_path):
    store=ResearchObjectStore();store.mode='local';store.local_root=tmp_path/'objects';return store


def fake_model(calls):
    def invoke(role,prompt,trace=None,**kwargs):
        calls.append((role,prompt))
        role=role.split('｜')[0]
        if role=='公司全量原文分析 Agent':
            docs=json.loads(prompt.rsplit('资料：\n',1)[1])['originals']
            facts=[];window_reviews=[]
            import re
            for d in docs:
                for w in d['windows']:
                    relevant=False
                    for owner,pattern in [(6,r'[^。\n]*营业收入[^。]*。'),(7,r'[^。\n]*正式担任总经理[^。]*。')]:
                        for match in re.finditer(pattern,w['quote']):
                            relevant=True
                            facts.append({'evidence_id':d['evidence_id'],'window_id':w['window_id'],
                                'quote':match[0],'quote_start':w['start']+match.start(),
                                'chapter':owner,'scope':'group','relevance':'原文明确披露对应事实与期间。'})
                    window_reviews.append({'evidence_id':d['evidence_id'],'window_id':w['window_id'],
                        'disposition':'accepted' if relevant else 'no_relevant_claim','reason':'核对本批原文范围。','missing_fields':[]})
            answer={'decisions':[{'evidence_id':d['evidence_id'],'disposition':'accepted' if any(f['evidence_id']==d['evidence_id'] for f in facts) else 'no_relevant_claim',
                'reason':'只判断给出的原文范围。'} for d in docs],'facts':facts,'window_reviews':window_reviews}
        elif role=='公司本章问题覆盖核对':
            data=json.loads(prompt.rsplit('资料：\n',1)[1])
            answer={'questions':[{'id':q['id'],'status':'answered','support_ids':[data['proofs'][0]['id']],
                'missing_fields':[],'reason':'原文给出对应主体与期间及完整事件状态。'} for q in data['questions']],
                'follow_up_queries':[]}
        elif role=='公司信息逐项用途核对':
            rows=json.loads(prompt.rsplit('信息：\n',1)[1])
            answer={'records':[{'information_id':r['information_id'],'status':'use','chapter':r['chapters'][0],
                'aspect':outline()[r['chapters'][0]-1][1][0],'voice':'公司披露',
                'relevance':'本段保留对应主体和期间的具体事实与限制。'} for r in rows]}
        elif role=='公司交付正文编写':
            rows=json.loads(prompt.rsplit('材料：\n',1)[1].split('\n上一稿',1)[0])
            answer={'findings':[{'finding_id':'p'+str(n),'text':r['text'],'information_ids':[r['information_id']]}
                for n,r in enumerate(rows)]}
        elif role=='公司交付正文独立审稿':
            from report_agents.company_editorial import REVIEW_CRITERIA
            data=json.loads(prompt.rsplit('资料：\n',1)[1])
            answer={'criteria':dict.fromkeys(REVIEW_CRITERIA,True),
                'findings':[{'finding_id':f['finding_id'],'status':'supported','reason':'原文完整支持该陈述。'} for f in data['findings']],
                'information':[{'information_id':r['information_id'],'status':'retained','reason':'本条原文和范围完整保留。',
                    'spans':[{'finding_id':f['finding_id'],'source_excerpt':r['text'],'output_excerpt':f['text']}
                        for f in data['findings'] if r['information_id'] in f['information_ids']]} for r in data['records']],
                'issues':[]}
        else:answer={'status':'pass','issues':[]}
        return json.dumps(answer,ensure_ascii=False)
    return invoke


def flow(tmp_path,monkeypatch,sources=()):
    store=local_store(tmp_path)
    monkeypatch.setattr('research_store.research_store',store)
    p=project(sources);w=ResearchWorkflow();calls=[];events=[]
    monkeypatch.setattr(w,'_invoke_company_report_editor',fake_model(calls))
    db=NS(commit=lambda:None,rollback=lambda:None,expire=lambda *a:None)
    return ChapterFlow(w,db,p,config(),events.append),calls,events


def test_long_document_is_located_by_chapter_without_embedding_or_full_prompt():
    noise='\n\n'.join(TARGET+'在本页说明图书馆楼层及服务时间，原件本页不涉及本章所需的具体事实或指标。' for _ in range(200))
    s=source();s.content+='\n\n'+noise;p=project([s]);p.company_research_intake=config()
    reader=ReadingIndex()
    six=reader.select(p,6);seven=reader.select(p,7)
    assert six['diagnostic']['embeddings_created']==seven['diagnostic']['embeddings_created']==0
    text6='\n'.join(w['quote'] for d in six['prepared'][0] for w in d['windows'])
    text7='\n'.join(w['quote'] for d in seven['prepared'][0] for w in d['windows'])
    assert FINANCE in text6
    assert six['diagnostic']['selected_chars']>0
    assert TEAM in text7
    assert seven['diagnostic']['selected_chars']<=len(s.content)
    assert all(st['reading_scope']!='full_native_text' for st in seven['prepared'][1].values())
    assert reader.parsed_sources==1
    assert any(w['physical_page']==80 for w in seven['manifest'])
    assert all(s.content[w['start']:w['start']+len(w['quote'])]==w['quote'] for d in seven['prepared'][0] for w in d['windows'])


def test_query_cache_is_single_flight_scoped_and_preserves_failing_requests(tmp_path):
    j=FlowJournal(local_store(tmp_path),1,{'target':TARGET});calls=[]
    def search():calls.append(1);return SearchResults([{'url':'https://original.test/a'}],audit={'status':'success'})
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:j.query({'query':'same','limit':5},search),range(4)))
    assert len(calls)==1 and sum(reused for _,reused in results)==3
    j.query({'query':'same','limit':6},search);assert len(calls)==2
    def fail():calls.append(1);return SearchResults([],audit={'status':'failed'})
    j.query({'query':'failure'},fail);j.query({'query':'failure'},fail)
    assert len(calls)==4
    j.save();restored=FlowJournal(j.store,1,{'target':TARGET});assert restored.restore()
    _,reused=restored.query({'query':'same','limit':5},search);assert reused and len(calls)==4


def test_checkpoint_tamper_budget_and_scope_are_not_silent_success(tmp_path,monkeypatch):
    monkeypatch.setenv('COMPANY_FLOW_MAX_MODEL_CALLS','1')
    j=FlowJournal(local_store(tmp_path),1,{'target':TARGET});j.invoke(lambda *a:'ok','role','prompt')
    with pytest.raises(CompanyFlowLimit):j.invoke(lambda *a:'must not run','role','prompt')
    assert j.data['budget_stop_reason']=='model_calls'
    j.save();assert not FlowJournal(j.store,1,{'target':'another'}).restore()
    pointer=json.loads(j.store.get_text(j.prefix+'/current.json'))
    j.store.put_text(pointer['key'],'{}')
    with pytest.raises(ValueError,match='hash_mismatch'):FlowJournal(j.store,1,{'target':TARGET}).restore()


def test_question_completion_requires_known_native_proofs():
    def invalid(role,prompt,trace):
        data=json.loads(prompt.rsplit('资料：\n',1)[1])
        return json.dumps({'questions':[{'id':q['id'],'status':'answered','support_ids':['invented']}
            for q in data['questions']]})
    result=assess_questions(7,TARGET,[{'fact':TEAM}],invalid)
    assert not result['complete'] and all(q['status']=='missing' for q in result['questions'])


def test_real_chapter_loop_writes_six_before_seven_reusing_the_same_yearbook(tmp_path,monkeypatch):
    f,calls,events=flow(tmp_path,monkeypatch)
    searches=[]
    monkeypatch.setattr(f.workflow,'collect_structured_sources',lambda *a,**kw:0)
    def collect(db,p,*a,**kw):
        searches.append(kw['intake']['focus_modules'])
        p.sources.append(source());return 1
    monkeypatch.setattr(f.workflow,'collect_web_sources',collect)
    f.run_chapter(6)
    assert not f.editorials[6]['diagnostic']['pending_information_ids'],[(b['errors'],b.get('attempts')) for b in f.editorials[6]['batches']]
    assert FINANCE in f.sections[6],{'review':f.reads[6],'usage':f.usages[6],'calls':[r for r,p in calls]}
    f.run_chapter(7);assert TEAM in f.sections[7]
    assert not f.editorials[7]['diagnostic']['pending_information_ids']
    assert searches==[['company.ch06']]
    roles7=[prompt for role,prompt in calls if role.startswith('公司全量原文分析') and 'company_chapter_07_agent' in role]
    assert roles7==[]  # Shared native reading is reused before chapter 7 writing.
    assert any(b.get('attempts')==0 for b in f.reads[7]['review_receipts'])
    finished=[e['chapter'] for e in events if e.get('label')=='本章正文与核验结果已保存']
    assert finished==[6,7]
    assert f.journal.data['chapters']['6']['initial_search_done']
    assert 'initial_search_done' not in f.journal.data['chapters']['7']


def test_resume_revalidates_receipts_and_does_not_rewrite_unchanged_chapter(tmp_path,monkeypatch):
    f,calls,events=flow(tmp_path,monkeypatch,[source()]);f.run_chapter(7)
    assert not f.editorials[7]['diagnostic']['pending_information_ids']
    p=f.project;w=f.workflow;db=f.db
    resumed=ChapterFlow(w,db,p,config(),events.append);resumed.restore()
    count=len(calls);resumed.run_chapter(7)
    assert len(calls)==count
    assert any(e.get('label')=='复用已核本章正文' for e in events)


@pytest.mark.parametrize('change',['scope','version'])
def test_changed_routing_policy_cannot_reuse_an_entire_finished_chapter(tmp_path,monkeypatch,change):
    f,calls,events=flow(tmp_path,monkeypatch,[source()]);f.run_chapter(7)
    if change=='scope':f.usages[7]['review_scope']={**f.usages[7]['review_scope'],'routing_policy_sha256':'old-policy'}
    else:f.usages[7]['version']='old-routing-version'
    calls.clear();events.clear();f.run_chapter(7)
    routing=[(role,prompt) for role,prompt in calls if role.startswith('公司信息逐项用途核对')]
    assert routing and all('company_chapter_07_agent' not in role for role,prompt in routing)
    assert not any(e.get('label')=='复用已核本章正文' for e in events)
    from report_agents.company_information_usage import routing_scope,VERSION
    assert f.usages[7]['review_scope']==routing_scope(f.project) and f.usages[7]['version']==VERSION


def test_outbound_routing_decisions_are_cached_even_when_origin_has_no_body(tmp_path,monkeypatch):
    f,calls,_=flow(tmp_path,monkeypatch,[source()]);base=f.workflow._invoke_company_report_editor
    def invoke(role,prompt,trace=None,**kwargs):
        answer=base(role,prompt,trace,**kwargs)
        if role=='公司信息逐项用途核对':
            data=json.loads(answer)
            for decision in data['records']:decision.update(chapter=7,aspect=outline()[6][1][0])
            return json.dumps(data)
        return answer
    monkeypatch.setattr(f.workflow,'_invoke_company_report_editor',invoke)
    f.run_chapter(6)
    assert f.usages[6]['records']==[] and f.usages[6]['routing_input_records']
    before=sum(role=='公司信息逐项用途核对' for role,prompt in calls)
    f.write(6)
    assert sum(role=='公司信息逐项用途核对' for role,prompt in calls)==before
    assert f.routed_records(7)


def test_changed_native_body_invalidates_index_and_earlier_chapter_only_when_related(tmp_path,monkeypatch):
    f,calls,_=flow(tmp_path,monkeypatch,[source()]);f.run_chapter(7)
    first=f.reads[7]['input_sha256'];count=len(calls)
    unrelated=source(2,TARGET+'公告公司办公楼的图书借阅开放时间与楼层安排。')
    f.project.sources.append(unrelated);f.run_chapter(7)
    assert len(calls)>count and f.reads[7]['input_sha256']!=first
    assert not f.reads[7]['rejected_selections']
    assert any(st['state']=='reviewed_no_accepted_claim' for st in f.reads[7]['source_review'].values())
    count=len(calls)
    f.run_chapter(7);assert len(calls)==count
    # Same URL/title/metadata, changed original: it cannot reuse a stale index.
    f.project.sources[0].content=f.project.sources[0].content.replace('2025年5月1日','2025年6月1日')
    f.run_chapter(7)
    assert len(calls)>count and f.reads[7]['input_sha256']!=first
    assert '2025年6月1日' in f.sections[7]


def test_search_partial_provider_failure_is_not_frozen_in_cache(tmp_path):
    j=FlowJournal(local_store(tmp_path),1,{'target':TARGET});calls=[]
    def partial():
        calls.append(1)
        return SearchResults([{'url':'https://original.test/a'}],audit={
            'engine_states':{'exa':{'status':'returned'},'tavily':{'status':'failed'}}})
    j.query({'query':'same'},partial);j.query({'query':'same'},partial)
    assert len(calls)==2
    def empty():
        calls.append(1);return SearchResults([],audit={'engine_states':{
            'exa':{'status':'returned','result_count':0},'unconfigured':{'status':'not_configured'}}})
    j.query({'query':'empty'},empty);j.query({'query':'empty'},empty)
    assert len(calls)==3
    # Success is durable before a separate chapter checkpoint.
    restored=FlowJournal(j.store,1,{'target':TARGET});assert restored.restore()
    assert restored.query({'query':'empty'},empty)[1]


def test_platform_reuse_preserves_current_session_and_failures_retry(tmp_path):
    from company_platform import CompanyPlatformAudit
    j=FlowJournal(local_store(tmp_path),1,{'target':TARGET});p=project();p._company_flow_journal=j
    audit=CompanyPlatformAudit(p,'qcc','fixture-only',{});calls=[]
    def tool(*a,**kw):calls.append(1);return {'rows':[{'name':TARGET}]},'old-session'
    first=audit.call(tool,'url',{},'get_company',{'searchKey':TARGET},session='s1')
    reused=audit.call(tool,'url',{},'get_company',{'searchKey':TARGET},session='s2')
    assert len(calls)==1 and first[1]=='old-session' and reused[1]=='s2'
    audit.call(tool,'url',{},'get_company',{'searchKey':'another'},session='s3')
    assert len(calls)==2
    def fail(*a,**kw):calls.append(1);return {'error':'unauthorized'},'session'
    audit.call(fail,'url',{},'other_tool',{},session='s1')
    audit.call(fail,'url',{},'other_tool',{},session='s1')
    assert len(calls)==4


def test_pause_and_model_budget_keep_native_material_and_checkpoint(tmp_path,monkeypatch):
    f,_,_=flow(tmp_path,monkeypatch,[source()]);f.pause_requested=lambda:True
    with pytest.raises(WorkflowPaused):f.run_chapter(7)
    assert f.project.sources[0].content and f.project.status=='paused'
    restored=FlowJournal(f.store,42,f.journal.scope);assert restored.restore()
    assert restored.data['reads']['7']['facts']
    f.pause_requested=None;f.journal.limits['model_calls']=f.journal.data['metrics']['model_calls']
    with pytest.raises(CompanyFlowLimit):f.invoke('must stop','prompt')
    assert f.project.sources[0].content


def test_cleanup_requires_validated_export_and_retry_does_not_research(tmp_path,monkeypatch):
    f,calls,_=flow(tmp_path,monkeypatch,[source()]);a=NS(id=9,artifact_metadata={'delivery_status':'export_failed'})
    with pytest.raises(ValueError,match='cleanup_before'):f.finish_cleanup(a)
    a.artifact_metadata={'delivery_status':'final_candidate','company_delivery_contract':{'delivery_ready':True}}
    f.project.artifacts=[a];f.journal.data.update(status='cleanup_pending',report_artifact_id=9)
    f.journal.save();clean=[]
    monkeypatch.setattr(f.workflow,'_latest_artifact',lambda *a:f.project.artifacts[0])
    monkeypatch.setattr(f.workflow,'_finalize_source_records',lambda *a:clean.append(1) or True)
    result=f.run()
    assert result==([a],0) and clean==[1] and not calls
    assert a.artifact_metadata['temporary_materials_status']=='cleared_after_success'
    assert not (f.store.local_root/f.journal.prefix).exists()


def test_cleanup_failure_keeps_checkpoint_for_retry(tmp_path,monkeypatch):
    f,_,_=flow(tmp_path,monkeypatch,[source()]);a=NS(id=9,artifact_metadata={
        'delivery_status':'final_candidate','company_delivery_contract':{'delivery_ready':True}})
    f.journal.data['report_artifact_id']=9
    monkeypatch.setattr(f.workflow,'_finalize_source_records',lambda *a:False)
    f.finish_cleanup(a)
    assert a.artifact_metadata['temporary_materials_status']=='cleanup_pending'
    restored=FlowJournal(f.store,42,f.journal.scope);assert restored.restore()
    assert restored.data['status']=='cleanup_pending' and f.project.sources[0].content


def test_company_cleanup_deletes_only_server_upload_copies_and_preserves_assets(tmp_path):
    from source_retention import finalize_company_sources
    store=local_store(tmp_path);p=project();server_root=tmp_path/'uploads';folder=server_root/str(p.id)
    folder.mkdir(parents=True);copy=folder/'annual.pdf';copy.write_bytes(b'public-file')
    desktop=tmp_path/'desktop.pdf';desktop.write_bytes(b'user-original')
    key=store.put_text(f'projects/{p.id}/uploads/native.txt',TEAM)
    final_key=store.put_text(f'projects/{p.id}/desktop_report/report.md','final report')
    other_key=store.put_text('projects/43/uploads/native.txt','other project')
    s=source();s.object_key=key;s.source_metadata.update(local_path=str(copy),document_pages=[{'text':TEAM}])
    p.sources=[s]
    assert finalize_company_sources(NS(commit=lambda:None),p,store,server_root)==1
    assert not copy.exists() and desktop.read_bytes()==b'user-original'
    assert not s.content and not s.object_key and s.source_metadata['retention_policy']=='record_only'
    assert 'document_pages' not in s.source_metadata
    assert store.get_text(final_key)=='final report' and store.get_text(other_key)=='other project'


def test_actual_company_entrypoint_dispatches_only_to_new_flow(tmp_path,monkeypatch):
    f,_,_=flow(tmp_path,monkeypatch);seen=[]
    monkeypatch.setattr('proposal_branch.load_context',lambda *a,**kw: {})
    def run(w,db,p,intake,*a):seen.append(intake);return [],0
    monkeypatch.setattr('company_chapter_flow.run_company_chapters',run)
    assert f.workflow.run_project(f.db,f.project,[],[],intake=config())==([],0)
    assert seen[0]['company_template_version']==TEMPLATE_VERSION


def test_unanswered_selected_questions_block_delivery_even_when_other_gates_pass(tmp_path,monkeypatch):
    from report_agents.company_delivery_contract import assess_delivery
    f,_,_=flow(tmp_path,monkeypatch,[source()]);f.run_chapter(7)
    f.coverage[7]['complete']=False;f.merge()
    contract=assess_delivery(f.project,'\n\n'.join(f.sections.values()))
    assert '第7章必答问题尚未全部核对完成' in contract['errors']


def test_full_company_flow_exports_fourteen_sections_and_keeps_raw_on_failed_gate(tmp_path,monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from database import Base
    from models import User,ResearchProject,ResearchSource
    from report_agents.company_delivery_contract import split_sections
    store=local_store(tmp_path)
    monkeypatch.setattr('research_store.research_store',store)
    monkeypatch.setattr('research_workflow.research_store',store)
    monkeypatch.setenv('DOCX_RENDER_QA_ENABLED','false')
    monkeypatch.setenv('RESEARCH_KNOWLEDGE_ARCHIVE_ENABLED','false')
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    with Session(engine) as db:
        user=User(username='isolated-test',password_hash='unused');db.add(user);db.flush()
        p=ResearchProject(title='公司逐章集成验收',target_name=TARGET,target_type='company',
            industry='制造业',created_by_id=user.id);db.add(p);db.flush()
        key=store.put_text(f'projects/{p.id}/raw_web/annual.txt',source().content)
        s=source();db.add(ResearchSource(project_id=p.id,title=s.title,url=s.url,content=s.content,
            source_type='filing',object_key=key,source_metadata={**s.source_metadata,'retention_policy':'transient_web_body'}))
        db.commit();w=ResearchWorkflow();calls=[]
        monkeypatch.setattr(w,'_invoke_company_report_editor',fake_model(calls))
        artifacts,added=w.run_project(db,p,[],[],intake={**config([]),'ai_search_enabled':False})
        report=next(a for a in artifacts if a.artifact_type=='desktop_report')
        assert set(split_sections(report.content))==set(range(1,15))
        assert report.artifact_metadata['company_flow_version']=='company-chapter-flow-v1'
        from research_workflow import COMPANY_REPORT_VERSION
        assert report.artifact_metadata['report_pipeline_version']==COMPANY_REPORT_VERSION
        assert report.artifact_metadata['docx_object_key']
        assert report.artifact_metadata['company_delivery_contract']['delivery_ready'] is False
        assert p.status=='diagnostic' and added==0
        assert p.sources[0].content and store.get_text(key)
        assert (store.local_root/f'projects/{p.id}/company_chapter_flow/current.json').exists()
        assert any(a.artifact_type=='proposal' for a in artifacts)
        resumed=ChapterFlow(w,db,p,w._normalize_intake(p,{**config([]),'ai_search_enabled':False},[],[]))
        resumed.restore();count=len(calls);resumed.run_chapter(7)
        assert len(calls)==count  # Actual final-review receipts remain reusable.


def test_actual_search_adapter_reuses_request_across_chapter_labels(tmp_path,monkeypatch):
    import research_workflow
    j=FlowJournal(local_store(tmp_path),1,{'target':TARGET});calls=[]
    def search(query,**parameters):
        calls.append((query,parameters));return SearchResults([{'url':'https://original.test/a','title':'原文'}],
            audit={'engine_states':{'fixture':{'status':'returned'}}})
    monkeypatch.setattr(research_workflow,'web_search_provider',NS(engines=[('fixture',search)],search=search))
    w=ResearchWorkflow()
    first=w._search_query_items_parallel([{'query':'same public question','module':'company.ch06'}],5,['fixture'],query_cache=j)
    second=w._search_query_items_parallel([{'query':'same public question','module':'company.ch07'}],5,['fixture'],query_cache=j)
    assert len(calls)==1 and first[0][1]==second[0][1]
    assert second[0][0]['company_query_reused'] is True


def test_failed_search_pass_can_retry_on_resume_without_becoming_a_completed_round(tmp_path,monkeypatch):
    f,_,_=flow(tmp_path,monkeypatch)
    monkeypatch.setattr(f.workflow,'collect_structured_sources',lambda *a,**kw:0)
    calls=[]
    def fail(*a,**kw):
        calls.append(1);f.journal.data['metrics']['search_failures']=len(calls);return 0
    monkeypatch.setattr(f.workflow,'collect_web_sources',fail)
    f.run_chapter(6)
    assert f.journal.data['chapters']['6']['initial_search_done'] is False
    f.run_chapter(6)
    assert len(calls)==2


def test_traditional_locator_preserves_native_quotes_and_offsets():
    from opencc import OpenCC
    s=source();s.content=OpenCC('s2t').convert(s.content)
    p=project([s]);p.company_research_intake=config()
    selected=ReadingIndex().select(p,7)
    windows=[w for d in selected['prepared'][0] for w in d['windows']]
    assert windows and any('總經理' in w['quote'] for w in windows)
    assert all(s.content[w['start']:w['start']+len(w['quote'])]==w['quote'] for w in windows)


def test_complete_native_reading_plan_covers_tail_without_claiming_all_is_useful():
    p=project([source(text='\n\n'.join([source().content]+[
        TARGET+f'于2025年设立第{i}号业务服务中心，为当地经销商提供售后支持，公告未列示相关投入金额。'
        for i in range(30)]+[
        TARGET+'于2025年开通经销商专线，向各地经销商提供远程售后服务，公告未披露该项业务的收费金额。']))])
    p.company_research_intake=config();reader=ReadingIndex()
    initial=reader.select(p,6);expanded=reader.select(p,6,expanded=True,gap_terms=['经销商专线'])
    native=sum(len(d['windows']) for d in reader.prepare(p)[0])
    assert native>1
    assert initial['diagnostic']['selected_passages']<=expanded['diagnostic']['selected_passages']==native
    assert expanded['diagnostic']['unread_ranges']=={}
    assert all(st['reviewed_windows']==0 for st in expanded['prepared'][1].values())
    assert any('开通经销商专线' in w['quote'] for d in expanded['prepared'][0] for w in d['windows'])


def test_completed_native_batches_survive_a_later_parser_failure(tmp_path,monkeypatch):
    f,calls,_=flow(tmp_path,monkeypatch,[source()])
    def fail(*a,**kw):raise RuntimeError('simulated parser outage')
    monkeypatch.setattr(f.writer,'render_evidence_chapter',fail)
    with pytest.raises(RuntimeError,match='parser outage'):f.read(7)
    restored=ChapterFlow(f.workflow,f.db,f.project,config());restored.restore()
    assert restored.journal.data['partial_reads']['7']
    count=sum(r.startswith('公司全量原文分析') for r,p in calls)
    restored.read(7)
    assert sum(r.startswith('公司全量原文分析') for r,p in calls)==count


def test_company_uploads_never_embed_even_when_legacy_vector_settings_are_enabled(monkeypatch):
    import research_api
    monkeypatch.setenv('VECTOR_INDEX_UPLOADS','true');monkeypatch.setenv('RESEARCH_LEGACY_RAG_ENABLED','true')
    def forbidden(*a,**kw):raise AssertionError('Company documents must not enter embedding preparation.')
    monkeypatch.setattr(research_api,'_source_text_chunks',forbidden)
    result=research_api._index_source_for_rag(project(),source())
    assert result['vector_indexed'] is False and result['vector_index_reason']=='company_task_local_reading'


@pytest.mark.anyio
async def test_company_pdf_upload_keeps_native_pages_and_skips_overlapping_chunks(tmp_path,monkeypatch,anyio_backend):
    import research_api
    from io import BytesIO
    from starlette.datastructures import UploadFile
    store=local_store(tmp_path);p=project();rows=[]
    monkeypatch.setattr(research_api,'UPLOAD_DIR',tmp_path/'uploads')
    monkeypatch.setattr(research_api,'research_store',store)
    monkeypatch.setattr(research_api,'_merge_upload_identity_into_intake',lambda *a:{})
    def forbidden(*a,**kw):raise AssertionError('Company PDF must use its native page parser.')
    monkeypatch.setattr(research_api,'_lightweight_upload_text',forbidden)
    def native(payload):
        assert payload==b'%PDF-fixture'
        return {'content':'--- PDF page 9 ---\n'+TEAM,'document_pages':[{'page':9,'text':TEAM}],
            'document_extraction':{'complete':True,'extracted_pages':1}}
    monkeypatch.setattr('company_pdf.extract_company_pdf',native)
    db=NS(add=rows.append,commit=lambda:None,refresh=lambda r:setattr(r,'id',1))
    result=await research_api._store_uploaded_research_source(db,p,
        UploadFile(file=BytesIO(b'%PDF-fixture'),filename='native-annual.pdf'),
        source_type='upload',module='company.ch07',credibility_score=90)
    assert result.source_metadata['document_pages']==[{'page':9,'text':TEAM}]
    assert result.source_metadata['vector_index_reason']=='company_task_local_reading'
    assert store.get_text(result.object_key)=='--- PDF page 9 ---\n'+TEAM


def test_large_provider_body_is_stored_once_outside_checkpoint_and_hash_checked(tmp_path):
    j=FlowJournal(local_store(tmp_path),1,{'target':TARGET});body='public original body '*50000
    def execute():return SearchResults([{'url':'https://original.test/a','raw_content':body}],audit={'status':'success'})
    j.query({'query':'large public document'},execute)
    pointer=json.loads(j.store.get_text(j.prefix+'/current.json'))
    assert len(j.store.get_text(pointer['key']))<len(body)/10
    cache=next(iter(j.data['query_cache'].values()))
    assert j.query({'query':'large public document'},execute)[0]['rows'][0]['raw_content']==body
    j.store.put_text(cache['key'],'{}')
    with pytest.raises(ValueError,match='cache_object_hash_mismatch'):
        j.query({'query':'large public document'},execute)


def test_task_budget_stop_is_not_misclassified_as_provider_outage():
    from report_agents.company_transport import bounded_company_invoke
    def stop(*a,**kw):raise CompanyFlowLimit('experiment_budget')
    guarded=bounded_company_invoke(stop,threshold=1,cooldown_seconds=60)
    with pytest.raises(CompanyFlowLimit):guarded('role','prompt')
