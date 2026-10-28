"""Retain nominated public originals through the production person fetch path."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--live', action='store_true')
    ap.add_argument('--reextract-archive', type=Path, help='Offline production-parser replay of hash-matched archived PDF bytes')
    args = ap.parse_args()
    if not args.live and not args.reextract_archive:
        ap.error('--live is required for real public-document requests')
    if args.live and args.reextract_archive:
        ap.error('Choose new retrieval or retained-byte extraction, not both')
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    import requests
    from research_workflow import ResearchWorkflow
    from research_store import research_store
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    intake = json.loads(Path(plan['intake']).read_text(encoding='utf-8'))
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / 'plan.json').write_bytes(args.plan.read_bytes())
    secret_values = [v for k, v in os.environ.items() if len(v) >= 12 and any(
        t in k.upper() for t in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD'))]

    def safe(value):
        text = json.dumps(value, ensure_ascii=False, default=str)
        for secret in sorted(secret_values, key=len, reverse=True):
            text = text.replace(secret, '[REDACTED]')
        return text

    def emit(event):
        with (out / 'trace.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(safe(event) + '\n')

    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    archived_receipts = []
    archived_sources = {}
    if args.reextract_archive:
        archived_receipts = json.loads((args.reextract_archive / 'receipts.json').read_text(encoding='utf-8'))
        archived_sources = {s['url']: s for s in json.loads((args.reextract_archive / 'source-snapshots.json').read_text(encoding='utf-8'))}
    sources, receipts = [], []
    for index, item in enumerate(plan['originals'], 1):
        began = time.monotonic()
        url = item['url']
        if not url.startswith('https://'):
            raise ValueError('Nominated public originals must use HTTPS')
        archived = None
        if args.reextract_archive:
            archived = next(r for r in archived_receipts if r['url'] == url)
            digest = archived['binary_sha256']
            if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('Invalid archived PDF hash')
            payload = (args.reextract_archive / (digest + '.pdf')).read_bytes()
            if hashlib.sha256(payload).hexdigest() != digest or not archived['binary_archive_matches_extraction']:
                raise ValueError('Archived PDF no longer matches the production receipt')
            from person_pdf import extract_person_pdf
            fetched = {'status': 'done', **extract_person_pdf(payload)}
            (out / (digest + '.pdf')).write_bytes(payload)
        else:
            fetched = workflow._fetch_web_url_with_timeout(url, allow_browser=False, emit=emit,
                                                           document_profile='person')
        content = str(fetched.get('content') or '')
        extraction = fetched.get('document_extraction') or {}
        receipt = {'url': url, 'fetch_status': fetched.get('status'),
            'production_fetches': 0 if archived else 1, 'archive_downloads': 0,
            'content_sha256': hashlib.sha256(content.encode('utf-8')).hexdigest(),
            'elapsed_seconds': round(time.monotonic() - began, 3),
            'document_extraction': extraction, 'binary_archive_matches_extraction': False}
        if content:
            receipt['text_object_key'] = research_store.put_text(
                'person-primary-originals/' + receipt['content_sha256'] + '.txt', content,
                'text/plain; charset=utf-8')
            # The production fetcher currently retains extraction metadata but
            # not PDF bytes. Archive a separate real response and require its
            # bytes to match the production extractor's source hash.
            try:
                if archived:
                    receipt.update(binary_file=digest + '.pdf', binary_sha256=digest,
                        binary_archive_matches_extraction=digest == extraction.get('source_sha256'),
                        retained_bytes_reextracted=True,
                        parent_receipts_sha256=hashlib.sha256((args.reextract_archive / 'receipts.json').read_bytes()).hexdigest())
                else:
                    receipt['archive_downloads'] = 1
                    response = requests.get(url, timeout=(5, 30))
                    response.raise_for_status()
                    digest = hashlib.sha256(response.content).hexdigest()
                    if not response.content.startswith(b'%PDF-'):
                        raise ValueError('Original response did not have a PDF signature')
                    (out / (digest + '.pdf')).write_bytes(response.content)
                    receipt.update(binary_file=digest + '.pdf', binary_sha256=digest,
                        binary_archive_matches_extraction=digest == extraction.get('source_sha256'))
            except Exception as exc:
                receipt['archive_error_type'] = type(exc).__name__
            identity = workflow._person_source_identity_confidence(item['title'], content, intake)
            sources.append({'id': index, 'url': url, 'title': item['title'], 'content': content,
                'source_type': 'web', 'source_metadata': {
                    'provider': 'retained_original_production_parser_replay' if archived else 'production_person_original_fetch',
                    'identity_status': 'candidate_requires_original_review',
                    'identity_confidence': identity['confidence'], 'identity_reason': identity['reason'],
                    'identity_assessment': identity,
                    'retrieved_at': (archived_sources[url]['source_metadata']['retrieved_at'] if archived else datetime.now(timezone.utc).isoformat()),
                    'extracted_at': datetime.now(timezone.utc).isoformat(),
                    'document_pages': fetched.get('document_pages') or [],
                    'document_extraction': extraction, 'binary_archive': receipt.get('binary_file'),
                    'binary_archive_matches_extraction': receipt['binary_archive_matches_extraction'],
                    'nominated_research_question': item['question'],
                    'source_statement_not_independently_verified': True}})
        receipts.append(receipt)
        (out / 'source-snapshots.json').write_text(safe(sources), encoding='utf-8')
        (out / 'receipts.json').write_text(safe(receipts), encoding='utf-8')
    summary = {'production_fetches': sum(r['production_fetches'] for r in receipts),
        'retained_byte_reextractions': sum(bool(r.get('retained_bytes_reextracted')) for r in receipts),
        'archive_downloads': sum(r['archive_downloads'] for r in receipts),
        'retained_sources': len(sources), 'matching_binary_archives': sum(r['binary_archive_matches_extraction'] for r in receipts),
        'model_calls': 0, 'historical_corpus_modified': False, 'report_accepted': False}
    (out / 'summary.json').write_text(safe(summary), encoding='utf-8')
    print(safe(summary))


if __name__ == '__main__':
    main()
