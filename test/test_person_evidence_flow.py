"""Regressions for retained originals lost between cleaning and chapter use."""
import json
from types import SimpleNamespace

import pytest

from person_evidence import build_packages, normalize_facts, generate_person_report, split_sections
from person_chapter_selection import retained_management_events
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


def record(text, url='https://filing.invalid/a', **extra):
    return {'fact': text, 'source_url': url, 'source_title': '原始披露',
            'source_grade': 'A', 'identity_match': 'confirmed', **extra}


def test_dated_appointments_and_equity_survive_biography_capacity():
    rows = [record(f'林知远担任本公司董事长，持有公司{i+1}万股，曾签署股份转让协议。',
                   f'https://filing.invalid/{i}') for i in range(24)]
    cards = []
    for status, fields in [('平台所列（是否现任需核验）记录', {'任职起止时间': '开始时间:2017-01-01,结束时间:[]', '职位': '董事长'}),
                           ('历史记录', {'任职起止时间': '开始时间:[],结束时间:2022-03-01', '职位': '董事'}),
                           ('平台所列（是否现任需核验）记录', {'持股比例': '12%', '角色': ['股东']})]:
        text = f'林知远；查询定位机构：恒川软件有限公司；{status}；' + json.dumps({'企业名称': '恒川软件有限公司', **fields}, ensure_ascii=False)
        cards.append(record(text, f'structured://records/{len(cards)}', claim_type='person_platform_record', source_grade='C', person_chapters=[9, 10]))
    value = build_packages({'facts': rows + cards}, '林知远', PERSON_REPORT_OUTLINE,
                           {'target_name': '林知远', 'special_requirements': '核对任职及持股变化'})
    for n in [9, 10]:
        selected = value['chapters'][n]['facts']
        assert len(selected) <= 12
        assert {c['fact'] for c in cards} <= {f['fact'] for f in selected}
    assert not any(f.get('claim_type') == 'person_platform_record' for f in value['chapters'][7]['facts'])


@pytest.mark.parametrize('name,org', [('林知远','恒川软件'), ('沈岚','远山科技')])
def test_feedback_discovery_original_can_supply_other_event_chapters(name, org):
    event = f'2015年{name}在{org}年会上宣布全面裁撤小区经理，减少管理层级，并实行计件工资制度；该报道并未说明后续执行结果。'
    authority = f'{name}在{org}授予店长3万元的签字权限，100万元以上的签字须报其审批；此处为历史报道中的安排。'
    namesake = f'比如另一公司的首席执行官{name}参与接班计划，{org}的管理者也面临类似的问题。'
    personality = f'{org}的{name}在接班计划中看重善良，有人形容其性格温和，这是个主观评价并非人格鉴定。'
    source = SimpleNamespace(content='\n\n'.join([event, authority, namesake, personality]), url='https://news.invalid/interview',
        title='采访原文', source_metadata={'person_feedback_only': True, 'identity_confidence': 'high',
        'identity_status': 'accepted', 'content_kind': 'full_text', 'fetch_status': 'done'})
    intake = {'target_name': name, 'person_anchor': {'known_affiliations': [org]}}
    recovered = retained_management_events([source], intake)
    assert {r['fact'] for r in recovered} == {event, authority}
    packages = build_packages({'facts': []}, name, PERSON_REPORT_OUTLINE, intake, [source])
    assert event in {f['fact'] for f in packages['chapters'][5]['facts']}
    assert authority in {f['fact'] for f in packages['chapters'][11]['facts']}
    for n in [2, 3, 6, 7, 8, 9, 10, 12]:
        assert not packages['chapters'][n]['facts']
    # Existing exact-original and identity guards remain active.
    fabricated = {**recovered[0], 'fact': event.replace('2015', '2016'), 'evidence_quote': ''}
    accepted, rejected = normalize_facts({'facts': [fabricated]}, name, sources=[source])
    assert not accepted and rejected[0]['rejection_reason'] == 'statement_and_quote_not_in_original'
    source.source_metadata['identity_confidence'] = 'low'
    assert not retained_management_events([source], intake)


