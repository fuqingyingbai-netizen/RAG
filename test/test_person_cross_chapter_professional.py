"""Offline physical-field/reference checks, not live model acceptance."""
import copy
import json
import pytest
from person_cross_chapter_tables import (attach_professional_table_references,
    reference_rows,reference_lines,validate_report_references)
from person_structured_tables import structured_tables
from person_material_accounting import diagnose_material
from person_content_acceptance import check_coverage
from person_evidence import validate_model_claims


def fixture(target='陈安'):
    role={'evidence_id':'E-PCROSSREF001','fact':target+'；历史记录；'+json.dumps({
        '企业名称':'恒川软件有限公司','职位':'董事长','任职起止时间':'开始时间:2018-10-15,结束时间:2024-06-20',
        '成立日期':'1995-02-10','持股比例':'16.9%'},ensure_ascii=False),
        'source_url':'structured://fixture/historical/role','subject':target,'subject_scope':'person',
        'claim_type':'person_platform_record','analysis_allowed':False}
    company={'evidence_id':'E-PCROSSREF002','fact':'恒川软件有限公司；注册资本100万元；状态存续。',
        'source_url':'structured://fixture/company','subject':'恒川软件有限公司','subject_scope':'affiliated_company',
        'claim_type':'person_company_record','analysis_allowed':False}
    chapters={n:{'chapter':n,'title':'章节'+str(n),'task':'核对任职与持股原始记录。',
        'facts':[],'research_facts':[],'writing_contract':'evidence_selection_v2'} for n in range(1,16)}
    for n,rows in [(4,[company]),(9,[role]),(10,[role,company])]:
        chapters[n].update(facts=rows,research_facts=rows)
    c={'target_name':target,'facts':[role,company],'chapters':chapters}
    attach_professional_table_references(c)
    return c,role,company


def physical_report(c):
    return '\n\n'.join('## '+str(n)+'. 章节'+str(n)+'\n'+
        '\n'.join(structured_tables(p)+reference_lines(p)) for n,p in c['chapters'].items())


def diagnosed(c):
    def forbidden(*args):raise AssertionError('An already rendered typed field needs no new model verdict')
    d=diagnose_material(c['chapters'][10],[],forbidden,None)
    return d,{10:{'content_acceptance':{'material_diagnosis':d}}}


@pytest.mark.parametrize('target',['陈安','欧阳清和','Alex Morgan'])
def test_exact_professional_fields_are_referenced_without_duplicate_prose_or_permission_promotion(target):
    c,role,company=fixture(target);d,diagnostics=diagnosed(c)
    assert d['status']=='passed' and d['counts']=={'table_reference':2} and d['requests']==0
    assert {r['referenced_chapter'] for r in d['rows']}=={4,9}
    assert validate_report_references(physical_report(c),c,diagnostics)==[]
    assert not role['analysis_allowed'] and not company['analysis_allowed']
    claims,errors=validate_model_claims(json.dumps({'claims':[{'analysis':target+'个人信用良好。',
        'evidence_ids':[company['evidence_id']]}]}),c['chapters'][10])
    assert errors and not claims[0]['analysis']
    assert '公司字段不认定个人贡献' in '\n'.join(reference_lines(c['chapters'][10]))


@pytest.mark.parametrize('change',['missing_row','changed_date','changed_company','lost_historical_scope','missing_reference_note'])
def test_a_planned_reference_never_certifies_missing_or_changed_physical_fields(change):
    c,role,company=fixture();d,diagnostics=diagnosed(c);text=physical_report(c)
    row=next(line for line in structured_tables(c['chapters'][9]) if '['+role['evidence_id']+']' in line)
    if change=='missing_row':text=text.replace(row,'')
    elif change=='changed_date':text=text.replace('2024-06-20','2025-06-20')
    elif change=='changed_company':text=text.replace('恒川软件有限公司（历史）','远山科技有限公司（历史）')
    elif change=='lost_historical_scope':text=text.replace('恒川软件有限公司（历史）','恒川软件有限公司（平台所列）')
    else:text=text.replace(next(line for line in reference_lines(c['chapters'][10]) if '第9章' in line),'')
    errors=validate_report_references(text,c,diagnostics)
    assert any(e['evidence_id']==role['evidence_id'] for e in errors)


