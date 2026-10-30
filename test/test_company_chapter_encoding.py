"""Normalize only canonical numeric chapter encoding; retain every evidence gate."""
from copy import deepcopy
import hashlib
import json

import pytest

from report_agents.company_corpus import prepare_corpus,build_corpus_review,_batches
from report_agents.company_source_review import validate_selection
from test_company_corpus import TARGET,source,project


def prepared():
    p=project([source()]);documents,_,_=prepare_corpus(p,{})
    doc=documents[0]
    row=dict(evidence_id=doc['evidence_id'],window_id=doc['windows'][0]['window_id'],
             chapter=2,scope='target',relevance='登记字段按平台原文归因')
    return p,doc,row


def test_canonical_numeric_string_preserves_literal_and_records_encoding_correction():
    _,doc,row=prepared();lookup={doc['evidence_id']:doc}
    normal,error=validate_selection(row,lookup,TARGET)
    encoded,error2=validate_selection({**row,'chapter':'2'},lookup,TARGET)
    assert not error and not error2
    assert {k:v for k,v in encoded.items() if k!='selection_corrections'}=={
        k:v for k,v in normal.items() if k!='selection_corrections'}
    assert encoded['selection_corrections']==[dict(field='chapter',proposed='2',accepted=2,
        reason='canonical_numeric_chapter_encoding')]


@pytest.mark.parametrize('chapter',['02','2.0',' 2 ','+2','2x','12',2.0,True,None,[]])
def test_noncanonical_types_and_unsupported_chapters_are_still_rejected(chapter):
    _,doc,row=prepared()
    assert validate_selection({**row,'chapter':chapter},{doc['evidence_id']:doc},TARGET)[1]=='invalid_chapter'


def test_type_normalization_cannot_change_routing_or_create_missing_source_window_or_scope():
    _,doc,row=prepared();lookup={doc['evidence_id']:doc}
    for changes in [dict(chapter='5'),dict(evidence_id='E-FFFFFFFFFFFF'),dict(window_id='W999'),
                    dict(scope='invented_scope')]:
        assert validate_selection({**row,'chapter':'2',**changes},lookup,TARGET)[0] is None


def propose(chapter):
    def invoke(role,prompt,trace):
        docs=json.loads(prompt.split('资料：\n',1)[1])['originals']
        return json.dumps({'decisions':[dict(evidence_id=d['evidence_id'],disposition='accepted') for d in docs],
            'facts':[dict(evidence_id=d['evidence_id'],window_id=w['window_id'],chapter=chapter,
                scope='target',relevance='原始登记字段') for d in docs for w in d['windows']]})
    return invoke


def test_rejected_selection_is_not_misclassified_as_no_relevant_claim():
    p,doc,_=prepared()
    result=build_corpus_review(p,{}, {},propose('02'),lambda *a,**k:None)
    assert not result['facts']
    assert result['source_review']['1']['state']=='reviewed_selections_rejected'
    assert '不代表没有找到资料' in result['source_review']['1']['reason']
    assert result['source_review']['1']['validation_rejections']==['invalid_chapter']
    assert result['rejected_selections']==[dict(evidence_id=doc['evidence_id'],window_id='W1',
        proposed_chapter='02',reason='invalid_chapter')]


def test_v11_raw_string_proposal_is_revalidated_without_modifying_receipt_or_requesting_again():
    p,_,_=prepared();result=build_corpus_review(p,{}, {},propose('2'),lambda *a,**k:None)
    old=deepcopy(result);old['version']='company-corpus-v11-bounded-industry-and-standard-roles'
    old['facts']=[]  # The old strict type check rejected this real proposal shape.
    batch=list(_batches(prepare_corpus(p,{})[0]))[0]
    old['review_receipts'][0]['input_sha256']=hashlib.sha256((old['version']+'\n'+TARGET+'\n2026-10-20\n'+
        json.dumps(batch,ensure_ascii=False,sort_keys=True)).encode()).hexdigest()
    raw=deepcopy(old['review_receipts'][0]['response']);p.company_corpus_analysis_cache=old
    def no_request(*a):raise AssertionError('Same raw proposal should be revalidated locally')
    current=build_corpus_review(p,{}, {},no_request,lambda *a,**k:None)
    assert len(current['facts'])==1 and current['diagnostic']['model_requests']==0
    assert current['review_receipts'][0]['response']==raw==old['review_receipts'][0]['response']
    assert raw['facts'][0]['chapter']=='2' and current['facts'][0]['chapter']==2
