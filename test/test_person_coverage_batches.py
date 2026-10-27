import json
import pytest
from person_content_acceptance import check_coverage


def fixture(count=8,chars=40):
    facts=[{'evidence_id':f'E-P{i}','fact':f'林知远于20{i:02d}年负责研发管理。'+'甲'*chars,
            'source_url':f'https://fixture.invalid/{i}','subject':'林知远','analysis_allowed':True} for i in range(count)]
    p={'chapter':5,'title':'研发管理','facts':facts,'research_facts':facts,'structured_tables':[]}
    prior=[{'analysis':f'林知远于20{i:02d}年负责研发管理。','evidence_ids':[f'E-P{i}']} for i in range(count)]
    return p,prior


def missing_reply(packet):
    return json.dumps({'reviews':[{'prior_index':i,'verdict':'missing','matched_claim_indices':[],
        'gaps':[{'prior_quote':row['analysis'],'evidence_ids':row['evidence_ids']}],'reason':'当前正文没有该项原有实质事项。'} for i,row in enumerate(packet['prior'])]},ensure_ascii=False)


def test_eight_independent_source_questions_use_two_real_requests(monkeypatch):
    monkeypatch.setenv('PERSON_CONTENT_COVERAGE_BATCH_SIZE','4');p,prior=fixture();calls=[]
    def invoke(role,prompt,*args):
        packet=json.loads(prompt.splitlines()[-1]);calls.append(packet)
        assert packet['prior_index_map']==[{'prior_index':i,**r} for i,r in enumerate(packet['prior'])]
        return missing_reply(packet)
    result=check_coverage(p,[],prior,invoke,None)
    assert len(calls)==result['requests']==2
    assert [r['prior_index'] for r in result['items']]==list(range(8))
    assert all(r['status']=='missing' and r['gaps'][0]['prior_quote']==prior[i]['analysis'] for i,r in enumerate(result['items']))
    assert [r['prior_indices'] for r in result['per_item_checks']]==[[0,1,2,3],[4,5,6,7]]


def test_exact_retained_questions_do_not_shift_global_indices(monkeypatch):
    monkeypatch.setenv('PERSON_CONTENT_COVERAGE_BATCH_SIZE','4');p,prior=fixture(6);calls=[]
    def invoke(role,prompt,*args):
        packet=json.loads(prompt.splitlines()[-1]);calls.append(packet);return missing_reply(packet)
    result=check_coverage(p,[prior[0],prior[2]],prior,invoke,None)
    assert len(calls)==1 and [r['status'] for r in result['items']]==['covered','missing','covered','missing','missing','missing']
    assert result['items'][5]['gaps'][0]['prior_quote']==prior[5]['analysis']


@pytest.mark.parametrize('reply',['empty','partial'])
def test_unreturned_batch_members_stay_pending_after_two_attempts(monkeypatch,reply):
    monkeypatch.setenv('PERSON_CONTENT_COVERAGE_BATCH_SIZE','4');p,prior=fixture(4);calls=[]
    def invoke(role,prompt,*args):
        calls.append(prompt)
        if reply=='empty':return ''
        data=json.loads(missing_reply(json.loads(prompt.splitlines()[-1])));data['reviews']=data['reviews'][:1];return json.dumps(data)
    result=check_coverage(p,[],prior,invoke,None)
    assert len(calls)==2 and result['status']=='pending_review'
    assert len(result['items'])==4 and not any(r['status']=='covered' for r in result['items'])
    assert all(r['status']=='pending_review' for r in result['items'][1:])


def test_source_size_splits_questions_without_truncating_originals(monkeypatch):
    monkeypatch.setenv('PERSON_CONTENT_COVERAGE_BATCH_SIZE','4');p,prior=fixture(3,chars=9000);calls=[]
    def invoke(role,prompt,*args):
        packet=json.loads(prompt.splitlines()[-1]);calls.append(packet)
        assert len(packet['prior'])==1 and len(packet['sources'][0]['original'])>9000
        return missing_reply(packet)
    result=check_coverage(p,[],prior,invoke,None)
    assert result['requests']==len(calls)==3
