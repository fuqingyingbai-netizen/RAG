"""Load only the staged module in this test process, preserving live sources."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,sys
import pytest

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
metadata=json.loads((HERE/'candidate.json').read_text(encoding='utf-8'))
parser=argparse.ArgumentParser();parser.add_argument('--full',action='store_true');args=parser.parse_args()
assert hashlib.sha256((ROOT/'backend/report_agents/company_governance.py').read_bytes()).hexdigest()==metadata['base_utf8_sha256']
assert hashlib.sha256((HERE/'company_governance.py').read_bytes()).hexdigest()==metadata['candidate_utf8_sha256']


class StagedModule:
    def pytest_sessionstart(self,session):
        assert 'report_agents.company_governance' not in sys.modules,'Reject mixed module bindings.'
        import report_agents
        spec=importlib.util.spec_from_file_location('report_agents.company_governance',HERE/'company_governance.py')
        module=importlib.util.module_from_spec(spec)
        sys.modules[spec.name]=module;spec.loader.exec_module(module)
        report_agents.company_governance=module

    def pytest_sessionfinish(self,session,exitstatus):
        module=sys.modules['report_agents.company_governance']
        assert Path(module.__file__).resolve()==(HERE/'company_governance.py').resolve()
        assert module.VERSION=='company-governance-v7-literal-identifier-and-calendar-equivalence'
        assert hashlib.sha256((ROOT/'backend/report_agents/company_governance.py').read_bytes()).hexdigest()==metadata['base_utf8_sha256']
        assert hashlib.sha256((HERE/'company_governance.py').read_bytes()).hexdigest()==metadata['candidate_utf8_sha256']

targets=['test'] if args.full else ['test/test_company_governance.py','test/test_company_governance_graph_delivery.py']
raise SystemExit(pytest.main([*targets,str(HERE/'test_governance_values.py'),'-q','-p','anyio.pytest_plugin',
    '--junitxml='+str(HERE/('full.xml' if args.full else 'targeted.xml'))],plugins=[StagedModule()]))
