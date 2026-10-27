"""Offline request-option tests; never model/transport probes."""
import pytest
from person_model_transport import section_model_options


def test_glm_default_preserves_existing_request_context(monkeypatch):
    monkeypatch.delenv('PERSON_REPORT_SECTION_THINKING',raising=False)
    assert 'extra_body' not in section_model_options('glm-5.2')


@pytest.mark.parametrize('mode',['enabled','disabled'])
def test_documented_glm52_thinking_option_requires_explicit_configuration(monkeypatch,mode):
    monkeypatch.setenv('PERSON_REPORT_SECTION_THINKING',mode)
    options=section_model_options('glm-5.2')
    assert options['extra_body']=={'thinking':{'type':mode}}
    assert options['max_tokens']==8192 and 'reasoning_effort' not in options


def test_glm52_option_is_not_assumed_for_new_mandatory_thinking_models(monkeypatch):
    monkeypatch.setenv('PERSON_REPORT_SECTION_THINKING','disabled')
    assert 'extra_body' not in section_model_options('glm-5.3')


def test_invalid_explicit_option_is_rejected_before_any_call(monkeypatch):
    monkeypatch.setenv('PERSON_REPORT_SECTION_THINKING','invalid')
    with pytest.raises(ValueError,match='invalid_person_section_thinking_mode'):section_model_options('glm-5.2')
