"""Turn commissioner questions into bounded, auditable retrieval requirements.

Question text is a search instruction, never evidence. Topic matching only opens
a source candidate; it does not certify a finding or personal responsibility.
"""
import hashlib
import re

TOPICS = (
    ('ownership', '持股及权益', ('持股', '股权', '股东', '持有股份', '股份变动', '增持', '减持', 'shareholding', 'shareholder', 'ownership'), '持股 变动 公告', (9,)),
    ('career', '任职及职责', ('任职', '履历', '职务', '职位', '董事', '总经理', '角色', '高管', 'career', 'appointed', 'position', 'director'), '任职 历史 职务 公告', (2, 6, 9)),
    ('education', '教育与资格', ('教育', '学历', '毕业', '学校', '学位', '大学', 'education', 'degree', 'university'), '教育 毕业 官方 简介', (2,)),
    ('relations', '关联关系', ('关联', '代持', '实控', '实际控制', '控制权', '表决权', 'related party', 'control'), '关联 关系 交易 披露', (9,)),
    ('legal', '司法及契约事项', ('司法', '诉讼', '裁判', '案号', '被执行', '执行案号', '执行法院', '强制执行', '处罚', '冻结', '欠薪', '债务', '违约', '契约', '履约', '承诺', '偿还', 'litigation', 'lawsuit', 'penalty', 'debt', 'contract'), '案件 当事人 案号 裁判 履约 承诺 原文', (7, 9, 12)),
    ('ipr', '知识产权', ('知识产权', '专利', '商标', '著作权', 'patent', 'intellectual property'), '知识产权 申请人 原始记录', (9,)),
    ('operations', '经营与融资', ('经营', '融资', '业绩', '营收', '战略', '创新', 'financing', 'revenue', 'strategy'), '经营 职责 结果 公告', (4,)),
    ('management', '管理与团队', ('管理', '用人', '授权', '组织', '接班', '团队', '治理', '退出', '回购', 'management', 'team', 'delegation', 'governance', 'exit'), '管理 授权 团队 治理 退出 原文', (5, 6, 11)),
    ('comparison', '同业比较', ('同业', '对标', '比较', '可比', 'peer', 'benchmark', 'comparison'), '同业 可比人物 职责 时期', (8,)),
)


def compact(text):
    return re.sub(r'\s+', '', str(text or '')).lower()


def requirements(intake):
    values = [('special', intake.get('special_requirements') or '')]
    focus = intake.get('focus_questions') or []
    if isinstance(focus, str):
        focus = focus.splitlines()
    values.extend(('focus', q) for q in focus)
    rows, seen = [], set()
    for origin, value in values:
        # Split instructions, but keep conjunctions so a single question can
        # explicitly contain both holdings and career requirements.
        for part in re.split(r'[\n；;。！？!?]+', str(value)[:2400]):
            question = part.strip(' ，,、')[:320]
            if not question:
                continue
            found = [topic for topic in TOPICS if any(compact(t) in compact(question) for t in topic[2])]
            if not found:
                cleaned = re.sub(r'请|核查|核对|是否|关于|评估|验证|关注|了解|调查|目标人物|相关情况', ' ', question)
                terms = tuple(re.findall(r'[\u4e00-\u9fff]{2,8}|[A-Za-z]{3,}', cleaned))[:8]
                if not terms:
                    continue
                found = [('custom', question[:60], terms, question[:120], ())]
            for key, label, terms, query, chapters in found:
                # The same topic across focus/special questions shares a budget
                # and a question record, rather than buying duplicate searches.
                signature = key if key != 'custom' else compact(question)
                if signature in seen:
                    existing = next(r for r in rows if r['signature'] == signature)
                    if question not in existing['questions']:
                        existing['questions'].append(question)
                    continue
                seen.add(signature)
                rows.append({'id': 'C-' + hashlib.sha256(signature.encode()).hexdigest()[:10].upper(),
                             'signature': signature, 'topic': key, 'question': label, 'questions': [question],
                             'origin': origin, 'terms': list(terms), 'query_terms': query,
                             'target_name': str(intake.get('target_name') or intake.get('company_name') or ''),
                             'related_chapters': list(chapters),
                             'completion_condition': '核对原文、人物角色、事件时期及适用边界；候选命中不代表核查完成'})
                if len(rows) >= 12:
                    return rows
    return rows


