from copy import deepcopy
import re
from types import SimpleNamespace

import pytest

from report_agents.company_governance import refs
from report_agents.company_diligence import build_diligence_package, render_diligence, display_diligence_fact, task_object
from report_agents.company_risk_register import attach_case_display_references, _display_fact
from report_agents.company_people import build_people_package
from report_agents.company_report_agent import CompanyReportAgent


def case(name='甲公司与乙公司购销争议'):
    return {'kind':'disclosed_case','source_url':'https://www.hkexnews.hk/report.pdf','source_title':'年度报告',
            'period':'2025年年度报告','page':86,'pages':[86],'case_description':name,'amount':'100万元',
            'stage':'执行中','result':'乙公司支付甲公司100万元；一审诉讼费12,345元，由乙公司承担',
            'execution':'正在执行','fact':name+'；判决乙公司付款100万元；一审诉讼费12,345元，由乙公司承担；正在执行',
            'evidence_id':'E-123456ABCDEF','evidence_ids':['E-123456ABCDEF']}


def test_repeated_same_source_citation_is_deduplicated_without_mutating_proof():
    record={'evidence_ids':['E-111111111111','E-111111111111','E-222222222222','E-111111111111']}
    old=deepcopy(record)
    assert refs(record)=='[E-111111111111][E-222222222222]' and record==old


def test_different_metrics_from_one_report_keep_facts_and_combine_display_citations():
    from test_company_assessment import src,build
    from report_agents.company_assessment import render_assessment
    packet=build(src());before=deepcopy(packet)
    text=render_assessment(packet)
    assert packet==before and len(packet['financial_observations'])==3
    assert '盈利与经营现金净流入并存' in text
    assert not re.search(r'(\[E-[A-Z0-9-]{6,}\])\1',text)
    assert set(re.findall(r'\[(E-[A-Z0-9-]{6,})\]',text))=={e for r in packet['facts'] for e in r['evidence_ids']}


def test_diligence_keeps_case_proof_but_does_not_repeat_chapter9_costs():
    original=case();before=deepcopy(original)
    p=build_diligence_package({'facts':[]},'甲公司',[],prior_packages={'judicial':{'facts':[original]}})
    assert original==before
    r=next(r for r in p['facts'] if r['kind']=='execution_followup')
    assert r['result']==original['result'] and r['fact']==original['fact']
    text=render_diligence(p)
    assert '12,345' not in text and '第九章同事项' in text
    assert '100万元' in text and '正在执行' in text and '[E-123456ABCDEF]' in text
    assert p['tasks'][0]['object'].count(original['case_description'])==1


def test_standalone_evidence_without_verified_prior_chapter_keeps_full_literal():
    record={**case(),'kind':'execution_followup','entity':'甲公司'}
    assert display_diligence_fact(record)==record['fact']


@pytest.mark.parametrize('change',[{}, {'case_description':'另一案件'}, {'period':'2026年半年度报告'},
                                  {'result':'当期已全部支付'}, {'amount':'999万元'}])
def test_risk_cross_reference_requires_same_case_version_not_just_same_source(change):
    original=case();r={**original,**change};entry={'fact_record':r};entries=[entry]
    attach_case_display_references(entries,{'facts':[original]})
    shown=_display_fact(entry['fact_record'])
    if not change:
        assert '第九章同事项' in shown and '12,345' not in shown
        assert entry['fact_record']['fact']==original['fact']
    else:
        assert '第九章同事项' not in shown and '12,345' in shown
    assert 'display_reference' not in original and 'display_reference' not in r


def test_fund_use_trigger_keeps_total_and_leaves_allocations_in_detail_table():
    r={'entity':'甲股份有限公司','period':'2025年年度报告','kind':'fund_use',
       'fact':'截至2025年末，公司已使用配售所得100万元，其中60万元用于研发，40万元补充营运资金。'}
    obj=task_object(r)
    assert '100万元' in obj and '2025年年度报告' in obj and '60万元' not in obj
    assert '60万元' in r['fact'] and '40万元' in r['fact']


def test_learning_word_never_enters_chapter_diagnostic_citation_inventory():
    target='青禾制造股份有限公司';url='https://www.hkexnews.hk/report.pdf'
    text=target+'建立数字化人才培养体系，搭建E-learning在线学习平台，为新员工提供入职培训和职业发展课程。'
    source={'url':url,'title':target+'2025年年度报告','content':target+'\n2025年年度报告\n'+text,
            'source_metadata':{'document_pages':[{'page':71,'text':text}]}}
    card={'source_url':url,'source_title':source['title'],'evidence_id':'E-123456ABCDEF'}
    packet=build_people_package({'facts':[card]},target,[source]);project=SimpleNamespace()
    body=CompanyReportAgent()._write_people(project,packet,lambda *a,**kw:None)
    assert 'E-learning' in body
    assert not project.company_people_diagnostic['degraded']
    assert project.company_people_diagnostic['cited_evidence_ids']==['E-123456ABCDEF']
