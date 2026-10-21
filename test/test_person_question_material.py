"""Regressions for concrete failures found in the retained 15-chapter report."""
import json
from types import SimpleNamespace

import pytest

from person_evidence import build_packages, generate_person_report, render_section, split_sections, numbers
from person_records import observation
from person_records import source_events
from person_records import definition_errors, personal_inference_errors, current_status_errors
from person_chapter_selection import team_source_facts
from person_chapter_selection import prioritize_sentences
from person_chapter_selection import material_matches
from person_records import comparison_errors
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


def row(text, url='https://filing.invalid/a'):
    return {'fact': text, 'source_url': url, 'source_title': '留存公开原文',
            'identity_match': 'confirmed', 'identity_confidence': 'high'}


def packages(rows, name='林知远'):
    return build_packages({'facts': rows}, name, PERSON_REPORT_OUTLINE)


@pytest.mark.parametrize('name', ['林知远', '沈岚', 'Amelia Hart'])
def test_a_school_or_degree_is_material_without_the_template_heading(name):
    p = packages([row(f'{name}于２００９年毕业于远山大学，获得硕士学位，原件待进一步核对。')], name)
    chapter = p['chapters'][2]
    education = chapter['material_coverage'][0]
    assert education['state'] == 'partial' and education['evidence_ids']
    assert '已取得教育经历线索' in education['status']
    assert '须核对' in education['status']
    assert '不再记为' not in education['status']
    assert not any('家庭' in gap for gap in chapter['information_gaps'])
    assert '教育事件原文日期：２００９年' in render_section(chapter)


def test_specific_authorization_is_not_starved_by_many_lockup_statements():
    rows = [row(f'林知远作为董事及高级管理人员，承诺上市后{i+1}个月不得转让持股，每年转让受限。', f'https://filing.invalid/lockup-{i}') for i in range(20)]
    authorization = '经股东大会批准，董事会授权林知远全权办理资产支持证券发行，授权期限另见议案。'
    rows.append(row(authorization, 'https://filing.invalid/authorization'))
    p = packages(rows)
    assert any(f['fact'] == authorization for f in p['chapters'][11]['facts'])
    assert all('不得转让' not in f['fact'] for f in p['chapters'][5]['facts'])
    assert any(r['reason'] == 'not_chapter_material' for r in p['chapters'][5]['selection_audit'])


def test_external_ceo_news_and_the_targets_portfolio_are_not_a_team_profile():
    rows = [row('林知远向远辰公司CEO顾海交付产品，双方签署客户合作文件。'),
            row('林知远任职恒川软件董事长，负责产品与研发。', 'https://news.invalid/b'),
            row('团队成员姓名：陈雨安；职务：研发负责人；与林知远同属核心团队，任期另核。', 'https://filing.invalid/team')]
    chapter = packages(rows)['chapters'][6]
    assert len(chapter['facts']) == 1
    assert chapter['facts'][0]['subject_scope'] == 'other_person'
    assert '陈雨安' in chapter['facts'][0]['subject']
    assert not chapter['facts'][0]['analysis_allowed']


def test_name_field_stops_before_birthday_without_breaking_english_names():
    for name in ['林知远', 'Amelia Hart']:
        obs = observation(row(f'姓名：{name} 出生日期：1980年 国籍：中国 任职董事。'), name)
        assert obs['subject_scope'] == 'person'
        assert obs['source_named_person'] == name


def test_event_dates_are_literal_and_never_borrow_birth_or_company_registration():
    assert not source_events('林知远于1980年出生，公司于2003年成立，原文没有任期。')
    assert source_events('林知远于２００９年毕业于远山大学。')[0]['date_literal'] == '２００９年'
    obs = observation(row('林知远于2009年毕业于远山大学，持有公司20万股。'), '林知远')
    assert not obs['period'] and not obs['metrics'][0]['period']
    assert numbers('２００９年与２０万股') == numbers('2009年与20万股')


