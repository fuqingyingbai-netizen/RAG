import json
from types import SimpleNamespace

import pytest

from person_evidence import (ORDER, append_index, build_packages, cited_ids, generate_person_report,
                             normalize_facts, normalize_person_risk, report_audit, split_sections,
                             temporal_conflicts, validate_model_claims, name_in_text)
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE
from research_strategies.person import PersonResearchStrategy
from research_workflow import ResearchWorkflow
from company_platform import CompanyPlatformAudit


def person(name="林知远"):
    return SimpleNamespace(target_name=name, target_type="person", title="离线合成人物测试", industry="工业软件",
                           description="合成数据不是真实人物调查", sources=[])


def fact(name="林知远", **extra):
    row = {"fact": f"{name}于2021年在恒川软件任职，参与产品战略和团队管理工作。",
           "source_url": "https://fixture.invalid/profile", "source_title": "合成公开原件",
           "identity_match": "confirmed", "identity_confidence": "high", "module": "教育与履历"}
    return {**row, **extra}


def noop(*args, **kwargs):
    pass


def echo(role, prompt, trace):
    pack = json.loads(prompt[prompt.index('{"chapter":'):])
    return json.dumps({"claims": [{"statement": f["fact"], "evidence_ids": [f["evidence_id"]], "analysis": ""}
                                   for f in pack["facts"]]}, ensure_ascii=False)


@pytest.mark.parametrize("name", ["林知远", "陈雨安", "Amelia Hart", "Noah O'Connell", "山田太郎"])
def test_person_generation_is_not_bound_to_one_name(name):
    p = person(name)
    report = generate_person_report(p, json.dumps({"facts": [fact(name)]}), "{}", PERSON_REPORT_OUTLINE, echo, noop)
    assert set(split_sections(report)) == set(range(1, 16))
    assert name in report
    assert "LOOT" not in report and "马云" not in report and "阿里巴巴" not in report
    assert p.person_delivery_diagnostic["generation_order"] == list(ORDER)
    assert p.person_delivery_diagnostic["errors"] == []


@pytest.mark.parametrize("chapter", range(1, 16))
def test_every_template_chapter_has_diagnostic_and_appropriate_source_scope(chapter):
    p = person()
    facts = [fact(fact=f"林知远参与{requirements[0]}相关工作，原件仅披露职责，不提供能力评级。",
                  source_url=f"https://fixture{i}.invalid/record", module=title)
             for i, (title, requirements) in enumerate(PERSON_REPORT_OUTLINE[:13], 1)]
    report = generate_person_report(p, json.dumps({"facts": facts}), "{}", PERSON_REPORT_OUTLINE, echo, noop)
    audit = p.person_delivery_diagnostic
    assert len(audit["chapters"]) == 15
    assert str(chapter) in {str(k) for k in audit["section_diagnostics"]}
    assert not audit["chapters"][chapter-1]["unknown_evidence_ids"]
    if chapter < 14:
        assert cited_ids(split_sections(report)[chapter])
    if chapter == 14:
        assert "原始定位" in split_sections(report)[chapter]
    if chapter == 15:
        assert "优先级" in split_sections(report)[chapter]


def test_sources_in_index_are_actual_body_citations_and_can_repeat_across_chapters():
    cards, _ = normalize_facts({"facts": [fact(), fact(source_url="https://unused.invalid/x")]}, "林知远")
    eid = cards[0]["evidence_id"]
    report = append_index(f"## 1. 摘要\n\n[{eid}]\n\n## 2. 履历\n\n[{eid}]\n\n## 15. 后续研究点\n待核验", cards)
    assert "https://fixture.invalid/profile" in report
    assert "https://unused.invalid" not in report
    assert "1,2" in report
    assert append_index(report, cards) == report
    titled = "# 人物研究底稿\n\n" + report
    assert append_index(titled, cards).startswith("# 人物研究底稿")
    fallback = append_index("# 降级底稿\n\n## 一、执行摘要\n来源不足。", cards)
    assert "## 一、执行摘要" in fallback


