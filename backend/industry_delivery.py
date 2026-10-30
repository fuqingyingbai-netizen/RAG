"""Deterministic industry synthesis from validated artifacts, including reexports."""
import hashlib
import re

VERIFICATION_TASK_VERSION = 'industry-verification-v10-current-question-tasks'

# These are follow-up destinations, not permission to score a dimension.
RISK_TASK_SCOPE = {
    '政策与监管风险': ([3, 13, 14], ['policy']),
    '市场增长与需求风险': ([4, 5, 14], ['market_size', 'growth']),
    '竞争格局与集中度风险': ([6, 14], ['concentration', 'market_share']),
    '商业化与盈利模式风险': ([10, 14], ['pricing_model', 'profitability']),
    '技术迭代与替代风险': ([7, 14], ['technology_cost']),
    '资本热度与估值风险': ([8, 9, 14], ['capital']),
    '数据口径与证据可靠性风险': ([15, 14], []),
}


def verification_task_chapters(task):
    """Bind missing metrics by their structured requirement, even without a chapter."""
    chapters = {int(c) for c in (task.get('chapters') or ([task['chapter']] if task.get('chapter') else []))
                if str(c).isdigit()}
    if not chapters:
        chapters = {int(sub['chapter']) for sub in task.get('subtasks') or []
                    if isinstance(sub, dict) and str(sub.get('chapter')).isdigit()}
    requirements = set(task.get('requirement_ids') or [])
    if not chapters and requirements:
        for destinations, names in RISK_TASK_SCOPE.values():
            if requirements.intersection(names):
                chapters.update(c for c in destinations if c != 14)
    return sorted(chapters)


def _question_topic(topic):
    return re.sub(r'^结论支持复核\s*[：:]\s*', '', str(topic or '')).strip()


def consolidate_verification_tasks(tasks):
    """One current task per chapter/question; revisions remain audit data.

    This also normalizes saved legacy task lists on reexport. It never mutates
    the stored task input or interprets an old rejected claim as new evidence.
    Distinct defects, completion conditions and candidate references are kept
    together rather than emitted as another task for each attempted draft.
    """
    from copy import deepcopy
    result = []
    for original in tasks:
        if not isinstance(original, dict):
            continue
        task = deepcopy(original)
        task['chapters'] = verification_task_chapters(task)
        current = {}
        for source in task.get('subtasks') or []:
            if not isinstance(source, dict):
                continue
            sub = deepcopy(source)
            topic = _question_topic(sub.get('topic'))
            key = (sub.get('chapter'), topic)
            if key not in current:
                current[key] = {**sub, 'topic': topic, 'audit_merged_task_ids': [],
                                'audit_revision_history': [], 'issue_codes': [], 'review_reasons': []}
            target = current[key]
            for tid in [sub.get('task_id'), *sub.get('audit_merged_task_ids', [])]:
                if tid and tid not in target['audit_merged_task_ids']:
                    target['audit_merged_task_ids'].append(tid)
            for field in ('evidence_ids', 'issue_codes', 'review_reasons'):
                target.setdefault(field, [])
                target[field] = list(dict.fromkeys([*target[field], *(sub.get(field) or [])]))
            for event in sub.get('audit_revision_history') or []:
                if event not in target['audit_revision_history']:
                    target['audit_revision_history'].append(event)
            if str(sub.get('topic') or '').startswith('结论支持复核') or sub.get('support_review_required'):
                target['support_review_required'] = True
            if sub.get('status') in {'contradicted', 'unsupported', 'partial', 'uncertain'}:
                target['status'] = sub['status']
            # Different source/number corrections are one question with all of
            # its completion conditions, not silently discarded duplicate work.
            for field in ('completion', 'action', 'materials'):
                value = str(sub.get(field) or '').strip()
                old = str(target.get(field) or '').strip()
                if value and value not in old:
                    target[field] = (old + ' ' + value).strip()
        if task.get('subtasks') is not None:
            task['subtasks'] = list(current.values())
        result.append(task)
    return result


def _cell(value):
    return re.sub(r'\s+', ' ', str(value or '—')).replace('|', '/')


def review_reason_summary(reasons):
    """Group reader notices without truncating a reason or changing audit data."""
    chapters = sorted({r['chapter'] for r in reasons if r.get('code') == 'chapter_analysis_pending_review'
                       and isinstance(r.get('chapter'), int)})
    risks = list(dict.fromkeys(str(r['dimension']) for r in reasons
                              if r.get('code') == 'risk_assessment_incomplete' and r.get('dimension')))
    support = list(dict.fromkeys(str(r['dimension']) for r in reasons
                                if r.get('code') == 'risk_claim_support_pending' and r.get('dimension')))
    parts = []
    if chapters:
        parts.append('第' + '、'.join(map(str, chapters)) + '章分析结论待语义复核')
    if risks:
        parts.append('未完成风险评估：' + '、'.join(risks))
    if support:
        parts.append('风险初评的判断支持关系待复核：' + '、'.join(support))
    other = sum(r.get('code') not in {'chapter_analysis_pending_review', 'risk_assessment_incomplete', 'risk_claim_support_pending'} for r in reasons)
    if other:
        parts.append(f'另有{other}项证据或生成校验问题')
    return '；'.join(parts) + ('。完整原因及核验任务见报告质量诊断和第16章。' if parts else '')


