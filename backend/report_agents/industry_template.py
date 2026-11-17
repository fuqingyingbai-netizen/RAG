'Industry outline adapted from the supplied report reference workbook.'

TEMPLATE_VERSION = 'industry-content-template-v2-required-questions'

INDUSTRY_REPORT_OUTLINE = [('摘要', ['整篇报告的完整摘要，涵盖报告概述、核心研究发现、需关注信号、标的所属赛道竞争格局速览及总体评估等要点']),
 ('行业基础定义与产业链全景', ['涵盖行业分类、行业定义内涵、代表产品及应用领域，完整产业链上下游结构图谱，产业链各环节代表企业、价值分配与平均毛利率水平，以及产业链核心瓶颈环节研判']),
 ('政策环境分析与近期政策摘录',
  ['包含国家级顶层规划、专项行动、行业标准体系、补贴准入资质、重点省市产业规划、园区载体、产业基金以及监管收紧、进出口管制、技术断供等政策风险识别。附近期行业相关政策文件原文摘编以及政策基调与监管方向的综合判断']),
 ('市场规模与增长预测',
  ['包含行业近3-5年历史市场规模与CAGR增速，对未来5-10年市场规模进行分场景预测；确认增长的核心驱动因素与制约因素，判断行业天花板以及目前整体所处阶段（实验室/原型验证/小批量量产/规模化商用）']),
 ('行业热度形成',
  ['以市场环境催化（里程碑事件、市场规模与增速、商业化进展、终端需求变化等）和政策驱动（国家顶层设计、监管审批突破、地方配套政策等）两大维度，系统分析赛道热度来源、景气度变化趋势及资本关注的核心逻辑']),
 ('竞争格局', ['涵盖玩家分层（头部链主/腰部/初创/海外巨头）与CR3/CR5市场集中度；进行波特五力模型（上下游议价/同业竞争/新进入者/替代品）模型；介绍行业核心竞争力与护城河']),
 ('技术路线对比', ['行业主流技术路线横向对比，含优劣势、落地难度、成本、迭代速度、商业化成熟度等维度']),
 ('行业投融资全景', ['涵盖近年一级市场融资总规模、融资事件汇总、阶段分布及地域融资梯队；资本市场IPO进度、已上市标的及估值区间；产业并购案例及估值倍数；产业资本（车企/互联网/制造龙头等）战略布局方向']),
 ('二级市场情绪', ['行业板块近期走势、估值水平（PE/PB/PS）、机构配置热度、卖方覆盖与评级变化、成交额占比等情绪指标的综合研判']),
 ('投资机会', ['从细分赛道选择、核心能力筛选标准、产业整合路径、资本配置方向等维度，并结合资本市场情绪热度识别行业核心投资机会，明确标的筛选逻辑与重点关注的标的类型']),
 ('前景展望', ['综合上述研究结果，对赛道未来3-5年发展趋势、关键变量、可能的情景路径进行展望判断']),
 ('行业核心公司主体全面尽调',
  ['基本信息：企业注册信息（成立时间、公司规模、注册资本等）；股权架构及历史工商变更情况；业务发展历程、历史沿革、关键里程碑及股权变动',
   '核心业务经营状况：核心业务板块及全系列产品参数、技术路线、自研核心技术、专利；研发落地进度、新产品线规划及新品上市计划；新产品销售情况及公司内部市场前景与业绩增长预期；生产规划、产能情况及产能利用率等',
   '竞品与交易对标分析：统一核心可比企业筛选标准，进行多维对比（融资估值/营收交付/技术/客户/产能/毛利率/商业模式等）；近年同赛道融资并购IPO案例复盘；标的相对竞品的核心差异化优劣势',
   '经营与客户供应商分析：销售渠道（直销/经销/海外占比）；客户结构（前五大客户、集中度、合作年限、订单规模、行业分布）；供应商结构（上游核心厂商、采购集中度、供应链风险）；商业模式、定价体系、收费模式等']),
 ('风险核查',
  ['根据上述检索信息进行风险识别',
   '-行业层面风险\n'
   '-标的经营风险（客户集中、产能不足、商业化慢、供应链依赖）\n'
   '-技术研发风险（迭代落后、核心部件外购、模型能力不足）\n'
   '-合规法律风险（股权瑕疵、资质过期、诉讼、数据安全）\n'
   '-资本与估值风险（估值过高、融资承压、现金流紧张）等']),
 ('综合评估', ['对目标行业进行综合评估；明确风险分与行业吸引力等评价的区别，无有效证据时写待核验。指定核心企业时，另列企业评价与局限，不与行业评分混合。']),
 ('信息来源', ['注明检索的信息来源，包括信息点、网址等，以及检索用的数据获取工具']),
 ('后续研究点', ['给出有待确认的信息点和进行下一步更加深度的研究所需要关注的研究方向'])]

