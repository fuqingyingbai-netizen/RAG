"""Reader-facing conclusions bound to facts actually used in the current report.

This module does not infer a risk score or certify entailment. The synthesis call
replaces source-only summary selection; the summary then reuses whole conclusions.
"""
import hashlib
import json
import re

VERSION = 'industry-briefing-v5-developed-executive-summary'
HEADING = '### 阶段性综合结论'
ORDER = (4, 10, 7, 6, 3, 2, 13, 11, 5)


def short_conclusion(claim):
    """Display only an explicit, checked prefix of the same reviewed claim."""
    from industry_answer_quality import complete_finding
    text, finding = claim.get('text'), claim.get('conclusion')
    if claim.get('source_observation_only'):return ''
    if (claim.get('answer_quality_warning') and not claim.get('partial_parent_claim_id')
            and not (claim.get('support_review',{}).get('status')=='supported'
                     and claim.get('support_review',{}).get('answer_quality')=='answered')):
        return ''
    if (claim.get('validation_status') != 'rule_checked'
            or claim.get('claim_kind') == 'limitation' or claim.get('analysis_role') == 'material_limitation'
            or claim.get('support_review', {}).get('status') in {'partial', 'unsupported', 'contradicted'}
            or not complete_finding(finding)
            or not isinstance(text, str) or not text.startswith(finding)):
        return ''
    return finding


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()


def _basis(facts, scope):
    # Include the licensed number, statement and original locator. Same E-ID with
    # a changed statement/scope is not permission to reuse an old conclusion.
    return _hash({'scope': scope, 'facts': [{k: f.get(k) for k in (
        'evidence_id', 'fact_contract', 'numeric_context', 'numeric_validation',
        'eligible_for_report', 'evidence_scope', 'scope_match', 'provenance')}
        for f in sorted(facts, key=lambda f: f['evidence_id'])]})


def _visible(text):
    """Compare reader prose, ignoring only presentation and citation markup."""
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', str(text or ''))
    text = re.sub(r'\[E-[A-Fa-f0-9]{12}\]', '', text)
    return re.sub(r'[\s>*_`]', '', text)


def _usable_judgment(claim):
    if (claim.get('source_observation_only') or claim.get('claim_kind') == 'limitation'
            or claim.get('analysis_role') == 'material_limitation'
            or claim.get('support_review', {}).get('status') in {'partial', 'unsupported', 'contradicted'}):
        return False
    return bool(claim.get('text')) and not (claim.get('answer_quality_warning')
        and not claim.get('partial_parent_claim_id')
        and not (claim.get('support_review', {}).get('status') == 'supported'
                 and claim.get('support_review', {}).get('answer_quality') == 'answered'))


def _judgment_record(claim, chapter):
    record = {k: claim[k] for k in ('question', 'text', 'conclusion', 'evidence_ids', 'claim_kind') if k in claim}
    record['chapter'] = chapter
    record['judgment_fingerprint'] = _hash(record)
    return record


def _judgment_visible(claim, body):
    """The renderer may move an exact finding prefix into the chapter lead.

    Both pieces must remain in reader prose. An E-ID or a copy of the source
    statement below Key Evidence cannot stand in for a removed analysis.
    """
    prose = re.split(r'(?m)^###\s*(?:关键依据|材料覆盖与研究缺口)', body, 1)[0]
    text = str(claim.get('text') or '')
    if _visible(text) in _visible(prose):
        return True
    finding = short_conclusion(claim)
    if not finding or not text.startswith(finding) or text == finding:
        return False
    parts = re.split(r'(?m)^###\s*研究分析\s*$', prose, 1)
    remainder = text[len(finding):].lstrip()
    return bool(len(parts)==2 and remainder and _visible(finding) in _visible(parts[0])
        and _visible(remainder) in _visible(parts[1]))


def chapter_judgments(plans, package, sections=None):
    """Current reader-visible judgments, not a history of reused E-IDs."""
    from industry_fact_contracts import validate_analyses
    allowed = {f['evidence_id'] for f in package.get('facts', [])}
    records, seen = [], set()
    fields = {'question', 'text', 'conclusion', 'evidence_ids', 'premises', 'claim_kind', 'reasoning'}
    for chapter in ORDER:
        plan = plans.get(chapter, plans.get(str(chapter), {})) or {}
        body = None if sections is None else sections.get(chapter, sections.get(str(chapter), ''))
        for claim in plan.get('analysis_claims', []):
            if not _usable_judgment(claim) or not claim.get('evidence_ids') or not set(claim['evidence_ids']) <= allowed:
                continue
            if body is not None and not _judgment_visible(claim, body):
                continue
            if not validate_analyses([{k:v for k,v in claim.items() if k in fields}], package, chapter, list(allowed))[0]:
                continue
            record = _judgment_record(claim, chapter)
            if record['judgment_fingerprint'] not in seen:
                records.append(record); seen.add(record['judgment_fingerprint'])
    return records


