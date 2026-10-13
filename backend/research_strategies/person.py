import re

from .base import BaseResearchStrategy


class PersonResearchStrategy(BaseResearchStrategy):
    target_type = "person"
    default_modules = [
        "身份核验",
        "基础履历",
        "教育与履历",
        "公开表达与采访",
        "经营业绩",
        "企业经营与战略事件",
        "关联利益",
        "司法信用",
        "口碑与操守",
        "团队与治理",
        "同业对标",
        "专项风险",
        "个人背景",
    ]
    query_templates = [
        ("身份核验", '"{target}" "{affiliation}"'),
        ("身份核验", "{target} 中文名 英文名 别名 官方简介"),
        ("基础履历", "{target} 出生 籍贯 教育 毕业 任教 早年经历"),
        ("基础履历", "{target} biography profile education career"),
        ("教育与履历", "{target} 教育背景 工作经历 任职 时间线"),
        ("教育与履历", "{target} 访谈 履历 早年 任教 创业经历"),
        ("公开表达与采访", "{target} 采访 演讲 公开信 价值观 管理理念"),
        ("公开表达与采访", "{target} interview speech leadership philosophy"),
        ("经营业绩", "{target} 创办 公司 项目 经营业绩"),
        ("经营业绩", "{target} {affiliation} 年报 招股书 公告"),
        ("经营业绩", "{affiliation} annual report"),
        ("经营业绩", "{affiliation} annual report Form 20-F {target}"),
        ("经营业绩", "{affiliation} Form 20-F SEC filing"),
        ("经营业绩", "{affiliation} SEC filing HKEX announcement {target}"),
        ("经营业绩", "{affiliation} HKEX announcement governance board shareholders"),
        ("经营业绩", "{affiliation} 年报 港交所 公告 {target}"),
        ("经营业绩", "{affiliation} 年报 港交所 公告 董事会 股东"),
        ("企业经营与战略事件", "{target} {affiliation} 战略 转型 并购 上市 融资"),
        ("企业经营与战略事件", "{target} {affiliation} 重大事件 组织调整 业务调整"),
        ("企业经营与战略事件", "{affiliation} 官网 公告 治理 股权 表决权 {target}"),
        ("关联利益", "{target} 对外投资 关联公司 股东"),
        ("关联利益", "{target} 代持 关联交易 利益冲突"),
        ("关联机构", "{target} {affiliation} 任职 关系"),
        ("司法信用", "{target} 裁判文书 诉讼 被执行人"),
        ("司法信用", "{target} 失信 限制高消费 行政处罚"),
        ("口碑与操守", "{target} 行业口碑 商业操守 诚信 争议"),
        ("口碑与操守", "{target} 员工评价 合作伙伴评价 同行评价 客户评价"),
        ("团队与治理", "{target} 核心团队 高管 离职 董事会 控制权"),
        ("团队与治理", "{target} {affiliation} 合伙人 管理团队 组织文化 接班"),
        ("团队与治理", "{affiliation} 董事会 合伙人制度 高管 治理结构 {target}"),
        ("同业对标", "{target} 同业 对标 创始人 比较 能力"),
        ("同业对标", "{affiliation} 竞争对手 创始人 管理风格 对比"),
        ("专项风险", "{target} 债务 资产转移 股权冻结 质押 知识产权"),
        ("专项风险", "{target} 负面 舆情 监管 调查 争议 风险"),
        ("个人背景", "{target} 采访 家庭 成长经历 婚姻"),
    ]
    authority_queries = [
        {"module": "司法信用", "query": '"{target}" 诉讼 裁判', "domains": ["wenshu.court.gov.cn", "court.gov.cn"], "min_sources": 2},
        {"module": "司法信用", "query": '"{target}" 被执行 失信', "domains": ["zxgk.court.gov.cn", "creditchina.gov.cn"], "min_sources": 2},
        {"module": "信用与处罚", "query": '"{target}" 行政处罚 监管', "domains": ["creditchina.gov.cn", "samr.gov.cn", "csrc.gov.cn", "pbc.gov.cn", "nfra.gov.cn"], "min_sources": 2},
        {"module": "上市披露", "query": '"{target}" 股东 董事 控制权', "domains": ["cninfo.com.cn", "sse.com.cn", "szse.cn", "hkexnews.hk", "sec.gov"], "exa_category": "financial report", "min_sources": 2},
        {"module": "上市披露", "query": '"{affiliation}" "{target}" annual report Form 20-F', "domains": ["sec.gov", "hkexnews.hk"], "exa_category": "financial report", "min_sources": 2},
        {"module": "上市披露", "query": '"{affiliation}" annual report Form 20-F', "domains": ["sec.gov"], "exa_category": "financial report", "min_sources": 2},
        {"module": "上市披露", "query": '"{affiliation}" annual report shareholders directors governance', "domains": ["sec.gov", "hkexnews.hk"], "exa_category": "financial report", "min_sources": 2},
        {"module": "上市披露", "query": '"{affiliation}" "{target}" HKEX announcement annual report', "domains": ["hkexnews.hk"], "exa_category": "financial report", "min_sources": 2},
        {"module": "上市披露", "query": '"{affiliation}" "{target}" 年报 公告 董事会 控制权', "domains": ["hkexnews.hk", "cninfo.com.cn", "sse.com.cn", "szse.cn"], "exa_category": "financial report", "min_sources": 2},
        {"module": "上市披露", "query": '"{affiliation}" 年报 港交所 公告 董事会 股东 治理', "domains": ["hkexnews.hk", "cninfo.com.cn", "sse.com.cn", "szse.cn"], "exa_category": "financial report", "min_sources": 2},
        {"module": "企业经营与战略事件", "query": '"{affiliation}" "{target}" 官网 公告 治理 股权 表决权', "domains": ["alibabagroup.com", "antgroup.com", "hkexnews.hk", "sec.gov"], "exa_category": "financial report", "min_sources": 2},
        {"module": "知识产权", "query": '"{target}" 申请人 发明人', "domains": ["cnipa.gov.cn"], "min_sources": 1},
    ]
    module_templates = {
        "创始人底色画像（家庭/教育/履历）": ["{target} 教育 经历 学校", "{target} 履历 biography", "{target} 采访 家庭 成长经历", "{target} {affiliation} 任职 经历"],
        "人格特质与诚信评估": ["{target} 采访 演讲 价值观", "{target} 管理风格 公开评价", "{target} 争议 诚信 口碑"],
        "经营胜任力（战略/执行/创新）": ["{target} {affiliation} 战略 执行 创新", "{target} {affiliation} 融资 上市 并购", "{target} 创业 经营 业绩"],
        "识人用人与团队管控": ["{target} 团队 管理 高管 合伙人", "{target} {affiliation} 组织 文化 用人 接班", "{target} 高管 离职 管理争议"],
        "核心管理团队背景": ["{target} {affiliation} 管理团队 高管 董事", "{target} 合伙人 蔡崇信 组织治理", "{target} 核心团队 背景"],
        "商业操守与行业口碑": ["{target} 商业操守 诚信 口碑", "{target} 员工 合作伙伴 同行 客户 评价", "{target} 公开争议 声誉"],
        "同业对标下综合能力与品行隐患": ["{target} 同业 对标 创始人 能力", "{affiliation} 竞争对手 创始人 比较", "{target} 管理风格 对比"],
        "关联利益冲突（体外公司/代持/关联交易）": ["{target} 关联公司 股东 投资", "{target} 代持 关联交易 利益冲突", "{target} 配偶 亲属 关联企业"],
        "司法负面与诉讼核查": ["{target} 诉讼 裁判文书", "{target} 被执行人 失信 限制高消费", "{target} 行政处罚 监管"],
        "个人信用与财务风险": ["{target} 个人信用 债务 质押", "{target} 股权冻结 破产 执行", "{target} 税务 处罚"],
        "投后治理及退出风险": ["{target} {affiliation} 上市 治理 股东 董事会", "{target} 控制权 合伙人制度 投资人 沟通", "{affiliation} IPO 退出 治理结构"],
        "风险核查": ["{target} 风险 诉讼 监管 处罚 舆情", "{target} 诚信 道德 商业信用", "{target} 关联企业 风险"],
    }

    def normalize_affiliations(self, value: str) -> list[str]:
        role_terms = {"创始人", "联合创始人", "董事长", "董事", "总经理", "高管", "员工", "合伙人", "ceo", "coo", "cto", "cfo", "founder", "chairman", "partner"}
        rows: list[str] = []
        for item in re.split(r"\s*[/／|｜,，;；、\n]\s*", str(value or "")):
            text = re.sub(r"(?:等|旗下|相关公司)$", "", item.strip()).strip()
            if len(text) >= 2 and text.lower() not in role_terms and text not in rows:
                rows.append(text)
        return rows[:12]

    def required_source_types(self, module: str) -> list[str]:
        if module in {"司法信用", "司法负面与诉讼核查", "个人信用与财务风险", "专项风险"}:
            return ["court", "government", "regulatory", "filing", "news"]
        if module in {"关联利益", "关联利益冲突（体外公司/代持/关联交易）", "团队与治理", "企业经营与战略事件"}:
            return ["filing", "official", "business_database", "news"]
        if module in {"公开表达与采访", "口碑与操守", "同业对标"}:
            return ["official", "interview", "news", "business_database"]
        return super().required_source_types(module)

    def affiliation_discovery_queries(self, target: str, affiliations: list[str]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for affiliation in affiliations:
            rows.extend([
                {"module": "关联机构发现", "query": f'"{target}" "{affiliation}"', "search_tier": "open_web", "preferred_providers": ["exa", "tavily", "serpapi", "brave"], "exa_category": "company"},
                {"module": "关联利益", "query": f"{target} {affiliation} 股东 投资 任职", "search_tier": "open_web", "preferred_providers": ["exa", "tavily", "serpapi", "brave"], "exa_category": "company"},
                {"module": "经营业绩", "query": f"{target} {affiliation} 公告 年报 公开资料", "search_tier": "open_web", "preferred_providers": ["tavily", "exa", "serpapi", "brave"], "exa_category": "financial report"},
                {"module": "上市披露", "query": f"{affiliation} annual report Form 20-F SEC filing", "search_tier": "authoritative", "preferred_providers": ["exa", "serpapi", "brave"], "domains": ["sec.gov"], "exa_category": "financial report"},
                {"module": "上市披露", "query": f"{affiliation} HKEX announcement annual report 董事会 股东 治理", "search_tier": "authoritative", "preferred_providers": ["exa", "serpapi", "brave"], "domains": ["hkexnews.hk"], "exa_category": "financial report"},
                {"module": "企业经营与战略事件", "query": f"{affiliation} 官网 公告 治理 股权 表决权 {target}", "search_tier": "authoritative", "preferred_providers": ["exa", "serpapi", "brave"], "domains": ["alibabagroup.com", "antgroup.com", "cainiao.com", "sec.gov", "hkexnews.hk"], "exa_category": "financial report"},
            ])
        return rows
