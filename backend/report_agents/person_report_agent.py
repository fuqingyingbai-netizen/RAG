import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from .report_prompts import (
    build_editor_prompt,
    build_section_prompt,
    classify_person_fact_scope,
    person_evidence_level,
    person_scope_note,
)
from .report_style import REFERENCE_REPORT_STYLE, REPORT_CHAPTER_HEADING_RE, ensure_delivery_sections


PERSON_REPORT_OUTLINE = [
    ("摘要", ["报告概述", "核心发现点", "需关注信号", "公司所属赛道竞争格局", "总体评估"]),
    ("创始人底色画像", ["家庭/教育/健康/婚姻等基本信息", "社会关系与数字身份", "关键履历节点", "履历断点与异常经历", "失信违规、重大挫折及潜在声誉风险"]),
    ("人格特质风险", ["责任心", "诚信度", "事业心", "表达能力", "风险偏好", "压力反应", "利益取舍", "行为稳定性与潜在性格短板"]),
    ("经营胜任力、持续创新与迭代能力验证", ["顶层业务设计", "行业前瞻", "战略执行", "资本对接", "资源统筹", "创新迭代", "项目落地", "问题处置", "复盘优化", "持续学习"]),
    ("识人用人、统筹管理及核心经营管控能力", ["团队搭建", "文化塑造", "授权机制", "冲突处理", "关键用人", "核心团队稳定性", "组织治理和团队失控风险"]),
    ("核心管理团队背景调研", ["管理层履历", "产业资源", "关联关系", "管理能力", "团队掌控力", "派系斗争或人事动荡风险"]),
    ("商业操守与个人信用风险核查", ["员工/合作伙伴/同行/客户评价", "行业口碑", "诚信水平", "契约精神", "职业操守"]),
    ("同业对标下综合能力与品行隐患评估", ["同业竞争对手横向对标", "综合素养短板", "个人行事风格风险", "信用问题对企业长期经营的影响"]),
    ("关联利益冲突及司法负面核查", ["体外关联产业", "隐性持股", "亲友代持", "关联交易", "资源输送", "同业竞争", "诉讼纠纷", "行政处罚", "监管记录", "负面舆情", "重大异常事项"]),
    ("专项调研", ["根据项目重点填写具体专项方向", "债务/婚姻纠纷/资产转移/业绩真实性/股东关系/知识产权/创业压力等高敏感事项"]),
    ("投后治理及退出风险研判", ["上市/退出路径", "投资方与创始团队决策沟通", "制度落地", "信息同步", "董事会议事", "重大事项审批", "低效治理情形", "持续经营与退出路径影响"]),
    ("风险核查", ["经验不足", "业务能力局限", "战略能力", "管理能力局限", "驱动力不足", "资源局限", "贪腐", "创业目的不纯", "个人道德问题", "商业信誉度低", "不良嗜好", "为人处世风格问题", "奢侈消费观", "个人健康风险", "婚变风险", "诉讼纠纷及舆情监管", "学术/职业经理人/连续创业者/草根创业者等画像风险"]),
    ("综合评估", ["总结打分"]),
    ("信息来源", ["信息点", "网址/来源说明", "检索工具", "可信度", "支持章节"]),
    ("后续研究点", ["待确认信息点", "下一步深度研究方向", "优先级排序", "建议数据源/访谈对象"]),
]


# The deterministic fallback must not rotate arbitrary facts through the outline.
# These mappings are intentionally conservative: a fact is eligible only when its
# cleaning module or text has a defensible relationship with the chapter.
PERSON_SECTION_EVIDENCE_RULES: dict[int, dict[str, tuple[str, ...]]] = {
    2: {"modules": ("创始人底色画像（家庭/教育/履历）", "个人背景", "教育与履历", "身份核验", "关联利益", "关联机构", "经营业绩", "团队与治理"), "keywords": ("教育", "学校", "学历", "毕业", "履历", "任职", "创办", "创立", "成立", "创业", "家庭", "父母", "配偶", "子女", "出生", "身份", "曾用名")},
    3: {"modules": ("人格特质与诚信评估", "口碑与操守", "商业操守与行业口碑", "个人背景", "教育与履历", "关联机构"), "keywords": ("诚信", "责任", "表达", "风险偏好", "压力", "口碑", "评价", "风格", "领导", "决策", "危机", "争议", "性格", "价值观")},
    4: {"modules": ("经营胜任力（战略/执行/创新）", "经营业绩", "关联利益", "团队与治理", "身份核验", "教育与履历"), "keywords": ("战略", "执行", "创新", "经营", "业绩", "融资", "上市", "收购", "扩张", "转型", "增长", "营收")},
    5: {"modules": ("识人用人与团队管控", "团队与治理", "核心管理团队背景", "经营业绩", "关联利益", "个人背景"), "keywords": ("团队", "管理", "高管", "组织", "文化", "用人", "离职", "稳定性", "组织架构", "授权", "接班人")},
    6: {"modules": ("核心管理团队背景", "团队与治理", "识人用人与团队管控", "关联利益", "经营业绩", "教育与履历"), "keywords": ("管理团队", "高管", "董事", "CEO", "总裁", "合伙人", "CFO", "CTO", "COO", "副总裁", "核心成员")},
    7: {"modules": ("商业操守与行业口碑", "口碑与操守", "信用与处罚", "个人信用与财务风险", "司法信用", "关联利益", "个人背景", "教育与履历"), "keywords": ("操守", "口碑", "诚信", "履约", "信用", "处罚", "评价", "声誉", "争议", "负面", "诉讼", "纠纷")},
    8: {"modules": ("经营胜任力（战略/执行/创新）", "经营业绩", "口碑与操守", "关联利益", "团队与治理", "身份核验", "教育与履历"), "keywords": ("同业", "竞争", "对比", "对标", "优势", "劣势", "差异", "行业", "经营", "能力", "口碑", "排名")},
    9: {"modules": ("关联利益", "关联机构", "关联利益冲突（体外公司/代持/关联交易）", "司法负面与诉讼核查", "司法信用", "信用与处罚", "上市披露", "个人信用与财务风险"), "keywords": ("关联", "持股", "控制", "代持", "体外", "输送", "配偶", "亲属", "子女", "诉讼", "处罚", "监管", "司法", "利益冲突")},
    10: {"modules": ("司法负面与诉讼核查", "司法信用", "信用与处罚", "个人信用与财务风险", "知识产权", "关联利益"), "keywords": ("债务", "资产", "诉讼", "监管", "知识产权", "专项", "执行", "破产", "冻结", "质押")},
    11: {"modules": ("团队与治理", "经营业绩", "上市披露", "关联利益", "司法信用", "口碑与操守"), "keywords": ("治理", "董事", "股东", "上市", "退出", "决策", "投资", "IPO", "并购", "回购", "董事会")},
    12: {"modules": ("司法负面与诉讼核查", "司法信用", "信用与处罚", "个人信用与财务风险", "关联利益", "口碑与操守", "上市披露"), "keywords": ("风险", "诉讼", "处罚", "失信", "负面", "监管", "信用", "执行", "限高", "违法", "违规", "调查")},
}

