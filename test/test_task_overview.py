"""Task views use isolated databases; no workflow or provider calls."""
from datetime import datetime, timedelta

import auth
import research_api as api
from models import ResearchArtifact, ResearchProject, ResearchSource
from test_research_recovery import recovery_api


def headers(name='recovery-owner', role='user'):
    return {'Authorization': 'Bearer ' + auth.create_access_token(name, role)}


def test_roster_uses_worker_liveness_and_permission_scoped_source_totals(recovery_api, monkeypatch):
    client, factory = recovery_api
    with factory() as db:
        db.get(ResearchProject, 1).status = 'collecting'
        db.add(ResearchProject(id=2, title='Other', status='collecting', created_by_id=2))
        db.flush()
        db.add_all([ResearchSource(project_id=pid, title='Source', source_type='web') for pid in [1, 1, 2]])
        db.commit()
    monkeypatch.setattr(api, '_is_project_running', lambda pid: pid == 2)
    data = client.get('/research/projects', headers=headers()).json()
    assert data['summary']['running'] == 0 and data['summary']['source_count'] == 2
    assert data['projects'][0]['is_running'] is False
    assert data['projects'][0]['state_label'] == '待继续'
    data = client.get('/research/projects', headers=headers('recovery-admin', 'admin')).json()
    assert data['summary']['running'] == 1 and data['summary']['source_count'] == 3
    assert next(p for p in data['projects'] if p['id'] == 2)['state_label'].startswith('进行中')
    with factory() as db:
        assert db.get(ResearchProject, 1).status == 'collecting'


def test_compact_detail_keeps_latest_types_and_full_recovery_counts(recovery_api):
    client, factory = recovery_api
    with factory() as db:
        for i in range(3, 33):
            db.add(ResearchArtifact(id=i, project_id=1, artifact_type='desktop_report', title=f'Report {i}',
                version=i, content='PRIVATE_HISTORICAL_BODY', created_at=datetime(2026, 10, 1)+timedelta(minutes=i)))
        db.add(ResearchArtifact(id=33, project_id=1, artifact_type='cleaned_facts', title='Facts', content='PRIVATE_FACTS'))
        db.add_all([ResearchSource(project_id=1, title=f'Source {i}', source_type='upload' if i % 2 else 'web',
                                  content='PRIVATE_SOURCE_BODY') for i in range(64)])
        db.commit()
    result = client.get('/research/projects/1/detail?latest_only=true', headers=headers())
    assert result.status_code == 200
    data = result.json()
    assert data['artifact_count'] == 33 and data['downloadable_artifact_count'] == 32
    assert len(data['artifacts']) == 2
    reports = [a for a in data['artifacts'] if a['artifact_type'] == 'desktop_report']
    # Order is timestamp-first, not a numeric version from a different run.
    with factory() as db:
        newest = db.query(ResearchArtifact).filter_by(artifact_type='desktop_report').order_by(
            ResearchArtifact.created_at.desc(), ResearchArtifact.version.desc(), ResearchArtifact.id.desc()).first()
        assert reports[0]['id'] == newest.id
    assert data['source_count'] == 64 and data['upload_count'] == 32
    assert len(data['sources']) == 50 and data['sources_truncated']
    assert data['recovery']['saved']['report_text_records'] == 31
    assert 'PRIVATE_' not in result.text
    # Existing callers retain the full-detail contract.
    old = client.get('/research/projects/1/detail', headers=headers()).json()
    assert len(old['artifacts']) == 33 and len(old['sources']) == 64


def test_artifact_history_is_paged_scoped_and_contains_no_bodies(recovery_api):
    client, factory = recovery_api
    with factory() as db:
        for i in range(3, 48):
            db.add(ResearchArtifact(id=i, project_id=1, artifact_type='cleaned_facts', title=f'Facts {i}',
                version=i, content='PRIVATE_BODY', created_at=datetime(2026, 10, 25)))
        db.commit()
    route = '/research/projects/1/artifact-history'
    assert client.get(route).status_code == 401
    assert client.get(route, headers=headers('recovery-other')).status_code == 403
    first = client.get(route+'?page=1&page_size=20', headers=headers()).json()
    second = client.get(route+'?page=2&page_size=20', headers=headers()).json()
    assert first['total'] == 46 and len(first['records']) == len(second['records']) == 20
    assert not ({r['id'] for r in first['records']} & {r['id'] for r in second['records']})
    assert all(not r['content'] and r['artifact_type'] != 'workflow_trace' for r in first['records'])
    assert client.get(route+'?page_size=500', headers=headers()).status_code == 422
    assert client.get(route+'?page=0', headers=headers()).status_code == 422
    assert client.get('/research/projects/999/artifact-history', headers=headers()).status_code == 404


def test_progress_exposes_actual_activity_not_the_recent_heartbeat(recovery_api):
    client, factory = recovery_api
    with factory() as db:
        trace = db.get(ResearchArtifact, 2)
        trace.artifact_metadata = {'run_id':'current-run', 'run_started_at':'2026-10-26T04:00:00Z',
                                  'last_backend_event_timestamp':'2026-10-26T04:01:00Z'}
        trace.content = '[{"heartbeat":true,"timestamp":"2026-10-26T04:10:00Z"}]'
        db.commit()
    data = client.get('/research/projects/1/progress', headers=headers()).json()
    assert data['activity']['last_backend_event_timestamp'] == '2026-10-26T04:01:00Z'
    assert data['activity']['run_id'] == 'current-run'


def test_compact_metadata_retains_user_decisions_without_sending_raw_plans(recovery_api):
    client, factory = recovery_api
    with factory() as db:
        db.get(ResearchArtifact, 1).artifact_metadata = {
            'statement_plans': {'raw':'PRIVATE_BODY'}, 'docx_export_error':'PRIVATE_ERROR',
            'delivery_status':'review_draft', 'generation_degradations':[{'message':'需要人工复核', 'original_analysis':'PRIVATE_ANALYSIS'}],
            'claim_support_review':{'valid_review_count':0, 'total_claim_count':9, 'reviews':{'raw':'PRIVATE_RESPONSE'}},
            'risk_transparency':{'version':'rubric', 'dimensions':[]}}
        db.commit()
    data = client.get('/research/projects/1/detail?latest_only=true', headers=headers()).json()
    meta = data['artifacts'][0]['metadata']
    assert meta['docx_export_error'] is True and meta['delivery_status'] == 'review_draft'
    assert meta['generation_degradations'] == [{'message':'需要人工复核'}]
    assert meta['claim_support_review']['total_claim_count'] == 9
    assert 'PRIVATE_' not in str(data)
    # Explicit body/detail callers still receive the original audit metadata.
    old = client.get('/research/projects/1/detail', headers=headers()).json()
    report = next(a for a in old['artifacts'] if a['id'] == 1)
    assert report['metadata']['statement_plans']['raw'] == 'PRIVATE_BODY'

