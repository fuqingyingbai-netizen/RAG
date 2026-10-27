import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from report_agents.company_editorial import (
    REVIEW_CRITERIA,build_editorial_package,parse_proposal,validate_audit,
    comparable_conflicts,apply_narrative_uses,digest_groups,document_review,
    render_conflicts,review_jobs,fingerprint,record_payload,
)
from report_agents.company_delivery_contract import assess_delivery,report_hash,finalize_export,delivery_requirements
from report_agents.company_information_usage import information_records
from report_agents.company_report_agent import COMPANY_REPORT_OUTLINE as OUTLINE


def record(i='I-a',text='青禾食品公司披露本期已交付产品，计划新增产线尚未完成。',chapter=6,**ctx):
    return {'information_id':i,'text':text,'context':{'entity':'青禾食品公司','scope':'target_direct',**ctx},
            'decision':{'status':'use','chapter':chapter,'aspect':OUTLINE[chapter-1][1][0],
                        'voice':'公司披露','relevance':'交付及计划状态分别说明。'},
            'evidence_ids':['E-123456ABCDEF'],'statement_ids':['T-'+i],
            'provenance':[{'source_url':'https://foods.test/report','source_title':'公司披露'}],
            'uses':[{'surface':'chapter_detail','chapter':chapter}]}


def proposal(rows):
    return {'findings':[{'finding_id':'p'+str(n),'text':r['text'],'information_ids':[r['information_id']]}
                        for n,r in enumerate(rows)]}


def audit(rows,findings):
    return {'criteria':dict.fromkeys(REVIEW_CRITERIA,True),
            'findings':[{'finding_id':f['finding_id'],'status':'supported','reason':'原文支持归因和完整范围。'} for f in findings],
            'information':[{'information_id':r['information_id'],'status':'retained','reason':'独立事实与条件完整表达。',
                'spans':[{'finding_id':f['finding_id'],'source_excerpt':r['text'],'output_excerpt':f['text']} for f in findings if r['information_id'] in f['information_ids']]}
                for r in rows],'issues':[]}


def invoke_for(rows,calls=None):
    def invoke(role,prompt,trace):
        if calls is not None:calls.append(role)
        if role=='公司交付正文独立审稿':
            data=json.loads(prompt.split('资料：\n',1)[1]); lookup={r['information_id']:r for r in rows}
            return json.dumps(audit([lookup[r['information_id']] for r in data['records']],data['findings']),ensure_ascii=False)
        if role=='公司交付全文审稿':return json.dumps({'status':'pass','issues':[]})
        data=json.loads(prompt.split('材料：\n',1)[1].split('\n上一稿',1)[0].split('\n最终报告',1)[0])
        lookup={r['information_id']:r for r in rows}
        return json.dumps(proposal([lookup[r['information_id']] for r in data]),ensure_ascii=False)
    return invoke


@pytest.mark.parametrize('name,sector',[('青禾食品公司','食品'),('远帆物流有限公司','物流'),('Northstar Devices Ltd','医疗设备'),('某研发工作室','未融资初创')])
def test_all_company_names_and_sectors_use_the_same_semantic_contract(name,sector):
    rows=[record(text=name+'披露本期已交付产品，计划新增产线尚未完成。')]
    package=build_editorial_package({'records':rows},OUTLINE,name,invoke_for(rows),workers=1)
    assert package['diagnostic']['pending_information_ids']==[] and package['diagnostic']['narrative_information']==1
    apply_narrative_uses({'records':rows},package)
    assert rows[0]['uses'][-1]['surface']=='chapter_narrative'
    assert rows[0]['uses'][-1]['source_excerpt']==rows[0]['text']
    assert rows[0]['text'] in digest_groups(package)[0]['summary']


def test_support_ids_alone_cannot_pass_semantic_retention():
    rows=[record()]; findings,errors=parse_proposal(proposal(rows),rows,6,OUTLINE[5][1][0]); assert not errors
    qa=audit(rows,findings);qa['information'][0]['spans']=[]
    assert 'lost_information:I-a' in validate_audit(rows,findings,qa)
    qa=audit(rows,findings);qa['information'][0]['spans'][0]['output_excerpt']='正文中并不存在的句子'
    assert 'unbound_semantic_span:I-a' in validate_audit(rows,findings,qa)


@pytest.mark.parametrize('native,rendered',[('2024-07-04','July 4, 2024'),
    ('2024/07/04','2024年7月4日'),('2024年07月04日','04 July 2024'),
    ('1905-04-03','April 3, 1905'),('2024-09-04','Sept. 04, 2024')])
def test_equivalent_valid_calendar_padding_is_not_new_or_lost_information(native,rendered):
    rows=[record(text='公司披露于'+native+'完成产品交付。')]
    answer={'findings':[{'finding_id':'date','text':'公司披露于'+rendered+'完成产品交付。','information_ids':['I-a']}]}
    findings,errors=parse_proposal(answer,rows,6,OUTLINE[5][1][0])
    assert not errors
    assert not validate_audit(rows,findings,audit(rows,findings))


def test_calendar_format_support_does_not_change_quantities_or_validate_an_invalid_calendar():
    from report_agents.company_editorial import numeric_tokens
    for native,changed in [('0.50亿元','0.5亿元'),('000100股','100股'),('-07.04万元','-7.04万元'),
                           ('2024-02-31','2024年2月31日'),('2024-07-04','2024年7月5日')]:
        assert numeric_tokens(native)!=numeric_tokens(changed)


