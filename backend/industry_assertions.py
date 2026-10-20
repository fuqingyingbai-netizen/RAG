"""Narrow source-to-claim contracts; these do not establish semantic truth."""
import re


def _qualified(text):
    return bool(re.search(r'不能|不得|不可|不应|不代表|不足以|不构成|并非|不是|是否|尚待|待验证|假设', text))


def _rate_kind(text):
    matches = list(re.finditer(r'CAGR|复合(?:年)?增长(?:率|速)?|年均增长(?:率|速)?|同比|环比', text, re.I))
    if not matches:
        return ''
    value = matches[-1][0].lower()
    return 'compound' if re.search(r'cagr|复合|年均', value) else value


def bounded_conflict_unsupported(text, facts):
    """Different lower bounds can coexist; they are not unequal point estimates."""
    if not re.search(r'不一致数值|数值.{0,8}冲突|口径冲突|(?:两组|三组).{0,8}不一致', text):
        return False
    from industry_research import number_key
    groups = {}
    for fact in facts:
        ctx = fact.get('numeric_context') or {}
        key = number_key(str(ctx.get('value', '')) + str(ctx.get('unit', '')))
        if key is None or (fact.get('numeric_validation') or {}).get('passed') is not True:
            continue
        comparator = (fact.get('fact_contract') or {}).get('comparator') or ctx.get('comparator') or '='
        group = (ctx.get('metric'), ctx.get('period'), ctx.get('geography'), key[1], ctx.get('is_forecast'))
        groups.setdefault(group, []).append((key[0], comparator))
    compatible_bounded = False
    for values in groups.values():
        if len(values) < 2 or not any(c in {'>', '>=', '<', '<='} for _,c in values):
            continue
        if any(c == 'approx' for _,c in values):
            continue  # Approximation tolerance requires a separate methodology.
        lows = [(v,c == '>') for v,c in values if c in {'>', '>=', '='}]
        highs = [(v,c == '<') for v,c in values if c in {'<', '<=', '='}]
        low = max((v for v,_ in lows), default=None)
        high = min((v for v,_ in highs), default=None)
        strict_low = any(v == low and c for v,c in lows)
        strict_high = any(v == high and c for v,c in highs)
        if low is not None and high is not None and (low > high or (low == high and (strict_low or strict_high))):
            return False
        compatible_bounded = True
    return compatible_bounded


