from person_source_boundaries import source_context_errors


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
