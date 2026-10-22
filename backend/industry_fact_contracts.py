"""Industry fact admission and immutable statements, independent of LLM prose.

Located text is not semantic proof. This contract records a limited, reproducible
permission to quote a statement; it never certifies truth or calibrates a score.
The model can order statement IDs, but cannot edit their metrics or legal fields.
"""
from copy import deepcopy
import hashlib
import json
import re

VERSION = 'industry-fact-contract-v9-observed-inputs'
PLAN_VERSION = 'industry-statement-plan-v10-observed-inputs'

QUANTITY_TYPES = (
    ('growth', r'增速|增长速度|增长率|增幅|同比|环比|CAGR|复合.*增长'),
    ('ratio', r'占比|比例|份额|市占率|集中度|CR\d|毛利率|净利率|渗透率|成功率|准确率'),
    ('count', r'数量|企业数|公司数|机构数|专利数|论文数'),
    ('latency', r'延迟|时延|响应时间'),
    ('throughput', r'吞吐|token/s|每秒.*token'),
    ('amount', r'规模|收入|营收|金额|利润|估值|融资额|成本|单价|价格'),
)
TASK_PATTERNS = {
    'chain': r'上游.{0,180}中游.{0,180}下游',
    'competition': r'市场份额|市占率|集中度|CR\d|HHI|竞争对手|竞争压力|进入壁垒|迁移成本|替代竞争|价格战|厂商排名|前[三四五十]厂商|市场第一阵营|市场前[三四五十]',
    'technology': r'测试条件|测试环境|统一硬件|量化精度|吞吐量|token/s|推理延迟|响应延迟|首\s*token|推理成本|单位推理成本|技术替代|技术路线',
    'business': r'订阅|按量计费|付费客户|免费转(?:为)?付费|开始付费|续费|续约|回款|收费|收入结构|毛利率|净利率|盈利模式',
    'event': r'发布|推出|开源|签署|收购|施行|生效',
    'market': r'市场规模|产业规模|行业规模|需求|增长率|增速|增长速度|出货量',
    'capital': r'融资|估值|IPO|市盈率|市销率|成交额|换手率',
    'policy': r'管理办法|《办法》|条例|监管义务|准入要求|监管要求|行政处罚|标识要求|应当|不得|必须|禁止',
    'risk': r'风险|漏洞|攻击|欺诈|成本压力|价格战|技术替代|安全威胁',
}
CHAPTER_TASK = {2: 'chain', 3: 'policy', 4: 'market', 5: 'event', 6: 'competition',
                7: 'technology', 8: 'capital', 9: 'capital', 10: 'business', 11: 'forecast', 13: 'risk'}
GAPS = {
    'chain': '产业链主体、分工及上下游关系',
    'business': '收费机制、收入结构及盈利兑现',
    'market': '同口径规模、统计期间及需求趋势',
    'event': '事件主体、日期及事件记录；热度成因仍需传播数据',
    'competition': '竞争机制、份额及集中度口径；企业数量不能替代',
    'technology': '技术路线、测试条件、性能及单位成本；宏观规模不能替代',
    'capital': '融资、估值及市场交易的统计口径',
    'forecast': '预测来源、假设、情景及触发条件；不自建金额',
    'policy': '适用政策原文、发布和施行日期及执行材料',
    'risk': '具体风险机制、影响对象和对应证据；行业规模不能代替',
}


def quantity_type(metric):
    return next((kind for kind, pattern in QUANTITY_TYPES if re.search(pattern, str(metric), re.I)), 'other')


def _quote(fact):
    locator = (fact.get('provenance') or {}).get('locator') or {}
    return str(locator.get('quote') or fact.get('evidence_quote') or fact.get('fact') or '').strip()


