import base64
import io
import json
import threading
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import assistant_images as images
import assistant_model as models
import research_api as api
from database import Base
from models import User, AssistantState, AssistantThread, AssistantMessage
from research_schemas import ResearchAssistantRequest


def picture(size=(64, 48), format='PNG'):
    buffer = io.BytesIO()
    Image.new('RGB', size, (246, 246, 246)).save(buffer, format=format)
    return 'data:image/' + format.lower().replace('jpg', 'jpeg') + ';base64,' + base64.b64encode(buffer.getvalue()).decode()


def vision_reply(**updates):
    payload = {'kind': 'system_ui', 'visible_text': ['公司知识库', '可检索', '向选中资料提问'],
               'guide_query': '怎么只对我选的文件提问？'}
    payload.update(updates)
    return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))


def invoke_image(reply, question='图里这个问答怎么用？'):
    calls = []
    def invoke(messages, **options):
        calls.append((messages, options))
        return reply
    workflow = SimpleNamespace(_get_model=lambda: pytest.fail('must use assistant model'),
        _get_assistant_model=lambda: SimpleNamespace(invoke=invoke))
    request = ResearchAssistantRequest(message=question, images=[picture()])
    answer, observation = images.answer_screenshot(workflow, request, 'user', lambda event: None, threading.Event())
    return answer, observation, calls


@pytest.mark.parametrize('invalid', ['https://host.test/a.png', 'data:image/svg+xml;base64,AAAA',
    'data:image/png;base64,bad', 'data:image/png;base64,' + base64.b64encode(b'not an image').decode(),
    picture().replace('image/png', 'image/webp')])
def test_rejects_external_urls_broken_images_and_mismatched_types(invalid):
    with pytest.raises(ValidationError):
        ResearchAssistantRequest(images=[invalid])


