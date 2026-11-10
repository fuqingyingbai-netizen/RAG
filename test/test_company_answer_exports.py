import io
import json
import pytest
from sqlalchemy import select
from test_company_memory import env, create
from company_catalog import CompanyDocument, CompanyAuditEvent
import company_memory as memory
import company_answer_exports as exports


ANSWER = '| 项目 | 收入（万元） | 来源 |\n|---|---|---|\n|甲项目|120|[id_1]|\n|乙项目|80|[id_1]|'
REFS = [{'id':'1','local_id':'doc-a','document_id':'cloud-a','title':'收入表','version':1,'pages':[2],
    'text':'2025年甲项目收入120万元，乙项目收入80万元。','evidence_id':'evidence-a'}]


def saved(env, answer=ANSWER, refs=None, status='completed'):
    CompanyAuditEvent.__table__.create(env.db.kw['bind'],checkfirst=True)
    sid = create(env)
    with env.db() as db:
        deps = memory.accessible(db, env.user, 'memory-index')
        msg=memory.KnowledgeChatMessage(thread_id=sid,request_id='export',role='assistant',content=answer,
            references=REFS if refs is None else refs,dependencies=deps,status=status)
        db.add(msg);db.commit();mid=msg.id
    return sid, mid


def download(env, sid, mid, fmt, **kwargs):
    return env.client.post(f'/company-knowledge/conversations/{sid}/messages/{mid}/export',json={'format':fmt,**kwargs})


def test_downloads_use_saved_answer_provenance_and_audit(env):
    from openpyxl import load_workbook
    from docx import Document
    from PIL import Image
    sid,mid=saved(env)
    for fmt in ('xlsx','docx','png'):
        response=download(env,sid,mid,fmt)
        assert response.status_code==200,response.text
        assert response.headers['cache-control']=='no-store'
        assert response.headers['x-watermark-trace']
        if fmt=='xlsx':
            wb=load_workbook(io.BytesIO(response.content));assert wb['整理结果']['B7'].value==120
            assert '甲项目' in wb['原文依据']['E2'].value
            assert wb['原文依据']['D2'].value=='2'
        elif fmt=='docx':
            doc=Document(io.BytesIO(response.content));assert len(doc.tables)==1
            assert '甲项目' in ' '.join(p.text for p in doc.paragraphs)
        else:
            image=Image.open(io.BytesIO(response.content));assert image.width==1400 and image.height>300
    with env.db() as db:
        events=list(db.scalars(select(CompanyAuditEvent).where(CompanyAuditEvent.action=='answer.export')))
        assert len(events)==3 and all(e.actor_username=='bob' and e.details['sha256'] for e in events)


def test_cross_account_incomplete_and_changed_source_are_rejected(env):
    sid,mid=saved(env)
    env.user.id=1;env.user.username='alice'
    assert download(env,sid,mid,'xlsx').status_code==404
    env.user.id=2;env.user.username='bob'
    with env.db() as db:
        db.get(CompanyDocument,'doc-a').version=2;db.commit()
    assert download(env,sid,mid,'xlsx').status_code==409
    sid,mid=saved(env,status='interrupted')
    assert download(env,sid,mid,'docx').status_code==409


def test_export_rechecks_revocation_after_build(env,monkeypatch):
    sid,mid=saved(env)
    original=exports.workbook
    def revoke(*args):
        payload=original(*args)
        with env.db() as db:
            db.get(CompanyDocument,'doc-a').readers=[];db.commit()
        return payload
    monkeypatch.setattr(exports,'workbook',revoke)
    assert download(env,sid,mid,'xlsx').status_code==409


@pytest.mark.parametrize('answer,fragment',[
    (ANSWER.replace('|80|','|81|'),'直接核对'),
    (ANSWER.replace('|80|','|80亿元|'),'同单位'),
    (ANSWER.replace('|120|','|120亿元|').replace('|80|','|80亿元|'),'单位不一致'),
    (ANSWER.replace('[id_1]','[id_999]'),'有效行引用'),
    ('没有表格','没有对应表格'),
    (ANSWER.replace('|乙项目|80|[id_1]|','|乙项目|80|'),'列数不一致'),
])
def test_chart_rejects_unverifiable_or_ambiguous_data(env,answer,fragment):
    sid,mid=saved(env,answer)
    response=download(env,sid,mid,'png')
    assert response.status_code==422 and fragment in response.json()['detail']


def test_formula_injection_is_exported_as_text_and_missing_stays_missing(env):
    from openpyxl import load_workbook
    sid,mid=saved(env,ANSWER.replace('甲项目','=HYPERLINK("https://example.invalid")').replace('|80|','|未披露|'))
    response=download(env,sid,mid,'xlsx');assert response.status_code==200
    wb=load_workbook(io.BytesIO(response.content))
    assert wb['整理结果']['A7'].data_type=='s'
    assert wb['整理结果']['B8'].value=='未披露'
    assert download(env,sid,mid,'png').status_code==200


def test_formats_columns_and_unknown_message_are_validated(env):
    sid,mid=saved(env)
    assert download(env,sid,mid,'exe').status_code==422
    assert download(env,sid,mid,'xlsx',table_index=31).status_code==422
    assert download(env,sid,mid+100,'docx').status_code==404
    assert download(env,sid,mid,'png',value_column=29).status_code==422


def test_legacy_answer_without_bound_source_version_cannot_be_exported(env):
    sid,mid=saved(env,refs=[{**REFS[0],'local_id':''}])
    assert download(env,sid,mid,'docx').status_code==409
