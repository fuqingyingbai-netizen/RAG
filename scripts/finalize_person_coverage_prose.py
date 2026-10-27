"""Apply a recorded, source-bound editorial narrowing after report generation."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend')]
from person_evidence import split_sections, cited_ids, validate_model_claims, report_audit


def persist_review(run,result,record):
    contract=json.loads((run/'contract.json').read_text(encoding='utf-8'))
    contract['chapters']={int(k):v for k,v in contract['chapters'].items()}
    audit=json.loads((run/'audit.json').read_text(encoding='utf-8'))
    audit.update(report_audit(result,contract,audit.get('degradations',[])),editorial_review=record)
    summary=json.loads((run/'summary.json').read_text(encoding='utf-8'))
    summary['editorial_review']=record
    (run/'desktop_report.md').write_text(result,encoding='utf-8')
    (run/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    (run/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')


def finalize(run):
    path=run/'desktop_report.md'
    text=path.read_text(encoding='utf-8')
    old='本批材料中家庭信息仅以“张勇夫妇”出现，未载配偶姓名及健康详情。'
    new='该段共同创办及持股材料以“张勇夫妇”合称；这些记载不能证明婚姻登记或健康状况。'
    if old not in text:
        review=run/'editorial-review.json'
        if review.exists():
            record=json.loads(review.read_text(encoding='utf-8'))
            assert hashlib.sha256(text.encode()).hexdigest()==record['output_report_sha256']
            persist_review(run,text,record)
        return
    assert text.count(old)==1
    contract=json.loads((run/'contract.json').read_text(encoding='utf-8'))
    section=split_sections(text)[2]
    line=next(x for x in section.splitlines() if old in x)
    revised=line.replace(old,new)
    ids=sorted(cited_ids(line)); package=contract['chapters']['2']
    analysis=revised.split('：',1)[1]
    import re
    analysis=re.sub(r'\s*\[E-[A-Z0-9-]+\]','',analysis).strip()
    _,errors=validate_model_claims(json.dumps({'claims':[{'analysis':analysis,'evidence_ids':ids}]},ensure_ascii=False),
        {**package,'facts':package['research_facts'],'writing_contract':'evidence_selection_v2'})
    assert not errors,errors
    result=text.replace(old,new)
    record={'kind':'editorial_narrowing_not_a_model_response','chapter':2,
        'reason':'The absence claim could be read as covering the complete report; retain only the scope of the cited joint-founder/holding passage.',
        'before':old,'after':new,'evidence_ids':ids,
        'input_report_sha256':hashlib.sha256(text.encode()).hexdigest(),
        'output_report_sha256':hashlib.sha256(result.encode()).hexdigest(),
        'editorial_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'new_model_requests':0,'new_retrieval_calls':0}
    (run/'editorial-review.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    persist_review(run,result,record)


if __name__=='__main__':
    finalize(Path(sys.argv[1]).resolve())
