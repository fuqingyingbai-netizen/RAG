"""Bounded opt-in live probes of the actual person collector and writer.

Default uses saved probe results. --live performs 12 lightweight search requests,
up to six original-page fetches and at most 12 professional business calls.
--model also exercises actual chapter generation for the first public example.
No application database, deployment or account configuration is modified.
"""
import argparse
import html
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')
from person_identity import build_anchor
from person_evidence import generate_person_report, build_packages
from person_retrieval import SearchSession, coverage
from person_platforms import collect, documents, validated_records
from research_strategies.person import PersonResearchStrategy
from research_workflow import ResearchWorkflow
from report_agents.person_report_agent import PersonReportAgent
from web_search import web_search_provider

OUT = ROOT / 'work/person-optimization/context-v2'


def echo(role, prompt, trace=None):
    pack = json.loads(prompt[prompt.index('{"chapter":'):])
    return json.dumps({'claims': [{'statement': f['fact'], 'evidence_ids': [f['evidence_id']], 'analysis': ''}
                                 for f in pack['facts']]}, ensure_ascii=False)


def live(model=False):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from models import Base, ResearchProject, ResearchSource, User
    from research_store import research_store
    from company_platform import failure_kind
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    research_store.mode, research_store.local_root = 'local', OUT / 'objects'
    os.environ['PERSON_PLATFORM_CALL_BUDGET'] = '6'
    os.environ['WEB_FETCH_TOTAL_TIMEOUT_SECONDS'] = '20'
    os.environ['PERSON_REPORT_SECTION_TIMEOUT_SECONDS'] = '40'
    os.environ['PERSON_REPORT_SECTION_MAX_RETRIES'] = '0'
    workflow = ResearchWorkflow()
    workflow._save_professional_visual_evidence = lambda *a, **kw: []
    cases = []
    with Session(engine) as db:
        user = User(username='isolated-context-probe', password_hash='not-a-real-login')
        db.add(user)
        db.flush()
        for index, (name, company, context) in enumerate([
            ('王传福', '比亚迪股份有限公司', '核对本人任职、历史关联企业及公开司法记录；企业事项与个人责任分开。'),
            ('董明珠', '珠海格力电器股份有限公司', '核对本人任职、历史关联企业及公开司法记录；不把同名其他人员记录归给本人。')]):
            p = ResearchProject(title=f'{name}身份锚定接口抽样', target_name=name, target_type='person',
                                industry='', description='有界接口验收，不是完整背景调查', created_by_id=user.id)
            db.add(p)
            db.commit()
            value = workflow._normalize_intake(p, {'target_type': 'person', 'affiliation': company,
                'person_context': context, 'focus_modules': ['经营胜任力', '核心管理团队背景'],
                'focus_questions': ['核对历史任职与当前任职'], 'as_of_date': datetime.now().date().isoformat()}, [], [])
            p.person_research_intake = value
            attempts, candidates = [], []
            for provider in ('bocha', 'tavily', 'exa'):
                for query in (f'"{name}" "{company}" 任职 履历', f'"{name}" "{company}" 司法 处罚'):
                    try:
                        rows = web_search_provider.search_single(provider, query, limit=2)
                        candidates.extend(rows)
                        attempt = {'provider': provider, 'query': query, 'status': 'returned', 'count': len(rows),
                                   'urls': [r.get('url') for r in rows]}
                    except Exception as exc:
                        attempt = {'provider': provider, 'query': query, 'status': 'failed',
                                   'reason': failure_kind({'error': str(exc)}), 'exception_type': type(exc).__name__}
                    attempts.append(attempt)
                    print(json.dumps({k: v for k, v in attempt.items() if k != 'urls'}, ensure_ascii=False), flush=True)
            seen, fetched = set(), 0
            for row in candidates:
                url = row.get('url') or ''
                if not url or url in seen or fetched >= 3:
                    continue
                seen.add(url)
                fetched += 1
                result = workflow._fetch_web_url_with_timeout(url, allow_browser=False)
                body = result.get('content') or ''
                identity = workflow._person_source_identity_confidence(row.get('title') or '', body, value)
                attempts.append({'provider': 'original_web', 'url': url, 'status': result.get('status'),
                                 'chars': len(body), 'identity_confidence': identity['confidence']})
                if result.get('status') == 'done' and body and identity['confidence'] in {'medium', 'high'}:
                    db.add(ResearchSource(project_id=p.id, source_type='web', title=row.get('title') or '',
                        url=url, content=body, summary='', credibility_score=75,
                        source_metadata={'identity_confidence': identity['confidence'], 'identity_reason': identity['reason'],
                                         'provider': (row.get('metadata') or {}).get('provider'), 'module': '教育与履历',
                                         'person_chapters': [2], 'person_discovery_only': False}))
                    db.commit()
            prepared = workflow._prepare_structured_entity_intake(p, value)
            collect(workflow, db, p, company, prepared)
            db.expire(p, ['sources'])
            plan = workflow.plan_research(p, value)
            p.person_retrieval_audit = {'scope': 'bounded_live_probe_not_complete_run', 'attempts': attempts,
                                      'coverage': coverage(list(p.sources), value)}
            payload = workflow.clean_sources(p, plan=plan)
            (OUT / f'live-{index+1}-cleaned.json').write_text(payload, encoding='utf-8')
            invoke = workflow._invoke_person_report_section if model and index == 0 else echo
            report = generate_person_report(p, payload, '{}', PersonReportAgent.outline, invoke, lambda *a, **kw: None)
            (OUT / f'live-{index+1}-report.md').write_text(report, encoding='utf-8')
            facts = json.loads(payload).get('facts', [])
            contract = build_packages({'facts': facts}, name, PersonReportAgent.outline, value, list(p.sources))
            case = {'target': name, 'affiliation': company, 'identity_anchor': value['person_anchor'],
                    'scope': 'bounded_live_collection_actual_model' if model and index == 0 else 'bounded_live_collection_deterministic_claim_replay',
                    'attempts': attempts, 'platform_attempts': getattr(p, 'person_platform_attempts', []),
                    'source_count': len(p.sources), 'fact_count': len(facts), 'chapter_audit': p.person_delivery_diagnostic,
                    'chapter_evidence_counts': {str(k): len(v['facts']) for k, v in contract['chapters'].items()}}
            cases.append(case)
            # Checkpoint after every person; rerunning default mode is free.
            (OUT / 'live-context.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'person': name, 'sources': len(p.sources), 'facts': len(facts), 'chapters': 15,
                              'model_attempts': len(p.person_delivery_diagnostic['api_attempts'])}, ensure_ascii=False), flush=True)
    return cases


