"""Bounded source-review metadata. No fetching, indexing, models or cleanup."""
from math import ceil

from sqlalchemy import String, case, cast, func, or_

from models import ResearchSource

VERSION = 'industry-source-review-v2-text-integrity'


def source_records(db, project_id, *, page=1, page_size=15, search='', source_type='', archive_state=''):
    original = func.coalesce(ResearchSource.source_metadata['original_object_key'].as_string(), '')
    text_review = func.lower(cast(ResearchSource.source_metadata['text_encoding_review']['requires_source_review'].as_string(),String)).in_(['true','1'])
    policy = func.coalesce(ResearchSource.source_metadata['retention_policy'].as_string(), '')
    removed = func.coalesce(ResearchSource.source_metadata['body_removed_at'].as_string(), '')
    effective_key = case((original != '', original), else_=ResearchSource.object_key)
    has_archive = effective_key.like(f'projects/{project_id}/%')
    state = case((has_archive, 'archived'), (or_(removed != '', policy == 'record_only'), 'cleared'), else_='not_archived')
    base = db.query(ResearchSource).filter(ResearchSource.project_id == project_id)
    types = {kind: count for kind, count in base.with_entities(ResearchSource.source_type, func.count()).group_by(ResearchSource.source_type).all()}
    states = {kind: count for kind, count in base.with_entities(state, func.count()).group_by(state).all()}
    query = base
    if search.strip():
        value = search.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        pattern = '%' + value + '%'
        query = query.filter(or_(ResearchSource.title.ilike(pattern, escape='\\'),
                                 ResearchSource.url.ilike(pattern, escape='\\'),
                                 ResearchSource.summary.ilike(pattern, escape='\\')))
    if source_type:
        query = query.filter(ResearchSource.source_type == source_type)
    if archive_state:
        query = query.filter(state == archive_state)
    total = query.with_entities(func.count(ResearchSource.id)).scalar()
    page = min(page, max(1, ceil(total / page_size)))
    # Explicit columns keep full content and provider metadata out of the list.
    records = query.with_entities(ResearchSource.id, ResearchSource.project_id,
        ResearchSource.source_type, ResearchSource.title, ResearchSource.url,
        func.substr(ResearchSource.summary, 1, 801).label('summary'),
        ResearchSource.credibility_score, ResearchSource.created_at,
        state.label('archive_state'), removed.label('body_removed_at'), policy.label('retention_policy'),
        func.coalesce(text_review,False).label('text_review_required'))
    rows = records.order_by(ResearchSource.created_at.desc(), ResearchSource.id.desc()).offset((page-1)*page_size).limit(page_size).all()
    result = []
    for row in rows:
        item = dict(row._mapping)
        summary = item.get('summary') or ''
        item.update(summary=summary[:800], summary_truncated=len(summary)>800,
                    has_archive=item['archive_state']=='archived',
                    archive_verified=False, archive_status_basis='registered_object_reference',
                    created_at=item['created_at'].isoformat() if item.get('created_at') else '')
        result.append(item)
    return {'project_id':project_id, 'records':result, 'total':total, 'page':page,
            'page_size':page_size, 'project_total':sum(types.values()), 'source_types':types,
            'archive_counts':states, 'version':VERSION}


def compact_progress_trace(trace, limit=120):
    """Keep latest UI events; the full journal and activity clock stay unchanged."""
    fields = {'stage':80, 'agent':120, 'label':240, 'status':40, 'detail':1200,
              'timestamp':80, 'run_id':80, 'run_started_at':80, 'type':40,
              'section':240, 'current_section':240, 'current_label':240,
              'platform':120, 'url':2000}
    numeric = {'heartbeat','elapsed_seconds','total_elapsed_seconds','stage_elapsed_seconds',
               'current_elapsed_seconds','idle_seconds','input_chars','output_chars','batch','project_id'}
    rows = []
    for event in trace[-limit:]:
        if not isinstance(event,dict):
            continue
        row = {key:str(event[key])[:cap] for key,cap in fields.items() if event.get(key) is not None}
        row.update({key:value for key,value in event.items() if key in numeric and type(value) in (bool,int,float)})
        rows.append(row)
    return rows
