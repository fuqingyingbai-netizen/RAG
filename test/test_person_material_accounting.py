import json
import pytest
from person_material_accounting import diagnose_material,build_accounting,delivery_gate
from person_content_acceptance import accept_content
from person_evidence import build_packages,validate_model_claims
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


def test_three_hundred_distinct_records_are_all_diagnosed_and_retained_in_delivery_annex():
    facts=[{'evidence_id':f'E-TEST{i:04d}','fact':f'林知远负责研发事项{i}，该事项结果仍待核实。',
        'subject':'林知远','subject_scope':'person','analysis_allowed':True,'source_url':f'https://fixture.invalid/{i}',
        'claim_type':'person_platform_record','provider':'qcc'} for i in range(300)]
    p={'chapter':4,'title':'战略与执行','facts':facts,'research_facts':facts};seen=[]
    def invoke(role,prompt,*a):
        data=json.loads(prompt.splitlines()[-1]);seen.extend(f['evidence_id'] for f in data['facts'])
        return json.dumps({'material_reviews':[{'evidence_id':f['evidence_id'],'disposition':'appendix',
            'reason':f"{f['original']}属于研发项目的具体待核细节，作为完整原始补充记录。"} for f in data['facts']]})
    d=diagnose_material(p,[],invoke,None)
    assert d['status']=='passed' and len(seen)==len(set(seen))==300
    contract={'facts':facts,'chapters':{4:p}}
    accounting,annex=build_accounting('## 4. 战略与执行\n尚未作个人能力判断。',contract,{4:{'content_acceptance':{'material_diagnosis':d}}})
    assert accounting['admitted_records']==accounting['professional_records_in_appendix']==300
    assert accounting['dispositions']=={'supporting_appendix':300}
    assert not accounting['unaccounted_evidence_ids']
    assert all(f['fact'] in annex and f['evidence_id'] in annex for f in facts)


def test_length_alone_cannot_justify_putting_a_material_item_in_appendix():
    f={'evidence_id':'E-TEST0001','fact':'董事会选举林知远任董事长，任期三年。','analysis_allowed':True}
    p={'chapter':5,'title':'管理','facts':[f]};calls=[]
    def invoke(*a):
        calls.append(a)
        return json.dumps({'material_reviews':[{'evidence_id':f['evidence_id'],'disposition':'appendix','reason':'篇幅字数不够'}]})
    d=diagnose_material(p,[],invoke,None)
    assert len(calls)==2 and d['status']=='pending' and d['counts']=={'pending':1}


def test_first_report_without_prior_draft_repairs_an_uncovered_material_fact():
    data={'facts':[{'fact':'董事会于2024年选举陈雨安任董事长，任期三年。','source_url':'https://fixture.invalid/appointment','identity_match':'confirmed'}]}
    p=build_packages(data,'陈雨安',PERSON_REPORT_OUTLINE)['chapters'][5]
    p.update(writing_contract='evidence_selection_v2',require_material_dispositions=True)
    f=p['research_facts'][0];old={'analysis':'来源载董事会于2024年选举陈雨安任董事长，任期三年。','evidence_ids':[f['evidence_id']]}
    def invoke(role,prompt,*a):
        packet=json.loads(prompt.splitlines()[-1])
        if '材料采用诊断' in role:
            row={'evidence_id':f['evidence_id'],'reason':'任命及任期须保留'}
            row.update({'disposition':'analysis','matched_claim_indices':[0]} if packet['draft'] else
                       {'disposition':'missing','required_quote':f['fact']})
            return json.dumps({'material_reviews':[row]})
        if '事项覆盖验收' in role:
            return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered' if packet['draft'] else 'missing',
                'matched_claim_indices':[0] if packet['draft'] else [],'gaps':[] if packet['draft'] else
                [{'prior_quote':f['fact'],'evidence_ids':[f['evidence_id']]}]}]})
        if '事项定向补写' in role:return json.dumps({'claims':[old]})
        if '语义复核' in role:return json.dumps({'reviews':[{'claim_index':0,'verdict':'supported','supporting_evidence_ids':[f['evidence_id']]}]})
        raise AssertionError(role)
    result,issues,audit=accept_content(p,[],[],{'chapter':5,'facts':p['research_facts']},invoke,None,validate_model_claims)
    assert not issues and result[0]['analysis']==old['analysis']
    assert audit['material_diagnosis']['status']=='passed' and audit['stop_reason']=='accepted'


