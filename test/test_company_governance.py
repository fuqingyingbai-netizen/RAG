import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from report_agents.company_governance import (
    HEADINGS, build_governance_package, governance_errors,
    governance_graph_nodes, read_fields, render_governance,
)
from report_agents.company_report_agent import CompanyReportAgent


def evidence(target, content, *, i=1, tool='get_company_registration_info', meta=None, **changes):
    url=f'structured://fixture/{i}'
    source={'url':url,'title':target+'原始记录','content':content,'created_at':'2026-10-14 09:00:00',
            'source_metadata':{'tool':tool,'entity_validation':'verified','content_kind':'structured_data',**(meta or {})}}
    card={'evidence_id':f'E-{i:012X}','source_url':url,'source_title':source['title'],
          'company_name':target,'evidence_scope':'target_direct','eligible_for_report':True,
          'source_entity_validation':'verified','claim_type':'source_excerpt','fact':target+'登记信息。',**changes}
    return card,source


def package(target, *pairs, **kwargs):
    return build_governance_package({'facts':[p[0] for p in pairs]},target,[p[1] for p in pairs],**kwargs)


def table(target, body):
    return '| 字段 | 值 |\n| --- | --- |\n| 企业名称 | '+target+' |\n'+body


@pytest.mark.parametrize('name,legal,capital',[
    ('星河精密股份有限公司','赵一','35000万元'),
    ('青禾食品有限公司','钱二','100万美元'),
    ('Northstar Robotics Limited','Morgan Lee','EUR 1,000,000'),
])
def test_multiple_companies_keep_their_own_fields_currency_and_no_example_conclusions(name,legal,capital):
    raw=table(name,f'| 法定代表人 | {legal} |\n| 注册资本 | {capital} |\n| 成立日期 | 2019-03-02 |')
    p=package(name,evidence(name,raw))
    text=render_governance(p)
    assert name in text and legal in text and capital in text
    assert all('### '+h in text for h in HEADINGS)
    assert '比亚迪' not in text and '王传福' not in text
    assert '未发现重大公开矛盾' not in text and '具备较强稳定性基础' not in text
    assert governance_errors(text,p)==[]


def test_fields_read_from_reordered_headers_and_no_query_date_borrowed_as_data_date():
    name='星河精密股份有限公司'
    raw=table(name,'')+'\n\n| 持股数 | 股东名称 | 持股比例 |\n| --- | --- | --- |\n| 200 | 赵一 | 20% |'
    p=package(name,evidence(name,raw,tool='get_shareholder_info'))
    row=next(r for r in p['facts'] if r['kind']=='shareholder')
    assert row['entity']=='赵一' and row['ratio']=='20%'
    assert row['count']=='持股数：200'
    assert row['period']=='数据基准日未载' and row['observed_at']=='2026-10-14'


def test_source_insert_date_is_not_described_as_an_actual_acquisition_date():
    name='青禾食品有限公司';pair=evidence(name,table(name,'| 注册资本 | 100万元 |'))
    text=render_governance(package(name,pair))
    assert '本次入库日期2026-10-14' in text and '原始采集时间未单列' in text
    assert '采集于2026-10-14' not in text
    pair[1]['source_metadata']['retrieved_at']='2026-10-10T12:00:00+00:00'
    text=render_governance(package(name,pair))
    assert '原件采集记录日期2026-10-10' in text and '本次入库日期2026-10-14' not in text


def test_json_provider_keeps_explicit_subject_and_private_company_contributions():
    name='青禾食品有限公司'
    raw=json.dumps({'data':{'companyName':name,'regCapital':'100万美元','actualController':'钱二',
        'shareholders':[{'shareholderName':'钱二','stockPercent':'70%','认缴出资额（万美元）':'70'},
                        {'shareholderName':'青禾合伙企业（有限合伙）','stockPercent':'30%','认缴出资额（万美元）':'30'}]}},ensure_ascii=False)
    p=package(name,evidence(name,raw,tool='company_detail'))
    text=render_governance(p)
    assert '认缴出资额（万美元）：70' in text and '100万美元' in text
    assert any(r['kind']=='control' and r['value']=='钱二' for r in p['facts'])
    assert '控制关系的明确披露' in text


@pytest.mark.parametrize('validation,scope', [('rejected','target_direct'),('verified','related_entity_context'),('ambiguous','target_direct')])
def test_wrong_or_related_source_is_not_promoted_by_query_echo(validation,scope):
    name='星河精密股份有限公司'
    pair=evidence(name,table('星河精密零件有限公司','| 注册资本 | 999万元 |'),
                  meta={'entity_validation':validation},evidence_scope=scope)
    p=package(name,pair)
    assert p['facts']==[]
    assert governance_errors(render_governance(p),p)


