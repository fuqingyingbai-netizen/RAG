"""Bounded industry quality contracts over already located evidence.

No network, search, model, database or fabricated metrics. Passing these narrow
checks is not semantic entailment or a guarantee of research completeness.
"""
import hashlib
import re
from collections import defaultdict

VERSION='industry-quality-v2-focus-and-qualified-context'
SEGMENTS=('四足机器人','人形机器人','具身智能','智能手机','自动驾驶','大语言模型','生成式人工智能')

def bind_local_context(fact, body):
    """Only a nearby heading/paragraph from the same verified body is context."""
    fact.pop('source_context',None)
    loc=(fact.get('provenance') or {}).get('locator') or {}
    start,end=loc.get('start'),loc.get('end')
    if (not body or loc.get('status')!='verified' or type(start)!=int or type(end)!=int
            or not 0<=start<end<=len(body) or loc.get('body_sha256')!=hashlib.sha256(body.encode()).hexdigest()):
        return fact
    # A large page/header is not permission to bind unrelated navigation text.
    paragraph=body.rfind('\n\n',max(0,start-180),start)
    left=max(start-180,paragraph+2 if paragraph>=0 else 0,0)
    prefix=body[left:start]
    lines=[v.strip() for v in prefix.splitlines() if v.strip()]
    heading=lines[-1] if lines and len(lines[-1])<=100 else ''
    quote=body[start:end]
    context=(heading+'\n'+quote).strip()
    spans=[{'start':start,'end':end,'quote':quote}]
    if heading:
        heading_start=body.rfind(heading,left,start)
        spans.insert(0,{'start':heading_start,'end':heading_start+len(heading),'quote':heading})
    fact['source_context']={'text':context,'use':'scope_and_attribution_only',
        'spans':spans,'body_sha256':loc['body_sha256']}
    return fact

def evidence_quality(fact, scope):
    loc=(fact.get('provenance') or {}).get('locator') or {}
    quote=str(loc.get('quote') or fact.get('evidence_quote') or fact.get('fact') or '')
    context=str((fact.get('source_context') or {}).get('text') or quote)
    from industry_source_quality import source_qualifications
    source_quality = source_qualifications(fact, scope)
    issues=list(source_quality['issues'])
    if (re.search(r'思维导图|模板下载|素材下载|一键生成|点击下载',quote)
            and re.search(r'这是一个|收藏|点赞|模板|下载|分享',quote)):
        issues.append('promotional_or_template_passage')
    if (quote.count('\ufffd')>=2 or re.search(r'(?:[A-Za-z]\s+){12,}',quote)
            or re.search(r'(?:[\u4e00-\u9fff]\s+){18,}',quote)):
        issues.append('ocr_fragment_requires_review')
    ai=bool(re.search(r'人工智能|\bAI\b',str(scope.get('industry_name') or ''),re.I))
    ai_anchor=bool(re.search(r'人工智能|\bAI\b|大模型|机器学习|深度学习|模型推理|自动驾驶|具身智能|机器人',context,re.I))
    unrelated=bool(re.search(r'手机业务|汽车业务|房地产|煤炭|白酒|水泥|手机.{0,8}(?:毛利|成本)|汽车.{0,8}(?:毛利|成本)',quote))
    if ai and unrelated and not ai_anchor:
        issues.append('local_industry_subject_mismatch')
    from industry_review_fixes import local_segments
    segments=[s for s in local_segments(fact,quote,context,SEGMENTS) if s not in str(scope.get('industry_name') or '')]
    requested=[str(s) for s in scope.get('segments') or []]
    narrower=[s for s in segments if not any(s in r or r in s for r in requested)]
    # Only an explicit nearby narrower subject is retained, never inferred
    # from a site title or distant page navigation.
    boundary='、'.join(narrower) if narrower else ''
    if any(str(x) and str(x) in narrower for x in scope.get('excluded_segments',[])):
        issues.append('excluded_local_segment')
    region='全球' if '全球' in context else '中国大陆' if '中国大陆' in context else ''
    return {'version':VERSION,'requested_focus':source_quality['requested_focus'],'focus_terms':source_quality['focus_terms'],'issues':issues,'segment':boundary,'geography':region,
        'local_scope_only':bool(boundary),'forecast_window':__import__('industry_outlook_quality').forecast_window(fact,scope),'semantic_entailment':'not_evaluated'}

