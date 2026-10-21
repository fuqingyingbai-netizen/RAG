import json
from types import SimpleNamespace

import pytest

from report_agents.company_operations import (
    HEADINGS,build_operations_package,render_operations,operations_errors,
)
from report_agents.company_report_agent import CompanyReportAgent
from test_company_history import filing


def package(name,*pairs,**kwargs):
    return build_operations_package({'facts':[p[0] for p in pairs]},name,[p[1] for p in pairs],**kwargs)


@pytest.mark.parametrize('name',['星河精密股份有限公司','青禾食品有限公司','Northstar Robotics Limited'])
def test_company_independent_chapter_with_explicit_incentive_execution(name):
    p=package(name,filing(name,'本员工持股计划已完成股票的购买，累计买入500股。'))
    text=render_operations(p)
    assert all('### '+h in text for h in HEADINGS)
    assert '500股' in text and '比亚迪' not in text and '购买执行披露' in text
    assert operations_errors(text,p)==[]


def test_workforce_counts_keep_parent_subsidiary_and_combined_scope():
    name='星河精密股份有限公司'
    raw='报告期末母公司在职员工的数量（人）2,075 报告期末主要子公司在职员工的数量（人）867,547 报告期末在职员工的数量合计（人）869,622'
    text=render_operations(package(name,filing(name,raw)))
    assert '母公司在职员工2,075人' in text and '主要子公司在职员工867,547人' in text
    assert '母公司及主要子公司合计在职员工869,622人' in text
    assert '高度分散' not in text and '相差300倍' not in text


def test_workforce_missing_not_zero_and_insured_not_group_employees():
    name='青禾食品有限公司'
    text=render_operations(package(name,filing(name,'本公司参保人数20人。')))
    assert '母公司在职员工20人' not in text and '在职员工0人' not in text
    assert '多数员工未参保' not in text


def test_non_independent_director_never_matches_independent_director():
    name='青禾食品有限公司'
    pair=filing(name,'公司董事会已召开会议。')
    c=pair[0]
    governance={'facts':[dict(c,kind='personnel',entity='甲',role='非独立董事',period='未载'),
                          dict(c,kind='personnel',entity='乙',role='独立董事',period='未载')]}
    p=package(name,pair,governance=governance)
    role=next(r for r in p['facts'] if r['mode']=='任职字段')
    assert '乙' in role['fact'] and '甲' not in role['fact']


def test_charter_design_not_proof_of_executed_meetings_or_effectiveness():
    name='青禾食品有限公司'
    c,s=filing(name,'')
    s['content']=name+'章程\n2025年10月\n第一百条 董事会每年至少召开两次会议。审核委员会负责审核公司财务信息。总经理对董事会负责。'
    c['evidence_scope']='industry_context'
    p=package(name,(c,s));text=render_operations(p)
    assert len(p['facts'])==3 and all(r['mode']=='制度条款' for r in p['facts'])
    assert '2025年10月章程' in text and '公司运行披露' not in text
    assert '集权型' not in text and '封闭的权力核心' not in text


def test_wrong_or_rejected_issuer_charter_not_recovered():
    name='青禾食品有限公司';c,s=filing(name,'')
    s['content']='青禾餐饮有限公司章程\n2025年10月\n董事会每年召开两次会议。'
    assert package(name,(c,s))['facts']==[]
    c,s=filing(name,'公司董事会召开会议。');c['eligible_for_report']=False
    assert package(name,(c,s))['facts']==[]


def test_authorization_only_in_rights_and_duplicate_periods_suppressed():
    name='青禾食品有限公司'
    raw='公司董事会会议审议通过议案，董事会同意授权公司管理层制定市值管理制度。'
    p=package(name,filing(name,raw),filing(name,raw,year=2026,i=2))
    matches=[r for r in p['facts'] if '授权' in r['fact']]
    assert len(matches)==1 and matches[0]['aspect']==HEADINGS[2]
    assert matches[0]['period']=='2026年年度报告'


