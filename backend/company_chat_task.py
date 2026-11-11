"""Small conversation checkpoint: user intent only, never retrieved facts."""
import re

FORMAT = re.compile(r'^(?:请)?(?:把(?:上面|刚才|之前)?(?:的)?(?:回答|答案|内容|结果)?|将(?:回答|答案|内容|结果))?(?:整理|改|转换|转)?成(?:一个)?(表格|列表|清单|段落)[。！!？?\s]*$')
SINGULAR = re.compile(r'它(?!们)|该公司|这家公司|这个项目')
CORRECTION = re.compile(r'^(?:我指的是|我说的是|指的是)')


def fresh(question):
    return {'request': question, 'subjects': [], 'topic': '', 'format': 'auto',
            'constraints': [], 'structured': False, 'needs_clarification': False}


def local_followup(question, task):
    """Return (handled, query, next state); leave uncertain language to the model."""
    if not task or not task.get('request'):
        return False, None, None
    output = FORMAT.fullmatch(question.strip())
    if output and not task.get('needs_clarification'):
        return True, task['request'], {**task, 'format': output[1]}
    if not task.get('structured'):
        return False, None, None
    subjects = task['subjects']
    if SINGULAR.search(question) and len(subjects) > 1:
        return True, None, {**task, 'needs_clarification': True}
    if len(subjects) != 1 or task.get('needs_clarification'):
        return False, None, None
    # shortcut: only short, explicit field requests; new objects and ordinals use rewriting.
    field = re.fullmatch(r'(?:那)?(客户数|客户数量|收入|营业收入|收费方式|价格|目标用户|商业模式|有哪些风险|怎么收费)[呢？?。\s]*', question)
    if field:
        topic = field[1]
        query = subjects[0] + '的' + topic + '？'
    else:
        match = re.fullmatch(r'(?:那)?(?:它|该公司|这家公司|这个项目)(?:的)?(.{1,60})', question)
        if not match or SINGULAR.search(match[1]) or re.search(r'比较|相比|第[一二三\d]|和|与', match[1]):
            return False, None, None
        topic = match[1]
        query = subjects[0] + '的' + topic
    constraints = task.get('constraints', [])
    if constraints:
        query += '；' + '；'.join(constraints)
    if len(query) > 1500:
        return False, None, None
    return True, query, {**task, 'request': query, 'topic': topic, 'needs_clarification': False}


def from_rewrite(payload, question, previous, user_text):
    query = payload['query']
    if query is None:
        return {**(previous or fresh(question)), 'needs_clarification': True}
    task = fresh(query)
    # Older providers may return only query; retain compatibility without guessing entities.
    if 'subjects' not in payload:
        return task
    subjects, constraints = payload['subjects'], payload.get('constraints', [])
    source = question + '\n' + user_text + '\n' + (previous or {}).get('request', '')
    for values, limit in ((subjects, 8), (constraints, 8)):
        if (not isinstance(values, list) or len(values) > limit
                or any(not isinstance(value, str) or not 0 < len(value) <= 120 or value not in source for value in values)):
            raise ValueError('invalid task metadata')
    topic, output = payload.get('topic', ''), payload.get('format', 'auto')
    if not isinstance(topic, str) or len(topic) > 200 or output not in ('auto', '表格', '列表', '清单', '段落'):
        raise ValueError('invalid task metadata')
    return {**task, 'subjects': list(dict.fromkeys(subjects)), 'topic': topic, 'format': output,
            'constraints': list(dict.fromkeys(constraints)), 'structured': True}
