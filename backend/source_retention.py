"""Drop newly collected web bodies after successful research, keeping provenance."""
from datetime import datetime
from urllib.parse import urlsplit
from pathlib import Path
import hashlib


def external_url(value):
    try:
        url = urlsplit(value or '')
        return value if url.scheme in ('http', 'https') and url.hostname and not url.username and not url.password else ''
    except ValueError:
        return ''


def finalize_web_sources(db, project, store):
    changed = 0
    for source in project.sources or []:
        meta = dict(source.source_metadata or {})
        if meta.get('retention_policy') not in ('transient_web_body', 'transient_platform_body'):
            continue  # Existing records and user-supplied originals are preserved.
        key = source.object_key
        if key and not key.startswith((f'projects/{project.id}/raw_web/', f'projects/{project.id}/structured/')):
            continue
        if key:
            store.delete_object(key)  # Failure leaves a resumable body, never a false success marker.
        revision = (meta.get('previous_document_revision') or {}).get('object_key', '')
        if revision.startswith(f'projects/{project.id}/source_revisions/{source.id}_'):
            store.delete_object(revision)
            meta.pop('previous_document_revision', None)
        raw_key = meta.get('raw_response_key', '')
        if raw_key.startswith(f'projects/{project.id}/structured/'):
            store.delete_object(raw_key)
            meta.pop('raw_response_key', None)
        for image in meta.get('images') or []:
            image_key = image.get('object_key', '') if isinstance(image, dict) else ''
            if image_key.startswith(f'projects/{project.id}/visual_evidence/'):
                store.delete_object(image_key)
        excerpt = (source.summary or source.content or '')[:500]
        # These fields can contain full page text, OCR, or inline image payloads.
        for field in ('document_pages', 'document_extraction', 'images', 'ocr_text', 'raw_content', 'raw_response'):
            meta.pop(field, None)
        meta.update(retention_policy='record_only', body_removed_at=datetime.utcnow().isoformat() + 'Z',
                    evidence_excerpt=excerpt, original_url=external_url(source.url))
        source.source_metadata = meta
        source.content, source.object_key, source.summary = '', '', excerpt
        changed += 1
    if changed:
        db.commit()
    return changed


def finalize_company_sources(db,project,store,upload_root=None):
    """Drop task-owned copies after final delivery; never delete desktop originals."""
    changed=finalize_web_sources(db,project,store)
    root=(Path(upload_root) if upload_root is not None else Path(__file__).resolve().parent.parent/
        'data/research_uploads').resolve()/str(int(project.id))
    for source in project.sources or []:
        meta=dict(source.source_metadata or {})
        prefix=f'projects/{int(project.id)}/uploads/'
        key=source.object_key or ''
        if key.startswith(prefix):
            keys=[key,meta.get('original_object_key','')]
            if any(k and not store.project_key(k,project.id).startswith(prefix) for k in keys):
                raise ValueError('company_upload_cleanup_scope_mismatch')
            local=Path(meta['local_path']).resolve() if meta.get('local_path') else None
            if local is not None and not local.is_relative_to(root):
                raise ValueError('company_upload_cleanup_outside_server_copy')
            digest=hashlib.sha256((source.content or '').encode()).hexdigest()
            for k in keys:
                if k:store.delete_object(k)
            if local is not None and local.is_file():local.unlink()
            source.content='';source.object_key='';source.summary=''
            meta.update(retention_policy='record_only',body_removed_at=datetime.utcnow().isoformat()+'Z',
                native_sha256=digest,original_url=external_url(source.url))
            changed+=1
        if meta.get('retention_policy')=='record_only':
            keep={'provider','module','tool','target','query','publication_date','entity_validation',
                'entity_validation_reason','retention_policy','body_removed_at','original_url','evidence_excerpt',
                'company_chapter_ids','company_chapter_id','company_requirement_ids','original_filename',
                'native_sha256','retrieved_at','evidence_scope','content_kind'}
            source.source_metadata={k:v for k,v in meta.items() if k in keep}
    db.commit()
    return changed
