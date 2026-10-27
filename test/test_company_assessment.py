import json
from collections import defaultdict
from copy import deepcopy
from types import SimpleNamespace

import pytest

from report_agents.company_assessment import (
    RUBRIC, METRICS, _financial_scores, aggregate_scores, assessment_errors,
    build_assessment_package, capital_status_observations, control_score,
    execution_score, financial_observations, funding_score,
    internal_control_observations, outcome_observations, render_assessment,
    score_row, filing_cutoff,
)
from report_agents.company_risk_register import source_anchor

ROOT = '青禾制造股份有限公司'
CHILD = '青禾元件股份有限公司'


def src(year=2025, half=False, integers=False, amounts=None, extra=None, index=1, owner=ROOT):
    period = str(year) + ('年半年度报告' if half else '年年度报告')
    date = str(year) + ('年6月30日' if half else '年12月31日')
    pairs = amounts or [(120,100,90),(12,10,9),(24,20,18)]
    def number(v):return str(v) if integers else f'{v:.2f}'
    header = '本报告期 上年同期 本报告期比上年同期增减' if half else f'{year}年 {year-1}年 本年比上年增减 {year-2}年'
    lines = []
    for name,(a,b,c) in zip(METRICS,pairs):
        yoy=(a/b-1)*100 if b else 0
        lines.append(name+'（千元） '+number(a)+' '+number(b)+f' {yoy:.2f}%'+(' '+number(c) if not half else ''))
    pages=[{'page':1,'text':owner+'\n'+period},
           {'page':9,'text':'六、主要会计数据和财务指标\n'+header+'\n'+'\n'.join(lines)},
           {'page':40,'text':'合并资产负债表\n'+date+'\n编制单位：'+owner+'\n单位：人民币元'}]+(extra or [])
    url=f'https://www.hkexnews.hk/reports/{year}/r{index}.pdf'
    s={'title':owner+period,'url':url,'content':'\n\n'.join(f"--- PDF page {p['page']} ---\n{p['text']}" for p in pages),
       'source_metadata':{'content_kind':'pdf_text_extracted','fetch_status':'done','document_pages':pages}}
    return s


def base(s):return {**source_anchor(s,defaultdict(list)),'entity':ROOT}


def build(*sources,**kwargs):
    return build_assessment_package({'facts':[]},ROOT,list(sources),intake=kwargs.pop('intake',{'as_of_date':'2026-10-14'}),**kwargs)


def metric(metric=METRICS[0],value='120',previous='100',third='90',kind='annual',cutoff='2025-12-31',**kwargs):
    return {'kind':'financial_metric','metric':metric,'value':value,'previous_value':previous,'third_value':third,
            'period':'2025年年度报告','period_kind':kind,'cutoff':cutoff,'unit':'千元',
            'printed_yoy_conflict':False,'evidence_ids':['E-000000000001'],'source_url':'https://www.hkexnews.hk/source.pdf',
            'source_title':'原件','entity':ROOT,'page':9,'fact':metric+' '+value,**kwargs}


def test_weights_are_explicit_company_performance_not_evidence_coverage():
    assert sum(d['weight'] for d in RUBRIC)==100
    assert [d['weight'] for d in RUBRIC]==[20,25,15,15,15,10]
    assert all('覆盖' not in d['name'] and '信用等级' not in d['name'] for d in RUBRIC)


def platform_source_record(text):
    return {'title':ROOT+'专业平台记录','url':'structured://qcc_company/financial/'+ROOT,
            'content':text,'source_metadata':{'provider':'qcc_company','content_kind':'structured_data'}}


def platform_metrics():
    return (f'| 字段 | 值 |\n| --- | --- |\n| 企业名称 | {ROOT} |\n\n'
        '| 指标 | 本期 | 上年同期 | 单位 | 币种 | 统计范围 | 报告期 | 报告截至日 |\n'
        '| --- | --- | --- | --- | --- | --- | --- | --- |\n'+''.join(
        f'| {m} | {a} | {b} | 万元 | 人民币 | 合并 | 2025年度 | 2025-12-31 |\n'
        for m,a,b in zip(METRICS,[120,12,24],[100,10,20])))


def test_original_platform_fields_can_score_revenue_profit_and_cash_without_exchange():
    p=build(platform_source_record(platform_metrics()))
    assert len(p['financial_observations'])==3
    assert [d['score'] for d in p['dimensions'][:2]]==[4,4]
    assert p['platform_source_review'][0]['admitted']
    assert p['platform_source_review'][0]['financial_records']==3
    assert '专业平台所载' in render_assessment(p)


