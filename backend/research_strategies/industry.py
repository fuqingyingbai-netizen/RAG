import re
from typing import Any

from .base import BaseResearchStrategy

INDUSTRY_MODULE_ALIASES = {
    "行业定义": "行业定义与边界", "供应商调研": "细分赛道与产业链", "下游渠道": "细分赛道与产业链",
    "终端客户调研": "细分赛道与产业链", "政策环境分析": "政策与监管",
    "市场规模与增长预测": "市场规模与增长", "竞争格局": "竞争格局与代表企业",
    "投融资全景": "投融资与资本市场", "二级市场情绪": "投融资与资本市场",
    "技术路线与壁垒": "技术路线对比", "核心公司尽调": "核心企业尽调",
    "投资机会研判": "商业模式与盈利逻辑",
}

INDUSTRY_PROFILES = (
    (("半导体", "芯片"), "晶圆 制程 封装测试 材料 设备 性能 成本"),
    (("医药", "生物", "医疗"), "研发管线 临床试验 审批进度 商业化 专利"),
    (("机器人",), "控制器 执行器 核心部件 精度 安全 产能"),
    (("新能源", "储能", "电池"), "技术路线 能量效率 寿命 装机容量 产能"),
)


class IndustryResearchStrategy(BaseResearchStrategy):
    target_type = "industry"

    default_modules = [
        "行业定义与边界",
        "细分赛道与产业链",
        "政策与监管",
        "市场规模与增长",
        "竞争格局与代表企业",
        "商业模式与盈利逻辑",
        "技术演进与平台生态",
        "技术路线对比",
        "投融资与资本市场",
        "行业风险与不确定性",
    ]

    query_templates = [
        ("行业定义与边界", "{target} {industry} 定义 边界 子赛道 产业链"),
        ("细分赛道与产业链", "{target} {industry} 细分赛道 产业链 上下游 代表企业"),
        ("政策与监管", "{target} 政策 监管 准入 行业标准"),
        ("市场规模与增长", "{target} 市场规模 需求 渗透率 增速 CAGR"),
        ("竞争格局与代表企业", "{target} {industry} 市场份额 竞争格局 龙头企业 CR3 CR5"),
        ("商业模式与盈利逻辑", "{target} {industry} 商业模式 变现 收入结构 利润率"),
        ("技术演进与平台生态", "{target} 技术进展 产业生态 商业化成熟度"),
        ("技术路线对比", "{target} 技术路线 性能 成本 落地难度"),
        ("投融资与资本市场", "{target} {industry} 投融资 IPO 并购 年报 招股书"),
        ("行业风险与不确定性", "{target} {industry} 行业风险 监管风险 商业化风险 技术替代"),
    ]

    authority_queries = [
        {
            "module": "政策与监管",
            "query": '"{target}" 政策 规划 监管 准入 标准',
            "domains": ["gov.cn", "ndrc.gov.cn", "miit.gov.cn", "samr.gov.cn", "cac.gov.cn"],
            "min_sources": 3,
            "evidence_scope": "industry_level",
        },
        {
            "module": "市场规模与增长",
            "query": '"{target}" 统计 数据 市场规模 渗透率',
            "domains": ["stats.gov.cn", "gov.cn", "miit.gov.cn"],
            "min_sources": 2,
            "evidence_scope": "industry_level",
        },
        {
            "module": "竞争格局与代表企业",
            "query": '"{target}" 市场份额 竞争格局 龙头企业',
            "domains": ["samr.gov.cn", "gov.cn", "cninfo.com.cn", "sse.com.cn", "szse.cn", "hkexnews.hk", "sec.gov"],
            "exa_category": "financial report",
            "min_sources": 2,
            "evidence_scope": "industry_level",
        },
        {
            "module": "投融资与资本市场",
            "query": '"{target}" 上市 年报 招股书 IPO 并购',
            "domains": ["cninfo.com.cn", "sse.com.cn", "szse.cn", "hkexnews.hk", "sec.gov"],
            "exa_category": "financial report",
            "min_sources": 2,
            "evidence_scope": "capital_market",
        },
    ]

    module_templates = {
        "行业定义与边界": [
            "{target} 定义 边界 分类",
            "{target} 子赛道 分类 产业链",
            "{target} 行业报告 定义 边界",
        ],
        "细分赛道与产业链": [
            "{target} 细分赛道 产业链 上下游",
            "{target} 产业链 价值链 代表企业",
            "{target} 产品分类 应用场景 细分市场",
        ],
        "政策与监管": [
            "{target} 政策 监管 行业准入",
            "{target} 国家标准 行业标准 监管",
            "{target} 行业协会 政策解读 合规",
        ],
        "市场规模与增长": [
            "{target} 市场规模 用户规模 渗透率 增速",
            "{target} 官方统计 需求规模 行业数据",
            "{target} 市场规模 统计 口径 地域",
        ],
        "竞争格局与代表企业": [
            "{target} 市场份额 竞争格局 龙头企业",
            "{target} 代表企业 上市公司 年报",
            "{target} CR3 CR5 集中度 市场份额",
        ],
        "商业模式与盈利逻辑": [
            "{target} 商业模式 收入结构 定价",
            "{target} 产业链 收入结构 利润率",
            "{target} 代表企业 年报 收入结构 业务分部",
        ],
        "技术演进与平台生态": [
            "{target} 技术趋势 关键技术 产业生态",
            "{target} 技术进展 研发 商业化",
            "{target} 技术基础设施 核心部件",
        ],
        "技术路线对比": ["{target} 技术路线 性能 成本 商业化成熟度", "{target} 技术路线 优劣势 落地难度"],
        "投融资与资本市场": [
            "{target} 投融资 IPO 并购 融资事件",
            "{target} 上市公司 年报 招股书 业务分部",
            "{target} 一级市场 融资 估值 资本热度",
        ],
        "行业风险与不确定性": [
            "{target} 行业风险 监管风险 商业化风险",
            "{target} 产业链 准入 合规 风险",
            "{target} 技术替代 成本 需求变化 风险",
        ],
    }

    def templates_for_module(self, module: str, target: str, industry: str) -> list[str]:
        canonical = INDUSTRY_MODULE_ALIASES.get(module, module)
        return self.module_templates.get(canonical) or ["{target} " + canonical + " 行业研究 官方来源"]

    def expand_search_queries(self, plan: dict[str, Any], intake: dict[str, Any]) -> list[dict[str, Any]]:
        rows = super().expand_search_queries(plan, intake)
        scope = intake.get("industry_scope") if isinstance(intake.get("industry_scope"), dict) else {}
        segments = [str(item).strip() for item in scope.get("segments", []) if str(item).strip()]
        target = str(intake.get("target_name") or intake.get("industry") or "").strip()
        industry = str(intake.get("industry") or target).strip()
        capital_enabled = scope.get("capital_market") != "none"
        selected = {str(row.get("name")) for row in plan.get("modules", []) if isinstance(row, dict)}

        def classify(module: str, query: str) -> dict[str, Any]:
            if module == "投融资与资本市场":
                return {"evidence_scope": "capital_market"}
            blob = f"{module} {query}"
            if any(word in blob for word in ("代表企业", "龙头", "市场份额", "竞争格局", "年报", "收入结构", "业务分部")):
                return {"evidence_scope": "representative_company", "company_role": "benchmark"}
            if any(word in blob for word in ("投融资", "IPO", "并购", "上市", "估值", "招股书", "资本")):
                return {"evidence_scope": "capital_market"}
            if any(word in blob for word in ("子赛道", "细分", "本地生活", "云服务", "AI", "平台经济")):
                return {"evidence_scope": "segment_level"}
            return {"evidence_scope": "industry_level"}

        enriched: list[dict[str, Any]] = []
        for item in rows:
            row = dict(item)
            if selected and row.get("module") not in selected | {"用户指定"}:
                continue
            if row.get("module") == "核心企业尽调":
                continue  # This module uses only explicit named-company queries below.
            if not capital_enabled and row.get("module") == "投融资与资本市场":
                continue
            for key, value in classify(str(row.get("module") or ""), str(row.get("query") or "")).items():
                row.setdefault(key, value)
            for route in self.authority_queries:
                if row.get("search_tier") == "authority_first" and row.get("module") == route["module"]:
                    for key in ("evidence_scope", "company_role"):
                        if key in route:
                            row[key] = route[key]
            row["industry_name"] = industry or target
            if row.get("search_tier") == "authority_first":
                geography = str(scope.get("geography") or "")
                if any(word in geography.lower() for word in ("欧洲", "欧盟", "europe")):
                    row["include_domains"] = ["europa.eu", "ec.europa.eu"]
                elif any(word in geography.lower() for word in ("美国", "united states", "usa")):
                    row["include_domains"] = ["census.gov", "commerce.gov", "sec.gov"]
                elif any(word in target for word in ("医药", "生物", "医疗")) and row.get("module") == "政策与监管":
                    row["include_domains"] = ["nmpa.gov.cn", "nhc.gov.cn", "gov.cn"]
            enriched.append(row)

        for segment in segments:
            if segment in {target, industry}:
                continue
            for suffix, module in [
                ("市场规模 用户规模 增速 口径", "市场规模与增长"),
                ("竞争格局 代表企业 市场份额", "竞争格局与代表企业"),
                ("政策 监管 合规", "政策与监管"),
            ]:
                if selected and module not in selected:
                    continue
                enriched.append(
                    {
                        "module": module,
                        "query": re.sub(r"\s+", " ", f"{target} {segment} {suffix}").strip(),
                        "search_tier": "open_web",
                        "evidence_scope": "segment_level",
                        "industry_name": industry or target,
                        "segment_name": segment,
                    }
                )

        for company in scope.get("named_companies") or []:
            for suffix in ("注册信息 股权结构 历史沿革 官网", "业务 产品 技术路线 研发 产能 年报", "客户 供应商 收入 毛利率 风险 公告"):
                enriched.append({"module": "核心企业尽调", "query": f'"{company}" {suffix}',
                                 "search_tier": "open_web", "evidence_scope": "representative_company",
                                 "company_role": "requested_due_diligence", "company_name": company,
                                 "industry_name": industry or target})
        if not selected or selected & {"技术路线对比", "技术演进与平台生态"}:
            for words, terms in INDUSTRY_PROFILES:
                if any(word in target for word in words):
                    enriched.append({"module": "技术路线对比", "query": f"{target} {terms}",
                                     "search_tier": "open_web", "evidence_scope": "industry_level",
                                     "industry_name": industry or target})
                    break
        for row in enriched:
            row["geography"] = scope.get("geography", "")
            row["as_of_date"] = scope.get("as_of_date", "")
            if row["geography"] and row.get("evidence_scope") in {"industry_level", "segment_level"}:
                row["query"] = f'{row["query"]} {row["geography"]}'

        seen: set[tuple[str, tuple[str, ...]]] = set()
        deduped: list[dict[str, Any]] = []
        for item in enriched:
            key = (re.sub(r"\s+", "", str(item.get("query") or "").lower()), tuple(item.get("include_domains") or []))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        deduped.sort(key=lambda item: 0 if item.get("search_tier") == "authority_first" else 1)
        return deduped

    def module_questions(self, module: str, target: str, industry: str) -> list[str]:
        return [
            f"{target} 在「{module}」中有哪些可被公开来源验证的行业事实？",
            "这些事实属于行业层、细分赛道层，还是代表企业样本？",
            "是否存在口径、地域、时间截点不一致导致不能合并判断的材料？",
        ]

    def required_source_types(self, module: str) -> list[str]:
        if module in {"政策与监管", "市场规模与增长"}:
            return ["government", "regulatory", "official", "industry_report"]
        if module in {"竞争格局与代表企业", "商业模式与盈利逻辑", "投融资与资本市场"}:
            return ["filing", "official", "industry_report", "news"]
        return ["official", "industry_report", "news"]
