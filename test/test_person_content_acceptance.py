import json
from person_content_acceptance import check_coverage,accept_content,tenure_requirements
from person_role_checks import role_errors,roster_roles,align_tenure_citations
from person_evidence import build_packages,validate_model_claims
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


def fixture():
    payload={'facts':[
        {'fact':'林知远于2018年担任远山科技董事长兼总裁，负责研发管理；董事长任期三年，总裁任期三年。本次会议由林知远召集并主持。',
         'source_url':'https://fixture.invalid/roles','identity_match':'confirmed'},
        {'fact':'林知远公开介绍工程师文化，称要建立文化认同。',
         'source_url':'https://fixture.invalid/culture','identity_match':'confirmed'}]}
    p=build_packages(payload,'林知远',PERSON_REPORT_OUTLINE)['chapters'][5]
    p['writing_contract']='evidence_selection_v2';p['facts']=p['research_facts']
    role=next(f['evidence_id'] for f in p['facts'] if '2018' in f['fact'])
    culture=next(f['evidence_id'] for f in p['facts'] if '文化' in f['fact'])
    old=[{'analysis':'2018年来源载林知远担任董事长，董事长任期三年；担任总裁，总裁任期三年。','evidence_ids':[role]}]
    current=[{'analysis':'2018年公告载，本次会议由林知远召集并主持。','evidence_ids':[role]},
             {'analysis':'来源记载林知远公开介绍工程师文化，属于其自述。','evidence_ids':[culture]}]
    return p,old,current


def complete_coverage_reply(prompt):
    """Offline reviewer responds to every explicit question in a batch."""
    data=json.loads(prompt.splitlines()[-1])
    return json.dumps({'reviews':[{'prior_index':i,'verdict':'covered',
        'matched_claim_indices':[j for j,c in enumerate(data['draft']) if set(c['evidence_ids']) & set(old['evidence_ids'])],
        'gaps':[],'reason':'核对具体任期和实际承接文字。'} for i,old in enumerate(data['prior'])]})


def test_roster_mixed_job_levels_are_blocked_but_generic_summary_is_allowed():
    facts=[{'fact':'李明女士，现任本公司执行副总裁。刘伟先生，现任本公司副总裁。周颖女士，现任本公司高级副总裁。'}]
    assert roster_roles(facts)['刘伟']=={'副总裁'}
    assert role_errors('年报载李明、刘伟、周颖等历任经理后任执行副总裁或高级副总裁。',facts)==['named_executive_role_misattributed']
    assert not role_errors('年报载李明、刘伟、周颖等担任高管，具体职责各不相同。',facts)
    assert role_errors('刘伟现任执行副总裁。',facts)
    assert not role_errors('刘伟曾任高级副总裁。',facts) # no inferred historical denial


def test_role_check_does_not_flatten_different_report_periods():
    facts=[{'fact':'刘伟先生，现任本公司副总裁。'},{'fact':'刘伟先生，现任本公司高级副总裁。'}]
    assert not role_errors('刘伟现任高级副总裁。',facts)


def test_same_citation_and_meeting_date_cannot_stand_in_for_both_tenures():
    p,old,claims=fixture()
    assert set(tenure_requirements(old[0]['analysis']))=={('董事长','3年'),('总裁','3年')}
    reply={'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[0],'gaps':[],'reason':'同一来源'}]}
    review=check_coverage(p,claims,old,lambda *a:json.dumps(reply),None)
    assert review['status']=='pending_review'
    assert review['items'][0]['status']=='missing'
    assert len(review['items'][0]['missing_tenures'])==2


def test_empty_coverage_response_never_becomes_a_mass_rewrite_request():
    p,old,claims=fixture();calls=[]
    def invoke(*a):calls.append(a);return ''
    result,reasons,audit=accept_content(p,claims,old,{'chapter':5,'facts':p['facts']},invoke,None,validate_model_claims)
    assert result==claims and len(calls)==2
    assert audit['status']=='pending_delivery' and reasons


def test_nonliteral_gap_gets_one_format_retry_without_turning_missing_into_pass():
    p,old,claims=fixture();calls=[]
    def invoke(role,prompt,*a):
        calls.append((role,prompt))
        quote='改述的遗漏事项' if len(calls)==1 else old[0]['analysis']
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'missing','matched_claim_indices':[0],
            'gaps':[{'prior_quote':quote,'evidence_ids':old[0]['evidence_ids']}]}]})
    audit=check_coverage(p,claims,old,invoke,None)
    assert len(calls)==2 and '格式补核' in calls[1][0]
    assert audit['items'][0]['status']=='missing'
    assert audit['items'][0]['gaps'][0]['prior_quote']==old[0]['analysis']


