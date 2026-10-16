"""Industry source boundaries and reader-safe passages; no external requests."""
import re
from datetime import date


def sample_boundary(fact):
    text = ' '.join(str(fact.get(k) or '') for k in ('source_title', 'evidence_quote', 'fact'))
    if fact.get('evidence_scope') == 'representative_company':
        return str(fact.get('sample_boundary_reason') or '企业样本')
    if re.search(r'代表性(?:上市)?(?:企业|公司)|(?:上市企业|上市公司|企业)样本|样本(?:企业|公司)|部分上市(?:企业|公司)|selected companies', text, re.I):
        return '代表企业样本，来源所称平均值仅限该样本，不能外推行业整体'
    if fact.get('source_type') == 'filing' or re.search(r'(?:公司|股份|集团).{0,30}(?:年度报告|年报|招股书)', str(fact.get('source_title') or '')):
        return '企业披露样本'
    if fact.get('claim_type') == 'vendor_benchmark':
        return '供应商自述测试样本，测试方法及独立性待核验'
    if fact.get('claim_type') == 'benchmark_sample':
        return '技术测试样本，仅适用于对应测试条件，不能外推行业整体'
    return ''


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
    published = ''
    if match:
        try:
            published = date(*map(int, match.groups())).isoformat()
        except ValueError:
            pass
    from urllib.parse import urlsplit
    return {'source_type': source.source_type, 'provider': meta.get('provider') or meta.get('platform') or urlsplit(str(source.url or '')).hostname or '',
            'publisher': meta.get('publisher') or meta.get('author') or '', 'published_date': published,
            'date': published, 'source_object_key': getattr(source, 'object_key', '') or ''}


def metric_period_region(quote, metric, value, unit):
    """Use the local metric/value block; a later global ambition is not geography."""
    text = re.sub(r'\s+', '', quote)
    from industry_research import NUMBER_PATTERN, number_key
    for anchor in re.finditer(re.escape(re.sub(r'\s+', '', metric)), text):
        tail = text[anchor.end():]
        number = re.search(NUMBER_PATTERN, tail)
        if not number or number.start() > 60 or number_key(number[0]) != number_key(str(value) + unit):
            continue
        # A numbered roadmap stage such as "第一步到2020年" is part of this block.
        start = max(text.rfind('。', 0, anchor.start()), text.rfind(';', 0, anchor.start()), text.rfind('；', 0, anchor.start())) + 1
        prefix = text[start:anchor.end() + number.end()]
        years = re.findall(r'20\d{2}', prefix)
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
