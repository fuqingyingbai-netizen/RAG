"""Bounded risk-reason correction followed by a fresh independent review.

The caller supplies the existing normalizer/repair role. No searches or IO run
here; a valid adverse verdict is never retried without a changed reason/basis.
"""
from collections import Counter
from copy import deepcopy
import os

from industry_reasoning import REVIEW_STATES, apply_risk_support, claim_id, fingerprint
from industry_research_stages import review_in_groups


def _claims(rows):
    result = []
    for row in rows:
        if row.get('score') is None:
            continue
        claim = {'question':row['name'], 'text':row.get('reason',''),
                 'evidence_ids':row.get('evidence_ids',[]), 'chapter':14}
        result.append({**claim, 'claim_id':claim_id(claim,14)})
    return result


def _request_limit():
    try:
        return max(1, min(6, int(os.getenv('INDUSTRY_RISK_REVIEW_MAX_REQUESTS','3'))))
    except ValueError:
        return 3


def _merge_reviews(initial, revised, claims):
    """Keep earlier valid verdicts only for unchanged claim identities."""
    result = {**deepcopy(initial), 'attempts':initial['attempts']+revised['attempts'],
              'groups':deepcopy(initial['groups'])+deepcopy(revised['groups']),
              'max_requests':initial['max_requests']+revised['max_requests'],
              'shared_timeout_seconds':initial['shared_timeout_seconds']+revised['shared_timeout_seconds']}
    all_reviews = {**initial['reviews'], **revised['reviews']}
    current_ids = {c['claim_id'] for c in claims}
    result['reviews'] = {cid:review for cid,review in all_reviews.items() if cid in current_ids}
    submitted = set(initial['submitted_claim_ids']) | set(revised['submitted_claim_ids'])
    result['submitted_claim_ids'] = [c['claim_id'] for c in claims if c['claim_id'] in submitted]
    result['excluded_claim_ids'] = [c['claim_id'] for c in claims if c['claim_id'] not in submitted]
    result['exclusion_reasons'] = {cid:reason for cid,reason in
        {**initial['exclusion_reasons'],**revised['exclusion_reasons']}.items()
        if cid in current_ids and cid not in submitted}
    states = Counter(result['reviews'].get(c['claim_id'],{}).get('status','not_evaluated') for c in claims)
    count = {'total':len(claims), 'submitted':len(result['submitted_claim_ids']),
             'valid':sum(states[s] for s in REVIEW_STATES), 'supported':states['supported']}
    result.update(coverage_by_chapter={'14':count}, total_claim_count=count['total'],
                  submitted_claim_count=count['submitted'], valid_review_count=count['valid'],
                  supported_claim_count=count['supported'], pending_claim_count=count['total']-count['valid'],
                  review_state_counts=dict(states), packet_fingerprint=fingerprint([
                      group['packet_fingerprint'] for group in result['groups']]))
    result['retry_counts'] = {**initial.get('retry_counts',{}),**revised.get('retry_counts',{})}
    return result


def review_risk_assessment(result, facts, scope, invoke, repair):
    """Review every scored reason; correct semantic rejections at most once.

    Format/transport failures use the same bounded group recovery as chapters.
    The repair callback must normalize its output against retained facts. Only
    requested dimensions with a changed reason or evidence basis are accepted
    for a new review; successful/abstained dimensions cannot be overwritten.
    """
    original_claims = _claims(result.get('dimensions',[]))
    current_names = {claim['question'] for claim in original_claims}
    initial = review_in_groups(original_claims,facts,invoke,max_requests=_request_limit())
    checked = apply_risk_support(result,initial,facts,scope)
    rejected = [row['name'] for row in checked.get('dimensions',[])
                if row['name'] in current_names and row.get('score') is None
                and row.get('unknown_cause')=='claim_support_rejected']
    if not rejected:
        return checked
    audit = {'attempted':True, 'attempts':1, 'requested_dimensions':rejected,
             'changed_dimensions':[], 'unchanged_dimensions':[], 'repaired_dimensions':[],
             'remaining_dimensions':rejected.copy(),
             'initial_rejections':{row['name']:deepcopy(row.get('validation_diagnostic',{}))
                for row in checked.get('dimensions',[]) if row['name'] in rejected}}
    checked.setdefault('validation_diagnostics',{})['support_repair'] = audit
    try:
        candidate = repair(deepcopy(checked))
    except Exception as exc:
        audit.update(status='repair_failed',error_type=type(exc).__name__)
        return checked
    if not isinstance(candidate,dict) or not isinstance(candidate.get('dimensions'),list):
        audit['status'] = 'invalid_repair_result'
        return checked
    audit['repair_diagnostic'] = deepcopy(candidate.get('validation_diagnostics',{}).get('repair',{}))
    before = {c['question']:c for c in original_claims}
    from industry_delivery import _assessed_dimension
    allowed = {f['evidence_id'] for f in facts if f.get('evidence_id')}
    counts = Counter(row['name'] for row in candidate['dimensions']
                     if isinstance(row,dict) and isinstance(row.get('name'),str))
    replacements = {}
    for row in candidate['dimensions']:
        if (not isinstance(row,dict) or not isinstance(row.get('name'),str)
                or row['name'] not in rejected or counts[row['name']]!=1):
            continue
        name = row['name']
        refs = row.get('evidence_ids')
        if (not isinstance(row.get('reason'),str) or not row['reason'].strip()
                or not isinstance(refs,list) or not refs
                or any(not isinstance(eid,str) for eid in refs) or len(set(refs))!=len(refs)
                or not _assessed_dimension(row) or not set(refs) <= allowed):
            continue
        if (str(row.get('reason','')).strip()==before[name]['text'].strip()
                and set(row['evidence_ids'])==set(before[name]['evidence_ids'])):
            audit['unchanged_dimensions'].append(name)
            continue
        replacements[name] = deepcopy(row)
        replacements[name].pop('unknown_cause',None)
        replacements[name].pop('claim_support_review',None)
        replacements[name].pop('validation_diagnostic',None)
    if not replacements:
        audit['status'] = 'no_valid_changed_reason'
        return checked
    audit['changed_dimensions'] = list(replacements)
    rows = []
    for row in checked['dimensions']:
        if row['name'] not in replacements:
            rows.append(row)
            continue
        replacement = replacements[row['name']]
        if 'input_selection' in row and 'input_selection' not in replacement:
            replacement['input_selection'] = deepcopy(row['input_selection'])
        rows.append(replacement)
    changed_claims = _claims(list(replacements.values()))
    revised = review_in_groups(changed_claims,facts,invoke,max_requests=_request_limit())
    claims = [c for c in original_claims if c['question'] not in replacements] + changed_claims
    combined = _merge_reviews(initial,revised,claims)
    combined['reason_repair_attempts'] = 1
    final = apply_risk_support({**checked,'dimensions':rows},combined,facts,scope)
    # Count a repair only after the new reasoning passes its independent check.
    audit = final['validation_diagnostics']['support_repair']
    audit['repaired_dimensions'] = [row['name'] for row in final['dimensions']
        if row['name'] in replacements and row.get('score') is not None
        and row.get('claim_support_review',{}).get('status')=='supported']
    audit['remaining_dimensions'] = [name for name in rejected if name not in audit['repaired_dimensions']]
    audit['status'] = 'complete' if not audit['remaining_dimensions'] else 'partial' if audit['repaired_dimensions'] else 'rejected'
    final['unknowns'] = [note for note in final.get('unknowns',[]) if not any(
        str(note).startswith(name+'：') for name in audit['repaired_dimensions'])]
    return final
