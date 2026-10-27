"""Publish four same-corpus automatic post-writing acceptance samples."""
import hashlib
import html
import json
from pathlib import Path
import sys
from urllib.parse import unquote,urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'scripts')]
from bs4 import BeautifulSoup
from person_evidence import split_sections
from audit_person_report_quality import inspect
from build_person_prose_rerun import metrics,rendered


def read(p):return json.loads(p.read_text(encoding='utf-8'))


def main():
    work=ROOT/'work/person-content-acceptance-20261023';output=ROOT/'deliverables/person-content-acceptance-20261023/dist'
    output.mkdir(parents=True,exist_ok=True);esc=lambda v:html.escape(str(v),quote=True)
    cases=[('wang5','王传福',5,work/'wang5-v5',ROOT/'work/person-review-fix-20261023/wang-final'),
           ('wang3','王传福',3,work/'wang3-v2',ROOT/'work/person-prose-rerun-20261023/wang'),
           ('zhang3','张勇',3,work/'zhang-v2',ROOT/'work/person-prose-rerun-20261023/zhang-retry'),
           ('zhang5','张勇',5,work/'zhang-v2',ROOT/'work/person-prose-rerun-20261023/zhang-retry')]
    labels={'passed_without_targeted_repair':'自动通过','passed_after_targeted_repair':'自动定向修订后通过','pending_review':'仍待复核'}
    rows=[];sections=[];evidence=[];runs={}
    for key,name,n,run,automatic in cases:
        summary=read(run/'summary.json');assert summary['code_unchanged_during_run']
        base=Path(summary['prior_run']);previous=read(base/'summary.json');assert summary['sources_sha256']==previous['sources_sha256']
        runs[str(run.relative_to(work))]={k:summary[k] for k in ['sources_sha256','generation_code_sha256','model_requests','model_requests_returned','model_requests_failed','exact_input_responses_reused','new_search_calls','new_fetch_calls','new_professional_calls','scope','actual_cost_available']}
        contract=read(run/'contract.json');before_contract=read(automatic/'contract.json');prior_contract=read(base/'contract.json')
        after=split_sections((run/'desktop_report.md').read_text(encoding='utf-8'))[n]
        before=split_sections((automatic/'desktop_report.md').read_text(encoding='utf-8'))[n]
        prior=split_sections((base/'desktop_report.md').read_text(encoding='utf-8'))[n]
        result=read(run/'acceptance-results.json')[str(n)];a=metrics(after,contract['chapters'][str(n)])
        b=metrics(before,before_contract['chapters'][str(n)]);old=metrics(prior,prior_contract['chapters'][str(n)])
        quality=inspect(run);q=next(r for r in quality['chapters'] if r['chapter']==n)
        (run/'quality-inspection.json').write_text(json.dumps(quality,ensure_ascii=False,indent=2),encoding='utf-8')
        if result['status']!='pending_review':
            assert not result['unresolved'] and result['content_acceptance']['status'].startswith('passed')
            assert all(not c['complete_guard_rejections'] and not c['explicit_source_boundary_issues'] for c in q['analyses'])
            assert a['analysis_chars']<=600
        assert not q['unknown_evidence_ids']
        row={'key':key,'name':name,'chapter':n,'title':contract['chapters'][str(n)]['title'],
            'status':result['status'],'baseline':old,'input_automatic_draft':b,'after':a,
            'acceptance':result,'new_model_requests':result['new_model_requests'],
            'report_sha256':hashlib.sha256((run/'desktop_report.md').read_bytes()).hexdigest(),
            'source_hash':summary['sources_sha256']}
        rows.append(row)
        c=result['content_acceptance'];first=c.get('initial_review',{});final=c.get('final_review',first)
        checklist=[]
        for item in final.get('items',[]):
            checklist.append('<li>旧稿事项 '+str(item['prior_index']+1)+'：'+esc(item['status'])+' — '+esc(item.get('reason',''))+'</li>')
        technical={'initial_issues':first.get('issues',[]),'target_claim_indices':c.get('target_claim_indices',[]),
            'preserved_claim_indices':c.get('preserved_claim_indices',[]),'same_document_citation_alignment':c.get('same_document_citation_alignment',[]),
            'remaining_issues':result['unresolved'],'content_acceptance_status':c['status'],
            'unaccepted_candidate':c.get('candidate_repair',c.get('rejected_repair',[]))}
        review_note=('以下为未采纳修订候选的复核；候选未全部通过，右栏保留原自动稿，仍待复核。'
                     if c.get('final_review') and result['status']=='pending_review' else '以下逐条核对旧稿判断中的实质内容。')
        sections.append('<section id="'+key+'"><h2>'+esc(name)+f' 第{n}章 · '+esc(row['title'])+'</h2><p><strong>'+esc(labels[row['status']])+'</strong>；旧稿判断 '+str(result['prior_items'])+' 条（各条逐项核对）；本轮新增模型请求 '+str(row['new_model_requests'])+' 次。</p><p>'+review_note+'</p><ul>'+''.join(checklist)+'</ul><details><summary>验收及定向修订依据</summary><pre>'+esc(json.dumps(technical,ensure_ascii=False,indent=2))+'</pre></details><div class="columns"><article><h3>既有自动稿</h3>'+rendered(before,key)+'</article><article><h3>自动写后验收结果</h3>'+rendered(after,key)+'</article></div></section>')
        pool={f['evidence_id']:f for p in [contract['chapters'][str(n)],before_contract['chapters'][str(n)]] for f in p.get('research_facts',p['facts'])}
        for eid,f in sorted(pool.items()):
            url=f.get('source_url','');link='<a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">'+esc(f.get('source_title') or url)+'</a>' if url.startswith(('http://','https://')) else esc(url)
            evidence.append('<details id="'+key+'-'+esc(eid)+'"><summary>'+esc(name)+f' 第{n}章 · '+esc(eid)+' · '+esc(f.get('source_title',''))+'</summary><p>'+link+'</p><blockquote>'+esc(f['fact'])+'</blockquote><p>'+esc(f.get('attribution_boundary',''))+'</p></details>')
    counts={value:sum(r['status']==value for r in rows) for value in labels}
    probes=[]
    for name in ['wang5','wang5-final','wang5-accepted','wang5-complete','wang5-v4','wang3','zhang']:
        p=work/name/'summary.json'
        if p.exists():
            s=read(p);probes.append({'phase':name,'model_requests':s['model_requests'],'results':s['results']})
    total=sum(r['model_requests'] for r in runs.values())+sum(p['model_requests'] for p in probes)
    public={'scope':'automatic_postwriting_acceptance_on_archived_auto_drafts_not_fresh_research_or_full_report_acceptance',
        'counts':counts,'runs':runs,'probe_history':probes,'total_new_model_requests':total,'cases':rows,'tests':read(work/'test-results.json'),
        'boundary':'Distinct URL counts and model-aided content review are not independent fact verification. Prior admitted draft items are checked; this does not prove every research record should appear in prose.'}
    (output/'metrics.json').write_text(json.dumps(public,ensure_ascii=False,indent=2),encoding='utf-8')
    style='body{max-width:1500px;margin:28px auto;padding:0 20px;font:15px/1.75 system-ui,"Microsoft YaHei",sans-serif;color:#203b34;background:#f3f5f4}header,section,.card,article,details{background:white;border:1px solid #d5dfd9;border-radius:8px;padding:20px;margin:16px 0;min-width:0;overflow-wrap:anywhere}h1,h2{color:#205a45}a{color:#176247;overflow-wrap:anywhere}.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse}th,td{border:1px solid #d1ddd6;padding:9px;text-align:left}.columns{display:grid;grid-template-columns:1fr 1fr;gap:14px}blockquote,pre{white-space:pre-wrap;background:#f3f5f4;padding:12px;border-left:3px solid #a1b9ad;margin:12px 0}summary{cursor:pointer}details:target{border:2px solid #205a45}@media(max-width:1050px){.columns{grid-template-columns:1fr}}'
    base='<script>if((location.protocol==="https:"||location.protocol==="http:")&&!location.pathname.endsWith("/")&&!location.pathname.endsWith(".html")){history.replaceState(null,"",location.pathname+"/"+location.search+location.hash);}</script>'
    head='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>人物报告自动事项验收</title>'+base+'<style>'+style+'</style></head><body>'
    table=[]
    for r in rows:
        table.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [r['name']+f" 第{r['chapter']}章",labels[r['status']],r['after']['research_sources'],
            f"{r['baseline']['analysis_sources']} → {r['input_automatic_draft']['analysis_sources']} → {r['after']['analysis_sources']}",
            r['after']['analysis_records'],r['after']['analysis_chars']])+'</tr>')
    page=head+'<header><h1>人物报告：自动事项覆盖与职务核对</h1><p>对已有自动稿重新执行写后验收、定向修订与复核；没有重新生成研究批次，没有人工提供替换句子，没有新增检索、抓取或专业查询。</p><p>同一批留存材料对比；检查旧稿仍有原文依据的事项是否保留，以及职务、引用和600字符分析预算。验收是模型辅助核对，不是来源真实性认证，也不代表所有研究卡都已写进正文。</p><p>'+esc('；'.join(labels[k]+' '+str(v)+' 章' for k,v in counts.items()))+'</p><p><a href="evidence.html">四章完整研究证据</a> · <a href="metrics.json">完整统计与调用记录</a></p></header>'
    page+='<section><h2>四章结果</h2><div class="scroll"><table><thead><tr><th>样本</th><th>状态</th><th>研究来源</th><th>分析引用来源：原规则→既有自动稿→本轮</th><th>引用记录</th><th>分析字符</th></tr></thead><tbody>'+''.join(table)+'</tbody></table></div><p>来源按不同URL计；证据记录可能语义重叠。待复核章节不计为验收通过。</p></section>'+''.join(sections)
    page+='<section><h2>验证与边界</h2><p>人物报告测试 '+str(public['tests']['passed'])+' 项通过。含前置试跑在内，本次新增模型请求 '+str(total)+' 次，均保留回执；账单金额不可用。</p><p>文件及锚点已作静态检查，未进行浏览器视觉验收。无部署、无数据库写入、未覆盖旧版汇报。本轮只检查四章样本，未宣布全报告完成。</p></section></body></html>'
    (output/'index.html').write_text(page,encoding='utf-8')
    (output/'evidence.html').write_text(head+'<h1>四章完整研究证据</h1><p><a href="index.html">返回自动验收对比</a></p>'+''.join(evidence)+'<script>function reveal(){const e=document.getElementById(decodeURIComponent(location.hash.slice(1)));if(e){e.open=true;e.scrollIntoView();}}addEventListener("hashchange",reveal);reveal();</script></body></html>',encoding='utf-8')
    targets={p.name:{t['id'] for t in BeautifulSoup(p.read_text(encoding='utf-8'),'html.parser').select('[id]')} for p in output.glob('*.html')}
    checked=0;errors=[]
    for p in output.glob('*.html'):
        for tag in BeautifulSoup(p.read_text(encoding='utf-8'),'html.parser').select('a[href]'):
            u=urlsplit(tag['href'])
            if u.scheme or u.netloc:continue
            target=unquote(u.path) or p.name;checked+=1
            if not (output/target).is_file() or u.fragment and unquote(u.fragment) not in targets.get(target,set()):errors.append(tag['href'])
    assert not errors,errors[:10]
    (output/'checks.json').write_text(json.dumps({'checked_local_links':checked,'errors':errors,'visual_review_performed':False},indent=2),encoding='utf-8')
    print(json.dumps({'output':str(output),'counts':counts,'new_model_requests':total,'local_links':checked},ensure_ascii=False))


if __name__=='__main__':main()
