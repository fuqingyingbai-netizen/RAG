"""Create a local administrator without putting a password in source control."""
import argparse
import getpass
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
sys.path.insert(0, str(ROOT / 'backend'))

from auth import get_password_hash, validate_new_password
from database import SessionLocal, init_db
from models import User


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', default='admin')
    args = parser.parse_args()
    username = args.username.strip()
    if not username:
        parser.error('username cannot be empty')
    password = os.getenv('BOOTSTRAP_ADMIN_PASSWORD') or getpass.getpass('Admin password: ')
    try:
        validate_new_password(password)
    except HTTPException as error:
        parser.error(error.detail)
    init_db()
    with SessionLocal() as db:
        if db.query(User).filter(User.username == username).first():
            parser.error('Username already exists; no existing account was changed')
        db.add(User(username=username, password_hash=get_password_hash(password), role='admin'))
        db.commit()
    print(f'Administrator created: {username}')


if __name__ == '__main__':
    main()
