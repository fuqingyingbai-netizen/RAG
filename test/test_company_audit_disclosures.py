from types import SimpleNamespace

import pytest
from opencc import OpenCC

from report_agents.company_audit_disclosures import combined_control_rows,goodwill_impairment_rows
from report_agents.company_assessment import internal_control_observations,control_score

TARGET='青禾网络科技有限公司'
BASE={'entity':TARGET,'source_url':'https://www.hkexnews.hk/original.pdf','evidence_id':'E-000000000001','evidence_ids':['E-000000000001']}


def audit(opinion='在所有重大方面保持了有效的财务报告内部控制',target=TARGET):
    return ('独立注册公众会计师事务所报告\n致'+target+'董事会及股东\n关于财务报表及财务报告内部控制之意见\n'
        '我们已审计'+target+'及其子公司（统称贵公司）的合并财务报表。'
        '我们认为合并财务报表公允反映贵公司于2025年及2024年12月31日的财务状况。'
        '此外，我们认为贵公司于2025年12月31日按照COSO《内部控制整合框架（2013版）》准则，'+opinion+'。'
        '形成审计意见的基础\n管理层负责保持有效的内部控制。')


@pytest.mark.parametrize('traditional',[False,True])
def test_combined_auditor_opinion_is_dated_and_quoted_without_a_second_control_year(traditional):
    raw=audit();raw=OpenCC('s2t').convert(raw) if traditional else raw
    page={'page':22,'text':raw};records=combined_control_rows([page],TARGET,BASE)
    assert len(records)==1 and records[0]['state']=='effective' and records[0]['cutoff']=='2025-12-31'
    assert records[0]['fact'] in raw and records[0]['evidence_quote'] in raw
    assert control_score(records)['score']==3
    source=SimpleNamespace(content=raw,title='2025年年度报告',source_metadata={'document_pages':[page]})
    integrated=internal_control_observations(source,BASE)
    assert len(integrated)==1 and integrated[0]['state']=='effective'


@pytest.mark.parametrize('opinion,state,score',[
    ('未能在所有重大方面保持有效的财务报告内部控制','ineffective',1),
    ('除已列重大缺陷的影响外，财务报告内部控制在所有重大方面有效','qualified',2),
])
def test_negative_and_qualified_control_opinions_are_not_overwritten_as_effective(opinion,state,score):
    records=combined_control_rows([{'page':22,'text':audit(opinion)}],TARGET,BASE)
    assert len(records)==1 and records[0]['state']==state and control_score(records)['score']==score


def test_ordinary_financial_audit_definitions_self_assessment_and_other_addressee_do_not_supply_control_score():
    for raw in [
        audit().replace('此外，我们认为贵公司于2025年12月31日按照COSO《内部控制整合框架（2013版）》准则，在所有重大方面保持了有效的财务报告内部控制。',''),
        audit().replace('独立注册公众会计师事务所报告','管理层年度自我评价报告'),
        audit(target='青禾网络技术有限公司'),
        audit().replace('贵公司于2025年12月31日按照','贵公司按照'),
    ]:
        assert not combined_control_rows([{'page':22,'text':raw}],TARGET,BASE)


def test_recorded_annual_goodwill_loss_keeps_currency_unit_and_separates_carrying_balance():
    raw=('关键审计事项\n关于两个报告单位的商誉减值评估\n'
        '截至2025年12月31日贵公司的合并商誉账面余额为人民币56,789百万元。'
        '截至2025年12月31日止年度贵公司录得减值亏损人民币1,234百万元。')
    pages=[{'page':22,'text':audit()},{'page':23,'text':OpenCC('s2t').convert(raw)}]
    rows=goodwill_impairment_rows(pages,TARGET,BASE)
    assert len(rows)==1 and rows[0]['value']=='1,234' and rows[0]['currency']=='人民币' and rows[0]['unit']=='百万元'
    assert rows[0]['as_of']=='2025-12-31' and rows[0]['fact'] in pages[1]['text']
    assert '重复扣减' in rows[0]['stage_note'] and '56,789' not in rows[0]['fact']
    assert not goodwill_impairment_rows([{'page':22,'text':audit()},{**pages[1],'page':24}],TARGET,BASE)
    pages[1]['text']=pages[1]['text'].replace('錄得','可能錄得')
    assert not goodwill_impairment_rows(pages,TARGET,BASE)
