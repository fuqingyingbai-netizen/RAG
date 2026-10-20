import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from person_chapter_research import exact_span, validate_discovery, annotated_facts, collect, discovery_prompt, contextual_identity
from person_evidence import build_packages, render_section
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


def intake():
    return {'target_type': 'person', 'target_name': '林知远', 'ai_search_enabled': True,
            'person_anchor': {'known_affiliations': ['恒川软件'], 'aliases': []}}


def source(text, url='https://news.invalid/a', **metadata):
    return SimpleNamespace(id=1, url=url, content=text, title='公开来源', source_type='news', credibility_score=80,
                           source_metadata={'identity_confidence': 'high', 'content_kind': 'full_text', 'fetch_status': 'done', **metadata})


def discovery():
    quote = '远山软件董事长陈雨安曾负责企业软件产品。'
    basis = '恒川软件与远山软件同属软件行业，报道将林知远与陈雨安作为同业人物比较。'
    feedback = '2025年，恒川软件的客户顾海表示，林知远按合同约定交付了产品，但该评价仍代表顾海个人立场。'
    text = (quote + basis + feedback + '本报道仅记录公开陈述，不构成信用鉴定。') * 2
    row = {'name': '陈雨安', 'company': '远山软件', 'role': '董事长', 'industry': '软件', 'stage': '成熟期',
           'period': '2025', 'source_url': 'https://news.invalid/a', 'quote': quote, 'basis_quote': basis}
    opinion = {'kind': 'attributed_opinion', 'evaluator': '顾海', 'relationship': '客户',
               'quote': feedback, 'source_url': 'https://news.invalid/a', 'period': '2025'}
    return source(text), row, opinion


def test_exact_span_restores_whitespace_instead_of_changing_quotes():
    original = '来源称：林知远\n在 恒川软件 任职。'
    assert exact_span('来源称：林知远在恒川软件任职。', original) == original
    assert not exact_span('林知远在另一家公司任职。', original)


def test_nominations_keep_only_literal_fields_and_public_attribution():
    src, peer, feedback = discovery()
    peers, records, rejected = validate_discovery(json.dumps({'peers': [peer], 'feedback': [feedback]}), [src], intake())
    assert not rejected and peers[0]['industry'] == '软件'
    assert not peers[0]['stage'] and not peers[0]['period']
    assert records[0]['evaluator'] == '顾海'
    assert records[0]['status'] == 'published_statement_not_authorized_interview'


@pytest.mark.parametrize('field,value', [('name', '不存在的人'), ('company', '恒川软件'), ('basis_quote', '编造的同业关系')])
def test_hallucinated_or_target_company_peers_never_become_candidates(field, value):
    src, peer, _ = discovery()
    peer[field] = value
    assert not validate_discovery(json.dumps({'peers': [peer]}), [src], intake())[0]


def test_anonymous_feedback_self_praise_and_summary_only_are_not_public_credit_evidence():
    src, _, feedback = discovery()
    for actor in ('知情人士', '网友', '林知远'):
        feedback['evaluator'] = actor
        assert not validate_discovery(json.dumps({'feedback': [feedback]}), [src], intake())[1]
    src.source_metadata['content_kind'] = 'summary_only'
    assert not validate_discovery(json.dumps({'feedback': [feedback]}), [src], intake())[1]


def test_company_praise_does_not_turn_into_personal_opinion_by_widening_context():
    text = '恒川软件董事长林知远出席活动。客户顾海表示：“我们应该学习恒川软件的成功案例。”' * 4
    row = {'kind': 'attributed_opinion', 'evaluator': '顾海', 'relationship': '客户',
           'source_url': 'https://news.invalid/a', 'quote': '我们应该学习恒川软件的成功案例。'}
    _, accepted, errors = validate_discovery(json.dumps({'feedback': [row]}), [source(text)], intake())
    assert not accepted and 'opinion_not_about_target_person' in errors


def test_naming_the_founder_in_company_praise_does_not_make_it_personal_feedback():
    quote = '客户顾海表示，林知远的公司产品表现出色，未来将继续采购公司的产品。'
    row = {'kind': 'attributed_opinion', 'evaluator': '顾海', 'relationship': '客户', 'quote': quote, 'source_url': 'https://news.invalid/a'}
    _, records, errors = validate_discovery(json.dumps({'feedback': [row]}), [source(quote * 4)], intake())
    assert not records and 'company_focused_opinion' in errors


