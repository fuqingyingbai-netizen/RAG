import json
import re
from typing import Any

from .report_style import REFERENCE_REPORT_STYLE
from .company_text import match_text


GLOBAL_REPORT_RULES = """
总原则：
1. 这是一份投前/项目启动前桌面研究交付物，不是泛泛百科介绍；所有内容都要服务于“判断能否继续推进、哪些风险必须核验、下一步怎么查”。
2. 只使用清洗事实、风险研判和项目背景中已经出现的材料；不得凭行业常识补数据、补融资额、补人物关系或补结论。
3. 每个关键判断后尽量标注来源标题、URL 或 evidence_quote；无法标注来源时只写“待核验”，不要在正文反复写“暂无充分公开证据”。
4. 明确区分三类内容：事实、分析判断、风险/待核验事项。
5. 优先使用表格承载履历、工商、股权、产品、融资、竞品、政策、风险矩阵、时间线、交付物和资料清单。
6. 有数字就写口径、年份、地区、来源；没有数字不得编估算。
7. 证据不足的章节不得空泛补写；正文只保留少量关键“待核验”提示，所有缺口必须汇总到集中式待核验清单。
8. 禁止写“本章严格依据清洗事实”“以下内容基于已提供材料”“作为桌面研究”等元语言，直接写业务内容。
"""


SECTION_OUTPUT_FRAME = """
章节输出骨架：
## {index}. {section_title}

### 本章结论
- 用 2-4 条写本章最重要的事实判断；没有证据时写“待核验”，不要重复“暂无充分公开证据”。

### 事实梳理
- 使用表格或要点列出可被来源支持的信息。
- 对时间、金额、任职、股权、产品阶段、诉讼处罚等硬信息必须标注来源。

### 分析判断
- 解释这些事实对投资、尽调或项目推进的含义。
- 明确哪些是高置信、哪些只是弱信号。

### 风险与待核验
- 列出本章识别的风险点、触发原因、证据来源、建议核验动作。
"""


EDITOR_RULES = """
总编合并要求：
1. 严格保留标准章节顺序和章节标题，不要新增无关章节，不要删除证据不足的章节。
2. 合并重复事实，统一称谓、日期、公司名、人名、币种和口径。
3. 摘要必须像投资人 briefing：报告概述、核心发现、需关注信号、竞争/行业格局速览、总体评估。
4. 综合评估必须给出分项评分或等级，并说明评分依据、证据强弱和主要扣分项。
5. 信息来源必须汇总核心来源，至少包含“信息点/来源标题/URL或来源说明/可信度/用于支持的章节”。
6. 后续研究点必须按高/中/低优先级排序，给出核验问题、建议数据源/访谈对象、预期判断价值。
7. 必须新增或保留“集中式待核验清单”，用表格列出：待核验事项｜为什么公开检索无法确认｜建议核验方式｜优先级｜需客户/公司/访谈/走访提供材料。
8. 正文中“暂无充分公开证据”“证据不足”等重复表达合并到集中式清单；章节正文只保留最关键的少量“待核验”。
9. 输出中文 Markdown，可直接转换为 Word；不要输出 JSON，不要输出过程说明。
"""

# Delivery should read like an investment briefing, not a template-completion exercise.
EDITOR_RULES += """

精简规则：只保留影响判断的事实、风险和结论，合并重复表述。没有可靠事实或有效来源支撑的三级小节和普通章节必须整体省略，不得输出”暂无信息、无公开证据、待核验”占位章节，更不得用模板话术凑篇幅。身份核验、重大风险、信息来源和后续核验清单属于必要质量说明，可简短保留。目录只列最终实际存在的标题，正文证据标签不要进入目录。

章节保护规则（最高优先级，覆盖精简规则）：报告的标准顶级章节（## N. 标题）一个都不能少。即使某章没有任何可靠事实、只有一个”待核验”句子，也必须保留该顶级标题。精简规则仅对章节内部的 ### 子标题和正文段落生效，绝对不能用于删除整个 ## 顶级章节。final output 的顶级章节数量必须与标准目录完全一致。

人物身份隔离规则：人物姓名、同名自然人、同名公司法定代表人和关联企业必须分别建档。除非姓名之外还有所属公司/职位、时间线、教育经历、公开账号或其他至少两项独立锚点一致，不得认定为同一人；不得把同名公司的工商、司法或信用数据写成目标人物事实。身份未确认时，结论必须是“身份待核验/暂停判断”，不得输出低风险、高分或建议推进。

风险评分口径：risk_assessment 中的 overall_score 是风险分，0 为最低风险、100 为最高风险，严禁将其描述为企业质量分、信用分或推荐分。
"""


VISUAL_EVIDENCE_RULES = """
视觉/图谱证据要求：
1. 如果清洗事实中出现 image_urls、vision_text、OCR 文本、天眼图谱/股权结构图/关系图等证据，必须在相关章节中单列“视觉证据/图谱证据”或并入证据表。
2. image_urls 应以 Markdown 链接或图片语法保留，不能丢弃；无法嵌入图片时至少保留可追溯链接。
3. vision_text 只能作为对图片内容的辅助解读，结论仍需绑定来源标题、URL 或证据摘录。
"""


