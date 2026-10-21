from person_source_boundaries import source_context_errors


def test_month_and_day_are_preserved_when_year_is_unknown():
    source=[{'fact':'1月13日，公司公告称林知远获委任为首席执行官，即日起生效。'}]
    assert source_context_errors('公告未提供具体年月日。',source)==['available_calendar_information_denied']
    assert not source_context_errors('公告载明1月13日获委任，未披露年份及完整日期。',source)


def test_universal_dates_must_appear_in_each_source_not_just_the_union():
    sources=[{'fact':'林知远于1994年3月创办公司。','source_url':'https://a.invalid/1'},
             {'fact':'公司于1994年创立，由林知远负责经营。','source_url':'https://b.invalid/2'}]
    assert 'universal_source_claim_not_shared' in source_context_errors('两份材料均确认1994年3月创办公司。',sources)
    assert not source_context_errors('两份材料均记载1994年创办公司。',sources)


def test_fact_cards_are_not_counted_as_independent_documents():
    sources=[{'fact':'林知远于1994年3月创办公司。','source_url':'https://a.invalid/1'},
             {'fact':'林知远于1994年3月与同学创办公司。','source_url':'https://a.invalid/1'}]
    assert source_context_errors('两份材料均确认1994年3月创办公司。',sources)==['source_document_count_misstated']
    assert not source_context_errors('两个摘录均确认1994年3月创办公司。',sources)


def test_equal_ratio_with_different_companies_cannot_form_one_universal_holding():
    sources=[{'fact':'林知远持有恒川软件68%股权。'}, {'fact':'林知远在静远投资持有68%股权。'}]
    assert 'universal_source_claim_not_shared' in source_context_errors('材料均描述林知远在静远投资持有68%股权。',sources)


def test_adverbial_comparison_does_not_create_a_peer_chapter():
    from person_records import chapter_relevant
    assert not chapter_relevant({'fact':'张勇说，火锅店老板一般都比较勤奋，员工比较努力。'},8)
    assert chapter_relevant({'fact':'张勇讨论同业竞争对手及可比人物的筛选条件。'},8)


def test_date_for_an_unrelated_event_on_the_same_page_cannot_date_a_holding():
    from person_records import observation
    from person_text import person_statement_excerpt
    original=('--- PDF page 48 ---\n截至2010 年 6 月 30 日，公司从客户处收到充电器换货26080只。'
              +'产品责任及客户关系说明。'*35+'\n四、管理风险\n截至本招股说明书签署之日，林知远直接持有本公司25.08%的股份。')
    assert observation({'fact':original},'林知远')['period']==''
    excerpt=person_statement_excerpt(original,['林知远'])
    assert excerpt in original and '截至本招股说明书签署之日' in excerpt
    assert '2010' not in excerpt and '充电器' not in excerpt
    fact={'fact':original,'subject':'林知远','observation':observation({'fact':original},'林知远')}
    assert 'date_bound_to_different_source_event' in source_context_errors('截至2010年6月30日，林知远直接持有25.08%股份。',[fact])
    assert not source_context_errors('原文称截至本招股说明书签署之日，林知远直接持有25.08%股份。',[fact])


def test_explicit_typed_period_still_supports_calendar_equivalent_spelling():
    fact={'fact':'林知远；数据基准日：2020-01-01；持股比例为25.08%。','subject':'林知远',
          'observation':{'subject':'林知远','period':'2020-01-01'}}
    assert not source_context_errors('截至2020年1月1日，林知远持有25.08%股份。',[fact])


def test_approved_appointment_is_not_downgraded_to_a_pending_proposal():
    fact={'fact':'表决情况：9票同意，0票反对。董事会同意聘任林知远为总裁，任期自本次董事会审议通过之日起计算。'}
    assert 'adopted_resolution_as_unapproved_proposal' in source_context_errors('属于董事会议案而非既成事实。',[fact])
    assert not source_context_errors('董事会同意聘任林知远为总裁，自审议通过日起计算任期，后续任职状态待核。',[fact])


