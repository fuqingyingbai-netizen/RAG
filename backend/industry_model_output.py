"""Read industry model text without serializing reasoning or tool blocks as JSON."""
import re
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar

_REQUEST_DEADLINE = ContextVar('industry_request_deadline', default=None)


class MeasuredText(str):
    """String-compatible result carrying only already sanitized usage metadata."""
    def __new__(cls, text, diagnostic):
        value = super().__new__(cls, text)
        value.output_diagnostic = diagnostic
        return value


@contextmanager
def request_deadline(deadline):
    token = _REQUEST_DEADLINE.set(deadline)
    try:
        yield
    finally:
        _REQUEST_DEADLINE.reset(token)


def remaining_request_timeout():
    deadline = _REQUEST_DEADLINE.get()
    return None if deadline is None else max(0.0, deadline-time.monotonic())


class IndustryModelOutputError(ValueError):
    """A fixed diagnostic code; never include the provider response or secrets."""

    def __init__(self, code, diagnostics=None):
        self.code = code
        self.diagnostics = diagnostics or {}
        super().__init__(code)


def generation_options(model):
    """Qwen's hidden thinking otherwise shares the capped visible-output budget.

    Do not send provider-specific options to unrelated model families.
    """
    return {'extra_body': {'enable_thinking': False}} if 'qwen3' in str(model).lower() else {}


def stage_output_options(stage, default):
    """A completion cap includes hidden reasoning on some compatible gateways."""
    try:
        limit = int(os.getenv(f'INDUSTRY_{stage.upper()}_MAX_OUTPUT_TOKENS', str(default)))
    except ValueError:
        limit = default
    if limit < 0:
        limit = default
    return {'max_tokens': min(131072, max(256, limit))} if limit else {}


def invoke_model(model, messages, *, timeout=None):
    """Keep long reasoning responses active without accepting partial answers.

    Streaming is transport only: callers still validate the completed message.
    The wall budget includes reasoning, and an interrupted stream is discarded.
    """
    options = {'timeout': timeout} if timeout is not None else {}
    if os.getenv('INDUSTRY_MODEL_STREAMING_ENABLED', 'false').lower() not in {'1', 'true', 'yes', 'on'}:
        return model.invoke(messages, **options)
    budget = timeout if timeout is not None else getattr(model, 'request_timeout', None)
    deadline = time.monotonic() + budget if isinstance(budget, (int, float)) else None
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError('model_request_timeout')
    result = None
    stream = model.stream(messages, stream_usage=True, **options)
    try:
        for chunk in stream:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError('model_request_timeout')
            result = chunk if result is None else result + chunk
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError('model_request_timeout')
    finally:
        close = getattr(stream, 'close', None)
        if close:
            close()
    if result is None:
        raise IndustryModelOutputError('empty_model_output')
    if not (getattr(result, 'response_metadata', None) or {}).get('finish_reason'):
        raise IndustryModelOutputError('incomplete_model_stream')
    return result


def conclusion_output_limit():
    """Zero/unset omits max_tokens; the provider still enforces its own limit."""
    try:
        limit = int(os.getenv('INDUSTRY_CONCLUSION_MAX_OUTPUT_TOKENS', '0'))
    except ValueError:
        return None
    return limit if limit > 0 else None


def stage_timeout(role):
    defaults = {'planner': 120, 'selector': 120, 'writer': 360, 'review': 240}
    try:
        value = int(os.getenv(f'INDUSTRY_{role.upper()}_TIMEOUT_SECONDS', str(defaults[role])))
    except ValueError:
        value = defaults[role]
    return max(10, min(600, value))


def generation_error_code(exc):
    if isinstance(exc, IndustryModelOutputError):
        return exc.code
    return {'LengthFinishReasonError': 'truncated_model_output',
            'ContentFilterFinishReasonError': 'refused_model_output',
            'APITimeoutError': 'model_request_timeout',
            'APIConnectionError': 'model_connection_failed',
            'RateLimitError': 'model_rate_limited'}.get(type(exc).__name__,
                'model_request_timeout' if isinstance(exc, TimeoutError) else 'model_invocation_failed')


