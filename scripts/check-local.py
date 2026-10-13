"""Read-only smoke checks for the restored local development environment."""
import argparse
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import redis
import requests
import urllib3
from dotenv import load_dotenv
from jose import jwt
from minio import Minio
from pymilvus import MilvusClient
from sqlalchemy import create_engine, text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8010)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / '.env')
    session = requests.Session()
    session.trust_env = False
    base_url = f'http://127.0.0.1:{args.port}'
    failures = []

    def check(label, operation):
        try:
            detail = operation()
            print(f'PASS {label}: {detail}')
        except Exception as exc:
            # Exception bodies can contain credentials or retrieved content.
            failures.append(label)
            print(f'FAIL {label}: {type(exc).__name__}')

    def http_status(path, expected=200):
        response = session.get(base_url + path, timeout=15)
        assert response.status_code == expected, response.status_code
        return response.status_code

    for path in ('/', '/docs', '/openapi.json'):
        check(path, lambda path=path: http_status(path))
    check('unauthenticated access', lambda: http_status('/auth/me', 401))

    engine = create_engine(os.environ['DATABASE_URL'], connect_args={'connect_timeout': 5})

    def database_check():
        with engine.connect() as connection:
            counts = {
                table: connection.execute(text(f'SELECT count(*) FROM {table}')).scalar()
                for table in ('research_projects', 'research_sources', 'research_artifacts')
            }
        return counts

    check('PostgreSQL', database_check)

    def authenticated_check():
        with engine.connect() as connection:
            user = connection.execute(text('SELECT id, username, role FROM users ORDER BY id LIMIT 1')).mappings().first()
            assert user is not None
            token = jwt.encode(
                {'sub': user['username'], 'role': user['role'], 'exp': datetime.now(timezone.utc) + timedelta(minutes=2)},
                os.environ['JWT_SECRET_KEY'], algorithm=os.getenv('JWT_ALGORITHM', 'HS256'),
            )
            headers = {'Authorization': f'Bearer {token}'}
            for path in ('/auth/me', '/research/projects'):
                response = session.get(base_url + path, headers=headers, timeout=15)
                assert response.status_code == 200
            query = 'SELECT a.id FROM research_artifacts a JOIN research_projects p ON p.id=a.project_id WHERE a.artifact_type=\'desktop_report\''
            parameters = {}
            if user['role'] != 'admin':
                query += ' AND p.created_by_id=:user_id'
                parameters['user_id'] = user['id']
            query += ' ORDER BY a.id DESC LIMIT 1'
            artifact_id = connection.execute(text(query), parameters).scalar()
        if artifact_id is not None:
            response = session.get(f'{base_url}/research/artifacts/{artifact_id}/download', headers=headers, timeout=30)
            assert response.status_code == 200 and response.content.startswith(b'PK')
            return 'user, projects and existing Word report download OK'
        return 'user and projects OK; no existing report to check'

    check('authenticated API', authenticated_check)

    def redis_check():
        client = redis.Redis.from_url(os.environ['REDIS_URL'], socket_connect_timeout=5, socket_timeout=5)
        try:
            assert client.ping()
            return 'PONG'
        finally:
            client.close()

    check('Redis', redis_check)

    def minio_check():
        client = Minio(
            os.getenv('MINIO_ENDPOINT', '127.0.0.1:9000'),
            access_key=os.getenv('MINIO_ACCESS_KEY', 'minioadmin'),
            secret_key=os.getenv('MINIO_SECRET_KEY', 'minioadmin'),
            secure=os.getenv('MINIO_SECURE', 'false').lower() == 'true',
            http_client=urllib3.PoolManager(timeout=urllib3.Timeout(connect=5, read=10), retries=1),
        )
        assert client.bucket_exists(os.getenv('MINIO_BUCKET', 'research'))
        return 'original research bucket accessible'

    check('MinIO', minio_check)

    def milvus_check():
        client = MilvusClient(uri=f'http://{os.getenv("MILVUS_HOST", "127.0.0.1")}:{os.getenv("MILVUS_PORT", "19530")}', timeout=15)
        try:
            collection = os.getenv('MILVUS_COLLECTION', 'embeddings_collection')
            assert client.has_collection(collection_name=collection)
            rows = client.query(collection_name=collection, filter='', output_fields=['chunk_id'], limit=1, timeout=15)
            return f'configured collection query OK; sample rows={len(rows)}'
        finally:
            client.close()

    check('Milvus', milvus_check)
    engine.dispose()
    session.close()
    print(f'{len(failures)} failed checks')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
