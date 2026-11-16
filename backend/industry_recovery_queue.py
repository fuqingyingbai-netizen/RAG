"""Run-local, auditable source processing queue. No search or model calls."""
from copy import deepcopy

VERSION = 'industry-recovery-source-queue-v1'


class RecoverySourceQueue:
    def __init__(self, run_id):
        self.run_id = run_id
        self.pending = []
        self.reserved = []
        self.staged = []
        self.processed = []
        self.excluded = {}
        self.failures = {}
        self.processed_artifacts = {}

    def enqueue(self, sources):
        seen = set(self.pending + self.reserved + self.staged + self.processed) | set(self.excluded)
        for source in sources:
            source_id = getattr(source, 'id', None)
            if isinstance(source_id, int) and source_id > 0 and source_id not in seen:
                self.pending.append(source_id)
                seen.add(source_id)

    def plan(self, active_sources, limit, preferred_modules=()):
        from industry_evidence import stored_body
        active = {s.id:s for s in active_sources}
        ready = []
        for source_id in list(self.pending):
            source = active.get(source_id)
            reason = 'outside_active_scope' if source is None else 'no_original_body' if not stored_body(source).strip() else ''
            if reason:
                self.pending.remove(source_id)
                self.excluded[source_id] = reason
            else:
                ready.append(source)
        preferred = set(preferred_modules)
        def priority(source):
            meta = getattr(source, 'source_metadata', None) or {}
            original = meta.get('fetch_status') == 'done' or meta.get('content_origin') in {'original_page','provider_raw_content','provider_text'}
            return (meta.get('module') not in preferred, not original, source.id)
        ready.sort(key=priority)
        return [ready[i:i+limit] for i in range(0,len(ready),limit)]

    def reserve(self, sources):
        assert not self.reserved
        ids = [s.id for s in sources]
        assert len(ids) == len(set(ids)) and set(ids) <= set(self.pending)
        self.pending = [i for i in self.pending if i not in set(ids)]
        self.reserved = ids

    def stage(self):
        self.staged.extend(self.reserved)
        self.reserved = []

    def defer(self, error):
        for source_id in self.reserved:
            self.failures[source_id] = {'error_type':type(error).__name__,
                'attempts':self.failures.get(source_id,{}).get('attempts',0)+1}
        self.pending.extend(self.reserved)
        self.reserved = []

    def commit(self, artifact_id):
        for source_id in self.staged:
            self.processed.append(source_id)
            self.processed_artifacts[source_id] = artifact_id
            self.failures.pop(source_id,None)
        self.staged = []

    def release(self):
        # A pause/failure before fact merge must never acknowledge those sources.
        self.pending = list(dict.fromkeys(self.staged + self.reserved + self.pending))
        self.staged = [];self.reserved = []

    def snapshot(self):
        return deepcopy({'version':VERSION,'run_id':self.run_id,
            'counts':{'pending':len(self.pending),'reserved':len(self.reserved),'staged':len(self.staged),
                'processed':len(self.processed),'excluded':len(self.excluded)},
            'pending_source_ids':self.pending,'reserved_source_ids':self.reserved,
            'staged_source_ids':self.staged,'processed_source_ids':self.processed,
            'excluded_sources':{str(k):v for k,v in self.excluded.items()},
            'processing_failures':{str(k):v for k,v in self.failures.items()},
            'processed_artifacts':{str(k):v for k,v in self.processed_artifacts.items()}})
