"""Neutral regressions for issues first exposed by actual cross-company runs."""
from collections import Counter
from types import SimpleNamespace

from report_agents.company_summary import build_company_summary_package,_structured_claims
from report_agents.company_history import non_issuer_event_context
from report_agents.company_governance import build_governance_package
from report_agents.company_judicial import _structured
from report_agents.company_diligence import build_diligence_package
from research_workflow import ResearchWorkflow

TARGET='青禾模型技术有限公司'


def test_market_roundup_does_not_supply_another_issuers_profit_to_company_summary():
    url='https://example.test/market-roundup'
    raw='上市公司资讯汇总\n\n2025年2月6日，远山股份公告，营业收入12亿元，净利润2亿元。\n\n'+TARGET+'发布技术模型。'
    fact={'evidence_id':'E-000000000001','source_url':url,'source_title':TARGET+'相关资讯',
          'fact':TARGET+'相关资讯及营业收入12亿元。','evidence_quote':raw,'claim_type':'source_excerpt',
          'eligible_for_report':True,'evidence_scope':'target_direct'}
    source={'url':url,'title':fact['source_title'],'content':raw,'source_metadata':{}}
    p=build_company_summary_package({'facts':[fact]},TARGET,[source])
    assert not any(r['summary_topic']=='financial' for r in p['facts'])
    assert all('远山股份' not in r['fact'] for r in p['facts'])


def test_contribution_amount_and_share_count_keep_their_native_headers_when_reordered():
    raw='| 认缴出资额（万元） | 股东名称 | 持股比例 |\n| --- | --- | --- |\n| 500 | 赵甲 | 60% |'
    text=_structured_claims(raw,'get_shareholder_info',TARGET)[0][0]
    assert '认缴出资额（万元）：500' in text and '500股' not in text and '持股数' not in text


def test_reference_list_dates_are_not_events_in_company_history():
    assert non_issuer_event_context('2024年 '+TARGET+'．登记平台 ［引用日期2025-01-01］；模型发布．新闻平台 ［引用日期2025-02-01］')


def test_duplicate_currency_suffix_is_not_admitted_as_a_capital_amount():
    url='structured://fixture/registry'
    source={'url':url,'title':TARGET,'content':'| 企业名称 | '+TARGET+' |\n| 注册资本 | 1000万人民币万元人民币 |',
            'source_metadata':{'tool':'get_company_registration_info','entity_validation':'verified'}}
    f={'evidence_id':'E-000000000001','source_url':url,'fact':TARGET+'登记记录。','evidence_scope':'target_direct',
       'eligible_for_report':True,'source_entity_validation':'verified','claim_type':'source_excerpt'}
    p=build_governance_package({'facts':[f]},TARGET,[source])
    assert not any(r.get('field')=='注册资本' for r in p['facts'])


def test_native_decision_row_survives_multiline_reasoning_breaking_the_table():
    raw='| 字段 | 值 |\n| --- | --- |\n| 企业名称 | '+TARGET+' |\n| 案号 | （2025）青0101民初123号 |\n| 本院认为 | 很长的裁判说理\n下一段不是表格行。 |\n| 判决结果 | 驳回原告的诉讼请求。案件受理费由原告承担。 |\n| 当事人原文 | 原告某甲，被告某公司。 |\n\n### 被告\n- 某公司（'+TARGET+'）'
    rows=_structured(raw,'get_judicial_document_detail',TARGET,{'evidence_id':'E-000000000001'},Counter())
    assert len(rows)==1 and '驳回原告的诉讼请求' in rows[0]['fact']
    assert '| 判决结果 |' in rows[0]['evidence_quote'] and '数据库映射' in rows[0]['mode']