def _role(fact, source_text):
    """A government host is not sufficient to identify a legal original."""
    title = str(fact.get('source_title') or '')
    header = title + '\n' + str(source_text or '')[:1400]
    declared = str(fact.get('claim_type') or '')
    if declared in {'opinion', 'commentary', 'viewpoint'} or re.search(r'个人观点|不作为投资依据|仅代表作者观点|行情复盘', header) or re.search(r'业绩确定性最高|弹性最大|笔者认为|我认为|比.{0,25}更能决定|成为.{0,40}核心指标|验证了.{0,20}可行性|如果说.{0,60}那么|细读财报不难发现|未来.{0,25}(?:企业|用户)可以|多数.{0,30}企业.{0,30}共同.{0,10}特征', _quote(fact)):
        return 'opinion'
    if re.search(r'解读|评论|访谈|红旗文稿|立法规范', header):
        return 'policy_commentary' if fact.get('module') == '政策与监管' else 'commentary'
    if (re.search(r'吞吐量.{0,10}(?:数倍|大幅)|(?:保持|不损失|不牺牲|不降低).{0,12}精度|普及率大幅', _quote(fact))
            and not all(re.search(p, _quote(fact), re.I) for p in (r'测试|实测', r'硬件|GPU|芯片|配置', r'模型|版本|负载'))):
        return 'performance_claim'
    from industry_claims import public_source_type
    official = public_source_type(fact.get('source_url')) in {'government', 'regulatory'}
    if (official and re.search(r'办法|条例|规定|法案|Regulation|Act', title, re.I)
            and re.search(r'第[一二三四五六七八九十百\d]+条|Article\s+\d+', source_text or _quote(fact), re.I)):
        return 'policy_primary'
    quote = re.sub(r'\s+', ' ', _quote(fact))
    from industry_passages import recommendation_context
    if recommendation_context(fact, source_text):
        return 'recommendation'
    if re.search(r'如果|倘若|假如|若(?:强行|采用|使用|缺乏)|当.{3,60}时[，,]', quote):
        return 'conditional_statement'
    if (re.search(r'^(?:对|对于).{1,20}[，,](?:推动|促进|引导|鼓励|探索)|应(?:当)?(?:推动|建立|完善)|建议|亟需|需(?:要)?(?:建立|完善|探索)|核心都是|生存法则', quote)):
        return 'recommendation'
    if not fact.get('numeric_context'):
        if re.match(r'^(?:推动|推进|落实|实施)[^。！？；;]{0,90}[，,]要(?:充分|积极|着力|坚持|发挥|加强|建立|完善)', quote):
            return 'recommendation'
        if (re.match(r'^(?:在)?未来[，,：:]', quote)
                and not re.search(r'已(?:经|实现|取得|完成)|目前|当前|实际(?:支付|收费)', quote)):
            return 'commentary'
    if (not fact.get('numeric_context')
            and re.search(r'(?:大幅|显著|极大地?)(?:降低|减少|提升|提高).{0,25}(?:门槛|功耗|吞吐|延迟|成本)', quote)
            and not all(re.search(p, quote, re.I) for p in (r'测试|实测', r'硬件|GPU|芯片|配置', r'模型|版本|负载'))):
        return 'performance_claim'
    if re.search(r'炒概念|兑现利润|景气度持续向上|深刻改变.{0,30}(?:底层逻辑|竞争格局)|形成.{0,25}双向反馈机制', quote):
        return 'commentary'
    if not fact.get('numeric_context') and re.search(r'有望|或将|预计|预期.{0,20}(?:增长|提升|扩大)|将(?:持续|进一步)?(?:增长|提升|扩大|成为)|(?:会|将)(?:根据|依据)[^。]{0,50}(?:探索|尝试|转向)', quote):
        return 'commentary'  # Qualitative outlook is not an observed industry result.
    return 'source_statement'


