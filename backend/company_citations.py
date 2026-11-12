"""Conservative streaming normalization of numeric source markers in prose."""
import re

TOKENS = re.compile(r'(?P<ticks>`+)|!?\[[^\]\n]*\]\([^\n)]*\)|\[[^\]\n]*\]\[[^\]\n]*\]|\$[^$\n]*\$|\\\([^\n]*?\\\)')
NUMERIC = re.compile(r'\[([1-9]\d{0,3})\]')


class CitationFormatter:
    def __init__(self, ids):
        self.ids = {str(value) for value in ids}
        self.pending = ''
        self.fence = ''
        self.ticks = ''
        self.math_end = ''
        self.unknown = set()
        self.changed = False
        self.emitted = 0

    def feed(self, text, *, final=False):
        self.pending += text
        lines = self.pending.splitlines(keepends=True)
        if lines and not final and not lines[-1].endswith(('\n', '\r')):
            self.pending = lines.pop()
        else:
            self.pending = ''
        output = []
        for line in lines:
            rendered = self.line(line)
            output.append(rendered[self.emitted:])
            self.emitted = 0
        if self.pending:
            # shortcut: stream plain prefixes now; keep Markdown/citation tails
            # until newline/final so chunking cannot change literal interpretation.
            special = re.search(r'[\[\x60$\\]', self.pending)
            cut = special.start() if special else len(self.pending)
            output.append(self.pending[self.emitted:cut])
            self.emitted = cut
        return ''.join(output)

    def line(self, line):
        fence = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if self.fence:
            if fence and fence[1][0] == self.fence[0] and len(fence[1]) >= len(self.fence) and not line[fence.end():].strip():
                self.fence = ''
            return line
        if self.math_end:
            if line.strip() == self.math_end:
                self.math_end = ''
            return line
        if not self.ticks and fence:
            self.fence = fence[1]
            return line
        if not self.ticks and line.strip() in ('$$', r'\['):
            self.math_end = '$$' if line.strip() == '$$' else r'\]'
            return line
        if line.startswith(('    ', '\t')):
            return line
        parts, start = [], 0
        for token in TOKENS.finditer(line):
            before = line[start:token.start()]
            parts.append(before if self.ticks else self.prose(before, line[:start]))
            parts.append(token[0])
            if token['ticks']:
                self.ticks = '' if self.ticks == token[0] else self.ticks or token[0]
            start = token.end()
        tail = line[start:]
        parts.append(tail if self.ticks else self.prose(tail, line[:start]))
        return ''.join(parts)

    def prose(self, text, prefix):
        def replace(match):
            before = prefix + text[:match.start()]
            after = text[match.end():]
            # shortcut: only unambiguous trailing prose markers; preserve literals and links.
            if (not before.strip() or re.search(r'[A-Za-z0-9_\\!`=$+*/\-\[\]|\'"“‘]\s*$', before)
                    or (re.search(r'(?:为|是|等于|取值|编号|序号|索引|数组|示例|列表|参数|[:：])\s*$', before)
                        and not re.search(r'(?:来源|参考|依据)[:：]?\s*$', before))
                    or (after and not re.match(r'[\s,，。.;；!?！？、|）)\]}]', after))):
                return match[0]
            if match[1] not in self.ids:
                self.unknown.add(match[1])
                return match[0]
            self.changed = True
            return '[id_' + match[1] + ']'
        return NUMERIC.sub(replace, text)
