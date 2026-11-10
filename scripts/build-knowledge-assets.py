"""Version the knowledge-only UI assets so existing tabs keep their original scripts."""
import hashlib
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def build():
    frontend=ROOT/'frontend'
    index=frontend/'index.html'
    html=index.read_text(encoding='utf-8')
    files=[]
    for name in ('knowledge-glass-optics.js','knowledge-document-viewer.js','knowledge-note-editor.js','knowledge-note-editor.css','company-knowledge.js','company-knowledge-glass.css','knowledge-workspace.css'):
        source=frontend/name
        # Git checks these files out with LF. Hash the same bytes on Windows too.
        payload=source.read_text(encoding='utf-8').encode('utf-8')
        checksum=hashlib.sha256(payload).hexdigest()
        filename=source.stem+'.'+checksum[:12]+source.suffix
        target=frontend/filename
        if target.exists() and target.read_bytes()!=payload:raise RuntimeError('Asset digest collision')
        target.write_bytes(payload)
        pattern=re.escape(source.stem)+r'(?:\.[a-f0-9]{12})?'+re.escape(source.suffix)
        html,count=re.subn(r'((?:src|href)=")'+pattern+r'(")',lambda m:m[1]+filename+m[2],html)
        if count!=1:raise RuntimeError('Expected one HTML entry for '+name)
        files.append(filename)
    index.write_text(html,encoding='utf-8',newline='\n')
    print('Knowledge assets: '+', '.join(files))


if __name__=='__main__':build()
