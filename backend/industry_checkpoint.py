"""Immutable per-chapter research checkpoints, never final report artifacts."""
import hashlib
import json
import re
from copy import deepcopy

VERSION = 'industry-chapter-checkpoint-v1'
PIPELINE = 'industry-report-evidence-v61-bounded-recovery'

def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def binding(project, cleaned, risk):
    return digest(encode({'project_id':getattr(project,'id',None),
        'target':str(getattr(project,'target_name','')), 'scope':getattr(project,'industry_scope',{}),
        'pipeline':PIPELINE, 'cleaned':digest(cleaned), 'risk':digest(risk)}))

def prefix(project, key):
    pid = getattr(project, 'id', None)
    return f'projects/{pid}/industry_chapter_checkpoints/{key}' if type(pid) is int and pid > 0 else ''

def save_chapter(project, cleaned, risk, chapter, section, package):
    store = getattr(project, 'industry_checkpoint_store', None)
    folder = prefix(project, binding(project, cleaned, risk))
    if store is None or not folder:
        return
    plan = deepcopy(getattr(project, 'industry_statement_plans', {}).get(chapter, {}))
    if not plan:
        return
    # Private checkpoint only. It does not advance report/delivery status.
    row = {'version':VERSION, 'chapter':chapter, 'section':section, 'plan':plan,
           'package_sha256':digest(package), 'run_id':getattr(project,'industry_run_id',None)}
    text = encode(row)
    sha = digest(text)
    store.put_text(f'{folder}/{chapter}-{sha}.json', text, 'application/json; charset=utf-8')
    # Keep a valid previous pointer before replacing the head. Custom stores
    # and interrupted head writes can recover without accepting partial data.
    try:
        previous_text = store.get_text(f'{folder}/{chapter}.json')
        previous = json.loads(previous_text)
        old_sha = previous.get('sha256','')
        if (previous.get('version') == VERSION and isinstance(old_sha,str)
                and re.fullmatch('[0-9a-f]{64}',old_sha)
                and digest(store.get_text(f'{folder}/{chapter}-{old_sha}.json')) == old_sha):
            store.put_text(f'{folder}/{chapter}.previous.json', previous_text,
                           'application/json; charset=utf-8')
    except (FileNotFoundError, ValueError, TypeError, KeyError):
        pass
    except Exception as exc:
        if getattr(exc, 'code', '') not in {'NoSuchKey','NoSuchObject','NoSuchBucket'}:
            raise
    store.put_text(f'{folder}/{chapter}.json', encode({'version':VERSION,'sha256':sha}),
                   'application/json; charset=utf-8')

def restore_chapters(project, cleaned, risk, packages):
    store = getattr(project, 'industry_checkpoint_store', None)
    folder = prefix(project, binding(project, cleaned, risk))
    if store is None or not folder:
        return {}
    sections = {}
    reused = []
    for chapter in (2,3,4,5,6,7,10,11,13):
        package = packages.get(chapter)
        if not isinstance(package,str):
            continue
        for pointer_key in (f'{folder}/{chapter}.json', f'{folder}/{chapter}.previous.json'):
            try:
                pointer = json.loads(store.get_text(pointer_key))
                sha = pointer.get('sha256','')
                if pointer.get('version') != VERSION or not re.fullmatch('[0-9a-f]{64}',sha):
                    continue
                text = store.get_text(f'{folder}/{chapter}-{sha}.json')
                if digest(text) != sha:
                    continue
                row = json.loads(text)
                if (row.get('version') != VERSION or row.get('chapter') != chapter
                        or row.get('package_sha256') != digest(package)
                        or not isinstance(row.get('section'),str) or not isinstance(row.get('plan'),dict)):
                    continue
                plan = row['plan']
                # Every resumed claim still goes through the normal support review.
                project.industry_statement_plans[chapter] = plan
                sections[chapter] = row['section']
                reused.append({'chapter':chapter,'source_run_id':row.get('run_id'),'input_binding':binding(project,cleaned,risk),'review_status':'requires_current_support_review'})
                break
            except (OSError, ValueError, TypeError, KeyError):
                continue
            except Exception:
                # Object-store outages must never turn an unverified pointer into output.
                continue
    project.industry_checkpoint_reuse = reused
    return sections
