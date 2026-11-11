import io,json,sqlite3,time
from pathlib import Path
import httpx
from docx import Document
root=Path(__file__).parent
con=sqlite3.connect(root/'ui-data/audit.sqlite');con.row_factory=sqlite3.Row
note=con.execute("SELECT id,current_document_id FROM company_notes WHERE title='TS-UPDATE-NOTE'").fetchone()
assert note
result={}
with httpx.Client(base_url='http://127.0.0.1:8903/company-knowledge',headers={'Authorization':'Bearer audit-bob'},timeout=30,trust_env=False) as c:
    view=c.get('/notes/'+note['id']);view.raise_for_status()
    assert view.json()['can_manage'] is False
    assert 'PUBLIC-UPDATE-PARAGRAPH' in json.dumps(view.json()['content'])
    body=c.get('/documents/'+note['current_document_id']+'/download');body.raise_for_status()
    doc=Document(io.BytesIO(body.content));assert 'PUBLIC-UPDATE-PARAGRAPH' in ' '.join(p.text for p in doc.paragraphs)
    result['published_json_and_docx_member_read']='passed'
    start=time.monotonic()
    try:
        page=c.get('/documents/'+note['current_document_id']+'/page?page=1')
        result['page_status']=page.status_code
        if page.status_code==200:
            assert page.headers.get('Content-Type','').startswith('image/png')
            (root/'note-member-page.png').write_bytes(page.content)
            result['page_preview']='passed'
        else:result['page_error']=page.text[:600]
    except Exception as exc:result['page_error']=type(exc).__name__+': '+str(exc)
    result['page_seconds']=round(time.monotonic()-start,2)
(root/'note-member-evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
