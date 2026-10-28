"""Conservative typed observations and comparison guards for person research.

Fields describe what a source says, not verified real-world facts. Unspecified
subjects, units and event periods stay unknown rather than borrowing fetch dates.
"""
import json
import re
import unicodedata
try:
    from .person_text import folded
except ImportError:
    from person_text import folded


UNKNOWN = {'', '未披露', '未记录', '待查', 'unknown', 'None'}


def compact(value):
    return re.sub(r'\s+', '', str(value or '')).lower()


def payload(text):
    start = text.find('{')
    if start >= 0:
        try:
            value, _ = json.JSONDecoder().raw_decode(text[start:])
            if isinstance(value, dict):
                return value
        except (ValueError, TypeError):
            pass
    return {}


def source_events(text):
    """Keep explicitly labelled event dates, with their literal source span."""
    characters, offsets = [], []
    for index, char in enumerate(text):
        value = folded(char)
        characters.extend(value)
        offsets.extend([index] * len(value))
    clean = ''.join(characters)
    year = r'(?:(?:19|20)\d{2}|[一二][零〇一二三四五六七八九]{3}|[零〇一二三四五六七八九]{2})年'
    date = year + r'(?:(?:\d{1,2}|[一二三四五六七八九十]{1,3})月(?:(?:\d{1,2}|[一二三四五六七八九十]{1,3})日)?)?'
    specs = [('education', r'(?P<date>' + date + r')[，,]?\s*(?:本科|研究生|硕士|博士|大学|技校|高中|初中|小学)?(?:毕业|入学|就读|获.{0,35}学位)'),
             ('appointment', r'(?P<date>' + date + r'(?:至' + date + r')?)\s*(?:起)?(?:被聘任|获委任|出任|加入|担任|任我们|任本公司)'),
             ('founding', r'(?P<date>' + date + r')(?:(?!' + year + r'|出生|毕业)[^。；;]){0,20}?(?:共同创办|联合创办|创办|创立)(?!人|者)'),
             ('contract', r'(?P<date>' + date + r')(?:(?!' + year + r'|成立|出生)[^。；;]){0,30}?(?:签署|签订|转让|赠与|出具承诺)'),
             ('management', r'(?P<date>' + date + r')(?:(?!' + year + r'|出生|毕业|出版)[^。；;]){0,110}?(?:宣布.{0,12}(?:裁撤|接班|退休|计划)|推行.{0,12}(?:计划|制度|工资)|内部(?:信|邮件))'),
             ('publication', r'(?P<date>' + date + r')\s*出版')]
    rows = []
    for kind, pattern in specs:
        for match in re.finditer(pattern, clean):
            if kind in {'founding', 'contract', 'management'} and re.search(r'出生[于於]?\s*$', clean[max(0, match.start()-8):match.start()]):
                continue
            start, end = match.span('date')
            literal = text[offsets[start]:offsets[end-1]+1]
            quote = text[offsets[match.start()]:offsets[match.end()-1]+1]
            if (kind, literal) not in {(r['kind'], r['date_literal']) for r in rows}:
                rows.append({'kind': kind, 'date_literal': literal, 'source_quote': quote})
    return rows