@pytest.mark.parametrize('native,rendered',[
    ('③股份公司成立后，注册资本5,384.45万元。','股份公司成立后，注册资本5,384.45万元。'),
    ('第六届董事会第十二次会议','12th meeting of the sixth session of the board'),
    ('第一百零二次会议','102nd meeting'),
    ('第007期发行文件','007th edition'),
])
def test_explicit_list_and_ordinal_notation_does_not_invent_a_quantity(native,rendered):
    from report_agents.company_editorial import numeric_tokens
    assert numeric_tokens(native)==numeric_tokens(rendered)
    rows=[record(text=native)]
    findings,errors=parse_proposal({'findings':[{'finding_id':'p','text':rendered,
        'information_ids':['I-a']}]},rows,6,OUTLINE[5][1][0])
    assert not errors
    assert not validate_audit(rows,findings,audit(rows,findings))


@pytest.mark.parametrize('native,changed',[
    ('持有3股','持有4股'),('持有3股','持有股份'),
    ('第十二次会议','第十三次会议'),('第007期','第7期'),
    ('0.50亿元','0.5亿元'),('000100股','100股'),
    ('第2026-012号文','第2026-12号文'),
])
def test_ordinal_support_preserves_real_quantities_and_identifiers(native,changed):
    from report_agents.company_editorial import numeric_tokens
    assert numeric_tokens(native)!=numeric_tokens(changed)


def test_traditional_currency_name_is_not_a_new_currency_but_fx_changes_still_fail():
    rows=[record(text='公司的註冊資本為人民幣5,560,600,544元。')]
    answer={'findings':[{'finding_id':'p','text':'公司披露注册资本为人民币5,560,600,544元。',
                        'information_ids':['I-a']}]}
    findings,errors=parse_proposal(answer,rows,6,OUTLINE[5][1][0])
    assert not errors
    assert not validate_audit(rows,findings,audit(rows,findings))
    answer['findings'][0]['text']='公司披露注册资本为美元5,560,600,544元。'
    assert any('new_or_changed_currency' in e for e in parse_proposal(answer,rows,6,OUTLINE[5][1][0])[1])


@pytest.mark.parametrize('native,rendered',[
    ('原文为人民币46,317.9293 元。','原文为人民币46,317.9293 元，其中数字46,317.9293按原文照录。'),
    ('原文错位片段为辞任之日起 日内确定新的法定代表30 人。',
     '原文错位片段为“辞任之日起 日内确定新的法定代表30 人”，其中“30”与“日”位置错乱，不能据此修复数量。'),
])
def test_bare_reference_requires_complete_native_quantity_in_same_finding(native,rendered):
    rows=[record(text=native)]
    findings,errors=parse_proposal({'findings':[{'finding_id':'p','text':rendered,
        'information_ids':['I-a']}]},rows,6,OUTLINE[5][1][0])
    assert not errors
    assert not validate_audit(rows,findings,audit(rows,findings))


@pytest.mark.parametrize('native,changed',[
    ('收入10万元。','收入10。'),
    ('持股30股。','持股30。'),
    ('收入10万元。','原文收入10万元，但实际收入10亿元。'),
    ('收入0.50亿元。','原文收入0.50亿元，但实际收入0.5亿元。'),
    ('持股000100股。','原文持股000100股，数字100为股数。'),
])
def test_bare_reference_cannot_remove_unit_or_change_scale_precision_or_code(native,changed):
    rows=[record(text=native)]
    errors=parse_proposal({'findings':[{'finding_id':'p','text':changed,
        'information_ids':['I-a']}]},rows,6,OUTLINE[5][1][0])[1]
    assert any('new_or_changed_number_unit' in e for e in errors)


def test_quantity_reference_does_not_authorize_a_new_metric_or_skip_semantic_audit():
    rows=[record(text='公司披露收入10万元。')]
    def invoke(role,prompt,trace):
        if role=='公司交付正文编写':
            return json.dumps({'findings':[{'finding_id':'p','text':'公司披露收入10万元，利润为10。',
                                           'information_ids':['I-a']}]},ensure_ascii=False)
        data=json.loads(prompt.split('资料：\n',1)[1]);result=audit(rows,data['findings'])
        result['criteria']['factual_support']=False;result['findings'][0]['status']='unsupported'
        result['issues']=['原文仅披露收入，没有利润数据。']
        return json.dumps(result,ensure_ascii=False)
    package=build_editorial_package({'records':rows},OUTLINE,'任意目标',invoke,workers=1)
    assert not package['findings'] and package['diagnostic']['pending_information_ids']==['I-a']


@pytest.mark.parametrize('native,rendered',[
    ('7,485萬股','7,485万股'),('人民幣18,435萬元','人民币18,435万元'),
    ('港幣5億元','港币5亿元'),('歐元5萬元','欧元5万元'),
])
def test_same_currency_and_scale_script_keeps_numeric_meaning(native,rendered):
    from report_agents.company_editorial import numeric_tokens,currency_tokens
    assert numeric_tokens(native)==numeric_tokens(rendered)
    assert currency_tokens(native)==currency_tokens(rendered)


def test_script_normalization_retains_exact_native_quote_offsets_and_scale():
    from report_agents.company_editorial import quantity_spans,restore_native_notation
    native='公司披露：人民幣18,435萬元。'
    span=next(s for s in quantity_spans(native) if s['dimension']=='currency:CNY')
    assert native[span['start']:span['end']]==span['text']=='人民幣18,435萬元'
    assert span['value']==184350000
    rows=[record(text=native)]
    answer={'findings':[{'finding_id':'p','text':'公司披露人民币184350000元。','information_ids':['I-a']}]}
    assert restore_native_notation(answer,rows)
    assert '人民幣18,435萬元' in answer['findings'][0]['text']
    assert not parse_proposal(answer,rows,6,OUTLINE[5][1][0])[1]