def assessment_review_plan(cause, dimension=''):
    """Match the correction task to the rejected claim instead of buying more data."""
    if cause == 'claim_support_rejected':
        plans = {
            '政策与监管风险':(
                '核对具体义务的对象和适用场景，分别标出提供者、审查机构和地方政府职责；删除跨主体或跨场景的推论，执行效果另核验。',
                '所引政策原文、义务主体、适用范围、有效版本及本轮支持复核记录。',
                '条款、对象与适用范围逐项对应；文本义务与执行效果分开，未支持的影响判断收窄后重新评估。'),
            '市场增长与需求风险':(
                '对齐指标、地域、期间与数值性质，区分单期增长、下限值和持续需求判断；逐项核对评分推理。',
                '原始统计、比较符、期间与定义、预测属性及本轮支持复核记录。',
                '增长判断只覆盖有证据的期间和指标；不由两个下限或预测证明实际增长，复核后再评估。'),
            '竞争格局与集中度风险':(
                '分别核对玩家类型、样本排名、市场份额和集中度；人才与平台优势不直接证明准入壁垒。',
                '玩家分层原文、份额与分母、壁垒的直接材料及本轮支持复核记录。',
                '定性分层、量化集中度和进入壁垒分别有依据；未支持的行业格局判断收窄，不用企业数或样本代替份额。'),
            '商业化与盈利模式风险':(
                '区分所引材料未披露与行业整体未披露，核对收费方式、实际收入成本和盈利兑现之间的推理。',
                '原始收费及经营披露、行业与企业样本边界、本轮支持复核记录。',
                '收费机制不代替盈利结果；缺披露限定为本轮所引材料，不由统计缺口推导经营恶化。'),
            '技术迭代与替代风险':(
                '逐条绑定具体路线的优化目标、测试阶段和供应依赖；不同路线的性能、成本或自主性主张不能相互借用。',
                '路线原文、测试配置与阶段、依赖约束及本轮支持复核记录。',
                '路线、条件和推论一一对应；测试导入不等于规模部署，自主性讨论不直接证明供应受限。'),
            '数据口径与证据可靠性风险':(
                '分别复核原始出处与转载链、统计口径可比性和风险评级依据；字段完整或引用可定位不能证明评级可靠。',
                '原始报告及转载关系、统计方法、可比性对照和本轮支持复核记录。',
                '口径问题与真实经营风险分开，评级有独立适用依据；未完成校准和概率解释继续保留原限制。'),
        }
        return plans.get(dimension)
    if cause == 'ranking_source_missing':
        return ('回到排名正文或原始表，逐项核对主体、细分市场、统计期间、指标和名次；报告标题、发布消息和选样名单不能替代排名结果。',
                '原始排名表或完整正文、排序方法、统计期间和市场边界；本轮引用及评分诊断。',
                '排名结论有对应的授权原文后再独立评估；仍缺材料则删除排名判断并保留未知。')
    if cause in {'source_corroboration_overstated', 'numeric_corroboration_not_comparable'}:
        return (
            '逐项核对原始报告、发布方及转载关系；同一原始报告或同文转载合并计数。'
            '再对照指标定义、地域、期间、单位、数值性质及列示值；不同口径不能因数值相同而相互印证。',
            '原始报告署名和链接、转载链、逐项指标对照表、本轮评分输入和校验诊断。',
            '记录独立原始出处及指标可比性；未满足多源声明时删除该声明并重新评估，仍不足则保留未知。')
    if cause == 'absence_as_low_risk':
        return ('先核对具体监管义务、适用主体和执行材料；未见处罚只表示本轮没有取得相应材料，不能推出影响可控或风险较低。',
                '适用政策原文、履行记录、检查或处罚决定及检索范围。',
                '删除由未见处罚推导低风险的理由；取得直接影响证据后独立评估，否则保持未知。')
    if cause == 'growth_trend_not_comparable':
        return ('按同一指标、统计定义、地域、单位和历史期间建立时间序列；预测和估计单独列示，不用未来算力市场代替已实现的行业增长。',
                '历史统计原表、逐期定义与方法、预测假设及本轮评分输入。',
                '历史序列的可比性逐项通过后再评价增长趋势；否则删除持续增长判断并保留未知。')
    if cause == 'evidence_gap_as_business_risk':
        return ('先区分本轮缺少经营材料与已经发生的经营结果；核对真实收费、行业盈利统计或边界清楚的企业样本，不由未披露推导盈利恶化。',
                '原始收费与收入成本披露、统计期间、样本覆盖及盈利口径；本轮评分诊断单独保留。',
                '只有实际经营结果有直接证据时再独立评估；仍缺资料则保持未知，不把样本外推行业。')
    if cause in {'concentration_inference_unsupported', 'sample_extrapolation_unsupported'}:
        return ('先核对所引材料的行业边界、统计期和样本；定性分层可保留，集中度判断须另有份额、CR或HHI及分母。',
                '市场份额原表、统计分母、行业及地域范围、样本方法与本轮拒绝诊断。',
                '删除无指标支持的集中度或样本外推判断；适用指标和分母核验后独立评估，仍不足则保持未知。')
    if cause == 'internal_diagnostic_as_evidence':
        return ('移除内部字段和校验通过状态构成的评分理由；回到保存原文、统计方法及具体口径冲突实例，区分格式核验与研究真实性。',
                '原始报告和统计方法、逐项冲突或不可比记录、原文定位；内部诊断仅用于审计。',
                '评分理由不再依赖内部状态，只引用适用原始材料；没有实质可靠性证据时保留未知。')
    return None


def task_criteria(topic):
    """A test report, financial population and policy duty have different completion criteria."""
    if re.search(r'技术|测试|性能|单位成本|部署|迭代', topic):
        return ('核对原始测试报告，逐项对应路线、模型和软件版本、硬件配置、负载与测量方法；只在同条件下比较性能和成本。',
                '测试配置、模型与版本、负载、性能结果、计费或资源口径及原文定位。',
                '记录环境、版本、负载、测量方法、性能和单位成本；可比性逐项核对，不可比的分别列示，不据单一样本排序行业路线。')
    if re.search(r'盈利|收入|成本材料|付费|收费|商业化|变现|客户', topic):
        return ('先确认行业统计与企业样本的边界，再核对实际收费、真实付费、收入和成本披露；企业报告仅作为样本复核入口。',
                '原始财务与实际收费披露、统计期间、样本及分母、收入成本定义、实际回款或付费客户记录。',
                '实际收费、收入及成本有对应披露；说明样本选择和覆盖，企业结果不外推行业；行业盈利结论须另有适用总体资料。')
    if re.search(r'政策|监管|义务|施行|执行', topic):
        return ('按截止日核对原始文件、义务对象、适用范围及发布与施行日期；执行效果另核对检查或履行记录。',
                '政策原文、有效版本、发布及施行日期、适用主体、履行或执法材料。',
                '政策版本、日期、义务及对象对应原文；文件公布与实际执行效果分开，缺执行记录不推定低风险。')
    if re.search(r'预测|情景|触发|假设|前景', topic):
        return ('回到来源模型及方法，核对目标期、假设、情景和触发条件；历史预测不能充当实际值。',
                '原始预测报告、基期、目标期、假设与方法、触发变量和更新记录。',
                '目标期、基期及假设可定位，情景与实际值分开；缺模型或假设时只列来源观点，不补造预测金额。')
    if re.search(r'竞争|集中度|份额|玩家|五力|护城河', topic):
        return ('分别核对定性玩家分层与CR3/CR5、HHI或量化份额；记录细分市场、地域、统计期及分母，企业数不能替代集中度。',
                '原始玩家分类、市场份额表、CR或HHI定义、行业及地域范围、期间和分母。',
                '定性分层说明来源及历史期间；集中度只有取得适用数值与分母才形成判断，否则继续保留未知。')
    return None