def build_contract(fact, scope=None, source_text=''):
    """Fail closed on ambiguous quantities; retain rejected input for audit."""
    scope = scope or {}
    quote = re.sub(r'\s+', ' ', _quote(fact))
    context = dict(fact.get('numeric_context') or {})
    if context:
        from industry_passages import numeric_temporal_attribute
        nature = numeric_temporal_attribute(quote, context.get('metric'), context.get('value'), str(context.get('unit') or ''))
        if (nature == 'estimate' and scope.get('as_of_date') and str(context.get('period') or '')[:4] > str(scope['as_of_date'])[:4]):
            nature = 'forecast'
        if nature:
            context.update(value_nature=nature, is_forecast=nature == 'forecast')
    role = _role(fact, source_text)
    from industry_passages import passage_issues, has_predicate
    issues = passage_issues(quote)
    locator=(fact.get('provenance') or {}).get('locator') or {}
    end=locator.get('end')
    start=locator.get('start')
    from industry_passages import source_prefix
    prefix = source_prefix(fact, source_text)
    if (re.match(r'[\u4e00-\u9fff]', quote)
            and re.search(r'(?:该|此|其)[\u4e00-\u9fff]{0,3}\s*\n\s*---\s*PDF\s+page\s+\d+\s*---\s*\n(?:[^\n]*\n){0,2}\s*\d*\s*$', prefix)):
        issues.append('cross_page_fragment')
    if source_text and isinstance(start,int) and 0<start<len(source_text):
        if (re.match(r'[\u4e00-\u9fffA-Za-z0-9]',quote)
                and re.match(r'[\u4e00-\u9fffA-Za-z0-9]',source_text[start-1])):
            issues.append('clipped_source_span')
    if source_text and isinstance(end,int) and end<len(source_text):
        following=source_text[end:].lstrip()[:1]
        if (re.search(r'[\u4e00-\u9fffA-Za-z0-9]$',quote)
                and re.match(r'[\u4e00-\u9fffA-Za-z0-9]',following)):
            issues.append('clipped_source_span')
    if not quote or len(quote) < 12 or re.match(r'^[，,。；;：:）)"”]|^[-+−]?\d+(?:\.\d+)?\s*[%％]', quote):
        issues.append('incomplete_proposition')
    if re.match(r'^(?:[一二三四五六七八九十]+[、.]|[（(]?\d+[.、）)])', quote) and not re.search(r'为|是|采用|达到|增长|下降|包括|显示|表明|推出', quote):
        issues.append('heading_only')
    if re.search(r'image_urls|vision_text|research_questions_status', quote, re.I):
        issues.append('metadata_fragment')
    kind = quantity_type(context.get('metric') or '') if context else 'qualitative'
    comparator, period = '=', str(context.get('period') or '')
    if context:
        value, unit = str(context.get('value') if context.get('value') is not None else ''), str(context.get('unit') or '')
        percent = unit in {'%', '％', '百分点'}
        if ((kind in {'growth', 'ratio'} and not percent) or
                (kind in {'count', 'latency', 'throughput'} and percent) or
                (kind == 'amount' and percent)):
            issues.append('metric_unit_conflict')
        # Local words between the metric and its value outrank a distant label.
        from industry_grounding import metric_endpoint_period
        endpoint = metric_endpoint_period(quote, context.get('metric'), value, unit)
        metric = re.escape(str(context.get('metric') or ''))
        paired = re.search(metric + r'([^。；;\n]{0,60}?)' + re.escape(value) + r'\s*' + re.escape(unit), quote) if value and metric else None
        if not paired:
            issues.append('metric_value_pair_missing')
        from industry_research import numeric_mentions, number_key
        allowed_number = number_key(value + unit)
        if any(number_key(n) != allowed_number for n in numeric_mentions(str(context.get('definition') or ''))):
            issues.append('definition_has_unauthorized_quantity')
        if paired:
            local_kind = quantity_type(paired[1])
            if local_kind != 'other' and local_kind != kind and not endpoint:
                issues.append('metric_binding_conflict')
            suffix = quote[paired.end():paired.end()+3]
            prefix = paired[1]
            if suffix.startswith(('以上', '及以上')): comparator = '>='
            elif suffix.startswith(('以下', '及以下')): comparator = '<='
            elif re.search(r'超过|大于|高于|突破|逾|超(?!过)', prefix): comparator = '>'
            elif re.search(r'不足|低于|少于', prefix): comparator = '<'
            elif re.search(r'约|大约|近', prefix): comparator = 'approx'
        ranges = re.findall(r'(20\d{2})\s*(?:年)?\s*[-—–至到]\s*(20\d{2})\s*年?', quote)
        if ranges:
            interval = next((a+'—'+b for a, b in ranges if a in period or b in period), '')
            if interval:
                # Preserve the source interval; never promote its last year.
                period = endpoint or interval
        from industry_grounding import metric_period_region
        source_period, _ = metric_period_region(quote, str(context.get('metric') or ''), value, unit)
        if source_period:
            # Time is anchored before this amount, not any four digits in it.
            if endpoint or not ranges or not any(a in period and b in period for a,b in ranges):
                period = source_period
        else:
            issues.append('statistical_period_unlocated')
        if (fact.get('numeric_validation') or {}).get('passed') is not True:
            issues.append('numeric_context_unvalidated')
    else:
        from industry_research import numeric_mentions
        if numeric_mentions(quote):
            issues.append('untyped_quantity')
        if not has_predicate(quote):
            issues.append('topic_without_proposition')
    tasks = {task for task, pattern in TASK_PATTERNS.items() if re.search(pattern, quote, re.I)}
    if context.get('is_forecast') is True: tasks.add('forecast')
    if fact.get('module') == '政策与监管':
        subjects = [scope.get('industry_name'), *scope.get('segments', [])]
        # Document titles cannot make every paragraph in a filing applicable.
        local_subject = any(str(s).lower() in quote.lower() for s in subjects if s)
        local_subject |= bool(re.search(r'人工智能|\bAI\b', quote, re.I))
        if not local_subject and subjects and any(subjects): issues.append('local_subject_missing')
        if role != 'policy_primary' and re.search(r'罚款|处罚|营业额|第.{1,8}条|施行日期', quote):
            issues.append('legal_original_required')
    if kind in {'amount', 'count'}:
        # A module label cannot turn a market size/count into a tech/competition measurement.
        tasks.discard('competition')
        if not re.search(r'推理|训练|测试|硬件|芯片|模型|算法', str(context.get('metric') or '')):
            tasks.discard('technology')
    # A market amount does not acquire a regulatory mechanism from its module
    # or the source headline. Only the permitted proposition is examined.
    if context and re.search(r'市场规模|产业规模|收入|营收|企业数', str(context.get('metric') or '')):
        tasks.discard('policy')
        tasks.discard('risk')
    if context and kind != 'other' and 'event' in tasks:
        tasks.discard('event')
    from industry_grounding import sample_boundary
    boundary = sample_boundary(fact)
    # An anaphoric passage can refer to a named installation on the preceding
    # PDF page. Its industry-report headline does not make the case universal.
    if not boundary and re.match(r'^(?:该|其|这一|算集群)', quote):
        sample_prefix = re.sub(r'\s+', '', prefix)
        if re.search(r'[\u4e00-\u9fffA-Za-z]{2,24}(?:智算集群|算力平台|服务平台|数据中心)(?:已于|已经|已|于)', sample_prefix):
            boundary = '具名部署或平台样本，仅适用于对应条件，不能外推行业整体'
    subject=re.match(r'^([\u4e00-\u9fffA-Za-z]{2,12})在',quote)
    if (not boundary and subject and subject[1] not in {'中国','我国','全球','行业','市场','企业','该行业','消费者','供应商'}
            and not any(str(s) and str(s) in subject[1] for s in [scope.get('industry_name'),*scope.get('segments',[])])):
        boundary='单一主体观察，仅作为样本，不外推行业整体'
    located = (fact.get('provenance') or {}).get('locator', {}).get('status') == 'verified'
    admitted = not issues and located and fact.get('scope_match') == 'in_scope' and fact.get('eligible_for_report') is not False
    statement = ''
    if admitted:
        if context:
            symbol = {'=':'', '>=':'不少于', '<=':'不超过', '>':'超过', '<':'低于', 'approx':'约'}[comparator]
            nature = ('预测/目标值' if context.get('is_forecast') is True else '来源估计值'
                      if context.get('value_nature') == 'estimate' else '历史基期值'
                      if context.get('value_nature') == 'historical_base' else '来源报告值')
            statement = (f'{nature}：{period} {context.get("geography", "")} {context.get("metric", "")}：'
                         f'{symbol}{context.get("value", "")}{context.get("unit", "")}；口径：{context.get("definition", "")}。')
        else:
            from industry_grounding import display_text
            from industry_passages import reader_proposition
            statement = display_text(reader_proposition(re.sub(r'\s+', ' ', quote)))
            if not re.search(r'[。！？][”」"]?$', statement):
                statement += '。'
        from industry_grounding import display_text
        statement = display_text(statement)
        if role in {'opinion', 'commentary'}: statement = '来源观点（未作事实认定）：' + statement
        if role == 'policy_commentary': statement = '政策解读（须核对原文）：' + statement
        if role == 'performance_claim': statement = '来源性能主张（测试条件未核验）：' + statement
        if role == 'conditional_statement': statement = '来源条件性陈述（不能视为普遍实测结论）：' + statement
        if role == 'recommendation': statement = '来源建议或机制设想（非已实现经营结果）：' + statement
        if boundary:
            statement = statement.replace('行业平均', '代表企业样本平均')
            statement = '样本观察（不能外推行业整体）：' + statement
        # A source's own unsupported inference must not bypass the same narrow
        # claim checks used on written prose merely because the model selects IDs.
        from industry_research import claim_semantic_issues
        checked_fact={**fact,'numeric_context':{**context,'period':period,'comparator':comparator}} if context else fact
        claim_issues=claim_semantic_issues(statement,[checked_fact])
        if claim_issues:
            issues.extend('claim_'+i['code'] for i in claim_issues)
            admitted=False
            statement=''
    subjects = [str(s).strip().lower() for s in [scope.get('industry_name'), *scope.get('segments', [])] if s]
    local_subject = not subjects or any(s in quote.lower() for s in subjects)
    if any('人工智能' in s for s in subjects):
        local_subject |= bool(re.search(r'(?<![A-Za-z])AI(?![A-Za-z])', quote, re.I))
    summary_background = ''
    if not context and re.search(r'(?:发布|发表|公布)(?:了)?《[^》]+》(?:报告|白皮书|研究)[。]?$|(?:发布|发表)(?:了)?《[^》]*(?:报告|白皮书)》[。]?$', quote):
        summary_background = 'report_publication_only'
    actor = re.match(r'^(?:第[一二三四五六七八九十百\d]+条\s*)?((?:服务中心|审查机构|复核机构|审查委员会)[^。；;]{0,25}?)(?:应当|不得|必须)', quote)
    if role == 'policy_primary' and actor and not re.search(r'提供者|开发者|运营者|用户|企业', actor[1]):
        summary_background = 'institutional_review_procedure'
    if role == 'policy_primary':
        from industry_passages import policy_purpose_or_principle
        if policy_purpose_or_principle(quote):
            summary_background = 'policy_principle_or_purpose'
    material_kind = ('sample' if boundary else 'conditional' if role == 'conditional_statement'
        else 'proposal' if role == 'recommendation' else 'opinion' if role in {'opinion','commentary','policy_commentary'}
        else 'proposal' if re.search(r'有望|可以按|将有|拟(?:采用|推出)|(?:在)?未来[，,：:]|未来.{0,35}(?:将|应当|应该|在于|能够)', quote) and not context
        else 'reported')
    return {'version': VERSION, 'quantity_type': kind, 'source_role': role, 'comparator': comparator,
            'summary_subject_present': local_subject, 'summary_background_reason': summary_background,
            'period': period, 'tasks': sorted(tasks), 'issues': list(dict.fromkeys(issues)),
            'sample_boundary':boundary, 'value_nature': context.get('value_nature'),
            'material_kind': material_kind,
            'report_admitted': admitted, 'risk_admitted': admitted and not boundary and material_kind not in {'proposal','opinion','conditional'} and summary_background not in {'institutional_review_procedure', 'policy_principle_or_purpose'} and role not in {'opinion', 'commentary', 'policy_commentary', 'performance_claim', 'conditional_statement', 'recommendation'},
            'statement': statement, 'statement_sha256': hashlib.sha256(statement.encode()).hexdigest(),
            'semantic_status': 'not_evaluated'}


