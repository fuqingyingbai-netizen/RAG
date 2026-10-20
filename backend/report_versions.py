"""Read-only report history and bounded text previews using project access rules."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth import get_current_user, get_db
from models import ResearchArtifact, User

REPORT_TYPES = ('desktop_report', 'proposal')
PREVIEW_LIMIT = 120_000


def record_label(version):
    return f'记录 {version:03d}'


def describe_record(row):
    meta = row.artifact_metadata if isinstance(row.artifact_metadata, dict) else {}
    if row.created_by == 'human_review' or meta.get('stage') == 'human_review':
        origin = '上传修订'
    elif meta.get('stage') == 'second_stage':
        origin = '补充资料后生成'
    elif meta.get('reexported_from_artifact_id'):
        origin = '重新导出'
    elif row.created_by in {'agent', 'workflow', 'system'}:
        origin = '系统生成'
    else:
        origin = '来源未记录'
    review = '建议书待确认' if meta.get('proposal_confirmation_status') == 'pending' else (
        '待复核稿' if meta.get('delivery_status') == 'review_draft' or meta.get('quality_warning')
        or meta.get('requires_human_review') else '')
    return {
        'id': row.id, 'project_id': row.project_id, 'artifact_type': row.artifact_type,
        'title': row.title, 'version': row.version, 'record_label': record_label(row.version),
        'created_at': row.created_at.isoformat() + 'Z', 'origin_label': origin,
        'original_filename': str(meta.get('original_filename') or '').replace('\\', '/').rsplit('/', 1)[-1],
        'review_label': review, 'export_error': bool(meta.get('docx_export_error')),
        'can_download': bool(row.has_text or row.object_key or meta.get('docx_object_key')
                             or meta.get('review_original_object_key')),
        'has_preview': bool(row.has_text),
    }


def create_report_versions_router(get_project):
    router = APIRouter(tags=['Report history'])

    @router.get('/projects/{project_id}/report-versions')
    def report_versions(project_id: int,
                        artifact_type: Literal['desktop_report', 'proposal'] = 'desktop_report',
                        page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=50),
                        db: Session = Depends(get_db), user: User = Depends(get_current_user)):
        project = get_project(db, project_id, user)
        filters = (ResearchArtifact.project_id == project_id, ResearchArtifact.artifact_type == artifact_type)
        total = db.scalar(select(func.count()).select_from(ResearchArtifact).where(*filters))
        newest = db.scalar(select(ResearchArtifact.id).where(*filters).order_by(
            ResearchArtifact.version.desc(), ResearchArtifact.created_at.desc(), ResearchArtifact.id.desc()).limit(1))
        # Never include report bodies, storage keys or diagnostic metadata in a list.
        rows = db.execute(select(
            ResearchArtifact.id, ResearchArtifact.project_id, ResearchArtifact.artifact_type,
            ResearchArtifact.title, ResearchArtifact.version, ResearchArtifact.created_at,
            ResearchArtifact.created_by, ResearchArtifact.artifact_metadata, ResearchArtifact.object_key,
            (func.length(ResearchArtifact.content) > 0).label('has_text'),
        ).where(*filters).order_by(ResearchArtifact.version.desc(), ResearchArtifact.created_at.desc(),
                                   ResearchArtifact.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
        records = [describe_record(row) | {'is_latest': row.id == newest} for row in rows]
        return JSONResponse({'project': {'id': project.id, 'title': project.title}, 'records': records,
                             'total': total, 'page': page, 'page_size': page_size},
                            headers={'Cache-Control': 'no-store'})

    @router.get('/artifacts/{artifact_id}/preview')
    def preview(artifact_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
        row = db.get(ResearchArtifact, artifact_id)
        if not row:
            raise HTTPException(404, '报告记录不存在')
        get_project(db, row.project_id, user)
        if row.artifact_type not in REPORT_TYPES:
            raise HTTPException(404, '该成果不提供报告预览')
        content = row.content or ''
        return JSONResponse({'id': row.id, 'project_id': row.project_id, 'title': row.title,
                             'record_label': record_label(row.version), 'content': content[:PREVIEW_LIMIT],
                             'truncated': len(content) > PREVIEW_LIMIT, 'has_preview': bool(content)},
                            headers={'Cache-Control': 'no-store'})

    return router