def replace_chapter(report, number, title, body):
    section = f'## {number}. {title}\n\n{body.strip()}\n\n'
    pattern = rf'(?ms)^##\s*{number}[.、．][^\n]*\n.*?(?=^##\s*(?:\d+[.、．]|集中式待核验清单|报告编制说明)|\Z)'
    if re.search(pattern, report):
        return re.sub(pattern, lambda _: section, report, count=1)
    match = re.search(rf'(?m)^##\s*{number+1}[.、．]',report)
    pos = match.start() if match else len(report)
    return (report[:pos].rstrip()+'\n\n' if report[:pos].strip() else '') + section + report[pos:]


def _assessed_dimension(row):
    score = row.get('score')
    return (isinstance(score, (int, float)) and not isinstance(score, bool) and 0 <= score <= 100
            and row.get('level') in {'low', 'medium', 'high', 'critical'} and bool(row.get('evidence_ids')))


def _support_pending(row):
    return ('claim_support_review' in row and (row.get('claim_support_review') or {}).get('status') != 'supported')


def risk_status_section(risk, scope, title='综合评估'):
    from industry_research import active_risk_dimensions
    dimensions = {d.get('name'):d for d in (risk.get('dimensions') or []) if isinstance(d,dict)}
    rows, assessed, pending = [], 0, 0
    for name in active_risk_dimensions(scope):
        row = dimensions.get(name) or {}
        score = row.get('score')
        valid = _assessed_dimension(row)
        assessed += int(valid)
        pending += int(valid and _support_pending(row))
        refs = ' '.join(f'[{eid}]' for eid in row.get('evidence_ids',[])) if valid else '—'
        reason = row.get('reason') or '本轮尚未形成有效评估，保留未知。'
        label = {'low':'低','medium':'中','high':'高','critical':'严重'}.get(row.get('level'),'未知') if valid else '未知'
        rows.append('| '+' | '.join(map(_cell,(name,'初评待复核' if valid and _support_pending(row) else '已评估' if valid else '未完成评估',str(score) if valid else '未评分',label,reason,refs)))+' |')
    total = len(active_risk_dimensions(scope))
    overall = risk.get('overall_score') if assessed == total else None
    status = (f'本轮{total}个启用风险维度中，{assessed}项形成模型初评，{total-assessed}项未完成评估；其中{pending}项判断支持关系尚待复核。' if pending else
              f'本轮{total}个启用风险维度中，{assessed}项已评估，{total-assessed}项未完成评估。')
    return (f'## 14. {title}\n\n' + status
            + ('总分暂不计算。' if overall is None else f'模型风险'+('初评总分' if pending else '总分')+f'：{overall}（启用维度等权均值）。')
            + '评分尚未人工校准，不是风险概率；引用规则通过不等于判断已获语义证明。\n\n'
            '| 风险维度 | 评估状态 | 模型分值 | 风险等级 | 判断依据或未评分原因 | 证据编号 |\n'
            '| --- | --- | --- | --- | --- | --- |\n'+'\n'.join(rows)+'\n')


