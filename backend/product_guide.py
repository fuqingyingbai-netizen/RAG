"""Search the maintained product manual, never customer documents or web pages."""
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

CATALOG = json.loads(Path(__file__).with_name('guide_catalog.json').read_text(encoding='utf-8'))
PAGES = {key: (page['title'], page['summary']) for key, page in CATALOG['pages'].items()}
GUIDE_TOOL = {'type': 'function', 'function': {
    'name': 'search_system_guide',
    'description': '查本系统实际功能的使用指南：页面入口、填写步骤、权限、文件格式、状态、异常排查、账号与小助手记忆。优先用功能目录里的主题名称定位，再补具体关键词。系统操作问题必须参考此指南，不查公开网页或用户业务资料；空结果时换简短同义词再查，不执行任何业务操作。',
    'parameters': {'type': 'object', 'properties': {
        'query': {'type': 'string', 'description': '要查的功能或具体使用问题，最多300字，例如“行业范围怎么填”“文件不能勾选”“恢复已归档账号”。'}}, 'required': ['query']}}}


def normalize(text):
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', unicodedata.normalize('NFKC', str(text)).lower())


def visible_topics(role='user'):
    return [topic for topic in CATALOG['topics'] if role in topic['roles']]


def _grams(text):
    return {text[i:i + 2] for i in range(len(text) - 1)}


_SEARCH_TEXT = {topic['id']: normalize(' '.join([topic['title'], *topic['aliases']])) for topic in CATALOG['topics']}
_FREQUENCY = Counter(gram for value in _SEARCH_TEXT.values() for gram in _grams(value))


def find_topics(question, page='submit', role='user', limit=5):
    """Exact titles/aliases first; rare character pairs support paraphrases."""
    query = normalize(str(question)[:6000])
    if not query:
        return []
    grams, ranked = _grams(query), []
    for topic in visible_topics(role):
        aliases = [normalize(topic['title']), *map(normalize, topic['aliases'])]
        matched = [alias for alias in aliases if len(alias) >= 2 and alias in query]
        exact = any(query == alias for alias in aliases)
        score = 200 if exact else max((50 + min(len(alias), 20) for alias in matched), default=0)
        if any(all(normalize(term) in query for term in pattern) for pattern in topic.get('patterns', [])):
            score = max(score, 80)
        overlap = grams & _grams(_SEARCH_TEXT[topic['id']])
        score += min(35, sum(math.log(1 + len(CATALOG['topics']) / _FREQUENCY[g]) for g in overlap))
        if topic['page'] == page and score:
            score += 1
        if score >= 4:
            ranked.append((score, topic))
    ranked.sort(key=lambda pair: -pair[0])
    return [dict(topic, score=round(score, 2)) for score, topic in ranked[:max(1, min(8, limit))]]


def is_product_question(question):
    query = normalize(question)
    if any(term in query for term in ('帮我写', '写一份', '写一篇', '改写', '润色')) and not any(term in query for term in ('页面', '本系统', '怎么填', '按钮')):
        return False
    strong = find_topics(question, role='admin', limit=1)
    if strong and strong[0]['score'] >= 50:
        return True
    if any(term in query for term in ('任务管理', '提交任务', '新建任务', '提交尽调', '溯源库', '公司知识库',
        '知识库', '邀请码', '临时密码', '账号管理', '归档账号', '停用账号', '待复核稿', '复核与一手资料',
        '二阶段', '历史版本', '重试归档', '清空记录', '新对话', '权限申请', '功能目录', '系统指南',
        '修改密码', '重置密码', '登录', '注册', '暂停', '重跑', '下载报告', '报告下载', '人物报告',
        '行业报告', '研究任务', '上传资料', '复核', '筛选', '资料库', '原件', '数据截止日',
        '提升为管理员', '降级管理员', '管理员权限', '上传文件', '上传材料', '建议书',
        '桌面研究', '申请权限', '查看报告', '报告预览', '文件打不开')):
        return True
    if any(term in query for term in ('本系统', '这个系统', '这套系统', '本平台', '这个平台', '当前页面', '这个页面', '按钮')):
        return True
    if '小助手' in query:
        return any(term in query for term in ('怎么用', '怎么使用', '能干什么', '能做什么', '支持什么', '能查天气吗', '记忆', '上下文', '功能', '操作', '联网', '模型'))
    return any(normalize(topic['title']) == query or query == normalize(alias)
               for topic in CATALOG['topics'] for alias in topic['aliases'])