def test_bound_source_label_and_exact_document_title_do_not_become_company_quantities():
    rows=[record(text='公司披露产品已完成交付。')]
    rows[0]['provenance'][0]['source_title']='青禾食品公司资料_Alpha12_金融服务网'
    text='Alpha12页面引述公司披露，产品已完成交付。'
    answer={'findings':[{'finding_id':'p','text':text,'information_ids':['I-a']}]}
    assert not parse_proposal(answer,rows,6,OUTLINE[5][1][0])[1]
    rows[0]['provenance'][0]['source_title']='青禾食品2025年度报告'
    answer['findings'][0]['text']='《青禾食品2025年度报告》披露产品已完成交付。'
    assert not parse_proposal(answer,rows,6,OUTLINE[5][1][0])[1]
    answer['findings'][0]['text']='《青禾食品2025年度报告》披露公司在2025年完成产品交付。'
    assert any('new_or_changed_number_unit' in e for e in
               parse_proposal(answer,rows,6,OUTLINE[5][1][0])[1])


@pytest.mark.parametrize('text',[
    'Alpha13页面称公司披露产品已完成交付。',
    '公司2025年完成产品交付。',
    'Alpha12页面称公司营业收入12万元，已完成产品交付。',
    '《青禾食品2025年度报告》称公司在2025年完成产品交付。',
    '《青禾食品2026年度报告》披露产品已完成交付。',
])
def test_source_metadata_cannot_authorize_unknown_label_amount_or_company_period(text):
    rows=[record(text='公司披露产品已完成交付。')]
    rows[0]['provenance'][0]['source_title']='青禾食品2025年度报告_Alpha12_金融服务网'
    errors=parse_proposal({'findings':[{'finding_id':'p','text':text,'information_ids':['I-a']}]},
                          rows,6,OUTLINE[5][1][0])[1]
    assert any('new_or_changed_number_unit' in e for e in errors)


def test_partial_coverage_and_falsified_review_cannot_pass():
    rows=[record()]; findings,_=parse_proposal(proposal(rows),rows,6,OUTLINE[5][1][0])
    qa=audit(rows,findings);qa['information'][0]['status']='lost'
    assert validate_audit(rows,findings,qa)
    qa=audit(rows,findings);qa['information']*=2
    assert 'incomplete_information_review' in validate_audit(rows,findings,qa)
    qa=audit(rows,findings);qa['criteria']['factual_support']='true'
    assert validate_audit(rows,findings,qa)


def test_new_units_false_completion_and_bad_audit_trigger_automatic_repair():
    rows=[record(text='公司披露营业收入10亿元，拟于下期投产。')];calls=[];counter=0
    base=invoke_for(rows)
    def invoke(role,prompt,trace):
        nonlocal counter
        calls.append(role)
        if role=='公司交付正文编写':
            counter+=1
            if counter==1:return json.dumps({'findings':[{'finding_id':'wrong','text':'公司已投产并实现营业收入10亿美元。','information_ids':['I-a']}]})
        return base(role,prompt,trace)
    package=build_editorial_package({'records':rows},OUTLINE,'任意目标',invoke,workers=1)
    assert package['batches'][0]['accepted'] and len(package['batches'][0]['attempts'])==2
    assert any('new_or_changed_number_unit' in e for e in package['batches'][0]['attempts'][0]['errors'])
    assert package['findings'][0]['text']==rows[0]['text']


def test_persistent_model_failure_remains_pending_and_never_fabricates_prose():
    def fail(*a):raise TimeoutError()
    p=build_editorial_package({'records':[record()]},OUTLINE,'任意目标',fail,workers=1)
    assert not p['findings'] and p['diagnostic']['pending_information_ids']==['I-a']
    assert len(p['batches'][0]['attempts'])==3


def test_identical_proofs_can_reuse_but_new_unit_period_or_voice_cannot():
    rows=[record()];calls=[]
    p=build_editorial_package({'records':rows},OUTLINE,'公司',invoke_for(rows),workers=1)
    again=build_editorial_package({'records':rows},OUTLINE,'公司',invoke_for(rows,calls),previous=p,workers=1)
    assert again['batches'][0]['reused'] and not calls
    changed=deepcopy(rows);changed[0]['decision']['voice']='原告主张，非裁判认定'
    third=build_editorial_package({'records':changed},OUTLINE,'公司',invoke_for(changed,calls),previous=p,workers=1)
    assert calls and not third['batches'][0].get('reused')


def test_conflict_requires_equal_explicit_scope_and_period_unknown_is_not_zero():
    a=record(field='收入',value='10.00',unit='亿元',period='2025年度')
    b=record('I-b',field='收入',value='12.00',unit='亿元',period='2025年度')
    c=record('I-c',field='收入',value='12.00',unit='亿元',period='2024年度')
    d=record('I-d',field='收入',value='待查',unit='亿元',period='2025年度')
    e=record('I-e',field='收入',value='12.00',unit='亿元',period='2025年度',scope='parent_only')
    differences=comparable_conflicts([a,b,c,d,e]); assert len(differences)==1
    assert differences[0]['information_ids']==['I-a','I-b']
    text=render_conflicts({'conflicts':differences},{6:'正文'})[6]
    assert '10.00' in text and '12.00' in text and '未取得解释前不择一认定' in text


def test_zero_currency_and_previous_values_remain_distinct_information():
    def s(ctx):return {'statement_id':str(ctx),'chapter':6,'text':'源表原值','context':ctx}
    rows=information_records([s({'value':0}),s({'value':''}),s({'currency':'USD'}),s({'currency':'CNY'}),
                              s({'previous_value':'10.00'}),s({'previous_value':'10.0'})])
    assert len(rows)==6