INDUSTRY_PROPOSAL_OUTLINE = [
 ('项目基本情况', ['调研目的、目标行业、核心动因、研究范围与关注方向']),
 ('项目调研分析', ['一般分析方法、行业特殊问题、本轮优先核验任务与完成条件']),
 ('项目调研框架与主要研究范围', ['规模、增长、渗透率及ToB/ToC；商业模式、收入结构与用户粘性；功能、模型策略、部署及质量评测；定价、付费率、ARPU、留存与玩家比较；政策及风险；资本、企业经营及管理层按用户范围启用']),
 ('项目调研方法与渠道资源', ['国内与海外渠道、授权数据库、专家及上下游客户访谈、交叉验证；列表注明可用性、授权和负责人，区分拟使用与已完成']),
 ('项目工作方法与周期安排', ['工作阶段及分项排期、任务关联、资料依赖、预计工作日与负责人；中期简报可选，最终报告、实际访谈纪要及适用风险矩阵评分；实际周期由双方确认']),
 ('项目团队安排', ['角色、姓名职位、从业经验、擅长领域、职责及投入确认表；实际人员由业务确认，不得编造']),
 ('项目报价与保密条款', ['人员、数据、访谈、差旅及其他费用确认表；计量单位数量、单价金额税费、币种、付款节点、预算审批及保密数据管理；金额和合同条款待双方确认']),
]


def chapter_template_contract(index, scope=None):
    """The reader's template is an input requirement, never a source of facts."""
    scope = scope or {}
    title, requirements = INDUSTRY_REPORT_OUTLINE[index-1]
    return {
        'version': TEMPLATE_VERSION, 'report_chapter_count': 16,
        'chapter': index, 'title': title, 'required_content': list(requirements),
        'scope_rules': {
            'capital_enabled': scope.get('capital_market') != 'none',
            'company_diligence_enabled': bool(scope.get('named_companies')),
            'geography': scope.get('geography') or '', 'as_of_date': scope.get('as_of_date') or '',
        },
        'requirements': [
            '标题、顺序和必答内容固定，不以几条摘录替代本章研究任务。',
            '逐项区分有来源支持、仅有样本或观点、缺少资料；未回答的内容进入核验任务。',
            '分析须说明引用材料能支持什么、与本章问题有什么关系，以及尚缺的验证条件。',
            '模板要求不授权补造数据、市场预测、企业事实、评分或已完成的工作。',
            '资本关闭时不补资本指标；未指定企业时不生成企业尽调；样本不评分行业整体。',
        ],
    }


def validate_report_template(report, plans=None, scope=None):
    """Check structure and expose unanswered content; no semantic certification."""
    import re
    scope = scope or {}
    headings = re.findall(r'^##\s+(\d+)\.\s+([^\n]+)', report, re.M)
    errors = []
    if [int(n) for n, _ in headings] != list(range(1, 17)):
        errors.append('report_template_chapter_order')
    for number, heading in headings:
        index = int(number)
        if 1 <= index <= 16:
            expected = INDUSTRY_REPORT_OUTLINE[index-1][0]
            if heading != expected and not (index == 15 and heading.startswith(expected+'（')):
                errors.append('report_template_title_'+number)
    gaps = []
    for number, plan in (plans or {}).items():
        index = int(number)
        if ((index in {8,9} and scope.get('capital_market') == 'none')
                or (index == 12 and not scope.get('named_companies'))):
            continue
        for row in plan.get('content_coverage') or []:
            if row.get('status') != 'source_material_pending_review' or row.get('analysis_status') != 'draft_analysis_present':
                gaps.append({'chapter':index, 'question':row['question'], 'material_status':row.get('status'),
                             'analysis_status':row.get('analysis_status')})
    return {'version': TEMPLATE_VERSION, 'structure_passed': not errors, 'errors': errors,
            'content_gaps': gaps, 'entailment_status': 'not_evaluated'}
