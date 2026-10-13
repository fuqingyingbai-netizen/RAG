from research_strategies import get_research_strategy


def _intake(target_type: str):
    return {
        "target_type": target_type,
        "target_name": "测试对象",
        "industry": "人工智能",
        "affiliation": "测试集团",
    }


def test_each_target_type_has_an_independent_strategy():
    person = get_research_strategy("person")
    company = get_research_strategy("company")
    industry = get_research_strategy("industry")

    assert type(person) is not type(company)
    assert type(company) is not type(industry)
    assert person.target_type == "person"
    assert company.target_type == "company"
    assert industry.target_type == "industry"


def test_authority_routes_are_isolated_by_target_type():
    person_rows = get_research_strategy("person").expand_search_queries({"modules": []}, _intake("person"))
    company_rows = get_research_strategy("company").expand_search_queries({"modules": []}, _intake("company"))
    industry_rows = get_research_strategy("industry").expand_search_queries({"modules": []}, _intake("industry"))

    assert any(row["module"] == "司法信用" for row in person_rows)
    assert not any(row["module"] == "司法信用" for row in company_rows)
    assert any(row["module"] == "企业司法负面核查" for row in company_rows)
    assert not any(row["module"] == "企业司法负面核查" for row in industry_rows)
    assert any(row["module"] == "政策环境分析与近期政策摘录" for row in industry_rows)


def test_authority_queries_use_native_domain_filters():
    for target_type in ("person", "company", "industry"):
        rows = get_research_strategy(target_type).expand_search_queries({"modules": []}, _intake(target_type))
        authority = [row for row in rows if row.get("search_tier") == "authority_first"]
        assert authority
        assert all(row.get("include_domains") for row in authority)
        assert all(row.get("authority_required", 0) >= 1 for row in authority)
