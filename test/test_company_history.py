import json
from types import SimpleNamespace

import pytest

from report_agents.company_history import (
    TITLE, HEADINGS, _date, _event_status, _heading_events,
    build_history_package, financial_rows, render_history, history_errors,
)
from report_agents.company_report_agent import CompanyReportAgent
from test_company_governance import evidence


def history(name,*pairs,**kwargs):
    return build_history_package({'facts':[p[0] for p in pairs]},name,[p[1] for p in pairs],**kwargs)


def filing(name,body,*,i=1,year=2025,scope='target_direct'):
    c,s=evidence(name,name+f'{year}年年度报告。'+body,i=i,evidence_scope=scope)
    c['source_url']=s['url']=f'https://static.cninfo.com.cn/{year}/{i}.pdf'
    c['source_title']=s['title']='COMPANY REPORT'
    s['source_type']='filing'
    return c,s


def financial_table(name,*,revenue='120.00',prior='100.00',profit='8.00',old_profit='10.00',unit='万元'):
    return (f'\n\n| 项目 | 2025年 | 2024年 | 本年比上年增减 |\n| --- | --- | --- | --- |\n'
            f'| 营业收入（{unit}） | {revenue} | {prior} | 20.00% |\n'
            f'| 归属于上市公司股东的净利润（{unit}） | {profit} | {old_profit} | -20.00% |\n'
            f'| 经营活动产生的现金流量净额（{unit}） | 6.00 | 12.00 | -50.00% |')


@pytest.mark.parametrize('name',['星河精密股份有限公司','青禾食品有限公司','Northstar Robotics Limited'])
def test_template_aligned_company_independent_history_without_example_facts(name):
    raw=f'{name}于2019年3月2日成立。公司于2025年6月1日完成新产线投产。'
    p=history(name,filing(name,raw))
    text=render_history(p)
    assert '历史沿革与成长质量'==TITLE
    assert name in text and all('### '+h in text for h in HEADINGS)
    assert '比亚迪' not in text and '无实质性出资瑕疵' not in text
    assert '成长质量待核验' in text and '0万元' not in text
    assert history_errors(text,p)==[]


def test_listing_date_distinct_from_approval_date():
    claim='公司于2011年6月7日经核准，首次发行7,900万股，于2011年6月30日在证券交易所上市。'
    assert _date(claim)=='2011-06-30'


def test_capital_base_date_not_used_as_execution_date():
    claim='公司于2008年3月20日经股东会批准，以2007年6月30日总股本为基数实施资本公积转增。'
    assert not _date(claim).startswith('2007')


def test_completion_date_not_replaced_by_embedded_distribution_year_or_parenthesized_base():
    claim='公司于2025年7月29日实施完成2024年度分红方案，以董事会召开日即（2025年4月22日）总股本为基数转增。'
    assert _date(claim)=='2025-07-29'


def test_omitted_execution_year_does_not_become_approval_date():
    assert _date('本公司于2002年6月12日经批准发行H股，并于7月31日在香港联交所上市。')==''


def test_nested_bond_name_year_not_replace_exact_issue_date():
    assert _date('于2025年8月25日，本公司发行公司2025年度科技创新债券。')=='2025-08-25'


def test_range_in_document_name_not_interpreted_as_2027_completed_financing():
    name='星河精密股份有限公司'
    p=history(name,filing(name,'本所接受'+name+'委托，担任注册“公司2025-2027年度债务融资工具”的特聘法律顾问。'))
    assert not any(r['kind']=='event' and r['period']=='2027' for r in p['facts'])


def test_carbon_target_year_not_used_as_signing_date():
    assert _date('本集团签署储能供货协议，助力阿联酋二零五零年碳中和目标战略落地。')==''


def test_issuer_esg_pdf_year_headings_are_not_a_website_history():
    name='星河精密股份有限公司'
    annual=filing(name,'网站：https://www.example-manufacturer.test\n公司于2019年成立。')
    c,s=evidence(name,'# 2045\n- 要求合作伙伴遵守个人数据保护标准和要求',i=2)
    c['source_url']=s['url']='https://www.example-manufacturer.test/esg.pdf'
    s['source_metadata']['document_pages']=[{'page': 1, 'text': s['content']}]
    p=history(name,annual,(c,s))
    assert not any(r['kind']=='event' and r['period']=='2045' for r in p['facts'])


