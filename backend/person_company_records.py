"""Extract complete company-level table observations for person chapter packages."""
import re


def company_records(source, audit=None):
    meta = source.source_metadata or {}
    context = meta.get('person_affiliation') or {}
    if meta.get('entity_validation')=='rejected' or meta.get('identity_confidence') in {'low','rejected'} or meta.get('fetch_status') in {'failed','blocked','empty','challenge'}:
        return []
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
        # Length controls belong to writing; preserve the qualified raw field.
        # Company scope prevents this from becoming a personal interpretation.
        pair = len(cells) == 2 and header[0] in {'字段', '项目', '指标', '名称'}
        label = cells[0] if pair else section + ' ' + ' '.join(header)
        if re.fullmatch(r'gsId|request.?id|trace.?id|接口状态|响应码|请求参数',label,re.I):
            if audit is not None:audit.append({'source_url':source.url,'field':label,'source_quote':line,'reason':'provider_metadata_not_company_fact'})
            continue
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
            chapters.add(4)
        value = '；'.join(f'{k}：{v}' for k, v in zip(header, cells)) if not pair else '：'.join(cells)
        rows.append({'fact': f'{company}的平台记录（{section}）：{value}',
                     'evidence_quote': line, 'source_url': source.url, 'source_title': source.title,
                     'source_type': source.source_type, 'provider': meta.get('provider'),
                     'module': meta.get('module'), 'person_affiliation': context,
                     'category': 'person_affiliation_structured', 'claim_type': 'person_company_record',
                     'person_chapters': sorted(chapters), 'identity_confidence': meta.get('identity_confidence', 'medium'),
                     'identity_match': 'probable', 'eligible_for_report': True,
                     'retrieved_at': meta.get('retrieved_at', ''), 'event_date': '', 'published_at': ''})
    return rows
