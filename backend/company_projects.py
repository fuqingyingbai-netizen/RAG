"""Persistent project/folder workspaces, with inherited upload defaults."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import company_knowledge as kb
from company_catalog import (CompanyDocument, CompanyProject, CompanyFolder, can_read, can_manage,
                             backfill_company_projects, media_kind)
from company_workspace import CATEGORIES, validate_acl, validate_tags, validate_confidentiality, schedule_document
from database import SessionLocal
from models import User
from company_audit import record, snapshot, mark_modified

projects_router = APIRouter()


def clean_name(value):
    value = value.strip()
    if not value or value in ('.', '..') or any(ord(c) < 32 or c in '/\\' for c in value):
        raise HTTPException(422, '名称不能为空，不能包含斜杠或控制字符。')
    return value


def find_project(db, project_id, user, manage=False):
    project = db.scalar(select(CompanyProject).where(CompanyProject.id == project_id).with_for_update())
    if not project or project.index_id != kb.settings()['index_id'] or not can_read(project, user):
        raise HTTPException(404, '项目不存在或没有访问权限。')
    if manage and not can_manage(project, user):
        raise HTTPException(403, '只有项目创建者或管理员可以编辑目录与上传资料。')
    return project


def find_folder(db, project_id, folder_id):
    if not folder_id:
        return None
    folder = db.get(CompanyFolder, folder_id)
    if not folder or folder.project_id != project_id:
        raise HTTPException(404, '目录不存在或不属于当前项目。')
    return folder


def project_values(project):
    return dict(project=project.name, industry=project.industry, category=project.category,
        review=project.review, confidentiality=project.confidentiality, visibility=project.visibility,
        readers=list(project.readers or []), tags=list(project.tags or []))


def restrict_to_project(values, project):
    """Project ACL is a ceiling. File exceptions may be narrower, never broader."""
    result = dict(values)
    validate_confidentiality(result['confidentiality'])
    result['readers'] = validate_acl(result['visibility'], result['readers'])
    rank = {'internal': 0, 'confidential': 1, 'secret': 2}
    if rank[result['confidentiality']] < rank[project.confidentiality]:
        result['confidentiality'] = project.confidentiality
    if project.visibility == 'restricted' or project.confidentiality != 'internal':
        readers = list(project.readers or [])
        if result['visibility'] == 'restricted':
            readers = [name for name in result['readers'] if name in readers]
        result['visibility'], result['readers'] = 'restricted', readers
    return result


def serialize_project(project, user, docs, folders):
    values = {key: getattr(project, key) for key in ('id', 'name', 'owner', 'owner_user_id', 'industry',
        'category', 'review', 'confidentiality', 'visibility', 'description', 'created_by', 'modified_by')}
    values.update(tags=list(project.tags or []), readers=list(project.readers or []) if can_manage(project, user) else [],
        can_manage=can_manage(project, user), created_at=project.created_at.isoformat()+'Z',
        modified_at=project.updated_at.isoformat()+'Z', document_count=len(docs),
        ready_count=sum(doc.state == 'ready' and can_read(doc, user) for doc in docs),
        folder_count=len(folders), media_count=sum(bool(media_kind(doc)) and can_read(doc, user) for doc in docs))
    return values


class ProjectValues(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    industry: str = Field(default='', max_length=100)
    description: str = Field(default='', max_length=10000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    category: str = '项目原件'
    review: str = '待复核'
    confidentiality: str = 'internal'
    visibility: str = 'members'
    readers: list[str] = Field(default_factory=list, max_length=100)

    def validated(self):
        values = self.model_dump()
        values['name'] = clean_name(values['name'])
        values['tags'] = validate_tags(values['tags'])
        validate_confidentiality(values['confidentiality'])
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
        backfill_company_projects(db.get_bind())
        projects = list(db.scalars(select(CompanyProject).where(
            CompanyProject.index_id == kb.settings()['index_id']).order_by(CompanyProject.updated_at.desc())))
        docs = list(db.scalars(select(CompanyDocument).where(CompanyDocument.index_id == kb.settings()['index_id'],
            CompanyDocument.state != 'deleted')))
        folders = list(db.scalars(select(CompanyFolder).join(CompanyProject).where(
            CompanyProject.index_id == kb.settings()['index_id'])))
        allowed = {p.id for p in projects if can_read(p, user)}
        return {'projects': [serialize_project(p, user, [d for d in docs if d.knowledge_project_id == p.id],
                    [f for f in folders if f.project_id == p.id]) for p in projects if p.id in allowed],
                'folders': [{'id': f.id, 'project_id': f.project_id, 'parent_id': f.parent_id, 'name': f.name}
                    for f in folders if f.project_id in allowed]}


@projects_router.post('/projects', status_code=201)
def create_project(data: ProjectValues, user: User = Depends(kb.require_knowledge_user)):
    values = data.validated()
    with SessionLocal() as db:
        project = CompanyProject(id=uuid.uuid4().hex, index_id=kb.settings()['index_id'],
            owner=user.username, owner_user_id=getattr(user, 'id', None), created_by=user.username, modified_by=user.username, **values)
        db.add(project)
        record(db, user, 'project.create', project)
        commit(db)
        return serialize_project(project, user, [], [])


@projects_router.patch('/projects/{project_id}')
async def edit_project(project_id: str, data: ProjectValues, user: User = Depends(kb.require_knowledge_user)):
    values = data.validated()
    with SessionLocal() as db:
        project = find_project(db, project_id, user, manage=True)
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
            list(db.scalars(select(CompanyFolder).where(CompanyFolder.project_id == project.id))))
    for doc_id in queued:
        import company_workspace as workspace
        workspace.schedule_document(doc_id)
    return result


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


@projects_router.delete('/projects/{project_id}/folders/{folder_id}')
def delete_empty_folder(project_id: str, folder_id: str, user: User = Depends(kb.require_knowledge_user)):
    with SessionLocal() as db:
        project = find_project(db, project_id, user, manage=True)
        folder = find_folder(db, project.id, folder_id)
        if not folder:
            raise HTTPException(404, '目录不存在。')
        if db.scalar(select(CompanyFolder.id).where(CompanyFolder.project_id == project.id,
                CompanyFolder.parent_id == folder.id).limit(1)) or db.scalar(select(CompanyDocument.id).where(
                CompanyDocument.knowledge_project_id == project.id, CompanyDocument.folder_id == folder.id,
                CompanyDocument.state != 'deleted').limit(1)):
            raise HTTPException(409, '目录不为空，请先处理其中的文件和子目录。')
        record(db, user, 'folder.delete', folder, before=snapshot(folder), details={'deleted': True})
        db.delete(folder)
        mark_modified(project, user)
        commit(db)
        return {'deleted': True}
