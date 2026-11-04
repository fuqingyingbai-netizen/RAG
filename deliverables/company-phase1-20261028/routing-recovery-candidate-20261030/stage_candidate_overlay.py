"""Apply the exact patch only in an ignored test overlay, outside live backend."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

here=Path(__file__).resolve().parent;root=here.parents[2]
overlay=root/'work/company-phase1-20261028/routing-candidate-overlay'
manifest=json.loads((here/'candidate-manifest.json').read_text(encoding='utf-8'))
assert not overlay.exists(), 'Retain each previous tested overlay; do not overwrite it.'
for path,metadata in manifest['paths'].items():
    source=root/path;target=overlay/path
    target.parent.mkdir(parents=True,exist_ok=True)
    if metadata['base_sha256'] is not None:
        assert hashlib.sha256(source.read_bytes()).hexdigest()==metadata['base_sha256']
        shutil.copyfile(source,target)
subprocess.run(['git','apply','--directory='+overlay.relative_to(root).as_posix(),
    str(here/'routing-recovery-candidate.patch')],cwd=root,check=True)
for path,metadata in manifest['paths'].items():
    assert hashlib.sha256((overlay/path).read_bytes()).hexdigest()==metadata['candidate_utf8_sha256']
print(json.dumps({'overlay_staged':True,'paths':len(manifest['paths']),'live_backend_modified':False}))
