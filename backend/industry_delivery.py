"""Deterministic industry synthesis from validated artifacts, including reexports."""
import hashlib
import re

VERIFICATION_TASK_VERSION = 'industry-verification-v4-proposal-appendix'

# These are follow-up destinations, not permission to score a dimension.
RISK_TASK_SCOPE = {
    '政策与监管风险': ([3, 13, 14], ['policy']),
    '市场增长与需求风险': ([4, 5, 14], ['market_size', 'growth']),
    '竞争格局与集中度风险': ([6, 14], ['concentration', 'market_share']),
    '商业化与盈利模式风险': ([10, 14], ['pricing_model', 'profitability']),
    '技术迭代与替代风险': ([7, 14], ['technology_cost']),
    '资本热度与估值风险': ([8, 9, 14], ['capital']),
    '数据口径与证据可靠性风险': ([15, 14], []),
}


def _cell(value):
    return re.sub(r'\s+', ' ', str(value or '—')).replace('|', '/')


def replace_chapter(report, number, title, body):
    section = f'## {number}. {title}\n\n{body.strip()}\n\n'
    pattern = rf'(?ms)^##\s*{number}[.、．][^\n]*\n.*?(?=^##\s*(?:\d+[.、．]|集中式待核验清单|报告编制说明)|\Z)'
    if re.search(pattern, report):
        return re.sub(pattern, lambda _: section, report, count=1)
    match = re.search(rf'(?m)^##\s*{number+1}[.、．]',report)
    pos = match.start() if match else len(report)
    return (report[:pos].rstrip()+'\n\n' if report[:pos].strip() else '') + section + report[pos:]


def risk_status_section(risk, scope, title='综合评估'):
    from industry_research import active_risk_dimensions
    dimensions = {d.get('name'):d for d in (risk.get('dimensions') or []) if isinstance(d,dict)}
    rows, assessed = [], 0
    for name in active_risk_dimensions(scope):
        row = dimensions.get(name) or {}
        score = row.get('score')
        valid = (isinstance(score,(int,float)) and not isinstance(score,bool) and 0<=score<=100
                 and row.get('level') in {'low','medium','high','critical'} and bool(row.get('evidence_ids')))
        assessed += int(valid)
        refs = ' '.join(f'[{eid}]' for eid in row.get('evidence_ids',[])) if valid else '—'
        reason = row.get('reason') or '本轮尚未形成有效评估，保留未知。'
        cause = '' if valid else f'；原因代码：{row.get("unknown_cause") or "assessment_unavailable"}'
        label = {'low':'低','medium':'中','high':'高','critical':'严重'}.get(row.get('level'),'未知') if valid else '未知'
        rows.append('| '+' | '.join(map(_cell,(name,'已评估' if valid else '未完成评估',str(score) if valid else '未评分',label,reason+cause,refs)))+' |')
    total = len(active_risk_dimensions(scope))
    overall = risk.get('overall_score') if assessed == total else None
    return (f'## 14. {title}\n\n本轮{total}个启用风险维度中，{assessed}项已评估，{total-assessed}项未完成评估。'
            + ('总分暂不计算。' if overall is None else f'模型风险总分：{overall}（启用维度等权均值）。')
            + '评分尚未人工校准，不是风险概率；引用规则通过不等于判断已获语义证明。\n\n'
            '| 风险维度 | 评估状态 | 模型分值 | 风险等级 | 判断依据或未评分原因 | 证据编号 |\n'
            '| --- | --- | --- | --- | --- | --- |\n'+'\n'.join(rows)+'\n')


