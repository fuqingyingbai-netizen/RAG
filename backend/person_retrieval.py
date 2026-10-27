"""Bounded person search routing and conservative, inspectable chapter gaps.

This is retrieval readiness, not factual verification. Keyword co-occurrence can
open an extraction candidate; only the downstream source-bound ledger can cite it.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from collections import Counter
from urllib.parse import urlparse

try:
    from .person_evidence import TOPICS, VIEWS, TASKS, compact
    from .person_commission import requirements as commission_requirements, event_years, matches as commission_matches
except ImportError:
    from person_evidence import TOPICS, VIEWS, TASKS, compact
    from person_commission import requirements as commission_requirements, event_years, matches as commission_matches

VERSION = 'person-retrieval-v7-complete-candidate-flow'
DIMENSIONS = {
    2: [('education', '教育时间与院校', ('教育', '毕业', '大学', '学历', 'education', 'university', 'degree')),
        ('career', '机构、职位与任职时间', ('任职', '担任', '履历', '创立', 'appointed', 'joined', 'career'))],
    3: [('behavior', '可定位的行为与表达', ('采访', '演讲', '公开表达', '压力', 'interview', 'speech', 'leadership'))],
    4: [('role_result', '个人职责及经营结果', ('战略', '创新', '融资', '业绩', 'strategy', 'innovation', 'revenue'))],
    5: [('management', '授权、用人与冲突事件', ('授权', '管理', '组织', '接班', 'delegation', 'management', 'succession'))],
    6: [('team', '团队成员职责和变动', ('高管', '团队', '董事', '离职', 'executive', 'team', 'director'))],
    7: [('reputation', '评价者立场与契约记录', ('评价', '诚信', '契约', '处罚', 'reputation', 'integrity', 'contract'))],
    8: [('comparison', '可比人物、时期与同口径指标', ('同业', '对标', '竞争', '可比', 'benchmark', 'competitor', 'comparison'))],
    9: [('relations', '任职、持股及关系时间', ('持股', '关联', '股权', '控制', 'shareholder', 'ownership', 'related')),
        ('legal', '案件当事人、案号与时间', ('诉讼', '案号', '司法', 'litigation', 'lawsuit', 'case'))],
    10: [('commission', '委托问题对应原件', ('专项', '债务', '资产', '知识产权', 'debt', 'patent', 'dispute'))],
    11: [('governance', '实际决策权与投后制度', ('治理', '董事会', '退出', '回购', 'governance', 'board', 'exit'))],
    12: [('risk', '直接与关联风险及查询边界', ('风险', '诉讼', '处罚', '失信', 'risk', 'sanction', 'penalty', 'lawsuit'))],
}
DIMENSIONS[7] += [('attributed_feedback', '具名员工、前同事、客户或合作方的原始评价及利益立场',
                   ('员工评价', '前同事', '客户评价', '合作伙伴', '评价者', '履约', 'contract'))]
DIMENSIONS[8] += [('peer_basis', '至少两名可比人物的行业、发展阶段、职责、时期与同单位指标',
                   ('可比人物', '竞争对手', '同行', '董事长', '创始人', 'benchmark'))]
DIMENSIONS[11] += [('exit_terms', '董事会授权、重大事项审批、回购及退出安排原始条款与适用条件',
                    ('授权', '重大事项', '回购', '退出', '股东协议', 'exit'))]
DIMENSIONS[12] += [('judicial_scope', '失信被执行、执行案件、裁判文书的当事人身份、案号、日期及查询范围',
                    ('失信', '被执行', '案号', '裁判文书', 'judgment', 'court'))]
FOLLOWUP_PRIORITY = (7, 8, 9, 12, 11)
FOLLOWUP_QUERIES = {
    'attributed_feedback': '前同事 员工 合作伙伴 客户 评价 采访 履约',
    'peer_basis': '同行 竞争对手 创始人 董事长 履历 年报',
    'exit_terms': '董事会 授权 股东协议 重大事项 回购 退出 条款',
    'judicial_scope': '失信 被执行人 裁判文书 案号 法院',
}
ORIGINAL_TYPES = {'official', 'filing', 'court', 'government', 'regulatory', 'upload', 'manual', 'business_database'}


def integer(name, default, lo, hi):
    try:
        return max(lo, min(hi, int(os.getenv(name, default))))
    except (TypeError, ValueError):
        return default


def user_time_remaining():
    deadline = os.getenv('RESEARCH_USER_DEADLINE_UTC', '')
    if not deadline:
        return None
    return (datetime.fromisoformat(deadline.replace('Z', '+00:00')) - datetime.now(timezone.utc)).total_seconds()


def coverage(sources, intake):
    chapters = []
    commissioned = commission_requirements(intake)
    for chapter in range(1, 16):
        requirements = []
        specs = DIMENSIONS.get(chapter, [])
        if chapter == 10 and commissioned:
            specs = [(r['id'], r['question'], r['terms']) for r in commissioned]
        for key, label, terms in specs:
            commission = next((r for r in commissioned if r['id'] == key), None)
            candidates = []
            for source in sources:
                meta = source.source_metadata or {}
                if meta.get('retention_policy') == 'record_only' or meta.get('identity_confidence') in {'low', 'rejected'}:
                    continue
                if meta.get('identity_status') == 'quarantined' or meta.get('person_discovery_only'):
                    continue
                if not (meta.get('identity_confidence') in {'medium', 'high'} or meta.get('person_affiliation') or meta.get('person_subject_verified')):
                    continue
                text = str(source.content or '')
                # A snippet/title alone does not satisfy original text access.
                if len(text) < 120 or meta.get('fetch_status') in {'blocked', 'failed', 'challenge'}:
                    continue
                excerpts = [p.strip()[:600] for p in re.split(r'[\n。！？]+', text)
                            if (commission_matches({'fact': p, 'person_affiliation': meta.get('person_affiliation')}, commission)
                                if commission else any(t.lower() in p.lower() for t in terms)) and len(p.strip()) >= 24]
                if not excerpts:
                    continue
                host = urlparse(source.url or '').netloc.lower().removeprefix('www.')
                # Syndicated identical text is one evidence family, even on different hosts.
                family = hashlib.sha256(compact(excerpts[0]).encode()).hexdigest()[:16]
                candidates.append({'source_id': source.id, 'url': source.url, 'host': host, 'family': family,
                                   'excerpt': excerpts[0], 'original': source.source_type in ORIGINAL_TYPES,
                                   'event_date_present': bool(event_years(' '.join(excerpts))) if commission else bool(re.search(r'(?:19|20)\d{2}', ' '.join(excerpts))),
                                   'scope': 'affiliated_company' if meta.get('person_affiliation') else 'person'})
            hosts = {r['host'] for r in candidates if r['host']}
            families = {r['family'] for r in candidates}
            gaps = []
            if not candidates:
                gaps.append('缺少身份匹配且有正文的候选资料')
            if candidates and not any(r['event_date_present'] for r in candidates):
                gaps.append('缺少事件时间，网页发布日期不能替代')
            if candidates and not any(r['original'] for r in candidates):
                gaps.append('缺少官方、原始披露或可定位专业记录')
            if min(len(hosts), len(families)) < 2:
                gaps.append('缺少第二个独立证据来源；转载不重复计数')
            if candidates and all(r['scope'] == 'affiliated_company' for r in candidates):
                gaps.append('仅有关联机构材料，个人职责或责任待核实')
            # Candidate relevance does not prove these multi-part requirements.
            if key == 'peer_basis':
                gaps.append('须人工确认至少两名可比人物及行业、阶段、角色、时期、指标口径，不按关键词自动验收')
            if key == 'attributed_feedback':
                gaps.append('须核对评价者身份、与目标关系及原始出处；公开报道不等于已完成授权访谈')
            if key in {'exit_terms', 'judicial_scope'}:
                gaps.append('须逐项核实原始条款或案件记录；公司事项不能直接认定为个人权利或责任')
            requirements.append({'id': f'{chapter}.{key}', 'question': label,
                                 'state': 'missing' if not candidates else 'partial' if gaps else 'ready_for_extraction',
                                 'gaps': gaps, 'candidates': candidates[:8],
                                 'completion_condition': '经事实账本核对原文、身份、事件时间、归属及冲突；候选齐全不等于已证实'})
            if commission:
                requirements[-1].update(commission_id=commission['id'], query_terms=commission['query_terms'],
                                        questions=commission['questions'])
        if chapter == 10 and not (intake.get('special_requirements') or intake.get('focus_questions')):
            for item in requirements:
                item.update(state='scope_not_specified', gaps=['未指定专项问题，不自动扩张敏感事项调查'])
        chapters.append({'chapter': chapter, 'task': TASKS[chapter],
                         'state': 'derived_from_cited_chapters' if not requirements else 'needs_review',
                         'requirements': requirements})
    return {'version': VERSION, 'assessment': 'retrieval_readiness_only', 'chapters': chapters}


class SearchSession:
    def __init__(self, intake, providers):
        self.intake = intake
        self.providers = [p for p in providers if p in {'bocha', 'exa', 'tavily'}]
        if not self.providers:
            self.providers = list(providers)
        self.budget = integer('PERSON_SEARCH_CALL_BUDGET', 48, 0, 200)
        self.followup_reserve = min(integer('PERSON_CHAPTER_7_8_CALL_BUDGET', 10, 0, 20), self.budget // 3) if self.budget >= 24 else 0
        self.initial_budget = self.budget - self.followup_reserve
        self.rows, self.seen = [], set()
        self.chapter_calls = Counter()
        self.unavailable = {}
        self.last_coverage = None

    def primary_identity_query(self, items, sources, round_index):
        anchor = self.intake.get('person_anchor') or {}
        orgs = anchor.get('known_affiliations') or []
        if not orgs:
            return None
        primary = [s for s in sources if (s.source_metadata or {}).get('identity_confidence') in {'high','medium'}
                   and not (s.source_metadata or {}).get('person_discovery_only')
                   and (s.source_metadata or {}).get('identity_status') != 'quarantined'
                   and s.source_type in {'official','filing','government','regulatory','upload','manual'}
                   and len(s.content or '') >= 120]
        if round_index > 1 and primary:
            return None
        target, org = self.intake['target_name'], str(orgs[0]).replace('"', '')
        listed_context = any(re.search(r'上市|股票代码|股份代号|港交所|证券代码|stock ticker|listed company', (s.content or '')[:10000], re.I) for s in sources)
        domains = {'hkexnews.hk','cninfo.com.cn','sse.com.cn','szse.cn','sec.gov'}
        filings = [r for r in items if domains.intersection(r.get('include_domains') or []) and target in r['query'] and org in r['query']]
        query = dict(filings[0]) if round_index > 1 and listed_context and filings else {
            'module':'人物原始身份资料', 'query':f'"{target}" "{org}" 官方 简历 任职 董事会', 'search_tier':'open_web'}
        return {**query, 'person_chapters':[2,6,9,11],
                'retrieval_reason':'primary_identity_source_reserve' if round_index == 1 else 'independent_engine_probe'}

    def choose(self, items, round_index, sources):
        remaining = user_time_remaining()
        if remaining is not None and remaining < 60:
            self.time_budget_exhausted = True
            return []
        self.last_coverage = coverage(sources, self.intake)
        primary_query = self.primary_identity_query(items, sources, round_index)
        if round_index == 1:
            # Spread the initial budget over chapters before aliases or template variants.
            chosen = [primary_query] if primary_query else []
            for chapter in DIMENSIONS:
                if chapter == 10 and not (self.intake.get('special_requirements') or self.intake.get('focus_questions')):
                    continue
                options = [r for r in items if chapter in r.get('person_chapters', [])]
                if options:
                    exact = [r for r in options if r.get('person_chapters') == [chapter]]
                    if chapter == 10:
                        exact = [r for r in options if r.get('commission_id')] or exact
                    chosen.append(dict((exact or options)[0], person_chapters=[chapter]))
            chosen += [dict(r) for r in items if r.get('commission_id')][1:3]
        else:
            chosen = [primary_query] if primary_query else []
            anchor = self.intake.get('person_anchor') or {}
            orgs = list(anchor.get('known_affiliations') or [])
            chapter_rows = sorted(self.last_coverage['chapters'],
                                  key=lambda r: FOLLOWUP_PRIORITY.index(r['chapter']) if r['chapter'] in FOLLOWUP_PRIORITY else 10 + r['chapter'])
            for row in chapter_rows:
                requirements = [r for r in row['requirements'] if r['state'] != 'scope_not_specified']
                # Round two is a mandatory independent engine probe, even if the
                # first engine looks complete. Round three requires a concrete gap.
                gaps = [r for r in requirements if r['state'] in {'missing', 'partial'}]
                if not requirements or (round_index > 2 and not gaps):
                    continue
                chapter = row['chapter']
                context = (' "' + orgs[0].replace('"', '')[:100] + '"') if orgs else ''
                candidates = gaps or requirements
                if chapter == 10:
                    candidates = sorted(candidates, key=lambda r: sum(r['id'] in row.get('requirement_ids', []) or r.get('commission_id') in row.get('requirement_ids', []) for row in self.rows))[:2]
                else:
                    candidates = sorted(candidates, key=lambda req: (
                        sum(req['id'] in attempt.get('requirement_ids', []) for attempt in self.rows),
                        0 if req['state'] == 'missing' else 1))[:1]
                for req in candidates:
                    # Relax the current employer once for old affiliations / namesakes.
                    clue = '' if round_index == 3 and req['state'] == 'missing' else context
                    key = req['id'].split('.', 1)[-1]
                    query_terms = req.get('query_terms') or FOLLOWUP_QUERIES.get(key) or req['question']
                    chosen.append({'module': '人物逐章缺口', 'query': f'"{self.intake["target_name"]}"{clue} {query_terms}',
                                   'person_chapters': [chapter], 'requirement_ids': [req['id']],
                                   'commission_id': req.get('commission_id', ''),
                                   'retrieval_reason': 'independent_engine_probe' if round_index == 2 else '; '.join(req['gaps']),
                                   'search_tier': 'open_web'})
        routed = []
        for item in chosen:
            if not self.providers or len(self.rows) >= self.initial_budget:
                break
            chapter = next(iter(item.get('person_chapters') or [2]))
            chapter_limit = min(8, max(5, len(commission_requirements(self.intake)))) if chapter == 10 else 5
            if self.chapter_calls[chapter] >= chapter_limit:
                continue
            primary = 'exa' if re.search(r'[A-Za-z]{3}', self.intake.get('target_name', '')) else 'bocha'
            order = list(dict.fromkeys([primary, 'tavily', 'exa', 'bocha']))
            available = [p for p in order if p in self.providers and p not in self.unavailable]
            available += [p for p in self.providers if p not in order and p not in self.unavailable]
            if not available:
                break
            used = {r['provider'] for r in self.rows if chapter in r['chapters']}
            engine = next((p for p in available if p not in used), available[min(round_index-1, len(available)-1)])
            key = (engine, compact(item['query']), tuple(sorted(item.get('include_domains') or [])), self.intake.get('as_of_date', ''))
            if key in self.seen:
                continue
            self.seen.add(key)
            row = {'query': item['query'], 'provider': engine, 'chapters': item.get('person_chapters') or [chapter],
                   'requirement_ids': item.get('requirement_ids') or [], 'commission_id': item.get('commission_id', ''),
                   'reason': item.get('retrieval_reason', 'initial_chapter_recall'), 'status': 'planned',
                   'result_count': 0, 'include_domains': item.get('include_domains') or []}
            item = {**item, 'preferred_providers': [engine], 'person_search_audit_index': len(self.rows)}
            self.rows.append(row)
            self.chapter_calls[chapter] += 1
            routed.append(item)
        return routed

    def record(self, batches):
        for item, results in batches:
            index = item.get('person_search_audit_index')
            if index is not None:
                self.rows[index].update(status=item.get('person_search_status', 'returned' if results else 'empty_or_unavailable'),
                                        result_count=len(results), error_type=item.get('person_search_error_type', ''),
                                        error_reason=item.get('person_search_error_reason', ''))
                reason = item.get('person_search_error_reason')
                if reason in {'quota_exceeded', 'unauthorized', 'access_denied', 'rate_limited'}:
                    self.unavailable[self.rows[index]['provider']] = reason

    def audit(self, sources):
        return {'version': VERSION, 'identity_anchor': self.intake.get('person_anchor') or {},
                'call_budget': self.budget, 'calls_planned': len(self.rows),
                'chapter_7_8_reserved_calls': self.followup_reserve, 'initial_stage_call_budget': self.initial_budget,
                'budget_exhausted': len(self.rows) >= self.budget, 'attempts': self.rows,
                'user_time_budget_exhausted': getattr(self, 'time_budget_exhausted', False),
                'unavailable_providers': self.unavailable,
                'coverage': coverage(sources, self.intake),
                'cost_note': '按实际请求次数限制；供应商单价及账户扣费未在此估算'}
