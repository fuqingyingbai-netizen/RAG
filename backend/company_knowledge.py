"""Bailian managed RAG: authenticated document listing and answer streaming."""

import asyncio
from contextlib import suppress
import json
import os
import re
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auth import get_current_user
from models import User

load_dotenv(Path(__file__).resolve().parents[1] / '.env')
router = APIRouter(prefix='/company-knowledge', tags=['Company knowledge'])


class KnowledgeError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def upload_category():
    return os.getenv('BAILIAN_KNOWLEDGE_CATEGORY_ID', 'default').strip() or 'default'


def oss_upload_url(value):
    url = safe_url(value)
    host = urlsplit(url).hostname or ''
    return url if host.endswith('.aliyuncs.com') and '.oss-' in host else ''


async def cloud_rpc(client, cfg, path, payload=None, *, method='POST', params=None):
    response = await client.request(method, cfg['base_url'] + path, headers=headers(cfg), json=payload, params=params)
    if response.status_code != 200:
        raise provider_error(response.status_code)
    result = response.json()
    if (result.get('success') is False or str(result.get('code', '')).lower() not in ('success', '200', '')
            or str(result.get('status_code', result.get('status', '200'))).upper() not in ('200', 'SUCCESS')):
        raise KnowledgeError('云端操作未成功，请检查服务权限或文件格式后重试。')
    return result.get('data') or {}


def settings():
    names = ('API_KEY', 'BASE_URL', 'AGENT_ID', 'INDEX_ID')
    cfg = {name.lower(): os.getenv('BAILIAN_KNOWLEDGE_' + name, '').strip() for name in names}
    if not all(cfg.values()):
        raise KnowledgeError('公司知识库尚未配置，请联系管理员。', 503)
    try:
        parsed = urlsplit(cfg['base_url'])
        valid = (parsed.scheme == 'https' and not parsed.username and not parsed.password and not parsed.port
                 and parsed.path in ('', '/') and not parsed.query and not parsed.fragment
                 and re.fullmatch(r'[a-z0-9-]+\.[a-z0-9-]+\.maas\.aliyuncs\.com', parsed.hostname or ''))
    except ValueError:
        valid = False
    if not valid:
        raise KnowledgeError('百炼知识库接口地址配置无效。', 503)
    cfg['base_url'] = cfg['base_url'].rstrip('/')
    return cfg


def has_access(user: User) -> bool:
    if getattr(user, 'is_active', True) is False:
        return False
    granted = getattr(user, 'knowledge_access', None)
    allowed = {name.strip() for name in os.getenv('COMPANY_KNOWLEDGE_USERS', '').split(',') if name.strip()}
    return user.role == 'admin' or (granted if granted is not None else user.username in allowed)


def require_knowledge_user(user: User = Depends(get_current_user)) -> User:
    # Invitation registration does not automatically grant internal documents.
    if not has_access(user):
        raise HTTPException(403, '该账号尚未获得公司知识库访问权限，请联系管理员。')
    return user


def headers(cfg):
    return {'Authorization': 'Bearer ' + cfg['api_key'], 'Accept': 'application/json'}


def provider_error(status: int, *, provider: str = '百炼') -> KnowledgeError:
    message = {401: f'{provider}接口认证失败，请联系管理员核对 API Key、接口地址及密钥状态。',
               403: f'{provider}访问权限不足，请核对服务与模型权限。',
               404: f'{provider}服务未找到，请核对接口地址和服务或模型 ID。',
               429: '知识库请求较多，请稍后重试。'}.get(status, '云端知识库暂时不可用，请稍后重试。')
    return KnowledgeError(message, 429 if status == 429 else 502)


async def list_cloud_documents(cfg, page_number=1, page_size=100):
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        response = await client.get(cfg['base_url'] + '/api/v1/indices/rag/index/files',
                                    headers=headers(cfg), params={'index_id': cfg['index_id'],
                                    'page_number': page_number, 'page_size': page_size})
        if response.status_code != 200:
            raise provider_error(response.status_code)
        data = response.json()
        if data.get('success') is False or str(data.get('code', '')).lower() not in ('success', '200', ''):
            raise KnowledgeError('云端文档列表查询失败，请核对知识库配置。')
        result = data.get('data', {})
        return {'documents': [{
            'id': row['doc_id'], 'title': row.get('doc_name', ''),
            'format': str(row.get('doc_type', '')).upper(), 'size': row.get('size', 0),
            'status': row.get('status', ''), 'status_message': row.get('message', ''),
            'category': row.get('categoryName') or '公司资料',
            'tags': row.get('tags') if isinstance(row.get('tags'), list) else [tag for tag in str(row.get('tags') or '').split(',') if tag],
            'modified_at': row.get('gmt_modified'),
        } for row in result.get('rows', []) if row.get('doc_id')],
            'total_count': result.get('total_count', 0), 'page_number': page_number, 'page_size': page_size}


def safe_url(value):
    if not isinstance(value, str):
        return ''
    try:
        url = urlsplit(value)
    except ValueError:
        return ''
    return value if url.scheme == 'https' and url.hostname and not url.username and not url.password else ''