PROPOSAL_PROMPT = """
请扮演咨询项目建议书总监，基于桌面研究报告和风险研判，生成可直接给客户沟通的项目建议书。

建议书不是报告复述，必须转化为项目方案。三种类型（目标公司、目标个人/创始人、目标行业）统一使用以下 7 节结构，标题和顺序不得改变：

1. 项目基本情况
- 简要说明委托方调研目的、标的对象（公司/个人）或目标行业，以及本次调研的核心动因。
- 标的对象基本信息：
  - 若为目标公司：注册信息、成立时间、注册资本、主营业务、发展历程、股权结构。
  - 若为目标个人：姓名、年龄、教育背景、任职经历、目前职位及职责。
  - 若为目标行业：行业定义、核心赛道、代表产品/应用、标的所处位置。
- 重点关注方向：如管理层关系、技术壁垒、商业化进度、合规风险、客户供应商、政策监管、投融资与退出路径等。
- 重点研究内容/重点关注公司/重点关注产品信息等。

2. 项目调研分析
- 列举分析方法，包括一般性分析和特殊性分析。
- 一般性分析：明确研究目标，说明本次调研将采用的通用方法论，例如公开信息检索、数据库核验、访谈交叉验证、竞品对标、风险矩阵。
- 特殊性分析：针对标的特有的行业属性、发展阶段或敏感问题，强调调研重点。

3. 项目调研框架与主要研究范围
- 总体框架：市场格局（行业规模、竞争态势）、产品/业务竞争力（技术对比、商业化指标）、管理层与组织（核心人员背景、关系、能力）、风险核查（法律、财务、业务可持续性）。
- 行业与市场研究（针对行业尽调）：全球及国内市场规模、增速、渗透率（ToB/ToC拆分）、主要玩家商业模式、收入结构、用户粘性、政策环境影响。
- 产品与技术对比：对标产品功能、模型策略、部署形态、质量评测、商业化维度（定价、付费率、ARPU、留存率等）、创业公司与大厂优劣势对比。
- 核心管理层调研（针对创始人背调）：职责分工与管理风格、合作基础、内部派系、口碑评价、过往业绩贡献与潜在利益冲突。
- 公司专项调研（针对公司背调）：经营状况（收入、客户、供应链）、研发进度与新品规划、融资背景、投资人关系、上市路径、合规与诉讼风险。
- 风险识别与评估：按风险类别（组织、业务、财务、法律、行业）列出潜在风险点，并初步评估影响程度。

4. 项目调研方法与渠道资源
- 调研方法包括公开信息检索（上市公司公告、行业报告、媒体报道、专利数据库）、数据库查询（工商、司法、税务、征信等商业数据库）、深度访谈（标的公司现/离职员工、前同事、行业专家、下游客户与上游供应商、投资人与合作伙伴）、交叉验证（多源数据比对，确保结论客观可靠）。
- 渠道资源包括海外渠道、国内渠道、特定行业专家库等；没有已确认渠道时写“拟使用渠道”，不得声称已完成访谈或已获取付费数据库结果。

5. 项目工作方法与周期安排
- 根据项目复杂度划定整体周期，对主要研究范围中的各部分研究内容设定时间范围。
- 给定交付物为中期简报（可选）与最终调研报告，最终报告应包含详实数据、访谈纪要、风险矩阵、综合评分等。

6. 项目团队安排
- 列出参与项目的核心人员，包括姓名、职位、从业经验、擅长领域及在本项目中的角色。
- 如果没有真实团队名单，不得编造姓名；可用“项目负责人/研究经理/行业专家/访谈顾问/质量复核”作为角色占位。

7. 项目报价
- 确定咨询费用：总金额（人民币/美元，含税与否需注明）；费用包含人员薪酬、差旅、渠道访谈、数据采购等。
- 支付条款：如分阶段付款、预付比例等。
- 保密条款必须包含：无论贵公司与我公司是否就本案达成委托，未经贵公司书面许可，我公司不会将贵公司情况及贵公司咨询业务所涉事项（包括文字、声像、图片及其它载体资料）向第三方披露。望贵公司对本案做同等保密处理。谢谢！

写作要求：
- 使用中文 Markdown，可直接转换为 Word。
- 用表格呈现调研范围、方法渠道、工作计划、团队安排、报价条款和风险优先级。
- 不要堆砌原始事实，只保留能说明项目必要性的核心发现。
- 对缺证据事项写“待客户补充/待访谈/待付费数据库核验”。
- 语气专业、克制、可执行，避免夸张营销话术。
"""


def format_outline(outline: list[tuple[str, list[str]]]) -> str:
    return "\n".join(
        f"{idx}. {title}\n" + "\n".join(f"   - {item}" for item in requirements)
        for idx, (title, requirements) in enumerate(outline, 1)
    )


