"""Local passage roles and temporal anchors; no retrieval or model calls."""
import re


def passage_issues(text):
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
    if re.search(r'(?:占据|占有).{0,12}(?:约|大约)\s*[%％]', text):
        issues.append('missing_quantity_placeholder')
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
    if re.search(r'用户提问|如何|为什么|怎样|是否|[?？]',text):
        issues.append('question_not_assertion')
    return list(dict.fromkeys(issues))


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
    for occurrence in re.finditer(re.escape(anchor), text):
        for number in re.finditer(NUMBER_PATTERN, text[occurrence.end():]):
            if number.start() > 100 or number_key(number[0]) != expected:
                continue
            between = text[occurrence.end():occurrence.end()+number.start()]
            earlier = list(re.finditer(NUMBER_PATTERN, between))
            if earlier and not re.fullmatch(r'(?:增长|增|升|提高|下降|减少)(?:至|到)20\d{2}年(?:的)?', between[earlier[-1].end():]):
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
