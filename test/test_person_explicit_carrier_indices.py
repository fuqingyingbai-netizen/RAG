"""Offline receipt labels clarify positions without accepting wrong indices."""
import json
import person_content_acceptance as acceptance
from test_person_content_acceptance import fixture


def test_explicit_index_map_preserves_exact_plain_draft_checkpoint_payload():
    p,old,current=fixture();seen=[]
    def invoke(role,prompt,*args):
        packet=json.loads(prompt.splitlines()[-1]);seen.append(packet)
        assert packet['draft']==old
        assert packet['draft_index_map']==[{'claim_index':0,**old[0]}]
        return json.dumps({'reviews':[{'prior_index':0,'verdict':'covered',
            'matched_claim_indices':[packet['draft_index_map'][0]['claim_index']],
            'gaps':[],'reason':'实际正文逐字承接'}]})
    review=acceptance._check_one(p,old,old,invoke,None)
    assert review['status']=='passed' and len(seen)==1


def test_explicit_labels_never_coerce_one_based_or_out_of_range_matches():
    p,old,current=fixture()
    response={'reviews':[{'prior_index':0,'verdict':'covered','matched_claim_indices':[1],
        'gaps':[],'reason':'错误地使用一起编号'}]}
    review=acceptance._check_one(p,old,old,lambda *a:json.dumps(response),None)
    assert review['status']=='pending_review' and review['items'][0]['status']!='covered'


def test_material_review_uses_the_same_explicit_carrier_labels():
    from person_material_accounting import diagnose_material
    facts=[{'evidence_id':f'E-PINDEX{i}','fact':f'林知远负责研发事项{i}。',
        'source_url':f'https://fixture.invalid/{i}','analysis_allowed':True,'subject_scope':'person'} for i in range(2)]
    claims=[{'analysis':f['fact'],'evidence_ids':[f['evidence_id']]} for f in facts];seen=[]
    def invoke(role,prompt,*args):
        packet=json.loads(prompt.splitlines()[-1]);seen.append(packet)
        assert packet['draft']==claims
        assert packet['draft_index_map']==[{'claim_index':i,**r} for i,r in enumerate(claims)]
        return json.dumps({'material_reviews':[{'evidence_id':f['evidence_id'],'disposition':'analysis',
            'matched_claim_indices':[i],'reason':'对应研发职责已经由实际分析逐字保留'} for i,f in enumerate(facts)]})
    result=diagnose_material({'chapter':4,'title':'战略','facts':facts},claims,invoke,None)
    assert result['status']=='passed' and len(seen)==1
