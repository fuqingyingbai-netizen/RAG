"""Freeze legacy company inputs into this checkout without writing legacy paths.

Run with the existing application Python environment. Never emits credentials.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'work/company-phase1-20261028'
DELIVERY = ROOT / 'deliverables/company-phase1-20261028'
LEGACY = Path('E:/projects/output/公司真实检索交付验收_20261024')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def prepare_environment():
    from dotenv import dotenv_values
    original = Path('E:/projects/RAG/.env')
    values = dotenv_values(original)
    overrides = {
        'DATABASE_URL': 'sqlite:///' + (RUN / 'runtime.sqlite').as_posix(),
        'RESEARCH_OBJECT_STORE': 'local',
        'RESEARCH_LOCAL_STORE': str(RUN / 'objects'),
        'COMPANY_KNOWLEDGE_OBJECT_STORE': 'local',
        'COMPANY_KNOWLEDGE_LOCAL_STORE': str(RUN / 'knowledge'),
        'BM25_STATE_PATH': str(RUN / 'bm25.json'),
        'REDIS_KEY_PREFIX': 'company-phase1-01a18168',
        'MILVUS_COLLECTION': 'company_phase1_01a18168',
        'DOCX_RENDER_QA_WORKDIR': str(RUN / 'render'),
        'RESEARCH_LEGACY_RAG_ENABLED': 'false',
        'REPORT_SECTION_MAX_WORKERS': '1',
        'COMPANY_EDITORIAL_WORKERS': '1',
        'COMPANY_CORPUS_REVIEW_WORKERS': '1',
        'COMPANY_CORPUS_WRITE_WORKERS': '1',
        'COMPANY_SOURCE_REVIEW_WORKERS': '1',
        'CLEANING_MAX_WORKERS': '1',
        'WEB_SEARCH_QUERY_CONCURRENCY': '2',
        'RESEARCH_OBJECT_PREFIX': 'company-phase1-01a18168',
    }
    # Preserve the actual current configuration; override only isolation/limits.
    text = original.read_text(encoding='utf-8-sig')
    for name, value in overrides.items():
        text += '\n' + name + '=' + json.dumps(value, ensure_ascii=False)
    destination = ROOT / '.env'
    if destination.exists():
        current = dotenv_values(destination)
        missing = {k: v for k, v in overrides.items() if k not in current}
        assert all(current.get(k, str(v)) == str(v) for k, v in overrides.items())
        assert current.get('MODEL') == values.get('MODEL')
        if missing:
            with destination.open('a', encoding='utf-8') as stream:
                for key, value in missing.items():
                    stream.write('\n' + key + '=' + json.dumps(value, ensure_ascii=False))
    else:
        destination.write_text(text + '\n', encoding='utf-8')
    assert subprocess.run(['git', 'check-ignore', '-q', '.env'], cwd=ROOT).returncode == 0
    return {'credentials_copied_not_linked': True,
            'current_model': values.get('MODEL'), 'isolation': overrides,
            'model_concurrency': 1, 'search_concurrency': 2,
            'external_accounts_and_host_resources_shared': True}


def freeze_case(case, proof):
    old = LEGACY / case / 'attempt-01'
    dest = RUN / 'baseline' / case
    dest.mkdir(parents=True, exist_ok=True)
    saved_manifest = dest / 'manifest.json'
    if saved_manifest.exists():
        saved = json.loads(saved_manifest.read_text(encoding='utf-8'))
        assert saved['source_count'] == proof['source_count']
        assert saved['database']['quick_check'] == 'ok'
        assert saved['historical_completed_receipts'] == len(proof['preserved_completed_model_receipts'])
        return {k: v for k, v in saved.items() if k != 'files'} | {
            'copied_files': len(saved['files']), 'reused_verified_manifest': True}
    old_db = Path(proof['database_backup'])
    new_db = dest / 'acceptance.sqlite'
    with sqlite3.connect(old_db.as_uri() + '?mode=ro', uri=True) as source:
        existing = new_db.exists()
        with sqlite3.connect(new_db) as target:
            if not existing:
                source.backup(target)
            assert target.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
            count = target.execute('SELECT COUNT(*) FROM research_sources').fetchone()[0]
            assert count == proof['source_count']
            tables = [r[0] for r in target.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    files = []
    # Retain the verified compressed checkpoint archive instead of duplicating
    # gigabytes of historical journal revisions. Source originals are copied;
    # archived journal entries remain available for selective native restore.
    checkpoint = proof['post_stop_checkpoint_archive']
    archive = Path(checkpoint['path'])
    archive_copy = dest / 'native-checkpoints.zip'
    if not archive_copy.exists():
        shutil.copyfile(archive, archive_copy)
    archive_digest = sha(archive)
    assert sha(archive_copy) == archive_digest
    # Legacy whole_sha256 denotes the uncompressed whole checkpoint, not ZIP.
    with zipfile.ZipFile(archive_copy) as z:
        native = z.read('whole-' + checkpoint['whole_sha256'] + '.json')
        assert hashlib.sha256(native).hexdigest() == checkpoint['whole_sha256']
    files.append({'path': archive_copy.name, 'bytes': archive_copy.stat().st_size,
                  'sha256': archive_digest,
                  'uncompressed_checkpoint_sha256': checkpoint['whole_sha256']})
    for folder in ('objects', 'model-receipts', 'artifacts'):
        for src in sorted((old / folder).rglob('*')):
            if folder == 'model-receipts' and src.name not in proof['preserved_completed_model_receipts']:
                continue
            if not src.is_file():
                continue
            relative = src.relative_to(old)
            if 'company_generation_checkpoint' in relative.parts:
                continue
            dst = dest / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            digest = sha(src)
            if not dst.exists() or sha(dst) != digest:
                shutil.copyfile(src, dst)
                assert sha(dst) == digest
            files.append({'path': relative.as_posix(), 'bytes': dst.stat().st_size, 'sha256': digest})
    expected = proof['preserved_completed_model_receipts']
    for name, digest in expected.items():
        assert sha(dest / 'model-receipts' / name) == digest
    result = {'case': case, 'source_count': count, 'as_of': '2026-10-24',
              'sample_kind': 'real_public_legacy_development', 'new_collection': False,
              'database': {'sha256': sha(new_db), 'quick_check': 'ok', 'tables': tables},
              'historical_completed_receipts': len(expected), 'files': files,
              'earlier_model_receipts_readonly_reference': str(old / 'model-receipts'),
              'receipt_copy_scope': 'all_completed_receipts_from_controlled_stop_manifest',
              'checkpoint_archive': checkpoint,
              'historical_journal_storage': 'verified_zip_selective_restore',
              'delivery_accepted': False, 'v1_receipts_are_not_v2_acceptance': True}
    write(dest / 'manifest.json', result)
    return {k: v for k, v in result.items() if k not in ('files',)} | {'copied_files': len(files)}


def main():
    RUN.mkdir(parents=True, exist_ok=True)
    env = prepare_environment()
    proof = json.loads((LEGACY / 'controlled-owned-native-stop-before-focus-fix-v148.json').read_text(encoding='utf-8-sig'))
    summary = {'at': datetime.now(timezone.utc).isoformat(), 'root': str(ROOT),
               'base_commit': '7cc0752c15a052bf606135a7a1e39553ccb23863',
               'shared_search_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
               'environment': env, 'cases': []}
    for case in ('haitian', 'kingsoft'):
        summary['cases'].append(freeze_case(case, proof['cases'][case]))
        write(DELIVERY / 'baseline-isolation.json', summary)
        print(json.dumps(summary['cases'][-1], ensure_ascii=False), flush=True)
    print('Baseline frozen; no network, model, service startup, or legacy mutation.', flush=True)


if __name__ == '__main__':
    main()
