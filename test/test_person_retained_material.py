from types import SimpleNamespace
from person_retained_material import retained_source_statements


def source(body, **meta):
    return SimpleNamespace(url='https://fixture.invalid/profile', title='林知远的经历', content=body,
        source_metadata={'identity_confidence':'high', 'content_kind':'full_text', 'fetch_status':'done', **meta})


INTAKE={'target_name':'林知远','person_anchor':{'known_affiliations':['恒川软件']}}


def test_full_source_scan_keeps_late_distinct_statements_and_literal_whitespace():
    quotes=[f'林知远于{1980+n}年参加项目编号{n}的研发，并在恒川软件负责不同产品的技术管理。' for n in range(65)]
    quotes.append('林知远于\n一九九零年毕业于远山大学，\n获得硕士学位并进入恒川软件任职。')
    rows=retained_source_statements([source('\n\n'.join(quotes))],INTAKE)
    assert [r['fact'] for r in rows] == quotes
    assert rows[-1]['evidence_quote'] == quotes[-1]


def test_source_without_existing_cards_is_still_scanned_but_snippet_is_not():
    original='林知远于1990年毕业于远山大学，之后在恒川软件担任技术经理。'
    audit=[]
    assert len(retained_source_statements([source(original)],INTAKE,audit=audit)) == 1
    assert audit[0]['retained_chars_scanned'] == len(original)
    audit=[]
    assert not retained_source_statements([source(original,person_discovery_only=True)],INTAKE,audit=audit)
    assert audit[0]['status'] == 'not_admitted'


def test_existing_longer_quote_covers_shorter_statement_without_adding_duplicate():
    quote='林知远于1990年毕业于远山大学，之后在恒川软件担任技术经理。'
    assert not retained_source_statements([source(quote)],INTAKE,[{'source_url':source('').url,'fact':quote+'后续记载另一件事。'}])


def test_related_headline_is_not_promoted_to_original_statement():
    assert not retained_source_statements([source('林知远全部新闻\n林知远拟在明年扩张业务 (2020-03-01)')],INTAKE)
    assert not retained_source_statements([source('林知远去年工资缩水3成 为何拼不过其他公司高管？ (2013-04-02 03:15)')],INTAKE)


def test_literal_profile_fields_do_not_need_sentence_punctuation_or_repeat_name():
    body='人物首页\n\n林知远\n\n职务 ：恒川软件董事长\n\n单位 ：恒川软件有限公司\n\n毕业院校：远山大学（本科），白河学院（硕士） 详细资料>>\n\n热门人物\n\n其他人'
    rows=retained_source_statements([source(body)],INTAKE)
    assert len(rows)==1 and rows[0]['literal_profile_fields']
    assert rows[0]['fact'] in body and '毕业院校' in rows[0]['fact']
    assert '热门人物' not in rows[0]['fact']


def test_feedback_source_supplement_is_attributed_context_not_personal_analysis():
    quote='林知远曾用鱼池比喻公司技术储备，报道将这些投资解释为供应链布局。'
    rows=retained_source_statements([source(quote,person_feedback_only=True)],INTAKE)
    assert rows[0]['opinion_only'] and rows[0]['eligible_for_risk_scoring'] is False
    from person_evidence import normalize_facts
    facts,rejected=normalize_facts({'facts':rows},'林知远',sources=[source(quote,person_feedback_only=True)])
    assert not rejected and len(facts)==1


def test_context_admission_cannot_accept_an_invented_quote():
    from person_evidence import normalize_facts
    row=retained_source_statements([source('林知远曾用鱼池比喻公司技术储备，报道将这些投资解释为供应链布局。',person_feedback_only=True)],INTAKE)[0]
    row['fact']='林知远曾经承诺承担所有投资亏损，现已完成全部赔偿。'
    row['evidence_quote']=row['fact']
    facts,rejected=normalize_facts({'facts':[row]},'林知远',sources=[source('原文没有此项陈述。',person_feedback_only=True)])
    assert not facts and rejected
