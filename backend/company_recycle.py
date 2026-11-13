"""Ten-day recovery records, scoped restoration and bounded original reclamation."""
import uuid
from contextlib import ExitStack
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import DateTime, Index, JSON, String, select, text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
import company_knowledge as kb

RETENTION_DAYS = 10
router = APIRouter()


def initialize(engine):
    """Legacy deletions get a fresh ten-day grace period, never guessed file ages."""
    RecycleItem.__table__.create(engine, checkfirst=True)
    import company_workspace as ws
    from company_catalog import CompanyDocument, CompanyProject, CompanyAuditEvent
    from company_notes import CompanyNote
    with ws.SessionLocal() as db:
        if engine.dialect.name == 'postgresql':
            # Multiple application workers may start together after a release.
            db.execute(text('SELECT pg_advisory_xact_lock(731101010)'))
        for index in RecycleItem.__table__.indexes:
            index.create(bind=db.connection(), checkfirst=True)
        known = select(RecycleItem.target_id).where(RecycleItem.kind == 'document')
        for doc in db.scalars(select(CompanyDocument).where(CompanyDocument.state == 'deleted',
                CompanyDocument.object_key != '', ~CompanyDocument.id.in_(known))):
            capture(db, 'document.delete', doc, {'state': 'ready'}, group=False)
        for kind, model in (('note', CompanyNote), ('project', CompanyProject)):
            known = select(RecycleItem.target_id).where(RecycleItem.kind == kind)
            for obj in db.scalars(select(model).where(model.deleted_at.is_not(None), ~model.id.in_(known))):
                before = {}
                if kind == 'project':
                    event = db.scalar(select(CompanyAuditEvent).where(CompanyAuditEvent.target_id == obj.id,
                        CompanyAuditEvent.action == 'project.delete').order_by(CompanyAuditEvent.created_at.desc()))
                    before['name'] = event.target_name if event else obj.name
                capture(db, kind+'.delete', obj, before, group=False)
        db.commit()


