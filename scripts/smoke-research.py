"""Log in and exercise a real company workflow, preserving its results and trace."""
import argparse
import getpass
import io
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path

import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8010')
    parser.add_argument('--username', default='admin')
    parser.add_argument('--company', default='比亚迪股份有限公司')
    parser.add_argument('--project-id', type=int, help='Resume an existing smoke project')
    args = parser.parse_args()
    password = os.getenv('BOOTSTRAP_ADMIN_PASSWORD') or getpass.getpass('Admin password: ')
    output = Path(__file__).resolve().parents[1] / 'work' / 'smoke-research' / datetime.now().strftime('%Y%m%d-%H%M%S')
    output.mkdir(parents=True)
    client = requests.Session()
    client.trust_env = False

    def api(method, path, **kwargs):
        response = client.request(method, args.base_url + path, timeout=60, **kwargs)
        response.raise_for_status()
        return response

    assert client.get(args.base_url + '/auth/me', timeout=15).status_code == 401
    login = api('POST', '/auth/login', json={'username': args.username, 'password': password}).json()
    client.headers['Authorization'] = 'Bearer ' + login['access_token']
    assert api('GET', '/auth/me').json()['role'] == 'admin'
    print('PASS real administrator login and /auth/me', flush=True)
    api('GET', '/documents')
    api('GET', '/research/projects')
    if args.project_id:
        project = api('GET', f'/research/projects/{args.project_id}').json()
    else:
        project = api('POST', '/research/projects', json={
            'title': f'本地端到端验证-{args.company}-{datetime.now():%Y%m%d%H%M}',
            'target_name': args.company, 'target_type': 'company', 'industry': '新能源汽车',
            'description': '验证真实公司研究流程，关注公司背景、主营业务与公开风险证据。',
        }).json()
    project_id = project['id']
    (output / 'project.json').write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Project #{project_id}; trace: {output}', flush=True)
    errors = []
    warnings = []
    with client.post(args.base_url + f'/research/projects/{project_id}/run/stream', json={
        'company_name': args.company, 'target_type': 'company',
        'search_queries': [f'{args.company} 主营业务 年报'],
        'focus_questions': ['公司主营业务与公开风险证据有哪些？'],
        'focus_modules': ['公司背景', '主营业务', '企业司法负面核查'],
        'as_of_date': datetime.now().strftime('%Y-%m-%d'),
    }, stream=True, timeout=(30, 900)) as response:
        response.raise_for_status()
        with (output / 'events.jsonl').open('w', encoding='utf-8') as log:
            for line in response.iter_lines():
                if not line.startswith(b'data: '):
                    continue
                event = json.loads(line[6:])
                log.write(json.dumps(event, ensure_ascii=False) + '\n')
                log.flush()
                if event.get('type') == 'trace_step':
                    if event.get('stage') != 'web_search' or event.get('status') in {'error', 'warning', 'fallback', 'paused'}:
                        print(event.get('stage'), event.get('status'), event.get('label'), flush=True)
                    if event.get('status') in {'fallback', 'failed', 'error', 'warning'}:
                        warnings.append(event)
                elif event.get('type') == 'error':
                    errors.append(event)
                    print('WORKFLOW ERROR (see saved events)', flush=True)
                elif event.get('type') == 'done':
                    break
    detail = api('GET', f'/research/projects/{project_id}/detail').json()
    (output / 'detail.json').write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding='utf-8')
    downloads = []
    latest = {}
    for artifact in detail['artifacts']:
        if artifact['artifact_type'] not in {'desktop_report', 'proposal'}:
            continue
        previous = latest.get(artifact['artifact_type'])
        if previous is None or (artifact['version'], artifact['id']) > (previous['version'], previous['id']):
            latest[artifact['artifact_type']] = artifact
    for artifact in latest.values():
        response = api('GET', f"/research/artifacts/{artifact['id']}/download")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert 'word/document.xml' in archive.namelist()
            assert archive.testzip() is None
        path = output / f"{artifact['artifact_type']}-{artifact['id']}.docx"
        path.write_bytes(response.content)
        downloads.append(str(path))
        print(f'PASS Word download: {path.name}', flush=True)
    quality_warnings = [
        {'artifact_id': artifact['id'], 'warning': artifact['metadata'].get('quality_warning') or 'Review draft'}
        for artifact in latest.values()
        if artifact['metadata'].get('quality_warning') or artifact['metadata'].get('delivery_status') == 'review_draft'
    ]
    workflow_passed = detail['project']['status'] == 'completed' and len(downloads) == 2 and not errors
    delivery_passed = workflow_passed and not quality_warnings
    passed = workflow_passed and delivery_passed
    result = {'passed': passed, 'workflow_passed': workflow_passed, 'delivery_passed': delivery_passed,
              'quality_warnings': quality_warnings, 'project_id': project_id, 'status': detail['project']['status'],
              'source_count': detail['source_count'], 'artifact_count': detail['artifact_count'],
              'errors': errors, 'warnings': warnings, 'downloads': downloads}
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"{'PASS' if workflow_passed else 'FAIL'} workflow: {result['status']}; sources={result['source_count']}; artifacts={result['artifact_count']}", flush=True)
    if quality_warnings:
        print('FAIL delivery quality: review draft; see result.json and quality diagnostics', flush=True)
    client.close()
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
