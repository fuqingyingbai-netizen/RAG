'Industry outline adapted from the supplied report reference workbook.'

TEMPLATE_VERSION = 'industry-content-template-v2-required-questions'

from industry_chapters import CHAPTERS, report_chapters

INDUSTRY_REPORT_OUTLINE = [(c['title'], c['requirements']) for c in CHAPTERS]

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
        'version': TEMPLATE_VERSION, 'report_chapter_count': len(report_chapters(scope)),
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
    from industry_chapters import report_chapters
    expected_chapters = report_chapters(scope)
    if [int(n) for n, _ in headings] != expected_chapters:
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
        if index not in expected_chapters:
            continue
        if ((index in {8,9} and scope.get('capital_market') == 'none')
                or (index == 12 and not scope.get('named_companies'))):
            continue
        for row in plan.get('content_coverage') or []:
            if row.get('status') != 'source_material_pending_review' or row.get('analysis_status') != 'draft_analysis_present':
                gaps.append({'chapter':index, 'question':row['question'], 'material_status':row.get('status'),
                             'analysis_status':row.get('analysis_status')})
    return {'version': TEMPLATE_VERSION, 'structure_passed': not errors, 'errors': errors,
            'content_gaps': gaps, 'entailment_status': 'not_evaluated'}