def _source_basis(records):
    return _hash(sorted(r['judgment_fingerprint'] for r in records))


def _pricing_design_only(text):
    return bool(re.search(r'收费|计费|订阅|Token|商业模型|商业模式', text, re.I)
        and re.search(r'仅提出|仅(?:作为|是).{0,16}(?:方向|设计|假设)|(?:未|没有|尚未)(?:说明|披露|证实|提供|显示).{0,50}(?:实际采用|已采用|采用主体|付费客户|客户身份|收费水平|收费金额|实际收费|取得收入)', text))


def synthesis_source_issues(claim, package):
    """Known cross-chapter upgrades; this narrow check is not semantic proof.

    Revise the aggregate using the current chapter judgment, instead of making
    a source card authorize an opposite account of actual adoption.
    """
    refs = set(claim.get('evidence_ids') or [])
    sources = [r for r in package.get('source_judgments', []) if refs.intersection(r.get('evidence_ids') or [])]
    if not any(_pricing_design_only(str(r.get('text') or '')) for r in sources):
        return []
    for clause in re.split(r'[。；;]', str(claim.get('text') or '')):
        if not re.search(r'收费|计费|订阅|Token|商业模型|商业模式', clause, re.I):
            continue
        if (re.search(r'(?:计费|收费|商业模式|商业模型).{0,16}(?:转向|转为|已采用|普遍采用|已实现)|已经.{0,18}(?:采用|收费|变现)|已(?:商业化|实现盈利)', clause)
                and not re.search(r'未|没有|尚无|假设|若|如果|可能|建议|方向|设计|选项|待验证|不能据此', clause)):
            return ['synthesis_statement_nature_changed']
    return []


