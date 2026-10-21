from report_agents.company_press_releases import press_financing_rows
from report_agents.company_issuer_identity import build_issuer_identity
from report_agents.company_diligence import build_diligence_package,render_diligence
from test_company_issuer_identity import TARGET,LEGAL,filing,page


def release():
    return page('青禾集团完成新股份配售\n\n2026年8月26日\n\n'
        'Hong Kong, China, August 26, 2026 — '+LEGAL+' (NYSE: BLUE and HKEX: 1234, the “Company”) today announced the completion of its HK$20 billion placing of 500,000,000 newly issued ordinary shares of the Company, at a placing price of HK$40.00 per Placement Share.\n\n'
        'The Company intends to utilize the net proceeds to invest as follows: approximately 60%, or HK$11,940 million, will be used for infrastructure; approximately 40%, or HK$7,960 million, will be used for research.')


def base(s):return {'source_url':s['url'],'source_title':s['title'],'evidence_id':'E-000000000001','evidence_ids':['E-000000000001']}


def test_completed_gross_shares_price_and_intended_use_are_distinct_without_calculated_net_or_payment():
    s=release();ctx=build_issuer_identity([filing(),s],TARGET)
    rows=press_financing_rows(s,TARGET,base(s),ctx,as_of='2026-10-20')
    assert len(rows)==2 and rows[0]['gross_proceeds_text']=='HK$20 billion'
    assert rows[0]['shares_text']=='500,000,000' and rows[0]['placing_price_text']=='HK$40.00'
    assert rows[0]['net_proceeds_text']==''
    assert rows[1]['kind']=='financing_use_plan' and '非实际支出' in rows[1]['mode']
    assert all(r['fact'] in s['content'] for r in rows)
    assert not press_financing_rows(s,TARGET,base(s),ctx,as_of='2026-08-20')
    c=base(s)
    p=build_diligence_package({'facts':[c]},TARGET,[filing(),s],intake={'as_of_date':'2026-10-20'})
    assert {'financing','financing_use_plan'}=={r['kind'] for r in p['facts']}
    assert 'HK$20 billion' in render_diligence(p)
    c['eligible_for_report']=False
    assert not build_diligence_package({'facts':[c]},TARGET,[filing(),s])['facts']


def test_plan_pricing_and_mismatched_dateline_do_not_become_completed_funding():
    s=release();ctx=build_issuer_identity([filing(),s],TARGET)
    s['content']=s['content'].replace('today announced the completion of','today announced the proposed pricing of')
    assert not press_financing_rows(s,TARGET,base(s),ctx)
    s=release();s['content']=s['content'].replace('August 26, 2026','August 27, 2026')
    assert not press_financing_rows(s,TARGET,base(s),ctx)


def test_subsidiary_press_statement_does_not_inherit_parent_funding():
    s=release();ctx=build_issuer_identity([filing(),s],TARGET)
    s['content']=s['content'].replace(LEGAL,'Blue River Trading Limited')
    assert not press_financing_rows(s,TARGET,base(s),ctx)


def test_copyright_footer_does_not_hide_the_bilingual_legal_action_binding():
    s=release();s['content']+='\n\n版权公告 © 2026 '+TARGET+'及／或其关联公司。'
    ctx=build_issuer_identity([filing(),s],TARGET)
    rows=press_financing_rows(s,TARGET,base(s),ctx,as_of='2026-10-20')
    assert len(rows)==2 and rows[0]['gross_proceeds_text']=='HK$20 billion'
