import json
from types import SimpleNamespace

from person_semantic_review import review_analyses


def test_transport_retry_reviews_identical_candidate_and_preserves_pending_on_failure():
    facts, claims = inputs()
    calls=[]
    def invoke(role,prompt,*args):
        calls.append((role,prompt))
        raise TimeoutError('temporary')
    final, errors, audit=review_analyses(5,'管理',facts,claims,invoke)
    assert len(calls)==2 and calls[0]==calls[1]
    assert errors==['semantic_review_unavailable'] and audit['requests']==2
    assert [r['review_analysis'] for r in final]==[r['analysis'] for r in claims]


def test_nontransient_review_failure_is_pending_without_retry_or_writer():
    facts, claims=inputs();calls=[]
    def invoke(*args):
        calls.append(args)
        raise PermissionError('denied')
    final,errors,audit=review_analyses(5,'管理',facts,claims,invoke)
    assert len(calls)==1 and audit['requests']==1
    assert errors==['semantic_review_unavailable'] and final[0]['review_analysis']


def test_limited_date_precision_is_repaired_from_actual_finding_then_reviewed():
    from person_semantic_review import repair_semantic_findings
    from person_evidence import validate_model_claims
    from test_person_complete_material import facts as make_facts
    source=make_facts(1)['research_facts'][0]
    source['fact']='2022年3月1日公告称林知远卸任总裁；公告未说明卸任生效日。'
    p={'chapter':5,'title':'管理','facts':[source],'writing_contract':'evidence_selection_v2'}
    original=[{'evidence_ids':[source['evidence_id']], 'analysis':'林知远于2022年3月1日卸任总裁。'}]
    prior,errors=validate_model_claims(json.dumps({'claims':original},ensure_ascii=False),p)
    assert not errors
    finding={'claim_index':0,'validation_reason':'semantic_inference_requires_review',
        'issues':['inference_gap'],'reason':'3月1日是公告日，不是已明确的卸任生效日。'}
    reviewed=[{**prior[0],'analysis':'','review_analysis':original[0]['analysis'],'analysis_status':'pending_review'}]
    corrected='2022年3月1日公告称林知远卸任总裁，生效日未明。'
    seen=[]
    def invoke(role,prompt,*args):
        seen.append(role)
        if '核验修订' in role:
            packet=json.loads(prompt[prompt.index('{"material":'):])
            assert packet['corrections'][0]['review_reason']==finding['reason']
            assert packet['corrections'][0]['rejected_analysis']==original[0]['analysis']
            return json.dumps({'claims':[{'evidence_ids':[source['evidence_id']],'analysis':corrected}]},ensure_ascii=False)
        packet=json.loads(prompt.splitlines()[-1])
        assert packet['claims'][0]['analysis']==corrected
        return json.dumps({'reviews':[{'claim_index':0,'verdict':'supported',
            'supporting_evidence_ids':[source['evidence_id']]}]})
    final,errors,audit=repair_semantic_findings(5,'管理',[source],prior,reviewed,
        ['semantic_inference_requires_review'],{'claims':[finding]},p,{'facts':[source]},
        invoke,None,validate_model_claims)
    assert not errors and final[0]['analysis']==corrected
    assert len(seen)==2 and audit['status']=='corrected_and_rechecked'


def inputs():
    facts = [{'evidence_id':f'E-PTEST{i:06d}', 'fact':'来源记载历史董事职务，不能确认现任。',
              'source_url':f'https://fixture.invalid/{i}'} for i in range(3)]
    claims = [{'analysis':'来源披露历史董事角色，缺少当前任期依据。', 'evidence_ids':[facts[0]['evidence_id']]},
              {'analysis':'另有来源记载同一历史职务，仍须核对当前任期。',
               'evidence_ids':[f['evidence_id'] for f in facts[1:]]}]
    return facts, claims


def test_empty_review_preserves_drafts_as_pending_without_rewriting():
    facts, claims = inputs()
    calls = []
    def invoke(*args):
        calls.append(args)
        return ''
    result, reasons, audit = review_analyses(5,'管理',facts,claims,invoke)
    assert len(calls)==1 and audit['status']=='invalid_structured_response'
    assert reasons==['semantic_review_unavailable']
    assert [c['review_analysis'] for c in result]==[c['analysis'] for c in claims]
    assert all(c['analysis_status']=='pending_review' and not c['analysis'] for c in result)