def test_raw_entity_has_to_match_even_if_platform_metadata_is_verified():
    name='青禾食品有限公司'
    p=package(name,evidence(name,table('青禾餐饮有限公司','| 注册资本 | 999万元 |')))
    assert p['facts']==[]


def test_rejected_fact_cannot_be_reinstated_from_raw_source():
    name='青禾食品有限公司'
    p=package(name,evidence(name,table(name,'| 注册资本 | 999万元 |'),eligible_for_report=False))
    assert p['facts']==[]


def test_valid_registration_fields_survive_unrelated_operating_scope_exceptions():
    name='星河精密股份有限公司'
    raw=table(name,'| 注册资本 | 500万元 |\n| 经营范围 | 精密零件加工；不涉及许可证管理的商品进出口。 |')
    rejected,src=evidence(name,raw,eligible_for_report=False,evidence_scope='noise')
    atomic={**rejected,'eligible_for_report':True,'evidence_scope':'target_direct',
            'claim_type':'structured_field','fact':name+'注册资本500万元。'}
    p=build_governance_package({'facts':[rejected,atomic]},name,[src])
    assert any(r['field']=='注册资本' and r['value']=='500万元' for r in p['facts'])
    assert '不涉及许可证' in render_governance(p)


def test_distinct_nominees_kept_and_english_organization_not_dropped():
    name='星河精密股份有限公司'
    raw=table(name,'')+'\n\n| 股东名称 | 持股比例 | 持股数 |\n| --- | --- | --- |\n| HKSCC NOMINEES LIMITED | 40.38% | 100 |\n| 香港中央结算有限公司 | 1.86% | 10 |'
    p=package(name,evidence(name,raw,tool='get_shareholder_info'))
    nodes=governance_graph_nodes(p,'equity')
    assert {n[0] for n in nodes}=={'HKSCC NOMINEES LIMITED','香港中央结算有限公司'}
    assert not governance_graph_nodes(p,'control')
    assert not any('H股市场清算' in r['value'] or '无治理权' in r['value'] for r in p['facts'])


def test_unstated_percentage_scale_not_converted_and_no_forced_total_100():
    name='青禾食品有限公司'
    raw=json.dumps({'companyName':name,'shareholders':[{'shareholderName':'钱二','ratio':0.7}]},ensure_ascii=False)
    p=package(name,evidence(name,raw))
    row=next(r for r in p['facts'] if r['kind']=='shareholder')
    assert row['ratio']=='0.7（源字段未载百分比单位）'
    text=render_governance(p)
    assert '70%' not in text and '100%' not in text and '剩余30%' not in text


def test_source_percent_header_supplies_explicit_scale():
    name='星河精密股份有限公司'
    raw=table(name,'')+'\n\n| 股东名称 | 持股比例（%） |\n| --- | --- |\n| 赵一 | 70 |'
    p=package(name,evidence(name,raw))
    assert next(r for r in p['facts'] if r['kind']=='shareholder')['ratio']=='70%'


def test_historical_founder_table_never_becomes_current_shareholders():
    name='星河精密股份有限公司'
    raw=table(name,'')+'\n\n| 股东名称 | 持股比例 |\n| --- | --- |\n| 赵一 | 80% |'
    pair=evidence(name,raw,tool='historical_shareholders')
    pair[1]['title']=name+'设立时发起人结构'
    p=package(name,pair)
    assert not any(r['kind']=='shareholder' for r in p['facts'])
    assert any(r['kind']=='historical_shareholder' for r in p['facts'])
    assert any('当前股东' in gap for gap in p['information_gaps'])


@pytest.mark.parametrize('format',['markdown','json'])
def test_history_context_is_preserved_per_table_not_just_in_document_title(format):
    name='星河精密股份有限公司'
    if format=='markdown':
        raw=(table(name,'')+'\n\n### 设立时发起人\n\n| 股东名称 | 持股比例 |\n| --- | --- |\n| 赵一 | 80% |'
             '\n\n### 最新股东\n\n| 股东名称 | 持股比例 |\n| --- | --- |\n| 赵一 | 30% |')
    else:
        raw=json.dumps({'companyName':name,'historicalShareholders':[{'shareholderName':'赵一','StockPercent':'80%'}],
                        'shareholders':[{'shareholderName':'赵一','StockPercent':'30%'}]},ensure_ascii=False)
    p=package(name,evidence(name,raw))
    assert [r['ratio'] for r in p['facts'] if r['kind']=='shareholder']==['30%']
    assert [r['ratio'] for r in p['facts'] if r['kind']=='historical_shareholder']==['80%']


