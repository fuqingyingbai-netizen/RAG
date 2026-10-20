"""Bounded execution journals. Persist on the workflow thread at stage boundaries.

The journal survives restarts; the executor is still an in-process worker. A
stored running status is not a lease or evidence that a worker is alive.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from threading import Lock
from uuid import uuid4

VERSION = 'industry-run-journal-v1'
STAGES = ('init', 'planning', 'web_search', 'quality', 'cleaning', 'risk', 'report', 'proposal')
OUTPUTS = {'planning': ('research_plan',), 'quality': ('source_quality',),
           'cleaning': ('cleaned_facts',), 'risk': ('risk_assessment',),
           'report': ('desktop_report', 'report_quality_diagnostic', 'industry_claim_ledger'),
           'proposal': ('proposal',)}


def utcnow():
    # Existing workflow timestamps are naive UTC; keep this journal compatible.
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def artifact_reference(artifact, existing_ids):
    meta = artifact.artifact_metadata or {}
    return {'artifact_id': artifact.id, 'artifact_type': artifact.artifact_type,
            'version': artifact.version, 'created_at': str(artifact.created_at),
            'content_sha256': hashlib.sha256((artifact.content or '').encode()).hexdigest(),
            'usage': 'reused' if artifact.id in existing_ids else 'created',
            'pipeline_versions': {k: v for k, v in meta.items() if k in {
                'pipeline_version', 'risk_pipeline_version', 'report_pipeline_version'}},
            'delivery_status': meta.get('delivery_status'),
            'dependencies': {k: v for k, v in meta.items() if k in {
                'cleaned_artifact_id', 'risk_artifact_id', 'report_artifact_id',
                'cleaned_sha256', 'risk_sha256', 'source_fingerprint', 'intake_fingerprint',
                'reexported_from_artifact_id', 'reused_from_artifact_id'}}}


class RunJournal:
    def __init__(self, project_id, existing_ids=(), parent_run_id=None, clock=utcnow):
        self.clock = clock
        self.existing_ids = set(existing_ids)
        self.lock = Lock()
        now = clock()
        self.data = {'version': VERSION, 'run_id': str(uuid4()), 'project_id': project_id,
            'parent_run_id': parent_run_id, 'started_at': now, 'timezone': 'UTC',
            'finished_at': None, 'status': 'running', 'current_stage': 'init',
            'executor': 'in_process', 'worker_liveness': 'not_verified',
            'automatic_restart_recovery': False, 'stages': [], 'observed_event_counts': {},
            'last_backend_event_timestamp': None}
        self._start('init', now)

    def _start(self, stage, now):
        self.data['current_stage'] = stage
        self.data['stages'].append({'name': stage, 'status': 'running', 'started_at': now,
                                    'finished_at': None, 'outputs': []})

    def tag_event(self, event):
        event = {**event, 'run_id': self.data['run_id'], 'run_started_at': self.data['started_at']}
        with self.lock:
            if not event.get('heartbeat'):
                self.data['last_backend_event_timestamp'] = max(self.data['last_backend_event_timestamp'] or '',
                                                                event.get('timestamp') or self.clock())
                status = event.get('status')
                status = status if status in {'running', 'done', 'error', 'warning', 'fallback', 'skipped', 'paused'} else 'other'
                counts = self.data['observed_event_counts']
                counts[status] = counts.get(status, 0) + 1
        return event

    def checkpoint(self, stage, artifacts=(), source_count=0):
        with self.lock:
            current = self.data['stages'][-1]
            if current['name'] != stage or current['status'] != 'running':
                raise ValueError('Unexpected industry stage checkpoint')
            now = self.clock()
            current.update(status='completed', finished_at=now,
                outputs=[artifact_reference(a, self.existing_ids) for a in artifacts], source_count=source_count)
            if stage != STAGES[-1]:
                self._start(STAGES[STAGES.index(stage)+1], now)

    def finish(self, status, error_type=None):
        if status not in {'completed', 'paused', 'failed'}:
            raise ValueError('Invalid industry run status')
        with self.lock:
            self.data.update(status=status, finished_at=self.clock())
            if status != 'completed':
                self.data['stages'][-1].update(status=status, finished_at=self.data['finished_at'])
            if error_type:
                # Exception text can contain provider credentials or private source data.
                self.data['error_type'] = error_type

    def snapshot(self):
        with self.lock:
            return deepcopy(self.data)
