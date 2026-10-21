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
