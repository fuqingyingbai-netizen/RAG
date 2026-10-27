import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from .report_prompts import _focused_cleaned_json, build_editor_prompt, build_section_prompt
from .report_style import REPORT_CHAPTER_HEADING_RE, REFERENCE_REPORT_STYLE, ensure_delivery_sections, normalize_report_headings, sanitize_nested_report_chapter_headings


from .industry_template import INDUSTRY_REPORT_OUTLINE
try:
    from ..industry_research import package_risk_evidence, bounded_package, mark_unverified_numbers, summary_package, summary_length, claim_semantic_issues, risk_fact_text
except ImportError:
    from industry_research import package_risk_evidence, bounded_package, mark_unverified_numbers, summary_package, summary_length, claim_semantic_issues, risk_fact_text

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
- 第14章须区分模型风险分、指标证据覆盖和评分可信度；评分尚未人工校准，原文引用通过不能表述为评分可靠，不能虚构可信度概率。
- 数值字段完整或原文可定位不能写成来源真实性已验证、证据充分或高确定性；同一行不能同时标已验证和待核验。来源观点必须明确归属。
- 企业数量不能推出市场集中度；跨期或未授权的增速不能直接比较。发布与施行日期分开，处罚上限绑定违法类型；律所及企业解读不得称为政策原文。
- 上市企业或供应商样本只能列为样本观察，来源自己称“行业平均”也不能据此外推。占比不能推出进入壁垒，缺少执行材料不能推出政策执行效力存疑。
- 只列有来源的预测，不自建未经计算验证的金额或区间；“待核验”不能授权新增预测值。不得将本章选证范围扩大为“所有清洗事实/全部公开资料均无”。
- 同比、环比和复合年增长率不得互换；与GDP或其他增速比较须有同期间可比基准。原始披露时点不得改成报告截止日。
- 词元/token计费只是适用业务的模式观察，不能变成全行业投资硬门槛或据此排除离线SDK、定制算法。宏观增长不能证明投入错配、并购整合、采购刚性或投资确定性。
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
        setattr(project, 'industry_report_degradations', [])
        section_fact_counts: dict[int, int] = {}
        emit(trace_emit, "report", self.trace_agent, "目标行业报告团队启动", f"sections={len(self.outline)}", status="running")
        # Allocate by chapter relevance; distinct facts from one URL can be reused.
        used_urls: set[str] = set()
        section_packages: dict[int, str] = {}
        payload = json.loads(cleaned_json)
        project.industry_statement_mode = bool(payload.get('fact_contract_version'))
        project.industry_statement_plans = {}
        project.industry_analysis_repair_budget = {'requests_used': 0, 'chapters': []}
        risk = json.loads(risk_json)
        for index, (section_title, requirements) in enumerate(self.outline, 1):
            if index >= 15:
                package = _focused_cleaned_json(cleaned_json, section_title, requirements,
                                                str(project.target_name or ''), 'industry') if index == 16 else '{"facts": []}'
                section_packages[index] = bounded_package(json.loads(package))
                section_fact_counts[index] = len(json.loads(section_packages[index])['facts'])
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
            package, _ = package_risk_evidence(json.loads(package), payload, risk, include_all=index in {1, 13, 14})
            from industry_reasoning import prioritize_questions
            package = prioritize_questions(package, index)
            section_packages[index] = bounded_package(package)
            section_fact_counts[index] = len(json.loads(section_packages[index])['facts'])
        emit(trace_emit, "report", self.trace_agent, "行业章节证据包已按章节分桶", f"unique_sources={len(used_urls)}, evidence_chapters=14", unique_sources=len(used_urls), status="done")

        setattr(project, "industry_section_packages", section_packages)

        # Chapter 9: when capital_market is "none", skip the model call.
        industry_scope = getattr(project, "industry_scope", {}) or {}
        capital_market = str(industry_scope.get("capital_market") or "")
        from industry_delivery import risk_status_section, tasks_section, finalize_synthesis
        sections_by_index[14] = risk_status_section(risk, industry_scope, self.outline[13][0])
        sections_by_index[16] = tasks_section([], self.outline[15][0])

        # Pre-allocate zero-evidence chapters and capital_market=none chapter.
        for index, (section_title, _requirements) in enumerate(self.outline, 1):
            if index in {14, 15, 16}:
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
                    "本章保留的原文证据尚不足以形成可引用结论；相关核验事项见第16章。"
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
                    package = json.loads(section_packages[index])
                    section = mark_unverified_numbers(self._fallback_section(package, index, section_title), package.get('facts', []))
                    project.industry_report_degradations.append({'chapter': index, 'message': f'第{index}章写作异常，保留来源事实摘录；需人工复核。'})
                if section.strip():
                    sections_by_index[index] = section
        if project.industry_statement_mode:
            self._write_synthesis(project, payload, section_packages, sections_by_index, industry_scope, invoke, emit, trace_emit)
            self._review_statement_claims(project, payload, section_packages, sections_by_index, invoke, emit, trace_emit)
        summary_title, summary_requirements = self.outline[0]
        # Only cited, budgeted cards enter the summary and its chapter digest.
        summary_cards = summary_package(section_packages, sections_by_index, industry_scope)
        section_packages[1] = json.dumps(summary_cards, ensure_ascii=False)
        section_fact_counts[1] = len(json.loads(section_packages[1])['facts'])
        summary_digest = '\n'.join(f'{f.get("module", "")}：{f.get("fact", "")[:500]} [{f["evidence_id"]}]'
                                   for f in summary_cards['facts'])
        try:
            summary = self._write_section(project, section_packages[1], risk_json, 1, summary_title,
                summary_requirements, section_fact_counts[1], invoke, clip, emit, trace_emit,
                completed_sections=summary_digest)
            sections_by_index[1] = summary
        except Exception as exc:
            emit(trace_emit, "report", self.trace_agent, "摘要写作失败，保留核验提示", str(exc), status="fallback")
            sections_by_index[1] = mark_unverified_numbers(self._fallback_section(summary_cards, 1, summary_title), summary_cards['facts'])
            project.industry_report_degradations.append({'chapter': 1, 'message': '摘要写作异常，保留主要事实摘录；综合判断需人工复核。'})
        sections = [sections_by_index[index] for index in range(1, len(self.outline) + 1) if sections_by_index.get(index)]
        draft = "\n\n".join(sections)
        if not draft.strip():
            return ""
        final = self._edit(project, draft, risk_json, section_fact_counts, invoke, clip, emit, trace_emit)
        final, tasks = finalize_synthesis(final, payload, risk, project.industry_report_degradations, industry_scope,
                                         getattr(project, 'industry_statement_plans', {}))
        project.industry_verification_tasks = tasks
        final = ensure_delivery_sections(project, final, self.report_kind)
        from .industry_template import validate_report_template
        validation = validate_report_template(final, getattr(project, 'industry_statement_plans', {}), industry_scope)
        if not validation['structure_passed']:
            raise ValueError('industry_report_template_mismatch: ' + ','.join(validation['errors']))
        emit(trace_emit, "report", self.trace_agent, "目标行业桌面研究报告完成", f"chars={len(final)}", chars=len(final), status="done")
        return final

    def _write_section(self, project: Any, cleaned_json: str, risk_json: str, index: int, section_title: str, requirements: list[str], fact_count: int, invoke: Callable[[str, str, Any], str], clip: Callable[[str, int], str], emit: Callable[..., None], trace_emit: Any, completed_sections: str = "") -> str:
        package = json.loads(cleaned_json)
        if getattr(project, 'industry_statement_mode', False) or any(f.get('fact_contract') for f in package.get('facts', [])):
            return self._write_statement_section(project, package, index, section_title, invoke, emit, trace_emit)
        emit(trace_emit, "report", self.trace_agent, "章节写作启动", f"{index}/{len(self.outline)} {section_title}", section=section_title, status="running")
        # Evidence-density-driven chapter writing (company v8 pattern):
        #   fact_count >= 3 -> full section structure + few-shot
        #   fact_count <  3 -> minimal: title + max 3 points
        rich_evidence = fact_count >= INDUSTRY_SPARSE_CHAPTER_MIN_FACTS
        if index == 1:
            few_shot = ''
            section_structure = (f'只输出 `## 1. {section_title}` 标题、研究范围、3至5项主要发现和证据限制。'
                                 '使用短段落或要点，目标450字以内，不使用表格或子标题。')
        elif index == 16:
            few_shot = ''
            section_structure = (f'只输出 `## {index}. {section_title}`。逐项列待完成问题、原始来源核对动作、所需资料和完成条件，'
                                 '引用对应证据编号。不得复制市场规模摘录或综合评估，不编造已经完成的访谈、补搜或采购。')
        elif rich_evidence:
            few_shot = INDUSTRY_FEW_SHOT
            section_structure = INDUSTRY_SECTION_STRUCTURES.get(index, "")
        else:
            few_shot = ""
            section_structure = (
                f"只保留 `## {index}. {section_title}` 标题。"
                "按已有证据写最多三个要点；仅在有两条以上可比较事实时使用表格。"
                "不要为了覆盖任务书增加二级标题、三级标题或本章待核验清单。"
            )
        package = json.loads(cleaned_json)
        _, scoped_risk = package_risk_evidence(package, package, json.loads(risk_json), include_all=index in {1, 13, 14})
        prompt = build_section_prompt(
            report_kind=self.report_kind,
            outline=self.outline,
            project=project,
            cleaned_json=cleaned_json,
            risk_json=json.dumps(scoped_risk, ensure_ascii=False),
            index=index,
            section_title=section_title,
            requirements=requirements,
            clip=clip,
            few_shot=few_shot,
            section_structure=section_structure,
            evidence_preselected=True,
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
10. 预测、预估、情景或目标数值须在数值所在分句明确标记，不能当成已实现统计。多张证据卡或同一发布方不同页面不等于独立来源，不得据此声称多源一致或交叉印证。
11. ### 子标题总数硬性上限：rich_evidence 章节最多 12 个，稀疏章节最多 3 个。超过上限的必须合并或删除，不是列出更多子标题。
12. 同比、环比、CAGR及其统计区间分别保留；单年同比不能改写为跨年复合增速，不因数值一致而视为同一指标。
13. 一种计费模式或专家观点不得升级为全行业投资硬门槛；没有覆盖的商业模式、赛道或企业不能据此判为不合格。
14. 企业数量占比不代表投入错配；市场增长不证明已进入规模化商用、采购刚性或整合加速。分析假设必须与已证实事实分开，不得宣称降低投资风险或高确定性。
15. 历史统计、来源发布日期与报告截止日分别记录；没有新披露不能将旧累计数量写成截至当前。
"""
        prompt += f"\n章节格式硬性要求：本章顶级标题必须且只能是 `## {index}. {section_title}`（两个#号）。正文子标题用 `###`（三个#号）。禁止将章节标题写成 `# {index}.`（一个#号）。\n"
        if not rich_evidence and index <= 14:
            prompt += "\n本章属于有限证据章节：旧章节骨架和 few-shot 仅供丰富证据章节参考，本章不适用。只写已证实事实和最多两条克制推演，不超过三个要点，不生成表格；所有待核验动作只放第16章。\n"
        if completed_sections:
            prompt += "\n实体章节已引用的事实摘要（编号均属于本章证据包）：\n" + completed_sections
        if index == 1:
            prompt += '\n摘要限600字：概括研究范围、3至5项主要发现及证据限制。不要复制其他章节标题、来源索引、长表格或逐条重复事实。每项发现只引用本章提供的编号。不能把摘要证据包条数当作报告总来源数或全库事实数。\n'
        if index == 12:
            prompt += "\n按指定企业分别列示注册、股权、经营、产品、客户供应商与风险。仅根据本轮公开资料核查，未覆盖的事项写待核验；不得声称已经完成企业内部核验、访谈或现场调研。企业结论不得替代行业整体结论。\n"
        if (getattr(project, 'industry_scope', {}) or {}).get('capital_market') == 'none':
            prompt += '\n资本市场模块未启用：不要将投融资、估值或二级市场缺失列为本次研究缺口、风险或必做补采任务。\n'
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
            normalized = self._validate_section(normalized, package, index, section_title, invoke, emit, trace_emit,
                                                getattr(project, 'industry_report_degradations', []))
            emit(trace_emit, "report", self.trace_agent, "章节写作完成", section_title, section=section_title, status="done")
            return normalized
        emit(trace_emit, 'report', self.trace_agent, '章节模型未返回正文，保留来源事实摘录', f'chapter={index}', status='fallback')
        getattr(project, 'industry_report_degradations', []).append({'chapter': index, 'message': f'第{index}章模型未返回有效正文，使用来源事实摘录；建议复核综合判断。'})
        return mark_unverified_numbers(self._fallback_section(package, index, section_title), package.get('facts', []))

    def _write_statement_section(self, project, package, index, title, invoke, emit, trace_emit):
        """Preserve source statements and validate separately authored analysis."""
        from industry_fact_contracts import chapter_admitted, plan_prompt, parse_chapter_response, validate_analyses, render_plan, PLAN_VERSION
        facts = [f for f in package.get('facts', []) if f.get('fact_contract') and chapter_admitted(f, index)]
        if index == 1:
            facts = [f for f in facts if f.get('summary_lineage')]
        admitted = {**package, 'facts': facts}
        ids, failures, proposed_analyses = [], [], []
        if index == 1 or not facts:
            ids = [f['evidence_id'] for f in facts[:5]]
        else:
            prompt = plan_prompt(admitted, index)
            for attempt in range(2):
                try:
                    raw = invoke(f'{self.report_kind}章节' + ('修复' if attempt else '编排') + f' Agent - {title}',
                                 prompt + ('\n上次计划格式或编号无效，请仅返回规定JSON；本次修复最多3段分析，每段60至180字，未回答的问题保留缺口。' if attempt else ''), trace_emit)
                    ids, proposed_analyses = parse_chapter_response(raw, admitted, index)
                    break
                except Exception as exc:
                    failures.append(type(exc).__name__)
            else:
                ids = [f['evidence_id'] for f in facts[:8]]
                getattr(project, 'industry_report_degradations', []).append({'chapter': index,
                    'message': f'第{index}章编排计划未通过，保留已准入陈述的顺序；综合分析待复核。',
                    'initial_validation_reasons': ['invalid_statement_plan'], 'attempt_failures': failures})
        model_ids = list(ids)
        prelim_analyses, _ = validate_analyses(proposed_analyses, admitted, index, model_ids)
        if index != 1:
            from industry_analysis import complete_plan
            ids = complete_plan(admitted, index, ids, prelim_analyses)
        analyses, analysis_rejections = validate_analyses(proposed_analyses, admitted, index, ids)
        from industry_analysis_repair import repair_analyses
        analyses, analysis_rejections, analysis_repair = repair_analyses(
            project, admitted, index, ids, analyses, analysis_rejections, invoke, emit, trace_emit,
            f'{self.report_kind}章节分析局部修复 Agent - {title}')
        from industry_reasoning import question_ledger
        from industry_reader import analysis_balance
        ledger = question_ledger(admitted, index, ids, analyses)
        coverage = ledger['questions']
        plans = getattr(project, 'industry_statement_plans', None)
        if plans is not None:
            plans[index] = {'version': PLAN_VERSION, 'evidence_ids': ids, 'model_attempts': (len(failures) if len(failures) == 2 else len(failures)+1) if index != 1 and facts else 0,
                            'fallback': len(failures) == 2, 'semantic_status': 'not_evaluated',
                            'analysis_method': 'evidence_bounded_model_analysis' if analyses else 'deterministic_evidence_operations',
                            'analysis_claims': analyses, 'analysis_rejections': analysis_rejections,
                            'analysis_repair': analysis_repair,
                            'reader_balance': analysis_balance(admitted, index, ids, analyses),
                            'selection_alignment': {'model_evidence_ids': model_ids,
                                'final_evidence_ids': list(ids),
                                'rule_checked_premise_ids': list(dict.fromkeys(eid for c in prelim_analyses for eid in c['evidence_ids'])),
                                'premise_ids_not_retained': list(dict.fromkeys(eid for c in prelim_analyses for eid in c['evidence_ids'] if eid not in ids))},
                            'question_ledger': ledger,
                            'content_coverage': coverage}
        # This mode produces auditable source statements, not a certified analyst
        # synthesis. Keep that limitation visible in delivery state and tasks.
        if index not in {1, 15, 16}:
            from industry_fact_contracts import chapter_coverage
            getattr(project, 'industry_report_degradations', []).append({'chapter': index,
                'message': f'第{index}章已完成' + ('受证据约束的分析' if analyses else '来源陈述编排；尚缺有效模型分析') + '，结论尚待语义复核。', 'review_type': 'statement_synthesis_review',
                'evidence_ids': list(ids), 'content_coverage': coverage})
        emit(trace_emit, 'report', self.trace_agent, '章节陈述编排完成', f'chapter={index}; statements={len(ids)}', status='done')
        return render_plan(admitted, index, title, ids, analyses=analyses, ledger=ledger)

    def _write_synthesis(self, project, payload, packages, sections, scope, invoke, emit, trace_emit):
        """One bounded cross-chapter synthesis, never a rewrite of risk scores."""
        from industry_briefing import synthesis_package, bind_plan, reuse_chapter_judgments
        from industry_fact_contracts import plan_prompt, parse_chapter_response, validate_analyses, render_plan, PLAN_VERSION
        from industry_reasoning import question_ledger
        package = synthesis_package(packages, sections, scope, project.industry_statement_plans)
        packages[14] = json.dumps(package, ensure_ascii=False)
        ids = [f['evidence_id'] for f in package['facts']]
        claims, rejected, error, attempts = [], [], '', 0
        if ids:
            emit(trace_emit, 'report', self.trace_agent, '综合已完成章节，形成阶段性判断', f'facts={len(ids)}', status='running')
            try:
                attempts = 1
                raw = invoke('行业阶段性综合 Agent', plan_prompt(package, 14), trace_emit)
                ids, proposed = parse_chapter_response(raw, package, 14)
                claims, rejected = validate_analyses(proposed, package, 14, ids)
            except Exception as exc:
                error = type(exc).__name__
        reused = False
        if not any(c.get('analysis_role') == 'draft_claim' for c in claims):
            fallback = reuse_chapter_judgments(project.industry_statement_plans, package)
            if fallback:
                claims = fallback
                ids = [f['evidence_id'] for f in package['facts']]
                reused = True
        ledger = question_ledger(package, 14, ids, claims, rejected)
        plan = {'version': PLAN_VERSION, 'evidence_ids': ids, 'analysis_claims': claims,
            'analysis_rejections': rejected, 'model_attempts': attempts, 'fallback': not bool(claims),
            'analysis_method': 'chapter_analysis_reuse' if reused else 'cross_chapter_synthesis' if claims else 'synthesis_not_completed',
            'question_ledger': ledger, 'content_coverage': ledger['questions'], 'error_type': error}
        bind_plan(plan, package)
        project.industry_statement_plans[14] = plan
        project.industry_report_degradations.append({'chapter': 14, 'review_type': 'statement_synthesis_review',
            'message': '阶段性综合判断待人工复核。' if claims else '阶段性综合未形成有效分析，保留原章节依据和风险状态。',
            'evidence_ids': ids, 'content_coverage': ledger['questions'], 'error_type': error})
        sections[14] = render_plan(package, 14, self.outline[13][0], ids, claims, ledger)

    def _review_statement_claims(self, project, payload, packages, sections, invoke, emit, trace_emit):
        """One bounded second pass; reject claims without erasing valid sources."""
        from industry_reasoning import claim_id, question_ledger, run_support_review
        from industry_fact_contracts import render_plan
        plans = getattr(project, 'industry_statement_plans', {})
        claims = []
        for chapter in [14, 13, 10, 7, 4, 6, 11, 3, 2, 5]:
            plan = plans.get(chapter, {})
            for claim in plan.get('analysis_claims', []):
                claims.append({**claim, 'chapter': chapter, 'claim_id': claim_id(claim, chapter)})
        if os.getenv('INDUSTRY_CLAIM_REVIEW_ENABLED', 'true').lower() in {'0', 'false', 'no', 'off'}:
            review = {'attempts': 0, 'reviews': {}, 'status': 'disabled', 'human_review_required': True}
        else:
            review = run_support_review(claims, payload.get('facts', []),
                lambda prompt: invoke('行业结论支持复核 Agent', prompt, trace_emit))
        project.industry_claim_support_review = review
        for chapter, plan in plans.items():
            kept = []
            for claim in plan.get('analysis_claims', []):
                verdict = review.get('reviews', {}).get(claim_id(claim, chapter), {'status': 'not_evaluated'})
                checked = {**claim, 'support_review': verdict}
                if verdict['status'] in {'partial', 'unsupported', 'contradicted'}:
                    plan['analysis_rejections'].append({'question': claim['question'], 'issues': ['claim_support_'+verdict['status']],
                        'original_analysis': dict(claim), 'support_review': verdict})
                else:
                    kept.append(checked)
            plan['analysis_claims'] = kept
            package = json.loads(packages[chapter])
            plan['question_ledger'] = question_ledger(package, chapter, plan['evidence_ids'], kept, plan['analysis_rejections'])
            plan['content_coverage'] = plan['question_ledger']['questions']
            plan['analysis_method'] = 'evidence_bounded_model_analysis' if kept else 'deterministic_evidence_operations'
            from industry_reader import analysis_balance
            plan['reader_balance'] = analysis_balance(package, chapter, plan['evidence_ids'], kept)
            sections[chapter] = render_plan(package, chapter, self.outline[chapter-1][0], plan['evidence_ids'], kept, plan['question_ledger'])
            for note in project.industry_report_degradations:
                if note.get('chapter') == chapter and note.get('review_type') == 'statement_synthesis_review':
                    note['content_coverage'] = plan['content_coverage']
                    note['analysis_rejections'] = plan['analysis_rejections']
                    if any(r.get('support_review') for r in plan['analysis_rejections']):
                        note['message'] = f'第{chapter}章部分判断未通过结论支持复核，已保留有效来源与可保留分析；需核对适用范围和推理。'
        emit(trace_emit, 'report', self.trace_agent, '关键分析支持关系复核完成',
            f'claims={len(claims)}; reviewed={len(review.get("reviews", {}))}; attempts={review["attempts"]}', status='done')

    def _fallback_section(self, package, index, title):
        if any(f.get('fact_contract') for f in package.get('facts', [])):
            from industry_fact_contracts import chapter_admitted, render_plan
            ids = [f['evidence_id'] for f in package['facts'] if f.get('fact_contract') and chapter_admitted(f, index)
                   and (index != 1 or f.get('summary_lineage'))][:8]
            return render_plan(package, index, title, ids)
        facts, seen = [], set()
        for fact in package.get('facts', []):
            if fact.get('eligible_for_report') is False:
                continue
            key = re.sub(r'\s+', '', risk_fact_text(fact))
            if not key or key in seen or not fact.get('evidence_id'):
                continue
            seen.add(key)
            facts.append(fact)
        if index == 16:
            rows = []
            for fact in facts[:8]:
                context = fact.get('numeric_context') or {}
                topic = str(context.get('metric') or fact.get('module') or '来源判断')
                rows.append(f'- 核对{topic}的原始披露、时间与地域口径，确认适用范围及缺失字段；取得证据前保留未知。 [{fact["evidence_id"]}]({fact.get("source_url", "")})')
            return f'## {index}. {title}\n\n' + ('\n\n'.join(dict.fromkeys(rows)) or '待核验：补充市场口径、竞争指标、技术测试与商业化披露，并为每项任务确认来源、责任人和完成条件。')
        if index == 5:
            facts = [f for f in facts if re.search(r'发布|开源|政策|推出|发布会|热度|关注|搜索指数', risk_fact_text(f))][:4]
        if index == 11:
            facts = [f for f in facts if (f.get('numeric_context') or {}).get('is_forecast') is True][:4]
        if index == 7:
            from industry_grounding import passage_tasks
            facts = [f for f in facts if any(t.startswith('技术') for t in passage_tasks(f))]
        if index == 1:
            # A synthesis fallback remains short, traceable and explicit about its limits.
            facts = facts[:5]
        heading = f'## {index}. {title}\n\n'
        body = '以下为已完成章节的主要事实摘要；模型摘要未通过校验，综合判断需人工复核。\n\n' if index == 1 else ''
        body += {5: '热度成因和事件时间线尚待核验；以下仅为来源事件摘录，不推定传播机制。\n\n',
                 7: '本章尚未形成同条件技术路线比较；仅列保留的测试条件、性能或成本材料，样本不代表行业整体。需补核的测试条件、性能、单位成本与适配问题见第16章。\n\n',
                 11: '尚未形成情景对照与触发条件；以下仅列来源预测，不作为确定性展望。\n\n',
                 14: '综合评估尚待完成；以下为可追溯背景，不能替代风险未知项和证据缺口的复核。\n\n'}.get(index, '')
        for fact in facts:
            # Render the single authorized metric with its nature in the same
            # clause. Raw multi-metric quotes remain in the audit library.
            text = risk_fact_text(fact)
            from industry_grounding import sample_boundary, complete_excerpt
            boundary = sample_boundary(fact)
            if boundary:
                text = f'样本观察（{boundary}）：' + text
            if len(text) > 700:
                text = complete_excerpt(text,700) or '原文较长，具体内容待核验。'
            line = f'- {text} [{fact["evidence_id"]}]({fact.get("source_url", "")})'
            line = mark_unverified_numbers(line, [fact])
            if claim_semantic_issues(line, [fact]):
                line = f'- 该来源的数值或综合表述需复核，暂不转述其判断。 [{fact["evidence_id"]}]({fact.get("source_url", "")})'
            candidate = body + line + '\n\n'
            if index == 1 and summary_length(heading + candidate) > 600:
                continue
            body = candidate
        return heading + (body.strip() or '待核验。本次证据不足，相关事项见第16章。')

    def _edit(self, project: Any, draft: str, risk_json: str, section_fact_counts: dict[int, int], invoke: Callable[[str, str, Any], str], clip: Callable[[str, int], str], emit: Callable[..., None], trace_emit: Any) -> str:
        # Chapters have already been audited independently. A whole-report model
        # rewrite both loses citations and duplicates expensive output tokens.
        expected = {idx: title for idx, (title, _) in enumerate(self.outline, 1)}
        emit(trace_emit, 'report', self.trace_agent, '行业报告分章校验完成，执行目录合并', 'sections=16', status='done')
        return sanitize_nested_report_chapter_headings(normalize_report_headings(draft, expected), expected)

    @staticmethod
    def _normalize_section_format(section):
        section = section.strip()
        fence = re.fullmatch(r'```(?:markdown|md)?\s*\n(.*?)\n```', section, re.S | re.I)
        if fence:
            section = fence[1].strip()
        return re.sub(r'^# (\d{1,2})\. ', r'## \1. ', section, flags=re.M)

    @staticmethod
    def _section_validation_reasons(section, allowed, index, title):
        ids = set(re.findall(r'\bE-[A-Z0-9-]{6,}\b', section, re.I))
        reasons = []
        if (section.splitlines() or [''])[0].strip() != f'## {index}. {title}':
            reasons.append('wrong_heading')
        if len(re.findall(r'(?m)^##\s+\d+[.、．]', section)) > 1:
            reasons.append('duplicate_chapter_heading')
        if not ids & allowed:
            reasons.append('missing_citation')
        if ids - allowed:
            reasons.append('invalid_citation')
        if index == 1 and summary_length(section) > 600:
            reasons.append('summary_too_long')
        if index != 1 and re.search(r'(?m)^###\s*(?:摘要|行业基础定义与产业链全景)\s*$',section):
            reasons.append('section_task_conflict')
        return reasons

    def _validate_section(self, section, package, index, title, invoke, emit, trace_emit, degradations=None):
        facts = package.get('facts', [])
        allowed = {f.get('evidence_id') for f in facts if f.get('evidence_id')}
        section = self._normalize_section_format(section)
        ids = set(re.findall(r'\bE-[A-Z0-9-]{6,}\b', section, re.I))
        expected_heading = f'## {index}. {title}'
        if index == 1:
            section = mark_unverified_numbers(section, facts)
        initial_reasons = self._section_validation_reasons(section, allowed, index, title)
        initial_reasons += list(dict.fromkeys(x['code'] for x in claim_semantic_issues(section, facts)))
        if initial_reasons:
            emit(trace_emit, 'report', self.trace_agent, '章节校验未通过，尝试一次局部修复',
                 f'chapter={index}; reasons={",".join(initial_reasons)}', status='warning', validation_reasons=initial_reasons)
            # Retain cited cards first, then validate against exactly what the repair saw.
            repair_package = json.loads(bounded_package({**package, 'facts': sorted(facts,
                key=lambda f: f.get('evidence_id') not in ids)}, 14000 if index == 1 else 12000))
            repair_facts = repair_package['facts']
            repair_allowed = {f.get('evidence_id') for f in repair_facts if f.get('evidence_id')}
            prompt = (f'仅修复第{index}章，顶级标题为 {expected_heading}。删除无证据结论，保留合法来源编号。'
                      '只输出本章；不能新增数字或证据编号。预测值须在同一分句保留预计/预测标记；'
                      '多卡片或同一发布方不等于独立来源，禁止无据声称多源一致。'
                      '保留同比/环比/CAGR的原指标，不按报告截止日更新旧统计；删除由计费观点推导的强制投资门槛及由宏观数量推导的商业确定性。'
                      '\n校验原因：' + ','.join(initial_reasons) + '\n证据：' + json.dumps(repair_package, ensure_ascii=False)
                      + '\n待修复章节：\n' + section[:8000])
            if index == 1:
                prompt += '\n摘要压缩至450字以内，最多5项发现，保留来源编号和数值待核验提示。禁止表格和章节复述。'
            try:
                repaired = self._normalize_section_format(invoke(f'{self.report_kind}章节修复 Agent - {title}', prompt, trace_emit))
                repair_error = ''
            except Exception as exc:
                repaired = ''
                repair_error = type(exc).__name__
            if index == 1:
                repaired = mark_unverified_numbers(repaired, repair_facts)
            repair_reasons = self._section_validation_reasons(repaired, repair_allowed, index, title)
            repair_reasons += list(dict.fromkeys(x['code'] for x in claim_semantic_issues(repaired, repair_facts)))
            if repair_error:
                repair_reasons.append('model_error:' + repair_error)
            if not repair_reasons:
                section = repaired
            else:
                # Preserve traceable facts, not prose whose citations failed.
                section = self._fallback_section(package, index, title)
                if degradations is not None:
                    labels = {'wrong_heading':'标题不符', 'duplicate_chapter_heading':'章节标题重复',
                              'missing_citation':'缺少引用', 'invalid_citation':'引用不在修复证据包', 'summary_too_long':'摘要超长',
                              'forecast_presented_as_actual':'预测属性缺失', 'source_corroboration_overstated':'多源印证依据不足',
                              'evidence_status_conflict':'证据状态矛盾', 'concentration_inference_unsupported':'集中度推断缺证',
                              'growth_comparison_unsupported':'增速比较口径不足', 'policy_primary_source_missing':'缺少政策原文',
                              'policy_penalty_scope_conflict':'处罚适用类型错误', 'policy_effective_date_conflict':'政策生效日期错误',
                              'evidence_gap_as_business_risk':'证据缺口误作经营风险'}
                    labels.update({'entry_barrier_inference_unsupported':'进入壁垒推断缺证',
                        'evidence_gap_as_policy_effect':'缺证误作执行低效','derived_forecast_unvalidated':'新增预测数值缺少验证',
                        'policy_causal_inference_unsupported':'政策效果推断缺证','evidence_absence_overstated':'选证范围被扩大',
                        'sample_extrapolation_unsupported':'企业样本外推行业','table_total_incomplete':'表格列示与总数不一致',
                        'section_task_conflict':'子标题与本章任务不符'})
                    labels.update({'business_screening_rule_unsupported':'投资筛选门槛缺证','growth_rate_kind_conflict':'增长率类型被替换',
                        'growth_benchmark_missing':'增速比较缺少基准','allocation_inference_unsupported':'投入错配推断缺证',
                        'integration_inference_unsupported':'产业整合推断缺证','commercial_certainty_unsupported':'商业确定性推断缺证',
                        'statistic_asof_rebased':'历史统计被更新到截止日','rate_unit_conflict':'增长率单位错误'})
                    labels.update({'publisher_attribution_unsupported':'发布机构归属缺证','roadmap_as_current_state':'历史目标误作现状'})
                    explanation = '、'.join(labels.get(reason, reason) for reason in repair_reasons)
                    degradations.append({'chapter': index, 'initial_validation_reasons': initial_reasons,
                        'repair_validation_reasons': repair_reasons,
                        'message': f'第{index}章局部修复失败（{explanation}），使用来源事实摘录；建议复核综合判断。'})
                emit(trace_emit, 'report', self.trace_agent, '局部修复失败，保留来源事实摘录',
                     f'chapter={index}; reasons={",".join(repair_reasons)}', status='fallback', validation_reasons=repair_reasons)
        return mark_unverified_numbers(section, facts)