def synthesis_package(packages, sections, scope, plans=None):
    """Reserve different topics using canonical statements in completed chapters."""
    from industry_analysis import statement_lineage_present
    from industry_fact_contracts import chapter_admitted
    from industry_research import bounded_package
    groups, lineage = [], {}
    for chapter in ORDER:
        raw = packages.get(chapter, packages.get(str(chapter), {}))
        package = json.loads(raw) if isinstance(raw, str) else raw
        body = sections.get(chapter, '')
        rows = []
        for fact in package.get('facts', []):
            if (not fact.get('fact_contract') or not chapter_admitted(fact, 14) or not chapter_admitted(fact, 1)
                    or fact['fact_contract'].get('sample_boundary')
                    or fact.get('eligible_for_report') is False
                    or (fact.get('provenance') or {}).get('locator', {}).get('status') != 'verified'
                    or not statement_lineage_present(fact, body, package, chapter)):
                continue
            rows.append(fact)
            lineage.setdefault(fact['evidence_id'], []).append(chapter)
        plan = (plans or {}).get(chapter, (plans or {}).get(str(chapter), {}))
        used = {eid for c in plan.get('analysis_claims', []) if c.get('analysis_role') != 'material_limitation'
                for eid in c.get('evidence_ids', [])}
        rows.sort(key=lambda f: f['evidence_id'] in used, reverse=True)
        groups.append(rows)
    chosen, seen = [], set()
    eligible = {f['evidence_id']: f for group in groups for f in group}
    def assemble(cards):
        return {'facts': cards, 'industry_scope': scope,
            'synthesis_lineage': {f['evidence_id']: lineage[f['evidence_id']] for f in cards},
            'synthesis_basis': _basis(cards, scope)}
    def writer_chars(package):
        from industry_fact_contracts import plan_prompt
        return len(plan_prompt(package, 14))
    def reserve(rows):
        additions = [f for f in rows if f['evidence_id'] not in seen]
        if len(chosen)+len(additions)>8:
            return False
        projected = []
        for fact in additions:
            projected += json.loads(bounded_package({'facts': [fact]}, 14000))['facts']
        if len(projected)!=len(additions) or writer_chars(assemble(chosen+projected))>14000:
            return False
        chosen.extend(projected)
        seen.update(f['evidence_id'] for f in additions)
        return True
    # Reserve complete premises before filling individual topic cards: a partial
    # bundle cannot support reuse when the single synthesis request times out.
    from industry_fact_contracts import validate_analyses
    fields = {'conclusion', 'text', 'evidence_ids', 'premises', 'claim_kind', 'reasoning'}
    bundles = 0
    for chapter in ORDER:
        for claim in ((plans or {}).get(chapter,(plans or {}).get(str(chapter),{}))).get('analysis_claims',[]):
            refs = claim.get('evidence_ids') or []
            if (claim.get('source_observation_only') or not refs or not set(refs)<=eligible.keys() or claim.get('claim_kind')=='limitation'
                    or claim.get('analysis_role')=='material_limitation'
                    or claim.get('support_review',{}).get('status') in {'partial','unsupported','contradicted'}):
                continue
            rows = [eligible[eid] for eid in refs]
            candidate = {**{k:v for k,v in claim.items() if k in fields},'question':'总体判断及成立条件'}
            if not validate_analyses([candidate],{'facts':rows},14,refs)[0]:
                continue
            if reserve(rows):
                bundles += 1
                break
        if bundles>=4:
            break
    for offset in range(max(map(len, groups), default=0)):
        for group in groups:
            if offset < len(group) and group[offset]['evidence_id'] not in seen:
                candidate = group[offset]
                reserve([candidate])
            if len(chosen) == 8:
                break
        if len(chosen) == 8:
            break
    result = assemble(chosen)
    result['source_judgments'] = chapter_judgments(plans or {}, result, sections)
    result['source_judgment_basis'] = _source_basis(result['source_judgments'])
    # The synthesis writer receives completed, rechecked chapter judgments too,
    # instead of rediscovering their relationships from source cards alone.
    judgments = reuse_chapter_judgments(plans or {}, result)
    result['completed_chapter_judgments'] = []
    for claim in judgments:
        record = {k: claim[k] for k in ('text', 'conclusion', 'evidence_ids', 'reused_from_chapter') if k in claim}
        record['statement_nature'] = ('pricing_design_not_actual_adoption'
            if _pricing_design_only(claim['text']) else 'current_chapter_judgment_with_its_conditions')
        record['use_constraints'] = '继承本判断的主体、期间、样本、预测和已发生性质；可以解释联系，不能反向升级结论。'
        candidate = {**result, 'completed_chapter_judgments': result['completed_chapter_judgments'] + [record]}
        if writer_chars(candidate) <= 14000:
            result = candidate
    result['synthesis_input_budget'] = {'basis': 'actual_writer_prompt', 'limit_chars': 14000,
        'actual_prompt_chars': writer_chars(result), 'retained_cards': len(result['facts'])}
    return result


def bind_plan(plan, package):
    source_records = package.get('source_judgments', [])
    if source_records:
        claims = plan.get('analysis_claims', [])
        bad = [c for c in claims if synthesis_source_issues(c, package)]
        if bad:
            for claim in bad:
                plan.setdefault('analysis_rejections', []).append({'question':claim.get('question'),
                    'issues':['synthesis_statement_nature_changed'], 'original_analysis':claim.get('text'),
                    'details':[{'code':'current_chapter_boundary',
                        'message':'综合陈述与当前章节对实际采用和模式设计的判断不一致；按当前章节判断修订。'}]})
            # Keep useful siblings, then substitute the current source chapter's
            # prose for the inconsistent aggregate. Mutate the same list because
            # the caller renders it immediately after binding.
            claims[:] = [c for c in claims if c not in bad]
            fallback_plans = {chapter:{'analysis_claims':[
                r for r in source_records if r['chapter']==chapter]} for chapter in ORDER}
            existing = {_visible(c['text']) for c in claims}
            for candidate in reuse_chapter_judgments(fallback_plans, package):
                if _visible(candidate['text']) not in existing and len(claims)<4:
                    claims.append(candidate); existing.add(_visible(candidate['text']))
            plan['synthesis_alignment'] = {'revised_claims':len(bad),
                'method':'reuse_current_chapter_judgments', 'human_review_required':True}
    plan['synthesis_version'] = VERSION
    plan['synthesis_basis'] = package['synthesis_basis']
    plan['synthesis_lineage'] = package['synthesis_lineage']
    # Fingerprint exactly the projected cards supplied to the writer.
    plan['synthesis_cards'] = package['facts']
    plan['synthesis_source_judgments'] = source_records
    plan['synthesis_source_basis'] = package.get('source_judgment_basis', _source_basis(source_records))
    if package.get('synthesis_input_budget'):
        plan['synthesis_input_budget'] = package['synthesis_input_budget']


