"""All retained values need a literal witness in each independent stage."""
from copy import deepcopy
import json

import pytest

from report_agents.company_presentation import (
    build_presentation, package_errors, retain_placement_answers, validate_batch,
)
from test_company_presentation import record, placements, TARGET, SCOPE


def rows():
    return [record('I-a',text='原文甲规定票数不得计入有表决权的股份总数。'),
            record('I-b',text='原文乙规定本次回购实施期限不超过十二个月。')]


@pytest.mark.parametrize('stage', ['proposal','review'])
def test_alternating_unbound_rows_keep_first_valid_answers_with_full_context(stage):
    native=rows();usage={'records':native};before=deepcopy(usage);calls=[];responses=[];counts={}
    def invoke(role,prompt,trace):
        current='review' if role.endswith('独立审稿') else 'proposal'
        counts[current]=counts.get(current,0)+1
        calls.append((current,prompt))
        assert all(row['text'] in prompt for row in native)  # no source or context truncation
        answer=placements(native)
        for item in answer['records']:item['reason']=('首轮独有候选理由需要保留原文核对。' if current=='proposal' else '独立轮原件核对的取舍理由完整保留。')
        if current=='review':assert '首轮独有候选理由' not in prompt
        if current==stage:
            index=0 if counts[current]==1 else 1
            answer['records'][index]['source_excerpt']='该条中不存在的改写内容不能作为引文。'
        responses.append(deepcopy(answer))
        return json.dumps(answer,ensure_ascii=False)
    result=build_presentation(usage,TARGET,SCOPE,invoke,workers=1)
    assert len(calls)==3 and counts[stage]==2
    assert result['batches'][0]['accepted'] is True
    assert not package_errors(result,usage,TARGET,SCOPE)
    assert usage==before
    batch=result['batches'][0]
    assert batch['retained_stage_answers'] is True
    assert [attempt['response'] for attempt in batch['attempts']]==responses
    stage_attempts=[attempt['response'] for attempt in batch['attempts'] if attempt['stage']==stage]
    assert batch[stage]['records'][0]==stage_attempts[1]['records'][0]
    assert batch[stage]['records'][1]==stage_attempts[0]['records'][1]


@pytest.mark.parametrize('defect',['missing','duplicate','unknown','malformed','unhashable'])
def test_omitted_unknown_duplicate_and_malformed_values_supply_no_answer_for_that_id(defect):
    native=rows();answer=placements(native)
    if defect=='missing':answer['records'].pop()
    elif defect=='duplicate':answer['records'][1]=deepcopy(answer['records'][0])
    elif defect=='unknown':answer['records'][1]['information_id']='I-other'
    elif defect=='malformed':answer['records'][1]='not a record'
    else:answer['records'][1]['information_id']=['I-b']
    retained=retain_placement_answers(native,answer)
    assert set(retained)==({'I-a'} if defect in {'missing','unknown'} else set())
    assert 'I-b' not in retained
    package=build_presentation({'records':native},TARGET,SCOPE,lambda *args:json.dumps(answer),workers=1)
    assert package['batches'][0]['accepted'] is False
    assert set(package['diagnostic']['pending_information_ids'])=={'I-a','I-b'}


@pytest.mark.parametrize('stage',['proposal','review'])
def test_omitted_ids_stay_pending_until_a_fresh_full_context_response_supplies_them(stage):
    native=rows();counts={};calls=[]
    def invoke(role,prompt,trace):
        current='review' if role.endswith('独立审稿') else 'proposal'
        counts[current]=counts.get(current,0)+1;answer=placements(native);calls.append(prompt)
        assert all(row['text'] in prompt for row in native)
        if current==stage:answer['records'].pop(0 if counts[current]==1 else 1)
        return json.dumps(answer,ensure_ascii=False)
    package=build_presentation({'records':native},TARGET,SCOPE,invoke,workers=1)
    assert len(calls)==3 and package['batches'][0]['accepted'] is True
    assert not package_errors(package,{'records':native},TARGET,SCOPE)


def test_wrong_glyphs_and_short_quotes_are_never_repaired_or_borrowed():
    native=rows();answer=placements(native)
    answer['records'][0]['source_excerpt']='票數不得計入有表決權的股份總數'
    answer['records'][1]['source_excerpt']='不超过十二个月'
    before=deepcopy(answer)
    assert retain_placement_answers(native,answer)=={}
    assert answer==before


