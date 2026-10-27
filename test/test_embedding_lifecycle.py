"""Dense-model lifecycle checks use fakes; no model is downloaded or executed."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier, Event

import pytest

import embedding


def test_import_does_not_load_dense_model_or_tensor_runtime(tmp_path):
    env = {key: os.environ[key] for key in ['PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP'] if key in os.environ}
    env.update(BM25_STATE_PATH=str(tmp_path / 'sparse.json'),
               PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'backend'),
               PYTHON_DOTENV_DISABLED='1')
    code = '''
import importlib.abc, sys, json
class NoModelImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'langchain_huggingface', 'torch', 'sentence_transformers'}:
            raise AssertionError('Model runtime was imported before a dense request')
sys.meta_path.insert(0, NoModelImports())
import embedding
print(json.dumps({'model_unloaded': embedding.embedding_service._embedder is None,
 'huggingface_imported': 'langchain_huggingface' in sys.modules, 'torch_imported': 'torch' in sys.modules}))
'''
    result = subprocess.run([sys.executable, '-c', code], env=env, text=True,
                            capture_output=True, check=True, timeout=15)
    assert json.loads(result.stdout) == {'model_unloaded': True, 'huggingface_imported': False, 'torch_imported': False}


def test_sparse_operations_and_empty_dense_input_do_not_create_model(tmp_path, monkeypatch):
    def forbidden():
        raise AssertionError('Sparse statistics must not initialize the dense model')
    monkeypatch.setattr(embedding, '_create_dense_embedder', forbidden)
    path = tmp_path / 'sparse.json'
    service = embedding.EmbeddingService(path)
    assert service.get_embeddings([]) == []
    service.increment_add_documents(['机器人行业资料', '行业政策'])
    assert service.get_sparse_embedding('行业')
    service.increment_remove_documents(['行业政策'])
    restored = embedding.EmbeddingService(path)
    assert restored._total_docs == 1 and restored._vocab == service._vocab
    assert service._embedder is None and restored._embedder is None


def test_concurrent_first_requests_share_one_dense_model(tmp_path, monkeypatch):
    barrier, entered, release = Barrier(6), Event(), Event()
    calls = []
    class FakeModel:
        def embed_documents(self, texts):
            return [[len(text), 1.0] for text in texts]
    def create():
        calls.append('created'); entered.set()
        assert release.wait(3)
        return FakeModel()
    monkeypatch.setattr(embedding, '_create_dense_embedder', create)
    service = embedding.EmbeddingService(tmp_path / 'sparse.json')
    def request(_):
        barrier.wait(timeout=3)
        return service.get_embeddings(['行业'])
    with ThreadPoolExecutor(max_workers=6) as pool:
        pending = [pool.submit(request, index) for index in range(6)]
        assert entered.wait(3)
        release.set()
        assert [future.result(timeout=3) for future in pending] == [[[2, 1.0]]] * 6
    assert calls == ['created']
    assert service.get_embeddings(['abc']) == [[3, 1.0]]
    assert calls == ['created']


def test_failed_initialization_can_retry_without_replacing_sparse_state(tmp_path, monkeypatch):
    calls = []
    class FakeModel:
        def embed_documents(self, texts):
            return [[0.5] for _ in texts]
    def create():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('model files temporarily unavailable')
        return FakeModel()
    monkeypatch.setattr(embedding, '_create_dense_embedder', create)
    service = embedding.EmbeddingService(tmp_path / 'sparse.json')
    service.increment_add_documents(['保留稀疏统计'])
    with pytest.raises(Exception, match='temporarily unavailable'):
        service.get_embeddings(['行业'])
    assert service._embedder is None
    assert service.get_embeddings(['行业']) == [[0.5]]
    assert len(calls) == 2 and service._total_docs == 1


@pytest.mark.parametrize('name', ['check_embedding', 'evaluate_langsmith', 'split_audio', 'fix_bom'])
def test_importing_manual_tools_does_not_run_models_evaluations_or_file_operations(name, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Manual tool ran while being imported')
    monkeypatch.setattr(os, 'makedirs', forbidden)
    monkeypatch.setattr(Path, 'write_bytes', forbidden)
    path = Path(__file__).resolve().parents[1] / 'scripts/manual' / (name + '.py')
    spec = importlib.util.spec_from_file_location('manual_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(getattr(module, 'main' if name != 'split_audio' else 'split_fixed'))


def test_automated_tests_block_external_network_before_dns(request):
    if request.config.getoption('--allow-network'):
        pytest.skip('Network explicitly enabled for this test run')
    import socket
    with pytest.raises(RuntimeError, match='禁止外部网络'):
        socket.getaddrinfo('example.invalid', 443)
    with pytest.raises(RuntimeError, match='禁止外部网络'):
        socket.create_connection(('203.0.113.10', 443), timeout=.1)
