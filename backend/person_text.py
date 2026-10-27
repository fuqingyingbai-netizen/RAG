"""Comparison-only Chinese/Unicode folding; never rewrite quoted originals."""
import re
import unicodedata
from functools import lru_cache
from opencc import OpenCC

_simplify = OpenCC('t2s')


def numeric_literals(text):
    """Equivalent numeral spelling only; never convert a quantity's scale/unit."""
    text = unicodedata.normalize('NFKC', str(text or ''))
    # Grouping separators are numeral spelling, not separate quantities.
    # Preserve the original quote elsewhere; comparison uses a whole token.
    text = re.sub(r'(?<![\d.])\d{1,3}(?:[,，]\d{3})+(?:\.\d+)?(?!\d)',
                  lambda m: m[0].replace(',', '').replace('，', ''), text)
    digits = {c: i for i,c in enumerate('零一二三四五六七八九')}
    digits.update({'〇': 0, '两': 2})
    def spelling(value):
        if all(c in digits for c in value):
            return ''.join(str(digits[c]) for c in value)
        result, current = 0, 0
        for c in value:
            if c in digits:
                current = digits[c]
            else:
                result += (current or 1) * {'十': 10, '百': 100, '千': 1000}[c]
                current = 0
        return str(result + current)
    def convert(match):
        return spelling(match[1])+match[2]
    def percent(match):
        integer=spelling(re.sub(r'\s+','',match[1]))
        decimal=''.join(str(digits[c]) for c in re.sub(r'\s+','',match[2] or ''))
        return integer+('.'+decimal if decimal else '')+'%'
    # 百分之二十五 and 25% are the same explicitly denominated literal.
    # No ratio/scale conversion is performed and stored originals stay intact.
    text=re.sub(r'百分之\s*([零〇一二两三四五六七八九十百千]+(?:\s+[零〇一二两三四五六七八九十百千]+)*)(?:点([零〇一二两三四五六七八九]+))?',percent,text)
    return re.sub(r'([零〇一二两三四五六七八九十百千]+)(个月|年|月|日|届|人|位|次|万股|亿股|股|万元|亿元|元)', convert, text)


def without_verified_numeric_source_names(text, supports):
    """Ignore verified media-name digits only in source-attribution phrases.

    Source titles do not license their other dates or quantities as facts.
    Quoted originals and the analysis itself are never rewritten here.
    """
    metadata=' '.join(str(f.get(k) or '') for f in supports
        for k in ('source_title','source_document_issuer','source_publisher','publisher')).casefold()
    suffix=r'经济报道|证券报|通讯社|电视台|日报|周刊|财经|新闻|网|氪'
    pattern=re.compile(r'(^|[，,。；;\n])(?P<name>[^，,。；;：:\s]{1,28}?(?:'+suffix+r'))(?P<verb>报道|消息|载|称)')
    def replace(match):
        name=match['name']
        for start in range(len(name)):
            brand=name[start:];normalized=numeric_literals(brand)
            if (start and re.search(r'[\d零〇一二两三四五六七八九十]$',name[:start])):continue
            if (not re.search(r'\d',normalized) or brand.casefold() not in metadata
                    or re.search(r'年|月|\d(?:个|家|名|人|股|例|次|亿元|万元|元|%|％)',normalized)):continue
            return match[1]+name[:start]+match['verb']
        return match[0]
    return pattern.sub(replace,str(text or ''))


def person_statement_excerpt(text, names):
    """Return a literal target row, not an adjacent director's whole roster."""
    if re.search(r'姓名.{0,45}(?:职务|職務|职位|職位)', text):
        rows = list(re.finditer(r'(?<![\u4e00-\u9fff])([\u4e00-\u9fff]{2,4})\s*(?:副董事长|副董事長|董事长|董事長|非执行|非執行|执行董事|執行董事|独立董事|獨立董事|副总裁|副總裁|董事|总裁|總裁|监事|監事)', text))
        forms = {folded(n) for n in names}
        for index, match in enumerate(rows):
            if folded(match[1]) in forms and index+1 < len(rows):
                return text[match.start():rows[index+1].start()].strip()
    if re.search(r'PDF page \d+', text):
        positions = [m for name in names for m in re.finditer(re.escape(name), text)]
        first = min(positions, key=lambda m: m.start(), default=None)
        if first and first.start() > 250:
            prefix = text[:first.start()]
            # One physical page can contain the end of an unrelated product
            # event followed by the person's risk/holding section. Preserve
            # the complete local sentence before the name, including an
            # "as of signing" qualifier; do not borrow the prior event date.
            boundary = max(prefix.rfind('。'), prefix.rfind('；'), prefix.rfind(';'))+1
            role = re.search(r'(?:本公司)?(?:控股股东及)?实际控制人\s*$', prefix)
            return text[boundary if boundary else role.start() if role else first.start():].strip()
    return text


@lru_cache(maxsize=4096)
def folded(text):
    return re.sub(r'\s+', '', _simplify.convert(unicodedata.normalize('NFKC', str(text or '')))).lower()
def calendar_layout(text):
    """Comparison-only spacing in explicit Chinese calendar components."""
    text=numeric_literals(str(text or ''))
    # PDF character spacing can split the four year digits and two month
    # digits. Join only horizontal spacing inside an explicit year/month/day
    # form; punctuation, other words and neighboring numbers stay boundaries.
    pattern=r'(?<!\d)((?:1[ \t]*9|2[ \t]*0)[ \t]*\d[ \t]*\d)[ \t]*年\s*((?:\d[ \t]*){1,2})月(?:\s*((?:\d[ \t]*){1,2})日)?'
    def calendar(match):
        y,m,d=[re.sub(r'[ \t]+','',v or '') for v in match.groups()]
        if not 1<=int(m)<=12 or d and not 1<=int(d)<=31:return match[0]
        return y+'年'+m+'月'+(d+'日' if d else '')
    text=re.sub(pattern,calendar,text)
    return re.sub(r'(\d{1,2}\s*月)\s*((?:\d[ \t]*){1,2})日',
        lambda m:m[1]+re.sub(r'\s+','',m[2])+'日',text)


def source_bound_calendar_notation(text,originals):
    """Compare dotted dates only when one cited original spells that full date.

    Never rewrite a stored original or compose dates across source records.
    Decimals, versions, incomplete dates and changed components stay intact.
    """
    from datetime import date
    dates=set()
    for original in originals:
        for match in re.finditer(r'(?<!\d)((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日',calendar_layout(original)):
            try:dates.add(date(*(int(v) for v in match.groups())))
            except ValueError:continue
    text=calendar_layout(text)
    def restore(match):
        prefix=text[max(0,match.start()-20):match.start()]
        if re.search(r'(?:版本(?:号)?|型号|编号|version|release|v)\s*(?:为|是|[:：])?\s*$',prefix,re.I):return match[0]
        if re.match(r'\s*(?:版|条|款|[%％])',text[match.end():]):return match[0]
        try:value=date(*(int(v) for v in match.groups()))
        except ValueError:return match[0]
        return f'{value.year}年{value.month}月{value.day}日' if value in dates else match[0]
    return re.sub(r'(?<![A-Za-z0-9_.])((?:19|20)\d{2})\.(\d{1,2})\.(\d{1,2})(?![A-Za-z0-9_.])',restore,text)