def assertion_issues(text, facts):
    from industry_research import EVIDENCE_ID_PATTERN, numeric_scan_text, numeric_supported, number_key
    issues = []
    by_id = {f['evidence_id']: f for f in facts if f.get('evidence_id')}
    exclusion = False
    for line in text.splitlines():
        if line.lstrip().startswith('#'):
            exclusion = False
        if re.search(r'明确排除|规避信号|硬性门槛|必要条件', line):
            exclusion = True
        elif line.strip() and not re.match(r'^\s*(?:[-*]|\d+[.)、])', line):
            exclusion = False
        ids = set(re.findall(EVIDENCE_ID_PATTERN, line, re.I))
        rows = [f for eid, f in by_id.items() if not ids or eid in ids]
        numeric = {f['evidence_id']: {'context': f.get('numeric_context') or {},
                   'validation': f.get('numeric_validation') or {}} for f in rows}
        def add(code, message):
            issues.append({'code': code, 'message': message, 'evidence_ids': sorted(ids)})
        # An author's preferred charging model is not a universal eligibility rule.
        billing = re.search(r'token|词元|按需调用|按量计费|计量化|定制算法|离线SDK', line, re.I)
        mandatory = re.search(r'硬性门槛|必须|须具备|需支持|必要条件|明确排除|不符合|规避信号|仅限', line)
        if billing and (mandatory or exclusion) and not _qualified(line):
            direct = [f for f in rows if f.get('evidence_scope') in {'industry_level', 'segment_level'}
                      and re.search(r'必须|应当|强制|禁止', str(f.get('evidence_quote') or ''))
                      and re.search(r'token|词元|按量计费|按需调用', str(f.get('evidence_quote') or ''), re.I)]
            if not direct:
                add('business_screening_rule_unsupported', '计费模式观点不能升级为全行业投资硬门槛或淘汰条件，需有适用的明确规则及边界。')
        scan = numeric_scan_text(line)
        if re.search(r'(?:增速|增长率|同比增幅)(?:(?!单位|收入|规模)[^|。]){0,35}单位\s*[:：]\s*(?:亿元|万元|美元|元)', line):
            add('rate_unit_conflict', '增速或增长率的单位不能写成金额，需将增长率与收入规模分别列示。')
        for clause in re.split(r'[，；;。！？]|(?<!\d),|,(?!\d)', scan):
            for number in re.finditer(r'[-+−]?\d[\d,]*(?:\.\d+)?\s*[%％]', clause):
                kind = _rate_kind(clause[max(0, number.start()-65):number.start()])
                if not kind or _qualified(clause[:number.start()]):
                    continue
                supporting = [f for f in rows if numeric_supported(number[0], f['evidence_id'], numeric)]
                kinds = {_rate_kind(str((f.get('numeric_context') or {}).get('metric') or ''))
                         or _rate_kind(str((f.get('numeric_context') or {}).get('definition') or '')) for f in supporting}
                kinds.discard('')
                if not kinds:
                    # Other numbers in a quote cannot authorize writing. They
                    # can still reveal that a borrowed rate was relabelled.
                    for fact in rows:
                        quote = str(fact.get('evidence_quote') or '')
                        for original in re.finditer(r'[-+−]?\d[\d,]*(?:\.\d+)?\s*[%％]', quote):
                            if number_key(original[0]) == number_key(number[0]):
                                original_kind = _rate_kind(quote[max(0,original.start()-65):original.start()])
                                if original_kind:
                                    kinds.add(original_kind)
                if kinds and kind not in kinds:
                    add('growth_rate_kind_conflict', '增长率数值虽相同，但同比、环比与复合年增长率不能互换；须保留对应指标含义。')
            if (re.search(r'高于|低于|超过', clause) and re.search(r'GDP|国内生产总值', clause, re.I)
                    and re.search(r'增速|增长|同比|CAGR', clause, re.I) and not _qualified(clause)):
                benchmark = [f for f in rows if (f.get('numeric_validation') or {}).get('passed') is True
                             and re.search(r'GDP|国内生产总值', str(f.get('numeric_context') or {}), re.I)]
                rates = re.findall(r'[-+−]?\d[\d,]*(?:\.\d+)?\s*[%％]', clause)
                industry = [f for f in rows if f not in benchmark and any(numeric_supported(n, f['evidence_id'], numeric) for n in rates)]
                comparable = any((a.get('numeric_context') or {}).get('period')
                                 and (a.get('numeric_context') or {}).get('period') == (b.get('numeric_context') or {}).get('period')
                                 and (a.get('numeric_context') or {}).get('geography') == (b.get('numeric_context') or {}).get('geography')
                                 for a in industry for b in benchmark)
                if not comparable:
                    add('growth_benchmark_missing', '与GDP增速的比较缺少对应期间、口径的已核验基准，不能仅凭单个行业增长率得出结论。')
        if not _qualified(line):
            if bounded_conflict_unsupported(line, rows):
                add('compatible_bounds_as_conflict', '多个下限或相容区间不能仅因数值不同就认定冲突，须核对比较符、定义及测算时点。')
            if (re.search(r'未见|无证据表明|没有.{0,8}证据', line)
                    and re.search(r'准入限制|处罚影响|限制或处罚', line)):
                add('absence_as_low_risk', '未见限制或处罚材料不能证明政策影响较低，需对应义务、适用范围和执行证据。')
            conclusions = (
                (r'投入错配|结构性失衡|结构显著失衡|结构性瓶颈', r'投入错配|投入结构|投入产出|资源错配|瓶颈', 'allocation_inference_unsupported', '企业数量占比或增长率不能证明投入错配和结构性瓶颈，需对应投入、产出或瓶颈证据。'),
                (r'整合.{0,10}(?:加速发生|正在发生|已发生)|(?:确认|表明).{0,12}整合方向', r'并购|兼并|合资|整合案例|生态联盟', 'integration_inference_unsupported', '规模增长不能证明产业整合已发生或确定其方向，需对应主体行为材料。'),
                (r'已越过.{0,15}验证阶段|进入规模化商用|刚性采购需求|最坚实投资前提|降低赛道选择风险', r'采购合同|实际采购|付费客户|续约率|回款|商业闭环', 'commercial_certainty_unsupported', '宏观规模、企业数量或场景基础不能单独证明商业闭环、刚性采购或投资确定性。'),
            )
            for pattern, support, code, message in conclusions:
                if re.search(pattern, line) and not any(re.search(support, str(f.get('evidence_quote') or f.get('fact') or '')) for f in rows):
                    add(code, message)
            if (re.search(r'证监会旗下报告|证监会发布的报告', line)
                    and not any(re.search(r'证监会', str(f.get('publisher') or ''))
                                or re.match(r'https?://(?:[^/]+\.)?csrc\.gov\.cn(?:/|$)', str(f.get('source_url') or '')) for f in rows)):
                add('publisher_attribution_unsupported', '承载PDF或转载的域名不能证明报告属于监管机关，需核对原始署名和发布机构。')
            if (re.search(r'暗示|表明|说明', line) and re.search(r'龙头.{0,8}尚未成型|仍处于.{0,6}初步建成', line)
                    and any('规划' in str(f.get('source_title') or '') and re.search(r'培育|初步建成', str(f.get('evidence_quote') or '')) for f in rows)):
                add('roadmap_as_current_state', '历史规划的目标措辞不能作为当前龙头或产业体系尚未形成的证据，需核对目标年度和现状材料。')
        # A source's publication date does not license rebasing its old counts.
        if re.search(r'\d+\s*(?:项|家|个)', scan):
            year = re.search(r'截至\s*(20\d{2})|\b(20\d{2})-\d{2}-\d{2}.{0,12}as_of_date', scan)
            if year and not _qualified(line):
                claimed = next(g for g in year.groups() if g)
                dated = [f for f in rows if re.match(r'20\d{2}', str(f.get('published_date') or f.get('date') or ''))]
                if dated and all(claimed > str(f.get('published_date') or f.get('date'))[:4]
                                 and claimed not in str((f.get('numeric_context') or {}).get('period') or '')
                                 and claimed not in str(f.get('evidence_quote') or '') for f in dated):
                    add('statistic_asof_rebased', '旧来源的累计数量不能按报告截止日更新为当前统计，需保留原始披露时点或取得新披露。')
    return issues


