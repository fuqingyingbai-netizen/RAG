"""Reconcile current collected tests against snapshots and targeted reruns."""
import hashlib,json,shutil
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
NAMES=['company-quality-full-initial','company-quality-company-current','company-quality-focused-final',
       'company-quality-policy-final','company-quality-regressions-final','company-quality-final-core',
       'company-quality-delivery-final','company-quality-last-cache','company-quality-summary-cache-final',
       'company-quality-targeted-final','company-quality-empty-optional-final','company-quality-shared-rules-final',
       'company-quality-stage-separation','company-quality-support-binding-final']


def main():
    out=ROOT/'docs/deliverables/company-quality-20261104';out.mkdir(parents=True,exist_ok=True)
    collected=ROOT/'work/runtime/quality-collected-final.txt';current=set()
    for line in collected.read_text(encoding='utf-8',errors='replace').splitlines():
        if line.startswith('test/') and '::' in line:
            path,*parts=line.split('::')
            current.add(path[:-3].replace('/','.')+('.'+'.'.join(parts[:-1]) if len(parts)>1 else '')+'::'+parts[-1])
    assert current and 'tests collected' in collected.read_text(encoding='utf-8',errors='replace')
    latest={};runs=[]
    for name in NAMES:
        path=ROOT/'work/runtime'/(name+'.xml');counts=Counter();tree=ET.parse(path)
        for test in tree.iter('testcase'):
            key=test.attrib['classname']+'::'+test.attrib['name']
            status=('failed' if test.find('failure') is not None or test.find('error') is not None else
                    'skipped' if test.find('skipped') is not None else 'passed')
            counts[status]+=1
            if key in current:latest[key]={'status':status,'run':name+'.xml'}
        shutil.copy2(path,out/path.name)
        runs.append({'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'counts':dict(counts),
                     'seconds':sum(float(s.attrib.get('time',0)) for s in tree.iter('testsuite'))})
    result={'scope':'Full-suite snapshot plus newer affected-module reruns, reconciled against final collection; not one fresh monolithic green run',
            'runs':runs,'current_collected':len(current),'effective_counts':dict(Counter(v['status'] for v in latest.values())),
            'unverified_current_tests':sorted(current-latest.keys()),
            'unresolved_test_failures':{k:v for k,v in latest.items() if v['status']=='failed'}}
    (out/'verification-summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result['unverified_current_tests'] or result['unresolved_test_failures']:raise SystemExit(1)


if __name__=='__main__':main()
