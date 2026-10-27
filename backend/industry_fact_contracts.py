"""Industry fact admission and immutable statements, independent of LLM prose.

Located text is not semantic proof. This contract records a limited, reproducible
permission to quote a statement; it never certifies truth or calibrates a score.
The model can order statement IDs, but cannot edit their metrics or legal fields.
"""
from copy import deepcopy
import hashlib
import json
import re

VERSION = 'industry-fact-contract-v11-analysis-boundaries'
PLAN_VERSION = 'industry-statement-plan-v16-evidence-proportional-body'

PLAYER_LAYER_PATTERN = r'竞争派系|(?:参与者|玩家|厂商).{0,18}(?:分为|分成|分层)|头部.{0,30}(?:腰部|初创|海外)'

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
    'competition': r'市场份额|市占率|集中度|CR\d|HHI|竞争对手|竞争压力|进入壁垒|迁移成本|替代竞争|价格战|厂商排名|前[三四五十]厂商|市场第一阵营|市场前[三四五十]|' + PLAYER_LAYER_PATTERN,
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
    if declared in {'opinion', 'commentary', 'viewpoint'} or re.search(r'个人观点|不作为投资依据|仅代表作者观点|行情复盘', header) or re.search(r'业绩确定性最高|弹性最大|笔者认为|我认为|比.{0,25}更能决定|比.{0,25}更有意义|成为.{0,40}核心指标|验证了.{0,20}可行性|如果说.{0,60}那么|细读财报不难发现|未来.{0,25}(?:企业|用户)可以|多数.{0,30}企业.{0,30}共同.{0,10}特征', _quote(fact)):
        return 'opinion'
    if re.search(r'解读|评论|访谈|红旗文稿|立法规范', header):
        return 'policy_commentary' if fact.get('module') == '政策与监管' else 'commentary'
    if (re.search(r'吞吐量.{0,10}(?:数倍|大幅)|(?:保持|不损失|不牺牲|不降低).{0,12}精度|普及率大幅|(?:延迟|时延).{0,8}(?:降低|缩短|降至|降到).{0,8}(?:毫秒级|微秒级)', re.sub(r'\s+', '', _quote(fact)))
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
    boundary = sample_boundary(fact, source_text)
    if not boundary and re.match(r'^(?:相关)?上市(?:公司|企业).{0,12}(?:回款|现金流|毛利|营收|净利)', quote):
        boundary = '上市企业经营样本，不能外推行业整体'
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
            historical = re.search(r'(?:根据|据)《[^》]{2,100}?[（(](20\d{2})[）)][^》]*》', quote)
            if historical and str(scope.get('as_of_date') or '')[:4] > historical[1]:
                period = historical[1]
                statement = f'历史来源观察（{period}年口径）：' + statement
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
    from industry_grounding import resolved_source_title
    display_title = resolved_source_title(item, source_text)
    if display_title != item.get('source_title'):
        item['source_display_title'] = display_title
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
    2: [('行业定义、产品及应用', r'定义|是指|行业分类|应用领域|应用场景|代表产品'), ('产业链主体和分层关系', r'上游.{0,180}中游.{0,180}下游'), ('各环节价值分配及毛利率', r'价值分配|价值份额|毛利率|利润分配'), ('核心瓶颈', r'瓶颈|受制于|供应短缺|核心部件依赖')],
    3: [('适用政策原文', 'primary'), ('国家规划与地方支持', r'规划|专项行动|地方|省市|园区|产业基金'), ('标准、补贴与准入', r'行业标准|国家标准|补贴|资质|准入|进出口管制'), ('义务主体及具体要求', r'应当|不得|必须|禁止'), ('发布与施行日期', r'(?:发布|施行|生效).{0,8}20\d{2}|20\d{2}.{0,12}(?:发布|施行|生效)'), ('实际执行材料', r'处罚决定|检查结果|已.{0,8}(?:处罚|查处)')],
    4: [('规模、期间和统计口径', 'amount'), ('同口径增长趋势', 'growth'), ('近三至五年历史序列与CAGR', 'historical_series'), ('未来五至十年来源预测', 'long_forecast'), ('情景假设和约束因素', r'情景假设|基准情景|乐观情景|悲观情景|制约因素|天花板'), ('增长驱动与商业化阶段', r'驱动因素|原型验证|小批量|规模化商用|增长动力')],
    5: [('有日期的主体事件', r'20\d{2}\s*年\s*\d{1,2}\s*月'), ('商业化里程碑与终端需求', r'开始收费|付费客户|订单交付|终端需求|量产|商业化落地'), ('传播或关注度数据', r'搜索指数|讨论量|曝光量|传播量')],
    6: [('竞争机制与玩家分层', r'迁移成本|进入壁垒|价格战|竞争压力|厂商排名|前[三四五十]厂商|市场第一阵营|市场前[三四五十]|' + PLAYER_LAYER_PATTERN), ('份额及集中度', r'市场份额|市占率|CR\d|HHI|集中度'), ('五力机制与护城河', r'议价|新进入者|替代品|供应商|迁移成本|护城河|专利壁垒')],
    7: [('路线及适用场景', r'技术路线|架构|云端|端侧|边缘侧|适用场景'), ('同条件测试配置', r'测试环境|统一硬件|量化精度|测试条件'), ('可核验性能及单位成本', 'technical_measurement'), ('落地难度与迭代成熟度', r'落地难度|迭代|成熟度|部署条件|量产验证')],
    10: [('实际收费与付费客户', r'订阅|按量计费|付费客户|续约|回款'), ('盈利及收入成本材料', r'毛利率|净利率|营业收入|收入结构|成本定义'), ('细分赛道与筛选标准', r'细分赛道|筛选标准|客户认证|单位经济|投资机会|产业整合')],
    11: [('来源预测与目标期间', 'forecast'), ('未来三至五年趋势与关键变量', r'未来.{0,15}趋势|关键变量|发展趋势|趋势判断'), ('来源假设和情景条件', r'假设|基准情景|情景假设'), ('可跟踪触发条件', r'触发条件|阈值|前提条件')],
    13: [('风险机制及作用对象', r'风险|漏洞|攻击|欺诈|成本压力|价格战|技术替代'), ('行业经营与技术研发风险', r'客户集中|产能不足|商业化慢|供应链依赖|技术迭代|研发失败|核心部件外购'), ('监管义务或执行材料', r'应当|不得|处罚决定|检查结果')],
    14: [('市场信号与发展判断', r'规模|增长|需求|市场'),
         ('竞争与商业化判断', r'玩家|竞争|订阅|计费|收费|盈利|商业模式'),
         ('技术及落地条件', r'技术|架构|云端|端侧|边缘|部署|性能|成本'),
         ('政策与经营约束', r'应当|不得|监管|义务|风险'),
         ('总体判断及成立条件', 'synthesis')],
}


