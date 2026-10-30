"""Tolerate harmless presentation differences; keep evidence permissions exact."""
from copy import deepcopy
from difflib import SequenceMatcher
import re

CLAIM_FIELDS = {'question','conclusion','text','evidence_ids','premises','claim_kind','reasoning'}
AUDIT_FIELDS = {'answer_quality_warning','development_warning','partial_answer','partial_parent_claim_id','support_review','source_observation_only'}
MAX_UNITS = 3


def _actual_payment_clauses(value):
    """Read stated transactions separately from conditional/future continuations.

    Once a sentence introduces a scenario, its comma-separated consequences do
    not establish actual payment. Earlier actual clauses stay available, and the
    next sentence starts a fresh scope. This only guides the payment-question
    completion flag; it never edits or removes the reader's draft.
    """
    scenario = (r'如果|假如|假设|假定|设想|倘若|一旦|只要|只有|除非|若(?!干)|'
                r'当.{1,40}时|在.{1,40}(?:条件下|情景下|情况下|假设下|前提下)|以.{1,40}(?:为前提|为假设)|'
                r'预计|未来|计划(?:于|在|采用|按|向|提供|收取|收费|推出|购买|支付|订阅|采购)|'
                r'拟(?:于|在|采用|收费|订阅|采购|购买|支付|推出|定价)|'
                r'将(?:于|在|会|要|采用|按|收费|推出|开始|进行|购买|支付|收取)|'
                r'建议|应(?:当|该|优先|考虑|采用|按|向|收取|收费|提供)|'
                r'可(?:以|考虑|采用|向|通过|按|提供|收取|收费)|有望|可能')
    negative = (r'未说明|未披露|尚无|尚未|没有|均未|而非|并非|假设|待验证|可作为|'
                r'不能(?:证明|作为|据此|判断)|不作为|'
                r'(?:未(?:曾|有|实际)?|不曾|并未|从未|未必|不一定|不)(?:实际)?(?:采用|支付|付费|采购|订阅|购买|收费|收取)')
    for sentence in re.split(r'[。！？；;\n]', str(value or '')):
        scoped = False
        for clause in re.split(r'[，,]', sentence):
            marker = None
            for candidate in re.finditer(scenario,clause):
                # A temporal-looking token inside an explicit company/group
                # name is a subject label, not a forecast. Other scenario
                # markers (e.g. an earlier 如果) still govern the sentence.
                name=re.match(r'未来[\u4e00-\u9fffA-Za-z0-9·&]{0,24}(?:公司|集团)',clause[candidate.start():])
                if (candidate.group()=='未来' and name and not re.search(
                        r'采用|购买|采购|收费|订阅|客户|企业|计划|预计|可能|将会|这类|相关',name.group()[2:])):
                    continue
                marker=candidate
                break
            prefix = clause[:marker.start()] if marker else clause
            if marker and marker.group() in {'假设','设想'} and re.search(r'(?:的|这一|只是|仅是|仅为|是一个|作为)$',prefix):
                prefix = ''
            if not scoped and prefix and not re.search(negative, prefix):
                yield prefix
            scoped = scoped or marker is not None


def question_alignment_issue(claim):
    """Known wrong-question answers remain readable drafts, never completed jobs."""
    question = claim.get('question', '')
    body = str(claim.get('conclusion') or '') + str(claim.get('text') or '')
    if question == '实际收费与付费客户':
        # A margin, revenue total or hypothetical pricing option does not identify
        # an actual transaction. This flag asks for revision, not text removal.
        positive = [c for field in ('conclusion', 'text') for c in _actual_payment_clauses(claim.get(field))]
        actual = any(re.search(r'(?:实际|已|正在|目前|现行).{0,12}(?:采用|收费|支付|付费|采购|订阅|购买)|'
                              r'(?:客户|用户|企业).{0,12}(?:支付|购买|采购|订阅)|'
                              r'(?:收费|售价|定价|价格|订阅费|套餐|服务费).{0,12}\d+(?:\.\d+)?\s*(?:元|美元|人民币|美金|/次|/月|/年)', c)
                     for c in positive)
        if not actual:
            return 'actual_payment_not_answered'
    if question in {'商业化里程碑与终端需求', '传播或关注度数据'}:
        policy_dates = re.search(r'施行|公布|发布|审议通过', body)
        demand = re.search(r'订单|付费|销售|采购|客户|用户|渗透|使用量|调用量|搜索量|关注度|传播量|阅读量|融资', body)
        if policy_dates and not demand:
            return 'policy_dates_not_demand_evidence'
    return None