def test_year_and_month_cannot_be_recombined_from_different_events():
    sources=[{'fact':'2022年末，公司人员紧缺。林知远表示，10月份左右管理可以恢复到此前水平。'}]
    assert source_context_errors('林知远预计至2022年10月管理可恢复。',sources)==['unsupported_date_combination']
    assert not source_context_errors('林知远预计10月左右管理可恢复，年份未明确。',sources)
    assert not source_context_errors('来源载明2022年10月获任。',[{'fact':'2022 年 10 月获任。'}])


def test_holding_is_not_automatically_direct_holding():
    assert source_context_errors('来源称林知远直接持有公司33亿股。',[{'fact':'林知远持有公司33亿股。'}])==['ownership_mode_not_in_source']
    assert not source_context_errors('来源称林知远持有公司33亿股。',[{'fact':'林知远持有公司33亿股。'}])
    assert not source_context_errors('来源称林知远通过甲公司直接持股34.61%。',[{'fact':'林知远通过甲公司直接持股34.61%。'}])


def test_retirement_plan_is_not_a_shareholder_exit_design():
    source=[{'fact':'林知远在内部信中宣布10至15年内退休，并启动接班人选拔计划。'}]
    assert source_context_errors('体现其主导退出路径设计。',source)==['retirement_as_shareholder_exit']
    assert not source_context_errors('此为管理层退休及接班计划，不构成投资方退出路径设计。',source)


def test_company_efficiency_assessment_keeps_its_source_stance():
    source=[{'fact':'公司称同时担任两个职务有利于提高决策效率和运营效率，确保长期战略持续稳定。'}]
    assert source_context_errors('同时担任两个职务有利于提高决策效率和运营效率。',source)==['company_assessment_without_attribution']
    assert not source_context_errors('公司称同时担任两个职务有利于提高决策效率和运营效率。',source)


def test_direct_mode_is_checked_per_quantity_not_inherited_from_another_ratio():
    sources=[{'fact':'林知远直接持有公司25.08%股份。'}, {'fact':'林知远；持股比例16.9%。'}]
    assert 'ownership_mode_not_in_source' in source_context_errors('林知远直接持股比例分别为25.08%和16.9%。',sources)
    assert not source_context_errors('林知远直接持有25.08%，未说明另一记录是否直接持股16.9%。',sources)
    assert 'ownership_mode_not_in_source' in source_context_errors('林知远直接持有16.9%。',[{'fact':'林知远未直接持有16.9%。'}])


def test_retirement_exit_phrase_is_checked_before_an_unrelated_later_negation():
    source=[{'fact':'林知远宣布10至15年内退休并建立接班人制度。'}]
    assert 'retirement_as_shareholder_exit' in source_context_errors('明确其退出路径规划，但未说明实际执行。',source)
    assert not source_context_errors('仅为退休及接班计划，未说明投资方退出路径。',source)


def test_general_exoneration_is_not_inferred_from_an_omitted_case_record():
    source=[{'fact':'材料记载林知远的一次股权转让。'}]
    assert 'absence_as_general_exoneration' in source_context_errors('亦无司法负面记录。',source)
    assert not source_context_errors('原文未列司法事项，不代表无司法负面记录。',source)


def test_same_entity_role_dates_in_the_broader_pool_cannot_be_denied():
    from person_records import observation
    def record(data):
        import json
        fact={'fact':'林知远；'+json.dumps(data,ensure_ascii=False),'subject_scope':'person'}
        fact['observation']=observation(fact,'林知远')
        return fact
    sparse=record({'企业名称':'恒川软件有限公司','角色':['董事长'],'成立日期':'2002-01-01'})
    dated=record({'企业名称':'恒川软件有限公司','职位':'董事长','任职起止时间':'开始时间:2018-10-15,结束时间:2024-12-20'})
    assert 'broader_material_contains_role_dates' in source_context_errors('所有记录均未注明任职起止时间。',[sparse],[sparse,dated])
    assert not source_context_errors('所引关联企业表未注明任职起止时间。',[sparse],[sparse,dated])


def test_historical_signing_snapshot_is_preserved_without_inventing_calendar_date():
    sources=[{'fact':'截至本招股说明书签署之日，林知远直接持有本公司25.08%股份，为控股股东及实际控制人。'}]
    assert 'historical_snapshot_qualifier_missing' in source_context_errors('来源披露林知远直接持股25.08%，为实际控制人。',sources)
    assert 'available_relative_baseline_denied' in source_context_errors('来源披露截至签署日直接持有25.08%，但未说明该比例对应的基准日期。',sources)
    assert not source_context_errors('来源披露截至签署日林知远直接持股25.08%；签署日的具体日历日期仍待核对。',sources)