@pytest.mark.parametrize('old,new',[
    (ROOT,CHILD),('2025-12-31','待查'),('万元','待查'),('合并','子公司口径'),
    ('人民币','待查'),('2025年度','2025年单季')])
def test_platform_class_is_admitted_but_missing_or_incompatible_fields_do_not_score(old,new):
    s=platform_source_record(platform_metrics().replace(old,new));p=build(s)
    assert not p['financial_observations']
    assert all(d['score'] is None for d in p['dimensions'])


def test_platform_estimated_revenue_does_not_erase_other_actual_metrics():
    p=build(platform_source_record(platform_metrics().replace('120','预计120')))
    assert len(p['financial_observations'])==2
    assert p['dimensions'][0]['score'] is None
    assert p['dimensions'][1]['score']==4


@pytest.mark.parametrize('state',['rejected','ambiguous','related_entity_context'])
def test_explicit_subject_quarantine_cannot_reenter_target_financial_scoring(state):
    s=platform_source_record(platform_metrics());s['source_metadata']['entity_validation']=state
    p=build(s)
    assert p['financial_observations']==[]
    assert all(d['score'] is None for d in p['dimensions'][:2])
    assert not p['platform_source_review'][0]['admitted']
    assert p['platform_source_review'][0]['reason']=='entity_validation:'+state


def test_platform_copy_of_actual_outcomes_and_audit_is_not_rejected_by_domain():
    s=src(extra=[outcome_page(),control_page()])
    s['url']='https://pilu.tianyancha.com/announcement/source.pdf'
    p=build(s);scores={d['id']:d['score'] for d in p['dimensions']}
    assert scores['revenue']==5 and scores['earnings_cash']==5
    assert scores['technology']==4 and scores['control']==3 and scores['team']==3.6


def test_platform_funding_amount_is_visible_without_inventing_completion_or_receipt():
    text=(f'| 字段 | 值 |\n| --- | --- |\n| 公司名称 | {ROOT} |\n\n'
          '| 融资日期 | 融资金额 | 融资轮次 | 投资方 |\n| --- | --- | --- | --- |\n'
          '| 2025-05-01 | 1000万元人民币 | A轮 | 甲基金 |\n')
    p=build(platform_source_record(text))
    assert len(p['platform_observations'])==1
    assert next(d for d in p['dimensions'] if d['id']=='funding')['score'] is None
    assert '1000万元人民币' in render_assessment(p)


def test_platform_explicit_completed_receipt_can_score_and_is_literal_revalidated():
    text=(f'| 字段 | 值 |\n| --- | --- |\n| 公司名称 | {ROOT} |\n\n'
          '| 融资日期 | 融资金额 | 完成状态 | 收款主体 | 实际募集净额 |\n'
          '| --- | --- | --- | --- | --- |\n'
          f'| 2025-05-01 | 1100万元人民币 | 已完成 | {ROOT} | 1000万元人民币 |\n')
    p=build(platform_source_record(text));d=next(d for d in p['dimensions'] if d['id']=='funding')
    assert d['score']==3 and d['records'][0]['original_quote_verified']
    for old,new in [('已完成','拟完成'),('2025-05-01','2020-05-01'),('1000万元人民币','待查')]:
        p=build(platform_source_record(text.replace(old,new)))
        assert next(d for d in p['dimensions'] if d['id']=='funding')['score'] is None


def test_platform_native_json_financial_rows_preserve_quote_and_decimal_precision():
    text='{"company_name": "'+ROOT+'", "financials": [{"metric":"营业收入","current_value":120.00,"previous_value":100.00,"unit":"万元","currency":"人民币","scope":"合并","report_period":"2025年度报告","report_end_date":"2025-12-31"}]}'
    package=build(platform_source_record(text))
    row=package['financial_observations'][0]
    assert row['value']=='120.00' and row['previous_value']=='100.00'
    assert row['evidence_quote'] in text and row['original_offset']==text.find(row['evidence_quote'])
    assert package['dimensions'][0]['score']==4


def test_mixed_company_platform_table_admits_only_target_rows_without_rejecting_comparison():
    text=platform_metrics().replace('| 指标 |','| 公司名称 | 指标 |').replace('| --- | --- | --- | --- | --- | --- | --- | --- |','| --- | --- | --- | --- | --- | --- | --- | --- | --- |')
    for metric_name in METRICS:text=text.replace('| '+metric_name+' |','| '+ROOT+' | '+metric_name+' |')
    text+='| '+CHILD+' | 营业收入 | 999 | 1 | 万元 | 人民币 | 合并 | 2025年度 | 2025-12-31 |\n'
    package=build(platform_source_record(text))
    assert len(package['financial_observations'])==3
    assert package['platform_source_review'][0]['admitted']
    assert not any(row['value']=='999' for row in package['financial_observations'])