def citation(doc):
    pages = doc.get('page_number', [])
    if not isinstance(pages, list):
        pages = [pages] if pages is not None else []
    return {'id': str(doc.get('_citation_index', '')), 'document_id': str(doc.get('doc_id', '')),
            'title': str(doc.get('doc_name') or doc.get('title') or '引用资料'),
            'text': str(doc.get('content') or ''), 'pages': pages,
            'url': safe_url(doc.get('doc_url')), 'location_url': safe_url(doc.get('_pos_url'))}


def frame_events(frame):
    """Normalize upstream SSE; never expose planning/reasoning as the answer."""
    code = str(frame.get('code', '200'))
    if code.lower() not in ('200', 'success'):
        raise KnowledgeError('百炼问答调用失败，请联系管理员检查服务状态。')
    for choice in frame.get('output', {}).get('choices', []):
        message = choice.get('message', {})
        extra = message.get('extra') or {}
        change = extra.get('step_change')
        step = extra.get('step')
        if change == 'plan_start':
            yield {'type': 'progress', 'stage': 'organizing', 'label': '正在整理资料',
                   'detail': '云端正在处理检索结果，准备回答。'}
        if change == 'plan_end':
            yield {'type': 'progress', 'stage': 'organizing', 'label': '资料整理阶段完成',
                   'detail': '等待云端后续处理。', 'finished': True}
        if change == 'tool_return':
            result = (message.get('additional_kwargs') or {}).get('extra_json') or {}
            if isinstance(result, str):
                result = json.loads(result)
            if isinstance(result, dict) and isinstance(result.get('docs'), list):
                refs = [citation(d) for d in result['docs'] if isinstance(d, dict)]
                count = len({r['document_id'] or r['title'] for r in refs})
                yield {'type': 'progress', 'stage': 'retrieving', 'label': '检索完成',
                       'detail': f'本次命中 {count} 份文件、{len(refs)} 个片段。', 'finished': True}
                yield {'type': 'citations', 'citations': refs}
        if change == 'tool_calling':
            yield {'type': 'status', 'message': '正在检索公司资料…'}
            for tool in message.get('tool_calls') or []:
                function = tool.get('function') or {}
                try:
                    arguments = json.loads(function.get('arguments') or '{}')
                except (ValueError, TypeError):
                    arguments = {}
                if not isinstance(arguments, dict):
                    arguments = {}
                tool_name = function.get('name', '')
                label = {'obtain_file': '正在读取文档', 'section_browse': '正在浏览相关章节',
                         'section_peruse': '正在读取相关章节', 'execute_sql': '正在查询表格数据'}.get(tool_name, '正在检索公司资料')
                query = arguments.get('query')
                detail = '检索问题：' + query[:200] if isinstance(query, str) else '云端正在查找与问题相关的资料。'
                yield {'type': 'progress', 'stage': 'retrieving', 'label': label, 'detail': detail}
        if change == 'generation_start':
            yield {'type': 'status', 'message': '正在生成回答…'}
            yield {'type': 'progress', 'stage': 'answering', 'label': '正在生成回答',
                   'detail': '回答将逐步显示在下方。'}
        if step == 'generating':
            content = message.get('content')
            if isinstance(content, list):
                content = ''.join(str(part.get('text', '')) for part in content if isinstance(part, dict) and part.get('type') == 'text')
            if isinstance(content, str) and content:
                yield {'type': 'answer_delta', 'text': content}
        if change == 'generation_end':
            yield {'type': 'done', 'usage': frame.get('usage') or {},
                   'model': (message.get('response_metadata') or {}).get('model_name', '')}


async def sse_frames(lines):
    """Read SSE records, including multi-line data and a final record without LF."""
    data = []
    async for line in lines:
        if not line:
            if data:
                value = '\n'.join(data)
                if value == '[DONE]':
                    return
                yield json.loads(value)
                data = []
        elif line.startswith('data:'):
            data.append(line[5:].lstrip())
    if data and '\n'.join(data) != '[DONE]':
        yield json.loads('\n'.join(data))


class HistoryMessage(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=20000)


class KnowledgeQuestion(BaseModel):
    message: str = Field(min_length=1, max_length=1500)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=20)
    document_ids: list[str] = Field(default_factory=list, max_length=20)
    scope: Literal['accessible', 'my-projects'] = 'accessible'
    session_id: str | None = Field(default=None, max_length=64)
    request_id: str | None = Field(default=None, max_length=64)


