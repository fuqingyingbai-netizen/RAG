"""Consistent local backup of this deployment; root-only, idle workloads only."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tarfile

ROOT = Path('/opt/supermew')
ACTIVE = ('planning','searching','source_assessing','cleaning','risk_assessing',
          'report_generating','proposal_generating','pausing')


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, timeout=300, **kwargs)
    if result.returncode:
        raise RuntimeError('Backup command failed: ' + args[0])
    return result.stdout


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def backup(retain=7):
    import fcntl
    if os.geteuid() != 0 or not (ROOT/'.deployment-owned').is_file():
        raise RuntimeError('Expected root and this deployment ownership marker')
    os.umask(0o077)
    parent = ROOT/'backups';parent.mkdir(mode=0o700, exist_ok=True);parent.chmod(0o700)
    with (parent/'.backup.lock').open('a') as lock:
        try:fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:return {'status':'skipped_existing_backup'}
        if subprocess.run(['systemctl','is-active','--quiet','supermew']).returncode:
            return {'status':'skipped_application_inactive'}
        states = ','.join("'"+state+"'" for state in ACTIVE)
        count = run(['runuser','-u','postgres','--','psql','-d','supermew','-At','-c',
                     'SELECT count(*) FROM research_projects WHERE status IN ('+states+')']).strip()
        if int(count):return {'status':'skipped_busy'}
        folder = parent/datetime.now(timezone.utc).strftime('backup-%Y%m%dT%H%M%SZ')
        folder.mkdir(mode=0o700)
        app_was_active = vector_was_active = False
        try:
            # Remember intent before issuing stop, so failure still restores the service.
            app_was_active = True
            run(['systemctl','stop','supermew'])
            state = run(['docker','inspect','--format','{{.State.Running}}','supermew-milvus']).strip()
            vector_was_active = state == b'true'
            if vector_was_active:run(['docker','stop','-t','30','supermew-milvus'])
            with (folder/'database.dump').open('xb') as output:
                result = subprocess.run(['runuser','-u','postgres','--','pg_dump','-d','supermew','-Fc'],
                                        stdout=output,stderr=subprocess.PIPE,timeout=300)
                if result.returncode:raise RuntimeError('Database dump failed')
            run(['pg_restore','--list',str(folder/'database.dump')])
            for name in ['data','milvus']:
                with tarfile.open(folder/(name+'.tar.gz'),'w:gz') as archive:
                    archive.add(ROOT/'shared'/name,arcname=name)
            shutil.copyfile('/etc/supermew/app.env',folder/'app.env')
            shutil.copyfile(ROOT/'current'/'release-manifest.json',folder/'release-manifest.json')
            manifest = json.loads((folder/'release-manifest.json').read_text())
            result = {'status':'completed','commit':manifest['commit'],'directory':str(folder),
                      'database_archive_listed':True,
                      'checksums':{p.name:digest(p) for p in folder.iterdir() if p.is_file()}}
            (folder/'verification.json').write_text(json.dumps(result,indent=2))
            (folder/'COMPLETE').touch(mode=0o600)
            old = sorted(p for p in parent.iterdir() if p.is_dir() and not p.is_symlink()
                         and re.fullmatch(r'backup-\d{8}T\d{6}Z',p.name) and (p/'COMPLETE').is_file())
            for obsolete in old[:-retain]:
                if obsolete.resolve().parent != parent.resolve():raise RuntimeError('Invalid retention target')
                shutil.rmtree(obsolete)
            return result
        finally:
            # Handle both failures and service-manager termination without leaving the site stopped.
            try:
                if vector_was_active:run(['docker','start','supermew-milvus'])
            finally:
                if app_was_active:run(['systemctl','start','supermew'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true',required=True)
    parser.add_argument('--retain',type=int,default=7)
    args=parser.parse_args()
    if not 1<=args.retain<=90:parser.error('retain must be between 1 and 90')
    def interrupted(signum,frame):raise InterruptedError('Backup interrupted')
    signal.signal(signal.SIGTERM,interrupted)
    print(json.dumps(backup(args.retain),indent=2))


if __name__=='__main__':main()