@pytest.mark.parametrize('integers',[False,True])
def test_read_current_prior_and_third_values_from_actual_header_and_local_units(integers):
    s=src(integers=integers);rows=financial_observations(s,base(s))
    assert len(rows)==3 and all(r['unit']=='千元' and r['page']==9 for r in rows)
    assert all(r['cutoff']=='2025-12-31' and r.get('third_value') for r in rows)
    assert not any(r['printed_yoy_conflict'] for r in rows)


def test_interim_is_not_annualized_and_cannot_earn_two_annual_growth_bonus():
    s=src(year=2026,half=True);rows=financial_observations(s,base(s))
    assert all(r['period_kind']=='interim' and 'third_value' not in r for r in rows)
    scores=_financial_scores(rows)
    assert scores[0]['score']==4 and scores[1]['score']==4
    assert rows[0]['value']=='120.00'


@pytest.mark.parametrize('current,prior,third,expected',[
    ('120','100','90',5),('120','100',None,4),('100','100','90',3),
    ('90','100','80',2),('80','90','100',1),('0','90','80',1),
    ('20','0',None,3),('0','0',None,None),('-5','100','90',None)])
def test_revenue_scores_follow_observed_trend_not_scale(current,prior,third,expected):
    assert _financial_scores([metric(value=current,previous=prior,third=third)])[0]['score']==expected


@pytest.mark.parametrize('profit,cash,pp,cp,expected',[
    ('-1','-1','2','2',1),('-1','2','2','2',2),('0','2','2','2',2),
    ('2','1','3','2',3),('2','2','1','1',4)])
def test_profit_and_cash_are_not_divided_or_confused(profit,cash,pp,cp,expected):
    a=metric(METRICS[1],profit,pp,None);b=metric(METRICS[2],cash,cp,None)
    row=_financial_scores([a,b])[1]
    assert row['score']==expected and '不相除' in row['reason']


def test_conflicting_latest_observation_freezes_score_instead_of_picking_favorable():
    a=metric();b=metric(value='999')
    assert _financial_scores([a,b])[0]['score'] is None
    a['printed_yoy_conflict']=True
    assert _financial_scores([a])[0]['score'] is None


def test_profit_cash_require_matching_period_and_unit():
    a=metric(METRICS[1]);b=metric(METRICS[2],cutoff='2026-06-30',kind='interim')
    assert _financial_scores([a,b])[1]['score'] is None
    b=metric(METRICS[2],unit='万元')
    assert _financial_scores([a,b])[1]['score'] is None


def test_missing_dimensions_keep_weights_and_are_not_imputed_zero_or_three():
    ds=[score_row(d['id'],None,'缺原件',[]) for d in RUBRIC]
    ds[0]=score_row('revenue',4,'原件已核',[metric()])
    a=aggregate_scores(ds)
    assert a['quality_score'] is None and a['known_contribution']==16
    assert a['unassessed_weight_pct']==80 and a['possible_range']==[32.0,96.0]
    assert a['known_contribution']!=80  # no renormalization of one 4/5 dimension


def test_empty_packet_has_no_fake_low_score_or_meaningless_range():
    p=build()
    assert p['aggregate']['quality_score'] is None and p['aggregate']['possible_range'] is None
    assert assessment_errors(render_assessment(p),p)


def test_duplicate_documents_do_not_raise_company_score():
    s=src();a=build(s);b=build(s,deepcopy(s))
    assert a['aggregate']==b['aggregate']
    assert [(d['id'],d['score']) for d in a['dimensions']]==[(d['id'],d['score']) for d in b['dimensions']]


def test_cleaner_score_claims_and_wrong_company_original_are_not_inputs():
    s=src(owner='其他股份有限公司')
    p=build_assessment_package({'facts':[{'evidence_id':'E-000000000001','source_url':s['url'],
        'source_title':ROOT,'fact':'BBB+，公司技术4.8分，整体表现优异。','evidence_scope':'target_direct'}]},ROOT,[s],intake={'as_of_date':'2026-10-14'})
    assert not p['financial_observations'] and all(d['score'] is None for d in p['dimensions'])
    assert 'BBB+' not in render_assessment(p)


