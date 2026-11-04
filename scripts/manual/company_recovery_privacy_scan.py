"""Scan deliverable bytes and staged/history blobs without printing secrets."""
import argparse,hashlib,json,re,subprocess
from pathlib import Path
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[2]
BASE='514f0327a6a14cd442860e1c4ecd23f74e38703c'
OUT=ROOT/'docs/deliverables/company-recovery-20261104/privacy-review.json'


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT)


def main():
    global OUT
    parser=argparse.ArgumentParser();parser.add_argument('--output',default=str(OUT))
    args=parser.parse_args();OUT=Path(args.output).resolve();assert OUT.is_relative_to(ROOT.resolve())
    OUT.parent.mkdir(parents=True,exist_ok=True)
    values={v.encode() for k,v in dotenv_values(ROOT/'.env').items()
            if any(s in k.upper() for s in ('KEY','TOKEN','SECRET','PASSWORD')) and v and len(v)>=12}
    pattern=re.compile(rb'(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}')
    checked={};hits=[];candidates=[]
    def scan(label,raw):
        digest=hashlib.sha256(raw).hexdigest();checked[label]=digest
        if any(value in raw for value in values):hits.append(label)
        if pattern.search(raw):candidates.append(label)
    paths=git('ls-files','--cached','--others','--exclude-standard','-z').decode().split('\0')
    for name in sorted(set(paths)-{''}):
        path=ROOT/name
        if path.is_file() and path.resolve()!=OUT:scan('worktree:'+name,path.read_bytes())
    forbidden=[p for p in git('diff','--cached','--name-only','-z').decode().split('\0')
               if p and (p=='.env' or p.startswith('work/') or p.endswith(('.sqlite','.sqlite3','.db')))]
    # Read the actual index bytes, rather than assuming staged == worktree.
    objects={}
    for line in git('ls-files','--stage').decode().splitlines():
        entry,name=line.split('\t',1);oid=entry.split()[1]
        objects.setdefault(oid,[]).append('index:'+name)
    history=git('rev-list','--objects',BASE+'..HEAD').decode().splitlines()
    for line in history:
        oid,_,name=line.partition(' ')
        objects.setdefault(oid,[]).append('history:'+oid+':'+name)
    payload=subprocess.check_output(['git','cat-file','--batch'],cwd=ROOT,
        input=('\n'.join(objects)+'\n').encode())
    cursor=0
    for oid,labels in objects.items():
        end=payload.index(b'\n',cursor);header=payload[cursor:end].split()
        length=int(header[2]);raw=payload[end+1:end+1+length];cursor=end+length+2
        if header[1]==b'blob':
            for label in labels:scan(label,raw)
    result={'scope':'Current tracked/unignored deliverables, actual index blobs, and merged history since baseline; secret values never emitted',
        'base_commit':BASE,'head':git('rev-parse','HEAD').decode().strip(),
        'checked_objects':len(checked),'known_local_credentials_checked':len(values),
        'known_local_credential_matches':hits,'bounded_token_pattern_candidates':candidates,
        'forbidden_staged_paths':forbidden,
        'env_is_gitignored':subprocess.run(['git','check-ignore','-q','.env'],cwd=ROOT).returncode==0}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    if hits or candidates or forbidden or not result['env_is_gitignored']:raise SystemExit(1)


if __name__=='__main__':main()
