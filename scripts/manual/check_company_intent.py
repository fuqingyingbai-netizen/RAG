"""Synthetic routing acceptance; no business corpus, retrieval, or production DB.

Uses the existing COMPANY_KNOWLEDGE_MODEL/BASE_URL/API_KEY configuration.
Only these three variables are read from an optional --env-file.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--interval', type=float, default=2)
    args = parser.parse_args()
    if args.env_file:
        from dotenv import dotenv_values
        values = dotenv_values(args.env_file)
        for suffix in ('MODEL', 'BASE_URL', 'API_KEY'):
            key = 'COMPANY_KNOWLEDGE_' + suffix
            if values.get(key):
                os.environ[key] = values[key]
    if not all(os.getenv('COMPANY_KNOWLEDGE_' + key) for key in ('MODEL', 'BASE_URL', 'API_KEY')):
        parser.error('Load COMPANY_KNOWLEDGE_MODEL/BASE_URL/API_KEY before running.')
    os.environ.update(PYTHON_DOTENV_DISABLED='1', DATABASE_URL='sqlite://',
                      JWT_SECRET_KEY='synthetic-intent-evaluation-only', LANGSMITH_TRACING='false')
    corpus = ROOT / 'test/fixtures/knowledge_intent_cases.json'
    source_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
        'backend/company_intent.py', 'backend/company_memory.py', 'backend/company_knowledge.py')}
    cases = json.loads(corpus.read_text(encoding='utf-8'))
    rows = []
    with TemporaryDirectory(prefix='knowledge-intent-') as temporary:
        os.environ.update(COMPANY_KNOWLEDGE_LOCAL_STORE=temporary + '/originals',
                          COMPANY_KNOWLEDGE_LOG_DIR=temporary + '/logs')
        import company_knowledge as kb
        import company_memory as memory
        import company_observability as obs
        from company_chat_task import fresh
        original = memory.complete
        last_call = 0.0

        async def paced(*a, **kw):
            nonlocal last_call
            await asyncio.sleep(max(0, args.interval - (time.monotonic() - last_call)))
            last_call = time.monotonic()
            return await original(*a, **kw)
        memory.complete = paced

        def save():
            business = [row for row in rows if row['expected'] in {'knowledge', 'transform'}]
            durations = sorted(row['seconds'] for row in rows)
            git = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
            result = {'source_commit': git.stdout.strip() if git.returncode == 0 else None, 'source_sha256': source_hashes,
                      'model': os.environ['COMPANY_KNOWLEDGE_MODEL'],
                      'endpoint': os.environ['COMPANY_KNOWLEDGE_BASE_URL'],
                      'dataset_sha256': hashlib.sha256(corpus.read_bytes()).hexdigest(),
                      'scope': 'synthetic intent routing only; no corpus retrieval or answer-quality evaluation',
                      'total': len(rows), 'planned': len(cases),
                      'passed': sum(row['passed'] for row in rows),
                      'accuracy': sum(row['passed'] for row in rows) / len(rows),
                      'business_recall': sum(row['actual'] in {'knowledge', 'transform'} and bool(row.get('query')) for row in business) / len(business) if business else None,
                      'model_http_statuses': {}, 'model_errors': sum(bool(row.get('error')) or bool(row['trace'].get('intent_error_type')) for row in rows),
                      'p95_seconds': durations[max(0, int(len(durations) * .95 + .999) - 1)],
                      'median_seconds': statistics.median(durations), 'cases': rows}
            for row in rows:
                for status, count in row['trace'].get('upstream_statuses', {}).items():
                    result['model_http_statuses'][status] = result['model_http_statuses'].get(status, 0) + count
            result['acceptance_passed'] = len(rows) == len(cases) and result['accuracy'] >= .95 and result['business_recall'] >= .98 and result['model_errors'] == 0
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

        async def run():
            for case in cases:
                trace = obs.Trace()
                token = obs._current.set(trace)
                ctx = {'summary': '', 'recent': [], 'task': fresh(case['task']) if case.get('task') else {}}
                if case.get('task'):
                    ctx['recent'] = [{'role': 'user', 'content': case['task']},
                                     {'role': 'assistant', 'content': '需依据资料核对。'}]
                started = time.perf_counter()
                row = {**case}
                try:
                    route = await memory.route_question({}, case['question'], ctx)
                    row.update(actual=route['intent'], query=route['query'], passed=route['intent'] == case['expected'])
                except Exception as error:
                    row.update(actual='error', passed=False, error=type(error).__name__)
                finally:
                    obs._current.reset(token)
                row.update(seconds=round(time.perf_counter() - started, 4), trace=trace.stats)
                rows.append(row)
                save()
                print(json.dumps({key: row[key] for key in ('id', 'expected', 'actual', 'passed', 'seconds')}), flush=True)
        asyncio.run(run())


if __name__ == '__main__':
    main()
