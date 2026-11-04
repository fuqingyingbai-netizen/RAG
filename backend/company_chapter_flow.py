"""One company workflow: reuse -> bounded reading/search -> chapter -> report.

Source admission, literal validation, numeric tables and independent narrative
audits are reused from the existing company implementation. No embeddings are
created for task documents. Only this task's successful final delivery permits
temporary-state cleanup.
"""
from copy import deepcopy, copy
from datetime import datetime
import json
import time
import os
import threading
from types import SimpleNamespace

from company_chapters import VERSION as TEMPLATE_VERSION, chapter, outline, selected_chapters
from company_flow_state import FlowJournal, VERSION, fingerprint, CompanyFlowLimit
from company_reading import ReadingIndex, source_view, assess_questions
from company_requirements import bind_queries
from report_agents.company_chapter_agent import create_chapter_agents
from report_agents.company_report_agent import CompanyReportAgent
from report_agents.company_corpus import build_corpus_review, research_context, VERSION as CORPUS_VERSION
from report_agents.company_corpus_writer import collect_statements, render_compact_chapters
from report_agents.company_information_usage import build_information_usage, source_information_map, routing_scope
from report_agents.company_editorial import (build_editorial_package,digest_groups,apply_narrative_uses,
    comparable_conflicts,VERSION as EDITORIAL_VERSION,record_payload,fingerprint as editorial_fingerprint)
from report_agents.company_information_usage import VERSION as USAGE_VERSION
from report_agents.company_delivery_contract import fill_evidence_gaps,followup_chapter,split_sections
from report_agents.report_style import normalize_report_headings
from report_agents.company_evidence import source_body

PACKAGE_KEYS={2:'governance',3:'history',4:'operations',5:'reputation',6:'business',
    7:'management',8:'people',9:'judicial',10:'diligence',11:'risk_register',12:'assessment'}