def verification_tasks(payload, risk, degradations, scope):
    """Prioritize structured deficiencies, never headings scraped from report prose."""
    from industry_research import active_risk_dimensions
    from industry_claims import industry_gap_plan
    tasks, keys = [], set()
    facts = {f.get('evidence_id'): f for f in payload.get('facts', []) if isinstance(f, dict) and f.get('evidence_id')}
    coverage = (payload.get('evidence_coverage') or {}).get('requirements', [])
    covered_requirements = set()

    def review_ids(ids):
        # References point to review material, never imply a rejected card now
        # supports a score. Unknown/unlocated/quarantined IDs stay in audit JSON.
        return list(dict.fromkeys(eid for eid in ids if isinstance(eid, str) and eid in facts
                       and facts[eid].get('eligible_for_report') is not False
                       and facts[eid].get('scope_match') == 'in_scope'
                       and not (scope.get('capital_market') == 'none' and facts[eid].get('evidence_scope') == 'capital_market')
                       and (facts[eid].get('provenance') or {}).get('locator', {}).get('status') == 'verified'))

    def review_reference(eid):
        fact = facts[eid]
        locator = (fact.get('provenance') or {}).get('locator') or {}
        return {'evidence_id':eid, 'title':fact.get('source_display_title') or fact.get('source_title') or '保存来源',
                'sample_boundary':(fact.get('fact_contract') or {}).get('sample_boundary') or '',
                'url':fact.get('source_url') or '', 'start':locator.get('start'), 'end':locator.get('end'),
                'body_sha256':locator.get('body_sha256')}

    def add(key,topic,reason,kind=None,chapter=None,task_type='evidence_gap',ids=(),chapters=(),requirements=(),candidate_count=None,reference_limit=6,validation_cause=''):
        if key in keys:return
        keys.add(key)
        _,action,priority,materials = industry_gap_plan(kind or topic)
        completion='取得适用原始材料，逐项记录期间、地域、定义及来源位置后复核；仍缺证时说明原因，继续保留未知。'
        criteria = task_criteria(topic)
        if criteria:
            action, materials, completion = criteria
        if task_type == 'assessment_validation':
            reason='当前评分未通过引用、数值或主张边界校验；这不等于行业经营恶化，也不能直接断定需要新增采购。'
            action='先对照已保存原文和授权指标，修正证据归属、数值及预测属性，再独立复核；确有资料缺口时再确认补采。'
            materials='本轮评分输入、已保存原文、授权指标与校验诊断；失败理由仅用于纠错，不作为事实。'
            completion='引用归属、单项指标和预测属性复核通过后再评估；未通过继续保留未知，不强行补分。'
            if validation_cause=='claim_support_rejected':
                reason='评分理由的支持关系未通过，需按本维度核对原文及推理；不表示行业经营恶化。'
            specific = assessment_review_plan(validation_cause,topic)
            if specific:
                action, materials, completion = specific
        elif task_type == 'assessment_abstained':
            reason='模型未给出有效评估；已有候选不等于指标已核验，须先区分可用材料与实际缺口。'
            action='先核对现有候选是否满足本维度指标；不足时再按下述要求补证。'+action
        elif task_type == 'input_selection_review':
            reason='全库有适用候选，但评分包未保留对应材料；这是选材问题，尚不能判定需要外部补采。'
            action='先复核本轮已保存事实的适用性，按维度与指标重新分配证据预算；包内材料仍不足时再确认补采。'
            materials='全库适用候选、实际评分包、维度保留计数及来源位置。'
            completion='记录全库与包内适用数，复核选材后再独立评估；不能仅凭候选数量恢复分值。'
        elif task_type == 'execution_failure':
            reason='本轮评估调用或执行未完成，尚不能据此判断资料不足。'
            action='先排查调用与执行诊断，确认失败原因；是否重新评估由用户决定，不自动追加请求或采购。'
            materials='本轮调用状态、执行诊断和已保存的评分输入。'
            completion='执行问题查明后由用户决定后续评估；未完成前保持未知，不把连接失败认作行业缺证。'
        elif task_type == 'generation_review':
            completion='按当前证据和评分修订对应章节，引用及结论边界检查通过，且与第14章状态一致；不足则继续标待复核。'
        all_refs = review_ids(ids)
        # A proposal needs a usable starting list, not a dump of every keyword
        # match. Preserve every candidate in audit metadata and disclose selection.
        from industry_research import source_document_key
        ranked=sorted(all_refs,key=lambda eid:(bool((facts[eid].get('fact_contract') or {}).get('sample_boundary')),
            facts[eid].get('claim_type')=='source_excerpt',
            (facts[eid].get('fact_contract') or {}).get('source_role') in {'opinion','commentary','performance_claim'},
            all_refs.index(eid)))
        refs=[]; documents=set()
        for eid in ranked:
            document=source_document_key(facts[eid].get('source_url') or '')
            if document in documents:continue
            refs.append(eid);documents.add(document)
            if len(refs)>=reference_limit:break
        for eid in ranked:
            if len(refs)>=reference_limit:break
            if eid not in refs:refs.append(eid)
        assigned_chapters = verification_task_chapters({'chapter':chapter, 'chapters':chapters,
                                                       'requirement_ids':requirements})
        tasks.append({'key':key,'task_id':'V-'+hashlib.sha256(key.encode()).hexdigest()[:8].upper(),
                      'version':VERIFICATION_TASK_VERSION,'task_type':task_type,'validation_cause':validation_cause,
                      'topic':topic,'reason':reason,'action':action,'priority':'高' if key.startswith('risk:') else priority,
                      'materials':materials,'chapter':chapter,'chapters':assigned_chapters,
                      'requirement_ids':sorted(set(requirements)), 'review_evidence_ids':refs,
                      'audit_review_evidence_ids':all_refs, 'review_candidate_count':len(all_refs),
                      'review_references':[review_reference(eid) for eid in refs],
                      'candidate_evidence_count':candidate_count,'completion':completion})
    for row in risk.get('dimensions') or []:
        if (row.get('name') not in active_risk_dimensions(scope) or row.get('score') is not None
                or row.get('applicable') is False or row.get('status') in {'disabled','not_applicable'}):continue
        chapters, reqs = RISK_TASK_SCOPE.get(row['name'], ([14], []))
        diagnostic = row.get('validation_diagnostic') or {}
        cause = row.get('unknown_cause') or ''
        primary_status = (risk.get('validation_diagnostics') or {}).get('primary_status')
        if primary_status in {'empty_or_invalid_json', 'request_failed', 'timeout', 'connection_error'} and not diagnostic:
            task_type='execution_failure'
        elif cause == 'evidence_budget_excluded':
            task_type='input_selection_review'
        elif cause == 'model_abstained':
            task_type='assessment_abstained'
        elif cause and cause not in {'no_applicable_evidence','assessment_unavailable'}:
            task_type=('assessment_validation' if cause in {'missing_model_citations','invalid_citations',
                       'invalid_reason_citations','unverified_reason_numbers','invalid_score'}
                       or diagnostic.get('original_score') is not None or diagnostic.get('semantic_issues')
                       else 'evidence_gap')
        else:
            task_type='evidence_gap'
        ids=list(diagnostic.get('admissible_evidence_ids') or [])
        for requirement in coverage:
            if requirement.get('requirement_id') in reqs:
                ids.extend(requirement.get('candidate_evidence_ids') or [])
        reason='本轮尚无适用且完成核验的行业评分证据；不表示该指标在行业中不存在。'
        if task_type == 'evidence_gap' and re.search(r'[\u4e00-\u9fff]', str(row.get('reason') or cause)):
            reason=str(row.get('reason') or cause)
        add('risk:'+row['name'],row['name'],reason,
            task_type=task_type,ids=ids,chapters=chapters,requirements=reqs,candidate_count=row.get('candidate_evidence_count'),validation_cause=cause)
        if cause=='claim_support_rejected':
            review=diagnostic.get('support_review') or row.get('claim_support_review') or {}
            tasks[-1]['support_review_diagnostic']={k:review[k] for k in ('status','reason','diagnostic_code') if k in review}
        covered_requirements.update(reqs)
    for row in coverage:
        if row.get('status')=='verified':continue
        if scope.get('capital_market')=='none' and row.get('module')=='投融资与资本市场':continue
        if row.get('requirement_id') in covered_requirements:continue
        add('metric:'+str(row.get('requirement_id')),str(row.get('question') or row.get('module')),
            '已有候选原文，但口径或适用性未核验。' if row.get('status')=='candidate' else '本轮保留的事实包尚无适用证据。',
            ids=row.get('candidate_evidence_ids') or [],requirements=[row['requirement_id']] if row.get('requirement_id') else [],
            candidate_count=len(row.get('candidate_evidence_ids') or []))
    synthesis_by_chapter = {}
    for note in degradations:
        if not isinstance(note,dict):continue
        chapter = note.get('chapter')
        if chapter in ({8,9} if scope.get('capital_market')=='none' else set()) or (chapter==12 and not scope.get('named_companies')):continue
        if note.get('review_type') == 'statement_synthesis_review':
            # Later notes describe the current chapter. Older attempts already
            # live in the plan/recovery journal and must not create more work.
            synthesis_by_chapter[chapter] = note
            continue
        add('chapter:'+str(chapter),'第'+str(chapter)+'章综合写作复核' if chapter else '报告综合写作复核',str(note.get('message') or '生成校验未完成'),
            kind='章节写作复核',chapter=chapter,task_type='generation_review',ids=note.get('evidence_ids') or [])
    synthesis = list(synthesis_by_chapter.values())
    if synthesis:
        chapters=sorted({n['chapter'] for n in synthesis if isinstance(n.get('chapter'),int)})
        ids=[eid for n in synthesis for eid in review_ids(n.get('evidence_ids') or [])[:2]]
        add('synthesis:source-statements','章节分析及研究缺口复核',
            '来源陈述编排已完成；尚需复核分析和章节问题，不属于模型执行失败。',
            task_type='synthesis_review',chapters=chapters,ids=ids,reference_limit=18)
        task=tasks[-1]
        task.update(priority='中',action='对照下列章节问题与已选原文，补齐有依据的分析；优先处理事实纠错、评分拒绝和缺证任务。不得用宏观规模填充竞争或技术比较。',
                    materials='对应章节、已选证据链接和材料覆盖表；不需要把全部章节作为失败任务重写。',
                    completion='逐章说明已回答的问题及仍缺的材料；有依据的判断通过复核，无依据的部分继续保留未知。',
                    chapter_questions=[{'chapter':n['chapter'],'coverage':n.get('content_coverage') or []} for n in synthesis])
        task['subtasks'] = []
        for n in synthesis:
            covered_questions = {}
            for number, question in enumerate(n.get('content_coverage') or [], 1):
                topic = str(question.get('question') or '')
                if not topic:
                    continue
                covered_questions[topic] = question
                if question.get('answer_verified') is True:
                    continue
                criteria = task_criteria(topic)
                completion = ('；'.join(question['criteria'])+'；逐项核对并记录适用范围及原文位置。'
                              if question.get('criteria') else criteria[2] if criteria else
                              '逐项核对所引材料与本问题的关系；有依据的分析经复核保留，缺少的材料明确登记。')
                question_key = f'{n["chapter"]}:{topic}'
                task['subtasks'].append({'task_id':task['task_id']+f'-C{n["chapter"]}-Q'+hashlib.sha256(question_key.encode()).hexdigest()[:8].upper(),
                    'question_id': question.get('question_id'),
                    'chapter':n['chapter'], 'topic':topic, 'status':question.get('evidence_state', question.get('status')),
                    'material_status':question.get('evidence_state', question.get('status')),
                    'evidence_ids':question.get('evidence_ids') or [],
                    'next_action': question.get('next_action'), 'claim_support_states': question.get('claim_support_states', []),
                    'model_revision_complete': question.get('model_revision_complete') is True,
                    'action': criteria[0] if criteria else '核对本题已选原文与当前判断，记录仍缺的条件及材料。',
                    'materials': criteria[1] if criteria else '本题当前正文、已选原文、来源位置及复核记录。',
                    'completion':completion})
            rejections = n.get('active_analysis_rejections', n.get('analysis_rejections', []))
            for number, rejection in enumerate(rejections, 1):
                if not rejection.get('support_review'): continue
                topic = _question_topic(rejection.get('question'))
                question = covered_questions.get(topic, {})
                if question.get('model_revision_complete') or question.get('answer_verified'):
                    continue
                review = rejection['support_review']
                reason = str(review.get('reason') or rejection.get('quality_reason') or '')
                issue_codes = list(dict.fromkeys(str(code) for code in rejection.get('issues', []) if isinstance(code, str)))
                criteria = task_criteria(topic)
                raw_ids = list(rejection.get('evidence_ids') or [])
                original = rejection.get('original_analysis')
                if isinstance(original, dict):
                    raw_ids += original.get('evidence_ids') or []
                task['subtasks'].append({'task_id': task['task_id']+f'-C{n["chapter"]}-R{number}',
                    'chapter': n['chapter'], 'topic': '结论支持复核：'+topic,
                    'status': rejection['support_review']['status'],
                    'evidence_ids':review_ids(raw_ids), 'issue_codes':issue_codes,
                    'review_reasons':[reason] if reason else [], 'support_review_required':True,
                    'audit_revision_history':[{'issue_codes':issue_codes, 'review':dict(review),
                        'claim_id':rejection.get('claim_id'), 'question':topic}],
                    'next_action': 'review_claim_support',
                    'action': criteria[0] if criteria else '对照已保存前提核对主体、期间、适用范围和推理缺口；先修正判断，确有资料缺口再补采。',
                    'materials': criteria[1] if criteria else '本题当前正文、原始出处与具体复核诊断。',
                    'completion': '对照已保存前提核对主体、期间、适用范围和推理缺口；先收窄或修正判断，确有材料缺口再确认补采。'})
    tasks = consolidate_verification_tasks(tasks)
    for task in tasks:
        for sub in task.get('subtasks') or []:
            sub['evidence_ids'] = review_ids(sub.get('evidence_ids') or [])
            sub['review_references'] = [review_reference(eid) for eid in sub['evidence_ids']]
    return tasks