def test_target_in_another_issuers_placement_list_is_an_investor_not_a_funded_issuer():
    base={'kind':'event','period':'2026-08-06','source_url':'https://example.test/placement',
          'evidence_id':'E-000000000001','evidence_ids':['E-000000000001'],'evidence_scope':'target_direct',
          'fact':'2026年8月6日，远山股份披露战略配售名单，'+TARGET+'作为“与发行人经营业务具有战略合作关系的大型企业”入围。'}
    p=build_diligence_package({'facts':[]},TARGET,[],prior_packages={'history':{'facts':[base]}})
    assert any(r['kind']=='investment_candidacy' and r['stream']=='战略布局' for r in p['facts'])
    assert not any(r['kind']=='financing' for r in p['facts'])
    own={**base,'fact':TARGET+'于2026年8月6日完成配售股份，募集净额10亿元。'}
    p=build_diligence_package({'facts':[]},TARGET,[],prior_packages={'history':{'facts':[own]}})
    assert any(r['kind']=='financing' for r in p['facts'])


def test_report_index_keeps_original_trailing_slashes_and_distinct_path_locators():
    urls=['https://example.test/news/','https://example.test/news']
    facts=[{'evidence_id':f'E-{i:012X}','source_url':url,'source_title':'企业原件',
            'fact':TARGET+'原文记录。','evidence_scope':'target_direct'} for i,url in enumerate(urls,1)]
    project=SimpleNamespace(target_name=TARGET,target_type='company',sources=[])
    text='## 1. 摘要\n原文记录[E-000000000001][E-000000000002]\n\n## 13. 信息来源\n\n## 14. 后续研究建议'
    result=ResearchWorkflow.__new__(ResearchWorkflow)._append_company_claim_evidence_index(project,text,facts,
                                        total_traceable_sources=2,eligible_company_sources=2)
    assert '原始链接 → https://example.test/news/ |' in result
    assert '原始链接 → https://example.test/news |' in result
    assert '唯一来源：2 /' in result


def test_partnership_shareholders_are_rendered_as_organizations_not_natural_persons(monkeypatch):
    import research_workflow as rw
    svgs=[]
    monkeypatch.setattr(rw.research_store,'put_bytes',lambda key,blob,mime:svgs.append(blob.decode()))
    for name in ['青禾咨询合伙企业（有限合伙）','Blue River LLP']:
        project=SimpleNamespace(id=1,target_name=TARGET,title=TARGET,target_type='company',sources=[],
            company_governance_package={'target_name':TARGET,'facts':[{'kind':'shareholder','entity':name,'ratio':'60%','period':''}]})
        assert ResearchWorkflow.__new__(ResearchWorkflow)._build_relationship_graph_svg(project,'{}',graph_kind='equity')
        assert '企业/机构' in svgs[-1] and '自然人' not in svgs[-1]


def test_navigation_date_and_conditional_equity_policy_are_not_company_events():
    assert non_issuer_event_context('2026年10月21日星期三本版第1版：要闻。2021年4月10日'+TARGET+'受到行政处罚。')
    assert non_issuer_event_context('截至2026年3月31日，本公司员工都可能被授予自本公司成立以来实施的股权激励计划。')
    assert non_issuer_event_context(TARGET+'于1999年成立，现任董事局主席兼首席执行官王甲。')
    assert non_issuer_event_context(TARGET+'于1999年成立，时任董事局主席兼首席执行官为王甲。')


def test_unverified_web_registry_and_old_current_role_are_not_summary_identity():
    from report_agents.company_summary import build_company_summary_package
    sources=[];facts=[]
    for i,text in enumerate(['法定代表人：王甲。','当事人：'+TARGET+'，现任董事局主席兼首席执行官王乙，业务包括网络服务。'],1):
        url='https://example.test/'+str(i)
        sources.append({'url':url,'title':TARGET,'content':text})
        facts.append({'evidence_id':f'E-{i:012X}','source_url':url,'source_title':TARGET,'fact':TARGET+text,
                      'evidence_quote':text,'evidence_scope':'target_direct','entity_match':'exact','claim_type':'fact'})
    result=build_company_summary_package({'facts':facts},TARGET,sources)
    assert not any('法定代表人' in r['fact'] or '现任董事局主席' in r['fact'] for r in result['facts'])


