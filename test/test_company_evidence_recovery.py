import json
from copy import deepcopy
from types import SimpleNamespace as NS
import pytest
from company_reading import ReadingIndex
from report_agents.company_source_review import validate_selection
from report_agents.company_corpus import build_corpus_review
from report_agents.company_reading_recovery import uncovered_ranges
from test_company_chapter_flow import project,source,config,TARGET,flow


def candidates(text,**metadata):
    s=source(text=text);s.source_metadata.update(metadata)
    p=project([s]);p.company_research_intake=config()
    return p,ReadingIndex().select(p,6,expanded=True)


def selected(doc,window=None,chapter='company.ch10',**extra):
    w=window or doc['windows'][0]
    return {'evidence_id':doc['evidence_id'],'window_id':w['window_id'],'chapter':chapter,
        'scope':'third_party_about_target','relevance':'支持本章具体用途，主体边界按原始返回核对。',**extra}


@pytest.mark.parametrize('text',['登记状态：存续','0','未知','平台载明最高余额及采购上限，应按关联方口径分别核对。','仅有一个没有任何主题词的字符串'])
def test_zero_keyword_and_short_native_values_reach_model_and_can_route(text):
    p,sel=candidates(text,provider='qcc')
    doc=sel['prepared'][0][0];assert ''.join(w['quote'] for w in doc['windows'])==text
    seen=[]
    def invoke(role,prompt,trace):
        seen.append(prompt)
        return json.dumps({'decisions':[{'evidence_id':doc['evidence_id'],'disposition':'accepted','reason':'明确用途'}],
            'facts':[selected(doc)],'window_reviews':[{'evidence_id':doc['evidence_id'],'window_id':w['window_id'],'disposition':'accepted'} for w in doc['windows']]})
    out=build_corpus_review(p,{'facts':[]},{6:'正文'},invoke,lambda *a,**k:None,prepared=sel['prepared'])
    assert seen and out['facts'][0]['fact']==text
    assert out['facts'][0]['chapter']==10 and not out['rejected_selections']
    assert out['source_review']['1']['reading_scope']=='full_native_text'


@pytest.mark.parametrize('chapter',[6,'6','06','company.ch06','ch06','第六章','6.'])
def test_chapter_encoding_normalization_and_semantic_routing(chapter):
    _,sel=candidates('字段名称：原值')
    doc=sel['prepared'][0][0]
    fact,error=validate_selection(selected(doc,chapter=chapter),{doc['evidence_id']:doc},TARGET)
    assert not error and fact['chapter']==6


def test_unknown_ids_cross_task_and_native_tampering_still_fail():
    p,sel=candidates('短字段：0');doc=sel['prepared'][0][0]
    assert validate_selection({**selected(doc),'evidence_id':'E-foreign'},{doc['evidence_id']:doc},TARGET)[1]=='unknown_source'
    assert validate_selection({**selected(doc),'window_id':'W999'},{doc['evidence_id']:doc},TARGET)[1]=='unknown_window'
    modified=deepcopy(doc);modified['windows'][0]['quote']='伪造'
    assert validate_selection(selected(modified),{doc['evidence_id']:modified},TARGET)[1] in {'invalid_native_offset','native_window_hash_mismatch'}
    p.sources[0].project_id=999
    docs,states,_=ReadingIndex().prepare(p)
    assert not docs and states['1']['state']=='foreign_task_source'


def test_long_cross_page_table_coverage_retains_headers_names_units_and_tail():
    raw='董事：王某\n表头：本期/上期；单位：元\n'+'\n'.join(f'项目{i}\t{i}\t未知' for i in range(1300))+'\n--- PDF page 2 ---\n末行：0\n期间：2025年度'
    _,sel=candidates(raw)
    doc=sel['prepared'][0][0];windows=doc['windows']
    assert len(windows)>2 and ''.join(w['quote'] for w in windows)==raw
    assert uncovered_ranges(len(raw),[(w['start'],w['end']) for w in windows])==[]
    assert '末行：0' in windows[-1]['quote'] and sel['prepared'][1]['1']['reviewed_windows']==0
    assert sel['prepared'][1]['1']['reading_scope']!='full_native_text'


