import sys
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from research_api import _identity_skeleton
from research_workflow import ResearchWorkflow
from report_agents.person_report_agent import PersonReportAgent
from web_search import WebSearchProvider


def test_company_identity_skeleton_from_lightweight_text():
    result = _identity_skeleton(
        "公司名称：北京示例科技有限公司\n统一社会信用代码：91110108MA01234567\n所属行业：人工智能软件",
        "company",
    )
    assert result["company_name"] == "北京示例科技有限公司"
    assert result["official_identifier"] == "91110108MA01234567"
    assert result["industry"] == "人工智能软件"


def test_person_identity_skeleton_includes_affiliation():
    result = _identity_skeleton(
        "姓名：梁浩辉\n公司名称：示例资本有限公司\n职位：董事总经理",
        "person",
    )
    assert result["target_name"] == "梁浩辉"
    assert "示例资本有限公司" in result["affiliation"]
    assert "董事总经理" in result["affiliation"]


def test_bocha_result_is_normalized(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "test-key")
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"code": 200, "data": {"webPages": {"value": [{"name": "示例结果", "url": "https://example.com/a", "snippet": "摘要", "siteName": "示例站"}]}}}
    provider = WebSearchProvider()
    with patch("web_search.requests.post", return_value=response), patch.object(
        provider, "fetch_url", return_value={"status": "done", "content": "抓取后的网页正文", "error": ""}
    ):
        rows = provider._search_bocha("示例查询", 3)
    assert rows[0]["metadata"]["provider"] == "bocha"
    assert rows[0]["url"] == "https://example.com/a"
    assert rows[0]["content"] == "抓取后的网页正文"
    assert rows[0]["metadata"]["fetch_status"] == "done"


def test_pdf_url_returning_html_is_not_sent_to_pdf_parser(monkeypatch):
    response = Mock()
    response.raise_for_status.return_value = None
    response.headers = {"Content-Type": "application/pdf"}
    response.url = "https://example.com/report.pdf"
    response.content = b"<script>location.href='/challenge'</script>"
    provider = WebSearchProvider()
    parser = Mock(side_effect=AssertionError("PDF parser must not be called"))
    monkeypatch.setattr(provider, "_extract_pdf_text", parser)

    with patch("web_search.requests.get", return_value=response):
        result = provider._fetch_url_once(response.url, 3, 1000, "test-agent", "desktop")

    assert result["status"] == "invalid_pdf_response"
    assert result["error"] == "pdf_url_returned_html"
    parser.assert_not_called()


def test_multi_search_quarantines_provider_after_403(monkeypatch):
    provider = WebSearchProvider()
    forbidden = requests.HTTPError("forbidden")
    forbidden.response = Mock(status_code=403)
    failing_engine = Mock(side_effect=forbidden)
    healthy_engine = Mock(return_value=[{"url": "https://example.com/ok", "credibility_score": 80}])
    provider.engines = [("tavily", failing_engine), ("serper", healthy_engine)]
    monkeypatch.setenv("TAVILY_API_KEY", "bad-key")
    monkeypatch.setenv("SERPER_API_KEY", "good-key")

    assert provider.multi_engine_search("first", 5)[0]["url"] == "https://example.com/ok"
    assert provider.multi_engine_search("second", 5)[0]["url"] == "https://example.com/ok"
    assert failing_engine.call_count == 1
    assert healthy_engine.call_count == 2


def test_person_target_is_not_replaced_by_same_name_company():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = SimpleNamespace(
        title="阿里巴巴人物背调", target_name="马云", target_type="person", industry="互联网", description="", sources=[]
    )
    intake = {"target_name": "马云", "target_type": "person", "company_name": "马云", "affiliation": ""}
    prepared = workflow._prepare_structured_entity_intake(project, intake)
    assert prepared.get("structured_target") is None
    assert project.target_name == "马云"


def test_person_affiliated_brand_drives_structured_lookup_without_overwriting_person():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = SimpleNamespace(
        title="马云人物背调", target_name="马云", target_type="person", industry="互联网", description="", sources=[]
    )
    intake = {
        "target_name": "马云",
        "target_type": "person",
        "company_name": "马云",
        "affiliation": "阿里巴巴 / 创始人",
    }
    prepared = workflow._prepare_structured_entity_intake(project, intake)
    assert prepared["structured_target"] == "阿里巴巴"
    assert prepared["associated_company"] == "阿里巴巴"
    assert project.target_name == "马云"


def test_person_role_without_company_does_not_drive_structured_lookup():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = SimpleNamespace(
        title="马云人物背调", target_name="马云", target_type="person", industry="互联网", description="", sources=[]
    )
    prepared = workflow._prepare_structured_entity_intake(
        project,
        {"target_name": "马云", "target_type": "person", "company_name": "马云", "affiliation": "创始人"},
    )
    assert prepared.get("structured_target") is None


