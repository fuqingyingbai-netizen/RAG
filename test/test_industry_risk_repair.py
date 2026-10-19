import json
import re
from types import SimpleNamespace

import pytest

from industry_research import (NUMBER_PATTERN, numeric_mentions, number_key, annotate_fact, extract_industry_source_facts,
    normalize_risk, package_risk_evidence, mark_unverified_numbers, delivery_errors, risk_repair_package)
from research_workflow import ResearchWorkflow


SCOPE = {'industry_name':'机器人','geography':'中国大陆','capital_market':'none','as_of_date':'2026-10-15'}


def card(eid='E-0DC3EB7C53F5',module='政策与监管',text='机器人行业实行分级准入监管。'):
    return {'evidence_id':eid,'fact':text,'module':module,'scope_match':'in_scope','evidence_scope':'industry_level',
        'source_url':'https://stats.gov.cn/robot','source_title':'机器人研究','eligible_for_risk_scoring':True}


def row(fact,score=30,reason=None,name='政策与监管风险'):
    return {'name':name,'score':score,'level':'low','reason':reason or fact['fact'],
            'evidence_ids':[fact['evidence_id']]}


def payload(facts,mapping=None):
    return {'facts':facts,'dimension_evidence_ids':mapping or {'政策与监管风险':[f['evidence_id'] for f in facts]}}


def repair_case():
    f=card(); other=card('E-1234567890AB','市场规模与增长','机器人行业应用需求增加。')
    normalized=normalize_risk({'dimensions':[row(f,reason='参见 E-AAAAAAAAAAAA'),
        row(other,score=20,name='市场增长与需求风险')]},[f,other],SCOPE)
    evidence=payload([f,other],{'政策与监管风险':[f['evidence_id']],'市场增长与需求风险':[other['evidence_id']]})
    return ResearchWorkflow.__new__(ResearchWorkflow), f, other, normalized, evidence


@pytest.mark.parametrize('eid',['E-0DC3EB7C53F5','E-6387350C0EBF','E-B3EB1A8D149B','E-1234567890EB'])
def test_hex_evidence_ids_are_never_numeric_tokens(eid):
    assert re.findall(NUMBER_PATTERN,eid)==[]
    assert numeric_mentions(f'参考[{eid}](https://stats.gov.cn/3EB)')==[]


@pytest.mark.parametrize('url',['https://stats.gov.cn/a?size=3EB','structured://projects/68/100亿元',
                              'https://stats.gov.cn/a?growth=42%'])
def test_url_destinations_do_not_authorize_or_invalidate_body_numbers(url):
    assert numeric_mentions(f'参考来源 {url}')==[]
    assert numeric_mentions(f'[{card()["evidence_id"]}]({url})，正文数据101.34EB。')==['101.34EB']


def test_real_eb_and_percentage_are_still_checked_next_to_identifier():
    text='数据101.34 EB，同比增长42.86% [E-0DC3EB7C53F5]'
    assert numeric_mentions(text)==['101.34 EB','42.86%']
    assert '待核验' in mark_unverified_numbers(text,[card()])
    assert '待核验' not in mark_unverified_numbers('定性事实 [E-0DC3EB7C53F5]',[card()])


def test_signed_values_are_not_reinterpreted_as_positive():
    assert numeric_mentions('同比-5%，净收入-1.2亿元')==['-5%','-1.2亿元']
    assert number_key('-1.2亿元')==number_key('-12000万元')
    assert number_key('-5%')!=number_key('5%')
    src=SimpleNamespace(content='2025年我国机器人净利率-5%。',url='https://stats.gov.cn/r',title='机器人行业',
        source_type='government',source_metadata={'module':'商业模式与盈利逻辑'},credibility_score=90)
    fact=annotate_fact(extract_industry_source_facts([src],SCOPE)[0],SCOPE)
    assert fact['numeric_context']['value']=='-5' and fact['numeric_validation']['passed']


def test_url_numbers_do_not_turn_qualitative_fact_into_numeric_card():
    f=annotate_fact({**card(), 'fact':'机器人采用订阅模式，参考https://stats.gov.cn/100亿元'},SCOPE)
    assert 'numeric_validation' not in f


def test_qualitative_score_with_eb_fragment_id_is_not_rejected():
    f=card()
    checked=normalize_risk({'dimensions':[row(f,reason=f'根据{f["evidence_id"]}，存在合规成本。')]},[f],SCOPE)
    assert checked['dimensions'][0]['score']==30


