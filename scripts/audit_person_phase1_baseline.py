"""Read/copy frozen person corpora and audit both sides without provider calls."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]
from person_evidence import build_packages, cited_ids, split_sections
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--old-workspace', required=True, type=Path)
    args = ap.parse_args()
    output = ROOT / 'deliverables/person-phase1-20261028'
    owned = ROOT / 'work/person-phase1-20261028/frozen'
    previous = ModuleType('person_evidence_baseline')
    source = subprocess.check_output(['git', 'show', 'b60ea11:backend/person_evidence.py'], cwd=ROOT)
    exec(compile(source, 'shared-baseline:person_evidence.py', 'exec'), previous.__dict__)
    results = []
    for alias in ['wang', 'zhang']:
        origin = args.old_workspace / 'work/person-coverage-20261023' / ('corpus-' + alias)
        dest = owned / alias
        dest.mkdir(parents=True, exist_ok=True)
        copies = []
        for path in origin.iterdir():
            if not path.is_file():
                continue
            target = dest / path.name
            if target.exists() and digest(target) != digest(path):
                raise ValueError('Frozen input would change: ' + str(target))
            if not target.exists():
                shutil.copyfile(path, target)
            copies.append({'origin': str(path), 'copy': str(target), 'sha256': digest(target)})
        read = lambda name: json.loads((dest / name).read_text(encoding='utf-8'))
        intake, payload = read('intake.json'), read('cleaned_facts.json')
        sources = [SimpleNamespace(**s) for s in read('source-snapshots.json')]
        attempts = read('summary.json').get('provider_attempts', [])
        kwargs = dict(target=intake['target_name'], outline=PERSON_REPORT_OUTLINE,
                      intake=intake, sources=sources, platform_attempts=attempts)
        before = previous.build_packages(payload, **kwargs)
        after = build_packages(payload, **kwargs)
        report = (dest / 'desktop_report.md').read_text(encoding='utf-8')
        sections = split_sections(report)
        citations = cited_ids(report)
        before_ids = {r['evidence_id'] for r in before['facts']}
        after_ids = {r['evidence_id'] for r in after['facts']}
        removed = [r for r in before['facts'] if r['evidence_id'] not in after_ids]
        record = {'alias': alias, 'target_name': intake['target_name'], 'sample_role': 'development',
                  'real_public_person': True, 'source_mode': 'frozen_historical_corpus',
                  'cutoff': intake.get('as_of_date'), 'source_snapshots': len(sources),
                  'source_sha256': digest(dest / 'source-snapshots.json'),
                  'raw_extracted_statements': len(payload.get('facts', [])),
                  'before_admitted': len(before['facts']), 'after_admitted': len(after['facts']),
                  'before_rejected': dict(Counter(r['rejection_reason'] for r in before['rejected'])),
                  'after_rejected': dict(Counter(r['rejection_reason'] for r in after['rejected'])),
                  'new_admitted_ids': sorted(after_ids - before_ids),
                  'removed_from_admission': [{'evidence_id': r['evidence_id'], 'source_url': r['source_url'],
                                             'statement': r['fact']} for r in removed],
                  'historical_report_chapters_present': sorted(sections),
                  'historical_report_unique_citations': len(citations),
                  'historical_citations_absent_from_current_contract': sorted(citations - after_ids),
                  'current_contract_routed_ids': len({r['evidence_id'] for p in after['chapters'].values()
                                                       for r in p.get('research_facts', p['facts'])}),
                  'report_rewritten': False, 'full_report_accepted': False,
                  'new_search_calls': 0, 'new_model_calls': 0,
                  'boundary': 'A source/fact/citation count is not substantive adoption or verification.'}
        save(output / alias / 'frozen-inputs.json', copies)
        save(output / alias / 'baseline-audit.json', record)
        save(owned / alias / 'current-contract.json', after)
        save(output / alias / 'provenance-index.json', after['provenance_index'])
        save(output / alias / 'risk-evidence-register.json', after['risk_evidence_register'])
        save(output / alias / 'form-requirements.json', after['form_requirements'])
        results.append(record)
        print(json.dumps({k:v for k,v in record.items() if k not in {
            'removed_from_admission', 'historical_citations_absent_from_current_contract', 'new_admitted_ids'}},
                         ensure_ascii=False), flush=True)
    save(output / 'baseline-comparison.json', results)


if __name__ == '__main__':
    main()
