"""Apply two documented, source-bound editorial corrections to the sample.

Raw model drafts remain immutable. Every changed sentence is validated and
reviewed; unchanged accepted analyses are retained. This is sample QA, not an
automatic guarantee that the general writer preserves every substantive item.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'scripts')]
from dotenv import load_dotenv
from person_semantic_review import review_analyses
from person_evidence import generate_person_report,render_section,split_sections,validate_model_claims
from person_prose_budget import enforce_budget
from replay_person_chapters import retained_claims,generation_code_snapshot
from person_iteration import ChapterInvoker
from report_agents.person_report_agent import PERSON_REPORT_OUTLINE


def read(p):return json.loads(p.read_text(encoding='utf-8'))


def main():
    work=ROOT/'work/person-review-fix-20261023';raw=work/'wang-final';out=work/'wang-reviewed';out.mkdir(exist_ok=True)
    summary,contract,audit=[read(raw/n) for n in ['summary.json','contract.json','audit.json']]
    code=generation_code_snapshot()
    assert hashlib.sha256(json.dumps(code,sort_keys=True).encode()).hexdigest()==summary['generation_code_sha256']
    edits=read(work/'targeted-corrections.json');pack=contract['chapters']['5']
    candidates=[f for f in pack['research_facts'] if f.get('analysis_allowed')]
    original_report=(raw/'desktop_report.md').read_text(encoding='utf-8');sections=split_sections(original_report)
    original_claims=retained_claims(sections[5]);new_claims=edits['claims']
    indices=[r['index'] for r in edits['changes']]
    assert all(c['analysis']==new_claims[i]['analysis'] for i,c in enumerate(original_claims) if i not in indices)
    def draft_rows(rows):return [{'analysis':c['analysis'],'evidence_ids':c['evidence_ids']} for c in rows]
    validated,errors=validate_model_claims(json.dumps({'claims':draft_rows(new_claims)},ensure_ascii=False),{**pack,'facts':pack['research_facts']})
    assert not errors
    load_dotenv(ROOT/'.env')
    os.environ.update(PERSON_REPORT_SECTION_TIMEOUT_SECONDS='180',PERSON_REPORT_SECTION_MAX_RETRIES='0',LLM_MAX_RETRIES='0')
    from research_workflow import ResearchWorkflow
    wf=ResearchWorkflow.__new__(ResearchWorkflow);wf._person_report_section_model=None
    calls=[]
    def invoke(role,prompt,emit=None):
        assert len(calls)<2
        calls.append({'role':role,'status':'started'})
        try:
            result=wf._invoke_person_report_section(role,prompt,emit)
            calls[-1].update(status='returned',output_chars=len(result))
            return result
        finally:(out/'request-status.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2),encoding='utf-8')
    model_context={'model':os.getenv('MODEL'),'endpoint_sha256':hashlib.sha256((os.getenv('BASE_URL') or '').rstrip('/').encode()).hexdigest()}
    logged=ChapterInvoker(invoke,out,rewrite=[5],model_context=model_context)
    revised,reasons,review=review_analyses(5,pack['title'],candidates,[validated[i] for i in indices],logged,
        stage='定向修订语义复核',as_of_date=contract.get('as_of_date'))
    (out/'targeted-review.json').write_text(json.dumps({'indices':indices,'review':review,'reasons':reasons},ensure_ascii=False,indent=2),encoding='utf-8')
    assert not reasons and all(c.get('analysis') for c in revised),'targeted_editorial_review_not_complete'
    for i,c in zip(indices,revised):validated[i]=c
    final,errors=validate_model_claims(json.dumps({'claims':draft_rows(validated)},ensure_ascii=False),{**pack,'facts':pack['research_facts']})
    assert not errors
    final,prose=enforce_budget(final,5);assert prose['status']=='within_budget'
    corpus=Path(summary['baseline']);intake,payload=[read(corpus/n) for n in ['intake.json','cleaned_facts.json']]
    source_bytes=(corpus/'source-snapshots.json').read_bytes()
    assert hashlib.sha256(source_bytes).hexdigest()==summary['sources_sha256']
    sources=[SimpleNamespace(**s) for s in json.loads(source_bytes)]
    for record in read(ROOT/'work/person-coverage-20261023/wang-feedback.json')['records']:
        source=next(s for s in sources if s.url==record['source_url'])
        source.source_metadata={**source.source_metadata,'person_feedback_records':[*source.source_metadata.get('person_feedback_records',[]),record]}
    project=SimpleNamespace(title=intake['target_name'],target_name=intake['target_name'],target_type='person',sources=sources,
        person_research_intake=intake,person_platform_attempts=read(corpus/'summary.json')['provider_attempts'],person_retrieval_audit=read(corpus/'person_retrieval_audit.json'))
    sections[5]=render_section(pack,final)
    diagnostic=audit['section_diagnostics']['5']
    diagnostic.update(prose_budget=prose,accepted_analysis_count=len(final),pending_review_analysis_count=0,
        model_calls=diagnostic['model_calls']+len(calls),editorial_model_calls=len(calls),
        semantic_review={'status':'targeted_editorial_corrections_reviewed','unchanged_analyses_review':diagnostic['semantic_review'],'editorial_review':review},
        editorial_corrections=[{'claim_index':i,'before':original_claims[i],'after':final[i]} for i in indices])
    retained={}
    for n in range(2,13):
        retained[n]={'text':sections[n],'selected_ids':[f['evidence_id'] for f in contract['chapters'][str(n)]['facts']],
            'diagnostic':audit['section_diagnostics'][str(n)],'claims':final if n==5 else retained_claims(sections[n]),
            'gaps':next(r for r in audit['chapters'] if r['chapter']==n).get('gaps',[])}
    def no_model(*a,**k):raise AssertionError('frozen rendering must not invoke a model')
    report=generate_person_report(project,json.dumps(payload,ensure_ascii=False),'{}',PERSON_REPORT_OUTLINE,no_model,lambda *a,**k:None,retained_sections=retained)
    after=split_sections(report)
    assert all(after[n]==sections[n] for n in range(2,13))
    assert source_bytes==(corpus/'source-snapshots.json').read_bytes()
    assert code==generation_code_snapshot()
    (out/'desktop_report.md').write_text(report,encoding='utf-8')
    for name,value in [('contract.json',project.person_evidence_contract),('audit.json',project.person_delivery_diagnostic),('generation-code-snapshot.json',code)]:
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    summary.update(raw_generation_run=str(raw),editorial_review_model_requests=len(calls),
        model_requests=summary['model_requests']+len(calls),model_requests_returned=summary['model_requests_returned']+sum(c['status']=='returned' for c in calls),
        sample_status='source_bound_targeted_editorial_corrections_applied_not_general_coverage_acceptance')
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(out),'editorial_calls':len(calls),'analysis_chars':prose['published_chars'],'sources_unchanged':True},ensure_ascii=False))


if __name__=='__main__':main()
