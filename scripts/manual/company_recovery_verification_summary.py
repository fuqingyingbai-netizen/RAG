"""Summarize recorded pytest runs; keep failures and rerun provenance explicit."""
from pathlib import Path
from collections import Counter
import hashlib,json
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/deliverables/company-recovery-20261104'


def main():
    names=['regression-final.xml','company-research-final.xml','recovery-final.xml',
           'platform-final.xml','reading-format-final.xml','format-html-final.xml','attribution-final.xml']
    latest={};runs=[];original_failures=[]
    for name in names:
        path=OUT/name;root=ET.parse(path).getroot();counts=Counter()
        for case in root.iter('testcase'):
            key=case.get('classname','')+'::'+case.get('name','')
            status='failed' if case.find('failure') is not None else 'error' if case.find('error') is not None else 'skipped' if case.find('skipped') is not None else 'passed'
            counts[status]+=1;latest[key]={'status':status,'source':name}
            if name==names[0] and status in {'failed','error'}:original_failures.append(key)
        suites=list(root.iter('testsuite'))
        runs.append({'file':name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'counts':dict(counts),'seconds':sum(float(s.get('time',0)) for s in suites),
            'started_at':[s.get('timestamp') for s in suites]})
    result={'scope':'A full-suite snapshot followed by newer company and recovery reruns; not one fresh monolithic full-suite pass',
        'runs':runs,'latest_observed_unique_test_verdicts':dict(Counter(v['status'] for v in latest.values())),
        'original_failures_with_latest_verdict':[{'test':key,**latest[key]} for key in original_failures],
        'remaining_observed_failures':[{'test':k,**v} for k,v in latest.items() if v['status'] in {'failed','error'}],
        'frontend':{'files':len(json.loads((OUT/'frontend-tests.json').read_text(encoding='utf-8'))),
            'failed_files':[r['file'] for r in json.loads((OUT/'frontend-tests.json').read_text(encoding='utf-8')) if r['exit_code']]}}
    (OUT/'verification-summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('latest_observed_unique_test_verdicts','remaining_observed_failures','frontend')}))


if __name__=='__main__':main()