def test_source_validated_candidate_can_advance_to_second_targeted_repair(monkeypatch):
    from test_person_content_acceptance import fixture
    p,prior,claims=fixture();revisions=[]
    def invoke(role,prompt,*a):
        data=json.loads(prompt.splitlines()[-1])
        if '事项定向补写' in role:
            revisions.append(data)
            return json.dumps({'claims':[claims[0] if len(revisions)==1 else prior[0]]})
        if '语义复核' in role:return json.dumps({'reviews':[{'claim_index':0,'verdict':'supported','supporting_evidence_ids':prior[0]['evidence_ids']}]})
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[0],'gaps':[]}]})
    result,issues,audit=accept_content(p,claims,prior,{'chapter':5,'facts':p['research_facts']},invoke,None,validate_model_claims)
    assert not issues and len(revisions)==2 and len(audit['rounds'])==2
    assert result[1]['analysis']==claims[1]['analysis']
    assert revisions[1]['previous_repair_diagnostics']


def test_explicit_semantic_failure_is_fed_back_into_the_next_targeted_revision():
    from test_person_content_acceptance import fixture
    p,prior,claims=fixture();revisions=[];reviews=[]
    def invoke(role,prompt,*a):
        data=json.loads(prompt.splitlines()[-1])
        if '事项定向补写' in role:
            revisions.append(data)
            text='2018年来源载林知远任董事长及总裁，两职任期三年，并通过家族协作取得关键资源。' if len(revisions)==1 else prior[0]['analysis']
            return json.dumps({'claims':[{'analysis':text,'evidence_ids':prior[0]['evidence_ids']}]})
        if '语义复核' in role:
            reviews.append(data)
            return json.dumps({'reviews':[{'claim_index':0,'verdict':'unsupported' if len(reviews)==1 else 'supported',
                'issues':['unsupported_new_fact'] if len(reviews)==1 else [],'reason':'原文没有家族协作取得资源。' if len(reviews)==1 else '任期与原文一致。',
                'supporting_evidence_ids':prior[0]['evidence_ids']}]})
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[0],'gaps':[]}]})
    result,issues,audit=accept_content(p,claims,prior,{'chapter':5,'facts':p['research_facts']},invoke,None,validate_model_claims)
    assert not issues and len(revisions)==2 and result[1]['analysis']==claims[1]['analysis']
    assert revisions[1]['previous_repair_diagnostics'][0]['repair_semantic_review']


def test_missing_material_diagnosis_never_passes_even_without_prior_draft():
    p={'chapter':5,'title':'管理','facts':[{'evidence_id':'E-TEST0001','fact':'聘任陈雨安为总裁。','analysis_allowed':True}],
       'require_material_dispositions':True}
    result,issues,audit=accept_content(p,[],[],{'facts':p['facts']},lambda *a:'',None,validate_model_claims)
    assert issues==['material_disposition_review_incomplete'] and audit['status']=='pending_delivery'
    assert audit['stop_reason']=='review_or_provider_unavailable'


def test_missing_record_question_does_not_require_a_model_to_retype_a_fact():
    f={'evidence_id':'E-TEST0001','fact':'董事会于2024年聘任陈雨安为总裁。','analysis_allowed':True}
    p={'chapter':5,'title':'管理','facts':[f]}
    reply={'material_reviews':[{'evidence_id':f['evidence_id'],'disposition':'missing','reason':'本条任命事项尚未在正文保留。',
        'required_quote':'错误改述并非原句，不能用于事实。'}]}
    a=diagnose_material(p,[],lambda *a:json.dumps(reply),None)
    assert a['status']=='missing' and not a['requirements']
    assert a['questions'][0]['material_evidence_ids']==[f['evidence_id']]
    assert a['questions'][0]['planning_only_not_evidence']
    assert not p.get('required_source_displays')


def test_shared_writing_cards_keep_every_original_and_scope_without_duplicating_proof_text():
    from person_material_review import writing_cards
    text='陈雨安曾担任远山科技研发负责人，并在董事会任命后负责该公司研发团队。'*20
    facts=[{'evidence_id':'E-TEST0001','fact':text,'evidence_quote':text,'subject_scope':'affiliated_company','analysis_allowed':False,
        'source_url':'https://fixture.invalid/filing','observation':{'source_events':[{'kind':'appointment','date_literal':'2024年','source_quote':text}],
        'metrics':[{'metric':'test','value':1,'source_quote':text}], 'role_date_fields':[{'field':'开始时间','source_value':'2024年'}]}}]
    cards=writing_cards(facts)
    assert len(cards)==len(facts) and cards[0]['fact']==text
    assert cards[0]['evidence_id']==facts[0]['evidence_id'] and not cards[0]['personal_analysis_allowed']
    assert cards[0]['subject_scope']=='affiliated_company'
    assert cards[0]['role_dates'][0]['source_value']=='2024年'
    assert 'source_quote' not in cards[0]['source_events'][0]
    assert len(json.dumps(cards,ensure_ascii=False))<len(json.dumps(facts,ensure_ascii=False))/2


