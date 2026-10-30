import copy

import pytest
from opencc import OpenCC

from report_agents.company_text import OriginalTextView, issuer_anchor, match_text
from report_agents.company_management import issuer
from report_agents.company_people import table_metrics, build_people_package, render_people
from report_agents.company_reputation import survey_table_rows, build_reputation_package, render_reputation
from report_agents.report_prompts import _company_fact_has_trusted_target_anchor, infer_company_fact_tags

T = OpenCC('s2t')


@pytest.mark.parametrize('target', ['青禾制造股份有限公司', '星河电子有限公司', '远山食品有限责任公司'])
def test_original_publisher_statement_accepts_script_variant_without_renaming_source(target):
    raw = '关于本报告\n本报告是' + T.convert(target) + '（以下简称「本公司」）发布的第五份ESG报告。'
    source = {'url': 'https://www1.hkexnews.hk/issuer.pdf', 'content': T.convert(raw)}
    before = copy.deepcopy(source)
    assert issuer(source, target, set())
    assert issuer_anchor(source['content'], target)['evidence_quote'] in source['content']
    assert source == before


@pytest.mark.parametrize('raw', [
    '本报告包含青禾制造股份有限公司及其附属公司的资料。',
    '本报告由青禾制造包装股份有限公司发布，青禾制造股份有限公司为其股东。',
    '青禾制造包装股份有限公司\n2025年度可持续发展报告\n本报告是青禾制造股份有限公司发布的ESG报告。',
    '本报告由青禾制造股份有限公司提供支持，编制发布单位另见附注。',
])
def test_script_matching_does_not_relax_publisher_or_parent_child_boundaries(raw):
    source = {'url': 'https://www.hkexnews.hk/report.pdf', 'content': T.convert(raw),
              'title': '青禾制造股份有限公司2025年报告'}
    assert not issuer(source, '青禾制造股份有限公司', set())


def test_unknown_domain_and_rejected_entity_still_fail():
    s = {'url': 'https://unknown.test/report.pdf', 'content': '青禾製造股份有限公司\n2025年年度報告'}
    assert not issuer(s, '青禾制造股份有限公司', set())
    s['url'] = 'https://www.hkexnews.hk/report.pdf'
    s['source_metadata'] = {'entity_validation': 'rejected'}
    assert not issuer(s, '青禾制造股份有限公司', set())


def test_exchange_wrapper_narrative_is_not_a_conflicting_legal_name():
    raw=('青 禾 製 造 股 份 有 限 公 司\nOVERSEAS REGULATORY ANNOUNCEMENT\n'
         '以下為青禾製造股份有限公司於交易所網站刊發之「青禾製造股份有限公司\n2025年年度報告全文」。\n'
         '青禾製造股份有限公司\n2025 年年度報告')
    anchor=issuer_anchor(raw,'青禾制造股份有限公司')
    assert anchor['matched'] and not anchor['conflicting_heading']


def test_spaced_subsidiary_cover_still_conflicts_with_parent_claim():
    raw='青 禾 製 造 包 裝 股 份 有 限 公 司\n2025年年度報告\n本報告是青禾製造股份有限公司發佈。'
    anchor=issuer_anchor(raw,'青禾制造股份有限公司')
    assert anchor['conflicting_heading'] and not anchor['matched']


def test_matching_view_maps_length_changing_conversion_to_actual_original(monkeypatch):
    monkeypatch.setattr('report_agents.company_text.match_text', lambda x: x.replace('AB', 'XYZ'))
    view = OriginalTextView('指标甲AB乙 35.7%')
    assert view.quote(view.text.index('X'), view.text.index('Z')+1) == 'AB'
    start = view.text.index('甲')
    assert view.quote(start, view.text.index('乙')+1) == '甲AB乙'


def test_long_repetitive_originals_align_only_independently_verified_lines(monkeypatch):
    from difflib import SequenceMatcher
    sizes=[]
    def observed(junk,a,b,**kw):
        sizes.append((len(a),len(b)))
        return SequenceMatcher(junk,a,b,**kw)
    monkeypatch.setattr('report_agents.company_text.SequenceMatcher',observed)
    raw=('董事會及股東資料。'*12+'\n')*45+'青禾製造股份有限公司\n年度報告。'
    view=OriginalTextView(raw)
    start=view.text.index('青禾制造股份有限公司')
    assert view.quote(start,start+len('青禾制造股份有限公司'))=='青禾製造股份有限公司'
    assert view.quote(start,start+len('青禾制造股份有限公司\n年度报告。'))=='青禾製造股份有限公司\n年度報告。'
    assert sizes and max(max(s) for s in sizes)<=max(map(len,raw.splitlines(keepends=True)))