def test_ambiguous_identity_never_becomes_a_personal_adverse_finding():
    cards, rejected = normalize_facts({"facts": [fact(identity_match="ambiguous"), fact(identity_confidence="low")]}, "林知远")
    assert not cards
    assert len(rejected) == 2
    assert all(f["rejection_reason"] == "identity_quarantine" for f in rejected)


def test_affiliation_record_keeps_company_boundary_and_cannot_score_person():
    f = fact(fact="恒川软件发生了一起劳动争议。", category="person_affiliation_structured",
             person_affiliation={"person_name": "林知远", "affiliation_name": "恒川软件"})
    cards, _ = normalize_facts({"facts": [f]}, "林知远")
    assert cards[0]["subject_scope"] == "affiliated_company"
    assert cards[0]["eligible_for_risk_scoring"] is False
    assert "不能证明人物" in cards[0]["attribution_boundary"]
    assert not normalize_facts({"facts": [f]}, "陈雨安")[0]


def test_unrelated_facts_do_not_fill_sparse_chapters():
    contract = build_packages({"facts": [fact(fact="林知远在机构中完成学历登记。", module="教育与履历")]}, "林知远", PERSON_REPORT_OUTLINE)
    assert contract["chapters"][2]["facts"]
    assert contract["chapters"][9]["facts"] == []
    assert contract["chapters"][9]["information_gaps"]


def test_disputed_event_dates_are_preserved_as_conflicts_not_arbitrarily_selected():
    cards, _ = normalize_facts({"facts": [fact(fact="林知远于2020年卸任CEO。"),
                                         fact(fact="林知远于2022年卸任CEO。", source_url="https://other.invalid/event")]}, "林知远")
    conflicts = temporal_conflicts(cards)
    assert len(conflicts) == 1
    assert conflicts[0]["values"] == ["2020", "2022"]


def test_foreign_company_and_fabricated_claim_are_rejected_even_with_real_evidence_id():
    contract = build_packages({"facts": [fact()]}, "林知远", PERSON_REPORT_OUTLINE)
    package = contract["chapters"][2]
    eid = package["facts"][0]["evidence_id"]
    claims, reasons = validate_model_claims(json.dumps({"claims": [
        {"statement": "OTHER LABS在2099年融资999亿元。", "evidence_ids": [eid]}]}), package)
    assert claims == [] and "statement_not_in_cited_fact" in reasons


def test_unsupported_analytical_numbers_and_personal_certainties_are_removed():
    package = build_packages({"facts": [fact()]}, "林知远", PERSON_REPORT_OUTLINE)["chapters"][2]
    f = package["facts"][0]
    for analysis in ["该人物的诚信优秀且无任何诉讼。", "2029年已融资900亿元。"]:
        claims, reasons = validate_model_claims(json.dumps({"claims": [
            {"statement": f["fact"], "evidence_ids": [f["evidence_id"]], "analysis": analysis}]}), package)
        assert not claims[0]["analysis"]
        assert "unsupported_analysis" in reasons


def test_quota_failure_stops_further_provider_calls_and_preserves_all_chapters():
    p, calls = person(), []
    def fail(*args):
        calls.append(args[0])
        raise RuntimeError("insufficient_quota")
    report = generate_person_report(p, json.dumps({"facts": [fact()]}), "{}", PERSON_REPORT_OUTLINE, fail, noop)
    assert len(calls) == 1
    assert len(split_sections(report)) == 15
    assert "quota_exceeded" in report
    assert p.person_delivery_diagnostic["errors"]
    workflow = ResearchWorkflow.__new__(ResearchWorkflow)
    with pytest.raises(RuntimeError, match="质量闸门"):
        workflow._validate_delivery_report(p, report)


def test_missing_information_does_not_become_a_risk_score():
    result = normalize_person_risk({"facts": [], "information_gaps": ["未披露个人财务"]})
    assert result["overall_score"] is None
    assert all(d["score"] is None for d in result["dimensions"])


