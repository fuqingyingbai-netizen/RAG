"""All relevant evidence reaches research; concise display is a later step."""
import json
from types import SimpleNamespace

from person_chapter_selection import select_material
from person_evidence import build_packages, validate_model_claims, render_section
from person_material_review import material_batches, read_then_write, presentation_facts
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


def facts(count=40):
    rows=[{'fact':f'林知远在第{i+1}份公开记录中担任远山科技董事，持股数量为{i+1}万股，历史职位不等于当前职责。',
        'source_url':'https://official.invalid/retained', 'source_title':'完整任职记录',
        'identity_match':'confirmed','source_grade':'B'} for i in range(count)]
    return build_packages({'facts':rows},'林知远',PERSON_REPORT_OUTLINE)['chapters'][9]


def test_a_busy_source_is_fully_researched_before_display_budget():
    package=facts()
    assert len(package['research_facts'])==40
    assert len(package['facts'])<40
    assert not any(a['reason'] in {'chapter_capacity','source_concentration','domain_concentration','same_member_profile'}
        for a in package['research_selection_audit'])
    last=package['research_facts'][-1]
    claims=[{'evidence_ids':[last['evidence_id']], 'analysis':'来源记载历史任职，不证明当前职责。'}]
    displayed=presentation_facts(package,claims,max_records=3,max_chars=180)
    assert last in displayed and len(displayed)<=3
    rendered=render_section({**package,'display_facts':displayed},claims)
    assert last['evidence_id'] in rendered
    # Readiness and source quotas do not disappear by relabeling an omitted
    # card: the late record is actually in the research package and body input.
    assert last['evidence_id'] in {f['evidence_id'] for f in package['research_facts']}


def test_structured_start_and_end_dates_are_not_a_news_listing():
    text='林知远；查询定位机构：恒川软件；历史记录；'+json.dumps({'任职起止时间':'开始时间:2018-10-15,结束时间:2024-12-20','企业名称':'远山科技有限公司','职位':'董事长'},ensure_ascii=False)
    row={'fact':text,'source_url':'structured://qcc/positions','identity_match':'confirmed',
         'claim_type':'person_platform_record','person_chapters':[2,9,10]}
    result=build_packages({'facts':[row]},'林知远',PERSON_REPORT_OUTLINE,
        {'special_requirements':'核对任职变化'})
    for n in [2,9,10]:
        assert text in {f['fact'] for f in result['chapters'][n]['research_facts']}
    from person_chapter_selection import useful_for_chapter
    assert not useful_for_chapter({'fact':'林知远相关新闻 2018-10-15 2024-12-20 更多新闻'},9)


def test_contained_display_quote_does_not_repeat_its_larger_original():
    package=facts(1)
    short={**package['facts'][0],'evidence_id':'E-PSHORT0001','fact':'林知远在公开记录中担任远山科技董事，负责公司技术管理。'}
    long={**short,'evidence_id':'E-PLONG00001','fact':short['fact']+'该来源说明上述资料为历史时点，不代表当前职责。'}
    package.update(facts=[short,long],research_facts=[short,long])
    claims=[{'analysis':'来源说明历史任职及职责。','evidence_ids':[short['evidence_id'],long['evidence_id']]}]
    assert presentation_facts(package,claims)==[long]


def test_batch_budget_never_drops_a_long_original_or_late_record():
    rows=[{'evidence_id':str(i),'fact':'原文'*size} for i,size in enumerate([20,25,600,15,40])]
    batches=material_batches(rows,max_chars=180)
    assert [r for batch in batches for r in batch]==rows
    assert any(len(batch)==1 and batch[0]['evidence_id']=='2' for batch in batches)