def test_embedded_historical_tenure_is_not_reported_as_missing():
    obs = observation(row('姓名 职务 任期起止日期 林知远 董事 ２００８年６月１１日至２０１１年６月１０日，1980年出生。'), '林知远')
    assert obs['role_date_fields'] == [{'field': '任期起止原文', 'source_value': '２００８年６月１１日至２０１１年６月１０日'}]
    assert not obs['period']  # Historical tenure is not a current data snapshot.


def test_equal_digits_do_not_permit_changed_units_or_completed_authorization():
    assert definition_errors('来源称其持股15.41亿股。', [row('林知远持有15.41%的股份。')]) == ['quantity_unit_not_supported']
    support = [row('董事会提请股东大会授权，并在取得批准之同时授权林知远办理发行。')]
    assert 'conditional_authorization_as_completed' in definition_errors('其被董事会授权办理发行。', support)
    assert not definition_errors('议案提请授权林知远，取得股东大会批准后方可生效。', support)
    assert personal_inference_errors('一句公开发言反映其高风险偏好。')
    assert definition_errors('来源另列多个万股数量，无法确认比例。', [row('林知远承诺锁定所持股份。')]) == ['quantity_unit_not_supported']


def test_historical_source_attribution_and_explicit_negation_are_not_current_assertions():
    supports = [row('林知远在原始文件中担任总裁。')]
    assert not current_status_errors('历史文件称其现任总裁，但未载明对应时点，不能确认当前仍任职。', supports)
    assert not current_status_errors('历史股权转让记录不构成对当前持股状态的持续性认定。', supports)
    assert current_status_errors('林知远现任总裁，负责集团经营。', supports)


def test_identical_statements_do_not_take_all_the_chapter_slots():
    p = packages([row('林知远于2009年毕业于远山大学。', f'https://copy{i}.invalid/a') for i in range(15)])
    chapter = p['chapters'][2]
    assert len(chapter['facts']) == 1
    assert sum(r['reason'] == 'same_source_statement' for r in chapter['selection_audit']) == 14
    assert len(p['facts']) == 15  # Original provenance remains in the ledger.


def test_late_source_questions_are_reserved_before_repeated_early_mentions():
    sentences = [f'林知远负责公司的日常事务，这是来源前部第{i}条相似的常规职务描述。' for i in range(30)]
    education = '林知远于2009年毕业于远山大学，获得工程硕士学位，原件仍待复核。'
    authorization = '股东大会于2021年授权林知远办理具体融资事项，期限以议案为准。'
    chosen = prioritize_sentences([*sentences, education, authorization], lambda s: '林知远' in s)[:12]
    assert education in chosen and authorization in chosen


def test_full_document_identity_accepts_late_traditional_name_with_supplied_company():
    from research_workflow import ResearchWorkflow
    intake = {'target_type': 'person', 'target_name': '沈岚',
              'person_anchor': {'aliases': ['沈岚'], 'known_affiliations': ['青禾科技有限公司']}}
    body = '前部是与目标无关的报告正文。' * 1000 + '沈嵐现任青禾科技有限公司董事，具体任期以原始文件为准。'
    identity = ResearchWorkflow.__new__(ResearchWorkflow)._person_source_identity_confidence('公开披露', body, intake)
    assert identity['confidence'] == 'high'


def test_summary_footer_is_not_repeated_and_gaps_do_not_demand_private_information():
    p = SimpleNamespace(target_name='林知远', target_type='person', title='留存材料复验', sources=[],
                        person_research_intake={}, person_platform_attempts=[])
    text = generate_person_report(p, json.dumps({'facts': [row('林知远于2009年毕业于远山大学，2021年担任恒川软件总裁。')]}), '{}',
                                  PERSON_REPORT_OUTLINE, lambda *a: '{"claims":[]}', lambda *a, **kw: None)
    assert split_sections(text)[13].count('### 综合判断与证据充分程度') == 1
    assert '家庭健康等公开信息边界”缺少' not in split_sections(text)[15]
    assert '核对学校或机构原始简介' in split_sections(text)[15]