@pytest.mark.parametrize('mutator',[
    lambda s:s['source_metadata'].update(fetch_status='failed'),
    lambda s:s['source_metadata'].update(content_kind='search_summary'),
    lambda s:s.update(url='https://example.invalid/not-primary.pdf')])
def test_failed_snippet_or_untrusted_original_cannot_score(mutator):
    s=src();mutator(s)
    p=build(s)
    assert all(d['score'] is None for d in p['dimensions'])


def test_future_or_decade_old_financials_do_not_represent_current_profile():
    assert not build(src(year=2027))['financial_observations']
    assert not build(src(year=2010))['financial_observations']


def control_page(state='positive'):
    claim=(ROOT+'于2025年12月31日在所有重大方面保持了有效的财务报告内部控制。' if state=='positive'
           else ROOT+'于2025年12月31日未能在所有重大方面保持有效的财务报告内部控制。')
    return {'page':50,'text':'内部控制审计报告\n重大缺陷标准：财务报告内部控制无效；发现董事重大舞弊。\n内部控制审计报告中的审议意见段\n我们认为，'+claim}


def test_deficiency_definitions_are_not_findings_or_negative_opinions():
    s=src(extra=[control_page()]);rs=internal_control_observations(s,base(s))
    assert rs[0]['state']=='effective' and control_score(rs)['score']==3


def test_actual_adverse_internal_control_opinion_not_treated_as_effective():
    s=src(extra=[control_page('negative')]);rs=internal_control_observations(s,base(s))
    assert control_score(rs)['score']==1


def test_financial_statement_audit_and_company_self_assessment_do_not_replace_control_opinion():
    s=src(extra=[{'page':50,'text':'审计报告\n标准无保留意见。本公司自评内部控制有效。'}])
    assert not internal_control_observations(s,base(s))


def test_same_control_opinion_mirrors_cannot_earn_continuity_bonus():
    s=src(extra=[control_page()]);rs=internal_control_observations(s,base(s))
    assert control_score(rs*5)['score']==3
    previous={**rs[0],'cutoff':'2024-12-31'}
    assert control_score(rs+[previous])['score']==4


def funding_event(quote='2025年3月11日，本公司完成配售，所得款项净额为1,200万元。'):
    s=src(extra=[{'page':15,'text':quote}])
    r={**base(s),'kind':'event','period':'2025-03-11','fact':quote}
    return s,r


def test_only_actual_issuer_completed_funding_and_same_quote_amount_count():
    s,r=funding_event()
    assert funding_score({'facts':[r]},ROOT,'2026-10-14',{s['url']:s})['score']==3
    r2={**r,'fact':'2025年3月11日，本公司完成配售。'}
    assert funding_score({'facts':[r2]},ROOT,'2026-10-14',{s['url']:s})['score'] is None


@pytest.mark.parametrize('quote',[
    '2025年3月11日，本公司拟完成配售，净额1,200万元。',
    '2025年3月11日，本公司子公司完成配售，净额1,200万元。',
    '2025年3月11日，本公司获批发行，净额1,200万元。'])
def test_planned_approved_or_subsidiary_funding_not_parent_execution_grade(quote):
    s,r=funding_event(quote)
    assert funding_score({'facts':[r]},ROOT,'2026-10-14',{s['url']:s})['score'] is None


def outcome_page(tech=True,execution=True):
    text='本集团合并口径\n2025年 2024年 同比\n核心技术产品收入（千元） 120 100 20.00%'
    tables=[]
    if execution:
        text+='\n全公司目标考核范围涵盖下表全部指标'
        tables=[[
            ['指标','目标','实际','单位','目标批准日期','责任主体','考核权重（%）'],
            ['年度交付','100','110','台','2024年12月20日',ROOT,'60'],
            ['年度服务','20','20','项','2024年12月20日',ROOT,'40']]]
    return {'page':51,'text':text if tech else text[text.find('全公司目标'):], 'tables':tables}


def test_proper_company_outcomes_enable_technology_and_execution_scoring():
    s=src(extra=[outcome_page()]);tech,ex=outcome_observations([s],ROOT,defaultdict(list))
    assert len(tech)==1 and len(ex)==2
    assert execution_score(ex,[])['score']==3.6
    p=build(s);scores={d['id']:d['score'] for d in p['dimensions']}
    assert scores['technology']==4 and scores['team']==3.6


