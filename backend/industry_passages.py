"""Local passage roles and temporal anchors; no retrieval or model calls."""
import re


def reader_proposition(text):
    """Drop an attached numbered heading only before an attributed proposition.

    The returned view is a substring. Stored source text, locator and quote are
    never rewritten, and no qualification after the attribution is removed.
    """
    text = str(text or '')
    # PDF letterheads may repeat every issuing body. Only discard the header
    # before a complete, titled promulgation statement; never edit the archive.
    title = text.find('《')
    header = text[:title] if title > 0 else ''
    if (re.search(r'([\u4e00-\u9fff]{3,35}(?:委员会|办公室|总局|部))\1', header)
            and re.search(r'第\s*\d+\s*号\s*$', header)
            and re.search(r'通过|公布|施行', text[title:])):
        text = text[title:]
    prefix = re.match(r'^[\u4e00-\u9fff]{2,25}(?:\d{1,2}[、.．]|[一二三四五六七八九十]+、)'
                      r'[\u4e00-\u9fff]{2,35}?(?=根据《|据《|报告显示|数据显示)', text)
    candidate = text[prefix.end():] if prefix else text
    return candidate if has_predicate(candidate) else text


def passage_issues(text, *, analysis=False):
    """Reject page furniture and clipped propositions, not their whole source."""
    text = str(text or '').strip()
    from text_integrity import text_issues
    issues = text_issues(text)
    if re.match(r'^(?:作者|来源|发布时间|发布日期|浏览次数)\s*[:：]', text):
        issues.append('page_furniture')
    if re.search(r'(?:^|\s)#{2,6}\s+', text):
        issues.append('embedded_markdown_heading')
    if re.search(r'(?:在场景|全球领|模型的|旨在简化)\s*[。.]?$', text):
        issues.append('incomplete_proposition')
    if re.match(r'^\s*[>＞]?\s*注[：:]\s*(?:以上|上述|以下|下表)', text):
        issues.append('dependent_caveat')
    if any(text.count(a) != text.count(b) for a, b in [('“', '”'), ('「', '」')]) or text.count('"') % 2:
        issues.append('unclosed_quotation')
    if re.search(r'全产业链梳理\s*[:：]', text) and len(re.findall(r'[、,，]', text)) >= 4:
        issues.append('title_stock_list')
    if re.search(r'\.{3,}|…{1,}', text):
        issues.append('elided_source_passage')
    if re.search(r'(?:行业主要|主要)(?:上市公司|上市企业)\s*[:：]', text):
        issues.append('title_stock_list')
    if re.search(r'(?:占据|占有).{0,12}(?:约|大约)\s*[%％]', text):
        issues.append('missing_quantity_placeholder')
    if re.search(r'Contents\s*Page|目录页', text, re.I):
        issues.append('table_of_contents')
    if re.search(r'---\s*PDF\s+page\s+\d+\s*---|目录\s*\d|文档简介|(?:^|\s)(?:Contact|For more information|Phone number|Email:)\b', text, re.I):
        issues.append('page_furniture')
    if re.search(r'\.(?:docx?|pdf)\s*[-—]|报告服务热线|浏览次数\s*[:：]|文章字号|\[.*?\]\(https?://[^)]*$', text, re.I):
        issues.append('page_furniture')
    if (len(re.findall(r'(?:^|\s)\d+(?:\.\d+){1,3}\s',text)) >= 3
            and not re.search(r'达到|同比|采用|包括|显示|表明|推出|降低|增长|下降',text)):
        issues.append('table_of_contents')
    if len(re.findall(r'(?:^|\s)[#*\\]+|\\\s*(?:财经|娱乐|房产|旅游|教育|时尚)', text)) >= 3:
        issues.append('navigation_fragment')
    if re.search(r'(?:与|以及|及|或者|包括|其中|如下|由|在|为|，|、|：|:|\(|（)\s*[。.]?$', text):
        issues.append('incomplete_proposition')
    if re.match(r'^[，,。；;：:）)"”]|^[-+−]?\d+(?:\.\d+)?\s*[%％]', text):
        issues.append('incomplete_proposition')
    # Source questions are not evidence. Authored analysis may legitimately say
    # "未说明是否可比"; interrogative words inside that statement are not a question.
    if (re.search(r'用户提问|[?？]', text)
            or (not analysis and re.search(r'如何|为什么|怎样|是否', text))
            or (analysis and re.match(r'^(?:请问|如何|为什么|怎样|是否)', text))):
        issues.append('question_not_assertion')
    return list(dict.fromkeys(issues))


