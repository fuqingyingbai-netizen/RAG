"""Run points tests against a disposable loopback-only PostgreSQL container, never configured data."""
from pathlib import Path
import json
import os
import secrets
import subprocess
import sys
import time
import uuid

import psycopg2
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]


def main():
    name = 'codex-points-check-' + uuid.uuid4().hex[:12]
    password = secrets.token_urlsafe(32)
    output = ROOT / 'work' / 'points-validation'
    output.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, 'POSTGRES_PASSWORD': password}
    container_id = None
    try:
        subprocess.run(['docker', 'image', 'inspect', 'postgres:15'], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=15, check=True)
        container_id = subprocess.check_output(['docker', 'run', '--rm', '-d', '--name', name,
            '--label', 'codex.points.validation=' + name, '-e', 'POSTGRES_PASSWORD', '-e', 'POSTGRES_DB=points_test',
            '--tmpfs', '/var/lib/postgresql/data:rw,size=512m',
            '-p', '127.0.0.1::5432', 'postgres:15'], env=environment, timeout=45, text=True).strip()
        address = subprocess.check_output(['docker', 'port', name, '5432/tcp'], timeout=10, text=True).strip()
        assert address.startswith('127.0.0.1:')
        port = int(address.rsplit(':', 1)[1])
        deadline = time.monotonic() + 45
        last_error = ''
        while True:
            try:
                connection = psycopg2.connect(host='127.0.0.1', port=port, user='postgres',
                    password=password, dbname='points_test', connect_timeout=2)
                connection.close()
                break
            except psycopg2.OperationalError as exc:
                last_error = str(exc).replace(password, '<redacted>')
                if time.monotonic() > deadline:
                    logs = subprocess.check_output(['docker', 'logs', name], stderr=subprocess.STDOUT, timeout=10, text=True)
                    (output / 'postgres-bootstrap.log').write_text(logs.replace(password, '<redacted>') + '\n' + last_error, encoding='utf-8')
                    raise RuntimeError('Owned PostgreSQL did not become ready') from None
                time.sleep(.5)
        database_url = URL.create('postgresql+psycopg2', username='postgres', password=password,
                                 host='127.0.0.1', port=port, database='points_test').render_as_string(hide_password=False)
        environment.update(POINTS_TEST_DATABASE_URL=database_url, POINTS_TEST_OWNED_CONTAINER=name,
                           PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
        with (output / 'postgres.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, '-m', 'pytest', 'test/test_company_points.py', '-q',
                '--disable-warnings', '--tb=short', '-o', 'faulthandler_timeout=60', '--junitxml=work/points-validation/postgres.xml'],
                cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                start_new_session=os.name != 'nt')
            try:
                result = process.wait(timeout=300)
            except subprocess.TimeoutExpired:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
                else:
                    import signal
                    os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=20)
                raise RuntimeError('Owned PostgreSQL test run exceeded five minutes; child processes stopped') from None
        print(json.dumps({'database': 'disposable PostgreSQL 15', 'host': 'loopback only', 'exit_code': result}))
        print('\n'.join((output / 'postgres.log').read_text(encoding='utf-8').splitlines()[-12:]))
        return result
    finally:
        if container_id:
            inspection = json.loads(subprocess.check_output(['docker', 'inspect', name], timeout=10, text=True))[0]
            assert inspection['Id'] == container_id and inspection['Config']['Labels'].get('codex.points.validation') == name
            subprocess.run(['docker', 'stop', '--time', '10', name], timeout=25, check=True, stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    raise SystemExit(main())
