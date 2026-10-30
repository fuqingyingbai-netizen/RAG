"""Complete review coverage and bounded correction without real model calls."""
import json
from copy import deepcopy

import pytest

from industry_model_output import remaining_request_timeout, stage_timeout
from industry_reasoning import review_packet, validate_reviews, claim_id
from industry_research_stages import review_in_groups
from test_industry_reasoning import chain, review_claim, response, verdict


@pytest.mark.parametrize('shape', ['metadata','nested','encoded','preface'])
def test_complete_review_format_changes_preserve_exact_binding(shape):
    fact=chain(); claim=review_claim(fact)
    packet,_=review_packet([claim],[fact])
    value={'packet_fingerprint':packet['packet_fingerprint'],'reviews':[verdict(claim,fact)]}
    raw={'metadata':json.dumps({**value,'message':'presentation only'}),
         'nested':json.dumps({'data':value}),
         'encoded':json.dumps(json.dumps(value)),
         'preface':'复核结果如下：\n'+json.dumps(value)+'\n复核完成。'}[shape]
    diagnostic={}
    result=validate_reviews(raw,packet,diagnostic)
    assert result[claim['claim_id']]['status']=='supported'
    assert diagnostic['normalizations']
    assert result[claim['claim_id']]['entailment_proven'] is False


def test_review_wrapper_never_repairs_missing_binding_or_truncated_outer_json():
    f=chain(); c=review_claim(f); packet,_=review_packet([c],[f])
    valid={'packet_fingerprint':packet['packet_fingerprint'],'reviews':[verdict(c,f)]}
    for raw in [json.dumps({'data':valid})[:-1], json.dumps({'reviews':[verdict(c,f)]}),
                json.dumps(valid)+'\n'+json.dumps(valid),
                json.dumps({**valid,'data':valid}),
                json.dumps({'data':{**valid,'packet_fingerprint':'stale'}})]:
        result=validate_reviews(raw,packet)
        assert result[c['claim_id']]['status']=='not_evaluated'


def make_claims(count):
    f=chain(); claims=[]
    for i in range(count):
        c=review_claim(f, question=f'问题{i}',text=f['fact_contract']['statement']+f'本项研究主题{i}。')
        c['claim_id']=claim_id(c,2);claims.append(c)
    return f,claims


def complete(prompt):
    packet=json.loads(prompt.split('\n',1)[1].split('\n本组',1)[0])
    return json.dumps({'packet_fingerprint':packet['packet_fingerprint'],'reviews':[
        {'claim_id':c['claim_id'],'status':'supported','reason':'主体与所引原文保持一致且明确保留适用范围。',
         'quotes':[{'evidence_id':eid,'quote':packet['cards'][eid]['statement'][:35]} for eid in c['evidence_ids']]}
        for c in packet['claims']]})


def test_review_covers_later_chapters_instead_of_fixed_ten_claim_limit(monkeypatch):
    monkeypatch.delenv('INDUSTRY_REVIEW_MAX_REQUESTS',raising=False)
    f,claims=make_claims(16); calls=[]
    result=review_in_groups(claims,[f],lambda p:calls.append(p) or complete(p))
    assert len(calls)==4 and result['submitted_claim_count']==16
    assert result['valid_review_count']==16 and result['pending_claim_count']==0
    assert remaining_request_timeout() is None


def test_review_repairs_only_failed_units_after_covering_sibling_group(monkeypatch):
    monkeypatch.setenv('INDUSTRY_REVIEW_MAX_REQUESTS','3')
    f,claims=make_claims(6); calls=[]
    def invoke(prompt):
        calls.append(prompt)
        return '完整JSON尚未给出' if len(calls)==1 else complete(prompt)
    result=review_in_groups(claims,[f],invoke)
    assert len(calls)==3 and result['supported_claim_count']==6
    assert result['groups'][2]['format_retry']
    assert len(result['groups'][1]['submitted_claim_ids'])==1
    assert result['groups'][2]['submitted_claim_ids']==result['groups'][0]['submitted_claim_ids']
    assert 'invalid_review_json' in calls[-1]


def test_bounded_review_does_not_keep_retrying_or_promote_unknown(monkeypatch):
    monkeypatch.setenv('INDUSTRY_REVIEW_MAX_REQUESTS','2')
    monkeypatch.setenv('INDUSTRY_REVIEW_FORMAT_RETRIES','1')
    f,claims=make_claims(6); before=deepcopy(claims); calls=[]
    result=review_in_groups(claims,[f],lambda p:calls.append(p) or 'invalid')
    assert len(calls)==2 and result['pending_claim_count']==6
    assert not result['supported_claim_count'] and claims==before
    assert remaining_request_timeout() is None


def test_review_specific_timeout_can_be_extended_without_hidden_retries(monkeypatch):
    monkeypatch.delenv('INDUSTRY_WRITER_TIMEOUT_SECONDS',raising=False)
    monkeypatch.delenv('INDUSTRY_REVIEW_TIMEOUT_SECONDS',raising=False)
    assert stage_timeout('writer')==360 and stage_timeout('review')==240
    monkeypatch.setenv('INDUSTRY_REVIEW_TIMEOUT_SECONDS','500')
    assert stage_timeout('review')==500