def source_prefix(fact, body, limit=650):
    """Read a bounded prefix only when it belongs to the located quotation.

    The prefix supplies qualifications, never extra metrics or writing facts.
    A headline or an unbound page must not change a statement's local role.
    """
    locator = (fact.get('provenance') or {}).get('locator') or {}
    start, end = locator.get('start'), locator.get('end')
    if not (locator.get('status') == 'verified' and isinstance(start, int) and isinstance(end, int)
            and 0 <= start < end <= len(body or '')):
        return ''
    quote = str(locator.get('quote') or fact.get('evidence_quote') or '')
    if re.sub(r'\s+', '', body[start:end]).casefold() != re.sub(r'\s+', '', quote).casefold():
        return ''
    if locator.get('body_sha256'):
        import hashlib
        if hashlib.sha256(body.encode()).hexdigest() != locator['body_sha256']:
            return ''
    return body[max(0, start-limit):start]


def recommendation_context(fact, body):
    """An action item inherits its nearby advice/next-step heading, not success."""
    prefix = source_prefix(fact, body)
    quote = str(fact.get('evidence_quote') or '')
    if not prefix or not re.search(r'依托|通过|推行|优化|打造|建立|探索|降低|提升', quote):
        return False
    # A new completed result or speaker resets an earlier proposal section.
    reset = list(re.finditer(r'记者[：:]|(?:调查|结果|数据)显示|(?:已经|已于|已实现|已完成|已取得|试运行以来)', prefix))
    if reset:
        prefix = prefix[reset[-1].end():]
    if re.search(r'已经|已于|已实现|已完成|已取得|实际(?:支付|收费|回款)|调查显示', quote):
        return False
    return bool(re.search(r'为此建议[：:]|(?:下一步|未来)[，,：:]|需要[^。！？\n]{0,70}(?:商业模式|建立|完善|探索)', prefix))


def policy_obligation(text):
    """Return an explicit actor/action pair; a development principle is not one.

    This is a conservative display/coverage rule, not a full legal opinion.
    """
    text = re.sub(r'^第[一二三四五六七八九十百\d]+条\s*', '', str(text).strip())
    match = re.search(r'^([^。；;]{2,35}?)(应当|不得|必须|禁止)([^。；;]{3,160})', text)
    if not match:
        return None
    actor, modal, action = match.groups()
    if (re.search(r'产业发展|行业发展|产业体系', actor)
            or re.match(r'坚持.{0,60}原则', action)):
        return None
    return actor.strip(), modal, action


def policy_purpose_or_principle(text):
    """Recognize a complete purpose clause without a short-distance loophole."""
    text = re.sub(r'^第[一二三四五六七八九十百\d]+条\s*', '', str(text).strip())
    if policy_obligation(text):
        return False
    return bool(re.fullmatch(r'(?:为了|为)[^。！？；;]+制定(?:本|该)(?:条例|办法|规定|细则)[。]?', text)
                or re.search(r'坚持[^。！？；;]*原则|建成[^。！？；;]*高地', text))


def has_predicate(text):
    """A research heading naming topics is not a proposition about them."""
    return bool(re.search(r'是|为|有|达到|占据|占比|领先|增长|下降|提高|提升|降低|包括|形成|提供|服务|负责|采用|支付|要求|应当|不得|必须|提出|推动|支持|导致|决定|表明|显示|认为|指出|呈现|改变|影响|验证|限制|面临|建立|发布|推出|加强|追求|促进|承担|完成|减少|增多|保护|保障|走向|走到|兑现|出现|演进|保持|取得|进入|处于|成为|确定性最高|弹性最大|竞争激烈|集中度较高|集中度较低',text))