def test_persistently_nonliteral_gaps_stay_pending_after_bounded_retry():
    p,old,claims=fixture();calls=[]
    def invoke(*a):
        calls.append(a)
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'missing','matched_claim_indices':[0],
            'gaps':[{'prior_quote':'不属于旧稿的文字','evidence_ids':old[0]['evidence_ids']}]}]})
    audit=check_coverage(p,claims,old,invoke,None)
    assert len(calls)==2 and audit['items'][0]['status']=='pending_review'


def test_old_content_gap_can_select_provided_old_paragraph_segments():
    p,old,claims=fixture();calls=[]
    def invoke(role,prompt,*a):
        calls.append(role);data=json.loads(prompt.splitlines()[-1])
        gap={'evidence_ids':old[0]['evidence_ids']}
        if len(calls)==1:gap['prior_quote']='改述，不能被当作原文'
        else:
            assert data['prior_segments']['0']
            gap['prior_segment_ids']=[0]
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'missing','matched_claim_indices':[0],'gaps':[gap]}]})
    a=check_coverage(p,claims,old,invoke,None)
    assert a['items'][0]['status']=='missing' and len(calls)==2
    assert a['items'][0]['gaps'][0]['source_segment_ids_selected']
    assert a['items'][0]['gaps'][0]['prior_quote'] in old[0]['analysis']


def test_malformed_verdict_type_stays_pending_instead_of_crashing():
    p,old,claims=fixture()
    a=check_coverage(p,claims,old,lambda *a:json.dumps({'reviews':[{'prior_index':0,'verdict':['covered']}]}),None)
    assert a['status']=='pending_review' and a['items'][0]['status']=='pending_review'


def test_transient_coverage_connection_failure_retries_the_same_content_review_once():
    p,old,_=fixture();calls=[]
    def invoke(role,prompt,*a):
        calls.append((role,prompt))
        if len(calls)==1:raise ConnectionError('temporary model connection failure')
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[0],'gaps':[]}]})
    current=[{**old[0], 'analysis':'来源注明：'+old[0]['analysis']}]
    a=check_coverage(p,current,old,invoke,None)
    assert a['status']=='passed' and a['requests']==2
    assert calls[0][1]==calls[1][1] and '调用补核' in calls[1][0]


def test_a_prior_platform_fact_can_be_preserved_in_the_actual_body_table():
    f={'evidence_id':'E-TEST0001','fact':'陈雨安；历史记录；'+json.dumps({'企业名称':'远山公司','职位':'董事',
        '任职起止时间':'开始时间:2020-01-01,结束时间:[]'},ensure_ascii=False),
        'source_url':'structured://qcc/historical_positions','claim_type':'person_platform_record','analysis_allowed':True}
    p={'chapter':9,'title':'关联关系','facts':[f]}
    prior=[{'analysis':'平台历史记录载其2020年1月1日开始担任远山公司董事，结束时间为空。','evidence_ids':[f['evidence_id']]}]
    def invoke(role,prompt,*a):
        data=json.loads(prompt.splitlines()[-1])
        assert data['tables'][0]['evidence_ids']==[f['evidence_id']]
        assert '2020-01-01' in data['tables'][0]['text']
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[],
            'matched_table_indices':[0],'gaps':[],'reason':'旧稿任职事实完整保留在本章专业明细表。'}]})
    a=check_coverage(p,[],prior,invoke,None)
    assert a['status']=='passed' and a['items'][0]['matched_table_indices']==[0]


