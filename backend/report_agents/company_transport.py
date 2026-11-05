"""Sanitized provider diagnostics and one bounded retry owner for company work."""
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
import threading
import time
from company_flow_state import CompanyFlowLimit, fingerprint


_STEP=threading.local()


@contextmanager
def step_budget(budget):
    previous=getattr(_STEP,'budget',None)
    _STEP.budget=budget
    try:yield
    finally:_STEP.budget=previous


def safe_identifier(value):
    value = str(value or '')
    return value[:128] if re.fullmatch(r'[A-Za-z0-9_.:/-]{1,128}', value) and 'sk-' not in value else ''


def failure_diagnostic(exc, *, stage='', input_hash='', elapsed=0, attempts=1):
    if isinstance(exc, CompanyModelUnavailable):
        return {**exc.diagnostic, 'stage': stage or exc.diagnostic.get('stage', ''),
                'input_sha256': input_hash or exc.diagnostic.get('input_sha256', '')}
    response = getattr(exc, 'response', None)
    status = getattr(exc, 'status_code', None) or getattr(response, 'status_code', None)
    headers = getattr(response, 'headers', {}) or {}
    message = str(exc).lower()  # Inspected only; never persisted or logged.
    name = type(exc).__name__
    category = 'unknown_provider_error'; retryable = False
    if isinstance(exc, CompanyFlowLimit): category = 'budget_exhausted';attempts=0
    elif name=='WorkflowPaused':category='paused';attempts=0
    elif status == 401: category = 'authentication'
    elif status == 403: category = 'permission'
    elif status == 402 or 'insufficient_balance' in message: category = 'balance'
    elif status == 429: category, retryable = 'rate_limit', True
    elif status and 500 <= status < 600: category, retryable = 'temporary_server', True
    elif status == 413 or any(s in message for s in ('context_length', 'context length', 'maximum context', 'too many tokens')): category = 'context_limit'
    elif 'timeout' in name.lower() or isinstance(exc, TimeoutError): category, retryable = 'timeout', True
    elif any(s in name.lower() for s in ('connection', 'connecterror', 'readerror', 'remoteprotocol')): category, retryable = 'connection', True
    elif 'truncated' in message: category = 'output_truncated'
    elif 'incomplete' in message or 'empty company model' in message: category = 'output_incomplete'
    elif isinstance(exc, (ValueError, TypeError)): category = 'output_format'
    elif status in {400, 404, 422}: category = 'configuration'
    retry_after = None
    hint = headers.get('retry-after') or headers.get('Retry-After')
    if hint:
        try: retry_after = max(0, float(hint))
        except (ValueError, TypeError):
            try: retry_after = max(0, (parsedate_to_datetime(hint)-datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError, OverflowError): pass
    return {'category':category,'exception_type':safe_identifier(name),'http_status':status,
        'provider_request_id':safe_identifier(getattr(exc,'request_id','') or headers.get('x-request-id') or headers.get('request-id')),
        'stage':stage,'input_sha256':input_hash,'retryable':retryable,'retry_after_seconds':retry_after,
        'attempts':attempts,'seconds':round(elapsed,3),'request_invoked':attempts>0,
        'request_sent':True if status or getattr(exc,'company_response_received',False) else None if attempts else False,
        'usage':getattr(exc,'company_usage',None) or {}}


class CompanyModelUnavailable(RuntimeError):
    def __init__(self, *, attempted=False, diagnostic=None):
        self.diagnostic=diagnostic or {'category':'unknown_provider_error' if attempted else 'protection_not_sent','attempts':int(attempted),
            'request_invoked':attempted,'request_sent':None if attempted else False,'retryable':False}
        self.attempted=attempted
        self.attempts=int(self.diagnostic.get('attempts',int(attempted)))
        super().__init__('company_model_unavailable:'+self.diagnostic['category'])


def invocation_attempts(invoke):
    local=getattr(invoke,'_company_last_call',None)
    return int(getattr(local,'attempts',1)) if local is not None else 1


def bounded_company_invoke(invoke, threshold=3, *, cooldown_seconds=30, recovery_attempts=0,
                           max_attempts=3, sleep=time.sleep):
    """Transient retries have one owner. A new run can resume an open circuit.

    SDK retries must be disabled. Identical stage/input cannot spend another
    three requests in an outer content-repair loop. Queued work is not HTTP.
    Legacy recovery parameters remain accepted; no hidden probes are issued.
    """
    if getattr(invoke,'_company_transport_guard',False): return invoke
    if threshold<1 or max_attempts not in range(1,4) or cooldown_seconds<0 or recovery_attempts<0:
        raise ValueError('invalid company transport recovery limits')
    lock=threading.RLock();spent={};failures=0;fatal=None;last_call=threading.local()
    def call(*args,**kwargs):
        nonlocal failures,fatal
        last_call.attempts=0
        stage=str(args[0]) if args else str(kwargs.get('role','company_model'))
        key=(fingerprint([stage,args[1] if len(args)>1 else kwargs['prompt']]) if len(args)>1 or 'prompt' in kwargs else
            fingerprint([args,{k:v for k,v in kwargs.items() if k not in {'trace','trace_emit','emit','usage_sink'}}]))
        with lock:
            if fatal or failures>=threshold or spent.get(key,0)>=max_attempts:
                raise CompanyModelUnavailable(diagnostic={'category':'protection_not_sent',
                    'blocked_by':fatal or ('circuit_open' if failures>=threshold else 'identical_input_attempt_limit'),'stage':stage,'input_sha256':key,'attempts':0,
                    'request_invoked':False,'request_sent':False,'retryable':False})
        started=time.monotonic();history=[]
        for attempt in range(max_attempts):
            with lock:
                if spent.get(key,0)>=max_attempts:break
                spent[key]=spent.get(key,0)+1
            budget=getattr(_STEP,'budget',None)
            if budget is not None:
                if budget.get('attempts',0)>=3:
                    raise CompanyModelUnavailable(diagnostic={'category':'protection_not_sent','blocked_by':'step_attempt_limit',
                        'attempts':0,'stage':stage,'input_sha256':key,'request_invoked':False,'request_sent':False,'retryable':False})
                budget['attempts']=budget.get('attempts',0)+1
            try:
                last_call.attempts+=1
                answer=invoke(*args,**kwargs)
                if not str(answer or '').strip():raise ValueError('empty company model response')
            except CompanyFlowLimit:raise
            except CompanyModelUnavailable as exc:
                if not exc.attempted:
                    last_call.attempts=max(0,last_call.attempts-1)
                    if budget is not None:budget['attempts']=max(0,budget.get('attempts',0)-1)
                if exc.diagnostic.get('category') in {'authentication','permission','balance','configuration'}:
                    with lock:fatal=exc.diagnostic['category']
                raise
            except Exception as exc:
                diagnostic=failure_diagnostic(exc,stage=stage,input_hash=key,
                    elapsed=time.monotonic()-started,attempts=attempt+1)
                history.append(diagnostic)
                with lock:
                    # A context/format repair is local to this input. It is
                    # not evidence that the provider is unavailable globally.
                    failures=failures+1 if diagnostic.get('retryable') else 0
                    if diagnostic['category'] in {'authentication','permission','balance','configuration'}:fatal=diagnostic['category']
                if not diagnostic.get('retryable') or attempt+1>=max_attempts:
                    raise CompanyModelUnavailable(attempted=any(h.get('request_invoked') for h in history),
                        diagnostic={**diagnostic,'attempts':sum(h.get('attempts',1) for h in history) if isinstance(exc,CompanyModelUnavailable) else len(history),'history':history}) from exc
                delay=diagnostic.get('retry_after_seconds')
                delay=delay if delay is not None else min(cooldown_seconds,2**attempt)
                if delay>60:
                    raise CompanyModelUnavailable(attempted=True,diagnostic={**diagnostic,
                        'deferred_until':time.time()+delay,'history':history}) from exc
                sleep(delay)
                continue
            with lock:failures=0
            return answer
        raise CompanyModelUnavailable()
    call._company_transport_guard=True
    call._company_last_call=last_call
    return call
