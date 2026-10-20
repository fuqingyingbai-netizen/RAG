"""Industry source boundaries and reader-safe passages; no external requests."""
import re
from datetime import date


def sample_boundary(fact):
    text = ' '.join(str(fact.get(k) or '') for k in ('source_title', 'evidence_quote', 'fact'))
    if fact.get('evidence_scope') == 'representative_company':
        return str(fact.get('sample_boundary_reason') or '企业样本')
    if re.search(r'代表性(?:上市)?(?:企业|公司)|(?:上市企业|上市公司|企业)样本|样本(?:企业|公司)|部分上市(?:企业|公司)|selected companies', text, re.I):
        return '代表企业样本，来源所称平均值仅限该样本，不能外推行业整体'
    if re.search(r'受访.{0,12}(?:企业|公司)|企业.{0,8}调查样本', text):
        return '受访企业调查样本，不能当作行业总体或已实现营收统计'
    if fact.get('source_type') == 'filing' or re.search(r'(?:公司|股份|集团).{0,30}(?:年度报告|年报|招股书)', str(fact.get('source_title') or '')):
        return '企业披露样本'
    if fact.get('claim_type') == 'vendor_benchmark':
        return '供应商自述测试样本，测试方法及独立性待核验'
    if fact.get('claim_type') == 'benchmark_sample':
        return '技术测试样本，仅适用于对应测试条件，不能外推行业整体'
    # The subject of this passage matters more than an industry collection's
    # title. Keep generic statements about firms and aggregate statistics usable.
    quote = re.sub(r'\s+', ' ', str(fact.get('evidence_quote') or fact.get('fact') or ''))
    if (re.search(r'[\u4e00-\u9fffA-Za-z]{2,40}(?:股份有限公司|有限责任公司|有限公司|股份公司|集团)(?:则|在|已|将|拥有|提供|推出|位居|收入|业务|产品|面临|采用|实现)', quote)
            or re.search(r'旗下|本公司|我司|自家|成立以来.{0,40}(?:公司|科技创新|品牌|发展)', quote)):
        return '企业经营或产品宣传样本，不能外推行业整体'
    if re.search(r'(?:^|[，,。；;：:])\s*(?:本公司|该公司|公司|两家公司|两家企业|某公司|某企业)(?:的|在|已|将|拥有|体量|收入|业务|产品|面临|采用|提供|实现)', quote):
        return '特定企业经营观察，仅作为样本，不外推行业整体'
    named = re.match(r'^([A-Za-z][A-Za-z0-9.+-]{1,30})(?:因|已|在|宣布|推出|暂停|计划|发布)', quote)
    if named and named[1].upper() not in {'AI', 'GPU', 'CPU', 'API', 'SAAS', 'MOE', 'FDE'}:
        return '具名产品或企业个案，仅作为样本，不外推行业整体'
    actor = re.search(r'(?:^|[，,：:])\s*([\u4e00-\u9fffA-Za-z0-9]{2,24})(?:宣布|推出|暂停|入选|荣获)', quote)
    if actor and not re.search(r'行业|产业|市场|人工智能|机器人|国家|国务院|政府|委员会|部门|研究院|报告|办法|条例|指南', actor[1]):
        return '具名主体行为样本，不能外推行业整体'
    if re.search(r'^(?:[一二三四五]是)?其(?:过往|自研|产品|营收|利润|年报|模型|业务)|(?:一家|某家|该家).{0,15}(?:企业|公司|厂商)', quote):
        return '特定主体或匿名企业观察，仅作为样本，不外推行业整体'
    return ''


def growth_definition(quote, metric, value, unit):
    """Resolve a growth referent only from an adjacent, explicit measured noun.

    This does not attach a total's rate to a later sub-metric, cross a sentence,
    or supply an industry/geography/year absent from the original passage.
    """
    if not re.search(r'同比|环比|增速|增长率|增幅', str(metric)) or unit not in {'%', '％'}:
        return ''
    from industry_research import NUMBER_PATTERN, number_key
    text = re.sub(r'\s+', '', str(quote))
    anchor = re.sub(r'\s+', '', str(metric))
    expected = number_key(str(value) + unit)
    for match in re.finditer(re.escape(anchor), text):
        number = re.search(NUMBER_PATTERN, text[match.end():])
        if not number or number.start() > 12 or number_key(number[0]) != expected:
            continue
        prefix = re.split(r'[。！？；;]', text[:match.start()])[-1]
        amounts = list(re.finditer(NUMBER_PATTERN, prefix))
        if not amounts:
            continue
        previous = amounts[-1]
        if not re.fullmatch(r'[，,]?', prefix[previous.end():]):
            continue
        subject = re.search(r'([^，,：:]{2,100}?(?:核心产业规模|产业规模|市场规模|行业规模|营业收入|营收|收入|利润|总量|推理量|训练量|出货量|销量|产量|产值|企业数量|企业数))'
                            r'(?:已|为|达到|达|突破|超过|超|逾|累计|实现|约)*$', prefix[:previous.start()])
        if subject:
            # A definition names the measure, not the adjacent amount or year.
            return re.sub(r'20\d{2}年?', '', subject[1]) + anchor
    return ''


def display_text(text):
    """Reader normalization only; stored quotes, SHA256 and offsets stay intact."""
    return re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])', '', str(text or ''))