def analysis_boundary_issues(claim, facts, chapter):
    body=str(claim.get('text') or '')
    canonical=' '.join(str(f.get('fact_contract',{}).get('statement') or '') for f in facts)
    from industry_source_quality import analysis_issues
    issues=analysis_issues(claim, facts, chapter)
    for f in facts:
        q=f.get('fact_contract',{}).get('evidence_quality') or {}
        segment=q.get('segment') or ''
        if segment and not any(s in body for s in segment.split('、')) and not claim.get('claim_kind')=='limitation':
            issues.append('analysis_local_segment_boundary_missing')
        if q.get('local_scope_only') and q.get('geography')=='全球' and '全球' not in body:
            issues.append('analysis_local_geography_boundary_missing')
    legal=chapter in {3,13} or bool(re.search(r'条款|法规|《[^》]*(?:办法|条例|规定)[^》]*》',body))
    if legal:
        for clause in re.split(r'[。；;]',body):
            timing=re.search(r'事前|启动前|开始前|之前|之前完成|事后补记|事后补办',clause)
            if not timing or timing[0] in canonical:
                continue
            # An expressly non-legal operational suggestion remains possible;
            # absence of a deadline is not legal permission for late compliance.
            suggestion=bool(re.search(r'建议|内部流程|非(?:法定|法律)|不代表.{0,10}法定',clause))
            assertion=bool(re.search(r'需(?:要)?|须|必须|应当|不得|禁止|允许|可以事后|可在事后',clause))
            rejects_permission = bool(re.search(r'(?:不能|不得|不应|不足以).{0,30}(?:推定|认定|证明|视为).{0,10}(?:允许|可以|无需|不必)',clause))
            scoped_absence = bool(re.search(r'(?:所引|本条|该条|上述条款).{0,12}(?:未|没有)(?:明确)?(?:规定|要求|载明)',clause)) and (rejects_permission or not re.search(r'允许|可以事后|可在事后|无需|不必',clause))
            if assertion and not suggestion and not scoped_absence:
                issues.append('analysis_unauthorized_legal_timing')
        if (re.search(r'(?:《[^》]*(?:办法|条例|规定)[^》]*》|本法|该法|该办法).{0,12}仅适用于',body)
                and '仅适用于' not in canonical):
            issues.append('analysis_article_promoted_to_law_scope')
        if (re.search(r'(?:未|没有|未曾)(?:明确)?规定.{0,20}(?:因此|故|所以|意味着).{0,20}(?:允许|可以|无需|不必)',body)
                and not re.search(r'允许|无需|不必',canonical)):
            issues.append('analysis_permission_from_legal_silence')
    if chapter==7 and re.search(r'(?:性能|成本|延迟|吞吐).{0,12}(?:优于|更好|更低|最高|最低)|全面领先',body):
        if not comparison_contract({'facts':facts},7)['quantitative_comparison_ready']:
            issues.append('analysis_comparison_conditions_missing')
    return list(dict.fromkeys(issues))

def comparison_row(fact):
    c=fact.get('fact_contract') or {};n=fact.get('numeric_context') or {}
    quote=str(c.get('statement') or '')
    conditions={}
    for key,pattern in {
        'hardware':r'(?:GPU型号|硬件配置|统一硬件|相同硬件)\s*[为：:]\s*([^。；;，,]{1,70})',
        'model':r'(?:测试模型|模型版本|相同模型)\s*[为：:]\s*([^。；;，,]{1,70})',
        'load':r'(?:测试负载|输入长度|并发数|量化精度)\s*[为：:]\s*([^。；;，,]{1,70})',
    }.items():
        m=re.search(pattern,quote,re.I)
        if m:conditions[key]=m[0]
    return {'evidence_id':fact.get('evidence_id'),'subject':fact.get('segment_name') or fact.get('subject_name') or fact.get('company_name') or '',
        'period':n.get('period') or c.get('period') or '', 'geography':n.get('geography') or '',
        'definition':n.get('definition') or '', 'metric':n.get('metric') or '', 'unit':n.get('unit') or '',
        'value':n.get('value') or '', 'nature':c.get('value_nature') or '',
        'sample_boundary':c.get('sample_boundary') or '', 'test_conditions':conditions}

