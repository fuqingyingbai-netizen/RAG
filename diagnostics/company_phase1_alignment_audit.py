"""Compare exact original quotations against the prior mapper on frozen data."""
from pathlib import Path
from difflib import SequenceMatcher
import hashlib
import json
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from report_agents.company_text import OriginalTextView,company_matching_cache


class LegacyView(OriginalTextView):
    def quote(self,start,end):
        if start>=end:return ''
        if self.original==self.text:return self.original[start:end]
        if self._opcodes is None:
            self._opcodes=SequenceMatcher(None,self.original,self.text,autojunk=False).get_opcodes()
        spans=[]
        for tag,a,b,c,d in self._opcodes:
            if c>=end or d<=start:continue
            spans.append((a+max(start,c)-c,a+min(end,d)-c) if tag=='equal' else (a,b))
        return self.original[spans[0][0]:spans[-1][1]] if spans else ''


def main():
    run=ROOT/'work/company-phase1-20261028'
    cases=[]
    for case in ('haitian','kingsoft'):
        database=run/'baseline'/case/'acceptance.sqlite'
        with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as db:
            target=db.execute('SELECT target_name FROM research_projects WHERE id=1').fetchone()[0]
            for sid,content in db.execute('SELECT id,content FROM research_sources ORDER BY id'):
                raw=str(content or '')[:6500]
                view=OriginalTextView(raw)
                if raw==view.text or target not in view.text:continue
                start=view.text.index(target)
                cases.append((case,sid,raw,start,start+len(target)))
                if sum(row[0]==case for row in cases)>=8:break
    outputs={};seconds={}
    for name,cls in (('legacy',LegacyView),('segmented',OriginalTextView)):
        started=time.perf_counter();values=[]
        with company_matching_cache():
            for case,sid,raw,start,end in cases:
                quoted=cls(raw).quote(start,end)
                assert quoted and quoted in raw
                values.append(quoted)
        seconds[name]=round(time.perf_counter()-started,6);outputs[name]=values
    assert outputs['legacy']==outputs['segmented'],'Original quotation differs; inspect before accepting optimization'
    result={'cases':len(cases),'seconds':seconds,'exact_quote_equality':True,
        'network_calls':0,'model_calls':0,'report_acceptance':False,
        'records':[{'case':case,'source_id':sid,'input_sha256':hashlib.sha256(raw.encode()).hexdigest(),
                    'quote_sha256':hashlib.sha256(quote.encode()).hexdigest()} for (case,sid,raw,_,_),quote in zip(cases,outputs['segmented'])]}
    (run/'alignment-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':main()