def alignment_feedback(issue):
    return {
        'analysis_not_developed': '上一稿保留了具体判断，但分析没有展开。请用本题已有原文说明判断的依据联系、作用对象、实际业务含义及成立条件；风险题区分触发情景和条件性影响。不重新检索，不重复小结或用缺口清单凑字数。',
        'actual_payment_not_answered': '本题问实际收费与付费客户。上一稿只给样本毛利、财务表现或假设计费选项，不能作为本题已回答。请核对已给材料中的实际采用主体、客户及交易/收费安排；有哪个就明确哪个，缺少的列具体缺口。原有毛利分析可保留在盈利问题，不重复充当收费答案。',
        'policy_dates_not_demand_evidence': '上一稿仅列政策发布或施行日期，没有回答商业化需求或传播关注度。请按本题已有订单、使用或传播材料作有限判断；若没有，不把日期节点解释为热度成因，明确所缺指标。',
    }.get(issue, '')


def _draft_signature(claim):
    body = re.sub(r'\s+|\[?E-[0-9A-Fa-f]{12}\]?', '', str(claim.get('text') or ''))
    body = re.sub(r'《[^《\n]*?》(?:[，,]\d{4}[./年]\d{1,2}(?:[./月]\d{1,2})?》)?', '', body)
    finding = re.sub(r'\s+', '', str(claim.get('conclusion') or ''))
    # Shared citations can discuss different periods, subjects or geographic
    # scopes. Never fold those distinct observations together just by similarity.
    numbers = tuple(sorted(set(re.findall(r'[-−]?\d+(?:[.,]\d+)*\s*(?:%|％)?', body))))
    scopes = tuple(sorted(set(re.findall(r'中国大陆|全球|美国|欧洲|中国|日本|英国|深圳|上海', body))))
    subjects = tuple(sorted(set(re.findall(r'[A-Za-z甲乙丙丁]+(?:公司|企业)|华为|英伟达|百度|阿里云|腾讯|'
                                          r'[A-Za-z][A-Za-z0-9._+-]{1,30}', body))))
    nature=(bool(re.search(r'预测|预计|目标期|情景',finding)),bool(re.match(r'若|如果|假设|在.{1,25}条件下',finding)))
    return body, finding, numbers, scopes, subjects, nature


def _same_judgment(left, right):
    if left.get('question') != right.get('question') or set(left.get('evidence_ids', [])) != set(right.get('evidence_ids', [])):
        return False
    a, af, *anchors_a = _draft_signature(left)
    b, bf, *anchors_b = _draft_signature(right)
    if a == b:
        return True
    if not a or not b or anchors_a != anchors_b:
        return False
    # A repeated attribution-only sentence adds no second judgment to a longer
    # current analysis using the same question and exact evidence permission.
    def attribution_only(c):
        text=str(c.get('text') or '')
        return len(text)<100 and bool(re.match(r'该(?:陈述|材料|表述)(?:为|是|属于)',text)
            and re.search(r'来源观点|非事实认定|关联假设',text))
    if attribution_only(left) != attribution_only(right):
        return True
    if min(len(a), len(b)) >= 24 and (a in b or b in a):
        return True
    matcher=SequenceMatcher(None,a,b,autojunk=False)
    # Small replacements near the subject position may be names absent from
    # simple entity fields; conservatively keep both rather than lose a subject.
    connectors={'因此','所以','据此','由此','意味着','同时','此外','以及','其中','但是','不过','然而'}
    def framing(value):
        return bool(re.fullmatch(r'(?:但|这|只|是|仅|反映|该|表示|说明|仍|而|在|所|本|样本)+',value))
    if any(tag=='replace' and i<40 and 2<=j-i<=12 and 2<=l-k<=12 and not {a[i:j],b[k:l]}<=connectors
           and not (framing(a[i:j]) and framing(b[k:l]))
           for tag,i,j,k,l in matcher.get_opcodes()):
        return False
    body_ratio = matcher.ratio()
    finding_ratio = SequenceMatcher(None, af, bf, autojunk=False).ratio() if af and bf else 0
    def metric_focus(text):
        head=re.split(r'但|不能|不足以|仅反映|因此|所以|意味着',text,1)[0]
        return set(re.findall(r'毛利率|收入|成本|现金流|市场规模|份额|渗透率|同比|增速|吞吐|延迟|能效',head))
    same_numeric_point=(bool(anchors_a[0]) and metric_focus(af) and metric_focus(af)==metric_focus(bf))
    return body_ratio >= .86 or finding_ratio >= .92 or (body_ratio >= .70 and finding_ratio >= .70 and same_numeric_point)


