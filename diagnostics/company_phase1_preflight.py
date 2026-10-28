"""Bounded live proof through the existing production company/search factories."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'work/company-phase1-20261028/preflight'


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=True)
    os.environ['PYTHON_DOTENV_DISABLED'] = '1'
    sys.path.insert(0, str(ROOT / 'backend'))
    import research_workflow as runtime
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / 'result.json').exists():
        raise RuntimeError('Preflight already recorded; do not repeat unchanged calls')
    secrets = {v for k, v in os.environ.items() if len(v) >= 8 and any(t in k for t in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD'))}
    def write(name, value):
        text = json.dumps(value, ensure_ascii=False, default=str, indent=2)
        for secret in secrets:
            text = text.replace(secret, '[REDACTED]')
        (OUT / name).write_text(text, encoding='utf-8')
    events = []
    def emit(event):
        events.append(event)
        write('events.json', events)
    workflow = runtime.ResearchWorkflow()
    model = workflow._get_company_report_editor_model()
    observed = {}
    class Observed:
        def invoke(self, messages, *args, **kwargs):
            observed['messages'] = messages
            observed['started_at'] = datetime.now(timezone.utc).isoformat()
            started = time.monotonic()
            try:
                result = model.invoke(messages, *args, **kwargs)
                observed.update(response=result.content, response_metadata=result.response_metadata,
                                usage_metadata=getattr(result, 'usage_metadata', None))
                return result
            except Exception as exc:
                observed.update(error_type=type(exc).__name__, error=str(exc))
                raise
            finally:
                observed['elapsed_seconds'] = round(time.monotonic() - started, 3)
                write('model-receipt.json', observed)
    workflow._company_report_editor_model = Observed()
    plan = {'logical_model_requests': 1,
            'model_sdk_max_retries': getattr(model, 'max_retries', None),
            'search_queries': 2, 'search_result_limit': 3, 'fetch_original_limit': 1,
            'model_concurrency': 1, 'search_query_concurrency': 2,
            'model': os.getenv('MODEL'), 'new_report_acceptance': False,
            'search_explicit_preferred_providers': ['serper', 'exa'],
            'configured_search_mode': os.getenv('WEB_SEARCH_PROVIDER', '')}
    write('call-plan.json', plan)
    answer = workflow._invoke_company_report_editor('company_phase1_connectivity',
        '以下是合成连通性样例，不是真实公司或案件：原告甲公司请求100元；法院判乙公司支付60元。'
        '不得将请求额写为判赔额。仅返回JSON：{"sample_kind":"synthetic_connectivity",'
        '"claim":100,"award":60,"currency":"CNY"}。', emit=emit)
    queries = [
        {'module': '收入情况', 'query': '佛山市海天调味食品股份有限公司 2026 半年度报告 经营活动现金流量净额 原文',
         'search_tier': 'authority_first', 'include_domains': ['cninfo.com.cn', 'sse.com.cn', 'hkexnews.hk'],
         'preferred_providers': ['serper'], 'query_purpose': '验证当前入口及补取同口径财务原件'},
        {'module': '公司背景', 'query': '北京金山办公软件股份有限公司 2026 半年度报告 原文',
         'search_tier': 'authority_first', 'include_domains': ['cninfo.com.cn', 'sse.com.cn'],
         'preferred_providers': ['exa'], 'query_purpose': '验证第二引擎当前原件发现入口'},
    ]
    start = time.monotonic()
    searched = workflow._search_query_items_parallel(queries, 3, ['serper', 'exa'], emit=emit)
    write('search-results.json', searched)
    allowed = {'cninfo.com.cn', 'sse.com.cn', 'hkexnews.hk'}
    fetched = None
    for query, rows in searched:
        for row in rows:
            url = row.get('url', '')
            host = (urlsplit(url).hostname or '').lower()
            if not any(host == domain or host.endswith('.' + domain) for domain in allowed):
                continue
            began = time.monotonic()
            try:
                value = runtime.web_search_provider.fetch_url(url, allow_browser=False, document_profile='company')
                fetched = {'url': url, 'result': value, 'elapsed_seconds': round(time.monotonic()-began, 3)}
            except Exception as exc:
                fetched = {'url': url, 'error_type': type(exc).__name__, 'error': str(exc)}
            write('fetched-original.json', fetched)
            break
        if fetched is not None:
            break
    result = {'model': os.getenv('MODEL'), 'model_returned': bool(answer),
              'model_finish_reason': observed.get('response_metadata', {}).get('finish_reason'),
              'model_usage': observed.get('usage_metadata'),
              'model_seconds': observed.get('elapsed_seconds'),
              'search_seconds_including_fetch': round(time.monotonic() - start, 3),
              'search_result_counts': [len(rows) for query, rows in searched],
              'query_audits': [query.get('search_result_audit') for query, rows in searched],
              'original_fetch_attempted': fetched is not None,
              'actual_cost': None, 'cost_reason': '本轮保留记录没有可确认的货币费用；保留原始 token 用量，不推断账单或供应商是否提供费用字段',
              'not_end_to_end_report_acceptance': True,
              'call_plan_sha256': hashlib.sha256((OUT/'call-plan.json').read_bytes()).hexdigest()}
    write('result.json', result)
    write('summary.json', {key: result[key] for key in ('model', 'model_returned', 'model_finish_reason',
          'model_usage', 'model_seconds', 'search_result_counts', 'original_fetch_attempted', 'actual_cost')})
    print(json.dumps(json.loads((OUT/'summary.json').read_text(encoding='utf-8')), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
