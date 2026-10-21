"""One multimodal model for assistant chat, screenshot reading and summaries."""
import os
from functools import lru_cache

from langchain_openai import ChatOpenAI


@lru_cache(maxsize=1)
def configured_model():
    key = os.getenv('ASSISTANT_API_KEY') or os.getenv('ARK_API_KEY')
    base = os.getenv('ASSISTANT_BASE_URL') or os.getenv('BASE_URL')
    if not key or not base:
        return None
    return ChatOpenAI(model=os.getenv('ASSISTANT_MODEL') or 'qwen3.5-flash', api_key=key,
        base_url=base, temperature=0.1, timeout=30, max_retries=0, max_tokens=1800,
        extra_body={'enable_thinking': False})


def assistant_model(workflow):
    # Small workflow doubles may keep the original test interface.
    getter = getattr(workflow, '_get_assistant_model', None) or workflow._get_model
    return getter()
