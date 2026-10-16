"""Persistent company document catalogue; originals never live under static files."""
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, UniqueConstraint, text
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
    project: Mapped[str] = mapped_column(String(200), default='')
    industry: Mapped[str] = mapped_column(String(100), default='')
    category: Mapped[str] = mapped_column(String(50), default='项目原件')
    review: Mapped[str] = mapped_column(String(30), default='待复核')
    version: Mapped[int] = mapped_column(Integer, default=1)
    visibility: Mapped[str] = mapped_column(String(20), default='members')
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


def document_store():
    store = ResearchObjectStore()
    store.mode = os.getenv('COMPANY_KNOWLEDGE_OBJECT_STORE', 'local').strip().lower()
    if store.mode not in ('local', 'minio'):
        raise RuntimeError('COMPANY_KNOWLEDGE_OBJECT_STORE must be local or minio')
    store.bucket = os.getenv('COMPANY_KNOWLEDGE_BUCKET', 'company-knowledge')
    store.local_root = Path(os.getenv('COMPANY_KNOWLEDGE_LOCAL_STORE') or
                            str(Path(__file__).resolve().parents[1] / 'data/company_knowledge')).resolve()
    return store


def can_read(doc, user):
    return user.role == 'admin' or doc.visibility == 'members' or doc.owner == user.username or user.username in (doc.readers or [])


def can_manage(doc, user):
    return user.role == 'admin' or doc.owner == user.username


STATE_LABELS = {'queued': '等待处理', 'uploading': '上传到知识库', 'parsing': '解析 / OCR 中',
                'indexing': '建立索引中', 'ready': '可检索', 'failed': '处理失败', 'deleting': '正在移除索引', 'deleted': '已删除'}


def serialize(doc, user):
    return {key: getattr(doc, key) for key in ('id', 'title', 'format', 'size', 'owner', 'project', 'industry',
            'category', 'review', 'version', 'visibility', 'state', 'status_message')} | {
                'readers': doc.readers if can_manage(doc, user) else [],
                'cloud_id': doc.cloud_id, 'status': 'FINISH' if doc.state == 'ready' else doc.state.upper(),
                'label': STATE_LABELS.get(doc.state, doc.state), 'has_original': bool(doc.object_key),
                'can_manage': can_manage(doc, user), 'modified_at': doc.updated_at.isoformat() + 'Z', 'tags': []}
