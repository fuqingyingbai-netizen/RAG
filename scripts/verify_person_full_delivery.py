"""Static fidelity, source, link and ZIP checks; no browser or model is used."""
import argparse,hashlib,json,os,re,sys,zipfile
from pathlib import Path
from urllib.parse import unquote,urlsplit
from bs4 import BeautifulSoup
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'scripts')]
from replay_person_chapters import generation_code_snapshot


def read(p):return json.loads(p.read_text(encoding='utf-8'))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('output',type=Path);ap.add_argument('--runs',nargs='+',required=True,type=Path)
    ap.add_argument('--archive',type=Path);ap.add_argument('--result',required=True,type=Path);args=ap.parse_args()
    out=args.output.resolve();cases=read(out/'metrics.json')['cases'];assert len(cases)==len(args.runs)
    checked=[]
    for case,run in zip(cases,args.runs):
        contract=read(run/'contract.json');summary=read(run/'summary.json');audit=read(run/'audit.json')
        assert audit['automatic_delivery_status']=='passed' and audit['delivery_gate']['blockers']==[]
        assert summary['code_unchanged_during_run'] and read(run/'generation-code-snapshot.json')==generation_code_snapshot()
        assert hashlib.sha256((Path(summary['baseline'])/'source-snapshots.json').read_bytes()).hexdigest()==summary['sources_sha256']==case['source_snapshot_sha256']
        folder=out/case['folder']
        for name in ['desktop_report.md','evidence-appendix.md','audit.json','acceptance-results.json']:
            assert (folder/name).read_bytes()==(run/name).read_bytes(),('File differs from actual run',case['folder'],name)
        annex=(folder/'evidence-appendix.md').read_text(encoding='utf-8')
        chunks=re.split(r'^## (E-[A-Z0-9-]+)\s*$',annex,flags=re.M)
        originals={chunks[i]:'\n'.join(line[2:] for line in chunks[i+1].splitlines() if line.startswith('> ')) for i in range(1,len(chunks),2)}
        assert len(originals)==len(contract['facts'])
        assert all(originals[f['evidence_id']]=='\n'.join(f['fact'].splitlines()) for f in contract['facts'])
        assert all(c['metrics']['analysis_chars']<=600 and c['metrics']['displayed_original_chars']<=1600 for c in case['chapters'])
        checked.append({'target':case['target_name'],'whole_report_gate':'passed','original_records_verified':len(originals)})
    secret_values={v for k,v in {**os.environ,**dotenv_values(ROOT/'.env')}.items() if isinstance(v,str) and len(v)>=12 and any(t in k.upper() for t in ['KEY','TOKEN','SECRET','PASSWORD'])}
    links=0;parsed={};files={p.relative_to(out).as_posix():p for p in out.rglob('*') if p.is_file()}
    for path in files.values():
        text=path.read_text(encoding='utf-8',errors='replace')
        assert not any(v in text for v in secret_values),('Secret value in file',path.name)
        if path.suffix=='.html':parsed[path.resolve()]=BeautifulSoup(text,'html.parser')
    for path,soup in parsed.items():
        assert soup.html and soup.html.get('lang')=='zh-CN' and soup.find('meta',attrs={'name':'viewport'})
        for node in soup.find_all(href=True):
            href=node['href'];url=urlsplit(href)
            if url.scheme in ['https','http']:
                assert url.hostname not in ['localhost','127.0.0.1'];continue
            assert not url.scheme and not href.startswith('/'),('Nonportable link',href)
            target=(path.parent/unquote(url.path)).resolve() if url.path else path
            assert target.is_relative_to(out) and target.is_file(),('Missing local target',href)
            if url.fragment:
                assert target in parsed and parsed[target].find(id=unquote(url.fragment)),('Missing local anchor',href)
            links+=1
        assert not soup.find_all(['img','script','link'],src=True),'Unexpected runtime resource'
    result={'reports':checked,'generation_code_matches':True,'source_snapshots_unchanged':True,
        'all_qualified_originals_verified':True,'case_files_match_actual_runs':True,'chapter_budgets_passed':True,
        'local_links_and_anchors_checked':links,'secret_value_matches':0,'browser_visual_qa':'not_performed'}
    if args.archive:
        with zipfile.ZipFile(args.archive) as z:
            assert z.testzip() is None and 'index.html' in z.namelist()
            assert set(z.namelist())==set(files)
            assert all(z.read(name)==path.read_bytes() for name,path in files.items())
        result.update(zip_crc='passed',zip_files_and_bytes_match=True,zip_sha256=hashlib.sha256(args.archive.read_bytes()).hexdigest())
    args.result.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
