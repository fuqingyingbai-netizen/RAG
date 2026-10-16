"""Industry evidence requirements, source locators and report claim lineage.

Pure, deterministic contracts: candidate retrieval is never proof of a claim.
"""
import hashlib
import json
import re
from array import array
from collections import OrderedDict

VERSION = 'industry-evidence-contract-v2-atomic-passages'

# Requirements describe research questions, not an obligation to manufacture data.
REQUIREMENTS = (
    ('market_size', '市场规模与增长', '市场规模及年度口径', r'市场规模|产业规模|行业规模', 'amount', '市场规模 官方统计 年度 地域 统计口径'),
    ('growth', '市场规模与增长', '历史增长率及预测区别', r'增长率|增速|同比|CAGR|复合增长', 'percent', '历史 同比增长率 CAGR 预测 统计口径'),
    ('concentration', '竞争格局与代表企业', '行业集中度CR3/CR5或HHI', r'CR[235]|HHI|集中度', 'percent', 'CR3 CR5 HHI 行业集中度 年度 样本范围 数据'),
    ('market_share', '竞争格局与代表企业', '头部玩家市场份额及分母', r'市场份额|市占率', 'percent', '头部企业 市场份额 市占率 统计年度 行业分母'),
    ('pricing_model', '商业模式与盈利逻辑', '实际收费及变现机制', r'订阅|按量|按需|计费|收费模式|授权费', 'qualitative', '行业研究 订阅 按量计费 收费模式 实际落地'),
    ('profitability', '商业模式与盈利逻辑', '行业盈利质量及样本边界', r'毛利率|净利率|付费转化率|续约率|客户留存', 'percent', '行业 毛利率 付费转化率 续约率 样本统计'),
    ('technology_cost', '技术路线对比', '可比技术成本及测试条件', r'成本|单价|价格|费用', 'amount', '技术路线 单位成本 单价 测试条件 对比 实测'),
    ('policy', '政策与监管', '政策原文与适用范围', r'条例|办法|规定|标准|监管|准入', 'qualitative', '监管 准入 政策原文 适用范围 生效日期'),
    ('capital', '投融资与资本市场', '行业融资统计及年度口径', r'融资总额|融资规模|投资总额', 'amount', '行业融资规模 统计年度 统计口径'),
)


def stored_body(source) -> str:
    meta=source.source_metadata or {}
    if (meta.get('content_kind')=='summary_only' or meta.get('extraction_status') in {'summary_only','error','failed','empty','pending'}
            or str(source.content or '').lstrip().startswith(('[解析失败','[待解析'))):
        return ''
    return str(source.content or '')


def _locator_key(url: str) -> str:
    from industry_research import source_document_key
    value=str(url or '').strip()
    return value.split('#',1)[0].rstrip('/') if value.startswith('structured://') else source_document_key(value)


def source_fingerprint(sources: list) -> str:
    """Cache only equivalent primary-body snapshots; ignore duplicate rows and summaries."""
    rows=set()
    for source in sources:
        body=stored_body(source)
        if not body.strip():continue
        meta=source.source_metadata or {}
        row={'document':_locator_key(source.url),'body_sha256':hashlib.sha256(body.encode()).hexdigest(),
            'title':source.title,'type':source.source_type,'credibility':getattr(source,'credibility_score',None),
            'publication':{k:meta.get(k) for k in ('published_date','published_at','publication_date','publisher','provider')},
            'scope':{k:meta.get(k) for k in ('module','evidence_scope','company_role','industry_name','segment_name','company_name')}}
        rows.add(json.dumps(row,sort_keys=True,ensure_ascii=False))
    return hashlib.sha256(json.dumps(sorted(rows),ensure_ascii=False).encode()).hexdigest()


def evidence_requirements(modules: list, scope: dict | None = None) -> list[dict]:
    selected = {m.get('name') if isinstance(m, dict) else m for m in modules}
    return [{'id':eid, 'module':module, 'question':question, 'metric_pattern':pattern,
             'kind':kind, 'query_terms':query, 'accepted_scopes':['industry_level','segment_level'],
             'verification_fields':['source_locator','scope','metric_context'] if kind!='qualitative' else ['source_locator','scope']}
            for eid,module,question,pattern,kind,query in REQUIREMENTS if module in selected
            and not (module=='投融资与资本市场' and (scope or {}).get('capital_market')=='none')]


