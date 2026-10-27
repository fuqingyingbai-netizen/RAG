"""Provider methodology requires review; target query data stays protected."""
import json
from copy import deepcopy

import pytest
from report_agents.company_information_usage import (
    build_information_usage,information_records,finalize_usage,routing_fingerprint,
)
from report_agents.company_report_agent import COMPANY_REPORT_OUTLINE as OUTLINE
from test_company_information_usage import statement,decision


def method_statement(text='当事人信息以公开裁判文书内容为准，可能存在匿名化；查询主体可能作为关联方命中该文书。'):
    s=statement(text='能力声明：'+text);s['chapter']=2
    s['context'].update(field='能力声明',value=text,kind='platform_native_field',scope='platform_query_return')
    return s


def exclude(row,supported=True):
    iid=row['information_id']
    return {'information_id':iid,'status':'exclude','exclude_code':'non_substantive',
            'reason':'仅说明平台查询方法，没有研究目标的个案事实或查询结果。',
            'exclusion_check':{'information_id':iid,'exclusion_supported':supported,
                               'reason':'原文仅为服务方通用方法说明，未提供目标公司的具体事实。'}}


def test_two_supported_reviews_allow_generic_method_field_to_stay_only_in_ledger():
    s=method_statement();rows=information_records([s]);before=deepcopy(rows)
    p=finalize_usage(rows,{rows[0]['information_id']:exclude(rows[0])},{2:'old'},{'statements':[s]})
    row=p['records'][0]
    assert row['state']=='excluded_with_reason' and not row['uses']
    assert row['text']==s['text'] and row['provenance']==rows[0]['provenance']
    assert p['statement_to_information'][s['statement_id']]==row['information_id']
    assert rows==before


@pytest.mark.parametrize('mode',['missing','unsupported','empty_reason','wrong_id'])
def test_method_label_without_valid_independent_review_is_not_enough(mode):
    s=method_statement();rows=information_records([s]);d=exclude(rows[0])
    if mode=='missing':d.pop('exclusion_check')
    elif mode=='unsupported':d['exclusion_check']['exclusion_supported']=False
    elif mode=='empty_reason':d['exclusion_check']['reason']=''
    else:d['exclusion_check']['information_id']='another'
    p=finalize_usage(rows,{rows[0]['information_id']:d},{2:'old'},{'statements':[s]})
    assert p['records'][0]['uses'] and p['records'][0]['decision']['exclusion_overturned']


@pytest.mark.parametrize('value',[0,False,'未知','待查','查询返回0条文书','该公司涉及2023年案件，具体当事人待核。'])
def test_query_results_zero_unknown_and_mixed_case_facts_stay_protected(value):
    s=method_statement(str(value));s['context']['value']=value
    rows=information_records([s]);p=finalize_usage(rows,{rows[0]['information_id']:exclude(rows[0])},{2:'old'},{'statements':[s]})
    assert p['records'][0]['uses']


def test_actual_platform_field_cannot_borrow_method_exclusion():
    s=method_statement();s['context']['field']='诉讼记录'
    rows=information_records([s]);p=finalize_usage(rows,{rows[0]['information_id']:exclude(rows[0])},{2:'old'},{'statements':[s]})
    assert p['records'][0]['uses']


def test_only_method_candidate_rechecks_old_routing_and_gets_independent_exclusion():
    a=method_statement();b=statement('T-2');digest={'statements':[a,b]};scope={'as_of_date':'2026-10-24'}
    records=information_records(digest['statements']);calls=[]
    old=finalize_usage(records,{r['information_id']:decision(r,chapter=2,aspect=OUTLINE[1][1][0]) for r in records},{},digest)
    old.update(target_name='某公司',review_scope=scope,legacy_scope_verified=True,
               routing_record_hashes={r['information_id']:routing_fingerprint(r,'某公司',scope,OUTLINE) for r in records})
    # Reproduce a policy predating the method-field hash; legacy scope does
    # not authorize skipping the current targeted review.
    old['routing_record_hashes'][records[0]['information_id']]='old-policy-hash'
    def invoke(role,prompt,trace):
        calls.append(role)
        assert records[1]['information_id'] not in prompt
        if role=='公司信息排除独立核对':return json.dumps({'records':[exclude(records[0])['exclusion_check']]})
        return json.dumps({'records':[exclude(records[0])]})
    result=build_information_usage(digest,{},OUTLINE,'某公司',invoke,previous=old,review_scope=scope,workers=1)
    assert calls==['公司信息逐项用途核对','公司信息排除独立核对']
    assert result['records'][0]['state']=='excluded_with_reason'
    assert result['records'][1]['uses'] and result['diagnostic']['cached_information_records']==1