async def cloud_answer(cfg, question):
    if cfg.get('_conversation'):
        from company_memory import conversation_stream
        async with asyncio.timeout(270):
            async for event in conversation_stream(*cfg['_conversation']):
                yield event
        return
    if 'allowed_documents' in cfg:
        from company_workspace import grounded_answer
        async with asyncio.timeout(240):
            async for event in grounded_answer(cfg, question):
                yield event
        return
    payload = {'input': {'messages': [m.model_dump() for m in question.history] +
                        [{'role': 'user', 'content': question.message.strip()}]},
               'parameters': {'agent_options': {'agent_id': cfg['agent_id']}}, 'stream': True}
    answer_received = False
    async with asyncio.timeout(240):
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=20), trust_env=False) as client:
            async with client.stream('POST', cfg['base_url'] + '/api/v2/apps/knowledge/chat',
                                     headers={**headers(cfg), 'Accept': 'text/event-stream'}, json=payload) as response:
                if response.status_code != 200:
                    raise provider_error(response.status_code)
                if 'text/event-stream' not in response.headers.get('content-type', ''):
                    raise KnowledgeError('百炼未返回有效的流式回答。')
                async for frame in sse_frames(response.aiter_lines()):
                    for event in frame_events(frame):
                        if event['type'] == 'answer_delta':
                            answer_received = True
                        if event['type'] == 'done':
                            if not answer_received:
                                raise KnowledgeError('云端未生成回答，请稍后重试。')
                            yield event
                            return
                        yield event
    raise KnowledgeError('云端回答中断，请重新提问。')


async def stream_events(cfg, question, heartbeat_interval=3):
    """Send observed stages and keep the browser informed during quiet periods."""
    started = time.monotonic()
    queue = asyncio.Queue()

    async def produce():
        try:
            async for event in cloud_answer(cfg, question):
                await queue.put(event)
        except KnowledgeError as exc:
            await queue.put({'type': 'error', 'message': str(exc)})
        except (httpx.HTTPError, TimeoutError):
            await queue.put({'type': 'error', 'message': '云端响应超时或连接中断，请稍后重试。'})
        except (ValueError, KeyError, TypeError):
            await queue.put({'type': 'error', 'message': '云端返回格式异常，请联系管理员。'})
        finally:
            queue.put_nowait(None)

    worker = asyncio.create_task(produce())
    try:
        yield {'type': 'progress', 'stage': 'connecting', 'label': '正在连接知识库',
               'detail': '问题已提交，正在等待云端响应。', 'elapsed_seconds': 0}
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
            except TimeoutError:
                yield {'type': 'heartbeat', 'elapsed_seconds': int(time.monotonic() - started)}
                continue
            if event is None:
                return
            yield {**event, 'elapsed_seconds': int(time.monotonic() - started)}
            if event['type'] in ('done', 'error'):
                return
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker


@router.get('/status')
def knowledge_status(user: User = Depends(get_current_user)):
    try:
        settings()
        configured = True
    except KnowledgeError:
        configured = False
    return {'configured': configured, 'access_allowed': has_access(user),
            'name': '公司知识库', 'provider': '阿里云百炼', 'is_admin': user.role == 'admin',
            'username': user.username, 'account_id': getattr(user, 'id', None)}


async def documents(page_number: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=100),
                    _: User = Depends(require_knowledge_user)):
    try:
        return await list_cloud_documents(settings(), page_number, page_size)
    except KnowledgeError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(502, '云端文档列表暂时无法加载，请稍后重试。') from None


@router.post('/chat/stream')
async def chat(question: KnowledgeQuestion, user: User = Depends(require_knowledge_user)):
    if not question.message.strip():
        raise HTTPException(422, '问题不能为空。')
    if sum(len(m.content) for m in question.history) > 60000:
        raise HTTPException(422, '对话内容过长，请开始新对话。')
    if not question.document_ids and re.search(
            r'(我的项目|我(?:曾经)?(?:做过|参与过|负责过|上传过|上传的).{0,12}(?:项目|资料|文件)|我.{0,6}(?:做了|做过|参与|负责|上传).{0,10}(?:哪些|什么).{0,6}(?:项目|资料|文件))',
            question.message):
        question = question.model_copy(update={'scope': 'my-projects'})
    try:
        cfg = settings()
        if question.session_id:
            from company_memory import scope_of
            saved_scope, saved_ids = scope_of(user, cfg['index_id'], question.session_id)
            if saved_scope != question.scope or set(saved_ids) != set(question.document_ids):
                raise HTTPException(409, '资料范围已变化，请开始新的研究对话。')
            question = question.model_copy(update={'scope': saved_scope, 'document_ids': saved_ids, 'history': []})
            cfg['explicit_document_scope'] = bool(saved_ids)
        from company_workspace import prepare_scope, my_projects
        cfg['allowed_documents'] = await prepare_scope(cfg, user, question.document_ids, question.scope)
        if question.scope == 'my-projects':
            cfg['project_portfolio'] = my_projects(user)
        if question.session_id:
            from company_memory import begin_turn
            from uuid import uuid4
            question = question.model_copy(update={'request_id': question.request_id or uuid4().hex})
            token, plan, dependencies = begin_turn(user, cfg, question.session_id, question.request_id, question.message)
            cfg['_conversation'] = (user, cfg, question, token, plan, dependencies)
    except KnowledgeError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None

    async def stream():
        async for event in stream_events(cfg, question):
            yield 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'

    return StreamingResponse(stream(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})


from company_workspace import workspace_router
router.include_router(workspace_router)
from company_memory import memory_router
router.include_router(memory_router)
