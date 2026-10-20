import io
import json
import re
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from industry_claims import public_source_type, claim_contract_issues, industry_gap_plan
from industry_research import annotate_fact, append_evidence_index, mark_unverified_numbers, claim_semantic_issues
from docx_exporter import markdown_to_docx_bytes
from report_agents.industry_proposal import build_industry_proposal
from research_workflow import ResearchWorkflow

NS = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def card(eid='E-111111111111', **updates):
    return {'evidence_id':eid, 'source_url':'https://stats.example/report', 'source_title':'原始统计表',
        'fact':'2024年机器人同比增长54%。', 'module':'市场规模与增长', 'date':'2025-03-01',
        'numeric_context':{'metric':'同比增长率','value':54,'unit':'%','period':'2024','geography':'中国大陆','definition':'机器人行业同比'},
        'numeric_validation':{'passed':True}, 'eligible_for_risk_scoring':True,
        'evidence_scope':'industry_level', **updates}


@pytest.mark.parametrize('url,expected', [
    ('https://www.cac.gov.cn/policy','government'),
    ('https://disc.static.szse.cn/filing.pdf','filing'),
    ('https://www.dehenglaw.com/监管新规','web_search'),
    ('https://court.gov.cn.evil.example/政府处罚','web_search'),
    ('https://news.example/article?next=https://samr.gov.cn','web_search'),
    ('https://www.samr.gov.cn/law','regulatory')])
def test_source_authority_cannot_be_granted_by_title_or_url_substring(url, expected):
    assert public_source_type(url)==expected
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    actual=w._detect_source_type(url,'法院监管处罚的政策原文',url)
    assert actual not in {'government','regulatory','court','filing'} if expected=='web_search' else actual==expected


def test_old_law_firm_government_classification_is_demoted_without_mutation():
    original=card(source_url='https://www.dehenglaw.com/analysis',source_type='government',source_grade='A')
    checked=annotate_fact(original, {'industry_name':'机器人','as_of_date':'2026-10-14'})
    assert checked['source_type']=='web_search' and checked['source_grade']=='C'
    assert original['source_type']=='government'
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    w._is_structured_professional_source=lambda source:False
    source=SimpleNamespace(source_metadata={},source_type='government',url=original['source_url'],title='监管新规解读',content='',summary='')
    assert w._source_grade(source)=='C'


def test_industry_graph_never_reads_company_board_nodes_or_writes_assets():
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    w._professional_graph_nodes=lambda *a: pytest.fail('sector read corporate governance nodes')
    p=SimpleNamespace(target_type='industry',sources=[])
    report='## 2. 产业链\n### 核心关系网络图\n![核心关系网络图](old.svg)\n> 注：本图根据已取得的结构化证据生成；待核验。\n正文保留。'
    assert w._build_relationship_graph_svg(p,'{}')==''
    cleaned=w._append_professional_evidence_assets(p,report,'{}')
    assert '董事' not in cleaned and '关系网络图' not in cleaned and 'old.svg' not in cleaned
    assert '正文保留' in cleaned
    assert 'mermaid' not in w._append_professional_evidence_assets(p,'```mermaid\ngraph TD; AI-->董事\n```\n正文保留。','{}')


@pytest.mark.parametrize('text',[
    '| 54% | E-111111111111 | 已验证 | 待核验 |',
    '三项证据充分的投资机会，高确定性增长。'])
def test_conflicting_or_uncited_certainty_is_rejected(text):
    assert 'evidence_status_conflict' in {r['code'] for r in claim_contract_issues(text,[card()])}


def test_unverified_table_annotation_does_not_create_an_extra_column():
    text='| 市场 | 192亿元 | E-111111111111 | 已验证 |'
    updated=mark_unverified_numbers(text,[card()])
    assert updated.count('|')==text.count('|')
    assert '已验证' not in updated and '待核验' in updated


def test_count_is_not_a_concentration_metric_even_with_a_pending_suffix():
    text='企业超过6200家，表明供给端高度碎片化 E-111111111111 （待核验）'
    assert 'concentration_inference_unsupported' in {r['code'] for r in claim_contract_issues(text,[card()])}
    assert not claim_contract_issues('企业数量不能证明行业高度碎片化 E-111111111111',[card()])


def test_growth_comparison_rejects_cross_period_but_accepts_same_period_rates():
    a=card();b=card('E-222222222222',numeric_context={**a['numeric_context'],'value':22.5,'period':'2025'})
    text='基础层同比54%高于行业同比22.5% E-111111111111 E-222222222222'
    assert 'growth_comparison_unsupported' in {r['code'] for r in claim_contract_issues(text,[a,b])}
    b['numeric_context']['period']='2024'
    assert not claim_contract_issues(text,[a,b])


def test_missing_statistics_does_not_establish_deteriorating_business():
    assert claim_contract_issues('市场统计口径混乱，增长可持续性存疑。',[])[0]['code']=='evidence_gap_as_business_risk'
    assert not claim_contract_issues('统计口径不一致不能证明需求不振。',[])