def test_qualified_judicial_rows_can_complete_the_deterministic_risk_chapter_without_inventing_analysis():
    from types import SimpleNamespace
    from person_evidence import generate_person_report,split_sections
    row={'fact':'陈雨安；平台所列裁判文书；{"案号":"（2025）测试001号","当事人角色":"原告","程序状态":"待核"}',
        'source_url':'structured://qcc/judicial','claim_type':'person_platform_record','person_chapters':[12],
        'identity_match':'confirmed','provider':'qcc'}
    p=SimpleNamespace(target_name='陈雨安',title='合成司法原字段验证',sources=[],person_research_intake={})
    def forbidden(*a,**kw):raise AssertionError('complete typed table needs no model inference')
    report=generate_person_report(p,json.dumps({'facts':[row]},ensure_ascii=False),'{}',PERSON_REPORT_OUTLINE,forbidden,lambda *a,**kw:None)
    chapter=split_sections(report)[12]
    assert '原告' in chapter and '（2025）测试001号' in chapter and '不评分' in chapter
    audit=p.person_delivery_diagnostic['section_diagnostics'][12]['content_acceptance']
    assert audit['status'].startswith('passed') and audit['material_diagnosis']['counts']=={'table':1}


@pytest.mark.parametrize('repetitions',[20,31])
def test_new_material_first_uses_available_space_while_preserving_accepted_content(repetitions):
    from test_person_content_acceptance import fixture
    p,_,base=fixture();p['require_material_dispositions']=True
    f={'evidence_id':'E-TEST0001','fact':'林知远于2024年获董事会授权审批研发项目。','source_url':'https://fixture.invalid/new',
        'subject_scope':'person','analysis_allowed':True}
    p['research_facts'].append(f)
    current=[base[0],{**base[1],'analysis':'来源记载林知远公开介绍工程师文化。'*repetitions}]
    assert 300<sum(len(c['analysis']) for c in current)<=600
    proposals=[]
    def invoke(role,prompt,*a):
        data=json.loads(prompt.splitlines()[-1])
        if '材料采用诊断' in role:
            out=[]
            for r in data['facts']:
                indices=[i for i,c in enumerate(data['draft']) if r['evidence_id'] in c['evidence_ids']]
                out.append({'evidence_id':r['evidence_id'],'disposition':'analysis' if indices else 'missing',
                    'matched_claim_indices':indices,'reason':'材料实质内容应在正文保留。'})
            return json.dumps({'material_reviews':out})
        if '事项定向补写' in role:
            proposals.append(data)
            assert data['locked_analyses']==current and not data['replace_draft']
            assert not data['prior_draft_analyses_not_evidence']
            return json.dumps({'claims':[{'analysis':f['fact'],'evidence_ids':[f['evidence_id']]}]})
        if '语义复核' in role:
            return json.dumps({'reviews':[{'claim_index':i,'verdict':'supported','supporting_evidence_ids':c['evidence_ids']}
                for i,c in enumerate(data['claims'])]})
        old=data['prior'][0]
        index=1 if old['evidence_ids']==base[1]['evidence_ids'] else 0
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[index],'gaps':[]}]})
    result,issues,audit=accept_content(p,current,[],{'chapter':5,'facts':p['research_facts']},invoke,None,validate_model_claims)
    assert not issues and len(proposals)==1
    assert not audit.get('compaction_reason')
    assert [r['analysis'] for r in result[:2]]==[r['analysis'] for r in current]
    assert sum(len(c['analysis']) for c in result)<=600
    assert not audit['final_review']['items']


