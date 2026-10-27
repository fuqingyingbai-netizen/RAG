"""Conserve immutable source baselines and certified intermediate versions.

Inputs are real validated coverage decisions, not new model verdicts. A proof
using tables/literals is deliberately not compacted because those carriers can
change during a later display allocation.
"""

def key(row):
    return row['analysis'],tuple(sorted(set(row['evidence_ids'])))


def conserve_requirements(prior,active,targets,review,protected):
    immutable={key(r) for r in protected};replaced={}
    for row in review.get('items',[]):
        i=row.get('prior_index');matches=row.get('matched_claim_indices',[])
        if (type(i) is not int or not 0<=i<len(prior) or key(prior[i]) in immutable
                or row.get('status')!='covered' or row.get('matched_table_indices')
                or row.get('gaps') or row.get('missing_numeric_anchors') or row.get('missing_tenures')
                or not isinstance(matches,list) or not matches
                or any(type(j) is not int or not 0<=j<len(active) for j in matches)):
            continue
        replaced[i]=list(matches)
    result=[];indices={}
    def add(row):
        k=key(row)
        if k not in indices:indices[k]=len(result);result.append(row)
        return indices[k]
    mapping={}
    for i,row in enumerate(prior):
        if i not in replaced:mapping[i]=add(row)
    for matches in replaced.values():
        for i in matches:add(active[i])
    for i in sorted(targets):add(active[i])
    proof={'prior_index_map':mapping,'certified_intermediate_replacements':[
        {'prior_index':i,'prior':prior[i],'matched_claim_indices':matches,
         'current_carriers':[active[j] for j in matches],
         'basis':'Actual covered receipt with no table/literal dependency; immutable original baselines and complete final source/material checks remain.'}
        for i,matches in sorted(replaced.items())]}
    return result,proof


def writer_missing_items(items,mapping):
    return [{**row,'prior_index':mapping[row['prior_index']]} if row.get('status')=='missing'
        and type(row.get('prior_index')) is int and row['prior_index'] in mapping else row for row in items]
def checkpoint_requirements(checkpoint,content,origin_binding):
    """Restore actual conserved obligations, never just a shortened candidate.

    Caller authenticates the audit, raw candidate and source/code snapshots;
    every restored paragraph must still pass current source validation.
    """
    import copy
    if origin_binding!='authenticated_last_validated_candidate_rebase':return [],None
    actual=content.get('last_validated_candidate')
    if not isinstance(actual,list) or actual!=checkpoint.get('claims'):raise ValueError('conservation_checkpoint_candidate_mismatch')
    def source_text(rows):
        if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):return None
        return [{'analysis':r.get('analysis'),'evidence_ids':r.get('evidence_ids')} for r in rows]
    if 'last_validated_requirements' in content:
        rows=content['last_validated_requirements']
        if not isinstance(rows,list) or any(not isinstance(r,dict) or not isinstance(r.get('analysis'),str)
                or not r['analysis'].strip() or not isinstance(r.get('evidence_ids'),list) or not r['evidence_ids']
                or not all(isinstance(e,str) and e for e in r['evidence_ids']) for r in rows):
            raise ValueError('conservation_checkpoint_invalid_requirements')
        return copy.deepcopy(rows),{'origin':'authenticated_last_validated_requirements',
            'restored_items':len(rows),
            'boundary':'All actual obligations at this candidate checkpoint, including early review failures. Prior questions only; current source/semantic/coverage checks remain mandatory.'}
    events=[content,*reversed(content.get('rounds',[]))]
    for event in events:
        rows=event.get('conserved_requirements')
        if not rows or source_text(event.get('candidate_repair'))!=source_text(actual):continue
        if not isinstance(rows,list) or any(not isinstance(r,dict) or not isinstance(r.get('analysis'),str)
                or not r['analysis'].strip() or not isinstance(r.get('evidence_ids'),list) or not r['evidence_ids']
                or not all(isinstance(e,str) and e for e in r['evidence_ids']) for r in rows):
            raise ValueError('conservation_checkpoint_invalid_requirements')
        return copy.deepcopy(rows),{'round':event.get('round'),'restored_items':len(rows),
            'boundary':'Actual prior audit obligations only; pending stays pending and current source/semantic/coverage checks remain mandatory.'}
    return [],None




def remember_source_validated_candidate(package,claims):
    """Remember real pre-semantic prose as questions, never accepted evidence."""
    import copy
    rows=package.setdefault('pre_semantic_conservation_candidates',[])
    known={key(r) for r in rows}
    for claim in claims:
        if not claim.get('analysis') or claim.get('review_analysis'):continue
        row={'analysis':claim['analysis'],'evidence_ids':list(claim['evidence_ids'])}
        if key(row) not in known:
            rows.append(copy.deepcopy(row));known.add(key(row))


def source_conservation_prior(package,prior,current=()):
    """Source-valid proposals still need semantic support or justified exclusion."""
    import copy
    result=copy.deepcopy(prior);known={key(r) for r in result}
    retained={key(r) for r in current if r.get('analysis')}
    for row in package.get('pre_semantic_conservation_candidates',[]):
        if key(row) not in known and key(row) not in retained:
            result.append(copy.deepcopy(row));known.add(key(row))
    return result