def test_official_overseas_identity_and_roster_remain_disclosed_not_current_registry():
    from report_agents.company_summary import _chapter_summary_cards
    base={'evidence_id':'E-000000000001','source_url':'https://www.hkexnews.hk/annual.pdf','period':'2026财年年度报告'}
    packages={'governance':{'target_name':TARGET,'facts':[{**base,'kind':'registry','basis':'official_overseas_filing','field':'注册司法辖区','value':'某境外司法辖区'}]},
              'management':{'facts':[{**base,'kind':'role','roster_format':'simple_annual','document_period_end':'2026-03-31','entity':'王甲','source_role':'主席'}]}}
    rows=_chapter_summary_cards(packages)
    assert len(rows)==2 and '非独立工商核验' in rows[0]['fact'] and '不认定截至研究日仍在任' in rows[1]['fact']


def test_unused_tax_expiry_and_conditional_ipo_are_not_payment_or_completed_funding():
    from report_agents.company_diligence import classify_quote,disclosure_rows
    assert classify_quote('截至2027年至2031年3月31日止年度到期（如未使用）。') is None
    assert classify_quote('如果远山集团未能于指定时间内完成合格首次公开发行，此等权利将不会终止。') is None
    assert classify_quote('我们不时进行企业合并，并在完成时进行收购对价分摊。') is None
    assert classify_quote('根据2020年修订，于远山集团合格首次公开发行完成后，我们参与其首次公开发行的权利将告终止。') is None
    assert classify_quote('上述董事提名权仅在新股增发完成后我们持有的远山集团股权降低至一定数量或其合格首次公开发行完成时失效。') is None
    rows=disclosure_rows({},[{'page':1,'text':'• 远山集团或支付平台完成合格首次公开发行；'}],{'entity':TARGET})
    assert not rows
    assert classify_quote('截至2026年3月31日，本集团尚未使用的配售所得款项为人民币100万元。')[0]=='payment_pending'


def test_conditional_employee_penalty_risk_is_not_a_culture_practice():
    from report_agents.company_people import policy_rows
    text='若未遵守有关我们或子公司的员工股权激励计划法规，可能使我们或境内参与人被处以罚款及其他法律或行政处罚。我们可能增加注册资本。'
    assert policy_rows([{'page':1,'text':text}],'2026年',TARGET)==[]
    assert policy_rows([{'page':2,'text':'我们不会为其提供任何额外薪酬，但原件前文提及对象未包含于本句中。'}],'2026年',TARGET)==[]


def test_web_event_is_not_described_as_a_professional_platform_return():
    from report_agents.company_summary import fallback_company_summary
    f={'evidence_id':'E-000000000001','fact':TARGET+'于2021年收到行政处罚决定。','summary_topic':'risk',
       'source_kind':'other','source_url':'https://example.test/old-penalty','period':'2021-04-10'}
    text=fallback_company_summary(SimpleNamespace(target_name=TARGET),{'facts':[f]})
    assert '平台返回记录' not in text and '历史日期及后续处理仍需核验' in text
    f['source_url']='structured://fixture/risk'
    assert '平台返回记录' in fallback_company_summary(SimpleNamespace(target_name=TARGET),{'facts':[f]})


def test_completed_placement_share_counts_survive_without_conditional_rights():
    from report_agents.company_diligence import classify_quote,disclosure_rows
    q='配售完成后，本公司的已发行股份总数由100股增加至120股，A股数目维持不变。'
    assert classify_quote(q)[0]=='financing'
    q='注5：2025年3月11日公司完成配售20股新H股，叠加报告期内权益分派影响，名义持股随之增加。'
    rows=disclosure_rows({},[{'page':1,'text':q}],{'entity':TARGET})
    assert len(rows)==1 and rows[0]['kind']=='financing'


def test_promotional_investor_recognition_does_not_replace_financing_amount_rows():
    from report_agents.company_diligence import classify_quote
    assert classify_quote('本集团完成规模达10亿美元的配售，全球顶级投资者参与，充分体现投资人坚定看好。') is None
    assert classify_quote('我们完成10亿美元配售，这份认可代表对未来的期许。') is None
