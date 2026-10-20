"""Merge retained real provider probes into an isolated corpus, without requests.

Probe outcomes retain their own timestamps. No result is invented for a query
that was skipped; the original full run remains unchanged.
"""
import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    parser.add_argument('--qcc-probe', type=Path, required=True)
    parser.add_argument('--platform-probe', type=Path, required=True)
    args = parser.parse_args()
    from person_platforms import response_state, documents
    from research_workflow import ResearchWorkflow
    original = args.baseline.resolve()
    out = ROOT / 'work/person-optimization' / ('supplemented-corpus-' + datetime.now().strftime('%Y%m%dT%H%M%S'))
    out.mkdir(parents=True)
    for name in ('intake.json', 'person_retrieval_audit.json'):
        shutil.copyfile(original / name, out / name)
    shutil.copytree(original / 'objects-before-cleanup', out / 'objects-before-cleanup')
    summary = json.loads((original / 'summary.json').read_text(encoding='utf-8'))
    sources = json.loads((original / 'source-snapshots.json').read_text(encoding='utf-8'))
    attempts = summary['provider_attempts']
    qcc = json.loads(args.qcc_probe.read_text(encoding='utf-8'))
    extra = json.loads(args.platform_probe.read_text(encoding='utf-8'))
    for probe in qcc:
        docs = probe['documents']
        if not docs:
            continue
        payload = {'result': {'content': [{'text': json.dumps(doc, ensure_ascii=False)} for doc in docs]}}
        company = docs[0].get('企业名称', '')
        if response_state(payload) == 'explicit_empty_record_list':
            attempts.append({'provider': 'qcc', 'subject': company, 'tool': probe['tool'],
                             'arguments': {'searchKey': company, 'personName': docs[0].get('人员名称')},
                             'status': 'empty_result', 'reason': 'explicit_empty_record_list',
                             'provenance': str(args.qcc_probe), 'retrieved_at': datetime.fromtimestamp(args.qcc_probe.stat().st_mtime).isoformat()})
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    for probe in extra:
        provider, tool, arguments = probe['provider'], probe['tool'], probe['arguments']
        payload = probe.get('payload') or {}
        company = arguments.get('searchKey') or arguments.get('firm_name', '')
        row = {'provider': provider, 'subject': company, 'tool': tool, 'arguments': arguments,
               'retrieved_at': probe['retrieved_at'], 'provenance': str(args.platform_probe)}
        if provider == 'qcc' and response_state(payload) == 'regional_restriction':
            attempts.append({**row, 'status': 'failed', 'reason': 'regional_restriction'})
        if provider != 'xiniu' or payload.get('error'):
            continue
        docs = documents(payload)
        if not any((doc.get('公司信息') or {}).get('公司名称') == company for doc in docs):
            raise ValueError('Xiniu returned company does not match retained query')
        identity = next((source['source_metadata'].get('target_person') for source in sources
                         if source['source_metadata'].get('person_subject_verified')
                         and source['source_metadata'].get('target') == company), '')
        if not identity:
            raise ValueError('No retained verified person anchor for the company context')
        content = workflow._extract_mcp_text(payload)
        sources.append({'id': max(r['id'] for r in sources) + 1, 'source_type': 'business_database',
                        'title': f'烯牛-{tool}-{company}-实测补充',
                        'url': f'structured://xiniu/supplement/{len(sources)+1}',
                        'content': content, 'summary': '关联企业融资背景；不能直接证明个人信用或能力',
                        'credibility_score': 80,
                        'source_metadata': {'provider': 'xiniu', 'tool': tool, 'module': '关联企业融资背景',
                                            'query': company, 'target': company, 'identity_confidence': 'medium',
                                            'retrieved_at': probe['retrieved_at'], 'content_kind': 'structured_data',
                                            'query_status': 'returned', 'person_chapters': [4, 6, 11],
                                            'person_affiliation': {'person_name': identity, 'affiliation_name': company,
                                                                   'canonical_company_name': company,
                                                                   'relationship_type': '已保留人物关联定位机构，平台返回公司名匹配'}}})
        label = tool + (':' + arguments['aspect'] if arguments.get('aspect') else '')
        attempts.append({**row, 'tool': label, 'status': 'collected', 'reason': 'source_statement_pending_review'})
    summary.update(scope='retained_full_corpus_plus_actual_provider_probes_no_new_requests',
                   original_full_run=str(original), new_requests_in_merge=0, source_count=len(sources))
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'source-snapshots.json').write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out)


if __name__ == '__main__':
    main()
