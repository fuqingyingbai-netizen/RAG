"""Drop newly collected web bodies after successful research, keeping provenance."""
from datetime import datetime
from urllib.parse import urlsplit


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