def observation(fact, target, aliases=()):
    text = str(fact.get('fact') or '')
    data = payload(text)
    context = fact.get('person_affiliation')
    context = context if isinstance(context, dict) else {}
    issuer = str(data.get('企业名称') or data.get('公司名称') or context.get('canonical_company_name') or context.get('affiliation_name') or fact.get('team_affiliation_name') or '')
    named = re.search(r'(?:姓名|人员名称)["\s]*[:：]["\s]*(.+?)(?=\s+(?:出生日期|出生年月|国籍|籍贯|职位|职务|任职|所在地)|[；;，,\n"|]|$)', text)
    team_name = str(fact.get('team_member_name') or '') if fact.get('claim_type') == 'person_team_member_record' else ''
    named_person = str(data.get('人员名称') or data.get('姓名') or (team_name if team_name and compact(team_name) in compact(text) else '') or (named[1].strip() if named else ''))
    table_person = re.match(r'^([\u4e00-\u9fff]{2,4})\s+(?:副董事长|董事长|董事|执行董事|总裁|总经理|财务总监)', text)
    if not named_person and table_person:
        named_person = table_person[1]
    forms = [target, *aliases]
    def same_person(value):
        plain = re.split(r'[（(]', value, maxsplit=1)[0].strip()
        if any(folded(plain) == folded(n) for n in forms):
            return True
        parts = str(target).split()
        return bool(len(parts) == 2 and all(re.fullmatch(r"[A-Za-z'-]+", p) for p in parts)
                    and re.fullmatch(re.escape(parts[0]) + r'\s+(?:[A-Z]\.\s*|[A-Z]\s+){0,2}' + re.escape(parts[1]), plain, re.I))
    other = bool(named_person and not same_person(named_person))
    honorific = re.match(r'^([\u4e00-\u9fff]{1,3})(?:先生|女士|老师|教授|律师)', folded(text))
    if honorific and not folded(target).startswith(folded(honorific[1])):
        other = True
        named_person = named_person or honorific[0]
    # A shared surname is not identity. Listed-company bios often describe a
    # sibling as "王先生...为...王某某先生的兄长" in the same excerpt.
    for form in forms:
        if not form:
            continue
        # A possessive mention names the relative as the actor. In particular,
        # "X之子...毕业/加入公司" does not describe X's education or appointment.
        # Keep the unsplit original as background; do not invent a verified name.
        normalized_text = compact(folded(text))
        kin = re.search(re.escape(compact(folded(form))) + r'(?:先生|女士)?'
            r'(?P<relation>之子(?!公司)|之女|的儿子|的女儿|的配偶|的父亲|的母亲|的兄长|的弟弟|的姐姐|的妹妹)', normalized_text)
        if kin:
            relative_clause = re.split(r'[。；;]', normalized_text[kin.end():], maxsplit=1)[0]
            repeated_target = re.search('|'.join(re.escape(compact(folded(n))) for n in forms if n), relative_clause)
            if repeated_target:
                relative_clause = relative_clause[:repeated_target.start()]
            if re.search(r'毕业|留学|就读|入学|获.{0,12}学位|加入|出任|担任|获委任|被聘任|被执行|被处罚|被判|刑拘', relative_clause):
                relation = {'之子': '儿子', '之女': '女儿'}.get(kin['relation'], kin['relation'].removeprefix('的'))
                other = True
                named_person = named_person or f'{target}的{relation}（原文亲属称谓，姓名待核）'
                break
        relative = re.search(r'([\u4e00-\u9fff]{1,4}(?:先生|女士)).{0,100}?为.{0,100}?'
                             + re.escape(compact(form)) + r'(?:先生|女士)?的(兄长|弟弟|姐姐|妹妹|配偶|父亲|母亲|儿子|女儿)', compact(text))
        if relative and compact(relative[1]).removesuffix('先生').removesuffix('女士') != compact(form):
            other = True
            named_person = named_person or f'{target}的{relative[2]}（原文：{relative[1]}）'
            break
        contextual_actor = re.search(r'在' + re.escape(compact(form)) + r'[^。；;]{0,30}?(?:之后|以后|后)[，,]?[“\"]([^”\"]{2,12})[”\"](?:加入|任|已|开始|推动)', compact(text))
        if contextual_actor:
            other, named_person = True, contextual_actor[1]
            break
    company_field=(fact.get('claim_type')=='person_company_record'
        and fact.get('subject_scope')=='affiliated_company')
    # A named manager/shareholder is a field inside an admitted company record,
    # not a reason to lose the entire company-level source observation.
    scope = 'affiliated_company' if company_field else 'other_person' if other else 'affiliated_company' if fact.get('subject_scope') == 'affiliated_company' or context else 'person'
    # Only source event fields and explicitly labelled source snapshots count
    # as periods. Birthday, company founding, page publication and collection
    # timestamps cannot complete this field.
    period = str(fact.get('event_date') or '')
    period_basis = 'event_field' if period not in UNKNOWN and re.search(r'(?:19|20)\d{2}', period) else ''
    if not period_basis:
        period = ''
        for key in ('数据基准日', '截至日期', '统计日期', '报告期'):
            if data.get(key) and re.search(r'(?:19|20)\d{2}', str(data[key])):
                period, period_basis = str(data[key]), 'source_snapshot_field'
                break
        if not period:
            context = folded(text)
            if scope == 'person':
                # Dates belonging to another event on the same PDF page or
                # article are not the person's holding/role snapshot.
                context = '。'.join(sentence for sentence in re.split(r'[。；;]', context)
                    if any(folded(name) in sentence for name in forms if name))
            match = re.search(r'(?:截至|截止|数据基准日|统计日期)[:：]?((?:19|20)\d{2}(?:[-年]\d{1,2}(?:[-月]\d{1,2}日?)?)?)', context)
            if match:
                period, period_basis = match[1], 'source_labelled_snapshot'
    period = re.sub(r'年|月', '-', period).rstrip('日-')
    dates = []
    for key in ('任职起止时间', '任职日期', '任职终止日', '离任日期', '生效日期'):
        if data.get(key) and re.search(r'(?:19|20)\d{2}', str(data[key])):
            dates.append({'field': key, 'source_value': str(data[key])})
    # A table may embed a literal tenure range instead of a JSON date field.
    # Full-width years are retained verbatim; birth/graduation dates cannot
    # supply this range and a document publication date is never substituted.
    if re.search(r'任期起止|任职起止|任期日期', text):
        date = r'[０-９0-9]{4}\s*年\s*[０-９0-9]{1,2}\s*月\s*[０-９0-9]{1,2}\s*日'
        tenure = re.search(date + r'\s*(?:至|到|—|－|-)\s*' + date, text)
        if tenure:
            dates.append({'field': '任期起止原文', 'source_value': tenure[0]})
    if not dates and (fact.get('literal_roster_row') or re.match(r'^[\u4e00-\u9fff]{2,4}\s*(?:董事长|董事|执行董事|总裁|总经理)', text)):
        date = r'[０-９0-9]{4}\s*年\s*[０-９0-9]{1,2}\s*月\s*[０-９0-9]{1,2}\s*日'
        tenure = re.search(date + r'\s*(?:至|到|—|－|-)\s*' + date, text)
        if tenure:
            dates.append({'field': '原文时间区间（职务对应待核）', 'source_value': tenure[0]})
    ownership_subject = ''
    for form in forms:
        group = re.search(re.escape(form) + r'(?:(?:与|和|及|、)[\u4e00-\u9fff]{2,4})?(?:夫妇|夫妻|及其配偶)',text)
        if group and re.search(r'持股|持有|股权|股份',text[group.end():group.end()+65]):
            ownership_subject = group[0]
            break
    metrics = []
    for match in re.finditer(r'(?<![\d,，.])((?:\d{1,3}(?:[,，]\d{3})+|\d+)(?:\.\d+)?)\s*(%|％|(?:万|亿)?股|(?:万|亿)?元)', text):
        context_before = text[max(0, match.start()-35):match.start()]
        unit = match[2].replace('％', '%')
        metric = ('holding_ratio' if unit == '%' and re.search(r'持股|股东|股权|持有|股份|股本|拥有公司|ownership|shareholding', context_before, re.I) else
                  'share_count' if unit.endswith('股') else
                  'revenue' if unit.endswith('元') and re.search(r'营收|营业收入|revenue', context_before, re.I) else '')
        if metric:
            # Several ownership subjects can occur in a single paragraph.
            # A couple's later stake must not relabel the person's earlier
            # individual stake or another founder's percentage.
            before = folded(text[:match.start()])
            boundary = max([0, *[m.end() for m in re.finditer(r'[。；;]|\d+(?:\.\d+)?%', before)]])
            local = before[boundary:]
            local_group = re.search(r'([\u4e00-\u9fff]{2,4}(?:夫妇|夫妻))', local)
            local_owner = local_group[1] if local_group else ''
            if not local_owner:
                # An entity outside parentheses can own the next percentage,
                # while the parentheses describe the couple's stake in that
                # entity. Do not assign both percentages to the person.
                outside = re.sub(r'[（(][^（）()]*[）)]', '', text[:match.start()])
                clause = re.split(r'[。；;]', outside)[-1]
                company = re.search(r'([A-Za-z][A-Za-z0-9&.\s-]{1,70}(?:Ltd\.?|Limited|Inc\.?|LLC))\s*(?:直接|间接)?持股\s*$',clause,re.I)
                if company:
                    local_owner = re.sub(r'\s+',' ',company[1]).strip()
            metrics.append({'metric': metric, 'value': match[1].replace(',', '').replace('，', ''), 'unit': unit,
                            'source_literal': match[0], 'period': period, 'subject': local_owner or named_person or (target if scope == 'person' else issuer), 'issuer': issuer})
    relations = []
    if any(data.get(k) for k in ('角色', '曾担任角色', '职位', '职务', '任职起止时间')) or re.search(r'任职|担任|appointed|joined', text, re.I):
        relations.append('appointment')
    if metrics or re.search(r'持股|股权|股东', text):
        relations.append('holding')
    if re.search(r'案号|裁判|诉讼|被执行|执行法院|行政处罚|litigation|lawsuit', text, re.I):
        relations.append('legal')
    direct_link = scope == 'person'
    if scope == 'affiliated_company':
        # The seed affiliation alone is not evidence that every shareholder or
        # team member in the company database is the investigation subject.
        direct_link = bool(named_person and same_person(named_person))
        if not named_person and compact(target) in compact(text) and re.search(r'股东名称|持股人|当事人|被执行人|法定代表|董事|任职|持股', text):
            direct_link = True
    gaps = []
    if scope == 'other_person':
        gaps.append('本条主要描述其他人员，不能归给目标人物')
    if not period:
        gaps.append('事件或数据基准时期未明确，禁止用采集日期补齐')
    events = source_events(text)
    for event in fact.get('team_role_events', []) if fact.get('team_source_kind') == 'explicit_company_role_in_article' else []:
        if (isinstance(event, dict) and event.get('subject') == team_name and event.get('kind') == 'appointment'
                and event.get('source_quote') and compact(event['source_quote']) in compact(text)
                and event.get('date_literal') and compact(event['date_literal']) in compact(event['source_quote'])):
            events.append(event)
    return {'subject': issuer if company_field else target if scope == 'person' else named_person or issuer, 'source_named_person': named_person, 'subject_scope': scope,
            'issuer': issuer, 'relations': relations, 'period': period, 'period_basis': period_basis, 'ownership_subject': ownership_subject,
            'role_date_fields': dates, 'source_events': events, 'metrics': metrics, 'direct_person_link': bool(direct_link),
            'source_url': fact.get('source_url', ''), 'evidence_id': fact.get('evidence_id', ''),
            'gaps': gaps, 'verification': 'source_statement_requires_review'}