def test_direct_verified_concentration_metric_is_not_rejected():
    f=card(numeric_context={**card()['numeric_context'],'metric':'CR3集中度','value':15})
    assert not claim_contract_issues('行业高度分散，CR3为15% E-111111111111',[f])


@pytest.mark.parametrize('text,code',[
    ('人工智能生成合成内容标识办法。\n强制标准（2025年3月起施行）','policy_effective_date_conflict'),
    ('欧盟AI Act对高风险系统违规最高罚7%全球营业额。','policy_penalty_scope_conflict'),
    ('欧盟AI Act高风险系统最高罚7%，该数值待核验。','policy_penalty_scope_conflict'),
    ('政策原文 E-111111111111','policy_primary_source_missing')])
def test_known_policy_attribution_errors_are_rejected(text,code):
    assert code in {r['code'] for r in claim_contract_issues(text,[card(source_url='https://law.example/analysis')])}


def test_correct_policy_dates_and_penalty_distinctions_are_not_rejected():
    text='人工智能生成合成内容标识办法2025年3月发布，2025年9月1日起施行。\nAI Act禁止的实践最高罚7%，不能泛化为高风险系统一般违规。'
    assert not claim_contract_issues(text,[])


def test_source_index_deduplicates_chapters_and_exports_original_urls():
    f=card();report='## 1. 摘要\nE-111111111111\n## 2. 定义\nE-111111111111\n## 15. 信息来源\n旧\n## 16. 后续研究'
    indexed,meta=append_evidence_index(report,{'facts':[f]},[('章节',[])]*16,{i:{'facts':[f]} for i in range(1,17)})
    assert indexed.count('https://stats.example/report')==1
    assert '第1、2章' in indexed and '原始统计表' in indexed
    assert meta['referenced_sources']==1
    with ZipFile(io.BytesIO(markdown_to_docx_bytes(indexed,document_kind='industry_report'))) as z:
        assert b'https://stats.example/report' in z.read('word/_rels/document.xml.rels')


def test_legacy_extra_table_notes_are_merged_without_losing_content():
    md='## 1. 测试\n| 项目 | 数值 |\n| --- | --- |\n| A | 192亿元 | （待核验）\n'
    with ZipFile(io.BytesIO(markdown_to_docx_bytes(md))) as z:
        root=ET.fromstring(z.read('word/document.xml'))
        assert {len(r.findall('w:tc',NS)) for r in root.findall('.//w:tr',NS)}=={2}
        assert '待核验' in ''.join(root.itertext())


def test_word_retains_compact_link_label_and_real_external_target():
    with ZipFile(io.BytesIO(markdown_to_docx_bytes('正文 [E-111111111111](https://stats.example/report)'))) as z:
        root=ET.fromstring(z.read('word/document.xml'))
        assert 'E-111111111111' in ''.join(root.itertext())
        assert 'https://stats.example/report' not in ''.join(root.itertext())
        assert b'https://stats.example/report' in z.read('word/_rels/document.xml.rels')


def test_gap_appendix_excludes_headings_and_does_not_claim_search_actions():
    w=ResearchWorkflow.__new__(ResearchWorkflow)
    report='## 16. 后续研究点\n待核验事项：\n集中式待核验清单（本章）\n- 行业市场规模的统计期间与分母定义待核验。\n- 语音专利统计的期间和范围待核验。'
    result=w._consolidate_report_verification_gaps(report,target_type='industry')
    appendix=result.split('## 集中式待核验清单')[-1]
    assert '| 待核验事项： |' not in appendix
    assert '已执行' not in appendix and '统一社会信用代码' not in appendix
    assert '原始统计表' in appendix and '正式文件编号' in appendix


def test_proposal_reflects_actual_unknowns_and_uses_pending_cover_and_navigation():
    p=SimpleNamespace(title='机器人研究',target_name='机器人',industry_scope={'capital_market':'none','named_companies':[]})
    risk={'dimensions':[{'name':'竞争格局与集中度风险','score':None,'unknown_cause':'缺少CR3和份额分母'},
                        {'name':'资本风险','score':None}]}
    md=build_industry_proposal(p,risk_json=json.dumps(risk,ensure_ascii=False))
    assert '缺少CR3和份额分母' in md and '报价确认表' in md and '修改轮次' in md
    assert '| 资本市场 | 仅在启用' not in md and '| 核心企业 | 仅对' not in md
    assert re.findall(r'^## (\d+)\.',md,re.M)==[str(i) for i in range(1,8)]
    with ZipFile(io.BytesIO(markdown_to_docx_bytes(md,title='建议书',document_kind='industry_proposal',review_draft=True))) as z:
        root=ET.fromstring(z.read('word/document.xml'));text=''.join(root.itertext())
        assert '项目建议书待确认稿' in text and '桌面研究交付版' not in text
        assert len(root.findall('.//w:bookmarkStart',NS))==7
        assert len(root.findall('.//w:fldSimple',NS))==7
        assert b'updateFields' in z.read('word/settings.xml')
        assert all(len({len(r.findall('w:tc',NS)) for r in t.findall('w:tr',NS)})==1 for t in root.findall('.//w:tbl',NS))