def evaluation_inputs(payload):
    """Keep industry evaluation distinct from risk, without inventing a rating."""
    from industry_grounding import sample_boundary, complete_excerpt
    from industry_research import risk_fact_text, numeric_mentions, claim_semantic_issues
    from industry_fact_contracts import risk_admitted
    from industry_analysis import observed_business
    from industry_passages import policy_obligation
    from industry_grounding import passage_tasks
    groups=[('增长与需求','市场规模与增长'),('盈利与变现','商业模式与盈利逻辑'),
            ('政策支持与约束','政策与监管'),('技术与替代条件','技术路线对比')]
    lines=['### 行业评价输入与局限','',
        '行业吸引力不是风险分的倒数；以下仅列可追溯的评价输入，不给出未经独立验证的吸引力等级。企业样本不代替行业整体盈利，技术样本不代替行业技术成熟度。','',
        '| 评价方向 | 本轮可用输入 | 判断边界 |','| --- | --- | --- |']
    for label,module in groups:
        cards=[f for f in payload.get('facts',[]) if f.get('module')==module and f.get('eligible_for_report') is not False
               and risk_admitted(f, {'市场规模与增长':'市场增长与需求风险','商业模式与盈利逻辑':'商业化与盈利模式风险',
                    '政策与监管':'政策与监管风险','技术路线对比':'技术迭代与替代风险'}[module])
               and f.get('scope_match')=='in_scope' and not sample_boundary(f)
               and (f.get('provenance') or {}).get('locator',{}).get('status')=='verified'
               and (not numeric_mentions(str(f.get('fact') or '')) or (f.get('numeric_validation') or {}).get('passed') is True)
               and not claim_semantic_issues(risk_fact_text(f), [f])
               and not claim_semantic_issues(str(f.get('fact') or ''), [f])]
        if module == '技术路线对比':
            # A headline about a "breakthrough" is not an input about testing,
            # performance or cost. Keep it in its source chapter if admissible.
            cards = [f for f in cards if passage_tasks(f) & {'技术测试条件','技术性能','技术成本'}]
        def input_rank(fact):
            statement = (fact.get('fact_contract') or {}).get('statement') or risk_fact_text(fact)
            fit = (observed_business(fact) if module == '商业模式与盈利逻辑' else
                   bool(policy_obligation(statement)) if module == '政策与监管' else
                   '技术测试条件' in passage_tasks(fact) if module == '技术路线对比' else False)
            return (fit, (fact.get('numeric_validation') or {}).get('passed') is True,
                    (fact.get('numeric_context') or {}).get('is_forecast') is not True,
                    fact.get('claim_type') != 'source_excerpt')
        cards.sort(key=input_rank, reverse=True)
        if cards:
            card=cards[0]
            text=risk_fact_text(card)
            if len(text)>230:text=complete_excerpt(text,230)
            published = str(card.get('published_date') or '')
            if text and re.match(r'^20\d{2}-\d{2}-\d{2}(?:\b|T)', published):
                # "Currently" belongs to the dated source, not the report's
                # cutoff. Do not fill a missing publication date from scope.
                text = '来源发布：' + published[:10] + '；' + text
            value=(text+' ['+card['evidence_id']+']') if text else '较长原文需核对后再转述。'
            limit='来源表述及适用边界仍需复核；单项输入不能单独证明行业吸引力。'
        else:
            value='尚未取得适用于本方向的完整行业层输入。'
            limit='保留待核验，不把选证不足当作行业经营恶化，也不以样本填补整体判断。'
        lines.append('| '+' | '.join(map(_cell,(label,value,limit)))+' |')
    return '\n'.join(lines)+'\n'