def test_a_table_for_a_different_source_cannot_silently_cover_the_prior_record():
    f={'evidence_id':'E-TEST0001','fact':'陈雨安；历史记录；{"企业名称":"远山公司","职位":"董事"}',
        'source_url':'structured://qcc/historical_positions','claim_type':'person_platform_record'}
    p={'chapter':9,'title':'关联关系','facts':[f]}
    prior=[{'analysis':'旧来源记载其担任另一个机构董事。','evidence_ids':['E-OTHER0002']}]
    row={'prior_index':0,'verdict':'covered','matched_claim_indices':[],'matched_table_indices':[0],'gaps':[]}
    a=check_coverage(p,[],prior,lambda *a:json.dumps({'reviews':[row]}),None)
    assert a['status']=='pending_review'


def test_bad_review_indices_and_nonliteral_exclusion_cannot_pass():
    p,old,claims=fixture()
    for row in [
        {'prior_index':0,'verdict':'covered','matched_claim_indices':[99]},
        {'prior_index':0,'verdict':'invalid_prior','evidence_id':old[0]['evidence_ids'][0],
         'source_quote':'来源没有出现的编造片段不应通过','reason':'字数不够'}]:
        review=check_coverage(p,claims,old,lambda *a:json.dumps({'reviews':[row]}),None)
        assert review['status']=='pending_review'


def test_targeted_coverage_repair_preserves_good_paragraph_then_rechecks_every_prior_item():
    p,old,claims=fixture();calls=[]
    def invoke(role,prompt,*a):
        data=json.loads(prompt.splitlines()[-1]);calls.append(role)
        if '事项定向补写' in role:
            assert data['locked_analyses']==[claims[1]]
            assert data['replace_draft']==[claims[0]]
            return json.dumps({'claims':[{**old[0],'analysis':old[0]['analysis']+'本次会议由其召集并主持。'}]})
        if '语义复核' in role:
            return json.dumps({'reviews':[{'claim_index':i,'verdict':'supported','supporting_evidence_ids':c['evidence_ids']}
                                           for i,c in enumerate(data['claims'])]})
        return complete_coverage_reply(prompt)
    result,reasons,audit=accept_content(p,claims,old,{'chapter':5,'facts':p['facts']},invoke,None,validate_model_claims)
    assert not reasons and audit['status']=='passed_after_targeted_repair'
    assert result[1]['analysis']==claims[1]['analysis']
    assert '董事长任期三年' in result[0]['analysis'] and '总裁任期三年' in result[0]['analysis']
    assert audit['preserved_claim_indices']==[1] and audit['requests']==5
    assert '召集并主持' in result[0]['analysis']
    assert len(calls)==5


def test_failed_post_repair_coverage_keeps_old_draft_and_records_candidate():
    p,old,claims=fixture();count=[]
    def invoke(role,prompt,*a):
        count.append(role);data=json.loads(prompt.splitlines()[-1])
        if '事项定向补写' in role:return json.dumps({'claims':[claims[0]]})
        if '语义复核' in role:return json.dumps({'reviews':[{'claim_index':0,'verdict':'supported','supporting_evidence_ids':old[0]['evidence_ids']}]})
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[0],'gaps':[]}]})
    result,reasons,audit=accept_content(p,claims,old,{'chapter':5,'facts':p['facts']},invoke,None,validate_model_claims)
    assert result==claims and reasons and audit['status']=='pending_delivery'
    assert audit['candidate_repair']


def test_pending_semantic_draft_and_missing_baseline_are_not_called_coverage_success():
    p,old,claims=fixture()
    def forbidden(*a):raise AssertionError('unexpected model call')
    pending=[{**claims[0],'analysis':'','review_analysis':claims[0]['analysis']}]
    _,reasons,audit=accept_content(p,pending,old,{},forbidden,None,validate_model_claims)
    assert reasons and audit['status']=='pending_delivery'
    _,reasons,audit=accept_content(p,claims,[],{},forbidden,None,validate_model_claims)
    assert not reasons and audit['status']=='no_prior_draft_comparison'