class RecycleItem(Base):
    __tablename__ = 'company_recycle_items'
    __table_args__ = (Index('uq_company_recycle_active', 'kind', 'target_id', unique=True,
        postgresql_where=text("status = 'deleted'"), sqlite_where=text("status = 'deleted'")),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    index_id: Mapped[str] = mapped_column(String(100), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    parent_id: Mapped[str] = mapped_column(String(64), default='', index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    deleted_at: Mapped[datetime] = mapped_column(DateTime)
    purge_after: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(20), default='deleted', index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


def models():
    from company_catalog import CompanyDocument, CompanyProject, CompanyFolder
    from company_notes import CompanyNote
    return {'document': CompanyDocument, 'project': CompanyProject, 'note': CompanyNote, 'folder': CompanyFolder}


def capture(db, action, target, before=None, *, group=True):
    """Called by the audit writer, in exactly the deletion transaction."""
    kind = action.split('.')[0]
    if action not in ('document.delete', 'project.delete', 'note.delete', 'folder.delete'):
        return
    from company_catalog import CompanyProject, CompanyFolder
    index_id = db.get(CompanyProject, target.project_id).index_id if kind == 'folder' else target.index_id
    now = datetime.utcnow()
    item = RecycleItem(id=uuid.uuid4().hex, index_id=index_id, kind=kind,
        target_id=target.id, title=(before or {}).get('name') or getattr(target, 'title', '') or target.name,
        parent_id='', deleted_at=now, purge_after=now + timedelta(days=RETENTION_DAYS),
        status='deleted', details={'state': (before or {}).get('state', 'ready')})
    db.add(item)
    transaction = db.get_transaction()
    captured = db.info.setdefault('recycle_captures', {})
    if captured.get('transaction') is not transaction:
        captured.clear()
        captured.update(transaction=transaction, ids=set())
    captured['ids'].add(item.id)
    if group and kind in ('note', 'project', 'folder'):
        from company_catalog import CompanyDocument
        folder_ids = set()
        if kind == 'folder':
            all_folders = list(db.scalars(select(CompanyFolder).where(CompanyFolder.project_id == target.project_id)))
            folder_ids.add(target.id)
            queue = [target.id]
            for parent_id in queue:
                for child in all_folders:
                    if child.parent_id == parent_id and child.id not in folder_ids:
                        folder_ids.add(child.id)
                        queue.append(child.id)
        docs = list(db.scalars(select(CompanyDocument).where(
            (CompanyDocument.note_id == target.id) if kind == 'note' else
            (CompanyDocument.knowledge_project_id == target.project_id) & CompanyDocument.folder_id.in_(folder_ids) if kind == 'folder' else
            (CompanyDocument.knowledge_project_id == target.id))))
        ids = {doc.id for doc in docs}
        # Flush first so the records created earlier in this transaction are visible.
        db.flush()
        children = list(db.scalars(select(RecycleItem).where(RecycleItem.status == 'deleted',
            RecycleItem.index_id == index_id, RecycleItem.parent_id == '')))
        from company_notes import CompanyNote
        note_ids = set(db.scalars(select(CompanyNote.id).where(CompanyNote.project_id == target.id))) if kind == 'project' else set(db.scalars(
            select(CompanyNote.id).where(CompanyNote.project_id == target.project_id, CompanyNote.folder_id.in_(folder_ids)))) if kind == 'folder' else set()
        for child in children:
            if child.id != item.id and ((child.kind == 'document' and child.target_id in ids) or
                    (child.kind == 'note' and child.target_id in note_ids) or
                    (child.kind == 'folder' and child.target_id in folder_ids)):
                # An older separately deleted file must not be resurrected with its parent.
                if child.id in captured['ids']:
                    child.parent_id = item.id
                    for member in descendants(db, child):
                        member.purge_after = item.purge_after
    return item


def authorized(db, item, user):
    from company_catalog import classification_allowed, is_owner
    target = db.get(models()[item.kind], item.target_id)
    principal = target
    if target and item.kind == 'folder':
        from company_catalog import CompanyProject
        principal = db.get(CompanyProject, target.project_id)
    allowed = principal and (user.role == 'admin' or is_owner(principal, user))
    if principal and hasattr(principal, 'confidentiality'):
        allowed = allowed and classification_allowed(principal, user)
    if target and item.kind == 'note':
        from company_catalog import CompanyProject
        project = db.get(CompanyProject, target.project_id)
        allowed = allowed and project is not None and classification_allowed(project, user)
    if not allowed or item.index_id != kb.settings()['index_id']:
        raise HTTPException(404, '回收站记录不存在或没有管理权限。')
    return target


@router.get('/recycle-bin')
def listing(page: int = Query(1, ge=1), user=Depends(kb.require_knowledge_user)):
    import company_workspace as ws
    with ws.SessionLocal() as db:
        rows = db.scalars(select(RecycleItem).where(RecycleItem.index_id == kb.settings()['index_id'],
            RecycleItem.status == 'deleted', RecycleItem.parent_id == '').order_by(RecycleItem.deleted_at.desc()))
        visible = []
        for row in rows:
            try:
                authorized(db, row, user)
            except HTTPException:
                continue
            visible.append({'id': row.id, 'kind': row.kind, 'title': row.title,
                'deleted_at': row.deleted_at.isoformat()+'Z', 'purge_after': row.purge_after.isoformat()+'Z',
                'can_restore': row.purge_after > datetime.utcnow()})
        return {'items': visible[(page-1)*50:page*50], 'total': len(visible), 'retention_days': RETENTION_DAYS}


def descendants(db, item):
    result = [item]
    for parent in result:
        result.extend(db.scalars(select(RecycleItem).where(RecycleItem.parent_id == parent.id,
            RecycleItem.status == 'deleted').order_by(RecycleItem.id).with_for_update()))
    return result


@router.post('/recycle-bin/{item_id}/restore')
async def restore(item_id: str, user=Depends(kb.require_knowledge_user)):
    import company_workspace as ws
    from company_catalog import CompanyDocument, CompanyProject, CompanyFolder, document_store
    from company_audit import record, snapshot, mark_modified
    queued, notices = [], []
    with ws.SessionLocal() as db:
        # Same parent-before-document lock order as normal document mutations.
        original = db.get(RecycleItem, item_id)
        if not original:
            raise HTTPException(404, '回收站记录不存在。')
        target = authorized(db, original, user)
        project_id = target.id if original.kind == 'project' else getattr(target, 'knowledge_project_id', '') or getattr(target, 'project_id', '')
        project = db.scalar(select(CompanyProject).where(CompanyProject.id == project_id).with_for_update()) if project_id else None
        item = db.scalar(select(RecycleItem).where(RecycleItem.id == item_id).with_for_update())
        if item.status != 'deleted' or item.purge_after <= datetime.utcnow() or item.parent_id:
            raise HTTPException(409, '恢复期限已过或记录状态已变化；请从所属项目或笔记恢复。')
        if project and project.deleted_at and item.kind != 'project':
            raise HTTPException(409, '请先恢复所属项目。')
        group = descendants(db, item)
        # Parents are restored before their children, and all folders before notes/files.
        group.sort(key=lambda row: {'project': 0, 'folder': 1, 'note': 2, 'document': 3}[row.kind])
        for row in group:
            obj = authorized(db, row, user)
            if row.purge_after <= datetime.utcnow():
                raise HTTPException(409, '关联资料已超过恢复期限。')
            before = snapshot(obj)
            if hasattr(obj, 'folder_id') and obj.folder_id:
                parent_folder = db.get(CompanyFolder, obj.folder_id)
                if parent_folder and parent_folder.deleted_at:
                    raise HTTPException(409, '请先恢复所属目录，再恢复这份资料。')
                if not parent_folder:
                    obj.folder_id = ''
            if row.kind == 'project':
                conflict = db.scalar(select(CompanyProject.id).where(CompanyProject.index_id == obj.index_id,
                    CompanyProject.owner == obj.owner, CompanyProject.name == row.title, CompanyProject.id != obj.id))
                obj.name = row.title if not conflict else row.title[:170] + '（恢复 '+obj.id[:8]+'）'
                obj.deleted_at = None
            elif row.kind == 'folder':
                if obj.deleted_at is None:
                    raise HTTPException(409, '目录状态已变化。')
                parent = db.get(CompanyFolder, obj.parent_id) if obj.parent_id else None
                if parent and parent.deleted_at:
                    raise HTTPException(409, '请先恢复上级目录。')
                if obj.parent_id and not parent:
                    obj.parent_id = ''
                    notices.append('原上级目录已永久删除，目录已恢复到项目根目录。')
                conflict = db.scalar(select(CompanyFolder.id).where(CompanyFolder.project_id == obj.project_id,
                    CompanyFolder.parent_id == obj.parent_id, CompanyFolder.name == row.title,
                    CompanyFolder.id != obj.id, CompanyFolder.deleted_at.is_(None)))
                obj.name = row.title if not conflict else row.title[:170] + '（恢复 '+obj.id[:8]+'）'
                obj.deleted_at = None
            elif row.kind == 'note':
                if obj.deleted_at is None:
                    raise HTTPException(409, '笔记状态已变化。')
                obj.deleted_at = None
            else:
                obj = db.scalar(select(CompanyDocument).where(CompanyDocument.id == obj.id).with_for_update())
                if obj.state != 'deleted':
                    raise HTTPException(409, '文件状态已变化。')
                if not obj.object_key:
                    raise HTTPException(409, '该历史资料没有本地原件，无法自动恢复。')
                try:
                    store = document_store()
                    if store.mode == 'local':
                        if not store._local_path(obj.object_key).is_file():
                            raise OSError()
                    else:
                        store.get_bytes(obj.object_key)
                except (OSError, ValueError):
                    raise HTTPException(409, '原件已不存在，无法自动恢复。') from None
                # A new version avoids collisions with uploads made while this file was deleted.
                peers = list(db.scalars(select(CompanyDocument).where(CompanyDocument.id != obj.id,
                    CompanyDocument.index_id == obj.index_id, CompanyDocument.owner == obj.owner,
                    CompanyDocument.project == obj.project, CompanyDocument.knowledge_project_id == obj.knowledge_project_id,
                    CompanyDocument.folder_id == obj.folder_id, CompanyDocument.title == obj.title)))
                if any(p.state != 'deleted' and p.sha256 == obj.sha256 and obj.sha256 for p in peers):
                    raise HTTPException(409, '资料库已有相同内容的文件，请保留现有文件。')
                if any(p.is_current and p.state != 'deleted' for p in peers):
                    obj.is_current = 0 if obj.note_id or obj.research_project_id else 1
                    obj.version = max([obj.version, *[p.version for p in peers]]) + 1
                    if obj.is_current:
                        notices.append('同名文件已有其他版本，已作为下一版本恢复，原有版本保留。')
                obj.stale_cloud_id = obj.cloud_id or obj.stale_cloud_id or ''
                obj.cloud_id, obj.job_id, obj.lease_id = None, '', ''
                obj.state = 'archived' if not obj.is_current else 'queued'
                obj.status_message = '已从回收站恢复，等待重新索引' if obj.is_current else '已恢复历史版本'
                if obj.is_current:
                    queued.append(obj.id)
            row.status, row.finished_at = 'restored', datetime.utcnow()
            mark_modified(obj, user)
            record(db, user, row.kind+'.restore', obj, before=before, details={'recycle_id': row.id})
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise HTTPException(409, '资料发生并发修改，请刷新后重试。') from None
    for doc_id in queued:
        ws.schedule_document(doc_id)
    return {'restored': True, 'queued': len(queued), 'notices': list(dict.fromkeys(notices))}


async def purge_due(limit=25):
    """Bounded background work. Row locks serialize restore versus physical deletion."""
    import company_workspace as ws
    from company_catalog import CompanyDocument, document_store
    from company_notes import CompanyNote, CompanyNoteAsset
    count = 0
    with ws.SessionLocal() as db:
        ids = list(db.scalars(select(RecycleItem.id).where(RecycleItem.status == 'deleted',
            RecycleItem.purge_after <= datetime.utcnow()).order_by(RecycleItem.finished_at.asc().nullsfirst(),
                RecycleItem.purge_after).limit(limit)))
    for item_id in ids:
        with ws.SessionLocal() as db:
            item = db.scalar(select(RecycleItem).where(RecycleItem.id == item_id).with_for_update(skip_locked=True))
            if not item or item.status != 'deleted' or item.purge_after > datetime.utcnow():
                continue
            obj = db.get(models()[item.kind], item.target_id)
            if not obj:
                continue
            with ExitStack() as original_locks:
                try:
                    from company_file_operations import file_lock
                    keys = [obj.object_key] if item.kind == 'document' else [a.object_key for a in db.scalars(select(CompanyNoteAsset).where(CompanyNoteAsset.note_id == obj.id))] if item.kind == 'note' else []
                    for key in sorted(set(keys) - {''}):
                        original_locks.enter_context(file_lock(db, key))
                    if item.kind == 'document':
                        obj = db.scalar(select(CompanyDocument).where(CompanyDocument.id == obj.id).with_for_update())
                        if obj.state != 'deleted' or (obj.lease_until and obj.lease_until > datetime.utcnow()):
                            continue
                        if obj.cloud_id or obj.stale_cloud_id:
                            async with kb.httpx.AsyncClient(timeout=15, trust_env=False) as client:
                                await kb.cloud_rpc(client, kb.settings(), '/api/v1/indices/rag/index/delete_file',
                                    {'index_id': obj.index_id, 'doc_ids': list(dict.fromkeys(x for x in
                                        (obj.cloud_id, obj.stale_cloud_id) if x))})
                        if obj.object_key:
                            shared = db.scalar(select(CompanyDocument.id).where(CompanyDocument.id != obj.id,
                                CompanyDocument.object_key == obj.object_key).limit(1))
                            asset = db.scalar(select(CompanyNoteAsset.id).where(CompanyNoteAsset.object_key == obj.object_key).limit(1))
                            if not shared and not asset:
                                document_store().delete_object(obj.object_key)
                        obj.object_key, obj.cloud_id, obj.stale_cloud_id = '', None, ''
                    elif item.kind == 'note':
                        if not obj.deleted_at:
                            continue
                        pending = db.scalar(select(RecycleItem.id).where(RecycleItem.parent_id == item.id,
                            RecycleItem.status == 'deleted').limit(1))
                        if pending:
                            continue
                        for asset in db.scalars(select(CompanyNoteAsset).where(CompanyNoteAsset.note_id == obj.id)):
                            # Asset keys are normally unique; do not assume that when reclaiming.
                            shared = db.scalar(select(CompanyNoteAsset.id).where(CompanyNoteAsset.id != asset.id,
                                CompanyNoteAsset.object_key == asset.object_key).limit(1))
                            doc = db.scalar(select(CompanyDocument.id).where(CompanyDocument.object_key == asset.object_key).limit(1))
                            if asset.object_key and not shared and not doc:
                                document_store().delete_object(asset.object_key)
                            asset.object_key = ''
                    else:
                        if not obj.deleted_at or db.scalar(select(RecycleItem.id).where(
                                RecycleItem.parent_id == item.id, RecycleItem.status == 'deleted').limit(1)):
                            continue
                    item.status, item.finished_at = 'purged', datetime.utcnow()
                    db.commit()
                    count += 1
                except Exception:
                    # Keep recovery metadata and retry next run. Never log provider response/secrets.
                    db.rollback()
                    retry = db.get(RecycleItem, item_id)
                    if retry and retry.status == 'deleted':
                        retry.finished_at = datetime.utcnow()
                        db.commit()
    return count
