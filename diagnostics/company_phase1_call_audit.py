"""Summarize native request ledgers; never infer billing or report acceptance."""
from __future__ import annotations
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'work/company-phase1-20261028'


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    rounds=[]
    for case in ['haitian','kingsoft','holdout']:
        native=RUN/'native'/case
        stops=[]
        for path in native.glob('*stop-proof.json'):
            value=json.loads(path.read_text(encoding='utf-8'))
            stops.append((path,value))
        for plan_path in sorted(native.glob('bounded-plan-*.json')):
            tag=plan_path.stem.removeprefix('bounded-plan-')
            plan=json.loads(plan_path.read_text(encoding='utf-8'))
            ledger=native/('bounded-calls-'+tag+'.jsonl')
            # Read once: a live file can grow, so bind the exact observed bytes.
            raw=ledger.read_bytes() if ledger.exists() else b''
            lines=raw.decode('utf-8').splitlines();events=[];partial_lines=[]
            for i,line in enumerate(lines,1):
                try:events.append(json.loads(line))
                except json.JSONDecodeError:partial_lines.append(i)
            started={e['number'] for e in events if e['kind']=='model_started'}
            returned=[e for e in events if e['kind']=='model_returned']
            returned_ids=[e['number'] for e in returned]
            failed={e['number'] for e in events if e['kind']=='model_failed'}
            assert len(returned_ids)==len(set(returned_ids)),'Duplicate logical response numbers'
            assert set(returned_ids)<=started and failed<=started,'Response without logical start'
            result_path=native/('bounded-result-'+tag+'.json')
            result=json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else None
            matching_stops=[p for p,v in stops if v.get('round')==tag or tag in str(v.get('online_backup',''))]
            state=(result.get('state') if result else 'externally_stopped_with_proof' if matching_stops else
                   'in_progress_or_unrecorded_stop')
            usage=Counter()
            for event in returned:
                item=event.get('usage') or {}
                for key in ['input_tokens','output_tokens','total_tokens']:
                    if isinstance(item.get(key),int):usage[key]+=item[key]
                reasoning=(item.get('output_token_details') or {}).get('reasoning')
                if isinstance(reasoning,int):usage['reasoning_tokens']+=reasoning
            rounds.append({'case':case,'tag':tag,'code_commit':plan.get('code_commit'),
                'stage':plan.get('stage'),'model':plan.get('model'),'state':state,
                'logical_model_requests':len(started),'logical_model_returns':len(returned),
                'finish_reasons':dict(Counter(str(e.get('finish_reason')) for e in returned)),
                'logical_model_failures':len(failed),
                'logical_without_recorded_return_or_failure':len(started-set(returned_ids)-failed),
                'event_counts':dict(Counter(e['kind'] for e in events)),
                'model_http_statuses':dict(Counter(str(e['http_status']) for e in events if e['kind']=='model_http_headers')),
                'returned_reported_token_usage':dict(usage),
                'partial_or_malformed_ledger_lines':partial_lines,
                'plan_sha256':digest(plan_path),'observed_ledger_sha256':hashlib.sha256(raw).hexdigest(),
                'observed_ledger_bytes':len(raw),
                'result_sha256':digest(result_path) if result_path.exists() else None,
                'stop_proofs':{p.name:digest(p) for p in matching_stops},
                'report_acceptance':'not_inferred_from_calls','actual_currency_cost':None})
    report={'version':'company-phase1-native-call-audit-v1',
        'audit_source_sha256':digest(Path(__file__)),
        'observed_at':datetime.now(timezone.utc).isoformat(),'rounds':rounds,
        'scope':'Native ledgers and their requests fetches only; excludes separate connectivity/capacity probes, GitHub upstream-source retrieval and standalone original-page downloads.',
        'limitations':['Live ledgers are bound to observed bytes and may subsequently grow.',
                      'Returned token usage is not a billing statement; failed or interrupted calls may also be billed.',
                      'HTTP 200, stop and successful historical receipts do not establish semantic or full report acceptance.'],
        'full_report_acceptance':'not_evaluated_by_this_call_audit'}
    destination=RUN/'native-call-audit.json'
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(destination),'rounds':len(rounds),
        'logical_model_requests':sum(r['logical_model_requests'] for r in rounds),
        'reported_returns':sum(r['logical_model_returns'] for r in rounds),
        'report_acceptance':'not_evaluated'},ensure_ascii=False))


if __name__=='__main__':main()
