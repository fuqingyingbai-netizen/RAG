from copy import deepcopy

import pytest

from report_agents.company_risk_register import _judicial_entries


def records():
    target='青禾网络科技有限公司'
    first='三年来，监管机关加强对'+target+'合规整改的督导，对整改落实情况开展深入核查，并委托第三方机构开展执法效果评估。'
    title='市场监管总局督导'+target+'完成三年整改'
    long=first+'从核查情况看，该公司已停止相关行为，整改工作取得良好成效。'
    base={'kind':'regulatory_remediation','entity':target,'authority':'国家市场监督管理总局',
          'source_title':title,'date':'2024-08-30','period':'2024-08-30','publication_date':'2024-08-30',
          'source_url':'https://www.samr.gov.cn/original.html','fact':long,'evidence_quote':long,
          'evidence_id':'E-000000000001','evidence_ids':['E-000000000001']}
    repost=dict(base,source_url='https://www.samr.gov.cn/repost.html',publication_date='2024-09-09',
                evidence_id='E-000000000002',evidence_ids=['E-000000000002'])
    short=dict(repost,source_url='https://www.samr.gov.cn:7280/repost.html',fact=first+' '+title,
               evidence_quote=first+' '+title,evidence_id='E-000000000003',evidence_ids=['E-000000000003'])
    return [base,repost,short]


@pytest.mark.parametrize('reverse',[False,True])
def test_short_alias_version_is_not_another_remediation_or_a_witness_for_the_complete_quote(reverse):
    original=records()[::(-1 if reverse else 1)];before=deepcopy(original)
    entries=_judicial_entries(original)
    assert len(entries)==1
    row=entries[0]['fact_record']
    assert row['fact']==records()[0]['fact'] and row['publication_date']=='2024-08-30'
    assert set(row['evidence_ids'])=={'E-000000000001','E-000000000002'}
    assert row['same_publication_variants'][0]['evidence_id']=='E-000000000003'
    assert original==before


@pytest.mark.parametrize('change',[
    {'source_url':'https://www.samr.gov.cn/other-notice.html'},
    {'publication_date':'2024-09-10'},
    {'entity':'青禾网络技术有限公司'},
    {'authority':'某省市场监督管理局'},
    {'fact':'监管部门对青禾网络科技有限公司继续开展整改核查，但指出该公司尚未落实部分措施，不具备完成整改条件。'},
])
def test_other_notices_dates_recipients_authorities_and_changed_outcomes_stay_separate(change):
    original=records();original[-1].update(change)
    assert len(_judicial_entries(original))==2
