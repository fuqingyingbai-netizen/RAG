from copy import deepcopy
from types import SimpleNamespace as NS

from company_pdf import TABLES_VERSION
from company_pdf_reading_order import VERSION as COMPARISON_VERSION
from research_workflow import ResearchWorkflow, company_source_fingerprint


def fixture():
    body='远山制造股份有限公司2025年年度报告\n主要会计数据\n营业收入 120.00 100.00'
    source=NS(id=7,url='https://static.cninfo.com.cn/report.pdf',title='2025年年度报告',content=body,
              source_metadata={'content_kind':'pdf_text_extracted','document_pages':[{'page':1,'text':body}]})
    project=NS(id=12,target_type='company',target_name='远山制造股份有限公司',sources=[source])
    return project,source


def test_facts_cache_changes_for_added_source_body_or_table_cells_but_not_source_order():
    project,source=fixture(); first=company_source_fingerprint(project.sources)
    assert first==company_source_fingerprint(deepcopy(project.sources))
    source.source_metadata['document_pages'][0]['tables']=[[['营业收入','120.00','100.00']]]
    assert first!=company_source_fingerprint(project.sources)
    second=company_source_fingerprint(project.sources); source.content+='\n新披露'
    assert second!=company_source_fingerprint(project.sources)
    another=deepcopy(source);another.id=8;project.sources.append(another)
    assert company_source_fingerprint(project.sources)==company_source_fingerprint(project.sources[::-1])
    assert company_source_fingerprint(project.sources)!=company_source_fingerprint([source])


def test_refresh_keeps_a_coherent_original_and_stops_after_current_extractor_receipt(monkeypatch):
    project,source=fixture(); workflow=ResearchWorkflow(); calls=[]
    # Same body, newly recovered native cells: the old page metadata is still a revision.
    pages=deepcopy(source.source_metadata['document_pages']);pages[0]['tables']=[[['主要会计数据','2025年']]]
    result={'content':source.content,'document_pages':pages,'document_extraction':{'table_version':TABLES_VERSION},'status':'done'}
    monkeypatch.setattr(workflow,'_fetch_web_url_with_timeout',lambda *a,**k:calls.append(a) or result)
    revisions=[]
    monkeypatch.setattr('research_workflow.research_store.put_text',lambda *a:revisions.append(a) or 'revision.json')
    db=NS(commit=lambda:None)
    assert workflow.enrich_company_tables(db,project)==1
    assert source.source_metadata['document_pages']==pages and revisions
    assert workflow.enrich_company_tables(db,project)==0 and len(calls)==1


def test_fetch_failure_preserves_original_and_other_issuers_are_not_refreshed(monkeypatch):
    project,source=fixture();workflow=ResearchWorkflow();before=deepcopy(source.source_metadata)
    monkeypatch.setattr(workflow,'_fetch_web_url_with_timeout',lambda *a,**k:{'status':'timeout'})
    assert workflow.enrich_company_tables(NS(commit=lambda:None),project)==0
    assert source.source_metadata['document_pages']==before['document_pages']
    assert source.source_metadata['table_refresh_failure']['status']=='timeout'
    project.target_name='另一家公司'
    assert workflow._company_table_refresh_candidates(project)==[]


def test_identical_failed_refresh_keeps_complete_original_fingerprint_but_traces_new_attempt(monkeypatch):
    project,source=fixture();workflow=ResearchWorkflow();events=[]
    source.source_metadata['table_refresh_failure']={'version':TABLES_VERSION,'status':'timeout',
        'retrieved_at':'2010-01-01T00:00:00'}
    before=deepcopy(source.source_metadata);fingerprint=company_source_fingerprint(project.sources)
    monkeypatch.setattr(workflow,'_fetch_web_url_with_timeout',lambda *a,**k:{'status':'timeout'})
    assert workflow.enrich_company_tables(NS(commit=lambda:None),project,events.append)==0
    assert source.source_metadata==before and company_source_fingerprint(project.sources)==fingerprint
    traces=[e for e in events if e.get('label')=='公司原表提取状态已保存']
    assert traces and '本次尝试时间：' in traces[-1]['detail'] and '2010-01-01' not in traces[-1]['detail']
    monkeypatch.setattr(workflow,'_fetch_web_url_with_timeout',lambda *a,**k:{'status':'failed'})
    workflow.enrich_company_tables(NS(commit=lambda:None),project)
    assert company_source_fingerprint(project.sources)!=fingerprint
    assert source.source_metadata['table_refresh_failure']['status']=='failed'