def test_summary_and_assessment_inherit_body_material_without_new_model_writing(monkeypatch):
    monkeypatch.setenv('PERSON_REPORT_SEMANTIC_REVIEW_ENABLED', 'false')
    p = SimpleNamespace(target_name='林知远', target_type='person', title='复验', sources=[], person_research_intake={}, person_platform_attempts=[])
    calls = []
    def invoke(role, prompt, *args):
        calls.append(role)
        data = json.loads(prompt.split('\n')[-1])
        return json.dumps({'claims': [{'evidence_ids': [data['facts'][0]['evidence_id']], 'analysis': '来源记录了历史教育事件，未提供当前任期资料。'}]}, ensure_ascii=False)
    generate_person_report(p, json.dumps({'facts': [row('林知远于2009年毕业于远山大学，获得硕士学位，其他任职细节未披露。')]}), '{}', PERSON_REPORT_OUTLINE, invoke, lambda *a, **kw: None)
    assert not any('摘要' in role or '综合评估' in role for role in calls)
    for n in (1, 13):
        assert p.person_delivery_diagnostic['section_diagnostics'][n]['model_calls'] == 0
        assert p.person_delivery_diagnostic['section_diagnostics'][n]['semantic_review']['status'] == 'inherited_body_analyses_no_new_inference'


def test_retained_management_document_recovers_colleagues_without_attributing_to_target():
    body = ('恒川软件有限公司 高级管理人员简历\n林知远先生，任本公司总裁，具体履历另见公开披露。\n\n'
            '陈雨安女士，1980年出生，毕业于远山大学，现任本公司技术副总裁，负责研发管理。'
            '本条是公开披露，任期仍须核实，不据此评价管理能力或个人信用。\n\n'
            '公司董事会包括张\n清和先生，以及其他董事。本段只是跨行名录，不是完整人物简介。')
    src = SimpleNamespace(url='https://filing.invalid/team', content=body, title='管理层简历',
                          source_metadata={'identity_confidence': 'high', 'content_kind': 'pdf_text_extracted', 'fetch_status': 'done'})
    intake = {'target_name': '林知远', 'person_anchor': {'known_affiliations': ['恒川软件有限公司']}}
    recovered = team_source_facts([src], intake)
    assert [r['team_member_name'] for r in recovered] == ['陈雨安']
    assert all(r['fact'] in body for r in recovered)
    p = build_packages({'facts': []}, '林知远', PERSON_REPORT_OUTLINE, intake, [src])
    assert p['chapters'][6]['facts'][0]['subject'] == '陈雨安'
    for n in (1, 2, 3, 4, 5, 7, 9, 10, 11, 12, 13):
        assert not any(f.get('team_member_name') for f in p['chapters'][n]['facts'])
    changed = {**intake, 'person_anchor': {'known_affiliations': ['另一家公司']}}
    assert not team_source_facts([src], changed)


def test_legal_commission_uses_personal_undertakings_but_not_company_credit_codes():
    intake = {'special_requirements': '核查个人契约及承诺事项'}
    p = build_packages({'facts': [row('林知远已出具承诺函，承诺承担公司补缴税款，实际履行仍未核实。'),
                                  row('恒川软件的统一社会信用代码为合成001。')]},
                       '林知远', PERSON_REPORT_OUTLINE, intake)
    assert p['chapters'][10]['commission_coverage'][0]['matched_evidence_ids']
    assert all('统一社会信用代码' not in f['fact'] for f in p['chapters'][10]['facts'])


def test_equivalent_numerals_do_not_change_units_or_legal_obligations():
    original = {'fact': '林知远承诺股票上市之日起三十六个月内不转让股份，条件成立时全额承担补税。'}
    assert not definition_errors('承诺期限为36个月，履行情况尚未核实。', [original])
    assert 'legal_obligation_definition_not_supported' in definition_errors('林知远承担连带责任。', [original])
    assert not definition_errors('原文未载明连带责任。', [original])
    assert 'repeated_disclosure_not_repeated_event' in definition_errors('林知远多次承诺不转让。', [original, original])
    assert 'quantity_unit_not_supported' in definition_errors('其持股15.41亿股。', [{'fact': '持股15.41%。'}])


