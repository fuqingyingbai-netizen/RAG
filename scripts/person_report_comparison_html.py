"""Render saved reports safely, preserving actual text and embedded local graphs."""
import base64
import hashlib
import html
import re
from pathlib import Path

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt


def chapter_texts(text):
    result = {int(m[1]): m[0].strip() for m in re.finditer(
        r'^## (\d+)\.[\s\S]*?(?=^## \d+\.|\Z)', text, re.M)}
    if set(result) != set(range(1, 16)):
        raise ValueError('The saved report must contain exactly chapters 1 through 15')
    return result


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def render_report(text, run_path, output, graph_records):
    pictures = {}

    def picture(match):
        label, reference = match[1], match[2]
        token = 'SAVEDREPORTGRAPH' + str(len(pictures)) + 'PLACEHOLDER'
        path = (run_path/'objects'/reference).resolve()
        objects = (run_path/'objects').resolve()
        if not path.is_relative_to(objects) or path.suffix.lower() != '.svg':
            raise ValueError('Only a saved local SVG graph is allowed here')
        if path.is_file():
            data = path.read_bytes()
        else:
            # A bundled page can be rebuilt without the ignored run directory.
            snapshots = output/'graphs'
            candidates = list(snapshots.glob(digest(reference)[:16] + '.svg'))
            if not candidates:
                raise FileNotFoundError(path)
            data = candidates[0].read_bytes()
        if re.search(rb'<\s*(?:script|foreignObject)\b|(?:href|src)\s*=\s*[\'"]\s*(?:https?:|javascript:)', data, re.I):
            raise ValueError('The saved graph contains active or remote content')
        graphs = output/'graphs'
        graphs.mkdir(parents=True, exist_ok=True)
        name = digest(reference)[:16] + '.svg'
        (graphs/name).write_bytes(data)
        graph_records.append({'source_reference': reference, 'sha256': hashlib.sha256(data).hexdigest(),
                              'bundled_file': 'graphs/' + name})
        uri = 'data:image/svg+xml;base64,' + base64.b64encode(data).decode('ascii')
        pictures[token] = '<figure><img class="report-graph" src="' + uri + '" alt="' + html.escape(label, quote=True) + '"><figcaption>' + html.escape(label) + ' · 原运行留存图，未重新绘制</figcaption></figure>'
        return '\n\n' + token + '\n\n'

    # HTML from the report is escaped, and MarkdownIt rejects unsafe link schemes.
    prepared = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', picture, text)
    rendered = MarkdownIt('commonmark', {'html': False}).enable('table').render(prepared)
    for token, figure in pictures.items():
        rendered = rendered.replace('<p>' + token + '</p>', figure)
    return rendered


def normalized(value):
    value = re.sub(r'\[E-[A-Z0-9]+\]', '', value)
    return re.sub(r'\s+', '', value)


def mark_text_differences(old_html, new_html):
    """A whole row/paragraph comparison, not a fact or inference validator."""
    soups = [BeautifulSoup(value, 'html.parser') for value in (old_html, new_html)]
    blocks = [s.select('tbody > tr, p, li') for s in soups]
    fingerprints = [{normalized(e.get_text(' ', strip=True)) for e in side} for side in blocks]
    counts = []
    for i, side in enumerate(blocks):
        changed = 0
        for element in side:
            value = normalized(element.get_text(' ', strip=True))
            if len(value) >= 12 and value not in fingerprints[1-i]:
                element['class'] = list(element.get('class', [])) + ['text-changed']
                changed += 1
        counts.append(changed)
    return [str(s) for s in soups], counts


def chapter_comparison(n, text_pair, run_pair, output, graph_records):
    rendered = [render_report(text, run, output, graph_records) for text, run in zip(text_pair, run_pair)]
    marked, counts = mark_text_differences(*rendered)
    labels = ('优化前 · 早期真实稿', '优化后 · 当前待复核稿')
    panels = []
    for i, (label, body) in enumerate(zip(labels, marked)):
        side = 'old' if i == 0 else 'new'
        filename = 'report-before.html' if i == 0 else 'report-after.html'
        panels.append(f'<section class="document {side}"><div class="document-label">{label}<span>{len(text_pair[i]):,}字符 · 本章完整原文　<a href="{filename}#chapter-{n}" target="_blank" rel="noopener">单独阅读 ↗</a></span></div><div class="document-body" tabindex="0" aria-label="第{n}章{label}正文">{body}</div></section>')
    panel = '<div class="actual-comparison"><div class="actual-heading"><h3>报告正文 · 前后并排对照</h3><span>正文可分别滚动，或展开整章</span></div><div class="document-grid">' + ''.join(panels) + f'</div><button type="button" class="expand-report" aria-expanded="false">展开第{n}章全部原文</button></div>'
    return panel, {'before_sha256': digest(text_pair[0]), 'after_sha256': digest(text_pair[1]),
                   'before_chars': len(text_pair[0]), 'after_chars': len(text_pair[1]),
                   'full_text_present': True, 'text_matching_changed_blocks': counts}


def standalone_report(markdown, run, output, graph_records, label):
    body = render_report(markdown, run, output, graph_records)
    soup = BeautifulSoup(body, 'html.parser')
    for heading in soup.select('h2'):
        number = re.match(r'^(\d+)\.', heading.get_text(strip=True))
        if number:
            heading['id'] = 'chapter-' + number[1]
    body = str(soup)
    style = '''body{font:15px/1.85 'Microsoft YaHei',sans-serif;max-width:1180px;margin:30px auto;padding:0 22px;color:#243f38}table{border-collapse:collapse;width:100%;table-layout:fixed}td,th{border:1px solid #d7e0d7;padding:9px;vertical-align:top;overflow-wrap:anywhere}th{background:#edf3e7}img{max-width:100%;height:auto}a{color:#247462}h2{border-top:1px solid #d7e0d7;margin-top:32px;padding-top:20px}blockquote{border-left:3px solid #c8d9b8;padding-left:15px;color:#64745f}pre{white-space:pre-wrap;overflow-wrap:anywhere}.banner{padding:15px;background:#f3f0e4;color:#765c37}'''
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + html.escape(label) + '</title><style>' + style + '</style></head><body><a href="index.html">← 返回逐章对比</a><p class="banner">' + html.escape(label) + '。历史研究底稿，保留原有问题及核验边界，不作为已核实结论。</p>' + body + '</body></html>'
