"""Reproducible chapter comparisons and limitations over admitted propositions.

These operations add no market estimates or legal conclusions. Their supporting
IDs remain visible; semantic review and business calibration are still separate.
"""
import re
from decimal import Decimal, InvalidOperation


def observed_business(fact):
    c = fact.get('fact_contract') or {}
    text = c.get('statement') or fact.get('evidence_quote') or ''
    return (c.get('material_kind') not in {'opinion', 'proposal', 'conditional'}
            and c.get('source_role') not in {'opinion', 'commentary', 'policy_commentary', 'conditional_statement', 'recommendation'}
            and bool(re.search(r'实际.{0,20}(?:支付|收费|付费|回款)|(?:已|现有).{0,12}(?:付费客户|订阅客户|续约|回款)|披露.{0,20}(?:收入|营收)|客户按.{0,20}支付|用户按实际.{0,20}支付', text)))


def complete_plan(package, index, ids):
    """Reserve question coverage before filling with the model's ordered IDs."""
    from industry_fact_contracts import chapter_admitted, chapter_coverage
    cards = {f['evidence_id']: f for f in package.get('facts', []) if chapter_admitted(f, index)}
    def rank(eid):
        f = cards[eid]; c = f['fact_contract']
        return (not bool(c.get('sample_boundary')),
                c.get('source_role') not in {'opinion', 'commentary', 'conditional_statement', 'recommendation', 'policy_commentary'},
                c.get('source_role') == 'policy_primary',
                bool(re.search(r'应当|不得|必须|禁止', c['statement'])) if index == 3 else False,
                (f.get('numeric_context') or {}).get('is_forecast') is False if index == 4 else False,
                (f.get('numeric_validation') or {}).get('passed') is True,
                float(f.get('quality_score') or 0), eid in ids)
    chosen = []
    for question in chapter_coverage(package, index, list(cards)):
        candidates = question['evidence_ids']
        eid = max(candidates, key=rank) if candidates else None
        if eid and eid not in chosen:
            chosen.append(eid)
    seen_events = set()
    result = []
    ordered = chosen + list(ids)
    if index == 5:
        ordered = sorted(dict.fromkeys(ordered), key=lambda eid: rank(eid) if eid in cards else (), reverse=True)
    for eid in ordered:
        if eid in result or eid not in cards:
            continue
        text = cards[eid]['fact_contract']['statement']
        if index == 5:
            event = re.search(r'《([^》]+)》', text)
            if event:
                # The same promulgation may lead with its approval date in one
                # source and publication date in another. An explicit effective
                # date identifies that version without merging later amendments.
                effective = re.search(r'自(?:(20\d{2})年|今年|本年)?(\d{1,2})月(\d{1,2})日(?:起)?(?:施行|生效)', text)
                date = effective or re.search(r'(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日', text)
                key = (event[1], 'draft' if re.search(r'征求意见', text) else 'published',
                       ((date[1] or str(cards[eid].get('published_date') or '')[:4]), int(date[2]), int(date[3])) if date else '')
                if key in seen_events:
                    continue
                seen_events.add(key)
        result.append(eid)
        if len(result) == 8:
            break
    return result


def market_table(cards):
    """Consolidate identical observations, retaining every selected definition.

    Equal displayed values are not proof of equal methods or independent sources.
    """
    from industry_research import number_key
    from industry_grounding import display_text
    from industry_fact_contracts import statement_markdown
    grouped = {}
    for f in cards:
        ctx = f.get('numeric_context') or {}; c = f['fact_contract']
        if not ctx or not (f.get('numeric_validation') or {}).get('passed'):
            continue
        metric = re.sub(r'核心产业规模', '产业规模', display_text(ctx.get('metric')))
        key = (metric, ctx.get('period'), ctx.get('geography'), c.get('value_nature'),
               c.get('comparator'), number_key(str(ctx.get('value')) + str(ctx.get('unit'))))
        grouped.setdefault(key, []).append(f)
    if not grouped:
        return '', set()
    lines = ['| 期间与数值性质 | 来源列示值 | 分别保留的统计口径与出处 |', '| --- | --- | --- |']
    included = set()
    labels = {'forecast':'预测/目标值', 'estimate':'来源估计值', 'historical_base':'历史基期值', 'reported':'来源报告值'}
    for group in grouped.values():
        f = group[0]; ctx = f['numeric_context']; c = f['fact_contract']
        symbol = {'>':'超过', '>=':'不少于', '<':'低于', '<=':'不超过', 'approx':'约'}.get(c.get('comparator'), '')
        definitions = {}
        for row in group:
            definition = display_text(row['numeric_context'].get('definition')).strip()
            definition = re.sub(r'20\d{2}\s*年?|\s', '', definition).replace('我国', '中国')
            definitions.setdefault(definition, []).append('[' + row['evidence_id'] + ']')
            included.add(row['evidence_id'])
        fields = [str(ctx.get('period', '')) + ' ' + labels.get(c.get('value_nature'), '来源报告值'),
                  str(ctx.get('geography', '')) + ' ' + str(ctx.get('metric', '')) + '：' + symbol + str(ctx.get('value')) + str(ctx.get('unit')),
                  '；'.join(statement_markdown(k) + ' ' + ' '.join(v) for k,v in definitions.items())]
        lines.append('| ' + ' | '.join([statement_markdown(x).replace('|', '/') for x in fields[:2]] + [fields[2]]) + ' |')
    return ('相同期间与列示值合列展示，统计定义和出处分别保留；合列不表示口径已经统一或来源相互独立。\n\n'
            + '\n'.join(lines)), included