def test_person_full_legal_affiliated_company_can_drive_structured_lookup():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = SimpleNamespace(
        title="人物背调", target_name="示例人物", target_type="person", industry="", description="", sources=[]
    )
    prepared = workflow._prepare_structured_entity_intake(
        project,
        {"target_name": "示例人物", "target_type": "person", "affiliation": "北京示例科技有限公司 / CEO"},
    )
    assert prepared["structured_target"] == "北京示例科技有限公司"
    assert project.target_name == "示例人物"


def test_person_search_expands_core_due_diligence_dimensions():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    queries = workflow._expand_search_queries(
        {"modules": []},
        {"target_name": "马云", "target_type": "person", "affiliation": "阿里巴巴 / 创始人", "industry": "互联网"},
    )
    text = "\n".join(item["query"] for item in queries)
    modules = {item["module"] for item in queries}
    assert "教育背景" in text
    assert "工作经历" in text
    assert "裁判文书" in text
    assert "关联交易" in text
    assert "经营业绩" in text
    assert {"身份核验", "教育与履历", "经营业绩", "关联利益", "司法信用"}.issubset(modules)


def test_person_source_filter_rejects_generic_and_same_name_noise():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    intake = {"target_type": "person", "target_name": "马云", "affiliation": "阿里巴巴 / 创始人"}
    assert workflow._person_source_is_relevant("马云人物简介", "阿里巴巴创始人及其教育经历", intake)
    assert not workflow._person_source_is_relevant("个人贷款风险分析", "银行个人信用风险通用知识", intake)
    assert not workflow._person_source_is_relevant("上海马云标识有限公司", "法定代表人马云，经营标识服务", intake)


def test_gap_queries_route_online_sources_and_skip_offline_only_items():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    rows = workflow._gap_queries({}, {"target_name": "示例科技"}, [
        "融资方与工商变更待核验",
        "专利及软件著作权缺少证据",
        "客户合同和银行流水待核验",
    ])
    text = "\n".join(row["query"] for row in rows)
    assert "融资公告" in text
    assert "cnipa.gov.cn" in text
    assert "银行流水" not in text


def test_relationship_graph_replaces_mermaid_inside_existing_section():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    report = """## 2. 工商与治理\n\n### 股东/实控人/关联方关系网图\n\n```mermaid\ngraph LR\nC-->S\n```\n\n节点表。\n\n## 3. 历史沿革\n"""
    result = workflow._insert_relationship_graph(report, "projects/1/relationship.svg", "company")
    assert "graph LR" not in result
    assert result.count("![核心关系网络图]") == 1
    assert result.index("![核心关系网络图]") < result.index("## 3. 历史沿革")


def test_resume_screenshot_builds_person_search_anchors():
    text = """Kevin Leung 梁浩辉
University of Oxford
CFA Charter Holder
BMW ArcherMind (50-50 JV between BMW and ArcherMind) (Nanjing)
The largest digital car software R&D center of BMW in China
Founding CEO"""
    result = _identity_skeleton(text, "person")
    assert result["target_name"] == "Kevin Leung 梁浩辉"
    assert "BMW ArcherMind" in result["affiliation"]
    assert "Founding CEO" in result["affiliation"]
    assert result["industry"] == "汽车软件与数字化研发"
    assert "University of Oxford" in result["identity_anchors"]
    assert "BMW ArcherMind" in result["identity_anchors"]


def test_failed_image_extraction_is_not_used_as_fact():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    source = SimpleNamespace(
        content="[解析失败，原始文件已保留] resume.png RuntimeError: quota exceeded",
        summary="",
        source_metadata={"extraction_status": "failed"},
    )
    assert workflow._is_failed_extraction_source(source)


def test_missing_evidence_is_normalized_to_unknown_not_low_risk():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    result = workflow._normalize_risk_unknowns({
        "overall_score": 10,
        "risk_level": "low",
        "dimensions": [{"name": "法律合规风险", "score": 10, "level": "low", "reason": "未检索到负面记录", "evidence_sources": []}],
    })
    assert result["risk_level"] == "unknown"
    assert result["overall_score"] is None
    assert result["dimensions"][0]["level"] == "unknown"


def test_structured_brand_result_rejects_unverified_vertical_subsidiary():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    ok, reason = workflow._structured_entity_matches_request(
        "企业名称：杭州阿里巴巴广告有限公司",
        {"query": "阿里巴巴"},
        None,
    )
    assert not ok
    assert reason == "brand_query_resolved_to_subsidiary"
    assert not workflow._is_usable_company_anchor("管理有限公司")
    assert workflow._is_usable_company_anchor("阿里巴巴")


def test_person_report_parser_does_not_treat_subheadings_as_chapters():
    report = "## 1. First\n### 1.1 Detail\nbody\n## 2. Second\n### 2.1 Detail\nbody"
    assert set(PersonReportAgent()._split_numbered_sections_strict(report)) == {1, 2}
