"""Normalize complete review envelopes without inventing verdicts or bindings."""
import json
import re


def review_envelope(raw, diagnostic):
    from json_utils import parse_json_output
    value = parse_json_output(raw)
    if value is None and isinstance(raw, str):
        # Some gateways add prose around otherwise complete JSON. Decode whole
        # objects only; never repair a truncated JSON string or a missing field.
        body = re.sub(r'^\s*<think>.*?</think>\s*', '', raw, flags=re.S)
        decoder = json.JSONDecoder()
        candidates = []
        cursor = 0
        while cursor < len(body):
            start = body.find('{', cursor)
            if start < 0:
                break
            try:
                item, end = decoder.raw_decode(body, start)
            except ValueError:
                # A complete inner object is not a valid substitute for a
                # truncated outer response containing it.
                return None
            if isinstance(item, dict) and ('reviews' in item or 'packet_fingerprint' in item):
                candidates.append(item)
            cursor = end
        if len(candidates) == 1:
            value = candidates[0]
            diagnostic.setdefault('normalizations', []).append('outer_presentation_removed')
        elif len(candidates) > 1:
            diagnostic['ambiguous_envelopes'] = len(candidates)
            return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
            diagnostic.setdefault('normalizations', []).append('encoded_json_unwrapped')
        except ValueError:
            return None
    diagnostic['container_type'] = type(value).__name__
    for _ in range(2):
        if not isinstance(value, dict):
            return value
        containers = [key for key in ('data', 'result') if isinstance(value.get(key), dict)]
        if 'reviews' in value or 'packet_fingerprint' in value:
            if containers:
                diagnostic['ambiguous_envelopes'] = len(containers) + 1
                return None
            # Extra presentation metadata does not carry authorization.
            if set(value) - {'packet_fingerprint', 'reviews'}:
                diagnostic.setdefault('normalizations', []).append('metadata_ignored')
            return {key: value[key] for key in ('packet_fingerprint', 'reviews') if key in value}
        if len(containers) != 1:
            return value
        diagnostic.setdefault('normalizations', []).append('nested_review_unwrapped')
        value = value[containers[0]]
    return value