def _company_fact_has_trusted_target_anchor(fact: dict[str, Any], target_name: str) -> bool:
    """Require the underlying source to name the company, not only an LLM summary."""
    # Local comparison view only. Never overwrite the retained source quote
    # or promote a rejected/related legal entity through script conversion.
    fact = {**fact, **{key: match_text(fact.get(key)) for key in
            ("fact", "source_title", "evidence_quote", "subject", "object", "company_name", "entity_name")}}
    target_name = match_text(target_name)
    target_key = "".join(str(target_name or "").lower().split())
    if not target_key or fact.get("eligible_for_report") is False:
        return False
    entity_match = str(fact.get("entity_match") or "").lower()
    if entity_match in {"ambiguous", "mismatch", "out_of_scope"}:
        return False
    # Explicitly rejected entity validations must never be silently promoted
    # back to a trusted fact.  This closes the gap where a structured source
    # is marked rejected during ingestion but later admitted via the
    # ``verified_entity`` path at the bottom of this function.
    if str(fact.get("source_entity_validation") or "").lower() in {"rejected", "ambiguous", "related", "related_entity_context"}:
        return False

    source_title = str(fact.get("source_title") or "")
    evidence_quote = str(fact.get("evidence_quote") or "")
    trusted_blob = " ".join(
        str(fact.get(key) or "")
        for key in ("subject", "object", "company_name", "entity_name")
    )
    full_blob = " ".join(
        str(fact.get(key) or "")
        for key in ("fact", "source_title", "evidence_quote", "subject", "object", "company_name", "entity_name")
    )
    compact_trusted = "".join(trusted_blob.lower().split())
    compact_full = "".join(full_blob.lower().split())
    target_negative_markers = (
        "not" + target_key,
        "doesnotdirectlyinvolve",
        "notmentioned",
        "\u672a\u627e\u5230" + target_key,
        "\u672a\u76f4\u63a5\u6d89\u53ca",
        "\u672a\u63d0\u53ca",
        "\u4e0d\u6d89\u53ca",
        "\u4e0e\u67e5\u8be2\u5bf9\u8c61\u4e0d\u7b26",
        "\u4fe1\u606f\u5bf9\u4e0d\u4e0a",
    )
    if any(marker in compact_full for marker in target_negative_markers):
        return False
    # A search-result extractor often repeats the user's query in its summary.
    # That echo is not source evidence: it was the root cause of unrelated
    # Anhui companies entering the previous company report.  A title naming
    # the target is reliable enough for a public page; quote-only matching is
    # admitted only for a structured professional record or an explicitly
    # verified source entity.
    title_key = "".join(source_title.lower().split())
    structured = bool(fact.get("is_structured_evidence")) or str(fact.get("source_url") or "").startswith("structured://")
    # Professional platforms have an unambiguous legal-subject contract: a
    # similarly named subsidiary is context, never proof of the target company.
    if structured:
        entity_name = "".join(
            "".join(str(fact.get(key) or "").lower().split())
            for key in ("entity_name", "company_name", "subject")
        )
        if not entity_name:
            entity_blob = " ".join(
                str(fact.get(key) or "")
                for key in ("fact", "evidence_quote", "source_title")
            )
            entity_patterns = (
                r"(?:企业名称|公司名称|主体名称)\s*[|：:]\s*([^|\n\r]{2,80})",
                r"(?:企业名称|公司名称|主体名称)\s*[|：:]\s*`?([^`|\n\r]{2,80})`?",
            )
            for pattern in entity_patterns:
                match = re.search(pattern, entity_blob)
                if match:
                    entity_name = "".join(match.group(1).lower().split())
                    break
        if entity_name and entity_name != target_key:
            return False
        if not entity_name and str(fact.get("source_entity_validation") or "").lower() not in {"verified", "matched_anchor", "enterprise_name_field_match", "credit_code_match"}:
            return False
    if target_key in title_key:
        return True
    if not structured and str(fact.get('source_entity_validation') or '').lower() == 'matched_original_issuer':
        if (''.join(match_text(fact.get('source_issuer_name')).casefold().split()) == target_key
                and target_key in ''.join(match_text(fact.get('source_issuer_quote')).casefold().split())):
            return True
    query_echo_markers = (
        "用户查询", "查询关注", "针对用户", "与查询", "相关性", "检索关键词",
        "userquery", "searchquery", "queryfocus", "doesnotdirectlyinvolve",
    )
    quote_key = "".join(evidence_quote.lower().split())
    if any(marker in evidence_quote.lower() or marker in quote_key for marker in query_echo_markers):
        return target_key in compact_trusted
    verified_entity = str(fact.get("source_entity_validation") or "").lower() in {"verified", "matched_anchor"}
    return target_key in compact_trusted or ((structured or verified_entity) and target_key in quote_key)


def infer_company_fact_tags(fact: dict[str, Any]) -> set[str]:
    """Infer stable report tags; keywords rank evidence but do not gate it."""
    blob = match_text(" ".join(str(fact.get(key) or "") for key in (
        "fact", "category", "module", "claim_type", "fact_type", "source_title",
        "provider", "evidence_quote",
    ))).lower()
    tags = {str(item).strip().lower() for item in (fact.get("fact_tags") or []) if str(item).strip()}
    rules = {
        "business_registration": ("工商", "注册资本", "法定代表人", "统一社会信用", "成立", "经营范围", "登记状态"),
        "shareholder": ("股东", "持股", "实控", "控制人", "出资", "关联方", "股权"),
        "financing": ("融资", "投资轮", "募资", "估值", "上市", "ipo", "并购"),
        "financial_performance": ("营收", "收入", "净利润", "财报", "资产", "负债", "现金流", "gmv", "财务"),
        "management": ("高管", "董事", "监事", "创始人", "管理团队", "ceo", "管理层"),
        "product": ("产品", "服务", "业务", "解决方案", "平台", "技术", "研发", "专利"),
        "customer_supplier": ("客户", "供应商", "采购", "合同", "合作伙伴", "渠道"),
        "workforce": ("员工", "招聘", "人员", "组织文化", "离职", "雇主"),
        "litigation": ("诉讼", "法院", "裁判", "被执行", "失信", "仲裁"),
        "regulatory": ("处罚", "监管", "合规", "行政", "立案", "整改", "制裁"),
        "public_opinion": ("舆情", "负面", "投诉", "口碑", "争议"),
        "industry_competition": ("行业", "市场", "竞品", "竞争", "赛道", "市场份额", "政策"),
        "history": ("沿革", "变更", "曾用名", "历史", "成立以来"),
    }
    for tag, markers in rules.items():
        if any(marker in blob for marker in markers):
            tags.add(tag)
    return tags or {"general"}