def test_conditional_control_defect_clause_not_reported_as_actual_defect():
    name='青禾食品有限公司'
    p=package(name,filing(name,'4）内部控制评价的结果特别是重大或重要缺陷未得到整改；公司内部控制自我评价报告披露不存在内部控制重大缺陷和重要缺陷。'))
    assert len(p['facts'])==1 and p['facts'][0]['mode']=='公司内控自述'
    assert '未得到整改' not in render_operations(p)


def test_failed_incentive_condition_survives_quota_and_not_converted_to_unlock():
    name='青禾食品有限公司'
    raw=('参与本员工持股计划的总人数不超过25,000人。'
         '本员工持股计划累计买入10,000股，已完成股票的购买。'
         '本员工持股计划的股票分三期解锁，解锁时点为12个月、24个月、36个月。'
         '本员工持股计划首个锁定期于2026年5月23日届满。'
         '第一个解锁期公司层面的业绩考核指标为2025年营业收入增长率不低于10%。'
         '由于第一个解锁期解锁条件未达成，本员工持股计划的相应奖励股份将不会解锁。')
    p=package(name,filing(name,raw));text=render_operations(p)
    assert '不会解锁' in text and '2025年营业收入增长率不低于10%' in text
    assert '执行结果／未达成' in text and '计划额度／非实际人数' in text
    assert '已覆盖25,000人' not in text and len([r for r in p['facts'] if r['aspect']==HEADINGS[4]])<=4


def test_rnd_table_preserves_capitalization_and_years_not_marketing_approximation():
    name='青禾食品有限公司'
    raw='公司研发投入情况 2025年 2024年 变动比例 研发投入金额（元）63,441,379,000.00 54,160,964,000.00 17.13% 研发投入资本化的金额（元）5,463,274,000.00 966,219,000.00 465.43%'
    text=render_operations(package(name,filing(name,raw)))
    assert '63,441,379,000.00元' in text and '5,463,274,000.00元' in text
    assert '465.43%' in text and '全球领先' not in text


def test_rnd_integer_cells_require_original_boundaries():
    name='青禾食品有限公司'
    p=package(name,filing(name,'公司研发人员情况 2025年2024年变动比例研发人员数量（人）50040025.00%'))
    assert not p['facts']
    p=package(name,filing(name,'公司研发人员情况 2025年 2024年 变动比例 研发人员数量（人）500 400 25.00%'))
    assert '2025年500人，2024年400人' in render_operations(p)


@pytest.mark.parametrize('unit',['万元','万美元','EUR'])
def test_other_company_rnd_currency_and_units_not_assumed_yuan(unit):
    name='Northstar Robotics Limited'
    raw=f'公司研发投入情况 2025年 2024年 变动比例 研发投入金额（{unit}）120.00 100.00 20.00%'
    text=render_operations(package(name,filing(name,raw)))
    assert f'2025年120.00{unit}，2024年100.00{unit}' in text


def test_no_response_conclusion_from_pricing_and_subsidiary_registration():
    name='青禾食品有限公司'
    p=package(name,filing(name,'子公司于2025年新增电池回收经营范围。公司于2025年上调产品选装价格。'))
    assert not any(r['aspect']==HEADINGS[5] for r in p['facts'])


def test_complete_financial_segments_labelled_separately_from_organization_chart():
    name='青禾食品有限公司'
    raw='本集团目前有两个报告分部，分别如下：a) 食品分部包括制造及销售食品；b) 包装分部包括制造包装产品。管理层出于配置资源和评价业绩的决策目的分开管理。'
    p=package(name,filing(name,raw));rows=[r for r in p['facts'] if r['aspect']==HEADINGS[0]]
    assert len(rows)==1 and '食品分部' in rows[0]['fact'] and '包装分部' in rows[0]['fact']
    assert rows[0]['mode']=='财务报告分部／非组织架构'


def test_auditor_procedure_not_internal_control_effectiveness_opinion():
    name='青禾食品有限公司'
    p=package(name,filing(name,'我们在审计过程中对收入确认执行的审计程序包括评价与收入相关内部控制的设计及执行有效性；'))
    assert p['facts'][0]['mode']=='外部审计程序／非全面有效结论'


