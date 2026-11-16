"""Research-premise routing and concise reading views. No IO or new evidence."""
import re

VERSION = 'industry-substance-v1-conditional-outlook-and-reading-copy'
OUTLOOK_QUESTIONS = {'未来三至五年趋势与关键变量', '可跟踪触发条件'}
DRIVERS = r'需求|客户|采购|付费|续约|回款|成本|价格|部署|推理|算力|芯片|供给|交付|监管|准入|数据治理|工具调用|权限'
ACTION = r'增加|增长|下降|降低|提高|上升|采用|采购|付费|续约|回款|收费|部署|依赖|限制|要求|应当|不得|影响|决定|制约|支持|成本|权限|工具调用'


def outline_material(text):
    """A study agenda identifies questions, never supplies their answers."""
    from industry_passages import passage_issues
    text = str(text or '').strip()
    if passage_issues(text):
        return True
    if re.search(r'结果显示|结果表明|研究发现|研究表明|测算结果|实测结果', text):
        return False
    return bool(re.search(r'(?:本报告|本研究|报告目录|研究提纲|章节安排|研究框架).{0,160}(?:涵盖|梳理|分为|包括|围绕|阐述|展开|分析|介绍)', text)
                and (len(re.findall(r'市场|技术|竞争|商业|政策|产业链|前景|风险|建议', text)) >= 3
                     or re.search(r'第[一二三四五六七八九十\d]+章|目录|提纲', text)))


def outlook_premise(fact, scope=None):
    """Current observations may support conditional paths, never a new forecast."""
    c = fact.get('fact_contract') or {}
    if not c.get('report_admitted') or fact.get('scope_match') not in (None, 'in_scope'):
        return False
    if (c.get('material_kind') in {'proposal','opinion','conditional'}
            or c.get('source_role') in {'opinion','commentary','policy_commentary','performance_claim','conditional_statement','recommendation'}
            or c.get('evidence_quality',{}).get('requested_focus') == 'background'):
        return False
    from industry_outlook_quality import forecast_window
    if forecast_window(fact, scope or {}).get('status') in {'expired','cutoff_unknown','target_period_unknown'}:
        return False
    period=str((fact.get('numeric_context') or {}).get('period') or '')
    cutoff=str((scope or {}).get('as_of_date') or '')
    if re.fullmatch(r'20\d{2}',period) and re.match(r'20\d{2}',cutoff) and int(cutoff[:4])-int(period)>3:
        return False
    text = str(c.get('statement') or '')
    return not outline_material(text) and bool(re.search(DRIVERS,text,re.I) and re.search(ACTION,text,re.I))


def prefer_comparable_premises(facts, chapter):
    """Reserve a complete same-condition pair before unrelated single points."""
    if chapter not in {6,7,10}:
        return facts
    from industry_quality import comparison_contract
    contract = comparison_contract({'facts':facts},chapter)
    groups = list(contract.get('comparable_groups') or [])
    if chapter in {6,10}:
        buckets={}
        for fact,row in zip(facts,contract['rows']):
            n=fact.get('numeric_context') or {}
            if ((fact.get('numeric_validation') or {}).get('passed') is not True
                    or not all(row.get(k) for k in ('subject','period','geography','definition','metric','unit'))
                    or row.get('sample_boundary')):
                continue
            key=tuple(str(row[k]) for k in ('period','geography','definition','metric','unit','nature'))
            buckets.setdefault(key,[]).append((row['evidence_id'],row['subject']))
        groups += [[eid for eid,_ in rows] for rows in buckets.values() if len({subject for _,subject in rows})>=2]
    if not groups:
        return facts
    first=set(groups[0][:4])
    return [f for f in facts if f['evidence_id'] in first]+[f for f in facts if f['evidence_id'] not in first]


def answer_state(row, claims, chapter):
    """Question completion is separate from a model supporting a limited claim."""
    useful=[c for c in claims if c.get('analysis_role')!='material_limitation'
            and c.get('claim_kind')!='limitation' and not c.get('source_observation_only')]
    if not row.get('evidence_ids') or not useful:
        return 'not_answered'
    from industry_review_fixes import completion_issue
    if all(completion_issue({**c,'question':row['question']}) for c in useful):return 'partial_answer'
    text=' '.join(str(c.get('text') or '') for c in useful)
    if chapter==7 and row['question'] in {'同条件测试配置','可核验性能及单位成本'}:
        if re.search(r'(?:尚无|没有|缺少|未提供|未披露|无法).{0,25}(?:同条件|同一测试|测试配置|性能.{0,8}成本|单位成本|可比测试)',text):
            return 'partial_answer'
    if chapter==11 and row['question'] in OUTLOOK_QUESTIONS:
        return 'conditional_analysis' if any(c.get('claim_kind')=='conditional' for c in useful) else 'draft_answer'
    return 'draft_answer'


