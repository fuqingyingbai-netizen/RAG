"""Prepare an isolated usage-builder copy; never edit the running backend."""
from pathlib import Path

root = Path(__file__).resolve().parents[3]
source = root / 'backend/report_agents/company_information_usage.py'
text = source.read_text(encoding='utf-8')

def replace_once(old, new):
    global text
    assert text.count(old) == 1, old
    text = text.replace(old, new, 1)

replace_once('previous=None, review_scope=None, emit=None, trace_emit=None):',
             'previous=None, review_scope=None, emit=None, trace_emit=None, journal_loader=None):')
replace_once("    for row in records:\n        if row['information_id'] in decisions:continue\n",
'''    journal_ids=[]
    if journal_loader:
        try:
            candidates=journal_loader(records)
            for row in records:
                iid=row['information_id']
                if iid in decisions:continue
                candidate=candidates.get(iid) if isinstance(candidates,dict) else None
                if not isinstance(candidate,dict) or candidate.get('status')!='use':continue
                checked,errors=validate_review([row],{'records':[candidate]},outline)
                if not errors and iid in checked:
                    decisions[iid]=checked[iid];cached_ids.append(iid);journal_ids.append(iid)
        except Exception as exc:
            if emit:
                emit(trace_emit,'report','company_checkpoint','信息用途恢复回执读取失败',
                     type(exc).__name__+'；未恢复记录仍重新判定。',status='warning')
    for row in records:
        if row['information_id'] in decisions:continue
''')
replace_once("        receipt={'information_ids':[r['information_id'] for r in rows],'decisions':checked,",
'''        receipt={'routing_version':VERSION,'target_name':target,'review_scope':scope,
            'routing_record_hashes':{r['information_id']:fingerprints[r['information_id']] for r in rows},
            'information_ids':[r['information_id'] for r in rows],'decisions':checked,''')
replace_once("review_batches_with_errors=sum(bool(r['errors']) for r in receipts),cached_information_records=len(cached_ids))",
             "review_batches_with_errors=sum(bool(r['errors']) for r in receipts),cached_information_records=len(cached_ids),\n        cached_journal_records=len(journal_ids))")
output=Path(__file__).with_name('company_information_usage.py')
output.write_text(text,encoding='utf-8')
print('Prepared isolated usage-builder copy; backend unchanged.')