def test_all_batches_feed_final_synthesis_including_last_source(monkeypatch):
    monkeypatch.setenv('PERSON_RESEARCH_BATCH_CHARS','4000')
    package={**facts(80),'writing_contract':'evidence_selection_v2'}
    rows=[{k:f[k] for k in ['evidence_id','fact','subject']} for f in package['research_facts']]
    delivered=[]
    final_received=[]
    def invoke(role,prompt,emit):
        data=json.loads(prompt.splitlines()[-1])
        if role.endswith('综合写作'):
            final_received.extend(data['research_findings'])
            return json.dumps({'claims':[data['research_findings'][-1]]},ensure_ascii=False)
        delivered.extend(r['evidence_id'] for r in data['facts'])
        return json.dumps({'claims':[{'evidence_ids':[data['facts'][-1]['evidence_id']],
            'analysis':'来源记载历史任职，不证明当前职责。'}]},ensure_ascii=False)
    answer,calls=read_then_write('章节Agent','仅用给定原文。\n',{'facts':rows},package,invoke,None,validate_model_claims)
    assert delivered==[r['evidence_id'] for r in rows]
    assert len(package['material_review']['batches'])>1
    assert calls==len(package['material_review']['batches'])+1
    assert final_received and json.loads(answer)['claims'][0]['evidence_ids']==[rows[-1]['evidence_id']]
    assert not package['material_review']['omitted_for_input_budget']


def test_failed_batch_cannot_be_presented_as_complete(monkeypatch):
    import pytest
    monkeypatch.setenv('PERSON_RESEARCH_BATCH_CHARS','4000')
    package={**facts(80),'writing_contract':'evidence_selection_v2'}
    rows=[{k:f[k] for k in ['evidence_id','fact','subject']} for f in package['research_facts']]
    def invoke(*a):
        raise TimeoutError('retained test timeout')
    with pytest.raises(TimeoutError):
        read_then_write('章节Agent','仅用给定原文。\n',{'facts':rows},package,invoke,None,validate_model_claims)
    assert package['material_review']['status']=='failed'
    assert package['material_review']['batches'][0]['status']=='failed'


def test_distinct_findings_get_display_slots_before_repeated_supports():
    package = facts(12)
    rows = package['research_facts']
    claims = [{'analysis': '第一项判断', 'evidence_ids': [r['evidence_id'] for r in rows[:4]]},
              {'analysis': '另一事项', 'evidence_ids': [rows[-1]['evidence_id']]}]
    shown = presentation_facts(package, claims, max_records=2)
    assert [f['evidence_id'] for f in shown] == [rows[0]['evidence_id'], rows[-1]['evidence_id']]


def test_summary_keeps_different_findings_without_repeating_same_support():
    from person_material_tables import distinct_inherited_analyses
    claims = {5: [{'analysis': '历史授权安排', 'evidence_ids': ['a']}],
              11: [{'analysis': '再次叙述同一授权', 'evidence_ids': ['a']},
                   {'analysis': '另一退出安排', 'evidence_ids': ['b']}]}
    assert [r['analysis'] for r in distinct_inherited_analyses(claims, [5, 11])] == ['历史授权安排', '另一退出安排']


def test_repeated_original_is_quoted_once_while_chapter_citations_remain():
    from person_evidence import generate_person_report, split_sections, cited_ids
    original = '林知远于2021年担任远山科技董事，持股数量为30万股，任职期限与变更情况仍需核对。'
    project = SimpleNamespace(target_name='林知远', title='合成尽调', target_type='person', sources=[],
        person_research_intake={'focus_questions': ['核对历史任职及持股变化']})
    report = generate_person_report(project, json.dumps({'facts': [{'fact': original,
        'source_url': 'https://fixture.invalid/retained', 'identity_match': 'confirmed'}]}), '{}',
        PERSON_REPORT_OUTLINE, lambda *a: '{"claims":[]}', lambda *a, **kw: None)
    sections = split_sections(report)
    assert report.count('> ' + original) == 1
    assert '同一原文已列第2章' in sections[9]
    assert cited_ids(sections[9]) <= cited_ids(sections[14])
