"""Provider transport compatibility, independent of report/proposal business logic."""
from copy import deepcopy
import os
from urllib.parse import urlsplit
from langchain.chat_models import init_chat_model as _init_chat_model


def official_deepseek(model, base_url=None):
    host=urlsplit(base_url or os.getenv('BASE_URL','')).hostname
    return str(model or '').lower().startswith('deepseek') and host == 'api.deepseek.com'


def compatible_options(model, options):
    options=dict(options)
    if not official_deepseek(model, options.get('base_url')):
        return options
    extra=deepcopy(options.get('extra_body') or {})
    enabled=extra.pop('enable_thinking', None)
    budget=extra.pop('thinking_budget', None)
    if 'thinking' not in extra:
        mode=('enabled' if enabled is True or budget or options.get('reasoning_effort') else
              'disabled' if enabled is False else os.getenv('DEEPSEEK_THINKING_MODE','disabled'))
        if mode not in {'enabled','disabled'}:
            raise ValueError('invalid_deepseek_thinking_mode')
        extra['thinking']={'type':mode}
    options['extra_body']=extra
    return options


def request_body_options(model, base_url=None):
    if not official_deepseek(model, base_url):
        return {}
    return {'thinking':{'type':os.getenv('DEEPSEEK_THINKING_MODE','disabled')}}


def init_chat_model(*args, **kwargs):
    model=kwargs.get('model', args[0] if args else None)
    return _init_chat_model(*args, **compatible_options(model, kwargs))
