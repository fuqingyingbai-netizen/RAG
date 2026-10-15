"""Parse model JSON without treating code fences inside string values as wrappers."""

import json
import re
from typing import Any


def strip_nul(value: Any) -> Any:
    """Remove PostgreSQL-incompatible NULs without changing literal escape text."""
    if isinstance(value, str):
        return value.replace('\x00', '')
    if isinstance(value, dict):
        return {strip_nul(k): strip_nul(v) for k, v in value.items()}
    if isinstance(value, list):
        return [strip_nul(v) for v in value]
    return value


def parse_json_output(text: str) -> Any:
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip().lstrip('\ufeff')
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        pass
    wrapper = re.fullmatch(r'```(?:json)?\s*\n?(.*?)\n?\s*```', raw, flags=re.S | re.I)
    if wrapper is None:
        return None
    try:
        return json.loads(wrapper.group(1).strip())
    except (ValueError, TypeError):
        return None