def verification_tasks(payload, risk, degradations, scope):
    """Prioritize structured deficiencies, never headings scraped from report prose."""
    from industry_research import active_risk_dimensions
    from industry_claims import industry_gap_plan
    tasks, keys = [], set()
    facts = {f.get('evidence_id'): f for f in payload.get('facts', []) if isinstance(f, dict) and f.get('evidence_id')}
    coverage = (payload.get('evidence_coverage') or {}).get('requirements', [])
    covered_requirements = set()

    def review_ids(ids):
        # References point to review material, never imply a rejected card now
        # supports a score. Unknown/unlocated/quarantined IDs stay in audit JSON.
        return list(dict.fromkeys(eid for eid in ids if isinstance(eid, str) and eid in facts
                       and facts[eid].get('eligible_for_report') is not False
                       and facts[eid].get('scope_match') == 'in_scope'
                       and not (scope.get('capital_market') == 'none' and facts[eid].get('evidence_scope') == 'capital_market')
                       and (facts[eid].get('provenance') or {}).get('locator', {}).get('status') == 'verified'))

    def add(key,topic,reason,kind=None,chapter=None,task_type='evidence_gap',ids=(),chapters=(),requirements=(),candidate_count=None,reference_limit=6):
        if key in keys:return
        keys.add(key)
        _,action,priority,materials = industry_gap_plan(kind or topic)
        completion='取得适用原始材料，逐项记录期间、地域、定义及来源位置后复核；仍缺证时说明原因，继续保留未知。'
        if task_type == 'assessment_validation':
            reason='当前评分未通过引用、数值或主张边界校验；这不等于行业经营恶化，也不能直接断定需要新增采购。'
            action='先对照已保存原文和授权指标，修正证据归属、数值及预测属性，再独立复核；确有资料缺口时再确认补采。'
            materials='本轮评分输入、已保存原文、授权指标与校验诊断；失败理由仅用于纠错，不作为事实。'
            completion='引用归属、单项指标和预测属性复核通过后再评估；未通过继续保留未知，不强行补分。'
        elif task_type == 'assessment_abstained':
            reason='模型未给出有效评估；已有候选不等于指标已核验，须先区分可用材料与实际缺口。'
            action='先核对现有候选是否满足本维度指标；不足时再按下述要求补证。'+action
        elif task_type == 'input_selection_review':
            reason='全库有适用候选，但评分包未保留对应材料；这是选材问题，尚不能判定需要外部补采。'
            action='先复核本轮已保存事实的适用性，按维度与指标重新分配证据预算；包内材料仍不足时再确认补采。'
            materials='全库适用候选、实际评分包、维度保留计数及来源位置。'
            completion='记录全库与包内适用数，复核选材后再独立评估；不能仅凭候选数量恢复分值。'
        elif task_type == 'execution_failure':
            reason='本轮评估调用或执行未完成，尚不能据此判断资料不足。'
            action='先排查调用与执行诊断，确认失败原因；是否重新评估由用户决定，不自动追加请求或采购。'
            materials='本轮调用状态、执行诊断和已保存的评分输入。'
            completion='执行问题查明后由用户决定后续评估；未完成前保持未知，不把连接失败认作行业缺证。'
        elif task_type == 'generation_review':
            completion='按当前证据和评分修订对应章节，引用及结论边界检查通过，且与第14章状态一致；不足则继续标待复核。'
        all_refs = review_ids(ids)
        # A proposal needs a usable starting list, not a dump of every keyword
        # match. Preserve every candidate in audit metadata and disclose selection.
        from industry_research import source_document_key
        ranked=sorted(all_refs,key=lambda eid:(facts[eid].get('claim_type')=='source_excerpt',
            (facts[eid].get('fact_contract') or {}).get('source_role') in {'opinion','commentary','performance_claim'},
            all_refs.index(eid)))
        refs=[]; documents=set()
        for eid in ranked:
            document=source_document_key(facts[eid].get('source_url') or '')
            if document in documents:continue
            refs.append(eid);documents.add(document)
            if len(refs)>=reference_limit:break
        for eid in ranked:
            if len(refs)>=reference_limit:break
            if eid not in refs:refs.append(eid)
        tasks.append({'key':key,'task_id':'V-'+hashlib.sha256(key.encode()).hexdigest()[:8].upper(),
                      'version':VERIFICATION_TASK_VERSION,'task_type':task_type,
                      'topic':topic,'reason':reason,'action':action,'priority':'高' if key.startswith('risk:') else priority,
                      'materials':materials,'chapter':chapter,'chapters':sorted(set(chapters or ([chapter] if chapter else []))),
                      'requirement_ids':sorted(set(requirements)), 'review_evidence_ids':refs,
                      'audit_review_evidence_ids':all_refs, 'review_candidate_count':len(all_refs),
                      'review_references':[{'evidence_id':eid,'title':facts[eid].get('source_title') or '保存来源',
                          'url':facts[eid].get('source_url') or '',
                          'start':((facts[eid].get('provenance') or {}).get('locator') or {}).get('start'),
                          'end':((facts[eid].get('provenance') or {}).get('locator') or {}).get('end'),
                          'body_sha256':((facts[eid].get('provenance') or {}).get('locator') or {}).get('body_sha256')}
                          for eid in refs],
                      'candidate_evidence_count':candidate_count,'completion':completion})
    for row in risk.get('dimensions') or []:
        if (row.get('name') not in active_risk_dimensions(scope) or row.get('score') is not None
                or row.get('applicable') is False or row.get('status') in {'disabled','not_applicable'}):continue
        chapters, reqs = RISK_TASK_SCOPE.get(row['name'], ([14], []))
        diagnostic = row.get('validation_diagnostic') or {}
        cause = row.get('unknown_cause') or ''
        primary_status = (risk.get('validation_diagnostics') or {}).get('primary_status')
        if primary_status in {'empty_or_invalid_json', 'request_failed', 'timeout', 'connection_error'} and not diagnostic:
            task_type='execution_failure'
        elif cause == 'evidence_budget_excluded':
            task_type='input_selection_review'
        elif cause == 'model_abstained':
            task_type='assessment_abstained'
        elif cause and cause not in {'no_applicable_evidence','assessment_unavailable'}:
            task_type=('assessment_validation' if cause in {'missing_model_citations','invalid_citations',
                       'invalid_reason_citations','unverified_reason_numbers','invalid_score'}
                       or diagnostic.get('original_score') is not None or diagnostic.get('semantic_issues')
                       else 'evidence_gap')
        else:
            task_type='evidence_gap'
        ids=list(diagnostic.get('admissible_evidence_ids') or [])
        for requirement in coverage:
            if requirement.get('requirement_id') in reqs:
                ids.extend(requirement.get('candidate_evidence_ids') or [])
        reason='本轮尚无适用且完成核验的行业评分证据；不表示该指标在行业中不存在。'
        if task_type == 'evidence_gap' and re.search(r'[\u4e00-\u9fff]', str(row.get('reason') or cause)):
            reason=str(row.get('reason') or cause)
        add('risk:'+row['name'],row['name'],reason,
            task_type=task_type,ids=ids,chapters=chapters,requirements=reqs,candidate_count=row.get('candidate_evidence_count'))
        covered_requirements.update(reqs)
    for row in coverage:
        if row.get('status')=='verified':continue
        if scope.get('capital_market')=='none' and row.get('module')=='投融资与资本市场':continue
        if row.get('requirement_id') in covered_requirements:continue
        add('metric:'+str(row.get('requirement_id')),str(row.get('question') or row.get('module')),
            '已有候选原文，但口径或适用性未核验。' if row.get('status')=='candidate' else '本轮保留的事实包尚无适用证据。',
            ids=row.get('candidate_evidence_ids') or [],requirements=[row['requirement_id']] if row.get('requirement_id') else [],
            candidate_count=len(row.get('candidate_evidence_ids') or []))
    synthesis = []
    for note in degradations:
        if not isinstance(note,dict):continue
        chapter = note.get('chapter')
        if chapter in ({8,9} if scope.get('capital_market')=='none' else set()) or (chapter==12 and not scope.get('named_companies')):continue
        if note.get('review_type') == 'statement_synthesis_review':
            synthesis.append(note)
            continue
        add('chapter:'+str(chapter),'第'+str(chapter)+'章综合写作复核' if chapter else '报告综合写作复核',str(note.get('message') or '生成校验未完成'),
            kind='章节写作复核',chapter=chapter,task_type='generation_review',ids=note.get('evidence_ids') or [])
    if synthesis:
        chapters=sorted({n['chapter'] for n in synthesis if isinstance(n.get('chapter'),int)})
        ids=[eid for n in synthesis for eid in review_ids(n.get('evidence_ids') or [])[:2]]
        add('synthesis:source-statements','章节分析及研究缺口复核',
            '来源陈述编排已完成；尚需复核分析和章节问题，不属于模型执行失败。',
            task_type='synthesis_review',chapters=chapters,ids=ids,reference_limit=18)
        task=tasks[-1]
        task.update(priority='中',action='对照下列章节问题与已选原文，补齐有依据的分析；优先处理事实纠错、评分拒绝和缺证任务。不得用宏观规模填充竞争或技术比较。',
                    materials='对应章节、已选证据链接和材料覆盖表；不需要把全部章节作为失败任务重写。',
                    completion='逐章说明已回答的问题及仍缺的材料；有依据的判断通过复核，无依据的部分继续保留未知。',
                    chapter_questions=[{'chapter':n['chapter'],'coverage':n.get('content_coverage') or []} for n in synthesis])
    return tasks


