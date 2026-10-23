import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('person_iteration', Path(__file__).resolve().parents[1] / 'scripts/person_iteration.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_exact_input_reuse_prevents_unrelated_paid_rewrites(tmp_path):
    old, new = tmp_path / 'old', tmp_path / 'new'
    old.mkdir(); new.mkdir()
    calls = []
    def invoke(role, prompt, emit=None):
        calls.append(prompt)
        return '{"claims":[]}'
    writer = module.ChapterInvoker(invoke, old)
    for chapter in [2, 4, 7, 13, 1]:
        writer(str(chapter), f'人物背景调查第{chapter}章：旧输入')
    calls.clear()
    writer = module.ChapterInvoker(invoke, new, reuse=old, rewrite=[7])
    for chapter in [2, 4, 7, 13, 1]:
        writer(str(chapter), f'人物背景调查第{chapter}章：旧输入')
    assert len(calls) == 3  # Chapter7 plus its summary and assessment dependencies.
    assert sum(e['status'] == 'exact_input_reused' for e in writer.events) == 2
    with pytest.raises(RuntimeError, match='outside'):
        writer('4', '人物背景调查第4章：来源已经发生变化')
    assert len(calls) == 3


def test_deadline_blocks_new_calls_but_allows_exact_cached_responses(tmp_path):
    writer = module.ChapterInvoker(lambda *a: pytest.fail('No paid request is allowed'), tmp_path,
                                   deadline='2000-01-01T00:00:00Z')
    with pytest.raises(RuntimeError, match='budget exhausted'):
        writer('2', '人物背景调查第2章：未跑输入')
    assert writer.events[-1]['status'] == 'time_budget_exhausted'


def test_response_with_different_input_hash_is_never_reused(tmp_path):
    old, new = tmp_path / 'old', tmp_path / 'new'
    old.mkdir(); new.mkdir()
    (old / 'chapter-model-inputs.jsonl').write_text(json.dumps({'role': 'r', 'prompt': '人物背景调查第2章：版本甲'}), encoding='utf-8')
    (old / 'chapter-model-responses.jsonl').write_text(json.dumps({'role': 'r', 'response': 'old answer', 'input_sha256': 'wrong'}), encoding='utf-8')
    writer = module.ChapterInvoker(lambda *a: 'new answer', new, reuse=old, rewrite=[2])
    assert writer('r', '人物背景调查第2章：版本甲') == 'new answer'


@pytest.mark.parametrize('new_context', [{'model':'new','endpoint_sha256':'a'}, {'model':'old','endpoint_sha256':'b'}, None])
def test_explicit_service_context_prevents_cross_provider_response_reuse(tmp_path, new_context):
    old, new = tmp_path/'old', tmp_path/'new'
    old.mkdir(); new.mkdir()
    previous_context = {'model':'old','endpoint_sha256':'a'}
    writer = module.ChapterInvoker(lambda *a: 'old answer', old, model_context=new_context)
    writer('r', '相同输入')
    calls = []
    writer = module.ChapterInvoker(lambda *a: calls.append(a) or 'new answer', new,
        reuse=old, model_context=previous_context)
    assert writer('r', '相同输入') == 'new answer'
    assert len(calls) == 1


def test_matching_service_context_can_reuse_successful_exact_input(tmp_path):
    old, new = tmp_path/'old', tmp_path/'new'
    old.mkdir(); new.mkdir()
    context = {'model':'same','endpoint_sha256':'same'}
    module.ChapterInvoker(lambda *a: 'answer',old,model_context=context)('r','相同输入')
    writer = module.ChapterInvoker(lambda *a: pytest.fail('Should reuse'),new,reuse=old,model_context=context)
    assert writer('r','相同输入') == 'answer'


def test_original_object_tree_copy_preserves_bytes_and_existing_archive(tmp_path):
    source, destination = tmp_path/'originals', tmp_path/'archive'
    nested = source/'projects'/'1'/('a'*90)/('b'*90)
    # Test fixtures also need the extended-path spelling on Windows.
    import os
    path = '\\\\?\\' + str(nested.resolve()) if os.name == 'nt' else str(nested)
    Path(path).mkdir(parents=True)
    (Path(path)/'raw.json').write_bytes(b'{"original":true}')
    destination.mkdir()
    (destination/'older.txt').write_text('keep', encoding='utf-8')
    module.copy_retained_tree(source, destination)
    output = destination/'projects'/'1'/('a'*90)/('b'*90)/'raw.json'
    actual = Path('\\\\?\\' + str(output.resolve())) if os.name == 'nt' else output
    assert actual.read_bytes() == b'{"original":true}'
    assert (destination/'older.txt').read_text(encoding='utf-8') == 'keep'