def display_source_title(title, limit=80):
    title = re.sub(r'\s+', ' ', display_text(title)).strip()
    if re.search(r'全产业链梳理\s*[:：]', title) and len(re.findall(r'[、,，]', title)) >= 4:
        title = re.split(r'[:：]', title, maxsplit=1)[0].strip()
    if len(title) > limit:
        prefix = title[:limit-1]
        cut = max(prefix.rfind('；'), prefix.rfind('。'), prefix.rfind(' - '))
        title = (prefix[:cut] if cut >= limit//2 else prefix).rstrip(' ，、:：（([') + '…'
    return title or '保存来源'


def source_markdown_link(title, url):
    import html
    label = html.escape(display_source_title(title), quote=False).replace('[', '［').replace(']', '］').replace('|', '/')
    url = str(url or '')
    if re.fullmatch(r'https?://[^\s<>]+', url):
        return '[' + label + '](' + url.replace('(', '%28').replace(')', '%29') + ')'
    return label


def complete_excerpt(text, limit=360):
    """Choose complete sentences; never turn a clipped tail into a new quotation."""
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', str(text or ''))
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if (not line or line.startswith(('#', 'http', '|', 'Posted by', '作者', '来源：', '责任编辑', 'Image:', '[Image'))
                or re.search(r'avatar|image_urls|research_questions_status|information_gaps|named_companies', line, re.I)):
            continue
        lines.append(line)
    sentences = re.findall(r'[^。！？；;\n]+[。！？；;]', '\n'.join(lines))
    result = ''
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 12 or len(sentence) > limit:
            continue
        if len(result + sentence) > limit:
            break
        result += sentence
    return result


def source_metadata(source):
    """Keep publication distinct from statistical period; no current-year default."""
    meta = source.source_metadata or {}
    published = str(meta.get('published_date') or meta.get('published_at') or meta.get('publication_date') or meta.get('date') or '')
    match = re.match(r'(20\d{2})[-/](\d{1,2})[-/](\d{1,2})', published)
    if not match:
        # Only an explicitly labelled publication date near the page header.
        match = re.search(r'(?:发布时间|发布日期|发布于|Posted by[^\n]*?)\s*[：:]?\s*(20\d{2})[年/-](\d{1,2})[月/-](\d{1,2})', str(source.content or '')[:900])
    if not match:
        # A timestamp joined to a source/byline is page metadata, unlike a
        # year embedded in a statistical sentence. Keep this header-only.
        match = re.search(r'(?m)^\s*(20\d{2})[年/-](\d{1,2})[月/-](\d{1,2})日?\s+\d{1,2}:\d{2}[^\n]{0,40}(?:来源|作者)', str(source.content or '')[:900])
    published = ''
    if match:
        try:
            published = date(*map(int, match.groups())).isoformat()
        except ValueError:
            pass
    from urllib.parse import urlsplit
    return {'source_type': source.source_type, 'provider': meta.get('provider') or meta.get('platform') or urlsplit(str(source.url or '')).hostname or '',
            'publisher': meta.get('publisher') or meta.get('author') or '', 'published_date': published,
            'original_source_url': meta.get('original_source_url') or '', 'original_publisher': meta.get('original_publisher') or '',
            'date': published, 'source_object_key': getattr(source, 'object_key', '') or ''}


def metric_period_region(quote, metric, value, unit):
    """Use the local metric/value block; a later global ambition is not geography."""
    text = re.sub(r'\s+', '', quote)
    from industry_research import NUMBER_PATTERN, number_key
    for anchor in re.finditer(re.escape(re.sub(r'\s+', '', metric)), text):
        tail = text[anchor.end():]
        number = next((n for n in re.finditer(NUMBER_PATTERN, tail) if n.start() <= 100
                       and number_key(n[0]) == number_key(str(value) + unit)), None)
        if not number:
            continue
        earlier = list(re.finditer(NUMBER_PATTERN, tail[:number.start()]))
        if earlier and not re.fullmatch(r'(?:增长|增|升|提高|下降|减少)(?:至|到)20\d{2}年(?:的)?', tail[earlier[-1].end():number.start()]):
            continue
        # A numbered roadmap stage such as "第一步到2020年" is part of this block.
        start = max(text.rfind('。', 0, anchor.start()), text.rfind(';', 0, anchor.start()), text.rfind('；', 0, anchor.start())) + 1
        prefix = text[start:anchor.end() + number.start()]
        from industry_passages import temporal_years
        years = temporal_years(prefix)
        regions = {'我国':'中国大陆', '全国':'中国大陆', '中国大陆':'中国大陆', '中国':'中国大陆', '全球':'全球', '美国':'美国', '欧洲':'欧洲', '欧盟':'欧盟'}
        matches = list(re.finditer('|'.join(regions), prefix))
        region = regions[matches[-1][0]] if matches else ''
        # Reject a region token merely describing companies ("全球领先企业").
        if matches and re.match(r'(?:领先|骨干|头部|一流).{0,8}(?:企业|公司)', prefix[matches[-1].end():]):
            region = ''
        return (years[-1] if years else '', region)
    return '', ''


TASK_PATTERNS = {
    '产业链分层': r'上游.{0,180}中游.{0,180}下游',
    '技术测试条件': r'测试环境|统一硬件|统一软件|量化精度|测试模型|测试条件|统一.{0,6}基准',
    '技术性能': r'吞吐量|token/s|响应延迟|首\s*token|推理成功率',
    '技术成本': r'单位.{0,15}成本|计费|单价|每.{0,10}元',
}


def passage_tasks(fact):
    text = str(fact.get('evidence_quote') or fact.get('fact') or '')
    return {name for name, pattern in TASK_PATTERNS.items() if re.search(pattern, text, re.I)}