def test_final_document_review_cannot_pass_on_invalid_or_unbound_issue():
    p=SimpleNamespace(target_name='某公司',company_research_intake={})
    review=document_review(p,{1:'## 1. 摘要\n经营变化。',6:'## 6. 经营\n原件经营内容。'}, {},
        lambda *a:json.dumps({'status':'fail','issues':[{'chapter':6,'quote':'不存在的句子','message':'有问题'}]}))
    assert review['status']=='failed' and any('document_review_failed' in i['message'] for i in review['issues'])


def test_long_document_review_jobs_retain_every_character_without_clipping():
    text='\n\n'.join('第'+str(i)+'项原文。'*15 for i in range(200))
    jobs=review_jobs({'6':text},max_chars=500)
    assert len(jobs)>2
    assert compact_join([j['6'] for j in jobs])==compact_join([text])


def compact_join(values):return ''.join(''.join(v.split()) for v in values)


def good_contract_project():
    rows=[record('I-id','青禾食品公司登记状态为存续。',chapter=2),record()]
    p=build_editorial_package({'records':rows},OUTLINE,'青禾食品公司',invoke_for(rows),workers=1)
    report='\n\n'.join(f'## {r["decision"]["chapter"]}. 章节\n{r["text"]}' for r in rows)
    project=SimpleNamespace(target_name='青禾食品公司',company_research_intake={},
        company_information_usage_package={'records':rows},company_editorial_package=p,
        company_document_review={'status':'passed','issues':[],'report_sha256':report_hash(report)},
        company_assessment_package={'dimensions':[{'id':'revenue','score':None}]})
    return project,report


def test_unknown_score_can_be_disclosed_but_required_score_and_stale_text_block_delivery():
    project,text=good_contract_project();assert assess_delivery(project,text)['status']=='passed'
    project.company_research_intake={'scoring_required':True}
    assert '委托要求完整评分' in '；'.join(assess_delivery(project,text)['errors'])
    project.company_research_intake={}
    assert assess_delivery(project,text+'改写内容。')['status']=='needs_repair'
    project.company_editorial_package['findings'][0]['text']='被偷偷替换的段落。'
    assert '实际精编段落' not in '；'.join(assess_delivery(project,text)['errors'])
    assert '丢失或被改写' in '；'.join(assess_delivery(project,text)['errors'])


def test_only_successful_content_integrity_render_and_layout_can_mark_ready():
    project,text=good_contract_project();c=assess_delivery(project,text)
    m={'docx_integrity_status':'passed','docx_layout_status':'passed'}
    assert finalize_export(m,c,{'docx_render_status':'passed'})['company_delivery_contract']['delivery_ready']
    assert not finalize_export(m,c,{'docx_render_status':'unavailable'})['company_delivery_contract']['delivery_ready']
    assert finalize_export({**m,'quality_warning':'旧闸门发现内容问题'},c,{'docx_render_status':'passed'})['delivery_status']=='review_draft'
    assert finalize_export({},c,{'docx_render_status':'passed'})['delivery_status']=='review_draft'


def test_core_requirements_do_not_relax_for_small_or_unlisted_companies():
    assert delivery_requirements({})['required_chapters']==[2,6]
    assert delivery_requirements({'required_chapters':[9,10,'12','bogus']})['required_chapters']==[2,6,9,10,12]


def test_precise_numeric_and_currency_information_must_survive_synthesis():
    from report_agents.company_editorial import prose_errors
    rows=[record(text='The company reported revenue of $10.00 million and a decline of 2%.')]
    assert 'new_or_changed_currency_scale' in prose_errors('The company reported revenue of $10.00 billion.',rows)
    findings,_=parse_proposal({'findings':[{'finding_id':'x','text':'The company reported revenue of $10.00 million.','information_ids':['I-a']}]},rows,6,OUTLINE[5][1][0])
    qa=audit(rows,findings)
    assert 'lost_numeric_information:I-a' in validate_audit(rows,findings,qa)


def test_review_must_visit_all_native_propositions_even_when_model_says_retained():
    rows=[record(text='公司披露已完成本期产品交付。另有下一期产线扩建计划尚未落地。')]
    findings,_=parse_proposal(proposal(rows),rows,6,OUTLINE[5][1][0]);qa=audit(rows,findings)
    qa['information'][0]['spans'][0]['source_excerpt']='公司披露已完成本期产品交付。'
    assert 'unreviewed_native_proposition:I-a' in validate_audit(rows,findings,qa)


def test_gaps_are_specific_and_do_not_clear_unknown_ids_or_failed_calculations():
    from report_agents.company_delivery_contract import fill_evidence_gaps,diagnostic_requires_review
    project,text=good_contract_project();sections=fill_evidence_gaps({2:text.split('\n\n')[0],6:text.split('\n\n')[1]},project.company_editorial_package,OUTLINE)
    report='\n\n'.join(sections[n] for n in sorted(sections))
    project.company_document_review={'status':'passed','issues':[],'report_sha256':report_hash(report)}
    project.company_delivery_contract=assess_delivery(project,report)
    project.company_people_diagnostic={'degraded':True,'errors':['第八章尚无可核对的文化与人员记录']}
    assert not diagnostic_requires_review(project,'people',report)
    project.company_people_diagnostic['errors'].append('第八章存在未知证据编号')
    assert diagnostic_requires_review(project,'people',report)
    assert '分岗位离职人数' in sections[8] and '分母' in sections[8] and '流失情况' in sections[8]


