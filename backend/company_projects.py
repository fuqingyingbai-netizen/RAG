"""Persistent project/folder workspaces, with inherited upload defaults."""
import uuid
import hashlib
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import company_knowledge as kb
from company_catalog import (CompanyDocument, CompanyProject, CompanyFolder, can_read, can_manage,
                             backfill_company_projects, media_kind, classification_allowed, locked_scalar)
from company_workspace import CATEGORIES, validate_acl, validate_tags, validate_confidentiality, schedule_document
from database import SessionLocal
from models import User
from company_audit import record, snapshot, mark_modified
from company_collections import EXPERIENCE_CATEGORIES
from company_catalog import effective_acl, shared_experience
from company_departments import Department

projects_router = APIRouter()


def clean_name(value):
    value = value.strip()
    if not value or value in ('.', '..') or any(ord(c) < 32 or c in '/\\' for c in value):
        raise HTTPException(422, '名称不能为空，不能包含斜杠或控制字符。')
    return value


def find_project(db, project_id, user, manage=False):
    query = select(CompanyProject).where(CompanyProject.id == project_id)
    project = locked_scalar(db, query) if manage else db.scalar(query)
    if not project or project.index_id != kb.settings()['index_id'] or not can_read(project, user):
        raise HTTPException(404, '项目不存在或没有访问权限。')
    if manage and not can_manage(project, user):
        raise HTTPException(403, '只有项目创建者或管理员可以编辑目录与上传资料。')
    return project


def find_folder(db, project_id, folder_id):
    if not folder_id:
        return None
    folder = db.get(CompanyFolder, folder_id)
    if not folder or folder.project_id != project_id or folder.deleted_at:
        raise HTTPException(404, '目录不存在或不属于当前项目。')
    return folder


def project_values(project):
    return dict(project=project.name, industry=project.industry, department=project.department, category=project.category,
        review=project.review, confidentiality=project.confidentiality, visibility=project.visibility,
        readers=list(project.readers or []), tags=list(project.tags or [])) | effective_acl(project)


def restrict_to_project(values, project):
    """Project ACL is a ceiling. File exceptions may be narrower, never broader."""
    result = dict(values)
    if shared_experience(project):
        return result | effective_acl(project)
    result['confidentiality'] = validate_confidentiality(result['confidentiality'])
    result['readers'] = validate_acl(result['visibility'], result['readers'])
    rank = {'internal': 0, 'secret': 1}
    ceiling = validate_confidentiality(project.confidentiality)
    if rank[result['confidentiality']] < rank[ceiling]:
        result['confidentiality'] = ceiling
    if project.visibility == 'restricted' or project.confidentiality != 'internal':
        readers = list(project.readers or [])
        if result['visibility'] == 'restricted':
            readers = [name for name in result['readers'] if name in readers]
        result['visibility'], result['readers'] = 'restricted', readers
    return result


def serialize_project(project, user, docs, folders):
    values = {key: getattr(project, key) for key in ('id', 'name', 'owner', 'owner_user_id', 'industry', 'department',
        'category', 'review', 'confidentiality', 'visibility', 'description', 'created_by', 'modified_by')}
    values.update(tags=list(project.tags or []), readers=list(project.readers or []) if can_manage(project, user) else [],
        can_manage=can_manage(project, user), created_at=project.created_at.isoformat()+'Z',
        modified_at=project.updated_at.isoformat()+'Z', document_count=len(docs),
        ready_count=sum(doc.state == 'ready' and can_read(doc, user) for doc in docs),
        folder_count=len(folders), media_count=sum(bool(media_kind(doc)) and can_read(doc, user) for doc in docs))
    if shared_experience(project):
        values.update(effective_acl(project))
    return values


