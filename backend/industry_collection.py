"""Run-scoped industry collection scheduling and external-request accounting."""
from collections import Counter
from contextlib import contextmanager
import hashlib
import os
import re
import threading
import time

VERSION = 'industry-collection-v2-balanced-recall'


class CollectionBudgetExhausted(RuntimeError):
    pass


def query_key(row, target=''):
    query = str(row.get('query') or '').casefold()
    query = query.translate(str.maketrans({'“':'"', '”':'"', '‘':"'", '’':"'"}))
    target = str(target or '').casefold().strip()
    if target:
        # Quoting the same target and accidentally repeating its prefix do not
        # define a new question. Other quoted phrases and numeric fields remain.
        query = query.replace('"' + target + '"', target).replace("'" + target + "'", target)
        query = re.sub(r'^(?:' + re.escape(target) + r'\s+){2,}', target + ' ', query)
    query = re.sub(r'\s+', ' ', query).strip()
    return (query, tuple(sorted(row.get('include_domains') or [])),
            tuple(sorted(row.get('exclude_domains') or [])),
            row.get('evidence_scope', ''), row.get('search_tier', ''),
            row.get('independent_verification', False))


def _integer(name, default, lower, upper):
    try:
        return max(lower, min(upper, int(os.getenv(name, default))))
    except (TypeError, ValueError):
        return default


