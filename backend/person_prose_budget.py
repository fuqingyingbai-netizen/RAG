"""Length budgets apply to prose, never to the number of research sources."""
import json
import os
import re


def analysis_budget(chapter):
    return 300 if chapter == 1 else 600


def prose_chars(claims):
    return sum(len(str(c.get(field) or '').strip()) for c in claims
               if isinstance(c, dict) for field in ('analysis', 'review_analysis'))


def compact_draft(answer, role, prefix, writing_input, invoke, emit, audit, max_chars=None):
    """Measured compression of one candidate; source/semantic guards follow."""
    budget = analysis_budget(writing_input.get('chapter')) if max_chars is None else max_chars
    try:
        parsed = json.loads(re.sub(r'^```(?:json)?\s*|\s*```$', '', str(answer).strip()))
        claims = parsed.get('claims', []) if isinstance(parsed, dict) else []
    except (ValueError, TypeError):
        return answer, 0
    if not isinstance(claims, list) or prose_chars(claims) <= budget:
        return answer, 0
    target=max(1,budget-max(10,budget//20))
    audit['compression'] = {'status': 'requested', 'max_analysis_chars': budget,
                            'target_analysis_chars':target,'draft_chars': prose_chars(claims)}
    note = (f'本章分析合计不得超过{budget}字符（不含证据编号），不限制分析条数或来源数量。'
            '压缩目标预留计数余量，不是删去实质事项的许可，最终仍核对全部事实。'
            '请合并同一事项、删除重复和泛泛提醒，保留不同实质事项、来源归属、时期、条件、反例和矛盾。'
            '不能为缩短篇幅删去使结论成立的限定，不逐字截断句子。引用所有实际支撑合并结论的来源编号。'
            '若给出prior_draft_analyses_not_evidence，须核对其原有实质事项在最终正文中的覆盖；已提供existing_body_representations时，允许由其中实际逐字片段或资料表承接，不重复挤入分析；旧稿不是证据，不能继承错误。'
            'draft只是待压缩的候选，仍以facts原文为准；不要复制不受原文支持的判断。\n')
    note += ('只压缩draft，不输出locked_analyses或其他上下文里的判断。'
             '只返回JSON {"claims":[{"analysis":"压缩后的完整文字","evidence_ids":["实际支撑的编号"]}]}，不得返回编号列表或Markdown。\n')
    try:
        limit=max(1,min(5,int(os.getenv('PERSON_PROSE_COMPACTION_MAX_ROUNDS','3'))))
    except ValueError:limit=3
    try:
        attempts=[];audit['compression']['attempts']=attempts
        for attempt in range(limit):
            # Compression is not a second attempt at the whole missing-item
            # writing task. Keep every original card and every conserved/body
            # representation; the outer loop retains all diagnostics and
            # missing tasks and rechecks them after validation.
            packet={k:v for k,v in writing_input.items() if k not in {'previous_repair_diagnostics','missing_items'}}
            packet.update(draft=claims,target_analysis_chars=target)
            feedback=''
            if attempt:
                feedback=f'程序实测上一候选分析为{prose_chars(claims)}字符，仍超过{budget}字符。继续压缩同一候选，不新增事项；优先删重复措辞，保留来源、条件和不同实质事项。\n'
                packet['measured_analysis_chars']=prose_chars(claims)
            from person_model_transport import invoke_same_input
            result=invoke_same_input(invoke,role+'篇幅压缩',prefix+note+f'本次请以{target}字符以内为目标。\n'+feedback+json.dumps(packet,ensure_ascii=False),emit,audit['compression'],'transport')
            try:
                parsed=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',str(result).strip()))
                revised=parsed.get('claims') if isinstance(parsed,dict) else None
            except (ValueError,TypeError):revised=None
            valid=isinstance(revised,list) and all(isinstance(c,dict) for c in revised)
            attempts.append({'attempt':attempt+1,'structured_response':valid,
                'requested_target_analysis_chars':target,'analysis_chars':prose_chars(revised) if valid else None})
            if not valid or prose_chars(revised)<=budget:break
            target=max(1,min(target-1,int(target*budget/prose_chars(revised)*.95)))
            claims=revised
        audit['compression']['status']='returned_for_validation'
        return result,len(attempts)
    except Exception:
        audit['compression']['status'] = 'failed'
        raise


def enforce_budget(claims, chapter):
    """Check again after repairs; retain an oversized draft in the audit."""
    budget, size = analysis_budget(chapter), prose_chars(claims)
    audit = {'max_analysis_chars': budget, 'draft_chars': size,
             'scope': 'analysis_and_pending_analysis_excluding_citations_tables_and_quotes',
             'status': 'within_budget', 'published_chars': size}
    if size <= budget:
        return claims, audit
    # Do not silently select the first few findings or cut away qualifications.
    # The complete draft and supports remain reviewable, outside concise prose.
    audit.update(status='oversized_draft_withheld_for_review', published_chars=0,
                 withheld_claims=[dict(c) for c in claims])
    return [{**c, 'analysis': '', 'review_analysis': '',
             'analysis_status': 'length_review_required'} for c in claims], audit



def resource_only_omission_reason(reason):
    """Resource limits alone do not justify omitting substantive material."""
    text=str(reason or '')
    resource=re.compile(r'篇幅|字数|条数|配额|模型预算|上下文预算|输出预算|token|来源.{0,5}(?:足够|够用|已够)',re.I)
    if not resource.search(text):return False
    parts=re.split(r'[，,。；;\n]',text)
    substantive=''.join(p for p in parts if not resource.search(p))
    substantive=re.sub(r'本条|该条|本材料|该材料|本记录|该记录|原文|材料|资料|信息|完整|附录|保留|留存|留作|留待|作为|仅作|补充|参考|备查|回查|备用|因此|所以|故|正文|分析|保存|不需要|需要|可以|能够|待核','',substantive)
    substantive=re.sub(r'[^A-Za-z\u4e00-\u9fff]','',substantive)
    return len(substantive)<8
