"""Persistent company document catalogue; originals never live under static files."""
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, inspect, text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from research_store import ResearchObjectStore


class CompanyDocument(Base):
    __tablename__ = 'company_documents'
    __table_args__ = (
        UniqueConstraint('index_id', 'cloud_id', name='uq_company_cloud_file'),
        Index('uq_company_active_content_v2', 'index_id', 'owner', 'project', 'knowledge_project_id', 'folder_id', 'title', 'sha256', unique=True,
              postgresql_where=text("sha256 != '' AND state != 'deleted'"),
              sqlite_where=text("sha256 != '' AND state != 'deleted'")),
        Index('uq_company_file_version_v2', 'index_id', 'owner', 'project', 'knowledge_project_id', 'folder_id', 'title', 'version', unique=True,
              postgresql_where=text("sha256 != ''"), sqlite_where=text("sha256 != ''")),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    index_id: Mapped[str] = mapped_column(String(100), index=True)
    cloud_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    format: Mapped[str] = mapped_column(String(20))
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default='')
    object_key: Mapped[str] = mapped_column(String(500), default='')
    owner: Mapped[str] = mapped_column(String(100), default='')
    owner_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    uploaded_by: Mapped[str] = mapped_column(String(100), default='')
    uploaded_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    modified_by: Mapped[str] = mapped_column(String(100), default='')
    research_project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    research_artifact_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    is_current: Mapped[int] = mapped_column(Integer, default=1)
    note_id: Mapped[str] = mapped_column(String(64), default='', index=True)
    knowledge_project_id: Mapped[str] = mapped_column(String(64), default='', index=True)
    folder_id: Mapped[str] = mapped_column(String(64), default='', index=True)
    inherits_project: Mapped[int] = mapped_column(Integer, default=0)
    project: Mapped[str] = mapped_column(String(200), default='')
    industry: Mapped[str] = mapped_column(String(100), default='')
    tags: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default='')
    stale_cloud_id: Mapped[str] = mapped_column(String(200), default='')
    category: Mapped[str] = mapped_column(String(50), default='项目原件')
    review: Mapped[str] = mapped_column(String(30), default='待复核')
    version: Mapped[int] = mapped_column(Integer, default=1)
    visibility: Mapped[str] = mapped_column(String(20), default='members')
    confidentiality: Mapped[str] = mapped_column(String(20), default='internal')
    readers: Mapped[list] = mapped_column(JSON, default=list)
    state: Mapped[str] = mapped_column(String(30), default='queued')
    status_message: Mapped[str] = mapped_column(Text, default='等待上传到知识库')
    lease_id: Mapped[str] = mapped_column(String(255), default='')
    job_id: Mapped[str] = mapped_column(String(150), default='')
    parser: Mapped[str] = mapped_column(String(50), default='DOCMIND')
    worker_id: Mapped[str] = mapped_column(String(64), default='')
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CompanyProject(Base):
    __tablename__ = 'company_projects'
    __table_args__ = (UniqueConstraint('index_id', 'owner', 'name', name='uq_company_project_name'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    index_id: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(200))
    legacy_key: Mapped[str] = mapped_column(String(64), default='')
    owner: Mapped[str] = mapped_column(String(100))
    owner_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String(100), default='')
    modified_by: Mapped[str] = mapped_column(String(100), default='')
    industry: Mapped[str] = mapped_column(String(100), default='')
    tags: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default='')
    category: Mapped[str] = mapped_column(String(50), default='项目原件')
    review: Mapped[str] = mapped_column(String(30), default='待复核')
    confidentiality: Mapped[str] = mapped_column(String(20), default='internal')
    visibility: Mapped[str] = mapped_column(String(20), default='members')
    readers: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CompanyFolder(Base):
    __tablename__ = 'company_folders'
    __table_args__ = (UniqueConstraint('project_id', 'parent_id', 'name', name='uq_company_folder_name'),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('company_projects.id', ondelete='CASCADE'), index=True)
    parent_id: Mapped[str] = mapped_column(String(64), default='')
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CompanyAccessRequest(Base):
    __tablename__ = 'company_access_requests'
    __table_args__ = (
        Index('ix_company_access_request_document_status', 'document_id', 'status'),
        Index('ix_company_access_request_requester_status', 'requester_id', 'status'),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey('company_documents.id', ondelete='CASCADE'), index=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    requester_username: Mapped[str] = mapped_column(String(100), index=True)
    reason: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(20), default='pending', index=True)
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    decided_by_username: Mapped[str] = mapped_column(String(100), default='')
    decision_note: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CompanyAuditEvent(Base):
    __tablename__ = 'company_audit_events'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    index_id: Mapped[str] = mapped_column(String(100), index=True)
    project_id: Mapped[str] = mapped_column(String(64), default='', index=True)
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    target_name: Mapped[str] = mapped_column(String(255), default='')
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_username: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(50), index=True)
    changes: Mapped[dict] = mapped_column(JSON, default=dict)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


