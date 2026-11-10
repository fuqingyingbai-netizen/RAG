"""Server-owned attribution and transactional knowledge operation history."""
import copy
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, select

from company_catalog import CompanyAuditEvent, CompanyDocument, CompanyProject, can_manage, can_read

FIELDS = ('name', 'title', 'industry', 'department', 'category', 'review', 'confidentiality', 'visibility',
          'readers', 'tags', 'description', 'folder_id', 'parent_id', 'state', 'version',
          'content', 'revision', 'published_revision', 'knowledge_project_id', 'is_root', 'inherits_project', 'owner')


def snapshot(target):
    return {key: copy.deepcopy(getattr(target, key)) for key in FIELDS if hasattr(target, key)}


def record(db, user, action, target, *, before=None, details=None, event_id=None):
    """Join the caller's transaction; never trust attribution supplied by a client."""
    kind = 'project' if isinstance(target, CompanyProject) else 'document' if isinstance(target, CompanyDocument) else 'note' if getattr(target, '__tablename__', '') == 'company_notes' else 'folder'
    project_id = target.id if kind == 'project' else target.knowledge_project_id if kind == 'document' else target.project_id
    index_id = getattr(target, 'index_id', None)
    if index_id is None:
        index_id = db.get(CompanyProject, project_id).index_id
    after = snapshot(target)
    changes = {key: {'before': (before or {}).get(key), 'after': value} for key, value in after.items()
               if before is None or (before or {}).get(key) != value}
    event = CompanyAuditEvent(id=event_id or uuid.uuid4().hex, index_id=index_id, project_id=project_id,
        target_type=kind, target_id=target.id, target_name=getattr(target, 'name', None) or getattr(target, 'title', ''),
        actor_id=getattr(user, 'id', None), actor_username=user.username, action=action,
        changes=changes, details=details or {})
    db.add(event)
    if action in ('document.delete', 'project.delete', 'note.delete'):
        from company_recycle import capture
        capture(db, action, target, before)
    return event


def mark_modified(target, user):
    target.modified_by = user.username
    target.updated_at = datetime.utcnow()


def history(db, user, index_id, *, project_id='', document_id='', page=1, page_size=30):
    if document_id:
        target = db.get(CompanyDocument, document_id)
    elif project_id:
        target = db.get(CompanyProject, project_id)
    elif user.role != 'admin':
        raise HTTPException(403, '仅管理员可查看全部操作记录。')
    else:
        target = None
    if (document_id or project_id) and (not target or target.index_id != index_id or not can_read(target, user) or not can_manage(target, user)):
        raise HTTPException(404, '记录不存在或没有查看权限。')
    query = select(CompanyAuditEvent).where(CompanyAuditEvent.index_id == index_id)
    if document_id:
        query = query.where(CompanyAuditEvent.target_type == 'document', CompanyAuditEvent.target_id == document_id)
    elif project_id:
        query = query.where(CompanyAuditEvent.project_id == project_id)
    # Project owners cannot inspect metadata belonging to legacy files with a narrower ACL.
    if user.role != 'admin' and project_id:
        hidden = [d.id for d in db.scalars(select(CompanyDocument).where(CompanyDocument.knowledge_project_id == project_id)) if not can_read(d, user)]
        if hidden:
            query = query.where(~((CompanyAuditEvent.target_type == 'document') & CompanyAuditEvent.target_id.in_(hidden)))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(CompanyAuditEvent.created_at.desc(), CompanyAuditEvent.id.desc())
        .offset((page - 1) * page_size).limit(page_size))
    return {'events': [{key: getattr(row, key) for key in ('id', 'project_id', 'target_type', 'target_id',
        'target_name', 'actor_id', 'actor_username', 'action', 'changes', 'details')} |
        {'created_at': row.created_at.isoformat() + 'Z'} for row in rows], 'total': total, 'page': page, 'page_size': page_size}
