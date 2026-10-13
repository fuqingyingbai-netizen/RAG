from .base import BaseResearchStrategy


class CompanyResearchStrategy(BaseResearchStrategy):
    target_type = "company"
    default_modules = [
        "公司背景",
        "诉讼/制裁",
        "负面新闻",
        "股东高管",
        "融资情报",
        "管理团队",
        "行业市场",
        "风险核查",
        "技术实力",
    ]
    query_templates = [
        ("主体工商基本信息核查股东关系与治理底盘", "{target} 工商 股东 实控人 董监高"),
        ("主体工商基本信息核查股东关系与治理底盘", "{target} 统一社会信用代码 注册资本 法定代表人"),
        ("历史沿革与融资", "{target} 融资 投资方 估值 IPO 招股书 年报"),
        ("主营业务真实经营情况核验", "{target} 商业化 收入 客户 订单 产品线"),
        ("核心管理团队（深度/基础）风险研判", "{target} 创始人 管理团队 履历 高管 离职"),
        ("企业司法负面核查", "{target} 诉讼 裁判文书 行政处罚"),
        ("诉讼/制裁", "{target} 被执行人 失信 限制高消费 制裁 黑名单"),
        ("技术实力", "{target} 专利 知识产权 商标 软著"),
        ("行业口碑、产品认可度与同业竞争地位研判", "{target} 员工评价 竞品 市场份额 客户 合作伙伴"),
    ]
    authority_queries = [
        {"module": "企业司法负面核查", "query": '"{target}" 诉讼 裁判', "domains": ["wenshu.court.gov.cn", "court.gov.cn"], "min_sources": 2},
        {"module": "风险核查", "query": '"{target}" 被执行 失信 行政处罚', "domains": ["zxgk.court.gov.cn", "creditchina.gov.cn", "samr.gov.cn"], "min_sources": 2},
        {"module": "上市披露", "query": '"{target}" 年报 招股书 公告 股东', "domains": ["cninfo.com.cn", "sse.com.cn", "szse.cn", "hkexnews.hk", "sec.gov"], "exa_category": "financial report", "min_sources": 2},
        {"module": "金融监管", "query": '"{target}" 监管 处罚', "domains": ["csrc.gov.cn", "pbc.gov.cn", "nfra.gov.cn"], "min_sources": 2},
        {"module": "技术实力", "query": '"{target}" 专利 商标', "domains": ["cnipa.gov.cn"], "min_sources": 1},
    ]

    def required_source_types(self, module: str) -> list[str]:
        if module in {"主体工商基本信息核查股东关系与治理底盘", "历史沿革与融资"}:
            return ["filing", "official", "business_database", "news"]
        if module in {"企业司法负面核查", "诉讼/制裁", "风险核查"}:
            return ["court", "government", "regulatory", "news"]
        return super().required_source_types(module)
