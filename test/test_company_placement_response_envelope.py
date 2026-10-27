"""Envelope compatibility never supplies a placement or a review verdict."""
from copy import deepcopy
import json

import pytest

from report_agents.company_editorial import parse_json_response
from report_agents.company_presentation import (
    parse_placement_response, validate_placements, build_presentation, package_errors,
)
from test_company_presentation import record, placements, TARGET, SCOPE


@pytest.mark.parametrize('envelope', ['object','array','fenced_array','json_label_array'])
def test_complete_envelopes_keep_every_record_and_exact_native_quote(envelope):
    rows=[record(text='原文保留人民幣934.2百萬元和申请状态，不能改写。')]
    answer=placements(rows);before=deepcopy(answer)
    raw=json.dumps(answer if envelope=='object' else answer['records'],ensure_ascii=False)
    if envelope=='fenced_array':raw='```json\n'+raw+'\n```'
    if envelope=='json_label_array':raw='JSON\n'+raw
    parsed=parse_placement_response(raw)
    assert parsed==before and not validate_placements(rows,parsed)[1]
    assert answer==before


@pytest.mark.parametrize('raw', ['null','true','42','"text"','[{"source原文"}]','[{"information_id":"I-a"}'])
def test_scalars_and_broken_json_are_not_repaired(raw):
    with pytest.raises((ValueError,TypeError)):
        parse_placement_response(raw)


@pytest.mark.parametrize('defect', ['missing','duplicate','wrong_quote','wrong_id','nested'])
def test_array_wrapper_cannot_cover_missing_ids_or_unbound_text(defect):
    rows=[record('I-a',text='本条原文记载了金额与生效条件，须保留原字。'),
          record('I-b',text='另一条原文记录日期和主体，不可相互借用。')]
    values=placements(rows)['records']
    if defect=='missing':values.pop()
    elif defect=='duplicate':values[1]=deepcopy(values[0])
    elif defect=='wrong_quote':values[0]['source_excerpt']=rows[1]['text']
    elif defect=='wrong_id':values[0]['information_id']='I-other'
    elif defect=='nested':values=[{'records':values}]
    answer=parse_placement_response(json.dumps(values,ensure_ascii=False))
    assert validate_placements(rows,answer)[1]


def test_array_support_is_scoped_to_placement_not_factual_audits():
    with pytest.raises(ValueError,match='not_json_object'):
        parse_json_response('[{"status":"supported"}]')


@pytest.mark.parametrize('second_valid', [True,False])
def test_normal_workflow_still_needs_a_fresh_source_bound_second_read(second_valid):
    rows=[record(text='章程规定会议记录应由与会人员签名，原文完整保留。')]
    calls=[]
    def invoke(role,prompt,trace):
        calls.append(role);answer=placements(rows)
        if role.endswith('独立审稿') and not second_valid:
            answer['records'][0]['source_excerpt']='另一份文档的文本，不能作为这条原文的定位。'
        return json.dumps(answer['records'],ensure_ascii=False)
    package=build_presentation({'records':rows},TARGET,SCOPE,invoke,workers=1)
    assert calls[0]=='公司交付正文取舍'
    assert calls.count('公司交付正文取舍独立审稿')==(1 if second_valid else 3)
    if second_valid:
        assert not package_errors(package,{'records':rows},TARGET,SCOPE)
        assert package['batches'][0]['accepted'] is True
    else:
        assert package['batches'][0]['accepted'] is False
        assert package['diagnostic']['pending_information_ids']==[rows[0]['information_id']]


def test_valid_existing_object_receipts_remain_reusable_with_full_validation():
    rows=[record()]
    old=build_presentation({'records':rows},TARGET,SCOPE,
        lambda *args:json.dumps(placements(rows)),workers=1)
    def unavailable(*args):raise AssertionError('Unchanged validated object receipt must not call the model again.')
    resumed=build_presentation({'records':rows},TARGET,SCOPE,unavailable,previous=old,workers=1)
    assert resumed['batches'][0]['reused'] is True
    assert not package_errors(resumed,{'records':rows},TARGET,SCOPE)