def chapter_coverage(package, index, ids):
    """Presence of relevant material is distinct from a verified answer."""
    ids = set(ids)
    cards = [f for f in package.get('facts', []) if f.get('evidence_id') in ids and chapter_admitted(f, index)]
    historical_ids, compound_ids, series_exists = set(), set(), False
    if index == 4:
        from industry_assertions import observation_key
        groups = {}
        for fact in cards:
            ctx = fact.get('numeric_context') or {}
            if ctx.get('is_forecast') is False and fact['fact_contract'].get('quantity_type') == 'amount':
                historical_ids.add(fact['evidence_id'])
                key = observation_key(fact)
                if key and re.fullmatch(r'20\d{2}', str(ctx.get('period') or '')):
                    groups.setdefault(key[:5], set()).add(str(ctx['period']))
            if (fact['fact_contract'].get('quantity_type') == 'growth'
                    and re.search(r'CAGR|复合.*增长', str(ctx.get('metric') or ''), re.I)):
                compound_ids.add(fact['evidence_id'])
        series_exists = any(len(years) >= 3 for years in groups.values()) and bool(compound_ids)
    rows = []
    for question, pattern in CHAPTER_QUESTIONS.get(index, []):
        matched, background = [], []
        for fact in cards:
            c = fact['fact_contract']; ctx = fact.get('numeric_context') or {}
            if pattern == 'synthesis': ok = True
            elif pattern == 'primary': ok = c['source_role'] == 'policy_primary'
            elif question in {'义务主体及具体要求', '监管义务或执行材料'}:
                from industry_passages import policy_obligation
                ok = c['source_role'] == 'policy_primary' and bool(policy_obligation(_quote(fact)) or re.search(r'处罚决定|检查结果', _quote(fact)))
            elif pattern == 'amount': ok = c['quantity_type'] == 'amount'
            elif pattern == 'growth': ok = c['quantity_type'] == 'growth'
            elif pattern == 'forecast': ok = ctx.get('is_forecast') is True
            elif pattern == 'historical_series':
                ok = series_exists and fact['evidence_id'] in historical_ids | compound_ids
                if not ok and (fact['evidence_id'] in historical_ids or c['quantity_type'] == 'growth'):
                    background.append(fact['evidence_id'])
            elif pattern == 'long_forecast':
                cutoff = str((package.get('industry_scope') or {}).get('as_of_date') or '')[:4]
                period = str(ctx.get('period') or '')
                ok = (ctx.get('is_forecast') is True and cutoff.isdigit() and re.fullmatch(r'20\d{2}', period)
                      and 5 <= int(period)-int(cutoff) <= 10)
                if not ok and ctx.get('is_forecast') is True:
                    background.append(fact['evidence_id'])
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
            elif question == '竞争机制与玩家分层':
                ok = not c.get('sample_boundary') and bool(re.search(pattern, c['statement'], re.I))
                if not ok and c.get('sample_boundary') and re.search(pattern, c['statement'], re.I):
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
    from report_agents.industry_template import chapter_template_contract
    from industry_reasoning import question_ledger
    from industry_reader import writing_profile, writing_instruction
    profile = writing_profile(package, index)
    depth = writing_instruction(profile) if index in {2, 3, 4, 5, 6, 7, 10, 11, 13} else ''
    cards = [{'id': f['evidence_id'], 'statement': f['fact_contract']['statement'],
              'tasks': f['fact_contract']['tasks'], 'sample_boundary': f['fact_contract'].get('sample_boundary'),
              'material_kind': f['fact_contract'].get('material_kind')} for f in package.get('facts', []) if chapter_admitted(f, index)]
    synthesis = ('本章是阶段性综合评估：围绕已完成章节的已知信息，给出3至4项可供人工深化的初步判断。'
        '每项先用一句话说明已知材料支持什么判断，再解释跨材料的联系和成立条件；不能整段只列缺口或照抄摘录。'
        '可写有边界的比较、推论和条件判断，不能据规模直接认定需求、盈利、低风险或投资吸引力。'
        '优先综合不同章节的适用材料，只有同一主题时也可给局部判断，不为了凑跨章引用加入无关材料。'
        '每项只写一个可独立复核的判断：规模单点可写规模信号，不称持续扩张；技术侧重不同可写方案分化，不补造落地协同的必要性。'
        '先把原文支持的观察完整说清，再单独标出有条件推论；不要把可保留事实和较强推论捆成一大段。'
        '研究角度不要求每项各写一段；总体判断可以体现在前述观察的联系中。'
        '每段60至160字，最多4项，每项引用1至2条材料，推理说明40至80字；不输出总分、评级、概率、投资建议或新事实。\n' if index == 14 else '')
    count_rule = ('最多8条来源、4段分析；每段60至160字。' if index == 14 else '最多8条来源、6段分析；每段60至360字。')
    return (synthesis + depth + '严格按固定模板逐项研究。来源陈述不可改写；另写受证据约束的分析，不能只给编号或复述摘录。'
            '返回严格JSON：{"evidence_ids":["E-..."],"analyses":[{"question":"本章研究问题原名",'
            '"text":"解释材料与问题的关系、可支持的判断及仍缺的条件", "evidence_ids":["E-..."],'
            '"claim_kind":"observation|comparison|inference|conditional|limitation",'
            '"reasoning":"简述从前提到判断的推理及其他可能解释，不新增事实"}]}。'
            + count_rule + '只引用选中且适用于该问题的材料。'
            '原文前提由程序按每段evidence_ids逐字绑定，不必返回premises或反复抄写statement；reasoning简述推理，不能替代正文展开。'
            '分析不得新增数值、法律日期或义务，不得把预测写成实际、观点写成事实、样本写成行业结论。'
            '缺证的要求保留缺口；模板不能提供事实。不要输出标题、Markdown、网址或引用标记，引用另填编号。'
            '描述所引材料未覆盖的问题时用limitation，明确限定本章所引材料，不得声称整个行业或所有公开资料均无。'
            '样本可作有明确边界的比较或背景，不得据此形成行业评分或行业总体结论。\n'
            + json.dumps({'chapter': index, 'template_contract': chapter_template_contract(index, package.get('industry_scope')),
                'writing_profile': profile,
                'required_questions': [q for q, _ in CHAPTER_QUESTIONS.get(index, [])],
                'question_coverage': chapter_coverage(package, index, [c['id'] for c in cards]),
                'research_questions': question_ledger(package, index, [c['id'] for c in cards])['questions'],
                'task': GAPS.get(CHAPTER_TASK.get(index), '可引用来源陈述'), 'cards': cards}, ensure_ascii=False))


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


