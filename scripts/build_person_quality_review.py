"""Build local full-report comparisons from actual retained iteration outputs."""
import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]
from person_evidence import split_sections, cited_ids
from audit_person_report_quality import inspect
from audit_person_source_use import inspect as inspect_source_use
from build_person_evidence_ledger import build as build_evidence_ledger
from replay_person_chapters import generation_code_snapshot
from markdown_it import MarkdownIt
from bs4 import BeautifulSoup, NavigableString

CHAPTER_NOTES = {
1: '摘要只继承正文保留的判断，压缩重复事项；不新增独立推断。',
2: '教育、出生、创办与任职日期分开；表格只取目标人物行，履历材料不被概括成“没有其他信息”。',
3: '公开发言保留其语境；对孩子的评价不用于目标人格判断，资料不足不形成品行评级。',
4: '完整考虑公司背景及个人职责，保留媒体预期与已发生事项的区别；不从公司结果推定个人贡献。',
5: '出版、实施、授权条件、威胁、下令与实际执行分开；保留员工反应及其他管理者的行为。',
6: '校验披露主体，恢复留存报道中的明确公司姓名职务关系；完整成员表不用四条摘录配额裁掉成员。',
7: '具名观点与个人契约分开，关系说明不重复整段采访；公开资料不冒充授权访谈或司法认定。',
8: '公司“同业竞争”声明不充当人物对标；候选字段用全部合格资料核对，口径不齐不排名。',
9: '千分位数量、夫妻共同持股、间接关系及历史任职保持归属；缺失判断同时检查完整研究池。',
10: '专项问题保留完整匹配台账，正文只列代表性编号，避免数百个编号撑长报告；多年份不自动证明变化。',
11: '沿用前文已展示原文的回查引用；历史制度、退休意向不冒充现行投资协议或退出权。',
12: '对风险偏好的比较描述不作为直接负面信号；公司潜在风险、个人责任及查询状态分别列示。',
13: '综合评估从正文已保留分析汇总，同一支持不重复概括；拦截判断不重新进入结论。',
14: '索引只包含正文实际编号，明确代表性摘录与完整台账的区别；编号数不等于独立来源数。',
15: '保留实际缺口、未完成复核及平台限制，删除已恢复材料对应的错误缺失说明。',
}

