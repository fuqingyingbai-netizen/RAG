"""Refresh local phase-one evidence without model calls or acceptance mutation."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,re,shutil,subprocess,xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'work/company-phase1-20261028'
OUT=ROOT/'deliverables/company-phase1-20261028'
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def write(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()

def main():
    head=git('rev-parse','HEAD');tested='c881cfe163f2f0d81b508469a4a80cc07101e96f'
    linux_base='66bd061582d1066a8b9f8ef91af356c25c315f04'
    unchanged=subprocess.run(['git','diff','--quiet',tested,'--','backend','test','frontend'],cwd=ROOT).returncode==0
    assert not git('ls-files','--others','--exclude-standard','--','backend','test','frontend'), 'Untracked runtime or tests need separate verification'
    assert unchanged,'Current runtime or tests differ from the retained full regression'
    shared='cb9f7bfd640e425ed6617fe4d83b9435d24e5bad'
    assert subprocess.run(['git','merge-base','--is-ancestor',shared,head],cwd=ROOT).returncode==0
    pins=[]
    for row in read(OUT/'upstream-source-index.json'):
        repository=row['repository'].removeprefix('https://github.com/')
        folder=RUN/'upstream'/repository.replace('/','--')
        verified=[]
        for kind,records in [('license',row.get('license_files',[])),('selected',row.get('selected_files',[]))]:
            for item in records:
                base=folder/'selected' if kind=='selected' else folder
                path=(base/item['path']).resolve()
                assert path.is_relative_to(folder.resolve()) and path.is_file(),str(path)
                assert sha(path)==item['sha256'],repository+':'+item['path']
                verified.append({'kind':kind,'path':item['path'],'sha256':item['sha256']})
        pins.append({'repository':row['repository'],'commit':row['commit'],'verified_files':verified})
    suites=ET.parse(OUT/'test-results/routing-recovery-full-20261030.xml').getroot().findall('testsuite')
    assert all(s.get('failures')=='0' and s.get('errors')=='0' for s in suites)
    candidate_proof=read(OUT/'routing-recovery-full-regression-proof.json')
    for name,expected in candidate_proof['evidence_sha256'].items():assert sha(ROOT/name)==expected
    for name,item in candidate_proof['exact_candidate_paths'].items():
        assert sha(ROOT/name)==item['candidate_utf8_sha256']
    release_proof=read(ROOT/'docs/UNIFIED_SERVER_SYNC_20261030.json')
    assert release_proof['deployed_code_commit']==linux_base
    for name in ['pytest.log','pytest.xml']:
        assert sha(ROOT/'work/server-update-20261030'/name)==release_proof['evidence_sha256'][name]
    frontend_text=(RUN/'frontend-regression-60d7aca.log').read_text(encoding='utf-8')
    frontend_text=re.sub(r'\x1b\[[0-9;]*m','',frontend_text)
    frontend={k:int(v) for k,v in re.findall(r'(?m)^(?:#\s*|ℹ\s*)?(tests|pass|fail|skipped)\s+(\d+)',frontend_text)}
    assert frontend.get('pass')==frontend.get('tests') and frontend.get('fail')==frontend.get('skipped')==0
    frontend_tested='60d7aca0fbdf7f17ad85f5c8fdeb3d95c6de6dc3'
    assert not git('diff','--name-only',frontend_tested,'--','frontend','test/*.cjs')
    evidence={}
    for source in [ROOT/'work/server-update-20261030/pytest.log',ROOT/'work/server-update-20261030/pytest.xml',
                   RUN/'frontend-regression-60d7aca.log',OUT/'test-results/routing-recovery-full-20261030.log',
                   OUT/'test-results/routing-recovery-full-20261030.xml']:
        name=('full-regression-66bd061-linux'+source.suffix) if source.name.startswith('pytest.') else source.name
        destination=OUT/'test-results'/name
        if destination.exists():assert sha(destination)==sha(source),'Immutable regression evidence differs'
        else:shutil.copyfile(source,destination)
        evidence[destination.relative_to(OUT).as_posix()]={'sha256':sha(destination),'bytes':destination.stat().st_size}
    cases=[]
    for case in ['haitian','kingsoft','holdout']:
        directory=RUN/'native'/case
        plans=sorted(directory.glob('bounded-plan-*.json'))
        latest=plans[-1] if plans else None
        result=latest.with_name(latest.name.replace('bounded-plan-','bounded-result-')) if latest else None
        acceptance=read(directory/'acceptance.json') if (directory/'acceptance.json').exists() else {}
        cases.append({'case':case,'latest_plan':latest.name if latest else None,
            'latest_round_has_end_record':bool(result and result.exists()),
            'persisted_acceptance_status':acceptance.get('status','not_started'),
            'final_report_acceptance_proven':False,
            'note':'A persisted stage or a prior report is not proof of a live worker or final acceptance.'})
    baseline=RUN/'resume-state-20261030.json'
    summary={'at':datetime.now(timezone.utc).isoformat(),'current_code_commit':head,'tested_code_commit':tested,
        'runtime_tests_frontend_unchanged_from_full_regression':unchanged,
        'shared_search_patch_ancestor':shared,'upstream_pinned_files_reverified':pins,
        'baseline_readonly_audit_sha256':sha(baseline),'cases':cases,
        'regression':{'passed':sum(int(s.get('tests','0'))-int(s.get('skipped','0')) for s in suites),
                      'failures':0,'errors':0,'skipped':sum(int(s.get('skipped','0')) for s in suites),
                      'platform':'Windows Python 3.12.14','frontend_passed':frontend['pass'],'evidence':evidence,
                      'skipped_tests':candidate_proof['skipped_tests']},
        'unfinished_requirements':['source-to-implementation mapping with final case and regression evidence for adopted designs',
            'both development reports through the real workflow',
            'untuned holdout through fresh real collection on frozen development code',
            'same-report machine audit and all fourteen chapters reviewed',
            'Markdown HTML Word evidence ZIP hash binding for each case',
            'browser inspection and every final Word page visually inspected',
            'final reproducibility package and requirement-by-requirement completion audit'],
        'goal_achieved':False,'model_calls_by_this_audit':0,'business_data_mutated':False}
    write(OUT/'resume-audit-20261030.json',summary)
    # Preserve the immutable Git record instead of rewriting the old test counts.
    write(OUT/'current-regression-proof.json',{
        'backend_product_commit':tested,'checked_repository_commit':head,
        'backend_test_frontend_files_unchanged_since_test_commit':unchanged,
        'backend':{**summary['regression'],'scope':'full automated regression; not real-report acceptance'},
        'historical_linux_base':{'product_commit':linux_base,'passed':4724,'skipped':0,
            'scope':'base product before the routing candidate; not a Linux full run of the candidate'},
        'frontend':{'passed':frontend['pass'],'failures':0,'skipped':0,'tested_commit':frontend_tested,
                    'current_frontend_sources_unchanged_since_test':True,
                    'command':'bundled node --test test/*.cjs'},
        'historical_proof':{'commit':'60d7aca0fbdf7f17ad85f5c8fdeb3d95c6de6dc3',
            'path':'deliverables/company-phase1-20261028/current-regression-proof.json',
            'git_blob':git('rev-parse','60d7aca:deliverables/company-phase1-20261028/current-regression-proof.json')},
        'files':evidence,'real_report_acceptance':'pending for all three cases'})
    print(json.dumps({'source_repositories':len(pins),'verified_source_files':sum(len(p['verified_files']) for p in pins),
        'backend_passed':summary['regression']['passed'],'frontend_passed':frontend['pass'],'real_reports_accepted':0,
        'latest_rounds_have_end_record':{c['case']:c['latest_round_has_end_record'] for c in cases}},ensure_ascii=False))

if __name__=='__main__':main()