def _draft_rank(claim):
    verdict = claim.get('support_review') or {}
    status = verdict.get('status')
    review = (4 if status == 'supported' and verdict.get('answer_quality') == 'answered' else
              3 if status == 'supported' else 0 if status in {'unsupported', 'contradicted'} else 1)
    substantive = not (question_alignment_issue(claim) or claim.get('source_observation_only') or claim.get('partial_parent_claim_id')
                       or claim.get('answer_quality_warning') or claim.get('development_warning') or claim.get('partial_answer'))
    return review, int(substantive), min(len(str(claim.get('text') or '')), 1200)


def consolidate_drafts(previous, proposed=(), *, final=False):
    """One current draft per repeated judgment, preserving distinct siblings.

    Before review, one best old fallback and one new candidate may coexist so a
    failed revision cannot destroy supported content. After review, select the
    strongest equivalent candidate; audit history lives outside reader prose.
    """
    groups = []
    for origin, claims in (('previous', previous), ('proposed', proposed)):
        for claim in claims:
            if not usable_analysis(claim):
                continue
            group = next((g for g in groups if any(_same_judgment(c, claim) for _, c in g)), None)
            if group is None:
                group = []; groups.append(group)
            group.append((origin, deepcopy(claim)))
    kept = []
    for group in groups:
        best = max(group, key=lambda item: _draft_rank(item[1]))[1]
        if final:
            kept.append(best)
            continue
        for origin in ('previous', 'proposed'):
            options = [c for source, c in group if source == origin]
            if not options:
                continue
            candidate = max(options, key=_draft_rank)
            if not any(c.get('question') == candidate.get('question') and c.get('text') == candidate.get('text')
                       and set(c.get('evidence_ids', [])) == set(candidate.get('evidence_ids', [])) for c in kept):
                kept.append(candidate)
    return kept


def current_revision_state(plan):
    """Keep historic attempts in audit, but expose only current unresolved work."""
    from industry_conclusion_recovery import finding_issue
    complete = {c.get('question') for c in plan.get('analysis_claims', [])
                if c.get('support_review', {}).get('status') == 'supported'
                and c.get('support_review', {}).get('answer_quality') == 'answered' and not finding_issue(c)}
    plan['resolved_questions'] = sorted(complete)
    plan['active_analysis_rejections'] = [r for r in plan.get('analysis_rejections', []) if r.get('question') not in complete]
    for row in plan.get('question_ledger', {}).get('questions', []):
        row['model_revision_complete'] = row.get('question') in complete
    return plan


def answer_envelope(value, diagnostic):
    diagnostic['container_type'] = type(value).__name__
    if isinstance(value,dict):
        known = {'answers','results','data','question_id','status','claims','conclusion','analysis','refs'}
        diagnostic['recognized_fields'] = sorted(set(value)&known)
        diagnostic['other_field_count'] = len(set(value)-known)
        containers = [k for k in ('answers','results','data') if isinstance(value.get(k),(list,dict))]
        if len(containers)>1:
            raise ValueError('ambiguous_question_response')
        if containers:
            selected=containers[0]
            if selected!='answers' or set(value)!={'answers'}:
                diagnostic.setdefault('normalizations',[]).append('response_envelope_normalized')
            inner=value[selected]
            if isinstance(inner,dict) and 'question_id' not in inner:
                return answer_envelope(inner,diagnostic)
            value=inner
        elif 'question_id' in value:
            diagnostic.setdefault('normalizations',[]).append('single_answer_wrapped')
            value=[value]
    if isinstance(value,dict) and 'question_id' in value:value=[value]
    if not isinstance(value,list):raise ValueError('invalid_question_response')
    if len(value)>8:raise ValueError('question_response_too_many_items')
    return value


def normalize_answer(answer, packet, question):
    """Aliases select the same explicit fields/refs; no guessed evidence or text."""
    if not isinstance(answer,dict):raise ValueError('invalid_question_answer_or_references')
    result={'question_id':answer.get('question_id')}
    aliases={'conclusion':('conclusion','summary'),'analysis':('analysis','text'),
             'kind':('kind','claim_kind'),'refs':('refs','evidence_ids')}
    for target,names in aliases.items():
        values=[answer[k] for k in names if k in answer]
        if len(values)>1 and any(v!=values[0] for v in values[1:]):
            raise ValueError('conflicting_answer_fields')
        if values:result[target]=values[0]
    status=answer.get('status')
    if status=='insufficient':
        return {**result,'status':status,'reason':answer.get('reason')}
    result['status']=status if status is not None else 'answered'
    if 'kind' not in result:result['kind']='conditional'
    refs=result.get('refs')
    if isinstance(refs,str) and re.fullmatch(r'(?:F\d+|E-[A-Fa-f0-9]{12})(?:\s*[,，;；、]\s*(?:F\d+|E-[A-Fa-f0-9]{12}))*',refs):
        refs=re.split(r'\s*[,，;；、]\s*',refs)
    if isinstance(refs,list):
        inverse={eid:alias for alias,eid in packet['_refs'].items()}
        refs=[inverse.get(ref,ref) if isinstance(ref,str) else ref for ref in refs]
        if all(isinstance(ref,str) for ref in refs):refs=list(dict.fromkeys(refs))
    result['refs']=refs
    return result


