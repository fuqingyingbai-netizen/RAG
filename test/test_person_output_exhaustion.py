import pytest

from person_model_transport import EmptyPersonModelResponse, invoke_same_input
from person_material_review import material_batches


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
