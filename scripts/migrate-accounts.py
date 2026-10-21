"""Inspect or apply the additive invitation/account migration without starting research services."""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import inspect, text

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "backend"))

from account_migrations import VERSION, migrate_accounts
from database import engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply migration; otherwise inspect only")
    args = parser.parse_args()
    if args.apply:
        migrate_accounts(engine)
    with engine.connect() as connection:
        inspector = inspect(connection)
        applied = inspector.has_table("account_schema_versions") and bool(connection.execute(
            text("SELECT version FROM account_schema_versions WHERE version=:v"), {"v": VERSION}).first())
        print(f"{VERSION}: {'applied' if applied else 'pending'}")
    engine.dispose()


if __name__ == "__main__":
    main()