def attach_contract(fact, scope=None, source_text=''):
    item = deepcopy(fact)
    item['fact_contract'] = build_contract(item, scope, source_text)
    if item.get('numeric_context'):
        item['numeric_context'].update(period=item['fact_contract']['period'], comparator=item['fact_contract']['comparator'])
        if item['fact_contract'].get('value_nature'):
            item['numeric_context'].update(value_nature=item['fact_contract']['value_nature'],
                                          is_forecast=item['fact_contract']['value_nature'] == 'forecast')
    if not item['fact_contract']['report_admitted']:
        item.update(eligible_for_report=False, eligible_for_risk_scoring=False, requires_human_review=True)
    elif not item['fact_contract']['risk_admitted']:
        item['eligible_for_risk_scoring'] = False
    return item


def chapter_admitted(fact, index):
    contract = fact.get('fact_contract')
    if not contract: return True  # Historical artifacts are handled by legacy rules, never silently upgraded.
    if not contract.get('report_admitted'): return False
    if index == 6 and contract.get('summary_background_reason') == 'report_publication_only': return False
    if index in {1, 14} and (contract.get('material_kind') in {'proposal','opinion','conditional'} or contract['source_role'] in {'opinion', 'commentary', 'policy_commentary', 'performance_claim', 'conditional_statement', 'recommendation'}): return False
    if index == 1:
        from industry_grounding import sample_boundary
        from industry_passages import passage_issues
        # Recheck historical contracts too: an old admission flag cannot make
        # company publicity or a clipped web snippet eligible for a new summary.
        if (contract.get('summary_subject_present') is False or contract.get('summary_background_reason') or contract.get('sample_boundary')
                or sample_boundary(fact) or passage_issues(_quote(fact))):
            return False
    task = CHAPTER_TASK.get(index)
    if index == 13: return bool({'risk', 'policy'} & set(contract['tasks']))
    if index == 5:
        return ('event' in contract['tasks'] and bool(re.search(r'20\d{2}\s*年\s*\d{1,2}\s*月', _quote(fact))))
    return not task or task in contract['tasks']


