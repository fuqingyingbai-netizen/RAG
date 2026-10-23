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
    row = {'fact': '2011年出版的书记录分级授权。之后，林知远很想做的事是进一步给店长松绑。'}
    assert 'publication_year_as_event_date' in source_context_errors('2011年后给店长松绑属意向。', [row])
    assert not source_context_errors('书中记载给店长松绑的意向，实施时间未明。', [row])


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
