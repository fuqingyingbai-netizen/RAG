"""Automated tests are isolated from configured data and external services."""
import ipaddress
import os
from pathlib import Path
import socket
from uuid import uuid4

import pytest


def pytest_addoption(parser):
    parser.addoption('--allow-network', action='store_true',
                     help='Explicitly allow service connections (manual acceptance tools live in scripts/manual).')


def _require_loopback(host):
    if host is None:
        return
    if isinstance(host, bytes):
        host = host.decode('ascii')
    if str(host).lower().rstrip('.') == 'localhost':
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise RuntimeError('自动测试禁止外部网络请求；真实服务验收请使用 scripts/manual 中的工具。')


def pytest_configure(config):
    guard = pytest.MonkeyPatch()
    config._rag_test_guard = guard
    root = Path(config.rootpath) / 'work' / ('automated-tests-' + uuid4().hex)
    guard.setenv('PYTHON_DOTENV_DISABLED', '1')
    guard.setenv('JWT_SECRET_KEY', 'automated-tests-only-not-a-deployment-secret')
    guard.setenv('LANGSMITH_TRACING', 'false')
    guard.setenv('LANGCHAIN_TRACING_V2', 'false')
    # dotenv must not point a test at real business data, even during collection.
    if os.getenv('ACCOUNT_TEST_POSTGRES') != '1':
        guard.setenv('DATABASE_URL', 'sqlite://')
    guard.setenv('BM25_STATE_PATH', str(root / 'bm25.json'))
    guard.setenv('RESEARCH_OBJECT_STORE', 'local')
    guard.setenv('RESEARCH_LOCAL_STORE', str(root / 'research'))
    guard.setenv('COMPANY_KNOWLEDGE_OBJECT_STORE', 'local')
    guard.setenv('COMPANY_KNOWLEDGE_LOCAL_STORE', str(root / 'knowledge'))
    guard.setenv('REDIS_URL', 'redis://127.0.0.1:1/0')
    guard.setenv('MILVUS_HOST', '127.0.0.1')
    guard.setenv('MILVUS_PORT', '1')
    import embedding
    def no_real_model():
        raise RuntimeError('自动测试不加载真实向量模型，请注入假模型；真实模型验收使用 scripts/manual/check_embedding.py。')
    guard.setattr(embedding, '_create_dense_embedder', no_real_model)
    if config.getoption('--allow-network'):
        return
    original_lookup = socket.getaddrinfo
    original_connect, original_connect_ex = socket.socket.connect, socket.socket.connect_ex

    def lookup(host, *args, **kwargs):
        _require_loopback(host)
        return original_lookup(host, *args, **kwargs)

    def connect(sock, address):
        if sock.family in {socket.AF_INET, socket.AF_INET6}:
            _require_loopback(address[0])
        return original_connect(sock, address)

    def connect_ex(sock, address):
        if sock.family in {socket.AF_INET, socket.AF_INET6}:
            _require_loopback(address[0])
        return original_connect_ex(sock, address)

    # Install before collection so an import cannot launch an external request.
    guard.setattr(socket, 'getaddrinfo', lookup)
    guard.setattr(socket.socket, 'connect', connect)
    guard.setattr(socket.socket, 'connect_ex', connect_ex)


def pytest_unconfigure(config):
    guard = getattr(config, '_rag_test_guard', None)
    if guard:
        guard.undo()