def test_later_publication_is_read_with_historical_boundary():
    _,sel=candidates('本公司披露前期已发生事项。',publication_date='2027-01-01')
    doc=sel['prepared'][0][0]
    fact,error=validate_selection(selected(doc),{doc['evidence_id']:doc},TARGET,'2026-11-03')
    assert not error and fact['time_context']['post_cutoff_disclosure'] is True
    assert '事后披露' in fact['boundary']
    from report_agents.company_time_context import annotate_time_context
    original=deepcopy(fact['time_context'])
    annotate_time_context({'facts':[fact]},[source()], '2026-11-03')
    assert fact['time_context']==original


def test_missing_name_is_supplemented_from_actual_adjacent_original_and_rejudged():
    raw='候选人姓名：王某'+('，履历原文附注'*40)+'\n\n2024年9月至今担任独立董事。\n\n财务期间：2025年；单位：元。'
    p,sel=candidates(raw);doc=sel['prepared'][0][0];w=doc['windows'][1];doc['windows']=[w]
    calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        if role=='公司全量原文分析 Agent':
            return json.dumps({'decisions':[{'evidence_id':doc['evidence_id'],'disposition':'needs_context','reason':'缺姓名'}],
                'facts':[],'window_reviews':[{'evidence_id':doc['evidence_id'],'window_id':w['window_id'],'disposition':'needs_context','missing_fields':['姓名']}]})
        data=json.loads(prompt.rsplit('资料：\n',1)[1]);expanded=data['originals'][0]
        assert '候选人姓名：王某' in expanded['windows'][0]['quote']
        return json.dumps({'decisions':[{'evidence_id':doc['evidence_id'],'disposition':'accepted','reason':'邻文提供姓名'}],
            'facts':[selected(expanded,chapter=7)],'window_reviews':[{'evidence_id':doc['evidence_id'],'window_id':w['window_id'],'disposition':'accepted','reason':'邻文完整'}]})
    out=build_corpus_review(p,{'facts':[]},{7:'团队'},invoke,lambda *a,**k:None,prepared=sel['prepared'])
    assert calls==['公司全量原文分析 Agent','公司原文结构上下文补读']
    assert '候选人姓名：王某' in out['facts'][0]['fact'] and out['facts'][0]['chapter']==7
    assert not out['source_review']['1']['structural_gaps']


def test_unresolved_context_preserves_specific_gap_and_clear_facts():
    p,sel=candidates('现金流量表：列关系丢失'+('，原始列位置不明'*40)+'\n\n清楚字段：0');doc=sel['prepared'][0][0];w=doc['windows'][0]
    def invoke(role,prompt,trace):
        return json.dumps({'decisions':[{'evidence_id':doc['evidence_id'],'disposition':'needs_context','reason':'缺列对应'}],
            'facts':[selected(doc,window=doc['windows'][1])],'window_reviews':[{'evidence_id':doc['evidence_id'],'window_id':w['window_id'],'disposition':'needs_context','missing_fields':['现金流本期/上期列关系']}]})
    out=build_corpus_review(p,{'facts':[]},{6:'业务'},invoke,lambda *a,**k:None,prepared=sel['prepared'])
    assert out['source_review']['1']['structural_gaps'][0]['missing_fields']==['现金流本期/上期列关系']
    assert out['source_review']['1']['structural_gaps'][0]['stop_reason']
    assert out['facts']  # Clear information is not discarded for another gap.


def test_failed_platform_receipt_is_read_but_cannot_be_company_fact():
    _,sel=candidates('{"error":{"code":"quota_exceeded"}}',provider='xiniu',collection_failure='quota_exceeded')
    doc=sel['prepared'][0][0]
    assert validate_selection(selected(doc),{doc['evidence_id']:doc},TARGET)[1]=='platform_collection_gap_not_company_fact'


def test_native_context_conflict_clarifies_without_broad_rewrite():
    p,sel=candidates('平台字段：原值');doc=sel['prepared'][0][0];calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        return json.dumps({'decisions':[{'evidence_id':doc['evidence_id'],'disposition':'no_relevant_claim' if len(calls)==1 else 'accepted','reason':'明确范围'}], 'facts':[selected(doc)],'window_reviews':[{'evidence_id':doc['evidence_id'],'window_id':w['window_id'],'disposition':'accepted'} for w in doc['windows']]})
    out=build_corpus_review(p,{'facts':[]},{6:'title'},invoke,lambda *a,**k:None,prepared=sel['prepared'])
    assert len(calls)==2 and calls[-1]=='公司原文判断冲突澄清'
    assert out['facts']