class ChapterFlow:
    def __init__(self,workflow,db,project,intake,emit=None,pause_requested=None):
        from research_store import research_store
        from research_workflow import _emit
        self.workflow=workflow;self.db=db;self.project=project;self.intake=dict(intake)
        self.emit=emit;self.pause_requested=pause_requested;self._emit=_emit
        self.store=research_store
        scope={k:self.intake.get(k) for k in ('target_name','official_identifier','as_of_date',
            'industry','focus_modules','focus_questions','special_requirements','search_queries',
            'ai_search_enabled','required_chapters','scoring_required')}
        scope.update(template_version=TEMPLATE_VERSION,flow_version=VERSION)
        self.journal=FlowJournal(self.store,project.id,scope)
        self.reader=ReadingIndex();self.writer=CompanyReportAgent();self.writer.outline=outline()
        self.sections={};self.packages={};self.reads={};self.usages={};self.editorials={};self.coverage={}
        self.final_receipts=[]
        self.raw_invoke=lambda role,prompt,trace=None:workflow._invoke_company_report_editor(
            role,prompt,emit=emit,usage_sink=lambda value:self.journal.usage({**value,'stage':role,'input_sha256':fingerprint([role,prompt])}))
        from report_agents.company_transport import bounded_company_invoke
        transport=bounded_company_invoke(lambda role,prompt,trace=None:self.journal.invoke(self.raw_invoke,role,prompt,trace))
        self.model_concurrency=max(1,min(6,int(os.getenv('COMPANY_MODEL_CONCURRENCY','1'))))
        self.model_slots=threading.BoundedSemaphore(self.model_concurrency)
        def serial_invoke(role,prompt,trace=None):
            with self.model_slots:return transport(role,prompt,trace)
        serial_invoke._company_transport_guard=True
        serial_invoke._company_last_call=transport._company_last_call
        self.invoke=serial_invoke
        project.company_research_intake=dict(intake)
        project.company_template_version=TEMPLATE_VERSION
        project._company_flow_journal=self.journal
        project._company_flow_invoke=self.invoke
        project._company_chapter_agents=create_chapter_agents(project,_emit,emit)
        project.company_reading_mode='detailed'
        project.company_delivery_contract_required=True
        project.company_verified_chapters_required=True
        project.company_flow_version=VERSION
        project.company_professional_platform_attempts=[]
        project.company_judicial_query_attempts=[]

    def event(self,label,detail='',*,number=None,status='running',**extra):
        self._emit(self.emit,'report',chapter(number)['agent_id'] if number else 'company_chapter_flow',
            label,detail,status=status,chapter=number,flow_version=VERSION,**extra)

    def checkpoint(self,stage,number=None):
        self.journal.data['stage']=stage
        self.journal.data['current_chapter']=number
        self.journal.data['source_ids']=[s.id for s in self.project.sources or []]
        self.journal.data['sections']={str(n):text for n,text in self.sections.items()}
        self.journal.data['packages']=self.packages
        self.journal.data['reads']={str(n):r for n,r in self.reads.items()}
        self.journal.data['usages']={str(n):u for n,u in self.usages.items()}
        self.journal.data['editorials']={str(n):e for n,e in self.editorials.items()}
        self.journal.data['coverage']={str(n):c for n,c in self.coverage.items()}
        self.journal.data['platform_attempts']=self.project.company_professional_platform_attempts
        self.journal.data['judicial_attempts']=self.project.company_judicial_query_attempts
        self.journal.save()
        self.project.updated_at=datetime.utcnow();self.db.commit()
        if self.journal.data.get('budget_stop_reason'):
            raise CompanyFlowLimit('company_flow_'+self.journal.data['budget_stop_reason']+'_budget_exhausted')
        if self.pause_requested and self.pause_requested():
            from research_workflow import WorkflowPaused
            self.project.status='paused';self.journal.data['status']='paused'
            self.journal.save();self.db.commit()
            raise WorkflowPaused('任务已暂停；本章资料和写作结果已保存')

    def restore(self):
        if not self.journal.restore():return
        data=self.journal.data
        for name in ('sections','reads','usages','editorials','coverage'):
            setattr(self,name,{int(n):r for n,r in data.get(name,{}).items()})
        self.packages=data.get('packages',{})
        for name,value in self.packages.items():setattr(self.project,name,value)
        self.project.company_professional_platform_attempts=data.get('platform_attempts',[])
        self.project.company_judicial_query_attempts=data.get('judicial_attempts',[])
        self.project.company_question_coverage=self.coverage
        self.project.company_summary_receipt=data.get('summary_receipt',{})
        self.event('恢复逐章研究检查点','已保存内容仍按当前原件、模板和回执复验。',status='done')

    def chapter_invoke(self,number):
        agent=self.project._company_chapter_agents[number]
        def bound(role,prompt,trace=None):return agent.invoke(self.invoke,role,prompt,trace)
        bound._company_transport_guard=True
        bound._company_last_call=self.invoke._company_last_call
        return bound

    def publish_packages(self,view):
        for name,value in vars(view).items():
            if name.startswith('company_') and (name.endswith('_package') or name.endswith('_diagnostic')):
                if name.endswith('_package') and isinstance(value,dict):
                    from report_agents.company_time_context import annotate_time_context
                    annotate_time_context(value,list(self.project.sources or []),self.intake.get('as_of_date',''))
                self.packages[name]=deepcopy(value)
                setattr(self.project,name,value)

    def merge(self):
        facts=[];states={};receipts=[]
        for number,review in sorted(self.reads.items()):
            facts.extend(review.get('facts',[]));receipts.extend(review.get('review_receipts',[]))
            for sid,state in review.get('source_review',{}).items():
                def coverage_score(value):
                    return (value.get('reviewed_windows',0)/max(1,value.get('review_windows',0)),
                        -len(value.get('structural_gaps',[])),value.get('accepted_claims',0))
                reused=states.get(sid,{}).get('reused_by_chapters',[])+[number]
                if sid not in states or coverage_score(state)>coverage_score(states[sid]):states[sid]=deepcopy(state)
                states[sid]['reused_by_chapters']=reused
        facts=list({r.get('statement_id') or fingerprint(r):r for r in facts}.values())
        for sid,state in states.items():state['accepted_claims']=sum(r.get('source_id')==sid for r in facts)
        records=[r for n,u in sorted(self.usages.items()) for r in u.get('records',[])]
        records+=self.routed_records()
        unique={}
        for record in records:
            iid=record['information_id']
            if iid in unique and fingerprint(record_payload(unique[iid]))!=fingerprint(record_payload(record)):
                raise ValueError('conflicting_chapter_information_identifier')
            unique.setdefault(iid,record)
        records=list(unique.values())
        statements=[s for n,u in sorted(self.usages.items()) for s in u.get('_statements',[])]
        batches=[b for n,e in sorted(self.editorials.items()) for b in e.get('batches',[])]
        findings=[f for n,e in sorted(self.editorials.items()) for f in e.get('findings',[])]
        from report_agents.company_chapter_placements import accounted_ids
        accepted_ids=accounted_ids({'batches':batches})
        review={'version':CORPUS_VERSION,'target_name':self.project.target_name,
            'research_as_of':self.intake.get('as_of_date',''),'research_context':research_context(self.project),
            'facts':facts,'source_review':states,'review_receipts':receipts,
            'diagnostic':{'all_candidate_windows_reviewed':all(
                r.get('diagnostic',{}).get('all_candidate_windows_reviewed',False) and
                not any(b.get('error') for b in r.get('review_receipts',[])) for r in self.reads.values()),
                'reading_scope':'full_native_plan_with_explicit_window_acknowledgements',
                'accepted_claims':len(facts)}}
        usage={'version':USAGE_VERSION,'target_name':self.project.target_name,'records':records,
            'review_scope':routing_scope(self.project),
            'review_receipts':[r for u in self.usages.values() for r in u.get('review_receipts',[])],
            'diagnostic':{'pending_information_ids':[r['information_id'] for r in records
                if r.get('decision',{}).get('status') not in {'use','exclude'}]}}
        usage['source_map']=source_information_map(list(self.project.sources or []),review,usage)
        usable=[r for r in records if r.get('decision',{}).get('status')=='use']
        editorial={'version':EDITORIAL_VERSION,'target_name':self.project.target_name,
            'input_sha256':editorial_fingerprint([record_payload(r) for r in usable]),
            'batches':batches,'findings':findings,'conflicts':comparable_conflicts(records),
            'diagnostic':{'usable_information':len(usable),'narrative_information':len(accepted_ids),
                'pending_information_ids':[r['information_id'] for r in usable if r['information_id'] not in accepted_ids],
                'failed_batches':sum(not b.get('accepted') for b in batches),
                'review_incomplete_batches':sum(b.get('review_status')=='review_incomplete' for b in batches),
                'revision_required_batches':sum(b.get('review_status')=='revision_required' for b in batches),
                'accepted_batches':sum(bool(b.get('accepted')) for b in batches)}}
        self.project.company_source_review_package=review
        self.project.company_information_usage_package=usage
        self.project.company_editorial_package=editorial
        self.project.company_corpus_digest_package={'statements':statements,'groups':digest_groups(editorial),
            'diagnostic':editorial['diagnostic']}
        self.project.company_question_coverage=self.coverage
        return review,usage,editorial

    def selection(self,number,*,expanded=False):
        prior=self.reads.get(number,{}).get('reading_diagnostic',{})
        if prior.get('expanded_in_file'):
            terms=prior.get('gap_terms',[])
        else:
            coverage=self.coverage.get(number,{})
            terms=coverage.get('local_search_terms',[])+[str(field) for q in coverage.get('questions',[])
                if q.get('status') not in {'answered','not_applicable'} for field in q.get('missing_fields',[])]
        selection=self.reader.select(self.project,number,expanded=expanded,gap_terms=terms)
        shared=self.journal.data.get('shared_read_receipts',{})
        selection['input_sha256']=fingerprint([selection['input_sha256'],[record_payload(r) for r in self.routed_records(number)],
            sorted((key,fingerprint(r.get('response',{}))) for key,r in shared.items())])
        return selection

    def read(self,number,*,expanded=False):
        selection=self.selection(number,expanded=expanded)
        view=source_view(self.project,selection['sources'])
        view.company_reading_mode='detailed'
        local_invoke=self.invoke
        # Specialized tables are computed from native documents, not an LLM
        # paraphrase. Only current-chapter records enter its narrative prompt.
        section=self.sections.get(number,f'## {number}. '+chapter(number)['title'])
        old=self.reads.get(number,{})
        partial=self.journal.data.get('partial_reads',{}).get(str(number),[])
        shared=self.journal.data.get('shared_read_receipts',{})
        view.company_corpus_analysis_cache={**old,'review_receipts':list(shared.values())+old.get('review_receipts',[])+partial}
        def save_read_receipts(receipts):
            with self.journal.lock:
                shared=self.journal.data.setdefault('shared_read_receipts',{})
                changed=any(r.get('error') or r['input_sha256'] not in shared or
                    fingerprint(r.get('response'))!=fingerprint(shared[r['input_sha256']].get('response')) for r in receipts)
                if not changed:return  # Identical shared receipts are already durable.
                self.journal.data.setdefault('partial_reads',{})[str(number)]=deepcopy(receipts)
                for receipt in receipts:
                    if not receipt.get('error'):shared[receipt['input_sha256']]=deepcopy(receipt)
                self.journal.save()
        view.company_corpus_receipt_callback=save_read_receipts
        view.company_native_page_reader=self.read_original_page
        review=build_corpus_review(view,{'facts':[]},{number:section},local_invoke,self._emit,self.emit,
            prepared=selection['prepared'])
        review['reading_manifest']=selection['manifest']
        review['reading_diagnostic']=selection['diagnostic']
        # Successful shared supplements may change without changing the raw
        # source. Bind the completed read to those receipts for final refresh.
        review['input_sha256']=self.selection(number,expanded=expanded)['input_sha256']
        self.reads[number]=review
        # Rebuild the numeric/table package with any newly accepted native
        # passages. This is program parsing; it does not reread the document
        # through another generative model request.
        cleaned=json.dumps({'facts':review.get('facts',[])},ensure_ascii=False)
        section,package=self.writer.render_evidence_chapter(view,number,cleaned,local_invoke,self._emit,self.emit)
        self.publish_packages(view)
        self.sections[number]=section
        proofs=[r for r in review.get('facts',[]) if r.get('chapter')==number]+package.get('facts',[])+self.routed_records(number)
        previous_coverage=self.coverage.get(number,{})
        partial_coverage=self.journal.data.get('partial_coverage',{}).get(str(number),{})
        previous_coverage={**previous_coverage,'batches':previous_coverage.get('batches',[])+partial_coverage.get('batches',[])}
        def save_coverage(receipt):
            self.journal.data.setdefault('partial_coverage',{})[str(number)]=receipt
            self.journal.save()
        coverage=assess_questions(number,self.project.target_name,proofs,self.chapter_invoke(number),previous_coverage,receipt_callback=save_coverage)
        self.coverage[number]=coverage
        self.event('本章已有资料核对完成',number=number,status='done',
            selected_chars=selection['diagnostic']['selected_chars'],
            original_chars=selection['diagnostic']['source_chars'],
            question_states=[q['status'] for q in coverage['questions']],expanded=expanded)
        self.journal.data.setdefault('partial_reads',{}).pop(str(number),None)
        self.checkpoint('reading',number)
        return selection

    def collect(self,number,*,gap=False):
        if number not in selected_chapters(self.intake) or not self.intake.get('ai_search_enabled',True):return 0
        record=self.journal.data['chapters'].setdefault(str(number),{})
        flag='gap_search_done' if gap else 'initial_search_done'
        if record.get(flag):return 0
        local={**self.intake,'focus_modules':[chapter(number)['id']],
            'max_search_rounds':1,'search_queries':[],'_company_chapter_pass':True,
            '_company_query_cache':self.journal}
        full_requirements=getattr(self.project,'company_research_requirements',None)
        plan=self.workflow.plan_research(self.project,local)
        coverage=self.coverage.get(number,{})
        queries=coverage.get('follow_up_queries') or []
        if gap:
            queries=[{'module':chapter(number)['id'],'query':q['query'],'search_tier':'open_web',
                'gap_question_id':q['question_id']} for q in queries]
        else:
            queries=self.workflow._expand_search_queries(plan,local)
            if not any(c.get('initial_search_done') for c in self.journal.data['chapters'].values()):
                queries += [{'module':chapter(number)['id'],'query':q,'search_tier':'open_web'}
                    for q in self.intake.get('search_queries',[])]
        queries=bind_queries(queries,plan.get('company_requirements',[]))
        local['_company_chapter_query_items']=queries
        self.event('本章定向补查' if gap else '本章检索缺失原件',number=number,
            query_count=len(queries),question_ids=[q.get('gap_question_id') for q in queries])
        added=0
        failures=self.journal.data['metrics'].get('search_failures',0)
        audit_start=len(self.project.company_professional_platform_attempts)
        try:
            if not gap:
                added+=self.workflow.collect_structured_sources(self.db,self.project,local,emit=self.emit)
            if queries:
                added+=self.workflow.collect_web_sources(self.db,self.project,[],[],30,emit=self.emit,
                    plan=plan,intake=local,reuse_archived=False,pause_requested=self.pause_requested)
        finally:
            self.project.company_research_requirements=full_requirements
            self.retain_platform_sources(local)
        self.db.expire(self.project,['sources'])
        failed=(self.journal.data['metrics'].get('search_failures',0)>failures or
            any(a.get('status')=='failed' or (a.get('status')=='not_queried' and a.get('reason'))
                for a in self.project.company_professional_platform_attempts[audit_start:]))
        record[flag]=not failed
        record[flag+'_status']='retryable_transport_failure' if failed else 'finished'
        self.checkpoint('gap_search' if gap else 'initial_search',number)
        return added

    def read_original_page(self,source_id,page,missing_fields):
        from report_agents.company_page_context import read_page_context,page_input_fingerprint
        source=next((s for s in self.project.sources or [] if str(s.id)==str(source_id)),None)
        if source is None:return {'status':'unavailable','reason':'original_source_not_in_task','pixels_read':False}
        key=fingerprint(['company-page-context-v2',source_id,fingerprint(source_body(source)),source.source_metadata,
            page,missing_fields,page_input_fingerprint(source,page,self.store)])
        cached=self.journal.data.setdefault('page_context_receipts',{}).get(key)
        if cached and cached.get('status')=='transcribed':return deepcopy(cached)
        try:receipt=read_page_context(source,page,self.store)
        except Exception as exc:receipt={'status':'failed','exception_type':type(exc).__name__,'pixels_read':False,'reason':'original_page_ocr_failed'}
        self.journal.data['page_context_receipts'][key]=receipt;self.journal.save()
        return receipt

    def retain_platform_sources(self,intake):
        # Raw envelopes are the reading source, not the clipped display table.
        # Preserve even empty/failed responses, explicitly as collection gaps.
        for key in self.journal.data.get('platform_raw_records',{}):
            row=self.journal.cached('platform_raw_records',key)
            title='平台原始返回-'+key
            self.workflow._save_structured_source(self.db,self.project,row['provider'],'raw_receipt',title,
                json.dumps(row['raw_payload'],ensure_ascii=False,indent=2),
                {'tool':row['tool'],'target':row['target'],'query':row['arguments'].get('searchKey') or row['arguments'].get('company_name') or row['arguments'].get('firm_name') or row['arguments'].get('query') or '',
                 'raw_arguments':row['arguments'],'retrieved_at':row['retrieved_at'],
                 'collection_failure':row['collection_failure'],'raw_receipt_sha256':key,
                 'company_platform_raw_response':row['raw_payload']},intake=intake,emit=self.emit)

    def routed_records(self,number=None):
        sources={str(s.id):s for s in self.project.sources or []}
        records=[]
        for value in self.journal.data.get('routed_information',{}).values():
            if value.get('routing_version')!=USAGE_VERSION:continue
            if any(sid not in sources or fingerprint(source_body(sources[sid]))!=digest
                    for sid,digest in value.get('source_bindings',{}).items()):continue
            row=value['record']
            if number is None or row['decision']['chapter']==number:records.append(deepcopy(row))
        return records

    def route_information(self,usage,number):
        sources={str(s.id):s for s in self.project.sources or []};outbound=[];own=[]
        for row in usage['records']:
            destination=row.get('decision',{}).get('chapter')
            if row.get('decision',{}).get('status')=='use' and destination!=number:
                if not isinstance(destination,int) or not 2<=destination<=11:
                    # Assessment is derived after substantive chapters, never
                    # a destination for otherwise unassigned primary evidence.
                    row['decision']={**row['decision'],'status':'pending_destination_clarification'}
                    own.append(row);continue
                bindings={str(proof['source_id']):fingerprint(source_body(sources[str(proof['source_id'])]))
                    for proof in row.get('provenance',[]) if str(proof.get('source_id')) in sources}
                if not bindings:
                    row['decision']={**row['decision'],'status':'pending_source_binding'};own.append(row);continue
                self.journal.data.setdefault('routed_information',{})[row['information_id']]={
                    'routing_version':USAGE_VERSION,'record':deepcopy(row),'source_bindings':bindings,'origin_chapter':number}
                outbound.append({'information_id':row['information_id'],'destination_chapter':destination,
                    'reason':row['decision'].get('relevance'),'source_bindings':bindings})
            else:own.append(row)
        incoming=self.routed_records(number)
        usage['records']=list({r['information_id']:r for r in own+incoming}.values())
        usage['outbound_routes']=outbound
        usage.setdefault('diagnostic',{})['pending_information_ids']=[r['information_id'] for r in usage['records']
            if r.get('decision',{}).get('status') not in {'use','exclude'}]
        return usage

    def write(self,number):
        view=source_view(self.project,self.project.sources or [])
        for name in PACKAGE_KEYS.values():
            if name!=PACKAGE_KEYS[number]:setattr(view,'company_'+name+'_package',{})
        review=self.reads[number]
        statements=[r for r in collect_statements(view,review) if r['chapter']==number]
        for row in statements:
            row['context']={**row.get('context',{}),'chapter_question_owner':number}
        digest={'statements':statements,'groups':[],'diagnostic':{}}
        local_invoke=self.chapter_invoke(number)
        usage=build_information_usage(digest,{number:self.sections[number]},outline(),self.project.target_name,
            local_invoke,previous=self.usages.get(number),review_scope=routing_scope(self.project),
            emit=self._emit,trace_emit=self.emit,workers=self.model_concurrency)
        usage=self.route_information(usage,number)
        self.usages[number]=usage
        self.checkpoint('information_routed',number)
        partial=self.journal.data.get('partial_editorials',{}).get(str(number),[])
        previous={**self.editorials.get(number,{}),'version':EDITORIAL_VERSION,
            'target_name':self.project.target_name,'batches':self.editorials.get(number,{}).get('batches',[])+partial}
        def save_editorial(receipt):
            self.journal.data.setdefault('partial_editorials',{}).setdefault(str(number),[]).append(deepcopy(receipt))
            self.journal.save()
        editorial=build_editorial_package(usage,outline(),self.project.target_name,self.invoke,
            previous=previous,emit=self._emit,trace_emit=self.emit,receipt_callback=save_editorial,
            chapter_agents=self.project._company_chapter_agents)
        apply_narrative_uses(usage,editorial)
        usage['_statements']=statements
        self.usages[number]=usage;self.editorials[number]=editorial
        self.merge()
        from report_agents.company_chapter_placements import appendix_html
        self.project.company_chapter_appendix_html=appendix_html(self.project.company_information_usage_package,self.project.company_editorial_package)
        rendered=render_compact_chapters(self.project,{'groups':digest_groups(editorial)},outline(),
            {number:self.sections[number]})
        self.sections[number]=self.project._company_chapter_agents[number].execute(
            lambda:rendered[number],phase='chapter_narrative')
        row=self.journal.data['chapters'].setdefault(str(number),{})
        pending=list(dict.fromkeys(editorial['diagnostic']['pending_information_ids']+
            usage.get('diagnostic',{}).get('pending_information_ids',[])))
        review_pending=bool(pending or self.coverage.get(number,{}).get('errors') or
            any(b.get('error') for b in review.get('review_receipts',[])) or
            not review.get('diagnostic',{}).get('all_candidate_windows_reviewed') or
            any(st.get('structural_gaps') or st.get('unread_ranges') for st in review.get('source_review',{}).values()))
        row.update(status='pending_review' if review_pending else
            'written_with_gaps' if not self.coverage.get(number,{}).get('complete') else 'written',
            input_sha256=self.reads[number]['input_sha256'],
            questions=self.coverage.get(number,{}).get('questions',[]),
            pending_information_ids=pending)
        self.event('本章草稿与待复核结果已保存' if review_pending else '本章正文与核验结果已保存',
            number=number,status='warning' if review_pending else 'done',
            chapter_status=row['status'],body_chars=len(self.sections[number]))
        self.checkpoint('chapter_written',number)

    def run_chapter(self,number,*,local_only=False):
        expanded=self.reads.get(number,{}).get('reading_diagnostic',{}).get('expanded_in_file',False)
        current=self.selection(number,expanded=expanded)
        saved=self.journal.data['chapters'].get(str(number),{})
        search_settled=(self.coverage.get(number,{}).get('complete') or local_only or
            number not in selected_chapters(self.intake) or not self.intake.get('ai_search_enabled',True) or
            (saved.get('initial_search_done') and saved.get('gap_search_done')))
        # Reuse requires both unchanged source inputs and revalidated narrative
        # receipts, never just a green status string.
        if (search_settled and saved.get('input_sha256')==current['input_sha256'] and number in self.editorials
                and self.reads.get(number,{}).get('diagnostic',{}).get('all_candidate_windows_reviewed') is True
                and not any(b.get('error') for b in self.reads.get(number,{}).get('review_receipts',[]))
                and not any(st.get('structural_gaps') or st.get('unread_ranges') for st in self.reads.get(number,{}).get('source_review',{}).values())
                and not self.coverage.get(number,{}).get('errors')
                and not self.usages[number].get('diagnostic',{}).get('pending_information_ids')
                and not self.editorials[number].get('diagnostic',{}).get('pending_information_ids')):
            from report_agents.company_editorial import package_errors
            records=[r for r in self.usages[number].get('records',[]) if r.get('decision',{}).get('status')=='use']
            if not package_errors(self.editorials[number],records,self.project.target_name):
                self.event('复用已核本章正文',number=number,status='done');return
        self.project.status='report_generating'
        self.event('开始本章：先核对本地资料',number=number)
        self.read(number,expanded=expanded)
        if not expanded and (not self.coverage[number]['complete'] or self.reads[number].get('reading_diagnostic',{}).get('unread_ranges')):
            self.event('本章执行一次文件内补读',number=number)
            self.read(number,expanded=True)
        if not local_only and not self.coverage[number]['complete']:
            added=self.collect(number)
            if added:self.read(number,expanded=True)
            if not self.coverage[number]['complete']:
                added=self.collect(number,gap=True)
                if added:self.read(number,expanded=True)
        if not self.coverage[number]['complete']:
            self.event('本章保留未解决问题',number=number,status='warning',
                stop_reason='bounded_search_finished_or_no_new_proof',
                questions=self.coverage[number]['questions'])
        self.write(number)

    def finalize(self):
        # New evidence can revise earlier chapters. Refresh only changed native
        # dependencies; this final sweep performs no additional external search.
        for number in range(2,12):
            old=self.journal.data['chapters'].get(str(number),{})
            expanded=self.reads.get(number,{}).get('reading_diagnostic',{}).get('expanded_in_file',False)
            now=self.selection(number,expanded=expanded)
            if old.get('input_sha256')!=now['input_sha256']:
                self.event('后续原件影响前章，定向复核',number=number)
                self.run_chapter(number,local_only=True)
        self.merge()
        from report_agents.company_chapter_placements import appendix_html
        self.project.company_chapter_appendix_html=appendix_html(self.project.company_information_usage_package,self.project.company_editorial_package)
        self.event('汇总综合评估与最终摘要')
        # Assessment is deterministic over already retained company proofs;
        # it does not open another full-document generative reading pass.
        view=source_view(self.project,self.project.sources or [])
        text,_=self.writer.render_evidence_chapter(view,12,json.dumps({'facts':self.project.company_source_review_package['facts']},
            ensure_ascii=False),self.chapter_invoke(12),self._emit,self.emit)
        self.publish_packages(view);self.sections[12]=text
        self.sections[1]=self.writer._write_summary(self.project,'{}',self.sections,self.invoke,self._emit,self.emit)
        self.sections[13]='## 13. '+chapter(13)['title']+'\n\n来源索引由本报告实际引用生成。'
        self.sections[14]=self.project._company_chapter_agents[14].execute(
            lambda:followup_chapter(self.project,outline()),phase='followup')
        self.sections=fill_evidence_gaps(self.sections,self.project.company_editorial_package,outline(),
            usage=self.project.company_information_usage_package)
        report='\n\n'.join(normalize_report_headings(self.sections[n],{n:chapter(n)['title']}) for n in range(1,15))
        report=self.workflow._append_professional_evidence_assets(self.project,report,'{}',emit=self.emit)
        report=self.workflow._append_report_evidence_index(self.project,report,'{}',emit=self.emit)
        report,metadata=self.workflow._prepare_company_delivery(self.project,report,emit=self.emit)
        # Final review may repair accepted batches. Persist those actual receipts,
        # so resume does not restore the pre-repair narrative over the final one.
        final_editorial=self.project.company_editorial_package
        for number in self.editorials:
            own=self.editorials[number]
            for key in ('batches','findings'):
                own[key]=[deepcopy(row) for row in final_editorial.get(key,[]) if row.get('chapter')==number]
            usable=[r for r in self.usages[number].get('records',[]) if r.get('decision',{}).get('status')=='use']
            own['input_sha256']=editorial_fingerprint([record_payload(r) for r in usable])
            from report_agents.company_chapter_placements import accounted_ids
            accepted=accounted_ids(own)
            own['diagnostic']['pending_information_ids']=[r['information_id'] for r in usable if r['information_id'] not in accepted]
        self.sections.update(split_sections(report))
        self.checkpoint('final_review')
        self.project.company_chapter_agents_metadata=[a.metadata() for a in self.project._company_chapter_agents.values()]
        from research_workflow import COMPANY_REPORT_VERSION
        metadata.update(report_pipeline_version=COMPANY_REPORT_VERSION,
            company_flow_version=VERSION,company_template_version=TEMPLATE_VERSION,
            company_question_coverage=deepcopy(self.coverage),
            company_flow_summary=self.summary(),company_summary_evidence=getattr(self.project,'company_summary_package',{}),
            company_summary_diagnostic=getattr(self.project,'company_summary_diagnostic',{}),
            company_source_review_evidence=self.project.company_source_review_package,
            company_professional_platform_attempts=self.project.company_professional_platform_attempts)
        for number,name in PACKAGE_KEYS.items():
            metadata['company_'+name+'_evidence']=getattr(self.project,'company_'+name+'_package',{})
            metadata['company_'+name+'_diagnostic']=getattr(self.project,'company_'+name+'_diagnostic',{})
        try:self.workflow._validate_delivery_report(self.project,report)
        except RuntimeError as exc:
            metadata.update(quality_warning=str(exc),delivery_status='review_draft')
            report=self.workflow._prepend_review_draft_notice(report,str(exc))
        else:metadata['delivery_status']='final_candidate'
        artifact=self.workflow.save_artifact(self.db,self.project,'desktop_report',self.project.title+' · 公司研究报告',report,metadata)
        # These are final evidence receipts, referenced by the report and its
        # download UI, rather than disposable original documents/query caches.
        for kind,attribute,label in (
                ('company_source_coverage','company_source_coverage_package','逐来源处理台账'),
                ('company_information_usage','company_information_usage_package','逐项信息使用与排除清单'),
                ('company_editorial','company_editorial_package','正文精编与语义验收'),
                ('company_corpus_digest','company_corpus_digest_package','章节原文与证据表')):
            package=getattr(self.project,attribute,{}) or {}
            if not package:continue
            receipt=self.workflow.save_artifact(self.db,self.project,kind,self.project.title+' · '+label,
                json.dumps(package,ensure_ascii=False),{'report_artifact_id':artifact.id,
                    'company_flow_version':VERSION,'summary':package.get('summary',package.get('diagnostic',{}))})
            artifact.artifact_metadata={**(artifact.artifact_metadata or {}),kind+'_artifact_id':receipt.id}
            self.final_receipts.append(receipt)
        appendix=getattr(self.project,'company_chapter_appendix_html','')
        if appendix:
            receipt=self.workflow.save_artifact(self.db,self.project,'company_evidence_annex',self.project.title+' · 章节证据附件',appendix,
                {'report_artifact_id':artifact.id,'company_flow_version':VERSION,'placement_scope':'chapter_writer_independently_reviewed',
                 'sha256':__import__('hashlib').sha256(appendix.encode()).hexdigest()})
            artifact.artifact_metadata={**(artifact.artifact_metadata or {}),'company_chapter_appendix_artifact_id':receipt.id}
            self.final_receipts.append(receipt)
        self.db.commit()
        self.journal.data['report_artifact_id']=artifact.id
        self.checkpoint('report_exported')
        return artifact

    def summary(self):
        self.journal.data['metrics']['elapsed_seconds']=round(time.monotonic()-self.journal.started,3)
        return {'version':VERSION,'run_id':self.journal.data['run_id'],
            'metrics':deepcopy(self.journal.data['metrics']),'limits':dict(self.journal.limits),
            'chapters':{n:{k:v for k,v in c.items() if k!='raw'} for n,c in self.journal.data['chapters'].items()},
            'token_usage_complete':self.journal.data['metrics']['reported_usage_calls']==self.journal.data['metrics']['model_calls'],
            'model_concurrency':self.model_concurrency,
            'embeddings_created':0,'parsed_source_versions':self.reader.parsed_sources,
            'reading_mode':'chapter_local_native_passages'}

    def run(self):
        before={s.id for s in self.project.sources or []}
        self.restore()
        try:
            if self.journal.data.get('status')=='cleanup_pending':
                artifact=self.workflow._latest_artifact(self.project,'desktop_report')
                if artifact and artifact.id==self.journal.data.get('report_artifact_id') and self.delivery_ready(artifact):
                    self.finish_cleanup(artifact)
                    return [artifact],0
                raise ValueError('cleanup_report_dependency_changed')
            self.journal.data['status']='running'
            self.intake=self.workflow.resolve_business_entity(self.project,self.intake,emit=self.emit)
            plan=self.workflow.plan_research(self.project,self.intake,emit=self.emit)
            self.journal.data['plan']=plan
            self.checkpoint('planning')
            for number in range(2,12):self.run_chapter(number)
            artifact=self.finalize()
            # Preserve the existing proposal deliverable. Its optional model
            # pass uses the same task budget, with a workflow-local adapter.
            proposal_workflow=copy(self.workflow)
            proposal_workflow._invoke=lambda role,prompt,emit=None,**kwargs:self.invoke(role,prompt)
            proposal=proposal_workflow.generate_proposal(self.project,artifact.content,'{}',emit=self.emit)
            proposal=self.workflow._normalize_proposal_placeholders(proposal)
            warning=self.workflow._proposal_quality_warning(proposal,target_type='company',project=self.project)
            if warning:proposal=self.workflow._fallback_company_proposal(self.project)
            proposal_artifact=self.workflow.save_artifact(self.db,self.project,'proposal',
                self.project.title+' · 项目建议书',proposal,
                {'company_flow_version':VERSION,'report_artifact_id':artifact.id,'requires_human_review':True})
            self.checkpoint('proposal_exported')
            meta=artifact.artifact_metadata or {}
            ready=self.delivery_ready(artifact)
            self.project.status='completed' if ready else 'diagnostic'
            self.journal.data['status']='cleanup_pending' if ready else 'review_required'
            artifact.artifact_metadata={**meta,'company_flow_summary':self.summary(),
                'temporary_materials_status':'cleanup_pending' if ready else 'retained_for_review'}
            self.journal.save();self.db.commit()
            if ready:
                self.finish_cleanup(artifact)
            else:self.event('报告已生成待复核稿，保留临时资料用于续跑',status='warning')
            return [artifact,proposal_artifact,*self.final_receipts],len({s.id for s in self.project.sources or []}-before)
        except Exception as exc:
            from research_workflow import WorkflowPaused
            self.db.rollback()
            self.project.status='paused' if isinstance(exc,(WorkflowPaused,CompanyFlowLimit)) else 'failed'
            self.journal.data['status']='budget_exhausted' if isinstance(exc,CompanyFlowLimit) else self.project.status
            self.journal.data['error_type']=type(exc).__name__
            self.journal.save();self.db.commit()
            raise

    @staticmethod
    def delivery_ready(artifact):
        meta=artifact.artifact_metadata or {}
        return bool((meta.get('company_delivery_contract') or {}).get('delivery_ready') is True
            and meta.get('delivery_status')=='final_candidate' and not meta.get('quality_warning'))

    def finish_cleanup(self,artifact):
        if not self.delivery_ready(artifact):raise ValueError('cleanup_before_validated_export')
        cleaned=self.workflow._finalize_source_records(self.db,self.project,self.emit)
        if cleaned:
            try:self.store.delete_prefix(self.journal.prefix)
            except Exception:cleaned=False
        artifact.artifact_metadata={**(artifact.artifact_metadata or {}),
            'temporary_materials_status':'cleared_after_success' if cleaned else 'cleanup_pending',
            'company_flow_summary':self.summary()}
        self.project.status='completed';self.db.commit()
        if cleaned:self.event('报告已成功生成，临时阅读资料已清理',status='done')
        else:
            self.journal.data['status']='cleanup_pending';self.journal.save()
            self.event('报告已生成，临时资料清理尚未完成',status='warning')


def run_company_chapters(workflow,db,project,intake,emit=None,pause_requested=None):
    from report_agents.company_text import company_matching_cache
    with company_matching_cache():
        return ChapterFlow(workflow,db,project,intake,emit,pause_requested).run()