def test_one_permanently_unbound_review_row_still_blocks_the_whole_batch():
    native=rows();calls=[]
    def invoke(role,prompt,trace):
        calls.append(role);answer=placements(native)
        if role.endswith('独立审稿'):answer['records'][0]['source_excerpt']=native[1]['text']
        return json.dumps(answer,ensure_ascii=False)
    result=build_presentation({'records':native},TARGET,SCOPE,invoke,workers=1)
    assert calls.count('公司交付正文取舍独立审稿')==3
    assert result['batches'][0]['accepted'] is False
    assert set(result['diagnostic']['pending_information_ids'])=={'I-a','I-b'}
    assert not result['main_information_ids'] and not result['evidence_information_ids']
    assert package_errors(result,{'records':native},TARGET,SCOPE)


@pytest.mark.parametrize('tamper',['answer','witness','missing_witness'])
def test_cached_retained_answers_must_reconstruct_from_their_original_stage_responses(tamper):
    native=rows()
    result=build_presentation({'records':native},TARGET,SCOPE,lambda *args:json.dumps(placements(native)),workers=1)
    batch=deepcopy(result['batches'][0]);assert not validate_batch(native,batch)[1]
    if tamper=='answer':batch['review']['records'][0]['reason']='改写后的理由即使看似合理也不是实际模型见证。'
    elif tamper=='witness':batch['attempts'][-1]['response']['records'][0]['source_excerpt']='另一个来源才有的引文。'
    else:batch['attempts'][-1].pop('response')
    assert any(error.startswith('placement_retained_witness_') for error in validate_batch(native,batch)[1])


def test_valid_legacy_receipts_without_retention_metadata_still_require_full_validation():
    native=rows();usage={'records':native}
    old=build_presentation(usage,TARGET,SCOPE,lambda *args:json.dumps(placements(native)),workers=1)
    for batch in old['batches']:
        batch.pop('retained_stage_answers')
        for attempt in batch['attempts']:
            attempt.pop('response');attempt.pop('response_errors')
    def unexpected(*args):raise AssertionError('valid unchanged legacy receipt must be reused')
    resumed=build_presentation(usage,TARGET,SCOPE,unexpected,previous=old,workers=1)
    assert resumed['batches'][0]['reused'] is True
    assert not package_errors(resumed,usage,TARGET,SCOPE)


def test_retention_preserves_core_and_independent_disagreement_main_promotions():
    native=rows();native[0]['context'].update(kind='financial_metric');calls={}
    def invoke(role,prompt,trace):
        stage='review' if role.endswith('独立审稿') else 'proposal'
        calls[stage]=calls.get(stage,0)+1;answer=placements(native)
        if stage=='proposal':answer['records'][1]['surface']='main'
        if stage=='review':
            answer['records'][0 if calls[stage]==1 else 1]['source_excerpt']='不属于这条原文的内容。'
        return json.dumps(answer,ensure_ascii=False)
    result=build_presentation({'records':native},TARGET,SCOPE,invoke,workers=1)
    assert set(result['main_information_ids'])=={'I-a','I-b'}
    assert not package_errors(result,{'records':native},TARGET,SCOPE)


@pytest.mark.parametrize('stage',['proposal','review'])
@pytest.mark.parametrize('first_surface',['main','evidence'])
def test_any_bound_main_answer_survives_same_stage_retry_disagreement(stage,first_surface):
    native=rows();counts={}
    def invoke(role,prompt,trace):
        current='review' if role.endswith('独立审稿') else 'proposal'
        counts[current]=counts.get(current,0)+1;answer=placements(native)
        if current==stage:
            answer['records'][1]['surface']=first_surface if counts[current]==1 else ('evidence' if first_surface=='main' else 'main')
            if counts[current]==1:answer['records'][0]['source_excerpt']='原文并未记载这句话。'
        return json.dumps(answer,ensure_ascii=False)
    package=build_presentation({'records':native},TARGET,SCOPE,invoke,workers=1)
    assert package['batches'][0][stage]['records'][1]['surface']=='main'
    assert 'I-b' in package['main_information_ids']
    assert not package_errors(package,{'records':native},TARGET,SCOPE)
