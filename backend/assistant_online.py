"""Bounded public tools for chat. No project/store/database imports or writes."""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

import requests

CHINA_TIME = timezone(timedelta(hours=8))

TOOLS = [
    {'type': 'function', 'function': {
        'name': 'get_weather',
        'description': '查询指定城市的天气及未来三天预报。必须使用用户本轮或最近对话明确提供的城市；没有城市时先询问，不能按服务器位置、IP或用户角色猜城市。',
        'parameters': {'type': 'object', 'properties': {
            'location': {'type': 'string', 'description': '明确的城市，如上海、北京、London；有同名城市时补充省或国家。'},
            'forecast': {'type': 'boolean', 'description': '问明天、后天或未来几天天气时为true。'}}, 'required': ['location']}}},
    {'type': 'function', 'function': {
        'name': 'search_web',
        'description': '查询新闻、最新动态及需要外部核实的公开信息。只发送当前问题所需的简短公开关键词，不发送系统操作说明、角色、整段历史、内部项目或文件内容。',
        'parameters': {'type': 'object', 'properties': {
            'query': {'type': 'string', 'description': '公开检索词，最多300字。'},
            'news': {'type': 'boolean', 'description': '查询新闻动态时为true。'},
            'include_domains': {'type': 'array', 'items': {'type': 'string'}, 'description': '用户指定网站或要求官方信息时，限制在已知正确的官方域名，最多5个。不要使用相似拼写的第三方营销域名。'},
            'time_range': {'type': 'string', 'enum': ['', 'day', 'week', 'month', 'year'], 'description': '用户明确要求时间范围时设置；不要把所有旧资料当成实时信息。'}}, 'required': ['query']}}},
]


def now_text():
    return datetime.now(CHINA_TIME).isoformat(timespec='seconds')


def safe_public_url(value):
    try:
        url = urlsplit(str(value or ''))
        return str(value) if url.scheme in ('http', 'https') and url.hostname and not url.username and not url.password else ''
    except ValueError:
        return ''


def _description(row):
    for key in ('lang_zh', 'lang_xx', 'weatherDesc'):
        values = row.get(key) or []
        if values and isinstance(values[0], dict) and values[0].get('value'):
            value = str(values[0]['value'])[:100]
            return {'sunny': '晴', 'clear': '晴', 'partly cloudy': '局部多云', 'cloudy': '多云',
                    'overcast': '阴', 'mist': '薄雾', 'fog': '雾', 'light rain': '小雨',
                    'moderate rain': '中雨', 'heavy rain': '大雨', 'light snow': '小雪',
                    'moderate snow': '中雪', 'heavy snow': '大雪',
                    'patchy rain nearby': '附近局部有雨', 'patchy rain possible': '可能有局部降雨'}.get(value.lower(), value)
    return '未提供'


def get_weather(location, forecast=False):
    location = str(location or '').strip()
    if (len(location) < 2 or len(location) > 80 or re.search(r'[/\\:#?@\x00-\x1f]', location)
            or location.lower() in ('unknown', 'here', 'near me', 'my location', 'current location', 'none', 'null', '城市', '我的位置', '所在城市')
            or any(word in location for word in ('这里', '当地', '本地', '附近', '我在的城市', '未知'))):
        return {'status': 'needs_location', 'message': '你想查询哪个城市的天气？例如上海、北京，或省份加城市。'}
    url = 'https://wttr.in/' + quote(location, safe=', ')
    try:
        response = requests.get(url, params={'format': 'j1', 'lang': 'zh'},
                                headers={'User-Agent': 'curl/8.0'}, timeout=(5, 12))
        response.raise_for_status()
        payload = response.json()
        data = payload.get('data', payload)
        current = (data.get('current_condition') or [{}])[0]
        if current.get('temp_C') is None:
            return {'status': 'empty', 'message': '天气服务未返回有效数据，请确认城市名称或稍后重试。'}
        area = (data.get('nearest_area') or [{}])[0]
        observation = current.get('localObsDateTime') or current.get('observation_time') or '服务未提供'
        incomplete_time = not bool(current.get('localObsDateTime'))
        result = {
            'status': 'ok', 'location_requested': location,
            'location_resolved': (area.get('areaName') or [{}])[0].get('value', location),
            'country': (area.get('country') or [{}])[0].get('value', ''),
            'current': {'description': _description(current), 'temperature_c': current.get('temp_C'),
                        'feels_like_c': current.get('FeelsLikeC'), 'humidity_percent': current.get('humidity'),
                        'wind_kph': current.get('windspeedKmph'), 'observed_at': observation,
                        'observation_time_incomplete': incomplete_time},
            'forecast': [{'date': day.get('date'), 'min_c': day.get('mintempC'), 'max_c': day.get('maxtempC'),
                          'description': _description((day.get('hourly') or [{}])[min(4, len(day.get('hourly') or [{}])-1)])}
                         for day in (data.get('weather') or [])[:3]] if forecast else [],
            'retrieved_at': now_text(), 'time_note': '观测时间按天气服务原值展示；查询时间为北京时间。当前天气可能有延迟，不将查询时间当作观测时间。',
            'sources': [{'title': location + '天气 · wttr.in', 'url': url, 'provider': 'wttr.in',
                         'observed_at': observation, 'retrieved_at': now_text()}],
        }
        lines = [f'**{location}天气**（服务定位：{result["location_resolved"]}）',
                 f'天气：{result["current"]["description"]}；温度：{current.get("temp_C")}℃。']
        if current.get('FeelsLikeC') is not None:
            lines.append(f'体感温度：{current["FeelsLikeC"]}℃。')
        lines.append(f'服务观测时间：{observation}' + ('（未提供观测日期和时区，不能据此确认实时性）。' if incomplete_time else '（当地时间）。'))
        if forecast and result['forecast']:
            lines.append('\n未来三天预报：')
            lines.extend(f'- {day["date"]}：{day["description"]}，{day["min_c"]}～{day["max_c"]}℃。' for day in result['forecast'])
        lines.append('\n查询时间（北京时间）：' + result['retrieved_at'])
        result['formatted_answer'] = '\n\n'.join(lines)
        return result
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError, IndexError):
        return {'status': 'error', 'message': '天气服务暂时不可用，本次未取得可核实的天气；请稍后重试。'}


