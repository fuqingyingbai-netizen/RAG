"""Conservative pre-retrieval routing; business facts always need evidence."""
import re
import unicodedata

INTENTS = {'smalltalk', 'assistant', 'knowledge', 'transform', 'clarify'}
KNOWLEDGE = re.compile(r'资料|文件|文档|报告|原文|引用|来源|依据|公司|项目|预算|收入|营收|客户|收费|价格|风险|负责人|产品|商业|定位|指标|数据|合同|专利|技术|材料|证据|检索|总结|对比|比较|分析|整理|表格|Meshy|Tripo|Rodin|豆包|\b(?:summarize|analyse|analyze|compare|document|report)\b', re.I)
SOCIAL = re.compile(r'(?:你好[呀啊]?|您好|嗨|哈[喽啰]|在吗|在不在|有人吗|早上好|早安|上午好|中午好|下午好|晚上好|晚安|'
    r'谢谢(?:你|您|啦|了|啊)?|多谢(?:你|您)?|感谢(?:你|您)?|辛苦了|不客气|再见|拜拜|拜|'
    r'好的?|好呀|好哒|行|可以|明白(?:了)?|了解(?:了)?|收到|知道了|没问题|'
    r'聊聊(?:天)?|聊聊天|聊会儿天|陪我聊聊天|我们聊聊天吧|hello|hi|hey|thanks|thankyou|bye|ok|okay)+', re.I)
SYSTEM = re.compile(r'(?:请问|请问一下|我想知道|告诉我|请告诉我)?(?:我(?:应该|该|要)?)?'
    r'(?:在(?:本|这个|当前)(?:系统|平台|页面))?(?:怎么|如何|在哪(?:里)?|哪里可以)'
    r'(?:上传(?:文件|资料|材料|文档|视频|图片|音频)|下载(?:文件|报告|原件)|修改密码|重置密码|'
    r'申请权限|新建(?:会话|对话)|删除(?:会话|对话)|使用(?:知识库|本系统|这个系统|AI助手|ai助手))'
    r'(?:呢|啊|呀|的)?')

INSTRUCTION = ('\n同时判断意图，只能选smalltalk（纯闲聊）、assistant（本系统操作咨询，转去AI助手）、'
    'knowledge（资料问答）、transform（已有内容的格式加工）、clarify（对象不明）。'
    '问候加业务任务按业务处理；感谢、闲聊和系统咨询不得覆盖当前业务对象。'
    '不能因资料可能没有答案而判为闲聊；知识库相关的业务概念、解释和事实问题也属于knowledge。'
    '纯格式加工仍补全为原业务检索问题。多个并列对象的单数指代需clarify；单一对象的追问应补全。'
    '在原JSON中增加"intent"字段；smalltalk、assistant、clarify的query必须是null，'
    'knowledge、transform的query必须是完整检索问题。不要输出闲聊答案或调用工具。')


def compact(question):
    return re.sub(r'[\s，,。.!！?？~～、；;]+', '', unicodedata.normalize('NFKC', question)).strip()


def local_route(question):
    text = compact(question)
    if SOCIAL.fullmatch(text):
        return {'intent': 'smalltalk', 'query': None}
    if not knowledge_signal(question) and re.search(
            r'陪我.{0,6}(?:聊|说)|想.{0,8}(?:聊|说说话)|(?:随便|随意|随口).{0,4}聊|你(?:今天)?过得怎么样|你.{0,4}说话.{0,8}(?:有趣|有意思)', question):
        return {'intent': 'smalltalk', 'query': None}
    system_ui = (re.fullmatch(r'(?:本|这个|当前)(?:页面|系统)(?:的)?(?:上传|下载|新建对话)(?:按钮|入口)(?:在哪(?:里)?|怎么找)', text)
                 or re.fullmatch(r'(?:文件|资料|视频|图片|音频)上传失败(?:了)?(?:我(?:应该|该|要)?)?(?:去)?(?:哪里|怎么|如何)(?:重试|重新上传)', text))
    if SYSTEM.fullmatch(text) or system_ui:
        return {'intent': 'assistant', 'query': None}
    return None


def knowledge_signal(question):
    return bool(KNOWLEDGE.search(question))


def validate(payload, question, task):
    # Query-only replies from existing providers remain evidence-bound.
    intent = payload.get('intent', 'clarify' if payload['query'] is None else 'knowledge')
    if not isinstance(intent, str) or intent not in INTENTS:
        raise ValueError('invalid intent')
    query = payload['query']
    if intent in {'knowledge', 'transform'}:
        if not isinstance(query, str) or not query.strip():
            raise ValueError('business intent requires query')
    elif query is not None:
        raise ValueError('non-business intent requires null query')
    if intent in {'smalltalk', 'assistant'}:
        system_wording = (intent == 'assistant' and re.search(r'怎么|如何|在哪|哪里|按钮|页面|本系统|这个系统', question)
                          and not re.search(r'公司|项目|预算|收入|客户|收费|价格|风险|依据|根据|资料[中里]|文件[中里]|文档[中里]', question))
        if knowledge_signal(question) and not system_wording:
            raise ValueError('business request cannot skip retrieval')
        if task.get('request') and re.fullmatch(r'(?:那)?(?:它|他们|她们|它们)?(?:呢|继续|为什么|再详细|展开说)[？?。！!\s]*', question):
            raise ValueError('business followup cannot become smalltalk')
    return {'intent': intent, 'query': query.strip() if isinstance(query, str) else None}


def reply(route, question):
    if route['intent'] == 'assistant':
        return '系统操作问题请到“AI 助手”咨询；这里可以帮你查找、总结和比较知识库资料。'
    if re.search(r'谢谢|感谢|多谢|辛苦|thanks|thank\s*you', question, re.I):
        return '不客气！需要查资料时，直接告诉我问题即可。'
    if re.search(r'再见|拜|晚安|bye', question, re.I):
        return '再见，需要查资料时随时来问。'
    if re.search(r'聊|心情|难过|压力|烦|累', question):
        return '可以聊聊。你想聊些什么？'
    return '你好！可以帮你查找资料、总结报告、比较不同资料的结论，并提供引用依据。'