def attributed_forecast(analysis,sentence,match,supports):
    """A matched source forecast is a reported view, not new arithmetic.

    All numeric, date, subject, personal-inference and semantic guards still
    apply. A source's forecast is never evidence of an achieved outcome.
    """
    from person_text import numeric_literals
    if match[0] not in {'高于','低于','多于','少于','增加','减少','提升','下降','增长','领先','落后','发生变化','发生变动'}:return False
    prefix=sentence[:match.start()]
    if (re.search(r'本报告|据此|由此|因此可|这表明|可见|已经实现|已实现|事实证明',sentence)
            or re.match(r'\s*我们(?:预计|预期|认为|判断)',sentence)):return False
    names={str(f.get('subject') or (f.get('observation') or {}).get('subject') or '') for f in supports}-{''}
    speakers=r'其|他|她|股东会|会上|采访|演讲|报道|来源|原文|公告|财报|年报'+''.join('|'+re.escape(n) for n in sorted(names))
    attributed=re.search(r'(?:'+speakers+r')[^。；;]{0,25}(?:称|说|表示|预计|预期|认为|指出|希望)',prefix)
    framed=re.match(r'^[^。；;]{0,80}?(?:报道[：:]|来源(?:称|记载|表示)|原文(?:称|载)|公告(?:称|披露)|年报(?:载|称)|财报(?:载|称)|书中(?:称|记载))',analysis)
    if not (attributed or framed) or not re.search(r'预期|预计|未来|今后|展望|有望|目标|将|以后|年后',prefix):return False
    digits=r'[零〇一二两三四五六七八九十百千万\d]+'
    time=re.compile(r'(?:(?:未来|今后|接下来|到))?'+digits+r'(?:(?:到|至|—|-|～|~)'+digits+r')?(?:年(?!度)|月|季)(?:之后|以后|之内|后|内)?')
    def anchors(text):
        return [re.sub(r'^(?:未来|今后|接下来|到)','',numeric_literals(m[0])).replace('至','到').replace('—','到').replace('-','到').replace('～','到').replace('~','到').replace('以后','后').replace('之后','后') for m in time.finditer(text)]
    wanted=anchors(prefix)
    dimensions={v for v in ('营收','收入','利润','市值','销量','销售额','员工','持股','薪酬','规模') if v in prefix[-35:]}
    polarity=lambda s:bool(re.search(r'(?:不(?:会|再|能)?|未(?:能)?|没有)[^，,。；;、]{0,5}$',s))
    for fact in supports:
        for original in re.split(r'[。！？；;\n]',folded(fact.get('fact') or '')):
            for event in re.finditer(re.escape(match[0]),original):
                before=original[:event.start()]
                if (not re.search(r'预期|预计|展望|有望|目标|将',before)
                        or re.search(r'是否|会否|否认|无法判断|没有预测|未作预测',before[-60:])
                        or polarity(prefix)!=polarity(before)
                        or not all(d in before[-50:] for d in dimensions)):continue
                existing=anchors(before)
                if wanted:
                    if existing and wanted[-1]==existing[-1]:return True
                elif not existing:
                    phrase=folded(sentence[max(0,match.start()-4):match.end()+6])
                    if len(phrase)>=6 and phrase in original:return True
    return False


