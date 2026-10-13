import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from .report_prompts import _focused_cleaned_json, build_editor_prompt, build_section_prompt
from .report_style import REPORT_CHAPTER_HEADING_RE, REFERENCE_REPORT_STYLE, ensure_delivery_sections, normalize_report_headings, sanitize_nested_report_chapter_headings


INDUSTRY_REPORT_OUTLINE = [
    ("摘要", ["报告概述", "核心研究发现", "需关注信号", "标的所属赛道竞争格局速览", "总体评估"]),
    ("行业基础定义与产业链全景", ["细分行业分类", "行业定义内涵", "代表产品及应用领域", "产业链上下游结构图谱", "各环节代表企业", "价值分配与平均毛利率水平", "产业链核心瓶颈环节"]),
    ("政策环境分析与近期政策摘录", ["国家级顶层规划", "专项行动", "行业标准体系", "补贴/准入资质", "重点省市产业规划", "园区载体", "产业基金", "监管收紧/进出口管制/技术断供风险", "近期政策文件摘编", "政策基调与监管方向"]),
    ("市场规模与增长预测", ["近3-5年历史市场规模", "CAGR", "未来5-10年分场景预测", "核心增长驱动因素", "制约因素", "行业天花板", "所处阶段：实验室/原型验证/小批量量产/规模化商用"]),
    ("行业热度形成", ["市场环境催化", "里程碑事件", "商业化进展", "终端需求变化", "政策驱动", "景气度变化趋势", "资本关注核心逻辑"]),
    ("竞争格局", ["玩家分层：头部链主/腰部/初创/海外巨头", "CR3/CR5市场集中度", "波特五力", "行业核心竞争力", "护城河", "主流技术路线横向对比", "优劣势", "落地难度", "成本", "迭代速度", "商业化成熟度"]),
    ("行业投融资全景", ["近年一级市场融资总规模", "融资事件汇总", "阶段分布", "地域融资梯队", "IPO进度", "已上市标的及估值区间", "产业并购案例及估值倍数", "产业资本战略布局"]),
    ("二级市场情绪", ["交易资金热度", "情绪预期", "行业关注度", "板块成交额占比", "换手率及历史分位", "主力买入率/主力资金净流入", "日内价格动量", "股指期货升贴水率", "期权PCR", "卖方覆盖报告数量与评级变动", "行业词频关注度"]),
    ("投资机会", ["细分赛道选择", "核心能力筛选标准", "产业整合路径", "资本配置方向", "资本市场情绪热度", "核心投资机会", "标的筛选逻辑"]),
    ("前景展望", ["未来5年趋势", "关键变量", "情景路径", "乐观/中性/谨慎假设"]),
    ("龙头公司与重点企业对标", ["代表企业选择口径", "龙头公司业务结构", "收入与盈利模式", "用户/流量/渠道优势", "技术与生态能力", "代表企业对行业格局的影响", "可借鉴的商业化路径", "对标局限与待核验"]),
    ("行业风险与不确定性", ["行业层面风险", "商业化风险", "技术迭代与替代风险", "合规法律风险", "资本与估值风险", "数据口径与证据缺口"]),
    ("行业判断与综合评估", ["行业吸引力评分", "增长确定性评分", "竞争强度评分", "商业化成熟度评分", "监管压力评分", "资本热度评分", "主要加分/扣分项", "结论边界"]),
    ("信息来源", ["信息点", "网址/来源说明", "检索工具", "可信度", "支持章节"]),
    ("后续研究点", ["待确认信息点", "下一步深度研究方向", "优先级排序", "建议数据源/访谈对象"]),
]