def comparison_contract(package, chapter):
    facts=[f for f in package.get('facts',[]) if (f.get('fact_contract') or {}).get('report_admitted')]
    rows=[comparison_row(f) for f in facts]
    # Preserve a licensed qualitative object when no quantitative conditions exist.
    for row, fact in zip(rows, facts):
        if not row['subject'] and not row['metric']:
            row['subject'] = re.split(r'[，,。；;]',str(fact.get('fact_contract',{}).get('statement') or ''))[0][:60]
    groups=defaultdict(list)
    if chapter==7:
        for row in rows:
            if row['metric'] and row['unit'] and len(row['test_conditions'])==3:
                key=(row['metric'],row['unit'],tuple(sorted(row['test_conditions'].items())))
                statement=next(f.get('fact_contract',{}).get('statement') for f in facts if f.get('evidence_id')==row['evidence_id'])
                groups[key].append((row['evidence_id'],statement))
    comparable=[[eid for eid,_ in group] for group in groups.values() if len({text for _,text in group})>=2]
    needs={4:['同一地域、总体与指标定义','至少连续三年历史值','增长率的起终期间与方法'],
        6:['同一市场定义、期间及份额分母','参与主体或产品口径','独立原始来源'],
        7:['同一对象层次与测试任务','硬件、模型版本和负载条件','性能单位与成本构成'],
        10:['收费对象和已付费或交付记录','同期间收入确认口径','成本构成和盈利兑现'],
        11:['仍在有效目标期间内的来源预测','来源假设与情景条件','可跟踪变量和触发条件']}
    return {'version':VERSION,'purpose':'comparison_conditions_not_new_evidence','chapter':chapter,
        'required_conditions':needs.get(chapter,[]),'rows':rows[:12],
        'quantitative_comparison_ready':bool(comparable),'comparable_groups':comparable,
        'unknown_fields_remain_unknown':True}

def comparison_markdown(cards, chapter):
    if chapter not in {4,6,7,10,11}:return ''
    contract=comparison_contract({'facts':cards},chapter)
    if not contract['rows'] or not contract['quantitative_comparison_ready']:return ''
    from industry_fact_contracts import statement_markdown
    def cell(v):return statement_markdown(str(v or '未披露')).replace('|','/')
    lines=['### 可比材料与条件','',
        '以下列出材料明确披露的比较条件；并列展示不代表已完成统计口径或盈利质量核验。',
        '', '| 原文编号 | 期间与范围 | 指标或对象 | 已披露条件 |', '| --- | --- | --- | --- |']
    useful=[row for row in contract['rows'] if row['subject'] or row['metric'] or row['period'] or row['test_conditions']]
    if not useful:return ''
    for row in useful[:6]:
        extent='；'.join(v for v in (row['period'],row['geography'],row['sample_boundary']) if v)
        metric='；'.join(v for v in (row['subject'],row['metric'],row['definition']) if v)
        conditions='；'.join(row['test_conditions'].values())
        lines.append('| ['+str(row['evidence_id'])+'] | '+cell(extent)+' | '+cell(metric)+' | '+cell(conditions)+' |')
    lines+=['','比较前须核对：'+'；'.join(contract['required_conditions'])+'。未披露的条件须先补证，不能按同口径处理。']
    return '\n'.join(lines)