def comparison_errors(analysis, supports):
    """Require aligned dimensions before a new comparison can enter a draft."""
    comparative = r'差异|矛盾|不一致|有出入|相互冲突|互相冲突|高于|低于|多于|少于|增加|减少|提升|下降|增长|领先|落后|发生变化|发生变动'
    assertions = []
    from person_text import numeric_literals
    allowed_literals = re.sub(r'\s+', '', numeric_literals(' '.join(f['fact'] for f in supports)))
    for sentence in re.split(r'[。！？；;\n]', analysis):
        for match in re.finditer(comparative, sentence):
            if attributed_forecast(analysis,sentence,match,supports):
                continue
            # A source's exact lower/upper monetary bound is an event
            # condition, not a new cross-source numerical comparison.
            if match[0] in {'高于', '低于', '多于', '少于'} and sentence[max(0, match.start()-1):match.start()] == '不':
                bound = re.match(r'不(?:高于|低于|多于|少于)\s*\d+(?:\.\d+)?\s*(?:亿元|万元|元|亿股|万股|股|%)', numeric_literals(sentence[match.start()-1:]))
                if bound and re.sub(r'\s+', '', bound[0]) in allowed_literals:
                    continue
            limitation_prefix = sentence[max(0, match.start()-48):match.start()]
            if re.search(r'(?:未说明|未披露|未提供|未载明|尚不清楚)[^，,。；;]{0,40}$', limitation_prefix):
                continue
            prefix = sentence[max(0, match.start()-20):match.start()]
            if re.search(r'(?:不能|不可|不宜|无法|尚未|不足以|不代表|不等于|不构成|不能据此|尚不能).{0,18}$', prefix):
                continue
            assertions.append(match[0])
    if not assertions:
        return []
    records = [f.get('observation') or observation(f, f.get('subject', '')) for f in supports]
    metrics = [m for r in records for m in r['metrics']]
    dimensions = {(m['metric'], m['unit']) for m in metrics}
    if len(dimensions) > 1:
        return ['incomparable_metrics_or_units']
    if any(not r['metrics'] for r in records):
        return ['comparison_basis_insufficient']
    if len({r['subject'] for r in records}) != 1 or len({r['issuer'] for r in records}) != 1:
        return ['comparison_subject_or_entity_mismatch']
    if len({m['subject'] for m in metrics}) > 1:
        return ['comparison_subject_or_entity_mismatch']
    if metrics and any(not r['issuer'] for r in records):
        return ['comparison_subject_or_entity_mismatch']
    periods = {r['period'] for r in records}
    if '' in periods or len(periods) != 1:
        return ['comparison_period_missing_or_mismatched']
    if len({f.get('source_url') for f in supports}) < 2 or not dimensions:
        return ['comparison_basis_insufficient']
    if any(t in {'高于', '低于', '多于', '少于', '增加', '减少', '提升', '下降', '增长', '领先', '落后', '发生变化', '发生变动'} for t in assertions):
        # A time-series/directional conclusion requires arithmetic and event
        # linkage, which this source-conflict check does not pretend to prove.
        return ['direction_or_change_not_verified']
    return []


