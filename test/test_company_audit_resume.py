import importlib.util
import json
from pathlib import Path

import pytest


def loader():
    path=Path(__file__).resolve().parents[1]/'scripts/audit_company_live.py'
    spec=importlib.util.spec_from_file_location('company_audit_resume_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.retained_project_state


def test_missing_optional_state_is_only_tolerated_for_an_explicit_interrupted_collection(tmp_path):
    load=loader()
    assert load(tmp_path,interrupted=True)=={}
    with pytest.raises(FileNotFoundError):load(tmp_path)
    assert not (tmp_path/'project-state.json').exists()


def test_existing_state_is_preserved_and_corruption_never_suppressed_by_resume(tmp_path):
    load=loader();path=tmp_path/'project-state.json'
    state={'company_professional_platform_attempts':[{'status':'no_record'}]}
    path.write_text(json.dumps(state),encoding='utf-8')
    assert load(tmp_path,interrupted=True)==state
    path.write_text('{broken',encoding='utf-8')
    with pytest.raises(json.JSONDecodeError):load(tmp_path,interrupted=True)
