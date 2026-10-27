import pytest
from person_source_boundaries import joint_participant_duplicate_errors


@pytest.mark.parametrize('a,b,c',[('陈安','李宁','周明'),('欧阳清和','司徒静','陈雨安'),('Alex Morgan','Emma Lee','Sam Taylor')])
def test_named_spouse_stays_in_the_couple_instead_of_becoming_extra_participant(a,b,c):
    facts=[{'fact':f'在离开之前，{a}协同妻子{b}以及{c}转让股权。'}]
    assert joint_participant_duplicate_errors(f'{a}夫妇、{b}、{c}转让股权。',facts)==['joint_participant_repeated']
    assert joint_participant_duplicate_errors(f'{b}及{a}夫妻共同转让股权。',facts)==['joint_participant_repeated']
    assert not joint_participant_duplicate_errors(f'{a}夫妇（配偶为{b}）以及{c}转让股权。',facts)
    assert not joint_participant_duplicate_errors(f'{a}与{b}及{c}转让股权。',facts)


def test_names_are_not_inferred_to_be_spouses_from_adjacent_mentions():
    facts=[{'fact':'陈安与李宁以及周明共同转让股权。'}]
    assert not joint_participant_duplicate_errors('陈安夫妇、李宁转让股权。',facts)
