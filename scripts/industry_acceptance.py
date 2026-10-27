"""Versioned, offline acceptance candidates with independently frozen labels.

This measures existing deterministic gates, not full semantic entailment or a
live model. No model, search, business database, or document regeneration runs.
"""
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = ROOT / 'test/fixtures/industry_acceptance/v1/cases.json'
sys.path.insert(0, str(ROOT / 'backend'))


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


@contextmanager
def offline():
    """Fail on network use, including accidental provider calls, and restore it."""
    originals = socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex
    def denied(*args, **kwargs):
        raise RuntimeError('Acceptance evaluation is offline; network access is prohibited')
    socket.getaddrinfo = socket.socket.connect = socket.socket.connect_ex = denied
    try:
        yield
    finally:
        socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex = originals


def validate_suite(suite):
    if suite.get('schema_version') != 1 or not suite.get('suite_id'):
        raise ValueError('Unsupported or unnamed acceptance suite')
    if suite.get('label_status') not in {'candidate', 'business_reviewed'}:
        raise ValueError('Explicit label review status is required')
    if suite.get('label_status') == 'business_reviewed' and not suite.get('review_record'):
        raise ValueError('Business-reviewed labels require a separate review record')
    cases = suite.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('A suite must contain cases')
    ids = set()
    allowed = {'fact': {'report', 'summary', 'risk'}, 'claim': {'claim'}}
    for case in cases:
        case_id = case.get('id')
        if not case_id or case_id in ids:
            raise ValueError('Missing or duplicate case id')
        ids.add(case_id)
        kind = case.get('kind')
        if kind not in allowed or case.get('target') not in allowed[kind]:
            raise ValueError(f'{case_id}: unsupported kind/target')
        if case.get('split') not in {'development', 'challenge'}:
            raise ValueError(f'{case_id}: missing fixed evaluation split')
        if not case.get('category') or not case.get('rationale') or not case.get('scope'):
            raise ValueError(f'{case_id}: missing category, rationale or scope')
        expected = case.get('expected', {})
        if type(expected.get('allowed')) is not bool:
            raise ValueError(f'{case_id}: expected.allowed must be a frozen boolean')
        if kind == 'fact' and not case.get('fact'):
            raise ValueError(f'{case_id}: missing candidate fact')
        if kind == 'claim' and not case.get('text'):
            raise ValueError(f'{case_id}: missing candidate statement')
        if case['target'] == 'risk' and not case.get('dimension'):
            raise ValueError(f'{case_id}: a risk target requires its dimension')
        for spec in [case['fact']] if kind == 'fact' else case.get('facts', []):
            if not spec.get('quote') or not spec.get('source', {}).get('url'):
                raise ValueError(f'{case_id}: source text and URL are required')
    return suite


def fixture_fact(spec, ordinal=1):
    """Input fixture only: locate its quote literally, never set expected labels."""
    source = spec['source']
    quote = spec['quote']
    body = source.get('body', quote)
    start = body.find(quote)
    locator = {'status': 'unlocated', 'reason': 'quote_not_in_stored_body'}
    if source.get('content_kind', 'body') == 'body' and start >= 0:
        locator = {'status': 'verified', 'source_id': ordinal,
            'body_sha256': hashlib.sha256(body.encode()).hexdigest(),
            'start': start, 'end': start + len(quote), 'quote': quote,
            'archive_binding_status': 'not_verified'}
    fact = {'evidence_id': spec.get('evidence_id', f'E-{ordinal:012X}'),
        'fact': quote, 'evidence_quote': quote, 'module': spec.get('module', '市场规模与增长'),
        'scope_match': 'in_scope', 'evidence_scope': spec.get('evidence_scope', 'industry_level'),
        'claim_type': spec.get('claim_type', 'fact'), 'source_url': source['url'],
        'source_title': source.get('title', '合成验收资料'), 'published_date': source.get('published_date', ''),
        'provenance': {'locator': locator}}
    for field in ('numeric_context', 'numeric_validation', 'original_source_url', 'original_publisher'):
        if field in spec:
            fact[field] = deepcopy(spec[field])
    return fact, body


