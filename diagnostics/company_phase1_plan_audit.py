"""Inspect every actual company checkbox using production strategy methods."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    from research_strategies import get_research_strategy
    strategy = get_research_strategy('company')
    script = (ROOT / 'frontend/script.js').read_text(encoding='utf-8')
    block = script.split('modulesByTarget: { company: [', 1)[1].split('], person:', 1)[0]
    modules = re.findall(r"value:\s*'([^']+)'", block)
    target = '示例制造股份有限公司'
    intake = {'target_type': 'company', 'target_name': target, 'industry': '制造业', 'as_of_date': '2026-10-24'}
    rows = []
    for module in modules:
        questions = strategy.module_questions(module, target, intake['industry'])
        templates = strategy.templates_for_module(module, target, intake['industry'])
        plan = {'modules': [{'name': module, 'research_questions': questions, 'query_templates': templates}]}
        queries = strategy.expand_search_queries(plan, {**intake, 'focus_modules': [module]})
        related = [row for row in queries if row.get('module') == module]
        rows.append({'checkbox': module, 'questions': questions, 'query_templates': templates,
                     'checkbox_query_count': len(related),
                     'queries_with_requirement_ids': sum(bool(row.get('company_requirement_ids')) for row in related),
                     'queries_with_purpose': sum(bool(row.get('query_purpose')) for row in related),
                     'all_expanded_query_count': len(queries)})
    out = ROOT / 'deliverables/company-phase1-20261028' / ('checkbox-plan-' + args.label + '.json')
    out.write_text(json.dumps({'sample_kind': 'synthetic_structural_probe', 'rows': rows}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checkboxes': len(rows), 'fully_requirement_bound': sum(row['checkbox_query_count'] > 0 and
          row['queries_with_requirement_ids'] == row['checkbox_query_count'] for row in rows)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