@pytest.mark.parametrize('claim,status',[
    ('公司于2025年5月签署收购协议。','已签约／完成待核验'),
    ('公司计划于2026年完成投产。','计划／拟议'),
    ('公司于2025年5月完成收购交割。','原文记载已发生'),
    ('公司于2025年5月收购事项尚未完成。','尚未完成'),
    ('公司于2025年4月22日审议通过资本公积转增方案。','已决议／执行待核验'),
    ('公司审议通过方案后于2025年7月实施完毕资本公积转增。','原文记载已发生'),
])
def test_proposal_signing_and_completion_are_distinct(claim,status):
    assert _event_status(claim)==status


def test_product_release_not_inferred_to_be_commercial_success():
    name='青禾食品有限公司'
    p=history(name,filing(name,'公司于2025年5月发布新产品，计划下一年度建设产线。'))
    text=render_history(p)
    assert '品牌公信力' not in text and '驱动产品力升级' not in text and '显著提升资本背书' not in text


def test_unknown_issuer_or_rejected_fact_not_recovered_from_filing_query():
    name='青禾食品有限公司'
    c,s=filing(name,'公司于2025年5月完成产线投产。',scope='industry_context')
    s['content']='青禾餐饮有限公司2025年年度报告。公司于2025年5月完成产线投产。'
    assert history(name,(c,s))['facts']==[]
    c,s=filing(name,'公司于2025年5月完成产线投产。')
    c['eligible_for_report']=False
    assert history(name,(c,s))['facts']==[]


def test_subsidiary_and_personal_resume_events_do_not_become_parent_history():
    name='星河精密股份有限公司'
    p=history(name,filing(name,'子公司于2025年3月完成产线投产。王先生于2003年创办另一家公司。'))
    assert not any(r['kind']=='event' for r in p['facts'])


def test_running_filing_headers_and_financial_table_words_not_milestones():
    name='星河精密股份有限公司'
    raw=name+'2025年年度报告全文26本集团持续推出适配多元场景的产品。'+name+'2025年年度报告全文198合并财务报表主要项目注释，预收购房款和合同负债表。'
    p=history(name,filing(name,raw))
    assert not any(r['kind']=='event' for r in p['facts'])


def test_markdown_annual_finances_and_foreign_currency_preserved():
    rows=financial_rows(financial_table('青禾',unit='万美元'),'2025年年度报告')
    assert len(rows)==3 and rows[0]['unit']=='万美元'
    assert rows[0]['value']=='120.00' and rows[0]['previous_value']=='100.00'
    assert rows[1]['yoy']=='-20.00%'


def test_finances_require_header_and_handle_reversed_columns():
    row='| 营业收入（元） | 100.00 | 120.00 | 20.00% |'
    assert financial_rows(row,'2025年年度报告')==[]
    rows=financial_rows('| 项目 | 2024年 | 2025年 | 同比增减 |\n| --- | --- | --- | --- |\n'+row,'2025年年度报告')
    assert rows[0]['value']=='120.00' and rows[0]['previous_value']=='100.00'


def test_flattened_financial_table_retains_adjacent_two_decimal_values():
    raw='2025年2024年本年比上年增减2023年营业收入（元）803,964,958,000.00777,102,455,000.003.46%602,315,354,000.00'
    r=financial_rows(raw,'2025年年度报告')[0]
    assert r['value']=='803,964,958,000.00' and r['previous_value']=='777,102,455,000.00'
    assert r['yoy']=='3.46%'


def test_growth_judgment_reflects_profit_and_cash_divergence():
    name='青禾食品有限公司'
    p=history(name,filing(name,financial_table(name)))
    text=render_history(p)
    assert '规模与利润表现分化' in text and '经营现金流净额同比减少' in text
    assert '规模实现较快增长' not in text and '发展路径整体较为顺畅' not in text


def test_half_year_and_full_year_not_compared_to_each_other():
    name='青禾食品有限公司'
    annual=filing(name,financial_table(name))
    c,s=filing(name,financial_table(name,revenue='60.00',prior='50.00'),i=2,year=2026)
    s['content']=s['content'].replace('2026年年度报告','2026年半年度报告')
    s['content']=s['content'].replace('2025年 | 2024年','本报告期 | 上年同期')
    p=history(name,annual,(c,s));text=render_history(p)
    assert '2025年年度报告' in text and '2026年半年度报告' in text
    assert '不拿半年数与全年数相除' in text


