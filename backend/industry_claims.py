"""Deterministic delivery checks. Passing these checks is not semantic proof."""
import re
from urllib.parse import urlsplit


def public_source_type(url):
    """Authority follows the actual host, never a regulator word in a title."""
    try:
        host = (urlsplit(str(url or '')).hostname or '').lower().rstrip('.')
    except ValueError:
        return 'web_search'
    def domain(value):
        return host == value or host.endswith('.' + value)
    if any(domain(x) for x in ('qcc.com', 'tianyancha.com', 'aiqicha.baidu.com', 'qixin.com')):
        return 'business_database'
    if any(domain(x) for x in ('cninfo.com.cn', 'sse.com.cn', 'szse.cn', 'hkexnews.hk', 'sec.gov')):
        return 'filing'
    if any(domain(x) for x in ('court.gov.cn', 'courts.gov.cn')):
        return 'court'
    if any(domain(x) for x in ('csrc.gov.cn', 'pbc.gov.cn', 'nfra.gov.cn', 'samr.gov.cn', 'creditchina.gov.cn')):
        return 'regulatory'
    if any(domain(x) for x in ('gov.cn', 'gov', 'gov.uk', 'gov.au', 'go.jp', 'europa.eu')):
        return 'government'
    return 'web_search'


def claim_contract_issues(text, facts):
    from industry_research import EVIDENCE_ID_PATTERN, numeric_mentions, numeric_supported
    issues = []
    by_id = {f['evidence_id']: f for f in facts if f.get('evidence_id')}
    for line in text.splitlines():
        ids = set(re.findall(EVIDENCE_ID_PATTERN, line, re.I))
        rows = [f for eid, f in by_id.items() if not ids or eid in ids]
        numeric = {f['evidence_id']: {'context': f.get('numeric_context') or {},
                   'validation': f.get('numeric_validation') or {}} for f in rows}
        def add(code, message):
            issues.append({'code': code, 'message': message, 'evidence_ids': sorted(ids)})
        assertion = re.search(r'已验证|已核验|证据充分|高确定性', line)
        negated = assertion and re.search(r'未|无|不|尚待|待', line[max(0, assertion.start()-5):assertion.start()])
        if assertion and not negated:
            numbers = numeric_mentions(line)
            if (not ids or not rows or '待核验' in line or (numbers and any(
                    not any(numeric_supported(n, eid, numeric) for eid in numeric) for n in numbers))):
                add('evidence_status_conflict', '已验证、证据充分或高确定性声明与该行待核验状态或授权数值不一致。')
        if re.search(r'(?:供给端|行业|市场|竞争格局|同业竞争).{0,12}(?:高度碎片化|高度分散|集中度(?:较|很|极)低)', line):
            if not re.search(r'不能|不代表|不足以|是否|假设', line):
                concentration = [f for f in rows if f.get('eligible_for_risk_scoring') is not False
                    and f.get('evidence_scope') in {'industry_level', 'segment_level'}
                    and (f.get('numeric_validation') or {}).get('passed') is True
                    and re.search(r'集中度|CR[235]|HHI|市场份额|市占率', str((f.get('numeric_context') or {}).get('metric', '')), re.I)]
                if not concentration:
                    add('concentration_inference_unsupported', '企业数量不能证明行业集中度或高度碎片化，需适用的份额或集中度指标。')
        barrier = re.search(r'(?:低门槛|门槛.{0,6}(?:较低|更低|很低)|较低.{0,8}壁垒|壁垒.{0,6}(?:更高|较高|更低|较低)|隐含更高能力门槛)', line)
        if barrier and not re.search(r'不能|不足以|是否|尚待|需核验',line[max(0,barrier.start()-15):barrier.start()]):
            direct = [f for f in rows if re.search(r'准入(?:要求|条件)|许可(?:成本|要求)|迁移成本|专利保护|专利许可|研发投入|客户认证|资质要求|专用接口|硬件投入',
                str(f.get('evidence_quote') or f.get('fact') or '')) and f.get('evidence_scope') in {'industry_level','segment_level'}]
            if not direct:
                add('entry_barrier_inference_unsupported','企业数量或层级占比不能推出准入及技术壁垒，须有适用的准入、成本或能力证据。')
        if re.search(r'执行(?:效力|效果|力度).{0,8}(?:存疑|不足|薄弱|低下)',line) and not re.search(r'不能|不足以证明|是否',line):
            direct = [f for f in rows if re.search(r'执行效果|执行效力|执法检查|处罚决定|抽查结果', str(f.get('evidence_quote') or f.get('fact') or ''))]
            if not direct:
                add('evidence_gap_as_policy_effect','未取得执行材料只能列为核验缺口，不能据此断定政策执行效力不足。')
        # A pending suffix does not license constructing new forecast numbers.
        if re.search(r'预测|预计|情景|假设|推算',line) and re.search(r'规模|增长|达到|万亿元|亿元',line):
            new = [n for n in numeric_mentions(line) if not any(numeric_supported(n,eid,numeric) for eid in numeric)]
            if new:
                add('derived_forecast_unvalidated','预测或情景中出现未授权数值，需有逐项来源或经验证的计算模型，不能仅加待核验提示后保留。')
        if re.search(r'(?:标准|政策).{0,60}(?:缩短|加快|减少).{0,20}(?:审批|审核)|(?:审批|审核).{0,20}(?:缩短|加快)',line) and not re.search(r'待核验|假设|不能推定',line):
            if not any(re.search(r'审批|审核',str(f.get('evidence_quote') or f.get('fact') or '')) and re.search(r'缩短|加快',str(f.get('evidence_quote') or f.get('fact') or '')) for f in rows):
                add('policy_causal_inference_unsupported','标准发布不能直接证明审批周期缩短，需对应的执行效果材料。')
        if re.search(r'(?:所有|全部)(?:清洗)?(?:事实|证据|来源|公开资料).{0,18}(?:均无|均未|没有|不存在)|完全没有(?:技术路线|测试条件|实测)',line):
            add('evidence_absence_overstated','本章选证不能证明全库或全部公开资料不存在信息，应说明本章覆盖及待核验范围。')
        from industry_grounding import sample_boundary
        if any(sample_boundary(f) for f in rows) and re.search(r'行业(?:整体|级|平均|普遍|所有|全部)|(?:全|整个)行业|(?:所有|全部).{0,8}技术路线|普遍(?:部署|适用|成熟|投入|商用|生产)|唯一可验证',line):
            if not re.search(r'不得|不能|不可|不代表|不外推|仅限.{0,6}样本',line):
                add('sample_extrapolation_unsupported','代表企业或上市公司样本不能改写为行业平均或行业级指标，须保留样本边界。')
        if re.search(r'高于|低于|超过.*均值', line) and re.search(r'增速|增长|同比', line) and not re.search(r'不可比|不能比较|假设', line):
            rates = [n for n in numeric_mentions(line) if '%' in n or '％' in n]
            cards = [f for f in rows if any(numeric_supported(n, f['evidence_id'], numeric) for n in rates)]
            periods = {str((f.get('numeric_context') or {}).get('period') or '') for f in cards}
            if len(rates) >= 2 and (len(periods) > 1 or any(not any(numeric_supported(n, eid, numeric) for eid in numeric) for n in rates)):
                add('growth_comparison_unsupported', '增速比较缺少同期间的已校验指标，不能借用原文中的其他数字。')
        if re.search(r'政策原文|法规原文', line) and rows and all(public_source_type(f.get('source_url')) not in {'government', 'regulatory'} for f in rows):
            if not re.search(r'非|不是|不等于|待核验|需核对', line):
                add('policy_primary_source_missing', '政策原文声明只引用了解读或其他非官方网页，需回到发布机关原文。')
        if re.search(r'AI\s*Act|人工智能法案', line, re.I) and re.search(r'高风险.{0,70}7\s*[%％]', line):
            if not re.search(r'禁止|第\s*5\s*条|不能|不等于', line):
                add('policy_penalty_scope_conflict', '7%罚款档不能泛化为高风险系统的一般违规，需核对适用违法类型和原始条款。')
        if re.search(r'口径(?:混乱|不一致)|统计不可比', line) and re.search(r'增长可持续性存疑|需求不振|经营风险高', line):
            if not re.search(r'不代表|不能|不足以', line):
                add('evidence_gap_as_business_risk', '统计口径缺口不能直接证明实际增长、需求或经营风险恶化。')
    # Reviewed against CAC 2025-03-14 release and European Commission's
    # enforcement-ai-act page. These are narrow known-error checks, not a
    # complete legal interpretation or a substitute for dated primary text.
    if re.search(r'人工智能生成合成内容标识|GB\s*45438', text) and re.search(r'2025\s*年\s*3\s*月(?:份)?(?:起|开始|即)?(?:施行|实施|生效)', text):
        issues.append({'code': 'policy_effective_date_conflict', 'message': '标识办法及配套强制标准于2025年9月1日起施行，不能将3月发布日期当成施行日期。'})
    issues.extend(table_completeness_issues(text))
    from industry_assertions import assertion_issues
    issues.extend(assertion_issues(text, facts))
    return issues