def executive_context(plans):
    groups=((4,'市场连续序列与口径'),(6,'份额与竞争机制'),(7,'同条件性能和成本'),(10,'收费及盈利兑现'))
    missing=[]
    for chapter,label in groups:
        plan=(plans or {}).get(chapter,(plans or {}).get(str(chapter),{})) or {}
        rows=plan.get('content_coverage') or []
        if not rows or any(not row.get('evidence_ids') or row.get('status') in {'missing','background_only','unsupported','contradicted'} for row in rows):
            missing.append(label)
    uncertainty='关键不确定性：'+('、'.join(missing[:3])+'尚待核验。' if missing else '当前判断的证据支持、统计口径与成立条件仍需人工确认。')
    priority='优先核验：'+('先核对'+missing[0]+'，再检查各章推论是否与原文一致。' if missing else '复核原文与跨章判断，按第16章完成条件逐项确认。')
    return [uncertainty,priority]

def summary_candidates(report,payload,plans,claims):
    from industry_briefing import chapter_judgments
    from industry_fact_contracts import chapter_admitted
    facts=[f for f in payload.get('facts',[]) if f.get('eligible_for_report') is not False
        and f.get('provenance',{}).get('locator',{}).get('status')=='verified'
        and f.get('fact_contract',{}).get('report_admitted') and chapter_admitted(f,1) and chapter_admitted(f,14)
        and not f.get('fact_contract',{}).get('sample_boundary')]
    sections={int(m[1]):m[0] for m in re.finditer(r'(?ms)^##\s*(\d+)[.、．][^\n]*\n.*?(?=^##\s*\d+[.、．]|\Z)',report)}
    # Each record is revalidated and must still be visible in the same chapter.
    rows=chapter_judgments(plans,{'facts':facts},sections)
    from industry_analysis import statement_lineage_present
    by_id={f['evidence_id']:f for f in facts}
    rows=[row for row in rows if all(eid in by_id and statement_lineage_present(by_id[eid],sections.get(row['chapter'],''),{'facts':facts},row['chapter']) for eid in row['evidence_ids'])]
    from industry_outlook_quality import finding_key
    result=[];seen=set()
    for claim in claims:
        key=finding_key(claim)
        if key and key not in seen:result.append(claim);seen.add(key)
    for row in rows:
        key=finding_key(row)
        if key and key not in seen:
            result.append({**row,'validation_status':'rule_checked'});seen.add(key)
    # A long sequence of market findings must not crowd out a distinct
    # technical, commercial or regulatory finding that is already validated.
    def topic(c):
        q=str(c.get('question') or '')
        chapter=c.get('chapter') or c.get('reused_from_chapter')
        if chapter in {3,6,7,10,11}:return {3:'policy',6:'competition',7:'tech',10:'business',11:'outlook'}[chapter]
        for key,pattern in (('outlook',r'预测|前景|情景|触发|未来'),('market',r'市场|增长|规模'),('business',r'商业|盈利|收费'),('tech',r'技术|路线|部署'),('competition',r'竞争|份额'),('policy',r'政策|义务|监管')):
            if re.search(pattern,q):return key
        return 'chapter_'+str(c.get('chapter') or c.get('reused_from_chapter') or q)
    first=[];remaining=[];topics=set()
    for c in result:
        key=topic(c)
        if key not in topics:first.append(c);topics.add(key)
        else:remaining.append(c)
    order={'market':0,'outlook':1,'competition':2,'tech':3,'business':4,'policy':5}
    first.sort(key=lambda c:order.get(topic(c),6))
    return first+remaining

def enrich_peer_context(claims):
    result=[]
    for claim in claims:
        if claim.get('same_source_peer_claims'):
            result.append(claim);continue
        peers=[];refs=set(claim.get('evidence_ids') or [])
        for other in claims:
            if other.get('chapter')==claim.get('chapter') or not refs.intersection(other.get('evidence_ids') or []):continue
            text=other.get('text') or ''
            if len(text)>600:text=other.get('conclusion') or ''
            if text and len(text)<=600:
                peers.append({'chapter':other.get('chapter'),'text':text,'evidence_ids':other.get('evidence_ids')})
            if len(peers)==2:break
        result.append({**claim,**({'same_source_peer_claims':peers} if peers else {})})
    return result