def test_real_bad_numbers_and_original_reason_remain_auditable():
    f=card();text=f'同比增长42.86% [{f["evidence_id"]}]'
    checked=normalize_risk({'dimensions':[row(f,reason=text)]},[f],SCOPE)['dimensions'][0]
    diagnostic=checked['validation_diagnostic']
    assert checked['score'] is None and checked['unknown_cause']=='unverified_reason_numbers'
    assert diagnostic['unverified_numbers']==['42.86%']
    assert diagnostic['original_reason']==text and diagnostic['original_score']==30


def test_report_gate_does_not_invent_eb_values_from_citation_ids():
    eid=card()['evidence_id']
    text='研究边界与口径\n'+ '\n'.join(f'## {i}. 章节\n定性事实 [{eid}]' for i in range(1,17))
    diag={'evidence_ids':[eid],'chapter_evidence_ids':{i:[eid] for i in range(1,17)},'numeric_evidence':{}}
    assert not any('EB' in issue for issue in delivery_errors(text,diag,SCOPE))


def test_score_prompt_omits_other_quote_numbers_but_storage_keeps_them():
    f=card(text='2025年机器人数据量101.34 EB，其他总量199.48 EB增长42.86%。')
    f.update(evidence_quote=f['fact'], numeric_context={'metric':'数据量','value':101.34,'unit':'EB','period':'2025',
        'geography':'中国大陆','definition':'机器人数据量','is_forecast':False},numeric_validation={'passed':True})
    raw=ResearchWorkflow.__new__(ResearchWorkflow)._risk_evidence_payload(json.dumps({'facts':[f]}),'industry')
    sent=json.loads(raw)['facts'][0]
    assert sent['allowed_numbers']==['101.34EB'] and not sent.get('evidence_quote')
    assert '42.86' not in raw and '199.48' not in raw and '42.86' in f['evidence_quote']


def test_single_repair_only_changes_requested_dimension_and_cleans_stale_unknown():
    w,f,other,normalized,evidence=repair_case();calls=[]
    def invoke(role,prompt,**kwargs):
        calls.append((role,kwargs))
        return json.dumps({'dimensions':[row(f,score=40),row(other,score=99,name='市场增长与需求风险')]})
    w._invoke_industry_risk=invoke
    fixed=w._repair_industry_risk(normalized,evidence,[f,other],SCOPE)
    assert len(calls)==1 and calls[0][1]['repair'] is True
    assert fixed['dimensions'][0]['score']==40 and fixed['dimensions'][1]['score']==20
    assert fixed['overall_score'] is None  # Other applicable dimensions remain unassessed.
    assert not any(n.startswith('政策与监管风险：') for n in fixed['unknowns'])
    assert fixed['validation_diagnostics']['initial_rejections'][0]['original_reason']=='参见 E-AAAAAAAAAAAA'
    assert fixed['validation_diagnostics']['repair']['repaired_dimensions']==['政策与监管风险']


@pytest.mark.parametrize('answer',['', 'not JSON', '{"dimensions":[]}', '{"dimensions":1}', '{"dimensions":null}'])
def test_failed_repair_preserves_original_unknown_without_loop(answer):
    w,f,other,normalized,evidence=repair_case();calls=[]
    w._invoke_industry_risk=lambda *a,**kw: (calls.append(a) or answer)
    fixed=w._repair_industry_risk(normalized,evidence,[f,other],SCOPE)
    assert len(calls)==1
    assert fixed['dimensions'][0]['unknown_cause']=='invalid_reason_citations'
    assert fixed['dimensions'][1]['score']==20
    assert fixed['validation_diagnostics']['repair']['attempts']==1


def test_repair_timeout_has_no_hidden_second_attempt():
    w,f,other,normalized,evidence=repair_case();calls=[]
    def fail(*a,**kw):
        calls.append(a);raise TimeoutError('bounded timeout')
    w._invoke_industry_risk=fail
    fixed=w._repair_industry_risk(normalized,evidence,[f,other],SCOPE)
    assert len(calls)==1 and fixed['dimensions'][0]['score'] is None
    assert fixed['validation_diagnostics']['repair']['exception_type']=='TimeoutError'