def observe_case(case):
    from industry_fact_contracts import attach_contract, chapter_admitted, risk_admitted
    from industry_research import claim_semantic_issues, numeric_mentions, numeric_supported
    if case['kind'] == 'fact':
        fact, body = fixture_fact(case['fact'])
        item = attach_contract(fact, case['scope'], body)
        contract = item['fact_contract']
        decision = {'report': lambda: contract['report_admitted'],
            'summary': lambda: chapter_admitted(item, 1),
            'risk': lambda: risk_admitted(item, case['dimension'])}[case['target']]()
        return {'allowed': bool(decision), 'source_role': contract['source_role'],
            'comparator': contract['comparator'], 'period': contract['period'],
            'value_nature': contract.get('value_nature'), 'statement': contract['statement'],
            'issues': contract['issues'], 'locator_status': fact['provenance']['locator']['status']}
    facts = [fixture_fact(spec, ordinal)[0] for ordinal, spec in enumerate(case.get('facts', []), 1)]
    issues = [row['code'] for row in claim_semantic_issues(case['text'], facts)]
    ids = set(re.findall(r'\bE-[A-Z0-9-]{6,}\b', case['text'], re.I))
    by_id = {f['evidence_id']: f for f in facts}
    if ids - by_id.keys():
        issues.append('invalid_citation')
    cited = {eid: {'context': f.get('numeric_context') or {},
                   'validation': f.get('numeric_validation') or {}}
             for eid, f in by_id.items() if eid in ids}
    if any(not any(numeric_supported(number, eid, cited) for eid in cited)
           for number in numeric_mentions(case['text'])):
        issues.append('unverified_number')
    return {'allowed': not issues, 'issues': sorted(set(issues))}


def compare_case(case, actual):
    expected = case['expected']
    differences = []
    for field, wanted in expected.items():
        if field == 'required_issue_codes':
            if not set(wanted) <= set(actual.get('issues', [])):
                differences.append({'field': field, 'expected': wanted, 'actual': actual.get('issues', [])})
        elif actual.get(field) != wanted:
            differences.append({'field': field, 'expected': wanted, 'actual': actual.get(field)})
    return {'id': case['id'], 'category': case['category'], 'split': case['split'],
        'target': case['target'], 'expected': expected, 'actual': actual,
        'rationale': case['rationale'], 'passed': not differences, 'differences': differences}


def metrics(rows):
    decided = [row for row in rows if row.get('actual') is not None]
    confusion = Counter()
    for row in decided:
        want, got = row['expected']['allowed'], row['actual']['allowed']
        confusion['true_allow' if want and got else 'false_reject' if want else
                  'false_allow' if got else 'true_reject'] += 1
    positives = confusion['true_allow'] + confusion['false_reject']
    negatives = confusion['true_reject'] + confusion['false_allow']
    return {'case_count': len(rows), 'passed': sum(row['passed'] for row in rows),
        'errors': sum(row.get('error') is not None for row in rows),
        **{key: confusion[key] for key in ('true_allow', 'true_reject', 'false_allow', 'false_reject')},
        'false_allow_rate': confusion['false_allow'] / negatives if negatives else None,
        'false_reject_rate': confusion['false_reject'] / positives if positives else None}


