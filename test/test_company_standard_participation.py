import hashlib
import json
from copy import deepcopy

import pytest

from report_agents.company_corpus import prepare_corpus, build_corpus_review, _batches
from report_agents.company_source_review import external_standard_participation, validate_selection
from test_company_corpus import TARGET, project, source


def standard_source(body):
    item=source(body=body)
    item.update(url='https://standards.example/record',title='国家标准公开记录')
    return item


def test_drafting_role_keeps_contiguous_title_and_future_status_without_business_or_governance_inference():
    raw=('国家标准 推荐性 即将实施\n\n国家标准《模型服务技术规范》由全国技术标准化委员会归口。\n\n'
         '主要起草单位 其他企业有限公司 、'+TARGET+' 、研究院 。\n\n'
         '实施日期\n: 2028-03-01')
    docs,states,_=prepare_corpus(project([standard_source(raw)]),{})
    assert states['1']['native_scope_recovery']
    doc=docs[0]
    window=next(w for w in doc['windows'] if '即将实施' in w['quote'])
    assert window['candidate_chapters']==[5]
    assert '《模型服务技术规范》' in window['quote']
    assert raw[window['start']:window['start']+len(window['quote'])]==window['quote']
    fact,error=validate_selection(dict(evidence_id=doc['evidence_id'],window_id=window['window_id'],
        chapter=5,scope='third_party_about_target',relevance='公开列示的标准参与'),{doc['evidence_id']:doc},TARGET)
    assert not error and fact['chapter']==5
    assert '不等于认证' in fact['boundary'] and not fact['eligible_for_risk_scoring']


def test_external_committee_employer_is_not_internal_company_governance():
    raw='委员会名称 TC123 全国信息技术标准化技术委员会 工作单位 '+TARGET+' 委员会职务 副主任委员 加入时间 2025-08-28'
    docs,_,_=prepare_corpus(project([standard_source(raw)]),{})
    doc=docs[0];window=doc['windows'][0]
    base=dict(evidence_id=doc['evidence_id'],window_id=window['window_id'],scope='third_party_about_target',relevance='外部委员会公开履历')
    assert validate_selection(dict(base,chapter=5),{doc['evidence_id']:doc},TARGET)[0]
    assert validate_selection(dict(base,chapter=4),{doc['evidence_id']:doc},TARGET)[1]=='nonliteral_or_unrouted_quote'


@pytest.mark.parametrize('raw',[
    TARGET+'被新闻提及。主要起草单位 其他企业有限公司 。',
    '主要起草单位 '+TARGET+'下属研究中心 。',
    '主要起草单位 其他'+TARGET+' 。',
    '主要起草单位 '+TARGET+' 。',
    '工作单位 其他企业有限公司 委员会职务 委员。'+TARGET+'；全国标准化技术委员会。',
    '工作单位 '+TARGET+' 委员会职务 委员；公司内部经营委员会。',
])
def test_remote_name_or_different_entity_cannot_bind_external_standard_role(raw):
    assert not external_standard_participation(raw,TARGET)


def test_unchanged_v10_receipt_revalidated_after_standard_routing_upgrade_without_new_request():
    p=project([source()])
    def invoke(role,prompt,trace):
        docs=json.loads(prompt.split('资料：\n',1)[1])['originals']
        return json.dumps({'decisions':[dict(evidence_id=d['evidence_id'],disposition='accepted') for d in docs],
            'facts':[dict(evidence_id=d['evidence_id'],window_id=w['window_id'],chapter=2,
                scope='target',relevance='登记字段') for d in docs for w in d['windows']]})
    first=build_corpus_review(p,{}, {},invoke,lambda *a,**k:None)
    old=deepcopy(first);old['version']='company-corpus-v10-issuer-reply-authorship'
    batch=list(_batches(prepare_corpus(p,{})[0]))[0]
    old['review_receipts'][0]['input_sha256']=hashlib.sha256((old['version']+'\n'+TARGET+'\n2026-10-20\n'+
        json.dumps(batch,ensure_ascii=False,sort_keys=True)).encode()).hexdigest()
    p.company_corpus_analysis_cache=old
    def no_request(*a):raise AssertionError('Unchanged source input was requested again')
    current=build_corpus_review(p,{}, {},no_request,lambda *a,**k:None)
    assert current['diagnostic']['model_requests']==0
    assert current['facts']==first['facts']


def test_concrete_industry_market_size_is_routed_to_attributed_context_without_target_inference():
    raw='据行业研究机构统计，2024年中国相关行业市场规模达到100亿元，同比增长8.9%，统计范围为国内公开市场。'
    p=project([standard_source(raw)]);p.company_research_intake['industry']='相关行业'
    docs,states,_=prepare_corpus(p,{})
    assert states['1']['native_scope_recovery']
    doc=docs[0];window=doc['windows'][0]
    fact,error=validate_selection(dict(evidence_id=doc['evidence_id'],window_id=window['window_id'],
        chapter=5,scope='target',relevance='行业统计口径'),{doc['evidence_id']:doc},TARGET)
    assert not error and fact['scope']=='industry_context'
    assert fact['fact']==raw and not fact['eligible_for_risk_scoring']