def company_section_evidence_budget(section_title: str) -> int:
    """Maximum facts supplied to one chapter; availability, not company size, decides length."""
    budgets = (
        (("摘要",), 12), (("工商", "股东", "治理底盘"), 12), (("沿革", "融资"), 12),
        (("组织", "治理"), 8), (("行业", "竞争", "口碑"), 12), (("经营",), 15),
        (("团队",), 10), (("文化", "人员"), 6), (("司法", "负面"), 12),
        (("专项",), 10), (("风险",), 12), (("综合评价",), 12),
    )
    return next((budget for markers, budget in budgets if any(marker in section_title for marker in markers)), 10)


def company_section_density(facts: list[dict[str, Any]], section_title: str) -> str:
    """Classify one chapter by evidence strength, source diversity and chapter type."""
    if not facts:
        return "empty"
    tags = set().union(*(infer_company_fact_tags(fact) for fact in facts))
    urls = {str(fact.get("source_url") or fact.get("evidence_id") or "") for fact in facts}
    authority = sum(1 for fact in facts if str(fact.get("source_grade") or "").upper().startswith("A") or str(fact.get("provider") or "").lower() in {"qcc", "tyc", "xiniu"})
    strength = len(facts) + min(authority, 3) * 0.75 + min(len(urls), 4) * 0.25
    if tags & {"litigation", "regulatory"} and authority:
        return "rich" if strength >= 2 else "normal"
    if tags & {"business_registration", "shareholder"}:
        return "rich" if strength >= 4 else ("normal" if strength >= 2 else "sparse")
    if "industry_competition" in tags or "financial_performance" in tags:
        return "rich" if strength >= 6 else ("normal" if strength >= 3 else "sparse")
    return "rich" if strength >= 5 else ("normal" if strength >= 2 else "sparse")


def classify_company_fact_scope(fact: dict[str, Any], target_name: str) -> str:
    """Classify a company-search fact without deleting the underlying source.

    ``target_direct`` is admissible for company facts, scoring and the audit
    index.  ``industry_context`` is intentionally retained for the market /
    competition chapter only.  ``noise`` stays in the durable raw ledger but
    can never appear in a delivery report.
    """
    entity_match = str(fact.get("entity_match") or "").lower()
    source_validation = str(fact.get("source_entity_validation") or "").lower()
    if entity_match in {"related", "related_entity_context", "affiliate"} or source_validation in {"related", "related_entity_context"}:
        return "related_entity_context"
    if _company_fact_has_trusted_target_anchor(fact, target_name):
        return "target_direct"
    blob = " ".join(
        str(fact.get(key) or "")
        for key in ("fact", "source_title", "evidence_quote", "category", "module")
    )
    compact = "".join(blob.lower().split())
    negative_markers = (
        "not" + "".join(str(target_name or "").lower().split()),
        "doesnotdirectlyinvolve", "notmentioned", "未直接涉及", "未提及", "不涉及", "404",
    )
    if not compact or any(marker in compact for marker in negative_markers):
        return "noise"
    related_markers = ("集团", "控股", "子公司", "关联方", "旗下", "京东科技", "京东物流", "京东健康")
    if any(marker in blob for marker in related_markers) and target_name:
        return "related_entity_context"
    context_markers = (
        "行业", "市场", "竞品", "竞争", "政策", "赛道", "机器人", "具身智能",
        "industry", "market", "competitor", "competition", "policy", "robot", "embodied ai",
    )
    return "industry_context" if any(marker in blob for marker in context_markers) else "noise"