def evaluate_suite(path=DEFAULT_SUITE, observer=None):
    path = Path(path)
    suite = validate_suite(json.loads(path.read_text(encoding='utf-8-sig')))
    before = deepcopy(suite)
    rows = []
    with offline():
        for case in suite['cases']:
            try:
                actual = (observer or observe_case)(deepcopy(case))
                if type(actual.get('allowed')) is not bool:
                    raise ValueError('Observer did not return a boolean decision')
                row = compare_case(case, actual)
            except Exception as exc:
                row = {'id': case['id'], 'category': case['category'], 'split': case['split'],
                    'target': case['target'], 'expected': case['expected'], 'actual': None,
                    'passed': False, 'error': type(exc).__name__}
            rows.append(row)
    if suite != before:
        raise RuntimeError('Evaluation mutated its frozen labels')
    groups = lambda field: {name: metrics([row for row in rows if row[field] == name])
                            for name in sorted({row[field] for row in rows})}
    source_files = ['backend/industry_fact_contracts.py', 'backend/industry_research.py',
        'backend/industry_claims.py', 'backend/industry_assertions.py',
        'backend/industry_grounding.py', 'backend/industry_passages.py']
    return {'schema_version': 1, 'mode': 'offline_candidate_acceptance',
        'created_at_utc': datetime.now(timezone.utc).isoformat(), 'suite_id': suite['suite_id'],
        'evaluator_sha256': digest(Path(__file__)),
        'gate_disk_source_sha256': {name:digest(Path(__file__).resolve().parents[1] / name) for name in source_files},
        'suite_sha256': digest(path), 'label_status': suite['label_status'],
        'labels_sha256': hashlib.sha256(json.dumps(
            [(c['id'], c['expected'], c['rationale']) for c in suite['cases']],
            ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        'metrics': metrics(rows), 'by_split': groups('split'), 'by_category': groups('category'),
        'passed': all(row['passed'] for row in rows), 'cases': rows,
        'limitations': ['Candidate labels require business review; no human gold-standard claim.',
            'Challenge examples are fixed rewrites visible during creation, not a statistically unseen test.',
            'Passing deterministic gates does not prove complete semantic support, live model quality or Word layout.',
            'No model, search, business database or report regeneration is used.']}


def _private_path(relative):
    path = (ROOT / relative).resolve()
    if not path.is_relative_to((ROOT / 'work').resolve()):
        raise ValueError('Historical inputs must remain inside the private work directory')
    return path


def inspect_private_manifest(manifest_path):
    """Verify pinned historical files. Pending business judgements are never passes."""
    manifest_path = _private_path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    if manifest.get('schema_version') != 1 or not manifest.get('cases'):
        raise ValueError('Invalid private acceptance manifest')
    ids, rows = set(), []
    from industry_research import summary_length
    for case in manifest['cases']:
        if not case.get('id') or case['id'] in ids:
            raise ValueError('Missing or duplicate private case id')
        ids.add(case['id'])
        if not {'cleaned_facts', 'risk_assessment', 'report', 'proposal'} <= case.get('files', {}).keys():
            raise ValueError('A historical case requires all four original input artifacts')
        paths = {kind: _private_path(info['path']) for kind, info in case['files'].items()}
        checks = {kind: path.is_file() and digest(path) == case['files'][kind]['sha256']
                  for kind, path in paths.items()}
        row = {'id': case['id'], 'integrity_verified': all(checks.values()), 'file_checks': checks,
            'business_review_status': case.get('business_review_status', 'pending'),
            'business_quality_passed': None, 'focus': case.get('focus', [])}
        if row['integrity_verified']:
            report = paths['report'].read_text(encoding='utf-8-sig')
            proposal = paths['proposal'].read_text(encoding='utf-8-sig')
            row.update(report_chapters=[int(n) for n in re.findall(r'^##\s*(\d+)[.、．]', report, re.M)],
                proposal_chapters=[int(n) for n in re.findall(r'^##\s*(\d+)[.、．]', proposal, re.M)],
                summary_body_chars=None)
            summary = re.search(r'(?ms)^##\s*1[.、．][^\n]*\n.*?(?=^##\s*2[.、．]|\Z)', report)
            if summary:
                row['summary_body_chars'] = summary_length(summary[0])
        rows.append(row)
    return {'mode': 'private_historical_input_inventory', 'case_count': len(rows),
        'integrity_verified': all(row['integrity_verified'] for row in rows),
        'business_quality_passed': None, 'cases': rows,
        'limitation': 'File identity and chapter counts are not business quality acceptance; pending labels are not passes.'}


def write_result(result, output):
    output = _private_path(output)
    if output.suffix != '.json':
        raise ValueError('Acceptance output must be private JSON')
    if output.exists():
        raise ValueError('Use a new output filename to preserve earlier acceptance evidence')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def render_review(suite, result):
    """Readable, escaped evidence/labels; it never presents a rule pass as proof."""
    esc = lambda value: html.escape(str(value), quote=True)
    outcomes = {row['id']: row for row in result['cases']}
    cards = []
    for case in suite['cases']:
        row = outcomes[case['id']]
        facts = [case['fact']] if case['kind'] == 'fact' else case.get('facts', [])
        materials = ''.join('<details><summary>合成来源正文</summary><pre>'
            + esc(f['source'].get('body', f['quote'])) + '</pre><p>候选摘录：'
            + esc(f['quote']) + '</p></details>' for f in facts)
        actual = ('运行异常：' + row['error'] if row.get('error') else
                  '规则放行' if row['actual']['allowed'] else '规则拦截')
        detail = '<pre>' + esc(json.dumps(row.get('differences', []), ensure_ascii=False, indent=2)) + '</pre>' if not row['passed'] else ''
        cards.append(f'<article class="{"pass" if row["passed"] else "fail"}"><h2>{esc(case["id"])} · {esc(case["category"])}</h2>'
            + f'<p>分组：{esc(case["split"])}　检查入口：{esc(case["target"])}　'
            + f'候选预期：{"放行" if case["expected"]["allowed"] else "拦截"}　实际：{esc(actual)}</p>'
            + '<p><strong>判断依据：</strong>' + esc(case['rationale']) + '</p>'
            + ('<pre>' + esc(case['text']) + '</pre>' if case.get('text') else '')
            + materials + detail + '<p class="review">业务复核：待确认；如标签有误，应记录理由并发布新版本。</p></article>')
    m = result['metrics']
    historical = ''
    if result.get('historical_inputs'):
        historical = '<header><h2>真实历史输入：待业务复核</h2><p>历史材料按独立清单保存。指纹一致只确认原文件未变，不代表报告质量通过。</p>'
        for row in result['historical_inputs']['cases']:
            historical += '<p><strong>' + esc(row['id']) + '</strong>　原始文件：' \
                + ('指纹一致' if row['integrity_verified'] else '需核对') \
                + '；报告章节数：' + esc(len(row.get('report_chapters', []))) \
                + '；建议书章节数：' + esc(len(row.get('proposal_chapters', []))) \
                + '；业务质量：待复核。<br>重点：' + esc('、'.join(row['focus'])) + '</p>'
        historical += '</header>'
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' \
        '<title>行业验收集候选 v1</title><style>body{font:16px/1.7 system-ui,sans-serif;color:#172c44;background:#f4f7fa;max-width:1040px;margin:auto;padding:24px}' \
        'article,header{background:white;padding:24px;margin:20px 0;border:1px solid #d7e0ea;border-radius:10px}' \
        'article.fail{border-left:6px solid #b73232}h1{font-size:28px}h2{font-size:21px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fa;padding:16px}' \
        '.review{color:#596b7d;font-size:14px}summary{cursor:pointer}details{margin-top:12px}</style><header><h1>行业验收集候选 v1</h1>' \
        + f'<p>{m["case_count"]}条样例，{m["passed"]}条符合候选标签；误放行{m["false_allow"]}，误拒绝{m["false_reject"]}。</p>' \
        + '<p>标签由助手按验收准则拟定，尚待业务复核。所有材料均为合成示例；规则放行不表示整句语义已证明。challenge为创建时可见的固定改写组。</p>' \
        + '<p>数据指纹：' + esc(result['suite_sha256']) + '</p></header>' + historical + ''.join(cards) + '</html>'


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, default=DEFAULT_SUITE)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--private-manifest', type=Path)
    parser.add_argument('--review-output', type=Path, help='New private HTML file with all examples and candidate labels')
    args = parser.parse_args(argv)
    try:
        result = evaluate_suite(args.suite)
        if args.private_manifest:
            with offline():
                result['historical_inputs'] = inspect_private_manifest(args.private_manifest)
        if args.output or args.review_output:
            # Never let a report overwrite its suite, manifest, or input artifacts.
            protected = {args.suite.resolve()}
            if args.private_manifest:
                protected.add(_private_path(args.private_manifest))
                manifest = json.loads(_private_path(args.private_manifest).read_text(encoding='utf-8-sig'))
                protected.update(_private_path(f['path']) for c in manifest['cases'] for f in c['files'].values())
            outputs = [p for p in (args.output, args.review_output) if p]
            if len({p.resolve() for p in outputs}) != len(outputs):
                raise ValueError('JSON and HTML outputs must be separate files')
            for path in outputs:
                if path.resolve() in protected or _private_path(path).exists():
                    raise ValueError('Output cannot overwrite inputs or earlier acceptance evidence')
            if args.review_output and args.review_output.suffix != '.html':
                raise ValueError('Review output must be HTML')
            if args.output and args.output.suffix != '.json':
                raise ValueError('Acceptance output must be JSON')
            if args.output:
                write_result(result, args.output)
            if args.review_output:
                path = _private_path(args.review_output)
                path.parent.mkdir(parents=True, exist_ok=True)
                suite = json.loads(args.suite.read_text(encoding='utf-8-sig'))
                path.write_text(render_review(suite, result), encoding='utf-8')
        print(json.dumps({key: result[key] for key in ('suite_id', 'label_status', 'passed', 'metrics', 'by_split')}, ensure_ascii=False, indent=2))
        if args.private_manifest:
            print('Historical input identity:', result['historical_inputs']['integrity_verified'],
                  '; business quality: pending separate review')
        return 0 if result['passed'] and result.get('historical_inputs', {}).get('integrity_verified', True) else 2
    except (ValueError, KeyError, OSError, TypeError) as exc:
        print(f'Acceptance input error: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
