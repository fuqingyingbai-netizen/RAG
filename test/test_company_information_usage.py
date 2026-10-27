import json

from report_agents.company_information_usage import (
    information_records,finalize_usage,validate_review,build_information_usage,
    render_information_sections,append_information_markdown,
)
from report_agents.company_report_agent import COMPANY_REPORT_OUTLINE as OUTLINE


def statement(sid='T-1',text='平台载明本期招聘研发岗位，不等于已入职人数。',url='https://platform.test/company'):
    return {'statement_id':sid,'chapter':8,'text':text,'evidence_ids':['E-123456ABCDEF'],
        'context':{'source_kind':'professional_platform_record','period':'数据基准日未载','scope':'target'},
        'origin':'literal_original_statement','source_url':url,'source_title':'招聘平台原表'}


def decision(row,**kwargs):
    return {'information_id':row['information_id'],'status':'use','chapter':8,
        'aspect':'团队激励与人才结构现状','relevance':'招聘岗位是人才配置观察，不能转成实际人数。',
        'voice':'平台招聘记录',**kwargs}


def test_same_text_different_url_is_one_information_with_every_source():
    rows=information_records([statement(),statement('T-2',url='https://second.test/company')])
    assert len(rows)==1 and len(rows[0]['statement_ids'])==2
    assert {p['source_url'] for p in rows[0]['provenance']}=={'https://platform.test/company','https://second.test/company'}


def test_different_fields_periods_and_numeric_precision_are_not_fuzzy_duplicates():
    a=statement();b=statement('T-2');b['context']={**b['context'],'period':'2025年度'}
    c=statement('T-3','平台记录持股比例8.52%。');d=statement('T-4','平台记录持股比例8.5214%。')
    assert len(information_records([a,b,c,d]))==4


def test_support_ids_are_not_actual_semantic_use_and_missing_calls_stay_pending():
    s=statement();rows=information_records([s])
    digest={'statements':[s],'groups':[{'group_id':'G1','statement_ids':['T-1']}]}
    package=finalize_usage(rows,{}, {8:'原文只概括人才问题。'},digest)
    row=package['records'][0]
    assert row['prior_group_ids']==['G1'] and row['prior_exact_body_chapters']==[]
    assert row['uses']==[] and row['state']=='pending_review'
    assert package['diagnostic']['pending_information_ids']==[row['information_id']]


def test_every_literal_atom_maps_to_actual_chapter_content_and_html_is_escaped():
    s=statement(text='平台记录招聘岗位。<script>alert(1)</script>须按原文归因。')
    rows=information_records([s]);package=finalize_usage(rows,{rows[0]['information_id']:decision(rows[0])},{8:'old'},{'statements':[s]})
    output=render_information_sections(package,OUTLINE)[8]
    assert '<script>' not in output and '&lt;script&gt;' in output
    assert package['atoms'] and all(a['uses'] for a in package['atoms'])
    assert rows[0]['information_id'] in output and '平台记录招聘岗位' in output
    assert '平台记录招聘岗位' in append_information_markdown(package,{8:'old'},OUTLINE)[8]


def test_safe_numeric_chapter_string_does_not_block_usable_information():
    rows=information_records([statement()]);d=decision(rows[0],chapter='8')
    accepted,errors=validate_review(rows,{'records':[d]},OUTLINE)
    assert not errors and accepted[rows[0]['information_id']]['chapter']==8


def test_exclusion_requires_independent_support_and_never_source_class():
    s=statement();digest={'statements':[s]}
    def invoke(role,prompt,trace):
        if role=='公司信息排除独立核对':
            iid=information_records([s])[0]['information_id']
            return json.dumps({'records':[{'information_id':iid,'exclusion_supported':False,'reason':'招聘原字段可用，不能因不是员工人数就排除'}]})
        iid=information_records([s])[0]['information_id']
        return json.dumps({'records':[{'information_id':iid,'status':'exclude','exclude_code':'non_substantive','reason':'不能推定员工人数，不形成财务评分'}]})
    package=build_information_usage(digest,{8:'old'},OUTLINE,'公司',invoke,workers=1)
    row=package['records'][0]
    assert row['state']=='used_in_chapter_detail' and row['decision']['exclusion_overturned']


