"""Publish a new local comparison without replacing the fixed round-21 archive."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import unquote, urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'scripts')]
from person_evidence import split_sections, cited_ids
from audit_person_source_use import inspect as source_use
from audit_person_report_quality import inspect as quality
from build_person_quality_review import render, source_use_page
from build_person_evidence_ledger import build as evidence_ledger
from build_person_optimization_h5 import CSS, JS, page, stats
from replay_person_chapters import generation_code_snapshot
from person_structured_tables import relationship_groups
from bs4 import BeautifulSoup

H=html.escape


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def search_stages(audit):
    stages=[('initial',audit.get('attempts',[]))]
    stages += [('followup_'+str(i+1),x.get('attempts',[])) for i,x in enumerate(audit.get('followup_iterations',[]))]
    if audit.get('primary_identity_followup'):
        stages.append(('primary_identity',audit['primary_identity_followup'].get('attempts',[])))
    return [{'stage':label,'logged_requests':len(rows),'returned_result_count':sum(r.get('result_count',0) for r in rows)} for label,rows in stages]


def model_call_history(work,key):
    rows=[]
    for run in sorted(work.iterdir()):
        if not run.is_dir() or not run.name.endswith('-'+key):
            continue
        def jsonl(name):
            path=run/name
            return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()] if path.exists() else []
        inputs=jsonl('chapter-model-inputs.jsonl');events=jsonl('chapter-iteration-events.jsonl')
        if not inputs:
            continue
        known={r['input_sha256']:r['status'] for r in events}
        receipts=read(run/'request-status.json') if (run/'request-status.json').exists() else []
        rows.append({'run':run.name,'completed_new_requests':len(receipts),
            'returned_new_requests':sum(r['status']=='returned' for r in receipts),
            'failed_new_requests':sum(r['status']=='failed' for r in receipts),
            'exact_input_reuses':sum(r['status']=='exact_input_reused' for r in events),
            'interrupted_requests_with_unknown_outcome':[{'role':r['role'],'input_sha256':r['input_sha256']}
                for r in inputs if r['input_sha256'] not in known],
            'status':'interrupted_not_delivered' if (run/'interruption.json').exists() else 'completed' if (run/'summary.json').exists() else 'pending'})
    return rows


def normalized_render(text,key,side):
    soup=BeautifulSoup(render(text,key+'-'+side),'html.parser')
    ledger=key+'-'+('before-' if side=='before' else '')+'evidence.html'
    for link in soup.select('a[data-eid]'):
        link['href']=ledger+'#'+link['data-eid']
        link.attrs.pop('data-side',None)
    return str(soup)


def link_check(out):
    pages={p.resolve():BeautifulSoup(p.read_text(encoding='utf-8'),'html.parser') for p in out.rglob('*.html')}
    issues=[]; checked=0
    for path,soup in pages.items():
        for tag in soup.select('[href],[src]'):
            value=tag.get('href') or tag.get('src')
            parts=urlsplit(value)
            if parts.scheme or parts.netloc:
                continue
            target=(path.parent/unquote(parts.path)).resolve() if parts.path else path
            checked+=1
            if not target.exists():issues.append({'page':str(path.relative_to(out)), 'link':value,'reason':'missing_file'})
            elif parts.fragment and target in pages and not pages[target].find(id=unquote(parts.fragment)):
                issues.append({'page':str(path.relative_to(out)), 'link':value,'reason':'missing_anchor'})
    return {'checked_local_references':checked,'issues':issues,'browser_visual_qa':'not_performed_due_to_existing_browser_access_boundary'}


def build(out,runs):
    out.mkdir(parents=True,exist_ok=True)
    fixed=ROOT/'deliverables/person-report-quality-20261021'
    old_h5=ROOT/'deliverables/person-optimization-h5-20261023/dist'
    for p in old_h5.glob('projects/**/*.svg'):
        dest=out/p.relative_to(old_h5);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
    (out/'style.css').write_text(CSS+'\n.card .stats{grid-template-columns:repeat(2,minmax(0,1fr))}.stat{min-width:0}.stat b{overflow-wrap:anywhere}',encoding='utf-8');(out/'app.js').write_text(JS,encoding='utf-8')
    code_sha=hashlib.sha256(json.dumps(generation_code_snapshot(),sort_keys=True).encode()).hexdigest()
    manifest={'generated_utc':datetime.now(timezone.utc).isoformat(),'scope':'new body retrieval plus code and report changes; not same-material attribution',
              'original_research_cutoff':'2026-10-20','new_body_retrieval_date':'2026-10-23','subjects':{},
              'limits':['网页补抓不证明截止日当时的页面内容相同。','历史搜索日志缺少完整候选URL，无法还原全量去重漏斗。',
                        '模型收到材料不代表已理解或独立核实。','只做静态版式与链接检查，未完成浏览器视觉验收和PDF原页核验。']}
    tests=ROOT/'work/person-coverage-20261023/test-results.json'
    if tests.exists():
        manifest['person_test_results']=read(tests)
        shutil.copyfile(tests,out/'test-results.json')
    cards=[]
    for key,name in [('wang','王传福'),('zhang','张勇（海底捞）')]:
        run=runs[key]; summary=read(run/'summary.json'); corpus=Path(summary['baseline'])
        assert summary['code_unchanged_during_run'] and summary['generation_code_sha256']==code_sha
        use=source_use(run); inspection=quality(run); contract=read(run/'contract.json')
        old_use=read(fixed/(key+'-source-use.json'))
        before_path=ROOT/'work/person-six-hour/round21'/key/'desktop_report.md'
        before_text=before_path.read_text(encoding='utf-8');after_text=(run/'desktop_report.md').read_text(encoding='utf-8')
        before,after=split_sections(before_text),split_sections(after_text)
        assert len(before)==len(after)==15
        assert not inspection['displayed_original_literal_mismatches']
        before_ids=set().union(*(cited_ids(before[n]) for n in range(1,14)))
        body_ids=set().union(*(cited_ids(after[n]) for n in range(1,14)))
        by_id={f['evidence_id']:f for f in contract['facts']}
        research_ids={f['evidence_id'] for n in range(2,13) for f in contract['chapters'][str(n)]['research_facts']}
        research_sources={by_id[e]['source_url'] for e in research_ids}
        body_sources={by_id[e]['source_url'] for e in body_ids if e in by_id}
        analyses=[a for ch in inspection['chapters'] if 2<=ch['chapter']<=12 for a in ch['analyses']]
        analysis_ids={e for a in analyses for e in a['evidence_ids']}
        structured_ids={e for n in (4,9) for e in cited_ids(after[n].split('### '+('关联公司背景资料归并表' if n==4 else '专业平台关联记录完整归并表'))[-1])
                        if e in by_id and by_id[e]['claim_type'] in {'person_company_record','person_platform_record'}}
        retrieval=read(corpus/'person_retrieval_audit.json'); stages=search_stages(retrieval)
        fetches=read(corpus/'new-fetch-receipts.json')
        missing_research=[r['chapter'] for r in inspection['chapters'] if r['all_research_records_accounted_for'] is False]
        guard=[{'chapter':c['chapter'],'analysis':a['analysis'],'reasons':a['complete_guard_rejections']}
               for c in inspection['chapters'] for a in c['analyses'] if a['complete_guard_rejections']]
        audit=read(run/'audit.json')
        platform_groups=relationship_groups(contract['chapters']['9']['research_facts'])
        platform_counts={'record_count':sum(len(g['ids']) for g in platform_groups.values()),
                         'merged_rows':len(platform_groups),'historical_enterprise_rows':sum(k[1] for k in platform_groups),
                         'platform_listed_enterprise_rows':sum(not k[1] for k in platform_groups)}
        metrics={'retained_sources':use['source_rows'],'research_sources':len(research_sources),'body_sources_including_tables':len(body_sources),
                 'analysis_support_sources':len({by_id[e]['source_url'] for e in analysis_ids}),
                 'body_records_including_tables':len(body_ids),'structured_table_records':len(structured_ids),
                 'before_research_sources':sum(r['research_fact_count']>0 for r in old_use['sources']),
                 'before_body_sources':sum(r['body_fact_count']>0 for r in old_use['sources']),
                 'new_fetch_calls':len(fetches),'recovered_body_sources':sum(r['accepted_replacement'] for r in fetches),
                 'new_search_calls':0,'new_professional_calls':0,'old_logged_search_hits':sum(s['returned_result_count'] for s in stages),
                 'last_render_new_model_requests':summary['model_requests'],'last_render_failed_model_requests':summary['model_requests_failed'],
                 'missing_research_chapters':missing_research,'post_render_guard_rejections':guard,'degradations':audit['degradations']}
        metrics['professional_relationship_table']=platform_counts
        new_uses=[]
        for row in use['sources']:
            new_uses.append({**row,'analysis_support_record_count':len(analysis_ids.intersection({f['evidence_id'] for f in contract['facts'] if f['source_url']==row['url']})),
                'structured_table_record_count':len(structured_ids.intersection({f['evidence_id'] for f in contract['facts'] if f['source_url']==row['url']}))})
        funnel={'historical_search_stages':stages,'historical_unique_candidate_urls':None,
                'historical_unrecoverable_boundary':'旧日志未保存全量命中URL；无法把累计结果数减去保存来源数解释成重复或无效数量。chapter_7_8_followup是followup_iterations的重复字段，不再次累计。',
                'metrics':metrics,'states':use['states'],'sources':new_uses,
                'original_sources_sha256':read(corpus/'summary.json')['original_sources_sha256'],'new_sources_sha256':summary['sources_sha256'],
                'fixed_before_report_sha256':hashlib.sha256(before_text.encode()).hexdigest(),
                'after_report_sha256':hashlib.sha256(after_text.encode()).hexdigest()}
        funnel['new_model_call_history_including_interrupted_runs']=model_call_history(ROOT/'work/person-coverage-20261023',key)
        if (run/'editorial-review.json').exists():
            funnel['editorial_review']=read(run/'editorial-review.json')
            shutil.copyfile(run/'editorial-review.json',out/(key+'-editorial-review.json'))
        metrics['all_generation_completed_model_requests']=sum(r['completed_new_requests'] for r in funnel['new_model_call_history_including_interrupted_runs'])
        metrics['all_generation_failed_model_requests']=sum(r['failed_new_requests'] for r in funnel['new_model_call_history_including_interrupted_runs'])
        metrics['interrupted_requests_with_unknown_outcome']=sum(len(r['interrupted_requests_with_unknown_outcome']) for r in funnel['new_model_call_history_including_interrupted_runs'])
        funnel['new_fetch_call_boundary']='83 total URL-fetch operations across both subjects; each operation may make multiple underlying HTTP attempts. No new search-provider or professional-platform calls.'
        manifest['subjects'][key]=funnel
        for suffix in ['html','json']:
            shutil.copyfile(fixed/(key+'-evidence.'+suffix),out/(key+'-before-evidence.'+suffix))
        (out/(key+'-before.md')).write_text(before_text,encoding='utf-8');(out/(key+'-after.md')).write_text(after_text,encoding='utf-8')
        write_json(out/(key+'-source-use.json'),use);write_json(out/(key+'-flow.json'),funnel)
        write_json(out/(key+'-fetch-receipts.json'),fetches);write_json(out/(key+'-quality.json'),inspection)
        (out/(key+'-source-use.html')).write_text(source_use_page(use,name),encoding='utf-8')
        evidence_ledger(run,out,key,name)
        status='内部评审稿；全部研读输入已对账' if not missing_research and not audit['degradations'] and not guard else '内部评审稿；仍有未完成研读或待修复项，详见验证记录'
        intro=f'<section class="hero"><div class="eyebrow">SOURCE COVERAGE / 2026.10.23</div><h1>{H(name)} · 材料利用优化</h1><p>固定第21轮报告 → 本轮补取原文后的实际报告。新增抓取改变了材料范围，差异不能只归因于代码改进。</p><p class="meta">{H(status)}<br>旧研究截止：2026-10-20；新补取：2026-10-23。网页可能更新，具体事件时期仍须核对。</p></section>'
        numbers=stats([(f'{metrics["before_research_sources"]} → {len(research_sources)}','进入研究的来源'),
                       (f'{metrics["before_body_sources"]} → {len(body_sources)}','正文及结构化表引用来源'),
                       (str(metrics['recovered_body_sources']),'本轮恢复身份匹配正文'),
                       (str(metrics['analysis_support_sources']),'模型判断实际支持来源')])
        links=f'<div class="tools"><a href="{key}-report.html">优化后全文</a><a href="{key}-source-use.html">逐条来源去向</a><a href="{key}-evidence.html">完整证据台账</a><a href="{key}-flow.json">覆盖与口径 JSON</a><a href="{key}-after.md" download>下载 Markdown</a></div>'
        if platform_counts['record_count']:
            links += f'<section class="panel"><h2>平台材料的具体去向</h2><p>{platform_counts["record_count"]}条任职及关联记录归并为{platform_counts["merged_rows"]}行，包含{platform_counts["platform_listed_enterprise_rows"]}家平台所列企业与{platform_counts["historical_enterprise_rows"]}家历史关联企业。不同工具字段并列保留，详见第9章完整表；不据此认定现任或个人风险。</p></section>'
        nav=''.join(f'<a href="#chapter-{n}"><span>{n:02d}</span>{H(after[n].splitlines()[0])}</a>' for n in range(1,16))
        sections=[];full=[]
        notes={4:'补列公司背景归并表，保留来源及原字段；公司事实不推定个人贡献。',9:'将专业平台任职与关联记录按企业及历史标记归并，保留全部入表字段和证据编号。',14:'正文引用索引随实际引用重建，包含完整结构化表。',15:'核对补取后仍未解决的缺口及查询限制。'}
        for n in range(1,16):
            content={side:normalized_render(text[n],key,side) for side,text in [('before',before),('after',after)]}
            panes=''.join(f'<section class="pane {side}"><div class="pane-label">{label} · {len(text[n]):,} 字符</div><div class="doc">{content[side]}</div></section>' for side,label,text in [('before','固定第21轮',before),('after','本轮补取后',after)])
            sections.append(f'<article class="chapter" id="chapter-{n}"><h2>{H(after[n].splitlines()[0].removeprefix("## "))}</h2><p class="note">{H(notes.get(n,"完整保留本轮实际章节；新增材料、判断及来源边界见正文和台账。"))}</p><div class="columns">{panes}</div></article>')
            full.append(f'<article class="chapter" id="chapter-{n}"><div class="doc">{content["after"]}</div></article>')
        comparison='<div class="layout"><aside>'+nav+'</aside><main>'+intro+numbers+links+''.join(sections)+'</main></div>'
        (out/(key+'.html')).write_text(page(name+' · 15章前后对比',comparison,'<a href="index.html">返回入口</a><button data-toggle="reading-after">仅看本轮报告</button>'),encoding='utf-8')
        (out/(key+'-report.html')).write_text(page(name+' · 本轮报告全文','<main class="wrap">'+intro+links+''.join(full)+'</main>','<a href="index.html">返回入口</a>'),encoding='utf-8')
        cards.append(f'<article class="card"><h2>{H(name)}</h2>{numbers}<p>{H(status)}</p><a class="cta" href="{key}.html">查看15章前后对比 →</a></article>')
    body='<main class="wrap"><section class="hero"><div class="eyebrow">EVIDENCE TO REPORT / 2026.10.23</div><h1>人物报告 · 扩大材料利用</h1><p>补取留存原文，修复隐性数量截断，将专业平台的历史关联和公司背景放入归并表。保留固定的第21轮基线，逐章比较实际报告。</p><p class="meta">新增原文抓取83次；新增搜索与专业平台调用均为0。原研究截止2026-10-20，本次补取2026-10-23；属于新增材料优化。</p></section><div class="cards" style="margin-top:24px">'+''.join(cards)+'</div><section class="panel"><h2>统计边界</h2><p>正文引用包含归并表中的来源，另列模型判断实际支持来源，避免把列入表格等同于形成结论。进入研究表示材料输入或确定性处理已留痕，不表示独立核实。</p><p>旧搜索日志仍缺全量候选 URL，因此去重候选数留空。所有保存来源都有单独处理去向；不同阶段的数量不能直接相减。</p><p><a href="manifest.json">完整来源漏斗、报告摘要值及检查结果</a></p></section><div class="notice"><strong>内部评审稿</strong><p>原件真实性、PDF原页及浏览器视觉验收尚未完成。新增抓取的页面可能较原截止日更新，不作同材料实验。</p></div></main>'
    (out/'index.html').write_text(page('人物报告 · 扩大材料利用',body),encoding='utf-8')
    review_path=ROOT/'work/person-coverage-20261023/final-chapter-review.json'
    if review_path.exists():
        review=read(review_path)
        for key in runs:
            assert review['subjects'][key]['report_sha256']==manifest['subjects'][key]['after_report_sha256'], 'Chapter review is stale'
            assert len(review['subjects'][key]['chapters'])==15
        shutil.copyfile(review_path,out/'chapter-review.json')
        manifest['chapter_review_file']='chapter-review.json'
    write_json(out/'manifest.json',manifest)
    checks=link_check(out);write_json(out/'checks.json',checks)
    assert not checks['issues'],checks['issues'][:5]
    print(json.dumps({'output':str(out),'subjects':{k:v['metrics'] for k,v in manifest['subjects'].items()},'links':checks},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--wang',type=Path,required=True);parser.add_argument('--zhang',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'deliverables/person-coverage-20261023/dist')
    args=parser.parse_args();build(args.output.resolve(),{'wang':args.wang.resolve(),'zhang':args.zhang.resolve()})
