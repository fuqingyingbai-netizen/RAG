"""Narrow source-to-claim contracts; these do not establish semantic truth."""
import re


def _qualified(text):
    return bool(re.search(r'不能|不得|不可|不应|不代表|不等于|不足以|不构成|并非|不是|是否|尚待|待验证|假设', text))


def absence_as_reassurance(text):
    """A neutral search limitation cannot justify a reassuring risk conclusion.

    Inspect the conclusion's own clause: a disclaimer elsewhere in a reason
    must not hide an affirmative inference. Merely recording missing execution
    material remains allowed and does not automatically reject an assessment.
    """
    absence = r'未见|尚未发现|未(?:取得|获得|查到|检索到)|无证据(?:表明|显示|证明)|没有.{0,8}(?:证据|材料|记录)'
    reassurance = (r'(?:风险|影响|冲击|压力).{0,8}(?:较低|很低|可控|有限|不大|轻微)'
                   r'|(?:低|常规|一般|正常)风险|(?:支持|表明|说明).{0,8}低风险')
    for sentence in re.split(r'[。！？\n]', text):
        clauses = re.split(r'[，,；;]', sentence)
        for i, clause in enumerate(clauses):
            if not (re.search(absence, clause) and re.search(r'处罚|准入限制|执行收紧', clause)):
                continue
            start = max(0, i-1) if re.search(r'因为|由于|鉴于|仅因|依据', clause) else i
            for conclusion in clauses[start:i+4]:
                for match in re.finditer(reassurance, conclusion):
                    prefix = conclusion[:match.start()]
                    if (not _qualified(conclusion[:match.end()])
                            and not re.search(r'删除|移除|撤回|纠正|避免|不再保留|暂不保留', prefix)):
                        return True
    return False


def _rate_kind(text):
    matches = list(re.finditer(r'CAGR|复合(?:年)?增长(?:率|速)?|年均增长(?:率|速)?|同比|环比', text, re.I))
    if not matches:
        return ''
    value = matches[-1][0].lower()
    return 'compound' if re.search(r'cagr|复合|年均', value) else value


def observation_key(fact):
    """A minimum numeric comparison key, never a certificate of methodology."""
    from industry_research import number_key
    ctx = fact.get('numeric_context') or {}
    if (fact.get('numeric_validation') or {}).get('passed') is not True:
        return None
    if not all(str(ctx.get(k) or '').strip() for k in ('metric', 'period', 'geography', 'definition', 'unit')):
        return None
    number = number_key(str(ctx.get('value')) + str(ctx.get('unit')))
    if number is None:
        return None
    definition = re.sub(r'20\d{2}年?|\s|[，,。；;：:]', '', str(ctx['definition'])).replace('我国', '中国')
    comparator = (fact.get('fact_contract') or {}).get('comparator') or ctx.get('comparator') or '='
    return (str(ctx['metric']), definition, str(ctx['geography']), number[1],
            ctx.get('value_nature') or ('forecast' if ctx.get('is_forecast') is True else 'reported'),
            str(ctx['period']), number[0], comparator)


def publisher_keys(facts):
    """Use the same conservative publisher boundary for every comparison group."""
    from industry_research import source_document_key
    publishers = set()
    for fact in facts:
        key = source_document_key(fact.get('source_url', ''))
        if not key:
            continue
        host = key.split('/')[0].split(':')[0]
        labels = host.split('.')
        depth = 3 if '.'.join(labels[-2:]) in {'com.cn','gov.cn','org.cn','net.cn','edu.cn','ac.cn','co.uk','org.uk','com.au','co.jp'} else 2
        publishers.add(host if all(x.isdecimal() for x in labels) else '.'.join(labels[-depth:]))
    return publishers


SOURCE_COUNT_PATTERN = r'(\d+|[一二两三四五六七八九十])\s*(?:个独立来源|家机构|源|份(?:独立)?(?:研究报告|报告|研究)|篇(?:研究报告|报告|文章))'


def required_source_count(text):
    """Count the sources actually claimed, including parenthetical examples."""
    chinese = dict(zip('一二两三四五六七八九十', [1,2,2,3,4,5,6,7,8,9,10]))
    return max([2] + [int(m[1]) if m[1].isdigit() else chinese[m[1]]
                      for m in re.finditer(SOURCE_COUNT_PATTERN, text)])


def comparable_corroboration(facts, required, text=''):
    """Numeric agreement needs the same observation as well as different hosts."""
    from industry_research import numeric_mentions, number_key
    comparison = re.sub(SOURCE_COUNT_PATTERN, ' ', text)
    targets = {key for n in numeric_mentions(comparison) if (key := number_key(n)) is not None}
    groups = {}
    for fact in facts:
        key = observation_key(fact)
        if key is not None:
            groups.setdefault(key, []).append(fact)
    if not groups:
        return not targets  # Qualitative entailment is outside this numeric check.
    supported = set()
    for key, group in groups.items():
        if len(publisher_keys(group)) >= required and len(independent_origin_keys(group)) >= required:
            supported.add((key[6], key[3]))
    # Unrelated agreeing cards cannot pad the particular value being claimed.
    return targets <= supported if targets else bool(supported)


