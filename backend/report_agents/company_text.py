"""Chinese-script matching views; source names and original quotes stay intact."""
import re
from difflib import SequenceMatcher
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock

from opencc import OpenCC

_CC = OpenCC('t2s')
_MATCHING_CACHE=ContextVar('company_matching_cache',default=None)


class _MatchingCache:
    """Bound temporary string storage; keys contain the entire native input."""
    def __init__(self,max_chars,max_entries):
        self.max_chars=max_chars;self.max_entries=max_entries
        self.entries=OrderedDict();self.chars=0;self.lock=RLock()

    def convert(self,text):
        converter=_CC;key=(converter,text)
        with self.lock:
            if key in self.entries:
                result=self.entries.pop(key);self.entries[key]=result;return result
        result=converter.convert(text);weight=len(text)+len(result)
        with self.lock:
            if key in self.entries:return self.entries[key]
            if self.max_entries<1 or weight>self.max_chars:return result
            while self.entries and (self.chars+weight>self.max_chars or len(self.entries)>=self.max_entries):
                old_key,old_result=self.entries.popitem(last=False)
                self.chars-=len(old_key[1])+len(old_result)
            self.entries[key]=result;self.chars+=weight
        return result


@contextmanager
def company_matching_cache(*,max_chars=8_000_000,max_entries=4096):
    """Reuse pure matching views during one generation; retain no text after it.

    A nested scope shares its parent. New threads and independent report calls
    receive their own scope. Source storage and quote offsets stay unchanged.
    """
    if _MATCHING_CACHE.get() is not None:
        yield;return
    cache=_MatchingCache(max_chars,max_entries);token=_MATCHING_CACHE.set(cache)
    try:yield
    finally:
        cache.entries.clear();cache.chars=0;_MATCHING_CACHE.reset(token)


def match_text(value):
    text=str(value or '');cache=_MATCHING_CACHE.get()
    return cache.convert(text) if cache is not None else _CC.convert(text)


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


def issuer_response_title(title):
    """An issuer's feedback submission is not the hosting agency's opinion."""
    title=re.sub(r'\s+','',str(title or ''))
    title=re.sub(r'\.pdf$','',title,flags=re.I)
    return bool(re.search(r'(?:首次公开发行|发行注册|发行人|保荐|上市).{0,180}'
                          r'(?:反馈意见|审核问询|问询函|问询).{0,100}(?:回复|答复)[》）)]*$',title))


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
