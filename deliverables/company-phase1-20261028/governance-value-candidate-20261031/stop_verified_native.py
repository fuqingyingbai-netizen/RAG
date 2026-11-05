"""Stop only the pinned native run after candidate tests and durable recovery."""
from pathlib import Path
from datetime import datetime,timezone
from types import SimpleNamespace
import argparse,hashlib,json,re,sqlite3,sys
import xml.etree.ElementTree as ET
import psutil

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
NATIVE=ROOT/'work/company-phase1-20261028/native/haitian'
parser=argparse.ArgumentParser();parser.add_argument('--stop-owned-native',action='store_true');args=parser.parse_args()
assert Path.cwd().resolve()==ROOT


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


full=ET.parse(HERE/'full.xml').getroot();suites=list(full.iter('testsuite'))
counts={k:sum(int(s.get(k,'0')) for s in suites) for k in ['tests','failures','errors','skipped']}
assert counts=={'tests':4792,'failures':0,'errors':0,'skipped':4},counts
assert sum(c.get('classname','').endswith('test_governance_values') for c in full.iter('testcase'))==34
metadata=json.loads((HERE/'candidate.json').read_text(encoding='utf-8'))
assert sha(HERE/'company_governance.py')==metadata['candidate_utf8_sha256']
assert sha(ROOT/'backend/report_agents/company_governance.py')==metadata['base_utf8_sha256']
plan_path=NATIVE/'bounded-plan-20261030T145059173514.json'
assert sorted(NATIVE.glob('bounded-plan-*.json'))[-1]==plan_path
plan=json.loads(plan_path.read_text(encoding='utf-8'))
assert all(sha(ROOT/name)==digest for name,digest in plan['code_sha256'].items())
backup_proof_path=NATIVE/'pre-governance-values-backup-20261030T163917822583.json'
backup_proof=json.loads(backup_proof_path.read_text(encoding='utf-8'))
assert backup_proof['backup_quick_check']=='ok' and backup_proof['native_plan_sha256']==sha(plan_path)
backup=(ROOT/backup_proof['online_backup']).resolve()
assert backup.is_relative_to(NATIVE) and sha(backup)==backup_proof['online_backup_sha256']
sys.path.insert(0,str(ROOT/'backend'))
from report_agents.company_checkpoint import source_fingerprint


def fingerprint_database(path):
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
        db.row_factory=sqlite3.Row;sources=[]
        for row in db.execute('SELECT * FROM research_sources WHERE project_id=1 ORDER BY id'):
            values=dict(row)
            if isinstance(values.get('source_metadata'),str):values['source_metadata']=json.loads(values['source_metadata'])
            sources.append(SimpleNamespace(**values))
    assert len(sources)==1246
    return source_fingerprint(sources)


backup_fingerprint=fingerprint_database(backup)
owned=[]
for item in backup_proof['owned_processes_observed_before_backup']:
    proc=psutil.Process(item['pid'])
    assert abs(proc.create_time()-item['created_at'])<.01
    assert Path(proc.cwd()).resolve()==ROOT and 'company_phase1_native.py haitian' in ' '.join(proc.cmdline())
    owned.append(proc)
if not args.stop_owned_native:
    print(json.dumps({'candidate_counts':counts,'backup_verified':True,'owned_native_processes_live':[p.pid for p in owned],'stopped':False}));raise SystemExit(0)

stopped=False;suspended=[]
try:
    # Freeze this owned writer briefly; never kill during a partial index write.
    for proc in owned:proc.suspend();suspended.append(proc)
    folder=NATIVE/'objects/projects/1/company_generation_checkpoint'
    pointer=json.loads((folder/'current.json').read_text(encoding='utf-8'))
    checkpoint=folder/(pointer['sha256']+'.json');assert sha(checkpoint)==pointer['sha256']
    payload=json.loads(checkpoint.read_text(encoding='utf-8'))
    assert payload['source_fingerprint']==backup_fingerprint==fingerprint_database(NATIVE/'acceptance.sqlite')
    assert len(payload['packages']['company_information_usage_cache']['records'])==9374
    raw=(folder/'presentation-current.json').read_bytes();index=json.loads(raw)
    for key,digest in index['entries'].items():
        assert re.fullmatch(r'[a-f0-9]{64}',key) and re.fullmatch(r'[a-f0-9]{64}',digest)
        receipt=folder/'presentation'/(digest+'.json');assert sha(receipt)==digest
        batch=json.loads(receipt.read_text(encoding='utf-8'));assert batch['accepted'] is True and batch['input_sha256']==key
    snapshot=NATIVE/'governance-value-stop-presentation-index-20261031.json'
    assert not snapshot.exists();snapshot.write_bytes(raw)
    proof={'at':datetime.now(timezone.utc).isoformat(),'reason':'verified governance date equivalence and identifier field defects',
        'native_plan':plan_path.name,'runtime_code_unchanged':True,'verified_owned_processes':backup_proof['owned_processes_observed_before_backup'],
        'checkpoint':pointer,'checkpoint_sha_verified':True,'information_usage_records':9374,
        'source_fingerprint_matches_online_backup':True,'online_backup_proof':backup_proof_path.relative_to(ROOT).as_posix(),
        'online_backup_proof_sha256':sha(backup_proof_path),'presentation_index_snapshot':snapshot.relative_to(ROOT).as_posix(),
        'presentation_index_sha256':sha(snapshot),'native_candidate_entries':len(index['entries']),
        'candidate_test_counts':counts,'candidate_full_xml_sha256':sha(HERE/'full.xml'),
        'stop_helper_sha256':sha(Path(__file__)),'candidate_promoted':False,'full_report_accepted':False,
        'unfinished_model_calls_are_not_approved':True}
    for proc in owned:proc.kill()
    _,alive=psutil.wait_procs(owned,timeout=10);assert not alive
    assert (folder/'presentation-current.json').read_bytes()==raw
    proof['owned_native_processes_stopped']=True
    path=NATIVE/'governance-value-stop-proof-20261031.json';assert not path.exists()
    path.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    stopped=True
    print(json.dumps({'proof':str(path),'owned_native_processes_stopped':True,'native_candidate_entries':len(index['entries']),'candidate_promoted':False}))
finally:
    if not stopped:
        for proc in reversed(suspended):
            try:
                if proc.is_running():proc.resume()
            except psutil.NoSuchProcess:pass
