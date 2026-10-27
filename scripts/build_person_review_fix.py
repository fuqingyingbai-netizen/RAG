"""Preserve the original, regressed and repaired chapter as separate samples."""
import hashlib
import html
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit, unquote

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'scripts')]
from bs4 import BeautifulSoup
from person_evidence import split_sections
from build_person_prose_rerun import metrics, rendered
from audit_person_report_quality import inspect


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    work=ROOT/'work/person-review-fix-20261023'
    output=ROOT/'deliverables/person-review-fix-20261023/dist'
    output.mkdir(parents=True,exist_ok=True)
    runs=[('原规则',ROOT/'work/person-coverage-20261023/frozen-wang'),
          ('放开条数后的首次试跑',ROOT/'work/person-prose-rerun-20261023/wang'),
          ('修复并定向核对后的样本',work/'wang-reviewed')]
    records,panes,evidence=[],[],{}
    esc=lambda v:html.escape(str(v),quote=True)
    for title,path in runs:
        contract=read(path/'contract.json');audit=read(path/'audit.json')
        report=(path/'desktop_report.md').read_text(encoding='utf-8')
        body=split_sections(report)[5];p=contract['chapters']['5']
        m=metrics(body,p)
        records.append({'version':title,'metrics':m,'pending_review_analysis_count':audit['section_diagnostics']['5'].get('pending_review_analysis_count',0),
                        'report_sha256':hashlib.sha256((path/'desktop_report.md').read_bytes()).hexdigest()})
        for f in p.get('research_facts',p['facts']):evidence[f['evidence_id']]=f
        panes.append('<article><h3>'+esc(title)+'</h3>'+rendered(body,'wang')+'</article>')
    summary=read(work/'wang-reviewed/summary.json');audit=read(work/'wang-reviewed/audit.json');d=audit['section_diagnostics']['5']
    assert summary['code_unchanged_during_run']
    assert summary['sources_sha256']==summary['prior_sources_sha256']
    quality=inspect(work/'wang-reviewed')
    (work/'wang-reviewed/quality-inspection.json').write_text(json.dumps(quality,ensure_ascii=False,indent=2),encoding='utf-8')
    selected=next(r for r in quality['chapters'] if r['chapter']==5)
    content=read(work/'content-review.json')
    assert content['report_sha256']==records[-1]['report_sha256']
    comparison={'comparison_scope':'same_corpus_single_chapter_sample','versions':records,
        'content_review':content,'prose_budget':d['prose_budget'],'quotation_budget':d['quotation_budget'],
        'prior_analysis_coverage':d.get('prior_analysis_coverage',{}),
        'selected_chapter_quality':selected,
        'unresolved_validation_rejections':d['unresolved_validation_rejections'],
        'requests':{k:summary[k] for k in ['model_requests','model_requests_returned','model_requests_failed','exact_input_responses_reused',
            'new_search_calls','new_fetch_calls','new_professional_calls','unchanged_body_chapters','actual_cost_available']},
        'boundary':'Different URLs are counted separately; source statements and model review are not independent fact verification. This is one chapter sample, not whole-report acceptance.'}
    trial=read(work/'wang/summary.json')
    comparison['fix_attempt_history'] = [
        {'phase':'targeted_review_fix_before_revision_budget','new_model_requests':trial['model_requests'],
         'outcome':'analysis_length_budget_exceeded','draft_chars':read(work/'wang/audit.json')['section_diagnostics']['5']['prose_budget']['draft_chars']},
        {'phase':'final_with_revision_budget_and_targeted_editorial_review','new_model_requests':summary['model_requests'],
         'exact_input_responses_reused':summary['exact_input_responses_reused']}]
    comparison['total_new_model_requests_for_this_fix']=trial['model_requests']+summary['model_requests']
    comparison['tests']=read(work/'test-results.json')
    comparison['targeted_editorial_review_model_requests']=summary.get('editorial_review_model_requests',0)
    (output/'metrics.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2),encoding='utf-8')
    style='body{max-width:1650px;margin:30px auto;padding:0 20px;font:15px/1.75 system-ui,"Microsoft YaHei",sans-serif;color:#1f3434;background:#f3f5f4}header,article,.card,details{background:white;border:1px solid #d1ddd8;border-radius:8px;padding:22px;margin:14px 0;min-width:0;overflow-wrap:anywhere}h1,h2{color:#215343}a{color:#185f4b;overflow-wrap:anywhere}.columns{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}table{width:100%;border-collapse:collapse}th,td{border:1px solid #d1ddd8;padding:9px;text-align:left}.scroll{overflow-x:auto}blockquote{white-space:pre-wrap;background:#f3f5f4;border-left:3px solid #9cb6a9;margin:12px 0;padding:12px}summary{cursor:pointer}details:target{border:2px solid #215343}@media(max-width:1200px){.columns{grid-template-columns:1fr}}'
    base='<script>if((location.protocol==="https:"||location.protocol==="http:")&&!location.pathname.endsWith("/")&&!location.pathname.endsWith(".html")){history.replaceState(null,"",location.pathname+"/"+location.search+location.hash);}</script>'
    head='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>王传福第5章复核修复对比</title>'+base+'<style>'+style+'</style></head><body>'
    rows=[]
    for r in records:
        m=r['metrics'];cells=[r['version'],m['research_sources'],m['analysis_sources'],m['analysis_records'],m['analysis_count'],r['pending_review_analysis_count'],m['analysis_chars']]
        rows.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in cells)+'</tr>')
    page=head+'<header><h1>王传福第5章：复核流程修复验证</h1><p>同一批91条研究记录、24个来源。仅重跑第5章，其余10个研究正文章节保留；摘要与索引按最终正文重建。</p><p>保留三版结果，按不同URL统计来源。分析预算600字符，原文展示预算1600字符，附表及证据台账另计。</p><p><a href="#comparison">三版完整章节</a> · <a href="evidence.html">本章完整证据台账</a> · <a href="metrics.json">统计与检查记录</a></p></header>'
    page+='<section class="card"><h2>实际结果</h2><div class="scroll"><table><thead><tr><th>版本</th><th>研究来源</th><th>分析引用来源</th><th>分析引用记录</th><th>分析条数</th><th>待复核条数</th><th>分析字符</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'
    page+='<p>'+esc(content['conclusion'])+'</p><p>最终样本包括人工逐项核对后的两处定向修订，均再次执行引用与语义复核；不是仅靠自动生成即通过验收。</p><ul>'+''.join('<li>'+esc(r['topic'])+'：'+esc(r['assessment'])+'</li>' for r in content['prior_topics'])+'</ul></section>'
    page+='<section class="card"><h2>本次改动与验证范围</h2><ul><li>复核空响应保留待复核草稿，不能变成不支持的判定，也不触发整章改写。</li><li>引用返回不齐时，仅对对应判断补核一次；所有引用仍须逐条获支持，不能自动删除未复核的编号或放宽检查。</li><li>只修订明确不受支持的判断，其他已通过或待复核的判断保留；修订部分按剩余字符预算压缩，并重新校验。</li><li>旧稿事项仅用于覆盖提醒，仍需以原文校验；引用重叠不证明内容完整。</li></ul><p>代码在此次生成过程中保持不变，测试结果见统计记录。</p><p>本次修复两轮实际请求共'+str(comparison['total_new_model_requests_for_this_fix'])+'次；最终一轮实际请求'+str(summary['model_requests'])+'次，返回'+str(summary['model_requests_returned'])+'次；另复用'+str(summary['exact_input_responses_reused'])+'条完全相同输入的既有响应，重新执行当前校验。前一轮修订后超长的972字符草稿已保留在工作记录中。无新增搜索、抓取或专业查询，接口未提供账单金额。</p><p>本页完成静态文件与引用检查，未进行浏览器视觉验收；本章样本通过情况不代表整份报告验收完成。</p></section>'
    page+='<section id="comparison"><h2>三版完整章节</h2><div class="columns">'+''.join(panes)+'</div></section></body></html>'
    (output/'index.html').write_text(page,encoding='utf-8')
    cards=[]
    for eid,f in sorted(evidence.items()):
        url=f.get('source_url','');link='<a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">'+esc(f.get('source_title') or url)+'</a>' if url.startswith(('http://','https://')) else esc(url)
        cards.append('<details id="wang-'+esc(eid)+'"><summary>'+esc(eid)+' · '+esc(f.get('source_title',''))+'</summary><p>'+link+'</p><blockquote>'+esc(f['fact'])+'</blockquote><p>'+esc(f.get('attribution_boundary',''))+'</p></details>')
    (output/'evidence.html').write_text(head+'<h1>本章完整研究证据</h1><p><a href="index.html">返回三版对比</a></p>'+''.join(cards)+'<script>function reveal(){const e=document.getElementById(decodeURIComponent(location.hash.slice(1)));if(e){e.open=true;e.scrollIntoView();}}addEventListener("hashchange",reveal);reveal();</script></body></html>',encoding='utf-8')
    targets={p.name:{tag['id'] for tag in BeautifulSoup(p.read_text(encoding='utf-8'),'html.parser').select('[id]')} for p in output.glob('*.html')}
    errors=[];checked=0
    for p in output.glob('*.html'):
        for tag in BeautifulSoup(p.read_text(encoding='utf-8'),'html.parser').select('a[href]'):
            u=urlsplit(tag['href'])
            if u.scheme or u.netloc:continue
            target=unquote(u.path) or p.name;checked+=1
            if not (output/target).is_file() or u.fragment and unquote(u.fragment) not in targets.get(target,set()):errors.append(tag['href'])
    assert not errors,errors
    (output/'checks.json').write_text(json.dumps({'checked_local_links':checked,'errors':errors,'visual_review_performed':False},indent=2),encoding='utf-8')
    print(json.dumps({'output':str(output),'checked_local_links':checked,'metrics':records[-1]['metrics'],'unresolved':d['unresolved_validation_rejections']},ensure_ascii=False))


if __name__=='__main__':main()