def test_context_only_material_is_displayed_as_an_attributed_literal_without_personal_inference():
    from person_material_review import presentation_facts
    f={'evidence_id':'E-TEST0001','fact':'陈雨安公开表示，工程师文化是团队继续研发的基础。','analysis_allowed':False,'source_url':'https://fixture.invalid/speech'}
    p={'chapter':5,'title':'管理','facts':[f]}
    reply={'material_reviews':[{'evidence_id':f['evidence_id'],'disposition':'missing',
        'reason':'这是其公开自述，应保留其来源立场。','required_quote':f['fact']}]}
    audit=diagnose_material(p,[],lambda *a:json.dumps(reply),None)
    assert audit['status']=='passed' and audit['counts']=={'source_display':1}
    assert not audit['requirements'] and not f['analysis_allowed']
    displayed=presentation_facts(p,[])
    assert displayed[0]['fact']==f['fact'] and not p['quotation_budget']['required_undisplayed_evidence_ids']


def test_material_quote_restores_source_layout_without_accepting_paraphrases():
    f={'evidence_id':'E-TEST0001','fact':'陈雨安先生，曾任远山科技\n研发负责人，董事会聘任其为总裁。','analysis_allowed':False,'source_url':'https://fixture.invalid/filing'}
    p={'chapter':5,'title':'管理','facts':[f]}
    reply={'material_reviews':[{'evidence_id':f['evidence_id'],'disposition':'source_display',
        'reason':'保留其在原披露中的历史职责与任命。','required_quote':'陈雨安先生，曾任远山科技研发负责人，董事会聘任其为总裁。'}]}
    audit=diagnose_material(p,[],lambda *a:json.dumps(reply),None)
    assert audit['status']=='passed' and audit['rows'][0]['quote_layout_restored']
    assert p['required_source_displays'][0]['quote']==f['fact']
    changed={**reply['material_reviews'][0],'required_quote':'陈雨安先生现任远山科技总裁，拥有最高决策权。'}
    audit=diagnose_material({**p,'required_source_displays':[]},[],lambda *a:json.dumps({'material_reviews':[changed]}),None)
    assert audit['status']=='pending'


def test_format_recovery_can_select_literal_source_segments_without_retyping_them():
    f={'evidence_id':'E-TEST0001','fact':'陈雨安曾任研发负责人；董事会于2024年聘任其为总裁。','analysis_allowed':False}
    p={'chapter':5,'title':'管理','facts':[f]};calls=[]
    def invoke(role,prompt,*a):
        calls.append(role);data=json.loads(prompt.splitlines()[-1])
        row={'evidence_id':f['evidence_id'],'disposition':'source_display','reason':'须保留职责及任命原句。'}
        if len(calls)==1:row['required_quote']='陈雨安现任最高研发决策人。'
        else:
            assert data['validation_errors'] and data['facts'][0]['source_segments']
            row['required_segment_ids']=[0,1]
        return json.dumps({'material_reviews':[row]})
    a=diagnose_material(p,[],invoke,None)
    assert len(calls)==2 and a['status']=='passed'
    assert a['rows'][0]['source_segment_ids_selected']
    assert ''.join(r['quote'] for r in p['required_source_displays'])==f['fact']


def test_required_source_quotes_get_priority_without_exceeding_quote_budget():
    from person_material_review import presentation_facts
    f={'evidence_id':'E-TEST0001','fact':'A'*1500,'source_url':'https://fixture.invalid/a'}
    g={'evidence_id':'E-TEST0002','fact':'B'*1000,'source_url':'https://fixture.invalid/b'}
    p={'chapter':5,'facts':[f,g],'required_source_displays':[{'evidence_id':g['evidence_id'],'quote':'B'*100}]}
    displayed=presentation_facts(p,[{'analysis':'A','evidence_ids':[f['evidence_id']]}])
    assert displayed[0]['evidence_id']==g['evidence_id'] and sum(len(x['fact']) for x in displayed)<=1600
    assert not p['quotation_budget']['required_undisplayed_evidence_ids']


def test_full_report_gate_cannot_be_passed_by_a_source_ledger_or_only_one_checked_chapter():
    p={'chapter':5,'title':'管理','facts':[],'research_facts':[{'evidence_id':'E-TEST0001','fact':'董事会聘任陈雨安为总裁。'}]}
    contract={'facts':p['research_facts'],'chapters':{5:p}}
    accounting={'appendix_record_count':1,'unaccounted_evidence_ids':[]}
    gate=delivery_gate('## 5. 管理\n已留存原始材料。',contract,{},accounting)
    assert gate['status']=='pending'
    assert any(r['code']=='material_or_content_review_pending' for r in gate['blockers'])


