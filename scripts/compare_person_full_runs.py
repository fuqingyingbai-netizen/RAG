"""Build an honest chapter comparison from two retained workflow runs."""
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from person_evidence import split_sections

NOTES = {
    1: '摘要只消费正文实际引用；仍为待人工复核摘要。',
    2: '公司资料退出个人履历；学校、职责与时期仍需逐项核验。',
    3: '不再以公司介绍支撑人格判断；来源评价不等于人格结论。',
    4: '公司经营资料拆成短记录；公司业绩不能直接归因为个人能力。',
    5: '保留管理相关来源；决策过程、机制和个人贡献需要补证。',
    6: '人员任职记录按章节标签入选；团队背景和现任状态仍需原件。',
    7: '公司资料退出个人信用；公开负面线索不自动生成个人信用评分。',
    8: '没有两名口径一致的可比人物，不做排名；本轮仍有缺口。',
    9: '企查查角色记录可按结构标签进入；关联企业事项与个人责任分开。',
    10: '专项方向保留，但不再用整段公司介绍充当持股及任职变化证据。',
    11: '治理资料按主题入选；历史任职不推导当前控制权和退出权。',
    12: '按来源登记核查线索；缺失、未命中及企业风险均不自动评分。',
    13: '综合评估引用前文章节材料；仍不输出无量表的A/B评级。',
    14: '索引由正文真实出现的E-ID生成；编号数量不等于独立来源或核实事实数。',
    15: '把每个未覆盖研究维度、平台失败及模型拦截集中列入补查计划。',
}


