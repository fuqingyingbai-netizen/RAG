"""Initialization boundaries and format dispatch; no model or storage calls."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import threading

import pytest

from document_loader import DocumentLoader


def test_import_and_constructor_do_not_import_optional_ml_or_parser_packages():
    backend = Path(__file__).resolve().parents[1] / 'backend'
    code = (
        'import sys,json;sys.path.insert(0,' + repr(str(backend)) + ');'
        'from document_loader import DocumentLoader;loader=DocumentLoader();'
        'print(json.dumps([name for name in ["torch","sentence_transformers",'
        '"langchain_text_splitters","langchain_community.document_loaders"] if name in sys.modules]))'
    )
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=10, check=True)
    assert json.loads(result.stdout) == []


def test_concurrent_first_use_initializes_each_level_once(monkeypatch):
    calls = []
    class Splitter:
        def __init__(self, **kwargs): calls.append(kwargs)
    monkeypatch.setitem(sys.modules, 'langchain_text_splitters', SimpleNamespace(RecursiveCharacterTextSplitter=Splitter))
    loader = DocumentLoader()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: loader._get_splitters(), range(32)))
    assert all(result is results[0] for result in results)
    assert [(c['chunk_size'], c['chunk_overlap']) for c in calls] == [(1200,240),(600,120),(300,60)]
    assert all(c['add_start_index'] and c['separators'] == ['\n\n','\n','。','！','？','，','、',' ',''] for c in calls)


def test_failed_initialization_does_not_publish_half_ready_splitters(monkeypatch):
    calls = []
    class Splitter:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 2: raise RuntimeError('synthetic import dependency failure')
    monkeypatch.setitem(sys.modules, 'langchain_text_splitters', SimpleNamespace(RecursiveCharacterTextSplitter=Splitter))
    loader = DocumentLoader()
    with pytest.raises(RuntimeError): loader._get_splitters()
    assert loader._splitters is None
    assert len(loader._get_splitters()) == 3
    assert len(calls) == 5


@pytest.mark.parametrize('extension,expected', [('.PDF','PyPDFLoader'),('.docx','Docx2txtLoader'),
    ('.doc','Docx2txtLoader'),('.XLSX','UnstructuredExcelLoader'),('.xls','UnstructuredExcelLoader')])
def test_only_the_selected_file_parser_is_requested(extension, expected, monkeypatch):
    requested = []
    class Parsers:
        def __getattr__(self, name):
            requested.append(name)
            if name.startswith('__'): raise AttributeError(name)
            return lambda path: SimpleNamespace(load=lambda: [])
    monkeypatch.setitem(sys.modules, 'langchain_community.document_loaders', Parsers())
    loader = DocumentLoader()
    assert loader.load_document('synthetic/path', 'sample'+extension) == []
    assert [name for name in requested if not name.startswith('__')] == [expected]
    assert loader._splitters is None


def test_empty_page_and_unsupported_type_do_not_start_parsing(monkeypatch):
    loader = DocumentLoader()
    monkeypatch.setattr(loader, '_get_splitters', lambda: pytest.fail('empty text must not initialize splitters'))
    assert loader._split_page_to_three_levels('', {}, 0) == []
    with pytest.raises(ValueError, match='不支持的文件类型'):
        loader.load_document('synthetic', 'unknown.bin')


def test_invalid_overlap_is_rejected_at_construction_before_optional_imports():
    with pytest.raises(ValueError, match='larger chunk overlap'):
        DocumentLoader(chunk_size=500, chunk_overlap=10000)


def test_legacy_knowledge_upload_parses_and_indexes_in_a_worker(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import api
    entered, release = threading.Event(), threading.Event()
    writes = []
    def slow_parse(*_):
        entered.set(); assert release.wait(5)
        return [{'chunk_level':1,'text':'parent'}, {'chunk_level':3,'text':'leaf'}]
    monkeypatch.setattr(api, 'UPLOAD_DIR', tmp_path/'upload')
    monkeypatch.setattr(api, '_remove_bm25_stats_for_filename', lambda _: None)
    monkeypatch.setattr(api.milvus_manager, 'init_collection', lambda: None)
    monkeypatch.setattr(api.milvus_manager, 'query', lambda **kwargs: [])
    monkeypatch.setattr(api.parent_chunk_store, 'contains_filename', lambda _: False)
    monkeypatch.setattr(api.milvus_manager, 'delete', lambda _: None)
    monkeypatch.setattr(api.parent_chunk_store, 'delete_by_filename', lambda _: None)
    monkeypatch.setattr(api.parent_chunk_store, 'upsert_documents', lambda docs: writes.append(('parent',docs)))
    monkeypatch.setattr(api.milvus_writer, 'write_documents', lambda docs: writes.append(('leaf',docs)))
    monkeypatch.setattr(api.loader, 'load_document', slow_parse)
    app = FastAPI(); app.include_router(api.router)
    app.dependency_overrides[api.require_admin] = lambda: SimpleNamespace(role='admin')
    @app.get('/responsive-check')
    async def responsive_check(): return {'ok': True}
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
        upload = pool.submit(client.post, '/documents/upload', files={'file':('sample.docx',b'synthetic')})
        try:
            assert entered.wait(2)
            quick = pool.submit(client.get, '/responsive-check')
            assert quick.result(timeout=1).json() == {'ok':True}
        finally:
            release.set()
        result = upload.result(timeout=3)
        assert result.status_code == 200, result.text
        assert result.json()['chunks_processed'] == 1
    assert [kind for kind, docs in writes] == ['parent','leaf']
