"""Release-boundary tests use disposable Git repositories and synthetic credentials only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load_script('build-release')
config = load_script('check-production-config')


def git(repo, *args, input=None):
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_AUTHOR_NAME='Release Test', GIT_AUTHOR_EMAIL='release-test@invalid.test',
               GIT_COMMITTER_NAME='Release Test', GIT_COMMITTER_EMAIL='release-test@invalid.test')
    result = subprocess.run(['git', '-C', str(repo), '-c', 'commit.gpgsign=false',
                             '-c', f'core.hooksPath={repo / "empty-hooks"}', *args],
                            input=input, capture_output=True, env=env, check=True)
    return result.stdout.decode().strip()


@pytest.fixture
def source_repo(tmp_path):
    repo = tmp_path / 'source'
    repo.mkdir()
    git(repo, 'init')
    files = {
        '.gitattributes': '* text=auto eol=lf\n',
        'backend/app.py': 'print("committed application")\n',
        'frontend/index.html': '<html>committed frontend</html>\n',
        'frontend/vendor/LICENSE.txt': 'synthetic license\n',
        'pyproject.toml': '[project]\nname="test-release"\n',
        'scripts/check-production-config.py': (ROOT / 'scripts/check-production-config.py').read_text(encoding='utf-8'),
        'deploy/supermew.service': (ROOT / 'deploy/supermew.service').read_text(encoding='utf-8'),
        'deploy/app.env.example': (ROOT / 'deploy/app.env.example').read_text(encoding='utf-8'),
        'uv.lock': 'version = 1\n', 'README.md': 'Synthetic test application\n',
        '.env': 'SENSITIVE_FILE=must-not-be-exported\n',
        'work/private-report.docx': 'private report',
        'data/uploads/private.json': '{"private":true}',
        'deliverables/private.docx': 'private template',
    }
    for name, value in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'Synthetic release fixture')
    return repo


def members(path):
    with tarfile.open(path, 'r:gz') as archive:
        return {item.name: archive.extractfile(item).read() for item in archive if item.isfile()}


def test_committed_source_only_and_private_files_excluded(source_repo, tmp_path):
    (source_repo / 'backend/app.py').write_text('uncommitted change', encoding='utf-8')
    (source_repo / 'backend/untracked.py').write_text('untracked change', encoding='utf-8')
    package, manifest = release.build_release(source_repo, 'HEAD', tmp_path / 'out')
    files = members(package)
    assert files['backend/app.py'] == b'print("committed application")\n'
    assert 'backend/untracked.py' not in files
    assert not any(name.startswith(('.env', 'work/', 'data/', 'deliverables/')) for name in files)
    assert manifest['commit'] == git(source_repo, 'rev-parse', 'HEAD')
    assert json.loads(files['release-manifest.json']) == manifest
    for item in manifest['files']:
        assert item['sha256'] == hashlib.sha256(files[item['path']]).hexdigest()


def test_identical_commit_produces_identical_package(source_repo, tmp_path):
    first, _ = release.build_release(source_repo, 'HEAD', tmp_path / 'first')
    second, _ = release.build_release(source_repo, 'HEAD', tmp_path / 'second')
    assert first.read_bytes() == second.read_bytes()
    assert first.with_suffix('.gz.sha256').read_text().split()[0] == hashlib.sha256(first.read_bytes()).hexdigest()
    with pytest.raises(release.ReleaseError, match='already exists'):
        release.build_release(source_repo, 'HEAD', tmp_path / 'first')


def test_local_export_attributes_cannot_change_committed_files(source_repo, tmp_path):
    attributes = source_repo / '.git/info/attributes'
    attributes.write_text('backend/app.py export-ignore\n', encoding='utf-8')
    package, _ = release.build_release(source_repo, 'HEAD', tmp_path / 'out')
    assert members(package)['backend/app.py'] == b'print("committed application")\n'


@pytest.mark.parametrize('name,content', [
    ('backend/key.pem', 'synthetic private data'),
    ('backend/credential.py', 'API_KEY = "unit-test-hardcoded-token-value"\n'),
    ('frontend/key.txt', '-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n'),
    ('backend/connection.py', 'DATABASE_URL = "postgresql://user:unit-test-private-pass-123@localhost/test"\n'),
    ('deploy/app.env.example', 'ARK_API_KEY=unit-test-api-token-123456\n'),
])
def test_risky_runtime_files_stop_release(source_repo, tmp_path, name, content):
    (source_repo / name).parent.mkdir(parents=True, exist_ok=True)
    (source_repo / name).write_text(content, encoding='utf-8')
    git(source_repo, 'add', '.')
    git(source_repo, 'commit', '-m', 'Synthetic unsafe fixture')
    with pytest.raises(release.ReleaseError):
        release.build_release(source_repo, 'HEAD', tmp_path / 'out')
    assert not list((tmp_path / 'out').glob('*.tar.gz'))


def test_symlink_in_runtime_path_is_rejected(source_repo, tmp_path):
    blob = git(source_repo, 'hash-object', '-w', '--stdin', input=b'../.env')
    git(source_repo, 'update-index', '--add', '--cacheinfo', f'120000,{blob},backend/link.py')
    git(source_repo, 'commit', '-m', 'Synthetic link fixture')
    with pytest.raises(release.ReleaseError, match='Unsupported link'):
        release.build_release(source_repo, 'HEAD', tmp_path / 'out')


def test_missing_commit_or_dependency_lock_stops_release(source_repo, tmp_path):
    with pytest.raises(release.ReleaseError):
        release.build_release(source_repo, 'not-a-commit', tmp_path / 'out')
    git(source_repo, 'rm', 'uv.lock')
    git(source_repo, 'commit', '-m', 'Synthetic missing lock fixture')
    with pytest.raises(release.ReleaseError, match='missing required'):
        release.build_release(source_repo, 'HEAD', tmp_path / 'out')


@pytest.fixture
def good_config():
    return {
        'JWT_SECRET_KEY': 'unit-test-signing-material-01234567890123456789',
        'DATABASE_URL': 'postgresql+psycopg2://test:unit-test-password-123456@127.0.0.1:5432/test',
        'REDIS_URL': 'redis://:unit-test-cache-password-123456@127.0.0.1:6379/0',
        'MODEL': 'unit-test-model', 'ARK_API_KEY': 'unit-test-api-token-123456789',
        'BASE_URL': 'https://model.invalid/v1', 'WEB_SEARCH_PROVIDER': 'tavily',
        'TAVILY_API_KEY': 'unit-test-search-token-123456789',
        'EMBEDDING_MODEL': '/opt/supermew/shared/models/test-model',
        'EMBEDDING_DEVICE': 'cpu', 'DENSE_EMBEDDING_DIM': '512',
        'MILVUS_HOST': '127.0.0.1', 'MILVUS_PORT': '19530',
        'BM25_STATE_PATH': '/opt/supermew/shared/data/bm25.json',
        'RESEARCH_LOCAL_STORE': '/opt/supermew/shared/data/research',
        'COMPANY_KNOWLEDGE_LOCAL_STORE': '/opt/supermew/shared/data/knowledge',
        'RESEARCH_OBJECT_STORE': 'local', 'COMPANY_KNOWLEDGE_OBJECT_STORE': 'local',
        'LIBREOFFICE_SOFFICE_PATH': '/usr/bin/soffice',
        'DOCX_RENDER_QA_WORKDIR': '/opt/supermew/shared/data/docx-qa',
        'DOCX_RENDER_QA_ENABLED': 'true', 'DOCX_RENDER_QA_REQUIRED': 'true',
    }


def test_offline_check_accepts_complete_config_and_keeps_manual_limits(good_config):
    issues = config.check_config(good_config)
    assert not [issue for issue in issues if issue[0] == 'ERROR']
    assert any(issue[1] == 'MANUAL_ACCEPTANCE' for issue in issues)
    text = json.dumps(issues)
    assert all(value not in text for key, value in good_config.items() if key.endswith(('KEY', 'URL')))


def test_search_pool_can_replace_single_key_without_exposing_credentials(good_config):
    good_config.pop('TAVILY_API_KEY')
    good_config['TAVILY_API_KEYS'] = 'unit-search-token-one,unit-search-token-two'
    issues = config.check_config(good_config)
    assert not [issue for issue in issues if issue[0] == 'ERROR']
    assert 'unit-search-token-one' not in json.dumps(issues)
    good_config['TAVILY_API_KEYS'] = '["private-invalid-json"'
    issues = config.check_config(good_config)
    assert any(level == 'ERROR' and field == 'TAVILY_API_KEYS' for level, field, _ in issues)
    assert 'private-invalid-json' not in json.dumps(issues)
    good_config['TAVILY_API_KEYS'] = ',,,'
    assert any(level == 'ERROR' and field == 'TAVILY_API_KEYS' for level, field, _ in config.check_config(good_config))


def test_multi_search_mode_keeps_existing_engine_selection(good_config):
    good_config['WEB_SEARCH_PROVIDER'] = 'multi'
    assert not any(level == 'ERROR' for level, _, _ in config.check_config(good_config))
    del good_config['TAVILY_API_KEY']
    assert any(level == 'ERROR' and key == 'WEB_SEARCH_PROVIDER'
               for level, key, _ in config.check_config(good_config))


@pytest.mark.parametrize('key,value', [
    ('JWT_SECRET_KEY', 'change-this-secret'),
    ('DATABASE_URL', 'postgresql://postgres:postgres@localhost/test'),
    ('DATABASE_URL', 'postgresql://test:unit-test-password-123456@localhost/test#unencoded'),
    ('REDIS_URL', 'redis://127.0.0.1:6379/0'),
    ('BASE_URL', 'http://model.invalid/v1'),
    ('EMBEDDING_MODEL', 'D:\\rag\\model'),
    ('BM25_STATE_PATH', '/opt/supermew/releases/old/bm25.json'),
    ('DENSE_EMBEDDING_DIM', 'not-a-number'),
    ('TAVILY_API_KEY', 'REPLACE_WITH_SEARCH_API_KEY'),
    ('MAX_UPLOAD_BYTES', '0'),
    ('MAX_JSON_BYTES', 'unlimited'),
    ('RESEARCH_MAX_CONCURRENT_RUNS', '999'),
    ('CORS_ALLOWED_ORIGINS', '*'),
    ('CORS_ALLOWED_ORIGINS', 'https://trusted.invalid/path'),
    ('DOCX_RENDER_QA_REQUIRED', 'false'),
    ('RESEARCH_DEMO_ENABLED', 'true'),
    ('ASSISTANT_MODEL', 'REPLACE_WITH_ASSISTANT_MODEL'),
])
def test_invalid_production_settings_are_rejected(good_config, key, value):
    good_config[key] = value
    assert any(level == 'ERROR' and field == key for level, field, _ in config.check_config(good_config))


def test_minio_and_company_knowledge_require_complete_credentials(good_config):
    good_config.update(RESEARCH_OBJECT_STORE='minio', BAILIAN_KNOWLEDGE_API_KEY='unit-test-token')
    errors = {key for level, key, _ in config.check_config(good_config) if level == 'ERROR'}
    assert {'MINIO_ACCESS_KEY', 'MINIO_SECRET_KEY', 'MINIO_ENDPOINT',
            'BAILIAN_KNOWLEDGE_BASE_URL', 'BAILIAN_KNOWLEDGE_AGENT_ID'} <= errors


def test_company_knowledge_endpoint_matches_application_contract(good_config):
    good_config.update(BAILIAN_KNOWLEDGE_API_KEY='unit-test-knowledge-token-123',
                       BAILIAN_KNOWLEDGE_BASE_URL='https://test-workspace.cn-beijing.maas.aliyuncs.com',
                       BAILIAN_KNOWLEDGE_AGENT_ID='test-agent', BAILIAN_KNOWLEDGE_INDEX_ID='test-index')
    assert not any(level == 'ERROR' for level, _, _ in config.check_config(good_config))
    good_config['BAILIAN_KNOWLEDGE_BASE_URL'] += '/api'
    assert any(level == 'ERROR' and key == 'BAILIAN_KNOWLEDGE_BASE_URL'
               for level, key, _ in config.check_config(good_config))


@pytest.mark.skipif(os.name == 'nt', reason='Actual Linux path checks run on the target platform.')
def test_first_start_allows_missing_bm25_file_when_parent_exists(tmp_path, good_config):
    good_config['BM25_STATE_PATH'] = (tmp_path / 'new-bm25.json').as_posix()
    assert not any(level == 'ERROR' and key == 'BM25_STATE_PATH'
                   for level, key, _ in config.check_config(good_config, check_paths=True))


def test_env_parser_rejects_ambiguous_and_duplicate_assignments():
    values, issues = config.parse_env('JWT_SECRET_KEY="unit-test # quoted"\nJWT_SECRET_KEY=duplicate\nexport MODEL=bad\nMODEL=value # inline comment\n')
    assert values['JWT_SECRET_KEY'] == 'unit-test # quoted'
    assert len(issues) == 3
    assert 'duplicate' not in json.dumps(issues)
    assert 'unit-test # quoted' not in json.dumps(issues)


def test_no_environment_expansion_or_windows_path_acceptance(good_config):
    good_config['ARK_API_KEY'] = '${SHOULD_NOT_BE_READ_FROM_ENV}'
    assert any(level == 'ERROR' and key == 'ARK_API_KEY' for level, key, _ in config.check_config(good_config))
    _, issues = config.parse_env('EMBEDDING_MODEL=D:\\rag\\model\n')
    assert issues and 'D:\\rag' not in json.dumps(issues)


def test_check_paths_is_explicit_and_reports_only_field_names(good_config):
    good_config['RESEARCH_LOCAL_STORE'] = '/nonexistent-test-path-3dbf1d6f'
    assert not any(level == 'ERROR' for level, _, _ in config.check_config(good_config))
    issues = config.check_config(good_config, check_paths=True)
    assert any(level == 'ERROR' and key == 'RESEARCH_LOCAL_STORE' for level, key, _ in issues)
    assert good_config['RESEARCH_LOCAL_STORE'] not in json.dumps(issues)


@pytest.mark.parametrize('key', ['BM25_STATE_PATH', 'RESEARCH_LOCAL_STORE',
                               'LIBREOFFICE_SOFFICE_PATH', 'EMBEDDING_MODEL'])
def test_path_permission_failure_is_reported_without_leaking_the_path(good_config, monkeypatch, key):
    blocked = '/restricted-test-path-must-not-be-echoed'
    good_config[key] = blocked
    original = Path.stat
    def stat(path, *args, **kwargs):
        if path.as_posix() == blocked:
            raise PermissionError(blocked)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', stat)
    issues = config.check_config(good_config, check_paths=True)
    assert any(level == 'ERROR' and field == key for level, field, _ in issues)
    assert blocked not in json.dumps(issues)


def test_cli_failure_redacts_config_secrets(tmp_path, good_config):
    import sys
    secret = 'unit-test-super-sensitive-password-123456789'
    good_config['DATABASE_URL'] = f'postgresql://user:{secret}@host:invalid/db'
    path = tmp_path / 'private.env'
    path.write_text('\n'.join(f'{key}={value}' for key, value in good_config.items()), encoding='utf-8')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/check-production-config.py'),
                             '--env-file', str(path), '--json'], capture_output=True, text=True)
    assert result.returncode == 1
    assert secret not in result.stdout + result.stderr
    assert not json.loads(result.stdout)['passed']


def test_cli_success_stays_offline_and_redacts_values(tmp_path, good_config):
    import sys
    path = tmp_path / 'private.env'
    path.write_text('\n'.join(f'{key}={value}' for key, value in good_config.items()), encoding='utf-8')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/check-production-config.py'),
                             '--env-file', str(path), '--json'], capture_output=True, text=True)
    assert result.returncode == 0 and json.loads(result.stdout)['passed']
    assert good_config['JWT_SECRET_KEY'] not in result.stdout + result.stderr