def test_literal_source_cannot_justify_excluding_a_prior_item_for_length():
    p,old,claims=fixture();fact=next(f for f in p['facts'] if f['evidence_id']==old[0]['evidence_ids'][0])
    row={'prior_index':0,'verdict':'invalid_prior','evidence_id':fact['evidence_id'],
         'source_quote':fact['fact'],'error_type':'wrong_period','reason':'字数预算不足，删除旧稿'}
    audit=check_coverage(p,claims,old,lambda *a:json.dumps({'reviews':[row]}),None)
    assert audit['status']=='pending_review' and audit['items'][0]['status']!='excluded_with_source_bound_reason'


def test_tenure_alignment_only_adds_explicit_target_record_from_provided_same_document():
    rows=[{'evidence_ids':['a'],'analysis':'林知远为董事长，董事长任期三年；获聘总裁，总裁任期三年。'}]
    base={'subject':'林知远','subject_scope':'person','analysis_allowed':True,'source_url':'https://fixture.invalid/doc'}
    facts=[{**base,'evidence_id':'a','fact':'董事会选举林知远为董事长，任期三年。'},
           {**base,'evidence_id':'b','fact':'聘任林知远为公司总裁，任期三年。'},
           {**base,'evidence_id':'other','fact':'聘任周明为公司总裁，任期三年。'},
           {**base,'evidence_id':'newdoc','source_url':'https://fixture.invalid/new','fact':'林知远为总裁，任期三年。'}]
    revised,events=align_tenure_citations(rows,facts)
    assert revised[0]['analysis']==rows[0]['analysis']
    assert revised[0]['evidence_ids']==['a','b'] and len(events)==1
    revised,events=align_tenure_citations(rows,[f for f in facts if f['evidence_id']!='b'])
    assert revised[0]['evidence_ids']==['a'] and not events


def test_coverage_is_split_by_prior_item_without_losing_current_draft_context():
    p,old,claims=fixture();packets=[]
    def invoke(role,prompt,*a):
        packet=json.loads(prompt.splitlines()[-1]);packets.append(packet)
        assert len(packet['prior'])==1 and len(packet['draft'])==len(claims)
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'missing','matched_claim_indices':[0],
            'gaps':[{'prior_quote':packet['prior'][0]['analysis'],'evidence_ids':packet['prior'][0]['evidence_ids']}]}]})
    audit=check_coverage(p,claims,[*old,*old],invoke,None)
    assert len(packets)==2 and audit['requests']==2
    assert [r['prior_index'] for r in audit['items']]==[0,1]


def test_nominating_chairman_is_not_the_office_assigned_president_tenure():
    from person_role_checks import role_tenures
    assert role_tenures('经董事长提名、提名委员会审核，同日聘任其为总裁，任期三年。')==[('总裁','3年')]
    assert set(role_tenures('董事长与总裁任期均三年。'))=={('董事长','3年'),('总裁','3年')}


def test_tenure_guard_accepts_explicit_same_document_support_but_keeps_missing_role_guard():
    from person_records import definition_errors
    executive={'fact':'经董事长提名，聘任林知远为总裁，任期三年。','source_url':'https://fixture.invalid/doc'}
    chairman={'fact':'选举林知远为董事长，任期三年。','source_url':'https://fixture.invalid/doc'}
    assert 'mixed_role_tenure_not_supported' not in definition_errors('经董事长提名、提名委员会审核，同日聘任其为总裁，任期三年。',[executive])
    assert 'mixed_role_tenure_not_supported' in definition_errors('林知远同时担任董事长和总裁，任期三年。',[executive])
    assert 'mixed_role_tenure_not_supported' not in definition_errors('林知远同时担任董事长和总裁，任期三年。',[chairman,executive])
    assert 'mixed_role_tenure_not_supported' in definition_errors('林知远同时担任董事长和总裁，任期三年。',[chairman,{**executive,'source_url':'https://fixture.invalid/other'}])


