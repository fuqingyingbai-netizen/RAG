"""Publish all-chapter text comparison with specific reputation/peer boundaries."""
import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from person_evidence import split_sections


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    args = parser.parse_args()
    runs = [json.loads((p / 'summary.json').read_text(encoding='utf-8')) for p in (args.before, args.after)]
    reports = [split_sections((p / 'desktop_report.md').read_text(encoding='utf-8')) for p in (args.before, args.after)]
    ledger = json.loads((args.after / 'person_claim_ledger.json').read_text(encoding='utf-8'))
    after_facts = {f['evidence_id']: f for f in ledger['facts']}
    chapters, sections, table = [], [], []
    for i in range(1, 16):
        old, new = [run['chapter_audit']['chapters'][i-1] for run in runs]
        ids = new['cited_evidence_ids']
        facts = [after_facts[eid] for eid in ids if eid in after_facts]
        row = {'chapter': i, 'title': new['title'], 'before_cited_ids': len(old['cited_evidence_ids']),
               'after_cited_ids': len(ids), 'after_review_status': new['review_status'],
               'source_scope_counts': new['source_scope_counts'], 'remaining_gaps': new['gaps'],
               'peer_names': sorted({f['comparison_subject'] for f in facts if f.get('comparison_subject')}),
               'opinion_records': sum(bool(f.get('opinion_only')) for f in facts)}
        chapters.append(row)
        esc = html.escape
        table.append(f'<tr><td><a href="#c{i}">{i}. {esc(new["title"])}</a></td><td>{row["before_cited_ids"]} → {len(ids)}</td>'
                     f'<td>{esc(new["review_status"])}</td></tr>')
        panels = []
        for label, report in zip(('优化前', '本轮补证及校验后'), reports):
            text = re.sub(r'!\[[^\]]*\]\([^\n]*\)', '[图像略]', report.get(i, ''))
            panels.append(f'<details><summary>{label}</summary><pre>{esc(text)}</pre></details>')
        sections.append(f'<section id="c{i}"><h2>{i}. {esc(new["title"])}</h2>' + ''.join(panels) + '</section>')
    result = {'scope': 'new_material_chapter_7_8_followup_not_controlled_accuracy_experiment',
              'before': str(args.before), 'after': str(args.after), 'formal_delivery_accepted': False,
              'final_validation_new_model_requests': runs[1].get('actual_model_requests'),
              'final_validation_retained_responses_used': runs[1].get('retained_model_responses_used'),
              'retained_source_count': runs[1]['sources_added'], 'chapters': chapters,
              'word_visual_qa': 'not_completed_renderer_unavailable'}
    (ROOT / 'docs/PERSON_REPUTATION_PEERS_VALIDATION_20261020.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>人物第7、8章：具名评价与可比人物补证</title><style>body{font:16px/1.7 system-ui,sans-serif;max-width:1150px;margin:30px auto;padding:0 22px;color:#17283b}table{border-collapse:collapse;width:100%}td,th{border:1px solid #d5dde7;padding:10px;text-align:left}section{margin:30px 0;padding-top:16px;border-top:1px solid #d5dde7}details{margin:12px 0;padding:12px;background:#f3f6f9}summary{cursor:pointer;font-weight:600}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 system-ui}a{color:#175dab}</style>
<h1>人物第7、8章：具名评价与可比人物补证</h1>
<p><strong>已改进检索与选材，当前仍为待复核研究稿。</strong>本轮按具体评价者、本人契约事项和可比人物来源链补证，不以公司宣传、匿名说法或百科页面直接下个人信用与能力结论。</p>
<p>第7章从0条引用到6条来源陈述，包含历史承诺材料和具名历史争议说法；来源或转载可能重复，不等于6个独立事件。承诺不证明履行；争议中的单方说法不证明指控成立。该观点单列报道发布时间，事件时期、利益关系、回应及原始处理结果仍须核对，且不送入模型分析或风险评分。</p>
<p>第8章从0条引用到11条资料及提名依据，建立李斌/蔚来、李书福/吉利两位候选并分别检索。候选资料含第三方百科及机构介绍，不能自动当作官方任职证明；行业、阶段、职责、时期及指标单位尚未全部对齐，不排名。</p>
<p>前后材料不同，不计算准确率或质量提升百分比。3次有界采集试验共12次新增搜索和18次抓取尝试，另有2次仅用留存原文的摘录试验；具体模型请求和失败分类见验证记录。最终复验复用保存的真实模型输出，没有新增API请求。当前保留76个来源，不把来源数量当作验收标准。</p>
<p>身份及机构附带线索继续保留；姓名与机构核心词的匹配只作待复核线索。同行资料仅用于第8章及引用索引，不进入目标人物履历、人格或风险。普通检索预留请求和抓取预算供本阶段使用，总预算不增加。</p>
<p>Word已导出，包结构单独检查；逐页视觉验收仍未完成。本轮未部署生产或写入共享知识库。下面保留15章实际前后正文和剩余缺口，避免只展示有改善的段落。</p>
<table><thead><tr><th>章节</th><th>引用编号数</th><th>状态</th></tr></thead><tbody>'''
    page += ''.join(table) + '</tbody></table>' + ''.join(sections) + '</html>'
    output = ROOT / 'deliverables/person-reputation-peers-20261020.html'
    output.write_text(page, encoding='utf-8')
    print(json.dumps({'page': str(output), 'chapters': len(chapters)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