def test_material_limitation_is_not_a_comparative_finding():
    assert not comparison_errors('未说明该承诺的签署时间、生效条件或法律效力差异。', [])
    assert comparison_errors('未说明原因，但持股存在差异。', [])


def test_narrative_lawsuit_and_prospective_control_risk_are_not_personal_findings():
    story = {'fact': '林知远与周远都看到了这出戏的必然走向：对簿公堂，剧情连环诉讼。', 'subject': '林知远', 'subject_scope': 'person'}
    assert not material_matches(story, 9, '司法事项及当事人身份')
    assert not material_matches(story, 12, '已发现的直接信号')
    party = {**story, 'fact': '林知远被列为合同诉讼被告，案号为（2021）合成001号，结果待核对。'}
    assert material_matches(party, 9, '司法事项及当事人身份')
    disclosure = {**story, 'fact': '本公司招股说明书披露控股股东及实际控制人控制风险，林知远持股25%。'}
    assert not material_matches(disclosure, 12, '已发现的直接信号')
    assert material_matches(disclosure, 12, '关联主体间接信号')


def test_query_compaction_preserves_each_tool_and_separates_subjects_and_outcomes():
    from person_evidence import grouped_query_coverage
    base = {'provider': 'qcc', 'subject': '甲机构', 'status_label': '返回空结果', 'reason_label': '仅本项查询'}
    rows = [{**base, 'tool_label': '裁判文书'}, {**base, 'tool_label': '被执行记录'},
            {**base, 'tool_label': '行政处罚', 'status_label': '尚未查询'},
            {**base, 'tool_label': '裁判文书', 'subject': '乙机构'}]
    result = grouped_query_coverage(rows)
    assert len(result) == 3
    assert result[0]['tool_label'] == '裁判文书；被执行记录'
    assert result[1]['status_label'] == '尚未查询' and result[2]['subject'] == '乙机构'


def test_peer_available_dates_are_distinct_from_an_aligned_comparison_period():
    from person_chapter_research import peer_material_fields
    fields = peer_material_fields([{'comparison_record_kind': 'profile', 'fact': '沈岚任汽车制造公司董事。',
        'observation': {'source_events': [{'kind': 'appointment', 'date_literal': '2021年'},
                                          {'kind': 'education', 'date_literal': '2009年'}]}}])
    assert fields['industry_literals'] == ['汽车制造']
    assert fields['role_date_literals'] == ['2021年']
    assert 'period' not in fields


def test_postprocessing_uses_the_writer_contract_instead_of_reselecting_summaries():
    import hashlib
    from research_workflow import ResearchWorkflow
    payload = json.dumps({'facts': [row('林知远于2009年毕业于远山大学，获得硕士学位。')]})
    p = SimpleNamespace(target_name='林知远', target_type='person', sources=[], person_research_intake={})
    contract = build_packages(json.loads(payload), '林知远', PERSON_REPORT_OUTLINE)
    contract['cleaned_payload_sha256'] = hashlib.sha256(payload.encode()).hexdigest()
    contract['chapters'][1]['facts'] = []
    p.person_evidence_contract = contract
    p.person_delivery_diagnostic = {'degradations': []}
    report = '\n\n'.join(render_section(contract['chapters'][n]) for n in range(1,16))
    contract['chapters'][9]['query_coverage'] = [{'status': 'empty_result', 'tool': 'fixture'}]
    ResearchWorkflow.__new__(ResearchWorkflow)._append_report_evidence_index(p, report, payload)
    assert p.person_evidence_contract is contract
    assert not p.person_evidence_contract['chapters'][1]['facts']
    assert p.person_evidence_contract['chapters'][9]['query_coverage'][0]['status'] == 'empty_result'