CHAPTER_QUESTIONS = {
    2: [('产业链主体和分层关系', r'上游.{0,180}中游.{0,180}下游')],
    3: [('适用政策原文', 'primary'), ('义务主体及具体要求', r'应当|不得|必须|禁止'), ('发布与施行日期', r'(?:发布|施行|生效).{0,8}20\d{2}|20\d{2}.{0,12}(?:发布|施行|生效)'), ('实际执行材料', r'处罚决定|检查结果|已.{0,8}(?:处罚|查处)')],
    4: [('规模、期间和统计口径', 'amount'), ('同口径增长趋势', 'growth')],
    5: [('有日期的主体事件', r'20\d{2}\s*年\s*\d{1,2}\s*月'), ('传播或关注度数据', r'搜索指数|讨论量|曝光量|传播量')],
    6: [('竞争机制与玩家分层', r'迁移成本|进入壁垒|价格战|竞争压力|竞争派系|厂商排名|前[三四五十]厂商|市场第一阵营|市场前[三四五十]'), ('份额及集中度', r'市场份额|市占率|CR\d|HHI|集中度')],
    7: [('同条件测试配置', r'测试环境|统一硬件|量化精度|测试条件'), ('可核验性能及单位成本', 'technical_measurement')],
    10: [('实际收费与付费客户', r'订阅|按量计费|付费客户|续约|回款'), ('盈利及收入成本材料', r'毛利率|净利率|营业收入|收入结构|成本定义')],
    11: [('来源预测与目标期间', 'forecast'), ('来源假设和情景条件', r'假设|基准情景|情景假设'), ('可跟踪触发条件', r'触发条件|阈值|前提条件')],
    13: [('风险机制及作用对象', r'风险|漏洞|攻击|欺诈|成本压力|价格战|技术替代'), ('监管义务或执行材料', r'应当|不得|处罚决定|检查结果')],
}