FALLBACK_MARKER = "本章为自动检索证据底稿内容，尚未进入人工尽调核验。"
LEGACY_FALLBACK_MARKER = "本章为确定性证据保底内容，尚未完成人工分析复核。"

_BASIC_PROFILE_FACT_KEYWORDS = (
    "出生", "籍贯", "出生地", "教育", "学校", "学历", "学位", "毕业", "专业",
    "任教", "讲师", "教师", "早年", "成长", "职业", "履历", "任职", "创办", "创立", "公益",
)

_SENSITIVE_GAP_KEYWORDS = (
    "司法", "诉讼", "失信", "被执行", "限高", "处罚", "监管", "债务", "资产",
    "冻结", "质押", "婚姻", "健康", "腐败", "代持", "控制权", "违法", "违规",
)

# Chapters where related-party (关联企业) evidence may be used for reasoned
# inference when direct person-level evidence is sparse.  The section writer is
# still required to tag every inference with a boundary marker and keep the
# original evidence id.
PERSON_RELATED_PARTY_CHAPTERS: set[int] = {4, 6}
PERSON_INDIRECT_EVIDENCE_CHAPTERS: set[int] = {4, 5, 6, 8, 9, 10, 11, 12, 13}
PERSON_SENSITIVE_CHAPTERS: set[int] = {7, 9, 10, 12}
_AUTHORITY_DOMAINS = (
    "gov.cn", "court.gov.cn", "wenshu.court.gov.cn", "zxgk.court.gov.cn",
    "cninfo.com.cn", "sse.com.cn", "szse.cn", "hkexnews.hk", "sec.gov",
    "pbc.gov.cn", "csrc.gov.cn", "samr.gov.cn", "cnipa.gov.cn",
)
_FACT_NOISE_MARKERS = ("上一页", "下一页", "快讯", "cb=", "error calling tool", "...[truncated]", "空结果：")


PERSON_SECTION_STRUCTURES = {
    1: """
创始人报告专属章节输出骨架：
## 1. 摘要

必须用短段落或要点覆盖以下五块，不要使用“本章结论/事实梳理/分析判断/风险与待核验”四段式：
- 执行摘要：报告概述、研究对象、公司/项目定位、当前阶段。
- 核心发现：创始人/团队最重要的可验证亮点、能力互补、关键成果。
- 关键验证与修正：履历修正、职位夸大、时间空白、公开数据矛盾、产品/融资/媒体覆盖缺口。
- 需关注信号：声誉、诚信、履历、产品、团队磨合、信息密度不足等风险信号。
- 竞争格局与总体评估：公司所属赛道竞争格局、相对位置、总体等级/推进建议。
""",
    2: """
创始人报告专属章节输出骨架：
## 2. 创始人底色画像

建议使用以下子结构，不要套用通用四段式：
- 基本底色：家庭、教育、健康、婚姻、社会关系；证据不足必须明示。
- 数字身份与个人品牌：公开账号、统一昵称、对外叙事策略。
- 人物-公司-项目关系网图：仅保留本小标题和“待核验关系节点表”，不要输出 Mermaid、graph LR/TD 或字符画；系统会根据结构化证据在此处插入关系图图片。
- 职业阶段时间线：按阶段列明时间、机构/项目、角色、可验证成果、异常或待核验点、来源。
- 履历断点与异常：空白期、职位表述不一致、夸大/遗漏、重大挫折。
- 声誉与合规风险初判：失信违规、重大负面、公开争议和后续核验路径。

待核验关系节点表建议列：节点/主体｜关系类型｜已知证据｜证据强度｜待核验问题｜建议核验渠道。
""",
    3: """
创始人报告专属章节输出骨架：
## 3. 人格特质风险

围绕责任心、诚信度、事业心、表达能力、风险偏好、压力反应、利益取舍展开。建议使用“维度｜公开信号｜正面解释｜风险解释｜证据强度｜待核验动作”表格，并在表后给出行为稳定性判断。
""",
    4: """
创始人报告专属章节输出骨架：
## 4. 经营胜任力、持续创新与迭代能力验证

必须覆盖顶层业务设计、行业前瞻、战略执行、资本对接、资源统筹、创新迭代能力，并分别核查项目落地：能否将顶层战略拆解为阶段性任务，保障业务目标如期达成；问题处置：面对市场波动、经营难题，行动效率与应变水平；复盘优化：定期总结业务得失，及时调整经营路线，不固守旧模式；持续学习：吸收行业新技术、新模式，与时俱进完成组织与业务升级。建议用“能力项｜已验证事实｜对当前公司阶段的意义｜短板/约束｜证据强度”表格。
""",
    5: """
创始人报告专属章节输出骨架：
## 5. 识人用人、统筹管理及核心经营管控能力

按“权责 + 人事 + 经营”三位一体评估团队搭建、文化塑造、授权机制、冲突处理、关键用人、核心团队稳定性。重点识别组织治理和团队失控风险。
""",
    6: """
创始人报告专属章节输出骨架：
## 6. 核心管理团队背景调研

摸清管理层履历、产业资源、关联关系、管理能力和团队掌控力。建议输出“成员｜角色｜履历与资源｜与创始人关系｜可验证成果｜治理隐患｜来源/待核验”表格，并说明是否存在派系斗争、人事动荡或关键人依赖。
""",
    7: """
创始人报告专属章节输出骨架：
## 7. 商业操守与个人信用风险核查

从员工、合作伙伴、同行、客户等多方口径交叉验证行业口碑、诚信水平、契约精神与职业操守。没有访谈材料时，不得虚构评价，必须写“暂无访谈证据”，并给出应访谈对象和问题清单。
""",
    8: """
创始人报告专属章节输出骨架：
## 8. 同业对标下综合能力与品行隐患评估

横向对标行业竞争对手或同阶段创始人，研判综合素养短板。建议结构：同业横向对标表、能力短板归纳、个人行事风格/信用问题对企业长期经营的影响。
""",
    9: """
创始人报告专属章节输出骨架：
## 9. 关联利益冲突及司法负面核查

排查体外关联产业、隐性持股、亲友代持、关联交易、资源输送、同业竞争，以及诉讼纠纷、行政处罚、监管记录、负面舆情、重大异常事项。建议用“事项｜发现/未发现｜证据来源｜风险含义｜下一步核验”表格。

若本章材料含“人物关联企业上下文”，该企业的专业平台结构化信息属于独立证据类型：只能表述为关联企业的工商、股权、高管或风险信息，绝不能改写为创始人的个人信用、司法或持股事实。必须写清关系类型、证据强度、受控一跳边界和待核验点；不得因该企业资料未重复出现人物姓名而忽略，也不得把平台返回的二跳股东、子公司或投资企业扩展为新的穿透对象。
""",
    10: """
创始人报告专属章节输出骨架：
## 10. 专项调研 - （写具体调研方向）

标题中的括号必须替换为结合本项目材料识别出的具体方向，例如“知识产权与技术归属专项风险评估”“创业压力与债务专项风险评估”等。核验诉讼纠纷、行政处罚、监管记录、负面舆情及重大异常事项，识别财务、合规、声誉及融资上市风险。围绕债务、婚姻纠纷、资产转移、业绩真实性、股东关系、知识产权、创业压力等高敏感事项开展定向核查。
""",
    11: """
创始人报告专属章节输出骨架：
## 11. 投后治理及退出风险研判

必须覆盖上市/退出路径（港股/A股/美股等）、投后治理机制评估（投资交割完成后，基金投资方与创始团队之间的决策沟通顺畅程度；=制度落地、信息同步、董事会议事、重大事项审批的顺畅程度；根据创始人管理风格、核心团队稳定性、关键岗位承接及组织能力，评估是否会影响公司持续经营和投后治理效率）。需列举低效治理情形：独断决策、信息壁垒、抵触规范化管理、管理层内讧、股东权责无法落地，并判断对持续经营和退出路径的影响。
""",
    12: """
创始人报告专属章节输出骨架：
## 12. 风险核查

按风险字典逐类筛查，不要泛泛罗列。建议表格列：风险类别｜本项目是否出现信号｜具体表现｜证据来源｜风险等级｜核验动作。风险类别至少覆盖：经验不足、业务能力局限、战略能力、管理能力局限、驱动力不足、资源局限、贪腐、创业目的不纯、个人道德问题、商业信誉度低、不良嗜好、为人处世风格问题、奢侈消费观、个人健康风险、婚变风险、诉讼纠纷及舆情监管，并根据学术背景/职业经理人/连续创业者/草根创业者画像补充特定风险。
""",
    13: """
创始人报告专属章节输出骨架：
## 13. 综合评估

综合上述研究内容，对标的人物或创始团队进行总结打分。建议结构：整体评级、分项评分表、核心加分项、核心扣分项、关键判断、投资推进建议。评分必须说明证据强弱和不确定性。
""",
    14: """
创始人报告专属章节输出骨架：
## 14. 信息来源

注明检索的信息来源，包括信息点、网址或来源说明、检索工具、可信度、支持章节。建议表格列：信息点｜来源标题/平台｜URL或来源说明｜数据获取工具｜可信度｜支持章节。
""",
    15: """
创始人报告专属章节输出骨架：
## 15. 后续研究点

给出待确认信息点和下一步深度研究方向。必须按高/中/低优先级排序，并说明建议数据源/访谈对象、预期判断价值、触发的投资决策问题。
""",
}


