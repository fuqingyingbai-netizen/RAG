"""Re-execute the production post-writing checks on an archived auto draft.

No research batch is regenerated and no manual replacement text is supplied.
The corpus, preceding baseline and draft are hashed; all new calls are logged.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'scripts')]
from person_content_acceptance import accept_content,draft_rows
from person_evidence import generate_person_report,build_packages,split_sections,render_section,validate_model_claims,cited_ids,compact,preserve_cited_aliases
from person_material_review import presentation_facts,writing_input_for
from person_prose_budget import enforce_budget
from person_claim_repair import repair_source_findings
from person_semantic_review import review_analyses,repair_semantic_findings
from person_iteration import ChapterInvoker
from person_replay_state import checkpoint_literal_plan
from replay_person_chapters import generation_code_snapshot,retained_claims
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def material_checkpoint_origin_binding(checkpoint,checkpoint_path,previous_summary,previous_acceptance,folder):
    """Bind a prior review to its unchanged, authenticated automatic candidate.

    This authorizes restoring review state, never accepting its pending rows.
    Current source/semantic checks and full material fingerprints still run.
    """
    if previous_summary.get('automatic_checkpoint_sha256')==hashlib.sha256(checkpoint_path.read_bytes()).hexdigest():
        return 'same_initial_automatic_checkpoint'
    folder=folder.resolve();chapter=str(checkpoint['chapter'])
    assert previous_summary['sources_sha256']==checkpoint['sources_sha256'],'material_checkpoint_source_mismatch'
    assert previous_summary.get('code_unchanged_during_run') is True,'material_checkpoint_incomplete_code_provenance'
    assert Path(checkpoint['origin_inputs']).resolve()==folder/'chapter-model-inputs.jsonl','material_checkpoint_rebase_origin_mismatch'
    code_path=folder/'generation-code-snapshot.json'
    assert Path(checkpoint['origin_code_snapshot']).resolve()==code_path,'material_checkpoint_rebase_code_origin_mismatch'
    code_sha=hashlib.sha256(json.dumps(read(code_path),sort_keys=True).encode()).hexdigest()
    assert code_sha==previous_summary['generation_code_sha256']==checkpoint['origin_generation_code_sha256'],'material_checkpoint_rebase_code_mismatch'
    actual=previous_acceptance[chapter]['content_acceptance'].get('last_validated_candidate')
    assert actual is not None and actual==checkpoint['claims'],'material_checkpoint_rebase_candidate_mismatch'
    entry=next((json.loads(line) for line in (folder/'chapter-model-inputs.jsonl').read_text(encoding='utf-8').splitlines()
        if json.loads(line).get('input_sha256')==checkpoint['origin_input_sha256']),None)
    assert entry is not None,'material_checkpoint_rebase_request_missing'
    packet=json.loads(entry['prompt'].splitlines()[-1])
    assert packet.get('draft')==actual,'material_checkpoint_rebase_raw_candidate_mismatch'
    literal=lambda rows:[{k:r[k] for k in ('evidence_id','quote')} for r in rows]
    recorded=checkpoint_literal_plan(packet)
    prior_plan=read(folder/'contract.json')['chapters'][chapter].get('required_source_displays',[])
    assert recorded==literal(checkpoint['required_source_displays'])==literal(prior_plan),'material_checkpoint_rebase_literal_mismatch'
    return 'authenticated_last_validated_candidate_rebase'


def review_complete_candidate(package,research,initial,writing,invoke,stage,as_of_date=None):
    """Every source-valid current paragraph receives the semantic gate."""
    from person_conservation import remember_source_validated_candidate
    remember_source_validated_candidate(package,initial)
    before=[dict(c) for c in initial]
    eligible=[f for f in research if f.get('analysis_allowed')]
    reviewed,errors,audit=review_analyses(package['chapter'],package['title'],eligible,initial,invoke,
        stage=stage,as_of_date=as_of_date)
    return repair_semantic_findings(package['chapter'],package['title'],eligible,before,
        reviewed,errors,audit,{**package,'facts':research},writing,invoke,None,
        validate_model_claims,as_of_date=as_of_date)


def restore_source_valid_protection(package,baseline_prior,protected,research):
    """Retain each guard-valid immutable row; one rejected row cannot poison all."""
    restored,errors=validate_model_claims(json.dumps({'claims':[*baseline_prior,*protected]},ensure_ascii=False),
        {**package,'facts':research})
    package['restored_content_protected_prior']=draft_rows(restored)
    return {'protected_initial_requirements_restored':len(package['restored_content_protected_prior']),
        **({'protected_initial_requirement_guard_rejections':errors} if errors else {})}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('draft',type=Path);ap.add_argument('--baseline',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path);ap.add_argument('--chapters',type=int,nargs='+',required=True)
    ap.add_argument('--feedback-records',required=True,type=Path)
    ap.add_argument('--max-model-calls',type=int,default=16)
    ap.add_argument('--reuse-model-run',type=Path)
    ap.add_argument('--routing-audit',type=Path)
    ap.add_argument('--resume-auto-checkpoint',type=Path)
    ap.add_argument('--resume-material-audit',type=Path)
    ap.add_argument('--chapter-seed-run',action='append',default=[],metavar='CHAPTER=RUN',
        help='Use an authentic completed same-corpus report chapter and its state; no replacement prose.')
    ap.add_argument('--model',help='Explicit model for new calls; prior raw responses still require the exact model context.')
    args=ap.parse_args();assert set(args.chapters)<=set(range(2,13))
    start=time.monotonic();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    code=generation_code_snapshot();source_summary=read(args.draft/'summary.json');corpus=Path(source_summary['baseline'])
    prior_summary=read(args.baseline/'summary.json')
    source_bytes=(corpus/'source-snapshots.json').read_bytes()
    sha=hashlib.sha256(source_bytes).hexdigest()
    assert sha==prior_summary['sources_sha256']==source_summary['sources_sha256']
    audit=read(args.draft/'audit.json')
    original=(args.draft/'desktop_report.md').read_text(encoding='utf-8');sections=split_sections(original)
    previous_contract=read(args.draft/'contract.json')
    seed_packages={str(n):previous_contract['chapters'][str(n)] for n in range(2,13)}
    seed_provenance={}
    for spec in args.chapter_seed_run:
        number,folder=spec.split('=',1);n=int(number);assert 2<=n<=12
        folder=Path(folder).resolve();summary=read(folder/'summary.json')
        assert summary['sources_sha256']==sha and summary['code_unchanged_during_run'] is True,'chapter_seed_source_or_code_mismatch'
        body=(folder/'desktop_report.md').read_text(encoding='utf-8')
        sections[n]=split_sections(body)[n]
        audit['section_diagnostics'][str(n)]=read(folder/'audit.json')['section_diagnostics'][str(n)]
        seed_packages[str(n)]=read(folder/'contract.json')['chapters'][str(n)]
        seed_provenance[str(n)]={'run':str(folder),'report_sha256':hashlib.sha256(body.encode()).hexdigest(),
            'summary_sha256':hashlib.sha256((folder/'summary.json').read_bytes()).hexdigest()}
    prior_sections=split_sections((args.baseline/'desktop_report.md').read_text(encoding='utf-8'))
    intake,payload=[read(corpus/name) for name in ['intake.json','cleaned_facts.json']]
    sources=[SimpleNamespace(**s) for s in json.loads(source_bytes)]
    feedback=read(args.feedback_records);assert feedback['sources_sha256']==sha
    for record in feedback['records']:
        s=next(s for s in sources if s.url==record['source_url'])
        s.source_metadata={**s.source_metadata,'person_feedback_records':[*s.source_metadata.get('person_feedback_records',[]),record]}
    project=SimpleNamespace(title=intake['target_name'],target_name=intake['target_name'],target_type='person',sources=sources,
        person_research_intake=intake,person_platform_attempts=read(corpus/'summary.json')['provider_attempts'],person_retrieval_audit=read(corpus/'person_retrieval_audit.json'))
    contract=build_packages(payload,intake['target_name'],PERSON_REPORT_OUTLINE,intake,sources,project.person_platform_attempts)
    contract['chapters']={str(n):p for n,p in contract['chapters'].items()}
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    if args.model:os.environ.update(MODEL=args.model,PERSON_REPORT_SECTION_MODEL=args.model)
    os.environ.update(PERSON_REPORT_SECTION_TIMEOUT_SECONDS='180',PERSON_REPORT_SECTION_MAX_RETRIES='0',LLM_MAX_RETRIES='0')
    from research_workflow import ResearchWorkflow
    wf=ResearchWorkflow.__new__(ResearchWorkflow);wf._person_report_section_model=None
    secrets=[v for k,v in os.environ.items() if len(v)>=12 and any(t in k.upper() for t in ['KEY','TOKEN','SECRET','PASSWORD'])]
    def safe(data):
        text=json.dumps(data,ensure_ascii=False,default=str)
        for secret in secrets:text=text.replace(secret,'[REDACTED]')
        return json.loads(text)
    calls=[]
    def emit(event):
        with (out/'trace.jsonl').open('a',encoding='utf-8') as handle:handle.write(json.dumps(safe(event),ensure_ascii=False)+'\n')
    def bounded(role,prompt,emitter=None):
        if len(calls)>=args.max_model_calls:raise RuntimeError('postwrite_call_cap')
        event={'role':role,'status':'started','started_utc':datetime.now(timezone.utc).isoformat()};calls.append(event)
        began=time.monotonic()
        try:
            result=wf._invoke_person_report_section(role,prompt,emit);event.update(status='returned',output_chars=len(result));return result
        except Exception as exc:event.update(status='failed',exception_type=type(exc).__name__);raise
        finally:
            event['elapsed_seconds']=round(time.monotonic()-began,3)
            (out/'request-status.json').write_text(json.dumps(safe(calls),ensure_ascii=False,indent=2),encoding='utf-8')
    from person_model_transport import section_model_context
    model_context=section_model_context()
    invoke=ChapterInvoker(bounded,out,safe,rewrite=args.chapters,model_context=model_context,reuse=args.reuse_model_run,force_rewrite=False)
    from person_material_routing import review_unassigned,apply_routing
    routing=review_unassigned(contract,intake['target_name'],invoke,emit,previous=read(args.routing_audit) if args.routing_audit else None)
    apply_routing(contract,routing);project.person_material_routing_audit=routing
    from person_replay_state import restore_chapter_state
    state_restoration={}
    conflicts={eid for row in contract.get('conflicts',[]) for eid in row.get('evidence_ids',[])}
    for n in range(2,13):
        p=contract['chapters'][str(n)]
        preserve_cited_aliases(p,contract['facts'],cited_ids(sections[n]),conflicts)
        state_restoration[str(n)]=restore_chapter_state(p,seed_packages[str(n)],
            audit['section_diagnostics'][str(n)],retained_claims(sections[n]),contract['facts'],conflicts)
    (out/'routing-audit.json').write_text(json.dumps(safe(routing),ensure_ascii=False,indent=2),encoding='utf-8')
    checkpoint=read(args.resume_auto_checkpoint) if args.resume_auto_checkpoint else {}
    if checkpoint:
        assert checkpoint['sources_sha256']==sha and checkpoint['no_manual_replacement_text']
        assert checkpoint['feedback_sha256']==hashlib.sha256(args.feedback_records.read_bytes()).hexdigest()
        assert hashlib.sha256(json.dumps(checkpoint['claims'],ensure_ascii=False,sort_keys=True).encode()).hexdigest()==checkpoint['claims_sha256']
        origin=Path(checkpoint['origin_inputs']).resolve();assert origin.is_relative_to(ROOT/'work')
        original_entry=next(json.loads(line) for line in origin.read_text(encoding='utf-8').splitlines() if json.loads(line).get('input_sha256')==checkpoint['origin_input_sha256'])
        assert json.loads(original_entry['prompt'].splitlines()[-1])['draft']==checkpoint['claims']
        original_packet=json.loads(original_entry['prompt'].splitlines()[-1])
        assert checkpoint_literal_plan(original_packet)==[{k:r[k] for k in ('evidence_id','quote')} for r in checkpoint['required_source_displays']]
    material_checkpoint={};material_checkpoint_provenance={}
    if args.resume_material_audit:
        assert args.resume_auto_checkpoint,'material_checkpoint_requires_bound_automatic_draft'
        previous_summary=read(args.resume_material_audit.parent/'summary.json')
        assert previous_summary['sources_sha256']==sha,'material_checkpoint_source_mismatch'
        material_checkpoint=read(args.resume_material_audit)
        origin_binding=material_checkpoint_origin_binding(checkpoint,args.resume_auto_checkpoint,previous_summary,
            material_checkpoint,args.resume_material_audit.parent)
        material_checkpoint_provenance={'path':str(args.resume_material_audit.resolve()),
            'sha256':hashlib.sha256(args.resume_material_audit.read_bytes()).hexdigest(),
            'origin_binding':origin_binding,
            'origin_model_context':previous_summary['model_context'],
            'reuse_policy':'Completed structured decisions are revalidated against full source/draft/task/table/literal fingerprints; pending or changed contexts must be reviewed. These are prior reviewer decisions, not responses attributed to the current model.'}
    from person_cross_chapter_tables import attach_professional_table_references
    attach_professional_table_references(contract)
    results={};updated={}
    for n in args.chapters:
        old=retained_claims(sections[n]);prior=retained_claims(prior_sections[n]);baseline_prior=list(prior)
        resumed=bool(checkpoint and checkpoint['chapter']==n)
        if resumed:old=checkpoint['claims']
        if resumed and material_checkpoint:
            from person_conservation import checkpoint_requirements,key
            obligations,obligation_proof=checkpoint_requirements(checkpoint,
                material_checkpoint[str(n)]['content_acceptance'],material_checkpoint_provenance['origin_binding'])
            if obligation_proof:
                known={key(r) for r in prior}
                for row in obligations:
                    if key(row) not in known:
                        prior.append(row);known.add(key(row))
                material_checkpoint_provenance['conserved_prior_requirements_restored']=obligation_proof
        p=contract['chapters'][str(n)]
        preserve_cited_aliases(p,contract['facts'],{eid for c in old+prior for eid in c['evidence_ids']},{eid for row in contract.get('conflicts',[]) for eid in row.get('evidence_ids',[])})
        research=p.get('research_facts',p['facts']);p['writing_contract']='evidence_selection_v2'
        if resumed:
            from person_records import personal_analysis_allowed
            admitted={f['evidence_id']:f for f in contract['facts']}
            conflicts={eid for row in contract.get('conflicts',[]) for eid in row.get('evidence_ids',[])}
            needed={eid for c in old+prior for eid in c['evidence_ids']}|{r['evidence_id'] for r in checkpoint['required_source_displays']}
            for eid in sorted(needed-{f['evidence_id'] for f in research}):
                assert eid in admitted
                f=admitted[eid];research.append({**f,'analysis_allowed':personal_analysis_allowed(f,conflicts),'temporal_conflict':eid in conflicts,
                    'automatic_checkpoint_material_pending_relevance_review':True})
            by_id={f['evidence_id']:f for f in research}
            assert all(r['evidence_id'] in by_id and r['quote'] in by_id[r['evidence_id']]['fact'] for r in checkpoint['required_source_displays'])
            p['required_source_displays']=checkpoint['required_source_displays']
            p['literal_material_display_proposed']=checkpoint['literal_material_display_proposed']
        if str(n) in material_checkpoint:
            previous_acceptance=material_checkpoint[str(n)]['content_acceptance']
            if previous_acceptance.get('last_validated_candidate') is not None:
                assert previous_acceptance['last_validated_candidate']==old,'material_checkpoint_candidate_mismatch'
                binding='explicit_last_validated_candidate'
            else:
                # Older successful audits did not persist this checkpoint
                # field. Bind to their actual rendered prose and citations;
                # never derive or modify report text to make it fit.
                from person_content_acceptance import same_source_bound_draft
                prior_report_path=args.resume_material_audit.parent/'desktop_report.md'
                prior_report=prior_report_path.read_text(encoding='utf-8')
                observed=retained_claims(split_sections(prior_report).get(n,''))
                assert same_source_bound_draft(observed,old),'material_checkpoint_rendered_candidate_mismatch'
                binding='actual_prior_rendered_prose_and_citations'
                material_checkpoint_provenance['prior_rendered_report_sha256']=hashlib.sha256(prior_report_path.read_bytes()).hexdigest()
            material_checkpoint_provenance.setdefault('candidate_bindings',{})[str(n)]=binding
            prior_material=previous_acceptance.get('material_diagnosis',{})
            prior_contract_path=args.resume_material_audit.parent/'contract.json'
            if prior_contract_path.exists() and (prior_material.get('status')=='passed'
                    or material_checkpoint_provenance.get('origin_binding')=='authenticated_last_validated_candidate_rebase'):
                prior_package=read(prior_contract_path)['chapters'][str(n)]
                if 'required_source_displays' in prior_package:
                    from person_content_acceptance import restore_literal_plan_from_checkpoint
                    restored_plan=restore_literal_plan_from_checkpoint(p,prior_package)
                    material_checkpoint_provenance.setdefault('source_display_bindings',{})[str(n)]={
                        **restored_plan,'prior_contract_sha256':hashlib.sha256(prior_contract_path.read_bytes()).hexdigest(),
                        'prior_material_status':prior_material.get('status'),
                        'basis':'Actual prior literal state and same bound candidate; each literal rechecked against current admitted originals. Pending decisions remain pending.'}
            p['material_diagnosis_checkpoint']=prior_material
        prior_checked,prior_errors=validate_model_claims(json.dumps({'claims':prior},ensure_ascii=False),{**p,'facts':research})
        prior=draft_rows(prior_checked)
        if resumed and material_checkpoint:
            previous_content=material_checkpoint[str(n)]['content_acceptance']
            protected=previous_content.get('protected_initial_requirements')
            if isinstance(protected,list):
                material_checkpoint_provenance.update(restore_source_valid_protection(p,baseline_prior,protected,research))
        initial,errors=validate_model_claims(json.dumps({'claims':old},ensure_ascii=False),{**p,'facts':research})
        writing={**writing_input_for(p,research),'prior_draft_analyses_not_evidence':prior}
        role_repair={};semantic={};before_calls=len(calls)
        if not errors:
            initial,errors,semantic=review_complete_candidate(p,research,initial,writing,invoke,
                '自动候选续跑语义复核',contract.get('as_of_date'))
        if errors and not semantic:

            try:
                initial,errors,role_repair=repair_source_findings(json.dumps({'claims':old},ensure_ascii=False),{**p,'facts':research},
                    writing,initial,errors,invoke,None,validate_model_claims)
                if not errors and any(c.get('analysis') for c in initial):
                    initial,errors,semantic=review_complete_candidate(p,research,initial,writing,invoke,
                        '来源修订后完整语义复核',contract.get('as_of_date'))
            except Exception as exc:
                role_repair={'status':'request_failed','exception_type':type(exc).__name__}
                errors=['source_role_repair_unavailable']
        p['as_of_date']=contract.get('as_of_date')
        p['require_material_dispositions']=True
        if errors:
            final=initial;content={'status':'pending_source_or_semantic_validation','issues':errors,'requests':0}
        else:
            final,errors,content=accept_content(p,initial,prior,writing,invoke,None,validate_model_claims)
        final,budget=enforce_budget(final,n)
        if budget['status']!='within_budget':errors=list(dict.fromkeys([*errors,'analysis_length_budget_exceeded']))
        passed=not errors and content['status'].startswith('passed') and not any(c.get('review_analysis') for c in final)
        status=('passed_after_targeted_repair' if role_repair.get('status') or content['status']=='passed_after_targeted_repair'
                else 'passed_without_targeted_repair') if passed else 'pending_review'
        d=dict(audit['section_diagnostics'][str(n)])
        d.update(content_acceptance=content,source_role_repair=role_repair,source_role_semantic_review=semantic,
            prose_budget=budget,postwrite_acceptance_status=status,
            accepted_analysis_count=sum(bool(c.get('analysis')) for c in final),pending_review_analysis_count=sum(bool(c.get('review_analysis')) for c in final),
            unresolved_validation_rejections=errors,validation_rejections=errors,
            model_calls=d.get('model_calls',0)+len(calls)-before_calls,
            retained_previous_draft_and_research=True,prior_baseline_guard_rejections=prior_errors)
        if not passed:p['information_gaps'].append('本章自动写后事项验收尚未通过，具体缺失或待复核事项见内容验收台账。')
        p['display_facts']=presentation_facts(p,final)
        if p['quotation_budget'].get('required_undisplayed_evidence_ids'):
            errors=list(dict.fromkeys([*errors,'required_source_display_over_budget']))
            passed=False;status='pending_review';content['status']='pending_source_display_budget'
            d.update(postwrite_acceptance_status=status,unresolved_validation_rejections=errors,validation_rejections=errors)
        p['prior_originals']={}
        for fact in p['display_facts']:
            previous=next((j for j in range(2,n) if compact(fact['fact']) in compact('\n'.join(
                line[2:] for line in sections[j].splitlines() if line.startswith('> ')))),None)
            if previous:p['prior_originals'][fact['evidence_id']]={'chapter':previous,'evidence_id':fact['evidence_id']}
        d.update(quotation_budget=p['quotation_budget'],display_fact_count=len(p['display_facts']),
                 reused_original_reference_count=len(p['prior_originals']))
        sections[n]=render_section(p,final)
        updated[n]={'claims':final,'diagnostic':d}
        results[str(n)]={'status':status,'new_model_requests':len(calls)-before_calls,'prior_items':len(prior),
            'prior_guard_rejections':prior_errors,'content_acceptance':content,'role_repair':role_repair,'prose_budget':budget,
            'unresolved':errors,'no_manual_replacement_text':True,'resumed_automatic_checkpoint':resumed}
        (out/'acceptance-results.json').write_text(json.dumps(safe(results),ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'chapter':n,'status':status,'new_requests':len(calls)-before_calls,'chars':budget['published_chars']},ensure_ascii=False),flush=True)
    retained={n:{'text':sections[n],'selected_ids':[f['evidence_id'] for f in contract['chapters'][str(n)]['facts']],
        'diagnostic':updated[n]['diagnostic'] if n in updated else audit['section_diagnostics'][str(n)],
        'claims':updated[n]['claims'] if n in updated else retained_claims(sections[n]),
        'required_source_displays':contract['chapters'][str(n)].get('required_source_displays',[]),
        'literal_material_display_proposed':contract['chapters'][str(n)].get('literal_material_display_proposed',False),
        'research_facts':contract['chapters'][str(n)].get('research_facts',contract['chapters'][str(n)]['facts']),
        'gaps':contract['chapters'][str(n)]['information_gaps']} for n in range(2,13)}
    def forbidden(*a,**k):raise AssertionError('frozen_render_model_call')
    report=generate_person_report(project,json.dumps(payload,ensure_ascii=False),'{}',PERSON_REPORT_OUTLINE,forbidden,lambda *a,**k:None,retained_sections=retained)
    assert all(split_sections(report)[n]==sections[n] for n in range(2,13))
    assert source_bytes==(corpus/'source-snapshots.json').read_bytes()
    assert code==generation_code_snapshot(),'generation_code_changed_during_run'
    (out/'desktop_report.md').write_text(report,encoding='utf-8')
    (out/'evidence-appendix.md').write_text(project.person_evidence_appendix,encoding='utf-8')
    for name,value in [('contract.json',project.person_evidence_contract),('audit.json',project.person_delivery_diagnostic),('generation-code-snapshot.json',code)]:
        (out/name).write_text(json.dumps(safe(value),ensure_ascii=False,indent=2),encoding='utf-8')
    summary={'baseline':str(corpus),'draft_run':str(args.draft.resolve()),'prior_run':str(args.baseline.resolve()),'sources_sha256':sha,
        'generation_code_sha256':hashlib.sha256(json.dumps(code,sort_keys=True).encode()).hexdigest(),'code_unchanged_during_run':True,
        'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope':'automatic_postwriting_acceptance_and_targeted_repair_on_archived_auto_drafts_no_manual_edits',
        'automatic_checkpoint_sha256':hashlib.sha256(args.resume_auto_checkpoint.read_bytes()).hexdigest() if args.resume_auto_checkpoint else None,
        'rewritten_chapters':args.chapters,'unchanged_body_chapters':[n for n in range(2,13) if n not in args.chapters],
        'model_requests':len(calls),'model_requests_returned':sum(c['status']=='returned' for c in calls),
        'model_requests_failed':sum(c['status']=='failed' for c in calls),'new_search_calls':0,'new_fetch_calls':0,'new_professional_calls':0,
        'exact_input_responses_reused':sum(e['status']=='exact_input_reused' for e in invoke.events),
        'restored_material_checkpoint':material_checkpoint_provenance,
        'chapter_state_restoration':state_restoration,'chapter_seed_provenance':seed_provenance,
        'actual_cost_available':False,'model_context':model_context,'elapsed_seconds':round(time.monotonic()-start,3),
        'results':{n:r['status'] for n,r in results.items()}}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
