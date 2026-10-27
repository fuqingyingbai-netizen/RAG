"""Present every admitted professional record with its original scope intact."""
import json
import re
from collections import defaultdict


def cell(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str('未载明' if value is None or value == '' else value).replace('|', '\\|').replace('\n', ' ')


def relationship_groups(facts):
    groups = {}
    for f in facts:
        if f.get('claim_type') != 'person_platform_record':
            continue
        raw = re.search(r'\{.*\}', f['fact'], re.S)
        if not raw:
            continue
        try:
            row = json.loads(raw[0])
        except ValueError:
            continue
        company = row.get('企业名称') or row.get('公司名称')
        if not company:
            continue
        historical = 'historical' in f['source_url'] or '；历史记录；' in f['fact']
        group = groups.setdefault((company, historical), {'fields':defaultdict(list), 'ids':[]})
        for k,v in row.items():
            if v not in ('', [], None) and v not in group['fields'][k]:
                group['fields'][k].append(v)
        if f['evidence_id'] not in group['ids']:
            group['ids'].append(f['evidence_id'])
    return groups


def _primary_structured_tables(package):
    chapter = package['chapter']
    facts = package.get('research_facts', package['facts'])
    if chapter == 9:
        groups = relationship_groups(facts)
        if not groups:
            return []
        count = len({eid for g in groups.values() for eid in g['ids']})
        lines = ['', '### 专业平台关联记录完整归并表', '',
            f'将本章{count}条平台记录按企业及历史标记归并为{len(groups)}行，同一企业不同工具的字段保留并列。'
            '“平台所列”不认定现任，企业状态不认定个人风险；成立日期不是个人任职起点，空日期不是任期至今。', '',
            '| 企业及记录类别 | 职务、角色与持股原字段 | 日期原字段 | 企业背景原字段 | 回查编号 |',
            '| --- | --- | --- | --- | --- |']
        for (company, historical), g in groups.items():
            role, dates, other = [], [], []
            for key, values in g['fields'].items():
                if key in {'企业名称','公司名称'}:
                    continue
                dest = dates if re.search('时间|日期', key) else role if re.search('角色|职位|职务|持股',key) else other
                dest.extend(key+'：'+cell(v) for v in values)
            lines.append('| '+cell(company)+('（历史）' if historical else '（平台所列）')+' | '+
                ' | '.join([cell('；'.join(role)),cell('；'.join(dates)),cell('；'.join(other)),
                            ' '.join('['+eid+']' for eid in g['ids'])])+' |')
        return lines+['']
    if chapter == 4:
        groups = {}
        for f in facts:
            if f.get('claim_type') != 'person_company_record':
                continue
            key = re.sub(r'\s+', '', f['fact'])
            group = groups.setdefault(key, {'fact':f['fact'],'subject':f.get('subject',''), 'ids':[]})
            if f['evidence_id'] not in group['ids']:
                group['ids'].append(f['evidence_id'])
        if not groups:
            return []
        count = sum(len(g['ids']) for g in groups.values())
        lines = ['', '### 关联公司背景资料归并表', '',
            f'本章{count}条合格公司背景记录按相同原文归并为{len(groups)}行，保留各来源编号。'
            '这些是平台所载公司字段，适用年份和单位以原句为准；不用于推定个人贡献、个人资产、个人债务或信用。', '',
            '| 归属主体 | 平台原字段或原句 | 回查编号 |', '| --- | --- | --- |']
        lines += ['| '+cell(g['subject'])+' | '+cell(g['fact'])+' | '+
                  ' '.join('['+eid+']' for eid in g['ids'])+' |' for g in groups.values()]
        return lines+['']
    return []


def structured_tables(package):
    lines=_primary_structured_tables(package)
    if package['chapter'] not in {9,12}:return lines
    shown=set(re.findall(r'\[(E-[A-Z0-9-]+)\]','\n'.join(lines)))
    remaining=[f for f in package.get('research_facts',package['facts'])
        if f.get('claim_type')=='person_platform_record' and f['evidence_id'] not in shown]
    if remaining:
        lines += ['', '### 专业平台原始记录明细', '',
            '以下保留本章尚未归并的平台原字段。当事人、时期、生效及履行状态以原记录为准；来源原文同时附于完整证据附录。', '',
            '| 归属主体 | 平台原字段 | 回查编号 |','| --- | --- | --- |']
        lines += ['| '+cell(f.get('subject'))+' | '+cell(f['fact'])+' | ['+f['evidence_id']+'] |' for f in remaining]
    return lines