def _metric_present(text: str, requirement: dict) -> bool:
    from industry_research import numeric_mentions
    for match in re.finditer(requirement['metric_pattern'], text, re.I):
        # Restrict to the sentence containing the metric; page-level co-occurrence is insufficient.
        left = max(text.rfind('。',0,match.start()), text.rfind('\n',0,match.start())) + 1
        ends = [p for sep in ('。','\n') if (p:=text.find(sep,match.end()))>=0]
        right = min(ends) if ends else len(text)
        sentence = text[max(left,match.start()-80):min(right,match.end()+160)]
        if re.search(r'未披露|未提供|没有|缺少|暂无|待核验|不详', sentence):
            continue
        if requirement['kind']=='qualitative':
            return True
        numbers = numeric_mentions(sentence)
        if requirement['kind']=='percent' and any('%' in n or '％' in n for n in numbers):
            return True
        if requirement['id']=='concentration' and re.search(r'HHI\s*(?:为|达到|=|：|:)\s*\d{2,5}',sentence,re.I):
            return True
        if requirement['kind']=='amount' and any(re.search(r'元|美元',n) for n in numbers):
            return True
    return False


def source_coverage(sources: list, requirements: list[dict]) -> dict:
    """Body-level candidate coverage drives search; summaries and titles never fulfill it."""
    from industry_research import source_document_key
    rows = []
    for req in requirements:
        documents = set()
        for source in sources:
            meta = source.source_metadata or {}
            if meta.get('module') != req['module'] or meta.get('evidence_scope') == 'representative_company':
                continue
            from industry_grounding import sample_boundary
            if sample_boundary({'source_title':source.title,'source_type':source.source_type}):continue
            body = stored_body(source)
            if body and _metric_present(body,req):
                key = source_document_key(source.url)
                if key: documents.add(key)
        rows.append({'requirement_id':req['id'], 'module':req['module'], 'question':req['question'],
                     'status':'candidate' if documents else 'missing', 'candidate_document_count':len(documents),
                     'verified_evidence_ids':[]})
    return {'version':VERSION, 'phase':'retrieval_candidates', 'requirements':rows,
            'information_gaps':[f"{r['module']}：缺少可定位的{r['question']}候选原文 [需求:{r['requirement_id']}]"
                                for r in rows if r['status']=='missing']}


