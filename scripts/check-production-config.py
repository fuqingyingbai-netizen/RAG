"""Offline Linux production configuration checks. Never loads app code or connects to services."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
from urllib.parse import unquote, urlsplit

PLACEHOLDERS = ('change-this-secret', 'change_me', 'changeme', 'replace_', 'your_',
                'example', 'placeholder', '${', '<', '>')
PATH_KEYS = ('BM25_STATE_PATH', 'RESEARCH_LOCAL_STORE', 'COMPANY_KNOWLEDGE_LOCAL_STORE',
             'LIBREOFFICE_SOFFICE_PATH', 'DOCX_RENDER_QA_WORKDIR')
SEARCH_KEYS = {'tavily': 'TAVILY_API_KEY', 'exa': 'EXA_API_KEY', 'serper': 'SERPER_API_KEY',
               'serpapi': 'SERPAPI_API_KEY', 'brave': 'BRAVE_API_KEY', 'bocha': 'BOCHA_API_KEY'}


def parse_env(text):
    """Supported subset: one KEY=value per line, optional matching quotes, no expansion."""
    values, issues = {}, []
    for line_number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
            issues.append(('ERROR', f'line_{line_number}', 'Use one uppercase KEY=value assignment per line.'))
            continue
        if key in values:
            issues.append(('ERROR', f'line_{line_number}', 'Duplicate configuration assignment.'))
            continue
        if value.startswith(('"', "'")):
            quote = value[0]
            if len(value) < 2 or value[-1] != quote or quote in value[1:-1]:
                issues.append(('ERROR', f'line_{line_number}', 'Use matching quotes without embedded quotes.'))
                continue
            value = value[1:-1]
        elif any(char.isspace() for char in value) or '#' in value or '"' in value or "'" in value:
            issues.append(('ERROR', f'line_{line_number}', 'Quote values containing spaces or #; comments use their own line.'))
            continue
        if '\\' in value or '\x00' in value:
            issues.append(('ERROR', f'line_{line_number}', 'Backslashes and NUL are unsupported; use Linux paths and simple quoted values.'))
            continue
        values[key] = value
    return values, issues


def placeholder(value):
    lower = value.lower()
    return not value or any(marker in lower for marker in PLACEHOLDERS)


def check_config(values, *, check_paths=False):
    issues = []

    def issue(level, key, message):
        issues.append((level, key, message))

    def required(key):
        value = values.get(key, '')
        if placeholder(value):
            issue('ERROR', key, 'Required value is missing or still a template placeholder.')
            return ''
        return value

    def secret(key, minimum=16):
        value = required(key)
        if value and (len(value) < minimum or value.lower() in {'postgres', 'minioadmin', 'password'}):
            issue('ERROR', key, 'Use a unique random production credential of sufficient length.')
        return value

    def connection_url(key, schemes, minimum_password=16):
        value = required(key)
        if not value:
            return
        try:
            parsed = urlsplit(value)
            port = parsed.port
            if parsed.scheme not in schemes or not parsed.hostname or parsed.hostname in {'0.0.0.0', '::'}:
                raise ValueError
            if port is not None and not 1 <= port <= 65535:
                raise ValueError
            password = unquote(parsed.password or '')
            if placeholder(password) or len(password) < minimum_password or password.lower() in {'postgres', 'minioadmin', 'password'}:
                issue('ERROR', key, 'Connection must contain a non-default production password; URL-encode reserved characters.')
            if key == 'DATABASE_URL' and (not parsed.username or parsed.path in {'', '/'}):
                issue('ERROR', key, 'Specify database username and database name.')
            if key == 'REDIS_URL' and not re.fullmatch(r'/[0-9]+', parsed.path):
                issue('ERROR', key, 'Specify a numeric Redis database index.')
            if parsed.query or parsed.fragment or len(parsed.path.split('/')) > 2:
                issue('ERROR', key, 'Unexpected URL suffix; check encoding and connection format.')
            if parsed.hostname not in {'localhost', '127.0.0.1', '::1'}:
                issue('WARN', key, 'Non-loopback service: verify private networking and firewall access separately.')
        except ValueError:
            issue('ERROR', key, 'Invalid service URL; no credential values are displayed.')

    def https_endpoint(key):
        value = required(key)
        if not value:
            return
        try:
            parsed = urlsplit(value)
            if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError
            if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'localhost', '127.0.0.1', '::1'}):
                raise ValueError
            _ = parsed.port
        except ValueError:
            issue('ERROR', key, 'Use an HTTPS endpoint, or HTTP on loopback for an explicitly local service.')

    secret('JWT_SECRET_KEY', 32)
    if values.get('JWT_ALGORITHM', 'HS256') != 'HS256':
        issue('ERROR', 'JWT_ALGORITHM', 'This deployment profile supports HS256 only.')
    connection_url('DATABASE_URL', {'postgresql', 'postgresql+psycopg2'})
    connection_url('REDIS_URL', {'redis', 'rediss'})
    required('MODEL')
    secret('ARK_API_KEY')
    https_endpoint('BASE_URL')
    if values.get('ASSISTANT_BASE_URL'):
        https_endpoint('ASSISTANT_BASE_URL')
    if values.get('ASSISTANT_API_KEY'):
        secret('ASSISTANT_API_KEY')
    tavily_pool = values.get('TAVILY_API_KEYS', '').strip()
    if tavily_pool:
        try:
            pool_keys = json.loads(tavily_pool) if tavily_pool.startswith('[') else re.split(r'[,;\s]+', tavily_pool)
            if (not isinstance(pool_keys, list) or not pool_keys
                    or not any(isinstance(key, str) and key.strip() for key in pool_keys)
                    or any(not isinstance(key, str) or placeholder(key.strip()) or len(key.strip()) < 16
                           for key in pool_keys if key != '')):
                raise ValueError
        except (ValueError, TypeError):
            issue('ERROR', 'TAVILY_API_KEYS', 'Use a list of valid credentials; values are never displayed.')
    provider = values.get('WEB_SEARCH_PROVIDER', '').lower()
    if provider and provider not in SEARCH_KEYS and provider != 'multi':
        issue('ERROR', 'WEB_SEARCH_PROVIDER', 'Unsupported search provider in this deployment profile.')
    elif provider == 'tavily' and tavily_pool:
        pass  # An explicit pool supersedes the legacy single credential.
    elif provider in SEARCH_KEYS:
        secret(SEARCH_KEYS[provider])
    elif not tavily_pool and not any(not placeholder(values.get(key, '')) for key in SEARCH_KEYS.values()):
        issue('ERROR', 'WEB_SEARCH_PROVIDER', 'Configure at least one search provider credential.')

    required('EMBEDDING_MODEL')
    if values.get('EMBEDDING_DEVICE') != 'cpu':
        issue('ERROR', 'EMBEDDING_DEVICE', 'The checked server profile uses CPU; GPU support has not been verified.')
    try:
        if int(values.get('DENSE_EMBEDDING_DIM', '0')) <= 0:
            raise ValueError
    except ValueError:
        issue('ERROR', 'DENSE_EMBEDDING_DIM', 'Specify a positive dimension and verify it against the actual model and collection.')
    host = required('MILVUS_HOST')
    if host and (host in {'0.0.0.0', '::'} or '/' in host or ':' in host and host != '::1'):
        issue('ERROR', 'MILVUS_HOST', 'Specify a host name or address, without URL or port.')
    try:
        if not 1 <= int(values.get('MILVUS_PORT', '0')) <= 65535:
            raise ValueError
    except ValueError:
        issue('ERROR', 'MILVUS_PORT', 'Specify a valid service port.')
    for key in PATH_KEYS:
        value = required(key)
        if value and (not PurePosixPath(value).is_absolute() or re.match(r'^[A-Za-z]:', value)):
            issue('ERROR', key, 'Use an absolute Linux path outside the versioned release directory.')
        elif value and ('/releases/' in value or '/current/' in value or '..' in PurePosixPath(value).parts):
            issue('ERROR', key, 'Use persistent shared storage or a system binary, independent of the release directory.')
        elif value and check_paths:
            path = Path(value)
            try:
                if key == 'BM25_STATE_PATH':
                    valid = path.is_file() or (not path.exists() and path.parent.is_dir())
                elif key == 'LIBREOFFICE_SOFFICE_PATH':
                    valid = path.is_file() and os.access(path, os.X_OK)
                else:
                    valid = path.is_dir()
            except OSError:
                valid = False
            if not valid:
                issue('ERROR', key, 'Configured directory or executable is unavailable on this machine.')
    embedding = values.get('EMBEDDING_MODEL', '')
    if '\\' in embedding or re.match(r'^[A-Za-z]:', embedding):
        issue('ERROR', 'EMBEDDING_MODEL', 'Windows model paths cannot be used on Linux.')
    elif embedding.startswith('/') and check_paths:
        try:
            model_available = Path(embedding).is_dir()
        except OSError:
            model_available = False
        if not model_available:
            issue('ERROR', 'EMBEDDING_MODEL', 'Configured local model directory is unavailable.')
    for key in ('RESEARCH_OBJECT_STORE', 'COMPANY_KNOWLEDGE_OBJECT_STORE'):
        if values.get(key) not in {'local', 'minio'}:
            issue('ERROR', key, 'Explicitly select local or minio storage.')
    if any(values.get(key) == 'minio' for key in ('RESEARCH_OBJECT_STORE', 'COMPANY_KNOWLEDGE_OBJECT_STORE')):
        secret('MINIO_ACCESS_KEY')
        secret('MINIO_SECRET_KEY')
        endpoint = required('MINIO_ENDPOINT')
        try:
            parsed = urlsplit('//' + endpoint)
            if not parsed.hostname or parsed.username or parsed.password or parsed.path or not parsed.port:
                raise ValueError
            if values.get('MINIO_SECURE', '').lower() not in {'true', 'false'}:
                raise ValueError
            local = parsed.hostname in {'localhost', '127.0.0.1', '::1'}
            if not local and values.get('MINIO_SECURE', '').lower() != 'true':
                issue('WARN', 'MINIO_SECURE', 'Verify private networking for unencrypted non-loopback object storage.')
        except ValueError:
            issue('ERROR', 'MINIO_ENDPOINT', 'Specify host:port and an explicit MINIO_SECURE setting.')
    knowledge_keys = ('BAILIAN_KNOWLEDGE_API_KEY', 'BAILIAN_KNOWLEDGE_BASE_URL',
                      'BAILIAN_KNOWLEDGE_AGENT_ID', 'BAILIAN_KNOWLEDGE_INDEX_ID')
    if any(values.get(key) for key in knowledge_keys):
        for key in knowledge_keys:
            required(key)
        https_endpoint('BAILIAN_KNOWLEDGE_BASE_URL')
        try:
            parsed = urlsplit(values.get('BAILIAN_KNOWLEDGE_BASE_URL', ''))
            if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port
                    or parsed.path not in {'', '/'} or parsed.query or parsed.fragment
                    or not re.fullmatch(r'[a-z0-9-]+\.[a-z0-9-]+\.maas\.aliyuncs\.com', parsed.hostname or '')):
                raise ValueError
        except ValueError:
            issue('ERROR', 'BAILIAN_KNOWLEDGE_BASE_URL', 'Use the workspace endpoint format required by the application, with no extra path or port.')
    else:
        issue('WARN', 'COMPANY_KNOWLEDGE', 'Managed company knowledge is not configured; confirm release scope.')
    for key in ('DOCX_RENDER_QA_ENABLED', 'DOCX_RENDER_QA_REQUIRED'):
        if values.get(key, '').lower() != 'true':
            issue('ERROR', key, 'This release profile requires rendered Word delivery checks.')
    if values.get('RESEARCH_DEMO_ENABLED', 'false').lower() != 'false':
        issue('ERROR', 'RESEARCH_DEMO_ENABLED', 'Disable demo research data for production.')
    for key, value in values.items():
        if value and placeholder(value) and not any(level == 'ERROR' and field == key for level, field, _ in issues):
            issue('ERROR', key, 'Replace template values; service environment files do not expand variables.')
    for key, default, maximum in [('MAX_UPLOAD_BYTES', 52428800, 104857600),
                                  ('MAX_REQUEST_BYTES', 54525952, 110100480),
                                  ('MAX_JSON_BYTES', 2097152, 10485760),
                                  ('RESEARCH_MAX_CONCURRENT_RUNS', 1, 8),
                                  ('RESEARCH_MAX_RUNS_PER_USER', 1, 8)]:
        try:
            if not 1 <= int(values.get(key, str(default))) <= maximum:
                raise ValueError()
        except ValueError:
            issue('ERROR', key, 'Specify a positive bounded resource limit.')
    for origin in values.get('CORS_ALLOWED_ORIGINS', '').split(','):
        if not origin.strip():
            continue
        try:
            parsed = urlsplit(origin.strip())
            if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username
                    or parsed.password or parsed.path or parsed.query or parsed.fragment or '*' in origin):
                raise ValueError()
        except ValueError:
            issue('ERROR', 'CORS_ALLOWED_ORIGINS', 'List explicit trusted HTTP or HTTPS origins without paths or wildcards.')
    issue('WARN', 'MANUAL_ACCEPTANCE', 'Offline checks cannot prove CORS, TLS, permissions, connectivity, backup recovery or task capacity.')
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True, type=Path)
    parser.add_argument('--check-paths', action='store_true', help='Check path existence on the Linux target, not Windows')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    try:
        values, issues = parse_env(args.env_file.read_text(encoding='utf-8-sig'))
        issues += check_config(values, check_paths=args.check_paths)
    except (OSError, UnicodeError):
        issues = [('ERROR', 'ENV_FILE', 'Unable to read UTF-8 configuration file.')]
    errors = sum(item[0] == 'ERROR' for item in issues)
    if args.json:
        print(json.dumps({'passed': errors == 0, 'errors': errors,
                          'issues': [{'level': level, 'key': key, 'message': message}
                                     for level, key, message in issues]}, ensure_ascii=False, indent=2))
    else:
        for level, key, message in issues:
            print(f'{level} {key}: {message}')
        print(f'{"FAIL" if errors else "PASS"} offline configuration: {errors} error(s). Values are never displayed.')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
