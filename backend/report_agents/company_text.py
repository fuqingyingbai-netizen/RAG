"""Chinese-script matching views; source names and original quotes stay intact."""
import re
from difflib import SequenceMatcher

from opencc import OpenCC

_CC = OpenCC('t2s')


def match_text(value):
    return _CC.convert(str(value or ''))


def match_compact(value):
    return re.sub(r'\s+', '', match_text(value)).casefold()


class OriginalTextView:
    """Map a normalized regex span back to the unmodified original.

    Conversion may change length. Changed chunks are quoted in full rather
    than guessing a character offset or manufacturing a simplified quote.
    """
    def __init__(self, original):
        self.original = str(original or '')
        self.text = match_text(self.original)
        self._opcodes = None

    def quote(self, start, end):
        if start >= end:
            return ''
        if self.original == self.text:
            return self.original[start:end]
        if self._opcodes is None:
            self._opcodes = SequenceMatcher(None, self.original, self.text, autojunk=False).get_opcodes()
        spans = []
        for tag, a, b, c, d in self._opcodes:
            if c >= end or d <= start:
                continue
            if tag == 'equal':
                spans.append((a + max(start, c) - c, a + min(end, d) - c))
            else:
                spans.append((a, b))
        return self.original[spans[0][0]:spans[-1][1]] if spans else ''


def issuer_anchor(raw, target):
    """Full issuer heading or explicit publisher, never title/parent mention.

    A conflicting full issuer heading rejects even an ownership sentence
    naming the requested parent. Domain verification belongs to the caller.
    """
    view = OriginalTextView(str(raw or '')[:6500])
    text = view.text
    name = r'\s*'.join(map(re.escape, match_text(target).strip()))
    if not name:
        return {'matched': False, 'standalone': False, 'publisher_statement': False}
    heading_text='\n'.join(re.sub(r'[ \t\r]+','',line) for line in text[:2400].splitlines())
    # A whole legal-name line excludes quoted narrative such as the HKEX
    # wrapper "以下为…刊发之「…年度报告」". Spaces inside cover names are
    # normalized for this check, without removing quote/parent boundaries.
    headings = re.finditer(r'(?mi)^\s*([\w·（）()&.-]{2,100}(?:股份有限公司|有限责任公司|有限公司|Limited))\s*20\d{2}[^\n]{0,50}(?:报告|Report)', heading_text)
    conflict = any(match_compact(m[1]) != match_compact(target) for m in headings)
    standalone = re.search(r'(?m)^\s*(?P<issuer>' + name + r')\s*(?:\n|20\d{2}\s*年)', text)
    statement = re.search(r'本报告[」”"\s）)]*(?:是|由|为)\s*(?P<issuer>' + name + ')'
                          + r'(?:\s*[（(][^）)]{0,80}[）)])?\s*(?:发布|编制)', text)
    chosen = standalone or statement
    return {'matched': bool(chosen and not conflict), 'standalone': bool(standalone),
            'publisher_statement': bool(statement), 'conflicting_heading': conflict,
            'issuer_name': view.quote(chosen.start('issuer'),chosen.end('issuer')) if chosen else '',
            'evidence_quote': view.quote(chosen.start(), chosen.end()) if chosen else ''}
