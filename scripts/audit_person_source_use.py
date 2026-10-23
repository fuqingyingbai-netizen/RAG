"""Account for every retained source row, separately from body citations.

Actual returned research inputs and deterministic tables prove processing
scope, never comprehension, source independence or real-world accuracy.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'backend')]
from person_evidence import split_sections, cited_ids


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def inspect(run):
    summary, contract, audit = [read(run/name) for name in ['summary.json','contract.json','audit.json']]
    source_path = Path(summary['baseline'])/'source-snapshots.json'
    sources = read(source_path)
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == summary['sources_sha256']
    sections = split_sections((run/'desktop_report.md').read_text(encoding='utf-8'))
    body_ids = set().union(*(cited_ids(sections[n]) for n in range(1,14)))
    by_id = {f['evidence_id']:f for f in contract['facts']}
    research, returned, deterministic = {}, set(), set()
    for n in range(2,13):
        package = contract['chapters'][str(n)]
        research[n] = {f['evidence_id'] for f in package.get('research_facts',package['facts'])}
        stage = audit.get('section_diagnostics',{}).get(str(n),{}).get('material_review',{})
        returned |= {eid for batch in stage.get('batches',[]) if batch.get('status')=='returned' for eid in batch['evidence_ids']}
        deterministic |= set(stage.get('deterministically_processed_evidence_ids',[]))
    all_research = set().union(*research.values())
    scans = {s['source_url']:s for s in contract.get('source_material_audit',[])}
    rows=[]
    for position, source in enumerate(sources,1):
        url = source['url']
        meta = source.get('source_metadata') or {}
        facts = {eid for eid,f in by_id.items() if f['source_url']==url}
        rejected = [f for f in contract['rejected'] if f.get('source_url')==url]
        pool_ids, body = facts & all_research, facts & body_ids
        scan = scans.get(url,{})
        reasons=Counter()
        for n in range(2,13):
            package=contract['chapters'][str(n)]
            for event in [*package.get('routing_audit',[]),*package.get('research_selection_audit',[])]:
                if event.get('evidence_id') in facts and event.get('status') in {'not_candidate','not_selected'}:
                    reasons[event.get('reason','unspecified')] += 1
        if body:
            state, reason = 'cited_in_body', '正文实际编号可回查；其余合格记录仍进入研究池'
        elif pool_ids & (returned|deterministic):
            state, reason = 'researched_without_body_citation', '材料已进入返回的研读批次或确定性表格处理，正文压缩后未逐条引用'
        elif pool_ids:
            state, reason = 'research_processing_incomplete', '已进入研究池但缺少完整返回或确定性处理记录，须继续诊断'
        elif facts and all(by_id[eid].get('claim_type') not in {'person_platform_record','person_company_record'}
                and '。' not in by_id[eid]['fact']
                and re.search(r'(?:19|20)\d{2}[-./]\d{2}[-./]\d{2}|相关阅读|更多>>', by_id[eid]['fact']) for eid in facts):
            state, reason = 'retained_lead_or_unavailable_original', '仅有日期标题或相关链接，未取得可采纳的对应文章正文'
        elif facts:
            state, reason = 'no_admitted_chapter_material', '有来源陈述，但经逐章相关性、原文字形或重复规则后未进入实质研究池'
        elif rejected:
            state, reason = 'statements_rejected', '已有事实候选未通过身份、原文、时期或归属校验'
        elif scan.get('status') == 'not_admitted':
            reason=scan.get('reason','')
            state='identity_not_admitted' if reason=='identity_not_admitted' else 'retained_lead_or_unavailable_original'
        elif scan.get('status') == 'scanned':
            state, reason = 'scanned_no_admissible_person_statement', scan.get('reason') or '完整目标姓名陈述未通过原文或逐章相关性校验'
        else:
            state, reason = 'source_accounting_missing', '缺少原始来源处理记录'
        rows.append({'source_row':position,'title':source['title'],'url':url,
            'retained_chars':len(source.get('content') or ''),'content_kind':meta.get('content_kind'),
            'identity_confidence':meta.get('identity_confidence'),'fetch_status':meta.get('fetch_status'),
            'provider':meta.get('provider'),'platform':meta.get('platform'),
            'state':state,'reason':reason,'normalized_fact_count':len(facts),
            'research_fact_count':len(pool_ids),'body_fact_count':len(body),
            'returned_model_fact_count':len(pool_ids & returned),
            'deterministically_processed_fact_count':len(pool_ids & deterministic),
            'research_chapters':[n for n,ids in research.items() if ids & facts],
            'body_evidence_ids':sorted(body),'research_evidence_ids':sorted(pool_ids),
            'rejected_statement_reasons':dict(Counter(f['rejection_reason'] for f in rejected)),
            'chapter_routing_and_selection_reasons':dict(reasons),
            'original_scan':{k:v for k,v in scan.items() if k not in {'source_url','source_title','rejected_spans'}},
            'non_evidence_span_reasons':dict(Counter(s['reason'] for s in scan.get('rejected_spans',[])))})
    query_rows={}
    for n in [9,12]:
        for query in contract['chapters'][str(n)].get('query_coverage',[]):
            query_rows[tuple(str(query.get(k,'')) for k in ['provider','subject','tool','status','reason'])]=query
    return {'sources_sha256':summary['sources_sha256'],'source_rows':len(sources),
        'normalized_source_urls':len({r['url'].rstrip('/') for r in rows}),
        'states':dict(Counter(r['state'] for r in rows)),
        'missing_accounting_rows':[r['source_row'] for r in rows if r['state']=='source_accounting_missing'],
        'incomplete_research_rows':[r['source_row'] for r in rows if r['state']=='research_processing_incomplete'],
        'professional_source_rows':[r['source_row'] for r in rows if r['url'].startswith('structured://')],
        'professional_query_coverage':list(query_rows.values()),
        'sources':rows,
        'limits':['A fetched source may be only a retained partial PDF, snippet or failed original.',
                  'Local full-text scans seek target-anchored statements; they are not a full-document human review.',
                  'Returned model inputs do not prove comprehension or independent verification.',
                  'Different URLs may repeat the same original report and are not independent confirmations.']}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('run',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=inspect(args.run.resolve())
    output=args.output or args.run/'source-use-audit.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'sources','professional_query_coverage'}},ensure_ascii=False))


if __name__=='__main__':
    main()