def test_core_evidence_gap_triggers_specific_bounded_retrieval_only_once(monkeypatch):
    from research_workflow import ResearchWorkflow
    workflow=ResearchWorkflow.__new__(ResearchWorkflow);calls=[]
    workflow.collect_web_sources=lambda *a,**kw:calls.append((a,kw)) or 1
    db=SimpleNamespace(expire=lambda *a:None,rollback=lambda:None)
    project=SimpleNamespace(target_name='远帆物流有限公司',sources=[])
    contract={'repair_tasks':[{'chapter':6,'question':'确认目标公司具体产品、服务及实际经营状态'}]}
    assert workflow._collect_company_delivery_repair(db,project,{'ai_search_enabled':True,'as_of_date':'2026-10-23'},contract)==1
    assert len(calls)==1
    repair=calls[0][1]['intake'];assert repair['max_search_rounds']==1
    assert len(repair['company_delivery_repair_queries'])==1 and '远帆物流' in repair['search_queries'][0]
    assert workflow._collect_company_delivery_repair(db,project,{'ai_search_enabled':True},{'repair_tasks':[]})==0
    assert len(calls)==1


def test_final_workflow_review_is_bound_to_actual_report_and_uses_no_case_names(monkeypatch):
    from research_workflow import ResearchWorkflow
    workflow=ResearchWorkflow.__new__(ResearchWorkflow);project,text=good_contract_project()
    monkeypatch.setattr(workflow,'_invoke_company_report_editor',lambda *a,**kw:json.dumps({'status':'pass','issues':[]}))
    result,meta=workflow._prepare_company_delivery(project,text)
    assert text in result and meta['company_delivery_contract']['status']=='passed'
    assert meta['company_document_review']['report_sha256']==report_hash(result)
    assert assess_delivery(project,result+'\n额外未经审核的结论。')['status']=='needs_repair'


def test_export_rejects_missing_chapter_or_lost_body_text():
    from docx_exporter import markdown_to_docx_bytes
    from report_agents.company_delivery_contract import validate_docx
    report='\n\n'.join(f'## {n}. {title}\n\n具体正文内容必须完整保留以便阅读和核对。' for n,(title,_) in enumerate(OUTLINE,1))
    data=markdown_to_docx_bytes(report,title='公司交付检查',outline=OUTLINE)
    assert validate_docx(data,report,OUTLINE)['docx_integrity_status']=='passed',validate_docx(data,report,OUTLINE)
    assert validate_docx(data,report.replace('具体正文内容必须完整保留以便阅读和核对。','被错误替换的新段落不得悄悄进入交付文件。'),OUTLINE)['docx_integrity_status']=='failed'
    assert validate_docx(b'bad bytes',report,OUTLINE)['docx_integrity_status']=='failed'


def test_english_originals_have_topic_routing_without_publisher_or_scope_upgrade():
    from report_agents.company_corpus import prepare_corpus
    raw='Northstar Devices Ltd (NASDAQ: NSTD) provides medical devices and reported revenue growth.\n\nNorthstar Devices offers monitoring products to hospital customers.'
    source={'id':1,'url':'https://devices.test/release','title':'Northstar Devices Ltd quarterly statement','content':raw,'source_metadata':{'fetch_status':'done','content_kind':'primary_page'}}
    project=SimpleNamespace(target_name='Northstar Devices Ltd',sources=[source],company_research_intake={})
    docs,states,_=prepare_corpus(project,{'facts':[]})
    assert docs and any(6 in w['candidate_chapters'] for d in docs for w in d['windows'])
    assert states['1']['source_kind']=='attributed_publication'
    assert 'Northstar Devices' in docs[0]['subject_binding']['disclosed_aliases']


def test_calendar_translation_is_not_changed_measurement_or_currency():
    from report_agents.company_editorial import numeric_tokens,prose_errors
    assert numeric_tokens('September 1, 2026; quarter Q2 ended July 31, 2026')==numeric_tokens('2026年9月1日；第二季度截至2026年7月31日')
    assert numeric_tokens('second quarter fiscal year 2027')==numeric_tokens('2027财年第二季度')
    assert numeric_tokens('超过800 亿元')==numeric_tokens('超过800亿元')
    assert prose_errors('原站披露50亿元。',[record(text='原站披露50亿美元。')])


def test_json_formatting_is_repaired_without_skipping_semantic_audit():
    from report_agents.company_editorial import parse_json_response
    assert parse_json_response('JSON\n{"x":1}')=={'x':1}
    rows=[record()];base=invoke_for(rows);calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        if role=='公司交付正文编写':return '{not JSON}'
        if role=='公司交付正文编写格式修复':return json.dumps(proposal(rows))
        return base(role,prompt,trace)
    package=build_editorial_package({'records':rows},OUTLINE,'公司',invoke,workers=1)
    assert package['diagnostic']['pending_information_ids']==[]
    assert '公司交付正文编写格式修复' in calls and '公司交付正文独立审稿' in calls


def test_short_zero_field_stays_semantically_verifiable():
    from report_agents.company_editorial import bind_proposition_spans,native_propositions
    row=record(text='0',field='参保人数',value='0');rows=[row]
    findings,_=parse_proposal({'findings':[{'finding_id':'x','text':'平台参保人数原字段为0，不直接代表在岗员工人数。','information_ids':['I-a']}]},rows,8,OUTLINE[7][1][0])
    qa=audit(rows,findings);qa['information'][0]['spans']=[{'proposition_id':native_propositions(row)[0]['proposition_id'],
        'finding_id':'x','output_excerpt':findings[0]['text']}]
    assert not validate_audit(rows,findings,bind_proposition_spans(rows,qa))


def test_short_speaker_header_is_recovered_as_one_contiguous_native_quote():
    from report_agents.company_corpus import _attributed_speech_spans
    raw='公司公告。\n\n目标公司董事长王甲表示：\n\n“本期已经交付新产品，但下一期产线扩建仍处于计划阶段。后续将按公告披露执行情况。”'
    spans=list(_attributed_speech_spans(raw));assert len(spans)==1
    offset,quote=spans[0];assert raw[offset:offset+len(quote)]==quote
    assert quote.startswith('目标公司董事长王甲表示') and '仍处于计划阶段' in quote


