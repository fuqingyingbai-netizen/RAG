"""Offline reproductions of defects observed in the retained 2026-10-20 run."""
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
import requests

from company_publishers import statistics_publisher_identity, statistics_release_candidate
from search_results import interleave_research_candidates
from web_search import WebSearchProvider
from research_workflow import ResearchWorkflow
from research_strategies.company import CompanyResearchStrategy
from report_agents.company_reputation import benchmark_discovery_queries, build_reputation_package
from test_company_reputation import market_text
from test_company_history import filing


def response(status, body):
    result=requests.Response()
    result.status_code=status
    result._content=json.dumps(body).encode()
    result.url='https://google.serper.dev/search'
    return result


def test_free_account_limit_is_negotiated_once_and_cached_per_credential(monkeypatch):
    monkeypatch.setenv('SERPER_API_KEY','offline-account-a')
    monkeypatch.setenv('SERPER_FETCH_ENABLED','false')
    sent=[]
    def post(_url,**kw):
        sent.append(kw['json']['num'])
        return response(400,{'message':'Query pattern not allowed for free accounts.'}) if kw['json']['num']>10 else response(200,{'organic':[]})
    monkeypatch.setattr('web_search.requests.post',post)
    provider=WebSearchProvider()
    with ThreadPoolExecutor(max_workers=3) as ex:
        rows=list(ex.map(lambda q:provider._search_serper(q,30),['one','two','three']))
    assert sent==[30,10,10,10]
    assert all(r.audit['effective_limit']==10 and r.audit['requested_limit']==30 for r in rows)
    assert all(r.audit['negotiated_account_cap']==10 for r in rows)
    monkeypatch.setenv('SERPER_API_KEY','offline-account-b')
    provider._search_serper('different account',30)
    assert sent[-2:]==[30,10]


@pytest.mark.parametrize('status,message',[(400,'Invalid query'),(401,'Unauthorized'),(429,'Too many requests')])
def test_unrelated_http_errors_do_not_trigger_serper_cap_retry(monkeypatch,status,message):
    monkeypatch.setenv('SERPER_API_KEY','offline-account')
    sent=[]
    monkeypatch.setattr('web_search.requests.post',lambda _url,**kw:(sent.append(kw['json']['num']) or response(status,{'message':message})))
    with pytest.raises(requests.HTTPError):WebSearchProvider()._search_serper('question',30)
    assert sent==[30]


@pytest.mark.parametrize('status,body,expected',[
    (401,{'error':'invalid api key'},'unauthorized'),
    (402,{'message':'Payment required'},'quota_exceeded'),
    (400,{'message':'Not enough credits'},'quota_exceeded'),
    (403,{'code':'403','message':'You do not have enough money or package quota'},'quota_exceeded'),
    (432,{'detail':{'error':'Plan credit limit'}},'quota_exceeded'),
    (433,{'detail':{'error':'Account usage cap'}},'quota_exceeded'),
    (429,{'message':'Too many requests'},'rate_limited'),
    (403,{'message':'Forbidden'},'access_denied'),
    (503,{},'temporary_service_failure'),
    (400,{'message':'Invalid query'},'invalid_request'),
])
def test_search_failure_reasons_do_not_conflate_account_and_network(status,body,expected):
    exc=requests.HTTPError(response=response(status,body))
    assert WebSearchProvider._search_failure_reason(exc)==expected
    assert WebSearchProvider._search_failure_reason(requests.ReadTimeout())=='temporary_network_failure'


@pytest.mark.parametrize('status,body',[(402,{}),(400,{'message':'Not enough credits'})])
def test_terminal_failure_is_retained_in_following_query_audit(monkeypatch,status,body):
    provider=WebSearchProvider()
    calls=[]
    def fail(*a,**kw):
        calls.append(1)
        raise requests.HTTPError(response=response(status,body))
    provider.engines=[('serper',fail)]
    monkeypatch.setenv('SERPER_API_KEY','offline-account')
    first=provider.multi_engine_search('first',30,candidate_limit=30)
    second=provider.multi_engine_search('second',30,candidate_limit=30)
    assert first.audit['engine_states']['serper']['reason']=='quota_exceeded'
    assert second.audit['engine_states']['serper']=={'status':'not_queried','reason':'quota_exceeded'}
    assert calls==[1]


def test_admission_interleaves_modules_and_questions_without_dropping_candidates():
    batches=[({'module':'capital','query':'a'},list(range(30))),
             ({'module':'capital','query':'b'},list(range(100,130))),
             ({'module':'people','query':'c'},list(range(200,205))),
             ({'module':'reputation','query':'d'},list(range(300,305)))]
    interleaved=list(interleave_research_candidates(batches))
    assert [(q['query'],r[0]) for q,r in interleaved[:6]]==[('a',0),('c',200),('d',300),('b',100),('c',201),('d',301)]
    assert len(interleaved)==70
    for query,rows in batches:
        assert [r[0] for q,r in interleaved if q['query']==query['query']]==rows
    assert list(interleave_research_candidates([({'module':'empty'},[])]))==[]


