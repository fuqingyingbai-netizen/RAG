"""Cold-start the actual app against an isolated DB, without a dense model."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_login_home_and_account_management_start_without_vector_model(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = {key: os.environ[key] for key in ['PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP'] if key in os.environ}
    env.update(PYTHONPATH=os.pathsep.join([str(root), str(root / 'backend')]),
               PYTHON_DOTENV_DISABLED='1', JWT_SECRET_KEY='isolated-startup-test-secret-only',
               DATABASE_URL='sqlite:///' + str(tmp_path / 'startup.sqlite'),
               REDIS_URL='redis://127.0.0.1:1/0', MILVUS_HOST='127.0.0.1', MILVUS_PORT='1',
               BM25_STATE_PATH=str(tmp_path / 'bm25.json'), RESEARCH_OBJECT_STORE='local',
               RESEARCH_LOCAL_STORE=str(tmp_path / 'reports'), COMPANY_KNOWLEDGE_ENABLED='false',
               COMPANY_KNOWLEDGE_LOCAL_STORE=str(tmp_path / 'knowledge'),
               LANGSMITH_TRACING='false', LANGCHAIN_TRACING_V2='false')
    code = '''
import ipaddress, socket, time, json
started = time.perf_counter()
lookup = socket.getaddrinfo
def offline_lookup(host, *args, **kwargs):
    if host is not None and str(host).lower() != 'localhost':
        try: allowed = ipaddress.ip_address(host).is_loopback
        except ValueError: allowed = False
        if not allowed: raise AssertionError('External request during isolated startup')
    return lookup(host, *args, **kwargs)
socket.getaddrinfo = offline_lookup
import embedding
def no_model(): raise AssertionError('Login tried to initialize the dense model')
embedding._create_dense_embedder = no_model
from backend.app import app
from fastapi.testclient import TestClient
from database import SessionLocal
from models import User
import auth
auth.PBKDF2_ROUNDS = 1000
with TestClient(app) as client:
    assert client.get('/').status_code == 200
    assert client.get('/auth/me').status_code == 401
    with SessionLocal() as db:
        db.add(User(username='startup-admin', role='admin', password_hash=auth.get_password_hash('Fixture123')))
        db.commit()
    login = client.post('/auth/login', json={'username': 'startup-admin', 'password': 'Fixture123'})
    assert login.status_code == 200, login.status_code
    headers = {'Authorization': 'Bearer ' + login.json()['access_token']}
    assert client.get('/research/home', headers=headers).status_code == 200
    assert client.get('/admin/users', headers=headers).status_code == 200
    assert embedding.embedding_service._embedder is None
print(json.dumps({'model_unloaded': True, 'login_home_accounts_ok': True, 'seconds': round(time.perf_counter()-started, 2)}))
'''
    result = subprocess.run([sys.executable, '-c', code], cwd=root, env=env, text=True,
                            encoding='utf-8', errors='replace', capture_output=True, timeout=90)
    assert result.returncode == 0, result.stderr
    state = json.loads(result.stdout.strip().splitlines()[-1])
    assert state['model_unloaded'] and state['login_home_accounts_ok']