def chapter_coverage(package, index, ids):
    """Presence of relevant material is distinct from a verified answer."""
    cards = [f for f in package.get('facts', []) if f.get('evidence_id') in ids and chapter_admitted(f, index)]
    rows = []
    for question, pattern in CHAPTER_QUESTIONS.get(index, []):
        matched, background = [], []
        for fact in cards:
            c = fact['fact_contract']; ctx = fact.get('numeric_context') or {}
            if pattern == 'primary': ok = c['source_role'] == 'policy_primary'
            elif question in {'义务主体及具体要求', '监管义务或执行材料'}:
                from industry_passages import policy_obligation
                ok = c['source_role'] == 'policy_primary' and bool(policy_obligation(_quote(fact)) or re.search(r'处罚决定|检查结果', _quote(fact)))
            elif pattern == 'amount': ok = c['quantity_type'] == 'amount'
            elif pattern == 'growth': ok = c['quantity_type'] == 'growth'
            elif pattern == 'forecast': ok = ctx.get('is_forecast') is True
            elif pattern == 'technical_measurement':
                ok = (c['quantity_type'] in {'throughput', 'latency', 'amount'} and 'technology' in c['tasks']
                      and all(re.search(p, _quote(fact), re.I) for p in (r'实测|测试', r'GPU|硬件|配置', r'模型|版本|负载')))
            elif question == '实际收费与付费客户':
                from industry_analysis import observed_business
                ok = observed_business(fact)
            elif question == '同条件测试配置':
                ok=(c['source_role']!='performance_claim' and bool(re.search(r'统一硬件|相同模型|测试条件.{0,4}(?:为|[:：])|硬件配置|GPU型号|测试负载',_quote(fact),re.I)))
            elif question == '份额及集中度':
                ok = ((fact.get('numeric_validation') or {}).get('passed') is True
                      and bool(re.search(r'市场份额|市占率|集中度|CR\d|HHI', str(ctx.get('metric') or ''), re.I))
                      and bool(ctx.get('period') and ctx.get('geography') and ctx.get('definition'))
                      and not c.get('sample_boundary') and c.get('risk_admitted') is True)
                if not ok and re.search(pattern, re.sub(r'《[^》]+》', '', _quote(fact)), re.I):
                    background.append(fact['evidence_id'])
            else: ok = bool(re.search(pattern, _quote(fact), re.I))
            if ok:
                matched.append(fact['evidence_id'])
            elif question == '实际收费与付费客户' and 'business' in c['tasks']:
                background.append(fact['evidence_id'])
        rows.append({'question': question, 'evidence_ids': matched, 'background_evidence_ids': background,
                     'status': 'source_material_pending_review' if matched else 'background_only' if background else 'missing'})
    return rows


