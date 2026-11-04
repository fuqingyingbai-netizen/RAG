import json
from copy import copy
import os
import re
from typing import Any, Callable

from .report_prompts import (
    _focused_cleaned_json,
    build_editor_prompt,
    build_section_prompt,
    company_section_density,
    company_section_evidence_budget,
)
from .report_style import REFERENCE_REPORT_STYLE, REPORT_CHAPTER_HEADING_RE, ensure_delivery_sections, normalize_report_headings
from .company_summary import (
    build_company_summary_package,
    build_company_summary_prompt,
    fallback_company_summary,
    normalize_company_summary,
    package_fingerprint,
    summary_errors,
)
from .company_governance import build_governance_package, render_governance, governance_errors, cited_evidence_ids
from .company_history import build_history_package, render_history, history_errors
from .company_operations import build_operations_package, render_operations, operations_errors
from .company_reputation import build_reputation_package, render_reputation, reputation_errors
from .company_business import build_business_package, render_business, business_errors
from .company_management import build_management_package, render_management, management_errors
from .company_people import build_people_package, render_people, people_errors
from .company_judicial import build_judicial_package, render_judicial, judicial_errors
from .company_diligence import build_diligence_package, render_diligence, diligence_errors
from .company_risk_register import build_risk_register, dictionary as risk_dictionary, render_risk_register, risk_register_errors
from .company_assessment import build_assessment_package, render_assessment, assessment_errors
from .company_source_review import build_source_review, render_reviewed_statements
from .company_corpus import build_corpus_review,build_corpus_review_with_recovery
from .company_corpus_writer import corpus_cache_matches,build_compact_digest,render_compact_chapters,update_evidence_diagnostics,collect_statements
from .company_text import company_matching_cache
from company_chapters import chapters as company_chapters, outline as chapter_outline, prompt_contract, uses_chapter_contract, VERSION as CHAPTER_TEMPLATE_VERSION
from .company_chapter_agent import create_chapter_agents


COMPANY_REPORT_OUTLINE = chapter_outline(legacy=True)


COMPANY_SECTION_STRUCTURES = {c['chapter']: prompt_contract(c['chapter']) for c in company_chapters()}


COMPANY_RISK_TAXONOMY = (
    "公司风险核查字典（模板75个问题，不是已发生事实或默认评分）：\n"
    + "\n".join(item['id'] + ' ' + item['category'] + ('／' + item['sector'] if item['sector'] else '')
                + '：' + item['label'] for item in risk_dictionary()['items'])
)


COMPANY_SECTION_FEW_SHOTS = {c['chapter']: c['few_shot']['text'] if c['few_shot']['status'] == 'active' else ''
                           for c in company_chapters()}


COMPANY_FEW_SHOT = f"""
目标公司桌面研究报告写作要求：
- 固定为 14 节，章节标题必须与标准目录一致；每节使用该节专属结构，不得机械套用"本章结论/事实梳理/分析判断/风险与待核验"。
- 证据不足处正文只写"待核验"，不要反复写"暂无充分公开证据"；所有缺口统一进入集中式待核验清单，不得编造访谈、财务、司法、客户、供应商或经营数据。
- 工商表建议列：主体名称｜成立时间｜注册资本｜股东/实控人｜历史变更｜异常/待核验｜来源。
- 经营核验表建议列：业务板块｜产品/服务｜运营数据｜研发/产能/销售进展｜证据强度｜待核验事项。

{COMPANY_RISK_TAXONOMY}
"""