def test_intentional_abstention_is_not_forced_into_repair():
    f=card();risk={'dimensions':[{'name':'政策与监管风险','score':None,'level':'unknown','reason':'缺少实证。','evidence_ids':[]}]}
    normalized=normalize_risk(risk,[f],SCOPE)
    assert normalized['dimensions'][0]['unknown_cause']=='model_abstained'
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    w._invoke_industry_risk=lambda *a,**kw: pytest.fail('An abstention must not trigger another call')
    fixed=w._repair_industry_risk(normalized,payload([f]),[f],SCOPE)
    assert not fixed['validation_diagnostics']['repair']['attempted']


def test_absent_applicable_evidence_never_triggers_repair():
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    w._invoke_industry_risk=lambda *a,**kw: pytest.fail('No candidates, no repair')
    normalized=normalize_risk({'dimensions':[row(card(),score=30)]},[],SCOPE)
    fixed=w._repair_industry_risk(normalized,{'facts':[],'dimension_evidence_ids':{}},[],SCOPE)
    assert fixed['dimensions'][0]['unknown_cause']=='no_applicable_evidence'
    assert not fixed['validation_diagnostics']['repair']['attempted']


def test_repair_uses_intact_budget_and_rejects_dropped_card():
    facts=[card(f'E-{i:012X}',text='机器人准入规范。'*100) for i in range(50)]
    normalized=normalize_risk({'dimensions':[row(facts[0],reason='参考 E-AAAAAAAAAAAA')]},facts,SCOPE)
    evidence=payload(facts)
    package=risk_repair_package(evidence,normalized)
    assert len(json.dumps(package,ensure_ascii=False))<=18000
    retained={f['evidence_id'] for f in package['facts']}
    assert 0<len(retained)<50
    dropped=next(f for f in facts if f['evidence_id'] not in retained)
    w=ResearchWorkflow.__new__(ResearchWorkflow);calls=[]
    w._invoke_industry_risk=lambda *a,**kw:(calls.append(a) or json.dumps({'dimensions':[row(dropped)]}))
    fixed=w._repair_industry_risk(normalized,evidence,facts,SCOPE)
    assert len(calls)==1 and fixed['dimensions'][0]['score'] is None
    assert fixed['validation_diagnostics']['repair']['status']=='rejected'


def test_repair_revalidates_numbers_instead_of_accepting_shorter_prose():
    w,f,other,normalized,evidence=repair_case()
    w._invoke_industry_risk=lambda *a,**kw: json.dumps({'dimensions':[row(f,reason='增长99%。')]})
    fixed=w._repair_industry_risk(normalized,evidence,[f,other],SCOPE)
    assert fixed['dimensions'][0]['score'] is None
    assert fixed['validation_diagnostics']['repair']['rejected_diagnostics'][0]['unverified_numbers']==['99%']


def test_normalized_rejection_diagnostics_never_enter_writer_risk_context():
    f=card();risk=normalize_risk({'dimensions':[row(f,reason='增长99%。')]},[f],SCOPE)
    _,scoped=package_risk_evidence({'facts':[f]},{'facts':[f]},risk,include_all=True)
    assert 'original_reason' not in json.dumps(scoped)


def test_risk_models_have_bounded_timeouts_and_no_sdk_retry(monkeypatch):
    import research_workflow
    settings=[]
    monkeypatch.setenv('ARK_API_KEY','test-only-key');monkeypatch.setenv('MODEL','test-only-model')
    monkeypatch.delenv('INDUSTRY_RISK_TIMEOUT_SECONDS',raising=False)
    monkeypatch.delenv('INDUSTRY_RISK_REPAIR_TIMEOUT_SECONDS',raising=False)
    monkeypatch.setattr(research_workflow,'init_chat_model',lambda **kw:(settings.append(kw) or
        SimpleNamespace(invoke=lambda m:SimpleNamespace(content='{}'))))
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    assert w._invoke_industry_risk('风险','prompt')=='{}'
    assert w._invoke_industry_risk('风险修复','prompt',repair=True)=='{}'
    assert [s['timeout'] for s in settings]==[90,45]
    assert all(s['max_retries']==0 for s in settings)


def test_company_risk_route_never_uses_industry_model_or_repair():
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    w._invoke_industry_risk=lambda *a,**kw:pytest.fail('Company route must stay separate')
    w._invoke=lambda *a,**kw:'{"dimensions":[],"risk_level":"unknown"}'
    p=SimpleNamespace(title='企业测试',target_name='样本企业',target_type='company',industry='机器人')
    assert isinstance(json.loads(w.assess_risk(p,'{"facts":[]}')),dict)