def evaluation_inputs(payload):
    """Keep industry evaluation distinct from risk, without inventing a rating."""
    from industry_grounding import sample_boundary, complete_excerpt
    from industry_research import risk_fact_text, numeric_mentions, claim_semantic_issues
    from industry_fact_contracts import risk_admitted
    groups=[('增长与需求','市场规模与增长'),('盈利与变现','商业模式与盈利逻辑'),
            ('政策支持与约束','政策与监管'),('技术与替代条件','技术路线对比')]
    lines=['### 行业评价输入与局限','',
        '行业吸引力不是风险分的倒数；以下仅列可追溯的评价输入，不给出未经独立验证的吸引力等级。企业样本不代替行业整体盈利，技术样本不代替行业技术成熟度。','',
        '| 评价方向 | 本轮可用输入 | 判断边界 |','| --- | --- | --- |']
    for label,module in groups:
        cards=[f for f in payload.get('facts',[]) if f.get('module')==module and f.get('eligible_for_report') is not False
               and risk_admitted(f, {'市场规模与增长':'市场增长与需求风险','商业模式与盈利逻辑':'商业化与盈利模式风险',
                    '政策与监管':'政策与监管风险','技术路线对比':'技术迭代与替代风险'}[module])
               and f.get('scope_match')=='in_scope' and not sample_boundary(f)
               and (f.get('provenance') or {}).get('locator',{}).get('status')=='verified'
               and (not numeric_mentions(str(f.get('fact') or '')) or (f.get('numeric_validation') or {}).get('passed') is True)
               and not claim_semantic_issues(risk_fact_text(f), [f])
               and not claim_semantic_issues(str(f.get('fact') or ''), [f])]
        cards.sort(key=lambda f:((f.get('numeric_validation') or {}).get('passed') is True,f.get('claim_type')!='source_excerpt'),reverse=True)
        if cards:
            card=cards[0]
            text=risk_fact_text(card)
            if len(text)>230:text=complete_excerpt(text,230)
            value=(text+' ['+card['evidence_id']+']') if text else '较长原文需核对后再转述。'
            limit='来源表述及适用边界仍需复核；单项输入不能单独证明行业吸引力。'
        else:
            value='尚未取得适用于本方向的完整行业层输入。'
            limit='保留待核验，不把选证不足当作行业经营恶化，也不以样本填补整体判断。'
        lines.append('| '+' | '.join(map(_cell,(label,value,limit)))+' |')
    return '\n'.join(lines)+'\n'


