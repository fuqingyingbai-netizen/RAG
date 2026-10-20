"""Bounded original-disclosure follow-up on a retained corpus, no model calls."""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    parser.add_argument('--search-budget', type=int, default=3, choices=range(1,5))
    parser.add_argument('--fetch-budget', type=int, default=4, choices=range(1,7))
    parser.add_argument('--deadline-utc', required=True)
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    os.environ['RESEARCH_USER_DEADLINE_UTC'] = args.deadline_utc
    from research_workflow import ResearchWorkflow
    from research_strategies.person import PersonResearchStrategy
    from person_retrieval import SearchSession, user_time_remaining
    from person_chapter_research import primary_document
    from web_search import web_search_provider
    from person_iteration import copy_retained_tree
    baseline = args.baseline.resolve()
    out = ROOT/'work/person-optimization'/('primary-followup-'+datetime.now().strftime('%Y%m%dT%H%M%S'))
    out.mkdir(parents=True)
    snapshots = json.loads((baseline/'source-snapshots.json').read_text(encoding='utf-8'))
    raw = json.loads((baseline/'intake.json').read_text(encoding='utf-8'))
    target = raw.get('target_name') or raw['company_name']
    project = SimpleNamespace(target_name=target, target_type='person', title=target, industry='', description='')
    workflow = ResearchWorkflow()
    intake = workflow._normalize_intake(project, raw, [], [])
    items = PersonResearchStrategy().expand_search_queries({'modules':[]}, intake)
    routing = SearchSession(intake,[name for name,_ in web_search_provider.engines])
    attempts, fetches, seen = [], [], {s['url'] for s in snapshots}
    providers = [p for p in ('bocha','tavily','exa') if os.getenv(p.upper()+'_API_KEY')]
    for index, provider in enumerate(providers[:args.search_budget]):
        if user_time_remaining() < 110 or len(fetches) >= args.fetch_budget:
            break
        sources = [SimpleNamespace(**r) for r in snapshots]
        query = routing.primary_identity_query(items, sources, index+1)
        if not query:
            break
        event = {'provider':provider,'query':query['query'],'include_domains':query.get('include_domains',[])}
        attempts.append(event)
        try:
            results = web_search_provider.search_single(provider, query['query'], limit=6,
                include_domains=query.get('include_domains'), category=query.get('exa_category'))
            event.update(status='returned', result_count=len(results))
        except Exception as exc:
            event.update(status='failed', exception_type=type(exc).__name__)
            continue
        for result in results:
            url = result.get('url') or ''
            candidate = SimpleNamespace(url=url)
            if not url.startswith(('https://','http://')) or url in seen or not primary_document(candidate):
                continue
            if len(fetches) >= args.fetch_budget or user_time_remaining() < 110:
                break
            seen.add(url)
            try:
                fetched = workflow._fetch_web_url_with_timeout(url,False,document_profile='person')
            except Exception as exc:
                fetched = {'status':'failed','exception_type':type(exc).__name__}
            body = fetched.get('content') or ''
            identity = workflow._person_source_identity_confidence(result.get('title',''),body,intake)
            receipt = {'url':url,'status':fetched.get('status'),'text_chars':len(body),'identity':identity}
            fetches.append(receipt)
            (out/f'original-response-{len(fetches)}.json').write_text(json.dumps(fetched,ensure_ascii=False),encoding='utf-8')
            if fetched.get('status') != 'done' or len(body)<120 or identity['confidence'] not in {'medium','high'}:
                continue
            snapshots.append({'id':max(r['id'] for r in snapshots)+1,'source_type':'filing',
                'title':result.get('title') or '人物原始披露','url':url,'content':body,'summary':'','credibility_score':85,
                'source_metadata':{'provider':provider,'module':'人物原始身份与治理披露','content_kind':'full_text',
                    'identity_confidence':identity['confidence'],'identity_status':'accepted','identity_reason':identity['reason'],
                    'person_intake_fingerprint':workflow._intake_evidence_fingerprint(intake),'fetch_status':'done',
                    'retrieved_at':datetime.now(timezone.utc).isoformat(),
                    **{k:fetched[k] for k in ('document_pages','document_extraction') if k in fetched}}})
        print(json.dumps(event,ensure_ascii=False),flush=True)
    audit = json.loads((baseline/'person_retrieval_audit.json').read_text(encoding='utf-8'))
    audit['primary_identity_followup'] = {'attempts':attempts,'fetches':fetches,'new_model_calls':0,'new_professional_calls':0}
    audit['calls_planned'] = audit.get('calls_planned',0)+len(attempts)
    audit['page_fetch_attempts'] = audit.get('page_fetch_attempts',0)+len(fetches)
    summary = json.loads((baseline/'summary.json').read_text(encoding='utf-8'))
    summary.update(scope='retained_corpus_plus_primary_identity_followup',baseline=str(baseline),new_search_calls=len(attempts),
        new_fetches=len(fetches),source_count=len(snapshots),new_model_calls=0,new_professional_calls=0)
    copy_retained_tree(baseline/'objects-before-cleanup',out/'objects-before-cleanup')
    for name,data in [('source-snapshots.json',snapshots),('intake.json',raw),('person_retrieval_audit.json',audit),('summary.json',summary)]:
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'saved':str(out),'sources':len(snapshots),'queries':len(attempts),'fetches':len(fetches)},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
