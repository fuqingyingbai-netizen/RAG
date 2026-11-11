from pathlib import Path
import json,hashlib
from docx import Document
from openpyxl import load_workbook
from PIL import Image
root=Path(__file__).parent;report=[]
for format in ('docx','xlsx','png'):
 p=root/'exports'/('browser-answer.'+format)
 if format=='docx':
  doc=Document(p);text=' '.join(x.text for x in doc.paragraphs)+' '.join(c.text for t in doc.tables for row in t.rows for c in row.cells);assert all(x in text for x in ('甲项目','120','80'))
 elif format=='xlsx':
  book=load_workbook(p);text=' '.join(str(c.value) for sheet in book for row in sheet for c in row);assert all(x in text for x in ('甲项目','120','80'))
 else:
  image=Image.open(p);image.verify()
 report.append({'format':format,'status':'passed','bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
(root/'browser-download-verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