PERSON_RISK_TAXONOMY = """
风险核查字典：
- 经验不足：落地经验不足、实践经验匮乏、缺乏商业化经验、无整体操盘经验、精细化管理经验不足。
- 业务能力局限：思维认知局限、商业洞察滞后、顶层设计能力不足、成本意识淡薄、缺乏创新迭代意识、股权结构搭建草率、不擅长品牌营销。
- 战略能力：欠缺战略管理意识、机会判断偏差、战略目标不明确、战略布局缺乏全局观、组织构建不及时、战略执行不力、缺乏战略耐心、战略制定缺乏连续性。
- 管理能力局限：人才识别不清、任人唯亲、偏听偏信、内部派系林立、管理制度不完善、忽视企业文化建设、团队梯队断层、管理缺乏人性化、组织架构变动频繁。
- 驱动力不足：创业目标模糊、缺乏韧性、自控力差、缺乏财富欲望。
- 资源局限：人脉积累薄弱、资源不具备广泛性、资源拓展/转化进度不畅、资源整合能力不足、资源政治风险的潜在连带风险。
- 贪腐/利益问题：在职消费、职务侵占、体系外关联交易、收受贿赂、中饱私囊、跑冒滴漏。
- 创业目的不纯：追求短期利益、套现离场、吸引融资偿还巨额债务、投机主义。
- 个人道德与商业信用：言语不实、诚信缺失、违背信义、违法违规、谋取私利、恶意诋毁、出尔反尔、擅自毁约、拖欠合同款项、履约能力差。
- 生活与健康风险：不良嗜好、奢侈消费观、重大疾病史、慢性疲劳、焦虑抑郁、婚变风险。
- 诉讼纠纷及舆情监管：失信、限高、重大被诉、知识产权纠纷、或有负债、桃色新闻、政治风险。
- 画像特定风险：学术背景、职业经理人、连续创业者、草根创业者分别可能对应商业化、角色转换、短期化扩张、家族式管理等风险。
"""


PERSON_SECTION_FEW_SHOTS = {
    1: "摘要表达：研究对象与范围；已引用核心事实；关键矛盾；需关注信号；有边界的总体判断。不得引入其他项目示例。",
    13: "综合评估表达：按前文证据汇总优势、局限、未知项和核验优先级；未建立量表不评分。",
    14: "信息来源：信息点、原始网址或结构化记录、工具、等级、日期和实际支持章节。",
    15: "后续研究点：待确认问题、优先级、建议来源、完成核验条件。",
}



PERSON_FEW_SHOT = f"""
创始人桌面研究报告写作要求：
- 本报告固定为 15 节，章节标题必须与标准目录一致；每节使用该节专属结构，不得机械套用“本章结论/事实梳理/分析判断/风险与待核验”。
- 证据不足处正文只写“待核验”，不要反复写“暂无充分公开证据”；所有缺口统一进入集中式待核验清单，不得编造访谈、司法、婚姻、健康、债务或私生活信息。
- 履历表建议列：时间｜机构/项目｜角色｜可验证成果｜异常或待核验点｜来源。
- 风险核查表建议列：风险类别｜已发现信号｜证据来源｜风险等级｜后续核验动作。
- 对带有“人物关联企业上下文”的专业平台材料，必须视为关联企业证据而不是人物个人事实；关联企业受控穿透台账由系统固定注入第9节，写作时应围绕其关系边界、风险含义和待核验事项展开，不得删除或改写台账事实。

{PERSON_RISK_TAXONOMY}
"""