def test_capital_reduction_event_is_distinct_from_generic_permission_in_charter():
    name='星河精密股份有限公司'
    raw=table(name,'| 注册资本 | 500万元 |')+'\n\n| 变更日期 | 变更事项 | 变更前 | 变更后 |\n| --- | --- | --- | --- |\n| 2025-05-01 | 注册资本减资 | 1000万元 | 500万元 |'
    p=package(name,evidence(name,raw,tool='company_changes'))
    event=next(r for r in p['facts'] if r['kind']=='history')
    assert event['period']=='2025-05-01' and '1000万元 → 500万元' in event['value']
    assert not any('逐项事件' in x for x in p['information_gaps'])
    raw2='星河精密股份有限公司章程：公司可以减少其注册资本。'
    c,s=evidence(name,raw2,i=2,claim_type='fact',fact='公司可以减少其注册资本。',evidence_quote='公司可以减少其注册资本。')
    s['url']=c['source_url']='https://filing.test/charter'
    p2=package(name,(c,s))
    assert not any(r['kind']=='history' for r in p2['facts'])


def test_restructuring_event_separate_from_registered_founding_date():
    name='星河精密股份有限公司'
    registry=evidence(name,table(name,'| 成立日期 | 1995-02-10 |'))
    text=name+'于2002年6月11日整体改制设立。'
    c,s=evidence(name,text,i=2,claim_type='fact',fact=text,evidence_quote=text,date='2002-06-11')
    s['url']=c['source_url']='https://filing.test/charter'
    p=package(name,registry,(c,s))
    assert any(r['field']=='成立日期' and r['value']=='1995-02-10' for r in p['facts'])
    assert any(r['kind']=='history' and r['period']=='2002-06-11' for r in p['facts'])
    assert '成立时间存在两个口径' not in render_governance(p)


def test_field_boundary_prevents_fake_legal_representative_conflict():
    name='青禾食品有限公司'
    fields,_=read_fields('企业名称：'+name+'\n法定代表人：钱二注册资本：100万美元 成立日期：2020-01-01')
    assert fields['法定代表人']=='钱二' and fields['注册资本']=='100万美元'


def test_conflicting_registration_values_preserved_and_cited_not_silently_overwritten():
    name='青禾食品有限公司'
    a=evidence(name,table(name,'| 注册资本 | 100万元 |'),i=1)
    b=evidence(name,table(name,'| 注册资本 | 200万元 |'),i=2)
    p=package(name,a,b)
    assert p['conflicts'][0]['values']==['100万元','200万元']
    text=render_governance(p)
    assert '不同来源值' in text and '[E-000000000001]' in text and '[E-000000000002]' in text


def test_missing_and_zero_are_distinct_and_no_hit_is_not_a_clean_bill():
    name='青禾食品有限公司'
    p=package(name,evidence(name,table(name,'| 实缴资本 | 0万元 |\n| 参保人数 | 0 |\n| 注册资本 | 待查 |')))
    text=render_governance(p)
    assert '0万元' in text and not any(r['field']=='注册资本' for r in p['facts'])
    assert '治理稳定' not in text and '无重大风险' not in text


def test_shareholding_and_employment_overlap_does_not_prove_control():
    name='青禾食品有限公司'
    raw=table(name,'| 法定代表人 | 钱二 |')+'\n\n| 股东名称 | 持股比例 |\n| --- | --- |\n| 钱二 | 40% |\n\n| 职务 | 姓名 | 本届任期 |\n| --- | --- | --- |\n| 董事长,总经理 | 钱二 | 2024-01-01 至今 |'
    p=package(name,evidence(name,raw))
    text=render_governance(p)
    assert '持股与任职的交集' in text
    assert '自2024年起担任法定代表人' not in text
    assert not any(n[1]=='实际控制人' for n in governance_graph_nodes(p,'relationship'))


def test_duplicate_snapshot_removed_but_distinct_dates_remain():
    name='青禾食品有限公司'
    a=evidence(name,table(name,'| 注册资本 | 100万元 |'),i=1)
    b=evidence(name,table(name,'| 注册资本 | 100万元 |'),i=2)
    p=package(name,a,b)
    caps=[r for r in p['facts'] if r['field']=='注册资本']
    assert len(caps)==1 and len(caps[0]['evidence_ids'])==2
    a[1]['source_metadata']['as_of_date']='2025-01-01'
    b[1]['source_metadata']['as_of_date']='2026-01-01'
    p=package(name,a,b)
    assert len([r for r in p['facts'] if r['field']=='注册资本'])==2
    assert not p['conflicts']


