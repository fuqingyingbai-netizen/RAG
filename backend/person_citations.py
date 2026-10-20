"""Repair only unambiguous citation formatting inside a supplied allowlist."""


def canonical_reference(value, allowed):
    if not isinstance(value, str):
        return value
    normalized = value.strip().upper()
    if normalized in allowed:
        return normalized
    matches = [eid for eid in allowed if len(normalized) >= 12 and 0 < len(eid)-len(normalized) <= 2 and eid.startswith(normalized)]
    return matches[0] if len(matches) == 1 else value