def independent_origin_keys(facts):
    """Collapse explicit common originals and verbatim republications only.

    Distinct keys remain a minimum cardinality check, not proof of independence.
    """
    from industry_research import source_document_key
    keys = set()
    for fact in facts:
        original = source_document_key(fact.get('original_source_url') or '')
        publisher = str(fact.get('original_publisher') or '').strip().lower()
        quote = re.sub(r'\s+|[*#]', '', str(fact.get('evidence_quote') or ''))
        if original or publisher:
            key = ('original', original or publisher)
        elif len(quote) >= 12:
            key = ('quote', quote)
        else:
            key = ('document', source_document_key(fact.get('source_url') or ''))
        keys.add(key)
    return keys


def reader_evidence_excerpt(fact, limit=160):
    """The audit table cannot republish an assertion rejected in the body."""
    from industry_research import risk_fact_text, claim_semantic_issues
    from industry_grounding import complete_excerpt, sample_boundary
    locator = (fact.get('provenance') or {}).get('locator') or {}
    if fact.get('eligible_for_report') is False or (locator and locator.get('status') != 'verified'):
        return '原文定位或适用性未通过，不转述信息点。'
    if fact.get('claim_type') == 'source_excerpt' and not complete_excerpt(fact.get('evidence_quote') or '', limit):
        return '定位摘录未形成完整信息点，需核对原文，不补写残句。'
    text = risk_fact_text(fact)
    from industry_passages import passage_issues
    if passage_issues(text):
        return '原文含乱码、缺字或不完整结构，暂不转述；请回原始来源核对。'
    boundary = sample_boundary(fact)
    prefix = '样本观察，不能外推行业整体：' if boundary else ''
    # Check before adding a sample/unknown disclaimer; a suffix cannot cure a
    # false penalty scope, rewritten growth metric or unsupported inference.
    checks = claim_semantic_issues(text, [fact])
    if checks:
        return '该来源表述未通过引用或主张边界核验，暂不转述；请核对原文及适用范围。'
    if len(prefix + text) > limit:
        text = complete_excerpt(text, limit-len(prefix))
    if not text:
        return '定位摘录未形成完整信息点，需核对原文，不补写残句。'
    return prefix + text
