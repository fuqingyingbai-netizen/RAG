"""Actor scope is independent of the target name; originals stay intact."""
import pytest
from person_source_boundaries import collective_retirement_scope_errors


SOURCE='我们四个人都担心学习能力跟不上，所以他决定在10年到15年内会退休。我们四个会把积分最高的那批人找出来，长时间观察，择优录取。'


@pytest.mark.parametrize('text', [
    '林知远等四人拟10至15年内退休。',
    '四人拟10-15年内退休。',
    '其与陈晨、李峰、周敏因忧学习能力跟不上，拟10至15年内退休。',
    '另一目标等4人计划10到15年内退休。'])
def test_singular_decision_cannot_be_inherited_by_group(text):
    supports=[{'fact': SOURCE}]
    assert collective_retirement_scope_errors(text,supports)==['collective_retirement_scope_expanded']
    assert supports[0]['fact']==SOURCE


@pytest.mark.parametrize('text', [
    '四人共同担心学习能力跟不上，因此他决定10至15年内退休。',
    '其拟10至15年内退休，四人将长期观察接班候选人。',
    '四人担忧，他计划10至15年内退休。',
    '其与陈晨、李峰、周敏担心学习跟不上，所以他决定10至15年内退休。',
    '不能将其个人退休计划扩大为四人共同退休。'])
def test_actual_singular_scope_and_explicit_limit_are_allowed(text):
    assert not collective_retirement_scope_errors(text,[{'fact': SOURCE}])


def test_direct_cited_collective_plan_remains_usable():
    assert not collective_retirement_scope_errors('四人拟10至15年内退休。',[
        {'fact': SOURCE},{'fact': '他们四人决定在10年到15年内退休。'}])


def test_absent_singular_contradiction_is_left_to_semantic_review():
    assert not collective_retirement_scope_errors('四人拟退休。',[{'fact':'四人共同拟定了接班人的选拔制度。'}])
