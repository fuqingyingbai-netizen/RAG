"""Compact tables drawn from complete material, without new interpretations."""
import re
from person_text import folded


def _unique_literals(values):
    seen, result = set(), []
    for value in values:
        key = folded(value)
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def role_literals(fact):
    if fact.get('team_role_literal'):
        return [fact['team_role_literal']]
    text = fact['fact']
    matches = list(re.finditer(r'现任|現任|担任|擔任|出任|获委任为|獲委任為|历任|歷任|任本公司', text))
    candidates = []
    for match in matches:
        prefix = text[max(0, match.start()-20):match.start()]
        if re.search(r'不得|禁止|不符合|不适合|不能', prefix):
            continue
        remainder = text[match.start():]
        end = re.search(r'[，,。；;、]', remainder)
        literal = remainder[:end.start()] if end else remainder
        if re.search(r'情形|资格|禁止|不得', literal) or len(literal) < 5:
            continue
        # Only remove layout whitespace between Chinese characters. Never
        # cut a role at a PDF line wrap or arbitrary character count.
        literal = re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])', '', literal)
        candidates.append((0 if match[0] in {'现任', '現任'} else 1, literal))
    return [literal for _, literal in sorted(candidates, key=lambda row: row[0])]


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
        '| 成员与机构 | 职务原词（仅合并排版换行） | 原文事件日期（非现职任期） | 回查编号 |', '| --- | --- | --- | --- |']
    for (name, company), facts in groups.items():
        roles, periods = [], []
        for fact in facts:
            roles += role_literals(fact)
            record = fact.get('observation') or {}
            if fact.get('team_source_kind') != 'explicit_company_role_in_article':
                periods += [r['field'] + '：' + r['source_value'] for r in record.get('role_date_fields', [])]
                periods += ['事件原词：' + r['source_quote'] for r in record.get('source_events', []) if r['kind'] == 'appointment']
        role = '；'.join(_unique_literals(roles)[:2]) or '完整职责原句见证据台账，职务待核'
        period = '；'.join(_unique_literals(periods)[:3]) or '原段日期与该成员任期尚未逐项对齐，见原文'
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