def test_subsidiary_tech_data_or_missing_company_scope_cannot_become_company_score():
    p=outcome_page();p['text']=p['text'].replace('本集团合并口径','子公司财务口径')
    s=src(extra=[p]);tech,_=outcome_observations([s],ROOT,defaultdict(list))
    assert not tech


def test_execution_incomplete_weights_and_retroactive_goals_do_not_score():
    p=outcome_page();p['tables'][0].pop();s=src(extra=[p]);_,ex=outcome_observations([s],ROOT,defaultdict(list))
    assert execution_score(ex,[])['score'] is None
    p=outcome_page();p['tables'][0][1][4]='2025年12月20日';s=src(extra=[p]);_,ex=outcome_observations([s],ROOT,defaultdict(list))
    assert execution_score(ex,[])['score'] is None


def test_complete_evidence_can_produce_company_score_not_permanent_unknown_workaround():
    funding='2025年3月11日，本公司完成配售，所得款项净额为1,200万元。'
    s=src(extra=[outcome_page(),control_page(),{'page':15,'text':funding}])
    p=build(s)
    assert all(d['score'] is not None for d in p['dimensions'])
    assert p['aggregate']['quality_score'] is not None
    assert not assessment_errors(render_assessment(p),p)


def capital_parent():
    return src(extra=[{'page':55,'text':'本公司分拆所属子公司'+CHILD+'至交易所上市。2022年1月27日，'+CHILD+'符合发行条件、上市条件和信息披露要求。'}])


def termination_notice(quoted_child=CHILD):
    return {'title':'发行注册程序终止通知书','url':'https://www.csrc.gov.cn/notice/2022/stop.html',
            'content':quoted_child+'：\n2022年11月23日，你公司提交申请，主动要求撤回注册申请文件。\n根据有关规定，我会决定终止对你公司发行注册程序。\n2022年12月27日',
            'source_metadata':{'content_kind':'html_text_extracted','fetch_status':'done'}}


def test_capital_status_uses_later_formal_termination_not_earlier_approval():
    rows,_=capital_status_observations([capital_parent(),termination_notice()],ROOT,defaultdict(list),'2026-10-14')
    assert len(rows)==1 and rows[0]['state']=='terminated' and rows[0]['date']=='2022-12-27'


def test_termination_is_not_transferred_by_brand_or_unproven_parent_relation():
    rows,_=capital_status_observations([termination_notice()],ROOT,defaultdict(list),'2026-10-14')
    assert not rows
    rows,_=capital_status_observations([capital_parent(),termination_notice('青禾其他股份有限公司')],ROOT,defaultdict(list),'2026-10-14')
    assert rows and all(r['state']!='terminated' for r in rows)


def test_future_parent_relationship_not_available_for_historical_cutoff():
    rows,_=capital_status_observations([capital_parent(),termination_notice()],ROOT,defaultdict(list),'2022-02-01')
    assert not rows


def test_invalid_research_cutoff_cannot_be_silently_reinterpreted():
    with pytest.raises(ValueError,match='截至日无法识别'):
        build(src(),intake={'as_of_date':'2026-02-30'})


def test_combined_company_and_consolidated_statement_date_before_title():
    s=src();s['source_metadata']['document_pages'][2]['text']='青禾制造股份有限公司\n2025年12月31日合并及公司资产负债表\n金额单位为人民币千元\n流动资产'
    assert filing_cutoff(s['source_metadata']['document_pages'])=='2025-12-31'
    assert len(financial_observations(s,base(s)))==3


@pytest.mark.parametrize('progress,expected',[
    ('截至2025年末，项目尚未投产，正在准备工作。',None),
    ('2025年10月1日，核心器件项目已投产，开展客户交付。',3),
    ('2028年10月1日，核心器件项目已投产，开展客户交付。',None),
    ('项目已经终止量产工作，后续发展另行研究。',None),
    ('核心器件达到A样状态，预计2026年实现上市。',2),
    ('项目处于研发样机试制阶段，开展性能验证。',2)])
def test_project_targets_future_dates_or_termination_are_not_accomplished_production(progress,expected):
    page={'page':20,'text':'主要研发项目情况\n'+progress,
          'tables':[[['项目名称','项目目的','项目进展','拟达到目标','对公司影响'],
                     ['核心器件','提高效率',progress,'明年实现大规模量产','提升商业化能力']]]}
    p=build(src(extra=[page]));d=next(d for d in p['dimensions'] if d['id']=='technology')
    assert d['score'] is None
    assert ([r['project_observation_score'] for r in d['project_scores']] or [None])==[expected]