def test_actor_and_reaction_denial_conflicts_with_retained_context():
    original = [{'fact': '张勇宣布裁撤小区经理。员工不接受，店长推不下去，杨利娟当即下令开除员工，这些都是张勇后来才知道的。'}]
    assert source_context_errors('来源未提及其他主体介入或权责转移。', original) == ['other_actor_action_denied']
    assert source_context_errors('原文未提及员工反馈。', original) == ['source_reaction_denied']
    assert not source_context_errors('来源记载张勇宣布改革、员工抵制及杨利娟处置，不能据此认定张勇个人能力。', original)


def test_team_mention_alone_does_not_prove_other_actor_intervention():
    assert not source_context_errors('未提及其他主体介入。', [{'fact': '张勇向店长和管理层宣布方案。'}])


def test_historical_platform_roles_need_explicit_historical_qualification():
    fact = {'fact': '林知远；历史记录；{"企业名称":"远山科技","曾担任角色":["董事长"]}',
            'claim_type': 'person_platform_record'}
    assert source_context_errors('来源披露林知远担任远山科技董事长。', [fact]) == ['historical_role_without_qualification']
    assert not source_context_errors('来源披露林知远曾担任远山科技董事长，未说明任职起止。', [fact])


def test_publication_year_is_not_an_implementation_date():
    original = [{'fact': '作者记录店长有签字权。书是在2011年出版的，在那之后，他希望进一步放权。'}]
    assert source_context_errors('来源载明他在2011年前后实施分级授权。', original) == ['publication_year_as_event_date']
    assert not source_context_errors('该书于2011年出版，记录了分级签字权安排；实施时点未明确。', original)
    assert not source_context_errors('来源载明他在2011年实施分级授权。', [{'fact': '他在2011年实施分级授权，同年出版了相关书籍。'}])


def test_birth_year_cannot_bind_a_founder_identity_label():
    from person_records import source_events
    assert not source_events('公开资料显示，林知远出生于1971年，是恒川软件的创办人之一。')
    assert source_events('林知远于1994年3月与同学共同创办恒川软件。')[0]['date_literal'] == '1994年3月'


def test_management_event_preserves_date_without_assigning_others_actions():
    from person_records import source_events
    rows = source_events('那是2015年公司的年会，林知远宣布要全面裁撤小区经理。员工不接受，陈雨安当即下令开除员工。')
    assert rows == [{'kind': 'management', 'date_literal': '2015年', 'source_quote': '2015年公司的年会，林知远宣布要全面裁撤'}]


def test_other_company_cover_cannot_create_main_company_team_members():
    from types import SimpleNamespace
    from person_chapter_selection import team_source_facts
    body = ('恒川软件创始人林知远与远山集团有业务往来。董事和高级管理人员简历\n'
            '陈雨安女士，1980年出生，现任本公司技术副总裁，负责研发管理，任期以本报告所列历史时期为限，具体任职仍需原件复核。')
    source = SimpleNamespace(url='https://fixture.invalid/other-company', title='目录', content=body,
        source_metadata={'identity_confidence': 'high', 'document_pages': [{'page': 1, 'ocr_text': '远山集团股份有限公司\n年度报告\n恒川软件产品展示'}]})
    audit = []
    assert not team_source_facts([source], {'target_name': '林知远', 'person_anchor': {'known_affiliations': ['恒川软件']}}, audit=audit)
    assert audit[0]['document_issuer'] == '远山集团股份有限公司'
    assert audit[0]['reason'] == 'document_issuer_differs_from_target_affiliation'


def test_positive_comparison_of_risk_appetite_is_not_adverse_personal_signal():
    from person_chapter_selection import material_matches
    row = {'fact': '不同于职业经理人过度回避风险，公司改革得益于创始人敢放权。', 'subject_scope': 'person', 'subject': '林知远'}
    assert not material_matches(row, 12, '已发现的直接信号')