def test_platform_quota_is_audited_per_affiliation_without_mutating_company_audit():
    p = person()
    audit = CompanyPlatformAudit(p, "qcc", "test-only", {}, attribute="person_platform_attempts", subject="恒川软件")
    audit.planned(["registration", "risk"])
    assert audit.result("registration", {}, {"error": "insufficient_quota"})
    assert p.person_platform_attempts[0]["reason"] == "quota_exceeded"
    assert p.person_platform_attempts[1]["status"] == "not_queried"
    assert not hasattr(p, "company_professional_platform_attempts")


def test_queries_cover_all_chapters_without_celebrity_domains():
    rows = PersonResearchStrategy().expand_search_queries({"modules": [{"name": "核心管理团队背景"}]}, {"target_name": "Amelia Hart", "affiliation": "Northwind Robotics"})
    assert set(range(2, 13)) <= {i for r in rows for i in r["person_chapters"]}
    assert not any(x in json.dumps(rows, ensure_ascii=False) for x in ["alibabagroup.com", "antgroup.com", "cainiao.com", "蔡崇信", "马云", "阿里巴巴"])


def test_sparse_profiles_do_not_fail_an_arbitrary_fact_count_threshold():
    result = ResearchWorkflow.__new__(ResearchWorkflow)._validate_person_cleaned_facts([fact()])
    assert result["fact_count"] == 1 and result["requires_human_review"]


def test_long_english_original_is_split_into_attributed_person_sentences():
    p = person("Amelia Hart")
    source = SimpleNamespace(title="Official biography", url="https://fixture.invalid/bio", summary="",
        content=("Navigation text. " * 50) + "Amelia Hart joined the company in 2018 and led product strategy. "
                "Amelia Hart received a university degree in engineering in 2010.",
        source_metadata={"identity_confidence": "high", "module": "教育与履历"}, source_type="official", credibility_score=90)
    facts = ResearchWorkflow.__new__(ResearchWorkflow)._extract_sentence_facts([source], p)
    assert len(facts) == 2
    contract = build_packages({"facts": facts}, p.target_name, PERSON_REPORT_OUTLINE)
    assert contract["chapters"][2]["facts"] and contract["chapters"][4]["facts"]


def test_publication_date_is_not_promoted_to_event_date():
    facts, _ = normalize_facts({"facts": [fact(date="2026-10-19")]}, "林知远")
    assert facts[0]["published_at"] == "2026-10-19"
    assert facts[0]["event_date"] == "未披露"


def test_middle_initial_is_supported_without_matching_arbitrary_middle_names():
    assert name_in_text("Amelia Hart", "Dr. Amelia J. Hart joined the company.")
    assert not name_in_text("Amelia Hart", "Amelia was quoted in a report about Jonathan Hart.")
    assert not name_in_text("Amelia Hart", "Amelia Johnson Hart joined the company.")


def test_workflow_identity_uses_middle_initial_and_near_company_anchor():
    intake = {"target_type": "person", "target_name": "Amelia Hart", "affiliation": "Northwind Robotics",
              "person_anchor": {"aliases": ["Amelia Hart"], "known_affiliations": ["Northwind Robotics"]}}
    result = ResearchWorkflow.__new__(ResearchWorkflow)._person_source_identity_confidence(
        "Official biography", "Dr. Amelia J. Hart is an executive of Northwind Robotics.", intake)
    assert result["confidence"] == "high"


def test_research_cutoff_excludes_later_disclosures_without_deleting_audit():
    contract = build_packages({"facts": [fact(date="2026-10-20")]}, "林知远", PERSON_REPORT_OUTLINE,
                              {"as_of_date": "2026-10-19"})
    assert not contract["facts"]
    assert contract["rejected"][0]["rejection_reason"] == "published_after_research_cutoff"


def test_person_word_export_keeps_actual_citation_jump_and_original_url():
    import io
    import zipfile
    import xml.etree.ElementTree as ET
    from docx_exporter import markdown_to_docx_bytes
    cards, _ = normalize_facts({"facts": [fact()]}, "林知远")
    eid = cards[0]["evidence_id"]
    report = append_index(f"## 2. 创始人底色画像\n来源事实 [{eid}]\n\n## 15. 后续研究点\n待核验", cards)
    data = markdown_to_docx_bytes(report, title="离线合成人物测试", outline=PERSON_REPORT_OUTLINE)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.testzip() is None
        doc = ET.fromstring(archive.read("word/document.xml"))
        rels = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    assert any(x.get(w + "anchor") == "evidence_" + eid.replace("-", "_") for x in doc.iter(w + "hyperlink"))
    assert cards[0]["source_url"] in {x.get("Target") for x in rels}