def tasks_section(tasks, title='后续研究点'):
    return ('## 16. '+title+'\n\n以下为待完成的核验任务；未表示已补搜、访谈或采购，也不预设人员、工期及费用。\n\n'
            +verification_task_table(tasks)+'\n')


def verification_task_table(tasks, include_reference_index=True, reference_index_only=False, reference_location='本节候选清单'):
    """One reader-facing task contract for the report and proposal.

    Review links are a route to inspect a candidate, not scoring citations.
    Keep six columns: adding provenance must not create unheaded note cells.
    """
    if not tasks:
        return '本轮未记录额外结构化核验任务，仍需人工核对原文和交付内容。'
    labels={'evidence_gap':'资料缺口','assessment_validation':'评分校验复核',
            'assessment_abstained':'评分弃评复核','execution_failure':'执行问题', 'generation_review':'章节复核',
            'synthesis_review':'分析复核'}
    rows=['| 核验任务 | 关联章节与候选证据 | 问题与处理类型 | 核验动作及材料 | 优先级 | 完成条件 |',
          '| --- | --- | --- | --- | --- | --- |']
    extra_references=[]
    linked_documents={}
    for task in tasks:
        chapters=task.get('chapters') or ([task['chapter']] if task.get('chapter') else [])
        links=('第'+'、'.join(map(str,chapters))+'章；') if chapters else ''
        ids=task.get('review_evidence_ids') or []
        if task.get('review_candidate_count',len(ids))>len(ids):
            links+='精选'+str(len(ids))+'/'+str(task['review_candidate_count'])+'个核验入口（全量编号保留于关联审计）；'
        refs={r['evidence_id']:r for r in task.get('review_references',[]) if r.get('evidence_id')}
        def reference(eid, with_title=False):
            ref=refs.get(eid,{})
            url=str(ref.get('url') or '')
            from industry_grounding import display_source_title
            label=eid+(' / '+display_source_title(ref.get('title')) if with_title else '')
            label=re.sub(r'[\[\]<>\\]', '', label).replace('|','/')
            if re.match(r'^https?://[^\s<>]+$',url):
                label='['+label+']('+url.replace('(','%28').replace(')','%29')+')'
            if with_title and ref.get('start') is not None:
                label+='；原文位置 '+str(ref['start'])+'–'+str(ref.get('end'))
                if ref.get('body_sha256'): label+=' / 指纹前缀 '+ref['body_sha256'][:12]
            return label
        if ids:
            links+='候选原文 '+ ' '.join(reference(eid) if eid in refs else '['+eid+']' for eid in ids[:3])
            # Every candidate has an offline title/link/locator entry. Grouping
            # by document avoids repeating a long title for every evidence ID.
            if refs:
                grouped={}
                for eid in ids:
                    ref=refs.get(eid,{})
                    grouped.setdefault((ref.get('url') or eid,ref.get('body_sha256') or ''),[]).append(eid)
                for group in grouped.values():
                    first=refs[group[0]]
                    document=linked_documents.setdefault((first.get('url') or group[0],first.get('body_sha256') or ''),{'tasks':set(),'refs':{}})
                    document['tasks'].add(str(task.get('task_id') or task.get('key')))
                    for eid in group:
                        ref=refs[eid]
                        position=('；位置 '+str(ref['start'])+'–'+str(ref.get('end'))) if ref.get('start') is not None else ''
                        if ref.get('body_sha256'):position+=' / 指纹前缀 '+ref['body_sha256'][:12]
                        document['refs'][eid]=(reference(eid,True),reference(eid)+position)
            if len(ids)>3:
                links+='；其余编号见'+reference_location+'。'
                if not refs:
                    for start in range(3,len(ids),8):
                        extra_references.append('| '+_cell(task.get('task_id') or task.get('key'))+' | '
                                                +' '.join('['+eid+']' for eid in ids[start:start+8])+' |')
        elif task.get('task_type') in {'assessment_validation','assessment_abstained','execution_failure'}:
            links+='先核对本轮评分输入的编号与原文定位，未登记可定位候选。'
        elif task.get('task_type') in {'generation_review','synthesis_review'}:
            links+='对应章节正文及来源索引，未登记可定位候选。'
        else:
            links+='尚无可定位候选编号，需补证或核对来源。'
        reason=labels.get(task.get('task_type'),'待复核')+'：'+task.get('reason','')
        fields=(str(task.get('task_id') or task.get('key') or '')+' '+task.get('topic',''),links,reason,
                task.get('action','')+' 所需材料：'+task.get('materials',''),task.get('priority','高'),
                task.get('completion') or '核对适用原文后复核；未取得材料时继续保留未知。')
        rows.append('| '+' | '.join(map(_cell,fields))+' |')
    for document in linked_documents.values():
        refs=list(document['refs'].values())
        for start in range(0,len(refs),8):
            batch=refs[start:start+8]
            extra_references.append('| '+'、'.join(sorted(document['tasks']))+' | '+_cell(batch[0][0])+'；'
                                    +' '.join(_cell(ref[1]) for ref in batch[1:])+' |')
    index = (['候选核验编号清单：仅为原文复核入口，不能直接作为评分依据。', '',
              '| 核验任务 | 其余候选编号 |', '| --- | --- |', *extra_references] if extra_references else [])
    if reference_index_only:
        return '\n'.join(index) or '本轮尚无已登记的候选来源索引。'
    if include_reference_index and index:
        rows += ['', *index]
    return '\n'.join(rows)