def attach_provenance(facts: list[dict], sources: list, body_snapshots: dict | None = None) -> list[dict]:
    """Locate stored quotes in immutable body hashes, never in search summaries."""
    from industry_research import source_document_key
    by_url = {}
    for source in sources:
        key = _locator_key(source.url)
        if key: by_url.setdefault(key,[]).append(source)
    result = []
    normalized_bodies=OrderedDict()
    cached_chars=0
    for original in facts:
        fact = dict(original)
        quote = str(fact.get('evidence_quote') or fact.get('fact') or '').strip()
        locator = {'status':'unlocated', 'reason':'quote_not_in_stored_body'}
        candidates = by_url.get(_locator_key(fact.get('source_url','')),[])
        for source in candidates:
            body = stored_body(source)
            if not quote or not body: continue
            start=body.find(quote);end=start+len(quote);mode='literal'
            if start<0:
                key=id(source)
                if key not in normalized_bodies:
                    normalized=re.sub(r'\s+','',body).lower()
                    positions=array('I',(i for i,ch in enumerate(body) if not ch.isspace() for _ in ch.lower()))
                    if len(normalized)<=2_000_000:
                        normalized_bodies[key]=(normalized,positions);cached_chars+=len(normalized)
                        while len(normalized_bodies)>8 or cached_chars>2_000_000:
                            _,(old,_) = normalized_bodies.popitem(last=False);cached_chars-=len(old)
                else:
                    normalized,positions=normalized_bodies[key]
                    normalized_bodies.move_to_end(key)
                needle=re.sub(r'\s+','',quote).lower();offset=normalized.find(needle)
                if offset<0:continue
                start=positions[offset];end=positions[offset+len(needle)-1]+1;mode='whitespace_case_normalized'
            locator = {'status':'verified', 'source_id':getattr(source,'id',None),
                'source_object_key':getattr(source,'object_key',''), 'body_field':'research_sources.content_snapshot',
                'body_version_id':'sha256:'+hashlib.sha256(body.encode()).hexdigest(),
                'archive_binding_status':'not_verified',
                'source_document_key':_locator_key(source.url),
                'body_sha256':hashlib.sha256(body.encode()).hexdigest(),
                'start':start, 'end':end, 'match_mode':mode, 'quote':body[start:end]}
            anchor=str(fact.get('scope_anchor_quote') or '')
            if anchor:
                anchor_start=body.find(anchor)
                if anchor_start<0:
                    fact.update(eligible_for_report=False,eligible_for_risk_scoring=False)
                    fact['scope_anchor_validation']='unlocated'
                else:
                    locator['scope_anchor']={'start':anchor_start,'end':anchor_start+len(anchor),'quote':anchor}
            if body_snapshots is not None:
                digest=locator['body_sha256']
                body_snapshots.setdefault(digest,{'content':body,'body_sha256':digest,
                    'source_url':source.url,'source_id':getattr(source,'id',None),'source_title':source.title,
                    'archive_object_key':getattr(source,'object_key',''),'archive_binding_status':'not_verified'})
                locator['body_field']=f'cleaned_facts.source_body_snapshots.{digest}.content'
                locator['snapshot_key']=digest
            from industry_grounding import source_metadata
            if source.title:fact['source_title']=source.title
            for name,value in source_metadata(source).items():
                if value and not fact.get(name):fact[name]=value
            from industry_grounding import sample_boundary
            boundary=sample_boundary(fact)
            if boundary:
                fact.update(evidence_scope='representative_company',eligible_for_risk_scoring=False,
                            sample_boundary_reason=boundary,attribution_boundary=boundary)
            # A raw-page card is an audit container. Its located passage, not
            # later unlocated paragraphs, is the writer's authorization.
            if fact.get('claim_type')=='source_excerpt':
                fact['attribution_boundary'] = '仅定位摘录可供转述；较长页面内容仅保留审计，完整语义仍待复核。'
            break
        fact['provenance'] = {'version':VERSION, 'locator':locator}
        result.append(fact)
    return result


def fact_requirement_ids(fact: dict, requirements: list[dict], verified_only: bool = False) -> list[str]:
    from industry_grounding import sample_boundary
    if sample_boundary(fact):return []
    if fact.get('scope_match')!='in_scope' or fact.get('eligible_for_report') is False:
        return []
    locator_ok = (fact.get('provenance') or {}).get('locator',{}).get('status')=='verified'
    matched = []
    for req in requirements:
        if fact.get('module')!=req['module'] or fact.get('evidence_scope') not in req['accepted_scopes']:
            continue
        if not _metric_present(str(fact.get('fact') or ''),req): continue
        if verified_only:
            if not locator_ok or fact.get('claim_type')=='source_excerpt': continue
            context = fact.get('numeric_context') or {}
            if req['kind']!='qualitative' and ((fact.get('numeric_validation') or {}).get('passed') is not True
                    or not re.search(req['metric_pattern'],str(context.get('metric') or ''),re.I)):
                continue
        matched.append(req['id'])
    return matched


def fact_coverage(facts: list[dict], requirements: list[dict]) -> dict:
    rows = []
    for req in requirements:
        candidates = [f['evidence_id'] for f in facts if f.get('evidence_id') and req['id'] in fact_requirement_ids(f,[req])]
        verified = [f['evidence_id'] for f in facts if f.get('evidence_id') and req['id'] in fact_requirement_ids(f,[req],True)]
        rows.append({'requirement_id':req['id'],'module':req['module'],'question':req['question'],
            'status':'verified' if verified else 'candidate' if candidates else 'missing',
            'candidate_evidence_ids':candidates,'verified_evidence_ids':verified})
    return {'version':VERSION,'phase':'cleaned_facts','requirements':rows,
        'information_gaps':[f"{r['module']}：{r['question']}尚未形成口径和原文定位完整的事实 [需求:{r['requirement_id']}]"
                            for r in rows if r['status']!='verified']}


