from copy import deepcopy

import pytest

from report_agents.company_beneficial_ownership import beneficial_ownership_disclosures
from report_agents.company_governance import build_governance_package,render_governance,governance_graph_nodes
from test_company_governance import evidence


NAME='星河网络集团有限公司'


def ownership(day='2025 年5月18日'):
    return ('A. 主要股東\n下表載列截至 '+day+'，以下人士對我們的普通股擁有實益所有權的相關信息：\n'
        '本年度報告中呈列的實益所有權資料按照美國證交會的規則和條例認定，包括表決或處置權；'
        '逐人計入截至日後60日內有權取得的股份。\n'
        '實益所有權 實益所有權\n姓名 （股份） （美國存託股）\n(1)\n比例\n'
        '董事及高級管理人員：\n趙一\n(2) 12,000 1,500 0.1%\n'
        'Alex 123 Quinn 80 10 0.0%\n全體董事及高級管理人員合計 13,000 1,625 0.2%\n'
        '附註：\n(1) 美國存託股數目僅按原表顯示。\n(2) 趙一的權利另見下頁。')


def pages(raw=None):
    return [{'page':72,'text':raw or ownership()},
            {'page':73,'text':'趙一先生對受託機構持有的8,000股股份並不具有任何金錢權益。\nB. 關聯交易'}]


def source_pair(i=1,raw=None,**changes):
    body=raw or ownership();p=pages(body)
    card,src=evidence(NAME,NAME+'2025年年度报告\n'+body,i=i,meta={'content_kind':'full_text','document_pages':p})
    card['source_url']=src['url']=f'https://www.hkexnews.hk/annual-{i}.pdf'
    src.update(changes)
    return card,src


def package(*pairs,as_of='2026-10-20'):
    return build_governance_package({'facts':[c for c,s in pairs]},NAME,[s for c,s in pairs],as_of_date=as_of)


def test_original_names_three_columns_dates_zero_display_and_aggregate_are_kept_separate():
    original=pages();before=deepcopy(original)
    rows,contexts=beneficial_ownership_disclosures(original,as_of_date='2026-10-20')
    assert len(rows)==3 and len(contexts)==1 and original==before
    assert rows[0]['entity']=='趙一' and rows[0]['ordinary_shares']=='12,000' and rows[0]['ads']=='1,500'
    assert rows[0]['footnote_marker']=='2' and rows[0]['cutoff']=='2025-05-18'
    assert rows[1]['entity']=='Alex 123 Quinn' and rows[1]['ratio']=='0.0%' and rows[1]['ordinary_shares']=='80'
    assert rows[2]['kind']=='beneficial_ownership_total' and rows[2]['ordinary_shares']=='13,000'
    assert rows[2]['ordinary_shares']!='12,080'  # No invented sum or ADS conversion.
    assert all(r['evidence_quote'] in original[0]['text'] for r in rows)
    note=contexts[0]['holder_caveats'][0]
    assert note['page']==73 and note['quote'] in original[1]['text'] and '金錢權益' in note['quote']


def test_verified_filing_table_is_not_a_registry_or_a_controller_graph():
    p=package(source_pair())
    assert {r['kind'] for r in p['facts']}=={'beneficial_ownership','beneficial_ownership_total'}
    assert governance_graph_nodes(p,'equity')==[] and governance_graph_nodes(p,'control')==[]
    text=render_governance(p)
    assert '非完整登记股东名册' in text and '不直接等同本人金钱权益' in text
    assert '0.0%为原表显示值' in text and '原表合计，非独立主体' in text
    assert '8,000股股份並不具有任何金錢權益' in text
    assert '2025-05-18' in text and '原注2' in text


def test_identical_original_mirrors_preserve_provenance_without_duplicating_holders():
    p=package(source_pair(1),source_pair(2))
    assert len(p['facts'])==3 and len(p['beneficial_ownership_contexts'])==1
    assert all(len(r['evidence_ids'])==2 for r in p['facts'])


def test_same_date_conflicting_values_are_not_overwritten_or_averaged():
    p=package(source_pair(1),source_pair(2,ownership().replace('12,000','14,000')))
    holders=[r for r in p['facts'] if r['entity']=='趙一']
    assert {r['ordinary_shares'] for r in holders}=={'12,000','14,000'}
    assert any('受益所有权' in r['field'] for r in p['conflicts'])


def test_latest_allowed_table_date_is_not_the_fiscal_date_or_current_query_date():
    old=source_pair(1,ownership('2024 年5月18日'));new=source_pair(2)
    p=package(old,new,as_of='2024-12-31')
    assert {r['cutoff'] for r in p['facts']}=={'2024-05-18'}
    p=package(old,new)
    assert {r['cutoff'] for r in p['facts']}=={'2025-05-18'}


@pytest.mark.parametrize('transform',[
    lambda s:s.replace('按照美國證交會的規則和條例','按本地登記規定'),
    lambda s:s.replace('（美國存託股）','（本期獲授股份）'),
    lambda s:s.replace('姓名 （股份）','姓名 （股份） （另列其他權利）'),
    lambda s:s.replace('下表載列截至 2025 年5月18日','下表列示'),
    lambda s:'以下僅為示例\n'+s,
])
def test_unproved_units_layouts_missing_dates_and_examples_are_not_admitted(transform):
    assert beneficial_ownership_disclosures(pages(transform(ownership())))[0]==[]


def test_malformed_number_does_not_become_a_smaller_valid_holding():
    rows,_=beneficial_ownership_disclosures(pages(ownership().replace('12,000','1,23,000')))
    assert not any(r['entity']=='趙一' for r in rows)


def test_future_table_and_invalid_cutoff_are_not_silently_admitted():
    assert beneficial_ownership_disclosures(pages(),as_of_date='2024-01-01')[0]==[]
    assert beneficial_ownership_disclosures(pages(),as_of_date='bad-date')[0]==[]


def test_summary_discovery_and_subsidiary_cover_do_not_authenticate_a_table():
    card,src=source_pair();src['source_metadata']['content_kind']='search_summary'
    assert not package((card,src))['facts']
    card,src=source_pair();src['content']='星河存储科技有限公司2025年年度报告\n'+NAME+'2025年年度报告的股东为本公司。\n'+ownership()
    assert not package((card,src))['facts']