def search_web(query, news=False, time_range='', include_domains=None):
    query = str(query or '').strip()
    if not query or len(query) > 300:
        return {'status': 'error', 'message': '请提供300字以内的公开检索关键词。'}
    if include_domains is not None and not isinstance(include_domains, list):
        return {'status': 'error', 'message': '网站范围必须使用域名列表。'}
    provider = os.getenv('ASSISTANT_SEARCH_PROVIDER', '').strip().lower()
    if not provider:
        provider = 'tavily' if os.getenv('TAVILY_API_KEY') else 'serper'
    if provider not in ('tavily', 'serper'):
        return {'status': 'error', 'message': '小助手搜索服务未配置，请管理员选择 tavily 或 serper。'}
    key = os.getenv(provider.upper() + '_API_KEY', '').strip()
    if not key:
        return {'status': 'error', 'message': '小助手搜索密钥未配置，请联系管理员。'}
    domains = [str(domain).lower().strip() for domain in (include_domains or [])[:5]
               if re.fullmatch(r'(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}', str(domain).strip())]
    if include_domains and not domains:
        return {'status': 'error', 'message': '网站范围应为有效域名，例如 example.com。'}
    try:
        if provider == 'tavily':
            params = {'query': query, 'max_results': 5, 'search_depth': 'basic',
                      'topic': 'news' if news else 'general', 'include_answer': False,
                      'include_raw_content': False, 'include_images': False}
            if time_range in ('day', 'week', 'month', 'year'):
                params['time_range'] = time_range
            if domains:
                params['include_domains'] = domains
            response = requests.post('https://api.tavily.com/search', json=params,
                headers={'Authorization': 'Bearer ' + key}, timeout=(5, 18))
            response.raise_for_status()
            rows = response.json().get('results') or []
        else:
            params = {'q': query, 'num': 5}
            if domains:
                params['q'] += ' (' + ' OR '.join('site:' + domain for domain in domains) + ')'
            if time_range in ('day', 'week', 'month', 'year'):
                params['tbs'] = 'qdr:' + {'day': 'd', 'week': 'w', 'month': 'm', 'year': 'y'}[time_range]
            response = requests.post('https://google.serper.dev/' + ('news' if news else 'search'), json=params,
                headers={'X-API-KEY': key}, timeout=(5, 18))
            response.raise_for_status()
            payload = response.json()
            rows = payload.get('news' if news else 'organic') or []
        results = []
        for row in rows[:5]:
            url = safe_public_url(row.get('url') or row.get('link'))
            if not url:
                continue
            host = (urlsplit(url).hostname or '').lower()
            if domains and not any(host == domain or host.endswith('.' + domain) for domain in domains):
                continue
            results.append({'title': str(row.get('title') or url)[:250], 'url': url,
                'snippet': str(row.get('content') or row.get('snippet') or '')[:1400],
                'published_at': str(row.get('published_date') or row.get('date') or '')[:100],
                'retrieved_at': now_text(), 'provider': provider})
        return {'status': 'ok' if results else 'empty', 'query': query, 'provider': provider, 'results': results,
                'sources': [{key: value for key, value in item.items() if key != 'snippet'} for item in results],
                'message': '以下是搜索摘要，并不代表已经阅读完整网页；发布日期缺失时不能推断为今天。'}
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
        return {'status': 'error', 'message': '网页搜索暂时不可用或额度不足，本次未取得可核实结果。'}


def execute_tool(name, arguments):
    try:
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if not isinstance(arguments, dict):
            raise ValueError()
        if name == 'get_weather':
            return get_weather(arguments.get('location'), arguments.get('forecast') is True)
        if name == 'search_web':
            return search_web(arguments.get('query'), arguments.get('news') is True, arguments.get('time_range', ''), arguments.get('include_domains'))
    except (ValueError, TypeError):
        pass
    return {'status': 'error', 'message': '该工具或参数不可用；小助手仅支持天气和公开网页搜索。'}
