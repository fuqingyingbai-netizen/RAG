"""Copy a machine-passed native report into an immutable local QA candidate.

No approval flags are changed. The final source/report/page review remains a
separate artifact bound to these exact bytes. No environment file is packaged.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
from pathlib import Path
import re
import sqlite3
import zipfile

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'work/company-phase1-20261028'


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', choices=['haitian', 'kingsoft', 'holdout'])
    args = parser.parse_args()
    native = RUN / 'native' / args.case
    plans = sorted(native.glob('bounded-plan-*.json'))
    if not plans:
        raise RuntimeError('No bounded native run plan exists.')
    plan_path = plans[-1]
    result_path = plan_path.with_name(plan_path.name.replace('bounded-plan-', 'bounded-result-'))
    if not result_path.exists():
        raise RuntimeError('The latest native run has not ended; old artifacts cannot be packaged.')
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    result = json.loads(result_path.read_text(encoding='utf-8'))
    if result.get('state') != 'native_entry_completed' or result.get('runtime_code_unchanged') is not True:
        raise RuntimeError('The latest native run is incomplete or its source changed.')
    acceptance_path = native / 'acceptance.json'
    acceptance = json.loads(acceptance_path.read_text(encoding='utf-8'))
    if acceptance.get('status') != 'passed' or acceptance.get('exception'):
        raise RuntimeError('The latest native run did not pass its machine contract.')
    with sqlite3.connect((native / 'acceptance.sqlite').resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM research_artifacts WHERE artifact_type='desktop_report' ORDER BY version DESC,id DESC LIMIT 1").fetchone()
        if row is None:
            raise RuntimeError('No native report exists.')
        artifact = dict(row)
    metadata = json.loads(artifact['artifact_metadata'] or '{}')
    contract = metadata.get('company_delivery_contract') or {}
    markdown = artifact['content'].encode('utf-8')
    if (contract.get('status') != 'passed' or contract.get('export_status') != 'passed'
            or contract.get('delivery_ready') is not True or contract.get('errors')
            or contract.get('report_sha256') != sha(markdown)):
        raise RuntimeError('The latest report has not passed its exact native content/export contract.')
    if (acceptance.get('report_metadata') or {}).get('company_delivery_contract') != contract:
        raise RuntimeError('The native run receipt belongs to a different report.')

    def read_object(key):
        value = metadata.get(key)
        if not isinstance(value, str) or not value:
            raise RuntimeError('Missing export object: ' + key)
        path = (native / 'objects' / value).resolve()
        if not path.is_relative_to((native / 'objects').resolve()):
            raise RuntimeError('Export path escaped the task runtime.')
        return path.read_bytes()

    docx = read_object('docx_object_key')
    annex = read_object('evidence_annex_object_key')
    bundle = read_object('delivery_bundle_object_key')
    for payload, field in [(docx, 'docx_sha256'), (annex, 'evidence_annex_sha256'),
                           (bundle, 'delivery_bundle_sha256')]:
        if sha(payload) != metadata.get(field):
            raise RuntimeError('Native export hash mismatch: ' + field)
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        if (archive.testzip() is not None
                or archive.namelist() != ['分析主报告.docx', '完整证据附件.html']
                or archive.read('分析主报告.docx') != docx
                or archive.read('完整证据附件.html') != annex):
            raise RuntimeError('Native bundle content mismatch.')

    # Generated from the exact Markdown, without changing a factual sentence.
    # Disallow raw source HTML and use CommonMark's safe link handling.
    renderer = MarkdownIt('commonmark', {'html': False}).enable('table')
    chapter_links = []
    def heading_open(tokens, index, options, env):
        if tokens[index].tag == 'h2' and index + 1 < len(tokens):
            label = tokens[index + 1].content
            match = re.match(r'^(\d+)[.、．]\s*', label)
            if match:
                anchor = 'chapter-' + match[1]
                tokens[index].attrSet('id', anchor)
                chapter_links.append((anchor, label))
        return renderer.renderer.renderToken(tokens, index, options, env)
    renderer.renderer.rules['heading_open'] = heading_open
    body = renderer.render(markdown.decode('utf-8'))
    title = html.escape(artifact['title'])
    directory = '<details><summary>目录</summary><ol>' + ''.join(
        '<li><a href="#' + anchor + '">' + html.escape(label) + '</a></li>'
        for anchor, label in chapter_links) + '</ol></details>'
    webpage = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
               '<meta name="viewport" content="width=device-width,initial-scale=1">'
               '<meta name="source-markdown-sha256" content="' + sha(markdown) + '">'
               '<title>' + title + '</title><style>'
               'body{margin:0;color:#111;background:#f5f5f3;font:17px/1.8 "Microsoft YaHei",sans-serif}'
               'main{max-width:1050px;margin:auto;padding:44px 48px;background:white}'
               'h1,h2,h3,h4{color:#000;line-height:1.5;overflow-wrap:anywhere}'
               'h2{margin-top:2.2em;border-bottom:1px solid #d9d9d9;padding-bottom:.4em}'
               'table{border-collapse:collapse;width:100%;margin:1.3em 0;font-size:15px}'
               'th,td{border:1px solid #d9d9d9;padding:10px 12px;text-align:left;overflow-wrap:anywhere}'
               'th{background:#eaf0f5}tr:nth-child(even){background:#fafafa}'
               'a{color:#185b86;overflow-wrap:anywhere}p,li{overflow-wrap:anywhere}'
               'blockquote{margin:1em 0 1em 1.4em}pre{white-space:pre-wrap;overflow-wrap:anywhere}'
               'nav{font-size:14px;margin-bottom:2em}@media(max-width:700px){main{padding:22px 18px}table{font-size:13px}}'
               '</style><main><nav><a href="报告.md">Markdown</a> · '
               '<a href="分析主报告.docx">Word</a> · <a href="完整证据附件.html">完整证据附件</a></nav>'
               + directory + '<article>' + body + '</article></main></html>').encode('utf-8')
    files = {'报告.md': markdown, '报告.html': webpage, '分析主报告.docx': docx,
             '完整证据附件.html': annex, '原生交付包.zip': bundle}
    renderer_source_sha256 = sha(Path(__file__).read_bytes())
    candidate_id = sha(json.dumps({'files': {name: sha(payload) for name, payload in files.items()},
                                  'renderer_source_sha256': renderer_source_sha256}, sort_keys=True).encode())
    destination = RUN / 'review-candidates' / args.case / candidate_id
    destination.mkdir(parents=True, exist_ok=True)
    for name, payload in files.items():
        path = destination / name
        if path.exists() and path.read_bytes() != payload:
            raise RuntimeError('An immutable QA candidate already has different bytes: ' + name)
        path.write_bytes(payload)
    manifest = {'version': 'company-phase1-review-candidate-v1', 'case': args.case,
                'candidate_id': candidate_id, 'renderer_source_sha256': renderer_source_sha256,
                'artifact_id': artifact['id'], 'artifact_version': artifact['version'],
                'report_sha256': sha(markdown),
                'native_code_commit': plan.get('code_commit'),
                'native_run_proofs': {p.name: sha(p.read_bytes()) for p in (plan_path, result_path, acceptance_path)},
                'files': {name: {'sha256': sha(payload), 'bytes': len(payload)} for name, payload in files.items()},
                'native_content_and_export_contract': contract,
                'human_semantic_review': 'pending', 'browser_review': 'pending',
                'word_all_pages_review': 'pending', 'final_accepted': False,
                'html_renderer': 'markdown-it-py commonmark with table, raw HTML disabled',
                'no_new_model_or_search_calls': True}
    (destination / 'candidate-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'case': args.case, 'destination': str(destination),
                      'report_sha256': sha(markdown), 'final_accepted': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