def risk_admitted(fact, dimension):
    contract = fact.get('fact_contract')
    if not contract: return True
    if not contract.get('risk_admitted'): return False
    task = {'政策与监管风险':'policy', '市场增长与需求风险':'market', '竞争格局与集中度风险':'competition',
            '商业化与盈利模式风险':'business', '技术迭代与替代风险':'technology', '资本热度与估值风险':'capital'}.get(dimension)
    return not task or task in contract['tasks']


def plan_prompt(package, index):
    cards = [{'id': f['evidence_id'], 'statement': f['fact_contract']['statement'],
              'tasks': f['fact_contract']['tasks']} for f in package.get('facts', []) if chapter_admitted(f, index)]
    return ('你仅编排不可改写的来源陈述。返回严格JSON：{"evidence_ids":["E-..."]}，最多8项；'
            '只选本章任务适用、互不重复的项。不要返回标题、正文、数值或新增结论。'
            '无适用项返回空列表。模型不负责重述指标、替换口径或确认法律。\n'
            + json.dumps({'chapter': index, 'task': GAPS.get(CHAPTER_TASK.get(index), '可引用来源陈述'), 'cards': cards}, ensure_ascii=False))


def statement_markdown(statement):
    """Source punctuation cannot create headings, tables, HTML or hidden links."""
    import html
    statement = html.escape(re.sub(r'\s+', ' ', statement), quote=False)
    return re.sub(r'([\\`*\[\]|])', r'\\\1', statement)


