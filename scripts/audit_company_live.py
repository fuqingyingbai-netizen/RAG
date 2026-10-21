"""Opt-in real company workflow in isolated storage, with retained QA evidence.

The research, cleaning and report methods are production implementations.
Instrumentation only records inputs/outputs and prevents shared knowledge writes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from urllib.parse import urlsplit
from collections import Counter
from io import StringIO
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--intake', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--deadline', required=True, help='Absolute ISO timestamp with timezone')
    parser.add_argument('--reuse-search-from', type=Path, help='Retained real provider responses and originals; missing requests remain live')
    parser.add_argument('--report-only', action='store_true', help='Requires retained run; freeze original sources and cleaned facts, regenerate production risk/report/export only')
    parser.add_argument('--reclean-retained', action='store_true', help='Requires completed retained run; freeze actual collected originals, execute the current production cleaner and risk/report/export without reusing old cleaned facts')
    parser.add_argument('--resume-interrupted', action='store_true', help='Resume an interrupted real collection from its retained provider receipts and SQLite sources; missing calls remain live, no completed-cleaning claim')
    parser.add_argument('--resume-collected', action='store_true', help='Resume a retained run stopped at the pre-clean professional-source gate; freeze its actual collected sources, then execute real cleaning/risk/report')
    parser.add_argument('--supplement-json', type=Path, help='Requires retained run; fetch explicitly listed known original URLs, retain prior corpus, clean changed inputs, regenerate report; no search replay')
    parser.add_argument('--max-new-search-calls', type=int, default=240, help='Bound additional provider calls in retained-input follow-up mode')
    args = parser.parse_args()
    if not args.live:
        parser.error('--live is required for paid external calls')
    if args.report_only and not args.reuse_search_from:
        parser.error('--report-only requires --reuse-search-from')
    if args.reclean_retained and (not args.reuse_search_from or args.report_only or args.resume_collected or args.supplement_json or args.resume_interrupted):
        parser.error('--reclean-retained requires --reuse-search-from and excludes other replay modes')
    if args.resume_interrupted and (not args.reuse_search_from or args.report_only or args.resume_collected or args.supplement_json):
        parser.error('--resume-interrupted requires --reuse-search-from and excludes frozen replay modes')
    if args.resume_collected and (not args.reuse_search_from or args.report_only or args.supplement_json):
        parser.error('--resume-collected requires --reuse-search-from and excludes report-only/supplement modes')
    if args.supplement_json and (not args.reuse_search_from or args.report_only):
        parser.error('--supplement-json requires --reuse-search-from and cannot be combined with --report-only')
    frozen_retrieval=bool(args.report_only or args.supplement_json or args.resume_collected or args.reclean_retained)
    deadline = datetime.fromisoformat(args.deadline).timestamp()
    if deadline - time.time() < 300:
        parser.error('Less than five minutes remain; no new run may start')
    run = args.output.resolve()
    run.mkdir(parents=True, exist_ok=False)
    def hard_stop():
        # API admission and workflow checkpoints normally stop three minutes
        # earlier. This is the absolute backstop for a stuck native parser.
        (run/'deadline-stop.json').write_text(json.dumps({'status':'deadline_stopped',
            'deadline':args.deadline,'note':'Committed SQLite rows and earlier snapshots retained; no new calls permitted.'}),encoding='utf-8')
        os._exit(124)
    budget_timer=threading.Timer(deadline-time.time(),hard_stop)
    budget_timer.daemon=True
    budget_timer.start()
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    overrides = {
        'DATABASE_URL': 'sqlite:///' + (run / 'run.sqlite').as_posix(),
        'RESEARCH_OBJECT_STORE': 'local', 'RESEARCH_LOCAL_STORE': str(run / 'objects'),
        'RESEARCH_LEGACY_RAG_ENABLED': 'false', 'WORKFLOW_RESUME_ENABLED': 'false',
        'LLM_TIMEOUT_SECONDS': '90', 'LLM_MAX_RETRIES': '0',
        'COMPANY_REPORT_EDITOR_TIMEOUT_SECONDS': '90', 'COMPANY_REPORT_EDITOR_MAX_RETRIES': '0',
        'STRUCTURED_SOURCE_TIMEOUT_SECONDS': '30',
    }
    if args.reuse_search_from:
        overrides['WORKFLOW_RESUME_ENABLED']='true'
    os.environ.update(overrides)
    secrets = [v for k, v in os.environ.items() if v and len(v) >= 12 and re.search('KEY|TOKEN|SECRET|PASSWORD', k.upper())]
    lock = threading.RLock()

    def safe(value):
        text = json.dumps(value, ensure_ascii=False, default=str)
        for secret in secrets:
            text = text.replace(secret, '[REDACTED]')
        # Document signatures and business selector parameters are locators,
        # not configured account credentials. Preserve them for traceability.
        text = re.sub(r'(?i)(api[_-]?key|secret)=([^\s&"<>]+)', r'\1=[REDACTED]', text)
        return json.loads(text)

    def write(name, value):
        with lock:
            target=run/name
            temporary=target.with_name(target.name+'.tmp')
            temporary.write_text(json.dumps(safe(value), ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(temporary,target)

    def append(name, value):
        with lock, (run / name).open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(safe(value), ensure_ascii=False) + '\n')

    def fingerprint():
        files = sorted((ROOT / 'backend').rglob('*.py')) + [Path(__file__)]
        return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}

    code = fingerprint()
    # Preserve the exact loaded source even if the parallel person session edits it.
    for name in code:
        dst = run / 'code' / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dst)
    write('code-start.json', {'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                             'hashes': code, 'status': subprocess.check_output(['git', 'status', '--short'], cwd=ROOT, text=True)})
    intake = json.loads(args.intake.read_text(encoding='utf-8-sig'))
    write('intake.json', intake)
    write('runtime.json', {'scope': 'known_original_url_supplement_with_incremental_cleaning' if args.supplement_json else 'frozen_real_originals_and_cleaned_facts_production_report_replay' if args.report_only else 'retained_real_search_and_originals_plus_live_missing_requests' if args.reuse_search_from else 'fresh_real_production_full_workflow',
                          'retained_run':str(args.reuse_search_from) if args.reuse_search_from else None,
                          'platform_scope':'retained real same-session receipts' if args.reuse_search_from else 'live configured platforms',
                          'max_new_search_calls':0 if frozen_retrieval else args.max_new_search_calls if args.reuse_search_from else None,
                          'started_at': datetime.now(timezone.utc).isoformat(),
                          'deadline': args.deadline, 'overrides': {k: v for k, v in overrides.items() if k != 'DATABASE_URL'},
                          'configured_search_engines': [k for k in ('TAVILY', 'SERPER', 'EXA', 'BOCHA', 'BRAVE', 'SERPAPI') if os.getenv(k + '_API_KEY')],
                          'configured_platforms': [k for k in ('QCC', 'TYC', 'XINIU') if os.getenv(k + '_API_KEY')],
                          'model': os.getenv('MODEL'), 'cleaning_mode': os.getenv('CLEANING_MODE'),
                          'cleaning_llm': os.getenv('CLEANING_LLM_ENABLED'),
                          'indexing': 'disabled_in_QA_harness_only',
                          'sources': 'retained current-session corpus plus explicit freshly fetched known originals' if args.supplement_json else 'frozen current-session real corpus' if args.report_only else 'retained current-session professional receipts; web collector reruns' if args.reuse_search_from else 'empty_project_no_historical_corpus'})
    if args.resume_collected:
        runtime=json.loads((run/'runtime.json').read_text(encoding='utf-8'))
        runtime.update(scope='resume_actual_collected_sources_after_preclean_gate_failure',
                       sources='Frozen actual collected originals; real cleaning/risk/report executes now; prior failed run remains unchanged')
        write('runtime.json',runtime)
    if args.reclean_retained:
        runtime=json.loads((run/'runtime.json').read_text(encoding='utf-8'))
        runtime.update(scope='frozen_actual_originals_current_production_reclean_risk_report_export',
                       sources='Frozen real collected originals; old cleaned facts are not used as cleaner output')
        write('runtime.json',runtime)
    if args.resume_interrupted:
        runtime=json.loads((run/'runtime.json').read_text(encoding='utf-8'))
        runtime.update(scope='interrupted_actual_collection_resume_with_live_missing_requests',
                       sources='Same-session interrupted real collection; retained receipts reused, missing requests live; current production cleaning executes from originals')
        write('runtime.json',runtime)

    import requests
    import httpx
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import report_knowledge
    from models import Base, ResearchProject, ResearchSource, ResearchArtifact, User
    from research_workflow import ResearchWorkflow, WorkflowPaused
    from web_search import web_search_provider
    from research_store import research_store
    from search_results import canonical_source_url

    retained_search={};ambiguous=set();retained_sources=[];retained_fetch={};new_search_calls=0
    previous_cleaned={};previous_intake={}
    if args.reuse_search_from:
        previous=args.reuse_search_from.resolve()
        if not (previous/'result.json').exists() and not args.resume_interrupted:
            raise ValueError('Retained run must have finished before starting a follow-up')
        previous_result=json.loads((previous/'result.json').read_text(encoding='utf-8')) if (previous/'result.json').exists() else {}
        if args.resume_interrupted:
            if previous_result.get('completed') or (previous/'cleaned_facts.json').exists() or not (previous/'run.sqlite').exists():
                raise ValueError('Interrupted collection resume requires actual SQLite collection, without completed output or prior cleaned facts')
            write('interrupted-collection-inputs.json',{'scope':'Interrupted actual collection; no completion or prior cleaning claimed',
                'retained_run':str(previous),'prior_result':previous_result or None,
                'sqlite_sha256':hashlib.sha256((previous/'run.sqlite').read_bytes()).hexdigest(),
                'trace_sha256':hashlib.sha256((previous/'trace.jsonl').read_bytes()).hexdigest(),
                'prior_code':json.loads((previous/'code-start.json').read_text(encoding='utf-8'))})
        elif args.resume_collected:
            if (previous_result.get('completed') is not False or '专业数据库来源' not in str(previous_result.get('error') or '')
                    or (previous/'cleaned_facts.json').exists() or not (previous/'source-snapshots.json').exists()):
                raise ValueError('Collection resume requires the actual retained pre-clean professional-source gate failure and its source snapshot')
            write('preclean-resume-proof.json',{'previous_result':previous_result,
                  'previous_result_sha256':hashlib.sha256((previous/'result.json').read_bytes()).hexdigest(),
                  'no_previous_cleaned_facts':True,'scope':'Prior failed result is preserved; no new search or platform queries; genuine production cleaning follows'})
        elif not previous_result.get('completed'):
            raise ValueError('Retained run must have completed collection/cleaning before starting a follow-up')
        search_log=previous/'search-provider-results.jsonl'
        with (StringIO('') if frozen_retrieval else search_log.open(encoding='utf-8')) as stream:
            for line in stream:
                if not line.strip():continue
                try:batch=json.loads(line)
                except json.JSONDecodeError:
                    if not args.resume_interrupted:raise
                    append('interrupted-input-recovery.jsonl',{'kind':'incomplete_provider_receipt_excluded',
                        'line_sha256':hashlib.sha256(line.encode()).hexdigest()})
                    continue
                if 'results' not in batch:continue
                key=(batch['provider'],batch['query'])
                if key in retained_search:
                    ambiguous.add(key)
                else:retained_search[key]=batch['results']
        for key in ambiguous:retained_search.pop(key,None)
        if (previous/'source-snapshots.json').exists():
            retained_sources=json.loads((previous/'source-snapshots.json').read_text(encoding='utf-8'))
        elif args.resume_interrupted:
            with sqlite3.connect('file:'+(previous/'run.sqlite').as_posix()+'?mode=ro',uri=True) as checkpoint:
                checkpoint.row_factory=sqlite3.Row
                retained_sources=[dict(row) for row in checkpoint.execute('SELECT * FROM research_sources ORDER BY id')]
            for source in retained_sources:
                source['source_metadata']=json.loads(source.get('source_metadata') or '{}')
            write('interrupted-source-checkpoint.json',retained_sources)
        else:raise ValueError('Retained source snapshot is missing')
        previous_intake=json.loads((previous/'intake.json').read_text(encoding='utf-8'))
        if any(previous_intake.get(k)!=intake.get(k) for k in ('company_name','industry','as_of_date','focus_questions')):
            raise ValueError('Retained-input follow-up requires the same target, industry, cutoff and focus questions')
        previous_cleaned={} if args.resume_collected or args.reclean_retained or args.resume_interrupted else json.loads((previous/'cleaned_facts.json').read_text(encoding='utf-8'))
        if args.reclean_retained:
            write('reclean-retained-inputs.json',{'scope':'Same actual retained originals; current production cleaner executes from originals, without prior cleaned output reuse',
                'retained_run':str(previous),'source_count':len(retained_sources),
                'sources_sha256':hashlib.sha256((previous/'source-snapshots.json').read_bytes()).hexdigest(),
                'prior_cleaned_facts_sha256':hashlib.sha256((previous/'cleaned_facts.json').read_bytes()).hexdigest()})
        if args.report_only:
            write('frozen-report-inputs.json',{'scope':'Report-stage replay; no claim of a new full collection or cleaning run',
                'retained_run':str(previous),'source_count':len(retained_sources),
                'sources_sha256':hashlib.sha256((previous/'source-snapshots.json').read_bytes()).hexdigest(),
                'cleaned_facts_sha256':hashlib.sha256((previous/'cleaned_facts.json').read_bytes()).hexdigest()})
        for source in retained_sources:
            meta=source.get('source_metadata') or {}
            if meta.get('fetch_status')!='done' or not source.get('content'):continue
            key=canonical_source_url(source.get('url'))
            old=retained_fetch.get(key,{})
            if len(source['content'])>=len(old.get('content','')):
                retained_fetch[key]=source
        previous_objects=previous/'objects-before-cleanup'
        if not previous_objects.exists():previous_objects=previous/'objects'
        shutil.copytree(previous_objects,run/'objects',dirs_exist_ok=True)
        write('retained-input-manifest.json',{'provider_batches':len(retained_search),'ambiguous_batches_requeried':len(ambiguous),
              'retained_successful_originals':len(retained_fetch),'source_snapshot_sha256':hashlib.sha256((previous/'source-snapshots.json').read_bytes()).hexdigest() if (previous/'source-snapshots.json').exists() else None,
              'interrupted_sqlite_sha256':hashlib.sha256((previous/'run.sqlite').read_bytes()).hexdigest() if args.resume_interrupted else None,
              'search_log_sha256':hashlib.sha256(search_log.read_bytes()).hexdigest() if search_log.exists() else None,
              'note':'These are retained actual responses, not new online results or simulated fixtures.'})

    def admit_call():
        if time.time() > deadline - 180:
            raise WorkflowPaused('Absolute deadline approaching; external calls stopped')

    request_original = requests.Session.request
    def request(session, method, url, **kwargs):
        admit_call()
        started = time.monotonic()
        parts = urlsplit(str(url))
        payload = kwargs.get('json') or {}
        tool = (payload.get('params') or {}).get('name') if isinstance(payload, dict) else None
        row = {'at': datetime.now(timezone.utc).isoformat(), 'transport': 'requests', 'method': method,
               'host': parts.hostname, 'path': parts.path, 'rpc_tool': tool}
        try:
            result = request_original(session, method, url, **kwargs)
            row['status'] = result.status_code
            if isinstance(payload,dict) and 'messages' in payload:
                row['model']=payload.get('model')
                try:row['usage']=result.json().get('usage',{})
                except (ValueError,AttributeError):pass
            return result
        except BaseException as exc:
            row['error'] = type(exc).__name__
            raise
        finally:
            row['seconds'] = round(time.monotonic() - started, 3)
            append('http-calls.jsonl', row)
    requests.Session.request = request
    send_original = httpx.Client.send
    def send(client, request, **kwargs):
        admit_call()
        started = time.monotonic()
        row = {'at': datetime.now(timezone.utc).isoformat(), 'transport': 'httpx', 'method': request.method,
               'host': request.url.host, 'path': request.url.path}
        try:
            response = send_original(client, request, **kwargs)
            row['status'] = response.status_code
            if not kwargs.get('stream'):
                try:
                    body = response.json()
                    row['usage'] = body.get('usage', {})
                except (ValueError, AttributeError):
                    pass
            return response
        except BaseException as exc:
            row['error'] = type(exc).__name__
            raise
        finally:
            row['seconds'] = round(time.monotonic() - started, 3)
            append('http-calls.jsonl', row)
    httpx.Client.send = send
    report_knowledge.sync_report_safely = lambda *a, **kw: None
    research_store.mode, research_store.local_root = 'local', run / 'objects'
    if retained_fetch:
        fetch_original=web_search_provider.fetch_url
        def cached_fetch(url,*a,**kw):
            source=retained_fetch.get(canonical_source_url(url))
            if source:
                meta=source.get('source_metadata') or {}
                append('original-cache-uses.jsonl',{'url':url,'source_run':str(args.reuse_search_from),
                       'original_retrieved_at':source.get('created_at'), 'content_sha256':hashlib.sha256(source['content'].encode()).hexdigest()})
                return {'status':'done','content':source['content'],'fetch_attempt':'retained_original_cache',
                        'content_type':meta.get('fetched_content_type',''),'pages':meta.get('fetched_pages',0),
                        **{k:meta[k] for k in ('document_pages','document_extraction','images') if k in meta}}
            return fetch_original(url,*a,**kw)
        web_search_provider.fetch_url=cached_fetch

    for index, (provider, function) in enumerate(web_search_provider.engines):
        def observed(*a, _provider=provider, _function=function, **kw):
            nonlocal new_search_calls
            admit_call()
            started = time.monotonic()
            query=a[0] if a else kw.get('query')
            cached=retained_search.get((_provider,query))
            if cached is not None:
                append('search-provider-results.jsonl',{'provider':_provider,'query':query,'seconds':0,
                       'retrieval_mode':'retained_real_response','source_run':str(args.reuse_search_from),'results':cached})
                return cached
            if args.reuse_search_from:
                with lock:
                    if new_search_calls>=args.max_new_search_calls:
                        append('search-budget-skips.jsonl',{'provider':_provider,'query':query,'reason':'new_search_call_budget_exhausted'})
                        raise RuntimeError('New search call budget exhausted; retained responses remain available')
                    new_search_calls+=1
            try:
                rows = _function(*a, **kw)
                append('search-provider-results.jsonl', {'provider': _provider, 'query': a[0] if a else kw.get('query'),
                       'retrieval_mode':'live','seconds': round(time.monotonic()-started, 3), 'results': rows})
                return rows
            except BaseException as exc:
                append('search-provider-results.jsonl', {'provider': _provider, 'query': a[0] if a else kw.get('query'),
                       'seconds': round(time.monotonic()-started, 3), 'error': type(exc).__name__})
                raise
        web_search_provider.engines[index] = (provider, observed)

    workflow = ResearchWorkflow()
    started = time.monotonic()
    def emit(event):
        append('trace.jsonl', {'observed_at': datetime.now(timezone.utc).isoformat(), 'elapsed_seconds': round(time.monotonic()-started, 2), **event})
        write('state.json', {'elapsed_seconds': round(time.monotonic()-started, 2), 'event': event})
        if event.get('stage') != 'web_search' or '结束' in event.get('label', '') or '启动' in event.get('label', ''):
            print(json.dumps(safe({k: event[k] for k in ('stage', 'label', 'status', 'section') if k in event}), ensure_ascii=False), flush=True)

    def snapshot(project, label):
        # Keep original snapshots without serializing the complete large PDF
        # corpus several times in memory. A probe failure must not silently
        # substitute source snippets for the retained actual cleaned facts.
        target=run/'source-snapshots.json';temporary=run/'source-snapshots.json.tmp'
        try:
            with lock,temporary.open('w',encoding='utf-8') as stream:
                stream.write('[\n')
                for index,source in enumerate(project.sources):
                    if index:stream.write(',\n')
                    row={k:getattr(source,k) for k in ('id','source_type','title','url','object_key','content','summary','source_metadata','credibility_score')}
                    stream.write(json.dumps(safe(row),ensure_ascii=False))
                stream.write('\n]')
            os.replace(temporary,target)
        except Exception as exc:
            append('snapshot-failures.jsonl',{'stage':label,'error_type':type(exc).__name__,'error':str(exc)})
            raise
        write('project-state.json', {k: v for k, v in vars(project).items() if k.startswith('company_')})
        for key, value in vars(project).items():
            if key.startswith('company_') and key.endswith('_package'):
                write(key + '.json', value)
        append('snapshots.jsonl', {'stage': label, 'sources': len(project.sources), 'at': datetime.now(timezone.utc).isoformat()})

    clean_original = workflow.clean_sources
    def source_signature(source):
        def field(name,default=''):
            return source.get(name,default) if isinstance(source,dict) else getattr(source,name,default)
        meta=field('source_metadata',{}) or {}
        content={'title':field('title'),'content':field('content'),'type':field('source_type'),
            'document':canonical_source_url(field('url')),'document_pages':meta.get('document_pages'),
            'scope':{k:meta.get(k) for k in ('evidence_scope','diligence_entity','recall_entity','entity_validation',
                     'identity_status','content_kind','publication_date','published_date')}}
        return hashlib.sha256(json.dumps(content,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
    previous_by_url={canonical_source_url(s.get('url')):s for s in retained_sources}
    previous_signatures={url:source_signature(s) for url,s in previous_by_url.items()}
    def clean(project, *a, **kw):
        snapshot(project, 'before_clean')
        if args.report_only:
            value=json.dumps(previous_cleaned,ensure_ascii=False,indent=2)
            emit({'stage':'cleaning','label':'仅报告回放：保留本轮实际清洗事实','status':'skipped',
                  'detail':'No new source extraction or model cleaning; frozen real input corpus.'})
        elif not previous_cleaned:
            value = clean_original(project, *a, **kw)
        else:
            current={canonical_source_url(s.url):s for s in project.sources}
            unchanged={url for url,s in current.items() if previous_signatures.get(url)==source_signature(s)}
            changed=[s for s in project.sources if canonical_source_url(s.url) not in unchanged]
            reused=[]
            for fact in previous_cleaned.get('facts',[]):
                url=canonical_source_url(fact.get('source_url'))
                if url not in unchanged:continue
                source=current[url]
                row={**fact,'source_id':source.id,'source_url':source.url}
                if fact.get('source_url')!=source.url:row['retained_original_source_url']=fact.get('source_url')
                reused.append(row)
            context={k:getattr(project,k) for k in ('id','title','target_name','target_type','industry','description')}
            context.update({k:v for k,v in vars(project).items() if k.startswith('company_')})
            context.update(sources=changed,artifacts=[])
            subset=SimpleNamespace(**context)
            emit({'stage':'cleaning','label':'仅重清洗新增或原文改变的来源','status':'running',
                  'detail':f'changed_sources={len(changed)}, unchanged_sources={len(unchanged)}, retained_facts={len(reused)}'})
            # Extraction is incremental; entity/publisher identity is not.
            # A new English statistic still needs the retained issuer filing
            # that explicitly discloses its abbreviation. Classify it with
            # the complete real corpus on its first annotation, before noise
            # exclusions become durable. Explicit input exclusions stay intact.
            annotate_original=workflow._annotate_evidence_facts
            def contextual_annotation(scope,facts):
                return annotate_original(project if scope is subset else scope,facts)
            workflow._annotate_evidence_facts=contextual_annotation
            try:
                result=json.loads(clean_original(subset,*a,**kw))
            finally:
                workflow._annotate_evidence_facts=annotate_original
            new_fact_count=len(result.get('facts',[]))
            result['facts']=workflow._annotate_evidence_facts(project,workflow._dedupe_facts(reused+result.get('facts',[])))
            selected=workflow._select_cleaning_sources(project.sources,project=project)
            result['evidence_ledger']=workflow._build_evidence_ledger(project.sources,selected,target_type='company')
            for row in result['evidence_ledger']:
                if canonical_source_url(row.get('url')) in unchanged:row['cleaning_reused_from']=str(args.reuse_search_from)
            # Extraction gaps from a subset cannot be promoted to whole-corpus
            # absence claims after previously cleaned facts have been retained.
            result['incremental_input_only_gaps']=result.get('information_gaps',[])
            result['information_gaps']=list((kw.get('quality') or {}).get('information_gaps',[]))
            result['coverage_summary']={**result.get('coverage_summary',{}),'source_count':len(project.sources),
                'ledgered_source_count':len(selected),'deterministically_processed_source_count':len(selected),
                'deterministically_cleaned_source_count':sum(r['deterministically_cleaned'] for r in result['evidence_ledger']),
                'fact_module_counts':dict(Counter(f.get('module','unknown') for f in result['facts']))}
            manifest={'scope':'unchanged original bodies/pages retained; changed sources use the actual production cleaner; all merged cards re-annotated',
                'baseline':str(args.reuse_search_from),'unchanged_sources':len(unchanged),'changed_sources':len(changed),
                'identity_context_sources':len(project.sources),'identity_context_note':'First annotation of new facts uses full retained original context, including issuer-disclosed aliases; extraction/model context remains limited to changed sources.',
                'retained_fact_count':len(reused),'newly_cleaned_fact_count':new_fact_count,
                'baseline_facts_sha256':hashlib.sha256((args.reuse_search_from/'cleaned_facts.json').read_bytes()).hexdigest(),
                'unchanged_source_signatures':{u:previous_signatures[u] for u in sorted(unchanged)},
                'removed_source_urls':sorted(previous_by_url.keys()-current.keys())}
            result['incremental_cleaning']=manifest
            write('incremental-cleaning-manifest.json',manifest)
            value=json.dumps(result,ensure_ascii=False,indent=2)
        (run / 'cleaned-before-save.json').write_text(value, encoding='utf-8')
        snapshot(project, 'after_clean')
        return value
    workflow.clean_sources = clean
    if frozen_retrieval:
        def frozen_collection(*a,**kw):
            emit({'stage':'web_search','label':'保留本轮真实来源，跳过重复搜索','status':'skipped',
                  'detail':'Explicitly scoped retained-corpus validation; no new search or platform queries. Cleaning mode is recorded separately.'})
            return 0
        workflow.collect_web_sources=frozen_collection
        workflow.collect_structured_sources=frozen_collection
    if args.report_only or args.reclean_retained:
        workflow.enrich_ocr_sources=frozen_collection
        workflow.enrich_company_survey_charts=frozen_collection
    finalize_original = workflow._finalize_source_records
    def finalize(db, project, trace=None):
        snapshot(project, 'before_source_cleanup')
        if (run / 'objects').exists():
            shutil.copytree(run / 'objects', run / 'objects-before-cleanup', dirs_exist_ok=True)
        return finalize_original(db, project, trace)
    workflow._finalize_source_records = finalize
    save_original = workflow.save_artifact
    def save(db, project, kind, title, content, *a, **kw):
        artifact = save_original(db, project, kind, title, content, *a, **kw)
        if kind=='cleaned_facts' and args.report_only:
            prior_metadata=args.reuse_search_from/'cleaned_facts-metadata.json'
            original_meta=json.loads(prior_metadata.read_text(encoding='utf-8-sig')) if prior_metadata.exists() else {}
            current_meta=dict(artifact.artifact_metadata or {})
            current_version=current_meta.get('pipeline_version')
            current_meta.update(pipeline_version=original_meta.get('pipeline_version','retained_original_version_unknown'),
                frozen_replay={'retained_from':str(args.reuse_search_from),'cleaning_executed':False,
                    'current_cleaning_code_version':current_version})
            artifact.artifact_metadata=current_meta
            db.add(artifact);db.commit()
        (run / (kind + ('.md' if kind in {'desktop_report', 'proposal'} else '.json'))).write_text(content, encoding='utf-8')
        write(kind + '-metadata.json', artifact.artifact_metadata)
        return artifact
    workflow.save_artifact = save
    engine = create_engine(os.environ['DATABASE_URL'])
    Base.metadata.create_all(engine)
    result = {'acceptance_status': 'not_evaluated',
              'scope':'known_original_supplement_incremental_cleaning_production_report' if args.supplement_json else 'frozen_real_inputs_production_risk_report_export_replay' if args.report_only else 'retained_real_inputs_with_live_missing_requests_and_incremental_cleaning' if args.reuse_search_from else 'real_full_run_not_yet_independently_accepted'}
    if args.resume_collected:result['scope']='retained_actual_collection_after_preclean_failure_with_real_cleaning_and_report'
    if args.reclean_retained:result['scope']='retained_actual_originals_current_production_cleaning_risk_report_export'
    if args.resume_interrupted:result['scope']='interrupted_actual_collection_resumed_current_cleaning_risk_report_export'
    try:
        with Session(engine) as db:
            user = User(username='company-live-qa', password_hash='no-product-login')
            db.add(user); db.flush()
            project = ResearchProject(title=intake['company_name'] + '真实全链路回归', target_name=intake['company_name'],
                                      target_type='company', industry=intake.get('industry',''), created_by_id=user.id)
            db.add(project); db.commit()
            if args.reuse_search_from:
                for source in retained_sources:
                    if not frozen_retrieval and source.get('source_type')!='business_database':continue
                    fields={k:source[k] for k in ('source_type','title','url','object_key','content','summary','source_metadata','credibility_score') if k in source}
                    fields['title'],fields['source_metadata']=workflow._source_title_for_storage(fields.get('title',''),fields.get('source_metadata') or {})
                    if frozen_retrieval and source.get('id'):fields['id']=source['id']
                    db.add(ResearchSource(project_id=project.id,**fields))
                previous_state=json.loads((args.reuse_search_from/'project-state.json').read_text(encoding='utf-8'))
                for key in ('company_professional_platform_attempts','company_judicial_query_attempts'):
                    if key in previous_state:setattr(project,key,previous_state[key])
                db.commit();db.expire(project,['sources'])
                prior_audit=args.reuse_search_from/'professional_platform_audit.json'
                if prior_audit.exists():
                    workflow.save_artifact(db,project,'professional_platform_audit','复用本会话实际专业平台回执',
                        prior_audit.read_text(encoding='utf-8'),{'retained_from':str(args.reuse_search_from),'new_platform_requests':0})
            if args.supplement_json:
                rows=json.loads(args.supplement_json.read_text(encoding='utf-8-sig'))
                write('known-original-inputs.json',rows)
                known={canonical_source_url(s.url):s for s in project.sources}
                for item in rows:
                    url=str(item['url']);parsed=urlsplit(url)
                    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username:
                        raise ValueError('Known originals require an absolute public HTTP(S) locator')
                    existing=known.get(canonical_source_url(url))
                    if existing and (existing.source_metadata or {}).get('fetch_status')=='done' and existing.content.strip():
                        append('known-original-fetches.jsonl',{'url':url,'status':'retained_successful_original',
                            'content_sha256':hashlib.sha256(existing.content.encode()).hexdigest()})
                        continue
                    admit_call()
                    fetched=web_search_provider.fetch_url(url,allow_browser=True,document_profile='company')
                    content=str(fetched.get('content') or '')
                    if fetched.get('status')!='done' or not content.strip():
                        raise RuntimeError('Explicit original fetch failed; no substitute facts supplied')
                    metadata={'module':item['module'],'query':url,'provider':'known_original_direct_fetch',
                        'content_kind':'full_text','fetch_status':'done','fetch_attempt':fetched.get('fetch_attempt'),
                        'fetched_content_type':fetched.get('content_type'),'fetched_pages':fetched.get('pages'),
                        'retrieved_at':datetime.now(timezone.utc).isoformat(),
                        'discovery_basis':item.get('discovery_basis','explicit prior evidence locator'),
                        **{k:fetched[k] for k in ('document_pages','document_extraction','images') if k in fetched}}
                    from company_publishers import statistics_publisher_identity
                    metadata.update(statistics_publisher_identity(url,content))
                    title=item.get('title') or fetched.get('title') or url
                    quality=workflow.score_source({'title':title,'url':url,'content':content,'metadata':metadata},
                        module=item['module'],query=url,target=project.target_name)
                    metadata['quality']=quality
                    title,metadata=workflow._source_title_for_storage(title,metadata)
                    key='projects/'+str(project.id)+'/known-originals/'+hashlib.sha256(url.encode()).hexdigest()+'.txt'
                    research_store.put_text(key,content)
                    fields=dict(source_type=quality['source_type'],title=title,url=url,object_key=key,content=content,
                        summary='',source_metadata=metadata,credibility_score=quality['score'])
                    if existing:
                        for name,value in fields.items():setattr(existing,name,value)
                        source=existing
                    else:
                        source=ResearchSource(project_id=project.id,**fields);db.add(source)
                    db.commit();known[canonical_source_url(url)]=source;db.expire(project,['sources'])
                    append('known-original-fetches.jsonl',{'url':url,'status':'done','characters':len(content),
                        'content_sha256':hashlib.sha256(content.encode()).hexdigest(),'discovery_basis':metadata['discovery_basis']})
            try:
                artifacts, added = workflow.run_project(db, project, intake.get('search_queries', []), intake.get('focus_questions', []),
                     emit=emit, intake=intake, pause_requested=lambda: time.time() > deadline - 180)
                result.update(completed=True, project_status=project.status, sources_added=added,
                              artifacts=[a.artifact_type for a in artifacts])
                write('project-state.json', {k: v for k,v in vars(project).items() if k.startswith('company_')})
                for key, value in vars(project).items():
                    if key.startswith('company_') and key.endswith('_package'):
                        write(key+'.json', value)
            finally:
                # Preserve partial artifacts even if a quality gate rejects delivery.
                db.rollback()
                if len(project.sources) and not (run / 'source-snapshots.json').exists():
                    snapshot(project, 'partial_failure')
                for artifact in db.query(ResearchArtifact).filter_by(project_id=project.id):
                    (run / (artifact.artifact_type + ('.md' if artifact.artifact_type in {'desktop_report','proposal'} else '.json'))).write_text(artifact.content or '', encoding='utf-8')
                    write(artifact.artifact_type+'-metadata.json', artifact.artifact_metadata)
    except BaseException as exc:
        result.update(completed=False, error_type=type(exc).__name__, error=str(exc))
        (run / 'error.txt').write_text(json.dumps(safe(traceback.format_exc()), ensure_ascii=False), encoding='utf-8')
    finally:
        result['elapsed_seconds'] = round(time.monotonic()-started,2)
        result['new_search_provider_function_calls']=new_search_calls if args.reuse_search_from else None
        result['finished_at'] = datetime.now(timezone.utc).isoformat()
        write('result.json', result)
        after = fingerprint()
        write('code-end.json', {'hashes': after, 'changed_during_run': [k for k in sorted(set(code)|set(after)) if code.get(k) != after.get(k)]})
        budget_timer.cancel()
        print(json.dumps(safe(result), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
