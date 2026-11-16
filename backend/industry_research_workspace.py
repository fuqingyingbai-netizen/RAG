"""An offline workspace over archived blocks and separately admitted evidence.

Raw recall is a candidate for normal verification, never a new authorized fact.
"""
import hashlib
import re
from copy import deepcopy
from industry_source_document import build_document, digest

VERSION = 'industry-research-workspace-v1-archive-before-search'


def archive_inventory(payload):
    """Build source structure once per body, without duplicating source text."""
    documents = {}
    for key, row in (payload.get('source_body_snapshots') or {}).items():
        body = row.get('content')
        if not isinstance(body, str) or not body or row.get('body_sha256') != digest(body):
            continue
        document = build_document(body)
        document.update(snapshot_key=key, source_url=row.get('source_url',''),
                        source_title=row.get('source_title',''))
        documents[key] = document
    return {'version': VERSION, 'documents': documents,
        'candidate_use': 'review_existing_original_then_apply_normal_admission',
        'search_scope': 'only_archived_snapshots_bound_to_this_cleaned_artifact'}


def _terms(question):
    synonyms = []
    for pattern, words in [
        ('预测|前景|趋势|情景', ['预测','预计','展望','情景','增长至','将从','市场规模']),
        ('收费|盈利|商业化', ['收费','订阅','付费','收入','成本','毛利']),
        ('测试|性能|技术|路线', ['测试','评测','延迟','吞吐','工具调用','硬件','单位成本']),
        ('政策|义务|标准|准入', ['应当','不得','实施','适用','规定','标准']),
        ('份额|竞争|集中度', ['份额','集中度','CR3','CR5','HHI','竞争'])]:
        if re.search(pattern, question):
            synonyms.extend(words)
    return list(dict.fromkeys(synonyms + re.findall(r'[A-Za-z]{2,}|[\u4e00-\u9fff]{2,6}', question)))


def recall(payload, question, scope=None, limit=3):
    """Recall uncompressed archived blocks and preserve why they need review."""
    workspace = payload.get('research_workspace') or archive_inventory(payload)
    from industry_source_quality import mentions_focus
    scope = scope or payload.get('industry_scope') or {}
    terms = _terms(question)
    rows = []
    forecast = bool(re.search('预测|前景|趋势|情景', question))
    for key, document in workspace.get('documents',{}).items():
        source = (payload.get('source_body_snapshots') or {}).get(key,{})
        body = source.get('content','')
        if digest(body) != document['body_sha256']:
            continue
        for block in document['blocks']:
            if block['kind'] == 'heading':
                continue
            text = body[block['start']:block['end']]
            # A general industry page may contain unrelated subsections. A
            # source title or another section's wording cannot establish focus
            # for this block or suppress collection for the requested segment.
            if not mentions_focus('\n'.join([*block['heading_path'], text]), scope):
                continue
            score = sum(1 for term in terms if term.casefold() in text.casefold())
            if score < 2:
                continue
            # Future targets improve retrieval ranking, never admission or
            # completion. An arbitrary monetary value such as2030亿元 is not a year.
            years = [int(y) for y in re.findall(r'(?<!\d)(20\d{2})\s*年',text)]
            cutoff = str(scope.get('as_of_date',''))[:4]
            target = max(years, default=0)
            if forecast and cutoff.isdigit() and target > int(cutoff):
                score += 2
            rows.append({'block_id': block['block_id'], 'document_id':document['document_id'],
                'snapshot_key':key, 'source_url':document['source_url'], 'source_title':document['source_title'],
                'start':block['start'],'end':block['end'],'heading_path':block['heading_path'],
                'text_sha256':block['text_sha256'],'target_years':sorted(set(years)),
                'relevance_score':score,'status':'candidate_requires_admission',
                'admitted_as_evidence':False})
    rows.sort(key=lambda row:(-row['relevance_score'],-max(row['target_years'],default=0),row['block_id']))
    return rows[:limit]


def question_material_scope(payload, question, refs=()):
    candidates = recall(payload, question)
    return {'version':VERSION,'scope':'this_run_archived_and_admitted_material_only',
        'admitted_reference_count':len(refs),'archive_candidates':candidates,
        'state':'existing_original_requires_review' if candidates else 'no_additional_archive_candidate_found',
        'not_selected_is_not_absent':True,'raw_candidates_do_not_authorize_claims':True}


def evidence_record(fact):
    """Stable source identity shared by chapters; no new semantic judgement."""
    locator=(fact.get('provenance') or {}).get('locator') or {}
    contract=fact.get('fact_contract') or {}
    binding={k:deepcopy(locator.get(k)) for k in ('body_sha256','start','end')}
    import json
    context= fact.get('source_document_context') or {}
    binding.update(statement_sha256=contract.get('statement_sha256') or digest(str(fact.get('fact') or '')),
                   quote_sha256=digest(locator['quote']) if locator.get('quote') else locator.get('quote_sha256'),
                   numeric_context=deepcopy(fact.get('numeric_context') or {}),
                   context_sha256=hashlib.sha256(json.dumps(context,sort_keys=True,ensure_ascii=False).encode()).hexdigest())
    key=hashlib.sha256(json.dumps(binding,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return {'record_id':'ER-'+key[:20], 'evidence_id':fact.get('evidence_id'),
        'binding':binding,'report_admitted':contract.get('report_admitted') is True,
        'semantic_status':'not_evaluated'}


def material_absence_issues(text, material_scope):
    if not material_scope or not material_scope.get('archive_candidates'):
        return []
    # Permit precise reports about checked inputs, never a corpus-wide absence
    # inferred from a writer packet while relevant originals are awaiting review.
    for sentence in re.split(r'[。！？\n]', text):
        broad = re.search(r'(?:现有|全部|所有|任何)(?:来源|材料|资料|公开资料)[^。！？]{0,25}(?:只|仅|没有|未提供|未披露|不存在)', sentence)
        if not broad:
            continue
        # A limitation in another sentence does not qualify this assertion.
        prefix = sentence[:broad.start()]
        if not re.search(r'(?:本题已核验|本轮已核验|当前选入|本题选入|所引且已核验)[^；;]{0,12}$',prefix):
            return ['archive_candidate_absence_overclaim']
    return []


def writer_material_scope(scope):
    """Keep raw-candidate provenance in the audit, not in the writer token budget."""
    if not scope:
        return {}
    return {**{k:scope[k] for k in ('version','scope','state','not_selected_is_not_absent',
        'raw_candidates_do_not_authorize_claims') if k in scope},
        'archive_candidates':[{'block_id':row['block_id'],'status':row['status']}
                              for row in scope.get('archive_candidates',[])]}