def claims_observed_growth(text):
    """Keep negation and forecast qualifications local to each growth claim."""
    pattern = (r'增长持续性.{0,12}(?:支持|验证|证明)|(?:支持|证明|验证).{0,12}(?:持续增长|高增长)'
               r'|持续高增长|持续(?:稳定)?增长|增长(?:趋势|态势|势头)?(?:仍在|仍然|继续)?持续|保持增长(?:势头|态势)')
    for match in re.finditer(pattern, text):
        prefix = re.split(r'[，,。！？；;|]', text[:match.start()])[-1]
        suffix = text[match.end():]
        if (_qualified(prefix) or _qualified(match[0])
                or re.search(r'尚未|未经|未获|未被|没有', match[0])
                or re.search(r'删除|移除|撤回|纠正|避免|不再保留|暂不保留', prefix[-12:])
                or re.search(r'预计|预测|有望|或将|情景', prefix)):
            continue
        if re.match(r'性?(?:尚待|仍待|待|尚需|需|有待)(?:核验|验证|确认|评估)|(?:的|为|作为)?(?:假设|预测|情景)', suffix):
            continue
        return True
    return False


def observed_growth_series(facts):
    """Forecasts and different markets cannot supply a realized growth series."""
    groups = {}
    for fact in facts:
        key = observation_key(fact)
        if (key is None or key[4] not in {'reported', 'historical_base'} or key[7] != '='
                or not re.fullmatch(r'20\d{2}', key[5])
                or not re.search(r'规模|收入|营收|增长|同比', key[0])):
            continue
        groups.setdefault(key[:4], []).append((int(key[5]), key[6]))
    for key, values in groups.items():
        for year, value in values:
            for later, after in values:
                if later == year + 1 and ((value > 0 and after > 0) if re.search(r'同比|增长', key[0]) else after > value):
                    return True
    return False


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
        if absence_as_reassurance(line):
            add('absence_as_low_risk', '未见限制或处罚材料不能证明政策影响较低或属于常规风险，需对应义务、适用范围和执行证据。')
        if claims_observed_growth(line) and not observed_growth_series(rows):
            add('growth_trend_not_comparable', '不同市场、不同统计口径、单期增速与未来预测不能拼成已实现的持续增长证据，需同口径的历史时间序列。')
        internal = re.search(r'(?<![A-Za-z0-9_])(?:numeric_validation|allowed_numbers|eligible_for_(?:report|risk_scoring)|source_provenance_verified|(?:report|risk)_admitted)(?![A-Za-z0-9_])', line, re.I)
        validation_premise = re.search(r'(?:数值|字段|引用|定位).{0,16}(?:校验通过|检查通过|验证通过|通过.{0,8}(?:校验|检查|验证))', line)
        reliability_conclusion = re.search(r'可靠|可信|风险(?:较低|可控)|属.{0,6}(?:低|中度)', line)
        if (internal or (validation_premise and reliability_conclusion)) and not _qualified(line):
            add('internal_diagnostic_as_evidence', '内部字段、引用或数值格式校验状态不能作为行业事实、数据可靠性或风险程度的证据。')
        ranking_pattern = r'(?:位居|位列|排名|居)[^，,。；;]{0,25}(?:第[一二三四五六七八九十\d]+|首位)'
        if re.search(ranking_pattern, line) and not _qualified(line):
            from industry_research import risk_fact_text
            if not any(re.search(ranking_pattern, risk_fact_text(f)) for f in rows):
                add('ranking_source_missing', '排名判断缺少授权正文或原始排名表；来源标题、报告发布消息或选样名单不能证明名次。')
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
            if (re.search(r'缺(?:少|乏)|未(?:取得|提供|披露)|无[^。；;]{0,28}(?:证据|材料|披露|数据)', line)
                    and re.search(r'盈利(?:能力|可持续性)?[^。；;]{0,8}(?:存疑|不足|不稳|疲弱)|需求[^。；;]{0,6}(?:不振|疲软)|经营风险[^。；;]{0,6}(?:较高|上升)', line)):
                add('evidence_gap_as_business_risk', '缺少盈利或经营资料只能说明本轮评估依据不足，不能据此认定实际盈利不稳、需求疲软或经营恶化。')
            if bounded_conflict_unsupported(line, rows):
                add('compatible_bounds_as_conflict', '多个下限或相容区间不能仅因数值不同就认定冲突，须核对比较符、定义及测算时点。')
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
