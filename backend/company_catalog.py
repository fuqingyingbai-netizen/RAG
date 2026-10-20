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
        Index('uq_company_active_content', 'index_id', 'owner', 'project', 'title', 'sha256', unique=True,
              postgresql_where=text("sha256 != '' AND state != 'deleted'"),
              sqlite_where=text("sha256 != '' AND state != 'deleted'")),
        Index('uq_company_file_version', 'index_id', 'owner', 'project', 'title', 'version', unique=True,
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
    research_project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    research_artifact_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    is_current: Mapped[int] = mapped_column(Integer, default=1)
    project: Mapped[str] = mapped_column(String(200), default='')
    industry: Mapped[str] = mapped_column(String(100), default='')
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


CONFIDENTIALITY_LABELS = {'internal': '内部', 'confidential': '敏感', 'secret': '机密'}


def ensure_company_schema(engine):
    """Install additive catalogue columns when upgrading an existing preview DB."""
    inspector = inspect(engine)
    if 'company_documents' not in inspector.get_table_names():
        Base.metadata.create_all(bind=engine)
        return
    columns = {column['name'] for column in inspector.get_columns('company_documents')}
    additions = []
    if 'owner_user_id' not in columns:
        additions.append('ADD COLUMN owner_user_id INTEGER')
    if 'confidentiality' not in columns:
        additions.append("ADD COLUMN confidentiality VARCHAR(20) DEFAULT 'internal' NOT NULL")
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
    for index in CompanyDocument.__table__.indexes:
        index.create(bind=engine, checkfirst=True)


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


def can_read(doc, user):
    if user.role == 'admin' or is_owner(doc, user) or user.username in (doc.readers or []):
        return True
    return doc.confidentiality == 'internal' and doc.visibility == 'members'


def can_manage(doc, user):
    return user.role == 'admin' or is_owner(doc, user)


STATE_LABELS = {'queued': '等待处理', 'uploading': '上传到知识库', 'parsing': '解析 / OCR 中',
                'indexing': '建立索引中', 'ready': '可检索', 'failed': '处理失败', 'deleting': '正在移除索引', 'deleted': '已删除'}


def serialize(doc, user, request_status=''):
    readable = can_read(doc, user)
    locked = not readable
    values = {key: getattr(doc, key) for key in ('id', 'title', 'format', 'size', 'owner', 'owner_user_id',
              'project', 'industry', 'category', 'review', 'version', 'visibility', 'confidentiality', 'state',
              'research_project_id', 'research_artifact_id', 'is_current')}
    values['status_message'] = doc.status_message if readable else '需要管理员批准后才能阅读、下载或用于问答。'
    return values | {
        'confidentiality_label': CONFIDENTIALITY_LABELS.get(doc.confidentiality, doc.confidentiality),
        'readers': doc.readers if can_manage(doc, user) else [],
        'cloud_id': doc.cloud_id if readable else None,
        'status': ('FINISH' if doc.state == 'ready' else doc.state.upper()) if readable else 'LOCKED',
        'label': STATE_LABELS.get(doc.state, doc.state) if readable else '需要授权',
        'has_original': bool(doc.object_key) if readable else False,
        'can_read': readable, 'can_request': locked and request_status != 'pending',
        'request_status': request_status, 'is_owner': is_owner(doc, user),
        'can_manage': can_manage(doc, user), 'modified_at': doc.updated_at.isoformat() + 'Z', 'tags': []}
