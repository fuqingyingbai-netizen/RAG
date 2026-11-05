"""Read historical reports and their own linked receipts; never call services."""
import collections
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'backend')]
from search_results import canonical_source_url


def compact(text):return re.sub(r'\s+','',text)
def counts(mapping):return {k:len(v) if isinstance(v,list) else v for k,v in mapping.items()}


def audit_case(name):
    path=ROOT/'work/company-phase1-20261028/native'/name/'acceptance.sqlite'
    con=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    con.row_factory=sqlite3.Row
    report=dict(con.execute("SELECT * FROM research_artifacts WHERE artifact_type='desktop_report' ORDER BY id DESC LIMIT 1").fetchone())
    meta=json.loads(report['artifact_metadata']);packages={};ids={}
    for kind in ('company_source_coverage','company_corpus_digest','company_information_usage','company_editorial','company_presentation'):
        aid=meta[kind+'_artifact_id'];row=con.execute('SELECT artifact_type,content FROM research_artifacts WHERE id=?',(aid,)).fetchone()
        if row['artifact_type']!=kind:raise ValueError('linked artifact type mismatch')
        packages[kind]=json.loads(row['content']);ids[kind]=aid
    coverage=packages['company_source_coverage'];sources=coverage['sources']
    full=[r for r in sources if r['text_origin']=='retrieved_content']
    unique={r['original_sha256'] for r in full if r.get('original_sha256')}
    platform=[r for r in sources if r.get('review',{}).get('professional_platform')]
    corpus_states=dict(collections.Counter(r.get('review',{}).get('state') for r in sources))
    editorial=packages['company_editorial'];usage=packages['company_information_usage'];presentation=packages['company_presentation']
    body=re.split(r'(?m)^##\s*13[.、．]',report['content'])[0]
    exact=[f for f in editorial['findings'] if compact(f['text']) in compact(body)]
    platform_audit=json.loads(con.execute("SELECT content FROM research_artifacts WHERE artifact_type='professional_platform_audit' ORDER BY id DESC LIMIT 1").fetchone()[0])
    attempt_counts=collections.Counter(str(r.get('provider'))+':'+str(r.get('status')) for r in platform_audit['attempts'])
    audits=[]
    # An empty later collection receipt does not prove that the original search
    # returned zero. Keep this stage unknown unless raw engine returns exist.
    for row in con.execute("SELECT id,created_at,length(content) AS chars FROM research_artifacts WHERE artifact_type='company_collection_audit' ORDER BY id"):
        audits.append(dict(row))
    candidate_keys=set();candidate_urls=set();latest_outcome={}
    for row in con.execute("SELECT content FROM research_artifacts WHERE artifact_type='company_collection_audit' AND created_at<=? AND length(content)>1000 ORDER BY id",(report['created_at'],)):
        for r in json.loads(row['content']).get('candidates',[]):
            url=r.get('canonical_url') or canonical_source_url(r.get('url',''))
            candidate_urls.add(url);candidate_keys.add((url,r.get('query'),r.get('module')))
            latest_outcome[url]=r.get('outcome')
    stored_urls={canonical_source_url(r['url']) for r in sources}
    result={'target':meta.get('company_delivery_contract',{}).get('target_name'),
        'report_artifact_id':report['id'],'report_created_at':report['created_at'],
        'report_sha256':hashlib.sha256(report['content'].encode()).hexdigest(),
        'delivery_status':meta.get('delivery_status'),'linked_artifact_ids':ids,
        'sources_added_after_report':con.execute('SELECT count(*) FROM research_sources WHERE created_at>?',(report['created_at'],)).fetchone()[0],
        'raw_engine_hit_count':None,'raw_engine_hit_count_reason':'完整原始搜索返回未在本次统计中核实，不用入库条数或空的后续采集回执替代。',
        'observed_search_candidates':{'distinct_url_query_module':len(candidate_keys),'distinct_urls':len(candidate_urls),
            'urls_present_in_final_source_catalogue':len(candidate_urls & stored_urls),
            'urls_absent_from_final_source_catalogue':len(candidate_urls-stored_urls),
            'catalogue_urls_not_in_retained_candidate_receipts':len(stored_urls-candidate_urls),
            'professional_sources_outside_candidate_receipts':sum(canonical_source_url(r['url']) not in candidate_urls for r in platform),
            'professional_sources_inside_candidate_receipts':sum(canonical_source_url(r['url']) in candidate_urls for r in platform),
            'absent_url_last_observed_outcomes':dict(collections.Counter(latest_outcome[u] for u in candidate_urls-stored_urls)),
            'boundary':'留存采集回执中的观察集合；不是各引擎原始命中数，也不等于完整调用次数。'},
        'source_summary':coverage['summary'],'retrieved_unique_body_hashes':len(unique),
        'retrieved_exact_body_duplicate_records':len(full)-len(unique),'corpus_source_states':corpus_states,
        'information_usage':counts(usage['diagnostic']),
        'statement_origins':dict(collections.Counter(r.get('origin') for r in packages['company_corpus_digest']['statements'])),
        'presentation':counts(presentation['diagnostic']),
        'editorial':counts(editorial['diagnostic']),
        'editorial_final_batch_error_types':dict(collections.Counter(e for b in editorial['batches'] for e in b.get('errors',[]))),
        'exact_approved_paragraphs_in_saved_body':len(exact),
        'accepted_paragraphs':len(editorial['findings']),
        'contract_missing_or_changed_paragraph_errors':sum(e.startswith('核对通过的段落在最终正文中丢失或被改写') for e in meta.get('company_delivery_contract',{}).get('errors',[])),
        'semantic_adoption_count':None,
        'semantic_adoption_boundary':'引用来源数、逐批审核通过信息数、原句字面出现数均不能替代最终正文逐命题语义采用数。',
        'professional_platform':{'source_records':len(platform),
            'origins':dict(collections.Counter(r['text_origin'] for r in platform)),
            'source_states':dict(collections.Counter(r.get('review',{}).get('state') for r in platform)),
            'specialist_candidate_sources':sum(bool(r.get('chapter_candidates')) for r in platform),
            'claim_packaged_sources':sum(bool(r.get('claim_packaged_in')) for r in platform),
            'body_cited_sources':sum(r.get('body_cited',False) for r in platform),
            'recorded_direct_api_attempt_status':dict(attempt_counts)},
        'collection_audit_summaries':audits,'new_model_calls':0,'new_search_calls':0}
    annex=con.execute('SELECT id,content FROM research_artifacts WHERE id=?',(meta.get('company_evidence_annex_artifact_id'),)).fetchone()
    if annex:
        annex_ids=re.findall(r'<article\b[^>]*\bdata-information-id="([^"]+)"',annex['content'])
        result['evidence_annex']={'artifact_id':annex['id'],'information_records':len(annex_ids),
            'distinct_information_ids':len(set(annex_ids)),'integrity_status':meta.get('evidence_annex_status')}
    con.close()
    # Conservation checks use the same report's receipts, not newer caches.
    s=result['source_summary'];p=result['presentation'];e=result['editorial'];u=result['information_usage']
    assert sum(s['origins'].values())==s['source_records']
    assert sum(corpus_states.values())==s['source_records']
    assert p['main_information']+p['evidence_information']+p['pending_information_ids']==p['native_information']
    assert e['narrative_information']+e['pending_information_ids']==e['usable_information']
    assert u['states']['used_in_chapter_detail']+u['states']['excluded_with_reason']==u['exact_distinct_information_records']
    return result


if __name__=='__main__':
    output=ROOT/'work/company-source-flow-audit-20261104';output.mkdir(exist_ok=True)
    results={name:audit_case(name) for name in ('haitian','kingsoft')}
    (output/'analysis.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    for name,r in results.items():
        preview={k:v for k,v in r.items() if k!='collection_audit_summaries'}
        print(name,json.dumps(preview,ensure_ascii=False),flush=True)
