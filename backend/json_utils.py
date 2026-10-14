"""Parse model JSON without treating code fences inside string values as wrappers."""

import json
import re
from typing import Any


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
