"""A bounded proposal matching the reference template's seven sections."""
import json
import re
from .industry_proposal_contract import render_tables, validate_proposal, _cell


def _task_overview(tasks, risk, scope=None):
    """Project questions first; detailed work and source locators live in appendices."""
    from industry_delivery import _cell
    unknown = [str(d.get('name')) for d in risk.get('dimensions', [])
               if d.get('score') is None and d.get('name')
               and not ((scope or {}).get('capital_market') == 'none'
                        and (d.get('key') == 'capital' or '资本' in str(d.get('name'))))]
    lines = []
    if unknown:
        lines += ['本轮尚未完成有效评估的事项：' + '、'.join(unknown) + '。先区分评分校验问题与真实资料缺口，再决定复核、补采或缩减范围。', '']
    lines += ['| 优先级 | 本轮待解决问题 | 完成条件 |', '| --- | --- | --- |']
    chapter_topics = {}
    for t in tasks:
        lines.append('| ' + ' | '.join(map(_cell, (t.get('priority', '高'),
            str(t.get('task_id') or t.get('key') or '') + ' ' + str(t.get('topic') or '待确认问题'),
            t.get('completion') or '核对原始材料后复核；缺证继续保留未知。'))) + ' |')
        # All individual questions and full completion criteria remain in
        # appendix A; the main proposal must not duplicate that entire appendix.
        for sub in t.get('subtasks') or []:
            if sub.get('material_status', sub.get('status')) in {'missing', 'background_only'}:
                chapter_topics.setdefault(sub['chapter'], [])
                if sub['topic'] not in chapter_topics[sub['chapter']]:
                    chapter_topics[sub['chapter']].append(sub['topic'])
    if chapter_topics:
        lines += ['', '优先复核方向（完整动作见附录A）：' + '；'.join(
            '第'+str(chapter)+'章：'+'、'.join(topics) for chapter, topics in chapter_topics.items())+'。']
    if not tasks:
        return ('\n'.join(lines[:2]) if unknown else '') + '本轮尚未登记专项任务，实施前先核对报告及实际研究缺口。'
    return '\n'.join(lines)


