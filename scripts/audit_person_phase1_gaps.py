"""Whole-report source-use and gap ledger; no model or source request is made."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]
from person_evidence import cited_ids, split_sections
from person_material_accounting import build_accounting


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def audit(run, corpus, output):
    contract, diagnostics = read(run / 'contract.json'), read(run / 'audit.json')
    report_bytes = (run / 'desktop_report.md').read_bytes()
    report = report_bytes.decode('utf-8')
    source_bytes = (corpus / 'source-snapshots.json').read_bytes()
    sha = hashlib.sha256(source_bytes).hexdigest()
    assert read(run / 'summary.json')['sources_sha256'] == sha
    sources = json.loads(source_bytes)
    accounting, _ = build_accounting(report, contract, diagnostics['section_diagnostics'])
    by_id = {f['evidence_id']: f for f in contract['facts']}
    by_url = {}
    for row in accounting['records']:
        by_url.setdefault(row['source_url'], []).append(row)
    source_rows, gaps = [], []
    for index, source in enumerate(sources):
        meta = source.get('source_metadata') or {}
        records = by_url.get(source['url'], [])
        body = [r['evidence_id'] for r in records if r['analysis_chapters'] or r['table_chapters'] or r['excerpt_chapters']]
        assessment = 'retained_source_pending_independent_review'
        if meta.get('identity_status') == 'quarantined':
            assessment = 'peer_context_only' if meta.get('person_peer_context') else 'subject_unresolved'
        elif meta.get('person_discovery_only') or meta.get('content_kind') in {'summary_only', 'search_summary', 'search_snippet'}:
            assessment = 'summary_or_index_requires_original'
        elif not str(source.get('content') or '').strip():
            assessment = 'original_unavailable'
        row = {'source_id': source.get('id'), 'source_index': index, 'url': source['url'],
            'title': source.get('title'), 'identity_state': meta.get('identity_status'),
            'identity_reason': meta.get('identity_reason'), 'collection_state': assessment,
            'content_kind': meta.get('content_kind'), 'fetch_status': meta.get('fetch_status'),
            'record_count': len(records), 'body_presence_ids': body,
            'appendix_record_ids': [r['evidence_id'] for r in records],
            'record_destinations': records,
            'boundary': 'Body presence and appendix indexing are not a substantive adoption verdict.'}
        source_rows.append(row)
        if assessment in {'subject_unresolved', 'summary_or_index_requires_original', 'original_unavailable'} or not records:
            gaps.append({'gap_id': 'SOURCE-' + str(index), 'source_url': source['url'],
                'kind': assessment if assessment != 'retained_source_pending_independent_review' else 'no_admitted_statement',
                'reason': meta.get('identity_reason') or '需定位原文及与研究问题的对应关系',
                'fix': '核对原件、身份范围与提取去向；不因采集失败形成个人风险', 'state': 'pending'})
    for row in accounting['records']:
        if not (row['analysis_chapters'] or row['table_chapters'] or row['excerpt_chapters']):
            gaps.append({'gap_id': 'BODY-' + row['evidence_id'], 'evidence_id': row['evidence_id'],
                'source_url': row['source_url'], 'kind': 'admitted_not_in_body_requires_importance_review',
                'reason': row['reason'], 'research_chapters': row['research_chapters'],
                'fix': '独立审稿判断是否重要、是否适用及是否已由其他来源实质合并；低重要性附录须说明理由',
                'state': 'pending_not_automatically_material_omission'})
    for index, error in enumerate(diagnostics.get('degradations', [])):
        gaps.append({'gap_id': 'REVIEW-' + str(index), 'chapter': error.get('chapter'),
            'kind': 'model_or_review_failure', 'reason': error.get('reasons'),
            'fix': '依照真实请求日志区分网络、空正文、格式、引用和实质审稿失败', 'state': 'pending'})
    collection = []
    for index, attempt in enumerate(read(corpus / 'summary.json').get('provider_attempts', [])):
        record = {k:attempt.get(k) for k in ('provider','tool','subject','status','reason','error_code','retrieved_at')}
        collection.append(record)
        if record['status'] in {'failed','not_queried','no_citable_record'}:
            gaps.append({'gap_id':'PLATFORM-' + str(index),
                'kind':'professional_platform_failure' if record['status']=='failed' else
                    'professional_tool_not_run' if record['status']=='not_queried' else 'returned_no_citable_record',
                'collection':record, 'state':'pending_collection_gap',
                'reason':'专业工具的失败、未查询和没有可引用记录分别保留，不作为个人风险或无风险。',
                'fix':'检查授权、地域、接口或数据准入原因；保留查询范围和下一步原件核查。'})
    sections = split_sections(report)
    review = []
    for chapter in range(2, 13):
        analyses = [line for line in sections.get(chapter, '').splitlines()
                    if line.startswith('- 研究判断（待人工复核）：')]
        selected = analyses if chapter in {7, 9, 10, 12} else analyses[:1]
        for index, line in enumerate(selected):
            supports = []
            for eid in sorted(cited_ids(line)):
                f = by_id.get(eid)
                if f:
                    original = next((s.get('content') or '' for s in sources if s['url'] == f['source_url']), '')
                    supports.append({'evidence_id': eid, 'source_url': f['source_url'], 'quote': f['fact'],
                        'exact_original_match': f['fact'] in original, 'scope': f.get('subject_scope'),
                        'event_date': f.get('event_date'), 'observation': f.get('observation')})
            review.append({'review_id': f'C{chapter}-{index}', 'chapter': chapter, 'claim': line,
                'sampling': 'all_high_risk_chapter_analyses' if chapter in {7, 9, 10, 12} else 'first_ordinary_analysis_in_chapter',
                'source_support': supports, 'independent_review_status': 'pending',
                'source_truth_or_responsibility_confirmed': False})
    write(output / 'source-use-ledger.json', source_rows)
    write(output / 'fact-use-ledger.json', accounting)
    write(output / 'gap-ledger.json', gaps)
    write(output / 'professional-collection-outcomes.json', collection)
    write(output / 'independent-citation-review-plan.json', review)
    summary = {'report_sha256': hashlib.sha256(report_bytes).hexdigest(),
        'report_hash_basis': 'raw_file_bytes', 'report_file': str((run / 'desktop_report.md').resolve()),
        'source_sha256': sha, 'sources': len(sources), 'admitted_records': len(accounting['records']),
        'record_destinations': accounting['dispositions'], 'gap_categories': dict(Counter(r['kind'] for r in gaps)),
        'independent_review_claims_planned': len(review), 'independent_review_claims_completed': 0,
        'full_report_accepted': False}
    write(output / 'gap-summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True, type=Path)
    ap.add_argument('--corpus', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args()
    audit(args.run.resolve(), args.corpus.resolve(), args.output.resolve())


if __name__ == '__main__':
    main()