def test_citation_followup_only_resends_incomplete_claim_and_keeps_every_reference():
    facts, claims = inputs()
    packets=[]
    def invoke(role,prompt,*args):
        packet=json.loads(prompt.splitlines()[-1]); packets.append(packet)
        if len(packets)==1:
            return json.dumps({'reviews':[
                {'claim_index':0,'verdict':'supported','supporting_evidence_ids':claims[0]['evidence_ids']},
                {'claim_index':1,'verdict':'supported','supporting_evidence_ids':claims[1]['evidence_ids'][:1]}]})
        assert len(packet['claims'])==1 and packet['claims'][0]['analysis']==claims[1]['analysis']
        return json.dumps({'reviews':[{'claim_index':0,'verdict':'supported',
                                      'supporting_evidence_ids':claims[1]['evidence_ids']}]})
    result,reasons,audit=review_analyses(5,'管理',facts,claims,invoke)
    assert not reasons and result==claims
    assert audit['requests']==2 and audit['targeted_followup']['original_claim_indices']==[1]


def test_persistent_partial_review_stays_pending_never_drops_unreviewed_source_ids():
    facts,claims=inputs()
    def invoke(*args):
        return json.dumps({'reviews':[{'claim_index':0,'verdict':'supported',
                                      'supporting_evidence_ids':claims[1]['evidence_ids'][:1]}]})
    result,reasons,audit=review_analyses(5,'管理',facts,[claims[1]],invoke)
    assert reasons==['semantic_review_incomplete'] and audit['requests']==2
    assert result[0]['review_analysis']==claims[1]['analysis']
    assert result[0]['evidence_ids']==claims[1]['evidence_ids']


def test_targeted_followup_failure_cannot_erase_already_supported_other_claims():
    facts,claims=inputs(); calls=[]
    def invoke(*args):
        calls.append(args)
        if len(calls)>1: raise TimeoutError('test timeout')
        return json.dumps({'reviews':[
            {'claim_index':0,'verdict':'supported','supporting_evidence_ids':claims[0]['evidence_ids']},
            {'claim_index':1,'verdict':'supported','supporting_evidence_ids':claims[1]['evidence_ids'][:1]}]})
    result,reasons,audit=review_analyses(5,'管理',facts,claims,invoke)
    assert result[0]==claims[0]
    assert result[1]['review_analysis']==claims[1]['analysis']
    assert reasons==['semantic_review_unavailable']
    assert audit['targeted_followup']['status']=='request_failed'


def test_empty_semantic_review_does_not_trigger_report_writer_repair(monkeypatch):
    from person_evidence import generate_person_report
    from report_agents.person_report_agent import PERSON_REPORT_OUTLINE
    monkeypatch.setenv('PERSON_REPORT_SEMANTIC_REVIEW_ENABLED','true')
    monkeypatch.setenv('PERSON_REPORT_REPAIR_REJECTED','true')
    project=SimpleNamespace(target_name='林知远',title='合成管理研究',target_type='person',sources=[],person_research_intake={})
    roles=[]
    def invoke(role,prompt,*args):
        roles.append(role)
        if '语义复核' in role:return ''
        data=json.loads(prompt.splitlines()[-1])
        return json.dumps({'claims':[{'evidence_ids':[data['facts'][0]['evidence_id']],
                                     'analysis':'来源载明林知远于2018年担任董事长兼总裁，负责研发管理；上述为历史任职记录。'}]})
    payload={'facts':[{'fact':'林知远于2018年担任远山科技董事长兼总裁，负责研发管理，任职期限以该历史时期为限。',
                       'source_url':'https://fixture.invalid/retained','identity_match':'confirmed'}]}
    generate_person_report(project,json.dumps(payload,ensure_ascii=False),'{}',PERSON_REPORT_OUTLINE,invoke,lambda *a,**kw:None)
    diagnostic=project.person_delivery_diagnostic['section_diagnostics'][5]
    assert diagnostic['pending_review_analysis_count']==1
    assert diagnostic['semantic_review']['status']=='invalid_structured_response'
    assert not any('核验修订' in role for role in roles)


