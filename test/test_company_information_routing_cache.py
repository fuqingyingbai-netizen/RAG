from copy import deepcopy
import json

import pytest

from report_agents.company_information_usage import build_information_usage, bind_legacy_routing_scope
from test_company_information_usage import statement, decision, OUTLINE

SCOPE={'as_of_date':'2026-10-24','declared_industry':'办公软件'}


def run(statements,previous=None,scope=None,outline=None):
    calls=[];events=[]
    def invoke(role,prompt,trace):
        calls.append(role)
        rows=json.loads(prompt.rsplit('\n信息：\n',1)[1])
        return json.dumps({'records':[decision(r) for r in rows]},ensure_ascii=False)
    package=build_information_usage({'statements':statements},{8:'原文待组织'},outline or OUTLINE,'测试公司',invoke,
        previous=previous,review_scope=SCOPE if scope is None else scope,workers=1,
        emit=lambda *a,**k:events.append(a[3]))
    return package,calls,events


def inputs():return [statement(),statement('T-2','平台披露研发团队有24人，按所载口径观察。')]


def test_identical_source_inputs_reuse_only_checked_routes_without_changing_information():
    first,_,events=run(inputs());second,calls,reused=run(inputs(),first)
    assert '信息逐条用途核对完成' in events and '复用同一输入的信息用途判定' in reused
    assert calls==[] and second['diagnostic']['cached_information_records']==2
    assert first['records']==second['records']


@pytest.mark.parametrize('change',['text','source_kind','source_url','evidence_ids','new_semantic_zero'])
def test_changed_source_or_semantic_field_is_reviewed_again(change):
    first,_,_=run(inputs());rows=inputs()
    if change=='text':rows[0]['text']+='原表另载一个独立条件。'
    elif change=='source_kind':rows[0]['context']['source_kind']='issuer_disclosure'
    elif change=='source_url':rows[0]['source_url']='https://different.test/original'
    elif change=='evidence_ids':rows[0]['evidence_ids']=['E-999999ABCDEF']
    else:rows[0]['context']['new_unmapped_field']=0
    second,calls,_=run(rows,first)
    assert len(calls)==1 and second['diagnostic']['cached_information_records']==1
    assert len(second['records'])==2 and not second['diagnostic']['pending_information_ids']


@pytest.mark.parametrize('scope',[{**SCOPE,'as_of_date':'2026-09-30'},
    {**SCOPE,'declared_industry':'调味品'},{**SCOPE,'focus_questions':['融资实际净额']}])
def test_changed_date_industry_or_question_never_inherits_old_routes(scope):
    first,_,_=run(inputs());second,calls,_=run(inputs(),first,scope)
    assert calls and second['diagnostic']['cached_information_records']==0


def test_template_change_and_incomplete_receipts_are_not_cache_hits():
    first,_,_=run(inputs());outline=deepcopy(OUTLINE);outline[7]=(outline[7][0]+'新边界',outline[7][1])
    changed,calls,_=run(inputs(),first,outline=outline)
    assert calls and changed['diagnostic']['cached_information_records']==0
    broken=deepcopy(first);iid=broken['records'][0]['information_id'];broken['routing_record_hashes'][iid]='invalid'
    changed,calls,_=run(inputs(),broken)
    assert calls and changed['diagnostic']['cached_information_records']==1
    broken=deepcopy(first);broken['records'][0]['decision']['voice']=''
    assert run(inputs(),broken)[0]['diagnostic']['cached_information_records']==1


def test_legacy_routes_require_exact_report_scope_and_known_template_binding():
    first,_,_=run(inputs());old=deepcopy(first);old['version']='company-information-usage-v2-semantic-context'
    old.pop('review_scope');old.pop('routing_record_hashes')
    assert run(inputs(),old)[1]
    review={'version':'company-corpus-v6-explicit-research-scope','target_name':'测试公司',
        'research_as_of':SCOPE['as_of_date'],'research_context':{'declared_industry':'办公软件'}}
    version='company-report-evidence-v99-native-operating-accounting-tables'
    bound=bind_legacy_routing_scope(old,'测试公司',SCOPE,review,version)
    assert run(inputs(),bound)[1]==[]
    assert bind_legacy_routing_scope(old,'其他公司',SCOPE,review,version)=={}
    assert bind_legacy_routing_scope(old,'测试公司',{**SCOPE,'as_of_date':'2026-09-30'},review,version)=={}
    assert bind_legacy_routing_scope(old,'测试公司',SCOPE,review,'unknown')=={}
    assert bind_legacy_routing_scope(old,'测试公司',{},review,version)=={}


def test_exclusions_are_rechecked_instead_of_silently_reusing_absence():
    row=statement(text='术语的一般定义，无企业特定内容。');iid=None;calls=[]
    from report_agents.company_information_usage import information_records
    iid=information_records([row])[0]['information_id']
    def invoke(role,*args):
        calls.append(role)
        if '排除独立' in role:return json.dumps({'records':[{'information_id':iid,'exclusion_supported':True,'reason':'一般定义而非公司事实'}]})
        return json.dumps({'records':[{'information_id':iid,'status':'exclude','exclude_code':'generic_definition','reason':'仅解释一般术语，没有公司特定事实'}]})
    first=build_information_usage({'statements':[row]},{},OUTLINE,'测试公司',invoke,review_scope=SCOPE)
    calls.clear();second=build_information_usage({'statements':[row]},{},OUTLINE,'测试公司',invoke,previous=first,review_scope=SCOPE)
    assert len(calls)==2 and second['diagnostic']['cached_information_records']==0