def test_target_roster_row_excludes_adjacent_executives_and_legal_name_keyword():
    from person_text import person_statement_excerpt
    text = ('姓名 本公司职务 公司名称 兼职单位职务 林知远 董事长 恒川软件有限责任公司 董事 '
            '陈雨安 副董事长 远山科技有限公司 董事长 许清和 总裁 另一公司 董事')
    excerpt = person_statement_excerpt(text, ['林知远'])
    assert excerpt in text and '陈雨安' not in excerpt and '许清和' not in excerpt
    p = packages([row(text)])
    assert p['chapters'][9]['facts']
    assert not p['chapters'][3]['facts']
    retained = p['chapters'][9]['facts'][0]
    assert retained['source_statement_full'] == text
    assert retained['fact'] == excerpt


def test_chinese_date_words_remain_literal_and_birth_is_not_an_appointment():
    events = source_events('沈岚女士，一九七七年出生，于二零零五年三月毕业于远山大学，二零零六年七月加入恒川软件。')
    assert [(r['kind'],r['date_literal']) for r in events] == [('education','二零零五年三月'),('appointment','二零零六年七月')]


def test_document_report_period_and_physical_page_do_not_fill_event_time():
    from person_source_context import literal_document_context
    quote = '沈岚先生现任本公司董事，具体任期未在本段披露。'
    source = SimpleNamespace(title='原始年报', content='--- PDF page 1 ---\n2025 年年度报告\n--- PDF page 62 ---\n' + quote)
    context = literal_document_context(source, quote)
    assert context['source_physical_pages'] == [62]
    assert context['source_reporting_period_literal'] == '2025 年年度报告'
    assert not observation({'fact':quote}, '沈岚')['period']


def test_news_index_cannot_mix_namesakes_even_with_a_positive_company_nearby():
    from person_evidence import normalize_facts
    from research_workflow import ResearchWorkflow
    title = '林知远最新新闻报道与相关消息'
    body = '恒川软件创始人林知远出席活动。\n另一机构董事长林知远发表讲话。'
    src = SimpleNamespace(url='https://news.invalid/tag/name', title=title, content=body, source_metadata={})
    intake = {'target_type':'person', 'target_name':'林知远', 'person_anchor':{'known_affiliations':['恒川软件']}}
    identity = ResearchWorkflow.__new__(ResearchWorkflow)._person_source_identity_confidence(title, body, intake)
    assert identity['confidence'] == 'low'
    facts, rejected = normalize_facts({'facts':[row('另一机构董事长林知远发表讲话。',src.url) | {'source_title':title}]}, '林知远', sources=[src])
    assert not facts and rejected[0]['rejection_reason'] == 'discovery_index_not_original_article'
    assert ResearchWorkflow.__new__(ResearchWorkflow)._person_source_identity_confidence('恒川软件创始人访谈', body[:18], intake)['confidence'] == 'high'
    assert ResearchWorkflow.__new__(ResearchWorkflow)._person_source_identity_confidence('林知远回应相关消息', body[:18], intake)['confidence'] == 'high'


def test_contextual_name_does_not_take_another_quoted_actors_action():
    record = observation({'fact':'在林知远重回管理一线之后，“小林”加入公司虽然时间不长，但已开始着手推动人员调动。'}, '林知远')
    assert record['subject_scope'] == 'other_person' and record['subject'] == '小林'
    assert 'personal_intention_not_supported' in definition_errors('该增持显示其持续控制意图。', [{'fact':'林知远增持公司股份。'}])


def test_affiliation_discovery_does_not_borrow_a_cofounders_other_appointments():
    from person_identity import relation_actor_is_target
    body = ('林知远先生，担任恒川软件有限公司董事。\n'
            '陈雨安先生，与林知远共同创办恒川软件，现任本公司副董事长，并担任远山投资有限公司董事长。')
    assert relation_actor_is_target(body,body.index('担任'), '林知远')
    assert not relation_actor_is_target(body,body.rindex('担任'), '林知远')