def reading_copy(rendered, chapter, claims, coverage=()):
    """Keep exact reviewed prose and canonical evidence; remove duplicate UI audit."""
    rendered=re.split(r'\n\n### 材料覆盖与研究缺口\n',rendered,1)[0]
    unanswered=[row['question'] for row in coverage if answer_state(row,
        [c for c in claims if c.get('question')==row['question']],chapter) in {'not_answered','partial_answer'}]
    gap=('\n\n本章尚未回答：'+'、'.join(unanswered[:3])+('；其余'+str(len(unanswered)-3)+'项见独立台账' if len(unanswered)>3 else '')+'。') if unanswered else ''
    candidates=[row['question'] for row in coverage if row.get('inventory_status')=='candidate_review_required' and not row.get('evidence_ids')]
    if candidates:gap+='\n\n已有待核候选，先核对原文单位、口径及范围：'+'、'.join(candidates[:2])+'。'
    if not claims:
        return rendered+gap
    parts=rendered.split('\n\n',2)
    if len(parts)==3 and parts[1].startswith('本章初步判断及其依据如下'):
        rendered=parts[0]+'\n\n'+parts[2]
    start=rendered.find('\n\n### 本章初步结论\n')
    analysis=re.search(r'\n\n### (?:研究分析|来源观察与待深化分析)\n',rendered)
    end=rendered.find('\n\n### 关键依据\n')
    if analysis and end>analysis.start():
        from industry_fact_contracts import statement_markdown
        from industry_reader import analysis_paragraphs
        paragraphs=[]
        from industry_review_fixes import reading_paragraphs
        for row in reading_paragraphs(claims):
            refs=' '.join('['+eid+']' for eid in row['refs'])
            paragraphs.append(statement_markdown(row['text'])+' '+refs)
        prefix=rendered[:start if start>=0 else analysis.start()]
        rendered=prefix+'\n\n### 研究分析\n\n'+'\n\n'.join(paragraphs)+rendered[end:]
    return rendered+gap


def concise_tasks(tasks, include_chapter_topics=True):
    """Bounded reading queue; complete tasks are saved in the independent ledger."""
    from industry_delivery import _cell
    if not tasks:return '本轮未登记额外核验事项，仍需人工复核原文与判断。'
    priority={'最高':0,'高':1,'中':2,'低':3}
    indexed=list(enumerate(tasks));indexed.sort(key=lambda pair:(priority.get(pair[1].get('priority'),1),pair[0]))
    shown=indexed[:6]
    lines=['| 优先级 | 核验事项 | 下一步与完成条件 |','| --- | --- | --- |']
    for _,task in shown:
        topic=str(task.get('topic') or '待确认问题')
        key=str(task.get('task_id') or task.get('key') or '')
        from industry_reader import _first_sentence
        action=_first_sentence(task.get('action'),'核对该问题的原始材料与适用条件。')
        done=_first_sentence(task.get('completion'),'有依据则修订判断，仍缺证则明确保留未知。')
        detail=action+(' '+done if done!=action else '')
        material=_first_sentence(task.get('materials'),'')
        if material:detail+=' 材料：'+material
        subs=task.get('subtasks') or []
        if len(subs)==1:
            sub_action=_first_sentence(subs[0].get('action'),'')
            if sub_action:detail+=' 子任务入口：'+sub_action
        refs=task.get('review_references') or []
        ref=next((r for r in refs if re.match(r'^https?://[^\s<>]+$',str(r.get('url') or ''))),None)
        if ref:detail+=' 候选入口：['+str(ref.get('evidence_id') or '原始材料')+']('+str(ref['url']).replace('(','%28').replace(')','%29')+')。'
        lines.append('| '+' | '.join(_cell(v) for v in (task.get('priority') or '高',key+' '+topic,detail))+' |')
    lines += ['',f'本节仅列前{len(shown)}项优先工作，共{len(tasks)}项。完整问题、子任务、材料及完成条件保留在本轮独立结论证据台账；候选来源不作为已核实结论。']
    return '\n'.join(lines)


def priority_work(scope, requirements=''):
    """Proposed deliverables and roles, without committing people or dates."""
    outlook=bool(re.search(r'前景|未来|趋势|展望',str(requirements)))
    light=bool(re.search(r'日常了解|初步了解|概览',str(scope.get('purpose') or scope.get('research_purpose') or '')))
    rows=[('优先1' if outlook else '工作包1','前景判断：哪些因素驱动发展、什么条件会阻碍、跟踪什么信号',
           '前景判断简报：已有发现、条件性路径、主要阻碍和监测指标；区分来源预测与研究推论，不承诺无依据增速',
           '行业研究员拟稿，质量复核人员复核；证据不足的路径说明缺口，确认后再展开全稿'),
          ('优先2' if outlook else '工作包2','竞争、技术与商业化的有效比较',
           '同赛道玩家与产品定位、同条件性能成本、实际付费与收入成本对照；无可比数据的字段不排名',
           '数据分析人员核对口径，行业研究员解释差异；每项比较说明能得出的判断和限制'),
          ('优先3' if outlook else '工作包3','风险机制与最终报告修订',
           '风险作用对象、触发条件和影响路径；未完成维度继续不评分，并据复核发现修订报告',
           '行业研究员负责修订，质量复核人员核对依据，项目负责人确认最终版本；具体人员与轮次待确认')]
    from industry_delivery import _cell
    return '\n'.join(['### 优先研究问题与交付顺序','',('本轮先交付桌面前景简报；下列深度比较、访谈和采购仅作可选范围，另行确认后开展。' if light else '以下为建议工作顺序，范围、人员及节点须双方确认。'),
        '| 顺序 | 首先回答的问题 | 交付结果 | 完成与修订责任 |','| --- | --- | --- | --- |']+
        ['| '+' | '.join(_cell(v) for v in row)+' |' for row in rows])