def test_oversized_candidate_is_compacted_before_partial_source_repair_can_reserve_its_budget(monkeypatch):
    p,old,claims=fixture();seen=[]
    replacement={'analysis':old[0]['analysis']+'本次会议由林知远召集并主持。','evidence_ids':old[0]['evidence_ids']}
    def invoke(role,prompt,*a):
        seen.append((role,prompt))
        data=json.loads(prompt[prompt.index('{"material":'):] if '核验修订' in role else prompt.splitlines()[-1])
        if '事项定向补写' in role:
            return json.dumps({'claims':[{'analysis':'来源记载林知远公开介绍工程师文化。'*40,'evidence_ids':claims[1]['evidence_ids']},
                {'analysis':'2018年林知远董事长任期四年。','evidence_ids':old[0]['evidence_ids']}]})
        if '事项修订前篇幅压缩' in role:
            assert sum(len(c['analysis']) for c in data['draft'])>600
            return json.dumps({'claims':[{'analysis':'2018年林知远董事长任期四年。','evidence_ids':old[0]['evidence_ids']}]})
        if '核验修订' in role:
            assert '最多0字符' not in prompt
            assert data['corrections'][0]['issues']
            return json.dumps({'claims':[replacement]})
        if '语义复核' in role:
            return json.dumps({'reviews':[{'claim_index':0,'verdict':'supported','supporting_evidence_ids':old[0]['evidence_ids']}]})
        return complete_coverage_reply(prompt)
    result,issues,audit=accept_content(p,claims,old,{'chapter':5,'facts':p['research_facts']},invoke,None,validate_model_claims)
    assert not issues, (audit, seen)
    assert result[0]['analysis']==replacement['analysis'] and result[1]['analysis']==claims[1]['analysis']
    roles=[r for r,_ in seen]
    assert next(i for i,r in enumerate(roles) if '事项修订前篇幅压缩' in r)<next(i for i,r in enumerate(roles) if '核验修订' in r)
    assert audit['initial_revision_compression']['compression']['status']=='returned_for_validation'


def test_targeted_writer_does_not_expand_unrelated_records_from_the_same_pdf():
    p,old,claims=fixture()
    unrelated={**p['facts'][0],'evidence_id':'E-TESTFFFF','fact':'林知远于2001年毕业于远山大学，取得学位。'}
    p['research_facts']=[*p['research_facts'],unrelated];p['facts']=p['research_facts']
    replacement={'analysis':old[0]['analysis']+'本次会议由林知远召集并主持。','evidence_ids':old[0]['evidence_ids']}
    supplied=[]
    def invoke(role,prompt,*a):
        data=json.loads(prompt.splitlines()[-1])
        if '事项定向补写' in role:
            supplied.extend(data['facts'])
            return json.dumps({'claims':[replacement]})
        if '语义复核' in role:
            return json.dumps({'reviews':[{'claim_index':0,'verdict':'supported','supporting_evidence_ids':old[0]['evidence_ids']}]})
        return complete_coverage_reply(prompt)
    result,issues,audit=accept_content(p,claims,old,{'chapter':5,'facts':p['facts']},invoke,None,validate_model_claims)
    assert not issues and result[0]['analysis']==replacement['analysis']
    assert unrelated in p['research_facts']
    assert supplied and all(f['evidence_id']!='E-TESTFFFF' for f in supplied)
    assert all(f['fact']==next(r['fact'] for r in p['research_facts'] if r['evidence_id']==f['evidence_id']) for f in supplied)


def test_transient_server_error_retries_targeted_repair_without_bypassing_its_checks():
    p,old,claims=fixture();writes=[]
    server_error=type('InternalServerError',(RuntimeError,),{})
    replacement={'analysis':old[0]['analysis']+'本次会议由林知远召集并主持。','evidence_ids':old[0]['evidence_ids']}
    def invoke(role,prompt,*a):
        if '事项定向补写' in role:
            writes.append(prompt)
            if len(writes)==1:raise server_error('temporary provider failure')
            assert prompt==writes[0]
            return json.dumps({'claims':[replacement]})
        if '语义复核' in role:return json.dumps({'reviews':[{'claim_index':0,'verdict':'supported','supporting_evidence_ids':old[0]['evidence_ids']}]})
        return complete_coverage_reply(prompt)
    result,issues,audit=accept_content(p,claims,old,{'chapter':5,'facts':p['research_facts']},invoke,None,validate_model_claims)
    assert not issues and len(writes)==2 and len(audit['rounds'])==1
    assert result[0]['analysis']==replacement['analysis'] and audit['stop_reason']=='accepted'