def test_required_scoring_is_preserved_from_explicit_request_and_negation():
    assert delivery_requirements({'special_requirements':'本次要求给出完整六维评分，不得留空。'})['scoring_required']
    assert not delivery_requirements({'special_requirements':'本次不需要评分，只做经营资料核查。'})['scoring_required']
    assert not delivery_requirements({'special_requirements':'要求完整评分。','scoring_required':False})['scoring_required']


def test_recovered_native_sources_are_indexed_even_if_cleaning_is_empty():
    from research_workflow import ResearchWorkflow
    workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    target='远帆物流有限公司';url='https://logistics.test/original';eid=workflow._stable_evidence_id(url,'原始披露')
    fact={'source_url':url,'source_title':'原始披露','fact':target+'披露具体物流产品及已交付服务。',
          'evidence_id':eid,'evidence_ids':[eid],'evidence_scope':'target_direct','chapter':6}
    project=SimpleNamespace(target_name=target,target_type='company',sources=[],company_source_review_package={'facts':[fact]})
    text='## 6. 主营业务\n具体交付披露。['+eid+']\n\n## 13. 信息来源\n\n## 14. 后续研究建议'
    result=workflow._append_report_evidence_index(project,text,'{"facts":[]}')
    assert url in result and '已纳入章节证据包的唯一来源：1' in result


def test_final_editorial_receipts_are_rechecked_instead_of_trusting_green_counts():
    project,text=good_contract_project()
    project.company_editorial_package['batches'][0]['audit']['information'][0]['spans']=[]
    result=assess_delivery(project,text)
    assert result['status']=='needs_repair' and any('回执复验未通过' in e for e in result['errors'])


def test_future_parser_context_fields_are_not_erased_by_a_fixed_dedup_whitelist():
    a={'statement_id':'a','chapter':6,'text':'项目结果相同文字','context':{'trial_phase':'phase 1'}}
    b={'statement_id':'b','chapter':6,'text':'项目结果相同文字','context':{'trial_phase':'phase 2'}}
    assert len(information_records([a,b]))==2


def test_unknown_dates_cannot_create_a_same_period_numeric_conflict():
    a=record(field='收入',value='10.00',unit='万元',period='原字段数据基准日未载')
    b=record('I-b',field='收入',value='12.00',unit='万元',period='原字段数据基准日未载')
    assert comparable_conflicts([a,b])==[]


def test_support_id_repair_requires_real_semantic_representation_of_both_sources():
    a=record('I-a','原站披露该金额超过100.00元。')
    b=record('I-b','原站另披露该金额为101.00元。')
    rows=[a,b];text=a['text']+b['text'];calls=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        if role=='公司交付正文编写':return json.dumps({'findings':[{'finding_id':'x','text':text,'information_ids':['I-a']}]})
        if role=='公司交付引用归属修复':return json.dumps({'assignments':[{'finding_id':'x','information_ids':['I-a','I-b'],'reason':'正文同时保留两条原值，不能只引用第一条。'}]})
        data=json.loads(prompt.split('资料：\n',1)[1]);return json.dumps(audit(rows,data['findings']))
    result=build_editorial_package({'records':rows},OUTLINE,'公司',invoke,workers=1)
    assert result['diagnostic']['narrative_information']==2 and not result['diagnostic']['pending_information_ids']
    assert result['findings'][0]['text']==text and result['batches'][0]['attempts'][0]['support_repair']
    assert '公司交付正文独立审稿' in calls


def test_question_specific_followup_separates_incentives_and_organization():
    from report_agents.company_delivery_contract import question_materials,followup_chapter
    assert '授予' in question_materials(4,'内部激励')
    assert '部门' in question_materials(4,'组织架构合理性')
    project,_=good_contract_project();text=followup_chapter(project,OUTLINE)
    assert '未来' not in text or '本轮未开展' in text
    assert '原权重未载' in text and '不能计算' in text
    assert '每章最多' not in text


def test_equal_quantity_spelling_is_restored_without_changing_values_or_currency():
    from report_agents.company_editorial import restore_native_notation
    row=record(text='The publisher states more than 50 million registered users.')
    p={'findings':[{'finding_id':'x','text':'发布者称注册用户超过5000万。','information_ids':['I-a']}]}
    changes=restore_native_notation(p,[row])
    assert changes and p['findings'][0]['text']=='发布者称注册用户超过50 million。'
    assert changes[0]['exact_decimal']=='50000000'
    for original,generated in [('公司披露100万元。','公司披露101万元。'),('公司披露10亿美元。','公司披露100000万元。')]:
        p={'findings':[{'finding_id':'x','text':generated,'information_ids':['I-a']}]}
        assert not restore_native_notation(p,[record(text=original)])
        assert p['findings'][0]['text']==generated


def test_notation_restoration_preserves_surrounding_spaces_and_long_precision():
    from report_agents.company_editorial import restore_native_notation
    row=record(text='More than 50 million users.')
    p={'findings':[{'finding_id':'x','text':'More than 5000万 users.','information_ids':['I-a']}]}
    restore_native_notation(p,[row]);assert p['findings'][0]['text']=='More than 50 million users.'
    a='123456789012345678901234567890.123456789'
    row=record(text='USD'+a+' million.')
    p={'findings':[{'finding_id':'x','text':'USD123456789012345678901234567890.123456788 million.','information_ids':['I-a']}]}
    assert not restore_native_notation(p,[row])