def atomic_passages(body):
    """Return original sentence spans, never a fixed-width page prefix."""
    body='\n'.join('' if len(line)<=650 and set(passage_issues(line)) & {'page_furniture','navigation_fragment','table_of_contents'}
                   else line for line in str(body or '').splitlines())
    # Join a soft CJK line wrap, not blank paragraphs or PDF page boundaries.
    body=re.sub(r'(?<=[\u4e00-\u9fffA-Za-z0-9，、])\r?\n(?=[\u4e00-\u9fff0-9（《])',' ',body)
    for paragraph in body.splitlines():
        pending = ''
        for match in re.finditer(r'[^。！？；;\n]+(?:[。！？；;][”」"]?|$)', paragraph):
            text = (pending + match[0]).strip(' -*#\t\r\n')
            problems = passage_issues(text)
            if 'unclosed_quotation' in problems and len(text) <= 650:
                pending = text
                continue
            pending = ''
            if 12 <= len(text) <= 650 and not problems:
                yield text.rstrip('。！？；;')


def temporal_years(text):
    """A money amount such as 2020亿美元 is not a year."""
    years = []
    for match in re.finditer(r'(?<!\d)(20\d{2})(?!\d)', str(text or '')):
        tail = text[match.end():]
        if re.match(r'\s*(?:亿美元|万亿美元|万亿元|亿元|万元|万美元|美元|元|%|％|家|项|台|EB|PB|TB|GB|ms)', tail, re.I):
            continue
        years.append(match[1])
    return years


def numeric_temporal_attribute(quote, metric, value, unit):
    """Bind time nature to one amount; a forecast's starting point is historical."""
    from industry_research import NUMBER_PATTERN, number_key
    text = re.sub(r'\s+', '', str(quote or ''))
    anchor = re.sub(r'\s+', '', str(metric or ''))
    expected = number_key(str(value) + unit)
    if not anchor or expected is None:
        return None
    results = []
    from industry_grounding import metric_endpoint_period
    endpoint = metric_endpoint_period(quote, metric, value, unit)
    for occurrence in re.finditer(re.escape(anchor), text):
        for number in re.finditer(NUMBER_PATTERN, text[occurrence.end():]):
            if number.start() > 100 or number_key(number[0]) != expected:
                continue
            between = text[occurrence.end():occurrence.end()+number.start()]
            earlier = list(re.finditer(NUMBER_PATTERN, between))
            if earlier and not endpoint and not re.fullmatch(r'(?:增长|增|升|提高|下降|减少)(?:至|到)20\d{2}年(?:的)?', between[earlier[-1].end():]):
                continue
            end = occurrence.end() + number.end()
            prefix = text[:occurrence.end() + number.start()]
            clauses = re.split(r'[，,；;。！？]', prefix)
            local = clauses[-1]
            if len(clauses) > 1 and re.fullmatch(r'.{0,25}(?:预计|预测|预估)(?:显示|表明|认为)?', clauses[-2]):
                local = clauses[-2] + local
            parenthetical = re.match(r'[（(]([^）)]{0,40})[）)]', text[end:])
            if parenthetical:
                local += parenthetical[1]
            if re.search(r'从20\d{2}年(?:的)?$', local) and re.match(r'(?:起)?(?:增长|增|升|提高).{0,8}(?:至|到)20\d{2}', text[end:]):
                kind = 'historical_base'
            elif re.search(r'预测|预计|预估|有望|或将|情景|假设|目标|力争|争取|将达|锚定|第[一二三]步到20\d{2}年|forecast|projected', local, re.I):
                kind = 'forecast'
            elif re.search(r'估计|估算|预估|estimated', local, re.I):
                kind = 'estimate'
            else:
                kind = 'reported'
            years = temporal_years(prefix)
            for note in re.finditer(r'(20\d{2})年?(?:数据)?(?:为|系|是)(预估|预测|预计|估计|目标)值?', text):
                if years and note[1] == years[-1]:
                    kind = 'estimate' if note[2] in {'预估', '估计'} else 'forecast'
            results.append(kind)
    return results[0] if results and len(set(results)) == 1 else None
