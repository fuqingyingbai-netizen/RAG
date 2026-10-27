"""Reader-facing conclusions bound to facts actually used in the current report.

This module does not infer a risk score or certify entailment. The synthesis call
replaces source-only summary selection; the summary then reuses whole conclusions.
"""
import hashlib
import json
import re

VERSION = 'industry-briefing-v1-evidence-bound-conclusions'
HEADING = '### 阶段性综合结论'
ORDER = (4, 10, 7, 6, 3, 2, 13, 11, 5)


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
    for offset in range(max(map(len, groups), default=0)):
        for group in groups:
            if offset < len(group) and group[offset]['evidence_id'] not in seen:
                candidate = group[offset]
                seen.add(candidate['evidence_id'])
                projected = json.loads(bounded_package({'facts': [candidate]}, 14000))['facts']
                if projected and len(json.dumps({'facts': chosen + projected, 'industry_scope': scope}, ensure_ascii=False)) <= 14000:
                    chosen += projected
            if len(chosen) == 8:
                break
        if len(chosen) == 8:
            break
    result = {'facts': chosen, 'industry_scope': scope}
    result['synthesis_lineage'] = {f['evidence_id']: lineage[f['evidence_id']] for f in result['facts']}
    result['synthesis_basis'] = _basis(result['facts'], scope)
    return result


def bind_plan(plan, package):
    plan['synthesis_version'] = VERSION
    plan['synthesis_basis'] = package['synthesis_basis']
    plan['synthesis_lineage'] = package['synthesis_lineage']
    # Fingerprint exactly the projected cards supplied to the writer.
    plan['synthesis_cards'] = package['facts']


def reuse_chapter_judgments(plans, package):
    """A failed synthesis call can reuse existing analysis, never invent one."""
    from industry_fact_contracts import validate_analyses
    allowed = {f['evidence_id'] for f in package['facts']}
    candidates, seen = [], set()
    for chapter in ORDER:
        for claim in (plans.get(chapter, plans.get(str(chapter), {})) or {}).get('analysis_claims', []):
            if (claim.get('claim_kind') == 'limitation' or claim.get('analysis_role') == 'material_limitation'
                    or claim.get('support_review', {}).get('status') in {'partial', 'unsupported', 'contradicted'}
                    or not set(claim.get('evidence_ids') or []) <= allowed or claim.get('text') in seen):
                continue
            seen.add(claim['text'])
            fields = {'text', 'evidence_ids', 'premises', 'claim_kind', 'reasoning'}
            candidates.append({**{k: v for k, v in claim.items() if k in fields}, 'question': '总体判断及成立条件'})
            break
    kept, _ = validate_analyses(candidates, package, 14, list(allowed))
    return kept[:4]


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
    proposed = [c for c in plan.get('analysis_claims', [])
                if c.get('claim_kind') != 'limitation' and c.get('analysis_role') != 'material_limitation'
                and c.get('support_review', {}).get('status') not in {'partial', 'unsupported', 'contradicted'}]
    # Strip audit fields before passing the original claim schema to the checker.
    fields = {'question', 'text', 'evidence_ids', 'claim_kind', 'premises', 'reasoning'}
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


def refresh_conclusion_summary(report, claims):
    """Reuse complete conclusions; do not ask another model to expand them."""
    from industry_research import summary_length
    from industry_fact_contracts import statement_markdown
    match = re.search(r'(?ms)^##\s*1[.、．]\s*([^\n]+)\n(.*?)(?=^##\s*(?:[2-9]|1[0-6])[.、．]|\Z)', report)
    if not match:
        return report
    heading = '## 1. ' + match[1].strip() + '\n\n'
    notice = next((p for p in re.split(r'\n\s*\n', match[2].strip())
                   if p.startswith('评估与使用边界：')), '')
    if not claims:
        if '阶段性判断摘要（依据正文综合评估，供人工复核深化）：' not in match[2]:
            return report
        # A changed source or edited body invalidates its derived summary too.
        body = '\n\n'.join(p for p in [notice, '综合结论的依据已变化，需依据当前正文重新形成阶段性判断。'] if p)
        return report[:match.start()] + heading + body + '\n\n' + report[match.end():]
    paragraphs = [notice] if notice else []
    paragraphs.append('阶段性判断摘要（依据正文综合评估，供人工复核深化）：')
    kept = 0
    for claim in claims:
        text = '- ' + statement_markdown(claim['text']) + ' ' + ' '.join('['+eid+']' for eid in claim['evidence_ids'])
        if summary_length(heading + '\n\n'.join(paragraphs + [text])) <= 600:
            paragraphs.append(text); kept += 1
    if not kept:
        return report
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
