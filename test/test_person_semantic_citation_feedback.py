"""Offline citation-receipt tests; these responses are not live acceptance."""
import copy,json,pytest
from person_semantic_review import review_analyses


def fixture():
    facts=[{'evidence_id':f'E-PFEEDBACK{i}','fact':text,'source_url':f'https://fixture.invalid/{i}'}
        for i,text in enumerate(['2025年报列陈安任董事长、总裁。','2026年公告列陈安任执行董事。','招股文件载陈安在签署时任执行董事。'])]
    claim={'analysis':'2025年报所列：陈安任董事长、总裁、执行董事。','evidence_ids':[f['evidence_id'] for f in facts]}
    return facts,claim


@pytest.mark.parametrize('reply_kind',['unsupported','still_partial'])
def test_followup_names_actual_missing_citation_and_never_promotes_omission(reply_kind):
    facts,claim=fixture();before=copy.deepcopy((facts,claim));calls=[]
    def invoke(role,prompt,*args):
        packet=json.loads(prompt.splitlines()[-1]);calls.append(packet)
        if len(calls)==2:
            feedback=packet['claims'][0]['previous_citation_review']
            assert feedback['missing_evidence_ids']==[facts[2]['evidence_id']]
            assert feedback['required_evidence_ids']==claim['evidence_ids']
            assert feedback['planning_only_not_evidence'] is True
            assert packet['claims'][0]['analysis']==claim['analysis']
        verdict='unsupported' if len(calls)==2 and reply_kind=='unsupported' else 'supported'
        return json.dumps({'reviews':[{'claim_index':0,'verdict':verdict,'issues':[],
            'reason':'历史招股任职不能证明2025年报岗位。' if verdict=='unsupported' else '前两份提供部分岗位信息。',
            'supporting_evidence_ids':claim['evidence_ids'][:2]}]},ensure_ascii=False)
    result,errors,audit=review_analyses(5,'管理',facts,[claim],invoke,as_of_date='2026-10-20')
    assert len(calls)==2 and errors and not result[0]['analysis']
    assert ('semantic_support_missing' if reply_kind=='unsupported' else 'semantic_review_incomplete') in errors
    assert (facts,claim)==before


def test_complete_first_receipt_leaves_original_request_packet_unchanged():
    facts,claim=fixture();seen=[]
    def invoke(role,prompt,*args):
        data=json.loads(prompt.splitlines()[-1]);seen.append(data)
        assert 'previous_citation_review' not in data['claims'][0]
        return json.dumps({'reviews':[{'claim_index':0,'verdict':'supported','issues':[],
            'reason':'离线收据形状测试，不代表此示例的真实语义通过。','supporting_evidence_ids':claim['evidence_ids']}]},ensure_ascii=False)
    _,errors,audit=review_analyses(5,'管理',facts,[claim],invoke)
    assert not errors and len(seen)==1 and audit['requests']==1


def test_feedback_indices_are_local_while_effective_review_indices_remain_original():
    facts,claim=fixture();first={**claim,'analysis':'另一个离线候选。'};calls=[]
    def invoke(role,prompt,*args):
        data=json.loads(prompt.splitlines()[-1]);calls.append(data)
        if len(calls)==1:
            return json.dumps({'reviews':[{'claim_index':i,'verdict':'supported','issues':[],
                'reason':'离线收据形状测试','supporting_evidence_ids':claim['evidence_ids'][:2] if i else claim['evidence_ids']} for i in [0,1]]})
        assert len(data['claims'])==1 and data['claims'][0]['claim_index']==0
        assert data['claims'][0]['previous_citation_review']['missing_evidence_ids']==[facts[2]['evidence_id']]
        return json.dumps({'reviews':[{'claim_index':0,'verdict':'unsupported','issues':[],
            'reason':'该引用缺少对应报告期','supporting_evidence_ids':[]}]})
    result,errors,audit=review_analyses(5,'管理',facts,[first,claim],invoke)
    assert result[0]['analysis']==first['analysis'] and not result[1]['analysis']
    assert audit['effective_claims'][1]['claim_index']==1 and errors
