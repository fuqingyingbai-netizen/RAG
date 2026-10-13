import re
from typing import Any


COMMON_MODULE_TEMPLATES = {
    "公司背景": ["{target}", "{target} 官网", "{target} 公司简介", "{target} 产品 客户 合作伙伴", "{target} {industry}"],
    "诉讼/制裁": ["{target} 诉讼", "{target} 法院 判决", "{target} 裁判文书", "{target} 行政处罚", "{target} 制裁 黑名单"],
    "负面新闻": ["{target} 负面 新闻", "{target} 风险 舆情", "{target} 投诉", "{target} fraud lawsuit scandal"],
    "股东高管": ["{target} 股东", "{target} 高管", "{target} 董事 监事", "{target} 融资 投资方"],
    "融资情报": ["{target} 融资", "{target} 投资方", "{target} 股权融资", "{target} IPO 上市", "{target} 估值 投融资"],
    "管理团队": ["{target} 管理团队", "{target} 高管 团队", "{target} 董事 监事 经理", "{target} 核心团队"],
    "行业市场": ["{industry} 市场规模", "{industry} 竞争格局", "{industry} 政策 监管", "{industry} 趋势 报告"],
    "风险核查": ["{target} 风险", "{target} 合规 风险", "{target} 经营异常", "{target} 行政处罚", "{target} 被执行人"],
    "技术实力": ["{target} 专利", "{target} 知识产权", "{target} 商标 软件著作权", "{target} 技术 架构"],
}


class BaseResearchStrategy:
    target_type = "company"
    default_modules: list[str] = []
    query_templates: list[tuple[str, str]] = []
    authority_queries: list[dict[str, Any]] = []
    module_templates: dict[str, list[str]] = {}

    def normalize_affiliations(self, value: str) -> list[str]:
        return []

    def templates_for_module(self, module: str, target: str, industry: str) -> list[str]:
        return self.module_templates.get(module) or COMMON_MODULE_TEMPLATES.get(module) or [
            f"{target} {module}",
            f"{target} {module} 风险",
        ]

    def module_questions(self, module: str, target: str, industry: str) -> list[str]:
        if module == "公司背景":
            return [f"{target} 的业务、产品、官网和客户是否清晰？", "主体信息是否能被一手来源验证？"]
        if module == "诉讼/制裁":
            return [f"{target} 是否存在诉讼、处罚、制裁、失信或监管记录？", "是否存在需要重点关注的合规风险？"]
        if module == "行业市场":
            return [f"{industry} 的市场规模、政策和竞争格局是什么？", "行业趋势是否支持当前商业判断？"]
        return [f"{target} 在 {module} 维度有哪些可验证事实？", f"{module} 维度还缺哪些关键证据？"]

    def required_source_types(self, module: str) -> list[str]:
        if module == "诉讼/制裁":
            return ["government", "court", "regulatory", "news"]
        if module == "公司背景":
            return ["official", "business_database", "news"]
        if module == "股东高管":
            return ["official", "business_database", "filing", "news"]
        return ["news", "official", "industry_report"]

    def expand_search_queries(self, plan: dict[str, Any], intake: dict[str, Any]) -> list[dict[str, Any]]:
        target = str(intake.get("target_name") or "").strip()
        industry = str(intake.get("industry") or "").strip()
        affiliations = self.normalize_affiliations(str(intake.get("affiliation") or intake.get("associated_company") or ""))
        affiliation = affiliations[0] if affiliations else ""
        items: list[dict[str, Any]] = []

        def add(module: str, template: str, affiliation_override: str | None = None, **metadata: Any) -> None:
            active_affiliation = affiliation if affiliation_override is None else affiliation_override
            if "{affiliation}" in template and not active_affiliation:
                return
            query = template.format(target=target, industry=industry, affiliation=active_affiliation).strip()
            query = re.sub(r"\s+", " ", query)
            if query:
                items.append({"module": module or "综合", "query": query, "search_tier": "open_web", **metadata})

        for route in self.authority_queries:
            template = str(route["query"])
            anchors = affiliations if "{affiliation}" in template and affiliations else [None]
            for anchor in anchors:
                add(
                    str(route["module"]),
                    template,
                    anchor,
                    search_tier="authority_first",
                    include_domains=list(route.get("domains") or []),
                    preferred_providers=list(route.get("providers") or ["tavily", "exa", "serpapi", "brave", "serper"]),
                    exa_category=route.get("exa_category"),
                    authority_required=int(route.get("min_sources") or 2),
                )
        for module, template in self.query_templates:
            if "{affiliation}" in template and affiliations:
                for anchor in affiliations:
                    add(module, template, anchor)
            else:
                add(module, template)
        for query in intake.get("search_queries") or []:
            add("用户指定", str(query))
        for module in plan.get("modules") or []:
            if not isinstance(module, dict):
                continue
            name = str(module.get("name") or "综合")
            for query in module.get("queries") or []:
                add(name, str(query))
            for template in module.get("query_templates") or self.templates_for_module(name, target, industry):
                if "{affiliation}" in template and affiliations:
                    for anchor in affiliations:
                        add(name, template, anchor)
                else:
                    add(name, template)
        seen: set[tuple[str, tuple[str, ...]]] = set()
        rows: list[dict[str, Any]] = []
        for item in items:
            key = (re.sub(r"\s+", "", item["query"].lower()), tuple(item.get("include_domains") or []))
            if key in seen:
                continue
            seen.add(key)
            rows.append(item)
        rows.sort(key=lambda item: 0 if item.get("search_tier") == "authority_first" else 1)
        return rows
