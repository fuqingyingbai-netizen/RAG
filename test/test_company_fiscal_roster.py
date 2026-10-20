"""Generic explicit annual-roster fixtures, not live company evidence."""
from copy import deepcopy

import pytest

from report_agents.company_management import (
    simple_annual_roster_rows,narrative_annual_biographies,latest_roles,period_date,
)

PERIOD='2026财年年度报告（截至2026-03-31）'


def pages():
    return [{'page':165,'text':'董事及高級管理人員\n姓名\n(1)\n年齡 職位╱職銜\n'
             '王甲\n†(a) 50 主席\nJ. Michael GREEN\n†(b) 45 董事兼總裁\n'
             '李乙 40 首席法務官\n趙丙 38 電商事業群首席執行官\n'
             '† 本公司提名的董事。\n(a) 本屆任期至2027年股東大會，不能推算為12月31日。\n'
             '履歷資料\n王甲於2000年加入本公司，擁有遠山大學碩士學位。\n'
             'J. Michael  GREEN 於2010年加入本公司，擁有青禾學院學士學位。\n'
             '李乙自2015年加入本公司，曾任法律顧問，擁有法學碩士學位。\n'
             '趙丙現任電商事業群首席執行官，於2012年加入公司。\n'
             '公司合夥\n我們於2011年成立合夥制度，管理層可選舉新成員。\nB. 薪酬\n與個人履歷不同。'}]


def test_explicit_name_age_title_table_keeps_native_names_and_qualified_business_role():
    rows=simple_annual_roster_rows(pages(),PERIOD)
    assert len(rows)==4
    assert [(x['entity'],x['role']) for x in rows]==[
        ('王甲','主席'),('J. Michael GREEN','董事兼总裁'),('李乙','首席法务官'),('趙丙','电商事业群首席执行官')]
    assert '總裁' in rows[1]['source_role']


def test_fiscal_year_end_does_not_invent_roster_effective_date_or_tenure():
    rows=simple_annual_roster_rows(pages(),PERIOD)
    assert period_date(PERIOD)=='2026-03-31'
    assert all(r['as_of']=='' and r['start']=='未绑定任期起始' for r in rows)
    assert all(r['document_period_end']=='2026-03-31' for r in rows)
    assert all('2027-12-31' not in r['fact'] for r in rows)


@pytest.mark.parametrize('kind',['candidates','employees','meeting','awards'])
def test_candidate_employee_meeting_and_award_tables_do_not_become_management_rosters(kind):
    p=deepcopy(pages())
    if kind=='candidates':p[0]['text']=p[0]['text'].replace('董事及高級管理人員','董事及高級管理人員候選名單')
    if kind=='employees':p[0]['text']=p[0]['text'].replace('董事及高級管理人員','員工名冊')
    if kind=='meeting':p[0]['text']=p[0]['text'].replace('年齡 職位╱職銜','出席次數 會議名稱')
    if kind=='awards':p[0]['text']=p[0]['text'].replace('年齡 職位╱職銜','行權價 持有股份 授予日 到期日')
    assert simple_annual_roster_rows(p,PERIOD)==[]


def test_meeting_name_is_still_not_a_position_with_an_age_column():
    p=pages();p[0]['text']=p[0]['text'].replace('50 主席','50 董事會會議')
    assert '王甲' not in {r['entity'] for r in simple_annual_roster_rows(p,PERIOD)}


def test_document_order_uses_declared_fiscal_end_without_claiming_a_role_start():
    current=simple_annual_roster_rows(pages(),PERIOD)
    older=deepcopy(current[0]);older.update(period='2025财年年度报告（截至2025-03-31）',document_period_end='2025-03-31')
    result=latest_roles([older]+current)
    wang=next(rows for name,rows in result if name=='王甲')
    assert len(wang)==1 and wang[0]['period']==PERIOD and wang[0]['as_of']==''


def test_native_biographies_allow_english_spacing_and_stop_before_partnership_rules():
    roles=simple_annual_roster_rows(pages(),PERIOD)
    bios=narrative_annual_biographies(pages(),{r['entity'] for r in roles},PERIOD)
    assert len(bios)==4
    english=next(x for x in bios if x['entity']=='J. Michael GREEN')
    assert 'J. Michael  GREEN' in english['fact']
    assert all('公司合夥' not in x['fact'] and '管理層可選舉' not in x['fact'] for x in bios)
    assert all(x['as_of']=='' for x in bios)