def test_real_personal_opinion_can_preserve_unknown_relationship_without_inventing_it():
    quote = '顾海在公开采访中形容林知远是一位重视技术细节的创业者，这只是受访者观点，双方利益关系未披露。'
    row = {'kind': 'attributed_opinion', 'evaluator': '顾海', 'relationship': '',
           'source_url': 'https://news.invalid/a', 'quote': quote}
    _, records, _ = validate_discovery(json.dumps({'feedback': [row]}), [source(quote * 4)], intake())
    assert records and not records[0]['relationship']


def test_supplied_person_alias_is_kept_through_attributed_feedback_validation():
    value = intake()
    value['person_anchor']['aliases'] = ['Evan Lin']
    quote = 'Client Ada said Evan Lin honored the published contract terms; this is Ada\'s statement and not an independent credit rating.'
    row = {'kind': 'attributed_opinion', 'evaluator': 'Ada', 'relationship': 'Client', 'quote': quote, 'source_url': 'https://news.invalid/a'}
    _, records, _ = validate_discovery(json.dumps({'feedback': [row]}), [source(quote * 2)], value)
    assert records and records[0]['target_name'] == '林知远'


def test_historical_disputed_opinion_is_dated_separately_and_never_analyzed_as_personal_guilt():
    quote = '顾海在采访中称林知远偷走了技术文件，该陈述尚未得到独立核实。'
    text = '发布时间：2010-09-06\n\n' + quote + ('其他背景资料。' * 30)
    src = source(text)
    raw = {'kind': 'attributed_opinion', 'evaluator': '顾海', 'relationship': '', 'quote': quote, 'source_url': src.url}
    _, records, _ = validate_discovery(json.dumps({'feedback': [raw]}), [src], intake())
    src.source_metadata['person_feedback_records'] = records
    pack = build_packages({'facts': []}, '林知远', PERSON_REPORT_OUTLINE, intake(), [src])
    finding = pack['chapters'][7]['facts'][0]
    assert finding['feedback_record']['source_published_at'] == '2010-09-06'
    assert not finding['analysis_allowed'] and not finding['eligible_for_risk_scoring']
    assert not pack['chapters'][12]['facts']
    text = render_section(pack['chapters'][7])
    assert '历史争议中的具名单方陈述' in text and '不代替事件时间' in text


def test_other_person_profiles_have_a_validated_nomination_chain_and_only_enter_chapter8():
    src, candidate, feedback = discovery()
    peers, records, _ = validate_discovery(json.dumps({'peers': [candidate], 'feedback': [feedback]}), [src], intake())
    peer = peers[0]
    profile_quote = '远山软件董事长陈雨安负责企业软件业务，原始简介没有说明本次研究的比较时期与个人绩效指标。'
    profile = source(profile_quote * 3, url='https://official.invalid/peer', identity_confidence='low',
                     identity_status='quarantined', person_peer_context=peer,
                     person_peer_records=[{'quote': profile_quote, 'nomination': peer}])
    src.source_metadata['person_feedback_records'] = records
    pack = build_packages({'facts': []}, '林知远', PERSON_REPORT_OUTLINE, intake(), [src, profile])
    peer_facts = [f for f in pack['facts'] if f.get('comparison_subject')]
    assert len(peer_facts) == 2 and all(f['subject_scope'] == 'comparison_person' for f in peer_facts)
    assert all(not f['eligible_for_risk_scoring'] for f in peer_facts)
    for chapter in (1, 2, 3, 6, 7, 9, 10, 12, 13):
        assert not any(f.get('comparison_subject') for f in pack['chapters'][chapter]['facts'])
    assert pack['chapters'][7]['facts'][0]['feedback_record']['evaluator'] == '顾海'
    assert '未完成授权访谈' in render_section(pack['chapters'][7])
    text = render_section(pack['chapters'][8])
    assert '陈雨安' in text and '候选可比性及指标口径待核对，不排名' in text
    assert any('两位' in gap for gap in pack['chapters'][8]['information_gaps'])


def test_context_change_invalidates_peer_chain_and_modified_quotes():
    src, candidate, _ = discovery()
    peers, _, _ = validate_discovery(json.dumps({'peers': [candidate]}), [src], intake())
    peer = peers[0]
    src.source_metadata['person_peer_records'] = [{'quote': candidate['quote'], 'nomination': peer}]
    assert annotated_facts([src], intake())
    changed = {**intake(), 'target_name': '另一人', 'person_anchor': {'known_affiliations': ['别的机构']}}
    assert not annotated_facts([src], changed)
    src.content = '原文已经被更换，原先的摘录及提名依据都不存在。' * 10
    assert not annotated_facts([src], intake())