def test_complete_platform_raw_envelopes_are_saved_and_indexed_without_table_clipping(tmp_path,monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from database import Base
    from models import User,ResearchProject,ResearchSource
    from research_store import ResearchObjectStore
    from company_platform import CompanyPlatformAudit,redact_provider_payload
    from company_chapter_flow import ChapterFlow
    from research_workflow import ResearchWorkflow
    from company_flow_state import FlowJournal
    store=ResearchObjectStore();store.mode='local';store.local_root=tmp_path/'objects'
    monkeypatch.setattr('research_store.research_store',store);monkeypatch.setattr('research_workflow.research_store',store)
    engine=create_engine('sqlite://');Base.metadata.create_all(engine)
    payload={'result':{'rows':[{'name':TARGET,'zero':0,'unknown':None,'empty':'','false':False,
        'period':'2025','unit':'元','extra_column':'原值','tail':i,'long_field':'原字段'*4500} for i in range(83)]}}
    with Session(engine) as db:
        user=User(username='platform-replay',password_hash='unused');db.add(user);db.flush()
        p=ResearchProject(title='平台结构回放',target_name=TARGET,target_type='company',created_by_id=user.id)
        db.add(p);db.commit()
        f=ChapterFlow(ResearchWorkflow(),db,p,config())
        for provider in ('qcc','tyc','xiniu'):
            audit=CompanyPlatformAudit(p,provider,'synthetic-test-credential',{},subject=TARGET)
            audit.call(lambda *a,**k:(payload,None),'https://unit.test',{},'native_fields',{'searchKey':TARGET})
        f.retain_platform_sources(config());db.expire(p,['sources'])
        assert len(p.sources)==3
        for src in p.sources:
            assert json.loads(src.content)==payload
            assert json.loads(store.get_text(src.source_metadata['raw_response_key']))==payload
        documents,states,_=ReadingIndex().prepare(p)
        assert len(documents)==3 and all(st['review_windows']>0 for st in states.values())
        for doc in documents:
            raw=''.join(w['quote'] for w in doc['windows'])
            assert json.loads(raw)==payload and '82' in raw
        assert redact_provider_payload({'zero':0,'unknown':None,'Authorization':'hidden','field':'原值'})=={'zero':0,'unknown':None,'Authorization':'[REDACTED]','field':'原值'}


def test_cross_chapter_routing_keeps_bound_records_and_invalidates_destination(tmp_path,monkeypatch):
    from test_company_editorial import record
    f,_,_=flow(tmp_path,monkeypatch,[source()])
    native=record(text=f.project.sources[0].content,chapter=6)
    native['decision']['chapter']=7
    native['provenance'][0].update(source_id=1,original_offset=0,native_quote=f.project.sources[0].content)
    before=f.selection(7)['input_sha256']
    usage=f.route_information({'records':[native],'diagnostic':{}},6)
    assert usage['records']==[] and usage['outbound_routes'][0]['destination_chapter']==7
    assert f.routed_records(7)[0]['text']==native['text']
    queued=f.journal.data['routed_information'][native['information_id']]
    scope=queued.pop('review_scope')
    assert f.routed_records(7)==[]
    queued['review_scope']=scope
    assert f.selection(7)['input_sha256']!=before
    received=f.route_information({'records':[],'diagnostic':{}},7)
    assert received['records'][0]['information_id']==native['information_id']
    f.project.sources[0].content+='原件新修订'
    assert f.routed_records(7)==[]


def test_rerouting_removes_stale_queue_and_destination_but_keeps_native_cache_receipts(tmp_path,monkeypatch):
    from copy import deepcopy
    from test_company_editorial import record
    f,_,_=flow(tmp_path,monkeypatch,[source()])
    native=record(chapter=6);native['provenance'][0].update(source_id=1,original_offset=0)
    routed=deepcopy(native);routed['decision']['chapter']=7
    first=f.route_information({'records':[routed],'diagnostic':{}},6)
    assert first['records']==[] and first['routing_input_records']==[routed]
    f.usages[6]=first;f.usages[7]=f.route_information({'records':[],'diagnostic':{}},7)
    f.editorials[7]={'batches':[{'information_ids':[native['information_id']],'accepted':True}]}
    second=f.route_information({'records':[native],'diagnostic':{}},6)
    assert f.routed_records()==[] and f.usages[7]['records']==[]
    assert 7 not in f.editorials and f.journal.data['chapters']['7']['input_sha256']=='routing_destination_changed'
    assert f.journal.data['partial_editorials']['7'][0]['accepted']
    assert second['records']==[native] and second['routing_input_records']==[native]


@pytest.mark.parametrize('change',['explanation','native_text','destination','aspect'])
def test_merge_prefers_audited_destination_over_queue_explanations_but_rejects_native_conflicts(tmp_path,monkeypatch,change):
    from copy import deepcopy
    f,_,_=flow(tmp_path,monkeypatch,[source()]);f.run_chapter(7)
    native=f.usages[7]['records'][0];queued=deepcopy(native)
    if change=='explanation':queued['decision'].update(relevance='同一事实的另一种路由说明',voice='发布者自述')
    elif change=='native_text':queued['text']+='改动原文'
    elif change=='destination':queued['decision']['chapter']=6
    else:queued['decision']['aspect']='其他用途'
    monkeypatch.setattr(f,'routed_records',lambda *a:[queued])
    if change!='explanation':
        with pytest.raises(ValueError,match='conflicting_chapter_information_identifier'):f.merge()
    else:
        _,usage,_=f.merge()
        assert usage['records'][0]['decision']==native['decision']
        assert len(usage['records'])==len(f.usages[7]['records'])


def test_unknown_selection_ids_are_repaired_in_isolation_and_bound_before_use():
    p,sel=candidates('原始字段：存续');doc=sel['prepared'][0][0];calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        if role=='公司全量原文分析 Agent':
            return json.dumps({'decisions':[{'evidence_id':doc['evidence_id'],'disposition':'accepted','reason':'平台原值'}],
                'facts':[{**selected(doc),'window_id':'foreign-window'}],
                'window_reviews':[{'evidence_id':doc['evidence_id'],'window_id':w['window_id'],'disposition':'accepted'} for w in doc['windows']]})
        return json.dumps({'repairs':[{'proposal_index':0,'replacement':selected(doc),'reason':'只使用任务实际窗口编号，保持原值。'}]})
    out=build_corpus_review(p,{'facts':[]},{6:'title'},invoke,lambda *a,**k:None,prepared=sel['prepared'])
    assert out['facts'] and calls==['公司全量原文分析 Agent','公司原文引用与主体记录修复']
    assert not out['rejected_selections'] and out['review_receipts'][0]['response']['selection_repairs']


def test_context_overflow_splits_without_dropping_tail_and_reuses_successful_child(tmp_path,monkeypatch):
    from company_flow_state import fingerprint
    p,sel=candidates(('第一段完整原文。'*40)+'\n\n'+('末段原文。'*50))
    docs=sel['prepared'][0];assert len(docs[0]['windows'])>1
    calls=[]
    def invoke(role,prompt,trace):
        data=json.loads(prompt.rsplit('资料：\n',1)[1]);batch=data['originals'];calls.append(batch)
        if sum(len(d['windows']) for d in batch)>1:
            exc=RuntimeError('context_length_exceeded');exc.status_code=413;raise exc
        return json.dumps({'decisions':[{'evidence_id':d['evidence_id'],'disposition':'accepted','reason':'完整原文'} for d in batch],
            'facts':[selected(d,window=w) for d in batch for w in d['windows']],
            'window_reviews':[{'evidence_id':d['evidence_id'],'window_id':w['window_id'],'disposition':'accepted'} for d in batch for w in d['windows']]})
    out=build_corpus_review(p,{'facts':[]},{6:'title'},invoke,lambda *a,**k:None,prepared=sel['prepared'])
    assert len(calls)==3 and len(out['facts'])==2
    assert any('末段原文' in f['fact'] for f in out['facts'])
    assert all(not part['error'] for part in out['review_receipts'][0]['response']['split_manifest'])


def test_source_decision_does_not_claim_unacknowledged_tail_was_read():
    p,sel=candidates(('开头原文。'*50)+'\n\n'+('末尾原文。'*50));doc=sel['prepared'][0][0]
    calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        return json.dumps({'decisions':[{'evidence_id':doc['evidence_id'],'disposition':'no_relevant_claim','reason':'仅看开头'}],
            'facts':[],'window_reviews':[{'evidence_id':doc['evidence_id'],'window_id':doc['windows'][0]['window_id'],'disposition':'no_relevant_claim'}]})
    result=build_corpus_review(p,{}, {},invoke,lambda *a,**k:None,prepared=sel['prepared'])
    assert len(calls)==2
    assert result['diagnostic']['all_candidate_windows_reviewed'] is False
    assert result['source_review']['1']['unread_ranges']
    assert result['review_receipts'][0]['response']['pending_window_reviews']


def test_retained_original_pixels_are_actually_read_and_missing_pixels_remain_explicit(tmp_path):
    from PIL import Image
    from io import BytesIO
    from report_agents.company_page_context import read_page_context
    data=BytesIO();Image.new('RGB',(20,30),'white').save(data,format='PNG')
    store=NS(get_bytes=lambda key:data.getvalue())
    source=NS(source_metadata={'images':[{'physical_page':2,'object_key':'retained-page'}]},object_key=None)
    seen=[]
    def recognize(pixels):
        seen.append(pixels.shape);return [[[[0,0],[19,0],[19,10],[0,10]],'姓名：王某',0.91]]
    result=read_page_context(source,2,store,recognize=recognize)
    assert seen==[(30,20,3)] and result['pixels_read'] is True
    assert result['physical_page']==2 and result['original_sha256'] and result['lines'][0]['confidence']==0.91
    assert result['mode']=='local_ocr_transcription_not_visual_model_review'
    assert read_page_context(NS(source_metadata={},object_key=None),2,store)['pixels_read'] is False


def test_page_context_is_bound_into_fact_and_changed_pixels_invalidate_receipt():
    from report_agents.company_reading_recovery import bind_context_expansions
    from company_flow_state import fingerprint
    p,sel=candidates('原表字段：0');doc=sel['prepared'][0][0];w=doc['windows'][0]
    receipt={'status':'transcribed','pixels_read':True,'original_sha256':'retained-pixels','text':'表头：本期'}
    p.company_native_page_reader=lambda *a:deepcopy(receipt)
    expansion={'evidence_id':doc['evidence_id'],'window_id':w['window_id'],'start':w['start'],'end':w['end'],
        'native_window_sha256':w['native_window_sha256'],'original_page_context':deepcopy(receipt),'missing_fields':['表头']}
    lookup=bind_context_expansions(p,[doc],{'context_expansions':[expansion]})
    fact,error=validate_selection(selected(doc),lookup,TARGET)
    assert not error and fact['original_page_context']['original_sha256']=='retained-pixels'
    receipt['original_sha256']='changed-pixels'
    with pytest.raises(ValueError,match='original_page_context_changed'):
        bind_context_expansions(p,[doc],{'context_expansions':[expansion]})


def test_supplemented_shared_reading_invalidates_prior_chapter_even_with_same_native_bytes(tmp_path,monkeypatch):
    f,_,_=flow(tmp_path,monkeypatch,[source()])
    before=f.selection(6)['input_sha256']
    f.journal.data['shared_read_receipts']={'bound-batch':{'response':{'facts':[]}}}
    after=f.selection(6)['input_sha256'];assert after!=before
    f.journal.data['shared_read_receipts']['bound-batch']['response']['facts']=[{'statement_id':'new-native-proof'}]
    assert f.selection(6)['input_sha256']!=after


def test_reading_rule_change_invalidates_same_native_plan(monkeypatch):
    import company_reading
    p,_=candidates('同一版本原文，字段：0');reader=ReadingIndex()
    before=reader.select(p,6)['input_sha256']
    monkeypatch.setattr(company_reading,'MODEL_READING_VERSION','new-bound-reading-contract')
    assert reader.select(p,6)['input_sha256']!=before


def test_cross_chapter_read_reuse_does_not_multiply_native_coverage_counts(tmp_path,monkeypatch):
    f,_,_=flow(tmp_path,monkeypatch,[source()]);f.read(6)
    f.reads[7]=deepcopy(f.reads[6])
    combined=f.merge()[0];state=combined['source_review']['1'];original=f.reads[6]['source_review']['1']
    assert state['review_windows']==original['review_windows']
    assert state['reviewed_windows']==original['reviewed_windows']
    assert state['accepted_claims']==len([r for r in combined['facts'] if r['source_id']=='1'])
    assert state['reused_by_chapters']==[6,7]


def test_exact_neighbor_quote_can_correct_window_locator_but_changed_context_still_fails():
    raw=('完整的首段原文。'*40)+'\n\n相邻原文保留最高余额与采购上限，不能推定实际使用。'
    _,sel=candidates(raw);doc=sel['prepared'][0][0];w=doc['windows'][0]
    quote='相邻原文保留最高余额与采购上限，不能推定实际使用。'
    assert quote not in w['quote'] and quote in w['context_quote']
    row=selected(doc,window=w,quote=quote)
    fact,error=validate_selection(row,{doc['evidence_id']:doc},TARGET)
    assert not error and raw[fact['original_offset']:fact['original_end']]==quote
    changed=deepcopy(doc);changed['windows'][0]['context_quote']+='虚构'
    assert validate_selection(row,{doc['evidence_id']:changed},TARGET)[1]=='native_context_hash_mismatch'


def test_reading_json_accepts_literal_pdf_line_breaks_without_rewriting_quotations():
    from report_agents.company_reading_recovery import parse
    quote='原表第一行\n第二行：0'
    raw=json.dumps({'facts':[{'quote':quote}]}).replace('\\n','\n')
    assert parse('JSON\n'+raw)['facts'][0]['quote']==quote


def test_unread_window_format_failure_is_durable_and_resume_repairs_only_the_record(tmp_path):
    from report_agents.company_reading_recovery import complete_window_reviews
    from report_agents.company_transport import bounded_company_invoke
    from company_flow_state import FlowJournal
    from test_company_chapter_flow import local_store
    _,sel=candidates('原表字段：0');doc=sel['prepared'][0][0];w=doc['windows'][0]
    original={'decisions':[{'evidence_id':doc['evidence_id'],'disposition':'accepted'}],'facts':[]}
    calls=[]
    def fail_format(role,prompt,trace):
        calls.append(role)
        if role=='公司未确认窗口补读':return '{malformed response'
        raise TimeoutError('temporary format service failure')
    journal=FlowJournal(local_store(tmp_path),1,{'target':TARGET})
    result=complete_window_reviews([doc],original,bounded_company_invoke(fail_format,sleep=lambda _:None),journal=journal)
    assert len(calls)==3 and calls.count('公司未确认窗口补读')==1
    assert result['pending_window_reviews'] and result['window_review_receipt']['format_pending']
    restored=FlowJournal(journal.store,1,{'target':TARGET});assert restored.restore()
    resumed=[]
    def repair(role,prompt,trace):
        resumed.append(role);assert '{malformed response' in prompt and doc['windows'][0]['quote'] in prompt
        return json.dumps({'window_reviews':[{'evidence_id':doc['evidence_id'],'window_id':w['window_id'],'disposition':'accepted','reason':'对照同版本原文核对阅读判断。'}]})
    done=complete_window_reviews([doc],original,bounded_company_invoke(repair),journal=restored)
    assert resumed==['公司窗口阅读回执格式恢复'] and not done['pending_window_reviews']
    assert not done['window_review_receipt']['format_pending'] and not done['facts']


def test_window_format_repair_cannot_approve_foreign_ids():
    from report_agents.company_reading_recovery import complete_window_reviews
    _,sel=candidates('原表字段：0');doc=sel['prepared'][0][0];calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        if len(calls)==1:return '{malformed'
        return json.dumps({'window_reviews':[{'evidence_id':'E-foreign','window_id':'W1','disposition':'accepted'}],
            'facts':[{'evidence_id':'E-foreign','window_id':'W1','quote':'伪造'}]})
    done=complete_window_reviews([doc],{'facts':[]},invoke)
    assert done['pending_window_reviews'] and not done['facts']
    assert done['rejected_window_supplement_facts'][0]['selection']['evidence_id']=='E-foreign'