CSS = '''
:root{font-family:system-ui,"Microsoft YaHei",sans-serif;color:#172b42;background:#f4f6f8;font-size:15px;line-height:1.7}
*{box-sizing:border-box}body{margin:0}header{background:#fff;border-bottom:1px solid #d9e1e8;padding:28px max(24px,calc((100vw - 1480px)/2))}
h1{font-size:28px;line-height:1.3;margin:0 0 10px}h2{font-size:23px}h3{font-size:18px;margin:22px 0 8px}p{margin:10px 0}a{color:#185e9b}button,select{font:inherit;padding:8px 14px;border:1px solid #bac8d4;border-radius:6px;background:white;color:#172b42;cursor:pointer}
button.active{background:#173f65;color:white;border-color:#173f65}.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:16px}.muted{color:#5b6c7d}.wrap{max-width:1540px;margin:20px auto;padding:0 24px}.overview{background:white;padding:18px 22px;border:1px solid #d9e1e8;border-radius:8px}.stats{display:flex;gap:36px;flex-wrap:wrap}.stats strong{display:block;font-size:23px;font-weight:650}.layout{display:grid;grid-template-columns:230px minmax(0,1fr);gap:18px;margin-top:18px}nav{align-self:start;position:sticky;top:16px;background:white;border:1px solid #d9e1e8;border-radius:8px;padding:9px}nav button{width:100%;border:0;text-align:left;padding:7px 9px;font-size:13px;margin:2px 0}.columns{display:grid;grid-template-columns:1fr 1fr;gap:14px;align-items:start}.pane{min-width:0;background:white;border:1px solid #d9e1e8;border-radius:8px;padding:20px 24px;overflow-wrap:anywhere}.pane>h2:first-child{font-size:14px;color:#5b6c7d;margin:0 0 16px}.note{border-left:3px solid #527a9d;padding:8px 14px;background:#eaf0f5;margin:0 0 14px}table{width:100%;border-collapse:collapse;font-size:13px;line-height:1.6;margin:14px 0}th,td{border:1px solid #d4dde5;padding:9px;text-align:left;vertical-align:top}th{background:#eaf0f5}blockquote{border-left:3px solid #cad5df;padding:1px 14px;margin:12px 0;color:#334b62;background:#f7f9fb}blockquote p{white-space:pre-wrap}code{white-space:pre-wrap;font-size:12px}li{margin:8px 0}.eid{font-size:12px;word-break:break-all}details{margin:12px 0}summary{cursor:pointer}.full{max-width:1120px;margin:30px auto;padding:0 24px;background:white}.full article{padding:22px 16px;border-bottom:1px solid #d9e1e8}
@media(max-width:1100px){.layout{grid-template-columns:1fr}nav{position:static;display:flex;flex-wrap:wrap}nav button{width:auto}.columns{grid-template-columns:1fr}.pane{padding:18px}.wrap{padding:0 12px}}@media print{header,.toolbar,nav{display:none}.layout,.columns{display:block}.pane{border:0}.full article{break-before:page}a{color:inherit;text-decoration:none}table{font-size:10px}}
'''


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def render(markdown, prefix):
    soup = BeautifulSoup(MarkdownIt('commonmark', {'html': False}).enable('table').render(markdown), 'html.parser')
    # Exact index cells provide stable targets. References keep the original
    # evidence IDs; hyperlinks add navigation without rewriting source text.
    known = set()
    for cell in soup.select('tbody tr td:first-child'):
        eid = cell.get_text(strip=True)
        if re.fullmatch(r'E-[A-Z0-9-]{6,}', eid):
            cell['id'] = prefix + '-' + eid
            known.add(eid)
            if prefix.endswith('-after'):
                tag = soup.new_tag('a', href=prefix.removesuffix('-after')+'-evidence.html#'+eid)
                tag['target'] = '_blank'
                tag['rel'] = 'noopener noreferrer'
                tag.string = eid
                cell.clear()
                cell.append(tag)
    for node in list(soup.find_all(string=True)):
        if node.parent.name in {'a', 'script', 'style', 'code'}:
            continue
        value = str(node)
        chunks, cursor = [], 0
        pattern = r'https?://[^\s<>]+|\[E-[A-Z0-9-]{6,}\]'
        for match in re.finditer(pattern, value):
            chunks.append(NavigableString(value[cursor:match.start()]))
            text = match[0]
            if text.startswith('['):
                tag = soup.new_tag('a', href='#' + prefix + '-' + text[1:-1])
                tag['class'] = 'eid'
                tag['data-eid'] = text[1:-1]
                tag['data-side'] = prefix
            else:
                tag = soup.new_tag('a', href=text)
                tag['target'] = '_blank'
                tag['rel'] = 'noopener noreferrer'
            tag.string = text
            chunks.append(tag)
            cursor = match.end()
        if cursor:
            chunks.append(NavigableString(value[cursor:]))
            node.replace_with(*chunks)
    return str(soup)


def report_metrics(run):
    inspection = inspect(run)
    contract, audit, summary = read(run/'contract.json'), read(run/'audit.json'), read(run/'summary.json')
    sections = split_sections((run/'desktop_report.md').read_text(encoding='utf-8'))
    by_id = {f['evidence_id']: f for f in contract['facts']}
    body_ids = set().union(*(cited_ids(sections[n]) for n in range(1, 14)))
    assert body_ids == cited_ids(sections[14]), 'Body/index mismatch'
    assert body_ids <= by_id.keys(), 'Unknown body reference'
    pool = {f['evidence_id']: f for n in range(2,13) for f in contract['chapters'][str(n)].get('research_facts', [])}
    return {'chars': sum(len(sections[n]) for n in range(1,16)),
        'body_chars': sum(len(sections[n]) for n in range(1,14)),
        'body_fact_ids': len(body_ids), 'body_source_urls': len({by_id[eid]['source_url'] for eid in body_ids}),
        'research_pool_unique_facts': len(pool), 'research_pool_unique_source_urls': len({f['source_url'] for f in pool.values()}),
        'repeated_original_characters': inspection['repeated_original_character_excess'],
        'all_substantive_chapter_inputs_accounted_for': all(r['all_research_records_accounted_for'] for r in inspection['chapters'] if 2 <= r['chapter'] <= 12),
        'post_render_guard_rejections':[{'chapter':c['chapter'],**a} for c in inspection['chapters'] for a in c['analyses'] if a['complete_guard_rejections']],
        'contained_quote_review_targets':inspection['contained_original_review_targets'],
        'displayed_original_literal_mismatches':inspection['displayed_original_literal_mismatches'],
        'degradations': audit['degradations'], 'model_requests': summary['model_requests'],
        'excluded_candidate_analyses': [
            {'chapter': int(n), 'count': row.get('excluded_invalid_analysis_count', 0),
             'reasons': row.get('excluded_validation_rejections', [])}
            for n, row in audit.get('section_diagnostics', {}).items()
            if row.get('excluded_invalid_analysis_count')],
        'generation_code_sha256':summary.get('generation_code_sha256'),
        'code_unchanged_during_run':summary.get('code_unchanged_during_run'),
        'model_failures': summary['model_requests_failed'], 'exact_input_reuses': summary['exact_input_responses_reused'],
        'inspection': inspection, 'report_sha256': inspection['report_sha256']}


