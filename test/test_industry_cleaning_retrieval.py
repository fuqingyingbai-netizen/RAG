"""Selection tests use injected vectors, original text and no network/DB."""
from copy import deepcopy
import hashlib
from threading import Event
from types import SimpleNamespace

import pytest

from industry_cleaning_retrieval import CleaningRetriever, cached_vectors, original_spans
from research_workflow import ResearchWorkflow


def source(body, **meta):
    return SimpleNamespace(id=19, title='合成行业资料', url='https://example.test/report', content=body,
        summary='SEARCH_SUMMARY_MUST_NOT_BE_USED', source_type='web', source_metadata={
            'module': '技术路线对比', 'industry_name': '机器人', **meta})


BODY = ('本文比较机器人系统，只讨论指定环境，不代表行业平均。\n'
        + '\n'.join('园区举办开放日，介绍展厅空间与活动安排，参观者可预约参观。' for _ in range(12))
        + '\n采用统一硬件及相同模型版本，测试负载为固定请求，延迟和单位成本分别记录，结果仅适用于本次测试。\n'
        + '端侧路线适用于离线场景，云端依赖持续联网，部署条件不同，不能直接认定普遍优劣。')


def test_keyword_fallback_finds_late_material_and_keeps_exact_offsets():
    s = source(BODY); before = deepcopy(s.__dict__)
    r = CleaningRetriever(dense=False); text = r.select(s, 240)
    assert '统一硬件' in text and 'SEARCH_SUMMARY' not in text
    audit = r.diagnostic()['sources'][0]
    assert audit['mode'] == 'bm25' and not audit['dense_applied']
    assert audit['body_sha256'] == hashlib.sha256(BODY.encode()).hexdigest()
    assert len(text) <= 240
    for span in audit['selected']:
        assert BODY[span['start']:span['end']] in text
    assert s.__dict__ == before


def test_dense_matching_is_fused_but_cannot_mark_evidence_verified():
    calls = []
    def embed(texts):
        calls.append(texts)
        return [[1.0, 0.0] if ('部署' in t or '路线' in t) else [0.0, 1.0] for t in texts]
    r = CleaningRetriever(embed=embed); text = r.select(source(BODY), 240)
    assert text and calls and r.audit[0]['dense_applied']
    assert r.audit[0]['role'] == 'extraction_candidates_not_verified_facts'
    assert r.diagnostic()['writes_approved_fact_index'] is False


def test_cache_reuses_vectors_by_content_and_model_namespace():
    calls = []
    def embed(texts): calls.append(texts); return [[1.0, 0.5] for _ in texts]
    first = cached_vectors(['alpha', 'beta'], embed, 'cache-test-v1')
    again = cached_vectors(['beta', 'alpha'], embed, 'cache-test-v1')
    changed = cached_vectors(['alpha'], embed, 'cache-test-v2')
    assert len(calls) == 2 and again[1] == 2 and first[0] == again[0] and changed[1] == 0


def test_dense_error_opens_run_circuit_and_keeps_keyword_material():
    calls = []
    def fail(texts): calls.append(1); raise RuntimeError('offline model unavailable')
    r = CleaningRetriever(embed=fail)
    a = r.select(source(BODY), 240); b = r.select(source(BODY), 240)
    assert '统一硬件' in a and '统一硬件' in b and calls == [1]
    assert r.circuit and r.audit[-1]['dense_error'] == 'circuit_open'


def test_timeout_does_not_queue_jobs_for_every_source():
    release = Event(); calls = []
    def slow(texts): calls.append(1); release.wait(2); return [[1.0] for _ in texts]
    r = CleaningRetriever(embed=slow, source_seconds=0.02)
    try:
        assert r.select(source(BODY), 240)
        assert r.select(source(BODY), 240)
        assert r.audit[0]['dense_error'] == 'timeout' and r.circuit and len(calls) == 1
    finally: release.set()


@pytest.mark.parametrize('values', [lambda texts: [], lambda texts: [[float('nan')]]*len(texts),
                                  lambda texts: [[1.0], [2.0, 3.0]]+[[1.0]]*(len(texts)-2)])
def test_bad_vectors_never_discard_original_material(values):
    r = CleaningRetriever(embed=values)
    assert '统一硬件' in r.select(source(BODY), 240)
    assert not r.audit[0]['dense_applied'] and r.circuit


@pytest.mark.parametrize('meta', [{'content_kind': 'summary_only'}, {'extraction_status': 'failed'}])
def test_search_summaries_and_failed_pages_never_enter_candidate_matrix(meta):
    def forbidden(texts): raise AssertionError('unapproved body used')
    r = CleaningRetriever(embed=forbidden)
    assert r.select(source(BODY, **meta), 240) == '' and not r.audit[0]['dense_applied']


def test_run_budget_exhaustion_uses_keyword_selection():
    def forbidden(texts): raise AssertionError('budget exceeded')
    r = CleaningRetriever(embed=forbidden, budget_seconds=-1)
    assert '统一硬件' in r.select(source(BODY), 240)
    assert r.audit[0]['dense_error'] == 'run_budget_exhausted'


def test_short_originals_are_kept_without_loading_any_model():
    def forbidden(texts): raise AssertionError('unneeded embedding')
    body = '仅在统一硬件下比较，样本结果不能外推其他设备。'
    r = CleaningRetriever(embed=forbidden)
    assert r.select(source(body), 200) == body and r.audit[0]['mode'] == 'whole_body'


def test_warmup_runs_once_and_is_part_of_the_shared_budget():
    calls = []
    def embed(texts): calls.append(texts); return [[1.0] for _ in texts]
    r = CleaningRetriever(embed=embed)
    r.warmup(); r.warmup()
    assert len(calls) == 1 and r.initialization['status'] == 'ready'


def test_source_context_uses_local_selector_without_changing_rule_cleaning_input():
    w = ResearchWorkflow.__new__(ResearchWorkflow)
    w._is_structured_professional_source = lambda s: False
    s = source(BODY); r = CleaningRetriever(dense=False)
    context = w._source_context([s], 240, industry=True, industry_retriever=r)
    assert '统一硬件' in context and s.content == BODY and 'SEARCH_SUMMARY' not in context


def test_local_embedding_path_requires_offline_loading_and_leaves_bm25_alone(tmp_path, monkeypatch):
    import embedding
    calls = []
    class Fake:
        def embed_documents(self, texts): return [[1.0, 0.5] for _ in texts]
    def factory(**kwargs): calls.append(kwargs); return Fake()
    monkeypatch.setattr(embedding, '_create_dense_embedder', factory)
    service = embedding.EmbeddingService(tmp_path/'sparse.json')
    assert service.get_local_embeddings(['a']) and service.get_local_embeddings(['b'])
    assert calls == [{'local_files_only': True}]
    assert service._total_docs == 0 and not (tmp_path/'sparse.json').exists()
