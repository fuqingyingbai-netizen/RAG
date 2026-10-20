import json
import threading
from types import SimpleNamespace

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

import assistant_online as online
import research_api as api
from research_schemas import ResearchAssistantRequest
from system_guide import model_answer


class Reply:
    def __init__(self, data): self.data = data
    def raise_for_status(self): pass
    def json(self): return self.data


def weather_payload():
    return {'current_condition': [{'temp_C': '21', 'FeelsLikeC': '20', 'humidity': '60',
             'windspeedKmph': '8', 'lang_xx': [{'value': '多云'}], 'localObsDateTime': '2026-10-20 09:00 AM'}],
            'nearest_area': [{'areaName': [{'value': 'Shanghai'}], 'country': [{'value': 'China'}]}],
            'weather': [{'date': '2026-10-21', 'mintempC': '18', 'maxtempC': '25',
                         'hourly': [{'weatherDesc': [{'value': 'Sunny'}]}]}]}


def test_weather_uses_explicit_city_returns_real_fields_and_provider_times(monkeypatch):
    calls = []
    monkeypatch.setattr(online.requests, 'get', lambda url, **kw: (calls.append((url, kw)) or Reply(weather_payload())))
    result = online.get_weather('上海', forecast=True)
    assert result['status'] == 'ok'
    assert result['current']['temperature_c'] == '21'
    assert result['current']['description'] == '多云'
    assert result['current']['observed_at'] == '2026-10-20 09:00 AM'
    assert result['forecast'][0]['date'] == '2026-10-21'
    assert result['sources'][0]['retrieved_at'].endswith('+08:00')
    assert calls[0][0].startswith('https://wttr.in/%')
    assert calls[0][1]['params'] == {'format': 'j1', 'lang': 'zh'}


@pytest.mark.parametrize('city', ['', None, '这里', '我附近', '我的位置', 'unknown', 'current location', 'https://internal.test', '../secret', '上海?key=secret'])
def test_missing_or_unsafe_weather_locations_never_issue_http(monkeypatch, city):
    monkeypatch.setattr(online.requests, 'get', lambda *a, **kw: pytest.fail('must first ask for a city'))
    assert online.get_weather(city)['status'] == 'needs_location'


def test_weather_handles_nested_schema_and_unavailable_data(monkeypatch):
    monkeypatch.setattr(online.requests, 'get', lambda *a, **kw: Reply({'data': weather_payload()}))
    assert online.get_weather('北京')['status'] == 'ok'
    monkeypatch.setattr(online.requests, 'get', lambda *a, **kw: Reply({'error': 'private-upstream-secret'}))
    result = online.get_weather('北京')
    assert result['status'] == 'empty' and 'private-upstream-secret' not in str(result)


def test_weather_errors_do_not_leak_upstream_response_or_invent_temperatures(monkeypatch):
    def fail(*a, **kw): raise requests.Timeout('secret-account-query')
    monkeypatch.setattr(online.requests, 'get', fail)
    result = online.get_weather('北京')
    assert result['status'] == 'error' and 'secret-account' not in str(result)
    assert 'current' not in result


def test_search_selects_one_existing_provider_and_only_requests_snippets(monkeypatch):
    monkeypatch.delenv('ASSISTANT_SEARCH_PROVIDER', raising=False)
    monkeypatch.setenv('TAVILY_API_KEY', 'private-key')
    monkeypatch.setenv('SERPER_API_KEY', 'other-private-key')
    monkeypatch.setenv('WEB_SEARCH_PROVIDER', 'multi')
    calls = []
    def post(url, **kw):
        calls.append((url, kw))
        return Reply({'results': [{'title': '公开消息', 'url': 'https://issuer.test/news', 'content': '公开摘要', 'published_date': '2026-10-20'},
                                  {'title': 'bad', 'url': 'javascript:alert(1)', 'content': 'unsafe'}]})
    monkeypatch.setattr(online.requests, 'post', post)
    result = online.search_web('公司公开新闻', news=True, time_range='week')
    assert len(calls) == 1 and calls[0][0] == 'https://api.tavily.com/search'
    params = calls[0][1]['json']
    assert params['include_raw_content'] is False and params['include_images'] is False
    assert params['search_depth'] == 'basic' and params['topic'] == 'news' and params['time_range'] == 'week'
    assert params['query'] == '公司公开新闻' and 'private-key' not in str(params)
    assert len(result['results']) == 1 and result['results'][0]['snippet'] == '公开摘要'
    assert result['sources'][0]['published_at'] == '2026-10-20'
    assert 'snippet' not in result['sources'][0] and 'private-key' not in str(result)