def test_export_requires_native_citation_targets_and_exact_zero_table_cells():
    import io,zipfile
    from xml.etree import ElementTree as ET
    from docx_exporter import markdown_to_docx_bytes
    from report_agents.company_delivery_contract import validate_docx
    report='\n\n'.join(f'## {n}. {title}'+('（自动生成审计索引）' if n==13 else '')+'\n\n具体正文内容必须完整保留以便阅读和核对。'+
        ('[E-123456ABCDEF]\n\n| 字段 | 原值 | 来源 |\n| --- | --- | --- |\n| 在册人数 | 0 | [E-123456ABCDEF] |' if n==6 else '')+
        ('\n\n| 证据编号 | 原件 |\n| --- | --- |\n| E-123456ABCDEF | 原始网页 |' if n==13 else '')
        for n,(title,_) in enumerate(OUTLINE,1))
    data=markdown_to_docx_bytes(report,outline=OUTLINE)
    assert validate_docx(data,report,OUTLINE)['docx_integrity_status']=='passed',validate_docx(data,report,OUTLINE)
    def edit_docx(change):
        original=zipfile.ZipFile(io.BytesIO(data));root=ET.fromstring(original.read('word/document.xml'))
        change(root);out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as result:
            for name in original.namelist():result.writestr(name,ET.tostring(root) if name=='word/document.xml' else original.read(name))
        return validate_docx(out.getvalue(),report,OUTLINE)
    w='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    def remove_native_links(root):
        for parent in root.iter():
            for child in list(parent):
                if child.tag==w+'hyperlink' and (child.get(w+'anchor') or '').startswith('evidence_'):
                    parent.remove(child)
    assert 'docx_missing_native_citation_links' in edit_docx(remove_native_links)['docx_integrity_errors']
    def change_zero(root):
        for text in root.iter(w+'t'):
            if text.text=='0':text.text='1000'
    assert 'docx_table_row_changed:6' in edit_docx(change_zero)['docx_integrity_errors']


def test_excluded_original_cannot_reappear_in_body_as_an_accepted_claim():
    project,text=good_contract_project()
    excluded=record('I-excluded','另一个主体的争议记录不适用于本次研究目标。',chapter=9)
    excluded['decision']['status']='exclude'
    project.company_information_usage_package['records'].append(excluded)
    text+='\n\n## 9. 司法\n\n'+excluded['text']+'[E-123456ABCDEF]'
    project.company_document_review['report_sha256']=report_hash(text)
    assert any('排除清单与实际正文出现冲突' in e for e in assess_delivery(project,text)['errors'])


def test_save_entry_point_rechecks_content_even_with_green_export_and_cached_contract(monkeypatch):
    from unittest.mock import Mock
    import research_workflow,report_knowledge
    from research_workflow import ResearchWorkflow
    from report_agents import company_delivery_contract as contract
    project,text=good_contract_project();project.id=1;project.target_type='company';project.title='公司研究';project.industry=''
    project.company_delivery_contract=assess_delivery(project,text)
    workflow=ResearchWorkflow.__new__(ResearchWorkflow);database=Mock()
    database.query.return_value.filter.return_value.order_by.return_value.first.return_value=None
    monkeypatch.setattr(research_workflow.research_store,'put_text',lambda *a,**kw:'text/key')
    monkeypatch.setattr(research_workflow.research_store,'put_bytes',lambda *a,**kw:'bytes/key')
    monkeypatch.setattr(report_knowledge,'sync_report_safely',lambda *a:None)
    monkeypatch.setattr(contract,'validate_docx',lambda *a:{'docx_integrity_status':'passed'})
    monkeypatch.setattr(contract,'audit_pdf_layout',lambda *a:{'docx_layout_status':'passed'})
    monkeypatch.setattr(workflow,'_select_report_outline',lambda *a:OUTLINE)
    monkeypatch.setattr(workflow,'_render_docx_quality',lambda *a:({'docx_render_status':'passed'},b'%PDF-test'))
    def reject(*a):raise RuntimeError('原件引用定位失败')
    monkeypatch.setattr(workflow,'_validate_delivery_report',reject)
    artifact=workflow.save_artifact(database,project,'desktop_report','公司研究',text)
    meta=artifact.artifact_metadata
    assert meta['delivery_status']=='review_draft' and not meta['company_delivery_contract']['delivery_ready'],meta
    assert '原件引用定位失败' in meta['quality_warning']


def test_gap_plans_do_not_turn_structure_labels_into_company_events():
    from report_agents.company_delivery_contract import fill_evidence_gaps,followup_chapter,question_plan
    project,_=good_contract_project()
    sections=fill_evidence_gaps({12:'## 12. 综合评价\n原锚点及未评分原因'},project.company_editorial_package,OUTLINE)
    assert sections[12]=='## 12. 综合评价\n原锚点及未评分原因'
    followup=followup_chapter(project,OUTLINE)
    for label in ('本章待核验事项','视觉/图谱证据说明','核验判断与具体缺口'):
        assert '| '+label+' |' not in sections[7] and label not in followup
    assert '分部门业务运营数据核验表' not in followup
    assert '分部附注' in question_plan(6,'分部门业务运营数据核验表')['action']
    assert question_plan(4,'内部激励')['action']!=question_plan(4,'组织架构合理性')['action']