def parse_chapter_response(text, package, index):
    """Keep old ID-only responses usable; validate analysis independently."""
    raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip(), flags=re.I)
    response = json.loads(raw)
    if not isinstance(response, dict) or set(response) - {'evidence_ids', 'analyses'}:
        raise ValueError('invalid_statement_plan')
    ids = parse_plan(json.dumps({'evidence_ids': response.get('evidence_ids')}, ensure_ascii=False), package, index)
    analyses = response.get('analyses', [])
    if not isinstance(analyses, list) or len(analyses) > 6:
        raise ValueError('invalid_analysis_plan')
    return ids, analyses


def normalize_analysis(claim, allowed_ids):
    """Repair presentation only; never truncate prose, change a value or add evidence."""
    result, changes = deepcopy(claim), []
    if not isinstance(result, dict):
        return result, changes
    refs = result.get('evidence_ids')
    if isinstance(refs, list) and all(isinstance(eid, str) for eid in refs):
        unique = list(dict.fromkeys(refs))
        if unique != refs:
            result['evidence_ids'] = unique
            changes.append('duplicate_reference_removed')
    body = result.get('text')
    if isinstance(body, str):
        normalized = re.sub(r'\s+', ' ', body).strip()
        if normalized != body:
            changes.append('whitespace_normalized')
        authorized = set(result.get('evidence_ids') or []) & set(allowed_ids) if isinstance(refs, list) and all(isinstance(eid, str) for eid in refs) else set()
        token = r'E-[A-F0-9]{12}'
        citation_list = token + r'(?:\s*[、,，;；]\s*' + token + r')*'
        def remove_marker(match):
            cited = set(re.findall(token, match.group(0)))
            if cited and cited <= authorized:
                following = normalized[match.end():].lstrip()
                before = normalized[:match.start()].rstrip()
                predicate = r'的|则|以|指出|显示|表明|说明|披露|描述|记载|提出|认为|提供|反映|将|把|只'
                preposition = bool(re.search(r'(?:根据|依据|参照|结合|对照|来自|据|从)\s*$', before))
                wrapped = match.group(0).lstrip().startswith(('[', '【', '(', '（', '`'))
                embedded_marker = wrapped and bool(re.search(r'[\u4e00-\u9fffA-Za-z0-9]$', before)) and not preposition
                if preposition or (re.match(predicate, following) and not embedded_marker):
                    changes.append('authorized_reference_subject_labelled')
                    return '所引材料'
                changes.append('authorized_inline_citation_removed')
                return ''
            return match.group(0)
        # Remove only citation-shaped tokens already authorized in the separate
        # references field. Keep unknown IDs, URLs, identifier fragments and
        # every prose/numeric character for the ordinary validator to inspect.
        for left, right in (('[', ']'), ('【', '】'), ('(', ')'), ('（', '）'), ('`', '`')):
            normalized = re.sub(re.escape(left) + r'\s*' + citation_list + r'\s*' + re.escape(right), remove_marker, normalized)
        normalized = re.sub(r'(?<![A-Za-z0-9_/.=:-])' + citation_list + r'(?![A-Za-z0-9_/-])', remove_marker, normalized)
        def alias_subject(match):
            alias = match.group(0)
            matches = [eid for eid in authorized if eid.startswith(alias)]
            if len(matches) != 1:
                return alias
            if isinstance(allowed_ids, dict) and any(alias in str((f.get('fact_contract') or {}).get('statement') or '')
                                                    for f in allowed_ids.values() if isinstance(f, dict)):
                return alias  # A real product/code in the original is not a citation alias.
            following = normalized[match.end():].lstrip()
            before = normalized[:match.start()].rstrip()
            if re.match(r'的|则|以|指出|显示|表明|说明|披露|描述|记载|提出|认为|提供|反映|将|把|只', following) or re.search(r'(?:根据|依据|参照|结合|对照|来自|据|从)\s*$', before):
                changes.append('authorized_reference_alias_labelled')
                return '所引材料'
            return alias
        normalized = re.sub(r'(?<![A-Za-z0-9_/.=:-])E-[A-F0-9]{2,11}(?![A-Za-z0-9_-])', alias_subject, normalized)
        result['text'] = re.sub(r'\s+', ' ', normalized).strip()
    return result, list(dict.fromkeys(changes))