def test_reporting_year_hints_follow_requested_cutoff_without_asserting_a_report_exists():
    target='星河精密股份有限公司'
    rows=CompanyResearchStrategy().expand_search_queries({'modules':[]},{'target_name':target,'as_of_date':'2024-06-30'})
    dated=[r for r in rows if 'search_year_hint' in r]
    assert [r['search_year_hint'] for r in dated]==[2024,2023]
    assert all('星河精密' in r['query'] and r['as_of_date']=='2024-06-30' for r in dated)
    assert not any('2025' in r['query'] for r in dated)
    assert all('period' not in r for r in dated)


def test_company_cutoff_is_preserved_and_included_in_reuse_fingerprint():
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    p=SimpleNamespace(target_name='星河精密股份有限公司',title='公开资料研究',industry='制造',target_type='company',description='')
    a=w._normalize_intake(p,{'company_name':p.target_name,'target_type':'company','as_of_date':'2024-06-30'},[],[])
    b={**a,'as_of_date':'2025-06-30'}
    assert a['as_of_date']=='2024-06-30'
    assert w._intake_evidence_fingerprint(a)!=w._intake_evidence_fingerprint(b)


def test_full_legal_target_does_not_mine_sentence_fragments_or_other_credit_codes():
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    for target in ('星河精密股份有限公司','青禾食品有限公司'):
        source=SimpleNamespace(title=f'关于{target}拟分拆其子公司远山科技有限公司',
            summary=target+target,content='其他公司统一社会信用代码：91110108MACUTWH50K',source_metadata={})
        p=SimpleNamespace(target_name=target,target_type='company',sources=[source])
        assert w._structured_entity_candidates(p,{'company_name':target},target)==[target]


def test_publisher_identity_requires_own_release_route_and_dataset_attribution():
    text='Source: Global EV and Battery Monthly Tracker, SNE Research'
    url='https://www.sneresearch.com/en/insight/release_view/42/page/0'
    assert statistics_publisher_identity(url,text)['publisher_name']=='SNE Research'
    assert statistics_publisher_identity(url,'A third party mentions SNE Research')=={}
    assert statistics_publisher_identity(url.replace('sneresearch.com','sneresearch.com.evil.example'),text)=={}
    assert statistics_publisher_identity(url.replace('/insight/release_view/','/news/'),text)=={}
    assert not statistics_release_candidate(url.replace('https:','http:'))
    assert statistics_publisher_identity('https://www.idc.com/resource-center/press-releases/example/','Source: IDC Quarterly Tracker')['publisher_name']=='IDC'


def test_original_statistics_are_industry_context_and_never_company_risk_facts():
    target='星河精密股份有限公司'
    _card,issuer=filing(target,'公司外文名称缩写 NSR')
    url='https://sneresearch.com/en/insight/release_view/42/page/0'
    raw=market_text()+'\nSource: Global EV and Battery Monthly Tracker, SNE Research'
    source=SimpleNamespace(url=url,title='Global EV battery market share',content=raw,summary='',source_type='web',
        source_metadata={'content_kind':'full_text','fetch_status':'done'},credibility_score=70,id=2)
    p=SimpleNamespace(target_name=target,target_type='company',sources=[issuer,source])
    annotated=ResearchWorkflow.__new__(ResearchWorkflow)._annotate_evidence_facts(p,[{'source_url':url,'source_title':source.title,'fact':'Market data','evidence_quote':'Market data'}])
    assert annotated[0]['evidence_scope']=='industry_context'
    assert annotated[0]['eligible_for_risk_scoring'] is False
    assert annotated[0].get('eligible_for_report') is not False
    packet=build_reputation_package({'facts':annotated},target,[issuer,source])
    assert len([r for r in packet['facts'] if r['kind']=='benchmark'])==2
    assert all(r['mode']=='原发布机构统计' for r in packet['facts'])
    blocked={**annotated[0],'eligible_for_report':False,'entity_match':'mismatch'}
    assert not build_reputation_package({'facts':[blocked]},target,[issuer,source])['facts']
    queries=benchmark_discovery_queries([issuer],target,set(),'2026-10-20')
    assert len(queries)==1 and '"NSR" 2026' in queries[0]['query']


