"""Question contribution and source identity, separate from evidence truth.

These narrow checks catch known non-answers. Passing is not semantic proof.
Attribution context never licenses additional numbers or source assertions.
"""
import re

VERSION = 'industry-answer-contract-v1-context-and-contribution'
ALIAS = re.compile(r'(?<![A-Za-z0-9_])F\d+(?![A-Za-z0-9_])')


def complete_finding(text):
    """A short finding can explain an implication in 1-3 complete sentences."""
    # Count sentence boundaries outside attributed document titles. Identity,
    # number and markup authorization are checked independently against cards.
    if not isinstance(text,str) or not 12<=len(text)<=300:
        return False
    shape=re.sub(r'《[^《》\n]*》','所引文件',text)
    return bool(re.fullmatch(r'(?:[^。！？\n]+[。！？]){1,3}',shape))


def source_identity(fact):
    meta = fact.get('source_metadata') or {}
    return {k: str(v)[:240] for k, v in {
        'document_title': fact.get('source_title'),
        'publisher': fact.get('publisher') or meta.get('publisher'),
        'published_date': fact.get('published_date') or meta.get('published_date') or meta.get('published_at'),
        'subject': fact.get('company_name') or fact.get('subject_name') or fact.get('industry_name'),
        'segment': fact.get('segment_name'), 'evidence_scope': fact.get('evidence_scope'),
    }.items() if v}


def without_document_titles(text, facts):
    """A cited document's title is attribution, not an extra numeric claim."""
    for fact in facts:
        title=str(fact.get('source_title') or '').strip()
        if not title:continue
        labels={title,title[:27]+'…' if len(title)>28 else title}
        for label in labels:
            text=text.replace('《'+label+'》','所引文件')
    return text


def writer_card(ref, fact):
    contract = fact['fact_contract']
    row = {'ref': ref, 'statement': contract['statement'], 'identity': source_identity(fact),
            'identity_use': 'attribution_only_not_additional_claim_authorization',
            'sample_boundary': contract.get('sample_boundary'), 'material_kind': contract.get('material_kind'),
            'source_role': contract.get('source_role'),
            'authorized_metric': fact.get('numeric_context') if (fact.get('numeric_validation') or {}).get('passed') is True else None}
    quote = fact.get('evidence_quote')
    if (isinstance(quote,str) and quote!=contract['statement'] and len(quote)<=900
            and fact.get('provenance',{}).get('locator',{}).get('status')=='verified'):
        row['original_context'] = quote
        row['context_use'] = 'attribution_and_conditions_only_not_extra_metrics_or_assertions'
    return row


def expand_aliases(value, packet, selected):
    """Only aliases actually cited by this answer may be rendered as source names."""
    if not isinstance(value, str):
        return value
    def label(match):
        alias = match[0]
        if alias not in selected:
            raise ValueError('uncited_alias_in_analysis')
        fact = packet['_facts'][packet['_refs'][alias]]
        title = str(fact.get('source_title') or '').strip()
        if not title:
            raise ValueError('unresolved_source_alias')
        # Full source title and URL remain in the source index.
        return '《' + (title[:27]+'…' if len(title)>28 else title) + '》'
    def span(match):
        first, last = int(match[1]), int(match[2])
        if not 0 <= last-first <= 7:
            raise ValueError('uncited_alias_in_analysis')
        return '、'.join('F'+str(n) for n in range(first,last+1))
    value = re.sub(r'F(\d+)\s*(?:至|到|—|–|-)\s*F(\d+)',span,value)
    return ALIAS.sub(label,value)


def same_premises(claim, old_cards, current_cards):
    refs = claim.get('evidence_ids', [])
    def projection(fact):
        row = {k:fact.get(k) for k in ('fact_contract','numeric_context','numeric_validation',
                'source_title','source_url','evidence_scope','eligible_for_report','scope_match')}
        # Writer projections omit only the duplicated locator quote; its SHA,
        # offsets, source ID and the exact licensed statement must still match.
        provenance = fact.get('provenance') or {}
        row['provenance'] = {**provenance,'locator':{k:v for k,v in (provenance.get('locator') or {}).items() if k!='quote'}}
        return row
    return bool(refs) and all(eid in old_cards and eid in current_cards
        and projection(old_cards[eid])==projection(current_cards[eid]) for eid in refs)


