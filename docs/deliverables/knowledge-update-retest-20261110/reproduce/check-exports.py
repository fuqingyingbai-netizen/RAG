import concurrent.futures,io,json,sqlite3,time
from pathlib import Path
import httpx
from docx import Document
from openpyxl import load_workbook
from PIL import Image

root=Path(__file__).parent
con=sqlite3.connect(root/'ui-data/audit.sqlite')
con.row_factory=sqlite3.Row
message=con.execute("SELECT id,thread_id,content FROM company_chat_messages WHERE role='assistant' AND content LIKE '%甲项目%' AND status='completed' ORDER BY id DESC LIMIT 1").fetchone()
assert message is not None,'Synthetic UI answer not saved'
out=root/'exports';out.mkdir(exist_ok=True)
def export(fmt):
    started=time.monotonic()
    try:
        response=httpx.post(f"http://127.0.0.1:8903/company-knowledge/conversations/{message['thread_id']}/messages/{message['id']}/export",headers={'Authorization':'Bearer audit-alice'},json={'format':fmt},timeout=25,trust_env=False)
        result={'format':fmt,'status':response.status_code,'seconds':round(time.monotonic()-started,2),'bytes':len(response.content)}
        if response.status_code!=200:result['error']=response.text[:400];return result
        (out/('answer.'+fmt)).write_bytes(response.content)
        assert response.headers.get('X-Watermark-Trace') and response.headers.get('Cache-Control')=='no-store'
        if fmt=='xlsx':
            wb=load_workbook(io.BytesIO(response.content));texts=' '.join(str(c.value) for sheet in wb for row in sheet for c in row)
            assert '甲项目' in texts and '120' in texts and '80' in texts
        elif fmt=='docx':
            doc=Document(io.BytesIO(response.content));texts=' '.join(p.text for p in doc.paragraphs)+' '.join(c.text for t in doc.tables for row in t.rows for c in row.cells)
            assert '甲项目' in texts and '120' in texts
        else:
            image=Image.open(io.BytesIO(response.content));assert image.width>0 and image.height>0
            result['image_size']=[image.width,image.height]
        result['validated']=True
        return result
    except Exception as exc:return {'format':fmt,'seconds':round(time.monotonic()-started,2),'error':type(exc).__name__+': '+str(exc)}
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(export,['docx','xlsx','png']))
(root/'export-api-evidence.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False,indent=2))