def tasks_section(tasks, title='后续研究点'):
    from industry_reader import task_brief
    tasks = consolidate_verification_tasks(tasks)
    return ('## 16. '+title+'\n\n以下为待完成的核验任务；未表示已补搜、访谈或采购，也不预设人员、工期及费用。\n\n'
            +task_brief(tasks)+'\n')


def verification_task_table(tasks, include_reference_index=True, reference_index_only=False, reference_location='本节候选清单'):
    """One reader-facing task contract for the report and proposal.

    Review links are a route to inspect a candidate, not scoring citations.
    Keep six columns: adding provenance must not create unheaded note cells.
    """
    tasks = consolidate_verification_tasks(tasks)
    if not tasks:
        return '本轮未记录额外结构化核验任务，仍需人工核对原文和交付内容。'
    labels={'evidence_gap':'资料缺口','assessment_validation':'评分校验复核',
            'assessment_abstained':'评分弃评复核','execution_failure':'执行问题', 'generation_review':'章节复核',
            'synthesis_review':'分析复核'}
    rows=['| 核验任务 | 关联章节与候选证据 | 问题与处理类型 | 核验动作及材料 | 优先级 | 完成条件 |',
          '| --- | --- | --- | --- | --- | --- |']
    extra_references=[]
    linked_documents={}
    for task in tasks:
        chapters=task.get('chapters') or ([task['chapter']] if task.get('chapter') else [])
        links=('第'+'、'.join(map(str,chapters))+'章；') if chapters else ''
        ids=task.get('review_evidence_ids') or []
        if task.get('review_candidate_count',len(ids))>len(ids):
            links+='精选'+str(len(ids))+'/'+str(task['review_candidate_count'])+'个核验入口（全量编号保留于关联审计）；'
        refs={r['evidence_id']:r for r in task.get('review_references',[]) if r.get('evidence_id')}
        def reference(eid, with_title=False):
            ref=refs.get(eid,{})
            url=str(ref.get('url') or '')
            from industry_grounding import display_source_title
            label=eid+(' / '+display_source_title(ref.get('title')) if with_title else '')
            if with_title and ref.get('sample_boundary'):
                label+='（样本核查入口，非行业总体证据）'
            label=re.sub(r'[\[\]<>\\]', '', label).replace('|','/')
            if re.match(r'^https?://[^\s<>]+$',url):
                label='['+label+']('+url.replace('(','%28').replace(')','%29')+')'
            if with_title and ref.get('start') is not None:
                label+='；原文位置 '+str(ref['start'])+'–'+str(ref.get('end'))
                if ref.get('body_sha256'): label+=' / 指纹前缀 '+ref['body_sha256'][:12]
            return label
        if ids:
            links+='候选原文 '+ ' '.join(reference(eid) if eid in refs else '['+eid+']' for eid in ids[:3])
            # Every candidate has an offline title/link/locator entry. Grouping
            # by document avoids repeating a long title for every evidence ID.
            if refs:
                grouped={}
                for eid in ids:
                    ref=refs.get(eid,{})
                    grouped.setdefault((ref.get('url') or eid,ref.get('body_sha256') or ''),[]).append(eid)
                for group in grouped.values():
                    first=refs[group[0]]
                    document=linked_documents.setdefault((first.get('url') or group[0],first.get('body_sha256') or ''),{'tasks':set(),'refs':{}})
                    document['tasks'].add(str(task.get('task_id') or task.get('key')))
                    for eid in group:
                        ref=refs[eid]
                        position=('；位置 '+str(ref['start'])+'–'+str(ref.get('end'))) if ref.get('start') is not None else ''
                        if ref.get('body_sha256'):position+=' / 指纹前缀 '+ref['body_sha256'][:12]
                        document['refs'][eid]=(reference(eid,True),reference(eid)+position)
            if len(ids)>3:
                links+='；其余编号见'+reference_location+'。'
                if not refs:
                    for start in range(3,len(ids),8):
                        extra_references.append('| '+_cell(task.get('task_id') or task.get('key'))+' | '
                                                +' '.join('['+eid+']' for eid in ids[start:start+8])+' |')
        elif task.get('task_type') in {'assessment_validation','assessment_abstained','execution_failure'}:
            links+='先核对本轮评分输入的编号与原文定位，未登记可定位候选。'
        elif task.get('task_type') in {'generation_review','synthesis_review'}:
            links+='对应章节正文及来源索引，未登记可定位候选。'
        else:
            links+='尚无可定位候选编号，需补证或核对来源。'
        reason=labels.get(task.get('task_type'),'待复核')+'：'+task.get('reason','')
        fields=(str(task.get('task_id') or task.get('key') or '')+' '+task.get('topic',''),links,reason,
                task.get('action','')+' 所需材料：'+task.get('materials',''),task.get('priority','高'),
                task.get('completion') or '核对适用原文后复核；未取得材料时继续保留未知。')
        rows.append('| '+' | '.join(map(_cell,fields))+' |')
        for sub in task.get('subtasks') or []:
            state = '缺少适用材料' if sub.get('status') == 'missing' else '仅有背景材料' if sub.get('status') == 'background_only' else '材料及分析待复核'
            if sub.get('model_revision_complete'):
                state = '当前判断已完成模型修订，仍待人工确认'
            elif sub.get('support_review_required'):
                state = '结论支持复核：'+{'unsupported':'未获支持','contradicted':'与材料冲突',
                    'partial':'仅部分支持','uncertain':'支持关系未确定'}.get(sub.get('status'),'支持关系待确认')
            reasons = list(dict.fromkeys(sub.get('review_reasons') or []))
            details = '；'.join(reasons[:3])
            if len(reasons)>3:
                details += '；其余具体诊断见关联审计记录。'
            action = sub.get('action') or '核对本题当前判断及已选原文，按完成条件处理。'
            if details:
                action = '当前需修订：'+details+' '+action
            if sub.get('materials'):
                action += ' 所需材料：'+sub['materials']
            related = '第'+str(sub['chapter'])+'章；见本章材料覆盖表'
            if sub.get('evidence_ids'):
                sub_refs = {r['evidence_id']:r for r in sub.get('review_references') or [] if r.get('evidence_id')}
                refs.update(sub_refs)
                related += '；原文入口 '+' '.join(reference(eid) for eid in sub['evidence_ids'][:6])
                for eid, ref in sub_refs.items():
                    document=linked_documents.setdefault((ref.get('url') or eid,ref.get('body_sha256') or ''),{'tasks':set(),'refs':{}})
                    document['tasks'].add(str(sub['task_id']))
                    position=('；位置 '+str(ref['start'])+'–'+str(ref.get('end'))) if ref.get('start') is not None else ''
                    if ref.get('body_sha256'):position+=' / 指纹前缀 '+ref['body_sha256'][:12]
                    document['refs'][eid]=(reference(eid,True),reference(eid)+position)
            fields=(sub['task_id']+' '+sub['topic'], related, state, action, '中', sub['completion'])
            rows.append('| '+' | '.join(map(_cell,fields))+' |')
    for document in linked_documents.values():
        refs=list(document['refs'].values())
        for start in range(0,len(refs),8):
            batch=refs[start:start+8]
            extra_references.append('| '+'、'.join(sorted(document['tasks']))+' | '+_cell(batch[0][0])+'；'
                                    +' '.join(_cell(ref[1]) for ref in batch[1:])+' |')
    index = (['候选核验编号清单：仅为原文复核入口，不能直接作为评分依据。', '',
              '| 核验任务 | 其余候选编号 |', '| --- | --- |', *extra_references] if extra_references else [])
    if reference_index_only:
        return '\n'.join(index) or '本轮尚无已登记的候选来源索引。'
    if include_reference_index and index:
        rows += ['', *index]
    return '\n'.join(rows)