def test_financial_conflicting_values_kept_and_not_used_for_trend():
    name='青禾食品有限公司'
    a=filing(name,financial_table(name),i=1)
    b=filing(name,financial_table(name,revenue='999.00'),i=2)
    p=history(name,a,b);text=render_history(p)
    assert '120.00万元' in text and '999.00万元' in text and '差异待核验' in text
    assert '规模与利润表现分化' not in text
    assert '[E-000000000001]' in text and '[E-000000000002]' in text


def test_duplicate_mirrors_and_no_fabricated_currency_conversion():
    name='青禾食品有限公司'
    raw='公司于2025年3月11日完成配售，配售价335.2港元，所得款项净额约43,383百万港元。'
    p=history(name,filing(name,raw,i=1),filing(name,raw,i=2))
    events=[r for r in p['facts'] if r['kind']=='event']
    assert len(events)==1 and len(events[0]['evidence_ids'])==2
    text=render_history(p)
    assert '43,383百万港元' in text and '约合人民币' not in text


def test_page_excerpt_false_number_not_reintroduced_as_atomic_history():
    name='青禾食品有限公司';raw='公司于2019年成立。'
    c,s=filing(name,raw)
    c.update(claim_type='fact',fact=name+'于2019年成立，初始资本999万元。',evidence_quote=raw)
    p=history(name,(c,s))
    assert '999' not in render_history(p)


def test_legacy_absence_and_capital_rounding_do_not_prove_legality():
    name='青禾食品有限公司'
    p=history(name,filing(name,'公司于2019年成立。注册资本100万元，实缴资本100.01万元。'))
    text=render_history(p)
    assert '四舍五入误差' not in text and '无实质性出资瑕疵' not in text and '符合《公司法》' not in text
    assert '不能据此认定没有遗留问题' in text


def test_official_timeline_uses_adjacent_year_not_navigation():
    raw='- 2025\n- 2024\n• 发布甲产品\n\n2023\n\n• 发布乙产品\n\n2022\n• 停止旧产品生产'
    assert list(_heading_events(raw))==[('2023','发布乙产品'),('2022','停止旧产品生产')]


def test_collapsed_bullets_split_without_splitting_product_versions():
    raw='2022\n• 发布DM-i技术 • 发布CTB技术 • 第300万辆产品下线'
    assert list(_heading_events(raw))==[('2022','发布DM-i技术'),('2022','发布CTB技术'),('2022','第300万辆产品下线')]


def test_repeated_mobile_timeline_cannot_rebind_missing_years():
    raw='## 发展历程\n2005\n• 发布新产品\n## 发展历程\n2007\n• 发布新产品'
    assert list(_heading_events(raw))==[('2005','发布新产品')]


def test_navigation_before_first_prose_and_pdf_wraps_do_not_lose_ipo_date():
    name='星河精密股份有限公司'
    prelude=('工商资料无句号\n'*100)+'\n\n'
    raw=prelude+'本公司于2002年7月31日首次发行14,950万股，\n\n并在香港联交所上市。'
    p=history(name,filing(name,raw))
    assert any(r['period']=='2002-07-31' and '14,950万股' in r['fact'] for r in p['facts'])


def test_adjacent_ipo_issue_terms_not_lost_when_date_in_next_sentence():
    name='星河精密股份有限公司'
    p=history(name,filing(name,'公司首次向社会公众公开发行人民币普通股7,900万股，每股发行价格为人民币18.00元。经交易所同意，公司发行的A股股票于2011年6月30日在深圳证券交易所上市。'))
    text=render_history(p)
    assert '2011-06-30' in text and '18.00元' in text


def test_product_listing_not_capital_market_listing_and_praise_trimmed():
    name='星河精密股份有限公司'
    p=history(name,filing(name,'本集团于2025年5月发布新设备上市，充分体现了全球领先优势。'))
    event=next(r for r in p['facts'] if r['kind']=='event')
    assert event['event_type']=='业务动作' and '领先优势' not in event['fact']


def test_distinct_product_generations_not_false_date_conflicts():
    name='星河精密股份有限公司'
    f=filing(name,'网站：https://www.example-manufacturer.test\n公司于2021年发布DM-i技术。')
    c,s=evidence(name,'发展历程\n2024\n• 发布第五代DM技术',i=2,evidence_scope='industry_context')
    c['source_url']=s['url']='https://www.example-manufacturer.test/about'
    p=history(name,f,(c,s))
    assert p['time_conflicts']==[]