def table_completeness_issues(text):
    """Check count/share tables only when an accompanying total is asserted."""
    issues=[]
    for match in re.finditer(r'(?m)^\|[^\n]*(?:企业数量|企业数)[^\n]*\n\|[^\n]*\n(?:\|[^\n]*\n?)+',text):
        header,*rows=match[0].strip().splitlines()
        headers=[c.strip() for c in header.strip('|').split('|')]
        col=next((i for i,c in enumerate(headers) if re.search(r'企业数',c)),None)
        counts=[]
        for row in rows[1:]:
            cells=[c.strip() for c in row.strip('|').split('|')]
            if col is None or col>=len(cells):continue
            n=re.fullmatch(r'([\d,]+)\s*家?',cells[col])
            if n:counts.append(int(n[1].replace(',','')))
        context=text[max(0,match.start()-220):match.start()]
        total=re.search(r'(?:合计|总计|共计|总数(?:为|达)?)\s*([\d,]+)\s*家',context)
        if counts and total and sum(counts)!=int(total[1].replace(',','')) and not re.search(r'部分|节选|不完整|未列全',context+match[0]):
            issues.append({'code':'table_total_incomplete','message':f'企业数量表列示合计{sum(counts)}家与表前总数{total[1]}家不符，需核对完整原表或明确为部分列示；不得编造其余分布。'})
    return issues