def test_cross_line_conversion_falls_back_to_whole_original_alignment(monkeypatch):
    monkeypatch.setattr('report_agents.company_text.match_text',lambda x:x.replace('A\nB','XYZ'))
    view=OriginalTextView('甲A\nB乙')
    assert view.quote(view.text.index('X'),view.text.index('Z')+1)=='A\nB'


def test_single_year_traditional_metrics_keep_units_quote_and_absent_comparison():
    raw = ('指標名稱 單位 2025年\n員工總人數 千人 198\n員工流失率 % 35.7\n'
           '員工培訓覆蓋率 % 100\n支持員工繼續教育投入金額 萬元 866.5\n累計培訓總費用 億元 1.7')
    rows = table_metrics({'page': 74, 'text': raw})
    assert len(rows) == 5
    assert next(r for r in rows if r['kind'] == 'workforce')['unit'] == '千人'
    assert next(r for r in rows if r['metric'] == '累计培训总费用')['value'] == '1.7'
    assert all(r['previous_period'] == '' and r['previous_value'] == '—' for r in rows)
    assert all(r['evidence_quote'] in raw and r['source_metric'] in raw for r in rows)
    assert not any('198000' in r['fact'] or '2024年' in r['fact'] for r in rows)


@pytest.mark.parametrize('raw', [
    '員工總人數 千人 198',
    '指標名稱 單位 2025年\n員工總人數 千人 198 200',
    '指標名稱 單位 2025年\n員工總人數 未知 198',
    '指標名稱 單位 2025年 2025年\n員工總人數 人 198 200',
    '指標名稱 單位 2024年 2025年\n員工總人數 人 198 /',
])
def test_single_year_support_does_not_guess_missing_or_ambiguous_columns(raw):
    assert not table_metrics({'page': 1, 'text': raw})


def test_single_year_surveys_keep_distinct_original_labels_and_no_fake_change():
    raw = '指標名稱 單位 2025年\n用戶滿意度 % 99.02\n產品及服務投訴率 % 0.05'
    rows = survey_table_rows({'page': 75, 'text': raw})
    assert [(r['metric'], r['value']) for r in rows] == [('用户满意度', '99.02'), ('产品及服务投诉率', '0.05')]
    assert all(r['previous_period'] == '' and r['previous_value'] == '—' for r in rows)
    assert all(r['evidence_quote'] in raw and r['source_metric'] in raw for r in rows)


def test_cleaning_anchor_and_tags_use_local_script_view_but_respect_rejection():
    c = {'source_title': '青禾製造股份有限公司2025年員工培訓報告', 'evidence_quote': '員工培訓覆蓋率100%',
         'fact': '員工培訓覆蓋率100%', 'eligible_for_report': True}
    before = copy.deepcopy(c)
    assert _company_fact_has_trusted_target_anchor(c, '青禾制造股份有限公司')
    assert 'workforce' in infer_company_fact_tags(c)
    assert c == before
    assert not _company_fact_has_trusted_target_anchor({**c, 'source_entity_validation': 'rejected'}, '青禾制造股份有限公司')
    assert not _company_fact_has_trusted_target_anchor({**c, 'source_url': 'structured://qcc/test',
        'entity_name': '青禾製造包裝股份有限公司', 'source_entity_validation': 'verified'}, '青禾制造股份有限公司')


def test_company_packets_keep_training_population_note_and_raw_scope():
    raw = ('指標名稱 單位 2025年\n員工總人數 千人 198\n員工培訓覆蓋率 % 100\n'
           '34 受訓員工比例計算公式為：該類別受訓員工數量/受訓員工總數。培訓數據為平台記錄，未含部分線下數據。\n'
           '指標名稱 單位 2025年\n用戶滿意度 % 99.02')
    url = 'https://www1.hkexnews.hk/report.pdf'
    source = {'url': url, 'content': '本報告是青禾製造股份有限公司發佈的ESG報告。\n' + raw,
              'title': '青禾製造股份有限公司2025年ESG報告', 'source_metadata': {
              'document_pages': [{'page': 74, 'text': raw}], 'content_kind': 'pdf_text_extracted'}}
    c = {'evidence_id': 'E-ABCDEF123456', 'source_url': url, 'source_title': source['title']}
    people = build_people_package({'facts': [c]}, '青禾制造股份有限公司', [source])
    text = render_people(people)
    assert '198千人' in text and '未含部分線下數據' in text
    # A class share of trained staff is not the denominator of the company's
    # overall training coverage; its raw footnote remains a source note.
    assert all(not r.get('definitions') for r in people['facts'] if r['kind'] == 'training')
    assert any('該類別受訓員工數量' in n['text'] for n in people['source_notes'])
    reputation = build_reputation_package({'facts': [c]}, '青禾制造股份有限公司', [source])
    assert '用戶滿意度' in render_reputation(reputation)