def test_cleaned_paraphrase_cannot_introduce_numbers_absent_from_original():
    original = "林知远在公开访谈中提及其产品研发职责，但没有披露融资金额。"
    source = SimpleNamespace(url="https://fixture.invalid/profile", content=original)
    cards, rejected = normalize_facts({"facts": [fact(fact="林知远完成900亿元融资。", evidence_quote=original)]},
                                      "林知远", sources=[source])
    assert not rejected
    assert cards[0]["fact"] == original and "900" not in cards[0]["fact"]
    assert cards[0]["original_excerpt_match"]


def test_real_workflow_persists_all_chapters_ledger_and_review_status_on_resume(monkeypatch, tmp_path):
    """Actual ORM/stages/export; external collection, LLM and archive are isolated."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import research_workflow as module
    import report_knowledge
    from models import Base, ResearchProject, ResearchSource, User
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setenv("AUTHORITY_COVERAGE_REQUIRED", "false")
    monkeypatch.setenv("CLEANING_LLM_ENABLED", "false")
    monkeypatch.setenv("RESEARCH_LEGACY_RAG_ENABLED", "false")
    monkeypatch.setattr(module, "FIXED_GENERATE_PROPOSAL", False)
    monkeypatch.setattr(module.research_store, "mode", "local")
    monkeypatch.setattr(module.research_store, "local_root", tmp_path)
    monkeypatch.setattr(report_knowledge, "sync_report_safely", noop)
    w = ResearchWorkflow()
    monkeypatch.setattr(w, "resolve_business_entity", lambda p, intake, **kw: intake)
    for method in ("collect_web_sources", "collect_structured_sources", "collect_person_affiliation_structured_sources", "enrich_ocr_sources"):
        monkeypatch.setattr(w, method, lambda *a, **kw: 0)
    monkeypatch.setattr(w, "_invoke_person_report_section", lambda role, prompt, **kw: echo(role, prompt, None))
    monkeypatch.setattr(w, "_append_professional_evidence_assets", lambda p, report, cleaned, **kw: report)
    monkeypatch.setattr(w, "_render_docx_quality", lambda data: ({"docx_render_status": "not_run_in_offline_test"}, b""))
    monkeypatch.setattr(w, "_finalize_source_records", noop)
    with Session(engine) as db:
        user = User(username="offline-person-audit", password_hash="not-a-login-credential")
        db.add(user)
        db.flush()
        p = ResearchProject(title="林知远人物背景调查", target_name="林知远", target_type="person", industry="软件", description="合成验收", created_by_id=user.id)
        db.add(p)
        db.flush()
        db.add(ResearchSource(project_id=p.id, source_type="official", title="合成机构履历记录", url="https://fixture.invalid/profile",
            content=fact()["fact"], summary="", source_metadata={"identity_confidence": "high", "module": "教育与履历", "person_chapters": [2]}, credibility_score=90))
        db.commit()
        for expected in (1, 2):
            artifacts, _ = w.run_project(db, p, [], [], intake={"target_type": "person", "target_name": "林知远"})
            report = next(a for a in artifacts if a.artifact_type == "desktop_report")
            ledger = next(a for a in artifacts if a.artifact_type == "person_claim_ledger")
            assert report.version == expected and ledger.version == expected
            assert report.artifact_metadata["requires_human_review"]
            assert report.artifact_metadata["delivery_status"] == "review_draft"
            assert report.artifact_metadata.get("docx_object_key")
            assert ledger.object_key.endswith(".json")
            ledger_data = json.loads(ledger.content)
            assert all(f.get("person_chapters") == [2] for f in ledger_data["facts"])
            audit = ledger_data["diagnostic"]
            assert len(audit["chapters"]) == 15
            assert set(split_sections(report.content)) == set(range(1, 16)), report.content[:3500]
            db.expire_all()