def comparison_fixture():
    project,source=fixture()
    source.title=project.target_name+'关于修订公司章程的公告'
    source.content=project.target_name+'\n章程修订对照表\n修订前 修订后\n注册资本 万 万 100.00 元。'
    source.url='http://static.cninfo.com.cn/charter.pdf'
    source.source_metadata={'content_kind':'provider_text','provider_content_complete':True}
    return project,source


def test_repeated_unverified_comparison_preserves_original_version_without_promoting_new_body(monkeypatch):
    project,source=comparison_fixture();workflow=ResearchWorkflow();body=source.content
    source.source_metadata['table_refresh_failure']={'version':TABLES_VERSION,'status':'done',
        'comparison_reason':'original_subject_or_grid_not_verified','retrieved_at':'2010-01-01T00:00:00'}
    before=deepcopy(source.source_metadata);fingerprint=company_source_fingerprint(project.sources)
    result={'content':'其他企业股份有限公司\n章程修订对照表',
        'document_pages':[{'page':1,'text':'其他企业股份有限公司'}],
        'document_extraction':{'table_version':TABLES_VERSION,'comparison_tables':{
            'version':COMPARISON_VERSION,'recovered_pages':[1]}},'status':'done'}
    monkeypatch.setattr(workflow,'_fetch_web_url_with_timeout',lambda *a,**k:result)
    workflow.enrich_company_tables(NS(commit=lambda:None),project)
    assert source.content==body and source.source_metadata==before
    assert company_source_fingerprint(project.sources)==fingerprint


def test_provider_retained_comparison_can_fetch_verified_geometry_without_promoting_a_guess(monkeypatch):
    project,source=comparison_fixture();before=deepcopy(source.source_metadata);old=source.content
    body=project.target_name+'\n章程修订对照表\n| 修订前 | 修订后 |\n| 注册资本90.00万元 | 注册资本100.00万元 |'
    result={'content':body,'document_pages':[{'page':1,'text':body}],
            'document_extraction':{'table_version':TABLES_VERSION,'comparison_tables':{
                'version':COMPARISON_VERSION,'recovered_pages':[1],'pending_pages':[],'source_sha256':'pdf-byte-hash'}},'status':'done'}
    workflow=ResearchWorkflow();calls=[];revisions=[]
    monkeypatch.setattr(workflow,'_fetch_web_url_with_timeout',lambda *a,**k:calls.append(a[0]) or result)
    monkeypatch.setattr('research_workflow.research_store.put_text',lambda *a:revisions.append(a) or 'revision.json')
    assert workflow.enrich_company_tables(NS(commit=lambda:None),project)==1
    assert calls==['https://static.cninfo.com.cn/charter.pdf']
    assert source.content==body and source.source_metadata['previous_document_revision']
    import json
    archive=json.loads(revisions[0][1]);assert archive['content']==old and archive['source_metadata']==before
    assert workflow.enrich_company_tables(NS(commit=lambda:None),project)==0
    assert len(calls)==1


def test_wrong_issuer_or_unverified_grid_cannot_replace_provider_original(monkeypatch):
    project,source=comparison_fixture();old=source.content;workflow=ResearchWorkflow()
    def fetched(name,recovered):
        return {'content':name+'\n章程修订对照表\n修订前 修订后','document_pages':[{'page':1,'text':name}],
            'document_extraction':{'table_version':TABLES_VERSION,'comparison_tables':{
                'version':COMPARISON_VERSION,'recovered_pages':recovered}},'status':'done'}
    monkeypatch.setattr(workflow,'_fetch_web_url_with_timeout',lambda *a,**k:fetched('另一家股份有限公司',[1]))
    assert workflow.enrich_company_tables(NS(commit=lambda:None),project)==0 and source.content==old
    # A target name appearing later inside another issuer's original is not
    # permission to promote that original to the target's own disclosure.
    monkeypatch.setattr(workflow,'_fetch_web_url_with_timeout',lambda *a,**k:fetched('另一家股份有限公司\n收购对象\n'+project.target_name,[1]))
    assert workflow.enrich_company_tables(NS(commit=lambda:None),project)==0 and source.content==old
    monkeypatch.setattr(workflow,'_fetch_web_url_with_timeout',lambda *a,**k:fetched(project.target_name,[]))
    assert workflow.enrich_company_tables(NS(commit=lambda:None),project)==0 and source.content==old
    assert source.source_metadata['content_kind']=='provider_text'


def test_comparison_refresh_still_rejects_related_entities_and_other_subjects():
    project,source=comparison_fixture();workflow=ResearchWorkflow()
    source.source_metadata['entity_validation']='related_entity_context'
    assert workflow._company_table_refresh_candidates(project)==[]
    source.source_metadata.pop('entity_validation');project.target_name='另一家公司'
    assert workflow._company_table_refresh_candidates(project)==[]
