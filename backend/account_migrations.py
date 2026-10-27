"""Versioned, additive account migration; safe to rerun on existing installations."""
import os

from sqlalchemy import inspect, text

BASE_VERSION = "20261019_invited_accounts_v1"
ROLE_VERSION = "20261019_invited_accounts_v2_roles"
SECURITY_VERSION = "20261020_account_security_v3"
PROFILE_VERSION = "20261020_account_profiles_audits_v4"
VERSION = "20261020_account_archives_v5"


def migrate_accounts(engine):
    from database import Base
    import models  # noqa: F401

    with engine.begin() as connection:
        # Serialize startup migrations across PostgreSQL workers.
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(2026101901)"))
        Base.metadata.create_all(bind=connection)
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS account_schema_versions "
            "(version VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)"
        ))
        if not connection.execute(text("SELECT version FROM account_schema_versions WHERE version=:v"), {"v": BASE_VERSION}).first():
            columns = {item["name"] for item in inspect(connection).get_columns("users")}
            additions = {
                "is_active": "BOOLEAN NOT NULL DEFAULT TRUE",
                "token_version": "INTEGER NOT NULL DEFAULT 0",
                "must_change_password": "BOOLEAN NOT NULL DEFAULT FALSE",
                "knowledge_access": "BOOLEAN NOT NULL DEFAULT FALSE",
                "last_login_at": "TIMESTAMP NULL",
            }
            for name, definition in additions.items():
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE users ADD COLUMN {name} {definition}"))
            # One-time import. Subsequent access changes are managed in the UI.
            allowed = {name.strip() for name in os.getenv("COMPANY_KNOWLEDGE_USERS", "").split(",") if name.strip()}
            for username in allowed:
                connection.execute(text("UPDATE users SET knowledge_access=TRUE WHERE username=:name"), {"name": username})
            connection.execute(text("INSERT INTO account_schema_versions (version) VALUES (:v)"), {"v": BASE_VERSION})
        if not connection.execute(text("SELECT version FROM account_schema_versions WHERE version=:v"), {"v": ROLE_VERSION}).first():
            columns = {item["name"] for item in inspect(connection).get_columns("account_invitations")}
            if "role" not in columns:
                connection.execute(text("ALTER TABLE account_invitations ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user'"))
            connection.execute(text("INSERT INTO account_schema_versions (version) VALUES (:v)"), {"v": ROLE_VERSION})
        if not connection.execute(text("SELECT version FROM account_schema_versions WHERE version=:v"), {"v": SECURITY_VERSION}).first():
            connection.execute(text("INSERT INTO account_management_lock (id, revision) VALUES (1, 0) ON CONFLICT (id) DO NOTHING"))
            connection.execute(text("INSERT INTO account_schema_versions (version) VALUES (:v)"), {"v": SECURITY_VERSION})
        if not connection.execute(text("SELECT version FROM account_schema_versions WHERE version=:v"), {"v": PROFILE_VERSION}).first():
            columns = {item["name"] for item in inspect(connection).get_columns("users")}
            for name, definition in {"display_name": "VARCHAR(100)", "notes": "TEXT"}.items():
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE users ADD COLUMN {name} {definition} NOT NULL DEFAULT ''"))
            for index in models.AccountAudit.__table__.indexes:
                index.create(bind=connection, checkfirst=True)
            connection.execute(text("INSERT INTO account_schema_versions (version) VALUES (:v)"), {"v": PROFILE_VERSION})
        if not connection.execute(text("SELECT version FROM account_schema_versions WHERE version=:v"), {"v": VERSION}).first():
            columns = {item["name"] for item in inspect(connection).get_columns("users")}
            if "archived_at" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN archived_at TIMESTAMP NULL"))
            connection.execute(text("INSERT INTO account_schema_versions (version) VALUES (:v)"), {"v": VERSION})