def statement_lineage_present(fact, section, package, index):
    """Verify canonical prose or a deterministically reconstructed market row.

    An E-ID alone, or an arbitrary row with the same amount, is not lineage.
    """
    from industry_fact_contracts import statement_markdown
    statement = (fact.get('fact_contract') or {}).get('statement') or ''
    eid = fact['evidence_id']
    if any(statement_markdown(statement) in line and eid in line for line in section.splitlines()):
        return bool(statement)
    if index != 4:
        return False
    by_id = {f['evidence_id']:f for f in package.get('facts', []) if f.get('fact_contract',{}).get('report_admitted')}
    for line in section.splitlines():
        if not line.startswith('|') or eid not in line:
            continue
        ids = list(dict.fromkeys(re.findall(r'\bE-[A-Z0-9-]{6,}\b', line)))
        if any(i not in by_id for i in ids):
            continue
        expected, included = market_table([by_id[i] for i in ids])
        if eid in included and line in expected.splitlines()[4:]:
            return True
    return False


def chapter_analysis(package, index, ids):
    from industry_fact_contracts import chapter_admitted, chapter_coverage
    cards = [f for f in package.get('facts', []) if f.get('evidence_id') in ids and chapter_admitted(f, index)]
    if not cards or index in {1, 8, 9, 12, 15, 16}:
        return ''
    refs = lambda fs: ' '.join('[' + f['evidence_id'] + ']' for f in fs)
    lines = []
    if index == 2:
        chains = [f for f in cards if re.search(r'上游.{0,180}中游.{0,180}下游', f['fact_contract']['statement'])]
        if chains:
            parts = re.search(r'上游(.{1,100}?)[，,；;、。]中游(.{1,100}?)[，,；;、。]下游(.{1,100}?)(?:[。；;]|$)', chains[0]['fact_contract']['statement'])
            if parts:
                lines.append('分工对照：上游' + parts[1] + '；中游' + parts[2] + '；下游' + parts[3] + '。' + refs(chains[:1]))
            lines.append('所引材料支持按上游供给、中游集成与下游应用梳理分工。不同细分链条分别保留；尚不能据链条列举推断各环节价值份额或供需强弱。' + refs(chains[:2]))
    elif index == 3:
        primary = [f for f in cards if f['fact_contract']['source_role'] == 'policy_primary']
        duties = [f for f in primary if re.search(r'应当|不得|必须|禁止', f['fact_contract']['statement'])]
        if duties:
            for f in duties[:2]:
                duty = re.search(r'(?:第[一二三四五六七八九十百\d]+条\s*)?([^。；;]{2,35}?)(应当|不得|必须|禁止)([^。；;]{3,120})', f['fact_contract']['statement'])
                if duty:
                    lines.append('义务对象及要求：' + duty[1].strip() + duty[2] + duty[3] + '；履行和执行结果另行核对。' + refs([f]))
            lines.append('可识别的约束来自上述原文中的具体义务，后续应按义务主体核对履行材料；发布文件本身不证明已发生处罚，也不证明风险较低。' + refs(duties[:2]))
        elif primary:
            lines.append('现有原文可作为政策范围入口，但所选条款尚未提供足够的具体履行或执行结果；不能由立法目的推出监管影响已经兑现。' + refs(primary[:2]))
    elif index == 4:
        numeric = [f for f in cards if f.get('numeric_context') and (f.get('numeric_validation') or {}).get('passed')]
        pair = None
        for a in numeric:
            x = a['numeric_context']
            for b in numeric:
                y = b['numeric_context']
                definition = lambda c: re.sub(r'20\d{2}年?|\s|[，。；;]', '', str(c.get('definition') or ''))
                if (a is not b and x.get('period') != y.get('period') and definition(x) == definition(y)
                        and all(x.get(k) == y.get(k) for k in ('metric', 'unit', 'geography', 'is_forecast'))):
                    pair = (a, b)
                    break
            if pair:
                break
        if pair:
            bound = any(f['fact_contract'].get('comparator', '=') != '=' for f in pair)
            if not bound and all(re.fullmatch(r'20\d{2}', str(f['numeric_context'].get('period'))) for f in pair):
                before, after = sorted(pair, key=lambda f: f['numeric_context']['period'])
                try:
                    old, new = (Decimal(str(f['numeric_context']['value']).replace(',', '')) for f in (before, after))
                    relation = '较高' if new > old else '较低' if new < old else '相同'
                    lines.append('列示值对照：后期记录的数值' + relation + '；这是来源列示值的比较，尚不等于经方法核验的行业增长结论。' + refs([before, after]))
                except InvalidOperation:
                    pass
            lines.append(('这些数值包含下限或近似表述，只能分别列示，不能用下限变化代替实际增长率。' if bound else
                          '材料具备相同指标、单位和地域的跨期对照入口；仍须核对统计方法和样本变化，再判断是否可计算增长。') + refs(pair))
        elif numeric:
            lines.append('所选规模记录尚未组成统计定义、地域、期间和数值性质均可对照的时间序列。分别列示，暂不计算统一增速或合并不同市场口径。' + refs(numeric[:3]))
        rates = [f for f in numeric if f['fact_contract'].get('quantity_type') == 'growth']
        if rates:
            lines.append('本章增速按来源直接列示的指标和期间保留，不能从规模下限反算，也不能跨细分口径拼接。' + refs(rates[:2]))
    elif index == 5:
        lines.append('这些记录只能证明对应主体事件有公开材料。文件发布、施行和媒体转载须按同一事件合并；解释行业热度还需要关注度或传播数据，不能用事件条数替代。' + refs(cards[:2]))
    elif index == 6:
        mechanism = [f for f in cards if re.search(r'迁移成本|进入壁垒|价格战|竞争压力', f['fact_contract']['statement']) and not f['fact_contract'].get('sample_boundary')]
        if mechanism:
            lines.append('现有材料支持讨论上述迁移、进入或价格竞争机制；机制描述不能自动换算为市场集中度。仍须区分行业口径与代表企业观察。' + refs(mechanism[:2]))
        else:
            lines.append('当前仅有来源判断或企业样本，尚不能构成全行业玩家分层及集中度结论；份额判断应补齐细分市场、期间和分母。' + refs(cards[:2]))
    elif index == 7:
        measurements = next((r for r in chapter_coverage(package, index, ids) if r['question'] == '可核验性能及单位成本'), {})
        usable = measurements.get('evidence_ids', [])
        lines.append(('存在可回查的测试数值，但只有模型、硬件、负载和版本一致的记录才可横向排序；供应商测试保留样本属性。' if usable else
                      '当前材料主要说明路线、应用侧约束或来源观点，尚无同条件测试形成的性能与单位成本对照。因此不对路线作胜负或成本优势排序。') + refs(cards[:2]))
    elif index == 10:
        actual = [f for f in cards if observed_business(f)]
        for label, pattern in [('按量计费', r'按量计费|按实际调用|词元.{0,8}收费'), ('订阅', r'订阅|续约|续费'), ('项目制', r'项目制|一次性授权')]:
            supporting = [f for f in cards if re.search(pattern, f['fact_contract']['statement'])]
            if supporting:
                status = '含实际支付或客户披露入口' if any(observed_business(f) for f in supporting) else '仅模式、观点或样本材料，实际兑现待核'
                lines.append(label + '：' + status + '。' + refs(supporting[:2]))
        lines.append(('材料包含实际支付或经营披露入口，可进一步核对客户、期间和成本；单项收费安排仍不能证明行业盈利质量。' + refs(actual[:2])) if actual else
                     ('现有材料说明计费方式、商业设想或企业样本，未形成行业实际付费和盈利兑现的完整证据链。不能从计费模式推出已规模化商用或投资确定性。' + refs(cards[:2])))
    elif index == 11:
        predictions = [f for f in cards if (f.get('numeric_context') or {}).get('is_forecast')]
        if predictions:
            lines.append('上述预测保留各自目标期和市场定义，不能混成同一条增长曲线。缺原始假设或触发条件时，只作为来源情景参考，不作为已实现规模或收益承诺。' + refs(predictions[:3]))
    elif index == 13:
        lines.append('所选材料给出了潜在风险或约束的来源描述；还需逐项核对适用对象、发生条件及实际影响。证据不足保持未评分，不把资料缺口直接等同于行业经营恶化。' + refs(cards[:2]))
    if not lines:
        return ''
    return '\n\n### 材料支持的分析与边界\n\n' + '\n\n'.join(lines)