def output_diagnostics(result):
    """Allowlisted usage is useful even when text is empty or truncated."""
    metadata = getattr(result, 'response_metadata', None) or {}
    finish = metadata.get('finish_reason', '') if isinstance(metadata, dict) else ''
    content = getattr(result, 'content', None)
    diagnostic = {'finish_reason': finish if isinstance(finish, str) and re.fullmatch(r'[a-z_]{0,40}', finish) else 'unknown',
                  'output_chars': len(content) if isinstance(content, str) else 0}
    usage = getattr(result, 'usage_metadata', None) or {}
    if isinstance(usage, dict):
        diagnostic['token_usage'] = {k: usage[k] for k in ('input_tokens', 'output_tokens', 'total_tokens')
                                    if type(usage.get(k)) is int and usage[k] >= 0}
        details = usage.get('output_token_details') or {}
        if isinstance(details, dict) and type(details.get('reasoning')) is int and details['reasoning'] >= 0:
            diagnostic['token_usage']['reasoning_tokens'] = details['reasoning']
    return diagnostic


def error_diagnostics(exc):
    if isinstance(exc, IndustryModelOutputError):
        return exc.diagnostics
    # The SDK may reject a length-limited JSON completion before creating an
    # AIMessage. Extract counts only; provider prose, URLs and keys stay private.
    completion = getattr(exc, 'completion', None)
    usage = getattr(completion, 'usage', None)
    counts = {}
    for source, target in [('prompt_tokens', 'input_tokens'), ('completion_tokens', 'output_tokens'), ('total_tokens', 'total_tokens')]:
        value = getattr(usage, source, None)
        if type(value) is int and value >= 0:
            counts[target] = value
    reasoning = getattr(getattr(usage, 'completion_tokens_details', None), 'reasoning_tokens', None)
    if type(reasoning) is int and reasoning >= 0:
        counts['reasoning_tokens'] = reasoning
    return {'token_usage': counts} if counts else {}


def response_text(result):
    """Return text and allowlisted diagnostics. Never salvage truncated output."""
    metadata = getattr(result, 'response_metadata', None) or {}
    raw_finish = metadata.get('finish_reason', '') if isinstance(metadata, dict) else ''
    finish = raw_finish if isinstance(raw_finish, str) and re.fullmatch(r'[a-z_]{0,40}', raw_finish) else 'unknown'
    diagnostic = output_diagnostics(result)
    if finish in {'length', 'max_tokens'}:
        raise IndustryModelOutputError('truncated_model_output', diagnostic)
    extra = getattr(result, 'additional_kwargs', None) or {}
    if finish in {'content_filter', 'refusal'} or (isinstance(extra, dict) and extra.get('refusal')):
        raise IndustryModelOutputError('refused_model_output')
    content = getattr(result, 'content', None)
    if isinstance(content, str):
        text, shape = content, 'string'
    elif isinstance(content, list):
        pieces = []
        for block in content:
            if isinstance(block, str):
                pieces.append(block)
            elif isinstance(block, dict) and block.get('type') in {'text', 'output_text'} and isinstance(block.get('text'), str):
                pieces.append(block['text'])
            elif isinstance(block, dict) and block.get('type') in {'reasoning', 'thinking', 'reasoning_content'}:
                continue
            else:
                raise IndustryModelOutputError('non_text_model_output')
        text, shape = ''.join(pieces), 'text_blocks'
    else:
        raise IndustryModelOutputError('non_text_model_output')
    if not text.strip():
        raise IndustryModelOutputError('empty_model_output', diagnostic)
    diagnostics = {'content_shape': shape, 'finish_reason': finish, 'output_chars': len(text)}
    usage = getattr(result, 'usage_metadata', None) or {}
    if isinstance(usage, dict):
        diagnostics['token_usage'] = {k: usage[k] for k in ('input_tokens', 'output_tokens', 'total_tokens')
                                      if type(usage.get(k)) is int and usage[k] >= 0}
        details = usage.get('output_token_details') or {}
        if isinstance(details, dict) and type(details.get('reasoning')) is int and details['reasoning'] >= 0:
            diagnostics['token_usage']['reasoning_tokens'] = details['reasoning']
    return text, diagnostics
