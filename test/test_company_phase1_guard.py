"""Account failures stop paid diagnostic rounds; transient failures do not."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

spec=importlib.util.spec_from_file_location('company_phase1_native',
    Path(__file__).parents[1]/'diagnostics/company_phase1_native.py')
native=importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def test_known_account_errors_stop_rounds_without_treating_400_or_429_as_auth_by_default():
    for status in (401,403):
        assert native.terminal_model_error(SimpleNamespace(status_code=status))=='model_authentication_failed'
    for body in ({'error':{'code':'Arrearage'}},{'code':'insufficient_quota'}):
        assert native.terminal_model_error(SimpleNamespace(status_code=400,body=body))=='model_account_unavailable'
    for status,code in ((400,'InvalidParameter'),(429,'rate_limit_exceeded'),(500,'InternalError')):
        assert native.terminal_model_error(SimpleNamespace(status_code=status,body={'code':code}))==''
