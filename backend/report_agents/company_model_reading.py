"""Complete native candidates and semantic routing for the chapter workflow.

No content word, publisher category, field length or publication date is an
admission rule. Offsets and hashes bind model selections to this task's bytes.
"""
from bisect import bisect_right
import hashlib
import re
from .company_evidence import source_body
from .company_governance import get
from .company_source_review import TOPICS, BOUNDARIES, evidence_id, provenance, document_date_proof
from .company_text import match_text

VERSION='company-model-native-reading-v3-bound-context-subspans'


def canonical_chapter(value):
    if type(value) is int:return value if value in TOPICS else None
    if not isinstance(value,str):return None
    text=value.strip().lower()
    chinese={'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,'十一':11}
    if text.startswith('第') and text.endswith(('章','节')) and text[1:-1] in chinese:return chinese[text[1:-1]]
    m=re.fullmatch(r'(?:company[. _-]ch|ch(?:apter)?[. _-]?|第)?0?(\d{1,2})(?:[.、．]|章|节)?',text)
    return int(m[1]) if m and int(m[1]) in TOPICS else None


def native_spans(raw,limit=3600):
    # Group short labels with neighboring native context, never discard them.
    # Long blocks split on real lines. The union covers the entire original.
    paragraphs=list(re.finditer(r'[\s\S]+?(?:\n[ \t]*\n|\Z)',raw))
    left=0;right=0
    for block in paragraphs:
        if right>left and right-left>=240:
            yield left,right;left=right
        end=block.end()
        while end-left>limit:
            edge=raw.rfind('\n',left+limit//2,left+limit)
            edge=edge+1 if edge>=0 else left+limit
            yield left,edge;left=edge
        right=end
    if right<len(raw):right=len(raw)
    if right>left:yield left,right


def prepare_model_corpus(project,*,context=None):
    from .company_corpus import source_input_fingerprint, platform_source
    from company_flow_state import fingerprint
    aliases,identity=context or ([],{})
    documents=[];states={}
    project_id=get(project,'id',None)
    intake=getattr(project,'company_research_intake',{}) or {}
    for source in project.sources or []:
        sid=str(get(source,'id',get(source,'url')));raw,origin=source_body(source)
        meta=get(source,'source_metadata',{}) or {};eid=evidence_id(source)
        kind,binding=provenance(source,project.target_name,identity)
        platform=platform_source(source)
        kind='professional_platform_record' if platform else kind or 'attributed_publication'
        proof=document_date_proof(source)
        from .company_time_context import publication_context
        timing=publication_context(source,intake.get('as_of_date',''))
        publication=timing['publication_date']
        historical=timing['post_cutoff_disclosure']
        state={'evidence_id':eid,'native_evidence_id':eid,'source_input_sha256':source_input_fingerprint(source),
            'original_sha256':hashlib.sha256(raw.encode()).hexdigest(),'text_origin':origin,
            'source_kind':kind,'professional_platform':platform,'scanned_chars':len(raw),
            'candidate_windows':0,'review_windows':0,'reviewed_windows':0,'accepted_claims':0,
            'review_decisions':[],'validation_rejections':[],'coverage_ranges':[],
            'unread_ranges':[[0,len(raw)]] if raw else [],'state':'pending_model_reading',
            'publication_date':publication,'post_cutoff_disclosure':historical,
            'reading_scope':'native_chunks_not_yet_read','report_chapter_scope':list(TOPICS),'structural_gaps':[]}
        states[sid]=state
        if project_id is not None and get(source,'project_id',project_id) not in {None,project_id}:
            state['state']='foreign_task_source';continue
        if not raw:
            state['state']='empty_original';continue
        if origin=='discovery_summary':
            state['state']='original_not_available_discovery_only';continue
        windows=[];pages=list(re.finditer(r'--- PDF page (\d+) ---',raw))
        headings=list(re.finditer(r'(?m)^(?:#{1,6}\s+|第[^\n]{1,12}[章节节]|[一二三四五六七八九十]+[、．.])[^\n]{0,120}$',raw))
        # Short documents keep their whole original, including bare zero/unknown.
        spans=list(native_spans(raw))
        for index,(start,end) in enumerate(spans):
            quote=raw[start:end]
            normal=match_text(quote)
            priority=[n for n,pattern in TOPICS.items() if re.search(pattern,normal,re.I)]
            page=bisect_right([p.start() for p in pages],start)-1
            heading=bisect_right([h.start() for h in headings],start)-1
            left=max(0,start-1800);right=min(len(raw),end+1800)
            windows.append({'window_id':'W'+str(index+1),'quote':quote,'start':start,'end':end,
                'candidate_chapters':priority+[n for n in TOPICS if n not in priority],
                'priority_chapters':priority,'context_quote':raw[left:right],
                'context_start':left,'context_end':right,'physical_page':int(pages[page][1]) if page>=0 else None,
                'native_context_sha256':fingerprint([state['original_sha256'],left,right,raw[left:right]]),
                'heading':headings[heading][0] if heading>=0 else '',
                'subject_reference':'model_scope_required','partial_structure':len(spans)>1,
                'native_window_sha256':fingerprint([state['original_sha256'],start,end,quote])})
        state.update(candidate_windows=len(windows),review_windows=len(windows))
        binding={**binding,'disclosed_aliases':aliases,'entity_validation':meta.get('entity_validation','unknown'),
            'issuer_document':kind=='issuer_disclosure'}
        documents.append({'evidence_id':eid,'source_id':sid,'source_url':str(get(source,'url')),
            'source_title':str(get(source,'title')),'source_kind':kind,'subject_binding':binding,
            'document_date_proof':proof,'windows':windows,'model_reading_mode':VERSION,
            'original_sha256':state['original_sha256'],'native_chars':len(raw),'project_id':project_id,
            'time_context':{**timing,'event_date':'unknown','accounting_period':'unknown'},
            'collection_failure':meta.get('collection_failure',''),
            'platform_context':{key:meta.get(key) for key in ('provider','tool','query','target','raw_response_key','retrieved_at')}
                if platform else {}})
    return documents,states,[]


def validate_model_selection(row,doc,target,as_of=''):
    from company_flow_state import fingerprint
    if doc.get('collection_failure'):return None,'platform_collection_gap_not_company_fact'
    window=next((w for w in doc['windows'] if w['window_id']==str(row.get('window_id') or '')),None)
    if window is None:return None,'unknown_window'
    chapter=canonical_chapter(row.get('chapter'))
    if chapter is None:return None,'invalid_chapter'
    original=window['quote'];window_start=window['start'];window_end=window.get('end',window_start+len(original))
    if not original or window_end-window_start!=len(original):return None,'invalid_native_offset'
    if fingerprint([doc['original_sha256'],window_start,window_end,original])!=window.get('native_window_sha256'):
        return None,'native_window_hash_mismatch'
    quote=original;start=window_start;end=window_end;literal_corrections=[]
    if row.get('quote') is not None:
        proposed=row['quote']
        if not isinstance(proposed,str) or not proposed.strip():return None,'nonliteral_quote'
        position=original.find(proposed)
        if position<0 and window.get('native_context_sha256'):
            context=window.get('context_quote','');left=window.get('context_start');right=window.get('context_end')
            if type(left) is not int or type(right) is not int or right-left!=len(context) or fingerprint([doc['original_sha256'],left,right,context])!=window['native_context_sha256']:
                return None,'native_context_hash_mismatch'
            if context[window_start-left:window_end-left]!=original:return None,'native_context_window_mismatch'
            if proposed in context:
                original=context;window_start=left;window_end=right;position=context.find(proposed)
                literal_corrections.append({'field':'window_id','reason':'exact_bound_native_neighbor_subspan'})
        if position<0:
            # Only unambiguous whitespace differences may restore an exact
            # native span. No fuzzy semantic matching or rewritten quotation.
            positions=[i for i,c in enumerate(original) if not c.isspace()]
            compact=''.join(original[i] for i in positions);needle=''.join(proposed.split())
            position=compact.find(needle)
            if not needle or position<0 or compact.find(needle,position+1)>=0:return None,'nonliteral_quote'
            left=positions[position];right=positions[position+len(needle)-1]+1
            quote=original[left:right];position=left
            literal_corrections.append({'field':'quote','reason':'unique_native_whitespace_restoration'})
        else:
            if original.find(proposed,position+1)>=0:
                absolute=row.get('quote_start')
                if type(absolute) is not int or original[absolute-window_start:absolute-window_start+len(proposed)]!=proposed:
                    return None,'ambiguous_native_quote_offset'
                position=absolute-window_start
            quote=proposed
        start=window_start+position;end=start+len(quote)
    scope=row.get('scope')
    if scope not in {'target','group','service_joint','third_party_about_target','industry_context'}:return None,'unbound_scope'
    relevance=str(row.get('relevance') or '').strip()
    if not relevance:return None,'missing_relevance'
    binding=doc.get('subject_binding') or {};corrections=list(literal_corrections)
    if binding.get('entity_validation') in {'rejected','ambiguous','related_entity_context'} and scope=='target':
        return None,'target_scope_requires_entity_clarification'
    # Neither a brand nor a known publisher implies the legal scope. A model
    # must state its basis when claiming a single legal entity absent its name.
    if scope=='target' and match_text(target) not in match_text(quote+' '+window.get('context_quote','')) and not binding.get('issuer_document'):
        if not str(row.get('subject_basis') or '').strip():return None,'target_scope_requires_entity_clarification'
    if row.get('chapter')!=chapter:corrections.append({'field':'chapter','proposed':row.get('chapter'),'accepted':chapter,'reason':'canonical_chapter_encoding'})
    time_context=doc.get('time_context',{})
    boundary=BOUNDARIES[doc['source_kind']]
    if time_context.get('post_cutoff_disclosure'):
        boundary+='；事后披露：不得表示历史截至日已知，事件日与会计期仍按原文分别核对。'
    if doc['source_kind']=='professional_platform_record':
        boundary+='；仅为平台所载字段；计数不证明败诉/责任，零值与未知保留原状，失败是采集缺口。'
    return {'kind':'reviewed_original_statement','chapter':chapter,'fact':quote,'evidence_quote':quote,
        'evidence_id':doc['evidence_id'],'evidence_ids':[doc['evidence_id']],
        'source_id':doc['source_id'],'source_url':doc['source_url'],'source_title':doc['source_title'],
        'source_kind':doc['source_kind'],'subject_binding':binding,'scope':scope,'relevance':relevance,
        'subject_basis':str(row.get('subject_basis') or ''),'period':'事实时点及期间见原文；披露日不等于事件日',
        'time_context':time_context,'document_date_proof':doc.get('document_date_proof',{}),
        'context_quote':window.get('context_quote',''),'original_page_context':window.get('original_page_context'),
        'original_offset':start,'original_end':end,
        'original_sha256':doc['original_sha256'],'selection_corrections':corrections,'model_reading_mode':doc['model_reading_mode'],
        'eligible_for_risk_scoring':False,'boundary':boundary},''