def test_cleaning_ledger_reports_real_exclusion_state():
    from research_workflow import ResearchWorkflow
    def source(i, **meta):
        return SimpleNamespace(id=i, url=f'https://news.invalid/{i}', title='人物介绍', content='明确的原文内容。' * 25,
            summary='', source_type='news', credibility_score=70,
            source_metadata={'identity_confidence': 'high', 'content_kind': 'full_text', **meta})
    sources = [source(1), source(2, content_kind='summary_only'), source(3, identity_confidence='low')]
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    rows = workflow._build_evidence_ledger(sources, sources, target_type='person')
    assert rows[0]['status'] == 'cleaned' and rows[0]['rejected_reason'] == ''
    assert rows[1]['status'] == 'discovery_only' and not rows[1]['deterministically_cleaned']
    assert rows[2]['rejected_reason'] == 'identity_quarantine' and not rows[2]['usable_for_hard_fact']


def test_feedback_packet_keeps_target_before_named_evaluator_and_full_sentence():
    from person_chapter_research import personal_feedback_packets
    text = '林知远在恒川软件敢于向下放权，顾海曾评价“这种明确权限的授权方式很少见”。该段为原作者转述的公开评价。' + '原报道未披露评价者是否存在投资利益关系，仍须独立核对其身份、立场以及评价对应的实际时期。' * 2
    src = SimpleNamespace(id=1, url='https://news.invalid/interview', content=text,
        source_metadata={'identity_confidence':'high','person_feedback_only':True,'content_kind':'full_text','fetch_status':'done'})
    packets = personal_feedback_packets([src], {'target_name':'林知远'})
    assert packets[0]['text'] == text


def test_announcement_and_repeated_title_do_not_create_personal_obligation():
    from person_chapter_research import feedback_event
    assert not feedback_event('董事长林知远宣布，恒川软件承诺为客户提供一年维修服务。林知远：恒川软件率先承诺兜底。', '林知远')
    assert feedback_event('林知远本人承诺在离任后十二个月内不转让持股。', '林知远')


def test_anonymous_reporter_and_neighboring_speech_do_not_become_named_evaluation():
    from person_chapter_research import validate_discovery
    text = '记者赞扬恒川软件的产品质量，林知远则表示公司将继续改进。' + '这是公开报道的逐字留存内容，未经独立核实。' * 6
    src = SimpleNamespace(id=1,title='报道',url='https://news.invalid/a',content=text,
        source_metadata={'identity_confidence':'high','content_kind':'full_text','fetch_status':'done'})
    answer=json.dumps({'feedback':[{'kind':'attributed_opinion','evaluator':'记者','quote':text,'source_url':src.url}]},ensure_ascii=False)
    assert not validate_discovery(answer,[src],{'target_name':'林知远'})[1]


def test_first_person_quote_keeps_its_literal_local_speaker_attribution():
    from person_chapter_research import validate_discovery
    statement='几年前，林知远来找我，希望我们合作开发新产品，我带他参观了实验室，后来双方就合作细节发生了分歧。'
    text='在顾海的回忆中又是另一个样子：“'+statement+'”\n\n'+'此段为历史争议中的单方公开陈述，来源未披露当事人回应及后续处理结果。'*3
    src=SimpleNamespace(id=1,title='历史报道',url='https://news.invalid/a',content=text,
        source_metadata={'identity_confidence':'high','content_kind':'full_text','fetch_status':'done'})
    answer=json.dumps({'feedback':[{'kind':'attributed_opinion','evaluator':'顾海','quote':statement,'source_url':src.url}]},ensure_ascii=False)
    _,records,rejected=validate_discovery(answer,[src],{'target_name':'林知远'})
    assert records and not rejected and '在顾海的回忆中' in records[0]['quote']


def test_literal_reporting_relationship_counts_as_employee_material_not_verification():
    from person_chapter_research import view_status
    found,selected,status=view_status(7,'员工与前同事评价',[{'fact':'具名来源陈述','feedback_record':{'relationship':'上下级'}}])
    assert found and selected and '仍需核对' in status


def test_management_event_keeps_adjacent_employee_response_and_other_actor():
    first='2015年林知远在恒川软件年会上宣布裁撤地区经理，减少管理层级，并在公司门店实行计件工资制度。'
    response='这次变革在恒川软件门店引起员工不满，有员工提出集体辞职，副总顾海决定停止试行；这些都是林知远后来才知道的。'
    source=SimpleNamespace(content=first+'\n\n'+response,url='https://news.invalid/a',title='采访',
        source_metadata={'person_feedback_only':True,'identity_confidence':'high','content_kind':'full_text','fetch_status':'done'})
    rows=retained_management_events([source],{'target_name':'林知远','person_anchor':{'known_affiliations':['恒川软件']}})
    assert rows[0]['fact']==source.content
    assert '副总顾海决定停止试行' in rows[0]['fact']