def test_failed_review_cannot_turn_into_no_valid_information():
    def fail(*args):raise RuntimeError('model transport unavailable')
    package=build_information_usage({'statements':[statement()]},{8:'old'},OUTLINE,'公司',fail,workers=1)
    assert len(package['diagnostic']['pending_information_ids'])==1
    assert package['records'][0]['state']=='pending_review'


def test_published_conditional_policy_is_used_as_policy_without_inventing_an_event():
    s=statement(text='若发生合并收购，我们会要求继受方继续履行个人信息保护义务。')
    s['context']['source_kind']='service_self_attribution';s['source_title']='DeepSeek隐私政策'
    rows=information_records([s]);iid=rows[0]['information_id']
    package=finalize_usage(rows,{iid:{'status':'exclude','exclude_code':'non_substantive','reason':'没有实际发生的并购事项'}},{8:'old'},{'statements':[s]})
    row=package['records'][0]
    assert row['uses'][0]['chapter']==4 and row['uses'][0]['aspect']=='执行流程'
    assert row['decision']['voice']=='服务方公布的条款，非执行效果核验'
    assert s['text'] in render_information_sections(package,OUTLINE)[4]


def test_platform_unknown_field_is_information_and_cannot_be_excluded_for_no_score():
    s=statement(text='待查');s['chapter']=2;s['context']['field']='公司盈利情况'
    rows=information_records([s]);iid=rows[0]['information_id']
    package=finalize_usage(rows,{iid:{'status':'exclude','exclude_code':'non_substantive','reason':'未知值不能支持评分'}},{2:'old'},{'statements':[s]})
    assert package['records'][0]['uses'][0]['aspect']=='主体工商信息表'
    assert '公司盈利情况：待查' in render_information_sections(package,OUTLINE)[2]


def test_reprinted_policy_is_retained_with_reprint_attribution():
    s=statement(text='作为本服务的使用者，您不得恶意对抗本服务的过滤机制。')
    s['context']['source_kind']='attributed_publication';s['source_title']='DeepSeek用户协议 法务网转载'
    rows=information_records([s]);iid=rows[0]['information_id']
    package=finalize_usage(rows,{iid:{'status':'exclude','exclude_code':'generic_definition','reason':'属于通用安全条款，没有已发生事项'}},{8:'old'},{'statements':[s]})
    assert package['records'][0]['uses'][0]['chapter']==4
    assert package['records'][0]['decision']['voice']=='原站刊载的条款文本，原发布版本与执行效果另核'


def test_unique_exact_aspect_repairs_chapter_mismatch_without_dropping_information():
    rows=information_records([statement()]);d=decision(rows[0],chapter=2,aspect='历史工商变更')
    result,errors=validate_review(rows,{'records':[d]},OUTLINE)
    assert not errors and result[rows[0]['information_id']]['chapter']==3


def test_repair_preserves_prior_accepted_records_and_requests_only_missing_information():
    a=statement();b=statement('T-2','平台原表另列另一类岗位，不能据此视作实际员工数。')
    records=information_records([a,b]);calls=[]
    def invoke(role,prompt,trace):
        calls.append(prompt)
        if len(calls)==1:return json.dumps({'records':[decision(records[0])]})
        assert records[0]['information_id'] not in prompt.split('信息：\n')[1].split('\n第')[0]
        return json.dumps({'records':[decision(records[1])]})
    p=build_information_usage({'statements':[a,b]},{8:'old'},OUTLINE,'公司',invoke,workers=1)
    assert len(calls)==2 and not p['diagnostic']['pending_information_ids']
    assert all(r['uses'] for r in p['records'])
