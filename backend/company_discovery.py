"""Scoped content discovery and authenticated visual previews; no model generation."""
import asyncio
import io
import tempfile
import uuid
import threading
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

import company_knowledge as kb
import company_workspace as ws
from company_catalog import document_store, serialize
from company_watermark import ExportIdentity, WatermarkError, export_copy, office_to_pdf, run, ffmpeg_binary

discovery_router = APIRouter()
OFFICE_PAGES = {'DOC', 'DOCX', 'XLS', 'XLSX', 'PPT', 'PPTX'}
conversion_lock = threading.Lock()


class ContentSearch(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    scope: Literal['accessible', 'my-projects', 'experience', 'my-experience'] = 'accessible'
    document_ids: list[str] | None = Field(default=None, max_length=5000)
    page: int = Field(default=1, ge=1, le=100)
    page_size: int = Field(default=10, ge=1, le=20)


@discovery_router.post('/search')
async def content_search(body: ContentSearch, user=Depends(kb.require_knowledge_user)):
    if len(body.query.strip()) < 2:
        raise HTTPException(422, '正文搜索至少输入两个字符。')
    cfg = kb.settings()
    # An explicitly empty UI filter can never expand to the whole collection.
    if body.document_ids == []:
        return {'matches': [], 'total': 0, 'page': body.page, 'limited': False}
    try:
        allowed = await ws.prepare_scope(cfg, user, body.document_ids or [], body.scope)
        if not allowed:
            return {'matches': [], 'total': 0, 'page': body.page, 'limited': False}
        nodes = []
        async with kb.httpx.AsyncClient(timeout=60, trust_env=False) as client:
            ids = list(allowed)
            for start in range(0, len(ids), 100):
                result = await kb.cloud_rpc(client, cfg, '/api/v1/indices/rag/index/retrieve', {
                    'index_id': cfg['index_id'], 'query': body.query.strip(),
                    'dense_similarity_top_k': 50, 'sparse_similarity_top_k': 50, 'rerank_top_n': 50,
                    'search_filters': [{'doc_id': ids[start:start + 100]}]})
                nodes.extend(result.get('nodes', []))
    except kb.KnowledgeError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except kb.httpx.HTTPError:
        raise HTTPException(503, '正文检索暂不可用，请稍后重试。') from None
    ranked, seen = [], set()
    for node in sorted(nodes, key=lambda item: float(item.get('score') or 0), reverse=True):
        meta = node.get('metadata') or {}
        cloud_id = meta.get('doc_id')
        text = str(meta.get('content') or node.get('text') or '')[:10000]
        if cloud_id not in allowed or not text or (meta.get('pipeline_id') and meta['pipeline_id'] != cfg['index_id']):
            continue
        key = (cloud_id, text)
        if key in seen:
            continue
        seen.add(key)
        source = allowed[cloud_id]
        ref = kb.citation({**meta, 'content': text, 'doc_name': source['title'], '_citation_index': len(ranked) + 1})
        ref['local_id'] = source['id']
        ranked.append(ref)
    # Recheck permissions after the upstream await, including revoked/deleted files.
    with ws.SessionLocal() as db:
        safe = []
        for ref in ranked:
            try:
                doc = ws.find_doc(db, ref['local_id'], user)
            except HTTPException:
                continue
            if not ws.in_scope(doc, body.scope) or doc.state != 'ready' or doc.cloud_id != ref['document_id']:
                continue
            safe.append({'document': serialize(doc, user), 'reference': ref})
    start = (body.page - 1) * body.page_size
    return {'matches': safe[start:start + body.page_size], 'total': len(safe), 'page': body.page,
            'limited': True, 'message': '按正文语义相关度排序，展示本次召回的相关片段。'}


@lru_cache(maxsize=3)
def office_pdf(object_key, digest, fmt):
    # Bounded process-local cache of derived bytes, never exposed without an ACL check.
    if fmt == 'XLSX':
        from company_sheet_preview import sheet_info
        if sheet_info(object_key, digest)['mode'] == 'table':
            raise WatermarkError('此表格数据量较大，请刷新页面后使用按行分页预览。', 422, 'spreadsheet_table_available')
    with conversion_lock, tempfile.TemporaryDirectory(prefix='ckb-reading-') as directory:
        data = document_store().get_bytes(object_key)
        result = office_to_pdf(data, fmt, Path(directory))
        if len(result) > 32 * 1024 * 1024:
            raise WatermarkError('在线预览结果较大，请下载原格式水印副本阅读。', 422)
        return result


def reading_pdf(doc):
    if doc.format == 'PDF':
        return document_store().get_bytes(doc.object_key)
    if doc.format in OFFICE_PAGES:
        return office_pdf(doc.object_key, doc.sha256, doc.format)
    raise HTTPException(422, '此格式使用文档或图片阅读器。')


@discovery_router.get('/documents/{doc_id}/sheet')
async def spreadsheet(doc_id: str, sheet: int = 0, page: int = 1, column: int = 1,
                      user=Depends(kb.require_knowledge_user)):
    from company_sheet_preview import sheet_page
    if sheet < 0 or page < 1 or column < 1:
        raise HTTPException(422, '表格页码、工作表和列号无效。')
    with ws.SessionLocal() as db:
        doc = ws.find_doc(db, doc_id, user)
        if doc.format != 'XLSX' or not doc.object_key:
            raise HTTPException(404, '这份资料没有可读取的 XLSX 原件。')
        source = (doc.object_key, doc.sha256, doc.format)
    try:
        result = await asyncio.to_thread(sheet_page, source[0], source[1], sheet, page, column)
    except WatermarkError as error:
        raise HTTPException(error.status, str(error), headers={'X-Preview-Error': error.code}) from None
    except FileNotFoundError:
        raise HTTPException(404, '归档原件已缺失，请联系管理员补传原件。', headers={'X-Preview-Error': 'original_missing'}) from None
    with ws.SessionLocal() as db:
        doc = ws.find_doc(db, doc_id, user)
        if source != (doc.object_key, doc.sha256, doc.format):
            raise HTTPException(409, '资料已更新，请重新打开。')
        identity = ExportIdentity(user.username, getattr(user, 'id', None), datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'), uuid.uuid4().hex)
        if result['mode'] == 'table':
            ws.record(db, user, 'document.preview', doc, before=ws.snapshot(doc), event_id=identity.trace_id,
                      details={'trace_id': identity.trace_id, 'sheet': sheet, 'row_page': page, 'column': column})
            db.commit()
    from fastapi.responses import JSONResponse
    return JSONResponse({**result, 'watermark': identity.lines}, headers={'Cache-Control': 'private, no-store',
                        'X-Watermark-Trace': identity.trace_id, 'X-Content-Type-Options': 'nosniff'})


@lru_cache(maxsize=24)
def reading_page(object_key, digest, fmt, page):
    """Cache unmarked derived pages; callers authorize before and after stamping."""
    from types import SimpleNamespace
    doc = SimpleNamespace(object_key=object_key, sha256=digest, format=fmt)
    return ws.render_pdf_page(reading_pdf(doc), page)


def image_thumbnail(data, fmt):
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(data)) as original:
        image = ImageOps.exif_transpose(original).convert('RGB')
        image.thumbnail((720, 480))
        out = io.BytesIO()
        image.save(out, 'PNG')
        return out.getvalue()


def thumbnail_bytes(doc):
    if doc.format in {'PNG', 'JPG', 'JPEG'}:
        return image_thumbnail(document_store().get_bytes(doc.object_key), doc.format)
    if doc.format == 'PDF' or doc.format in OFFICE_PAGES:
        data, _ = reading_page(doc.object_key, doc.sha256, doc.format, 1)
        return image_thumbnail(data, 'PNG')
    if doc.format in {'MP4', 'WEBM'}:
        binary = ffmpeg_binary()
        with tempfile.TemporaryDirectory(prefix='ckb-cover-') as directory:
            source, target = Path(directory) / ('source.' + doc.format.lower()), Path(directory) / 'cover.png'
            source.write_bytes(document_store().get_bytes(doc.object_key))
            run([binary, '-nostdin', '-v', 'error', '-i', str(source), '-frames:v', '1',
                 '-vf', 'scale=720:480:force_original_aspect_ratio=decrease', '-y', str(target)], timeout=25)
            return target.read_bytes()
    raise HTTPException(422, '该格式暂用文件类型封面。')


@discovery_router.get('/documents/{doc_id}/thumbnail')
async def thumbnail(doc_id: str, user=Depends(kb.require_knowledge_user)):
    with ws.SessionLocal() as db:
        doc = ws.find_doc(db, doc_id, user)
        if not doc.object_key:
            raise HTTPException(404, '该资料没有归档原件。')
        try:
            data = await asyncio.to_thread(thumbnail_bytes, doc)
            identity = ExportIdentity(user.username, getattr(user, 'id', None), datetime.utcnow().isoformat(), uuid.uuid4().hex)
            data, _, _ = await asyncio.to_thread(export_copy, data, 'PNG', 'cover.png', identity)
        except WatermarkError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, '封面暂未生成，仍可打开文件阅读。') from None
        db.expire_all()
        doc = ws.find_doc(db, doc_id, user)  # Check again after conversion.
        ws.record(db, user, 'document.preview', doc, before=ws.snapshot(doc), event_id=identity.trace_id,
                  details={'trace_id': identity.trace_id, 'thumbnail': True, 'watermarked': True})
        db.commit()
    return Response(data, media_type='image/png', headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


class SourceLocation(BaseModel):
    text: str = Field(default='', max_length=10000)
    pages: list[int] = Field(default_factory=list, max_length=50)


def pdf_outline(data):
    import pypdfium2 as pdfium
    with ws.pdf_render_lock:
        pdf = pdfium.PdfDocument(data)
        try:
            entries = []
            for bookmark in pdf.get_toc(max_depth=8):
                destination = bookmark.get_dest()
                index = destination.get_index() if destination else None
                if index is not None and 0 <= index < len(pdf):
                    entries.append({'title': bookmark.get_title()[:160], 'page': index + 1})
                if len(entries) >= 150:
                    break
            return entries
        finally:
            pdf.close()


@discovery_router.get('/documents/{doc_id}/outline')
async def outline(doc_id: str, user=Depends(kb.require_knowledge_user)):
    with ws.SessionLocal() as db:
        doc = ws.find_doc(db, doc_id, user)
        if doc.format not in OFFICE_PAGES | {'PDF'} or not doc.object_key:
            return {'entries': []}
        try:
            entries = await asyncio.to_thread(pdf_outline, await asyncio.to_thread(reading_pdf, doc))
        except Exception:
            entries = []  # Missing bookmarks must never block reading the document.
        db.expire_all()
        ws.find_doc(db, doc_id, user)
        return {'entries': entries}


def locate_pdf(data, body):
    import pypdfium2 as pdfium
    import re
    # Only report a paragraph match when text was actually found in the original.
    terms = [line.strip() for line in body.text.splitlines() if len(line.strip()) >= 8]
    terms = [re.sub(r'^[#*\s]+', '', term)[:100] for term in terms[:8]]
    with ws.pdf_render_lock:
        pdf = pdfium.PdfDocument(data)
        try:
            hints = [page for page in body.pages if 1 <= page <= len(pdf)]
            order = list(dict.fromkeys(hints + list(range(1, min(len(pdf), 120) + 1))))
            for number in order:
                page = pdf[number - 1]
                textpage = page.get_textpage()
                try:
                    for term in terms:
                        searcher = textpage.search(term, match_case=False)
                        try:
                            hit = searcher.get_next()
                        finally:
                            searcher.close()
                        if hit:
                            index, count = hit
                            width, height = page.get_size()
                            rectangles = []
                            for i in range(textpage.count_rects(index, count)):
                                left, bottom, right, top = textpage.get_rect(i)
                                rectangles.append({'left': left / width, 'top': 1 - top / height,
                                                   'width': (right - left) / width, 'height': (top - bottom) / height})
                            return {'page': number, 'matched': True, 'rectangles': rectangles, 'text': term}
                finally:
                    textpage.close()
                    page.close()
            return {'page': hints[0] if hints else None, 'matched': False, 'rectangles': [],
                    'message': '已定位来源页，原文可能是扫描图，未自动标出段落。' if hints else '原件未找到可精确匹配的文字，请对照引用片段核对。'}
        finally:
            pdf.close()


@discovery_router.post('/documents/{doc_id}/locate')
async def locate(doc_id: str, body: SourceLocation, user=Depends(kb.require_knowledge_user)):
    with ws.SessionLocal() as db:
        doc = ws.find_doc(db, doc_id, user)
        if doc.format != 'PDF' and doc.format not in OFFICE_PAGES:
            return {'matched': False, 'text': body.text, 'message': '在原文中查找引用文字。'}
        try:
            data = await asyncio.to_thread(reading_pdf, doc)
            result = await asyncio.to_thread(locate_pdf, data, body)
        except WatermarkError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, '暂时无法匹配原文，请对照引用片段核对。') from None
        db.expire_all()
        ws.find_doc(db, doc_id, user)
        return result