def reuse_chapter_judgments(plans, package):
    """A failed synthesis call can reuse existing analysis, never invent one."""
    from industry_fact_contracts import validate_analyses
    allowed = {f['evidence_id'] for f in package['facts']}
    candidates, seen = [], set()
    for chapter in ORDER:
        rows = (plans.get(chapter, plans.get(str(chapter), {})) or {}).get('analysis_claims', [])
        rows = sorted(rows, key=lambda c:(c.get('support_review',{}).get('status')=='supported',
            c.get('support_review',{}).get('answer_quality')=='answered'),reverse=True)
        for claim in rows:
            if (claim.get('answer_quality_warning') and not claim.get('partial_parent_claim_id')
                    and not (claim.get('support_review',{}).get('status')=='supported'
                        and claim.get('support_review',{}).get('answer_quality')=='answered')):
                continue
            if (claim.get('source_observation_only') or claim.get('claim_kind') == 'limitation' or claim.get('analysis_role') == 'material_limitation'
                    or claim.get('support_review', {}).get('status') in {'partial', 'unsupported', 'contradicted'}
                    or not set(claim.get('evidence_ids') or []) <= allowed or claim.get('text') in seen):
                continue
            if 'source_judgments' in package and not any(
                    r['chapter']==chapter and r['text']==claim['text']
                    and r['evidence_ids']==claim.get('evidence_ids') for r in package['source_judgments']):
                continue
            fields = {'conclusion', 'text', 'evidence_ids', 'premises', 'claim_kind', 'reasoning'}
            candidate = {**{k:v for k,v in claim.items() if k in fields},'question':'总体判断及成立条件'}
            kept, _ = validate_analyses([candidate],package,14,list(allowed))
            if kept:
                candidates.append({**kept[0], 'reused_from_chapter':chapter,
                    'reused_from_analysis_index':claim.get('analysis_index')})
                seen.add(claim['text'])
                break
        if len(candidates)>=4:
            break
    return candidates


def current_conclusions(report, payload, plans, scope):
    """Revalidate current cards and body lineage on first export and reexport."""
    from industry_analysis import statement_lineage_present
    from industry_fact_contracts import chapter_admitted, validate_analyses
    from industry_research import bounded_package
    plans = plans or {}
    plan = plans.get(14, plans.get('14', {}))
    if not plan.get('synthesis_basis'):
        return []
    current = {f.get('evidence_id'): f for f in payload.get('facts', [])}
    cards, ids = [], plan.get('evidence_ids', [])
    originals = plan.get('synthesis_cards', [])
    for original in originals:
        fact = current.get(original.get('evidence_id'))
        if (not fact or not chapter_admitted(fact, 14) or not chapter_admitted(fact, 1)
                or fact.get('eligible_for_report') is False
                or fact['fact_contract'].get('sample_boundary')
                or (fact.get('provenance') or {}).get('locator', {}).get('status') != 'verified'):
            return []
        found = False
        for chapter in plan.get('synthesis_lineage', {}).get(fact['evidence_id'], []):
            section = re.search(rf'(?ms)^##\s*{chapter}[.、．][^\n]*\n.*?(?=^##\s*\d+[.、．]|\Z)', report)
            if section and statement_lineage_present(fact, section[0], {'facts': list(current.values())}, chapter):
                found = True
                break
        if not found:
            return []
        # Match the same projection, including removal of raw quote from locator.
        cards.append(json.loads(bounded_package({'facts': [fact]}, 20000))['facts'][0])
    if _basis(cards, scope) != plan['synthesis_basis']:
        return []
    package = {'facts': cards, 'industry_scope': scope}
    source_records = plan.get('synthesis_source_judgments') or []
    if source_records:
        sections = {int(m[1]):m[0] for m in re.finditer(
            r'(?ms)^##\s*(\d+)[.、．][^\n]*\n.*?(?=^##\s*\d+[.、．]|\Z)', report)}
        current_records = chapter_judgments(plans, package, sections)
        package['source_judgments'] = current_records
        if _source_basis(current_records) != plan.get('synthesis_source_basis'):
            # Same source text is not permission to resurrect a replaced chapter
            # conclusion. Reuse only current prose actually visible in this report.
            return reuse_chapter_judgments(plans, package) if current_records else []
    proposed = [c for c in plan.get('analysis_claims', [])
                if c.get('claim_kind') != 'limitation' and c.get('analysis_role') != 'material_limitation'
                and not c.get('source_observation_only')
                and (not c.get('answer_quality_warning') or c.get('partial_parent_claim_id')
                     or (c.get('support_review',{}).get('status')=='supported' and c.get('support_review',{}).get('answer_quality')=='answered'))
                and c.get('support_review', {}).get('status') not in {'partial', 'unsupported', 'contradicted'}]
    # Strip audit fields before passing the original claim schema to the checker.
    fields = {'question', 'conclusion', 'text', 'evidence_ids', 'claim_kind', 'premises', 'reasoning'}
    proposed = [c for c in proposed if not synthesis_source_issues(c, package)]
    accepted, _ = validate_analyses([{k: v for k, v in c.items() if k in fields} for c in proposed], package, 14, ids)
    verdicts = {c['text']: c.get('support_review', {}) for c in proposed}
    return [{**c, 'support_review': verdicts.get(c['text'], {})} for c in accepted][:4]