def classify_person_fact_scope(fact: dict[str, Any], target_name: str) -> str:
    """Classify person-report facts by attribution boundary.

    Person reports are allowed to use weak and indirect evidence, but the
    writer must not promote affiliated-company facts into personal facts.
    """
    if fact.get("eligible_for_report") is False:
        return "noise"
    identity = str(fact.get("identity_match") or "").lower()
    identity_confidence = str(fact.get("identity_confidence") or "").lower()
    usable_as = str(fact.get("usable_as") or "").lower()
    if identity in {"mismatch", "ambiguous"} or identity_confidence in {"low", "rejected"} or usable_as == "identity_quarantine":
        return "noise"
    category = str(fact.get("category") or "").lower()
    source_url = str(fact.get("source_url") or "")
    pa = fact.get("person_affiliation")
    if category == "person_affiliation_structured" or isinstance(pa, dict):
        return "affiliated_company"
    blob = " ".join(
        str(fact.get(key) or "")
        for key in ("fact", "source_title", "evidence_quote", "subject", "object", "entity_name", "company_name")
    )
    target_key = "".join(str(target_name or "").lower().split())
    compact = "".join(blob.lower().split())
    if target_key and target_key in compact:
        if source_url.startswith("structured://"):
            return "person_direct" if identity in {"matched", "verified", "exact"} else "person_direct_weak"
        return "person_direct" if identity in {"matched", "verified", "exact", ""} else "person_direct_weak"
    if any(word in blob for word in ("阿里", "Alibaba", "菜鸟", "蚂蚁", "SoftBank", "软银")):
        return "group_context"
    return "media_or_context"


def person_evidence_level(fact: dict[str, Any], target_name: str) -> str:
    scope = str(fact.get("evidence_scope") or classify_person_fact_scope(fact, target_name))
    url = str(fact.get("source_url") or "").lower()
    grade = str(fact.get("source_grade") or "").upper()
    evidence_type = str(fact.get("evidence_type") or "").lower()
    authority_domains = (
        "gov.cn", "court.gov.cn", "wenshu.court.gov.cn", "zxgk.court.gov.cn",
        "creditchina.gov.cn", "cninfo.com.cn", "sse.com.cn", "szse.cn",
        "hkexnews.hk", "sec.gov", "csrc.gov.cn", "samr.gov.cn", "cnipa.gov.cn",
    )
    if scope == "person_direct" and (evidence_type == "primary_record" or any(domain in url for domain in authority_domains)):
        return "A"
    if scope == "person_direct":
        return "B" if grade.startswith(("A", "B")) else "C"
    if scope == "person_direct_weak" or scope == "media_or_context":
        return "C"
    if scope in {"affiliated_company", "group_context"}:
        return "D"
    return "E"


def person_scope_note(scope: str, level: str) -> str:
    if level == "A":
        return "可支撑强事实判断；仍需保留来源口径。"
    if level == "B":
        return "可支撑基础事实；分析结论需克制。"
    if level == "C":
        return "二手/媒体/弱身份线索；只能写公开线索或待核验。"
    if level == "D":
        if scope == "affiliated_company":
            return "关联企业间接证据；只能写企业层面观察或人物管理边界推断。"
        return "集团/项目背景证据；不能直接证明人物个人事实。"
    return "未形成可用证据；只能列为待核验。"