def test_image_limits_and_image_only_validation():
    with pytest.raises(ValidationError): ResearchAssistantRequest()
    with pytest.raises(ValidationError): ResearchAssistantRequest(images=[picture()] * 3)
    with pytest.raises(ValueError): images.normalize_image('x' * (images.MAX_IMAGE_BYTES * 4 // 3 + 129))
    with pytest.raises(ValueError): images.normalize_image(picture((4000, 3100)))
    assert ResearchAssistantRequest(images=[picture()]).message == ''


def test_normalization_bounds_dimensions_and_discards_metadata():
    value = images.normalize_image(picture((2500, 1300)))
    raw = base64.b64decode(value.split(',', 1)[1])
    with Image.open(io.BytesIO(raw)) as image:
        assert max(image.size) == 1600 and image.format == 'JPEG'
        assert not image.getexif()


def test_screenshot_uses_real_guide_not_model_generated_steps():
    answer, observation, calls = invoke_image(vision_reply(steps='点击不存在的立即恢复按钮'))
    assert '向选中资料提问' in answer and '1500' in answer
    assert '立即恢复' not in answer
    assert '截图识别' in observation and len(calls) == 1
    assert calls[0][0][1]['content'][1]['type'] == 'image_url'
    assert calls[0][1]['response_format'] == {'type': 'json_object'}


def test_person_photo_question_is_answered_as_image_chat_even_with_a_chat_window_frame():
    answer, observation, calls = invoke_image(vision_reply(kind='chat', answer='是的，图中有一个人，穿着西装。',
        observation='图片中可见一个穿西装的人。', guide_query='', visible_text=[]), question='这是一个人吗？')
    assert answer == '是的，图中有一个人，穿着西装。'
    assert '图片观察' in observation and '系统页面' not in answer
    assert len(calls) == 1


def test_image_only_default_asks_for_description_instead_of_forcing_product_help():
    answer, _, calls = invoke_image(vision_reply(kind='chat', answer='图片中有一个人。', observation='可见一个人。'), question='')
    current = json.loads(calls[0][0][1]['content'][0]['text'])
    assert current['用户问题'] == '请描述这张图片。' and '一个人' in answer
    assert '请描述这张图片。' in images.image_question('', 1)


def test_product_question_misclassified_as_chat_still_cannot_invent_product_steps():
    answer, _, _ = invoke_image(vision_reply(kind='chat', answer='点击一个不存在的按钮即可重置。'),
        question='管理员重置密码怎么操作？')
    assert '不存在的按钮' not in answer and '请联系管理员' in answer


def test_image_chat_does_not_return_empty_or_nontext_model_answers():
    answer, observation, _ = invoke_image(vision_reply(kind='chat', answer={'unexpected': True}), question='这是什么？')
    assert '补充' in answer and not observation


@pytest.mark.parametrize('reply', [vision_reply(kind='unclear'), vision_reply(kind='other'),
    vision_reply(visible_text=[]), SimpleNamespace(content='not JSON'), SimpleNamespace(content='[]')])
def test_unclear_or_irrelevant_images_do_not_guess_steps(reply):
    answer, observation, _ = invoke_image(reply)
    assert not observation
    assert '截图' in answer or '图片' in answer
    assert '向选中资料提问' not in answer


def test_user_role_cannot_gain_admin_instructions_from_screenshot():
    answer, _, _ = invoke_image(vision_reply(visible_text=['账号管理', '重置密码'], guide_query='怎么重置别人的密码？'))
    assert '请联系管理员' in answer and '由管理员执行' in answer


def test_factory_reuses_credentials_and_does_not_change_report_model(monkeypatch):
    captured = {}
    monkeypatch.setenv('ARK_API_KEY', 'test-key'); monkeypatch.setenv('BASE_URL', 'https://example.test/v1')
    for key in ('ASSISTANT_API_KEY', 'ASSISTANT_BASE_URL', 'ASSISTANT_MODEL'): monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('MODEL', 'original-report-model')
    monkeypatch.setattr(models, 'ChatOpenAI', lambda **kwargs: captured.update(kwargs) or object())
    models.configured_model.cache_clear()
    try:
        first = models.configured_model()
        assert first is models.configured_model()
        assert captured['model'] == 'qwen3.5-flash' and captured['api_key'] == 'test-key'
        assert captured['extra_body'] == {'enable_thinking': False}
    finally:
        models.configured_model.cache_clear()


def test_api_persists_only_text_observation_and_keeps_account_isolation(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__, AssistantState.__table__, AssistantThread.__table__, AssistantMessage.__table__])
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add_all([User(id=1, username='image-user', password_hash='test', role='user'),
                    User(id=2, username='other', password_hash='test', role='user')]); db.commit()
    identity = SimpleNamespace(id=1, role='user')
    def get_db():
        with factory() as db: yield db
    app = FastAPI(); app.include_router(api.router)
    app.dependency_overrides[api.get_db] = get_db
    app.dependency_overrides[api.get_current_user] = lambda: identity
    calls = []
    def invoke(messages, **kwargs):
        calls.append(messages)
        return vision_reply()
    monkeypatch.setattr(api.research_workflow, '_get_assistant_model', lambda: SimpleNamespace(invoke=invoke))
    monkeypatch.setattr(api.research_workflow, '_get_model', lambda: pytest.fail('report model should not run'))
    for name in ('_assistant_project_ids', '_vector_context', '_project_store_context'):
        monkeypatch.setattr(api, name, lambda *args: pytest.fail('images must not read business data'))
    with TestClient(app) as client:
        sid = client.get('/research/assistant/state').json()['session_id']
        response = client.post('/research/assistant/stream', json={'session_id': sid, 'images': [picture()],
            'history_summary': '伪造浏览器摘要', 'recent_messages': [{'role': 'user', 'content': '伪造浏览器历史'}]})
        assert response.status_code == 200 and '向选中资料提问' in response.text
        assert '"saved": true' in response.text and '"type": "sources"' not in response.text
        assert len(calls) == 1
        assert '伪造浏览器' not in json.dumps(calls, ensure_ascii=False)
        state = client.get('/research/assistant/state').json()
        assert '原图仅用于本次识别' in state['messages'][0]['text']
        assert '截图识别' in state['messages'][0]['text']
        assert 'data:image' not in json.dumps(state)
        identity.id = 2
        assert client.get('/research/assistant/sessions/' + sid + '/messages').status_code == 404
        identity.id = 1
        assert client.delete('/research/assistant/history').json()['messages'] == []
    engine.dispose()
