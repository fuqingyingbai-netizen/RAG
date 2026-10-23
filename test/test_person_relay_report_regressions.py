from types import SimpleNamespace

from person_source_boundaries import source_context_errors
from person_source_context import literal_document_context
from person_records import observation


def test_retirement_year_does_not_date_a_parenthetical_holding_ratio():
    rows = [{'fact': '林知远于2022年3月卸任。目前持有33.64亿股，持股37.35%。',
             'subject': '林知远'}]
    assert 'holding_period_not_in_metric_context' in source_context_errors('持股37.35%（2022年后）。', rows)
    assert 'holding_period_not_in_metric_context' in source_context_errors('持股37.35%（近期）。', rows)
    assert not source_context_errors('来源称持股37.35%，基准日未注明。', rows)
    assert not source_context_errors('持股37.35%（近期）。', [{'fact': '林知远近期持股37.35%。'}])


def test_position_titles_do_not_establish_formal_control_authority():
    rows = [{'fact': '林知远获聘为董事长、总裁，并兼任战略委员会主席。'}]
    assert 'formal_authority_inferred_from_role' in source_context_errors('上述职务表明其具有直接主导权。', rows)
    assert not source_context_errors('任职本身不能证明其具有直接主导权。', rows)
    assert not source_context_errors('公告明确授予其最终决策权。', [{'fact': '本事项授予林知远最终决策权。'}])


def test_individual_and_couple_stakes_in_one_paragraph_are_separate():
    row = {'fact': '林知远个人拥有公司44.01%的权益。林知远夫妇通过甲公司直接持股34.61%。陈雨安夫妇持股16.40%。',
           'subject_scope': 'person', 'subject': '林知远'}
    row['observation'] = observation(row, '林知远')
    assert [m['subject'] for m in row['observation']['metrics']] == ['林知远', '林知远夫妇', '陈雨安夫妇']
    assert not source_context_errors('来源载明林知远个人拥有44.01%的权益。', [row])
    assert 'joint_holding_as_individual' in source_context_errors('林知远个人持股34.61%。', [row])
    assert not source_context_errors('林知远夫妇持股34.61%。', [row])


def test_cover_issuer_does_not_come_from_an_affiliate_mention():
    source = SimpleNamespace(title='目录', url='https://example.invalid/annual.pdf', content='林知远为海底捞创办人之一。',
        source_metadata={'document_pages': [{'page': 1, 'ocr_text': '颐海國際控股有限公司\n2017年度報告\n海底捞\n火锅底料'}]})
    context = literal_document_context(source, source.content)
    assert context['source_document_issuer'] == '颐海國際控股有限公司'
    assert context['source_document_kind'] == 'annual_report'
    source.source_metadata['document_pages'] = [{'page': 1, 'text': '关于公司业务及关联方恒川软件有限公司的介绍'}]
    assert literal_document_context(source, source.content)['source_document_issuer'] == ''


def test_outside_directorship_names_the_document_company():
    row = {'fact': '林知远为海底捞创办人之一，2016年3月7日获委任为本公司非执行董事。',
           'source_document_issuer': '颐海國際控股有限公司'}
    assert 'document_issuer_missing_for_relative_role' in source_context_errors('2016年3月7日获委任非执行董事。', [row])
    assert not source_context_errors('颐海年报载其2016年3月7日获委任该公司非执行董事。', [row])


def test_bilingual_date_is_retained_when_chinese_columns_are_interleaved():
    row = {'fact': '张先生分别于2011年\nprogram completed\n10月及2012年8月完成课程。in October2011and August 2012,respectively.'}
    assert not source_context_errors('2011年10月及2012年8月完成课程。', [row])
    assert 'unsupported_date_combination' in source_context_errors('2011年8月完成课程。', [row])
    row = {'fact': '获委任为董事，on7 March2016。'}
    assert not source_context_errors('2016年3月7日获委任董事。', [row])


def test_book_publication_does_not_date_the_later_intention():
    row = {'fact': '2011年出版的书记录分级授权。林知远另希望给店长松绑，未说明该意向的时点。'}
    assert 'publication_year_as_event_date' in source_context_errors('2011年后给店长松绑属意向。', [row])
    assert not source_context_errors('书中记载给店长松绑的意向，实施时间未明。', [row])
    explicit = {'fact':'书是在2011年出版的，在那之后，林知远心心念念的一件事，就是进一步给店长松绑。'}
    assert not source_context_errors('2011年后给店长松绑属意向。', [explicit])
    assert 'publication_year_as_event_date' in source_context_errors('2011年后已实施给店长松绑。', [explicit])