def test_full_report_includes_all_three_hundred_qualified_platform_rows_in_the_body_table():
    from types import SimpleNamespace
    from person_evidence import generate_person_report,split_sections,cited_ids
    from person_model_fixture import material_response
    rows=[{'fact':'陈雨安；查询定位机构：远山科技有限公司；平台所列记录；'+json.dumps(
        {'企业名称':f'远山项目{i}有限公司','职位':'董事','任职起止时间':'开始时间:2020-01-01,结束时间:[]'},ensure_ascii=False),
        'source_url':f'structured://qcc/positions/{i}','identity_match':'confirmed','claim_type':'person_platform_record',
        'provider':'qcc','person_chapters':[2,9]} for i in range(300)]
    project=SimpleNamespace(target_name='陈雨安',title='合成300条平台数据验证',sources=[],person_research_intake={})
    delivered=set()
    def invoke(role,prompt,*a):
        data=json.loads(prompt.splitlines()[-1])
        # Research delivery is distinct from repeated post-writing review.
        delivered.update(f['evidence_id'] for f in data.get('facts',[]) if 'evidence_id' in f)
        if '材料采用诊断' in role:
            if data['chapter']==9:
                return json.dumps({'material_reviews':[{'evidence_id':f['evidence_id'],'disposition':'table',
                    'reason':'平台任职原字段已在本章完整关联记录表展示。'} for f in data['facts']]})
            return material_response(data)
        return '{"claims":[]}'
    report=generate_person_report(project,json.dumps({'facts':rows},ensure_ascii=False),'{}',PERSON_REPORT_OUTLINE,invoke,lambda *a,**kw:None)
    body=split_sections(report)[9];accounting=project.person_delivery_diagnostic['material_accounting']
    assert len(project.person_evidence_contract['facts'])==len(delivered)==300
    assert all(f'远山项目{i}有限公司' in body for i in range(300))
    assert len(cited_ids(body))==300 and accounting['professional_records_in_body']==300
    assert accounting['appendix_record_count']==300
    assert '结束时间:[]' in body and '结束时间:[]' in project.person_evidence_appendix


def test_critical_factual_material_can_be_adopted_as_literal_body_text_without_new_personal_inference():
    from person_material_review import presentation_facts
    f={'evidence_id':'E-TEST0001','fact':'董事会于2024年选举陈雨安任董事长，任期三年。','analysis_allowed':True,
       'subject_scope':'person','source_url':'https://fixture.invalid/appointment'}
    p={'chapter':5,'title':'管理','facts':[f],'require_material_dispositions':True};writes=[]
    def invoke(role,prompt,*a):
        d=json.loads(prompt.splitlines()[-1])
        if '材料采用诊断' in role:
            row={'evidence_id':f['evidence_id'],'reason':'任命及三年任期属于本章主要事项。'}
            row.update({'disposition':'source_display'} if f['evidence_id'] in d['source_display_evidence_ids'] else
                       {'disposition':'missing','required_quote':f['fact']})
            return json.dumps({'material_reviews':[row]})
        writes.append(role);raise AssertionError('No inferred personal conclusion is needed for a literal appointment record')
    claims,issues,a=accept_content(p,[],[],{'chapter':5,'facts':[f]},invoke,None,validate_model_claims)
    assert not issues and not writes and not claims and a['status']=='passed_after_targeted_repair'
    assert a['material_diagnosis']['counts']=={'source_display':1}
    assert presentation_facts(p,claims)[0]['fact']==f['fact'] and p['quotation_budget']['displayed_chars']<=1600


def test_literal_display_proposal_cannot_use_a_fabricated_quote_or_hide_an_overflow():
    from person_material_accounting import propose_literal_displays
    facts=[{'evidence_id':f'E-TEST{i:04d}','fact':'不同来源实质记录'+str(i)+'。'*80} for i in range(2)]
    p={'facts':facts}
    d={'rows':[{'evidence_id':facts[0]['evidence_id'],'disposition':'missing','required_quote':'虚构原文'},
        {'evidence_id':facts[1]['evidence_id'],'disposition':'missing','required_quote':facts[1]['fact']}]}
    a=propose_literal_displays(p,d,max_chars=20)
    assert not a['added'] and len(a['skipped'])==2 and not p['required_source_displays']
    assert a['skipped'][1]['reason']=='quotation_budget_requires_other_representation_not_omission'