def test_company_response_plan_and_actual_exercise_remain_distinct():
    name='青禾食品有限公司'
    p=package(name,filing(name,'公司已建立业务连续性管理机制并开展应急演练。公司计划将于2026年开展应急演练。'))
    modes={r['mode'] for r in p['facts'] if r['aspect']==HEADINGS[5]}
    assert modes=={'公司运行披露','计划／执行待核验'}


def test_traditional_governance_keeps_original_quotes_and_separates_evidence_modes():
    from opencc import OpenCC
    name='青禾食品有限公司'
    raw=('目前，我们的薪酬委员会由三名成员组成，均为独立董事。'
         '我们的审计委员会的政策是，事先批准所有审计及非审计服务。'
         '我们的独立注册公众会计师事务所已对我们财务报告内部控制的有效性进行了审计。'
         '我们对财务报告内部控制的审计包括了解内部控制及评估是否存在重大缺陷的风险。')
    c,s=filing(name,OpenCC('s2t').convert(raw))
    p=package(name,(c,s))
    modes={r['mode'] for r in p['facts']}
    assert {'委员会组成披露','制度条款','公司披露的外部审计范围','外部审计程序／非全面有效结论'}<=modes
    assert all(r['fact'] in s['content'] for r in p['facts'])
    assert any('審計' in r['fact'] for r in p['facts'])


@pytest.mark.parametrize('raw',[
    '请参见「第4项.公司资料—C.组织架构」。',
    '• 「代表性实体」 指 「 第4项.公司资料—C.组织架构」中我们识别的实体；',
    '网络运营者负有制定网络安全事件应急预案等义务。',
    '上市公司须设有薪酬委员会及提名委员会，各委员会均完全由独立董事组成。',
    '组织架构调整可能会对我们的业务造成干扰，并产生重大不利影响。',
    '当本公司改变其内部组织架构导致报告分部组成变化时，先前期间将重列。',
    '• 薪酬委员会或提名委员会完全由独立董事组成；',
])
def test_traditional_references_legal_requirements_and_hypotheses_are_not_running_evidence(raw):
    from opencc import OpenCC
    name='青禾食品有限公司'
    assert not package(name,filing(name,OpenCC('s2t').convert(raw)))['facts']


def test_budget_keeps_whole_evidence_records_and_no_unknown_ids():
    name='青禾食品有限公司'
    p=package(name,filing(name,'公司董事会召开会议。总经理对董事会负责。'),limit=4000)
    assert len(json.dumps(p,ensure_ascii=False))<4000
    assert operations_errors(render_operations(p),p)==[]


def test_evidence_cannot_be_rewritten_to_control_or_unknown_citation():
    name='青禾食品有限公司'
    p=package(name,filing(name,'公司董事会召开会议。'))
    assert operations_errors(render_operations(p)+'公司治理稳定。[E-FFFFFFFFFFFF]',p)
    assert operations_errors(render_operations(package(name)),package(name))


def test_checked_operations_survive_batch_editor_without_padding(monkeypatch):
    name='青禾食品有限公司';pair=filing(name,'本员工持股计划已完成股票的购买，累计买入500股。')
    p=SimpleNamespace(target_name=name,title=name,target_type='company',industry='食品',description='',sources=[pair[1]])
    agent=CompanyReportAgent();monkeypatch.setattr(agent,'_write_section',lambda *a,**k:'')
    monkeypatch.setattr(agent,'_write_summary',lambda *a,**k:'## 1. 摘要\n摘要。')
    monkeypatch.setenv('COMPANY_REPORT_EDITOR_ENABLED','true')
    monkeypatch.setattr(agent,'_edit_batched',lambda *a,**k:'## 1. 摘要\n摘要。\n## 2. 工商\n待核验。\n## 3. 历史\n待核验。\n## 4. 治理\n集权型治理、未披露激励。[E-FFFFFFFFFFFF]\n## 5. 口碑\n待核验。')
    result=agent.generate(p,json.dumps({'facts':[pair[0]]}),'{}',lambda *a:'',lambda s,n:s[:n],lambda *a,**k:None)
    chapter=result.split('## 4.')[1].split('## 5.')[0]
    assert '500股' in chapter and 'FFFFFFFFFFFF' not in chapter and '本章引用证据' not in chapter