def test_search_failure_does_not_fan_out_or_expose_credentials(monkeypatch):
    monkeypatch.setenv('ASSISTANT_SEARCH_PROVIDER', 'tavily')
    monkeypatch.setenv('TAVILY_API_KEY', 'private-key')
    calls = []
    def fail(url, **kw):
        calls.append(url)
        raise requests.HTTPError('private-key: quota exhausted')
    monkeypatch.setattr(online.requests, 'post', fail)
    result = online.search_web('公开查询')
    assert len(calls) == 1 and result['status'] == 'error'
    assert 'private-key' not in str(result) and 'sources' not in result


def test_explicit_serper_is_independent_of_research_provider(monkeypatch):
    monkeypatch.setenv('ASSISTANT_SEARCH_PROVIDER', 'serper')
    monkeypatch.setenv('SERPER_API_KEY', 'key')
    calls = []
    monkeypatch.setattr(online.requests, 'post', lambda url, **kw: (calls.append((url, kw)) or Reply(
        {'news': [{'title': '行业新闻', 'link': 'https://source.test/news', 'snippet': '摘要', 'date': '昨天'}]})))
    result = online.search_web('行业新闻', news=True, time_range='day')
    assert calls[0][0] == 'https://google.serper.dev/news'
    assert calls[0][1]['json']['tbs'] == 'qdr:d'
    assert result['sources'][0]['published_at'] == '昨天'


def test_official_domain_filter_is_sent_and_enforced_on_returned_links(monkeypatch):
    monkeypatch.setenv('ASSISTANT_SEARCH_PROVIDER', 'tavily')
    monkeypatch.setenv('TAVILY_API_KEY', 'key')
    calls = []
    monkeypatch.setattr(online.requests, 'post', lambda url, **kw: (calls.append(kw) or Reply({'results': [
        {'title': '官方公告', 'url': 'https://news.issuer.test/announcement', 'content': '原文摘要'},
        {'title': '相似拼写的广告', 'url': 'https://issuer.test.marketing.test/ads', 'content': '广告'},
    ]})))
    result = online.search_web('官方公告', include_domains=['issuer.test', 'https://bad.test'])
    assert calls[0]['json']['include_domains'] == ['issuer.test']
    assert len(result['sources']) == 1 and result['sources'][0]['title'] == '官方公告'
    assert online.search_web('公告', include_domains='issuer.test')['status'] == 'error'
    assert online.search_web('公告', include_domains=['https://issuer.test'])['status'] == 'error'


def test_weather_missing_timezone_is_explicit_in_direct_answer(monkeypatch):
    data = weather_payload()
    del data['current_condition'][0]['localObsDateTime']
    data['current_condition'][0]['observation_time'] = '01:53 AM'
    monkeypatch.setattr(online.requests, 'get', lambda *a, **kw: Reply(data))
    result = online.get_weather('上海')
    assert result['current']['observation_time_incomplete']
    assert '未提供观测日期和时区' in result['formatted_answer']
    assert '01:53 AM' in result['formatted_answer'] and '当地时间' not in result['formatted_answer']
    assert online._description({'weatherDesc': [{'value': 'Overcast'}]}) == '阴'


def test_no_key_or_invalid_query_does_not_attempt_http(monkeypatch):
    monkeypatch.setenv('ASSISTANT_SEARCH_PROVIDER', 'tavily')
    monkeypatch.delenv('TAVILY_API_KEY', raising=False)
    monkeypatch.setattr(online.requests, 'post', lambda *a, **kw: pytest.fail('missing key must not call a provider'))
    assert online.search_web('公开查询')['status'] == 'error'
    assert online.search_web('x' * 301)['status'] == 'error'
    assert online.execute_tool('delete_project', {'id': 1})['status'] == 'error'


class FakeModel:
    def __init__(self, replies):
        self.replies = iter(replies); self.invocations = []; self.schemas = []
    def bind_tools(self, tools): self.schemas = tools; return self
    def invoke(self, messages, **kwargs):
        self.invocations.append(list(messages))
        return next(self.replies)


def assistant_reply(text='', calls=None):
    return SimpleNamespace(content=text, tool_calls=calls or [])


def tool_call(name, args, id='call1'):
    return {'name': name, 'args': args, 'id': id}


def test_ordinary_chat_does_not_execute_any_tools(monkeypatch):
    import system_guide as guide
    monkeypatch.setattr(guide, 'execute_tool', lambda *a: pytest.fail('ordinary chat must not issue HTTP'))
    model = FakeModel([assistant_reply('当然可以，欢迎加入团队！')])
    result = model_answer(SimpleNamespace(_get_model=lambda: model), ResearchAssistantRequest(message='写一句欢迎语'), 'user')
    assert '欢迎加入' in result and len(model.invocations) == 1
    assert {item['function']['name'] for item in model.schemas} == {'get_weather', 'search_web'}


