"""Inventory retained evidence before attributing report gaps to collection.

Run against an existing delivery; this never calls a model or a provider.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path


def audit(delivery, run, output):
    output.mkdir(parents=True, exist_ok=True)
    support = delivery / 'evidence/deepseek'
    read = lambda path: json.loads(path.read_text(encoding='utf-8'))
    sources = read(support / 'source-snapshots.json')
    digest = read(support / 'company_corpus_digest_package.json')
    review = read(support / 'company_source_review_package.json')
    state = read(run / 'project-state.json')
    report = (support / 'main-report.md').read_text(encoding='utf-8')
    citation_map = read(support / 'citation-map.json')
    chapters = {}
    for match in re.finditer(r'(?ms)^## (\d+)\..*?(?=^## \d+\.|\Z)', report):
        ids = set(re.findall(r'E-[A-Z0-9-]{6,}', match[0]))
        for label in re.findall(r'\[证据(\d+)\]', match[0]):
            ids.update(citation_map[label])
        chapters[int(match[1])] = ids
    inventory = []
    for source in sources:
        records = [r for r in digest['statements'] if r.get('source_url') == source['url']]
        sr = review['source_review'].get(str(source['id']), {})
        ids = set(e for r in records for e in r['evidence_ids'])
        ids.update(e for e in [sr.get('evidence_id')] if e)
        inventory.append({'id': source['id'], 'url': source['url'], 'title': source['title'],
            'chars': len(source.get('content') or ''), 'sha256': hashlib.sha256((source.get('content') or '').encode()).hexdigest(),
            'review_state': sr.get('state'), 'source_kind': sr.get('source_kind'), 'evidence_ids': sorted(ids),
            'statement_count': len(records), 'statement_chapters': sorted({r['chapter'] for r in records}),
            'body_chapters': [n for n, cited in chapters.items() if ids & cited],
            'fetch_status': source.get('source_metadata', {}).get('fetch_status'),
            'original_offset_records': [{'id': r['statement_id'], 'chapter': r['chapter'],
                'text': r['text'], 'context': r['context']} for r in records if r['chapter'] in (6, 10, 11)]})
    gaps = [
        {'id': 'G01', 'class': 1, 'chapter': 2, 'gap': '压缩正文未保留登记股东逐行原值表；已绘图不能替代表格',
         'proof': 'company_governance_package.facts[kind=shareholder] 与 main-report 第2章对照',
         'required_action': '共享原值表渲染，保留不同时点/比例冲突、原出资字段及来源；核验现有图与表'},
        {'id': 'G02', 'class': 1, 'chapter': 11, 'gap': '朝阳区官方仿冒案原文已保留，风险登记包仍为0条',
         'proof': 'source id 541；正文证据057；处罚对象为第三方，不是目标公司',
         'required_action': '原文定位接入结构化外部冒名事项，不认定目标受罚'},
        {'id': 'G03', 'class': 2, 'chapter': 11, 'gap': '意大利、德国、韩国监管措施只在归纳中，未保留监管原件',
         'required_action': '仅定向获取决定、监管通报及整改/恢复后续，区分程序性质和地域'},
        {'id': 'G04', 'class': 1, 'chapter': 12, 'gap': '投资方公告与专项核查原文存在，但无评分指标被概括成无可引用记录',
         'required_action': '补有边界的非评分观察与逐维缺口；基金出资、目标到账、对外认购分开'},
    ]
    for dimension in state['company_assessment_package']['dimensions']:
        gaps.append({'id': 'S-' + dimension['id'], 'class': 3, 'chapter': 12,
            'gap': dimension['reason'], 'dimension': dimension['name'], 'weight': dimension['weight'],
            'anchors': dimension['anchors'], 'score': dimension['score'],
            'required_action': '先审计保留原件，再定向查找对应原始指标；未找到不等于未公开，不填默认分'})
    for name, value in [('source-inventory', inventory), ('gap-checklist-before', gaps),
                        ('baseline-diagnostics', {k: v for k, v in state.items() if k.endswith('_diagnostic')})]:
        (output / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = {'sources': len(sources), 'review_claims': len(review['facts']), 'digest_statements': len(digest['statements']),
        'body_evidence_ids': len(set.union(*chapters.values())), 'gap_items': len(gaps),
        'risk_entries': len(state['company_risk_register_package']['entries']),
        'shareholder_rows': sum(r['kind'] == 'shareholder' for r in state['company_governance_package']['facts']),
        'financial_observations': state['company_assessment_package']['financial_observations'],
        'scored_dimensions': state['company_assessment_package']['diagnostic']['scored_dimensions']}
    (output / 'baseline-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--delivery', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    audit(args.delivery, args.run, args.output)