def main():
    before, after = [Path(p).resolve() for p in sys.argv[1:3]]
    typed = '--typed' in sys.argv[3:]
    commissioned = '--commission' in sys.argv[3:] or typed
    notes = dict(NOTES)
    if commissioned:
        for i in (1, 2, 3, 4, 5, 6, 8, 9, 11, 13):
            notes[i] = '程序保留事实原文；模型选择证据编号并为分析提供原文支持。' + notes[i]
        notes[10] = '按委托问题动态选材；排除公司名称关键词和其他团队成员；逐项列已有记录与尚未回答的问题。'
        notes[15] = '补查计划包含每个委托问题的缺口；多个年份和单个平台快照均不能自动证明历史变化。'
    if typed:
        notes.update({1: '摘要只汇总正文，正文仍待核验时不能自动获得通过状态。',
                      2: '保留原始任职日期字段；公司成立日、出生日期和采集日不能补成任职日。',
                      3: '剔除年报法定责任声明；公开表达不等于人格、抗压能力或诚信结论。',
                      4: '公司经营资料保留公司归属；不从企业规模或产品参数推导个人能力。',
                      5: '保留管理相关来源，不从员工规模、任职年限直接推出管理能力。',
                      6: '团队其他成员单独标明，不能归给目标人物，也不送入目标人物分析。',
                      7: '直接证据和授权访谈不足，维持待补证，不生成信用等级。',
                      8: '剔除“感谢同行伙伴”等误选；缺少同口径可比人物时明确无材料。',
                      9: '公司其他股东不当作人物持股；比例和股数、不同主体/单位/时期不能判为冲突。',
                      10: '委托问题驱动选材，列主体、指标、单位、时期与来源；每题保留未解决事项。',
                      11: '任职资料不自动证明实际决策权、投资人沟通机制或退出权利。',
                      12: '“执行董事”不能当作司法执行或风险信号；无直接资料不等于无风险。',
                      13: '综合评估继承正文待核验状态，不自动评级。',
                      14: '引用从正文实际编号生成，源材料始终由程序填入，不让模型重抄。',
                      15: '保留补证、分析拦截、时期和归属问题；程序规则不代表完整语义核验。'})
    summaries = [json.loads((p / 'summary.json').read_text(encoding='utf-8')) for p in (before, after)]
    reports = [split_sections((p / 'desktop_report.md').read_text(encoding='utf-8')) for p in (before, after)]
    audits = [{r['chapter']: r for r in s['chapter_audit']['chapters']} for s in summaries]
    if summaries[0].get('corpus_sha256'):
        assert summaries[0]['corpus_sha256'] == summaries[1]['corpus_sha256'], 'Different source corpora'
        assert summaries[0]['intake_sha256'] == summaries[1]['intake_sha256'], 'Different intakes'
    strip_images = lambda t: re.sub(r'!\[[^\]]*\]\([^\n]*\)', '[图像另存，文字对照中省略]', t)
    rows, cards = [], []
    for i in range(1, 16):
        b, a = [audit[i] for audit in audits]
        generation = summaries[1]['chapter_audit'].get('section_diagnostics', {}).get(str(i), {})
        old_generation = summaries[0]['chapter_audit'].get('section_diagnostics', {}).get(str(i), {})
        rejection = generation.get('validation_rejections', [])
        status = ('模型部分输出被拦截，保留底稿：' + ', '.join(rejection) if rejection else
                  '缺少本章可引用证据' if generation.get('status') == 'insufficient_evidence' else
                  '程序校验未拦截；待人工复核' if i < 14 else '自动生成核验记录')
        item = {'chapter': i, 'title': a['title'],
                'before_eids': len(b['cited_evidence_ids']), 'after_eids': len(a['cited_evidence_ids']),
                'before_text_chars': len(strip_images(reports[0].get(i, ''))),
                'after_text_chars': len(strip_images(reports[1].get(i, ''))),
                'before_listed_gaps': len(b.get('gaps', [])), 'after_listed_gaps': len(a.get('gaps', [])),
                'before_validation_rejections': old_generation.get('validation_rejections', []),
                'after_validation_rejections': rejection,
                'before_analysis_count': reports[0].get(i, '').count('- 研究判断（待人工复核）'),
                'after_analysis_count': reports[1].get(i, '').count('- 研究判断（待人工复核）'),
                'review_status': a.get('review_status', ''), 'source_scope_counts': a.get('source_scope_counts', {}),
                'status': status, 'change': notes[i], 'current_gaps': a.get('gaps', [])}
        rows.append(item)
        esc = html.escape
        cards.append(f'<section id="c{i}"><h2>{i}. {esc(a["title"])}</h2><p>{esc(notes[i])}</p><p class="state">{esc(status)}</p>'
                     f'<p>入选分析条数：{item["before_analysis_count"]} → {item["after_analysis_count"]}；数量不代表分析已核实。</p>'
                     f'<p>已列明缺口：{item["before_listed_gaps"]} → {item["after_listed_gaps"]}；'
                     f'文字长度：{item["before_text_chars"]} → {item["after_text_chars"]}（不含图像数据）</p>'
                     '<div class="pair">' + ''.join(f'<details><summary>{label}：查看实际章节正文</summary><pre>{esc(strip_images(report.get(i, "")))}</pre></details>'
                                                            for label, report in zip(('修正前', '修正后'), reports)) + '</div></section>')
    result = {'date': '2026-10-20', 'comparison_scope': 'same retained 35-source corpus before and after commissioned routing and analysis-only writing' if commissioned else 'same retained 35-source full live corpus before and after scoped company records; not legacy-main baseline',
              'baseline': str(before), 'after': str(after), 'corpus_sha256': summaries[1]['corpus_sha256'],
              'intake_sha256': summaries[1]['intake_sha256'], 'chapters': rows,
              'baseline_errors': summaries[0]['chapter_audit']['errors'], 'after_errors': summaries[1]['chapter_audit']['errors'],
              'baseline_model_rejections': summaries[0]['chapter_audit']['degradations'],
              'after_model_rejections': summaries[1]['chapter_audit']['degradations']}
    (after / 'chapter-comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    # Public-source draft only; raw archives, logs, credentials and local DBs
    # are deliberately not copied into deliverables.
    output = ROOT / ('deliverables/person-evidence-validation-20261020.html' if typed else 'deliverables/person-commission-optimization-20261020.html' if commissioned else 'deliverables/person-full-run-20261020.html')
    table = ''.join(f'<tr><td><a href="#c{r["chapter"]}">{r["chapter"]}. {html.escape(r["title"])}</a></td><td>{r["before_eids"]} → {r["after_eids"]}</td><td>{html.escape(r["change"])}</td><td>{html.escape(r["status"])}</td></tr>' for r in rows)
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>人物链路15章实际运行对照</title>
<style>body{font:16px/1.7 system-ui,sans-serif;color:#1c2a3a;background:#f3f6fa;max-width:1200px;margin:30px auto;padding:0 22px}h1{font-size:30px}section,.intro{background:white;padding:24px;margin:22px 0;border-radius:12px}table{border-collapse:collapse;width:100%;background:white}td,th{padding:12px;border:1px solid #dbe3ee;text-align:left;vertical-align:top}a{color:#165bb5}.state{color:#9d4312}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.7 system-ui}details{background:#f6f8fb;padding:12px;margin:10px 0}summary{cursor:pointer;font-weight:600}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:800px){.pair{display:block}table{font-size:13px}}</style>
<h1>人物链路：15章实际运行对照</h1><p>2026-10-20 · 王传福 / 比亚迪身份线索 · 公开来源研究底稿</p><div class="intro"><strong>流程跑通，尚未达到全部章节正式交付验收。</strong>
<p>修正前：本次新凭据下的完整真实检索、专业平台、清洗、报告及Word流程；35个归档来源（29网页、4企查查、2稀牛）。修正后：复用相同35个来源和相同委托条件，只重跑清洗及真实模型写作，没有新增检索或专业平台付费请求。</p>
<p>这是本次完整运行发现问题后的对照，不是原始主分支的全量旧版对照。旧页面的15章合成故障回放、此前两个人物抽样与本次真实运行分开记录。模型采样存在波动，不据此计算准确率或质量提升百分比。</p>
<p>E-ID计数是本章出现的不同证据编号，不是独立来源数，也不等于核实事实数。缺口增加表示识别更完整，不代表材料变差。文字变短是去除整段公司资料重复，不单独证明质量更高。</p>
<p>运行限制：博查本轮限流后熔断，由其他引擎继续；部分关联公司采集失败/身份不符被排除。建议书模型超时后使用模板兜底。Word包结构检查通过，因缺少LibreOffice尚未逐页视觉验收。应用登录、前端完整操作、共享知识入库和部署不在本次隔离运行范围。</p></div>
<table><thead><tr><th>章节</th><th>E-ID修正前→后</th><th>实际改善及边界</th><th>当前状态</th></tr></thead><tbody>'''
    if commissioned:
        page = page.replace('修正前：本次新凭据下的完整真实检索、专业平台、清洗、报告及Word流程；35个归档来源（29网页、4企查查、2稀牛）。修正后：复用相同35个来源和相同委托条件，只重跑清洗及真实模型写作，没有新增检索或专业平台付费请求。',
                            '前后均使用同一批35个来源和相同委托条件。修正前是首次按章节拆分公司记录后的复跑；修正后增加委托问题驱动选材及证据编号写作。该对照没有新增搜索或专业平台调用。另有两次专项搜索接口探针，仅验证查询连通，没有把搜索摘要加入报告。')
        page = page.replace('这是本次完整运行发现问题后的对照', '这是专项选材与写作协议修正的同材料对照')
        page = page.replace('文字变短是去除整段公司资料重复，不单独证明质量更高。', '文字长度用于检查冗余，分析条数和引用条数都不能单独证明质量提高。')
        page = page.replace('运行限制：博查本轮限流后熔断，由其他引擎继续；部分关联公司采集失败/身份不符被排除。建议书模型超时后使用模板兜底。',
                            '运行限制：原始采集曾遇博查限流及部分平台失败，本轮未重跑采集；另做的两个新搜索探针均有返回。最新写作复跑第9章模型超时，部分其他章节分析仍被拦截。建议书本轮未重跑。')
    if typed:
        page = page.replace('人物链路15章实际运行对照', '人物报告资料、写作与校验对照')
        page = page.replace('人物链路：15章实际运行对照', '人物报告：资料整理、写作与内容校验')
        start = page.index('<div class="intro">')
        end = page.index('</div>', start) + len('</div>')
        page = page[:start] + '''<div class="intro"><strong>完成15章生成，尚未通过正式内容交付验收。</strong>
<p>修正前为上一轮同材料真实写作；修正后为本轮新写作输出经最新规则复验的结果。均使用相同35来源和相同委托输入，SHA256一致。新写作实际调用10次模型，69.2秒完成，全部返回；随后复用保存的模型输出补验新增规则，复验没有新增模型/检索/专业平台请求。</p>
<p>本轮修复主体与字段整理、章节选材、原文由程序填入、写作输入过滤、不同指标/单位/主体/时期的比较限制及内部控制文字拦截。已剔除年报法定责任声明、“感谢同行伙伴”和“执行董事”造成的误选。证据编号、分析条数与生成速度都不是准确率。</p>
<p>新Tavily密钥一次搜索返回3条，用时1.8秒；搜索摘要没有加入本报告，密钥仅在本地忽略配置。来源中的任职与持股时期、个人责任、观点归属仍须人工核验。第7、8、12章缺直接材料；第2、3、4、5、6、9、10章仍有分析被拦截；第11章有证据缺口；第1、13章继承正文未完成状态。</p>
<p>Word包结构通过，环境缺少LibreOffice，未逐页视觉验收。没有重跑建议书、前端完整操作、共享知识入库或部署。规则不能代替完整的语义和事实核验。本页可展开每章查看实际前后正文。</p></div>''' + page[end:]
    page += table + '</tbody></table>' + ''.join(cards) + '</html>'
    output.write_text(page, encoding='utf-8')
    print(json.dumps({'page': str(output), 'comparison': str(after / 'chapter-comparison.json'), 'chapters': rows,
                      'after_errors': result['after_errors']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
