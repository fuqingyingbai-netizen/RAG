"""Financial note boundaries must not create unsupported unpaid balances."""
import pytest

from report_agents.company_diligence import classify_quote, disclosure_rows


BASE={'entity':'青禾食品股份有限公司','source_url':'https://example.com/report.pdf',
      'source_title':'年度报告','evidence_ids':['E-1'],'period':'2025年度报告'}


def rows(text):
    return disclosure_rows({},[{'page':17,'text':text}],BASE)


@pytest.mark.parametrize('heading',['36、 应付账款','7、应付账款','103． 应付账款'])
def test_not_applicable_reason_cannot_borrow_next_numbered_note_balance(heading):
    original=('本期末已到期未支付的应付票据总额为0元。\n'
              '到期未付的原因是：不适用\n'+heading+'\n'
              '(1) 应付账款列示\n√适用 □不适用\n单位：元 币种：人民币\n'
              '项目 期末余额 期初余额\n原材料 823,000.00 761,000.00\n合计 823,000.00 761,000.00')
    assert not [r for r in rows(original) if r['kind']=='payment_pending']


@pytest.mark.parametrize('text',[
    '本集团到期未付的原因是：不适用',
    '本集团到期未付的款项总额为0元',
    '本集团未付款项金额为人民币0.00万元',
    '本集团不存在到期未付的应付票据',
    '本集團並無到期未付的應付票據',
])
def test_negative_or_zero_field_is_not_a_positive_pending_payment(text):
    assert classify_quote(text) is None


def test_date_trimming_does_not_retain_discarded_unpaid_category():
    text=('未付票据情况列示如下\n2025年 2024年\n'
          '于2025年，本集团与关联方青禾商业保理有限公司签订合作协议以协助供应商融资。')
    assert not [r for r in rows(text) if r['kind']=='payment_pending']


def test_actual_pending_balance_and_its_reason_are_preserved():
    text=('于2025年12月31日，由于持票人未发起到期托收，本集团尚有余额为人民币7,123千元的应付票据到期未付。\n'
          '36、 应付账款\n单位：元 币种：人民币\n合计 83,000.00 79,000.00')
    result=[r for r in rows(text) if r['kind']=='payment_pending']
    assert len(result)==1 and '7,123千元' in result[0]['evidence_quote']
    assert '应付账款' not in result[0]['evidence_quote']
    assert '不直接等同违约' in result[0]['mode']


def test_zero_in_a_different_clause_does_not_suppress_actual_pending_balance():
    text='本集团到期未付款项总额为0元；本集团另一笔收购对价尚有人民币120万元未付。'
    assert classify_quote(text)[0]=='payment_pending'


def test_unused_proceeds_remain_a_distinct_disclosure_not_a_payment_proof():
    text='截至2025年12月31日，本集团配售募集资金人民币800万元尚未使用。'
    result=rows(text)
    assert len(result)==1 and result[0]['kind']=='payment_pending'
    assert '未使用' in result[0]['evidence_quote']


def test_empty_entrusted_loan_label_cannot_borrow_deposit_interest_amounts():
    text=('应收利息\n(1). 应收利息分类\n单位：元 币种：人民币\n'
          '项目 期末余额 期初余额\n定期存款 1,230,000.00 13,200,000.00\n'
          '委托贷款\n债券投资\n合计 1,230,000.00 13,200,000.00\n'
          '(2). 重要逾期利息\n□适用 √不适用')
    assert not [r for r in rows(text) if r['kind']=='related_funding']


@pytest.mark.parametrize('text',[
    '本集团本年提供委托贷款人民币500万元，贷款到期日为2027年6月30日。',
    '截至2025年12月31日，本集团委托贷款本金余额为人民币500万元。',
    'The Company obtained an entrusted loan of RMB5,000,000 from its parent company.',
    '截至2025年12月31日，借款人已偿还人民币200万元，剩余借款余额人民币300万元将于2026年12月到期。',
])
def test_actual_loan_transaction_or_balance_is_retained(text):
    result=[r for r in rows(text) if r['kind']=='related_funding']
    assert len(result)==1 and result[0]['evidence_quote']==text