def reader_cleanup(report):
    """Remove only known generation metadata, keeping substantive reader prose."""
    lines=[]
    for line in report.splitlines():
        if re.match(r'^\s*(?:[-*>]\s*)?(?:image_urls|research_questions_status|information_gaps|named_companies)\s*[:：]',line):continue
        if re.fullmatch(r'\s*(?:\*\*)?[（(]?本章完[）)]?(?:\*\*)?\s*',line):continue
        if re.search(r'本章(?:仅|只).{0,12}\d+.{0,3}(?:条|项).{0,8}证据|证据包.{0,8}(?:预算|条数)',line) and not line.strip().startswith('|'):continue
        if not line.lstrip().startswith('#'):
            line=re.sub(r'#{3,6}\s*','',line)
        line=re.sub(r'research_questions_status(?:\[\d+\])?\s*[:：]?','研究问题',line)
        line=re.sub(r'information_gaps(?:\[\d+\])?\s*[:：]?','证据缺口',line)
        line=re.sub(r'\bimage_urls\s*[:：]\s*\[[^\]]*\]','',line)
        line=re.sub(r'\bnamed_companies\s*[:：]\s*\[[^\]]*\]','指定企业',line)
        line=re.sub(r'\bas_of_date\s*[:：]\s*', '资料截止日：', line)
        line=re.sub(r'(对象类型\s*[:：|]\s*)industry\b', r'\1行业', line)
        if '范围置信度' in line:
            line=re.sub(r'\b(?:medium|high|low)\b', lambda m:{'medium':'中','high':'高','low':'低'}[m[0]], line)
        lines.append(line)
    return '\n'.join(lines)


