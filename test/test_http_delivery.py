"""Verify wire bytes and first-event delivery, without DB or external services."""
import asyncio
import gzip
import json

import pytest
from http_delivery import ResearchReadCompression


PAYLOAD=json.dumps({'results':[{'title':'合成研究记录','summary':'合成内容'*100} for _ in range(100)]},ensure_ascii=False).encode()


def deliver(payload=PAYLOAD,method='GET',path='/research/projects/1/detail',accept=b'gzip',headers=()):
    async def probe():
        messages=[]
        async def app(scope,receive,send):
            await send({'type':'http.response.start','status':200,'headers':[
                (b'content-type',b'application/json'),(b'cache-control',b'no-store'),
                (b'content-length',str(len(payload)).encode()),*headers]})
            await send({'type':'http.response.body','body':payload})
        async def receive():return {'type':'http.request','body':b''}
        async def send(message):messages.append(message)
        await ResearchReadCompression(app)({'type':'http','method':method,'path':path,'headers':[(b'accept-encoding',accept)]},receive,send)
        return dict(messages[0]['headers']),b''.join(message.get('body',b'') for message in messages[1:])
    return asyncio.run(probe())


def test_large_research_read_compresses_without_changing_its_data_or_cache_policy():
    headers,body=deliver()
    assert headers[b'content-encoding']==b'gzip'
    assert gzip.decompress(body)==PAYLOAD and len(body)<len(PAYLOAD)//10
    assert int(headers[b'content-length'])==len(body)
    assert headers[b'cache-control']==b'no-store'
    assert b'Accept-Encoding' in headers[b'vary']


@pytest.mark.parametrize('options',[
    {'accept':b'identity'}, {'accept':b'gzip;q=0'}, {'accept':b'br, gzip; q=0'},
    {'accept':b'gzip;q=invalid'}, {'accept':b'xgzip'}, {'method':'POST'},
    {'path':'/research/artifacts/1/download'}, {'path':'/research/sources/1/download'},
    {'path':'/auth/me'}, {'payload':b'{"ok":true}'},
])
def test_unsupported_clients_writes_small_responses_and_original_downloads_stay_unchanged(options):
    headers,body=deliver(**options)
    assert b'content-encoding' not in headers
    assert body==options.get('payload',PAYLOAD)


def test_preencoded_responses_are_not_compressed_twice():
    encoded=gzip.compress(PAYLOAD)
    headers,body=deliver(payload=encoded,headers=[(b'content-encoding',b'gzip')])
    assert body==encoded and gzip.decompress(body)==PAYLOAD


def test_event_stream_first_chunk_reaches_client_before_the_stream_finishes():
    async def probe():
        first,finish=asyncio.Event(),asyncio.Event();messages=[]
        async def app(scope,receive,send):
            await send({'type':'http.response.start','status':200,'headers':[(b'content-type',b'text/event-stream; charset=utf-8')]})
            await send({'type':'http.response.body','body':b'data: {"type":"started"}\n\n','more_body':True})
            await finish.wait()
            await send({'type':'http.response.body','body':b'data: {"type":"result"}\n\n','more_body':False})
        async def receive():return {'type':'http.request','body':b''}
        async def send(message):
            messages.append(message)
            if message.get('body'):first.set()
        task=asyncio.create_task(ResearchReadCompression(app)({'type':'http','method':'GET','path':'/research/events','headers':[(b'accept-encoding',b'gzip')]},receive,send))
        try:
            await asyncio.wait_for(first.wait(),1)
            assert not task.done()
            assert messages[-1]['body']==b'data: {"type":"started"}\n\n'
            assert b'content-encoding' not in dict(messages[0]['headers'])
        finally:finish.set();await task
    asyncio.run(probe())
