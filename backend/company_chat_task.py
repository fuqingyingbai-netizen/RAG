"""Small conversation checkpoint: user intent only, never retrieved facts."""
import re

FORMAT = re.compile(r'^(?:请)?(?:把(?:上面|刚才|之前)?(?:的)?(?:回答|答案|内容|结果)?|将(?:回答|答案|内容|结果))?(?:整理|改|转换|转)?成(?:一个)?(表格|列表|清单|段落)[。！!？?\s]*$')
SINGULAR = re.compile(r'它(?!们)|该公司|这家公司|这个项目|该项目')
CORRECTION = re.compile(r'^(?:我指的是|我说的是|指的是)')


def fresh(question):
    pair = re.match(r'^(?:请)?(?:比较|对比)([^，。？?的]{1,60}?)(?:和|与|、)([^，。？?的]{1,60}?)(?:的|在|之间|有什么|有哪些|有何|[。？?]|$)', question)
    subjects = [pair[1].strip(), pair[2].strip()] if pair else []
    # shortcut: recognize only a complete, literal company/field template; other wording uses the model.
    single = re.fullmatch(r'(?:请)?(?:介绍|查询|列出|分析|告诉我)?([^，。？?的与和\s]{1,60}?公司)'
        r'(20\d{2}年)?的(营业收入|收入|客户数量|客户数|目标用户|收费方式|价格)(?:是(?:多少|什么|谁)|有多少)?[？?。\s]*', question)
    project = re.fullmatch(r'(?:请)?(?:查询|列出|介绍)?([^，。？?的与和、\s]{1,60}项目)'
        r'(20\d{2}(?:年度|年))?的?(批准预算|预算额度|预算|试验预算|负责人|客户数量|客户数)'
        r'(?:是(?:多少(?:万元)?|什么|谁)|有多少)?[？?。\s]*'
        r'(保留预算口径并引用[，,](?:仅用两句话回答[，,])?(?:800字以内[。]?)?)?', question)
    single = single or project
    if single and single[1] not in ('该公司', '这家公司', '那个公司', '这个公司', '我们公司', '这个项目', '该项目', '那个项目', '本项目'):
        subjects = [single[1]]
    else:
        single = None
    constraints = [single[2]] if single and single[2] else []
    if project and project[4]:
        constraints.append(project[4])
    return {'request': question, 'subjects': subjects, 'topic': single[3] if single else '', 'format': 'auto',
            'constraints': constraints,
            'structured': bool(subjects), 'needs_clarification': False}


def local_followup(question, task):
    """Return (handled, query, next state); leave uncertain language to the model."""
    if not task or not task.get('request'):
        return False, None, None
    if task.get('rewrite_failed') and (SINGULAR.search(question) or FORMAT.fullmatch(question.strip())
            or re.fullmatch(r'(?:请)?(?:继续|再详细|再展开|展开说|为什么|可以展开吗|客户数(?:量)?|收费方式|收入|价格|怎么收费|有哪些风险)[呢？?。\s]*', question)):
        return True, None, {**task, 'unresolved_question': question}
    output = FORMAT.fullmatch(question.strip())
    if output and not task.get('needs_clarification'):
        return True, task['request'], {**task, 'format': output[1]}
    if not task.get('structured'):
        return False, None, None
    subjects = task['subjects']
    if SINGULAR.search(question) and len(subjects) > 1:
        return True, None, {**task, 'needs_clarification': True, 'unresolved_question': question}
    if len(subjects) != 1 or task.get('needs_clarification'):
        return False, None, None
    # shortcut: only short, explicit field requests; new objects and ordinals use rewriting.
    field = re.fullmatch(r'(?:那)?(客户数|客户数量|负责人|收入|营业收入|收费方式|价格|目标用户|商业模式|有哪些风险|怎么收费)[呢？?。\s]*', question)
    if field:
        topic = field[1]
        query = subjects[0] + ('' if topic in ('有哪些风险', '怎么收费') else '的') + topic + '？'
    else:
        match = re.fullmatch(r'(?:那)?(?:它|该公司|这家公司|这个项目|该项目)(?:的)?'
            r'((?:客户数(?:量)?|负责人|营业收入|收入|目标用户|商业模式|收费方式|价格)(?:是(?:多少|什么|谁)|有多少)?|怎么收费|有哪些风险)'
            r'[呢？?。\s]*(仅回答姓名并引用[。]?)?', question)
        if not match:
            return False, None, None
        topic = match[1]
        query = subjects[0] + ('' if topic in ('有哪些风险', '怎么收费') else '的') + topic + '？'
        if match[2]:
            query += match[2]
    constraints = task.get('constraints', [])
    if constraints:
        query += '；' + '；'.join(constraints)
    if len(query) > 1500:
        return False, None, None
    return True, query, {**task, 'request': query, 'topic': topic, 'needs_clarification': False}


def from_rewrite(payload, question, previous, user_text):
    query = payload['query']
    if query is None:
        return {**(previous or fresh(question)), 'needs_clarification': True, 'unresolved_question': question}
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
    if any(subject not in query for subject in subjects):
        raise ValueError('query lost resolved subject')
    intent = previous.get('unresolved_question', question) if previous and CORRECTION.search(question) else question
    for terms in ('收费|价格|定价|费用|计费', '客户', '收入|营收'):
        if re.search(terms, intent) and not re.search(terms, query):
            raise ValueError('query lost explicit field')
    return {**task, 'subjects': list(dict.fromkeys(subjects)), 'topic': topic, 'format': output,
            'constraints': list(dict.fromkeys(constraints)), 'structured': True}