def build_industry_proposal(project, report='', risk_json='{}') -> str:
    scope = getattr(project, 'industry_scope', {}) or {}
    segments = '、'.join(scope.get('segments') or [project.target_name])
    companies = '、'.join(scope.get('named_companies') or []) or '未指定；企业主体尽调不在本轮默认范围'
    capital = '纳入一级融资、IPO、估值与二级市场概览' if scope.get('capital_market') == 'summary' else '不纳入资本市场指标'
    try:
        risk = json.loads(risk_json) if isinstance(risk_json, str) else (risk_json or {})
    except (ValueError, TypeError):
        risk = {}
    from industry_delivery import verification_tasks, verification_task_table, consolidate_verification_tasks
    structured_tasks = getattr(project,'industry_verification_tasks',None)
    if isinstance(structured_tasks,list):
        # The current report and proposal share one prioritized gap list. Do
        # not rescan prose or silently truncate late technical/quality tasks.
        tasks=[dict(t) for t in structured_tasks if isinstance(t,dict)]
    else:
        tasks=verification_tasks(getattr(project,'industry_evidence_payload',{}) or {},risk,
                                 getattr(project,'industry_report_degradations',[]) or [],scope)
        # Legacy callers may only have the report. Treat an explicit technical
        # gap as a review task, never synthesize technical facts from its prose.
        if re.search(r'技术路线.{0,40}(?:缺失|缺少|待核验)|无法构建横向对比',report) and not any('技术' in t['topic'] for t in tasks):
            tasks += verification_tasks({}, {}, [{'chapter':7,'message':'技术路线尚未形成同条件比较，需复核测试条件及性能成本材料。'}], scope)
    tasks = consolidate_verification_tasks(tasks)
    task_section=_task_overview(tasks, risk, scope)
    tables=render_tables(scope, tasks)
    task_detail=verification_task_table(tasks, include_reference_index=False, reference_location='附录B候选来源索引')
    task_sources=verification_task_table(tasks, reference_index_only=True)
    dependency=getattr(project,'industry_report_dependency',{}) or {}
    basis=('依据报告：v'+str(dependency.get('report_version') or '待核验')
           +'（产物 '+str(dependency.get('report_artifact_id') or '待核验')+'）；生成时间：'
           +str(dependency.get('report_created_at') or '待核验')+' UTC；运行编号：'
           +str(dependency.get('run_id') or '待核验')+'。\n\n'
           +'报告正文SHA256：'+str(dependency.get('report_sha256') or '待核验')+'；事实产物：'
           +str(dependency.get('cleaned_artifact_id') or '待核验')+'；评分产物：'
           +str(dependency.get('risk_artifact_id') or '待核验')+'。') if dependency else '依据报告产物及版本尚未绑定，实施前须核对本建议书所承接的报告。'
    proposal = f'''# {_cell(project.title)}：行业研究项目建议书

状态：待确认稿。范围、排期、投入人员、费用及验收条件须双方确认后实施；本稿不构成已确认报价。

## 1. 项目基本情况

本项目研究 {_cell(scope.get('industry_name') or project.target_name)}，用于 {_cell(scope.get('purpose') or '行业了解')}。后续工作以本轮报告的证据缺口为起点，明确需要补充的数据、交叉验证方式和预期判断价值。

{basis}

| 范围要素 | 本轮口径 |
| --- | --- |
| 纳入赛道 | {_cell(segments)} |
| 研究地域 | {_cell(scope.get('geography'))} |
| 数据截止日 | {_cell(scope.get('as_of_date'))} |
| 核心企业 | {_cell(companies)} |
| 资本市场 | {capital} |

{tables['project']}

## 2. 项目调研分析

{tables['methods']}

优先核验对决策影响大的缺口：规模统计是否同口径、关键政策是否仍适用、技术路线的性能与成本是否有可比数据、需求和商业化是否有原始披露支持。来源观点单独标注，预测必须列假设，企业样本不能替代行业整体统计。

本轮专项任务如下。完成标准为问题与原始资料逐项对应，形成可追溯结论，或明确保留缺证原因和下一步；不能以增加网页数量替代指标核验。

本章保留优先问题与完成条件；具体核验动作和所需材料见附录A，候选来源链接与原文位置见附录B。候选材料须先核验，不能直接作为评分依据。

{task_section}

## 3. 项目调研框架与主要研究范围

{tables['research']}

验收口径：市场表逐项注明期间、地域、定义、单位及实际或预测属性；技术比较注明同一测试条件和版本；每项判断能追溯至原始来源与证据编号。样本数量、赛道覆盖、修改轮次、确认人及确认日期在启动会书面确认，未确认不得以空表视为达标。无法取得的数据逐项记录原因，由双方决定补采、缩减范围或保留未知。行业代表样本比较不等于独立企业主体尽调；关闭的模块不列入交付。

## 4. 项目调研方法与渠道资源

{tables['resources']}

交叉验证记录原始链接、检索工具、数据期间、统计口径及证据编号。重复转载只计为同一原始来源。冲突数据分别呈现并说明差异，不以简单平均消除口径冲突。

## 5. 项目工作方法与周期安排

| 阶段 | 工作与成果 | 时间安排 |
| --- | --- | --- |
| 启动 | 确认用途、范围、重点企业、资料清单和验收标准 | 启动会确认 |
| 桌面研究 | 补充权威来源，清洗和核对市场、政策、技术数据 | 按资料可得性估算后确认 |
| 深度核验 | 对高优先级缺口执行数据库核验、专家及企业访谈 | 按渠道可联系性确认 |
| 复核交付 | 来源回溯、口径一致性检查、报告审阅和修改 | 与客户约定复核窗口 |

排期确认项：各阶段预计工作日、客户资料提供截止日、访谈等待上限、阶段负责人、验收确认人及修改轮次均须填入双方确认的工作计划。依赖材料或渠道延迟时，先书面说明影响和调整日期，再变更交付时间。

{tables['schedule']}

客户配合清单：确认研究范围与排除项、提供可共享资料及使用授权、指定资料/访谈联系人、确认受访对象与审批责任、按节点反馈复核意见。历史数据截止日保持上述口径；新增来源仅在其覆盖该截止日时使用，需扩展时间范围则另行确认。

{tables['deliverables']}

## 6. 项目团队安排

{tables['team']}

人员姓名、履历、从业经验、投入工时和可调用专家名单由项目启动时确认，当前不以角色占位声称已有确定人员。

## 7. 项目报价与保密条款

{tables['fees']}

{tables['terms']}

本建议书不生成未经报价确认的金额或折扣。数据库、专家和差旅未经预算批准不采购；客户追加范围先确认费用与工期。

无论双方最终是否形成委托，涉及委托方及其咨询业务的文字、声像、图片和其他载体资料均应按双方书面约定保密；未经书面许可不向第三方披露。数据保管、访问权限、使用期限、项目结束后的归档或删除方式，以及专家和访谈对象的保密责任应纳入合同或保密协议，由双方确认。

## 附录A 核验任务明细

{task_detail}

## 附录B 候选来源索引

{task_sources}
'''
    diagnostic = validate_proposal(proposal, scope, tasks)
    if not diagnostic['passed']:
        raise ValueError('industry_proposal_template_mismatch: ' + ', '.join(e['code'] for e in diagnostic['errors']))
    return proposal
