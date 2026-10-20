"""Compare review policy on a fixed corpus, then show a separate new-material run."""
import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from person_evidence import split_sections
from person_platforms import coverage_rows

NOTES = {
    1: '摘要继承正文待复核状态；待确认分析带标记，不自动变成确认发现。',
    2: '原始任职、事件时间与当前状态分开；缺时期不称现任。',
    3: '公开表达仅作行为材料；不从宣传或业务结果确定人格、能力和诚信。',
    4: '公司结果与个人贡献分开；缺乏推理支持时按明确错误或待复核分别处理。',
    5: '保留管理来源陈述；错误数字、无效编号及无依据能力结论仍被拦截。',
    6: '同姓亲属及团队其他成员单独归属；亲属持股不能归给本人。',
    7: '具名评价与契约记录优先补查；没有材料时保留缺口，不用兄长资格说明填章。',
    8: '竞争力宣传与“感谢同行伙伴”不当作人物对标；可比人物和口径未齐不排名。',
    9: '查询任职、持股及司法事项；比较必须核对主体、指标、单位和时期。',
    10: '按委托问题逐项留材料与缺口，不把已有事实数量当作专项已完成。',
    11: '补充董事会授权及历史锁定承诺；不得推导当前控制权或通用退出权利。',
    12: '关键司法、信用查询先于公司背景扩展；查询为空和平台失败均不等于无风险。',
    13: '综合评估继承正文限制；不自动给出信用评级或人格判断。',
    14: '引用索引保留真实来源；待复核分析的引用也能回查。',
    15: '逐章补证计划与专业平台查询结果分开列出，保留空结果、失败、未查询和返回待核验。',
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('before', type=Path)
    parser.add_argument('policy_after', type=Path)
    parser.add_argument('supplement_after', type=Path)
    args = parser.parse_args()
    paths = [args.before, args.policy_after, args.supplement_after]
    runs = [json.loads((p / 'summary.json').read_text(encoding='utf-8')) for p in paths]
    assert runs[0]['corpus_sha256'] == runs[1]['corpus_sha256']
    assert runs[0]['intake_sha256'] == runs[1]['intake_sha256'] == runs[2]['intake_sha256']
    reports = [split_sections((p / 'desktop_report.md').read_text(encoding='utf-8')) for p in paths]
    esc = html.escape
    strip_images = lambda s: re.sub(r'!\[[^\]]*\]\([^\n]*\)', '[图像省略]', s)
    chapters, table, details = [], [], []
    for index in range(1, 16):
        observations = []
        for run in runs:
            audit = run['chapter_audit']
            row = next(r for r in audit['chapters'] if r['chapter'] == index)
            gen = audit['section_diagnostics'].get(str(index), {})
            observations.append({'cited_ids': len(row['cited_evidence_ids']),
                                 'pending_analysis': gen.get('pending_review_analysis_count', 0),
                                 'blocked_analysis': gen.get('blocked_analysis_count', 0),
                                 'review_status': row['review_status'], 'gaps': row['gaps'],
                                 'validation_rejections': gen.get('validation_rejections', []),
                                 'source_scope_counts': row['source_scope_counts']})
        title = runs[2]['chapter_audit']['chapters'][index-1]['title']
        chapters.append({'chapter': index, 'title': title, 'change': NOTES[index],
                         'before': observations[0], 'same_corpus_policy_after': observations[1],
                         'supplement_after': observations[2]})
        counts = ' → '.join(str(r['cited_ids']) for r in observations)
        table.append(f'<tr><td><a href="#c{index}">{index}. {esc(title)}</a></td><td>{counts}</td>'
                     f'<td>{observations[2]["pending_analysis"]}</td><td>{esc(NOTES[index])}</td></tr>')
        panels = ''.join(f'<details><summary>{label}</summary><pre>{esc(strip_images(report.get(index,"")))}</pre></details>'
                         for label, report in zip(('原35来源待复核稿', '相同35来源及已保存模型输出：标记策略复验', '新增检索、平台补测后的70来源待复核稿'), reports))
        details.append(f'<section id="c{index}"><h2>{index}. {esc(title)}</h2><p>{esc(NOTES[index])}</p>{panels}</section>')
    query_coverage = runs[2]['chapter_audit'].get('platform_query_coverage') or coverage_rows(runs[2]['chapter_audit'].get('platform_attempts', []))
    result = {'date': '2026-10-20', 'scope': 'fixed_corpus_policy_comparison_plus_separate_supplemented_corpus_review',
              'formal_delivery_accepted': False, 'same_corpus_and_saved_outputs_for_policy_test': True,
              'before': str(args.before), 'policy_after': str(args.policy_after), 'latest': str(args.supplement_after),
              'latest_new_model_requests': runs[2].get('actual_model_requests'),
              'latest_retained_responses_used': runs[2].get('retained_model_responses_used'),
              'platform_query_coverage': query_coverage, 'chapters': chapters,
              'word_visual_qa': {'status': 'blocked', 'reason': 'LibreOffice soffice.exe unavailable; packaged renderer failed; binary download unavailable'},
              'tests': 'See docs/PERSON_REVIEW_FOLLOWUP_REVIEW_20261020.md for final test scope and counts'}
    (ROOT / 'docs/PERSON_REVIEW_FOLLOWUP_VALIDATION_20261020.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>人物报告：复核标记与逐章补证</title><style>body{font:16px/1.7 system-ui,sans-serif;max-width:1200px;margin:30px auto;padding:0 22px;color:#17283b}table{border-collapse:collapse;width:100%}td,th{border:1px solid #d5dde7;padding:10px;text-align:left}section{margin:30px 0;padding-top:16px;border-top:1px solid #d5dde7}details{margin:12px 0;padding:12px;background:#f3f6f9}summary{cursor:pointer;font-weight:600}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 system-ui}a{color:#175dab}</style>
<h1>人物报告：复核标记与逐章补证</h1>
<p><strong>15章已生成，当前仍是待复核研究稿。</strong>依据不足但可审阅的分析保留“待复核”标记；错误引用、主体归属错误、指标混比及无依据人格结论继续拦截。</p>
<p>第一、二列使用相同35来源、相同委托及保存的真实模型输出，复验没有新API请求。第三列使用新完整检索69来源及一次成功犀牛补测，共70来源；新材料写作实际请求11次模型、80.7秒，最终用其中仍适用的10份保存响应重新校验，没有再次请求模型。第三列与前两列的材料不同，不能用于计算准确率或质量提升百分比。</p>
<p>平台情况：企查查主要公司的任职和历史关系有记录，失信/被执行/裁判文书为供应商对应数据库明确返回空结果；关联公司的地域限制单列。犀牛完整检索时有一次请求失败，单独补测融资资料成功。没有证据要求继续充值。所有结果均保留查询范围，空结果不代表个人无风险。</p>
<p>仍缺：第7章直接评价与授权访谈，第8章至少两位口径匹配的可比人物；第9、11、12章的个人责任、条款适用时期和关键查询范围仍须核实。部分分析被保留标记或拦截；来源数量、引用编号、速度均不等于事实已核实。</p>
<p>Word已导出并检查包结构；本机缺少LibreOffice，渲染器执行失败，尚未完成逐页视觉验收。本轮未覆盖生产部署、应用完整前端操作或共享知识入库。</p>
<table><thead><tr><th>章节</th><th>引用编号数：旧稿→同材料复验→补证稿</th><th>补证稿待复核分析</th><th>变化与边界</th></tr></thead><tbody>'''
    page += ''.join(table) + '</tbody></table>' + ''.join(details) + '</html>'
    output = ROOT / 'deliverables/person-review-followup-20261020.html'
    output.write_text(page, encoding='utf-8')
    print(json.dumps({'page': str(output), 'chapters': len(chapters)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
