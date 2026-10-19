"""Resumable ingestion with database leases and checkpointed cloud identifiers."""
import asyncio
import base64
import hashlib
import uuid
from datetime import datetime, timedelta

from sqlalchemy import or_, update

from database import SessionLocal
from company_catalog import CompanyDocument, document_store
import company_knowledge as kb

ACTIVE = ('queued', 'uploading', 'parsing', 'indexing')
upload_slots = asyncio.Semaphore(3)


def checkpoint(doc_id, token, **values):
    with SessionLocal() as db:
        result = db.execute(update(CompanyDocument).where(CompanyDocument.id == doc_id,
            CompanyDocument.worker_id == token).values(**values, updated_at=datetime.utcnow(),
            lease_until=datetime.utcnow() + timedelta(minutes=3)))
        db.commit()
        if result.rowcount != 1:
            raise kb.KnowledgeError('处理任务已交由另一工作进程接管。')


async def process_document(doc_id):
    async with upload_slots:
        await _process_document(doc_id)


async def _process_document(doc_id):
    token = uuid.uuid4().hex
    with SessionLocal() as db:
        claimed = db.execute(update(CompanyDocument).where(CompanyDocument.id == doc_id,
            CompanyDocument.state.in_(ACTIVE), or_(CompanyDocument.lease_until.is_(None),
            CompanyDocument.lease_until < datetime.utcnow())).values(worker_id=token,
            lease_until=datetime.utcnow() + timedelta(minutes=3)))
        db.commit()
        if claimed.rowcount != 1:
            return
        doc = db.get(CompanyDocument, doc_id)
        values = {key: getattr(doc, key) for key in ('index_id', 'cloud_id', 'object_key', 'title', 'format',
                                                   'size', 'lease_id', 'job_id', 'parser')}
    try:
        cfg = kb.settings()
        # A changed deployment must not import an old task into a different corpus.
        if values['index_id'] != cfg['index_id']:
            raise kb.KnowledgeError('知识库配置已变更，请管理员检查原任务。')
        async with kb.httpx.AsyncClient(timeout=120, trust_env=False) as client:
            if not values['cloud_id']:
                checkpoint(doc_id, token, state='uploading', status_message='正在上传至知识库')
                payload = await asyncio.to_thread(document_store().get_bytes, values['object_key'])
                # A previous upload may have completed before process exit. A new lease is
                # safe until registration; the registered ID is persisted before import.
                lease = await kb.cloud_rpc(client, cfg, '/api/v1/connector/dash/applyFileUploadLease', {
                    'category': kb.upload_category(), 'fileName': values['title'],
                    'sizeBytes': str(len(payload)),
                    'contentMd5': base64.b64encode(hashlib.md5(payload).digest()).decode(),
                    'categoryType': 'UNSTRUCTURED'})
                lease_id = lease.get('leaseId') or lease.get('fileUploadLeaseId')
                param = lease.get('param') or {}
                url = kb.oss_upload_url(param.get('url'))
                if not lease_id or not url or param.get('method', 'PUT') != 'PUT':
                    raise kb.KnowledgeError('云端上传凭证格式异常。')
                # Only provider-issued upload headers go to OSS, never the API key.
                response = await client.put(url, headers=param.get('headers') or {}, content=payload)
                if response.status_code not in (200, 201, 204):
                    raise kb.KnowledgeError('原件上传至知识库失败，请重试。')
                checkpoint(doc_id, token, lease_id=lease_id, state='parsing', status_message='正在解析文档，扫描件将识别文字')
                registered = await kb.cloud_rpc(client, cfg, '/api/v1/connector/dash/addFile', {
                    'leaseId': lease_id, 'category': kb.upload_category(), 'categoryType': 'UNSTRUCTURED',
                    'parser': values['parser'], 'tags': ['company-workspace', 'ckdoc-' + doc_id]})
                values['cloud_id'] = registered.get('fileId')
                if not values['cloud_id']:
                    raise kb.KnowledgeError('云端未返回文件编号，请联系管理员。')
                checkpoint(doc_id, token, cloud_id=values['cloud_id'])
            if not values['job_id']:
                created = await kb.cloud_rpc(client, cfg, '/api/v1/indices/rag/index/job/create', {
                    'indexId': cfg['index_id'], 'sourceType': 'DATA_CENTER_FILE', 'docIds': [values['cloud_id']]})
                values['job_id'] = created.get('ingestionId')
                if not values['job_id']:
                    raise kb.KnowledgeError('知识库未返回索引任务编号，请重试。')
                checkpoint(doc_id, token, job_id=values['job_id'], state='indexing', status_message='已提交知识库，等待解析与索引')
            for _ in range(450):
                checkpoint(doc_id, token)
                result = await kb.cloud_rpc(client, cfg, '/api/v1/indices/rag/index_job/status', method='GET', params={
                    'index_id': cfg['index_id'], 'job_id': values['job_id'], 'page_number': 1, 'page_size': 100})
                row = next((row for row in result.get('rows', []) if row.get('doc_id') == values['cloud_id']), {})
                state = str(row.get('status') or row.get('code') or '').upper()
                if state == 'FINISH':
                    checkpoint(doc_id, token, state='ready', status_message='解析与索引完成，可以检索和提问')
                    return
                if any(word in str(row.get('code', '')).upper() + state for word in ('FAIL', 'ERROR')):
                    raise kb.KnowledgeError('云端解析或索引失败，请检查文件后重试。')
                parsing = 'PARS' in state or not row
                checkpoint(doc_id, token, state='parsing' if parsing else 'indexing',
                           status_message='正在解析 / OCR 识别' if parsing else '正在建立检索索引')
                await asyncio.sleep(4)
            raise kb.KnowledgeError('处理时间较长，可点击重试继续查询原任务。')
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        message = str(exc) if isinstance(exc, kb.KnowledgeError) else '处理连接中断，原件已保存，可稍后重试。'
        checkpoint(doc_id, token, state='failed', status_message=message)
    finally:
        with SessionLocal() as db:
            db.execute(update(CompanyDocument).where(CompanyDocument.id == doc_id,
                       CompanyDocument.worker_id == token).values(worker_id='', lease_until=None))
            db.commit()