def parse_plan(text, package, index):
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip(), flags=re.I)
    plan = json.loads(text)
    if not isinstance(plan, dict) or set(plan) != {'evidence_ids'} or not isinstance(plan['evidence_ids'], list):
        raise ValueError('invalid_statement_plan')
    allowed = {f['evidence_id'] for f in package.get('facts', []) if chapter_admitted(f, index)}
    ids = plan['evidence_ids']
    if len(ids) > 8 or any(not isinstance(eid, str) or eid not in allowed for eid in ids) or len(set(ids)) != len(ids):
        raise ValueError('unauthorized_statement_plan')
    if allowed and not ids: raise ValueError('empty_statement_plan')
    return ids


def render_plan(package, index, title, ids):
    cards = {f['evidence_id']: f for f in package.get('facts', []) if chapter_admitted(f, index)
             and (index != 1 or f.get('summary_lineage'))}
    lines, seen = [], set()
    for eid in ids:
        if eid not in cards: raise ValueError('unauthorized_statement_plan')
        fact = cards[eid]
        statement = fact['fact_contract']['statement']
        if statement in seen: continue
        seen.add(statement)
        lines.append('- ' + statement_markdown(statement) + f' [{eid}]({fact.get("source_url", "")})')
    if index in {4, 11}:
        from industry_analysis import market_table
        table, numeric_ids = market_table([cards[eid] for eid in ids if eid in cards],
            (package.get('industry_scope') or {}).get('as_of_date') if index == 11 else None)
        if table:
            lines = [table] + [line for line in lines if not any(' [' + eid + '](' in line for eid in numeric_ids)]
    task = CHAPTER_TASK.get(index)
    note = ('本章列示已准入陈述及材料支持的比较和边界分析；分析结论仍待语义复核。'
            + ('需核验：' + GAPS[task] + '。' if task else ''))
    if index == 1:
        # Whole statements only: no model expansion, mid-sentence clipping or raw-card fallback.
        from industry_research import summary_length
        header = f'## 1. {title}\n\n'
        body = '以下摘自已完成章节的准入陈述；整体判断仍待复核。\n\n'
        for line in lines:
            if summary_length(header + body + line) <= 600: body += line + '\n\n'
        return header + body.strip()
    coverage = chapter_coverage(package, index, ids)
    matrix = ''
    if coverage:
        matrix = '\n\n### 材料覆盖与研究缺口\n\n| 本章研究问题 | 当前材料 | 研究状态 |\n| --- | --- | --- |\n'
        for row in coverage:
            matched = ' '.join('['+eid+']' for eid in row['evidence_ids'])
            background = ' '.join('['+eid+']' for eid in row.get('background_evidence_ids', []))
            refs = ('对应材料：' + matched if matched else '')
            if background:
                refs += ('；' if refs else '') + '背景材料（未回答本问题）：' + background
            refs = refs or '尚无适用材料'
            state = ('有来源材料，适用性与结论支持仍需复核' if row['evidence_ids'] else
                     ('仅有模式或观点背景，实际经营指标仍缺证' if index == 10 else
                      '仅有定性描述或观点背景，尚无已核验的可比指标') if row.get('background_evidence_ids') else '本轮未回答，需补证或缩减研究范围')
            matrix += f'| {row["question"]} | {refs} | {state} |\n'
    from industry_analysis import chapter_analysis
    return f'## {index}. {title}\n\n' + note + '\n\n' + ('\n\n'.join(lines) or '本章尚无满足准入条件的完整陈述，相关核验事项见第16章。') + chapter_analysis(package, index, ids) + matrix