class ProjectValues(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    industry: str = Field(default='', max_length=100)
    department: Department | None = None
    description: str = Field(default='', max_length=10000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    category: str = '项目原件'
    review: str = '待复核'
    confidentiality: str = 'internal'
    visibility: str = 'members'
    readers: list[str] = Field(default_factory=list, max_length=100)

    def validated(self, user=None):
        values = self.model_dump()
        # Omission preserves compatibility with existing clients and generated archives.
        if values['department'] is None:
            values.pop('department')
        values['name'] = clean_name(values['name'])
        values['tags'] = validate_tags(values['tags'])
        if values['category'] in EXPERIENCE_CATEGORIES:
            values.update(confidentiality='internal', visibility='members', readers=[])
        values['confidentiality'] = validate_confidentiality(values['confidentiality'], user)
        if values['confidentiality'] != 'internal':
            values['visibility'] = 'restricted'
        values['readers'] = validate_acl(values['visibility'], values['readers'])
        if values['category'] not in CATEGORIES or values['review'] not in ('待复核', '已复核', '参考资料'):
            raise HTTPException(422, '分类或复核状态不正确。')
        return values


def commit(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '同一位置已有这个名称，请换一个名称。') from None


@projects_router.get('/projects')
def list_projects(user: User = Depends(kb.require_knowledge_user)):
    with SessionLocal() as db:
        projects = list(db.scalars(select(CompanyProject).where(
            CompanyProject.index_id == kb.settings()['index_id']).order_by(CompanyProject.updated_at.desc())))
        docs = list(db.scalars(select(CompanyDocument).where(CompanyDocument.index_id == kb.settings()['index_id'],
            CompanyDocument.state != 'deleted',
            (CompanyDocument.note_id == '') | (CompanyDocument.is_current == 1))))
        folders = list(db.scalars(select(CompanyFolder).join(CompanyProject).where(
            CompanyProject.index_id == kb.settings()['index_id'], CompanyFolder.deleted_at.is_(None))))
        allowed = {p.id for p in projects if can_read(p, user)}
        docs = [doc for doc in docs if classification_allowed(doc, user)]
        docs_by_project, folders_by_project = {}, {}
        for doc in docs:
            docs_by_project.setdefault(doc.knowledge_project_id, []).append(doc)
        for folder in folders:
            folders_by_project.setdefault(folder.project_id, []).append(folder)
        return {'projects': [serialize_project(p, user, docs_by_project.get(p.id, []),
                    folders_by_project.get(p.id, [])) for p in projects if p.id in allowed],
                'folders': [{'id': f.id, 'project_id': f.project_id, 'parent_id': f.parent_id, 'name': f.name}
                    for f in folders if f.project_id in allowed]}


@projects_router.post('/projects', status_code=201)
def create_project(data: ProjectValues, user: User = Depends(kb.require_knowledge_user)):
    values = data.validated(user)
    if data.department == '' and values['category'] not in EXPERIENCE_CATEGORIES:
        raise HTTPException(422, '请选择所属部门／栏目。')
    with SessionLocal() as db:
        project = CompanyProject(id=uuid.uuid4().hex, index_id=kb.settings()['index_id'],
            owner=user.username, owner_user_id=getattr(user, 'id', None), created_by=user.username, modified_by=user.username, **values)
        db.add(project)
        record(db, user, 'project.create', project)
        commit(db)
        return serialize_project(project, user, [], [])


@projects_router.patch('/projects/{project_id}')
async def edit_project(project_id: str, data: ProjectValues, user: User = Depends(kb.require_knowledge_user)):
    values = data.validated(user)
    with SessionLocal() as db:
        project = find_project(db, project_id, user, manage=True)
        if (values['category'] in EXPERIENCE_CATEGORIES) != (project.category in EXPERIENCE_CATEGORIES):
            raise HTTPException(422, '资料库与经验沉淀分别归档，不能通过修改分类跨库移动项目。')
        before = snapshot(project)
        docs = list(db.scalars(select(CompanyDocument).where(CompanyDocument.knowledge_project_id == project.id)))
        # Existing ingestion must finish before changing fields used in a media description index.
        renamed = values['name'] != project.name
        metadata_changed = any(values[key] != getattr(project, key) for key in ('name', 'industry', 'tags'))
        if metadata_changed and any(media_kind(d) and (d.inherits_project or renamed) and (d.state in
                ('queued', 'uploading', 'parsing', 'indexing', 'deleting') or (d.lease_until and d.lease_until > datetime.utcnow())) for d in docs):
            raise HTTPException(409, '项目内音视频说明仍在索引，请处理完成后再编辑项目。')
        acl_changed = any(values[key] != getattr(project, key) for key in ('confidentiality', 'visibility', 'readers'))
        for key, value in values.items():
            setattr(project, key, value)
        mark_modified(project, user)
        queued = []
        for doc in docs:
            doc_before = snapshot(doc)
            # Attribution belongs to the project even for legacy files with narrower ACLs.
            if 'department' in values:
                doc.department = project.department
            if renamed:
                doc.project = project.name
            if doc.inherits_project:
                for key, value in project_values(project).items():
                    setattr(doc, key, value)
            elif acl_changed:
                for key, value in restrict_to_project({key: getattr(doc, key) for key in
                        ('confidentiality', 'visibility', 'readers')}, project).items():
                    setattr(doc, key, value)
            if (metadata_changed and doc.inherits_project or renamed) and media_kind(doc) and doc.description.strip() and doc.state != 'deleted':
                doc.stale_cloud_id = doc.cloud_id or doc.stale_cloud_id
                doc.cloud_id, doc.job_id, doc.lease_id = None, '', ''
                doc.state, doc.status_message = 'queued', '项目属性已更新，等待重新索引文字说明'
                queued.append(doc.id)
            doc.updated_at = datetime.utcnow()
            if snapshot(doc) != doc_before:
                mark_modified(doc, user)
                record(db, user, 'document.inherit', doc, before=doc_before, details={'source': 'project.update'})
        record(db, user, 'project.update', project, before=before)
        commit(db)
        result = serialize_project(project, user, [d for d in docs if d.state != 'deleted'],
            list(db.scalars(select(CompanyFolder).where(CompanyFolder.project_id == project.id, CompanyFolder.deleted_at.is_(None)))))
    for doc_id in queued:
        import company_workspace as workspace
        workspace.schedule_document(doc_id)
    return result


def deletion_scope(db, project, user):
    from company_notes import CompanyNote
    docs = list(db.scalars(select(CompanyDocument).where(
        CompanyDocument.knowledge_project_id == project.id).order_by(CompanyDocument.id).with_for_update()))
    notes = list(db.scalars(select(CompanyNote).where(CompanyNote.project_id == project.id, CompanyNote.deleted_at.is_(None))
        .order_by(CompanyNote.id).with_for_update()))
    folders = list(db.scalars(select(CompanyFolder).where(CompanyFolder.project_id == project.id, CompanyFolder.deleted_at.is_(None))
        .order_by(CompanyFolder.id).with_for_update()))
    live = [d for d in docs if d.state != 'deleted']
    if any(not can_manage(d, user) for d in live) or any(not can_manage(n, user) for n in notes):
        raise HTTPException(403, '项目内含有你不能管理的资料或笔记，请联系管理员删除整个项目。')
    if any(d.state in ('queued', 'uploading', 'parsing', 'indexing', 'deleting') or
            (d.lease_until and d.lease_until > datetime.utcnow()) for d in live):
        raise HTTPException(409, '项目内仍有资料正在处理，请等待完成后再删除。')
    fingerprint = [snapshot(project), [(d.id, d.state, str(d.updated_at)) for d in docs],
        [(n.id, n.revision, str(n.updated_at)) for n in notes], [(f.id, f.name, f.parent_id) for f in folders]]
    token = hashlib.sha256(json.dumps(fingerprint, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    preview = {'project_id': project.id, 'name': project.name, 'document_count': len(live),
        'note_count': len(notes), 'folder_count': len(folders), 'confirmation': token}
    return preview, live, notes


@projects_router.get('/projects/{project_id}/deletion-preview')
def project_deletion_preview(project_id: str, user: User = Depends(kb.require_knowledge_user)):
    with SessionLocal() as db:
        project = find_project(db, project_id, user, manage=True)
        preview, _, _ = deletion_scope(db, project, user)
        return preview


class ProjectDeletion(BaseModel):
    confirmation: str = Field(pattern='^[a-f0-9]{64}$')


@projects_router.delete('/projects/{project_id}')
def delete_project(project_id: str, body: ProjectDeletion, user: User = Depends(kb.require_knowledge_user)):
    with SessionLocal() as db:
        project = find_project(db, project_id, user, manage=True)
        preview, docs, notes = deletion_scope(db, project, user)
        if body.confirmation != preview['confirmation']:
            raise HTTPException(409, '项目内容已变化，请重新查看删除范围并确认。')
        before = snapshot(project)
        for doc in docs:
            previous = snapshot(doc)
            doc.state = 'deleted'
            doc.status_message = '所属项目已删除'
            mark_modified(doc, user)
            record(db, user, 'document.delete', doc, before=previous, details={'source': 'project.delete'})
        for note in notes:
            note.deleted_at = datetime.utcnow()
            record(db, user, 'note.delete', note, before=snapshot(note), details={'source': 'project.delete'})
        project.deleted_at = datetime.utcnow()
        # Retain the tree and originals for controlled recovery; release the active name.
        project.name = '已删除项目 · ' + project.id
        mark_modified(project, user)
        event = record(db, user, 'project.delete', project, before=before,
            details={**preview, 'deleted_at': project.deleted_at.isoformat() + 'Z'})
        event.target_name = preview['name']
        db.commit()
        return {'deleted': True, **{key: preview[key] for key in ('project_id', 'document_count', 'note_count', 'folder_count')}}


class FolderValues(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: str = Field(default='', max_length=64)


@projects_router.post('/projects/{project_id}/folders', status_code=201)
def create_folder(project_id: str, data: FolderValues, user: User = Depends(kb.require_knowledge_user)):
    with SessionLocal() as db:
        project = find_project(db, project_id, user, manage=True)
        parent = find_folder(db, project.id, data.parent_id)
        depth = 1
        while parent:
            depth += 1
            if depth > 12:
                raise HTTPException(422, '目录最多支持 12 层。')
            parent = find_folder(db, project.id, parent.parent_id)
        folder = CompanyFolder(id=uuid.uuid4().hex, project_id=project.id, parent_id=data.parent_id,
            name=clean_name(data.name))
        db.add(folder)
        mark_modified(project, user)
        record(db, user, 'folder.create', folder)
        commit(db)
        return {'id': folder.id, 'project_id': folder.project_id, 'parent_id': folder.parent_id, 'name': folder.name}


@projects_router.patch('/projects/{project_id}/folders/{folder_id}')
def edit_folder(project_id: str, folder_id: str, data: FolderValues, user: User = Depends(kb.require_knowledge_user)):
    with SessionLocal() as db:
        project = find_project(db, project_id, user, manage=True)
        folder = find_folder(db, project.id, folder_id)
        if not folder:
            raise HTTPException(404, '目录不存在。')
        before = snapshot(folder)
        # Renaming only; parent changes require a separate explicit move operation.
        folder.name = clean_name(data.name)
        folder.updated_at = datetime.utcnow()
        mark_modified(project, user)
        record(db, user, 'folder.update', folder, before=before)
        commit(db)
        return {'id': folder.id, 'project_id': folder.project_id, 'parent_id': folder.parent_id, 'name': folder.name}


def folder_deletion_scope(db, project, folder, user):
    """Lock the same project as uploads/notes, then resolve the entire live subtree."""
    from company_notes import CompanyNote
    all_folders = list(db.scalars(select(CompanyFolder).where(CompanyFolder.project_id == project.id,
        CompanyFolder.deleted_at.is_(None)).order_by(CompanyFolder.id).with_for_update()))
    folders, seen = [folder], {folder.id}
    for parent in folders:
        for child in all_folders:
            if child.parent_id == parent.id and child.id not in seen:
                seen.add(child.id)
                folders.append(child)
    docs = list(db.scalars(select(CompanyDocument).where(CompanyDocument.knowledge_project_id == project.id,
        CompanyDocument.folder_id.in_(seen)).order_by(CompanyDocument.id).with_for_update()))
    notes = list(db.scalars(select(CompanyNote).where(CompanyNote.project_id == project.id,
        CompanyNote.folder_id.in_(seen), CompanyNote.deleted_at.is_(None)).order_by(CompanyNote.id).with_for_update()))
    live = [doc for doc in docs if doc.state != 'deleted']
    if any(not can_manage(obj, user) for obj in [*live, *notes]):
        raise HTTPException(403, '目录内含有你不能管理的资料或笔记，请联系管理员删除整个目录。')
    if any(doc.state in ('queued', 'uploading', 'parsing', 'indexing', 'deleting') or
            (doc.lease_until and doc.lease_until > datetime.utcnow()) for doc in live):
        raise HTTPException(409, '目录内仍有资料正在处理，请等待完成后再删除。')
    fingerprint = [snapshot(project), [(f.id, f.name, f.parent_id, str(f.updated_at)) for f in folders],
        [(d.id, snapshot(d), str(d.updated_at)) for d in docs],
        [(n.id, snapshot(n), str(n.updated_at)) for n in notes]]
    token = hashlib.sha256(json.dumps(fingerprint, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {'folder_id': folder.id, 'name': folder.name, 'folder_count': len(folders)-1,
        'document_count': len(live), 'note_count': len(notes), 'confirmation': token,
        'recyclable': bool(len(folders)>1 or live or notes)}, folders, live, notes


@projects_router.get('/projects/{project_id}/folders/{folder_id}/deletion-preview')
def folder_deletion_preview(project_id: str, folder_id: str, user: User = Depends(kb.require_knowledge_user)):
    with SessionLocal() as db:
        project = find_project(db, project_id, user, manage=True)
        folder = find_folder(db, project.id, folder_id)
        if not folder:
            raise HTTPException(404, '目录不存在。')
        return folder_deletion_scope(db, project, folder, user)[0]


@projects_router.delete('/projects/{project_id}/folders/{folder_id}')
def delete_folder(project_id: str, folder_id: str, body: ProjectDeletion | None = None,
                  user: User = Depends(kb.require_knowledge_user)):
    with SessionLocal() as db:
        project = find_project(db, project_id, user, manage=True)
        folder = find_folder(db, project.id, folder_id)
        if not folder:
            raise HTTPException(404, '目录不存在。')
        preview, folders, docs, notes = folder_deletion_scope(db, project, folder, user)
        # Old clients may still delete genuinely empty folders; never cascade without a preview token.
        if (body and body.confirmation != preview['confirmation']) or (preview['recyclable'] and not body):
            raise HTTPException(409, '目录内容已变化，请重新查看删除范围并确认。')
        if preview['recyclable']:
            for doc in docs:
                before = snapshot(doc)
                doc.state, doc.status_message = 'deleted', '所属目录已删除'
                mark_modified(doc, user)
                record(db, user, 'document.delete', doc, before=before, details={'source': 'folder.delete'})
            for note in notes:
                before = snapshot(note)
                note.deleted_at = datetime.utcnow()
                mark_modified(note, user)
                record(db, user, 'note.delete', note, before=before, details={'source': 'folder.delete'})
            # Capture children before parents so the recycle records form one recoverable group.
            for child in reversed(folders):
                before = snapshot(child)
                child.deleted_at = datetime.utcnow()
                child.name = '已删除目录 · ' + child.id
                child.updated_at = datetime.utcnow()
                event = record(db, user, 'folder.delete', child, before=before,
                    details={'source': 'folder.delete', 'recyclable': True})
                event.target_name = before['name']
        else:
            record(db, user, 'folder.delete', folder, before=snapshot(folder), details={'deleted': True})
            db.delete(folder)
        mark_modified(project, user)
        commit(db)
        return {'deleted': True, **preview}