def test_report_repairs_only_explicitly_unsupported_analysis(monkeypatch):
    from person_evidence import generate_person_report
    from report_agents.person_report_agent import PERSON_REPORT_OUTLINE
    monkeypatch.setenv('PERSON_REPORT_SEMANTIC_REVIEW_ENABLED','true')
    monkeypatch.setenv('PERSON_REPORT_REPAIR_REJECTED','true')
    project=SimpleNamespace(target_name='林知远',title='合成管理研究',target_type='person',sources=[],person_research_intake={})
    original_good='来源记载2018年董事长任职，职责涉及研发管理。'
    repaired=[]
    def invoke(role,prompt,*args):
        if '核验修订' in role:
            packet=json.loads(prompt[prompt.index('{"material":'):])
            repaired.append(packet)
            assert original_good not in json.dumps(packet['corrections'],ensure_ascii=False)
            assert len(packet['response_schema']['claims'])==1
            eid=packet['response_schema']['claims'][0]['evidence_ids'][0]
            return json.dumps({'claims':[{'evidence_ids':[eid],
                'analysis':'来源记载2019年的总裁任职及研发管理职责。'}]})
        packet=json.loads(prompt.splitlines()[-1])
        if '语义复核' in role:
            reviews=[{'claim_index':i,'verdict':'supported','supporting_evidence_ids':c['evidence_ids']}
                     for i,c in enumerate(packet['claims'])]
            if '修订后' not in role:
                reviews[1]={'claim_index':1,'verdict':'unsupported','issues':['inference_gap'],
                            'reason':'合成用例：此项需要修订'}
            return json.dumps({'reviews':reviews})
        if '第5章' not in prompt:return '{"claims":[]}'
        a=next(f for f in packet['facts'] if '2018' in f['fact'])
        b=next(f for f in packet['facts'] if '2019' in f['fact'])
        return json.dumps({'claims':[{'evidence_ids':[a['evidence_id']],'analysis':original_good},
            {'evidence_ids':[b['evidence_id']],'analysis':'来源载明2019年担任总裁，负责研发管理。'}]})
    payload={'facts':[{'fact':'林知远于2018年担任远山科技董事长，负责研发管理。',
                       'source_url':'https://fixture.invalid/a','identity_match':'confirmed'},
                      {'fact':'林知远于2019年担任远山科技总裁，负责研发管理。',
                       'source_url':'https://fixture.invalid/b','identity_match':'confirmed'}]}
    report=generate_person_report(project,json.dumps(payload,ensure_ascii=False),'{}',PERSON_REPORT_OUTLINE,invoke,lambda *a,**kw:None)
    assert len(repaired)==1 and original_good in report
    diagnostic=project.person_delivery_diagnostic['section_diagnostics'][5]
    assert diagnostic['accepted_analysis_count']==2
    assert diagnostic['semantic_review']['rewritten_claim_indices']==[1]
    assert diagnostic['semantic_review']['preserved_other_claims']==1


def test_repair_only_compresses_changed_claim_and_reserves_accepted_prose():
    from person_claim_repair import repair_once
    from person_evidence import validate_model_claims
    from person_prose_budget import prose_chars
    from test_person_complete_material import facts
    package={**facts(2),'writing_contract':'evidence_selection_v2'}
    package['facts']=package['research_facts']
    good={'evidence_ids':[package['facts'][0]['evidence_id']],
          'analysis':'来源记载历史任职，不证明当前职责。'*12}
    bad={'evidence_ids':[package['facts'][1]['evidence_id']], 'analysis':'来源称持股99999万股。'}
    answer=json.dumps({'claims':[good,bad]},ensure_ascii=False)
    claims,reasons=validate_model_claims(answer,package)
    reserved=[{'analysis':'来源记载历史职务。'*10}]
    calls=[]
    def invoke(role,prompt,*args):
        calls.append(role)
        if '篇幅压缩' in role:
            packet=json.loads(prompt.splitlines()[-1])
            assert len(packet['draft'])==1
            assert packet['accepted_analyses_not_to_change'][0]['analysis']==good['analysis']
            text='来源记载历史任职，不证明当前职责。'
        else:text='来源记载历史任职，不证明当前职责。'*35
        return json.dumps({'claims':[{'evidence_ids':bad['evidence_ids'],'analysis':text}]},ensure_ascii=False)
    result,remaining,audit=repair_once(answer,package,{'chapter':9,'facts':package['facts']},
        claims,reasons,invoke,None,validate_model_claims,reserved_analyses=reserved)
    assert not remaining and len(calls)==2
    assert result[0]['analysis']==good['analysis']
    assert prose_chars([*result,*reserved])<=600
    assert audit['revision_compression']['compression']['status']=='returned_for_validation'


def test_oversized_invalid_raw_revision_is_rechecked_after_source_bound_compression():
    from person_claim_repair import repair_once
    from person_evidence import validate_model_claims
    from test_person_complete_material import facts
    p={**facts(1),'writing_contract':'evidence_selection_v2'};p['facts']=p['research_facts']
    eid=p['facts'][0]['evidence_id'];raw=json.dumps({'claims':[{'evidence_ids':[eid],'analysis':'持股99999万股。'}]})
    current,reasons=validate_model_claims(raw,p);calls=[]
    def invoke(role,prompt,*a):
        calls.append(role)
        text='来源称其现任公司董事。'*100 if len(calls)==1 else '来源记载历史任职，不证明当前职责。'
        return json.dumps({'claims':[{'evidence_ids':[eid],'analysis':text}]})
    result,remaining,audit=repair_once(raw,p,{'chapter':9,'facts':p['facts']},current,reasons,invoke,None,validate_model_claims)
    assert len(calls)==2 and not remaining and result[0]['analysis']
    assert audit['revision_compression']['raw_revision_rejections']
