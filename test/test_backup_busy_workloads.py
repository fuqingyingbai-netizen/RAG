"""Backups must not stop active collection, chat, or knowledge ingestion."""
import importlib.util
from pathlib import Path
import sys

import pytest


spec = importlib.util.spec_from_file_location('production_backup_guard',
    Path(__file__).resolve().parents[1]/'deploy/backup-production.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


@pytest.mark.skipif(sys.platform != 'linux', reason='Real flock and service guard run on Linux')
@pytest.mark.parametrize('kind', ['research', 'assistant', 'ingestion'])
def test_busy_job_skips_before_stopping_any_service(tmp_path, monkeypatch, kind):
    (tmp_path/'.deployment-owned').touch()
    monkeypatch.setattr(backup, 'ROOT', tmp_path)
    monkeypatch.setattr(backup.os, 'geteuid', lambda: 0)
    commands = []
    def command(args, **kwargs):
        commands.append(args)
        assert args == ['systemctl', 'is-active', '--quiet', 'supermew']
        return type('Result', (), {'returncode': 0})()
    monkeypatch.setattr(backup.subprocess, 'run', command)
    observed_queries = []
    def run(args, **kwargs):
        query = args[-1]; observed_queries.append(query)
        table = {'research': 'research_projects', 'assistant': 'assistant_threads',
                 'ingestion': 'company_documents'}[kind]
        return b'1\n' if 'FROM '+table+' ' in query else b'0\n'
    monkeypatch.setattr(backup, 'run', run)
    result = backup.backup()
    assert result['status'] == 'skipped_busy' and result['workloads'][kind] == 1
    assert len(commands) == 1 and len(observed_queries) == 3
    assert "'collecting'" in observed_queries[0]
    assert list((tmp_path/'backups').iterdir()) == [tmp_path/'backups'/'.backup.lock']
