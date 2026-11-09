"""Private autosaved drafts, immutable publications and project-scoped note assets."""
import asyncio
import copy
import hashlib
import io
import json
import uuid
import zipfile
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, select, update
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
import company_knowledge as kb
import company_workspace as ws
from company_catalog import CompanyDocument, CompanyProject, CompanyAuditEvent, can_read, can_manage, document_store
from company_projects import find_project, find_folder, project_values
from company_collections import EXPERIENCE_CATEGORIES
from company_audit import record, snapshot, mark_modified
from company_note_format import EMPTY, checked_content, image_ids, plain_text, markdown, word_document
from company_watermark import ExportIdentity, WatermarkError, export_copy

notes_router = APIRouter()


class CompanyNote(Base):
    __tablename__ = 'company_notes'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    index_id: Mapped[str] = mapped_column(String(100), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('company_projects.id'), index=True)
    folder_id: Mapped[str] = mapped_column(String(64), default='')
    owner: Mapped[str] = mapped_column(String(100))
    owner_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String(100))
    modified_by: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200), default='未命名笔记')
    content: Mapped[dict] = mapped_column(JSON, default=lambda: copy.deepcopy(EMPTY))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    published_revision: Mapped[int] = mapped_column(Integer, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_document_id: Mapped[str] = mapped_column(String(64), default='')
    pending_document_id: Mapped[str] = mapped_column(String(64), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CompanyNoteAsset(Base):
    __tablename__ = 'company_note_assets'
    __table_args__ = (UniqueConstraint('note_id','sha256',name='uq_company_note_image'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    note_id: Mapped[str] = mapped_column(ForeignKey('company_notes.id'), index=True)
    object_key: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    ocr_text: Mapped[str] = mapped_column(String(20000), default='')
    ocr_status: Mapped[str] = mapped_column(String(30), default='not_requested')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CompanyNotePublication(Base):
    __tablename__ = 'company_note_publications'
    __table_args__ = (UniqueConstraint('note_id','revision',name='uq_company_note_publication'),)
    id: Mapped[str] = mapped_column(ForeignKey('company_documents.id'), primary_key=True)
    note_id: Mapped[str] = mapped_column(ForeignKey('company_notes.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[dict] = mapped_column(JSON)
    published_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


def editable(note,user):
    return can_manage(note,user)


def find_note(db,note_id,user,manage=False):
    note=db.get(CompanyNote,note_id)
    if not note or note.deleted_at or note.index_id!=kb.settings()['index_id']:
        raise HTTPException(404,'笔记不存在或没有访问权限。')
    project=find_project(db,note.project_id,user,manage=manage)
    if project.category not in EXPERIENCE_CATEGORIES:
        raise HTTPException(404,'笔记不属于经验沉淀。')
    if manage:
        note=db.scalar(select(CompanyNote).where(CompanyNote.id==note_id).with_for_update())
        if not editable(note,user):raise HTTPException(403,'只有项目创建者或管理员可以修改这篇笔记。')
    elif not editable(note,user):
        doc=db.get(CompanyDocument,note.current_document_id) if note.current_document_id else None
        if not doc or doc.state=='deleted' or not can_read(doc,user):
            raise HTTPException(404,'草稿尚未发布，或没有访问权限。')
    return note,project


def public_view(db,note,user,content=True):
    manager=editable(note,user)
    current=db.get(CompanyDocument,note.current_document_id) if note.current_document_id else None
    pending=db.get(CompanyDocument,note.pending_document_id) if note.pending_document_id else None
    publication=db.get(CompanyNotePublication,note.current_document_id) if current and current.state!='deleted' else None
    result={'id':note.id,'project_id':note.project_id,'folder_id':note.folder_id,
        'title':note.title if manager else publication.title,'revision':note.revision if manager else publication.revision,
        'created_by':note.created_by,'modified_by':note.modified_by if manager else publication.published_by,
        'can_manage':manager,'published_revision':note.published_revision if manager else publication.revision,
        'indexed_revision':publication.revision if publication and current.state=='ready' else 0,
        'current_document_id':note.current_document_id if publication else '',
        'pending_document_id':note.pending_document_id if manager else '',
        'index_state':pending.state if pending else current.state if current else '',
        'index_message':pending.status_message if pending else current.status_message if current else '',
        'has_unpublished_changes':manager and note.revision!=note.published_revision,
        'created_at':note.created_at.isoformat()+'Z','updated_at':note.updated_at.isoformat()+'Z'}
    if content:result['content']=copy.deepcopy(note.content if manager else publication.content)
    return result


class NewNote(BaseModel):
    project_id: str = Field(min_length=1,max_length=64)
    folder_id: str = Field(default='',max_length=64)
    title: str = Field(default='未命名笔记',min_length=1,max_length=200)


def clean_title(value):
    title=value.strip() or '未命名笔记'
    if any(ord(char)<32 for char in title):raise HTTPException(422,'标题不能包含换行或控制字符。')
    return title


@notes_router.post('/notes',status_code=201)
def create_note(body:NewNote,user=Depends(kb.require_knowledge_user)):
    with ws.SessionLocal() as db:
        project=find_project(db,body.project_id,user,manage=True);find_folder(db,project.id,body.folder_id)
        if project.category not in EXPERIENCE_CATEGORIES:raise HTTPException(422,'图文笔记仅保存在经验沉淀，请选择经验项目。')
        note=CompanyNote(id=uuid.uuid4().hex,index_id=project.index_id,project_id=project.id,folder_id=body.folder_id,
            owner=project.owner,owner_user_id=project.owner_user_id,created_by=user.username,modified_by=user.username,
            title=clean_title(body.title),content=copy.deepcopy(EMPTY),revision=1,published_revision=0,
            current_document_id='',pending_document_id='')
        db.add(note);db.flush();record(db,user,'note.create',note);db.commit()
        return public_view(db,note,user)


@notes_router.get('/notes')
def notes(project_id:str='',folder_id:str='',user=Depends(kb.require_knowledge_user)):
    with ws.SessionLocal() as db:
        query=select(CompanyNote).where(CompanyNote.index_id==kb.settings()['index_id']).order_by(CompanyNote.updated_at.desc())
        if project_id:query=query.where(CompanyNote.project_id==project_id)
        if folder_id:query=query.where(CompanyNote.folder_id==folder_id)
        result=[]
        for note in db.scalars(query):
            # This list is a draft/edit workspace; published documents use the normal catalogue.
            project=db.get(CompanyProject,note.project_id)
            if project and project.category in EXPERIENCE_CATEGORIES and can_read(project,user) and editable(note,user):
                result.append(public_view(db,note,user,content=False))
        return {'notes':result}


@notes_router.get('/notes/{note_id}')
def read_note(note_id:str,user=Depends(kb.require_knowledge_user)):
    with ws.SessionLocal() as db:
        note,_=find_note(db,note_id,user);return public_view(db,note,user)


def note_deletion_scope(db,note,user):
    docs=list(db.scalars(select(CompanyDocument).where(CompanyDocument.note_id==note.id)
        .order_by(CompanyDocument.id).with_for_update()))
    assets=list(db.scalars(select(CompanyNoteAsset).where(CompanyNoteAsset.note_id==note.id).order_by(CompanyNoteAsset.id)))
    if any(not can_manage(d,user) for d in docs if d.state!='deleted'):
        raise HTTPException(403,'笔记包含无管理权限的发布文件，请联系管理员。')
    if any(d.state in ('queued','uploading','parsing','indexing','deleting') or
        (d.lease_until and d.lease_until>datetime.utcnow()) for d in docs if d.state!='deleted'):
        raise HTTPException(409,'笔记仍在发布或建立索引，请处理完成后再删除。')
    token=hashlib.sha256(json.dumps([note.id,note.revision,str(note.updated_at),
        [(d.id,d.state,str(d.updated_at)) for d in docs],[a.id for a in assets]],ensure_ascii=False).encode()).hexdigest()
    return {'title':note.title,'confirmation':token,'publication_count':sum(d.state!='deleted' for d in docs),
        'image_count':len(assets)},docs


@notes_router.get('/notes/{note_id}/deletion-preview')
def note_deletion_preview(note_id:str,user=Depends(kb.require_knowledge_user)):
    with ws.SessionLocal() as db:
        note,_=find_note(db,note_id,user,manage=True)
        preview,_=note_deletion_scope(db,note,user)
        return preview


class NoteDeletion(BaseModel):
    confirmation:str = Field(pattern='^[a-f0-9]{64}$')


@notes_router.delete('/notes/{note_id}')
def delete_note(note_id:str,body:NoteDeletion,user=Depends(kb.require_knowledge_user)):
    with ws.SessionLocal() as db:
        note,_=find_note(db,note_id,user,manage=True)
        preview,docs=note_deletion_scope(db,note,user)
        if body.confirmation!=preview['confirmation']:
            raise HTTPException(409,'笔记内容已变化，请重新查看删除范围并确认。')
        for doc in docs:
            if doc.state=='deleted':continue
            before=snapshot(doc);doc.state='deleted';doc.status_message='所属笔记已删除';mark_modified(doc,user)
            record(db,user,'document.delete',doc,before=before,details={'source':'note.delete'})
        before=snapshot(note);note.deleted_at=datetime.utcnow();mark_modified(note,user)
        record(db,user,'note.delete',note,before=before,details={**preview,'deleted':True})
        db.commit()
        return {'deleted':True}


class NoteEdit(BaseModel):
    revision:int = Field(ge=1)
    title:str = Field(min_length=1,max_length=200)
    content:dict


@notes_router.patch('/notes/{note_id}')
def edit_note(note_id:str,body:NoteEdit,user=Depends(kb.require_knowledge_user)):
    with ws.SessionLocal() as db:
        note,_=find_note(db,note_id,user,manage=True)
        if note.revision!=body.revision:raise HTTPException(409,'这篇笔记已在其他窗口更新。本窗口内容仍保留，请先查看最新版本再合并。')
        assets=set(db.scalars(select(CompanyNoteAsset.id).where(CompanyNoteAsset.note_id==note.id)))
        clean=checked_content(body.content,assets);before=snapshot(note);title=clean_title(body.title)
        if clean!=note.content or title!=note.title:
            note.content=clean;note.title=title;note.revision+=1;mark_modified(note,user)
            record(db,user,'note.save',note,before=before);db.commit()
        return public_view(db,note,user)


def normalize_image(payload):
    from PIL import Image,ImageOps
    try:
        with Image.open(io.BytesIO(payload)) as original:
            if original.format not in ('PNG','JPEG','WEBP') or original.width*original.height>40_000_000:
                raise ValueError()
            original.load();image=ImageOps.exif_transpose(original).convert('RGB')
            output=io.BytesIO();image.save(output,'PNG');data=output.getvalue()
            if len(data)>24*1024*1024:raise ValueError()
            return data,image.width,image.height
    except Exception:
        raise HTTPException(422,'请使用有效的 PNG、JPG 或 WebP 图片，单张最多 12 MB、4000 万像素。') from None


@notes_router.post('/notes/{note_id}/images',status_code=201)
async def add_image(note_id:str,file:UploadFile=File(...),user=Depends(kb.require_knowledge_user)):
    with ws.SessionLocal() as db:find_note(db,note_id,user,manage=True)
    payload=await file.read(12*1024*1024+1);await file.close()
    if len(payload)>12*1024*1024:raise HTTPException(413,'单张图片最多 12 MB，请压缩后重试。')
    data,width,height=await asyncio.to_thread(normalize_image,payload);digest=hashlib.sha256(data).hexdigest()
    return await asyncio.to_thread(_save_image,note_id,user,data,width,height,digest)


def _save_image(note_id,user,data,width,height,digest):
    with ws.SessionLocal() as db:
        note,_=find_note(db,note_id,user,manage=True)
        asset=db.scalar(select(CompanyNoteAsset).where(CompanyNoteAsset.note_id==note.id,CompanyNoteAsset.sha256==digest))
        if not asset:
            count=len(list(db.scalars(select(CompanyNoteAsset.id).where(CompanyNoteAsset.note_id==note.id))))
            if count>=100:raise HTTPException(422,'每篇笔记最多保存 100 张图片，请拆分笔记。')
            asset=CompanyNoteAsset(id=uuid.uuid4().hex,note_id=note.id,sha256=digest,width=width,height=height,
                object_key='notes/'+note.id+'/'+uuid.uuid4().hex+'.png',ocr_text='',ocr_status='not_requested')
            document_store().put_bytes(asset.object_key,data,'image/png')
            try:
                db.add(asset);record(db,user,'note.image_upload',note,before=snapshot(note),details={'asset_id':asset.id,'sha256':digest});db.commit()
            except Exception:
                db.rollback();document_store().delete_object(asset.object_key);raise
        return {'id':asset.id,'width':asset.width,'height':asset.height}


def find_asset(db,note,asset_id,user):
    asset=db.get(CompanyNoteAsset,asset_id)
    if not asset or asset.note_id!=note.id:raise HTTPException(404,'图片不存在或没有访问权限。')
    if not editable(note,user):
        publication=db.get(CompanyNotePublication,note.current_document_id)
        if not publication or asset.id not in image_ids(publication.content):raise HTTPException(404,'图片尚未发布。')
    return asset


def identity(user):
    return ExportIdentity(user.username,getattr(user,'id',None),datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),uuid.uuid4().hex)


@notes_router.get('/notes/{note_id}/images/{asset_id}')
async def image(note_id:str,asset_id:str,user=Depends(kb.require_knowledge_user)):
    with ws.SessionLocal() as db:
        note,_=find_note(db,note_id,user);asset=find_asset(db,note,asset_id,user);key=asset.object_key
    who=identity(user)
    data=await asyncio.to_thread(document_store().get_bytes,key)
    try:data,_,_=await asyncio.to_thread(export_copy,data,'PNG','image.png',who)
    except WatermarkError as error:raise HTTPException(error.status,str(error)) from None
    with ws.SessionLocal() as db:
        note,_=find_note(db,note_id,user);find_asset(db,note,asset_id,user)
        record(db,user,'note.image_preview',note,before=snapshot(note),event_id=who.trace_id,details={'trace_id':who.trace_id,'asset_id':asset_id});db.commit()
    return Response(data,media_type='image/png',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


def recognize_image(data):
    import numpy as np
    from PIL import Image
    from company_ocr import _recognize
    with Image.open(io.BytesIO(data)) as picture:
        picture.thumbnail((2500,2500));lines=_recognize(np.asarray(picture.convert('RGB')))
    return '\n'.join(str(row[1]) for row in lines if len(row)>=3 and float(row[2])>=.5)[:20000]


@notes_router.post('/notes/{note_id}/images/{asset_id}/ocr')
async def ocr_image(note_id:str,asset_id:str,user=Depends(kb.require_knowledge_user)):
    with ws.SessionLocal() as db:
        note,_=find_note(db,note_id,user,manage=True);asset=find_asset(db,note,asset_id,user);key=asset.object_key
    try:
        text=await asyncio.to_thread(recognize_image,await asyncio.to_thread(document_store().get_bytes,key))
    except Exception:
        raise HTTPException(503,'图片文字识别暂不可用。图片已保存，可以手动填写图片说明后发布。') from None
    with ws.SessionLocal() as db:
        note,_=find_note(db,note_id,user,manage=True);asset=find_asset(db,note,asset_id,user)
        asset.ocr_text=text;asset.ocr_status='recognized' if text else 'no_text'
        record(db,user,'note.image_ocr',note,before=snapshot(note),details={'asset_id':asset.id,'characters':len(text)});db.commit()
    return {'text':text,'message':'识别文字可在编辑器中校正；发布后参与检索。' if text else '未识别到清晰文字，请补充图片说明。'}


def asset_payloads(db,note,content):
    result={}
    total=0
    for asset_id in image_ids(content):
        asset=db.get(CompanyNoteAsset,asset_id)
        if not asset or asset.note_id!=note.id:raise HTTPException(422,'笔记图片缺失，请重新上传。')
        data=document_store().get_bytes(asset.object_key);total+=len(data)
        if total>32*1024*1024:raise HTTPException(413,'当前笔记的图片总量超过 32 MB，请压缩图片或拆分笔记后再发布、导出。')
        result[asset_id]=data
    return result


class NoteRevision(BaseModel):
    revision:int = Field(ge=1)


def _publish_note(note_id,body,user):
    with ws.SessionLocal() as db:
        note,project=find_note(db,note_id,user,manage=True)
        if note.revision!=body.revision:raise HTTPException(409,'请先保存当前内容，再发布最新草稿。')
        if not plain_text(note.content).strip() and not image_ids(note.content):raise HTTPException(422,'请先写正文或插入图片，再发布笔记。')
        existing=db.scalar(select(CompanyNotePublication).where(CompanyNotePublication.note_id==note.id,CompanyNotePublication.revision==note.revision))
        pending=db.get(CompanyDocument,note.pending_document_id) if note.pending_document_id else None
        if existing:
            doc=db.get(CompanyDocument,existing.id)
            if doc.state=='deleted':raise HTTPException(409,'这个发布文件已被移除，请编辑保存后重新发布。')
            if doc.state=='failed':
                if doc.lease_until and doc.lease_until>datetime.utcnow():raise HTTPException(409,'原任务仍在退出，请稍后重试。')
                if '时间较长' not in doc.status_message:doc.job_id=''
                before=snapshot(note);doc.state='queued';doc.status_message='正在重试笔记索引'
                note.pending_document_id=doc.id
                record(db,user,'note.retry',note,before=before,details={'document_id':doc.id});db.commit()
            return public_view(db,note,user)
        if pending and pending.state in ('queued','uploading','parsing','indexing'):
            raise HTTPException(409,'上一版仍在建立索引。草稿可以继续保存，索引完成后再发布。')
        before=snapshot(note);images=asset_payloads(db,note,note.content)
        payload=word_document(note.title,note.content,images,revision=note.revision)
        if len(payload)>32*1024*1024:raise HTTPException(413,'图文笔记超过 32 MB，请压缩图片或拆分后发布。')
        # Stable identity prevents different notes with the same title colliding in the file catalogue.
        filename=note.title.replace('/','_').replace('\\','_')+' · '+note.id[:8]+'.docx'
        version=1+max([d.version for d in db.scalars(select(CompanyDocument).where(CompanyDocument.note_id==note.id))] or [0])
        doc=CompanyDocument(id=uuid.uuid4().hex,index_id=note.index_id,note_id=note.id,
            title=filename,format='DOCX',size=len(payload),sha256=hashlib.sha256(payload).hexdigest(),
            object_key='notes/'+note.id+'/publications/'+uuid.uuid4().hex+'.docx',owner=note.owner,owner_user_id=note.owner_user_id,
            uploaded_by=user.username,uploaded_by_user_id=getattr(user,'id',None),modified_by=user.username,
            knowledge_project_id=note.project_id,folder_id=note.folder_id,inherits_project=1,
            version=version,is_current=int(not note.current_document_id),state='queued',status_message='笔记已发布，等待解析与索引',parser='DOCMIND',
            **project_values(project))
        document_store().put_bytes(doc.object_key,payload,'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        try:
            db.add(doc);db.flush()
            db.add(CompanyNotePublication(id=doc.id,note_id=note.id,revision=note.revision,title=note.title,content=copy.deepcopy(note.content),published_by=user.username))
            note.published_revision=note.revision;note.pending_document_id=doc.id
            if not note.current_document_id:note.current_document_id=doc.id
            mark_modified(note,user);record(db,user,'note.publish',note,before=before,details={'document_id':doc.id,'version':version})
            record(db,user,'document.upload',doc);db.commit()
        except Exception:
            db.rollback();document_store().delete_object(doc.object_key);raise
        result=public_view(db,note,user)
    return result


@notes_router.post('/notes/{note_id}/publish')
async def publish_note(note_id:str,body:NoteRevision,user=Depends(kb.require_knowledge_user)):
    result=await asyncio.to_thread(_publish_note,note_id,body,user)
    if result.get('pending_document_id'):ws.schedule_document(result['pending_document_id'])
    return result


def publication_lock(db,doc):
    if not doc.note_id:return
    db.scalar(select(CompanyProject).where(CompanyProject.id==doc.knowledge_project_id).with_for_update())
    db.scalar(select(CompanyNote).where(CompanyNote.id==doc.note_id).with_for_update())


def publication_ready(db,doc_id):
    doc=db.get(CompanyDocument,doc_id)
    if not doc or not doc.note_id:return
    note=db.get(CompanyNote,doc.note_id)
    if not note or note.pending_document_id!=doc.id:return
    db.execute(update(CompanyDocument).where(CompanyDocument.note_id==note.id,CompanyDocument.id!=doc.id).values(is_current=0,updated_at=datetime.utcnow()))
    doc.is_current=1;note.current_document_id=doc.id;note.pending_document_id=''


@notes_router.get('/notes/{note_id}/history')
def note_history(note_id:str,user=Depends(kb.require_knowledge_user)):
    with ws.SessionLocal() as db:
        note,_=find_note(db,note_id,user,manage=True)
        rows=db.scalars(select(CompanyAuditEvent).where(CompanyAuditEvent.target_type=='note',CompanyAuditEvent.target_id==note.id)
            .order_by(CompanyAuditEvent.created_at.desc()).limit(100))
        return {'events':[{'id':row.id,'action':row.action,'actor':row.actor_username,'created_at':row.created_at.isoformat()+'Z','changes':row.changes} for row in rows]}


def export_note_bytes(title,content,images,fmt,who):
    if fmt=='docx':
        marked={key:export_copy(data,'PNG','image.png',who)[0] for key,data in images.items()}
        data=word_document(title,content,marked)
        return export_copy(data,'DOCX',title+'.docx',who)[0],'application/vnd.openxmlformats-officedocument.wordprocessingml.document','.docx'
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        text=markdown(title,content).encode('utf-8');text=export_copy(text,'MD','note.md',who)[0]
        archive.writestr('note.md',text)
        for asset_id,data in images.items():archive.writestr('images/'+asset_id+'.png',export_copy(data,'PNG','image.png',who)[0])
        archive.writestr('说明.txt','note.md 为笔记正文，images 目录保存全部引用图片。请保持相对目录结构。正文与图片均含本次下载的身份标记。')
    return output.getvalue(),'application/zip','.zip'


@notes_router.get('/notes/{note_id}/export')
async def export_note(note_id:str,format:str=Query('docx',pattern='^(docx|markdown)$'),draft:bool=False,user=Depends(kb.require_knowledge_user)):
    with ws.SessionLocal() as db:
        note,_=find_note(db,note_id,user,manage=draft)
        if draft:title,content=note.title,copy.deepcopy(note.content)
        else:
            publication=db.get(CompanyNotePublication,note.current_document_id)
            if not publication:raise HTTPException(409,'这篇笔记尚未发布，可以选择导出当前草稿。')
            title,content=publication.title,copy.deepcopy(publication.content)
        images=asset_payloads(db,note,content)
    who=identity(user)
    try:data,mime,suffix=await asyncio.to_thread(export_note_bytes,title,content,images,format,who)
    except WatermarkError as error:raise HTTPException(error.status,str(error)) from None
    with ws.SessionLocal() as db:
        note,_=find_note(db,note_id,user,manage=draft)
        record(db,user,'note.download',note,before=snapshot(note),event_id=who.trace_id,
            details={'trace_id':who.trace_id,'format':format,'draft':draft,'sha256':hashlib.sha256(data).hexdigest()});db.commit()
    filename=title.replace('/','_').replace('\\','_')+suffix
    return Response(data,media_type=mime,headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff',
        'Content-Disposition':"attachment; filename*=UTF-8''"+quote(filename),'X-Download-Filename':quote(filename)})
