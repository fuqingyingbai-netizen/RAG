"""Durable native routing receipts, always revalidated against current inputs.

This journal is progress, never a report or delivery approval. Exclusions are
deliberately reviewed again, matching the existing whole-stage cache policy.
"""
import hashlib
import json
import re
from threading import RLock

from report_agents.company_checkpoint import encode, prefix, scope
from report_agents.company_information_usage import VERSION as ROUTING_VERSION, routing_fingerprint, validate_review

VERSION = 'company-information-routing-journal-v1'
_LOCK = RLock()


def binding(project, outline):
    return {'version': VERSION, 'routing_version': ROUTING_VERSION,
            'project_id': project.id, 'target_name': str(project.target_name),
            'review_scope': scope(project),
            'outline_sha256': hashlib.sha256(encode(outline).encode()).hexdigest()}


def _index(store, folder, expected):
    try:
        value = json.loads(store.get_text(folder + '/information-routing-current.json'))
    except (FileNotFoundError, ValueError):
        return {**expected, 'entries': {}}
    except Exception as exc:
        if getattr(exc, 'code', '') in {'NoSuchKey', 'NoSuchObject', 'NoSuchBucket'}:
            return {**expected, 'entries': {}}
        raise
    if (not isinstance(value, dict) or any(value.get(k) != v for k, v in expected.items())
            or not isinstance(value.get('entries'), dict)):
        return {**expected, 'entries': {}}
    return value


def checkpoint_batch(project, receipt, outline, emit=None, trace_emit=None):
    store = getattr(project, 'company_generation_checkpoint_store', None)
    folder = prefix(project)
    if store is None or not folder:
        return False
    try:
        expected = binding(project, outline)
        if (receipt.get('routing_version') != ROUTING_VERSION
                or receipt.get('target_name') != expected['target_name']
                or receipt.get('review_scope') != expected['review_scope']):
            return False
        hashes = receipt.get('routing_record_hashes', {})
        entries = {iid: fingerprint for iid, fingerprint in hashes.items()
                   if iid in receipt.get('information_ids', [])
                   and isinstance(fingerprint, str) and re.fullmatch(r'[0-9a-f]{64}', fingerprint)
                   and isinstance(receipt.get('decisions', {}).get(iid), dict)
                   and receipt['decisions'][iid].get('status') == 'use'}
        if not entries:
            return False
        text = encode({**expected, 'receipt': receipt})
        digest = hashlib.sha256(text.encode()).hexdigest()
        # Publish only after the immutable entry succeeds. Read and merge under
        # the same lock so simultaneous native batch completions cannot clobber.
        with _LOCK:
            index = _index(store, folder, expected)
            store.put_text(folder + '/information-routing/' + digest + '.json', text,
                           'application/json; charset=utf-8')
            updated = {**index['entries'], **{iid: {'sha256': digest, 'input_sha256': fingerprint}
                                             for iid, fingerprint in entries.items()}}
            store.put_text(folder + '/information-routing-current.json',
                           encode({**expected, 'entries': updated}), 'application/json; charset=utf-8')
        return True
    except Exception as exc:
        if emit:
            emit(trace_emit, 'report', 'company_checkpoint', '信息用途批次恢复回执保存失败',
                 type(exc).__name__ + '；未保存批次不计为可恢复进度。', status='warning')
        return False


def read_decisions(project, records, outline, *, store=None):
    store = store or getattr(project, 'company_generation_checkpoint_store', None)
    folder = prefix(project)
    if store is None or not folder:
        return {}
    expected = binding(project, outline)
    try:
        with _LOCK:
            index = _index(store, folder, expected)
    except Exception:
        return {}
    loaded = {}; decisions = {}
    for row in records:
        iid = row['information_id']; entry = index['entries'].get(iid)
        if not isinstance(entry, dict):
            continue
        digest = entry.get('sha256')
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            continue
        fingerprint = routing_fingerprint(row, str(project.target_name), expected['review_scope'], outline)
        if entry.get('input_sha256') != fingerprint:
            continue
        try:
            if digest not in loaded:
                text = store.get_text(folder + '/information-routing/' + digest + '.json')
                if hashlib.sha256(text.encode()).hexdigest() != digest:
                    loaded[digest] = None
                else:
                    payload = json.loads(text)
                    loaded[digest] = (payload if isinstance(payload, dict)
                                      and all(payload.get(k) == v for k, v in expected.items()) else None)
            payload = loaded[digest]
            if not payload:
                continue
            receipt = payload['receipt']
            if (receipt.get('routing_version') != ROUTING_VERSION
                    or receipt.get('target_name') != expected['target_name']
                    or receipt.get('review_scope') != expected['review_scope']
                    or iid not in receipt.get('information_ids', [])
                    or receipt.get('routing_record_hashes', {}).get(iid) != fingerprint):
                continue
            candidate = receipt.get('decisions', {}).get(iid)
            if not isinstance(candidate, dict) or candidate.get('status') != 'use':
                continue
            checked, errors = validate_review([row], {'records': [candidate]}, outline)
            if not errors and iid in checked:
                decisions[iid] = checked[iid]
        except Exception:
            continue
    return decisions