class CompanyReportAgent:
    report_kind = "BDD目标公司桌面研究报告"
    trace_agent = "company_report_agent"
    outline = COMPANY_REPORT_OUTLINE

    @company_matching_cache()
    def generate(
        self, project, cleaned_json, risk_json, invoke, clip, emit, trace_emit=None,
    ):
        # A workflow can serve concurrent old and new tasks. Keep its shared
        # agent instance immutable while each run binds its own chapter titles.
        return copy(self)._generate(project, cleaned_json, risk_json, invoke, clip, emit, trace_emit)

    def _generate(
        self,
        project: Any,
        cleaned_json: str,
        risk_json: str,
        invoke: Callable[[str, str, Any], str],
        clip: Callable[[str, int], str],
        emit: Callable[..., None],
        trace_emit: Any = None,
    ) -> str:
        self.outline = chapter_outline(legacy=not uses_chapter_contract(getattr(project, 'company_research_intake', {}) or {}))
        agents = create_chapter_agents(project, emit, trace_emit)
        project._company_chapter_agents = agents
        project.company_chapter_agents_metadata = [a.metadata() for a in agents.values()]
        project.company_template_version = CHAPTER_TEMPLATE_VERSION
        sections_by_index: dict[int, str] = {}
        project.company_corpus_digest_package={}
        project.company_information_usage_package={}
        project.company_editorial_package={}
        project.company_document_review={}
        project.company_delivery_contract={}
        project.company_delivery_contract_required=True
        from .company_presentation import reading_mode
        project.company_reading_mode=reading_mode(project)
        project.company_presentation_package={}
        project.company_main_focus_package={}
        project._company_main_focus_journal_index=None
        project.company_evidence_annex_html=''
        project.company_evidence_annex_manifest={}
        project.company_source_captions={}
        project._company_presentation_journal_index=None
        project.company_summary_editorial_feedback=[]
        emit(trace_emit, "report", self.trace_agent, "目标公司报告团队启动", f"sections={len(self.outline)}", status="running")
        # Company reports keep the fixed 14-chapter delivery outline, but their
        # content density follows the evidence.  A source may support several
        # chapters when each chapter uses a different claim from that source;
        # URL de-duplication is chapter-local, never global.
        section_packages: dict[int, str] = {}
        section_evidence_ids: dict[int, list[str]] = {}
        all_used_urls: set[str] = set()
        for index, (section_title, requirements) in enumerate(self.outline, 1):
            package_payload: dict[str, Any]
            if 2 <= index <= 12:
                text,package_payload=self.render_evidence_chapter(project,index,cleaned_json,invoke,emit,trace_emit)
                sections_by_index[index]=text
                section_evidence_ids[index]=sorted(set(cited_evidence_ids(text)))
            else:
                package_payload={'facts':[]}
                section_evidence_ids[index]=[]
            if index <= 12:
                all_used_urls.update(str(r.get("source_url") or "") for r in package_payload.get("facts", [])
                                     if isinstance(r, dict) and r.get("source_url"))
            section_packages[index] = json.dumps(package_payload, ensure_ascii=False)
        emit(
            trace_emit,
            "report",
            self.trace_agent,
            "公司章节证据分桶完成",
            f"unique_package_sources={len(all_used_urls)}, verified_chapters=12, cross_chapter_reuse=true",
            status="done",
        )

        # Chapter 13 is replaced by the deterministic audit index downstream.
        # Keeping a short placeholder avoids spending a model call on a source
        # list that the model must never invent.
        sections_by_index[13] = "## 13. 信息来源\n\n本章由系统根据正文实际引用的证据编号自动生成。"
        # The generic cleaning gaps predate the chapter-specific original
        # document checks. Repeating them resurrects already recovered facts
        # (e.g. product lines or judicial details) as false 'missing' findings.
        verification_gaps = []
        verification_gaps = list(dict.fromkeys(
            verification_gaps + getattr(project, "company_governance_package", {}).get("information_gaps", [])
            + getattr(project, "company_history_package", {}).get("information_gaps", [])
            + getattr(project, "company_operations_package", {}).get("information_gaps", [])
            + getattr(project, "company_reputation_package", {}).get("information_gaps", [])
            + getattr(project, "company_business_package", {}).get("information_gaps", [])
            + getattr(project, "company_management_package", {}).get("information_gaps", [])
            + getattr(project, "company_people_package", {}).get("information_gaps", [])
            + getattr(project, "company_judicial_package", {}).get("information_gaps", [])
            + getattr(project, "company_diligence_package", {}).get("information_gaps", [])
            + getattr(project, "company_risk_register_package", {}).get("information_gaps", [])
            + getattr(project, "company_assessment_package", {}).get("information_gaps", [])
        ))
        sections_by_index[14] = "## 14. 后续研究建议\n\n" + (
            "\n".join(f"- 待核验：{item}" for item in verification_gaps)
            if verification_gaps
            else "本次桌面研究未形成额外待核验事项。"
        )
        # Specialized parsers deliberately recognize narrow schemas. A missing
        # schema match is not an unusable original: review subject-bound native
        # statements and retain every source's actual disposition separately.
        try:
            review_cleaned = json.loads(cleaned_json or '{}')
        except (ValueError, TypeError):
            review_cleaned = {}
        full_corpus=os.getenv('COMPANY_CORPUS_REVIEW_ENABLED','true').strip().lower() in {'1','true','yes','on'}
        cached=getattr(project,'company_corpus_analysis_cache',{}) or {}
        if full_corpus and corpus_cache_matches(project,cached):
            review=cached
            emit(trace_emit,'report','company_corpus','复用同一语料已完成的全量分析',
                 '逐来源原文哈希、研究主体、截至日及完整性核对通过；本次仅重新归纳写作。',status='done')
        elif full_corpus:
            review=build_corpus_review_with_recovery(project,review_cleaned,sections_by_index,invoke,emit,trace_emit,
                builder=build_corpus_review)
        else:
            review=build_source_review(project,review_cleaned,sections_by_index,invoke,emit,trace_emit)
        project.company_source_review_package = review
        if full_corpus:project.company_corpus_analysis_cache=review
        from .company_checkpoint import checkpoint_generation_stage,checkpoint_editorial_batch
        checkpoint_generation_stage(project,emit,trace_emit)
        if full_corpus and os.getenv('COMPANY_CORPUS_COMPACT_WRITE_ENABLED','true').strip().lower() in {'1','true','yes','on'}:
            from .company_information_usage import build_information_usage, append_information_markdown, source_information_map, routing_scope
            editorial_enabled=os.getenv('COMPANY_DELIVERY_EDITORIAL_ENABLED','true').strip().lower() in {'1','true','yes','on'}
            if editorial_enabled:
                # Route all native information before writing. A short digest
                # and raw quotations no longer masquerade as a finished report.
                statements=collect_statements(project,review)
                digest={'version':'company-delivery-native-input-v1','target_name':str(project.target_name),
                    'statements':statements,'groups':[],'appendix_statements':[],
                    'diagnostic':{'native_statements':len(statements),'narrative_input_statements':len(statements),
                                  'unaccounted_statement_ids':[]}}
            else:
                digest=build_compact_digest(project,review,self.outline,invoke,emit,trace_emit)
            project.company_corpus_digest_package=digest
            from .company_information_journal import checkpoint_batch as checkpoint_routing, read_decisions as read_routing
            usage=build_information_usage(digest,sections_by_index,self.outline,str(project.target_name),invoke,
                previous=getattr(project,'company_information_usage_cache',{}),review_scope=routing_scope(project),
                emit=emit,trace_emit=trace_emit,
                receipt_callback=lambda batch:checkpoint_routing(project,batch,self.outline,emit,trace_emit),
                journal_loader=lambda rows:read_routing(project,rows,self.outline))
            usage['source_map']=source_information_map(list(project.sources or []),review,usage)
            project.company_information_usage_package=usage
            checkpoint_generation_stage(project,emit,trace_emit)
            if editorial_enabled:
                from .company_editorial import build_editorial_package,digest_groups,apply_narrative_uses,render_conflicts,fingerprint,record_payload
                editorial_usage=usage
                if project.company_reading_mode=='analysis_with_annex':
                    from .company_presentation import build_presentation,presentation_scope,main_usage,render_annex,checkpoint_batch,source_captions
                    presentation=build_presentation(usage,str(project.target_name),presentation_scope(project),invoke,
                        previous=getattr(project,'company_presentation_cache',{}),emit=emit,trace_emit=trace_emit,
                        receipt_callback=lambda batch:checkpoint_batch(project,batch,emit,trace_emit))
                    project.company_presentation_package=presentation
                    from .company_main_focus import build_main_focus,checkpoint_batch as checkpoint_focus
                    focus=build_main_focus(usage,presentation,str(project.target_name),presentation_scope(project),invoke,
                        previous=getattr(project,'company_main_focus_cache',{}),emit=emit,trace_emit=trace_emit,
                        receipt_callback=lambda batch:checkpoint_focus(project,batch,emit,trace_emit))
                    project.company_main_focus_package=focus
                    editorial_usage=main_usage(usage,presentation,focus)
                    project.company_source_captions=source_captions(project,usage)
                    project.company_evidence_annex_html=render_annex(usage,presentation,str(project.target_name),project.company_source_captions)
                    import hashlib
                    project.company_evidence_annex_manifest={
                        'sha256':hashlib.sha256(project.company_evidence_annex_html.encode('utf-8')).hexdigest(),
                        'native_input_sha256':fingerprint([record_payload(r) for r in usage.get('records',[])]),
                        'information_records':len(usage.get('records',[]))}
                    checkpoint_generation_stage(project,emit,trace_emit)
                editorial=build_editorial_package(editorial_usage,self.outline,str(project.target_name),invoke,
                    previous=getattr(project,'company_editorial_cache',{}),emit=emit,trace_emit=trace_emit,
                    receipt_callback=lambda batch:checkpoint_editorial_batch(project,batch,emit,trace_emit),
                    chapter_agents=agents)
                project.company_editorial_package=editorial
                checkpoint_generation_stage(project,emit,trace_emit)
                digest['groups']=digest_groups(editorial)
                digest['diagnostic'].update(editorial['diagnostic'])
                apply_narrative_uses(usage,editorial)
                sections_by_index=render_compact_chapters(project,digest,self.outline,sections_by_index)
                update_evidence_diagnostics(project,digest,sections_by_index)
                # Preserve the deterministic scoring calculation, while adding
                # checked non-scoring observations in the assessment chapter.
                for group in digest['groups']:
                    if group['chapter']==12:
                        sections_by_index[12]+='\n\n'+group['summary']
                sections_by_index=render_conflicts(editorial,sections_by_index)
                from .company_delivery_contract import fill_evidence_gaps
                sections_by_index=fill_evidence_gaps(sections_by_index,editorial,self.outline,usage=usage)
                project.company_information_details=append_information_markdown(usage,{},self.outline)
            else:
                sections_by_index=render_compact_chapters(project,digest,self.outline,sections_by_index)
                update_evidence_diagnostics(project,digest,sections_by_index)
                sections_by_index=append_information_markdown(usage,sections_by_index,self.outline)
        else:
            for chapter in range(2,12):
                rows=[r for r in review['facts'] if r['chapter']==chapter]
                sections_by_index[chapter]+=render_reviewed_statements(rows)
        for chapter in range(2,12):
            section_evidence_ids[chapter]=sorted(set(cited_evidence_ids(sections_by_index[chapter])))
        summary = self._write_summary(project, cleaned_json, sections_by_index, invoke, emit, trace_emit)
        sections_by_index[1] = summary
        # Only IDs actually cited in the checked summary count as its usage.
        section_evidence_ids[1] = sorted(set(cited_evidence_ids(summary)))
        sections_by_index = {n: agents[n].execute(
            lambda n=n, text=text: normalize_report_headings(text, {n: self.outline[n-1][0]}),
            phase='finalize') for n, text in sections_by_index.items()}
        project.company_chapter_agents_metadata = [a.metadata() for a in agents.values()]
        sections = [sections_by_index[index] for index in range(1, len(self.outline) + 1) if sections_by_index.get(index)]
        draft = "\n\n".join(sections)
        if not draft.strip():
            return ""
        # Default to the section drafts plus deterministic outline locking.
        # The batch editor is useful for wording polish, but it was also the
        # main place where the report drifted away from the standard sample:
        # subsections were promoted, thin required chapters were compressed,
        # and the Word directory no longer matched the intended 14 chapters.
        if os.getenv("COMPANY_REPORT_EDITOR_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}:
            final = self._edit_batched(project, sections, section_evidence_ids, invoke, emit, trace_emit)
        else:
            final = draft
        final = self._lock_standard_outline(final, sections_by_index, outline=self.outline)
        # A later wording editor cannot silently replace a checked summary
        # with a fresh, ungrounded set of claims.
        final = re.sub(r"(?ms)^##\s*1[.、．][^\n]*\n.*?(?=^##\s*2[.、．]|\Z)", summary + "\n\n", final, count=1)
        final = re.sub(r"(?ms)^##\s*2[.、．][^\n]*\n.*?(?=^##\s*3[.、．]|\Z)",
                       lambda _m: sections_by_index[2] + "\n\n", final, count=1)
        final = re.sub(r"(?ms)^##\s*3[.、．][^\n]*\n.*?(?=^##\s*4[.、．]|\Z)",
                       lambda _m: sections_by_index[3] + "\n\n", final, count=1)
        final = re.sub(r"(?ms)^##\s*4[.、．][^\n]*\n.*?(?=^##\s*5[.、．]|\Z)",
                       lambda _m: sections_by_index[4] + "\n\n", final, count=1)
        final = re.sub(r"(?ms)^##\s*5[.、．][^\n]*\n.*?(?=^##\s*6[.、．]|\Z)",
                       lambda _m: sections_by_index[5] + "\n\n", final, count=1)
        final = re.sub(r"(?ms)^##\s*6[.、．][^\n]*\n.*?(?=^##\s*7[.、．]|\Z)",
                       lambda _m: sections_by_index[6] + "\n\n", final, count=1)
        final = re.sub(r"(?ms)^##\s*7[.、．][^\n]*\n.*?(?=^##\s*8[.、．]|\Z)",
                       lambda _m: sections_by_index[7] + "\n\n", final, count=1)
        final = re.sub(r"(?ms)^##\s*8[.、．][^\n]*\n.*?(?=^##\s*9[.、．]|\Z)",
                       lambda _m: sections_by_index[8] + "\n\n", final, count=1)
        final = re.sub(r"(?ms)^##\s*9[.、．][^\n]*\n.*?(?=^##\s*10[.、．]|\Z)",
                       lambda _m: sections_by_index[9] + "\n\n", final, count=1)
        final = re.sub(r"(?ms)^##\s*10[.、．][^\n]*\n.*?(?=^##\s*11[.、．]|\Z)",
                       lambda _m: sections_by_index[10] + "\n\n", final, count=1)
        final = re.sub(r"(?ms)^##\s*11[.、．][^\n]*\n.*?(?=^##\s*12[.、．]|\Z)",
                       lambda _m: sections_by_index[11] + "\n\n", final, count=1)
        final = re.sub(r"(?ms)^##\s*12[.、．][^\n]*\n.*?(?=^##\s*13[.、．]|\Z)",
                       lambda _m: sections_by_index[12] + "\n\n", final, count=1)
        final = self._ensure_section_evidence_markers(final, section_evidence_ids)
        final = ensure_delivery_sections(project, final, self.report_kind)
        emit(trace_emit, "report", self.trace_agent, "目标公司桌面研究报告完成", f"chars={len(final)}", chars=len(final), status="done")
        return final

    def render_evidence_chapter(self, project, index, cleaned_json, invoke, emit, trace_emit=None):
        """Run one existing specialized parser/validator, never another writer."""
        if not 2 <= index <= 12:
            raise ValueError('unsupported_company_evidence_chapter')
        self=copy(self)
        self.outline=chapter_outline()
        agents=getattr(project,'_company_chapter_agents',None) or create_chapter_agents(project,emit,trace_emit)
        section_title,requirements=self.outline[index-1]
        sections_by_index={};section_evidence_ids={};all_used_urls=set()
        if index == 1:
            # The summary is assembled after substantive chapters. Its
            # cards are selected and budgeted independently below.
            package_payload = {"facts": []}
            section_evidence_ids[1] = []
        elif index == 2:
            try:
                parsed = json.loads(cleaned_json or "{}")
            except (ValueError, TypeError):
                parsed = {}
            package_payload = build_governance_package(
                parsed if isinstance(parsed, dict) else {}, str(project.target_name or ""),
                list(getattr(project, "sources", []) or []),
                as_of_date=str((getattr(project,"company_research_intake",{}) or {}).get('as_of_date') or ''),
            )
            project.company_governance_package = package_payload
            chapter = agents[index].execute(lambda: self._write_governance(project, package_payload, emit, trace_emit))
            sections_by_index[2] = chapter
            section_evidence_ids[2] = sorted(set(cited_evidence_ids(chapter)))
        elif index == 3:
            try:
                parsed = json.loads(cleaned_json or "{}")
            except (ValueError, TypeError):
                parsed = {}
            package_payload = build_history_package(
                parsed if isinstance(parsed, dict) else {}, str(project.target_name or ""),
                list(getattr(project, "sources", []) or []),
                governance=getattr(project, "company_governance_package", {}),
            )
            project.company_history_package = package_payload
            chapter = agents[index].execute(lambda: self._write_history(project, package_payload, emit, trace_emit))
            sections_by_index[3] = chapter
            section_evidence_ids[3] = sorted(set(cited_evidence_ids(chapter)))
        elif index == 4:
            try:
                parsed = json.loads(cleaned_json or "{}")
            except (ValueError, TypeError):
                parsed = {}
            package_payload = build_operations_package(
                parsed if isinstance(parsed, dict) else {}, str(project.target_name or ""),
                list(getattr(project, "sources", []) or []),
                governance=getattr(project, "company_governance_package", {}),
            )
            project.company_operations_package = package_payload
            chapter = agents[index].execute(lambda: self._write_operations(project, package_payload, emit, trace_emit))
            sections_by_index[4] = chapter
            section_evidence_ids[4] = sorted(set(cited_evidence_ids(chapter)))
        elif index == 5:
            try:
                parsed = json.loads(cleaned_json or "{}")
            except (ValueError, TypeError):
                parsed = {}
            package_payload = build_reputation_package(
                parsed if isinstance(parsed, dict) else {}, str(project.target_name or ""),
                list(getattr(project, "sources", []) or []),
                as_of=str((getattr(project, "company_research_intake", {}) or {}).get('as_of_date') or ''),
            )
            project.company_reputation_package = package_payload
            chapter = agents[index].execute(lambda: self._write_reputation(project, package_payload, emit, trace_emit))
            sections_by_index[5] = chapter
            section_evidence_ids[5] = sorted(set(cited_evidence_ids(chapter)))
        elif index == 6:
            try:
                parsed = json.loads(cleaned_json or "{}")
            except (ValueError, TypeError):
                parsed = {}
            package_payload = build_business_package(
                parsed if isinstance(parsed, dict) else {}, str(project.target_name or ""),
                list(getattr(project, "sources", []) or []),
                as_of=str((getattr(project, "company_research_intake", {}) or {}).get('as_of_date') or ''),
            )
            project.company_business_package = package_payload
            chapter = agents[index].execute(lambda: self._write_business(project, package_payload, emit, trace_emit))
            sections_by_index[6] = chapter
            section_evidence_ids[6] = sorted(set(cited_evidence_ids(chapter)))
        elif index == 7:
            try:
                parsed = json.loads(cleaned_json or "{}")
            except (ValueError, TypeError):
                parsed = {}
            package_payload = build_management_package(
                parsed if isinstance(parsed, dict) else {}, str(project.target_name or ""),
                list(getattr(project, "sources", []) or []),
                governance=getattr(project, "company_governance_package", {}),
            )
            project.company_management_package = package_payload
            chapter = agents[index].execute(lambda: self._write_management(project, package_payload, emit, trace_emit))
            sections_by_index[7] = chapter
            section_evidence_ids[7] = sorted(set(cited_evidence_ids(chapter)))
        elif index == 8:
            try:
                parsed = json.loads(cleaned_json or "{}")
            except (ValueError, TypeError):
                parsed = {}
            package_payload = build_people_package(
                parsed if isinstance(parsed, dict) else {}, str(project.target_name or ""),
                list(getattr(project, "sources", []) or []),
            )
            project.company_people_package = package_payload
            chapter = agents[index].execute(lambda: self._write_people(project, package_payload, emit, trace_emit))
            sections_by_index[8] = chapter
            section_evidence_ids[8] = sorted(set(cited_evidence_ids(chapter)))
        elif index == 9:
            try:
                parsed = json.loads(cleaned_json or "{}")
            except (ValueError, TypeError):
                parsed = {}
            package_payload = build_judicial_package(
                parsed if isinstance(parsed, dict) else {}, str(project.target_name or ""),
                list(getattr(project, "sources", []) or []),
                query_attempts=getattr(project, "company_judicial_query_attempts", []),
            )
            project.company_judicial_package = package_payload
            chapter = agents[index].execute(lambda: self._write_judicial(project, package_payload, emit, trace_emit))
            sections_by_index[9] = chapter
            section_evidence_ids[9] = sorted(set(cited_evidence_ids(chapter)))
        elif index == 10:
            try:
                parsed = json.loads(cleaned_json or "{}")
            except (ValueError, TypeError):
                parsed = {}
            package_payload = build_diligence_package(
                parsed if isinstance(parsed, dict) else {}, str(project.target_name or ""),
                list(getattr(project, "sources", []) or []),
                prior_packages={"history": getattr(project, "company_history_package", {}),
                                "judicial": getattr(project, "company_judicial_package", {})},
                intake=getattr(project, "company_research_intake", {}),
            )
            project.company_diligence_package = package_payload
            chapter = agents[index].execute(lambda: self._write_diligence(project, package_payload, emit, trace_emit))
            sections_by_index[10] = chapter
            section_evidence_ids[10] = sorted(set(cited_evidence_ids(chapter)))
        elif index == 11:
            try:
                parsed = json.loads(cleaned_json or "{}")
            except (ValueError, TypeError):
                parsed = {}
            from .company_event_evidence import review_primary_events
            project.company_event_review_package = review_primary_events(
                list(getattr(project, 'sources', []) or []), str(project.target_name or ''),
                str((getattr(project, 'company_research_intake', {}) or {}).get('as_of_date') or ''),
                invoke, cache=getattr(project, 'company_event_review_cache', None), trace_emit=trace_emit)
            from .company_checkpoint import checkpoint_generation_stage
            checkpoint_generation_stage(project, emit, trace_emit)
            package_payload = build_risk_register(
                parsed if isinstance(parsed, dict) else {}, str(project.target_name or ""),
                list(getattr(project, "sources", []) or []),
                industry=str(getattr(project, "industry", "") or ""),
                intake=getattr(project, "company_research_intake", {}),
                query_attempts=getattr(project, "company_judicial_query_attempts", []),
                displayed_judicial=getattr(project,"company_judicial_package",{}),
                event_reviews=project.company_event_review_package,
            )
            project.company_risk_register_package = package_payload
            chapter = agents[index].execute(lambda: self._write_risk_register(project, package_payload, emit, trace_emit))
            sections_by_index[11] = chapter
            section_evidence_ids[11] = sorted(set(cited_evidence_ids(chapter)))
        elif index == 12:
            try:
                parsed = json.loads(cleaned_json or "{}")
            except (ValueError, TypeError):
                parsed = {}
            package_payload = build_assessment_package(
                parsed if isinstance(parsed, dict) else {}, str(project.target_name or ""),
                list(getattr(project, "sources", []) or []),
                industry=str(getattr(project, "industry", "") or ""),
                intake=getattr(project, "company_research_intake", {}),
                event_reviews=getattr(project, 'company_event_review_package', None),
            )
            project.company_assessment_package = package_payload
            chapter = agents[index].execute(lambda: self._write_assessment(project, package_payload, emit, trace_emit))
            sections_by_index[12] = chapter
            section_evidence_ids[12] = sorted(set(cited_evidence_ids(chapter)))
        elif index <= 12:
            package = _focused_cleaned_json(
                cleaned_json,
                section_title,
                requirements,
                str(project.target_name or ""),
                "company",
            )
            try:
                package_payload = json.loads(package)
            except (TypeError, ValueError, json.JSONDecodeError):
                package_payload = {"facts": []}
            evidence_budget = company_section_evidence_budget(section_title)
            facts = [item for item in package_payload.get("facts", []) if isinstance(item, dict)][:evidence_budget]
            for item in facts:
                evidence_id = str(item.get("evidence_id") or "").strip()
                if evidence_id:
                    item["citation"] = f"[{evidence_id}]"
            package_payload["facts"] = facts
            package_payload["chapter_evidence_budget"] = evidence_budget
            package_payload["chapter_density"] = company_section_density(facts, section_title)
            section_evidence_ids[index] = [
                str(item.get("evidence_id") or "").strip()
                for item in facts
                if str(item.get("evidence_id") or "").strip()
            ]
            all_used_urls.update(
                str(item.get("source_url") or "").rstrip("/")
                for item in facts
                if str(item.get("source_url") or "").startswith(("http://", "https://"))
            )
        else:
            try:
                package_payload = json.loads(cleaned_json or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                package_payload = {}
            package_payload["facts"] = []
        text=normalize_report_headings(sections_by_index[index],{index:self.outline[index-1][0]})
        return text,package_payload

    def _write_governance(self, project: Any, package: dict, emit, trace_emit=None) -> str:
        chapter = render_governance(package)
        errors = governance_errors(chapter, package)
        project.company_governance_diagnostic = {
            "version": package["version"], **package["diagnostic"],
            "conflicts": package["conflicts"], "information_gaps": package["information_gaps"],
            "errors": errors, "degraded": bool(errors),
            "cited_evidence_ids": sorted(set(cited_evidence_ids(chapter))),
        }
        emit(trace_emit, "report", self.trace_agent, "第二章按字段证据完成核对与排版",
             json.dumps(project.company_governance_diagnostic, ensure_ascii=False),
             section=self.outline[1][0], status="fallback" if errors else "done")
        return chapter

    def _write_history(self, project: Any, package: dict, emit, trace_emit=None) -> str:
        chapter = render_history(package)
        errors = history_errors(chapter, package)
        project.company_history_diagnostic = {
            "version": package["version"], **package["diagnostic"], "errors": errors,
            "degraded": bool(errors), "information_gaps": package["information_gaps"],
            "cited_evidence_ids": sorted(set(cited_evidence_ids(chapter))),
        }
        emit(trace_emit, "report", self.trace_agent, "第三章沿革与成长质量核对完成",
             json.dumps(project.company_history_diagnostic, ensure_ascii=False),
             section=self.outline[2][0], status="fallback" if errors else "done")
        return chapter

    def _write_operations(self, project: Any, package: dict, emit, trace_emit=None) -> str:
        chapter = render_operations(package)
        errors = operations_errors(chapter, package)
        project.company_operations_diagnostic = {
            "version": package["version"], **package["diagnostic"], "errors": errors,
            "degraded": bool(errors), "information_gaps": package["information_gaps"],
            "cited_evidence_ids": sorted(set(cited_evidence_ids(chapter))),
        }
        emit(trace_emit, "report", self.trace_agent, "第四章治理制度与运行记录核对完成",
             json.dumps(project.company_operations_diagnostic, ensure_ascii=False),
             section=self.outline[3][0], status="fallback" if errors else "done")
        return chapter

    def _write_reputation(self, project: Any, package: dict, emit, trace_emit=None) -> str:
        chapter = render_reputation(package)
        errors = reputation_errors(chapter, package)
        project.company_reputation_diagnostic = {
            "version": package["version"], **package["diagnostic"], "errors": errors,
            "degraded": bool(errors), "information_gaps": package["information_gaps"],
            "cited_evidence_ids": sorted(set(cited_evidence_ids(chapter))),
        }
        emit(trace_emit, "report", self.trace_agent, "第五章评价主体与同口径对标核对完成",
             json.dumps(project.company_reputation_diagnostic, ensure_ascii=False),
             section=self.outline[4][0], status="fallback" if errors else "done")
        return chapter

    def _write_business(self, project: Any, package: dict, emit, trace_emit=None) -> str:
        chapter = render_business(package)
        errors = business_errors(chapter, package)
        project.company_business_diagnostic = {
            "version": package["version"], **package["diagnostic"], "errors": errors,
            "degraded": bool(errors), "information_gaps": package["information_gaps"],
            "cited_evidence_ids": sorted(set(cited_evidence_ids(chapter))),
        }
        emit(trace_emit, "report", self.trace_agent, "第六章业务口径与研发阶段核对完成",
             json.dumps(project.company_business_diagnostic, ensure_ascii=False),
             section=self.outline[5][0], status="fallback" if errors else "done")
        return chapter

    def _write_management(self, project: Any, package: dict, emit, trace_emit=None) -> str:
        chapter = render_management(package)
        errors = management_errors(chapter, package)
        project.company_management_diagnostic = {
            "version": package["version"], **package["diagnostic"], "errors": errors,
            "degraded": bool(errors), "information_gaps": package["information_gaps"],
            "cited_evidence_ids": sorted(set(cited_evidence_ids(chapter))),
        }
        emit(trace_emit, "report", self.trace_agent, "第七章人员任职与时点核对完成",
             json.dumps(project.company_management_diagnostic, ensure_ascii=False),
             section=self.outline[6][0], status="fallback" if errors else "done")
        return chapter

    def _write_people(self, project: Any, package: dict, emit, trace_emit=None) -> str:
        chapter = render_people(package)
        errors = people_errors(chapter, package)
        project.company_people_diagnostic = {
            "version": package["version"], **package["diagnostic"], "errors": errors,
            "degraded": bool(errors), "information_gaps": package["information_gaps"],
            "cited_evidence_ids": sorted(set(cited_evidence_ids(chapter))),
        }
        emit(trace_emit, "report", self.trace_agent, "第八章人员指标与文化实践核对完成",
             json.dumps(project.company_people_diagnostic, ensure_ascii=False),
             section=self.outline[7][0], status="fallback" if errors else "done")
        return chapter

    def _write_judicial(self, project: Any, package: dict, emit, trace_emit=None) -> str:
        chapter = render_judicial(package)
        errors = judicial_errors(chapter, package)
        project.company_judicial_diagnostic = {
            "version": package["version"], **package["diagnostic"], "errors": errors,
            "degraded": bool(errors), "information_gaps": package["information_gaps"],
            "cited_evidence_ids": sorted(set(cited_evidence_ids(chapter))),
        }
        emit(trace_emit, "report", self.trace_agent, "第九章司法记录与范围核对完成",
             json.dumps(project.company_judicial_diagnostic, ensure_ascii=False),
             section=self.outline[8][0], status="fallback" if errors else "done")
        return chapter

    def _write_diligence(self, project: Any, package: dict, emit, trace_emit=None) -> str:
        chapter = render_diligence(package)
        errors = diligence_errors(chapter, package)
        project.company_diligence_diagnostic = {
            "version": package["version"], **package["diagnostic"], "errors": errors,
            "degraded": bool(errors), "information_gaps": package["information_gaps"],
            "cited_evidence_ids": sorted(set(cited_evidence_ids(chapter))),
        }
        emit(trace_emit, "report", self.trace_agent, "第十章专项对象与核查边界核对完成",
             json.dumps(project.company_diligence_diagnostic, ensure_ascii=False),
             section=self.outline[9][0], status="fallback" if errors else "done")
        return chapter

    def _write_risk_register(self, project: Any, package: dict, emit, trace_emit=None) -> str:
        chapter = render_risk_register(package)
        errors = risk_register_errors(chapter, package)
        project.company_risk_register_diagnostic = {
            "version": package["version"], **package["diagnostic"], "errors": errors,
            "degraded": bool(errors), "information_gaps": package["information_gaps"],
            "cited_evidence_ids": sorted(set(cited_evidence_ids(chapter))),
        }
        emit(trace_emit, "report", self.trace_agent, "第十一章具体风险与模板核查目录核对完成",
             json.dumps(project.company_risk_register_diagnostic, ensure_ascii=False),
             section=self.outline[10][0], status="fallback" if errors else "done")
        return chapter

    def _write_assessment(self, project: Any, package: dict, emit, trace_emit=None) -> str:
        chapter = render_assessment(package)
        errors = assessment_errors(chapter, package)
        project.company_assessment_diagnostic = {
            "version": package["version"], **package["diagnostic"], "errors": errors,
            "degraded": bool(errors), "information_gaps": package["information_gaps"],
            "cited_evidence_ids": sorted(set(cited_evidence_ids(chapter))),
        }
        emit(trace_emit, "report", self.trace_agent, "第十二章公司评价及评分计算核对完成",
             json.dumps(project.company_assessment_diagnostic, ensure_ascii=False),
             section=self.outline[11][0], status="fallback" if errors else "done")
        return chapter

    def _write_summary(self, project: Any, cleaned_json: str, completed_sections: dict[int, str], invoke, emit, trace_emit=None) -> str:
        try:
            cleaned = json.loads(cleaned_json or "{}")
        except (TypeError, ValueError):
            cleaned = {}
        if not isinstance(cleaned, dict):
            cleaned = {}
        if (getattr(project,'company_editorial_package',{}) or {}).get('findings'):
            # The reader summary must follow the final checked body, not a
            # cleaner card that never survived source/semantic review.
            cleaned={'facts':[]}
        package = build_company_summary_package(
            cleaned, str(project.target_name or ""), list(getattr(project, "sources", []) or []),
            chapter_packages={key: getattr(project, 'company_' + key + '_package', {})
                              for key in ('assessment', 'reputation', 'business', 'governance', 'management','editorial')},
        )
        project.company_summary_package = package
        diagnostic = {
            "version": "company-summary-v1",
            "package_fingerprint": package_fingerprint(package),
            "delivered_evidence_ids": sorted({fact["evidence_id"] for fact in package["facts"]}),
            "delivered_cards": len(package["facts"]),
            "package_chars": len(json.dumps(package, ensure_ascii=False)),
            "selection": package.get("selection_diagnostic", {}),
            "repair_attempted": False, "degraded": False, "errors": [],
        }
        project.company_summary_diagnostic = diagnostic
        emit(trace_emit, "report", self.trace_agent, "公司摘要完整证据包已准备", json.dumps(diagnostic, ensure_ascii=False), status="done")
        if not package["facts"]:
            diagnostic.update(degraded=True, errors=["没有主体匹配的摘要证据"])
            return fallback_company_summary(project, package)
        prompt = build_company_summary_prompt(project, package, completed_sections)
        chapter_agent = (getattr(project, '_company_chapter_agents', {}) or {}).get(1)
        if chapter_agent:
            native_invoke = invoke
            invoke = lambda role, text, trace=None: chapter_agent.invoke(native_invoke, role, text, trace)

        feedback=getattr(project,'company_summary_editorial_feedback',[]) or []
        if feedback:prompt+='\n请修复最终审稿指出的摘要问题；只依据以上事实卡，原有来源范围和归因不能扩大：'+json.dumps(feedback,ensure_ascii=False)
        from company_flow_state import fingerprint,CompanyFlowLimit
        signature=fingerprint(['company-summary-reviewed-input-v2',package_fingerprint(package),
            {str(n):text for n,text in completed_sections.items() if n!=1},feedback])
        previous=getattr(project,'company_summary_receipt',{}) or {}
        if previous.get('input_sha256')==signature and previous.get('content') and not summary_errors(previous['content'],package):
            diagnostic['reused']=True
            return previous['content']
        answer = ""
        try:
            answer = normalize_company_summary(invoke(f"{self.report_kind}摘要 Agent", prompt, trace_emit))
            errors = summary_errors(answer, package)
            # A second free-form revision can introduce a different unsupported
            # relationship or absence claim. Rebuild from the same verified
            # cards as soon as the initial draft fails, then validate again.
        except CompanyFlowLimit:raise
        except Exception as exc:
            errors = [f"摘要模型调用失败：{type(exc).__name__}"]
        diagnostic["errors"] = errors
        if errors:
            diagnostic["model_errors"] = errors
            diagnostic["rebuilt_from_evidence"] = True
            rebuilt = fallback_company_summary(project, package)
            rebuilt_errors = summary_errors(rebuilt, package)
            diagnostic["errors"] = rebuilt_errors
            diagnostic["degraded"] = bool(rebuilt_errors)
            diagnostic["cited_evidence_ids"] = sorted(set(cited_evidence_ids(rebuilt)))
            emit(trace_emit, "report", self.trace_agent, "公司摘要已按原文事实重建", "模型草稿越界；" + "；".join(errors), status="fallback")
            return rebuilt
        project.company_summary_receipt={'input_sha256':signature,'content':answer,'package_fingerprint':package_fingerprint(package)}
        journal=getattr(project,'_company_flow_journal',None)
        if journal is not None:
            journal.data['summary_receipt']=project.company_summary_receipt
            journal.save()
        diagnostic["cited_evidence_ids"] = sorted(set(cited_evidence_ids(answer)))
        emit(trace_emit, "report", self.trace_agent, "公司摘要完成且通过结构与引用校验", f"chars={len(answer)}, delivered_cards={len(package['facts'])}", status="done")
        return answer

    def _write_section(self, project: Any, cleaned_json: str, risk_json: str, index: int, section_title: str, requirements: list[str], invoke: Callable[[str, str, Any], str], clip: Callable[[str, int], str], emit: Callable[..., None], trace_emit: Any) -> str:
        emit(trace_emit, "report", self.trace_agent, "章节写作启动", f"{index}/{len(self.outline)} {section_title}", section=section_title, status="running")
        try:
            fact_count = len(json.loads(cleaned_json or "{}").get("facts", []))
        except (TypeError, ValueError, json.JSONDecodeError):
            fact_count = 0
        try:
            package_payload = json.loads(cleaned_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            package_payload = {}
        density = str(package_payload.get("chapter_density") or company_section_density(package_payload.get("facts") or [], section_title))
        # Exactly one writing mode applies.  This prevents the old full chapter
        # skeleton from fighting the sparse-evidence prompt in the same call.
        if density == "rich":
            few_shot = "\n\n".join([COMPANY_FEW_SHOT, COMPANY_SECTION_FEW_SHOTS.get(index, "")]).strip()
            section_structure = COMPANY_SECTION_STRUCTURES.get(index, "")
        elif density == "normal":
            few_shot = ""
            section_structure = (
                f"只保留 `## {index}. {section_title}` 标题，并从本章任务中选择 2-4 个有证据支撑的小标题。"
                "可使用一张表格，但只列已有事实，不为填满结构补写字段；每个判断须紧邻 E-ID。"
            )
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

公司证据边界（强制执行）：
1. 仅可用 `evidence_scope=target_direct` 的事实证明目标公司的工商、融资、治理、经营、团队、司法监管、专项穿透或风险结论；行业/竞品材料仅可用于行业与竞争语境，必须明确其不是目标公司事实。
2. 搜索未命中、页面未提及、或专业平台未返回记录，只能写"在本次已检索公开来源中未形成可引用记录，待官方库/付费库/企业材料核验"；严禁写"没有""无""干净""不存在""风险为 0"。
3. 风险评分只能反映已获得且主体匹配的证据覆盖度与风险信号，不得把信息缺口计为低风险；信息缺口必须列入待核验项。
4. 不得把同名、同地区、同赛道、关联方或搜索结果页中的目标名称，当作目标主体证据。
5. 每项事实和由其形成的判断必须就近保留事实卡提供的 `[E-证据编号]`；不得自行编造证据编号。
6. 本章只有少量证据时，可以在证据明确支持的范围内作一至两条克制推演，但必须使用"基于现有证据判断/可能/仍需核验"等边界词，且推演后保留所依据的 E-ID。
7. 不要为了完成任务书逐项填充无证据内容。没有可写内容的子项直接省略；表格只有在存在至少两条可比较事实时才使用。
"""
        prompt += f"\n本章证据密度：`{density}`。必须仅按该密度对应的结构写作，不得引用其他密度模式的章节骨架。\n"
        if density == "sparse" and index <= 12:
            prompt += "本章属于有限证据章节：只写已证实事实和最多两条克制推演，不超过三个要点，不生成表格；所有待核验动作只放第14章。\n"
        answer = invoke(f"{self.report_kind}章节 Agent - {section_title}", prompt, trace_emit)
        if answer.strip():
            emit(trace_emit, "report", self.trace_agent, "章节写作完成", section_title, section=section_title, status="done")
            return answer.strip()
        return f"## {index}. {section_title}\n\n待核验。本章节需要后续补充核验：{'; '.join(requirements)}。"

    @staticmethod
    def _section_risk_json(risk_json: str, evidence_ids: set[str], *, include_followups: bool = False) -> str:
        """Return only company risk signals supported by this chapter's evidence."""
        try:
            parsed = json.loads(risk_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return "{}"
        if not isinstance(parsed, dict):
            return "{}"
        dimensions = []
        for item in parsed.get("dimensions") or []:
            if not isinstance(item, dict):
                continue
            item_ids = {str(value).strip() for value in item.get("evidence_ids") or [] if str(value).strip()}
            if item_ids & evidence_ids:
                dimensions.append(item)
        result: dict[str, Any] = {"dimensions": dimensions}
        if dimensions:
            result["overall_score"] = parsed.get("overall_score")
            result["risk_level"] = parsed.get("risk_level")
            result["key_risks"] = parsed.get("key_risks") or []
        if include_followups:
            result["unknowns"] = (parsed.get("unknowns") or [])[:12]
            result["recommended_followups"] = (parsed.get("recommended_followups") or [])[:12]
        return json.dumps(result, ensure_ascii=False)

    @classmethod
    def _ensure_section_evidence_markers(cls, report: str, section_evidence_ids: dict[int, list[str]]) -> str:
        """Preserve the actual chapter-to-evidence map even if an editor drops inline markers."""
        matches = list(REPORT_CHAPTER_HEADING_RE.finditer(report or ""))
        if not matches:
            return report
        chunks: list[str] = []
        cursor = 0
        for position, match in enumerate(matches):
            end = matches[position + 1].start() if position + 1 < len(matches) else len(report)
            chunks.append(report[cursor:match.start()])
            section = report[match.start():end].rstrip()
            index = int(match.group(1))
            expected = [value for value in section_evidence_ids.get(index, []) if value]
            missing = [value for value in expected if value not in section] if index not in {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12} else []
            if missing:
                section += "\n\n> 本章引用证据：" + "、".join(f"[{value}]" for value in missing)
            chunks.append(section + ("\n\n" if position + 1 < len(matches) else ""))
            cursor = end
        chunks.append(report[cursor:])
        return "".join(chunks)

    @classmethod
    def _lock_standard_outline(cls, report: str, fallback_sections: dict[int, str], *, outline=None) -> str:
        """Keep the company delivery structure identical to the standard sample."""
        expected_headings = {idx: title for idx, (title, _) in enumerate(outline or cls.outline, 1)}
        normalized = normalize_report_headings(report or "", expected_headings)
        matches = list(REPORT_CHAPTER_HEADING_RE.finditer(normalized))
        parsed: dict[int, str] = {}
        for position, match in enumerate(matches):
            index = int(match.group(1))
            if index not in expected_headings:
                continue
            finish = matches[position + 1].start() if position + 1 < len(matches) else len(normalized)
            parsed[index] = normalized[match.start():finish].strip()

        locked: list[str] = []
        for index, title in expected_headings.items():
            section = parsed.get(index) or fallback_sections.get(index) or f"## {index}. {title}\n\n待核验。"
            section = normalize_report_headings(section, {index: title}).strip()
            if not REPORT_CHAPTER_HEADING_RE.match(section):
                section = f"## {index}. {title}\n\n{section}"
            locked.append(section)
        return "\n\n".join(locked)

    def _edit(self, project: Any, draft: str, risk_json: str, invoke: Callable[[str, str, Any], str], clip: Callable[[str, int], str], emit: Callable[..., None], trace_emit: Any) -> str:
        emit(trace_emit, "report", self.trace_agent, "总编润色启动", f"sections={len(self.outline)}", status="running")
        prompt = build_editor_prompt(
            report_kind=self.report_kind,
            outline=self.outline,
            project=project,
            draft=draft,
            risk_json=risk_json,
            clip=clip,
        )
        prompt += f"""

目标公司报告专属总编要求：
1. 最终报告必须严格保留 14 节目录，标题和顺序如下：
{chr(10).join(f"{idx}. {title}" for idx, (title, _) in enumerate(self.outline, 1))}
2. 不得把每一节统一改写成"本章结论/事实梳理/分析判断/风险与待核验"四段式；每节必须保留该节自己的内容结构。
3. 第 10 节必须明确本项目需要定向穿透的具体方向；第 11 节必须按组织与管理、业务与运营、行业特殊风险三类展开。
4. 第 12 节必须给出评分或等级；第 13 节必须列信息点、来源/URL、工具、可信度、支持章节；第 14 节必须按高/中/低优先级排序。
5. 对无证据内容保持克制，正文只写"待核验"，并统一沉淀到"集中式待核验清单"；不要编造访谈、财务、客户、供应商、司法负面或经营数据。
"""
        answer = invoke(f"{self.report_kind}总编 Agent", prompt, trace_emit)
        return answer.strip() or draft

    @staticmethod
    def _split_batch_sections(text: str, start: int, end: int) -> dict[int, str] | None:
        """Return a batch only when every requested top-level section survived."""
        matches = list(REPORT_CHAPTER_HEADING_RE.finditer(text or ""))
        if not matches:
            return None
        parsed: dict[int, str] = {}
        for position, match in enumerate(matches):
            index = int(match.group(1))
            if index < start or index > end:
                continue
            finish = matches[position + 1].start() if position + 1 < len(matches) else len(text)
            parsed[index] = text[match.start():finish].strip()
        return parsed if all(index in parsed for index in range(start, end + 1)) else None

    def _edit_batched(
        self,
        project: Any,
        sections: list[str],
        section_evidence_ids: dict[int, list[str]],
        invoke: Callable[[str, str, Any], str],
        emit: Callable[..., None],
        trace_emit: Any,
    ) -> str:
        """Use small editor calls instead of one timeout-prone full rewrite.

        The editor is deliberately not asked to touch the deterministic source
        index and verification-plan chapters.  If one batch fails, its original
        section drafts are retained rather than failing the entire report.
        """
        by_index = {index: value for index, value in enumerate(sections, 1)}
        # Build the expected chapter headings dict once for heading normalisation
        # before _split_batch_sections.  This prevents the batch editor's LLM
        # heading format variations from causing unnecessary fallback.
        expected_headings = {idx: title for idx, (title, _) in enumerate(self.outline, 1)}
        # Two chapters per request keeps the editor below the provider's
        # practical response-time limit.  This is company-only and preserves
        # a failed batch's original chapter drafts.
        agents=getattr(project,'_company_chapter_agents',{}) or {}
        batches=([(n,n) for n in range(1,13)] if agents else [(1,2),(3,4),(5,6),(7,8),(9,10),(11,12)])
        for start, end in batches:
            if not any(section_evidence_ids.get(index) for index in range(start, end + 1)):
                continue
            original = "\n\n".join(by_index[index] for index in range(start, end + 1) if index in by_index)
            if not original.strip():
                continue
            sparse_chapters = [
                index for index in range(start, end + 1)
                if len(section_evidence_ids.get(index, [])) < 3
            ]
            emit(trace_emit, "report", self.trace_agent, "公司报告分批主编校订启动", f"chapters={start}-{end}", status="running")
            prompt = f"""
你是目标公司桌面尽调报告的分批主编。只编辑第 {start} 至第 {end} 章；不要输出其他章节。

标题格式强制规则（违反将导致报告被拒收）：
- 每一章必须严格使用 "## 数字. 标题" 格式输出，例如 "## 5. 行业口碑、产品认可度与同业竞争地位研判"
- 禁止使用以下任何变体："# 数字."（单井号）、"### 数字."（三井号）、"## 数字："（冒号）、"## 数字 -"（破折号）、"## 数字)"（半角括号）、"## 数字）"（全角括号）
- 数字和标题之间用英文句点 "." 分隔
- 禁止修改章节标题文字；章节标题必须与原文完全一致
- 所有子标题（如 "### 3.1 xxx"）保持不变，不做规范化

保留每一章的顶级标题、事实边界和证据编号，不得编造访谈、财务、客户、供应商、司法或经营数据。
删除同一章内部或相邻章节的重复表述；证据不足时只写"待核验"，将具体动作留给第14章。
输出简洁、可交付的 Markdown。不要增加长来源清单或 URL。

证据密度规则：第 {', '.join(str(index) for index in sparse_chapters) if sparse_chapters else '无'} 章为有限证据章节。旧二级结构和 few-shot 在这些章节只能作为可选参考，必须删除无证据的二级/三级标题、表格和"本章待核验清单"；每章最多保留三个事实或有边界的推演要点。其他章节证据足够时可保留原有结构，但同样不得为了完整性填充空内容。

待校订内容：
{original[:8000]}
""".strip()
            prompt += """

再次核验：删除或改写任何将"本次公开检索未发现/未返回"写成"无、没有、合规干净、风险为0、确定不存在"的句子；保留"待官方库/企业材料核验"的证据边界。行业、竞品和关联方材料不得用于证明目标公司事实或风险评分。
"""
            try:
                call = agents[start].invoke if agents else None
                role=f"{self.report_kind}分批主编 Agent {start}-{end}"
                answer = call(invoke,role,prompt,trace_emit) if call else invoke(role,prompt,trace_emit)
            except Exception as exc:
                emit(trace_emit, "report", self.trace_agent, "公司报告分批主编校订失败，保留章节草稿", f"chapters={start}-{end} | {exc}", status="fallback")
                continue
            # Normalise heading format in the batch editor's output before
            # splitting.  LLMs can produce ``# N.``, ``## N:`` and other
            # variants even when explicitly instructed otherwise; this
            # prevents unnecessary fallback to the unedited drafts.
            answer = normalize_report_headings(answer, expected_headings)
            parsed = self._split_batch_sections(answer, start, end)
            if parsed is None:
                emit(trace_emit, "report", self.trace_agent, "公司报告分批主编返回不完整，保留章节草稿", f"chapters={start}-{end}", status="fallback")
                continue
            by_index.update(parsed)
            emit(trace_emit, "report", self.trace_agent, "公司报告分批主编校订完成", f"chapters={start}-{end}", status="done")
        return "\n\n".join(by_index[index] for index in range(1, len(sections) + 1) if index in by_index)
