"""Bound failed company-model requests without treating failure as no evidence."""
import threading
import time


class CompanyModelUnavailable(RuntimeError):
    def __init__(self, *, attempted=False):
        super().__init__('company_model_unavailable')
        self.attempted = attempted


def bounded_company_invoke(invoke, threshold=3, *, cooldown_seconds=30, recovery_attempts=2):
    """Allow bounded recovery after an outage; never manufacture a model result.

    Queued workers wait for one recovery request rather than consuming their
    content retries while the provider is cooling down. A sustained outage still
    stops after a finite number of actual requests. Every successful response
    resets the guard, including a request already in flight when it opened.
    """
    if getattr(invoke, '_company_transport_guard', False):
        return invoke
    if threshold < 1 or cooldown_seconds < 0 or recovery_attempts < 0:
        raise ValueError('invalid company transport recovery limits')
    condition = threading.Condition()
    failures = 0
    retry_at = 0
    recoveries = 0
    probing = False
    exhausted = False

    def call(*args, **kwargs):
        nonlocal failures, retry_at, recoveries, probing, exhausted
        probe = False
        with condition:
            while failures >= threshold:
                if exhausted or recoveries >= recovery_attempts and not probing:
                    raise CompanyModelUnavailable()
                if probing:
                    condition.wait()
                    continue
                remaining = retry_at - time.monotonic()
                if remaining > 0:
                    condition.wait(timeout=remaining)
                    continue
                recoveries += 1
                probing = probe = True
                break
        try:
            answer = invoke(*args, **kwargs)
            if not str(answer or '').strip():
                raise ValueError('empty company model response')
        except Exception:
            with condition:
                failures += 1
                if probe:
                    probing = False
                if failures >= threshold:
                    retry_at = time.monotonic() + cooldown_seconds
                    exhausted = recoveries >= recovery_attempts and not probing
                condition.notify_all()
            raise CompanyModelUnavailable(attempted=True) from None
        with condition:
            failures = 0
            retry_at = recoveries = 0
            exhausted = False
            if probe:
                probing = False
            condition.notify_all()
        return answer

    call._company_transport_guard = True
    return call
