"""Inspect actual chapter prose and evidence; do not score real-world truth."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend')]
from person_evidence import split_sections, cited_ids
from person_source_boundaries import source_context_errors


def inspect(run):
    report = (run / 'desktop_report.md').read_text(encoding='utf-8')
    contract = json.loads((run / 'contract.json').read_text(encoding='utf-8'))
    audit = json.loads((run / 'audit.json').read_text(encoding='utf-8'))
    by_id = {f['evidence_id']: f for f in contract['facts']}
    sections = split_sections(report)
    rows, quote_uses, analysis_uses = [], defaultdict(list), defaultdict(list)
    for n in range(1, 16):
        body = sections.get(n, '')
        package = contract['chapters'][str(n)]
        pool = package.get('research_facts', package['facts'])
        diagnostic = audit.get('section_diagnostics', {}).get(str(n), {})
        displayed = re.findall(r'\*\*来源记录 \d+.*?\[(E-[A-Z0-9-]+)\]', body)
        analyses = []
        for line in body.splitlines():
            if line.startswith('- 研究判断（待人工复核）：'):
                ids = sorted(cited_ids(line))
                statement = re.sub(r'\s*\[E-[A-Z0-9-]+\]', '', line.split('：', 1)[1]).strip()
                supports = [by_id[eid] for eid in ids if eid in by_id]
                analyses.append({'analysis': statement, 'evidence_ids': ids,
                                 'explicit_source_boundary_issues': source_context_errors(statement, supports)})
                analysis_uses[statement].append(n)
        for eid in displayed:
            quote_uses[eid].append(n)
        all_ids = cited_ids(body)
        research = diagnostic.get('material_review', {})
        input_ids = research.get('input_evidence_ids', [])
        batch_ids = [eid for batch in research.get('batches', []) for eid in batch['evidence_ids']]
        rows.append({'chapter': n, 'title': package['title'], 'chars': len(body),
            'research_facts': len(pool), 'research_source_urls': len({f['source_url'] for f in pool}),
            'displayed_original_records': displayed, 'cited_fact_count': len(all_ids),
            'cited_source_urls': len({by_id[eid]['source_url'] for eid in all_ids if eid in by_id}),
            'unknown_evidence_ids': sorted(all_ids - by_id.keys()),
            'model_input_count': len(input_ids), 'batch_input_accounted_for': input_ids == batch_ids,
            'research_request_status': research.get('status', 'no_model_research_stage'),
            'research_scopes': {scope: sum(f['subject_scope'] == scope for f in pool)
                for scope in sorted({f['subject_scope'] for f in pool})},
            'analyses': analyses, 'analysis_chars': sum(len(a['analysis']) for a in analyses),
            'unresolved_validation_rejections': diagnostic.get('unresolved_validation_rejections', []),
            'facts_with_literal_dates_but_unlabelled_event_time': [eid for eid in displayed
                if by_id[eid].get('event_date') == '未披露'
                and not (by_id[eid].get('observation', {}).get('period') or by_id[eid].get('observation', {}).get('source_events') or by_id[eid].get('observation', {}).get('role_date_fields'))
                and re.search(r'(?:19|20)\d{2}年', by_id[eid]['fact'])]})
    duplicates = [{'evidence_id': eid, 'body_chapters': uses,
                   'original_chars': len(by_id[eid]['fact'])}
                  for eid, uses in quote_uses.items() if len(uses) > 1]
    repeated_body_analyses = [{'analysis': statement, 'chapters': uses}
        for statement, uses in analysis_uses.items() if len([n for n in uses if 2 <= n <= 12]) > 1]
    return {'run': str(run), 'report_sha256': hashlib.sha256(report.encode()).hexdigest(),
        'chapter_count': len(sections), 'chapters': rows,
        'repeated_originals_across_body_chapters': duplicates,
        'repeated_original_character_excess': sum((len(r['body_chapters'])-1)*r['original_chars'] for r in duplicates),
        'repeated_analyses_across_body_chapters': repeated_body_analyses,
        'boundary': 'Flags identify review targets; counts do not measure independent accuracy or research completeness.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = inspect(args.run.resolve())
    output = args.output or args.run / 'quality-inspection.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(output), 'chapter_count': result['chapter_count'],
        'repeat_chars': result['repeated_original_character_excess'],
        'boundary_issues': [{'chapter': c['chapter'], 'analysis': a['analysis'], 'issues': a['explicit_source_boundary_issues']}
            for c in result['chapters'] for a in c['analyses'] if a['explicit_source_boundary_issues']]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
