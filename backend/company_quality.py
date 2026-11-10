"""Evidence-first evaluation helpers. Scores never replace saved per-case reasons."""
import re
import unicodedata


def normalize(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text)).casefold()


def coverage(evidence, passages):
    if not evidence:
        return None
    return sum(any(str(p['document_id'])==str(e['document_id']) and normalize(e['quote']) in normalize(p['text'])
        for p in passages) for e in evidence)/len(evidence)


def citation_ids(answer):
    return set(re.findall(r'\[id_([^\]]+)\]',answer))


def retrieval_metrics(case, candidates, references):
    evidence=case.get('evidence',[])
    used=citation_ids(case.get('answer','')); known={str(r['id']) for r in references}
    first=next((i for i,p in enumerate(candidates,1) if any(str(p['document_id'])==str(e['document_id'])
        and normalize(e['quote']) in normalize(p['text']) for e in evidence)),None)
    return {'candidate_recall':coverage(evidence,candidates),'context_recall':coverage(evidence,references),
        'reciprocal_rank':1/first if first else (0 if evidence else None),
        'invalid_citation_ids':sorted(used-known),'citation_present':bool(used)}


def validate_case(case, corpus):
    if not case.get('question') or not case.get('expected_answer'):
        raise ValueError('Each case requires question and expected_answer')
    if case.get('split') not in ('development','holdout'):
        raise ValueError('Each case needs a fixed development/holdout split')
    for e in case.get('evidence',[]):
        doc=corpus[e['document_id']]
        raw='\n'.join(p['text'] for p in doc['parts'])
        if not e.get('quote') or normalize(e['quote']) not in normalize(raw):
            raise ValueError('Gold quote not found in original: '+case['id'])
        if e.get('source_sha256')!=doc['sha256']:
            raise ValueError('Original version changed: '+case['id'])


def summary(rows):
    def mean(items):
        values=[v for v in items if v is not None]
        return sum(values)/len(values) if values else None
    result={'cases':len(rows),'errors':sum(bool(r.get('error')) for r in rows)}
    for key in ('candidate_recall','context_recall','reciprocal_rank','automated_context_precision'):
        result[key]=mean([r.get('metrics',{}).get(key) for r in rows])
    for key in ('answer_correct','complete','faithful','citation_supported','refusal_correct'):
        result[key]=mean([0 if r.get('error') and key!='refusal_correct' else int(r['judgment'][key]) if isinstance(r.get('judgment',{}).get(key),bool) else None for r in rows])
    result['invalid_citations']=sum(bool(r.get('metrics',{}).get('invalid_citation_ids')) for r in rows)
    result['answer_latency_seconds']=mean([r.get('answer_seconds') for r in rows])
    result['evaluation_seconds']=mean([r.get('seconds') for r in rows])
    return result
