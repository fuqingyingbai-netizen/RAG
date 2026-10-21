"""Summarize retained local replays without retrieval or model requests."""
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    runs = []
    for key, chapter, name in [('wang-ch9', 9, '王传福'), ('zhang-ch5', 5, '张勇（海底捞）')]:
        folder = root / 'work/person-complete-material' / key
        summary = json.loads((folder / 'summary.json').read_text(encoding='utf-8'))
        audit = json.loads((folder / 'audit.json').read_text(encoding='utf-8'))
        diagnostic = audit['section_diagnostics'][str(chapter)]
        review = diagnostic['material_review']
        inputs = review['input_evidence_ids']
        delivered = [eid for batch in review['batches'] for eid in batch['evidence_ids']]
        assert inputs == delivered, 'Missing, repeated or reordered batch inputs'
        assert not review['omitted_for_input_budget']
        assert all(b['status'] == 'returned' for b in review['batches'])
        assert len(summary['unchanged_body_chapters']) == 10
        comparison = next(c for c in summary['comparisons'] if c['chapter'] == chapter)
        runs.append({
            'name': name, 'chapter': chapter, 'sources_sha256': summary['sources_sha256'],
            'scope': summary['research_scope'][str(chapter)],
            'delivered_model_input_facts': len(inputs), 'batch_count': len(review['batches']),
            'input_evidence_ids': inputs, 'all_batch_inputs_accounted_for': True,
            'omitted_for_input_budget': [], 'before_chars': comparison['before_chars'],
            'after_chars': comparison['after_chars'], 'accepted_analysis_count': diagnostic['accepted_analysis_count'],
            'unresolved_validation_rejections': diagnostic['unresolved_validation_rejections'],
            'model_requests': summary['model_requests'],
            'model_requests_returned': summary['model_requests_returned'],
            'new_search_calls': summary['new_search_calls'], 'new_fetch_calls': summary['new_fetch_calls'],
            'new_professional_calls': summary['new_professional_calls'],
            'unchanged_body_chapters': summary['unchanged_body_chapters'],
            'local_run': str(folder), 'independently_verified': False,
        })
    result = {'date': '2026-10-21', 'scope': 'same-corpus partial chapter replay', 'runs': runs,
              'tests': {'passed': 260, 'junit': 'work/person-complete-material/tests.xml'},
              'boundary': 'Input delivery, automated checks and concise prose do not establish truth or full report acceptance.'}
    output = root / 'docs/PERSON_COMPLETE_MATERIAL_VALIDATION_20261021.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps([{k:r[k] for k in ['name','chapter','delivered_model_input_facts','batch_count',
        'before_chars','after_chars','unresolved_validation_rejections']} for r in runs], ensure_ascii=False))


if __name__ == '__main__':
    main()
