import json
import threading
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from research_workflow import ResearchWorkflow
from json_utils import strip_nul


def test_nul_sanitization_preserves_literal_unicode_escape_and_nested_data():
    payload = {'text': 'PDF\x00正文', 'nested': ['a\x00b', {'literal': r'\u0000', 'key\x00': 0}]}
    clean = strip_nul(payload)
    assert clean == {'text': 'PDF正文', 'nested': ['ab', {'literal': r'\u0000', 'key': 0}]}
    assert json.loads(json.dumps(clean)) == clean



def test_index_worker_writes_result_after_timeout_and_rejects_parallel_retry(tmp_path):
    from database import Base
    from models import ResearchArtifact
    engine = create_engine(f'sqlite:///{tmp_path / "index.sqlite"}')
    Base.metadata.create_all(engine)
    release = threading.Event()
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    workflow._index_cleaned_facts = lambda *a: (release.wait(3) and 2)
    project = SimpleNamespace(id=1, title='测试', target_name='机器人', target_type='industry', industry='机器人')
    with Session(engine) as db:
        artifact = ResearchArtifact(project_id=1, artifact_type='cleaned_facts', title='事实', content='{"facts":[]}',
                                    artifact_metadata={'vector_index_status':'queued','markdown_object_key':'key'})
        db.add(artifact); db.commit(); db.refresh(artifact)
        workflow.start_artifact_index(db, project, artifact, wait_seconds=1)
        db.refresh(artifact)
        assert artifact.artifact_metadata['vector_index_status'] == 'background_timeout'
        with pytest.raises(ValueError, match='后台'):
            workflow.start_artifact_index(db, project, artifact)
        release.set()
        for _ in range(100):
            db.refresh(artifact)
            if artifact.artifact_metadata['vector_index_status'] == 'completed':break
            time.sleep(.01)
        assert artifact.artifact_metadata['vector_indexed_count'] == 2
        assert 'vector_index_error' not in artifact.artifact_metadata



def test_index_worker_persists_failure_for_independent_retry(tmp_path):
    from database import Base
    from models import ResearchArtifact
    engine = create_engine(f'sqlite:///{tmp_path / "failed.sqlite"}')
    Base.metadata.create_all(engine)
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    def fail(*a):raise RuntimeError('embedding unavailable')
    workflow._index_cleaned_facts = fail
    with Session(engine) as db:
        artifact = ResearchArtifact(project_id=1, artifact_type='cleaned_facts', title='事实', content='{"facts":[]}',
                                    artifact_metadata={'vector_index_status':'queued'})
        db.add(artifact);db.commit();db.refresh(artifact)
        workflow.start_artifact_index(db, SimpleNamespace(id=1), artifact, wait_seconds=2)
        db.refresh(artifact)
        assert artifact.artifact_metadata['vector_index_status']=='failed'
        assert 'embedding unavailable' in artifact.artifact_metadata['vector_index_error']



def test_retry_replaces_only_one_project_artifact_version(monkeypatch):
    import sys
    filters = []
    documents = []
    manager = SimpleNamespace(has_collection=lambda: True, delete=lambda expression: filters.append(expression))
    monkeypatch.setitem(sys.modules, 'milvus_writer', SimpleNamespace(MilvusWriter=lambda: SimpleNamespace(
        milvus_manager=manager, write_documents=lambda rows: documents.extend(rows))))
    project = SimpleNamespace(id=67, title='测试', target_name='机器人', target_type='industry', industry='机器人')
    count = ResearchWorkflow.__new__(ResearchWorkflow)._index_cleaned_facts(project, json.dumps({'facts':[{'fact':'机器人行业需求','source_url':'https://stats.gov.cn/report'}]}), 2, 'key')
    assert count == 1
    assert filters == ['project_id == 67 and artifact_type == "cleaned_facts" and artifact_version == 2']
    assert documents[0]['project_id'] == 67 and documents[0]['artifact_version'] == 2



def test_incomplete_embedding_batch_is_not_reported_as_success(monkeypatch):
    import sys
    import importlib.util
    from pathlib import Path
    monkeypatch.setitem(sys.modules, 'embedding', SimpleNamespace(EmbeddingService=object, embedding_service=None))
    monkeypatch.setitem(sys.modules, 'milvus_client', SimpleNamespace(MilvusManager=object))
    spec = importlib.util.spec_from_file_location('tested_milvus_writer', Path('backend/milvus_writer.py'))
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    embedding = SimpleNamespace(increment_add_documents=lambda rows:None, get_all_embeddings=lambda rows:([[1]], []))
    writer = module.MilvusWriter(embedding_service=embedding, milvus_manager=SimpleNamespace())
    with pytest.raises(RuntimeError, match='incomplete'):
        writer.write_documents([{'text':'fact'}])
