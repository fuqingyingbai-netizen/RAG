"""Restore report progress against current admitted originals, never old prose as evidence."""
from person_content_acceptance import restore_literal_plan_from_checkpoint,same_source_bound_draft
from person_records import personal_analysis_allowed


def checkpoint_literal_plan(packet):
    """Read exact source excerpts from material or coverage request formats."""
    material=None
    if 'source_display_quotes' in packet:
        rows=packet['source_display_quotes']
        if not isinstance(rows,list):raise ValueError('checkpoint_literal_context_invalid')
        material=[]
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('shown_evidence_id'),str) or not isinstance(row.get('quote'),str):
                raise ValueError('checkpoint_literal_context_invalid')
            material.append({'evidence_id':row['shown_evidence_id'],'quote':row['quote']})
    coverage=[];tables=packet.get('tables',[])
    if not isinstance(tables,list):raise ValueError('checkpoint_literal_context_invalid')
    for row in tables:
        if not isinstance(row,dict) or row.get('representation')!='literal_source_excerpt':continue
        ids=row.get('evidence_ids')
        if not isinstance(ids,list) or len(ids)!=1 or not isinstance(ids[0],str) or not isinstance(row.get('text'),str):
            raise ValueError('checkpoint_literal_context_invalid')
        coverage.append({'evidence_id':ids[0],'quote':row['text']})
    if material is not None and coverage and material!=coverage:
        raise ValueError('checkpoint_literal_context_conflict')
    return material if material is not None else coverage


def restore_research_pool(package,previous,admitted,conflicts=()):
    by_id={f['evidence_id']:f for f in admitted}
    research=package.setdefault('research_facts',list(package['facts']))
    present={f['evidence_id'] for f in research};added=[]
    for old in previous:
        eid=old['evidence_id'];current=by_id.get(eid)
        if current is None or any(old.get(k)!=current.get(k) for k in ('fact','source_url','subject','subject_scope')):
            raise ValueError('report_research_source_mismatch:'+eid)
        if eid in present:continue
        row={**current,'analysis_allowed':personal_analysis_allowed(current,set(conflicts)),
            'temporal_conflict':eid in conflicts}
        # This is a provenance marker, not permission or a review result.
        if old.get('automatic_checkpoint_material_pending_relevance_review'):
            row['automatic_checkpoint_material_pending_relevance_review']=True
        research.append(row);present.add(eid);added.append(eid)
    return added


def restore_chapter_state(package,previous,diagnostic,claims,admitted,conflicts=()):
    added=restore_research_pool(package,previous.get('research_facts',previous.get('facts',[])),admitted,conflicts)
    literal=restore_literal_plan_from_checkpoint(package,previous) if 'required_source_displays' in previous else {'records':0,'chars':0}
    if 'literal_material_display_proposed' in previous:
        package['literal_material_display_proposed']=previous['literal_material_display_proposed']
    elif package.get('required_source_displays'):
        # Older render handoffs omitted this presentation flag. These are
        # actual source-validated retained excerpts, not new review verdicts.
        package['literal_material_display_proposed']=True
    content=diagnostic.get('content_acceptance',{})
    bound=same_source_bound_draft(claims,content.get('last_validated_candidate'))
    if bound and isinstance(content.get('material_diagnosis'),dict):
        package['material_diagnosis_checkpoint']={**content['material_diagnosis'],
            'bound_candidate':content['last_validated_candidate']}
    return {'research_records_restored':len(added),'research_evidence_ids_restored':added,
        'literal_state':literal,'material_checkpoint_candidate_bound':bound,
        'policy':'Current source/semantic and complete context fingerprints still run; pending rows stay pending.'}