def test_thousands_grouped_share_count_remains_a_whole_number():
    import json
    from person_records import observation
    from person_evidence import normalize_facts, validate_model_claims
    original = '林知远持有570,642,580股本公司股份，占公司股本总额的25.08%。'
    row = {'fact': original, 'source_url': 'https://fixture.invalid/holding', 'identity_match': 'confirmed'}
    observation_record = observation(row, '林知远')
    assert observation_record['metrics'][0]['value'] == '570642580'
    assert observation_record['metrics'][0]['source_literal'] == '570,642,580股'
    assert observation_record['metrics'][1]['value'] == '25.08'
    cards, _ = normalize_facts({'facts': [row]}, '林知远')
    package = {'facts': cards, 'writing_contract': 'evidence_selection_v2'}
    def validate(text):
        return validate_model_claims(json.dumps({'claims': [{'evidence_ids': [cards[0]['evidence_id']], 'analysis': text}]}), package)
    accepted, errors = validate('来源记载林知远持有580股。')
    assert errors and not accepted[0]['analysis']
    accepted, errors = validate('来源记载林知远持有570,642,580股，未说明当前状态。')
    assert not errors and accepted[0]['analysis']


def test_adjacent_roster_without_spaces_does_not_assign_colleague_data_to_target():
    from person_text import person_statement_excerpt
    text = ('姓名职务任职起止日期 王传福董事长、执行董事、总裁 董事长、执行董事任期为2011年6月11日至2014年6月10日，总裁任期自2002年6月10日起24.24% '
            '吕向阳副董事长、非执行董事2008年6月11日至2011年6月10日16.34%')
    result = person_statement_excerpt(text, ['王传福'])
    assert result.startswith('王传福') and '吕向阳' not in result and '16.34%' not in result


def test_known_context_id_cannot_support_personal_analysis():
    import json
    from person_evidence import validate_model_claims
    package = {'writing_contract': 'evidence_selection_v2', 'facts': [{'evidence_id': 'E-PABCDEF12345678',
        'fact': '具名评价者称林知远对其有帮助，关系及代表性未核实。', 'subject_scope': 'person', 'analysis_allowed': False}]}
    accepted, errors = validate_model_claims(json.dumps({'claims': [{'evidence_ids': ['E-PABCDEF12345678'], 'analysis': '来源说明其乐于帮助他人。'}]}), package)
    assert errors == ['personal_analysis_not_permitted'] and not accepted[0]['analysis']


def test_joint_holding_stays_joint_when_other_supports_are_individual():
    from person_records import observation
    joint = {'fact': '林知远、陈雨安夫妇拥有远山47.76%的股权，是最大股东。', 'subject': '林知远'}
    joint['observation'] = observation(joint, '林知远')
    others = {'fact': '林知远是另一机构的间接出资人。', 'subject': '林知远'}
    assert 'joint_holding_as_individual' in source_context_errors('来源披露林知远为远山最大股东（47.76%），亦为另一机构间接出资人。', [joint, others])
    assert not source_context_errors('来源披露林知远、陈雨安夫妇合计持有远山47.76%股权。', [joint, others])


def test_indirect_capital_affiliations_keep_the_intermediate_institution():
    rows = [{'fact': '林知远是云峰投资、山海投资的间接出资人之一，这些公司的关联方有青禾商业、巨石网络等公司。'}]
    assert source_context_errors('其为云峰投资等机构间接出资人，关联青禾商业、巨石网络等外部资本。', rows) == ['indirect_relationship_flattened']
    assert not source_context_errors('林知远是云峰投资的间接出资人；上述机构的关联方包括青禾商业、巨石网络。', rows)


def test_conditional_board_authorization_is_not_an_effective_approval():
    from person_records import definition_errors
    rows = [{'fact': '董事会同意提请股东大会授权，并在取得股东大会批准后，由董事会授权林知远全权办理发行事项。'}]
    assert 'conditional_authorization_as_completed' in definition_errors('来源载明董事会授权林知远全权处理发行。', rows)
    assert 'conditional_authorization_as_completed' not in definition_errors('董事会提请股东大会批准后授权林知远办理发行，后续生效情况待核。', rows)


