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
        ("主体工商基本信息核查股东关系与治理底盘", '"{target}" 工商变更 股东变更 注册资本 变更日期'),
        ("主体工商基本信息核查股东关系与治理底盘", '"{target}" 减资公告 债权人 公告'),
        ("主体工商基本信息核查股东关系与治理底盘", '"{target}" 股东名册 实际控制人 一致行动 表决权'),
        ("历史沿革与成长质量", '"{target}" 历史沿革 发展历程 工商变更'),
        ("历史沿革与成长质量", '"{target}" 并购 收购 签约 交割 投产 量产'),
        ("历史沿革与成长质量", '"{target}" 年报 半年度报告 营业收入 净利润 经营现金流'),
        ("历史沿革与成长质量", '"{target}" 融资 发行 配售 上市 募集资金 到账'),
        ("组织治理与运营管理评估", '"{target}" 公司章程 董事会 专门委员会 总经理 授权'),
        ("组织治理与运营管理评估", '"{target}" 年报 内部控制 评价 审计 整改 员工持股计划'),
        ("组织治理与运营管理评估", '"{target}" 组织架构 汇报关系 研发组织 应急预案'),
        ("主营业务真实经营情况核验", "{target} 商业化 收入 客户 订单 产品线"),
        ("主营业务真实经营情况核验", '"{target}" 年报 半年度报告 营业收入构成 分产品 毛利率'),
        ("主营业务真实经营情况核验", '"{target}" 研发项目 项目进展 拟达到的目标 预计上市'),
        ("主营业务真实经营情况核验", '"{target}" 生产量 销售量 产销快报 本年累计 产能利用率'),
        ("主营业务真实经营情况核验", '"{target}" 客户订单 交付 验收 回款 实际投产 规划产能'),
        ("核心管理团队（深度/基础）风险研判", "{target} 创始人 管理团队 履历 高管 离职"),
        ("企业司法负面核查", "{target} 诉讼 裁判文书 行政处罚"),
        ("诉讼/制裁", "{target} 被执行人 失信 限制高消费 制裁 黑名单"),
        ("技术实力", "{target} 专利 知识产权 商标 软著"),
        ("行业口碑、产品认可度与同业竞争地位研判", '"{target}" 可持续发展报告 员工满意度 客户满意度 投诉 指标'),
        ("行业口碑、产品认可度与同业竞争地位研判", '"{target}" 竞品 同行 市场份额 原发布机构 统计口径'),
        ("行业口碑、产品认可度与同业竞争地位研判", '"{target}" 合作伙伴 共同开发 对方 官方公告'),
        ("行业口碑、产品认可度与同业竞争地位研判", '"{target}" 员工评价 客户评价 测评 样本 调查方法'),
    ]
    authority_queries = [
        {"module": "主体工商基本信息核查股东关系与治理底盘", "query": '"{target}" 注册资本 股东 变更', "domains": ["gsxt.gov.cn", "samr.gov.cn", "cninfo.com.cn", "szse.cn", "sse.com.cn", "hkexnews.hk"], "min_sources": 2},
        {"module": "企业司法负面核查", "query": '"{target}" 诉讼 裁判', "domains": ["wenshu.court.gov.cn", "court.gov.cn"], "min_sources": 2},
        {"module": "风险核查", "query": '"{target}" 被执行 失信 行政处罚', "domains": ["zxgk.court.gov.cn", "creditchina.gov.cn", "samr.gov.cn"], "min_sources": 2},
        {"module": "上市披露", "query": '"{target}" 年报 招股书 公告 股东', "domains": ["cninfo.com.cn", "sse.com.cn", "szse.cn", "hkexnews.hk", "sec.gov"], "exa_category": "financial report", "min_sources": 2},
        {"module": "主营业务真实经营情况核验", "query": '"{target}" 年度报告 半年度报告 分产品收入 产销 研发进展', "domains": ["cninfo.com.cn", "sse.com.cn", "szse.cn", "hkexnews.hk"], "min_sources": 2},
        {"module": "金融监管", "query": '"{target}" 监管 处罚', "domains": ["csrc.gov.cn", "pbc.gov.cn", "nfra.gov.cn"], "min_sources": 2},
        {"module": "技术实力", "query": '"{target}" 专利 商标', "domains": ["cnipa.gov.cn"], "min_sources": 1},
    ]

    def required_source_types(self, module: str) -> list[str]:
        if module in {"主体工商基本信息核查股东关系与治理底盘", "历史沿革与融资", "历史沿革与成长质量"}:
            return ["filing", "official", "business_database", "news"]
        if module in {"企业司法负面核查", "诉讼/制裁", "风险核查"}:
            return ["court", "government", "regulatory", "news"]
        return super().required_source_types(module)