def matches(value, requirement):
    row = value if isinstance(value, dict) else {}
    text = str(row.get('fact', '') if row else value)
    target = compact(requirement.get('target_name'))
    # A team row about another member must not enter the target's commission,
    # even when its biography mentions working with the target.
    named = re.search(r'(?:姓名|人员名称)["\s]*[:：]["\s]*([^；;，,"\s|]+)', text)
    if named and target and compact(named[1]) != target:
        return False
    honorific = re.match(r'^([\u4e00-\u9fff]{1,3})(?:先生|女士)', text)
    if honorific and target and not target.startswith(compact(honorific[1])):
        return False
    # Source labels and legal company suffixes are not holdings, career or
    # credit evidence. Match the actual field values, never the query/title.
    text = re.sub(r'^.{1,120}?的平台记录（[^）]*）：', '', text)
    text = re.sub(r'(?:企业名称|公司名称)["\s：:]+"[^"\n]+"', '', text)
    context = row.get('person_affiliation') or {}
    for key in ('affiliation_name', 'canonical_company_name'):
        if context.get(key):
            text = text.replace(str(context[key]), '')
    if requirement['topic'] == 'legal':
        try:
            from .person_text import folded
        except ImportError:
            from person_text import folded
        literal = folded(text)
        # A circular's glossary of legal terms and company laws is not a
        # personal judicial matter or a personal undertaking.
        if re.search(r'除文义另有所指|具有以下涵义|具有上市规则|开曼公司法', literal) and not re.search(r'案号|案件编号|执行法院|本人.{0,20}承诺|出具承诺|签署.{0,20}协议|补缴.{0,15}税', literal):
            return False
    if requirement['topic'] == 'career' and not re.search(r'任职|履历|职务|职位|董事|总经理|高管|聘任|出任|担任|主管|负责|career|appointed|position|director',text,re.I):
        return False
    if requirement['topic'] == 'comparison':
        if row.get('comparison_subject'):
            return True
        return bool(re.search(r'对标|可比人物|同行.{0,8}(?:评价|对比|比较)|(?:与|和).{2,30}(?:相比|比较|对比)|同业.{0,10}(?:人物|创始人|董事长)',text))
    if requirement['topic'] == 'operations' and re.search(r'生产经营和行政管理.{0,8}独立|丰富.{0,10}管理经验',text):
        return bool(re.search(r'融资|筹资|增资|营收|营业收入|交付|投产|研发|创新项目|业务策略',text))
    if requirement['topic'] == 'relations' and row.get('claim_type') == 'person_platform_record':
        return bool(re.search(r'角色|任职|股东|董事|ownership|position', text, re.I))
    return any(compact(term) in compact(text) for term in requirement['terms'])


def event_years(text):
    # A company founding date is never evidence of an executive's appointment
    # or of the effective date of a shareholding snapshot.
    text = re.sub(r'(?:成立日期|成立时间|设立日期|注册日期)["\s：:]*[^,，;；}\n|]{0,40}', '', str(text))
    return set(re.findall(r'(?:19|20)\d{2}', text))


def assess(facts, requirement):
    candidates = [f for f in facts if matches(f, requirement)]
    direct = [f for f in candidates if f.get('subject_scope') == 'person']
    try:
        from .person_records import observation
        from .person_text import numeric_literals
    except ImportError:
        from person_records import observation
        from person_text import numeric_literals
    years = set()
    kinds = {'career':{'appointment','founding'},'ownership':{'contract'},'education':{'education'},
             'relations':{'appointment','founding','contract'}}.get(requirement['topic'])
    for f in direct:
        record = f.get('observation') or observation(f,requirement.get('target_name',''))
        values = [record.get('period',''),*[r['source_value'] for r in record.get('role_date_fields',[])]]
        values += [r['date_literal'] for r in record.get('source_events',[]) if kinds is None or r['kind'] in kinds]
        years.update(event_years(numeric_literals(' '.join(values))))
    question = ' '.join(requirement['questions'])
    historical = requirement['topic'] in {'ownership', 'career', 'relations'} and re.search(r'历史|变化|变动|历任|曾任|histor|change', question, re.I)
    gaps = []
    if not candidates:
        gaps.append('缺少与委托问题直接相关、身份匹配的原文记录')
    elif not direct:
        gaps.append('只有关联企业材料，缺少目标人物的角色或责任记录')
    if candidates and not years:
        gaps.append('缺少事件时期；平台采集日及企业成立日不能替代')
    if candidates and historical and len(years) < 2:
        gaps.append('历史变化缺少至少两个可核对时点，单次平台快照不能证明变化')
    elif candidates and historical:
        gaps.append('需逐条核对变动前后记录及生效时点；多个年份不能自行证明任职或持股变化')
    if candidates and requirement['topic'] == 'comparison':
        gaps.append('可比人物的赛道、阶段、职责和时期尚需对齐，不能因出现“比较”字样完成对标')
    return {'id': requirement['id'], 'question': requirement['question'], 'questions': requirement['questions'],
            'state': 'missing' if not candidates else 'partial' if gaps else 'ready_for_review',
            'matched_evidence_ids': [f['evidence_id'] for f in candidates if f.get('evidence_id')],
            'gaps': gaps, 'completion_condition': requirement['completion_condition']}


def search_rows(intake):
    anchor = intake.get('person_anchor') or {}
    clue = next(iter(anchor.get('known_affiliations') or anchor.get('identity_anchors') or []), '')
    target = str(intake.get('target_name') or '').replace('"', '')
    context = ' "' + str(clue).replace('"', '')[:100] + '"' if clue else ''
    return [{'module': '委托专项问题', 'query': f'"{target}"{context} {r["query_terms"]} {r["questions"][0][:80]}',
             'search_tier': 'open_web', 'person_chapters': [10], 'commission_id': r['id'],
             'commission_questions': r['questions'],
             'requirement_ids': [r['id']], 'retrieval_reason': 'commission_question', 'identity_context': anchor}
            for r in requirements(intake)]
