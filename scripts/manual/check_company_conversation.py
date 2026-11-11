"""Real official model, controlled synthetic retrieval, disposable local conversations.

Supply COMPANY_KNOWLEDGE_MODEL/BASE_URL/API_KEY through the environment. This
checks conversation routing and grounded generation, not production retrieval recall.
"""
import argparse
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'test')]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--interval', type=float, default=15)
    parser.add_argument('--attempts', type=int, choices=(1, 2, 3), default=1)
    args = parser.parse_args()
    provider = {key: os.environ['COMPANY_KNOWLEDGE_' + key] for key in ('MODEL', 'BASE_URL', 'API_KEY')}
    if provider['BASE_URL'].rstrip('/') != 'https://open.bigmodel.cn/api/paas/v4':
        raise ValueError('This acceptance sends synthetic cases only to the official Zhipu endpoint.')
    os.environ.update(PYTHON_DOTENV_DISABLED='1', DATABASE_URL='sqlite://', JWT_SECRET_KEY='disposable-evaluation-only')
    import pytest
    import httpx
    import company_knowledge as kb
    import company_workspace as ws
    from company_catalog import CompanyDocument
    from test_company_memory import env, create, call

    rows, requests, retrievals = [], [], []
    last_call = 0.0
    original = httpx.AsyncClient

    async def pace():
        nonlocal last_call
        import asyncio
        await asyncio.sleep(max(0, args.interval - (time.monotonic() - last_call)))
        last_call = time.monotonic()

    class PacedClient(original):
        async def post(self, url, **kwargs):
            await pace()
            started = time.monotonic()
            response = await super().post(url, **kwargs)
            requests.append({'kind': 'rewrite', 'status': response.status_code, 'seconds': round(time.monotonic() - started, 3)})
            return response

        @asynccontextmanager
        async def stream(self, method, url, **kwargs):
            await pace()
            started = time.monotonic()
            record = {'kind': 'answer'}
            requests.append(record)
            try:
                async with super().stream(method, url, **kwargs) as response:
                    record['status'] = response.status_code
                    yield response
            finally:
                record['seconds'] = round(time.monotonic() - started, 3)

    facts = [
        ('doc-a', 'cloud-a', '甲公司', '2025年营业收入为1200万元，客户数量为87家；标准版价格为39元/月。未披露净利润。'),
        ('doc-b', 'cloud-b', '乙公司', '2025年营业收入为2600万元，客户数量为143家；标准版价格为69元/月。未披露净利润。'),
        ('doc-c', 'cloud-c', '丙公司', '2025年营业收入为5100万元，客户数量为218家；标准版价格为99元/月。未披露净利润。'),
    ]
    cases = [
        ('请列出甲公司2025年的营业收入与客户数量，每项注明来源。', '甲公司', ['1200', '87'], ['2600', '143', '5100', '218']),
        ('客户数呢？', '甲公司', ['87'], ['143', '218']),
        ('整理成表格', '甲公司', ['87', '|'], ['143', '218']),
        ('那乙公司呢？', '乙公司', ['143'], ['87', '218']),
        ('它怎么收费？', '乙公司', ['69'], ['39', '99']),
        ('请比较甲公司和乙公司的收费方式。', '甲公司、乙公司', ['39', '69'], ['99']),
        ('它的客户数量是多少？', 'clarify', [], []),
        ('我指的是乙公司', '乙公司', ['143'], ['87', '218']),
        ('客户数呢？', '乙公司', ['143'], ['87', '218']),
        ('请介绍丙公司2025年的营业收入。', '丙公司', ['5100'], ['1200', '2600']),
        ('它怎么收费？', '丙公司', ['99'], ['39', '69']),
        ('丙公司2025年的净利润是多少？不要推算。', 'refuse', [], []),
    ]
    query_terms = ['收入', '客户', '客户', '客户', '收费|价格|定价|费用|计费', '收费|价格|定价|费用|计费',
                   '', '客户', '客户', '收入', '收费|价格|定价|费用|计费', '净利润']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        args.output.write_text(json.dumps({'model': provider['MODEL'], 'endpoint': provider['BASE_URL'],
            'retrieval': 'controlled synthetic; all three documents returned on every retrieval',
            'interval_seconds': args.interval, 'maximum_attempts': args.attempts,
            'retries': sum(len(row['attempts']) - 1 for row in rows), 'cases': rows, 'requests': requests,
            'passed': sum(row['passed'] for row in rows), 'total': len(rows), 'planned': len(cases)}, ensure_ascii=False, indent=2), encoding='utf-8')
    with TemporaryDirectory(prefix='conversation-official-') as temp:
        patch = pytest.MonkeyPatch()
        fixture = env.__wrapped__(patch, Path(temp))
        state = next(fixture)
        try:
            for key, value in provider.items():
                patch.setenv('COMPANY_KNOWLEDGE_' + key, value)
            with state.db() as db:
                for doc_id, cloud_id, subject, _ in facts:
                    doc = db.get(CompanyDocument, doc_id)
                    if doc is None:
                        doc = CompanyDocument(id=doc_id, index_id='memory-index', cloud_id=cloud_id,
                            format='TXT', owner='bob', owner_user_id=2, visibility='members', state='ready')
                        db.add(doc)
                    doc.title = subject + '2025年测试资料'
                    doc.project = ''
                    doc.industry = ''
                db.commit()
            async def retrieve(client, cfg, path, payload):
                assert path.endswith('/retrieve')
                retrievals.append(payload['query'])
                return {'nodes': [{'metadata': {'doc_id': cloud, 'doc_name': name + '测试资料', 'content': name + '：' + content}}
                    for _, cloud, name, content in facts]}
            patch.setattr(kb, 'cloud_rpc', retrieve)
            patch.setattr(kb.httpx, 'AsyncClient', PacedClient)
            sid = create(state, [doc[0] for doc in facts])
            consecutive_errors = 0
            for number, (question, subject, required, forbidden) in enumerate(cases, 1):
                start, before, previous_retrieval = time.monotonic(), len(requests), len(retrievals)
                attempts = []
                for attempt in range(1, args.attempts + 1):
                    response = call(state, sid, question, f'official-{number}-{attempt}', document_ids=[doc[0] for doc in facts])
                    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
                    errors = [event for event in events if event['type'] == 'error']
                    attempts.append({'number': attempt, 'errors': errors, 'events': events})
                    if not errors:
                        break
                answer = ''.join(event.get('text', '') for event in events if event['type'] == 'answer_delta')
                errors = [event for event in events if event['type'] == 'error']
                refs = next((event['citations'] for event in events if event['type'] == 'citations'), [])
                cited = set(re.findall(r'\[id_(\d+)\]', answer))
                cited_names = [ref['title'] for index, ref in enumerate(refs, 1) if str(index) in cited]
                if subject == 'clarify':
                    correct = '请补充公司' in answer and len(retrievals) == previous_retrieval
                elif subject == 'refuse':
                    correct = bool(re.search(r'未披露|未找到|没有.*(?:依据|披露)|无法.*(?:确定|提供)', answer)) and not re.search(r'净利润.{0,10}\d', answer)
                else:
                    correct = (all(value in answer for value in required) and not any(value in answer for value in forbidden)
                        and all(any(name in title for title in cited_names) for name in subject.split('、')))
                    query = retrievals[-1] if len(retrievals) > previous_retrieval else ''
                    correct = correct and bool(re.search(query_terms[number - 1], query)) and all(name in query for name in subject.split('、'))
                row = {'turn': number, 'question': question, 'expected_subject': subject, 'answer': answer,
                    'attempts': attempts,
                    'errors': errors, 'passed': bool(correct and not errors and any(event['type'] == 'saved' for event in events)),
                    'retrieval_query': retrievals[-1] if len(retrievals) > previous_retrieval else None,
                    'cited_documents': cited_names, 'requests': requests[before:], 'seconds': round(time.monotonic() - start, 3)}
                rows.append(row); save()
                print(json.dumps({key: row[key] for key in ('turn', 'passed', 'seconds', 'errors')}, ensure_ascii=False), flush=True)
                consecutive_errors = consecutive_errors + 1 if errors else 0
                if consecutive_errors >= 3:
                    print('Stopped after three consecutive provider errors; remaining cases are untested.', flush=True)
                    break
        finally:
            fixture.close()
            state.db.kw['bind'].dispose()
            patch.undo()
    save()


if __name__ == '__main__':
    main()