def test_short_chinese_year_is_displayed_literally_without_century_inference():
    from person_records import source_events
    row = source_events('八八年七月，技校毕业后，进入拖拉机厂。')[0]
    assert row['kind'] == 'education'
    assert row['date_literal'] == '八八年七月'
    assert '1988' not in row['date_literal']


def test_parallel_company_clause_retains_named_supervisor():
    from person_colleague_material import explicit_colleague_roles
    text = '林知远主持会议。恒川软件，陈雨安和李清担任公司执行董事，周宁担任监事。各人任期仍须核对，未表明当前状态。'
    source = SimpleNamespace(url='https://example.invalid/a', title='原始报道', content=text,
        source_metadata={'identity_confidence': 'high', 'fetch_status': 'done'})
    intake = {'target_name': '林知远', 'person_anchor': {'known_affiliations': ['恒川软件']}}
    rows = explicit_colleague_roles([source], intake)
    assert {r['team_member_name'] for r in rows} == {'陈雨安', '李清', '周宁'}
    assert all(r['fact'] == text for r in rows)
    source.content = '林知远主持恒川软件会议。远山科技的周宁担任监事，与本公司不存在任职关系。'
    assert not explicit_colleague_roles([source], intake)


def test_timeline_coverage_prioritizes_dated_roles_over_value_statements():
    from person_chapter_selection import dimension_coverage
    rows = [{'evidence_id': 'E-PVALUE', 'fact': '林知远自创办企业起一直信奉创新价值观。'},
            {'evidence_id': 'E-PROLE', 'fact': '林知远于1995年创办企业并担任总经理。',
             'observation': {'source_events': [{'kind': 'founding', 'date_literal': '1995年'}]}}]
    coverage = next(r for r in dimension_coverage(2, rows) if r['view'] == '职业时间线与职责')
    assert coverage['evidence_ids'] == ['E-PROLE', 'E-PVALUE']


def test_repeated_research_limitations_keep_all_dimensions_and_distinct_states():
    from person_evidence import compact_dimension_gaps
    rows = ['研究维度“执行”已有材料但未完成核验：职责和时期待核。',
            '研究维度“创新”已有材料但未完成核验：职责和时期待核。',
            '研究维度“资本”：缺少原件。', '某次查询失败。']
    assert compact_dimension_gaps(rows) == ['研究维度“执行”、“创新”已有材料但未完成核验：职责和时期待核。',
            '研究维度“资本”：缺少原件。', '某次查询失败。']


def test_annual_report_year_comes_from_explicit_cover_not_appointment():
    source = SimpleNamespace(title='目录', url='https://example.invalid/annual.pdf',
        content='--- PDF page 2 ---\n2017  Annual Report\n张先生于2016年3月7日获委任董事。', source_metadata={})
    context = literal_document_context(source, '张先生于2016年3月7日获委任董事。')
    assert context['source_reporting_period_literal'] == '2017  Annual Report'
    row = {'fact':'张先生于2016年3月7日获委任董事。', **context}
    assert 'annual_report_year_not_supported' in source_context_errors('2016年年报载其获委任董事。', [row])
    assert not source_context_errors('2017年年报载其2016年3月7日获委任董事。', [row])


def test_related_link_questions_and_dotted_date_feeds_are_not_original_articles():
    from person_chapter_selection import useful_for_chapter
    assert not useful_for_chapter({'fact':'林知远出任董事长 2026-10-09 林知远的投资要用几个品牌来打造？'}, 2)
    assert not useful_for_chapter({'fact':'2016.06.13 访谈标题 2016.06.07 管理标题 2016.05.16 董事长演讲 查看更多>>'}, 2)
    assert useful_for_chapter({'fact':'2026-10-09，公司公告称林知远获聘董事长，任期三年。'}, 2)