CONFIDENTIALITY_LABELS = {'internal': '内部', 'secret': '机密'}
AUDIO_FORMATS = {'MP3', 'WAV', 'M4A', 'OGG', 'FLAC'}
VIDEO_FORMATS = {'MP4', 'WEBM'}


def media_kind(doc):
    return 'audio' if doc.format in AUDIO_FORMATS else 'video' if doc.format in VIDEO_FORMATS else ''


def normalize_confidentiality(value):
    # Old open tabs and archived source metadata may still send the former level.
    return 'secret' if value == 'confidential' else value


def migrate_confidentiality_levels(engine):
    """Consolidate the former sensitive level without broadening any access."""
    with engine.begin() as connection:
        for table in ('company_projects', 'company_documents'):
            connection.exec_driver_sql(
                "UPDATE " + table + " SET confidentiality='secret' WHERE confidentiality='confidential'")


def ensure_company_schema(engine):
    """Install additive catalogue columns when upgrading an existing preview DB."""
    inspector = inspect(engine)
    if 'company_documents' not in inspector.get_table_names():
        Base.metadata.create_all(bind=engine)
        migrate_confidentiality_levels(engine)
        return
    columns = {column['name'] for column in inspector.get_columns('company_documents')}
    additions = []
    for column, definition in (('note_id', "VARCHAR(64) DEFAULT '' NOT NULL"), ('knowledge_project_id', "VARCHAR(64) DEFAULT '' NOT NULL"), ('folder_id', "VARCHAR(64) DEFAULT '' NOT NULL"), ('inherits_project', 'INTEGER DEFAULT 0 NOT NULL')):
        if column not in columns:
            additions.append('ADD COLUMN ' + column + ' ' + definition)
    for column, definition in (('uploaded_by', "VARCHAR(100) DEFAULT '' NOT NULL"),
                               ('uploaded_by_user_id', 'INTEGER'), ('modified_by', "VARCHAR(100) DEFAULT '' NOT NULL")):
        if column not in columns:
            additions.append('ADD COLUMN ' + column + ' ' + definition)
    if 'owner_user_id' not in columns:
        additions.append('ADD COLUMN owner_user_id INTEGER')
    if 'confidentiality' not in columns:
        additions.append("ADD COLUMN confidentiality VARCHAR(20) DEFAULT 'internal' NOT NULL")
    for column, definition in (('tags', "JSON DEFAULT '[]' NOT NULL"),
                               ('description', "TEXT DEFAULT '' NOT NULL"),
                               ('stale_cloud_id', "VARCHAR(200) DEFAULT '' NOT NULL")):
        if column not in columns:
            additions.append('ADD COLUMN ' + column + ' ' + definition)
    for column in ('research_project_id', 'research_artifact_id'):
        if column not in columns:
            additions.append('ADD COLUMN ' + column + ' INTEGER')
    if 'is_current' not in columns:
        additions.append('ADD COLUMN is_current INTEGER DEFAULT 1 NOT NULL')
    if additions:
        with engine.begin() as connection:
            for clause in additions:
                connection.exec_driver_sql('ALTER TABLE company_documents ' + clause)
    Base.metadata.create_all(bind=engine)
    if 'company_projects' in inspector.get_table_names():
        project_columns = {column['name'] for column in inspect(engine).get_columns('company_projects')}
        with engine.begin() as connection:
            for column in ('created_by', 'modified_by'):
                if column not in project_columns:
                    connection.exec_driver_sql("ALTER TABLE company_projects ADD COLUMN " + column + " VARCHAR(100) DEFAULT '' NOT NULL")
    for index in CompanyDocument.__table__.indexes:
        index.create(bind=engine, checkfirst=True)
    with engine.begin() as connection:
        for name in ('uq_company_active_content', 'uq_company_file_version'):
            connection.exec_driver_sql('DROP INDEX IF EXISTS ' + name)
    backfill_company_projects(engine)
    migrate_confidentiality_levels(engine)


