"""Export admitted retained evidence without copying raw provider archives."""
from collections import defaultdict
import html
import json
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'backend')]
from person_evidence import split_sections, cited_ids


def build(run, output, key, name):
    contract = json.loads((run / 'contract.json').read_text(encoding='utf-8'))
    sections = split_sections((run / 'desktop_report.md').read_text(encoding='utf-8'))
    facts, research, citations = {}, defaultdict(list), defaultdict(list)
    for chapter in range(2, 13):
        for fact in contract['chapters'][str(chapter)].get('research_facts', []):
            facts[fact['evidence_id']] = fact
            research[fact['evidence_id']].append(chapter)
    all_facts = {f['evidence_id']: f for f in contract['facts']}
    for chapter in range(1, 14):
        for eid in cited_ids(sections[chapter]):
            facts[eid] = all_facts[eid]
            citations[eid].append(chapter)
    rows = []
    for eid, fact in sorted(facts.items()):
        # Deliberate allowlist: no credentials, raw platform payloads or traces.
        rows.append({k: fact.get(k) for k in ['evidence_id', 'fact', 'source_url',
            'source_title', 'subject_scope', 'claim_type', 'analysis_allowed',
            'source_document_issuer', 'source_document_kind', 'source_reporting_period_literal',
            'source_physical_pages', 'attribution_boundary']} | {'research_chapters': research[eid],
                'cited_chapters': citations[eid]})
    data = {'target': name, 'evidence': rows,
        'boundary': '留存原文及其处理范围；来源陈述尚未独立核实，记录数不等于独立信息源数。'}
    (output / f'{key}-evidence.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    esc = lambda value: html.escape(str(value or ''), quote=True)
    cards = []
    for row in rows:
        url = row['source_url'] or ''
        source = ('<a target="_blank" rel="noopener noreferrer" href="'+esc(url)+'">'+esc(row['source_title'] or url)+'</a>') if url.startswith(('http://', 'https://')) else esc(row['source_title'] or url)
        cards.append('<details id="'+esc(row['evidence_id'])+'"><summary>'+esc(row['evidence_id'])+' · '+esc(row['source_title'])+'</summary><p>'+source+'</p><p>研究章节：'+esc('、'.join(map(str,row['research_chapters'])) or '—')+'；正文引用章节：'+esc('、'.join(map(str,row['cited_chapters'])) or '—')+'；范围：'+esc(row['subject_scope'])+'</p><p>文件发行主体：'+esc(row['source_document_issuer'] or '未明确')+'；文件年度（非事件时间）：'+esc(row['source_reporting_period_literal'] or '未明确')+'；物理页：'+esc('、'.join(map(str,row['source_physical_pages'] or [])) or '未定位')+'</p><blockquote>'+esc(row['fact'])+'</blockquote><p>'+esc(row['attribution_boundary'])+'</p></details>')
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(name)+' 完整研究证据台账</title><style>body{max-width:1100px;margin:30px auto;padding:0 20px;font:15px/1.75 system-ui,"Microsoft YaHei",sans-serif;color:#172b42}details{border:1px solid #d4dde5;margin:12px 0;padding:12px}summary{cursor:pointer}blockquote{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;margin:10px 0;padding:14px}a{color:#185e9b}details:target{border:2px solid #185e9b}</style><h1>'+esc(name)+'：完整研究证据台账</h1><p>'+str(len(rows))+'条合格研究记录及正文引用原文，可逐条展开。'+esc(data['boundary'])+'</p><p><a href="index.html">逐章对比</a> · <a href="'+key+'-source-use.html">全部来源去向</a></p>'+''.join(cards)+'<script>function reveal(){const e=document.getElementById(decodeURIComponent(location.hash.slice(1)));if(e){e.open=true;e.scrollIntoView();}}addEventListener("hashchange",reveal);reveal();</script></html>'
    (output / f'{key}-evidence.html').write_text(page, encoding='utf-8')
    return len(rows)