def test_material_resume_reuses_only_completed_decisions_from_the_identical_context():
    facts=[{'evidence_id':f'E-TEST{i:04d}','fact':f'陈雨安的补充历史记录{i}。','analysis_allowed':True} for i in range(17)]
    p={'chapter':5,'title':'管理','facts':facts};seen=[];fail=[True]
    def invoke(role,prompt,*a):
        d=json.loads(prompt.splitlines()[-1]);seen.extend(r['evidence_id'] for r in d['facts'])
        if fail[0] and any(r['evidence_id']==facts[-1]['evidence_id'] for r in d['facts']):return '{}'
        return json.dumps({'material_reviews':[{'evidence_id':r['evidence_id'],'disposition':'appendix','reason':'该条是补充历史细节，没有本章任免或职责的新变化。'} for r in d['facts']]})
    initial=diagnose_material(p,[],invoke,None);assert initial['status']=='pending'
    fail[0]=False;seen.clear();resumed=diagnose_material(p,[],invoke,None,initial)
    assert resumed['status']=='passed' and resumed['same_context_decisions_reused']==16 and seen==[facts[-1]['evidence_id']]
    changed=[{'analysis':'不同的正文内容','evidence_ids':[facts[0]['evidence_id']]}];seen.clear()
    fresh=diagnose_material(p,changed,invoke,None,resumed)
    assert fresh['same_context_decisions_reused']==0 and len(seen)==17


def test_reviewing_a_displayed_record_does_not_append_an_unsolicited_alternative_quote():
    f={'evidence_id':'E-TEST0001','fact':'董事会选举陈雨安任董事长，任期三年。并由其负责研发项目审批。','analysis_allowed':True}
    excerpt={'evidence_id':f['evidence_id'],'quote':'董事会选举陈雨安任董事长，任期三年。'}
    p={'chapter':5,'title':'管理','facts':[f],'required_source_displays':[excerpt]}
    answer={'material_reviews':[{'evidence_id':f['evidence_id'],'disposition':'source_display',
        'reason':'所需任命与三年任期已由现有原文展示。','required_quote':f['fact']}]}
    a=diagnose_material(p,[],lambda *a:json.dumps(answer),None)
    assert a['status']=='passed' and p['required_source_displays']==[excerpt]


def test_malformed_required_quotes_use_only_the_complete_short_original_not_character_excerpts():
    from person_material_accounting import propose_literal_displays
    f={'evidence_id':'E-TEST0001','fact':'董事会选举陈雨安任董事长。'};p={'facts':[f]}
    d={'rows':[{'evidence_id':f['evidence_id'],'disposition':'missing','required_quotes':f['fact']}]}
    result=propose_literal_displays(p,d)
    assert result['added'] and p['required_source_displays'][0]['quote']==f['fact']


def test_new_literal_displays_are_reallocated_within_budget_and_then_all_material_is_reviewed_again():
    from person_material_review import presentation_facts
    facts=[{'evidence_id':f'E-TEST{i:04d}','fact':f'陈雨安负责事项{i}。'+('补充细节仅供回查。'*15),
        'analysis_allowed':True,'source_url':f'https://fixture.invalid/{i}'} for i in range(17)]
    p={'chapter':5,'title':'管理','facts':facts,'require_material_dispositions':True};allocations=[];reviews=[]
    def invoke(role,prompt,*a):
        d=json.loads(prompt.splitlines()[-1])
        if '原文展示编排' in role:
            allocations.append(d)
            return json.dumps({'displays':[{'evidence_id':r['evidence_id'],'segment_ids':[0]} for r in d['sources']]})
        assert '材料采用诊断' in role
        reviews.extend(r['evidence_id'] for r in d['facts'])
        return json.dumps({'material_reviews':[{'evidence_id':r['evidence_id'],'disposition':'source_display',
            'reason':'本条负责事项需保留。','required_quote':r['original']} for r in d['facts']]})
    claims,issues,a=accept_content(p,[],[],{'chapter':5,'facts':facts},invoke,None,validate_model_claims)
    assert not issues and len(allocations)==1 and len(reviews)==34
    assert a['material_diagnosis']['counts']=={'source_display':17}
    shown=presentation_facts(p,claims)
    assert len(shown)==17 and sum(len(f['fact']) for f in shown)<=1600
    assert not p['quotation_budget']['required_undisplayed_evidence_ids']


def test_invalid_literal_allocation_cannot_replace_the_existing_required_quotes():
    from person_material_accounting import allocate_literal_displays
    f={'evidence_id':'E-TEST0001','fact':'陈雨安负责研发审批。另有其他事项。'}
    original=[{'evidence_id':f['evidence_id'],'quote':f['fact']}]
    p={'chapter':5,'title':'管理','facts':[f],'required_source_displays':list(original)}
    response={'displays':[{'evidence_id':f['evidence_id'],'segment_ids':[999]}]}
    a=allocate_literal_displays(p,[],lambda *a:json.dumps(response),None,max_chars=10)
    assert a['status']=='pending' and a['requests']==2 and p['required_source_displays']==original


