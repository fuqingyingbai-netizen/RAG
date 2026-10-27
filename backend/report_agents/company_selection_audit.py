"""Retain source-level candidate/delivery transitions without changing selection."""
from collections import Counter


def selection_audit(candidates,delivered):
    def ids(record):
        # Personnel parsers retain the originating card separately from its
        # parsed row; use its own ID even after mirror merging.
        if isinstance(record,tuple):record=record[0]
        return record.get('evidence_ids') or [record.get('evidence_id')]
    selected=Counter(eid for row in delivered for eid in ids(row) if eid)
    counts=Counter(eid for row in candidates for eid in ids(row) if eid)
    return {eid:{'candidate_claims':count,'delivered_claims':selected[eid],
                 'state':'delivered_to_chapter' if selected[eid] else 'not_selected_by_chapter_policy'}
            for eid,count in counts.items()}