def validate_analyses(analyses, package, index, ids):
    """Rule checks permit a draft claim, never certify semantic entailment."""
    from industry_research import numeric_mentions, numeric_supported, claim_semantic_issues
    from industry_passages import passage_issues
    by_id = {f['evidence_id']: f for f in package.get('facts', []) if chapter_admitted(f, index) and f.get('evidence_id') in ids}
    questions = {r['question']: r for r in chapter_coverage(package, index, ids)}
    accepted, rejected = [], []
    for ordinal, original in enumerate(analyses):
        claim, formatting = normalize_analysis(original, by_id)
        errors, details = [], []
        def reject():
            rejected.append({'index': ordinal, 'question': claim.get('question') if isinstance(claim, dict) else None,
                'issues': list(dict.fromkeys(errors)), 'details': details,
                'original_analysis': deepcopy(original), 'normalized_analysis': deepcopy(claim),
                'format_normalization': formatting})
        if (not isinstance(claim, dict) or not {'question', 'text', 'evidence_ids'} <= set(claim)
                or set(claim) - {'question', 'text', 'evidence_ids', 'premises', 'claim_kind', 'reasoning'}):
            errors.append('invalid_analysis_schema')
            details.append({'code': 'invalid_schema', 'expected': ['question', 'text', 'evidence_ids']})
            reject()
            continue
        question, body, refs = claim['question'], claim['text'], claim['evidence_ids']
        if not isinstance(body, str):
            errors.append('invalid_analysis_text')
            details.append({'code': 'text_not_string'})
        else:
            if not 40 <= len(body) <= 420:
                details.append({'code': 'text_length_out_of_range', 'actual': len(body), 'min': 40, 'max': 420})
            for code, pattern in [('text_contains_url', r'https?://'), ('text_contains_inline_evidence_id', r'E-[A-F0-9]{12}'),
                                  ('text_contains_markup', r'[<>#|]')]:
                if re.search(pattern, body):
                    details.append({'code': code})
            if details:
                errors.append('invalid_analysis_text')
        if (not isinstance(refs, list) or not refs or len(refs) > 4
                or any(not isinstance(eid, str) or eid not in by_id for eid in refs)
                or len(set(refs)) != len(refs)):
            errors.append('invalid_analysis_citations')
            details.append({'code': 'invalid_references', 'supplied': refs, 'allowed_ids': list(by_id), 'max_count': 4})
        if not isinstance(question, str) or question not in questions:
            errors.append('unknown_template_question')
        if errors:
            reject()
            continue
        rows = [by_id[eid] for eid in refs]
        from industry_reasoning import premise_issues
        exact_claim = dict(claim)
        if 'premises' not in claim:
            exact_claim['premises'] = [{'evidence_id': f['evidence_id'], 'quote': f['fact_contract']['statement']} for f in rows]
        errors.extend(premise_issues(exact_claim, rows))
        if 'claim_kind' in claim and (not isinstance(claim['claim_kind'], str) or claim['claim_kind'] not in {'observation', 'comparison', 'inference', 'conditional', 'limitation'}):
            errors.append('invalid_claim_kind')
        if 'reasoning' in claim and (not isinstance(claim['reasoning'], str) or not 8 <= len(claim['reasoning']) <= 600):
            errors.append('invalid_claim_reasoning')
        coverage = questions[question]
        relevant = set(coverage['evidence_ids']) | set(coverage.get('background_evidence_ids', []))
        # A scoped explanation of a material gap is useful analysis, not an
        # answer or an admission upgrade. Only an explicit limitation can use
        # other selected, chapter-admitted cards to describe that limitation.
        limitation = (claim.get('claim_kind') == 'limitation'
            and re.search(r'所引|本章|本次|现有|这些|上述|当前|所列', body)
            and re.search(r'尚缺|尚无|缺少|未提供|未说明|未给出|不能|不足|无法', body)
            and not re.search(r'(?:全行业|所有公开|全部公开|整个行业).{0,8}(?:没有|不存在|均无|缺乏)', body))
        if claim.get('claim_kind') == 'limitation' and not limitation:
            errors.append('unscoped_material_limitation')
        if not set(refs) <= relevant and not limitation:
            errors.append('analysis_question_evidence_mismatch')
            details.append({'code': 'question_reference_mismatch', 'question': question,
                'supplied': refs, 'direct_ids': coverage['evidence_ids'],
                'background_ids': coverage.get('background_evidence_ids', [])})
        if not limitation and not set(refs) & set(coverage['evidence_ids']) and not re.search(r'尚缺|尚无|不能|不足|仅.*(?:模式|观点|样本|背景)', body):
            errors.append('background_presented_as_answer')
        if any(f['fact_contract'].get('sample_boundary') for f in rows) and not re.search(r'样本|所引企业|特定企业|特定测试', body):
            errors.append('analysis_sample_boundary_missing')
        numeric = {f['evidence_id']: {'context': f.get('numeric_context') or {}, 'validation': f.get('numeric_validation') or {}} for f in rows}
        if any(not any(numeric_supported(n, eid, numeric) for eid in refs) for n in numeric_mentions(body)):
            errors.append('analysis_unauthorized_number')
        canonical = re.sub(r'\s+', '', ' '.join(f['fact_contract']['statement'] for f in rows))
        legal_fields = re.findall(r'20\d{2}年\d{1,2}月\d{1,2}日|第[一二三四五六七八九十百\d]+条', body)
        if index in {3, 13} or re.search(r'法律|法规|条例|办法|监管|规定|许可证', body):
            legal_fields += re.findall(r'(?:企业|提供者|运营者|开发者|服务商|机构)[^。；;]{0,15}(?:应当|不得|必须|禁止)[^。；;]{1,80}', body)
        for legal in legal_fields:
            if re.sub(r'\s+', '', legal) not in canonical:
                errors.append('analysis_unauthorized_legal_statement')
        errors.extend(passage_issues(body, analysis=True))
        errors.extend(r['code'] for r in claim_semantic_issues(body+' '+ ' '.join(refs), rows))
        if errors:
            reject()
        else:
            accepted.append({**exact_claim, 'premise_binding': 'model_exact' if 'premises' in claim else 'program_exact',
                'analysis_index': ordinal, 'format_normalization': formatting,
                'analysis_role': 'material_limitation' if limitation else 'draft_claim',
                'validation_status': 'rule_checked', 'entailment_status': 'not_evaluated'})
    return accepted, rejected