def source_use_page(result, name):
    labels={'cited_in_body':'正文已引用','researched_without_body_citation':'已研究，正文合并精简',
        'research_processing_incomplete':'研究处理尚未完整',
        'no_admitted_chapter_material':'逐章筛选后无合格研究记录',
        'statements_rejected':'候选陈述未通过校验',
        'retained_lead_or_unavailable_original':'检索线索或原文不可用',
        'identity_not_admitted':'身份未匹配，不作人物证据',
        'scanned_no_admissible_person_statement':'扫描后无可采纳人物陈述',
        'source_accounting_missing':'来源处理记录缺失'}
    reasons={'identity_not_admitted':'身份匹配不足或已被隔离',
        'discovery_or_low_content_not_original_evidence':'仅有发现线索、摘要或低内容文本，不能当作已取得原文',
        'original_unavailable':'原文获取失败、受限、跳过或为空',
        'discovery_index_not_original_article':'新闻聚合或索引页，标题不能替代文章正文',
        'no_complete_target_anchored_statement':'留存文本中没有通过规则的完整目标人物陈述',
        'structured_records_processed_by_typed_adapter':'结构化返回由专门字段适配处理'}
    routing_labels={'same_source_statement':'相同原文重复，保留代表记录',
        'possible_revision_overlap':'修订或叠字文本尚需原页核对',
        'not_chapter_material':'不满足该章具体问题、原文字形或格式要求',
        'comparison_person_scope':'候选人物材料只供同业章节核查',
        'not_chapter_relevant':'未匹配该章调查问题',
        'no_question_or_topic_match':'未匹配该章问题或主题',
        'structured_record_chapter_scope':'按平台记录字段确定适用章节',
        'other_person_scope':'其他人员材料不归给目标本人',
        'management_event_scope':'组织事件只进入相应管理问题',
        'affiliated_company_not_personal_material':'关联公司材料不当作个人事实',
        'affiliated_company_without_direct_person_link':'关联公司记录缺少直接人物关系',
        'feedback_record_scope':'具名评价或契约事件保留专门归属'}
    rows=[]
    for item in result['sources']:
        url=html.escape(item['url'],quote=True)
        title=html.escape(item['title'])
        link='<a href="'+url+'" target="_blank" rel="noopener noreferrer">'+title+'</a>' if url.startswith(('https://','http://')) else title+'<br><code>'+url+'</code>'
        reason=reasons.get(item['reason'],item['reason'])
        scan_reason=item['original_scan'].get('reason','')
        scan_reason=reasons.get(scan_reason,scan_reason)
        route_details='；'.join(routing_labels[k]+' '+str(v)+'项' for k,v in item['chapter_routing_and_selection_reasons'].items() if k in routing_labels)
        details='<details><summary>逐章筛选记录</summary>'+html.escape(route_details)+'</details>' if route_details else ''
        rows.append('<tr><td>'+str(item['source_row'])+'</td><td>'+link+'</td><td>'+html.escape(str(item['content_kind'] or '未标注'))+'<br>'+str(item['retained_chars'])+'字符</td><td>'+html.escape(labels[item['state']])+'</td><td>'+str(item['research_fact_count'])+'<br>第'+('、'.join(map(str,item['research_chapters'])) or '—')+'章</td><td>模型返回 '+str(item['returned_model_fact_count'])+'<br>字段处理 '+str(item['deterministically_processed_fact_count'])+'<br>正文编号 '+str(item['body_fact_count'])+'</td><td>'+html.escape(reason)+'<br><small>'+html.escape(str(scan_reason))+'</small>'+details+'</td></tr>')
    counts='；'.join(labels[k]+' '+str(v)+'条' for k,v in result['states'].items())
    queries=''.join('<tr>'+''.join('<td>'+html.escape(str(q.get(k) or '未标注'))+'</td>' for k in ['provider','subject','tool_label','status_label','reason_label'])+'</tr>' for q in result.get('professional_query_coverage',[]))
    query_table='<h2>专业查询覆盖与未完成事项</h2><table><thead><tr><th>平台</th><th>查询主体</th><th>查询范围</th><th>实际状态</th><th>原因及边界</th></tr></thead><tbody>'+queries+'</tbody></table>' if queries else '<p>未提供可核对的专业查询状态，不能据此推定已经查全。</p>'
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(name)+' 逐来源使用台账</title><style>'+CSS+'</style><body><header><h1>'+html.escape(name)+'：逐来源使用台账</h1><p>全部'+str(result['source_rows'])+'条留存来源，逐条保留处理去向。'+html.escape(counts)+'。</p><p>专业结构化来源 '+str(len(result['professional_source_rows']))+'条。事实卡数量、URL数量和独立来源数量分别理解。</p><p class="muted">已研究表示材料进入返回的研读批次或确定性字段处理，不表示已独立核实或每条都用于结论。扫描只覆盖当前留存文本，部分PDF尚不完整。不同URL可能重复同一原始报道。</p><a href="index.html">返回逐章对比</a></header><main class="wrap"><table><thead><tr><th>序号</th><th>来源与原始定位</th><th>留存文本</th><th>处理状态</th><th>研究记录与章节</th><th>实际处理与引用</th><th>去向说明</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table>'+query_table+'</main></body></html>'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--final-round', type=int, required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'deliverables/person-report-quality-20261021')
    parser.add_argument('--review-record', type=Path, help='Source-bound chapter review pinned to the exact final report hashes')
    args = parser.parse_args()
    work = ROOT/'work/person-six-hour'
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    data, validation = {}, {'scope': 'same-retained-material full report iterations', 'experiment_started': '2026-10-21',
        'generated_utc':datetime.now(timezone.utc).isoformat(), 'final_round':args.final_round, 'subjects': {}, 'tests': {}}
    before_runs = {'wang': ROOT/'work/person-complete-material/wang-ch9', 'zhang': ROOT/'work/person-complete-material/zhang-ch5'}
    chapter_review = read(args.review_record) if args.review_record else None
    # Preflight BOTH subjects before replacing any existing deliverable.
    code_sha = hashlib.sha256(json.dumps(generation_code_snapshot(),sort_keys=True).encode()).hexdigest()
    for key in before_runs:
        run = work/f'round{args.final_round}'/key
        metrics = report_metrics(run)
        assert metrics['code_unchanged_during_run'], 'Final generation was not frozen'
        assert metrics['generation_code_sha256'] == code_sha, 'Final report does not match current generation code'
        assert metrics['all_substantive_chapter_inputs_accounted_for'], 'A research batch remains incomplete'
        assert not metrics['degradations'], 'Final report retains an unresolved generation failure'
        assert not metrics['post_render_guard_rejections'], 'Final prose fails the current source boundaries'
        assert not metrics['displayed_original_literal_mismatches'], 'Final displayed quote differs from its original'
        if chapter_review:
            review = chapter_review['subjects'][key]
            assert review['report_sha256'] == metrics['report_sha256'], 'Chapter review belongs to another report'
            assert sorted(row['chapter'] for row in review['chapters']) == list(range(1,16)), 'Review must account for all 15 chapters'
    if chapter_review:
        validation['chapter_review'] = chapter_review
    for key, name in [('wang', '王传福'), ('zhang', '张勇 海底捞')]:
        final = work/f'round{args.final_round}'/key
        original = before_runs[key]
        before_text, after_text = [(p/'desktop_report.md').read_text(encoding='utf-8') for p in [original, final]]
        before, after = split_sections(before_text), split_sections(after_text)
        assert len(before) == len(after) == 15
        before_summary = read(original/'summary.json')
        history = []
        for n in range(1,args.final_round+1):
            run = work/f'round{n}'/key
            if not (run/'summary.json').exists():
                continue
            summary = read(run/'summary.json')
            assert summary['sources_sha256'] == before_summary['sources_sha256']
            assert summary['new_search_calls'] == summary['new_fetch_calls'] == summary['new_professional_calls'] == 0
            metrics = report_metrics(run)
            history.append({'round': n, **{k:v for k,v in metrics.items() if k != 'inspection'}})
        metrics = report_metrics(final)
        final_summary = read(final/'summary.json')
        assert final_summary.get('code_unchanged_during_run'), 'Final report generation must use frozen code'
        source_use = inspect_source_use(final)
        assert not source_use['missing_accounting_rows'], 'Every retained source must have an explicit processing record'
        reviewed_chapters = {row['chapter']: row for row in chapter_review['subjects'][key]['chapters']} if chapter_review else {}
        evidence_count = build_evidence_ledger(final, out, key, name)
        (out/f'{key}-source-use.json').write_text(json.dumps(source_use,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (out/f'{key}-source-use.html').write_text(source_use_page(source_use,name),encoding='utf-8')
        chapters = [{'n': n, 'title': re.sub(r'^##\s*\d+[.、．]\s*', '', after[n].splitlines()[0]),
            'before': render(before[n], key+'-before'), 'after': render(after[n], key+'-after'),
            'before_chars': len(before[n]), 'after_chars': len(after[n]),
            'note': reviewed_chapters.get(n, {}).get('notes') or CHAPTER_NOTES[n]}
            for n in range(1,16)]
        (out/f'{key}-before.md').write_text(before_text, encoding='utf-8')
        (out/f'{key}-after.md').write_text(after_text, encoding='utf-8')
        report_html = ''.join('<article id="chapter-'+str(n)+'">'+render(after[n], key+'-after')+'</article>' for n in range(1,16))
        full = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(name)+' 质量迭代稿</title><style>'+CSS+'</style><body class="full"><header><h1>'+html.escape(name)+' 质量迭代稿</h1><p>研究截止日以报告所列时期为准。原始来源尚需独立核实。</p><p><a href="'+key+'-evidence.html">完整研究证据台账（'+str(evidence_count)+'条）</a> · <a href="'+key+'-source-use.html">全部来源去向</a></p></header>'+report_html+'</body></html>'
        (out/f'{key}-report.html').write_text(full, encoding='utf-8')
        resumed_from = work/'round12'/key/'desktop_report.md'
        if resumed_from.exists():
            resumed_sections = split_sections(resumed_from.read_text(encoding='utf-8'))
            navigation = ' · '.join('<a href="#chapter-'+str(n)+'">第'+str(n)+'章</a>' for n in range(1,16))
            comparisons = ''.join('<section id="chapter-'+str(n)+'"><h2>'+html.escape(chapters[n-1]['title'])+'</h2><div class="columns"><article class="pane"><h3>本次启动前（第12轮）</h3>'+render(resumed_sections[n],key+'-resume-before')+'</article><article class="pane"><h3>本次优化后（第'+str(args.final_round)+'轮）</h3>'+render(after[n],key+'-after')+'</article></div></section>' for n in range(1,16))
            comparison_page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(name)+' 本次启动前后逐章对比</title><style>'+CSS+'</style><body><header><h1>'+html.escape(name)+'：本次启动前后逐章对比</h1><p>左侧为此前暂停时的第12轮，右侧为本次继续生成后的第'+str(args.final_round)+'轮；保留全部15章。材料快照一致，模型接口已变更，差异包含模型与逻辑变化，不能单独归因于其中一项。</p><p><a href="index.html">返回总对比</a> · <a href="'+key+'-evidence.html">完整证据台账</a></p><nav>'+navigation+'</nav></header><main class="wrap">'+comparisons+'</main></body></html>'
            (out/f'{key}-resume-comparison.html').write_text(comparison_page,encoding='utf-8')
        data[key] = {'name': name, 'chapters': chapters, 'history': history, 'metrics': {k:v for k,v in metrics.items() if k != 'inspection'}}
        validation['subjects'][key] = {'sources_sha256': before_summary['sources_sha256'], 'history': history,
            'source_use_summary':{k:v for k,v in source_use.items() if k!='sources'},
            'final_run': str(final), 'final_metrics': metrics,
            'chapter_comparisons': [{k:v for k,v in c.items() if k not in {'before','after'}} for c in chapters]}
    for path in sorted(work.glob('*tests.xml')):
        document = ET.parse(path).getroot()
        suites = list(document) if document.tag == 'testsuites' else [document]
        validation['tests'][path.name] = {k: sum(float(s.get(k, 0)) for s in suites) for k in ['tests','failures','errors','skipped','time']}
    validation['limits'] = ['Source statements are not independent truth verification.',
        'Input accounting is not a measure of semantic comprehension or accuracy.',
        'Historical/OCR/identity gaps and unavailable private agreements remain explicit.',
        'Model critiques include false positives and are never automatically treated as verified errors.']
    (out/'validation.json').write_text(json.dumps(validation, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    encoded = json.dumps(data, ensure_ascii=False).replace('</','<\\/').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>人物报告质量迭代与逐章对比</title><style>'''+CSS+'''</style><body>
<header><h1>人物报告质量迭代与逐章对比</h1><p>复用王传福95条、张勇53条留存来源。研究材料尽量纳入，正文合并精简，原文和事实归属保持可回查。</p><p class="muted">每个章节均可查看完整前后文本。事实编号、URL与模型请求数是使用范围记录，不作为准确率或独立信源数。</p><div class="toolbar"><button id="wang" onclick="choose('wang')">王传福</button><button id="zhang" onclick="choose('zhang')">张勇 海底捞</button><a id="fullLink" target="_blank">打开优化后全文</a><a id="resumeLink" target="_blank">本次启动前后逐章对比</a><a id="mdLink">保存全文 Markdown</a><a id="sourceLink" target="_blank">逐条查看所有来源去向</a><a id="evidenceLink" target="_blank">展开完整研究证据</a><a href="validation.json" target="_blank">验证记录</a></div></header>
<main class="wrap"><section class="overview"><div class="stats" id="stats"></div><details><summary>每轮生成与复核记录</summary><div id="history"></div></details><p class="muted">所有轮次新增研究检索、原文抓取、专业平台请求均为0。部分轮次复用完整输入相同的模型响应，已与新请求分列。来源真实性、PDF坏字及现行治理协议等仍需核实。</p></section><div class="layout"><nav id="chapters"></nav><section><div class="note" id="note"></div><div class="columns"><article class="pane"><h2 id="beforeLabel"></h2><div id="before"></div></article><article class="pane"><h2 id="afterLabel"></h2><div id="after"></div></article></div></section></div></main>
<script>const D='''+encoded+''';let person='wang',chapter=1;
function choose(key){person=key;for(const k of ['wang','zhang'])document.getElementById(k).classList.toggle('active',k===key);const d=D[key],m=d.metrics;
document.getElementById('fullLink').href=key+'-report.html';document.getElementById('resumeLink').href=key+'-resume-comparison.html';document.getElementById('mdLink').href=key+'-after.md';document.getElementById('sourceLink').href=key+'-source-use.html';document.getElementById('evidenceLink').href=key+'-evidence.html';
document.getElementById('stats').innerHTML='<div><strong>'+m.research_pool_unique_facts+'</strong>合格研究事实卡 去重后</div><div><strong>'+m.research_pool_unique_source_urls+'</strong>研究池来源URL</div><div><strong>'+m.body_source_urls+'</strong>正文实际引用URL</div><div><strong>'+m.repeated_original_characters+'</strong>跨章重复原文字符</div>';
document.getElementById('history').innerHTML='<table><thead><tr><th>轮次</th><th>新模型请求</th><th>完全相同输入复用</th><th>请求失败</th><th>正文字符 1至13章</th><th>当轮未解决项</th><th>当前规则复查问题</th></tr></thead><tbody>'+d.history.map(r=>'<tr><td>'+r.round+'</td><td>'+r.model_requests+'</td><td>'+r.exact_input_reuses+'</td><td>'+r.model_failures+'</td><td>'+r.body_chars+'</td><td>'+r.degradations.length+'</td><td>'+r.post_render_guard_rejections.length+'</td></tr>').join('')+'</tbody></table>';show(chapter);}
function show(n){chapter=n;const d=D[person],c=d.chapters[n-1];document.getElementById('chapters').innerHTML=d.chapters.map(x=>'<button class="'+(x.n===n?'active':'')+'" onclick="show('+x.n+')">'+x.n+'. '+x.title+'</button>').join('');document.getElementById('beforeLabel').textContent='优化前 '+c.before_chars+'字符';document.getElementById('afterLabel').textContent='优化后 '+c.after_chars+'字符';document.getElementById('before').innerHTML=c.before;document.getElementById('after').innerHTML=c.after;document.getElementById('note').textContent=c.note;}
document.addEventListener('click',e=>{const a=e.target.closest('a[data-eid]');if(!a)return;e.preventDefault();const eid=a.dataset.eid,side=a.dataset.side;show(14);requestAnimationFrame(()=>document.getElementById(side+'-'+eid)?.scrollIntoView({block:'center',behavior:'smooth'}));});choose('wang');</script></body></html>'''
    (out/'index.html').write_text(page, encoding='utf-8')
    print(json.dumps({'output': str(out), 'subjects': {k:v['metrics'] for k,v in data.items()}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
