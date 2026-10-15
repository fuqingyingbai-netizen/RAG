"""Account failures are collection gaps, never negative company findings."""
import hashlib
import json
import re
import time
from datetime import datetime


def failure_kind(payload):
    """Classify error envelopes only; an authentic zero-result is not an error."""
    error = payload.get('error') if isinstance(payload, dict) else payload
    if not error:
        return ''
    text = json.dumps(error, ensure_ascii=False).lower()
    if any(x in text for x in ('credit_balance_insufficient', '余额不足', '积分不足', 'quota_exceeded',
                                '配额已用完', '配额不足', 'insufficient_quota', 'quota exceeded',
                                'quota exhausted', 'insufficient balance')):
        return 'quota_exceeded'
    if re.search(r'\b401\b|unauthorized|invalid[_ -]?(?:token|api[_ -]?key)|鉴权失败|无效.{0,5}(?:密钥|令牌)', text):
        return 'unauthorized'
    if re.search(r'\b429\b|rate.?limit|too many requests|请求过于频繁|限流', text):
        return 'rate_limited'
    if re.search(r'\b403\b|forbidden|permission denied|access denied|权限不足', text):
        return 'access_denied'
    if any(x in text for x in ('未启用', '未配置', '未开通', 'not enabled', 'not configured', 'disabled')):
        return 'tool_unavailable'
    return 'request_failed'


class CompanyPlatformAudit:
    """One provider pass, with a short credential-scoped in-memory circuit."""
    def __init__(self, project, provider, credential, cache, enabled=True):
        self.project, self.provider, self.enabled = project, provider, enabled
        self.cache = cache
        self.key = (provider, hashlib.sha256(credential.encode()).hexdigest())
        self.plan = []
        self.attempted = set()
        self.failed_tools = set()
        self.stop_reason = ''

    def planned(self, tools):
        self.plan.extend(t for t in tools if t not in self.plan)

    def call(self, function, url, headers, tool, arguments, **kwargs):
        try:
            return function(url, headers, tool, arguments, **kwargs)
        except Exception as exc:
            self._transport_failure(tool, arguments, exc)
            raise

    def initialize(self, function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as exc:
            self._transport_failure('initialize', {}, exc)
            raise

    def _transport_failure(self, tool, arguments, exc):
        if self.enabled:
            self.result(tool, arguments, {'error': {'code': 'transport_error', 'message': type(exc).__name__}})
            self.stop_reason = 'transport_failed'
            self.finish_unqueried()

    def record(self, tool, arguments, status, reason='', error=None):
        if not self.enabled:
            return
        rows = getattr(self.project, 'company_professional_platform_attempts', None)
        if rows is None:
            rows = []
            self.project.company_professional_platform_attempts = rows
        row = {'provider': self.provider, 'tool': tool, 'arguments': dict(arguments),
               'status': status, 'reason': reason, 'retrieved_at': datetime.now().isoformat(timespec='seconds')}
        if isinstance(error, dict):
            # Keep machine diagnostics, not external instructions or credentials.
            row['error_code'] = error.get('code')
            data = error.get('data')
            if isinstance(data, dict):
                row['error_type'] = data.get('error_type')
                row['quota_status'] = data.get('quota_status')
        rows.append(row)
        if self.provider == 'qcc' and tool in {
            'get_company_risk_scan', 'get_administrative_penalty', 'get_judicial_documents',
            'get_judicial_document_detail', 'get_service_announcement', 'get_filing_information',
            'get_court_announcement', 'get_hearing_announcement',
            'get_guarantee_info', 'get_stock_pledge_info',
        }:
            judicial = getattr(self.project, 'company_judicial_query_attempts', None)
            if judicial is None:
                judicial = []
                self.project.company_judicial_query_attempts = judicial
            judicial.append({**row, 'query': arguments.get('searchKey', '')})

    def cached_failure(self):
        if not self.enabled:
            return False
        entry = self.cache.get(self.key)
        if entry and entry[1] > time.monotonic():
            self.stop_reason = entry[0]
            self.finish_unqueried()
            return True
        self.cache.pop(self.key, None)
        return False

    def result(self, tool, arguments, payload):
        if not self.enabled:
            return False
        self.attempted.add(tool)
        reason = failure_kind(payload)
        self.record(tool, arguments, 'failed' if reason else 'returned', reason,
                    payload.get('error') if isinstance(payload, dict) else None)
        if reason:
            self.failed_tools.add(tool)
        # A tool-specific 403 does not establish that the whole account is bad.
        if reason in {'quota_exceeded', 'unauthorized', 'rate_limited'}:
            self.stop_reason = reason
            self.cache[self.key] = (reason, time.monotonic() + (60 if reason == 'rate_limited' else 900))
            self.finish_unqueried()
            return True
        return False

    def finish_unqueried(self):
        for tool in self.plan:
            if tool not in self.attempted:
                self.record(tool, {}, 'not_queried', self.stop_reason)
                self.attempted.add(tool)


def restore_platform_audit(project, audit):
    rows = audit.get('attempts') or []
    project.company_professional_platform_attempts = rows
    project.company_judicial_query_attempts = audit.get('judicial_query_attempts') or []
