import json
import os
from types import SimpleNamespace

from report_agents.person_report_agent import FALLBACK_MARKER, PersonReportAgent
from research_workflow import ResearchWorkflow


def test_person_fallback_uses_topic_matched_evidence_only():
    payload = {
        "facts": [
            {
                "module": "教育与履历",
                "fact": "目标人物在公开校方记录中出现，任职时间与履历表述一致。",
                "source_title": "校方记录一",
                "source_url": "https://school.example.edu/record-1",
                "confidence": 0.9,
            },
            {
                "module": "身份核验",
                "fact": "目标人物姓名、任职机构及时间三个身份锚点相互吻合。",
                "source_title": "机构记录二",
                "source_url": "https://company.example.com/record-2",
                "confidence": 0.9,
            },
            {
                "module": "知识产权",
                "fact": "某关联企业公开了一项专利。",
                "source_title": "无关专利",
                "source_url": "https://patent.example.com/unrelated",
                "confidence": 0.9,
            },
        ]
    }
    agent = PersonReportAgent()
    selected, _gaps = agent._rank_section_facts(json.dumps(payload, ensure_ascii=False), 2)
    assert {item["module"] for item in selected} == {"教育与履历", "身份核验"}
    section = agent._evidence_backed_section(json.dumps(payload, ensure_ascii=False), 2, "创始人底色画像")
    assert FALLBACK_MARKER in section
    assert "无关专利" not in section


def test_one_url_is_not_a_usable_person_chapter():
    agent = PersonReportAgent()
    section = "## 2. 创始人底色画像\n\n" + ("有来源支持的正文。" * 80) + "\nhttps://one.example.com"
    previous = os.environ.get("PERSON_REPORT_SECTION_MIN_URLS")
    os.environ["PERSON_REPORT_SECTION_MIN_URLS"] = "2"
    try:
        assert not agent._section_is_usable(section, 2)
    finally:
        if previous is None:
            os.environ.pop("PERSON_REPORT_SECTION_MIN_URLS", None)
        else:
            os.environ["PERSON_REPORT_SECTION_MIN_URLS"] = previous


def test_too_many_deterministic_fallbacks_cannot_pass_formal_delivery():
    sections = []
    for index in range(1, 16):
        marker = f"> {FALLBACK_MARKER}\n" if index <= 5 else ""
        body = "本节包含经来源支持的事实、证据边界和后续核验动作。" * 30
        sections.append(
            f"## {index}. 章节{index}\n\n{marker}{body}\n"
            f"https://source.example.com/{index}/a\nhttps://source.example.com/{index}/b"
        )
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    try:
        workflow._validate_delivery_report(SimpleNamespace(target_type="person"), "\n\n".join(sections))
    except RuntimeError as exc:
        assert "证据保底章节过多" in str(exc)
    else:
        raise AssertionError("five deterministic fallbacks must require review")


def test_low_confidence_person_source_is_quarantined_not_fact():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    source = SimpleNamespace(
        title="同名人物负面线索",
        url="https://example.com/same-name",
        source_type="news",
        content="马云，女，1958年12月26日出生，法院悬赏公告。",
        summary="",
        source_metadata={"identity_confidence": "low", "identity_reason": "仅命中姓名"},
        credibility_score=60,
    )
    project = SimpleNamespace(target_type="person", target_name="马云")
    cleaned = workflow._fast_clean_sources([source], project=project)
    assert cleaned["facts"] == []
    assert len(cleaned["identity_quarantine_facts"]) == 1
    assert cleaned["identity_quarantine_facts"][0]["usable_as"] == "identity_quarantine"


def test_ambiguous_identity_fact_cannot_enter_person_section_package():
    payload = {
        "facts": [
            {
                "module": "司法信用",
                "fact": "马云曾被列为失信被执行人。",
                "source_title": "同名人物报道",
                "source_url": "https://example.com/no-anchor",
                "identity_match": "ambiguous",
                "identity_confidence": "low",
                "confidence": 0.8,
            },
            {
                "module": "司法信用",
                "fact": "关联企业层面存在诉讼记录，不能归因为目标人物个人风险。",
                "source_title": "企查查结构化记录",
                "source_url": "structured://qcc_risk/example",
                "category": "person_affiliation_structured",
                "person_affiliation": {"person_name": "马云", "affiliation_name": "阿里巴巴"},
                "identity_match": "confirmed",
                "identity_confidence": "high",
                "confidence": 0.9,
            },
        ]
    }
    agent = PersonReportAgent()
    selected, _gaps = agent._rank_section_facts(json.dumps(payload, ensure_ascii=False), 12)
    assert [item["source_url"] for item in selected] == ["structured://qcc_risk/example"]


def test_person_source_utilization_uses_compact_package_capacity():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    sections = []
    for index in range(1, 16):
        body = (f"本章{index}包含已核验事实、证据边界、关联企业层面说明和后续核验动作。" * 30)
        sections.append(
            f"## {index}. 章节{index}\n\n{body}\n"
            f"https://source.example.com/{index}/a\nhttps://source.example.com/{index}/b"
        )
    report = "\n\n".join(sections) + (
        "\n\n## 审计引用索引（自动生成）\n\n"
        "> 已纳入本报告章节证据包的唯一来源：60 / 清洗事实库可追溯来源：836。"
    )
    workflow._validate_delivery_report(SimpleNamespace(target_type="person"), report)


def test_person_affiliation_anchor_requires_near_target_context():
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    intake = {
        "target_type": "person",
        "target_name": "马云",
        "person_anchor": {"known_affiliations": ["阿里巴巴"], "identity_anchors": []},
    }
    far_content = "马云出席公开活动。" + ("无关段落。" * 160) + "阿里巴巴发布业务公告。"
    near_content = "马云作为阿里巴巴创始人参与公开讨论。"
    assert workflow._person_source_identity_confidence("公开报道", far_content, intake)["confidence"] == "low"
    assert workflow._person_source_identity_confidence("公开报道", near_content, intake)["confidence"] == "high"


def test_secondary_affiliation_facts_do_not_crowd_person_section():
    payload = {
        "facts": [
            {
                "module": "经营胜任力（战略/执行/创新）",
                "fact": "阿里巴巴层面披露了治理和业务调整信息。",
                "source_title": "阿里巴巴结构化记录",
                "source_url": "structured://xiniu/ali/main",
                "category": "person_affiliation_structured",
                "person_affiliation": {"affiliation_name": "阿里巴巴", "selection_rank": 0},
                "identity_match": "confirmed",
                "identity_confidence": "high",
                "confidence": 0.9,
            },
            *[
                {
                    "module": "经营胜任力（战略/执行/创新）",
                    "fact": f"菜鸟网络第{i}条经营扩张信息。",
                    "source_title": f"菜鸟结构化记录{i}",
                    "source_url": f"structured://xiniu/cainiao/{i}",
                    "category": "person_affiliation_structured",
                    "person_affiliation": {"affiliation_name": "菜鸟网络科技有限公司", "selection_rank": 2},
                    "identity_match": "confirmed",
                    "identity_confidence": "high",
                    "confidence": 0.9,
                }
                for i in range(4)
            ],
        ]
    }
    agent = PersonReportAgent()
    selected, _gaps = agent._rank_section_facts(json.dumps(payload, ensure_ascii=False), 4)
    cainiao = [
        item for item in selected
        if (item.get("person_affiliation") or {}).get("affiliation_name") == "菜鸟网络科技有限公司"
    ]
    assert len(cainiao) == 1
