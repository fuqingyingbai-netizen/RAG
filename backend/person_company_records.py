"""Extract short company-level table observations for person chapter packages."""
import re


def company_records(source):
    meta = source.source_metadata or {}
    context = meta.get('person_affiliation') or {}
    company = context.get('canonical_company_name') or context.get('affiliation_name')
    if not company:
        return []
    rows, header, section = [], [], ''
    for line in str(source.content or '').splitlines():
        line = line.strip()
        if line.startswith('#'):
            section, header = line.lstrip('# ').strip(), []
            continue
        if not line.startswith('|') or not line.endswith('|'):
            continue
        cells = [x.strip() for x in line.strip('|').split('|')]
        if all(re.fullmatch(r'[:\s-]*', x) for x in cells):
            continue
        if not header:
            header = cells
            continue
        if len(cells) != len(header) or not any(cells):
            continue
        # Skip long embedded profiles/JSON blobs rather than allowing one full
        # company return to masquerade as a fact in every person chapter.
        if len(line) > 700:
            continue
        pair = len(cells) == 2 and header[0] in {'字段', '项目', '指标', '名称'}
        label = cells[0] if pair else section + ' ' + ' '.join(header)
        chapters = set()
        if re.search(r'融资|投资轮|投资时间|营收|营业收入|经营|战略|创新|产品|技术|市场|业务|简介', label):
            chapters.add(4)
        if re.search(r'团队|管理人员|高管|董事|监事|姓名|职位|职务|法定代表', label):
            chapters.add(6)
        if re.search(r'持股|股权|股东|实际控制|关联|受益|法定代表|董事|任职', label):
            chapters.add(9)
        if re.search(r'治理|董事会|决策|退出|回购|审批', label):
            chapters.add(11)
        if re.search(r'风险|诉讼|裁判|案号|执行|处罚|失信|冻结|质押|监管', label):
            chapters.update({9, 12})
        if not chapters:
            continue
        value = '；'.join(f'{k}：{v}' for k, v in zip(header, cells)) if not pair else '：'.join(cells)
        rows.append({'fact': f'{company}的平台记录（{section}）：{value}',
                     'evidence_quote': line, 'source_url': source.url, 'source_title': source.title,
                     'source_type': source.source_type, 'provider': meta.get('provider'),
                     'module': meta.get('module'), 'person_affiliation': context,
                     'category': 'person_affiliation_structured', 'claim_type': 'person_company_record',
                     'person_chapters': sorted(chapters), 'identity_confidence': meta.get('identity_confidence', 'medium'),
                     'identity_match': 'probable', 'eligible_for_report': True,
                     'retrieved_at': meta.get('retrieved_at', ''), 'event_date': '', 'published_at': ''})
    return rows[:100]