def conclusion_section(claims):
    from industry_fact_contracts import statement_markdown
    if not claims:
        return ''
    lines = [HEADING, '', '以下为当前材料支持的阶段性判断，供人工复核和深化；不替代风险分或投资决策。', '']
    seen = set()
    for claim in claims:
        if claim['text'] in seen:
            continue
        seen.add(claim['text'])
        lines += ['> **' + statement_markdown(claim['question']) + '**：'
            + statement_markdown(claim['text']) + ' '
            + ' '.join('['+eid+']' for eid in claim['evidence_ids']), '']
    return '\n'.join(lines)


def refresh_conclusion_summary(report, claims, scope=None):
    """Lead with findings and keep their explanation when whole claims fit.

    The summary never manufactures an implication or cuts off a claim's final
    qualification. Extra room is spent on complete existing prose, not notices.
    """
    from industry_research import summary_length
    from industry_fact_contracts import statement_markdown
    match = re.search(r'(?ms)^##\s*1[.、．]\s*([^\n]+)\n(.*?)(?=^##\s*(?:[2-9]|1[0-6])[.、．]|\Z)', report)
    if not match:
        return report
    heading = '## 1. ' + match[1].strip() + '\n\n'
    notice = next((p for p in re.split(r'\n\s*\n', match[2].strip())
                   if p.startswith('评估与使用边界：')), '')
    if not claims:
        if not any(marker in match[2] for marker in ('阶段性判断摘要（依据正文综合评估，供人工复核深化）：', '研究摘要：')):
            return report
        # A changed source or edited body invalidates its derived summary too.
        body = '\n\n'.join(p for p in [notice, '综合结论的依据已变化，需依据当前正文重新形成阶段性判断。'] if p)
        return report[:match.start()] + heading + body + '\n\n' + report[match.end():]
    subject = str((scope or {}).get('industry_name') or '').strip()
    introduction = '研究摘要：' + ('本报告研究'+statement_markdown(subject)+'行业，主要判断如下。'
        if subject and len(subject)<=80 else '本报告主要判断如下。')
    paragraphs, kept = [introduction], []
    def render(c, body):
        return statement_markdown(body) + ' ' + ' '.join('['+eid+']' for eid in c['evidence_ids'])
    def fits(parts):
        return summary_length(heading+'\n\n'.join(parts+([notice] if notice else []))) <= 600
    seen=set()
    for claim in claims:
        if not _usable_judgment(claim) or claim['text'] in seen:
            continue
        seen.add(claim['text'])
        text = render(claim, short_conclusion(claim) or claim['text'])
        if fits(paragraphs+[text]):
            paragraphs.append(text); kept.append(claim)
    if not kept:
        return report
    # Reserve each selected finding first, then expand with complete explanations
    # so the first long topic cannot crowd out every other supported finding.
    for i,claim in enumerate(kept,1):
        sentences=[s for s in re.split(r'(?<=[。！？])',claim['text']) if s.strip()]
        if len(sentences)!=len(set(sentences)):
            continue  # Repeated wording is not extra research depth.
        candidate=list(paragraphs);candidate[i]=render(claim,claim['text'])
        if fits(candidate):paragraphs=candidate
    if notice:paragraphs.append(notice)
    return report[:match.start()] + heading + '\n\n'.join(paragraphs) + '\n\n' + report[match.end():]


