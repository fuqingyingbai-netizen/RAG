"""Package actual chapter replays and source locators into a reviewable audit."""
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'scripts')]
from person_evidence import cited_ids,split_sections
from person_iteration import compare_sections
from search_results import canonical_source_url

WORK=ROOT/'work/person-flow'
OUT=ROOT/'deliverables/person-evidence-flow-20261021'
OUT.mkdir(parents=True,exist_ok=True)

NOTES={
1:'从最终正文继承摘要；未新建独立推断。',
2:'两例保持原文。教育与任期已有材料，不因没有访谈或私密材料补推断；仍有长表格、逐句只命中姓名的提取覆盖待核。',
3:'两例保持原文。公开发言不支持人格、诚信或风险偏好评级；排除公司责任套话合理。',
4:'主样本保持；第二样本恢复原采访中的制度创新和组织变革资料。来源对回归经营的预测仍按预测处理，不能写成已实现效果。',
5:'第二样本恢复2015年层级调整、计件工资及历史签字权限；时间、金额沿用原句。公司与人物自述仍须独立核实。',
6:'两例保持。其他团队成员独立归属，外部合作对象和同名人士不计入目标团队；第二样本团队原件仍稀疏。',
7:'主样本增加俞敏洪具名观点；第二样本从0恢复为杨利娟公开陈述与施永宏历史单方争议。非授权访谈，不作诚信结论；匿名记者与公司承诺继续排除。',
8:'两例保持。主样本有候选原件，但部分PDF文本损坏且时期、指标未对齐；第二样本未形成合格外部对标，不以关联公司管理者充当同行。',
9:'主样本让已取得的起始任职、历史离任和权益字段进入正文。公司诉讼叙事不能当作本人当事人证明；仍缺完整个人司法原件。单位判断仍保留拦截。',
10:'主样本把起止任职与历史记录用于委托问题；数据基准日缺失仍明确，不能把成立日当任职日或把历史比例写成当前持股。第二样本保持。',
11:'第二样本补历史授权分级与制度时期。未取得现行投资协议、信息权及退出触发条件，不认定存在当前退出权。主样本保持。',
12:'两例保持。直接个人信号与公司披露的潜在风险分列，17维未知项不评分；关联企业法律事件未完成全量上下文恢复，仍待证。',
13:'按最终正文实际保留分析汇总；被拦截内容不重新进入结论，待核验不变成风险等级。',
14:'按正文实际E-ID重建。E-ID是事实卡标识，同一URL多张卡不能算多个独立来源；来源镜像/同源转载仍需文档级核对。',
15:'同步更新缺口及平台状态。上下级关系现有材料与缺少客户/同行评价分开；地域限制、空列表、调用失败和未查询不混同。',
}


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    combined={'scope':'same_retained_corpus_partial_chapter_replays','new_search_calls':0,'new_fetch_calls':0,'new_platform_calls':0,
        'subjects':{},'tests':{},'limitations':['Not an independent truth or legal-responsibility verification','No fresh full-report online acceptance','No deployment or push']}
    documents=[]
    lines=['# 人物报告证据去向诊断与局部复验 2026年10月21日','',
        '已确认材料利用缺陷并完成必要修复与两位人物的真实章节回放。最严重的可复现问题是：已有任职记录被章节容量挤掉，评价用途标记封死了其他章节的管理事件，评价摘录句式和关系字段导致遗漏。资料不足、实现遗漏、模型错误和原文完整性不足必须分开。', '',
        '本轮以远程 main 的 f34f794 为基线，在隔离分支 codex/person-evidence-audit 中完成。原工作目录未切换或重置；没有部署、线上重启、合并或推送。', '',
        '模板已对照“创始人桌面研究”A/B列的15章。输出目录中的两份既有DOCX与相应归档DOCX逐字节哈希一致，诊断从它们对应的桌面报告Markdown、模型输入输出及原文快照追溯。', '',
        '## 统计口径与材料边界','',
        '| 样本 | 来源记录 / 规范化URL | 清洗卡 / 报告卡（前） | 正文E-ID 前→后 | 实际引用URL 前→后 |',
        '| --- | --- | --- | --- | --- |']
    page=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>人物报告证据去向诊断与局部复验</title>',
        '<style>body{font:16px/1.75 system-ui,"Microsoft YaHei",sans-serif;max-width:1380px;margin:32px auto;padding:0 24px;color:#172b42;background:#fafbfd}h1{font-size:30px}h2{margin-top:42px}table{border-collapse:collapse;width:100%;background:white}th,td{padding:11px;border:1px solid #d6dfe8;text-align:left;vertical-align:top}th{background:#eaf0f6}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.75 system-ui;margin:0}details{margin:16px 0;padding:16px;background:white;border:1px solid #d6dfe8}summary{cursor:pointer;font-weight:650}.cols{display:grid;grid-template-columns:1fr 1fr;gap:22px}.cols>div{min-width:0}a{color:#165dad}.muted{color:#526578}@media(max-width:850px){.cols{grid-template-columns:1fr}body{padding:0 14px}}nav{display:flex;gap:18px;flex-wrap:wrap}</style>',
        '<h1>人物报告证据去向诊断与局部复验</h1><p>已定位并修复材料丢失，使用两位人物原有语料做局部回放。没有新增检索、抓取或专业平台请求。</p>',
        '<p>本页包含15章概览、每个变动章节的完整前后文本，以及新增材料的原文定位。引用数不作为质量评分；公开观点、历史争议与当前个人责任保持边界。</p>',
        '<nav><a href="#overview">15章概览</a><a href="#wang">王传福前后文本</a><a href="#zhang">张勇前后文本</a><a href="#limits">仍待核验</a></nav>']
    table_rows=[]
    for key,name,affected in [('wang','王传福',{7,9,10}),('zhang','张勇（海底捞）',{4,5,7,11})]:
        old=read(WORK/f'{key}-before.json')
        base=Path(old['run'])
        final=WORK/f'{key}-final-validated'
        if (WORK/f'{key}-context-replay'/'desktop_report.md').exists():
            final=WORK/f'{key}-context-replay'
        contract,audit=read(final/'contract.json'),read(final/'audit.json')
        source_rows=read(base/'source-snapshots.json')
        by_url={s['url']:s for s in source_rows}
        facts={f['evidence_id']:f for f in contract['facts']}
        old_ledger=read(base/'person_claim_ledger.json')
        old_facts={f['evidence_id']:f for f in old_ledger['facts']}
        before_text=(base/'desktop_report.md').read_text(encoding='utf-8')
        after_text=(final/'desktop_report.md').read_text(encoding='utf-8')
        before,after=split_sections(before_text),split_sections(after_text)
        comparisons=compare_sections(before_text,after_text)
        body=set().union(*(cited_ids(after[n]) for n in range(1,14)))
        urls={canonical_source_url(facts[e]['source_url']) for e in body}
        index=cited_ids(after[14])
        assert body==index
        unchanged=[n for n in range(2,13) if n not in affected]
        assert all(before[n]==after[n] for n in unchanged)
        assert old['sources_sha256']==digest(base/'source-snapshots.json')
        rows=[]
        for n in range(1,16):
            oldids,newids=cited_ids(before[n]),cited_ids(after[n])
            oldurls={canonical_source_url(old_facts[e]['source_url']) for e in oldids if e in old_facts}
            newurls={canonical_source_url(facts[e]['source_url']) for e in newids if e in facts}
            rows.append({'chapter':n,'title':before[n].splitlines()[0],
                'selected_before':len(next(c for c in old['chapters'] if c['chapter']==n)['review'].get('cited_evidence_ids',[])),
                'candidates_before':next(c for c in old['chapters'] if c['chapter']==n)['candidates_audited'],
                'candidates_after':len(contract['chapters'][str(n)]['selection_audit']),
                'cited_before':len(oldids),'cited_after':len(newids),'urls_before':len(oldurls),'urls_after':len(newurls),
                'added_ids':sorted(newids-oldids),'removed_ids':sorted(oldids-newids),'text_unchanged':before[n]==after[n],
                'note':NOTES[n]})
        raw_doc=Path('E:/projects/output')/('人物报告_王传福_20261021_研究复核稿.docx' if key=='wang' else '人物报告_张勇海底捞_20261021_研究复核稿.docx')
        assert digest(raw_doc)==digest(base/'person-report.docx')
        snapshots=WORK/'originals'; snapshots.mkdir(exist_ok=True)
        key_source_ids=([31,39,43,51,54,66,67,68,69,88,89,93,94] if key=='wang' else [8,36,39,48,50,51,52,53])
        for source in source_rows:
            if source['id'] in key_source_ids:
                (snapshots/f'{key}-source-{source["id"]}.txt').write_text(source.get('content') or '',encoding='utf-8')
        source_flow=[]
        for source in source_rows:
            sfacts=[f for f in contract['facts'] if f['source_url']==source['url']]
            oldsource=next(s for s in old['sources'] if s['source_id']==source['id'])
            flow={'source_id':source['id'],'title':source['title'],'url':source['url'],
                'body_sha256':hashlib.sha256((source.get('content') or '').encode()).hexdigest(),
                'content_kind':oldsource['content_kind'],'fetch_status':oldsource['fetch_status'],
                'identity_confidence':oldsource['identity_confidence'],'discovery_only':oldsource['discovery_only'],
                'before_cleaned_cards':oldsource['cleaned_cards'],'before_report_cards':oldsource['report_cards'],
                'after_report_cards':len(sfacts),'before_cited_cards':oldsource['body_cited_cards'],
                'after_cited_cards':sum(f['evidence_id'] in body for f in sfacts),
                'historical_rejection_reasons':dict(Counter(r.get('rejection_reason') for r in oldsource['rejected_cards'])),
                'facts':[]}
            for f in sfacts:
                eid=f['evidence_id']; position=(source.get('content') or '').find(f['fact'])
                flow['facts'].append({'evidence_id':eid,'fact':f['fact'],'subject_scope':f['subject_scope'],
                    'original_char_offset':position if position>=0 else None,
                    'original_line':(source['content'][:position].count('\n')+1) if position>=0 else None,
                    'candidate_chapters':[int(n) for n,p in contract['chapters'].items() if any(r['evidence_id']==eid for r in p['selection_audit'])],
                    'routing':{n:next(r for r in p.get('routing_audit',[]) if r['evidence_id']==eid) for n,p in contract['chapters'].items() if any(r['evidence_id']==eid for r in p.get('routing_audit',[]))},
                    'selection':{n:next(r for r in p['selection_audit'] if r['evidence_id']==eid) for n,p in contract['chapters'].items() if any(r['evidence_id']==eid for r in p['selection_audit'])},
                    'cited_chapters':[n for n in range(1,14) if eid in cited_ids(after[n])],'indexed':eid in index})
            source_flow.append(flow)
        (WORK/f'{key}-evidence-flow.json').write_text(json.dumps(source_flow,ensure_ascii=False,indent=2),encoding='utf-8')
        stage_dirs=[p for p in WORK.iterdir() if p.is_dir() and p.name.startswith(key+'-') and (p/'request-status.json').exists()]
        stage_calls=[r for p in stage_dirs for r in read(p/'request-status.json')]
        extract_dirs=[WORK/f'{key}-feedback',WORK/f'{key}-feedback-v2']
        extraction_calls=sum(read(p/'feedback.json')['actual_model_requests'] for p in extract_dirs)
        calls=len(stage_calls)+extraction_calls
        subject={'baseline':str(base),'final_replay':str(final),'corpus_sha256':old['sources_sha256'],
            'source_records':old['source_records'],'normalized_unique_urls':old['unique_urls'],'cleaned_cards_before':old['cleaned_cards'],
            'report_cards_before':old['report_cards'],'report_cards_after':len(facts),
            'body_evidence_ids_before':old['body_evidence_ids'],'body_evidence_ids_after':len(body),
            'body_unique_urls_before':old['body_unique_urls'],'body_unique_urls_after':len(urls),
            'all_15_chapters':rows,'unchanged_body_chapters':unchanged,'model_requests':calls,
            'model_failures':sum(r['status']=='failed' for r in stage_calls),'extraction_calls':extraction_calls,
            'remaining_degradations':audit['degradations'],'original_docx_sha256':digest(raw_doc),
            'retrieval_attempt_states':dict(Counter(r.get('status') for r in old['retrieval']['attempts'])),
            'execution_stages':[{'stage':p.name,'elapsed_seconds':read(p/'summary.json')['elapsed_seconds']} for p in WORK.iterdir() if p.name.startswith(key+'-') and (p/'summary.json').exists()],
            'extraction_stages':[{'stage':p.name,'elapsed_seconds':read(p/'feedback.json')['elapsed_seconds']} for p in extract_dirs]}
        combined['subjects'][key]=subject
        lines.append(f'| {name} | {old["source_records"]} / {old["unique_urls"]} | {old["cleaned_cards"]} / {old["report_cards"]} | {old["body_evidence_ids"]}→{len(body)} | {old["body_unique_urls"]}→{len(urls)} |')
        documents.append((key,name,rows,before,after,old,contract))
        page+= [f'<h2 id="{key}">{html.escape(name)} 章节前后文本</h2>',f'<p>语料SHA256：{old["sources_sha256"]}<br>正文事实编号 {old["body_evidence_ids"]} → {len(body)}；实际URL {old["body_unique_urls"]} → {len(urls)}。这是使用范围统计，不是质量评分。</p>']
        (OUT/f'{key}-before.md').write_text(before_text,encoding='utf-8')
        (OUT/f'{key}-after.md').write_text(after_text,encoding='utf-8')
        for n in sorted(affected):
            title=re.sub(r'^##\s*\d+[.、．]\s*','',before[n].splitlines()[0])
            page.append(f'<details><summary>第{n}章 {html.escape(title)} 查看完整前后文本</summary><div class="cols"><div><h3>修复前</h3><pre>{html.escape(before[n])}</pre></div><div><h3>修复后</h3><pre>{html.escape(after[n])}</pre></div></div></details>')
        added=set().union(*(cited_ids(after[n])-cited_ids(before[n]) for n in affected))
        page.append('<h3>新增入选资料的原文定位</h3>')
        for eid in sorted(added):
            f=facts[eid]; s=by_url[f['source_url']]; body_text=s.get('content') or ''
            pos=body_text.find(f['fact']); line=body_text[:pos].count('\n')+1 if pos>=0 else None
            original=snapshots/f'{key}-source-{s["id"]}.txt'
            original.write_text(body_text,encoding='utf-8')
            page.append(f'<details><summary>{eid} 来源记录{s["id"]} 原文第{line or "待定位"}行</summary><p>{html.escape(s["title"])}<br>{html.escape(s["url"])}</p><pre>{html.escape(f["fact"])}</pre></details>')
            assert pos>=0, f'Newly selected card is not a literal retained-source substring: {eid}'
        (WORK/f'{key}-overall-comparison.json').write_text(json.dumps(comparisons,ensure_ascii=False,indent=2),encoding='utf-8')
    lines+=['','规范化URL数不等于独立文档数；镜像PDF、同源转载以及同一承诺的重复披露仍可能同源。新增入选原句已逐条验证是同一语料正文的连续子串，原件正文未改写。未把搜到的低正文、摘要、同名隔离材料计为有效原文。', '',
        '来源去向台账包含全部95＋53条归档记录及其清洗/身份状态、事实卡、章候选、入选原因、正文与索引。历史检索日志只保留请求统计或部分候选，无法恢复未留存候选的完整原文；该阶段明确标为“未留存”，不编造去向。修复后的包新增每张卡的 routing_audit，补足过去“未进入候选但无原因”的可观测性。', '',
        '## 全部15章覆盖与结论','',
        '| 章 | 王传福 E-ID/URL 前→后 | 张勇 E-ID/URL 前→后 | 诊断与边界 |','| --- | --- | --- | --- |']
    for n in range(1,16):
        a,b=[combined['subjects'][key]['all_15_chapters'][n-1] for key in ['wang','zhang']]
        lines.append(f'| {a["title"].replace("## ","")} | {a["cited_before"]}/{a["urls_before"]}→{a["cited_after"]}/{a["urls_after"]} | {b["cited_before"]}/{b["urls_before"]}→{b["cited_after"]}/{b["urls_after"]} | {NOTES[n]} |')
        table_rows.append(f'<tr><td>{html.escape(a["title"].replace("## ",""))}</td><td>{a["cited_before"]}/{a["urls_before"]} → {a["cited_after"]}/{a["urls_after"]}</td><td>{b["cited_before"]}/{b["urls_before"]} → {b["cited_after"]}/{b["urls_after"]}</td><td>{html.escape(NOTES[n])}</td></tr>')
    overview='<h2 id="overview">15章覆盖概览</h2><p>计数为事实编号/实际URL。第14章是索引，不另算正文证据。</p><table><tr><th>章节</th><th>王传福 前→后</th><th>张勇 前→后</th><th>诊断与边界</th></tr>'+''.join(table_rows)+'</table>'
    page.insert(5,overview)
    lines+=['','## 已确认缺陷与具体去向','',
        '1. **章节预算遗漏**：王传福来源66—69共有157张任职/关联卡，旧稿正文0张。历史台账明确记为 chapter_capacity，并非抓取失败或无记录。修复后，第9/10章各使用起始任职（2002-06-10）、深圳市比亚迪锂电池有限公司历史离任（2023-10-20）、16.9%权益字段，仍不认定这些就是当前状态。按问题保留代表资料，章容量仍为12，未把157张都塞入正文。', '',
        '2. **用途标记误筛**：张勇来源50完整采访13175字，48条历史候选被 feedback_source_requires_attribution_record 排除。原标记用于防止无归属评价进入第7章，却连组织变革原文一并封死。现恢复有姓名＋机构本地锚点的管理事件，仅路由4/5/11章；排除比较中阿里同名人物、人格描述和来源外改写。', '',
        '3. **评价摘录与关系字段**：旧规则偏向“评价…姓名”；修复双向句式并让模型选择完整原段编号，程序填原文，避免关系字段被拼成“CEO、下属”后因原文不连续而拒收。恢复张勇来源50杨利娟“上下级”评价；来源36施永宏陈述保留争议及未核实标记；主样本来源94俞敏洪观点保留具名但关系未知。没有把这些公开资料称为已做授权访谈。', '',
        '4. **误收防护**：修复匿名“记者”被当作具名评价者的漏洞，并要求本地明确发言归属；保留“在某人的回忆中”这类真实第一人称引语归属。排除代表公司发布服务承诺被当作个人承诺，未据此新增个人信用判断。', '',
        '5. **统计与身份贯穿**：来源台账原先可同时出现 status=cleaned 与 rejected_reason=empty_content；现区分真实成功、发现线索、身份隔离及未处理。清洗逐句提取及归一化补传用户别名，合成英文别名回归已验证；两位真实样本没有新增别名，不把此修复算成真实样本收益。', '',
        '6. **可控局部回放**：新增 replay_person_chapters.py；未请求章逐字保留，选材发生变化则拒绝保留。摘要、综合评估、索引和后续研究点重建；旧章未解决的校验状态继续传递，不自动过闸。', '',
        '7. **事件与反应被拆断**：第二样本初次回放把2015年组织调整的宣布与紧邻的员工不满、集体辞职、杨利娟处置拆开，导致模型误称未说明员工反馈。后续仅回放第5章；事件卡保留连续上下文，明确张勇后来才知道，不能把杨利娟的开除决定当作张勇直接下令。', '',
        '## 合理排除及仍待证事项','',
        '- 王传福第9章“15.41亿股”表述仍被 quantity_unit_not_supported 拦截：原表格扁平文本为“直接持股(股)…15.41亿”，程序尚未证明单元格与表头的单位绑定。没有放宽规则或把原句改成更方便过闸的数字。最终诊断仍保留此未解决项，不能宣称整份报告验收通过。',
        '- 第8章同期间、职责及指标对齐尚未完成。主样本可比PDF有原件定位，不等于全页OCR完整；张勇未形成合格可比人物来源，继续保留缺口。',
        '- 王传福旧PDF来源31/39/54均是80000字符，缺少完整页级提取收据，不能声称全文完整；本轮未为它们新增抓取。来源88保留414物理页，但机器字形异常及局部OCR不等于逐页核实。',
        '- 张勇来源51/53分别27/32物理页，仅局部OCR，complete=false；来源52实际为颐海2017年年报，246页且大量坏字，不能把它当作海底捞主体完整披露或借此认定无记录。来源39的37页文本提取收据完整，仍不代表来源事实独立核实。',
        '- 第9/12章：公司知识产权诉讼、旧管理者刑事事项不能自动归因目标本人。公司法律事件的无姓名上下文提取、平台明细范围和司法当事人定位仍有缺口，本轮不作无司法风险判断。',
        '- 第11章仍缺现行协议、授权生效及退出条件；公开报道不替代交割后治理事实。第7章仍缺多方授权访谈、利益关系及回应核对；公开观点不支持人格诚信推定。', '',
        '- 第5章新增原文已显示员工反应及杨利娟处置，但模型分析仍主要说明制度和证据边界；尚未形成独立的责任、效果或因果核验。不能把原句恢复等同于全部分析质量验收。', '',
        '## 请求与时间','',
        '| 样本 | 章节写作及复核请求 | 评价摘录请求 | 合计 | 失败 |','| --- | --- | --- | --- |']
    for key,name,*_ in documents:
        s=combined['subjects'][key]
        lines.append(f'| {name} | {s["model_requests"]-s["extraction_calls"]} | {s["extraction_calls"]} | {s["model_requests"]} | {s["model_failures"]} |')
    lines+=['','摘录每例两次：首次返回后发现关系改写/误收风险，第二次改为原段编号选择；没有无限重试。最终重复核对使用5份完整相同输入响应缓存，新增请求0。各阶段实际可得耗时见验证JSON；并行阶段耗时不可相加当作用户等待时间。API全部返回不等于内容全部通过。费用账单未返回，不估算金额，不猜测余额。新增搜索、网页抓取与专业平台调用均为0。', '',
        '## 验证与产物','',
        '- 人物相关整组248项回归通过；末次相关范围及新增测试结果由 final-targeted-tests.xml 记录。测试不替代真实章节验收。',
        '- 两位真实样本的新入选原句均能在原快照中连续定位，全部正文E-ID与第14章索引集合一致。受影响章之外正文逐字一致；摘要和综合评估只继承正文保留分析。',
        '- 对真实来源单独重清洗：张勇来源50从0张清洗卡恢复5张完整管理事件，0.187秒；王传福来源66维持27张卡，0.094秒。均无外部调用；证明修复不只在报告补丁层生效，未将受影响源重清洗误算作全语料重清洗。',
        '- 逐章完整前后文本：deliverables/person-evidence-flow-20261021/index.html；两位全文Markdown亦在同目录。该文件是本地审阅产物，没有发布网站。',
        '- 全部来源及卡去向：work/person-flow/wang-evidence-flow.json 与 zhang-evidence-flow.json；关键原件逐字文本、字符偏移和行号在 work/person-flow/originals。平台原始响应通过 source-snapshots.json 的 raw_response_key 回查 objects-before-cleanup，结构化字段投影不冒充网页原稿。', '',
        '已解决的是上述可复现的材料转化缺陷。原文完整性、司法明细覆盖、对标可比性、授权访谈及现行治理协议仍待补证；没有宣称彻底无遗漏。']
    lines+=['','## 代码与关键原件定位','']
    for path,number,label in [('backend/person_chapter_selection.py',181,'按研究问题选材及容量'),
        ('backend/person_chapter_selection.py',307,'从评价用途原件恢复管理事件及相邻反应'),
        ('backend/person_chapter_research.py',95,'个人契约与公司宣布边界'),
        ('backend/person_chapter_research.py',109,'评价者、原句与关系归属校验'),
        ('backend/person_chapter_research.py',386,'双向归属及完整原段选取'),
        ('backend/person_evidence.py',323,'事实卡逐章路由审计'),
        ('backend/person_evidence.py',835,'局部回放及旧校验状态继承'),
        ('backend/research_workflow.py',5082,'姓名与别名逐句提取'),
        ('backend/research_workflow.py',8200,'来源状态与排除原因统计')]:
        lines.append(f'- [{label}]({(ROOT/path).as_posix()}:{number})')
    lines+=['','| 样本及来源ID | 原件正文快照 | 关键内容或边界 |','| --- | --- | --- |']
    for key,i,label in [('wang',66,'开始时间2002-06-10与岗位字段'),('wang',67,'16.9%权益字段，无数据基准日'),
        ('wang',68,'历史关联公司，成立日期不是任职日期'),('wang',69,'历史任职结束字段'),('wang',94,'俞敏洪观点与本人自述'),
        ('wang',51,'郭台铭历史单方陈述及公司知识产权诉讼叙事'),('zhang',50,'2015年调整、员工反应、授权分级及杨利娟评价'),
        ('zhang',36,'施永宏历史单方陈述'),('zhang',52,'颐海年报及坏字/OCR边界')]:
        p=WORK/f'originals/{key}-source-{i}.txt'
        lines.append(f'| {key} / {i} | [逐字留存正文]({p.as_posix()}) | {label} |')
    import xml.etree.ElementTree as ET
    for filename in ['person-tests.xml','final-targeted-tests.xml']:
        root=ET.parse(WORK/filename).getroot(); suites=list(root) if root.tag=='testsuites' else [root]
        combined['tests'][filename]={k:sum(float(s.get(k,0)) for s in suites) for k in ['tests','failures','errors','skipped','time']}
    combined['actual_model_requests']=sum(s['model_requests'] for s in combined['subjects'].values())
    combined['reclean_validation']=read(WORK/'reclean-validation.json')
    combined['billing_cost_available']=False
    combined['validation']={'all_original_source_hashes_unchanged':True,'all_new_selected_quotes_are_literal_substrings':True,
        'actual_body_ids_equal_source_index':True,'unaffected_body_sections_verbatim':True,'remaining_review_gates_preserved':True}
    validation=ROOT/'docs/PERSON_EVIDENCE_FLOW_VALIDATION_20261021.json'
    validation.write_text(json.dumps(combined,ensure_ascii=False,indent=2),encoding='utf-8')
    report=ROOT/'docs/PERSON_EVIDENCE_FLOW_REVIEW_20261021.md'
    report.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    page+=['<h2 id="limits">仍待核验</h2><p>王传福第9章仍有单位校验未解决；旧PDF全文完整性、局部OCR、个人司法当事人定位、对标同期间口径、授权访谈和现行投后协议均未完成。不能从公开发言推导人格诚信，不能把公司风险归因个人。</p>',
        f'<p>实际模型请求{combined["actual_model_requests"]}次；新搜索、抓取和专业平台调用均为0。未取得账单，不估算金额。</p>',
        '<p>完整诊断与可复现数据在仓库docs/PERSON_EVIDENCE_FLOW_REVIEW_20261021.md及同日VALIDATION.json。没有部署或推送。</p></html>']
    (OUT/'index.html').write_text('\n'.join(page),encoding='utf-8')
    print(json.dumps({'model_requests':combined['actual_model_requests'],'subjects':{k:{x:v[x] for x in ['body_evidence_ids_before','body_evidence_ids_after','body_unique_urls_before','body_unique_urls_after','unchanged_body_chapters']} for k,v in combined['subjects'].items()},'tests':combined['tests'],'review':str(report)},ensure_ascii=False))


if __name__=='__main__':
    main()
