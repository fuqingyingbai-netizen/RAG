"""Idempotent local report outbox; existing ingestion workers handle cloud indexing."""
import hashlib
from sqlalchemy import select

from company_catalog import CompanyDocument, document_store
from models import User


def _native_evidence_for_archive(artifact):
    metadata=artifact.artifact_metadata or {}
    if (metadata.get('company_delivery_contract') or {}).get('reading_format')!='analysis_with_annex':return ''
    from research_store import research_store
    from report_agents.company_presentation import knowledge_annex_text
    key=metadata.get('evidence_annex_object_key')
    if not key:raise ValueError('完整证据附件尚未保存，不能只归档主报告而丢失检索内容。')
    return knowledge_annex_text(research_store.get_text(key),metadata.get('evidence_annex_sha256'),
                                metadata.get('evidence_native_input_sha256'))


def archive_report(db, project, artifact):
    import company_knowledge as kb
    cfg = kb.settings()
    owner = db.get(User, project.created_by_id)
    if owner is None:
        raise ValueError('任务创建账号不存在，无法归属报告。')
    # Lock the owner just as manual uploads do, including version activation.
    db.execute(select(User).where(User.id == owner.id).with_for_update())
    doc_id = hashlib.sha256(f"{cfg['index_id']}:{artifact.id}".encode()).hexdigest()[:32]
    previous = list(db.scalars(select(CompanyDocument).where(
        CompanyDocument.index_id == cfg['index_id'],
        CompanyDocument.research_project_id == project.id)))
    doc = db.get(CompanyDocument, doc_id)
    if doc and doc.state == 'deleted':
        raise ValueError('该报告已从知识库删除，请生成新版本后再归档。')
    if doc is None:
        level = 'internal'
        order = {'internal': 0, 'confidential': 1, 'secret': 2}
        for source in project.sources or []:
            candidate = (source.source_metadata or {}).get('confidentiality', 'internal')
            if order.get(candidate, 0) > order[level]:
                level = candidate
        # The version header also prevents repeated report bodies colliding with
        # the catalogue's content-identity constraint across report versions.
        evidence=_native_evidence_for_archive(artifact)
        payload = (f'# {artifact.title}\n\n第一阶段报告 · v{artifact.version} · AI 生成，复核状态以资料目录为准\n\n'
                   + artifact.content+('\n\n'+evidence if evidence else '')).encode('utf-8')
        key = 'originals/research-' + doc_id + '.md'
        document_store().put_bytes(key, payload, 'text/markdown; charset=utf-8')
        doc = CompanyDocument(id=doc_id, index_id=cfg['index_id'],
            title=(str(project.target_name or project.title)[:200] + ' 第一阶段报告.md'),
            format='MD', size=len(payload), sha256=hashlib.sha256(payload).hexdigest(), object_key=key,
            owner=owner.username, owner_user_id=owner.id, research_project_id=project.id,
            research_artifact_id=artifact.id, is_current=1,
            project=f'{project.title[:170]}（项目 {project.id}）', industry=project.industry[:100],
            category='研究成果', review='待复核', version=artifact.version, confidentiality=level,
            visibility='restricted', readers=[], parser='AUTO_SELECT', state='queued',
            status_message='报告已归档，等待解析与索引')
        db.add(doc)
    elif doc.state == 'failed':
        if '时间较长' not in doc.status_message:
            doc.job_id = ''
        doc.state, doc.status_message = 'queued', '正在重试报告入库'
        doc.worker_id, doc.lease_until = '', None
    newest = max([row.research_artifact_id or 0 for row in previous] + [artifact.id])
    for row in previous:
        row.is_current = int(row.research_artifact_id == newest)
    doc.is_current = int(artifact.id == newest)
    db.flush()
    meta = dict(artifact.artifact_metadata or {})
    meta.pop('knowledge_sync_error', None)
    artifact.artifact_metadata = meta | {
        'knowledge_document_id': doc.id, 'knowledge_sync_status': doc.state,
        'knowledge_project_id': project.id, 'knowledge_review': '待复核'}
    db.commit()
    return doc


def sync_report_safely(db, project, artifact):
    """Report delivery must succeed independently of catalogue configuration."""
    try:
        return archive_report(db, project, artifact)
    except Exception:
        db.rollback()
        artifact.artifact_metadata = dict(artifact.artifact_metadata or {}) | {
            'knowledge_sync_status': 'failed',
            'knowledge_sync_error': '报告已生成，知识库归档暂未完成；请重试或联系管理员检查配置。'}
        db.commit()
        return None
