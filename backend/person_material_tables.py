"""Compact tables drawn from complete material, without new interpretations."""
import re


def team_table(package):
    groups = {}
    for fact in package.get('research_facts', package['facts']):
        name = fact.get('team_member_name')
        if not name or fact.get('subject_scope') != 'other_person':
            continue
        groups.setdefault((name, fact.get('team_affiliation_name') or '机构待核'), []).append(fact)
    if not groups:
        return []
    def cell(value):
        return str(value).replace('|', '/').replace('\n', ' ')
    lines = ['', '### 团队成员与历史职责线索', '',
        '下表汇总本章研究池中的具名成员；职务原词保留来源语境，不认定为现任，其他人员经历不归于目标本人。', '',
        '| 成员与机构 | 职务原词 | 日期与适用边界 | 回查编号 |', '| --- | --- | --- | --- |']
    for (name, company), facts in groups.items():
        roles, periods = [], []
        for fact in facts:
            roles += re.findall(r'(?:现任|現任|担任|擔任|出任|获委任为|獲委任為|历任|歷任|任本公司)[^。；;\n]{2,65}', fact['fact'])
            record = fact.get('observation') or {}
            periods += [r['source_value'] for r in record.get('role_date_fields', [])]
            periods += [r['date_literal'] for r in record.get('source_events', []) if r['kind'] == 'appointment']
        role = '；'.join(list(dict.fromkeys(roles))[:2]) or '完整职责原句见证据台账，职务待核'
        period = '；'.join(list(dict.fromkeys(periods))[:3]) or '尚未取得已对齐的成员任职起止字段'
        refs = ' '.join('[' + f['evidence_id'] + ']' for f in facts)
        lines.append(f'| {cell(name)} / {cell(company)} | {cell(role)} | {cell(period)} | {refs} |')
    return lines


def distinct_inherited_analyses(section_claims, chapters, limit=None):
    """Preserve accepted text, avoiding a second summary of the same support."""
    chosen, covered = [], set()
    for chapter in chapters:
        for claim in section_claims.get(chapter, []):
            if not claim.get('analysis'):
                continue
            ids = set(claim['evidence_ids'])
            if ids <= covered:
                continue
            chosen.append({**claim, 'inherited_from_chapter': chapter})
            covered.update(ids)
            break
        if limit is not None and len(chosen) >= limit:
            break
    return chosen