def test_separate_role_dates_do_not_become_one_common_tenure():
    from person_records import definition_errors
    rows = [{'fact': '林知远董事长、执行董事、总裁 董事长、执行董事任期为2011年6月11日至2014年6月10日，总裁任期自2002年6月10日起。'}]
    assert 'mixed_role_tenure_not_supported' in definition_errors('来源载明林知远担任董事长、执行董事、总裁，任期起止为2011年6月11日至2014年6月10日。', rows)
    assert 'mixed_role_tenure_not_supported' not in definition_errors('董事长、执行董事的任期为2011年6月11日至2014年6月10日，总裁任期自2002年6月10日起。', rows)


def test_education_summary_does_not_erase_career_details_in_same_source():
    rows = [{'fact': '林知远于1987年毕业，1995年创办恒川软件，现任公司董事长。'}]
    assert source_context_errors('教育经历仅限1987年毕业，无其他学历或履历信息。', rows) == ['available_career_material_denied']
    assert not source_context_errors('来源载明1987年毕业及后续创办、任职，部分任期起止尚未对齐。', rows)


def test_collective_resignation_threat_and_dismissal_order_are_not_completed_events():
    rows = [{'fact': '员工以“集体辞职”相要挟，陈雨安当即下令，将这些人全部开除。林知远后来才知道此事。'}]
    assert source_context_errors('改革引发员工集体辞职抗议，陈雨安随即执行开除。', rows) == ['threatened_event_as_occurred', 'directed_action_as_completed']
    assert not source_context_errors('员工以集体辞职相要挟，陈雨安下令开除，实际执行结果尚未载明。', rows)


def test_absence_claim_uses_complete_research_context_not_only_selected_quotes():
    supports = [{'fact': '林知远是云峰投资的间接出资人。', 'subject_scope': 'person'}]
    context = [*supports, {'fact': '林知远、陈雨安夫妇拥有远山国际47.76%的股权。', 'subject_scope': 'person'}]
    claim = '材料未载明其在远山国际的任职、持股或实际控制状态。'
    assert source_context_errors(claim, supports, context) == ['broader_material_contains_claimed_missing_fact']
    assert not source_context_errors('所引片段未载明其在远山国际的当前持股情况，另有历史记录待核。', supports, context)


def test_year_month_day_cannot_be_recombined_from_different_dates():
    rows = [{'fact': '林知远于2022年3月1日卸任，公司于2026年1月13日披露新安排。'}]
    assert 'unsupported_date_combination' in source_context_errors('来源载明林知远于2022年1月13日卸任。', rows)
    assert not source_context_errors('来源载明2022年3月1日卸任，另一安排披露于2026-01-13。', rows)


def test_existing_roster_date_range_is_not_reported_as_absent():
    from person_records import observation
    row = {'fact': '林知远 董事长、执行董事 男 １９６６年出生 ２００８年６月１１日至２０１１年６月１０日；具体职务对应仍待核。'}
    row['observation'] = observation(row, '林知远')
    assert row['observation']['role_date_fields'][0]['source_value'] == '２００８年６月１１日至２０１１年６月１０日'
    assert source_context_errors('所有材料未载明具体起始日期或任期覆盖区间。', [row]) == ['available_role_period_denied']
    assert not source_context_errors('原文已列历史时间区间，但未说明当前任职起止与职务对应。', [row])


def test_exact_source_monetary_bound_is_not_a_new_comparison():
    from person_records import comparison_errors
    rows = [{'fact': '公司公告称林知远计划在12个月内增持不少于1亿元。', 'subject': '林知远'},
            {'fact': '另一报道载明林知远于5月增持1135万股。', 'subject': '林知远'}]
    assert not comparison_errors('公告载明计划增持不少于1亿元，另一报道记载1135万股，材料类型分别为计划和交易。', rows)
    assert comparison_errors('实际增持1135万股高于计划1亿元。', rows)


def test_approved_transfer_and_payment_do_not_establish_actual_closing():
    from person_records import definition_errors
    rows = [{'fact': '1997年股东会一致同意将持有的公司全部出资额290万元以总价302万元转让给甲公司、林知远和陈雨安。1995年已有转让意向，部分价款已支付。'}]
    assert 'conditional_transfer_as_completed' in definition_errors('1995年意向与1997年实际交割存在时间差。', rows)
    assert 'conditional_transfer_as_completed' not in definition_errors('股东会同意转让，已支付部分价款，未说明实际交割时点。', rows)