def test_rejected_interpretation_is_removed_without_losing_sources_or_failure_audit(monkeypatch):
    monkeypatch.setenv('PERSON_REPORT_SEMANTIC_REVIEW_ENABLED','false')
    monkeypatch.setenv('PERSON_REPORT_REPAIR_REJECTED','false')
    p = SimpleNamespace(target_name='林知远',target_type='person',title='合成来源验收',sources=[],person_research_intake={})
    def invoke(role,prompt,*args):
        pack=json.loads(prompt.split('\n')[-1]);eid=pack['facts'][0]['evidence_id']
        return json.dumps({'claims':[{'evidence_ids':[eid],'analysis':'来源提供教育记录，其他履历仍须核对。'},
                                     {'evidence_ids':[eid],'analysis':'2049年已融资900亿元。'}]},ensure_ascii=False)
    report=generate_person_report(p,json.dumps({'facts':[row('林知远于2009年毕业于远山大学，获得硕士学位。')]}),'{}',PERSON_REPORT_OUTLINE,invoke,lambda *a,**kw:None)
    assert '2049年已融资900亿元' not in report
    assert '获得硕士学位' in report and '来源提供教育记录' in report
    diagnostic=p.person_delivery_diagnostic['section_diagnostics'][2]
    assert diagnostic['excluded_invalid_analysis_count'] == 1
    assert diagnostic['validation_rejections'] and not diagnostic['unresolved_validation_rejections']
    assert not p.person_delivery_diagnostic['errors']
    assert '已不采用' in split_sections(report)[15]


def test_a_biography_cross_reference_is_a_locator_not_chapter_material():
    from person_chapter_selection import useful_for_chapter
    reference = row('有关林知远及陈雨安的具体情况请参见本招股说明书“董事、监事、高级管理人员及核心技术人员简介”。')
    assert not useful_for_chapter(reference,4)
    assert not useful_for_chapter(reference,5)


def test_couple_holding_keeps_its_holder_scope_and_cannot_become_solo_ownership():
    f={'fact':'截至2025年12月31日，林知远夫妇持股68%。','subject':'林知远'}
    record=observation(f,'林知远')
    assert record['ownership_subject']=='林知远夫妇'
    assert record['metrics'][0]['subject']=='林知远夫妇'
    f['observation']=record
    assert 'joint_holding_as_individual' in definition_errors('林知远持股68%。',[f])
    assert not definition_errors('原文称林知远夫妇持股68%。',[f])


def test_speech_cannot_prove_risk_preference_or_missing_approval_prove_pending_status():
    assert personal_inference_errors('他称敢于打破垄断，体现其事业突破姿态及风险承担意愿。')
    assert current_status_errors('材料未显示股东大会已召开，故授权尚处待决状态。',[])
    assert not current_status_errors('材料未显示批准，不能据此认定现实仍未生效。',[])
    assert 'industry_norm_not_supported' in definition_errors('该承诺属常规锁定安排。',[{'fact':'股东承诺锁定三十六个月。'}])


def test_special_questions_do_not_treat_same_industry_competition_or_narrative_role_as_evidence():
    from person_commission import matches,requirements,assess
    req={r['topic']:r for r in requirements({'target_name':'林知远','special_requirements':'核对历史任职变化、经营融资及同业比较'})}
    assert not matches(row('本公司与林知远控制的企业之间不存在同业竞争。'),req['comparison'])
    assert not matches(row('反击开始后，林知远与周远顿时互换了角色。'),req['career'])
    assert not matches(row('本公司的生产经营和行政管理完全独立于林知远控制的其他企业。'),req['operations'])
    f=row('林知远1966年出生，2025年年度报告称其现任董事，任期未载明。')
    f.update(evidence_id='E-PFIXTURE',subject_scope='person')
    status=assess([f],req['career'])
    assert any('缺少事件时期' in gap for gap in status['gaps'])


def test_legal_label_and_tenure_cannot_be_added_or_transferred_between_roles():
    f={'fact':'董事会同意聘任林知远为公司总裁，任期三年。另披露林知远同时担任董事长。'}
    assert 'mixed_role_tenure_not_supported' in definition_errors('林知远同时担任董事长和总裁，任期三年。',[f])
    assert not definition_errors('林知远同时担任董事长和总裁，其中总裁任期三年。',[f])
    assert 'legal_obligation_definition_not_supported' in definition_errors('该承诺属法定锁定期外的自愿锁定。',[{'fact':'股东自愿承诺锁定股份。'}])
