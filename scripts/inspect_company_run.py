"""Offline inspection and readable full-text comparison of retained real runs.

The JSON checks structural traceability; human factual review remains explicit.
The HTML always shows complete chapters rather than curated rewritten excerpts.
"""
import argparse
from collections import Counter, defaultdict
import difflib
import hashlib
import html
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from search_results import canonical_source_url
from build_company_comparison import chapters, render

CHAPTER_PACKAGES = {1:'summary',2:'governance',3:'history',4:'operations',5:'reputation',6:'business',
                    7:'management',8:'people',9:'judicial',10:'diligence',11:'risk_register',12:'assessment'}
EID = re.compile(r'E-[A-F0-9]{12}')
CSS = '''body{margin:0;background:#f3f5f8;color:#172637;font:15px/1.75 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1440px;margin:auto;padding:28px}header,article{background:white;padding:28px;margin-bottom:20px;border-radius:12px}nav{display:flex;gap:10px;flex-wrap:wrap}a{color:#1658a3;word-break:break-all}h1{font-size:30px}h2{font-size:23px}h3,h4{color:#234d72}details{margin:18px 0;border:1px solid #ccd6e3;border-radius:8px;padding:14px}summary{cursor:pointer;font-weight:650}.columns{display:grid;grid-template-columns:1fr 1fr;gap:24px}.columns>div{min-width:0}.table-scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:9px;border:1px solid #d9e2ed;min-width:80px;vertical-align:top;overflow-wrap:anywhere}th{background:#edf3fa}img{max-width:100%;height:auto}.eid{font-size:12px}.note{padding:14px;background:#eef5ff;border-left:4px solid #4476b3}.warning{background:#fff3db;padding:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere}button{padding:10px 18px;cursor:pointer}@media(max-width:950px){.columns{grid-template-columns:1fr}main{padding:10px}header,article{padding:18px}}'''


def load(path, default=None):
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default


def jsonl(path):
    # Unicode line separators are legal inside a JSON string; splitlines()
    # would split real provider body text in the middle of a valid record.
    if not path.exists():return []
    text=path.read_text(encoding='utf-8')
    return [json.loads(row) for row in text[:text.rfind('\n')].split('\n') if row]


def records(value):
    if isinstance(value, dict):
        if value.get('source_url') or value.get('evidence_id') or value.get('evidence_ids'):
            yield value
        for child in value.values():
            yield from records(child)
    elif isinstance(value, list):
        for child in value:
            yield from records(child)


def index_urls(text):
    result = {}
    for line in chapters(text).get(13, '').splitlines():
        ids = EID.findall(line)
        urls = re.findall(r'https?://[^\s|<>]+', line)
        if ids and urls:
            result[ids[0]] = urls[-1].rstrip(')')
    return result


