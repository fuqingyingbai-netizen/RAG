"""Probe one complete native focus batch; never transplant its response.

This diagnoses input/output capacity and formatting only. A successful probe is
not either of the production readers, not a semantic audit and not a report.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'work/company-phase1-20261028'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', choices=['haitian', 'kingsoft'])
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=True)
    os.environ['PYTHON_DOTENV_DISABLED'] = '1'
    sys.path.insert(0, str(ROOT / 'backend'))
    from report_agents.company_presentation import build_presentation, main_usage
    from report_agents.company_main_focus import mandatory_full_record, focus_batches, focus_prompt, validate_focus_answers
    from report_agents.company_event_evidence import _object_answer
    import research_workflow
    import httpx

    store = RUN / 'native' / args.case / 'objects'
    directory = store / 'projects/1/company_generation_checkpoint'
    pointer = json.loads((directory / 'current.json').read_text(encoding='utf-8'))
    raw = (store / pointer['key']).read_bytes()
    assert sha(raw) == pointer['sha256']
    checkpoint = json.loads(raw)
    usage = checkpoint['packages']['company_information_usage_cache']
    index = json.loads((directory / 'presentation-current.json').read_text(encoding='utf-8'))
    assert index['source_fingerprint'] == checkpoint['source_fingerprint']
    assert index['target_name'] == checkpoint['target_name']
    batches = []
    for key, digest in index['entries'].items():
        raw = (directory / 'presentation' / (digest + '.json')).read_bytes()
        assert sha(raw) == digest
        batch = json.loads(raw)
        assert batch['input_sha256'] == key
        batches.append(batch)
    def no_model(*args, **kwargs):
        raise BaseException('The offline restore must not request a new placement.')
    placement = build_presentation(usage, checkpoint['target_name'], index['scope'], no_model,
                                   previous={**index, 'batches': batches}, workers=1)
    assert not placement['diagnostic'].get('pending_information_ids')
    records = main_usage(usage, placement)['records']
    optional = [r for r in records if not mandatory_full_record(r, placement['placements'].get(r['information_id']))]
    jobs = list(focus_batches(optional))
    rows = max(jobs, key=lambda rows: len(focus_prompt(rows, checkpoint['target_name'], index['scope'])))
    role = '公司主报告事实选择'
    prompt = focus_prompt(rows, checkpoint['target_name'], index['scope'])
    messages = [{'role': 'system', 'content': '你是严谨的公司研究编辑与核对员。按当前任务精编或独立审稿；仅使用给定原文和结构化证据，不新增事实或来源，输出任务要求的完整格式。'},
                {'role': 'user', 'content': prompt}]
    output = RUN / 'focus-probes' / (args.case + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    output.mkdir(parents=True, exist_ok=False)
    (output / 'input.json').write_text(json.dumps({'role': role, 'messages': messages}, ensure_ascii=False, indent=2), encoding='utf-8')
    wire = []
    send = httpx.Client.send
    def observed(client, request, *positional, **keywords):
        if request.url.path.endswith('/chat/completions'):
            if len(wire) >= 3:
                raise BaseException('Probe model HTTP limit reached.')
            body = json.loads(request.content)
            item = {'settings': {k: body[k] for k in ('model', 'stream', 'max_completion_tokens', 'reasoning_effort', 'thinking_budget', 'enable_thinking') if k in body}}
            wire.append(item)
            try:
                response = send(client, request, *positional, **keywords)
                item['headers_http_status'] = response.status_code
                return response
            except Exception as exc:
                item['error_type'] = type(exc).__name__
                raise
        return send(client, request, *positional, **keywords)
    result = {'case': args.case, 'checkpoint_sha256': pointer['sha256'],
              'probe_directory': output.relative_to(ROOT).as_posix(),
              'code_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'code_sha256': {p.relative_to(ROOT).as_posix(): sha(p.read_bytes()) for p in
                              [ROOT / 'backend/research_workflow.py', ROOT / 'backend/report_agents/company_main_focus.py', Path(__file__)]},
              'batch_count': len(jobs), 'optional_records': len(optional),
              'probe_records': len(rows), 'prompt_characters': len(prompt),
              'input_sha256': sha(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()),
              'logical_model_calls': 1, 'wire': wire,
              'response_transplanted': False, 'independent_semantic_review': 'not_performed',
              'production_cache_modified': False, 'report_accepted': False}
    started = time.monotonic()
    httpx.Client.send = observed
    try:
        model = research_workflow.ResearchWorkflow()._get_company_report_editor_model(profile='main_focus')
        response = model.invoke(messages)
        content = str(response.content or '')
        result.update(finish_reason=response.response_metadata.get('finish_reason'), usage=response.usage_metadata)
        (output / 'response.json').write_text(json.dumps({'response': content, 'response_metadata': response.response_metadata,
                                                        'usage_metadata': response.usage_metadata}, ensure_ascii=False, indent=2), encoding='utf-8')
        if result['finish_reason'] != 'stop':
            raise RuntimeError('Probe response incomplete.')
        checked, errors = validate_focus_answers(rows, _object_answer(content))
        result.update(format_and_literal_errors=errors, checked_records=len(checked),
                      format_and_literal_status='passed' if not errors else 'failed')
    except Exception as exc:
        result.update(error_type=type(exc).__name__, http_status=getattr(exc, 'status_code', None))
    finally:
        httpx.Client.send = send
        result['elapsed_seconds'] = round(time.monotonic() - started, 3)
        (output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        (output.parent / 'latest.json').write_text(json.dumps({'summary': (output / 'summary.json').relative_to(ROOT).as_posix(),
            'sha256': sha((output / 'summary.json').read_bytes())}, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('format_and_literal_status') == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
