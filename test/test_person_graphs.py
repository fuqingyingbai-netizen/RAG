import json
from types import SimpleNamespace
from person_graphs import graph_nodes


def test_person_graph_uses_selected_actor_rows_and_never_fills_with_page_fragments():
    selected={'fact':'林知远 董事长 恒川软件有限公司 董事 本公司合营企业 远山慈善基金会 理事 无关联关系',
        'subject_scope':'person','literal_roster_row':True,'evidence_id':'E-PSELECTED'}
    p=SimpleNamespace(target_name='林知远',person_research_intake={'person_anchor':{'known_affiliations':['恒川软件有限公司']}},
        person_evidence_contract={'chapters':{9:{'facts':[selected]}}})
    raw={'facts':[{'fact':'林知远与陈雨安共同创业，陈雨安担任远山投资有限公司董事长，负责本集团事务。'}]}
    nodes=graph_nodes(p,json.dumps(raw))
    assert {n[0] for n in nodes}=={'恒川软件有限公司','远山慈善基金会'}
    assert all('待核验' in r and eid=='E-PSELECTED' for _,r,eid in nodes)
    assert p.person_relationship_graph_audit['basis']=='chapter9_selected_source_statements'


def test_two_adjacent_entities_are_not_concatenated_into_a_fake_organization():
    f={'fact':'林知远 董事长，并担任恒川软件有限公司董事及远山慈善基金会理事。',
       'subject_scope':'person','literal_roster_row':True,'evidence_id':'E-PSELECTED'}
    p=SimpleNamespace(target_name='林知远',person_evidence_contract={'chapters':{9:{'facts':[f]}}})
    names=[n for n,_,_ in graph_nodes(p,'{}')]
    assert '恒川软件有限公司' in names
    assert not any('有限公司董事及' in n for n in names)
