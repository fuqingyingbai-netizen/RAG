"""Audit a frozen native company run. No model, search, or acceptance mutation.

Reports record-level placements separately from literal report observations.
An evidence ID appearing in prose never proves that all its facts survived.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'work/company-phase1-20261028'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def compact(value):
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items()}
    if isinstance(value, list):
        return {'count': len(value), 'examples': value[:3]}
    return value


def audit(case):
    directory = RUN / 'baseline' / case
    output = RUN / 'baseline-audit' / case
    output.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect((directory / 'acceptance.sqlite').as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        project = dict(db.execute('SELECT * FROM research_projects').fetchone())
        sources = [dict(row) for row in db.execute('SELECT * FROM research_sources ORDER BY id')]
        for source in sources:
            source['source_metadata'] = json.loads(source['source_metadata'] or '{}')
        artifacts = {}
        for row in db.execute('SELECT * FROM research_artifacts ORDER BY version,id'):
            artifacts[row['artifact_type']] = dict(row)
    with zipfile.ZipFile(directory / 'native-checkpoints.zip') as z:
        whole = next(name for name in z.namelist() if name.startswith('whole-'))
        raw = z.read(whole)
        assert hashlib.sha256(raw).hexdigest() == whole[6:-5]
        checkpoint = json.loads(raw)
        journals = {stage: [json.loads(z.read(name)) for name in z.namelist()
                            if name.startswith(stage + '/') and name.endswith('.json')]
                    for stage in ('main-focus', 'editorial', 'presentation')}
    packages = checkpoint['packages']
    usage = packages.get('company_information_usage_cache') or {}
    native_review = (packages.get('company_corpus_analysis_cache') or {}).get('source_review') or {}
    records = usage.get('records') or []
    source_map = {str(row['source_id']): row for row in usage.get('source_map', {}).get('source_records', [])}
    report = artifacts.get('desktop_report', {}).get('content', '')
    (output / 'historical-main-report.md').write_text(report, encoding='utf-8')
    chapters = [(int(match[1]), match[0]) for match in re.finditer(r'(?ms)^##\s+(\d+)[.．、].*?(?=^##\s+\d+[.．、]|\Z)', report)]
    evidence_observations = {n: set(re.findall(r'E-[A-Z0-9-]{6,}', text)) for n, text in chapters}
    by_url = defaultdict(list)
    for row in records:
        for provenance in row.get('provenance', []):
            by_url[provenance.get('source_url', '')].append(row['information_id'])
    seen = {}
    inventory = []
    for source in sources:
        content = source.get('content') or ''
        content_sha = hashlib.sha256(content.encode()).hexdigest()
        metadata = source['source_metadata']
        # Empty bodies cannot become one spurious duplicate document group.
        dedup_key = content_sha if content.strip() else digest({'empty_source': source['id']})
        duplicate = seen.get(dedup_key)
        seen.setdefault(dedup_key, source['id'])
        native = source_map.get(str(source['id']), {})
        ids = sorted(set(native.get('information_ids') or by_url.get(source['url'], [])))
        inventory.append({'source_id': source['id'], 'document_id': 'DOC-' + dedup_key[:24],
            'source_revision': digest(source), 'content_sha256': content_sha,
            'title': source['title'], 'url': source['url'], 'object_key': source['object_key'],
            'chars': len(content), 'duplicate_of': duplicate,
            'source_type': source['source_type'], 'provider': metadata.get('platform') or metadata.get('provider'),
            'fetch_status': metadata.get('fetch_status'), 'original_available': bool(content.strip()),
            'information_ids': ids, 'native_source_disposition': native,
            'native_review': native_review.get(str(source['id']), {}),
            'audit_state': 'linked_native_information' if ids else 'requires_source_disposition_review',
            'whole_source_semantic_coverage_proven': False})
    information = []
    for row in records:
        literal = row.get('text', '')
        observations = [n for n, text in chapters if literal and literal in text]
        evidence_chapters = [n for n, ids in evidence_observations.items() if ids.intersection(row.get('evidence_ids', []))]
        information.append({**row, 'content_revision': digest(row),
            'historical_literal_report_chapters': observations,
            'historical_evidence_id_report_chapters': evidence_chapters,
            'semantic_adoption_proven': False,
            'audit_reason': 'literal_and_reference_observations_require_scope_and_proposition_review'})
    gap_types = {
        'qualified_evidence_not_adopted': '已有证据但未在所需正文中完成采用/独立核对',
        'summary_requires_original': '仅摘要或平台计数，需要原件',
        'conflicting_or_ambiguous_scope': '原件冲突或主体/时期不明',
        'platform_failure': '专业平台调用失败，不属于公司风险',
        'public_information_not_found': '有明确检索记录，尚未找到公开资料',
        'model_or_transport_failure': '模型或网络调用失败，不属于资料不存在',
        'unclassified_pending_review': '待逐条核对，不依据空值自动归因',
    }
    gaps = [{'gap_id': 'G-' + digest({'case': case, 'source_id': s['source_id']})[:24],
             'type': 'unclassified_pending_review', 'source_id': s['source_id'],
             'document_id': s['document_id'], 'reason': 'No native information/disposition mapping observed.',
             'next_action': '核对原文窗口、主体、原件状态及既有拒绝理由'}
            for s in inventory if not s['information_ids']]
    summary = {'case': case, 'target_name': project['target_name'], 'as_of': '2026-10-24',
        'sample': 'real_public_legacy_development', 'source_count': len(sources),
        'exact_nonempty_content_groups_and_empty_records': len(seen),
        'exact_content_duplicate_records': sum(s['duplicate_of'] is not None for s in inventory),
        'sources_with_native_mapping': sum(bool(s['information_ids']) for s in inventory),
        'source_review_states': dict(Counter(s['native_review'].get('state', 'missing') for s in inventory)),
        'source_disposition_review_pending': len(gaps),
        'native_information_records': len(records), 'usage_diagnostic': compact(usage.get('diagnostic', {})),
        'journal_entries': {key: len(value) for key, value in journals.items()},
        'main_focus_journal_versions': dict(Counter(str(row.get('version', 'unknown')) for row in journals['main-focus'])),
        'checkpoint_package_versions': {key: value.get('version') for key, value in packages.items()},
        'historical_report_sha256': hashlib.sha256(report.encode()).hexdigest(),
        'historical_report_chapters_observed': [n for n, text in chapters],
        'literal_match_information_records': sum(bool(row['historical_literal_report_chapters']) for row in information),
        'semantic_adoption_rate': None, 'semantic_adoption_rate_reason': '尚未对同一最终正文逐命题独立审阅，引用出现率不替代采用率',
        'delivery_accepted': False, 'new_model_calls': 0, 'new_search_calls': 0,
        'gap_taxonomy': gap_types,
        'baseline_only': True, 'v1_journals_are_not_v2_acceptance': True}
    write(output / 'source-inventory.json', inventory)
    write(output / 'information-dispositions.json', information)
    write(output / 'gap-ledger.json', gaps)
    write(output / 'summary.json', summary)
    write(output / 'native-packages.json', packages)
    write(ROOT / 'deliverables/company-phase1-20261028' / f'{case}-baseline-summary.json', summary)
    print(json.dumps({k: summary[k] for k in ['case', 'source_count', 'exact_content_duplicate_records',
        'sources_with_native_mapping', 'source_disposition_review_pending', 'native_information_records',
        'journal_entries', 'delivery_accepted']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cases', nargs='+', choices=['haitian', 'kingsoft'])
    args = parser.parse_args()
    for case in args.cases:
        audit(case)
