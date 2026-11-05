"""Publish content-addressed app assets referenced by the static entry page."""
from pathlib import Path
import hashlib
import re

ROOT=Path(__file__).resolve().parents[1]/'frontend'
page=ROOT/'index.html'
html=page.read_text(encoding='utf-8')
for name in ('script.js','company-chapters.css'):
    payload=(ROOT/name).read_bytes()
    path=Path(name)
    target=f'{path.stem}.{hashlib.sha256(payload).hexdigest()[:12]}{path.suffix}'
    (ROOT/target).write_bytes(payload)
    pattern=rf'(?<=["\']){re.escape(path.stem)}(?:\.[a-f0-9]{{12}})?{re.escape(path.suffix)}(?=["\'])'
    html,count=re.subn(pattern,target,html)
    if count!=1:raise ValueError(f'Expected one asset reference: {name}, got {count}')
page.write_text(html,encoding='utf-8')
print('Updated static app asset references')