def test_bounded_unscored_assessment_requires_every_original_reason_and_anchor():
    from report_agents.company_assessment import build_assessment_package,render_assessment
    from report_agents.company_delivery_contract import diagnostic_requires_review
    project,_=good_contract_project()
    p=build_assessment_package({'facts':[]},project.target_name,intake={'as_of_date':'2026-10-23'})
    text=render_assessment(p);project.company_assessment_package=p
    project.company_assessment_diagnostic={'degraded':True,'errors':['尚无可按原件和锚点评价的公司分项，需人工复核']}
    project.company_delivery_contract={'status':'passed'}
    project.company_document_review={'status':'passed','report_sha256':report_hash(text)}
    assert not diagnostic_requires_review(project,'assessment',text)
    changed=text.replace(p['dimensions'][0]['anchors'],'')
    project.company_document_review['report_sha256']=report_hash(changed)
    assert diagnostic_requires_review(project,'assessment',changed)


def test_gap_repair_is_idempotent_and_empty_score_reasons_do_not_claim_records_exist():
    from report_agents.company_delivery_contract import fill_evidence_gaps
    from report_agents.company_assessment import build_assessment_package,render_assessment
    p=build_assessment_package({'facts':[]},'远帆物流有限公司',intake={'as_of_date':'2026-10-23'})
    text=render_assessment(p)
    assert '已得项目' not in text and '已有岗位/任职' not in text
    assert '各指标数据期另列' not in text
    assert '补证与核验动作' in text and '分母' not in p['dimensions'][0]['reason']
    once=fill_evidence_gaps({11:'## 11. 风险核查\n完整核查目录'}, {'findings':[]},OUTLINE)
    twice=fill_evidence_gaps(once,{'findings':[]},OUTLINE)
    assert once==twice and twice[11].count('### 公开资料判断条件')==1


def test_gap_feedback_does_not_rewrite_accepted_facts_in_the_same_chapter(monkeypatch):
    import report_agents.company_editorial as editor
    from research_workflow import ResearchWorkflow
    project,text=good_contract_project();workflow=ResearchWorkflow.__new__(ResearchWorkflow)
    calls=[]
    def review(*args,**kwargs):
        calls.append('review')
        return {'status':'passed' if len(calls)>1 else 'failed',
            'issues':[] if len(calls)>1 else [{'chapter':2,'quote':'待核查的股东记录','message':'核验动作不具体'}]}
    monkeypatch.setattr(editor,'document_review',review)
    monkeypatch.setattr(editor,'build_editorial_package',lambda *a,**kw:pytest.fail('Gap feedback must not rewrite accepted source facts'))
    monkeypatch.setattr(workflow,'_append_report_evidence_index',lambda project,report,*a,**kw:report)
    result,meta=workflow._prepare_company_delivery(project,text)
    assert len(calls)==2 and meta['company_delivery_contract']['status']=='passed'
    assert all(f['text'] in result for f in project.company_editorial_package['findings'])


def test_failed_model_review_keeps_native_fields_in_a_blocked_draft():
    from report_agents.company_delivery_contract import fill_evidence_gaps
    original='## 2. 主体\n\n| 注册资本 | 100万元 | [E-123456ABCDEF] |'
    usage={'records':[{'information_id':'I-a','chapters':[2],'decision':{'status':'pending'}}]}
    result=fill_evidence_gaps({2:original},{'findings':[]},OUTLINE,usage=usage)
    assert original in result[2] and '正文核对尚未完成' in result[2]
    assert '本轮已接纳原文尚不足' not in result[2]


def test_undeclared_industry_keeps_sector_checks_pending_rather_than_excluded():
    from report_agents.company_risk_register import build_risk_register,render_risk_register
    p=build_risk_register({'facts':[]},'Northstar Devices Ltd',industry='')
    states=p['diagnostic']['checklist_states']
    assert states['requires_sector_confirmation']>0 and not states.get('outside_declared_sector_scope')
    assert sum(states.values())==75 and len(p['checklist'])==75
    text=render_risk_register(p)
    assert '行业适用范围待确认' in text and '合计75项' in text


def test_native_asterisk_footnotes_and_single_underscores_survive_export_validation():
    from docx_exporter import markdown_to_docx_bytes
    from report_agents.company_delivery_contract import validate_docx
    prose='All-Remote-Northstar Devices Ltd发布者称约50%的财富100强*使用API_V2服务，星号口径需按原始脚注理解。'
    text='\n\n'.join(f'## {n}. {title}\n\n'+prose for n,(title,_) in enumerate(OUTLINE,1))
    payload=markdown_to_docx_bytes(text,outline=OUTLINE)
    assert validate_docx(payload,text,OUTLINE)['docx_integrity_status']=='passed'
    assert validate_docx(payload,text.replace('API_V2','APIV2'),OUTLINE)['docx_integrity_status']=='failed'


def test_pdf_checks_allow_page_field_updates_but_still_require_native_zero(monkeypatch):
    import io,zipfile,pdfplumber
    from report_agents.company_delivery_contract import audit_pdf_layout
    w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    xml=f'<w:document xmlns:w="{w}"><w:body><w:p><w:r><w:t>native 0</w:t></w:r><w:fldSimple w:instr=" PAGEREF chapter_1 "><w:r><w:t>—</w:t></w:r></w:fldSimple></w:p></w:body></w:document>'
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:z.writestr('word/document.xml',xml)
    class PDF:
        def __init__(self,text):
            self.pages=[SimpleNamespace(width=600,height=800,images=[],
                chars=[{'text':c,'x0':20+i*8,'x1':27+i*8,'top':20,'bottom':30} for i,c in enumerate(text)],
                extract_text=lambda:text)]
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(pdfplumber,'open',lambda *a:PDF('native 0 7'))
    assert audit_pdf_layout(b'pdf',out.getvalue())['docx_layout_status']=='passed'
    monkeypatch.setattr(pdfplumber,'open',lambda *a:PDF('native 7'))
    assert 'docx_text_missing_from_rendered_pdf' in audit_pdf_layout(b'pdf',out.getvalue())['docx_layout_errors']
