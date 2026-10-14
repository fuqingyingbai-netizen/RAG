import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from .report_prompts import _focused_cleaned_json, build_editor_prompt, build_section_prompt
from .report_style import REPORT_CHAPTER_HEADING_RE, REFERENCE_REPORT_STYLE, ensure_delivery_sections, normalize_report_headings, sanitize_nested_report_chapter_headings


from .industry_template import INDUSTRY_REPORT_OUTLINE

INDUSTRY_SECTION_STRUCTURES = {
    index: f"## {index}. {title}\n\n本节内容要求：" + "；".join(requirements)
    for index, (title, requirements) in enumerate(INDUSTRY_REPORT_OUTLINE, 1)
}

INDUSTRY_FEW_SHOT = """
行业桌面研究报告写作要求：
- 固定为 16 节，章节标题必须与标准目录一致；每节使用该节专属结构，不得机械套用"本章结论/事实梳理/分析判断/风险与待核验"。
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
        # Allocate by chapter relevance; distinct facts from one URL can be reused.
        used_urls: set[str] = set()
        section_packages: dict[int, str] = {}
        for index, (section_title, requirements) in enumerate(self.outline, 1):
            if index >= 15:
                section_packages[index] = cleaned_json
                section_fact_counts[index] = 0
                continue
            package = _focused_cleaned_json(
                cleaned_json,
                section_title,
                requirements,
                str(project.target_name or ""),
                "industry",

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
        emit(trace_emit, "report", self.trace_agent, "行业章节证据包已按章节分桶", f"unique_sources={len(used_urls)}, evidence_chapters=14", unique_sources=len(used_urls), status="done")

        setattr(project, "industry_section_packages", section_packages)

        # Chapter 9: when capital_market is "none", skip the model call.
        industry_scope = getattr(project, "industry_scope", {}) or {}
        capital_market = str(industry_scope.get("capital_market") or "")

        # Pre-allocate zero-evidence chapters and capital_market=none chapter.
        for index, (section_title, _requirements) in enumerate(self.outline, 1):
            if index in {15, 16}:
                continue
            fact_count = section_fact_counts.get(index, 0)
            if index == 12 and not industry_scope.get("named_companies"):
                section_packages[index] = json.dumps({"facts": []})
                sections_by_index[index] = f"## {index}. {section_title}\n\n本次未指定核心企业，未开展企业主体尽调。代表企业仅作为竞争和技术样本；如需企业尽调，请补充公司名称。"
                continue
            if index in {8, 9} and capital_market == "none":
                section_packages[index] = json.dumps({"facts": []})
                sections_by_index[index] = (
                    f"## {index}. {section_title}\n\n"
                    "本次研究范围未纳入一级融资、IPO、估值与二级市场指标。"
                    "如需补充二级市场资金热度、情绪预期、板块成交额占比、换手率、"
                    "卖方覆盖等指标，可在后续研究轮次中开启资本市场模块。"
                )
                continue
            if fact_count == 0:
                sections_by_index[index] = (
                    f"## {index}. {section_title}\n\n"
                    "本次已检索公开来源未形成可引用记录；相关核验事项见第16章。"
                )

        workers = max(1, min(5, int(os.getenv("REPORT_SECTION_MAX_WORKERS", "3"))))
        with ThreadPoolExecutor(max_workers=min(workers, len(self.outline))) as executor:
            futures = {}
            for index, (section_title, requirements) in enumerate(self.outline, 1):
                if index == 1 or index in sections_by_index:
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
        summary_title, summary_requirements = self.outline[0]
        try:
            summary = self._write_section(project, section_packages[1], risk_json, 1, summary_title,
                summary_requirements, section_fact_counts[1], invoke, clip, emit, trace_emit,
                completed_sections="\n\n".join(sections_by_index.get(i, "") for i in range(2, 15)))
            sections_by_index[1] = summary
        except Exception as exc:
            emit(trace_emit, "report", self.trace_agent, "摘要写作失败，保留核验提示", str(exc), status="fallback")
            sections_by_index[1] = "## 1. 摘要\n\n摘要生成失败；请核对以下章节及后续研究点。"
        sections = [sections_by_index[index] for index in range(1, len(self.outline) + 1) if sections_by_index.get(index)]
        draft = "\n\n".join(sections)
        if not draft.strip():
            return ""
        final = self._edit(project, draft, risk_json, section_fact_counts, invoke, clip, emit, trace_emit)
        final = ensure_delivery_sections(project, final, self.report_kind)
        emit(trace_emit, "report", self.trace_agent, "目标行业桌面研究报告完成", f"chars={len(final)}", chars=len(final), status="done")
        return final

    def _write_section(self, project: Any, cleaned_json: str, risk_json: str, index: int, section_title: str, requirements: list[str], fact_count: int, invoke: Callable[[str, str, Any], str], clip: Callable[[str, int], str], emit: Callable[..., None], trace_emit: Any, completed_sections: str = "") -> str:
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
9. 同一章节内部避免重复同一论点；同一来源的不同事实可以分别支持不同章节，摘要可以概括实体章节中已引用的事实。
10. ### 子标题总数硬性上限：rich_evidence 章节最多 12 个，稀疏章节最多 3 个。超过上限的必须合并或删除，不是列出更多子标题。
"""
        prompt += f"\n章节格式硬性要求：本章顶级标题必须且只能是 `## {index}. {section_title}`（两个#号）。正文子标题用 `###`（三个#号）。禁止将章节标题写成 `# {index}.`（一个#号）。\n"
        if not rich_evidence and index <= 14:
            prompt += "\n本章属于有限证据章节：旧章节骨架和 few-shot 仅供丰富证据章节参考，本章不适用。只写已证实事实和最多两条克制推演，不超过三个要点，不生成表格；所有待核验动作只放第16章。\n"
        if completed_sections:
            prompt += "\n已完成的实体章节（摘要仅概括这些已写结论，不新增事实）：\n" + clip(completed_sections, 30000)
        if index == 12:
            prompt += "\n按指定企业分别列示注册、股权、经营、产品、客户供应商与风险。仅根据本轮公开资料核查，未覆盖的事项写待核验；不得声称已经完成企业内部核验、访谈或现场调研。企业结论不得替代行业整体结论。\n"
        if index == 15:
            return "## 15. 信息来源\n\n来源索引由系统根据章节证据生成。"
        prompt += "\n每个关键事实和数值后必须引用本章输入的 E-证据编号；不得引用未提供的编号。无评分证据时第14章返回待核验，不能补造评分。\n"
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
1. 最终报告必须严格保留 16 节目录，标题和顺序如下：
{outline_lines}
2. 不得把每一节统一改写成"本章结论/事实梳理/分析判断/风险与待核验"四段式；每节必须保留该节自己的内容结构。
3. 第 6 节写竞争格局，第 7 节单列技术路线对比，分别引用对应证据。
4. 第 9 节二级市场情绪如缺少实时交易数据，必须明确数据缺口和建议数据源，不得编造指标。
5. 第 14 节仅在有效证据支持时评分，否则写待核验；第 15 节来源索引由系统生成；第 16 节必须按高/中/低优先级排序。
6. 对无证据内容保持克制，正文只写"待核验"，并统一沉淀到"集中式待核验清单"；不要编造市场规模、融资金额、政策原文、二级市场指标、客户或供应商数据。

章节保护规则（最高优先级，凌驾于精简规则）：
- 最终输出的 16 个 ## 顶级章节一个都不能少。即使某章只有一句"本次已检索公开来源未形成可引用记录"，也必须保留其 ## 标题。
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