def diverse_evidence(candidates: list[dict], requirements: list[dict], limit: int = 12) -> list[dict]:
    """Keep metric coverage and distinct documents before filling remaining relevance slots."""
    from industry_research import source_document_key
    remaining = list(candidates); selected=[]; covered=set(); documents=set()
    metrics={id(f):set(fact_requirement_ids(f,requirements,True)) for f in remaining}
    while remaining and len(selected)<limit:
        def rank(pair):
            index,fact=pair
            reqs=metrics[id(fact)]
            document=source_document_key(fact.get('source_url',''))
            return (bool(reqs-covered),bool(document and document not in documents),-index)
        index,fact=max(enumerate(remaining),key=rank)
        remaining.pop(index);selected.append(fact)
        covered.update(metrics[id(fact)])
        documents.add(source_document_key(fact.get('source_url','')))
    return selected


def claim_ledger(report: str, facts: list[dict], diagnostic: dict, coverage: dict, dependencies: dict) -> dict:
    """Record citations, raw locators and checks, without claiming semantic entailment."""
    from industry_research import numeric_mentions, numeric_supported, claim_semantic_issues
    by_id={f.get('evidence_id'):f for f in facts if f.get('evidence_id')}
    chapters=diagnostic.get('chapter_evidence_ids') or {};all_ids=set(diagnostic.get('evidence_ids') or [])
    chapter=0;claims=[]
    for line_number,line in enumerate(report.splitlines(),1):
        heading=re.match(r'^##\s*(\d+)[.、．]',line)
        if heading:chapter=int(heading[1]);continue
        if chapter not in range(1,15) or not line.strip() or line.lstrip().startswith(('#','!','>','| ---')):continue
        ids=set(re.findall(r'\bE-[A-Z0-9-]{6,}\b',line,re.I))
        if not ids and len(re.sub(r'\s+','',line))<60:continue
        allowed=all_ids if chapter in {1,14} else set(chapters.get(chapter,chapters.get(str(chapter),[])))
        cards=[by_id[eid] for eid in sorted(ids) if eid in allowed and eid in by_id]
        issues=[]
        if not ids:issues.append('no_citation')
        if ids-allowed or ids-set(by_id):issues.append('invalid_citation')
        if any((f.get('provenance') or {}).get('locator',{}).get('status')!='verified' for f in cards):issues.append('unlocated_source_quote')
        numeric={f['evidence_id']:{'context':f.get('numeric_context') or {},'validation':f.get('numeric_validation') or {}} for f in cards}
        if any(not any(numeric_supported(n,eid,numeric) for eid in numeric) for n in numeric_mentions(line)):issues.append('unverified_number')
        issues.extend(i['code'] for i in claim_semantic_issues(line,cards))
        key=json.dumps([chapter,line,sorted(ids)],ensure_ascii=False)
        claims.append({'claim_id':'C-'+hashlib.sha256(key.encode()).hexdigest()[:16].upper(),
            'chapter':chapter,'line_number':line_number,'text':line[:1600],'text_truncated':len(line)>1600,
            'evidence_ids':sorted(ids),'reference_status':'requires_review' if issues else 'references_verified',
            'entailment_status':'not_evaluated','issues':list(dict.fromkeys(issues)),
            'source_locators':[{'evidence_id':f['evidence_id'],**(f.get('provenance') or {}).get('locator',{})} for f in cards]})
    return {'version':VERSION,'dependencies':dependencies,'coverage':coverage,'claims':claims,
        'summary':{'claim_count':len(claims),'requires_review_count':sum(c['reference_status']=='requires_review' for c in claims),
                   'entailment_review_required':True},
        'limitations':['references_verified confirms traceability and deterministic checks only, not full semantic support.',
                       'A missing metric is a research gap, not evidence of high risk.']}