def test_repair_can_choose_a_fuller_admitted_card_from_the_same_original():
    import json
    from person_evidence import build_packages, validate_model_claims
    from person_claim_repair import repair_once
    from report_agents.person_report_agent import PERSON_REPORT_OUTLINE
    rows = [{'fact':'林知远1988年技校毕业。', 'source_url':'https://example.invalid/a','identity_match':'confirmed'},
            {'fact':'林知远先前创业失败，为偿还3000元债务，后于1994年创办火锅店。', 'source_url':'https://example.invalid/a','identity_match':'confirmed'},
            {'fact':'林知远担任乙公司董事。', 'source_url':'https://example.invalid/b','identity_match':'confirmed'}]
    package = build_packages({'facts':rows},'林知远',PERSON_REPORT_OUTLINE)['chapters'][2]
    package['writing_contract'] = 'evidence_selection_v2'
    short = next(f for f in package['research_facts'] if '技校' in f['fact'])
    full = next(f for f in package['research_facts'] if '3000' in f['fact'])
    old = json.dumps({'claims':[{'evidence_ids':[short['evidence_id']],'analysis':'来源载其创业失败和3000元债务。'}]},ensure_ascii=False)
    claims, reasons = validate_model_claims(old,package)
    assert reasons
    def invoke(role,prompt,emit):
        material = json.loads(prompt[prompt.index('{"material":'):])['material']['facts']
        assert {f['evidence_id'] for f in material} == {short['evidence_id'],full['evidence_id']}
        return json.dumps({'claims':[{'evidence_ids':[full['evidence_id']],'analysis':'来源记载其创业失败和3000元债务，后于1994年创办火锅店。'}]},ensure_ascii=False)
    final, reasons, _ = repair_once(old,package,{'facts':package['research_facts']},claims,reasons,invoke,None,validate_model_claims)
    assert not reasons and final[0]['analysis']
    assert final[0]['evidence_ids'] == [full['evidence_id']]


def test_proven_document_year_can_label_report_but_not_date_an_event():
    import json
    from person_evidence import build_packages, validate_model_claims
    from report_agents.person_report_agent import PERSON_REPORT_OUTLINE
    row = {'fact':'林知远于2016年3月7日获委任董事。','source_url':'https://example.invalid/a','identity_match':'confirmed',
           'source_reporting_period_literal':'2017 Annual Report'}
    package = build_packages({'facts':[row]},'林知远',PERSON_REPORT_OUTLINE)['chapters'][2]
    package['writing_contract'] = 'evidence_selection_v2'
    eid = package['research_facts'][0]['evidence_id']
    def check(analysis):
        return validate_model_claims(json.dumps({'claims':[{'evidence_ids':[eid],'analysis':analysis}]},ensure_ascii=False),package)
    assert not check('2017年年报载其于2016年3月7日获委任董事。')[1]
    assert check('2017年年报载其于2017年获委任董事。')[1]


def test_listing_keyword_alone_is_not_exit_evidence():
    from person_chapter_selection import material_matches
    assert not material_matches({'fact':'林知远为公司股东，公司2018年上市。'},11,'退出路径及适用条件')
    assert material_matches({'fact':'林知远承诺股份上市后锁定三年，不转让所持股份。'},11,'退出路径及适用条件')


def test_reprinted_contained_quotes_display_once_without_dropping_research():
    from person_material_review import presentation_facts
    text = '林知远在公开采访中介绍公司授权制度，说明各岗位签字权限及适用条件，相关记录仅代表当时来源陈述。'*3
    a = {'evidence_id':'E-PA','source_url':'https://example.invalid/a','fact':text}
    b = {'evidence_id':'E-PB','source_url':'https://example.invalid/b','fact':text[8:]}
    c = {'evidence_id':'E-PC','source_url':'https://example.invalid/c','fact':text}
    package = {'facts':[a,b,c],'research_facts':[a,b,c]}
    chosen = presentation_facts(package,[{'analysis':'来源记载授权事项。','evidence_ids':['E-PA','E-PB','E-PC']}])
    assert [f['evidence_id'] for f in chosen] == ['E-PA']
    assert len(package['research_facts']) == 3
    short = {'evidence_id':'E-PSHORT','source_url':a['source_url'],'fact':'”'+text.split('。')[0]+'。'}
    package = {'facts':[a,short],'research_facts':[a,short]}
    chosen = presentation_facts(package,[{'analysis':'来源记载授权事项。','evidence_ids':['E-PA','E-PSHORT']}])
    assert [f['evidence_id'] for f in chosen] == ['E-PA']
    assert a['fact'] == text and short['fact'].startswith('”')


