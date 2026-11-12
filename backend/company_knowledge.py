"""Bailian managed RAG: authenticated document listing and answer streaming."""

import asyncio
import anyio
from contextlib import suppress, asynccontextmanager, aclosing
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

from auth import get_knowledge_current_user as get_current_user
from models import User
from company_observability import phase, observe_sse
from company_capacity import model_slots, MODEL_WAIT_SECONDS, CapacityBusy, waiting_reporter
from sqlalchemy.exc import TimeoutError as PoolTimeout

load_dotenv(Path(__file__).resolve().parents[1] / '.env')


class KnowledgeValidationError(BaseModel):
    """Business rejections use text; request validation uses FastAPI's error list."""
    detail: str | list[dict]


router = APIRouter(prefix='/company-knowledge', tags=['Company knowledge'],
                  responses={status: {'model': KnowledgeValidationError, 'description': description}
                      for status, description in {
                          400: '请求格式无效', 401: '未登录或登录已失效', 403: '没有执行此操作的权限',
                          404: '资源不存在或不可访问', 409: '资料状态冲突，请刷新或稍后重试',
                          410: '播放缓存已过期，请重新打开资料',
                          413: '上传文件或请求体超过限制', 416: '请求的播放范围无效',
                          422: '请求参数或业务校验失败',
                          429: '请求过于频繁，请稍后重试', 502: '上游服务响应异常',
                          503: '服务暂时繁忙或配置不可用，请稍后重试',
                      }.items()})


class KnowledgeError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class KnowledgeStreamingResponse(StreamingResponse):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # A disconnect can interrupt ASGI send while the iterator is at yield.
            with anyio.CancelScope(shield=True):
                await self.body_iterator.aclose()


def upload_category():
    return os.getenv('BAILIAN_KNOWLEDGE_CATEGORY_ID', 'default').strip() or 'default'


def oss_upload_url(value):
    url = safe_url(value)
    host = urlsplit(url).hostname or ''
    return url if host.endswith('.aliyuncs.com') and '.oss-' in host else ''


async def cloud_rpc(client, cfg, path, payload=None, *, method='POST', params=None):
    with phase(path.rsplit('/', 1)[-1]) as observation:
        response = await client.request(method, cfg['base_url'] + path, headers=headers(cfg), json=payload, params=params)
        observation['http_status'] = response.status_code
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


async def model_settings(client, cfg):
    """Use one inference provider for knowledge answers and conversation memory."""
    names = ('MODEL', 'BASE_URL', 'API_KEY')
    scoped = {name.lower(): os.getenv('COMPANY_KNOWLEDGE_' + name, '').strip() for name in names}
    if any(scoped.values()):
        if not all(scoped.values()):
            raise KnowledgeError('公司知识库模型配置不完整，请同时配置模型、接口地址和密钥。', 503)
        scoped['base_url'] = scoped['base_url'].rstrip('/')
        return {**scoped, 'provider': '知识库模型'}
    shared = {'model': os.getenv('MODEL', '').strip(), 'base_url': os.getenv('BASE_URL', '').strip().rstrip('/'),
              'api_key': os.getenv('ARK_API_KEY', '').strip()}
    if all(shared.values()):
        return {**shared, 'provider': '回答模型'}
    if not cfg.get('_chat_model'):
        info = await cloud_rpc(client, cfg, '/api/v1/indices/rag/app/get', {'agent_id': cfg['agent_id']})
        versions = [row for row in info.get('agent_details', []) if str(row.get('agent_version', '')).isdigit()]
        config = (max(versions, key=lambda row: int(row['agent_version'])).get('agent_config') or {}) if versions else {}
        if not config.get('agent_model'):
            raise KnowledgeError('未找到已发布的问答模型配置，请管理员检查应用。')
        cfg['_chat_model'] = config['agent_model']
    return {'model': cfg['_chat_model'], 'base_url': cfg['base_url'] + '/compatible-mode/v1',
            'api_key': cfg['api_key'], 'provider': '百炼'}


