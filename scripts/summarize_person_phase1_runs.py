"""Summarize retained request receipts without certifying report acceptance."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('runs', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for folder in sorted(args.runs.glob('round*')):
        summary_path = folder / 'summary.json'
        if not summary_path.is_file():
            summary_path = folder / 'review.json'
            if not summary_path.is_file():
                continue
        summary = json.loads(summary_path.read_text(encoding='utf-8'))
        review_run = summary_path.name == 'review.json'
        requests_path = folder / 'request-status.json'
        requests = json.loads(requests_path.read_text(encoding='utf-8')) if requests_path.exists() else []
        traces = folder / 'trace.jsonl'
        completed = []
        if traces.exists():
            completed = [row for line in traces.read_text(encoding='utf-8').splitlines()
                if (row := json.loads(line)).get('total_tokens') is not None]
        report = folder / 'desktop_report.md'
        parent = Path(summary.get('run') or folder).resolve()
        parent_summary = parent / 'summary.json'
        source_sha = summary.get('sources_sha256')
        if review_run and parent.is_relative_to(args.runs.resolve()) and parent_summary.exists():
            source_sha = json.loads(parent_summary.read_text(encoding='utf-8')).get('sources_sha256')
        events_path = folder / 'chapter-iteration-events.jsonl'
        events = [json.loads(line) for line in events_path.read_text(encoding='utf-8').splitlines()] if events_path.exists() else []
        rows.append({'run': folder.name, 'run_directory': str(folder.resolve()),
            'run_kind': 'independent_prose_review' if review_run else 'chapter_replay',
            'summary_sha256': hashlib.sha256(summary_path.read_bytes()).hexdigest(),
            'sources_sha256': source_sha,
            'generation_code_sha256': summary.get('generation_code_sha256'),
            'code_unchanged_during_run': summary.get('code_unchanged_during_run'),
            'model_context': summary.get('model_context'),
            'requests': len(requests) if requests_path.exists() else summary.get('model_requests'),
            'returned': sum(r.get('status') == 'returned' for r in requests) if requests_path.exists() else summary.get('model_requests_returned'),
            'failed': sum(r.get('status') == 'failed' for r in requests) if requests_path.exists() else summary.get('model_requests_failed'),
            'exact_input_reused': sum(e.get('status') == 'exact_input_reused' for e in events),
            'review_code_sha256': summary.get('review_code_sha256'),
            'review_batches_planned': summary.get('planned_model_requests') if review_run else None,
            'review_batches_returned': sum(b.get('status') == 'returned' for b in summary.get('batches', [])) if review_run else None,
            'elapsed_seconds': summary.get('elapsed_seconds'),
            'failure_types': sorted({r.get('exception_type') for r in requests if r.get('exception_type')}),
            'returned_usage_only': {name: sum(int(r.get(name) or 0) for r in completed)
                for name in ('input_tokens', 'output_tokens', 'reasoning_tokens', 'total_tokens')},
            'provider_actual_charge': None,
            'report_raw_sha256': hashlib.sha256(report.read_bytes()).hexdigest() if report.exists() else summary.get('report_sha256'),
            'degradations': summary.get('audit', {}).get('degradations', []),
            'report_accepted': False})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'runs': rows,
        'boundary': 'Returned usage omits failed requests without usage receipts. No billing estimate or report acceptance is inferred.'},
        ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'completed_run_receipts': len(rows), 'output': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
