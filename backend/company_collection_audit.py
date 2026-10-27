"""Company candidate dispositions and bounded primary-document diversity reserve."""
import hashlib
import threading
from collections import Counter
from urllib.parse import urlparse

from search_results import canonical_source_url
from report_agents.company_governance import get
from report_agents.company_text import match_compact

VERSION='company-collection-audit-v2-retained-provider-text'
EXCHANGES=('hkexnews.hk','cninfo.com.cn','szse.cn','sse.com.cn','sec.gov')


def available_provider_original(item):
    """Already supplied text can be archived without spending a fetch budget."""
    from report_agents.company_evidence import blocked_original_reason
    meta=item.get('metadata') or {};body=str(item.get('content') or '').strip()
    return (meta.get('content_origin') in {'original_page','provider_raw_content','provider_text'}
        and len(body)>=35 and not blocked_original_reason(body))


def primary_candidate(item,target,issuer_hosts=()):
    """A fetch-priority decision, never subject/fact verification."""
    host=(urlparse(str(item.get('url') or '')).hostname or '').lower().removeprefix('www.')
    authority=any(host==root or host.endswith('.'+root) for root in EXCHANGES)
    authority=authority or host.endswith('.gov.cn') or host in issuer_hosts
    if not authority:return False
    # The source title/body must name the complete legal target. The search
    # query and generated summary cannot authorize a diversity exception.
    original=str(item.get('title') or '')+'\n'+str(item.get('content') or '')[:4000]
    return bool(target and match_compact(target) in match_compact(original))


def module_host_counts(sources,target='',issuer_hosts=()):
    counts=Counter();seen=set()
    for source in sources:
        url=str(get(source,'url'));meta=get(source,'source_metadata',{}) or {}
        if target and not primary_candidate({'url':url,'title':get(source,'title'),'content':get(source,'content')},target,issuer_hosts):continue
        key=canonical_source_url(url)
        if key in seen:continue
        seen.add(key)
        host=(urlparse(url).hostname or '').lower().removeprefix('www.')
        counts[(host,str(meta.get('module') or 'general'))]+=1
    return counts


class CollectionAudit:
    def __init__(self,target,as_of=''):
        self.target=target;self.as_of=as_of;self.rows={};self.lock=threading.RLock()

    def candidate(self,item,query,module):
        url=str(item.get('url') or '')
        key=hashlib.sha256((canonical_source_url(url)+'\n'+query+'\n'+module).encode()).hexdigest()
        with self.lock:
            self.rows.setdefault(key,{'url':url,'canonical_url':canonical_source_url(url),'title':str(item.get('title') or ''),
                'query':query,'module':module,'provider':(item.get('metadata') or {}).get('provider',''),
                'outcome':'candidate_not_finished','events':[]})
        return key

    def observe(self,event):
        if event.get('stage')!='web_search' or not event.get('url'):return
        query=str(event.get('query') or '');module=str(event.get('module') or 'general')
        key=self.candidate({'url':event['url']},query,module)
        with self.lock:
            row=self.rows[key]
            row['events'].append({k:event[k] for k in ('label','status','skip_reason','fetch_status','budget_route') if k in event})
            label=str(event.get('label') or '')
            if label in {'网页来源已保存','复用已归档网页来源'}:row['outcome']='archived'
            elif label=='跳过同域名过量来源':row['outcome']='deferred_host_budget'
            elif label=='跳过重复网页':row['outcome']='duplicate_url'
            elif event.get('status')=='skipped':row['outcome']=str(event.get('skip_reason') or label)
            elif label=='单条网页归档失败，继续下一条':row['outcome']='archive_failed'

    def snapshot(self,sources):
        archived={canonical_source_url(str(get(s,'url'))):get(s,'id') for s in sources}
        with self.lock:
            rows=[{**r,'events':list(r['events']),'archived_source_id':archived.get(r['canonical_url'])} for r in self.rows.values()]
        return {'version':VERSION,'target_name':self.target,'as_of_date':self.as_of,'candidates':rows,
                'summary':{'candidate_appearances':len(rows),'canonical_urls':len({r['canonical_url'] for r in rows}),
                           'outcomes':dict(Counter(r['outcome'] for r in rows))},
                'boundary':'域名预算递延不表示无关或不可用；优先抓取不构成主体、真实性或事实质量验收。'}