def test_biographical_debt_is_labelled_as_a_lead_not_a_judicial_record():
    from person_commission import requirements, assess
    requirement = next(r for r in requirements({'target_name':'林知远','focus_questions':['核查债务及司法事项']}) if r['topic']=='legal')
    row = {'evidence_id':'E-PA','fact':'林知远曾创业失败，后来为了偿还3000元债务经营小店。','subject_scope':'person'}
    result = assess([row],requirement)
    assert any('不构成已发现司法事项' in gap for gap in result['gaps'])


def test_chairman_election_reaches_management_chapter_and_retains_term():
    from person_evidence import build_packages
    from report_agents.person_report_agent import PERSON_REPORT_OUTLINE
    row = {'fact':'经审议，董事会同意选举林知远先生为公司第九届董事会董事长，任期三年。',
           'source_url':'https://example.invalid/board','identity_match':'confirmed'}
    contract = build_packages({'facts':[row]},'林知远',PERSON_REPORT_OUTLINE)
    assert any(f['fact']==row['fact'] for f in contract['chapters'][5]['research_facts'])


def test_role_term_in_another_part_of_same_announcement_is_not_denied():
    short = {'fact':'同意聘任林知远为公司总裁，任期三年，同时担任董事长。',
             'source_url':'https://example.invalid/board','subject':'林知远','subject_scope':'person'}
    full = {'fact':'经审议，同意选举林知远先生为第九届董事会董事长，任期三年。',
            'source_url':short['source_url'],'subject':'林知远','subject_scope':'person'}
    assert 'available_same_document_role_tenure_denied' in source_context_errors('总裁任期三年，董事长任期未载明。',[short],[short,full])
    assert not source_context_errors('本段摘录董事长任期未载明，须结合其他议案。',[short],[short,full])
    assert not source_context_errors('董事长任期未载明。',[short],[{**full,'source_url':'https://example.invalid/other'}])


def test_listed_abs_mandate_is_not_reported_as_missing_scope():
    row = {'fact':'批准后授权林知远全权处理本次资产支持证券发行上市的全部事宜，包括规模、期限及发行时机。'}
    assert 'available_authorization_scope_denied' in source_context_errors('原文未载明授权边界。',[row])
    assert not source_context_errors('已列ABS发行事项，后续批准及实施情况未披露。',[row])


def test_company_holding_outside_parentheses_is_separate_from_couple_interest():
    row = {'fact':'林知远个人拥有公司44.01%的权益。林知远夫妇通过甲公司直接持股34.61%。陈雨安夫妇持股16.40%。NP United Holding Ltd.（林知远夫妇持有该公司67.85%权益）持股34.00%。',
           'subject':'林知远','subject_scope':'person'}
    row['observation'] = observation(row,'林知远')
    assert [m['subject'] for m in row['observation']['metrics']] == ['林知远','林知远夫妇','陈雨安夫妇','林知远夫妇','NP United Holding Ltd.']
    assert 'holding_metric_subject_misattributed' in source_context_errors('林知远个人持股34.00%。',[row])
    assert 'holding_metric_subject_misattributed' in source_context_errors('林知远持股16.40%。',[row])
    assert not source_context_errors('林知远个人拥有44.01%权益，NP United Holding Ltd.持股34.00%。',[row])


def test_appended_ocr_uses_its_own_physical_page_not_last_native_page():
    quote = '林知远先生获委任为本公司非执行董事，参与公司重要决策。'
    source = SimpleNamespace(title='目录',url='https://example.invalid/a.pdf',
        content='--- PDF page 245 ---\n财务报表附注。\n--- PDF page 37 local OCR transcription pending visual review ---\n'+quote,
        source_metadata={'document_pages':[{'page':37,'ocr_text':quote},{'page':245,'text':'财务报表附注。'}]})
    assert literal_document_context(source,quote)['source_physical_pages'] == [37]
    source.source_metadata = {}
    assert literal_document_context(source,quote)['source_physical_pages'] == [37]


def test_cofounder_coordination_does_not_duplicate_the_target():
    row = {'fact':'1994年3月，林知远夫妇和陈雨安何明月夫妇四人共同创办公司。',
           'subject':'林知远','subject_scope':'person'}
    assert 'target_coordination_self_repeated' in source_context_errors('其1994年3月与林知远夫妇、陈雨安何明月夫妇创办公司。',[row])
    assert 'target_coordination_self_repeated' in source_context_errors('林知远与林知远夫妇创办公司。',[row])
    assert not source_context_errors('1994年3月，林知远夫妇与陈雨安何明月夫妇四人创办公司。',[row])
    assert not source_context_errors('其与陈雨安夫妇共同创办公司。',[row])
    assert not source_context_errors('其配偶与林知远共同创办公司。',[row])
    assert not source_context_errors('陈雨安说其与林知远共同创办公司。',[row])


