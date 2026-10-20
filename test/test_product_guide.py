import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import product_guide as catalog
import research_api as api
import system_guide as guide
from database import Base
from models import User, AssistantState, AssistantThread, AssistantMessage
from research_schemas import ResearchAssistantRequest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('question,expected,words', [
    ('知识库上传支持什么格式，最大多大？', 'knowledge-upload', ['32 MB', 'PPT', '索引']),
    ('任务筛选后看不到项目怎么办？', 'task-filters', ['清空筛选', '页码', '账号']),
    ('行业的数据截止日怎么设置？', 'industry-scope', ['中国大陆', '提交日期', '16章']),
    ('人物同名时要补什么线索？', 'person-intake', ['任职时间', '排除同名', '15节']),
    ('已归档账号恢复后能直接登录吗？', 'admin-archive', ['停用', '另行启用', '保留']),
    ('怎么查看历史版本？', 'report-history', ['记录 001', '12万字', '没有']),
    ('为什么文件不能勾选问答？', 'knowledge-processing', ['可检索', '阅读权限', '重试']),
    ('小助手和知识库有什么区别？', 'assistant-role', ['主要职责', '不读取', '不能替你']),
    ('管理员能看到我的聊天吗？', 'assistant-privacy', ['按登录账号ID隔离', '不能通过小助手接口', '数据库运维']),
    ('怎么只对我选的文件提问？', 'knowledge-qa', ['向选中资料提问', '1500', '空范围']),
    ('报告已经完成怎么我的项目还没有？', 'report-archive', ['重试归档', '限制访问', '索引']),
    ('怎么保存资料库筛选条件？', 'knowledge-filters', ['浏览器', '排序', '分页']),
    ('可以一次删掉所有任务吗？', 'delete-task', ['没有批量', '运行中', '公司知识库']),
    ('关闭AI搜索为什么还联网？', 'research-inputs', ['固定策略', '专业平台', '人物/行业']),
    ('邀请有效期多长？', 'admin-invitations', ['六小时', '只能注册一个', '展示一次']),
    ('专业平台余额不足是不是对象没有风险？', 'professional-platforms', ['采集缺口', '不代表', '管理员']),
    ('知识库聊天记录会像小助手一样保存吗？', 'knowledge-chat-history', ['当前页面组件', '服务器', '不保证恢复']),
    ('小助手的新对话和清空记录分别是什么？', 'assistant-conversations', ['旧会话', '全部', '不影响公司知识库']),
])
def test_real_usage_questions_find_specific_operational_answers(question, expected, words):
    assert catalog.find_topics(question, 'submit', 'admin', 1)[0]['id'] == expected
    answer = guide.guide_answer(question, role='admin')
    assert answer
    for word in words:
        assert word in answer


