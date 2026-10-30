"""Account-only startup stays independent of the native vector SDK."""
import builtins
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace


def load_manager_module():
    path = Path(__file__).resolve().parents[1] / 'backend/milvus_client.py'
    spec = importlib.util.spec_from_file_location('isolated_lazy_milvus', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_module_and_manager_can_start_when_native_sdk_import_is_unavailable(monkeypatch):
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name == 'pymilvus' or name.startswith(('pymilvus.', 'grpc')):
            raise AssertionError('Account startup imported the vector SDK')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    manager = load_manager_module().MilvusManager()
    assert manager.client is None


def test_real_vector_client_is_created_on_first_use_and_cached(monkeypatch):
    module = load_manager_module()
    calls = []
    def client(**kwargs):
        calls.append(kwargs)
        return object()
    monkeypatch.setitem(sys.modules, 'pymilvus', SimpleNamespace(MilvusClient=client))
    monkeypatch.setenv('MILVUS_HOST', '127.0.0.1')
    monkeypatch.setenv('MILVUS_PORT', '19530')
    manager = module.MilvusManager()
    assert calls == []
    first = manager._get_client()
    assert manager._get_client() is first
    assert calls == [{'uri': 'http://127.0.0.1:19530'}]


def test_hybrid_operation_still_builds_both_requests_and_rrf_ranker(monkeypatch):
    module = load_manager_module()
    class SDKObject:
        def __init__(self, **kwargs):
            self.options = kwargs
    monkeypatch.setitem(sys.modules, 'pymilvus', SimpleNamespace(AnnSearchRequest=SDKObject, RRFRanker=SDKObject))
    calls = []
    manager = module.MilvusManager()
    manager.client = SimpleNamespace(hybrid_search=lambda **kwargs: calls.append(kwargs) or [[]])
    assert manager.hybrid_retrieve([0.1, 0.2], {1: 0.5}, top_k=3, rrf_k=30, filter_expr='owner == 1') == []
    request = calls[0]
    assert [r.options['anns_field'] for r in request['reqs']] == ['dense_embedding', 'sparse_embedding']
    assert [r.options['data'] for r in request['reqs']] == [[[0.1, 0.2]], [{1: 0.5}]]
    assert all(r.options['expr'] == 'owner == 1' and r.options['limit'] == 6 for r in request['reqs'])
    assert request['ranker'].options == {'k': 30} and request['limit'] == 3