def model_request_options(config):
    model = str(config['model']).lower().rsplit('/', 1)[-1]
    # GLM-5.3 models require thinking; Qwen's enable_thinking is not portable.
    if model.startswith('glm-5.3-flash'):
        return {'reasoning_effort': 'low'}
    if model.startswith('glm-5.3'):
        return {}
    if model in ('glm-5.2', 'glm-4.7-flash'):
        return {'thinking': {'type': 'disabled'}}
    from model_provider_options import official_deepseek
    # These GLM models use thinking.type; enable_thinking is a Qwen extension.
    return ({'thinking': {'type': 'disabled'}} if official_deepseek(config['model'], config['base_url'])
            else {'enable_thinking': False})


@asynccontextmanager
async def model_response(client, config, payload):
    """Retry a quickly rejected transient request once, before any answer bytes."""
    async with asyncio.timeout(180), model_slots.slot('model', wait=MODEL_WAIT_SECONDS):
        for attempt in range(2):
            with phase('model_stream' if payload.get('stream') else 'model_complete', attempt=attempt+1) as observation:
                started = time.perf_counter()
                async with client.stream('POST', config['base_url'] + '/chat/completions',
                        headers=headers(config), json=payload,
                        timeout=httpx.Timeout(120 if payload.get('stream') else 85, connect=20)) as response:
                    observation['http_status'] = response.status_code
                    observation['response_headers_ms'] = round((time.perf_counter()-started)*1000, 3)
                    # The gateway can fail only after 40+ seconds; repeating that
                    # request doubles occupied capacity during an upstream outage.
                    if (response.status_code not in {502, 503, 504} or attempt
                            or observation['response_headers_ms'] >= 5000):
                        if response.status_code != 200:
                            raise provider_error(response.status_code, provider=config['provider'])
                        response.extensions['knowledge_observation'] = observation
                        response.extensions['knowledge_started'] = started
                        yield response
                        return
            await asyncio.sleep(0.5)


def has_access(user: User) -> bool:
    # Membership grants entry; document classification is checked separately.
    # Ignore legacy opt-in flags for both existing and newly registered accounts.
    return (getattr(user, 'is_active', True) is not False
            and not getattr(user, 'archived_at', None) and user.role in ('admin', 'user'))


def require_knowledge_user(user: User = Depends(get_current_user)) -> User:
    if not has_access(user):
        raise HTTPException(403, '当前账号不可使用公司知识库，请联系管理员检查账号状态。')
    return user


def headers(cfg):
    return {'Authorization': 'Bearer ' + cfg['api_key'], 'Accept': 'application/json'}


def provider_error(status: int, *, provider: str = '百炼') -> KnowledgeError:
    message = {401: f'{provider}接口认证失败，请联系管理员核对 API Key、接口地址及密钥状态。',
               402: f'{provider}余额不足，请联系管理员核对账户额度。',
               403: f'{provider}访问权限不足，请核对服务与模型权限。',
               404: f'{provider}服务未找到，请核对接口地址和服务或模型 ID。',
               429: '知识库请求较多，请稍后重试。'}.get(status, f'{provider}服务暂时不可用，请稍后重试。')
    return KnowledgeError(message, 429 if status == 429 else 502)


def model_body_error(error):
    # Some gateways report account limits inside an HTTP200 JSON/SSE body.
    if isinstance(error, dict) and (error.get('type') == 'rate_limit_error' or str(error.get('code')) == '429'):
        return provider_error(429, provider='知识库模型')
    return KnowledgeError('云端模型调用失败，请稍后重试。')


async def list_cloud_documents(cfg, page_number=1, page_size=100):
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        with phase('list_documents') as observation:
            response = await client.get(cfg['base_url'] + '/api/v1/indices/rag/index/files',
                                        headers=headers(cfg), params={'index_id': cfg['index_id'],
                                        'page_number': page_number, 'page_size': page_size})
            observation['http_status'] = response.status_code
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
            # Source bytes must go through authenticated, personalised export routes.
            'url': '', 'location_url': ''}


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
    document_ids: list[str] = Field(default_factory=list, max_length=1000)
    scope: Literal['accessible', 'my-projects', 'experience', 'my-experience'] = 'accessible'
    session_id: str | None = Field(default=None, max_length=64)
    request_id: str | None = Field(default=None, max_length=64)


