import json
import io
import zipfile
from types import SimpleNamespace

import re

from docx_exporter import markdown_to_docx_bytes
from report_agents.report_prompts import (
    _focused_cleaned_json,
    classify_company_fact_scope,
    company_section_density,
    company_section_evidence_budget,
)
from report_agents.report_style import REPORT_CHAPTER_HEADING_RE, normalize_report_headings
from research_workflow import ResearchWorkflow


def _source(index: int, module: str = "教育与履历", source_type: str = "news", metadata=None):
    return SimpleNamespace(
        id=index,
        title=f"来源{index}",
        url=f"https://news.example.com/{index}",
        source_type=source_type,
        content=f"这是第{index}条可核验公开资料，包含足够正文内容用于规则清洗和证据台账。" * 3,
        summary="",
        source_metadata=metadata or {"module": module, "quality": {"score": 70}},
        credibility_score=70,
    )


def _project(sources, target_type="company"):
    return SimpleNamespace(
        id=1,
        title="测试项目",
        target_name="测试对象",
        target_type=target_type,
        industry="",
        description="",
        sources=sources,
    )


def test_deterministic_cleaning_has_no_global_source_cutoff():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    sources = [_source(index, module=f"模块{index % 9}") for index in range(1, 131)]

    selected = workflow._select_cleaning_sources(sources, project=_project(sources))

    assert len(selected) == 130
    assert {source.id for source in selected} == set(range(1, 131))


def test_fast_cleaning_records_every_safe_source_in_evidence_ledger(monkeypatch):
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    sources = [_source(index, module=f"模块{index % 4}") for index in range(1, 21)]
    project = _project(sources)
    monkeypatch.setenv("CLEANING_LLM_ENABLED", "false")

    result = json.loads(
        workflow.clean_sources(
            project,
            plan={"modules": []},
            quality={"source_count": len(sources), "module_counts": {}, "information_gaps": []},
        )
    )

    assert len(result["evidence_ledger"]) == len(sources)
    assert result["coverage_summary"]["ledgered_source_count"] == len(sources)
    assert result["coverage_summary"]["deterministically_cleaned_source_count"] == len(sources)
    assert all(row["deterministically_cleaned"] for row in result["evidence_ledger"])


def test_malformed_llm_gap_objects_cannot_trigger_global_cleaning_fallback(monkeypatch):
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    sources = [_source(1)]
    project = _project(sources)
    monkeypatch.setenv("CLEANING_LLM_ENABLED", "true")
    monkeypatch.setattr(
        workflow,
        "_clean_batches_with_llm",
        lambda *_args, **_kwargs: {
            "facts": [],
            "discarded_patterns": [{"pattern": "模型返回对象而非字符串"}],
            "information_gaps": [
                {"reason": "监管材料需要补充"},
                ["需补充权威来源", {"detail": "主体一致性待复核"}],
            ],
        },
    )

    result = json.loads(
        workflow.clean_sources(
            project,
            plan={"modules": []},
            quality={"source_count": 1, "module_counts": {}, "information_gaps": []},
        )
    )

    assert "监管材料需要补充" in result["information_gaps"]
    assert "主体一致性待复核" in result["information_gaps"]
    assert "模型返回对象而非字符串" in result["discarded_patterns"]
    assert result["evidence_ledger"]


def test_cleaning_payload_normalizes_object_and_single_fact_shapes():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    payload = workflow._normalize_cleaning_payload(
        {
            "facts": {"fact": "单条事实", "source_url": "https://source.example.com/1"},
            "discarded_patterns": {"description": "网页噪声"},
            "information_gaps": {"missing": "未提供官方记录"},
        }
    )

    assert len(payload["facts"]) == 1
    assert payload["discarded_patterns"] == ["网页噪声"]
    assert payload["information_gaps"] == ['{"missing": "未提供官方记录"}']


def test_one_llm_batch_exception_is_isolated_from_other_cleaning_results(monkeypatch):
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = _project([])
    monkeypatch.setattr(workflow, "_invoke", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("provider unavailable")))

    result = workflow._clean_batches_with_llm(
        project,
        {"modules": []},
        {"information_gaps": []},
        ["来源批次一", "来源批次二"],
    )

    assert result["facts"] == []
    assert len(result["information_gaps"]) == 2
    assert all("已保留规则清洗事实" in item for item in result["information_gaps"])


def test_section_package_is_small_and_source_diverse():
    facts = [
        {
            "fact": f"目标人物第{index}项教育与履历事实。",
            "module": "教育与履历",
            "source_title": f"来源{index}",
            "source_url": f"https://source.example.com/{index}",
            "quality_score": 80,
        }
        for index in range(30)
    ]
    payload = _focused_cleaned_json(
        json.dumps({"facts": facts}, ensure_ascii=False),
        "创始人底色画像",
        ["教育与履历"],
        "目标人物",
        "person",
    )
    selected = json.loads(payload)["facts"]

    assert 8 <= len(selected) <= 15
    assert len({item["source_url"] for item in selected}) == len(selected)


