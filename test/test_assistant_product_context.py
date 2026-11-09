"""Real scope metadata and offline help, without reading customer document text."""
import json
from types import SimpleNamespace

import pytest
from research_schemas import ResearchAssistantRequest
from assistant_product_context import resolve_location
from system_guide import answer_for_request
from test_company_workspace import setup, project


def request(**context):
    return ResearchAssistantRequest(message='我新建的笔记保存在这个目录下面吗？', current_page='company-knowledge',
                                    knowledge_context={'mode': 'cases', 'collection': 'experience', **context})


def answer(setup, req):
    with setup.db() as db:
        req._guide_location = resolve_location(db, setup.user, req)
    return answer_for_request(req, setup.user.role)


def test_project_subdirectory_and_capture_have_distinct_destinations(setup):
    p = project(setup, 'test', category='项目经验')
    f = setup.client.post('/company-knowledge/projects/' + p['id'] + '/folders', json={'name': '录音'}).json()
    text = answer(setup, request(project_id=p['id'], folder_id=f['id']))
    assert 'test / 录音' in text and '「上传文件」保存在这里' in text and '「新建图文笔记」也保存在这里' in text
    text = answer(setup, request(project_id=p['id'], folder_id=f['id'], dialog='capture'))
    assert '不会跟随' in text and '待整理' in text and 'test' not in text
    assert '待整理' in answer(setup, request())


def test_open_note_uses_stored_directory_not_the_background_page(setup):
    p = project(setup, '真正归档项目', category='手稿笔记')
    other = project(setup, '背景项目', category='项目经验')
    note = setup.client.post('/company-knowledge/notes', json={'project_id': p['id']}).json()
    req = request(project_id=other['id'], note_id=note['id'], dialog='note')
    text = answer(setup, req)
    assert '真正归档项目' in text and '背景项目' not in text and '后端记录' in text


def test_scope_cannot_leak_private_names_cross_index_or_folder(setup):
    setup.user.role = 'admin'
    secret = project(setup, '不可泄露的目录', category='项目经验', confidentiality='secret', visibility='restricted')
    other = project(setup, '另一个项目', category='项目经验')
    folder = setup.client.post('/company-knowledge/projects/' + other['id'] + '/folders', json={'name': '私有子目录'}).json()
    setup.user.role = 'user'
    assert '不能确认' in answer(setup, request(project_id=secret['id'], folder_id=folder['id']))
    setup.user.username, setup.user.id = 'bob', 2
    text = answer(setup, request(project_id=secret['id']))
    assert '不可泄露' not in text and '不能确认' in text
    setup.user.is_active = False
    assert '不能确认' in answer(setup, request(project_id=other['id']))


def test_readonly_project_and_library_do_not_claim_note_write_access(setup):
    p = project(setup, '只读经验', category='项目经验')
    setup.user.username, setup.user.id = 'bob', 2
    text = answer(setup, request(project_id=p['id']))
    assert '不能在此' in text and '待整理' in text
    setup.user.username, setup.user.id = 'alice', 1
    lib = project(setup, '研究原件')
    assert '不能创建到资料库' in answer(setup, request(project_id=lib['id'], collection='library', mode='library'))


def test_current_note_help_and_save_failure_route_to_operating_instructions(setup):
    p = project(setup, 'test', category='项目经验')
    req = request(project_id=p['id'], dialog='note')
    req.message = '这个页面怎么用？'
    assert '正文纸面' in answer(setup, req)
    req.message = '笔记保存失败怎么办？'
    text = answer(setup, req)
    assert '重试保存' in text and '当前目录：' not in text


def test_version_reports_release_notes_without_model_or_secrets():
    text = answer_for_request(ResearchAssistantRequest(message='现在系统是什么版本，更新了什么？'))
    assert '2026.11.09.2' in text and '图文笔记' in text and '不跨库' in text
    assert '默认可用' in text and '仅能访问内部资料' in text
    assert '密钥' not in text
    assert '历史版本' in answer_for_request(ResearchAssistantRequest(message='怎么查看历史版本？'))


def test_stream_uses_verified_context_and_saves_answer_without_model(setup, monkeypatch):
    import research_api as api
    from models import User, AssistantState, AssistantThread, AssistantMessage
    for model in (AssistantState, AssistantThread, AssistantMessage): model.__table__.create(setup.db.kw['bind'])
    with setup.db() as db:
        db.add(User(id=1, username='alice', password_hash='test', role='user')); db.commit()
    setup.client.app.include_router(api.router)
    def db_session():
        with setup.db() as db: yield db
    setup.client.app.dependency_overrides[api.get_db] = db_session
    setup.client.app.dependency_overrides[api.get_current_user] = lambda: setup.user
    monkeypatch.setattr(api.research_workflow, '_get_assistant_model', lambda: pytest.fail('help needs no model'))
    p = project(setup, 'test', category='项目经验')
    req = request(project_id=p['id'])
    payload = req.model_dump(); payload['_guide_location'] = {'path':['forged']}
    response = setup.client.post('/research/assistant/stream', json=payload)
    assert response.status_code == 200
    assert 'test' in response.text and 'forged' not in response.text and '"saved": true' in response.text
    assert '"type": "sources"' not in response.text


@pytest.mark.parametrize('question,words', [
    ('上传图片后怎么继续写正文？', ['在图片下继续写正文', '说明框']),
    ('表格只有3乘3吗？', ['100行', '12列', '下方加行']),
    ('草稿会进入RAG吗？', ['发布笔记', '索引']),
    ('MD加图片导出会丢图片吗？', ['images/', '相对路径']),
    ('资料库和经验沉淀互通吗？', ['隔离', '不自动跨库']),
    ('如何返回上一级？', ['面包屑', '项目空间']),
])
def test_new_editor_and_workspace_topics_answer_offline(question, words):
    text = answer_for_request(ResearchAssistantRequest(message=question, current_page='company-knowledge'))
    for word in words:
        assert word in text