def _focused_cleaned_json(
    cleaned_json: str,
    section_title: str,
    requirements: list[str],
    target_name: str = "",
    target_type: str = "",
    excluded_urls: set[str] | None = None,
) -> str:
    try:
        parsed = json.loads(cleaned_json)
    except Exception:
        return cleaned_json
    if not isinstance(parsed, dict):
        return cleaned_json
    noise_markers = ["地域限制", "后续调用建议", "error calling tool", "空结果：未发现", "未找到公司"]
    target_type = str(target_type or "").lower()

    def is_in_report_scope(fact: dict[str, Any]) -> bool:
        """Apply the relevance control that belongs to the report type only.

        ``identity_match`` is a person-specific safeguard.  Reusing it for a
        company or an industry silently couples unrelated report pipelines and
        makes their evidence selection hard to reason about.
        """
        if fact.get("eligible_for_report") is False:
            return False
        if target_type == "person":
            identity = str(fact.get("identity_match") or "").lower()
            identity_confidence = str(fact.get("identity_confidence") or "").lower()
            usable_as = str(fact.get("usable_as") or "").lower()
            if identity in {"mismatch", "ambiguous"} or identity_confidence in {"low", "rejected"} or usable_as == "identity_quarantine":
                return False
            scope = str(fact.get("evidence_scope") or classify_person_fact_scope(fact, target_name))
            return scope != "noise"
        if target_type == "company":
            scope = str(fact.get("evidence_scope") or classify_company_fact_scope(fact, target_name))
            if scope == "target_direct":
                return True
            related_chapter = any(word in section_title for word in ("摘要", "工商", "股东", "治理", "沿革", "专项", "风险", "综合评价"))
            if scope == "related_entity_context":
                return related_chapter
            # Context is useful, but never as proof of a company fact.  It is
            # confined to the explicitly market/competition-oriented chapter.
            context_chapter = any(word in section_title for word in ("行业", "口碑", "竞争", "竞品"))
            return scope == "industry_context" and context_chapter
        if target_type == "industry":
            return str(fact.get("scope_match") or "in_scope").lower() not in {"ambiguous", "uncertain", "mismatch", "out_of_scope"}
        return True

    excluded_urls = {str(url or "").rstrip("/") for url in (excluded_urls or set())}
    facts = [
        fact for fact in (parsed.get("facts") or [])
        if (
            isinstance(fact, dict)
            and is_in_report_scope(fact)
            and str(fact.get("source_url") or "").rstrip("/") not in excluded_urls
            and not any(marker in str(fact.get("fact") or "").lower() for marker in noise_markers)
        )
    ]
    if not facts:
        # Returning the unfiltered payload here silently reintroduced every
        # rejected fact into a chapter prompt.  An empty scoped package is the
        # only safe result when no fact passes the report-type boundary.
        return json.dumps(
            {
                "facts": [],
                "coverage_summary": parsed.get("coverage_summary", {}),
                "information_gaps": parsed.get("information_gaps", [])[:20],
                "discarded_patterns": parsed.get("discarded_patterns", [])[:10],
            },
            ensure_ascii=False,
            indent=2,
        )

    title_blob = f"{section_title} {' '.join(requirements)}"
    keyword_groups = [
        ("人物底色", ["家庭", "教育", "学校", "履历", "任职", "创业", "婚姻", "健康", "社会关系"]),
        ("能力治理", ["战略", "执行", "创新", "管理", "团队", "高管", "组织", "经营", "业绩", "资本"]),
        ("关联关系", ["关联公司", "关联机构", "投资", "持股", "股东", "控制", "基金", "任职", "关联交易"]),
        ("司法声誉", ["诉讼", "法院", "处罚", "监管", "失信", "负面", "舆情", "诚信", "承诺"]),
        ("来源后续", ["来源", "网址", "可信度", "待核验", "后续研究", "访谈"]),
        ("工商", ["工商", "注册", "注册资本", "法定代表人", "成立", "经营范围", "股东", "治理", "实控", "关联方"]),
        ("融资", ["融资", "投资", "股权变动", "历史沿革", "上市", "资本", "估值"]),
        ("团队", ["管理", "团队", "高管", "创始人", "履历", "组织", "人员", "文化", "流失"]),
        ("经营", ["主营", "业务", "产品", "客户", "供应商", "招聘", "收入", "研发", "运营", "生产", "产能", "营收", "GMV", "市场份额", "用户", "增长"]),
        ("行业", ["行业", "市场", "竞品", "竞争", "口碑", "产品认可", "同业", "政策"]),
        ("风险", ["风险", "司法", "诉讼", "处罚", "制裁", "负面", "舆情", "合规", "裁判"]),
        ("来源", ["信息来源", "来源", "检索工具", "可信度", "后续", "建议", "核验"]),
    ]
    active_keywords: set[str] = set()
    for _, words in keyword_groups:
        if any(word in title_blob for word in words):
            active_keywords.update(words)
    if not active_keywords:
        active_keywords.update(word for word in re_split_words(title_blob) if len(word) >= 2)

    target_key = "".join(str(target_name or "").lower().split())

    def company_chapter_tags() -> set[str]:
        title = section_title
        if "摘要" in title or "综合评价" in title:
            return {"business_registration", "shareholder", "financing", "financial_performance", "management", "product", "litigation", "regulatory", "industry_competition", "history"}
        if any(word in title for word in ("工商", "股东", "治理底盘")):
            return {"business_registration", "shareholder", "management"}
        if any(word in title for word in ("沿革", "融资")):
            return {"history", "financing", "shareholder", "business_registration"}
        if any(word in title for word in ("组织", "治理")):
            return {"management", "shareholder", "business_registration", "workforce"}
        if any(word in title for word in ("行业", "竞争", "口碑")):
            return {"industry_competition", "product", "public_opinion", "financial_performance"}
        if "经营" in title:
            return {"product", "financial_performance", "customer_supplier", "workforce"}
        if "团队" in title:
            return {"management", "workforce"}
        if any(word in title for word in ("文化", "人员")):
            return {"workforce", "management", "public_opinion"}
        if any(word in title for word in ("司法", "负面")):
            return {"litigation", "regulatory", "public_opinion"}
        if "专项" in title:
            return {"shareholder", "financing", "customer_supplier", "regulatory", "history"}
        if "风险" in title:
            return {"litigation", "regulatory", "public_opinion", "financial_performance", "shareholder"}
        return {"general"}

    required_company_tags = company_chapter_tags() if target_type == "company" else set()

    def industry_chapter_scopes() -> set[str]:
        title = section_title
        if "摘要" in title:
            return {"industry_level", "segment_level", "representative_company", "capital_market"}
        if any(word in title for word in ("定义", "产业链", "政策", "市场规模", "热度", "前景")):
            return {"industry_level", "segment_level"}
        if any(word in title for word in ("竞争", "代表企业", "龙头", "重点企业", "对标", "商业模式", "技术", "投融资")):
            return {"industry_level", "segment_level", "representative_company", "capital_market"}
        if any(word in title for word in ("风险", "综合评估")):
            return {"industry_level", "segment_level", "representative_company", "capital_market"}
        if any(word in title for word in ("信息来源", "后续")):
            return {"industry_level", "segment_level", "representative_company", "capital_market"}
        return {"industry_level", "segment_level"}

    required_industry_scopes = industry_chapter_scopes() if target_type == "industry" else set()

    def score(fact: dict[str, Any]) -> tuple[int, int, int]:
        blob = " ".join(
            str(fact.get(key) or "")
            for key in ["fact", "category", "module", "source_title", "provider", "platform", "evidence_quote", "identity_reason"]
        )
        # person_affiliation_structured facts describe affiliated companies,
        # not the target person by name.  Pull person_name and affiliation_name
        # from the person_affiliation dict so target_bonus and keyword_hits can
        # match against them (e.g. a Qichacha fact about "杭州云铂注册资本1000万"
        # can still link back to "马云").
        pa = fact.get("person_affiliation")
        if isinstance(pa, dict):
            blob += " " + str(pa.get("person_name") or "") + " " + str(pa.get("affiliation_name") or "")
        fact_key = "".join(blob.lower().split())
        target_bonus = 6 if target_key and target_key in fact_key else 0
        provider_bonus = 3 if target_type != "person" and (fact.get("category") == "business_database" or fact.get("provider") in {"qcc", "tyc", "xiniu"}) else 0
        scope = str(fact.get("evidence_scope") or "")
        if target_type == "person":
            scope = classify_person_fact_scope(fact, target_name)
            fact["evidence_scope"] = scope
            level = person_evidence_level(fact, target_name)
            fact["evidence_level"] = level
            fact["evidence_boundary"] = person_scope_note(scope, level)
        affiliation_bonus = 4 if (
            target_type == "person"
            and fact.get("category") == "person_affiliation_structured"
            and any(word in title_blob for word in ("经营", "团队", "治理", "管理", "关联", "专项", "退出", "风险", "对标"))
        ) else 0
        if target_type == "person" and scope in {"affiliated_company", "group_context"} and not affiliation_bonus:
            affiliation_bonus = -3
        keyword_hits = sum(1 for word in active_keywords if word and word in blob)
        fact_tags = infer_company_fact_tags(fact) if target_type == "company" else set()
        if target_type == "company":
            fact["fact_tags"] = sorted(fact_tags)
        chapter_tag_bonus = 5 if fact_tags & required_company_tags else 0
        related_penalty = -2 if target_type == "company" and str(fact.get("evidence_scope") or "") == "related_entity_context" else 0
        source_grade_bonus = 1 if str(fact.get("source_grade") or "").upper().startswith("A") else 0
        return (target_bonus + keyword_hits + provider_bonus + affiliation_bonus + chapter_tag_bonus + related_penalty, source_grade_bonus, int(float(fact.get("quality_score") or 0)))

    ranked = sorted(facts, key=score, reverse=True)
    # A chapter receives a small evidence package, not the complete fact DB.
    # Preserve source diversity first, then fill genuine module gaps.  This is
    # chapter-local packaging and never deletes facts from the durable ledger.
    # Company and industry reports use bounded, chapter-specific evidence
    # packages.  This keeps the delivered source index readable and prevents a
    # broad company search corpus from dominating every chapter.
    package_limit = company_section_evidence_budget(section_title) if target_type == "company" else (8 if target_type == "industry" else 12)
    # An industry report has 13 evidence-bearing chapters (1-13); reserve a
    # broad, non-overlapping package for each before allowing any reuse in
    # summaries and appendices.
    # A company chapter must not be padded with unrelated target-company facts.
    # An industry chapter likewise — zero genuinely relevant facts is a valid
    # input state and is rendered as one concise no-evidence sentence.
    # Zero genuinely relevant facts is a valid input state and is rendered as
    # one concise no-evidence sentence by the company agent.
    minimum_package = 0 if target_type in {"industry", "company", "person"} else 8
    focused: list[dict[str, Any]] = []
    used_urls: set[str] = set()
    for fact in ranked:
        fact_score = score(fact)
        # For industry reports, keyword-group matching is inherently imprecise
        # because the groups were designed for company / person reports.  Two
        # chapters ("前景展望" and "综合评估") trigger zero keyword groups and
        # their fallback labels ("情景路径", "谨慎假设"...) never appear in
        # fact text.  Filtering zero-scoring facts would starve those chapters
        # even when hundreds of industry facts exist in the ledger.
        if fact_score[0] <= 0 and target_type not in {"industry", "company"}:
            continue
        if target_type == "person":
            scope = str(fact.get("evidence_scope") or classify_person_fact_scope(fact, target_name))
            level = person_evidence_level(fact, target_name)
            fact["evidence_scope"] = scope
            fact["evidence_level"] = level
            fact["evidence_boundary"] = person_scope_note(scope, level)
        if target_type == "company":
            summary_chapter = any(word in section_title for word in ("摘要", "综合评价"))
            fact_tags = infer_company_fact_tags(fact)
            scope = str(fact.get("evidence_scope") or classify_company_fact_scope(fact, target_name))
            # Chapter admission is based on fact type/module/source semantics.
            # Keyword matching remains in ``score`` only, where it improves
            # ordering without deleting useful evidence.
            if not summary_chapter and not (fact_tags & required_company_tags):
                if not (scope == "related_entity_context" and any(word in section_title for word in ("股东", "治理", "沿革", "专项", "风险"))):
                    continue
            if scope == "related_entity_context":
                fact["attribution_boundary"] = "关联主体背景材料；不得推导为目标公司的工商、融资、治理、司法或风险事实。"
            elif scope == "industry_context":
                fact["attribution_boundary"] = "行业或竞品背景材料；仅用于市场与竞争语境。"
            else:
                fact["attribution_boundary"] = "目标主体直接证据。"
        if target_type == "industry":
            scope = str(fact.get("evidence_scope") or "").lower()
            if scope and scope not in required_industry_scopes:
                continue
            if scope == "representative_company":
                fact["attribution_boundary"] = "代表企业/龙头公司样本；仅用于行业竞争格局、商业模式和对标分析，不得写成目标公司尽调。"
            elif scope == "segment_level":
                fact["attribution_boundary"] = "细分赛道事实；不得与其他赛道混算市场规模、份额、增速或估值。"
            elif scope == "capital_market":
                fact["attribution_boundary"] = "资本市场/投融资事实；仅用于资本热度、融资和上市披露判断。"
            else:
                fact["attribution_boundary"] = "行业层事实；用于行业定义、政策、规模、趋势和风险判断。"
        url = str(fact.get("source_url") or "").rstrip("/")
        if url and url in used_urls:
            continue
        focused.append(fact)
        if url:
            used_urls.add(url)
        if len(focused) >= package_limit:
            break
    if len(focused) < minimum_package:
        for fact in ranked:
            if fact in focused:
                continue
            url = str(fact.get("source_url") or "").rstrip("/")
            if url and url in used_urls:
                continue
            focused.append(fact)
            if url:
                used_urls.add(url)
            if len(focused) >= minimum_package:
                break
    result = {
        "facts": focused,
        "coverage_summary": parsed.get("coverage_summary", {}),
        "information_gaps": parsed.get("information_gaps", [])[:20],
        "discarded_patterns": parsed.get("discarded_patterns", [])[:10],
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


def re_split_words(text: str) -> list[str]:
    import re

    return [item for item in re.split(r"[\s,，/、；;：:｜|()\[\]（）]+", text or "") if item]


def build_section_prompt(
    *,
    report_kind: str,
    outline: list[tuple[str, list[str]]],
    project: Any,
    cleaned_json: str,
    risk_json: str,
    index: int,
    section_title: str,
    requirements: list[str],
    clip,
    few_shot: str = "",
    section_structure: str = "",
) -> str:
    output_structure = section_structure or SECTION_OUTPUT_FRAME.format(index=index, section_title=section_title)
    project_target_type = str(project.target_type or "").lower()
    focused_cleaned = _focused_cleaned_json(cleaned_json, section_title, requirements, str(project.target_name or ""), project_target_type)
    industry_scope = getattr(project, "industry_scope", {}) if project_target_type == "industry" else {}
    evidence_package_label = (
        "本章证据包（按章节相关性筛选；人物报告允许 0 条、1 条或多条证据，必须按 evidence_level/evidence_boundary 降级表达）："
        if project_target_type == "person"
        else "本章证据包（8-15 条章节相关事实；事实库与全量证据台账未被裁剪）："
    )
    scope_rules = ""
    if isinstance(industry_scope, dict) and industry_scope:
        scope_rules = f"""
行业研究边界（必须遵守，不得自行扩展或混算）：
{json.dumps(industry_scope, ensure_ascii=False, indent=2)}
- 不同子赛道的市场规模、份额、增速和估值口径不得相加；无法比较时必须分别呈现。
- 关键数值必须同时保留统计口径、地域、数据期和来源；缺任一项时移入待核验清单，不得用于评分或结论。
- 龙头公司、上市公司、平台公司的资料只能作为 representative_company 对标样本；除非任务明确要求目标公司尽调，否则不得使用“目标公司”“标的经营风险”“工商尽调结论”等公司尽调语义。
"""
    return f"""
请扮演「{report_kind}」第 {index} 章专项写作 Agent。你只负责本章，不要写其他章节。

完整标准目录：
{format_outline(outline)}

当前章节：{index}. {section_title}
本章节任务书：
{json.dumps(requirements, ensure_ascii=False, indent=2)}

{GLOBAL_REPORT_RULES}

{VISUAL_EVIDENCE_RULES}

{scope_rules}

证据约束：不得把“未找到履约证明”写成“未履约/未兑现”，不得把“未发现记录”写成“确认不存在”。
观点、评论和媒体推测必须标为来源观点，不能改写为已确认事实。报告日期和编制日期由后端注入，禁止自行生成日期。

{output_structure}

章节风格 few-shot / 表达锚点：
{few_shot or "暂无专门示例；请严格按任务书、证据和输出骨架写。"}

参考交付风格：
{REFERENCE_REPORT_STYLE}

项目：{project.title}
研究对象：{project.target_name}
对象类型：{project.target_type}
行业：{project.industry}
项目背景：{project.description}

{evidence_package_label}
{clip(focused_cleaned, 14000)}

风险研判：
{clip(risk_json, 6000)}
"""


def build_editor_prompt(
    *,
    report_kind: str,
    outline: list[tuple[str, list[str]]],
    project: Any,
    draft: str,
    risk_json: str,
    clip,
) -> str:
    return f"""
请扮演「{report_kind}」总编 Agent，对分章节草稿进行最终合并、去重、统一口径和交付格式修订。

标准目录必须逐项保留：
{format_outline(outline)}

{GLOBAL_REPORT_RULES}

{VISUAL_EVIDENCE_RULES}

{EDITOR_RULES}

参考交付风格：
{REFERENCE_REPORT_STYLE}

报告元信息：
- 项目：{project.title}
- 研究对象：{project.target_name}
- 对象类型：{project.target_type}
- 行业：{project.industry}
- 项目背景：{project.description}

风险研判：
{clip(risk_json, 7000)}

分章节草稿：
{clip(draft, 42000)}
"""