def test_empty_chapter_retains_template_and_editor_cannot_replace_checked_chapter(monkeypatch):
    name='青禾食品有限公司'
    pair=evidence(name,table(name,'| 注册资本 | 100万元 |'))
    p=SimpleNamespace(target_name=name,title=name,target_type='company',industry='食品',description='',sources=[pair[1]])
    agent=CompanyReportAgent()
    monkeypatch.setattr(agent,'_write_section',lambda *a,**k:'')
    monkeypatch.setattr(agent,'_write_summary',lambda *a,**k:'## 1. 摘要\n第一章。')
    monkeypatch.setenv('COMPANY_REPORT_EDITOR_ENABLED','true')
    monkeypatch.setattr(agent,'_edit_batched',lambda *a,**k:'## 1. 摘要\n摘要\n## 2. 错误标题\n公司股东关系无冲突。[E-FFFFFFFFFFFF]\n## 3. 历史沿革与融资\n历史。')
    text=agent.generate(p,json.dumps({'facts':[pair[0]]}),'{}',lambda *a:'',lambda s,n:s[:n],lambda *a,**k:None)
    chapter=text.split('## 2.')[1].split('## 3.')[0]
    assert '100万元' in chapter and '公司股东关系无冲突' not in chapter
    assert '本章引用证据' not in chapter
    assert '工商变更档案' in text.split('## 14.')[1]


def test_unknown_rewritten_or_injected_claim_is_detected():
    name='青禾食品有限公司'
    p=package(name,evidence(name,table(name,'| 注册资本 | 100万元 |')))
    text=render_governance(p)
    assert governance_errors(text+'\n钱二持股90%。[E-FFFFFFFFFFFF]',p)
    assert governance_errors(text.replace('100万元','999万元'),p)


def test_company_searches_cover_event_history_control_and_capital_reduction():
    from research_strategies import get_research_strategy
    for name in ('青禾食品有限公司','星河精密股份有限公司','Northstar Robotics Limited'):
        rows=get_research_strategy('company').expand_search_queries({'modules':[]},{'target_name':name})
        queries=[r['query'] for r in rows if '主体工商' in r['module']]
        assert any('减资公告' in q and name in q for q in queries)
        assert any('变更日期' in q and name in q for q in queries)
        assert any('表决权' in q and name in q for q in queries)
        assert any('gsxt.gov.cn' in r.get('include_domains',[]) for r in rows)


def test_graph_uses_checked_company_package_without_raw_fallback(monkeypatch):
    from research_workflow import ResearchWorkflow
    import research_workflow as rw
    name='青禾食品有限公司'
    pair=evidence(name,table(name,'')+'\n\n| 股东名称 | 持股比例 |\n| --- | --- |\n| ACME LIMITED | 60% |')
    p=SimpleNamespace(id=99,target_name=name,title=name,target_type='company',sources=[SimpleNamespace(**pair[1])],
                      company_governance_package=package(name,pair))
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    monkeypatch.setattr(w,'_professional_graph_nodes',lambda *a:pytest.fail('must not re-read raw sources'))
    monkeypatch.setattr(w,'_cleaned_fact_graph_nodes',lambda *a:pytest.fail('must not add unchecked nodes'))
    svgs=[]
    monkeypatch.setattr(rw.research_store,'put_bytes',lambda key,blob,mime:svgs.append(blob.decode()))
    assert w._build_relationship_graph_svg(p,'{}',graph_kind='equity')
    assert 'ACME LIMITED' in svgs[0] and '企业/机构' in svgs[0]
    p.company_governance_package={'target_name':name,'facts':[]}
    assert w._build_relationship_graph_svg(p,'{}',graph_kind='equity')==''


def test_issuer_disclosure_recovers_late_control_even_when_page_was_classified_as_industry():
    name='星河精密股份有限公司'
    raw=name+'2025年年度报告。'+'行业出口资料。'*1200+'主要职业及职务公司控股股东和实际控制人为赵一先生，为公司董事长。'
    c,s=evidence(name,raw,evidence_scope='industry_context')
    c['source_url']=s['url']='https://www.hkexnews.hk/listedco/2025.pdf'
    c['source_title']=s['title']='COMPANY LIMITED'
    p=package(name,(c,s))
    r=next(r for r in p['facts'] if r['kind']=='control')
    assert r['entity']=='赵一' and r['period']=='2025年年度报告'
    assert governance_graph_nodes(p,'control')[0][1]=='披露实际控制人'
    assert not any('明确的控制关系' in gap for gap in p['information_gaps'])