def finalize_synthesis(report, payload, risk, degradations, scope):
    titles={int(m[1]):m[2].strip() for m in re.finditer(r'^##\s*(\d+)[.、．]\s*([^\n]+)',report,re.M)}
    section=risk_status_section(risk,scope,titles.get(14,'综合评估'))
    section += '\n'+evaluation_inputs(payload)
    report=replace_chapter(report,14,titles.get(14,'综合评估'),section.split('\n',1)[1])
    notes=[]
    for note in degradations:
        item=dict(note)
        match=re.search(rf'(?ms)^##\s*{item.get("chapter")}[.、．][^\n]*\n(.*?)(?=^##\s*\d+[.、．]|\Z)',report)
        if match:
            item['evidence_ids']=list(dict.fromkeys(re.findall(r'\bE-[A-Z0-9-]{6,}\b',match[1],re.I)))
        notes.append(item)
    tasks=verification_tasks(payload,risk,notes,scope)
    report=re.sub(r'(?ms)^## 集中式待核验清单\s*$.*\Z','',report).rstrip()
    section=tasks_section(tasks,titles.get(16,'后续研究点'))
    report=replace_chapter(report,16,titles.get(16,'后续研究点'),section.split('\n',1)[1])
    return reader_cleanup(report),tasks


def risk_state_issues(report,risk,scope):
    """A synthesis must retain exactly the current risk artifact's full state."""
    match=re.search(r'(?ms)^##\s*14[.、．]\s*([^\n]+)\n(.*?)(?=^##\s*(?:\d+[.、．]|集中式待核验清单|报告编制说明)|\Z)',report)
    if not match:
        return ['第14章缺少与本轮风险产物同步的风险状态表。']
    expected=risk_status_section(risk,scope,match[1].strip()).strip()
    current=match[0].split('### 行业评价输入与局限',1)[0].strip()
    return [] if current==expected else ['第14章评估状态、分值或未知原因未按本轮风险产物完整同步，应重建启用维度状态表。']