def test_narrative_does_not_join_different_period_profit_and_cash_as_coexisting():
    annual=src();interim=src(year=2026,half=True,index=2)
    page=interim['source_metadata']['document_pages'][1]
    page['text']='\n'.join(line for line in page['text'].splitlines() if METRICS[1] not in line)
    interim['content']='\n'.join(p['text'] for p in interim['source_metadata']['document_pages'])
    p=build(annual,interim)
    assert next(d for d in p['dimensions'] if d['id']=='earnings_cash')['score'] is None
    assert '已观察到盈利与经营现金净流入并存' not in render_assessment(p)


def test_model_cannot_rewrite_checked_chapter12_and_audit_index_uses_its_originals(monkeypatch):
    from report_agents.company_report_agent import CompanyReportAgent
    from research_workflow import ResearchWorkflow
    s=src();project=SimpleNamespace(target_name=ROOT,title=ROOT,target_type='company',industry='制造',description='',sources=[s],company_research_intake={'as_of_date':'2026-10-14'})
    agent=CompanyReportAgent()
    monkeypatch.setenv('COMPANY_REPORT_EDITOR_ENABLED','true')
    monkeypatch.setattr(agent,'_write_summary',lambda *a,**k:'## 1. 摘要\n摘要。')
    monkeypatch.setattr(agent,'_edit_batched',lambda *a,**k:'\n'.join(f'## {i}. 标题\n'+('BBB+，评分4.8，全数通过。[E-FFFFFFFFFFFF]' if i==12 else '待核验。') for i in range(1,15)))
    events=[]
    text=agent.generate(project,'{"facts":[]}','{}',lambda *a,**kw:'',lambda s,n:s[:n],lambda *a,**kw:events.append(a))
    chapter=text.split('## 12.')[1].split('## 13.')[0]
    assert 'BBB+' not in chapter and '4.8' not in chapter and '原始贡献' in chapter
    assert not project.company_assessment_diagnostic['degraded']
    assert any(len(e)>4 and e[3]=='公司章节证据分桶完成' and 'unique_package_sources=1' in e[4] for e in events)
    indexed=ResearchWorkflow.__new__(ResearchWorkflow)._append_company_claim_evidence_index(project,text,[],total_traceable_sources=1,eligible_company_sources=1)
    assert '第十二章原文核对' in indexed


def test_no_citation_padding_and_no_model_rating_fallback_for_empty_chapter():
    from report_agents.company_report_agent import CompanyReportAgent
    p=build();text=CompanyReportAgent._ensure_section_evidence_markers(render_assessment(p),{12:[]})
    assert '分项锚点' in text and '数学边界' not in text and 'BBB+' not in text


def test_tampered_aggregate_and_orphan_eid_are_detected():
    p=build(src());p['aggregate']['known_contribution']=99
    assert len(assessment_errors(render_assessment(p)+'[E-FFFFFFFFFFFF]',p))==2


def test_partial_pdf_metrics_do_not_imply_full_document_acceptance():
    s=src();s['source_metadata']['document_extraction']={'omitted_pages':135,'needs_ocr_pages':[80]}
    p=build(s)
    assert p['diagnostic']['scored_dimensions']>=2
    assert '135页未提取' in render_assessment(p) and p['source_limitations']


def test_company_template_fallback_without_current_chapter_checks_fails_gate():
    from research_workflow import ResearchWorkflow
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    p=SimpleNamespace(target_type='company',target_name=ROOT,company_verified_chapters_required=True)
    report='\n\n'.join(f'## {i}. 标题\n有原始材料的有限判断。' for i in range(1,15))
    with pytest.raises(RuntimeError,match='第12章缺少本轮原件核对结果'):
        w._validate_delivery_report(p,report)


def test_generation_resets_old_diagnostics_before_any_template_fallback():
    from research_workflow import ResearchWorkflow
    class FailAgent:
        def generate(self,*a,**kw):raise RuntimeError('模拟写作故障')
    w=ResearchWorkflow.__new__(ResearchWorkflow);w._report_agents={'company':FailAgent()}
    p=SimpleNamespace(target_type='company',target_name=ROOT,company_assessment_diagnostic={'degraded':False},company_summary_package={'facts':[{'evidence_id':'E-OLD123456'}]})
    with pytest.raises(RuntimeError,match='模拟写作故障'):
        w.generate_report(p,'{}','{}',intake={'target_type':'company'})
    assert p.company_verified_chapters_required and p.company_assessment_diagnostic=={}
    assert p.company_summary_package=={}