def test_cleaning_recovers_issuer_from_original_not_short_search_title_or_invented_field():
    from types import SimpleNamespace
    from research_workflow import ResearchWorkflow
    w = ResearchWorkflow.__new__(ResearchWorkflow)
    url = 'https://www1.hkexnews.hk/report.pdf'
    s = SimpleNamespace(url=url, title='2025 ESG報告', content='本報告是青禾製造股份有限公司發佈的ESG報告。',source_metadata={})
    p = SimpleNamespace(target_type='company', target_name='青禾制造股份有限公司', sources=[s])
    c = {'source_url':url, 'source_title':s.title,'fact':'員工培訓覆蓋率100%', 'evidence_quote':'員工培訓覆蓋率100%'}
    before = copy.deepcopy(c)
    card = w._annotate_evidence_facts(p,[c])[0]
    assert card['evidence_scope']=='target_direct'
    assert card['source_issuer_name']=='青禾製造股份有限公司'
    assert card['source_issuer_quote'] in s.content and c==before
    s.content='本報告是青禾製造包裝股份有限公司發佈的ESG報告。青禾製造股份有限公司為其股東。'
    forged={**c,'source_issuer_name':'青禾制造股份有限公司','source_issuer_quote':'本报告是青禾制造股份有限公司发布'}
    card=w._annotate_evidence_facts(p,[forged])[0]
    assert not card.get('source_issuer_name')
    assert card['evidence_scope']!='target_direct'
    s.content='青禾製造包裝股份有限公司\n2025年年度報告\n本報告是青禾製造股份有限公司發佈。'
    misleading={**c,'source_title':'青禾制造股份有限公司2025年年度报告'}
    card=w._annotate_evidence_facts(p,[misleading])[0]
    assert card['evidence_scope']=='related_entity_context'
    assert not _company_fact_has_trusted_target_anchor(card,p.target_name)


def test_traditional_policy_retains_original_quote_and_does_not_admit_accounting():
    from report_agents.company_people import policy_rows
    raw='本集團建立覆蓋全體員工的培訓體系，提供新員工入職培訓與人才培養課程。'
    rows=policy_rows([{'page':30,'text':raw}],'2025年','青禾制造股份有限公司')
    assert rows and rows[0]['evidence_quote'] in raw and '培訓體系' in rows[0]['fact']
    accounting='本集團在職工提供服務的會計期間，將實際發生的短期薪酬確認為負債，並計入當期損益。'
    assert not policy_rows([{'page':31,'text':accounting}],'2025年','青禾制造股份有限公司')


def test_employee_survey_chart_method_not_guessed_score_or_no_disclosure():
    url='https://www1.hkexnews.hk/report.pdf'
    raw='我們每年開展統一的員工敬業度調查，通過系統分析調查結果並制定針對性優化措施。\nBand類員工調查分數（滿分100分）\n74\n80\n77\n79'
    s={'url':url,'title':'2025年ESG報告','content':'本報告是青禾製造股份有限公司發佈的ESG報告。\n2025年\n'+raw,
       'source_metadata':{'document_pages':[{'page':39,'text':raw}]}}
    c={'source_url':url,'source_title':s['title'],'evidence_id':'E-ABCDEF123456'}
    p=build_reputation_package({'facts':[c]},'青禾制造股份有限公司',[s]);t=render_reputation(p)
    method=next(r for r in p['facts'] if r['kind']=='survey_method')
    assert method['evidence_quote'] in raw and 'Band類' in t
    assert '尚未可靠绑定' in t and '79分' not in t
    assert not any(r['kind']=='survey' for r in p['facts'])


def test_learning_product_name_is_not_a_citation_but_unknown_bracketed_id_is():
    from report_agents.company_governance import cited_evidence_ids
    assert cited_evidence_ids('E-learning及E-LEARNING平台，证据[E-123456ABCDEF]')==['E-123456ABCDEF']
    assert cited_evidence_ids('未知证据[E-FFFFFFFFFFFF]及[E-LEARNING]')==['E-FFFFFFFFFFFF','E-LEARNING']


@pytest.mark.parametrize('target',['青禾制造股份有限公司','远山食品股份有限公司'])
def test_real_style_learning_platform_does_not_degrade_people_chapter(target):
    from report_agents.company_people import people_errors
    url='https://www.hkexnews.hk/report.pdf'
    text=target+'积极推进数字化人才培养平台的建设工作，搭建了 E-learning在线学习平台，让员工随时随地可以获取知识，实现了100%培训覆盖。'
    s={'url':url,'title':target+'2025年年度报告','content':target+'\n2025年年度报告\n'+text,
       'source_metadata':{'document_pages':[{'page':71,'text':text}]}}
    c={'source_url':url,'source_title':s['title'],'evidence_id':'E-123456ABCDEF'}
    p=build_people_package({'facts':[c]},target,[s]);body=render_people(p)
    assert 'E-learning' in body and not people_errors(body,p)
    assert any('未知证据编号' in e for e in people_errors(body+' [E-FFFFFFFFFFFF]',p))