def test_followup_never_spends_after_total_search_budget_or_when_disabled(monkeypatch):
    monkeypatch.setenv('PERSON_SEARCH_CALL_BUDGET', '5')
    project = SimpleNamespace(target_type='person', person_retrieval_audit={'calls_planned': 5})
    workflow = Mock()
    assert collect(workflow, None, project, intake()) == 0
    workflow._invoke_person_report_section.assert_not_called()


def test_discovery_packets_prioritize_new_relevant_originals_over_old_filings():
    original, _, _ = discovery()
    original.source_metadata['module'] = '可比人物资料'
    boilerplate = [source(('林知远承诺遵守规定。' * 100), url=f'https://filing.invalid/{i}') for i in range(10)]
    prompt = discovery_prompt(boilerplate + [original], intake())
    assert prompt.index('https://news.invalid/a') < prompt.index('https://filing.invalid/0')


def test_legal_name_core_is_only_a_provisional_identity_clue():
    from research_workflow import ResearchWorkflow
    wf = ResearchWorkflow.__new__(ResearchWorkflow)
    value = {**intake(), 'person_anchor': {'known_affiliations': ['恒川软件股份有限公司']}}
    result = contextual_identity(wf, '采访', '恒川软件的林知远接受采访，相关身份和时期仍需核实。', value)
    assert result['confidence'] == 'medium' and '仍需复核' in result['reason']
    assert contextual_identity(wf, '另一人', '远山软件的林知远接受采访。', value)['confidence'] not in {'high', 'medium'}


def test_collector_fetches_peer_identity_separately_and_preserves_primary_quarantine(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, ResearchProject, User
    import web_search
    import research_store as store_module
    from research_workflow import ResearchWorkflow
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    monkeypatch.setenv('TAVILY_API_KEY', 'synthetic-key')
    monkeypatch.setattr(store_module.research_store, 'mode', 'local')
    monkeypatch.setattr(store_module.research_store, 'local_root', tmp_path)
    wf = ResearchWorkflow.__new__(ResearchWorkflow)
    src, first, feedback = discovery()
    second = dict(first, name='许清和', company='明川软件', role='创始人',
                  quote='明川软件创始人许清和负责软件产品。',
                  basis_quote='恒川软件与明川软件同属软件行业，报道将林知远与许清和作为同业人物比较。')
    original = src.content + second['quote'] + second['basis_quote']
    queries, fetches = [], []
    def search(provider, query, **kw):
        queries.append(query)
        person = next((r['name'] for r in (first, second) if r['name'] in query), '')
        return [{'url': 'https://official.invalid/' + person if person else src.url, 'title': '公开原件'}]
    def fetch(url, **kw):
        fetches.append(url)
        name = url.rsplit('/', 1)[-1]
        candidate = next((r for r in (first, second) if r['name'] == name), None)
        text = (candidate['quote'] * 8) if candidate else original
        return {'status': 'done', 'content': text}
    monkeypatch.setattr(web_search.web_search_provider, 'search_single', search)
    monkeypatch.setattr(wf, '_fetch_web_url_with_timeout', fetch)
    monkeypatch.setattr(wf, '_is_low_quality_open_web_source', lambda *a, **kw: (False, ''))
    monkeypatch.setattr(wf, '_invoke_person_report_section', lambda *a: json.dumps({'peers': [first, second], 'feedback': [feedback]}))
    with Session(engine) as db:
        user = User(username='chapter-peer-test', password_hash='test')
        db.add(user); db.flush()
        project = ResearchProject(title='合成人物', target_name='林知远', target_type='person', industry='', description='', created_by_id=user.id)
        db.add(project); db.commit()
        project.person_retrieval_audit = {'calls_planned': 30, 'page_fetch_attempts': 33}
        assert collect(wf, db, project, intake()) == 3
        assert len(queries) == 9 and len(fetches) == 3
        assert project.person_retrieval_audit['calls_planned'] == 39
        assert project.person_retrieval_audit['page_fetch_attempts'] == 36
        peers = [s for s in project.sources if s.source_metadata.get('person_peer_context')]
        assert len(peers) == 2 and all(s.source_metadata['identity_confidence']=='low' for s in peers)
        contract = build_packages({'facts': []}, '林知远', PERSON_REPORT_OUTLINE, intake(), project.sources)
        assert {f['comparison_subject'] for f in contract['chapters'][8]['facts'] if f.get('comparison_subject')} == {'陈雨安', '许清和'}
        assert all(f['subject']=='林知远' for f in contract['chapters'][7]['facts'])
        stored = next(s for s in project.sources if s.url==src.url).source_metadata['person_peer_records']
        assert {r['nomination']['name'] for r in stored} == {'陈雨安', '许清和'}
