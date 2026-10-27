"""Run the same source/semantic/material/content checks on every body chapter.

Each chapter commits an authentic report checkpoint before the next starts.
Failures are recorded, never converted to acceptance. This runner has no target
names or target-specific evidence IDs; the agent diagnoses any pending sweep.
"""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'scripts')]
from replay_person_chapters import generation_code_snapshot
from person_evidence import split_sections
from person_replay_state import checkpoint_literal_plan


def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')


def raw_cache(destination,origins):
    destination.mkdir(exist_ok=False)
    for name in ['chapter-model-inputs.jsonl','chapter-model-responses.jsonl']:
        rows=[]
        for origin in origins:
            path=origin/name
            if path.exists():rows.extend(path.read_text(encoding='utf-8').splitlines())
        # Keep the last occurrence of byte-identical log lines, preserving
        # the original order of distinct returned outcomes for the same key.
        rows=list(dict.fromkeys(reversed(rows)))[::-1]
        (destination/name).write_text('\n'.join(rows)+'\n',encoding='utf-8')
    write(destination/'provenance.json',{'origins':[str(p.resolve()) for p in origins],
        'policy':'Only authentic raw requests and returned responses; exact role/prompt/model/options; current validators rerun. No audit-based override or fabricated outcome.'})


def authentic_candidate(run,chapter,feedback,output):
    """Recover an actual material-input draft, with an audit only if fully bound."""
    # Zero-call chapters have no raw model candidate to recover. The
    # published body still goes through all current checks in the next run.
    if not (run/'chapter-model-inputs.jsonl').exists():return None,None
    accepted=read(run/'acceptance-results.json')[str(chapter)]
    # Keep the published result of completed chapters. Earlier raw candidates
    # may predate their final source/coverage repairs or even be empty.
    if accepted.get('status','').startswith('passed'):return None,None
    content=accepted['content_acceptance']
    last=content.get('last_validated_candidate')
    plan=read(run/'contract.json')['chapters'][str(chapter)].get('required_source_displays',[])
    literal=lambda rows:[{k:r[k] for k in ['evidence_id','quote']} for r in rows]
    matches=[]
    for line in (run/'chapter-model-inputs.jsonl').read_text(encoding='utf-8').splitlines():
        entry=json.loads(line)
        try:packet=json.loads(entry['prompt'].splitlines()[-1])
        except ValueError:continue
        if 'draft' not in packet or not ('source_display_quotes' in packet or any(
                isinstance(row,dict) and row.get('representation')=='literal_source_excerpt' for row in packet.get('tables',[]))):continue
        quotes=checkpoint_literal_plan(packet)
        bound=packet['draft']==last and quotes==literal(plan)
        matches.append((bound,entry,packet,quotes))
    if not matches:return None,None
    bound,entry,packet,quotes=next((row for row in reversed(matches) if row[0]),matches[-1])
    summary=read(run/'summary.json')
    checkpoint={'status':'automatic_candidate_pending_acceptance','chapter':chapter,'claims':packet['draft'],
        'required_source_displays':quotes,'literal_material_display_proposed':True,
        'sources_sha256':summary['sources_sha256'],'feedback_sha256':hashlib.sha256(feedback.read_bytes()).hexdigest(),
        'origin_inputs':str((run/'chapter-model-inputs.jsonl').resolve()),'origin_input_sha256':entry['input_sha256'],
        'origin_code_snapshot':str((run/'generation-code-snapshot.json').resolve()),
        'origin_generation_code_sha256':summary['generation_code_sha256'],'no_manual_replacement_text':True,
        'claims_sha256':hashlib.sha256(json.dumps(packet['draft'],ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
        'resume_reason':'Exact archived model material-review input; all current gates rerun. Audit rebound only for exact last-validated candidate and final literal state.'}
    write(output,checkpoint)
    return output,(run/'acceptance-results.json' if bound else None)


def permanent_provider_failure(value):
    if isinstance(value,dict):
        if value.get('failure_kind') in {'quota_exceeded','unauthorized','access_denied'}:return value['failure_kind']
        return next((found for v in value.values() if (found:=permanent_provider_failure(v))),None)
    if isinstance(value,list):return next((found for v in value if (found:=permanent_provider_failure(v))),None)


def prior_chapter_runs(current,workspace=ROOT):
    """Find actual per-chapter ancestors, even after later chapters completed."""
    current=current.resolve();sections=split_sections((current/'desktop_report.md').read_text(encoding='utf-8'))
    source_sha=read(current/'summary.json')['sources_sha256'];found={};visited=set();cursor=current
    while cursor not in visited and cursor.is_relative_to((workspace/'work').resolve()):
        visited.add(cursor);summary_path=cursor/'summary.json'
        if not summary_path.exists():break
        summary=read(summary_path)
        if summary.get('sources_sha256')!=source_sha or summary.get('code_unchanged_during_run') is not True:break
        audit=cursor/'acceptance-results.json'
        if audit.exists():
            previous_sections=split_sections((cursor/'desktop_report.md').read_text(encoding='utf-8'))
            for key in read(audit):
                n=int(key)
                if n not in found and 2<=n<=12 and sections.get(n)==previous_sections.get(n):found[n]=cursor
        parent=summary.get('draft_run')
        if not parent:break
        cursor=Path(parent).resolve()
    return found


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('draft',type=Path);ap.add_argument('--baseline',required=True,type=Path)
    ap.add_argument('--feedback-records',required=True,type=Path);ap.add_argument('--routing-audit',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path);ap.add_argument('--model',required=True)
    ap.add_argument('--reuse-model-run',action='append',type=Path,default=[])
    ap.add_argument('--chapter-seed-run',action='append',default=[])
    ap.add_argument('--chapter-order',nargs='+',type=int,default=[9,10,7,12,11,2,4,6,8,3,5])
    ap.add_argument('--max-model-calls-per-chapter',type=int,default=384)
    args=ap.parse_args();assert set(args.chapter_order)==set(range(2,13)) and len(args.chapter_order)==11
    root=args.output.resolve();root.mkdir(exist_ok=False)
    snapshot=generation_code_snapshot();runner=ROOT/'scripts/run_person_content_acceptance.py'
    runner_hash=hashlib.sha256(runner.read_bytes()).hexdigest()
    current=args.draft.resolve();seeds=list(args.chapter_seed_run);origins=list(args.reuse_model_run)
    ancestors=prior_chapter_runs(current)
    for seed in seeds:
        number,folder=seed.split('=',1);folder=Path(folder).resolve();summary=read(folder/'summary.json')
        assert summary['sources_sha256']==read(current/'summary.json')['sources_sha256'] and summary['code_unchanged_during_run'] is True
        ancestors[int(number)]=folder
    results=[]
    progress={'status':'running','initial_draft':str(current),'generation_code_snapshot':snapshot,
        'runner_sha256':runner_hash,'chapters':results,'last_completed_report':str(current)}
    write(root/'progress.json',progress)
    for step,n in enumerate(args.chapter_order,1):
        if (root/'STOP_AFTER_CURRENT_CHAPTER').exists():
            progress.update(status='checkpointed_for_controller_diagnosis')
            write(root/'progress.json',progress);return
        assert snapshot==generation_code_snapshot() and runner_hash==hashlib.sha256(runner.read_bytes()).hexdigest(),'code_changed_during_sweep'
        cache=root/f'raw-cache-{step:02d}';raw_cache(cache,origins)
        output=root/f'chapter-{n:02d}';output.mkdir()
        command=[sys.executable,str(runner),str(current),'--baseline',str(args.baseline.resolve()),
            '--output',str(output),'--chapters',str(n),'--feedback-records',str(args.feedback_records.resolve()),
            '--routing-audit',str(args.routing_audit.resolve()),'--model',args.model,
            '--reuse-model-run',str(cache),'--max-model-calls',str(args.max_model_calls_per_chapter)]
        for seed in seeds:command.extend(['--chapter-seed-run',seed])
        # A sweep may start from a prior completed chapter run. Recover only
        # authentic raw model candidates, never edit prose to fit a checkpoint.
        prior=ancestors.get(n)
        if prior:
            cp,audit=authentic_candidate(prior,n,args.feedback_records.resolve(),root/f'chapter-{n:02d}-automatic-checkpoint.json')
            if cp:command.extend(['--resume-auto-checkpoint',str(cp)])
            if audit:command.extend(['--resume-material-audit',str(audit)])
        with (output/'console.log').open('w',encoding='utf-8') as log:
            completed=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        if completed.returncode:
            progress.update(status='runner_error',failed_chapter=n,exit_code=completed.returncode)
            write(root/'progress.json',progress);raise RuntimeError('Chapter runner failed; inspect '+str(output/'console.log'))
        summary=read(output/'summary.json');acceptance=read(output/'acceptance-results.json')[str(n)]
        results.append({'chapter':n,'run':str(output),'status':acceptance['status'],
            'unresolved':acceptance['unresolved'],'model_requests':summary['model_requests'],
            'model_requests_failed':summary['model_requests_failed']})
        current=output;origins.append(output);seeds=[]
        progress['last_completed_report']=str(current);write(root/'progress.json',progress)
        print(json.dumps(results[-1],ensure_ascii=False),flush=True)
        permanent=permanent_provider_failure(acceptance) if not acceptance['status'].startswith('passed') else None
        if permanent:
            progress.update(status='provider_unavailable',failure_kind=permanent)
            write(root/'progress.json',progress);return
        if (root/'STOP_AFTER_CURRENT_CHAPTER').exists():
            progress.update(status='checkpointed_for_controller_diagnosis')
            write(root/'progress.json',progress);return
    audit=read(current/'audit.json')
    progress.update(status='passed' if audit['automatic_delivery_status']=='passed' else 'pending_diagnosis',
        delivery_gate=audit['delivery_gate'],code_unchanged_during_sweep=snapshot==generation_code_snapshot(),
        total_new_model_requests=sum(r['model_requests'] for r in results),
        total_failed_model_requests=sum(r['model_requests_failed'] for r in results))
    write(root/'progress.json',progress);print(json.dumps({k:v for k,v in progress.items() if k!='generation_code_snapshot'},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
