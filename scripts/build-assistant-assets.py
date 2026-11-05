"""Version shared assistant/app assets while preserving files used by open tabs."""
import hashlib
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1] / 'frontend'


def build():
    index = ROOT / 'index.html'
    html = index.read_text(encoding='utf-8')
    for name in ('script.js', 'assistant.css'):
        source = ROOT / name
        payload = source.read_text(encoding='utf-8-sig').encode('utf-8')
        target = source.stem + '.' + hashlib.sha256(payload).hexdigest()[:12] + source.suffix
        (ROOT / target).write_bytes(payload)
        pattern = r'((?:src|href)=")' + re.escape(source.stem) + r'(?:\.[a-f0-9]{12})?' + re.escape(source.suffix) + r'(")'
        html, count = re.subn(pattern, lambda m: m[1] + target + m[2], html)
        if count != 1:
            raise ValueError('Expected one static entry: ' + name)
    index.write_text(html, encoding='utf-8', newline='\n')
    print('Updated assistant/app asset references')


if __name__ == '__main__': build()