def reader_cleanup(report):
    """Remove only known generation metadata, keeping substantive reader prose."""
    lines=[]
    for line in report.splitlines():
        if re.match(r'^\s*(?:[-*>]\s*)?(?:image_urls|research_questions_status|information_gaps|named_companies)\s*[:：]',line):continue
        if re.fullmatch(r'\s*(?:\*\*)?[（(]?本章完[）)]?(?:\*\*)?\s*',line):continue
        if re.search(r'本章(?:仅|只).{0,12}\d+.{0,3}(?:条|项).{0,8}证据|证据包.{0,8}(?:预算|条数)',line) and not line.strip().startswith('|'):continue
        if not line.lstrip().startswith('#'):
            line=re.sub(r'#{3,6}\s*','',line)
        line=re.sub(r'research_questions_status(?:\[\d+\])?\s*[:：]?','研究问题',line)
        line=re.sub(r'information_gaps(?:\[\d+\])?\s*[:：]?','证据缺口',line)
        line=re.sub(r'\bimage_urls\s*[:：]\s*\[[^\]]*\]','',line)
        line=re.sub(r'\bnamed_companies\s*[:：]\s*\[[^\]]*\]','指定企业',line)
        line=re.sub(r'\bas_of_date\s*[:：]\s*', '资料截止日：', line)
        line=re.sub(r'(对象类型\s*[:：|]\s*)industry\b', r'\1行业', line)
        if '范围置信度' in line:
            line=re.sub(r'\b(?:medium|high|low)\b', lambda m:{'medium':'中','high':'高','low':'低'}[m[0]], line)
        lines.append(line)
    return '\n'.join(lines)