def process_text(text):
    return bool(re.search(r'analysis_allowed|writing_contract|subject_scope|evidence_ids|support_quotes|identity_clues_not_facts|source_bound_draft|\bE-P[A-F0-9]{14}\b|证据禁止分析|系统提示词|按照提示词|模型必须|输出JSON|返回JSON', text, re.I))


def chapter_relevant(fact, chapter):
    text = folded(fact.get('fact', ''))
    if chapter==12 and fact.get('claim_type')=='person_platform_record' and 12 in fact.get('person_chapters',[]):
        return True
    if chapter == 7:
        if fact.get('feedback_record'):
            return True
        try:
            from .person_chapter_research import feedback_event
        except ImportError:
            from person_chapter_research import feedback_event
        return feedback_event(text, fact.get('subject', '')) or bool(
            fact.get('claim_type') == 'person_platform_record' and 7 in fact.get('person_chapters', [])
            and (fact.get('observation') or {}).get('relations') and 'legal' in fact['observation']['relations'])
    if chapter == 3 and '年度报告' in text and '法律责任' in text and re.search(r'真实.{0,8}准确.{0,8}完整', text):
        return False
    if chapter == 8 and not fact.get('comparison_subject'):
        # A loan's interbank reference rate is not a peer-comparison claim.
        text = re.sub(r'同业拆息|同业拆借(?:利率)?', '', text)
        if re.search(r'同业竞争|显失公平.{0,8}关联交易', text) and not re.search(r'对标|可比人物|同行评价|竞争对手', text):
            return False
        return bool(re.search(r'同业|对标|竞争对手|竞争者|同行评价|横向比较|比较对象|可比人物|可比企业|竞品|benchmark|competitor|comparison', text, re.I))
    if chapter == 12:
        text = text.replace('非执行董事', '').replace('执行董事', '')
        return bool(re.search(r'风险|诉讼|处罚|失信|被执行|执行案号|执行法院|强制执行|负面|监管(?:调查|措施|问询|处罚)|违规|纠纷|贪腐|舞弊|争议|risk|litigation|penalty|sanction|fraud', text, re.I))
    return True