def test_literal_allocator_retries_a_transient_failure_but_still_requires_valid_source_ids():
    from person_material_accounting import allocate_literal_displays
    f={'evidence_id':'E-TEST0001','fact':'陈雨安负责研发审批。'}
    p={'chapter':5,'title':'管理','facts':[f],'required_source_displays':[{'evidence_id':f['evidence_id'],'quote':f['fact']}]};calls=[]
    def invoke(role,prompt,*a):
        calls.append(prompt)
        if len(calls)==1:raise ConnectionError('temporary transport failure')
        return json.dumps({'displays':[{'evidence_id':f['evidence_id'],'segment_ids':[0]}]})
    audit=allocate_literal_displays(p,[],invoke,None)
    assert audit['requests']==2 and len(calls)==2 and audit['status']=='selected_for_material_review'
    assert p['required_source_displays'][0]['quote']==f['fact']


def test_review_scope_separates_body_reference_ids_from_every_requested_material_card():
    facts=[{'evidence_id':f'E-TEST{i:04d}','fact':f'陈雨安相关补充记录{i}。','analysis_allowed':True} for i in range(17)]
    p={'chapter':5,'title':'管理','facts':facts,'required_source_displays':[{'evidence_id':facts[0]['evidence_id'],'quote':facts[0]['fact']}]};seen=[]
    def invoke(role,prompt,*a):
        d=json.loads(prompt.splitlines()[-1]);ids=[r['evidence_id'] for r in d['facts']];seen.extend(ids)
        assert len(ids)<=8 and d['review_evidence_ids']==ids
        assert [r['evidence_id'] for r in d['response_schema']['material_reviews']]==ids
        assert d['source_display_quotes'][0]['shown_evidence_id']==facts[0]['evidence_id']
        assert 'evidence_id' not in d['source_display_quotes'][0]
        return json.dumps({'material_reviews':[{'evidence_id':eid,'disposition':'appendix','reason':'本条为补充细节，无本章职责变化。'} for eid in ids]})
    a=diagnose_material(p,[],invoke,None)
    assert a['status']=='passed' and seen==[r['evidence_id'] for r in facts] and a['input_records']==17


def test_literal_overflow_repairs_only_eligible_facts_in_prose_and_keeps_all_ten_records():
    facts=[];bases=[]
    for i in range(9):
     base=f'2024年林知远批准研发事项{i}，额度为{i+1}万元。';bases.append(base)
     text=(base+'项目附件补充线索'*30)[:200]
     facts.append({'evidence_id':f'E-T{i:04d}','fact':text,'analysis_allowed':True,'subject_scope':'person','source_url':f'https://fixture.invalid/{i}'})
    false={'evidence_id':'E-T9999','fact':('记者对林知远的评价观点，实际行为仍待核实。'+'评价背景补充'*50)[:200],'analysis_allowed':False,'subject_scope':'attributed_opinion','source_url':'https://fixture.invalid/opinion'}
    facts.append(false);ids=[f['evidence_id'] for f in facts[:-1]];written=[]
    p={'chapter':5,'title':'管理','facts':facts,'require_material_dispositions':True}
    def invoke(role,prompt,*args):
     d=json.loads(prompt.splitlines()[-1])
     if '材料采用诊断' in role:
      active={eid for c in d['draft'] for eid in c['evidence_ids']}
      return json.dumps({'material_reviews':[{'evidence_id':r['evidence_id'],'disposition':'analysis' if r['evidence_id'] in active else 'source_display',
       'matched_claim_indices':[0] if r['evidence_id'] in active else [],'required_quote':r['original'],
       'reason':'本条关键授权额度应通过分析或原文保留，评价仅作来源观点展示。'} for r in d['facts']]})
     if '原文展示编排' in role:
      selected={*ids[:7],false['evidence_id']}
      return json.dumps({'displays':[{'evidence_id':r['evidence_id'],'segment_ids':[next(s['segment_id'] for s in r['segments'] if len(s['quote'])==200)]} for r in d['sources'] if r['evidence_id'] in selected]})
     if '事项定向补写' in role:
      written.append(d);selected=[f['evidence_id'] for f in d['facts']];return json.dumps({'claims':[{'analysis':''.join(bases[ids.index(eid)] for eid in selected),'evidence_ids':selected}]})
     if '语义复核' in role:return json.dumps({'reviews':[{'claim_index':0,'verdict':'supported','supporting_evidence_ids':[f['evidence_id'] for f in written[-1]['facts']]}]})
     raise AssertionError(role)
    def validate(answer,package):
     rows=json.loads(answer)['claims'];assert all(false['evidence_id'] not in c['evidence_ids'] for c in rows)
     from person_evidence import validate_model_claims
     return validate_model_claims(answer,{**package,'writing_contract':'evidence_selection_v2'})
    claims,issues,a=accept_content(p,[],[],{'chapter':5,'facts':facts},invoke,None,validate)
    assert not issues and a['status'].startswith('passed') and len(written)==1
    assert false['evidence_id'] in {r['evidence_id'] for r in p['required_source_displays']}
    assert len(written[0]['facts'])==2
    assert sum(len(r['quote']) for r in p['required_source_displays'])<=1600
    assert len(claims[0]['analysis'])<=600

    from person_material_review import presentation_facts
    shown=presentation_facts(p,claims)
    assert {f["evidence_id"] for f in shown}|{eid for c in claims for eid in c["evidence_ids"]}=={f["evidence_id"] for f in facts}
    assert sum(len(f["fact"]) for f in shown)<=1600 and not p["quotation_budget"]["required_undisplayed_evidence_ids"]
    assert not false["analysis_allowed"]