def refresh_summary_readiness(report, risk, degradations, scope):
    """Expose current decision limits in the summary, reserving whole prose units.

    This is generated status, not a model-authored conclusion. Reexports replace
    it using current artifacts; no old score or rejected reason is carried over.
    """
    from industry_research import active_risk_dimensions, summary_length
    match = re.search(r'(?ms)^##\s*1[.、．]\s*([^\n]+)\n(.*?)(?=^##\s*(?:[2-9]|1[0-6])[.、．]|\Z)', report)
    if not match:
        return report
    marker = '评估与使用边界：'
    paragraphs = [p for p in re.split(r'\n\s*\n', match[2].strip()) if p.strip()
                  and not p.lstrip().startswith(marker)]
    dimensions = {d.get('name'): d for d in (risk.get('dimensions') or []) if isinstance(d, dict)}
    unknown = [name for name in active_risk_dimensions(scope) if not _assessed_dimension(dimensions.get(name) or {})]
    pending = [n for n in degradations if isinstance(n.get('chapter'), int) and 1 <= n['chapter'] <= 14
               and not (n['chapter'] in {8, 9} and scope.get('capital_market') == 'none')
               and not (n['chapter'] == 12 and not scope.get('named_companies'))]
    parts = []
    if unknown:
        parts.append('未完成评估：' + '、'.join(unknown) + '；总分暂不计算')
    if any(_assessed_dimension(dimensions.get(name) or {}) and _support_pending(dimensions.get(name) or {})
           for name in active_risk_dimensions(scope)):
        parts.append('风险分为模型初评，判断支持关系尚待复核')
    if pending:
        parts.append('部分章节分析或生成结果待复核，具体原因及任务见第16章')
    notice = marker + '；'.join(parts) + '。' if parts else ''
    heading = f'## 1. {match[1].strip()}\n\n'
    kept = []
    for paragraph in paragraphs:
        candidate = '\n\n'.join(([notice] if notice else []) + kept + [paragraph])
        if summary_length(heading + candidate) <= 600:
            kept.append(paragraph)
    body = '\n\n'.join(([notice] if notice else []) + kept)
    return report[:match.start()] + heading + body + '\n\n' + report[match.end():]


def finalize_synthesis(report, payload, risk, degradations, scope, plans=None):
    titles={int(m[1]):m[2].strip() for m in re.finditer(r'^##\s*(\d+)[.、．]\s*([^\n]+)',report,re.M)}
    from industry_briefing import current_conclusions, conclusion_section, refresh_conclusion_summary
    claims = current_conclusions(report, payload, plans, scope)
    section=risk_status_section(risk,scope,titles.get(14,'综合评估'))
    # Keep the deterministic state matrix independently testable; present the
    # evidence-bound conclusions before it for the reader.
    if claims:
        header, body = section.split('\n', 1)
        section = header + '\n\n' + conclusion_section(claims) + '\n### 风险评估状态\n' + body
    section += '\n'+evaluation_inputs(payload)
    report=replace_chapter(report,14,titles.get(14,'综合评估'),section.split('\n',1)[1])
    notes=[]
    for note in degradations:
        item=dict(note)
        match=re.search(rf'(?ms)^##\s*{item.get("chapter")}[.、．][^\n]*\n(.*?)(?=^##\s*\d+[.、．]|\Z)',report)
        if match:
            actual_ids=list(dict.fromkeys(re.findall(r'\bE-[A-Z0-9-]{6,}\b',match[1],re.I)))
            # Moving analyses or tables must not reshuffle candidate entrances.
            # Keep prior priority only while the ID is still in the current body.
            retained=[eid for eid in item.get('evidence_ids', []) if eid in actual_ids]
            item['evidence_ids']=list(dict.fromkeys(retained+actual_ids))
        notes.append(item)
    tasks=verification_tasks(payload,risk,notes,scope)
    report=re.sub(r'(?ms)^## 集中式待核验清单\s*$.*\Z','',report).rstrip()
    section=tasks_section(tasks,titles.get(16,'后续研究点'))
    report=replace_chapter(report,16,titles.get(16,'后续研究点'),section.split('\n',1)[1])
    report=refresh_summary_readiness(report,risk,degradations,scope)
    report=refresh_conclusion_summary(report,claims,scope)
    return reader_cleanup(report),tasks


def risk_state_issues(report,risk,scope):
    """A synthesis must retain exactly the current risk artifact's full state."""
    match=re.search(r'(?ms)^##\s*14[.、．]\s*([^\n]+)\n(.*?)(?=^##\s*(?:\d+[.、．]|集中式待核验清单|报告编制说明)|\Z)',report)
    if not match:
        return ['第14章缺少与本轮风险产物同步的风险状态表。']
    expected=risk_status_section(risk,scope,match[1].strip()).strip()
    current=match[0].split('### 行业评价输入与局限',1)[0].strip()
    if '### 风险评估状态' in current:
        current = current.split('\n', 1)[0] + '\n\n' + current.split('### 风险评估状态', 1)[1].strip()
    return [] if current==expected else ['第14章评估状态、分值或未知原因未按本轮风险产物完整同步，应重建启用维度状态表。']
