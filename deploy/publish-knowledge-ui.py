"""Publish versioned knowledge UI resources without restarting the application.

The existing entrypoint is patched only after all immutable assets are in place.
Running research workers and already-open browser tabs keep their existing code.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime,timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request

ROOT=Path('/opt/supermew')


def digest(payload):return hashlib.sha256(payload).hexdigest()


def pid():
    value=int(subprocess.check_output(['systemctl','show','supermew','-p','MainPID','--value']).strip())
    if value<=0 or b'backend.app:app' not in Path(f'/proc/{value}/cmdline').read_bytes():
        raise RuntimeError('Expected the running research service')
    return value


def loaded_version():
    with urllib.request.urlopen('http://127.0.0.1:8010/version',timeout=10) as response:return json.load(response)


def backend_fingerprint(release):
    return {str(p.relative_to(release)):digest(p.read_bytes()) for p in sorted((release/'backend').rglob('*.py'))}


def atomic_write(path,payload,mode=0o644,owner=None):
    descriptor,name=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    temporary=Path(name)
    try:
        with os.fdopen(descriptor,'wb') as stream:
            stream.write(payload);stream.flush();os.fsync(stream.fileno())
        temporary.chmod(mode)
        if owner:os.chown(temporary,*owner)
        temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


def publish(package):
    if os.geteuid()!=0 or not (ROOT/'.deployment-owned').is_file():raise RuntimeError('Expected the managed deployment')
    package=package.resolve(strict=True)
    if ROOT/'staging' not in package.parents:raise RuntimeError('Expected a package in this deployment staging directory')
    manifest=json.loads((package/'knowledge-ui-manifest.json').read_text())
    if set(manifest['baseline'])!={'index.html','company-knowledge.js','company-knowledge-glass.css'}:
        raise RuntimeError('Incomplete frontend baseline')
    commit=manifest['commit']
    if not re.fullmatch('[0-9a-f]{40}',commit):raise RuntimeError('Expected a fixed Git commit')
    assets={}
    notes_only=manifest.get('kind')=='note-editor'
    assistant_only=manifest.get('kind')=='assistant-style'
    patterns={'optics':r'knowledge-glass-optics\.[0-9a-f]{12}\.js',
              'viewer':r'knowledge-document-viewer\.[0-9a-f]{12}\.js',
              'engine':r'vendor/knowledge-reader/knowledge-document-engine\.[0-9a-f]{12}\.js',
              'docx_license':r'vendor/knowledge-reader/docx-preview-LICENSE\.txt',
              'zip_license':r'vendor/knowledge-reader/jszip-LICENSE\.txt',
              'provenance':r'vendor/knowledge-reader/provenance\.json',
              'component':r'company-knowledge\.[0-9a-f]{12}\.js',
              'style':r'company-knowledge-glass\.[0-9a-f]{12}\.css'}
    if notes_only:
        patterns={'note_editor':r'knowledge-note-editor\.[0-9a-f]{12}\.js',
                  'note_style':r'knowledge-note-editor\.[0-9a-f]{12}\.css'}
    if assistant_only:
        patterns={'assistant_style':r'assistant\.[0-9a-f]{12}\.css'}
    for row in manifest['assets']:
        role=row['role'];name=row['path']
        if role not in patterns or not re.fullmatch(patterns[role],name):raise RuntimeError('Unapproved UI asset')
        path=package/name
        if path.is_symlink() or not path.resolve().is_relative_to(package):raise RuntimeError('Package assets must be regular files')
        payload=path.read_bytes()
        if digest(payload)!=row['sha256']:raise RuntimeError('Asset checksum mismatch')
        if role in {'optics','viewer','engine','component','style','note_editor','note_style','assistant_style'} and row['sha256'][:12] not in name:raise RuntimeError('Asset filename checksum mismatch')
        if role in assets:raise RuntimeError('Duplicate asset role')
        assets[role]=(name,payload)
    if set(assets)!=set(patterns):raise RuntimeError('Incomplete UI package')
    with ExitStack() as stack:
        for name in ('staging/.deployment.lock','.frontend-deploy.lock'):
            lock=stack.enter_context((ROOT/name).open('a'));fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        process=pid();version=loaded_version()
        current=(ROOT/'current').resolve(strict=True)
        running=Path(f'/proc/{process}/cwd').resolve(strict=True)
        targets=list(dict.fromkeys([current,running]))
        snapshots={};prepared={};fingerprints={}
        for release in targets:
            if release.parent!=ROOT/'releases':raise RuntimeError('Unexpected application directory')
            frontend=release/'frontend'
            if frontend.is_symlink():raise RuntimeError('Expected a release-owned frontend directory')
            for name,checksum in manifest['baseline'].items():
                if name not in {'index.html','company-knowledge.js','company-knowledge-glass.css'}:raise RuntimeError('Unapproved baseline file')
                if digest((frontend/name).read_bytes())!=checksum:raise RuntimeError('Frontend changed during review: '+name)
            index=frontend/'index.html';original=index.read_bytes();html=original.decode('utf-8')
            if assistant_only:
                html,count=re.subn(r'(href=")assistant(?:\.[0-9a-f]{12})?\.css(")',lambda m:m[1]+assets['assistant_style'][0]+m[2],html)
                if count!=1:raise RuntimeError('Expected one assistant stylesheet')
            elif notes_only:
                for role,attribute,extension in [('note_editor','src','js'),('note_style','href','css')]:
                    pattern=r'('+attribute+r'=")knowledge-note-editor(?:\.[0-9a-f]{12})?\.'+extension+r'(")'
                    html,count=re.subn(pattern,lambda m:m[1]+assets[role][0]+m[2],html)
                    if count!=1:raise RuntimeError('Expected one note editor '+extension+' entry')
            else:
                for role,stem in [('component','company-knowledge'),('optics','knowledge-glass-optics'),('viewer','knowledge-document-viewer')]:
                    pattern=r'(<script\b[^>]*\bsrc=")'+stem+r'(?:\.[0-9a-f]{12})?\.js("[^>]*></script>)'
                    html,count=re.subn(pattern,lambda m:m[1]+assets[role][0]+m[2],html)
                    if count==0 and role!='component':
                        marker='<script defer src="'+assets['component'][0]+'"></script>'
                        if html.count(marker)!=1:raise RuntimeError('Expected the knowledge entrypoint')
                        html=html.replace(marker,'<script defer src="'+assets[role][0]+'"></script>\n'+marker)
                    elif count!=1:raise RuntimeError('Expected one '+role+' script')
                html,count=re.subn(r'(href=")company-knowledge-glass(?:\.[0-9a-f]{12})?\.css(")',lambda m:m[1]+assets['style'][0]+m[2],html)
                if count!=1:raise RuntimeError('Expected one knowledge glass stylesheet')
            snapshots[release]=original;prepared[release]=html.encode('utf-8');fingerprints[release]=backend_fingerprint(release)
        os.umask(0o077)
        backup=ROOT/'backups'/('knowledge-ui-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+commit[:12])
        backup.mkdir(mode=0o700)
        for number,release in enumerate(targets):(backup/(str(number)+'-index.html')).write_bytes(snapshots[release])
        changed=[]
        try:
            for release in targets:
                frontend=release/'frontend'
                for name,payload in assets.values():
                    destination=frontend/name
                    folder=frontend
                    for part in Path(name).parts[:-1]:
                        folder=folder/part
                        if folder.is_symlink():raise RuntimeError('Unexpected asset directory')
                        if not folder.exists():folder.mkdir(mode=0o755);folder.chmod(0o755)
                        if not folder.is_dir():raise RuntimeError('Expected an asset directory')
                    if not destination.parent.resolve().is_relative_to(frontend.resolve()) or destination.is_symlink():raise RuntimeError('Unexpected asset destination')
                    if destination.exists():
                        if destination.read_bytes()!=payload:raise RuntimeError('Existing immutable asset differs')
                    else:atomic_write(destination,payload)
            if pid()!=process or (ROOT/'current').resolve()!=current:raise RuntimeError('Another deployment changed the application')
            for release in targets:
                index=release/'frontend/index.html';stat=index.stat()
                atomic_write(index,prepared[release],stat.st_mode&0o777,(stat.st_uid,stat.st_gid));changed.append(release)
            with urllib.request.urlopen('http://127.0.0.1:8010/',timeout=10) as response:served=response.read()
            served_roles=('assistant_style',) if assistant_only else ('note_editor','note_style') if notes_only else ('component','optics','viewer','style')
            if not all(assets[role][0].encode() in served for role in served_roles):raise RuntimeError('Running service did not load the UI entrypoint')
            for name,payload in assets.values():
                with urllib.request.urlopen('http://127.0.0.1:8010/'+name,timeout=10) as response:
                    if digest(response.read())!=digest(payload):raise RuntimeError('Published asset differs: '+name)
            if pid()!=process or loaded_version()!=version:raise RuntimeError('Application instance changed during UI publication')
            if any(backend_fingerprint(release)!=fingerprints[release] for release in targets):raise RuntimeError('Backend source changed during UI publication')
            receipt={'status':'published','frontend_commit':commit,'time_utc':datetime.now(timezone.utc).isoformat(),
                'backend_pid_unchanged':process,'backend_instance_unchanged':version['instance_id'],'backend_source_unchanged':True,
                'application_restart':False,'targets':[str(p) for p in targets],'backup':str(backup),'assets':manifest['assets'],
                'indexes':{str(p):digest(prepared[p]) for p in targets}}
            (backup/'receipt.json').write_text(json.dumps(receipt,indent=2))
            atomic_write(ROOT/('knowledge-ui-receipt-'+commit[:12]+'.json'),json.dumps(receipt,indent=2).encode(),0o600)
            print(json.dumps(receipt),flush=True)
        except BaseException:
            for release in reversed(changed):
                index=release/'frontend/index.html';stat=index.stat()
                atomic_write(index,snapshots[release],stat.st_mode&0o777,(stat.st_uid,stat.st_gid))
            raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True)
    parser.add_argument('--run',action='store_true',required=True)
    args=parser.parse_args();publish(args.package)