def industry_gap_plan(item):
    if re.search(r'章节写作复核|综合写作',item):
        return ('本章生成校验未完成。','对照原文及风险结果重写失败章节，复核引用、数值归属及结论边界。','高','本轮章节正文、失败原因、原始证据及当前评分结果。')
    if re.search(r'产业链|分层|上中下游',item):
        return ('产业链环节及其对应证据尚需核对。','核对行业原始报告的环节定义、产品及上下游关系，区分行业层与企业样本。','高','原始产业链图表、环节定义及对应来源位置。')
    if re.search(r'集中度|市场份额|市占率|CR[235]|HHI|竞争格局', item, re.I):
        return ('集中度或份额尚缺同口径的指标支持。', '核对CR3/CR5、HHI或头部玩家份额的原始表，统一地域、期间、行业边界及分母；企业数量和网页数量不能替代集中度。', '高', '集中度或份额原表、头部玩家与行业分母、样本及计算方法。')
    if re.search(r'商业化|盈利模式|变现|续约|付费转化|定价|收费', item):
        return ('实际收费、客户转化或盈利质量尚需原始披露支持。', '核对实际收费、付费客户、续约及收入成本口径；分别记录行业统计和企业样本，不将计费观点当作商业落地证明。', '高', '原始收费及经营披露、统计期间、成本定义、样本选择与覆盖范围。')
    if re.search(r'规模|增长|增速|口径|统计|集中度|份额|CR[235]|HHI|盈利|毛利率', item, re.I) and not re.search(r'专利',item):
        return ('统计期间、地域、定义或分母仍需对应原始资料核对。', '核对统计机构原报告和数据表，分别记录实际值与预测值；转载按原始来源去重。', '高', '原始统计表、期间、地域、行业定义、样本和分母。')
    if re.search(r'专利|知识产权',item):
        return ('现有记录不足以核对原始文件及适用范围。', '核对发布机关或专利主管部门原文，分别记录发布、生效日期和统计定义。', '高', '正式文件编号、原始链接、适用地域与时间；专利统计方法。')
    if re.search(r'政策|监管|标准|准入|法规|标识办法|适用主体|处罚条款',item):
        return ('现有材料尚未核对政策适用性及执行情况。','核对发布机关原文，区分发布日期、生效日期、适用义务与执行结果。','高','正式文件编号、原始链接、适用地域与时间；需要时补执行决定或检查结果。')
    if re.search(r'技术|路线|性能|成本|推理|算力', item):
        return ('现有资料未形成同条件的技术比较。', '核对原始测试报告、配置、负载和测试方法；必要时访谈技术负责人。', '高', '测试环境、版本、性能与单位成本表、方法说明。')
    return ('本轮证据尚不足以形成该项判断。', '先核对公开原始披露；仍缺证时经确认补充客户资料或访谈。', '中', '对应原始披露、待确认问题及可联系的核验对象。')
