import re
from typing import Any

from .base import BaseResearchStrategy


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
        "投融资与资本市场",
        "行业风险与不确定性",
    ]

    query_templates = [
        ("行业定义与边界", "{target} {industry} 定义 边界 子赛道 产业链"),
        ("细分赛道与产业链", "{target} {industry} 细分赛道 产业链 上下游 代表企业"),
        ("政策与监管", "{target} {industry} 政策 监管 合规 算法 数据 反垄断"),
        ("市场规模与增长", "{target} {industry} 市场规模 用户规模 渗透率 增速 CAGR"),
        ("竞争格局与代表企业", "{target} {industry} 市场份额 竞争格局 龙头企业 CR3 CR5"),
        ("商业模式与盈利逻辑", "{target} {industry} 商业模式 变现 收入结构 利润率"),
        ("技术演进与平台生态", "{target} {industry} 技术趋势 AI 云计算 平台生态"),
        ("投融资与资本市场", "{target} {industry} 投融资 IPO 并购 年报 招股书"),
        ("行业风险与不确定性", "{target} {industry} 行业风险 监管风险 商业化风险 技术替代"),
    ]

    authority_queries = [
        {
            "module": "政策与监管",
            "query": '"{target}" 政策 规划 监管 反垄断 数据合规 算法',
            "domains": ["gov.cn", "ndrc.gov.cn", "miit.gov.cn", "samr.gov.cn", "cac.gov.cn"],
            "min_sources": 3,
            "evidence_scope": "industry_level",
        },
        {
            "module": "市场规模与增长",
            "query": '"{target}" 统计 数据 用户规模 渗透率',
            "domains": ["stats.gov.cn", "gov.cn", "cnnic.net.cn", "miit.gov.cn"],
            "min_sources": 2,
            "evidence_scope": "industry_level",
        },
        {
            "module": "竞争格局与代表企业",
            "query": '"{target}" 市场份额 竞争格局 龙头企业',
            "domains": ["samr.gov.cn", "gov.cn", "cninfo.com.cn", "sse.com.cn", "szse.cn", "hkexnews.hk", "sec.gov"],
            "exa_category": "financial report",
            "min_sources": 2,
            "evidence_scope": "representative_company",
            "company_role": "benchmark",
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
            "{target} 平台经济 本地生活 云服务 AI应用 细分",
        ],
        "政策与监管": [
            "{target} 政策 监管 数据合规 算法备案",
            "{target} 反垄断 平台经济 监管",
            "{target} 网络安全 个人信息保护 合规",
        ],
        "市场规模与增长": [
            "{target} 市场规模 用户规模 渗透率 增速",
            "{target} CNNIC 用户规模 网民 互联网发展统计",
            "{target} 市场规模 统计 口径 地域",
        ],
        "竞争格局与代表企业": [
            "{target} 市场份额 竞争格局 龙头企业",
            "{target} 代表企业 美团 阿里 京东 腾讯 字节 年报",
            "{target} CR3 CR5 集中度 市场份额",
        ],
        "商业模式与盈利逻辑": [
            "{target} 商业模式 收入结构 变现 佣金 广告 会员",
            "{target} 平台经济 收入结构 利润率",
            "{target} 代表企业 年报 收入结构 业务分部",
        ],
        "技术演进与平台生态": [
            "{target} 技术趋势 AI 云计算 大模型 平台生态",
            "{target} 数字化 智能化 技术演进",
            "{target} 技术基础设施 云服务 算法",
        ],
        "投融资与资本市场": [
            "{target} 投融资 IPO 并购 融资事件",
            "{target} 上市公司 年报 招股书 互联网业务",
            "{target} 一级市场 融资 估值 资本热度",
        ],
        "行业风险与不确定性": [
            "{target} 行业风险 监管风险 商业化风险",
            "{target} 平台经济 反垄断 数据合规 风险",
            "{target} 技术替代 流量成本 用户增长 风险",
        ],
    }

    def expand_search_queries(self, plan: dict[str, Any], intake: dict[str, Any]) -> list[dict[str, Any]]:
        rows = super().expand_search_queries(plan, intake)
        scope = intake.get("industry_scope") if isinstance(intake.get("industry_scope"), dict) else {}
        segments = [str(item).strip() for item in scope.get("segments", []) if str(item).strip()]
        target = str(intake.get("target_name") or intake.get("industry") or "").strip()
        industry = str(intake.get("industry") or target).strip()

        def classify(module: str, query: str) -> dict[str, Any]:
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
            for key, value in classify(str(row.get("module") or ""), str(row.get("query") or "")).items():
                row.setdefault(key, value)
            row["industry_name"] = industry or target
            enriched.append(row)

        for segment in segments:
            if segment in {target, industry}:
                continue
            for suffix, module in [
                ("市场规模 用户规模 增速 口径", "市场规模与增长"),
                ("竞争格局 代表企业 市场份额", "竞争格局与代表企业"),
                ("政策 监管 合规", "政策与监管"),
            ]:
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
