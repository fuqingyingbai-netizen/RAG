"""Publication, event and accounting time remain distinct evidence dimensions."""
from .company_governance import get
from .company_source_review import document_date_proof


def annotate_time_context(package,sources,as_of):
    by_url={str(get(s,'url')):s for s in sources}
    for key in ('facts','events','observations'):
        for record in package.get(key,[]):
            if not isinstance(record,dict):continue
            if record.get('model_reading_mode'):continue  # Already bound by the native reading contract.
            source=by_url.get(str(record.get('source_url') or ''))
            if source is None:continue
            timing=publication_context(source,as_of)
            publication=str(record.get('publication_date') or timing['publication_date'] or '')
            late=bool(as_of and publication and publication>as_of)
            record['time_context']={**timing,'publication_date':publication,'research_as_of':as_of,
                'post_cutoff_disclosure':late,'event_date':record.get('event_date') or record.get('date') or 'unknown',
                'accounting_period':record.get('period') or 'unknown'}
            if late:
                record['post_cutoff_disclosure']=True
                record['eligible_for_risk_scoring']=False
                record['boundary']=str(record.get('boundary') or '')+'；事后披露，不代表历史截至日已知；事件日与会计期分别核对。'
    return package


def publication_context(source,as_of):
    from .company_evidence import source_body
    from .company_risk_register import publication_date
    import re
    proof=document_date_proof(source);raw,_=source_body(source)
    known=publication_date(source,raw)
    url=str(get(source,'url') or '')
    match=re.search(r'/(20\d{2})/(\d{2})(\d{2})(?:/|\b)',url)
    url_hint='-'.join(match.groups()) if match else ''
    late=bool(as_of and known and known>as_of)
    return {'publication_date':known,'publication_date_basis':'native_or_declared' if known else 'unknown',
        'document_date_hint':proof.get('date',''),'url_date_hint':url_hint,
        'post_cutoff_publication_hint':bool(as_of and not known and url_hint and url_hint>as_of),
        'post_cutoff_disclosure':late,'research_as_of':as_of,
        'known_at_historical_cutoff':False if late else None}