INDUSTRY_SECTION_STRUCTURES = {
    1: """
行业报告专属章节输出骨架：
## 1. 摘要

完整摘要必须覆盖报告概述、核心研究发现、需关注信号、标的所属赛道竞争格局速览及总体评估。不要使用"本章结论/事实梳理/分析判断/风险与待核验"四段式。
""",
    2: """
行业报告专属章节输出骨架：
## 2. 行业基础定义与产业链全景

涵盖赛道细分分类、行业定义内涵、代表产品及应用领域、产业链上下游结构图谱、各环节代表企业、价值分配与平均毛利率水平、产业链核心瓶颈环节研判。建议输出产业链表：环节｜主要功能｜代表企业｜价值占比/毛利率｜瓶颈｜标的相关性。
""",
    3: """
行业报告专属章节输出骨架：
## 3. 政策环境分析与近期政策摘录

包含国家级顶层规划、专项行动、行业标准体系、补贴准入资质、重点省市产业规划、园区载体、产业基金，以及监管收紧、进出口管制、技术断供等政策风险。必须附近期政策文件摘编和政策基调/监管方向判断。
""",
    4: """
行业报告专属章节输出骨架：
## 4. 市场规模与增长预测

包含近5年历史市场规模与CAGR、未来5-10年分场景预测、增长驱动与制约因素、行业天花板、行业所处阶段（实验室/原型验证/小批量量产/规模化商用）。建议表格：年份｜地区/口径｜规模｜增速/CAGR｜来源｜可信度｜备注。
""",
    5: """
行业报告专属章节输出骨架：
## 5. 行业热度形成

以市场环境催化（里程碑事件、市场规模与增速、商业化进展、终端需求变化）和政策驱动（国家顶层设计、监管审批突破、地方配套政策）两大维度，分析赛道热度来源、景气度变化趋势及资本关注逻辑。
""",
    6: """
行业报告专属章节输出骨架：
## 6. 竞争格局

必须覆盖玩家分层（头部链主/腰部/初创/海外巨头）、CR3/CR5集中度、波特五力、核心竞争力与护城河、主流技术路线横向对比。技术路线表建议列：路线｜代表公司｜优势｜短板｜成本/落地难度｜迭代速度｜商业化成熟度｜适用场景。
""",
    7: """
行业报告专属章节输出骨架：
## 7. 行业投融资全景

涵盖近年一级市场融资总规模、融资事件汇总、阶段分布、地域融资梯队、IPO进度、已上市标的及估值区间、产业并购案例及估值倍数、产业资本战略布局方向。融资事件表建议列：时间｜公司｜轮次/交易类型｜金额/估值｜投资方/买方｜业务方向｜来源。
""",
    8: """
行业报告专属章节输出骨架：
## 8. 二级市场情绪

从交易资金热度、情绪预期、行业关注度研判板块温度与趋势。核心指标包括板块成交额占比、换手率及历史分位、主力买入率/主力资金净流入、日内价格动量、股指期货升贴水率、期权PCR、卖方覆盖报告数量与评级变动、行业词频关注度。没有数据时写明缺口与建议数据源。
""",
    9: """
行业报告专属章节输出骨架：
## 9. 投资机会

从细分赛道选择、核心能力筛选标准、产业整合路径、资本配置方向，结合资本市场情绪热度识别核心投资机会，明确标的筛选逻辑与重点关注的标的类型。
""",
    10: """
行业报告专属章节输出骨架：
## 10. 前景展望

综合上述研究，对赛道未来5年发展趋势、关键变量、可能情景路径进行判断。建议拆为乐观/中性/谨慎情景。
""",
    11: """
行业报告专属章节输出骨架：
## 11. 龙头公司与重点企业对标

本章只做代表企业/龙头公司对标，不做目标公司主体尽调。按代表企业选择口径、业务结构、收入与盈利模式、用户/流量/渠道优势、技术与生态能力、对行业格局的影响、可借鉴商业化路径、对标局限与待核验来写。公司材料必须明确标注为样本，不得外推为行业整体事实。
""",
    12: """
行业报告专属章节输出骨架：
## 12. 行业风险与不确定性

根据检索信息识别行业层面风险、商业化风险、技术迭代与替代风险、合规法律风险、资本与估值风险、数据口径与证据缺口。建议表格：风险类别｜风险信号｜证据来源｜影响程度｜发生概率｜核验动作。不得写“标的经营风险”或把代表企业风险等同为行业结论。
""",
    13: """
行业报告专属章节输出骨架：
## 13. 行业判断与综合评估

综合研究内容，对目标行业进行总结打分。建议结构：整体评级、行业吸引力评分、增长确定性评分、竞争强度评分、商业化成熟度评分、监管压力评分、资本热度评分、主要加分/扣分项、结论边界。不得设置“目标公司/标的相对位置评分”。
""",
    14: """
行业报告专属章节输出骨架：
## 14. 信息来源

注明检索的信息来源，包括信息点、网址或来源说明、检索工具、可信度、支持章节。建议表格列：信息点｜来源标题/平台｜URL或来源说明｜数据获取工具｜可信度｜支持章节。
""",
    15: """
行业报告专属章节输出骨架：
## 15. 后续研究点

给出有待确认的信息点和下一步深度研究方向。必须按高/中/低优先级排序，并说明建议数据源/访谈对象、预期判断价值。
""",
}