def current_status_errors(analysis, supports):
    absence = re.search(r'未(?:显示|提供|见到|载明|说明)[^。]{0,85}(?:因此|故|所以|可见)[^。]{0,25}(?:尚处|仍处|尚未|仍未|未生效|待决)',analysis)
    if absence and not re.search(r'不能|不代表|并不|不等于',absence[0]):
        return ['absence_of_evidence_as_status']
    for match in re.finditer(r'现任|当前(?:持股|任职|担任|控制|为|是|董事|总裁|负责人)|任职.{0,12}至今', analysis):
        prefix = analysis[max(0, match.start()-16):match.start()]
        if re.search(r'是否|不能|不宜|无法|尚未|未说明|未注明|未披露|未载明|未能|不构成|不反映|需核验|不代表', prefix):
            continue
        attributed = re.search(r'(?:来源|文件|招股意向书|招股说明书|公告|报告|材料).{0,12}(?:称|载明|披露|记载).{0,10}$', prefix)
        if attributed and re.search(r'(?:未|缺少|不能|不代表|不构成).{0,22}(?:当前|时点|时期|任期|持续)', analysis):
            continue
        if any(not (f.get('observation') or {}).get('period') for f in supports):
            return ['current_status_without_effective_period']
    return []


def personal_inference_errors(analysis):
    pattern = r'(?:体现|说明|证明|反映|表明|意味着|可见|可判定|足以|因此|所以)[^。！？；;，,]{0,35}(?:个人信用|诚信|品行|人格|能力|抗压|责任心|事业心|风险偏好|风险承担意愿|承担风险的意愿|目标导向|技术自信|审慎考量|谨慎态度|违法|无风险|低风险)'
    for match in re.finditer(pattern, analysis):
        prefix = analysis[max(0, match.start()-14):match.start()]
        if re.search(r'不能|无法|不足以|不代表|尚未|不宜', prefix) or (match[0].startswith('足以') and prefix.endswith('不')):
            continue
        return ['personal_conclusion_not_verified']
    return []