def test_prior_fact_can_be_preserved_in_an_actual_required_literal_excerpt():
    p,old,claims=fixture();f=next(f for f in p['facts'] if f['evidence_id'] in old[0]['evidence_ids'])
    p['required_source_displays']=[{'evidence_id':f['evidence_id'],'quote':f['fact']}]
    reply={'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[],
        'matched_table_indices':[0],'gaps':[]}]}
    a=check_coverage(p,claims,old,lambda *a:json.dumps(reply),None)
    assert a['status']=='passed' and a['items'][0]['matched_table_indices']==[0]
    p['required_source_displays'][0]['quote']='虚构的董事长及总裁任期三年。'
    assert check_coverage(p,claims,old,lambda *a:json.dumps(reply),None)['status']=='pending_review'


def test_noncontiguous_literal_exclusion_proofs_are_separate_and_forged_spans_fail():
    p,old,claims=fixture();eid=old[0]['evidence_ids'][0]
    prior=[{'analysis':'2018年来源只记其主持会议，没有董事长或总裁任职信息。','evidence_ids':[eid]}]
    quotes=['林知远于2018年担任远山科技董事长兼总裁','董事长任期三年，总裁任期三年']
    row={'prior_index':0,'verdict':'invalid_prior','matched_claim_indices':[0],'gaps':[],
        'evidence_id':eid,'source_quote':'；'.join(quotes),'error_type':'source_contradiction',
        'reason':'原文明确列出两项任职及任期，旧稿称没有任职信息不成立；其余会议主持事实仍已保留。'}
    a=check_coverage(p,claims,prior,lambda *args:json.dumps({'reviews':[row]}),None)
    assert a['status']=='passed'
    proof=a['items'][0]['source_bound_exclusion']
    assert proof['source_quotes']==quotes and proof['proof_spans_validated']
    bad={**row,'source_quotes':[quotes[0],'总裁任期十年且有绝对决策权。']}
    b=check_coverage(p,claims,prior,lambda *args:json.dumps({'reviews':[bad]}),None)
    assert b['status']=='pending_review' and b['requests']==2


def test_new_known_source_can_preserve_the_same_fact_in_the_actual_body_table():
    old={'evidence_id':'E-OLD0002','fact':'陈雨安于2020年1月1日出任远山公司董事，任职终止日未披露。',
        'source_url':'https://fixture.invalid/appointment','subject':'陈雨安','subject_scope':'person'}
    new={'evidence_id':'E-NEW0003','fact':'陈雨安；历史记录；'+json.dumps({'企业名称':'远山公司','职位':'董事',
        '任职起止时间':'开始时间:2020-01-01,结束时间:[]'},ensure_ascii=False),
        'source_url':'structured://qcc/historical_positions','claim_type':'person_platform_record',
        'subject':'陈雨安','subject_scope':'person','analysis_allowed':True}
    p={'chapter':9,'title':'关联关系','facts':[old,new]}
    prior=[{'analysis':'资料载陈雨安2020年1月1日开始担任远山公司董事，任职终止日未披露。','evidence_ids':[old['evidence_id']]}]
    def invoke(role,prompt,*args):
        data=json.loads(prompt.splitlines()[-1]);assert data['tables'][0]['source_contexts'][0]['subject']=='陈雨安'
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[],
            'matched_table_indices':[0],'gaps':[],'reason':'同一人物、企业、职务与起止日期原字段由新平台记录完整保留。'}]})
    assert check_coverage(p,[],prior,invoke,None)['status']=='passed'


