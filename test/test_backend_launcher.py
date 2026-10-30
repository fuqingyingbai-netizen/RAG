"""Launcher tests use fake HTTP responses and never start research or servers."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import requests

spec = importlib.util.spec_from_file_location('tested_backend_launcher', Path(__file__).resolve().parents[1]/'scripts/run_backend.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_unauthenticated_401_proves_only_reachability(monkeypatch):
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=401)
    monkeypatch.setattr(launcher.requests, 'get', get)
    result = launcher.probe_provider('https://provider.invalid/v1?secret=PRIVATE')
    assert result['network_reachable'] and not result['authorization_sent'] and not result['model_request_verified']
    assert calls == [('https://provider.invalid/v1/models', {'timeout':8,'allow_redirects':False,'auth':launcher._without_auth})]
    assert 'PRIVATE' not in json.dumps(result)


def test_denied_socket_and_other_connection_failures_are_safe(monkeypatch):
    for message, code in [('WinError 10013 PRIVATE', 'network_permission_denied'), ('reset PRIVATE', 'provider_connection_failed')]:
        def get(*a, **kw):
            raise requests.ConnectionError(message)
        monkeypatch.setattr(launcher.requests, 'get', get)
        result = launcher.probe_provider('https://provider.invalid/v1')
        assert not result['network_reachable'] and result['error_code'] == code
        assert 'PRIVATE' not in json.dumps(result)


def test_invalid_or_credential_embedded_urls_never_send_credentials(monkeypatch):
    monkeypatch.setattr(launcher.requests, 'get', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('must not send')))
    for url in ['', 'file:///PRIVATE', 'https://user:PRIVATE@provider.invalid/v1']:
        result = launcher.probe_provider(url)
        assert result['error_code'] == 'invalid_provider_url'
        assert 'PRIVATE' not in json.dumps(result)


def test_failed_preflight_exits_without_importing_or_running_server(monkeypatch, capsys):
    monkeypatch.setattr(launcher, 'load_dotenv', lambda *a, **kw: None)
    monkeypatch.setattr(launcher, 'probe_provider', lambda _: {'network_reachable':False})
    assert launcher.main([]) == 2
    assert 'not started' in capsys.readouterr().err


def test_check_only_never_starts_the_server(monkeypatch):
    monkeypatch.setattr(launcher, 'load_dotenv', lambda *a, **kw: None)
    monkeypatch.setattr(launcher, 'probe_provider', lambda _: {'network_reachable':True,'http_status':401})
    assert launcher.main(['--check-only']) == 0


def test_probe_cannot_implicitly_send_netrc_or_existing_authorization(monkeypatch):
    monkeypatch.setattr(requests.sessions, 'get_netrc_auth', lambda *a, **kw: ('user','PRIVATE'))
    request=requests.Request('GET','https://provider.invalid/v1/models',
        headers={'Authorization':'PRIVATE'}, auth=launcher._without_auth)
    prepared=requests.Session().prepare_request(request)
    assert 'Authorization' not in prepared.headers