def contribution_issue(claim):
    """Specific negative answers stay valid; a generic disclaimer is not a finding."""
    conclusion = str(claim.get('conclusion') or '').strip()
    question = str(claim.get('question') or '')
    if not conclusion:
        return 'missing_finding'
    if claim.get('claim_kind') == 'limitation':
        return 'scope_only_answer'
    # A concrete implication or comparison is allowed even with qualifications.
    implication = re.search(r'取决于|关键在于|关键是|依赖|应优先|应分别|应按|需分别|需要区分|'
                            r'决定了|影响.{0,12}(?:选择|成本|交付)|(?:收入|成本).{0,12}(?:挂钩|随.{0,8}变化)|'
                            r'云端.{0,16}(?:吞吐|算力).{0,35}端侧.{0,16}(?:能效|成本)', conclusion)
    if implication:
        return None
    # A factual allocation, duty or deployment distinction is already a usable
    # answer. A qualification later in the sentence must not erase it.
    before_boundary = re.split(r'但|不过|然而|不能据此|尚不能|不足以',conclusion,1)[0]
    if re.search(r'上游.{0,20}(?:提供|供给).{0,35}(?:中游|下游)|'
                 r'(?:职责|责任|义务).{0,15}(?:由|赋予|承担|属于)|'
                 r'(?:云端|端侧|边缘端).{0,15}(?:侧重|面向|适用于)',before_boundary):
        return None
    if re.search(r'各有(?:适用前提|特点|优势)|不能仅凭.{0,20}判定优劣', conclusion):
        return 'generic_comparison_without_criteria'
    if re.search(r'仅能确认|只能确认|仅凭|不足以|尚不能|不能据此|无法判断|不能确认', conclusion):
        # A question about comparability can be answered by an explicit mismatch.
        specific_negative = re.search(r'口径|可比|适用范围|差异', question) and re.search(
            r'(?:地域|币种|期间|定义|分母|对象|市场).{0,10}(?:不同|不一致)|不属于|不适用于', conclusion)
        if not specific_negative:
            return 'scope_only_answer'
    if question == '适用政策原文' and re.search(r'材料未|尚缺|待补|条款出处|文件名称',conclusion):
        return 'scope_only_answer'
    if re.fullmatch(r'(?:本章|所引|现有|上述|这些).{0,100}(?:尚待|仍需|需要).{0,8}(?:复核|核验|研究|分析)[。！]?',conclusion):
        return 'only_review_notice'
    return None


def quality_feedback(issue):
    return {
        'scope_only_answer':'上一稿仅说明材料或判断范围。请用已给前提回答成立的业务关系、适用场景或具体责任，再解释影响；确实缺少前提则弃答，不改写成另一段限制说明。',
        'generic_comparison_without_criteria':'请区分服务、产品和架构的层次，明确各自解决什么问题、在哪些条件下适用；不把不同层次对象统一排名，也不以各有前提作为结论。',
        'only_review_notice':'上一稿只有复核提示。请回答原问题，给出已知信息之间的实际联系；没有可用前提则返回具体缺口。',
        'missing_finding':'请先给出一句完整的实际判断，再说明现有依据与成立条件。',
    }.get(issue,'')


def search_outcome(audit, result_count):
    states = (audit or {}).get('engine_states', {})
    if result_count:
        return {'status':'returned','result_count':result_count}
    if any(v.get('status')=='returned' for v in states.values()):
        return {'status':'no_hits','result_count':0}
    blocked = {k:{f:v[f] for f in ('status','reason','http_status') if f in v}
               for k,v in states.items() if v.get('status') in {'failed','not_queried','not_configured'}}
    return {'status':'provider_unavailable' if states else 'empty_unverified',
            'result_count':0, 'providers':blocked}
