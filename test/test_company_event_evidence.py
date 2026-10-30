import hashlib
from copy import deepcopy
from types import SimpleNamespace

import pytest

from report_agents.company_event_evidence import (
    VERSION, REVIEW_CRITERIA, reviewed_event_records, review_primary_events, validate_event,primary_event_candidate,
    independent_check_witness,
)
from report_agents.company_risk_register import build_risk_register, render_risk_register, risk_register_errors
from report_agents.company_governance import governance_graph_nodes, render_registered_shareholders
from report_agents.company_corpus_writer import render_compact_chapters
from report_agents.company_report_agent import COMPANY_REPORT_OUTLINE
from report_agents.company_assessment import non_scoring_investment_context
from collections import defaultdict


TARGET = '青禾科技有限公司'


def source():
    return {'title': TARGET + '第三方仿冒案件', 'url': 'https://www.samr.gov.cn/example.html',
        'content': '发布日期：2025-02-01\n针对青禾科技有限公司的第三方仿冒案件，监管机关责令仿冒者停止违法行为。',
        'source_metadata': {'fetch_status': 'done'}}


def selection(s):
    raw = s['content']
    row = {'target_name': TARGET, 'kind': 'external_impersonation', 'source_url': s['url'], 'source_title': s['title'],
        'quote': raw.split('\n')[1], 'subject_quote': TARGET, 'date_quote': '发布日期：2025-02-01',
        'publication_date': '2025-02-01', 'summary': '主管机关通报第三方仿冒案，处置对象是仿冒者。',
        'source_date': '2025-02-01', 'source_date_role': 'publication',
        'subject_scope': '外部仿冒者；目标公司不是受处罚人',
        'original_sha256': hashlib.sha256(raw.encode()).hexdigest(),
        'independent_check': {'status': 'supported', 'criteria': dict.fromkeys(REVIEW_CRITERIA, True)}}
    for key in ('quote', 'subject_quote', 'date_quote'): row[key + '_offset'] = raw.find(row[key])
    row['independent_check_witness']=independent_check_witness(row,row['independent_check'],TARGET,'2026-10-20')
    return row


@pytest.mark.parametrize('mutation,error', [
    ({'quote': '目标公司被罚款'}, 'nonliteral_quote'),
    ({'quote_offset': -1}, 'nonliteral_quote'),
    ({'publication_date': '2024-02-01'}, 'unproven_publication_date'),
    ({'original_sha256': 'stale'}, 'original_changed'),
    ({'target_name': '同名其他公司'}, 'target_mismatch'),
    ({'kind': 'convicted_fraud'}, 'unsupported_event_kind'),
    ({'independent_check': {'status': 'unsupported'}}, 'independent_check_missing'),
    ({'summary': '监管机关处罚公司900万元。'}, 'new_summary_number'),
])
def test_review_cannot_bypass_native_or_scope_guards(mutation, error):
    s = source(); row = selection(s); row.update(mutation)
    assert error in validate_event(row, s, TARGET, '2026-10-20')


def test_after_cutoff_and_search_abstract_never_become_historical_event():
    s = source(); row = selection(s)
    assert 'after_research_cutoff' in validate_event(row, s, TARGET, '2024-12-31')
    s['source_metadata']['content_kind'] = 'search_summary'
    assert 'not_usable_primary_event_source' in validate_event(row, s, TARGET, '2026-10-20')


def test_third_party_mirror_is_not_a_primary_regulatory_source():
    s = source(); s['url'] = 'https://news.example.com/notice'
    assert 'not_usable_primary_event_source' in validate_event(selection(s), s, TARGET, '2026-10-20')


def test_changed_original_invalidates_cached_selection():
    s = source(); p = {'version': VERSION, 'target_name': TARGET, 'as_of_date': '2026-10-20', 'events': [selection(s)]}
    assert len(reviewed_event_records(p, [s], TARGET, '2026-10-20')) == 1
    s['content'] += '\n已发布后续变更'
    assert reviewed_event_records(p, [s], TARGET, '2026-10-20') == []


def test_no_event_retains_receipt_without_manufacturing_a_risk():
    import json
    s = source(); s['title'] = TARGET + '安全教育知识'
    p = review_primary_events([s], TARGET, '2026-10-20', lambda *a: json.dumps({'event': None}))
    assert not p['events'] and p['receipts'][0]['state'] == 'no_specific_event'


def test_named_primary_action_cannot_be_dismissed_by_a_null_model_answer():
    import json
    p = review_primary_events([source()], TARGET, '2026-10-20', lambda *a: json.dumps({'event': None}))
    assert not p['events'] and p['receipts'][0]['state'] == 'requires_review'
    assert p['receipts'][0]['error'] == 'named_primary_action_returned_no_event'


