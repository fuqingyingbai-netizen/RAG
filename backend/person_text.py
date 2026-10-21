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
    def convert(match):
        value = match[1]
        if all(c in digits for c in value):
            return ''.join(str(digits[c]) for c in value) + match[2]
        result, current = 0, 0
        for c in value:
            if c in digits:
                current = digits[c]
            else:
                result += (current or 1) * {'十': 10, '百': 100, '千': 1000}[c]
                current = 0
        return str(result + current) + match[2]
    return re.sub(r'([零〇一二两三四五六七八九十百千]+)(个月|年|月|日|届|人|位|次|万股|亿股|股|万元|亿元|元)', convert, text)


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


@lru_cache(maxsize=256)
def folded(text):
    return re.sub(r'\s+', '', _simplify.convert(unicodedata.normalize('NFKC', str(text or '')))).lower()
