from types import SimpleNamespace

from research_workflow import ResearchWorkflow
from report_agents.person_report_agent import PersonReportAgent


def _project(**overrides):
    values = {
        "title": "马云2",
        "target_name": "阿里马云",
        "target_type": "person",
        "industry": "",
        "description": "",
        "sources": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_person_editor_cannot_drop_required_sections():
    agent = PersonReportAgent()
    report = agent._ensure_outline_sections("# 报告\n\n## 2. 创始人底色画像\n\n有证据的正文。")
    assert all(f"## {index}." in report for index in range(1, 16))
    assert report.index("## 1.") < report.index("## 2.") < report.index("## 15.")


def test_verification_appendix_rejects_markdown_rows_and_truncation():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    report = """## 1. 摘要

关键合同履约状态待核验。
| 待核验事项 | 为什么公开检索无法确认 |
| 表格中的待核验 | 说明 |
一段非常长且被截断的待核验内容...[truncated]
"""
    result = workflow._consolidate_report_verification_gaps(report)
    appendix = result.split("## 集中式待核验清单", 1)[1]
    assert "关键合同履约状态待核验" in appendix
    assert "表格中的待核验" not in appendix
    assert "...[truncated]" not in appendix


def test_professional_aggregator_is_not_graded_as_primary_evidence():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    source = SimpleNamespace(
        source_metadata={"provider": "tyc", "content_kind": "structured_data_company"},
        source_type="business_database",
        url="structured://tyc/company/1",
        title="工商信息",
        content="",
        summary="",
    )
    assert workflow._source_grade(source) == "B"


def test_person_affiliation_graph_can_fall_back_to_cleaned_facts():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    cleaned = '{"facts":[{"fact":"马云创立阿里巴巴集团。","source_grade":"A"},{"fact":"马云投资云锋基金。","source_grade":"B"}]}'
    nodes = workflow._cleaned_fact_graph_nodes(_project(target_name="马云"), cleaned)
    assert any("阿里巴巴集团" in name for name, _relation, _note in nodes)
    assert any("云锋基金" in name for name, _relation, _note in nodes)


def test_person_name_uses_clean_project_title_when_form_has_company_prefix():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    normalized = workflow._normalize_intake(
        _project(),
        {
            "target_type": "person",
            "company_name": "阿里马云",
            "affiliation": "阿里巴巴等",
            "focus_modules": ["教育背景"],
        },
        [],
        [],
    )

    assert normalized["target_name"] == "马云"


def test_person_identity_filter_ignores_affiliation_placeholder_suffix():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    intake = {
        "target_type": "person",
        "target_name": "马云",
        "affiliation": "阿里巴巴等",
    }

    assert workflow._person_source_is_relevant(
        "马云卸任给阿里巴巴留下了什么",
        "马云是阿里巴巴创始人。",
        intake,
    )


def test_person_identity_filter_still_rejects_same_name_company_noise():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    intake = {
        "target_type": "person",
        "target_name": "马云",
        "affiliation": "阿里巴巴等",
    }

    assert not workflow._person_source_is_relevant(
        "上海马云标识有限公司",
        "法定代表人马云，经营标识服务。",
        intake,
    )


def test_person_affiliation_is_optional_and_name_only_page_is_kept():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    intake = {"target_type": "person", "target_name": "马云", "affiliation": ""}

    assert workflow._person_source_is_relevant(
        "马云人物经历",
        "马云曾从事教育工作，随后开始创业。",
        intake,
    )


def test_name_only_person_source_is_quarantined_not_promoted():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    intake = {"target_type": "person", "target_name": "马云", "affiliation": "阿里巴巴"}

    result = workflow._person_source_identity_confidence(
        "云泽资本合伙人马云投资项目",
        "云泽资本合伙人马云近日参与某项目投资。",
        intake,
    )

    assert result["confidence"] == "low"


def test_known_affiliation_person_source_has_high_identity_confidence():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    result = workflow._person_source_identity_confidence(
        "马云在阿里巴巴活动上发言",
        "阿里巴巴创始人马云参加活动。",
        {"target_type": "person", "target_name": "马云", "affiliation": "阿里巴巴"},
    )

    assert result["confidence"] == "high"


def test_multiple_affiliations_each_expand_to_search_queries():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    rows = workflow._expand_search_queries(
        {"modules": []},
        {
            "target_type": "person",
            "target_name": "马云",
            "affiliation": "阿里巴巴 / 蚂蚁集团 / 云锋基金 / 创始人",
            "industry": "",
        },
    )
    queries = "\n".join(row["query"] for row in rows)

    assert "马云 阿里巴巴 任职 关系" in queries
    assert "马云 蚂蚁集团 任职 关系" in queries
    assert "马云 云锋基金 任职 关系" in queries
    assert "创始人 任职 关系" not in queries


def test_person_authority_queries_run_before_open_web_queries():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    rows = workflow._expand_search_queries(
        {"modules": []},
        {"target_type": "person", "target_name": "马云", "affiliation": "阿里巴巴", "industry": ""},
    )

    first_open_web = next(index for index, row in enumerate(rows) if row.get("search_tier") == "open_web")
    assert first_open_web > 0
    assert all(row.get("search_tier") == "authority_first" for row in rows[:first_open_web])
    assert any("wenshu.court.gov.cn" in row.get("include_domains", []) for row in rows[:first_open_web])
    assert any("hkexnews.hk" in row.get("include_domains", []) for row in rows[:first_open_web])


def test_person_affiliation_discovery_confirms_high_quality_relationships_only():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    sources = [
        SimpleNamespace(
            id=1,
            title="马云投资版图",
            content="公开资料显示，马云联合创办云锋基金，并参与多项长期投资。",
            summary="",
            url="https://example.gov.cn/profile",
            credibility_score=90,
        ),
        SimpleNamespace(
            id=2,
            title="未经证实的讨论",
            content="有人声称马云创办传闻资本，但没有提供依据。",
            summary="",
            url="https://example.invalid/post",
            credibility_score=40,
        ),
    ]

    rows = workflow._discover_person_affiliations(
        sources,
        {"target_type": "person", "target_name": "马云", "affiliation": "阿里巴巴"},
    )

    assert [row["name"] for row in rows] == ["云锋基金"]


def test_affiliation_discovery_does_not_run_for_company_projects():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    assert workflow._discover_person_affiliations([], {"target_type": "company", "target_name": "示例公司"}) == []


def test_person_affiliation_structured_collection_is_bounded_and_non_recursive(monkeypatch):
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    collected = []
    monkeypatch.setenv("PERSON_AFFILIATION_STRUCTURED_LIMIT", "2")
    monkeypatch.setattr(
        workflow,
        "_structured_entity_candidates",
        lambda _project, _intake, target: [f"{target}有限公司", "91110108MA01234567"],
    )

    def fake_collect(_db, _project, intake, emit=None):
        collected.append(dict(intake))
        return 1

    def grouped(_workflow, db, project, jobs, emit=None):
        return sum(fake_collect(db, project, value, emit) for _, value in jobs)
    monkeypatch.setattr('person_platforms.collect_group', grouped)
    intake = {
        "target_type": "person",
        "target_name": "马云",
        "affiliation": "阿里巴巴",
        "confirmed_person_affiliations": [
            {"name": "低排名资本", "host_count": 2, "source_count": 2, "max_score": 80},
            {"name": "蚂蚁集团", "host_count": 4, "source_count": 5, "max_score": 95},
            {"name": "云锋基金", "host_count": 3, "source_count": 3, "max_score": 90},
        ],
    }

    added = workflow.collect_person_affiliation_structured_sources(None, _project(), intake)

    assert added == 2
    assert [row["associated_company"] for row in collected] == ["蚂蚁集团", "云锋基金"]
    assert all(row["confirmed_person_affiliations"] == [] for row in collected)
    assert all(row["structured_target_candidates"][0].endswith("有限公司") for row in collected)
    assert all(row["person_affiliation_context"]["recursion_depth"] == 1 for row in collected)
    assert all("仅执行一跳" in row["person_affiliation_context"]["filtering_note"] for row in collected)


def test_person_affiliation_structured_collection_skips_initial_anchor(monkeypatch):
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    collected = []
    monkeypatch.setattr(workflow, "collect_structured_sources", lambda *_args, **_kwargs: collected.append(1) or 1)
    intake = {
        "target_type": "person",
        "target_name": "马云",
        "affiliation": "阿里巴巴 / 蚂蚁集团",
        "associated_company": "蚂蚁科技集团股份有限公司",
        "structured_target": "蚂蚁科技集团股份有限公司",
        "confirmed_person_affiliations": [
            {"name": "蚂蚁集团", "host_count": 3, "source_count": 3, "max_score": 90}
        ],
    }

    assert workflow.collect_person_affiliation_structured_sources(None, _project(), intake) == 0
    assert collected == []


def test_affiliation_credit_code_must_be_near_the_company_name():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = _project(
        sources=[
            SimpleNamespace(
                title="工商资料",
                summary="",
                content=(
                    "蚂蚁集团工商主体信息，统一社会信用代码：91110108MA01234567。"
                    "另一企业统一社会信用代码：91330100MA01234567。"
                ),
                source_metadata={},
            )
        ]
    )

    assert workflow._credit_code_is_near_affiliation(project, "蚂蚁集团", "91110108MA01234567")
    assert not workflow._credit_code_is_near_affiliation(project, "云锋基金", "91330100MA01234567")


def test_person_affiliation_structured_facts_can_omit_person_name():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    source = SimpleNamespace(
        url="structured://tyc/company/ant",
        source_type="business_database",
        title="天眼查-公司背景-蚂蚁集团",
        content="蚂蚁科技集团股份有限公司，统一社会信用代码：91110108MA01234567。",
        summary="",
        source_metadata={
            "provider": "tyc",
            "content_kind": "structured_data",
            "target": "蚂蚁集团",
            "person_affiliation": {
                "person_name": "马云",
                "affiliation_name": "蚂蚁集团",
                "canonical_company_name": "蚂蚁科技集团股份有限公司",
                "relationship_type": "联合创办",
                "relationship_evidence_source_ids": [1],
                "relationship_evidence_hosts": ["example.gov.cn"],
                "recursion_depth": 1,
            },
        },
    )
    facts = workflow._sanitize_structured_facts(
        [{
            "fact": "蚂蚁科技集团股份有限公司统一社会信用代码为91110108MA01234567。",
            "evidence_quote": "统一社会信用代码：91110108MA01234567。",
            "source_url": source.url,
        }],
        _project(target_name="马云", sources=[source]),
    )

    assert facts[0]["category"] == "person_affiliation_structured"
    assert facts[0]["person_affiliation"]["affiliation_name"] == "蚂蚁集团"


def test_person_report_injects_affiliation_ledger_without_new_section():
    source = SimpleNamespace(
        source_metadata={
            "provider": "qcc",
            "person_affiliation": {
                "person_name": "马云",
                "affiliation_name": "蚂蚁集团",
                "canonical_company_name": "蚂蚁科技集团股份有限公司",
                "relationship_type": "联合创办",
                "relationship_evidence_hosts": ["example.gov.cn", "example.com"],
                "selection_rank": 1,
                "selection_reason": "高置信直接关联入选。",
                "filtering_note": "仅一跳，不递归。",
            },
        },
        content="统一社会信用代码：91110108MA01234567。注册资本：100万元。法定代表人：张三。",
        summary="",
    )
    report = PersonReportAgent()._inject_affiliation_ledger(
        _project(target_name="马云", sources=[source]),
        "## 9. 关联利益冲突及司法负面核查\n\n正文。\n\n## 10. 专项调研 - 示例\n\n正文。",
    )

    assert "关联企业受控穿透台账" in report
    assert "91110108MA01234567" in report
    assert report.index("关联企业受控穿透台账") < report.index("## 10.")


def test_risk_fallback_marks_every_dimension_unknown():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    result = workflow._fallback_risk('{"facts":[{"fact":"涉及诉讼和处罚风险"}]}')

    assert result["overall_score"] is None
    assert result["risk_level"] == "unknown"
    assert all(item["score"] is None and item["level"] == "unknown" for item in result["dimensions"])


def test_utf8_milvus_clip_respects_byte_limit():
    from research_workflow import _clip_utf8_bytes

    result = _clip_utf8_bytes("马云" * 1000, 1900)
    assert len(result.encode("utf-8")) <= 1900


def test_sentence_fallback_keeps_attributed_person_sentences_not_full_pages():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = SimpleNamespace(target_name="马云")
    source = SimpleNamespace(
        title="人物资料",
        url="https://example.com/profile",
        source_type="news",
        content=(
            "网站首页 下载APP。"
            "马云于1999年与团队在杭州创办阿里巴巴，该事件可由公司历史资料进一步核验。"
            "另一段与目标无关的长篇内容不会进入人物事实。"
        ),
        summary="",
        source_metadata={"module": "教育与履历", "provider": "test"},
        credibility_score=80,
    )

    facts = workflow._extract_sentence_facts([source], project)
    assert len(facts) == 1
    assert facts[0]["fact"].startswith("马云于1999年")
    assert facts[0]["claim_type"] == "source_statement"


def test_low_identity_fact_requires_llm_confirmation_before_promotion():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    project = _project(
        target_name="马云",
        sources=[
            SimpleNamespace(
                url="https://example.com/yunze",
                source_metadata={"identity_confidence": "low"},
            )
        ],
    )
    ambiguous = workflow._sanitize_structured_facts(
        [{"fact": "云泽资本合伙人马云投资某项目。", "evidence_quote": "云泽资本合伙人马云", "source_url": "https://example.com/yunze", "identity_match": "ambiguous"}],
        project,
    )
    confirmed = workflow._sanitize_structured_facts(
        [{"fact": "云泽资本合伙人马云投资某项目。", "evidence_quote": "材料同时列明其为阿里巴巴创始人", "source_url": "https://example.com/yunze", "identity_match": "confirmed"}],
        project,
    )

    assert ambiguous == []
    assert len(confirmed) == 1


def test_personal_background_is_retained_but_excluded_from_risk_payload():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    cleaned = '{"facts":[{"fact":"某媒体叙述其早期婚恋经历。","category":"personal_background","eligible_for_risk_scoring":false,"source_url":"https://example.com/story"},{"fact":"马云创办阿里巴巴。","category":"profile","source_url":"https://example.com/profile"}]}'

    payload = workflow._risk_evidence_payload(cleaned)

    assert "早期婚恋" not in payload
    assert "创办阿里巴巴" in payload