def test_weather_tool_followup_uses_history_and_streams_numbered_sources(monkeypatch):
    import system_guide as guide
    calls = []
    monkeypatch.setattr(guide, 'execute_tool', lambda name, args: (calls.append((name, args)) or {
        'status': 'ok', 'sources': [{'title': '上海天气', 'url': 'https://wttr.in/Shanghai'}], 'current': {'temperature_c': '21'}}))
    model = FakeModel([assistant_reply(calls=[tool_call('get_weather', {'location': '上海'})]), assistant_reply('上海21℃，见来源[1]。')])
    request = ResearchAssistantRequest(message='上海', recent_messages=[{'role': 'user', 'content': '今天天气怎么样？'}])
    events = []
    answer = model_answer(SimpleNamespace(_get_model=lambda: model), request, 'user', events.append)
    assert '21℃' in answer and calls == [('get_weather', {'location': '上海'})]
    assert '今天天气怎么样' in model.invocations[0][1]['content']
    assert events[0]['type'] == 'status' and events[1]['sources'][0]['number'] == 1
    assert model.invocations[1][-1]['role'] == 'tool'
    assert json.loads(model.invocations[1][-1]['content'])['sources'][0]['number'] == 1


def test_tool_failure_cannot_be_followed_by_a_made_up_realtime_answer(monkeypatch):
    import system_guide as guide
    monkeypatch.setattr(guide, 'execute_tool', lambda *a: {'status': 'error', 'message': '查询失败，无法核实天气。'})
    model = FakeModel([assistant_reply(calls=[tool_call('get_weather', {'location': '北京'})]), assistant_reply('北京晴天25℃')])
    result = model_answer(SimpleNamespace(_get_model=lambda: model), ResearchAssistantRequest(message='北京天气'), 'user')
    assert result == '查询失败，无法核实天气。' and len(model.invocations) == 1


def test_repeated_tool_calls_are_cached_and_total_new_calls_are_bounded(monkeypatch):
    import system_guide as guide
    executed = []
    monkeypatch.setattr(guide, 'execute_tool', lambda name, args: (executed.append(args) or {'status': 'ok', 'results': []}))
    model = FakeModel([
        assistant_reply(calls=[tool_call('get_weather', {'location': '北京'}, 'a'), tool_call('get_weather', {'location': '上海'}, 'b')]),
        assistant_reply(calls=[tool_call('get_weather', {'location': '北京'}, 'c'), tool_call('get_weather', {'location': '杭州'}, 'd')]),
        assistant_reply('这里只比较已查询的北京和上海。')])
    model_answer(SimpleNamespace(_get_model=lambda: model), ResearchAssistantRequest(message='比较天气'), 'user')
    assert executed == [{'location': '北京'}, {'location': '上海'}]


def test_cancellation_stops_followup_tools(monkeypatch):
    import system_guide as guide
    cancelled = threading.Event(); cancelled.set()
    model = FakeModel([])
    monkeypatch.setattr(guide, 'execute_tool', lambda *a: pytest.fail('cancelled request must not issue HTTP'))
    assert '超时' in model_answer(SimpleNamespace(_get_model=lambda: model), ResearchAssistantRequest(message='上海天气'), 'user', cancel_event=cancelled)
    assert not model.invocations


def test_assistant_endpoint_streams_live_sources_without_project_db_access(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database import Base
    from models import User
    engine = create_engine('sqlite:///' + str(tmp_path / 'online.db'), connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(id=99, username='new-user', password_hash='test', role='user')); db.commit()
    def get_history_db():
        with factory() as db:
            yield db
    import system_guide as guide
    model = FakeModel([assistant_reply(calls=[tool_call('search_web', {'query': '公开消息'})]), assistant_reply('已找到公开消息[1]。')])
    monkeypatch.setattr(api.research_workflow, '_get_model', lambda: model)
    monkeypatch.setattr(guide, 'execute_tool', lambda *a: {'status': 'ok', 'sources': [{'title': '公开来源', 'url': 'https://issuer.test/news'}]})
    for name in ('_vector_context', '_project_store_context', '_assistant_project_ids'):
        monkeypatch.setattr(api, name, lambda *a: pytest.fail('no project retrieval'))
    app = FastAPI(); app.include_router(api.router)
    app.dependency_overrides[api.get_current_user] = lambda: SimpleNamespace(id=99, username='new-user', role='user')
    app.dependency_overrides[api.get_db] = get_history_db
    with TestClient(app) as client:
        response = client.post('/research/assistant/stream', json={'message': '帮我联网查公开消息'})
    assert response.status_code == 200 and '正在搜索公开网页' in response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ') and line[6:] != '[DONE]']
    assert any(event['type'] == 'sources' and event['sources'][0]['url'] == 'https://issuer.test/news' for event in events)
    assert response.text.endswith('data: [DONE]\n\n')
    with TestClient(app) as client:
        history = client.get('/research/assistant/state').json()
    assert history['messages'][-1]['sources'][0]['url'] == 'https://issuer.test/news'
    engine.dispose()