def comparison_table(cards, chapter):
    """Native, editable comparison tables; no inferred quantities or rankings."""
    from industry_fact_contracts import statement_markdown
    if chapter == 2:
        for fact in cards:
            statement = fact['fact_contract']['statement']
            parts = re.search(r'上游(.{1,100}?)[，,；;、。]中游(.{1,100}?)[，,；;、。]下游(.{1,100}?)(?:[。；;]|$)', statement)
            if parts and not fact['fact_contract'].get('sample_boundary'):
                scope_label = '（具身智能来源口径）' if '具身智能' in statement else ''
                return ('### 产业分工示意'+scope_label+'\n\n| 上游 | 中游 | 下游 |\n| --- | --- | --- |\n| '
                    + ' | '.join(statement_markdown(p.strip()) for p in parts.groups()) + ' |\n\n'
                    + '分工关系按来源列示，不表示价值份额或供需强弱。 ['+fact['evidence_id']+']('+fact.get('source_url', '')+')'), set()
    if chapter == 7:
        table, included = route_comparison(cards)
        if table:
            return table, included
    if chapter not in {2, 6, 7} or len(cards) < 2:
        return '', set()
    labels = {2: ('产业链与产品', '分工或应用'), 6: ('竞争观察', '玩家或机制'), 7: ('技术对照', '路线或条件')}
    title, direction = labels[chapter]
    rows = [f'### {title}速览', '', '| 比较方向 | 原文信息 | 适用边界 |', '| --- | --- | --- |']
    included, grouped = set(), {}
    for fact in cards:
        grouped.setdefault(fact['fact_contract']['statement'], []).append(fact)
    for group in list(grouped.values())[:5]:
        fact = group[0]
        c = fact['fact_contract']; statement = c['statement']
        if len(statement) > 600:
            continue
        sample = c.get('sample_boundary')
        boundary = ('样本观察：' + sample) if sample else '来源所述范围；不据此补推份额、排名或实测性能'
        topic = '、'.join(c.get('tasks', [])) or direction
        topic = {'chain': '产业分工', 'competition': '玩家与竞争机制', 'technology': '路线与部署条件'}.get(topic, direction)
        # Equal statements can have different IDs; keep every actual citation,
        # without counting these rows as independent corroboration.
        refs = ' '.join('['+f['evidence_id']+']('+f.get('source_url', '')+')' for f in group)
        rows.append('| ' + topic + ' | ' + statement_markdown(statement) + ' ' + refs + ' | '+statement_markdown(boundary)+' |')
        included.update(f['evidence_id'] for f in group)
    return ('\n'.join(rows), included) if len(included) >= 2 else ('', set())


def route_comparison(cards):
    """Transpose an explicit three-route statement without adding test results."""
    from industry_fact_contracts import statement_markdown
    for fact in cards:
        c = fact.get('fact_contract') or {}
        if c.get('sample_boundary') or c.get('source_role') != 'source_statement':
            continue
        statement = c.get('statement') or ''
        match = re.search(r'云端((?:追求|侧重)[^，,；;。]{1,90})[，,；;]端侧((?:追求|侧重)[^，,；;。]{1,90})[，,；;]边缘侧((?:追求|侧重)[^。；;]{1,90})[。；;]?$', statement)
        if not match:
            continue
        eid = fact['evidence_id']
        prefix = statement[:match.start()].rstrip('：:，, ')
        lines = ['### 部署路线与优化目标', '']
        if prefix:
            lines += [statement_markdown(prefix)+'。 ['+eid+']', '']
        lines += ['| 部署位置 | 原文明确侧重点 |', '| --- | --- |']
        for label, value in zip(('云端', '端侧', '边缘侧'), match.groups()):
            lines.append('| '+label+' | '+statement_markdown(value)+' |')
        lines += ['', '对照依据：['+eid+']('+fact.get('source_url', '')+')。'
            '本表按原文列示优化目标；性能与成本的可比性另据同条件测试核验。']
        return '\n'.join(lines), {eid}
    return '', set()