@pytest.mark.parametrize('title',[
    '关于青禾科技首次公开发行股票并上市发行注册环节反馈意见落实函的回复',
    '发行人及保荐机构关于上市申请审核问询函的回复.pdf',
    '发行人关于问询函的答复',
])
def test_government_hosted_issuer_reply_is_retained_without_becoming_an_agency_original(title):
    s=source();s['title']=title;s['url']='https://www.csrc.gov.cn/disclosure/reply.pdf'
    s['content']=TARGET+'及保荐机构回复：子公司曾收到整改通知，现已提交整改报告。责令事项、报告提交与整改验收不能混同。'
    original=deepcopy(s)
    assert not primary_event_candidate(s)
    calls=[]
    package=review_primary_events([s],TARGET,'2026-10-20',lambda *args:calls.append(args))
    assert not calls and not package['events'] and s==original
    from report_agents.company_corpus import prepare_corpus
    project=SimpleNamespace(target_type='company',target_name=TARGET,sources=[SimpleNamespace(**{**s,'id':1,'source_type':'web','summary':''})])
    documents,states,duplicates=prepare_corpus(project,{})
    assert documents and any('子公司曾收到整改通知' in w['quote'] for d in documents for w in d['windows'])
    assert all(d['source_kind'] in {'issuer_disclosure','attributed_issuer_reply'} for d in documents)


def test_regulators_action_on_an_issuer_reply_is_still_a_primary_event_candidate():
    s=source();s['title']='关于对青禾科技发行注册环节反馈意见回复出具警示函的决定'
    assert primary_event_candidate(s)


def test_another_issuers_reply_cannot_become_the_targets_disclosure_from_a_body_mention():
    from report_agents.company_source_review import provenance
    s=source();s['title']='关于远帆设备有限公司首次公开发行股票上市审核问询函的回复'
    s['content']=TARGET+'\n发行人及保荐机构已逐项核查，现回复如下。目标公司只是本回复所列供应商。'
    kind,binding=provenance(s,TARGET,{})
    assert kind=='attributed_issuer_reply' and binding['issuer_response_not_agency_original'] is True


def test_the_issuers_native_reply_statement_binds_authorship_without_turning_into_agency_approval():
    from report_agents.company_source_review import provenance
    s=source();s['title']='关于'+TARGET+'首次公开发行股票上市审核问询函的回复'
    s['content']='关于'+TARGET+'首次公开发行股票申请的回复。'+TARGET+'（以下简称发行人）与保荐机构已逐项核查，现回复如下。'
    kind,binding=provenance(s,TARGET,{})
    assert kind=='issuer_disclosure' and binding['issuer_response_not_agency_original'] is True


def test_primary_event_survives_risk_package_and_compact_writer_without_default_score():
    s = source(); review = {'version': VERSION, 'target_name': TARGET, 'as_of_date': '2026-10-20', 'events': [selection(s)]}
    p = build_risk_register({'facts': []}, TARGET, [s], intake={'as_of_date': '2026-10-20'}, event_reviews=review)
    text = render_risk_register(p)
    assert len(p['entries']) == 1 and not risk_register_errors(text, p)
    assert p['overall_score'] is None and p['entries'][0]['score'] is None
    assert '不记为目标公司的违法' in text
    project = SimpleNamespace(target_name=TARGET, company_risk_register_package=p)
    group = {'chapter': 11, 'aspect': COMPANY_REPORT_OUTLINE[10][1][-1], 'summary': '按原文核对。', 'evidence_ids': []}
    text = render_compact_chapters(project, {'groups': [group]}, COMPANY_REPORT_OUTLINE, {})[11]
    assert '主管机关通报第三方仿冒案' in text and p['entries'][0]['evidence_ids'][0] in text
    assert len(p['checklist']) == 75


def test_registry_table_and_graph_preserve_conflicting_ratios_and_unknown_dates():
    rows = [{'kind': 'shareholder', 'entity': '甲方', 'ratio': ratio, 'contribution': '认缴出资额：99',
             'period': '数据基准日未载', 'evidence_ids': ['E-000000000001']} for ratio in ('60.19%', '60.1915%')]
    p = {'target_name': TARGET, 'facts': rows}
    table = render_registered_shareholders(p)
    nodes = governance_graph_nodes(p, 'equity')
    assert len(nodes) == 2 and {n[2] for n in nodes} == {'60.19%', '60.1915%'}
    assert '数据基准日未载' in nodes[0][1] and '认缴出资额：99' in table
    project = SimpleNamespace(target_name=TARGET, company_governance_package=p)
    group = {'chapter': 2, 'aspect': COMPANY_REPORT_OUTLINE[1][1][0], 'summary': '归纳。', 'evidence_ids': []}
    text = render_compact_chapters(project, {'groups': [group]}, COMPANY_REPORT_OUTLINE, {})[2]
    assert table in text


