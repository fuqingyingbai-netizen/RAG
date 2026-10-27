"""Regression: overseas beneficial ownership must survive compact writing."""
from types import SimpleNamespace
import pytest

from report_agents.company_governance import governance_graph_nodes, render_beneficial_ownership
from report_agents.company_corpus_writer import render_compact_chapters
from test_company_beneficial_ownership import package, source_pair, NAME
from report_agents.company_report_agent import COMPANY_REPORT_OUTLINE
from research_workflow import ResearchWorkflow
import research_workflow as rw


def test_beneficial_graph_retains_disclosure_kind_dates_and_zero_without_aggregate():
    p=package(source_pair())
    nodes=governance_graph_nodes(p, 'beneficial')
    assert len(nodes)==2
    assert nodes[0]==('趙一','披露实益持股 0.1%','2025-05-18')
    assert nodes[1][1]=='披露实益持股 0.0%'
    assert governance_graph_nodes(p,'equity')==[]
    assert governance_graph_nodes(p,'relationship')==[]


def test_distinct_periods_and_conflicting_values_do_not_collapse_to_one_node():
    p=package(source_pair(1), source_pair(2,raw=source_pair()[1]['content'].replace('0.1%', '0.3%')))
    assert len([n for n in governance_graph_nodes(p,'beneficial') if n[0]=='趙一'])==2


def test_compact_writer_keeps_original_columns_and_holder_footnote():
    p=SimpleNamespace(target_name=NAME,company_governance_package=package(source_pair()))
    group={'chapter':2,'aspect':COMPANY_REPORT_OUTLINE[1][1][0],'summary':'已核对的原文归纳。','evidence_ids':['E-000000000001']}
    sections=render_compact_chapters(p,{'groups':[group]},COMPANY_REPORT_OUTLINE,{2:''})
    text=sections[2]
    for value in ('12,000','1,500','0.0%','13,000','原表合计，非独立主体','8,000股股份並不具有任何金錢權益','2025-05-18','E-000000000001'):
        assert value in text
    assert render_beneficial_ownership(p.company_governance_package) in text


def test_real_svg_has_disclosed_interest_date_and_boundary(monkeypatch):
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    p=SimpleNamespace(id=1,target_name=NAME,title=NAME,target_type='company',sources=[],company_governance_package=package(source_pair()))
    blobs=[]
    monkeypatch.setattr(rw.research_store,'put_bytes',lambda key,blob,mime:blobs.append(blob.decode()))
    key=w._build_relationship_graph_svg(p,'{}',title='披露实益持股关系示意图',graph_kind='beneficial')
    assert key and len(blobs)==1
    assert all(x in blobs[0] for x in ('披露实益持股0.1%','2025-05-18','不等于登记持股','趙一'))
    assert '全體董事及高級管理人員合計' not in blobs[0]


def test_missing_eligible_graph_fails_delivery_instead_of_silent_skip(monkeypatch):
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    p=SimpleNamespace(target_type='company',company_governance_package=package(source_pair()))
    monkeypatch.setattr(w,'_build_relationship_graph_svg',lambda *a,**k:'')
    with pytest.raises(ValueError,match='已有合格关系证据'):
        w._append_professional_evidence_assets(p,'## 2. 工商治理\n\n## 3. 沿革','{}')


def test_graph_appears_inside_relationship_section_and_absence_is_explained():
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    report='## 2. 工商治理\n\n### 股东/实控人/关联方关系网图\n\n### 治理底盘判断\n原文。\n\n## 3. 沿革\n'
    result=w._insert_company_governance_graphs(report,'','','local/beneficial.svg')
    assert result.index('![披露实益持股') < result.index('### 治理底盘判断')
    assert '不等于登记持股' in result
    result=w._insert_company_governance_graphs(report,'','')
    assert '关系图暂缺，不能据此认定不存在相关关系' in result
    assert result.index('关系图证据覆盖说明') < result.index('### 治理底盘判断')
