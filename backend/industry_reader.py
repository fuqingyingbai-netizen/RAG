"""Industry reader budgets and compact review views over unchanged audit data."""
from collections import defaultdict
import re

VERSION = 'industry-reader-v1-evidence-proportional-body'


def writing_profile(package, chapter, ids=None):
    from industry_fact_contracts import chapter_admitted, chapter_coverage
    cards = [f for f in package.get('facts', []) if chapter_admitted(f, chapter)
             and (ids is None or f.get('evidence_id') in ids)]
    selected = [f['evidence_id'] for f in cards]
    coverage = chapter_coverage(package, chapter, selected)
    direct = [q['question'] for q in coverage if q['evidence_ids']]
    documents = {f.get('source_document_key') or f.get('source_url') for f in cards}
    documents.discard(None); documents.discard('')
    # Richness means suitable question material, not the total retrieval count.
    # Samples and opinions remain labelled in the writer's unchanged cards.
    rich = len(direct) >= 3 and len(cards) >= 4 and len(documents) >= 2
    tier = 'rich' if rich else 'standard' if len(direct) >= 2 else 'sparse'
    limits = {'rich': (1100, 1800, '5至6', '180至320'),
              'standard': (600, 1100, '3至5', '150至280'),
              'sparse': (200, 500, '1至3', '100至220')}
    low, high, count, paragraph = limits[tier]
    return {'version': VERSION, 'tier': tier, 'suitable_fact_count': len(cards),
        'document_count': len(documents), 'questions_with_direct_material': direct,
        'target_analysis_characters': [low, high], 'suggested_paragraphs': count,
        'suggested_paragraph_characters': paragraph,
        'targets_are_guidance_not_permission_to_invent': True}


def writing_instruction(profile):
    low, high = profile['target_analysis_characters']
    return (f'本章按适用材料量分配正文，当前为{profile["tier"]}：优先写{profile["suggested_paragraphs"]}段分析，'
        f'每段约{profile["suggested_paragraph_characters"]}字，研究分析合计建议{low}至{high}字，最多6段。'
        '这些是展开程度提示，不是硬凑字数的要求。已有相应材料的问题，先直接回答能得出什么判断，'
        '再组织事实之间的联系、差异、条件及其他可能解释；有多项可比材料时比较，有机制前提时作有边界推论。'
        '每段应包含具体信息及其含义，不能反复以“材料不足、不能判断”代替分析，也不照抄整段原文。'
        '未覆盖的问题保留简短缺口说明，完整核验动作由程序安排；不要把补证清单写成长篇正文。'
        '资料只有单点、观点或企业样本时缩短相应分析，不能扩成趋势、实际盈利或行业整体判断。')


def analysis_balance(package, chapter, ids, claims):
    profile = writing_profile(package, chapter, ids)
    substantive = [c for c in claims if c.get('claim_kind') != 'limitation' and c.get('analysis_role') != 'material_limitation']
    chars = sum(len(re.sub(r'\s+', '', c.get('text', ''))) for c in substantive)
    return {**profile, 'substantive_analysis_paragraphs': len(substantive),
        'substantive_analysis_characters': chars,
        'limitation_paragraphs': len(claims)-len(substantive),
        'expansion_review_needed': profile['tier'] in {'rich', 'standard'} and chars < profile['target_analysis_characters'][0],
        'metric_is_not_semantic_or_quality_proof': True}


def _first_sentence(text, fallback):
    """Keep a complete first instruction; never hard-cut a narrative sentence."""
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    sentence = re.split(r'(?<=[。！？])', text, maxsplit=1)[0]
    return sentence if sentence and len(sentence) <= 150 else fallback


def task_brief(tasks, include_chapter_topics=True):
    """The report gets a reading view; complete task data stays in the diagnosis."""
    from industry_delivery import _cell
    if not tasks:
        return '本轮未登记额外核验事项，仍需人工复核原文与判断。'
    lines = ['| 优先级 | 核验事项 | 下一步与完成条件 |', '| --- | --- | --- |']
    chapters = defaultdict(list)
    for task in tasks:
        topic = str(task.get('task_id') or task.get('key') or '') + ' ' + str(task.get('topic') or '待确认问题')
        action = _first_sentence(task.get('action'), '先核对已有原文与当前判断，明确待解决的问题。')
        completion = _first_sentence(task.get('completion'), '按完整任务台账逐项复核；仍缺证则保留未知。')
        value = action + (' '+completion if completion != action else '')
        refs = task.get('review_evidence_ids') or []
        if refs:
            ref = next((r for r in task.get('review_references', []) if r.get('evidence_id') == refs[0]), {})
            url = str(ref.get('url') or '')
            anchor = '['+refs[0]+']'
            if re.match(r'^https?://[^\s<>]+$', url):
                anchor += '('+url.replace('(', '%28').replace(')', '%29')+')'
            value += ' 候选核验入口：'+anchor+'。'
        lines.append('| '+' | '.join(_cell(v) for v in (task.get('priority') or '高', topic, value))+' |')
        for sub in task.get('subtasks') or []:
            question = str(sub.get('topic') or '')
            if question.startswith('结论支持复核：'):
                question = question.removeprefix('结论支持复核：')+'（含推理复核）'
            if question and question not in chapters[sub.get('chapter')]:
                chapters[sub.get('chapter')].append(question)
    if include_chapter_topics and chapters:
        lines += ['', '各章核验重点（具体动作、候选来源及完成标准见完整明细）：', '']
        for chapter, questions in chapters.items():
            lines.append('- 第'+str(chapter)+'章：'+'；'.join(questions)+'。')
    lines += ['', '完整任务及候选来源保留在本轮核验台账、报告质量诊断及配套建议书附录A/B；'
        '候选入口不代表已支持事实或评分。']
    return '\n'.join(lines)


def balance_markdown(plans):
    rows = ['## 正文展开与证据使用', '',
        '以下检查正文是否充分使用已选材料，不以字数证明结论正确，也不自动追加模型请求。', '',
        '| 章节 | 适用材料档位 | 分析正文字符 | 建议展开范围 | 检查结果 |', '| --- | --- | --- | --- | --- |']
    for chapter, plan in plans.items():
        d = plan.get('reader_balance')
        if not d:
            continue
        low, high = d['target_analysis_characters']
        state = '已有适用材料，正文展开偏少，优先复核已知信息的解释与比较' if d['expansion_review_needed'] else '按材料和研究问题复核，不按字数单独判通过'
        rows.append(f'| 第{chapter}章 | {d["tier"]} | {d["substantive_analysis_characters"]} | {low}至{high} | {state} |')
    return '\n'.join(rows)+'\n\n' if len(rows) > 6 else ''
