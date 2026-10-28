"""Shared, ordered Tavily credentials for research and assistant searches.

Only credential-local failures advance the pool. Bad queries, network errors
and service failures propagate without spending requests on every credential.
State is shared by callers in this Python process, and resets on restart.
"""
import json
import os
import re
import threading
import time

import requests


def tavily_api_keys() -> tuple[str, ...]:
    """An explicit pool supersedes the legacy single key; preserve order."""
    configured = os.getenv("TAVILY_API_KEYS", "").strip()
    if configured.startswith("["):
        try:
            values = json.loads(configured)
        except ValueError:
            raise ValueError("TAVILY_API_KEYS must be a JSON array or separated keys") from None
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError("TAVILY_API_KEYS must contain strings")
    else:
        values = re.split(r"[,;\s]+", configured) if configured else []
    keys = tuple(dict.fromkeys(value.strip() for value in values if value.strip()))
    return keys or tuple(filter(None, [os.getenv("TAVILY_API_KEY", "").strip()]))


class TavilyKeysUnavailable(requests.RequestException):
    def __init__(self, reason, *, response=None, audit=None):
        super().__init__("No Tavily credential is currently available: " + reason.replace("_", " "), response=response)
        self.reason = reason
        self.audit = audit or {}


def _failure_reason(response):
    status = getattr(response, "status_code", None)
    try:
        body = json.dumps(response.json(), ensure_ascii=False).lower()
    except (AttributeError, ValueError, TypeError):
        body = ""
    if status in {402, 432, 433} or (status in {400, 403, 429} and any(term in body for term in (
        "insufficient_quota", "quota_exceeded", "quota exceeded", "quota exhausted",
        "usage limit", "credit limit", "credits exhausted", "insufficient credits",
        "not enough credits", "exceeds your plan", "exceeded your plan", "配额不足", "余额不足",
    ))):
        return "quota_exceeded"
    if status == 401:
        return "unauthorized"
    if status == 403:
        return "access_denied"
    if status == 429:
        return "rate_limited"
    return ""


def _seconds(name, default):
    try:
        value = float(os.getenv(name, str(default)))
        return value if 1 <= value <= 86400 * 31 else default
    except ValueError:
        return default


class TavilyKeyPool:
    def __init__(self, keys):
        self._keys = tuple(keys)
        self._lock = threading.Lock()
        self._cursor = 0
        self._blocked = {}
        self._wrap_recheck_after = 0.0

    def search(self, params, *, timeout=30, post=None):
        """Try eligible keys, with one bounded first-key recheck on wraparound."""
        attempted = set()
        attempt_sequence = []
        failures = []
        last_response = None
        last_reason = "not_configured"
        wrap_pending = False
        wrap_rechecked = False
        while True:
            with self._lock:
                now = time.monotonic()
                index = next((candidate for offset in range(len(self._keys))
                              if (candidate := (self._cursor + offset) % len(self._keys)) not in attempted
                              and self._blocked.get(candidate, (0, ""))[0] <= now), None)
                is_wrap_recheck = False
                # Completing the list must revisit its first key even when an
                # old quota/auth failure put it in quarantine. Also allow a
                # later request to probe recovery while the whole pool cools.
                # A shared deadline prevents concurrent callers from each
                # probing the same exhausted credential. Respect real 429s.
                first_reason = self._blocked.get(0, (0, ""))[1]
                if (len(self._keys) > 1 and not wrap_rechecked
                        and (wrap_pending or index is None)
                        and first_reason in {"quota_exceeded", "unauthorized", "access_denied"}
                        and now >= self._wrap_recheck_after):
                    index = 0
                    is_wrap_recheck = wrap_rechecked = True
                    wrap_pending = False
                    self._wrap_recheck_after = now + _seconds("TAVILY_KEY_WRAP_RECHECK_SECONDS", 60)
                if index is None:
                    if self._blocked and not failures:
                        last_reason = next(iter(self._blocked.values()))[1]
                    break
                blocked_before_request = self._blocked.get(index)
            attempted.add(index)
            attempt_sequence.append(index + 1)
            response = None
            try:
                response = (post or requests.post)(
                    "https://api.tavily.com/search",
                    headers={"Authorization": "Bearer " + self._keys[index]},
                    json={key: value for key, value in params.items() if key != "api_key"},
                    timeout=timeout,
                )
                response.raise_for_status()
            except requests.HTTPError as exc:
                failed_response = exc.response if exc.response is not None else response
                reason = _failure_reason(failed_response)
                if not reason:
                    raise
                last_response, last_reason = failed_response, reason
                failures.append({"key_slot": index + 1, "reason": reason,
                                 "http_status": getattr(failed_response, "status_code", None)})
                if is_wrap_recheck:
                    failures[-1]["wrap_recheck"] = True
                if reason in {"unauthorized", "access_denied"}:
                    cooldown = float("inf")
                elif reason == "quota_exceeded":
                    cooldown = _seconds("TAVILY_KEY_QUOTA_COOLDOWN_SECONDS", 3600)
                else:
                    cooldown = _seconds("TAVILY_KEY_RATE_LIMIT_COOLDOWN_SECONDS", 60)
                    try:
                        cooldown = max(cooldown, float(failed_response.headers.get("Retry-After", "0")))
                    except (AttributeError, TypeError, ValueError):
                        pass
                with self._lock:
                    self._blocked[index] = (time.monotonic() + cooldown, reason)
                    if self._cursor == index:
                        self._cursor = (index + 1) % len(self._keys)
                if index == len(self._keys) - 1 and not wrap_rechecked:
                    wrap_pending = True
                continue
            # Empty successful results are valid; they must not burn other keys.
            payload = response.json()
            with self._lock:
                if self._blocked.get(index) == blocked_before_request:
                    self._cursor = index
                    self._blocked.pop(index, None)
                    if is_wrap_recheck:
                        self._wrap_recheck_after = 0.0
            return payload, {"configured_key_count": len(self._keys), "key_slot": index + 1,
                             "attempted_key_slots": sorted(value + 1 for value in attempted),
                             "key_attempt_sequence": attempt_sequence, "wrap_rechecked": wrap_rechecked,
                             "key_failovers": failures}
        raise TavilyKeysUnavailable(last_reason, response=last_response, audit={
            "configured_key_count": len(self._keys),
            "key_attempt_sequence": attempt_sequence, "wrap_rechecked": wrap_rechecked,
            "attempted_key_slots": sorted(value + 1 for value in attempted), "key_failovers": failures,
        })


_pool_lock = threading.Lock()
_pool = None


def get_tavily_pool():
    """All call sites reuse state, including when WebSearchProvider is recreated."""
    global _pool
    keys = tavily_api_keys()
    with _pool_lock:
        if _pool is None or _pool._keys != keys:
            _pool = TavilyKeyPool(keys)
        return _pool
