"""Publish immutable entry assets without replacing resources held by already-open tabs."""
import hashlib
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def build():
    frontend = ROOT / 'frontend'
    index = frontend / 'index.html'
    html = index.read_text(encoding='utf-8')
    files = []
    for name in ('knowledge-points.js', 'knowledge-points.css', 'company-knowledge.js',
                 'account-management.js', 'personal-home.js', 'script.js'):
        source = frontend / name
        content = source.read_text(encoding='utf-8').encode('utf-8')
        digest = hashlib.sha256(content).hexdigest()[:12]
        target = source.stem + '.' + digest + source.suffix
        destination = frontend / target
        if destination.exists() and destination.read_bytes() != content:
            raise RuntimeError('Immutable asset name collision')
        destination.write_bytes(content)
        pattern = re.escape(source.stem) + r'(?:\.[a-f0-9]{12})?' + re.escape(source.suffix)
        html, count = re.subn(r'((?:src|href)=")' + pattern + r'(")', lambda match: match[1] + target + match[2], html)
        if count != 1:
            raise RuntimeError('Expected one entry for ' + name)
        files.append(target)
    index.write_text(html, encoding='utf-8', newline='\n')
    print('Points assets: ' + ', '.join(files))


if __name__ == '__main__':
    build()
