import pytest

from person_model_transport import EmptyPersonModelResponse, invoke_same_input, section_model_options, section_model_context
from person_material_review import material_batches


@pytest.mark.parametrize('failure', ['RemoteProtocolError', 'ReadError'])
def test_stream_disconnect_retries_identical_input_once_and_never_adopts_partial_text(failure):
    import httpx
    calls, audit = [], {}
    def invoke(*args):
        calls.append(args)
        raise getattr(httpx, failure)('incomplete response body')
    with pytest.raises(getattr(httpx, failure)):
        invoke_same_input(invoke, 'writer', 'full original input', None, audit, 'transport')
    assert len(calls) == 2 and calls[0] == calls[1]
    assert audit['transport']['exhausted'] is True
    assert [row['status'] for row in audit['transport']['attempts']] == ['failed', 'failed']


def test_empty_length_response_is_not_retried_as_network_failure():
    calls, audit = [], {}
    def invoke(*args):
        calls.append(args)
        raise EmptyPersonModelResponse('empty_model_final_content:length', finish_reason='length')
    with pytest.raises(EmptyPersonModelResponse):
        invoke_same_input(invoke, 'review', 'unchanged full input', None, audit, 'transport')
    assert len(calls) == 1
    assert audit['transport']['exhausted'] is True
    assert audit['transport']['attempts'][0]['failure_kind'] == 'model_output_exhausted'


def test_unknown_empty_response_can_still_have_the_existing_bounded_transient_retry():
    calls, audit = [], {}
    def invoke(*args):
        calls.append(args)
        if len(calls) == 1:
            raise EmptyPersonModelResponse('empty_model_final_content:unknown')
        return 'actual returned answer'
    assert invoke_same_input(invoke, 'review', 'same input', None, audit, 'transport') == 'actual returned answer'
    assert len(calls) == 2


def test_smaller_partitions_keep_every_original_record_and_its_order():
    rows = [{'evidence_id': str(n), 'original': ('甲' * (700 + n * 10))} for n in range(40)]
    batches = material_batches(rows, 4000)
    assert [row for batch in batches for row in batch] == rows
    assert len(batches) > len(material_batches(rows, 14000))


def test_qwen_default_is_preserved_and_explicit_thinking_change_invalidates_context(monkeypatch):
    monkeypatch.setenv('MODEL', 'qwen3.8-max')
    monkeypatch.delenv('PERSON_REPORT_SECTION_MODEL', raising=False)
    monkeypatch.delenv('PERSON_REPORT_QWEN_THINKING', raising=False)
    baseline = section_model_context()
    assert 'extra_body' not in baseline['request_options']
    monkeypatch.setenv('PERSON_REPORT_QWEN_THINKING', 'disabled')
    changed = section_model_context()
    assert changed['request_options']['extra_body'] == {'enable_thinking': False}
    assert changed != baseline
    assert 'extra_body' not in section_model_options('unrelated-model')
    monkeypatch.setenv('PERSON_REPORT_QWEN_THINKING', 'enabled')
    assert section_model_options('qwen3.8-max')['extra_body']['enable_thinking'] is True
    monkeypatch.setenv('PERSON_REPORT_QWEN_THINKING', 'unsupported')
    with pytest.raises(ValueError, match='invalid_person_qwen_thinking_mode'):
        section_model_options('qwen3.8-max')


def test_streaming_transport_is_explicit_and_is_part_of_the_model_context(monkeypatch):
    monkeypatch.setenv('MODEL', 'qwen3.8-max')
    monkeypatch.delenv('PERSON_REPORT_SECTION_MODEL', raising=False)
    monkeypatch.delenv('PERSON_REPORT_SECTION_STREAMING', raising=False)
    before = section_model_context()
    assert 'streaming' not in before['request_options']
    monkeypatch.setenv('PERSON_REPORT_SECTION_STREAMING', 'true')
    after = section_model_context()
    assert after != before and after['request_options']['streaming'] is True
    monkeypatch.setenv('PERSON_REPORT_SECTION_STREAMING', 'invalid')
    with pytest.raises(ValueError, match='invalid_person_section_streaming_mode'):
        section_model_options('qwen3.8-max')