class IndustryCollection:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.limits = {
            'queries': _integer('INDUSTRY_COLLECTION_QUERY_LIMIT', 48, 6, 80),
            'search_requests': _integer('INDUSTRY_COLLECTION_REQUEST_LIMIT', 160, 12, 240),
            'fetch_requests': _integer('INDUSTRY_COLLECTION_FETCH_LIMIT', 120, 6, 180),
            'seconds': _integer('INDUSTRY_COLLECTION_SECONDS', 900, 60, 1800),
        }
        self.initial_limits = {key: int(value * .75) for key, value in self.limits.items()}
        self.batch_size = _integer('INDUSTRY_COLLECTION_BATCH_SIZE', 3, 1, 4)
        self.candidate_limit = _integer('INDUSTRY_COLLECTION_CANDIDATES', 12, 2, 20)
        self.recovery_candidate_limit = _integer('INDUSTRY_COLLECTION_RECOVERY_CANDIDATES', 8, 2, 16)
        self.recovery_query_limit = _integer('INDUSTRY_COLLECTION_RECOVERY_QUERIES', 8, 4, 12)
        self.per_engine = _integer('INDUSTRY_COLLECTION_ENGINE_RESULTS', 6, 1, 8)
        self.fetch_attempts_per_page = _integer('INDUSTRY_COLLECTION_FETCH_ATTEMPTS_PER_PAGE', 2, 1, 3)
        self.stagnation_limit = _integer('INDUSTRY_COLLECTION_STAGNANT_BATCHES', 3, 2, 5)
        self.used = Counter()
        self.requests = Counter()
        self.seen = set()
        self.fetch_seen = set()
        self.elapsed = 0.0
        self.phase_started = None
        self.phase = 'initial'
        self.generation = 0
        self.pause_requested = None
        self.records = []
        self.skipped = Counter()
        self.batch_records = []
        self.stop_reasons = []
        self.stalled_batches = 0
        self.phase_stopped = False
        self.considered_modules = set()

    def begin(self, phase):
        with self.lock:
            self.phase = phase
            self.generation += 1
            self.phase_started = self.clock()
            self.stalled_batches = 0
            self.phase_stopped = False
            self.considered_modules = set()

    def end(self):
        with self.lock:
            if self.phase_started is not None:
                self.elapsed += self.clock() - self.phase_started
                self.phase_started = None

    def remaining_seconds(self):
        active = self.clock() - self.phase_started if self.phase_started is not None else 0
        limit = self.initial_limits['seconds'] if self.phase == 'initial' else self.limits['seconds']
        return max(0, limit - self.elapsed - active)

    def available(self, kind):
        limit = self.initial_limits[kind] if self.phase == 'initial' else self.limits[kind]
        return self.used[kind] < limit and self.remaining_seconds() >= 1

    def stop(self, reason):
        # Exhausting page transport must not stop keyword recall or provider text.
        if reason not in {'scheduled_questions_processed', 'fetch_requests_exhausted'}:
            self.phase_stopped = True
        record = {'phase': self.phase, 'reason': reason}
        if record not in self.stop_reasons:
            self.stop_reasons.append(record)

    def prioritize(self, rows, intake):
        segments = (intake.get('industry_scope') or {}).get('segments') or []
        def rank(row):
            segment = row.get('segment_name')
            if segment in segments:
                return 0
            return 1 if row.get('search_tier') == 'authority_first' else 2
        # Round-robin within a priority group prevents one module exhausting it.
        groups = {}
        for row in rows:
            groups.setdefault((rank(row), row.get('module', '')), []).append(row)
        ordered = []
        for priority in sorted({key[0] for key in groups}):
            queues = [group[:] for key, group in groups.items() if key[0] == priority]
            while any(queues):
                for group in queues:
                    if group:
                        ordered.append(group.pop(0))
        # Give every enabled module a first turn before spending on second
        # questions in focus/authority modules. Preserve priority within each pass.
        first, rest, modules = [], [], set()
        for row in ordered:
            module = row.get('module', '')
            if module not in modules:
                first.append(row)
                modules.add(module)
            else:
                rest.append(row)
        return first + rest

    @staticmethod
    def focus_supported(row, sources):
        segment = str(row.get('segment_name') or '')
        if not segment:
            return True
        terms = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z][a-zA-Z0-9_-]*', segment)
        for source in sources:
            meta = source.source_metadata or {}
            if meta.get('evidence_scope') == 'representative_company':
                continue
            if meta.get('module') != row.get('module') or meta.get('extraction_status') == 'failed':
                continue
            body = str(source.content or '')
            if len(body.strip()) >= 300 and any(term.casefold() in body.casefold() for term in terms):
                return True
        return False

    def select(self, pending, coverage, sources, intake):
        selected = []
        if self.phase_stopped:
            return selected
        missing = {str(gap).split('：', 1)[0] for gap in coverage.get('information_gaps', [])}
        target = intake.get('target_name') or intake.get('industry') or ''
        while pending and len(selected) < self.batch_size:
            row = pending.pop(0)
            self.considered_modules.add(row.get('module', ''))
            key = query_key(row, target)
            if key in self.seen:
                self.skipped['equivalent_query'] += 1
                continue
            module = row.get('module')
            confirmed_gap = self.phase == 'recovery' or row.get('gap_reason') or row.get('requirement_id')
            if not confirmed_gap and module not in missing and self.focus_supported(row, sources):
                self.skipped['archived_candidate_coverage'] += 1
                continue
            with self.lock:
                if not self.available('queries') or not self.available('search_requests'):
                    self.stop('initial_budget_reserved' if self.phase == 'initial' else 'run_budget_exhausted')
                    return selected
                self.seen.add(key)
                self.used['queries'] += 1
                selected.append(row)
                self.records.append({'query': row['query'], 'module': module, 'phase': self.phase})
        return selected

    @contextmanager
    def request_scope(self, key):
        try:
            from .web_search import search_request_budget
        except ImportError:
            from web_search import search_request_budget
        token = search_request_budget.set((self, key, self.generation))
        try:
            yield
        finally:
            search_request_budget.reset(token)

    def reserve_request(self, provider, key, timeout, expected_generation=None):
        kind = 'fetch_requests' if provider == 'page_fetch' else 'search_requests'
        with self.lock:
            if expected_generation is not None and (
                    self.phase_started is None or expected_generation != self.generation):
                raise CollectionBudgetExhausted('expired_collection_phase')
            if self.pause_requested and self.pause_requested():
                raise CollectionBudgetExhausted('collection_paused')
            if not self.available(kind):
                self.stop(kind + '_exhausted')
                raise CollectionBudgetExhausted(kind)
            if provider == 'page_fetch':
                try:
                    from .search_results import canonical_source_url
                except ImportError:
                    from search_results import canonical_source_url
                key = canonical_source_url(key)
            request_key = (provider, key)
            if provider == 'page_fetch' and self.requests[request_key] >= self.fetch_attempts_per_page:
                self.skipped['page_attempt_limit'] += 1
                raise CollectionBudgetExhausted('page_attempt_limit')
            self.used[kind] += 1
            if self.requests[request_key]:
                self.used['fetch_retries' if provider == 'page_fetch' else 'search_retries'] += 1
            self.requests[request_key] += 1
            seconds = max(.1, self.remaining_seconds())
            if isinstance(timeout, tuple):
                return tuple(min(float(value), max(.1, seconds / len(timeout))) for value in timeout)
            return min(float(timeout or 30), seconds)

    def allow_fetch(self, url):
        with self.lock:
            if url in self.fetch_seen:
                self.skipped['repeated_page_fetch'] += 1
                return False
            if not self.available('fetch_requests'):
                self.skipped['page_fetch_budget'] += 1
                return False
            self.fetch_seen.add(url)
            self.used['pages_scheduled'] += 1
            return True

    @staticmethod
    def usable_documents(sources):
        documents = set()
        for source in sources:
            meta = source.source_metadata or {}
            body = str(source.content or '').strip()
            if len(body) < 300 or meta.get('extraction_status') in {'failed', 'empty', 'fetch_timeout'}:
                continue
            if meta.get('content_origin') == 'search_summary' and meta.get('fetch_status') != 'done':
                continue
            documents.add(hashlib.sha256(body.encode()).hexdigest())
        return documents

    def batches(self, rows, search, evaluate, sources, intake, notice):
        pending = self.prioritize(rows, intake)
        modules = {row.get('module', '') for row in pending}
        while pending:
            current_sources = sources()
            before = evaluate()
            usable_before = self.usable_documents(current_sources)
            selected = self.select(pending, before, current_sources, intake)
            if not selected:
                return
            notice('开始小批次定向检索', {**dict(self.used), 'queries':len(selected),
                   'queries_used':self.used['queries'], 'phase':self.phase})
            for row, results in search(selected):
                if self.remaining_seconds() < 1:
                    self.stop('collection_time_exhausted')
                    return
                yield row, results[:self.candidate_limit]
            after_sources = sources()
            after = evaluate()
            usable_added = len(self.usable_documents(after_sources) - usable_before)
            covered = len(set(before.get('information_gaps', [])) - set(after.get('information_gaps', [])))
            self.stalled_batches = 0 if usable_added or covered else self.stalled_batches + 1
            failed_searches = sum(self.search_unavailable(row) for row in selected)
            record = {'phase':self.phase, 'queries':len(selected), 'unavailable_searches':failed_searches,
                      'new_usable_documents':usable_added,
                      'resolved_candidate_gaps':covered, 'remaining_gaps':after.get('information_gaps', [])}
            self.batch_records.append(record)
            notice('本批次采集检查完成', record)
            if self.stalled_batches >= self.stagnation_limit and modules <= self.considered_modules:
                unavailable = self.batch_records[-self.stagnation_limit:]
                reason = ('search_services_unavailable' if all(
                    batch['unavailable_searches'] == batch['queries'] for batch in unavailable)
                    else 'consecutive_batches_without_usable_gain')
                self.stop(reason)
                return
        self.stop('scheduled_questions_processed')

    @staticmethod
    def search_unavailable(row):
        if row.get('person_search_status') == 'failed':
            return True
        states = (row.get('search_result_audit') or {}).get('engine_states') or {}
        selected = [state for state in states.values() if state.get('status') != 'not_selected']
        return bool(selected) and all(state.get('status') != 'returned' for state in selected)

    def progress_text(self):
        labels = {
            'initial_budget_reserved':'前置采集额度用完，预留后续补证额度',
            'run_budget_exhausted':'本轮查询或搜索请求额度用完',
            'fetch_requests_exhausted':'网页抓取额度用完，关键词检索和服务返回原文仍可继续',
            'search_requests_exhausted':'本轮搜索服务请求额度用完',
            'collection_time_exhausted':'本轮采集时间用完',
            'two_batches_without_usable_gain':'连续两批未取得有效增量',
            'consecutive_batches_without_usable_gain':f'连续{self.stagnation_limit}批未取得有效增量',
            'search_services_unavailable':'搜索服务请求未成功，证据缺口保留',
            'scheduled_questions_processed':'计划问题已处理，未覆盖需求保留进入核验',
        }
        reason = labels.get(self.stop_reasons[-1]['reason'], '') if self.stop_reasons else '本阶段采集结束'
        return (f"{reason}；查询 {self.used['queries']}/{self.limits['queries']} 组，"
                f"搜索请求 {self.used['search_requests']}/{self.limits['search_requests']} 次，"
                f"网页抓取尝试 {self.used['fetch_requests']}/{self.limits['fetch_requests']} 次，"
                f"采集用时 {round(self.snapshot()['active_seconds'])}/{self.limits['seconds']} 秒")

    def snapshot(self):
        return {'version':VERSION, 'limits':dict(self.limits), 'initial_limits':dict(self.initial_limits),
                'settings':{'batch_size':self.batch_size,'candidates_per_query':self.candidate_limit,
                    'candidates_per_recovery_query':self.recovery_candidate_limit,
                    'queries_per_recovery_call':self.recovery_query_limit,'results_per_engine':self.per_engine,
                    'fetch_attempts_per_page':self.fetch_attempts_per_page,'stagnant_batches':self.stagnation_limit},
                'used':dict(self.used), 'active_seconds':round(self.elapsed + (
                    self.clock() - self.phase_started if self.phase_started is not None else 0), 2),
                'queries':self.records[:80], 'skipped':dict(self.skipped),
                'batches':self.batch_records[-32:], 'stop_reasons':self.stop_reasons}