def replay_retained_records(case, index):
    """Re-run current scope guards against retained real responses, at no API cost.

    The initial probe exposed a same-second storage collision, so only retained
    responses are replayed. This does not claim to reconstruct every original
    request or to rerun the live model after the final guard fixes.
    """
    sources, facts, paths = [], [], []
    for path in (OUT / 'objects').rglob('*_raw.json'):
        payload = json.loads(path.read_text(encoding='utf-8'))
        for doc in documents(payload):
            if doc.get('人员名称') != case['target'] or doc.get('企业名称') != case['affiliation']:
                continue
            fields = ' '.join(doc)
            historical = 'historical_' if '历史' in fields else ''
            suffix = 'related_companies' if '关联企业' in fields else 'positions'
            tool = 'get_executive_' + historical + suffix
            matched, quotes = validated_records(payload, case['target'], case['affiliation'], tool)
            if not matched or not quotes:
                continue
            paths.append(str(path.relative_to(ROOT)))
            url = 'structured://retained_qcc/' + path.name
            content = '\n\n'.join(quotes)
            sources.append(SimpleNamespace(id=len(sources)+1, url=url, title=tool, content=content, summary='',
                source_type='business_database', source_metadata={'person_subject_verified': True, 'identity_confidence': 'high'}, credibility_score=92))
            for quote in quotes:
                facts.append({'fact': quote, 'evidence_quote': quote, 'source_url': url, 'source_title': tool,
                    'source_type': 'business_database', 'provider': 'qcc_executive', 'identity_confidence': 'high',
                    'identity_match': 'confirmed', 'claim_type': 'person_platform_record', 'person_chapters': [2, 6, 9]})
    p = SimpleNamespace(target_name=case['target'], target_type='person', title=case['target']+'人员原始记录范围回放',
                        description='', industry='', sources=sources,
                        person_research_intake={'person_anchor': case['identity_anchor'], 'affiliation': case['affiliation']})
    report = generate_person_report(p, json.dumps({'facts': facts}, ensure_ascii=False), '{}', PersonReportAgent.outline,
                                    echo, lambda *a, **kw: None)
    for row in p.person_delivery_diagnostic['api_attempts']:
        row['execution'] = 'deterministic_replay_no_api'
    (OUT / f'current-record-replay-{index+1}.md').write_text(report, encoding='utf-8')
    return {'scope': 'retained_real_personnel_responses_current_code_deterministic_replay',
            'raw_paths': paths, 'raw_count': len(paths), 'input_record_count': len(facts),
            'storage_limitation': '初次抽样发现同秒原始文件覆盖；已修复并新增复现测试。这里只回放实际保留的原始返回，不声称包含丢失的现任原始文件。',
            'diagnostic': p.person_delivery_diagnostic}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--model', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    cases = live(args.model) if args.live else json.loads((OUT / 'live-context.json').read_text(encoding='utf-8')) if (OUT / 'live-context.json').exists() else []
    for index, case in enumerate(cases):
        live_model = case['scope'] == 'bounded_live_collection_actual_model'
        case['live_model_calls'] = len(case['chapter_audit']['api_attempts']) if live_model else 0
        for attempt in case['chapter_audit']['api_attempts']:
            attempt['execution'] = 'live_api' if live_model else 'deterministic_replay_no_api'
        case['current_record_replay'] = replay_retained_records(case, index)
    value = {'target_name': '林知远', 'target_type': 'person', 'affiliation': '恒川软件有限公司 / 原CTO',
             'person_context': '任职时间：2018—2022；教育：远山大学', 'focus_questions': ['核对历史任职'],
             'identity_anchors': '远山大学', 'person_aliases': ['Evan Lin']}
    value['person_anchor'] = build_anchor(value)
    rows = PersonResearchStrategy().expand_search_queries({'modules': []}, value)
    session = SearchSession(value, ['bocha', 'exa', 'tavily'])
    for round_index in range(1, 4):
        chosen = session.choose(rows, round_index, [])
        session.record([(r, []) for r in chosen])
    audit = session.audit([])
    changes = {
        1: '摘要接收统一身份上下文，仅汇总前文实际引用。',
        2: '机构、角色、学校、任职时间分开保留；同名只作隔离线索；人员现任及历史记录入账。',
        3: '补充背景作为定位线索；公开行为候选与人格判断分开。',
        4: '融资资料按需调用，企业结果保持关联主体边界。',
        5: '管理事件查询携带身份上下文；正文抓取按章节保留额度。',
        6: '人员任职记录与烯牛团队分析按需调用，成员不混入目标身份。',
        7: '未拿到原文或独立评价保留缺口，不由摘要推定信用。',
        8: '比较候选与指标口径待审，不以找到竞争关键词视为完成。',
        9: '企查查人员及历史工具使用姓名与机构双锚；校验返回主体，明细按风险线索触发。',
        10: '重点问题持续进入检索和写作；未指定专项不自动扩张敏感事项。',
        11: '融资与近期事件工具按委托方向调用；公司治理不自动归为个人能力。',
        12: '零结果、摘要、接口失败不作无风险事实；个人与关联风险分开。',
        13: '综合评估保留身份定位及证据限制，不自动生成分数。',
        14: '仅索引实际引用；接口审计另保留检索次数、主体和失败原因。',
        15: '汇总逐问题缺口、独立来源不足、正文不足、预算用尽和API阻碍。'}
    previous = json.loads((ROOT / 'work/person-optimization/comparison.json').read_text(encoding='utf-8')) if (ROOT / 'work/person-optimization/comparison.json').exists() else {}
    chapters = []
    for i, (title, _) in enumerate(PersonReportAgent.outline, 1):
        older = next((r for r in previous.get('chapters', []) if r['chapter'] == i), {})
        chapters.append({'chapter': i, 'title': title, 'change': changes[i],
                         'same_fixture_before': older.get('before', {}), 'same_fixture_after': older.get('after', {}),
                         'retrieval_contract': audit['coverage']['chapters'][i-1],
                         'live_cases': [{'target': c['target'], 'fact_candidates': c['chapter_evidence_counts'].get(str(i), 0),
                                         'diagnostic': c['chapter_audit']['section_diagnostics'].get(str(i), c['chapter_audit']['section_diagnostics'].get(i, {})),
                                         'current_retained_record_replay': c['current_record_replay']['diagnostic']['chapters'][i-1]} for c in cases]})
    result = {'version': audit['version'], 'branch': 'codex/company', 'identity_anchor': value['person_anchor'],
              'scope': '工程与同输入合成回放；真实接口为有界抽样，不等于完整人物尽调准确率',
              'chapters': chapters, 'synthetic_request_simulation': audit, 'live': cases}
    (OUT / 'comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    esc = html.escape
    cards = []
    for row in chapters:
        detail = json.dumps({k: v for k, v in row.items() if k not in {'change', 'title'}}, ensure_ascii=False, indent=2)
        cards.append(f'<article id="ch{row["chapter"]}"><h2>{row["chapter"]}. {esc(row["title"])}</h2><p>{esc(row["change"])}</p><details><summary>改前、改后、检索缺口与真实接口抽样记录</summary><pre>{esc(detail)}</pre></details></article>')
    nav = ''.join(f'<a href="#ch{r["chapter"]}">{r["chapter"]} {esc(r["title"])}</a>' for r in chapters)
    overview = {'默认搜索调用上限': 48, '单次结果数上限': 6, '正文抓取上限': 44, '专业业务调用上限': 18,
                '说明': '上述为生产默认上限，可用环境变量下调。二引擎独立探测逐章执行；三引擎按剩余缺口与预算扩展。'}
    document = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>人物身份锚定与逐章检索优化</title><style>body{{font:16px/1.7 "Microsoft YaHei",sans-serif;background:#f2f6fa;color:#203248;margin:0}}header,main{{max-width:1200px;margin:auto;padding:24px}}article,.overview{{background:white;border:1px solid #dce5ef;border-radius:12px;padding:24px;margin:18px 0}}nav{{display:flex;flex-wrap:wrap;gap:14px}}a,summary{{color:#087f7a}}summary{{cursor:pointer}}pre{{font:13px/1.6 monospace;white-space:pre-wrap;word-break:break-word;max-height:700px;overflow:auto}}</style><header><h1>人物身份锚定与逐章检索优化</h1><p>codex/company · 2026-10-20 · 15章均保留改进、证据及未完成事项</p></header><main><section class="overview"><h2>本轮变化</h2><p>姓名、身份与关联机构、任职时间、重点问题和上传材料共同定位人物；用户提供的线索仍需来源验证。任职、教育、公司经营、个人责任分开归属。</p><p>真实接口抽样 {len(cases)} 人；完整调查仍需补齐各章缺口并人工复核。零结果、接口失败、预算用尽均不等于无风险。</p><pre>{esc(json.dumps(overview,ensure_ascii=False,indent=2))}</pre><p>同输入合成文本前后对照来自<a href="person-report-optimization.html">原15章对照记录</a>；本页增加身份上下文、请求编排及真实采集抽样。没有把合成结果当作真实调查效果。</p></section><nav>{nav}</nav>{''.join(cards)}</main></html>'''
    target = ROOT / 'deliverables/person-context-optimization.html'
    target.write_text(document, encoding='utf-8')
    print(json.dumps({'html': str(target), 'chapters': len(chapters), 'live_cases': len(cases),
                      'simulated_calls': len(audit['attempts'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