def test_catalog_covers_actual_pages_and_referenced_controls_still_exist():
    html = (ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    actual = set(re.findall(r"activeView\s*===\s*'([^']+)'", html))
    assert actual == set(catalog.PAGES)
    ids = [topic['id'] for topic in catalog.CATALOG['topics']]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 60
    for topic in catalog.CATALOG['topics']:
        assert topic['page'] in actual and topic['body'] and topic['aliases']
        for ref in topic['code_refs']:
            assert ref['anchor'] in (ROOT / ref['path']).read_text(encoding='utf-8-sig'), (topic['id'], ref)


def test_generated_manual_is_identical_to_runtime_catalog():
    spec = importlib.util.spec_from_file_location('build_guide', ROOT / 'scripts/build-system-guide.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert (ROOT / 'docs/SYSTEM_USER_GUIDE.md').read_text(encoding='utf-8') == module.render()


def test_every_topic_is_discoverable_and_exact_titles_are_unambiguous():
    for topic in catalog.visible_topics('admin'):
        assert catalog.find_topics(topic['title'], topic['page'], 'admin', 1)[0]['id'] == topic['id']
        assert topic['title'] in catalog.directory('admin')
        assert topic['body'] in guide.guide_answer(topic['title'], topic['page'], 'admin')


def test_ordinary_roles_never_receive_admin_walkthroughs():
    result = catalog.search_guide({'query': '管理员邀请码、操作日志和恢复账号'}, 'accounts', 'user')
    assert all(topic['page'] != 'accounts' for topic in result['topics'])
    assert '### 账号与注册' in guide.guide_answer('如何生成邀请码？', role='user')
    assert '请联系管理员' in guide.guide_answer('管理员账号怎么归档恢复？', role='user')
    assert '管理员账号列表' not in catalog.directory('user')
    prompt = guide.chat_prompt(ResearchAssistantRequest(message='怎么生成管理员邀请码？', current_page='accounts'), 'user')
    assert '【账号管理】' not in prompt and 'expires_in_hours' not in prompt


@pytest.mark.parametrize('question', ['小助手，上海今天天气怎么样？', '帮我写一篇行业报告', '我之前说我住哪里？', '你好，聊聊周末的安排'])
def test_general_chat_weather_and_personal_recall_are_not_replaced_with_manual(question):
    assert not catalog.is_product_question(question)
    assert guide.guide_answer(question) == ''


class FakeModel:
    def __init__(self, responses):
        self.responses = iter(responses); self.schemas = []; self.messages = []; self.options = []
    def bind_tools(self, schemas): self.schemas = schemas; return self
    def invoke(self, messages, **kwargs):
        self.messages.append(list(messages)); self.options.append(kwargs); return next(self.responses)


def test_model_can_find_local_guide_details_without_any_public_search(monkeypatch):
    model = FakeModel([
        SimpleNamespace(content='', tool_calls=[{'id': 'guide1', 'name': 'search_system_guide', 'args': {'query': '选中文件 限定问答范围'}}]),
        SimpleNamespace(content='勾选已完成索引的资料，点击“向选中资料提问”。', tool_calls=[]),
    ])
    monkeypatch.setattr(guide, 'execute_tool', lambda *args: pytest.fail('system usage must not query an external provider'))
    events = []
    answer = guide.model_answer(SimpleNamespace(_get_model=lambda: model),
        ResearchAssistantRequest(message='在这个系统里，我只想回答依据三份我挑的文件，该怎么做？'), 'user', events.append)
    assert '向选中资料提问' in answer
    assert {schema['function']['name'] for schema in model.schemas} == {'search_system_guide'}
    assert model.options[0]['tool_choice']['function']['name'] == 'search_system_guide'
    assert len(model.messages) == 1
    payload = catalog.search_guide({'query': '选中文件 限定问答范围'}, 'submit', 'user')
    assert payload['kind'] == 'system_guide'
    assert any(topic['id'] == 'knowledge-qa' for topic in payload['topics'])
    assert events[0]['content'] == '正在查阅系统使用指南…'
    assert not any(event['type'] == 'sources' for event in events)


def test_model_cannot_replace_verified_steps_with_invented_controls():
    model = FakeModel([SimpleNamespace(content='打开资料归集，然后选择手动文件选择器。', tool_calls=[])])
    answer = guide.model_answer(SimpleNamespace(_get_model=lambda: model),
        ResearchAssistantRequest(message='这个系统能在报销审批台上批量退款吗？'), 'user')
    assert '资料归集' not in answer and '手动文件选择器' not in answer


def test_guide_lookup_is_formatted_without_a_second_freeform_completion(monkeypatch):
    model = FakeModel([SimpleNamespace(content='', tool_calls=[{'id': 'guide', 'name': 'search_system_guide', 'args': {'query': '历史版本'}}]),
                       SimpleNamespace(content='点击一键恢复旧版。', tool_calls=[])])
    answer = guide.model_answer(SimpleNamespace(_get_model=lambda: model),
        ResearchAssistantRequest(message='这个系统能一键比较两份报告的文字差异并恢复旧稿吗？'), 'user')
    assert '没有' in answer and '一键恢复旧版' in answer
    assert len(model.messages) == 1


def test_empty_lookup_can_retry_with_a_more_precise_local_query():
    model = FakeModel([
        SimpleNamespace(content='', tool_calls=[{'id': 'first', 'name': 'search_system_guide', 'args': {'query': '不存在的报销退款流程'}}]),
        SimpleNamespace(content='', tool_calls=[{'id': 'second', 'name': 'search_system_guide', 'args': {'query': '历史版本'}}]),
    ])
    answer = guide.model_answer(SimpleNamespace(_get_model=lambda: model),
        ResearchAssistantRequest(message='这个系统以前保存的成果从哪里看？'), 'user')
    assert '### 历史版本、记录编号与正文预览' in answer
    assert '记录 001' in answer and len(model.messages) == 2


def test_short_followup_keeps_local_guide_scope_but_chat_and_weather_can_switch_topics():
    prior = [{'role': 'user', 'content': '怎么查看历史版本？'},
             {'role': 'assistant', 'content': guide.guide_answer('怎么查看历史版本？')}]
    assert catalog.is_guide_request(ResearchAssistantRequest(message='这个能恢复成之前那份吗？', recent_messages=prior))
    assert not catalog.is_guide_request(ResearchAssistantRequest(message='小助手，上海今天天气怎么样？', recent_messages=prior))
    assert not catalog.is_guide_request(ResearchAssistantRequest(message='聊聊面试压力吧', recent_messages=prior))
    assert catalog.is_product_question('建议书和桌面研究有什么区别？')
    assert catalog.is_product_question('上传文件怎么弄？')
    assert catalog.is_product_question('这个平台的收藏入口在哪？')


def test_execution_layer_rejects_public_search_even_if_model_requests_it(monkeypatch):
    model = FakeModel([SimpleNamespace(content='', tool_calls=[{'id': 'bad', 'name': 'search_web', 'args': {'query': '本系统资料'}}])])
    monkeypatch.setattr(guide, 'execute_tool', lambda *args: pytest.fail('product help cannot leave this service'))
    answer = guide.model_answer(SimpleNamespace(_get_model=lambda: model), ResearchAssistantRequest(message='这个系统的某个按钮怎么操作？'), 'user')
    assert '不能使用公开网络检索' in answer


def test_unknown_feature_offline_clarifies_instead_of_inventing_buttons():
    answer = guide.model_answer(SimpleNamespace(_get_model=lambda: None), ResearchAssistantRequest(message='这个系统的报销审核在哪里？'), 'user')
    assert '尚未确认' in answer and '页面或按钮' in answer


def test_precise_page_question_is_not_overridden_by_generic_usage_trigger():
    answer = guide.guide_answer('公司知识库怎么使用，为什么文件不能勾选问答？', 'company-knowledge')
    assert '只有你有阅读权限且状态为可检索' in answer
    assert '### 新人入门' not in answer
    assert '知识库研究首页' not in answer


def test_long_history_does_not_make_offline_guides_depend_on_summary_model(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__, AssistantState.__table__, AssistantThread.__table__, AssistantMessage.__table__])
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(id=21, username='guide-long', password_hash='test', role='user')); db.commit()
    def get_db():
        with factory() as db: yield db
    app = FastAPI(); app.include_router(api.router)
    app.dependency_overrides[api.get_db] = get_db
    app.dependency_overrides[api.get_current_user] = lambda: SimpleNamespace(id=21, username='guide-long', role='user')
    monkeypatch.setattr(api.research_workflow, '_get_assistant_model', lambda: pytest.fail('local guide must not call any model'))
    with TestClient(app) as client:
        sid = client.get('/research/assistant/state').json()['session_id']
        with factory() as db:
            for index in range(44):
                db.add(AssistantMessage(thread_id=sid, request_id=f'{index:036}', role='user', content='旧对话资料' * 200))
            db.commit()
        response = client.post('/research/assistant/stream', json={'session_id': sid, 'message': '知识库上传支持什么格式？'})
        assert response.status_code == 200 and '32 MB' in response.text
        assert '"saved": true' in response.text and '"type": "sources"' not in response.text
    engine.dispose()