def test_new_source_resolves_prior_unknown_year_without_losing_the_actual_event_day():
    old={'evidence_id':'E-OLD0002','fact':'1月13日林知远接替周明任CEO。','source_url':'https://fixture.invalid/old','subject':'林知远'}
    new={'evidence_id':'E-NEW0003','fact':'董事会宣布，自2026年1月13日起林知远接替周明担任CEO。',
        'source_url':'https://fixture.invalid/official','subject':'林知远'}
    p={'chapter':5,'title':'管理','facts':[old,new]}
    prior=[{'analysis':'来源载1月13日林知远接替周明任CEO，年份未明。','evidence_ids':[old['evidence_id']]}]
    current=[{'analysis':'公告载自2026年1月13日起林知远接替周明任CEO。','evidence_ids':[new['evidence_id']]}]
    def invoke(role,prompt,*args):
        data=json.loads(prompt.splitlines()[-1]);assert {x['evidence_id'] for x in data['sources']}=={old['evidence_id'],new['evidence_id']}
        assert '同一事件和同一期间' in prompt
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[0],'gaps':[],
            'reason':'新公告明确同一CEO交接的完整日期，旧年份未知状态已得到更新，日次和前后任均保留。'}]})
    assert check_coverage(p,current,prior,invoke,None)['status']=='passed'
    lost_day=[{**current[0],'analysis':current[0]['analysis'].replace('13日','')}]
    assert check_coverage(p,lost_day,prior,invoke,None)['status']=='pending_review'


def test_second_round_conserves_newly_validated_content_and_keeps_review_indices_aligned():
    p,prior,claims=fixture();role=prior[0]['evidence_ids'][0];culture=claims[1]['evidence_ids'][0]
    current=[{'analysis':'2018年来源载林知远担任董事长兼总裁；另来源载其公开介绍工程师文化。','evidence_ids':[role,culture]}]
    writes=[]
    def invoke(role_name,prompt,*args):
        data=json.loads(prompt.splitlines()[-1])
        if '事项定向补写' in role_name:
            writes.append(data)
            analysis=prior[0]['analysis']+('另来源载其公开介绍工程师文化，属于自述。' if len(writes)>1 else '')
            return json.dumps({'claims':[{'analysis':analysis,'evidence_ids':[role,culture] if len(writes)>1 else [role]}]})
        if '语义复核' in role_name:return json.dumps({'reviews':[{'claim_index':0,'verdict':'supported',
            'supporting_evidence_ids':[role,culture] if len(writes)>1 else [role]}]})
        assert '事项覆盖验收' in role_name
        text=''.join(c['analysis'] for c in data['draft']);reviews=[]
        for i,row in enumerate(data['prior']):
            old=row['analysis'];gap=None
            if '公开介绍工程师文化' in old and '公开介绍工程师文化' not in text:gap={'prior_quote':'公开介绍工程师文化','evidence_ids':[culture]}
            elif '董事长任期三年' in old and '董事长任期三年' not in text:gap={'prior_quote':'董事长任期三年','evidence_ids':[role]}
            reviews.append({'prior_index':i,'verdict':'missing' if gap else 'covered','matched_claim_indices':[0],'gaps':[gap] if gap else []})
        return json.dumps({'reviews':reviews})
    result,issues,a=accept_content(p,current,prior,{'chapter':5,'facts':p['research_facts']},invoke,None,validate_model_claims)
    assert not issues and len(writes)==2 and a['status']=='passed_after_targeted_repair'
    assert '公开介绍工程师文化' in result[0]['analysis'] and '董事长任期三年' in result[0]['analysis']
    assert len(a['rounds'][0]['conserved_requirements'])==2


def test_same_wording_citation_recovery_uses_its_own_source_permission_and_conflict():
    from person_evidence import preserve_cited_aliases
    a={'evidence_id':'E-ALIAS001','fact':'林知远任董事长。','subject':'林知远','subject_scope':'person',
        'source_url':'https://fixture.invalid/a','analysis_allowed':True}
    b={**a,'evidence_id':'E-ALIAS002','source_url':'https://fixture.invalid/b'}
    p={'facts':[a],'research_facts':[a]}
    preserve_cited_aliases(p,[a,b],{b['evidence_id']},{b['evidence_id']})
    assert not p['research_facts'][-1]['analysis_allowed'] and p['research_facts'][-1]['temporal_conflict']
    a={**a,'analysis_allowed':False,'opinion_only':True};b={**b,'opinion_only':False};p={'facts':[a],'research_facts':[a]}
    preserve_cited_aliases(p,[a,b],{b['evidence_id']},set())
    assert p['research_facts'][-1]['analysis_allowed'] and p['research_facts'][-1]['source_url']==b['source_url']
