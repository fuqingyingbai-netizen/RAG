"""Give the workspace entrypoints immutable names while retaining existing assets."""
import hashlib
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def build():
    frontend = ROOT / 'frontend'
    index = frontend / 'index.html'
    html = index.read_text(encoding='utf-8')
    files = []
    for name in ('project-workspace.js', 'project-workspace.css', 'script.js'):
        source = frontend / name
        payload = source.read_text(encoding='utf-8').encode('utf-8')
        checksum = hashlib.sha256(payload).hexdigest()
        filename = source.stem + '.' + checksum[:12] + source.suffix
        destination = frontend / filename
        if destination.exists() and destination.read_bytes() != payload:
            raise RuntimeError('Immutable asset collision')
        destination.write_bytes(payload)
        pattern = r'((?:src|href)=")' + re.escape(source.stem) + r'(?:\.[a-f0-9]{12})?' + re.escape(source.suffix) + r'(")'
        html, count = re.subn(pattern, lambda m: m[1] + filename + m[2], html)
        if count != 1:
            raise RuntimeError('Expected one workspace entry for ' + name)
        files.append(filename)
    index.write_text(html, encoding='utf-8', newline='\n')
    print(', '.join(files))


if __name__ == '__main__':
    build()