def test_recovered_event_persists_in_cleaned_facts_not_only_report_supplement(monkeypatch):
    from research_workflow import ResearchWorkflow
    monkeypatch.setenv('CLEANING_MODE','fast')
    monkeypatch.setenv('CLEANING_LLM_ENABLED','false')
    text='2015年林知远在恒川软件年会上宣布全面裁撤地区经理，减少管理层级，并实行计件工资制度；该报道没有给出量化经营效果。'
    src=SimpleNamespace(id=1,title='完整采访',url='https://news.invalid/a',content=text,summary='',source_type='news',
        credibility_score=70,source_metadata={'person_feedback_only':True,'identity_confidence':'high',
        'content_kind':'full_text','fetch_status':'done'})
    project=SimpleNamespace(id=1,target_name='林知远',target_type='person',sources=[src],
        person_research_intake={'target_name':'林知远','person_anchor':{'known_affiliations':['恒川软件']}})
    payload=json.loads(ResearchWorkflow.__new__(ResearchWorkflow).clean_sources(project,plan={'modules':[]},quality={'source_count':1}))
    assert any(f['fact']==text and f['claim_type']=='person_management_event' for f in payload['facts'])


def test_supplied_english_alias_survives_sentence_extraction_and_normalization():
    from research_workflow import ResearchWorkflow
    text='Evan Lin was appointed chief engineer at Hengchuan Software in 2018 and was responsible for the product research team.'
    src=SimpleNamespace(id=1,title='履历',url='https://official.invalid/profile',content=text,summary='',
        source_type='official',credibility_score=75,source_metadata={'identity_confidence':'high','content_kind':'full_text'})
    project=SimpleNamespace(target_name='林知远',person_research_intake={'person_anchor':{'aliases':['林知远','Evan Lin']}})
    wf=ResearchWorkflow.__new__(ResearchWorkflow)
    extracted=wf._extract_sentence_facts([src],project)
    assert len(extracted)==1 and extracted[0]['fact']==text
    accepted,rejected=normalize_facts({'facts':extracted},project.target_name,['Evan Lin'],[src])
    assert len(accepted)==1 and not rejected


def test_partial_replay_freezes_body_and_preserves_unresolved_review_gate():
    payload=json.dumps({'facts':[record('林知远担任恒川软件董事长，股东会授权其办理重大事项及公司股权转让。')]},ensure_ascii=False)
    project=SimpleNamespace(title='研究',target_name='林知远',sources=[],person_research_intake={},person_platform_attempts=[])
    calls=[]
    def invoke(role,*args):
        calls.append(role)
        return '{"claims":[]}'
    before=generate_person_report(project,payload,'{}',PERSON_REPORT_OUTLINE,invoke,lambda *a,**k:None)
    original_contract=project.person_evidence_contract
    original_audit=project.person_delivery_diagnostic
    sections=split_sections(before)
    retained={n:{'text':sections[n], 'selected_ids':[f['evidence_id'] for f in original_contract['chapters'][n]['facts']],
        'diagnostic':original_audit['section_diagnostics'][n], 'claims':[], 'gaps':[]}
        for n in range(2,13) if n!=9}
    retained[5]['diagnostic']={**retained[5]['diagnostic'],'unresolved_validation_rejections':['api_failed:timeout']}
    calls.clear()
    after=generate_person_report(project,payload,'{}',PERSON_REPORT_OUTLINE,invoke,lambda *a,**k:None,retained_sections=retained)
    assert len(calls)==1 and '关联利益' in calls[0]
    assert all(sections[n]==split_sections(after)[n] for n in retained)
    assert {'chapter':5,'reasons':['api_failed:timeout']} in project.person_delivery_diagnostic['degradations']
    retained[2]['selected_ids']=['wrong-id']
    with pytest.raises(ValueError,match='material changed'):
        generate_person_report(project,payload,'{}',PERSON_REPORT_OUTLINE,invoke,lambda *a,**k:None,retained_sections=retained)
