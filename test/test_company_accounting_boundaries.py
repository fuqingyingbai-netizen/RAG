from report_agents.company_evidence import annotate_page_notes
from report_agents.company_history import _date, _event_status, build_history_package
from report_agents.company_diligence import classify_quote, display_diligence_fact
from test_company_history import filing, history


def test_same_page_agenda_number_never_changes_calendar_or_quantity():
    quote='公司于2025年6月12日召开会议，调整6人获授数量。'
    page={'page':1,'text':quote+'\n6 本议案详细说明如下并附授予名单。'}
    assert annotate_page_notes(quote,[page])==quote


def test_board_action_date_wins_over_performance_year():
    quote='公司于2025年4月29日召开董事会，审议通过回购注销议案，同意因2024年度个人业绩考核不达标等原因对已获授但尚未解除限售的股份进行回购注销。'
    assert _date(quote)=='2025-04-29'
    assert _event_status(quote)=='已决议／执行待核验'


def test_dividend_proposal_not_completed_payment():
    assert _event_status('董事会于2026年3月30日提议以总股本为基数向普通股股东派发现金股利。')=='计划／拟议'


def test_employee_scheme_year_is_not_the_application_date():
    assert _date('公司向登记公司提交注销2021年限制性股票尚未解除限售股份的申请。')==''
    assert _date('2025年度，本集团合计回购库存股，授予员工持股计划。')=='2025'
    assert _event_status('2025年度，本集团合计回购库存股并授予员工持股计划。')=='原文记载已发生'


def test_note_header_and_balance_dates_do_not_override_following_actual_action():
    name='青禾制造股份有限公司'
    raw='2025年度财务报表附注库存股2024年12月31日本年增加本年减少2023年12月31日，2025年度，本集团合计回购库存股人民币100万元，在2025年度授予员工持股计划。'
    p=history(name,filing(name,raw))
    event=next(r for r in p['facts'] if r['kind']=='event')
    assert event['period']=='2025' and event['status']=='原文记载已发生'
    assert '财务报表附注' not in event['fact']
    rule='本集团按照公开发行证券公司信息披露编报规则（2010年修订）编制，本公司为在交易所上市的H股公司。'
    assert not any(r['kind']=='event' for r in history(name,filing(name,rule))['facts'])


def test_accounting_standard_and_instrument_definitions_do_not_become_history():
    name='青禾制造股份有限公司'
    standard='本公司的财务报表按照财政部于2006年2月15日发布的企业会计准则编制。'
    instrument='本集团持有的债务工具是指从发行方角度分析符合金融负债定义的工具，2025年以收取合同现金流量为目标。'
    p=history(name,filing(name,standard+instrument+'公司于2025年7月2日完成新产线投产。'))
    events=[r for r in p['facts'] if r['kind']=='event']
    assert events and all('会计准则' not in r['fact'] and '债务工具是指' not in r['fact'] for r in events)
    assert any(r['period']=='2025-07-02' for r in events)


def test_measurement_definitions_are_not_actual_funding_or_consolidation():
    assert classify_quote('本集团持有的债务工具是指从发行方角度分析符合金融负债定义的工具。') is None
    assert classify_quote('交易性金融负债为纳入合并范围内结构化主体中归属于第三方的权益，计量模式为指定以公允价值计量且其变动计入当期损益。') is None
    assert classify_quote('本集团于2025年取得股东贷款人民币100,000,000元。')[0]=='related_funding'


def test_impairment_test_assumptions_not_labelled_proforma_cash():
    quote='商誉账面价值为人民币300,000千元，审计师测试商誉减值模型所用关键假设及审批控制。'
    assert classify_quote(quote)[0]=='purchase_accounting'
    assert classify_quote('备考假设本次收购于期初已完成，支付现金人民币100万元。')[0]=='pro_forma'


def test_control_date_accounting_policy_not_actual_consolidation():
    assert classify_quote('从取得子公司的实际控制权之日起，本集团开始将其纳入合并范围；') is None
    assert classify_quote('公司于2025年4月完成收购，将青禾元件公司纳入合并范围。')[0]=='closing'


def test_short_closing_reference_does_not_invent_or_merge_acquisition_targets():
    record={'kind':'closing','fact':'于2025年12月，本集团完成了该项收购。','page':400}
    assert '本句未单列收购标的' in display_diligence_fact(record)
    assert record['fact']=='于2025年12月，本集团完成了该项收购。'


def test_integer_original_financial_table_is_available_to_history():
    name='青禾制造股份有限公司'
    c,s=filing(name,'')
    raw='主要会计数据\n2025年 2024年 本年比上年增减 2023年\n营业收入（千元） 120,000 100,000 20.00% 90,000\n归属于上市公司股东的净利润（千元） 8,000 10,000 -20.00% 9,000\n经营活动产生的现金流量净额（千元） 6,000 12,000 -50.00% 8,000'
    s['source_metadata']['document_pages']=[{'page':1,'text':name+'\n2025年年度报告'}, {'page':10,'text':raw}, {'page':40,'text':'合并资产负债表\n2025年12月31日\n编制单位：'+name}]
    s['content']=name+'2025年年度报告。\n'+raw
    p=build_history_package({'facts':[c]},name,[s])
    rows=[r for r in p['facts'] if r['kind']=='performance']
    assert len(rows)==3 and all(r['unit']=='千元' and r['page']==10 for r in rows)
    assert not any('成长质量尚缺同口径' in g for g in p['information_gaps'])