def inspect(run):
    report = (run / 'desktop_report.md').read_text(encoding='utf-8') if (run/'desktop_report.md').exists() else ''
    sections = chapters(report)
    sources = load(run/'source-snapshots.json', [])
    source_keys = {canonical_source_url(s.get('url')) for s in sources}
    packages = {n:load(run/f'company_{name}_package.json', {}) for n,name in CHAPTER_PACKAGES.items()}
    state = load(run/'project-state.json', {})
    events = jsonl(run/'trace.jsonl')
    queries = [e for e in events if e.get('label')=='在线检索完成']
    calls = jsonl(run/'http-calls.jsonl')
    cleaned=load(run/'cleaned_facts.json',{})
    urls = index_urls(report)
    indexed = set(EID.findall(sections.get(13,'')))
    body = set(EID.findall('\n'.join(v for n,v in sections.items() if n!=13)))
    unresolved = sorted(body-indexed)
    unretained = {eid:url for eid,url in urls.items() if canonical_source_url(url) not in source_keys}
    source_ids={}
    for source in sources:
        seed='\n'.join(re.sub(r'\s+',' ',str(v or '').strip()) for v in (source.get('url'),source.get('title'),''))
        source_ids['E-'+hashlib.sha256(seed.encode()).hexdigest()[:12].upper()]=canonical_source_url(source.get('url'))
    for fact in cleaned.get('facts',[]):
        if fact.get('evidence_id') and canonical_source_url(fact.get('source_url')) in source_keys:
            source_ids[fact['evidence_id']]=canonical_source_url(fact['source_url'])
    untraceable=sorted(body-set(source_ids))
    summary_errors = []
    if packages[1] and sections.get(1):
        from report_agents.company_summary import summary_errors as check_summary
        summary_errors = check_summary(sections[1], packages[1])
    diagnostics = {}
    for n, package in packages.items():
        diagnostic = state.get('company_'+CHAPTER_PACKAGES[n]+'_diagnostic', {})
        cited = set(EID.findall(sections.get(n,'')))
        rows = list(records(package))
        package_urls = {canonical_source_url(r.get('source_url')) for r in rows if r.get('source_url')}
        diagnostics[n] = {'heading': sections.get(n,'').splitlines()[0] if sections.get(n) else '',
            'chars':len(sections.get(n,'')), 'cited_evidence_ids':sorted(cited),
            'package_facts':len(package.get('facts',[])), 'package_sources':len(package_urls),
            'package_sources_not_retained':sorted(package_urls-source_keys),
            'information_gaps':package.get('information_gaps',[]),
            'subheadings':re.findall(r'(?m)^### (.+)$', sections.get(n,'')),
            'production_diagnostic':diagnostic or package.get('diagnostic',{})}
    # A locator audit is deliberately weaker than a factual acceptance: some
    # records paraphrase native table cells or join consecutive original pages.
    # Keep unmatched literals for review instead of declaring them fabricated.
    from report_agents.company_text import match_compact
    source_by_url = {canonical_source_url(s.get('url')):s for s in sources}
    locator_rows=[]
    for n,package in packages.items():
        for row in package.get('facts',[]):
            url=canonical_source_url(row.get('source_url'))
            source=source_by_url.get(url,{})
            pages=(source.get('source_metadata') or {}).get('document_pages') or []
            requested=list(row.get('pages') or ([] if row.get('page') is None else [row['page']]))
            selected=[p for p in pages if p.get('page') in requested] if requested else pages
            parts=[source.get('content','')]
            parts += [str(p.get('text',''))+'\n'+'\n'.join(' | '.join(str(c or '') for c in cells) for table in p.get('tables') or [] for cells in table) for p in selected]
            original='\n'.join(parts)
            normalized=match_compact(original)
            quote=str(row.get('evidence_quote') or '')
            fields={k:str(row[k]) for k in ('entity','value','previous_value','ratio','count','role','term','yoy','margin','cost') if row.get(k) not in (None,'')}
            locator_rows.append({'chapter':n,'kind':row.get('kind'), 'metric':row.get('metric'), 'period':row.get('period'),
                'source_url':row.get('source_url'),'evidence_ids':row.get('evidence_ids',[]),
                'requested_physical_pages':requested,'missing_physical_pages':[p for p in requested if p not in {x.get('page') for x in pages}],
                'quote_status':'literal_normalized_match' if quote and match_compact(quote) in normalized else 'composite_or_paraphrase_review' if quote else 'no_quote_field',
                'field_literal_presence':{k:match_compact(v) in normalized for k,v in fields.items()},
                'fields':fields,'fact':row.get('fact'),'quote':quote})
    (run/'field-locator-audit.json').write_text(json.dumps(locator_rows,ensure_ascii=False,indent=2),encoding='utf-8')
    stages = defaultdict(list)
    for event in events:
        stages[event.get('stage','')].append(event.get('elapsed_seconds',0))
    funnel = {'queries':len(queries), 'raw_results':sum(q.get('search_result_audit',{}).get('raw_count',0) for q in queries),
              'unique_per_query':sum(q.get('search_result_audit',{}).get('unique_count',0) for q in queries),
              'kept_per_query':sum(q.get('result_count',0) for q in queries),
              'trimmed_per_query':sum(q.get('search_result_audit',{}).get('trimmed_count',0) for q in queries),
              'event_counts':dict(Counter(e.get('label') for e in events)),
              'retained_sources':len(sources), 'source_modules':dict(Counter((s.get('source_metadata') or {}).get('module','') for s in sources)),
              'cleaning_coverage':cleaned.get('coverage_summary',{}),
              'ledger_statuses':dict(Counter(r.get('status') for r in cleaned.get('evidence_ledger',[]))),
              'ledger_rejection_reasons':dict(Counter(r.get('rejected_reason') for r in cleaned.get('evidence_ledger',[]) if r.get('status')=='rejected')),
              'facts':len(cleaned.get('facts',[])),
              'fact_scopes':dict(Counter(f.get('evidence_scope','unclassified') for f in cleaned.get('facts',[]))),
              'facts_explicitly_excluded':sum(f.get('eligible_for_report') is False for f in cleaned.get('facts',[])),
              'source_fetch_statuses':dict(Counter((s.get('source_metadata') or {}).get('fetch_status','') for s in sources)),
              'http_calls':len(calls), 'http_statuses':dict(Counter(str(c.get('status',c.get('error',''))) for c in calls)),
              'http_hosts':dict(Counter(c.get('host') for c in calls)),
              'http_total_seconds_sum_not_wallclock':round(sum(c.get('seconds',0) for c in calls),2),
              'usage':dict(Counter({k:sum(c.get('usage',{}).get(k,0) for c in calls if isinstance(c.get('usage',{}).get(k),int))
                           for k in ('prompt_tokens','completion_tokens','total_tokens')})),
              'usage_capture_note':'Only usage present in recorded responses is counted; no monetary cost or missing provider billing is inferred.',
              'stage_event_time_ranges':{k:[min(v),max(v)] for k,v in stages.items()}}
    assets = re.findall(r'!\[[^]]*\]\(([^)]+)\)',report)
    objects = run/'objects-before-cleanup' if (run/'objects-before-cleanup').exists() else run/'objects'
    missing_assets = [a for a in assets if not (objects/a).is_file()]
    proof_links={};locators={}
    for eid in sorted(body):
        source=source_by_url.get(source_ids.get(eid),{})
        meta=source.get('source_metadata') or {}
        keys=[meta.get('raw_response_key'),source.get('object_key')]
        proof=next((objects/key for key in keys if key and (objects/key).is_file()),None)
        if proof:proof_links[eid]=proof.relative_to(run).as_posix()
        locators[eid]={'source_url':source.get('url'),'source_title':source.get('title'),
            'provider':meta.get('provider'),'tool':meta.get('tool'),'query':meta.get('query'),
            'retained_original_file':proof_links.get(eid),'source_snapshot_id':source.get('id')}
    (run/'evidence-locators.json').write_text(json.dumps(locators,ensure_ascii=False,indent=2),encoding='utf-8')
    errors = []
    if set(sections)!=set(range(1,15)):errors.append('章节不完整')
    if unresolved:errors.append('正文EID未全部进入索引')
    if untraceable:errors.append('正文EID未绑定本轮来源或清洗卡')
    if unretained:errors.append('索引来源不在本轮保留原件中')
    if missing_assets:errors.append('图形文件缺失')
    if summary_errors:errors.append('摘要事实校验未通过')
    for n,d in diagnostics.items():
        if d['chars']<100:errors.append(f'第{n}章内容过少')
        if d['package_sources_not_retained']:errors.append(f'第{n}章证据包存在未保留来源')
        if d['production_diagnostic'].get('errors'):errors.append(f'第{n}章生成器诊断有错误')
    acceptance=load(run/'acceptance.json',{})
    result = {'automated_structure_passed':not errors,'manual_factual_acceptance':acceptance.get('status','pending'),
        'limitations':'自动结构与引用检查不能证明全部事实或章节满足尽调要求；需逐章对照原件。',
        'errors':errors,'chapters':len(sections),'body_evidence_ids':len(body),'indexed_evidence_ids':len(indexed),
        'unresolved_ids':unresolved,'untraceable_ids':untraceable,'unretained_index_sources':unretained,'summary_errors':summary_errors,
        'missing_assets':missing_assets,'chapter_diagnostics':diagnostics,'funnel':funnel,
        'report_sha256':hashlib.sha256(report.encode()).hexdigest()}
    (run/'inspection.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return report, sections, urls, objects, result, proof_links


def page(title, text):
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+'</title><style>'+CSS+'</style><main>'+text+'</main></html>'


def main():
    p=argparse.ArgumentParser()
    p.add_argument('run',type=Path)
    p.add_argument('--before',type=Path)
    p.add_argument('--before-label',default='上一版已验收优化稿')
    p.add_argument('--after-label',default='本轮真实完整重跑基线')
    p.add_argument('--comparison-name',default='comparison',help='Separate filenames for accepted-version and same-run comparisons')
    p.add_argument('--review-notes',type=Path,help='Evidence-backed chapter review notes; these never modify report text')
    args=p.parse_args()
    report,sections,urls,objects,audit,proof_links=inspect(args.run)
    def render_current(text):
        content=render(text,'本轮',objects,urls)
        for eid,link in proof_links.items():
            content=content.replace('<span class="eid">['+eid+']</span>',
                '<a class="eid" title="本轮保留的原始回执" href="'+html.escape(link,quote=True)+'" target="_blank" rel="noopener">['+eid+']</a>')
        return content
    toc='<nav>'+''.join(f'<a href="#c{n}">第{n}章</a>' for n in sections)+'</nav>'
    acceptance=load(args.run/'acceptance.json',{})
    status='存在未通过项，见 inspection.json'
    if audit['automated_structure_passed']:
        status='样本验收通过，保留已披露核验缺口' if acceptance.get('accepted') is True else '自动结构检查通过；事实验收待复核'
    banner='<header><h1>'+html.escape(args.after_label)+'</h1><p>'+html.escape(str(args.run))+'</p><p class="warning">检查状态：'+status+'</p>'+toc+'</header>'
    body=''.join(f'<article id="c{n}">'+render_current(t)+'</article>' for n,t in sections.items())
    (args.run/'report.html').write_text(page(args.after_label,banner+body),encoding='utf-8')
    if args.before:
        before=args.before.read_text(encoding='utf-8')
        old=chapters(before);old_urls=index_urls(before)
        old_objects=args.before.parent/'objects'
        if (args.before.parent/'objects-before-cleanup').exists():old_objects=args.before.parent/'objects-before-cleanup'
        cards=[];manifest={};evidence_delta={}
        notes=load(args.review_notes,{}) if args.review_notes else {}
        for n in range(1,15):
            a,b=old.get(n,''),sections.get(n,'')
            no_ids=lambda x: re.sub(r'!\[[^]]*\]\([^)]+\)', '', EID.sub('E-ID',x))
            equal=no_ids(a)==no_ids(b)
            ratio=round(difflib.SequenceMatcher(None,no_ids(a).splitlines(),no_ids(b).splitlines(),autojunk=False).ratio(),4)
            manifest[n]={'same_text_excluding_EIDs_and_image_keys':equal,'similarity':ratio,'similarity_method':'full_line_sequence_not_quality_score','before_chars':len(a),'after_chars':len(b),
                         'before_ids':len(set(EID.findall(a))),'after_ids':len(set(EID.findall(b)))}
            if n in CHAPTER_PACKAGES:
                name=CHAPTER_PACKAGES[n]
                old_package=load(args.before.parent/f'company_{name}_package.json',{})
                new_package=load(args.run/f'company_{name}_package.json',{})
                def identity(row):
                    ignored={'source_url','source_title','evidence_id','evidence_ids','page','pages','evidence_quote','evidence_scope','retrieved_at'}
                    value={k:v for k,v in row.items() if k not in ignored}
                    return json.dumps(value,ensure_ascii=False,sort_keys=True)
                old_records={identity(r):r for r in old_package.get('facts',[])}
                new_records={identity(r):r for r in new_package.get('facts',[])}
                evidence_delta[n]={'package':name,'method':'all non-locator fields, exact comparison; wording changes may remain',
                    'added_or_changed':[new_records[k] for k in sorted(new_records.keys()-old_records.keys())],
                    'not_reproduced_or_changed':[old_records[k] for k in sorted(old_records.keys()-new_records.keys())],
                    'unchanged_record_count':len(old_records.keys()&new_records.keys())}
            note=notes.get(str(n),{})
            reason='<p class="note">'+html.escape(str(note.get('explanation','本项展示实际文本差异；来源池和提取版本可能不同，差异本身不构成改善证明。')))+'</p>'
            facts_note=f'前版 {len(a):,} 字符、{manifest[n]["before_ids"]} 个实际引用编号；本轮 {len(b):,} 字符、{manifest[n]["after_ids"]} 个实际引用编号。'
            cards.append(f'<article id="c{n}"><h2>第{n}章 · '+html.escape(str(note.get('title') or ('文本保持' if equal else '内容或覆盖有变化')))+'</h2><p>'+facts_note+'</p>'+reason+'<details><summary>展开两版完整章节</summary><div class="columns"><div><h3>'+html.escape(args.before_label)+'</h3>'+render(a,'前版',old_objects,old_urls)+'</div><div><h3>'+html.escape(args.after_label)+'</h3>'+render_current(b)+'</div></div></details></article>')
        heading='<header><h1>逐章真实文本比较</h1><p>前版：'+html.escape(args.before_label)+'<br>'+html.escape(str(args.before))+'</p><p>后版：'+html.escape(args.after_label)+'<br>'+html.escape(str(args.run/'desktop_report.md'))+'</p><p class="note">来源池可能不同。文本长度、编号和数量变化不代表质量改善；结论以逐章原件核对及验收记录为准。</p><p><a href="report.html">后版完整报告</a></p>'+toc+'<button onclick="document.querySelectorAll(\'details\').forEach(x=>x.open=true)">展开全部章节</button></header>'
        (args.run/(args.comparison_name+'.html')).write_text(page('逐章真实文本比较',heading+''.join(cards)),encoding='utf-8')
        (args.run/(args.comparison_name+'-changes.json')).write_text(json.dumps({'before':str(args.before),'before_label':args.before_label,'after_label':args.after_label,'chapters':manifest},ensure_ascii=False,indent=2),encoding='utf-8')
        (args.run/(args.comparison_name+'-evidence-delta.json')).write_text(json.dumps(evidence_delta,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:audit[k] for k in ['automated_structure_passed','errors','chapters','body_evidence_ids','unresolved_ids']},ensure_ascii=False))


if __name__=='__main__':main()
