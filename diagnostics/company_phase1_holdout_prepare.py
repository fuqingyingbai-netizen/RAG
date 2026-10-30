"""Prepare the registered holdout's empty input state; do not collect or evaluate."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'work/company-phase1-20261028'


def main():
    registration_path = ROOT / 'deliverables/company-phase1-20261028/holdout-registration.json'
    registration = json.loads(registration_path.read_text(encoding='utf-8'))
    directory = RUN / 'baseline/holdout'
    directory.mkdir(parents=True, exist_ok=True)
    path = (directory / 'acceptance.sqlite').resolve()
    manifest_path = directory / 'manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['database']['sha256']:
            raise RuntimeError('The immutable empty holdout input has changed.')
        print('Verified existing empty holdout input; no collection or evaluation.')
        return
    if path.exists():
        raise RuntimeError('Unfinished holdout initialization needs inspection; refusing to overwrite it.')
    os.environ.update(PYTHON_DOTENV_DISABLED='1', DATABASE_URL='sqlite:///' + path.as_posix())
    sys.path.insert(0, str(ROOT / 'backend'))
    from database import Base, engine, SessionLocal
    from models import User, ResearchProject
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        user = User(username='isolated-live-acceptance', password_hash='disabled-test-account', role='user')
        db.add(user)
        db.flush()
        db.add(ResearchProject(title=registration['target_name'] + ' 背景调查报告',
                               target_name=registration['target_name'], target_type='company',
                               industry='', created_by_id=user.id))
        db.commit()
    engine.dispose()
    (directory / 'objects').mkdir(exist_ok=True)
    with zipfile.ZipFile(directory / 'native-checkpoints.zip', 'w'):
        pass
    manifest = {'kind': 'empty_registered_holdout_input_not_a_historical_sample',
                'registration_sha256': hashlib.sha256(registration_path.read_bytes()).hexdigest(),
                'target_name': registration['target_name'], 'as_of_date': registration['as_of_date'],
                'identity_is_user_input_not_verified': True,
                'database': {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()},
                'source_count': 0, 'checkpoint_count': 0, 'model_response_count': 0,
                'new_model_calls': 0, 'new_search_calls': 0,
                'collected': False, 'evaluated': False, 'report_accepted': False}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Prepared registered target only: 0 sources, 0 model responses, 0 collection/evaluation.')


if __name__ == '__main__':
    main()