def test_mixed_ownership_paragraph_is_not_labelled_wholly_as_a_couple_stake():
    from person_evidence import build_packages, render_section
    from report_agents.person_report_agent import PERSON_REPORT_OUTLINE
    row = {'fact':'林知远个人拥有公司44.01%的权益。林知远夫妇直接持股34.61%。陈雨安夫妇持股16.40%。',
           'source_url':'https://example.invalid/stakes','identity_match':'confirmed'}
    package = build_packages({'facts':[row]},'林知远',PERSON_REPORT_OUTLINE)['chapters'][9]
    text = render_section(package)
    assert '权益归属：本段涉及多个持有主体' in text
    assert '权益披露主体：林知远夫妇' not in text
    assert row['fact'] in text


def test_existing_commission_questions_are_sent_and_not_denied(monkeypatch):
    import json
    from person_evidence import build_packages, validate_model_claims, generate_person_report
    from report_agents.person_report_agent import PERSON_REPORT_OUTLINE
    row = {'fact':'林知远曾任远山科技有限公司董事，负责公司战略。',
           'source_url':'https://example.invalid/career','identity_match':'confirmed'}
    intake = {'target_name':'林知远','special_requirements':'核查历史任职变化'}
    package = build_packages({'facts':[row]},'林知远',PERSON_REPORT_OUTLINE,intake)['chapters'][10]
    package['writing_contract'] = 'evidence_selection_v2'
    eid = package['research_facts'][0]['evidence_id']
    claims,reasons = validate_model_claims(json.dumps({'claims':[{'evidence_ids':[eid],'analysis':'本章未列明具体专项问题，专项范围待确认。'}]},ensure_ascii=False),package)
    assert 'commission_scope_denied' in reasons
    assert not any(c['analysis'] for c in claims)
    project = SimpleNamespace(title='委托范围回归',target_name='林知远',person_research_intake=intake,sources=[])
    received = []
    def invoke(role,prompt,emit):
        if '人物背景调查第10章：' in prompt:
            received.append(json.loads(prompt.splitlines()[-1]))
        return '{"claims":[]}'
    generate_person_report(project,json.dumps({'facts':[row]},ensure_ascii=False),'{}',PERSON_REPORT_OUTLINE,invoke,lambda *a,**k:None)
    assert received
    assert all(any('核查历史任职变化' in q['questions'] for q in r['commission_questions']) for r in received)


def test_different_board_terms_are_not_claimed_as_one_source():
    rows = [
        {'fact':'董事会同意提请股东大会授权林知远办理ABS发行事项。','source_title':'第六届董事会会议决议', 'source_url':'https://example.invalid/six'},
        {'fact':'第九届董事会同意选举林知远为董事长。','source_url':'https://example.invalid/nine'}]
    assert 'different_board_documents_as_same_source' in source_context_errors('董事会提请授权，同一来源称其当选董事长。',rows)
    assert not source_context_errors('第六届董事会提请授权，另一公告载第九届董事会选举其为董事长。',rows)
    assert not source_context_errors('董事会提请授权，同一来源称其当选董事长。',[{**r,'source_url':'https://example.invalid/one'} for r in rows])
    assert not source_context_errors('同一来源称其当选董事长。',[rows[1],{**rows[1],'source_url':'https://example.invalid/reprint'}])


def test_traditional_biography_reaches_commission_without_rewriting_quote():
    from person_commission import requirements, matches
    from person_evidence import build_packages
    from report_agents.person_report_agent import PERSON_REPORT_OUTLINE
    quote = '林知遠先生，於2016年獲委任為本公司非執行董事，並於2011年完成長江商學院工商管理課程。'
    row = {'fact':quote,'source_url':'https://example.invalid/traditional','identity_match':'confirmed'}
    intake = {'target_name':'林知远','focus_questions':['核对教育及职业履历']}
    qs = requirements(intake)
    assert all(matches(row,q) for q in qs)
    package = build_packages({'facts':[row]},'林知远',PERSON_REPORT_OUTLINE,intake)['chapters'][10]
    assert any(f['fact']==quote for f in package['research_facts'])
    other = {**row,'fact':quote.replace('林知遠','陳雨安')}
    assert not any(matches(other,q) for q in qs)