def test_history_rejects_traditional_holdings_declaration_and_subordinate_incorporation():
    from report_agents.company_history import non_issuer_event_context, build_history_package
    from test_company_history import filing
    target='星河精密股份有限公司'
    declarations=[
        '除上述披露者外，於二零二六年六月三十日，概無本公司董事於股份中擁有權益，根據上市發行人董事進行證券交易的標準守則須知會本公司。',
        '本公司下属远山技术有限公司为1998年设立于深圳市的生产型企业。',
    ]
    for raw in declarations:
        assert non_issuer_event_context(raw)
        card,source=filing(target,raw)
        package=build_history_package({'facts':[card]},target,[source])
        assert not [r for r in package['facts'] if r['kind']=='event']


def test_history_capital_classification_and_completion_match_both_chinese_scripts():
    from report_agents.company_history import _event_kind, _event_status
    raw='本公司於二零二五年三月完成增發境外上市外資股，所得款項淨額載於本報告。'
    assert _event_kind(raw)=='资本事项'
    assert _event_status(raw)=='原文记载已发生'


def test_history_registry_date_replaces_matching_coarse_formation_but_keeps_reform():
    from report_agents.company_history import build_history_package
    from test_company_history import filing
    target='星河精密股份有限公司'
    card,source=filing(target,f'{target}成立于1995年2月。公司于2008年5月完成整体改制。')
    registry={**card,'kind':'registry','field':'成立日期','value':'1995-02-10'}
    packet=build_history_package({'facts':[card]},target,[source],governance={'facts':[registry]})
    events=[r for r in packet['facts'] if r['kind']=='event']
    assert [r['period'] for r in events if r['period'].startswith('1995')]==['1995-02-10']
    assert any(r['period']=='2008-05' and '改制' in r['fact'] for r in events)


@pytest.mark.parametrize('mixed_scope',[False,True])
def test_rebuilt_summary_keeps_group_and_parent_financial_subjects(mixed_scope):
    from report_agents.company_summary import fallback_company_summary,summary_errors
    from test_company_summary import card,project
    period='2026年半年度报告'
    rows=[card(1,f'本集团{period}：营业收入为120.00万元。',summary_topic='financial',period=period)]
    subject='母公司单体' if mixed_scope else '本集团'+period+'：'
    rows.append(card(2,subject+'归属于上市公司股东的净利润为8.00万元。',summary_topic='financial',period=period))
    package={'facts':rows}
    text=fallback_company_summary(project(),package)
    financial=next(line for line in text.splitlines() if line.startswith('- ') and '营业收入' in line)
    assert '本集团' in financial
    if mixed_scope:assert '母公司单体' in financial
    else:assert financial.startswith('- 本集团'+period+'，')
    assert summary_errors(text,package)==[]


def test_history_report_publication_dates_do_not_displace_product_actions():
    from report_agents.company_history import build_history_package
    target='星河精密股份有限公司'
    raw=('本公司于2026年3月发布第二代微型部件。'+target+'2026年半年度报告全文发布日期为2026年8月。'
         '本公司于2024年3月27日在网站发布《2023年社会责任报告》。')
    card,source=filing(target,raw)
    events=[r for r in build_history_package({'facts':[card]},target,[source])['facts'] if r['kind']=='event']
    assert len(events)==1 and '第二代微型部件' in events[0]['fact']


def test_history_host_label_in_layout_is_not_the_later_action_subject():
    from report_agents.company_history import build_history_package
    target='星河精密股份有限公司'
    raw=('公益活动主办方：'+target+'承办方：公益基金会。新项目质量等级及活动版面主办方：'+target
         +'承办方：公益基金会2010年7月，星河精密捐资设立了慈善基金会。')
    card,source=filing(target,raw)
    assert not [r for r in build_history_package({'facts':[card]},target,[source])['facts'] if r['kind']=='event']


def test_management_relationship_quotes_keep_which_same_surname_person_is_speaking():
    from report_agents.company_management import relationship_rows,render_management
    pages=[{'page':7,'text':'王甲先生，1980年出生。王先生与本公司董事王乙先生为兄弟关系。'},
           {'page':12,'text':'王乙先生，1981年出生。王先生与本公司董事王甲先生为兄弟关系。'}]
    rows=relationship_rows(pages,{'王甲','王乙'},'2026-09-29','星河精密股份有限公司')
    assert [r['subject'] for r in rows]==['王甲','王乙']
    for i,row in enumerate(rows):row.update(evidence_id=f'E-{i+1:012X}',evidence_ids=[f'E-{i+1:012X}'])
    text=render_management({'facts':rows,'information_gaps':[]})
    assert '（王甲相关原文）：王先生' in text and '（王乙相关原文）：王先生' in text
    assert all(r['evidence_quote']==r['fact'] for r in rows)