def is_guide_request(request):
    """Resolve short follow-ups against recent guide turns, not just keywords."""
    if is_product_question(request.message):
        return True
    query = normalize(request.message)
    if any(term in query for term in ('天气', '新闻', '聊聊', '闲聊', '帮我写', '写一', '改写', '润色',
        '翻译', '算一下', '我住哪', '我叫什么', '我的名字', '你记得', '我之前说', '秋招', '面试',
        '心情', '压力', '紧张', '焦虑', '难过', '找工作')):
        return False
    contextual = len(query) <= 100 and (any(term in query for term in (
        '这个', '那个', '这一步', '下一步', '接下来', '然后', '第二个', '你说的', '再详细', '继续讲', '具体步骤'))
        or query in ('怎么做', '为什么', '在哪里', '没找到', '还是不行', '详细一点'))
    if not contextual:
        return False
    history = list(request.recent_messages[-6:])
    if history and history[-1].get('role') == 'user' and history[-1].get('content') == request.message:
        history.pop()
    return any((row.get('role') == 'user' and is_product_question(row.get('content', ''))) or
               (row.get('role') == 'assistant' and str(row.get('content', '')).startswith('### ') and
                any(topic['title'] in str(row.get('content', ''))[:120] for topic in CATALOG['topics']))
               for row in history[-4:])


def format_topic(topic):
    return f'### {topic["title"]}\n\n{topic["body"]}'


def directory(role='user'):
    lines = ['### 系统功能目录', '可以直接问下面任一功能的名称，我会说明入口、步骤、权限和注意事项。']
    for page, (title, _) in PAGES.items():
        topics = [topic for topic in visible_topics(role) if topic['page'] == page]
        if topics:
            lines += ['\n**' + title + '**', *['- ' + topic['title'] for topic in topics]]
    lines.append('\n小助手只提供操作说明；真实项目、文件内容和操作结果请到对应页面核对。')
    return '\n'.join(lines)


def page_help(page, role='user'):
    title, summary = PAGES[page]
    topics = [topic for topic in visible_topics(role) if topic['page'] == page]
    lines = [f'### {title}', summary, '\n可以继续问这些具体功能：']
    for topic in topics:
        lines.append(f'- **{topic["title"]}**：{topic["body"].split(chr(10))[0][:160]}')
    return '\n\n'.join(lines)


def guide_context(question, page, role):
    # The compact inventory makes every maintained capability discoverable;
    # detailed relevant topics and the local tool provide the operational facts.
    overview = '\n'.join(f'【{title}】{summary}' for key, (title, summary) in PAGES.items()
                         if key != 'accounts' or role == 'admin')
    topics = find_topics(question, page, role, limit=6)
    return overview + '\n\n' + directory(role) + '\n\n相关功能详细说明：\n' + '\n\n'.join(format_topic(topic) for topic in topics)


def search_guide(arguments, page, role):
    if not isinstance(arguments, dict) or not isinstance(arguments.get('query'), str) or not 0 < len(arguments['query'].strip()) <= 300:
        return {'status': 'error', 'message': '请提供300字以内的功能名称或使用问题。'}
    topics = find_topics(arguments['query'], page, role)
    if topics and topics[0]['score'] < 10:
        topics = []
    if not topics:
        return {'status': 'empty', 'kind': 'system_guide', 'topics': [],
                'message': '当前使用指南没有找到这个功能。请补充所在页面、按钮名称或具体提示；不能确认它已经实现。'}
    return {'status': 'ok' if topics else 'empty', 'kind': 'system_guide',
            'message': '这是按当前角色提供的本系统使用指南，不是用户业务数据，也不代表已经执行任何操作。未找到精确说明时请明确询问页面或按钮，不编造。',
            'topics': [{key: topic[key] for key in ('id', 'page', 'title', 'body')} |
                       {'match': 'phrase' if topic['score'] >= 50 else 'approximate'} for topic in topics]}


def answer_from_lookup(result):
    """The model may select a topic, but never invent the operational steps."""
    topics = result.get('topics') or []
    if not topics:
        return result.get('message') or '未找到这项操作，请补充所在页面或按钮名称。'
    chosen = topics[:1]
    if len(topics) > 1 and topics[0].get('match') == topics[1].get('match') == 'phrase':
        chosen = topics[:2]
    lead = '' if topics[0].get('match') == 'phrase' else '找到以下可能相关的实际操作说明；如果不是你要问的功能，请补充所在页面或按钮名称。\n\n'
    return lead + '\n\n'.join(format_topic(topic) for topic in chosen)
