"""Regressions for observed PDF false blocks, stale audits and misplaced edits."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from report_agents import company_editorial as editorial
from report_agents.company_editorial_context import make_evidence_context
from report_agents.company_summary import fallback_company_summary,summary_errors,summary_observations
from report_agents.company_corpus_writer import render_compact_chapters
from report_agents.company_delivery_contract import followup_chapter,fill_evidence_gaps
from test_company_editorial import record,invoke_for,audit,OUTLINE


@pytest.mark.parametrize('native,prose',[
    ('主营业务收入273.99 亿\n元。','主营业务收入为273.99亿元。'),
    ('单位：元\n营业收入 3,000,000.00','营业收入为3,000,000.00元。'),
    ('单位：人民币万元\n收入 10','收入为10万元人民币。'),
    ('2026-07-04','2026年7月4日'),
])
def test_pdf_notation_and_header_units_reach_semantic_auditor(native,prose):
    rows=[record(text=native,context_quote=native)]
    findings,errors=editorial.parse_proposal({'findings':[{'finding_id':'p','text':prose,'information_ids':['I-a']}]},rows,6,OUTLINE[5][1][0])
    assert not errors
    assert not editorial.validate_audit(rows,findings,audit(rows,findings))
    qa=audit(rows,findings);qa['criteria']['factual_support']=False
    assert 'editorial_criterion:factual_support' in editorial.validate_audit(rows,findings,qa)


def test_actual_prompt_change_invalidates_accepted_audit_without_version_edit(monkeypatch):
    rows=[record()];first=editorial.build_editorial_package({'records':rows},OUTLINE,'公司',invoke_for(rows),workers=1)
    calls=[]
    same=editorial.build_editorial_package({'records':rows},OUTLINE,'公司',invoke_for(rows,calls),previous=first,workers=1)
    assert same['batches'][0]['reused'] and not calls
    original=editorial.audit_prompt
    monkeypatch.setattr(editorial,'audit_prompt',lambda *a,**kw:'新增审稿要求。'+original(*a,**kw))
    revised=editorial.build_editorial_package({'records':rows},OUTLINE,'公司',invoke_for(rows,calls),previous=first,workers=1)
    assert calls==['公司交付正文编写','公司交付正文独立审稿']
    assert revised['batches'][0]['policy_sha256']!=first['batches'][0]['policy_sha256']
    assert 'editorial_review_policy_changed' in editorial.package_errors(first,rows,'公司')


def test_document_repair_pins_unaffected_paragraph_and_audits_the_combined_text():
    rows=[record('I-a',text='公司披露收入100元。'),record('I-b',text='公司计划新增产线，尚未实施。')]
    def first_invoke(role,prompt,trace):
        if role=='公司交付正文编写':return json.dumps({'findings':[
            {'finding_id':'bad','text':'公司收入100元，已全部收款。','information_ids':['I-a']},
            {'finding_id':'keep','text':'公司计划新增产线，尚未实施。','information_ids':['I-b']}]})
        data=json.loads(prompt.split('资料：\n',1)[1]);return json.dumps(audit(rows,data['findings']))
    first=editorial.build_editorial_package({'records':rows},OUTLINE,'公司',first_invoke,workers=1)
    bad=next(f for f in first['findings'] if f['local_finding_id']=='bad');calls=[]
    def repair(role,prompt,trace):
        calls.append(role)
        if role=='公司交付正文编写':
            assert '固定已审正文' in prompt and rows[1]['text'] in prompt
            return json.dumps({'findings':[{'finding_id':'ADD_a','text':rows[0]['text'],'information_ids':['I-a']}]})
        data=json.loads(prompt.split('资料：\n',1)[1]);assert len(data['findings'])==2
        return json.dumps(audit(rows,data['findings']))
    second=editorial.build_editorial_package({'records':rows},OUTLINE,'公司',repair,previous=first,workers=1,
        feedback=[{'chapter':6,'finding_ids':[bad['finding_id']],'quote':bad['text'],'message':'收入不能证明收款。'}])
    assert calls==['公司交付正文编写','公司交付正文独立审稿']
    assert not second['diagnostic']['pending_information_ids']
    assert {f['text'] for f in second['findings']}=={r['text'] for r in rows}
    assert second['batches'][0]['attempts'][0]['repair_mode']=='document_targeted_repair'


def test_independent_reviewer_does_not_receive_the_chapter_authoring_example():
    from report_agents.company_chapter_agent import CompanyChapterAgent
    from company_chapters import prompt_contract
    p=SimpleNamespace(target_name='公司');agent=CompanyChapterAgent(2,p,lambda *a,**kw:None);prompts=[]
    def invoke(role,prompt,trace):prompts.append(prompt);return '{}'
    agent.invoke(invoke,'公司交付正文编写','写作任务')
    agent.invoke(invoke,'公司交付正文独立审稿','核对任务')
    assert prompt_contract(2,'公司') in prompts[0]
    assert prompt_contract(2,'公司') not in prompts[1] and 'expression_example' not in prompts[1]
    assert '当前是独立核对任务' in prompts[1] and '核对任务' in prompts[1]


def test_routing_cache_binds_actual_review_prompt_and_model_configuration(monkeypatch):
    from report_agents import company_information_usage as usage
    from test_company_information_journal import setup,statement,decision
    project,_,_=setup();calls=[]
    def invoke(role,prompt,trace):
        rows=json.loads(prompt.rsplit('信息：\n',1)[1]);calls.append(role)
        return json.dumps({'records':[decision(r) for r in rows]})
    scope=usage.routing_scope(project);digest={'statements':[statement()]}
    first=usage.build_information_usage(digest,{},OUTLINE,project.target_name,invoke,workers=1,review_scope=scope)
    before=len(calls)
    usage.build_information_usage(digest,{},OUTLINE,project.target_name,invoke,workers=1,review_scope=scope,previous=first)
    assert len(calls)==before
    original=usage.review_prompt
    monkeypatch.setattr(usage,'review_prompt',lambda *a:'新增归属要求。'+original(*a))
    changed=usage.build_information_usage(digest,{},OUTLINE,project.target_name,invoke,workers=1,review_scope=scope,previous=first)
    assert len(calls)>before and changed['diagnostic']['cached_information_records']==0
    monkeypatch.setenv('MODEL','different-routing-model')
    assert usage.routing_scope(project)!=scope


@pytest.mark.parametrize('successful_assignment',[1,2,3])
def test_auditor_cross_record_locator_repairs_support_ids_without_rewriting_prose(successful_assignment):
    rows=[record('I-a',text='公司本期营业收入10元。'),record('I-b',text='公司本期营业收入10元。公司利润2元。')]
    original={'findings':[{'finding_id':'p1','text':rows[0]['text'],'information_ids':['I-a']},
                          {'finding_id':'p2','text':'公司利润2元。','information_ids':['I-b']}]}
    calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        if role=='公司交付正文编写':return json.dumps(original)
        if role=='公司交付引用归属修复':
            assert '不是冗余引用' in prompt
            ids=['I-a','I-b'] if calls.count(role)>=successful_assignment else ['I-a']
            return json.dumps({'assignments':[{'finding_id':'p1','information_ids':ids,'reason':'两条原文明确同一收入。'},
                                               {'finding_id':'p2','information_ids':['I-b'],'reason':'利润仅见第二条。'}]})
        data=json.JSONDecoder().raw_decode(prompt.rsplit('资料：\n',1)[1])[0];findings=data['findings'];result=audit(rows,findings)
        result['information'][1]['spans']=[{'finding_id':'p1','source_excerpt':rows[0]['text'],'output_excerpt':rows[0]['text']},
                                          {'finding_id':'p2','source_excerpt':'公司利润2元。','output_excerpt':'公司利润2元。'}]
        return json.dumps(result)
    result=editorial.build_editorial_package({'records':rows},OUTLINE,'公司',invoke,workers=1)
    assert not result['diagnostic']['pending_information_ids'],(calls,[(b['errors'],b.get('audit')) for b in result['batches']])
    assert calls==['公司交付正文编写']+['公司交付正文独立审稿','公司交付引用归属修复','公司交付审稿定位重核']*successful_assignment
    assert [f['text'] for f in result['findings']]==[f['text'] for f in original['findings']]
    assert result['findings'][0]['information_ids']==['I-a','I-b']


def test_changed_policy_reaudits_but_keeps_resolved_feedback_on_identical_evidence(monkeypatch):
    rows=[record()];feedback=[{'chapter':6,'information_ids':['I-a'],'message':'保留原文计划尚未完成的状态。'}]
    first=editorial.build_editorial_package({'records':rows},OUTLINE,'公司',invoke_for(rows),workers=1,feedback=feedback)
    original=editorial.audit_prompt
    monkeypatch.setattr(editorial,'audit_prompt',lambda *a,**kw:'新增审稿规则。'+original(*a,**kw))
    calls=[]
    def invoke(role,prompt,trace):
        calls.append(prompt);return invoke_for(rows)(role,prompt,trace)
    second=editorial.build_editorial_package({'records':rows},OUTLINE,'公司',invoke,workers=1,previous=first)
    assert len(calls)==2 and second['batches'][0]['feedback']==feedback
    assert feedback[0]['message'] in calls[0]


def test_summary_feedback_survives_resume_and_explicit_new_request_invalidates_it(monkeypatch):
    from report_agents import company_report_agent as agent
    facts={'facts':[{'evidence_id':'E-123456ABCDEF','fact':'公司披露本期收入10元。'}]}
    monkeypatch.setattr(agent,'build_company_summary_package',lambda *a,**kw:deepcopy(facts))
    p=SimpleNamespace(target_name='公司',description='',industry='',sources=[],
        company_summary_editorial_feedback=[{'chapter':1,'message':'不得扩大为合并范围。'}])
    calls=[]
    def invoke(*args):
        calls.append(args)
        return json.dumps({'报告概述':{'text':'本次研究使用已提供原文。','evidence_ids':[]},
            '核心发现点':[{'text':facts['facts'][0]['fact'],'evidence_ids':['E-123456ABCDEF']}],
            '需关注信号':[],'公司所属赛道竞争格局':{'text':'','evidence_ids':[]},'总体评估':{'text':'','evidence_ids':[]}})
    writer=agent.CompanyReportAgent();emit=lambda *a,**kw:None
    first=writer._write_summary(p,'{}',{6:'已核经营数据'},invoke,emit)
    assert p.company_summary_receipt['editorial_feedback']==p.company_summary_editorial_feedback
    del p.company_summary_editorial_feedback
    assert writer._write_summary(p,'{}',{6:'已核经营数据'},invoke,emit)==first and len(calls)==1
    p.company_summary_editorial_feedback=[]
    writer._write_summary(p,'{}',{6:'已核经营数据'},invoke,emit)
    assert len(calls)==2


def test_full_original_scope_change_reaudits_same_selected_record():
    rows=[record()];url=rows[0]['provenance'][0]['source_url']
    sources=[{'id':1,'url':url,'content':'单位：元\n'+rows[0]['text']}]
    first=editorial.build_editorial_package({'records':rows},OUTLINE,'公司',invoke_for(rows),workers=1,originals=sources)
    calls=[];sources[0]['content']='单位：万元\n'+rows[0]['text']
    second=editorial.build_editorial_package({'records':rows},OUTLINE,'公司',invoke_for(rows,calls),previous=first,workers=1,originals=sources)
    assert len(calls)==2 and not second['batches'][0].get('reused')


def test_writer_and_auditor_receive_identical_complete_original():
    rows=[record()];url=rows[0]['provenance'][0]['source_url'];native='--- PDF page 1 ---\n单位：元\n--- PDF page 2 ---\n'+rows[0]['text']
    sources=[{'id':1,'url':url,'content':native}];packet=make_evidence_context(rows,sources)
    base=invoke_for(rows);prompts=[]
    def invoke(role,prompt,trace):
        prompts.append(prompt);return base(role,prompt,trace)
    editorial.build_editorial_package({'records':rows},OUTLINE,'公司',invoke,workers=1,originals=sources)
    encoded=json.dumps(packet,ensure_ascii=False)
    assert len(prompts)==2 and all(encoded in prompt for prompt in prompts)
    assert packet['sources'][0]['complete_original']==native
    bounded=make_evidence_context(rows,sources,max_full_chars=3)
    assert bounded['sources'][0]['visible_scope']=='bounded_native_excerpts'
    assert 'complete_original' not in bounded['sources'][0]
    assert bounded['sources'][0]['native_excerpts'][0]['information_id']=='I-a'


def test_multi_paragraph_issue_targets_all_affected_records_and_rejects_forged_id():
    units=[{'finding_id':'F-1','chapter':6,'text':'股东会材料误写成年报。','information_ids':['I-a']},
           {'finding_id':'F-2','chapter':6,'text':'另一处仍误写成年报。','information_ids':['I-b']}]
    issue={'chapter':6,'finding_ids':['F-1','F-2'],'quote':units[0]['text'],'message':'两处来源文类错误'}
    bound,pending=editorial.bind_document_issues([issue],{'6':'\n'.join(f['text'] for f in units)},units)
    assert not pending and bound[0]['information_ids']==['I-a','I-b']
    issue['finding_ids']=['F-forged']
    issue['quote']='并不存在的原句'
    bound,pending=editorial.bind_document_issues([issue],{'6':units[0]['text']},units)
    assert not bound and pending[0]['original_issue']==issue


def test_summary_heading_and_invented_single_label_recover_only_by_exact_native_quote():
    units=[{'finding_id':'A-real','chapter':1,'text':'摘要明确提示财务数据未经审计。','information_ids':[]}]
    issue={'chapter':'1. 摘要','finding_ids':['1-需关注信号-2'],'quote':units[0]['text'],'message':'具体问题'}
    bound,pending=editorial.bind_document_issues([issue],{'1':units[0]['text']},units)
    assert not pending and bound[0]['finding_ids']==['A-real']
    assert bound[0]['reported_finding_ids']==['1-需关注信号-2'] and bound[0]['chapter']==1
    issue['quote']='模型改写的句子'
    assert not editorial.bind_document_issues([issue],{'1':units[0]['text']},units)[0]


def test_multi_paragraph_feedback_rewrites_both_batches_and_reuses_unaffected_chapter():
    rows=[record('I-a'),record('I-b',text='另一段披露关联交易协议约定。'),record('I-c',chapter=7)]
    rows[1]['decision']['aspect']=OUTLINE[5][1][1]
    first=editorial.build_editorial_package({'records':rows},OUTLINE,'公司',invoke_for(rows),workers=1)
    affected=[f for f in first['findings'] if f['chapter']==6]
    feedback=[{'chapter':6,'finding_ids':[f['finding_id'] for f in affected],
               'quote':affected[0]['text'],'message':'这两段均须重新核对来源文类。'}]
    calls=[]
    second=editorial.build_editorial_package({'records':rows},OUTLINE,'公司',invoke_for(rows,calls),
        previous=first,workers=1,feedback=feedback)
    assert len(calls)==4 and next(b for b in second['batches'] if b['chapter']==7)['reused']
    assert all(b.get('feedback') for b in second['batches'] if b['chapter']==6)


def test_partial_source_locator_repairs_keep_valid_repairs_and_original_pending_rows(monkeypatch):
    from report_agents import company_reading_recovery as recovery,company_source_review
    rows=[{'scope':'说明文本','quote':'原文甲'},{'scope':'说明文本','quote':'原文乙'}]
    monkeypatch.setattr(recovery,'bind_context_expansions',lambda *a:{})
    monkeypatch.setattr(company_source_review,'validate_selection',lambda row,*a:(row,'') if row['scope']=='target' else (None,'unbound_scope'))
    def invoke(role,prompt,trace):
        assert 'target/group/service_joint' in prompt
        return json.dumps({'repairs':[{'proposal_index':0,'replacement':{'scope':'target','quote':'原文甲'},'reason':'按原件修复主体编码'}]})
    result=recovery.repair_selection_records(SimpleNamespace(target_name='公司'),[],{'facts':rows},invoke)
    assert result['facts'][0]['scope']=='target' and result['facts'][1]==rows[1]
    assert [r['proposal_index'] for r in result['pending_selection_repairs']]==[1]


def test_valid_issues_survive_failed_locator_repair_and_cannot_be_erased_by_pass():
    rows=[record()];package=editorial.build_editorial_package({'records':rows},OUTLINE,'公司',invoke_for(rows),workers=1)
    f=package['findings'][0];p=SimpleNamespace(target_name='公司',sources=[],company_information_usage_package={'records':rows})
    calls=[]
    valid={'chapter':6,'finding_ids':[f['finding_id']],'quote':f['text'],'message':'实际问题'}
    invalid={'chapter':6,'quote':'不存在的句子','message':'另一个问题'}
    def invoke(role,prompt,trace):
        calls.append(prompt)
        return json.dumps({'status':'fail','issues':[valid,invalid]} if len(calls)==1 else {'status':'pass','issues':[]})
    result=editorial.document_review(p,{6:'## 6. 主营业务\n'+f['text']},package,invoke)
    assert result['status']=='failed'
    assert any(i['message']=='实际问题' for i in result['issues'])
    assert any(i.get('unresolved_locator') and i['original_issue']==invalid for i in result['issues'])
    assert len(calls)==2 and json.dumps(invalid,ensure_ascii=False) in calls[1]


def test_summary_fallback_has_only_literal_cards_and_no_program_event_story():
    fact={'fact':'公司公告提示半年度财务数据未经审计。','evidence_id':'E-123456ABCDEF','summary_topic':'risk'}
    package={'facts':[fact]};text=fallback_company_summary(SimpleNamespace(target_name='公司'),package)
    body=[line for line in text.splitlines() if line and not line.startswith('#')]
    assert body==['- '+fact['fact']+'[E-123456ABCDEF]']
    assert not summary_errors(text,package)
    changed=text.replace(fact['fact'],'公司营业收入为10亿美元。')
    assert not summary_errors(changed,package) and summary_observations(changed,package)


def test_sparse_chapters_keep_actual_data_and_pending_metadata_without_empty_talk():
    p=SimpleNamespace(target_name='公司',company_editorial_package={'batches':[{'chapter':6,'accepted':False}]},company_information_usage_package={})
    text='公司披露收入10元。[E-123456ABCDEF]'
    digest={'groups':[{'chapter':6,'aspect':OUTLINE[5][1][0],'summary':text,'evidence_ids':['E-123456ABCDEF']} ]}
    sections=render_compact_chapters(p,digest,OUTLINE,{6:'## 6. 旧模板\n如本章展示图谱'})
    assert text in sections[6] and '待核验事项' not in sections[6] and '图谱' not in sections[6]
    assert not p.company_editorial_package['batches'][0]['accepted']
    gaps=fill_evidence_gaps(sections,p.company_editorial_package,OUTLINE)
    assert gaps[8]=='## 8. '+OUTLINE[7][0]
    assert followup_chapter(p,OUTLINE).strip()=='## 14. '+OUTLINE[13][0]
