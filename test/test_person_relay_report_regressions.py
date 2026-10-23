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
