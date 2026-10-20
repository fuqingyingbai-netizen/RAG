"""Account acceptance tests use temporary databases, never the application DB."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier, Event
import os
import uuid

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

import account_api as accounts
import auth
from account_migrations import migrate_accounts
from database import Base
from models import (AccountAudit, AccountInvitation, AdminActionConfirmation, AuthThrottle, User,
                    ResearchProject, ResearchArtifact, ResearchSource, ChatSession, ChatMessage)

PASSWORD = "Employee-pass-123"


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("ACCOUNT_TEST_POSTGRES") == "1" else []))
def account_engine(tmp_path, request):
    namespace = None
    if request.param == "postgresql":
        from database import engine as configured_engine
        namespace = "account_test_" + uuid.uuid4().hex
        with configured_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{namespace}"'))
        engine = create_engine(configured_engine.url, connect_args={"options": f"-csearch_path={namespace}"})
    else:
        engine = create_engine("sqlite:///" + str(tmp_path / "accounts.db"), connect_args={"check_same_thread": False, "timeout": 15})
    try:
        yield engine
    finally:
        engine.dispose()
        if namespace:
            assert namespace.startswith("account_test_") and len(namespace) == 45
            with configured_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{namespace}" CASCADE'))


@pytest.fixture
def setup(account_engine, monkeypatch):
    monkeypatch.setattr(auth, "PBKDF2_ROUNDS", 1000)
    monkeypatch.setattr(auth, "SECRET_KEY", "isolated-account-test-secret-key-123456789")
    monkeypatch.setenv("COMPANY_KNOWLEDGE_USERS", "")
    engine = account_engine
    migrate_accounts(engine)
    factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    with factory() as db:
        db.add_all([User(username="admin", role="admin", password_hash=auth.get_password_hash(PASSWORD)),
                    User(username="existing", role="user", password_hash=auth.get_password_hash(PASSWORD))])
        db.commit()
    def get_db():
        with factory() as db:
            yield db
    app = FastAPI()
    app.include_router(accounts.router)
    app.dependency_overrides[auth.get_db] = get_db
    @app.get("/business")
    def business(user=Depends(auth.get_current_user)):
        return {"username": user.username}
    @app.get("/knowledge")
    def knowledge(user=Depends(auth.get_current_user)):
        import company_knowledge as kb
        if not kb.has_access(user):
            from fastapi import HTTPException
            raise HTTPException(403)
        return {"allowed": True}
    with TestClient(app) as client:
        yield client, factory


def login(client, username="admin", password=PASSWORD):
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def invite(client, headers):
    response = client.post("/admin/invitations", headers=headers, json={})
    assert response.status_code == 201, response.text
    return response.json()


def confirmed(client, headers, action, target_id=None, password=PASSWORD):
    response = client.post('/auth/confirm-admin', headers=headers, json={
        'password': password, 'action': action, 'target_user_id': target_id,
    })
    assert response.status_code == 200, response.text
    return {**headers, 'X-Admin-Confirmation': response.json()['confirmation_token']}


def register(client, token, username="employee", **changes):
    body = {"username": username, "password": PASSWORD, "confirm_password": PASSWORD, "invitation": token}
    body.update(changes)
    return client.post("/auth/register", json=body)


def test_invitation_lifecycle_does_not_expose_secrets(setup):
    client, factory = setup
    admin = login(client)
    invitation = invite(client, admin)
    token = invitation["token"]
    assert client.post("/auth/invitations/validate", json={"invitation": "https://company.test/#invite=" + token}).status_code == 200
    rows = client.get("/admin/invitations", headers=admin).json()
    assert rows["items"][0]["status"] == "active"
    assert token not in str(rows) and "token_hash" not in str(rows)
    response = register(client, "https://company.test/#invite=" + token)
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "user"
    employee = {"Authorization": "Bearer " + response.json()["access_token"]}
    assert client.get("/business", headers=employee).status_code == 200
    assert client.get("/knowledge", headers=employee).status_code == 403
    assert register(client, token, "another").status_code == 400
    assert client.post(f'/admin/invitations/{invitation["id"]}/revoke', headers=admin).status_code == 409
    row = client.get("/admin/users?q=employee", headers=admin).json()["items"][0]
    assert row["invited_by"] == "admin" and row["invitation_id"] == invitation["id"]
    assert "password" not in str(row) .replace("must_change_password", "")
    with factory() as db:
        stored = db.scalar(select(AccountInvitation))
        assert stored.token_hash != token and len(stored.token_hash) == 64
        assert stored.used_by_id is not None
        assert token not in str([item.details for item in db.scalars(select(AccountAudit))])


def test_rejected_registrations_preserve_invitation(setup):
    client, factory = setup
    token = invite(client, login(client))["token"]
    assert register(client, token, "existing").status_code == 409
    assert register(client, token, password="short", confirm_password="short").status_code == 400
    assert register(client, token, confirm_password="different").status_code == 400
    assert register(client, token, "has space").status_code == 400
    assert register(client, token, role="admin", admin_code="anything").status_code == 422
    assert client.post("/auth/register", json={"username": "bypass", "password": PASSWORD}).status_code == 422
    with factory() as db:
        assert db.scalar(select(AccountInvitation)).used_at is None
    assert register(client, token).status_code == 200


def test_eight_character_passwords_work_for_registration_and_change(setup):
    client, _ = setup
    token = invite(client, login(client))["token"]
    for password in ("Abc1234", "abcdefgh", "12345678"):
        assert register(client, token, password=password, confirm_password=password).status_code == 400
    registered = register(client, token, password="Abcd1234", confirm_password="Abcd1234")
    assert registered.status_code == 200, registered.text
    headers = {"Authorization": "Bearer " + registered.json()["access_token"]}
    changed = client.post("/auth/change-password", headers=headers, json={
        "current_password": "Abcd1234", "new_password": "Efgh5678", "confirm_password": "Efgh5678",
    })
    assert changed.status_code == 200, changed.text
    assert client.get("/business", headers=login(client, "employee", "Efgh5678")).status_code == 200


def test_expired_revoked_and_malformed_invitations(setup):
    client, factory = setup
    admin = login(client)
    expired = invite(client, admin)
    with factory() as db:
        db.get(AccountInvitation, expired["id"]).expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    revoked = invite(client, admin)
    assert client.post(f'/admin/invitations/{revoked["id"]}/revoke', headers=admin).status_code == 200
    for value in [expired["token"], revoked["token"], "bad", "https://example.com/#invite=bad", "https://[invalid"]:
        assert register(client, value).status_code == 400
        assert client.post("/auth/invitations/validate", json={"invitation": value}).status_code == 400
    states = {row["status"] for row in client.get("/admin/invitations", headers=admin).json()["items"]}
    assert states == {"revoked"}
    with factory() as db:
        assert db.get(AccountInvitation, expired["id"]) is None
        assert db.scalar(select(AccountAudit).where(AccountAudit.action == "invitation_expired")).details["invitation_id"] == expired["id"]
    for hours in [0, 169]:
        assert client.post("/admin/invitations", json={"expires_in_hours": hours}, headers=admin).status_code == 422


def test_concurrent_registration_claims_only_one_account(setup, monkeypatch):
    client, factory = setup
    token = invite(client, login(client))["token"]
    barrier = Barrier(2)
    original = accounts.valid_invitation
    def synchronized(*args):
        value = original(*args)
        barrier.wait(timeout=10)
        return value
    monkeypatch.setattr(accounts, "valid_invitation", synchronized)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda name: register(client, token, name), ["employee1", "employee2"]))
    assert sorted(response.status_code for response in responses) == [200, 400]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(User).where(User.username.like("employee%"))) == 1
        assert db.scalar(select(func.count()).select_from(AccountAudit).where(AccountAudit.action == "invitation_used")) == 1


def test_revocation_after_validation_still_blocks_registration(setup, monkeypatch):
    client, factory = setup
    admin = login(client)
    invitation = invite(client, admin)
    checked, proceed = Event(), Event()
    original = accounts.valid_invitation
    def delayed(*args):
        value = original(*args)
        checked.set()
        assert proceed.wait(timeout=10)
        return value
    monkeypatch.setattr(accounts, "valid_invitation", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(register, client, invitation["token"])
        try:
            assert checked.wait(timeout=10)
            assert client.post(f'/admin/invitations/{invitation["id"]}/revoke', headers=admin).status_code == 200
        finally:
            proceed.set()
        assert pending.result(timeout=10).status_code == 400
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(User).where(User.username == "employee")) == 0


def test_user_management_revokes_tokens_and_preserves_data(setup):
    client, factory = setup
    admin = login(client)
    employee = login(client, "existing")
    row = client.get("/admin/users?q=existing", headers=admin).json()["items"][0]
    uid = row["id"]
    assert row["last_login_at"] is not None
    assert client.patch(f"/admin/users/{uid}", headers=admin, json={"knowledge_access": True}).status_code == 200
    assert client.get("/knowledge", headers=employee).status_code == 200
    assert client.patch(f"/admin/users/{uid}", headers=admin, json={"knowledge_access": False}).status_code == 200
    assert client.get("/knowledge", headers=employee).status_code == 403
    assert client.patch(f"/admin/users/{uid}", headers=admin, json={"is_active": False}).status_code == 200
    assert client.get("/business", headers=employee).status_code == 401
    assert client.post("/auth/login", json={"username": "existing", "password": PASSWORD}).status_code == 401
    assert client.get("/admin/users?state=disabled", headers=admin).json()["total"] == 1
    assert client.patch(f"/admin/users/{uid}", headers=admin, json={"is_active": True}).status_code == 200
    assert client.get("/business", headers=employee).status_code == 401
    assert client.get("/business", headers=login(client, "existing")).status_code == 200
    with factory() as db:
        assert db.get(User, uid) is not None


def test_password_reset_forces_change_and_invalidates_every_old_token(setup):
    client, factory = setup
    admin = login(client)
    old = login(client, "existing")
    uid = client.get("/admin/users", headers=admin).json()["items"][0]["id"]
    response = client.post(f"/admin/users/{uid}/reset-password", headers=confirmed(client, admin, 'reset_password', uid))
    temporary = response.json()["temporary_password"]
    assert client.get("/auth/me", headers=old).status_code == 401
    assert client.post("/auth/login", json={"username": "existing", "password": PASSWORD}).status_code == 401
    forced = login(client, "existing", temporary)
    assert client.get("/auth/me", headers=forced).json()["must_change_password"] is True
    denied = client.get("/business", headers=forced)
    assert denied.status_code == 403 and denied.headers["X-Password-Change-Required"] == "true"
    body = {"current_password": temporary, "new_password": "My-new-password-456", "confirm_password": "My-new-password-456"}
    assert client.post("/auth/change-password", headers=forced, json={**body, "current_password": "wrong"}).status_code == 400
    changed = client.post("/auth/change-password", headers=forced, json=body)
    assert changed.status_code == 200 and changed.json()["must_change_password"] is False
    assert client.get("/auth/me", headers=forced).status_code == 401
    assert client.get("/business", headers=login(client, "existing", body["new_password"])).status_code == 200
    with factory() as db:
        assert temporary not in str([entry.details for entry in db.scalars(select(AccountAudit))])


@pytest.mark.parametrize("method,url,body", [
    ("get", "/admin/users", None), ("get", "/admin/invitations", None),
    ("post", "/admin/invitations", {}), ("post", "/admin/invitations/1/revoke", None),
    ("patch", "/admin/users/2", {"is_active": False}), ("post", "/admin/users/2/reset-password", None),
    ("post", "/admin/users/2/promote", None),
    ("post", "/admin/users/1/demote", None),
    ("delete", "/admin/invitations/1", None),
    ("post", "/admin/users/2/archive", None), ("post", "/admin/users/2/restore", None),
    ("post", "/auth/confirm-admin", {"password": PASSWORD, "action": "promote_user", "target_user_id": 2}),
    ("get", "/admin/audits", None),
    ("patch", "/admin/users/2/profile", {"display_name": "同事", "notes": "备注"}),
])
def test_admin_endpoints_reject_anonymous_and_ordinary_users(setup, method, url, body):
    client, _ = setup
    kwargs = {"json": body} if body is not None else {}
    assert client.request(method, url, **kwargs).status_code == 401
    assert client.request(method, url, headers=login(client, "existing"), **kwargs).status_code == 403


def test_last_admin_is_protected_and_role_patch_is_forbidden(setup):
    client, _ = setup
    admin = login(client)
    assert client.patch("/admin/users/1", headers=admin, json={"is_active": False}).status_code == 409
    assert client.post("/admin/users/1/demote", headers=admin).status_code == 409
    assert client.post("/admin/users/1/reset-password", headers=admin).status_code == 409
    assert client.patch("/admin/users/2", headers=admin, json={"role": "admin"}).status_code == 422
    assert client.get("/admin/users?q=%", headers=admin).json()["total"] == 0
    assert client.get("/admin/users?page_size=1", headers=admin).json()["total"] == 1


def test_existing_schema_migrates_once_and_preserves_access(account_engine, monkeypatch):
    engine = account_engine
    with engine.begin() as db:
        db.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(100), password_hash VARCHAR(255), role VARCHAR(20), created_at TIMESTAMP)"))
        db.execute(text("INSERT INTO users VALUES (1, 'employee', 'original-hash', 'user', CURRENT_TIMESTAMP)"))
        db.execute(text("INSERT INTO users VALUES (2, 'other', 'other-hash', 'user', CURRENT_TIMESTAMP)"))
    monkeypatch.setenv("COMPANY_KNOWLEDGE_USERS", "employee")
    Base.metadata.create_all(engine)
    migrate_accounts(engine)
    with engine.begin() as db:
        row = db.execute(text("SELECT * FROM users WHERE id=1")).mappings().one()
        assert row["password_hash"] == "original-hash" and row["is_active"] and row["knowledge_access"]
        assert row["token_version"] == 0 and not row["must_change_password"]
        assert db.execute(text("SELECT knowledge_access FROM users WHERE id=2")).scalar() == 0
        db.execute(text("UPDATE users SET knowledge_access=FALSE WHERE id=1"))
    migrate_accounts(engine)
    with engine.connect() as db:
        assert db.execute(text("SELECT knowledge_access FROM users WHERE id=1")).scalar() == 0
        assert db.execute(text("SELECT COUNT(*) FROM account_schema_versions")).scalar() == 5


def test_administrator_invitation_creates_admin_without_client_role_input(setup):
    client, _ = setup
    admin = login(client)
    response = client.post("/admin/invitations", headers=confirmed(client, admin, 'create_admin_invitation'), json={"role": "admin"})
    assert response.status_code == 201
    invitation = response.json()
    validation = client.post("/auth/invitations/validate", json={"invitation": invitation["token"]})
    assert validation.json()["role"] == "admin"
    result = register(client, invitation["token"], "invited-admin", password="Abcd1234", confirm_password="Abcd1234")
    assert result.status_code == 200 and result.json()["role"] == "admin"
    new_admin = login(client, "invited-admin", "Abcd1234")
    assert client.get("/admin/users", headers=new_admin).status_code == 200
    assert register(client, invitation["token"], "another-admin").status_code == 400
    assert client.post("/admin/invitations", headers=admin, json={"role": "superadmin"}).status_code == 422


def test_promotion_is_admin_only_and_revokes_old_user_token(setup):
    client, factory = setup
    admin = login(client)
    old = login(client, "existing")
    uid = client.get("/admin/users?q=existing", headers=admin).json()["items"][0]["id"]
    client.patch(f"/admin/users/{uid}", headers=admin, json={"is_active": False})
    assert client.post(f"/admin/users/{uid}/promote", headers=admin).status_code == 409
    client.patch(f"/admin/users/{uid}", headers=admin, json={"is_active": True})
    old = login(client, "existing")
    assert client.post(f"/admin/users/{uid}/promote", headers=confirmed(client, admin, 'promote_user', uid)).status_code == 200
    assert client.get("/auth/me", headers=old).status_code == 401
    new_admin = login(client, "existing")
    assert client.get("/admin/invitations", headers=new_admin).status_code == 200
    assert client.get("/admin/users?q=existing", headers=admin).json()["total"] == 0
    assert client.post(f"/admin/users/{uid}/promote", headers=admin).status_code == 404
    with factory() as db:
        entry = db.scalar(select(AccountAudit).where(AccountAudit.action == "account_promoted"))
        assert entry.target_user_id == uid and entry.details["to_role"] == "admin"


def test_expiry_deletes_live_tokens_but_retains_history_and_registration_source(setup, monkeypatch):
    client, factory = setup
    admin = login(client)
    invitation = invite(client, admin)
    assert register(client, invitation["token"]).status_code == 200
    with factory() as db:
        db.get(AccountInvitation, invitation["id"]).expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    import account_lifecycle as lifecycle
    monkeypatch.setattr(lifecycle, "SessionLocal", factory)
    assert lifecycle.cleanup_once() == 1
    assert lifecycle.cleanup_once() == 0
    assert client.get("/admin/invitations", headers=admin).json()["total"] == 0
    assert register(client, invitation["token"], "reuse").status_code == 400
    employee = client.get("/admin/users?q=employee", headers=admin).json()["items"][0]
    assert employee["invitation_id"] == invitation["id"] and employee["invited_by"] == "admin"
    with factory() as db:
        assert db.get(AccountInvitation, invitation["id"]) is None
        archived = db.scalar(select(AccountAudit).where(AccountAudit.action == "invitation_expired"))
        assert archived.details["previous_status"] == "used"
        assert "token" not in str(archived.details) and invitation["token"] not in str(archived.details)
        original = db.scalar(select(AccountAudit).where(AccountAudit.action == "invitation_used"))
        assert original.invitation_id is None and original.details["invitation_id"] == invitation["id"]


def test_existing_v1_invites_migrate_as_ordinary_invites(account_engine, monkeypatch):
    with account_engine.begin() as db:
        db.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(100), password_hash VARCHAR(255), role VARCHAR(20), created_at TIMESTAMP, is_active BOOLEAN DEFAULT TRUE, token_version INTEGER DEFAULT 0, must_change_password BOOLEAN DEFAULT FALSE, knowledge_access BOOLEAN DEFAULT FALSE, last_login_at TIMESTAMP)"))
        db.execute(text("INSERT INTO users (id,username,password_hash,role) VALUES (1,'admin','unchanged','admin')"))
        db.execute(text("CREATE TABLE account_invitations (id INTEGER PRIMARY KEY, token_hash VARCHAR(64) UNIQUE NOT NULL, created_by_id INTEGER NOT NULL, created_at TIMESTAMP NOT NULL, expires_at TIMESTAMP NOT NULL, revoked_at TIMESTAMP, used_at TIMESTAMP, used_by_id INTEGER UNIQUE)"))
        db.execute(text("INSERT INTO account_invitations (id,token_hash,created_by_id,created_at,expires_at) VALUES (1,'existing-hash',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        db.execute(text("CREATE TABLE account_schema_versions (version VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)"))
        db.execute(text("INSERT INTO account_schema_versions (version) VALUES ('20261019_invited_accounts_v1')"))
    monkeypatch.setenv("COMPANY_KNOWLEDGE_USERS", "admin")
    migrate_accounts(account_engine)
    with account_engine.connect() as db:
        row = db.execute(text("SELECT role,token_hash FROM account_invitations WHERE id=1")).one()
        assert row.role == "user" and row.token_hash == "existing-hash"
        assert db.execute(text("SELECT knowledge_access FROM users WHERE id=1")).scalar() == 0


def test_legacy_version_zero_jwt_remains_usable_until_revoked(setup):
    client, _ = setup
    from jose import jwt
    token = jwt.encode({"sub": "existing", "exp": datetime.utcnow() + timedelta(minutes=5)}, auth.SECRET_KEY, algorithm=auth.ALGORITHM)
    headers = {"Authorization": "Bearer " + token}
    assert client.get("/business", headers=headers).status_code == 200
    admin = login(client)
    uid = client.get("/admin/users", headers=admin).json()["items"][0]["id"]
    client.patch(f"/admin/users/{uid}", headers=admin, json={"is_active": False})
    assert client.get("/business", headers=headers).status_code == 401


def test_confirmation_is_required_scoped_single_use_and_secret_free(setup):
    client, factory = setup
    admin = login(client)
    for url, body in [('/admin/users/2/reset-password', None), ('/admin/users/2/promote', None),
                      ('/admin/invitations', {'role': 'admin'})]:
        assert client.post(url, headers=admin, json=body).status_code == 403
    assert client.post('/auth/confirm-admin', headers=admin, json={
        'password': 'wrong', 'action': 'promote_user', 'target_user_id': 2,
    }).status_code == 400
    proof = confirmed(client, admin, 'reset_password', 2)
    raw = proof['X-Admin-Confirmation']
    assert client.get('/business', headers={'Authorization': 'Bearer ' + raw}).status_code == 401
    assert client.post('/admin/users/2/promote', headers=proof).status_code == 403
    assert client.post('/admin/users/2/reset-password', headers=proof).status_code == 200
    assert client.post('/admin/users/2/reset-password', headers=proof).status_code == 403
    with factory() as db:
        assert raw not in str([row.token_hash for row in db.scalars(select(AdminActionConfirmation))])
        assert raw not in str([row.details for row in db.scalars(select(AccountAudit))])


def test_confirmation_expiry_target_and_actor_version_are_enforced(setup):
    client, factory = setup
    admin = login(client)
    proof = confirmed(client, admin, 'reset_password', 999)
    assert client.post('/admin/users/2/reset-password', headers=proof).status_code == 403
    proof = confirmed(client, admin, 'promote_user', 2)
    with factory() as db:
        for row in db.scalars(select(AdminActionConfirmation)):
            row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.post('/admin/users/2/promote', headers=proof).status_code == 403
    proof = confirmed(client, admin, 'promote_user', 2)
    changed = client.post('/auth/change-password', headers=admin, json={
        'current_password': PASSWORD, 'new_password': 'New-admin-password-456', 'confirm_password': 'New-admin-password-456',
    })
    fresh = {'Authorization': 'Bearer ' + changed.json()['access_token'], 'X-Admin-Confirmation': proof['X-Admin-Confirmation']}
    assert client.post('/admin/users/2/promote', headers=fresh).status_code == 403


def test_admin_filters_demotion_disable_enable_and_reset(setup):
    client, factory = setup
    admin = login(client)
    assert client.get('/admin/users?role=admin', headers=admin).json()['items'][0]['is_self']
    old = login(client, 'existing')
    assert client.post('/admin/users/2/promote', headers=confirmed(client, admin, 'promote_user', 2)).status_code == 200
    other = login(client, 'existing')
    listing = client.get('/admin/users?role=all', headers=admin).json()
    assert listing['total'] == listing['active_admin_count'] == 2
    assert client.get('/business', headers=old).status_code == 401
    assert client.patch('/admin/users/2', headers=admin, json={'is_active': False}).status_code == 403
    assert client.patch('/admin/users/2', headers=confirmed(client, admin, 'disable_admin', 2), json={'is_active': False}).status_code == 200
    assert client.get('/admin/users', headers=other).status_code == 401
    assert client.patch('/admin/users/2', headers=confirmed(client, admin, 'enable_admin', 2), json={'is_active': True}).status_code == 200
    other = login(client, 'existing')
    response = client.post('/admin/users/2/reset-password', headers=confirmed(client, admin, 'reset_password', 2))
    assert response.status_code == 200
    assert client.get('/auth/me', headers=other).status_code == 401
    forced = login(client, 'existing', response.json()['temporary_password'])
    assert client.get('/auth/me', headers=forced).json()['must_change_password']
    assert client.post('/admin/users/2/demote', headers=confirmed(client, admin, 'demote_user', 2)).status_code == 200
    with factory() as db:
        assert db.get(User, 2).role == 'user'
        assert db.scalar(select(AccountAudit).where(AccountAudit.action == 'account_demoted')).target_user_id == 2


@pytest.mark.parametrize('action', ['demote_user', 'disable_admin'])
def test_concurrent_admin_removal_always_keeps_one_enabled_admin(setup, action):
    client, factory = setup
    first = login(client)
    assert client.post('/admin/users/2/promote', headers=confirmed(client, first, 'promote_user', 2)).status_code == 200
    second = login(client, 'existing')
    proofs = [confirmed(client, first, action, 1), confirmed(client, second, action, 2)]
    barrier = Barrier(2)
    def remove(index):
        barrier.wait(timeout=10)
        uid = index + 1
        if action == 'demote_user':
            return client.post(f'/admin/users/{uid}/demote', headers=proofs[index])
        return client.patch(f'/admin/users/{uid}', headers=proofs[index], json={'is_active': False})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(remove, [0, 1]))
    assert sorted(row.status_code for row in responses) == [200, 409]
    assert next(row for row in responses if row.status_code == 200).json()['requires_relogin']
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(User).where(User.role == 'admin', User.is_active.is_(True))) == 1


def test_login_throttle_persists_and_expires_without_revealing_accounts(setup, monkeypatch):
    client, factory = setup
    for username in ['existing', 'unknown-account']:
        codes = [client.post('/auth/login', json={'username': username, 'password': 'wrong'}).status_code for _ in range(5)]
        assert codes == [401, 401, 401, 401, 429]
    blocked = client.post('/auth/login', json={'username': 'existing', 'password': PASSWORD})
    assert blocked.status_code == 429 and 0 < int(blocked.headers['Retry-After']) <= 300
    import account_security as security
    monkeypatch.setattr(security, 'now', lambda: datetime.utcnow() + timedelta(seconds=301))
    assert client.post('/auth/login', json={'username': 'existing', 'password': PASSWORD}).status_code == 200
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AuthThrottle)) >= 3


def test_successful_login_resets_failures_and_admin_confirmation_is_limited(setup):
    client, _ = setup
    for _ in range(4):
        assert client.post('/auth/login', json={'username': 'existing', 'password': 'wrong'}).status_code == 401
    login(client, 'existing')
    assert client.post('/auth/login', json={'username': 'existing', 'password': 'wrong'}).status_code == 401
    admin = login(client)
    codes = [client.post('/auth/confirm-admin', headers=admin, json={
        'password': 'wrong', 'action': 'promote_user', 'target_user_id': 2,
    }).status_code for _ in range(5)]
    assert codes == [400, 400, 400, 400, 429]
    assert client.post('/auth/confirm-admin', headers=admin, json={
        'password': PASSWORD, 'action': 'promote_user', 'target_user_id': 2,
    }).status_code == 429


def test_disabled_admin_does_not_count_as_last_admin_backup(setup):
    client, factory = setup
    admin = login(client)
    with factory() as db:
        db.add(User(username='disabled-admin', role='admin', is_active=False, password_hash=auth.get_password_hash(PASSWORD)))
        db.commit()
    assert client.post('/admin/users/1/demote', headers=confirmed(client, admin, 'demote_user', 1)).status_code == 409


def test_ip_limit_cannot_be_bypassed_by_rotating_names_or_forwarded_headers(setup):
    client, _ = setup
    for index in range(60):
        result = client.post('/auth/login', headers={'X-Forwarded-For': f'192.0.2.{index}'}, json={
            'username': f'missing-{index}', 'password': 'wrong',
        })
        assert result.status_code == 401
    result = client.post('/auth/login', json={'username': 'admin', 'password': PASSWORD})
    assert result.status_code == 429 and int(result.headers['Retry-After']) <= 60


def test_concurrent_confirmation_replay_runs_mutation_once(setup):
    client, factory = setup
    proof = confirmed(client, login(client), 'reset_password', 2)
    barrier = Barrier(2)
    def reset(_):
        barrier.wait(timeout=10)
        return client.post('/admin/users/2/reset-password', headers=proof)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reset, [0, 1]))
    assert sorted(result.status_code for result in results) == [200, 403]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AccountAudit).where(AccountAudit.action == 'password_reset')) == 1


def test_current_password_guesses_are_limited(setup):
    client, _ = setup
    headers = login(client, 'existing')
    body = {'current_password': 'wrong', 'new_password': 'New-password-123', 'confirm_password': 'New-password-123'}
    assert [client.post('/auth/change-password', headers=headers, json=body).status_code for _ in range(5)] == [400, 400, 400, 400, 429]


def test_profile_edit_search_clear_and_existing_login_remains_valid(setup):
    client, factory = setup
    admin = login(client)
    employee = login(client, 'existing')
    with factory() as db:
        before_hash = db.get(User, 2).password_hash
    result = client.patch('/admin/users/2/profile', headers=admin, json={
        'display_name': ' 张同事 ', 'notes': ' 项目联络人\n下周复核 ',
    })
    assert result.status_code == 200 and result.json()['display_name'] == '张同事'
    for query in ['existing', '张同事', '下周复核']:
        rows = client.get('/admin/users', headers=admin, params={'q': query}).json()
        assert rows['total'] == 1
        assert rows['items'][0]['notes'] == '项目联络人\n下周复核'
    assert client.get('/business', headers=employee).status_code == 200
    assert client.patch('/admin/users/2/profile', headers=admin, json={'display_name': '张同事'}).status_code == 200
    with factory() as db:
        user = db.get(User, 2)
        assert user.password_hash == before_hash and user.token_version == 0 and user.role == 'user'
        logs = db.scalars(select(AccountAudit).where(AccountAudit.action == 'account_profile_updated')).all()
        assert len(logs) == 1 and logs[0].details == {'fields': ['display_name', 'notes']}
        assert '下周复核' not in str(logs[0].details)
    result = client.patch('/admin/users/2/profile', headers=admin, json={'display_name': '', 'notes': ''})
    assert result.status_code == 200 and result.json()['notes'] == ''
    assert client.get('/admin/users?q=张同事', headers=admin).json()['total'] == 0
    assert client.patch('/admin/users/1/profile', headers=admin, json={'display_name': '管理员姓名'}).status_code == 200
    assert client.get('/admin/users', headers=admin).status_code == 200


@pytest.mark.parametrize('body,status', [
    ({}, 400), ({'department': '部门'}, 422), ({'role': 'admin'}, 422),
    ({'display_name': None}, 422), ({'display_name': 'a' * 101}, 422),
    ({'notes': 'a' * 1001}, 422), ({'display_name': 'a\nb'}, 400), ({'notes': 'a\x00b'}, 400),
])
def test_profile_validation_does_not_modify_records_or_audit(setup, body, status):
    client, factory = setup
    assert client.patch('/admin/users/2/profile', headers=login(client), json=body).status_code == status
    with factory() as db:
        assert db.get(User, 2).display_name == '' and db.get(User, 2).notes == ''
        assert db.scalar(select(func.count()).select_from(AccountAudit)) == 0


def test_profile_search_treats_wildcards_literally_and_disabled_users_are_editable(setup):
    client, _ = setup
    admin = login(client)
    client.patch('/admin/users/2', headers=admin, json={'is_active': False})
    assert client.patch('/admin/users/2/profile', headers=admin, json={'display_name': '同事%_', 'notes': '<b>普通文本</b>'}).status_code == 200
    assert client.get('/admin/users?role=all&q=%25_', headers=admin).json()['total'] == 1
    assert client.get('/admin/users?role=all&q=不存在%25', headers=admin).json()['total'] == 0
    assert client.patch('/admin/users/999/profile', headers=admin, json={'notes': '未知'}).status_code == 404


def test_audit_filters_pagination_timezone_and_secret_redaction(setup):
    client, factory = setup
    admin = login(client)
    with factory() as db:
        db.get(User, 1).display_name = '管理者'
        db.get(User, 2).display_name = '同事'
        db.add_all([
            AccountAudit(actor_id=1, target_user_id=2, action='account_updated', created_at=datetime(2026, 10, 19, 16, 0),
                         details={'is_active': False, 'password': 'private-password', 'token': 'private-code'}),
            AccountAudit(actor_id=1, target_user_id=2, action='password_reset', created_at=datetime(2026, 10, 19, 16, 0),
                         details={'temporary_password': 'private-temporary-password'}),
            AccountAudit(actor_id=2, target_user_id=2, action='password_changed', created_at=datetime(2026, 10, 20, 16, 0), details={}),
        ])
        db.commit()
    result = client.get('/admin/audits', headers=admin, params={
        'actor': '管理者', 'target': '同事', 'start': '2026-10-20T00:00:00+08:00', 'end': '2026-10-21T00:00:00+08:00',
        'page_size': 1,
    }).json()
    assert result['total'] == 2 and len(result['items']) == 1
    assert result['items'][0]['action'] == 'password_reset'
    assert result['items'][0]['actor_username'] == 'admin' and result['items'][0]['target_name'] == '同事'
    assert 'private-' not in str(result) and 'details' not in result['items'][0]
    result = client.get('/admin/audits', headers=admin, params={'action': 'account_updated', 'actor': 'admin'}).json()
    assert result['total'] == 1 and result['items'][0]['summary'] == '账号状态：停用'
    assert client.get('/admin/audits?actor=%25', headers=admin).json()['total'] == 0
    assert client.get('/admin/audits?target=不存在', headers=admin).json()['total'] == 0
    result = client.get('/admin/audits?page=5&page_size=1', headers=admin).json()
    assert result['total'] == 3 and result['items'] == []
    assert client.get('/admin/audits?page_size=0', headers=admin).status_code == 422
    assert client.get('/admin/audits?action=unsupported', headers=admin).status_code == 400
    assert client.get('/admin/audits?start=bad', headers=admin).status_code == 422
    assert client.get('/admin/audits?start=2026-10-21T00:00:00Z&end=2026-10-20T00:00:00Z', headers=admin).status_code == 400


def test_audit_system_cleanup_archived_invitation_and_malformed_legacy_details(setup):
    client, factory = setup
    admin = login(client)
    with factory() as db:
        db.add_all([
            AccountAudit(actor_id=1, target_user_id=2, action='invitation_expired',
                         details={'invitation_id': 77, 'previous_status': 'used', 'role': 'admin', 'token_hash': 'private-digest'}),
            AccountAudit(actor_id=1, action='invitation_expired', details={'previous_status': {}, 'invitation_id': 'private-id'}),
            AccountAudit(actor_id=1, action='future_action', details={'password': 'private-password'}),
            AccountAudit(actor_id=1, action='password_changed', details=['private-legacy-detail']),
        ])
        db.commit()
    result = client.get('/admin/audits?actor=系统', headers=admin).json()
    assert result['total'] == 2
    assert all(item['is_system'] for item in result['items'])
    archived = next(item for item in result['items'] if item['invitation_id'] == 77)
    assert '#77' in archived['summary'] and '已使用' in archived['summary']
    assert archived['target_username'] == 'existing'
    assert 'private-' not in str(client.get('/admin/audits', headers=admin).json())


def test_v3_migration_adds_profiles_preserves_credentials_and_is_idempotent(account_engine, monkeypatch):
    from account_migrations import BASE_VERSION, ROLE_VERSION, SECURITY_VERSION, VERSION
    with account_engine.begin() as db:
        db.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(100), password_hash VARCHAR(255), role VARCHAR(20), created_at TIMESTAMP, is_active BOOLEAN DEFAULT TRUE, token_version INTEGER DEFAULT 0, must_change_password BOOLEAN DEFAULT FALSE, knowledge_access BOOLEAN DEFAULT FALSE, last_login_at TIMESTAMP)"))
        db.execute(text("INSERT INTO users (id,username,password_hash,role,token_version) VALUES (1,'admin','original-hash','admin',7)"))
        db.execute(text("CREATE TABLE account_schema_versions (version VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)"))
        for version in [BASE_VERSION, ROLE_VERSION, SECURITY_VERSION]:
            db.execute(text('INSERT INTO account_schema_versions (version) VALUES (:v)'), {'v': version})
    monkeypatch.setenv('COMPANY_KNOWLEDGE_USERS', 'admin')
    migrate_accounts(account_engine)
    with account_engine.begin() as db:
        row = db.execute(text('SELECT * FROM users WHERE id=1')).mappings().one()
        assert row['display_name'] == row['notes'] == ''
        assert row['password_hash'] == 'original-hash' and row['token_version'] == 7 and not row['knowledge_access']
        db.execute(text("UPDATE users SET display_name='姓名', notes='保留备注' WHERE id=1"))
    migrate_accounts(account_engine)
    with account_engine.connect() as db:
        assert db.execute(text('SELECT notes FROM users WHERE id=1')).scalar() == '保留备注'
        assert db.execute(text('SELECT COUNT(*) FROM account_schema_versions')).scalar() == 5
        assert db.execute(text('SELECT version FROM account_schema_versions WHERE version=:v'), {'v': VERSION}).scalar() == VERSION


@pytest.mark.parametrize('state', ['used', 'revoked'])
def test_delete_finished_invitation_retains_logs_attribution_and_registered_user(setup, state):
    client, factory = setup
    admin = login(client)
    invitation = invite(client, admin)
    if state == 'used':
        assert register(client, invitation['token']).status_code == 200
        employee = login(client, 'employee')
        before_user = client.get('/auth/me', headers=employee).json()
    else:
        assert client.post(f'/admin/invitations/{invitation["id"]}/revoke', headers=admin).status_code == 200
    with factory() as db:
        digest = db.get(AccountInvitation, invitation['id']).token_hash
        original_ids = set(db.scalars(select(AccountAudit.id)))
    response = client.delete(f'/admin/invitations/{invitation["id"]}', headers=admin)
    assert response.status_code == 200, response.text
    assert client.get('/admin/invitations', headers=admin).json()['total'] == 0
    assert client.delete(f'/admin/invitations/{invitation["id"]}', headers=admin).status_code == 404
    assert client.post('/auth/invitations/validate', json={'invitation': invitation['token']}).status_code == 400
    with factory() as db:
        assert db.get(AccountInvitation, invitation['id']) is None
        entries = db.scalars(select(AccountAudit)).all()
        assert original_ids < {entry.id for entry in entries}
        assert all(entry.invitation_id is None and entry.details['invitation_id'] == invitation['id'] for entry in entries)
        deletion = next(entry for entry in entries if entry.action == 'invitation_deleted')
        assert deletion.actor_id == 1 and deletion.details['previous_status'] == state
        assert deletion.details['created_by'] == 'admin' and deletion.details['performed_by'] == 'admin'
        assert invitation['token'] not in str([entry.details for entry in entries])
        assert digest not in str([entry.details for entry in entries])
    logs = client.get('/admin/audits?action=invitation_deleted', headers=admin).json()
    assert logs['total'] == 1 and not logs['items'][0]['is_system']
    assert f'#{invitation["id"]}' in logs['items'][0]['summary']
    assert ('已使用' if state == 'used' else '已撤销') in logs['items'][0]['summary']
    if state == 'used':
        assert client.get('/auth/me', headers=employee).json() == before_user
        user = next(item for item in client.get('/admin/users', headers=admin).json()['items'] if item['username'] == 'employee')
        assert user['invitation_id'] == invitation['id'] and user['invited_by'] == 'admin'
        assert logs['items'][0]['target_username'] == 'employee'


def test_active_invitation_cannot_be_deleted(setup):
    client, factory = setup
    admin = login(client)
    invitation = invite(client, admin)
    assert client.delete(f'/admin/invitations/{invitation["id"]}', headers=admin).status_code == 409
    assert client.get('/admin/invitations', headers=admin).json()['items'][0]['status'] == 'active'
    assert client.delete('/admin/invitations/999999', headers=admin).status_code == 404
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AccountAudit).where(AccountAudit.action == 'invitation_deleted')) == 0


def test_archive_restore_preserves_business_data_and_requires_separate_enable(setup):
    client, factory = setup
    admin, employee = login(client), login(client, 'existing')
    with factory() as db:
        user = db.get(User, 2)
        user.display_name, user.notes, user.knowledge_access = '张同事', '保留备注', True
        password_hash = user.password_hash
        project = ResearchProject(title='保留的任务', created_by_id=2)
        chat = ChatSession(user_id=2, session_id='archive-fixture')
        db.add_all([project, chat]); db.flush()
        db.add_all([ResearchSource(project_id=project.id, source_type='upload', content='保留资料'),
                    ResearchArtifact(project_id=project.id, artifact_type='report', title='保留报告', content='报告正文'),
                    ChatMessage(session_ref_id=chat.id, message_type='user', content='保留聊天')])
        db.commit()
        project_id = project.id
    assert client.post('/admin/users/2/archive', headers=admin).status_code == 409
    assert client.post('/admin/users/1/archive', headers=admin).status_code == 409
    assert client.post('/admin/users/999999/archive', headers=admin).status_code == 404
    assert client.post('/admin/users/2/restore', headers=admin).status_code == 409
    assert client.patch('/admin/users/2', headers=admin, json={'is_active': False}).status_code == 200
    assert client.post('/admin/users/2/archive', headers=admin).status_code == 200
    assert client.post('/admin/users/2/archive', headers=admin).status_code == 409
    for state in ['all', 'active', 'disabled']:
        assert client.get('/admin/users', headers=admin, params={'state': state}).json()['total'] == 0
    archived = client.get('/admin/users?state=archived&q=张同事', headers=admin).json()
    assert archived['total'] == 1 and archived['items'][0]['archived_at']
    assert not archived['items'][0]['is_active'] and archived['active_admin_count'] == 1
    for method, url, body in [('patch', '/admin/users/2', {'is_active': True}),
                              ('patch', '/admin/users/2', {'knowledge_access': False}),
                              ('patch', '/admin/users/2/profile', {'notes': '不应修改'}),
                              ('post', '/admin/users/2/reset-password', None),
                              ('post', '/admin/users/2/promote', None), ('post', '/admin/users/2/demote', None)]:
        assert client.request(method, url, headers=admin, **({'json': body} if body else {})).status_code == 409
    assert client.get('/business', headers=employee).status_code == 401
    assert client.post('/auth/login', json={'username': 'existing', 'password': PASSWORD}).status_code == 401
    invitation = invite(client, admin)
    assert register(client, invitation['token'], 'existing').status_code == 409
    assert client.post('/admin/users/2/restore', headers=admin).status_code == 200
    assert client.post('/admin/users/2/restore', headers=admin).status_code == 409
    assert client.get('/admin/users?state=archived', headers=admin).json()['total'] == 0
    restored = client.get('/admin/users?state=disabled', headers=admin).json()['items'][0]
    assert restored['archived_at'] is None and not restored['is_active']
    assert client.post('/auth/login', json={'username': 'existing', 'password': PASSWORD}).status_code == 401
    assert client.patch('/admin/users/2', headers=admin, json={'is_active': True}).status_code == 200
    assert client.get('/business', headers=login(client, 'existing')).status_code == 200
    assert client.get('/business', headers=employee).status_code == 401
    with factory() as db:
        user = db.get(User, 2)
        assert user.password_hash == password_hash and user.display_name == '张同事' and user.notes == '保留备注'
        assert user.knowledge_access and user.role == 'user'
        assert db.get(ResearchProject, project_id).created_by_id == 2
        assert db.scalar(select(ResearchArtifact)).content == '报告正文'
        assert db.scalar(select(ResearchSource)).content == '保留资料'
        assert db.scalar(select(ChatMessage)).content == '保留聊天'
        assert db.scalar(select(ChatSession)).user_id == 2
    for action in ['account_archived', 'account_restored']:
        logs = client.get('/admin/audits', headers=admin, params={'action': action, 'target': '张同事'}).json()
        assert logs['total'] == 1 and logs['items'][0]['actor_username'] == 'admin'


def test_disabled_admin_can_be_archived_and_restored_without_restoring_access(setup):
    client, _ = setup
    admin = login(client)
    assert client.post('/admin/users/2/promote', headers=confirmed(client, admin, 'promote_user', 2)).status_code == 200
    old = login(client, 'existing')
    assert client.patch('/admin/users/2', headers=confirmed(client, admin, 'disable_admin', 2), json={'is_active': False}).status_code == 200
    assert client.post('/admin/users/2/archive', headers=admin).status_code == 200
    assert client.get('/admin/users?role=admin', headers=admin).json()['total'] == 1
    assert client.get('/admin/users?role=admin&state=archived', headers=admin).json()['total'] == 1
    assert client.post('/admin/users/2/restore', headers=admin).status_code == 200
    assert client.get('/admin/users?role=admin', headers=admin).json()['active_admin_count'] == 1
    assert client.get('/admin/users', headers=old).status_code == 401


def test_concurrent_invitation_deletion_keeps_one_audit_event(setup):
    client, factory = setup
    admin = login(client)
    invitation = invite(client, admin)
    assert client.post(f'/admin/invitations/{invitation["id"]}/revoke', headers=admin).status_code == 200
    barrier = Barrier(2)
    def remove(_):
        barrier.wait(timeout=10)
        return client.delete(f'/admin/invitations/{invitation["id"]}', headers=admin).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(remove, range(2))) == [200, 404]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AccountAudit).where(AccountAudit.action == 'invitation_deleted')) == 1


def test_v4_migration_adds_archive_without_hiding_existing_accounts(account_engine):
    from account_migrations import VERSION
    migrate_accounts(account_engine)
    with account_engine.begin() as db:
        db.execute(text("INSERT INTO users (id,username,password_hash,role,created_at,display_name,notes) VALUES (1,'existing','original-hash','admin',CURRENT_TIMESTAMP,'姓名','原备注')"))
        db.execute(text('ALTER TABLE users DROP COLUMN archived_at'))
        db.execute(text('DELETE FROM account_schema_versions WHERE version=:v'), {'v': VERSION})
    migrate_accounts(account_engine)
    migrate_accounts(account_engine)
    with account_engine.connect() as db:
        row = db.execute(text('SELECT * FROM users WHERE id=1')).mappings().one()
        assert row['archived_at'] is None and row['display_name'] == '姓名' and row['notes'] == '原备注'
        assert row['password_hash'] == 'original-hash' and row['role'] == 'admin' and row['is_active']
        assert db.execute(text('SELECT COUNT(*) FROM account_schema_versions')).scalar() == 5


def test_archive_and_enable_race_never_reactivates_an_archived_account(setup):
    client, factory = setup
    admin = login(client)
    assert client.patch('/admin/users/2', headers=admin, json={'is_active': False}).status_code == 200
    barrier = Barrier(2)
    def change(action):
        barrier.wait(timeout=10)
        if action == 'archive':
            return client.post('/admin/users/2/archive', headers=admin).status_code
        return client.patch('/admin/users/2', headers=admin, json={'is_active': True}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(change, ['archive', 'enable'])) == [200, 409]
    with factory() as db:
        user = db.get(User, 2)
        assert bool(user.archived_at) != user.is_active
