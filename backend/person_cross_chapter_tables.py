"""Reuse real professional fields once per report, with final physical checks.

Only deterministic professional tables qualify. This never grants permission
to turn company fields, a role, or a source opinion into a personal judgment.
"""
import hashlib
import json
import re
from collections import defaultdict

KINDS={'person_platform_record','person_company_record'}


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def eligible(fact,target):
    from person_text import folded
    if (fact.get('claim_type') not in KINDS or fact.get('subject_scope') not in {'person','affiliated_company'}
            or fact.get('comparison_subject') or fact.get('team_member_name')):return False
    return fact.get('subject_scope')!='person' or bool(target and folded(fact.get('subject',''))==folded(target))


def signature(fact):
    return digest({k:fact.get(k) for k in ('evidence_id','fact','source_url','subject','subject_scope','claim_type')})


def row_parts(line):
    """Keep field labels/values intact, including escaped Markdown pipes."""
    if not isinstance(line,str) or not line.startswith('|'):return None
    cells=re.split(r'(?<!\\)\|',line)
    if len(cells)<4:return None
    ids=set(re.findall(r'\[(E-[A-Z0-9-]+)\]',cells[-2]))
    return (tuple(c.strip() for c in cells[1:-2]),ids) if ids else None


def chapter_map(contract):
    return {int(n):p for n,p in contract['chapters'].items()}


def native_rows(package):
    from person_structured_tables import structured_tables
    return [(line,*parts) for line in structured_tables(package) if (parts:=row_parts(line))]


def attach_professional_table_references(contract):
    """Plan only exact admitted records represented by a native typed table."""
    chapters=chapter_map(contract);facts={f['evidence_id']:f for f in contract['facts']}
    candidates=defaultdict(list)
    for n in (4,9,12):
        if n not in chapters:continue
        for line,fields,ids in native_rows(chapters[n]):
            if not all(e in facts and eligible(facts[e],contract.get('target_name','')) for e in ids):continue
            for eid in ids:
                if eid in facts and eligible(facts[eid],contract.get('target_name','')):
                    candidates[eid].append((n,line,fields,ids))
    total=0
    for n,p in chapters.items():
        p.pop('professional_table_references',None)
        if n not in range(2,13):continue
        native_ids={eid for _,_,ids in native_rows(p) for eid in ids}
        grouped={}
        for f in p.get('research_facts',p.get('facts',[])):
            eid=f['evidence_id']
            if (eid in native_ids or eid not in candidates or not eligible(f,contract.get('target_name',''))
                    or eid not in facts or signature(f)!=signature(facts[eid])):continue
            choices=[r for r in candidates[eid] if r[0]!=n]
            if not choices:continue
            origin,line,fields,ids=choices[0];key=(origin,fields)
            ref=grouped.setdefault(key,{'chapter':origin,'text':line,'fields':list(fields),
                'evidence_ids':[],'record_signatures':{},'target_name':contract.get('target_name',''),
                'row_source_records':[{k:facts[e].get(k) for k in ('evidence_id','fact','source_url','subject','subject_scope','claim_type')}
                    for e in sorted(ids) if e in facts and facts[e].get('claim_type') in KINDS]})
            ref['evidence_ids'].append(eid);ref['record_signatures'][eid]=signature(f)
        if grouped:
            p['professional_table_references']=list(grouped.values());total+=sum(len(r['evidence_ids']) for r in grouped.values())
    return total


def reference_rows(package):
    """Current source binding is required even for an internally planned row."""
    facts={f['evidence_id']:f for f in package.get('research_facts',package.get('facts',[]))}
    result=[]
    for ref in package.get('professional_table_references',[]):
        ids=ref.get('evidence_ids',[]);parts=row_parts(ref.get('text'))
        if (not ids or not parts or list(parts[0])!=ref.get('fields')
                or not set(ids)<=parts[1] or ref.get('chapter')==package['chapter']):continue
        if not all(e in facts and eligible(facts[e],ref.get('target_name',''))
                   and ref.get('record_signatures',{}).get(e)==signature(facts[e]) for e in ids):continue
        result.append(ref)
    return result


def reference_lines(package):
    grouped=defaultdict(set)
    for ref in reference_rows(package):grouped[ref['chapter']].update(ref['evidence_ids'])
    if not grouped:return []
    lines=['','### 跨章专业资料引用','']
    for origin,ids in sorted(grouped.items()):
        example=sorted(ids)[0]
        lines.append(f'本章涉及的{len(ids)}条专业平台记录的原字段已在第{origin}章资料表逐项列示，沿用该表的主体、字段名、时期及状态限定，不重复抄录。回查示例：[{example}]。')
    lines+=['专业表的展示与引用不等于个人判断；企业成立日不是个人任职起点，空结束日期不等于任职至今，公司字段不认定个人贡献、债务或信用。','']
    return lines


def validate_report_references(report,contract,diagnostics):
    """A planned reference cannot certify absent, edited, or wrong-scope data."""
    from person_evidence import split_sections
    sections=split_sections(report);chapters=chapter_map(contract)
    facts={f['evidence_id']:f for f in contract['facts']};errors=[]
    for n,p in chapters.items():
        d=diagnostics.get(n,diagnostics.get(str(n),{}))
        used={r['evidence_id']:r for r in d.get('content_acceptance',{}).get('material_diagnosis',{}).get('rows',[])
              if r.get('disposition')=='table_reference'}
        if not used:continue
        refs=reference_rows(p);resolved=set()
        for ref in refs:
            ids=set(ref['evidence_ids'])&set(used)
            if not ids:continue
            origin=ref['chapter'];canonical=native_rows(chapters.get(origin,{'chapter':origin,'facts':[]}))
            expected=set().union(*(row_ids for _,fields,row_ids in canonical if list(fields)==ref['fields']))
            actual=[parts for line in sections.get(origin,'').splitlines() if (parts:=row_parts(line))]
            source_ok=(ref.get('target_name')==contract.get('target_name','')
                and all(e in facts and ref['record_signatures'].get(e)==signature(facts[e]) for e in ids)
                and all(r['evidence_id'] in facts and signature(r)==signature(facts[r['evidence_id']]) for r in ref.get('row_source_records',[])))
            rows_ok=any(list(fields)==ref['fields'] and ids<=row_ids<=expected for fields,row_ids in actual)
            note_ok=all(line in sections.get(n,'') for line in reference_lines(p) if line and not line.startswith('###'))
            state_ok=all(used[e].get('referenced_chapter')==origin for e in ids)
            if source_ok and rows_ok and note_ok and state_ok:resolved.update(ids)
        for eid in sorted(set(used)-resolved):errors.append({'chapter':n,'code':'professional_table_reference_unresolved','evidence_id':eid})
    return errors
