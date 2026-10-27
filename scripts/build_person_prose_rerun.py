"""Compare bounded live reruns against the preceding same-corpus reports."""
import hashlib
import html
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'scripts')]
from bs4 import BeautifulSoup, NavigableString
from markdown_it import MarkdownIt
from person_evidence import split_sections, cited_ids
from audit_person_report_quality import inspect


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def metrics(body, package):
    research = package.get('research_facts', package['facts'])
    by_id = {f['evidence_id']:f for f in research}
    analyses = []
    for line in body.splitlines():
        if line.startswith('- 研究判断（待人工复核）：'):
            analyses.append({'analysis':re.sub(r'\s*\[E-[A-Z0-9-]+\]', '', line.split('：',1)[1]).strip(),
                             'evidence_ids':sorted(cited_ids(line))})
    ids = {eid for c in analyses for eid in c['evidence_ids']}
    body_ids = cited_ids(body)
    return {'research_records':len(research), 'research_sources':len({f['source_url'] for f in research}),
            'analysis_count':len(analyses), 'analysis_chars':sum(len(c['analysis']) for c in analyses),
            'analysis_records':len(ids), 'analysis_sources':len({by_id[eid]['source_url'] for eid in ids if eid in by_id}),
            'body_records':len(body_ids), 'body_sources':len({by_id[eid]['source_url'] for eid in body_ids if eid in by_id}),
            'displayed_original_chars':sum(len(line[2:]) for line in body.splitlines() if line.startswith('> ')),
            'research_records_not_cited_in_analysis':sorted(set(by_id)-ids),
            'analysis_evidence_ids':sorted(ids), 'analyses':analyses, 'chapter_chars':len(body)}


def rendered(text, who):
    soup = BeautifulSoup(MarkdownIt('commonmark', {'html':False}).enable('table').render(text), 'html.parser')
    for node in list(soup.find_all(string=True)):
        if node.parent.name in {'a','script','style','code'}:
            continue
        value, chunks, cursor = str(node), [], 0
        for match in re.finditer(r'\[(E-[A-Z0-9-]+)\]', value):
            chunks.append(NavigableString(value[cursor:match.start()]))
            tag = soup.new_tag('a', href=f'evidence.html#{who}-{match[1]}')
            tag.string = match[0]
            chunks.append(tag)
            cursor = match.end()
        if cursor:
            chunks.append(NavigableString(value[cursor:]))
            node.replace_with(*chunks)
    return str(soup)