async def cloud_answer(cfg, question):
    if cfg.get('_conversation'):
        from company_memory import conversation_stream
        async with asyncio.timeout(330), aclosing(conversation_stream(*cfg['_conversation'])) as events:
            async for event in events:
                yield event
        return
    if 'allowed_documents' in cfg:
        from company_workspace import grounded_answer
        async with asyncio.timeout(240), aclosing(grounded_answer(cfg, question)) as events:
            async for event in events:
                yield event
        return
    payload = {'input': {'messages': [m.model_dump() for m in question.history] +
                        [{'role': 'user', 'content': question.message.strip()}]},
               'parameters': {'agent_options': {'agent_id': cfg['agent_id']}}, 'stream': True}
    answer_received = False
    async with asyncio.timeout(240):
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=20), trust_env=False) as client:
            with phase('cloud_chat') as observation:
                started = time.perf_counter()
                async with client.stream('POST', cfg['base_url'] + '/api/v2/apps/knowledge/chat',
                                         headers={**headers(cfg), 'Accept': 'text/event-stream'}, json=payload) as response:
                    observation['http_status'] = response.status_code
                    observation['response_headers_ms'] = round((time.perf_counter()-started)*1000, 3)
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
        reporter_token = waiting_reporter.set(queue.put)
        try:
            async with aclosing(cloud_answer(cfg, question)) as events:
                async for event in events:
                    await queue.put(event)
        except KnowledgeError as exc:
            await queue.put({'type': 'error', 'message': str(exc), 'status_code': exc.status_code})
        except (CapacityBusy, PoolTimeout):
            await queue.put({'type': 'error', 'message': '服务当前繁忙，请稍后重试。', 'status_code': 503, 'retry_after': 2})
        except (httpx.HTTPError, TimeoutError):
            await queue.put({'type': 'error', 'message': '云端响应超时或连接中断，请稍后重试。'})
        except (ValueError, KeyError, TypeError):
            await queue.put({'type': 'error', 'message': '云端返回格式异常，请联系管理员。'})
        finally:
            waiting_reporter.reset(reporter_token)
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
            observe_sse(event)
            yield {**event, 'elapsed_seconds': int(time.monotonic() - started)}
            if event['type'] in ('done', 'error'):
                return
    finally:
        worker.cancel()
        with anyio.CancelScope(shield=True):
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
    if not question.session_id and not question.document_ids and re.search(
            r'(我的项目|我(?:曾经)?(?:做过|参与过|负责过|上传过|上传的).{0,12}(?:项目|资料|文件)|我.{0,6}(?:做了|做过|参与|负责|上传).{0,10}(?:哪些|什么).{0,6}(?:项目|资料|文件))',
            question.message):
        from company_collections import personal_scope
        question = question.model_copy(update={'scope': personal_scope(question.scope)})
    try:
        cfg = settings()
        if question.session_id:
            from company_memory import scope_of
            saved_scope, saved_ids = await asyncio.to_thread(scope_of, user, cfg['index_id'], question.session_id)
            if saved_scope != question.scope or set(saved_ids) != set(question.document_ids):
                raise HTTPException(409, '资料范围已变化，请开始新的研究对话。')
            question = question.model_copy(update={'scope': saved_scope, 'document_ids': saved_ids, 'history': []})
            cfg['explicit_document_scope'] = bool(saved_ids)
        from company_workspace import prepare_scope, my_projects
        cfg['allowed_documents'] = await prepare_scope(cfg, user, question.document_ids, question.scope)
        if question.scope in ('my-projects', 'my-experience'):
            cfg['project_portfolio'] = await asyncio.to_thread(my_projects, user, question.scope)
        if question.session_id:
            from company_memory import begin_turn
            from uuid import uuid4
            question = question.model_copy(update={'request_id': question.request_id or uuid4().hex})
            token, plan, dependencies = await asyncio.to_thread(begin_turn, user, cfg, question.session_id, question.request_id, question.message)
            cfg['_conversation'] = (user, cfg, question, token, plan, dependencies)
    except KnowledgeError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None

    async def stream():
        async with aclosing(stream_events(cfg, question)) as events:
            async for event in events:
                yield 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'

    return KnowledgeStreamingResponse(stream(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})


from company_workspace import workspace_router
router.include_router(workspace_router)
from company_memory import memory_router
router.include_router(memory_router)
from company_discovery import discovery_router
router.include_router(discovery_router)
from company_notes import notes_router
router.include_router(notes_router)
from company_recycle import router as recycle_router
router.include_router(recycle_router)
from company_answer_exports import router as answer_exports_router
router.include_router(answer_exports_router)