INDUSTRY_FEW_SHOT = """
行业桌面研究报告写作要求：
- 固定为 15 节，章节标题必须与标准目录一致；每节使用该节专属结构，不得机械套用"本章结论/事实梳理/分析判断/风险与待核验"。
- 竞争格局速览：头部/腰部/初创/海外玩家分别列示，写清资金、客户、技术、产能或渠道差距。
- 需关注信号：市场规模口径不统一、政策强监管、核心部件外购、商业化慢、估值透支等都要进入风险提示。
- 证据不足处正文只写"待核验"，不要反复写"暂无充分公开证据"；所有缺口统一进入集中式待核验清单，不得编造市场规模、融资金额、政策原文、上市估值、客户或供应商数据。
"""

# Evidence-density-driven chapter writing (company v8 pattern):
# Chapters with fewer than this many facts receive no historical
# skeleton or few-shot examples so they stay minimal.
INDUSTRY_SPARSE_CHAPTER_MIN_FACTS = 3


class IndustryReportAgent:
    report_kind = "CDD目标行业桌面研究报告"
    trace_agent = "industry_report_agent"
    outline = INDUSTRY_REPORT_OUTLINE

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
        sections_by_index: dict[int, str] = {}
        section_fact_counts: dict[int, int] = {}
        emit(trace_emit, "report", self.trace_agent, "目标行业报告团队启动", f"sections={len(self.outline)}", status="running")
        # Allocate evidence before parallel writing.  Previously every chapter
        # ranked the entire fact library independently, so the same handful of
        # generic policy/market sources won all 15 rankings.  Chapters 1-13
        # now receive disjoint evidence packages; 14 is deterministic and 15
        # is a forward-looking verification plan.
        used_urls: set[str] = set()
        section_packages: dict[int, str] = {}
        for index, (section_title, requirements) in enumerate(self.outline, 1):
            if index >= 14:
                section_packages[index] = cleaned_json
                section_fact_counts[index] = 0
                continue
            package = _focused_cleaned_json(
                cleaned_json,
                section_title,
                requirements,
                str(project.target_name or ""),
                "industry",
                excluded_urls=used_urls,
            )
            try:
                package_facts = json.loads(package).get("facts", [])
            except (TypeError, ValueError, json.JSONDecodeError):
                package_facts = []
            used_urls.update(
                str(item.get("source_url") or "").rstrip("/")
                for item in package_facts
                if isinstance(item, dict) and str(item.get("source_url") or "").startswith(("http://", "https://"))
            )
            section_packages[index] = package
            section_fact_counts[index] = len(package_facts) if isinstance(package_facts, list) else 0
        emit(trace_emit, "report", self.trace_agent, "行业章节证据包已按章节分桶", f"unique_sources={len(used_urls)}, evidence_chapters=13", unique_sources=len(used_urls), status="done")

        # Chapter 8: when capital_market is "none", skip the model call.
        industry_scope = getattr(project, "industry_scope", {}) or {}
        capital_market = str(industry_scope.get("capital_market") or "")

        # Pre-allocate zero-evidence chapters and capital_market=none chapter.
        for index, (section_title, _requirements) in enumerate(self.outline, 1):
            if index in {14, 15}:
                continue
            fact_count = section_fact_counts.get(index, 0)
            if index == 8 and capital_market == "none":
                sections_by_index[8] = (
                    "## 8. 二级市场情绪\n\n"
                    "本项目研究边界设定为不纳入交易性二级市场指标（capital_market=none）。"
                    "如需补充二级市场资金热度、情绪预期、板块成交额占比、换手率、"
                    "卖方覆盖等指标，可在后续研究轮次中开启资本市场模块。"
                )
                continue
            if fact_count < INDUSTRY_SPARSE_CHAPTER_MIN_FACTS:
                if fact_count == 0:
                    sections_by_index[index] = (
                        f"## {index}. {section_title}\n\n"
                        "本次已检索公开来源未形成可引用记录；相关核验事项见第15章。"
                    )
                else:
                    sections_by_index[index] = (
                        f"## {index}. {section_title}\n\n"
                        f"本章仅检索到 {fact_count} 条碎片信息，不足以支撑独立分析；相关核验事项见第15章。"
                    )

        workers = max(1, min(5, int(os.getenv("REPORT_SECTION_MAX_WORKERS", "3"))))
        with ThreadPoolExecutor(max_workers=min(workers, len(self.outline))) as executor:
            futures = {}
            for index, (section_title, requirements) in enumerate(self.outline, 1):
                if index in sections_by_index:
                    continue
                fact_count = section_fact_counts.get(index, 0)
                future = executor.submit(
                    self._write_section,
                    project,
                    section_packages[index],
                    risk_json,
                    index,
                    section_title,
                    requirements,
                    fact_count,
                    invoke,
                    clip,
                    emit,
                    trace_emit,
                )
                futures[future] = (index, section_title, requirements)
            for future in as_completed(futures):
                index, section_title, requirements = futures[future]
                try:
                    section = future.result()
                except Exception as exc:
                    emit(trace_emit, "report", self.trace_agent, "章节写作失败，保留待核验章节", f"{index}. {section_title} | {exc}", section=section_title, status="fallback")
                    section = f"## {index}. {section_title}\n\n待核验。本章节需要后续补充核验：{'; '.join(requirements)}。"
                if section.strip():
                    sections_by_index[index] = section
        sections = [sections_by_index[index] for index in range(1, len(self.outline) + 1) if sections_by_index.get(index)]
        draft = "\n\n".join(sections)
        if not draft.strip():
            return ""
        final = self._edit(project, draft, risk_json, section_fact_counts, invoke, clip, emit, trace_emit)
        final = ensure_delivery_sections(project, final, self.report_kind)
        emit(trace_emit, "report", self.trace_agent, "目标行业桌面研究报告完成", f"chars={len(final)}", chars=len(final), status="done")
        return final

    def _write_section(self, project: Any, cleaned_json: str, risk_json: str, index: int, section_title: str, requirements: list[str], fact_count: int, invoke: Callable[[str, str, Any], str], clip: Callable[[str, int], str], emit: Callable[..., None], trace_emit: Any) -> str:
        emit(trace_emit, "report", self.trace_agent, "章节写作启动", f"{index}/{len(self.outline)} {section_title}", section=section_title, status="running")
        # Evidence-density-driven chapter writing (company v8 pattern):
        #   fact_count >= 3 -> full section structure + few-shot
        #   fact_count <  3 -> minimal: title + max 3 points
        rich_evidence = fact_count >= INDUSTRY_SPARSE_CHAPTER_MIN_FACTS
        if rich_evidence:
            few_shot = INDUSTRY_FEW_SHOT
            section_structure = INDUSTRY_SECTION_STRUCTURES.get(index, "")
        else:
            few_shot = ""
            section_structure = (
                f"只保留 `## {index}. {section_title}` 标题。"
                "按已有证据写最多三个要点；仅在有两条以上可比较事实时使用表格。"
                "不要为了覆盖任务书增加二级标题、三级标题或本章待核验清单。"
            )
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
            few_shot=few_shot,
            section_structure=section_structure,
        )
        prompt += """
行业证据边界（强制执行）：
1. 仅可用清洗事实中已提供的材料；不得凭行业常识补数据、补融资额、补市场规模或补政策原文。
2. 搜索未命中、页面未提及、或数据口径不可比，只能写"在本次已检索公开来源中未形成可引用记录，待付费数据库/官方统计库核验"；严禁写"没有""不存在""无数据"。
3. 不同子赛道的市场规模、份额、增速和估值口径不得相加；无法比较时必须分别呈现，并移至待核验。
4. 关键数值必须同时保留统计口径、地域、数据期和来源；缺任一项时不得用于评分或结论。
5. 观点、评论和媒体推测必须标为来源观点，不能改写为已确认事实。
6. 本章只有少量证据时，可在证据明确支持的范围内作一至两条克制推演，但必须使用"基于现有证据判断/可能/仍需核验"等边界词。
7. 不要为了完成任务书逐项填充无证据内容。没有可写内容的子项直接省略；表格只有在存在至少两条可比较事实时才使用。
8. 每个 ### 子标题下的正文必须有对应的清洗事实来源；禁止为没有证据的子标题编造正文。
9. 禁止在不同 ### 子标题之间重复同一论点或同一来源；每个事实只用一次。
10. ### 子标题总数硬性上限：rich_evidence 章节最多 12 个，稀疏章节最多 3 个。超过上限的必须合并或删除，不是列出更多子标题。
"""
        prompt += f"\n章节格式硬性要求：本章顶级标题必须且只能是 `## {index}. {section_title}`（两个#号）。正文子标题用 `###`（三个#号）。禁止将章节标题写成 `# {index}.`（一个#号）。\n"
        if not rich_evidence and index <= 13:
            prompt += "\n本章属于有限证据章节：旧章节骨架和 few-shot 仅供丰富证据章节参考，本章不适用。只写已证实事实和最多两条克制推演，不超过三个要点，不生成表格；所有待核验动作只放第15章。\n"
        answer = invoke(f"{self.report_kind}章节 Agent - {section_title}", prompt, trace_emit)
        if answer.strip():
            # Normalise heading levels: some models promote ## N. to # N.
            # despite explicit instructions.  Fix it so the editor and
            # quality gate see the expected structure.
            normalized = re.sub(
                r"^# (\d{1,2})\. ",
                r"## \1. ",
                answer.strip(),
                flags=re.MULTILINE,
            )
            emit(trace_emit, "report", self.trace_agent, "章节写作完成", section_title, section=section_title, status="done")
            return normalized
        return f"## {index}. {section_title}\n\n待核验。本章节需要后续补充核验：{'; '.join(requirements)}。"

    def _edit(self, project: Any, draft: str, risk_json: str, section_fact_counts: dict[int, int], invoke: Callable[[str, str, Any], str], clip: Callable[[str, int], str], emit: Callable[..., None], trace_emit: Any) -> str:
        emit(trace_emit, "report", self.trace_agent, "总编润色启动", f"sections={len(self.outline)}", status="running")
        prompt = build_editor_prompt(
            report_kind=self.report_kind,
            outline=self.outline,
            project=project,
            draft=draft,
            risk_json=risk_json,
            clip=clip,
        )
        # Count how many chapters are truly substantive (have significant body text
        # beyond a one-line placeholder).  Used below to guide the editor.
        sparse_chapter_nums = sorted(
            idx for idx, fc in section_fact_counts.items() if fc < INDUSTRY_SPARSE_CHAPTER_MIN_FACTS
        )
        outline_lines = chr(10).join(f"{idx}. {title}" for idx, (title, _) in enumerate(self.outline, 1))
        sparse_hint = ""
        if sparse_chapter_nums:
            sparse_labels = ", ".join(f"第{idx}章" for idx in sparse_chapter_nums)
            sparse_hint = (
                "以下章节证据稀疏（fact_count < " + str(INDUSTRY_SPARSE_CHAPTER_MIN_FACTS) + "），"
                "正文应简短（最多3个要点、不用表格），但 ## 顶级标题必须保留：" + sparse_labels + "\n"
            )
        prompt += f"""

行业报告专属总编要求：
1. 最终报告必须严格保留 15 节目录，标题和顺序如下：
{outline_lines}
2. 不得把每一节统一改写成"本章结论/事实梳理/分析判断/风险与待核验"四段式；每节必须保留该节自己的内容结构。
3. 第 6 节必须同时覆盖竞争格局与主流技术路线横向对比；不得再单独新增"技术路线对比"章节。
4. 第 8 节二级市场情绪如缺少实时交易数据，必须明确数据缺口和建议数据源，不得编造指标。
5. 第 13 节必须给出评分或等级；第 14 节必须列信息点、来源/URL、工具、可信度、支持章节；第 15 节必须按高/中/低优先级排序。
6. 对无证据内容保持克制，正文只写"待核验"，并统一沉淀到"集中式待核验清单"；不要编造市场规模、融资金额、政策原文、二级市场指标、客户或供应商数据。

章节保护规则（最高优先级，凌驾于精简规则）：
- 最终输出的 15 个 ## 顶级章节一个都不能少。即使某章只有一句"本次已检索公开来源未形成可引用记录"，也必须保留其 ## 标题。
- 精简规则只能用于删除章节内部的 ### 子标题和空洞正文段落，绝对不能删除整个 ## 顶级章节。
- 如果草稿中某章缺失，必须补回其 ## 标题和一句占位说明；不得直接跳过该编号。
{sparse_hint}
"""
        answer = invoke(f"{self.report_kind}总编 Agent", prompt, trace_emit)
        edited = answer.strip()
        if not edited:
            return draft
        expected = {idx: title for idx, (title, _) in enumerate(self.outline, 1)}
        edited = normalize_report_headings(edited, expected)
        edited = sanitize_nested_report_chapter_headings(edited, expected)
        present = {int(match.group(1)) for match in REPORT_CHAPTER_HEADING_RE.finditer(edited or "")}
        missing = [idx for idx in range(1, len(self.outline) + 1) if idx not in present]
        if missing:
            emit(
                trace_emit,
                "report",
                self.trace_agent,
                "总编输出缺章，回退分章节草稿",
                f"missing={missing}",
                status="fallback",
            )
            return draft
        return edited