def main():
    output = ROOT/'deliverables/person-prose-rerun-20261023'
    output.mkdir(parents=True, exist_ok=True)
    rows, cards, chapters, runs = [], [], [], {}
    esc = lambda value:html.escape(str(value),quote=True)
    for who in ['wang','zhang']:
        run = ROOT/'work/person-prose-rerun-20261023'/who
        first_run = run
        if who == 'zhang' and (run.with_name('zhang-retry')/'summary.json').exists():
            run = run.with_name('zhang-retry')
        summary, contract, audit = [read(run/n) for n in ['summary.json','contract.json','audit.json']]
        old = ROOT/'work/person-coverage-20261023'/f'frozen-{who}'
        old_contract = read(old/'contract.json')
        before = split_sections((old/'desktop_report.md').read_text(encoding='utf-8'))
        after = split_sections((run/'desktop_report.md').read_text(encoding='utf-8'))
        quality = inspect(run)
        (run/'quality-inspection.json').write_text(json.dumps(quality,ensure_ascii=False,indent=2),encoding='utf-8')
        assert summary['sources_sha256'] == summary['prior_sources_sha256']
        assert summary['code_unchanged_during_run']
        selected_chapters = [3,5]
        assert all(before[n] == after[n] for n in range(2,13) if n not in selected_chapters)
        runs[who] = {k:summary[k] for k in ['sources_sha256','generation_code_sha256','model_requests',
            'model_requests_returned','model_requests_failed','new_search_calls','new_fetch_calls',
            'new_professional_calls','unchanged_body_chapters','elapsed_seconds','actual_cost_available']}
        runs[who]['report_sha256'] = hashlib.sha256((run/'desktop_report.md').read_bytes()).hexdigest()
        runs[who]['final_run'] = str(run.relative_to(ROOT))
        runs[who]['unchanged_body_chapters'] = [n for n in range(2,13) if n not in selected_chapters]
        run_chain = [first_run,run] if first_run != run else [run]
        runs[who]['model_requests'] = sum(read(p/'summary.json')['model_requests'] for p in run_chain)
        runs[who]['model_requests_returned'] = sum(read(p/'summary.json')['model_requests_returned'] for p in run_chain)
        runs[who]['model_requests_failed'] = sum(read(p/'summary.json')['model_requests_failed'] for p in run_chain)
        runs[who]['empty_model_responses'] = sum(not r['response'].strip() for p in run_chain
            for r in [json.loads(line) for line in (p/'chapter-model-responses.jsonl').read_text(encoding='utf-8').splitlines()])
        runs[who]['attempt_chain'] = [str(p.relative_to(ROOT)) for p in run_chain]
        runs[who]['stage_failures'] = [r for p in run_chain for r in read(p/'audit.json').get('api_attempts',[])
                                      if r.get('status') == 'failed']
        runs[who]['token_usage'] = {k:sum(r.get(k,0) for p in run_chain
            for r in [json.loads(line) for line in (p/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
            if r.get('stage') == 'llm' and r.get('status') == 'done')
            for k in ['input_tokens','output_tokens','total_tokens']}
        evidence = {}
        for n in selected_chapters:
            p = contract['chapters'][str(n)]
            previous = old_contract['chapters'][str(n)]
            for f in [*p.get('research_facts',p['facts']),*previous.get('research_facts',previous['facts'])]:
                evidence[f['evidence_id']] = f
            diagnostic = audit['section_diagnostics'][str(n)]
            q = next(c for c in quality['chapters'] if c['chapter'] == n)
            b, a = metrics(before[n],previous), metrics(after[n],p)
            row = {'target':contract['target_name'],'key':who,'chapter':n,'title':p['title'],
                   'before':b,'after':a,'prose_budget':diagnostic.get('prose_budget',{}),
                   'quotation_budget':diagnostic.get('quotation_budget',{}),
                   'unresolved_validation_rejections':diagnostic['unresolved_validation_rejections'],
                   'excluded_invalid_analysis_count':diagnostic.get('excluded_invalid_analysis_count',0),
                   'excluded_validation_rejections':diagnostic.get('excluded_validation_rejections',[]),
                   'semantic_review_status':diagnostic.get('semantic_review',{}).get('status'),
                   'all_research_records_accounted_for':q['all_research_records_accounted_for'],
                   'guard_rejections':[c for c in q['analyses'] if c['complete_guard_rejections']],
                   'source_boundary_issues':[c for c in q['analyses'] if c['explicit_source_boundary_issues']]}
            rows.append(row)
            cells = [contract['target_name']+f' 第{n}章',str(a['research_sources']),
                f"{b['analysis_sources']} → {a['analysis_sources']}",
                f"{b['analysis_records']} → {a['analysis_records']}",
                f"{b['analysis_count']} → {a['analysis_count']}",
                f"{b['analysis_chars']} → {a['analysis_chars']}"]
            cards.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in cells)+'</tr>')
            status = '完整研读回执齐全' if row['all_research_records_accounted_for'] else '完整研读回执尚不齐全'
            status += '；未解决校验问题：'+('、'.join(row['unresolved_validation_rejections']) or '无')
            status += '；被校验剔除的判断：'+str(row['excluded_invalid_analysis_count'])+' 条'
            chapters.append(f'<section id="{who}-{n}"><h2>{esc(contract["target_name"])} · 第{n}章 {esc(p["title"])}</h2>'
                '<p>'+esc(status)+'</p><p>下方展示完整章节；600 字符限制只计算分析文字，原文、引用、附表及覆盖清单另计。</p>'
                '<div class="columns"><article><h3>修改前</h3>'+rendered(before[n],who)+
                '</article><article><h3>本次重跑</h3>'+rendered(after[n],who)+'</article></div></section>')
        runs[who]['evidence'] = list(evidence.values())
    evidence_cards = []
    for who, data in runs.items():
        for f in data.pop('evidence'):
            url = f.get('source_url','')
            link = ('<a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">'+esc(f.get('source_title') or url)+'</a>') if url.startswith(('https://','http://')) else esc(url)
            evidence_cards.append('<details id="'+who+'-'+esc(f['evidence_id'])+'"><summary>'+esc(f['evidence_id'])+' · '+esc(f.get('source_title',''))+'</summary><p>'+link+'</p><blockquote>'+esc(f['fact'])+'</blockquote><p>'+esc(f.get('attribution_boundary',''))+'</p></details>')
    style = 'body{max-width:1500px;margin:28px auto;padding:0 20px;font:15px/1.75 system-ui,"Microsoft YaHei",sans-serif;color:#172b42;background:#f4f6f8}table{border-collapse:collapse;width:100%;background:white}td,th{border:1px solid #cdd7e1;padding:10px;text-align:left}a{color:#155c9c;overflow-wrap:anywhere}section{margin:32px 0}.columns{display:grid;grid-template-columns:1fr 1fr;gap:16px}article,details{background:white;border:1px solid #d1dae4;padding:20px;min-width:0;overflow-wrap:anywhere}blockquote{white-space:pre-wrap;background:#f4f6f8;margin:12px 0;padding:14px;border-left:3px solid #98aabd}summary{cursor:pointer}details{margin:14px 0}details:target{border:2px solid #155c9c}@media(max-width:900px){.columns{grid-template-columns:1fr}body{padding:0 10px}table{font-size:12px}td,th{padding:5px}}'
    head = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>'+style+'</style>'
    summary = {'comparison_scope':'same_retained_corpus_partial_live_rerun','runs':runs,'chapters':rows,
               'boundary':'来源数按不同URL计，非独立核实来源数；证据记录可能语义重叠。未引用不等于无价值，也未逐条证明所有重要事项均已覆盖。'}
    observations = [
        '四章均在600字符分析预算内；实际展示原文均在1600字符内。两章分析引用来源增加，一章持平，一章减少。',
        '王传福第5章回退：复核空响应触发批量改写；后续4条虽获supported评价，但返回的支撑编号没有覆盖其全部引用，被严格校验剔除；另1条任期修订未通过规则。原有团队履历、工程师用人文化及本届任期信息未在最终分析中保留。',
        '张勇第3章分析条数增加而来源数仍为2，不能把拆分判断或增加证据卡直接等同于增加独立来源。',
        '本次共23次真实模型请求，包含2次空内容返回。张勇第5章失败后缩小研读批次重试；全部研究材料保留。调用数量包含失败及重试，账单金额不可用。',
        '结论：放开条数可改善部分章节覆盖，但复核空响应处理、支撑编号对齐和原有事项保留仍需优化；本轮不能作为全面验收通过。']
    summary['review_observations'] = observations
    (output/'metrics.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'index.html').write_text(head+'<title>放开条数后的四章重跑对比</title><h1>放开条数后的四章重跑对比</h1>'
        '<p>两个人物各重跑第 3、5 章。沿用同一批原始材料，无新增检索、抓取或专业查询；每个人物其余 9 个研究正文章节逐字保留。摘要、综合评估和索引随最终正文更新。</p>'
        '<p>分析每章最多 600 字符、摘要最多 300 字符；代表性原文合计最多 1600 字符；分析和摘录均不按条数限额。完整原文见证据台账。</p>'
        '<p>运行记录：'+esc('；'.join(who+' 共 '+str(r['model_requests'])+' 次模型请求、'+str(r['empty_model_responses'])+' 次空响应' for who,r in runs.items()))+'。空响应及重试均计入，接口未提供账单金额。</p>'
        '<p>'+esc(summary['boundary'])+'</p><p><a href="metrics.json">完整统计 JSON</a> · <a href="evidence.html">本次四章全部研究证据</a></p>'
        '<h2>复核观察</h2><ul>'+''.join('<li>'+esc(note)+'</li>' for note in observations)+'</ul>'
        '<table><thead><tr><th>人物／章节</th><th>研究来源</th><th>分析实际引用来源：前 → 后</th><th>分析引用记录：前 → 后</th><th>分析条数：前 → 后</th><th>分析字符：前 → 后</th></tr></thead><tbody>'
        +''.join(cards)+'</tbody></table>'+''.join(chapters)+'</html>',encoding='utf-8')
    (output/'evidence.html').write_text(head+'<title>四章完整研究证据</title><h1>四章完整研究证据</h1><p><a href="index.html">返回章节对比</a></p>'+''.join(evidence_cards)+
        '<script>function reveal(){const e=document.getElementById(decodeURIComponent(location.hash.slice(1)));if(e){e.open=true;e.scrollIntoView();}}addEventListener("hashchange",reveal);reveal();</script></html>',encoding='utf-8')
    errors, checked, target_ids = [], 0, {}
    for path in output.glob('*.html'):
        soup = BeautifulSoup(path.read_text(encoding='utf-8'),'html.parser')
        for tag in soup.select('a[href]'):
            url = urlsplit(tag['href'])
            if url.scheme or url.netloc: continue
            target = output/unquote(url.path) if url.path else path
            checked += 1
            if not target.is_file(): errors.append(tag['href'])
            elif url.fragment:
                if target not in target_ids:
                    target_ids[target] = {t['id'] for t in BeautifulSoup(target.read_text(encoding='utf-8'),'html.parser').select('[id]')}
                if unquote(url.fragment) not in target_ids[target]: errors.append(tag['href'])
    assert not errors, errors[:10]
    (output/'checks.json').write_text(json.dumps({'local_links_checked':checked,'errors':errors,
        'visual_review_performed':False},indent=2),encoding='utf-8')
    print(json.dumps({'output':str(output),'local_links_checked':checked,'chapters':[{k:r[k] for k in ['target','chapter','before','after','unresolved_validation_rejections']} for r in rows]},ensure_ascii=False))


if __name__ == '__main__':
    main()
