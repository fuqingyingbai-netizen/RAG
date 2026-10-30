"""Locate financial development-sample review facts without accepting a report.

This is an offline acceptance specification, never imported by production. Its
literal anchors locate retained source text; they are not a semantic score.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'work/company-phase1-20261028'


def main():
    specifications = [
        ('haitian', 25, 'H-share financing', [
            ('listing_and_base_issue', '2025 年 6 月 19 日，本公司发行',
             'Separate the listing/issuance date from any bank receipt date; retain shares, HKD issue price, CNY gross amount, costs and actual net amount.'),
            ('overallotment_and_combined_net', '2025 年 7 月 16 日，本公司上市整体协调人',
             'The additional issue belongs to the same financing; preserve its gross/cost/net and combined net without double counting.'),
        ]),
        ('haitian', 165, '2026 first-half comparative metrics', [
            ('auditing_and_period', '未经审计',
             'Attribute the figures to the unaudited first-half report; do not imply an audit opinion.'),
            ('adjusted_comparison', '上年同期 调整后',
             'Keep adjusted and unadjusted comparative columns distinct; do not mix their growth denominators.'),
            ('revenue', '16,146,273,837.53',
             'Retain first-half revenue and the disclosed 6.01% adjusted-comparison growth.'),
            ('parent_profit', '4,190,156,263.00',
             'Keep parent-attributable profit separate from total profit and deducted profit; disclosed growth is 7.13%.'),
            ('operating_cash', '1,224,226,577.61',
             'Positive operating cash declined 18.52%; a decline is not negative cash flow or default.'),
        ]),
        ('kingsoft', 30, '2026 first-half statutory metrics', [
            ('revenue', '3,313,262,599.20',
             'Retain first-half revenue and 24.69% growth.'),
            ('statutory_profit', '2,517,594,330.93',
             'Statutory parent profit grew 236.94%; this is not the company-adjusted growth rate.'),
            ('statutory_deducted_profit', '2,487,375,431.21',
             'Statutory deducted profit grew 241.99%; do not call fund gains nonrecurring merely because they are excluded by a separate company-adjusted metric.'),
            ('operating_cash', '642,693,273.51',
             'Positive operating cash declined 12.96%; preserve the separate company explanation from the full report as attributed counterevidence.'),
        ]),
        ('kingsoft', 2, '2026 first-half full report explanations', [
            ('non_gaap_definition', '该指标定义为在归属于上市公司股东的净利润基础上剔',
             'Company-adjusted profit excludes share-based payments, fund investment returns and their tax effects; it supplements statutory metrics and does not replace them.'),
            ('cash_counterevidence', '剔除本期投资收益浮盈的预缴所得税影响后',
             'Attribute the statement of positive cash-flow growth after this adjustment to the company; retain the statutory 12.96% decrease alongside it.'),
            ('fund_contribution', '公司部分对外投资基金项目产生大额投资收益',
             'Attribute the significant contribution to profit growth to the disclosed fund investments; adjusted parent profit is 108,679.68 ten-thousand CNY, up 28.29%.'),
            ('adjustment_footnote', '公司对经调整的归属于上市公司股东的净利润的定义为',
             'Read the footnote together with the main discussion; do not infer a legal nonrecurring classification or independent verification.'),
        ]),
    ]
    documents = []
    for case, source_id, topic, facts in specifications:
        path = (RUN / 'baseline' / case / 'acceptance.sqlite').resolve()
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
            title, url, content, raw_meta = db.execute(
                'SELECT title,url,content,source_metadata FROM research_sources WHERE id=?', (source_id,)).fetchone()
        metadata = json.loads(raw_meta or '{}')
        text = content or ''
        rows = []
        for fact_id, anchor, requirement in facts:
            start = text.find(anchor)
            if start < 0:
                rows.append({'fact_id': fact_id, 'anchor_found': False, 'requirement': requirement})
                continue
            left = max(0, start - 180)
            right = min(len(text), start + len(anchor) + 700)
            rows.append({'fact_id': fact_id, 'anchor_found': True, 'anchor_start': start,
                         'window_start': left, 'window_end': right,
                         'literal_window': text[left:right], 'requirement': requirement})
        documents.append({'case': case, 'source_id': source_id, 'topic': topic,
                          'title': title, 'url': url,
                          'retained_content_origin': metadata.get('content_origin'),
                          'retained_extraction_status': metadata.get('extraction_status'),
                          'retained_provider_text_is_not_a_direct_fetch': metadata.get('content_origin') == 'provider_text',
                          'source_text_sha256': hashlib.sha256(text.encode()).hexdigest(),
                          'review_facts': rows})
    result = {'version': 'company-phase1-financial-development-review-v1',
              'as_of': '2026-10-24', 'documents': documents,
              'new_model_calls': 0, 'new_search_calls': 0,
              'report_semantic_review': 'pending_same_final_report',
              'report_accepted': False,
              'limitation': 'Source locators and review requirements only. Literal presence does not prove semantic adoption, correct scope or counterevidence preservation.'}
    output = RUN / 'financial-review-spec.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    missing = [(d['case'], r['fact_id']) for d in documents for r in d['review_facts'] if not r['anchor_found']]
    print(json.dumps({'documents': len(documents), 'facts': sum(len(d['review_facts']) for d in documents),
                      'missing_anchors': missing, 'report_accepted': False}, ensure_ascii=False))
    return 1 if missing else 0


if __name__ == '__main__':
    raise SystemExit(main())
