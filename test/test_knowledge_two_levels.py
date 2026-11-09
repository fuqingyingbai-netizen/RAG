"""Two canonical levels, lossless legacy migration, and old-tab compatibility."""
from company_catalog import (CONFIDENTIALITY_LABELS, CompanyDocument, CompanyProject,
    migrate_confidentiality_levels, can_read)
from test_company_workspace import setup, upload, project, stored_original


def test_sensitive_migration_preserves_files_ownership_acl_and_is_repeatable(setup):
    setup.user.role='admin'
    p=project(setup,confidentiality='secret',readers=['bob'])
    row=upload(setup,project_id=p['id']).json()
    with setup.db() as db:
        engine=db.get_bind()
        directory=db.get(CompanyProject,p['id']);doc=db.get(CompanyDocument,row['id'])
        directory.confidentiality=doc.confidentiality='confidential'
        before=(doc.object_key,doc.sha256,doc.owner_user_id,list(doc.readers),doc.visibility,doc.updated_at,directory.updated_at)
        db.commit()
    original=stored_original(setup,row['id'])
    migrate_confidentiality_levels(engine);migrate_confidentiality_levels(engine)
    with setup.db() as db:
        directory=db.get(CompanyProject,p['id']);doc=db.get(CompanyDocument,row['id'])
        assert directory.confidentiality==doc.confidentiality=='secret'
        assert (doc.object_key,doc.sha256,doc.owner_user_id,list(doc.readers),doc.visibility,doc.updated_at,directory.updated_at)==before
        setup.user.role='user'
        assert not can_read(doc,setup.user)
    assert stored_original(setup,row['id'])==original
    assert CONFIDENTIALITY_LABELS=={'internal':'内部','secret':'机密'}


def test_old_tabs_are_normalized_without_persisting_a_third_level(setup):
    setup.user.role='admin'
    p=project(setup,confidentiality='confidential')
    assert p['confidentiality']=='secret'
    row=upload(setup,confidentiality='confidential').json()
    assert row['confidentiality']=='secret' and row['confidentiality_label']=='机密'
    assert setup.client.patch('/company-knowledge/documents/'+row['id'],json={'confidentiality':'internal'}).status_code==200
    response=setup.client.patch('/company-knowledge/documents/'+row['id'],json={'confidentiality':'confidential'})
    assert response.status_code==200 and response.json()['confidentiality']=='secret'
    assert setup.client.post('/company-knowledge/projects',json={'name':'无效等级','confidentiality':'public'}).status_code==422
