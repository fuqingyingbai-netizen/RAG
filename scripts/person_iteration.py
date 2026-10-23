"""Exact-input response reuse for bounded, chapter-level research iterations."""
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


def copy_retained_tree(source, destination):
    """Preserve nested object keys on Windows without the legacy 260 limit."""
    def native(path):
        value = str(Path(path).resolve())
        if os.name == 'nt' and not value.startswith('\\\\?\\'):
            return '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value
        return value
    shutil.copytree(native(source), native(destination), dirs_exist_ok=True)


def fingerprint(role, prompt):
    return hashlib.sha256((role + '\n' + prompt).encode('utf-8')).hexdigest()


def chapter_number(role, prompt):
    import re
    match = re.search(r'人物背景调查第(\d+)章', prompt)
    return int(match[1]) if match else None


class ChapterInvoker:
    def __init__(self, invoke, output, safe=lambda x: x, reuse=None, rewrite=(), deadline=None, force_rewrite=True, min_start_seconds=95, model_context=None):
        self.invoke, self.output, self.safe = invoke, Path(output), safe
        self.rewrite = set(rewrite) | ({1, 13} if rewrite else set())
        self.force_rewrite = force_rewrite
        self.min_start_seconds = min_start_seconds
        self.model_context = model_context
        self.deadline = datetime.fromisoformat(deadline.replace('Z', '+00:00')) if deadline else None
        self.cache, self.events = {}, []
        if reuse:
            root = Path(reuse)
            inputs = [json.loads(x) for x in (root / 'chapter-model-inputs.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
            answers = [json.loads(x) for x in (root / 'chapter-model-responses.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
            # Role alone is insufficient: a changed source, date or prompt
            # invalidates an old answer. Failed requests have no answer.
            for row in inputs:
                if model_context is not None and row.get('model_context') != model_context:
                    continue
                key = fingerprint(row['role'], row['prompt'])
                response = next((a for a in reversed(answers) if a['role'] == row['role'] and
                                 (a.get('input_sha256') == key or
                                  not a.get('input_sha256') and sum(i['role'] == row['role'] for i in inputs) == 1)), None)
                if response and (model_context is None or response.get('model_context') == model_context):
                    self.cache[key] = response['response']

    def __call__(self, role, prompt, emit=None):
        key, chapter = fingerprint(role, prompt), chapter_number(role, prompt)
        event = {'role': role, 'chapter': chapter, 'input_sha256': key, 'model_context': self.model_context}
        self.events.append(event)
        if key in self.cache and (chapter not in self.rewrite or not self.force_rewrite):
            event['status'] = 'exact_input_reused'
            response = self.cache[key]
        else:
            if self.cache and chapter is not None and chapter not in self.rewrite:
                event['status'] = 'changed_input_outside_requested_chapters'
                raise RuntimeError('Changed chapter input is outside the bounded rewrite request')
            if self.deadline and (self.deadline - datetime.now(timezone.utc)).total_seconds() < self.min_start_seconds:
                event['status'] = 'time_budget_exhausted'
                raise RuntimeError('User time budget exhausted; no new model request started')
            event['status'] = 'requested'
            self.write('chapter-model-inputs.jsonl', {'role': role, 'prompt': prompt, 'input_sha256': key, 'model_context': self.model_context})
            try:
                response = self.invoke(role, prompt, emit)
            except Exception as exc:
                event.update(status='failed', exception_type=type(exc).__name__)
                self.write('chapter-iteration-events.jsonl', event)
                raise
            event['status'] = 'returned'
        if event['status'] == 'exact_input_reused':
            self.write('chapter-model-inputs.jsonl', {'role': role, 'prompt': prompt, 'input_sha256': key, 'model_context': self.model_context})
        self.write('chapter-model-responses.jsonl', {'role': role, 'response': response, 'input_sha256': key, 'model_context': self.model_context})
        self.write('chapter-iteration-events.jsonl', event)
        return response

    def write(self, name, value):
        with (self.output / name).open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(self.safe(value), ensure_ascii=False) + '\n')


def compare_sections(before, after):
    from person_evidence import split_sections, cited_ids
    old, new = split_sections(before), split_sections(after)
    return [{'chapter': n, 'text_changed': old.get(n) != new.get(n),
             'before_sha256': hashlib.sha256(old.get(n, '').encode()).hexdigest(),
             'after_sha256': hashlib.sha256(new.get(n, '').encode()).hexdigest(),
             'before_chars': len(old.get(n, '')), 'after_chars': len(new.get(n, '')),
             'added_evidence_ids': sorted(cited_ids(new.get(n, '')) - cited_ids(old.get(n, ''))),
             'removed_evidence_ids': sorted(cited_ids(old.get(n, '')) - cited_ids(new.get(n, '')))} for n in range(1, 16)]