def usable_analysis(claim):
    """Retained draft can still need a better answer; a notice alone is not prose."""
    from industry_answer_quality import contribution_issue
    return bool(claim.get('text')) and (claim.get('source_observation_only') or claim.get('partial_parent_claim_id')
        or contribution_issue(claim) not in {'missing_finding','only_review_notice'})


def preserve_audit(accepted, originals):
    for claim in accepted:
        old=next((c for c in originals if c.get('question')==claim.get('question')
            and c.get('text')==claim.get('text') and c.get('evidence_ids')==claim.get('evidence_ids')),None)
        if old:
            for field in AUDIT_FIELDS:
                if field in old:claim[field]=deepcopy(old[field])


def merge_rejections(previous,current,updated_questions):
    # An unrelated pass must not erase the specific failure or its source text.
    return [deepcopy(r) for r in previous if r.get('question') not in updated_questions]+current


def supported_fragments(claim, verdict, package, chapter):
    """Only exact whole sentences explicitly approved by this review are usable."""
    from industry_fact_contracts import validate_analyses
    from industry_reasoning import claim_id
    body=claim.get('text','');sentences=re.split(r'(?<=[。！？])',body)
    kept=[]
    for fragment in verdict.get('supported_fragments',[]):
        text=fragment['text'];refs=fragment['evidence_ids']
        if text not in sentences:continue
        candidate={k:v for k,v in claim.items() if k in CLAIM_FIELDS}
        candidate.update(text=text,conclusion=text if 12<=len(text)<=110 else '',evidence_ids=refs,
                         reasoning='保留本次支持复核明确认可的原稿完整句子；未补写被拒绝的推断。')
        candidate.pop('premises',None)
        valid,_=validate_analyses([candidate],package,chapter,refs)
        if not valid:continue
        item=valid[0]
        item.update(partial_answer=True,partial_parent_claim_id=claim_id(claim,chapter),
            support_review={**{k:v for k,v in verdict.items() if k not in {'supported_fragments','claim_fingerprint'}},
                'status':'supported','method':'model_reviewed_exact_fragment',
                'reason':'本次复核明确认可此原稿句子；原段其余内容未获得支持。',
                'answer_quality':'scope_only','human_review_required':True,'entailment_proven':False})
        kept.append(item)
    return kept


def source_observations(package, chapter, ids):
    """Readable output while analysis is revised; never rename extracts as analysis."""
    from industry_fact_contracts import chapter_coverage,validate_analyses
    from industry_research import risk_fact_text
    from industry_question_generation import outline_only
    cards={f['evidence_id']:f for f in package.get('facts',[]) if f.get('evidence_id') in ids}
    kept=[];seen=set()
    for question in chapter_coverage(package,chapter,ids):
        candidates=question['evidence_ids'] or question.get('background_evidence_ids',[])
        for eid in candidates:
            f=cards.get(eid)
            if not f or eid in seen or outline_only(f['fact_contract']['statement']):continue
            body=risk_fact_text(f).strip()
            if not body or len(body)>1200:continue
            if f['fact_contract'].get('sample_boundary') and '样本' not in body:
                body='样本观察（不能外推行业整体）：'+body
            if not question['evidence_ids']:body='仅作背景材料观察：'+body
            if body[-1] not in '。！？':body+='。'
            candidate={'question':question['question'],'text':body,'claim_kind':'observation','evidence_ids':[eid],
                'reasoning':'按本轮准入原文保留来源观察；综合分析与业务推论仍需修订。'}
            valid,_=validate_analyses([candidate],package,chapter,ids)
            if not valid:continue
            item=valid[0]
            item.update(source_observation_only=True,partial_answer=True,
                support_review={'status':'not_evaluated','method':'exact_source_observation',
                    'reason':'此处保留来源观察，未认定综合分析已完成。','human_review_required':True,'entailment_proven':False})
            kept.append(item);seen.add(eid);break
        if len(kept)>=2:break
    return kept
