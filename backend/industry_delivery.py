"""Deterministic industry synthesis from validated artifacts, including reexports."""
import re


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
    def add(key,topic,reason,kind=None,chapter=None):
        if key in keys:return
        keys.add(key)
        _,action,priority,materials = industry_gap_plan(kind or topic)
        tasks.append({'key':key,'topic':topic,'reason':reason,'action':action,'priority':priority,
                      'materials':materials,'chapter':chapter,'completion':'取得适用原始材料，核对口径及引用后重新评估；缺证继续保留未知。'})
    for row in risk.get('dimensions') or []:
        if row.get('name') not in active_risk_dimensions(scope) or row.get('score') is not None:continue
        add('risk:'+row['name'],row['name'],str(row.get('reason') or '尚未完成有效评估')+'；'+str(row.get('unknown_cause') or 'assessment_unavailable'))
    for row in (payload.get('evidence_coverage') or {}).get('requirements',[]):
        if row.get('status')=='verified':continue
        if scope.get('capital_market')=='none' and row.get('module')=='投融资与资本市场':continue
        add('metric:'+str(row.get('requirement_id')),str(row.get('question') or row.get('module')),
            '已有候选原文，但口径或适用性未核验。' if row.get('status')=='candidate' else '本轮保留的事实包尚无适用证据。')
    for note in degradations:
        if not isinstance(note,dict):continue
        chapter = note.get('chapter')
        if chapter in ({8,9} if scope.get('capital_market')=='none' else set()) or (chapter==12 and not scope.get('named_companies')):continue
        add('chapter:'+str(chapter),'第'+str(chapter)+'章综合写作复核' if chapter else '报告综合写作复核',str(note.get('message') or '生成校验未完成'),
            kind='章节写作复核',chapter=chapter)
    return tasks


def evaluation_inputs(payload):
    """Keep industry evaluation distinct from risk, without inventing a rating."""
    from industry_grounding import sample_boundary, complete_excerpt
    from industry_research import risk_fact_text, numeric_mentions
    groups=[('增长与需求','市场规模与增长'),('盈利与变现','商业模式与盈利逻辑'),
            ('政策支持与约束','政策与监管'),('技术与替代条件','技术路线对比')]
    lines=['### 行业评价输入与局限','',
        '行业吸引力不是风险分的倒数；以下仅列可追溯的评价输入，不给出未经独立验证的吸引力等级。企业样本不代替行业整体盈利，技术样本不代替行业技术成熟度。','',
        '| 评价方向 | 本轮可用输入 | 判断边界 |','| --- | --- | --- |']
    for label,module in groups:
        cards=[f for f in payload.get('facts',[]) if f.get('module')==module and f.get('eligible_for_report') is not False
               and f.get('scope_match')=='in_scope' and not sample_boundary(f)
               and (f.get('provenance') or {}).get('locator',{}).get('status')=='verified'
               and (not numeric_mentions(str(f.get('fact') or '')) or (f.get('numeric_validation') or {}).get('passed') is True)]
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
    rows = ['## 16. '+title,'','以下为待完成的核验任务；未表示已补搜、访谈或采购，也不预设人员、工期及费用。','',
            '| 待核验事项 | 具体缺口 | 核验动作 | 优先级 | 所需材料 | 完成条件 |','| --- | --- | --- | --- | --- | --- |']
    rows += ['| '+' | '.join(_cell(t[k]) for k in ('topic','reason','action','priority','materials','completion'))+' |' for t in tasks]
    if not tasks:rows += ['本轮未记录额外结构化核验任务，仍需人工核对原文和交付内容。']
    return '\n'.join(rows)+'\n'


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
        lines.append(line)
    return '\n'.join(lines)


def finalize_synthesis(report, payload, risk, degradations, scope):
    titles={int(m[1]):m[2].strip() for m in re.finditer(r'^##\s*(\d+)[.、．]\s*([^\n]+)',report,re.M)}
    section=risk_status_section(risk,scope,titles.get(14,'综合评估'))
    section += '\n'+evaluation_inputs(payload)
    report=replace_chapter(report,14,titles.get(14,'综合评估'),section.split('\n',1)[1])
    tasks=verification_tasks(payload,risk,degradations,scope)
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