def backfill_company_projects(engine):
    """Give legacy named projects stable IDs, preserving every file's original ACL."""
    import uuid
    import hashlib
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from sqlalchemy.exc import IntegrityError
    with Session(engine) as db:
        rows = list(db.scalars(select(CompanyDocument).where(
            CompanyDocument.knowledge_project_id == '', CompanyDocument.state != 'deleted')))
        try:
            for doc in rows:
                name = doc.project.strip() or '未归档资料'
                key = hashlib.sha256((doc.index_id + '\0' + doc.owner + '\0' + doc.project).encode()).hexdigest()
                project = db.scalar(select(CompanyProject).where(CompanyProject.index_id == doc.index_id,
                    CompanyProject.owner == doc.owner, CompanyProject.legacy_key == key))
                if not project:
                    base, suffix = name, 1
                    while db.scalar(select(CompanyProject.id).where(CompanyProject.index_id == doc.index_id,
                            CompanyProject.owner == doc.owner, CompanyProject.name == name)):
                        name = base[:180] + '（历史归档' + str(suffix) + '）'
                        suffix += 1
                    project = CompanyProject(id=uuid.uuid4().hex, index_id=doc.index_id, name=name, legacy_key=key,
                        owner=doc.owner, owner_user_id=doc.owner_user_id, industry=doc.industry,
                        category=doc.category, review=doc.review, tags=[], description='', created_at=doc.created_at, updated_at=doc.updated_at)
                    db.add(project)
                    db.flush()
                project.created_at = min(project.created_at, doc.created_at)
                project.updated_at = max(project.updated_at, doc.updated_at)
                doc.knowledge_project_id = project.id
            db.commit()
        except IntegrityError:
            db.rollback()  # Concurrent migration won; the next catalogue read retries.


def document_store():
    store = ResearchObjectStore()
    store.mode = os.getenv('COMPANY_KNOWLEDGE_OBJECT_STORE', 'local').strip().lower()
    if store.mode not in ('local', 'minio'):
        raise RuntimeError('COMPANY_KNOWLEDGE_OBJECT_STORE must be local or minio')
    store.bucket = os.getenv('COMPANY_KNOWLEDGE_BUCKET', 'company-knowledge')
    store.local_root = Path(os.getenv('COMPANY_KNOWLEDGE_LOCAL_STORE') or
                            str(Path(__file__).resolve().parents[1] / 'data/company_knowledge')).resolve()
    return store


def is_owner(doc, user):
    user_id = getattr(user, 'id', None)
    return ((doc.owner_user_id is not None and user_id is not None and doc.owner_user_id == user_id)
            or (doc.owner_user_id is None and doc.owner == user.username))


def classification_allowed(doc, user):
    return user.role == 'admin' or doc.confidentiality == 'internal'


def can_read(doc, user):
    # Classification is a ceiling, including for legacy owners and reader grants.
    if not classification_allowed(doc, user):
        return False
    if user.role == 'admin' or is_owner(doc, user) or user.username in (doc.readers or []):
        return True
    return doc.confidentiality == 'internal' and doc.visibility == 'members'


def can_manage(doc, user):
    # Notes inherit their project's ceiling in find_note/find_project.
    permitted = not hasattr(doc, 'confidentiality') or classification_allowed(doc, user)
    return permitted and (user.role == 'admin' or is_owner(doc, user))


STATE_LABELS = {'queued': '等待处理', 'uploading': '上传到知识库', 'parsing': '解析 / OCR 中',
                'indexing': '建立索引中', 'ready': '可检索', 'failed': '处理失败', 'deleting': '正在移除索引', 'deleted': '已删除', 'archived': '已归档'}


def serialize(doc, user, request_status=''):
    readable = can_read(doc, user)
    locked = not readable
    values = {key: getattr(doc, key) for key in ('id', 'title', 'format', 'size', 'owner', 'owner_user_id', 'uploaded_by', 'modified_by',
              'project', 'industry', 'category', 'review', 'version', 'visibility', 'confidentiality', 'state',
              'research_project_id', 'research_artifact_id', 'is_current', 'knowledge_project_id', 'folder_id', 'inherits_project')}
    values['status_message'] = doc.status_message if readable else '需要管理员批准后才能阅读、下载或用于问答。'
    return values | {
        'note_id': doc.note_id if readable else '',
        'confidentiality_label': CONFIDENTIALITY_LABELS.get(doc.confidentiality, doc.confidentiality),
        'readers': doc.readers if can_manage(doc, user) else [],
        'cloud_id': doc.cloud_id if readable else None,
        'status': ('FINISH' if doc.state == 'ready' else doc.state.upper()) if readable else 'LOCKED',
        'label': STATE_LABELS.get(doc.state, doc.state) if readable else '需要授权',
        'has_original': bool(doc.object_key) if readable else False,
        'can_read': readable, 'can_request': locked and request_status != 'pending',
        'request_status': request_status, 'is_owner': is_owner(doc, user),
        'can_manage': can_manage(doc, user), 'modified_at': doc.updated_at.isoformat() + 'Z',
        'created_at': doc.created_at.isoformat() + 'Z',
        'tags': list(doc.tags or []) if readable else [],
        'description': doc.description if readable else '', 'media_kind': media_kind(doc)}