def test_person_report_gets_deterministic_audit_index_from_fact_library():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = _project([], target_type="person")
    project.target_name = "目标人物"
    facts = [
        {
            "fact": f"目标人物第{index}条教育、履历与经营相关公开事实。",
            "module": "教育与履历",
            "source_title": f"权威来源{index}",
            "source_url": f"https://evidence.example.com/{index}",
            "quality_score": 90,
        }
        for index in range(1, 61)
    ]
    report = workflow._append_person_report_evidence_index(
        project,
        "## 1. 摘要\n\n报告正文。",
        json.dumps({"facts": facts}, ensure_ascii=False),
    )

    assert "## 14. 信息来源（自动生成审计索引）" in report
    assert "E-" in report
    assert "https://evidence.example.com/1" in report
    assert "已纳入章节证据包的唯一来源：" in report


def test_industry_scope_is_safe_for_non_expert_input():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = _project([], target_type="industry")
    project.target_name = "互联网"
    project.industry = "互联网"
    project.description = "帮我看中国互联网行业的投资机会，重点看即时零售和 AI 应用"

    intake = workflow._normalize_intake(
        project,
        {"target_type": "industry", "industry": "互联网", "special_requirements": project.description},
        [],
        [],
    )

    scope = intake["industry_scope"]
    assert scope["geography"] == "中国大陆"
    assert {"即时零售", "AI应用"} <= set(scope["segments"])
    assert scope["purpose"] == "投资判断"
    assert scope["capital_market"] == "summary"
    assert scope["assumptions"]


def test_industry_report_gets_a_deterministic_ledger_in_chapter_14():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = _project([], target_type="industry")
    project.target_name = "互联网"
    project.industry = "互联网"
    titles = [title for title, _requirements in __import__("report_agents.industry_report_agent", fromlist=["INDUSTRY_REPORT_OUTLINE"]).INDUSTRY_REPORT_OUTLINE]
    facts = [
        {
            "fact": f"互联网行业第{index}项可审计公开事实，含统计期、地域和数据口径。",
            "module": titles[(index - 1) % len(titles)],
            "source_title": f"权威来源{index}",
            "source_url": f"https://evidence.example.com/industry/{index}",
            "quality_score": 90,
            "date": "2026-07-18",
        }
        for index in range(1, 91)
    ]
    report = "\n\n".join(f"## {index}. {title}\n\n章节正文。" for index, title in enumerate(titles, 1))

    result = workflow._append_report_evidence_index(project, report, json.dumps({"facts": facts}, ensure_ascii=False))

    assert "## 14. 信息来源（自动生成审计索引）" in result
    assert "| 支持章节 | 核心来源定位 | 覆盖说明 |" in result
    assert "E-" in result
    used,total=map(int,re.search(r'已纳入章节证据包的唯一来源：(\d+) / 清洗事实库可追溯来源：(\d+)',result).groups())
    # Delivery selection is bounded; all original fact sources stay in the
    # ledger. Requiring all 90 in the Word index defeated its readability cap.
    assert 30 <= used <= total == 90
    assert 'https://evidence.example.com/industry/' in result


def test_industry_scope_card_is_inserted_before_first_report_chapter():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = _project([], target_type="industry")
    project.industry_scope = {
        "industry_name": "互联网",
        "segments": ["平台经济"],
        "geography": "中国大陆",
        "as_of_date": "2026-07-18",
        "purpose": "日常了解",
        "capital_market": "none",
        "scope_confidence": "medium",
        "assumptions": ["默认范围"],
    }
    report = workflow._prepend_industry_scope_card(project, "# 行业研究\n\n## 1. 摘要\n\n正文")

    assert report.index("研究边界与口径（自动生成）") < report.index("## 1. 摘要")
    assert "中国大陆" in report