def test_quote_only_replan_rechecks_affected_records_but_body_or_source_changes_recheck_everything():
    facts=[{'evidence_id':f'E-CACHE{i:04d}','fact':f'林知远补充经历{i}。','analysis_allowed':True} for i in range(10)]
    p={'chapter':5,'title':'管理','facts':facts,'literal_material_display_proposed':True};seen=[]
    def invoke(role,prompt,*args):
        data=json.loads(prompt.splitlines()[-1]);seen.extend(r['evidence_id'] for r in data['facts'])
        return json.dumps({'material_reviews':[{'evidence_id':r['evidence_id'],
            'disposition':'source_display' if r['evidence_id'] in data['source_display_evidence_ids'] else 'appendix',
            'reason':'该补充经历没有任期或权责的新事件，作为背景资料留存。'} for r in data['facts']]})
    a=diagnose_material(p,[],invoke,None);assert len(seen)==10
    p['required_source_displays']=[{'evidence_id':facts[0]['evidence_id'],'quote':facts[0]['fact']}];seen.clear()
    b=diagnose_material(p,[],invoke,None,a)
    assert seen==[facts[0]['evidence_id']] and b['unchanged_record_decisions_reused']==9 and len(b['rows'])==10
    draft=[{'analysis':'正文已改变。','evidence_ids':[facts[1]['evidence_id']]}];seen.clear()
    c=diagnose_material(p,draft,invoke,None,b);assert len(seen)==10 and c['unchanged_record_decisions_reused']==0
    facts[2]['analysis_allowed']=False;seen.clear()
    d=diagnose_material(p,draft,invoke,None,c);assert len(seen)==10 and not facts[2]['analysis_allowed']


def test_quote_dependency_is_not_reused_when_another_display_disappears():
    facts=[{'evidence_id':f'E-DEP{i:04d}','fact':f'林知远项目事项{i}。','analysis_allowed':True} for i in range(3)]
    p={'chapter':5,'title':'管理','facts':facts,'literal_material_display_proposed':True,
        'required_source_displays':[{'evidence_id':facts[0]['evidence_id'],'quote':facts[0]['fact']}]};seen=[]
    def invoke(role,prompt,*args):
        d=json.loads(prompt.splitlines()[-1]);seen.extend(f['evidence_id'] for f in d['facts']);reviews=[]
        for f in d['facts']:
            dependent=f['evidence_id']==facts[1]['evidence_id']
            reviews.append({'evidence_id':f['evidence_id'],'disposition':'missing' if dependent and not d.get('source_display_quotes') else 'appendix',
                'reason':'与另一编号已展示的原文对应，需核对共同事件是否仍保留。' if dependent else '本条是背景事项，没有新的任期或权责事件。'})
        return json.dumps({'material_reviews':reviews})
    a=diagnose_material(p,[],invoke,None);p['required_source_displays']=[];seen.clear()
    b=diagnose_material(p,[],invoke,None,a)
    assert seen==[facts[0]['evidence_id'],facts[1]['evidence_id']] and b['status']=='missing'
    assert b['unchanged_record_decisions_reused']==1