def definition_errors(analysis, supports):
    from person_text import numeric_literals
    allowed = ' '.join(f['fact'] for f in supports)
    errors = []
    for term in ('法定锁定期','法定责任','法定要求','法定义务','监管要求','法律实体独立','独立法人'):
        if term in analysis and term not in allowed:
            position=analysis.index(term)
            if not re.search(r'不能|不代表|未说明|不足以|未载明',analysis[max(0,position-18):position]):
                errors.append('legal_obligation_definition_not_supported')
    executive_tenure = re.search(r'(总裁|总经理)[，,\s]*任期[一二三四五六七八九十\d]+年',allowed)
    # A nominating chairman is not a second office whose term is asserted.
    tenure_analysis=analysis.replace('董事长提名','提名')
    from person_role_checks import role_tenures
    doc_terms={}
    for i,fact in enumerate(supports):
        key=fact.get('source_url') or ('single_record',i)
        doc_terms.setdefault(key,set()).update(role_tenures(fact['fact']))
    explicit_shared=any(('董事长',term) in pairs and ('总裁',term) in pairs
        and re.search(r'任期(?:均为|均|为)?'+re.escape(term),numeric_literals(analysis))
        for pairs in doc_terms.values() for role,term in pairs if role=='总裁')
    if (executive_tenure and re.search(r'董事长[^。；;]{0,18}(?:总裁|总经理)[^。；;]{0,8}任期',tenure_analysis)
            and not re.search(r'(?:其中|该)?(?:总裁|总经理)(?:职务)?(?:的)?任期',tenure_analysis) and not explicit_shared):
        errors.append('mixed_role_tenure_not_supported')
    separate_role_dates = re.search(r'董事长[^。；;]{0,15}任期[^。；;]{0,100}总\s*裁任期自', allowed)
    if (separate_role_dates and re.search(r'董事长[^。；;]{0,18}总裁[^。；;]{0,18}任期', tenure_analysis)
            and not re.search(r'其中.{0,10}(?:董事长|执行董事)|总裁任期自|董事长、执行董事的任期', tenure_analysis)):
        errors.append('mixed_role_tenure_not_supported')
    for match in re.finditer(r'属(?:于)?常规|为常规|符合惯例|属(?:于)?正常交易',analysis):
        if match[0] not in allowed and not re.search(r'不能|未说明|不代表|不足以',analysis[max(0,match.start()-14):match.start()]):
            errors.append('industry_norm_not_supported')
    records = [f.get('observation') or observation(f,f.get('subject','')) for f in supports]
    simultaneous = re.search(r'同时持有|同一时点持有|同期持有', analysis)
    if (len(records) > 1 and simultaneous
            and not re.search(r'是否|未说明|未披露|不能|不足以', analysis[max(0,simultaneous.start()-20):simultaneous.start()])
            and (any(not r.get('period') for r in records)
                 or len({r.get('period') for r in records}) != 1)):
        errors.append('simultaneous_ownership_period_not_supported')
    if (len(records) > 1 and re.search(r'主体[^。；;]{0,10}(?:不同|有别)|不同主体', analysis)
            and len({r.get('subject') for r in records}) == 1):
        errors.append('comparison_subject_or_entity_mismatch')
    if records and all(r.get('ownership_subject') for r in records):
        people = {r.get('subject','') for r in records}
        if (any(name and re.search(re.escape(name)+r'(?:个人|单独)?(?:持股|持有|拥有)',analysis) for name in people)
                and not re.search(r'夫妇|夫妻|配偶|共同持有|共同持股|合计持',analysis)):
            errors.append('joint_holding_as_individual')
    if re.search(r'共识事实|事实已确认|已交叉验证|已交叉印证', analysis):
        errors.append('independent_verification_not_performed')
    for match in re.finditer(r'不可采信|不可信|属虚假|内容失实', analysis):
        if match[0] not in allowed and not re.search(r'不能|不代表|不足以|无法|尚不能', analysis[max(0,match.start()-14):match.start()]):
            errors.append('source_truth_verdict_not_supported')
    clean = numeric_literals(allowed)
    canonical_analysis = numeric_literals(analysis)
    for unit in ('亿股', '万股', '亿元', '万元'):
        if unit in analysis and unit not in clean:
            errors.append('quantity_unit_not_supported')
            break
    # Numeric equality alone cannot license a changed scale or unit: 15.41%
    # must never become 15.41亿股. Require the literal quantity/unit pairing.
    quantity = r'(?<![\d.])\d+(?:\.\d+)?\s*(?:亿股|万股|股|亿元|万元|元|%|个月)'
    allowed_quantities = {compact(value) for value in re.findall(quantity, clean)}
    for value in re.findall(quantity, canonical_analysis):
        if compact(value) not in allowed_quantities:
            errors.append('quantity_unit_not_supported')
            break
    for match in re.finditer(r'连带责任', analysis):
        if '连带责任' not in allowed and not re.search(r'不能|不代表|不足以|未说明|未载明|不构成|并非|未记载', analysis[max(0, match.start()-14):match.start()]):
            errors.append('legal_obligation_definition_not_supported')
    if re.search(r'多次(?:承诺|签署|出具|被执行|强调|表示|表态)|多起诉讼', analysis) and not re.search(r'多次|先后|多起', allowed):
        event_dates = {r['date_literal'] for f in supports for r in (f.get('observation') or {}).get('source_events', []) if r['kind'] == 'contract'}
        if len(event_dates) < 2:
            errors.append('repeated_disclosure_not_repeated_event')
    if re.search(r'(?:显示|表明|体现|说明|反映)[^。；，,]{0,20}(?:控制意图|持股信心)', analysis) and not re.search(r'控制意图|持股信心', allowed):
        errors.append('personal_intention_not_supported')
    if re.search(r'同意.{0,80}转让|申请.{0,80}转让', compact(allowed)) and not re.search(r'已完成.{0,15}转让|已办理.{0,15}变更|完成.{0,15}交割', allowed):
        for clause in re.split(r'[。；，,]', analysis):
            if re.search(r'于.{0,30}向.{0,20}转让|已经?转让|完成.{0,30}转让|转让了|实际交割|已经?交割|完成.{0,15}过户|已办理.{0,15}变更', clause) and not re.search(r'同意|拟|计划|是否|未说明|未披露|未载明|不能|无法确认|不等于', clause):
                errors.append('conditional_transfer_as_completed')
                break
    conditional = re.search(r'提请.{0,35}授权|在取得.{0,35}批准|拟.{0,20}授权', compact(allowed))
    if conditional and re.search(r'被.{0,8}授权|获明确授权|已.{0,8}授权|完成授权|(?:董事会|公司|股东大会)(?:已|正式)?授权', analysis) and not re.search(r'待.{0,12}批准|取得.{0,12}批准.{0,8}后|提请|有条件|拟|尚未|须经|需经|以.{0,18}批准.{0,8}前提|不代表.*生效', analysis):
        errors.append('conditional_authorization_as_completed')
    if re.search(r'年薪|年度薪酬|年度报酬', analysis) and not re.search(r'年薪|年度薪酬|年度报酬', allowed):
        errors.append('metric_period_or_definition_not_supported')
    for match in re.finditer(r'任职.{0,16}成立(?:日|日期|时间)|成立(?:日|日期|时间).{0,16}任职', analysis):
        prefix = analysis[max(0, match.start()-20):match.start()]
        segment = analysis[match.start():match.end()+8]
        if not re.search(r'不能|不等于|不代表|不是|无法|不应', prefix + segment):
            errors.append('company_founding_date_used_as_role_date')
    return list(dict.fromkeys(errors))


def mixed_biographical_context(fact):
    """Dates in a multi-person roster need individual attribution."""
    text = folded(fact.get('fact') or '')
    people = set(re.findall(r'([\u4e00-\u9fff]{2,4})(?:先生|女士)', text))
    return len(people) >= 3 and len(re.findall(r'毕业|加入|获[^。；;]{0,16}学位',text)) >= 3


def personal_analysis_allowed(fact, conflicting=()):
    """Topic routing never changes the original source permission checks."""
    return (fact.get("subject_scope")=="person" and not fact.get("opinion_only")
            and not fact.get("source_text_issue") and fact.get("evidence_id") not in conflicting)