def test_share_class_aggregate_is_kept_as_original_row_but_not_a_person_node():
    row = {'kind': 'shareholder', 'entity': 'A股股东', 'ratio': '59.60%', 'period': '数据基准日未载',
           'evidence_ids': ['E-000000000001']}
    p = {'target_name': TARGET, 'facts': [row]}
    assert '股份类别汇总，非独立股东' in render_registered_shareholders(p)
    assert governance_graph_nodes(p, 'equity') == []


def test_equity_svg_separates_date_so_the_exact_percentage_is_not_clipped(monkeypatch):
    import research_workflow as rw
    rows = [{'kind': 'shareholder', 'entity': '甲方', 'ratio': ratio, 'period': '数据基准日未载',
             'evidence_ids': ['E-000000000001']} for ratio in ('60.19%', '60.1915%')]
    project = SimpleNamespace(id=1, target_type='company', target_name=TARGET, title=TARGET,
                              company_governance_package={'target_name': TARGET, 'facts': rows})
    blobs = []
    monkeypatch.setattr(rw.research_store, 'put_bytes', lambda key, blob, mime: blobs.append(blob.decode()))
    assert rw.ResearchWorkflow.__new__(rw.ResearchWorkflow)._build_relationship_graph_svg(project, '{}', graph_kind='equity')
    assert '60.19%' in blobs[0] and '60.1915%' in blobs[0] and '数据基准日未载' in blobs[0]


def test_investor_contribution_is_literal_non_scoring_context_only():
    text = ('证券代码：000001 公告编号：2026-001\n其他上市公司\n关于间接投资的公告\n'
            '公司经甲基金间接投资于青禾科技有限公司，已实缴500万元。\n截至本公告日，投资事项已完成交割。')
    s = {'title': '其他上市公司投资公告', 'url': 'https://disc.static.szse.cn/notice.pdf', 'content': text,
         'source_metadata': {'fetch_status': 'done', 'document_pages': [{'page': 1, 'text': text}]}}
    rows = non_scoring_investment_context([s], TARGET, defaultdict(list))
    assert len(rows) == 1 and rows[0]['fact'] in text and '不进入六项评分' in rows[0]['boundary']
    assert 'score' not in rows[0]


def test_transaction_boundary_reference_is_registered_without_becoming_a_score():
    from report_agents.company_assessment import build_assessment_package, render_assessment, assessment_errors
    p = build_assessment_package({'facts': []}, TARGET, [], intake={'as_of_date': '2026-10-20'})
    project = SimpleNamespace(target_name=TARGET, company_assessment_package=p)
    statement = {'chapter': 10, 'text': '根据财务报表并经核查，流动资金覆盖证券认购。',
        'evidence_ids': ['E-000000000001'], 'context': {'source_kind': 'third_party_filing', 'scope': 'third_party_about_target'},
        'source_url': 'https://www.sse.com.cn/check.pdf', 'source_title': '专项核查报告'}
    text = render_compact_chapters(project, {'groups': [], 'statements': [statement]}, COMPANY_REPORT_OUTLINE,
                                   {12: render_assessment(p)})[12]
    assert 'E-000000000001' in text
    assert not any('无原件定位' in e for e in assessment_errors(text, p))
    assert all(d['score'] is None for d in p['dimensions'])
    assert all(not d['records'] for d in p['dimensions'])


def test_compact_personnel_table_retains_raw_role_term_and_observation_boundary():
    from report_agents.company_governance import render_governance_personnel
    p = {'target_name': TARGET, 'facts': [{'kind': 'personnel', 'entity': '乙某', 'role': '核心技术人员',
         'term': '', 'period': '数据基准日未载', 'evidence_ids': ['E-000000000001']}]}
    text = render_governance_personnel(p)
    assert '核心技术人员' in text and '源表未载' in text and '数据基准日未载' in text
    project=SimpleNamespace(target_name=TARGET,company_governance_package=p)
    group={'chapter':2,'aspect':COMPANY_REPORT_OUTLINE[1][1][0],'summary':'原文归纳。','evidence_ids':[]}
    assert text in render_compact_chapters(project,{'groups':[group]},COMPANY_REPORT_OUTLINE,{})[2]
