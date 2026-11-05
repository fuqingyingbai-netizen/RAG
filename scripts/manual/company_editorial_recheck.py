"""Recheck retained chapter prose without research, DB writes or old file changes."""
import argparse
from copy import deepcopy
import html
import json
from pathlib import Path
import sys
import time

from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--run',action='store_true',help='Allow real configured-model calls for failed batches only.')
    parser.add_argument('--max-calls',type=int,default=4)
    args=parser.parse_args()
    source=args.input.resolve();output=args.output.resolve()
    if source==output or not output.is_relative_to(ROOT/'work'):
        raise ValueError('output must be a separate folder under workspace/work')
    output.mkdir(parents=True,exist_ok=True)
    load_dotenv(ROOT/'.env',override=True)
    sys.path[:0]=[str(ROOT/'backend'),str(ROOT)]
    from report_agents.company_editorial import build_editorial_package,digest_groups,package_errors,parse_proposal,validate_audit
    from report_agents.company_corpus_writer import render_compact_chapters
    from report_agents.company_report_agent import COMPANY_REPORT_OUTLINE as outline
    from report_agents.company_delivery_contract import fill_evidence_gaps
    from research_workflow import ResearchWorkflow
    from types import SimpleNamespace

    objects=source/'objects'
    pointer=json.loads((objects/'projects/1/company_chapter_flow/current.json').read_text(encoding='utf-8'))
    state=json.loads((objects/pointer['key']).read_text(encoding='utf-8'))
    usage=deepcopy(state['usages']['7']);previous=deepcopy(state['editorials']['7'])
    target=state['scope']['target_name'];calls=[];native_usage=[];workflow=ResearchWorkflow()
    def invoke(role,prompt,trace):
        if not args.run:raise RuntimeError('real model not enabled')
        if len(calls)>=args.max_calls:raise RuntimeError('manual_call_limit')
        calls.append({'role':role,'input_chars':len(prompt)})
        print(json.dumps({'model_call':len(calls),'role':role},ensure_ascii=False),flush=True)
        return workflow._invoke_company_report_editor(role,prompt,usage_sink=native_usage.append)

    start=time.monotonic()
    package=build_editorial_package(usage,outline,target,invoke,previous=previous,workers=1)
    project=SimpleNamespace(target_name=target,company_editorial_package=package,company_information_usage_package=usage)
    sections=render_compact_chapters(project,{'groups':digest_groups(package)},outline,{7:state['sections']['7']})
    sections=fill_evidence_gaps(sections,package,outline,usage=usage)
    (output/'editorial.json').write_text(json.dumps(package,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'chapter-draft.md').write_text(sections[7],encoding='utf-8')
    summary={'kind':'retained_chapter_editorial_recheck_not_full_report_acceptance',
        'real_model_enabled':args.run,'target':target,'seconds':round(time.monotonic()-start,3),
        'new_search_requests':0,'new_source_parsing':0,'native_usage':native_usage,'calls':calls,
        'reused_batches':sum(bool(b.get('reused')) for b in package['batches']),
        'diagnostic':package['diagnostic'],'receipt_errors':package_errors(package,usage['records'],target),
        'chapter_body_chars':len(sections[7]),'chapter_question_coverage':state['coverage']['7']['complete']}
    (output/'result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    esc=html.escape
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>海天第七章 · 校验优化复测</title><style>body{font:16px/1.85 system-ui,"Microsoft YaHei";max-width:1000px;margin:30px auto;padding:0 22px;background:#f6f8fa;color:#203040}section,header{background:white;border:1px solid #dce3e8;padding:26px;margin:20px 0;border-radius:12px}pre{white-space:pre-wrap;font:inherit;overflow-wrap:anywhere}small{color:#657586}nav a{margin-right:20px}h1{line-height:1.4}.note{background:#fff4de;padding:14px}</style>'''
    page+='<header><small>2026-11-04 · 复用已保存原文及模型段落</small><h1>海天第七章：校验优化复测</h1><p class="note">单份公告的章节复测，不是完整公司报告。章节研究问题仍未完全覆盖，不能当作完整报告验收。</p>'
    page+='<p>原试跑通过信息：7 / 10；本次通过信息：'+str(package['diagnostic']['narrative_information'])+' / 10。复用批次：'+str(summary['reused_batches'])+'；新增模型调用：'+str(len(calls))+'；新增搜索：0。</p><nav><a href="#new">本次章稿</a><a href="#old">修改前章稿</a><a href="#pending">未通过批次的草稿</a></nav></header>'
    page+='<section id="new"><h2>本次实际章稿</h2><pre>'+esc(sections[7])+'</pre></section>'
    page+='<section id="old"><h2>修改前实际章稿</h2><pre>'+esc(state['sections']['7'])+'</pre></section>'
    page+='<section id="pending"><h2>尚未通过批次</h2>'
    for batch in package['batches']:
        if batch['accepted']:continue
        page+='<h3>'+esc(batch['aspect'])+'</h3><p>'+esc(batch['review_status'])+'</p>'
        for finding in (batch.get('attempts') or [{}])[-1].get('proposal',{}).get('findings',[]):
            page+='<pre>'+esc(str(finding.get('text','')))+'</pre>'
    page+='</section></html>'
    (output/'chapter-review-preview.html').write_text(page,encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return 0 if not summary['receipt_errors'] else 2


if __name__=='__main__':raise SystemExit(main())