def test_low_confidence_same_name_fact_stays_out_of_person_report_package():
    payload = _focused_cleaned_json(
        json.dumps(
            {
                "facts": [
                    {
                        "fact": "同名人士的无关任职信息。",
                        "source_url": "https://example.com/ambiguous",
                        "eligible_for_report": False,
                    },
                    {
                        "fact": "目标人物的已确认履历信息。",
                        "source_url": "https://example.com/confirmed",
                        "module": "教育与履历",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        "创始人底色画像",
        ["教育与履历"],
        "目标人物",
        "person",
    )

    urls = {item["source_url"] for item in json.loads(payload)["facts"]}
    assert "https://example.com/ambiguous" not in urls
    assert "https://example.com/confirmed" in urls


def test_report_evidence_packages_keep_person_company_and_industry_match_rules_separate():
    facts = [
        {
            "fact": "目标人物可审计事实。",
            "source_url": "https://example.com/person",
            "identity_match": "mismatch",
            "entity_match": "confirmed",
            "scope_match": "in_scope",
        },
        {
            "fact": "目标人物可审计事实。",
            "source_url": "https://example.com/company",
            "identity_match": "confirmed",
            "entity_match": "mismatch",
            "scope_match": "in_scope",
        },
        {
            "fact": "目标人物可审计事实。",
            "source_url": "https://example.com/industry",
            "identity_match": "confirmed",
            "entity_match": "confirmed",
            "scope_match": "out_of_scope",
        },
    ]
    payload = json.dumps({"facts": facts}, ensure_ascii=False)

    person = json.loads(_focused_cleaned_json(payload, "履历", ["教育"], "目标人物", "person"))["facts"]
    company = json.loads(_focused_cleaned_json(payload, "经营", ["业务"], "目标公司", "company"))["facts"]
    industry = json.loads(_focused_cleaned_json(payload, "市场", ["市场规模"], "目标行业", "industry"))["facts"]

    assert {item["source_url"] for item in person} == {"https://example.com/company", "https://example.com/industry"}
    assert {item["source_url"] for item in company} == set()
    assert {item["source_url"] for item in industry} == {"https://example.com/person", "https://example.com/company"}


def test_company_package_rejects_query_echo_and_keeps_source_title_anchor():
    facts = [
        {
            "fact": "TargetCo is mentioned in this generated query summary.",
            "source_title": "OtherCo financing news",
            "source_url": "https://example.com/other",
            "entity_match": "confirmed",
        },
        {
            "fact": "Hiring evidence for TargetCo.",
            "source_title": "TargetCo hiring notice",
            "source_url": "https://example.com/target",
            "entity_match": "confirmed",
        },
        {
            "fact": "This page does not directly involve TargetCo.",
            "source_title": "TargetCo query result",
            "source_url": "https://example.com/negative",
            "entity_match": "confirmed",
        },
    ]
    result = json.loads(
        _focused_cleaned_json(
            json.dumps({"facts": facts}),
            "Team",
            ["Hiring"],
            "TargetCo",
            "company",
        )
    )

    assert {item["source_url"] for item in result["facts"]} == {"https://example.com/target"}


def test_docx_exporter_creates_real_external_hyperlinks_for_plain_urls():
    payload = markdown_to_docx_bytes(
        "| 来源 | URL |\n| --- | --- |\n| 官方 | https://example.com/evidence |",
        title="超链接测试",
    )
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        relationships = archive.read("word/_rels/document.xml.rels").decode("utf-8")
        document = archive.read("word/document.xml").decode("utf-8")

    assert "relationships/hyperlink" in relationships
    assert 'TargetMode="External"' in relationships
    assert '<w:hyperlink r:id=' in document


def test_docx_exporter_marks_only_quality_passed_output_as_delivery_version():
    payload = markdown_to_docx_bytes("# Report\n\n## 1. Summary", title="Delivery", review_draft=False)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        cover = archive.read("word/document.xml").decode("utf-8")
        footer = archive.read("word/footer1.xml").decode("utf-8")
    assert "证据可追溯桌面研究交付版" in cover
    assert "证据可追溯桌面研究交付版" in footer


def test_docx_exporter_excludes_chinese_sentence_punctuation_from_url_target():
    payload = markdown_to_docx_bytes("来源：https://example.com/evidence）。", title="超链接清洗测试")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        relationships = archive.read("word/_rels/document.xml.rels").decode("utf-8")

    assert 'Target="https://example.com/evidence"' in relationships
    assert "evidence）" not in relationships


def test_docx_exporter_stops_url_before_full_width_colon_and_following_text():
    payload = markdown_to_docx_bytes(
        "Source: https://example.com/evidence\uFF1Athis explanation is not part of the URL.",
        title="URL boundary test",
    )
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        relationships = archive.read("word/_rels/document.xml.rels").decode("utf-8")

    assert 'Target="https://example.com/evidence"' in relationships
    assert "explanation" not in relationships


def test_person_relationship_graph_keeps_company_nodes_separate_from_people():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    source = _source(
        1,
        source_type="business_database",
        metadata={
            "provider": "tyc",
            "content_kind": "structured_data",
            "target": "蚂蚁集团",
            "person_affiliation": {
                "person_name": "马云",
                "affiliation_name": "蚂蚁集团",
                "canonical_company_name": "蚂蚁科技集团股份有限公司",
                "relationship_type": "联合创办",
            },
        },
    )
    source.content = "法定代表人：张三\n| 姓名 | 职务 |\n| 张三 | 董事长 |"
    project = _project([source], target_type="person")
    project.target_name = "马云"

    nodes = workflow._professional_graph_nodes(project, "relationship")

    assert any("蚂蚁科技集团股份有限公司" in name for name, _relation, _note in nodes)
    assert all(name != "张三" for name, _relation, _note in nodes)


def test_company_relationship_graph_does_not_repeat_equity_shareholders():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    source = _source(
        1,
        source_type="business_database",
        metadata={
            "provider": "qcc_company",
            "content_kind": "structured_data",
            "entity_validation": "verified",
            "query": "京东集团股份有限公司",
            "module": "股东高管",
            "tool": "get_shareholder_info",
        },
    )
    source.url = "structured://qcc_company/shareholders"
    source.content = "\n".join(
        [
            "| 企业名称 | 京东集团股份有限公司 |",
            "| 股东名称 | 持股比例 |",
            "| 宿迁聚合数字企业管理有限公司 | 60% |",
            "| 北京红杉鸿德股权投资中心（有限合伙） | 40% |",
            "| 姓名 | 职务 |",
            "| 刘强东 | 董事长 |",
        ]
    )
    project = _project([source], target_type="company")
    project.target_name = "京东集团股份有限公司"

    equity_nodes = workflow._professional_graph_nodes(project, "equity")
    relationship_nodes = workflow._professional_graph_nodes(project, "relationship")

    assert any("宿迁聚合数字企业管理有限公司" in name for name, _relation, _note in equity_nodes)
    assert all("股东/投资方" not in relation for _name, relation, _note in relationship_nodes)


def test_professional_fields_are_extracted_without_llm_and_keep_person_boundary():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    source = _source(
        1,
        source_type="business_database",
        metadata={
            "provider": "qcc",
            "content_kind": "structured_data",
            "target": "蚂蚁集团",
            "canonical_company_name": "蚂蚁科技集团股份有限公司",
            "person_affiliation": {
                "person_name": "马云",
                "affiliation_name": "蚂蚁集团",
                "canonical_company_name": "蚂蚁科技集团股份有限公司",
            },
        },
    )
    source.url = "structured://qcc/company/ant"
    source.content = "企业名称：蚂蚁科技集团股份有限公司\n统一社会信用代码：91110108MA01234567\n法定代表人：张三\n注册资本：100万元"
    project = _project([source], target_type="person")
    project.target_name = "马云"

    facts = workflow._extract_professional_structured_facts([source], project)

    assert {item["field"] for item in facts} >= {"统一社会信用代码", "法定代表人", "注册资本"}
    assert all(item["category"] == "person_affiliation_structured" for item in facts)
    assert all(item["eligible_for_risk_scoring"] is False for item in facts)
    assert all("\u4e0d\u5f97\u5f52\u56e0\u4e3a\u76ee\u6807\u4eba\u7269" in item["attribution_boundary"] for item in facts)
    source.source_metadata['canonical_company_name']='另一家公司股份有限公司'
    assert workflow._extract_professional_structured_facts([source],project)==[]


def test_company_ledger_uses_actual_body_citations_and_allows_cross_chapter_reuse():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = _project([], target_type="company")
    project.target_name = "TargetCo"
    titles = [
        title
        for title, _requirements in __import__(
            "report_agents.company_report_agent", fromlist=["COMPANY_REPORT_OUTLINE"]
        ).COMPANY_REPORT_OUTLINE
    ]
    facts = [
        {
            "fact": f"TargetCo verifiable company fact {index}",
            "module": titles[(index - 1) % 12],
            "source_title": f"TargetCo authoritative source {index}",
            "source_url": f"https://evidence.example.com/company/{index}",
            "entity_match": "confirmed",
            "quality_score": 90,
        }
        for index in range(1, 91)
    ]
    facts.extend(
        {
            "fact": f"Unrelated result {index}",
            "source_title": f"Unrelated source {index}",
            "source_url": f"https://noise.example.com/{index}",
            "entity_match": "mismatch",
        }
        for index in range(1, 41)
    )
    facts = workflow._annotate_evidence_facts(project, facts)
    cited_id = facts[0]["evidence_id"]
    report = "\n\n".join(
        f"## {index}. {title}\n\nCompany chapter body. [{cited_id}]" if index in {2, 9}
        else f"## {index}. {title}\n\n本次已检索公开来源未形成可引用记录；相关核验事项见第14章。"
        for index, title in enumerate(titles, 1)
    )

    result = workflow._append_report_evidence_index(project, report, json.dumps({"facts": facts}))

    assert "目标主体匹配可用来源：90" in result
    assert "https://noise.example.com" not in result
    assert result.count(f"| {cited_id} |") == 1
    assert "第 2 章" in result
    assert "第 9 章" in result


def test_company_evidence_scope_keeps_context_but_rejects_negative_or_unrelated_pages():
    direct = {
        "source_title": "TargetCo company registration",
        "evidence_quote": "TargetCo registered capital is 10 million.",
        "source_url": "https://example.com/direct",
    }
    context = {
        "source_title": "Embodied AI market outlook",
        "evidence_quote": "Robot competition and market growth are discussed.",
        "category": "industry",
        "source_url": "https://example.com/context",
    }
    negative = {
        "source_title": "AnotherCo financing news",
        "evidence_quote": "This article does not directly involve TargetCo.",
        "source_url": "https://example.com/noise",
    }
    assert classify_company_fact_scope(direct, "TargetCo") == "target_direct"
    assert classify_company_fact_scope(context, "TargetCo") == "industry_context"
    assert classify_company_fact_scope(negative, "TargetCo") == "noise"


def test_company_scope_rejects_target_name_echoed_only_by_search_summary():
    echoed_query = {
        "source_title": "AnotherCo financing news",
        "evidence_quote": "For the user query TargetCo financing, this page discusses AnotherCo.",
        "fact": "TargetCo financing search result summary.",
        "source_url": "https://example.com/another-company",
    }
    assert classify_company_fact_scope(echoed_query, "TargetCo") == "noise"


def test_structured_company_scope_rechecks_enterprise_name_inside_old_cleaned_fact():
    old_cleaned_fact = {
        "fact": "| 企业名称 | 京东科技控股股份有限公司 |\n| 统一社会信用代码 | 91110302053604529E |",
        "evidence_quote": "| 企业名称 | 京东科技控股股份有限公司 |",
        "source_title": "企查查-get_company_registration_info-京东集团股份有限公司",
        "source_url": "structured://qcc_company/公司背景/企查查-get_company_registration_info-京东集团股份有限公司",
        "is_structured_evidence": True,
        "source_entity_validation": "verified",
        "entity_match": "confirmed",
        "eligible_for_report": True,
    }

    assert classify_company_fact_scope(old_cleaned_fact, "京东集团股份有限公司") == "related_entity_context"


def test_structured_no_hit_is_kept_in_raw_ledger_but_not_as_a_company_fact():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    assert workflow._is_structured_no_hit_text("企业名称：TargetCo；搜索结果：已全量扫描，未发现任何记录。")


def test_company_template_fallback_never_reuses_noise_facts():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = _project([], target_type="company")
    project.target_name = "TargetCo"
    project.title = "TargetCo"
    project.industry = "robotics"
    project.description = ""
    report = workflow._fallback_report(project, json.dumps({"facts": [
        {"fact": "TargetCo official fact", "source_title": "TargetCo official", "source_url": "https://example.com/target"},
        {"fact": "AnotherCo fact", "source_title": "AnotherCo", "evidence_quote": "For the user query TargetCo", "source_url": "https://example.com/noise"},
    ]}), "{}")
    assert "TargetCo official fact" in report
    assert "AnotherCo fact" not in report


def test_persistent_company_evidence_ids_are_stable_and_noise_is_not_report_eligible():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = _project([], target_type="company")
    project.target_name = "TargetCo"
    facts = workflow._annotate_evidence_facts(project, [
        {
            "source_title": "TargetCo official profile",
            "evidence_quote": "TargetCo profile",
            "source_url": "https://example.com/target",
        },
        {
            "source_title": "AnotherCo profile",
            "evidence_quote": "This article does not directly involve TargetCo.",
            "source_url": "https://example.com/other",
        },
    ])
    assert facts[0]["evidence_id"].startswith("E-")
    assert facts[0]["evidence_scope"] == "target_direct"
    assert facts[1]["evidence_scope"] == "noise"
    assert facts[1]["eligible_for_report"] is False
    assert facts[0]["evidence_id"] == workflow._stable_evidence_id(
        "https://example.com/target", "TargetCo official profile"
    )


def test_company_audit_index_keeps_stable_id_and_clickable_original_url():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = _project([], target_type="company")
    project.target_name = "TargetCo"
    titles = __import__("report_agents.company_report_agent", fromlist=["COMPANY_REPORT_OUTLINE"]).COMPANY_REPORT_OUTLINE
    report = "\n\n".join(
        f"## {idx}. {title}\n\nBody. [E-ABC123DEF456]" if idx == 2
        else f"## {idx}. {title}\n\n本次已检索公开来源未形成可引用记录；相关核验事项见第14章。"
        for idx, (title, _requirements) in enumerate(titles, 1)
    )
    result = workflow._append_report_evidence_index(project, report, json.dumps({"facts": [{
        "evidence_id": "E-ABC123DEF456",
        "fact": "TargetCo registration fact",
        "source_title": "TargetCo official record",
        "evidence_quote": "TargetCo registration",
        "source_url": "https://example.com/target-record",
        "entity_match": "confirmed",
    }]}))
    assert "E-ABC123DEF456" in result
    assert "https://example.com/target-record" in result


def test_company_quality_gate_accepts_sparse_but_fully_traceable_fourteen_chapter_report():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = _project([], target_type="company")
    titles = __import__("report_agents.company_report_agent", fromlist=["COMPANY_REPORT_OUTLINE"]).COMPANY_REPORT_OUTLINE
    evidence_id = "E-ABC123DEF456"
    chapters = []
    for index, (title, _requirements) in enumerate(titles, 1):
        if index == 2:
            body = f"工商登记显示目标公司处于存续状态。[{evidence_id}]"
        elif index == 13:
            body = (
                "| 证据编号 | 支持章节 | 来源与关键摘要 | 台账定位 |\n"
                "| --- | --- | --- | --- |\n"
                f"| {evidence_id} | 第 2 章 | 官方工商记录 | 原始链接 → https://issuer.test/company |\n\n"
                "> 已纳入章节证据包的唯一来源：1 / 清洗事实库可追溯来源：1。目标主体匹配可用来源：1。"
            )
        elif index == 14:
            body = "本次桌面研究未形成额外待核验事项。"
        else:
            body = "本次已检索公开来源未形成可引用记录；相关核验事项见第14章。"
        chapters.append(f"## {index}. {title}\n\n{body}")

    workflow._validate_delivery_report(project, "\n\n".join(chapters))


def test_company_audit_index_keeps_structured_business_evidence_referenced_by_body():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = _project([], target_type="company")
    project.target_name = "TargetCo"
    titles = __import__("report_agents.company_report_agent", fromlist=["COMPANY_REPORT_OUTLINE"]).COMPANY_REPORT_OUTLINE
    evidence_id = "E-STRUCT123456"
    report = "\n\n".join(
        f"## {index}. {title}\n\nStructured registration fact [{evidence_id}]"
        if index == 2 else f"## {index}. {title}\n\nPlaceholder"
        for index, (title, _requirements) in enumerate(titles[:12], 1)
    )
    result = workflow._append_report_evidence_index(project, report, json.dumps({"facts": [{
        "evidence_id": evidence_id,
        "evidence_scope": "target_direct",
        "entity_match": "confirmed",
        "fact": "TargetCo registration record",
        "source_title": "QCC company registration",
        "source_url": "structured://qcc/company/targetco-registration",
        "provider": "qcc",
    }]}))

    assert f"| {evidence_id} |" in result
    assert "结构化记录 → qcc / QCC company registration" in result


def test_company_risk_normalization_binds_source_title_to_evidence_id():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    cleaned = json.dumps({"facts": [{
        "evidence_id": "E-ABC123DEF456",
        "evidence_scope": "target_direct",
        "fact": "目标公司涉及一项待核验诉讼。",
        "source_title": "最高法知识产权法庭",
        "source_url": "https://example.com/court",
    }]}, ensure_ascii=False)
    risk = {"dimensions": [{
        "name": "法律合规风险",
        "score": 50,
        "level": "medium",
        "reason": "存在诉讼线索。",
        "evidence_sources": ["最高法知识产权法庭"],
    }]}

    normalized = workflow._normalize_company_risk_evidence(risk, cleaned)

    assert normalized["dimensions"][0]["evidence_ids"] == ["E-ABC123DEF456"]
    assert normalized["dimensions"][0]["score"] == 50


def test_company_docx_evidence_ids_link_to_chapter_13_bookmarks():
    evidence_id = "E-ABC123DEF456"
    markdown = f"""
## 1. 摘要

关键事实。[{evidence_id}]

## 13. 信息来源（自动生成审计索引）

| 证据编号 | 支持章节 | 来源与关键摘要 | 台账定位 |
| --- | --- | --- | --- |
| {evidence_id} | 第 1 章 | 官方记录 | 原始链接 → https://example.com/source |

## 14. 后续研究建议

待核验。
"""
    payload = markdown_to_docx_bytes(markdown, title="公司报告")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        document = archive.read("word/document.xml").decode("utf-8")

    assert 'w:name="evidence_E_ABC123DEF456"' in document
    assert 'w:anchor="evidence_E_ABC123DEF456"' in document


def test_company_audit_index_lists_unresolved_body_evidence_ids():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = _project([], target_type="company")
    project.target_name = "TargetCo"
    report = "## 1. 摘要\n\nBody cites a legacy id [E-MISSING123456].\n\n## 14. 后续研究建议\n\n待核验。"

    result = workflow._append_report_evidence_index(project, report, json.dumps({"facts": [{
        "evidence_id": "E-OTHER123456",
        "evidence_scope": "target_direct",
        "fact": "TargetCo registration record",
        "source_title": "TargetCo official record",
        "source_url": "https://example.com/target-record",
    }]}))

    assert "| E-MISSING123456 |" in result
    assert "待回溯事实卡" in result


def test_report_placeholder_urls_are_removed_before_export():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    report = "## 3. 历史沿革与融资\n\n股权结构图：https://example.com/jd_stock_structure.png"

    cleaned = workflow._normalize_report_placeholders(report)

    assert "example.com" not in cleaned
    assert "图谱证据：待系统根据结构化事实生成或由人工补充真实来源。" in cleaned


def test_company_agent_does_not_call_model_for_empty_evidence_chapters():
    agent_cls = __import__("report_agents.company_report_agent", fromlist=["CompanyReportAgent"]).CompanyReportAgent
    agent = agent_cls()
    project = _project([], target_type="company")
    project.title = "SparseCo"
    project.target_name = "SparseCo"
    project.industry = "robotics"
    project.description = ""
    calls = []

    def invoke(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("empty company chapters must not invoke the model")

    report = agent.generate(
        project,
        json.dumps({"facts": [], "information_gaps": ["核验工商档案"]}, ensure_ascii=False),
        "{}",
        invoke,
        lambda text, limit: text[:limit],
        lambda *args, **kwargs: None,
    )

    assert calls == []
    assert sum(1 for index in range(1, 15) if f"## {index}." in report) == 14
    assert "本次已检索公开来源未形成可引用记录" in report


# ---------------------------------------------------------------------------
# Heading normalisation tests
# ---------------------------------------------------------------------------


def test_heading_regex_matches_canonical_format():
    valid = [
        "## 1. 摘要",
        "## 12. 综合评价",
        "## 14. 后续研究建议",
        "## 2. 主体工商基本信息核查股东关系与治理底盘",
    ]
    for heading in valid:
        assert REPORT_CHAPTER_HEADING_RE.match(heading), f"Should match: {heading!r}"


def test_heading_regex_matches_unicode_separators():
    variants = [
        "## 1. 摘要",
        "## 1．摘要",
        "## 1、摘要",
        "## 1）摘要",
        "## 1) 摘要",
    ]
    for heading in variants:
        assert REPORT_CHAPTER_HEADING_RE.match(heading), f"Should match: {heading!r}"


def test_heading_regex_rejects_subheadings():
    invalid = [
        "### 1.1 子章节",
        "#### 1. 深嵌套",
        "# 1. 单井号",
        "##  摘要",
        "## 1摘要",
        "## 1.2 invalid sub-heading",
    ]
    for heading in invalid:
        assert not REPORT_CHAPTER_HEADING_RE.match(heading), f"Should NOT match: {heading!r}"


def test_normalize_report_headings_fixes_single_hash():
    report = "# 1. 摘要\n\nSome content.\n\n# 2. Wrong Title\n\nMore content."
    expected = {1: "摘要", 2: "主体工商基本信息核查股东关系与治理底盘"}
    result = normalize_report_headings(report, expected)
    assert "## 1. 摘要" in result
    # The original "# 1. 摘要" line must be gone (no line starts with single-# chapter heading)
    assert not any(line.startswith("# 1.") for line in result.split("\n"))
    assert "## 2. 主体工商基本信息核查股东关系与治理底盘" in result


def test_normalize_report_headings_fixes_wrong_separators():
    report = "## 1: 摘要\n\n## 2 - Wrong Title\n\n## 3) Another Title"
    expected = {1: "摘要", 2: "主体工商基本信息核查股东关系与治理底盘", 3: "历史沿革与融资"}
    result = normalize_report_headings(report, expected)
    assert "## 1. 摘要" in result
    assert "## 2. 主体工商基本信息核查股东关系与治理底盘" in result
    assert "## 3. 历史沿革与融资" in result


def test_normalize_report_headings_preserves_subheadings():
    report = "### 1.1 Subsection\n\ncontent\n\n## 2. 主体工商基本信息核查股东关系与治理底盘\n\nMore."
    expected = {1: "摘要", 2: "主体工商基本信息核查股东关系与治理底盘"}
    result = normalize_report_headings(report, expected)
    assert "### 1.1 Subsection" in result
    assert "## 2. 主体工商基本信息核查股东关系与治理底盘" in result


def test_normalize_report_headings_skips_unexpected_chapters():
    """Chapters not in expected_headings must be left unchanged."""
    report = "# 99. Extra Chapter\n\ncontent\n\n## 1. 摘要\n\ntext"
    expected = {1: "摘要"}
    result = normalize_report_headings(report, expected)
    assert "# 99. Extra Chapter" in result
    assert "## 1. 摘要" in result


def test_heading_regex_consistent_across_all_agents():
    """The centralized regex must match the same set as the legacy patterns."""
    canonical = "## 5. 行业口碑、产品认可度与同业竞争地位研判"
    # Legacy company-agent pattern (without ）) )
    company_legacy = r"(?m)^##\s*(\d{1,2})\s*(?:[、．]|\.(?!\d))\s*[^\n]+$"
    assert re.match(company_legacy, canonical)
    assert REPORT_CHAPTER_HEADING_RE.match(canonical)
    # Person-agent variants (with ）) )
    for variant in ["## 1）摘要", "## 5) 标题"]:
        assert REPORT_CHAPTER_HEADING_RE.match(variant), f"Should match person variant: {variant!r}"




def test_company_report_outline_matches_standard_delivery_structure():
    titles = [
        title
        for title, _requirements in __import__(
            "report_agents.company_report_agent", fromlist=["COMPANY_REPORT_OUTLINE"]
        ).COMPANY_REPORT_OUTLINE
    ]

    assert titles == [
        "\u6458\u8981",
        "\u4e3b\u4f53\u5de5\u5546\u57fa\u672c\u4fe1\u606f\u6838\u67e5\u80a1\u4e1c\u5173\u7cfb\u4e0e\u6cbb\u7406\u5e95\u76d8",
        "历史沿革与成长质量",
        "\u7ec4\u7ec7\u6cbb\u7406\u4e0e\u8fd0\u8425\u7ba1\u7406\u8bc4\u4f30",
        "\u884c\u4e1a\u53e3\u7891\u3001\u4ea7\u54c1\u8ba4\u53ef\u5ea6\u4e0e\u540c\u4e1a\u7ade\u4e89\u5730\u4f4d\u7814\u5224",
        "\u4e3b\u8425\u4e1a\u52a1\u771f\u5b9e\u7ecf\u8425\u60c5\u51b5\u6838\u9a8c",
        "\u6838\u5fc3\u7ba1\u7406\u56e2\u961f\u98ce\u9669\u7814\u5224",
        "\u4f01\u4e1a\u6587\u5316\u53ca\u4eba\u5458\u6d41\u5931\u60c5\u51b5",
        "\u4f01\u4e1a\u53f8\u6cd5\u8d1f\u9762\u6838\u67e5",
        "\u5b9a\u5411\u7a7f\u900f\u4e13\u9879\u5c3d\u804c\u8c03\u67e5",
        "\u98ce\u9669\u6838\u67e5",
        "\u7efc\u5408\u8bc4\u4ef7",
        "\u4fe1\u606f\u6765\u6e90",
        "\u540e\u7eed\u7814\u7a76\u5efa\u8bae",
    ]


# ---------------------------------------------------------------------------
# Entity validation tests
# ---------------------------------------------------------------------------


def test_structured_entity_matches_rejects_mismatched_enterprise_name():
    """When structured content has a 企业名称 field, compare against target."""
    wf = ResearchWorkflow()
    content = "企业名称| 京东科技控股股份有限公司\n统一社会信用代码| 91110108MA01ABCDEF"
    metadata = {"query": "京东集团股份有限公司"}
    ok, reason = wf._structured_entity_matches_request(content, metadata, None)
    assert not ok, f"Should reject, got: {reason}"
    assert "mismatch" in reason


def test_structured_entity_matches_accepts_matching_enterprise_name():
    """When the 企业名称 field matches the target, accept it."""
    wf = ResearchWorkflow()
    content = "企业名称| 京东集团股份有限公司\n统一社会信用代码| 91110108MA01ABCDEF"
    metadata = {"query": "京东集团股份有限公司"}
    ok, reason = wf._structured_entity_matches_request(content, metadata, None)
    assert ok, f"Should accept, got: {reason}"


def test_structured_entity_rejects_brand_to_subsidiary():
    """A short brand search must not resolve to a tech subsidiary."""
    wf = ResearchWorkflow()
    content = "企业名称| 京东科技控股股份有限公司"
    metadata = {"query": "京东"}
    ok, reason = wf._structured_entity_matches_request(content, metadata, None)
    assert not ok, f"Should reject tech subsidiary for short brand, got: {reason}"


def test_structured_entity_accepts_short_brand_core_entity():
    """A short brand matching a core registered entity without branch terms is ok."""
    wf = ResearchWorkflow()
    content = "企业名称| 京东集团股份有限公司"
    metadata = {"query": "京东"}
    ok, reason = wf._structured_entity_matches_request(content, metadata, None)
    assert ok, f"Should accept core entity, got: {reason}"


def test_structured_entity_accepts_full_name_exact_match():
    """When target IS a full legal name, accept subsidiary-like name with same brand."""
    wf = ResearchWorkflow()
    content = "企业名称| 北京京东世纪贸易有限公司"
    metadata = {"query": "北京京东世纪贸易有限公司"}
    ok, reason = wf._structured_entity_matches_request(content, metadata, None)
    assert ok, f"Full legal name should accept its own match, got: {reason}"


def test_structured_entity_requires_exact_full_legal_name_not_substring():
    wf = ResearchWorkflow()
    content = "企业名称| 京东集团股份有限公司（科技业务主体）\n统一社会信用代码| 91110108MA01ABCDEF"
    ok, reason = wf._structured_entity_matches_request(content, {"query": "京东集团股份有限公司"}, None)
    assert not ok
    assert reason == "enterprise_name_field_mismatch"


def test_structured_mismatched_group_member_is_retained_only_as_related_context():
    wf = ResearchWorkflow()
    content = "企业名称| 京东科技控股股份有限公司\n统一社会信用代码| 91110108MA01ABCDEF"
    metadata = {"query": "京东集团股份有限公司"}
    ok, _reason = wf._structured_entity_matches_request(content, metadata, None)
    assert not ok
    assert wf._structured_entity_is_related_context(content, metadata, None)


def test_company_semantic_chapter_matching_does_not_require_section_keyword_echo():
    facts = [{
        "fact": "2023年年度报告披露资产负债和现金流变化。",
        "evidence_quote": "年度报告披露资产负债和现金流变化。",
        "source_title": "TargetCo 2023 Annual Report",
        "source_url": "https://example.com/annual-report",
        "entity_name": "TargetCo",
        "source_grade": "A",
    }]
    package = json.loads(_focused_cleaned_json(
        json.dumps({"facts": facts}, ensure_ascii=False),
        "主营业务与经营情况核验",
        ["业务真实性", "经营表现"],
        "TargetCo",
        "company",
    ))
    assert len(package["facts"]) == 1
    assert "financial_performance" in package["facts"][0]["fact_tags"]


def test_company_chapter_budget_and_density_follow_chapter_evidence_not_company_size():
    assert company_section_evidence_budget("主营业务与经营情况核验") == 15
    assert company_section_evidence_budget("企业文化与人员情况") == 6
    registration = [
        {"fact": "工商登记注册资本信息", "source_url": f"structured://qcc/{index}", "provider": "qcc"}
        for index in range(3)
    ]
    assert company_section_density(registration, "主体工商基本信息核查股东关系与治理底盘") == "rich"


def test_structured_entity_falls_back_to_name_scan_when_no_enterprise_field():
    """If no 企业名称 field, fall back to legacy name-scanning behaviour."""
    wf = ResearchWorkflow()
    content = "Some other content mentioning 京东集团股份有限公司 in the body."
    metadata = {"query": "京东集团股份有限公司"}
    ok, reason = wf._structured_entity_matches_request(content, metadata, None)
    assert ok, f"Legacy name scan should still work, got: {reason}"


def test_structured_entity_fails_large_content_with_no_names():
    """Substantial content with no matching names must not be silently accepted."""
    wf = ResearchWorkflow()
    content = "A" * 300
    metadata = {"query": "京东集团股份有限公司"}
    ok, reason = wf._structured_entity_matches_request(content, metadata, None)
    assert not ok, f"Large unnamed content should be rejected, got: {reason}"
    assert "no_parseable" in reason