def render_plan(package, index, title, ids, analyses=None, ledger=None):
    cards = {f['evidence_id']: f for f in package.get('facts', []) if chapter_admitted(f, index)
             and (index != 1 or f.get('summary_lineage'))}
    if index == 14:
        from industry_briefing import conclusion_section
        return f'## 14. {title}\n\n' + conclusion_section([
            c for c in analyses or [] if c.get('claim_kind') != 'limitation'
            and c.get('analysis_role') != 'material_limitation'])
    lines, seen = [], {}
    for eid in ids:
        if eid not in cards: raise ValueError('unauthorized_statement_plan')
        fact = cards[eid]
        statement = fact['fact_contract']['statement']
        if statement in seen:
            lines[seen[statement]] += f' [{eid}]({fact.get("source_url", "")})'
            continue
        seen[statement] = len(lines)
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
    from industry_reasoning import question_ledger, STATE_LABELS
    coverage = (ledger or question_ledger(package, index, ids, analyses or []))['questions']
    matrix = ''
    if coverage:
        matrix = '\n\n### 材料覆盖与研究缺口\n\n| 本章研究问题 | 当前材料 | 研究状态 |\n| --- | --- | --- |\n'
        for row in coverage:
            matched = ' '.join('['+eid+']' for eid in row['evidence_ids'][:1])
            background = ' '.join('['+eid+']' for eid in row.get('background_evidence_ids', [])[:1])
            refs = ('对应材料：' + matched if matched else '')
            if background:
                refs += ('；' if refs else '') + '背景材料（未回答本问题）：' + background
            refs = refs or '尚无适用材料'
            state = ('有来源材料，适用性与结论支持仍需复核' if row['evidence_ids'] else
                     ('仅有模式或观点背景，实际经营指标仍缺证' if index == 10 else
                      '仅有定性描述或观点背景，尚无已核验的可比指标') if row.get('background_evidence_ids') else '本轮未回答，需补证或缩减研究范围')
            if row['evidence_state'] == 'selection_gap':
                state = '已有适用候选未进入本章选材，先复核选材，不据此判外部缺证'
            if row['claim_support_states']:
                if row.get('analysis_status') == 'limitations_only':
                    state += '；仅缺口说明接受复核，研究问题仍未解决'
                else:
                    state += '；' + '、'.join(dict.fromkeys(STATE_LABELS[s] for s in row['claim_support_states']))
            matrix += f'| {row["question"]} | {refs} | {state} |\n'
    from industry_analysis import chapter_analysis
    analysis = chapter_analysis(package, index, ids)
    if analyses:
        analysis = '\n\n### 研究分析\n\n' + '\n\n'.join(
            '**' + statement_markdown(c['question']) + '**：' + statement_markdown(c['text']) + ' '
            + ' '.join('['+eid+']' for eid in c['evidence_ids']) for c in analyses)
    from industry_briefing import comparison_table
    table, table_ids = comparison_table([cards[eid] for eid in ids if eid in cards], index)
    if table:
        lines = [line for line in lines if not any(' ['+eid+'](' in line for eid in table_ids)]
    evidence = '\n\n'.join(([table] if table else []) + lines)
    # Findings come before the audit material. Canonical source text and links
    # remain available below, rather than being replaced by model paraphrases.
    return (f'## {index}. {title}\n\n' + note + analysis + '\n\n### 关键依据\n\n'
            + (evidence or '本章尚无满足准入条件的完整陈述，相关核验事项见第16章。') + matrix)