def test_completed_course_record_is_not_denied_or_promoted_to_a_degree():
    support = {'fact':'林知远1988年技校毕业。','subject_scope':'person','subject':'林知远'}
    program = {'fact':'林知远于2011年完成长江商学院工商管理课程。','subject_scope':'person','subject':'林知远'}
    assert 'available_education_program_denied' in source_context_errors('来源载技校毕业，未载其他学历资格。',[support],[support,program])
    assert not source_context_errors('另有商学院课程完成记录，尚未提供学位证明。',[support,program],[support,program])
    assert not source_context_errors('未载其他学历资格。',[support],[support])


def test_host_exchange_does_not_prove_prospectus_share_class():
    row = {'fact':'林知远承诺自公司股票上市之日起三十六个月内不转让所持股份。',
           'source_title':'公司招股意向书','source_url':'https://www.hkexnews.hk/prospectus.pdf'}
    assert 'unsupported_share_class_document_label' in source_context_errors('H股招股文件载其作出锁定承诺。',[row])
    assert 'unsupported_share_class_document_label' in source_context_errors('A股招股说明书载其作出锁定承诺。',[row])
    assert not source_context_errors('招股文件载其作出锁定承诺。',[row])
    assert not source_context_errors('H股招股说明书载其作出锁定承诺。',[{**row,'source_title':'首次公开发行H股股票招股说明书'}])
    assert not source_context_errors('来源载其持有H股。',[row])


def test_multi_person_roster_dates_are_not_rendered_as_the_target_education():
    from person_evidence import build_packages, render_section
    from report_agents.person_report_agent import PERSON_REPORT_OUTLINE
    from person_records import mixed_biographical_context
    quote = '高级管理人员：林知远先生任本公司总裁。陈雨安女士1992年毕业，1996年加入公司。何明月先生1998年毕业，1999年加入公司。周青女士2005年毕业，2006年加入公司。'
    row = {'fact':quote,'source_url':'https://example.invalid/roster','identity_match':'confirmed'}
    package = build_packages({'facts':[row]},'林知远',PERSON_REPORT_OUTLINE)['chapters'][5]
    assert package['research_facts'] and mixed_biographical_context(package['research_facts'][0])
    text = render_section(package)
    assert '未逐人对齐，不作为目标个人教育或任期日期' in text
    assert quote in text
    assert '原文事件时间：教育事件原文日期：1992年' not in text


def test_multi_person_roster_requires_a_target_specific_date_support():
    mixed = {'fact':'林知远先生任总裁。陈雨安女士1992年毕业，1996年加入。何明月先生1998年毕业，1999年加入。周青女士2005年毕业，2006年加入。', 'subject':'林知远','subject_scope':'person'}
    assert 'mixed_roster_date_as_target' in source_context_errors('林知远1992年毕业。',[mixed])
    assert not source_context_errors('年报列示多名高管1996年后加入公司。',[mixed])
    assert not source_context_errors('林知远1987年毕业。',[mixed,{'fact':'林知远于1987年毕业。','subject':'林知远','subject_scope':'person'}])


def test_editor_and_media_promotion_do_not_supply_dimension_evidence():
    from person_chapter_selection import dimension_coverage
    rows = [{'evidence_id':'E-PBIO','fact':'（编辑：李青 供稿：现代管理与技术创新基地） 林知远董事长简介，1988年毕业后进入工厂。','subject':'林知远'},
            {'evidence_id':'E-PMEDIA','fact':'证券时报网由人民日报社主管主办，是中国资本市场的重要信息披露媒体。提供7*24小时财经资讯，为用户提供全方位、最新鲜的财经信息。林知远谈内部管理。','subject':'林知远'},
            {'evidence_id':'E-PFUND','fact':'林知远负责融资，筹集公司研发资金。','subject':'林知远'}]
    result = {r['view']:r for r in dimension_coverage(4,rows)}
    assert 'E-PBIO' not in result['创新迭代与阶段匹配']['evidence_ids']
    assert 'E-PMEDIA' not in result['资本资源与个人职责']['evidence_ids']
    assert 'E-PFUND' in result['资本资源与个人职责']['evidence_ids']
    assert len(rows)==3 and '技术创新' in rows[0]['fact']