def test_timeline_selection_retains_precise_ipo_and_completed_cash_financing():
    name='星河精密股份有限公司'
    raw=('网站：https://www.example-manufacturer.test\n公司于2002年7月31日首次发行并在联交所上市。'
         '公司于2025年3月11日完成配售，所得净款43,383百万港元。'
         '公司于2025年7月完成资本公积转增。公司于2025年4月审议通过转增方案。'
         '公司于2024年5月完成回购注销。')
    c,s=evidence(name,'发展历程\n2002\n• 在证券交易所上市',i=2,evidence_scope='industry_context')
    c['source_url']=s['url']='https://www.example-manufacturer.test/about'
    p=history(name,filing(name,raw),(c,s));text=render_history(p)
    assert '2002-07-31' in text and '43,383百万港元' in text
    assert '回购注销' in text and '公司于2025年7月完成资本公积转增' in text


def test_official_domain_in_issuer_filing_authenticates_history_page_without_company_specific_domain():
    name='星河精密股份有限公司'
    f=filing(name,'网站：https://www.example-manufacturer.test\n公司于2019年成立。')
    c,s=evidence(name,'发展历程\n\n2022\n• 发布CTB技术\n\n2025\n• 发布新智能设备',i=2,evidence_scope='industry_context')
    c['source_url']=s['url']='https://www.example-manufacturer.test/about'
    p=history(name,f,(c,s))
    assert any(r.get('date_basis')=='year_heading' and r['period']=='2022' for r in p['facts'])


def test_conflicting_release_years_flagged_without_silently_choosing_one():
    name='星河精密股份有限公司'
    f=filing(name,'网站：https://www.example-manufacturer.test\n公司在2023年5月发布了CTB技术。')
    c,s=evidence(name,'发展历程\n2022\n• 发布CTB技术',i=2,evidence_scope='industry_context')
    c['source_url']=s['url']='https://www.example-manufacturer.test/about'
    p=history(name,f,(c,s));text=render_history(p)
    assert p['time_conflicts'][0]['periods']==['2022','2023']
    assert '来源时点差异待核验' in text and '2022／2023' in text


def test_changed_claim_and_unknown_citation_fail_history_check():
    name='青禾食品有限公司'
    p=history(name,filing(name,'公司于2019年成立。'))
    assert history_errors(render_history(p)+'\n公司已融资999万元。[E-FFFFFFFFFFFF]',p)


def test_history_evidence_budget_keeps_complete_records_and_empty_chapter_review_boundary():
    name='青禾食品有限公司'
    pairs=[filing(name,f'公司于20{i:02d}年5月完成产线投产。',i=i) for i in range(1,20)]
    p=history(name,*pairs,limit=6500)
    assert len(json.dumps(p,ensure_ascii=False))<=6500 and p['facts']
    empty=history(name)
    assert all('### '+h in render_history(empty) for h in HEADINGS)
    assert history_errors(render_history(empty),empty)


def test_checked_third_chapter_survives_batch_editor_and_is_not_padded(monkeypatch):
    name='青禾食品有限公司';pair=filing(name,'公司于2019年成立。')
    p=SimpleNamespace(target_name=name,title=name,target_type='company',industry='食品',description='',sources=[pair[1]])
    agent=CompanyReportAgent()
    monkeypatch.setattr(agent,'_write_section',lambda *a,**k:'')
    monkeypatch.setattr(agent,'_write_summary',lambda *a,**k:'## 1. 摘要\n摘要。')
    monkeypatch.setenv('COMPANY_REPORT_EDITOR_ENABLED','true')
    monkeypatch.setattr(agent,'_edit_batched',lambda *a,**k:'## 1. 摘要\n摘要。\n## 2. 工商\n待核验。\n## 3. 历史沿革与融资\n公司成长快速、无历史瑕疵。[E-FFFFFFFFFFFF]\n## 4. 治理\n待核验。')
    result=agent.generate(p,json.dumps({'facts':[pair[0]]}),'{}',lambda *a:'',lambda s,n:s[:n],lambda *a,**k:None)
    third=result.split('## 3.')[1].split('## 4.')[0]
    assert '历史沿革与成长质量' in third and '2019' in third and 'FFFFFFFFFFFF' not in third
    assert '本章引用证据' not in third and '无历史瑕疵' not in third