@pytest.mark.parametrize('change',['source_text','source_actor','source_url','target','wrong_origin'])
def test_stale_or_wrong_source_and_target_bindings_remain_pending(change):
    c,role,company=fixture();d,diagnostics=diagnosed(c);text=physical_report(c)
    if change=='source_text':role['fact']=role['fact'].replace('16.9%','26.9%')
    elif change=='source_actor':role['subject']='另一个人'
    elif change=='source_url':role['source_url']='structured://fixture/other-source'
    elif change=='target':c['target_name']='另一个人'
    else:d['rows'][0]['referenced_chapter']=12
    assert validate_report_references(text,c,diagnostics)


def test_actual_referenced_fields_can_cover_prior_role_dates_with_all_scope_labels_visible():
    c,role,company=fixture();p=c['chapters'][10];packets=[]
    prior=[{'analysis':'平台历史记录载陈安任恒川软件董事长的区间为2018-10-15至2024-06-20。',
            'evidence_ids':[role['evidence_id']]}]
    def model(role_name,prompt,*args):
        data=json.loads(prompt.splitlines()[-1]);packets.append(data)
        row=next(t for t in data['tables'] if t.get('referenced_chapter')==9)
        assert '成立日期：1995-02-10' in row['text'] and '任职起止时间' in row['text']
        assert row['record_source_fields'][0]['fact']==role['fact']
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[],
            'matched_table_indices':[row['table_index']],'gaps':[],'reason':'逐字段保留同一企业历史任职区间，不以成立日期代替任职。'}]})
    audit=check_coverage(p,[],prior,model,None)
    assert audit['status']=='passed' and len(packets)==1


def test_unstructured_statements_do_not_gain_automatic_cross_chapter_table_coverage():
    c,role,company=fixture();plain={'evidence_id':'E-PCROSSREF003','fact':'陈安对公司管理提出一项看法。',
        'source_url':'https://fixture.invalid/comment','subject':'陈安','subject_scope':'person',
        'claim_type':'source_statement','analysis_allowed':True}
    c['facts'].append(plain);c['chapters'][10]['research_facts'].append(plain)
    attach_professional_table_references(c);seen=[]
    def model(role_name,prompt,*args):
        data=json.loads(prompt.splitlines()[-1]);seen.extend(f['evidence_id'] for f in data['facts'])
        return json.dumps({'material_reviews':[{'evidence_id':plain['evidence_id'],'disposition':'appendix',
            'reason':'只是未说明具体任职或持股的管理看法，不用于本章任职字段核查。'}]})
    d=diagnose_material(c['chapters'][10],[],model,None)
    assert d['status']=='passed' and seen==[plain['evidence_id']]
    assert d['counts']=={'table_reference':2,'appendix':1}


@pytest.mark.parametrize('case',['other_actor','comparison_scope','other_person_scope','comparison_subject','team_member'])
def test_other_people_and_comparison_records_never_become_target_field_references(case):
    c,role,company=fixture()
    if case=='other_actor':role['subject']='另一个人'
    elif case=='comparison_scope':role['subject_scope']='comparison_person'
    elif case=='other_person_scope':role['subject_scope']='other_person'
    elif case=='comparison_subject':role['comparison_subject']='另一个人'
    else:role['team_member_name']='另一个人'
    attach_professional_table_references(c)
    assert all(role['evidence_id'] not in r['evidence_ids'] for r in reference_rows(c['chapters'][10]))
    assert role in c['facts'] and role['fact'].endswith('}')


def test_a_mixed_actor_native_row_cannot_be_automatically_certified_as_target_fields():
    c,role,company=fixture();other={**role,'evidence_id':'E-PCROSSOTHER01','subject':'另一个人',
        'subject_scope':'comparison_person','comparison_subject':'另一个人'}
    c['facts'].append(other);c['chapters'][9]['research_facts'].append(other)
    attach_professional_table_references(c)
    assert all(role['evidence_id'] not in r['evidence_ids'] for r in reference_rows(c['chapters'][10]))