def test_subsidiary_statement_and_generic_charter_rules_never_create_control_edges():
    name='星河精密股份有限公司'
    raw=name+'2025年年度报告。子公司实际控制人为钱二先生。公司的实际控制人应当依法行使权利。'
    c,s=evidence(name,raw)
    c['source_url']=s['url']='https://static.cninfo.com.cn/2025.pdf'
    p=package(name,(c,s))
    assert not any(r['kind']=='control' for r in p['facts'])


@pytest.mark.parametrize('claim',['公司无实际控制人。','公司无控股股东及实际控制人。'])
def test_explicit_no_controller_disclosure_is_not_invented_as_a_person(claim):
    name='星河精密股份有限公司'
    c,s=evidence(name,name+'2025年年度报告。'+claim)
    c['source_url']=s['url']='https://static.cninfo.com.cn/2025.pdf'
    p=package(name,(c,s))
    assert any(r['kind']=='control' and r['value']==claim for r in p['facts'])
    assert not governance_graph_nodes(p,'control')


def test_capital_reduction_completion_date_not_announcement_date():
    name='星河精密股份有限公司'
    raw=(name+'2025年年度报告。公司2024年回购股份的方案于2024年4月26日实施完成，相关股份于2024年5月10日完成注销。'
         '详情请见公司2024年5月14日披露的《关于股份注销完成的公告》（公告编号：2024-056）。')
    c,s=evidence(name,raw)
    c['source_url']=s['url']='https://disc.static.szse.cn/2025.pdf'
    p=package(name,(c,s))
    events=[r for r in p['facts'] if r['kind']=='history']
    assert len(events)==1 and events[0]['period']=='2024-05-10'


def test_uncompleted_capital_reduction_is_not_reported_as_completed_event():
    name='星河精密股份有限公司'
    raw=name+'2025年年度报告。公司2024年股份回购注销尚未完成，减少注册资本事项将于后续办理。'
    c,s=evidence(name,raw)
    c['source_url']=s['url']='https://disc.static.szse.cn/2025.pdf'
    assert not any(r['kind']=='history' for r in package(name,(c,s))['facts'])


def test_recovered_issuer_claim_is_preserved_in_source_index():
    from research_workflow import ResearchWorkflow
    name='星河精密股份有限公司'
    raw=name+'2025年年度报告。公司实际控制人为赵一先生，为公司董事长。'
    c,s=evidence(name,raw,evidence_scope='industry_context')
    c['source_url']=s['url']='https://static.cninfo.com.cn/2025.pdf'
    p=SimpleNamespace(target_name=name,target_type='company',company_governance_package=package(name,(c,s)))
    text=render_governance(p.company_governance_package)+'\n\n## 13. 信息来源\n\n## 14. 后续研究建议\n待核验。'
    result=ResearchWorkflow.__new__(ResearchWorkflow)._append_company_claim_evidence_index(
        p,text,[c],total_traceable_sources=1,eligible_company_sources=0)
    index=result.split('## 13.')[1]
    assert '第二章原文核对' in index and '实际控制人为赵一先生' in index
    assert '第 2 章' in index


def test_package_budget_preserves_whole_records_and_identity_only_is_review_draft():
    name='青禾食品有限公司'
    pairs=[evidence(name,table(name,'| 注册资本 | '+str(i)+'万元 |'),i=i) for i in range(1,20)]
    p=package(name,*pairs,limit=7500)
    assert len(json.dumps(p,ensure_ascii=False))<=7500
    assert json.loads(json.dumps(p))['facts']
    empty=package(name,evidence(name,table(name,'')))
    assert governance_errors(render_governance(empty),empty)


def test_explicit_acquisition_provenance_does_not_displace_a_full_personnel_table():
    name='青禾食品有限公司'
    body=table(name,'')+'\n\n| 姓名 | 职务 | 任期 |\n| --- | --- | --- |\n'
    body+='\n'.join(f'| 员工{i} | 副总裁 | 2025-01-01 至今 |' for i in range(80))
    card,src=evidence(name,body,meta={'retrieved_at':'2026-10-20T10:00:00'})
    src['url']=card['source_url']='structured://neutral-platform/management/'+name+'/independent-original-record'
    src['title']=card['source_title']=name+'主要人员及董事会任职情况原始字段'
    p=package(name,(card,src))
    people=[r for r in p['facts'] if r['kind']=='personnel']
    assert {r['entity'] for r in people}=={f'员工{i}' for i in range(80)}
    assert all(r['observed_at']=='2026-10-20' and r['observed_at_basis']=='retrieved_at' for r in people)
    assert not p['diagnostic']['filters'].get('budget_excluded')