def test_treasury_share_accounting_table_is_not_employee_culture_practice():
    from report_agents.company_people import policy_rows
    target='星河精密股份有限公司'
    accounting=(target+'2025年半年度报告全文143合并财务报表主要项目注释39、库存股'
                '期初余额本期增加本期减少期末余额员工持股计划1002000300库存股本期增加为本期购买流通股所致。')
    valid=target+'构建覆盖全体员工的培训体系，提供不同技能提升与领导力发展课程。'
    assert policy_rows([{'page':143,'text':accounting}],'2025年',target)==[]
    rows=policy_rows([{'page':143,'text':accounting+valid}],'2025年',target)
    assert len(rows)==1 and '培训体系' in rows[0]['fact']


def test_consolidation_pronoun_does_not_transfer_a_subsidiary_ratio_to_the_issuer():
    from report_agents.company_diligence import disclosure_rows
    base={'entity':'星河精密股份有限公司','period':'2026年半年度报告'}
    unresolved='截至2026年6月30日，控股方占该公司65.76%的权益，故将其作为子公司纳入合并范围。'
    explicit='截至2026年6月30日，控股方占青禾电子有限公司65.76%的权益，故将青禾电子有限公司作为子公司纳入合并范围。'
    assert disclosure_rows(None,[{'page':169,'text':unresolved}],base)==[]
    rows=disclosure_rows(None,[{'page':169,'text':explicit}],base)
    assert len(rows)==1 and rows[0]['kind']=='consolidation' and '青禾电子有限公司' in rows[0]['fact']


def test_concatenated_recall_notices_never_share_another_manufacturers_scope():
    from collections import defaultdict
    from report_agents.company_risk_register import recall_events,source_anchor
    from test_company_risk_register import notice,CHILD
    first=notice()
    second=notice(owner='远山汽车有限公司',index=2)
    first['content']+='\n'+second['content']
    rows,state=recall_events(first,source_anchor(first,defaultdict(list)))
    assert rows==[] and state=='multiple_notices_require_manual_scope_review'


def test_indexed_defect_blocks_are_a_gap_until_campaign_join_is_verified():
    from collections import defaultdict
    from report_agents.company_risk_register import recall_events,source_anchor
    from test_company_risk_register import notice
    source=notice()
    source['content']=source['content'].replace('本次召回范围内','本次召回范围（一）内')
    rows,state=recall_events(source,source_anchor(source,defaultdict(list)))
    assert rows==[] and state=='indexed_recall_scopes_require_manual_scope_review'


def test_summary_cannot_attach_later_recall_to_earlier_financial_reporting():
    from report_agents.company_summary import summary_errors
    from test_company_summary import card,section
    risk=card(1,'2026年9月18日，主管部门公告制造主体召回事项，后续整改待核。')
    report=card(2,'本集团2026年半年度报告营业收入为100万元。')
    p={'facts':[risk,report]}
    assert any('计提' in e for e in summary_errors(section('需核验召回是否已在2026年半年度报告计提成本。[E-000000000001][E-000000000002]'),p))
    assert any('融资' in e for e in summary_errors(section('本集团已完成融资。[E-000000000002]'),p))
    unsupported=section('需核实HKSCC NOMINEES LIMITED股份的实际控制归属是否与创始人存在一致行动安排。[E-000000000002]')
    assert any('一致行动' in e for e in summary_errors(unsupported,p))
    assert any('名义持股' in e for e in summary_errors(unsupported,p))
    assert any('未披露' in e for e in summary_errors(section('主管部门未披露召回执行细节。[E-000000000001]'),p))


def test_spaced_inline_summary_ids_normalize_once_without_changing_claims():
    import json
    from report_agents.company_summary import normalize_company_summary,SUMMARY_HEADINGS
    obj={h:{'text':'本次研究待核验。','evidence_ids':[]} for h in SUMMARY_HEADINGS}
    obj['核心发现点']=[{'text':'本集团营业收入100万元[ E-000000000001 ]。','evidence_ids':['E-000000000001']}]
    text=normalize_company_summary(json.dumps(obj,ensure_ascii=False))
    assert text.count('[E-000000000001]')==1 and '[ E-' not in text


def test_profile_cover_year_does_not_reintroduce_known_coarse_founding():
    from report_agents.company_history import build_history_package
    from test_company_history import filing
    target='星河精密股份有限公司'
    card,source=filing(target,'2019年社会责任报告公司简介'+target+'成立于1995年2月，总部位于深圳市。')
    registry={**card,'kind':'registry','field':'成立日期','value':'1995-02-10'}
    p=build_history_package({'facts':[card]},target,[source],governance={'facts':[registry]})
    assert [r['period'] for r in p['facts'] if r['kind']=='event' and r['event_type']=='工商沿革']==['1995-02-10']