class PersonReportAgent:
    report_kind = "BDD目标人物桌面研究报告"
    trace_agent = "person_report_agent"
    outline = PERSON_REPORT_OUTLINE

    def generate(
        self,
        project: Any,
        cleaned_json: str,
        risk_json: str,
        invoke: Callable[[str, str, Any], str],
        clip: Callable[[str, int], str],
        emit: Callable[..., None],
        trace_emit: Any = None,
    ) -> str:
        try:
            from ..person_evidence import generate_person_report
        except ImportError:
            from person_evidence import generate_person_report
        return generate_person_report(project, cleaned_json, risk_json, self.outline, invoke, emit, trace_emit)

    def _write_section(self, project: Any, cleaned_json: str, risk_json: str, index: int, section_title: str, requirements: list[str], invoke: Callable[[str, str, Any], str], clip: Callable[[str, int], str], emit: Callable[..., None], trace_emit: Any) -> str:
        emit(trace_emit, "report", self.trace_agent, "章节写作启动", f"{index}/{len(self.outline)} {section_title}", section=section_title, status="running")
        evidence_policy = self._section_evidence_policy(cleaned_json, index)
        prompt = build_section_prompt(
            report_kind=self.report_kind,
            outline=self.outline,
            project=project,
            cleaned_json=cleaned_json,
            risk_json=risk_json,
            index=index,
            section_title=section_title,
            requirements=requirements,
            clip=clip,
            few_shot="\n\n".join([PERSON_FEW_SHOT, PERSON_SECTION_FEW_SHOTS.get(index, "")]).strip(),
            section_structure=PERSON_SECTION_STRUCTURES.get(index, ""),
        )
        prompt += """

本章证据闸门：必须保留本章编号与标题。只有直接证据才可写成事实；证据不足时用一句“本章证据状态：待核验”，不得用通用常识扩写，不得输出 OMIT_SECTION 或 HTML 注释。具体缺口统一放入第15章和集中式待核验清单。
"""
        prompt += """

硬性输出验收：本章必须包含 `## 编号. 标题`。若本章有可用证据，须列出一条或多条可审计事实，并在每条事实后保留原始来源 URL（含 `https://` / `http://` 网页链接或 `structured://` 结构化记录标识）；若证据确实不足，允许以一句"本章证据状态：待核验"取代事实展开，不得编造或扩写。
"""
        prompt += (
            "\n\n风险归因红线：目标人、关联企业和企业集团的事实必须分开表述。"
            "关联企业的处罚、诉讼、被执行或经营风险，不得写成目标人个人违法、被处罚或失信；"
            "除非来源直接证明目标人是当事人。实际控制关系必须标注截至日期和权威来源，无法确认则写待核验。"
        )
        prompt += f"""

本章证据等级政策（必须执行）：
{evidence_policy}

证据等级写法：
- A/B 级直接证据：可以写事实判断，但必须保留来源和口径。
- C 级弱来源：只能写“公开线索/二手资料显示”，不能写最终结论。
- D 级关联企业或集团背景证据：只能写“关联企业层面观察”“间接推断”“仍需核验”，不得直接证明人物个人信用、个人操守、司法责任或确定控制关系。
- E 级或无证据：只写待核验，不展开分析。
- 表格中必须保留“证据等级/边界”或同等字段。
"""
        if index in PERSON_RELATED_PARTY_CHAPTERS:
            prompt += """
\n关联企业证据推演规则（仅本章适用）：
- 当直接指向目标人物个人的证据不足时，允许使用其核心关联企业（如曾创立/长期控制的企业）的经营表现、战略决策和团队信息进行有边界的推演。
- 每项基于关联企业的推演必须标注边界词（"基于关联企业公开信息推演""间接证据""关联企业层面观察"），并保留原始证据编号或 URL。
- 推演总数不超过 3 条；不得将企业整体数据直接写为目标人物个人能力或成就。
- 证据确实无法支撑任何推演时，正文保留一句"本章证据状态：本次公开检索未形成可直接归属目标人物的充分证据"，具体缺口统一列入第15章。
"""
        answer = invoke(f"{self.report_kind}章节 Agent - {section_title}", prompt, trace_emit)
        if answer.strip() and "OMIT_SECTION" not in answer:
            emit(trace_emit, "report", self.trace_agent, "章节写作完成", section_title, section=section_title, status="done")
            return answer.strip()
        return self._evidence_gap_section(index, section_title)

    def _evidence_gap_section(self, index: int, section_title: str) -> str:
        return (
            f"## {index}. {section_title}\n\n"
            "本章证据状态：待核验。现有公开材料不足以形成可靠结论，"
            "相关核验事项统一列入第15章及集中式待核验清单。"
        )

    def _split_numbered_sections_strict(self, report: str) -> dict[int, str]:
        # Only level-2 headings identify chapters; e.g. ``### 1.1`` is a subsection.
        matches = list(REPORT_CHAPTER_HEADING_RE.finditer(report or ""))
        sections: dict[int, str] = {}
        for position, match in enumerate(matches):
            index = int(match.group(1))
            if index not in range(1, len(self.outline) + 1) or index in sections:
                continue
            end = matches[position + 1].start() if position + 1 < len(matches) else len(report)
            sections[index] = report[match.start():end].strip()
        return sections

    def _ensure_outline_sections(self, report: str) -> str:
        """Compatibility helper used by revisions and regression tests."""
        parsed = self._split_numbered_sections_strict(report)
        first_heading = REPORT_CHAPTER_HEADING_RE.search(report or "")
        preamble = (report[:first_heading.start()].strip() if first_heading else (report or "").strip())
        sections = [
            parsed.get(index) or self._evidence_gap_section(index, title)
            for index, (title, _requirements) in enumerate(self.outline, 1)
        ]
        return "\n\n".join(([preamble] if preamble else []) + sections).strip()

    def _section_usability(self, section: str, index: int) -> dict[str, Any]:
        text = str(section or "").strip()
        has_heading = bool(re.search(rf"(?m)^##\s*{index}\s*(?:[、．）)]|\.(?!\d))\s*[^\n]+$", text))
        body = re.sub(r"\s+", "", re.sub(r"(?m)^#.*$", "", text))
        urls = set(re.findall(r"(?:https?|structured)://[^\s)\]|>]+", text))
        # Person chapters often rely on weak public materials, interviews, or
        # related-company evidence whose full trace is carried by the automatic
        # audit index. Do not force narrative sections to print raw URLs.
        min_urls = int(os.getenv("PERSON_REPORT_SECTION_MIN_URLS", "0") or 0)
        min_body = 500 if index in PERSON_RELATED_PARTY_CHAPTERS else 320
        needs_boundary = index in PERSON_SENSITIVE_CHAPTERS or index in PERSON_INDIRECT_EVIDENCE_CHAPTERS
        has_boundary = any(marker in text for marker in ("证据等级", "证据边界", "边界", "间接", "待核验", "关联企业层面"))
        noise_markers = [marker for marker in _FACT_NOISE_MARKERS if marker in text.lower()]
        reasons: list[str] = []
        if not has_heading:
            reasons.append("heading_format")
        if len(body) < min_body:
            reasons.append("body_too_short")
        if len(urls) < min_urls:
            reasons.append("missing_url")
        if needs_boundary and not has_boundary:
            reasons.append("missing_boundary")
        if noise_markers:
            reasons.append("noise_marker")
        return {
            "usable": not reasons,
            "reasons": reasons,
            "body_len": len(body),
            "min_body": min_body,
            "url_count": len(urls),
            "min_urls": min_urls,
            "has_heading": has_heading,
            "needs_boundary": needs_boundary,
            "has_boundary": has_boundary,
            "noise_markers": noise_markers,
        }

    def _section_is_usable(self, section: str, index: int) -> bool:
        return bool(self._section_usability(section, index)["usable"])

    def _repair_section_heading(self, section: str, index: int, section_title: str) -> str:
        text = str(section or "").strip()
        if not text:
            return text
        canonical = f"## {index}. {section_title}"
        if re.search(rf"(?m)^##\s*{index}\s*(?:[、，:：]|\.(?!\d))\s*[^\n]+$", text):
            return text
        lines = text.splitlines()
        for pos, line in enumerate(lines[:8]):
            compact = re.sub(r"\s+", "", line)
            if re.match(rf"^#*\s*{index}\s*(?:[、，:：.]|．)?", line) or section_title and section_title in line:
                lines[pos] = canonical
                return "\n".join(lines).strip()
        return canonical + "\n\n" + text

    def _fact_source_strength(self, item: dict[str, Any]) -> tuple[int, str]:
        scope = str(item.get("evidence_scope") or "")
        level = str(item.get("evidence_level") or "")
        if level in {"A", "B", "C", "D", "E"}:
            return ({"A": 4, "B": 3, "C": 2, "D": 1, "E": 0}[level], f"{level}-{person_scope_note(scope, level)}")
        url = str(item.get("source_url") or "").lower()
        evidence_type = str(item.get("evidence_type") or "").lower()
        if evidence_type == "primary_record" or any(domain in url for domain in _AUTHORITY_DOMAINS):
            return (4, "A-权威/原始记录")
        if evidence_type == "media_report":
            return (2, "B-媒体报道")
        if evidence_type == "media_narrative":
            return (0, "C-媒体叙述/观点")
        return (1, "C-公开网页线索")

    def _annotate_person_fact(self, item: dict[str, Any]) -> dict[str, Any]:
        row = dict(item or {})
        scope = str(row.get("evidence_scope") or classify_person_fact_scope(row, ""))
        level = str(row.get("evidence_level") or person_evidence_level(row, ""))
        row["evidence_scope"] = scope
        row["evidence_level"] = level
        row["evidence_boundary"] = str(row.get("evidence_boundary") or person_scope_note(scope, level))
        return row

    def _section_evidence_policy(self, cleaned_json: str, index: int) -> str:
        selected, _gaps = self._rank_section_facts(cleaned_json, index)
        counts = {level: 0 for level in ("A", "B", "C", "D", "E")}
        scopes: dict[str, int] = {}
        for item in selected:
            level = str(item.get("evidence_level") or "E")
            counts[level] = counts.get(level, 0) + 1
            scope = str(item.get("evidence_scope") or "unknown")
            scopes[scope] = scopes.get(scope, 0) + 1
        lines = [
            f"- 本章证据包等级统计：A={counts.get('A', 0)}，B={counts.get('B', 0)}，C={counts.get('C', 0)}，D={counts.get('D', 0)}，E={counts.get('E', 0)}。",
            f"- 证据归属统计：{json.dumps(scopes, ensure_ascii=False)}。",
        ]
        if index in PERSON_SENSITIVE_CHAPTERS:
            lines.append("- 本章属于高敏感章节：若没有 A/B 级直接证据，不得输出关于目标人物个人违法、失信、操守缺陷、债务、婚姻、健康或法律责任的确定判断。")
        if index in PERSON_INDIRECT_EVIDENCE_CHAPTERS:
            lines.append("- 本章允许使用 D 级关联企业/集团背景材料，但只能作为间接观察或后续核验线索。")
        if not selected:
            lines.append("- 本章未检出可用证据：只保留待核验句和后续核验动作。")
        return "\n".join(lines)

    def _section_evidence_summary(self, cleaned_json: str, index: int) -> dict[str, Any]:
        selected, _gaps = self._rank_section_facts(cleaned_json, index)
        counts = {level: 0 for level in ("A", "B", "C", "D", "E")}
        structured = 0
        urls: set[str] = set()
        for item in selected:
            row = self._annotate_person_fact(item)
            level = str(row.get("evidence_level") or "E")
            counts[level] = counts.get(level, 0) + 1
            url = str(row.get("source_url") or "")
            if url:
                urls.add(url.rstrip("/"))
            if url.startswith("structured://") or row.get("category") == "person_affiliation_structured":
                structured += 1
        return {
            "selected_facts": len(selected),
            "unique_urls": len(urls),
            "structured_facts": structured,
            "evidence_levels": counts,
        }

    def _basic_profile_relevance(self, item: dict[str, Any]) -> int:
        text = " ".join(
            str(item.get(key) or "")
            for key in ("module", "fact", "source_title", "source_url")
        )
        hits = sum(1 for keyword in _BASIC_PROFILE_FACT_KEYWORDS if keyword in text)
        return min(hits, 8)

    def _gap_is_chapter_specific(self, gap: str, index: int) -> bool:
        if index == 15:
            return True
        if index == 2:
            return any(keyword in gap for keyword in _BASIC_PROFILE_FACT_KEYWORDS)
        if index in {7, 9, 10, 12}:
            return any(keyword in gap for keyword in _SENSITIVE_GAP_KEYWORDS)
        return False

    def _fact_allowed_for_section(self, item: dict[str, Any], index: int) -> bool:
        """Use identity classification as a writing gate, not as retrieval gate."""
        if item.get("eligible_for_report") is False:
            return False
        identity = str(item.get("identity_match") or "").lower()
        identity_confidence = str(item.get("identity_confidence") or "").lower()
        usable_as = str(item.get("usable_as") or "").lower()
        has_affiliation = bool(item.get("person_affiliation")) or str(item.get("category") or "") == "person_affiliation_structured"
        if usable_as == "identity_quarantine" or identity in {"mismatch", "ambiguous"} or identity_confidence in {"low", "rejected"}:
            return False
        if index in PERSON_SENSITIVE_CHAPTERS and not has_affiliation:
            return identity in {"confirmed", "probable"} or identity_confidence in {"high", "medium"}
        if index in PERSON_SENSITIVE_CHAPTERS and has_affiliation:
            # Related-company evidence can support a bounded risk observation,
            # never a direct personal legal / credit conclusion.
            return True
        return True

    def _rank_section_facts(self, cleaned_json: str, index: int) -> tuple[list[dict[str, Any]], list[str]]:
        try:
            payload = json.loads(cleaned_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return ([], [])
        facts = [item for item in payload.get("facts", []) if isinstance(item, dict)]
        all_gaps = [str(item).strip() for item in payload.get("information_gaps", []) if str(item).strip()]
        gaps = [gap for gap in all_gaps if self._gap_is_chapter_specific(gap, index)]
        rule = PERSON_SECTION_EVIDENCE_RULES.get(index)
        ranked: list[tuple[float, dict[str, Any]]] = []
        seen: set[tuple[str, str]] = set()
        for item in facts:
            if not self._fact_allowed_for_section(item, index):
                continue
            fact = re.sub(r"\s+", " ", str(item.get("fact") or "")).strip()
            url = str(item.get("source_url") or "").strip()
            # Accept any non-empty source_url so that structured business records
            # (QCC / Xiniu / Tianyancha with structured:// locators) can enter the
            # evidence-backed fallback table — the same repair applied to the
            # company-report audit index in v8.
            if not fact or not url:
                continue
            if any(marker in fact.lower() for marker in _FACT_NOISE_MARKERS):
                continue
            item = self._annotate_person_fact(item)
            key = (re.sub(r"\W+", "", fact.lower())[:180], url.rstrip("/"))
            if key in seen:
                continue
            seen.add(key)
            module = str(item.get("module") or "")
            blob = " ".join((module, fact, str(item.get("source_title") or "")))
            source_bonus, _label = self._fact_source_strength(item)
            affiliation = item.get("person_affiliation") if isinstance(item.get("person_affiliation"), dict) else {}
            try:
                affiliation_rank = int(affiliation.get("selection_rank")) if affiliation else 0
            except (TypeError, ValueError):
                affiliation_rank = 0
            secondary_affiliation_penalty = 3 if affiliation and affiliation_rank > 0 else 0
            basic_profile_hits = self._basic_profile_relevance(item) if index == 2 else 0
            if rule:
                module_match = module in rule["modules"]
                keyword_hits = sum(1 for keyword in rule["keywords"] if keyword in blob)
                if index == 2 and not module_match and basic_profile_hits <= 0:
                    continue
                # Assign minimal relevance (0) to facts that match neither the
                # expected module nor any keyword, rather than discarding them
                # outright.  The relevance floor lets under-matched facts surface
                # when a chapter has few better candidates, while the cap of 5
                # prevents a single low-quality flood.
                relevance = (8 if module_match else 0) + min(keyword_hits, 4)
            else:
                relevance = 2
            if index == 2:
                relevance = max(relevance, basic_profile_hits + 6)
            try:
                confidence = float(item.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = 0
            ranked.append((relevance + source_bonus + min(max(confidence, 0), 1) - secondary_affiliation_penalty, item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        selected: list[dict[str, Any]] = []
        used_urls: set[str] = set()
        secondary_affiliation_count = 0
        for _score, item in ranked:
            url_key = str(item.get("source_url") or "").rstrip("/")
            if url_key in used_urls:
                continue
            affiliation = item.get("person_affiliation") if isinstance(item.get("person_affiliation"), dict) else {}
            try:
                affiliation_rank = int(affiliation.get("selection_rank")) if affiliation else 0
            except (TypeError, ValueError):
                affiliation_rank = 0
            if affiliation and affiliation_rank > 0:
                secondary_affiliation_count += 1
                if secondary_affiliation_count > 1:
                    continue
            selected.append(item)
            used_urls.add(url_key)
            if len(selected) >= (12 if index == 2 else 8 if index in {14, 15} else 5):
                break
        return (selected, gaps)

    def _profile_bucket(self, item: dict[str, Any]) -> str:
        text = " ".join(str(item.get(key) or "") for key in ("module", "fact", "source_title"))
        if any(keyword in text for keyword in ("教育", "学校", "学历", "学位", "毕业", "专业", "education", "degree")):
            return "教育背景"
        if any(keyword in text for keyword in ("任教", "讲师", "教师", "任职", "就职", "创办", "创立", "创业", "career")):
            return "职业路径"
        if any(keyword in text for keyword in ("出生", "籍贯", "出生地", "姓名", "身份")):
            return "基本身份"
        if any(keyword in text for keyword in ("早年", "成长", "高考", "家庭")):
            return "早年经历"
        if any(keyword in text for keyword in ("公益", "社会职务", "社会组织", "公共服务")):
            return "公开身份"
        if any(keyword in text for keyword in ("合伙人", "联合创始人", "投资人", "共同持股", "关联关系")):
            return "关键关系"
        return "其他公开履历线索"

    def _basic_profile_section(self, cleaned_json: str, index: int, section_title: str) -> str:
        selected, gaps = self._rank_section_facts(cleaned_json, index)
        rows = [
            f"## {index}. {section_title}",
            "",
            f"> {FALLBACK_MARKER}",
            "",
            "本章保留二手公开信息中的基础画像事实。未取得一手原始材料时，不删除基础履历，而是在证据等级和待核验说明中标注边界。",
            "",
            "### 基础画像表",
            "",
            "| 模块 | 二手公开信息摘录 | 来源 | URL | 证据等级/边界 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in selected:
            fact = re.sub(r"\s+", " ", str(item.get("fact") or "")).replace("|", "/")[:360]
            title = re.sub(r"\s+", " ", str(item.get("source_title") or "公开来源")).replace("|", "/")[:90]
            url = str(item.get("source_url") or "").strip()
            _bonus, strength = self._fact_source_strength(item)
            rows.append(f"| {self._profile_bucket(item)} | {fact} | {title} | {url} | {strength}；二手公开信息待核验 |")
        if not selected:
            rows.append("| 基础画像 | 当前事实库未检出可写入正文的基础履历事实 | — | — | 待补充检索 |")
        timeline_items = [
            item for item in selected
            if self._profile_bucket(item) in {"教育背景", "职业路径", "早年经历"}
        ][:6]
        rows.extend([
            "",
            "### 履历时间线线索",
            "",
            "| 阶段 | 可写入正文的公开线索 | 来源 | 待核验边界 |",
            "| --- | --- | --- | --- |",
        ])
        for item in timeline_items:
            fact = re.sub(r"\s+", " ", str(item.get("fact") or "")).replace("|", "/")[:300]
            title = re.sub(r"\s+", " ", str(item.get("source_title") or "公开来源")).replace("|", "/")[:90]
            rows.append(f"| {self._profile_bucket(item)} | {fact} | {title} | 未取得一手原始记录前，仅作为二手公开履历线索 |")
        if not timeline_items:
            rows.append("| 待补充 | 当前事实库未形成可排序的教育/职业路径线索 | — | 后续补充权威简历、校方或本人公开材料 |")
        if gaps:
            rows.extend([
                "",
                "### 本章关键缺口",
                "",
                "本章仅保留与基础画像直接相关的缺口，完整缺口见第15章。",
            ])
            for gap in gaps[:3]:
                rows.append(f"- {str(gap).replace('|', '/')}")
        return "\n".join(rows)

    def _evidence_backed_section(
        self,
        cleaned_json: str,
        index: int,
        section_title: str,
        diagnostic: str = "",
    ) -> str:
        """Deterministic evidence-gap checklist for a chapter without usable analysis."""
        if index == 2:
            return self._basic_profile_section(cleaned_json, index, section_title)
        selected, gaps = self._rank_section_facts(cleaned_json, index)
        rows = [
            f"## {index}. {section_title}",
            "",
            f"> {FALLBACK_MARKER}",
            "",
            "### 本章证据状态",
            "",
            "本章未形成模型分析结论。以下仅列出已取得证据、尚缺证据及核验动作；不得据此作出关于目标人物品行、控制关系、法律责任或个人风险的确定性判断。",
            "",
        ]
        if diagnostic:
            rows.extend([
                "### 降级原因",
                "",
                diagnostic,
                "",
            ])
        rows.extend([
            "### 已有可审计证据",
            "",
            "| 证据摘录 | 来源 | URL | 证据强度 |",
            "| --- | --- | --- | --- |",
        ])
        for item in selected:
            fact = re.sub(r"\s+", " ", str(item.get("fact") or "")).replace("|", "/")[:460]
            title = re.sub(r"\s+", " ", str(item.get("source_title") or "公开来源")).replace("|", "/")[:120]
            url = str(item.get("source_url") or "").strip()
            _bonus, strength = self._fact_source_strength(item)
            rows.append(f"| {fact} | {title} | {url} | {strength} |")
        if not selected:
            rows.append("| 当前事实库未检出可直接支持本章的证据 | — | — | 待核验 |")
        else:
            rows.extend([
                "",
                "### 线索型观察",
                "",
                "以下内容基于已检索到的公开来源或关联企业层面材料形成，仅作为桌面研究线索；来源等级较低或属于间接证据时，不得作为正式尽调结论。",
            ])
            for item in selected[:5]:
                fact = re.sub(r"\s+", " ", str(item.get("fact") or "")).replace("|", "/")[:260]
                _bonus, strength = self._fact_source_strength(item)
                boundary = str(item.get("evidence_boundary") or item.get("attribution_boundary") or "")
                note = f"；边界：{boundary}" if boundary else ""
                rows.append(f"- {fact}（{strength}{note}）")
        requirements = self.outline[index - 1][1] if index <= len(self.outline) else []
        if index == 15:
            rows.extend([
                "",
                "### 集中待核验清单",
                "",
                "| 尚缺证据 / 核验事项 | 缺口原因 | 建议核验渠道 | 对报告结论影响 |",
                "| --- | --- | --- | --- |",
            ])
            deduped_gaps = []
            seen_gaps = set()
            for item in list(requirements) + gaps:
                gap = str(item).strip().replace("|", "/")
                key = re.sub(r"\s+", "", gap)[:120]
                if gap and key not in seen_gaps:
                    deduped_gaps.append(gap)
                    seen_gaps.add(key)
            for gap in deduped_gaps[:20]:
                rows.append(
                    f"| {gap} | 自动检索或清洗事实库未形成足够强的直接证据。 | 权威公示、公司原始材料、客户授权材料或交叉访谈复核。 | 未完成核验前不得形成最终尽调判断。 |"
                )
        elif gaps:
            rows.extend([
                "",
                "### 本章关键缺口",
                "",
                "本章仅列最关键缺口，完整缺口统一见第15章。",
            ])
            for gap in gaps[:3]:
                rows.append(f"- {str(gap).replace('|', '/')}")
        else:
            rows.extend([
                "",
                "### 待核验提示",
                "",
                "本章若需形成最终尽调判断，应结合第15章集中待核验清单补充人工核验。",
            ])
        rows.extend(
            [
                "",
                "### 使用边界",
                "",
                "本章仅作为自动检索底稿使用。现有证据不足以单独证明未公开的控制关系、个人信用、主观动机或法律责任；正式尽调应以权威登记、监管/司法记录、客户授权材料和交叉访谈进一步核验。",
            ]
        )
        return "\n".join(rows)

    def _usable_section_or_evidence_fallback(
        self,
        section: str,
        cleaned_json: str,
        index: int,
        section_title: str,
        emit: Callable[..., None],
        trace_emit: Any,
    ) -> str:
        section = self._repair_section_heading(section, index, section_title)
        usability = self._section_usability(section, index)
        if usability["usable"]:
            return section.strip()
        evidence_summary = self._section_evidence_summary(cleaned_json, index)
        detail = (
            f"section={index}; reasons={','.join(usability['reasons']) or 'unknown'}; "
            f"body={usability['body_len']}/{usability['min_body']}; "
            f"urls={usability['url_count']}/{usability['min_urls']}; "
            f"heading={str(usability['has_heading']).lower()}; "
            f"boundary={str(usability['has_boundary']).lower()} required={str(usability['needs_boundary']).lower()}; "
            f"noise={','.join(usability['noise_markers']) or '-'}; "
            f"selected_facts={evidence_summary['selected_facts']}; "
            f"unique_urls={evidence_summary['unique_urls']}; "
            f"structured_facts={evidence_summary['structured_facts']}; "
            f"levels={json.dumps(evidence_summary['evidence_levels'], ensure_ascii=False)}"
        )
        emit(
            trace_emit,
            "report",
            self.trace_agent,
            "章节未通过可用性检查，使用线索型证据保底章节",
            detail,
            section=section_title,
            status="fallback",
        )
        diagnostic = (
            f"章节写作结果未通过可用性检查：{','.join(usability['reasons']) or 'unknown'}；"
            f"正文长度 {usability['body_len']}/{usability['min_body']}；"
            f"显式来源 {usability['url_count']}/{usability['min_urls']}；"
            f"标题格式={'通过' if usability['has_heading'] else '未通过'}；"
            f"边界词={'通过' if usability['has_boundary'] else '缺失'}"
            f"{'；噪声=' + ','.join(usability['noise_markers']) if usability['noise_markers'] else ''}。"
        )
        return self._evidence_backed_section(cleaned_json, index, section_title, diagnostic=diagnostic)

    def _reconcile_outline_sections(
        self,
        edited: str,
        original_sections: list[str],
        cleaned_json: str,
        emit: Callable[..., None],
        trace_emit: Any,
    ) -> str:
        """Never let the optional editor remove a usable, sourced section draft."""
        edited_by_index = self._split_numbered_sections_strict(edited)
        final_sections: list[str] = []
        for index, (title, _requirements) in enumerate(self.outline, 1):
            candidate = edited_by_index.get(index, "")
            original = original_sections[index - 1] if index <= len(original_sections) else ""
            if self._section_is_usable(candidate, index):
                final_sections.append(candidate)
            elif self._section_is_usable(original, index):
                if candidate:
                    emit(
                        trace_emit,
                        "report",
                        self.trace_agent,
                        "总编结果过薄，恢复原始证据章节",
                        f"section={index}",
                        section=title,
                        status="fallback",
                    )
                final_sections.append(original)
            else:
                final_sections.append(
                    self._evidence_backed_section(
                        cleaned_json,
                        index,
                        title,
                        diagnostic="总编改写后章节仍未达到可用性检查要求，已保留可追溯证据底稿。",
                    )
                )
        return "\n\n".join(final_sections).strip()

    def _inject_affiliation_ledger(self, project: Any, report: str) -> str:
        """Append a deterministic one-hop affiliation ledger to person reports only."""
        ledger = self._person_affiliation_ledger(project)
        if not ledger:
            return report
        match = re.search(r"(?m)^##\s*9\s*[.、．]\s*[^\n]+", report or "")
        if not match:
            return report
        next_match = re.search(r"(?m)^##\s*10\s*[.、．]\s*[^\n]+", report[match.end():])
        insert_at = match.end() + (next_match.start() if next_match else len(report))
        return report[:insert_at].rstrip() + "\n\n" + ledger + "\n\n" + report[insert_at:].lstrip()

    def _person_affiliation_ledger(self, project: Any) -> str:
        groups: dict[str, dict[str, Any]] = {}
        for source in list(getattr(project, "sources", []) or []):
            meta = getattr(source, "source_metadata", {}) or {}
            context = meta.get("person_affiliation")
            if not isinstance(context, dict):
                continue
            person = re.sub(r"\s+", "", str(context.get("person_name") or "")).lower()
            target = re.sub(r"\s+", "", str(getattr(project, "target_name", "") or "")).lower()
            name = str(context.get("affiliation_name") or "").strip()
            if not target or person != target or not name:
                continue
            row = groups.setdefault(name, {"context": context, "sources": []})
            row["sources"].append(source)
        if not groups:
            return ""

        def value(patterns: list[str], text: str) -> str:
            for pattern in patterns:
                match = re.search(pattern, text, flags=re.I)
                if match:
                    return re.sub(r"\s+", " ", match.group(1)).strip(" ：:;；,，。")[:100]
            return "平台返回未识别，待核验"

        rows = [["关联企业", "主体及登记", "法人/关键人员", "与人物关系及证据", "纳入与穿透边界", "平台核验"]]
        ordered = sorted(groups.values(), key=lambda item: int(item["context"].get("selection_rank") or 999))
        for group in ordered:
            context = group["context"]
            sources = group["sources"]
            text = "\n".join(str(getattr(source, "content", "") or getattr(source, "summary", "") or "") for source in sources)
            name = str(context.get("affiliation_name") or "")
            canonical = str(context.get("canonical_company_name") or name)
            credit_code = value([r"(?:统一社会信用代码|社会信用代码)\s*[：:]?\s*([0-9A-Z]{18})"], text)
            capital = value([r"注册资本\s*[：:]?\s*([^\n；;。]{2,80})"], text)
            founded = value([r"(?:成立日期|成立时间|注册日期)\s*[：:]?\s*([^\n；;。]{2,50})"], text)
            status = value([r"(?:登记状态|经营状态)\s*[：:]?\s*([^\n；;。]{2,50})"], text)
            legal_rep = value([r"法定代表人\s*[：:]?\s*([^\n；;。]{2,50})"], text)
            people = value([r"(?:主要人员|董事长|执行董事|经理)\s*[：:]?\s*([^\n；;。]{2,100})"], text)
            relation = str(context.get("relationship_type") or "待由原始证据确认")
            evidence_hosts = list(context.get("relationship_evidence_hosts") or [])
            evidence = f"{relation}；高置信直接关联；独立来源{len(evidence_hosts)}个"
            boundary = f"{context.get('selection_reason') or '高置信直接关联入选。'} {context.get('filtering_note') or '仅一跳，不递归。'}"
            platforms = sorted({str((getattr(source, "source_metadata", {}) or {}).get("provider") or "专业平台") for source in sources})
            rows.append([
                name,
                f"法定全称：{canonical}\n统一社会信用代码：{credit_code}\n注册资本：{capital}\n成立/状态：{founded} / {status}",
                f"法定代表人：{legal_rep}\n关键人员：{people}",
                evidence,
                boundary,
                "、".join(platforms),
            ])
        def markdown_row(row: list[str]) -> str:
            return "| " + " | ".join(cell.replace("|", "/").replace("\n", "<br>") for cell in row) + " |"

        return (
            "### 关联企业受控穿透台账\n\n"
            + markdown_row(rows[0])
            + "\n| " + " | ".join("---" for _ in rows[0]) + " |\n"
            + "\n".join(markdown_row(row) for row in rows[1:])
        )

    def _edit(self, project: Any, draft: str, risk_json: str, invoke: Callable[[str, str, Any], str], clip: Callable[[str, int], str], emit: Callable[..., None], trace_emit: Any) -> str:
        emit(trace_emit, "report", self.trace_agent, "轻量总编分批润色启动", f"sections={len(self.outline)}", status="running")
        sections = self._split_numbered_sections(draft)
        # Keep editorial calls small and independent. Chapters 13-15 are
        # deterministic summaries/appendices and are preserved verbatim.
        batches = [list(range(start, min(start + 2, 13))) for start in range(1, 13, 2)]
        max_chars = max(3000, int(os.getenv("PERSON_REPORT_EDITOR_MAX_CHARS_PER_BATCH", "18000")))
        edited_batches: list[str] = []
        for batch_indexes in batches:
            batch_draft = "\n\n".join(
                sections.get(index) or self._evidence_gap_section(index, self.outline[index - 1][0])
                for index in batch_indexes
            )
            if len(batch_draft) > max_chars:
                emit(
                    trace_emit,
                    "report",
                    self.trace_agent,
                    "总编批次超过轻量编辑上限，保留章节草稿",
                    f"sections={batch_indexes[0]}-{batch_indexes[-1]}, chars={len(batch_draft)}, limit={max_chars}",
                    status="fallback",
                )
                edited_batches.append(batch_draft)
                continue
            prompt = build_editor_prompt(
                report_kind=self.report_kind,
                outline=self.outline,
                project=project,
                draft=batch_draft,
                risk_json=risk_json,
                clip=clip,
            )
            prompt += f"""

这是第 {batch_indexes[0]} 至第 {batch_indexes[-1]} 节的轻量编辑批次。只允许保留原有章节、删除重复、统一术语和修正明显语病；不得新增其他章节、不得压缩掉来源或表格、不得改写未被材料支持的结论。
若无法在当前材料中可靠完成编辑，必须原样返回本批次完整内容。
创始人报告特别规则：关联企业专业平台材料只能表述为关联企业信息，不得归因于人物个人事实。
"""
            answer = invoke(f"{self.report_kind}总编 Agent", prompt, trace_emit).strip()
            expected = set(batch_indexes)
            returned_sections = self._split_numbered_sections(answer)
            if answer and expected.issubset(returned_sections):
                edited_batches.append("\n\n".join(returned_sections[index] for index in batch_indexes))
            else:
                emit(
                    trace_emit,
                    "report",
                    self.trace_agent,
                    "总编批次未返回完整目录，保留章节草稿",
                    f"sections={batch_indexes[0]}-{batch_indexes[-1]}",
                    status="fallback",
                )
                edited_batches.append(batch_draft)
        edited_batches.extend(
            sections.get(index) or self._evidence_gap_section(index, self.outline[index - 1][0])
            for index in range(13, 16)
        )
        return "\n\n".join(edited_batches)

    def _split_numbered_sections(self, report: str) -> dict[int, str]:
        pattern = re.compile(r"(?m)^#{1,4}\s*(\d{1,2})\s*[.、．]\s*[^\n]+$")
        matches = list(pattern.finditer(report or ""))
        sections: dict[int, str] = {}
        for position, match in enumerate(matches):
            index = int(match.group(1))
            if index not in range(1, len(self.outline) + 1) or index in sections:
                continue
            end = matches[position + 1].start() if position + 1 < len(matches) else len(report)
            sections[index] = report[match.start():end].strip()
        return sections
